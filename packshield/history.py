"""
history.jsonl writer, per PROJECT.md Sec 4/Sec 6: every verdict is written
once to ~/.packshield/history.jsonl. Override records use the same file
with two additional fields (overridden, override_reason) rather than
separate storage, per Sec 6's explicit instruction.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

HISTORY_PATH = Path.home() / ".packshield" / "history.jsonl"


def append_history(entry: dict) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = dict(entry)
    entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    with open(HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")