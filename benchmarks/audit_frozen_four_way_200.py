"""Read-only integrity, strictness, candidate-portfolio and provenance audit for frozen V5-200."""

import os, sys, json, hashlib, gzip
from pathlib import Path
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmarks"))

import run_four_way as rf
from families import active_program_statements
from esq_dsl import interpreter as core
from esq_dsl.oracle import _normalise_candidates, propose_one_query

SOURCE = Path("benchmarks/results/four_way_200")
RECOVERY = Path("benchmarks/results/four_way_200_recovery_final")
AUDIT_DIR = Path("benchmarks/audits")
AUDIT_DIR.mkdir(parents=True, exist_ok=True)
ARMS = ("v1_symbolic", "v3_guided", "v5_ablation", "v5_full")
EXPECTED_TASK_IDS = [f"synth-200-{i:04d}" for i in range(200)]

def sha_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def read_jsonl(path):
    rows = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            item = json.loads(line)
            if not isinstance(item, dict):
                raise AssertionError(f"{path}:{n}: expected object")
            rows.append(item)
    return rows

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def active_ops(program):
    return len(active_program_statements(program))

# 1) Re-verify the frozen artifacts and recovery journal before any analysis.
cohort = json.loads((SOURCE / "cohort_lock.json").read_text(encoding="utf-8"))
target_manifest = json.loads((SOURCE / "target_map_manifest.json").read_text(encoding="utf-8"))
manifest = json.loads((RECOVERY / "artifact_manifest.json").read_text(encoding="utf-8"))
summary = json.loads((RECOVERY / "summary.json").read_text(encoding="utf-8"))
progress = json.loads((RECOVERY / "progress.json").read_text(encoding="utf-8"))

assert cohort["experiment"] == "SYNTH-ESQ-V5-FOUR-WAY-200"
assert cohort["task_count"] == 200
assert cohort["min_valid_cases"] == 25
assert cohort["reserved_evaluation_inputs_per_task"] == 50
assert cohort["query_pool_size"] == 100
assert cohort["search"]["max_ops"] == 4
assert sha_file(SOURCE / "candidate_freeze.jsonl") == cohort["candidate_freeze_sha256"]
assert sha_file(SOURCE / "query_and_eval_inputs.jsonl") == cohort["query_eval_inputs_sha256"]
assert sha_file(ROOT / "benchmarks/data/prior_family_hashes.txt.gz") == cohort["prior_family_exclusion_file_sha256"]
assert sha_file(ROOT / "checkpoints/esq_v3_converged.pt") == cohort["checkpoint_sha256"]
assert target_manifest["count"] == 400
assert set(target_manifest["sha256_by_file"]) == {
    f"{task_id}-{arm}.json" for task_id in EXPECTED_TASK_IDS
    for arm in ("v5_ablation", "v5_full")
}
for filename, expected_sha in target_manifest["sha256_by_file"].items():
    assert sha_file(SOURCE / "target_maps" / filename) == expected_sha

journal_bytes = (RECOVERY / "four_way_task_results.jsonl").read_bytes()
provenance_bytes = (RECOVERY / "oracle_provenance.jsonl").read_bytes()
journal_sha = hashlib.sha256(journal_bytes).hexdigest()
provenance_sha = hashlib.sha256(provenance_bytes).hexdigest()
assert journal_sha == summary["task_results_sha256"]
assert journal_sha == manifest["summary"]["task_results_sha256"]
assert journal_sha == manifest["files"]["four_way_task_results.jsonl"]
assert provenance_sha == manifest["provenance_sha256"]
assert provenance_sha == manifest["files"]["oracle_provenance.jsonl"]
assert hashlib.sha256((RECOVERY / "summary.json").read_bytes()).hexdigest() == manifest["files"]["summary.json"]
assert hashlib.sha256((RECOVERY / "progress.json").read_bytes()).hexdigest() == manifest["files"]["progress.json"]
assert summary == manifest["summary"]
assert progress["completed_task_count"] == progress["task_count"] == 200
assert progress["remaining_task_count"] == 0

journal_rows = read_jsonl(RECOVERY / "four_way_task_results.jsonl")
assert len(journal_rows) == 200
assert [r["task_id"] for r in journal_rows] == EXPECTED_TASK_IDS
journal = {r["task_id"]: r for r in journal_rows}
events = read_jsonl(RECOVERY / "oracle_provenance.jsonl")
assert len(events) == 1641
assert [e["seq"] for e in events] == list(range(len(events)))
events_by_session = defaultdict(list)
for event in events:
    events_by_session[event["task_id"]].append(event)

