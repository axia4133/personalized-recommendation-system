-- Missingness, technical validity, metadata completeness, and rating scale.
-- FILTER is conditional aggregation: all counts share the same table scan.
SELECT jsonb_build_object(
    'movies', (SELECT jsonb_build_object(
        'rows', COUNT(*),
        'null_movie_ids', COUNT(*) FILTER (WHERE movie_id IS NULL),
        'nonpositive_movie_ids', COUNT(*) FILTER (WHERE movie_id <= 0),
        'null_titles', COUNT(*) FILTER (WHERE title IS NULL),
        'blank_titles', COUNT(*) FILTER (WHERE title IS NOT NULL AND btrim(title) = ''),
        'null_genres', COUNT(*) FILTER (WHERE genres_raw IS NULL),
        'blank_genres', COUNT(*) FILTER (WHERE genres_raw IS NOT NULL AND btrim(genres_raw) = ''),
        'no_genres_listed', COUNT(*) FILTER (WHERE genres_raw = '(no genres listed)')
    ) FROM public.movies),
    'ratings', (SELECT jsonb_build_object(
        'rows', COUNT(*),
        'null_user_ids', COUNT(*) FILTER (WHERE user_id IS NULL),
        'null_movie_ids', COUNT(*) FILTER (WHERE movie_id IS NULL),
        'nonpositive_user_ids', COUNT(*) FILTER (WHERE user_id <= 0),
        'nonpositive_movie_ids', COUNT(*) FILTER (WHERE movie_id <= 0),
        'null_ratings', COUNT(*) FILTER (WHERE rating IS NULL),
        'invalid_rating_values', COUNT(*) FILTER (
            WHERE rating IS NOT NULL AND (
                NOT (rating BETWEEN 0.5 AND 5.0) OR MOD(rating * 2, 1) <> 0)),
        'null_timestamps', COUNT(*) FILTER (WHERE rating_timestamp IS NULL),
        'negative_timestamps', COUNT(*) FILTER (WHERE rating_timestamp < 0)
    ) FROM public.ratings),
    'tags', (SELECT jsonb_build_object(
        'rows', COUNT(*),
        'null_user_ids', COUNT(*) FILTER (WHERE user_id IS NULL),
        'null_movie_ids', COUNT(*) FILTER (WHERE movie_id IS NULL),
        'nonpositive_user_ids', COUNT(*) FILTER (WHERE user_id <= 0),
        'nonpositive_movie_ids', COUNT(*) FILTER (WHERE movie_id <= 0),
        'null_tags', COUNT(*) FILTER (WHERE tag IS NULL),
        'blank_tags', COUNT(*) FILTER (WHERE tag IS NOT NULL AND btrim(tag) = ''),
        'null_timestamps', COUNT(*) FILTER (WHERE tag_timestamp IS NULL),
        'negative_timestamps', COUNT(*) FILTER (WHERE tag_timestamp < 0)
    ) FROM public.tags),
    'links', (SELECT jsonb_build_object(
        'rows', COUNT(*),
        'null_movie_ids', COUNT(*) FILTER (WHERE movie_id IS NULL),
        'nonpositive_movie_ids', COUNT(*) FILTER (WHERE movie_id <= 0),
        'null_imdb_ids', COUNT(*) FILTER (WHERE imdb_id IS NULL),
        'blank_imdb_ids', COUNT(*) FILTER (WHERE imdb_id IS NOT NULL AND btrim(imdb_id) = ''),
        'malformed_imdb_ids', COUNT(*) FILTER (WHERE imdb_id IS NOT NULL AND imdb_id !~ '^[0-9]+$'),
        'null_tmdb_ids', COUNT(*) FILTER (WHERE tmdb_id IS NULL),
        'nonpositive_tmdb_ids', COUNT(*) FILTER (WHERE tmdb_id <= 0)
    ) FROM public.links),
    'rating_distribution', (SELECT jsonb_agg(jsonb_build_object(
        'rating', rating::text, 'rows', rows) ORDER BY rating)
        FROM (SELECT rating, COUNT(*) AS rows FROM public.ratings GROUP BY rating) d)
) AS core_quality;
