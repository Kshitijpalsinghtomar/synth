> **Status: Historical Record — Superseded by V6 Release Audit.** This document preserves the earlier V5 experiment or audit, including contemporaneous limitations and conclusions. It remains part of the research history; the [V6 four-way results](v6-four-way-200-results.md) and [V6 strict-depth-4 protocol](v6-strict-depth4-preflight-protocol.md) are the current release-level synthetic evaluation record.

# ESQ-DSL v5 — one-turn oracle baseline and queryability release

**Date:** 16 November 2026  
**Scope:** Typed DeepCoder list/integer DSL only. One external query maximum; no iterative CEGIS.

## Protocol

V5 freezes a portfolio of up to three distinct shortest exact-fit candidates, proposes one query from a deterministic profile-matched pool, prevalidates the query by executing every frozen candidate, asks the oracle once, and selects only candidates whose prediction exactly matches the answer. Skip, unknown, timeout, invalid response, adapter error, or zero survivors returns to the original pre-query best candidate. There is no retry or candidate regeneration after the response.

The initial implementation includes human-terminal and local subprocess adapters. Query provenance is append-only; the proposal is recorded before the oracle call. Reserved fresh-evaluation inputs and visible examples are excluded from query selection.

## Initial 200-task fresh-family result

The original v5 run used 200 new structural families with zero overlap against the previous 100k synthetic corpus. Candidate generation was visible-only. It produced 106 eligible tasks and 4,671 eligible valid fresh cases.

| Measure | V3 top-1 | Original V5 selected |
|---|---:|---:|
| Complete fresh-behaviour matches | 26/106 (24.53%) | 30/106 (28.30%) |
| Fresh-case accuracy on eligible cases | 68.02% | 70.67% |
| Fresh-case accuracy across all valid task cases | 66.61% | 69.33% |

The one-shot mechanism recovered four additional complete-task matches on the eligible subset and improved fresh-case accuracy by 2.65 percentage points.

| Query/fallback measure | Result |
|---|---:|
| Candidate sessions | 200 |
| Queryable sessions | 80 (40%) |
| Oracle requests | 80 |
| Valid oracle answers | 45 |
| Target-undefined / unknown answers | 35 |
| Fallback sessions | 162 (81%) |
| Not disambiguable candidate pools | 102 |
| No valid disagreement query | 18 |
| Oracle skip/unknown | 35 |
| Zero survivors | 7 |

**Decision:** the one-shot boundary is usable and preserves a deterministic fallback, but the 40% queryable rate and 81% fallback rate are not good enough to call it complete. The release follow-up therefore retains up to three shortest distinct exact-fit candidates for the target execution signature and generates conservative, in-distribution queries using visible value and list-length profiles. The full four-arm result for this improved release is recorded separately in the root benchmark manifest after execution.

## Claim boundary

These are local synthetic generator-matched results using a subprocess oracle backed by withheld synthetic reference programs. They are not an official ExeDec benchmark, a human-oracle study, or evidence of autonomous inference of hidden outputs. A real deployment must connect an authorized user, test harness, or runtime oracle.
