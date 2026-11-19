from __future__ import annotations
import unittest
from pathlib import Path
from esq_dsl.cli import run_task


class CLIModeTests(unittest.TestCase):
    def setUp(self):
        self.task = {
            "inputs": {"x0": [[1, 2, 3], [2, 3, 4], [3, 4, 5]]},
            "outputs": [[3, 2, 1], [4, 3, 2], [5, 4, 3]],
            "input_specs": {"x0": {"range": [0, 10], "length": [1, 5]}},
        }

    def test_symbolic_mode_needs_no_checkpoint_oracle(self):
        r = run_task(self.task, mode="symbolic", max_ops=2, timeout_s=2.0)
        self.assertEqual(r["mode"], "symbolic")
        self.assertTrue(r["exact_fit"])
        self.assertIn("program", r)

    def test_guided_mode_loads_checkpoint_without_oracle(self):
        cp = Path(__file__).resolve().parents[1] / "checkpoints" / "esq_v3_converged.pt"
        r = run_task(
            self.task, mode="guided", checkpoint=str(cp), max_ops=3, timeout_s=2.0
        )
        self.assertEqual(r["mode"], "guided")
        self.assertEqual(len(r["checkpoint_sha256"]), 64)
        self.assertNotIn("oracle", r)


if __name__ == "__main__":
    unittest.main()
