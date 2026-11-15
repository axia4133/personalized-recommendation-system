"""Hand-computed feature expectations, future-invariance, and atomic snapshots."""

import json
import os
from datetime import datetime, timedelta
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from src.features import build_sql_features as features


def config():
    result = json.loads((features.ROOT / "configs/features.json").read_text())
    result.update(recent_window_days=1, inspect_query_plans=False)
    return result


@pytest.fixture
def database():
    if os.getenv("RECSYS_TEST_DATABASE") != "1":
        pytest.skip("Set RECSYS_TEST_DATABASE=1 for isolated SQL feature tests")
    name = f"recsys_features_test_{uuid4().hex}"
    with psycopg.connect(**features.connection_options("postgres"), autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            with psycopg.connect(**features.connection_options(name), autocommit=True) as conn:
                for filename in ("001_movies.sql", "002_ratings.sql", "003_tags.sql", "004_links.sql"):
                    conn.execute((features.ROOT / "sql/schema" / filename).read_text())
                conn.execute((features.ROOT / "sql/cleaning/001_validated_views.sql").read_text())
                conn.execute("""
                    INSERT INTO movies VALUES
                    (1,'A',' Action |Comedy|Action| '),(2,'B','Action'),
                    (3,'C','(no genres listed)'),(4,'D','Drama'),(5,'E','Adventure');
                """)
                cutoff = features.feature_parameters(config())["cutoff"]
                rows = [(1, 1, 4, cutoff - 10), (1, 2, 2, cutoff - 5),
                        (2, 1, 5, cutoff - 86401), (2, 3, 1, cutoff - 86400),
                        (3, 2, 3, cutoff - 1), (99, 4, 5, cutoff), (1, 4, 1, cutoff + 1)]
                with conn.cursor() as cur:
                    cur.executemany("INSERT INTO ratings VALUES (%s,%s,%s,%s)", rows)
                yield conn
        finally:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def test_hand_computed_user_movie_and_genre_features(database):
    previous_workers = database.execute("SHOW max_parallel_workers_per_gather").fetchone()[0]
    previous_memory = database.execute("SHOW work_mem").fetchone()[0]
    report = features.build_snapshot(database, "features_hand", config())
    assert report["execution_settings"]["max_parallel_workers_per_gather"] == "0"
    assert database.execute("SHOW max_parallel_workers_per_gather").fetchone()[0] == previous_workers
    assert database.execute("SHOW work_mem").fetchone()[0] == previous_memory
    assert report["validation"]["history_rows"] == 5
    assert report["validation"]["users"] == 3
    assert report["validation"]["movies"] == 3
    user = database.execute("""
        SELECT rating_count, mean_rating, rating_variance, recent_rating_count, mean_gap_days
        FROM features_hand.user_features WHERE user_id=1
    """).fetchone()
    assert user == pytest.approx((2, 3, 1, 2, 5 / 86400))
    # Exactly at the lower recent bound is included; the event one second before is not.
    assert database.execute("SELECT recent_rating_count FROM features_hand.user_features WHERE user_id=2").fetchone()[0] == 1
    assert database.execute("SELECT rating_stddev, mean_gap_days FROM features_hand.user_features WHERE user_id=3").fetchone() == (0, None)
    movie = database.execute("SELECT rating_count, mean_rating, shrunk_mean_rating FROM features_hand.movie_features WHERE movie_id=1").fetchone()
    assert movie == pytest.approx((2, 4.5, (9 + 20 * 3) / 22))
    genres = database.execute("SELECT genre, genre_count FROM features_hand.movie_genres WHERE movie_id=1 ORDER BY genre").fetchall()
    assert genres == [("Action", 2), ("Comedy", 2)]
    action = database.execute("""
        SELECT support_weight, weighted_history_share, centered_affinity, genre_history_rank
        FROM features_hand.user_genre_features WHERE user_id=1 AND genre='Action'
    """).fetchone()
    assert action == pytest.approx((1.5, 0.75, -0.5 / 6.5, 1))
    assert database.execute("SELECT known_genre_history_fraction FROM features_hand.user_history_features WHERE user_id=2").fetchone()[0] == pytest.approx(0.5)
    assert database.execute("SELECT genre_metadata_policy FROM features_hand.snapshot_context").fetchone()[0] == "static_unversioned_assumption"


def test_requested_pairs_have_seen_cold_and_metadata_backoffs(database):
    features.build_snapshot(database, "features_pairs", config())
    rows = features.fetch_pair_features(database, "features_pairs", [(1,1), (1,3), (1,4), (99,1), (1,1)])
    assert len(rows) == 4  # Duplicate requests, not source records, are coalesced.
    contract = json.loads((features.ROOT / "configs/feature_contract.json").read_text())
    fields = [name for group in ("identifiers", "history_availability_indicators",
              "eligibility_only_not_learned_features", "behavioral_pair_features", "optional_static_genre_features")
              for name in contract[group]]
    assert len(fields) == len(set(fields))
    assert set(fields) == set(rows[0])
    by_pair = {(row["user_id"], row["movie_id"]): row for row in rows}
    assert by_pair[(1,1)]["has_prior_rating"]
    assert not by_pair[(1,1)]["eligible_under_observed_catalog_policy"]
    assert not by_pair[(1,4)]["has_movie_history"]  # A future-only movie is not in the catalog proxy.
    assert not by_pair[(1,4)]["eligible_under_observed_catalog_policy"]
    assert by_pair[(1,3)]["user_genre_affinity"] == 0
    assert by_pair[(1,3)]["known_item_genres"] == 0
    assert not by_pair[(99,1)]["has_user_history"]
    assert by_pair[(99,1)]["user_mean_rating"] == pytest.approx(3)
    assert by_pair[(99,1)]["popularity_relative_to_user_history"] is None


def test_future_ratings_cannot_change_existing_snapshot_feature_values(database):
    features.build_snapshot(database, "features_before", config())
    cutoff = features.feature_parameters(config())["cutoff"]
    database.execute("UPDATE ratings SET rating=0.5 WHERE rating_timestamp >= %s", (cutoff,))
    database.execute("INSERT INTO ratings VALUES (98,5,5,%s)", (cutoff + 100,))
    features.build_snapshot(database, "features_after", config())
    # Context source-row counts intentionally change; feature values must not.
    for table, order in [("history_ratings", "user_id,movie_id"), ("user_features", "user_id"),
                         ("movie_features", "movie_id"), ("movie_genres", "movie_id,genre"),
                         ("user_genre_features", "user_id,genre"), ("user_history_features", "user_id"),
                         ("example_user_item_features", "user_id,movie_id")]:
        before = database.execute(sql.SQL("SELECT * FROM {} ORDER BY " + order).format(sql.Identifier("features_before", table))).fetchall()
        after = database.execute(sql.SQL("SELECT * FROM {} ORDER BY " + order).format(sql.Identifier("features_after", table))).fetchall()
        assert before == after, table
    cold_pairs = [(999, 1), (1, 4), (999, 999)]
    assert features.fetch_pair_features(database, "features_before", cold_pairs) == features.fetch_pair_features(database, "features_after", cold_pairs)


def test_cutoff_is_exclusive_and_tied_events_enter_only_later_snapshot(database):
    first = features.build_snapshot(database, "features_cutoff", config())
    later = config()
    later["cutoff_utc"] = (datetime.fromisoformat(later["cutoff_utc"]) + timedelta(seconds=1)).isoformat()
    second = features.build_snapshot(database, "features_later", later)
    assert first["validation"]["history_rows"] == 5
    assert second["validation"]["history_rows"] == 6
    assert database.execute("SELECT COUNT(*) FROM features_cutoff.user_features WHERE user_id=99").fetchone()[0] == 0
    assert database.execute("SELECT COUNT(*) FROM features_later.user_features WHERE user_id=99").fetchone()[0] == 1


def test_no_known_genres_retains_all_behavioral_history(database):
    database.execute("UPDATE movies SET genres_raw='(no genres listed)'")
    report = features.build_snapshot(database, "features_unknown", config())
    assert report["validation"]["history_rows"] == 5
    assert report["validation"]["movie_genre_rows"] == 0
    assert report["validation"]["user_genre_rows"] == 0
    assert report["validation"]["users_without_known_genres"] == 3
    pair = features.fetch_pair_features(database, "features_unknown", [(1,3)])[0]
    assert pair["user_genre_affinity"] == 0
    assert pair["user_rating_count"] == 2


def test_failed_validation_rolls_back_entire_schema(database, monkeypatch):
    original = database.execute("SELECT * FROM ratings ORDER BY user_id,movie_id").fetchall()
    def fail(*args):
        raise ValueError("Intentional validation failure")
    monkeypatch.setattr(features, "validate_snapshot", fail)
    with pytest.raises(ValueError, match="Intentional"):
        features.build_snapshot(database, "features_failed", config())
    assert database.execute("SELECT 1 FROM pg_namespace WHERE nspname='features_failed'").fetchone() is None
    assert database.execute("SELECT * FROM ratings ORDER BY user_id,movie_id").fetchall() == original


def test_existing_schema_is_not_replaced(database):
    database.execute("CREATE SCHEMA features_existing; CREATE TABLE features_existing.marker AS SELECT 99 AS value")
    with pytest.raises(ValueError, match="already exists"):
        features.build_snapshot(database, "features_existing", config())
    assert database.execute("SELECT value FROM features_existing.marker").fetchone()[0] == 99


def test_empty_history_rolls_back_instead_of_publishing_empty_features(database):
    empty = config()
    empty["cutoff_utc"] = "1970-01-01T00:00:00+00:00"
    with pytest.raises(ValueError, match="No history"):
        features.build_snapshot(database, "features_empty", empty)
    assert database.execute("SELECT 1 FROM pg_namespace WHERE nspname='features_empty'").fetchone() is None


@pytest.mark.parametrize("change", [
    {"cutoff_utc": "2020-01-01T00:00:00"},
    {"movie_prior_count": 0}, {"genre_prior_weight": float("nan")},
    {"genre_metadata_policy": "historically_verified"}, {"work_mem_mb": 100000},
    {"example_users": 1000, "example_movies": 1000},
    {"parallel_workers_per_gather": -1},
])
def test_invalid_feature_contract_is_rejected(change):
    candidate = config()
    candidate.update(change)
    with pytest.raises(ValueError):
        features.feature_parameters(candidate)


@pytest.mark.parametrize("name", ["public", "clean", "features_", "features_BAD", "features_a;DROP SCHEMA public"])
def test_schema_names_cannot_target_raw_namespaces_or_inject_sql(name):
    with pytest.raises(ValueError):
        features.validate_schema(name)


@pytest.mark.parametrize("pairs", [[], [(0,1)], [(True,1)], [(1,)], [(1,2147483648)]])
def test_invalid_pair_requests_are_rejected(pairs):
    with pytest.raises(ValueError):
        features.validate_pairs(pairs)
