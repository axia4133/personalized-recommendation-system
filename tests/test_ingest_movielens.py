"""Schema, lossless CSV handling, and atomic bulk-load validation."""

import csv
import os
from decimal import Decimal
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from src.data import ingest_movielens as ingest


def write_csv(tmp_path, table, rows):
    path = tmp_path / f"{table}.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(ingest.HEADERS[table])
        writer.writerows(rows)
    return path


def test_canonical_digest_preserves_quoting_unicode_and_newlines():
    values = [(1, 'A, "quoted" film', 'Drama|Comedy'), (2, 'Café\nfilm', None)]
    source = ingest.ValueDigest()
    database = ingest.ValueDigest()
    for row in values:
        source.add(row)
        database.add(tuple("" if value is None else str(value) for value in row))
    assert source.hexdigest() == database.hexdigest()
    changed = ingest.ValueDigest()
    for row in reversed(values):
        changed.add(row)
    assert changed.hexdigest() != source.hexdigest()


def test_profile_counts_csv_records_not_physical_lines(tmp_path):
    path = write_csv(tmp_path, "tags", [(1, 1, "line one\nline two", 1), (1, 1, "", 2)])
    profile = ingest.profile_csv(path, "tags")
    assert profile["summary"] == {"rows": 2, "users": 1, "null_tags": 1}


def test_profile_preserves_leading_zeros_and_missing_external_ids(tmp_path):
    path = write_csv(tmp_path, "links", [(1, "0001234", ""), (2, "", 42)])
    assert ingest.profile_csv(path, "links")["summary"] == {
        "rows": 2, "null_imdb_ids": 1, "null_tmdb_ids": 1,
        "imdb_ids_with_leading_zero": 1,
    }


def test_out_of_order_source_is_rejected(tmp_path):
    path = write_csv(tmp_path, "ratings", [(2, 1, "4.0", 1), (1, 1, "3.5", 2)])
    with pytest.raises(ValueError, match="key order"):
        ingest.profile_csv(path, "ratings")


@pytest.fixture
def database():
    if os.getenv("RECSYS_TEST_DATABASE") != "1":
        pytest.skip("Set RECSYS_TEST_DATABASE=1 for isolated PostgreSQL integration tests")
    name = f"recsys_ingestion_test_{uuid4().hex}"
    with psycopg.connect(**ingest.connection_options("postgres"), autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            with psycopg.connect(**ingest.connection_options(name), autocommit=True) as conn:
                for schema in ingest.SCHEMAS.values():
                    conn.execute((ingest.ROOT / "sql/schema" / schema).read_text())
                conn.execute("INSERT INTO movies VALUES (1, 'Test movie', 'Drama'), (2, 'Other movie', NULL)")
                yield conn
        finally:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def test_tags_keep_repeated_events_and_embedded_text(database, tmp_path):
    rows = [(7, 1, 'Café, "great"\nfilm', 10)] * 2 + [(8, 2, "", 11)]
    path = write_csv(tmp_path, "tags", rows)
    source = ingest.profile_csv(path, "tags")
    ingest.load_table(database, "tags", path)
    assert ingest.validate_values(database, "tags", source)["matches_source"]
    assert database.execute("SELECT COUNT(*), COUNT(DISTINCT tag_id) FROM tags").fetchone() == (3, 3)
    summary = database.execute((ingest.ROOT / "sql/validation/001_ingestion_summary.sql").read_text()).fetchone()[0]
    assert summary["tags"] == source["summary"]


def test_links_roundtrip_leading_zeros_and_nulls(database, tmp_path):
    path = write_csv(tmp_path, "links", [(1, "0001234", ""), (2, "", 42)])
    source = ingest.profile_csv(path, "links")
    ingest.load_table(database, "links", path)
    assert ingest.validate_values(database, "links", source)["matches_source"]
    assert database.execute("SELECT imdb_id, tmdb_id FROM links WHERE movie_id = 1").fetchone() == ("0001234", None)


@pytest.mark.parametrize("rows,error", [
    ([(1, 1, "4.0", 1), (1, 1, "5.0", 2)], psycopg.errors.UniqueViolation),
    ([(1, 999, "4.0", 1)], psycopg.errors.ForeignKeyViolation),
    ([(1, 1, "3.7", 1)], psycopg.errors.CheckViolation),
])
def test_failed_load_is_atomic_and_restores_keys(database, tmp_path, rows, error):
    path = write_csv(tmp_path, "ratings", rows)
    with pytest.raises(error):
        ingest.load_table(database, "ratings", path)
    assert database.execute("SELECT COUNT(*) FROM ratings").fetchone()[0] == 0
    kinds = database.execute("SELECT contype FROM pg_constraint WHERE conrelid = 'ratings'::regclass").fetchall()
    assert ("p",) in kinds and ("f",) in kinds


def test_ratings_roundtrip_and_source_mismatch_detection(database, tmp_path):
    path = write_csv(tmp_path, "ratings", [(1, 1, "4.5", 2200000000), (1, 2, "0.5", 12)])
    source = ingest.profile_csv(path, "ratings")
    ingest.load_table(database, "ratings", path)
    assert ingest.validate_values(database, "ratings", source)["rows"] == 2
    database.execute("UPDATE ratings SET rating = %s WHERE movie_id = 1", (Decimal("3.5"),))
    with pytest.raises(ValueError, match="differ"):
        ingest.validate_values(database, "ratings", source)


def test_existing_target_is_refused(database):
    with pytest.raises(ValueError, match="already exists"):
        ingest.check_target(database, ["movies", "ratings", "tags", "links"], "full")
    assert database.execute("SELECT COUNT(*) FROM movies").fetchone()[0] == 2
