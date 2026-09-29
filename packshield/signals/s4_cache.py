"""
Last-known-good cache for live S4 data (registry features + weekly
downloads), keyed by (ecosystem, name).

Added to fix a real reliability bug (see PROJECT.md log): live S4 fetches
have no retry/fallback, so a single transient API failure (npm downloads
API / pypistats.org are both known to rate-limit or briefly error, per
the bulk fetch step earlier) silently produces NaN for that field,
causing the SAME package to score very differently across consecutive
runs with nothing about the package having actually changed -- a real
problem for a tool making BLOCK decisions.

Policy: always attempt a live fetch first (2 quick retries). Only fall
back to the last cached value on genuine failure -- never serve stale
data when live succeeds, since freshness matters when nothing is wrong.
"""

import json
import time
from pathlib import Path

CACHE_DIR = Path.home() / ".packshield"
CACHE_PATH = CACHE_DIR / "s4_last_known_good.json"


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


def get_cached_field(ecosystem: str, name: str, field: str):
    entry = _load().get(f"{ecosystem}:{name}", {})
    return entry.get(field)


def store_field(ecosystem: str, name: str, field: str, value) -> None:
    if value is None:
        return
    from datetime import datetime, timezone
    data = _load()
    key = f"{ecosystem}:{name}"
    entry = data.setdefault(key, {})
    entry[field] = value
    entry[f"{field}_fetched_at"] = datetime.now(timezone.utc).isoformat()
    _save(data)

def fetch_with_fallback(ecosystem: str, name: str, field: str, fetch_fn, retries: int = 2, delay: float = 0.5):
    """fetch_fn: a zero-arg callable returning the live value (or None on failure)."""
    for attempt in range(retries):
        value = fetch_fn()
        if value is not None:
            store_field(ecosystem, name, field, value)
            return value, False  # False = not stale
        if attempt < retries - 1:
            time.sleep(delay)

    cached = get_cached_field(ecosystem, name, field)
    return cached, cached is not None  # True = using stale/cached fallback