-- Only historically observed movies enter this snapshot's catalog proxy.
-- Genre labels are static, unversioned metadata, NOT proven historical values.
CREATE TABLE movie_genres AS
WITH observed_movies AS (
    SELECT DISTINCT movie_id FROM history_ratings
), tokens AS (
    SELECT m.movie_id, btrim(g.genre) AS genre
    FROM clean.movies m JOIN observed_movies o USING (movie_id)
    CROSS JOIN LATERAL unnest(string_to_array(m.genres_raw, '|')) AS g(genre)
), distinct_genres AS (
    SELECT DISTINCT movie_id, genre FROM tokens
    WHERE genre <> '' AND genre <> '(no genres listed)'
)
SELECT movie_id, genre,
       COUNT(*) OVER (PARTITION BY movie_id)::integer AS genre_count
FROM distinct_genres;
