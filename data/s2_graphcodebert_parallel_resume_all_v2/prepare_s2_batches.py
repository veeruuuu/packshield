"""Build five independent, balanced S2 feature-extraction batches.

The script reads the current four-shard S2 index and all package-level shard
checkpoints, then writes disjoint JSONL inputs, standalone PowerShell launchers,
and an auditable batch manifest under this directory's ``batches`` folder.
MalwareBench package contents are never opened by this planner.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


CHECKPOINT = re.compile(r"^(npm|pypi):\s+(\d+)/(\d+) packages;")
SHARD_INDEX = re.compile(r"^shard_\d+\.jsonl$")


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict) or not row.get("group_id"):
                    raise ValueError(f"Invalid package row at {path}:{line_number}")
                rows.append(row)
    return rows


def estimate_work(row: dict) -> float:
    try:
        files = max(1, int(float(row.get("total_file", 1))))
    except (TypeError, ValueError):
        files = 1
    try:
        size_mib = max(0.0, float(row.get("package_size", 0)))
    except (TypeError, ValueError):
        size_mib = 0.0
    return files + 8.0 * size_mib


def completed_ids(data_dir: Path) -> tuple[set[str], Counter[str]]:
    completed: set[str] = set()
    by_ecosystem: Counter[str] = Counter()
    for log_path in data_dir.parent.rglob("shard_*.log"):
        if not log_path.is_file():
            continue
        index_path = log_path.with_suffix(".jsonl")
        if not index_path.is_file():
            continue
        counters: dict[str, int] = {}
        with log_path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                match = CHECKPOINT.match(line.strip())
                if match:
                    counters[match.group(1)] = int(match.group(2))
        if not counters:
            continue
        rows_by_ecosystem: dict[str, list[str]] = defaultdict(list)
        for row in read_jsonl(index_path):
            ecosystem = row.get("ecosystem")
            if ecosystem in {"npm", "pypi"}:
                rows_by_ecosystem[ecosystem].append(str(row["group_id"]))
        for ecosystem, count in counters.items():
            ids = rows_by_ecosystem.get(ecosystem, [])[:count]
            before = len(completed)
            completed.update(ids)
            by_ecosystem[ecosystem] += len(completed) - before
    return completed, by_ecosystem


def partition(rows: list[dict], batch_count: int = 5) -> list[list[dict]]:
    categories = Counter((str(row.get("ecosystem", "unknown")),
                          str(row.get("label", "unknown"))) for row in rows)
    total_work = sum(estimate_work(row) for row in rows)
    target_work = total_work / batch_count if total_work else 1.0
    target_count = len(rows) / batch_count if rows else 1.0
    target_category = {key: count / batch_count for key, count in categories.items()}
    batches: list[list[dict]] = [[] for _ in range(batch_count)]
    loads = [0.0] * batch_count
    batch_categories = [Counter() for _ in range(batch_count)]
    order = sorted(rows, key=lambda row: (
        estimate_work(row), str(row.get("ecosystem", "")),
        str(row.get("label", "")), str(row["group_id"])), reverse=True)
    for row in order:
        category = (str(row.get("ecosystem", "unknown")),
                    str(row.get("label", "unknown")))
        weight = estimate_work(row)

        def score(batch_number: int) -> tuple[float, int, float, int]:
            work_score = ((loads[batch_number] + weight) / target_work) ** 2
            count_score = ((len(batches[batch_number]) + 1) / target_count) ** 2
            category_target = max(target_category[category], 0.2)
            category_score = ((batch_categories[batch_number][category] + 1)
                              / category_target) ** 2
            combined = 0.55 * work_score + 0.25 * count_score + 0.20 * category_score
            return (combined, len(batches[batch_number]), loads[batch_number], batch_number)

        selected = min(range(batch_count), key=score)
        batches[selected].append(row)
        loads[selected] += weight
        batch_categories[selected][category] += 1
    return batches


def launcher_text(batch_number: int) -> str:
    return f'''param(
    [string]$NpmRoot = $env:S2_NPM_ROOT,
    [string]$PypiRoot = $env:S2_PYPI_ROOT
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\\..\\..\\..')).Path
if (-not $NpmRoot) {{ $NpmRoot = Join-Path (Split-Path $ProjectRoot -Parent) 'npm' }}
if (-not $PypiRoot) {{ $PypiRoot = Join-Path (Split-Path $ProjectRoot -Parent) 'pypi' }}
if (-not (Test-Path -LiteralPath (Join-Path $NpmRoot '.git'))) {{ throw "npm Git checkout not found: $NpmRoot" }}
if (-not (Test-Path -LiteralPath (Join-Path $PypiRoot '.git'))) {{ throw "PyPI Git checkout not found: $PypiRoot" }}
$Python = Join-Path $ProjectRoot '.venv\\Scripts\\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {{ throw "Project venv missing: $Python" }}
$InputIndex = Join-Path $PSScriptRoot 'input.jsonl'
$RunId = Get-Date -Format 'yyyyMMdd_HHmmss'
$OutputDir = Join-Path $PSScriptRoot (Join-Path 'runs' $RunId)
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$RunLog = Join-Path $OutputDir 'runner.log'
"Batch {batch_number:02d} started: $(Get-Date -Format o)" | Tee-Object -FilePath $RunLog
"Input: $InputIndex" | Tee-Object -FilePath $RunLog -Append
"Output: $OutputDir" | Tee-Object -FilePath $RunLog -Append
"Shards: 3; parser workers: 1 per shard; archive batch size: 4" | Tee-Object -FilePath $RunLog -Append
& $Python -u -m packshield.tools.run_s2_extraction_parallel `
    --index $InputIndex `
    --npm-root $NpmRoot `
    --pypi-root $PypiRoot `
    --output-dir $OutputDir `
    --project-root $ProjectRoot `
    --workers 3 `
    --batch-size 4 `
    --poll-seconds 10 `
    --file-timeout-seconds 20 `
    --worker-startup-timeout 180 2>&1 | Tee-Object -FilePath $RunLog -Append
$ExitCode = $LASTEXITCODE
"Batch {batch_number:02d} finished: $(Get-Date -Format o); exit=$ExitCode" | Tee-Object -FilePath $RunLog -Append
exit $ExitCode
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path,
                        default=Path("data/s2_graphcodebert_parallel_resume_all_v2"))
    args = parser.parse_args()
    data_dir = args.data_dir.resolve()
    batch_dir = data_dir / "batches"

    source_rows = []
    for number in range(4):
        path = data_dir / f"shard_{number:02d}.jsonl"
        if not path.is_file():
            raise FileNotFoundError(path)
        source_rows.extend(row for row in read_jsonl(path)
                           if row.get("source_available"))
    current_by_id: dict[str, dict] = {}
    for row in source_rows:
        group_id = str(row["group_id"])
        if group_id in current_by_id and current_by_id[group_id] != row:
            raise ValueError(f"Conflicting duplicate package metadata: {group_id}")
        current_by_id[group_id] = row

    done_ids, _all_run_counts = completed_ids(data_dir)
    current_completed = Counter(
        str(current_by_id[group_id].get("ecosystem", "unknown"))
        for group_id in done_ids if group_id in current_by_id)
    outstanding = [row for group_id, row in current_by_id.items()
                   if group_id not in done_ids]
    if not outstanding:
        raise SystemExit("No uncompleted source-available S2 packages remain")
    batches = partition(outstanding)
    batch_dir.mkdir(parents=True, exist_ok=True)

    assignment_rows = []
    plans = []
    for number, batch in enumerate(batches, 1):
        folder = batch_dir / f"batch_{number:02d}"
        folder.mkdir(parents=True, exist_ok=True)
        input_path = folder / "input.jsonl"
        payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in batch)
        input_path.write_text(payload, encoding="utf-8", newline="")
        launcher = folder / f"run_batch_{number:02d}.ps1"
        launcher.write_text(launcher_text(number), encoding="utf-8", newline="\n")
        labels = Counter(str(row.get("label", "unknown")) for row in batch)
        ecosystems = Counter(str(row.get("ecosystem", "unknown")) for row in batch)
        work = sum(estimate_work(row) for row in batch)
        plans.append({
            "batch": number,
            "input": str(input_path),
            "launcher": str(launcher),
            "packages": len(batch),
            "estimated_work_units": round(work, 2),
            "ecosystems": dict(ecosystems),
            "labels": dict(labels),
        })
        assignment_rows.extend({
            "batch": number,
            "group_id": row["group_id"],
            "ecosystem": row.get("ecosystem", "unknown"),
            "label": row.get("label", "unknown"),
            "estimated_work_units": round(estimate_work(row), 2),
        } for row in batch)

    assignment_path = batch_dir / "package_assignments.csv"
    with assignment_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "batch", "group_id", "ecosystem", "label", "estimated_work_units"])
        writer.writeheader()
        writer.writerows(assignment_rows)

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_index_rows": len(current_by_id),
        "all_runs_unique_checkpoint_group_ids": len(done_ids),
        "confirmed_completed_group_ids_excluded": len(done_ids & current_by_id.keys()),
        "confirmed_completed_by_ecosystem_in_current_index": dict(current_completed),
        "outstanding_unique_packages": len(outstanding),
        "batch_count": len(batches),
        "parallel_shards_per_batch": 3,
        "parser_workers_per_shard": 1,
        "archive_batch_size": 4,
        "completion_basis": "last package-level counters in shard logs",
        "cost_estimate": "max(1,total_file) + 8 * max(0, package_size MiB)",
        "batches": plans,
    }
    (batch_dir / "batch_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
