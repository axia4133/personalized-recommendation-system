-- Freeze the exact behavioral input once. Events at the cutoff are excluded.
-- This is a history snapshot, not a training-label table.
CREATE TABLE history_ratings AS
SELECT user_id, movie_id, rating, rating_timestamp
FROM clean.ratings
WHERE rating_timestamp < %(cutoff)s;
