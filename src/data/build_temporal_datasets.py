"""Create versioned chronological ranking datasets without training models.

Run with python -m src.data.build_temporal_datasets from the repository root.
Feature snapshots commit independently; the dataset schema is built atomically.
"""

import argparse
import copy
import hashlib
import json
import math
import platform
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import psycopg
from psycopg import sql

from src.features import build_sql_features as features


ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = ROOT / "sql/splits"
TABLES = ["partition_metadata", "candidate_catalog", "label_events", "positive_truth",
          "ranking_users", "training_examples", "negative_sampling_audit"]


def validate_schema(schema):
    if not isinstance(schema, str) or not re.fullmatch(r"datasets_[a-z0-9_]{1,54}", schema):
        raise ValueError("Use a lowercase datasets_* schema of at most 63 characters")


def utc_epoch(value):
    date = datetime.fromisoformat(value)
    if date.tzinfo is None or date.utcoffset().total_seconds() != 0 or date.microsecond:
        raise ValueError("Protocol times must explicitly use UTC and whole seconds")
    if date.timestamp() < 0:
        raise ValueError("Protocol time is before the Unix epoch")
    return int(date.timestamp())


def validate_protocol(config):
    validate_schema(config["dataset_schema"])
    threshold = config["positive_rating_threshold"]
    if type(threshold) not in (int,float) or not math.isfinite(threshold) or not 0.5 <= threshold <= 5 or threshold * 2 % 1:
        raise ValueError("Positive rating threshold must be a half-star value in range")
    for name in ("minimum_history_ratings", "unobserved_per_positive", "work_mem_mb"):
        if type(config[name]) is not int or config[name] < 1:
            raise ValueError(f"{name} must be a positive integer")
    if not 1 <= config["unobserved_per_positive"] <= 20 or not 4 <= config["work_mem_mb"] <= 256:
        raise ValueError("Negative ratio or per-operator memory is outside supported range")
    if type(config["negative_seed"]) is not int or not 0 <= config["negative_seed"] < 2**63:
        raise ValueError("Seed must be a nonnegative 63-bit integer")
    if type(config["parallel_workers_per_gather"]) is not int or not 0 <= config["parallel_workers_per_gather"] <= 4:
        raise ValueError("Unsupported query worker setting")
    if not config["primary_ranking_k"] or any(type(k) is not int or k < 1 for k in config["primary_ranking_k"]):
        raise ValueError("Ranking K values must be positive integers")
    if config["default_feature_group"] != "behavioral_pair_features":
        raise ValueError("Default protocol must not silently enable unversioned metadata")
    partitions = config["partitions"]
    if [p["name"] for p in partitions] != ["train","validation","test"]:
        raise ValueError("Exactly ordered train, validation, test partitions are required")
    output = []
    for partition in partitions:
        features.validate_schema(partition["feature_schema"])
        cutoff, end = utc_epoch(partition["cutoff_utc"]), utc_epoch(partition["label_end_utc"])
        if cutoff >= end:
            raise ValueError("Label window must have positive duration")
        if output and output[-1]["label_end"] != cutoff:
            raise ValueError("Label windows must be adjacent and nonoverlapping")
        output.append(dict(split=partition["name"], cutoff=cutoff, label_end=end,
                           feature_schema=partition["feature_schema"],
                           positive_threshold=float(threshold),
                           minimum_history=config["minimum_history_ratings"]))
    if len({p["feature_schema"] for p in output}) != 3:
        raise ValueError("Each partition needs its own cutoff-bound feature schema")
    return output


def set_dataset_path(conn, schema):
    validate_schema(schema)
    conn.execute(sql.SQL("SET LOCAL search_path TO {}, pg_catalog").format(sql.Identifier(schema)))


