# V6 Confirmatory Protocol — Strict-Semantics Depth 4

## Status

**V6 confirmatory run completed on 2026-11-18.** The 200-task cohort was generated, frozen, scored once, and its durable artifacts were verified on branch `fix/eligible-only-benchmark-aggregation`.

- Source commit used to freeze and score the cohort: `31578842956d59715de9c65cf1b6f42a2b26ebe1`.
- Results-report commit: `0a2cca3b264a07b03664d6f37f558e17accfe0b0`; documentation-only V6 status follow-up: `d680261972eaa37a68b4735a3fc1e5f124b3725b`.
- Candidate admission: 275 candidates evaluated; 200 accepted and 75 rejected (64 target-preflight, 4 query-pool capacity, 7 reserved-input capacity).
- Scoring: 200/200 tasks and 800/800 arm results completed; prior-family overlap was zero.
- Full unit suite: **56 passed**, 5 non-failing warnings, on code/results commit `0a2cca3b264a07b03664d6f37f558e17accfe0b0`. The subsequent `d680261` commit changed only this protocol status document; the release-structuring pass makes no synthesis or benchmark-logic changes.
- Checkpoint SHA-256: `a0f03d5066d86022d932699c1a6dfe68957d56131a38e7816e2085bda2000d41`.
- Results and artifact hashes: [V6 four-way results and provenance](v6-four-way-200-results.md).

V6 is the confirmatory protocol/cohort, not a fifth model arm or a new model architecture. It compares the four existing symbolic, guided, one-turn ablation, and one-turn full arms while retaining the V5 checkpoint.

The run used Deepnote CPU Basic (2 vCPU / 5 GiB). The machine was stopped after validation. The workspace's larger 4-vCPU / 16-GiB machine was unavailable; this did not require changing the protocol.

## Locked research scope

- Experiment: SYNTH-ESQ-V6-FOUR-WAY-200
- Cohort: 200 fresh structural families, subject to both target-validity and complete-stream feasibility gates.
- Target active-operator depth: **1–4**.
- Search budget: **4 operations**.
- Search and evaluation semantics: **strict intermediate bounds** throughout.
- Four existing comparison arms only: symbolic, guided, one-turn ablation, and one-turn full.
- No new architecture, model head, operator, oracle iteration, search feature, or depth expansion is included.
- The V5 checkpoint and the already declared source/environment provenance gate remain in force.

## Minimal model-independent target-validity preflight

Each candidate target is checked before cohort acceptance and before any arm is run.

1. Generate 50 deterministic, unique input assignments under the candidate task's declared input specifications.
2. Derive the sample seed from a dedicated V6 preflight seed domain plus the task seed and structural-family hash.
3. Exclude the visible demonstration rows from the preflight sample.
4. Execute the reference target program using the authoritative strict interpreter.
5. Accept the candidate only when all 50 unique probe inputs were generated and at least **25/50** produce a non-None strict target result.
6. Reject candidates below that threshold and record the attempt, target depth, sample size, valid count, sample digest, and acceptance outcome.
7. Repeat deterministic candidate generation until 200 unique, unseen, preflight-valid structural families have been accepted or the declared generation-attempt ceiling is reached.

No model, candidate ranking, oracle answer, or arm result participates in the preflight decision.

## Complete-stream feasibility gate

Target validity alone is not sufficient to accept a task: the declared input specifications can describe a finite domain too small to supply every disjoint stream, and the bounded query sampler can return fewer rows than requested. Before a candidate is counted as an accepted cohort task, the runner must prove it can construct all remaining streams at their locked sizes.

