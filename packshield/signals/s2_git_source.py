"""Read MalwareBench source from Git without materializing package files.

The active reader streams ``git archive`` into memory and never imports,
executes, or writes package contents. Unsafe or Windows-illegal archive members
are skipped; source files over the configured byte limit are reported without
being read into memory.
"""

from __future__ import annotations

import subprocess
import tarfile
from pathlib import Path, PurePosixPath


class GitSourceError(RuntimeError):
    pass


def row_relative_path(row: dict) -> str:
    parts = ["packages"]
    if row["ecosystem"] == "npm" and row.get("scoped"):
        parts.extend([row["scoped"], row["name"], row["version"]])
    elif row["ecosystem"] == "npm":
        parts.extend([row["name"], row["version"]])
    elif row["ecosystem"] == "pypi":
        parts.extend([row["name"], row["version"], row["artifact_id"]])
    else:
        raise GitSourceError(f"unsupported ecosystem: {row.get('ecosystem')!r}")
    return "/".join(parts)


def _safe_member_path(relative_name: str) -> Path | None:
    parts = PurePosixPath(relative_name).parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        return None
    # NTFS rejects trailing spaces/dots and reserved device names. Skipping a
    # README with such a name is safe for the AST walker; source files remain.
    if any(part.endswith((" ", ".")) for part in parts):
        return None
    if any(part.upper().split(".")[0] in {"CON", "PRN", "AUX", "NUL"} for part in parts):
        return None
    return Path(*parts)


def iter_git_package_source_files(repo_root: Path, rows: list[dict],
                                  max_file_bytes: int = 2 * 1024 * 1024):
    """Yield supported source bytes without extracting files to disk.

    Oversized files are reported with ``source=None`` and status
    ``file_too_large``; their bytes are never read into Python memory.
    """
    relative_roots = {row_relative_path(row): row for row in rows}
    ordered_roots = sorted(relative_roots, key=len, reverse=True)
    process = subprocess.Popen(
        ["git", "-c", "safe.directory=*", "-C", str(repo_root),
         "archive", "--format=tar", "HEAD", "--", *ordered_roots],
        stdout=subprocess.PIPE,
        # Discard Git's diagnostics rather than pipe an unread stream: on
        # Windows, a full stderr pipe can stall an otherwise valid archive.
        stderr=subprocess.DEVNULL,
    )
    try:
        if process.stdout is None:
            raise GitSourceError("git archive did not provide stdout")
        with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
            for member in archive:
                root = next((candidate for candidate in ordered_roots
                             if member.name.startswith(candidate.rstrip("/") + "/")), None)
                if root is None or not member.isfile():
                    continue
                relative_name = member.name[len(root.rstrip("/")) + 1:]
                if _safe_member_path(member.name) is None:
                    continue
                suffix = Path(relative_name).suffix.lower()
                ecosystem = relative_roots[root]["ecosystem"]
                supported = {".py"} if ecosystem == "pypi" else {".js", ".mjs", ".cjs", ".jsx"}
                if suffix not in supported:
                    continue
                if member.size > max_file_bytes:
                    yield relative_roots[root], relative_name, None, "file_too_large"
                    continue
                source = archive.extractfile(member)
                if source is None:
                    continue
                with source:
                    source_bytes = source.read(max_file_bytes + 1)
                if len(source_bytes) > max_file_bytes:
                    yield relative_roots[root], relative_name, None, "file_too_large"
                else:
                    yield relative_roots[root], relative_name, source_bytes, None
        return_code = process.wait()
        if return_code != 0:
            raise GitSourceError(f"git archive batch failed with exit code {return_code}")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


