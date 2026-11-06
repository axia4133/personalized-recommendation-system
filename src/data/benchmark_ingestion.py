"""Compare COPY write_row with multi-row INSERT on a development sample.

Run from the repository root:
    python src/data/benchmark_ingestion.py --method both --output experiments/ingestion/run.json

Each trial creates an ordinary table, loads it in one transaction, validates
every value, and removes it. Existing benchmark tables are never overwritten.
"""

import argparse
import csv
import hashlib
import json
import os
import platform
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from statistics import median
from time import perf_counter

import psycopg


def connection_options():
    """Use the same local defaults as docker-compose.yml; do not log passwords."""
    return {
        "host": os.getenv("PGHOST", "127.0.0.1"),
        "port": int(os.getenv("PGPORT", "5432")),
        "dbname": os.getenv("PGDATABASE", "movielens"),
        "user": os.getenv("PGUSER", "recsys"),
        "password": os.getenv("PGPASSWORD", "recsys"),
        "connect_timeout": 5,
    }


def read_ratings(path):
    """Parse once, outside timing; both methods receive identical typed tuples."""
    with Path(path).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["userId", "movieId", "rating", "timestamp"]:
            raise ValueError("Unexpected ratings CSV header")
        rows = [
            (int(row["userId"]), int(row["movieId"]),
             Decimal(row["rating"]), int(row["timestamp"]))
            for row in reader
        ]
    if not rows:
        raise ValueError("Cannot benchmark an empty sample")
    if len({row[:2] for row in rows}) != len(rows):
        raise ValueError("Sample contains duplicate user-movie pairs")
    return rows


def load_with_copy(cur, rows):
    """One COPY operation; Psycopg formats each tuple for the COPY stream."""
    with cur.copy("""
        COPY public.ratings_ingestion_benchmark
            (user_id, movie_id, rating, rating_timestamp)
        FROM STDIN
    """) as copy:
        for row in rows:
            copy.write_row(row)


def load_with_insert(cur, rows, batch_size):
    """Preserve multi-row parameterized INSERT, including the final short batch."""
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        placeholders = ", ".join(["(%s, %s, %s, %s)"] * len(batch))
        parameters = []
        for row in batch:
            parameters.extend(row)
        cur.execute(
            """
            INSERT INTO public.ratings_ingestion_benchmark
                (user_id, movie_id, rating, rating_timestamp)
            VALUES
            """ + placeholders,
            parameters,
        )


def validate_rows(actual, expected):
    # Count alone would miss an incorrect rating, timestamp, or column mapping.
    if actual != expected:
        raise ValueError("Loaded rows differ from the sorted source sample")


def run_trial(conn, rows, expected, method, batch_size):
    if method not in {"insert", "copy"}:
        raise ValueError("Unknown loading method")
    if not 1 <= batch_size <= 10000:
        raise ValueError("Batch size must be between 1 and 10000")
    if not conn.autocommit:
        raise ValueError("Trial runner requires autocommit plus explicit transactions")

    # No IF NOT EXISTS: an existing table belongs to someone else or a prior
    # interrupted run. Failure here must never drop that pre-existing table.
    with conn.transaction():
        conn.execute("""
            CREATE TABLE public.ratings_ingestion_benchmark
            (LIKE public.ratings INCLUDING ALL)
        """)
        conn.execute("""
            ALTER TABLE public.ratings_ingestion_benchmark
            ADD FOREIGN KEY (movie_id) REFERENCES public.movies (movie_id)
        """)

    try:
        with conn.cursor() as cur:
            started = perf_counter()
            # Explicit BEGIN and successful COMMIT are both inside the timer.
            with conn.transaction():
                if method == "copy":
                    load_with_copy(cur, rows)
                else:
                    load_with_insert(cur, rows, batch_size)
            elapsed = perf_counter() - started

            # Post-commit validation and network readback are outside timing.
            cur.execute("""
                SELECT user_id, movie_id, rating, rating_timestamp
                FROM public.ratings_ingestion_benchmark
                ORDER BY user_id, movie_id
            """)
            validate_rows(cur.fetchall(), expected)
        return elapsed
    finally:
        # The transaction context has rolled back any normal loading failure.
        # Cleanup is a separate transaction and never touches source tables.
        conn.execute("DROP TABLE public.ratings_ingestion_benchmark")


