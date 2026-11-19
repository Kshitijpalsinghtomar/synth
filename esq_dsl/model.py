"""Set encoder with a tree-structured candidate scorer; ESQ stays the exact executor."""

from __future__ import annotations
from typing import Sequence, Mapping
import torch
from torch import nn
from . import interpreter as core

OP_NAMES = tuple(core.OPS.keys())
LAMBDA_NAMES = tuple(core.LAMBDAS.keys())
OP_TO_ID = {name: i + 1 for i, name in enumerate(OP_NAMES)}
LAMBDA_TO_ID = {name: i + 1 for i, name in enumerate(LAMBDA_NAMES)}
MAX_PROGRAM_OPS = 6
MAX_TREE_TOKENS = 2 * MAX_PROGRAM_OPS + 1
TYPE_TO_ID = {"int": 1, "list": 2}


def _variable_id(name):
    return {"x0": 1, "x1": 2, "x2": 3}.get(name, 4)


def _pad(records):
    ops, lam, typ, arity, var = zip(*records) if records else ([], [], [], [], [])
    values = [list(ops), list(lam), list(typ), list(arity), list(var)]
    for seq in values:
        seq.extend([0] * (MAX_TREE_TOKENS - len(seq)))
        if len(seq) > MAX_TREE_TOKENS:
            raise ValueError("candidate expression exceeds six-operator tree limit")
    return tuple(values)


def node_token_ids(node):
    """Postorder serialization retains operator, lambda, type, arity and leaf identity."""
    records = []

    def visit(current):
        if current.kind == "var":
            records.append(
                (0, 0, TYPE_TO_ID[current.type], 0, _variable_id(current.name or ""))
            )
            return
        for child in current.children:
            visit(child)
        records.append(
            (
                OP_TO_ID[current.op or ""],
                LAMBDA_TO_ID.get(current.lambda_token or "", 0),
                TYPE_TO_ID[current.type],
                len(current.children),
                0,
            )
        )

    visit(node)
    return _pad(records)


def program_token_ids(program, input_types: Mapping[str, str] | None = None):
    ast = core.parse_program(program) if isinstance(program, str) else program
    definitions = {stmt.lhs: stmt for stmt in ast}
    if input_types is None:
        input_types = {"x0": "int", "x1": "list", "x2": "list"}
    records = []
    visiting = set()

    def visit(name):
        if name in visiting:
            raise ValueError(f"cyclic reference in candidate program at {name}")
        stmt = definitions.get(name)
        if stmt is None:
            raise ValueError(f"undefined candidate variable {name}")
        if stmt.op == "INPUT":
            if name not in input_types:
                raise ValueError(f"missing input type for {name}")
            records.append((0, 0, TYPE_TO_ID[input_types[name]], 0, _variable_id(name)))
            return
        visiting.add(name)
        for arg in stmt.args:
            visit(arg)
        visiting.remove(name)
        records.append(
            (
                OP_TO_ID[stmt.op],
                LAMBDA_TO_ID.get(stmt.lambda_token or "", 0),
                TYPE_TO_ID[core.OPS[stmt.op].out_type],
                len(stmt.args),
                0,
            )
        )

    if ast:
        visit(ast[-1].lhs)
    return _pad(records)


