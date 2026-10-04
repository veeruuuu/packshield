"""Run a deterministic, balanced GraphCodeBERT pilot without disk extraction."""

from __future__ import annotations

import argparse
import json
import random
import tempfile
from collections import Counter
from pathlib import Path

from packshield.tools.prepare_s2_graphcodebert_features import run as extract_features


def select_pilot_rows(rows: list[dict], per_label: int = 13, seed: int = 20261004) -> list[dict]:
    """Select up to ``per_label`` rows for every ecosystem/label pair."""
    if per_label < 1:
        raise ValueError("per_label must be positive")
    rng = random.Random(seed)
    selected = []
    for ecosystem in ("npm", "pypi"):
        for label in ("malicious", "benign"):
            candidates = sorted(
                (row for row in rows if row.get("ecosystem") == ecosystem
                 and row.get("label") == label and row.get("source_available")),
                key=lambda row: row["group_id"],
            )
            rng.shuffle(candidates)
            selected.extend(candidates[:per_label])
    return selected


def run_pilot(index: Path, npm_root: Path, pypi_root: Path, output: Path,
              features_output: Path, per_label: int = 13, seed: int = 20261004,
              model_name: str = "microsoft/graphcodebert-base",
              max_file_bytes: int = 2 * 1024 * 1024,
              file_timeout_seconds: float = 20) -> dict:
    rows = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    selected = select_pilot_rows(rows, per_label=per_label, seed=seed)
    output.parent.mkdir(parents=True, exist_ok=True)
    features_output.parent.mkdir(parents=True, exist_ok=True)

    # The temporary file contains JSON metadata only. Package source remains in
    # Git objects and is streamed to the killable feature worker in memory.
    with tempfile.TemporaryDirectory(prefix="packshield-s2-pilot-index-") as temp_dir:
        selected_index = Path(temp_dir) / "selected-index.jsonl"
        selected_index.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in selected),
            encoding="utf-8",
        )
        extraction = extract_features(
            selected_index, npm_root, pypi_root, features_output, model_name,
            batch_size=20, max_file_bytes=max_file_bytes,
            file_timeout_seconds=file_timeout_seconds,
        )

    selected_counts = Counter((row["ecosystem"], row["label"]) for row in selected)
    summary = {
        "selected_packages": len(selected),
        "selected_per_ecosystem_label": {
            f"{ecosystem}_{label}": selected_counts[(ecosystem, label)]
            for ecosystem in ("npm", "pypi")
            for label in ("malicious", "benign")
        },
        "per_label_target": per_label,
        "seed": seed,
        "features_output": str(features_output),
        "extraction": extraction,
    }
    output.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--npm-root", type=Path, required=True)
    parser.add_argument("--pypi-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True,
                        help="Pilot summary JSON output")
    parser.add_argument("--features-output", type=Path, required=True,
                        help="GraphCodeBERT features JSONL(.gz) output")
    parser.add_argument("--per-label", type=int, default=13,
                        help="Packages per ecosystem and class (default: 13; up to 52 total)")
    parser.add_argument("--seed", type=int, default=20261004)
    parser.add_argument("--model-name", default="microsoft/graphcodebert-base")
    parser.add_argument("--max-file-bytes", type=int, default=2 * 1024 * 1024)
    parser.add_argument("--file-timeout-seconds", type=float, default=20)
    args = parser.parse_args()
    summary = run_pilot(args.index, args.npm_root, args.pypi_root, args.output,
                        args.features_output, args.per_label, args.seed,
                        args.model_name, args.max_file_bytes,
                        args.file_timeout_seconds)
    print(json.dumps({"selected_packages": summary["selected_packages"],
                      "selected_per_ecosystem_label": summary["selected_per_ecosystem_label"],
                      "extraction": summary["extraction"]}, indent=2))


if __name__ == "__main__":
    main()
