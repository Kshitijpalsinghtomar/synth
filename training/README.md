# Training and data provenance

The released neural artifact is the **ESQSetEncoder v3 prior guide** used by the ESQ-DSL v5 search protocol. It predicts operation/lambda/length priors; it is not a program-output model.

## Rebuild the dataset

From the repository root:

```bash
python -m pip install -e ".[training]"
python -m training.generate_dataset
```

The generator writes two local files under `artifacts/`:

- `esq_v3_synthetic_tasks_100k.jsonl.gz`: 100,000 generated tasks and reference DSL programs.
- `esq_v3_supervision_100k.npz`: feature tensors, labels, split codes and structural-family digests.

The corpus is synthetic. The implementation follows documented DeepCoder input/DSL constraints and pins the ExeDec source reference at commit `ef046ce2cc3fcd024e32f5dfe00e69700dac82ed`; it is not the official ExeDec dataset. The generator records corpus, supervision-array, generator, feature and model source hashes in `artifacts/esq_v3_synthetic_manifest.json`.

The 80/10/10 split is assigned by the first 32 bits of normalized structural-family SHA-256 modulo 100. The generator rejects cross-split family overlap. The released run has 79,535 training tasks, 10,546 development tasks, 9,919 confirmation tasks, and 54,649 unique structural families.

## Reproduce the released training procedure

```bash
python -m training.train_converged
```

The script first verifies the corpus and NPZ SHA-256 values against the synthetic manifest, verifies the generator/trainer/features/model source hashes, and independently checks structural-family disjointness in the NPZ. A missing or stale generated dataset must be rebuilt rather than silently accepted.

It uses CPU PyTorch, seed `20261116`, AdamW, batch size 256, learning rate 0.001, maximum 20 epochs, patience 4, minimum validation-loss improvement 0.0001, and gradient clipping at 1.0. Training uses only the training split; the development split selects the checkpoint. Confirmation is evaluated only after the checkpoint is atomically written. The model card, sidecar and checkpoint are written atomically; the card records corpus, supervision, source, entrypoint and runtime hashes.

Outputs:

- `checkpoints/esq_v3_converged.pt`
- `checkpoints/model_card.json`
- `checkpoints/esq_v3_converged.pt.sha256`

A rebuilt checkpoint may have a different byte-level SHA across library or runtime versions even when tensor weights are equivalent. The model card records runtime versions and each artifact hash. The inference loader requires the model card and matching `.sha256` sidecar before restricted deserialization. Never overwrite a published tag's checkpoint; publish a new version with a new hash.

## Artifact integrity and loading

The shipped checkpoint is checked against the SHA-256 in the adjacent model card by `NeuralGuide`. The declared neural/training dependency floor is PyTorch 2.0.0. Security note: PyTorch before 2.10.0 is affected by CVE-2026-24747 in the `weights_only=True` unpickler. On those older runtimes `NeuralGuide` accepts only the exact repository-bundled checkpoint digest embedded in the loader; custom or third-party weights are rejected until PyTorch 2.10.0 or later is used. SHA-256 verifies byte identity against the pinned release digest; it is not a general malware scanner. Never load arbitrary checkpoint files with a vulnerable PyTorch runtime.

## Dataset publication policy

The generated corpus and feature arrays are intentionally not committed to Git: they contain 100k tasks and can be regenerated from source and a fixed seed. Do not publish generated reference-program JSONL or benchmark target maps as test material. Publish generator source, provenance manifests and hashes; publish only permitted aggregate evaluation data.
