CREATE TABLE ratings (
    user_id INTEGER,
    movie_id INTEGER,
    rating NUMERIC NOT NULL,
    rating_timestamp BIGINT NOT NULL,

    PRIMARY KEY (user_id, movie_id),
    FOREIGN KEY (movie_id) REFERENCES movies (movie_id),
    CHECK (rating BETWEEN 0.5 AND 5.0),
    CHECK (MOD(rating * 2, 1) = 0)
);