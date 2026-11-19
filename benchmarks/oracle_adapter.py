"""One-turn local synthetic target adapters.

The benchmark uses SyntheticReferenceOracle in-process after visible portfolios
are frozen. The command-line mode implements the same JSON protocol for local
interactive CLI integrations and subprocess tests.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from esq_dsl.interpreter import execute_program
from esq_dsl.oracle import OracleRequest, OracleResponse, OracleStatus


class SyntheticReferenceOracle:
    """One-response adapter backed by a single task's withheld target-map file."""

    adapter_name = "synthetic_reference_file"

    def __init__(self, target_map_path: str | Path) -> None:
        self.target_map_path = Path(target_map_path)

    def ask(self, request: OracleRequest) -> OracleResponse:
        try:
            target_map = json.loads(self.target_map_path.read_text(encoding="utf-8"))
            program = target_map.get(request.task_id)
            if not isinstance(program, str):
                return OracleResponse(
                    OracleStatus.SKIPPED,
                    detail="target_unavailable",
                )
            value = execute_program(program, request.inputs, strict=True)
            if value is None:
                return OracleResponse(
                    OracleStatus.SKIPPED,
                    detail="target undefined",
                )
            return OracleResponse(OracleStatus.ANSWERED, value=value)
        except (OSError, ValueError, TypeError, KeyError) as error:
            return OracleResponse(
                OracleStatus.ERROR,
                detail=str(error)[:300],
            )


def main() -> int:
    """Serve one request from stdin against one task-specific target map."""
    if len(sys.argv) != 2:
        print(json.dumps({"status": "error", "detail": "target-map path required"}))
        return 2
    try:
        request: dict[str, Any] = json.load(sys.stdin)
        if request.get("protocol") != "esq-oracle-v1":
            print(json.dumps({"status": "invalid", "detail": "protocol mismatch"}))
            return 0
        oracle = SyntheticReferenceOracle(sys.argv[1])
        response = oracle.ask(
            OracleRequest(
                query_id=str(request.get("query_id", "")),
                task_id=str(request.get("task_id", "")),
                inputs=request.get("inputs", {}),
                expected_type=str(request.get("expected_type", "")),
                idempotency_key=(
                    str(request["idempotency_key"])
                    if request.get("idempotency_key") is not None
                    else None
                ),
            )
        )
        if response.status == OracleStatus.ANSWERED:
            payload = {"status": "answered", "value": response.value}
        elif response.status == OracleStatus.SKIPPED:
            payload = {"status": "unknown", "detail": response.detail}
        else:
            payload = {"status": "error", "detail": response.detail}
        print(json.dumps(payload, separators=(",", ":")))
        return 0
    except Exception as error:
        print(json.dumps({"status": "error", "detail": str(error)[:300]}))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
