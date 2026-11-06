-- IMDb IDs are identifiers: TEXT preserves leading zeros.
-- Blank external identifiers are nullable; do not invent missing metadata.
CREATE TABLE links (
    movie_id INTEGER PRIMARY KEY REFERENCES movies (movie_id),
    imdb_id TEXT,
    tmdb_id INTEGER
);