# 2) Reconstruct the exact visible tasks deterministically from the locked seed/archive.
old_families, prior_sha = rf.load_prior_families(ROOT / "benchmarks/data/prior_family_hashes.txt.gz")
assert prior_sha == cohort["prior_family_exclusion_file_sha256"]
tasks, attempts = rf.generate_cohort(old_families, cohort["task_count"])
assert attempts == cohort["generation_attempts_used"]
assert len(tasks) == 200
assert len({t["program_family_hash"] for t in tasks}) == 200
assert not ({t["program_family_hash"] for t in tasks} & old_families)
task_by_id = {t["task_id"]: t for t in tasks}
assert list(task_by_id) == EXPECTED_TASK_IDS

# 3) Reconcile all candidate, query, target, and journal records.
frozen_rows = read_jsonl(SOURCE / "candidate_freeze.jsonl")
query_rows = read_jsonl(SOURCE / "query_and_eval_inputs.jsonl")
assert len(frozen_rows) == 800
assert len(query_rows) == 200
frozen = {}
for row in frozen_rows:
    key = (row["task_id"], row["arm"])
    assert key not in frozen, f"duplicate frozen row: {key}"
    frozen[key] = row
    assert row["task_id"] in task_by_id
    assert row["arm"] in ARMS
assert set(frozen) == {(tid, arm) for tid in EXPECTED_TASK_IDS for arm in ARMS}
candidate_family_hash_rows = 0
candidate_family_hash_mismatches = 0
for row in frozen_rows:
    if row.get("family_hash") is not None:
        candidate_family_hash_rows += 1
        candidate_family_hash_mismatches += int(
            row["family_hash"] != task_by_id[row["task_id"]]["program_family_hash"]
        )
assert candidate_family_hash_mismatches == 0

query_by_id = {}
for row in query_rows:
    assert row["task_id"] not in query_by_id
    query_by_id[row["task_id"]] = row
assert set(query_by_id) == set(EXPECTED_TASK_IDS)

target_programs = {}
depth_hist = Counter()
depth_by_task = {}
target_pair_hashes = {}
for tid in EXPECTED_TASK_IDS:
    task = task_by_id[tid]
    target = task["program"]
    assert target
    assert active_ops(target) <= 6
    target_programs[tid] = target
    depth = active_ops(target)
    depth_hist[depth] += 1
    depth_by_task[tid] = depth

    # Both target-map arms must contain the same target, and that target must
    # match the deterministic task reconstructed from the locked generator.
    pair = {}
    for target_arm in ("v5_ablation", "v5_full"):
        path = SOURCE / "target_maps" / f"{tid}-{target_arm}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert list(payload) == [f"{tid}-{target_arm}"]
        pair[target_arm] = payload[f"{tid}-{target_arm}"]
        assert pair[target_arm] == target
    assert pair["v5_ablation"] == pair["v5_full"]
    target_pair_hashes[tid] = hashlib.sha256(target.encode()).hexdigest()

# Check input-stream uniqueness and disjointness. Query pool may overlap visible
# examples by construction; record that separately. Reserved inputs must overlap neither.
stream_audit = {
    "visible_examples": 0,
    "query_pool_rows": 0,
    "query_pool_duplicates": 0,
    "reserved_rows": 0,
    "reserved_duplicates": 0,
    "visible_query_overlap_rows": 0,
    "visible_reserved_overlap_rows": 0,
    "query_reserved_overlap_rows": 0,
}
query_pool_length_histogram = Counter()
query_pool_short_task_ids = []
for tid in EXPECTED_TASK_IDS:
    task = task_by_id[tid]
    qrow = query_by_id[tid]
    query_pool = qrow["query_pool"]
    reserved = qrow["reserved_evaluation_inputs"]
    visible = [
        {name: values[i] for name, values in task["inputs"].items()}
        for i in range(len(task["outputs"]))
    ]
    vis = {canonical(x) for x in visible}
    qlist = [canonical(x) for x in query_pool]
    qset = set(qlist)
    rlist = [canonical(x) for x in reserved]
    rset = set(rlist)
    stream_audit["visible_examples"] += len(visible)
    stream_audit["query_pool_rows"] += len(query_pool)
    stream_audit["query_pool_duplicates"] += len(qlist) - len(qset)
    stream_audit["reserved_rows"] += len(reserved)
    stream_audit["reserved_duplicates"] += len(rlist) - len(rset)
    stream_audit["visible_query_overlap_rows"] += len(vis & qset)
    stream_audit["visible_reserved_overlap_rows"] += len(vis & rset)
    stream_audit["query_reserved_overlap_rows"] += len(qset & rset)
    query_pool_length_histogram[len(query_pool)] += 1
    if len(query_pool) < cohort["query_pool_size"]:
        query_pool_short_task_ids.append(tid)
    assert len(visible) == 3
    # The lock records the requested maximum. Finite input domains and bounded
    # unique-sampling attempts can legitimately yield a shorter frozen pool.
    assert 0 < len(query_pool) <= cohort["query_pool_size"], tid
    assert len(query_pool) == len(qset), f"duplicate query-pool input: {tid}"
    assert len(reserved) == cohort["reserved_evaluation_inputs_per_task"]
    assert len(rset) == 50, f"duplicate reserved input: {tid}"
    assert not (vis & rset), f"visible/reserved overlap: {tid}"
    assert not (qset & rset), f"query/reserved overlap: {tid}"
