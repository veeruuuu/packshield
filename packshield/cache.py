"""
Verdict cache.

Per PROJECT.md §4/§8: keyed by (ecosystem, name, version, hash) so an
unchanged package is not re-scanned. Cache HIT -> reuse stored verdict,
skip straight to tree-level risk propagation. Cache MISS -> enter the
signal pipeline.

Status: read/write/key mechanism is REAL, stored at ~/.packshield/cache.json
(colocated with the history.jsonl / config.json locations described in §8).
There is nothing meaningful to store yet, since S1-S4 / fusion (which
produce the verdict this cache is meant to hold) are not implemented. This
step only wires up the HIT/MISS check itself against real registry-fetched
hashes -- every entry will show MISS until a later step adds something
real to store.
"""

import json
from pathlib import Path

CACHE_DIR = Path.home() / ".packshield"
CACHE_PATH = CACHE_DIR / "cache.json"


def _load() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def make_key(ecosystem: str, name: str, version: str, package_hash: str) -> str:
    return f"{ecosystem}:{name}@{version}:{package_hash}"


def get_verdict(key: str) -> dict | None:
    return _load().get(key)


def store_verdict(key: str, verdict: dict) -> None:
    data = _load()
    data[key] = verdict
    _save(data)