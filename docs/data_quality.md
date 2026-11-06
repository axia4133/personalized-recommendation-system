# Milestone 3: SQL quality analysis and validated source views

**Complete: Milestone 3 of 10, all 6 steps.** Executed November 5, 2026,
America/Los_Angeles (UTC report timestamps fall on November 6).

1. **2/2 substeps:** full-data scope/configuration and consistent audit snapshot.
2. **3/3 substeps:** missingness/value checks, duplicate identities, and references.
3. **2/2 substeps:** user/movie activity and reconciled sparsity distributions.
4. **3/3 substeps:** time bounds, source ordering, and calendar-boundary follow-up.
5. **3/3 substeps:** cleaning contract, validated views, and measured exclusions.
6. **3/3 substeps:** adversarial tests, documented evidence/decisions, and final verification.

The audited database is `movielens_full`; `movielens` remains the development
database. Raw counts are 32,000,204 ratings, 200,948 rating users, 87,585 movies,
2,000,072 tags, and 87,585 links. Primary ingestion provenance is in the completed
Milestone 2 report; this audit does not reload or alter source records.

## Reproduction and outputs

From the repository root with the virtual environment activated and Docker up:

```bash
python src/data/run_data_quality.py --database movielens_full \
  --create-clean-views --output experiments/quality/new-reviewed-run.json
```

Use a new report path; existing reports are refused. Omit `--create-clean-views`
for diagnostics only. The flag atomically creates/replaces the project's four
`clean` views; it never updates or deletes raw tables. Reapplying the same view
definitions is supported. Reports record parameters, query SHA-256 hashes,
execution durations, environment, snapshot, findings, and exact exclusion counts.

The runner uses one UTC, repeatable-read, read-only transaction for all audit
queries, with a 15-minute timeout per statement. View installation is a separate
transaction that checks the raw population did not change. Run against a static
local snapshot; concurrent source writers are not supported. Matching row counts
alone would not establish absence of same-count updates by another writer.

Current evidence: [final results](../experiments/quality/2026-11-05-full-final.json).
The [initial audit](../experiments/quality/2026-11-05-full.json) is retained as
genuine intermediate evidence, with its original timestamp query archived in
`experiments/quality/initial_timestamp_query.sql` and hash-verified. The reviewed
run clarifies the calendar-boundary interpretation and adds a focused follow-up;
it does not change which records are retained.

The final run also broadens blank-field checks to POSIX whitespace, including
tabs/newlines rather than just spaces. Its aggregate findings match the reviewed
run. `experiments/quality/initial_core_query.sql` retains the exact earlier
space-only query with a matching hash, so reports are never silently rewritten.

`configs/data_quality.json` fixes the user-history diagnostic at 20, sparse-movie
threshold at fewer than 5 ratings, and source-order diagnostic at the first 100
user IDs. These are not training eligibility rules. Calendar bounds interpret
the publisher's dates as UTC; the timezone of the publisher's date labels is not
established. This distinction matters for the timestamp finding below.

The SQL is in `sql/validation/010_core_quality.sql` through
`014_timestamp_boundary_review.sql`. Files use Psycopg named parameters from the
configuration, so execute them through the runner rather than pasting unbound
placeholders into psql. No Pandas processing is used.

## Missingness and technical validity

Observed:

- Zero NULL/blank titles, NULL/blank genre strings, nonpositive movie IDs, or
  missing/nonpositive required rating/tag identifiers.
- Zero NULL ratings, out-of-range ratings, non-half-star values, NULL timestamps,
  or negative timestamps in ratings/tags.
- Zero NULL/blank tag strings and no malformed or blank IMDb IDs.
- **7,080 movies** have the explicit `(no genres listed)` label. This is semantic
  missing genre information, even though the field is not NULL.
- **124 links** have missing TMDb IDs; other external IDs are not invented.

The rating distribution spans all ten allowed values. Full counts by half-star
are in the report and sum to exactly 32,000,204. The most frequent observed value
is 4.0 (8,367,654 ratings). This describes observed ratings, not exposure or the
distribution of preferences for every catalog movie.