def trial_schedule(methods, repeats, warmups):
    for phase, rounds in (("warmup", warmups), ("measured", repeats)):
        for round_index in range(rounds):
            order = methods if round_index % 2 == 0 else list(reversed(methods))
            for method in order:
                yield phase, round_index + 1, method


def summarize(trials, row_count):
    summary = {}
    for method in sorted({trial["method"] for trial in trials}):
        times = [trial["seconds"] for trial in trials
                 if trial["method"] == method and trial["phase"] == "measured"]
        middle = median(times)
        summary[method] = {
            "measured_runs": len(times),
            "median_seconds": middle,
            "min_seconds": min(times),
            "max_seconds": max(times),
            "rows_per_second_at_median": row_count / middle,
        }
    return summary


def source_counts(conn):
    return conn.execute("""
        SELECT (SELECT COUNT(*) FROM public.movies),
               (SELECT COUNT(*) FROM public.ratings)
    """).fetchone()


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Must be a positive integer")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--method", choices=["insert", "copy", "both"], default="both")
    parser.add_argument("--input", type=Path, default=Path("data/processed/ratings_dev.csv"))
    parser.add_argument("--batch-size", type=positive_int, default=1000)
    parser.add_argument("--repeats", type=positive_int, default=3)
    parser.add_argument("--warmups", type=positive_int, default=1)
    parser.add_argument("--output", type=Path, help="New JSON report; existing files are not overwritten")
    args = parser.parse_args()
    if args.batch_size > 10000:
        parser.error("--batch-size cannot exceed 10000 (four parameters per row)")
    if args.output and args.output.exists():
        parser.error("--output already exists; choose a new path")

    started_at = datetime.now(timezone.utc).isoformat()
    # Parsing, conversion, sorting, and hashing all happen before trial timing.
    rows = read_ratings(args.input)
    expected = sorted(rows, key=lambda row: row[:2])
    source_hash = hashlib.sha256(args.input.read_bytes()).hexdigest()
    methods = ["insert", "copy"] if args.method == "both" else [args.method]
    trials = []

    with psycopg.connect(**connection_options(), autocommit=True) as conn:
        original_counts = source_counts(conn)
        settings = {name: conn.execute("SELECT current_setting(%s)", (name,)).fetchone()[0]
                    for name in ("server_version", "fsync", "synchronous_commit", "full_page_writes")}
        for phase, round_number, method in trial_schedule(methods, args.repeats, args.warmups):
            seconds = run_trial(conn, rows, expected, method, args.batch_size)
            trials.append({"phase": phase, "round": round_number, "method": method,
                           "seconds": seconds, "validated_rows": len(rows)})
            print(f"{phase} {round_number}: {method} {seconds:.6f}s; {len(rows)} rows verified")
        if source_counts(conn) != original_counts:
            raise RuntimeError("Original source-table counts changed during benchmark")
        if conn.execute("SELECT to_regclass('public.ratings_ingestion_benchmark')").fetchone()[0]:
            raise RuntimeError("Benchmark table was not cleaned up")

    report = {
        "status": "completed",
        "started_at_utc": started_at,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "configuration": {
            "input": str(args.input), "input_sha256": source_hash,
            "rows": len(rows), "users": len({row[0] for row in rows}),
            "methods": methods, "insert_batch_size": args.batch_size,
            "measured_runs_per_method": args.repeats, "warmups_per_method": args.warmups,
            "order": "Alternate method order by round; INSERT first in round 1",
            "timing_includes": ["BEGIN", "Python loading and parameter construction",
                                "database transfer and execution", "constraints and indexes", "COMMIT"],
            "timing_excludes": ["CSV parsing and type conversion", "connection and table setup",
                                "row validation", "cleanup"],
            "copy_implementation": "Psycopg write_row from typed in-memory tuples (text COPY)",
            "table": "fresh ordinary table each trial, same PK, checks, NOT NULL, movie FK",
        },
        "environment": {"python": platform.python_version(), "psycopg": psycopg.__version__,
                        "platform": platform.platform(), "postgresql_settings": settings},
        "validation": {"every_trial_matches_source_values": True,
                       "original_counts_unchanged": True, "benchmark_table_removed": True,
                       "original_movie_rows": original_counts[0], "original_rating_rows": original_counts[1]},
        "trials": trials,
        "summary": summarize(trials, len(rows)),
    }
    print(json.dumps(report["summary"], indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
        print(f"Saved report: {args.output}")


if __name__ == "__main__":
    main()
