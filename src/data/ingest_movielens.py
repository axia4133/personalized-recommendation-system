"""Verified MovieLens 32M ingestion without replacing the development database.

Run from the repository root. Full mode requires an empty/new database;
metadata mode adds tags/links to an existing movies/ratings development database.
Reports describe observed progress and never mark a failed run complete.
"""

import argparse
import csv
import hashlib
import io
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from time import perf_counter

import psycopg
from psycopg import sql


ROOT = Path(__file__).resolve().parents[2]
HEADERS = {
    "movies": ["movieId", "title", "genres"],
    "ratings": ["userId", "movieId", "rating", "timestamp"],
    "tags": ["userId", "movieId", "tag", "timestamp"],
    "links": ["movieId", "imdbId", "tmdbId"],
}
COLUMNS = {
    "movies": ["movie_id", "title", "genres_raw"],
    "ratings": ["user_id", "movie_id", "rating", "rating_timestamp"],
    "tags": ["user_id", "movie_id", "tag", "tag_timestamp"],
    "links": ["movie_id", "imdb_id", "tmdb_id"],
}
SCHEMAS = {"movies": "001_movies.sql", "ratings": "002_ratings.sql",
           "tags": "003_tags.sql", "links": "004_links.sql"}
# Published in the GroupLens ml-32m README. MD5 verifies dataset identity;
# SHA-256 and the value digest are also recorded for reproducibility.
OFFICIAL_MD5 = {
    "movies": "0df90835c19151f9d819d0822e190797",
    "ratings": "cf12b74f9ad4b94a011f079e26d4270a",
    "tags": "963bf4fa4de6b8901868fddd3eb54567",
    "links": "8f033867bcb4e6be8792b21468b4fa6e",
}
PUBLISHED_COUNTS = {"movies": 87585, "ratings": 32000204, "tags": 2000072}


def connection_options(database):
    return dict(host=os.getenv("PGHOST", "127.0.0.1"),
                port=int(os.getenv("PGPORT", "5432")), dbname=database,
                user=os.getenv("PGUSER", "recsys"),
                password=os.getenv("PGPASSWORD", "recsys"), connect_timeout=5)


class ValueDigest:
    """Hash canonical CSV values in bounded batches, not source formatting.

    csv.writer handles quoting, embedded newlines, Unicode, and NULL -> empty
    consistently for parsed source rows and typed PostgreSQL result rows.
    """

    def __init__(self):
        self.hash = hashlib.sha256()
        self.buffer = io.StringIO(newline="")
        self.writer = csv.writer(self.buffer)
        self.rows = 0

    def add(self, row):
        self.writer.writerow(row)
        self.rows += 1
        if self.rows % 10000 == 0:
            self.flush()

    def flush(self):
        self.hash.update(self.buffer.getvalue().encode("utf-8"))
        self.buffer.seek(0)
        self.buffer.truncate(0)

    def hexdigest(self):
        self.flush()
        return self.hash.hexdigest()


def normalize_row(table, row):
    if len(row) != len(HEADERS[table]):
        raise ValueError(f"Unexpected column count in {table}")
    if table == "movies":
        return int(row[0]), row[1] or None, row[2] or None
    if table == "ratings":
        return int(row[0]), int(row[1]), Decimal(row[2]), int(row[3])
    if table == "tags":
        return int(row[0]), int(row[1]), row[2] or None, int(row[3])
    return int(row[0]), row[1] or None, int(row[2]) if row[2] else None


def profile_csv(path, table):
    """Scan complete CSV records; do not count physical lines in tagged text."""
    md5 = hashlib.md5(usedforsecurity=False)
    sha256 = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            md5.update(block)
            sha256.update(block)
    digest = ValueDigest()
    users = set()
    summary = {"rows": 0}
    if table == "tags":
        summary["null_tags"] = 0
    if table == "links":
        summary.update(null_imdb_ids=0, null_tmdb_ids=0, imdb_ids_with_leading_zero=0)
    previous_key = None
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream)
        if next(reader, None) != HEADERS[table]:
            raise ValueError(f"Unexpected CSV header for {table}")
        for raw in reader:
            row = normalize_row(table, raw)
            # Non-tag database reads use primary-key order. Check that source
            # ordering agrees before relying on an ordered value digest.
            if table != "tags":
                key = row[:2] if table == "ratings" else row[:1]
                if previous_key is not None and key < previous_key:
                    raise ValueError(f"Source {table} is not in expected key order")
                previous_key = key
            digest.add(row)
            summary["rows"] += 1
            if table in {"ratings", "tags"}:
                users.add(row[0])
            if table == "tags":
                summary["null_tags"] += row[2] is None
            if table == "links":
                summary["null_imdb_ids"] += row[1] is None
                summary["null_tmdb_ids"] += row[2] is None
                summary["imdb_ids_with_leading_zero"] += bool(row[1] and row[1].startswith("0"))
            if summary["rows"] % 4000000 == 0:
                print(f"Source {table}: {summary['rows']:,} records profiled", flush=True)
    if table in {"ratings", "tags"}:
        summary["users"] = len(users)
    return {"summary": summary, "md5": md5.hexdigest(), "sha256": sha256.hexdigest(),
            "values_sha256": digest.hexdigest(), "bytes": path.stat().st_size}


