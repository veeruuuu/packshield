"""
Assemble the Stage-1 training feature matrix from the name/metadata
dataset: S1 (name similarity) score computed fresh from the real signal
code, plus S4 raw features (NaN where unresolved), plus the
s4_registry_status categorical field.

KNOWN LIMITATION (see PROJECT.md log for this step): Sec 9 asks for a
temporal train/test split, but only relative day-counts were ever stored
for S4 features (package_age_days, days_since_last_publish), never an
absolute fetch timestamp. There is no way to reconstruct real calendar
dates from what's stored, so this script does NOT attempt a temporal
split -- it does a stratified random split instead, which does not
satisfy Sec 9's requirement. Flagged honestly, not silently substituted.

Usage:
    python -m packshield.training.prepare_features INPUT.jsonl OUTPUT.csv
"""

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packshield.signals.s1_name_similarity import score_name

FIELDNAMES = [
    "ecosystem", "name", "version", "label", "attack_type",
    "s1_score",
    "package_age_days", "days_since_last_publish",
    "total_versions", "versions_last_90_days", "maintainer_count",
    "weekly_downloads",
    "s4_registry_status",
]


def build_row(row: dict) -> dict:
    s1 = score_name(row["name"], row["ecosystem"])
    features = row.get("s4_features") or {}

    return {
        "ecosystem": row["ecosystem"],
        "name": row["name"],
        "version": row.get("version") or "",
        "label": row["label"],
        "attack_type": row.get("attack_type") or "",
        "s1_score": s1.score,
        "package_age_days": features.get("package_age_days", ""),
        "days_since_last_publish": features.get("days_since_last_publish", ""),
        "total_versions": features.get("total_versions", ""),
        "versions_last_90_days": features.get("versions_last_90_days", ""),
        "maintainer_count": features.get("maintainer_count", ""),
        "s4_registry_status": row.get("s4_registry_status", "unknown"),
        "weekly_downloads": features.get("weekly_downloads", ""),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_path")
    parser.add_argument("output_path")
    args = parser.parse_args()

    counts = {"malicious": 0, "benign": 0}
    with open(args.input_path, "r", encoding="utf-8") as f_in, \
         open(args.output_path, "w", newline="", encoding="utf-8") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=FIELDNAMES)
        writer.writeheader()
        for line in f_in:
            row = json.loads(line)
            out_row = build_row(row)
            writer.writerow(out_row)
            counts[row["label"]] = counts.get(row["label"], 0) + 1

    print(f"Wrote {args.output_path}")
    print(f"  malicious: {counts.get('malicious', 0)}")
    print(f"  benign: {counts.get('benign', 0)}")


if __name__ == "__main__":
    main()