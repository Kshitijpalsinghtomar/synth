# Synth: preliminary commercial and licensing assessment

**Status:** ownership and Apache-2.0 decision approved 18 November 2026; V6 evidence complete; public documentation and release metadata being finalized  
**Scope:** V6 strict-depth-4 branch, first-party source, packaged v3 prior-guide checkpoint, generated research materials, and direct dependencies  
**Decision:** owner-approved Apache-2.0 release for first-party source code and packaged weights; retain the current research-evidence and product-scope limitations.

## 1. What exists today

Synth is a bounded synthesizer for the DeepCoder typed integer/list DSL. It uses exact execution-signature deduplication, optional learned operation/lambda/length priors to reorder symbolic enumeration, and an optional single-turn oracle over a frozen exact-fit candidate set.

The shipped package is intentionally narrow:
- 15 typed operators and 19 lambda forms in the current model vocabulary;
- task input/output examples, with a fixed three-example feature representation;
- bounded search (four operations, 10,000 signatures, nominal 300 ms task budget in the benchmark);
- a CPU-trained 137,897-parameter ESQSetEncoder prior guide;
- one explicit oracle request at most in interactive mode.

It is not a general-purpose code generator, ETL platform, spreadsheet product, agent, or autonomous CEGIS system. The current repository does not ship table/JSON/string operators, connectors, user-facing workflow, multi-tenant service, audit UI, deployment controls, SLAs, or customer support.

## 2. Evidence versus market claims

### Technical evidence currently on record

- v3 has a positive result on one untouched ExeDec DeepCoder confirmation split: 118/180 versus 108/180 complete fresh-behaviour matches for the original v3 checkpoint. This is bounded evidence on that benchmark and checkpoint, not general synthesis capability.
- v4 candidate ranking has a modest aggregate candidate-only improvement (327/371 versus 320/371), with a regression on one cohort. The earlier 344/371 CEGIS headline was invalidated by a target-dependent query-selection flaw and must not be used as confirmatory evidence.
- The original v5 one-shot result is a small generator-matched synthetic study with a high fallback rate. It is not an official external benchmark or customer study.
- The V6 strict-depth-4 confirmatory evaluation is complete: 200 fresh structural families, zero accepted-family overlap, 200/200 tasks and 800/800 arm results scored. Complete fresh-behaviour match rates were 30.61% (V1 symbolic), 31.63% (V3 guided), 35.71% (V5 ablation), and 36.22% (V5 full); fresh-case accuracy was 70.03%, 70.77%, 74.36%, and 74.34%, respectively. See [V6 results and provenance](experiments/v6-four-way-200-results.md). This is a synthetic generator-held-out evaluation with a local file-backed reference oracle, not an official ExeDec benchmark or human-oracle study.

### What this evidence does not prove

It does not establish customer demand, willingness to pay, production reliability, performance on real customer data, superiority to existing data-preparation products, or a large addressable market. A synthetic held-out family split is useful scientific evidence but is not a proxy for a paid deployment.

## 3. Real-world need and incumbent alternatives

Program synthesis from examples is a real, established product category, not a newly invented market:
- Microsoft documents Flash Fill in Excel for pattern-based transformations from user examples: https://support.microsoft.com/en-us/excel/enable-flash-fill-in-excel
- Microsoft's PROSE research/engineering team lists integrations across Excel, Visual Studio, Azure Data Factory, Azure Data Studio, Azure Monitor, Power Apps, Power BI, Power Query, PowerShell and Data Migration Assistant: https://microsoft.github.io/prose/
- Microsoft documents Power Query as a data connectivity, preparation and transformation engine used across Excel, Power BI, Power Apps, Azure Data Factory and other products: https://learn.microsoft.com/en-us/power-query/power-query-what-is-power-query
- Workato describes enterprise process automation spanning applications, data systems, transformations, decision logic and exception handling: https://docs.workato.com/process-automation.html