assert stream_audit["visible_reserved_overlap_rows"] == 0
assert stream_audit["query_reserved_overlap_rows"] == 0
assert stream_audit["reserved_duplicates"] == 0

# Parse each candidate and target once. This is the main performance correction
# over the earlier audit, which parsed each program on every input execution.
ast_cache = {}
def ast_for(program):
    if program not in ast_cache:
        ast_cache[program] = core.parse_program(program)
    return ast_cache[program]

def bounded_trace(ast, inputs):
    """Mirror interpreter execution while retaining the first strict-bound failure."""
    env = {}
    violations = []
    for statement in ast:
        if statement.op == "INPUT":
            if statement.lhs not in inputs:
                return None, "missing_input", violations
            env[statement.lhs] = inputs[statement.lhs]
            continue
        if any(name not in env for name in statement.args):
            return None, "missing_variable", violations
        args = [env[name] for name in statement.args]
        actual_types = tuple("list" if isinstance(x, list) else "int" for x in args)
        if actual_types != core.OPS[statement.op].arg_types:
            return None, "type_mismatch", violations
        value = core.apply_op(statement.op, statement.lambda_token, args, strict=False)
        if value is None:
            return None, "undefined", violations
        if not core.is_valid_result(value):
            violations.append({
                "lhs": statement.lhs,
                "op": statement.op,
                "is_final": statement.lhs == ast[-1].lhs,
                "value_type": "list" if isinstance(value, list) else "int",
            })
        env[statement.lhs] = value
    return env[ast[-1].lhs], None, violations

def strict_value(trace):
    value, failure, violations = trace
    if failure is not None or violations:
        return None
    return value

# Sanity check the trace against the authoritative interpreter over a deterministic
# sample of real frozen candidates and inputs before using it for the full sweep.
trace_checks = 0
for tid in EXPECTED_TASK_IDS[:12]:
    task = task_by_id[tid]
    qrow = query_by_id[tid]
    visible = [{name: values[i] for name, values in task["inputs"].items()} for i in range(3)]
    sample_inputs = visible + qrow["reserved_evaluation_inputs"][:8]
    for arm in ARMS:
        row = frozen[(tid, arm)]
        programs = [row["program"]] + [c["program"] for c in (row.get("candidates") or []) if c.get("program")]
        for program in dict.fromkeys(p for p in programs if p):
            ast = ast_for(program)
            for inp in sample_inputs:
                tr = bounded_trace(ast, inp)
                permissive = core.execute_program(ast, inp, strict=False)
                strict = core.execute_program(ast, inp, strict=True)
                assert tr[0] == permissive
                assert strict_value(tr) == strict
                trace_checks += 1

# 4) Strictness and portfolio audit on the exact visible and reserved streams.
strictness = {
    arm: {
        "unique_programs": 0,
        "effective_portfolio_program_entries": 0,
        "primary_program_not_in_candidate_list": 0,
        "visible_program_input_executions": 0,
        "visible_permissive_successes": 0,
        "visible_strict_successes": 0,
        "programs_permissive_visible_exact_fit": 0,
        "programs_strict_visible_exact_fit": 0,
        "portfolio_permissive_visible_exact_fit_tasks": 0,
        "portfolio_strict_visible_exact_fit_tasks": 0,
        "selected_permissive_visible_exact_fit_tasks": 0,
        "selected_strict_visible_exact_fit_tasks": 0,
        "journal_visible_exact_fit_tasks": 0,
        "journal_visible_exact_fit_without_strict_match_tasks": 0,
        "journal_visible_exact_fit_permissive_reconciliation_mismatches": 0,
        "permissive_to_strict_visible_exact_fit_mismatch_tasks": 0,
        "visible_strict_bound_rejections": 0,
        "visible_intermediate_first_rejections": 0,
        "visible_final_first_rejections": 0,
        "reserved_program_input_executions": 0,
        "reserved_permissive_successes": 0,
        "reserved_strict_successes": 0,
        "reserved_strict_bound_rejections": 0,
        "reserved_intermediate_first_rejections": 0,
        "reserved_final_first_rejections": 0,
        "reserved_target_valid_program_input_executions": 0,
        "reserved_target_valid_strict_bound_rejections": 0,
        "programs_affected_on_visible": 0,
        "programs_affected_on_reserved": 0,
        "tasks_affected_on_visible": 0,
        "tasks_affected_on_reserved": 0,
        "portfolio_strict_full_matches_all_tasks": 0,
        "portfolio_strict_full_matches_eligible_tasks": 0,
        "portfolio_strict_full_matches_overdepth_tasks": 0,
        "portfolio_strict_full_matches_eligible_overdepth_tasks": 0,
        "selected_strict_full_matches_all_tasks": 0,
        "selected_strict_full_matches_eligible_tasks": 0,
        "portfolio_available_but_not_selected_all_tasks": 0,
        "portfolio_available_but_not_selected_eligible_tasks": 0,
        "selected_program_hash_missing": 0,
        "selected_case_count_mismatches": 0,
        "target_valid_case_count_mismatches": 0,
    }
    for arm in ARMS
}
first_bound_examples = []
target_valid_distribution = Counter()
portfolio_depth_cross = defaultdict(lambda: defaultdict(Counter))
strict_program_cache_counts = Counter()

