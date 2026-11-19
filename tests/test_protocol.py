from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from typing import Any

from esq_dsl.interpreter import execute_program
from esq_dsl.oracle import (
    HumanCLIOracle,
    OracleRequest,
    OracleResponse,
    OracleStatus,
    ProvenanceRecorder,
    SubprocessOracle,
    _normalise_candidates,
    generate_query_pool,
    propose_one_query,
    run_one_shot_oracle,
)

ROOT = Path(__file__).resolve().parents[1]


class SimulatedCrash(RuntimeError):
    pass


class SimulatedProcessDeath(BaseException):
    pass


class CrashAfterEventRecorder(ProvenanceRecorder):
    def __init__(self, path: Path, crash_after: str, attempt_id: str):
        super().__init__(
            path,
            durable_events={"query_proposed", "oracle_requested", "oracle_response"},
        )
        self.crash_after = crash_after
        self.attempt_id = attempt_id

    def emit(self, event: str, **details: Any) -> dict[str, Any]:
        record = super().emit(event, **details)
        if event == self.crash_after:
            raise SimulatedCrash(f"simulated stop after {event}")
        return record


class CachedIdempotentOracle:
    adapter_name = "test_cached_idempotent"

    def __init__(self):
        self.cache = {}
        self.calls = 0
        self.side_effect_keys = []

    def ask(self, request):
        self.calls += 1
        key = request.idempotency_key
        if key not in self.cache:
            self.side_effect_keys.append(key)
            self.cache[key] = OracleResponse(OracleStatus.ANSWERED, [2, 4, 1])
        return self.cache[key]


class OneShotProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.task = {
            "task_id": "oracle-test",
            "inputs": {"x0": [[1, 2, 3], [2, 3, 4], [3, 4, 5]]},
            "outputs": [[3, 2, 1], [4, 3, 2], [5, 4, 3]],
            "input_specs": {"x0": {"range": [0, 10], "length": [1, 5]}},
        }
        self.candidates = [
            {"program": "x0 = INPUT | x1 = Reverse x0", "exact_fit": True, "cost": 1},
            {"program": "x0 = INPUT | x1 = Sort x0", "exact_fit": True, "cost": 1},
        ]

    def test_human_oracle_consumes_one_json_response(self) -> None:
        prompts = []

        def answer(prompt: str) -> str:
            prompts.append(prompt)
            return "[2, 4, 1]"

        oracle = HumanCLIOracle(input_fn=answer)
        response = oracle.ask(
            OracleRequest("query-1", "task-1", {"x0": [1, 4, 2]}, "list")
        )
        self.assertEqual(response.status, OracleStatus.ANSWERED)
        self.assertEqual(response.value, [2, 4, 1])
        self.assertEqual(len(prompts), 1)

    def test_unknown_response_falls_back_without_retry(self) -> None:
        class UnknownOracle:
            adapter_name = "test_unknown"

            def __init__(self) -> None:
                self.calls = 0

            def ask(self, request):
                self.calls += 1
                return OracleResponse(OracleStatus.SKIPPED, detail="unknown")

        oracle = UnknownOracle()
        result = run_one_shot_oracle(
            self.task,
            self.candidates,
            [{"x0": [1, 4, 2]}],
            oracle,
            executor=lambda program, inputs: execute_program(
                program, inputs, strict=True
            ),
            recorder=ProvenanceRecorder(),
        )
        self.assertEqual(oracle.calls, 1)
        self.assertEqual(result.status, "fallback")
        self.assertEqual(
            result.selected_candidate.program,
            self.candidates[0]["program"],
        )
        self.assertEqual(result.fallback_reason, "oracle_skipped")

    def test_answer_selects_only_a_matching_frozen_candidate(self) -> None:
        class AnswerOracle:
            adapter_name = "test_answer"

            def __init__(self) -> None:
                self.calls = 0

            def ask(self, request):
                self.calls += 1
                return OracleResponse(OracleStatus.ANSWERED, [2, 4, 1])

        oracle = AnswerOracle()
        result = run_one_shot_oracle(
            self.task,
            self.candidates,
            [{"x0": [1, 4, 2]}],
            oracle,
            executor=lambda program, inputs: execute_program(
                program, inputs, strict=True
            ),
            recorder=ProvenanceRecorder(),
        )
        self.assertEqual(oracle.calls, 1)
        self.assertEqual(result.status, "answered")
        self.assertEqual(
            result.selected_candidate.program,
            self.candidates[0]["program"],
        )
        self.assertEqual(len(result.survivors), 1)

    def test_zero_survivors_fall_back_to_original_best(self) -> None:
        class WrongOracle:
            adapter_name = "test_wrong"

            def ask(self, request):
                return OracleResponse(OracleStatus.ANSWERED, [7, 8, 9])

        result = run_one_shot_oracle(
            self.task,
            self.candidates,
            [{"x0": [1, 4, 2]}],
            WrongOracle(),
            executor=lambda program, inputs: execute_program(
                program, inputs, strict=True
            ),
            recorder=ProvenanceRecorder(),
        )
        self.assertEqual(result.status, "fallback")
        self.assertEqual(result.fallback_reason, "zero_survivors")
        self.assertEqual(
            result.selected_candidate.program,
            self.candidates[0]["program"],
        )

    def test_local_subprocess_harness_implements_oracle_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target_map = Path(temp) / "target.json"
            target_map.write_text(
                json.dumps({"task-1": "x0 = INPUT | x1 = Reverse x0"}),
                encoding="utf-8",
            )
            adapter = ROOT / "benchmarks" / "oracle_adapter.py"
            oracle = SubprocessOracle(
                [sys.executable, str(adapter), str(target_map)],
                timeout_s=15.0,
            )
            response = oracle.ask(
                OracleRequest("q-1", "task-1", {"x0": [1, 4, 2]}, "list")
            )
        self.assertEqual(response.status, OracleStatus.ANSWERED)
        self.assertEqual(response.value, [2, 4, 1])

    def test_query_pool_is_deterministic_and_within_input_specs(self) -> None:
        first = generate_query_pool(self.task, count=100, seed=17)
        second = generate_query_pool(self.task, count=100, seed=17)
        self.assertEqual(first, second)
        self.assertTrue(all(0 <= value <= 10 for row in first for value in row["x0"]))


    def test_query_pool_excludes_preflight_calibration_inputs(self) -> None:
        baseline = generate_query_pool(self.task, count=100, seed=919)
        excluded = baseline[0]
        filtered = generate_query_pool(
            self.task, count=100, seed=919, exclude_inputs=[excluded]
        )
        self.assertEqual(len(filtered), 100)
        self.assertNotIn(excluded, filtered)

    def test_one_invalid_candidate_rejects_the_proposed_query(self) -> None:
        candidates = _normalise_candidates(
            [
                {"program": "reverse", "exact_fit": True},
                {"program": "undefined", "exact_fit": True},
            ]
        )

        def executor(program, inputs):
            if program == "undefined":
                return None
            return list(reversed(inputs["x0"]))

        proposal, stats = propose_one_query(
            self.task,
            candidates,
            [{"x0": [1, 4, 2]}],
            executor=executor,
        )
        self.assertIsNone(proposal)
        self.assertEqual(stats["candidate_execution_rejections"], 1)

    def test_benchmark_journal_fsyncs_the_query_proposal_before_oracle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.jsonl"
            recorder = ProvenanceRecorder(
                path,
                durable_events={"query_proposed"},
            )
            with patch("esq_dsl.oracle.os.fsync") as fsync:
                recorder.emit("portfolio_frozen", candidate_count=2)
                fsync.assert_not_called()
                recorder.emit("query_proposed", query_id="query-1")
                fsync.assert_called_once()
                recorder.emit("oracle_requested", query_id="query-1")
                fsync.assert_called_once()
            rows = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                [row["event"] for row in rows],
                ["portfolio_frozen", "query_proposed", "oracle_requested"],
            )

    def test_oracle_retries_reuse_idempotency_key_and_tag_distinct_attempts(self) -> None:
        class IdempotentOracle:
            adapter_name = "test_idempotent"

            def __init__(self):
                self.cache = {}
                self.side_effect_keys = []

            def ask(self, request):
                self.asserted_key = request.idempotency_key
                if request.idempotency_key not in self.cache:
                    self.side_effect_keys.append(request.idempotency_key)
                    self.cache[request.idempotency_key] = OracleResponse(
                        OracleStatus.ANSWERED, [2, 4, 1]
                    )
                return self.cache[request.idempotency_key]

        oracle = IdempotentOracle()
        recorders = [ProvenanceRecorder(), ProvenanceRecorder()]
        results = []
        for attempt_id, recorder in zip(("attempt-A", "attempt-B"), recorders):
            results.append(run_one_shot_oracle(
                self.task,
                self.candidates,
                [{"x0": [1, 4, 2]}],
                oracle,
                executor=lambda program, inputs: execute_program(
                    program, inputs, strict=True
                ),
                recorder=recorder,
                attempt_id=attempt_id,
            ))
        self.assertEqual(oracle.side_effect_keys, [results[0].query.query_id])
        self.assertEqual(results[0].query.query_id, results[1].query.query_id)
        for attempt_id, recorder in zip(("attempt-A", "attempt-B"), recorders):
            self.assertTrue(recorder.events)
            self.assertEqual(
                {event["attempt_id"] for event in recorder.events}, {attempt_id}
            )
            requested = next(
                event for event in recorder.events if event["event"] == "oracle_requested"
            )
            self.assertEqual(
                requested["idempotency_key"], results[0].query.query_id
            )


    def test_durable_oracle_response_hash_is_verified_before_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.jsonl"
            oracle = CachedIdempotentOracle()
            first = CrashAfterEventRecorder(path, "oracle_response", "attempt-A")
            with self.assertRaises(SimulatedCrash):
                run_one_shot_oracle(
                    self.task, self.candidates, [{"x0": [1, 4, 2]}], oracle,
                    executor=lambda program, inputs: execute_program(
                        program, inputs, strict=True
                    ),
                    recorder=first, attempt_id="attempt-A",
                )
            rows = [
                json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            ]
            response = next(row for row in rows if row["event"] == "oracle_response")
            response["response_value"] = [1, 2, 3]  # Keep the original SHA-256.
            path.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
                encoding="utf-8",
            )
            resumed = ProvenanceRecorder(
                path,
                durable_events={"query_proposed", "oracle_requested", "oracle_response"},
            )
            result = run_one_shot_oracle(
                self.task, self.candidates, [{"x0": [1, 4, 2]}], oracle,
                executor=lambda program, inputs: execute_program(
                    program, inputs, strict=True
                ),
                recorder=resumed, attempt_id="attempt-B",
            )
            replayed = [
                json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            ]
        self.assertEqual(result.status, "fallback")
        self.assertEqual(result.fallback_reason, "oracle_invalid_response")
        self.assertEqual(oracle.calls, 1)
        self.assertEqual(
            sum(row["event"] == "oracle_requested" for row in replayed), 1
        )

    def test_resume_after_query_proposed_crash_reuses_stable_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.jsonl"
            oracle = CachedIdempotentOracle()
            first = CrashAfterEventRecorder(path, "query_proposed", "attempt-A")
            with self.assertRaises(SimulatedCrash):
                run_one_shot_oracle(
                    self.task, self.candidates, [{"x0": [1, 4, 2]}], oracle,
                    executor=lambda program, inputs: execute_program(
                        program, inputs, strict=True
                    ),
                    recorder=first, attempt_id="attempt-A",
                )
            first_events = [
                json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(first_events[-1]["event"], "query_proposed")
            self.assertEqual(oracle.calls, 0)
            query_id = first_events[-1]["query_id"]

            resumed = ProvenanceRecorder(
                path,
                durable_events={"query_proposed", "oracle_requested", "oracle_response"},
            )
            result = run_one_shot_oracle(
                self.task, self.candidates, [{"x0": [1, 4, 2]}], oracle,
                executor=lambda program, inputs: execute_program(
                    program, inputs, strict=True
                ),
                recorder=resumed, attempt_id="attempt-B",
            )
            all_events = [
                json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            ]
        self.assertEqual(result.query.query_id, query_id)
        self.assertEqual(oracle.side_effect_keys, [query_id])
        self.assertEqual(
            {event["attempt_id"] for event in all_events},
            {"attempt-A", "attempt-B"},
        )
        self.assertEqual(
            sum(event["event"] == "oracle_requested" for event in all_events), 1
        )

    def test_resume_after_oracle_response_crash_does_not_duplicate_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.jsonl"
            oracle = CachedIdempotentOracle()
            first = CrashAfterEventRecorder(path, "oracle_response", "attempt-A")
            with self.assertRaises(SimulatedCrash):
                run_one_shot_oracle(
                    self.task, self.candidates, [{"x0": [1, 4, 2]}], oracle,
                    executor=lambda program, inputs: execute_program(
                        program, inputs, strict=True
                    ),
                    recorder=first, attempt_id="attempt-A",
                )
            first_events = [
                json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(first_events[-1]["event"], "oracle_response")
            query_id = first_events[-1]["query_id"]
            self.assertEqual(oracle.side_effect_keys, [query_id])

            resumed = ProvenanceRecorder(
                path,
                durable_events={"query_proposed", "oracle_requested", "oracle_response"},
            )
            result = run_one_shot_oracle(
                self.task, self.candidates, [{"x0": [1, 4, 2]}], oracle,
                executor=lambda program, inputs: execute_program(
                    program, inputs, strict=True
                ),
                recorder=resumed, attempt_id="attempt-B",
            )
            all_events = [
                json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            ]
        self.assertEqual(result.status, "answered")
        self.assertEqual(result.query.query_id, query_id)
        # The durable answer is replayed from provenance; the adapter is not
        # called a second time after a crash between response and arm checkpoint.
        self.assertEqual(oracle.calls, 1)
        self.assertEqual(oracle.side_effect_keys, [query_id])
        self.assertEqual(
            {event["attempt_id"] for event in all_events},
            {"attempt-A", "attempt-B"},
        )
        self.assertEqual(
            sum(event["event"] == "oracle_requested" for event in all_events), 1
        )
        self.assertEqual(
            sum(event["event"] == "oracle_response" for event in all_events), 1
        )
        self.assertEqual(
            sum(event["event"] == "oracle_response_reused" for event in all_events), 1
        )

    def test_resume_after_oracle_requested_crash_uses_same_idempotency_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.jsonl"
            oracle = CachedIdempotentOracle()
            first = CrashAfterEventRecorder(path, "oracle_requested", "attempt-A")
            with self.assertRaises(SimulatedCrash):
                run_one_shot_oracle(
                    self.task, self.candidates, [{"x0": [1, 4, 2]}], oracle,
                    executor=lambda program, inputs: execute_program(
                        program, inputs, strict=True
                    ),
                    recorder=first, attempt_id="attempt-A",
                )
            self.assertEqual(oracle.calls, 0)
            first_request = next(
                event for event in first.events if event["event"] == "oracle_requested"
            )
            second = ProvenanceRecorder(
                path,
                durable_events={"query_proposed", "oracle_requested", "oracle_response"},
            )
            result = run_one_shot_oracle(
                self.task, self.candidates, [{"x0": [1, 4, 2]}], oracle,
                executor=lambda program, inputs: execute_program(
                    program, inputs, strict=True
                ),
                recorder=second, attempt_id="attempt-B",
            )
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        requests = [row for row in rows if row["event"] == "oracle_requested"]
        self.assertEqual(result.status, "answered")
        self.assertEqual(len(requests), 2)
        self.assertEqual(
            {row["idempotency_key"] for row in requests},
            {first_request["idempotency_key"]},
        )
        self.assertEqual(oracle.calls, 1)
        self.assertEqual(oracle.side_effect_keys, [first_request["idempotency_key"]])

    def test_provider_idempotency_covers_crash_after_side_effect_before_response_log(self) -> None:
        class CrashOnceAfterSideEffect(CachedIdempotentOracle):
            def ask(self, request):
                response = super().ask(request)
                if self.calls == 1:
                    raise SimulatedProcessDeath()
                return response

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.jsonl"
            oracle = CrashOnceAfterSideEffect()
            first = ProvenanceRecorder(
                path,
                durable_events={"query_proposed", "oracle_requested", "oracle_response"},
            )
            with self.assertRaises(SimulatedProcessDeath):
                run_one_shot_oracle(
                    self.task, self.candidates, [{"x0": [1, 4, 2]}], oracle,
                    executor=lambda program, inputs: execute_program(
                        program, inputs, strict=True
                    ),
                    recorder=first, attempt_id="attempt-A",
                )
            rows_before = [
                json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertFalse(any(row["event"] == "oracle_response" for row in rows_before))
            second = ProvenanceRecorder(
                path,
                durable_events={"query_proposed", "oracle_requested", "oracle_response"},
            )
            result = run_one_shot_oracle(
                self.task, self.candidates, [{"x0": [1, 4, 2]}], oracle,
                executor=lambda program, inputs: execute_program(
                    program, inputs, strict=True
                ),
                recorder=second, attempt_id="attempt-B",
            )
        self.assertEqual(result.status, "answered")
        self.assertEqual(oracle.calls, 2)
        self.assertEqual(len(oracle.side_effect_keys), 1)

    def test_subprocess_adapter_receives_oracle_idempotency_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            observed = Path(temp) / "idempotency-key.txt"
            script = (
                "import json, pathlib, sys; "
                "payload=json.load(sys.stdin); "
                "pathlib.Path(sys.argv[1]).write_text(payload['idempotency_key']); "
                "print(json.dumps({'status':'answered','value':[3,2,1]}))"
            )
            oracle = SubprocessOracle([sys.executable, "-c", script, str(observed)])
            response = oracle.ask(
                OracleRequest(
                    "query-1", "task-1", {"x0": [1, 2, 3]}, "list",
                    idempotency_key="stable-request-1",
                )
            )
            self.assertEqual(response.status, OracleStatus.ANSWERED)
            self.assertEqual(observed.read_text(encoding="utf-8"), "stable-request-1")


    def test_provenance_recorder_truncates_torn_tail_before_appending(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.jsonl"
            previous = {
                "seq": 0, "timestamp_utc": "2026-01-01T00:00:00+00:00",
                "event": "previous",
            }
            path.write_text(
                json.dumps(previous) + "\n" + '{"seq":1,"event":',
                encoding="utf-8",
            )
            recorder = ProvenanceRecorder(path)
            recorder.emit("resumed")
            rows = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
            ]
        self.assertEqual([row["seq"] for row in rows], [0, 1])
        self.assertEqual([row["event"] for row in rows], ["previous", "resumed"])

    def test_provenance_recorder_rejects_corruption_in_complete_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.jsonl"
            path.write_text(
                '{"seq":0,"event":"valid"}\n{not-json}\n',
                encoding="utf-8",
            )
            with self.assertRaises(json.JSONDecodeError):
                ProvenanceRecorder(path)


if __name__ == "__main__":
    unittest.main()
