"""Build an isolated, atomic pre-cutoff SQL feature snapshot.

Run from the repository root with python -m src.features.build_sql_features.
No labels, chronological splits, model training, or dense user-item matrix are
created. Static genre metadata requires an explicit unversioned-data assumption.
"""

import argparse
import hashlib
import json
import math
import os
import platform
import re
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = ROOT / "sql/features"
BUILD_FILES = [
    "001_history.sql", "002_history_indexes.sql", "003_movie_genres.sql",
    "004_user_features.sql", "005_movie_features.sql", "006_user_genre_features.sql",
    "007_user_history_features.sql", "008_snapshot_context.sql", "009_feature_indexes.sql",
]
TABLES = ["history_ratings", "movie_genres", "user_features", "movie_features",
          "user_genre_features", "user_history_features", "snapshot_context",
          "example_user_item_features"]


def connection_options(database):
    return dict(host=os.getenv("PGHOST", "127.0.0.1"),
                port=int(os.getenv("PGPORT", "5432")), dbname=database,
                user=os.getenv("PGUSER", "recsys"),
                password=os.getenv("PGPASSWORD", "recsys"), connect_timeout=5)


def validate_schema(schema):
    if not isinstance(schema, str) or not re.fullmatch(r"features_[a-z0-9_]{1,54}", schema):
        raise ValueError("Use a lowercase features_* schema name, at most 63 characters")


def feature_parameters(config):
    validate_schema(config["snapshot_schema"])
    cutoff = datetime.fromisoformat(config["cutoff_utc"])
    if cutoff.tzinfo is None or cutoff.utcoffset().total_seconds() != 0 or cutoff.microsecond:
        raise ValueError("Cutoff must explicitly use UTC and whole seconds")
    if cutoff.timestamp() < 0:
        raise ValueError("Cutoff must be at or after the Unix epoch")
    for name in ("recent_window_days", "example_users", "example_movies", "work_mem_mb"):
        if type(config[name]) is not int or config[name] < 1:
            raise ValueError(f"{name} must be a positive integer")
    if config["example_users"] * config["example_movies"] > 10000:
        raise ValueError("Example pairs are limited to 10000")
    if not 4 <= config["work_mem_mb"] <= 256:
        raise ValueError("work_mem_mb must be between 4 and 256 per SQL operator")
    workers = config.get("parallel_workers_per_gather", 0)
    if type(workers) is not int or not 0 <= workers <= 4:
        raise ValueError("parallel_workers_per_gather must be an integer from 0 to 4")
    for name in ("movie_prior_count", "genre_prior_weight"):
        if type(config[name]) not in (int, float) or not math.isfinite(config[name]) or config[name] <= 0:
            raise ValueError(f"{name} must be finite and positive")
    if config["genre_metadata_policy"] != "static_unversioned_assumption":
        raise ValueError("MovieLens cannot establish historical genre metadata availability")
    if type(config["inspect_query_plans"]) is not bool:
        raise ValueError("inspect_query_plans must be boolean")
    epoch = int(cutoff.timestamp())
    return {
        "cutoff": epoch, "cutoff_utc": cutoff.isoformat(),
        "recent_start": epoch - config["recent_window_days"] * 86400,
        "recent_window_days": config["recent_window_days"],
        "movie_prior_count": float(config["movie_prior_count"]),
        "genre_prior_weight": float(config["genre_prior_weight"]),
        "genre_metadata_policy": config["genre_metadata_policy"],
    }


def set_snapshot_path(conn, schema):
    validate_schema(schema)
    conn.execute(sql.SQL("SET LOCAL search_path TO {}, pg_catalog").format(sql.Identifier(schema)))


def validate_pairs(pairs):
    if not isinstance(pairs, list) or not pairs or len(pairs) > 10000:
        raise ValueError("Supply 1..10000 user/movie pairs")
    output = []
    for pair in pairs:
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise ValueError("Each pair must contain a user ID and a movie ID")
        if any(type(value) is not int or not 1 <= value <= 2147483647 for value in pair):
            raise ValueError("Pair IDs must be positive PostgreSQL integers")
        output.append({"user_id": pair[0], "movie_id": pair[1]})
    return output


