"""
S4 — Publisher/Maintainer Reputation.

Per PROJECT.md §5:
- Engineered features: account age, time since last publish, publishing
  velocity across packages, 2FA-enabled status, co-maintainer churn
- Fed into a gradient-boosted tree (originally XGBoost/LightGBM in §7;
  under discussion to move to HistGradientBoostingClassifier -- not yet
  logged as settled)
- Cost tier: cheap, always runs (Stage 1)

Status of each Sec 5 feature in THIS implementation:
- "Account age"        -> NOT AVAILABLE via public registry API. Using
                           PACKAGE age (first release timestamp) as a
                           labeled proxy instead. Honest substitution,
                           not the literal feature named in Sec 5.
- "Time since last publish" -> REAL, from registry data.
- "Publishing velocity"     -> REAL (versions released in a trailing window).
- "2FA-enabled status"      -> NOT IMPLEMENTED. PROJECT.md Sec 5/Sec 11
                           explicitly says do not implement until confirmed
                           against current npm/PyPI API docs.
- "Co-maintainer churn"     -> NOT IMPLEMENTED. Requires a historical
                           snapshot store, not built yet.

No trained model exists yet (no labeled training data was available when
this was first written). This file currently only exposes the RAW FEATURE
FETCH functions (_fetch_npm_features / _fetch_pip_features) -- these are
what the bulk dataset-building tool (packshield/tools/fetch_s4_raw_features.py)
imports and calls. The score_publisher()/heuristic function is intentionally
NOT included here anymore -- per project decision, no permanent heuristic;
scoring will come from a real trained model once the dataset work
(gap #2) is complete.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


def _fetch_json(url: str) -> tuple[dict | None, str | None]:
    """Returns (data, error_type). error_type is None on success,
    "not_found" for a real 404, or the exception class name otherwise."""
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, "not_found"
        return None, f"http_error_{e.code}"
    except urllib.error.URLError as e:
        return None, f"url_error_{e.reason}"
    except (json.JSONDecodeError, ValueError):
        return None, "bad_json"
    except TimeoutError:
        return None, "timeout"


def _fetch_npm_features(name: str) -> tuple[dict | None, str | None]:
    safe_name = urllib.parse.quote(name, safe="@/")
    data, error_type = _fetch_json(f"https://registry.npmjs.org/{safe_name}")
    if data is None:
        return None, error_type

    time_obj = data.get("time", {})
    version_times = {
        k: v for k, v in time_obj.items()
        if k not in ("created", "modified", "unpublished") and isinstance(v, str)
    }
    if not version_times:
        return None, "no_version_times"

    parsed_times = []
    for iso_str in version_times.values():
        try:
            parsed_times.append(datetime.fromisoformat(iso_str.replace("Z", "+00:00")))
        except ValueError:
            continue
    if not parsed_times:
        return None, "unparseable_times"

    now = datetime.now(timezone.utc)
    first_release = min(parsed_times)
    last_release = max(parsed_times)
    ninety_days_ago = now.timestamp() - (90 * 86400)
    versions_last_90d = sum(1 for t in parsed_times if t.timestamp() >= ninety_days_ago)

    latest_version_key = data.get("dist-tags", {}).get("latest")
    maintainers = []
    if latest_version_key and latest_version_key in data.get("versions", {}):
        maintainers = data["versions"][latest_version_key].get("maintainers", [])
    if not maintainers:
        maintainers = data.get("maintainers", [])

    return {
        "package_age_days": (now - first_release).days,
        "days_since_last_publish": (now - last_release).days,
        "total_versions": len(parsed_times),
        "versions_last_90_days": versions_last_90d,
        "maintainer_count": len(maintainers),
    }, None


def _fetch_pip_features(name: str) -> tuple[dict | None, str | None]:
    data, error_type = _fetch_json(f"https://pypi.org/pypi/{urllib.parse.quote(name)}/json")
    if data is None:
        return None, error_type

    releases = data.get("releases", {})
    parsed_times = []
    for files in releases.values():
        for f in files:
            iso_str = f.get("upload_time_iso_8601")
            if iso_str:
                try:
                    parsed_times.append(datetime.fromisoformat(iso_str.replace("Z", "+00:00")))
                except ValueError:
                    continue
    if not parsed_times:
        return None, "no_release_times"

    now = datetime.now(timezone.utc)
    first_release = min(parsed_times)
    last_release = max(parsed_times)
    ninety_days_ago = now.timestamp() - (90 * 86400)
    versions_last_90d = sum(1 for t in parsed_times if t.timestamp() >= ninety_days_ago)

    info = data.get("info", {})
    has_named_maintainer = bool(info.get("maintainer") or info.get("author"))

    return {
        "package_age_days": (now - first_release).days,
        "days_since_last_publish": (now - last_release).days,
        "total_versions": len(parsed_times),
        "versions_last_90_days": versions_last_90d,
        "maintainer_count": 1 if has_named_maintainer else 0,
    }, None



def _fetch_npm_downloads(name: str) -> tuple[int | None, str | None]:
    """Weekly download count from npm's separate downloads API (distinct
    endpoint from the registry metadata API). Added specifically to fix a
    false-positive class found in real usage: young, single-maintainer,
    low-version-count packages (e.g. the ljharb/es-shims family --
    dunder-proto, math-intrinsics, get-proto, etc.) that are foundational
    and massively depended-on despite looking "new" on every other S4
    feature. Download count is the one signal that can tell these apart
    from a genuinely new, unproven, possibly-malicious package."""
    safe_name = urllib.parse.quote(name, safe="@/")
    data, error_type = _fetch_json(f"https://api.npmjs.org/downloads/point/last-week/{safe_name}")
    if data is None:
        return None, error_type
    downloads = data.get("downloads")
    if downloads is None:
        return None, "no_downloads_field"
    return downloads, None


def _fetch_pip_downloads(name: str) -> tuple[int | None, str | None]:
    """Weekly download count via pypistats.org's public API."""
    safe_name = urllib.parse.quote(name)
    data, error_type = _fetch_json(f"https://pypistats.org/api/packages/{safe_name}/recent")
    if data is None:
        return None, error_type
    downloads = data.get("data", {}).get("last_week")
    if downloads is None:
        return None, "no_last_week_field"
    return downloads, None