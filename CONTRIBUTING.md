# Contributing

Synth intentionally stays focused on the typed integer/list fragment of the DeepCoder DSL.

## Scope
Do not add JSON/table operators, bidirectional search, macro compression, paid inference APIs, hosted LLM dependencies, or multi-turn CEGIS without a separate research decision and benchmark protocol. Keep the symbolic interpreter authoritative; a learned component must not silently change DSL semantics.

## Development checks

~~~bash
python -m pip install -e ".[test]"
python -m unittest discover -s tests -v
python -m compileall -q esq_dsl cli.py benchmarks tests training
~~~

For neural/training changes, install documented optional extras and run checkpoint-integrity and provenance tests.

## Research changes
- Freeze task splits, seeds, budgets, and metrics before inspecting evaluation outcomes.
- Preserve failed experiments and negative results in docs/experiments/.
- Do not tune on a consumed confirmation cohort.
- Keep visible examples, candidate generation, oracle access, and fresh evaluation inputs separate.
- Never use hidden targets to choose candidates or queries.
- Report truncated runs as truncated; do not call them exhaustive.
- Commit code, configuration, hashes, aggregate outputs, and a validator for every claimed result.
- Do not publish hidden target maps or raw oracle traces as benchmark test material.

## Pull requests
State the research question, files changed, tests run, benchmark protocol affected, and whether the result is exploratory, development-only, or confirmatory. Unit tests alone do not pass a research claim.