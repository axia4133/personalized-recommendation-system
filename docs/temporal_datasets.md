# Milestone 5: chronological dataset runbook

The statistical contract is in [problem_formulation.md](problem_formulation.md).
This document describes implementation, reproduction, and actual data artifacts.
No models or ranking metrics are implemented by this milestone.

## Reproduce

Start Docker, activate `.venv`, and run from the repository root:

```bash
python -m src.data.build_temporal_datasets --database movielens_full \
  --config configs/temporal_protocol.json --schema datasets_calendar_v1_rerun \
  --output experiments/datasets/new-calendar-v1-run.json
```

Use a new dataset schema and report filename. Existing dataset schemas/reports
are refused. Feature schemas are different: matching, validated snapshots can
be reused. The builder checks their cutoff, recency window, shrinkage parameters,
metadata policy, database, source row count, and feature validations. A mismatch
requires a new feature schema/configuration, not silent replacement.

For each partition, the builder creates a missing feature snapshot with the
Milestone 4 builder or revalidates an existing one. These are independent atomic
feature transactions. It then creates the dataset tables in one repeatable-read
transaction, including labels, negative sampling, validation, and audit counts.
Failure inside that transaction rolls back the dataset schema but preserves
already completed feature snapshots. A post-commit reporting failure can leave a
valid schema with an incomplete report; inspect it instead of blindly deleting.

Resource settings are local to the transaction: 64 MiB work_mem per operator and
zero parallel query workers per gather. The Docker/PostgreSQL global settings
and raw/clean tables remain unchanged. Data is streamed from SQL; no full user
by catalog matrix or all-history Python dataframe is generated.

The version-one dataset schema is `datasets_calendar_v1`. It binds:

- Train -> `features_20190101`.
- Validation -> `features_20200101` (the existing Milestone 4 artifact).
- Test -> `features_20210101`.

## Objects and grains

SQL is split across `sql/splits/001_tables.sql` through `008_user_coverage.sql`.
Identifiers are composed with Psycopg Identifier; values use bound parameters.

- `partition_metadata`: one row per role, with cutoff, exclusive end, positive
  threshold, history requirement, and exact feature binding.
- `candidate_catalog`: one `(split,movie_id)` row for every historically rated
  item, plus a deterministic index and prior rating count. It never incorporates
  future-only item IDs merely because they occur in label windows.
- `label_events`: one `(split,user_id,movie_id)` source observation in each
  window, including low ratings and cold/sparse cases. Flags, genuine rating/time,
  and mutually exclusive status reasons support complete coverage accounting.
- `positive_truth`: eligible positive observed labels, with original rating/time
  and pre-cutoff history count. Binary relevance does not give five stars more
  gain than four stars in this protocol.
- `ranking_users`: users with at least one eligible positive, with positive and
  candidate counts. Models share this cohort; candidate generation does not
  depend on its outcome-conditioned membership.
- `training_examples`: genuine training positives and seeded unobserved contrasts.
  Negatives have NULL observed rating/time and explicit `sampled_unobserved`
  provenance. The primary key prevents duplicate pairs or positive/negative
  collisions. This table contains no validation/test positive labels.
- `negative_sampling_audit`: per-user requested, available, sampled, and proposal
  counts, with fallback usage. Exhausted pools are reported rather than invented.
- `historical_pairs` view: partition-tagged pre-cutoff pairs from the three frozen
  histories, supporting seen masks without copying all history a second time.
- `history_user_counts` view: partition-tagged historical user counts.
- `training_observations` view: complete pre-2020 interactions for initial
  fitting by collaborative/observed-rating methods. This is not a license to
  train on validation or test observations.

`ranking_users` includes the training role for supervised example construction.
Evaluation later uses its validation/test subsets. Neither it nor candidate
counts are scores, predictions, or ranking results.

## Training batches

```python
import psycopg
from src.features.build_sql_features import connection_options
from src.data.build_temporal_datasets import training_batch

with psycopg.connect(**connection_options("movielens_full"), autocommit=True) as conn:
    rows = training_batch(conn, "datasets_calendar_v1", limit=1000)
    if rows:
        last = rows[-1]
        next_rows = training_batch(
            conn, "datasets_calendar_v1", limit=1000,
            after=(last["user_id"], last["movie_id"]),
        )
```

Each row carries IDs, target/provenance, the train feature-schema name, and the
12 behavioral fields plus two history-availability indicators. The five optional
genre-derived fields are not returned. Keyset pagination avoids growing OFFSET
scans. Output order is deterministic; later training should implement its own
train-only shuffling with recorded seeds. No scalers, imputers, vocabulary maps,
losses, or model parameters are learned here.

