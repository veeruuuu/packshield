"""Recover complete JSONL records from an interrupted S2 gzip stream."""

from __future__ import annotations

import argparse
import gzip
import json
import zlib
from pathlib import Path


def salvage(source: Path, destination: Path) -> dict:
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    pending = bytearray()
    counts: dict[str, int] = {}
    packages: set[str] = set()
    records = 0
    destination.parent.mkdir(parents=True, exist_ok=True)

    with source.open("rb") as input_stream, gzip.open(
            destination, "wt", encoding="utf-8", newline="\n") as output_stream:
        while chunk := input_stream.read(8192):
            try:
                pending.extend(decoder.decompress(chunk))
            except zlib.error:
                break
            while True:
                newline = pending.find(b"\n")
                if newline < 0:
                    break
                raw = bytes(pending[:newline])
                del pending[:newline + 1]
                try:
                    record = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                output_stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                records += 1
                status = record.get("status", "missing_status")
                counts[status] = counts.get(status, 0) + 1
                if record.get("group_id"):
                    packages.add(record["group_id"])

    return {"records": records, "packages": len(packages), "statuses": counts,
            "source_gzip_complete": decoder.eof,
            "destination": str(destination)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(salvage(args.source, args.destination), indent=2))


if __name__ == "__main__":
    main()
