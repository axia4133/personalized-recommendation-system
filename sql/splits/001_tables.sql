CREATE TABLE partition_metadata (
    split TEXT PRIMARY KEY CHECK (split IN ('train','validation','test')),
    feature_schema TEXT NOT NULL UNIQUE,
    cutoff_epoch BIGINT NOT NULL,
    label_end_epoch BIGINT NOT NULL CHECK (label_end_epoch > cutoff_epoch),
    positive_threshold NUMERIC NOT NULL CHECK (positive_threshold BETWEEN 0.5 AND 5),
    minimum_history BIGINT NOT NULL CHECK (minimum_history >= 1)
);

CREATE TABLE candidate_catalog (
    split TEXT NOT NULL REFERENCES partition_metadata(split),
    movie_id INTEGER NOT NULL,
    movie_index INTEGER NOT NULL CHECK (movie_index >= 0),
    prior_rating_count BIGINT NOT NULL CHECK (prior_rating_count > 0),
    PRIMARY KEY (split, movie_id), UNIQUE (split, movie_index)
);

CREATE TABLE label_events (
    split TEXT NOT NULL REFERENCES partition_metadata(split),
    user_id INTEGER NOT NULL, movie_id INTEGER NOT NULL,
    rating NUMERIC NOT NULL, rating_timestamp BIGINT NOT NULL,
    is_positive BOOLEAN NOT NULL, history_count BIGINT NOT NULL,
    has_movie_history BOOLEAN NOT NULL, seen_before BOOLEAN NOT NULL,
    label_status TEXT NOT NULL CHECK (label_status IN (
        'below_positive_threshold','cold_user','sparse_user',
        'no_item_history','already_seen','eligible_positive')),
    PRIMARY KEY (split, user_id, movie_id)
);

CREATE TABLE training_examples (
    user_id INTEGER NOT NULL, movie_id INTEGER NOT NULL,
    target_label SMALLINT NOT NULL CHECK (target_label IN (0,1)),
    label_source TEXT NOT NULL,
    observed_rating NUMERIC,
    observed_timestamp BIGINT,
    PRIMARY KEY (user_id, movie_id),
    CHECK ((target_label = 1 AND label_source = 'observed_positive'
            AND observed_rating IS NOT NULL AND observed_timestamp IS NOT NULL)
        OR (target_label = 0 AND label_source = 'sampled_unobserved'
            AND observed_rating IS NULL AND observed_timestamp IS NULL))
);

CREATE TABLE negative_sampling_audit (
    user_id INTEGER PRIMARY KEY,
    positive_count BIGINT NOT NULL,
    requested_count BIGINT NOT NULL,
    available_count BIGINT NOT NULL,
    sampled_count BIGINT NOT NULL,
    proposal_count BIGINT NOT NULL,
    used_enumeration_fallback BOOLEAN NOT NULL
);
