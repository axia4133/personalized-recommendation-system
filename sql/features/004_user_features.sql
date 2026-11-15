CREATE TABLE user_features AS
WITH activity AS (
    SELECT user_id, COUNT(*) AS rating_count,
           AVG(rating)::double precision AS mean_rating,
           STDDEV_POP(rating)::double precision AS rating_stddev,
           VAR_POP(rating)::double precision AS rating_variance,
           MIN(rating_timestamp) AS first_rating_timestamp,
           MAX(rating_timestamp) AS last_rating_timestamp,
           COUNT(DISTINCT rating_timestamp / 86400) AS active_utc_days,
           COUNT(*) FILTER (WHERE rating_timestamp >= %(recent_start)s) AS recent_rating_count
    FROM history_ratings GROUP BY user_id
), ordered_events AS (
    SELECT user_id, rating_timestamp,
           LAG(rating_timestamp) OVER (
               PARTITION BY user_id ORDER BY rating_timestamp, movie_id
           ) AS previous_timestamp
    FROM history_ratings
), gaps AS (
    SELECT user_id, AVG((rating_timestamp - previous_timestamp) / 86400.0)::double precision AS mean_gap_days
    FROM ordered_events WHERE previous_timestamp IS NOT NULL GROUP BY user_id
)
SELECT a.*,
       (%(cutoff)s - first_rating_timestamp) / 86400.0::double precision AS history_age_days,
       (%(cutoff)s - last_rating_timestamp) / 86400.0::double precision AS days_since_last_rating,
       (last_rating_timestamp - first_rating_timestamp) / 86400.0::double precision AS activity_span_days,
       rating_count::double precision / active_utc_days AS ratings_per_active_day,
       recent_rating_count::double precision / %(recent_window_days)s AS recent_ratings_per_day,
       g.mean_gap_days
FROM activity a LEFT JOIN gaps g USING (user_id);
