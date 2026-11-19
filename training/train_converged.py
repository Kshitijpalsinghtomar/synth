from __future__ import annotations
import hashlib, json, platform, sys, time
from pathlib import Path
import os
import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

ROOT = Path(__file__).resolve().parents[1]
from esq_dsl.model import ESQSetEncoder, OP_NAMES, LAMBDA_NAMES

SEED=20261116
MAX_EPOCHS=20
PATIENCE=4
MIN_DELTA=1e-4
BATCH_SIZE=256
LEARNING_RATE=1e-3
DATA=ROOT/"artifacts"/"esq_v3_supervision_100k.npz"
SYNTH_MANIFEST=ROOT/"artifacts"/"esq_v3_synthetic_manifest.json"
OUT=ROOT/"checkpoints"
OUT.mkdir(parents=True,exist_ok=True)
CORPUS=ROOT/"artifacts"/"esq_v3_synthetic_tasks_100k.jsonl.gz"

def sha256_file(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""):
            digest.update(chunk)
    return digest.hexdigest()

for required in (DATA,SYNTH_MANIFEST,CORPUS):
    if not required.is_file(): raise FileNotFoundError(required)
synthetic_manifest=json.loads(SYNTH_MANIFEST.read_text(encoding="utf-8"))
if sha256_file(CORPUS) != synthetic_manifest.get("raw_jsonl_gzip_sha256"):
    raise ValueError("synthetic corpus SHA-256 does not match its manifest")
if sha256_file(DATA) != synthetic_manifest.get("supervision_npz_sha256"):
    raise ValueError("supervision NPZ SHA-256 does not match its manifest")
source_checks = {
    "generator_source_sha256": ROOT/"training"/"esq_data_v3.py",
    "training_source_sha256": ROOT/"training"/"esq_training_v3.py",
    "feature_source_sha256": ROOT/"esq_dsl"/"features.py",
    "model_source_sha256": ROOT/"esq_dsl"/"model.py",
}
for key, source_path in source_checks.items():
    expected = synthetic_manifest.get(key)
    if not isinstance(expected, str) or sha256_file(source_path) != expected:
        raise ValueError(f"{key} missing or does not match current source: {source_path}")
npz=np.load(DATA, allow_pickle=False)
arrays={name:npz[name] for name in npz.files}
splits=arrays["split_codes"]
train_idx=np.flatnonzero(splits==0)
dev_idx=np.flatnonzero(splits==1)
held_idx=np.flatnonzero(splits==2)
if not (len(train_idx)==79535 and len(dev_idx)==10546 and len(held_idx)==9919):
    raise AssertionError("expected frozen original family-disjoint v3 split")
if not bool(synthetic_manifest.get("split_family_disjoint")):
    raise AssertionError("synthetic manifest does not attest family-disjoint splits")
family_hashes = arrays.get("family_hashes")
if family_hashes is None or len(family_hashes) != len(splits):
    raise AssertionError("supervision NPZ must contain one family hash per task")
family_hashes = family_hashes.astype(str)
family_sets = [set(family_hashes[splits == code]) for code in (0, 1, 2)]
if any(family_sets[i] & family_sets[j] for i in range(3) for j in range(i+1, 3)):
    raise AssertionError("structural family overlap detected in supervision NPZ")
if len(set(family_hashes)) != 54649:
    raise AssertionError("unexpected unique structural-family count")
torch.manual_seed(SEED); np.random.seed(SEED); torch.set_num_threads(2)

train_ds=TensorDataset(
    torch.from_numpy(arrays["values"][train_idx]),
    torch.from_numpy(arrays["variable_mask"][train_idx]),
    torch.from_numpy(arrays["operator_labels"][train_idx]),
    torch.from_numpy(arrays["lambda_labels"][train_idx]),
    torch.from_numpy(arrays["length_labels"][train_idx]).long(),
)
loader=DataLoader(train_ds,batch_size=BATCH_SIZE,shuffle=True,num_workers=0)
dev_x=torch.from_numpy(arrays["values"][dev_idx])
dev_mask=torch.from_numpy(arrays["variable_mask"][dev_idx])
dev_ops=arrays["operator_labels"][dev_idx]
dev_lambdas=arrays["lambda_labels"][dev_idx]
dev_lengths=torch.from_numpy(arrays["length_labels"][dev_idx]).long()

def positive_weights(labels):
    positives=torch.from_numpy(labels.sum(axis=0)).float()
    return ((labels.shape[0]-positives)/positives.clamp_min(1)).clamp(1.0,30.0)

op_loss_fn=nn.BCEWithLogitsLoss(pos_weight=positive_weights(arrays["operator_labels"][train_idx]))
lambda_loss_fn=nn.BCEWithLogitsLoss(pos_weight=positive_weights(arrays["lambda_labels"][train_idx]))
length_loss_fn=nn.CrossEntropyLoss()

def combined_loss(out,ops,lambdas,lengths):
    return (
      op_loss_fn(out["operator_logits"],ops)
      +0.75*lambda_loss_fn(out["lambda_logits"],lambdas)
      +0.20*length_loss_fn(out["length_logits"],lengths)
    )

