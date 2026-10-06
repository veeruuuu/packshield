# PROJECT.md — Developer Package Shield (PackShield)

> **THIS IS THE SINGLE SOURCE OF TRUTH FOR THIS PROJECT.**
> Every human developer and every AI agent working on this codebase MUST read this
> file in full before writing any code, and MUST update the relevant sections
> (especially §14 Project Log) after every change — no matter how small.
> Do not delete history. Append corrections; do not silently overwrite past entries.
> If something is not yet decided, mark it `UNKNOWN`. If something is designed but
> not built, mark it `PLANNED`. If something was attempted and abandoned, mark it
> `NOT IMPLEMENTED` or move it to §10 Rejected Approaches — never delete the record.

---

## 0. Document Status

- **Document stage:** Design-complete, pre-implementation.
- **Codebase status as of this writing: NOT IMPLEMENTED.** No source code exists yet.
  Everything in this document describes the *agreed design*, not shipped software,
  unless explicitly marked `IMPLEMENTED` in §14.
- **Last updated by:** Claude (AI agent), initial creation, from project design
  conversation with the team.
- **Academic context:** BE final-year capstone project, CSE (AI & ML specialization),
  Global Academy of Technology (GAT), Bangalore. Academic year 2026–2027.

---

## 1. Project Identity

- **Name:** Developer Package Shield ("PackShield")
- **One-line pitch:** *"Existing tools protect the moment a package is first
  installed. PackShield protects the entire lifetime of that trust — catching not
  just malicious names, but malicious updates to packages you already trusted."*
- **Team (4 members):**
  - Brunda J
  - Lakshman R Solanki
  - Pranav Naik
  - Veeresh Y K
- **Department, USNs, Guide details, Project Category, SDG numbers:** `UNKNOWN` —
  not yet supplied by the team; still placeholders in the formal proposal document.

---

## 2. Problem Statement

Existing package security tools (TypoGuard, pip-audit, npm audit) defend the moment
of *first install* by comparing package names or checking known-CVE databases. They
are blind to two growing attack classes:

1. Packages whose install-time behavior is malicious but whose name is **not** a
   typosquat.
2. **Already-trusted packages that become malicious after a compromised or
   malicious update** — the attack class responsible for the highest-impact
   supply-chain incidents of 2021–2025 (`event-stream`, `ua-parser-js`, `coa`,
   `rc`, `xz-utils`). No tool reviewed in the project's literature survey handles
   this class well.

PackShield is a PATH-intercepting security shim that scores every `npm`/`pip`
install across the **entire trust lifecycle** of a package — from first publish
through every subsequent update — not just its name at install time.

---

## 3. Explicit Threat Model

State this out loud in any defense/demo — it is a designed scoping decision, not an
oversight.

| # | Attack class | Real-world example | Covered by | Status |
|---|---|---|---|---|
| T1 | Typosquatting / homoglyph confusion | `reqeusts`, `colourama` | Signal S1 | PLANNED |
| T2 | Malicious install-time behavior (lifecycle hooks) | credential-stealing `postinstall` scripts | Signal S2 | PLANNED |
| T3 | Update-time poisoning of a trusted package | `event-stream`, `xz-utils`, `coa`/`rc` | Signal S3 (**primary differentiator**) | PLANNED |
| T4 | Maintainer/publisher-level risk | mass-publishing burner accounts | Signal S4 | PLANNED |
| T5 | Dependency confusion (public pkg shadows private internal name) | Birsan 2021 (Apple, PayPal, Tesla) | **Not built — documented future work only** | NOT IMPLEMENTED, no plan to build in this project cycle |

**Explicitly out of scope / known bypass (state this in defense, do not hide it):**
The PATH-shim interception mechanism is bypassable by any developer who calls the
real binary by absolute path (e.g. `/usr/local/bin/npm`) or via `npx`/`corepack`.
This is a known limitation shared by all PATH-shim tools (`nvm`, `asdf`, etc.).
PackShield's threat model assumes a **cooperative developer environment**, not a
hostile one actively trying to evade its own security tooling.

---

## 4. Architecture Overview

```
DEVELOPER MACHINE
  npm install <pkg> / pip install <pkg>
  (or explicitly: packshield install <pkg> [--shieldmax])
        │
        ▼
  PATH SHIM  (single binary; this IS the CLI — no separate "wrapper" component)
        │
        ▼
  Precedence check for ShieldMax mode:
    --shieldmax flag (this call)
      > ~/.packshield/config.json "shieldmax_default" (dashboard "Paranoid Mode" toggle, OFF by default)
      > normal auto-escalating behavior
        │
        ▼
  DEPENDENCY RESOLUTION (dry-run) — full transitive tree, nothing downloaded/executed yet
        │
        ▼
  For each package in tree → CACHE CHECK (name + version + hash)
    HIT  → reuse stored score, go to Tree-Level Risk Propagation
    MISS → enter Signal Pipeline
        │
        ▼
  SIGNAL PIPELINE
    STAGE 1 (always runs, cheap): S1 + S3 + S4 in parallel
      combined score < 4/10 (provisional) AND ShieldMax not active
        → stop, go to Fusion with S1+S3+S4 only
      combined score ≥ 4/10 OR ShieldMax active
        → STAGE 2
    STAGE 2 (conditional/forced): S2
      static GraphCodeBERT pass first
      sandboxed dynamic dry-run only if static pass is inconclusive
        → Fusion with all four signals
        │
        ▼
  FUSION (per package): Meta-Classifier (Gradient-Boosted Trees, e.g. XGBoost/LightGBM)
    → one risk score + exact TreeSHAP breakdown → written to cache + history.jsonl
        │
        ▼
  TREE-LEVEL RISK PROPAGATION (across the full resolved dependency tree)
    MVP: final score = MAX score found anywhere in the tree
    Stretch: GraphSAGE learns propagation instead of flat max
        │
        ▼
  VERDICT
    ≥ 0.85       → BLOCK (real install never runs)
    0.50 – 0.85  → WARN (developer may proceed)
    < 0.50       → ALLOW (real install proceeds, transparently)
    backend unreachable → FAIL CLOSED, warn developer
        │
        ▼
  OUTPUT — written once to ~/.packshield/history.jsonl
    Terminal (TUI, rich/ink) — always available, THIS is where enforcement is felt
    packshield ui (on demand) — local server + browser dashboard, READ-ONLY,
      never part of the enforcement path
```

**HARD ARCHITECTURAL RULE (do not violate this in implementation):**
The PATH shim enforces the BLOCK/WARN/ALLOW decision synchronously, at install
time, entirely on its own. The dashboard is strictly read/visualize/configure. It
never gates or delays an install, and installs must work correctly even if the
dashboard has never been opened once. **CLI enforces. Dashboard visualizes.**

---

## 5. Detection Signals — Detailed Design

### S1 — Name Similarity & Homoglyph Detection
- **Status:** PLANNED
- Levenshtein + Damerau-Levenshtein distance + keyboard-proximity scoring
- Unicode NFKC normalization + zero-width character stripping + RTL-override detection
- Compared against the **top-N most-downloaded packages per ecosystem**, not the
  entire registry (cost control — attackers target popularity)
- Cost tier: cheap, always runs (Stage 1)

### S2 — Install-Time Behavioral Scan
- **Status:** PLANNED
- Static pass: AST parsing of **both** `setup.py`/`pyproject.toml` build backends
  (PyPI) **and** `preinstall`/`postinstall`/`install` hooks in `package.json` (npm)
- Static code/data-flow understanding via **GraphCodeBERT** (fine-tuned pretrained
  checkpoint — see §7 ML Models)
- If static pass is inconclusive: sandboxed dynamic dry-run (isolated
  container/restricted subprocess/Node `vm2`-style isolate, **no network egress**)
  to catch obfuscation (e.g. `exec(base64.decode(...))`) that static AST misses
- Flags: `exec`/`eval`, `subprocess`/`child_process`, raw socket/HTTP calls,
  filesystem writes outside the package directory, environment-variable
  exfiltration patterns
- Cost tier: **expensive** — the only signal gated behind the Stage-1 threshold or
  `--shieldmax` (see §6)
- **Security note (must be preserved in implementation):** this signal downloads
  and parses/executes untrusted, attacker-controlled input. It MUST run inside a
  hardened sandbox with no network egress. The detector itself is an attack
  surface if this is skipped.

### S3 — Update-Diff Poisoning Detector
- **Status:** PLANNED — **primary project differentiator**
- On every new version publish of a package with install history, diff the new
  release's AST and dependency manifest against the previously stored version
- Score the diff for newly-introduced risky capabilities: new network calls, new
  obfuscated blocks, new install hooks that didn't exist before, sudden
  minification of a previously readable file
- **Runs unconditionally alongside S1 and S4 in Stage 1** (not gated) — decided
  because T3 attacks (compromised trusted maintainer) by definition will not
  trigger a name or publisher-reputation suspicion score. Gating S3 behind an
  S1/S4 threshold would create a hole matching exactly the attack class this
  signal exists to catch. Cost is low (cheap diff against a stored artifact, not
  a fresh download/execute), so unconditional execution is affordable.
- **Dependency (must be built for S3 to function):** requires an AST/signature
  store keyed by `(package, version)` so a prior version is available to diff
  against. Not automatically free — this is real backend infrastructure.

### S4 — Publisher/Maintainer Reputation
- **Status:** PLANNED
- Engineered features (not a from-scratch GNN): account age, time since last
  publish, publishing velocity across packages, 2FA-enabled status, co-maintainer
  churn
- Fed into a **gradient-boosted tree (XGBoost/LightGBM)** — deliberately not a
  graph neural network for this signal (see §10 Rejected Approaches: original
  GraphSAGE-as-primary-classifier)
- This sidesteps the cold-start problem: a brand-new *package* can still have a
  scoreable *publisher*
- **UNKNOWN / needs verification before implementation:** whether per-package
  maintainer 2FA status is actually queryable via public npm/PyPI API. This
  differs between registries and may have changed over time. **Do not implement
  this feature until confirmed against current registry API documentation.**

### Developer Override + Local Logging
- **Status:** PLANNED (MVP scope — added as a deliberately cheap addition, not a
  full feedback loop)
- **What it does:** lets a developer explicitly disagree with a verdict and
  proceed anyway, with that override recorded locally. Nothing more.
  - On WARN: developer is prompted; if they proceed, record
    `{ verdict: "WARN", overridden: true, reason: <optional free text> }`
  - On BLOCK: developer can force through via an explicit flag:
    `packshield install <pkg> --override "reason here"`, record
    `{ verdict: "BLOCK", overridden: true, reason: "<text>" }`
  - Both append to the **same** `~/.packshield/history.jsonl` already used for
    scan history — just with two new fields: `overridden: bool`,
    `override_reason: string|null`. No new storage, no new infra, no network
    call.
- **Explicitly does NOT do (do not silently expand scope beyond this):**
  - Does not change any future verdict for that package — an override is a
    one-time local decision, not a whitelist entry. The same package is scored
    fresh next time.
  - Does not retrain or influence any model.
  - Does not send anything anywhere — purely local record-keeping, consistent
    with the local-first privacy principle (§12).
- **Relationship to the broader feedback-loop gap (§11):** this is the cheap
  partial answer to "how does a developer correct a wrong verdict." A full
  active-learning loop (community-submitted corrections → validated retraining
  pipeline → model redeployment) remains explicitly out of scope — see §11.

---

## 6. Signal Tiering & Escalation Logic (Final)

```
STAGE 1 — always runs on every new/changed package (all cheap):
    S1 Name/Homoglyph
    S3 Update-Diff Poisoning (if a prior version exists in the store)
    S4 Publisher Reputation
         │
         ▼
    Combined Stage-1 score
         │
    score < 4/10 (PROVISIONAL — see below)  AND  ShieldMax not active
         → Fusion using S1 + S3 + S4 only
    score ≥ 4/10  OR  ShieldMax active
         → STAGE 2

STAGE 2 — conditional/forced only:
    S2 Behavioral Scan (static GraphCodeBERT → sandboxed dynamic dry-run
       only if static is inconclusive)
         → Fusion using all four signals
```

