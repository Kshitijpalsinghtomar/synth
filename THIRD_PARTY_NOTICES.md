# Third-party notices

## First-party licensing

Copyright 2026 Kshitij Pal, TENS LAB.

Project home: https://tenslab.dev
Author and maintainer: Kshitij Pal.

Unless otherwise noted, all first-party Synth source code and the packaged
`ESQSetEncoder` model checkpoint are licensed under the Apache License,
Version 2.0. See the root LICENSE file. This grant does not relicense
third-party materials or research data excluded from the public release.

The sole packaged model checkpoint is
`checkpoints/esq_v3_converged.pt`, SHA-256
`a0f03d5066d86022d932699c1a6dfe68957d56131a38e7816e2085bda2000d41`. Its digest is also recorded in the model card,
sidecar, pyproject release metadata, and CITATION.cff.

## Direct Python dependencies

The optional dependency groups in `pyproject.toml` declare:

| Dependency | Purpose | Licence |
|---|---|---|
| NumPy | Neural feature preparation and training arrays | BSD-3-Clause |
| PyTorch | Neural model definition, inference and training | BSD-style; the distributed package may include additional components with their own notices |
| pytest | Test tooling | MIT |

The core symbolic package has no mandatory third-party runtime dependencies.
These are direct dependency licence identifiers, not a complete SBOM. Before
publishing binary environments or wheels, capture the exact resolved versions
and include all transitive/bundled licence notices for the target platform.

## ExeDec / DeepCoder benchmark materials

Synth references public DeepCoder task splits and documented DSL input/value
constraints distributed by ExeDec:

- Repository: https://github.com/google-deepmind/exedec
- Pinned revision: ef046ce2cc3fcd024e32f5dfe00e69700dac82ed
- Research paper: Shi et al., *ExeDec: Execution Decomposition for Compositional
  Generalization in Neural Program Synthesis*, ICLR 2024,
  https://arxiv.org/abs/2307.13883.

The upstream repository states that software is licensed under Apache License
2.0 and other materials under Creative Commons Attribution 4.0 International.
This notice is attribution/provenance information; it does not relicense
upstream files. Synth's published training corpus is generated synthetically;
the official ExeDec benchmark data and source are not bundled in this
repository. Do not bundle copied upstream code or benchmark assets unless the
specific file-level licences and required notices are preserved.

## Research-data exclusion

Raw synthetic task corpora, supervision arrays, generated reference programs,
hidden benchmark target maps, oracle response traces, and local run journals
are research artifacts and are excluded from the public source release.
Publish source generators, aggregate results, and permitted provenance/hashes
only. These private/generated artifacts are not covered by the root Apache-2.0
licence.

## Checkpoint loading security

PyTorch versions before 2.10.0 are affected by CVE-2026-24747 in the
`weights_only=True` unpickler. The loader permits an older runtime to load
only the exact SHA-256-pinned bundled checkpoint; alternate or untrusted
checkpoint files require PyTorch 2.10.0 or later. See the security advisory:
https://github.com/pytorch/pytorch/security/advisories/GHSA-63cw-57p8-fm3p