def multilabel_metrics(logits, labels):
    probs=torch.sigmoid(logits).cpu().numpy()
    pred=probs>=0.5
    truth=labels.astype(bool)
    tp=np.logical_and(pred,truth).sum(axis=0)
    fp=np.logical_and(pred,~truth).sum(axis=0)
    fn=np.logical_and(~pred,truth).sum(axis=0)
    f1=np.divide(2*tp,2*tp+fp+fn,out=np.zeros_like(tp,dtype=float),where=(2*tp+fp+fn)>0)
    micro_tp=int(tp.sum()); micro_fp=int(fp.sum()); micro_fn=int(fn.sum())
    micro_f1=(2*micro_tp/max(1,2*micro_tp+micro_fp+micro_fn))
    exact=float(np.all(pred==truth,axis=1).mean())
    bit_accuracy=float((pred==truth).mean())
    return {
      "macro_f1":float(f1.mean()),
      "micro_f1":float(micro_f1),
      "bit_accuracy":bit_accuracy,
      "exact_set_accuracy":exact
    }

model=ESQSetEncoder()
optimizer=torch.optim.AdamW(model.parameters(),lr=LEARNING_RATE,weight_decay=1e-4)
history=[]
best_loss=float("inf"); best_epoch=None; best_state=None; bad_epochs=0
started=time.perf_counter()
for epoch in range(1,MAX_EPOCHS+1):
    model.train(); total=0.0; batches=0
    for x,mask,op_target,lambda_target,length_target in loader:
        optimizer.zero_grad(set_to_none=True)
        out=model(x,mask)
        loss=combined_loss(out,op_target,lambda_target,length_target)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(),1.0)
        optimizer.step()
        total+=float(loss.detach()); batches+=1
    model.eval()
    with torch.no_grad():
        dev_out=model(dev_x,dev_mask)
        val_loss=float(combined_loss(
            dev_out,
            torch.from_numpy(dev_ops),
            torch.from_numpy(dev_lambdas),
            dev_lengths
        ))
    row={
      "epoch":epoch,
      "train_loss":total/max(1,batches),
      "validation_loss":val_loss,
      "validation_operator":multilabel_metrics(dev_out["operator_logits"],dev_ops),
      "validation_lambda":multilabel_metrics(dev_out["lambda_logits"],dev_lambdas),
      "validation_length_accuracy":float((dev_out["length_logits"].argmax(-1)==dev_lengths).float().mean())
    }
    history.append(row)
    print("EPOCH",json.dumps(row,sort_keys=True),flush=True)
    if val_loss < best_loss-MIN_DELTA:
        best_loss=val_loss; best_epoch=epoch
        best_state={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
        bad_epochs=0
    else:
        bad_epochs+=1
    if bad_epochs>=PATIENCE:
        print(f"EARLY_STOP epoch={epoch} best_epoch={best_epoch} patience={PATIENCE}",flush=True)
        break

if best_state is None: raise RuntimeError("training produced no best checkpoint")
model.load_state_dict(best_state); model.eval()
checkpoint_path=OUT/"esq_v3_converged.pt"
checkpoint_payload={
  "state_dict":best_state,
  "metadata":{
    "model_name":"ESQSetEncoder",
    "seed":SEED,
    "selected_epoch":best_epoch,
    "max_epochs":MAX_EPOCHS,
    "patience":PATIENCE,
    "batch_size":BATCH_SIZE,
    "learning_rate":LEARNING_RATE,
    "device":"cpu",
    "selection_metric":"development combined validation loss",
    "confirmation_rows_used_for_training":0,
    "confirmation_rows_used_for_validation":0,
  }
}
temporary_checkpoint = checkpoint_path.with_name(checkpoint_path.name + ".tmp")
torch.save(checkpoint_payload,temporary_checkpoint)
os.replace(temporary_checkpoint,checkpoint_path)
checkpoint_sha=sha256_file(checkpoint_path)
checkpoint_sha_path=checkpoint_path.with_suffix(checkpoint_path.suffix+".sha256")
temporary_sidecar = checkpoint_sha_path.with_name(checkpoint_sha_path.name + ".tmp")
temporary_sidecar.write_text(f"{checkpoint_sha}  {checkpoint_path.name}\n", encoding="utf-8")
os.replace(temporary_sidecar,checkpoint_sha_path)
total_params=sum(p.numel() for p in model.parameters())
active_prefixes=("variable_position.","value_encoder.","example_encoder.","task_projection.","operator_head.","lambda_head.","length_head.")
active_params=sum(p.numel() for name,p in model.named_parameters() if name.startswith(active_prefixes))
unused_params=total_params-active_params

# Confirmation split is opened only after the best checkpoint is frozen to disk.
hold_x=torch.from_numpy(arrays["values"][held_idx])
hold_mask=torch.from_numpy(arrays["variable_mask"][held_idx])
hold_ops=arrays["operator_labels"][held_idx]
hold_lambdas=arrays["lambda_labels"][held_idx]
hold_lengths=torch.from_numpy(arrays["length_labels"][held_idx]).long()
with torch.no_grad():
    hold_out=model(hold_x,hold_mask)
heldout={
  "operator":multilabel_metrics(hold_out["operator_logits"],hold_ops),
  "lambda":multilabel_metrics(hold_out["lambda_logits"],hold_lambdas),
  "program_length_accuracy":float((hold_out["length_logits"].argmax(-1)==hold_lengths).float().mean())
}
model_card={
 "model_name":"ESQSetEncoder",
 "model_version":"v3-prior-guide-release",
 "purpose":"Predict operator and lambda priors for branch-preserving symbolic search over the DeepCoder typed list/integer DSL",
 "device":"CPU",
 "parameter_count_total":total_params,
 "parameter_count_used_by_trained_prior_heads":active_params,
 "parameter_count_in_legacy_candidate_ranker_branch_not_optimized_by_this_objective":unused_params,
 "architecture":{
   "input_feature_shape":[3,4,37],
   "variable_position_embedding_dim":8,
   "value_encoder":["Linear(45,64)","GELU","LayerNorm(64)","Dropout(0.05)","Linear(64,64)","GELU"],
   "example_encoder":["Linear(128,64)","GELU","LayerNorm(64)"],
   "task_projection":["Linear(320,128)","GELU","LayerNorm(128)","Dropout(0.05)","Linear(128,128)","GELU"],
   "operator_head":{"outputs":len(OP_NAMES),"labels":list(OP_NAMES)},
   "lambda_head":{"outputs":len(LAMBDA_NAMES),"labels":list(LAMBDA_NAMES)},
   "length_head":{"outputs":6,"classes":[1,2,3,4,5,6]},
   "training_loss":"BCE(operator) + 0.75*BCE(lambda) + 0.20*cross_entropy(length)",
   "optimizer":"AdamW(weight_decay=1e-4)",
   "gradient_clip_norm":1.0
 },
 "training":{
   "seed":SEED,"epochs_run":len(history),"selected_epoch":best_epoch,
   "early_stopping":{"monitor":"development combined validation loss","patience":PATIENCE,"min_delta":MIN_DELTA},
   "batch_size":BATCH_SIZE,"learning_rate":LEARNING_RATE,
   "train_tasks":len(train_idx),"development_tasks":len(dev_idx),
   "sealed_confirmation_tasks":len(held_idx),
   "structural_family_split_disjoint":bool(synthetic_manifest.get("split_family_disjoint")),
   "confirmation_rows_used_for_optimizer":0,
   "confirmation_rows_used_for_model_selection":0,
   "history":history,
   "elapsed_seconds":round(time.perf_counter()-started,3)
 },
 "held_out_operator_lambda_prediction":{
   "split":"original v3 synthetic confirmation family split, evaluated after checkpoint freeze",
   "tasks":len(held_idx),
   "confirmation_rows_used_for_training":0,
   "confirmation_rows_used_for_validation":0,
   "metrics":heldout
 },
 "checkpoint":{"path":"checkpoints/esq_v3_converged.pt","sha256":checkpoint_sha,"sha256_sidecar":checkpoint_sha_path.name,"bytes":checkpoint_path.stat().st_size},
 "limitations":[
   "The guide predicts operation/lambda priors; it is not a program-output oracle.",
   "Search remains symbolic and branch-preserving; model scores reorder enumeration but do not prune valid branches.",
   "The legacy tree candidate-scoring branch is not used by v3 prior prediction and is not optimized by this training objective."
 ]
}
model_card["environment"] = {
 "python": platform.python_version(),
 "numpy": np.__version__,
 "torch": torch.__version__,
}
model_card["data_provenance"] = {
 "synthetic_manifest_sha256": sha256_file(SYNTH_MANIFEST),
 "synthetic_corpus_sha256": synthetic_manifest.get("raw_jsonl_gzip_sha256"),
 "supervision_npz_sha256": synthetic_manifest.get("supervision_npz_sha256"),
 "generator_source_sha256": synthetic_manifest.get("generator_source_sha256"),
 "training_source_sha256": synthetic_manifest.get("training_source_sha256"),
 "feature_source_sha256": synthetic_manifest.get("feature_source_sha256"),
 "model_source_sha256": synthetic_manifest.get("model_source_sha256"),
}
model_card["checkpoint"]["sha256_sidecar"] = checkpoint_sha_path.name
model_card["data_provenance"]["training_entrypoint_sha256"] = sha256_file(Path(__file__))
model_card["provenance_status"] = (
    "Complete for this checkpoint: synthetic corpus, supervision array, "
    "generator, trainer module, features, model, training entrypoint, "
    "checkpoint SHA-256, sidecar, and runtime versions are recorded."
)
temporary_card = OUT/"model_card.json.tmp"
temporary_card.write_text(json.dumps(model_card,indent=2) + "\n", encoding="utf-8")
os.replace(temporary_card,OUT/"model_card.json")
print("MODEL_CARD",json.dumps(model_card,indent=2),flush=True)
print("CHECKPOINT_SHA256",checkpoint_sha,flush=True)
print("MODEL_TRAINING_COMPLETE",flush=True)