for task_index, tid in enumerate(EXPECTED_TASK_IDS):
    task = task_by_id[tid]
    qrow = query_by_id[tid]
    stored_task = journal[tid]
    visible_inputs = [
        {name: values[i] for name, values in task["inputs"].items()}
        for i in range(3)
    ]
    reserved_inputs = qrow["reserved_evaluation_inputs"]
    target_ast = ast_for(target_programs[tid])
    expected_reserved = []
    for inp in reserved_inputs:
        expected, failure, violations = bounded_trace(target_ast, inp)
        expected_reserved.append(strict_value((expected, failure, violations)))
    valid_indices = [i for i, value in enumerate(expected_reserved) if value is not None]
    target_valid_distribution[len(valid_indices)] += 1
    depth = depth_by_task[tid]

    for arm in ARMS:
        row = frozen[(tid, arm)]
        metrics = stored_task["arms"][arm]
        stats = strictness[arm]
        all_programs = [row.get("program")] + [
            c.get("program") for c in (row.get("candidates") or [])
        ]
        programs = list(dict.fromkeys(p for p in all_programs if isinstance(p, str) and p.strip()))
        candidate_list_programs = list(dict.fromkeys(
            c.get("program") for c in (row.get("candidates") or [])
            if isinstance(c.get("program"), str) and c.get("program").strip()
        ))
        # v1/v3 use the primary search result directly. v5 sends only its
        # candidate-list entries through the one-shot selector; the primary
        # result is used only when that list is empty.
        effective_portfolio = (
            candidate_list_programs
            if arm in ("v5_ablation", "v5_full") and candidate_list_programs
            else ([row["program"]] if row.get("program") else [])
        )
        effective_portfolio_set = set(effective_portfolio)
        stats["unique_programs"] += len(programs)
        stats["effective_portfolio_program_entries"] += len(effective_portfolio_set)
        stats["primary_program_not_in_candidate_list"] += int(
            bool(candidate_list_programs) and bool(row.get("program"))
            and row["program"] not in set(candidate_list_programs)
        )
        target_valid_count = len(valid_indices)
        if target_valid_count != metrics["valid_fresh_cases"]:
            stats["target_valid_case_count_mismatches"] += 1

        portfolio_full = False
        task_visible_affected = False
        task_reserved_affected = False
        portfolio_visible_permissive_full = False
        portfolio_visible_strict_full = False
        visible_exact_by_program = {}
        for program in programs:
            ast = ast_for(program)
            depth_candidate = active_ops(program)
            assert depth_candidate <= cohort["search"]["max_ops"], (tid, arm, depth_candidate)
            program_visible_affected = False
            program_reserved_affected = False
            candidate_reserved_values = []
            program_visible_permissive_matches = []
            program_visible_strict_matches = []

            for visible_input, expected_output in zip(visible_inputs, task["outputs"]):
                value, failure, violations = bounded_trace(ast, visible_input)
                permissive_ok = failure is None and value is not None
                strict_ok = permissive_ok and not violations
                program_visible_permissive_matches.append(
                    permissive_ok and value == expected_output
                )
                program_visible_strict_matches.append(
                    strict_ok and value == expected_output
                )
                stats["visible_program_input_executions"] += 1
                stats["visible_permissive_successes"] += int(permissive_ok)
                stats["visible_strict_successes"] += int(strict_ok)
                if permissive_ok and not strict_ok:
                    program_visible_affected = True
                    stats["visible_strict_bound_rejections"] += 1
                    first = violations[0]
                    if first["is_final"]:
                        stats["visible_final_first_rejections"] += 1
                    else:
                        stats["visible_intermediate_first_rejections"] += 1
                    if len(first_bound_examples) < 40:
                        first_bound_examples.append({
                            "task_id": tid, "arm": arm, "stream": "visible",
                            "program_sha256": hashlib.sha256(program.encode()).hexdigest(),
                            "input": visible_input, "first_violation": first,
                            "all_violations": violations,
                        })

            for idx, inp in enumerate(reserved_inputs):
                value, failure, violations = bounded_trace(ast, inp)
                permissive_ok = failure is None and value is not None
                strict_ok = permissive_ok and not violations
                stats["reserved_program_input_executions"] += 1
                stats["reserved_permissive_successes"] += int(permissive_ok)
                stats["reserved_strict_successes"] += int(strict_ok)
                if idx in valid_indices:
                    stats["reserved_target_valid_program_input_executions"] += 1
                    if permissive_ok and not strict_ok:
                        stats["reserved_target_valid_strict_bound_rejections"] += 1
                if permissive_ok and not strict_ok:
                    program_reserved_affected = True
                    stats["reserved_strict_bound_rejections"] += 1
                    first = violations[0]
                    if first["is_final"]:
                        stats["reserved_final_first_rejections"] += 1
                    else:
                        stats["reserved_intermediate_first_rejections"] += 1
                    if len(first_bound_examples) < 40:
                        first_bound_examples.append({
                            "task_id": tid, "arm": arm, "stream": "reserved",
                            "program_sha256": hashlib.sha256(program.encode()).hexdigest(),
                            "input": inp, "first_violation": first,
                            "all_violations": violations,
                        })
                candidate_reserved_values.append(strict_value((value, failure, violations)))

            if program_visible_affected:
                stats["programs_affected_on_visible"] += 1
                task_visible_affected = True
            if program_reserved_affected:
                stats["programs_affected_on_reserved"] += 1
                task_reserved_affected = True

            permissive_visible_exact = all(program_visible_permissive_matches)
            strict_visible_exact = all(program_visible_strict_matches)
            visible_exact_by_program[program] = (
                permissive_visible_exact, strict_visible_exact
            )
            stats["programs_permissive_visible_exact_fit"] += int(
                permissive_visible_exact
            )
            stats["programs_strict_visible_exact_fit"] += int(strict_visible_exact)
            if program in effective_portfolio_set:
                portfolio_visible_permissive_full |= permissive_visible_exact
                portfolio_visible_strict_full |= strict_visible_exact

            # Candidate matches only count on target-valid reserved inputs.
            program_full_match = bool(
                valid_indices and all(
                    candidate_reserved_values[i] == expected_reserved[i]
                    for i in valid_indices
                )
            )
            if program in effective_portfolio_set and program_full_match:
                portfolio_full = True

        stats["tasks_affected_on_visible"] += int(task_visible_affected)
        stats["tasks_affected_on_reserved"] += int(task_reserved_affected)

        selected_sha = metrics["selected_program_sha256"]
        selected_program = next((
            p for p in programs
            if hashlib.sha256(p.encode()).hexdigest() == selected_sha
        ), None)
        if selected_sha and selected_program is None:
            stats["selected_program_hash_missing"] += 1
        selected_visible_permissive_full, selected_visible_strict_full = (
            visible_exact_by_program.get(selected_program, (False, False))
        )
        stats["portfolio_permissive_visible_exact_fit_tasks"] += int(
            portfolio_visible_permissive_full
        )
        stats["portfolio_strict_visible_exact_fit_tasks"] += int(
            portfolio_visible_strict_full
        )
        stats["selected_permissive_visible_exact_fit_tasks"] += int(
            selected_visible_permissive_full
        )
        stats["selected_strict_visible_exact_fit_tasks"] += int(
            selected_visible_strict_full
        )
        journal_visible_exact_fit = bool(metrics["visible_exact_fit"])
        stats["journal_visible_exact_fit_tasks"] += int(journal_visible_exact_fit)
        stats["journal_visible_exact_fit_without_strict_match_tasks"] += int(
            journal_visible_exact_fit and not portfolio_visible_strict_full
        )
        stats["journal_visible_exact_fit_permissive_reconciliation_mismatches"] += int(
            journal_visible_exact_fit != portfolio_visible_permissive_full
        )
        stats["permissive_to_strict_visible_exact_fit_mismatch_tasks"] += int(
            portfolio_visible_permissive_full and not portfolio_visible_strict_full
        )

        selected_full = False
        if selected_program is not None and valid_indices:
            selected_ast = ast_for(selected_program)
            selected_values = []
            selected_correct = 0
            for idx in range(50):
                value, failure, violations = bounded_trace(selected_ast, reserved_inputs[idx])
                actual = strict_value((value, failure, violations))
                selected_values.append(actual)
                if idx in valid_indices:
                    selected_correct += int(actual == expected_reserved[idx])
            if selected_correct != metrics["fresh_case_correct"]:
                stats["selected_case_count_mismatches"] += 1
            selected_full = selected_correct == len(valid_indices)

        eligible = len(valid_indices) >= cohort["min_valid_cases"]
        if portfolio_full:
            stats["portfolio_strict_full_matches_all_tasks"] += 1
            if eligible:
                stats["portfolio_strict_full_matches_eligible_tasks"] += 1
            if depth > 4:
                stats["portfolio_strict_full_matches_overdepth_tasks"] += 1
                if eligible:
                    stats["portfolio_strict_full_matches_eligible_overdepth_tasks"] += 1
        if selected_full:
            stats["selected_strict_full_matches_all_tasks"] += 1
            if eligible:
                stats["selected_strict_full_matches_eligible_tasks"] += 1
        if portfolio_full and not selected_full:
            stats["portfolio_available_but_not_selected_all_tasks"] += 1
            if eligible:
                stats["portfolio_available_but_not_selected_eligible_tasks"] += 1
        portfolio_depth_cross[arm][f"{'over4' if depth > 4 else 'le4'}|{'eligible' if eligible else 'ineligible'}"].update(
            {"portfolio_full": int(portfolio_full), "selected_full": int(selected_full)}
        )

    if (task_index + 1) % 25 == 0:
        print(f"CORE_AUDIT_PROGRESS {task_index + 1}/200", flush=True)

