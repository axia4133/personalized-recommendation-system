-- The ratings primary key already indexes (user_id, movie_id).
-- Separate movie access supports movie-based lookups and FK maintenance.
CREATE INDEX ratings_movie_id_idx ON ratings (movie_id);
CREATE INDEX tags_user_movie_idx ON tags (user_id, movie_id);
CREATE INDEX tags_movie_id_idx ON tags (movie_id);
