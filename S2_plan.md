PackShield — S2 Implementation Plan

Context for any agent picking this up: PackShield is a npm/pip install-time security shim. S1 (name similarity), S3 (update-diff), S4 (publisher reputation) are complete and live. Stage-1 fusion (HistGradientBoostingClassifier on S1+S4, combined with S3 via per-node MAX) is trained and deployed. Tree-level MAX propagation, verdict/enforcement (BLOCK/WARN/ALLOW), history.jsonl, ShieldMax, config, PATH-shim, and a full dashboard are all built and confirmed working. S2 is the only remaining component. It currently exists only as packshield/signals/s2_fake_stub.py — a deterministic hash-based placeholder, explicitly labeled fake everywhere in logs/UI ("s2_is_fake": true), built specifically so the rest of the pipeline could be developed and tested against a stand-in before S2 itself existed.

Do not confuse S2 with GraphSAGE. S2 = GraphCodeBERT, operating on one package's own code (AST + dataflow graph). GraphSAGE is a separate, stretch-goal component operating on the resolved dependency tree for risk propagation — not built, not MVP, never to be merged with S2 in naming, code, or documentation. Calling anything "GraphSAGECodeBERT" is explicitly wrong per PROJECT.md §10.

1. Architecture recap (where S2 sits)
Stage 1 (always runs, every package in tree): S1 + S3 + S4 → combined via MAX
         ↓
Tree-level MAX propagation across all packages in the resolved tree
         ↓
Escalation gate: tree-max Stage-1 ≥ 4/10  OR  --shieldmax / config.json / `shieldmax` prefix command
         ↓
Stage 2 (conditional): S2
  ├─ static GraphCodeBERT pass (always, once escalated)
  └─ sandboxed dynamic dry-run (only if static pass is inconclusive — NOT built yet, see §6)
         ↓
Final verdict = MAX(Stage-1 tree-max, S2 tree-max) → BLOCK (≥8.5) / WARN (5.0–8.5) / ALLOW (<5.0)

S2 replaces run_fake_s2(name, version, ecosystem) in packshield/cli.py's run_pipeline. The gating logic itself is already correct and tested — this plan only needs to produce a real score where the fake stub currently returns a deterministic hash.

2. Dataset: MalwareBench

Source: https://github.com/MalwareBench (separate npm and presumably pypi repos; Google Form access already granted). Academic dataset (Nair et al., MSR 2024), ~20,792 packages total, ~6,659 malicious, npm + PyPI, ships actual package files on disk (not just pre-extracted summary features like the earlier CLAMPD dataset was) — this is why it was chosen over CLAMPD for S2 specifically: GraphCodeBERT needs real source code to build AST/dataflow input from, and CLAMPD only had numeric summary stats.

Status as of this plan: the npm repo (6.15 GiB) has been cloned locally on Windows. The checkout partially failed on a path containing a trailing space (packages/@bgrc/kyc-theme/9000.0.2/README.md ) — a Windows/NTFS path-safety rejection, not a corrupted download. Resolution in progress: git config core.protectNTFS false then git checkout ., or a clean re-clone with that config set beforehand. Whoever continues this work should first confirm the full checkout succeeded (git status should show a clean working tree, no "needs merge"/partial-checkout warnings) before proceeding to inspection.

Next concrete step, not yet done by anyone: inspect the actual on-disk layout before writing any ingestion code. Specifically needed:

Top-level folder structure (Get-ChildItem -Recurse -Depth 2).
Whatever labels/metadata file maps package names/versions to malicious/benign status — likely a CSV or JSON at the repo root. This file's exact schema is currently unknown and must be inspected, not assumed — this project has repeatedly hit real bugs from guessing dataset schemas instead of inspecting them first (e.g. the S4 s4_registry_status leakage bug, the CLAMPD/Datadog schema mismatches).
The internal structure of one sample package folder — confirm whether it's raw unpacked source (ideal — direct AST input) or still-packed tarballs/wheels (needs an extraction step, same safe no-execution extraction pattern already built in packshield/signals/s3_fetch.py — reuse that code, don't rewrite it).

Do not execute, install, or run any code from this dataset directly. Per PROJECT.md §9's malware handling policy: isolated environment, no network egress, inspect via static file reads only (view/cat/AST parsing), never npm install/pip install/python <file> on a sample.

3. Dataset preparation pipeline (build this first, before any model work)

Once the real schema is confirmed (§2), build:

3a. A unified labeled index — one row per (ecosystem, name, version, label, source_path), analogous in spirit to the s1_s4_name_metadata_dataset.jsonl format already used for Stage-1, but pointing at real source trees instead of carrying pre-computed features. Reuse the existing honest-labeling conventions from that earlier work: label ∈ {malicious, benign}, plus attack_type_confidence if MalwareBench's own labels indicate T1–T4 breakdown (check for this — if MalwareBench labels by attack category, that's a strictly better source than this project's own earlier manual T1–T4 inference work on the Stage-1 dataset, and should be preferred).

3b. Train/validation/test split. Per PROJECT.md §9, a temporal split is preferred where possible. Check whether MalwareBench's metadata includes publish dates — if yes, use them for a real past/future split (finally satisfying the §9 requirement that Stage-1's dataset never could, since Stage-1's original fetch tools didn't log timestamps until after the fact — see PROJECT.md log entry on the temporal-split fix). If MalwareBench has no dates, fall back to stratified random split with the same honesty as Stage-1's: state plainly in the log that it's not temporal, don't claim otherwise.

3c. Class balance check. Stage-1's dataset work repeatedly hit severe imbalance problems (pypi malicious:benign was once 15:1 the wrong direction) that needed real fixing, not just noting. Compute the actual malicious:benign ratio in MalwareBench immediately after loading the index, before building anything downstream. If it's badly skewed, apply the same honest pattern used before: keep the full set for evaluation, build a separate balanced subset for training via seeded random undersampling — never silently drop data, never fabricate synthetic minority examples.

4. Feature extraction: AST + dataflow graph construction

This is the actual GraphCodeBERT input-preparation step, separate from dataset loading.

4a. Per-ecosystem parsing, reusing existing project infrastructure:

pip/Python files: stdlib ast module — already used and self-tested in packshield/signals/s3_signature.py. The AST-walking logic there (risky-call detection) is a different purpose than GraphCodeBERT's input format, but the underlying ast.parse() call and file-walking logic can be reused/adapted rather than rewritten from scratch.
npm/JavaScript files: esprima — already integrated and smoke-tested in the same file. Same reuse principle applies.

4b. GraphCodeBERT-specific input format. Unlike S3's use of the AST (which only needs call-site/import detection), GraphCodeBERT requires a specific tokenized-code + dataflow-graph input format matching its pretraining — this must be built fresh, following the dataflow-graph extraction procedure from the original GraphCodeBERT paper (Guo et al., 2021) and its official microsoft/CodeBERT repo's data preprocessing scripts for whichever downstream task most resembles binary malicious-code classification. Action item for whoever implements this: check that repo's GraphCodeBERT/clonedetection or similar classification-task example first — don't reinvent the dataflow-edge-extraction algorithm from the paper's math alone if reference code already exists.

4c. Known limitation to carry forward honestly: GraphCodeBERT's pretraining dataflow extraction has mature tooling for a specific set of languages (Python, Java, Go, PHP, JS, Ruby — per the original paper). JavaScript support exists but may be less robust than Python's in the reference implementation — flag this explicitly in whatever log entry documents this step, don't assume parity between the two ecosystems' pipelines without checking.

5. Model: GraphCodeBERT fine-tuning

5a. Starting checkpoint: a pretrained GraphCodeBERT checkpoint (Hugging Face: microsoft/graphcodebert-base), per PROJECT.md §7's explicit choice over plain CodeBERT (dated, lacks dataflow structure) — this is a settled decision, not open for re-litigation.

5b. Fine-tuning approach, per PROJECT.md §7: frozen lower layers, fine-tune only the top 2–3 transformer layers plus a new classification head (binary: malicious/benign). This is explicitly not full fine-tuning from scratch — stated as a time/compute-budget decision already made.

5c. Compute requirement, per PROJECT.md §7 and this project's own earlier cost research: GPU required. Budget estimate from §7: minutes to under an hour for the actual fine-tuning step itself, but the real time cost is the S2 sandbox infrastructure build, not model training time — don't under-budget the non-ML engineering work around this. Earlier cost research in this project (rented RTX 3090/4090-class GPU via RunPod/Vast.ai, ~$0.20–0.40/hr) remains the recommended path — a MacBook M4's MPS backend can run this but is meaningfully slower than cheap rented CUDA hardware for transformer fine-tuning, and at these prices renting is a clear win over burning the new laptop's time/battery.

