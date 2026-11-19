> **Status: Historical Record — Superseded by V6 Release Audit.** This document preserves the earlier V5 experiment or audit, including contemporaneous limitations and conclusions. It remains part of the research history; the [V6 four-way results](v6-four-way-200-results.md) and [V6 strict-depth-4 protocol](v6-strict-depth4-preflight-protocol.md) are the current release-level synthetic evaluation record.

# Four-way 200-task benchmark: recovery and validity audit

## Status

The 200 task-level results are complete and preserved. The interrupted run contributed the first 172 durable rows; the final recovery scored only tasks 0172–0199. No task was rescored during this audit.

The original recovery summary contained an aggregation defect: it included fresh-case counts from tasks that failed the predeclared eligibility threshold. The original non-resumable runner only aggregated fresh-case counts for eligible tasks. The durable task rows were correct; the recovery summary was not.

The recovery aggregation has been corrected on the audit branch. The durable journal remains unchanged.

## Corrected results

Eligibility is defined by at least 25 valid target executions among 50 reserved fresh inputs. All four arms share the same target program and reserved inputs, so eligibility is identical across arms.

| Arm | Eligible tasks | Correct / valid fresh cases | Eligible-only micro accuracy | Complete behaviour matches |
|---|---:|---:|---:|---:|
| v1 symbolic | 104/200 | 3,036 / 4,550 | 66.73% | 26/104 (25.00%) |
| v3 guided | 104/200 | 3,074 / 4,550 | 67.56% | 27/104 (25.96%) |
| v5 ablation | 104/200 | 3,210 / 4,550 | 70.55% | 30/104 (28.85%) |
| v5 full | 104/200 | 3,301 / 4,550 | 72.55% | 30/104 (28.85%) |

Fresh-case accuracy is pooled (micro-averaged) over valid cases from eligible tasks only. It is not accuracy over all 200 tasks or all 10,000 reserved input slots.

The v5 full arm has the highest eligible-only fresh-case micro accuracy, but it does **not** increase the number of complete-behaviour matches over v5 ablation. Do not claim an improvement in complete task-level generalization from this result.

### Sensitivity to the eligibility gate

The 96 ineligible tasks still contain 840 valid target cases in aggregate (81 tasks have 1–24 valid cases; 15 have none). For transparency, the two pooled case-level views are:

| Arm | Eligible-only (104 tasks / 4,550 cases) | All-task valid cases (200 tasks / 5,390 cases) | Ineligible subset (96 tasks / 840 cases) |
|---|---:|---:|---:|
| v1 symbolic | 66.73% | 65.10% | 56.31% |
| v3 guided | 67.56% | 65.84% | 56.55% |
| v5 ablation | 70.55% | 68.79% | 59.29% |
| v5 full | 72.55% | 70.58% | 59.88% |

The all-task and ineligible-subset figures are secondary descriptive calculations, not the protocol's headline metric. They show that the eligibility gate removes a harder subset and raises the reported eligible-only accuracy by roughly 1.6–2.0 percentage points. Both views should be retained in any research discussion; do not imply that the 96 ineligible tasks contained no usable examples.

### Paired v5-full versus v5-ablation comparison

Across the 104 eligible tasks, the two arms have identical per-task valid-case denominators. Their fresh-case correct counts differ on only 8 tasks: v5 full improves 7 and regresses 1; the other 96 tasks tie. The eight per-task correct-count deltas are `+18, -1, +5, +4, +31, +2, +20, +12`, summing to the 91-case pooled gain.

The mean per-task accuracy improvement is **+2.12 percentage points** (10,000-resample paired task bootstrap 95% interval: **+0.42 to +4.28 pp**). An exact paired sign-flip permutation test on the eight nonzero task deltas gives **p = 0.0156**; the two-sided sign test based only on 7 wins versus 1 loss gives **p = 0.0703**. Treat these post-hoc inferential calculations as exploratory, not as a pre-registered confirmatory test.

