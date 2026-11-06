"""Execute SQL data-quality diagnostics and optionally install validated views.

Examples (repository root):
    python src/data/run_data_quality.py --database movielens_full \
        --create-clean-views --output experiments/quality/full.json

Raw tables are never modified. Activity statistics describe complete history
and must not be reused as model features or temporal eligibility decisions.
"""

import argparse
import hashlib
import json
import os
import platform
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import psycopg
from psycopg import sql


ROOT = Path(__file__).resolve().parents[2]
QUERIES = {
    "core_quality": "010_core_quality.sql",
    "duplicates_and_references": "011_duplicates_and_references.sql",
    "activity_and_sparsity": "012_activity_and_sparsity.sql",
    "timestamp_diagnostics": "013_timestamp_diagnostics.sql",
    "timestamp_boundary_review": "014_timestamp_boundary_review.sql",
}
TABLES = ("movies", "ratings", "tags", "links")


def connection_options(database):
    return dict(host=os.getenv("PGHOST", "127.0.0.1"),
                port=int(os.getenv("PGPORT", "5432")), dbname=database,
                user=os.getenv("PGUSER", "recsys"),
                password=os.getenv("PGPASSWORD", "recsys"), connect_timeout=5)


def load_config(path):
    config = json.loads(Path(path).read_text())
    thresholds = ("minimum_user_history_diagnostic", "sparse_movie_rating_threshold",
                  "source_order_diagnostic_users")
    if any(type(config[name]) is not int or config[name] < 1 for name in thresholds):
        raise ValueError("Diagnostic thresholds must be positive integers")
    dates = [datetime.fromisoformat(config[name]) for name in (
        "documented_window_start_utc", "documented_window_end_exclusive_utc")]
    if any(date.tzinfo is None or date.utcoffset().total_seconds() != 0 for date in dates):
        raise ValueError("Documented window bounds must explicitly use UTC")
    if dates[0] >= dates[1]:
        raise ValueError("Documented window start must precede its exclusive end")
    parameters = {
        "minimum_user_history": config["minimum_user_history_diagnostic"],
        "sparse_movie_threshold": config["sparse_movie_rating_threshold"],
        "order_diagnostic_users": config["source_order_diagnostic_users"],
        "window_start": int(dates[0].timestamp()), "window_end": int(dates[1].timestamp()),
    }
    return config, parameters


def execute_check(conn, filename, parameters):
    query = (ROOT / "sql/validation" / filename).read_text()
    started = perf_counter()
    result = conn.execute(query, parameters).fetchone()[0]
    return {"result": result, "seconds": perf_counter() - started,
            "sql_file": f"sql/validation/{filename}",
            "sql_sha256": hashlib.sha256(query.encode()).hexdigest()}


def check_reconciliations(results):
    """Ensure independently computed totals describe the same population."""
    core = results["core_quality"]["result"]
    activity = results["activity_and_sparsity"]["result"]
    times = results["timestamp_diagnostics"]["result"]
    references = results["duplicates_and_references"]["result"]["references"]
    comparisons = {
        "user_ratings": activity["users"]["ratings"],
        "user_bins": sum(row["ratings"] for row in activity["user_bins"] or []),
        # Catalog bins cannot contain orphan ratings; count those separately so
        # a genuine detected defect does not masquerade as a broken query.
        "movie_bins_plus_orphans": sum(row["ratings"] for row in activity["movie_bins"] or [])
            + references["ratings_without_movie"],
        "rating_distribution": sum(row["rows"] for row in core["rating_distribution"] or []),
        "rating_years": sum(row["rows"] for row in times["rating_years"] or []),
        "time_ratings": times["ratings"]["rows"],
    }
    if any(count != core["ratings"]["rows"] for count in comparisons.values()):
        raise ValueError("Rating counts disagree between diagnostic queries")
    if sum(row["rows"] for row in times["tag_years"] or []) != core["tags"]["rows"]:
        raise ValueError("Tag year counts do not reconcile")
    if sum(row["movies"] for row in activity["movie_bins"] or []) != core["movies"]["rows"]:
        raise ValueError("Movie distribution excludes catalog rows")


def row_counts(conn, schema):
    return {table: conn.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(
        sql.Identifier(schema, table))).fetchone()[0] for table in TABLES}


def install_clean_views(conn, expected_raw_counts):
    definition = (ROOT / "sql/cleaning/001_validated_views.sql").read_text()
    with conn.transaction():
        conn.execute(definition)
        raw = row_counts(conn, "public")
        clean = row_counts(conn, "clean")
        if raw != expected_raw_counts:
            raise ValueError("Raw population changed while the quality workflow was running")
        if any(clean[name] > raw[name] for name in TABLES):
            raise ValueError("Clean view increased rows; investigate reference-key multiplicity")
    return {
        "views_installed": True,
        "sql_file": "sql/cleaning/001_validated_views.sql",
        "sql_sha256": hashlib.sha256(definition.encode()).hexdigest(),
        "raw_rows": raw, "clean_rows": clean,
        "excluded_rows": {table: raw[table] - clean[table] for table in TABLES},
        "policy": "Technical validity only; no activity, popularity, positivity, or documented-window exclusions",
        "raw_tables_modified": False,
    }


def save_report(path, report):
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="movielens_full")
    parser.add_argument("--config", type=Path, default=ROOT / "configs/data_quality.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--create-clean-views", action="store_true")
    args = parser.parse_args()
    config, parameters = load_config(args.config)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write("{}\n")
    report = {
        "status": "running", "database": args.database,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "configuration": config, "sql_parameters": parameters,
        "environment": {"python": platform.python_version(), "psycopg": psycopg.__version__},
        "checks": {}, "phase": "database connection",
        "cleaning": {"views_installed": False, "raw_tables_modified": False},
    }
    save_report(args.output, report)
    started = perf_counter()
    try:
        with psycopg.connect(**connection_options(args.database), autocommit=True) as conn:
            conn.execute("SET TIME ZONE 'UTC'")
            report["environment"]["postgresql"] = conn.execute("SHOW server_version").fetchone()[0]
            with conn.transaction():
                conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                conn.execute("SET LOCAL statement_timeout = '15min'")
                report["audit_snapshot_utc"] = conn.execute("SELECT transaction_timestamp()::text").fetchone()[0]
                report["audit_isolation"] = "REPEATABLE READ, READ ONLY"
                for name, filename in QUERIES.items():
                    report["phase"] = name
                    save_report(args.output, report)
                    print(f"Running {filename} on {args.database}", flush=True)
                    report["checks"][name] = execute_check(conn, filename, parameters)
                    print(f"Completed {name}: {report['checks'][name]['seconds']:.2f}s", flush=True)
                    save_report(args.output, report)
                check_reconciliations(report["checks"])
            if args.create_clean_views:
                report["phase"] = "install validated source views"
                save_report(args.output, report)
                counts = {table: report["checks"]["core_quality"]["result"][table]["rows"] for table in TABLES}
                report["cleaning"] = install_clean_views(conn, counts)
            report["reconciliations_passed"] = True
        report.update(status="completed", phase="completed",
                      completed_at_utc=datetime.now(timezone.utc).isoformat(),
                      total_seconds=perf_counter() - started)
        save_report(args.output, report)
        print(f"Quality report complete: {args.output}", flush=True)
        print(json.dumps(report["cleaning"], indent=2), flush=True)
    except Exception as exc:
        report.update(status="failed", error_type=type(exc).__name__,
                      failed_at_utc=datetime.now(timezone.utc).isoformat())
        save_report(args.output, report)
        raise


if __name__ == "__main__":
    main()
