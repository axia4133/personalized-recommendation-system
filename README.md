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

**Status:** the dataset has not been downloaded, ingested, or processed. Record counts will be reported only after they are measured.

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

**Setup only.** The project is in its initial development phase. No large-scale data processing, feature engineering pipelines, recommendation models, or evaluation experiments have been completed.

## Local setup (Milestone 1)

Requirements: Python 3.11+, Git, Docker Desktop (daemon running).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

PostgreSQL is defined in `docker-compose.yml`. Start Docker Desktop first, then we will bring the database up in the next setup task—do not run `docker compose up` until we walk through it.

## License and data usage

Code in this repository is for portfolio and learning use. MovieLens data remains subject to [GroupLens dataset terms](https://grouplens.org/datasets/movielens/).
