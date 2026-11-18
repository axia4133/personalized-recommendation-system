INSERT INTO candidate_catalog (split, movie_id, movie_index, prior_rating_count)
SELECT %(split)s, movie_id, (ROW_NUMBER() OVER (ORDER BY movie_id) - 1)::integer, rating_count
FROM {feature_schema}.movie_features;
