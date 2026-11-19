"""Load and run the frozen CPU neural search-priority model."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import torch

from .features import encode_task
from .model import ESQSetEncoder


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# CVE-2026-24747 affects torch.load(weights_only=True) before PyTorch 2.10.0.
# On older runtimes, load only this exact, repository-shipped checkpoint. Custom or
# externally supplied checkpoints require the patched PyTorch loader.
BUNDLED_CHECKPOINT_SHA256 = (
    "a0f03d5066d86022d932699c1a6dfe68957d56131a38e7816e2085bda2000d41"
)


def _require_safe_checkpoint_runtime(torch_version: str, checkpoint_sha256: str) -> None:
    match = re.match(r"^(\d+)\.(\d+)", str(torch_version))
    if match is None:
        raise ValueError(f"unrecognised PyTorch version: {torch_version!r}")
    version = tuple(map(int, match.groups()))
    if version < (2, 10) and checkpoint_sha256.lower() != BUNDLED_CHECKPOINT_SHA256:
        raise ValueError(
            "CVE-2026-24747: PyTorch before 2.10.0 cannot load custom or untrusted "
            "checkpoints through weights_only=True; upgrade PyTorch to >=2.10.0. "
            "On older runtimes only the exact hash-pinned bundled checkpoint is accepted."
        )


class NeuralGuide:
    """Inference-only adapter for a checkpoint with explicit integrity metadata."""

    def __init__(
        self,
        checkpoint: str | Path,
        *,
        expected_sha256: str | None = None,
    ) -> None:
        self.path = Path(checkpoint)
        if not self.path.is_file():
            raise FileNotFoundError(self.path)

        model_card_path = self.path.with_name("model_card.json")
        if not model_card_path.is_file():
            raise ValueError(
                f"model card is required beside checkpoint: {model_card_path}"
            )
        try:
            model_card = json.loads(model_card_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"model card is unreadable: {model_card_path}") from error

        checkpoint_record = model_card.get("checkpoint")
        if not isinstance(checkpoint_record, dict):
            raise ValueError("model card must contain a checkpoint record")
        recorded_sha256 = checkpoint_record.get("sha256")
        if not isinstance(recorded_sha256, str) or not re.fullmatch(
            r"[0-9a-fA-F]{64}", recorded_sha256
        ):
            raise ValueError("model card must contain a valid checkpoint SHA-256")
        recorded_sha256 = recorded_sha256.lower()

        if expected_sha256 is not None:
            if not isinstance(expected_sha256, str) or expected_sha256.lower() != recorded_sha256:
                raise ValueError("explicit expected SHA-256 disagrees with model card")

        sidecar_name = checkpoint_record.get(
            "sha256_sidecar", f"{self.path.name}.sha256"
        )
        if not isinstance(sidecar_name, str) or Path(sidecar_name).name != sidecar_name:
            raise ValueError("model card contains an invalid SHA-256 sidecar path")
        sidecar_path = self.path.with_name(sidecar_name)
        if not sidecar_path.is_file():
            raise ValueError(f"checkpoint SHA-256 sidecar is required: {sidecar_path}")
        try:
            sidecar_fields = sidecar_path.read_text(encoding="utf-8").strip().split()
        except OSError as error:
            raise ValueError(f"checkpoint SHA-256 sidecar is unreadable: {sidecar_path}") from error
        if (
            len(sidecar_fields) != 2
            or sidecar_fields[0].lower() != recorded_sha256
            or sidecar_fields[1].lstrip("*") != self.path.name
        ):
            raise ValueError("checkpoint SHA-256 sidecar disagrees with model card or filename")

        self.checkpoint_sha256 = _sha256_file(self.path)
        if self.checkpoint_sha256 != recorded_sha256:
            raise ValueError("checkpoint SHA-256 does not match the model card and sidecar")

        # PyTorch <2.10.0 has a weights_only unpickler vulnerability. Under that
        # runtime, the embedded source-level digest prevents loading custom weights.
        _require_safe_checkpoint_runtime(torch.__version__, self.checkpoint_sha256)

        # Restricted deserialization: do not execute arbitrary pickle globals.
        try:
            payload = torch.load(
                self.path,
                map_location="cpu",
                weights_only=True,
            )
        except Exception as error:
            raise ValueError("checkpoint could not be loaded with restricted deserialization") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("state_dict"), dict):
            raise ValueError("checkpoint must contain a state_dict")
        self.model = ESQSetEncoder()
        self.model.load_state_dict(payload["state_dict"], strict=True)
        self.model.eval()
        torch.set_num_threads(1)

    @torch.no_grad()
    def predict(
        self,
        task: dict[str, Any],
    ) -> tuple[dict[str, float], dict[str, float], list[float]]:
        values, variable_mask = encode_task(task)
        feature_tensor = torch.from_numpy(
            np.asarray(values, dtype=np.float32)[None, ...]
        )
        mask_tensor = torch.from_numpy(
            np.asarray(variable_mask, dtype=np.float32)[None, ...]
        )
        return self.model.predict_priors(feature_tensor, mask_tensor)