# 5) Re-run the deterministic, local query prevalidation only. This calls no oracle
# adapter and never reads target outputs to choose a query.
query_prevalidation = {
    "sessions_checked": 0,
    "screened_sessions": 0,
    "proposals_recomputed": 0,
    "queryable_journal_mismatches": [],
    "screening_event_mismatches": [],
    "proposal_event_mismatches": [],
    "strict_candidate_query_execution_rejections": 0,
    "strict_candidate_query_internal_bound_rejections": 0,
    "strict_candidate_query_final_bound_rejections": 0,
    "strict_candidate_query_runtime_invalids": 0,
    "per_arm": {
        "v5_ablation": {"sessions": 0, "queryable": 0, "fallback": 0, "screened": 0, "candidate_exec_rejections": 0},
        "v5_full": {"sessions": 0, "queryable": 0, "fallback": 0, "screened": 0, "candidate_exec_rejections": 0},
    },
}
query_screen_results = {}
for tid in EXPECTED_TASK_IDS:
    task = task_by_id[tid]
    qrow = query_by_id[tid]
    reserved_inputs = qrow["reserved_evaluation_inputs"]
    for arm in ("v5_ablation", "v5_full"):
        row = frozen[(tid, arm)]
        metrics = journal[tid]["arms"][arm]
        raw_candidates = row.get("candidates") or []
        if not raw_candidates:
            assert metrics["candidate_count"] == 0
            assert not metrics["queryable"]
            continue
        candidates = _normalise_candidates(raw_candidates)
        assert len(candidates) == metrics["candidate_count"]
        key = f"{tid}-{arm}"
        session_events = events_by_session.get(key, [])
        screens = [e for e in session_events if e["event"] == "query_pool_screened"]
        proposals_actual = [e for e in session_events if e["event"] == "query_proposed"]
        no_query_actual = [e for e in session_events if e["event"] == "no_query"]
        arm_stats = query_prevalidation["per_arm"][arm]
        arm_stats["sessions"] += 1
        arm_stats["queryable"] += int(bool(metrics["queryable"]))
        arm_stats["fallback"] += int(bool(metrics["fallback"]))
        query_prevalidation["sessions_checked"] += 1

        # Mirror run_one_shot_oracle's early exit exactly.
        if len(candidates) < 2 or any(not c.exact_fit for c in candidates):
            proposal = None
            stats = None
            assert not screens
            assert not metrics["queryable"]
            assert no_query_actual, key
        else:
            local_query_counters = Counter()
            def cached_strict_executor(program, inputs):
                value, failure, violations = bounded_trace(ast_for(program), dict(inputs))
                if failure is not None:
                    local_query_counters["runtime_invalid"] += 1
                    query_prevalidation["strict_candidate_query_runtime_invalids"] += 1
                    return None
                if violations:
                    local_query_counters["bound_rejected"] += 1
                    query_prevalidation["strict_candidate_query_execution_rejections"] += 1
                    if violations[0]["is_final"]:
                        local_query_counters["final_bound"] += 1
                        query_prevalidation["strict_candidate_query_final_bound_rejections"] += 1
                    else:
                        local_query_counters["intermediate_bound"] += 1
                        query_prevalidation["strict_candidate_query_internal_bound_rejections"] += 1
                    return None
                return value

            proposal, stats = propose_one_query(
                task,
                candidates,
                qrow["query_pool"],
                executor=cached_strict_executor,
                reserved_evaluation_inputs=reserved_inputs,
            )
            query_prevalidation["screened_sessions"] += 1
            query_prevalidation["per_arm"][arm]["screened"] += 1
            arm_stats["candidate_exec_rejections"] += stats["candidate_execution_rejections"]
            query_prevalidation["strict_candidate_query_execution_rejections"] += 0
            query_screen_results[key] = {
                "stats": stats,
                "proposal": None if proposal is None else {
                    "query_id": proposal.query_id,
                    "query_sha256": proposal.query_sha256,
                    "inputs": proposal.inputs,
                    "disagreement_count": proposal.disagreement_count,
                    "pairwise_disagreements": proposal.pairwise_disagreements,
                },
                "executor_counts": dict(local_query_counters),
            }
            if len(screens) == 0:
                query_prevalidation["screening_event_mismatches"].append({
                    "session": key, "issue": "missing_query_pool_screened_event"
                })
            else:
                expected_stats = stats
                for event in screens:
                    observed = {
                        k: v for k, v in event.items()
                        if k not in {"event", "seq", "task_id", "timestamp_utc"}
                    }
                    if observed != expected_stats:
                        query_prevalidation["screening_event_mismatches"].append({
                            "session": key, "seq": event["seq"],
                            "expected": expected_stats, "observed": observed
                        })
            if proposal is not None:
                query_prevalidation["proposals_recomputed"] += 1
                if not proposals_actual:
                    query_prevalidation["proposal_event_mismatches"].append({
                        "session": key, "issue": "proposal_missing_from_provenance"
                    })
                for event in proposals_actual:
                    if event["query_id"] != proposal.query_id or event["query_sha256"] != proposal.query_sha256:
                        query_prevalidation["proposal_event_mismatches"].append({
                            "session": key, "seq": event["seq"], "issue": "proposal_id_or_hash_mismatch"
                        })
            elif proposals_actual:
                query_prevalidation["proposal_event_mismatches"].append({
                    "session": key, "issue": "unexpected_proposal_in_provenance"
                })

        recomputed_queryable = proposal is not None
        if recomputed_queryable != bool(metrics["queryable"]):
            query_prevalidation["queryable_journal_mismatches"].append({
                "session": key, "recomputed": recomputed_queryable,
                "journal": bool(metrics["queryable"])
            })
        if not recomputed_queryable and not bool(metrics["fallback"]):
            # A no-query run with a non-empty portfolio must use its fallback.
            # A queryable run may also fall back after the oracle response; those
            # two journal flags are intentionally not mutually exclusive.
            query_prevalidation["queryable_journal_mismatches"].append({
                "session": key, "issue": "no-query session is missing its fallback flag",
                "journal_fallback": bool(metrics["fallback"]),
                "recomputed_queryable": recomputed_queryable,
            })


