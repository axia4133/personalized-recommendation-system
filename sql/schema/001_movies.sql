-- Milestone 2: movies parent table (no ratings yet).
-- Source: MovieLens movies.csv (movieId, title, genres).

CREATE TABLE movies (
    movie_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    genres_raw TEXT
);
