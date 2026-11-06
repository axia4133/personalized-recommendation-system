-- Non-destructive, version-controlled technical-validity layer.
-- No activity threshold, popularity, rating-positivity, or date-window filter.
-- Sparse histories and optional missing metadata remain in the population.
CREATE SCHEMA IF NOT EXISTS clean;

CREATE OR REPLACE VIEW clean.movies AS
SELECT movie_id, title, genres_raw FROM public.movies WHERE movie_id > 0;

CREATE OR REPLACE VIEW clean.ratings AS
SELECT r.user_id, r.movie_id, r.rating, r.rating_timestamp
FROM public.ratings r
JOIN clean.movies m ON m.movie_id = r.movie_id
WHERE r.user_id > 0 AND r.movie_id > 0
  AND r.rating BETWEEN 0.5 AND 5.0 AND MOD(r.rating * 2, 1) = 0
  AND r.rating_timestamp >= 0;

CREATE OR REPLACE VIEW clean.tags AS
SELECT t.tag_id, t.user_id, t.movie_id, t.tag, t.tag_timestamp
FROM public.tags t JOIN clean.movies m ON m.movie_id = t.movie_id
WHERE t.user_id > 0 AND t.movie_id > 0 AND t.tag_timestamp >= 0;

CREATE OR REPLACE VIEW clean.links AS
SELECT l.movie_id, l.imdb_id, l.tmdb_id
FROM public.links l JOIN clean.movies m ON m.movie_id = l.movie_id;

COMMENT ON SCHEMA clean IS 'Milestone 3 validated source views, not a model cohort or temporal split';
COMMENT ON VIEW clean.ratings IS 'Technical validity only; no sparsity filtering, deduplication, or target threshold';
COMMENT ON VIEW clean.tags IS 'Preserves repeated events and missing tag text; no silent text normalization';