def load_table(conn, table, path):
    """One atomic table load, including restoration/validation of deferred keys."""
    started = perf_counter()
    relation = sql.Identifier("public", table)
    deferred = []
    with conn.transaction():
        if table in {"ratings", "tags"}:
            deferred = conn.execute("""
                SELECT conname, pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conrelid = %s::regclass AND contype IN ('p', 'f')
                ORDER BY CASE contype WHEN 'p' THEN 0 ELSE 1 END
            """, (f"public.{table}",)).fetchall()
            for name, _ in deferred:
                conn.execute(sql.SQL("ALTER TABLE {} DROP CONSTRAINT {}").format(
                    relation, sql.Identifier(name)))
        command = sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT CSV, HEADER TRUE, ENCODING 'UTF8')").format(
            relation, sql.SQL(", ").join(map(sql.Identifier, COLUMNS[table])))
        with conn.cursor() as cur, path.open("rb") as stream:
            with cur.copy(command) as copy:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    copy.write(block)
        print(f"Copied {table}; building/validating keys before commit", flush=True)
        for name, definition in deferred:
            conn.execute(sql.SQL("ALTER TABLE {} ADD CONSTRAINT {} {}").format(
                relation, sql.Identifier(name), sql.SQL(definition)))
    return {"load_and_key_validation_seconds": perf_counter() - started,
            "deferred_key_names": [name for name, _ in deferred]}


def validate_values(conn, table, source):
    started = perf_counter()
    digest = ValueDigest()
    order = ["user_id", "movie_id"] if table == "ratings" else ["tag_id"] if table == "tags" else ["movie_id"]
    query = sql.SQL("SELECT {} FROM {} ORDER BY {}").format(
        sql.SQL(", ").join(map(sql.Identifier, COLUMNS[table])),
        sql.Identifier("public", table), sql.SQL(", ").join(map(sql.Identifier, order)))
    # A named cursor streams the complete result instead of materializing 32M rows.
    with conn.transaction():
        with conn.cursor(name=f"validate_{table}") as cur:
            cur.itersize = 10000
            cur.execute(query)
            for row in cur:
                digest.add(row)
                if digest.rows % 4000000 == 0:
                    print(f"Database {table}: {digest.rows:,} records verified", flush=True)
    actual = digest.hexdigest()
    if digest.rows != source["summary"]["rows"] or actual != source["values_sha256"]:
        raise ValueError(f"Source/database values differ for {table}")
    return {"rows": digest.rows, "values_sha256": actual,
            "validation_seconds": perf_counter() - started, "matches_source": True}


def ensure_database(database, scope):
    if database in {"postgres", "template0", "template1"}:
        raise ValueError("Choose a project database, not a PostgreSQL system database")
    with psycopg.connect(**connection_options("postgres"), autocommit=True) as admin:
        exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,)).fetchone()
        if not exists:
            if scope == "metadata":
                raise ValueError("Metadata mode requires an existing development database")
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))


def check_target(conn, tables, scope):
    for table in tables:
        if conn.execute("SELECT to_regclass(%s)", (f"public.{table}",)).fetchone()[0]:
            raise ValueError(f"Target table {table} already exists; nothing will be replaced")
    if scope == "full":
        if conn.execute("SELECT COUNT(*) FROM pg_tables WHERE schemaname = 'public'").fetchone()[0]:
            raise ValueError("Full mode requires an empty public schema")
    else:
        for table in ("movies", "ratings"):
            if conn.execute("SELECT to_regclass(%s)", (f"public.{table}",)).fetchone()[0] is None:
                raise ValueError("Metadata mode requires existing movies and ratings tables")


