from __future__ import annotations
import unittest
from training.esq_data_v3 import generate_synthetic_task_v3, structural_family_hash
class TrainingDataReproducibilityTests(unittest.TestCase):
 def test_seed_recreates_task_and_family_hash(self):
  first=generate_synthetic_task_v3(1_116_000,0)
  second=generate_synthetic_task_v3(1_116_000,0)
  self.assertEqual(first,second)
  self.assertEqual(len(first["outputs"]),3)
  self.assertEqual(first["program_family_hash"],structural_family_hash(first["program"],first["input_types"]))
  self.assertEqual(len(first["program_family_hash"]),64)
if __name__=="__main__": unittest.main()
