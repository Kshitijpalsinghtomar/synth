"""Command-line interface for Synth's three execution modes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from . import interpreter
from .oracle import (
    HumanCLIOracle,
    SubprocessOracle,
    generate_query_pool,
    run_one_shot_oracle,
)
from .synthesizer import synthesize_priority


def run_task(
    task: dict[str, Any],
    *,
    mode: str = "symbolic",
    checkpoint: str | Path = "checkpoints/esq_v3_converged.pt",
    oracle_command: Sequence[str] | None = None,
    max_ops: int = 4,
    max_signatures: int = 10_000,
    timeout_s: float = 0.30,
    query_count: int = 100,
) -> dict[str, Any]:
    """Run one task in symbolic, guided, or one-turn interactive mode."""
    if mode == "symbolic":
        result = interpreter.synthesize(
            task,
            max_ops=max_ops,
            max_signatures=max_signatures,
            timeout_s=timeout_s,
            strict_intermediates=True,
        )
        return {"mode": mode, **result.as_dict()}

    if mode not in {"guided", "interactive"}:
        raise ValueError("mode must be 'symbolic', 'guided', or 'interactive'")

    # Import the optional ML stack only when a guided mode is requested.
    from .neural_guide import NeuralGuide

    guide = NeuralGuide(checkpoint)
    operator_scores, lambda_scores, length_probabilities = guide.predict(task)
    result = synthesize_priority(
        task,
        operator_scores=operator_scores,
        lambda_scores=lambda_scores,
        max_ops=max_ops,
        max_signatures=max_signatures,
        timeout_s=timeout_s,
        top_k=3,
        strict_intermediates=True,
    )

    response: dict[str, Any] = {
        "mode": mode,
        "checkpoint_sha256": guide.checkpoint_sha256,
        "operator_priors": operator_scores,
        "lambda_priors": lambda_scores,
        "length_probabilities": length_probabilities,
        **result.as_dict(),
    }
    if mode == "guided":
        return response

    if not result.candidates:
        response["oracle"] = {
            "status": "no_candidates",
            "selected_program": None,
        }
        return response

    oracle = (
        SubprocessOracle(list(oracle_command)) if oracle_command else HumanCLIOracle()
    )
    query_pool = generate_query_pool(task, count=query_count)
    session = run_one_shot_oracle(task, result.candidates, query_pool, oracle)

    response["oracle"] = session.as_dict()
    response["selected_program"] = (
        session.selected_candidate.program if session.selected_candidate else None
    )
    return response


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="synth",
        description="Bounded synthesis for the DeepCoder typed list/integer DSL.",
    )
    parser.add_argument(
        "task", type=Path, help="JSON task containing inputs and outputs"
    )
    parser.add_argument(
        "--mode",
        choices=("symbolic", "guided", "interactive"),
        default="symbolic",
        help="search mode (default: symbolic)",
    )
    parser.add_argument(
        "--checkpoint",
        default="checkpoints/esq_v3_converged.pt",
        help="CPU model checkpoint used by guided and interactive modes",
    )
    parser.add_argument(
        "--oracle-command",
        nargs="+",
        help="local oracle adapter command; shell execution is disabled",
    )
    parser.add_argument("--max-ops", type=int, default=4)
    parser.add_argument("--max-signatures", type=int, default=10_000)
    parser.add_argument("--timeout", type=float, default=0.30)
    parser.add_argument("--query-count", type=int, default=100)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    task = json.loads(args.task.read_text(encoding="utf-8"))
    result = run_task(
        task,
        mode=args.mode,
        checkpoint=args.checkpoint,
        oracle_command=args.oracle_command,
        max_ops=args.max_ops,
        max_signatures=args.max_signatures,
        timeout_s=args.timeout,
        query_count=args.query_count,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
