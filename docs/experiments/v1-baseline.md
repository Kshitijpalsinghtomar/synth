> **Status: Historical Record — Superseded by V6 Release Audit.** This document preserves the earlier experiment's protocol, evidence, and conclusions as recorded at the time. It is retained for the research chronology; use the [V6 four-way results](v6-four-way-200-results.md) and [V6 strict-depth-4 protocol](v6-strict-depth4-preflight-protocol.md) for the current release-level synthetic evaluation.

# P6 — ESQ-DSL: execution-signature quotienting for bounded program synthesis

**Report date:** 15 November 2026  
**Research line:** P6 — ESQ-DSL program-synthesis baseline and tool release  
**Status:** implementation and ESQ-03 fresh-input evaluation complete; release as artifact/baseline; no novel-method or neural-architecture claim

## 1. Research question and method

Given a few visible input/output examples for a typed program, can bounded search avoid repeatedly exploring programs that are observationally indistinguishable on those examples?

For each candidate program p, ESQ computes the typed execution signature:

`σ_D(p) = (type(p), p(x_1), …, p(x_m))`.

Candidates with identical signatures on the current examples are in the same observational-equivalence class. ESQ keeps one deterministic representative (minimum operator count, then lexical program code) and enumerates typed DeepCoder expressions subject to:
- maximum four operator nodes;
- maximum 10,000 unique signatures per task;
- five-second per-task time budget.

This is an exact quotient only with respect to the current examples. It does not mean programs are equivalent on unseen inputs.

## 2. ESQ-03 external split and result

The evaluation used the public DeepMind ExeDec DeepCoder SWITCH_CONCEPT_ORDER split, pinned to commit ef046ce2cc3fcd024e32f5dfe00e69700dac82ed. It contained 200 tasks, each with three visible target I/O examples and four demonstration programs.

Candidate selection used only visible examples. The hidden reference program was accessed only after selection to score new inputs. Fifty fresh input tuples were generated per task (10,000 total), following the documented ExeDec value/length ranges; the input generator was independent and did not reproduce the official Python RNG stream.

| Measure | Four-shot retrieval | ESQ-03 |
|---|---:|---:|
| Exact fit on three visible examples | 0/200 (0%) | 177/200 (88.5%) |
| Match reference on every valid fresh input, eligible tasks | 0/180 (0%) | 144/180 (80.0%) |
| Correct outputs / 8,937 valid fresh cases | 454/8,937 (5.08%) | 7,947/8,937 (88.92%) |

The preregistered gate required at least 150 eligible tasks, zero visible-reference replay mismatches and a ≥10 percentage-point improvement over retrieval. All criteria passed; the task-level gain was +80 percentage points.

Important failure/limitation counts:
- 23/200 tasks (11.5%) reached the 10,000-signature cap without an exact fit in the admitted prefix.
- 16 eligible tasks fit all three visible examples but still diverged on at least one fresh input.
- 20 tasks were excluded from the complete-task-equivalence denominator because fewer than 25 of their 50 fresh inputs had valid reference outputs; their raw records were retained.

## 3. Earlier split history

- SFR-01 on COMPOSE_NEW_OP: visible I/O accuracy rose 12.67%→23.0%, but exact visible-task solves remained 0/200; FAIL.
- ESQ-01 on COMPOSE_NEW_OP: 175/200 visible fits, but 18.5% candidate-cap truncation; INCONCLUSIVE.
- ESQ-02 on COMPOSE_DIFFERENT_CONCEPTS: 183/200 visible fits, 17.5% truncation; INCONCLUSIVE.
- ESQ-03 on SWITCH_CONCEPT_ORDER: fixed budget retained, cap-aware termination correction applied, fresh-input behavioral gate PASS.

A protocol-mismatched diagnostic that reported 181/200 visible fits was discarded and is not used for the reported result.

## 4. Verification and limitations

The hidden reference replay passed 200/200 visible tasks. The report records eight unit tests for the Python CLI and exact-fit examples. The connected ESQ-03 benchmark runner was syntax-checked but not rerun in the local container because that runtime lacked network access; the aggregate benchmark figures are from the connected experiment run.

This was **not** an official reproduction of ExeDec's trained Transformer results or its complete evaluator. We used the official public task file and independently implemented the fresh-input generator using published ranges. The method is bounded enumerative synthesis and signature deduplication, not a learned model, language model or novel program-induction principle.

## 5. Publication and release decision

P6 is a completed artifact/baseline, not a standalone novel-method paper. The most defensible value is:
- an executable typed DSL synthesizer;
- deterministic equivalence-signature pruning;
- explicit search-budget/truncation reporting;
- one frozen fresh-input behavioral evaluation that future learned methods can be compared against.

A future learned method must beat ESQ-03 on fresh-input behavior under the same information boundary and budget and should include the official ExeDec evaluator/checkpoints or a fully validated adapter. No novelty claim is made for observational-equivalence pruning.

## 6. Manuscript and code provenance

- Pinned upstream reference: [ExeDec commit](https://github.com/google-deepmind/exedec/tree/ef046ce2cc3fcd024e32f5dfe00e69700dac82ed).
- A historical October 2026 handover referred to a working draft named `ESQ_DSL_PAPER_2026-10-22.md` and an archived PDF. Those files are not part of this standalone Synth repository and their current contents were not verified as the authoritative manuscript.
- The manuscript is maintained as a separate writing deliverable. This experiment report is not itself a paper and must not be described as peer-reviewed or published.
