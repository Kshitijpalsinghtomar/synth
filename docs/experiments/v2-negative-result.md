> **Status: Historical Record — Superseded by V6 Release Audit.** This document preserves the earlier experiment's protocol, evidence, and conclusions as recorded at the time. It is retained for the research chronology; use the [V6 four-way results](v6-four-way-200-results.md) and [V6 strict-depth-4 protocol](v6-strict-depth4-preflight-protocol.md) for the current release-level synthetic evaluation.

# P6 ESQ-DSL v2 — exploratory evaluation and decision report

**Date:** 16 November 2026  
**Research line:** P6 — ESQ-DSL  
**Status:** implementation and training completed; first guided-beam benchmark comparison is **NO-GO** for the current search policy.  
**Tracking:** GitHub issue #16, branch `p6/esq-dsl-v2-neuro-symbolic-2026-11-16`.

## Executive result

We implemented a locally trained neural guide around the original ESQ symbolic synthesizer, generated a 100,000-task synthetic corpus, trained a 137,897-parameter model on Deepnote CPU, and evaluated a guided-beam v2 against a Python v1 baseline on the exact pinned 200-task SWITCH_CONCEPT_ORDER split with the same 50 fresh inputs/task.

**The model training pipeline worked, but the current v2 integration did not improve synthesis.** At the budget-matched 300 ms target, v2 was worse than v1 on visible fits, fresh-input equivalence, case accuracy, truncation, and latency. Preserve this as a negative exploratory result. Do not promote it as a successful neuro-symbolic improvement.

## 1. v1 baseline reconciliation

The historical ESQ-03 report attributes its aggregate result to the original Node.js benchmark runner:
- 177/200 visible exact fits.
- 144/180 eligible tasks fully matched on fresh inputs.
- 7,947/8,937 valid fresh outputs matched (88.92%).
- 23/200 tasks hit the 10,000-signature cap.

The original runner is preserved in `benchmarks/esq03_generalization_eval.mjs`, but Node.js was not installed in the available Deepnote CPU image. We therefore ran the actual `esq_synth.py` Python implementation on the exact pinned file and the same 50 fresh tuples/task, with the original Mulberry32 generator ported and checked against its first four reference values.

Python-port diagnostic:
- Reference replay: 200/200.
- Visible exact fits: 176/200.
- Full fresh-input match: 144/180 eligible.
- Correct outputs: 7,965/8,937 (89.09%).
- Signature-cap tasks: 24/200.

This is a parity diagnostic, not an exact reproduction of the historical Node run. The one-task visible-fit and one-task truncation differences remain unresolved and must not be hidden.

## 2. Synthetic data and training

Generated 100,000 synthetic tasks from the implemented DSL grammar:
- 1–6 operator nodes per program.
- Three visible I/O examples per generated task.
- 20,000 tasks additionally labelled with a true candidate and two type-compatible one-edit mutations.
- Candidate behaviour measured against 16 generated fresh inputs.
- Grouped operator/lambda family split: 91,284 training / 8,716 held-out-family tasks.
- Frozen ExeDec benchmark usage in generator/training: zero.

Artifacts:
- Gzip JSONL SHA256: `6b9b8f50996c587af82e5f34876ac4c95f04abd6d7946b670131c636d5fa45d7`.
- Uncompressed JSONL SHA256: `feb1efdd6bd0f175eece88b2499ef5208ba37e6fd96a13c8f85db4a24c4ff768`.
- Supervision NPZ SHA256: `44228794897d9128043c3596fd032e7e05839881195e1c804496ab2044086495`.
- Supervision NPZ size: 14,919,844 bytes.

The model was trained from scratch on CPU:
- Parameters: 137,897.
- Seed: 20261116.
- Epochs: 4.
- Batch size: 256.
- Optimizer: AdamW, learning rate 1e-3.
- Held-out operator macro-F1: 0.4238.
- Held-out lambda macro-F1: 0.1929.
- Held-out length accuracy: 0.2217.
- Held-out candidate-score MAE: 0.2980.
- Checkpoint SHA256: `dda5a3e0731f47d9d91a1ce21532b3479b9e69ed8098edf4d1dda7d2a20bbd45`.
- Training wall time: 48.29 s.

These are diagnostics, not evidence of benchmark utility.

## 3. Budget-matched benchmark result

Same pinned dataset SHA and 50 fresh inputs/task. Both synthesizers used a 10,000-signature cap and a 300 ms target timeout; v1 was capped at four operations and v2 at six. All choices were fixed from visible data before the hidden reference was accessed.