def bind_or_build_features(conn, partition, base_config):
    """Reuse only a validated, exactly matching feature-time contract."""
    cfg = copy.deepcopy(base_config)
    cfg["cutoff_utc"] = datetime.fromtimestamp(partition["cutoff"], timezone.utc).isoformat()
    cfg["snapshot_schema"] = partition["feature_schema"]
    parameters = features.feature_parameters(cfg)
    schema = partition["feature_schema"]
    if conn.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (schema,)).fetchone() is None:
        print(f"Building missing {partition['split']} snapshot {schema}", flush=True)
        result = features.build_snapshot(conn, schema, cfg,
            lambda filename: print(f"  {schema}: {filename}", flush=True))
        return {"reused": False, "configuration": cfg, "snapshot": result}
    with conn.transaction():
        features.set_snapshot_path(conn, schema)
        conn.execute("SELECT set_config('work_mem', %s, true)", (f"{cfg['work_mem_mb']}MB",))
        conn.execute("SET LOCAL max_parallel_workers_per_gather=0")
        context = conn.execute("""
            SELECT cutoff_epoch, recent_window_days, movie_prior_count, genre_prior_weight,
                   genre_metadata_policy, source_database, source_rating_rows
            FROM snapshot_context
        """).fetchall()
        expected = (parameters["cutoff"], parameters["recent_window_days"], parameters["movie_prior_count"],
                    parameters["genre_prior_weight"], parameters["genre_metadata_policy"],
                    conn.info.dbname)
        if len(context) != 1 or context[0][:6] != expected:
            raise ValueError(f"Existing {schema} has a different feature contract")
        if context[0][6] != conn.execute("SELECT COUNT(*) FROM clean.ratings").fetchone()[0]:
            raise ValueError("Source population changed since the feature snapshot")
        validation = features.validate_snapshot(conn, parameters)
    print(f"Reused and revalidated {schema}", flush=True)
    return {"reused": True, "configuration": cfg, "schema": schema, "validation": validation}


def sample_unobserved(catalog, catalog_set, excluded, requested, seed, user_id):
    """Uniform proposals + rejection yield sampling without replacement.

    A bounded rejection phase avoids scanning the catalog for ordinary users.
    Dense/exhausted pools fall back to an explicit remaining-pool uniform sample.
    All randomness is independent per user, not dependent on cursor batching.
    """
    if not catalog or len(catalog) != len(catalog_set):
        raise ValueError("Catalog must contain unique items")
    if type(requested) is not int or requested < 0:
        raise ValueError("Requested count must be a nonnegative integer")
    excluded = set(excluded)
    available = len(catalog) - len(excluded & catalog_set)
    quota = min(requested, available)
    digest = hashlib.sha256(f"unobserved_v1:{seed}:{user_id}".encode()).digest()
    rng = random.Random(int.from_bytes(digest[:8], "big"))
    selected = set()
    proposals = 0
    while len(selected) < quota and proposals < max(64, 4 * quota):
        movie = catalog[rng.randrange(len(catalog))]
        proposals += 1
        if movie not in excluded:
            selected.add(movie)
    fallback = len(selected) < quota
    if fallback:
        remaining = [movie for movie in catalog if movie not in excluded and movie not in selected]
        selected.update(rng.sample(remaining, quota - len(selected)))
    return sorted(selected), available, proposals, fallback


def populate_training_negatives(conn, schema, train_schema, ratio, seed):
    with conn.transaction():
        set_dataset_path(conn, schema)
        expected_schema = conn.execute("SELECT feature_schema FROM partition_metadata WHERE split='train'").fetchone()[0]
        if expected_schema != train_schema:
            raise ValueError("Sampler feature binding must be the training snapshot")
        catalog = [row[0] for row in conn.execute("SELECT movie_id FROM candidate_catalog WHERE split='train' ORDER BY movie_index")]
        if not catalog:
            raise ValueError("Training catalog is empty")
        catalog_set = set(catalog)
        query = sql.SQL((SQL_DIR / "005_negative_sources.sql").read_text()).format(train_schema=sql.Identifier(train_schema))
        with conn.cursor(name="negative_sources") as source:
            source.execute(query)
            while batch := source.fetchmany(128):
                audits = []
                # Finish COPY before fetching the next server-cursor batch.
                with conn.cursor() as writer:
                    with writer.copy("COPY training_examples (user_id,movie_id,target_label,label_source,observed_rating,observed_timestamp) FROM STDIN") as copy_stream:
                        for user_id, positive_count, excluded in batch:
                            requested = positive_count * ratio
                            sampled, available, proposals, fallback = sample_unobserved(
                                catalog, catalog_set, excluded, requested, seed, user_id)
                            for movie_id in sampled:
                                copy_stream.write_row((user_id,movie_id,0,"sampled_unobserved",None,None))
                            audits.append((user_id,positive_count,requested,available,len(sampled),proposals,fallback))
                    writer.executemany("INSERT INTO negative_sampling_audit VALUES (%s,%s,%s,%s,%s,%s,%s)", audits)
        return hashlib.sha256(",".join(map(str,catalog)).encode()).hexdigest()


