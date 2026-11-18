# Chronological dataset evidence — calendar_v1

These are actual dataset-construction and coverage results, not ranking metrics.
The reports use UTC timestamps on November 15, 2026. Protocol choices were
defined before model outcomes; no model was trained, selected, or tested here.

Evidence:

- [Full build](2026-11-15-calendar-v1.json), `status: completed`.
- [Read-only supplemental user audit](2026-11-15-user-coverage.json), completed.
- [Problem/statistical contract](../../docs/problem_formulation.md).
- [Reproduction and schemas](../../docs/temporal_datasets.md).

## Data and cutoff bindings

Training labels cover 2019 with features strictly before 2019-01-01; validation
labels cover 2020 with features before 2020-01-01; test labels cover 2021 with
features before 2021-01-01. The calendar windows are half-open and adjacent.
2020 has 366 days; compare models within the same partition, not different years
as though they were the same population. Positive threshold is 4.0 and the warm
history threshold is five prior ratings.

The build created `features_20190101` (25,979,507 events; 172,569 historical users;
52,588 movies), reused/revalidated `features_20200101` (27,364,974 events;
179,419 users; 59,952 movies), and created `features_20210101` (29,053,133 events;
187,950 users; 66,750 movies). Each passed the pre-cutoff feature validations.
All are separate from `public`, `clean`, and the development sample.

## Actual label/cohort coverage

**Train (2019):**

- All window ratings: **1,385,467** from **12,345 users**.
- Observed positive labels: **689,576**.
- Eligible positives: **106,496**, from **5,150 ranking users**.
- Historical catalog: **52,588 movies**; candidate counts range **29,676–52,583**.
- Eligible positives cover **15.44% of all observed positives** and **91.97% of
  observed positives from warm-history users**.
- Positive-label exclusions by ordered reason: **571,172 cold-user**,
  **2,615 sparse-user**, **9,293 no-item-history**. Another **695,891 ratings**
  are below the positive threshold. No already-seen positive exclusions occurred.

**Validation (2020):**

- All window ratings: **1,688,159** from **14,525 users**.
- Observed positive labels: **864,105**.
- Eligible positives: **137,217**, from **5,716 ranking users**.
- Historical catalog: **59,952 movies**; candidate counts **27,753–59,947**.
- Eligible positives cover **15.88% of all observed positives** and **95.48% of
  observed positives from warm-history users**.
- Positive-label exclusions: **718,190 cold-user**, **2,207 sparse-user**,
  **6,491 no-item-history**. **824,054 ratings** are below threshold.

**Test (2021):**

- All window ratings: **1,239,912** from **12,109 users**.
- Observed positive labels: **614,934**.
- Eligible positives: **126,540**, from **6,082 ranking users**.
- Historical catalog: **66,750 movies**; candidate counts **58,243–66,745**.
- Eligible positives cover **20.58% of all observed positives** and **93.55% of
  observed positives from warm-history users**.
- Positive-label exclusions: **477,686 cold-user**, **1,986 sparse-user**,
  **8,722 no-item-history**. **624,978 ratings** are below threshold.

Coverage percentages are **data retention diagnostics**, not Recall@K or model
quality. Ordered reasons are mutually exclusive; a cold user's positive can also
be a new-item positive, but is counted under cold user first. Original boolean
facts remain in the dataset for overlapping analysis. No records were deleted
from the raw/clean source.

## User denominators and selection bias

- Train: 6,850 cold, 33 sparse, and 5,462 warm users have window observations.
  Of the warm observed users, 312 have no eligible positive. There are 172,497
  warm users in history altogether, most without primary ground truth this year.
- Validation: 8,531 cold, 39 sparse, and 5,955 warm observed users; 239 warm
  observed users lack eligible positives. All warm historical users: 179,352.
- Test: 5,668 cold, 36 sparse, and 6,405 warm observed users; 323 warm observed
  users lack eligible positives. All warm historical users: 187,892.

Consequently this is a **warm-history, observed-positive, historically known-item
benchmark**, not a broad cold-start or all-user evaluation. Most positive-label
loss is due to users with no history at the fixed prediction date. Changing to
monthly/rolling anchors could alter coverage but is not silently substituted
after viewing these counts. A different protocol requires a new version and
validation-based decisions. No model-based test result has been inspected.

## Training-only sampling and integrity

Training examples: **532,480 rows** = **106,496 observed positives** plus
**425,984 sampled unobserved contrasts**, across **5,150 users**. The requested
ratio of four unknowns per positive was met for every user; no available-pool
shortfall occurred. The sampler made **436,790 uniform index proposals** and
needed zero enumeration fallbacks in this run. Dense/exhausted cases are tested.

Unknowns exclude prior seen items and all observed training-window items,
including lower ratings. They do not consult validation/test outcomes. Seed 42
is independent per user; Python version, seed, catalog fingerprint, and SQL
hashes are recorded. The sampler algorithm is in version-controlled code;
original source-file hashes remain in the ingestion reports. These labels are
not observed dislikes or calibrated probabilities.
Training event weighting follows positive frequency; it is not per-user balanced,
whereas primary ranking metrics will macro-average users.

All window-boundary, positive eligibility, negative eligibility, budget, and
ranking-user validations returned zero errors. Complete timeline reconciliation:

- Before 2019 label start: **25,979,507** ratings.
- Three label windows: **4,313,538** ratings.
- At/after 2022 test end: **1,707,159** ratings.
- Total: **32,000,204** ratings.

The initial-fitting observation view contains **27,364,974** ratings; its latest
timestamp is **1577836786**, before the 2020 validation cutoff. No 2020/2021
observations enter that view. Training batches instead bind supervised pairs to
the older pre-2019 snapshot; they cannot silently join 2020 statistics to 2019
targets.

The source is retained completely; the **1,707,159** events outside the chosen
label windows are not claimed as part of evaluation. No Recall/Precision/NDCG/
Hit Rate value has been computed and no learned model parameters exist.

## Resource observations and reproducibility

The full workflow, including two new full-scale feature snapshots, validation
reuse, label construction, sampling, audits, and database commits, took **450.050 seconds**
in this execution. Dataset tables/indexes occupied **733,593,600 bytes** when
recorded; that excludes the much larger feature histories, source databases,
WAL, and views. These are single local observations, not general throughput or
speedup claims.

The primary report contains the seven SQL files that existed during that run.
The later eighth SQL file adds the read-only supplemental user audit, recorded
with its own SQL hash and snapshot timestamp. New builds include that audit.
No historical report was overwritten to pretend the query existed earlier.

Use the documented CLI with new schema/report names. Valid matching feature
snapshots are reused; mismatched contracts or source counts are refused. The
dataset transaction is atomic, while successful feature snapshots commit
independently and survive a dataset-stage failure. Tests cover this distinction.

Final verification passed **79 tests** with PostgreSQL integration enabled.
A separate read-only check matched saved configuration/SQL hashes, dataset
summaries, and user coverage to the live database. It verified all three feature
cutoffs, nine exhaustive candidate pools, three reproduced training-user
samples, and a 64-row behavioral-only training batch. Public and clean counts
remained 32,000,204 ratings, 87,585 movies, 2,000,072 tags, and 87,585 links;
the development database still contained 15,424 ratings. These checks validate
data construction, not recommendation quality.
