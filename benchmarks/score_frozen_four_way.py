"""Crash-resumable scoring for an already frozen four-arm Synth benchmark.

This consumes, but never modifies, the cohort, visible candidate freeze, query
pool, reserved inputs, and hidden target maps created by run_four_way.py. Each
completed task result is appended and fsynced before moving to the next task.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import uuid
from typing import Any, Iterable, Mapping

ARMS = ("v1_symbolic", "v3_guided", "v5_ablation", "v5_full")


def sha_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"{path}:{line_number}: record must be an object")
                rows.append(value)
    return rows


def load_durable_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Load completed records and truncate only a torn final append."""
    target = Path(path)
    if not target.exists():
        return []
    raw = target.read_bytes()
    if raw and not raw.endswith(b"\n"):
        last_newline = raw.rfind(b"\n")
        raw = raw[: last_newline + 1] if last_newline >= 0 else b""
        with target.open("r+b") as handle:
            handle.seek(0)
            handle.write(raw)
            handle.truncate()
            handle.flush()
            os.fsync(handle.fileno())
    rows = []
    for line_number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"{target}:{line_number}: record must be an object")
        rows.append(value)
    return rows


def append_durable_jsonl(path: str | Path, row: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(canonical(row) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def load_arm_results(
    path: str | Path, valid_task_ids: set[str]
) -> dict[tuple[str, str], dict[str, Any]]:
    """Load the append-only per-arm journal, rejecting ambiguous complete rows."""
    rows = load_durable_jsonl(path)
    results: dict[tuple[str, str], dict[str, Any]] = {}
    attempt_ids: set[str] = set()
    for line_number, row in enumerate(rows, 1):
        schema_version = row.get("schema_version")
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version != 1
        ):
            raise ValueError(
                f"arm journal row {line_number} has unsupported schema version"
            )
        task_id, arm = row.get("task_id"), row.get("arm")
        attempt_id, metrics = row.get("attempt_id"), row.get("metrics")
        if not isinstance(task_id, str) or task_id not in valid_task_ids:
            raise ValueError(f"arm journal contains unknown task id at row {line_number}: {task_id!r}")
        if arm not in ARMS:
            raise ValueError(f"arm journal contains unknown arm at row {line_number}: {arm!r}")
        if not isinstance(attempt_id, str) or not attempt_id.strip():
            raise ValueError(f"arm journal row {line_number} has no attempt_id")
        if attempt_id in attempt_ids:
            raise ValueError(f"duplicate arm attempt_id at row {line_number}")
        attempt_ids.add(attempt_id)
        if not isinstance(metrics, dict):
            raise ValueError(f"arm journal row {line_number} has no metrics object")
        key = (task_id, arm)
        if key in results:
            raise ValueError(f"duplicate arm result for {task_id}/{arm}")
        results[key] = row

    # A single writer scores tasks sequentially and arms in ARMS order. A
    # checkpoint may end part-way through one task, but it cannot skip tasks,
    # reorder arms, or continue to a later task after an incomplete group.
    task_positions = {
        task_id: index for index, task_id in enumerate(sorted(valid_task_ids))
    }
    current_task_id = None
    current_arms: list[str] = []
    previous_task_position = None
    for row in rows:
        task_id, arm = row["task_id"], row["arm"]
        if task_id != current_task_id:
            if current_task_id is not None:
                if len(current_arms) != len(ARMS):
                    raise ValueError(
                        f"incomplete arm group for {current_task_id} before next task"
                    )
                position = task_positions[task_id]
                if position != previous_task_position + 1:
                    raise ValueError("arm journal task groups are not contiguous")
            else:
                position = task_positions[task_id]
            current_task_id = task_id
            current_arms = []
            previous_task_position = position
        expected_arm = ARMS[len(current_arms)]
        if arm != expected_arm:
            raise ValueError(
                f"arm journal order mismatch for {task_id}: "
                f"expected {expected_arm}, got {arm}"
            )
        current_arms.append(arm)
    return results


def pending_arms(
    task_id: str, arm_results: Mapping[tuple[str, str], dict[str, Any]]
) -> list[str]:
    """Return arms not durably completed for a task, in the protocol's fixed order."""
    return [arm for arm in ARMS if (task_id, arm) not in arm_results]


def append_arm_result(
    path: str | Path,
    task_id: str,
    arm: str,
    metrics: dict[str, Any],
    *,
    attempt_id: str,
) -> None:
    if arm not in ARMS:
        raise ValueError(f"unknown arm: {arm}")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id must be a non-empty string")
    if not isinstance(attempt_id, str) or not attempt_id.strip():
        raise ValueError("attempt_id must be a non-empty string")
    if not isinstance(metrics, dict):
        raise ValueError("metrics must be an object")
    append_durable_jsonl(
        path,
        {
            "schema_version": 1,
            "task_id": task_id,
            "arm": arm,
            "attempt_id": attempt_id,
            "metrics": metrics,
        },
    )


def validate_arm_journal_follows_task_prefix(
    arm_results: Mapping[tuple[str, str], dict[str, Any]],
    task_ids: list[str],
    completed_task_ids: set[str],
) -> None:
    """Ensure arm checkpoints start at the next unfinished task, not a later one."""
    if task_ids != sorted(task_ids) or len(task_ids) != len(set(task_ids)):
        raise ValueError("frozen task IDs must be unique and ordered")
    if completed_task_ids != set(task_ids[: len(completed_task_ids)]):
        raise ValueError("completed task IDs are not an exact frozen-cohort prefix")
    positions = {task_id: index for index, task_id in enumerate(task_ids)}
    uncommitted_positions = sorted({
        positions[task_id]
        for task_id, _arm in arm_results
        if task_id not in completed_task_ids
    })
    next_position = len(completed_task_ids)
    for offset, position in enumerate(uncommitted_positions):
        if position != next_position + offset:
            expected = task_ids[next_position + offset] if next_position + offset < len(task_ids) else None
            actual = task_ids[position]
            raise ValueError(
                f"arm journal skips unfinished task: expected {expected}, got {actual}"
            )


def validate_arm_results_against_task_rows(
    arm_results: Mapping[tuple[str, str], dict[str, Any]],
    task_rows: list[dict[str, Any]],
) -> None:
    """Completed task rows, when backed by arm rows, must match all four exactly."""
    for task_row in task_rows:
        task_id = task_row.get("task_id")
        present = {
            arm for arm in ARMS if (task_id, arm) in arm_results
        }
        journal_version = task_row.get("arm_journal_version")
        if journal_version is not None and (
            isinstance(journal_version, bool) or journal_version != 1
        ):
            raise ValueError(
                f"completed task {task_id} has unsupported arm journal version "
                f"{journal_version!r}"
            )
        if not present:
            # Only unmarked legacy rows may predate per-arm checkpoints.
            if journal_version == 1:
                raise ValueError(
                    f"completed task {task_id} is missing its marked arm journal"
                )
            continue
        if present != set(ARMS):
            missing = sorted(set(ARMS) - present)
            raise ValueError(
                f"completed task {task_id} has an incomplete arm journal: {missing}"
            )
        journal_arms = task_row.get("arms", {})
        if set(journal_arms) != set(ARMS):
            raise ValueError(f"completed task {task_id} has incomplete task-row arms")
        attempt_ids = task_row.get("arm_attempt_ids")
        if journal_version == 1 and (
            not isinstance(attempt_ids, dict) or set(attempt_ids) != set(ARMS)
        ):
            raise ValueError(
                f"completed task {task_id} has incomplete arm attempt identifiers"
            )
        for arm in ARMS:
            arm_row = arm_results[(task_id, arm)]
            if arm_row["metrics"] != journal_arms[arm]:
                raise ValueError(
                    f"per-arm journal disagrees with task result: {task_id}/{arm}"
                )
            if journal_version == 1 and arm_row["attempt_id"] != attempt_ids[arm]:
                raise ValueError(
                    f"per-arm attempt identifier disagrees with task result: "
                    f"{task_id}/{arm}"
                )


def percentile(values: Iterable[float], q: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * q / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def aggregate_rows(rows: list[dict[str, Any]], task_count: int) -> dict[str, Any]:
    if task_count < 1:
        raise ValueError("task_count must be positive")
    if len(rows) != task_count:
        raise ValueError(f"expected {task_count} completed task rows, got {len(rows)}")
    results = {}
    for arm in ARMS:
        visible = eligible = full = correct = valid = 0
        sessions = queryable = fallback = 0
        runtimes = []
        for row in rows:
            metrics = row["arms"][arm]
            visible += int(bool(metrics["visible_exact_fit"]))
            eligible += int(bool(metrics["eligible"]))
            full += int(bool(metrics["full_fresh_behaviour_match"]))
            if bool(metrics["eligible"]):
                correct += int(metrics["fresh_case_correct"])
                valid += int(metrics["valid_fresh_cases"])
            runtimes.append(float(metrics["runtime_ms"]))
            if arm in ("v5_ablation", "v5_full") and int(metrics["candidate_count"]) > 0:
                sessions += 1
                queryable += int(bool(metrics["queryable"]))
                fallback += int(bool(metrics["fallback"]))
        results[arm] = {
            "visible_exact_fit_tasks": visible,
            "visible_exact_fit_rate": visible / task_count,
            "eligible_tasks": eligible,
            "full_fresh_behaviour_matches": full,
            "full_fresh_behaviour_match_rate": full / eligible if eligible else None,
            "fresh_case_correct": correct,
            "fresh_case_total": valid,
            "fresh_case_accuracy": correct / valid if valid else None,
            "candidate_sessions": sessions,
            "queryable_sessions": queryable,
            "queryable_rate_per_task": (
                queryable / task_count if arm in ("v5_ablation", "v5_full") else None
            ),
            "queryable_rate_per_candidate_session": queryable / sessions if sessions else None,
            "fallback_sessions": fallback,
            "fallback_rate_per_task": (
                fallback / task_count if arm in ("v5_ablation", "v5_full") else None
            ),
            "fallback_rate_per_candidate_session": fallback / sessions if sessions else None,
            "runtime_p50_ms": percentile(runtimes, 50),
            "runtime_p95_ms": percentile(runtimes, 95),
        }
    return results


def evaluate(program: str | None, target: str, inputs: dict[str, Any], core):
    try:
        expected = core.execute_program(target, inputs, strict=True)
    except Exception:
        return None, None
    if expected is None:
        return None, None
    try:
        actual = core.execute_program(program, inputs, strict=True) if program else None
    except Exception:
        actual = None
    return expected, actual


def verify_cohort_source_manifest(
    root: Path, source: Path, cohort: dict[str, Any]
) -> str | None:
    """Verify the locked source manifest and every declared source/environment digest.

    Cohorts predating source manifests remain explicitly legacy; no manifest is
    fabricated for them.
    """
    expected_sha = cohort.get("source_manifest_sha256")
    relative_name = cohort.get("source_manifest_file")
    if expected_sha is None and relative_name is None:
        return None
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        raise ValueError("cohort source manifest SHA-256 is missing or invalid")
    if not isinstance(relative_name, str) or not relative_name:
        raise ValueError("cohort source manifest path is missing or invalid")
    relative_path = Path(relative_name)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("cohort source manifest path must stay inside source directory")
    manifest_path = source / relative_path
    if not manifest_path.is_file() or sha_file(manifest_path) != expected_sha:
        raise ValueError("source manifest missing or SHA-256 differs from cohort lock")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    from benchmarks.provenance import verify_source_manifest

    mismatches = verify_source_manifest(root, manifest)
    if mismatches:
        raise ValueError(
            "locked source/runtime provenance mismatch: " + ", ".join(mismatches)
        )
    return expected_sha


def _verify_frozen_inputs(source: Path, cohort: dict[str, Any]):
    root = Path(__file__).resolve().parents[1]
    verify_cohort_source_manifest(root, source, cohort)
    candidate_path = source / "candidate_freeze.jsonl"
    query_path = source / "query_and_eval_inputs.jsonl"
    target_manifest_path = source / "target_map_manifest.json"
    if cohort.get("experiment") == "SYNTH-ESQ-V6-FOUR-WAY-200":
        for file_key, digest_key in (
            ("preflight_report_file", "preflight_report_sha256"),
            ("preflight_inputs_file", "preflight_inputs_sha256"),
        ):
            relative = Path(str(cohort.get(file_key, "")))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("V6 preflight artifact paths must stay inside source directory")
            preflight_file = source / relative
            if not preflight_file.is_file() or sha_file(preflight_file) != cohort.get(digest_key):
                raise ValueError(f"V6 preflight artifact missing or digest mismatch: {file_key}")
    if sha_file(candidate_path) != cohort["candidate_freeze_sha256"]:
        raise ValueError("candidate freeze SHA-256 does not match cohort lock")
    if sha_file(query_path) != cohort["query_eval_inputs_sha256"]:
        raise ValueError("query/evaluation input SHA-256 does not match cohort lock")
    target_manifest = json.loads(target_manifest_path.read_text(encoding="utf-8"))
    if int(target_manifest.get("count", -1)) != cohort["task_count"] * 2:
        raise ValueError("target-map manifest count does not match task count")
    actual_names = set()
    for name, expected_sha in target_manifest.get("sha256_by_file", {}).items():
        path = source / "target_maps" / name
        if not path.is_file() or sha_file(path) != expected_sha:
            raise ValueError(f"target map missing or digest mismatch: {name}")
        actual_names.add(name)
    expected_names = {
        f"{task_id}-{arm}.json"
        for task_id in (f"synth-200-{i:04d}" for i in range(cohort["task_count"]))
        for arm in ("v5_ablation", "v5_full")
    }
    if actual_names != expected_names:
        raise ValueError("target-map manifest has missing or unexpected names")
    return candidate_path, query_path, target_manifest_path


def _canonical_input(row: dict[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _verify_preflight_artifacts(
    source: Path,
    cohort: dict[str, Any],
    tasks: list[dict[str, Any]],
    query_by_task: dict[str, dict[str, Any]],
    core,
) -> None:
    """Verify the model-independent preflight gate and all disjoint input streams."""
    if cohort.get("experiment") != "SYNTH-ESQ-V6-FOUR-WAY-200":
        return
    search_policy = cohort.get("search")
    if (
        cohort.get("target_max_ops") != 4
        or not isinstance(search_policy, dict)
        or search_policy.get("max_ops") != 4
        or search_policy.get("strict_intermediates") is not True
    ):
        raise ValueError("V6 cohort lock must enforce strict-semantics depth 4")
    sample_size = int(cohort.get("preflight_sample_size", 0))
    minimum = int(cohort.get("preflight_min_valid_cases", 0))
    query_pool_size = int(cohort.get("query_pool_size", 0))
    reserved_input_count = int(cohort.get("reserved_evaluation_inputs_per_task", 0))
    if sample_size != 50 or minimum != 25:
        raise ValueError("V6 preflight policy must be exactly 25 valid inputs out of 50")
    if query_pool_size != 100 or reserved_input_count != 50:
        raise ValueError("V6 requires exactly 100 query inputs and 50 reserved evaluation inputs per task")
    report_path = source / str(cohort.get("preflight_report_file", ""))
    inputs_path = source / str(cohort.get("preflight_inputs_file", ""))
    if (
        not report_path.is_file()
        or sha_file(report_path) != cohort.get("preflight_report_sha256")
    ):
        raise ValueError("V6 preflight report is missing or its digest differs")
    if (
        not inputs_path.is_file()
        or sha_file(inputs_path) != cohort.get("preflight_inputs_sha256")
    ):
        raise ValueError("V6 preflight input stream is missing or its digest differs")

    report = json.loads(report_path.read_text(encoding="utf-8"))
    policy = report.get("policy", {})
    if (
        report.get("schema_version") != 1
        or policy.get("target_max_ops") != 4
        or policy.get("strict_intermediates") is not True
        or policy.get("sample_size") != 50
        or policy.get("minimum_valid_inputs") != 25
        or policy.get("query_pool_size") != query_pool_size
        or policy.get("reserved_evaluation_inputs_per_task") != reserved_input_count
        or policy.get("require_full_unique_streams") is not True
    ):
        raise ValueError("V6 preflight report has an incompatible policy")
    records = report.get("records")
    if not isinstance(records, list):
        raise ValueError("V6 preflight report has no records")
    accepted = [row for row in records if row.get("accepted") is True]
    rejected = [row for row in records if row.get("accepted") is False]
    rejection_counts = report.get("rejection_counts", {})
    actual_rejections = {
        "target_preflight": sum(
            row.get("rejection_reason") == "target_preflight" for row in rejected
        ),
        "query_pool_capacity": sum(
            row.get("rejection_reason") == "query_pool_capacity" for row in rejected
        ),
        "reserved_evaluation_input_capacity": sum(
            row.get("rejection_reason") == "reserved_evaluation_input_capacity"
            for row in rejected
        ),
    }
    if (
        len(accepted) != int(cohort.get("preflight_accepted_tasks", -1))
        or len(rejected) != int(cohort.get("preflight_candidates_rejected", -1))
        or len(records) != int(cohort.get("preflight_candidates_evaluated", -1))
        or len(tasks) != len(accepted)
        or rejection_counts != actual_rejections
        or actual_rejections["target_preflight"] != int(
            cohort.get("target_preflight_rejections", -1)
        )
        or actual_rejections["query_pool_capacity"] != int(
            cohort.get("query_pool_capacity_rejections", -1)
        )
        or actual_rejections["reserved_evaluation_input_capacity"] != int(
            cohort.get("reserved_evaluation_input_capacity_rejections", -1)
        )
    ):
        raise ValueError("V6 preflight report attrition counts disagree with cohort lock")

    rows = load_jsonl(inputs_path)
    if len(rows) != len(tasks):
        raise ValueError("V6 preflight input row count differs from accepted cohort")
    by_task = {row.get("task_id"): row for row in rows}
    accepted_by_task = {row.get("task_id"): row for row in accepted}
    expected_ids = [task["task_id"] for task in tasks]
    if (
        len(by_task) != len(rows)
        or set(by_task) != set(expected_ids)
        or set(accepted_by_task) != set(expected_ids)
    ):
        raise ValueError("V6 preflight task IDs do not match the frozen cohort")

    for task in tasks:
        task_id = task["task_id"]
        preflight_row = by_task[task_id]
        record = accepted_by_task[task_id]
        samples = preflight_row.get("inputs")
        if not isinstance(samples, list) or len(samples) != sample_size:
            raise ValueError(f"V6 preflight sample count mismatch: {task_id}")
        sample_keys = {_canonical_input(row) for row in samples}
        sample_sha = hashlib.sha256(
            json.dumps(samples, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        if (
            len(sample_keys) != sample_size
            or sample_sha != preflight_row.get("input_sha256")
            or sample_sha != record.get("input_sha256")
            or samples != task.get("preflight_inputs")
            or preflight_row.get("sample_seed") != task.get("preflight_seed")
        ):
            raise ValueError(f"V6 preflight sample provenance mismatch: {task_id}")

        visible = [
            {name: values[index] for name, values in task["inputs"].items()}
            for index in range(len(task["outputs"]))
        ]
        if (
            record.get("preflight_eligible") is not True
            or record.get("stream_feasible") is not True
            or record.get("query_pool_count") != query_pool_size
            or record.get("reserved_evaluation_input_count") != reserved_input_count
        ):
            raise ValueError(f"V6 accepted candidate does not satisfy full input-stream gates: {task_id}")
        query_row = query_by_task[task_id]
        query_pool = query_row.get("query_pool", [])
        reserved = query_row.get("reserved_evaluation_inputs", [])
        if (
            not isinstance(query_pool, list)
            or len(query_pool) != query_pool_size
            or not isinstance(reserved, list)
            or len(reserved) != reserved_input_count
        ):
            raise ValueError(f"V6 query/reserved input count mismatch: {task_id}")
        visible_keys = {_canonical_input(row) for row in visible}
        query_keys = {_canonical_input(row) for row in query_pool}
        reserved_keys = {_canonical_input(row) for row in reserved}
        if len(query_keys) != query_pool_size or len(reserved_keys) != reserved_input_count:
            raise ValueError(f"V6 query/reserved streams contain duplicate inputs: {task_id}")
        if (
            sample_keys & visible_keys
            or sample_keys & query_keys
            or sample_keys & reserved_keys
            or query_keys & visible_keys
            or query_keys & reserved_keys
            or reserved_keys & visible_keys
        ):
            raise ValueError(f"V6 visible/query/preflight/reserved streams overlap: {task_id}")
        valid_count = 0
        for sample in samples:
            try:
                output = core.execute_program(task["program"], sample, strict=True)
            except Exception:
                output = None
            valid_count += int(output is not None)
        if (
            valid_count != int(preflight_row.get("valid_count", -1))
            or valid_count != int(record.get("valid_count", -1))
            or valid_count < minimum
            or valid_count != int(task.get("preflight_valid_count", -1))
        ):
            raise ValueError(f"V6 strict target-validity preflight mismatch: {task_id}")



def rebuild_summary_artifacts(source: Path, output: Path, cohort: dict[str, Any]) -> dict[str, Any]:
    """Rebuild aggregate artifacts from a complete durable journal without rescoring."""
    task_count = int(cohort["task_count"])
    if not output.is_dir():
        raise FileNotFoundError(output)
    _verify_frozen_inputs(source, cohort)
    results_path = output / "four_way_task_results.jsonl"
    rows = load_durable_jsonl(results_path)
    expected_ids = [f"synth-200-{index:04d}" for index in range(task_count)]
    actual_ids = [row.get("task_id") for row in rows]
    if actual_ids != expected_ids:
        raise ValueError("durable journal must contain the exact ordered frozen cohort")
    arm_results_path = output / "four_way_arm_results.jsonl"
    arm_results = load_arm_results(arm_results_path, set(expected_ids))
    validate_arm_results_against_task_rows(arm_results, rows)
    for row in rows:
        if set(row.get("arms", {})) != set(ARMS):
            raise ValueError(f"incomplete arm results for {row.get('task_id')}")
        task_valid_counts = set()
        for arm in ARMS:
            metrics = row["arms"][arm]
            valid = int(metrics["valid_fresh_cases"])
            correct = int(metrics["fresh_case_correct"])
            if valid < 0 or valid > int(cohort["reserved_evaluation_inputs_per_task"]):
                raise ValueError(f"invalid fresh-case denominator: {row['task_id']}/{arm}")
            if correct < 0 or correct > valid:
                raise ValueError(f"invalid fresh-case numerator: {row['task_id']}/{arm}")
            task_valid_counts.add(valid)
            eligible = valid >= int(cohort.get("min_valid_cases", 25))
            if bool(metrics["eligible"]) != eligible:
                raise ValueError(f"eligibility flag disagrees with valid-case threshold: {row['task_id']}/{arm}")
            expected_full = eligible and correct == valid
            if bool(metrics["full_fresh_behaviour_match"]) != expected_full:
                raise ValueError(f"full-match flag disagrees with per-task counts: {row['task_id']}/{arm}")
        if len(task_valid_counts) != 1:
            raise ValueError(f"target-valid case counts differ across arms: {row['task_id']}")

    results_sha = sha_file(results_path)
    summary = {
        "experiment": cohort["experiment"],
        "task_count": task_count,
        "family_overlap_count": cohort["family_overlap_count"],
        "checkpoint_sha256": cohort["checkpoint_sha256"],
        "prior_family_hashes_sha256": cohort["prior_family_exclusion_file_sha256"],
        "candidate_freeze_sha256": cohort["candidate_freeze_sha256"],
        "query_eval_inputs_sha256": cohort["query_eval_inputs_sha256"],
        "source_manifest_sha256": cohort.get("source_manifest_sha256"),
        "task_results_sha256": results_sha,
        "arms": aggregate_rows(rows, task_count),
        "claim_boundary": "fresh structural-family-held-out synthetic generator cohort with a local file-backed reference oracle; not an official ExeDec benchmark",
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    progress = {
        "experiment": cohort["experiment"],
        "task_count": task_count,
        "completed_task_count": len(rows),
        "remaining_task_count": 0,
        "completed_arm_count": task_count * len(ARMS),
        "remaining_arm_count": 0,
        "arm_results_sha256": (
            sha_file(arm_results_path) if arm_results_path.is_file() else None
        ),
        "task_results_sha256": results_sha,
        "status": "complete",
    }
    (output / "progress.json").write_text(json.dumps(progress, indent=2), encoding="utf-8")
    provenance_path = output / "oracle_provenance.jsonl"
    manifest = {
        "summary": summary,
        "cohort_lock_sha256": sha_file(source / "cohort_lock.json"),
        "target_map_manifest_sha256": sha_file(source / "target_map_manifest.json"),
        "candidate_freeze_sha256": sha_file(source / "candidate_freeze.jsonl"),
        "query_eval_inputs_sha256": sha_file(source / "query_and_eval_inputs.jsonl"),
        "source_manifest_sha256": cohort.get("source_manifest_sha256"),
        "provenance_sha256": sha_file(provenance_path) if provenance_path.exists() else None,
        "files": {
            str(path.relative_to(output)): sha_file(path)
            for path in sorted(output.rglob("*"))
            if path.is_file() and path.name != "artifact_manifest.json"
        },
    }
    (output / "artifact_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return summary

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", required=True, help="Existing frozen four_way_200 directory")
    parser.add_argument("--output-dir", required=True, help="Separate durable scoring output directory")
    parser.add_argument("--prior-family-hashes", required=True)
    parser.add_argument("--max-new-tasks", type=int, default=40)
    parser.add_argument("--checkpoint", default="checkpoints/esq_v3_converged.pt")
    parser.add_argument("--rebuild-summary-only", action="store_true", help="Rebuild summary and manifest from a complete durable journal without scoring tasks")
    args = parser.parse_args()
    if args.max_new_tasks < 1:
        raise ValueError("--max-new-tasks must be positive")

    root = Path(__file__).resolve().parents[1]
    benchmark_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(benchmark_dir))

    from esq_dsl import interpreter as core
    from esq_dsl.oracle import ProvenanceRecorder, run_one_shot_oracle
    from oracle_adapter import SyntheticReferenceOracle
    from families import MAX_OPERATORS
    from run_four_way import generate_cohort, load_prior_families

    source = Path(args.source_dir).resolve()
    output = Path(args.output_dir).resolve()
    if source == output or source in output.parents or output in source.parents:
        raise ValueError("source and output directories must be separate and non-nested")
    if not source.is_dir():
        raise FileNotFoundError(source)
    output.mkdir(parents=True, exist_ok=True)

    cohort = json.loads((source / "cohort_lock.json").read_text(encoding="utf-8"))
    source_manifest_sha = cohort.get("source_manifest_sha256")
    task_count = int(cohort["task_count"])
    if task_count < 1 or task_count > 200:
        raise ValueError("frozen cohort task_count must be between 1 and 200")
    if args.rebuild_summary_only:
        summary = rebuild_summary_artifacts(source, output, cohort)
        print("FOUR_WAY_SUMMARY_REBUILT_FROM_DURABLE_JOURNAL", flush=True)
        print(json.dumps(summary, indent=2), flush=True)
        return 0
    candidate_path, query_path, target_manifest_path = _verify_frozen_inputs(source, cohort)

    # Reconstruct the deterministic visible task specifications and verify every
    # withheld target map against the generated reference program. No new targets
    # are generated or written.
    prior_families, prior_sha = load_prior_families(args.prior_family_hashes)
    if prior_sha != cohort["prior_family_exclusion_file_sha256"]:
        raise ValueError("prior family exclusion digest differs from frozen cohort")
    target_max_ops = int(cohort.get("target_max_ops", MAX_OPERATORS))
    tasks, attempts = generate_cohort(
        prior_families, task_count, max_target_ops=target_max_ops
    )
    if attempts != cohort["generation_attempts_used"]:
        raise ValueError("deterministic cohort generation attempt count differs")
    if len({task["program_family_hash"] for task in tasks}) != task_count:
        raise ValueError("reconstructed cohort contains duplicate structural families")
    for index, task in enumerate(tasks):
        if task["task_id"] != f"synth-200-{index:04d}":
            raise ValueError("reconstructed task order differs from cohort lock")

    candidates = load_jsonl(candidate_path)
    candidate_by_task: dict[str, dict[str, dict[str, Any]]] = {}
    for record in candidates:
        task_id, arm = record.get("task_id"), record.get("arm")
        if arm not in ARMS or not isinstance(task_id, str):
            raise ValueError("invalid candidate-freeze row")
        bucket = candidate_by_task.setdefault(task_id, {})
        if arm in bucket:
            raise ValueError(f"duplicate candidate-freeze arm: {task_id}/{arm}")
        bucket[arm] = record
    query_rows = load_jsonl(query_path)
    if len(query_rows) != task_count:
        raise ValueError("query/evaluation input row count differs from cohort")
    query_by_task = {row["task_id"]: row for row in query_rows}
    if len(query_by_task) != task_count:
        raise ValueError("duplicate task ids in query/evaluation inputs")
    _verify_preflight_artifacts(source, cohort, tasks, query_by_task, core)

    target_programs = {};
    for task in tasks:
        task_id = task["task_id"]
        target_path = source / "target_maps" / f"{task_id}-v5_full.json"
        target_payload = json.loads(target_path.read_text(encoding="utf-8"))
        target_program = target_payload.get(f"{task_id}-v5_full")
        if target_program != task["program"]:
            raise ValueError(f"frozen target map does not match deterministic task: {task_id}")
        target_programs[task_id] = target_program
        if task_id not in candidate_by_task or set(candidate_by_task[task_id]) != set(ARMS):
            raise ValueError(f"candidate freeze is incomplete for {task_id}")
        if task_id not in query_by_task:
            raise ValueError(f"query/evaluation input missing for {task_id}")
        if query_by_task[task_id].get("task_id") != task_id:
            raise ValueError(f"query/evaluation input task mismatch for {task_id}")

    results_path = output / "four_way_task_results.jsonl"
    prior_rows = load_durable_jsonl(results_path)
    prior_ids = [row.get("task_id") for row in prior_rows]
    expected_prior_prefix = [
        f"synth-200-{index:04d}" for index in range(len(prior_rows))
    ]
    completed = set(prior_ids)
    valid_ids = {task["task_id"] for task in tasks}
    if (
        len(prior_rows) > task_count
        or prior_ids != expected_prior_prefix
        or not completed.issubset(valid_ids)
        or len(completed) != len(prior_rows)
    ):
        raise ValueError(
            "existing scoring journal must be a unique ordered prefix of the frozen cohort"
        )
    arm_results_path = output / "four_way_arm_results.jsonl"
    arm_results = load_arm_results(arm_results_path, valid_ids)
    validate_arm_results_against_task_rows(arm_results, prior_rows)
    ordered_task_ids = [task["task_id"] for task in tasks]
    validate_arm_journal_follows_task_prefix(
        arm_results, ordered_task_ids, set(completed)
    )
    recorder = ProvenanceRecorder(
        output / "oracle_provenance.jsonl",
        durable_events={"query_proposed", "oracle_requested", "oracle_response"},
    )

    processed = 0
    for task in tasks:
        task_id = task["task_id"]
        if task_id in completed:
            continue
        if processed >= args.max_new_tasks:
            break
        visible_task = {
            "task_id": task_id,
            "inputs": task["inputs"],
            "outputs": task["outputs"],
            "input_specs": task["input_specs"],
        }
        input_record = query_by_task[task_id]
        reserved = input_record["reserved_evaluation_inputs"]
        query_pool = input_record["query_pool"]
        detail = {
            "task_id": task_id,
            "arm_journal_version": 1,
            "arm_attempt_ids": {},
            "arms": {},
        }
        for arm in ARMS:
            arm_key = (task_id, arm)
            if arm_key in arm_results:
                # A previous process already completed and fsynced this arm.
                # Reuse it without repeating synthesis, oracle calls or scoring.
                detail["arms"][arm] = arm_results[arm_key]["metrics"]
                detail["arm_attempt_ids"][arm] = arm_results[arm_key]["attempt_id"]
                continue

            attempt_id = uuid.uuid4().hex
            frozen = candidate_by_task[task_id][arm]
            selected = frozen.get("program")
            runtime = float(frozen["wall_ms"])
            queryable = fallback = False
            fallback_reason = None
            oracle_requests = 0
            oracle_wall_ms = 0.0
            candidate_rows = frozen.get("candidates") or []
            if arm in ("v5_ablation", "v5_full") and candidate_rows:
                adapter = SyntheticReferenceOracle(
                    source / "target_maps" / f"{task_id}-{arm}.json"
                )
                oracle_started = time.perf_counter()
                session = run_one_shot_oracle(
                    visible_task,
                    candidate_rows,
                    query_pool,
                    adapter,
                    task_id=f"{task_id}-{arm}",
                    attempt_id=attempt_id,
                    reserved_evaluation_inputs=reserved,
                    recorder=recorder,
                )
                selected = (
                    session.selected_candidate.program
                    if session.selected_candidate
                    else None
                )
                queryable = session.query is not None
                fallback = session.fallback_candidate is not None
                fallback_reason = session.fallback_reason
                oracle_wall_ms = (time.perf_counter() - oracle_started) * 1000.0
                oracle_requests = session.as_dict()["oracle_requests"]
                runtime += oracle_wall_ms

            correct = valid = 0
            for fresh_input in reserved:
                expected, actual = evaluate(
                    selected, target_programs[task_id], fresh_input, core
                )
                if expected is None:
                    continue
                valid += 1
                correct += int(actual == expected)
            eligible = valid >= int(cohort.get("min_valid_cases", 25))
            arm_metrics = {
                "visible_exact_fit": bool(frozen["exact_fit"]),
                "selected_program_sha256": (
                    hashlib.sha256(selected.encode("utf-8")).hexdigest()
                    if selected else None
                ),
                "candidate_count": len(candidate_rows),
                "valid_fresh_cases": valid,
                "fresh_case_correct": correct,
                "eligible": eligible,
                "full_fresh_behaviour_match": bool(eligible and correct == valid),
                "queryable": queryable,
                "fallback": fallback,
                "fallback_reason": fallback_reason,
                "oracle_requests": oracle_requests,
                "oracle_wall_ms": round(oracle_wall_ms, 3),
                "runtime_ms": round(runtime, 3),
            }
            append_arm_result(
                arm_results_path,
                task_id,
                arm,
                arm_metrics,
                attempt_id=attempt_id,
            )
            arm_results[arm_key] = {
                "schema_version": 1,
                "task_id": task_id,
                "arm": arm,
                "attempt_id": attempt_id,
                "metrics": arm_metrics,
            }
            detail["arm_attempt_ids"][arm] = attempt_id
            detail["arms"][arm] = arm_metrics
        append_durable_jsonl(results_path, detail)
        completed.add(task_id)
        processed += 1
        if len(completed) % 10 == 0 or len(completed) == task_count:
            print(f"DURABLE_SCORING {len(completed)}/{task_count}", flush=True)

    all_rows = load_durable_jsonl(results_path)
    final_task_ids = {row.get("task_id") for row in all_rows}
    completed_arm_count = sum(
        len(ARMS) if task_id in final_task_ids
        else len(ARMS) - len(pending_arms(task_id, arm_results))
        for task_id in valid_ids
    )
    progress = {
        "experiment": cohort["experiment"],
        "task_count": task_count,
        "completed_task_count": len(all_rows),
        "remaining_task_count": task_count - len(all_rows),
        "completed_arm_count": completed_arm_count,
        "remaining_arm_count": task_count * len(ARMS) - completed_arm_count,
        "arm_results_sha256": (
            sha_file(arm_results_path) if arm_results_path.is_file() else None
        ),
        "task_results_sha256": sha_file(results_path) if results_path.exists() else None,
        "status": "complete" if len(all_rows) == task_count else "partial",
    }
    (output / "progress.json").write_text(json.dumps(progress, indent=2), encoding="utf-8")

    if len(all_rows) == task_count:
        if {row["task_id"] for row in all_rows} != valid_ids:
            raise ValueError("scoring journal does not contain the exact frozen cohort")
        summary = {
            "experiment": cohort["experiment"],
            "task_count": task_count,
            "family_overlap_count": cohort["family_overlap_count"],
            "checkpoint_sha256": cohort["checkpoint_sha256"],
            "prior_family_hashes_sha256": prior_sha,
            "candidate_freeze_sha256": cohort["candidate_freeze_sha256"],
            "query_eval_inputs_sha256": cohort["query_eval_inputs_sha256"],
            "source_manifest_sha256": source_manifest_sha,
            "task_results_sha256": sha_file(results_path),
            "arms": aggregate_rows(all_rows, task_count),
            "claim_boundary": "fresh structural-family-held-out synthetic generator cohort with a local file-backed reference oracle; not an official ExeDec benchmark",
        }
        (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        manifest = {
            "summary": summary,
            "cohort_lock_sha256": sha_file(source / "cohort_lock.json"),
            "target_map_manifest_sha256": sha_file(target_manifest_path),
            "candidate_freeze_sha256": sha_file(candidate_path),
            "query_eval_inputs_sha256": sha_file(query_path),
            "source_manifest_sha256": source_manifest_sha,
            "provenance_sha256": (
                sha_file(output / "oracle_provenance.jsonl")
                if (output / "oracle_provenance.jsonl").exists() else None
            ),
            "files": {
                str(path.relative_to(output)): sha_file(path)
                for path in sorted(output.rglob("*"))
                if path.is_file() and path.name != "artifact_manifest.json"
            },
        }
        (output / "artifact_manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        print("FOUR_WAY_RECOVERY_COMPLETE", flush=True)
        print(json.dumps(summary, indent=2), flush=True)
    else:
        print(json.dumps(progress, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