# 6) Provenance retry accounting, session-set checks, and final invariants.
event_counts = Counter(e["event"] for e in events)
unique_sessions = set(events_by_session)
expected_candidate_sessions = {
    f"{tid}-{arm}" for tid in EXPECTED_TASK_IDS for arm in ("v5_ablation", "v5_full")
    if journal[tid]["arms"][arm]["candidate_count"] > 0
}
expected_query_sessions = {
    f"{tid}-{arm}" for tid in EXPECTED_TASK_IDS for arm in ("v5_ablation", "v5_full")
    if journal[tid]["arms"][arm]["queryable"]
}
expected_fallback_sessions = {
    f"{tid}-{arm}" for tid in EXPECTED_TASK_IDS for arm in ("v5_ablation", "v5_full")
    if journal[tid]["arms"][arm]["fallback"]
}
actual_portfolio_sessions = {
    key for key, rows in events_by_session.items()
    if any(e["event"] == "portfolio_frozen" for e in rows)
}
actual_query_sessions = {
    key for key, rows in events_by_session.items()
    if any(e["event"] == "query_proposed" for e in rows)
}
actual_fallback_sessions = {
    key for key, rows in events_by_session.items()
    if any(e["event"] == "fallback_selected" for e in rows)
}
assert expected_candidate_sessions == actual_portfolio_sessions
assert expected_query_sessions == actual_query_sessions
assert expected_fallback_sessions == actual_fallback_sessions
assert not query_prevalidation["queryable_journal_mismatches"]
assert not query_prevalidation["screening_event_mismatches"]
assert not query_prevalidation["proposal_event_mismatches"]

