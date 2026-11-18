-- Aggregate diagnostic only: ranking users are selected by future observed
-- positives, whereas candidate item sets never depend on those outcomes.
WITH per_user AS MATERIALIZED (
    SELECT split,user_id,MIN(history_count) AS min_history,MAX(history_count) AS history_count,
           BOOL_OR(is_positive) AS has_observed_positive,
           BOOL_OR(label_status='eligible_positive') AS has_eligible_positive
    FROM label_events GROUP BY split,user_id
), grouped AS (
    SELECT p.split,COUNT(u.user_id) AS window_users,
           COUNT(*) FILTER (WHERE u.history_count=0) AS window_cold_users,
           COUNT(*) FILTER (WHERE u.history_count>0 AND u.history_count<p.minimum_history) AS window_sparse_users,
           COUNT(*) FILTER (WHERE u.history_count>=p.minimum_history) AS window_warm_users,
           COUNT(*) FILTER (WHERE u.has_observed_positive) AS window_users_with_observed_positive,
           COUNT(*) FILTER (WHERE u.has_eligible_positive) AS ranking_users,
           COUNT(*) FILTER (WHERE u.history_count>=p.minimum_history AND NOT u.has_eligible_positive)
               AS window_warm_users_without_eligible_positive,
           COUNT(*) FILTER (WHERE u.min_history<>u.history_count) AS inconsistent_history_count_users,
           (SELECT COUNT(*) FROM history_user_counts h
               WHERE h.split=p.split AND h.history_count>=p.minimum_history) AS all_warm_history_users
    FROM partition_metadata p LEFT JOIN per_user u USING (split)
    GROUP BY p.split,p.minimum_history
)
SELECT jsonb_agg(to_jsonb(g) ORDER BY CASE split WHEN 'train' THEN 0 WHEN 'validation' THEN 1 ELSE 2 END)
FROM grouped g;
