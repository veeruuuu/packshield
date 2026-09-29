"""
packshield ui -- read-only local dashboard.

HARD RULE (Sec 4): this server only reads history.jsonl/config.json and
can toggle Paranoid Mode (an explicitly sanctioned config write, per
Sec 6). It NEVER gates, delays, or influences any install -- the CLI/
PATH-shim enforces entirely on its own, synchronously, with or without
this dashboard ever having been opened.

HONEST LIMITATION: the original spec calls for "SHAP detail." That
requires a real trained tree-based meta-classifier to compute TreeSHAP
values from. Fusion is currently MAX-based (a deliberate, logged
decision -- see Sec 7), not a trained model, so there is no SHAP to
show. The dashboard shows the real per-signal score breakdown instead,
labeled as such.
"""

import json
import time
from collections import Counter
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from packshield.config import get_config, set_shieldmax_default
from packshield.history import HISTORY_PATH
from packshield.live_status import LIVE_STATUS_PATH
from packshield.shim.setup import SHIM_CONFIG_PATH
from packshield.signals.s3_store import get_version_history

app = FastAPI(title="PackShield Dashboard (read-only)")

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.middleware("http")
async def revalidate_static(request, call_next):
    """Make the browser re-check app.js/style.css on every load, so a
    saved frontend edit is never hidden behind a stale cached copy."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static"):
        response.headers["Cache-Control"] = "no-cache"
    return response


def _read_history() -> list:
    if not HISTORY_PATH.exists():
        return []
    entries = []
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


@app.get("/", response_class=HTMLResponse)
def index():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return index_path.read_text(encoding="utf-8")
    return "<h1>PackShield Dashboard</h1><p>static/index.html not found.</p>"


@app.get("/api/history")
def get_history():
    entries = _read_history()
    entries.reverse()  # most recent first
    return {"entries": entries}


@app.get("/api/config")
def api_get_config():
    return get_config()


@app.post("/api/config/shieldmax/{state}")
def api_set_shieldmax(state: str):
    """state: 'on' or 'off'. The ONLY write this dashboard performs --
    toggling the persistent ShieldMax default, explicitly sanctioned as a
    dashboard action per Sec 6."""
    if state not in ("on", "off"):
        return {"error": "state must be 'on' or 'off'"}
    set_shieldmax_default(state == "on")
    return {"shieldmax_default": state == "on"}


@app.get("/api/shim_status")
def api_shim_status():
    if not SHIM_CONFIG_PATH.exists():
        return {"armed": False}
    try:
        config = json.loads(SHIM_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"armed": False}
    return {"armed": True, "real_npm_path": config.get("real_npm_path"), "real_pip_path": config.get("real_pip_path")}


@app.get("/api/live_status")
def api_live_status():
    headers = {"Cache-Control": "no-store"}
    if not LIVE_STATUS_PATH.exists():
        return JSONResponse({"active": False}, headers=headers)
    last_err = None
    for _ in range(3):
        try:
            with open(LIVE_STATUS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["file_age_seconds"] = round(time.time() - LIVE_STATUS_PATH.stat().st_mtime, 1)
            return JSONResponse(data, headers=headers)
        except (json.JSONDecodeError, OSError) as e:
            last_err = e
            time.sleep(0.02)
    return JSONResponse({"_read_error": str(last_err)}, headers=headers)


@app.get("/api/stats")
def api_stats():
    entries = _read_history()
    if not entries:
        return {"total_scans": 0}

    verdict_counts = Counter(e["verdict"] for e in entries)
    worst_signal_counts = Counter(e.get("worst_signal", "none") for e in entries)
    # rsplit so scoped packages like "@types/node@1.0.0" keep their name
    worst_node_counts = Counter(e["worst_node"].rsplit("@", 1)[0] for e in entries if e.get("worst_node"))

    # Honest signal->attack-type mapping, per PROJECT.md Sec 2's own table
    # (S1->T1, S2->T2, S3->T3, S4->T4). "Likely pattern," not a certainty --
    # no scan is ever actually classified by attack type at run time.
    signal_to_attack_type = {"s1": "T1", "s2_fake": "T2", "s3": "T3", "stage1": "T1/T4 (mixed S1+S4)"}
    attack_type_counts = Counter()
    for signal, count in worst_signal_counts.items():
        attack_type_counts[signal_to_attack_type.get(signal, "UNKNOWN")] += count

    return {
        "total_scans": len(entries),
        "verdict_counts": dict(verdict_counts),
        "worst_signal_counts": dict(worst_signal_counts),
        "likely_attack_type_counts": dict(attack_type_counts),
        "top_flagged_packages": worst_node_counts.most_common(5),
    }


@app.get("/api/package/{ecosystem}/{name:path}")
def api_package_forensics(ecosystem: str, name: str):
    history = get_version_history(ecosystem, name)
    mentions = []
    for entry in _read_history():
        for node in entry.get("node_scores", []):
            if node["name"] == name:
                mentions.append({
                    "scan_package": entry["package"],
                    "scan_verdict": entry["verdict"],
                    "node_scores": node,
                    "timestamp": entry.get("timestamp"),
                })
    return {"ecosystem": ecosystem, "name": name, "version_history": history, "scan_mentions": mentions}
@app.get("/api/threats")
def api_threats():
    """Per-attack-type breakdown, built the same honest way as /api/stats'
    likely_attack_type_counts: inferred from which SIGNAL produced each
    scan's worst score, per Sec 2's own S1->T1, S2->T2, S3->T3, S4->T4
    mapping. This is a pattern inference, not a real per-scan classifier
    -- no scan is ever actually labeled by attack type at run time."""
    entries = _read_history()
    signal_to_attack_type = {"s1": "T1", "s2_fake": "T2", "s3": "T3", "stage1": "T1/T4 (mixed S1+S4)"}

    buckets = {"T1": [], "T2": [], "T3": [], "T1/T4 (mixed S1+S4)": [], "UNKNOWN": []}
    for entry in entries:
        signal = entry.get("worst_signal", "none")
        attack_type = signal_to_attack_type.get(signal, "UNKNOWN")
        buckets[attack_type].append({
            "package": entry["package"],
            "pm": entry["pm"],
            "verdict": entry["verdict"],
            "final_score": entry["final_score"],
            "worst_node": entry.get("worst_node"),
            "timestamp": entry.get("timestamp"),
        })

    return {
        "definitions": {
            "T1": "Typosquatting / homoglyph confusion — caught by S1 (name similarity)",
            "T2": "Malicious install-time behavior — caught by S2 (currently a FAKE STUB, not real analysis)",
            "T3": "Update-time poisoning of a trusted package — caught by S3 (real AST/manifest diffing)",
            "T4": "Maintainer/publisher-level risk — caught by S4, currently folded into the Stage-1 combined score rather than scored standalone",
            "T5": "Dependency confusion — explicitly out of scope, not implemented at all (see PROJECT.md Sec 2)",
        },
        "buckets": buckets,
    }