def fetch_pair_features(conn, schema, pairs):
    """Read-only bounded lookup with cold/seen-item flags; no labels inferred."""
    parameters = {"pairs": Jsonb(validate_pairs(pairs))}
    with conn.transaction():
        set_snapshot_path(conn, schema)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute((SQL_DIR / "010_user_item_features.sql").read_text(), parameters)
            return cur.fetchall()


def inspect_history_lookup(conn, user_id):
    return conn.execute("""
        EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
        SELECT movie_id, rating, rating_timestamp FROM history_ratings
        WHERE user_id = %s ORDER BY rating_timestamp, movie_id LIMIT 50
    """, (user_id,)).fetchone()[0]


def validate_snapshot(conn, parameters):
    result = conn.execute((SQL_DIR / "011_validate_snapshot.sql").read_text(), parameters).fetchone()[0]
    total = result["history_rows"]
    if total <= 0:
        raise ValueError("No history before cutoff; choose a meaningful snapshot")
    for key in ("source_rows_before_cutoff", "ratings_summed_over_users", "ratings_summed_over_movies"):
        if result[key] != total:
            raise ValueError(f"Feature/source populations do not reconcile: {key}")
    if result["users"] != result["user_history_rows"]:
        raise ValueError("User summary population differs")
    for key in ("future_history_rows", "invalid_user_rows", "invalid_movie_rows",
                "invalid_genre_rows", "invalid_affinity_rows", "genre_weight_mismatch_users"):
        if result[key] != 0:
            raise ValueError(f"Feature validation failed: {key}")
    if result["max_history_timestamp"] >= parameters["cutoff"]:
        raise ValueError("A source event at/after cutoff entered the snapshot")
    if not math.isclose(result["popularity_share_sum"], 1.0, abs_tol=1e-9):
        raise ValueError("Movie popularity shares do not sum to one")
    return result


def build_snapshot(conn, schema, config, progress=None):
    """One repeatable-read transaction: failure rolls back the whole new schema."""
    validate_schema(schema)
    parameters = feature_parameters(config)
    if not conn.autocommit:
        raise ValueError("Builder requires autocommit with explicit transactions")
    result = {"schema": schema, "stages": [], "query_plans": {}, "sql_sha256": {}}
    with conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        conn.execute("SET LOCAL TIME ZONE 'UTC'")
        conn.execute("SET LOCAL statement_timeout = '20min'")
        conn.execute("SELECT set_config('work_mem', %s, true)", (f"{config['work_mem_mb']}MB",))
        # Docker's default /dev/shm is only 64 MiB. Avoid parallel hash shared
        # memory pressure without changing global settings or the container.
        conn.execute("SELECT set_config('max_parallel_workers_per_gather', %s, true)",
                     (str(config.get("parallel_workers_per_gather", 0)),))
        result["execution_settings"] = {name: conn.execute("SELECT current_setting(%s)", (name,)).fetchone()[0]
            for name in ("work_mem", "max_parallel_workers_per_gather", "max_parallel_maintenance_workers")}
        result["source_snapshot_utc"] = conn.execute("SELECT transaction_timestamp()::text").fetchone()[0]
        if conn.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema,)).fetchone():
            raise ValueError("Feature schema already exists; select a new name")
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        set_snapshot_path(conn, schema)
        lookup_user = None
        for filename in BUILD_FILES:
            if progress:
                progress(filename)
            query = (SQL_DIR / filename).read_text()
            result["sql_sha256"][filename] = hashlib.sha256(query.encode()).hexdigest()
            started = perf_counter()
            conn.execute(query, parameters if "%(" in query else None)
            if filename == "001_history.sql":
                lookup_user = conn.execute("SELECT MIN(user_id) FROM history_ratings").fetchone()[0]
                if lookup_user is None:
                    raise ValueError("No history before cutoff")
                conn.execute("ANALYZE history_ratings")
                if config["inspect_query_plans"]:
                    result["query_plans"]["before_history_indexes"] = inspect_history_lookup(conn, lookup_user)
            elif filename == "002_history_indexes.sql":
                conn.execute("ANALYZE history_ratings")
                if config["inspect_query_plans"]:
                    result["query_plans"]["after_history_indexes"] = inspect_history_lookup(conn, lookup_user)
            result["stages"].append({"sql_file": filename, "seconds": perf_counter() - started})

        for table in TABLES[:-1]:
            conn.execute(sql.SQL("ANALYZE {}").format(sql.Identifier(table)))
        if progress:
            progress("011_validate_snapshot.sql")
        result["validation"] = validate_snapshot(conn, parameters)

        users = conn.execute("SELECT user_id FROM user_features ORDER BY user_id LIMIT %s",
                             (config["example_users"],)).fetchall()
        movies = conn.execute("SELECT movie_id FROM movie_features ORDER BY rating_count DESC, movie_id LIMIT %s",
                              (config["example_movies"],)).fetchall()
        pairs = [(user[0], movie[0]) for user in users for movie in movies]
        pair_query = (SQL_DIR / "010_user_item_features.sql").read_text()
        conn.execute("CREATE TABLE example_user_item_features AS " + pair_query,
                     {"pairs": Jsonb(validate_pairs(pairs))})
        conn.execute("ALTER TABLE example_user_item_features ADD PRIMARY KEY (user_id, movie_id)")
        examples = conn.execute("""
            SELECT COUNT(*), COUNT(*) FILTER (WHERE has_prior_rating),
                   COUNT(*) FILTER (WHERE eligible_under_observed_catalog_policy)
            FROM example_user_item_features
        """).fetchone()
        if examples[0] != len(pairs) or examples[1] + examples[2] != examples[0]:
            raise ValueError("Example pair populations/seen flags disagree")
        result["example_pairs"] = {"rows": examples[0], "previously_rated": examples[1],
                                   "eligible_under_observed_catalog_policy": examples[2],
                                   "labels_created": False}
        for filename in ("010_user_item_features.sql", "011_validate_snapshot.sql"):
            result["sql_sha256"][filename] = hashlib.sha256((SQL_DIR / filename).read_bytes()).hexdigest()
        result["context"] = conn.execute("""
            SELECT jsonb_build_object('source_rating_rows', source_rating_rows,
                'history_rows', history_rows, 'min_history_timestamp', min_history_timestamp,
                'max_history_timestamp', max_history_timestamp, 'global_mean_rating', global_mean_rating,
                'genre_metadata_policy', genre_metadata_policy) FROM snapshot_context
        """).fetchone()[0]
    # Returning here means all tables, indexes, and validations committed.
    result["table_bytes"] = {table: conn.execute("SELECT pg_total_relation_size(%s::regclass)",
        (f"{schema}.{table}",)).fetchone()[0] for table in TABLES}
    result["total_table_bytes"] = sum(result["table_bytes"].values())
    return result


