# Milestone 5: observed-positive ranking protocol

## Primary question

At a fixed prediction cutoff, rank historically observed movies that a user has
not previously rated, to recover movies they will **rate at least 4.0 during the
following calendar-year window**. This is observed-positive rating prediction,
not numerical rating regression, a watch prediction, or a complete preference
model. Ratings and unobserved items are not exposure logs.

MovieLens does not tell us which movies were shown, watched without rating, or
available through a service. Offline ranking metrics cannot estimate online
click-through, causal impact, or true preference recall. Numerical rating
prediction could be a separately defined secondary experiment; no RMSE or
regression model is implemented here.

## Frozen version-one choices

`configs/temporal_protocol.json` specifies the protocol before model results:

- Positive relevance: observed rating **>= 4.0**. Lower observed values remain
  recorded but are not positive under this binary relevance definition.
- User cohort: **at least five ratings strictly before the prediction cutoff**.
  This is a warm-history use case, not a claim that five is universally optimal.
- Item catalog: items with at least one rating by any user strictly before the
  cutoff. No post-cutoff popularity or future item appearance enters the catalog.
- Candidate pool: that complete historical catalog minus **all** the user's
  pre-cutoff rated items, regardless of their rating values.
- Training contrast: four sampled unobserved items per eligible positive,
  capped by available pool size, with seed 42 and per-user stable randomness.
- Primary future ranking metrics: Recall@10/20 and NDCG@10/20; additionally
  Precision@10/20 and Hit Rate@10/20. Metrics/models belong to Milestone 6 and
  have not yet been executed.
- Default pair feature group is behavioral only. The optional static-genre
  group still requires the Milestone 4 metadata assumption and is disabled by
  default; any later inclusion must be a documented experiment.

Thresholds, dates, and sampling ratio are protocol choices, not optimized
parameters or evidence of better performance. Revisit choices with validation
experiments, not test-score feedback; version changed protocols explicitly.

## Global chronological ownership

All bounds are UTC. Feature events satisfy `timestamp < cutoff`; label events
satisfy `cutoff <= timestamp < label_end`:

- **Train:** features before 2019-01-01; labels during 2019, ending 2020-01-01.
- **Validation:** features before 2020-01-01; labels during 2020, ending 2021-01-01.
- **Test:** features before 2021-01-01; labels during 2021, ending 2022-01-01.

The pre-2020 snapshot existed as an exploratory feature artifact. It is now
explicitly assigned to validation, rather than retrospectively treated as
features for training labels that occurred before it. The other two snapshots
are built and validated with their respective cutoffs. Future data never enters
their behavioral statistics. A label exactly at a cutoff belongs to that new
window and is excluded from that window's feature history. Equal timestamps
remain together; arbitrary movie-ID ties do not create artificial temporal order.

The 2019/2021 windows have 365 days and 2020 has 366. The objective is a calendar
year, not an identical number of days. Model comparisons use identical windows
within a partition; do not call a score change across different years a model
improvement. Pre-2019 events are initial history. Events at/after 2022-01-01 are
outside these label windows and are accounted for, not silently discarded from
the source database.

Why global cutoffs: a random split can put future user behavior into training.
Even per-user chronological leave-last-out splits can leak global movie/user
statistics when different users' prediction dates differ. A statistic trained
on another user's later interaction can be future information for an earlier
prediction. Shared global anchors make the permitted time boundary explicit.
Per-user splits could be a separate evaluated protocol, not an automatic fix.

## Fitting, selection, and inference state

Initial fitting may access observations strictly before **2020-01-01**. The
`training_observations` view exposes exactly the frozen pre-2020 interactions
for collaborative methods or a separately defined observed-rating objective.
The supervised `training_examples` table instead pairs **2019 snapshot features**
with **2019 outcomes** and sampled unknown contrasts. Different model families
need not consume identical row formats, but must obey the same initial data
budget and share the evaluation cohorts/candidate pools.

`training_batch()` always binds those supervised pairs to the pre-2019 feature
schema and returns only the behavioral whitelist plus history indicators. It
does not let training silently consume validation/test label tables. Using the
pre-2020 snapshot to predict 2019 training labels would be leakage.

Select hyperparameters and feature groups on validation only. Version one keeps
learned parameters frozen after validation selection; no gradient/refitting
updates on validation or test labels are authorized for the test run. At test
time, deterministic **historical input state** may refresh through 2020 because
those observations are now past: the pre-2021 snapshot intentionally includes
validation-period events. A popular-count baseline can use updated historical
counts; a trained tower can consume updated historical inputs with fixed
weights. Recomputing data features is distinct from optimizing learned parameters.
Pure ID-based models may require fallbacks for IDs absent from fitting; do not
drop those cases per model. A final-refit-on-validation policy would be a new,
explicit experiment, not an unrecorded change to this protocol.

