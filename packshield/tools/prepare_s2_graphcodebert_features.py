"""Extract bounded, static GraphCodeBERT features for MalwareBench S2."""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import queue
import subprocess
import sys
import tarfile
import threading
from collections import Counter
from pathlib import Path

from packshield.signals.s2_git_source import GitSourceError, iter_git_package_source_files


class FeatureWorkerError(RuntimeError):
    pass


class FeatureWorker:
    """Long-lived parser process with parent-enforced per-file hard timeouts."""

    def __init__(self, model_name: str, code_length: int, data_flow_length: int,
                 startup_timeout: float):
        self.model_name = model_name
        self.code_length = code_length
        self.data_flow_length = data_flow_length
        self.startup_timeout = startup_timeout
        self.process: subprocess.Popen | None = None
        self.responses: queue.Queue = queue.Queue()
        self._start()

    def _start(self) -> None:
        responses: queue.Queue = queue.Queue()
        command = [
            sys.executable, "-m", "packshield.tools.s2_graphcodebert_worker",
            "--model-name", self.model_name,
            "--code-length", str(self.code_length),
            "--data-flow-length", str(self.data_flow_length),
        ]
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1,
        )

        def read_messages() -> None:
            assert process.stdout is not None
            try:
                for line in process.stdout:
                    try:
                        responses.put(json.loads(line))
                    except json.JSONDecodeError:
                        responses.put({"kind": "protocol_error", "error": "invalid worker JSON"})
            finally:
                responses.put(None)

        threading.Thread(target=read_messages, name="s2-feature-worker-reader", daemon=True).start()
        self.process = process
        self.responses = responses
        try:
            message = responses.get(timeout=self.startup_timeout)
        except queue.Empty as exc:
            self._stop(kill=True)
            raise FeatureWorkerError("S2 parser worker startup timed out") from exc
        if message is None:
            code = process.poll()
            self._stop(kill=True)
            raise FeatureWorkerError(f"S2 parser worker exited during startup (code {code})")
        if message.get("kind") != "ready":
            error = message.get("error", "unexpected worker startup response")
            self._stop(kill=True)
            raise FeatureWorkerError(f"S2 parser worker could not start: {error}")

    def _stop(self, kill: bool = False) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        if process.poll() is None:
            if not kill and process.stdin is not None:
                try:
                    process.stdin.close()
                    process.wait(timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    kill = True
            if kill and process.poll() is None:
                process.kill()
                process.wait()
        for pipe in (process.stdin, process.stdout):
            if pipe is not None:
                try:
                    pipe.close()
                except OSError:
                    pass

    def close(self) -> None:
        self._stop()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    @staticmethod
    def _status(row: dict, relative_file: str, status: str, error: str | None = None) -> dict:
        record = {"group_id": row["group_id"], "label": row["label"],
                  "ecosystem": row["ecosystem"], "relative_file": relative_file,
                  "status": status}
        if error:
            record["error"] = error[:300]
        return record

    def _restart_after_failure(self) -> str | None:
        try:
            self._start()
            return None
        except FeatureWorkerError as exc:
            return str(exc)

    def process_file(self, row: dict, relative_file: str, source: bytes,
                     timeout_seconds: float) -> dict:
        process = self.process
        if process is None or process.poll() is not None:
            restart_error = self._restart_after_failure()
            if restart_error:
                return self._status(row, relative_file, "worker_unavailable", restart_error)
            process = self.process
        assert process is not None and process.stdin is not None

        request = {
            "row": row,
            "relative_file": relative_file,
            "source_b64": base64.b64encode(source).decode("ascii"),
        }
        try:
            process.stdin.write(json.dumps(request, ensure_ascii=True) + "\n")
            process.stdin.flush()
            response = self.responses.get(timeout=timeout_seconds)
        except (BrokenPipeError, OSError):
            self._stop(kill=True)
            restart_error = self._restart_after_failure()
            detail = restart_error or "worker exited while processing this file"
            return self._status(row, relative_file, "worker_crash", detail)
        except queue.Empty:
            self._stop(kill=True)
            restart_error = self._restart_after_failure()
            detail = "per-file parser timeout"
            if restart_error:
                detail += f"; worker restart failed: {restart_error}"
            return self._status(row, relative_file, "parse_timeout", detail)

        if response is None:
            code = process.poll()
            self._stop(kill=True)
            restart_error = self._restart_after_failure()
            detail = f"worker exited unexpectedly (code {code})"
            if restart_error:
                detail += f"; restart failed: {restart_error}"
            return self._status(row, relative_file, "worker_crash", detail)
        if response.get("kind") == "result":
            return response["feature"]
        return self._status(row, relative_file, "worker_error",
                            response.get("error", "unexpected worker response"))


def _source_status(row: dict, relative_file: str, status: str) -> dict:
    return {"group_id": row["group_id"], "label": row["label"],
            "ecosystem": row["ecosystem"], "relative_file": relative_file,
            "status": status}


def run(index: Path, npm_root: Path, pypi_root: Path, output: Path, model_name: str,
        limit: int | None = None, batch_size: int = 50, code_length: int = 256,
        data_flow_length: int = 64, max_file_bytes: int = 2 * 1024 * 1024,
        file_timeout_seconds: float = 20, worker_startup_timeout: float = 180) -> dict:
    if max_file_bytes < 1:
        raise ValueError("max_file_bytes must be positive")
    if file_timeout_seconds <= 0 or worker_startup_timeout <= 0:
        raise ValueError("worker timeouts must be positive")

    rows = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [row for row in rows if row.get("source_available")]
    if limit is not None:
        rows = rows[:limit]
    summary = Counter()
    output.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if output.suffix.lower() == ".gz" else open

    with FeatureWorker(model_name, code_length, data_flow_length,
                       worker_startup_timeout) as worker:
        with opener(output, "wt", encoding="utf-8", newline="\n") as stream:
            for ecosystem, repo_root in (("npm", npm_root), ("pypi", pypi_root)):
                ecosystem_rows = [row for row in rows if row["ecosystem"] == ecosystem]
                for start in range(0, len(ecosystem_rows), batch_size):
                    batch = ecosystem_rows[start:start + batch_size]
                    records = []
                    seen_packages = set()
                    try:
                        for row, relative_file, source, source_status in iter_git_package_source_files(
                                repo_root, batch, max_file_bytes=max_file_bytes):
                            seen_packages.add(row["group_id"])
                            if source_status:
                                records.append(_source_status(row, relative_file, source_status))
                            elif source is not None:
                                records.append(worker.process_file(row, relative_file, source,
                                                                  file_timeout_seconds))
                        for row in batch:
                            if row["group_id"] not in seen_packages:
                                records.append({"group_id": row["group_id"], "label": row["label"],
                                                "ecosystem": ecosystem,
                                                "status": "no_supported_source"})
                    except (GitSourceError, OSError, tarfile.TarError) as exc:
                        summary["batch_archive_errors"] += 1
                        records = []
                        for row in batch:
                            try:
                                package_records = []
                                for item, relative, source, source_status in iter_git_package_source_files(
                                        repo_root, [row], max_file_bytes=max_file_bytes):
                                    if source_status:
                                        package_records.append(_source_status(item, relative, source_status))
                                    elif source is not None:
                                        package_records.append(worker.process_file(
                                            item, relative, source, file_timeout_seconds))
                                records.extend(package_records or [{"group_id": row["group_id"],
                                                                    "label": row["label"],
                                                                    "ecosystem": ecosystem,
                                                                    "status": "no_supported_source"}])
                            except (GitSourceError, OSError, tarfile.TarError) as package_exc:
                                records.append({"group_id": row["group_id"], "label": row["label"],
                                                "ecosystem": ecosystem, "status": "source_error",
                                                "error": str(package_exc or exc)[:300]})
                    summary["packages"] += len(batch)
                    for record in records:
                        if record.get("status") == "no_supported_source":
                            summary["packages_without_supported_source"] += 1
                        if "relative_file" in record:
                            summary["files"] += 1
                        summary[record["status"]] += 1
                        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                    completed = min(start + len(batch), len(ecosystem_rows))
                    print(f"{ecosystem}: {completed}/{len(ecosystem_rows)} packages; "
                          f"{summary['files']} source files emitted", file=sys.stderr, flush=True)
    return dict(summary)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--npm-root", type=Path, required=True)
    parser.add_argument("--pypi-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-name", default="microsoft/graphcodebert-base")
    parser.add_argument("--limit", type=int, help="Optional package limit for a pilot")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--code-length", type=int, default=256)
    parser.add_argument("--data-flow-length", type=int, default=64)
    parser.add_argument("--max-file-bytes", type=int, default=2 * 1024 * 1024)
    parser.add_argument("--file-timeout-seconds", type=float, default=20)
    parser.add_argument("--worker-startup-timeout", type=float, default=180)
    args = parser.parse_args()
    result = run(args.index, args.npm_root, args.pypi_root, args.output, args.model_name,
                 args.limit, args.batch_size, args.code_length, args.data_flow_length,
                 args.max_file_bytes, args.file_timeout_seconds,
                 args.worker_startup_timeout)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
