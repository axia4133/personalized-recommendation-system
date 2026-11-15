# Milestone 4: cutoff-based SQL feature snapshots

**Complete: Milestone 4 of 10, all 6 steps.**

1. **3/3 substeps:** UTC cutoff, metadata/catalog assumptions, and field-role contract.
2. **3/3 substeps:** genre splitting, missing-label handling, and fractional membership.
3. **3/3 substeps:** user statistics, frequency/recency, and chronological gaps.
4. **3/3 substeps:** movie summaries, shrinkage/popularity, and metadata indicators.
5. **3/3 substeps:** affinity/history signals, bounded pair queries, and cold/seen flags.
6. **4/4 substeps:** tests, actual builds, resource/query-plan review, and documentation.

Actual cardinalities, timings, failure details, and limitations are in the
[executed-build notes](../experiments/features/README.md). The opt-in integration
suite passes **61 tests** including hand-computed feature and future-invariance
cases. The full snapshot retained 27,364,974 events, 179,419 users, and 59,952
movies, with zero future events or validation violations.

This pipeline creates feature tables, not labels, train/validation/test splits,
models, or ranking metrics. The main preset is an **exploratory snapshot at
2020-01-01 00:00:00 UTC**. It is not a selected evaluation cutoff or a claimed
optimal date. Milestone 5 must establish the actual objective and protocol.

## Time contract and populations

Every behavioral input satisfies `rating_timestamp < cutoff_epoch`. Equality
is excluded. The recent window is `[cutoff - 90 days, cutoff)`, in UTC seconds.
All users/items with at least one prior rating are retained, including sparse
histories and low ratings. No global 20-rating user threshold is reapplied.

Each snapshot freezes its history in its own `features_*` schema, with feature
tables derived only from that frozen history. A single repeatable-read
transaction creates tables/indexes, runs validations, and commits. Failures
before commit roll back the entire schema. A process/connection failure after
commit but before report persistence can leave a valid schema with an incomplete
report; inspect and validate it rather than blindly rerunning or deleting it.
Existing schemas are refused; raw/clean tables are not
modified. Separate schemas permit later cutoffs without overwriting old ones.

Snapshot features may only predict events **at or after that snapshot cutoff**.
Joining the pre-2020 features to labels from 2019 would leak information about
those labels. Event-level training requires event-specific histories or a
properly defined sequence of snapshot/label windows. This milestone implements
neither a temporal split nor a training-label generator.

The item catalog proxy is movies with a rating before the cutoff. A movie's
first observed rating is not its release date or proof of actual availability.
Future-only and never-rated items are absent from the snapshot item tables.
Milestone 5 must decide cold-start coverage and candidate/denominator rules;
this proxy must not silently hide difficult future positives during evaluation.

The published MovieLens cohort itself was selected using total interaction
history. Time-filtering its rows does not recover excluded inactive users or
remove that source selection bias. There are no complete exposure/watch logs.
Recorded event timestamps are treated as availability times; without ingestion
or revision logs, late arrivals and historical rating edits cannot be audited.

## Static metadata limitation

MovieLens genre labels are not historically versioned. The explicit configuration
value `genre_metadata_policy: static_unversioned_assumption` acknowledges this.
Only historically observed movie IDs get genre rows, but this does not prove
their label strings were available or identical at the historical cutoff.

Behavioral fields use only pre-cutoff rating observations. Genre-derived fields
are a separate **optional static-metadata group**, not certified point-in-time
metadata. See `configs/feature_contract.json` for the pair-field whitelist and
roles. A behavioral-only model can omit that group. Using genre fields later
requires documenting the assumption and evaluating their contribution. Tags,
title text, parsed years, and external metadata are not used as features here.

## SQL stages and data dictionary

The pipeline runs `sql/features/001_history.sql` through
`009_feature_indexes.sql`, with validation in `011_validate_snapshot.sql`.

1. `history_ratings`: frozen pre-cutoff user/movie/rating/Unix-second rows. The
   primary key is `(user_id, movie_id)`; an additional
   `(user_id, rating_timestamp, movie_id)` index supports chronological access.
2. `movie_genres`: one row per `(movie_id, genre)`. LATERAL unnest splits pipes,
   surrounding spaces are stripped, repeated genre labels are coalesced, and
   empty/`(no genres listed)` tokens are omitted. The raw metadata is unchanged.
   A window COUNT records each movie's number of known genres. Missing genres
   remain explicit absence; no synthetic genre label is invented.
