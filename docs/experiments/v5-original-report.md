> **Status: Historical Record — Superseded by V6 Release Audit.** This document preserves the earlier V5 experiment or audit, including contemporaneous limitations and conclusions. It remains part of the research history; the [V6 four-way results](v6-four-way-200-results.md) and [V6 strict-depth-4 protocol](v6-strict-depth4-preflight-protocol.md) are the current release-level synthetic evaluation record.

# ESQ-DSL v5 — one-shot external oracle integration

**Tracking:** [Issue #21](https://github.com/Kshitijpalsinghtomar/research/issues/21)  
**Base:** verified ESQ-DSL v3 at SHA e148240f0b2c0fd8c6ee489df0e3c4474517477b  
**Branch:** p6/esq-dsl-v5-external-oracle-2026-11-16  
**Diagnostic predecessor:** v4 PR #20 remains a draft, unmerged diagnostic record.

## Product rule: this is not a continuous loop

A v5 session is a single, bounded transaction:

1. Freeze the exact-fit candidate portfolio and its hash.
2. Build or receive a finite query pool.
3. Remove visible and reserved evaluation inputs.
4. Validate each remaining input against the task's types, ranges and length bounds.
5. Execute every candidate strictly on each proposed input; discard any input where any candidate errors, returns undefined, or produces an out-of-bounds result.
6. Select exactly one deterministic disagreement query without access to the oracle.
7. Persist the query proposal, then make at most one oracle request.
8. If the answer is valid, select the first frozen candidate whose cached prediction exactly matches it. Otherwise return the first pre-query candidate as fallback.

There is no second query, automatic retry, candidate re-synthesis round, or continuous CEGIS loop. A session performs zero or one oracle request.

## Baseline and architecture

V5 starts from the verified v3 branch and imports its exact interpreter. It does not import v4's learned tree candidate ranker or v4 CEGIS code.

- The v3 search and priority-ordered exact-fit portfolio remain the synthesis baseline.
- src/esq_oracle.py defines the typed Oracle protocol, strict query screening, deterministic one-query selection, the coordinator, and provenance recorder.
- src/esq_oracle_cli.py is the interactive human adapter entrypoint.
- SubprocessOracle implements the local executable JSON protocol with shell=False, a hard subprocess timeout, exit-code handling and bounded stdout parsing.
- tests/test_esq_v5_oracle.py covers the one-shot boundary, adapters, fallback behavior, provenance and a real subprocess harness integration.
- tests/test_esq_v3_regression_mirror.py preserves the seven verified v3 regression tests without changing the v3 source branch.

The oracle only receives the selected validated input and request metadata. The query planner has no oracle parameter and never sees an answer while selecting a query.

## Oracle protocol

The subprocess adapter writes one JSON object to stdin:

~~~json
{
  "protocol": "esq-oracle-v1",
  "query_id": "…",
  "task_id": "…",
  "inputs": {"x0": [1, 3, 2]},
  "expected_type": "list"
}
~~~

The process must emit one JSON object on stdout:
- {"status":"answered","value":[…]} for a typed value;
- {"status":"skip"} or {"status":"unknown"} to abstain;
- {"status":"timeout"} to report an internal timeout;
- {"status":"error","detail":"..."} for an oracle-side error.

A non-zero exit, malformed JSON, wrong response shape, output above the configured byte limit, or process timeout becomes a typed status. Do not invoke the adapter again for the same task. The synthetic harness receives only that task's target-map file, never the complete target cohort.

## Human CLI

Prepare a session JSON file with task, frozen candidates, and optionally a query_pool / reserved_evaluation_inputs. The CLI accepts a single JSON answer or skip / unknown and never reprompts after malformed input or abstention.

~~~bash
python experiments/P6_ESQ_V5/src/esq_oracle_cli.py session.json \
  --provenance artifacts/oracle_session.jsonl
~~~

## Tests

From the repository root:

~~~bash
python -m unittest discover \
  -s experiments/P6_ESQ_V5/tests -p 'test_esq_v3_regression_mirror.py' -v

python -m unittest discover \
  -s experiments/P6_ESQ_V5/tests -p 'test_esq_v5_oracle.py' -v

python -m py_compile \
  experiments/P6_ESQ_V5/src/esq_oracle.py \
  experiments/P6_ESQ_V5/src/esq_oracle_cli.py \
  experiments/P6_ESQ_V5/evaluation/synthetic_reference_harness.py \
  experiments/P6_ESQ_V5/evaluation/run_fresh_family_evaluation.py
~~~

The v5 tests and preserved v3 regression mirror must pass before the integration gate is complete.

## Fresh-family evaluation run

After both test suites pass, run from the project/repository root with the pinned v3 artifacts available:

~~~bash
python experiments/P6_ESQ_V5/evaluation/run_fresh_family_evaluation.py \
  --task-count 200 \
  --prior-corpus artifacts/esq_v3_synthetic_tasks_100k.jsonl.gz \
  --checkpoint artifacts/esq_v3_model.pt \
  --output-dir artifacts/esq_v5_fresh_confirmation
~~~

The runner refuses a non-empty output directory, verifies the prior corpus hash (100,000 task rows / 54,649 structural families) and the v3 checkpoint hash, generates a new seed stream with zero family overlap against all 100k prior families, and freezes visible projections, query pools, reserved evaluation inputs and code/settings hashes before candidate generation. It freezes v3 candidate portfolios from visible inputs/outputs only; hidden targets are persisted afterward as one-task-per-file target maps for the local subprocess harness.

The default cohort is 200 tasks, with 100 candidate-validated query inputs and 50 reserved fresh evaluation inputs per task. It reports v3 top-1 versus v5 one-shot selection, candidate prevalidation rejection counts, target-undefined oracle responses, timeouts, skips, invalid answers, zero-survivor fallback, fallback rate and latency.

**The result is generator-matched synthetic evidence from new structural families, not an official external ExeDec benchmark.** Query prevalidation can prove that every frozen candidate executes cleanly on a proposed input. It cannot prove that an unseen target program defines an output there without consulting the oracle; doing that would violate the trust boundary. A harness response of unknown therefore causes one-shot fallback and is reported separately.

## Verification snapshot and current gate

Deepnote run 893f0b3b-f223-4de5-a46d-0b1466f8f21e completed successfully on the pre-portability-patch snapshot:
- 7/7 preserved v3 regression tests passed;
- 14/14 v5 unit/integration tests passed, including the real v3 interpreter and subprocess harness test;
- Python compilation passed for the v5 source, CLI, harness and evaluation runner.

After that run, explicit import-path handling was added for the GitHub checkout layout (where v3 search and v2 exact interpreter live in separate source directories). The updated current branch has not yet been rerun through the full test gate. A follow-up Deepnote run was rejected because the user's parallel-project quota is occupied; no other active project was stopped. GitHub Actions also reported startup_failure with no jobs created, so CI has not independently executed these tests.

The dedicated fresh-family evaluation notebook is prepared in the existing v3 Deepnote project:
- Notebook ID: 735d8e4d64a04f6ebf1c366a663ebdd3
- It runs v3/v5 tests and compilation first, then the 200-task fresh-family experiment.
- The evaluation itself has not started and no v5 accuracy or recovery claim is available yet.

## Evidence and claim limits

No v5 fresh-task evaluation result is claimed until the complete fresh-family run has succeeded and its task cohort, family exclusions, visible-only candidate freeze, reserved evaluation inputs, code/settings hashes, query provenance and target map checksums have been committed.

A local harness provides a real process boundary, but when backed by hidden synthetic reference programs the result is still simulated-oracle evaluation. It is not independent official ExeDec evidence, autonomous hidden-output inference, or a general-purpose synthesis result.