duplicate_attempts = {}
for key, rows in events_by_session.items():
    counts = Counter(e["event"] for e in rows)
    if any(counts[event] > 1 for event in (
        "portfolio_frozen", "query_pool_screened", "query_proposed",
        "oracle_requested", "oracle_response", "candidate_selected",
        "fallback_selected", "no_query"
    )):
        duplicate_attempts[key] = dict(counts)
assert set(duplicate_attempts) == {
    "synth-200-0172-v5_ablation",
    "synth-200-0172-v5_full",
}

# Queryability and fallback are separate states: a query can be issued but
# still end in fallback when no oracle answer is usable or no candidate survives.
query_fallback_overlap = {}
for arm in ("v5_ablation", "v5_full"):
    arm_rows = [journal[tid]["arms"][arm] for tid in EXPECTED_TASK_IDS]
    query_fallback_overlap[arm] = {
        "queryable_and_fallback": sum(
            bool(row["queryable"]) and bool(row["fallback"]) for row in arm_rows
        ),
        "queryable_without_fallback": sum(
            bool(row["queryable"]) and not bool(row["fallback"]) for row in arm_rows
        ),
        "no_query_with_fallback": sum(
            not bool(row["queryable"]) and bool(row["fallback"]) for row in arm_rows
        ),
        "no_query_without_fallback": sum(
            not bool(row["queryable"]) and not bool(row["fallback"]) for row in arm_rows
        ),
    }

