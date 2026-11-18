"""Temporal ownership, historical candidates, and train-only sampling tests."""

import json
import os
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from src.data import build_temporal_datasets as datasets
from src.features import build_sql_features as features


def protocol():
    config=json.loads((datasets.ROOT / "configs/temporal_protocol.json").read_text())
    config.update(minimum_history_ratings=2,unobserved_per_positive=2,primary_ranking_k=[1,2])
    for partition,name in zip(config["partitions"],["features_training","features_validation","features_testing"]):
        partition["feature_schema"]=name
    return config


@pytest.fixture
def database():
    if os.getenv("RECSYS_TEST_DATABASE") != "1":
        pytest.skip("Set RECSYS_TEST_DATABASE=1 for temporal dataset integration tests")
    name=f"recsys_datasets_test_{uuid4().hex}"
    with psycopg.connect(**features.connection_options("postgres"),autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            with psycopg.connect(**features.connection_options(name),autocommit=True) as conn:
                for filename in ("001_movies.sql","002_ratings.sql","003_tags.sql","004_links.sql"):
                    conn.execute((features.ROOT / "sql/schema" / filename).read_text())
                conn.execute((features.ROOT / "sql/cleaning/001_validated_views.sql").read_text())
                with conn.cursor() as cur:
                    cur.executemany("INSERT INTO movies VALUES (%s,%s,'Action')",[(i,f'Movie {i}') for i in range(1,14)])
                partitions=datasets.validate_protocol(protocol())
                train,val,test=[p["cutoff"] for p in partitions]
                end=partitions[-1]["label_end"]
                rows=[(1,1,3,train-20),(1,2,4,train-10),(2,1,4,train-20),(2,3,2,train-10),(3,4,4,train-10)]
                rows += [(50,i,3,train-100-i) for i in range(1,13)]
                rows += [(1,3,4,train),(1,4,2,train+1),(1,13,5,train+2),
                         (2,2,5,train+3),(3,5,5,train+4),(9,1,5,train+5),(9,13,5,train+6)]
                rows += [(1,5,4,val),(2,13,5,val+1),(2,6,3,val+2),(3,6,4,val+3)]
                rows += [(1,6,5,test),(2,7,4,test+1),(3,7,2,test+2),(1,7,5,end)]
                with conn.cursor() as cur:
                    cur.executemany("INSERT INTO ratings VALUES (%s,%s,%s,%s)",rows)
                cfg=json.loads((features.ROOT / "configs/features.json").read_text())
                cfg["inspect_query_plans"]=False
                bindings={p["split"]:datasets.bind_or_build_features(conn,p,cfg) for p in partitions}
                yield conn,bindings
        finally:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def build(database,schema="datasets_test"):
    conn,bindings=database
    return datasets.build_dataset_schema(conn,schema,protocol(),bindings)


def test_calendar_windows_and_explicit_coverage_statuses(database):
    report=build(database)
    summary={p["split"]:p for p in report["summary"]["partitions"]}
    assert summary["train"]["window_ratings"]==7
    assert summary["validation"]["window_ratings"]==4
    assert summary["test"]["window_ratings"]==3
    assert summary["train"]["status_counts"]=={
        "eligible_positive":2,"below_positive_threshold":1,
        "sparse_user":1,"cold_user":2,"no_item_history":1}
    assert report["source_timeline"]==dict(total=32,before_training_labels=17,label_windows=14,at_or_after_test_end=1)
    assert report["summary"]["training"]["positive_rows"]==2
    assert report["summary"]["training"]["sampled_unobserved_rows"]==4
    conn,_=database
    with conn.transaction():
        datasets.set_dataset_path(conn,"datasets_test")
        assert conn.execute("SELECT split FROM label_events WHERE user_id=1 AND movie_id=5").fetchone()[0]=="validation"
        assert conn.execute("SELECT split FROM label_events WHERE user_id=1 AND movie_id=6").fetchone()[0]=="test"
        assert conn.execute("SELECT COUNT(*) FROM label_events WHERE user_id=1 AND movie_id=7").fetchone()[0]==0


def test_candidates_exclude_seen_but_not_future_observed_outcomes(database):
    build(database)
    conn,_=database
    candidates=datasets.evaluation_candidates(conn,"datasets_test","train",1)
    assert candidates==list(range(3,13))
    assert 3 in candidates and 4 in candidates  # Future train positive and observed lower rating both stay.
    assert 13 not in candidates
    later=datasets.evaluation_candidates(conn,"datasets_test","validation",2)
    assert 13 in later  # Observed by another user before the next cutoff.
    assert datasets.evaluation_candidates(conn,"datasets_test","train",3)==[]  # One prior rating, below minimum.


def test_training_sampling_ignores_validation_and_test_targets(database):
    build(database)
    conn,_=database
    before=conn.execute("SELECT * FROM datasets_test.training_examples ORDER BY user_id,movie_id").fetchall()
    candidates_before=datasets.evaluation_candidates(conn,"datasets_test","train",1)
    with conn.transaction():
        datasets.set_dataset_path(conn,"datasets_test")
        # Make a sampled unknown into a held-out positive. It must not disappear
        # from the initial training sampler based on that future knowledge.
        movie=conn.execute("SELECT movie_id FROM training_examples WHERE user_id=1 AND target_label=0 LIMIT 1").fetchone()[0]
        conn.execute("DELETE FROM positive_truth WHERE split IN ('validation','test')")
        conn.execute("DELETE FROM label_events WHERE split IN ('validation','test')")
        conn.execute("INSERT INTO positive_truth VALUES ('test',1,%s,5,1609459200,5)",(movie,))
        conn.execute("DELETE FROM training_examples WHERE target_label=0")
        conn.execute("DELETE FROM negative_sampling_audit")
        datasets.populate_training_negatives(conn,"datasets_test","features_training",2,42)
    after=conn.execute("SELECT * FROM datasets_test.training_examples ORDER BY user_id,movie_id").fetchall()
    assert after==before
    assert datasets.evaluation_candidates(conn,"datasets_test","train",1)==candidates_before


def test_train_batches_bind_older_features_and_never_return_genre_group(database):
    build(database)
    conn,_=database
    first=datasets.training_batch(conn,"datasets_test",limit=3)
    assert len(first)==3
    assert all(row["feature_schema"]=="features_training" for row in first)
    assert all("user_genre_affinity" not in row["features"] for row in first)
    assert {row["label_source"] for row in datasets.training_batch(conn,"datasets_test",limit=10)}=={
        "observed_positive","sampled_unobserved"}
    last=first[-1]
    second=datasets.training_batch(conn,"datasets_test",limit=3,after=(last["user_id"],last["movie_id"]))
    assert len(second)==3
    assert {(r["user_id"],r["movie_id"]) for r in first}.isdisjoint({(r["user_id"],r["movie_id"]) for r in second})
    assert conn.execute("SELECT MAX(rating_timestamp) FROM datasets_test.training_observations").fetchone()[0] < datasets.utc_epoch("2020-01-01T00:00:00+00:00")


def test_read_only_user_coverage_separates_population_and_ranking_cohort(database):
    build(database)
    conn,_=database
    report=datasets.audit_existing(conn,"datasets_test",protocol())
    assert report["read_only"]
    rows={row["split"]:row for row in report["user_coverage"]}
    assert rows["train"]["window_users"]==4
    assert rows["train"]["window_cold_users"]==1
    assert rows["train"]["window_sparse_users"]==1
    assert rows["train"]["ranking_users"]==2
    assert rows["test"]["window_warm_users_without_eligible_positive"]==1


def test_snapshot_binding_refuses_wrong_cutoff(database):
    conn,_=database
    p=datasets.validate_protocol(protocol())[0]
    p["cutoff"]+=1
    cfg=json.loads((features.ROOT / "configs/features.json").read_text())
    with pytest.raises(ValueError,match="different feature contract"):
        datasets.bind_or_build_features(conn,p,cfg)


def test_dataset_failure_rolls_back_but_preserves_feature_snapshots(database,monkeypatch):
    conn,_=database
    def fail(*args):
        raise ValueError("Intentional dataset failure")
    monkeypatch.setattr(datasets,"validate_datasets",fail)
    with pytest.raises(ValueError,match="Intentional"):
        build(database,"datasets_failed")
    assert conn.execute("SELECT 1 FROM pg_namespace WHERE nspname='datasets_failed'").fetchone() is None
    assert conn.execute("SELECT COUNT(*) FROM features_training.history_ratings").fetchone()[0]==17
    assert conn.execute("SELECT COUNT(*) FROM public.ratings").fetchone()[0]==32


def test_existing_dataset_is_not_replaced(database):
    build(database)
    with pytest.raises(ValueError,match="already exists"):
        build(database)


def test_dataset_cannot_bind_label_windows_to_a_different_feature_cutoff(database):
    from datetime import datetime,timedelta
    conn,bindings=database
    cfg=protocol()
    for partition in cfg["partitions"]:
        for field in ("cutoff_utc","label_end_utc"):
            partition[field]=(datetime.fromisoformat(partition[field])+timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError,match="cutoff differs"):
        datasets.build_dataset_schema(conn,"datasets_wrong_time",cfg,bindings)
    assert conn.execute("SELECT 1 FROM pg_namespace WHERE nspname='datasets_wrong_time'").fetchone() is None


def test_unobserved_sampling_is_reproducible_capped_and_without_replacement():
    catalog=list(range(1,21))
    first=datasets.sample_unobserved(catalog,set(catalog),{1,2,3,100},5,42,7)
    assert first==datasets.sample_unobserved(catalog,set(catalog),{1,2,3,100},5,42,7)
    assert len(first[0])==len(set(first[0]))==5
    assert set(first[0]).isdisjoint({1,2,3})
    capped=datasets.sample_unobserved(catalog,set(catalog),set(range(1,20)),4,42,7)
    assert capped[0]==[20] and capped[1]==1
    empty=datasets.sample_unobserved(catalog,set(catalog),set(catalog),4,42,7)
    assert empty[0]==[] and empty[1]==0


def test_dense_pool_fallback_terminates_and_preserves_valid_pool(monkeypatch):
    class RepeatedExcludedProposal:
        def randrange(self,size):
            return 0
        def sample(self,population,count):
            return population[:count]
    monkeypatch.setattr(datasets.random,"Random",lambda seed:RepeatedExcludedProposal())
    sampled,available,proposals,fallback=datasets.sample_unobserved([1,2,3],{1,2,3},{1},2,42,1)
    assert sampled==[2,3] and available==2 and proposals==64 and fallback


@pytest.mark.parametrize("change",[
    {"positive_rating_threshold":3.7},{"minimum_history_ratings":0},
    {"unobserved_per_positive":0},{"negative_seed":-1},
    {"default_feature_group":"optional_static_genre_features"},
    {"dataset_schema":"public"},
])
def test_invalid_protocol_configuration_is_rejected(change):
    cfg=protocol()
    cfg.update(change)
    with pytest.raises(ValueError):
        datasets.validate_protocol(cfg)


def test_overlapping_or_naive_boundaries_are_rejected():
    cfg=protocol()
    cfg["partitions"][1]["cutoff_utc"]="2019-12-31T00:00:00+00:00"
    with pytest.raises(ValueError,match="adjacent"):
        datasets.validate_protocol(cfg)
    with pytest.raises(ValueError,match="UTC"):
        datasets.utc_epoch("2020-01-01T00:00:00")