5d. Evaluation metric, consistent with Stage-1's own precedent: recall at a fixed low FPR (not raw accuracy), reported per attack-type breakdown where labels allow it, exactly as Stage-1's train_stage1.py already does. Reuse that evaluation methodology/code pattern rather than inventing a new one — consistency across the two models' reported numbers matters for the eventual IEEE paper.

5e. Output artifact: a saved fine-tuned model (e.g. data/stage2_graphcodebert_model/, analogous to data/stage1_model.joblib's role) that packshield/signals/s2_real.py (new file, replacing the fake stub's import in cli.py) loads and calls at inference time.

6. Sandboxed dynamic dry-run (the second half of S2, lower priority)

Per PROJECT.md §5/§7: static GraphCodeBERT pass runs first; sandboxed dynamic dry-run only if the static pass is inconclusive. This is explicitly a two-tier design, not optional complexity — but the static pass alone is a legitimate, complete MVP milestone on its own. Recommended sequencing: build and ship the static GraphCodeBERT path fully (§§2–5 above) before starting this section at all. Don't let sandbox-infrastructure scope creep delay getting a real static S2 score into production, replacing the fake stub.

When this section is tackled:

Hard requirement, non-negotiable per §9's safety posture: isolated execution (container, restricted subprocess, or a JS isolate like vm2), no network egress, matching the same safety principle already enforced in packshield/signals/s3_fetch.py (no-script-execution source fetching) — but this time the opposite: controlled execution is the point, just fully network-isolated and sandboxed.
This is itself an attack surface — PROJECT.md explicitly flags "detector-as-attack-surface (S2 parses/executes untrusted code)" as a real risk, addressed by the sandbox design, not dismissed. Do not simplify this away "for convenience" during implementation — that's an explicit instruction in the original spec.
Hosting/infra for this is UNKNOWN per §11 — not decided yet whether this runs locally or needs cloud-side sandboxing for scale. This decision should be made explicitly and logged, not defaulted into silently.
7. Integration back into the live pipeline

Once a real S2 score exists (static-only is sufficient to start this):

Create packshield/signals/s2_real.py with a run_real_s2(name, version, ecosystem) function matching the same return shape as run_fake_s2 in packshield/signals/s2_fake_stub.py (an S2Result-like object with .score and .reasons), so the swap in cli.py is a minimal, low-risk change.
In packshield/cli.py, change the import and the call site inside run_pipeline's escalation branch from run_fake_s2(...) to the new real function. Do not delete s2_fake_stub.py — keep it available for local dev/testing without GPU access, but it must never be the default import path once real S2 exists.
Update every "s2_is_fake": True occurrence in run_pipeline's history_entry dict to reflect reality — this should become False once real S2 is wired in, and this change is exactly why that field was built as an explicit boolean rather than an assumption baked into the dashboard: the dashboard's fake-badge/sim-badge UI elements key off this field and will automatically stop showing "fake stub" labels once it flips, with no dashboard code changes needed.
Retrain/re-evaluate the Fusion layer's assumptions. Per PROJECT.md §7's own logged caveat: "a real fusion model — trained or rule-based — must be revisited once real S2 exists; training against the current fake stub's output would teach nothing real about S2's actual signal." The current MAX(Stage-1, S2) rule-based fusion may still be the right call even with real S2 (same reasoning as before: no leakage risk, transparent, easy to tune) — but this should be an explicit decision made with real S2 score distributions in hand, not assumed to carry over unchanged.
Re-run the same real-world validation pattern already used for S1/S3/S4: test against express, lodash, and ideally one of the real historical incidents already validated for S3 (ua-parser-js, coa, rc — their actual malicious code is still available via the reconstruction method documented in the S3 validation step) to sanity-check real S2 scores against known-good and known-bad packages before trusting it in production.
8. Honesty/logging requirements throughout (carry the project's existing standard forward)

Every step above should be logged into PROJECT.md following the exact pattern used for every prior signal: what's real vs. stubbed, what simplifications were made and why, what bugs were found and how they were confirmed before being called fixed. This project's defining characteristic so far has been catching and correctly diagnosing real bugs (the S4 leakage bug, the S3 version-store corruption bug, the live-status race condition, the PATH-shim System/User PATH ordering issue) rather than assuming things work — S2 should be held to the identical standard, especially given it's the component most likely to be built by a different agent with no memory of these earlier lessons.