def evaluation_candidates(conn, schema, split, user_id):
    if split not in ("train","validation","test") or type(user_id) is not int or user_id < 1:
        raise ValueError("Invalid candidate request")
    with conn.transaction():
        set_dataset_path(conn,schema)
        return [row[0] for row in conn.execute((SQL_DIR / "006_evaluation_candidates.sql").read_text(),
            {"split":split,"user_id":user_id})]


def training_batch(conn, schema, limit=1000, after=None):
    """Keyset batch with train-only labels and the default behavioral whitelist."""
    if type(limit) is not int or not 1 <= limit <= 10000:
        raise ValueError("Batch limit must be 1..10000")
    with conn.transaction():
        set_dataset_path(conn,schema)
        binding = conn.execute("SELECT feature_schema FROM partition_metadata WHERE split='train'").fetchone()[0]
        rows = conn.execute("""
            SELECT user_id,movie_id,target_label,label_source FROM training_examples
            WHERE (user_id,movie_id) > (%s,%s) ORDER BY user_id,movie_id LIMIT %s
        """, (*(after or (0,0)),limit)).fetchall()
        if not rows:
            return []
        pair_features = features.fetch_pair_features(conn,binding,[(row[0],row[1]) for row in rows])
        by_pair = {(row["user_id"],row["movie_id"]):row for row in pair_features}
        contract = json.loads((ROOT / "configs/feature_contract.json").read_text())
        fields = contract["behavioral_pair_features"] + contract["history_availability_indicators"]
        return [{"user_id":u,"movie_id":m,"target_label":target,"label_source":source,
                 "feature_schema":binding,"features":{name:by_pair[(u,m)][name] for name in fields}}
                for u,m,target,source in rows]


def make_history_views(conn, partitions):
    pairs, users = [], []
    for p in partitions:
        pairs.append(sql.SQL("SELECT {}::text AS split,user_id,movie_id FROM {}.history_ratings").format(
            sql.Literal(p["split"]),sql.Identifier(p["feature_schema"])))
        users.append(sql.SQL("SELECT {}::text AS split,user_id,rating_count AS history_count FROM {}.user_features").format(
            sql.Literal(p["split"]),sql.Identifier(p["feature_schema"])))
    conn.execute(sql.SQL("CREATE VIEW historical_pairs AS ") + sql.SQL(" UNION ALL ").join(pairs))
    conn.execute(sql.SQL("CREATE VIEW history_user_counts AS ") + sql.SQL(" UNION ALL ").join(users))
    # All observations available before the initial validation prediction date.
    # This supports collaborative models without exposing validation/test events.
    conn.execute(sql.SQL("CREATE VIEW training_observations AS SELECT * FROM {}.history_ratings").format(
        sql.Identifier(partitions[1]["feature_schema"])))


def validate_datasets(conn, partitions):
    summary = conn.execute((SQL_DIR / "007_validate_and_summarize.sql").read_text()).fetchone()[0]
    for key in ("invalid_label_windows","invalid_positive_truth","invalid_training_negatives",
                "invalid_training_positives","invalid_ranking_users","sampling_budget_mismatches"):
        if summary[key] != 0:
            raise ValueError(f"Dataset validation failed: {key}")
    by_split = {row["split"]:row for row in summary["partitions"]}
    for partition in partitions:
        expected = conn.execute("SELECT COUNT(*) FROM clean.ratings WHERE rating_timestamp >= %s AND rating_timestamp < %s",
            (partition["cutoff"],partition["label_end"])).fetchone()[0]
        observed = by_split[partition["split"]]
        if observed["window_ratings"] != expected or sum((observed["status_counts"] or {}).values()) != expected:
            raise ValueError("Label window or exclusion counts do not reconcile")
    if summary["training"]["positive_rows"] != by_split["train"]["eligible_positive_labels"]:
        raise ValueError("Training positives differ from training truth")
    if summary["training"]["sampled_unobserved_rows"] != summary["sampling"]["sampled"]:
        raise ValueError("Training negative count differs from audit")
    if summary["training"]["positive_rows"] == 0:
        raise ValueError("No eligible training positives; do not publish an empty experiment")
    return summary


