# S2 extraction stop and batch handoff log

## Stop and preserve

- Stopped only the four active S2 extraction trees: `shard00_speed_v7` (PID
  16576), `shard01_speed_v6` (PID 17324), `shard02_speed_v7` (PID 2328), and
  `shard03_speed_v5` (PID 11536). Their Python, Git, parser-worker, and console
  descendants were stopped with each tree.
- Before stopping, copied each active `shard_00.jsonl.gz` and `shard_00.log`
  to sibling `*.pre_stop_<timestamp>.bak` files. Original run files and all
  earlier run directories remain in place.
- After stopping, confirmed no matching process command lines remained.
- Recovered complete JSONL records from the interrupted gzip streams to
  `shard_00.stop_salvaged.jsonl.gz`. The original gzip files were left untouched.

| Previous run | Salvaged records | Salvaged package IDs | Status breakdown | Gzip trailer present |
|---|---:|---:|---|---|
| `shard00_speed_v7` | 301 | 52 | 272 `ok`, 28 `parse_error`, 1 `no_supported_source` | No |
| `shard01_speed_v6` | 270 | 40 | 244 `ok`, 26 `parse_error` | No |
| `shard02_speed_v7` | 0 | 0 | No records | No |
| `shard03_speed_v5` | 3,215 | 52 | 2,714 `ok`, 501 `parse_error` | No |

The gzip streams did not have complete trailers at stop time. Salvage files
contain complete JSONL records recovered from those streams. Keep original
files, backups, and salvage outputs for later consolidation; deduplicate by
`(group_id, relative_file/status)` when merging.

## Completion audit and new partition

- Current four-shard index: 21,129 unique source-available package IDs.
- Across all S2 extraction runs: 8,859 unique package IDs had package-level
  completion checkpoints. Of these, 5,883 intersect the current index; all
  5,883 are npm. No PyPI packages in the current index have a completed package
  checkpoint yet.
- Excluded those 5,883 confirmed current-index IDs. Partitioned the remaining
  15,246 IDs into five disjoint batches. Each batch has 3,049 or 3,050 packages;
  estimated work ranges from 59,958,557.37 to 59,958,562.91 units.
- Each batch is balanced across ecosystem and label counts and has a standalone
  PowerShell launcher. Each launcher runs three shards with one parser worker
  apiece and archive batch size four. Every shard writes separate compressed
  output and per-batch package logs; runs never share output paths.
- `prepare_s2_batches.py` rebuilds the split from the current index and
  package-level logs. Review the manifest after rerunning it because regenerated
  assignments may differ if new completed checkpoints appear.

## Do not lose continuation state

- Inputs: `batch_01/input.jsonl` through `batch_05/input.jsonl`.
- Launchers: `batch_01/run_batch_01.ps1` through `batch_05/run_batch_05.ps1`.
- Detailed counts and workload: `batch_manifest.json`.
- Package-to-batch map: `package_assignments.csv`.
- Run logs and outputs: each batch's timestamped `runs/<run-id>/` directory.
- A machine running a batch needs this project, S2 Python dependencies, the
  local GraphCodeBERT tokenizer cache, and both MalwareBench Git checkouts at the
  same revision. The launchers accept `-NpmRoot` and `-PypiRoot` or the
  `S2_NPM_ROOT` and `S2_PYPI_ROOT` environment variables.

## Batch 01 launched

- Started `batch_01/run_batch_01.ps1` hidden with npm and PyPI Git roots set to
  `C:\Users\Veeresh\Desktop\npm` and `C:\Users\Veeresh\Desktop\pypi`.
- Run directory: `batch_01/runs/20261006_132956/`.
- Launcher PID: 10536. Coordinator shard PIDs: 15468, 19644, and 10896.
- Each shard received 1,016, 1,016, and 1,017 packages respectively. All three
  shard input indexes and logs were created successfully at startup.
- Runner log: `batch_01/runs/20261006_132956/runner.log`.
- Feature output files: `shard_00.jsonl.gz`, `shard_01.jsonl.gz`, and
  `shard_02.jsonl.gz` in the same run directory. Per-shard progress is logged
  after each four-package archive batch. Check CPU and timestamps along with
  these log counters; allow large packages to continue while activity remains.
- First verified progress: each shard reached 12 npm packages (of 302, 319,
  and 306 npm rows in its independently balanced shard); emitted source-file
  counts were 66, 54, and 53. Gzip files grew to 38,922, 48,359, and 63,955
  bytes respectively. They remain open while extraction runs, so do not run a
  full-stream gzip validation until the corresponding process exits; the
  extractor flushes completed four-package batches and the salvage utility can
  recover complete JSONL records if a later interruption occurs.
- Later live check: all shards reached 44 npm packages (132 new completed
  packages total). Their logs and gzip outputs had matching fresh timestamps;
  compressed outputs measured 74,975, 82,288, and 94,323 bytes. The current
  total is therefore 6,015 confirmed packages in the current index (all npm),
  with 15,114 still unconfirmed: 4,506 npm and 10,608 PyPI.
