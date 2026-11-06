-- Preserve individual tag events, including repeated source observations.
CREATE TABLE tags (
    tag_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id INTEGER NOT NULL,
    movie_id INTEGER NOT NULL REFERENCES movies (movie_id),
    tag TEXT,
    tag_timestamp BIGINT NOT NULL
);