def save_report(path, report):
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="movielens_full")
    parser.add_argument("--config", type=Path, default=ROOT / "configs/features.json")
    parser.add_argument("--schema", help="Fresh features_* schema; existing schemas are refused")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    parameters = feature_parameters(config)
    schema = args.schema or config["snapshot_schema"]
    validate_schema(schema)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write("{}\n")
    report = {
        "status": "running", "database": args.database, "schema": schema,
        "started_at_utc": datetime.now(timezone.utc).isoformat(), "configuration": config,
        "sql_parameters": parameters,
        "environment": {"python": platform.python_version(), "psycopg": psycopg.__version__,
                        "platform": platform.platform()},
        "scope": "Exploratory frozen features; no labels, splits, trained model, or ranking metrics",
        "behavioral_policy": "rating_timestamp strictly less than cutoff",
        "metadata_limitation": "Genre labels are static and unversioned; historical availability cannot be verified",
        "phase": "connect",
    }
    save_report(args.output, report)
    started = perf_counter()

    def progress(filename):
        report["phase"] = filename
        save_report(args.output, report)
        print(f"Running {filename} on {args.database}.{schema}", flush=True)

    try:
        with psycopg.connect(**connection_options(args.database), autocommit=True) as conn:
            report["environment"]["postgresql"] = conn.execute("SHOW server_version").fetchone()[0]
            report["snapshot"] = build_snapshot(conn, schema, config, progress)
        report.update(status="completed", phase="completed",
                      completed_at_utc=datetime.now(timezone.utc).isoformat(),
                      total_seconds=perf_counter() - started)
        save_report(args.output, report)
        print(json.dumps(report["snapshot"]["validation"], indent=2), flush=True)
        print(f"Completed snapshot report: {args.output}", flush=True)
    except Exception as exc:
        report.update(status="failed", error_type=type(exc).__name__,
                      failed_at_utc=datetime.now(timezone.utc).isoformat())
        save_report(args.output, report)
        raise


if __name__ == "__main__":
    main()