**Threshold value: 4/10, explicitly provisional.**
Rationale: this is a security tool, so a false negative (malicious package scores
just under threshold, S2 never runs) is worse than a false positive escalation
(S2 runs on a benign package — a compute-time cost, not a false-BLOCK cost, since
S2 running does not itself mean BLOCK). Bias toward over-escalation is the safer
default. **Do not present this number as final in any report or defense** — state
explicitly: *"4/10 is our provisional threshold; the actual cutoff will be tuned
against our evaluation set using an ROC curve to hit our target false-positive
rate (see §9 Evaluation Plan), once real precision/recall data exists."*

### ShieldMax Mode
- **Status:** PLANNED
- Forces Stage 2 (S2) to run unconditionally, regardless of Stage-1 score.
- **Two entry points into the same underlying behavior** (do not build as two
  separate systems):
  1. CLI flag, one-off: `packshield install <pkg> --shieldmax`
  2. Dashboard toggle, persistent: "Paranoid Mode" in `packshield ui`, writes
     `{"shieldmax_default": true}` to `~/.packshield/config.json`. **OFF by
     default.**
- **Precedence order (must be implemented exactly in this order):**
  `--shieldmax` CLI flag (this call only) > `config.json` persisted setting >
  normal Stage-1 auto-escalation.
- Framing note for documentation/defense: ShieldMax does **not** mean "S2 only
  runs when asked." S2 remains in the automatic pipeline via Stage-1 escalation;
  ShieldMax is a second, deliberate entry point for a developer who wants maximum
  scrutiny regardless of score (e.g. installing something unfamiliar or
  high-stakes).

---

## 7. ML Models

| Component | Model | Status | Notes |
|---|---|---|---|
| S2 static code understanding | **GraphCodeBERT** (fine-tuned pretrained checkpoint) | PLANNED | Chosen over CodeBERT — CodeBERT (2020) is dated; GraphCodeBERT adds data-flow-graph structure directly relevant since AST/graph analysis is already used elsewhere in the system. Swap justified against the team's own literature-survey benchmark paper (IEEE Xplore 2024, "Coding-PTMs" — CodeBERT vs CodeT5 vs CodeGen vs UniXcoder), which showed model choice materially affects F1 on security-adjacent classification tasks. |
| S4 publisher reputation | **Gradient-Boosted Trees** (XGBoost or LightGBM — exact choice `UNKNOWN`, either acceptable) | PLANNED | Deliberately not a GNN — avoids cold-start problem, gives native/exact TreeSHAP support. |
| Fusion / meta-classifier | **Gradient-Boosted Trees** (same family as S4) | PLANNED | Not a hand-tuned MLP — chosen specifically so SHAP explanations are exact (TreeSHAP), not approximate post-hoc SHAP. |
| Tree-level risk propagation | **GraphSAGE** | PLANNED (STRETCH GOAL, not MVP) | Operates over the *resolved package dependency tree*, NOT the same graph or purpose as GraphCodeBERT — these are two separate components solving two separate problems and must never be referred to as one merged model ("GraphSAGECodeBERT" is incorrect terminology and must not appear in any documentation, code, or presentation). Cold-start is less severe here than in the original design because even a brand-new leaf package inherits context from its parent edge in the tree. |
| Explainability | **TreeSHAP** (exact) | PLANNED | Chosen over KernelSHAP/approximate SHAP specifically for real-time latency — naive SHAP on a deep fused model (the original CodeBERT+GraphSAGE design) was not fast enough for pre-install blocking. |

**Training cost estimate (informal, not yet measured against real data):**
- GraphCodeBERT fine-tuning (frozen lower layers, top 2–3 layers + classification
  head only): ~2–6 hours per run on a single T4 GPU, a handful of runs for
  hyperparameter tuning. This is fine-tuning a pretrained checkpoint, not training
  from scratch.
- GraphSAGE (2–3 layer GNN, tens of thousands of nodes): minutes to under an hour,
  often CPU-only.
- **Actual project bottleneck is expected to be data collection/labeling and the
  S2 sandbox infrastructure build, not model training time.** Do not under-budget
  these in project planning.

Model choice (superseding original XGBoost/LightGBM entry): Stage-1 (S1+S4) fusion uses sklearn.ensemble.HistGradientBoostingClassifier, not XGBoost/LightGBM. Rationale: sklearn-core dependency (no extra heavy install), native NaN/missing-value handling (critical given real S4 fetch coverage gaps — many resolved-status rows still have partial feature coverage), and native categorical-feature support. Trained on S1 name-similarity score + S4 registry features (package age, days since last publish, total versions, publish velocity, maintainer count, weekly downloads) + class_weight="balanced". Validated recall @ FPR≤5%: 82.0% → 83.4% after adding weekly_downloads (see below). One critical leakage bug was found and fixed during training: s4_registry_status (resolved/not_found/error) was initially included as a feature, but a package's takedown status cannot occur at real inference time (an install target necessarily exists on the registry) — removing it and restricting training to resolved-only rows dropped the (invalid) 97.4% headline recall to a real, trustworthy 82.0%.

