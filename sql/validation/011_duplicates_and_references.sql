-- GROUP BY defines observation identity; HAVING identifies repeated groups.
-- Same titles/external IDs and repeated tags are findings, not deletion rules.
WITH rating_pairs AS (
    SELECT COUNT(*) AS occurrences FROM public.ratings
    GROUP BY user_id, movie_id HAVING COUNT(*) > 1
), tag_events AS (
    SELECT COUNT(*) AS occurrences FROM public.tags
    GROUP BY user_id, movie_id, tag, tag_timestamp HAVING COUNT(*) > 1
), movie_ids AS (
    SELECT COUNT(*) AS occurrences FROM public.movies
    GROUP BY movie_id HAVING COUNT(*) > 1
), link_movies AS (
    SELECT COUNT(*) AS occurrences FROM public.links
    GROUP BY movie_id HAVING COUNT(*) > 1
), title_groups AS (
    SELECT COUNT(*) AS occurrences FROM public.movies
    WHERE title IS NOT NULL GROUP BY title HAVING COUNT(*) > 1
), imdb_groups AS (
    SELECT COUNT(*) AS occurrences FROM public.links
    WHERE imdb_id IS NOT NULL GROUP BY imdb_id HAVING COUNT(*) > 1
), tmdb_groups AS (
    SELECT COUNT(*) AS occurrences FROM public.links
    WHERE tmdb_id IS NOT NULL GROUP BY tmdb_id HAVING COUNT(*) > 1
), tag_users AS MATERIALIZED (
    SELECT DISTINCT user_id FROM public.tags WHERE user_id IS NOT NULL
)
SELECT jsonb_build_object(
    'ratings', (SELECT jsonb_build_object('duplicate_pair_groups', COUNT(*),
        'extra_rows', COALESCE(SUM(occurrences - 1), 0)) FROM rating_pairs),
    'tags', (SELECT jsonb_build_object('exact_repeated_event_groups', COUNT(*),
        'extra_rows', COALESCE(SUM(occurrences - 1), 0)) FROM tag_events),
    'movies', (SELECT jsonb_build_object('duplicate_id_groups', COUNT(*),
        'extra_rows', COALESCE(SUM(occurrences - 1), 0)) FROM movie_ids),
    'links', (SELECT jsonb_build_object('duplicate_movie_groups', COUNT(*),
        'extra_rows', COALESCE(SUM(occurrences - 1), 0)) FROM link_movies),
    'repeated_titles', (SELECT jsonb_build_object('groups', COUNT(*),
        'extra_rows', COALESCE(SUM(occurrences - 1), 0)) FROM title_groups),
    'reused_imdb_ids', (SELECT jsonb_build_object('groups', COUNT(*),
        'extra_rows', COALESCE(SUM(occurrences - 1), 0)) FROM imdb_groups),
    'reused_tmdb_ids', (SELECT jsonb_build_object('groups', COUNT(*),
        'extra_rows', COALESCE(SUM(occurrences - 1), 0)) FROM tmdb_groups),
    'references', jsonb_build_object(
        'ratings_without_movie', (SELECT COUNT(*) FROM public.ratings r
            WHERE NOT EXISTS (SELECT 1 FROM public.movies m WHERE m.movie_id = r.movie_id)),
        'tags_without_movie', (SELECT COUNT(*) FROM public.tags t
            WHERE NOT EXISTS (SELECT 1 FROM public.movies m WHERE m.movie_id = t.movie_id)),
        'links_without_movie', (SELECT COUNT(*) FROM public.links l
            WHERE NOT EXISTS (SELECT 1 FROM public.movies m WHERE m.movie_id = l.movie_id)),
        'movies_without_link', (SELECT COUNT(*) FROM public.movies m
            WHERE NOT EXISTS (SELECT 1 FROM public.links l WHERE l.movie_id = m.movie_id)),
        'tag_users_without_rating_history', (SELECT COUNT(*) FROM tag_users t
            WHERE NOT EXISTS (SELECT 1 FROM public.ratings r WHERE r.user_id = t.user_id))
    )
) AS duplicates_and_references;
