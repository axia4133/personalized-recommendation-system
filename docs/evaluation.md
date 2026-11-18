# Milestone 6: baseline evaluation

**In progress: Milestone 6 of 10, Step 1 of 6 complete, Substep 3 of 3.**

The six planned steps are:

1. Ranking metrics: definitions, implementation/tests, and verification/documentation.
2. Popularity baseline: SQL historical counts, exhaustive candidate ranking, validation run.
3. Basic collaborative filtering: training-only similarities, unknown-ID fallbacks, validation run.
4. Matrix factorization: objective/sampling, fitting, validation run.
5. Comparison: identical cohorts/candidates, frozen selection, final test evaluation.
6. Documentation: measured results, limitations, and reproduction instructions.

Only Step 1 is implemented. No model has been fitted, no recommendation run has
been evaluated, and no MovieLens ranking metric values are claimed. Synthetic
examples below verify mathematics; they are not experiment results.

## Step 1: metric contract

**Goal:** correctly score an already ordered recommendation list using binary
observed-positive relevance and macro-average over the fixed evaluation cohort.
This makes later comparisons interpretable; incorrect denominators or omitted
users can inflate a model's apparent performance.

The implementation in `src/evaluation/metrics.py` follows
[the frozen dataset protocol](problem_formulation.md). Concepts include binary
relevance, rank discounting, ideal ranking normalization, fixed denominators,
and user-level rather than interaction-level averaging.

For one user, with K requested positions and R eligible relevant items:

- Recall@K = hits / R.
- Precision@K = hits / K, even if fewer than K predictions are returned.
- Hit Rate@K = 1 if there is any hit, otherwise 0.
- DCG@K = sum of `1 / log2(rank + 1)` at relevant ranks, starting at rank 1.
- NDCG@K = DCG@K / ideal DCG for `min(K, R)` relevant items.

`binary_metrics_at_k()` returns an immutable `RankingMetrics` record.
`evaluate_rankings()` returns one record per K, equally averaged over users.
Its recommendation and relevance mapping keys must match exactly: a missing
prediction list is an error, whereas an explicitly empty list contributes zeros.
Truth must be nonempty for every supplied user. The caller must load **all**
users from the fixed `ranking_users` table; this helper cannot discover omitted
users if both input mappings were filtered before being passed in.

Movie and user IDs must be positive integers. Duplicate recommendations and
truth IDs are rejected rather than silently deduplicated. Recommendations
must have a defined order (for example a list or tuple), not a set. K values
must be positive, unique integers. Nonrelevant items receive zero binary gain;
they are not thereby proven dislikes.

## Hand-calculated example

For recommendations `[11, 12, 13]`, truth `{11, 13}`, and K=3:

- Hits = 2; Recall = 1; Precision = 2/3; Hit Rate = 1.
- DCG = `1 + 1/log2(4) = 1.5`.
- Ideal DCG = `1 + 1/log2(3)`.
- NDCG = `1.5 / (1 + 1/log2(3))`.

```python
from src.evaluation.metrics import binary_metrics_at_k, evaluate_rankings

one_user = binary_metrics_at_k([11, 12, 13], {11, 13}, k=3)

# Synthetic users: the empty list must stay in the denominator.
averages = evaluate_rankings(
    recommendations={101: [11, 12, 13], 102: []},
    relevance={101: {11, 13}, 102: {21}},
    ks=(10, 20),
)
```

For understanding, work out the same single-user example at K=2 before reading
the tests. Compare the Recall and NDCG changes: they measure different aspects
of the ranking.

## Integration boundary

The evaluator accepts already ranked IDs. It does not score candidates, sort
score ties, read SQL, generate negatives, or select a cohort. The next baseline
step must enforce candidate membership, exclude seen items using the correct
snapshot, sort by descending score then ascending movie ID, and request the
same complete historical candidate pool for every model.

Dataset exclusions and coverage must accompany later metrics. An exhaustive
historical-catalog evaluation is not complete preference ground truth and does
not cover all source users or every movie. Test labels remain reserved for the
final frozen comparison; metric unit tests use synthetic IDs only.

## Verification and Git checkpoint

```bash
python -m pytest -q tests/test_ranking_metrics.py
python -m pytest -q
# With Docker/PostgreSQL available:
RECSYS_TEST_DATABASE=1 python -m pytest -q
```

The metric module has **35 passing tests** covering hand-calculated examples,
rank discounting, ideal normalization, short/empty predictions, macro averaging,
invalid inputs, and all complete rankings/nonempty truth subsets of four items.
The latter checks metric bounds and monotone recall without incorrectly assuming
that NDCG must be monotone in K. No new dependency is needed.

The complete regression suite, including the opt-in PostgreSQL integration
tests, passed **114 tests** on 2026-11-17. Whitespace checks also passed.

Files in this increment:

- `src/evaluation/metrics.py`: binary metrics and strict fixed-cohort macro evaluator.
- `tests/test_ranking_metrics.py`: mathematical and evaluator-contract tests.
- `docs/evaluation.md`: progress, formulas, example, validation, and integration boundary.
- `docs/problem_formulation.md`: links the implemented metrics to the frozen protocol.
- `README.md`: current Milestone 6 progress.

Suggested commit after review: `feat(evaluation): add tested binary ranking metrics`.
The next small task is the historical popularity baseline, beginning with its
SQL score definition and deterministic top-K recommendations on validation.