These are evidence that users pay for adjacent outcomes (data transformation, integration, workflow automation), not evidence that they will buy Synth. They also show that Microsoft and established automation vendors already cover much of the obvious surface area. Synth should not try to compete with Excel Flash Fill or Power Query on their home turf.

## 4. Plausible commercial wedges — hypotheses, not validated markets

The only credible route is to embed the synthesis engine inside a narrow workflow where a small, verifiable program is more valuable than free-form generated code. Possible hypotheses:

1. **Domain-specific transformation SDK for a vendor:** a software vendor has a constrained internal DSL for mapping/normalizing structured values. Synth could propose a small program from examples; the vendor supplies the DSL, execution environment and integration.
2. **On-premise transformation component for a regulated workflow:** a buyer needs deterministic, inspectable transformations and cannot send examples/data to an external LLM. This requires a broader useful DSL, robust failure/ambiguity handling, security review and real deployment evidence.
3. **Specialist tool for migrating or mapping structured records:** an implementation partner repeatedly maps fields between two known schemas and could use example-driven synthesis to reduce manual rule authoring. The current integer/list DSL is not sufficient for this use case; it is only a possible direction for a future typed DSL.
4. **Research or OEM licensing:** a vendor licenses the algorithm/SDK for a bounded domain after independent replication and a technical evaluation. This is more plausible than selling the current CLI directly to end users.

Do not treat these as market findings. They are testable hypotheses derived from real adjacent workflows. Current Synth cannot yet perform common string, date, JSON, tabular, schema, connector or multi-step integration transformations.

## 5. Commercial models if a real wedge is validated

| Model | What the customer pays for | What must exist first |
|---|---|---|
| Embedded SDK / OEM licence | Right to embed the synthesis engine in the customer's product | Stable API, supported DSL extension model, security and compatibility policy, measurable customer value |
| Enterprise on-prem deployment | Private deployment, support, version control, auditability and integration | Production packaging, access controls, observability, deployment automation, support commitments |
| Hosted API | Usage by synthesis job or workload | Multi-tenant isolation, predictable latency/cost, abuse controls, uptime, data retention policy |
| Implementation / integration service | A scoped workflow implementation and maintenance | One repeatable vertical workflow and a buyer with budget |
| Research licence | Evaluation and commercialisation rights for a defined use | Clean IP ownership, licence terms, reproducible evidence and technical documentation |

Pricing should not be invented from comparable SaaS seat prices. First establish a buyer, a repeated workflow, current labour/error cost, measurable time saved, integration cost and procurement budget. Then test willingness to pay with paid pilots or signed evaluation agreements.

## 6. Market validation plan (before building a product)

Run a small, falsifiable discovery process:
1. Pick one workflow hypothesis, not all four.
2. Interview 12–15 people who own that workflow (engineering/data-platform leads, implementation partners, or product owners). Ask them to show a recent real transformation task, current toolchain, failure modes, review process, frequency and cost. Do not pitch first.
3. Obtain 3–5 anonymized real task examples with input/output pairs and the actual target language/schema. Establish data rights and confidentiality before accepting data.
4. Build a benchmark from those real tasks, with customer-approved holdout cases and a baseline against the incumbent workflow (manual rules, existing ETL, or LLM-assisted authoring).
5. Measure end-to-end time-to-correct-rule, exact correctness on unseen cases, ambiguity/abstention rate, human edits, runtime, integration cost and maintenance burden.
6. Seek at least two paid pilots or signed, budgeted evaluations before treating demand as validated.

**Kill criteria:** no repeated task pattern; examples do not determine intent safely; incumbent tools are already adequate; integration cost exceeds labour savings; customers will not provide data or pay for a pilot; or the system cannot beat the baseline on customer-approved holdouts.

## 7. Preliminary licence and ownership inventory

