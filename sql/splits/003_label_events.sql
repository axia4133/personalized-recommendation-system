-- Retain every observed rating in the window, including cold/low-rated cases.
-- Status reasons are mutually exclusive; boolean flags preserve overlapping facts.
INSERT INTO label_events
WITH annotated AS (
    SELECT r.user_id, r.movie_id, r.rating, r.rating_timestamp,
           r.rating >= %(positive_threshold)s AS is_positive,
           COALESCE(u.rating_count,0) AS history_count,
           m.movie_id IS NOT NULL AS has_movie_history,
           EXISTS (SELECT 1 FROM {feature_schema}.history_ratings h
                   WHERE h.user_id=r.user_id AND h.movie_id=r.movie_id) AS seen_before
    FROM clean.ratings r
    LEFT JOIN {feature_schema}.user_features u USING (user_id)
    LEFT JOIN {feature_schema}.movie_features m USING (movie_id)
    WHERE r.rating_timestamp >= %(cutoff)s AND r.rating_timestamp < %(label_end)s
)
SELECT %(split)s, a.*,
       CASE WHEN NOT is_positive THEN 'below_positive_threshold'
            WHEN history_count=0 THEN 'cold_user'
            WHEN history_count < %(minimum_history)s THEN 'sparse_user'
            WHEN NOT has_movie_history THEN 'no_item_history'
            WHEN seen_before THEN 'already_seen'
            ELSE 'eligible_positive' END AS label_status
FROM annotated a;
