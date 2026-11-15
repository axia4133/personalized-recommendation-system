CREATE TABLE snapshot_context AS
SELECT TRUE AS singleton,
       %(cutoff)s::bigint AS cutoff_epoch,
       %(cutoff_utc)s::timestamptz AS cutoff_utc,
       %(recent_start)s::bigint AS recent_start_epoch,
       %(recent_window_days)s::integer AS recent_window_days,
       %(movie_prior_count)s::double precision AS movie_prior_count,
       %(genre_prior_weight)s::double precision AS genre_prior_weight,
       %(genre_metadata_policy)s::text AS genre_metadata_policy,
       current_database()::text AS source_database,
       (SELECT COUNT(*) FROM clean.ratings) AS source_rating_rows,
       COUNT(*) AS history_rows,
       MIN(rating_timestamp) AS min_history_timestamp,
       MAX(rating_timestamp) AS max_history_timestamp,
       AVG(rating)::double precision AS global_mean_rating
FROM history_ratings;
