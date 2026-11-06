"""Quality checks must detect defects even when storage constraints are absent."""

import json
import os
import sys
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from src.data import run_data_quality as quality


PARAMETERS = dict(minimum_user_history=3, sparse_movie_threshold=2,
                  order_diagnostic_users=2, window_start=100, window_end=200)


@pytest.fixture
def database():
    if os.getenv("RECSYS_TEST_DATABASE") != "1":
        pytest.skip("Set RECSYS_TEST_DATABASE=1 for local database quality tests")
    name = f"recsys_quality_test_{uuid4().hex}"
    with psycopg.connect(**quality.connection_options("postgres"), autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            with psycopg.connect(**quality.connection_options(name), autocommit=True) as conn:
                # Deliberately unconstrained fixtures let queries demonstrate that
                # they detect invalid values, duplicates, and missing references.
                conn.execute("""
                    CREATE TABLE movies (movie_id integer, title text, genres_raw text);
                    CREATE TABLE ratings (user_id integer, movie_id integer, rating numeric, rating_timestamp bigint);
                    CREATE TABLE tags (tag_id bigint, user_id integer, movie_id integer, tag text, tag_timestamp bigint);
                    CREATE TABLE links (movie_id integer, imdb_id text, tmdb_id integer);
                    SET TIME ZONE 'UTC';
                """)
                yield conn
        finally:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def result(conn, name):
    return quality.execute_check(conn, quality.QUERIES[name], PARAMETERS)["result"]


def test_core_detects_nulls_ranges_missing_genres_and_bad_ids(database):
    database.execute("""
        INSERT INTO movies VALUES (1, ' ', '(no genres listed)'), (2, NULL, NULL), (-1, 'Negative ID', '');
        INSERT INTO ratings VALUES
            (1,1,3.7,101), (2,1,6.0,102), (3,1,NULL,103), (-1,1,4,-1), (NULL,1,4,NULL);
        INSERT INTO tags VALUES (1,1,1,' ',100);
        INSERT INTO links VALUES (1,'bad-id',-2);
    """)
    database.execute("INSERT INTO tags VALUES (2,1,1,%s,100)", ("\t\n",))
    core = result(database, "core_quality")
    assert core["ratings"]["invalid_rating_values"] == 2
    assert core["ratings"]["null_ratings"] == 1
    assert core["ratings"]["null_user_ids"] == 1
    assert core["ratings"]["nonpositive_user_ids"] == 1
    assert core["ratings"]["negative_timestamps"] == 1
    assert core["ratings"]["null_timestamps"] == 1
    assert core["movies"]["blank_titles"] == 1
    assert core["movies"]["null_titles"] == 1
    assert core["movies"]["no_genres_listed"] == 1
    assert core["tags"]["blank_tags"] == 2
    assert core["links"]["malformed_imdb_ids"] == 1
    assert core["links"]["nonpositive_tmdb_ids"] == 1


def test_duplicate_observations_are_distinguished_from_reused_metadata(database):
    database.execute("""
        INSERT INTO movies VALUES (1,'Same title','Drama'),(2,'Same title','Comedy');
        INSERT INTO ratings VALUES (1,1,4,101),(1,1,5,102),(2,999,4,103);
        INSERT INTO tags VALUES (1,9,1,'word',100),(2,9,1,'word',100);
        INSERT INTO links VALUES (1,'001',42),(2,'001',42),(999,NULL,NULL);
    """)
    checks = result(database, "duplicates_and_references")
    assert checks["ratings"] == {"duplicate_pair_groups": 1, "extra_rows": 1}
    assert checks["tags"] == {"exact_repeated_event_groups": 1, "extra_rows": 1}
    assert checks["repeated_titles"]["groups"] == 1
    assert checks["reused_imdb_ids"]["groups"] == 1
    assert checks["reused_tmdb_ids"]["groups"] == 1
    assert checks["references"]["ratings_without_movie"] == 1
    assert checks["references"]["links_without_movie"] == 1
    assert checks["references"]["tag_users_without_rating_history"] == 1


def test_activity_includes_unrated_movies_and_sums_to_population(database):
    database.execute("""
        INSERT INTO movies VALUES (1,'A','Drama'),(2,'B','Drama'),(3,'C','Drama'),(4,'D','Drama');
        INSERT INTO ratings VALUES (1,1,4,101),(1,2,5,102),(2,1,3,103);
    """)
    activity = result(database, "activity_and_sparsity")
    assert activity["users"]["count"] == 2
    assert activity["users"]["min"] == 1
    assert activity["users"]["max"] == 2
    assert activity["users"]["below_history_threshold"] == 2
    assert activity["users"]["single_timestamp_users"] == 1
    assert activity["movies"]["catalog_count"] == 4
    assert activity["movies"]["zero_ratings"] == 2
    assert activity["movies"]["below_rating_threshold"] == 3
    assert activity["movies"]["ratings_on_movies_below_threshold"] == 1
    assert activity["observed_rating_density"] == 0.375
    assert sum(row["ratings"] for row in activity["movie_bins"]) == 3


def test_timestamp_bounds_are_exclusive_and_order_check_is_scoped(database):
    database.execute("""
        INSERT INTO ratings VALUES
            (1,1,4,110),(1,2,4,105),(2,1,4,99),(2,2,4,200),(3,1,4,NULL);
    """)
    times = result(database, "timestamp_diagnostics")
    assert times["ratings"]["before_documented_start"] == 1
    assert times["ratings"]["at_or_after_documented_end"] == 1
    assert times["ratings"]["null_timestamps"] == 1
    assert times["movie_id_order_diagnostic"]["users"] == 2
    assert times["movie_id_order_diagnostic"]["ratings"] == 4
    assert times["movie_id_order_diagnostic"]["timestamp_decreases"] == 1
    assert sum(row["rows"] for row in times["rating_years"]) == 5


def test_boundary_review_distinguishes_next_day_from_later_events(database):
    database.execute("INSERT INTO ratings VALUES (1,1,4,199),(1,2,4,200),(2,1,4,86600)")
    review = result(database, "timestamp_boundary_review")
    assert review["at_or_after_interpreted_utc_end"] == 2
    assert review["within_following_utc_day"] == 1
    assert review["at_or_after_another_24_hours"] == 1
    assert review["min_flagged_epoch"] == 200


def test_clean_views_preserve_population_except_documented_technical_defects(database):
    database.execute("""
        INSERT INTO movies VALUES (1,'A','Drama'),(2,NULL,NULL),(-1,'Bad ID','Drama');
        INSERT INTO ratings VALUES
            (1,1,0.5,101),(2,2,5,9999999999),(-1,1,4,101),
            (3,999,4,101),(4,1,3.7,101),(5,1,NULL,101),(6,1,4,-1);
        INSERT INTO tags VALUES
            (1,7,1,'repeat',101),(2,7,1,'repeat',101),(3,-1,1,'bad',101),(4,8,2,NULL,101);
        INSERT INTO links VALUES (1,NULL,NULL),(999,'001',1);
    """)
    original = quality.row_counts(database, "public")
    cleaning = quality.install_clean_views(database, original)
    assert cleaning["clean_rows"] == {"movies": 2, "ratings": 2, "tags": 3, "links": 1}
    assert cleaning["excluded_rows"] == {"movies": 1, "ratings": 5, "tags": 1, "links": 1}
    assert quality.row_counts(database, "public") == original
    # Low ratings, sparse users, missing metadata, and future-window events stay.
    assert database.execute("SELECT COUNT(*) FROM clean.ratings WHERE rating = 0.5").fetchone()[0] == 1
    assert database.execute("SELECT COUNT(*) FROM clean.ratings WHERE rating_timestamp = 9999999999").fetchone()[0] == 1
    assert database.execute("SELECT COUNT(*) FROM clean.movies WHERE title IS NULL").fetchone()[0] == 1
    assert database.execute("SELECT COUNT(*) FROM clean.tags WHERE tag = 'repeat'").fetchone()[0] == 2
    assert database.execute("SELECT COUNT(*) FROM clean.links WHERE imdb_id IS NULL").fetchone()[0] == 1
    assert quality.install_clean_views(database, original)["clean_rows"] == cleaning["clean_rows"]


def test_independent_distribution_totals_reconcile(database):
    database.execute("""
        INSERT INTO movies VALUES (1,'A','Drama'),(2,'B','Drama');
        INSERT INTO ratings VALUES (1,1,4,101),(1,2,5,102),(2,1,3,103);
    """)
    checks = {name: quality.execute_check(database, filename, PARAMETERS)
              for name, filename in quality.QUERIES.items()}
    quality.check_reconciliations(checks)
    checks["core_quality"]["result"]["ratings"]["rows"] += 1
    with pytest.raises(ValueError, match="disagree"):
        quality.check_reconciliations(checks)


def test_reconciliation_accounts_for_detected_orphan_ratings(database):
    database.execute("""
        INSERT INTO movies VALUES (1,'A','Drama');
        INSERT INTO ratings VALUES (1,1,4,101),(1,999,5,102);
    """)
    checks = {name: quality.execute_check(database, filename, PARAMETERS)
              for name, filename in quality.QUERIES.items()}
    assert checks["duplicates_and_references"]["result"]["references"]["ratings_without_movie"] == 1
    quality.check_reconciliations(checks)


@pytest.mark.parametrize("change", [
    {"minimum_user_history_diagnostic": 0},
    {"documented_window_start_utc": "1995-01-09T00:00:00"},
    {"documented_window_start_utc": "2024-01-01T00:00:00+00:00"},
])
def test_invalid_quality_configuration_is_rejected(tmp_path, change):
    config = json.loads((quality.ROOT / "configs/data_quality.json").read_text())
    config.update(change)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        quality.load_config(path)


def test_existing_report_is_not_overwritten(tmp_path, monkeypatch):
    path = tmp_path / "report.json"
    path.write_text('{"keep": true}')
    monkeypatch.setattr(sys, "argv", ["run_data_quality.py", "--output", str(path)])
    with pytest.raises(FileExistsError):
        quality.main()
    assert path.read_text() == '{"keep": true}'
