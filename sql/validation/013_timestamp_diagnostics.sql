-- These documented bounds are data-audit references, not train/test cutoffs.
-- Calendar display is guarded to 1970..9999 to avoid converting extreme BIGINT
-- sentinels. The year histogram does not discard valid calendar dates merely
-- because they fall outside the interpreted source window.
WITH rating_years AS (
    SELECT CASE WHEN rating_timestamp BETWEEN 0 AND 253402300799
                THEN EXTRACT(YEAR FROM to_timestamp(rating_timestamp))::text
                ELSE 'outside_display_range_or_missing' END AS year,
           COUNT(*) AS rows
    FROM public.ratings GROUP BY 1
), tag_years AS (
    SELECT CASE WHEN tag_timestamp BETWEEN 0 AND 253402300799
                THEN EXTRACT(YEAR FROM to_timestamp(tag_timestamp))::text
                ELSE 'outside_display_range_or_missing' END AS year,
           COUNT(*) AS rows
    FROM public.tags GROUP BY 1
), selected_users AS MATERIALIZED (
    SELECT DISTINCT user_id FROM public.ratings ORDER BY user_id
    LIMIT %(order_diagnostic_users)s
), ordered_sample AS (
    SELECT r.user_id, r.rating_timestamp,
           LAG(r.rating_timestamp) OVER (
               PARTITION BY r.user_id ORDER BY r.movie_id, r.rating_timestamp
           ) AS previous_timestamp
    FROM public.ratings r JOIN selected_users u ON u.user_id = r.user_id
)
SELECT jsonb_build_object(
    'ratings', (SELECT jsonb_build_object(
        'rows', COUNT(*), 'min_epoch', MIN(rating_timestamp), 'max_epoch', MAX(rating_timestamp),
        'null_timestamps', COUNT(*) FILTER (WHERE rating_timestamp IS NULL),
        'negative_timestamps', COUNT(*) FILTER (WHERE rating_timestamp < 0),
        'before_documented_start', COUNT(*) FILTER (WHERE rating_timestamp < %(window_start)s),
        'at_or_after_documented_end', COUNT(*) FILTER (WHERE rating_timestamp >= %(window_end)s)
    ) FROM public.ratings),
    'tags', (SELECT jsonb_build_object(
        'rows', COUNT(*), 'min_epoch', MIN(tag_timestamp), 'max_epoch', MAX(tag_timestamp),
        'null_timestamps', COUNT(*) FILTER (WHERE tag_timestamp IS NULL),
        'negative_timestamps', COUNT(*) FILTER (WHERE tag_timestamp < 0),
        'before_documented_start', COUNT(*) FILTER (WHERE tag_timestamp < %(window_start)s),
        'at_or_after_documented_end', COUNT(*) FILTER (WHERE tag_timestamp >= %(window_end)s)
    ) FROM public.tags),
    'rating_years', (SELECT jsonb_agg(to_jsonb(r) ORDER BY year) FROM rating_years r),
    'tag_years', (SELECT jsonb_agg(to_jsonb(t) ORDER BY year) FROM tag_years t),
    'movie_id_order_diagnostic', (SELECT jsonb_build_object(
        'scope', 'first distinct user IDs, not a random sample',
        'users', COUNT(DISTINCT user_id), 'ratings', COUNT(*),
        'adjacent_pairs', COUNT(previous_timestamp),
        'timestamp_decreases', COUNT(*) FILTER (WHERE rating_timestamp < previous_timestamp)
    ) FROM ordered_sample)
) AS timestamp_diagnostics;
