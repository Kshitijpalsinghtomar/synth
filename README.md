# Synth (ESQ-DSL)

**Deterministic program synthesis via execution-signature quotienting.**

*TENS LAB · [tenslab.dev](https://tenslab.dev) · Release 1.0.0 · Apache-2.0 · Python 3.10+*

Synth searches for bounded typed programs that explain input/output examples. It combines three deliberately separate mechanisms:

- **Execution-signature quotienting** groups programs that behave identically on visible examples and expands one deterministic representative, avoiding repeated exploration of observationally identical states.
- **A 138k-parameter CPU neural search compass** (137,897 parameters) predicts operator, lambda, and program-length priors. Its scores reorder search visitation; they do not prune operators, lambdas, or branches.
- **One-turn oracle disambiguation** freezes up to three shortest distinct exact-fit candidates, validates one disagreement query, and accepts at most one answer. A skipped, invalid, timed-out, or non-matching response falls back to the pre-query best candidate.

The synthesizer remains symbolic and bounded. The neural model is a search guide, not a program-output predictor. Interactive mode is a single oracle turn, not an iterative CEGIS loop.

## Install and quickstart

Python 3.10 or later is required.

Install the package and CLI:

```bash
pip install -e .
```

The symbolic mode has no mandatory third-party runtime dependency. For neural-guided and interactive modes, install the optional neural dependencies (NumPy and PyTorch 2.0.0 or later):

```bash
pip install -e ".[neural]"
```

For the test suite:

```bash
pip install -e ".[test]"
```

**Checkpoint integrity and PyTorch versions.** The loader automatically verifies the bundled checkpoint against both its adjacent SHA-256 sidecar and the checkpoint record in the model card. With PyTorch versions earlier than 2.10.0, it permits only the exact bundled checkpoint digest:

```text
a0f03d5066d86022d932699c1a6dfe68957d56131a38e7816e2085bda2000d41
```

This restriction protects the older weights-only deserializer path. Custom or third-party checkpoints require PyTorch 2.10.0 or later. The hash check proves byte identity with the published bundled checkpoint; it is not a general malware scan.

The Hugging Face model-card README is maintained in [`huggingface/README.md`](huggingface/README.md). The canonical model card keeps `checkpoint.path` for this repository and records the separate Hub-root location in `checkpoint.hub_path`.

Create a task file named sample_task.json:

```json
{
  "task_id": "reverse-list-example",
  "inputs": {
    "x0": [[1, 2, 3], [2, 3, 4], [3, 4, 5]]
  },
  "outputs": [[3, 2, 1], [4, 3, 2], [5, 4, 3]],
  "input_specs": {
    "x0": {
      "range": [0, 10],
      "length": [1, 5]
    }
  }
}
```

Each task supplies visible input/output examples. Every input variable must retain one type across examples, and the output type must be consistent. Input specifications are optional for symbolic and guided search; interactive query generation uses their value and list-length bounds.

### CLI: three modes

**Symbolic** — bounded search without PyTorch or an oracle:

```bash
synth sample_task.json --mode symbolic
```

**Guided** — the same branch-preserving symbolic search, with learned priors used only to order visitation:

```bash
synth sample_task.json --mode guided --checkpoint checkpoints/esq_v3_converged.pt
```

**Interactive** — a frozen candidate portfolio and at most one oracle request:

```bash
synth sample_task.json --mode interactive --checkpoint checkpoints/esq_v3_converged.pt
```

Interactive mode uses a human terminal adapter by default. An optional local subprocess adapter can be supplied with --oracle-command; it receives one JSON request on standard input and returns one JSON response on standard output. It is launched without a shell. Only connect an oracle that is authorized to answer the task.

### Python API

The same three modes are available through run_task:

```python
from esq_dsl.cli import run_task

task = {
    "task_id": "reverse-list-example",
    "inputs": {"x0": [[1, 2, 3], [2, 3, 4], [3, 4, 5]]},
    "outputs": [[3, 2, 1], [4, 3, 2], [5, 4, 3]],
    "input_specs": {"x0": {"range": [0, 10], "length": [1, 5]}},
}

symbolic = run_task(task, mode="symbolic")
guided = run_task(task, mode="guided", checkpoint="checkpoints/esq_v3_converged.pt")
interactive = run_task(
    task, mode="interactive", checkpoint="checkpoints/esq_v3_converged.pt"
)

print(symbolic["program"])
print(guided["program"])
print(interactive["selected_program"])
```

The interactive call can ask at most one query. It selects only from the frozen candidates and otherwise falls back deterministically; it does not retry or resynthesize after the response.

## Benchmark results

The repository records **two different benchmark regimes**. Their denominators, task splits, checkpoint identities, and evidence boundaries differ; do not combine them into one leaderboard.

### 1. Standard external DeepCoder splits — concept and length generalization

These evaluations use public DeepCoder task splits from the ExeDec repository, with the project’s own bounded synthesizer and fresh-input evaluation. They are not reproductions of ExeDec’s trained Transformer baselines or complete official evaluator.

| Split | Method | Complete fresh-behaviour matches | Fresh-case accuracy |
|---|---|---:|---:|
| SWITCH_CONCEPT_ORDER (ESQ-03) | ESQ-03 symbolic baseline | **144/180 (80.0%)** | **7,947/8,937 (88.92%)** |
| LENGTH_GENERALIZATION (V3) | V3 original prior-guide checkpoint | **118/180 (65.56%)** | **78.69%** |
| LENGTH_GENERALIZATION (V1) | Pure symbolic baseline on the same confirmation split | **108/180 (60.00%)** | **75.23%** |

The ESQ-03 result is the original concept-order baseline: 144 of 180 eligible tasks matched the reference on every valid fresh input, with 7,947 of 8,937 valid fresh cases correct. The LENGTH_GENERALIZATION result is a separate, untouched confirmation split. V3 gained ten complete-task matches over V1 and 3.46 percentage points of fresh-case accuracy on that split.

**Checkpoint distinction matters.** The LENGTH_GENERALIZATION V3 confirmation used original research checkpoint SHA-256:

```text
1e5e086f0489c303475d4a0eee0e53a1360e1f888cf7cbb009ed9c9e55bba81c
```

That is not the checkpoint packaged in this release. Synth ships a separately rebuilt V3 prior-guide checkpoint:

```text
a0f03d5066d86022d932699c1a6dfe68957d56131a38e7816e2085bda2000d41
```

Do not attribute the historical 118/180 result to the packaged release checkpoint. The task splits and results are preserved in the [ESQ-03 baseline report](docs/experiments/v1-baseline.md), [V3 confirmation report](docs/experiments/v3-positive-result.md), and [model inventory](docs/MODEL_INVENTORY.md).

### 2. V6 strict depth-4 zero-overlap cohort — out-of-family structural stress test

V6 is the current confirmatory **synthetic** cohort, not a new model or a fifth search mode. It evaluates 200 accepted structural families with target depth 1–4, a four-operation search budget, and strict intermediate semantics.

The accepted cohort has **zero structural-family overlap** with the pinned 54,649-family exclusion index derived from the 100,000-row synthetic corpus. That corpus includes the original V3 train, development, and confirmation families. V6 therefore tests new AST-family structures relative to that training-family archive; it does not mean the cohort was sampled from the official ExeDec distribution.

| Arm | Complete fresh-behaviour matches | Full-match rate (n=196 eligible) | Fresh-case accuracy (n=8,869) |
|---|---:|---:|---:|
| V1 symbolic | 60/196 | 30.61% | 70.03% |
| V3 guided | 62/196 | 31.63% | 70.77% |
| V5 ablation | 70/196 | 35.71% | 74.36% |
| V5 full | 71/196 | 36.22% | 74.34% |

The cohort contains 200 tasks and 800/800 arm results. Four tasks are outside the predeclared eligibility denominator; fresh-case accuracy is pooled over the 8,869 valid fresh cases. All four arms use the same frozen task and reserved-input cohort.

**How to read the gain.** V3 guided is 1.02 percentage points above symbolic on complete matches. The two V5 arms both use a top-three frozen candidate portfolio and the one-turn local reference oracle: the prior-free V5 ablation reaches 35.71% (+5.10 points over V1), and V5 full reaches 36.22% (+5.61 points over V1). V5 full is 0.51 points above the ablation. Thus the larger observed improvement appears with the one-turn portfolio/oracle stage, while learned priors add a smaller increment in this cohort. The ablation is not an oracle-free control, so these results do not isolate the oracle’s causal effect. The comparisons are descriptive for one fixed cohort; no repeated-seed or inferential analysis was performed.

V6 uses a **local file-backed synthetic reference oracle**, not a human-oracle study or a live external benchmark oracle. It is not an official ExeDec result and does not establish general synthesis performance. See the [locked V6 results and provenance](docs/experiments/v6-four-way-200-results.md), [V6 protocol](docs/experiments/v6-strict-depth4-preflight-protocol.md), and [read-only V5 audit](docs/experiments/v5-four-way-200-recovery-audit.md).

## Positioning within programming-by-example synthesis

The following is a conceptual map of related approaches, not a head-to-head performance table. The categories overlap: for example, DeepCoder combines learned predictions with enumerative search.

| PBE family | Representative systems | Typical approach | Synth’s distinction |
|---|---|---|---|
| DSL-directed and enumerative synthesis | [DeepCoder](https://arxiv.org/abs/1611.01989), [Microsoft PROSE](https://www.microsoft.com/en-us/research/project/prose-framework/) | Search or synthesize programs in a domain-specific language from examples; DeepCoder uses learned program-property predictions to augment enumeration, while PROSE produces ranked DSL programs consistent with examples. | Synth adds exact execution-signature quotienting and keeps learned priors out of branch-pruning decisions. |
| Learned, step-scored search | [ExeDec](https://proceedings.iclr.cc/paper_files/paper/2024/hash/c43b2989b1ba055aa713a4abbe4a8b05-Abstract-Conference.html), [BUSTLE](https://research.google/pubs/bustle-bottom-up-program-synthesis-through-learning-guided-exploration/), [CrossBeam](https://research.google/pubs/crossbeam-learning-to-search-in-bottom-up-program-synthesis/) | Predict execution subgoals or learn which bottom-up program/value compositions to explore next. | Synth’s compact prior guide reorders a bounded typed enumerator; it does not replace enumeration with a learned search policy. |
| Sequence and general-LLM PBE | [RobustFill](https://proceedings.mlr.press/v70/devlin17a.html), [GPT-4o](https://openai.com/index/gpt-4o-system-card/), [Claude](https://platform.claude.com/docs/en/models/overview) | Sequence models or general LLMs generate candidate transformations/programs from examples or prompts; RobustFill targets string transformations. | Synth executes candidates in a restricted typed DSL and verifies them against examples and fresh inputs rather than treating generated text as executable truth. |

No head-to-head comparison against these systems is claimed. External Transformer/GPU baselines, general-LLM prompting baselines, and string-domain systems were not executed under this CPU-only scope. The external DeepCoder task splits were used as evaluation data; the original DeepCoder model was not reproduced. RobustFill and the string-oriented settings of related systems are outside Synth’s integer/list DSL.

## Repository map

```text
synth/
├── esq_dsl/                  # Typed DSL, strict interpreter, quotient search, guide, oracle
├── checkpoints/              # Packaged CPU model, SHA-256 sidecar, model card
├── benchmarks/
│   ├── audits/               # Read-only aggregate audit record
│   └── data/                 # Instructions for regenerating the local family index
├── training/                 # Synthetic generator and model reproduction code
├── tests/                    # Unit, protocol, release, and provenance tests
├── docs/
│   └── experiments/          # V1–V6 reports, protocols, and audits
├── .github/workflows/        # CI
├── LICENSE
├── THIRD_PARTY_NOTICES.md
├── CITATION.cff
├── SECURITY.md
└── pyproject.toml
```

Raw training corpora, supervision arrays, generated reference programs, hidden target maps, private oracle traces, run journals, and scratch notebooks are not included in the repository. The benchmark family index is generated locally from the pinned synthetic corpus.

## License and citation

First-party Synth source code and the packaged ESQSetEncoder model weights are licensed under **Apache-2.0**. See [LICENSE](LICENSE) and [third-party notices](THIRD_PARTY_NOTICES.md). This grant does not relicense dependencies or upstream benchmark materials, and it does not cover excluded raw research data.

For machine-readable release metadata, see [CITATION.cff](CITATION.cff). The software release version 1.0.0 is distinct from experimental milestones V1–V6 and the V5 interactive mode.

```bibtex
@software{synth_esq_dsl_2026,
  author       = {Kshitij Pal},
  title        = {Synth (ESQ-DSL): Deterministic Program Synthesis via
                 Execution-Signature Quotienting},
  version      = {1.0.0},
  organization = {TENS LAB},
  year         = {2026},
  url          = {https://tenslab.dev},
  license      = {Apache-2.0}
}
```

For research history and detailed limits, start with the [documentation index](docs/README.md) and [architecture](docs/ARCHITECTURE.md).
