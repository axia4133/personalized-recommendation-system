"""Unit tests plus explicitly enabled local PostgreSQL integration tests."""

import os
from decimal import Decimal

import psycopg
import pytest

from src.data import benchmark_ingestion as benchmark


def test_read_ratings_preserves_half_stars_and_large_timestamp(tmp_path):
    source = tmp_path / "sample.csv"
    source.write_text(
        "userId,movieId,rating,timestamp\n1,17,4.5,2200000000\n",
        encoding="utf-8",
    )
    assert benchmark.read_ratings(source) == [(1, 17, Decimal("4.5"), 2200000000)]


@pytest.mark.parametrize("contents", [
    "userId,movieId,rating,timestamp\n",
    "userId,movieId,rating,timestamp\n1,17,4,1\n1,17,5,2\n",
    "user_id,movieId,rating,timestamp\n1,17,4,1\n",
])
def test_invalid_sample_is_rejected(tmp_path, contents):
    source = tmp_path / "sample.csv"
    source.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError):
        benchmark.read_ratings(source)


def test_equal_counts_do_not_hide_changed_values():
    expected = [(1, 17, Decimal("4.5"), 100)]
    with pytest.raises(ValueError, match="differ"):
        benchmark.validate_rows([(1, 17, Decimal("3.5"), 100)], expected)


def test_schedule_alternates_and_keeps_warmups_separate():
    schedule = list(benchmark.trial_schedule(["insert", "copy"], 3, 1))
    assert schedule[:2] == [("warmup", 1, "insert"), ("warmup", 1, "copy")]
    assert [method for phase, _, method in schedule if phase == "measured"] == [
        "insert", "copy", "copy", "insert", "insert", "copy",
    ]


def test_summary_excludes_warmup_outlier():
    trials = [{"method": "copy", "phase": "warmup", "seconds": 999}]
    trials += [{"method": "copy", "phase": "measured", "seconds": value}
               for value in (1, 2, 6)]
    summary = benchmark.summarize(trials, 100)["copy"]
    assert summary["median_seconds"] == 2
    assert summary["rows_per_second_at_median"] == 50
    assert summary["measured_runs"] == 3


@pytest.fixture
def database():
    if os.getenv("RECSYS_TEST_DATABASE") != "1":
        pytest.skip("Set RECSYS_TEST_DATABASE=1 to test the local PostgreSQL instance")
    with psycopg.connect(**benchmark.connection_options(), autocommit=True) as conn:
        if conn.execute("SELECT to_regclass('public.ratings_ingestion_benchmark')").fetchone()[0]:
            pytest.fail("Benchmark table already exists; integration tests will not overwrite it")
        before = benchmark.source_counts(conn)
        yield conn
        assert benchmark.source_counts(conn) == before
        assert conn.execute("SELECT to_regclass('public.ratings_ingestion_benchmark')").fetchone()[0] is None


@pytest.fixture
def ratings(database):
    result = database.execute("SELECT movie_id FROM public.movies ORDER BY movie_id LIMIT 1").fetchone()
    if result is None:
        pytest.fail("Load movies before running integration tests")
    return [(user, result[0], Decimal("4.5"), 1700000000 + user)
            for user in (101, 102, 103)]


@pytest.mark.parametrize("method", ["insert", "copy"])
def test_both_loaders_preserve_values_and_clean_up(database, ratings, method):
    # A batch size of two exercises a final partial batch as well.
    assert benchmark.run_trial(database, ratings, sorted(ratings), method, 2) > 0


@pytest.mark.parametrize("method", ["insert", "copy"])
def test_check_failure_rolls_back_and_cleans_up(database, ratings, method):
    invalid = ratings.copy()
    user, movie, _, timestamp = invalid[-1]
    invalid[-1] = (user, movie, Decimal("3.7"), timestamp)
    with pytest.raises(psycopg.errors.CheckViolation):
        benchmark.run_trial(database, invalid, sorted(invalid), method, 2)


def test_validation_failure_still_cleans_up(database, ratings):
    incorrect_expectation = ratings[:-1]
    with pytest.raises(ValueError, match="differ"):
        benchmark.run_trial(database, ratings, incorrect_expectation, "insert", 2)


def test_preexisting_table_is_preserved(database, ratings):
    database.execute("CREATE TABLE public.ratings_ingestion_benchmark (marker text)")
    try:
        database.execute("INSERT INTO public.ratings_ingestion_benchmark VALUES ('keep me')")
        with pytest.raises(psycopg.errors.DuplicateTable):
            benchmark.run_trial(database, ratings, sorted(ratings), "insert", 2)
        assert database.execute("SELECT marker FROM public.ratings_ingestion_benchmark").fetchall() == [("keep me",)]
    finally:
        database.execute("DROP TABLE public.ratings_ingestion_benchmark")
