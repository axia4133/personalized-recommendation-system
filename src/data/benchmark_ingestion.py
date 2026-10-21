"""Ingestion benchmark in progress: batching and a read-only connection check.

Run from the repository root: python src/data/benchmark_ingestion.py
No loading or timing has been implemented yet.
"""

import csv
import os

import psycopg

input_file_path = "data/processed/ratings_dev.csv"
batch_size = 1000

with open(input_file_path, mode="r", encoding="utf-8", newline="") as infile:
    reader = csv.DictReader(infile)
    rows = list(reader)

for start in range(0, len(rows), batch_size):
    batch = rows[start : start + batch_size]
    print(len(batch))
# Defaults match docker-compose.yml for local development.
# Standard PostgreSQL environment variables allow connection overrides.
with psycopg.connect(
    host=os.getenv("PGHOST", "127.0.0.1"),
    port=int(os.getenv("PGPORT", "5432")),
    dbname=os.getenv("PGDATABASE", "movielens"),
    user=os.getenv("PGUSER", "recsys"),
    password=os.getenv("PGPASSWORD", "recsys"),
    connect_timeout=5,
) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT current_database(), current_user")
        database_name, user_name = cur.fetchone()
        print(f"Connected to database {database_name} as {user_name}")
