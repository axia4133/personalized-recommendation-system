# Data

This directory is the landing place for MovieLens files. **Do not commit raw or processed datasets.**

## Authoritative source

- Dataset: [MovieLens 32M](https://grouplens.org/datasets/movielens/32m/)
- Publisher: GroupLens (University of Minnesota)
- Typical archive name: `ml-32m.zip`

Download only from the official GroupLens page. Review their license and citation requirements before use.

## Intended local layout (not created yet)

```text
data/
  README.md          # this file
  raw/               # unzipped MovieLens files (gitignored)
  processed/         # derived exports, if any (gitignored)
```

## Status

No dataset files have been downloaded or ingested.

For development we will load a **small sample** into PostgreSQL before attempting the full ~32 million ratings.
