# Personalized Movie Recommendation System

Portfolio project: an end-to-end personalized movie recommendation and ranking pipeline using PostgreSQL, SQL, Python, and (later) PyTorch.

## Problem

With thousands of available movies, identifying relevant recommendations for individual users is challenging. This project explores how historical user ratings can be used to predict preferences and rank unseen movies.

## Objective

Build a personalized movie recommendation pipeline that emphasizes:

- SQL-based data processing and feature engineering
- Reproducible machine learning
- Systematic model evaluation with ranking metrics

The goal is a functioning, documented system—not an unreproduced notebook dump.

## Dataset

The project uses the GroupLens [MovieLens 32M](https://grouplens.org/datasets/movielens/32m/) dataset.

**Verified full ingestion:** `movielens_full` contains **32,000,204 ratings from 200,948 users**, **87,585 movies**, **2,000,072 tags**, and **87,585 links**. All four source checksums, complete streamed value comparisons, SQL summaries, and relational constraints passed. The separate `movielens` development database retains its 15,424-rating sample and also contains the full movies/tags/links metadata.

See `data/README.md` for download instructions and usage conditions. Raw data files are not committed to git.

## Planned tech stack

| Layer | Tools |
|---|---|
| Database | PostgreSQL (Docker) |
| Processing | SQL, Python, Pandas, NumPy |
| Machine learning | scikit-learn, PyTorch (later milestones) |
| Evaluation | Custom ranking metrics (Recall@K, NDCG@K, and related) |
| API | FastAPI (late milestone only) |
| Infrastructure | Docker, Git/GitHub |
| Testing | pytest and SQL/data validation |

## Planned approach

1. Design a relational schema for movies, ratings, and related metadata.
2. Ingest a development sample first, then the full dataset when the pipeline is validated.
3. Validate and prepare interaction data in SQL.
4. Engineer user and movie features in SQL without using future (held-out) interactions.
5. Define a ranking objective and chronological train/validation/test splits.
6. Compare recommendation algorithms against simple baselines using ranking metrics such as Recall@K and NDCG@K.
7. Only then train a neural two-tower model and a local prototype API.

MovieLens provides **explicit ratings**, not complete exposure or watch logs. Unrated movies are not treated as dislikes.

## Current status

**Milestone 2 complete — all 7 steps finished.** Relational schemas, constraints, development sampling, ingestion-method comparison, metadata, full ingestion, indexes, and reproducible verification are implemented. See the [ingestion runbook](docs/ingestion.md), [schema decisions](docs/schema.md), [current architecture](docs/architecture.md), and [actual full-load results](experiments/ingestion/full-load.md).

**Milestone 3 complete — all 6 steps finished.** Full-data SQL quality checks,
activity/sparsity distributions, timestamp investigation, and non-destructive
`clean` views are implemented. The reviewed audit preserves all 32,000,204
ratings and excludes zero rows. See the [quality findings and cleaning
decisions](docs/data_quality.md) and [executed reports](experiments/quality/README.md).

Findings include 7,080 movies with no genre labels, 124 missing TMDb mappings,
198 repeated-title groups, 36 reused TMDb-ID groups, and 108 ratings beyond a
UTC interpretation of the publisher's final calendar date. These are documented
and retained rather than silently removed or merged.

Next is Milestone 4: SQL feature engineering. Feature generation must establish
prediction-time boundaries before computing historical statistics. No models,
temporal splits, or ranking evaluation have been implemented. Whole-history
quality aggregates are diagnostics and must not be used as training features.

The ingestion-method benchmark is complete: on the 15,424-rating development
sample, median load times across three measured runs were 0.2052 seconds for
batched INSERT and 0.0671 seconds for COPY. These are local sample measurements,
not full-dataset throughput. See [configuration, actual results, tests, and
limitations](experiments/ingestion/README.md). This is an engineering benchmark;
model evaluation experiments have not started.

## Local setup

Requirements: Python 3.11+, Git, Docker Desktop (daemon running).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

For returning sessions, start Docker Desktop, then run from the repository root:

```bash
source .venv/bin/activate
docker compose up -d
docker compose exec -T postgres pg_isready -U recsys -d movielens
```

Existing tables and rows persist in the Docker volume. See [data/README.md](data/README.md) for download, verification, and first-time ingestion steps. Do not repeat ingestion on populated tables.

When finished, run `docker compose stop` and `deactivate`. Do not use `docker compose down -v` unless you intend to delete the database volume.

Run unit tests with `python -m pytest -q`. With Docker running and the development database available, run the opt-in integration suite with `RECSYS_TEST_DATABASE=1 python -m pytest -q`. The executed suite passed 36 tests.

## License and data usage

Code in this repository is for portfolio and learning use. MovieLens data remains subject to [GroupLens dataset terms](https://grouplens.org/datasets/movielens/).