def user_coverage(conn):
    rows=conn.execute((SQL_DIR / "008_user_coverage.sql").read_text()).fetchone()[0]
    for row in rows:
        if row["window_users"] != row["window_cold_users"]+row["window_sparse_users"]+row["window_warm_users"]:
            raise ValueError("User history cohorts do not reconcile")
        if row["inconsistent_history_count_users"] or row["ranking_users"] > row["window_warm_users"]:
            raise ValueError("Invalid outcome-conditioned user cohort")
    return rows


def audit_existing(conn,schema,config):
    partitions=validate_protocol(config)
    with conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        conn.execute("SET LOCAL work_mem='64MB'")
        conn.execute("SET LOCAL max_parallel_workers_per_gather=0")
        set_dataset_path(conn,schema)
        actual=conn.execute("SELECT split,feature_schema,cutoff_epoch,label_end_epoch,positive_threshold,minimum_history FROM partition_metadata ORDER BY CASE split WHEN 'train' THEN 0 WHEN 'validation' THEN 1 ELSE 2 END").fetchall()
        expected=[(p["split"],p["feature_schema"],p["cutoff"],p["label_end"],p["positive_threshold"],p["minimum_history"]) for p in partitions]
        if actual!=expected:
            raise ValueError("Existing dataset protocol differs from requested configuration")
        return {"user_coverage":user_coverage(conn),
                "audit_snapshot_utc":conn.execute("SELECT transaction_timestamp()::text").fetchone()[0],
                "coverage_sql_sha256":hashlib.sha256((SQL_DIR / "008_user_coverage.sql").read_bytes()).hexdigest(),
                "read_only":True}


def build_dataset_schema(conn, schema, config, feature_bindings, progress=None):
    validate_schema(schema)
    partitions = validate_protocol(config)
    result = {"sql_sha256":{path.name:hashlib.sha256(path.read_bytes()).hexdigest()
                           for path in sorted(SQL_DIR.glob("*.sql"))}}
    with conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        conn.execute("SET LOCAL TIME ZONE 'UTC'")
        conn.execute("SET LOCAL statement_timeout='20min'")
        conn.execute("SELECT set_config('work_mem',%s,true)",(f"{config['work_mem_mb']}MB",))
        conn.execute("SELECT set_config('max_parallel_workers_per_gather',%s,true)",
                     (str(config["parallel_workers_per_gather"]),))
        if conn.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s",(schema,)).fetchone():
            raise ValueError("Dataset schema already exists; choose a new name")
        for p in partitions:
            if p["split"] not in feature_bindings:
                raise ValueError("All partition feature bindings must be verified")
            contexts = conn.execute(sql.SQL("SELECT cutoff_epoch FROM {}.snapshot_context").format(
                sql.Identifier(p["feature_schema"]))).fetchall()
            if contexts != [(p["cutoff"],)]:
                raise ValueError("Dataset cutoff differs from its bound feature snapshot")
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        set_dataset_path(conn,schema)
        conn.execute((SQL_DIR / "001_tables.sql").read_text())
        for p in partitions:
            if progress:
                progress(f"labels and catalog: {p['split']}")
            conn.execute("INSERT INTO partition_metadata VALUES (%s,%s,%s,%s,%s,%s)",
                (p["split"],p["feature_schema"],p["cutoff"],p["label_end"],p["positive_threshold"],p["minimum_history"]))
            for filename in ("002_catalog.sql","003_label_events.sql"):
                query=sql.SQL((SQL_DIR / filename).read_text()).format(feature_schema=sql.Identifier(p["feature_schema"]))
                conn.execute(query,p)
        make_history_views(conn,partitions)
        conn.execute((SQL_DIR / "004_derived_sets.sql").read_text())
        for table in ("label_events","positive_truth","ranking_users","candidate_catalog"):
            conn.execute(sql.SQL("ANALYZE {}").format(sql.Identifier(table)))
        if progress:
            progress("training-only unobserved sampling")
        result["training_catalog_sha256"] = populate_training_negatives(
            conn,schema,partitions[0]["feature_schema"],config["unobserved_per_positive"],config["negative_seed"])
        for table in TABLES:
            conn.execute(sql.SQL("ANALYZE {}").format(sql.Identifier(table)))
        if progress:
            progress("dataset validation and coverage summaries")
        result["summary"] = validate_datasets(conn,partitions)
        result["user_coverage"] = user_coverage(conn)
        # Reconcile the complete source timeline, not only retained labels.
        source = conn.execute("""
            SELECT COUNT(*), COUNT(*) FILTER (WHERE rating_timestamp < %s),
                   COUNT(*) FILTER (WHERE rating_timestamp >= %s)
            FROM clean.ratings
        """,(partitions[0]["cutoff"],partitions[-1]["label_end"])).fetchone()
        windows = sum(p["window_ratings"] for p in result["summary"]["partitions"])
        if source[0] != source[1] + windows + source[2]:
            raise ValueError("Complete source timeline does not reconcile")
        result["source_timeline"] = dict(total=source[0],before_training_labels=source[1],
                                        label_windows=windows,at_or_after_test_end=source[2])
        result["initial_fit_observations"] = conn.execute("SELECT COUNT(*),MAX(rating_timestamp) FROM training_observations").fetchone()
        if result["initial_fit_observations"][1] >= partitions[1]["cutoff"]:
            raise ValueError("Validation observations entered initial fitting view")
    result["table_bytes"] = {table:conn.execute("SELECT pg_total_relation_size(%s::regclass)",
        (f"{schema}.{table}",)).fetchone()[0] for table in TABLES}
    return result