Repository inspection of the 49 tracked files on `release/esq-dsl-v5` found:
- No `LICENSE`, `COPYING`, or project-wide source licence.
- No separate model-weight licence in the model card.
- No dependency lockfile, SBOM, or generated third-party licence bundle.
- `pyproject.toml` declares no mandatory runtime dependencies; optional extras are NumPy, PyTorch and pytest with minimum versions, not exact pins.
- The package and tests import Python standard-library modules, NumPy, PyTorch and pytest. The inspected first-party Python source files contain no explicit third-party copyright/SPDX headers. This is a preliminary source scan, not a full provenance audit.
- No vendored third-party source directory or submodule appears in the tracked repository tree.
- `THIRD_PARTY_NOTICES.md` documents ExeDec provenance. ExeDec states its software is Apache-2.0 and other materials are CC BY 4.0. Synth's notice says it references DeepCoder splits and documented DSL constraints, pinned to ExeDec commit `ef046ce2cc3fcd024e32f5dfe00e69700dac82ed`. The current Git repository does not include the official ExeDec task dataset or its source code; the Synth training corpus is generated synthetically. If any ExeDec data or code is later redistributed, its exact file-level licence and attribution requirements must be followed.
- The current checkpoint is trained on the project's synthetic corpus, not on the official ExeDec benchmark tasks. Its model card records synthetic corpus/supervision hashes and a partial provenance status for the historical packaged rebuild. The current training script can produce a newly provenance-complete checkpoint, but that is not a reason to retrain for this audit.
- Git history visible on this branch lists one commit author identity (KPST). This is useful evidence, but it does not establish legal ownership by itself; check employment, university, contractor, collaboration and assignment obligations outside Git.

### Third-party licensing observations

- ExeDec's own repository states Apache-2.0 for software and CC BY 4.0 for other materials: https://github.com/google-deepmind/exedec
- NumPy's project documentation identifies BSD-3-Clause for its source/docs and describes additional permissively licensed components: https://numpy.org/doc/stable/license.html
- PyTorch's current project metadata lists a compound set of licences for its distribution, including Apache-2.0, BSD, MIT, ISC, BSL and Zlib components: https://github.com/pytorch/pytorch/blob/main/pyproject.toml
- pytest is MIT-licensed: https://pytest.org/en/latest/license.html

The actual resolved PyTorch/NumPy wheel builds can contain transitive and bundled components. A final distribution needs a lockfile/SBOM and notices for the exact platform artefacts, not merely a list of direct Python imports.

### Preliminary licensing position

The owner confirmed on 18 November 2026 that TensLab independently owns the first-party code and packaged checkpoint, with no client, employer, or university IP restrictions. The approved licence is Apache License 2.0 for both first-party source code and the packaged model weights. This grants downstream commercial reuse and does not reserve exclusivity. Third-party components retain their own licences. Raw synthetic corpora, supervision arrays, generated reference programs, hidden target maps, and private oracle traces are excluded from the public release. Do not publish those data artifacts or imply that the Apache licence covers them.

The repository now carries a root Apache-2.0 LICENSE and THIRD_PARTY_NOTICES.md. The approved first-party grant covers the source code and packaged checkpoint weights. It does not relicense dependencies, ExeDec materials, or excluded research data. Binary environment and wheel distributions still need exact resolved dependency versions and transitive/bundled notices, as stated in THIRD_PARTY_NOTICES.md.

## 8. Decision

**Current product decision: research prototype; no demonstrated product-market fit; no defensible TAM estimate. Licensing decision: Apache-2.0 for first-party source and packaged checkpoint weights. V6 evidence is complete and documented; customer validation and any platform-specific binary/SBOM work remain separate from this source release.**

The underlying need for example-driven data transformation and workflow automation is real. The obvious product surfaces are already served by capable incumbents. Synth's current DSL and evaluation evidence are far too narrow to claim it is a commercial alternative.

The next commercial step is not adding features or estimating a giant market. It is choosing one narrow buyer/workflow, obtaining real tasks, benchmarking against the buyer's current method, and testing willingness to pay. If that test fails, keep Synth as a research asset rather than forcing it into a startup narrative.
