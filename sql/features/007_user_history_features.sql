CREATE TABLE user_history_features AS
WITH item_history AS (
    SELECT r.user_id,
           AVG(m.rating_count)::double precision AS mean_rated_movie_popularity,
           AVG(m.shrunk_mean_rating)::double precision AS mean_rated_movie_shrunk_rating
    FROM history_ratings r JOIN movie_features m USING (movie_id)
    GROUP BY r.user_id
), genre_coverage AS (
    SELECT user_id, SUM(support_weight) AS known_genre_rating_weight
    FROM user_genre_features GROUP BY user_id
)
SELECT i.*, COALESCE(g.known_genre_rating_weight, 0) AS known_genre_rating_weight,
       COALESCE(g.known_genre_rating_weight, 0) / u.rating_count AS known_genre_history_fraction
FROM item_history i JOIN user_features u USING (user_id)
LEFT JOIN genre_coverage g USING (user_id);