def save_report(path, report):
    # The report was exclusively created by this execution; updates record progress.
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=["metadata", "full"], required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--input-dir", type=Path, default=ROOT / "data/raw/ml-32m")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation means a prior report can never be overwritten by a rerun.
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write("{}\n")
    tables = ["movies", "ratings", "tags", "links"] if args.scope == "full" else ["tags", "links"]
    report = {"status": "running", "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "database": args.database, "scope": args.scope, "sources": {}, "loads": {},
              "value_validation": {}, "phase": "source verification"}
    save_report(args.output, report)
    total_started = perf_counter()
    try:
        for table in tables:
            source = profile_csv(args.input_dir / f"{table}.csv", table)
            report["sources"][table] = source
            if source["md5"] != OFFICIAL_MD5[table]:
                raise ValueError(f"Official checksum mismatch for {table}")
            if table in PUBLISHED_COUNTS and source["summary"]["rows"] != PUBLISHED_COUNTS[table]:
                raise ValueError(f"Published row count mismatch for {table}")
            print(f"Verified source {table}: {source['summary']['rows']:,} records", flush=True)
            save_report(args.output, report)

        ensure_database(args.database, args.scope)
        with psycopg.connect(**connection_options(args.database), autocommit=True) as conn:
            conn.execute("SET search_path TO public")
            check_target(conn, tables, args.scope)
            original = None
            if args.scope == "metadata":
                original = conn.execute("SELECT (SELECT COUNT(*) FROM movies), (SELECT COUNT(*) FROM ratings)").fetchone()
            report["postgres_version"] = conn.execute("SHOW server_version").fetchone()[0]
            with conn.transaction():
                for table in tables:
                    conn.execute((ROOT / "sql/schema" / SCHEMAS[table]).read_text())

            for table in tables:
                report["phase"] = f"load {table}"
                save_report(args.output, report)
                report["loads"][table] = load_table(conn, table, args.input_dir / f"{table}.csv")
                report["phase"] = f"validate every {table} value"
                save_report(args.output, report)
                report["value_validation"][table] = validate_values(conn, table, report["sources"][table])
                print(f"Validated every {table} value against source", flush=True)
                save_report(args.output, report)

            report["phase"] = "indexes and SQL summary"
            save_report(args.output, report)
            with conn.transaction():
                conn.execute((ROOT / "sql/schema/005_ingestion_indexes.sql").read_text())
            for table in ("movies", "ratings", "tags", "links"):
                conn.execute(sql.SQL("ANALYZE {}").format(sql.Identifier("public", table)))
            summary = conn.execute((ROOT / "sql/validation/001_ingestion_summary.sql").read_text()).fetchone()[0]
            report["database_summary"] = summary
            for table in tables:
                if summary[table] != report["sources"][table]["summary"]:
                    raise ValueError(f"SQL/source summary differs for {table}")
            constraints = conn.execute("""
                SELECT c.relname, p.conname, p.contype, p.convalidated
                FROM pg_constraint p JOIN pg_class c ON c.oid = p.conrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relname = ANY(%s)
                ORDER BY c.relname, p.conname
            """, (["movies", "ratings", "tags", "links"],)).fetchall()
            if not all(row[3] for row in constraints):
                raise ValueError("An unvalidated constraint remains")
            report["constraints"] = [dict(table=row[0], name=row[1], kind=row[2], validated=row[3]) for row in constraints]
            report["indexes"] = conn.execute("SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' ORDER BY tablename, indexname").fetchall()
            if original is not None:
                after = (summary["movies"]["rows"], summary["ratings"]["rows"])
                if after != original:
                    raise ValueError("Existing development table counts changed")
                report["existing_movies_and_ratings_counts_unchanged"] = True
            report["database_bytes"] = conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]
        report.update(status="completed", phase="completed",
                      completed_at_utc=datetime.now(timezone.utc).isoformat(),
                      total_seconds=perf_counter() - total_started)
        save_report(args.output, report)
        print(json.dumps(report["database_summary"], indent=2), flush=True)
        print(f"Completed; verified report: {args.output}", flush=True)
    except Exception as exc:
        # Do not log rejected source rows or connection credentials in committed reports.
        report.update(status="failed", error_type=type(exc).__name__,
                      failed_at_utc=datetime.now(timezone.utc).isoformat())
        save_report(args.output, report)
        raise


if __name__ == "__main__":
    main()
