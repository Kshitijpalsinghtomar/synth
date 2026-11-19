# Security policy

**Project:** Synth (ESQ-DSL) 1.0.0  
**Author and maintainer:** Kshitij Pal  
**Umbrella:** [TENS LAB](https://tenslab.dev)  
**First-party release licence:** Apache-2.0  
**Bundled checkpoint SHA-256:** `a0f03d5066d86022d932699c1a6dfe68957d56131a38e7816e2085bda2000d41`

## Supported versions

Security fixes are developed against the current default branch and latest tagged release. Older untagged snapshots are not supported releases.

## Reporting a vulnerability

Do not publish exploit details, credentials, or sensitive proof-of-concept material in a public issue. Use GitHub private vulnerability reporting / Security Advisories when enabled. If private reporting is unavailable, contact the repository maintainer through a private GitHub channel and request a coordinated disclosure path.

## Model checkpoint handling

The bundled checkpoint is loaded through the restricted `weights_only=True` path and verified against both its adjacent SHA-256 sidecar and the digest recorded in the model card. The release checkpoint is:

`a0f03d5066d86022d932699c1a6dfe68957d56131a38e7816e2085bda2000d41`

On PyTorch versions earlier than 2.10.0, the loader permits only this exact bundled checkpoint digest. Custom or third-party checkpoints require PyTorch 2.10.0 or later. A checksum verifies byte identity with the published digest; it does not prove an arbitrary third-party checkpoint is benign. Do not load untrusted weights or bypass the restricted loader.

## Scope

Synth is a research prototype. First-party source code and the packaged ESQSetEncoder model weights are licensed under Apache-2.0. Third-party dependencies and upstream materials retain their own licences; raw research corpora, supervision arrays, generated reference programs, hidden target maps, and private oracle traces are excluded from the release.

The synthesizer executes a restricted in-process DSL. The optional subprocess oracle adapter launches the explicitly configured command without a shell. Users remain responsible for sandboxing external oracle programs and their file/network permissions.
