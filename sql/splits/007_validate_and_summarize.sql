WITH status_counts AS (
    SELECT split, label_status, COUNT(*) AS rows FROM label_events GROUP BY split,label_status
), summaries AS (
    SELECT p.split,
           (SELECT COUNT(*) FROM label_events l WHERE l.split=p.split) AS window_ratings,
           (SELECT COUNT(DISTINCT user_id) FROM label_events l WHERE l.split=p.split) AS window_users,
           (SELECT COUNT(*) FROM label_events l WHERE l.split=p.split AND is_positive) AS observed_positive_labels,
           (SELECT COUNT(*) FROM positive_truth g WHERE g.split=p.split) AS eligible_positive_labels,
           (SELECT COUNT(*) FROM ranking_users u WHERE u.split=p.split) AS ranking_users,
           (SELECT COUNT(*) FROM history_user_counts u WHERE u.split=p.split
               AND u.history_count >= p.minimum_history) AS all_warm_history_users,
           (SELECT COUNT(*) FROM candidate_catalog c WHERE c.split=p.split) AS catalog_movies,
           (SELECT MIN(candidate_count) FROM ranking_users u WHERE u.split=p.split) AS min_candidates,
           (SELECT MAX(candidate_count) FROM ranking_users u WHERE u.split=p.split) AS max_candidates,
           (SELECT AVG(candidate_count) FROM ranking_users u WHERE u.split=p.split) AS mean_candidates,
           (SELECT jsonb_object_agg(label_status,rows) FROM status_counts s WHERE s.split=p.split) AS status_counts
    FROM partition_metadata p
)
SELECT jsonb_build_object(
    'partitions', (SELECT jsonb_agg(to_jsonb(s) ORDER BY CASE split
        WHEN 'train' THEN 0 WHEN 'validation' THEN 1 ELSE 2 END) FROM summaries s),
    'training', (SELECT jsonb_build_object(
        'rows', COUNT(*), 'positive_rows', COUNT(*) FILTER (WHERE target_label=1),
        'sampled_unobserved_rows', COUNT(*) FILTER (WHERE target_label=0),
        'users', COUNT(DISTINCT user_id)) FROM training_examples),
    'sampling', (SELECT jsonb_build_object(
        'users', COUNT(*), 'requested', COALESCE(SUM(requested_count),0),
        'sampled', COALESCE(SUM(sampled_count),0),
        'users_with_pool_shortfall', COUNT(*) FILTER (WHERE sampled_count < requested_count),
        'users_without_negative_pool', COUNT(*) FILTER (WHERE available_count=0),
        'proposal_count', COALESCE(SUM(proposal_count),0),
        'users_using_enumeration_fallback', COUNT(*) FILTER (WHERE used_enumeration_fallback)
    ) FROM negative_sampling_audit),
    'invalid_label_windows', (SELECT COUNT(*) FROM label_events l JOIN partition_metadata p USING (split)
        WHERE l.rating_timestamp < p.cutoff_epoch OR l.rating_timestamp >= p.label_end_epoch),
    'invalid_positive_truth', (SELECT COUNT(*) FROM positive_truth g
        JOIN partition_metadata p USING (split)
        LEFT JOIN candidate_catalog c ON c.split=g.split AND c.movie_id=g.movie_id
        WHERE g.rating < p.positive_threshold OR g.history_count < p.minimum_history
            OR c.movie_id IS NULL OR EXISTS (SELECT 1 FROM historical_pairs h
                WHERE h.split=g.split AND h.user_id=g.user_id AND h.movie_id=g.movie_id)),
    'invalid_training_negatives', (SELECT COUNT(*) FROM training_examples e
        LEFT JOIN candidate_catalog c ON c.split='train' AND c.movie_id=e.movie_id
        WHERE e.target_label=0 AND (c.movie_id IS NULL
            OR EXISTS (SELECT 1 FROM historical_pairs h WHERE h.split='train'
                AND h.user_id=e.user_id AND h.movie_id=e.movie_id)
            OR EXISTS (SELECT 1 FROM label_events l WHERE l.split='train'
                AND l.user_id=e.user_id AND l.movie_id=e.movie_id))),
    'invalid_training_positives', (SELECT COUNT(*) FROM training_examples e
        WHERE e.target_label=1 AND NOT EXISTS (SELECT 1 FROM positive_truth g
            WHERE g.split='train' AND g.user_id=e.user_id AND g.movie_id=e.movie_id
                AND g.rating=e.observed_rating AND g.rating_timestamp=e.observed_timestamp)),
    'invalid_ranking_users', (SELECT COUNT(*) FROM ranking_users WHERE positive_count < 1 OR candidate_count < positive_count),
    'sampling_budget_mismatches', (SELECT COUNT(*) FROM negative_sampling_audit
        WHERE sampled_count <> LEAST(requested_count,available_count)),
    'sampling_input_policy', 'Training history and training-window observations only'
) AS dataset_summary;
