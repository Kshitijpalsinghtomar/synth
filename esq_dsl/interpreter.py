#!/usr/bin/env python3
"""ESQ-DSL: bounded typed program synthesis by execution-signature quotienting.

Input task format:
  {"inputs": {"x0": [example_0_value, example_1_value, ...]},
   "outputs": [example_0_output, example_1_output, ...]}

No third-party dependencies. Intended for small DeepCoder-like DSL tasks; it is
not a general-purpose synthesizer and does not learn weights from data.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

Value = int | list[int] | None


@dataclass(frozen=True)
class LambdaSpec:
    token: str
    arg_types: tuple[str, ...]
    out_type: str
    fn: Callable[..., Any]


@dataclass(frozen=True)
class OpSpec:
    name: str
    arg_types: tuple[str, ...]
    out_type: str
    fn: Callable[..., Any] | None = None
    lambda_types: tuple[str, ...] = ()  # allowed lambda input signatures, e.g. ('u1',)


def _is_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _take(n: Any, xs: Any) -> Any:
    return xs[:n]


def _drop(n: Any, xs: Any) -> Any:
    return xs[n:]


def _access(n: Any, xs: Any) -> Any:
    return xs[n] if _is_int(n) and 0 <= n < len(xs) else None


def _head(xs: Any) -> Any:
    return xs[0] if xs else None


def _last(xs: Any) -> Any:
    return xs[-1] if xs else None


def _minimum(xs: Any) -> Any:
    return min(xs) if xs else None


def _maximum(xs: Any) -> Any:
    return max(xs) if xs else None


def _scanl1(fn: Callable[[Any, Any], Any], xs: list[int]) -> list[int]:
    if not xs:
        return []
    out = [xs[0]]
    for item in xs[1:]:
        out.append(fn(out[-1], item))
    return out


LAMBDAS: dict[str, LambdaSpec] = {
    "(+1)": LambdaSpec("(+1)", ("int",), "int", lambda x: x + 1),
    "(-1)": LambdaSpec("(-1)", ("int",), "int", lambda x: x - 1),
    "(*2)": LambdaSpec("(*2)", ("int",), "int", lambda x: x * 2),
    "(/2)": LambdaSpec("(/2)", ("int",), "int", lambda x: x // 2),
    "(*(-1))": LambdaSpec("(*(-1))", ("int",), "int", lambda x: -x),
    "(**2)": LambdaSpec("(**2)", ("int",), "int", lambda x: x * x),
    "(*3)": LambdaSpec("(*3)", ("int",), "int", lambda x: x * 3),
    "(/3)": LambdaSpec("(/3)", ("int",), "int", lambda x: x // 3),
    "(*4)": LambdaSpec("(*4)", ("int",), "int", lambda x: x * 4),
    "(/4)": LambdaSpec("(/4)", ("int",), "int", lambda x: x // 4),
    "(>0)": LambdaSpec("(>0)", ("int",), "bool", lambda x: x > 0),
    "(<0)": LambdaSpec("(<0)", ("int",), "bool", lambda x: x < 0),
    "(%2==0)": LambdaSpec("(%2==0)", ("int",), "bool", lambda x: x % 2 == 0),
    "(%2==1)": LambdaSpec("(%2==1)", ("int",), "bool", lambda x: x % 2 == 1),
    "(+)": LambdaSpec("(+)", ("int", "int"), "int", lambda x, y: x + y),
    "(-)": LambdaSpec("(-)", ("int", "int"), "int", lambda x, y: x - y),
    "(*)": LambdaSpec("(*)", ("int", "int"), "int", lambda x, y: x * y),
    "(min)": LambdaSpec("(min)", ("int", "int"), "int", min),
    "(max)": LambdaSpec("(max)", ("int", "int"), "int", max),
}

OPS: dict[str, OpSpec] = {
    "Head": OpSpec("Head", ("list",), "int", _head),
    "Last": OpSpec("Last", ("list",), "int", _last),
    "Take": OpSpec("Take", ("int", "list"), "list", _take),
    "Drop": OpSpec("Drop", ("int", "list"), "list", _drop),
    "Access": OpSpec("Access", ("int", "list"), "int", _access),
    "Minimum": OpSpec("Minimum", ("list",), "int", _minimum),
    "Maximum": OpSpec("Maximum", ("list",), "int", _maximum),
    "Reverse": OpSpec("Reverse", ("list",), "list", lambda xs: list(reversed(xs))),
    "Sort": OpSpec("Sort", ("list",), "list", lambda xs: sorted(xs)),
    "Sum": OpSpec("Sum", ("list",), "int", lambda xs: sum(xs)),
    "Map": OpSpec("Map", ("list",), "list", lambda xs: xs, ("u1",)),
    "Filter": OpSpec("Filter", ("list",), "list", lambda xs: xs, ("ub",)),
    "Count": OpSpec("Count", ("list",), "int", lambda xs: xs, ("ub",)),
    "ZipWith": OpSpec("ZipWith", ("list", "list"), "list", lambda xs, ys: xs, ("b",)),
    "Scanl1": OpSpec("Scanl1", ("list",), "list", lambda xs: xs, ("b",)),
}

LAMBDA_FAMILY: dict[str, tuple[str, ...]] = {
    "u1": tuple(
        k for k, v in LAMBDAS.items() if v.arg_types == ("int",) and v.out_type == "int"
    ),
    "ub": tuple(
        k
        for k, v in LAMBDAS.items()
        if v.arg_types == ("int",) and v.out_type == "bool"
    ),
    "b": tuple(
        k
        for k, v in LAMBDAS.items()
        if v.arg_types == ("int", "int") and v.out_type == "int"
    ),
}


def type_of(value: Any) -> str:
    if _is_int(value):
        return "int"
    if isinstance(value, list) and all(_is_int(x) for x in value):
        return "list"
    raise TypeError(f"unsupported DeepCoder value/type: {value!r}")


def is_valid_result(value: Any, bound: int = 50) -> bool:
    if _is_int(value):
        return -bound <= value <= bound
    if isinstance(value, list):
        return all(_is_int(x) and -bound <= x <= bound for x in value)
    return False


def apply_op(
    op: str, lambda_token: str | None, args: list[Any], *, strict: bool = False
) -> Any:
    """Apply one DSL operation. `None` denotes an invalid/undefined result."""
    if any(x is None for x in args):
        return None
    try:
        spec = OPS[op]
        if lambda_token is None:
            if spec.fn is None:
                raise ValueError(f"{op} requires a lambda")
            result = spec.fn(*args)
        else:
            lam = LAMBDAS[lambda_token]
            if op == "Map":
                result = [lam.fn(x) for x in args[0]]
            elif op == "Filter":
                result = [x for x in args[0] if lam.fn(x)]
            elif op == "Count":
                result = sum(1 for x in args[0] if lam.fn(x))
            elif op == "ZipWith":
                result = [lam.fn(x, y) for x, y in zip(args[0], args[1])]
            elif op == "Scanl1":
                result = _scanl1(lam.fn, args[0])
            else:
                raise ValueError(f"{op} does not accept a lambda")
    except (ArithmeticError, TypeError, ValueError, IndexError):
        return None
    if strict and not is_valid_result(result):
        return None
    return result


def _split_lambda_atom(text: str) -> tuple[str, str]:
    text = text.lstrip()
    if not text.startswith("("):
        raise ValueError(f"lambda token must start with `(`: {text!r}")
    depth = 0
    for i, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[: i + 1], text[i + 1 :].strip()
    raise ValueError(f"unclosed lambda token: {text!r}")


@dataclass(frozen=True)
class Statement:
    lhs: str
    op: str
    args: tuple[str, ...] = ()
    lambda_token: str | None = None


def parse_program(program: str) -> list[Statement]:
    statements = []
    for raw in program.split("|"):
        if "=" not in raw:
            raise ValueError(f"missing assignment in {raw!r}")
        lhs, rhs = (x.strip() for x in raw.split("=", 1))
        if not lhs or not rhs:
            raise ValueError(f"invalid statement {raw!r}")
        if rhs == "INPUT":
            statements.append(Statement(lhs, "INPUT"))
            continue
        parts = rhs.split(None, 1)
        op = parts[0]
        rest = parts[1].strip() if len(parts) > 1 else ""
        if op not in OPS:
            raise ValueError(f"unknown operation {op!r}")
        lambda_token = None
        if OPS[op].lambda_types:
            lambda_token, rest = _split_lambda_atom(rest)
            if lambda_token not in LAMBDAS:
                raise ValueError(f"unknown lambda token {lambda_token!r}")
            if lambda_token not in LAMBDA_FAMILY[OPS[op].lambda_types[0]]:
                raise ValueError(f"lambda {lambda_token!r} has the wrong type for {op}")
        elif rest.startswith("("):
            raise ValueError(f"{op} does not take a lambda")
        args = tuple(rest.split()) if rest else ()
        if len(args) != len(OPS[op].arg_types):
            raise ValueError(
                f"{op} expects {len(OPS[op].arg_types)} variables, got {len(args)}"
            )
        statements.append(Statement(lhs, op, args, lambda_token))
    if not statements:
        raise ValueError("empty program")
    return statements


def execute_program(
    program: str | list[Statement], inputs: dict[str, Any], *, strict: bool = False
) -> Any:
    ast = parse_program(program) if isinstance(program, str) else program
    env: dict[str, Any] = {}
    for statement in ast:
        if statement.op == "INPUT":
            if statement.lhs not in inputs:
                raise ValueError(f"missing input {statement.lhs!r}")
            env[statement.lhs] = inputs[statement.lhs]
            continue
        if any(name not in env for name in statement.args):
            return None  # rejects forward references and missing variables
        args = [env[name] for name in statement.args]
        actual_types = tuple("list" if isinstance(x, list) else "int" for x in args)
        if actual_types != OPS[statement.op].arg_types:
            return None
        env[statement.lhs] = apply_op(
            statement.op, statement.lambda_token, args, strict=strict
        )
        if env[statement.lhs] is None:
            return None
    return env[ast[-1].lhs]


@dataclass
class Node:
    kind: str
    type: str
    signature: tuple[Any, ...]
    cost: int
    code: str
    name: str | None = None
    op: str | None = None
    lambda_token: str | None = None
    children: tuple["Node", ...] = ()


def _signature_key(node_type: str, signature: Iterable[Any]) -> str:
    return json.dumps(
        [node_type, list(signature)],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _valid_task(task: dict[str, Any]) -> int:
    if not isinstance(task, dict) or "inputs" not in task or "outputs" not in task:
        raise ValueError("task must contain `inputs` and `outputs`")
    inputs, outputs = task["inputs"], task["outputs"]
    if not isinstance(inputs, dict) or not inputs:
        raise ValueError(
            "inputs must be a nonempty mapping from variable names to example vectors"
        )
    if not isinstance(outputs, list) or not outputs:
        raise ValueError("outputs must be a nonempty list")
    n = len(outputs)
    if any(not isinstance(v, list) or len(v) != n for v in inputs.values()):
        raise ValueError("each input variable must have one value per output example")
    for variable, vec in inputs.items():
        types = {type_of(value) for value in vec}
        if len(types) != 1:
            raise ValueError(
                f"input variable {variable!r} changes type across examples"
            )
    output_types = {type_of(out) for out in outputs}
    if len(output_types) != 1:
        raise ValueError("outputs must have one consistent type across examples")
    return n


def _node_value(node: Node, idx: int) -> Any:
    return node.signature[idx]


def _compile_expression(node: Node, input_names: list[str]) -> str:
    # Programs evaluate to their last assignment. If the best expression is an
    # input variable itself, declare that variable last so serialization keeps
    # the chosen root as the program result.
    ordered_inputs = list(input_names)
    if node.kind == "var" and node.name in ordered_inputs:
        ordered_inputs = [name for name in ordered_inputs if name != node.name] + [
            node.name
        ]
    next_index = (
        max(
            [-1]
            + [
                int(name[1:])
                for name in input_names
                if len(name) > 1 and name[0] == "x" and name[1:].isdigit()
            ]
        )
        + 1
    )
    statements = [f"{name} = INPUT" for name in ordered_inputs]
    counter = next_index

    def emit(current: Node) -> str:
        nonlocal counter
        if current.kind == "var":
            assert current.name is not None
            return current.name
        child_vars = [emit(child) for child in current.children]
        lhs = f"x{counter}"
        counter += 1
        rhs = current.op or ""
        if current.lambda_token:
            rhs += f" {current.lambda_token}"
        if child_vars:
            rhs += " " + " ".join(child_vars)
        statements.append(f"{lhs} = {rhs}")
        return lhs

    emit(node)
    return " | ".join(statements)


@dataclass
class SynthesisResult:
    program: str | None
    exact_fit: bool
    examples_matched: int
    examples_total: int
    unique_signatures: int
    truncated: bool
    stop_reason: str
    elapsed_ms: float
    expression: str | None

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
        }


def synthesize(
    task: dict[str, Any],
    *,
    max_ops: int = 4,
    max_signatures: int = 10_000,
    timeout_s: float = 5.0,
    strict_intermediates: bool = False,
) -> SynthesisResult:
    """Synthesize a bounded program using execution-signature quotienting.

    The signature is `(result_type, outputs_on_visible_examples)`. Among programs
    with a repeated signature, one representative is retained. It is selected
    by minimum operator count, then lexical expression code.

    If a cap is reached, `truncated=True` makes clear that search completeness is
    not established. A partial-fit candidate is returned if any compatible
    candidate was examined.
    """
    n_examples = _valid_task(task)
    if max_ops < 0 or max_signatures < 1 or timeout_s <= 0:
        raise ValueError(
            "max_ops >= 0, max_signatures >= 1 and timeout_s > 0 are required"
        )
    t0 = time.perf_counter()
    deadline = t0 + timeout_s
    levels: dict[int, list[Node]] = {0: []}
    seen: dict[str, Node] = {}
    input_names = list(task["inputs"])

    for name in input_names:
        vec = tuple(task["inputs"][name])
        node_type = type_of(vec[0])
        node = Node("var", node_type, vec, 0, name, name=name)
        key = _signature_key(node.type, node.signature)
        if key not in seen:
            seen[key] = node
            levels[0].append(node)

    output_type = type_of(task["outputs"][0])
    target_signature = tuple(task["outputs"])

    def is_exact(node: Node) -> bool:
        return node.type == output_type and node.signature == target_signature

    def current_best() -> Node | None:
        pool = [x for x in seen.values() if x.type == output_type]
        if not pool:
            return None

        def rank(node: Node) -> tuple[int, int, str]:
            matches = sum(a == b for a, b in zip(node.signature, target_signature))
            return (-matches, node.cost, node.code)

        return min(pool, key=rank)

    exact_input = next((x for x in levels[0] if is_exact(x)), None)
    if exact_input is not None:
        return SynthesisResult(
            _compile_expression(exact_input, input_names),
            True,
            n_examples,
            n_examples,
            len(seen),
            False,
            "exact_input",
            (time.perf_counter() - t0) * 1000,
            exact_input.code,
        )

    def make_node(
        op_name: str, lambda_token: str | None, children: tuple[Node, ...]
    ) -> Node:
        spec = OPS[op_name]
        signature = []
        for i in range(n_examples):
            args = [_node_value(child, i) for child in children]
            value = apply_op(op_name, lambda_token, args, strict=strict_intermediates)
            signature.append(value)
        signature_tuple = tuple(signature)
        code = f'{op_name}{" " + lambda_token if lambda_token else ""}({",".join(c.code for c in children)})'
        return Node(
            "op",
            spec.out_type,
            signature_tuple,
            1 + sum(child.cost for child in children),
            code,
            op=op_name,
            lambda_token=lambda_token,
            children=children,
        )

    truncated = False
    stop_reason = "max_ops_reached"
    exact_found = False

    for cost in range(1, max_ops + 1):
        fresh: dict[str, Node] = {}

        def offer(node: Node) -> None:
            key = _signature_key(node.type, node.signature)
            if key in seen:
                return
            old = fresh.get(key)
            if old is None or node.code < old.code:
                fresh[key] = node

        for op_name, spec in OPS.items():
            lambda_tokens: tuple[str | None, ...] = (
                tuple(LAMBDA_FAMILY[spec.lambda_types[0]])
                if spec.lambda_types
                else (None,)
            )
            if len(spec.arg_types) == 1:
                for child in levels.get(cost - 1, []):
                    if child.type != spec.arg_types[0]:
                        continue
                    for lambda_token in lambda_tokens:
                        offer(make_node(op_name, lambda_token, (child,)))
            else:
                for left_cost in range(cost):
                    right_cost = cost - 1 - left_cost
                    for left in levels.get(left_cost, []):
                        if left.type != spec.arg_types[0]:
                            continue
                        for right in levels.get(right_cost, []):
                            if right.type != spec.arg_types[1]:
                                continue
                            for lambda_token in lambda_tokens:
                                offer(make_node(op_name, lambda_token, (left, right)))
            if time.perf_counter() >= deadline:
                truncated = True
                stop_reason = "time_cap"
                break
        if truncated:
            break

        nodes = sorted(fresh.values(), key=lambda x: x.code)
        room = max(0, max_signatures - len(seen))
        if len(nodes) > room:
            admitted = nodes[:room]
            levels[cost] = admitted
            for node in admitted:
                seen[_signature_key(node.type, node.signature)] = node
            # Accept an exact candidate in the deterministic admitted prefix.
            exact_found = any(is_exact(node) for node in admitted)
            if exact_found:
                stop_reason = "exact_fit_within_cap_prefix"
            else:
                truncated = True
                stop_reason = "signature_cap"
            break

        levels[cost] = nodes
        for node in nodes:
            seen[_signature_key(node.type, node.signature)] = node
        if any(is_exact(node) for node in nodes):
            exact_found = True
            stop_reason = "exact_fit_found"
            break
        if time.perf_counter() >= deadline:
            truncated = True
            stop_reason = "time_cap"
            break

    best = current_best()
    if best is None:
        return SynthesisResult(
            None,
            False,
            0,
            n_examples,
            len(seen),
            truncated,
            stop_reason,
            (time.perf_counter() - t0) * 1000,
            None,
        )
    matches = sum(a == b for a, b in zip(best.signature, target_signature))
    exact = matches == n_examples
    # If a full exact program was found, report it directly. If a cap was hit but
    # the admitted prefix includes an exact candidate, it still is an exact fit.
    return SynthesisResult(
        _compile_expression(best, input_names),
        exact,
        matches,
        n_examples,
        len(seen),
        truncated,
        stop_reason,
        (time.perf_counter() - t0) * 1000,
        best.code,
    )


def load_task(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        task = json.load(f)
    _valid_task(task)
    return task


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ESQ-DSL bounded typed program synthesizer"
    )
    parser.add_argument("task", type=Path, help="JSON task with inputs and outputs")
    parser.add_argument("--max-ops", type=int, default=4)
    parser.add_argument("--max-signatures", type=int, default=10_000)
    parser.add_argument(
        "--timeout", type=float, default=5.0, help="per-task wall-clock budget, seconds"
    )
    parser.add_argument(
        "--strict-intermediates",
        action="store_true",
        help="reject intermediate integer/list results outside [-50, 50]",
    )
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    task = load_task(args.task)
    result = synthesize(
        task,
        max_ops=args.max_ops,
        max_signatures=args.max_signatures,
        timeout_s=args.timeout,
        strict_intermediates=args.strict_intermediates,
    )
    print(
        json.dumps(
            result.as_dict(), indent=2 if args.pretty else None, ensure_ascii=False
        )
    )
    return 0 if result.exact_fit else 2


if __name__ == "__main__":
    raise SystemExit(main())