Stage-1 combination (S1+S3+S4), deviation from a jointly-trained model: per the original hard constraint that S1, S3, and S4 always run together in Stage 1, but S3 has no paired (old-version/new-version) training data — our dataset only ever had single-version labeled rows — S3 cannot currently be jointly trained alongside S1/S4 in one model. Stage-1's combined score is instead MAX(HistGradientBoosting(S1,S4), S3_score) per package, computed independently per node in the dependency tree. This is a deliberate interim choice, not an oversight: MAX ensures a strong S3 finding (e.g. a newly-added install hook) is never diluted by unrelated S1/S4 scores looking fine, preserving §5's explicit rationale for why S3 runs unconditionally (T3 attacks, by definition, won't trigger a name or publisher-reputation suspicion score). Building a real jointly-trained 3-feature model requires first constructing a version-paired S3 training dataset — a real, scoped future task, not started.

Tree-level propagation: per-node Stage-1/S3 scores are rolled up via MAX across the full resolved dependency tree, not just the top-level install target. Directly motivated by empirical testing against the real event-stream/flatmap-stream 2018 incident (see S3 validation log): the actual malicious payload lived in a newly-added transitive dependency, not the top-level package's own files — without tree-wide MAX propagation, that dependency's own high score would never reach the verdict a user actually sees.

Final verdict fusion (Stage-1 + S2): no trained meta-classifier combines Stage-1 and S2 into the final BLOCK/WARN/ALLOW score. final_score = MAX(Stage-1_max, S2_max) when S2 has run, else Stage-1_max alone. Same MAX-not-average principle as above, applied one level up. This is deliberately provisional: S2 is currently a fake, clearly-labeled deterministic stub (packshield/signals/s2_fake_stub.py), built specifically so the gating (4/10 escalation threshold, ShieldMax precedence), verdict tiering (≥8.5 BLOCK / 5.0–8.5 WARN / <5.0 ALLOW), enforcement (real BLOCK/override), and history.jsonl logging could be built and verified end-to-end before real S2 exists. Every stored verdict record explicitly flags "s2_is_fake": true so this is never ambiguous in stored data. A real fusion model — trained or rule-based — must be revisited once real S2 exists; training against the current fake stub's output would teach nothing real about S2's actual signal.

Verdict thresholds (≥8.5 BLOCK / 5.0–8.5 WARN / <5.0 ALLOW on our 0–10 scale, equivalent to §6's 0.85/0.50 on a 0–1 scale) remain provisional, not tuned against a real evaluation set — same status as the original 4/10 Stage-1 escalation threshold.

## 8. System Components

| Component | Description | Status |
|---|---|---|
| PATH shim / CLI binary | Single binary intercepting `npm`/`pip` calls via PATH precedence | PLANNED |
| Dependency resolver | Dry-run resolution of full transitive tree (`npm ls --all` / pip resolver equivalent) | PLANNED |
| Verdict cache | Keyed by `name + version + hash`; avoids re-scanning unchanged packages | PLANNED |
| AST/signature store | Keyed by `(package, version)`; required for S3 diffing | PLANNED |
| Signal pipeline (S1–S4) | See §5 | PLANNED |
| Meta-classifier / fusion | See §7 | PLANNED |
| Tree-level propagation | Max-score (MVP) / GraphSAGE (stretch) | PLANNED / NOT IMPLEMENTED (stretch) |
| Terminal TUI output | `rich` (Python) or `ink` (Node) — exact choice `UNKNOWN`, depends on implementation language chosen for the CLI | PLANNED |
| `packshield ui` local dashboard | Local server (FastAPI or Express — exact choice `UNKNOWN`) + browser frontend (D3.js dependency-tree graph, scan history, SHAP detail, dark console aesthetic, Paranoid Mode toggle) | PLANNED |
| Config file | `~/.packshield/config.json` — stores `shieldmax_default` and any future user settings | PLANNED |
| History log | `~/.packshield/history.jsonl` — append-only scan history, read by both TUI and dashboard | PLANNED |
| Registry change detection | **Polling** npm's replication/changes feed (`replicate.npmjs.com`) and PyPI's JSON API / RSS changelog to detect new version publishes and invalidate stale cache entries | PLANNED — corrected from an earlier, inaccurate "webhook" design (see §10) |

---

## 9. Evaluation Plan

- **Split methodology:** Temporal train/test split, NOT random split. Train on
  packages published before date X, test only on packages published after X.
  Random splits leak attacker infrastructure patterns across train/test and
  artificially inflate reported numbers.
- **Primary metric:** Recall at a fixed low false-positive rate (e.g. recall @ 1%
  FPR), not plain accuracy. Real-world base rate is roughly 1 malicious :
  10,000+ benign packages, so accuracy alone is not meaningful at this base rate.
- **Per-attack-type breakdown required:** report T1/T2/T3/T4 detection separately,
  not one blended number — this is what proves the system is not merely riding
  easy typosquat (T1) wins while other signals underperform.
- **Negative class construction:** must include obscure, low-download benign
  packages in training data, not only popular ones — otherwise the model risks
  learning "is this package popular" as a shortcut proxy for "is this package
  safe."
- **Adversarial/evasion evaluation:** `NOT IMPLEMENTED / PLANNED, currently the
  weakest part of the evaluation plan.` At minimum, a small hand-crafted set
  (~20–30 samples) of evasive/mimicry packages should be constructed to test
  robustness against an adaptive adversary, not just static known-malware
  detection. This gap was identified but not yet closed as of this document's
  writing.
- **Malware handling policy:** isolated VM, no network egress, samples never
  executed on a grading/demo machine. State this explicitly in any
  presentation — a security-literate reviewer will ask.
- **Suggested data sources (cite these directly, do not use an unspecified
  "N malicious packages" claim):** Backstabber's Knife Collection, OSV.dev,
  npm/PyPI advisory databases, Socket.dev public disclosures, GitHub Advisory
  Database.

---

## 10. Rejected Approaches / Design History

Preserve this section permanently. Do not delete past design decisions even after
they are superseded — this is the project's decision audit trail.

1. **Original design: GraphSAGE as the primary "is this package malicious"
   classifier, over the npm/PyPI dependency graph.**
   — **Rejected.** Fatal flaw: a brand-new malicious package (the most dangerous
   case, since it's the one most likely to slip past reviewers) has zero graph
   history/neighbors, so the model has no signal exactly when it matters most
   (cold-start problem). GraphSAGE was **not removed from the project** — it was
   re-scoped to tree-level risk propagation (§7), a task where cold-start is much
   less severe because even a new leaf package inherits context from its parent
   edge.

2. **Original design: plain CodeBERT (2020) for S2 code understanding.**
   — **Superseded** by GraphCodeBERT. CodeBERT is not "basic" or wrong, but is
   dated relative to 2025–26 alternatives, and the project's own cited literature
   (IEEE Xplore 2024 benchmark paper, present in the lit survey) showed model
   choice materially affects performance on this exact task type — using plain
   CodeBERT without addressing that finding would be a defensible weak point in
   review. GraphCodeBERT chosen as the direct upgrade since it adds relevant
   data-flow-graph structure at near-zero additional integration cost.

3. **Original design: benchmark only against TypoGuard and pip-audit.**
   — **Rejected as insufficient.** These are outdated academic/CLI baselines.
   Superseded by honest positioning against real production tools (Socket.dev,
   Phylum, Snyk), with explicit, defensible differentiators (update-time
   poisoning detection, local-first privacy, editor/CLI-native interception,
   fully transparent per-signal SHAP) rather than a false claim of beating
   commercial tools on raw detection rate.

4. **Original design: "registry webhook listener" to detect new package version
   publishes.**
   — **Factually incorrect, corrected.** npm and PyPI do not push webhooks to
   arbitrary third-party consumers. Corrected design: **poll** npm's public
   CouchDB replication/changes feed (`replicate.npmjs.com`) and PyPI's JSON API /
   RSS changelog.

5. **Original design: VS Code Webview as the primary/only UI surface.**
   — **Superseded**, then further reconsidered. A webview genuinely can support
   rich UI (D3.js, scan history, dark "console" aesthetic) — the earlier claim
   that it could not was an overstatement and was corrected mid-discussion. The
   team then made a separate, deliberate decision to **drop the VS Code webview
   entirely** in favor of a standalone local-server dashboard (`packshield ui`),
   reasoning: (a) removes VS Code extension API learning curve and CSP/bundling
   restrictions, (b) works for any editor or no editor at all, (c) precedent
   exists for this exact pattern (MLflow UI, Prisma Studio, Jupyter — local
   process produces artifacts, local server serves them, browser renders them),
   (d) demoing a browser tab is arguably easier than screen-sharing a VS Code
   sidebar. Explicit condition attached to this decision: the dashboard must
   remain strictly read-only/visualization-only and must never sit on the
   enforcement path (see §4 Hard Architectural Rule).

6. **Considered: CLI wrapper as a separate component from the PATH shim.**
   — **Terminology error, corrected, not a real second component.** "PATH shim"
   and "CLI wrapper" were being used inconsistently to describe what is actually
   one single binary. Resolved: there is one component. Call it the **PATH shim**
   (mechanism) which **is** the CLI binary (implementation). Do not reintroduce
   "CLI wrapper" as a separately named component in code, docs, or diagrams.

7. **Considered: gating S3 (update-diff) behind the same Stage-1 suspicion
   threshold as S2.**
   — **Rejected.** T3 attacks (compromised trusted maintainer publishing a
   malicious update) by definition will not look suspicious by name (S1) or
   publisher history (S4) — the attacker is riding an already-trusted identity.
   Gating S3 behind an S1/S4-triggered threshold would create a blind spot
   matching exactly the attack class S3 exists to catch. Resolved: S3 runs
   unconditionally alongside S1 and S4 in Stage 1, since it is cheap (a diff
   against a stored prior version, not a fresh download/execute).

8. **Naming error to avoid:** the model combination has been informally
   mis-stated as "GraphSAGECodeBERT" in conversation. **This is not a real,
   correct name.** GraphCodeBERT (S2, code/data-flow understanding within one
   package) and GraphSAGE (tree-level risk propagation across the dependency
   graph) are two separate models solving two separate problems in two separate
   pipeline stages. Never merge the names in documentation, code, slides, or a
   defense.

---

## 11. Known Gaps / Limitations (as of this document)

Track honestly — do not let this list quietly disappear as the project matures;
move resolved items to §10 with a note, do not delete.

| Gap | Status | Notes |
|---|---|---|
| Transitive dependency tree coverage | **Addressed in design** (§4 — dependency resolver walks full tree) | Was previously a blind spot: original design only scanned the top-level package a developer typed, missing attacks hidden deep in transitive dependencies (the actual mechanism of the `event-stream` compromise). |
| Dependency confusion (T5) | **Explicitly out of scope**, documented future work only | Not a hidden gap as long as it continues to be stated explicitly in any proposal/defense. |
| Adversarial/mimicry evaluation | **Open, not yet designed in detail** | See §9. Current eval plan handles base-rate realism well but does not yet include an adaptive-adversary test set. |
| 2FA status as an S4 feature | **Unverified** | Do not implement until confirmed against current npm/PyPI API documentation. |
| PATH-shim bypass (absolute path, npx/corepack) | **Known, accepted limitation, not fixed** | Stated explicitly as a threat-model boundary — cooperative-developer assumption (§3). |
| Detector-as-attack-surface (S2 parses untrusted code) | **Addressed in design** — sandboxed execution, no network egress required | Must be preserved exactly as designed during implementation; do not simplify away the sandbox for convenience. |
| Latency budget for S2/SHAP under real-time blocking | **Addressed in design** (TreeSHAP instead of approximate SHAP; S2 gated to avoid running on every install) | No concrete latency target (e.g. "<500ms p95") has been set yet — `UNKNOWN`, should be defined once a working pipeline exists to measure against. |
| Exact implementation language/stack (Python vs Node for the CLI binary) | `UNKNOWN` | Not yet decided. Affects TUI library choice (`rich` vs `ink`) and packaging approach. |
| Backend hosting for S2 cloud-side sandboxing (if any) | `UNKNOWN` | Design assumes local-first processing where possible (see Privacy Posture, §12), with cloud-side sandboxing only for unrecognized packages needing the dynamic dry-run — hosting/infra for this is not yet decided. |
| No active-learning / community feedback loop | **Explicitly out of scope for this project cycle**, future work only | Partial cheap mitigation added: Developer Override + Local Logging (§5) lets a developer record disagreement with a verdict locally. This does NOT retrain the model, does NOT whitelist the package for future scans, and does NOT transmit anything anywhere. A full loop (user corrections → validated retraining → redeployment) was deliberately not built — it requires abuse-resistance against bad-faith "mark as safe" submissions, a retraining pipeline, and model versioning, none of which fit this project's scope. State this trade-off explicitly if asked. |
| No proactive re-scan of already-installed packages | **Explicitly out of scope**, not planned | PackShield protects the install-time moment, not an idle already-installed environment. S3 (update-diff) provides partial, reactive coverage: a poisoned version is caught the next time that package is touched (reinstalled/updated/re-resolved), but there is no scheduled/background re-check of packages sitting untouched in `node_modules`. This is a deliberate scope boundary, not an oversight — a proactive monitoring daemon is a different product (fleet/CI monitoring) from this project's install-time thesis. |

---

## 12. Design Principles (do not violate without updating this document)

1. **CLI enforces, dashboard visualizes.** The dashboard must never be on the
   critical path for a BLOCK/WARN/ALLOW decision.
2. **Fail closed.** If the backend/analysis pipeline cannot be reached, block and
   warn — never silently allow an unverified install.
3. **Privacy: local-first where possible.** AST parsing and feature extraction
   happen locally in the shim/extension where feasible; only feature vectors and
   hashes are sent to any backend, not raw source, unless a package is
   unrecognized and requires cloud-side sandboxing. Rationale: organizations will
   not adopt a tool that exfiltrates their full dependency source tree.
4. **Honest scoping over inflated claims.** Explicitly name what is MVP, what is
   stretch, and what is future work (T5, GraphSAGE propagation, 2FA feature,
   adversarial eval) rather than presenting all components as equally mature.
5. **Cost-aware signal tiering.** Only S2 is gated behind a suspicion threshold or
   explicit ShieldMax request — because it is the only signal with meaningful
   compute cost (download + possible sandboxed execution). S1, S3, S4 always run
   because they are cheap and, in S3's case, specifically because gating it would
   defeat its purpose.

---

## 13. Folder Structure, APIs, Configuration, Testing, Deployment

**Status: NOT IMPLEMENTED / UNKNOWN.** No repository exists yet. This section is a
placeholder that MUST be filled in by the first implementation pass, and MUST be
kept current after every structural change. Suggested minimum sections to populate
once implementation begins:

```
UNKNOWN — folder structure not yet created
UNKNOWN — API contracts (dashboard <-> local server endpoints) not yet defined,
          though §4/§6 sketch: GET /history, GET /scan/:id, poll or WS /live
UNKNOWN — configuration schema beyond {"shieldmax_default": bool} in config.json
UNKNOWN — testing strategy/framework not yet chosen
UNKNOWN — packaging/distribution mechanism for the CLI binary not yet chosen
UNKNOWN — deployment target for any cloud-side sandboxing component
```

Do not invent details here to fill space. Leave as `UNKNOWN` until real decisions
are made, and record the decision plus the date/author in §14 when they are.

---

## 14. Project Log (Living Log — Append, Never Delete)

> **Every developer/agent MUST add an entry here after every work session**,
> covering: files touched, features added, bugs found/fixed, mistakes made,
> dependency/config changes, decisions made and why, tests run and their
> results, and what remains. Append new entries at the bottom in chronological
> order. Never edit or remove a past entry — if a past entry was wrong, add a
> new entry correcting it and say so explicitly.

### Entry 1 — Initial design conversation (pre-implementation)
- **Author:** Claude (AI agent), in conversation with the project team.
- **What happened:** Full architecture designed from scratch across an extended
  design conversation. Original 4-signal design (name similarity, AST scan,
  GraphSAGE-as-classifier, SHAP) critically reviewed; GraphSAGE cold-start flaw
  identified; CodeBERT flagged as dated relative to team's own cited literature;
  webhook assumption corrected to polling; UI approach explored (VS Code webview
  → reconsidered → replaced with standalone local dashboard); S2 cost concerns
  addressed via tiered escalation + ShieldMax; S3 correctly moved to
  always-run-with-S1/S4 rather than gated, to preserve T3 coverage.
- **Files touched:** None (no repository exists yet).
- **Decisions made:** See §10 for full rejected-approaches history and rationale.
  Final architecture as documented in §4–§8 represents the agreed design as of
  this entry.
- **Tests run:** None — no code exists.
- **Known open items carried forward:** adversarial evaluation set not designed
  (§9), 2FA feature unverified (§11), implementation language/stack undecided
  (§11), folder structure/APIs/testing/deployment all `UNKNOWN` (§13).
- **Next step for whoever picks this up:** Choose implementation language for the
  CLI binary (affects TUI library and packaging), then scaffold the repository
  structure and update §13 accordingly before writing detection logic.

### Entry 2 — Post-install maintenance & feedback-loop discussion
- **Author:** Claude (AI agent), in follow-up conversation with the project team.
- **What happened:** Team asked whether any maintenance-after-install or
  feedback mechanism had been designed. Confirmed neither had been — no
  scheduled re-scan of already-installed packages, and no way for a developer to
  correct a verdict they disagree with. Both were discussed and a scoping
  decision was made: full proactive re-scanning and a full active-learning
  feedback loop are both explicitly out of scope (see §11 for reasoning on
  each). A minimal, low-cost addition was approved and added: **Developer
  Override + Local Logging** (§5) — reuses the existing `history.jsonl`, adds
  `overridden`/`override_reason` fields, no new infra, no model impact, no
  network call.
- **Files touched:** `PROJECT.md` — added Developer Override + Local Logging
  subsection to §5, added two rows to the §11 Known Gaps table (feedback loop,
  proactive re-scan), added this log entry.
- **Decisions made:** (1) No proactive/background re-scan of installed
  packages — deliberate scope boundary, PackShield remains install-time-focused.
  (2) No full feedback/active-learning loop — deliberate scope boundary, named
  as future work. (3) Developer override + local logging IS added to MVP scope
  as the cheap partial mitigation for (2).
- **Tests run:** None — no code exists yet.
- **Next step for whoever picks this up:** When the CLI and `history.jsonl`
  schema are actually implemented, include `overridden`/`override_reason` fields
  from the start rather than retrofitting them later.

<!-- Add Entry 3, Entry 4, ... below this line. Do not remove prior entries. -->
### ENtry 3

Environment: Windows laptop, PowerShell, Python 3.11+, virtual environment at .venv/.
Files created: pyproject.toml, packshield/__init__.py, packshield/cli.py, .gitignore.
Decision made: Implementation language = Python 3.11+ (resolves §11/§13 UNKNOWN). TUI = rich, CLI parsing = click. Packaging/distribution mechanism (frozen binary vs pip console-script) remains UNKNOWN, deferred.
What's real vs stubbed: Real — a working packshield install <pkg> --pm npm|pip command, pip-installable in editable mode, that passes through to the real package manager. Stubbed: everything else in §4–§8 — PATH-shim interception, dependency resolution, verdict cache, S1–S4, fusion, tree propagation, verdicts, history.jsonl, config file, dashboard. --shieldmax/--override are parsed but no-ops.



### entry 4

Files created: packshield/resolver.py.
Files changed: packshield/cli.py — now calls resolve_tree() before passthrough and prints the resolved tree as a table.
What's real vs stubbed: Real — dry-run dependency resolution for both npm (npm install --dry-run --json in a disposable temp dir) and pip (pip install --dry-run --report -), returning a flat {name, version} list per package, with no code downloaded or executed. Stubbed/not implemented: cache check (name+version+hash), S1–S4, fusion, tree-level propagation, verdicts, history.jsonl, PATH-shim interception, config file, dashboard.
Known simplification, noted honestly: tree is currently flat (list of packages), no parent/child edges recorded. Acceptable for MVP since tree-level propagation is MAX-score-based (§4/§7); edges would only become necessary for the GraphSAGE stretch goal.


### entry 5

Files created: packshield/cache.py.
Files changed: packshield/resolver.py — each resolved entry now also carries a real content hash (npm: registry dist.integrity/dist.shasum lookup; pip: sha256 from the install report, with graceful "unknown" fallback if a hash can't be found). packshield/cli.py — resolved tree now goes through a cache HIT/MISS check keyed on (pm, name, version, hash) and displays it in the output table.
What's real vs stubbed: Real — cache file read/write at ~/.packshield/cache.json, key construction, HIT/MISS lookup, hash-fetching for both ecosystems. Stubbed/not implemented: nothing ever calls store_verdict() yet, because S1–S4/fusion (the thing that would produce a verdict) don't exist — so every run will show all-MISS until that's built. Also still stubbed: signal pipeline, tree-level propagation, actual verdicts, history.jsonl, PATH-shim interception, config file, dashboard.
Known limitation, noted honestly: npm registry hash lookup does a live network call per package during resolution — this is metadata-only (no code downloaded/executed, consistent with §4's dry-run requirement) but adds latency; acceptable for MVP, worth revisiting once there's a real latency budget (§11 notes none is set yet).
Next step: your call — say "next step" when ready. Natural candidates: S1 (name/homoglyph similarity) since it's the cheapest signal and needs no new infra, or the AST/signature store needed for S3.


### Entry 6

Files created: packshield/signals/__init__.py, packshield/signals/s1_name_similarity.py, packshield/data/top_npm.txt, packshield/data/top_pip.txt.
Files changed: packshield/cli.py — now computes and displays an S1 score + reason per resolved package.
What's real vs stubbed: Real — NFKC normalization, zero-width character detection, RTL-override detection, Levenshtein, Damerau-Levenshtein (optimal string alignment variant), and QWERTY-keyboard-weighted edit distance, combined into a 0–10 S1 score per package name. Known simplification, stated honestly: the "top-N most-downloaded packages per ecosystem" comparison set (§5) is currently a small hand-curated static list (~80 names per ecosystem), not a live download-count fetch from the registry — flagged as follow-up work. S1's score is currently informational/display-only — it feeds nothing (no Stage-1 combined score, no gating, no fusion, no verdict, no cache write) since those don't exist yet.
Still stubbed: S2, S3, S4, fusion, Stage 1 combined-score/threshold logic (§6), tree propagation, verdicts, history.jsonl, PATH-shim interception, config file, dashboard.
Next step: your call — natural candidates are S4 (publisher reputation, no new infra needed beyond registry API calls) or the AST/signature store needed for S3.


### Entry 7 
Files created (deliverables, not repo code):
s2_behavioral_dataset.jsonl — 20,794 rows, built from user-supplied CLAMPD_npm_malicious.csv, CLAMPD_npm_benign.csv, CLAMPD_pypi_malicious.csv, CLAMPD_pypi_benign.csv. Unified schema (ecosystem, name, version, label, attack_type, source, features). CLAMPD's own pre-extracted behavioral features (api_call_count, entropy, has_risky_api, etc.) kept as-is, unaltered — already normalized/standardized upstream, not raw units. This is S2-shaped data.
s1_s4_name_metadata_dataset.jsonl — built from the same CLAMPD files plus user-supplied datadog_npm_malicious.csv and datadog_pypi_malicious.csv. Name/version/label/ecosystem only, no behavioral features. Deduplicated by (ecosystem, name, version). Current counts: npm malicious=6,211 / benign=7,145; pypi malicious=55,247 / benign=3,633.
s1_s4_name_metadata_dataset_balanced_train.jsonl — separate training-only subset, 5:1 malicious:benign cap via seeded random undersampling (seed=42, reproducible). npm unchanged (6,211/7,145); pypi malicious downsampled 55,247 → 18,165 against 3,633 benign. 35,154 rows total. Original full dataset above is untouched/still shipped for eval use.



### Entry 8
Files changed: s1_s4_name_metadata_dataset.jsonl, s1_s4_name_metadata_dataset_balanced_train.jsonl, s2_behavioral_dataset.jsonl — all rows now carry attack_type (T1/T2/T3/UNKNOWN, None for benign) and attack_type_confidence (verified/inferred/unknown/None).
Method: T3 = exact-name match against the 5 incidents named in §2 (verified tier — found 0 matches this pass). T2 = every CLAMPD malicious row, inferred from CLAMPD's own feature set being inherently behavioral/install-time. T1 = Datadog/CLAMPD malicious names within edit-distance ≤2 of the top_npm.txt/top_pip.txt lists (Step 4's exact distance functions), inferred. T4 = not attempted, left UNKNOWN — no per-package maintainer/publish-velocity data exists yet to base it on.
Known gap, stated plainly: zero verified T3 rows currently in either dataset — the 5 named incidents aren't present by name in the source data. Majority of pypi malicious rows (51,433 / 55,247) remain UNKNOWN — real coverage of T1/T4 for that set is still limited by the small static top-package list and missing publisher metadata.
Next step: your call — add the 5 named T3 incidents as explicit rows, tackle gap #2 (live registry fetch for publish_date/maintainer), or move to the training script.




### Entry 9


Files changed: s1_s4_name_metadata_dataset.jsonl (72,236 → 72,249 rows), s1_s4_name_metadata_dataset_balanced_train.jsonl (35,154 → 35,167 rows). Not changed: s2_behavioral_dataset.jsonl — deliberately excluded, since these incident rows have no CLAMPD-style behavioral features and adding them there would mean fabricating or leaving blank feature values in a dataset meant to be real behavioral data.
13 rows added, all ecosystem=npm, attack_type=T3, attack_type_confidence=verified, source="named incident (PROJECT.md Sec 2)", each with a source_url and a publish_date_approx (explicitly labeled approximate, not exact registry timestamp — drawn from incident reports, not registry metadata):
event-stream@3.3.6
ua-parser-js@0.7.29, @0.8.0, @1.0.0
coa@2.0.3, @2.0.4, @2.1.1, @2.1.3, @3.0.1, @3.1.3
rc@1.2.9, @1.3.9, @2.3.9
xz-utils deliberately excluded, not a gap to revisit: it's distributed via Linux distro tarballs/apt/rpm (CVE-2024-3094), never published to npm or PyPI — structurally outside this project's npm/pip-only ecosystem scope (§4), not a sourcing failure.
Verification method: each incident cross-checked against multiple independent sources (CISA, GitHub Security Advisories, Snyk, BleepingComputer, Security Affairs) before adding — not single-sourced.
Remaining T3 coverage gap, still true: these 4 packages/13 versions are the only verified T3 rows in the dataset. Broader T3 coverage beyond these named incidents would require actively researching other update-poisoning cases, which hasn't been done.


### Entry 10
Files changed: s1_s4_name_metadata_dataset.jsonl, s1_s4_name_metadata_dataset_balanced_train.jsonl — every row now has s4_features (real package_age_days, days_since_last_publish, total_versions, versions_last_90_days, maintainer_count when resolved, else null) and s4_fetch_error (null on success, else the specific reason).
Resolution counts: full dataset — 12,774 / 72,249 rows resolved (17.7%), 59,475 unresolved, 0 not-attempted. Balanced-train subset — 12,511 / 35,167 resolved (35.6%, higher because pypi malicious was downsampled there). Root cause of the low overall rate: the great majority of unresolved rows are Datadog's pypi malicious list (51,292 genuine not_founds) — already-detected-and-removed malware, so a 404 there is the correct, expected answer, not a data problem.
Bug found during this step, not yet fixed: 1,914 npm packages failed with AttributeError: 'dict' object has no attribute 'replace' in _fetch_npm_features — npm's registry occasionally returns a non-string value in a version's time entry, which the code didn't handle. These 1,914 packages currently show s4_fetch_error = that exception message rather than a clean not_found/resolved. Fix + targeted re-fetch of just these 1,914 is still open work.
Dataset gap #2 status: substantially addressed — real S4 features now exist for the ~12.7k rows where resolution succeeded; the practical implication for training is that usable-for-S4 malicious examples are a smaller subset than the full malicious label count, especially on the pypi side.



### Entry 11

Bug fix (#1): _fetch_npm_features in packshield/signals/s4_publisher_reputation.py — excluded time.unpublished (a dict, not a date string) and added an isinstance(v, str) guard. Root cause of the 1,914-package AttributeError crash. Not yet re-run — waiting on you to apply the fix and run the retry tool against s4_retry_candidates.jsonl (1,922 rows extracted and provided).
Missing-feature handling (#5): added s4_registry_status (resolved/not_found/error) as a real categorical field on every row, rather than imputing fake numbers or dropping rows. Chosen specifically because HistGradientBoostingClassifier handles NaN natively — s4_features stays null for unresolved rows, ready to feed the model as-is.
Model choice (#6): confirmed — HistGradientBoostingClassifier, no better alternative worth the switch (CatBoost was the only real contender, not worth the extra dependency). Log this into §7 as settled.
OpenSSF verification (#7): skipped per your call.
Pypi benign expansion (#8): added 460 (full)/472 (balanced) real benign rows sourced from hugovk/top-pypi-packages (2026-09-01 snapshot, publicly hosted, download-ranked, includes packages well beyond just the top 20 for diversity). pypi benign: 3,633 → 4,093 (full), → 4,105 (balanced). These new rows have s4_registry_status: "not_attempted" — still need a live fetch pass.
Files placement reminder still open: local data\ folder needs the freshly re-downloaded versions of both files above (they changed again in this step).


### Entry 12
npm dict-parsing bug: fixed and verified. _fetch_npm_features now correctly excludes time.unpublished and guards with isinstance(v, str). Confirmed against the original failing examples (antibyfron, fluxhttp) — both now resolve with real feature data.
Retry merge complete: 2,302 rows newly resolved across both dataset files (from the 1,922 unique previously-bugged npm packages). Only 8–9 rows remain genuinely unresolved (real not_found/other, not the bug).
Dataset gap #2 (S4 live features) is now essentially closed for everything fetched so far. Remaining open thread: the ~932 new pypi benign names from the hugovk/top-pypi-packages addition still have s4_registry_status: "not_attempted" — not yet fetched.
Still open before/alongside training: decide whether to fetch those ~932 names now or accept them as not_attempted for the first training pass (HistGradientBoosting handles the resulting NaNs fine either way, so this isn't a hard blocker).


### Entry 13
Files created: packshield/training/__init__.py, packshield/training/prepare_features.py.
What's real: builds a flat feature table (S1 score recomputed from real signal code, S4's 5 raw features with blanks for unresolved, s4_registry_status) from either dataset file, ready for HistGradientBoostingClassifier (blank CSV cells → NaN, handled natively).
Known gap, stated plainly: §9's temporal train/test split is not implemented and not currently possible — absolute fetch timestamps were never stored alongside the relative day-count features, so there's no way to reconstruct real dates. Random stratified split will be used instead once training starts; this is a real limitation, not a stylistic choice, and should be fixed going forward by having the fetch tool record its run timestamp.



### Entry 14
Files created: packshield/training/train_stage1.py.
Critical bug found and fixed during this step: s4_registry_status was initially included as a model feature. It caused severe leakage — a package's takedown status (not_found) cannot occur at real inference time (an install target necessarily exists on the registry), but the model learned to exploit it anyway. Initial (invalid) result showed 97.4% recall @ 5% FPR, which collapsed to 65.9% when isolated to the resolved-only subset that actually represents real deployment. Fixed by removing s4_registry_status as a feature entirely and restricting both training and evaluation to s4_registry_status == "resolved" rows only.
Real, trustworthy Stage-1 result (S1 + S4 features only, HistGradientBoostingClassifier, class_weight="balanced"): Recall @ FPR≤1%: 56.8%. Recall @ FPR≤5%: 82.0% (actual FPR 4.17%). Recall @ FPR≤10%: 91.8%.
Per-attack-type breakdown (at the 5%-FPR threshold): T2: 86.3% (n=866, reliable sample). UNKNOWN: 37.5% (n=80) — flagged as a genuine, real weakness of Stage-1 alone, not a bug; plausibly attacks better suited to S2/S3. T1 (n=4) and T3 (n=2): sample sizes too small to draw any conclusion.
Dataset size reduction, stated honestly: training now uses only the ~15,536 rows with real resolved S4 features (down from 72,249 total), since that's genuinely all the trustworthy labeled data available — not an error, a correct consequence of fixing the leak.
Still open: temporal split (§9) remains unimplementable without fetch timestamps. T1/T3 sample sizes remain too small for reliable per-type evaluation. Model saved to data/stage1_model.joblib.

### Entry 15
Bug found and fixed: cli.py was importing score_publisher, which no longer existed after the heuristic-removal step — packshield install was broken. Fixed by wiring in the real trained model instead.
Real progress: packshield install now computes a genuine Stage-1 (S1+S4) score per resolved package using the actual HistGradientBoostingClassifier trained earlier, and shows whether it would cross the provisional 4/10 gating threshold (§6) — display-only, no enforcement yet.
S4 status, stated plainly: raw feature fetch is real and now live-wired into installs (not just training). 2FA status and co-maintainer churn remain explicitly deferred per §5/§11 — not a bug, a stated scope decision.
Still not wired in: S3 (code and store exist, but cli.py doesn't call them), S2, fusion across all 4 signals, tree-level MAX propagation, verdict/BLOCK-WARN-ALLOW logic, cache writes, history.jsonl.

### Entry 16
Bug found and fixed (my error, not yours): merged weekly_downloads into the dataset file in the sandbox but forgot to actually hand you the updated file — first retrain silently ran against stale local data, giving byte-identical (wrongly "unchanged") results. Caught via exact-match TP/FP/TN/FN comparison, re-shared the correct file, confirmed the retrain then genuinely changed.
New S4 feature added: weekly_downloads, fetched via npm's api.npmjs.org/downloads/point/last-week and PyPI's pypistats.org/api/packages/{name}/recent (separate endpoints from the registry metadata API already in use). Fetched for the ~12,660 resolved-status training packages (83% coverage after retry-with-backoff; original naive fetch got only 19.4% due to rate limiting — fixed with exponential backoff + lower concurrency).
Aggregate metric improvement: recall @ FPR≤5%: 82.0% → 83.4%. Recall @ FPR≤1%: 56.8% → 61.6% (bigger relative gain at the stricter threshold). T1/T2/T3/UNKNOWN breakdown otherwise unchanged, as expected — this feature targets a different failure mode than those categories.
Real-world validation, not just aggregate metrics: re-ran packshield install express --pm npm — the entire ljharb/es-shims false-positive cluster found earlier (dunder-proto, math-intrinsics, get-proto, es-object-atoms, call-bind-apply-helpers, call-bound, side-channel-*, es-errors, es-define-property, gopd) now scores 0.02–0.89/10, correctly below threshold. Zero false positives across all 68 packages in the real express dependency tree — a genuine, confirmed fix, not just a metrics improvement that might not hold in practice.
Live CLI updated too, not just training: _fetch_s4_features in cli.py now fetches weekly_downloads at real inference time, not only during dataset preparation — so this fix applies to actual packshield install runs, not just offline evaluation.
Model saved: data/stage1_model.joblib (updated).
Still open, unchanged by this step: UNKNOWN recall (37.5%→38.8%, still weak — confirmed separately as likely real T3/T4-shaped attacks, not fixable by more Stage-1 tuning), T1/T3 sample sizes still too small to trust, temporal split still not implementable.
### Entry 17
Files created: packshield/tools/smoketest_s3_js.py, packshield/tools/validate_s3_against_t3_incidents.py, packshield/signals/s3_fetch.py. Files rewritten: packshield/signals/s3_store.py (version-aware, bug fix). Files changed: packshield/signals/s3_signature.py (added declared_dependencies extraction), packshield/signals/s3_diff.py (added dependency-list diffing), packshield/cli.py (S3 fully wired into install, runs unconditionally per §5).
JS/esprima path: smoke-tested, PASS — all injected changes (eval, child_process, env access, obfuscated literal, new install hook) correctly detected.
Real historical validation: ua-parser-js (7.0, would catch), coa (10.0, would catch), rc (10.0, would catch) — tested via real current live source + a reconstruction of the documented attack pattern (npm fully deleted the original malicious tarballs — confirmed via direct 404s; Backstabber's access still pending; DataDog's public dataset checked and does not contain these specific incidents). event-stream tested via dependency-diff (2.5, would miss alone) — revealed that the real 2018 payload lived in a newly-added dependency (flatmap-stream), not event-stream's own files, meaning this specific attack pattern is only fully caught once tree-level MAX propagation (not yet built) scores the new dependency independently — not a flaw in S3 itself.
Critical bug found and fixed via direct evidence (debug instrumentation), not guesswork: s3_store.py originally keyed only by (ecosystem, name), with no version tracking. When a dependency tree contains multiple coexisting major versions of the same package (common — e.g. content-type@1.0.5 and @2.1.0 both present via different sub-dependents), the store would get overwritten mid-resolution by whichever version was processed last, corrupting the baseline and producing a false positive (content-type@2.1.0 falsely flagged with a fabricated "install hook added" at score 4.0) on a later encounter of the original version. Fixed: store now tracks version per entry; a major-version mismatch is explicitly skipped (not diffed, not silently compared) rather than corrupting state.
Safety-critical design decision, stated explicitly: S3's source fetch (s3_fetch.py) downloads and extracts package tarballs directly (npm .tgz, PyPI sdist/wheel) without ever invoking npm install/pip install on the target — meaning no preinstall/postinstall/setup.py code ever executes during S3's analysis. This preserves the entire point of Stage-1 gating (inspect before executing).
Known accepted limitation, stated plainly: S3's first-ever-seen version for any package becomes the trusted baseline with no independent verification that it wasn't already compromised — inherent to diff-based detection, not fixed here.
S3 status: COMPLETE. Real code, real AST parsing (both ecosystems), real safe fetching, real store with a fixed real bug, validated against real historical incidents.
### Entry 18
Files created: packshield/config.py (minimal config.json read, only shieldmax_default), packshield/history.py (history.jsonl append writer), packshield/verdict/verdict.py (BLOCK/WARN/ALLOW tiering per §6's exact thresholds, translated to our 0–10 scale: ≥8.5/5.0–8.5/<5.0).
packshield/cli.py fully rewritten to wire everything together:
Corrected a spec deviation from earlier: Stage-1 is now genuinely S1+S3+S4 (per your original hard constraint), combined via per-node MAX rather than a jointly-trained model — logged reason: S3 has no paired training data yet (see the dataset-gap discussion above), so joint retraining isn't possible right now; MAX is the honest interim per the same "worst signal wins" principle used elsewhere.
S2 (fake stub) gating fixed to match spec: previously ran unconditionally on every package (a bug relative to your original constraint "only S2 is gated behind the 4/10 threshold or --shieldmax"); now only runs when tree-max Stage-1 ≥ 4/10 or ShieldMax is active.
ShieldMax precedence implemented exactly as specified: CLI --shieldmax flag > config.json's shieldmax_default > normal auto-escalation.
Final verdict computed and — for the first time — actually enforced: BLOCK stops the real install unless --override "reason" is passed; WARN interactively prompts the developer (click.confirm); ALLOW proceeds silently.
--override now does something real (previously a permanent no-op): forces a BLOCK through, recorded to history.
history.jsonl writing implemented: every verdict (BLOCK/WARN/ALLOW) is appended, including overridden/override_reason fields, per §6's exact schema instruction (same file, two extra fields, no new storage).
What's still fake/not real, stated plainly: S2's actual score is a deterministic hash — meaningless for real security decisions, only used to validate that the gating/verdict/enforcement plumbing works end-to-end. Every history entry explicitly records "s2_is_fake": true so this is never ambiguous in stored data.
Status: BUILT BUT NOT YET TESTED. No test run has been executed or confirmed since this was written — the diagnostic run (packshield install express --pm npm, then again with --shieldmax, then checking history.jsonl) is still outstanding.
### Entry 19
Files created: packshield/signals/s4_cache.py (last-known-good cache, keyed by (ecosystem, name), fallback-only policy — never serves stale data when live fetch succeeds).
Bug found and fixed: live S4 fetches (registry features + weekly downloads) had no retry or fallback. A single transient failure on either the npm downloads API or pypistats.org (both independently confirmed to rate-limit/error somewhat often, per the earlier bulk-fetch step) silently produced NaN for that run, causing the same package, same version, minutes apart to score dramatically differently (e.g. etag@1.8.1 Stage-1 score: 0.03 → 3.81 → back to 0.03) with nothing about the package having changed. Flagged as a real reliability problem for a tool making BLOCK decisions, not just noise.
Fix verified: two consecutive runs of packshield install express --pm npm now produce byte-identical Stage-1 scores across all 68 packages.
Known limitation, stated honestly: the very first fetch for any never-before-seen package still has nothing cached to fall back on — a transient failure there still produces NaN/None on that first run. Inherent to any last-known-good cache design, not fixed here, not expected to be.
Verdict/enforcement/history/override step: now fully confirmed, including this reliability fix. BLOCK stops real installs, --override correctly forces through and records the reason, history.jsonl entries are accurate, ShieldMax precedence works, and scores are now stable across repeated runs.
### Entry 20
Files created: packshield/shim/setup.py, updated packshield/cli.py (added shim install/shim uninstall commands and the hidden _shim_intercept command; refactored the core pipeline into run_pipeline() so both the explicit install command and the shim share identical logic — no duplicated/drifting code paths).
Two mechanisms shipped together, one bug found and fixed along the way:
.cmd files in ~/.packshield/shims + User PATH — the originally-planned approach.
PowerShell profile functions — added after discovering mechanism 1 alone silently fails on Windows: Node.js installs itself to System PATH, which Windows always searches before User PATH regardless of string ordering within the User variable, so the real npm won permission-free every time. Profile functions resolve before PATH search entirely, sidestepping the problem with no admin rights needed.
Second bug found and fixed: click's argument parser was swallowing flag-like tokens (npm --version) as options to our own hidden command rather than passing them through, because nargs=-1 alone doesn't stop click from trying to interpret --prefixed tokens. Fixed with type=click.UNPROCESSED + ignore_unknown_options=True.
Verified working, end-to-end, in a genuinely fresh PowerShell session (not just re-activated): npm --version and npm list pass through untouched; npm install express triggers the complete Stage-1+verdict+enforcement pipeline exactly as packshield install does, with real npm install running afterward on ALLOW.
Documented scope limitations, not bugs: (1) only named-package installs (npm install <pkg>) are intercepted — bare npm install / pip install -r requirements.txt pass through unscored, since the pipeline only resolves one named package's tree, not "everything in a manifest." (2) python -m pip install <pkg> can never be intercepted by any PATH/profile shim on pip, since that invocation never touches anything named pip. (3) Interception via the profile-function mechanism only works inside PowerShell — cmd.exe and other shells fall back to mechanism 1's reliability, which is itself not guaranteed on typical Windows setups.
PATH-shim interception status: COMPLETE and verified.
### Entry 21
Files created: none new — packshield/config.py expanded from a single-purpose get_shieldmax_default() reader into a generic get/set-by-key config system, still exposing only shieldmax_default per §11's explicit "schema beyond this is UNKNOWN" scope note. packshield/cli.py gained config show and config set-shieldmax on|off commands — the CLI stand-in for the dashboard's not-yet-built "Paranoid Mode" toggle.
Verified: full 3-tier ShieldMax precedence now confirmed end-to-end (previously only the CLI-flag tier had been tested): --shieldmax flag > config.json's shieldmax_default > normal 4/10 auto-escalation. This test specifically proved the middle tier, which nothing had exercised until now.
Incidental correct-behavior finding: the shim's scope-limitation check (only score installs with a genuinely named package) correctly caught and passed through pip install -e . itself without attempting to misinterpret -e as a package name — confirms the earlier scope-limitation design holds up against a real edge case, not just the cases it was originally written for.
Config file support status: COMPLETE.
### Entry 22
New asset acquired: MalwareBench dataset access granted (Google Form approved) — 20,792 labeled npm/PyPI packages (6,659 malicious), includes actual package files suitable for AST-level feature extraction, per Nair et al. (MSR 2024). This replaces the earlier stalled Backstabber's Knife Collection / insufficient DataDog dataset path as the primary S2 training data source.
Status: access confirmed, dataset not yet downloaded/inspected. Real ingestion work starts once the files are in hand.
### Entry 23
Files changed: packshield/tools/fetch_s4_raw_features.py, packshield/tools/fetch_download_counts.py, packshield/signals/s4_cache.py — all now record a real UTC fetched_at timestamp alongside every fetched value.
What this fixes: closes the §9 temporal-split gap going forward only. Any dataset built from a fetch run after this change will carry real calendar timestamps, enabling a proper past/future train-test split for any future retraining.
What this does NOT fix: none of the already-collected training data (the ~72k-row dataset, the S4 feature cache, the download-counts cache) gains timestamps retroactively — those remain permanently unsplittable temporally, as already logged. The current stage1_model.joblib was trained on that data and still only has the random-split evaluation on record.
### Entry 24
Files created: packshield/dashboard/__init__.py, packshield/dashboard/server.py (FastAPI app), packshield/dashboard/static/index.html (dark-console-aesthetic frontend). Files changed: pyproject.toml (added fastapi>=0.110, uvicorn>=0.29), packshield/cli.py (added ui command, extended history_entry with a new node_scores field carrying the full per-package tree breakdown).
Two deliberate deviations from the original spec, both stated honestly rather than faked:
"SHAP detail" is not implemented and cannot be, as currently designed. TreeSHAP requires a real trained tree-based meta-classifier for Fusion; Fusion is currently MAX-based (a logged §7 decision, not an oversight), so there is no SHAP to compute. The dashboard shows the real per-signal score breakdown (S1/Stage-1/S3/S2-fake per package) instead, explicitly labeled as such — not fabricated SHAP values standing in for the real thing.
Local server framework (left UNKNOWN between FastAPI/Express in the original spec) — resolved as FastAPI, to keep the whole stack in Python.
Hard rule preserved and structurally enforced: the dashboard only reads history.jsonl/config.json via GET endpoints, and the only write path (POST /api/config/shieldmax/{state}) is the explicitly-sanctioned Paranoid Mode toggle per §6 — no route exists that could gate, delay, or influence an install. Verified: toggling ShieldMax in the browser and confirming via packshield config show in a separate terminal that the same config file is read/written correctly by both surfaces.
Bug hit and fixed during this step (yours, not code-generated): a dependencies → ddependencies typo in pyproject.toml silently broke pip install -e .'s build step, which meant the ui command command was never actually installed despite the code existing — caught by checking packshield --help's command list directly rather than assuming the install succeeded.
Verified working end-to-end: packshield ui launches, opens a browser tab, shows real scan history (including the express/lodash BLOCK entries from earlier), and clicking a row renders that scan's full per-package signal breakdown from the new node_scores field.
Dashboard status: COMPLETE.
### Entry 25
Files created: packshield/dashboard/static/style.css, packshield/dashboard/static/app.js. Files rewritten: packshield/dashboard/static/index.html (SPA shell). Files changed: packshield/dashboard/server.py (added /api/shim_status).
What's real: hash-based client-side router across 7 pages; Overview and History/Settings carry full real functionality (History's tree-drill-down preserved exactly from the original dashboard); shim-armed status read live from shim_config.json; command palette (Ctrl+K) fuzzy-searches real scan history by package name.
Honestly labeled placeholders, not fake data: Live, Graph, Threats, Forensics pages show a clear "not yet built" message rather than errors or fabricated content — each names the real backend endpoint it will eventually use (/api/live_status, node_scores, /api/package/...), since that backend already exists from chunk A.
Real incident during this step, not a code bug: the PowerShell profile's pip override function (installed during the PATH-shim step) shadowed a broken packshield install, creating a chicken-and-egg failure where fixing packshield required pip, which required packshield. Resolved using python -m pip install -e . — bypasses the shim entirely, since that invocation was already known to be un-interceptable (documented limitation from the PATH-shim step, now also useful as a recovery path).
Chunk B status: COMPLETE.
### Entry 26
Files changed: packshield/live_status.py (rewritten — in-memory state instead of read-modify-write on the shared file, atomic writes via temp-file + os.replace, per-line elapsed-time stamps), packshield/resolver.py (rewritten — added optional progress callback, parallelized npm hash fetching via ThreadPoolExecutor), packshield/dashboard/server.py (rewritten — /api/live_status now reports file_age_seconds and retries transient read races; added a no-cache middleware for / and /static to prevent stale-JS bugs recurring), packshield/cli.py (moved start_scan to actually run before resolution; wired the new progress callback), packshield/dashboard/static/app.js (live-status polling rewritten with a visible diagnostic line: HTTP status, latency, file-age, stuck-scan warning).
Three real bugs found and fixed during this chunk, each confirmed with direct evidence before being called fixed, not guessed at:
Read-modify-write race: the dashboard polling the same file the CLI was writing caused occasional read failures inside live_status.py itself, silently resetting started_at and wiping the log — this is what made elapsed_seconds always report ~0 regardless of real scan duration. Fixed by moving all scan state into the CLI process's memory; the file is now write-only from the CLI's side.
Misplaced start_scan call: ended up positioned after finish_scan in cli.py (a hand-edit ordering slip), meaning the "scan in progress" state was never actually written before the slow resolution phase — the dashboard had nothing live to show during exactly the part that most needed live feedback. Fixed by moving it to run immediately before resolve_tree.
Stale served JS: added a Cache-Control: no-cache middleware after a ReferenceError traced back to the browser silently running an old cached app.js despite the file on disk being correct — normal refreshes weren't enough to bypass it.
Real performance finding, not just a bug fix: profiling via the new progress lines showed npm's integrity-hash fetching was a real bottleneck when run sequentially — parallelized to 8 concurrent fetches, same cache keys, no behavior change to any downstream signal.
Verified end-to-end: Live Scan page now shows real-time, timestamped progress (dry-run start → hash fetching progress → per-package Stage-1 scoring → final verdict) during an actual multi-minute npm install webpack run, not a jump straight to the finished state. Scan Replay (animating stored node_scores client-side) confirmed working separately, no backend dependency.
Chunk H (Live Scan + Replay) status: COMPLETE.
### Entry 27
Files changed: packshield/dashboard/static/app.js — renderForensics replaced from a placeholder into a full page (real S3 version history table, real cross-scan mentions table, deep-linkable via #/forensics/{pm}/{name}). History's "Worst Node" column and per-package tree-detail rows now link directly into Forensics for that package.
No backend changes needed — /api/package/{ecosystem}/{name} already existed from chunk A; this was a frontend-only build.
Honest labeling preserved: version history is explicitly captioned "from S3's stored diffs... not a full registry changelog" — it only shows versions this tool has actually scanned, not a complete history from the registry.
Chunk F (Package Forensics) status: COMPLETE.
### Entry 28

Files changed: packshield/dashboard/server.py (added /api/threats — buckets scans by inferred attack type using the same honest signal→T1-T4 mapping as /api/stats, per §2's own S1→T1/S2→T2/S3→T3/S4→T4 table). packshield/dashboard/static/app.js (renderThreats built out fully: a D3 radar chart plus an expandable matrix; each category drills down into the real scans behind it, linking into Package Forensics).
Honesty preserved: the page states plainly, in its subtitle, that this is "inferred from which signal produced each scan's worst score," not a real per-scan classifier. T5 (dependency confusion) is shown with an explicit note that it's out of scope and nothing counts toward it — not silently omitted, not faked as zero.
Chunk G (Threats) status: COMPLETE.
Dashboard: all 7 originally-planned pages (Overview, Live Scan+Replay, Dependency Graph, Threats, Package Forensics, History, Settings) are now built and confirmed working.
### Entry 29
### Entry — MalwareBench checkout and metadata verification

- Author: Codex
- Files changed: None.
- Safety: Read-only inspection only. No dataset code was executed, installed, restored, cleaned, or modified.
- Step A — npm Git state:
  The npm repository is on the current main branch, but Git reports approximately 1.5 million staged deletions and approximately 75,000 untracked paths. Core files, including npm_package_info.csv, are affected. This is an inconsistent working tree/index caused by the earlier failed checkout. No restore or clean command was run because the operation would materially alter the large external dataset.
- Step B — scoped npm path:
  The CSV example @ramp106/timetable@99.14.9 maps to packages/@ramp106/timetable/99.14.9. Git HEAD contains this exact path and package files. Its absence from the working tree is therefore a checkout-state problem, not a path-schema mismatch.
- Step C — PyPI metadata:
  The committed PyPI repository contains pypi_package_info.csv and pypi_file_info.txt, although both are absent from the working tree because they are staged as deleted. The committed PyPI CSV contains 10,609 rows: 5,135 malware and 5,474 false_positive. No unreviewed rows were observed.
- Network check:
  Direct git ls-remote access to GitHub failed because network access was unavailable. The local Git repositories and remote URLs were inspected instead.
- Decision:
  Do not build the unified dataset index from the current working trees. Recover or freshly re-clone the MalwareBench repositories first. The label sources and scoped-package path mapping are now confirmed from Git HEAD.
- Remaining:
  Choose a safe recovery path for the broken checkout, preferably a fresh clone into a new directory before ingestion.


### Entry 30

- Author: Codex
- Files changed: None in PackShield architecture.
- Dataset action: Created isolated checkout locations on the Desktop; original MalwareBench repositories were preserved.
- Network clone result: Remote clone began but stalled before receiving the repository pack. This was not treated as a confirmed authentication failure.
- Local clone result: Cloning from the existing local Git objects succeeded for both npm and PyPI repositories.
- Checkout result: Full Windows checkout failed because the dataset contains paths exceeding Windows filename limits and paths with trailing spaces, including the documented @bgrc/kyc-theme path.
- Recovery decision: Full materialization was stopped. Git histories and metadata remain available in the isolated S2 checkout. No destructive cleanup was run.
- Finding: Private dataset access is not the primary issue. Windows path handling and repository size are the immediate checkout limitations.
### Entry 31
S2 MalwareBench metadata consistency inspection

- Author: Codex
- Files changed: None.
- Safety: Read-only inspection; no package code was executed or installed.
- npm metadata: npm_package_info.csv contains 19,448 rows: 7,683 malware, 7,134 false_positive, and 4,631 unreviewed.
- PyPI metadata: pypi_package_info.csv exists in Git HEAD and contains 10,609 rows: 5,135 malware and 5,474 false_positive.
- Path mapping: Scoped npm paths use packages/@scope/name/version. PyPI paths use packages/name/version/artifact_id.
- Critical finding: Many metadata rows do not have corresponding package directories in the current Git HEAD. This is a repository snapshot/metadata mismatch in addition to the Windows checkout problem.
- Decision: Do not begin GraphCodeBERT training until a source-complete MalwareBench snapshot is obtained or the missing-source rows are explicitly handled.
### Entry 32
 S2 labeled dataset indexer

- Author: Codex
- Files created:
  - packshield/tools/prepare_s2_dataset.py
  - data/s2_malwarebench_index.jsonl
- Scope: S2 dataset preparation only. No other PackShield architecture was changed.
- Behavior:
  - Maps malware to malicious.
  - Maps false_positive to benign.
  - Drops unreviewed.
  - Supports npm scoped packages and PyPI artifact directories.
  - Reads metadata from the working tree or Git HEAD.
  - Records source_path and source_exists for every retained row.
  - Never executes, imports, installs, or runs dataset package code.
- Result:
  - 25,426 retained labeled rows.
  - 4,631 unreviewed rows dropped.
  - npm: 7,683 malicious, 7,134 benign.
  - PyPI: 5,135 malicious, 5,474 benign.
  - Present source directories: npm 391, PyPI 1,495.
  - Missing source directories are retained in the index and explicitly marked.
- Verification: prepare_s2_dataset.py passed Python bytecode compilation.
- Remaining blocker: Obtain a source-complete MalwareBench snapshot before feature extraction or GraphCodeBERT training.
### Entry 33
S2 source availability resolved through Git objects

- Author: Codex
- Files changed: None outside S2.
- Finding: Windows cannot fully materialize every MalwareBench path because of filename length and trailing-space limitations.
- Verification: Git HEAD still contains the package source paths for 14,817 labeled npm rows and 10,608 labeled PyPI rows.
- Decision: S2 dataset preparation will use filesystem paths when available and Git HEAD source paths when Windows checkout is incomplete.
- Result: Full checkout is no longer required for source availability.
- Remaining exception: One PyPI metadata row, requ-sts_requðµsts-0.1.0_tar-gz, has no matching source path and remains explicitly unavailable.
### Entry 34

- Author: Codex
- Files created:
  - packshield/tools/prepare_s2_dataset.py
  - data/s2_malwarebench_index.jsonl
- Scope: S2 dataset preparation only.
- Label policy:
  - malware -> malicious
  - false_positive -> benign
  - unreviewed -> excluded
- Final index:
  - 25,426 labeled rows
  - 12,818 malicious
  - 12,608 benign
  - 4,631 unreviewed rows excluded
  - npm: 14,817 usable rows
  - PyPI: 10,608 usable rows
- Each row records:
  - ecosystem
  - package name and version
  - artifact information
  - normalized label
  - filesystem source path
  - filesystem availability
  - Git source availability
  - original threat type
- Safety: No package code was executed, imported, installed, or run.
- Verification: The indexer passed Python compilation and the final index was regenerated successfully.
- Next S2 step: Build the source reader and GraphCodeBERT preprocessing layer from this index.

### Entry 35

- Author: Codex
- Scope: S2 dataset preparation only.
- Files created:
  - packshield/tools/prepare_s2_splits.py
  - data/s2_malwarebench_splits/
- Unified index updated:
  - Added attack_type_confidence=null because MalwareBench does not provide T1-T4 attack categories.
- Date check:
  MalwareBench metadata contains no publish-date fields. A temporal split is therefore unavailable and is not claimed.
- Split method:
  Seeded grouped stratified random split using seed 42. Groups are (ecosystem, name, version), preventing PyPI wheel and source-distribution variants of one release from crossing splits.
- Initial split attempt found one package-version group with conflicting benign and malicious labels. That group was excluded from every split rather than assigning an arbitrary label.

### Entry 36

- Author: Codex
- Final S2 dataset preparation result:
  - Indexed rows: 25,426
  - Malicious: 12,818
  - Benign: 12,608
  - Unreviewed rows excluded: 4,631
  - Conflicting-label rows excluded from splits: 2
- Split sizes:
  - Train: 17,824
  - Validation: 3,796
  - Test: 3,804
  - Train-balanced: 17,824
- Class balance:
  Overall malicious-to-benign ratio = 1.0167, so the dataset is not severely imbalanced.
  No random undersampling was applied. Full evaluation data was preserved.
- Verification:
  - Train, validation, and test package-version groups have zero overlap.
  - Both S2 preparation scripts pass Python compilation.
  - Split summary records temporal_split=false and date_fields_found=[].
- No non-S2 architecture was changed.

### Entry 37

- Author: Codex
- Scope: S2 dataset validation only.
- Encoding check:
  The only non-ASCII name/version in the labeled index is the PyPI row requ-sts_requðµsts-0.1.0_tar-gz.
- Raw-byte verification:
  The mojibake value is already present in the committed MalwareBench CSV bytes. It was not introduced by the PackShield CSV reader.
- Decision:
  Treat this as one malformed dataset row. Do not reinterpret or silently repair it.
- Result:
  It has no matching source path and remains explicitly unavailable. No broader encoding corruption was found in the indexed rows.

  ### Entry 38

- Author: Codex
- Files created:
  - packshield/signals/s2_git_source.py
  - packshield/tools/pilot_s2_source_parse.py
- Scope:
  S2 source access only. No non-S2 architecture was changed.
- Implementation:
  Added a Git archive reader that extracts only the requested package into a temporary directory.
- Safety:
  Package contents are only read and statically analyzed. No package code is imported, installed, or executed.
- Failure isolation:
  Windows-invalid archive members are skipped and reported per package instead of failing the entire dataset.
- Known-path verification:
  @bgrc/kyc-theme@9000.0.2 extracted successfully. Its trailing-space README.md file was skipped; source files remained available for analysis.

  ### Entry 39

- Author: Codex
- Pilot:
  Ran the Git archive plus existing S3 signature extraction pipeline on 100 packages: 50 malicious and 50 benign.
- Result:
  - 100/100 package runs completed successfully.
  - 2,610 source files analyzed.
  - 1,457 files reported parser errors by the existing AST parser.
  - No extraction-level failures occurred.
- Performance finding:
  Per-package Git archive calls were too slow at scale, so the pilot was changed to batch package paths into one archive per ecosystem.
- Safety:
  No dataset code was executed.
- Remaining:
  GraphCodeBERT-specific token and data-flow graph generation is not implemented yet.


  ### Entry 40

- Author: Codex
- Correction to previous split log:
  The earlier reported conflicting-label group was caused by omitting the npm scope from the grouping key.
  cli@1.0.1 and @shopware-docs/cli@1.0.1 are different packages, not conflicting labels.
- Fix:
  Split grouping now uses (ecosystem, scoped, name, version).
- Final split result:
  - Conflicting groups excluded: 0
  - Train: 17,838
  - Validation: 3,794
  - Test: 3,794
  - Train/validation/test group overlap: 0
  - train_balanced is identical to train because the class ratio is near 1:1.

  ### Entry 41

- Author: Codex
- Scope: S2 source preparation and pilot only.
- Files created:
  - packshield/signals/s2_git_source.py
  - packshield/tools/pilot_s2_source_parse.py
  - data/s2_malwarebench_pilot.json
- Implementation:
  Added per-package and batched Git archive extraction so S2 can read package source without a full Windows checkout.
- Safety:
  Extraction and analysis are static-only. No package code was executed, imported, installed, or run.
- Known-path test:
  @bgrc/kyc-theme@9000.0.2 extracted successfully. Its trailing-space README.md file was skipped; source files remained available.
- Pilot:
  100 packages processed successfully: 50 malicious and 50 benign.
  2,610 source files were analyzed.
  1,457 files reported parser errors from the existing AST parser.
  No archive extraction failures occurred.
- Performance:
  The pilot was changed from one Git archive process per package to one batched archive per ecosystem after the per-package approach proved too slow.
- Dependency check:
  torch, transformers, tree_sitter, and tree_sitter_languages are not installed. esprima is available.
- Remaining:
  Implement GraphCodeBERT-specific tokenization and data-flow graph generation after the required S2 preprocessing dependencies are available.


### Entry 42
 — S2 GraphCodeBERT feature extraction
- Implemented static Python and JavaScript source parsing and GraphCodeBERT token/data-flow feature generation, following Microsoft’s parser and clone-detection preprocessing.
- Kept optional dependencies S2-only; package samples are read as text and never executed.
- Pilot: 4 packages, 32 files; 30 successful feature vectors, 2 PyPI file-read errors. Feature vector dimensions and graph-link lengths were checked.
- Known limits: JavaScript DFG robustness needs further evaluation; TypeScript is skipped. Full-dataset extraction remains to be run.


### Entry 43 
— S2 extraction safety and status
- Full extraction paused after Defender reported three severe npm detections and quarantined temporary sample copies. An earlier PyPI pilot also caused a Defender detection. No sample code was installed or executed.
- Removed leftover S2 staging folders; no extractor process or staging folder remains. Renamed the partial output.
- Updated the S2 extractor to stream source bytes in memory and load the tokenizer from the local cache only.
- Full Step 4 output remains incomplete. The PyPI archive reader stalled during a benign-only pilot; continue in a disposable, network-isolated environment per the malware-handling requirement.

### Entry 44
Step 4 safety assessment: reviewed the S2 GraphCodeBERT feature extractor and Git source reader without running dataset samples or changing files.

The current extractor uses GraphCodeBERT’s Python and JavaScript data-flow routines and loads the tokenizer with local_files_only=True. Its active Git archive reader streams source bytes in memory instead of writing those package files to disk. However, this does not isolate the parsers: Python AST, Esprima, and Tree-sitter still process untrusted source on the host. The reader also has no explicit per-file size or processing-time limits. Older S2 materialization helpers write raw package files into temporary folders and must not be used for another run on this PC.

Safety decision: do not resume dataset feature extraction on the normal Windows host. A prior extraction run triggered Defender quarantine notifications for dataset samples, although no sample was installed or executed. The dataset directories and an interrupted feature-output file are present. Windows Sandbox’s executable was not found at its usual system path; availability of another disposable, offline VM remains unknown.

Next step: arrange a disposable isolated environment with networking disabled and no writable host-shared folders. Then harden the S2-only extraction path with file-size, package-size, and runtime limits before a small pilot. Keep the existing interrupted output separate and do not treat it as complete.


### Entry 45
Step 4 safety assessment: checked the S2 GraphCodeBERT extractor and available isolation options without running dataset samples or changing project files.

The feature extractor uses GraphCodeBERT’s Python and JavaScript data-flow routines and loads the tokenizer in local-only mode. Its current Git archive reader streams source bytes in memory, but parsing still occurs in-process, with no explicit source-size or runtime limits. Older S2 helpers can write raw samples to temporary folders and must not be used for another run on the host.

Isolation check: Windows reports a Home edition, Windows Sandbox is absent and is not supported on Home, and VirtualBox/VMware are not installed. The current shell is not elevated, so I cannot install virtualization drivers here. C: has about 172 GB free.

Safety decision: do not resume dataset extraction on the normal Windows host. A previous extraction caused Defender quarantine notifications, although no sample was installed or executed. Recommended next environment: a disposable VirtualBox VM with networking and host integrations disabled before dataset access. The user needs to install the VirtualBox base package and download an Ubuntu Server ISO first. No MalwareBench samples have been opened or processed in this step.



### Entry 46
S2 Step 4 safety update: corrected the risk assessment. Python ast.parse() and Esprima parse source without executing it. Tree-sitter is the native parser component of concern; malformed or pathological inputs can also cause crashes or excessive resource use.

S2-only hardening prepared: the Git source reader now rejects files larger than 2 MiB before reading them into memory. Feature extraction runs each file in a worker process with a 20-second parent-enforced timeout; the parent kills/restarts a timed-out or crashed worker and records the status. Removed S2 helpers that materialized raw package source in temporary directories. Replaced the old materializing pilot with a seeded GraphCodeBERT pilot selecting up to 13 packages for each ecosystem/label group (up to 52 total). Added Esprima to optional S2 requirements.

Docker pilot setup prepared under packshield/s2: trusted dependencies are built into an image before any dataset mount; runtime uses --network none, read-only Git-object/index/model-cache mounts, a read-only container filesystem, and one writable output mount. The container runs unprivileged with Linux capabilities dropped, no-new-privileges, and CPU/memory/PID/temp-storage limits. Tokenizer remains local-only. No Defender exclusions were added.

Encoding/path finding: the main S2 index stores the PyPI version as requÃ°Âµsts-0.1.0, but Git HEAD contains requðµsts-0.1.0, leaving that indexed row unavailable. The package tree has a requеsts module directory containing Cyrillic U+0435 (е), a confusable with ASCII e. The PyPI label CSV is absent from current Git HEAD, so the original point of encoding corruption cannot be established. The same visible mojibake markers appear in only this one row across the three generated indexes; this is not proof that every other metadata issue is absent.

Execution status: no package source was opened, parsed, or executed in this step. No pilot or tests were run. Docker is absent and WSL is not installed; enabling WSL requires administrator action and may require a restart. Continue only after Docker Desktop’s WSL2 engine is running.



### Entry 47 — S2 GraphCodeBERT feature extraction

**Scope and safety**

- Started S2 Step 4 feature extraction only. No non-S2 architecture or project documentation was edited; I’m providing this log for you to paste.
- Did not use Docker or create a Defender exclusion.
- Samples were read from committed Git objects with `git archive` and streamed through memory. No sample was installed, imported, or executed, and no package source was extracted to disk.
- Parsing used a separate worker process with a 2 MiB per-file size limit and a 20-second per-file timeout. The worker loads the GraphCodeBERT tokenizer from the existing local cache with `local_files_only=True`.
- This is direct host-side parsing, not a sandbox. Tree-sitter is native parser code, so the risk is reduced by not executing samples and by the worker limits, but it is not zero.

**Dataset and pipeline**

- Input index: `data/s2_malwarebench_index.jsonl`
- Source availability: 25,425 packages total — npm 14,817; PyPI 10,608.
- Label counts among those rows:
  - npm: 7,683 malicious, 7,134 benign
  - PyPI: 5,134 malicious, 5,474 benign
- Source reader: `packshield/signals/s2_git_source.py`. It reads package paths from each repository’s Git `HEAD`, accepts Python `.py` and JavaScript `.js`, `.mjs`, `.cjs`, `.jsx` files, and skips oversized or unsafe archive members.
- Feature builder: `packshield/signals/s2_graphcodebert_features.py`. The worker uses tree-sitter-based parsing and the locally cached tokenizer to emit GraphCodeBERT code tokens and data-flow graph fields.
- Driver: `packshield/tools/prepare_s2_graphcodebert_features.py`. It records per-file statuses such as `ok`, `parse_error`, `parse_timeout`, `file_too_large`, and `no_supported_source`.
- Pilot selector: `packshield/tools/pilot_s2_source_parse.py`.

**Balanced pilots completed and verified**

- npm pilot: 26 packages (13 malicious, 13 benign), 6,489 source-file records. Statuses: 5,009 `ok`, 1,479 `parse_error`, 1 `file_too_large`, and 2 `no_supported_source`. Its gzip output was fully readable.
  - Output: `data/s2_graphcodebert_npm_pilot_features.jsonl.gz`
  - Summary: `data/s2_graphcodebert_npm_pilot_summary.json`
- PyPI pilot: 26 packages (13 malicious, 13 benign), 1,514 source-file records; all 1,514 were `ok`. Its gzip output was fully readable.
  - Output: `data/s2_graphcodebert_pypi_pilot_features.jsonl.gz`
  - Summary: `data/s2_graphcodebert_pypi_pilot_summary.json`
- A smaller PyPI probe also completed: 1 malicious and 1 benign package, 41 source-file records, all `ok`.

**Full extraction attempts and recovery**

- Started full extraction with 20-package Git archive batches. It reached npm package 760, then stopped advancing. I preserved and salvaged the readable gzip prefix rather than treating the interrupted file as complete.
- The 760–780 source-available index slice was then processed separately, one package per archive. It completed with 1,659 file records plus one `no_supported_source` record.
- Processing the next segment with 20-package batches again stopped advancing. Its recoverable prefix contains 17,567 feature records. The following 20-package slice was processed separately, one package per archive; it completed with 20 records.
- A later 20-package batch produced no output and no process CPU change for about 20 minutes. It was stopped and preserved as an idle attempt. The remaining extraction was restarted with **one package per Git archive**, so progress is checkpointed package by package.
- Large packages can take several minutes; the 7,832-file package in one isolated batch completed. Per your instruction, let slow packages run rather than interrupting them just because they take time.

**Current active extraction**

- Process session: `30607`
- Progress at the latest check: **306 / 13,497 npm packages** in this remaining segment; 306 source-file records emitted. The segment then continues through its PyPI rows.
- Input: `data/s2_malwarebench_remaining_1320.jsonl`
- Output being written: `data/s2_malwarebench_graphcodebert_features_tail_1320_single.jsonl.gz`
- Command running:

```powershell
.venv\Scripts\python.exe -m packshield.tools.prepare_s2_graphcodebert_features `
  --index data\s2_malwarebench_remaining_1320.jsonl `
  --npm-root 'C:\Users\Veeresh\Desktop\MalwareBench\npm' `
  --pypi-root 'C:\Users\Veeresh\Desktop\MalwareBench\pypi' `
  --output data\s2_malwarebench_graphcodebert_features_tail_1320_single.jsonl.gz `
  --batch-size 1 `
  --max-file-bytes 2097152 `
  --file-timeout-seconds 20
```

The output file showed zero bytes while the active run was reporting package progress. Check it again after the process exits; do not treat its current size as final.

**For whoever continues**

1. First check whether session `30607` is still running. Do not start a duplicate extraction while it is active. In this task, continue polling that session; if continuing elsewhere, confirm the existing Python/Git processes and output before launching anything.
2. Let long individual packages finish. The one-package mode avoids the multi-package archive stall and reports progress after each package.
3. Once the active process exits, validate the completed gzip by reading every JSONL record through Python’s `gzip` module. Confirm it reaches end-of-stream without an error.
4. Before assembling a final dataset, reconcile all feature records against the source-available index using `(ecosystem, group_id, relative_file)`. Some interrupted prefixes may overlap the separately processed slices; do not concatenate them blindly.
5. Preserve incomplete files for recovery. The successful pilot files and complete isolated-batch files are valid; files named `incomplete`, `interrupted`, or `idle` are not final outputs.
6. After reconciling coverage, produce one final gzip feature file and record totals by ecosystem, label, and status.

**Relevant artifacts**

All paths below are under `C:\Users\Veeresh\Desktop\packshield\data\`.

- Valid pilots: `s2_graphcodebert_npm_pilot_features.jsonl.gz`, `s2_graphcodebert_pypi_pilot_features.jsonl.gz`
- Salvaged prefixes and isolated batches: `s2_malwarebench_graphcodebert_features.prefix.jsonl.gz`, `s2_malwarebench_graphcodebert_batch_0760_0780.jsonl.gz`, `s2_malwarebench_graphcodebert_features_remaining.prefix.jsonl.gz`, `s2_malwarebench_graphcodebert_batch_0520_0540.jsonl.gz`
- Current active output: `s2_malwarebench_graphcodebert_features_tail_1320_single.jsonl.gz`
- Interrupted/idle attempts to preserve but not treat as final: `s2_malwarebench_graphcodebert_features.full_run_interrupted.jsonl.gz`, `s2_malwarebench_graphcodebert_features_remaining.interrupted_0520.jsonl.gz`, `s2_malwarebench_graphcodebert_features_tail_1320_batch20_idle.jsonl.gz`, and `s2_graphcodebert_direct_pilot_features.incomplete.jsonl.gz`

### Entry 47
 Scope and safety

- Work is limited to S2. No other architecture was intentionally changed.
- MalwareBench files are read from local Git repositories using `git archive`; package files are not extracted into the working tree, installed, imported, or executed.
- npm source extensions: `.js`, `.mjs`, `.cjs`, `.jsx`. PyPI source extension: `.py`.
- Feature parsing uses tree-sitter and the locally cached GraphCodeBERT tokenizer (`local_files_only=True`).
- Per-file size limit: 2 MiB. Parser worker timeout: 20 seconds; worker startup timeout: 180 seconds.
- This runs on the host and is not an OS sandbox or Docker container. No Defender exclusion was added.
- Preserve the original incomplete/interrupted files. Do not treat them as final datasets.

 S2 code changed

- Modified `packshield/tools/prepare_s2_graphcodebert_features.py` to write feature records as they are processed rather than holding a whole batch in memory.
- It flushes compressed output every 100 records and after each package batch. The current run uses batch size 1, so each completed package is a checkpoint.
- Added `packshield/tools/run_s2_extraction_parallel.py` to partition an index across four extractor processes, keep per-shard logs, and merge outputs only after every shard exits successfully.
- Shards are balanced by metadata `total_file`, then ordered from smaller to larger packages so results can be committed earlier.
- The runner reports progress periodically and terminates its direct child processes if interrupted. Check for leftover parser or Git child processes when stopping it.

 Inputs and recovery

- The original remaining tail was `data/s2_malwarebench_remaining_1320.jsonl` with 24,105 package rows.
- The first parallel attempt used batches of 20. It ran for roughly 90 minutes; shard 02 completed 20 npm packages and logged 61,251 source files, but its gzip was interrupted.
- Salvaged 61,235 valid JSON records for those 20 packages to:
  `data/s2_graphcodebert_parallel_1320/shard_02.prefix_salvaged.jsonl.gz`
- Salvage counts: 57,152 `ok`, 4,054 `parse_error`, 19 `parse_timeout`, 10 `file_too_large`. Sixteen incomplete records were discarded.
- The recovered 20 package IDs were checked against shard 02’s first 20 npm rows and removed from the resume index to avoid reprocessing:
  `data/s2_malwarebench_remaining_1320_after_recovery.jsonl`
- Earlier extraction artifacts for the first 1,320 rows remain in `data/`. The interrupted run did not overwrite them.

 Current run

- Runner session ID: `49442`.
- Output directory: `data/s2_graphcodebert_parallel_1320_streaming/`
- Four shard indexes: `shard_00.jsonl` through `shard_03.jsonl`
- Four logs: `shard_00.log` through `shard_03.log`
- Four compressed outputs: `shard_00.jsonl.gz` through `shard_03.jsonl.gz`
- Intended runner merge: `features_parallel.jsonl.gz`
- Command used:

  `.venv\\Scripts\\python.exe -u -m packshield.tools.run_s2_extraction_parallel --index data\\s2_malwarebench_remaining_1320_after_recovery.jsonl --npm-root C:\\Users\\Veeresh\\Desktop\\MalwareBench\\npm --pypi-root C:\\Users\\Veeresh\\Desktop\\MalwareBench\\pypi --output-dir data\\s2_graphcodebert_parallel_1320_streaming --project-root C:\\Users\\Veeresh\\Desktop\\packshield --workers 4 --batch-size 1 --poll-seconds 30`

- Shard input sizes: 6,020; 6,021; 6,022; 6,022 packages (24,085 total).
- Last saved progress:
  - shard 00: npm 1,358 / 3,366; 1,297 source files; log/output last modified 22:30
  - shard 01: npm 233 / 3,383; 88 source files; last modified 20:33
  - shard 02: npm 514 / 3,366; 367 source files; last modified 20:54
  - shard 03: npm 231 / 3,362; 87 source files; last modified 20:32
- Current logged npm progress totals 2,336 / 13,477. PyPI has not started.
- Including the earlier 1,320 rows and 20 salvaged packages, the nominal total processed is 3,676 / 25,425. Treat this as an estimate until a coverage audit reconciles every output package ID.

 Process check

- Runner child PIDs 18,776; 21,140; 9,880; 19,556 still exist, but had near-zero CPU.
- Git/parser processes also remained. A 10-second CPU comparison showed no CPU increase; shard logs and outputs had not advanced since the times above.
- Therefore the processes are alive, but useful progress is not confirmed. The open shard gzip files are partial outputs and must not be merged as final.

 Continuation steps

1. Recheck the shard logs, output timestamps, runner session, and matching Git/parser processes. A living wrapper PID alone does not prove progress.
2. If the run remains stalled, preserve its current files before stopping anything. Check and stop only processes belonging to this S2 run; verify there are no orphan Git or parser workers.
3. Recover only complete JSONL records from interrupted gzip prefixes, validate package IDs, and exclude those IDs from the next resume index. Do not overwrite a shard output containing recovered work.
4. Resume with package-sized batches and incremental flushing. Use a fresh output directory unless the resume indexes explicitly exclude every package already saved in the existing shard outputs.
5. After all shards exit successfully, validate each gzip fully, reconcile package IDs and statuses against the 25,425-row S2 index, then merge the recovered prefix, current shards, and earlier saved prefixes without duplicates.