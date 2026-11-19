# Synth architecture

Synth (ESQ-DSL) is a bounded synthesizer for the typed integer/list fragment of the DeepCoder DSL. The implementation keeps candidate generation, model guidance, and oracle disambiguation as separate layers.

## End-to-end flow

1. **Task validation.** A task supplies three visible input/output examples. Input variables must retain their type across examples, and output type must be consistent.
2. **Typed symbolic enumeration.** The interpreter and synthesizer enumerate expressions within explicit operator, signature, and time limits. Strict intermediate bounds reject undefined or out-of-domain intermediate values.
3. **Execution-signature quotienting.** For visible dataset D, a program p has a typed execution signature σD(p) = (type(p), p(x1), …, p(xm)). Candidates with the same signature are observationally indistinguishable on D. Synth keeps one deterministic representative for expansion, selected by minimum operator cost and then lexical expression.
4. **Optional neural priority.** The packaged ESQSetEncoder predicts operator and lambda priors from visible examples; these reorder complete typed candidate streams. It also has a program-length head trained with a weighted auxiliary loss and exposed by the prediction API, but the released runtime discards that output and does not use it to schedule search. No controlled ablation establishes whether the auxiliary length objective improves operator/lambda guidance. The 137,897-parameter CPU model does not change which grammar branches are reachable. It is not a pruning gate, does not remove grammar branches, and does not predict hidden outputs.
5. **Optional one-turn oracle.** Interactive mode takes up to three shortest distinct exact-fit candidates, builds a profile-matched query pool, prevalidates a disagreement query against every frozen candidate, records the proposal, and asks a human or local adapter once at most. Only an exact matching frozen candidate may be selected. Failure or abstention restores the pre-query best candidate.

## Modes and version labels

| Public mode | Historical research label | Model dependency | Oracle boundary |
|---|---|---|---|
| symbolic | V1 | None | None |
| guided | V3 | Packaged V3 prior-guide checkpoint | None |
| interactive | V5 | Same packaged V3 prior-guide checkpoint | Zero or one response |

V2 is retained as a negative result: learned beam pruning removed valid search branches and reduced fresh-input behavioural coverage. V4 explored candidate ranking and CEGIS; its candidate-ranker result and the invalidated target-dependent CEGIS headline are preserved in the historical audit. V5 introduced the explicit one-turn oracle protocol. V6 is a confirmatory evaluation protocol/cohort, not a fifth mode, model arm, or neural architecture.

## Checkpoint integrity and loading

The packaged checkpoint is an inference-only CPU model with 137,897 parameters. The loader requires the adjacent model card and SHA-256 sidecar, recomputes the checkpoint digest, and compares all three values before deserialization.

The bundled checkpoint SHA-256 is:

~~~text
a0f03d5066d86022d932699c1a6dfe68957d56131a38e7816e2085bda2000d41
~~~

PyTorch 2.0.0 is the declared neural minimum. Because the weights-only unpickler in PyTorch versions before 2.10.0 is affected by CVE-2026-24747, those runtimes may load only the exact hash-pinned bundled checkpoint. Alternate or external checkpoints require PyTorch 2.10.0 or later.

## Search and oracle limits

- Search is bounded by max operator depth, maximum unique signatures, and a timeout. A run stopped by a cap is reported as truncated; it is not proof that the space was exhausted.
- Exact execution-signature equality is defined only over the visible examples. It is not semantic equivalence over all possible inputs.
- The neural prior is advisory and does not change the reachable grammar under a non-truncated run.
- Interactive mode has one frozen candidate portfolio and at most one oracle request. There is no retry, iterative CEGIS, or post-answer resynthesis.
- An oracle answer is accepted only when it matches a cached prediction from a frozen candidate. Otherwise the pre-query fallback is preserved.

## Evidence boundary

The V6 four-way report records 200 fresh structural families, zero accepted-family overlap with the pinned prior-family archive, strict active-operator depth 1–4, search budget 4, and strict intermediate bounds. It scores four existing arms: V1 symbolic, V3 guided, V5 ablation, and V5 full. The run uses a local file-backed synthetic reference oracle. It is not an official ExeDec benchmark or a human-oracle study.

The historical ExeDec LENGTH_GENERALIZATION result (118/180 versus 108/180 full fresh-behaviour matches) belongs to the original V3 checkpoint SHA-256 beginning 1e5e086f. The checkpoint shipped here is a distinct release rebuild, SHA-256 a0f03d5066d86022d932699c1a6dfe68957d56131a38e7816e2085bda2000d41. Do not conflate those results.

## Related documentation

- [Model and checkpoint inventory](MODEL_INVENTORY.md)
- [V6 strict-depth-4 protocol](experiments/v6-strict-depth4-preflight-protocol.md)
- [V6 results and provenance](experiments/v6-four-way-200-results.md)
- [Training and reproduction instructions](../training/README.md)
