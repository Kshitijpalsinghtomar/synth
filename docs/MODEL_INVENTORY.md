# Model and checkpoint inventory

This document is the source of truth for model identity in the Synth code repository. It is technical release documentation, not the research manuscript. The manuscript and its LaTeX sources are maintained separately and must not be committed here.

## At a glance

There is one checkpoint shipped by this repository, but there are multiple historical research checkpoints in the associated Deepnote workspace. They are not interchangeable.

- **One model architecture:** `ESQSetEncoder`.
- **One checkpoint included in Synth:** `checkpoints/esq_v3_converged.pt`.
- **One additional trained research variant:** the v4 candidate-scoring checkpoint in the Deepnote research workspace.
- **v5 is the one-turn search/oracle protocol, not a new neural architecture or a new checkpoint.**
- **v6 is the strict-depth-4 confirmatory cohort/protocol, not a fifth arm or a new neural architecture; it compares four existing arms while retaining the packaged V5 checkpoint.**
- There is no neural program-output predictor. Program candidates are generated and executed symbolically.

## Checkpoint inventory

| Artifact | SHA-256 | Training/evaluation role | In Synth repository? |
|---|---|---|---|
| Original v3 research checkpoint, `artifacts/esq_v3_model.pt` | `1e5e086f0489c303475d4a0eee0e53a1360e1f888cf7cbb009ed9c9e55bba81c` | Four-epoch v3 prior-guide checkpoint. This is the checkpoint hash recorded in the frozen ExeDec LENGTH_GENERALIZATION candidate-freeze record and v3 result report. | No; retained in the research workspace. |
| v3 release rebuild, `checkpoints/esq_v3_converged.pt` | `a0f03d5066d86022d932699c1a6dfe68957d56131a38e7816e2085bda2000d41` | Rebuilt prior-guide checkpoint. Nine epochs were run and epoch 5 was selected by development loss. | **Yes; the only checkpoint shipped here.** |
| v4 candidate scorer, `artifacts/esq_v4_model.pt` | `b24c86b77e56375a08e2ed37e9a607ebd7a6dd6333e16ec91405603c84d810d2` | Initialized from the original v3 checkpoint. The v4 experiment froze the task encoder and operator/lambda/length prior heads and trained the tree candidate scorer for five epochs. | No; retained in the research workspace. |
| v3/v4 smoke checkpoints | Recorded in their local sidecar manifests | Short pipeline/debug artifacts, not final research checkpoints. | No. |

The v3 release rebuild and original v3 research checkpoint have different SHA-256 values and different recorded training histories. They are different weight snapshots even though they belong to the same v3 prior-guide model family. The release rebuild's current card contains corpus and supervision identity, but the exact training-entrypoint hash and runtime environment were not retained when that historical rebuild was produced. The committed training path now refuses to train against stale/mismatched corpus, NPZ, generator, trainer, feature or model hashes; run it from a freshly generated dataset before claiming full reproduction.

## Architecture: one model class, more than one learned role

The implementation defines one `ESQSetEncoder` PyTorch module. Its state dictionary contains:

1. A shared encoder for the visible task examples.
2. An operator-prior head (15 outputs).
3. A lambda-prior head (19 outputs).
4. A program-length prior head (6 outputs).
5. A tree-structured candidate-scoring branch (the legacy candidate ranker).

The released v3 prior-training objective uses the three prior heads. The current model card records 78,664 parameters used by the trained prior objective out of 137,897 total parameters; the remaining 59,233 parameters belong to the legacy candidate-scoring branch and are not optimized by the v3 prior objective. The v4 research checkpoint starts from the v3 model and trains that candidate-scoring branch while freezing the task encoder and prior heads.

Therefore:
- The operator, lambda and length heads are **not three separate models**; they are output heads in one model.
- The candidate scorer is a separate learned branch within the same model architecture. It becomes a distinct trained model *variant/checkpoint* in v4, not a second architecture.
- The v3 release checkpoint contains the candidate-scoring branch in its state dictionary, but that branch was not trained by the v3 prior objective and is not used by the standard prior prediction path.

## What each search mode uses

| Runtime mode | Learned checkpoint | Oracle |
|---|---|---|
| `symbolic` | None | None |
| `guided` | The packaged v3 release checkpoint | None |
| `interactive` | The same packaged v3 release checkpoint | At most one explicit terminal or subprocess response |

The interactive oracle is an external response protocol, not a neural model. It may be human-supplied or implemented by a local harness. The benchmark adapter uses synthetic reference programs and is not a production oracle.

## Version names: models versus protocols

| Name | Meaning | Is it a separate shipped neural model? |
|---|---|---|
| v1 | Pure symbolic execution-signature baseline | No |
| v2 | Learned beam/pruning experiment; negative result because pruning removed useful branches | No checkpoint in this release |
| v3 | Branch-preserving search with learned operator/lambda/length priors used only to reorder search | The v3 prior-guide family; the release branch includes one rebuilt checkpoint |
| v4 | Candidate-scoring experiment initialized from v3; trains the tree scorer while freezing prior components | Yes, a separate research checkpoint exists, but it is not shipped in Synth |
| v5 | One-turn, frozen candidate-portfolio/oracle protocol | **No.** It reuses the v3 prior guide in its neural-guided arm; it is not a new neural network |

## Critical evidence/provenance gap

The frozen v3 ExeDec confirmation report records checkpoint SHA-256:

`1e5e086f0489c303475d4a0eee0e53a1360e1f888cf7cbb009ed9c9e55bba81c`

The current Synth release contains:

`a0f03d5066d86022d932699c1a6dfe68957d56131a38e7816e2085bda2000d41`

These are not the same file. The report records four training epochs; the current release model card records nine epochs run with epoch 5 selected. Thus, the historical v3 result (118/180 complete fresh-behaviour matches versus 108/180 for the symbolic baseline on the locked LENGTH_GENERALIZATION cohort) is evidence for the **original v3 checkpoint**, not yet evidence for the currently shipped release rebuild.

Do not write that the current Synth checkpoint achieved 118/180 until it has been evaluated under the same frozen evaluation protocol. The release gate is to either:

1. Reproduce the historical run using the exact original v3 checkpoint and source snapshot, preserving its historical identity; or
2. Re-run the v1-versus-v3 confirmation comparison (and relevant v5 arms) using the current release checkpoint, then report the new results and hashes.

For the paper and the public release, option 2 gives the cleanest alignment between the code, checkpoint, and headline results. The historical results should remain labelled as historical and must not be silently reassigned to the rebuilt checkpoint.

## Publication and release rule

Ownership and licensing decision (18 November 2026): the owner confirms independent ownership under TensLab with no client, employer, or university IP restrictions. First-party source code and the packaged `ESQSetEncoder` checkpoint are licensed under Apache-2.0. This does not relicense ExeDec materials or any dependency. Raw synthetic corpora, supervision arrays, generated reference programs, hidden target maps, and private oracle traces remain excluded from the public release. The V6 benchmark result is complete and recorded in the [locked results report](experiments/v6-four-way-200-results.md). The original V3 ExeDec result remains attributable only to the original 1e5e086f checkpoint, not the packaged a0f03d50 checkpoint. The documented historical training-provenance gap for the packaged rebuild remains disclosed; the current public package does not claim that the packaged checkpoint reproduced the 118/180 ExeDec result. First-party source and checkpoint weights are covered by the root Apache-2.0 LICENSE; third-party materials retain their own terms.

The manuscript, PDF, BibTeX database, author drafts, and LaTeX files are maintained outside this repository. Do not add them to the Synth repository.