There are **no complete-behaviour-match transitions** between the arms: the same 30 tasks are complete matches in both, and the same 74 tasks are not. Thus the accuracy gain is sparse and partial; it does not create any additional task-level exact generalization successes.

## Eligibility attrition

The 200 target programs have the following valid-input coverage over the 50 reserved inputs:

- 55 tasks: 50/50 valid.
- 49 tasks: 25–49 valid.
- 81 tasks: 1–24 valid.
- 15 tasks: 0 valid.

Thus only 104/200 tasks (52%) meet the predeclared threshold. The 96 ineligible tasks are excluded from the eligible-only accuracy and complete-match denominators; they are not silently counted as model failures.

This attrition is a material generator limitation. The task generator accepts a program after finding three valid visible examples (with a bounded search of up to 500 input draws). That does not ensure the program has at least 25 valid cases under the independent reserved-input distribution. Some generated programs contain operations whose validity is highly input-dependent. For example, a program that uses the sum of a list as an index can be valid only for a small subset of sampled lists. This explains why some held-out tasks have very few or zero valid reference outputs.

The 25-case eligibility threshold was recorded in the cohort lock before scoring, and all arms use the same target-defined eligibility. Nevertheless, 52% coverage limits the strength and representativeness of conclusions. The cohort must not be presented as a broad sample of generally executable tasks.

## Target depth versus search depth

A second design mismatch is visible in the source: the synthetic target generator permits 1–6 active operators (`MAX_OPERATORS = 6`), while all four search arms are capped at 4 operations (`MAX_OPS = 4`). The frozen target maps include examples with 5–6 active operators.

The read-only reconstruction confirms this active-operator histogram: 2 operators: 6 tasks; 3: 21; 4: 47; 5: 61; 6: 65. Thus 126/200 targets (63%) exceed the four-operation search bound. Eligibility is lower among those deeper targets: 53/126 over-depth tasks are eligible (42.1%), versus 51/74 tasks at depth four or below (68.9%).

