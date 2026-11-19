from __future__ import annotations

import gzip
import json
import hashlib
import sys
from types import SimpleNamespace
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
import run_four_way
from benchmarks.families import generate_synthetic_task_v3
from benchmarks.provenance import capture_source_manifest, verify_source_manifest, sha256_file
from benchmarks.score_frozen_four_way import verify_cohort_source_manifest, _verify_preflight_artifacts


class FrozenBenchmarkInputTests(unittest.TestCase):
    def test_packed_archive_round_trips_full_sha256_membership(self) -> None:
        expected = {
            hashlib.sha256(b"family-a").hexdigest(),
            hashlib.sha256(b"family-b").hexdigest(),
            hashlib.sha256(b"family-c").hexdigest(),
        }
        packed = b"".join(bytes.fromhex(item) for item in sorted(expected))
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "prior_family_hashes.bin.gz"
            archive.write_bytes(gzip.compress(packed, compresslevel=9, mtime=0))
            archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
            with (
                patch.object(run_four_way, "PRIOR_FAMILY_COUNT", len(expected)),
                patch.object(run_four_way, "PRIOR_FAMILY_BINARY_SHA256", archive_sha),
            ):
                loaded, digest = run_four_way.load_prior_families(archive)
        self.assertEqual(loaded, expected)
        self.assertEqual(digest, archive_sha)

    def test_source_manifest_detects_changed_source_and_lock_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "src.py"
            lock = root / "requirements.lock"
            declaration = root / "pyproject.toml"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            lock.write_text("example==1.2.3\n", encoding="utf-8")
            declaration.write_text("[project]\nname='demo'\n", encoding="utf-8")
            manifest = capture_source_manifest(
                root, ["src.py", "requirements.lock", "pyproject.toml"]
            )
            self.assertEqual(verify_source_manifest(root, manifest), [])
            self.assertEqual(
                manifest["environment"]["dependency_lock_files_sha256"]["requirements.lock"],
                sha256_file(lock),
            )
            self.assertIn("remote_url", manifest["git"])
            self.assertIn("dirty_worktree", manifest["git"])
            self.assertIn("machine", manifest["environment"])
            self.assertIn("processor", manifest["environment"])
            source.write_text("VALUE = 2\n", encoding="utf-8")
            lock.write_text("example==2.0.0\n", encoding="utf-8")
            mismatches = verify_source_manifest(root, manifest)
        self.assertIn("changed:src.py", mismatches)
        self.assertIn("changed:requirements.lock", mismatches)
        self.assertEqual(
            [item for item in mismatches if item.startswith("environment:")], []
        )

    def test_scorer_rejects_source_manifest_drift_before_scoring(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "frozen"
            source.mkdir()
            code = root / "src.py"
            code.write_text("VALUE = 1\n", encoding="utf-8")
            source_manifest = capture_source_manifest(root, ["src.py"])
            manifest_path = source / "source_manifest.json"
            manifest_path.write_text(
                json.dumps(source_manifest, sort_keys=True, indent=2),
                encoding="utf-8",
            )
            digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            cohort = {
                "source_manifest_file": "source_manifest.json",
                "source_manifest_sha256": digest,
            }
            self.assertEqual(
                verify_cohort_source_manifest(root, source, cohort), digest
            )
            code.write_text("VALUE = 2\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source/runtime provenance mismatch"):
                verify_cohort_source_manifest(root, source, cohort)

    def test_legacy_cohort_without_source_manifest_is_not_backfilled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIsNone(verify_cohort_source_manifest(root, root, {}))

    def test_symbolic_and_guided_search_receive_strict_intermediate_policy(self) -> None:
        task = {
            "task_id": "strict-policy",
            "inputs": {"x0": [[1, 2], [2, 3], [3, 4]]},
            "outputs": [[1, 2], [2, 3], [3, 4]],
            "input_specs": {"x0": {"range": [0, 5], "length": [1, 3]}},
        }
        result = SimpleNamespace(
            program="x0 = INPUT",
            candidates=[],
            exact_fit=True,
            examples_matched=3,
            elapsed_ms=1.0,
            truncated=False,
        )
        with patch.object(run_four_way.core, "synthesize", return_value=result) as symbolic:
            run_four_way.synthesize(task, "v1_symbolic", None)
        self.assertIs(
            symbolic.call_args.kwargs["strict_intermediates"], True
        )

        with patch.object(run_four_way, "synthesize_priority", return_value=result) as guided:
            run_four_way.synthesize(task, "v5_ablation", None)
        self.assertIs(
            guided.call_args.kwargs["strict_intermediates"], True
        )

    def test_future_four_way_policy_aligns_search_and_target_depth(self) -> None:
        self.assertTrue(run_four_way.STRICT_INTERMEDIATES)
        self.assertEqual(run_four_way.MAX_TARGET_OPS, run_four_way.MAX_OPS)
        task = generate_synthetic_task_v3(
            seed=20261117, task_index=1, max_ops=run_four_way.MAX_TARGET_OPS
        )
        self.assertLessEqual(task["operator_count"], run_four_way.MAX_OPS)


    def test_preflight_is_deterministic_disjoint_and_counts_strict_validity(self) -> None:
        task = generate_synthetic_task_v3(
            seed=20261117, task_index=1, max_ops=run_four_way.MAX_TARGET_OPS
        )
        task["task_id"] = "preflight-test"
        first = run_four_way.preflight_target_inputs(task)
        second = run_four_way.preflight_target_inputs(task)

        self.assertEqual(first, second)
        self.assertEqual(first["sample_count"], run_four_way.PREFLIGHT_SAMPLE_SIZE)
        self.assertEqual(len(first["inputs"]), run_four_way.PREFLIGHT_SAMPLE_SIZE)
        visible_rows = [
            {name: values[index] for name, values in task["inputs"].items()}
            for index in range(len(task["outputs"]))
        ]
        preflight_keys = {run_four_way.canonical(row) for row in first["inputs"]}
        self.assertEqual(len(preflight_keys), run_four_way.PREFLIGHT_SAMPLE_SIZE)
        self.assertTrue(
            preflight_keys.isdisjoint(run_four_way.canonical(row) for row in visible_rows)
        )
        independently_valid = 0
        for row in first["inputs"]:
            try:
                value = run_four_way.core.execute_program(
                    task["program"], row, strict=True
                )
            except (ArithmeticError, TypeError, ValueError, IndexError):
                value = None
            independently_valid += int(value is not None)
        self.assertEqual(first["valid_count"], independently_valid)
        self.assertEqual(
            first["eligible"],
            independently_valid >= run_four_way.PREFLIGHT_MIN_VALID_CASES,
        )
        self.assertLessEqual(task["operator_count"], run_four_way.MAX_OPS)

    def test_stream_preparation_rejects_short_query_pool(self) -> None:
        attempt = 493
        task = generate_synthetic_task_v3(
            seed=run_four_way.SEED_BASE + attempt * run_four_way.SEED_STRIDE,
            task_index=attempt,
            max_ops=run_four_way.MAX_TARGET_OPS,
        )
        task["task_id"] = "synth-200-0098"
        preflight = run_four_way.preflight_target_inputs(task)
        self.assertTrue(preflight["eligible"])

        streams = run_four_way.prepare_disjoint_input_streams(
            task, preflight["inputs"], index=98
        )

        self.assertEqual(streams["query_pool_count"], 56)
        self.assertEqual(streams["reserved_evaluation_input_count"], 0)
        self.assertEqual(streams["rejection_reason"], "query_pool_capacity")

    def test_stream_preparation_rejects_missing_reserved_input_capacity(self) -> None:
        attempt = 554
        task = generate_synthetic_task_v3(
            seed=run_four_way.SEED_BASE + attempt * run_four_way.SEED_STRIDE,
            task_index=attempt,
            max_ops=run_four_way.MAX_TARGET_OPS,
        )
        task["task_id"] = "synth-200-0110"
        preflight = run_four_way.preflight_target_inputs(task)
        self.assertTrue(preflight["eligible"])

        streams = run_four_way.prepare_disjoint_input_streams(
            task, preflight["inputs"], index=110
        )

        self.assertEqual(streams["query_pool_count"], run_four_way.QUERY_COUNT)
        self.assertEqual(streams["reserved_evaluation_input_count"], 0)
        self.assertEqual(streams["rejection_reason"], "reserved_evaluation_input_capacity")

    def test_stream_preparation_keeps_full_pools_pairwise_disjoint(self) -> None:
        attempt = 2
        task = generate_synthetic_task_v3(
            seed=run_four_way.SEED_BASE + attempt * run_four_way.SEED_STRIDE,
            task_index=attempt,
            max_ops=run_four_way.MAX_TARGET_OPS,
        )
        task["task_id"] = "synth-200-0000"
        preflight = run_four_way.preflight_target_inputs(task)
        self.assertTrue(preflight["eligible"])

        streams = run_four_way.prepare_disjoint_input_streams(
            task, preflight["inputs"], index=0
        )

        self.assertIsNone(streams["rejection_reason"])
        self.assertEqual(streams["query_pool_count"], run_four_way.QUERY_COUNT)
        self.assertEqual(
            streams["reserved_evaluation_input_count"], run_four_way.EVAL_COUNT
        )
        visible_rows = [
            {name: values[index] for name, values in task["inputs"].items()}
            for index in range(len(task["outputs"]))
        ]
        groups = [
            {run_four_way.canonical(row) for row in visible_rows},
            {run_four_way.canonical(row) for row in preflight["inputs"]},
            {run_four_way.canonical(row) for row in streams["query_pool"]},
            {
                run_four_way.canonical(row)
                for row in streams["reserved_evaluation_inputs"]
            },
        ]
        for index, current in enumerate(groups):
            for other in groups[index + 1:]:
                self.assertTrue(current.isdisjoint(other))

    def test_cohort_generation_rejects_preflight_and_stream_failures_before_acceptance(self) -> None:
        def candidate(seed: int, family: str) -> dict:
            return {
                "seed": seed,
                "program": "x0 = INPUT | x1 = Reverse x0",
                "program_family_hash": family,
                "operator_count": 1,
                "inputs": {"x0": [[1, 2], [2, 3], [3, 4]]},
                "outputs": [[2, 1], [3, 2], [4, 3]],
                "input_specs": {"x0": {"range": [0, 5], "length": [1, 4]}},
                "input_types": {"x0": "list"},
            }

        first = candidate(11, "a" * 64)
        second = candidate(22, "b" * 64)
        third = candidate(33, "c" * 64)
        outcomes = [
            {
                "seed": 101,
                "inputs": [{"x0": [1, 2]}] * 50,
                "sample_count": 50,
                "valid_count": 24,
                "input_sha256": "1" * 64,
                "eligible": False,
            },
            {
                "seed": 202,
                "inputs": [{"x0": [2, 3]}] * 50,
                "sample_count": 50,
                "valid_count": 25,
                "input_sha256": "2" * 64,
                "eligible": True,
            },
            {
                "seed": 303,
                "inputs": [{"x0": [3, 4]}] * 50,
                "sample_count": 50,
                "valid_count": 50,
                "input_sha256": "3" * 64,
                "eligible": True,
            },
        ]
        rejected_streams = {
            "query_pool": [],
            "reserved_evaluation_inputs": [],
            "query_pool_count": 56,
            "reserved_evaluation_input_count": 0,
            "rejection_reason": "query_pool_capacity",
        }
        accepted_streams = {
            "query_pool": [{"x0": [index]} for index in range(100)],
            "reserved_evaluation_inputs": [{"x0": [index + 1000]} for index in range(50)],
            "query_pool_count": 100,
            "reserved_evaluation_input_count": 50,
            "rejection_reason": None,
        }
        records = []
        with (
            patch.object(
                run_four_way,
                "generate_synthetic_task_v3",
                side_effect=[first, second, third],
            ),
            patch.object(
                run_four_way,
                "preflight_target_inputs",
                side_effect=outcomes,
            ),
            patch.object(
                run_four_way,
                "prepare_disjoint_input_streams",
                side_effect=[rejected_streams, accepted_streams],
            ),
        ):
            tasks, attempts = run_four_way.generate_cohort(
                set(), 1, max_target_ops=run_four_way.MAX_OPS,
                preflight_records=records,
            )

        self.assertEqual(attempts, 3)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["program_family_hash"], "c" * 64)
        self.assertEqual(tasks[0]["task_id"], "synth-200-0000")
        self.assertEqual(len(tasks[0]["query_pool"]), 100)
        self.assertEqual(len(tasks[0]["reserved_evaluation_inputs"]), 50)
        self.assertEqual(len(records), 3)
        self.assertFalse(records[0]["accepted"])
        self.assertEqual(records[0]["rejection_reason"], "target_preflight")
        self.assertFalse(records[1]["accepted"])
        self.assertEqual(records[1]["rejection_reason"], "query_pool_capacity")
        self.assertTrue(records[2]["accepted"])
        self.assertEqual(records[2]["valid_count"], 50)


    def test_v6_scorer_verifies_preflight_hashes_stream_isolation_and_depth_policy(self) -> None:
        task = {
            "task_id": "synth-200-0000",
            "seed": 20261117,
            "program": "x0 = INPUT | x1 = Reverse x0",
            "program_family_hash": "a" * 64,
            "operator_count": 1,
            "inputs": {"x0": [[1, 2], [2, 3], [3, 4]]},
            "outputs": [[2, 1], [3, 2], [4, 3]],
            "input_types": {"x0": "list"},
            "input_specs": {"x0": {"range": [0, 5], "length": [1, 4]}},
        }
        preflight = run_four_way.preflight_target_inputs(task)
        self.assertTrue(preflight["eligible"])
        task["preflight_inputs"] = preflight["inputs"]
        task["preflight_seed"] = preflight["seed"]
        task["preflight_valid_count"] = preflight["valid_count"]

        query_pool = run_four_way.generate_query_pool(
            run_four_way.visible_projection(task),
            count=run_four_way.QUERY_COUNT,
            seed=991,
            exclude_inputs=preflight["inputs"],
        )
        reserved = run_four_way.reserve_inputs(
            task, query_pool, 0, excluded_inputs=preflight["inputs"]
        )
        query_by_task = {
            task["task_id"]: {
                "query_pool": query_pool,
                "reserved_evaluation_inputs": reserved,
            }
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs_path = root / "preflight_inputs.jsonl"
            report_path = root / "preflight_report.json"
            inputs_sha = run_four_way.write_jsonl(
                inputs_path,
                [{
                    "task_id": task["task_id"],
                    "sample_seed": preflight["seed"],
                    "sample_size": 50,
                    "valid_count": preflight["valid_count"],
                    "input_sha256": preflight["input_sha256"],
                    "inputs": preflight["inputs"],
                }],
            )
            report = {
                "schema_version": 1,
                "policy": {
                    "target_max_ops": 4,
                    "strict_intermediates": True,
                    "sample_size": 50,
                    "minimum_valid_inputs": 25,
                    "query_pool_size": run_four_way.QUERY_COUNT,
                    "reserved_evaluation_inputs_per_task": run_four_way.EVAL_COUNT,
                    "require_full_unique_streams": True,
                },
                "accepted_task_count": 1,
                "candidates_evaluated": 1,
                "candidates_rejected": 0,
                "rejection_counts": {
                    "target_preflight": 0,
                    "query_pool_capacity": 0,
                    "reserved_evaluation_input_capacity": 0,
                },
                "records": [{
                    "task_id": task["task_id"],
                    "accepted": True,
                    "preflight_eligible": True,
                    "stream_feasible": True,
                    "query_pool_count": run_four_way.QUERY_COUNT,
                    "reserved_evaluation_input_count": run_four_way.EVAL_COUNT,
                    "sample_size": 50,
                    "valid_count": preflight["valid_count"],
                    "input_sha256": preflight["input_sha256"],
                }],
            }
            report_path.write_text(
                json.dumps(report, sort_keys=True, indent=2),
                encoding="utf-8",
            )
            cohort = {
                "experiment": "SYNTH-ESQ-V6-FOUR-WAY-200",
                "target_max_ops": 4,
                "search": {"max_ops": 4, "strict_intermediates": True},
                "preflight_sample_size": 50,
                "preflight_min_valid_cases": 25,
                "preflight_report_file": report_path.name,
                "preflight_report_sha256": run_four_way.sha_file(report_path),
                "preflight_inputs_file": inputs_path.name,
                "preflight_inputs_sha256": inputs_sha,
                "preflight_accepted_tasks": 1,
                "preflight_candidates_rejected": 0,
                "preflight_candidates_evaluated": 1,
                "query_pool_size": run_four_way.QUERY_COUNT,
                "reserved_evaluation_inputs_per_task": run_four_way.EVAL_COUNT,
                "target_preflight_rejections": 0,
                "query_pool_capacity_rejections": 0,
                "reserved_evaluation_input_capacity_rejections": 0,
            }
            _verify_preflight_artifacts(
                root, cohort, [task], query_by_task, run_four_way.core
            )

            truncated = {
                task["task_id"]: {
                    "query_pool": query_pool[:-1],
                    "reserved_evaluation_inputs": reserved,
                }
            }
            with self.assertRaisesRegex(ValueError, "query/reserved input count mismatch"):
                _verify_preflight_artifacts(
                    root, cohort, [task], truncated, run_four_way.core
                )

            overlapping = {
                task["task_id"]: {
                    "query_pool": query_pool[:-1] + [preflight["inputs"][0]],
                    "reserved_evaluation_inputs": reserved,
                }
            }
            with self.assertRaisesRegex(ValueError, "streams overlap"):
                _verify_preflight_artifacts(
                    root, cohort, [task], overlapping, run_four_way.core
                )

            invalid_depth = dict(cohort)
            invalid_depth["target_max_ops"] = 6
            with self.assertRaisesRegex(ValueError, "strict-semantics depth 4"):
                _verify_preflight_artifacts(
                    root, invalid_depth, [task], query_by_task, run_four_way.core
                )

    def test_packed_archive_rejects_wrong_digest(self) -> None:
        packed = bytes.fromhex(hashlib.sha256(b"family-a").hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "prior_family_hashes.bin.gz"
            archive.write_bytes(gzip.compress(packed, compresslevel=9, mtime=0))
            with (
                patch.object(run_four_way, "PRIOR_FAMILY_COUNT", 1),
                patch.object(run_four_way, "PRIOR_FAMILY_BINARY_SHA256", "0" * 64),
            ):
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    run_four_way.load_prior_families(archive)


if __name__ == "__main__":
    unittest.main()
