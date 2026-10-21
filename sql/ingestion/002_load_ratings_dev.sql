-- Load the development ratings sample after movies have been loaded.
-- Run from the repository root with an empty ratings table:
-- docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 -U recsys -d movielens -c "$(cat sql/ingestion/002_load_ratings_dev.sql)" < data/processed/ratings_dev.csv
-- STDIN carries CSV data; pass this SQL with -c, not through the same stream.
-- Re-running after a successful load fails on existing primary keys.

COPY ratings (user_id, movie_id, rating, rating_timestamp)
FROM STDIN
WITH (FORMAT CSV, HEADER TRUE, ENCODING 'UTF8');
