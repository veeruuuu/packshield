# S2 completed feature merge snapshot

- Created UTC: 2026-10-06T09:17:56.719804+00:00
- Labeled split: 25426 rows (npm 14817; PyPI 10609); source-available: npm 14817, PyPI 10608 (one PyPI labeled row has no source).
- Already reconciled before current queue: 4296 complete IDs (npm 4,296).
- Saved checkpoint logs: 8859 IDs, including 2976 already in the prequeue set; unique stable complete total after union/pilot outputs: 10215 ({'npm': 10187, 'pypi': 28}).
- Completed pilot package IDs included: 56 ({'npm': 28, 'pypi': 28}).
- Live batch 01 was left running and its output files were excluded; current per-shard counters: {'shard_00.log': {'npm': 52}, 'shard_01.log': {'npm': 276}, 'shard_02.log': {'npm': 56}}, summed latest checkpoints: {'npm': 384}.
- Merged feature rows: 130445 ({'npm': 128928, 'pypi': 1517}); completed IDs with records: 9315; without records in saved archives: 900.
- Identical duplicate records skipped: 276011; differing duplicate keys recorded: 1058.
- Saved gzip sources read: 281; gzip files with trailer/read warnings: 179. Valid prefix records were retained.

## Package-level extraction statuses

- Scanned stable source archives for completion records without `relative_file`.
- Added 857 package status records: {'no_supported_source': 857}.
- Completed packages with any merged record: 10172 / 10215; unresolved completed IDs without any saved feature/status row: 43.
- Fully re-read merged gzip outputs through EOF: {'features_completed.jsonl.gz': 130445, 'package_status_features.jsonl.gz': 857}.
