"""
S3 — Update-Diff Poisoning Detector: diffs two signatures (old vs new
version of the same package) and scores newly-introduced risk.

Per PROJECT.md Sec 5, flags: new network calls, new obfuscated blocks,
new install hooks that didn't exist before, sudden minification of a
previously readable file.
"""

from dataclasses import dataclass, field


@dataclass
class S3Result:
    score: float  # 0-10
    reasons: list[str] = field(default_factory=list)


# Sudden jump in avg line length on a file that existed before, past this
# ratio AND past this absolute floor, is treated as likely minification
# rather than ordinary code growth.
_MINIFICATION_RATIO_THRESHOLD = 3.0
_MINIFICATION_ABSOLUTE_FLOOR = 300


def diff_signatures(old_sig: dict | None, new_sig: dict) -> S3Result:
    """old_sig=None means no prior version on record (first-ever publish
    for this package) -- nothing to diff against, so this returns a
    neutral (not risky, not clean) empty result. Caller decides how to
    treat a first-publish case; S3 is fundamentally an update-comparison
    signal and has nothing to say about a package's first version."""
    reasons = []
    score = 0.0

    if old_sig is None:
        return S3Result(score=0.0, reasons=["no prior version on record -- S3 has nothing to diff against"])

    old_files = old_sig.get("files", {})
    new_files = new_sig.get("files", {})

    old_risky = set()
    for f in old_files.values():
        old_risky.update(f.get("risky_calls", []))
    new_risky = set()
    for f in new_files.values():
        new_risky.update(f.get("risky_calls", []))

    newly_introduced = new_risky - old_risky
    for category in sorted(newly_introduced):
        score += 3.0
        reasons.append(f"newly introduced risky capability: {category}")

    old_hooks = old_sig.get("install_hooks", {})
    new_hooks = new_sig.get("install_hooks", {})
    for hook_name in ("preinstall", "install", "postinstall", "prepare"):
        old_val = old_hooks.get(hook_name)
        new_val = new_hooks.get(hook_name)
        if new_val and new_val != old_val:
            score += 4.0
            reasons.append(f"install hook '{hook_name}' added or changed")
    old_deps = set(old_sig.get("declared_dependencies", []))
    new_deps = set(new_sig.get("declared_dependencies", []))
    newly_added_deps = new_deps - old_deps
    for dep_name in sorted(newly_added_deps):
        score += 2.5
        reasons.append(f"new dependency added to manifest: '{dep_name}' "
                        f"(not independently vetted here -- flagged for visibility, "
                        f"same pattern used in the event-stream/flatmap-stream 2018 attack)")

    for rel_path, new_file_info in new_files.items():
        old_file_info = old_files.get(rel_path)
        if old_file_info is None or old_file_info.get("parse_error") or new_file_info.get("parse_error"):
            continue
        old_len = old_file_info.get("avg_line_length", 0)
        new_len = new_file_info.get("avg_line_length", 0)
        if old_len > 0 and new_len > _MINIFICATION_ABSOLUTE_FLOOR:
            ratio = new_len / old_len
            if ratio >= _MINIFICATION_RATIO_THRESHOLD:
                score += 3.0
                reasons.append(f"sudden minification-like change in '{rel_path}' "
                                f"(avg line length {old_len:.0f} -> {new_len:.0f})")

    return S3Result(score=min(score, 10.0), reasons=reasons)