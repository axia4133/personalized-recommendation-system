-- Review a diagnostic boundary, not evidence that these source events are bad.
-- America/Chicago is an illustrative calendar-date interpretation, not a claim
-- about the publisher's timezone. Epoch timestamps themselves remain UTC.
WITH flagged AS MATERIALIZED (
    SELECT user_id, rating_timestamp FROM public.ratings
    WHERE rating_timestamp >= %(window_end)s
), following_day AS (
    SELECT * FROM flagged WHERE rating_timestamp < %(window_end)s + 86400
)
SELECT jsonb_build_object(
    'at_or_after_interpreted_utc_end', (SELECT COUNT(*) FROM flagged),
    'users_with_flagged_ratings', (SELECT COUNT(DISTINCT user_id) FROM flagged),
    'within_following_utc_day', (SELECT COUNT(*) FROM following_day),
    'at_or_after_another_24_hours', (SELECT COUNT(*) FROM flagged
        WHERE rating_timestamp >= %(window_end)s + 86400),
    'min_flagged_epoch', (SELECT MIN(rating_timestamp) FROM flagged),
    'max_flagged_epoch', (SELECT MAX(rating_timestamp) FROM flagged),
    'first_following_day_utc', (SELECT MIN(to_timestamp(rating_timestamp))::text FROM following_day),
    'last_following_day_utc', (SELECT MAX(to_timestamp(rating_timestamp))::text FROM following_day),
    'last_following_day_america_chicago', (SELECT
        (MAX(to_timestamp(rating_timestamp)) AT TIME ZONE 'America/Chicago')::text FROM following_day),
    'following_day_events_on_preceding_chicago_date', (SELECT COUNT(*) FROM following_day
        WHERE (to_timestamp(rating_timestamp) AT TIME ZONE 'America/Chicago')::date
            = (to_timestamp(%(window_end)s - 1) AT TIME ZONE 'UTC')::date),
    'interpretation', 'Calendar-boundary discrepancy; retained pending provenance clarification'
) AS timestamp_boundary_review;
