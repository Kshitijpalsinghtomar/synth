from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from esq_dsl.neural_guide import (
    BUNDLED_CHECKPOINT_SHA256,
    NeuralGuide,
    _require_safe_checkpoint_runtime,
)

from esq_dsl.interpreter import execute_program
from esq_dsl.synthesizer import synthesize_priority
from esq_dsl.oracle import (
    OracleResponse,
    OracleStatus,
    ProvenanceRecorder,
    _normalise_candidates,
    propose_one_query,
    generate_query_pool,
    run_one_shot_oracle,
)


class ReleaseSearchTests(unittest.TestCase):
    def test_older_torch_only_accepts_the_hash_pinned_bundled_checkpoint(self) -> None:
        _require_safe_checkpoint_runtime("2.1.2+cu121", BUNDLED_CHECKPOINT_SHA256)
        with self.assertRaisesRegex(ValueError, "CVE-2026-24747"):
            _require_safe_checkpoint_runtime("2.1.2+cu121", "0" * 64)
        _require_safe_checkpoint_runtime("2.10.0", "0" * 64)

    def test_tampered_checkpoint_is_rejected_by_adjacent_model_card(self) -> None:
        source = Path(__file__).resolve().parents[1] / "checkpoints" / "esq_v3_converged.pt"
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / source.name
            checkpoint.write_bytes(source.read_bytes())
            model_card = json.loads(
                (source.parent / "model_card.json").read_text(encoding="utf-8")
            )
            (Path(directory) / "model_card.json").write_text(
                json.dumps(model_card), encoding="utf-8"
            )
            sidecar = source.with_name(source.name + ".sha256")
            (Path(directory) / sidecar.name).write_text(
                sidecar.read_text(encoding="utf-8"), encoding="utf-8"
            )
            damaged = bytearray(checkpoint.read_bytes())
            damaged[-1] ^= 1
            checkpoint.write_bytes(damaged)
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                NeuralGuide(checkpoint)

    def test_model_card_is_required(self) -> None:
        source = Path(__file__).resolve().parents[1] / "checkpoints" / "esq_v3_converged.pt"
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / source.name
            checkpoint.write_bytes(source.read_bytes())
            sidecar = source.with_name(source.name + ".sha256")
            (Path(directory) / sidecar.name).write_text(
                sidecar.read_text(encoding="utf-8"), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "model card is required"):
                NeuralGuide(checkpoint)

    def test_checkpoint_sidecar_is_required(self) -> None:
        source = Path(__file__).resolve().parents[1] / "checkpoints" / "esq_v3_converged.pt"
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / source.name
            checkpoint.write_bytes(source.read_bytes())
            model_card = json.loads(
                (source.parent / "model_card.json").read_text(encoding="utf-8")
            )
            (Path(directory) / "model_card.json").write_text(
                json.dumps(model_card), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "sidecar is required"):
                NeuralGuide(checkpoint)

    def test_typed_map_and_sort_execute(self) -> None:
        program = "x0 = INPUT | " "x1 = Map (+1) x0 | " "x2 = Sort x1"
        self.assertEqual(
            execute_program(program, {"x0": [3, 1, 2]}, strict=True),
            [2, 3, 4],
        )

    def test_three_shortest_distinct_exact_fit_candidates_are_retained(self) -> None:
        task = {
            "inputs": {"x0": [[1, 1], [1, 1], [1, 1]]},
            "outputs": [1, 1, 1],
        }
        result = synthesize_priority(
            task,
            top_k=3,
            max_ops=2,
            max_signatures=5_000,
            timeout_s=5.0,
            strict_intermediates=True,
        )
        self.assertTrue(result.exact_fit)
        self.assertEqual(len(result.candidates), 3)
        self.assertEqual(
            len({row["program"] for row in result.candidates}),
            3,
        )
        self.assertEqual(
            [row["cost"] for row in result.candidates],
            [1, 1, 1],
        )

    def test_profile_matched_query_pool_uses_nearby_lengths_and_values(self) -> None:
        task = {
            "task_id": "profile-check",
            "inputs": {
                "x0": [[4, 5], [3, 6, 5], [4, 4]],
                "x1": [2, 3, 4],
            },
            "outputs": [[5, 4], [6, 5, 3], [4, 4]],
            "input_specs": {
                "x0": {"range": [-50, 50], "length": [0, 5]},
                "x1": {"range": [0, 5]},
            },
        }
        query_pool = generate_query_pool(task, count=150, seed=7)
        visible_rows = [
            {name: values[index] for name, values in task["inputs"].items()}
            for index in range(3)
        ]
        canonical = lambda row: json.dumps(
            row, sort_keys=True, separators=(",", ":")
        )
        self.assertTrue(
            {canonical(row) for row in query_pool}.isdisjoint(
                {canonical(row) for row in visible_rows}
            )
        )
        self.assertEqual(len(query_pool), 150)
        self.assertTrue({len(row["x0"]) for row in query_pool}.issubset({1, 2, 3, 4}))
        self.assertTrue(
            all(-40 <= value <= 40 for row in query_pool for value in row["x0"])
        )

    def test_every_competing_candidate_is_prevalidated(self) -> None:
        task = {
            "task_id": "prevalidate",
            "inputs": {"x0": [[1, 2, 3], [2, 3, 4], [3, 4, 5]]},
            "outputs": [[3, 2, 1], [4, 3, 2], [5, 4, 3]],
            "input_specs": {"x0": {"range": [0, 10], "length": [1, 5]}},
        }
        candidates = _normalise_candidates(
            [
                {"program": "reverse", "exact_fit": True},
                {"program": "broken", "exact_fit": True},
                {"program": "sort", "exact_fit": True},
            ]
        )

        def executor(program, inputs):
            if program == "broken":
                return None
            if program == "reverse":
                return list(reversed(inputs["x0"]))
            return sorted(inputs["x0"])

        proposal, stats = propose_one_query(
            task,
            candidates,
            [{"x0": [1, 4, 2]}],
            executor=executor,
        )
        self.assertIsNone(proposal)
        self.assertEqual(stats["candidate_execution_rejections"], 1)

    def test_unknown_oracle_response_falls_back_to_frozen_best(self) -> None:
        task = {
            "task_id": "fallback",
            "inputs": {"x0": [[1, 1], [2, 2], [3, 3]]},
            "outputs": [[1, 1], [2, 2], [3, 3]],
        }
        rows = [
            {"program": "x0 = INPUT", "exact_fit": True, "cost": 0},
            {
                "program": "x0 = INPUT | x1 = Reverse x0",
                "exact_fit": True,
                "cost": 1,
            },
        ]

        class UnknownOracle:
            adapter_name = "test_unknown"

            def ask(self, request):
                return OracleResponse(
                    OracleStatus.SKIPPED,
                    detail="unknown",
                )

        result = run_one_shot_oracle(
            task,
            rows,
            [{"x0": [4, 5]}],
            UnknownOracle(),
            executor=lambda program, inputs: (
                inputs["x0"]
                if "Reverse" not in program
                else list(reversed(inputs["x0"]))
            ),
            recorder=ProvenanceRecorder(),
        )
        self.assertEqual(result.status, "fallback")
        self.assertEqual(result.selected_candidate.program, rows[0]["program"])
        self.assertEqual(result.fallback_reason, "oracle_skipped")


if __name__ == "__main__":
    unittest.main()
