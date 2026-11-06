# MovieLens ingestion runbook

Milestone 2 covers the relational schema, source verification, a working sample,
an ingestion-method benchmark, metadata, and full ingestion. Data quality
investigation and modeling population exclusions are Milestone 3; no cleaning
or model evaluation is performed by this pipeline.

**Completed:** all 7 Milestone 2 steps. Step 6 (metadata) completed its schema,
load, and verification substeps; Step 7 (full ingestion) completed resource/source
verification, full loads/keys, complete value validation, and documentation.
Observed counts/timings are in [the executed full-load report](../experiments/ingestion/full-load.md).

## Databases and scope

Both databases use the same local PostgreSQL 16 Docker service and named volume.

- `movielens`: the existing development database. Its ratings table contains the
  100-user development sample. Its movies, tags, and links contain full source
  metadata. Consequently, tags include users outside the sample ratings users.
- `movielens_full`: isolated full dataset. The loader does not replace, rename,
  truncate, or delete the development tables.

The Docker health check tests the service, not the ingestion completion status.
Only a report with `status: completed` means all loads and validations passed.
After a failed or interrupted run, a database can contain previously committed
tables or empty tables; it must not be presented as a completed full ingestion.

## Session setup

From `~/repos/personalized-recommendation-system`, start Docker Desktop, then:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
docker compose up -d
docker compose exec -T postgres pg_isready -U recsys -d movielens
```

Follow `data/README.md` for the authoritative download, extracted file layout,
license, and checksum verification. Keep all CSVs and archives out of Git.
The Python loader resolves default input/schema paths from its own file location.
Connection defaults match Docker Compose; `PGHOST`, `PGPORT`, `PGUSER`, and
`PGPASSWORD` can override them. The explicit `--database` selects the target.
The local database role must have CREATE DATABASE privilege for full mode.

## Development metadata load

Use this only after movies and the development ratings sample are loaded, and
before `tags` or `links` exists:

```bash
python src/data/ingest_movielens.py --scope metadata --database movielens \
  --output experiments/ingestion/metadata-new-run.json
```

This profiles and verifies tags/links, applies `003_tags.sql` and `004_links.sql`,
loads them without discarding duplicate events, validates every source value,
adds the ingestion indexes, and checks that original movie/rating counts remain
unchanged. It does not filter global tags to the 100 sampled ratings users.

## Full load into a new database

For first-time reproduction, when `movielens_full` does not exist or has an empty
public schema:

```bash
python src/data/ingest_movielens.py --scope full --database movielens_full \
  --output experiments/ingestion/full-new-run.json
```

Use a new report filename each time. Existing reports and target tables are
refused. To retry after investigating a failure, choose a new explicitly named
database and report; the loader does not automatically drop a failed database.
It does not resume partial runs or silently skip existing rows.

The pipeline:

1. Reads all selected source files, checks their headers, compares MD5 values
   with the published 32M hashes, records SHA-256, counts complete CSV records,
   and computes canonical source-value digests. It does not use line counts,
   since quoted tag text can include newlines.
2. Creates the database if necessary and refuses nonempty targets. Applies
   `001_movies.sql` through `004_links.sql` using the intended final constraints.
3. Streams each CSV into PostgreSQL using COPY, with bounded 1 MiB input blocks.
   Each table uses one atomic load transaction.
4. For ratings/tags only, removes their primary/foreign keys inside that load
   transaction, performs COPY, then rebuilds primary keys and validates foreign
   keys before committing. NOT NULL and rating CHECK rules remain active.
   Invalid duplicates/references fail the transaction; no row is dropped or
   arbitrarily chosen. This avoids retaining millions of per-row FK trigger
   events during a single COPY and builds large indexes using PostgreSQL's bulk
   index build. It is not the same table/index timing protocol as the sample
   benchmark, so its timings must not be compared as a controlled experiment.
5. Reads every stored source column back through a server-side cursor in batches
   of 10,000, using deterministic order, and compares canonical value digests and
   record counts. No full ratings dataframe or list is materialized in memory.
6. Builds `005_ingestion_indexes.sql`, runs ANALYZE, checks the reusable SQL
   summary against independent source counts/nulls/users, verifies constraints
   are validated, and records observed database size, indexes, and timings.

## What lossless validation means

The source and database both pass through Python's CSV writer with identical
quoting and encoding to produce the value digests. CSV quoting and file line
endings are not themselves data values. Empty CSV fields map to SQL NULL using
COPY's default CSV semantics. IDs/timestamps are normalized to integers, ratings
to exact Decimal values, while titles, genres, tags, and IMDb IDs remain text.
IMDb leading zeros and UTF-8 content are preserved. There is no deduplication.

Movies/links use movie-ID order; ratings use `(user_id, movie_id)` order, checked
against source ordering. Tags use generated `tag_id` order, which retains COPY's
source event order. The generated ID is not a MovieLens field. It preserves
repeated tags and is excluded from the source-value comparison.

Digest equality verifies every canonical source value up to cryptographic hash
collision risk; byte-level MD5/SHA-256 also identify the original input files.
Generated IDs, row storage order, and raw CSV formatting are not compared.

## Read-only verification

```bash
docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 -U recsys \
  -d movielens_full < sql/validation/001_ingestion_summary.sql
docker compose exec -T postgres psql -X -U recsys -d movielens_full \
  -c '\dt'
```

The same summary can target `movielens` to inspect the preserved development
database. Checksums, per-table exact-value comparisons, constraints, counts, and
database sizes are retained in `experiments/ingestion/*metadata.json` and
`*full.json` for the actual executed runs.

## Tests and limits

```bash
python -m pytest -q
RECSYS_TEST_DATABASE=1 python -m pytest -q
```

The opt-in tests create uniquely named disposable test databases and remove only
those databases afterward. They exercise repeated tag events, embedded text,
missing external IDs, leading zeros, large timestamps, post-load corruption,
constraint restoration, and rollback for duplicate ratings, orphan references,
and invalid half-star ratings. Benchmark integration tests still use their
separate benchmark table; run tests and ingestion sequentially.

Limitations: local single-machine ingestion, no concurrent writers or automatic
resume, no distributed processing, and no production deployment. Full-source
profiling retains only distinct user IDs and small digest buffers in memory.
Index builds can spill to disk, and WAL/database/index files require more space
than the source CSVs. Recorded ingestion times include key rebuilding and commit;
whole-run time also includes source and database validation. No general speedup
claim follows from those timings.

Movie genres remain in their original string; normalization is deferred. No
separate users table exists, so there are no user foreign keys. A future users
table must consider both ratings and tags. Metadata is not automatically a
leakage-safe historical feature; as-of availability is a later modeling decision.
