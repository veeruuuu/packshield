"""
S1 — Name Similarity & Homoglyph Detection.

Per PROJECT.md §5:
- Levenshtein + Damerau-Levenshtein distance + keyboard-proximity scoring
- Unicode NFKC normalization + zero-width character stripping + RTL-override detection
- Compared against the top-N most-downloaded packages per ecosystem, not the
  entire registry
- Cost tier: cheap, always runs (Stage 1)

Status: the distance/normalization math below is REAL.
KNOWN SIMPLIFICATION (see PROJECT.md log for this step): "top-N most-downloaded
packages" is currently a small, hand-curated static list per ecosystem
(packshield/data/top_npm.txt, top_pip.txt), NOT a live registry download-count
fetch. This is a stand-in to get S1 scoring working end-to-end; replacing it
with a real top-N-by-downloads fetch is flagged as follow-up work.

Score convention: 0-10 scale (matches the Stage-1 "combined score" scale used
in §6's 4/10 threshold). This is a first-pass heuristic, not tuned against
real data -- per §6/§9, actual thresholds get tuned later against an
evaluation set. Treat these numbers as provisional.

PERFORMANCE NOTE (added when this caused a near-hang on a 35k-row dataset):
- _load_top_names() now caches the file read per ecosystem instead of
  re-reading top_npm.txt/top_pip.txt from disk on every call.
- score_name() now caches its result per (name, ecosystem), since the same
  package name repeats across many rows (different malicious versions of
  the same name).
- The candidate loop now skips any candidate whose length differs from the
  target by more than 2 before running any distance function, since a
  min_dist <= 2 is then impossible anyway.
Without these, this file was effectively O(rows * top_names * distance_cost)
with no memoization -- fine for a handful of packages, but pathological
against a 35k+ row training dataset.
"""

import unicodedata
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"

# Zero-width / invisible characters sometimes used to disguise a name.
_ZERO_WIDTH_CHARS = {
    "\u200b",  # zero width space
    "\u200c",  # zero width non-joiner
    "\u200d",  # zero width joiner
    "\ufeff",  # zero width no-break space / BOM
}

# Directional override/isolate characters -- a strong standalone red flag,
# since a legitimate package name has no reason to contain these.
_RTL_CONTROL_CHARS = {
    "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",  # embeddings/overrides
    "\u2066", "\u2067", "\u2068", "\u2069",              # isolates
    "\u200e", "\u200f",                                   # LRM/RLM
}

# Rough QWERTY adjacency map for keyboard-proximity substitution cost.
_KEYBOARD_ROWS = ["qwertyuiop", "asdfghjkl", "zxcvbnm"]


def _build_adjacency() -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = {}
    for row in _KEYBOARD_ROWS:
        for i, ch in enumerate(row):
            neighbors = set()
            if i > 0:
                neighbors.add(row[i - 1])
            if i < len(row) - 1:
                neighbors.add(row[i + 1])
            adjacency[ch] = neighbors
    return adjacency


_ADJACENCY = _build_adjacency()


@dataclass
class S1Result:
    score: float  # 0-10
    reasons: list[str]


def normalize_name(name: str) -> tuple[str, list[str]]:
    """NFKC-normalize a name, strip zero-width chars, flag RTL control chars.

    Returns (cleaned_name, flags) where flags notes anything suspicious found
    during normalization itself.
    """
    flags = []
    found_zero_width = any(ch in _ZERO_WIDTH_CHARS for ch in name)
    found_rtl = any(ch in _RTL_CONTROL_CHARS for ch in name)

    if found_zero_width:
        flags.append("contains zero-width character(s)")
    if found_rtl:
        flags.append("contains RTL override/isolate character(s)")

    cleaned = unicodedata.normalize("NFKC", name)
    cleaned = "".join(ch for ch in cleaned if ch not in _ZERO_WIDTH_CHARS and ch not in _RTL_CONTROL_CHARS)

    if unicodedata.normalize("NFKC", name) != name:
        flags.append("name changes under NFKC normalization (possible homoglyph)")

    return cleaned, flags


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if len(a) == 0:
        return len(b)
    if len(b) == 0:
        return len(a)

    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                prev[j] + 1,
                curr[j - 1] + 1,
                prev[j - 1] + cost,
            )
        prev = curr
    return prev[-1]


