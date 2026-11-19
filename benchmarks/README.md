# Benchmark protocol

The release script performs a fresh, family-held-out four-arm comparison.

| Arm | Search policy | Oracle |
|---|---|---|
| v1 symbolic | Original pure symbolic bounded search; one output program | None |
| v3 guided | Neural operation/lambda priors reorder full enumeration; one output candidate | None |
| v5 ablation | Symbolic full enumeration with a three-candidate exact-fit portfolio | One-turn file-backed local oracle |
| v5 full | Neural-guided full enumeration with the same three-candidate portfolio | One-turn file-backed local oracle |

All four candidate portfolios are frozen using visible task data before the benchmark writes any target maps. A reserved fresh-input set is excluded from query selection and used only for behavioural scoring. The benchmark uses an in-process file-backed oracle adapter to avoid repeated interpreter startup; each adapter can read only its task-specific target map. The standalone interactive CLI also accepts an isolated subprocess adapter command.

The runner requires the pinned prior 100k structural-family corpus or the committed packed archive of its unique 256-bit family hashes, plus the frozen release checkpoint. It verifies exact hashes, dimensions and the compact archive SHA-256. The benchmark is local synthetic evidence, not an official ExeDec benchmark.

Regenerate the packed archive from the pinned corpus:

    python benchmarks/prepare_family_exclusions.py path/to/esq_v3_synthetic_tasks_100k.jsonl.gz

Run from the repository root:

    python benchmarks/run_four_way.py \
      --prior-family-hashes benchmarks/data/prior_family_hashes.bin.gz \
      --checkpoint checkpoints/esq_v3_converged.pt \
      --output-dir benchmarks/results/four_way_200

The script refuses to overwrite a non-empty result folder. Output includes a cohort lock, visible candidate freeze, query/reserved input freeze, 200 task-specific target maps, one-turn provenance, per-task metrics, aggregate summary and artifact checksums. Generated target maps and raw oracle provenance are local audit files and are not published in the repository.

## Resuming fresh scoring after preemption

The original runner freezes all visible candidates, query pools, reserved fresh inputs, and task-specific target maps before scoring. For long or preemptible environments, use the durable scorer against that frozen directory. It verifies the cohort-lock hashes, every target-map digest, and deterministic reconstruction of the 200 task programs before scoring. It writes and fsyncs one complete task result at a time; rerunning the command skips completed task IDs and continues where it stopped.

Run from the repository root, using a separate output directory:

    python benchmarks/score_frozen_four_way.py \
      --source-dir benchmarks/results/four_way_200 \
      --output-dir benchmarks/results/four_way_200_recovery \
      --prior-family-hashes benchmarks/data/prior_family_hashes.bin.gz \
      --max-new-tasks 40

Repeat the command until the progress file reports all tasks complete. The final summary and artifact manifest are written only when all 200 task rows are present. The scoring output directory must be separate from the frozen source directory. Do not commit target maps or raw oracle provenance.
