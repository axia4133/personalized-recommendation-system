# Intended relational schema

**Status:** Tables `movies` and `ratings` have been created locally. Rating constraints passed tests with temporary data that was rolled back. PostgreSQL now contains 87,585 movies and 15,424 development-sample ratings from 100 users. Loaded values were compared with the source CSVs; no sampled ratings reference missing movies. Full ratings ingestion and other tables remain planned.

Source files (downloaded and checksum-verified GroupLens MovieLens CSVs):

- `movies.csv` — `movieId`, `title`, `genres`
- `ratings.csv` — `userId`, `movieId`, `rating`, `timestamp`

CSV headers stay in camelCase on disk. PostgreSQL columns use `snake_case`.

## Design principles

- IDs (`user_id`, `movie_id`) are **nominal labels**, not quantities. We do not average them.
- A primary key uniquely identifies a **row**, not the slice we happen to analyze. Queries can still `GROUP BY` user or movie regardless of the PK.
- Keep source-faithful columns where a transformation would be lossy (especially genres).
- Implemented foreign keys and `CHECK` constraints enforce movie references and valid rating values during ingestion.

## `movies`

One row per movie. Parent table; no foreign keys.

| Column | Type (intent) | Source | Notes |
|---|---|---|---|
| `movie_id` | `INTEGER` | `movieId` | Primary key. Unique movie identifier. |
| `title` | `TEXT` | `title` | Variable-length titles. Often includes a year in the string, e.g. `Toy Story (1995)`. We do **not** parse year at first ingest. |
| `genres_raw` | `TEXT` | `genres` | Original pipe-separated string, e.g. `Adventure\|Animation\|Children\|Comedy\|Fantasy`. Kept for audit and to compare against any later split table. |

**Primary key:** `movie_id`

**Genres approach (both):**

- Keep `genres_raw` on `movies` so the source string is never thrown away.
- Later, add `movie_genres` with one row per `(movie_id, genre)` so joins, `GROUP BY genre`, and genre-affinity features are straightforward SQL.

A movie can belong to multiple genres, so a single `TEXT` column is the wrong grain for those queries. The split table is deferred until core ingest of `movies` and `ratings` works.

## `ratings`

One row per observed rating event. MovieLens timestamps are Unix seconds (seconds since 1970-01-01 UTC). Ratings are half-star values from 0.5 to 5.0, **not** integers.

| Column | Type (intent) | Source | Notes |
|---|---|---|---|
| `user_id` | `INTEGER` | `userId` | Nominal user label. MovieLens has no `users.csv`; users are inferred from this column. |
| `movie_id` | `INTEGER` | `movieId` | Must reference `movies.movie_id`. |
| `rating` | `NUMERIC` | `rating` | Range enforced by `CHECK (rating BETWEEN 0.5 AND 5.0)`. Half-star increments enforced by `CHECK (MOD(rating * 2, 1) = 0)`. |
| `rating_timestamp` | `BIGINT` | `timestamp` | Unix seconds as stored in the file. A `TIMESTAMPTZ` view or column can be added later for readable time splits. Named `rating_timestamp` so it is not confused with Postgres `TIMESTAMP` type syntax. |

**Primary key:** `(user_id, movie_id)` — composite.

- Many rows per user (a user rates many movies).
- Many rows per movie (many users rate it).
- At most one row per user–movie pair. `user_id` alone or `movie_id` alone cannot be the PK.

We will **verify** uniqueness on ingest. Duplicate pairs, if any, are a data-quality finding, not something to drop silently.

**Foreign key:** `movie_id → movies(movie_id)`

`user_id` is not a foreign key until we optionally add a `users` table.

## Deferred tables (not in first DDL)

| Table | Intent | When |
|---|---|---|
| `users` | `user_id` primary key, populated from distinct ids in ratings (and later tags). Enables `ratings.user_id` FK. | After first ratings load, if we want stricter integrity. |
| `movie_genres` | PK `(movie_id, genre)`, FK to `movies`. One row per genre label. | After `movies` ingest is validated. |
| `tags` | User-applied tags: `user_id`, `movie_id`, `tag`, timestamp. | Not required for the first ranking baseline. |
| `links` | `movie_id` plus IMDb/TMDb ids. | Optional metadata; not required for first ingest. |

## Load order

1. Create `movies` (no dependencies).
2. Load movies.
3. Create `ratings` with FK to `movies`.
4. Load ratings.
5. Optionally derive `users` and `movie_genres`.

## Out of scope for this document

- Chronological train/validation/test split tables
- Feature tables (must use only train-available rows; leakage is a later milestone)
- Implemented DDL lives in `sql/schema/`
