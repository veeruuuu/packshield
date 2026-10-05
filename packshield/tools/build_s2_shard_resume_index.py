"""Build a JSONL resume index from unfinished S2 extraction shards."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shard", action="append", nargs=2, required=True,
                        metavar=("NAME", "COMPLETED_NPM"),
                        help="Shard basename and its last completed npm package count")
    args = parser.parse_args()

    selected: list[dict] = []
    reports = []
    for name, completed_text in args.shard:
        completed = int(completed_text)
        rows = [json.loads(line) for line in
                (args.shard_dir / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()]
        npm_rows = [row for row in rows if row["ecosystem"] == "npm"]
        pypi_rows = [row for row in rows if row["ecosystem"] == "pypi"]
        if completed < 0 or completed > len(npm_rows):
            parser.error(f"invalid completed count {completed} for {name} ({len(npm_rows)} npm rows)")
        selected.extend(npm_rows[completed:])
        selected.extend(pypi_rows)
        reports.append({"shard": name, "npm_completed_skipped": completed,
                        "npm_remaining": len(npm_rows) - completed,
                        "pypi_remaining": len(pypi_rows)})

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                                          for row in selected), encoding="utf-8")
    print(json.dumps({"remaining_rows": len(selected), "shards": reports,
                      "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
