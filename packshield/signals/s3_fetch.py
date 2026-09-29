"""
Safe source download for S3: fetches a package's own tarball directly via
its registry-provided URL and extracts it -- NEVER invokes `npm install`,
`pip install`, or any package manager command on the target package itself.
This is the entire point: S3 must be able to inspect a package's code
BEFORE any install-time script (preinstall/postinstall/setup.py) has a
chance to run. Using the real install command here would defeat the
purpose of gating on S1/S3/S4 before S2/execution.

npm: tarball is a plain .tar.gz -- decompression only, no code execution.
pip: source is either an sdist (.tar.gz, decompression only) or a wheel
(.whl, a plain zip -- extraction only). Neither format's extraction step
executes any code; a wheel's own install-time hooks (there are none by
spec) and an sdist's setup.py are never invoked here.
"""

import json
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


class FetchError(Exception):
    pass


def _fetch_json(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError) as e:
        raise FetchError(str(e))


def fetch_npm_source(name: str, version: str, dest_dir: Path) -> Path:
    safe_name = urllib.parse.quote(name, safe="@/")
    data = _fetch_json(f"https://registry.npmjs.org/{safe_name}/{version}")
    tarball_url = data.get("dist", {}).get("tarball")
    if not tarball_url:
        raise FetchError(f"no tarball URL found for {name}@{version}")

    tar_path = dest_dir / "package.tgz"
    try:
        urllib.request.urlretrieve(tarball_url, tar_path)
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(dest_dir)
    except Exception as e:
        raise FetchError(f"download/extract failed: {e}")

    extracted = dest_dir / "package"
    if not extracted.exists():
        raise FetchError("extracted tarball did not contain expected 'package/' directory")
    return extracted


def fetch_pip_source(name: str, version: str, dest_dir: Path) -> Path:
    data = _fetch_json(f"https://pypi.org/pypi/{urllib.parse.quote(name)}/{version}/json")
    urls = data.get("urls", [])
    if not urls:
        raise FetchError(f"no release files found for {name}=={version}")

    # Prefer sdist (plain tarball) over wheel when available -- either is
    # safe to extract, sdist is slightly more likely to reflect the full
    # source tree including setup.py for our hook-detection logic.
    chosen = next((u for u in urls if u.get("packagetype") == "sdist"), urls[0])
    file_url = chosen["url"]
    filename = chosen["filename"]

    file_path = dest_dir / filename
    try:
        urllib.request.urlretrieve(file_url, file_path)
    except Exception as e:
        raise FetchError(f"download failed: {e}")

    try:
        if filename.endswith(".whl") or filename.endswith(".zip"):
            with zipfile.ZipFile(file_path) as z:
                z.extractall(dest_dir / "extracted")
        else:
            with tarfile.open(file_path, "r:*") as tar:
                tar.extractall(dest_dir / "extracted")
    except Exception as e:
        raise FetchError(f"extract failed: {e}")

    extracted_root = dest_dir / "extracted"
    # sdist tarballs extract into a "name-version/" subfolder; find it.
    subdirs = [p for p in extracted_root.iterdir() if p.is_dir()]
    if subdirs:
        return subdirs[0]
    return extracted_root