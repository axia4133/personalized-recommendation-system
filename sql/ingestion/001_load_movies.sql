-- Load MovieLens movies.csv into an empty movies table.
-- Run from the repository root (Docker Desktop and PostgreSQL must be running):
-- docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 -U recsys -d movielens -c "$(cat sql/ingestion/001_load_movies.sql)" < data/raw/ml-32m/movies.csv
-- STDIN carries CSV data; pass this SQL with -c, not through the same stream.
-- Re-running after a successful load fails on existing primary keys.

COPY movies (movie_id, title, genres_raw)
FROM STDIN
WITH (FORMAT CSV, HEADER TRUE, ENCODING 'UTF8');
