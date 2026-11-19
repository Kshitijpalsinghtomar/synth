"""Deterministic v3 corpus generation and CPU-only task-prior training."""
from __future__ import annotations

import gzip
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from .esq_data_v3 import (
    GENERATOR_VERSION,
    assign_family_split,
    generate_synthetic_task_v3,
)
from esq_dsl.features import encode_task
from esq_dsl.model import ESQSetEncoder, OP_NAMES, LAMBDA_NAMES

EXEDEC_COMMIT = "ef046ce2cc3fcd024e32f5dfe00e69700dac82ed"
EXEDEC_SOURCE_BLOBS = {
    "tasks/deepcoder/dataset/write_data.py": "0dbff61f362c884e9e6af9ad7de5aa4fffcba9c4",
    "tasks/deepcoder/old_sample_random.py": "0fb531f0cf00e28bea02fdc9ad65388f5c1466da",
    "tasks/deepcoder/deepcoder_dsl.py": "8bc0db8516e132aef19c9ca85cbb0d5210a9c565",
}
SPLIT_TO_CODE = {"train": 0, "development": 1, "confirmation": 2}
CODE_TO_SPLIT = {value: key for key, value in SPLIT_TO_CODE.items()}


def _multi_hot(items, vocab):
    lookup = {value: index for index, value in enumerate(vocab)}
    result = np.zeros(len(vocab), dtype=np.float32)
    for item in items:
        if item in lookup:
            result[lookup[item]] = 1.0
    return result


