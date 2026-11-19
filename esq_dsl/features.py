"""Compact feature encoding of three ESQ input/output examples."""

from __future__ import annotations
import math
from statistics import median
from typing import Any
import numpy as np

FEATURE_DIM = 37
MAX_INPUT_VARIABLES = 3
MAX_VARIABLES_WITH_OUTPUT = 4


def _ratio(value: float, scale: float) -> float:
    return float(np.clip(value / scale, -2.0, 2.0))


def _base(value: Any) -> list[float]:
    f = [0.0] * FEATURE_DIM
    if isinstance(value, bool):
        raise TypeError("bool is outside the DeepCoder value domain")
    if isinstance(value, int):
        f[0] = 1.0
        f[2] = _ratio(value, 50.0)
        f[3] = min(abs(value) / 50.0, 2.0)
        f[4], f[5], f[6] = float(value < 0), float(value == 0), float(value > 0)
        return f
    if not isinstance(value, list) or any(
        not isinstance(x, int) or isinstance(x, bool) for x in value
    ):
        raise TypeError(f"unsupported value {value!r}")
    f[1] = 1.0
    n = len(value)
    f[7] = min(n / 5.0, 2.0)
    f[24] = float(n == 0)
    if not n:
        return f
    avg = sum(value) / n
    variance = sum((x - avg) ** 2 for x in value) / n
    ordered = sorted(value)
    f[8] = _ratio(avg, 50.0)
    f[9] = min(math.sqrt(variance) / 50.0, 2.0)
    f[10], f[11] = _ratio(min(value), 50.0), _ratio(max(value), 50.0)
    f[12] = _ratio(sum(value), 250.0)
    f[13], f[14] = _ratio(value[0], 50.0), _ratio(value[-1], 50.0)
    f[15] = _ratio(float(median(value)), 50.0)
    f[16] = float(value == ordered)
    f[17] = len(set(value)) / n
    f[18] = sum(x < 0 for x in value) / n
    f[19] = sum(x == 0 for x in value) / n
    f[20] = sum(x > 0 for x in value) / n
    f[21] = sum(x % 2 == 0 for x in value) / n
    f[22] = sum(x % 2 != 0 for x in value) / n
    f[23] = float(len(set(value)) != n)
    return f


def _relations(value: Any, output: Any) -> list[float]:
    r = [0.0] * 11
    r[0] = float(value == output)
    r[1] = float(
        (isinstance(value, list) and isinstance(output, list))
        or (
            isinstance(value, int)
            and not isinstance(value, bool)
            and isinstance(output, int)
            and not isinstance(output, bool)
        )
    )
    if isinstance(value, list):
        r[2] = float(isinstance(output, list) and len(value) == len(output))
        if isinstance(output, list):
            r[3] = float(output == sorted(value))
            r[4] = float(output == list(reversed(value)))
        if value and isinstance(output, int) and not isinstance(output, bool):
            r[5] = float(output == sum(value))
            r[6] = float(output == min(value))
            r[7] = float(output == max(value))
            r[8] = float(output == value[0])
            r[9] = float(output == value[-1])
        r[10] = float(
            isinstance(output, int)
            and not isinstance(output, bool)
            and output == len(value)
        )
    return r


def encode_task(task: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    if not isinstance(task.get("inputs"), dict) or not task.get("outputs"):
        raise ValueError("task must contain inputs and outputs")
    inputs, outputs = task["inputs"], task["outputs"]
    names = list(inputs)
    if len(names) > MAX_INPUT_VARIABLES or len(outputs) != 3:
        raise ValueError(
            "expected at most three inputs and exactly three visible examples"
        )
    if any(not isinstance(inputs[k], list) or len(inputs[k]) != 3 for k in names):
        raise ValueError("each input variable must have three values")
    values = np.zeros((3, 4, FEATURE_DIM), dtype=np.float32)
    mask = np.zeros((4,), dtype=np.float32)
    mask[: len(names) + 1] = 1.0
    for i, output in enumerate(outputs):
        for j, name in enumerate(names):
            vector = _base(inputs[name][i])
            vector[25:36] = _relations(inputs[name][i], output)
            values[i, j] = vector
        out_vector = _base(output)
        out_vector[36] = 1.0
        values[i, len(names)] = out_vector
    if not np.isfinite(values).all():
        raise ValueError("non-finite task features")
    return values, mask
