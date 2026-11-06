# Executed metadata and full MovieLens 32M ingestion

**Milestone 2 completed on November 5, 2026, America/Los_Angeles.** The report
timestamps use UTC (November 6). These are actual completed runs, not estimates.

## Evidence

- [Development metadata report](2026-11-05-metadata.json): `status: completed`.
- [Full ingestion report](2026-11-05-full.json): `status: completed`.
- [Reproduction and design decisions](../../docs/ingestion.md).

The full report independently profiles the four official source CSVs, records
their published MD5 and measured SHA-256 values, then compares every canonical
source row with PostgreSQL readback. All four value digests and counts match.
All recorded primary/foreign keys and rating checks are validated. The SQL
summary agrees with the independent source counts, distinct users, and nulls.

## Observed database contents

`movielens_full`:

- Movies: **87,585**.
- Ratings: **32,000,204**, from **200,948 users**.
- Tags: **2,000,072**, from **15,848 users**; zero NULL tag values.
- Links: **87,585**; **124 NULL TMDb IDs**, zero NULL IMDb IDs, and **46,596 IMDb
  IDs beginning with zero**, preserved as text.
- Seven indexes: four primary-key indexes plus ratings movie-ID, tags
  user/movie, and tags movie-ID indexes.
- Recorded database size: **2,855,525,399 bytes** after ingestion, index creation,
  and ANALYZE. This excludes the source archive/files, WAL, and other databases.

The original `movielens` database preserves **15,424 ratings from 100 users** and
**87,585 movies**. It now also has the full tags/links metadata; the metadata
loader checked that original movies/ratings counts were unchanged. Separate
database scopes avoid replacing the sample during full ingestion.

## Actual timings and their boundaries

Full workflow elapsed time: **140.806 seconds** for this execution, including
source verification/profiling, database creation/schema setup, all loads and key
validation, complete database value verification, secondary indexes, ANALYZE,
SQL summaries, and report construction before its final write.

Per-table COPY, key rebuilding/validation, and commit times:

- Movies: **0.093 seconds**.
- Ratings: **24.691 seconds**.
- Tags: **1.799 seconds**.
- Links: **0.286 seconds**.

The ratings readback/value-digest validation alone took **49.508 seconds**.
The development metadata workflow took **8.811 seconds**. Unrounded observations
are retained in the JSON reports. These are single-run observations, not stable
throughput estimates or measured speedups.

Unlike the prior controlled sample benchmark, full ratings/tags streaming COPY
builds primary keys and validates foreign keys after copying within the same
transaction. No direct speed comparison with the earlier COPY/INSERT medians
is valid because workload size, input format, and index-maintenance strategy
differ. No alternate full-data load method was timed.

## What worked, what changed, and limits

The streaming approach processed the full ratings file without materializing
all interactions in Python. Source profiling uses bounded digest buffers and a
set of user IDs; database verification uses a server-side cursor. Tag event
identities retain repeated observations, IMDb text retains leading zeros, and
missing TMDb values remain NULL. No source rows were dropped or deduplicated.

Tests deliberately triggered duplicate ratings, missing movie references,
invalid half-star values, and post-load value corruption. The loader rejected
invalid loads, rolled back data and key changes, and detected corrupted values.
All **24 tests passed** with local database integration enabled. This includes
the prior benchmark tests and seven new ingestion database cases.

The source-value digest intentionally canonicalizes numeric types and treats
empty source fields as missing values; it does not assert byte-identical CSV
formatting or compare generated tag IDs. NULL-related metadata counts are also
checked independently. Source-file hashes retain original byte identity.

There was no failed real-data load in these two executions. A whole run is not
one database transaction: completed earlier tables remain if a later table
fails. Reports record failure/incomplete phases, and reruns refuse existing
tables rather than automatically replacing them. There is no automatic resume,
concurrent-writer handling, or distributed deployment.

## Remaining research

Milestone 3 will investigate distributions, missingness, time consistency,
sparsity, and modeling-population decisions using SQL. Successful ingestion and
validated constraints do not establish that the dataset is free of semantic
quality issues. Genre normalization, user feature tables, chronological splits,
ranking objectives, models, and evaluation remain future work.