# Summarize eligible/ineligible task depth and portfolio/selection transitions.
depth_eligibility = defaultdict(Counter)
for tid in EXPECTED_TASK_IDS:
    eligible = journal[tid]["arms"]["v1_symbolic"]["eligible"]
    depth_key = "over4" if depth_by_task[tid] > 4 else "le4"
    depth_eligibility[depth_key]["eligible" if eligible else "ineligible"] += 1

# Candidate strict-bound totals and rates are reported separately for visible and
# reserved streams; these are execution observations, not new benchmark scores.
output = {
    "audit_status": "PASS",
    "scope": "read-only audit of frozen candidates, inputs, targets, task journal and append-only provenance; no synthesis, training, oracle adapter calls, rescoring or frozen artifact writes",
    "artifact_integrity": {
        "cohort_lock_sha256": sha_file(SOURCE / "cohort_lock.json"),
        "candidate_freeze_sha256": sha_file(SOURCE / "candidate_freeze.jsonl"),
        "query_eval_inputs_sha256": sha_file(SOURCE / "query_and_eval_inputs.jsonl"),
        "target_map_manifest_sha256": sha_file(SOURCE / "target_map_manifest.json"),
        "task_journal_sha256": journal_sha,
        "provenance_sha256": provenance_sha,
        "target_map_count": target_manifest["count"],
        "frozen_candidate_rows": len(frozen_rows),
        "query_eval_rows": len(query_rows),
        "candidate_family_hash_rows": candidate_family_hash_rows,
        "candidate_family_hash_mismatches": candidate_family_hash_mismatches,
        "task_rows": len(journal_rows),
        "target_pair_content_mismatches": 0,
    },
    "cohort_reconstruction": {
        "generation_attempts": attempts,
        "unique_fresh_families": len({t["program_family_hash"] for t in tasks}),
        "prior_family_overlap": len({t["program_family_hash"] for t in tasks} & old_families),
        "trace_crosschecks": trace_checks,
    },
    "target_depth": {
        "active_operator_histogram": dict(sorted(depth_hist.items())),
        "targets_over_search_depth_4": sum(v for k, v in depth_hist.items() if k > 4),
        "targets_over_search_depth_4_rate": sum(v for k, v in depth_hist.items() if k > 4) / 200,
        "depth_by_eligibility": {k: dict(v) for k, v in depth_eligibility.items()},
        "interpretation": "This is a 4-operation search evaluated against generated targets containing 2–6 active operations. A >4-operation target is not automatically unsolvable; report separately the frozen portfolio's strict behavioural matches."
    },
    "input_streams": stream_audit,
    "query_pool_cardinality": {
        "requested_max_per_task": cohort["query_pool_size"],
        "actual_length_histogram": dict(sorted(query_pool_length_histogram.items())),
        "tasks_below_requested_max": len(query_pool_short_task_ids),
        "task_ids_below_requested_max": query_pool_short_task_ids,
    },
    "target_valid_reserved_cases_histogram": dict(sorted(target_valid_distribution.items())),
    "strictness": strictness,
    "query_fallback_overlap": query_fallback_overlap,
    "query_prevalidation": query_prevalidation,
    "portfolio_depth_cross": {arm: {k: dict(v) for k, v in depths.items()} for arm, depths in portfolio_depth_cross.items()},
    "provenance": {
        "event_count": len(events),
        "event_type_counts": dict(event_counts),
        "unique_candidate_sessions": len(actual_portfolio_sessions),
        "unique_query_sessions": len(actual_query_sessions),
        "unique_fallback_sessions": len(actual_fallback_sessions),
        "duplicate_attempts": duplicate_attempts,
        "query_screening_and_proposal_reconciliation": "PASS",
    },
    "first_bound_examples": first_bound_examples,
}
# Ensure the audit output lives outside all frozen cohort/recovery directories.
output_path = AUDIT_DIR / "four_way_200_extended_read_only_audit.json"
output_path.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
print(json.dumps({
    "audit_status": output["audit_status"],
    "output_path": str(output_path),
    "target_depth": output["target_depth"],
    "input_streams": output["input_streams"],
    "strictness": strictness,
    "query_prevalidation": query_prevalidation,
    "provenance": output["provenance"],
    "artifact_integrity": output["artifact_integrity"],
}, indent=2, sort_keys=True), flush=True)
