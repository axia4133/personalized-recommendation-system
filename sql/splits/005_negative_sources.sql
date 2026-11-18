-- Only training outcomes enter training exclusions. Never inspect validation
-- or test targets to avoid future false negatives: that would leak information.
WITH targets AS MATERIALIZED (
    SELECT user_id, positive_count FROM ranking_users WHERE split='train'
), exclusions AS (
    SELECT h.user_id, h.movie_id FROM {train_schema}.history_ratings h
    JOIN targets t USING (user_id)
    UNION ALL
    SELECT l.user_id, l.movie_id FROM label_events l JOIN targets t USING (user_id)
    WHERE l.split='train'
), grouped AS (
    SELECT user_id, array_agg(DISTINCT movie_id ORDER BY movie_id) AS excluded_movies
    FROM exclusions GROUP BY user_id
)
SELECT t.user_id, t.positive_count, COALESCE(g.excluded_movies, ARRAY[]::integer[]) AS excluded_movies
FROM targets t LEFT JOIN grouped g USING (user_id) ORDER BY t.user_id;