Only declared inference inputs/seen masks may refresh automatically. Fitted
similarity matrices, embeddings, scalers, imputers, and learned vocabularies
remain fitted from the initial training budget; do not call refitting them a
feature refresh. Fit ID maps/preprocessing on training information only and
report model-specific unknown-ID coverage without changing the common cohort.

Ingestion-time/revision availability and genre metadata versions are not
provided. The protocol uses recorded event time as availability time, retains
the existing static-metadata limitation, and cannot remove the published
MovieLens cohort's total-history selection bias.

## Ground truth and coverage accounting

All observed ratings in each label window remain in `label_events`. An event is
primary ground truth only if its rating meets the positive threshold, the user
meets the pre-cutoff history requirement, the item is in the historical catalog,
and the pair was not already seen at that cutoff.

Each observed label receives one mutually exclusive status, in this order:
below-positive-threshold, cold user (zero history), sparse user (1–4 history),
no item history, already seen, or eligible positive. The original boolean facts
and counts remain available for overlapping analyses; status totals must
reconcile exactly to all window ratings. Excluded source observations are not
deleted or relabeled.

The primary ranking cohort contains users with at least one eligible positive.
Recall/NDCG have no positive denominator for other users. Report the number of
all warm-history users, label-window users, evaluable users, and positive-label
coverage, rather than claiming the cohort represents all service users. This
outcome-conditioned offline cohort has selection bias. Do not substitute
"not observed positive" for a genuine dislike or assert those users were inactive.

Historically observed-item availability is only a conservative proxy. Some
unrated/newly observed movies may actually have been available earlier. Report
positive labels lost to this policy, including new items and cold/sparse users.
Do not hide these exclusions by presenting conditioned metrics as whole-catalog,
all-user recommendation quality.

## Training-only unobserved sampling

For each training user with eligible positive labels, sample without replacement
from the **training cutoff's catalog**, excluding:

1. Every item rated by that user before the training cutoff.
2. Every item observed for that user in the training-label window, including
   positives, lower ratings, and future-in-window cold-item observations.

Training-window outcomes are permitted supervised training information. They
are used to avoid labeling observed training examples as unobserved contrasts,
not to construct earlier behavioral features or evaluation candidate masks.
Validation/test outcomes are never consulted by the sampler. A sampled unknown
may become a later positive; excluding it based on that future fact would leak.

The sampler draws uniform catalog indices with a per-user PRNG seed derived
from SHA-256 of the protocol seed/user ID. Rejecting excluded/already-selected
items yields sampling without replacement. After bounded rejection attempts,
dense pools use an explicit remaining-pool uniform sample. No full user/catalog
cross product is generated. Only fallback users enumerate the catalog. Python
version, seed, algorithm identity, counts, and fallback usage are reproducible;
cross-version PRNG implementation identity is not assumed.

Requested negatives are `4 * positive_count`, capped at available unknown items.
Audits record requested/available/sampled counts, proposals, and fallback use.
No fake negatives fill an exhausted pool. Ratios and class balance are engineered
for training, so learned outputs are not calibrated preference/response
probabilities without a separate method and evidence.

`training_examples.target_label=0` means **sampled unobserved contrast**, not
observed dislike. Such rows have NULL observed rating/time. Target 1 rows retain
their genuine positive rating/time. Optional experiments using observed low
ratings as negatives would require a separate definition; they are not mixed
into this table.

## Exhaustive evaluation candidates and metric specification

No sampled evaluation negatives are generated. `evaluation_candidates()` uses
only the historical catalog, the user's historical count, and their pre-cutoff
seen mask. It does not inspect future positives, lower ratings, or ranking-cohort
membership to change the candidate item set. It can return the pool for any
warm-history user, even one with no evaluable positive labels.

Metrics must be labeled **exhaustive historical-catalog, warm-history,
observed-positive ranking**. This is not the entire 87,585-item source catalog
at every cutoff, nor complete preference ground truth. Every model must use the
same candidate pool, ground truth, and user cohort for a given partition. Future
unobserved or lower-rated candidates remain in the pool; they are nonrelevant
under the observed-positive metric definition, not proven dislikes.

Milestone 6 will implement/test these binary-relevance definitions:

- Return up to K unique candidate items; score ties break by movie ID ascending.
- Recall@K: hits divided by the user's eligible-positive count.
- Precision@K: hits divided by K, including if fewer than K items can be returned.
- Hit Rate@K: one if any hit, otherwise zero.
- NDCG@K: binary DCG with discount `1/log2(rank+1)`, divided by ideal DCG for
  `min(K, positive_count)` positives.
- Macro average equally over the fixed ranking users with positive denominators.
  Do not silently switch to interaction-weighted averages or sample candidates.

No metric values have been computed here. Test target values may be inspected
for integrity/coverage, but not model choice or tuning. Model-level test results
must stay untouched until choices are frozen.
