"""Build an S2 resume index by excluding package IDs with saved feature rows."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path


def _records(path: Path):
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    try:
        with opener(path, "rt", encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
    except (EOFError, OSError):
        # Interrupted gzip members can still contain complete records at their
        # beginning. Salvage tooling writes those to a valid gzip first, so an
        # incomplete source is tolerated only to the extent Python yielded rows.
        return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--completed", type=Path, action="append", required=True)
    args = parser.parse_args()

    done: set[str] = set()
    report = []
    for path in args.completed:
        before = len(done)
        done.update(str(record["group_id"]) for record in _records(path)
                    if record.get("group_id"))
        report.append({"path": str(path), "new_package_ids": len(done) - before,
                       "total_package_ids": len(done)})

    rows = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    rows = [row for row in rows if row.get("source_available")]
    remaining = [row for row in rows if row.get("group_id") not in done]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                                          for row in remaining), encoding="utf-8")
    print(json.dumps({"input_rows": len(rows), "completed_package_ids": len(done),
                      "remaining_rows": len(remaining), "completed_inputs": report,
                      "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
