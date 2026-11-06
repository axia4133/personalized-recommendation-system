"""Ingestion benchmark in progress: batching, connection, and temporary table.

Run from the repository root: python src/data/benchmark_ingestion.py
Batched insertion into temporary tables is implemented; timing is not yet implemented.
"""

import csv
import os

import psycopg

input_file_path = "data/processed/ratings_dev.csv"
batch_size = 1000

with open(input_file_path, mode="r", encoding="utf-8", newline="") as infile:
    reader = csv.DictReader(infile)
    rows = list(reader)


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

        # A temporary table's foreign keys must reference temporary tables.
        cur.execute("""
            CREATE TEMP TABLE movies_benchmark
            (LIKE public.movies INCLUDING ALL)
        """)
        cur.execute("""
            INSERT INTO movies_benchmark (movie_id, title, genres_raw)
            SELECT movie_id, title, genres_raw FROM public.movies
        """)

        # Copy columns, checks, and indexes, but no existing rating rows.
        cur.execute("""
            CREATE TEMP TABLE ratings_benchmark
            (LIKE public.ratings INCLUDING ALL)
        """)

        # LIKE does not copy foreign keys, so add the movie reference explicitly.
        cur.execute("""
            ALTER TABLE ratings_benchmark
            ADD FOREIGN KEY (movie_id) REFERENCES movies_benchmark (movie_id)
        """)

        cur.execute("SELECT COUNT(*) FROM ratings_benchmark")
        print("Benchmark rows:", cur.fetchone()[0])

        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]

            # One group of four placeholders for each rating.
            placeholders = ", ".join(
                ["(%s, %s, %s, %s)"] * len(batch)
            )

            parameters = []
            for row in batch:
                parameters.extend([
                    row["userId"],
                    row["movieId"],
                    row["rating"],
                    row["timestamp"],
                ])

            cur.execute(
                """
                INSERT INTO ratings_benchmark
                    (user_id, movie_id, rating, rating_timestamp)
                VALUES
                """ + placeholders,
                parameters,
            )

        cur.execute("SELECT COUNT(*) FROM ratings_benchmark")
        inserted_count = cur.fetchone()[0]
        assert inserted_count == len(rows), "Inserted row count differs from sample"
        print("Total rows inserted:", inserted_count)