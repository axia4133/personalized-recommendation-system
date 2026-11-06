-- This summary complements full source-to-database value digests.
-- Primary keys and validated foreign keys enforce uniqueness and references.
SELECT jsonb_build_object(
    'movies', (SELECT jsonb_build_object('rows', COUNT(*)) FROM movies),
    'ratings', (SELECT jsonb_build_object(
        'rows', COUNT(*), 'users', COUNT(DISTINCT user_id)
    ) FROM ratings),
    'tags', (SELECT jsonb_build_object(
        'rows', COUNT(*), 'users', COUNT(DISTINCT user_id),
        'null_tags', COUNT(*) FILTER (WHERE tag IS NULL)
    ) FROM tags),
    'links', (SELECT jsonb_build_object(
        'rows', COUNT(*),
        'null_imdb_ids', COUNT(*) FILTER (WHERE imdb_id IS NULL),
        'null_tmdb_ids', COUNT(*) FILTER (WHERE tmdb_id IS NULL),
        'imdb_ids_with_leading_zero', COUNT(*) FILTER (WHERE imdb_id LIKE '0%')
    ) FROM links)
) AS ingestion_summary;
