"""Rebuild the pinned 100k synthetic training corpus and feature arrays."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import numpy as np
from .esq_training_v3 import generate_corpus_v3
ROOT=Path(__file__).resolve().parents[1]
ARTIFACTS=ROOT/"artifacts"
def sha256_file(path: Path) -> str:
 d=hashlib.sha256()
 with path.open("rb") as stream:
  for chunk in iter(lambda:stream.read(1024*1024),b""): d.update(chunk)
 return d.hexdigest()
def main() -> None:
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument("--count",type=int,default=100_000)
 p.add_argument("--base-seed",type=int,default=1_116_000)
 a=p.parse_args(); ARTIFACTS.mkdir(parents=True,exist_ok=True)
 tasks=ARTIFACTS/"esq_v3_synthetic_tasks_100k.jsonl.gz"
 arrays,manifest=generate_corpus_v3(a.count,base_seed=a.base_seed,jsonl_gz_path=tasks)
 supervision=ARTIFACTS/"esq_v3_supervision_100k.npz"
 np.savez_compressed(supervision,**arrays)
 manifest.update({
  "supervision_npz_path":str(supervision.relative_to(ROOT)),
  "supervision_npz_sha256":sha256_file(supervision),
  "supervision_npz_bytes":supervision.stat().st_size,
  "generator_source_sha256":sha256_file(Path(__file__).with_name("esq_data_v3.py")),
  "training_source_sha256":sha256_file(Path(__file__).with_name("esq_training_v3.py")),
  "feature_source_sha256":sha256_file(ROOT/"esq_dsl"/"features.py"),
  "model_source_sha256":sha256_file(ROOT/"esq_dsl"/"model.py"),
 })
 (ARTIFACTS/"esq_v3_synthetic_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
 print(json.dumps({
  "task_corpus_sha256":manifest["raw_jsonl_gzip_sha256"],
  "supervision_sha256":manifest["supervision_npz_sha256"],
  "rows":manifest["task_count"],"split_task_counts":manifest["split_task_counts"],
  "split_family_counts":manifest["split_family_counts"],"family_disjoint":manifest["split_family_disjoint"]
 },indent=2))
if __name__=="__main__": main()
