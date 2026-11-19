> **Status: Historical Record — Superseded by V6 Release Audit.** This document preserves the earlier experiment's protocol, evidence, and conclusions as recorded at the time. It is retained for the research chronology; use the [V6 four-way results](v6-four-way-200-results.md) and [V6 strict-depth-4 protocol](v6-strict-depth4-preflight-protocol.md) for the current release-level synthetic evaluation.

# ESQ-DSL v4 — candidate-ranking result and CEGIS audit

**Date:** 16 November 2026  
**Project:** P6 / ESQ-DSL  
**Branch:** `p6/esq-dsl-v4-adaptive-cegis-2026-11-16`  
**Tracking:** [Issue #19](https://github.com/Kshitijpalsinghtomar/research/issues/19)  
**Protocol and audit correction:** [CEGIS metric audit and disposition](#3-cegis-metric-audit-and-disposition)

## Executive result

The v4 tree candidate evaluator was trained and evaluated against v3 on two previously unused ExeDec DeepCoder cohorts. The **candidate-only** comparison is retained: v4 reached 327/371 (88.14%) complete fresh-behaviour matches and 93.23% weighted fresh-case accuracy, versus 320/371 (86.25%) and 92.22% for v3.

This is not a uniform improvement. V4 candidate ranking improved the ADD_OP_FUNCTIONALITY cohort but regressed on NONE. The old reported one-turn CEGIS result is now superseded: a post-run audit found that hidden-reference validity filtered the query pool before the CEGIS selector chose a query. That gave the query selector target-dependent information. The old 344/371 and 95.19% CEGIS headline therefore **must not be treated as confirmatory evidence**.

The CEGIS query/oracle boundary has been corrected in code and regression-tested. No corrected CEGIS efficacy result is claimed, and no rerun on the two consumed cohorts is authorized.

## 1. What was built

### 1.1 Tree-aware candidate evaluator

The v3 model contained a task-conditioned tree GRU/head for candidate program trees, but the v3 training loop did not train that pathway and the evaluator did not use it. V4 trained the candidate-scoring pathway and applied it only to final exact-fit candidates.

Training supervision:
- 100k ExeDec-aligned synthetic task corpus; one selected task per structural family.
- 20,000 train families, 2,500 development families, and 2,500 sealed synthetic confirmation families.
- Each selected task contributed its true program and up to two type-compatible one-edit mutants, retained only when they exactly reproduced all three visible examples.
- Candidate labels measured agreement with the target program on 16 deterministic fresh inputs drawn from each task's own input specification.
- 37,703 visible-exact mutants were produced across the 25,000 selected family tasks; 83.664% of tasks had at least one visible-exact alternative.
- Synthetic confirmation families were not used by the optimizer or for model selection.

Model:
- ESQSetEncoder, 137,897 parameters.
- Only the tree-scoring pathway was fine-tuned; task encoder and operator/lambda/length heads were frozen.
- Five epochs, batch 128, AdamW learning rate 3e-4, seed 20261117, CPU.
- Synthetic development candidate top-1 mean behavioural agreement: 0.92151 versus 0.91159 for the static command-prior ranker.
- Pairwise ranking accuracy: 55.33%; Spearman: 0.1515; candidate MAE: 0.13156; MSE: 0.03539.
- Checkpoint SHA-256: `b24c86b77e56375a08e2ed37e9a607ebd7a6dd6333e16ec91405603c84d810d2`.

This is a modest ranking improvement on synthetic development families, not a calibrated probability model.

### 1.2 Partial-state scoring was rejected as the default

The development ablation invoking tree scoring on partial states increased truncation from 36 to 63 tasks and reduced complete fresh-behaviour matches from 146 to 144 on the already-consumed SWITCH development set. Mean latency also increased. The frozen candidate-only method therefore uses tree scoring only for final exact-fit candidates. It does not prune or alter the exact execution-signature quotient.

### 1.3 Oracle CEGIS software

The session implementation:
1. Maintains only programs that exactly fit every visible example.
2. Proposes a maximum-disagreement input when several hypotheses remain, or a novel validation input when one remains.
3. Marks proposals `oracle_required=true` and leaves expected output unset.
4. Accepts an expected output only from an explicit oracle.
5. Adds an answered counterexample, removes only hypotheses that fail exact interpreter execution, and re-synthesizes if the pool is emptied.
6. Records unresolved states instead of restoring disproved hypotheses.

The code review found that the **old offline evaluator did not respect this boundary when choosing a query**. It generated a deterministic pool, ran the hidden reference program on every pool item, discarded items for which the hidden reference returned no valid output, and only then asked the session to select the most discriminating item. Thus, although candidate generation was properly frozen before hidden-reference access, hidden-target validity influenced query selection.

The fix now:
- passes the complete deterministic pool to the query selector;
- creates the pending `oracle_required` proposal before invoking the simulated oracle callback;
- asks the oracle only about the selected input;
- records an unavailable response as `oracle_query_unanswered`, clearing the pending request but leaving candidates and visible examples unchanged; and
- reports attempted queries separately from valid oracle answers.

## 2. Candidate-only confirmation protocol and results

Both input datasets were frozen from ExeDec commit `ef046ce2cc3fcd024e32f5dfe00e69700dac82ed`. Candidate generation used only task index, visible inputs, and three visible outputs. Both candidate files were SHA-256 locked before hidden-reference scoring.

| Dataset | Tasks | Raw SHA-256 |
|---|---:|---|
| ADD_OP_FUNCTIONALITY | 200 | `dda8cf12e3b2b32d1406a20e44c5681f7930b5d0493363d9cc17d58bf4f12663` |
| NONE | 200 | `64ad0f41cbcec0e8508e280e9fcfb9f4f4836c2bcc0275779c4920d5d312f3d8` |

Candidate-generation settings: max 4 operators, 10,000 signatures, 300 ms per task per system, top-3 exact-fit portfolio, `strict_intermediates=False`. V4 candidate model inference and scoring were included in its budget. Fresh evaluation used 50 deterministic inputs/task; eligibility required at least 25 valid reference outputs. All 400 reference programs replayed the three visible examples.

### 2.1 ADD_OP_FUNCTIONALITY

| Metric | v3 | v4 candidate-only |
|---|---:|---:|
| Visible exact-fit tasks | 182 | 187 |
| Complete fresh-behaviour matches | 159/182 (87.36%) | 168/182 (92.31%) |
| Fresh-case accuracy | 92.84% | 95.81% |
| Search truncation | 33 | 42 |
| Mean candidate-generation latency | 88.94 ms | 104.21 ms |

### 2.2 NONE

| Metric | v3 | v4 candidate-only |
|---|---:|---:|
| Visible exact-fit tasks | 182 | 183 |
| Complete fresh-behaviour matches | 161/189 (85.19%) | 159/189 (84.13%) |
| Fresh-case accuracy | 91.62% | 90.78% |
| Search truncation | 29 | 40 |
| Mean candidate-generation latency | 82.06 ms | 105.35 ms |

### 2.3 Combined candidate-only comparison

| System | Complete fresh-behaviour matches | Rate over 371 eligible tasks | Weighted fresh-case accuracy |
|---|---:|---:|---:|
| v3 learned operation priority | 320/371 | 86.25% | 92.22% |
| v4 tree candidate ranker, no oracle | 327/371 | 88.14% | 93.23% |

The v4 ranker adds measured latency and is not better on every cohort. Its value remains an experimental ranking component, not a replacement for the exact symbolic core.

## 3. CEGIS metric audit and disposition

The previous version of this report recorded:
- 344/371 complete fresh-behaviour matches after one-turn CEGIS;
- 95.19% weighted fresh-case accuracy;
- 370 simulated oracle answers across 400 tasks;
- 17 recovered full-match tasks over candidate-only v4.

Those outputs are preserved in the historical JSON and compressed transcripts for traceability, but they are **not valid confirmatory evidence**. The hidden reference was used to pre-filter the candidate query pool by output validity before the query-selection rule ran. This is target-dependent query selection, not a clean oracle-assisted interaction.

The corrected implementation passed a focused regression that verifies:
- the query is selected from the complete pool before the oracle callback runs;
- the selected input is the one sent to the oracle;
- a missing oracle answer is recorded as unanswered; and
- candidates and visible examples remain unchanged when no output is available.

The corrected CEGIS workflow was subsequently run on a separately frozen, family-held-out synthetic cohort. The official ADD_OP_FUNCTIONALITY and NONE cohorts remain consumed and were not rerun. The synthetic result, its limits, and artifact hashes are recorded in Section 6 and `CEGIS_SYNTH_CONFIRMATION_PROTOCOL.md`.

## 4. Reproducibility and tests

- V4 checkpoint SHA-256: `b24c86b77e56375a08e2ed37e9a607ebd7a6dd6333e16ec91405603c84d810d2`.
- Base v3 checkpoint SHA-256: `1e5e086f0489c303475d4a0eee0e53a1360e1f888cf7cbb009ed9c9e55bba81c`.
- Dataset locks, candidate hashes, per-task head-to-head outputs, historical CEGIS transcripts, and artifact packing hashes remain under `results/`.
- Corrected Deepnote verification: **13/13 v4 tests passed; 7/7 v3 regression tests passed;** `py_compile` passed for `esq_cegis.py`, `esq_cegis_eval_v4.py`, `esq_v4.py`, and `esq_eval_v4.py`.
- No paid LLM or model API was used.

## 5. Interpretation and next work

The strongest valid v4 evidence is the candidate-only comparison. It shows a small aggregate improvement over v3 but not a uniform cohort improvement, and it adds latency. The CEGIS implementation now enforces the intended oracle boundary in its tested code path, but the corrected workflow has no valid new efficacy result.

Next research step: move from the simulated oracle to an explicit authorized oracle interface (user-provided expected output or a real test harness/runtime), while preserving the same proposal-before-answer and query/evaluation disjointness invariants. Do not retune on the completed synthetic cohort or the consumed ExeDec cohorts.

No novelty, SOTA, general-purpose program synthesis, or publication-readiness claim is implied.


## 6. Family-held-out synthetic confirmation — corrected CEGIS

A separate 3,008-task synthetic cohort was evaluated after the CEGIS query boundary was corrected. The cohort consists of the remaining structural confirmation families from the original v3 100k ExeDec-aligned synthetic corpus after excluding the 2,500 family tasks selected for v4 candidate-supervision preparation. There is zero family overlap with v3 training/development families or v4 candidate-supervision families.

This is family-held-out from model fitting, development diagnostics, and the v4 candidate-supervision sample, but it is generated from the same pinned task generator. It is **not** an official ExeDec external benchmark.

### 6.1 Freeze and information boundary

- Total cohort: 3,008 tasks, one task per structural family.
- Eligible tasks: 1,751 (at least 25 valid hidden-reference outputs among 50 fresh inputs).
- Valid fresh evaluation cases: 87,734.
- Reference visible replay: 3,008/3,008.
- Candidate generation saw only task index, visible inputs, and visible outputs; the freeze manifest records `hidden_programs_read=false`.
- Candidate portfolio SHA-256: `ff1a981639982e1d22d6c4bb07df1783e6eb38d86524eb322dbd39f4e663988b`.
- Visible projection SHA-256: `b775dca8aa809bbe2be425b909808057ee00642daefc67362ffabb1086822ec1`.
- Target-bearing raw cohort SHA-256: `c1690c8f5efe9da6c54d1c6f6622ddb76dbadd7211c767d3a801abe58258c4aa`.
- V3 model SHA-256: `1e5e086f0489c303475d4a0eee0e53a1360e1f888cf7cbb009ed9c9e55bba81c`.
- V4 model SHA-256: `b24c86b77e56375a08e2ed37e9a607ebd7a6dd6333e16ec91405603c84d810d2`.

The full deterministic CEGIS query pool was made disjoint from the 50 fresh-evaluation inputs and visible examples. Candidate disagreement selected the query before the oracle callback. The simulated hidden reference was called only for the selected pending query; missing target outputs were recorded as unanswered.

### 6.2 Candidate-only and CEGIS results

| System | Complete fresh-behaviour matches | Rate over 1,751 eligible tasks | Fresh-case accuracy |
|---|---:|---:|---:|
| V3 priority-order baseline | 428/1,751 | 24.44% | 62.54% |
| V4 candidate ranker only | 423/1,751 | 24.16% | 62.50% |
| V4 + one-turn corrected CEGIS | **556/1,751** | **31.75%** | **66.98%** |

The tree candidate ranker alone did not beat v3 on this cohort. The one-turn CEGIS stage recovered 139 tasks that were not initially full matches, while 6 initially full matches degraded; net change over candidate-only v4 was +133 complete tasks. Fresh-case accuracy rose by 4.49 percentage points over candidate-only v4.

This is a positive bounded result for the oracle-assisted loop on this synthetic family-held-out cohort, not a stand-alone neural synthesis result.

### 6.3 Oracle and recovery accounting

| Measure | Result |
|---|---:|
| Query attempts | 2,805 |
| Valid simulated-oracle answers | 1,583 |
| Unanswered queries (no valid target output) | 1,222 |
| Tasks resolved to one active candidate | 1,644 |
| Bounded re-synthesis calls | 519 |
| Truncated re-synthesis calls | 183 |
| Empty candidate pools after re-synthesis | 93 |
| Mean final active candidates (non-empty sessions) | 1.559 |

The unanswered queries are not silently dropped: they remain recorded and do not change candidate state or visible examples. The non-zero degradation count, truncations, and empty pools show that the one-turn process is not a monotonic guarantee.

### 6.4 Artifact and claim boundary

The compressed candidate portfolios, head-to-head task records, CEGIS transcripts, raw/visible cohort files, cohort lock, and summaries are archived under `experiments/P6_ESQ_V4/results/CEGIS_SYNTH_CONFIRMATION/`. The checksum manifest is `experiments/P6_ESQ_V4/results/CEGIS_SYNTH_CONFIRMATION_artifact_manifest.json`. Each logical artifact is stored as base64(gzip) text split into ordered `.partNNN` files; concatenate the parts in lexical order, base64-decode, then gzip-decompress. Verify raw and compressed hashes against the artifact manifest.

The oracle was simulated using the hidden reference after candidate freeze and query selection. The result demonstrates the value of one authorized answer when available, not the ability to infer hidden outputs autonomously. A real deployment must receive expected outputs from a user, a test harness, a runtime, or another authorized external oracle. This remains a synthetic generator-matched study, not an official ExeDec external benchmark, SOTA, novelty claim, or general-purpose synthesis result.
