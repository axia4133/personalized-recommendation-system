"""Ingestion benchmark in progress: selectable INSERT and COPY loaders.

Run from the repository root:
    python src/data/benchmark_ingestion.py --method insert
    python src/data/benchmark_ingestion.py --method copy
Setup, loading, and cleanup use separate transactions. Timing is not implemented.
Requires public.ratings_ingestion_benchmark not to exist before execution.
"""

import argparse
import csv
import os

import psycopg


def load_with_copy(cur, rows):
    with cur.copy("""
        COPY public.ratings_ingestion_benchmark
            (user_id, movie_id, rating, rating_timestamp)
        FROM STDIN
    """) as copy:
        for row in rows:
            copy.write_row((
                row["userId"],
                row["movieId"],
                row["rating"],
                row["timestamp"],
            ))


def load_with_insert(cur, rows, batch_size):
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
            INSERT INTO public.ratings_ingestion_benchmark
                (user_id, movie_id, rating, rating_timestamp)
            VALUES
            """ + placeholders,
            parameters,
        )


parser = argparse.ArgumentParser(description="Load and validate a ratings sample.")
parser.add_argument("--method", choices=["insert", "copy"], required=True)
args = parser.parse_args()

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

        # Fail if this table already exists; never overwrite another run's table.
        # LIKE copies columns, checks, and indexes, but no rows or foreign keys.
        cur.execute("""
            CREATE TABLE public.ratings_ingestion_benchmark
            (LIKE public.ratings INCLUDING ALL)
        """)
        cur.execute("""
            ALTER TABLE public.ratings_ingestion_benchmark
            ADD FOREIGN KEY (movie_id) REFERENCES public.movies (movie_id)
        """)
        conn.commit()

        # Only clean up after this run has successfully created its own table.
        try:
            if args.method == "copy":
                load_with_copy(cur, rows)
            else:
                load_with_insert(cur, rows, batch_size)

            # Commit all batches together, before validation or cleanup.
            conn.commit()

            cur.execute("SELECT COUNT(*) FROM public.ratings_ingestion_benchmark")
            inserted_count = cur.fetchone()[0]
            assert inserted_count == len(rows), "Inserted row count differs from sample"
            print(f"Method: {args.method}; total rows inserted: {inserted_count}")
        finally:
            # Clear failed inserts (or the validation transaction) before cleanup.
            # This runs on success and on normal Python/database exceptions.
            conn.rollback()
            cur.execute("DROP TABLE public.ratings_ingestion_benchmark")
            conn.commit()
