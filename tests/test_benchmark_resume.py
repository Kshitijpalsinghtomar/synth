import json
import tempfile
import unittest
from pathlib import Path

from benchmarks import score_frozen_four_way as scorer
from benchmarks.score_frozen_four_way import aggregate_rows, load_durable_jsonl


class DurableScoringJournalTests(unittest.TestCase):
    def test_loader_discards_only_a_torn_final_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.jsonl"
            path.write_bytes(b'{"task_id":"a"}\n{"task_id":"b"')
            rows = load_durable_jsonl(path)
            self.assertEqual([row["task_id"] for row in rows], ["a"])
            self.assertEqual(path.read_bytes(), b'{"task_id":"a"}\n')

    def test_loader_rejects_corruption_inside_a_complete_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.jsonl"
            path.write_bytes(b'{"task_id":"a"}\n{not-json}\n')
            with self.assertRaises(json.JSONDecodeError):
                load_durable_jsonl(path)

    def test_aggregates_paired_task_rows_and_excludes_ineligible_cases_from_accuracy(self):
        rows = [
            {
                "task_id": "t1",
                "arms": {
                    "v1_symbolic": {
                        "visible_exact_fit": True, "eligible": True,
                        "full_fresh_behaviour_match": True, "fresh_case_correct": 4,
                        "valid_fresh_cases": 4, "runtime_ms": 10.0,
                        "candidate_count": 0, "queryable": False, "fallback": False,
                    },
                    "v3_guided": {
                        "visible_exact_fit": False, "eligible": True,
                        "full_fresh_behaviour_match": False, "fresh_case_correct": 3,
                        "valid_fresh_cases": 4, "runtime_ms": 12.0,
                        "candidate_count": 0, "queryable": False, "fallback": False,
                    },
                    "v5_ablation": {
                        "visible_exact_fit": True, "eligible": True,
                        "full_fresh_behaviour_match": True, "fresh_case_correct": 4,
                        "valid_fresh_cases": 4, "runtime_ms": 14.0,
                        "candidate_count": 3, "queryable": True, "fallback": False,
                    },
                    "v5_full": {
                        "visible_exact_fit": True, "eligible": False,
                        "full_fresh_behaviour_match": False, "fresh_case_correct": 2,
                        "valid_fresh_cases": 2, "runtime_ms": 16.0,
                        "candidate_count": 2, "queryable": False, "fallback": True,
                    },
                },
            }
        ]
        result = aggregate_rows(rows, task_count=1)
        self.assertEqual(result["v1_symbolic"]["full_fresh_behaviour_matches"], 1)
        self.assertEqual(result["v3_guided"]["fresh_case_accuracy"], 0.75)
        self.assertEqual(result["v5_ablation"]["queryable_sessions"], 1)
        self.assertEqual(result["v5_full"]["fallback_sessions"], 1)
        self.assertEqual(result["v5_full"]["eligible_tasks"], 0)
        self.assertEqual(result["v5_full"]["fresh_case_correct"], 0)
        self.assertEqual(result["v5_full"]["fresh_case_total"], 0)
        self.assertIsNone(result["v5_full"]["fresh_case_accuracy"])

    def test_arm_journal_resumes_only_unfinished_arms(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "arm_results.jsonl"
            metrics = {"fresh_case_correct": 7, "valid_fresh_cases": 9}
            for index, arm in enumerate(scorer.ARMS[:3]):
                scorer.append_arm_result(
                    path, "t1", arm, metrics, attempt_id=f"attempt-{index}"
                )
            loaded = scorer.load_arm_results(path, {"t1"})
            self.assertEqual(loaded[("t1", "v5_ablation")]["metrics"], metrics)
            self.assertEqual(
                loaded[("t1", "v5_ablation")]["attempt_id"], "attempt-2"
            )
            self.assertEqual(
                scorer.pending_arms("t1", loaded),
                ["v5_full"],
            )

    def test_all_arm_checkpoints_reconstruct_task_after_preappend_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "arm_results.jsonl"
            arm_metrics = {
                arm: {"fresh_case_correct": index + 2, "valid_fresh_cases": 5}
                for index, arm in enumerate(scorer.ARMS)
            }
            for index, arm in enumerate(scorer.ARMS):
                scorer.append_arm_result(
                    path, "t1", arm, arm_metrics[arm],
                    attempt_id=f"attempt-{index}",
                )
            loaded = scorer.load_arm_results(path, {"t1"})
            self.assertEqual(scorer.pending_arms("t1", loaded), [])
            reconstructed = {
                "task_id": "t1",
                "arm_journal_version": 1,
                "arm_attempt_ids": {
                    arm: loaded[("t1", arm)]["attempt_id"] for arm in scorer.ARMS
                },
                "arms": {arm: loaded[("t1", arm)]["metrics"] for arm in scorer.ARMS},
            }
            scorer.validate_arm_results_against_task_rows(loaded, [reconstructed])
            self.assertEqual(reconstructed["arms"], arm_metrics)

    def test_versioned_task_row_rejects_missing_arm_journal(self):
        task_row = {
            "task_id": "t1",
            "arm_journal_version": 1,
            "arm_attempt_ids": {arm: "attempt" for arm in scorer.ARMS},
            "arms": {arm: {"done": True} for arm in scorer.ARMS},
        }
        with self.assertRaisesRegex(ValueError, "missing its marked arm journal"):
            scorer.validate_arm_results_against_task_rows({}, [task_row])

    def test_versioned_task_row_rejects_mismatched_attempt_id(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "arm_results.jsonl"
            metrics = {"fresh_case_correct": 1, "valid_fresh_cases": 1}
            loaded_rows = {}
            for index, arm in enumerate(scorer.ARMS):
                scorer.append_arm_result(
                    path, "t1", arm, metrics, attempt_id=f"attempt-{index}"
                )
            loaded_rows = scorer.load_arm_results(path, {"t1"})
            task_row = {
                "task_id": "t1",
                "arm_journal_version": 1,
                "arm_attempt_ids": {
                    arm: "wrong-attempt" if arm == "v5_full"
                    else loaded_rows[("t1", arm)]["attempt_id"]
                    for arm in scorer.ARMS
                },
                "arms": {arm: metrics for arm in scorer.ARMS},
            }
            with self.assertRaisesRegex(ValueError, "attempt identifier disagrees"):
                scorer.validate_arm_results_against_task_rows(loaded_rows, [task_row])

    def test_arm_journal_rejects_skipping_next_unfinished_task(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "arm_results.jsonl"
            for index, arm in enumerate(scorer.ARMS):
                scorer.append_arm_result(
                    path, "t3", arm, {"done": True},
                    attempt_id=f"attempt-{index}",
                )
            loaded = scorer.load_arm_results(path, {"t1", "t2", "t3"})
            with self.assertRaisesRegex(ValueError, "expected t2, got t3"):
                scorer.validate_arm_journal_follows_task_prefix(
                    loaded, ["t1", "t2", "t3"], {"t1"}
                )

    def test_arm_journal_can_resume_partial_next_task_after_legacy_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "arm_results.jsonl"
            for index, arm in enumerate(scorer.ARMS[:2]):
                scorer.append_arm_result(
                    path, "t2", arm, {"done": True},
                    attempt_id=f"attempt-{index}",
                )
            loaded = scorer.load_arm_results(path, {"t1", "t2", "t3"})
            scorer.validate_arm_journal_follows_task_prefix(
                loaded, ["t1", "t2", "t3"], {"t1"}
            )
            self.assertEqual(
                scorer.pending_arms("t2", loaded), ["v5_ablation", "v5_full"]
            )

    def test_arm_journal_rejects_skipped_arm_in_attempt_group(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "arm_results.jsonl"
            scorer.append_arm_result(
                path, "t1", "v1_symbolic", {"done": True}, attempt_id="attempt-1"
            )
            scorer.append_arm_result(
                path, "t1", "v5_ablation", {"done": True}, attempt_id="attempt-2"
            )
            with self.assertRaisesRegex(ValueError, "arm journal order mismatch"):
                scorer.load_arm_results(path, {"t1"})

    def test_arm_journal_rejects_unknown_schema_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "arm_results.jsonl"
            path.write_text(
                json.dumps({
                    "schema_version": 2, "task_id": "t1", "arm": "v1_symbolic",
                    "attempt_id": "attempt-1", "metrics": {},
                }) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unsupported schema version"):
                scorer.load_arm_results(path, {"t1"})

    def test_arm_journal_rejects_reused_attempt_id(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "arm_results.jsonl"
            for arm in scorer.ARMS[:2]:
                scorer.append_arm_result(
                    path, "t1", arm, {"done": True}, attempt_id="same-attempt"
                )
            with self.assertRaisesRegex(ValueError, "duplicate arm attempt_id"):
                scorer.load_arm_results(path, {"t1"})

    def test_arm_journal_rejects_duplicate_task_arm_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "arm_results.jsonl"
            row = {
                "schema_version": 1,
                "task_id": "t1", "arm": "v5_full",
                "attempt_id": "attempt-1", "metrics": {"correct": 1},
            }
            duplicate_key_row = {**row, "attempt_id": "attempt-2"}
            path.write_text(
                json.dumps(row) + "\n" + json.dumps(duplicate_key_row) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate arm result"):
                scorer.load_arm_results(path, {"t1"})


if __name__ == "__main__":
    unittest.main()