3. `user_features`: total/recent ratings, mean, population standard deviation and
   variance, first/last source timestamps, active UTC-day count, history age,
   recency, observed span, ratings per active day, recent ratings per day, and
   mean chronological gap. LAG partitions by user and orders by timestamp then
   movie ID. Simultaneous events have zero gap; movie ID only breaks ties and
   does not assert causal order. For one rating, population variance/stddev are
   zero and mean gap is NULL. Frequencies describe ratings, not viewing.
4. `movie_features`: counts, recent counts, mean/population variation, first/last
   observed timestamps, days since first observed rating, recency, recent share,
   log count, popularity share, tied popularity rank, percent rank, and genre
   completeness. First-observation age is **not movie release age**.
5. `user_genre_features`: rating support, fractional support, weighted mean,
   history share, centered/shrunk affinity, most recent event, and history rank.
   ROW_NUMBER breaks equal-support genre ties alphabetically for deterministic
   ordering; it is an activity rank, not a claim of favorite genre.
6. `user_history_features`: average popularity and shrunk mean of the movies the
   user rated, plus known-genre coverage. These are historical preference
   summaries, not a learned collaborative-filtering model.
7. `snapshot_context`: cutoff, recent window, smoothing parameters, database,
   global pre-cutoff mean, and history lineage. Its `source_rating_rows` counts
   the complete source for audit purposes and **includes post-cutoff rows**.
   That diagnostic count and build timestamps must never become model inputs.
8. `example_user_item_features`: a bounded example grid of the first active user
   IDs and highest-count historical movies. This deliberately biased demo is
   not training data, sampled negatives, a representative candidate set, or an
   evaluation. It contains seen flags rather than observed future labels.

Primary/foreign keys enforce the derived table grains. CTAS stages keep SQL
logic in separate reviewable files. ANALYZE updates planner statistics. Python
only handles configuration, orchestration, bounded pair requests, and reports;
all substantive feature computation stays in PostgreSQL.

## Feature formulas

For movie `i`, historical count `n_i`, historical mean `mu_i`, global historical
mean `mu`, and configured prior count `m = 20`:

```text
shrunk_mean_i = (n_i * mu_i + m * mu) / (n_i + m)
popularity_share_i = n_i / total_historical_ratings
```

This is a rating-summary shrinkage feature with a hand-chosen pseudocount, not
a tuned model or a guaranteed performance improvement. All means/counts use
the same pre-cutoff history. RANK orders counts descending with shared ranks
for ties; PERCENT_RANK orders counts ascending and returns zero for an entirely
tied/single-item population.

For a rated movie with `G_i` known genres, assign weight `1 / G_i` to each genre.
For user `u` and genre `g`, with historical user mean `mu_u`:

```text
support_ug = sum(1 / G_i)
weighted_mean_ug = sum(r_ui / G_i) / support_ug
history_share_ug = support_ug / user_rating_count
centered_affinity_ug = sum((r_ui - mu_u) / G_i) / (support_ug + 5)
```

Fractional weights prevent a multi-genre movie from multiplying a user's total
activity. Their sum equals the number of history ratings on movies with known
genres, not necessarily all ratings. Centering reduces the effect of users'
different rating baselines; the prior shrinks low-support affinity toward zero.
This treats stars as numerical values for descriptive features; it is not an
inference about unobserved preferences.

User-item genre affinity averages the user's centered affinities over the
candidate's known genres, assigning neutral zero to unobserved genre affinity.
Coverage fields distinguish missing support from evidence of neutrality.
Relative popularity divides candidate historical count by the average historical
movie count among movies the user rated. The rating-bias gap is candidate
shrunk mean minus historical user mean, not a trained rating prediction.

## Bounded user-item queries and backoffs

`010_user_item_features.sql` reads JSON pair requests and joins only snapshot
tables. It does not inspect future raw ratings to decide whether a pair is seen.
The helper accepts 1..10,000 positive integer pairs; duplicate **requests** are
coalesced, without deduplicating source events.

```python
import psycopg
from src.features.build_sql_features import connection_options, fetch_pair_features

with psycopg.connect(**connection_options("movielens_full"), autocommit=True) as conn:
    rows = fetch_pair_features(conn, "features_20200101", [(1, 1), (1, 2)])
```

The output has 23 fields, grouped in `configs/feature_contract.json`:
identifiers, history-availability indicators, eligibility flags, 12 behavioral
features, and five optional genre features. No full user/catalog matrix is
materialized. Callers may batch larger requests; retrieval/ranking is later work.

