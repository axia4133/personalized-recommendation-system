-- Exhaustive historical catalog minus pre-cutoff seen items. This query does
-- NOT consult positive_truth, ranking_users, or any future label_events.
SELECT c.movie_id FROM candidate_catalog c
JOIN history_user_counts u ON u.split=c.split AND u.user_id=%(user_id)s
JOIN partition_metadata p ON p.split=c.split
WHERE c.split=%(split)s AND u.history_count >= p.minimum_history
  AND NOT EXISTS (SELECT 1 FROM historical_pairs h
      WHERE h.split=c.split AND h.user_id=%(user_id)s AND h.movie_id=c.movie_id)
ORDER BY c.movie_id;
