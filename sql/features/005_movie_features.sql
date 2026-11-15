CREATE TABLE movie_features AS
WITH activity AS (
    SELECT movie_id, COUNT(*) AS rating_count,
           AVG(rating)::double precision AS mean_rating,
           STDDEV_POP(rating)::double precision AS rating_stddev,
           VAR_POP(rating)::double precision AS rating_variance,
           MIN(rating_timestamp) AS first_rating_timestamp,
           MAX(rating_timestamp) AS last_rating_timestamp,
           COUNT(*) FILTER (WHERE rating_timestamp >= %(recent_start)s) AS recent_rating_count
    FROM history_ratings GROUP BY movie_id
), global_history AS (
    SELECT COUNT(*) AS ratings, AVG(rating)::double precision AS mean_rating FROM history_ratings
), genres AS (
    SELECT movie_id, MAX(genre_count) AS genre_count FROM movie_genres GROUP BY movie_id
)
SELECT a.*,
       (a.rating_count * a.mean_rating + %(movie_prior_count)s * g.mean_rating)
           / (a.rating_count + %(movie_prior_count)s) AS shrunk_mean_rating,
       a.rating_count::double precision / g.ratings AS popularity_share,
       LN(1.0 + a.rating_count)::double precision AS log_rating_count,
       RANK() OVER (ORDER BY a.rating_count DESC) AS popularity_rank,
       PERCENT_RANK() OVER (ORDER BY a.rating_count) AS popularity_percent_rank,
       (%(cutoff)s - a.first_rating_timestamp) / 86400.0::double precision AS days_since_first_observed_rating,
       (%(cutoff)s - a.last_rating_timestamp) / 86400.0::double precision AS days_since_last_rating,
       a.recent_rating_count::double precision / a.rating_count AS recent_rating_share,
       COALESCE(genres.genre_count, 0) AS genre_count,
       COALESCE(genres.genre_count, 0) > 0 AS has_known_genres
FROM activity a CROSS JOIN global_history g LEFT JOIN genres USING (movie_id);
