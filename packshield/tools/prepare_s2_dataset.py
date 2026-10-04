"""Build the labeled MalwareBench index used by the S2 work.

This tool only reads CSV metadata and checks filesystem paths. It never imports,
installs, or executes package contents. The generated JSONL keeps rows whose
source directory is currently missing so checkout problems cannot silently
change the training population; downstream training must filter those rows
explicitly and report the omission.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import subprocess
from collections import Counter
from pathlib import Path


LABELS = {
    "malware": "malicious",
    "false_positive": "benign",
}
REQUIRED_COLUMNS = {
    "group_ID",
    "ecosystem",
    "scoped",
    "name",
    "version",
    "artifact_id",
    "total_file",
    "package_size",
    "threat_type",
}


def _metadata_text(repo_root: Path, ecosystem: str) -> tuple[str, str]:
    filename = f"{ecosystem}_package_info.csv"
    path = repo_root / filename
    if path.is_file():
        return path.read_text(encoding="utf-8"), str(path)

    # A broken Windows checkout may have the metadata in Git HEAD while the
    # working-tree file is missing. Reading the committed blob keeps indexing
    # read-only and makes that state visible in the summary.
    try:
        result = subprocess.run(
            ["git", "-c", "safe.directory=*", "-C", str(repo_root),
             "show", f"HEAD:{filename}"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise FileNotFoundError(f"metadata file not found: {path}") from exc
    return result.stdout, f"{repo_root} (Git HEAD:{filename})"


def _source_path(repo_root: Path, row: dict[str, str]) -> Path:
    packages = repo_root / "packages"
    ecosystem = row["ecosystem"].strip().lower()
    name = row["name"].strip()
    version = row["version"].strip()

    if ecosystem == "npm":
        scoped = row.get("scoped", "").strip()
        if scoped:
            return packages / scoped / name / version
        return packages / name / version

    if ecosystem == "pypi":
        artifact_id = row.get("artifact_id", "").strip()
        if not artifact_id:
            raise ValueError(
                f"PyPI row has no artifact_id: {row.get('group_ID', '<unknown>')}"
            )
        return packages / name / version / artifact_id

    raise ValueError(f"unsupported ecosystem: {ecosystem!r}")


def _git_source_roots(repo_root: Path, ecosystem: str) -> set[str]:
    """Return package roots represented in Git HEAD, without checking them out."""
    try:
        result = subprocess.run(
            ["git", "-c", "safe.directory=*", "-C", str(repo_root),
             "ls-tree", "-r", "--name-only", "HEAD", "--", "packages"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return set()

    roots: set[str] = set()
    for line in result.stdout.splitlines():
        parts = line.replace("\\", "/").split("/")
        if parts and parts[0] == "packages":
            # npm scoped and PyPI artifact paths both have five components;
            # unscoped npm paths have four and are handled separately.
            if ecosystem == "npm" and len(parts) >= 4 and not parts[1].startswith("@"):
                roots.add("/".join(parts[:3]))
            elif ecosystem == "npm" and len(parts) >= 5 and parts[1].startswith("@"):
                roots.add("/".join(parts[:4]))
            elif ecosystem == "pypi" and len(parts) >= 5:
                roots.add("/".join(parts[:4]))
    return roots


def build_index(npm_root: Path, pypi_root: Path, output: Path) -> dict[str, object]:
    output.parent.mkdir(parents=True, exist_ok=True)
    counters = Counter()
    rows_written = 0

    with output.open("w", encoding="utf-8", newline="") as destination:
        for ecosystem, repo_root in (("npm", npm_root), ("pypi", pypi_root)):
            metadata_text, metadata_source = _metadata_text(repo_root, ecosystem)
            git_roots = _git_source_roots(repo_root, ecosystem)
            reader = csv.DictReader(io.StringIO(metadata_text))
            columns = set(reader.fieldnames or [])
            missing_columns = REQUIRED_COLUMNS - columns
            if missing_columns:
                raise ValueError(
                    f"{metadata_source} is missing columns: {sorted(missing_columns)}"
                )

            for row in reader:
                threat_type = row["threat_type"].strip().lower()
                counters[f"raw_{ecosystem}"] += 1
                if threat_type == "unreviewed":
                    counters["dropped_unreviewed"] += 1
                    continue
                if threat_type not in LABELS:
                    counters["dropped_unknown_label"] += 1
                    continue

                source_path = _source_path(repo_root, row)
                source_exists = source_path.is_dir()
                relative_source = source_path.relative_to(repo_root).as_posix()
                source_in_git = relative_source in git_roots
                record = {
                    "group_id": row["group_ID"].strip(),
                    "ecosystem": ecosystem,
                    "name": row["name"].strip(),
                    "scoped": row.get("scoped", "").strip() or None,
                    "version": row["version"].strip(),
                    "artifact_id": row.get("artifact_id", "").strip() or None,
                    "label": LABELS[threat_type],
                    "source_path": str(source_path.resolve()),
                    "source_exists": source_exists,
                    "source_in_git": source_in_git,
                    "source_available": source_exists or source_in_git,
                    "total_file": row.get("total_file", "").strip() or None,
                    "package_size": row.get("package_size", "").strip() or None,
                    "original_threat_type": threat_type,
                    "attack_type_confidence": None,
                }
                destination.write(json.dumps(record, ensure_ascii=False) + "\n")
                rows_written += 1
                counters[f"{ecosystem}_{record['label']}"] += 1
                counters[f"{ecosystem}_{'present' if source_exists else 'missing'}"] += 1
                counters[f"{ecosystem}_{'git_present' if source_in_git else 'git_missing'}"] += 1

    summary = {
        "output": str(output.resolve()),
        "rows_written": rows_written,
        "counters": dict(sorted(counters.items())),
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--npm-root", type=Path, required=True)
    parser.add_argument("--pypi-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_index(args.npm_root, args.pypi_root, args.output), indent=2))


if __name__ == "__main__":
    main()
