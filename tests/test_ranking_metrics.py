"""Hand-calculated ranking examples and strict fixed-cohort behavior."""

from itertools import combinations, permutations
from math import log2

import pytest

from src.evaluation.metrics import RankingMetrics, binary_metrics_at_k, evaluate_rankings


def test_hand_calculated_hits_at_first_and_third_rank():
    result = binary_metrics_at_k([11, 12, 13], {11, 13}, 3)
    assert result.recall == 1
    assert result.precision == pytest.approx(2 / 3)
    # Actual DCG = 1 + 1/log2(4); ideal = 1 + 1/log2(3).
    assert result.ndcg == pytest.approx(1.5 / (1 + 1 / log2(3)))
    assert result.hit_rate == 1


def test_rank_discount_and_k_prefix():
    assert binary_metrics_at_k([7, 8, 9], {9}, 2) == RankingMetrics(0, 0, 0, 0)
    result = binary_metrics_at_k([7, 8, 9], {9}, 3)
    assert result == RankingMetrics(1, 1 / 3, 0.5, 1)


def test_ideal_dcg_uses_truth_count_capped_by_k():
    result = binary_metrics_at_k([1, 2], {1, 2, 3, 4}, 2)
    assert result == RankingMetrics(0.5, 1, 1, 1)


def test_short_list_precision_keeps_k_and_ndcg_keeps_missing_positives():
    result = binary_metrics_at_k([1], {1, 2}, 5)
    assert result.recall == 0.5
    assert result.precision == 0.2
    assert result.ndcg == pytest.approx(1 / (1 + 1 / log2(3)))
    assert result.hit_rate == 1


def test_empty_predictions_are_zero_scores_not_a_dropped_user():
    assert binary_metrics_at_k([], {1}, 10) == RankingMetrics(0, 0, 0, 0)
    result = evaluate_rankings({10: [1], 20: []}, {10: {1}, 20: {2}}, ks=(1,))
    assert result[1] == RankingMetrics(0.5, 0.5, 0.5, 0.5)


def test_macro_average_is_not_interaction_weighted():
    result = evaluate_rankings({10: [1], 20: [2]}, {10: {1}, 20: {2, 3, 4}}, ks=(1, 2))
    assert result[1] == RankingMetrics(2 / 3, 1, 1, 1)
    assert result[2].recall == pytest.approx(2 / 3)
    assert result[2].precision == 0.5
    assert result[2].ndcg == pytest.approx((1 + 1 / (1 + 1 / log2(3))) / 2)


def test_mapping_order_does_not_change_scores():
    relevance = {20: {3, 4}, 10: {1}}
    assert evaluate_rankings({10: [2, 1], 20: [3, 5]}, relevance) == evaluate_rankings(
        {20: [3, 5], 10: [2, 1]}, relevance
    )


@pytest.mark.parametrize("k", [0, -1, True, 1.5, "3", None])
def test_invalid_k_is_rejected(k):
    with pytest.raises(ValueError, match="positive integer"):
        binary_metrics_at_k([1], {1}, k)


@pytest.mark.parametrize(
    "ranked,relevant,match",
    [
        ([1, 1], {1}, "unique"),
        ([1, 2, 2], {1}, "unique"),  # Even duplicates outside top K are invalid.
        ([1], [1, 1], "unique"),
        ([1], set(), "at least one"),
        ({1, 2}, {1}, "ordered sequence"),
        ("12", {1}, "ordered sequence"),
        ([1], "1", "collection"),
        ([True], {1}, "positive integer"),
        ([0], {1}, "positive integer"),
        ([1.0], {1}, "positive integer"),
        ([1], {-1}, "positive integer"),
        ([1], {False}, "positive integer"),
    ],
)
def test_invalid_user_inputs_are_rejected(ranked, relevant, match):
    with pytest.raises(ValueError, match=match):
        binary_metrics_at_k(ranked, relevant, 1)


@pytest.mark.parametrize(
    "recommendations,relevance,ks,match",
    [
        ({}, {}, (1,), "empty"),
        ({}, {1: {1}}, (1,), "exactly match"),
        ({1: [1], 2: []}, {1: {1}}, (1,), "exactly match"),
        ({1: [1]}, {1: {1}}, (), "at least one K"),
        ({1: [1]}, {1: {1}}, (1, 1), "unique"),
        ({1: [1]}, {1: {1}}, (True,), "positive integer"),
        ({True: [1]}, {True: {1}}, (1,), "User ID"),
        ({0: [1]}, {0: {1}}, (1,), "User ID"),
        ({1: [1]}, {1: set()}, (1,), "at least one"),
    ],
)
def test_invalid_cohort_or_configuration_is_rejected(recommendations, relevance, ks, match):
    with pytest.raises(ValueError, match=match):
        evaluate_rankings(recommendations, relevance, ks)


def test_tiny_catalog_metric_bounds_and_recall_monotonicity():
    # Enumerate every complete ordering and nonempty truth subset of four items.
    # Recall can only increase with K; NDCG is bounded but need not be monotone.
    catalog = [1, 2, 3, 4]
    for ranking in permutations(catalog):
        for size in range(1, 5):
            for truth in combinations(catalog, size):
                previous_recall = 0
                for k in range(1, 6):
                    result = binary_metrics_at_k(ranking, truth, k)
                    assert previous_recall <= result.recall <= 1
                    assert 0 <= result.precision <= 1
                    assert 0 <= result.ndcg <= 1
                    assert result.hit_rate in (0, 1)
                    assert result.precision == pytest.approx(result.recall * size / k)
                    previous_recall = result.recall
                assert previous_recall == 1