def save_report(path,report):
    temporary=path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    temporary.replace(path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database",default="movielens_full")
    parser.add_argument("--config",type=Path,default=ROOT / "configs/temporal_protocol.json")
    parser.add_argument("--feature-config",type=Path,default=ROOT / "configs/features.json")
    parser.add_argument("--schema")
    parser.add_argument("--audit-existing",action="store_true",help="Read-only coverage audit; do not build or sample")
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    config=json.loads(args.config.read_text())
    partitions=validate_protocol(config)
    schema=args.schema or config["dataset_schema"]
    validate_schema(schema)
    base_features=json.loads(args.feature_config.read_text())
    features.feature_parameters(base_features)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x",encoding="utf-8") as stream:
        stream.write("{}\n")
    report={"status":"running","database":args.database,"schema":schema,
            "configuration":config,"feature_configuration":base_features,"feature_bindings":{},
            "started_at_utc":datetime.now(timezone.utc).isoformat(),"phase":"connect",
            "scope":"Problem/data definition only; no models or ranking metrics"}
    save_report(args.output,report)
    started=perf_counter()
    def progress(phase):
        report["phase"]=phase
        save_report(args.output,report)
        print(phase,flush=True)
    try:
        with psycopg.connect(**features.connection_options(args.database),autocommit=True) as conn:
            if not args.audit_existing and conn.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s",(schema,)).fetchone():
                raise ValueError("Dataset schema already exists")
            report["environment"]={"python":platform.python_version(),
                "psycopg":psycopg.__version__,"postgresql":conn.execute("SHOW server_version").fetchone()[0]}
            if args.audit_existing:
                progress("read-only user coverage audit")
                report["datasets"]=audit_existing(conn,schema,config)
            else:
                for p in partitions:
                    progress(f"bind features: {p['split']}")
                    report["feature_bindings"][p["split"]]=bind_or_build_features(conn,p,base_features)
                    save_report(args.output,report)
                progress("build dataset tables")
                report["datasets"]=build_dataset_schema(conn,schema,config,report["feature_bindings"],progress)
        report.update(status="completed",phase="completed",total_seconds=perf_counter()-started,
            completed_at_utc=datetime.now(timezone.utc).isoformat())
        save_report(args.output,report)
        print(json.dumps(report["datasets"].get("summary",report["datasets"]),indent=2),flush=True)
    except Exception as exc:
        report.update(status="failed",error_type=type(exc).__name__,failed_at_utc=datetime.now(timezone.utc).isoformat())
        save_report(args.output,report)
        raise


if __name__=="__main__":
    main()