## Exhaustive candidate pools

```python
from src.data.build_temporal_datasets import evaluation_candidates

with psycopg.connect(**connection_options("movielens_full"), autocommit=True) as conn:
    movie_ids = evaluation_candidates(conn, "datasets_calendar_v1", "validation", 1)
```

The requested user may have no future positive; warm-history users still get the
same historical item pool. Unknown or sub-threshold-history users get no primary
candidate pool under this version's warm-history contract. The helper does not
remove future lower ratings, future positives, or future unknowns. No evaluation
negative sample or ranked recommendation is generated. Candidate sizes vary by
user because their prior seen sets differ.

## Audits and tests

The primary report contains label status/count reconciliation, negative validity,
budget caps, initial-fitting time bound, source-timeline totals, table sizes, and
the embedded feature bindings. Dataset construction also checks that each
partition's actual snapshot context has its exact cutoff.

For an additional read-only coverage audit on an already built dataset:

```bash
python -m src.data.build_temporal_datasets --database movielens_full \
  --schema datasets_calendar_v1 --audit-existing \
  --output experiments/datasets/new-user-coverage.json
```

This verifies the stored protocol and counts cold, sparse, warm, observed-positive,
and evaluable users. It never rebuilds features, resamples, or changes the
dataset. The initial actual build report predates the added user-coverage query;
its supplemental audit is preserved separately. New builds include both.

```bash
python -m pytest -q
RECSYS_TEST_DATABASE=1 python -m pytest -q
```

Tests cover exact time-boundary ownership, future-only catalog items, minimum
history measured before prediction, candidate pools unaffected by future labels,
same-seed sampling without duplicates, exhausted/dense pool handling, training
sampler invariance to held-out targets, behavioral-only training batches,
incompatible feature binding, dataset rollback, and protected existing schemas.

## Completion checkpoint

**Milestone 5 of 10: all 6 steps complete.**

1. **3/3 substeps:** observed-positive objective, relevance threshold, metric definitions.
2. **4/4 substeps:** global windows, feature bindings, exact boundaries, source timeline.
3. **3/3 substeps:** warm-history cohort, historical catalog, exhaustive candidates.
4. **3/3 substeps:** reproducible unknown sampling, training-only exclusions, pool caps.
5. **3/3 substeps:** integration tests, behavioral training batches, dataset validations.
6. **4/4 substeps:** actual full-source build, coverage report, documentation, final checks.

The executed opt-in suite passed **79 tests**. No models or ranking metric
results are part of this milestone. See the [actual dataset evidence](../experiments/datasets/README.md)
for counts and coverage limitations.

## Files in this increment

- Configuration: `configs/temporal_protocol.json`.
- Implementation: `src/data/build_temporal_datasets.py`.
- SQL: `sql/splits/001_tables.sql`, `002_catalog.sql`, `003_label_events.sql`,
  `004_derived_sets.sql`, `005_negative_sources.sql`,
  `006_evaluation_candidates.sql`, `007_validate_and_summarize.sql`,
  and `008_user_coverage.sql`.
- Tests: `tests/test_temporal_datasets.py`.
- Evidence: `experiments/datasets/2026-11-15-calendar-v1.json`,
  `experiments/datasets/2026-11-15-user-coverage.json`,
  and `experiments/datasets/README.md`.
- Documentation: `README.md`, `data/README.md`, `docs/architecture.md`,
  `docs/schema.md`, `docs/features.md`, `docs/problem_formulation.md`,
  and this `docs/temporal_datasets.md`.

Suggested commit after review:
`feat(data): add chronological observed-positive ranking datasets`.
Milestone 6 will implement and test ranking metrics before comparing baselines.

## Limitations

The primary cohort covers only a fraction of all observed future positives,
especially because many users are cold at January 1. Reports retain full
denominators and reasons; see the actual results rather than assuming this is an
all-user benchmark. Calendar years differ, the source cohort is selected using
lifetime history, and historical observation is only an availability proxy.
Event time stands in for availability time; ingestion/revision logs are absent.

Parameters stay frozen after validation selection; only declared historical
inputs refresh at the next cutoff. Optional refitting or additional training
snapshots would be a new experiment. Explicit rating regression and alternative
negative definitions are not silently mixed into the primary ranking task.

The local prototype duplicates history/index storage across feature snapshots,
does not resume partial dataset transactions or support concurrent source
writers, and does not provide production serving. Candidate helpers are bounded
by a single user's historical catalog; Milestone 6 must batch scoring rather
than materialize every user/item combination.
