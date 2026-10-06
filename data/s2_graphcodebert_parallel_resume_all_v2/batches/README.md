# S2 independent feature-extraction batches

Five standalone package inputs are stored in `batch_01` through `batch_05`.
Each input is a disjoint subset of the current outstanding S2 index. Each
launcher runs three extraction shards, one parser worker per shard, with four
package paths per Git archive batch. The extractor writes and flushes shard
gzip output after every four-package batch; each shard also logs package
checkpoints. The launcher keeps a separate `runner.log` and timestamped output
directory for every run.

## Start any batch on a prepared machine

The machine needs this project with its S2 dependencies and local GraphCodeBERT
tokenizer cache, plus local MalwareBench npm and PyPI Git checkouts at the same
dataset revision. Package contents are read from Git archives, never installed
or executed. Set repository roots for that machine, then run any batch:

```powershell
$env:S2_NPM_ROOT = 'C:\path\to\npm'
$env:S2_PYPI_ROOT = 'C:\path\to\pypi'
powershell -NoProfile -File .\data\s2_graphcodebert_parallel_resume_all_v2\batches\batch_01\run_batch_01.ps1
```

Replace `batch_01` and the script name with the desired batch. Inputs do not
depend on another batch's output or progress. Keep each batch's input unchanged
while it is running. Outputs are isolated in that batch's `runs` directory.

## Counts and balance

`batch_manifest.json` records the source row count, checkpoint exclusions,
package counts, estimated work, ecosystem counts, and label counts. The
assignment CSV maps each package ID to exactly one batch. Estimated workload
uses source-file count plus eight times package size in MiB; this is a balancing
estimate, not a runtime guarantee.

`package_assignments.csv` provides a package-level audit trail. Batch launchers
record start/end timestamps and commands in `runner.log`; the extraction
coordinator also writes per-shard `shard_00.log` through `shard_02.log` and
compressed JSONL feature outputs.
