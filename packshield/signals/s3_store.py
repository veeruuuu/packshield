"""
S3 signature store: keyed by (ecosystem, name). Keeps the latest full
signature (for diffing the next version against) PLUS a compact history
of past diff results (for the dashboard's version timeline) -- NOT full
duplicate signatures per version, to keep this file small.

Version-awareness bug fix from earlier remains in place: a major-version
mismatch is never diffed against, to avoid the content-type@1.0.5 vs
@2.1.0 cross-contamination bug found and fixed previously.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

STORE_DIR = Path.home() / ".packshield"
STORE_PATH = STORE_DIR / "s3_signatures.json"
MAX_HISTORY_PER_PACKAGE = 20


def _load() -> dict:
    if not STORE_PATH.exists():
        return {}
    try:
        with open(STORE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def make_key(ecosystem: str, name: str) -> str:
    return f"{ecosystem}:{name}"


def _parse_version(version: str) -> tuple:
    parts = version.split("-")[0].split(".")
    nums = []
    for p in parts[:3]:
        try:
            nums.append(int(p))
        except ValueError:
            nums.append(0)
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def get_previous_signature(ecosystem: str, name: str, new_version: str) -> tuple[dict | None, str | None]:
    entry = _load().get(make_key(ecosystem, name))
    if entry is None:
        return None, None

    latest = entry.get("latest")
    if latest is None:
        return None, None

    stored_tuple = _parse_version(latest.get("version", "0.0.0"))
    new_tuple = _parse_version(new_version)

    if stored_tuple[0] != new_tuple[0]:
        return None, f"major version differs from stored baseline ({latest.get('version')} vs {new_version}) -- not compared"

    return latest.get("signature"), None


def store_signature(ecosystem: str, name: str, version: str, signature: dict, diff_score: float | None = None, diff_reasons: list | None = None) -> None:
    data = _load()
    key = make_key(ecosystem, name)
    existing = data.get(key, {"latest": None, "history": []})

    latest = existing.get("latest")
    if latest is not None:
        existing_tuple = _parse_version(latest.get("version", "0.0.0"))
        new_tuple = _parse_version(version)
        if new_tuple < existing_tuple:
            return  # never regress the baseline to an older version

    # Record a compact diff entry for the timeline (not the full signature).
    existing.setdefault("history", []).append({
        "version": version,
        "stored_at": datetime.now(timezone.utc).isoformat(),
        "diff_score": diff_score,
        "diff_reasons": diff_reasons or [],
    })
    existing["history"] = existing["history"][-MAX_HISTORY_PER_PACKAGE:]
    existing["latest"] = {"version": version, "signature": signature}

    data[key] = existing
    _save(data)


def get_version_history(ecosystem: str, name: str) -> list:
    entry = _load().get(make_key(ecosystem, name))
    if entry is None:
        return []
    return entry.get("history", [])