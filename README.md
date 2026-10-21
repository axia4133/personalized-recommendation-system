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

The project will use the GroupLens [MovieLens 32M](https://grouplens.org/datasets/movielens/32m/) dataset, containing approximately 32 million movie ratings.

**Status:** the archive has been downloaded and all four CSV checksums verified. PostgreSQL contains all 87,585 movie rows and a development sample of 15,424 ratings from 100 users. The full ratings file has not been ingested.

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

**Milestone 2 — development sample ingested.** Movies and ratings tables, constraints, sample extraction, and bulk-loading SQL are implemented. Loaded movie and sample-rating values were compared against their source CSVs. Feature engineering, recommendation models, and evaluation experiments have not started.

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

## License and data usage

Code in this repository is for portfolio and learning use. MovieLens data remains subject to [GroupLens dataset terms](https://grouplens.org/datasets/movielens/).
