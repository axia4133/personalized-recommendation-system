CREATE TABLE positive_truth AS
SELECT split, user_id, movie_id, rating, rating_timestamp, history_count
FROM label_events WHERE label_status='eligible_positive';
ALTER TABLE positive_truth ADD PRIMARY KEY (split, user_id, movie_id);

-- Outcome-conditioned offline ranking cohort. Candidate construction itself
-- must not use these future positives; it uses only historical inputs.
CREATE TABLE ranking_users AS
SELECT g.split, g.user_id, COUNT(*) AS positive_count,
       MAX(g.history_count) AS history_count,
       (SELECT COUNT(*) FROM candidate_catalog c WHERE c.split=g.split)
           - MAX(g.history_count) AS candidate_count
FROM positive_truth g GROUP BY g.split, g.user_id;
ALTER TABLE ranking_users ADD PRIMARY KEY (split, user_id);

INSERT INTO training_examples
SELECT user_id, movie_id, 1, 'observed_positive', rating, rating_timestamp
FROM positive_truth WHERE split='train';
