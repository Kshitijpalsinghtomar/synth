# Frozen benchmark family archive

The benchmark runner needs a lossless set of all 54,649 structural-family SHA-256 digests from the pinned 100,000-row ESQ-DSL v3 synthetic corpus.

The generated file `prior_family_hashes.bin.gz` is **not committed** to this repository. This keeps generated training data and derived artifacts out of the source tree. Recreate it from a clean checkout:

```bash
python -m training.generate_dataset
python benchmarks/prepare_family_exclusions.py \
  artifacts/esq_v3_synthetic_tasks_100k.jsonl.gz \
  --output benchmarks/data/prior_family_hashes.bin.gz
```

Expected prior corpus SHA-256:

`2faa003d65827bebdcc4cb7f7c2fac9958b905e5db8143c708466d58bd26c958`

Expected archive SHA-256:

`2564ab662e37a717d91019b4abc1b757f75df354899c8a0e40fcce0649049bee`

The archive is a deterministic gzip stream of 54,649 full 32-byte digests sorted lexicographically before packing. The runner verifies its checksum, byte length and unique-hash count before generating a fresh cohort. A plain-text gzip form is also accepted by the runner for existing frozen experiments.

The generated corpus, supervision arrays and family archive are local reproduction artifacts. Do not commit generated reference-program JSONL, hidden benchmark target maps, or raw oracle traces.
