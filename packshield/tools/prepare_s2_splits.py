"""Create deterministic S2 train/validation/test splits from the MalwareBench index.

MalwareBench's package metadata has no publish-date field, so this tool uses a
seeded grouped stratified random split. Groups are (ecosystem, name, version)
to keep PyPI wheel/sdist variants of one release in the same split. Validation
and test retain every row; only the training set may be undersampled when the
class ratio exceeds the configured imbalance threshold.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path


def _read_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _write_rows(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _allocate_groups(groups: list[list[dict]], rng: random.Random, fraction: float) -> int:
    target = round(len(groups) * fraction)
    return max(0, min(len(groups), target))


def build_splits(index_path: Path, output_dir: Path, seed: int = 42,
                 train_fraction: float = 0.70, validation_fraction: float = 0.15,
                 imbalance_threshold: float = 1.5) -> dict:
    rows = _read_rows(index_path)
    if not rows:
        raise ValueError("index is empty")

    date_fields = sorted({key for row in rows for key in row if "date" in key.lower() or "publish" in key.lower()})
    groups_by_label: dict[str, list[list[dict]]] = defaultdict(list)
    grouped: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    conflicting_groups: list[list[dict]] = []
    for row in rows:
        key = (row["ecosystem"], row.get("scoped") or "", row["name"], row["version"])
        grouped[key].append(row)
    for group in grouped.values():
        labels = {row["label"] for row in group}
        if len(labels) != 1:
            conflicting_groups.append(group)
            continue
        groups_by_label[next(iter(labels))].append(group)

    rng = random.Random(seed)
    train: list[dict] = []
    validation: list[dict] = []
    test: list[dict] = []
    for label, groups in sorted(groups_by_label.items()):
        rng.shuffle(groups)
        train_count = _allocate_groups(groups, rng, train_fraction)
        validation_count = _allocate_groups(groups[train_count:], rng, validation_fraction / (1 - train_fraction))
        train_groups = groups[:train_count]
        validation_groups = groups[train_count:train_count + validation_count]
        test_groups = groups[train_count + validation_count:]
        train.extend(row for group in train_groups for row in group)
        validation.extend(row for group in validation_groups for row in group)
        test.extend(row for group in test_groups for row in group)

    def counts(items: list[dict]) -> dict[str, int]:
        return dict(sorted(Counter(row["label"] for row in items).items()))

    train_counts = counts(train)
    malicious = train_counts.get("malicious", 0)
    benign = train_counts.get("benign", 0)
    ratio = (max(malicious, benign) / min(malicious, benign)) if min(malicious, benign) else None
    balanced_training = list(train)
    undersampled = False
    if ratio is not None and ratio > imbalance_threshold:
        minority = min(malicious, benign)
        by_label = defaultdict(list)
        for row in train:
            by_label[row["label"]].append(row)
        for label_rows in by_label.values():
            rng.shuffle(label_rows)
        balanced_training = by_label["malicious"][:minority] + by_label["benign"][:minority]
        rng.shuffle(balanced_training)
        undersampled = True

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_rows(output_dir / "train.jsonl", train)
    _write_rows(output_dir / "validation.jsonl", validation)
    _write_rows(output_dir / "test.jsonl", test)
    _write_rows(output_dir / "train_balanced.jsonl", balanced_training)

    summary = {
        "index": str(index_path.resolve()),
        "output_dir": str(output_dir.resolve()),
        "seed": seed,
        "split_method": "stratified_random_grouped_by_ecosystem_name_version",
        "temporal_split": False,
        "date_fields_found": date_fields,
        "total_rows": len(rows),
        "conflicting_label_groups_excluded": len(conflicting_groups),
        "conflicting_rows_excluded": sum(len(group) for group in conflicting_groups),
        "split_rows": {"train": len(train), "validation": len(validation), "test": len(test)},
        "class_counts": {"all": counts(rows), "train": train_counts,
                         "validation": counts(validation), "test": counts(test),
                         "train_balanced": counts(balanced_training)},
        "malicious_to_benign_ratio_all": (Counter(row["label"] for row in rows).get("malicious", 0) /
                                           Counter(row["label"] for row in rows).get("benign", 1)),
        "training_undersampled": undersampled,
        "train_balanced_identical_to_train": balanced_training == train,
        "train_balanced_note": ("identical to train because the class ratio did not exceed the imbalance threshold"
                                 if balanced_training == train else "undersampled majority class for training only"),
        "imbalance_threshold": imbalance_threshold,
        "attack_type_labels_available": False,
        "attack_type_confidence_policy": "null; MalwareBench threat_type has no T1-T4 attack category",
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    print(json.dumps(build_splits(args.index, args.output_dir, seed=args.seed), indent=2))


if __name__ == "__main__":
    main()
