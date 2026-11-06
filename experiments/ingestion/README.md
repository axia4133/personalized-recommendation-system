# Development-sample ingestion benchmark

**Status: executed on November 5, 2026 (America/Los_Angeles).** Milestone 2,
step 5 of 7, substeps 5 and 6 completed. UTC timestamps are in the result JSON.

## Question and decision

Compare multi-row parameterized INSERT against Psycopg text COPY using
`write_row`, starting from identical parsed, typed, in-memory ratings.
This supports the choice of COPY for bulk ingestion; it does not measure model
quality or establish full-dataset throughput.

## Configuration and controls

- Input: `data/processed/ratings_dev.csv`, 15,424 ratings from 100 users.
- Sample selection: first 100 users in source order, with complete histories;
  not a random or representative evaluation sample.
- INSERT batch size: 1,000 (16 statements, final batch of 424).
- COPY: one COPY operation, rows supplied through `write_row`, not streamed
  directly from the raw CSV. Python values are integers and Decimal ratings.
- One excluded warm-up per method, then three measured runs per method.
- Measured order: INSERT/COPY, COPY/INSERT, INSERT/COPY. This partly controls
  order effects but is not a perfectly balanced or randomized experiment.
- Each trial uses a freshly created ordinary table with the ratings schema,
  primary-key index, NOT NULL rules, rating checks, and movie foreign key.
- Both methods perform the entire load in one explicit transaction.
- Timer: `time.perf_counter`, immediately before BEGIN until after COMMIT.
- Included: Python loader/parameter construction, transfer, database execution,
  constraint/index maintenance, and commit.
- Excluded: CSV parsing/type conversion, sorting, connection, table setup,
  validation, and cleanup. No per-batch progress queries run inside the timer.
- Connection uses autocommit outside explicit transaction blocks so validation
  cannot accidentally leave an implicit transaction open before a load.
- PostgreSQL 16.15; Python 3.13.13; Psycopg 3.3.6; local macOS ARM64 client
  connected to Docker PostgreSQL. `fsync`, `synchronous_commit`, and
  `full_page_writes` were all on. Full environment and input SHA-256 are recorded.

## Actual results

Raw configuration, all warm-up/measured timings, validation outcomes, and
unrounded summary values: [2026-11-05-local.json](2026-11-05-local.json).

- INSERT measured seconds: 0.242634, 0.205157, 0.182460.
  Median: **0.205157 seconds**, approximately 75,181 rows/second.
- COPY measured seconds: 0.053001, 0.067119, 0.069952.
  Median: **0.067119 seconds**, approximately 229,801 rows/second.
- Ratio of median times: `0.20515712499945948 / 0.06711891699887929`,
  approximately **3.06**. COPY had lower elapsed time in this experiment.

Each of the eight trials (two warm-ups and six measurements) read back every
row after commit and compared all four values against the sorted source sample.
The original tables retained 87,585 movies and 15,424 ratings, and the benchmark
table was removed. No raw ratings or credentials are saved in the report.

## Interpretation and limitations

The evidence supports retaining COPY as the bulk-loading method. It does not
justify multiplying these timings to predict the duration of a 32M-row load.
The input is small, memory-resident, and non-random; larger tables may change
index, foreign-key lookup, WAL, checkpoint, and storage costs substantially.
Warm-ups deliberately exercise caches; these are not cold-start measurements.
Three observations per method give a descriptive comparison, not a robust
uncertainty estimate or a claim of statistical significance. Other local
processes and Docker resource limits were not controlled or fully recorded.
Only one batch size and one COPY implementation were compared.

Failure tests cover rejected ratings, incorrect expected output, partial INSERT
batches, and a pre-existing benchmark table. Cleanup runs on normal exceptions;
a killed process or lost database connection can still leave a benchmark table.
The script refuses to overwrite it rather than silently deleting it.

## Reproduce

From the repository root, activate `.venv`, start Docker/PostgreSQL, and follow
`data/README.md` to create the schema, load movies, and generate the sample.
Install pinned dependencies with `python -m pip install -r requirements.txt`.
No second load into the original ratings table is necessary for this benchmark.

```bash
python src/data/benchmark_ingestion.py --method both \
  --batch-size 1000 --warmups 1 --repeats 3 \
  --output experiments/ingestion/local-rerun.json
```

Use a new report filename for each execution. Existing output files and existing
`public.ratings_ingestion_benchmark` tables are not overwritten. The script is
intended for this small sample; it materializes the input and validation rows in
memory. Do not point it at the full ratings CSV.

Tests:

```bash
# Unit tests; PostgreSQL integration tests are explicitly skipped.
python -m pytest -q

# Includes tests that create, populate, and clean up the benchmark table.
RECSYS_TEST_DATABASE=1 python -m pytest -q
```

The executed suite passed **13 tests**, including six local database integration
cases. `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, and `PGPASSWORD` can override
local connection defaults. Run integration tests and benchmarks sequentially;
they intentionally use the same isolated table name.

## Learning and remaining questions

The implemented INSERT loader preserves batching and parameterized values.
The comparison holds transaction count and table rules fixed, measures through
commit, and keeps correctness validation outside the timed region. Temporary
tables were useful practice but were replaced by ordinary tables before timing.

Remaining questions: How does COPY behave on the full ratings load? How much do
index and foreign-key maintenance contribute at that size? Those measurements
remain planned for the next ingestion tasks.
