# Data

This directory is the landing place for MovieLens files. **Do not commit raw or processed datasets.**

## Authoritative source

- Dataset: [MovieLens 32M](https://grouplens.org/datasets/movielens/32m/)
- Publisher: GroupLens (University of Minnesota)
- Typical archive name: `ml-32m.zip`

Download only from the official GroupLens page. Review their license and citation requirements before use.

## Local layout

```text
data/
  README.md          # this file
  raw/               # ml-32m.zip and extracted ml-32m/ (gitignored)
  processed/         # ratings_dev.csv (gitignored)
```

## Status

Verified locally on November 5, 2026:

- All four extracted CSV checksums match the published MovieLens 32M values.
- All 87,585 movie rows are loaded in PostgreSQL and match the source CSV.
- The development sample contains 15,424 ratings from the first 100 distinct users, retaining their complete histories. Repeated extraction produced identical output.
- All sample ratings are loaded and match the sample CSV. There are no missing movie references.
- Development database `movielens` also contains all 2,000,072 tags and 87,585 links, without filtering global metadata to the sample users.
- Separate database `movielens_full` contains all 32,000,204 ratings from 200,948 users, 87,585 movies, 2,000,072 tags, and 87,585 links.
- Full-source and database canonical-value digests match for every table. All constraints are validated, and SQL source/database summaries agree.
- Links preserve 124 missing TMDb IDs as NULL and 46,596 IMDb IDs with leading zeros as text.

The sample is deterministic and selected by source user order, not randomly. It is for pipeline development and is not a representative evaluation sample. No records have been cleaned or excluded based on modeling criteria.

## Download and verify

Run from the repository root:

```bash
mkdir -p data/raw
curl --fail --location --connect-timeout 20 --max-time 600 \
  https://files.grouplens.org/datasets/movielens/ml-32m.zip \
  -o data/raw/ml-32m.zip
unzip -n data/raw/ml-32m.zip -d data/raw

# macOS: compare each CSV's hash with the corresponding checksums.txt entry.
cat data/raw/ml-32m/checksums.txt
md5 data/raw/ml-32m/links.csv data/raw/ml-32m/movies.csv \
  data/raw/ml-32m/ratings.csv data/raw/ml-32m/tags.csv
```

Usage conditions and the requested citation are in the [official dataset README](https://files.grouplens.org/datasets/movielens/ml-32m-README.html). Research use requires acknowledgment; commercial or revenue-bearing use requires permission. Redistribution must preserve the dataset terms, and use must not imply GroupLens endorsement.

Dataset citation: F. Maxwell Harper and Joseph A. Konstan (2015),
*The MovieLens Datasets: History and Context*, ACM Transactions on Interactive
Intelligent Systems, 5(4). [DOI: 10.1145/2827872](https://doi.org/10.1145/2827872).

## Reproduce the development load

These steps require the project virtual environment and a running PostgreSQL container; see the root README. Sample extraction uses only the standard library. The ingestion benchmark additionally uses the pinned Psycopg dependency, and its tests use pytest.

Run the following only on a fresh project database where `movies` and `ratings` do not yet exist. If the tables are already populated, skip these steps and use the count query below. Schema scripts fail on existing tables; successful ingestion must not be repeated because primary keys reject duplicate rows.

```bash
# Create both empty tables, movies first because ratings references it.
docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 -U recsys -d movielens < sql/schema/001_movies.sql
docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 -U recsys -d movielens < sql/schema/002_ratings.sql

# Create the sample and load movies before ratings.
python src/data/create_dev_sample.py
docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 -U recsys -d movielens -c "$(cat sql/ingestion/001_load_movies.sql)" < data/raw/ml-32m/movies.csv
docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 -U recsys -d movielens -c "$(cat sql/ingestion/002_load_ratings_dev.sql)" < data/processed/ratings_dev.csv
```

`-T` disables Docker's terminal allocation for streamed input. `-X` ignores personal psql startup configuration, and `ON_ERROR_STOP=1` makes SQL failures stop execution. `-c` supplies the SQL command while standard input carries the CSV; the two must use separate input channels.

Check the database counts:

```bash
docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 -U recsys -d movielens -c 'SELECT (SELECT COUNT(*) FROM movies) AS movie_rows, COUNT(*) AS rating_rows, COUNT(DISTINCT user_id) AS users FROM ratings;'
```

Expected for this development load: 87,585 movies, 15,424 ratings, and 100 users. Counts alone do not prove source equality; row-level comparisons were also performed during the original load validation.

## Ingestion benchmark

Milestone 2, step 5 of 7 is complete. COPY and batched INSERT were compared on
the development sample using fresh ordinary tables and one committed load
transaction per trial. Both methods passed full-value comparisons on every run.
See [the executed experiment](../experiments/ingestion/README.md) for results,
reproduction commands, tests, and limitations. The original tables are unchanged.
Tags/links ingestion and full ratings ingestion are now complete. See the
[full-load results](../experiments/ingestion/full-load.md) and
[runbook](../docs/ingestion.md) for the separate database scopes and reproduction.