def damerau_levenshtein(a: str, b: str) -> int:
    """Optimal string alignment distance (adds adjacent-transposition to Levenshtein)."""
    if a == b:
        return 0
    len_a, len_b = len(a), len(b)
    d = [[0] * (len_b + 1) for _ in range(len_a + 1)]
    for i in range(len_a + 1):
        d[i][0] = i
    for j in range(len_b + 1):
        d[0][j] = j

    for i in range(1, len_a + 1):
        for j in range(1, len_b + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(
                d[i - 1][j] + 1,
                d[i][j - 1] + 1,
                d[i - 1][j - 1] + cost,
            )
            if (
                i > 1 and j > 1
                and a[i - 1] == b[j - 2]
                and a[i - 2] == b[j - 1]
            ):
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[len_a][len_b]


def keyboard_weighted_distance(a: str, b: str) -> float:
    """Levenshtein variant where substituting an adjacent QWERTY key costs
    less than an unrelated one -- catches fat-finger typosquats specifically."""
    if a == b:
        return 0.0
    len_a, len_b = len(a), len(b)
    prev = [float(j) for j in range(len_b + 1)]
    for i, ca in enumerate(a, start=1):
        curr = [float(i)] + [0.0] * len_b
        for j, cb in enumerate(b, start=1):
            if ca == cb:
                sub_cost = 0.0
            elif cb in _ADJACENCY.get(ca, set()):
                sub_cost = 0.5
            else:
                sub_cost = 1.0
            curr[j] = min(
                prev[j] + 1.0,
                curr[j - 1] + 1.0,
                prev[j - 1] + sub_cost,
            )
        prev = curr
    return prev[-1]


_top_names_cache: dict[str, list[str]] = {}


def _load_top_names(ecosystem: str) -> list[str]:
    if ecosystem in _top_names_cache:
        return _top_names_cache[ecosystem]

    filename = "top_npm.txt" if ecosystem == "npm" else "top_pip.txt"
    path = DATA_DIR / filename
    if not path.exists():
        _top_names_cache[ecosystem] = []
        return []
    with open(path, "r", encoding="utf-8") as f:
        names = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    _top_names_cache[ecosystem] = names
    return names


_score_cache: dict[tuple[str, str], "S1Result"] = {}


def score_name(name: str, ecosystem: str) -> S1Result:
    """Score a single package name for typosquat/homoglyph suspicion.

    Returns a 0-10 score plus human-readable reasons. Cached per
    (name, ecosystem) -- the same package name repeats across many rows
    in a training dataset (different malicious versions of one name).
    """
    cache_key = (name, ecosystem)
    if cache_key in _score_cache:
        return _score_cache[cache_key]

    cleaned, norm_flags = normalize_name(name)
    reasons = list(norm_flags)

    # Directional-override / zero-width tricks are a strong standalone
    # signal regardless of edit distance -- max out the score.
    if norm_flags:
        result = S1Result(score=10.0, reasons=reasons)
        _score_cache[cache_key] = result
        return result

    top_names = _load_top_names(ecosystem)
    best_score = 0.0
    best_reason = None

    for candidate in top_names:
        if cleaned == candidate:
            continue  # exact match to a known popular package -- not a typosquat of itself
        if abs(len(cleaned) - len(candidate)) > 2:
            continue  # cheap pre-filter: distance can't be <= 2 if lengths differ by more

        lev = levenshtein(cleaned, candidate)
        dam = damerau_levenshtein(cleaned, candidate)
        kb = keyboard_weighted_distance(cleaned, candidate)
        min_dist = min(lev, dam, kb)

        max_len = max(len(cleaned), len(candidate))
        if max_len == 0:
            continue

        # Only close calls (1-2 edits) are worth flagging.
        if min_dist <= 2:
            similarity_score = max(0.0, 10.0 * (1 - (min_dist / 3)))
            if similarity_score > best_score:
                best_score = similarity_score
                best_reason = f"within {min_dist:g} edit(s) of popular package '{candidate}'"

    if best_reason:
        reasons.append(best_reason)

    result = S1Result(score=round(best_score, 2), reasons=reasons)
    _score_cache[cache_key] = result
    return result