-- Fractional membership prevents multi-genre movies from multiplying activity.
-- Center ratings by the user's own prior-history mean, then shrink toward zero.
CREATE TABLE user_genre_features AS
WITH contributions AS (
    SELECT r.user_id, mg.genre, COUNT(*) AS genre_rating_count,
           SUM(1.0::double precision / mg.genre_count) AS support_weight,
           SUM(r.rating::double precision / mg.genre_count) AS weighted_rating_sum,
           SUM((r.rating::double precision - u.mean_rating) / mg.genre_count) AS centered_rating_sum,
           MAX(r.rating_timestamp) AS last_rating_timestamp
    FROM history_ratings r
    JOIN movie_genres mg USING (movie_id)
    JOIN user_features u USING (user_id)
    GROUP BY r.user_id, mg.genre
)
SELECT c.user_id, c.genre, c.genre_rating_count, c.support_weight,
       c.weighted_rating_sum / c.support_weight AS weighted_mean_rating,
       c.support_weight / u.rating_count AS weighted_history_share,
       c.centered_rating_sum / (c.support_weight + %(genre_prior_weight)s) AS centered_affinity,
       c.last_rating_timestamp,
       ROW_NUMBER() OVER (
           PARTITION BY c.user_id ORDER BY c.support_weight DESC, c.genre
       ) AS genre_history_rank
FROM contributions c JOIN user_features u USING (user_id);
