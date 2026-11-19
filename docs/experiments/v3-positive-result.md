> **Status: Historical Record — Superseded by V6 Release Audit.** This document preserves the earlier experiment's protocol, evidence, and conclusions as recorded at the time. It is retained for the research chronology; use the [V6 four-way results](v6-four-way-200-results.md) and [V6 strict-depth-4 protocol](v6-strict-depth4-preflight-protocol.md) for the current release-level synthetic evaluation.

# P6 ESQ-DSL v3 — branch-preserving neural priority ordering

**Report date:** 16 November 2026  
**Tracking issue:** [#18](https://github.com/Kshitijpalsinghtomar/research/issues/18)  
**Branch:** `p6/esq-dsl-v3-safe-priority-2026-11-16`  
**Decision:** Positive result on one untouched ExeDec DeepCoder confirmation split; bounded to this DSL, protocol, and benchmark.

## Executive result

The v2 guided-beam policy was a NO-GO because learned scores deleted search branches and sharply reduced fresh-input behaviour. V3 instead uses learned probabilities only to order the full operation/lambda enumeration. Exact execution-signature quotienting remains the only semantic deduplication mechanism; learned thresholds and beam pruning are absent.

On the previously inspected `SWITCH_CONCEPT_ORDER` development split, v3 scored 146/180 eligible tasks as full fresh-behaviour matches versus 139/180 for the budget-matched Python v1 baseline. On the separately locked, untouched `LENGTH_GENERALIZATION` confirmation split, v3 scored **118/180 versus 108/180** for v1. Fresh-case accuracy was **78.69% versus 75.23%**. Reference visible replay passed 200/200 tasks.

This is a modest positive confirmation for this bounded task family. It is not evidence of general program-synthesis capability, novelty, state of the art, or publication readiness.

## 1. What changed from v2

V2 used the model as a beam-search gate. The model could effectively delete branches, and its Python comparison fell to 88/180 full fresh matches versus 138/180 for v1. V3 changes this design:

- Every typed operator remains in the search; every applicable lambda remains in its family.
- Learned operation and lambda scores change visitation order only. Candidate streams are round-robin advanced so a high-priority stream cannot starve lower-priority streams.
- One deterministic representative per exact typed execution signature is retained for expansion. This quotient is based on identical outputs across all visible examples, not learned confidence.
- The separate candidate portfolio is limited to exact fits for the task's target signature and ranked by visible-input model priors. The hidden reference never selects executable top-1.
- The only search cutoffs are explicit time/signature budgets. A cutoff is reported as truncated with a stop reason; a partial search is not described as exhaustive.

## 2. Synthetic data and training

A deterministic 100,000-task synthetic corpus was generated with three visible I/O examples and a DeepCoder-aligned input layout: one or two input variables, at least one list input, any additional input sampled from integer/list, and shuffled input order. Integer inputs use inclusive [0,5]; list element ranges are selected from (0,4), (0,9), (-10,10), and (-50,50), with list lengths selected from (1,3) or (0,5). Programs contain 1–6 operations from the existing typed DSL grammar.

Structural program families are hashed from the ordered input-type layout and normalized active output AST (operation, lambda, and child structure). Whole families are deterministically split 80/10/10:

| Partition | Tasks | Structural families |
|---|---:|---:|
| Train | 79,535 | 43,675 |
| Development | 10,546 | 5,466 |
| Synthetic confirmation (sealed) | 9,919 | 5,508 |

All family sets are pairwise disjoint. No official ExeDec confirmation tasks were used in corpus generation, training, or model selection.

A 137,897-parameter set encoder was trained from scratch on CPU for four epochs (seed 20261116, batch 256, AdamW learning rate 1e-3). Final development diagnostics were operator macro-F1 0.441, lambda macro-F1 0.188, and program-length accuracy 0.249. These are auxiliary prediction metrics, not synthesis performance.

Checkpoint SHA-256: `1e5e086f0489c303475d4a0eee0e53a1360e1f888cf7cbb009ed9c9e55bba81c`.

## 3. Search evaluation

Both systems used max four operations, a 10,000-signature cap, 300 ms nominal per-system timeout, and the same 50 fresh input tuples per task. V3's model inference time was deducted from its symbolic-search allowance and is included in its reported elapsed time. Top-3 oracle selection is reported only as a diagnostic upper bound, never as deployable model performance.

### Development: SWITCH_CONCEPT_ORDER

This 200-task split was already examined by earlier P6 work and is development-only. There were 180 eligible tasks and 8,937 valid fresh cases.

| Metric | Python v1 | V3 priority order |
|---|---:|---:|
| Visible exact fits | 170/200 | 176/200 |
| Full fresh-behaviour matches | 139/180 (77.22%) | 146/180 (81.11%) |
| Fresh-case accuracy | 87.80% | 89.56% |
| Truncated tasks | 30 | 36 |
| Mean unique signatures | 2,651 | 3,559 |
| Mean measured search time | 124.7 ms | 113.8 ms |
| P95 measured search time | 334.2 ms | 307.7 ms |

V3 top-3 oracle full-match coverage was 151/180 (83.89%); this uses hidden references to select among frozen candidates and is not a deployable result.

### Final clean confirmation: LENGTH_GENERALIZATION

The confirmation data file was frozen before candidate generation:

- Source: `google-deepmind/exedec/data/llm_data/deepcoder/LENGTH_GENERALIZATION.jsonl`
- ExeDec commit: `ef046ce2cc3fcd024e32f5dfe00e69700dac82ed`
- Rows: 200
- Raw bytes: 187,614
- Raw dataset SHA-256: `6d060c79b7f75c610af1239f461be41a97a5e621b1e72d2659497a9491a1189b`

All 200 v1/v3 candidate portfolios were generated using only visible I/O information and persisted before the separate scoring stage accessed hidden references. The frozen candidate file SHA-256 is `d9a94be2912d44ba60621321856a17fb62311c82a55cdf06003aa55ba0e8fb02`. The checkpoint SHA is the hash recorded above. No code, checkpoint, threshold, or search setting was changed after confirmation scoring.

There were 180 eligible tasks and 8,873 valid fresh reference cases. The reference program replayed all 200 visible task specifications correctly.

| Metric | Python v1 | V3 priority order |
|---|---:|---:|
| Visible exact fits | 137/200 | 154/200 |
| Full fresh-behaviour matches | 108/180 (60.00%) | **118/180 (65.56%)** |
| Fresh-case accuracy | 75.23% | **78.69%** |
| Truncated tasks | 63 | 71 |
| Mean unique signatures | 4,297 | 6,631 |
| Mean measured search time | 247.1 ms | 213.5 ms |
| P95 measured search time | 515.4 ms | 309.4 ms |

V3 top-3 oracle full-match coverage was 126/180 (70.00%); its oracle upper-bound case accuracy was 82.01%. These are not executable selector results.

### Budget and parity caveats

The 300 ms setting is a nominal per-system budget, not a hard real-time guarantee. Both Python implementations exceeded it on some tasks because timing checks are coarse-grained; v1 overran further on this length-generalization split. The report therefore includes measured mean, P50, P95, and maximum latencies rather than treating 300 ms as achieved wall time on every task.

The Deepnote image did not include Node.js, so these v1/v3 head-to-head results are Python-run comparisons. The existing ESQ-03 fresh-input generator port was reused for both systems and its Mulberry32 sequence was checked against the original JS outputs, but this does not claim a byte-for-byte rerun of the historical Node benchmark. Historical Node aggregates and this budget-matched Python evaluation remain distinct.

## 4. Reproducibility and artifacts

Code, tests, protocols, manifests, and compressed task-level results are under `experiments/P6_ESQ_V3/` in this branch. The task artifact manifest records raw, gzip, and base64 hashes. Deepnote retains the full 100,000-task synthetic corpus, compressed supervision arrays, trained checkpoint, candidate portfolios, and scored task-level outputs.

Key Git paths:

- `experiments/P6_ESQ_V3/PROTOCOL.md` — frozen method and benchmark policy.
- `experiments/P6_ESQ_V3/src/esq_v3.py` — branch-preserving priority search.
- `experiments/P6_ESQ_V3/src/esq_data_v3.py` — ExeDec-aligned variable-arity generator and structural family hash.
- `experiments/P6_ESQ_V3/src/esq_training_v3.py` — deterministic corpus and local training pipeline.
- `experiments/P6_ESQ_V3/src/esq_eval_v3.py` — two-stage candidate freeze/scoring pipeline.
- `experiments/P6_ESQ_V3/tests/test_esq_v3.py` — seven focused regression tests.
- `experiments/P6_ESQ_V3/results/SWITCH_DEV_summary.json` and `LENGTH_CONFIRMATION_summary.json` — aggregate outcomes.
- `experiments/P6_ESQ_V3/results/task_artifact_manifest.json` — raw/compressed artifact checksums.

Final source verification on the Deepnote project passed: 7/7 focused tests and `python -m compileall -q src`.

During packaging, two newline literals had been split by the notebook file writer in source text that had already been imported in the live kernel. Those source literals were repaired, committed, and the complete source tree recompiled successfully. The repair changes the intended JSONL line terminator only; the synthetic corpus, checkpoint, frozen candidate files, and scored results were not regenerated or altered.

## 5. Decision and next action

**Decision: keep v3 as the current positive research candidate, but do not merge or claim general superiority yet.** The clean split shows +10 complete fresh-behaviour tasks, +3.46 percentage points fresh-case accuracy, and 17 additional visible exact fits. The cost is more unique signatures and a higher truncation count (71 versus 63), even though measured mean and tail latency improved on this split.

The next scientific step is an independent replication on a new untouched ExeDec task family or another independently specified PBE DSL benchmark, with the same candidate-freeze discipline. Do not retune on `LENGTH_GENERALIZATION`; it is now consumed as a confirmation set. Further work should also profile hard wall-clock enforcement, task-level memory, and the exact effect of operation ordering vs lambda ordering separately.

No merge was performed. Draft PR review is the next repository gate.