# SYNTH-ESQ-V6-FOUR-WAY-200 — Results and provenance

**Run date:** 2026-11-18  
**Source branch:** fix/eligible-only-benchmark-aggregation  
**Source commit:** 31578842956d59715de9c65cf1b6f42a2b26ebe1  
**Status:** completed; 200 tasks and 800 arm results durable

## Locked protocol

- 200 fresh structural families; target active-operator depth 1–4; search budget 4; strict intermediate bounds.
- Four existing arms: v1_symbolic, v3_guided, v5_ablation, v5_full.
- Each accepted task has 50 unique preflight probes (minimum 25 strict-valid), 100 unique query inputs, and 50 unique reserved fresh-evaluation inputs. All four streams are pairwise disjoint.
- Checkpoint SHA-256: a0f03d5066d86022d932699c1a6dfe68957d56131a38e7816e2085bda2000d41
- Prior-family exclusion archive SHA-256: 2564ab662e37a717d91019b4abc1b757f75df354899c8a0e40fcce0649049bee
- Runtime: Deepnote CPU Basic, 2 vCPU / 5 GiB; PyTorch 2.1.2+cu121.

## Candidate admission

The stream-capacity gate is part of the recorded source commit. Candidates were admitted only if they passed target preflight and could supply all exact disjoint stream sizes; no query or reserved quota was shortened.

| Candidate outcome | Count |
|---|---:|
| Candidates evaluated | 275 |
| Accepted tasks | 200 |
| Rejected: target preflight | 64 |
| Rejected: query pool could not supply 100 unique rows | 4 |
| Rejected: reserved pool could not supply 50 unique rows | 7 |
| Generation attempts used | 1,058 |
| Prior-family overlap in accepted cohort | 0 |
| Target maps frozen | 400 |

## Four-way results

| Arm | Visible exact fit (n/200) | Full fresh behaviour match (n/196 eligible) | Fresh-case accuracy (n/8,869) | Queryable sessions (per task) | Fallback sessions (per task) | Runtime p50 / p95 (ms) |
|---|---:|---:|---:|---:|---:|---:|
| v1_symbolic | 186/200 (93.00%) | 60/196 (30.61%) | 6211/8869 (70.03%) | — | — | 9.353 / 330.884 |
| v3_guided | 193/200 (96.50%) | 62/196 (31.63%) | 6277/8869 (70.77%) | — | — | 10.752 / 305.606 |
| v5_ablation | 194/200 (97.00%) | 70/196 (35.71%) | 6595/8869 (74.36%) | 76 (38.00%) | 133 (66.50%) | 18.697 / 306.695 |
| v5_full | 192/200 (96.00%) | 71/196 (36.22%) | 6593/8869 (74.34%) | 75 (37.50%) | 132 (66.00%) | 18.748 / 307.191 |

**Denominators:** visible exact fit is out of 200 tasks; full fresh-behaviour match is out of the 196 eligible tasks; fresh-case accuracy is over 8,869 fresh input cases. Queryable and fallback rates are per 200 tasks. The symbolic and guided baselines do not create candidate sessions, so their queryable/fallback metrics are not applicable.

## Reading the result

- v5_full has 71/196 complete fresh-behaviour matches (36.22%) versus 70/196 (35.71%) for v5_ablation.
- v5_ablation has 6,595/8,869 fresh-case correct (74.36%) versus 6,593/8,869 (74.34%) for v5_full.
- v5_ablation has 76 queryable sessions (38.0% per task) and 133 fallback sessions (66.5%); v5_full has 75 queryable sessions (37.5%) and 132 fallback sessions (66.0%).
- The full arm adds one complete-behaviour match on this cohort but does not improve aggregate fresh-case accuracy. These are descriptive comparisons from one fixed cohort; no repeated-seed or inferential analysis was run, so the small differences should not be treated as statistically established.

## Provenance and durable artifacts

The source manifest records the clean source commit, branch and origin. Family overlap count is zero. The freeze manifest commits hashes for the cohort lock, preflight report, preflight inputs, candidate freeze, query/evaluation inputs and target-map manifest.

- Cohort lock SHA-256: c97863a60ed2fe8d27aea9b037304c9e006af92495e7a200aaf4234a4cd74a6d
- Preflight report SHA-256: a92df2f4e8442da9bc9fc81612c62b3e9f12dd683c658351008cc5d617f129d0
- Candidate freeze SHA-256: 0c13a66e30939026d5ea785c37dc413d9147eb5fd0c95f0ec21f96c9b689d175
- Query/evaluation inputs SHA-256: 560f9359b3bd1b8132b99b42886fd2f83a35131c3777bdf64ec981c60757b581
- Target-map manifest SHA-256: d5f7a466ff02d9a51e81abb67d95be739cb30d307debc65653325e1af2da82b6
- Source manifest SHA-256: 1afda3dd979ccc104070ba507be8ff0febfb6c5939821da2a433cc049a6c546a
- Task results SHA-256: 12020dadd7c9dd3d5089ecda4e02804ba0cb817006da29caec1fd601010fdfb1
- Arm results SHA-256: 8082064ee4a93105700a58471d1717579534f9ab70a5ee059bb5d361dd69ef28
- Oracle provenance SHA-256: 4d856bccc3bc5f9cbce05dbc06344a013e0c24bdb39caa155c33190d05382a98

The durable scorer completed with status complete: 200/200 tasks, 800/800 arm results, zero remaining tasks/arms. The machine-readable summary, progress, artifact manifest, arm/task journals and oracle provenance are stored in benchmarks/results/four_way_200_v6_scoring. The frozen cohort and its full input/target-map evidence are stored in benchmarks/results/four_way_200_v6.

## Claim boundary

This is a fresh structural-family-held-out synthetic generator cohort with a local file-backed reference oracle. It is **not** an official ExeDec benchmark and does not support claims about performance on the official ExeDec benchmark.
