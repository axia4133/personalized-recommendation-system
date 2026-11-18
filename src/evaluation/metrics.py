"""Binary ranking metrics for the fixed observed-positive evaluation cohort.

Inputs are already ranked, unique movie IDs, best first. Candidate eligibility
and score ties (score descending, movie ID ascending) are the caller's job.
These functions never select users, sample candidates, or inspect a database.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from math import fsum, log2
from numbers import Integral


@dataclass(frozen=True)
class RankingMetrics:
    recall: float
    precision: float
    ndcg: float
    hit_rate: float


def _positive_integer(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _validate_items(items: Collection[int], name: str) -> set[int]:
    for item in items:
        _positive_integer(item, f"{name} movie ID")
    unique = set(items)
    if len(unique) != len(items):
        raise ValueError(f"{name} must contain unique movie IDs")
    return unique


def _validate_user_inputs(
    ranked_items: Sequence[int], relevant_items: Collection[int]
) -> set[int]:
    # Sets have no rank order; refusing them prevents accidental arbitrary ranks.
    if not isinstance(ranked_items, Sequence) or isinstance(ranked_items, (str, bytes)):
        raise ValueError("Recommendations must be an ordered sequence")
    if not isinstance(relevant_items, Collection) or isinstance(relevant_items, (str, bytes)):
        raise ValueError("Relevant items must be a collection of unique movie IDs")
    _validate_items(ranked_items, "Recommendations")
    relevant = _validate_items(relevant_items, "Relevant items")
    if not relevant:
        raise ValueError("Each evaluation user must have at least one relevant item")
    return relevant


def _at_k(ranked_items: Sequence[int], relevant: set[int], k: int) -> RankingMetrics:
    hit_positions = [rank for rank, item in enumerate(ranked_items[:k], 1) if item in relevant]
    hits = len(hit_positions)
    dcg = fsum(1 / log2(rank + 1) for rank in hit_positions)
    ideal_dcg = fsum(1 / log2(rank + 1) for rank in range(1, min(k, len(relevant)) + 1))
    return RankingMetrics(
        recall=hits / len(relevant),
        precision=hits / k,
        ndcg=dcg / ideal_dcg,
        hit_rate=float(hits > 0),
    )


def binary_metrics_at_k(
    ranked_items: Sequence[int], relevant_items: Collection[int], k: int
) -> RankingMetrics:
    """Score one user, with binary relevance and ranks starting at one.

    Precision always divides by K, even for a short or empty recommendation
    list. Empty truth is undefined and rejected, rather than silently skipped.
    Duplicate predictions or truth are rejected, including beyond the K prefix.
    """
    _positive_integer(k, "K")
    relevant = _validate_user_inputs(ranked_items, relevant_items)
    return _at_k(ranked_items, relevant, k)


def evaluate_rankings(
    recommendations: Mapping[int, Sequence[int]],
    relevance: Mapping[int, Collection[int]],
    ks: Sequence[int] = (10, 20),
) -> dict[int, RankingMetrics]:
    """Macro-average equally over exactly the supplied fixed user cohort.

    The mapping key sets must match, including users with empty predictions.
    This prevents a model from improving reported scores by omitting failures.
    No cohort filtering or interaction weighting happens inside this evaluator.
    """
    if not ks:
        raise ValueError("Supply at least one K")
    for k in ks:
        _positive_integer(k, "K")
    if len(set(ks)) != len(ks):
        raise ValueError("K values must be unique")
    if not relevance:
        raise ValueError("The evaluation cohort must not be empty")
    if recommendations.keys() != relevance.keys():
        raise ValueError("Recommendation users must exactly match the fixed relevance cohort")
    for user_id in relevance:
        _positive_integer(user_id, "User ID")

    # Validate once per user for all K values; retain only per-user metric rows.
    values: dict[int, list[RankingMetrics]] = {k: [] for k in ks}
    for user_id in sorted(relevance):
        ranked = recommendations[user_id]
        relevant = _validate_user_inputs(ranked, relevance[user_id])
        for k in ks:
            values[k].append(_at_k(ranked, relevant, k))
    users = len(relevance)
    return {
        k: RankingMetrics(
            recall=fsum(row.recall for row in rows) / users,
            precision=fsum(row.precision for row in rows) / users,
            ndcg=fsum(row.ndcg for row in rows) / users,
            hit_rate=fsum(row.hit_rate for row in rows) / users,
        )
        for k, rows in values.items()
    }
