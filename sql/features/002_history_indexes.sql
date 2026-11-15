ALTER TABLE history_ratings ADD PRIMARY KEY (user_id, movie_id);
-- Supports chronological per-user scans and bounded history retrieval.
CREATE INDEX history_user_time_idx ON history_ratings (user_id, rating_timestamp, movie_id);