## Duplicate observations and relational integrity

- Zero repeated rating `(user_id, movie_id)` groups, repeated movie IDs, or
  repeated link movie IDs. SQL checks independently corroborate the raw keys.
- Zero exactly repeated tag `(user_id, movie_id, tag, tag_timestamp)` groups.
  Generated tag IDs are excluded from that duplicate definition.
- Zero rating/tag/link records without a movie. Every movie has a links row,
  and every full-data tag user has at least one rating.
- **198 exact-title groups**, with **203 additional rows** across those groups.
  Movie identity is not determined by title, so these are not automatically
  duplicate movie records.
- **36 reused TMDb-ID groups**, with **36 additional mappings**. No reused IMDb
  IDs were found. External mappings may need further entity-resolution review;
  this audit does not establish why those TMDb IDs are reused.

## Activity and sparsity

User activity:

- 200,948 rating users; minimum **20**, median **73**, maximum **33,332** ratings.
- Mean **159.25** ratings, substantially above the median.
- Discrete percentiles: 25th **36**, 75th **167**, 90th **364**, 95th **571**,
  and 99th **1,290**.
- Zero users below the 20-rating diagnostic. This does not guarantee 20 events
  before a future prediction cutoff. The source itself selected users with at
  least 20 total ratings, which limits generalization to new/inactive users.

Movie activity, including the entire metadata catalog through LEFT JOIN:

- **84,432 movies** have ratings; **3,153** have zero observed ratings.
- Median **5**, mean **365.36**, maximum **102,929** ratings.
- Discrete percentiles: 25th **2**, 75th **23**, 90th **230**, 95th **1,007**,
  and 99th **8,882**.
- **43,701 movies** have fewer than 5 ratings, including zero-rated movies:
  **49.90% of the catalog**. The 40,548 movies with 1–4 ratings account for
  **78,737 ratings**, or **0.2461% of observed rating events**.

The complete bin distributions are retained in JSON. Binned user/movie rating
totals reconcile to the raw count, and movie bins reconcile to the full catalog.
Observed rating density is approximately **0.1818%** of all user/catalog pairs.
This is observation sparsity, not an estimate of how many movies users disliked,
watched, or were exposed to.

## Timestamp investigation

Actual UTC ranges:

- Ratings: **1995-01-09 11:46:44** through **2023-10-13 02:29:07**.
- Tags: **2005-12-24 13:00:10** through **2023-10-12 23:56:23**.
- No events precede the chosen January 9, 1995 UTC reference start.

The README describes activity through October 12, 2023, while **108 ratings from
36 users** occur on October 13 UTC, between **00:00:34 and 02:29:07**. All are
within the following UTC day; none is a day or more beyond the chosen boundary.
These records matched the official source during full ingestion.

All 108 would still fall on October 12 in the illustrative America/Chicago
timezone; the latest becomes 21:29:07. That is consistent with a calendar-date
timezone explanation, but does **not prove** which timezone the publisher used.
The epoch timestamps themselves are UTC. Retain the records and track the
documentation ambiguity rather than declare them corrupt or force timestamps
back into the stated date range. The reviewed year histogram includes all valid
2023 events; calendar conversion guards do not act as population filters.

In the first 100 user IDs only, **7,528 of 15,324 adjacent pairs** decrease in
timestamp when ordered by movie ID. This is a scoped diagnostic over 15,424
ratings, not a random sample or a full-dataset rate. It confirms that movie-ID
order is unsuitable for chronological histories. LAG compares each row with the
previous movie-ID-ordered rating within its user partition.

**46 users** have all their observed ratings at a single timestamp. This may
reflect batch entry or timestamp resolution; it is not sufficient evidence of
bad data. Future temporal splits must explicitly handle equal timestamps.

## Cleaning contract and consequences

`sql/cleaning/001_validated_views.sql` creates a `clean` schema with four ordinary
views. It does not copy 32 million rows, cache aggregates, normalize tag text,
parse release years, impute external identifiers, or invent user attributes.