- Cold user: count/recent activity zero, mean falls back to the snapshot global
  historical mean, stddev zero, recency and relative popularity NULL. The
  history-availability flag preserves the difference from an observed user.
- No item history: historical counts/share zero, means use the global historical
  mean as a neutral fallback, and observed-catalog eligibility is false.
- Missing genres: affinity/coverage zero with known-genre count zero. Not a
  negative preference label.
- Previously rated pair: marked seen and ineligible under this exploratory
  unseen-item policy. Seen/eligibility flags are selection diagnostics, not
  learned predictors or labels.

Any later learned imputation, scaling, vocabulary selection, or feature
selection must be fitted using training data only. These backoffs are explicit
snapshot rules, not learned transformations fitted on validation/test outcomes.

## Build and reproduce

Start Docker, activate `.venv`, and run from the repository root:

```bash
python -m src.features.build_sql_features --database movielens_full \
  --config configs/features.json --schema features_20200101_rerun \
  --output experiments/features/new-pre2020-run.json
```

Use a new schema and report path. The current full preset uses serial query
execution and 64 MiB work_mem per operator, scoped to its transaction. Multiple
operators still use more than 64 MiB total. No global database or Docker resource
settings are changed. Index maintenance may use separate maintenance workers.

`configs/features_smoke.json` builds a tiny pre-1996 snapshot on the same full
source, useful for a low-cardinality smoke test. It is not the 100-user
development sample and is not representative of recommendation performance.

The report embeds the actual configuration, cutoff parameters, SQL hashes,
source snapshot time, cardinalities, validation results, table/index sizes,
stage timings, pair-example counts, and EXPLAIN ANALYZE/BUFFERS plans when enabled.
Reports with `status: failed` are not usable snapshots. Whole-build time includes
setup, validation, examples, and commit; stage times may also include ANALYZE and
the lookup plan inspections, not just CTAS/index creation.

## Validation and performance interpretation

Automated validation reconciles source history counts with snapshot rows and
user/item totals, rejects future source timestamps and invalid feature ranges,
checks popularity shares sum to one, and verifies fractional genre mass per
user. Tests use exact hand-computed examples, cutoff ties, recent-window edges,
cold histories, absent genres, duplicate requests, complete rollback, and adding
or modifying future ratings. The future-invariance test excludes context's
audit-only full-source count because that count is deliberately not a feature.

SQL EXPLAIN ANALYZE/BUFFERS compares the same bounded user-history lookup before
and after the snapshot indexes. Those are single observations with order/cache
effects, not a controlled speedup study. Small tables may correctly retain a
sequential scan. Query workers are disabled locally after the observed Docker
shared-memory failure described in the experiment notes; that is a reliability
choice, not evidence of a general performance optimization.

```bash
python -m pytest -q
RECSYS_TEST_DATABASE=1 python -m pytest -q
```

## Remaining limitations

The static genre assumption, conservative historical catalog, published cohort
selection, timestamp resolution, missing exposure logs, numerical rating
assumption, and NULL handling remain explicit limitations. Each snapshot stores
its own historical interactions/indexes and consumes disk; this local prototype
does not implement incremental updates, snapshot garbage collection, concurrent
source mutation, a feature server, or production-scale serving. Floating-point
aggregates may differ at tiny rounding levels across plans/platforms; validation
uses documented tolerances. No model quality or ranking improvement is claimed.

## Files in this increment

- Configuration/contracts: `configs/features.json`, `configs/features_smoke.json`,
  `configs/feature_contract.json`.
- SQL: `sql/features/001_history.sql`, `002_history_indexes.sql`,
  `003_movie_genres.sql`, `004_user_features.sql`, `005_movie_features.sql`,
  `006_user_genre_features.sql`, `007_user_history_features.sql`,
  `008_snapshot_context.sql`, `009_feature_indexes.sql`,
  `010_user_item_features.sql`, and `011_validate_snapshot.sql`.
- Implementation/tests: `src/features/build_sql_features.py`,
  `tests/test_sql_features.py`.
- Evidence: `experiments/features/2026-11-14-smoke.json`,
  `2026-11-14-full.json`, `2026-11-14-full-serial.json`, and the feature experiment
  `README.md` in that directory.
- Documentation: root `README.md`, `data/README.md`, `docs/schema.md`,
  `docs/architecture.md`, and this `docs/features.md`.
