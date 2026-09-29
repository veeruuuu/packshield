"""
Best-effort live scan status, for the dashboard's Live view. Purely
observational: every write is wrapped so a failure here can NEVER affect
the real enforcement pipeline.

DESIGN:
- The full scan state lives IN MEMORY in the CLI process. This module
  never reads the status file back (the dashboard polls it concurrently,
  and read-modify-write on a shared file raced).
- Writes are atomic (temp file + os.replace); on Windows os.replace can
  briefly fail while a reader holds the file open, so it retries and
  falls back to an in-place write as a last resort.
- Every log line carries an elapsed-time stamp so slow phases are visible.

HONEST LIMITATION: the dashboard polls (about every 500ms), not pushes.
If the CLI process crashes mid-scan, the file can be left showing
"active": true; the dashboard shows how long ago it was last written so
a stuck or dead scan is visible.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

LIVE_STATUS_PATH = Path.home() / ".packshield" / "live_status.json"
MAX_LOG_LINES = 200

_state: dict = {}
_started_at: float | None = None


def _write(data: dict) -> None:
    try:
        LIVE_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = LIVE_STATUS_PATH.with_name(LIVE_STATUS_PATH.name + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        for _ in range(5):
            try:
                os.replace(tmp_path, LIVE_STATUS_PATH)
                return
            except PermissionError:
                time.sleep(0.01)
        with open(LIVE_STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass  # never let a status-write failure affect the real pipeline


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _line(message: str) -> str:
    elapsed = time.time() - _started_at if _started_at else 0.0
    return f"[+{elapsed:.1f}s] {message}"


def _ensure_state() -> None:
    global _state, _started_at
    if not _state:
        _started_at = _started_at or time.time()
        _state = {"active": True, "package": None, "pm": None, "log": []}


def start_scan(package: str, pm: str, total_packages: int | None = None) -> None:
    global _state, _started_at
    _started_at = time.time()
    _state = {
        "active": True,
        "package": package,
        "pm": pm,
        "stage": "resolving",
        "total_packages": total_packages,
        "completed_packages": 0,
        "current_package": None,
        "log": [],
        "updated_at": _stamp(),
    }
    _state["log"].append(_line(f"Resolving dependency tree for {package}..."))
    _write(_state)


def log_event(message: str, stage: str | None = None, completed: int | None = None,
              total: int | None = None, current: str | None = None) -> None:
    """General-purpose progress line. Any field left as None is unchanged."""
    _ensure_state()
    if stage is not None:
        _state["stage"] = stage
    if completed is not None:
        _state["completed_packages"] = completed
    if total is not None:
        _state["total_packages"] = total
    if current is not None:
        _state["current_package"] = current
    _state["active"] = True
    _state["updated_at"] = _stamp()
    _state.setdefault("log", []).append(_line(message))
    _state["log"] = _state["log"][-MAX_LOG_LINES:]
    _write(_state)


def update_progress(current_package: str, completed: int, total: int, stage: str = "stage1") -> None:
    log_event(f"[{stage}] scored {current_package}", stage=stage, completed=completed,
              total=total, current=current_package)


def finish_scan(verdict: str, final_score: float, started_at: float | None = None) -> None:
    global _state
    _ensure_state()
    begun = started_at if started_at is not None else (_started_at or time.time())
    _state.update({
        "active": False,
        "stage": "done",
        "verdict": verdict,
        "final_score": final_score,
        "elapsed_seconds": round(time.time() - begun, 1),
        "updated_at": _stamp(),
    })
    _state.setdefault("log", []).append(_line(f"Final verdict: {verdict} ({final_score})"))
    _state["log"] = _state["log"][-MAX_LOG_LINES:]
    _write(_state)