def generate_corpus_v3(
    count=100_000,
    *,
    base_seed=1_116_000,
    jsonl_gz_path="artifacts/esq_v3_synthetic_tasks_100k.jsonl.gz",
    progress_every=5_000,
):
    if count < 100:
        raise ValueError("count must be >= 100")

    values = np.zeros((count, 3, 4, 37), dtype=np.float32)
    variable_mask = np.zeros((count, 4), dtype=np.float32)
    operator_labels = np.zeros((count, len(OP_NAMES)), dtype=np.float32)
    lambda_labels = np.zeros((count, len(LAMBDA_NAMES)), dtype=np.float32)
    length_labels = np.zeros(count, dtype=np.int64)
    split_codes = np.zeros(count, dtype=np.uint8)
    family_hashes = np.empty(count, dtype="U64")

    split_task_counts = {name: 0 for name in SPLIT_TO_CODE}
    split_family_sets = {name: set() for name in SPLIT_TO_CODE}
    arity_counts = {1: 0, 2: 0}
    input_type_counts = {"int": 0, "list": 0}
    started = time.perf_counter()
    path = Path(jsonl_gz_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    uncompressed_hash = hashlib.sha256()

    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            for index in range(count):
                task = generate_synthetic_task_v3(base_seed + index, index)
                feature_values, mask = encode_task({
                    "inputs": task["inputs"],
                    "outputs": task["outputs"],
                })
                values[index] = feature_values
                variable_mask[index] = mask
                operator_labels[index] = _multi_hot(task["operators"], OP_NAMES)
                lambda_labels[index] = _multi_hot(task["lambdas"], LAMBDA_NAMES)
                length_labels[index] = len(task["operators"]) - 1

                split = task["program_family_split"]
                split_codes[index] = SPLIT_TO_CODE[split]
                family_hash = task["program_family_hash"]
                family_hashes[index] = family_hash
                if assign_family_split(family_hash) != split:
                    raise AssertionError("family split assignment is not deterministic")
                split_task_counts[split] += 1
                split_family_sets[split].add(family_hash)

                arity_counts[len(task["inputs"])] += 1
                for value_type in task["input_types"].values():
                    input_type_counts[value_type] += 1

                task_line = json.dumps(
                    task, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode("utf-8") + b"\n"
                uncompressed_hash.update(task_line)
                gz.write(task_line)

                if progress_every and (index + 1) % progress_every == 0:
                    print(f"v3 corpus {index + 1}/{count}; elapsed={time.perf_counter()-started:.1f}s")

    family_owners = {}
    for split, hashes in split_family_sets.items():
        for family_hash in hashes:
            if family_hash in family_owners and family_owners[family_hash] != split:
                raise AssertionError("structural family leaked across data splits")
            family_owners[family_hash] = split

    unique_family_count = len(family_owners)
    family_counts = {split: len(hashes) for split, hashes in split_family_sets.items()}
    for left, right in (
        ("train", "development"),
        ("train", "confirmation"),
        ("development", "confirmation"),
    ):
        if split_family_sets[left] & split_family_sets[right]:
            raise AssertionError(f"{left}/{right} structural-family overlap")

    manifest = {
        "experiment": "P6-ESQ-V3-SYNTH-001",
        "generator_version": GENERATOR_VERSION,
        "base_seed": base_seed,
        "task_count": count,
        "visible_examples_per_task": 3,
        "max_program_arity": 2,
        "input_layout_contract": {
            "input_count": [1, 2],
            "at_least_one_list_input": True,
            "additional_input_type_choices": ["int", "list"],
            "input_order_shuffled": True,
            "scalar_range_inclusive": [0, 5],
            "list_element_ranges_inclusive": [[0, 4], [0, 9], [-10, 10], [-50, 50]],
            "list_length_ranges_inclusive": [[1, 3], [0, 5]],
        },
        "operator_count_range": [1, 6],
        "split_rule": "int(family_sha256[:8],16)%100: train<80, development<90, else confirmation",
        "split_task_counts": split_task_counts,
        "split_family_counts": family_counts,
        "unique_structural_families": unique_family_count,
        "split_family_disjoint": True,
        "input_arity_task_counts": {str(key): value for key, value in arity_counts.items()},
        "input_variable_type_counts": input_type_counts,
        "exedec_repository": "google-deepmind/exedec",
        "exedec_commit": EXEDEC_COMMIT,
        "exedec_source_blob_shas": EXEDEC_SOURCE_BLOBS,
        "frozen_official_confirmation_used": False,
        "raw_jsonl_gzip_path": str(path),
        "raw_jsonl_gzip_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "uncompressed_jsonl_sha256": uncompressed_hash.hexdigest(),
        "generation_seconds": round(time.perf_counter() - started, 3),
    }
    return {
        "values": values,
        "variable_mask": variable_mask,
        "operator_labels": operator_labels,
        "lambda_labels": lambda_labels,
        "length_labels": length_labels,
        "split_codes": split_codes,
        "family_hashes": family_hashes,
    }, manifest


def _positive_weights(labels):
    positives = torch.from_numpy(labels.sum(axis=0)).float()
    return ((labels.shape[0] - positives) / positives.clamp_min(1)).clamp(1.0, 30.0)


def _macro_f1(probabilities, labels):
    predicted = probabilities >= 0.5
    scores = []
    for column in range(labels.shape[1]):
        truth = labels[:, column].astype(bool)
        guess = predicted[:, column]
        true_positive = np.logical_and(truth, guess).sum()
        false_positive = np.logical_and(~truth, guess).sum()
        false_negative = np.logical_and(truth, ~guess).sum()
        denominator = 2 * true_positive + false_positive + false_negative
        if denominator:
            scores.append(2 * true_positive / denominator)
    return float(np.mean(scores)) if scores else 0.0


def train_v3_model(
    arrays,
    *,
    epochs=4,
    batch_size=256,
    learning_rate=1e-3,
    seed=20261116,
    progress=True,
):
    """Train only on train-family rows; use development rows for validation.

    Confirmation-family features, labels, and examples are never placed in the
    optimizer or validation tensors.
    """
    torch.manual_seed(seed)
    np.random.seed(seed)
    torch.set_num_threads(2)

    splits = arrays["split_codes"]
    train_indices = np.flatnonzero(splits == SPLIT_TO_CODE["train"])
    development_indices = np.flatnonzero(splits == SPLIT_TO_CODE["development"])
    confirmation_count = int(np.sum(splits == SPLIT_TO_CODE["confirmation"]))
    if len(train_indices) < 50 or len(development_indices) < 20 or confirmation_count < 1:
        raise ValueError("insufficient train/development/confirmation family rows")

    train = TensorDataset(
        torch.from_numpy(arrays["values"][train_indices]),
        torch.from_numpy(arrays["variable_mask"][train_indices]),
        torch.from_numpy(arrays["operator_labels"][train_indices]),
        torch.from_numpy(arrays["lambda_labels"][train_indices]),
        torch.from_numpy(arrays["length_labels"][train_indices]).long(),
    )
    loader = DataLoader(train, batch_size=batch_size, shuffle=True, num_workers=0)

    dev_values = torch.from_numpy(arrays["values"][development_indices])
    dev_mask = torch.from_numpy(arrays["variable_mask"][development_indices])
    dev_ops = arrays["operator_labels"][development_indices]
    dev_lambdas = arrays["lambda_labels"][development_indices]
    dev_lengths = torch.from_numpy(arrays["length_labels"][development_indices]).long()

    model = ESQSetEncoder()
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=1e-4)
    operator_loss = nn.BCEWithLogitsLoss(pos_weight=_positive_weights(arrays["operator_labels"][train_indices]))
    lambda_loss = nn.BCEWithLogitsLoss(pos_weight=_positive_weights(arrays["lambda_labels"][train_indices]))
    length_loss = nn.CrossEntropyLoss()

    history = []
    for epoch in range(epochs):
        model.train()
        total_loss = 0.0
        batch_count = 0
        for x, mask, op_target, lambda_target, length_target in loader:
            optimizer.zero_grad(set_to_none=True)
            output = model(x, mask)
            loss = (
                operator_loss(output["operator_logits"], op_target)
                + 0.75 * lambda_loss(output["lambda_logits"], lambda_target)
                + 0.20 * length_loss(output["length_logits"], length_target)
            )
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            total_loss += float(loss.detach())
            batch_count += 1

        model.eval()
        with torch.no_grad():
            output = model(dev_values, dev_mask)
            op_f1 = _macro_f1(torch.sigmoid(output["operator_logits"]).numpy(), dev_ops)
            lambda_f1 = _macro_f1(torch.sigmoid(output["lambda_logits"]).numpy(), dev_lambdas)
            length_accuracy = float(
                (output["length_logits"].argmax(-1) == dev_lengths).float().mean()
            )

        row = {
            "epoch": epoch + 1,
            "train_loss": total_loss / max(1, batch_count),
            "development_operator_macro_f1": op_f1,
            "development_lambda_macro_f1": lambda_f1,
            "development_length_accuracy": length_accuracy,
        }
        history.append(row)
        if progress:
            print(json.dumps(row, sort_keys=True))

    metadata = {
        "experiment": "P6-ESQ-V3-TRAIN-001",
        "model_name": "ESQSetEncoder",
        "trained_from_scratch": True,
        "seed": seed,
        "epochs": epochs,
        "batch_size": batch_size,
        "learning_rate": learning_rate,
        "device": "cpu",
        "train_task_count": int(len(train_indices)),
        "development_task_count": int(len(development_indices)),
        "confirmation_task_count_sealed": confirmation_count,
        "confirmation_rows_used_for_optimizer": 0,
        "confirmation_rows_used_for_validation": 0,
        "history": history,
    }
    return model, metadata


def save_v3_checkpoint(model, metadata, path="artifacts/esq_v3_model.pt"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": model.state_dict(), "metadata": metadata}, path)
    checkpoint_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    result = {
        **metadata,
        "checkpoint_path": str(path),
        "checkpoint_sha256": checkpoint_sha,
        "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
    }
    path.with_suffix(path.suffix + ".json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result
