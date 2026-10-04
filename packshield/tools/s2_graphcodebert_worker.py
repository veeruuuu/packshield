"""Process one S2 source file per request in a killable parser worker.

The parent sends bounded, base64-encoded bytes over stdin. This worker only
parses source and emits GraphCodeBERT features; it never imports or executes a
package file.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys

from packshield.signals.s2_graphcodebert_features import build_source_feature


def _load_tooling(model_name: str):
    try:
        from tree_sitter_languages import get_parser
        from transformers import AutoTokenizer
    except ImportError as exc:
        raise RuntimeError(
            "S2 feature dependencies missing; install packshield/s2-requirements.txt"
        ) from exc
    parsers = {"python": get_parser("python"), "javascript": get_parser("javascript")}
    tokenizer = AutoTokenizer.from_pretrained(
        model_name, use_fast=False, local_files_only=True
    )
    return parsers, tokenizer


def _write_message(message: dict) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--code-length", type=int, required=True)
    parser.add_argument("--data-flow-length", type=int, required=True)
    args = parser.parse_args()

    try:
        parser_by_language, tokenizer = _load_tooling(args.model_name)
    except BaseException as exc:
        _write_message({"kind": "startup_error", "error": f"{type(exc).__name__}: {exc}"})
        return
    _write_message({"kind": "ready"})

    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            job = json.loads(line)
            source = base64.b64decode(job["source_b64"], validate=True)
            feature = build_source_feature(
                job["row"], job["relative_file"], source,
                parser_by_language, tokenizer,
                args.code_length, args.data_flow_length,
            )
            _write_message({"kind": "result", "feature": feature})
        except BaseException as exc:
            _write_message({
                "kind": "worker_error",
                "error": f"{type(exc).__name__}: {exc}",
            })


if __name__ == "__main__":
    main()
