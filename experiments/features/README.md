# Executed SQL feature builds

These are feature-engineering execution reports, not model experiments or
ranking results. Executed November 14, 2026 in America/Los_Angeles; UTC timestamps
fall on November 15. Reports are retained without rewriting failed attempts.

## Runs and outcomes

1. [Pre-1996 smoke](2026-11-14-smoke.json): completed. Four historical ratings,
   two users, four movies, ten movie/genre rows, seven user/genre rows, and eight
   example pairs. This tiny early-date subset of the full source is a functional
   test, not the 100-user development sample or a representative evaluation.
2. [First pre-2020 attempt](2026-11-14-full.json): **failed**, at
   `007_user_history_features.sql` with PostgreSQL `DiskFull`. The exception was
   inability to resize a POSIX shared-memory segment, not exhaustion of ordinary
   database storage. Inspection showed Docker `/dev/shm` limited to 64 MiB, about
   420 GiB free on the database-volume filesystem, and a default of two parallel
   query workers per gather. The entire new schema rolled back; the smoke schema
   and original datasets remained available. Partial stage timings were not
   returned by the failed transaction and are not invented here.
3. [Pre-2020 retry](2026-11-14-full-serial.json): **completed** after setting
   `max_parallel_workers_per_gather=0` inside the build transaction. `work_mem`
   was 64 MiB per operator; maintenance workers remained at their separate default
   of two. No global server settings or container resource configuration changed.
   Current presets include the local resource setting; the historical smoke and
   failed reports retain their original configurations without that setting.

## Actual successful pre-2020 results

Schema: `movielens_full.features_20200101`. Exclusive cutoff:
**2020-01-01 00:00:00 UTC**. This is an exploratory cutoff, not a chosen
train/validation/test protocol.

- Frozen ratings: **27,364,974** of the 32,000,204 clean source observations.
  The **4,635,230** at/after cutoff do not enter behavioral feature statistics.
- Active historical users: **179,419**; observed historical movies: **59,952**.
- Normalized movie/genre rows: **103,695**.
- User/genre rows: **2,935,497**.
- User-history summaries: **179,419**.
- Retained users with one prior rating: **25**; no arbitrary minimum-history
  filter was applied. Their mean-gap feature is NULL and population variance zero.
- Movies without known genres: **4,657**. They retain their behavioral features.
- Users with no known-genre history: **zero** for this run; that edge case is
  covered by tests and does not cause users to be removed.
- Example pair rows: **1,000**, including **291 already-rated** and **709 eligible**
  under the exploratory observed-catalog/unseen-item policy. These are not labels
  or an evaluation candidate set.
- Latest source timestamp in the snapshot: **1577836786**, strictly before
  cutoff **1577836800**.
- Zero future-history rows, invalid user/movie/genre/affinity rows, or per-user
  fractional genre-weight mismatches. User/movie count totals reconcile exactly
  to historical ratings. Popularity shares sum to one within floating tolerance.

All eight physical tables, including indexes, occupied **3,605,774,336 bytes**
when measured after commit. The history table and its two indexes dominate
storage. This figure excludes raw/clean sources, the smoke schema, WAL, and other
databases. Multiple snapshots therefore have a real disk cost.

Successful workflow elapsed time: **145.800 seconds** on this execution.
Observed stage times, including any stage-specific ANALYZE/plan inspection:

- Frozen history and baseline lookup plan: 17.236 seconds.
- History primary/time indexes and after-index plan: 11.842 seconds.
- Genre normalization: 2.197 seconds.
- User aggregates/chronological gaps: 17.200 seconds.
- Movie summaries/popularity/shrinkage: 6.110 seconds.
- User/genre weighted affinities: 53.124 seconds.
- User historical item/genre coverage: 10.334 seconds.
- Snapshot context: 11.837 seconds.
- Derived-table keys: 1.301 seconds.

The remainder includes post-stage ANALYZE, validations, bounded examples, commit,
and report collection. These are single local execution observations, not
benchmarked speedups or predictions of production throughput.

## Query plans

The same bounded chronological history lookup was inspected with EXPLAIN
ANALYZE/BUFFERS before and after history indexes:

- Full snapshot before indexes: sequential scan plus sort; recorded execution
  **586.835 ms**.
- Full snapshot after indexes: index scan; recorded execution **0.059 ms**.
- Smoke snapshot: sequential scan plus sort both times, appropriate for four rows.

Raw plan trees and buffer observations are saved in each successful JSON report.
The order/cache effects and single observations prevent a controlled speedup
claim. The useful evidence is the supported access path, not a generalized ratio.
Disabling parallel query workers fixed the observed shared-memory failure; it is
not evidence that serial execution is generally faster.

## Validation, assumptions, and interpretation

The SQL validates strict cutoff exclusion, population reconciliation, ranges,
popularity mass, and fractional genre support. Hand-computed database fixtures
test formulas and missing histories. A future-perturbation test changes/adds
at-or-after-cutoff ratings, rebuilds at the same cutoff, and verifies feature
tables are unchanged. Failed validation removes the entire new schema through
transaction rollback; existing schemas are never replaced.

Genre labels remain static unversioned metadata. The optional genre group needs
that assumption; interaction cutoff tests cannot verify historical metadata
availability. The complete-source count in context is audit metadata, not a
predictor. Full-history quality diagnostics from Milestone 3 are not reused as
features. Item observation is a conservative catalog proxy, not exposure evidence.

No numerical rating target, positivity threshold, negative sampling, temporal
train/validation/test assignment, model fitting, ranking metric, or neural
architecture is implemented. The example pair grid is deliberately biased toward
popular historical items and low user IDs. It must not be used to report model
quality or candidate coverage. Source-selection bias and missing exposure logs
remain dataset limitations.

See [the feature contract, formulas, and runbook](../../docs/features.md) and
`configs/feature_contract.json`. Reproduction requires a new `features_*` schema
and report path. Actual configurations and SQL hashes are embedded in the reports.
