"""
Tree-level MAX-score propagation, per PROJECT.md Sec 4/Sec 7: the verdict
for the package a user is actually installing must reflect the WORST
score found anywhere in its full transitive dependency tree, not just
its own score.

Motivation (see PROJECT.md log): the event-stream/flatmap-stream 2018
incident showed that diffing a package's OWN files (S3) can correctly
show near-zero risk while the actual malicious payload lives in a
newly-added TRANSITIVE dependency. Without tree-level propagation, that
new dependency's own (correctly high) S1/S3/S4 scores would never
reach the top-level verdict a user actually sees.
"""

from dataclasses import dataclass, field


@dataclass
class PropagatedResult:
    top_level_package: str
    top_level_version: str
    max_s1: float
    max_stage1: float | None
    max_s3: float
    max_s2_fake: float
    worst_node: str  # "name@version" of whichever node in the tree produced the max
    worst_signal: str  # which signal (s1/stage1/s3/s2) produced the worst_node's flag
    per_node_scores: list[dict] = field(default_factory=list)


def propagate_tree_scores(top_level_name: str, top_level_version: str, node_scores: list[dict]) -> PropagatedResult:
    """
    node_scores: list of dicts, one per package in the resolved tree
    (including the top-level package itself), each shaped like:
        {"name": str, "version": str, "s1_score": float,
         "stage1_score": float | None, "s3_score": float, "s2_fake_score": float}
    """
    if not node_scores:
        raise ValueError("node_scores must include at least the top-level package itself")

    max_s1 = 0.0
    max_stage1 = None
    max_s3 = 0.0
    max_s2_fake = 0.0
    worst_node = f"{top_level_name}@{top_level_version}"
    worst_signal = "none"
    worst_overall = -1.0

    for node in node_scores:
        node_id = f"{node['name']}@{node['version']}"

        if node["s1_score"] > max_s1:
            max_s1 = node["s1_score"]
        if node.get("stage1_score") is not None:
            if max_stage1 is None or node["stage1_score"] > max_stage1:
                max_stage1 = node["stage1_score"]
        if node["s3_score"] > max_s3:
            max_s3 = node["s3_score"]
        if node["s2_fake_score"] > max_s2_fake:
            max_s2_fake = node["s2_fake_score"]

        # Track which single node+signal produced the single worst value
        # overall, for explainability ("why did this install get flagged?").
        node_candidates = [
            ("s1", node["s1_score"]),
            ("stage1", node.get("stage1_score") or 0.0),
            ("s3", node["s3_score"]),
            ("s2_fake", node["s2_fake_score"]),
        ]
        for signal_name, value in node_candidates:
            if value > worst_overall:
                worst_overall = value
                worst_node = node_id
                worst_signal = signal_name

    return PropagatedResult(
        top_level_package=top_level_name,
        top_level_version=top_level_version,
        max_s1=max_s1,
        max_stage1=max_stage1,
        max_s3=max_s3,
        max_s2_fake=max_s2_fake,
        worst_node=worst_node,
        worst_signal=worst_signal,
        per_node_scores=node_scores,
    )