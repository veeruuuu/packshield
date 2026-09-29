"""
Config file read/write: ~/.packshield/config.json.

Per PROJECT.md Sec 6/Sec 7: stores "shieldmax_default" (the persistent
form of ShieldMax mode, normally toggled via the dashboard's "Paranoid
Mode" switch -- since the dashboard doesn't exist yet, packshield config
set-shieldmax is the CLI equivalent). OFF by default.

Per Sec 11, the schema beyond shieldmax_default is explicitly marked
UNKNOWN/future work -- this module is written generically (get/set by
key) so additional settings can be added later without redesigning the
read/write mechanism, but does NOT invent any settings beyond the one
actually specified.
"""

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".packshield"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULTS = {
    "shieldmax_default": False,
}


def get_config() -> dict:
    if not CONFIG_PATH.exists():
        return dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    merged.update(data)
    return merged


def set_config_value(key: str, value) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = get_config()
    data[key] = value
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_shieldmax_default() -> bool:
    return bool(get_config().get("shieldmax_default", False))


def set_shieldmax_default(value: bool) -> None:
    set_config_value("shieldmax_default", bool(value))