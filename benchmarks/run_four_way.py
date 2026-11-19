"""Four-arm, 200-task fresh-family ESQ-DSL release benchmark."""

from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import random
import sys
import time
from pathlib import Path
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from esq_dsl import interpreter as core
from esq_dsl.features import encode_task
from esq_dsl.model import ESQSetEncoder
from esq_dsl.synthesizer import synthesize_priority
from esq_dsl.oracle import ProvenanceRecorder, generate_query_pool, run_one_shot_oracle
from oracle_adapter import SyntheticReferenceOracle
from families import (
    MAX_OPERATORS,
    MIN_OPERATORS,
    _draw_inputs,
    generate_synthetic_task_v3,
)
from benchmarks.provenance import capture_source_manifest, verify_source_manifest

SEED_BASE = 2026111700
SEED_STRIDE = 997
TASK_COUNT = 200
QUERY_COUNT = 100
EVAL_COUNT = 50
MAX_OPS = 4
MAX_SIGNATURES = 10000
SEARCH_TIMEOUT_S = 0.30
MIN_VALID_CASES = 25
PREFLIGHT_SAMPLE_SIZE = 50
PREFLIGHT_MIN_VALID_CASES = 25
PREFLIGHT_SEED_DOMAIN = "SYNTH-ESQ-V6-PREFLIGHT-v1"
# Future cohorts align target depth and search depth, and use runtime-authoritative
# intermediate bounds. Legacy frozen cohorts retain their recorded policies.
MAX_TARGET_OPS = MAX_OPS
STRICT_INTERMEDIATES = True
PRIOR_CORPUS_SHA256 = "2faa003d65827bebdcc4cb7f7c2fac9958b905e5db8143c708466d58bd26c958"
PRIOR_FAMILY_TEXT_SHA256 = (
    "a40167d2611c68b875cdfce0a503d07ff06180deecfc55726862323f72f8ec69"
)
PRIOR_FAMILY_BINARY_SHA256 = (
    "2564ab662e37a717d91019b4abc1b757f75df354899c8a0e40fcce0649049bee"
)
PRIOR_CORPUS_ROWS = 100000
PRIOR_FAMILY_COUNT = 54649
ARMS = ("v1_symbolic", "v3_guided", "v5_ablation", "v5_full")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def sha_file(path):
    return sha_bytes(Path(path).read_bytes())


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(canonical(row) + "\n" for row in rows), encoding="utf-8")
    return sha_file(path)


def load_prior_families(path):
    path = Path(path)
    digest = sha_file(path)
    if path.name.endswith(".jsonl.gz"):
        families = set()
        rows = 0
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                row = json.loads(line)
                family = row.get("program_family_hash")
                if not isinstance(family, str) or len(family) != 64:
                    raise ValueError("invalid prior family corpus")
                families.add(family)
                rows += 1
        if rows != PRIOR_CORPUS_ROWS:
            raise ValueError("prior corpus row count mismatch")
        expected_digest = PRIOR_CORPUS_SHA256
    elif path.name.endswith(".bin.gz"):
        with gzip.open(path, "rb") as stream:
            packed = stream.read()
        if len(packed) != PRIOR_FAMILY_COUNT * 32:
            raise ValueError("packed prior family archive has an invalid byte length")
        families = {
            packed[offset : offset + 32].hex() for offset in range(0, len(packed), 32)
        }
        expected_digest = PRIOR_FAMILY_BINARY_SHA256
    else:
        families = set()
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for line in stream:
                family = line.strip()
                if not family:
                    continue
                if len(family) != 64:
                    raise ValueError("invalid prior family hash")
                families.add(family)
        expected_digest = PRIOR_FAMILY_TEXT_SHA256
    if len(families) != PRIOR_FAMILY_COUNT:
        raise ValueError("prior unique-family count mismatch")
    if digest != expected_digest:
        raise ValueError("prior family exclusion input SHA-256 mismatch")
    return families, digest