1. Generate exactly **100 unique query-pool inputs**, excluding visible demonstrations and all 50 preflight probes.
2. Generate exactly **50 unique reserved fresh-evaluation inputs**, excluding visible demonstrations, preflight probes, and every query-pool input.
3. Verify the four streams (visible, preflight, query, reserved) are pairwise disjoint and that each stream has its exact required unique row count.
4. If the query sampler returns fewer than 100 rows, record `query_pool_capacity` and reject the candidate. If 50 reserved rows cannot be constructed, record `reserved_evaluation_input_capacity` and reject the candidate. The attempt, family hash, preflight evidence, actual stream counts, and rejection reason remain in the attrition report.
5. Continue the same deterministic candidate-generation sequence until 200 unique unseen families pass both gates. Do not shrink the 100/50 stream sizes, reuse rows across streams, weaken preflight validity, change target depth/search budget, or select a cohort based on model/arm outcomes.

This is an admission-feasibility rule for the already locked 100-query / 50-reserved protocol, not a change to the four arms or to scoring. The scorer independently rejects incomplete streams and verifies the recorded attrition counts and disjointness.

## Input-stream isolation

For every accepted task, four input streams remain pairwise disjoint:

- visible demonstrations;
- 50 preflight calibration probes;
- generated query-pool inputs;
- 50 reserved fresh-evaluation inputs.

The query-pool generator is explicitly passed the preflight rows as exclusions and must return exactly 100 unique inputs. The reserved-input generator excludes visible, query, and preflight rows and must return exactly 50 unique inputs. Candidates that cannot supply either quota are rejected before cohort acceptance with a recorded capacity-rejection reason. The runner fails closed on any intersection; the scorer independently verifies exact counts, uniqueness, attrition evidence, and pairwise disjointness from persisted artifacts.

## Frozen evidence and verification

Before any model arm is evaluated, V6 creates and persists:

- preflight_inputs.jsonl with accepted tasks' full 50-row calibration streams and per-task hashes;
- preflight_report.json with the predeclared policy, target-validity and stream-capacity attrition counts, accepted/rejected counts, and per-attempt evidence;
- disjoint query and reserved input rows;
- source/runtime manifest and checkpoint digests.

The cohort lock records the exact target-preflight and stream-feasibility policy, all three rejection counts, and hashes for both preflight artifacts. The scorer independently verifies policy, attrition counts, task identity, deterministic preflight sample identity and hash, strict valid-case counts, exact 100/50 stream sizes, uniqueness, and stream disjointness before scoring.

The accepted cohort is frozen at benchmarks/results/four_way_200_v6 using run_four_way.py --freeze-only. This produces a freeze manifest covering the cohort lock, preflight evidence, candidate/query streams, and target-map manifest without entering the inline scoring path. Run score_frozen_four_way.py once with --max-new-tasks 200 against that frozen source and a separate scoring output directory. Its per-arm durable journal allows recovery only within the same cohort and same scoring output; it must not regenerate, replace, or select a more favorable cohort.

## Run controls

- Execution record: the full suite passed with 56 tests and 5 non-blocking warnings on the current branch HEAD. The cohort freeze, single durable scoring invocation, and artifact inventory/hash checks all completed successfully.
- The recorded source update adds regression tests for query-pool shortfall, reserved-input exhaustion, exact stream completeness, pairwise disjointness, and scorer enforcement.
- The cohort and scoring artifacts are persisted under `benchmarks/results/four_way_200_v6` and `benchmarks/results/four_way_200_v6_scoring`. Do not regenerate either output or run a second cohort.
- Do not edit the frozen cohort, inputs, candidate freezes, target maps, scoring journal, or provenance after generation.

## After V6

The V6 run and artifact verification are complete. The ownership, first-party licensing, dependency, and upstream-attribution assessment is recorded in [the commercial and license audit](../COMMERCIAL_AND_LICENSE_AUDIT.md); the approved first-party licence is Apache-2.0 for source code and packaged model weights. This documentation/release-structuring pass does not reopen the cohort, rescore tasks, retrain the model, or alter synthesis logic.

The frozen V6 cohort, inputs, candidate freezes, target maps, scoring journal, and provenance artifacts remain immutable. Any future platform-specific wheel or binary distribution still needs its exact dependency/SBOM notices.
