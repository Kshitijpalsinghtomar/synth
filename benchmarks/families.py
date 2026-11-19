"""ExeDec-aligned variable-arity synthetic data and structural family splits."""

from __future__ import annotations

import hashlib
import itertools
import json
import random
from typing import Any

from esq_dsl import interpreter as core

LIST_VALUE_RANGES = ((0, 4), (0, 9), (-10, 10), (-50, 50))
LIST_LENGTH_RANGES = ((1, 3), (0, 5))
SCALAR_RANGE = (0, 5)
VISIBLE_EXAMPLES = 3
MIN_OPERATORS = 1
MAX_OPERATORS = 6
MAX_PROGRAM_ARITY = 2
GENERATOR_VERSION = "esq-synth-v3-exedec-inputs-1"


def assign_family_split(family_hash: str) -> str:
    """Stable 80/10/10 split assignment from a structural family digest."""
    if len(family_hash) != 64:
        raise ValueError("family_hash must be a SHA-256 hex digest")
    bucket = int(family_hash[:8], 16) % 100
    if bucket < 80:
        return "train"
    if bucket < 90:
        return "development"
    return "confirmation"


def structural_family_hash(program: str, input_types: dict[str, str]) -> str:
    """Hash input-type layout plus normalized active output AST."""
    ast = core.parse_program(program)
    definitions = {statement.lhs: statement for statement in ast}
    input_names = [statement.lhs for statement in ast if statement.op == "INPUT"]
    if not input_names or any(name not in input_types for name in input_names):
        raise ValueError("input_types must describe every declared input")
    input_index = {name: index for index, name in enumerate(input_names)}
    layout = [input_types[name] for name in input_names]

    def normalize(name: str):
        statement = definitions.get(name)
        if statement is None:
            raise ValueError(f"undefined variable {name}")
        if statement.op == "INPUT":
            return ["input", input_index[name]]
        return [
            "op",
            statement.op,
            statement.lambda_token,
            [normalize(argument) for argument in statement.args],
        ]

    payload = json.dumps(
        {"input_types": layout, "output_ast": normalize(ast[-1].lhs)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _draw_inputs(rng: random.Random, input_specs: dict[str, dict[str, Any]]):
    result = {}
    for name, spec in input_specs.items():
        if "length" not in spec:
            lo, hi = spec["range"]
            result[name] = rng.randint(lo, hi)
        else:
            lo, hi = spec["range"]
            length = rng.randint(*spec["length"])
            result[name] = [rng.randint(lo, hi) for _ in range(length)]
    return result


def _sample_input_layout(rng: random.Random):
    """Mirror ExeDec random_inputs defaults with max_program_arity=2."""
    input_count = rng.randint(1, MAX_PROGRAM_ARITY)
    input_types = ["list"] + [
        rng.choice(("int", "list")) for _ in range(input_count - 1)
    ]
    rng.shuffle(input_types)
    names = [f"x{i}" for i in range(input_count)]
    type_map = dict(zip(names, input_types))
    specs: dict[str, dict[str, Any]] = {}
    for name, value_type in type_map.items():
        if value_type == "int":
            specs[name] = {"range": list(SCALAR_RANGE)}
        else:
            specs[name] = {
                "range": list(rng.choice(LIST_VALUE_RANGES)),
                "length": list(rng.choice(LIST_LENGTH_RANGES)),
            }
    return type_map, specs


def generate_program_v3(
    rng: random.Random,
    input_types: dict[str, str],
    min_ops: int = MIN_OPERATORS,
    max_ops: int = MAX_OPERATORS,
):
    """Generate a valid single-output program over one or two typed inputs."""
    if not input_types or not any(
        value_type == "list" for value_type in input_types.values()
    ):
        raise ValueError("DeepCoder input layout must contain at least one list")
    if min_ops < 1 or max_ops < min_ops or max_ops > MAX_OPERATORS:
        raise ValueError("program length must be 1–6 operations")

    names = list(input_types)
    by_type = {
        "int": [
            name for name, value_type in input_types.items() if value_type == "int"
        ],
        "list": [
            name for name, value_type in input_types.items() if value_type == "list"
        ],
    }
    statements = [f"{name} = INPUT" for name in names]
    current_name = None
    current_type = None
    operators: list[str] = []
    lambda_tokens: list[str] = []

    for step in range(rng.randint(min_ops, max_ops)):
        options = []
        for op_name, spec in core.OPS.items():
            if current_name is None:
                pools = [by_type[value_type] for value_type in spec.arg_types]
                if any(not pool for pool in pools):
                    continue
                for combo in itertools.product(*pools):
                    if (
                        len(spec.arg_types) == 2
                        and spec.arg_types[0] == spec.arg_types[1]
                        and combo[0] == combo[1]
                    ):
                        continue
                    options.append((op_name, tuple(combo)))
            else:
                for current_position, arg_type in enumerate(spec.arg_types):
                    if arg_type != current_type:
                        continue
                    pools = [
                        (
                            [current_name]
                            if position == current_position
                            else [
                                name
                                for name in by_type[value_type]
                                if name != current_name
                            ]
                        )
                        for position, value_type in enumerate(spec.arg_types)
                    ]
                    if any(not pool for pool in pools):
                        continue
                    for combo in itertools.product(*pools):
                        if combo.count(current_name) == 1:
                            options.append((op_name, tuple(combo)))

        options = list(dict.fromkeys(options))
        if not options:
            raise RuntimeError("no valid continuation for generated DSL expression")

        op_name, args = rng.choice(options)
        spec = core.OPS[op_name]
        lambda_token = (
            rng.choice(core.LAMBDA_FAMILY[spec.lambda_types[0]])
            if spec.lambda_types
            else None
        )
        if lambda_token:
            lambda_tokens.append(lambda_token)
        lhs = f"t{step}"
        rhs = op_name + (f" {lambda_token}" if lambda_token else "")
        statements.append(f"{lhs} = {rhs} " + " ".join(args))
        operators.append(op_name)
        current_name, current_type = lhs, spec.out_type

    return " | ".join(statements), operators, lambda_tokens


def active_program_statements(program: str):
    ast = core.parse_program(program)
    definitions = {statement.lhs: statement for statement in ast}
    active = []
    visiting = set()

    def visit(name: str):
        if name in visiting:
            raise ValueError(f"cyclic dependency at {name}")
        statement = definitions.get(name)
        if statement is None or statement.op == "INPUT":
            return
        visiting.add(name)
        for argument in statement.args:
            visit(argument)
        visiting.remove(name)
        active.append(statement)

    if ast:
        visit(ast[-1].lhs)
    return active


def generate_synthetic_task_v3(
    seed: int,
    task_index: int = 0,
    max_attempts: int = 1000,
    *,
    min_ops: int = MIN_OPERATORS,
    max_ops: int = MAX_OPERATORS,
):
    """Generate a three-example task with explicit target-program depth bounds."""
    if min_ops < 1 or max_ops < min_ops or max_ops > MAX_OPERATORS:
        raise ValueError(f"target program length must be 1–{MAX_OPERATORS} operations")
    for attempt in range(max_attempts):
        attempt_seed = int(seed) + attempt * 104729
        rng = random.Random(attempt_seed)
        input_types, input_specs = _sample_input_layout(rng)
        try:
            program, _, _ = generate_program_v3(
                rng, input_types, min_ops=min_ops, max_ops=max_ops
            )
        except RuntimeError:
            continue
        program_ast = core.parse_program(program)
        active = active_program_statements(program)
        operators = [statement.op for statement in active]
        lambdas = [
            statement.lambda_token for statement in active if statement.lambda_token
        ]
        family_hash = structural_family_hash(program, input_types)

        rows = []
        outputs = []
        used = set()
        for _ in range(500):
            if len(rows) >= VISIBLE_EXAMPLES:
                break
            current = _draw_inputs(rng, input_specs)
            row_key = tuple(
                (name, tuple(value) if isinstance(value, list) else value)
                for name, value in current.items()
            )
            if row_key in used:
                continue
            try:
                output = core.execute_program(program_ast, current, strict=True)
            except (ArithmeticError, TypeError, ValueError, IndexError):
                output = None
            if output is None:
                continue
            used.add(row_key)
            rows.append(current)
            outputs.append(output)

        if len(rows) != VISIBLE_EXAMPLES:
            continue

        return {
            "task_id": int(task_index),
            "seed": attempt_seed,
            "generator_version": GENERATOR_VERSION,
            "inputs": {name: [row[name] for row in rows] for name in input_types},
            "outputs": outputs,
            "program": program,
            "operators": operators,
            "lambdas": lambdas,
            "operator_count": len(operators),
            "program_hash": hashlib.sha256(program.encode("utf-8")).hexdigest(),
            "program_family_hash": family_hash,
            "program_family_split": assign_family_split(family_hash),
            "input_types": input_types,
            "input_specs": input_specs,
        }

    raise RuntimeError(f"could not generate a valid task for seed {seed}")


def iter_synthetic_tasks(count: int, base_seed: int = 910000, start_index: int = 0):
    if count < 1:
        raise ValueError("count must be positive")
    for offset in range(count):
        index = start_index + offset
        yield generate_synthetic_task_v3(base_seed + index, index)