This does not prove that every deeper target is unsolvable: a semantically equivalent program with four or fewer operations may exist. The strict reserved-input audit confirms that the frozen portfolios contain such shorter matches for some over-depth tasks: v1 has 19 strict full matches across all tasks (8 eligible over-depth); v3 has 20 (8 eligible over-depth); v5 ablation and v5 full each have 28 (9 eligible over-depth). The eligible-overdepth counts are the relevant subset; all four arms still have only 26/27/30/30 eligible strict full matches overall. This is a four-operation bounded search evaluated against a 1–6-operation target distribution, not a same-depth synthesis comparison. See [issue #4](https://github.com/Kshitijpalsinghtomar/synth). Do not change the frozen search bound or candidate results in this audit.

The generator-validity follow-up is tracked separately in [issue #3](https://github.com/Kshitijpalsinghtomar/synth/issues/3).

## Search versus runtime strictness

The frozen V5 search arms call synthesis with `strict_intermediates=False`, while target generation, fresh evaluation, and the one-shot oracle's candidate executor use strict intermediate bounds. This meant the search could retain candidates that strict execution later rejects.

The exact read-only counts are below. A "candidate/input execution rejection" means that a frozen program returned a value under permissive execution but failed strict intermediate bounds for that specific input; it is not a count of unique incorrect tasks.

| Arm | Visible exact fits (permissive) | Visible exact fits (strict) | Visible exact-fit tasks lost | Reserved candidate/input rejections | Of these, target-valid inputs | Tasks with a reserved-affected candidate | Strict full matches on eligible tasks |
|---|---:|---:|---:|---:|---:|---:|---:|
| v1 symbolic | 170 | 167 | 3 | 392 / 10,000 | 54 / 5,390 (1.00%) | 14 | 26 / 104 |
| v3 guided | 182 | 177 | 5 | 474 / 10,000 | 65 / 5,390 (1.21%) | 17 | 27 / 104 |
| v5 ablation | 180 | 176 | 4 | 1,026 / 18,400 | 216 / 9,816 (2.20%) | 24 | 30 / 104 |
| v5 full | 182 | 178 | 4 | 1,026 / 18,450 | 216 / 9,866 (2.19%) | 24 | 30 / 104 |

For v5, 216 reserved candidate/input executions per arm fail strict bounds on target-valid inputs; this affects at least one frozen candidate in 24 tasks. This is a real search/runtime semantic mismatch and can waste portfolio capacity. It does **not** invalidate the reported selected-program scores: selected-program counts were reconciled against the durable task journal with zero case-count mismatches, and strict selected full-match counts on eligible tasks remain 26/27/30/30. No eligible task had a full-match candidate in its v5 portfolio that was available but not selected; the 6 ablation and 3 full portfolio-only matches occurred only among ineligible tasks.

The one-shot query prevalidation replay also reconciled with provenance and the journal with zero queryability, screening-event, or proposal-event mismatches. It screened 205 candidate sessions and recomputed 171 actual query proposals. Across those strict executions it recorded 1,044 candidate execution rejections, of which 871 were internal-bound rejections and 173 final-bound rejections, plus 874 runtime-invalid executions. This verifies that query prevalidation applied strict execution; it does not erase the relaxed-search mismatch for the rest of the frozen candidate/input domain.

**Decision for future cohorts:** strict intermediate bounds are now the policy for every V6 search arm, matching target generation, evaluation, and oracle candidate execution. The V6 runner and cohort lock encode this as `strict_intermediates=True`. The frozen V5 metrics and candidates remain unchanged. Tracked in [issue #5](https://github.com/Kshitijpalsinghtomar/synth/issues/5).

## Integrity checks

- 200 task rows, ordered from `synth-200-0000` through `synth-200-0199`.
- All four arms are present for every task.
- All four arms have identical per-task valid-case counts and eligibility.
- The journal SHA-256 remains `af4e85032aaf19d1837ebd78b1ba2c6ad5023136f1856fb192b97dae5296716c`.
- The frozen candidate and query/evaluation input digests remain unchanged.
- All 400 paired target maps match deterministic target reconstruction; 814 target-execution cross-checks passed.
- All 800 frozen candidate rows and the complete task journal reconcile; selected-case counts, target-valid denominators, selected-program hashes, and query-event reconciliation have zero mismatches.
- The candidate-freeze file contains no persisted family-hash fields (0/800 rows), so the historical file cannot independently prove those per-row family labels. Task-to-target identity was instead verified by deterministic cohort reconstruction and target-map equality.
- All 10,000 reserved inputs are unique; no visible/reserved or query/reserved overlap exists. The query pool has no duplicate rows. Its declared size of 100 is a maximum: 195 tasks have 100 unique rows and five have complete smaller profile domains (39, 42, 39, 39, 84). The query pool overlaps 136 visible examples across all tasks, but the query proposal code excludes visible examples and reserved inputs before a proposal is selected.
- Query selection is separated from the oracle response; it pre-validates candidates and proposes one deterministic disagreement query.
- The claim boundary remains: **fresh structural-family-held-out synthetic generator cohort with a local file-backed reference oracle; not an official ExeDec benchmark**.

The v5-arm runtime values include the local oracle/query transaction overhead; they should be described as end-to-end pipeline time, not raw synthesizer-only latency.

## Repair

The recovery aggregation now adds `fresh_case_correct` and `valid_fresh_cases` only when `eligible` is true, matching the original runner. The regression test reproducing the defect passed. The summary-only recovery path rebuilt `summary.json`, `progress.json`, and `artifact_manifest.json` from the existing journal without scoring any task again. The latest forward-only recovery, provenance, and V6 policy changes pass **17/17 protocol tests**, **13/13 arm-journal tests**, **6/6 focused frozen-input/source-provenance tests**, and **48/48 tests across the full repository**.

## Resume provenance reconciliation

The append-only provenance log contains 1,641 events with contiguous sequence numbers 0–1,640 and SHA-256 `a082ca592aaaa417f0a907038de9dfc689d78ffdf163af5f916135de7d90d7c9`. Reconciliation against the final task journal found two duplicated arm-attempt records for task `synth-200-0172`:

- `v5_ablation`: the first attempt completed its query, oracle response, and candidate selection; the final resume repeated that complete sequence.
- `v5_full`: the first attempt reached portfolio freeze and query-pool screening but stopped before proposing a query; the final resume repeated those events and completed one query/request/response/selection sequence.

This happened because the interrupted run emitted oracle events for task 0172 before its task result row was appended. The recovery journal contained only tasks 0000–0171, so the final run correctly reran task 0172 and appended one final task row, while preserving the earlier attempt in the provenance log.

The reconciliation counts are consistent after accounting for those retries: 362 unique candidate sessions, 171 unique query proposals, and 269 fallback selections match the task journal. The raw log has 364 portfolio-freeze events and 172 proposal/request/response events because of the duplicated partial attempt. The task journal itself still has exactly 200 unique rows.

The local synthetic file-backed oracle is deterministic and side-effect-free, so these retries did not change the final task scores. However, the provenance file is an attempt history, not a one-session-per-task/arm ledger. A future human or external oracle workflow must add attempt IDs and idempotent resume handling. Tracked in [issue #6](https://github.com/Kshitijpalsinghtomar/synth/issues/6).

The corrected summary and artifact manifest are stored in the Deepnote project under:

`release_work/standalone/benchmarks/results/four_way_200_recovery_final/`

No training, cohort regeneration, task rescoring, merge, release, or publication was performed.

## Forward crash-recovery hardening

The original frozen run is unchanged. The following recovery changes are being added to the scorer for future runs and are deliberately not backfilled into the old journal:

- **Per-arm durable checkpoint:** each arm's complete metrics and a unique `attempt_id` are appended and fsynced to `four_way_arm_results.jsonl` before the next arm begins. If a process stops mid-task, resume loads those rows and executes only unfinished arms.
- **Task-to-arm binding:** new task rows carry `arm_journal_version: 1` and all four `arm_attempt_ids`. Summary rebuild requires all four arm records and exact metric/attempt-ID agreement. This catches a lost or truncated whole arm-journal tail even if a task row survived.
- **Ordering and consistency gates:** duplicate `task_id/arm` rows, unknown task IDs/arms, skipped/reordered arms, non-contiguous task groups, incomplete arm state for a completed task, non-prefix task journals, or mismatches between per-arm and task-level metrics cause a hard failure instead of silent aggregation.
- **Attempt-aware oracle events:** each one-shot oracle call tags all events with a unique attempt ID. The deterministic query ID includes task, query, and frozen portfolio identity; it is sent as the stable idempotency key and recorded with request/response events.
- **Durable response replay:** a valid bounded oracle answer is stored in its response event. On resume, when the matching durable response exists, the scorer reconstructs the answer and continues candidate selection without asking the oracle again. The replay is attributed to the new attempt through `oracle_response_reused`; the original request/response remain intact.
- **Durable request boundary:** `query_proposed`, `oracle_requested`, and `oracle_response` are fsynced. If the process dies after the external side effect but before the response event is durable, a retry necessarily calls the adapter again with the same idempotency key; the provider/adapter must deduplicate that key to prevent a repeated side effect.
- **Provenance tail handling:** an unterminated final JSONL record is truncated before appending; malformed newline-terminated records, invalid sequence values, and sequence gaps fail closed rather than being silently skipped.
- **Adapter compatibility:** the subprocess adapter forwards the idempotency key; the human prompt displays it. An external adapter must actually enforce/deduplicate that key to guarantee exactly-once side effects. Passing the key through the protocol alone is not a universal exactly-once guarantee.

These are forward-only changes. The old 1,641-event provenance log has no attempt IDs, and its duplicate task-0172 attempts remain intact and represented by the original provenance digest. The existing 200 task results and their summary are not rescored or rewritten by this work. Legacy task journals without a per-arm journal remain readable; newly written output includes the per-arm journal in its artifact manifest.

The cohort lock also lacks source-file and runtime/environment digests, and the persisted candidate-freeze rows omit family hashes. The target maps can still be reconstructed and checked against the deterministic generator, but source-version reproducibility cannot be proven from the lock alone. This is tracked for future cohorts in [issue #7](https://github.com/Kshitijpalsinghtomar/synth/issues/7).

### Final recovery regression evidence (2026-11-17)

After the forward-only recovery implementation, the updated branch passed **17/17 protocol tests**, **11/11 arm-journal recovery tests**, and **41/41 full repository tests**. The new protocol tests cover crashes after query proposal, after the durable request event, after an external side effect but before the response event, and after the durable response event. They also verify response-hash validation and replay without a second adapter call. Arm-journal tests cover partial resume, task-row reconstruction before task append, task-prefix alignment, order, duplicates, lost journal segments, and attempt-ID mismatches.

The source and runtime provenance gap remains a future-cohort issue; these tests do not backfill or mutate the frozen 200-task cohort.

## Future cohort protocol: V6 (not executed)

A forward-only V6 path is implemented on this branch. It defaults to a separate output directory, `benchmarks/results/four_way_200_v6`, and labels the experiment `SYNTH-ESQ-V6-FOUR-WAY-200`; it cannot overwrite the frozen V5 directory.

V6's policy is intentionally aligned at the search/runtime boundary:

- Target generation is capped at four active operations, matching the four-operation search limit. The generator API accepts an explicit `max_ops`; its legacy default remains six so V5 target reconstruction is unchanged.
- All four search arms use `strict_intermediates=True`, matching target generation, fresh evaluation, and oracle candidate execution.
- The cohort lock records protocol version, target min/max operator bounds, search max operators, strictness policy, and a new source-manifest path and digest.
- Before arms run, the runner captures source-file SHA-256 values (including the actual selected checkpoint, sidecar, and adjacent model card), Git origin/commit/branch/dirty-worktree and tracked-diff/untracked-file digests, Python/runtime/host details, installed package versions, and dependency declaration/lockfile digests. V6 refuses to start without a Git origin, committed revision, and clean worktree. It verifies the source files and runtime again before writing the cohort lock.
- The scorer verifies the source manifest and environment against the cohort lock before scoring or summary-only rebuilding. Legacy V5 cohorts without a source manifest remain explicitly legacy; no metadata is fabricated or backfilled.
- The V5 query-pool file contains 136 rows overlapping the three visible demonstrations across 200 tasks; proposal selection already excludes those rows, so no visible example was proposed. V6 now excludes visible rows during query-pool generation so they do not consume the query-pool budget.

The complete repository suite passes **48/48** on the current branch tip; this includes the 17 protocol, 13 arm-journal and 6 focused frozen-input/source-provenance tests. The V6 runner has **not** been executed. The preflight validity gate in [issue #3](https://github.com/Kshitijpalsinghtomar/synth) is still required before V6 should be run: the original V5 generator admitted tasks after only three visible valid examples, producing just 104/200 eligible tasks on the reserved stream. A new cohort must measure validity independently before freezing candidates, use disjoint preflight/query/reserved streams, and report preflight attrition without conditioning on any model arm. Until that gate is implemented and verified, V6 execution remains blocked.

This policy does not retroactively alter V5. Its 1–6 operator target distribution, relaxed-search semantics, and absent source manifest remain the historical facts for that frozen experiment.

## Interpretation

This is evidence about bounded synthesis on a narrow synthetic integer/list DSL under this particular generator and local one-query oracle protocol. It is not evidence of general-purpose program synthesis, production data-wrangling performance, or superiority to commercial tools. External benchmark comparisons remain separate and have not been performed.
