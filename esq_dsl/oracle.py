"""One-shot external oracle integration for the verified ESQ-DSL v3 baseline.

A session is deliberately bounded: freeze -> validate/select one query -> one
oracle request -> select a verified survivor or restore the pre-query best.
There is no iterative CEGIS loop and no automatic oracle retry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import uuid
from typing import Any, Callable, Mapping, Protocol, Sequence


class OracleStatus(str, Enum):
    ANSWERED = "answered"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"
    INVALID = "invalid"
    ERROR = "error"


@dataclass(frozen=True)
class OracleRequest:
    query_id: str
    task_id: str
    inputs: dict[str, Any]
    expected_type: str
    # Stable across retries of the same frozen query/portfolio.
    idempotency_key: str | None = None


@dataclass(frozen=True)
class OracleResponse:
    status: OracleStatus
    value: Any = None
    detail: str | None = None


class Oracle(Protocol):
    """One request/one response oracle boundary."""

    adapter_name: str

    def ask(self, request: OracleRequest) -> OracleResponse: ...


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_object(value: Any) -> str:
    return _sha256_text(_canonical_json(value))


def _value_type(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return "int"
    if isinstance(value, list) and all(
        isinstance(item, int) and not isinstance(item, bool) for item in value
    ):
        return "list"
    return None


def _valid_bounded_value(
    value: Any,
    *,
    expected_type: str | None = None,
    bound: int = 50,
    max_list_length: int = 50,
) -> bool:
    value_type = _value_type(value)
    if value_type is None or (
        expected_type is not None and value_type != expected_type
    ):
        return False
    if value_type == "int":
        return -bound <= value <= bound
    return len(value) <= max_list_length and all(
        -bound <= item <= bound for item in value
    )


def _validate_query_inputs(
    task: Mapping[str, Any],
    inputs: Any,
    *,
    input_bound: int,
    max_list_length: int,
) -> tuple[bool, str | None]:
    if not isinstance(inputs, Mapping):
        return False, "query_inputs_not_mapping"
    visible = task.get("inputs")
    if not isinstance(visible, Mapping) or not visible:
        return False, "task_inputs_missing"
    if set(inputs.keys()) != set(visible.keys()):
        return False, "query_variable_set_mismatch"

    specs = task.get("input_specs") or {}
    if not isinstance(specs, Mapping):
        return False, "input_specs_not_mapping"

    for name, value in inputs.items():
        examples = visible.get(name)
        if not isinstance(examples, list) or not examples:
            return False, f"missing_visible_type:{name}"
        expected_type = _value_type(examples[0])
        if expected_type is None or not _valid_bounded_value(
            value,
            expected_type=expected_type,
            bound=input_bound,
            max_list_length=max_list_length,
        ):
            return False, f"invalid_type_or_bounds:{name}"

        spec = specs.get(name)
        if spec is None:
            continue
        if not isinstance(spec, Mapping):
            return False, f"invalid_input_spec:{name}"
        value_range = spec.get("range")
        if (
            not isinstance(value_range, (list, tuple))
            or len(value_range) != 2
            or any(not isinstance(x, int) or isinstance(x, bool) for x in value_range)
            or value_range[0] > value_range[1]
        ):
            return False, f"invalid_range_spec:{name}"
        values = [value] if expected_type == "int" else value
        if any(item < value_range[0] or item > value_range[1] for item in values):
            return False, f"outside_task_range:{name}"

        length_range = spec.get("length")
        if expected_type == "int":
            if length_range is not None:
                return False, f"scalar_has_length_spec:{name}"
        else:
            if (
                not isinstance(length_range, (list, tuple))
                or len(length_range) != 2
                or any(
                    not isinstance(x, int) or isinstance(x, bool) for x in length_range
                )
                or length_range[0] < 0
                or length_range[0] > length_range[1]
            ):
                return False, f"invalid_length_spec:{name}"
            if not length_range[0] <= len(value) <= length_range[1]:
                return False, f"outside_task_length:{name}"
    return True, None


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    program: str
    program_sha256: str
    exact_fit: bool = True
    priority_score: float = 0.0
    cost: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "program_sha256": self.program_sha256,
            "exact_fit": self.exact_fit,
            "priority_score": self.priority_score,
            "cost": self.cost,
        }


def _normalise_candidates(rows: Sequence[Any]) -> tuple[Candidate, ...]:
    output: list[Candidate] = []
    seen_programs: set[str] = set()
    seen_ids: set[str] = set()
    for row in rows:
        if isinstance(row, str):
            program = row
            exact_fit = True
            score = 0.0
            cost = 0
        elif isinstance(row, Mapping):
            program = row.get("program")
            exact_fit = bool(row.get("exact_fit", True))
            score = float(row.get("priority_score", 0.0))
            cost = int(row.get("cost", 0))
        else:
            continue
        if not isinstance(program, str) or not program.strip():
            continue
        if program in seen_programs:
            continue
        if not math.isfinite(score):
            raise ValueError("candidate priority_score must be finite")
        digest = _sha256_text(program)
        candidate_id = (
            str(row.get("candidate_id") or digest[:16])
            if isinstance(row, Mapping)
            else digest[:16]
        )
        if candidate_id in seen_ids:
            candidate_id = digest[:16]
        if candidate_id in seen_ids:
            candidate_id = f"{digest[:16]}-{len(output)}"
        output.append(Candidate(candidate_id, program, digest, exact_fit, score, cost))
        seen_programs.add(program)
        seen_ids.add(candidate_id)
    return tuple(output)


def _load_v3_core():
    from . import interpreter

    return interpreter


def execute_with_v3_interpreter(program: str, inputs: Mapping[str, Any]) -> Any:
    """Execute a candidate with the exact v3 shared interpreter and strict bounds."""
    core = _load_v3_core()
    return _load_v3_core().execute_program(program, dict(inputs), strict=True)


@dataclass(frozen=True)
class QueryProposal:
    query_id: str
    inputs: dict[str, Any]
    query_sha256: str
    query_pool_sha256: str
    selection_rationale: str
    disagreement_count: int
    pairwise_disagreements: int
    predictions: dict[str, Any]


def propose_one_query(
    task: Mapping[str, Any],
    candidates: Sequence[Candidate],
    query_pool: Sequence[Mapping[str, Any]],
    *,
    executor: Callable[[str, Mapping[str, Any]], Any] = execute_with_v3_interpreter,
    reserved_evaluation_inputs: Sequence[Mapping[str, Any]] = (),
    input_bound: int = 50,
    output_bound: int = 50,
    max_list_length: int = 50,
) -> tuple[QueryProposal | None, dict[str, Any]]:
    """Select one deterministic, fully pre-validated disagreement query.

    This function has no Oracle argument and therefore cannot observe an oracle
    response. Every candidate must execute cleanly on a proposed input.
    """
    query_pool_rows = list(query_pool)
    try:
        query_pool_sha256 = _sha256_object(query_pool_rows)
    except (TypeError, ValueError):
        query_pool_sha256 = _sha256_text(
            f"unserializable-query-pool:{len(query_pool_rows)}"
        )
    stats: dict[str, Any] = {
        "pool_size": len(query_pool_rows),
        "query_pool_sha256": query_pool_sha256,
        "invalid_inputs": 0,
        "candidate_execution_rejections": 0,
        "non_disagreements": 0,
        "excluded_visible_or_reserved": 0,
        "invalid_task_projection": 0,
    }
    if len(candidates) < 2 or any(not item.exact_fit for item in candidates):
        return None, stats

    outputs = task.get("outputs")
    visible = task.get("inputs")
    if (
        not isinstance(outputs, list)
        or not outputs
        or not isinstance(visible, Mapping)
        or not visible
    ):
        stats["invalid_task_projection"] = 1
        return None, stats
    expected_type = _value_type(outputs[0])
    if expected_type is None or any(
        _value_type(value) != expected_type
        or not _valid_bounded_value(
            value,
            expected_type=expected_type,
            bound=output_bound,
            max_list_length=max_list_length,
        )
        for value in outputs
    ):
        stats["invalid_task_projection"] = 1
        return None, stats
    row_count = len(outputs)
    for name, values in visible.items():
        if not isinstance(values, list) or len(values) != row_count or not values:
            stats["invalid_task_projection"] = 1
            return None, stats
        visible_type = _value_type(values[0])
        if visible_type is None or any(
            _value_type(value) != visible_type
            or not _valid_bounded_value(
                value,
                expected_type=visible_type,
                bound=input_bound,
                max_list_length=max_list_length,
            )
            for value in values
        ):
            stats["invalid_task_projection"] = 1
            return None, stats

    excluded = set()
    for index in range(row_count):
        row = {name: values[index] for name, values in visible.items()}
        excluded.add(_canonical_json(row))
    for row in reserved_evaluation_inputs:
        if isinstance(row, Mapping):
            excluded.add(_canonical_json(dict(row)))

    portfolio_sha = _sha256_object([item.as_dict() for item in candidates])
    proposals: list[QueryProposal] = []
    seen_inputs: set[str] = set()

    for raw_inputs in query_pool_rows:
        try:
            key = _canonical_json(raw_inputs)
        except (TypeError, ValueError):
            stats["invalid_inputs"] += 1
            continue
        if key in seen_inputs:
            continue
        seen_inputs.add(key)
        if key in excluded:
            stats["excluded_visible_or_reserved"] += 1
            continue

        valid, _reason = _validate_query_inputs(
            task,
            raw_inputs,
            input_bound=input_bound,
            max_list_length=max_list_length,
        )
        if not valid:
            stats["invalid_inputs"] += 1
            continue

        predictions: dict[str, Any] = {}
        candidate_failed = False
        for candidate in candidates:
            try:
                prediction = executor(candidate.program, raw_inputs)
            except Exception:
                candidate_failed = True
                break
            if not _valid_bounded_value(
                prediction,
                expected_type=expected_type,
                bound=output_bound,
                max_list_length=max_list_length,
            ):
                candidate_failed = True
                break
            predictions[candidate.candidate_id] = prediction
        if candidate_failed:
            stats["candidate_execution_rejections"] += 1
            continue

        distinct = {_canonical_json(value) for value in predictions.values()}
        disagreement_count = len(distinct)
        if disagreement_count < 2:
            stats["non_disagreements"] += 1
            continue

        prediction_values = list(predictions.values())
        pairwise = sum(
            prediction_values[left] != prediction_values[right]
            for left in range(len(prediction_values))
            for right in range(left + 1, len(prediction_values))
        )
        query_sha = _sha256_text(key)
        query_id = _sha256_text(
            f"{task.get('task_id', 'task')}:{query_sha}:{portfolio_sha}"
        )[:24]
        proposals.append(
            QueryProposal(
                query_id=query_id,
                inputs=dict(raw_inputs),
                query_sha256=query_sha,
                query_pool_sha256=query_pool_sha256,
                selection_rationale="max_distinct_predictions_then_pairwise_disagreement_then_query_sha256",
                disagreement_count=disagreement_count,
                pairwise_disagreements=pairwise,
                predictions=predictions,
            )
        )

    if not proposals:
        return None, stats
    proposals.sort(
        key=lambda proposal: (
            -proposal.disagreement_count,
            -proposal.pairwise_disagreements,
            proposal.query_sha256,
        )
    )
    return proposals[0], stats


def generate_query_pool(
    task: Mapping[str, Any],
    *,
    count: int = 100,
    seed: int = 20261116,
    input_bound: int = 50,
    max_list_length: int = 50,
    exclude_inputs: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Generate conservative queries matching visible value and list-length profiles.

    Query bounds are tighter than the DSL's hard [-50, 50] execution bound.
    Per-variable ranges are anchored to visible examples and constrained by the
    task's input_specs. propose_one_query still executes every candidate on each
    proposed input before the one-shot Oracle boundary.
    """
    if count < 1:
        raise ValueError("count must be >= 1")
    visible = task.get("inputs")
    if not isinstance(visible, Mapping) or not visible:
        raise ValueError("task inputs are required")
    specs = task.get("input_specs") or {}
    if not isinstance(specs, Mapping):
        raise ValueError("input_specs must be a mapping")
    safe_bound = min(40, max(1, int(input_bound)))
    rng_seed = int(_sha256_text(f"{seed}:{task.get('task_id', '')}")[:16], 16)
    rng = random.Random(rng_seed)

    def spec_range(name: str) -> tuple[int, int]:
        spec = specs.get(name, {})
        raw = spec.get("range") if isinstance(spec, Mapping) else None
        if (
            isinstance(raw, (list, tuple))
            and len(raw) == 2
            and all(isinstance(x, int) and not isinstance(x, bool) for x in raw)
            and raw[0] <= raw[1]
        ):
            return int(raw[0]), int(raw[1])
        return -10, 10

    def value_bounds(name: str, examples: list[Any]) -> tuple[int, int] | None:
        observed: list[int] = []
        for value in examples:
            if isinstance(value, int) and not isinstance(value, bool):
                observed.append(value)
            elif isinstance(value, list):
                observed.extend(
                    item
                    for item in value
                    if isinstance(item, int) and not isinstance(item, bool)
                )
        spec_low, spec_high = spec_range(name)
        spec_low, spec_high = max(spec_low, -safe_bound), min(spec_high, safe_bound)
        if spec_low > spec_high:
            return None
        if observed:
            observed = [min(safe_bound, max(-safe_bound, value)) for value in observed]
            low_seen, high_seen = min(observed), max(observed)
            padding = max(1, min(4, math.ceil((high_seen - low_seen) * 0.15)))
            low = max(spec_low, low_seen - padding)
            high = min(spec_high, high_seen + padding)
        else:
            low, high = spec_low, spec_high
        if low > high:
            center = (
                min(spec_high, max(spec_low, (low_seen + high_seen) // 2))
                if observed
                else spec_low
            )
            low = high = center
        return int(low), int(high)

    list_length_choices: dict[str, tuple[int, ...]] = {}
    bounds_by_name: dict[str, tuple[int, int]] = {}
    types: dict[str, str] = {}
    for name, examples in visible.items():
        if not isinstance(examples, list) or not examples:
            raise ValueError(f"visible examples missing for {name}")
        kind = _value_type(examples[0])
        if kind is None or any(_value_type(value) != kind for value in examples):
            raise ValueError(f"visible values have inconsistent type for {name}")
        types[name] = kind
        bounds = value_bounds(name, examples)
        if bounds is None:
            return []
        bounds_by_name[name] = bounds
        if kind == "list":
            observed_lengths = [len(value) for value in examples]
            nearby = {
                candidate
                for length in observed_lengths
                for candidate in (length - 1, length, length + 1)
                if 0 <= candidate <= max_list_length
            }
            spec = specs.get(name, {})
            length_range = spec.get("length") if isinstance(spec, Mapping) else None
            if (
                isinstance(length_range, (list, tuple))
                and len(length_range) == 2
                and all(
                    isinstance(x, int) and not isinstance(x, bool) for x in length_range
                )
                and 0 <= length_range[0] <= length_range[1]
            ):
                nearby = {
                    length
                    for length in nearby
                    if length_range[0] <= length <= length_range[1]
                }
            if not nearby:
                return []
            list_length_choices[name] = tuple(sorted(nearby))

    pool: list[dict[str, Any]] = []
    # Visible demonstrations are not useful active-query candidates: the
    # proposal selector must exclude them in any case, so exclude them while
    # sampling rather than letting them consume the finite query-pool budget.
    visible_rows = [
        {name: values[index] for name, values in visible.items()}
        for index in range(len(next(iter(visible.values()))))
    ]
    seen: set[str] = {_canonical_json(row) for row in visible_rows}
    for excluded_row in exclude_inputs or ():
        if not isinstance(excluded_row, Mapping):
            raise ValueError("exclude_inputs entries must be mappings")
        seen.add(_canonical_json(dict(excluded_row)))
    attempts = 0
    while len(pool) < count and attempts < count * 100:
        attempts += 1
        row: dict[str, Any] = {}
        for name, kind in types.items():
            low, high = bounds_by_name[name]
            if kind == "int":
                row[name] = rng.randint(low, high)
            else:
                observed_lengths = [len(value) for value in visible[name]]
                # Most queries preserve observed lengths; others vary by at most one.
                length = (
                    rng.choice(observed_lengths)
                    if rng.random() < 0.70
                    else rng.choice(list(list_length_choices[name]))
                )
                row[name] = [rng.randint(low, high) for _ in range(length)]
        key = _canonical_json(row)
        if key not in seen:
            seen.add(key)
            pool.append(row)
    return pool


class HumanCLIOracle:
    """Read exactly one human response; malformed input is returned as INVALID."""

    adapter_name = "human_cli"

    def __init__(self, input_fn: Callable[[str], str] = input):
        self._input = input_fn

    def ask(self, request: OracleRequest) -> OracleResponse:
        prompt = (
            f"Oracle query {request.query_id} [idempotency key "
            f"{request.idempotency_key or request.query_id}]: "
            f"{json.dumps(request.inputs, sort_keys=True)}. "
            f"Enter {request.expected_type} JSON, or 'skip'/'unknown': "
        )
        try:
            raw = self._input(prompt)
        except (EOFError, KeyboardInterrupt):
            return OracleResponse(OracleStatus.SKIPPED, detail="stdin_eof_or_interrupt")
        if not isinstance(raw, str):
            return OracleResponse(OracleStatus.INVALID, detail="response_not_text")
        token = raw.strip().lower()
        if token in {"skip", "unknown"}:
            return OracleResponse(OracleStatus.SKIPPED, detail=token)
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return OracleResponse(OracleStatus.INVALID, detail="malformed_json")
        return OracleResponse(OracleStatus.ANSWERED, value=value)


class SubprocessOracle:
    """One-shot JSON-lines-style subprocess adapter with shell disabled and timeout."""

    adapter_name = "subprocess"

    def __init__(
        self,
        command: Sequence[str],
        *,
        timeout_s: float = 2.0,
        cwd: str | Path | None = None,
        max_output_bytes: int = 8192,
    ):
        if not isinstance(command, (list, tuple)) or not command:
            raise ValueError("command must be a non-empty argument sequence")
        if any(not isinstance(part, str) or not part for part in command):
            raise ValueError("every command argument must be a non-empty string")
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout_s must be finite and > 0")
        if max_output_bytes < 1:
            raise ValueError("max_output_bytes must be >= 1")
        self.command = tuple(command)
        self.timeout_s = timeout_s
        self.cwd = str(cwd) if cwd is not None else None
        self.max_output_bytes = max_output_bytes

    def ask(self, request: OracleRequest) -> OracleResponse:
        payload = {
            "protocol": "esq-oracle-v1",
            "query_id": request.query_id,
            "task_id": request.task_id,
            "inputs": request.inputs,
            "expected_type": request.expected_type,
            "idempotency_key": request.idempotency_key,
        }
        try:
            completed = subprocess.run(
                self.command,
                input=_canonical_json(payload),
                text=True,
                capture_output=True,
                timeout=self.timeout_s,
                cwd=self.cwd,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return OracleResponse(OracleStatus.TIMED_OUT, detail="subprocess_timeout")
        except (OSError, ValueError) as error:
            return OracleResponse(OracleStatus.ERROR, detail=str(error)[:500])

        if (
            len(completed.stdout.encode("utf-8", errors="replace"))
            > self.max_output_bytes
        ):
            return OracleResponse(OracleStatus.INVALID, detail="stdout_too_large")
        if completed.returncode != 0:
            detail = (
                completed.stderr.strip()[:500] or f"exit_code:{completed.returncode}"
            )
            return OracleResponse(OracleStatus.ERROR, detail=detail)
        try:
            payload_out = json.loads(completed.stdout)
        except (json.JSONDecodeError, TypeError):
            return OracleResponse(
                OracleStatus.INVALID, detail="malformed_subprocess_json"
            )
        if not isinstance(payload_out, Mapping):
            return OracleResponse(
                OracleStatus.INVALID, detail="subprocess_response_not_object"
            )

        status = str(payload_out.get("status", "")).strip().lower()
        if status in {"skip", "skipped", "unknown"}:
            detail = payload_out.get("detail", status)
            return OracleResponse(OracleStatus.SKIPPED, detail=str(detail)[:500])
        if status in {"timeout", "timed_out"}:
            detail = payload_out.get("detail", status)
            return OracleResponse(OracleStatus.TIMED_OUT, detail=str(detail)[:500])
        if status == "error":
            return OracleResponse(
                OracleStatus.ERROR,
                detail=str(payload_out.get("detail", "harness_error"))[:500],
            )
        if status != "answered" or "value" not in payload_out:
            return OracleResponse(
                OracleStatus.INVALID, detail="invalid_subprocess_response_shape"
            )
        return OracleResponse(OracleStatus.ANSWERED, value=payload_out["value"])


class ProvenanceRecorder:
    """Append ordered provenance events with optional event-specific fsync."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        durable_events: Sequence[str] | None = None,
    ):
        self.path = Path(path) if path is not None else None
        self.durable_events = (
            None if durable_events is None else frozenset(durable_events)
        )
        self.events: list[dict[str, Any]] = []
        self._seq = 0
        if self.path is not None and self.path.exists():
            raw = self.path.read_bytes()
            if raw and not raw.endswith(b"\n"):
                # An unterminated final record was never committed as a complete
                # JSONL event. Remove only that tail; never hide corruption inside
                # a newline-terminated record.
                last_newline = raw.rfind(b"\n")
                committed = raw[: last_newline + 1] if last_newline >= 0 else b""
                with self.path.open("r+b") as handle:
                    handle.seek(0)
                    handle.write(committed)
                    handle.truncate()
                    handle.flush()
                    os.fsync(handle.fileno())
                raw = committed

            expected_seq = 0
            for line_number, line in enumerate(raw.splitlines(), 1):
                if not line.strip():
                    continue
                record = json.loads(line.decode("utf-8"))
                if not isinstance(record, dict):
                    raise ValueError(
                        f"{self.path}:{line_number}: provenance event must be an object"
                    )
                sequence = record.get("seq")
                if isinstance(sequence, bool) or not isinstance(sequence, int):
                    raise ValueError(
                        f"{self.path}:{line_number}: provenance seq must be an integer"
                    )
                if sequence != expected_seq:
                    raise ValueError(
                        f"{self.path}:{line_number}: expected provenance seq "
                        f"{expected_seq}, got {sequence}"
                    )
                self.events.append(record)
                expected_seq += 1
            self._seq = expected_seq

    def emit(self, event: str, **details: Any) -> dict[str, Any]:
        record = {
            "seq": self._seq,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **details,
        }
        line = _canonical_json(record) + "\n"
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                if self.durable_events is None or event in self.durable_events:
                    handle.flush()
                    os.fsync(handle.fileno())
        self.events.append(record)
        self._seq += 1
        return record


@dataclass(frozen=True)
class OneShotResult:
    status: str
    query: QueryProposal | None
    selected_candidate: Candidate | None
    fallback_candidate: Candidate | None
    survivors: tuple[Candidate, ...]
    fallback_reason: str | None
    provenance: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "query": (
                {
                    "query_id": self.query.query_id,
                    "inputs": self.query.inputs,
                    "query_sha256": self.query.query_sha256,
                    "query_pool_sha256": self.query.query_pool_sha256,
                    "selection_rationale": self.query.selection_rationale,
                    "disagreement_count": self.query.disagreement_count,
                    "pairwise_disagreements": self.query.pairwise_disagreements,
                }
                if self.query
                else None
            ),
            "selected_candidate": (
                self.selected_candidate.as_dict()
                | {"program": self.selected_candidate.program}
                if self.selected_candidate
                else None
            ),
            "fallback_candidate": (
                self.fallback_candidate.as_dict()
                | {"program": self.fallback_candidate.program}
                if self.fallback_candidate
                else None
            ),
            "survivor_ids": [candidate.candidate_id for candidate in self.survivors],
            "fallback_reason": self.fallback_reason,
            "oracle_requests": sum(
                row["event"] == "oracle_requested" for row in self.provenance
            ),
        }


def run_one_shot_oracle(
    task: Mapping[str, Any],
    candidate_rows: Sequence[Any],
    query_pool: Sequence[Mapping[str, Any]],
    oracle: Oracle,
    *,
    task_id: str | None = None,
    attempt_id: str | None = None,
    executor: Callable[[str, Mapping[str, Any]], Any] = execute_with_v3_interpreter,
    reserved_evaluation_inputs: Sequence[Mapping[str, Any]] = (),
    recorder: ProvenanceRecorder | None = None,
    input_bound: int = 50,
    output_bound: int = 50,
    max_list_length: int = 50,
) -> OneShotResult:
    """Execute a single query transaction; this function never starts a second round."""
    task_key = str(task_id if task_id is not None else task.get("task_id", "task"))
    # The default is durable: a proposal is fsynced before the adapter is called.
    # Callers can inject an in-memory recorder explicitly for isolated tests.
    default_provenance_path = (
        Path("artifacts")
        / "esq_oracle_provenance"
        / f"{_sha256_text(task_key)[:24]}.jsonl"
    )
    log = (
        recorder
        if recorder is not None
        else ProvenanceRecorder(default_provenance_path)
    )
    attempt_key = uuid.uuid4().hex if attempt_id is None else attempt_id
    if not isinstance(attempt_key, str) or not attempt_key.strip():
        raise ValueError("attempt_id must be a non-empty string")

    def emit(event: str, **details: Any) -> dict[str, Any]:
        return log.emit(event, attempt_id=attempt_key, **details)

    session_event_start = len(log.events)
    frozen = _normalise_candidates(candidate_rows)
    fallback = frozen[0] if frozen else None
    portfolio_sha = _sha256_object([candidate.as_dict() for candidate in frozen])
    emit(
        "portfolio_frozen",
        task_id=task_key,
        candidate_count=len(frozen),
        candidate_ids=[candidate.candidate_id for candidate in frozen],
        candidate_program_sha256=[candidate.program_sha256 for candidate in frozen],
        portfolio_sha256=portfolio_sha,
    )

    def finish(
        status: str,
        *,
        query: QueryProposal | None = None,
        selected: Candidate | None = None,
        survivors: Sequence[Candidate] = (),
        reason: str | None = None,
        fallback_candidate: Candidate | None = None,
    ) -> OneShotResult:
        return OneShotResult(
            status,
            query,
            selected,
            fallback_candidate,
            tuple(survivors),
            reason,
            tuple(log.events[session_event_start:]),
        )

    if not frozen:
        emit(
            "no_candidate_fallback", task_id=task_key, reason="empty_prequery_pool"
        )
        return finish("no_candidates", reason="empty_prequery_pool")
    if len(frozen) < 2 or any(not candidate.exact_fit for candidate in frozen):
        emit(
            "no_query", task_id=task_key, reason="candidate_pool_not_disambiguable"
        )
        emit(
            "fallback_selected",
            task_id=task_key,
            candidate_id=fallback.candidate_id,
            reason="candidate_pool_not_disambiguable",
            original_portfolio_sha256=portfolio_sha,
            original_candidate_ids=[candidate.candidate_id for candidate in frozen],
        )
        return finish(
            "no_valid_query",
            selected=fallback,
            reason="candidate_pool_not_disambiguable",
            fallback_candidate=fallback,
        )

    proposal, stats = propose_one_query(
        task,
        frozen,
        query_pool,
        executor=executor,
        reserved_evaluation_inputs=reserved_evaluation_inputs,
        input_bound=input_bound,
        output_bound=output_bound,
        max_list_length=max_list_length,
    )
    emit("query_pool_screened", task_id=task_key, **stats)
    if proposal is None:
        emit("no_query", task_id=task_key, reason="no_valid_disagreement_query")
        emit(
            "fallback_selected",
            task_id=task_key,
            candidate_id=fallback.candidate_id,
            reason="no_valid_disagreement_query",
            original_portfolio_sha256=portfolio_sha,
            original_candidate_ids=[candidate.candidate_id for candidate in frozen],
        )
        return finish(
            "no_valid_query",
            selected=fallback,
            reason="no_valid_disagreement_query",
            fallback_candidate=fallback,
        )

    expected_type = _value_type(task["outputs"][0])
    request = OracleRequest(
        proposal.query_id,
        task_key,
        proposal.inputs,
        str(expected_type),
        idempotency_key=proposal.query_id,
    )
    emit(
        "query_proposed",
        task_id=task_key,
        query_id=proposal.query_id,
        query_sha256=proposal.query_sha256,
        query_pool_sha256=proposal.query_pool_sha256,
        selection_rationale=proposal.selection_rationale,
        inputs=proposal.inputs,
        disagreement_count=proposal.disagreement_count,
        pairwise_disagreements=proposal.pairwise_disagreements,
        predictions=proposal.predictions,
        candidate_ids=[candidate.candidate_id for candidate in frozen],
    )
    prior_response = next(
        (
            event for event in reversed(log.events)
            if event.get("event") == "oracle_response"
            and event.get("task_id") == task_key
            and event.get("query_id") == proposal.query_id
            and event.get("idempotency_key") == request.idempotency_key
        ),
        None,
    )
    response_reused = prior_response is not None
    if prior_response is not None:
        try:
            prior_status = OracleStatus(prior_response.get("status"))
        except (TypeError, ValueError):
            prior_status = OracleStatus.INVALID
        if prior_status == OracleStatus.ANSWERED:
            if "response_value" not in prior_response:
                # Older provenance recorded only an answer hash. Do not issue a
                # potentially duplicate external/human request to recover it.
                response = OracleResponse(
                    OracleStatus.INVALID,
                    detail="durable_answer_value_missing",
                )
            elif prior_response.get("answer_sha256") != _sha256_object(
                prior_response["response_value"]
            ):
                response = OracleResponse(
                    OracleStatus.INVALID,
                    detail="durable_answer_hash_mismatch",
                )
            else:
                response = OracleResponse(
                    OracleStatus.ANSWERED,
                    value=prior_response["response_value"],
                )
        else:
            response = OracleResponse(
                prior_status,
                detail=(
                    str(prior_response.get("detail"))
                    if prior_response.get("detail") is not None
                    else "replayed_durable_oracle_status"
                ),
            )
        emit(
            "oracle_response_reused",
            task_id=task_key,
            query_id=proposal.query_id,
            idempotency_key=request.idempotency_key,
            original_attempt_id=prior_response.get("attempt_id"),
            status=response.status.value,
            answer_sha256=prior_response.get("answer_sha256"),
        )
    else:
        emit(
            "oracle_requested",
            task_id=task_key,
            query_id=proposal.query_id,
            idempotency_key=request.idempotency_key,
            adapter=getattr(oracle, "adapter_name", type(oracle).__name__),
        )
        try:
            response = oracle.ask(request)
        except Exception as error:
            response = OracleResponse(OracleStatus.ERROR, detail=str(error)[:500])
        if not isinstance(response, OracleResponse):
            response = OracleResponse(
                OracleStatus.INVALID, detail="oracle_returned_untyped_response"
            )
    try:
        response_status = OracleStatus(response.status)
    except (TypeError, ValueError):
        response_status = OracleStatus.INVALID

    answer_hash = None
    validation_error = None
    if response_status == OracleStatus.ANSWERED:
        expected_type = _value_type(task["outputs"][0])
        if not _valid_bounded_value(
            response.value,
            expected_type=expected_type,
            bound=output_bound,
            max_list_length=max_list_length,
        ):
            response_status = OracleStatus.INVALID
            validation_error = "answer_type_or_bounds_invalid"
        else:
            answer_hash = _sha256_object(response.value)

    if not response_reused:
        emit(
            "oracle_response",
            task_id=task_key,
            query_id=proposal.query_id,
            idempotency_key=request.idempotency_key,
            adapter=getattr(oracle, "adapter_name", type(oracle).__name__),
            status=response_status.value,
            answer_sha256=answer_hash,
            response_value=(
                response.value if response_status == OracleStatus.ANSWERED else None
            ),
            detail=validation_error or (response.detail[:500] if response.detail else None),
        )

    if response_status == OracleStatus.ANSWERED:
        survivors = tuple(
            candidate
            for candidate in frozen
            if proposal.predictions[candidate.candidate_id] == response.value
        )
        if survivors:
            selected = survivors[0]
            emit(
                "candidate_selected",
                task_id=task_key,
                candidate_id=selected.candidate_id,
                reason="oracle_answer_exactly_matches_candidate_prediction",
                survivor_ids=[candidate.candidate_id for candidate in survivors],
            )
            return finish(
                "answered", query=proposal, selected=selected, survivors=survivors
            )
        reason = "zero_survivors"
    else:
        survivors = tuple()
        reason = {
            OracleStatus.SKIPPED: "oracle_skipped",
            OracleStatus.TIMED_OUT: "oracle_timeout",
            OracleStatus.INVALID: "oracle_invalid_response",
            OracleStatus.ERROR: "oracle_error",
        }[response_status]

    emit(
        "fallback_selected",
        task_id=task_key,
        candidate_id=fallback.candidate_id,
        reason=reason,
        original_portfolio_sha256=portfolio_sha,
        original_candidate_ids=[candidate.candidate_id for candidate in frozen],
    )
    return finish(
        "fallback",
        query=proposal,
        selected=fallback,
        survivors=survivors,
        reason=reason,
        fallback_candidate=fallback,
    )
