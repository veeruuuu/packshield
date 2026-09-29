"""
FAKE S2 STUB — NOT REAL DETECTION. DO NOT TRUST THIS SCORE.

This exists ONLY so the rest of the pipeline (tree propagation, fusion,
verdict logic, --shieldmax, enforcement) can be built and tested
end-to-end before real S2 (GraphCodeBERT-based behavioral/AST analysis,
per PROJECT.md Sec 5/Sec 7) is built. Real S2 requires: a properly
sourced malicious-code dataset (Backstabber's Knife Collection access
pending; DataDog's public dataset checked and does not cover this),
GraphCodeBERT fine-tuning (rented GPU), and a sandboxed no-network-egress
execution environment (Sec 4/Sec 9) -- none of which exist yet.

This stub is DETERMINISTIC (same package+version always returns the same
fake score) so downstream testing is reproducible, but the score itself
is COMPLETELY MEANINGLESS -- it is derived from a hash of the package
name, not from any actual analysis of the package's code or behavior.

CRITICAL: any fusion model trained using this stub's output MUST be
retrained once real S2 exists. Training against fake S2 scores cannot
teach the fusion model anything real about S2's actual signal -- it can
only validate that the pipeline plumbing works end-to-end.

Every score this returns is prefixed/tagged as fake in its result so it
can never be silently confused with real S2 output.
"""

import hashlib
from dataclasses import dataclass, field


@dataclass
class S2Result:
    score: float  # 0-10 -- MEANINGLESS, see module docstring
    reasons: list[str] = field(default_factory=list)
    is_fake: bool = True  # always True for this stub -- real S2 must set this False


def run_fake_s2(name: str, version: str, ecosystem: str) -> S2Result:
    """Deterministic fake score derived from a hash -- NOT real analysis."""
    key = f"{ecosystem}:{name}@{version}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    fake_score = (int(digest[:8], 16) % 1000) / 100.0  # 0.00-9.99 spread

    return S2Result(
        score=round(fake_score, 2),
        reasons=[f"[FAKE S2 STUB -- NOT REAL] deterministic placeholder for {key}, "
                 f"do not use this score for any real security decision"],
        is_fake=True,
    )