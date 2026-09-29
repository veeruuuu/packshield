
"""
Bulk, resumable, rate-limited live registry fetch for S4 raw features
(package age, days since last publish, publish velocity, maintainer count).

This addresses dataset gap #2: neither CLAMPD nor Datadog's source data
includes publish_date/maintainer info, and S4 needs it. Running this
against tens of thousands of packages requires real infra (this script),
not a naive loop -- it will genuinely take hours for the pypi side.

Usage:
    python -m packshield.tools.fetch_s4_raw_features INPUT.jsonl OUTPUT.jsonl --workers 5 --delay 0.2

INPUT.jsonl: one of the dataset files (must have "ecosystem" and "name" per row).
OUTPUT.jsonl: cache file. Safe to Ctrl+C and re-run -- already-fetched
(ecosystem, name) pairs are skipped on restart, so progress is never lost.
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packshield.signals.s4_publisher_reputation import _fetch_npm_features, _fetch_pip_features


def load_targets(input_path: str) -> list[tuple[str, str]]:
    seen = set()
    targets = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            key = (row["ecosystem"], row["name"])
            if key not in seen and row["ecosystem"] in ("npm", "pypi"):
                seen.add(key)
                targets.append(key)
    return targets


def load_done(output_path: str) -> set[tuple[str, str]]:
    done = set()
    if not Path(output_path).exists():
        return done
    with open(output_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
                done.add((row["ecosystem"], row["name"]))
            except (json.JSONDecodeError, KeyError):
                continue
    return done


def fetch_one(ecosystem: str, name: str, delay: float) -> dict:
    time.sleep(delay)
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        if ecosystem == "npm":
            features, error_type = _fetch_npm_features(name)
        else:
            features, error_type = _fetch_pip_features(name)
    except Exception as e:  # noqa: BLE001
        return {"ecosystem": ecosystem, "name": name, "features": None, "error": f"unexpected_{type(e).__name__}: {e}", "fetched_at": fetched_at}

    return {"ecosystem": ecosystem, "name": name, "features": features, "error": error_type, "fetched_at": fetched_at}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_path")
    parser.add_argument("output_path")
    parser.add_argument("--workers", type=int, default=5, help="Concurrent fetch threads (default 5, be conservative)")
    parser.add_argument("--delay", type=float, default=0.2, help="Per-request delay in seconds, applied per worker (default 0.2)")
    args = parser.parse_args()

    targets = load_targets(args.input_path)
    done = load_done(args.output_path)
    remaining = [t for t in targets if t not in done]

    print(f"Total unique packages in input: {len(targets)}")
    print(f"Already fetched (resuming):     {len(done)}")
    print(f"Remaining to fetch:             {len(remaining)}")
    if not remaining:
        print("Nothing to do.")
        return

    completed = 0
    errors = 0
    start = time.time()

    with open(args.output_path, "a", encoding="utf-8") as out_f:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(fetch_one, eco, name, args.delay): (eco, name)
                for eco, name in remaining
            }
            for future in as_completed(futures):
                result = future.result()
                out_f.write(json.dumps(result) + "\n")
                out_f.flush()  # ensure it survives a Ctrl+C immediately
                completed += 1
                if result["error"]:
                    errors += 1
                if completed % 100 == 0:
                    elapsed = time.time() - start
                    rate = completed / elapsed if elapsed > 0 else 0
                    remaining_count = len(remaining) - completed
                    eta_min = (remaining_count / rate / 60) if rate > 0 else float("inf")
                    print(f"  {completed}/{len(remaining)} done, {errors} errors, "
                          f"{rate:.1f}/s, ETA ~{eta_min:.0f} min")

    print(f"Done. {completed} fetched this run, {errors} errors, "
          f"total elapsed {(time.time()-start)/60:.1f} min.")


if __name__ == "__main__":
    main()
