"""
Final verdict tiering, per PROJECT.md Sec 6:
    >= 0.85 (== 8.5 on our 0-10 scale) -> BLOCK
    0.50 - 0.85 (== 5.0 - 8.5)          -> WARN
    < 0.50 (== 5.0)                      -> ALLOW

Fusion note: no trained meta-classifier combines Stage-1 and S2 yet
(deliberate -- see PROJECT.md log: training one against the current fake
S2 stub would learn nothing real and require full retraining once real
S2 exists). Final score = MAX(Stage-1 combined score, S2 score if S2 ran)
-- consistent with the MAX-not-average principle already applied to Stage-1
itself (S1+S3+S4) and to tree propagation, for the same reason: a single
bad signal must not be diluted by other signals looking fine.
"""

from dataclasses import dataclass

BLOCK_THRESHOLD = 8.5  # == 0.85 in Sec 6's 0-1 scale
WARN_THRESHOLD = 5.0   # == 0.50 in Sec 6's 0-1 scale


@dataclass
class Verdict:
    tier: str  # "BLOCK" | "WARN" | "ALLOW"
    final_score: float
    stage1_score: float
    s2_score: float | None  # None if S2 did not run


def compute_verdict(stage1_score: float, s2_score: float | None) -> Verdict:
    final_score = max(stage1_score, s2_score) if s2_score is not None else stage1_score

    if final_score >= BLOCK_THRESHOLD:
        tier = "BLOCK"
    elif final_score >= WARN_THRESHOLD:
        tier = "WARN"
    else:
        tier = "ALLOW"

    return Verdict(tier=tier, final_score=final_score, stage1_score=stage1_score, s2_score=s2_score)