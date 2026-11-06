-- Whole-history diagnostics only. Never join these statistics into training
-- examples as features: they include future/held-out interactions.
WITH user_counts AS MATERIALIZED (
    SELECT user_id, COUNT(*) AS interactions,
           MIN(rating_timestamp) AS first_event, MAX(rating_timestamp) AS last_event
    FROM public.ratings GROUP BY user_id
), rated_movies AS MATERIALIZED (
    SELECT movie_id, COUNT(*) AS interactions FROM public.ratings GROUP BY movie_id
), movie_counts AS MATERIALIZED (
    -- LEFT JOIN includes catalog movies with zero ratings; zero is not a dislike.
    SELECT m.movie_id, COALESCE(r.interactions, 0) AS interactions
    FROM public.movies m LEFT JOIN rated_movies r ON r.movie_id = m.movie_id
), user_bins AS (
    SELECT CASE WHEN interactions < 5 THEN '01:1-4'
                WHEN interactions < 10 THEN '02:5-9'
                WHEN interactions < 20 THEN '03:10-19'
                WHEN interactions < 50 THEN '04:20-49'
                WHEN interactions < 100 THEN '05:50-99'
                WHEN interactions < 500 THEN '06:100-499'
                ELSE '07:500+' END AS bin,
           COUNT(*) AS users, SUM(interactions) AS ratings
    FROM user_counts GROUP BY 1
), movie_bins AS (
    SELECT CASE WHEN interactions = 0 THEN '01:0'
                WHEN interactions < 5 THEN '02:1-4'
                WHEN interactions < 10 THEN '03:5-9'
                WHEN interactions < 20 THEN '04:10-19'
                WHEN interactions < 100 THEN '05:20-99'
                WHEN interactions < 1000 THEN '06:100-999'
                ELSE '07:1000+' END AS bin,
           COUNT(*) AS movies, SUM(interactions) AS ratings
    FROM movie_counts GROUP BY 1
)
SELECT jsonb_build_object(
    'users', (SELECT jsonb_build_object(
        'count', COUNT(*), 'ratings', COALESCE(SUM(interactions), 0),
        'min', MIN(interactions), 'max', MAX(interactions), 'mean', AVG(interactions),
        'percentile_probabilities', ARRAY[0.25, 0.5, 0.75, 0.9, 0.95, 0.99],
        'percentiles', percentile_disc(ARRAY[0.25, 0.5, 0.75, 0.9, 0.95, 0.99])
            WITHIN GROUP (ORDER BY interactions),
        'below_history_threshold', COUNT(*) FILTER (WHERE interactions < %(minimum_user_history)s),
        'ratings_from_users_below_threshold', COALESCE(SUM(interactions)
            FILTER (WHERE interactions < %(minimum_user_history)s), 0),
        'single_timestamp_users', COUNT(*) FILTER (WHERE first_event = last_event)
    ) FROM user_counts),
    'movies', (SELECT jsonb_build_object(
        'catalog_count', COUNT(*), 'rated_count', COUNT(*) FILTER (WHERE interactions > 0),
        'zero_ratings', COUNT(*) FILTER (WHERE interactions = 0),
        'min', MIN(interactions), 'max', MAX(interactions), 'mean', AVG(interactions),
        'percentile_probabilities', ARRAY[0.25, 0.5, 0.75, 0.9, 0.95, 0.99],
        'percentiles', percentile_disc(ARRAY[0.25, 0.5, 0.75, 0.9, 0.95, 0.99])
            WITHIN GROUP (ORDER BY interactions),
        'below_rating_threshold', COUNT(*) FILTER (WHERE interactions < %(sparse_movie_threshold)s),
        'ratings_on_movies_below_threshold', COALESCE(SUM(interactions)
            FILTER (WHERE interactions < %(sparse_movie_threshold)s), 0)
    ) FROM movie_counts),
    'observed_rating_density', (SELECT SUM(interactions)::numeric
        / NULLIF(COUNT(*)::numeric * (SELECT COUNT(*) FROM movie_counts), 0) FROM user_counts),
    'user_bins', (SELECT jsonb_agg(to_jsonb(u) ORDER BY bin) FROM user_bins u),
    'movie_bins', (SELECT jsonb_agg(to_jsonb(m) ORDER BY bin) FROM movie_bins m)
) AS activity_and_sparsity;
