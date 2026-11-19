# ESQ-DSL experiment history

This directory preserves the research progression that led to the Synth release. The chronology distinguishes software modes, experimental protocols, and checkpoint identities. Historical findings—including negative and invalidated claims—remain intact.

## Chronology

1. **V1 — symbolic baseline:** [V1 report](v1-baseline.md). Bounded typed enumeration with exact execution-signature quotienting; no learned model or external oracle.
2. **V2 — pruning negative result:** [V2 report](v2-negative-result.md). Learned beam pruning was a NO-GO because it removed valid branches and reduced fresh-input behavioural coverage.
3. **V3 — priority guide:** [V3 report](v3-positive-result.md). Learned operation/lambda priors reorder the complete search without pruning. The historical ExeDec LENGTH_GENERALIZATION result was 118/180 versus 108/180, using the original V3 checkpoint SHA-256 beginning 1e5e086f.
4. **V4 — ranker and CEGIS audit:** [V4 audit](v4-cegis-audit.md). Candidate-only results are preserved. The earlier target-dependent 344/371 CEGIS headline was invalidated and is not confirmatory evidence.
5. **V5 — external one-turn oracle:** [one-shot results](v5-one-shot-results.md), [protocol](v5-original-protocol.md), [implementation report](v5-original-report.md), and [four-way recovery audit](v5-four-way-200-recovery-audit.md). A frozen portfolio, a single validated query at most, and deterministic fallback; no iterative CEGIS.
6. **V6 — strict depth-4 confirmation:** [V6 results](v6-four-way-200-results.md) and [locked protocol](v6-strict-depth4-preflight-protocol.md). A fresh 200-task structural-family-held-out synthetic cohort, zero accepted-family overlap, strict intermediate bounds, and four pre-existing comparison arms.

## Current claim boundary

V6 is the current confirmatory synthetic evaluation. It is not an official ExeDec benchmark, a human-oracle study, or evidence of arbitrary hidden-output inference. The packaged V5 checkpoint is the V3 prior-guide release rebuild; V6 adds no model architecture or fifth arm.

The original ExeDec V3 confirmation result belongs to the separate original checkpoint (SHA-256 beginning 1e5e086f), not the packaged checkpoint (SHA-256 a0f03d50…). Do not merge these checkpoint identities when citing results.
