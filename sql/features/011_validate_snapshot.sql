WITH expected_genre_weight AS (
    SELECT r.user_id, COUNT(*) AS expected_weight
    FROM history_ratings r JOIN (SELECT DISTINCT movie_id FROM movie_genres) m USING (movie_id)
    GROUP BY r.user_id
), weight_mismatches AS (
    SELECT u.user_id FROM user_features u
    LEFT JOIN expected_genre_weight e USING (user_id)
    LEFT JOIN user_history_features h USING (user_id)
    WHERE ABS(COALESCE(h.known_genre_rating_weight, 0) - COALESCE(e.expected_weight, 0))
        > 1e-9 * GREATEST(1, COALESCE(e.expected_weight, 0))
)
SELECT jsonb_build_object(
    'history_rows', (SELECT COUNT(*) FROM history_ratings),
    'source_rows_before_cutoff', (SELECT COUNT(*) FROM clean.ratings WHERE rating_timestamp < %(cutoff)s),
    'users', (SELECT COUNT(*) FROM user_features),
    'movies', (SELECT COUNT(*) FROM movie_features),
    'movie_genre_rows', (SELECT COUNT(*) FROM movie_genres),
    'user_genre_rows', (SELECT COUNT(*) FROM user_genre_features),
    'user_history_rows', (SELECT COUNT(*) FROM user_history_features),
    'ratings_summed_over_users', (SELECT SUM(rating_count) FROM user_features),
    'ratings_summed_over_movies', (SELECT SUM(rating_count) FROM movie_features),
    'max_history_timestamp', (SELECT MAX(rating_timestamp) FROM history_ratings),
    'future_history_rows', (SELECT COUNT(*) FROM history_ratings WHERE rating_timestamp >= %(cutoff)s),
    'invalid_user_rows', (SELECT COUNT(*) FROM user_features WHERE rating_count < 1
        OR recent_rating_count > rating_count OR recent_rating_count < 0
        OR mean_rating NOT BETWEEN 0.5 AND 5.0 OR rating_stddev < 0
        OR days_since_last_rating <= 0 OR mean_gap_days < 0
        OR last_rating_timestamp >= %(cutoff)s),
    'invalid_movie_rows', (SELECT COUNT(*) FROM movie_features WHERE rating_count < 1
        OR recent_rating_count > rating_count OR recent_rating_count < 0
        OR shrunk_mean_rating NOT BETWEEN 0.5 AND 5.0
        OR popularity_share <= 0 OR popularity_share > 1 OR popularity_rank < 1
        OR last_rating_timestamp >= %(cutoff)s),
    'invalid_genre_rows', (SELECT COUNT(*) FROM movie_genres WHERE genre_count < 1
        OR genre = '' OR genre = '(no genres listed)'),
    'invalid_affinity_rows', (SELECT COUNT(*) FROM user_genre_features WHERE support_weight <= 0
        OR ABS(centered_affinity) > 4.500000001 OR weighted_history_share < 0
        OR weighted_history_share > 1.000000001 OR last_rating_timestamp >= %(cutoff)s),
    'genre_weight_mismatch_users', (SELECT COUNT(*) FROM weight_mismatches),
    'users_without_known_genres', (SELECT COUNT(*) FROM user_history_features WHERE known_genre_rating_weight = 0),
    'movies_without_known_genres', (SELECT COUNT(*) FROM movie_features WHERE NOT has_known_genres),
    'single_rating_users', (SELECT COUNT(*) FROM user_features WHERE rating_count = 1),
    'popularity_share_sum', (SELECT SUM(popularity_share) FROM movie_features)
) AS validation;