def preflight_target_inputs(task):
    """Evaluate a target on a deterministic, model-independent disjoint sample."""
    visible_rows = [
        {name: values[index] for name, values in task["inputs"].items()}
        for index in range(len(task["outputs"]))
    ]
    seed_material = (
        f"{PREFLIGHT_SEED_DOMAIN}:{task['seed']}:{task['program_family_hash']}"
    )
    sample_seed = int(hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(sample_seed)
    excluded = {canonical(row) for row in visible_rows}
    inputs = []
    for _ in range(PREFLIGHT_SAMPLE_SIZE * 1000):
        row = _draw_inputs(rng, task["input_specs"])
        key = canonical(row)
        if key in excluded:
            continue
        excluded.add(key)
        inputs.append(row)
        if len(inputs) == PREFLIGHT_SAMPLE_SIZE:
            break

    valid_count = 0
    for row in inputs:
        try:
            value = core.execute_program(task["program"], row, strict=True)
        except (ArithmeticError, TypeError, ValueError, IndexError):
            value = None
        valid_count += int(value is not None)

    return {
        "seed": sample_seed,
        "inputs": inputs,
        "sample_count": len(inputs),
        "valid_count": valid_count,
        "input_sha256": hashlib.sha256(
            canonical(inputs).encode("utf-8")
        ).hexdigest(),
        "eligible": (
            len(inputs) == PREFLIGHT_SAMPLE_SIZE
            and valid_count >= PREFLIGHT_MIN_VALID_CASES
        ),
    }


def generate_cohort(
    old_families,
    task_count=TASK_COUNT,
    *,
    max_target_ops: int = MAX_OPERATORS,
    preflight_records=None,
):
    if not MIN_OPERATORS <= max_target_ops <= MAX_OPERATORS:
        raise ValueError("max_target_ops is outside the generator's supported bounds")
    if preflight_records is None:
        preflight_records = []
    tasks = []
    selected = set()
    attempt = 0
    while len(tasks) < task_count and attempt < 100000:
        try:
            task = generate_synthetic_task_v3(
                seed=SEED_BASE + attempt * SEED_STRIDE,
                task_index=attempt,
                max_ops=max_target_ops,
            )
        except RuntimeError:
            attempt += 1
            continue
        family = task["program_family_hash"]
        if family in old_families or family in selected:
            attempt += 1
            continue

        preflight = preflight_target_inputs(task)
        preflight_eligible = bool(preflight["eligible"])
        record = {
            "generation_attempt": attempt,
            "task_seed": task["seed"],
            "family_hash": family,
            "operator_count": task["operator_count"],
            "sample_seed": preflight["seed"],
            "sample_size": preflight["sample_count"],
            "valid_count": preflight["valid_count"],
            "input_sha256": preflight["input_sha256"],
            "preflight_eligible": preflight_eligible,
            "query_pool_count": 0,
            "reserved_evaluation_input_count": 0,
            "stream_feasible": False,
            "accepted": False,
            "rejection_reason": None,
        }
        if not preflight_eligible:
            record["rejection_reason"] = "target_preflight"
            preflight_records.append(record)
            attempt += 1
            continue

        cohort_index = len(tasks)
        task["task_id"] = f"synth-200-{cohort_index:04d}"
        task["generation_attempt"] = attempt
        task["preflight_inputs"] = preflight["inputs"]
        task["preflight_seed"] = preflight["seed"]
        task["preflight_valid_count"] = preflight["valid_count"]
        task["preflight_input_sha256"] = preflight["input_sha256"]

        streams = prepare_disjoint_input_streams(
            task, preflight["inputs"], index=cohort_index
        )
        record["query_pool_count"] = streams["query_pool_count"]
        record["reserved_evaluation_input_count"] = streams[
            "reserved_evaluation_input_count"
        ]
        record["stream_feasible"] = streams["rejection_reason"] is None
        if streams["rejection_reason"] is not None:
            record["rejection_reason"] = streams["rejection_reason"]
            preflight_records.append(record)
            attempt += 1
            continue

        task["query_pool"] = streams["query_pool"]
        task["reserved_evaluation_inputs"] = streams[
            "reserved_evaluation_inputs"
        ]
        record["task_id"] = task["task_id"]
        record["accepted"] = True
        preflight_records.append(record)
        tasks.append(task)
        selected.add(family)
        attempt += 1

    if len(tasks) != task_count:
        raise RuntimeError(
            f"unable to generate {task_count} unique unseen families with "
            "valid preflight and complete disjoint query/reserved input streams"
        )
    if selected & old_families:
        raise AssertionError("family overlap")
    return tasks, attempt


def visible_projection(task):
    return {
        key: task[key]
        for key in (
            "task_id",
            "inputs",
            "outputs",
            "input_specs",
            "input_types",
            "program_family_hash",
            "seed",
        )
    }


def reserve_inputs(task, query_pool, index, excluded_inputs=None):
    rng = random.Random(SEED_BASE + index * 13 + 11)
    visible = [
        {name: values[i] for name, values in task["inputs"].items()}
        for i in range(len(task["outputs"]))
    ]
    excluded = {canonical(row) for row in visible}
    excluded.update(canonical(row) for row in query_pool)
    excluded.update(canonical(row) for row in (excluded_inputs or ()))
    rows = []
    for _ in range(EVAL_COUNT * 200):
        row = _draw_inputs(rng, task["input_specs"])
        key = canonical(row)
        if key not in excluded:
            rows.append(row)
            excluded.add(key)
        if len(rows) == EVAL_COUNT:
            return rows
    raise RuntimeError("could not construct reserved fresh evaluation inputs")

def prepare_disjoint_input_streams(task, preflight_inputs, index):
    """Prepare full query and evaluation streams, rejecting candidates with finite-pool shortfalls."""
    visible = visible_projection(task)
    query_pool = generate_query_pool(
        visible,
        count=QUERY_COUNT,
        seed=SEED_BASE + index * 13 + 7,
        exclude_inputs=preflight_inputs,
    )
    result = {
        "query_pool": query_pool,
        "reserved_evaluation_inputs": [],
        "query_pool_count": len(query_pool),
        "reserved_evaluation_input_count": 0,
        "rejection_reason": None,
    }
    if len(query_pool) != QUERY_COUNT:
        result["rejection_reason"] = "query_pool_capacity"
        return result

    try:
        reserved_inputs = reserve_inputs(
            visible, query_pool, index, excluded_inputs=preflight_inputs
        )
    except RuntimeError as exc:
        if str(exc) != "could not construct reserved fresh evaluation inputs":
            raise
        result["rejection_reason"] = "reserved_evaluation_input_capacity"
        return result

    result["reserved_evaluation_inputs"] = reserved_inputs
    result["reserved_evaluation_input_count"] = len(reserved_inputs)
    if len(reserved_inputs) != EVAL_COUNT:
        result["rejection_reason"] = "reserved_evaluation_input_capacity"
        result["reserved_evaluation_inputs"] = []
        result["reserved_evaluation_input_count"] = 0
        return result

    visible_rows = [
        {name: values[i] for name, values in task["inputs"].items()}
        for i in range(len(task["outputs"]))
    ]
    stream_keys = [
        {canonical(row) for row in visible_rows},
        {canonical(row) for row in preflight_inputs},
        {canonical(row) for row in query_pool},
        {canonical(row) for row in reserved_inputs},
    ]
    if any(
        stream_keys[left] & stream_keys[right]
        for left in range(len(stream_keys))
        for right in range(left + 1, len(stream_keys))
    ):
        raise RuntimeError(
            f"V6 input streams overlap while preparing candidate {task['task_id']}"
        )
    return result


def load_model(checkpoint):
    # Share the inference loader's model-card checksum and restricted deserialization.
    from esq_dsl.neural_guide import NeuralGuide

    return NeuralGuide(checkpoint).model


def synthesize(task, arm, model):
    start = time.perf_counter()
    query_task = {
        "inputs": task["inputs"],
        "outputs": task["outputs"],
        "input_specs": task["input_specs"],
        "task_id": task["task_id"],
    }
    if arm == "v1_symbolic":
        result = core.synthesize(
            query_task,
            max_ops=MAX_OPS,
            max_signatures=MAX_SIGNATURES,
            timeout_s=SEARCH_TIMEOUT_S,
            strict_intermediates=STRICT_INTERMEDIATES,
        )
        return {
            "program": result.program,
            "candidates": [],
            "exact_fit": result.exact_fit,
            "visible_examples_matched": result.examples_matched,
            "search_elapsed_ms": result.elapsed_ms,
            "wall_ms": (time.perf_counter() - start) * 1000,
            "truncated": result.truncated,
        }
    operator_scores = lambda_scores = None
    if arm in ("v3_guided", "v5_full"):
        values, mask = encode_task(query_task)
        with torch.no_grad():
            operator_scores, lambda_scores, _ = model.predict_priors(
                torch.from_numpy(values[None]),
                torch.from_numpy(mask[None]),
            )
    top_k = 1 if arm == "v3_guided" else 3
    result = synthesize_priority(
        query_task,
        operator_scores=operator_scores,
        lambda_scores=lambda_scores,
        max_ops=MAX_OPS,
        max_signatures=MAX_SIGNATURES,
        timeout_s=SEARCH_TIMEOUT_S,
        top_k=top_k,
        strict_intermediates=STRICT_INTERMEDIATES,
    )
    candidates = [dict(row) for row in result.candidates if row.get("program")]
    return {
        "program": result.program,
        "candidates": candidates,
        "exact_fit": result.exact_fit,
        "visible_examples_matched": result.examples_matched,
        "search_elapsed_ms": result.elapsed_ms,
        "wall_ms": (time.perf_counter() - start) * 1000,
        "truncated": result.truncated,
    }


def evaluate(program, target, inputs):
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


def pctl(values, q):
    return float(np.percentile(np.asarray(values, dtype=float), q)) if values else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--prior-family-hashes", default="benchmarks/data/prior_family_hashes.bin.gz"
    )
    parser.add_argument("--checkpoint", default="checkpoints/esq_v3_converged.pt")
    parser.add_argument("--output-dir", default="benchmarks/results/four_way_200_v6")
    parser.add_argument("--task-count", type=int, default=TASK_COUNT)
    parser.add_argument(
        "--freeze-only",
        action="store_true",
        help="Freeze the V6 cohort and targets; score separately with score_frozen_four_way.py",
    )
    args = parser.parse_args()
    if args.task_count < 1 or args.task_count > TASK_COUNT:
        raise ValueError(f"task-count must be between 1 and {TASK_COUNT}")
    task_count = args.task_count
    out = Path(args.output_dir)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError("refusing to overwrite a frozen benchmark directory")
    out.mkdir(parents=True, exist_ok=True)

    checkpoint_path = Path(args.checkpoint)
    if not checkpoint_path.is_absolute():
        checkpoint_path = (ROOT / checkpoint_path).resolve()
    else:
        checkpoint_path = checkpoint_path.resolve()
    if not checkpoint_path.is_relative_to(ROOT):
        raise ValueError("V6 checkpoint must be stored inside the repository for provenance")
    checkpoint_sidecar = Path(str(checkpoint_path) + ".sha256")
    checkpoint_model_card = checkpoint_path.with_name("model_card.json")
    if not checkpoint_path.is_file():
        raise FileNotFoundError(checkpoint_path)
    if not checkpoint_sidecar.is_file() or not checkpoint_model_card.is_file():
        raise FileNotFoundError("checkpoint SHA-256 sidecar and adjacent model card are required")
    args.checkpoint = str(checkpoint_path)

    source_files = (
        "benchmarks/families.py",
        "benchmarks/run_four_way.py",
        "benchmarks/oracle_adapter.py",
        "benchmarks/score_frozen_four_way.py",
        "benchmarks/provenance.py",
        "esq_dsl/__init__.py",
        "esq_dsl/dsl.py",
        "esq_dsl/features.py",
        "esq_dsl/interpreter.py",
        "esq_dsl/model.py",
        "esq_dsl/neural_guide.py",
        "esq_dsl/oracle.py",
        "esq_dsl/synthesizer.py",
        "training/esq_data_v3.py",
        "training/esq_training_v3.py",
        "training/generate_dataset.py",
        checkpoint_path.relative_to(ROOT).as_posix(),
        checkpoint_sidecar.relative_to(ROOT).as_posix(),
        checkpoint_model_card.relative_to(ROOT).as_posix(),
        "pyproject.toml",
    )
    source_manifest = capture_source_manifest(ROOT, source_files)
    git_provenance = source_manifest.get("git", {})
    if not isinstance(git_provenance, dict) or not git_provenance.get("available"):
        raise RuntimeError("V6 requires an available Git working tree for source provenance")
    if not git_provenance.get("remote_url") or not git_provenance.get("commit_sha"):
        raise RuntimeError("V6 requires a Git origin URL and committed source revision")
    if git_provenance.get("dirty_worktree"):
        raise RuntimeError("V6 requires a clean Git working tree; commit or discard local changes")
    source_manifest_path = out / "source_manifest.json"
    source_manifest_path.write_text(
        json.dumps(source_manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    source_manifest_sha = sha_file(source_manifest_path)

    old, prior_sha = load_prior_families(args.prior_family_hashes)
    checkpoint_sha = sha_file(args.checkpoint)
    model = load_model(args.checkpoint)
    preflight_records = []
    tasks, attempts = generate_cohort(
        old, task_count, max_target_ops=MAX_TARGET_OPS,
        preflight_records=preflight_records,
    )
    preflight_rows = [
        {
            "task_id": task["task_id"],
            "sample_seed": task["preflight_seed"],
            "sample_size": PREFLIGHT_SAMPLE_SIZE,
            "valid_count": task["preflight_valid_count"],
            "input_sha256": task["preflight_input_sha256"],
            "inputs": task["preflight_inputs"],
        }
        for task in tasks
    ]
    preflight_inputs_sha = write_jsonl(out / "preflight_inputs.jsonl", preflight_rows)
    accepted_records = [row for row in preflight_records if row["accepted"]]
    rejected_records = [row for row in preflight_records if not row["accepted"]]
    preflight_report = {
        "schema_version": 1,
        "experiment": "SYNTH-ESQ-V6-FOUR-WAY-200",
        "policy": {
            "target_max_ops": MAX_TARGET_OPS,
            "strict_intermediates": True,
            "sample_size": PREFLIGHT_SAMPLE_SIZE,
            "minimum_valid_inputs": PREFLIGHT_MIN_VALID_CASES,
            "seed_domain": PREFLIGHT_SEED_DOMAIN,
            "query_pool_size": QUERY_COUNT,
            "reserved_evaluation_inputs_per_task": EVAL_COUNT,
            "require_full_unique_streams": True,
            "input_streams_disjoint_from": [
                "visible_examples", "preflight_inputs", "query_pool",
                "reserved_evaluation_inputs"
            ],
        },
        "accepted_task_count": len(tasks),
        "candidates_evaluated": len(preflight_records),
        "candidates_rejected": len(rejected_records),
        "rejection_counts": {
            "target_preflight": sum(
                row.get("rejection_reason") == "target_preflight"
                for row in rejected_records
            ),
            "query_pool_capacity": sum(
                row.get("rejection_reason") == "query_pool_capacity"
                for row in rejected_records
            ),
            "reserved_evaluation_input_capacity": sum(
                row.get("rejection_reason") == "reserved_evaluation_input_capacity"
                for row in rejected_records
            ),
        },
        "records": preflight_records,
    }
    (out / "preflight_report.json").write_text(
        json.dumps(preflight_report, indent=2, sort_keys=True), encoding="utf-8"
    )
    preflight_report_sha = sha_file(out / "preflight_report.json")
    visible = [visible_projection(task) for task in tasks]
    queries = [task["query_pool"] for task in tasks]
    reserved = [task["reserved_evaluation_inputs"] for task in tasks]
    for i, task in enumerate(visible):
        preflight_inputs = tasks[i]["preflight_inputs"]
        pool = queries[i]
        reserved_inputs = reserved[i]
        if len(pool) != QUERY_COUNT or len(reserved_inputs) != EVAL_COUNT:
            raise RuntimeError(
                f"V6 frozen input stream count mismatch for {task['task_id']}"
            )
        preflight_keys = {canonical(row) for row in preflight_inputs}
        visible_keys = {
            canonical({name: values[j] for name, values in task["inputs"].items()})
            for j in range(len(task["outputs"]))
        }
        query_keys = {canonical(row) for row in pool}
        reserved_keys = {canonical(row) for row in reserved_inputs}
        if (
            len(preflight_keys) != PREFLIGHT_SAMPLE_SIZE
            or len(query_keys) != QUERY_COUNT
            or len(reserved_keys) != EVAL_COUNT
            or preflight_keys & visible_keys
            or preflight_keys & query_keys
            or preflight_keys & reserved_keys
            or query_keys & visible_keys
            or query_keys & reserved_keys
            or reserved_keys & visible_keys
        ):
            raise RuntimeError(f"V6 input streams overlap or are incomplete for {task['task_id']}")
    # All arms are frozen on visible information before target maps are written.
    frozen = []
    for i, task in enumerate(visible):
        for arm in ARMS:
            result = synthesize(task, arm, model)
            frozen.append(
                {
                    "task_id": task["task_id"],
                    "family_hash": task["program_family_hash"],
                    "arm": arm,
                    **result,
                }
            )
        if (i + 1) % 25 == 0:
            print(f"VISIBLE_FREEZE {i + 1}/{task_count}", flush=True)
    candidate_sha = write_jsonl(out / "candidate_freeze.jsonl", frozen)
    query_sha = write_jsonl(
        out / "query_and_eval_inputs.jsonl",
        [
            {
                "task_id": task["task_id"],
                "query_pool": pool,
                "reserved_evaluation_inputs": evals,
            }
            for task, pool, evals in zip(visible, queries, reserved)
        ],
    )
    cohort = {
        "experiment": "SYNTH-ESQ-V6-FOUR-WAY-200",
        "protocol_version": 2,
        "target_depth_policy": "target active-operator cap equals search max_ops",
        "runtime_semantics_policy": "strict_intermediates=True and strict evaluation",
        "task_count": task_count,
        "unique_fresh_families": len({x["program_family_hash"] for x in tasks}),
        "family_overlap_count": len({x["program_family_hash"] for x in tasks} & old),
        "prior_family_exclusion_file_sha256": prior_sha,
        "prior_rows": PRIOR_CORPUS_ROWS,
        "prior_unique_families": len(old),
        "seed_base": SEED_BASE,
        "seed_stride": SEED_STRIDE,
        "generation_attempts_used": attempts,
        "query_pool_size": QUERY_COUNT,
        "reserved_evaluation_inputs_per_task": EVAL_COUNT,
        "target_preflight_rejections": sum(
            row.get("rejection_reason") == "target_preflight"
            for row in rejected_records
        ),
        "query_pool_capacity_rejections": sum(
            row.get("rejection_reason") == "query_pool_capacity"
            for row in rejected_records
        ),
        "reserved_evaluation_input_capacity_rejections": sum(
            row.get("rejection_reason") == "reserved_evaluation_input_capacity"
            for row in rejected_records
        ),
        "min_valid_cases": MIN_VALID_CASES,
        "preflight_sample_size": PREFLIGHT_SAMPLE_SIZE,
        "preflight_min_valid_cases": PREFLIGHT_MIN_VALID_CASES,
        "preflight_report_file": "preflight_report.json",
        "preflight_report_sha256": preflight_report_sha,
        "preflight_inputs_file": "preflight_inputs.jsonl",
        "preflight_inputs_sha256": preflight_inputs_sha,
        "preflight_candidates_evaluated": len(preflight_records),
        "preflight_candidates_rejected": len(rejected_records),
        "preflight_accepted_tasks": len(tasks),
        "checkpoint_sha256": checkpoint_sha,
        "candidate_freeze_sha256": candidate_sha,
        "query_eval_inputs_sha256": query_sha,
        "target_min_ops": MIN_OPERATORS,
        "target_max_ops": MAX_TARGET_OPS,
        "source_manifest_file": "source_manifest.json",
        "source_manifest_sha256": source_manifest_sha,
        "search": {
            "max_ops": MAX_OPS,
            "max_signatures": MAX_SIGNATURES,
            "timeout_s": SEARCH_TIMEOUT_S,
            "strict_intermediates": STRICT_INTERMEDIATES,
        },
        "visibility_gate": "all four candidate arms frozen before any target map is written",
    }
    source_mismatches = verify_source_manifest(ROOT, source_manifest)
    if source_mismatches:
        raise RuntimeError(
            "source files changed during benchmark execution: "
            + ", ".join(source_mismatches)
        )
    (out / "cohort_lock.json").write_text(
        json.dumps(cohort, indent=2), encoding="utf-8"
    )
    target_dir = out / "target_maps"
    target_dir.mkdir()
    targets = {task["task_id"]: task["program"] for task in tasks}
    target_manifest = {}
    for task_id, program in targets.items():
        for arm in ("v5_ablation", "v5_full"):
            oracle_task_id = f"{task_id}-{arm}"
            path = target_dir / f"{oracle_task_id}.json"
            path.write_text(
                json.dumps({oracle_task_id: program}, sort_keys=True),
                encoding="utf-8",
            )
            target_manifest[path.name] = sha_file(path)
    target_manifest_path = out / "target_map_manifest.json"
    target_manifest_path.write_text(
        json.dumps(
            {"count": len(target_manifest), "sha256_by_file": target_manifest}, indent=2
        ),
        encoding="utf-8",
    )
    if args.freeze_only:
        freeze_manifest = {
            "experiment": cohort["experiment"],
            "cohort_lock_sha256": sha_file(out / "cohort_lock.json"),
            "preflight_report_sha256": preflight_report_sha,
            "preflight_inputs_sha256": preflight_inputs_sha,
            "candidate_freeze_sha256": candidate_sha,
            "query_eval_inputs_sha256": query_sha,
            "target_map_manifest_sha256": sha_file(target_manifest_path),
            "target_map_count": len(target_manifest),
        }
        (out / "freeze_manifest.json").write_text(
            json.dumps(freeze_manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        print("FOUR_WAY_COHORT_FROZEN", flush=True)
        print(json.dumps(freeze_manifest, indent=2), flush=True)
        return 0

    provenance = ProvenanceRecorder(
        out / "oracle_provenance.jsonl",
        durable_events={"query_proposed"},
    )
    aggregates = {
        arm: {
            "visible_exact_fits": 0,
            "eligible": 0,
            "full_fresh_matches": 0,
            "correct": 0,
            "valid": 0,
            "candidate_sessions": 0,
            "queryable": 0,
            "fallback": 0,
            "runtime_ms": [],
        }
        for arm in ARMS
    }
    scored = []
    for i, (task, inputs, query_pool) in enumerate(zip(tasks, reserved, queries)):
        detail = {"task_id": task["task_id"], "arms": {}}
        for arm in ARMS:
            frozen_row = next(
                x for x in frozen if x["task_id"] == task["task_id"] and x["arm"] == arm
            )
            stats = aggregates[arm]
            stats["visible_exact_fits"] += int(frozen_row["exact_fit"])
            selected = frozen_row["program"]
            runtime = float(frozen_row["wall_ms"])
            queryable = fallback = False
            fallback_reason = None
            oracle_requests = 0
            oracle_wall_ms = 0.0
            if arm in ("v5_ablation", "v5_full") and frozen_row["candidates"]:
                stats["candidate_sessions"] += 1
                adapter = SyntheticReferenceOracle(
                    target_dir / f"{task['task_id']}-{arm}.json"
                )
                oracle_started = time.perf_counter()
                session = run_one_shot_oracle(
                    {
                        "task_id": f"{task['task_id']}-{arm}",
                        "inputs": task["inputs"],
                        "outputs": task["outputs"],
                        "input_specs": task["input_specs"],
                    },
                    frozen_row["candidates"],
                    query_pool,
                    adapter,
                    task_id=f"{task['task_id']}-{arm}",
                    reserved_evaluation_inputs=inputs,
                    recorder=provenance,
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
                stats["queryable"] += int(queryable)
                stats["fallback"] += int(fallback)
                runtime += oracle_wall_ms
            correct = valid = 0
            for fresh_input in inputs:
                expected, actual = evaluate(
                    selected, targets[task["task_id"]], fresh_input
                )
                if expected is None:
                    continue
                valid += 1
                correct += int(actual == expected)
            eligible = valid >= MIN_VALID_CASES
            if eligible:
                stats["eligible"] += 1
                stats["valid"] += valid
                stats["correct"] += correct
                stats["full_fresh_matches"] += int(correct == valid)
            stats["runtime_ms"].append(runtime)
            detail["arms"][arm] = {
                "visible_exact_fit": bool(frozen_row["exact_fit"]),
                "selected_program_sha256": (
                    sha_bytes(selected.encode()) if selected else None
                ),
                "candidate_count": len(frozen_row["candidates"]),
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
        scored.append(detail)
        if (i + 1) % 25 == 0:
            print(f"FRESH_SCORING {i + 1}/{task_count}", flush=True)
    results = {}
    for arm, stats in aggregates.items():
        results[arm] = {
            "visible_exact_fit_tasks": stats["visible_exact_fits"],
            "visible_exact_fit_rate": stats["visible_exact_fits"] / task_count,
            "eligible_tasks": stats["eligible"],
            "full_fresh_behaviour_matches": stats["full_fresh_matches"],
            "full_fresh_behaviour_match_rate": (
                stats["full_fresh_matches"] / stats["eligible"]
                if stats["eligible"]
                else None
            ),
            "fresh_case_correct": stats["correct"],
            "fresh_case_total": stats["valid"],
            "fresh_case_accuracy": (
                stats["correct"] / stats["valid"] if stats["valid"] else None
            ),
            "candidate_sessions": stats["candidate_sessions"],
            "queryable_sessions": stats["queryable"],
            "queryable_rate_per_task": (
                stats["queryable"] / task_count
                if arm in ("v5_ablation", "v5_full")
                else None
            ),
            "queryable_rate_per_candidate_session": (
                stats["queryable"] / stats["candidate_sessions"]
                if stats["candidate_sessions"]
                else None
            ),
            "fallback_sessions": stats["fallback"],
            "fallback_rate_per_task": (
                stats["fallback"] / task_count
                if arm in ("v5_ablation", "v5_full")
                else None
            ),
            "fallback_rate_per_candidate_session": (
                stats["fallback"] / stats["candidate_sessions"]
                if stats["candidate_sessions"]
                else None
            ),
            "runtime_p50_ms": pctl(stats["runtime_ms"], 50),
            "runtime_p95_ms": pctl(stats["runtime_ms"], 95),
        }
    results_sha = write_jsonl(out / "four_way_task_results.jsonl", scored)
    summary = {
        "experiment": cohort["experiment"],
        "task_count": task_count,
        "family_overlap_count": cohort["family_overlap_count"],
        "checkpoint_sha256": checkpoint_sha,
        "prior_family_hashes_sha256": prior_sha,
        "candidate_freeze_sha256": candidate_sha,
        "query_eval_inputs_sha256": query_sha,
        "task_results_sha256": results_sha,
        "arms": results,
        "claim_boundary": "fresh structural-family-held-out synthetic generator cohort with a local file-backed reference oracle; not an official ExeDec benchmark",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    artifact_manifest = {
        "summary": summary,
        "cohort_lock_sha256": sha_file(out / "cohort_lock.json"),
        "target_map_manifest_sha256": sha_file(out / "target_map_manifest.json"),
        "provenance_sha256": sha_file(out / "oracle_provenance.jsonl"),
        "files": {
            str(p.relative_to(out)): sha_file(p)
            for p in sorted(out.rglob("*"))
            if p.is_file()
        },
    }
    (out / "artifact_manifest.json").write_text(
        json.dumps(artifact_manifest, indent=2), encoding="utf-8"
    )
    print("FOUR_WAY_BENCHMARK_COMPLETE")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