| Metric | v1 Python baseline | v2 guided beam |
|---|---:|---:|
| Visible exact fits | 169/200 (84.5%) | 103/200 (51.5%) |
| Full fresh behaviour | 138/180 (76.7%) | 88/180 (48.9%) |
| Top-3 any-full-match (oracle upper bound) | — | 95/180 (52.8%) |
| Fresh case accuracy | 7,577/8,687 (87.22%) | 5,673/8,687 (65.30%) |
| Top-3 best-candidate case accuracy (oracle upper bound) | — | 5,953/8,687 (68.53%) |
| Truncated tasks | 31/200 (15.5%) | 200/200 (100%) |
| Mean unique signatures/task | 2,651 | 520 |
| Mean search time | 126.7 ms | 327.0 ms |
| Median search time | 30.1 ms | 306.8 ms |
| P95 search time | 347.4 ms | 408.7 ms |

The v2 top-3 figures use the hidden reference to select the best candidate after the candidate set is fixed. They are only an oracle upper-bound diagnostic; they are not the model's top-1 deployed result.

## 4. Decision and diagnosis

**NO-GO: current guided-beam search policy.**

It reduces the number of explored signatures by roughly fivefold but loses too much useful search coverage. The guide's probabilities are not sufficiently reliable to justify discarding most of the symbolic frontier. The resulting search hits the time target on every task and averages above the nominal 300 ms target. Top-3 candidate coverage only recovers seven additional full-behaviour tasks over top-1.

The first implementation also has a known synthetic/benchmark input distribution mismatch: the synthetic generator always supplies three input slots (one integer and two lists), while the external tasks vary in input arity and types. The family holdout is grouped by ordered operator/lambda sequence, not a full canonical syntax-tree family. These limitations weaken any interpretation of the learned model's generalization.

The most plausible engineering conclusion is not to remove the model, but to change its authority: use probabilities to **order** symbolic exploration, not to prune away branches. Keep one exact signature representative for expansion (semantically safe under deterministic typed operators), retain a small candidate portfolio for the final exact signature, and use an external oracle/spec to resolve disagreements via distinguishing inputs. This safer policy is a new experiment, not a post-hoc success claim.

## 5. Candidate handling and ChatGPT use

The local notebook has no paid LLM integration. Manual ChatGPT-generated programs can be imported through `src/esq_manual_candidates.py`; each is parsed and executed against all visible examples before it is admitted as a candidate. A visible exact fit is not treated as fresh-input proof.

The counterexample helper returns an input where candidates disagree and explicitly marks that the expected output is still required. It does not pick a “clean-looking” candidate or prune candidates automatically.

## 6. Reproducibility and artifacts

- Dataset repository: `google-deepmind/exedec`, commit `ef046ce2cc3fcd024e32f5dfe00e69700dac82ed`.
- Deepnote runtime: Python 3.11.18, PyTorch 2.1.2, CPU Basic (2 vCPU / 5 GiB RAM).
- No paid API calls, external LLM calls, or ExeDec model checkpoints used.
- Five built-in `unittest` regression tests passed.
- Original Node runner is preserved but was not run because Node was unavailable.

Deepnote output artifacts:
- `artifacts/v1_python_port_summary.json` and `v1_python_port_tasks.jsonl`.
- `artifacts/esq_v2_synthetic_manifest.json`.
- `artifacts/esq_v2_synthetic_tasks_100k.jsonl.gz`.
- `artifacts/esq_v2_supervision_100k.npz`.
- `artifacts/esq_v2_training_manifest.json`.
- `artifacts/esq_v2_model.pt` and checkpoint metadata.
- `artifacts/esq_v2_head_to_head_300ms.json` and per-task JSONL.

## 7. Next experiment — not yet run

1. Replace beam pruning with safe command/lambda ordering over the original symbolic search.
2. Generate input arity and types to match the task grammar rather than always including three fixed input variables.
3. Strengthen program-family holdout to a canonical AST/grammar-family key.
4. Keep the already-inspected SWITCH_CONCEPT_ORDER split as a development result only. Use a distinct untouched split for confirmation.
5. Add compute-matched ablations: v1 order, learned operation ordering only, ordering + candidate portfolio, ordering + tree scorer.
6. Measure exact fits, fresh behaviour, top-3 candidate coverage, truncation, signatures, wall time, and memory.

No new publication or novelty claim is supported by this run. P6 remains an executable baseline plus an exploratory negative result.
