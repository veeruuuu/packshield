# S2 GraphCodeBERT completed-output merge

Current consolidated snapshot: `snapshot_20261006_144223/`.

- `features_completed.jsonl.gz`: 130,445 deduplicated file-level feature records.
- `package_status_features.jsonl.gz`: 857 package-level `no_supported_source` outcomes.
- `completed_packages.jsonl`: 10,215 stable completed package IDs with per-package feature-record counts.
- `unresolved_completed_packages.jsonl`: 43 package IDs logged as complete but with no recoverable feature or status row; all 43 are npm and need recovery/retry.
- `conflicts.jsonl`: 1,058 duplicate package/file keys whose records differed across attempts. The selected row and alternate source are recorded.
- `merge_summary.json` and `merge_log.md`: counts, source coverage, validation, and merge notes.

The snapshot was made while batch 01 was running. Its live gzip outputs were excluded to avoid reading files while they were being written. At snapshot time, its three shard logs showed 52, 276, and 56 npm packages completed. Re-run the merge after the batch closes to incorporate those feature files.

Two earlier snapshots in this directory are intermediate and superseded by `snapshot_20261006_144223/`; they are retained for auditability.
