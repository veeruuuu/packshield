"""
Dependency resolution (dry-run only) for npm and pip.

Per PROJECT.md Sec 4: this step resolves the full transitive dependency
tree for a package WITHOUT downloading or executing any package code --
registry metadata lookups only. The result feeds the cache check and the
signal pipeline.

Each resolved entry includes:
- a content hash (npm: registry dist.integrity/dist.shasum; pip: sha256
  from the install report), required for the cache key per Sec 8.
- a "parent" field for real dependency-graph edges (used by the
  dashboard's interactive graph): npm's dry-run JSON includes each
  package's install path, which reveals real parent-child nesting. pip's
  --report format has NO equivalent nesting information, so pip's
  "parent" is always None -- stated honestly rather than faked.

PROGRESS: resolve_tree() accepts an optional `progress` callback used by
the live dashboard view. It is purely observational -- exceptions inside
it are swallowed and can never break resolution.

PERFORMANCE: npm integrity hashes are fetched HASH_FETCH_WORKERS at a
time instead of one by one. Same data, same cache keys.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

HASH_FETCH_WORKERS = 8


class ResolutionError(Exception):
    pass


def _safe_progress(progress, *args, **kwargs) -> None:
    if progress is None:
        return
    try:
        progress(*args, **kwargs)
    except Exception:
        pass  # observational only


def _fetch_npm_hash(name: str, version: str) -> str:
    """Fetch the integrity/shasum hash for one npm package@version."""
    safe_name = urllib.parse.quote(name, safe="@/")
    url = f"https://registry.npmjs.org/{safe_name}/{version}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        dist = data.get("dist", {})
        return dist.get("integrity") or dist.get("shasum") or "unknown"
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
        return "unknown"


def _extract_parent_from_path(path: str, package_name: str) -> str | None:
    """npm's dry-run JSON includes each package's install path, e.g.
    '...\\node_modules\\type-is\\node_modules\\content-type' -- the
    second-to-last node_modules segment (if more than one exists) is this
    package's real parent. Returns None for a top-level (hoisted) package."""
    if not path:
        return None
    parts = path.replace("/", "\\").split("\\node_modules\\")
    if len(parts) <= 2:
        return None
    parent_segment = parts[-2]
    return parent_segment.split("\\")[0] if parent_segment else None


def resolve_npm(package: str, progress=None) -> list[dict]:
    """Dry-run resolve an npm package's full transitive tree, with hashes and real parent edges."""
    npm_path = shutil.which("npm")
    if npm_path is None:
        raise ResolutionError("npm binary not found on PATH")

    with tempfile.TemporaryDirectory(prefix="packshield-npm-") as tmpdir:
        # Give npm its own throwaway package.json so it treats this temp
        # dir as an isolated project root instead of resolving against a
        # real, unrelated project higher up the filesystem.
        package_json_path = os.path.join(tmpdir, "package.json")
        with open(package_json_path, "w", encoding="utf-8") as f:
            json.dump({"name": "packshield-dry-run", "version": "0.0.0", "private": True}, f)

        _safe_progress(progress, f"npm dry-run started: resolving the full tree for {package} (no code is executed)")
        try:
            result = subprocess.run(
                [npm_path, "install", package, "--dry-run", "--json", "--no-audit", "--no-fund"],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            raise ResolutionError(f"npm dry-run resolution timed out for {package}")

        stdout = result.stdout.strip()
        if not stdout:
            raise ResolutionError(
                f"npm dry-run produced no output for {package}. stderr: {result.stderr.strip()}"
            )

        # Some npm versions print extra non-JSON lines before the JSON blob.
        json_start = stdout.find("{")
        if json_start == -1:
            raise ResolutionError(
                f"npm dry-run output for {package} contained no JSON. Raw output: {stdout[:300]}"
            )
        try:
            data = json.loads(stdout[json_start:])
        except json.JSONDecodeError:
            raise ResolutionError(f"Could not parse npm --json output for {package}")

        entries = []  # (name, version, parent)
        for entry in data.get("add", []):
            name, version = entry.get("name"), entry.get("version")
            if name and version:
                entries.append((name, version, _extract_parent_from_path(entry.get("path", ""), name)))
        for entry in data.get("change", []):
            to = entry.get("to", {})
            name, version = to.get("name"), to.get("version")
            if name and version:
                entries.append((name, version, _extract_parent_from_path(to.get("path", ""), name)))

        if not entries:
            return [{"name": package, "version": "unknown", "hash": "unknown", "parent": None}]

        _safe_progress(progress, f"npm dry-run finished: {len(entries)} packages in the tree; fetching integrity hashes...",
                       completed=0, total=len(entries))

        hashes = ["unknown"] * len(entries)
        with ThreadPoolExecutor(max_workers=HASH_FETCH_WORKERS) as executor:
            future_to_idx = {
                executor.submit(_fetch_npm_hash, name, version): i
                for i, (name, version, _parent) in enumerate(entries)
            }
            done = 0
            for future in as_completed(future_to_idx):
                try:
                    hashes[future_to_idx[future]] = future.result()
                except Exception:
                    hashes[future_to_idx[future]] = "unknown"
                done += 1
                if done % 10 == 0 or done == len(entries):
                    _safe_progress(progress, f"fetched integrity hashes {done}/{len(entries)}",
                                   completed=done, total=len(entries))

        return [
            {"name": name, "version": version, "hash": hashes[i], "parent": parent}
            for i, (name, version, parent) in enumerate(entries)
        ]


def _extract_pip_hash(item: dict) -> str:
    """Best-effort extraction of a sha256 hash from a pip install-report item."""
    download_info = item.get("download_info", {})
    archive_info = download_info.get("archive_info", {})
    hashes = archive_info.get("hashes")
    if isinstance(hashes, dict) and hashes.get("sha256"):
        return f"sha256:{hashes['sha256']}"
    single_hash = archive_info.get("hash")
    if single_hash:
        return single_hash
    return "unknown"


def resolve_pip(package: str, progress=None) -> list[dict]:
    """Dry-run resolve a pip package's full transitive tree, with hashes.

    Uses `pip install --dry-run --report -` (pip >= 22.2), which resolves
    without installing or executing anything. pip's report format has no
    parent/edge information -- "parent" is always None here.
    """
    _safe_progress(progress, f"pip dry-run started: resolving the full tree for {package} (nothing is installed or executed)")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", package, "--dry-run", "--report", "-"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        raise ResolutionError(f"pip dry-run resolution timed out for {package}")

    if not result.stdout.strip():
        raise ResolutionError(
            f"pip dry-run produced no output for {package}. stderr: {result.stderr.strip()}"
        )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise ResolutionError(f"Could not parse pip --report output for {package}")

    tree = []
    for item in data.get("install", []):
        meta = item.get("metadata", {})
        name = meta.get("name")
        version = meta.get("version")
        if name and version:
            tree.append({
                "name": name,
                "version": version,
                "hash": _extract_pip_hash(item),
                "parent": None,
            })

    if not tree:
        tree = [{"name": package, "version": "unknown", "hash": "unknown", "parent": None}]
    _safe_progress(progress, f"pip dry-run finished: {len(tree)} packages in the tree", completed=len(tree), total=len(tree))
    return tree


def resolve_tree(package: str, pm: str, progress=None) -> list[dict]:
    if pm == "npm":
        return resolve_npm(package, progress)
    elif pm == "pip":
        return resolve_pip(package, progress)
    else:
        raise ValueError(f"Unknown package manager: {pm}")