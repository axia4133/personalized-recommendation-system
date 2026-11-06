# SQL quality audit evidence

Milestone 3 is complete. These are executed diagnostic reports, not model
performance experiments or fabricated development notes.

- `2026-11-05-full.json`: initial completed full-data audit; all clean views
  preserved all source rows. It found 108 ratings beyond the UTC interpretation
  of the publisher's final calendar date. Its original timestamp query is
  archived in `initial_timestamp_query.sql` with a matching recorded SHA-256.
- `2026-11-05-full-reviewed.json`: reviewed audit, adds focused boundary analysis,
  clarifies the UTC interpretation in configuration, and uses a calendar display
  guard independent of the interpreted data window. The initial audit put those
  108 events in an out-of-window histogram bin; the reviewed histogram correctly
  includes them in calendar year 2023. Neither run excludes these records.
- `2026-11-05-full-final.json`: final evidence. Blank-field detection includes
  whitespace such as tabs/newlines; aggregate findings are unchanged. The exact
  earlier space-only core query is saved in `initial_core_query.sql` and matches
  the hash recorded in both earlier reports. Current SQL matches the final report.

All three runs were executed on November 5 in America/Los_Angeles; machine-readable
timestamps are UTC on November 6. Reports include all observed aggregate counts,
SQL parameters and hashes, per-query timing, environment, snapshot, and exact
clean/raw row counts. No row-level user interaction files are committed.

See [the quality report and decision record](../../docs/data_quality.md) for
actual results, rationale, limitations, and reproduction commands. Run new audits
with new report filenames. Configuration lives in `configs/data_quality.json`.

Main findings: no invalid ratings or orphan movie references; 7,080 movies with
no genre labels; 124 missing TMDb IDs; 198 repeated-title groups; 36 reused TMDb
mapping groups; sparse catalog coverage; a documented calendar-boundary
ambiguity. Current cleaning excludes zero rows. Activity distributions are not
training features and sparsity is not a negative label.