- `clean.movies`: require a positive movie ID; preserve optional metadata.
- `clean.ratings`: require positive user/movie IDs, a matching retained movie,
  a non-NULL 0.5–5.0 half-star rating, and a non-NULL nonnegative Unix timestamp.
- `clean.tags`: require positive identifiers, a matching retained movie, and a
  nonnegative timestamp; retain repeated events and optional text unchanged.
- `clean.links`: retain mappings for retained movies, preserving NULL external
  IDs and IMDb leading zeros. Mapping collisions remain flagged, not merged.

No history threshold, popularity cutoff, rating-positivity threshold, or
interpreted calendar-window filter is applied. Current technical rules exclude
**zero rows from every table**: clean ratings remain **32,000,204**, movies
**87,585**, tags **2,000,072**, and links **87,585**. Raw tables are unchanged.

Why retain the findings:

- Removing genre-missing or external-ID-missing movies would change catalog
  coverage for optional metadata, without making their interactions invalid.
- A five-rating item cutoff would remove nearly half the catalog, even though it
  removes only 0.2461% of interactions. That can hide cold/sparse-item difficulty.
- Reused titles/TMDb mappings do not justify merging user interactions without
  entity-resolution evidence. Such merges could also create duplicate pairs.
- Zero-rated catalog items are not negative labels; candidate availability and
  cold-start policy belong to the recommendation protocol.
- Identical timestamps do not establish false events. Preserve chronology
  uncertainty and define tie handling later.

The validated base views are **not a finalized training cohort** and do not mean
the dataset is semantically error-free. Any future exclusion needs a new
versioned rule with measured consequences. No failed exclusion or unsupported
improvement is claimed.

## Testing and limitations

```bash
python -m pytest -q
RECSYS_TEST_DATABASE=1 python -m pytest -q
```

The executed suite passes **36 tests** including local PostgreSQL integration.
Quality fixtures deliberately omit storage constraints to prove the SQL detects
defects, rather than merely retesting that constraints already rejected them.
Tests cover invalid values/nulls, duplicate identity definitions, orphan records,
catalog movies with no ratings, density denominators, exclusive time bounds,
the scoped order check, retained sparse histories/missing metadata/repeated tags,
idempotent view recreation, reconciliations, and protected existing reports.

Whole-history aggregates and activity thresholds are diagnostic only. They
include future interactions and must never be reused as training features or
prediction-time eligibility. Metadata timestamps/availability and candidate-set
construction still require leakage analysis. No chronological split, feature
pipeline, model, or evaluation experiment has been implemented here.

The audit examines defined technical checks and selected metadata collisions;
it cannot establish true viewing/exposure, verify all titles, resolve film
identity, detect every bot, or prove rating sincerity. PostgreSQL planner row
estimates are not treated as measured counts. Dataset/source hashes were
verified in ingestion; the audit records its database snapshot and SQL hashes,
not a new byte-for-byte export. Recorded query times are single local execution
observations, not optimization results.

## Files in this increment

- Configuration: `configs/data_quality.json`.
- Current SQL checks: `sql/validation/010_core_quality.sql`,
  `011_duplicates_and_references.sql`, `012_activity_and_sparsity.sql`,
  `013_timestamp_diagnostics.sql`, `014_timestamp_boundary_review.sql`.
- Cleaned dataset definition: `sql/cleaning/001_validated_views.sql`.
- Runner and tests: `src/data/run_data_quality.py`, `tests/test_data_quality.py`.
- Actual evidence: `experiments/quality/2026-11-05-full.json`,
  `2026-11-05-full-reviewed.json`, `2026-11-05-full-final.json`,
  `initial_timestamp_query.sql`, `initial_core_query.sql`, and `README.md` in
  that same quality directory.
- Documentation: root `README.md`, `data/README.md`, `docs/architecture.md`,
  `docs/ingestion.md`, `docs/schema.md`, and this `docs/data_quality.md`.
