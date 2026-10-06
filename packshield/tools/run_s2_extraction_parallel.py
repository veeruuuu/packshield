"""Run independent, bounded S2 feature-extraction shards in parallel.

This coordinator only partitions the metadata index and launches the existing
static extractor. Package contents are still read from Git archives and are
never installed or executed.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import subprocess
import sys
import time
from pathlib import Path


def _estimated_work(row: dict) -> float:
    """Rough extraction cost: source-file count plus unpacked MiB weight."""
    try:
        files = max(1, int(float(row.get("total_file", 1))))
    except (TypeError, ValueError):
        files = 1
    try:
        size_mib = max(0.0, float(row.get("package_size", 0)))
    except (TypeError, ValueError):
        size_mib = 0.0
    return files + 8.0 * size_mib


def _partition(rows: list[dict], workers: int,
               deferred_group_ids: set[str] | None = None) -> list[list[dict]]:
    deferred_group_ids = deferred_group_ids or set()
    shards: list[list[dict]] = [[] for _ in range(workers)]
    loads = [0.0] * workers
    for row in sorted(rows, key=lambda item: (
            item.get("group_id") in deferred_group_ids, _estimated_work(item)), reverse=True):
        shard = min(range(workers), key=loads.__getitem__)
        shards[shard].append(row)
        loads[shard] += _estimated_work(row)
    # Balance by file volume, but start on the smaller jobs so useful results
    # are committed early instead of waiting behind the largest package.
    for shard in shards:
        shard.sort(key=lambda item: (
            item.get("group_id") in deferred_group_ids, _estimated_work(item)))
    return shards


def _tail_new_lines(path: Path, position: int) -> tuple[int, list[str]]:
    if not path.exists():
        return position, []
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        stream.seek(position)
        lines = stream.readlines()
        return stream.tell(), [line.rstrip() for line in lines if line.strip()]


def _report_line(line: str) -> bool:
    match = re.search(r":\s+(\d+)/(\d+) packages;", line)
    if not match:
        return True
    completed, total = map(int, match.groups())
    return completed == 1 or completed % 50 == 0 or completed == total


def run(args: argparse.Namespace) -> int:
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    rows = [row for row in rows if row.get("source_available")]
    if not rows:
        raise SystemExit("No source_available rows found in the S2 index")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    shards = _partition(rows, args.workers, set(args.defer_group_id))
    processes: list[dict] = []
    for number, shard in enumerate(shards):
        if not shard:
            continue
        index_path = args.output_dir / f"shard_{number:02d}.jsonl"
        output_path = args.output_dir / f"shard_{number:02d}.jsonl.gz"
        log_path = args.output_dir / f"shard_{number:02d}.log"
        index_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                                         for row in shard), encoding="utf-8")
        command = [
            sys.executable, "-u", "-m", "packshield.tools.prepare_s2_graphcodebert_features",
            "--index", str(index_path), "--npm-root", str(args.npm_root),
            "--pypi-root", str(args.pypi_root), "--output", str(output_path),
            "--model-name", args.model_name, "--batch-size", str(args.batch_size),
            "--file-timeout-seconds", str(args.file_timeout_seconds),
            "--worker-startup-timeout", str(args.worker_startup_timeout),
        ]
        log = log_path.open("w", encoding="utf-8", buffering=1)
        process = subprocess.Popen(command, cwd=args.project_root, stdout=log,
                                   stderr=subprocess.STDOUT, text=True)
        processes.append({"number": number, "rows": len(shard), "path": log_path,
                          "position": 0, "process": process, "log": log,
                          "reported_exit": False})
        print(f"Started shard {number:02d}: {len(shard)} packages; PID {process.pid}",
              flush=True)

    try:
        while any(item["process"].poll() is None for item in processes):
            for item in processes:
                item["position"], lines = _tail_new_lines(item["path"], item["position"])
                for line in lines:
                    if _report_line(line):
                        print(f"[shard {item['number']:02d}] {line}", flush=True)
                code = item["process"].poll()
                if code is not None and not item["reported_exit"]:
                    item["reported_exit"] = True
                    print(f"Shard {item['number']:02d} exited with code {code}", flush=True)
            time.sleep(args.poll_seconds)

        failures = []
        for item in processes:
            item["position"], lines = _tail_new_lines(item["path"], item["position"])
            for line in lines:
                if _report_line(line):
                    print(f"[shard {item['number']:02d}] {line}", flush=True)
            code = item["process"].returncode
            if code:
                failures.append((item["number"], code))
        if failures:
            print(f"Shard failures: {failures}; partial shard files and logs were preserved",
                  flush=True)
            return 1

        merged = args.output_dir / args.merged_name
        with gzip.open(merged, "wt", encoding="utf-8", newline="\n") as destination:
            for item in processes:
                shard_output = args.output_dir / f"shard_{item['number']:02d}.jsonl.gz"
                with gzip.open(shard_output, "rt", encoding="utf-8") as source:
                    for line in source:
                        destination.write(line)
        print(f"Merged {len(rows)} package rows into {merged}", flush=True)
        return 0
    finally:
        for item in processes:
            process = item["process"]
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            item["log"].close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--npm-root", type=Path, required=True)
    parser.add_argument("--pypi-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--defer-group-id", action="append", default=[],
                        help="Keep this package ID last in its shard for a later retry")
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--poll-seconds", type=float, default=30)
    parser.add_argument("--file-timeout-seconds", type=float, default=20)
    parser.add_argument("--worker-startup-timeout", type=float, default=180)
    parser.add_argument("--model-name", default="microsoft/graphcodebert-base")
    parser.add_argument("--merged-name", default="features_parallel.jsonl.gz")
    args = parser.parse_args()
    if args.workers < 1 or args.batch_size < 1 or args.poll_seconds <= 0:
        parser.error("workers and batch-size must be positive; poll-seconds must be positive")
    if not args.project_root.is_absolute():
        args.project_root = args.project_root.resolve()
    if not args.output_dir.is_absolute():
        args.output_dir = (args.project_root / args.output_dir).resolve()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
