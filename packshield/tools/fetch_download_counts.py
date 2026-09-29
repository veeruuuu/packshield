
"""
Targeted fetch: weekly download counts, ONLY for packages that already
have resolved S4 features (s4_registry_status == "resolved"). Added to
fix a real false-positive class: young/single-maintainer/low-version
foundational packages (e.g. dunder-proto, math-intrinsics -- the
ljharb/es-shims family) being indistinguishable from genuinely new,
unproven, possibly-malicious packages on the features that existed
before this. See PROJECT.md log for this step.

Usage:
    python -m packshield.tools.fetch_download_counts INPUT.jsonl OUTPUT.jsonl --workers 5 --delay 0.2
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packshield.signals.s4_publisher_reputation import _fetch_npm_downloads, _fetch_pip_downloads


def load_targets(input_path: str) -> list[tuple[str, str]]:
    seen = set()
    targets = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            # Only filter by s4_registry_status if the field is present --
            # a pre-filtered candidates file (like a retry list) won't have
            # it and should be used as-is.
            if "s4_registry_status" in row and row["s4_registry_status"] != "resolved":
                continue
            key = (row["ecosystem"], row["name"])
            if key not in seen:
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
    max_retries = 4
    backoff = 2.0
    for attempt in range(max_retries):
        try:
            if ecosystem == "npm":
                downloads, error_type = _fetch_npm_downloads(name)
            else:
                downloads, error_type = _fetch_pip_downloads(name)
        except Exception as e:  # noqa: BLE001
            return {"ecosystem": ecosystem, "name": name, "weekly_downloads": None, "error": f"unexpected_{type(e).__name__}: {e}", "fetched_at": fetched_at}

        if error_type == "http_error_429" and attempt < max_retries - 1:
            time.sleep(backoff)
            backoff *= 2  # exponential backoff: 2s, 4s, 8s
            continue
        return {"ecosystem": ecosystem, "name": name, "weekly_downloads": downloads, "error": error_type, "fetched_at": fetched_at}

    return {"ecosystem": ecosystem, "name": name, "weekly_downloads": None, "error": "http_error_429_after_retries", "fetched_at": fetched_at}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_path")
    parser.add_argument("output_path")
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--delay", type=float, default=0.2)
    args = parser.parse_args()

    targets = load_targets(args.input_path)
    done = load_done(args.output_path)
    remaining = [t for t in targets if t not in done]

    print(f"Total resolved-status unique packages: {len(targets)}")
    print(f"Already fetched (resuming): {len(done)}")
    print(f"Remaining: {len(remaining)}")
    if not remaining:
        print("Nothing to do.")
        return

    completed = 0
    start = time.time()
    with open(args.output_path, "a", encoding="utf-8") as out_f:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(fetch_one, eco, name, args.delay): (eco, name) for eco, name in remaining}
            for future in as_completed(futures):
                result = future.result()
                out_f.write(json.dumps(result) + "\n")
                out_f.flush()
                completed += 1
                if completed % 100 == 0:
                    elapsed = time.time() - start
                    rate = completed / elapsed if elapsed > 0 else 0
                    eta_min = ((len(remaining) - completed) / rate / 60) if rate > 0 else float("inf")
                    print(f"  {completed}/{len(remaining)} done, {rate:.1f}/s, ETA ~{eta_min:.0f} min")

    print(f"Done. {completed} fetched, elapsed {(time.time()-start)/60:.1f} min.")


if __name__ == "__main__":
    main()

