-- Bounded requested pairs, not a full user/catalog cross product or labels.
WITH pairs AS MATERIALIZED (
    SELECT DISTINCT user_id, movie_id
    FROM jsonb_to_recordset(%(pairs)s::jsonb) AS p(user_id integer, movie_id integer)
), affinity AS (
    SELECT p.user_id, p.movie_id, COUNT(mg.genre) AS known_item_genres,
           COUNT(ug.genre) AS genres_with_user_history,
           AVG(COALESCE(ug.centered_affinity, 0)) AS genre_affinity
    FROM pairs p LEFT JOIN movie_genres mg USING (movie_id)
    LEFT JOIN user_genre_features ug ON ug.user_id = p.user_id AND ug.genre = mg.genre
    GROUP BY p.user_id, p.movie_id
)
SELECT p.user_id, p.movie_id,
       u.user_id IS NOT NULL AS has_user_history,
       m.movie_id IS NOT NULL AS has_movie_history,
       EXISTS (SELECT 1 FROM history_ratings r
               WHERE r.user_id = p.user_id AND r.movie_id = p.movie_id) AS has_prior_rating,
       m.movie_id IS NOT NULL AND NOT EXISTS (
           SELECT 1 FROM history_ratings r WHERE r.user_id = p.user_id AND r.movie_id = p.movie_id
       ) AS eligible_under_observed_catalog_policy,
       COALESCE(u.rating_count, 0) AS user_rating_count,
       COALESCE(u.mean_rating, c.global_mean_rating) AS user_mean_rating,
       COALESCE(u.rating_stddev, 0) AS user_rating_stddev,
       COALESCE(u.recent_rating_count, 0) AS user_recent_rating_count,
       u.days_since_last_rating AS user_days_since_last_rating,
       COALESCE(m.rating_count, 0) AS movie_rating_count,
       COALESCE(m.mean_rating, c.global_mean_rating) AS movie_mean_rating,
       COALESCE(m.shrunk_mean_rating, c.global_mean_rating) AS movie_shrunk_mean_rating,
       COALESCE(m.recent_rating_count, 0) AS movie_recent_rating_count,
       COALESCE(m.popularity_share, 0) AS movie_popularity_share,
       COALESCE(a.genre_affinity, 0) AS user_genre_affinity,
       a.known_item_genres, a.genres_with_user_history,
       COALESCE(a.genres_with_user_history::double precision / NULLIF(a.known_item_genres, 0), 0) AS genre_preference_coverage,
       COALESCE(h.known_genre_history_fraction, 0) AS user_known_genre_history_fraction,
       m.rating_count::double precision / NULLIF(h.mean_rated_movie_popularity, 0) AS popularity_relative_to_user_history,
       COALESCE(m.shrunk_mean_rating, c.global_mean_rating)
           - COALESCE(u.mean_rating, c.global_mean_rating) AS movie_user_rating_bias_gap
FROM pairs p CROSS JOIN snapshot_context c
LEFT JOIN user_features u USING (user_id)
LEFT JOIN movie_features m USING (movie_id)
LEFT JOIN user_history_features h USING (user_id)
JOIN affinity a USING (user_id, movie_id)
ORDER BY p.user_id, p.movie_id;