class ESQSetEncoder(nn.Module):
    def __init__(self, feature_dim=37, hidden_dim=64, embedding_dim=128, dropout=0.05):
        super().__init__()
        self.feature_dim = feature_dim
        self.variable_position = nn.Embedding(4, 8)
        self.value_encoder = nn.Sequential(
            nn.Linear(feature_dim + 8, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
        )
        self.example_encoder = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim), nn.GELU(), nn.LayerNorm(hidden_dim)
        )
        self.task_projection = nn.Sequential(
            nn.Linear(hidden_dim * 5, embedding_dim),
            nn.GELU(),
            nn.LayerNorm(embedding_dim),
            nn.Dropout(dropout),
            nn.Linear(embedding_dim, embedding_dim),
            nn.GELU(),
        )
        self.operator_head = nn.Linear(embedding_dim, len(OP_NAMES))
        self.lambda_head = nn.Linear(embedding_dim, len(LAMBDA_NAMES))
        self.length_head = nn.Linear(embedding_dim, MAX_PROGRAM_OPS)
        self.op_embedding = nn.Embedding(len(OP_NAMES) + 1, 24, padding_idx=0)
        self.lambda_embedding = nn.Embedding(len(LAMBDA_NAMES) + 1, 16, padding_idx=0)
        self.type_embedding = nn.Embedding(3, 8, padding_idx=0)
        self.arity_embedding = nn.Embedding(3, 4, padding_idx=0)
        self.variable_embedding = nn.Embedding(5, 4, padding_idx=0)
        self.tree_position = nn.Embedding(MAX_TREE_TOKENS, 8)
        self.candidate_gru = nn.GRU(64, 64, batch_first=True)
        self.candidate_head = nn.Sequential(
            nn.Linear(embedding_dim + 65, 128),
            nn.GELU(),
            nn.LayerNorm(128),
            nn.Dropout(dropout),
            nn.Linear(128, 64),
            nn.GELU(),
            nn.Linear(64, 1),
        )

    def encode(self, values, variable_mask):
        if values.ndim != 4 or values.shape[1:] != (3, 4, self.feature_dim):
            raise ValueError(f"expected (batch,3,4,{self.feature_dim}) task features")
        if variable_mask.shape != (values.shape[0], 4):
            raise ValueError("variable_mask must be (batch,4)")
        batch = values.shape[0]
        position = (
            self.variable_position(torch.arange(4, device=values.device))
            .view(1, 1, 4, -1)
            .expand(batch, 3, 4, -1)
        )
        encoded = self.value_encoder(torch.cat([values.float(), position], dim=-1))
        mask = variable_mask.float().view(batch, 1, 4, 1)
        mean = (encoded * mask).sum(dim=2) / mask.sum(dim=2).clamp_min(1.0)
        maximum = (
            encoded.masked_fill(mask == 0, torch.finfo(encoded.dtype).min)
            .max(dim=2)
            .values
        )
        maximum = torch.where(
            torch.isfinite(maximum), maximum, torch.zeros_like(maximum)
        )
        examples = self.example_encoder(torch.cat([mean, maximum], dim=-1))
        return self.task_projection(
            torch.cat(
                [
                    examples.reshape(
                        batch,
                        (
                            3 * self.value_encoder[-1].out_features
                            if hasattr(self.value_encoder[-1], "out_features")
                            else 192
                        ),
                    ),
                    examples.mean(dim=1),
                    examples.max(dim=1).values,
                ],
                dim=-1,
            )
        )

    def forward(self, values, variable_mask):
        emb = self.encode(values, variable_mask)
        return {
            "task_embedding": emb,
            "operator_logits": self.operator_head(emb),
            "lambda_logits": self.lambda_head(emb),
            "length_logits": self.length_head(emb),
        }

    def score_token_sequences(
        self,
        task_embedding,
        operator_ids,
        lambda_ids,
        type_ids,
        arity_ids,
        variable_ids,
    ):
        seqs = [operator_ids, lambda_ids, type_ids, arity_ids, variable_ids]
        if any(x.ndim != 2 or x.shape[1] != MAX_TREE_TOKENS for x in seqs):
            raise ValueError(
                f"candidate token batches must have shape (n,{MAX_TREE_TOKENS})"
            )
        count = operator_ids.shape[0]
        if any(x.shape[0] != count for x in seqs):
            raise ValueError("candidate token batch sizes differ")
        if task_embedding.shape[0] == 1 and count != 1:
            task_embedding = task_embedding.expand(count, -1)
        elif task_embedding.shape[0] != count:
            raise ValueError("task embedding batch must be one or match candidates")
        position = (
            self.tree_position(
                torch.arange(MAX_TREE_TOKENS, device=operator_ids.device)
            )
            .unsqueeze(0)
            .expand(count, -1, -1)
        )
        sequence = torch.cat(
            [
                self.op_embedding(operator_ids.long()),
                self.lambda_embedding(lambda_ids.long()),
                self.type_embedding(type_ids.long()),
                self.arity_embedding(arity_ids.long()),
                self.variable_embedding(variable_ids.long()),
                position,
            ],
            dim=-1,
        )
        lengths = (type_ids != 0).sum(dim=1)
        packed = nn.utils.rnn.pack_padded_sequence(
            sequence, lengths.clamp_min(1).cpu(), batch_first=True, enforce_sorted=False
        )
        _, hidden = self.candidate_gru(packed)
        candidate = hidden[-1]
        candidate = torch.where(
            lengths.unsqueeze(-1) > 0, candidate, torch.zeros_like(candidate)
        )
        fraction = lengths.float().unsqueeze(-1) / MAX_TREE_TOKENS
        return torch.sigmoid(
            self.candidate_head(
                torch.cat([task_embedding, candidate, fraction], dim=-1)
            )
        )

    @torch.no_grad()
    def score_nodes(self, task_embedding, nodes: Sequence[core.Node]):
        if not nodes:
            return []
        self.eval()
        tokens = [node_token_ids(node) for node in nodes]
        arrays = [
            torch.tensor(
                [token[j] for token in tokens],
                dtype=torch.long,
                device=task_embedding.device,
            )
            for j in range(5)
        ]
        scores = self.score_token_sequences(task_embedding, *arrays)
        return [float(v) for v in scores[:, 0].cpu().tolist()]

    @torch.no_grad()
    def score_programs(self, values, variable_mask, programs, input_types=None):
        if not programs:
            return torch.empty((0, 1), device=values.device)
        embedding = self.encode(values, variable_mask)
        tokens = [program_token_ids(program, input_types) for program in programs]
        arrays = [
            torch.tensor(
                [token[j] for token in tokens], dtype=torch.long, device=values.device
            )
            for j in range(5)
        ]
        return self.score_token_sequences(embedding, *arrays)

    @torch.no_grad()
    def predict_priors(self, values, variable_mask):
        self.eval()
        out = self(values, variable_mask)
        op = torch.sigmoid(out["operator_logits"])[0].cpu().tolist()
        lam = torch.sigmoid(out["lambda_logits"])[0].cpu().tolist()
        length = torch.softmax(out["length_logits"], dim=-1)[0].cpu().tolist()
        return dict(zip(OP_NAMES, op)), dict(zip(LAMBDA_NAMES, lam)), length
