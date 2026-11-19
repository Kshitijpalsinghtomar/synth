---
license: apache-2.0
library_name: pytorch
pipeline_tag: other
tags:
  - program-synthesis
  - neuro-symbolic
  - deepcoder
  - cpu
---

# Synth Compass (ESQSetEncoder)

**A 137,897-parameter CPU neural search compass for deterministic program synthesis.**

Synth combines execution-signature quotienting with branch-preserving symbolic search. The ESQSetEncoder checkpoint predicts operator, lambda, and program-length priors to reorder search visitation. It does **not** predict program outputs and does **not** prune valid symbolic branches.

- **Author:** Kshitij Pal
- **Organization:** TENS LAB — https://tenslab.dev
- **Source:** https://github.com/Kshitijpalsinghtomar/synth
- **License:** Apache-2.0 (first-party source code and model weights)
- **Checkpoint:** `esq_v3_converged.pt`
- **Parameters:** 137,897 total (78,664 used by trained prior heads; 59,233 in a legacy candidate-ranker branch not optimized by this objective)
- **Inference:** CPU; no GPU is required

## Repository files

| File | Purpose |
|---|---|
| `esq_v3_converged.pt` | Packaged PyTorch checkpoint |
| `model_card.json` | Architecture, training, provenance and limitations metadata |
| `esq_v3_converged.pt.sha256` | Expected SHA-256 digest for the checkpoint |
| `LICENSE` | Apache License 2.0 |

## Checkpoint integrity

Expected SHA-256:

```text
a0f03d5066d86022d932699c1a6dfe68957d56131a38e7816e2085bda2000d41
```

Verify after downloading:

```bash
sha256sum -c esq_v3_converged.pt.sha256
```

The expected digest identifies the exact packaged bytes. It is an integrity check, not a malware scan.

## Download and use with Synth

The Hub stores the checkpoint, model card, and SHA-256 sidecar at the repository root. Download all three together into Synth's `checkpoints/` directory so the package's loader can verify them as one artifact:

```bash
hf download Kshitijpalsinghtomar/synth-compass esq_v3_converged.pt model_card.json esq_v3_converged.pt.sha256 --local-dir checkpoints
```

From a clean Synth checkout, install the neural extras and run the guided search mode:

```bash
pip install -e ".[neural]"
synth sample_task.json --mode guided --checkpoint checkpoints/esq_v3_converged.pt
```

Use the Synth `NeuralGuide` loader rather than calling `torch.load` on arbitrary files yourself. It verifies the checkpoint SHA-256 against both the model card and sidecar, then uses restricted `weights_only=True` deserialization.

**PyTorch security:** CVE-2026-24747 affects the `weights_only` unpickler in PyTorch versions earlier than 2.10.0. Synth's loader permits only the exact hash-pinned bundled checkpoint on those older runtimes; custom or third-party checkpoints require PyTorch 2.10.0 or newer. Never disable `weights_only` to make an untrusted checkpoint load. SHA-256 confirms byte identity with the expected digest; it is not a malware scan. Hugging Face also runs file and pickle-import scans, but those checks are best-effort and are not a safety guarantee. See the [Hugging Face pickle-scanning guidance](https://huggingface.co/docs/hub/en/security-pickle) and [PyTorch security advisory](https://github.com/pytorch/pytorch/security/advisories/GHSA-63cw-57p8-fm3p).

## Architecture

ESQSetEncoder consumes a fixed-shape task representation with input feature shape `[3, 4, 37]`, an 8-dimensional variable-position embedding, value/example encoders, and a task projection. Three trained heads predict:

- **Operator priors:** 15 DeepCoder operators.
- **Lambda priors:** 19 supported lambda expressions.
- **Program-length prior:** lengths 1–6.

The training objective was binary cross-entropy for operator and lambda heads plus weighted cross-entropy for length. Inference uses PyTorch and runs on CPU.

The learned scores affect only enumeration order. Search remains symbolic, bounded, and branch-preserving. The model is not a program-output oracle.

## Locked V6 benchmark: strict depth-4 zero-overlap cohort

The V6 structural stress test used 196 eligible tasks and 8,869 fresh cases. No AST structural family in the evaluation cohort overlapped with training.

| Configuration | Complete task matches | Full-task accuracy | Fresh-case accuracy |
|---|---:|---:|---:|
| V1 symbolic | 60/196 | 30.61% | 70.03% |
| V3 guided | 62/196 | 31.63% | 70.77% |
| V5 ablation | 70/196 | 35.71% | 74.36% |
| V5 full | 71/196 | 36.22% | 74.34% |

The V5 full arm is 5.61 percentage points above V1 symbolic on complete task matches. This is an observed comparison across configurations, not an isolated causal estimate of the oracle component. The full and ablation arms differ by 0.51 percentage points in complete-task accuracy.

This is a structural-family-held-out synthetic evaluation under strict depth-4 semantics with a local file-backed synthetic oracle. It is not an official ExeDec benchmark or a human-oracle evaluation.

## Standard external DeepCoder splits

These evaluations are separate from the V6 structural stress test:

| Split | System | Complete fresh-behaviour matches | Fresh-case accuracy |
|---|---|---:|---:|
| `SWITCH_CONCEPT_ORDER` (ESQ-03) | Synth | 144/180 (80.0%) | 88.9% (7,947/8,937) |
| `LENGTH_GENERALIZATION` (V3) | Synth | 118/180 (65.6%) | 78.7% |
| `LENGTH_GENERALIZATION` | Pure symbolic | 108/180 (60.0%) | 75.2% |

The `LENGTH_GENERALIZATION` confirmation used the original V3 checkpoint `1e5e086f`, distinct from the packaged checkpoint `a0f03d50`. Do not attribute that result to the packaged checkpoint.

## Training and provenance notes

The canonical `model_card.json` records the architecture, training split, optimizer, epoch history, held-out prediction metrics, source-data digests, and limitations. The historical release rebuild has **partial provenance**: corpus and supervision hashes are known, but the exact training-entrypoint hash and runtime environment were not retained. Exact training reproduction is therefore not claimed.

## Usage

This checkpoint is intended to be loaded by the Synth package and used by its guided search mode. See the source repository for installation, command-line examples, runtime compatibility restrictions, and the complete synthesis pipeline:

https://github.com/Kshitijpalsinghtomar/synth

## Citation

```bibtex
@software{synth_esq_dsl_2026,
  author       = {Kshitij Pal},
  title        = {Synth: Execution-Signature Quotienting for Deterministic Program Synthesis},
  year         = {2026},
  organization = {TENS LAB},
  url          = {https://tenslab.dev},
  version      = {1.0.0},
  license      = {Apache-2.0}
}
```
