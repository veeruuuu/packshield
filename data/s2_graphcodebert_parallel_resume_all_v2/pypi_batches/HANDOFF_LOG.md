# PyPI batches — activity log

## 2026-10-06 — prepared PyPI-only queue

- Used the four current S2 source-available indexes and retained only `ecosystem=pypi` rows.
- Excluded IDs already marked complete in package-level S2 logs and the stable merged feature ledger. Audit: 10,608 source-available PyPI IDs; 0 in package checkpoints; 28 in the prior stable merged feature ledger; 10,580 remaining.
- Created disjoint inputs of 3,000, 3,000, 3,000, and 1,580 rows, balanced by estimated work (`total_file + 8 * package_size MiB`).
- Batch outputs and logs are isolated under each batch’s `runs/<timestamp>/`.
- Previous mixed batch 01 had 927 npm and 2,122 PyPI rows. Its run output/log files were copied to `*.pre_pypi_stop_<timestamp>.bak`. Windows denied process inspection and task termination for its recorded launcher/coordinator PIDs; the last observed log/output write was 2026-10-06 14:23 local. The new queue excludes all prior stable-completed PyPI IDs and is PyPI-only.
- Run policy: batch 01 is started; keep batches 02–04 idle until batch 01 completes or the user asks to start another.

## 2026-10-06 15:19 local — PyPI batch 01 launched

- Started standalone `pypi_batches/batch_01/run_pypi_batch_01.ps1` (launcher PID 15172).
- Run folder: `pypi_batches/batch_01/runs/20261006_151735/`.
- Three PyPI-only workers started: shard 00 PID 4480 (999 rows), shard 01 PID 11312 (1,000 rows), shard 02 PID 11988 (1,001 rows). Each uses one parser worker and Git archive batch size 4.
- First observed log checkpoints: shard 00 76/999 packages (99 source files), shard 01 8/1,000 (5 files), shard 02 76/1,001 (103 files). Processes were visible with `Get-Process`; package logs were advancing.
- Old mixed Batch 01 outputs remain preserved in place, with timestamped pre-stop copies created. Its package logs/output timestamps remain unchanged since 14:23 local. `taskkill /T /F` returned Access Denied for recorded old launcher/coordinator PIDs 10536, 15468, 19644, and 10896. `Get-Process` did not show those PIDs; therefore the prior npm run appears inactive, but termination could not be positively confirmed through this shell. No new npm work was launched.


## 2026-10-06 16:35 local — stalled batch 01 salvaged and resumed

- Confirmed stall: all three original shard package logs, output sizes, and Python/Git CPU totals were unchanged for over an hour. Latest completed counters before stop were 256/999, 8/1,000, and 472/1,001 (736 package IDs total).
- Backed up all three shard indices, logs, compressed outputs, and runner log to `*.stall_backup_20261006_162757.bak` before stopping.
- Terminated only the three stalled PyPI shard trees and their batch launcher using their recorded PIDs. Confirmed the old PIDs and descendants were no longer present.
- Recovered 1,580 complete feature/status JSON records (736 package IDs) from the interrupted gzip prefixes and rewrote a valid gzip at `batch_01/runs/20261006_151735/salvaged_prefix/salvaged_features.jsonl.gz`. Original incomplete gzip files and backups are retained unchanged. All three source prefixes lacked gzip end markers.
- Excluded the 736 checkpoint-complete IDs from the resume index. Deferred the next four package IDs from each stalled shard (12 total) so they are retried after other remaining packages. Resume index has 2,264 rows; details and exact IDs are in `batch_01/resume_01/resume_plan.json`.
- Launched recovery run `batch_01/resume_01/runs/20261006_163450/` (launcher PID 15292). Three shards started with 756, 756, and 752 rows. First observed progress: 36/756, 36/756, and 36/752. All three parser workers and Git archive processes were visible and active.
- Extraction reads PyPI Git archive source only; package files are not installed or executed.

## 2026-10-06 17:44 local — live batch 01 recovery checkpoint saved

- User requested saving progress; did not stop or alter the live extraction files.
- Copied all three shard indexes/logs, runner log, and compressed outputs to `*.checkpoint_20261006_174455.bak` beside the active files.
- Last package checkpoints at copy time: shard 00 80/756, shard 01 116/756, shard 02 64/752 (260 completed package IDs total).
- Recovered 586 complete JSON feature/status records from the snapshots and wrote `runs/20261006_163450/checkpoints/20261006_174455/features_checkpoint.jsonl.gz`; read back and validated all 586 records to gzip EOF. The three live gzip files themselves lacked end markers at snapshot time, so preserve both snapshots and the validated checkpoint gzip.
- At follow-up (17:46 local), package logs/output sizes were still unchanged since ~16:36. The recorded Python/Git processes remained present; some Python CPU totals had advanced since the earlier check. Left the run active while watching for further package/output progress.
