# MovieLens relational schema

**Status:** Milestone 2 complete. `movielens_full` contains 32,000,204 ratings (200,948 users), 87,585 movies, 2,000,072 tags, and 87,585 links. Complete canonical source/database value digests, SQL summaries, and constraints passed. Development database `movielens` retains 15,424 ratings from 100 users plus the full movie/tag/link metadata. The databases share one PostgreSQL container. See `docs/ingestion.md` for reproduction and scope.

Source files (downloaded and checksum-verified GroupLens MovieLens CSVs):

- `movies.csv` — `movieId`, `title`, `genres`
- `ratings.csv` — `userId`, `movieId`, `rating`, `timestamp`
- `tags.csv` — `userId`, `movieId`, `tag`, `timestamp`
- `links.csv` — `movieId`, `imdbId`, `tmdbId`

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

The validated primary key verified user-movie uniqueness during full ingestion. No duplicate pair was silently dropped or arbitrarily resolved. Source-to-database value digests also match for the complete ratings file.

**Foreign key:** `movie_id → movies(movie_id)`

`user_id` is not a foreign key until we optionally add a `users` table.

## `tags`

One row per source tag event. Implemented in `003_tags.sql`:

- `tag_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY`: generated event identifier, not a source field.
- `user_id INTEGER NOT NULL`: no user foreign key; metadata users need not appear in the development ratings sample.
- `movie_id INTEGER NOT NULL REFERENCES movies(movie_id)`.
- `tag TEXT`: preserve source text, including commas, quotes, Unicode, and newlines. Nullable until missingness is investigated; the current full source has zero NULL tags.
- `tag_timestamp BIGINT NOT NULL`: Unix seconds.

A user can apply multiple tags to a movie, and repeated observations are retained.
The `(user_id, movie_id)` pair is not a tag primary key. No uniqueness rule over
tag text/time is imposed without evidence. Generated `tag_id` order retains the
COPY source order for complete value-digest verification.

## `links`

One row per source movie mapping. Implemented in `004_links.sql`:

- `movie_id INTEGER PRIMARY KEY REFERENCES movies(movie_id)`.
- `imdb_id TEXT`: preserve leading zeros; 46,596 loaded IDs start with zero.
- `tmdb_id INTEGER`: nullable; 124 source mappings have no TMDb ID.

These are external identifiers, not movie features by themselves. No external
metadata API requests were made.

## Indexes and load transactions

Primary keys create indexes on movies/links movie IDs, ratings
`(user_id, movie_id)`, and tags `tag_id`. `005_ingestion_indexes.sql` additionally
indexes ratings `movie_id`, tags `(user_id, movie_id)`, and tags `movie_id`.
The ratings composite key already supports queries beginning with user ID.
Additional time-based indexes should follow actual split/feature query plans.

For the large ratings/tags COPY operations, primary/foreign keys are deferred
inside a single table transaction and rebuilt/validated before commit. Checks
and NOT NULL remain active. Failure rolls back both data and constraint changes.
This is only done on fresh targets; existing development ratings are preserved.
There are no unvalidated constraints in the completed databases.

## Deferred tables

| Table | Intent | When |
|---|---|---|
| `users` | `user_id` primary key, populated from distinct ids in ratings (and later tags). Enables `ratings.user_id` FK. | After first ratings load, if we want stricter integrity. |
| `movie_genres` | PK `(movie_id, genre)`, FK to `movies`. One row per genre label. | After `movies` ingest is validated. |

## Load order

1. Create movies, ratings, tags, and links schemas in dependency order.
2. Load movies first; all other tables reference movies.
3. Load and validate ratings, tags, and links.
4. Add ingestion indexes, ANALYZE, and verify complete values and SQL summaries.
5. Users and normalized movie genres remain deferred.

## Out of scope for this document

- Chronological train/validation/test split tables
- Feature tables (must use only train-available rows; leakage is a later milestone)
- Implemented DDL lives in `sql/schema/`
