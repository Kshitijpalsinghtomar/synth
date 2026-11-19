"""Branch-preserving neural-priority ordering for ESQ-DSL.

The guide only changes operator/lambda visitation order. It never removes a
valid operation, lambda, argument combination, or execution signature.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any, Callable, Mapping, Sequence

from . import interpreter as core


@dataclass
class SynthesisResultV3:
    program: str | None
    exact_fit: bool
    examples_matched: int
    examples_total: int
    unique_signatures: int
    truncated: bool
    stop_reason: str
    elapsed_ms: float
    expression: str | None
    candidates: list[dict[str, Any]]
    signature_keys: frozenset[str]
    visited_operations: tuple[str, ...]
    visited_lambdas: tuple[str, ...]
    generated_candidates: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "program": self.program,
            "exact_fit": self.exact_fit,
            "examples_matched": self.examples_matched,
            "examples_total": self.examples_total,
            "visible_example_accuracy": self.examples_matched / self.examples_total,
            "unique_signatures": self.unique_signatures,
            "truncated": self.truncated,
            "stop_reason": self.stop_reason,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "expression": self.expression,
            "candidates": self.candidates,
            "visited_operations": list(self.visited_operations),
            "visited_lambdas": list(self.visited_lambdas),
            "generated_candidates": self.generated_candidates,
        }


def _ordered(items: Sequence[str], scores: Mapping[str, float] | None) -> list[str]:
    """Stable descending-score order; all supplied choices are retained."""
    if scores is None:
        return list(items)
    clean: dict[str, float] = {}
    for key, value in scores.items():
        score = float(value)
        if not math.isfinite(score):
            raise ValueError(f"non-finite priority for {key}")
        clean[key] = score
    return sorted(items, key=lambda key: (-clean.get(key, 0.5), key))


def _candidate_record(
    node: core.Node, input_names: list[str], score: float
) -> dict[str, Any]:
    return {
        "program": core._compile_expression(node, input_names),
        "expression": node.code,
        "exact_fit": True,
        "priority_score": float(score),
        "cost": int(node.cost),
    }


def synthesize_priority(
    task: dict[str, Any],
    *,
    operator_scores: Mapping[str, float] | None = None,
    lambda_scores: Mapping[str, float] | None = None,
    max_ops: int = 4,
    max_signatures: int = 10_000,
    timeout_s: float = 5.0,
    top_k: int = 3,
    strict_intermediates: bool = False,
    candidate_scorer: Callable[[core.Node], float] | None = None,
    deadline_check_interval: int = 64,
) -> SynthesisResultV3:
    """Run complete typed enumeration ordered by learned priorities.

    With no time/signature cap, changing priorities leaves the reachable
    execution-signature set unchanged. The exact signature quotient is retained:
    one deterministic (minimum-cost, then lexical) representative is expanded
    per signature. A separate bounded portfolio stores alternatives only for
    the final target signature.

    Learned scores are never used as thresholds, masks, or beam widths.
    """
    n_examples = core._valid_task(task)
    if max_ops < 0 or max_signatures < 1 or timeout_s <= 0 or top_k < 1:
        raise ValueError("invalid search limits")
    if deadline_check_interval < 1:
        raise ValueError("deadline_check_interval must be >= 1")

    op_names = list(core.OPS.keys())
    ordered_ops = _ordered(op_names, operator_scores)
    ordered_lambda_families = {
        family: _ordered(tokens, lambda_scores)
        for family, tokens in core.LAMBDA_FAMILY.items()
    }

    started = time.perf_counter()
    deadline = started + timeout_s
    levels: dict[int, list[core.Node]] = {0: []}
    seen: dict[str, core.Node] = {}
    input_names = list(task["inputs"])

    for name in input_names:
        vector = tuple(task["inputs"][name])
        node_type = core.type_of(vector[0])
        node = core.Node("var", node_type, vector, 0, name, name=name)
        key = core._signature_key(node.type, node.signature)
        if key not in seen:
            seen[key] = node
            levels[0].append(node)

    target_type = core.type_of(task["outputs"][0])
    target_signature = tuple(task["outputs"])

    def exact(node: core.Node) -> bool:
        return node.type == target_type and node.signature == target_signature

    # Keep a bounded shortest-first portfolio for each exact execution signature.
    # The main search quotient still expands one representative per signature.
    exact_signature_cache: dict[str, list[core.Node]] = {}
    exact_found = False

    def retain_exact(node: core.Node) -> None:
        key = core._signature_key(node.type, node.signature)
        bucket = exact_signature_cache.setdefault(key, [])
        if any(existing.code == node.code for existing in bucket):
            return
        bucket.append(node)
        bucket.sort(key=lambda item: (item.cost, item.code))
        del bucket[top_k:]

    # An input may itself be exact. Continue through the first operator layer
    # so the portfolio can still contain up to three distinct shortest programs.
    for input_node in levels[0]:
        if exact(input_node):
            exact_found = True
            retain_exact(input_node)

    generated = 0
    visited_operations: list[str] = []
    visited_lambdas: list[str] = []
    truncated = False
    stop_reason = "max_ops_reached"
    stop = False
    partial_level: dict[str, core.Node] = {}

    def make_node(
        op_name: str,
        lambda_token: str | None,
        children: tuple[core.Node, ...],
    ) -> core.Node:
        spec = core.OPS[op_name]
        outputs = []
        for example_index in range(n_examples):
            args = [core._node_value(child, example_index) for child in children]
            outputs.append(
                core.apply_op(op_name, lambda_token, args, strict=strict_intermediates)
            )
        signature = tuple(outputs)
        expression = (
            f'{op_name}{" " + lambda_token if lambda_token else ""}'
            f'({",".join(child.code for child in children)})'
        )
        return core.Node(
            "op",
            spec.out_type,
            signature,
            1 + sum(child.cost for child in children),
            expression,
            op=op_name,
            lambda_token=lambda_token,
            children=children,
        )

    def consider(node: core.Node) -> None:
        nonlocal generated, exact_found, truncated, stop_reason, stop
        generated += 1

        if exact(node):
            exact_found = True
            retain_exact(node)

        key = core._signature_key(node.type, node.signature)
        if key in seen:
            return
        if key in partial_level:
            old = partial_level[key]
            if (node.cost, node.code) < (old.cost, old.code):
                partial_level[key] = node
            return

        if len(seen) + len(partial_level) >= max_signatures:
            truncated = True
            stop_reason = "signature_cap"
            stop = True
            return

        partial_level[key] = node

    for cost in range(1, max_ops + 1):
        partial_level = {}
        streams = []

        # Build one full candidate stream for every operation/lambda choice.
        # Scores decide stream order only. Every stream remains live and is
        # advanced once per round so a high-priority stream cannot starve others.
        for op_name in ordered_ops:
            visited_operations.append(op_name)
            spec = core.OPS[op_name]
            lambda_family = spec.lambda_types[0] if spec.lambda_types else None
            lambda_tokens: tuple[str | None, ...] = (
                tuple(ordered_lambda_families[lambda_family])
                if lambda_family
                else (None,)
            )

            for lambda_token in lambda_tokens:

                def candidate_stream(
                    op_name=op_name,
                    lambda_token=lambda_token,
                    spec=spec,
                    cost=cost,
                ):
                    if len(spec.arg_types) == 1:
                        for child in levels.get(cost - 1, []):
                            if child.type == spec.arg_types[0]:
                                yield make_node(op_name, lambda_token, (child,))
                    else:
                        for left_cost in range(cost):
                            right_cost = cost - 1 - left_cost
                            for left in levels.get(left_cost, []):
                                if left.type != spec.arg_types[0]:
                                    continue
                                for right in levels.get(right_cost, []):
                                    if right.type == spec.arg_types[1]:
                                        yield make_node(
                                            op_name, lambda_token, (left, right)
                                        )

                streams.append((op_name, lambda_token, iter(candidate_stream())))

        layer_complete = True
        active_streams = streams
        while active_streams:
            next_round = []
            for op_name, lambda_token, stream in active_streams:
                try:
                    node = next(stream)
                except StopIteration:
                    continue

                if lambda_token is not None:
                    visited_lambdas.append(lambda_token)
                consider(node)
                if stop:
                    layer_complete = False
                    break
                if (
                    generated % deadline_check_interval == 0
                    and time.perf_counter() >= deadline
                ):
                    truncated = True
                    stop_reason = "time_cap"
                    stop = True
                    layer_complete = False
                    break
                next_round.append((op_name, lambda_token, stream))

            active_streams = next_round
            if stop:
                break
            if time.perf_counter() >= deadline:
                truncated = True
                stop_reason = "time_cap"
                stop = True
                layer_complete = False
                break

        # Partial signatures remain available for the best visible candidate,
        # but are never expanded as if the interrupted layer were complete.
        for key, node in partial_level.items():
            seen[key] = node
        levels[cost] = sorted(partial_level.values(), key=lambda item: item.code)

        if stop:
            break
        if exact_found:
            stop_reason = "exact_fit_found"
            break
        if not layer_complete:
            break

    output_nodes = [node for node in seen.values() if node.type == target_type]
    if output_nodes:

        def visible_rank(node: core.Node) -> tuple[int, int, str]:
            matches = sum(a == b for a, b in zip(node.signature, target_signature))
            return (-matches, node.cost, node.code)

        best = min(output_nodes, key=visible_rank)
        matches = sum(a == b for a, b in zip(best.signature, target_signature))
        program = core._compile_expression(best, input_names)
        expression = best.code
    else:
        best = None
        matches = 0
        program = None
        expression = None

    def prior_candidate_score(node: core.Node) -> float:
        operation_probabilities = operator_scores or {}
        lambda_probabilities = lambda_scores or {}
        values = []

        def visit(current: core.Node):
            if current.kind != "op":
                return
            probability = min(
                max(float(operation_probabilities.get(current.op or "", 0.5)), 1e-6),
                1.0 - 1e-6,
            )
            values.append(math.log(probability))
            if current.lambda_token:
                probability = min(
                    max(
                        float(lambda_probabilities.get(current.lambda_token, 0.5)), 1e-6
                    ),
                    1.0 - 1e-6,
                )
                values.append(math.log(probability))
            for child in current.children:
                visit(child)

        visit(node)
        return sum(values) / len(values) if values else 0.0

    records = []
    for signature_key in sorted(exact_signature_cache):
        for node in exact_signature_cache[signature_key]:
            score = (
                float(candidate_scorer(node))
                if candidate_scorer
                else prior_candidate_score(node)
            )
            if not math.isfinite(score):
                raise ValueError("candidate scorer returned a non-finite value")
            records.append(_candidate_record(node, input_names, score))
    records.sort(
        key=lambda row: (-row["priority_score"], row["cost"], row["expression"])
    )
    records = records[:top_k]

    if records:
        # The executable top-1 is selected by the observable candidate score,
        # never by the hidden reference program.
        program = records[0]["program"]
        expression = records[0]["expression"]
        matches = n_examples

    return SynthesisResultV3(
        program,
        matches == n_examples,
        matches,
        n_examples,
        len(seen),
        truncated,
        stop_reason,
        (time.perf_counter() - started) * 1000,
        expression,
        records,
        frozenset(seen),
        tuple(visited_operations),
        tuple(visited_lambdas),
        generated,
    )
