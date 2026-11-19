# Synth documentation

**Synth (ESQ-DSL) 1.0.0** is developed under [TENS LAB](https://tenslab.dev). This index distinguishes the current release definition from historical experiments and the locked V6 confirmation.

## Start here

- [Architecture](ARCHITECTURE.md) — typed synthesis pipeline, execution-signature quotienting, model guidance, oracle boundary, and claim limits.
- [Model and checkpoint inventory](MODEL_INVENTORY.md) — original research checkpoint versus the packaged release rebuild.
- [Packaged model card](../checkpoints/model_card.json) — model details, checkpoint digest, training provenance, licence scope, and limitations.
- [Training and reproducibility](../training/README.md) — rebuild the synthetic corpus and reproduce the training procedure; generated corpora remain local artifacts.
- [Benchmark implementation and reproducibility](../benchmarks/README.md) — cohort generation, frozen inputs, scoring, source manifests, and artifact handling.
- [Commercial, ownership, and licence audit](COMMERCIAL_AND_LICENSE_AUDIT.md) — first-party Apache-2.0 decision, third-party boundaries, and limits on product claims.
- [Third-party notices](../THIRD_PARTY_NOTICES.md), [security policy](../SECURITY.md), [release citation](../CITATION.cff), and [root README](../README.md).

## Benchmark evidence map

The two benchmark regimes are separate and must not be merged into one leaderboard.

1. **External DeepCoder task splits:** [ESQ-03 SWITCH_CONCEPT_ORDER baseline](experiments/v1-baseline.md) records 144/180 complete fresh-behaviour matches and 7,947/8,937 fresh cases. [V3 LENGTH_GENERALIZATION confirmation](experiments/v3-positive-result.md) records 118/180 versus 108/180 for the original V3 checkpoint; that checkpoint differs from the packaged release rebuild.
2. **V6 strict depth-4 structural-family-held-out cohort:** [V6 results and provenance](experiments/v6-four-way-200-results.md) and the [locked V6 protocol](experiments/v6-strict-depth4-preflight-protocol.md) record the completed 200-task, four-arm synthetic evaluation. It uses a local file-backed reference oracle and is not an official ExeDec or human-oracle benchmark.

## Experiment chronology

V1–V5 reports are retained as **historical records**. Their first-line status banners identify them as superseded by the V6 release audit; keep their contemporary results and caveats intact.

1. **V1 — symbolic baseline:** [ESQ-03 baseline and external split record](experiments/v1-baseline.md). Exact execution-signature quotienting in bounded typed enumeration.
2. **V2 — pruning negative result:** [V2 negative evaluation](experiments/v2-negative-result.md). Learned beam pruning removed valid branches and reduced fresh-input behaviour.
3. **V3 — branch-preserving neural priority:** [V3 positive result](experiments/v3-positive-result.md). Learned operator/lambda priors reorder full enumeration; the original checkpoint’s LENGTH_GENERALIZATION confirmation is preserved here.
4. **V4 — candidate ranking and CEGIS audit:** [V4 audit](experiments/v4-cegis-audit.md). Candidate-only results remain historical; the target-dependent 344/371 CEGIS headline is invalidated and is not confirmatory evidence.
5. **V5 — one-turn oracle:** [one-shot results](experiments/v5-one-shot-results.md), [original protocol](experiments/v5-original-protocol.md), [implementation report](experiments/v5-original-report.md), and [four-way recovery/validity audit](experiments/v5-four-way-200-recovery-audit.md). These documents preserve the earlier protocol and its limitations.
6. **V6 — strict depth-4 confirmation:** [four-way results and provenance](experiments/v6-four-way-200-results.md) and [preflight protocol](experiments/v6-strict-depth4-preflight-protocol.md). Four existing arms, 200 accepted structural families, zero overlap with the pinned prior-family index, and 800/800 arm results.

## Reading and citation guidance

- Use V6 for the current release-level synthetic evaluation; do not call it an official ExeDec result or a human-oracle study.
- Use each V1–V5 report only for the method, audit finding, or historical result it records. The V4 target-dependent CEGIS headline is explicitly invalidated.
- The original V3 checkpoint (SHA-256 beginning 1e5e086f) and packaged V3 release rebuild (SHA-256 beginning a0f03d50) are different weight snapshots. The 118/180 result does not belong to the packaged checkpoint.
- Cite Synth 1.0.0 using [CITATION.cff](../CITATION.cff) or the BibTeX entry in the [root README](../README.md).
