# KG BERT Ablation Experiment

This branch-local experiment compares FormOwl's deterministic non-BERT
candidate matching path with an optional BERT/SentenceTransformer embedding
path.

The experiment is intentionally candidate-only:

- it does not write canonical graph or canonical type state;
- it does not grant raw asset access;
- it uses a fixed labeled fixture set;
- it records dataset hash, thresholds, package availability, runtime, and
  quality metrics in JSON artifacts.

## Run

Non-BERT baseline plus optional BERT/SentenceTransformer run:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local \
  python experiments/kg_bert_ablation/run_ablation.py \
    --output experiments/kg_bert_ablation/results/kg_bert_ablation_latest.json
```

If `sentence_transformers` is not installed in the environment, the JSON still
records the non-BERT baseline and marks the BERT run as
`blocked_missing_dependency`.

To run the neural side after dependencies and model files are available:

```sh
FORMOWL_BERT_ABLATION_MODEL=sentence-transformers/bert-base-nli-mean-tokens \
docker run --rm \
  -v "$PWD:/workspace" \
  -v formowl-hf-cache:/models/huggingface \
  -w /workspace \
  formowl-kg-bert-cpu:local \
  python experiments/kg_bert_ablation/run_ablation.py \
    --output experiments/kg_bert_ablation/results/kg_bert_ablation_latest.json \
    --fail-if-bert-unavailable
```

`FORMOWL_BERT_ABLATION_MODEL` may point to a local model directory or a model
name resolvable by `sentence_transformers`.

Build the neural CPU runtime first:

```sh
docker build \
  -f containers/kg-bert-cpu/Dockerfile \
  -t formowl-kg-bert-cpu:local \
  .
```

For a GPU machine with NVIDIA Container Toolkit:

```sh
docker build \
  -f containers/kg-bert-gpu/Dockerfile \
  -t formowl-kg-bert-gpu:cu118 \
  .
```

```sh
FORMOWL_BERT_ABLATION_MODEL=sentence-transformers/bert-base-nli-mean-tokens \
docker run --rm --gpus all \
  -v "$PWD:/workspace" \
  -v formowl-hf-cache:/models/huggingface \
  -w /workspace \
  formowl-kg-bert-gpu:cu118 \
  python experiments/kg_bert_ablation/run_ablation.py \
    --output experiments/kg_bert_ablation/results/kg_bert_ablation_bert_gpu_cu118.json \
    --fail-if-bert-unavailable
```

## Metrics

The output records:

- precision, recall, F1, accuracy, true positives, false positives, true
  negatives, false negatives;
- total latency and pair throughput;
- per-pair scores and decisions;
- model/package availability;
- whether neural models were actually used.

Use the JSON artifact, not chat history, as the evidence for stakeholder
discussion.

## Current Branch Artifact

Current dev-container result:

```text
experiments/kg_bert_ablation/results/kg_bert_ablation_2026-06-29_devcontainer_no_bert_dependency.json
```

Observed non-BERT baseline on the fixed 16-pair fixture:

```text
precision=1.0
recall=0.1
f1=0.181818
accuracy=0.4375
```

The BERT/SentenceTransformer side is currently recorded as
`blocked_missing_dependency` because the default `formowl-dev:local` image does
not include `sentence_transformers`, `transformers`, or `torch`.

A temporary attempt to install `sentence-transformers` inside the dev container
started pulling large CUDA/PyTorch artifacts and was intentionally stopped. The
next real BERT run should use `containers/kg-bert-cpu/Dockerfile`, or a remote
model worker that exposes embeddings to this harness without changing the core
FormOwl dev container.

Current CPU neural result:

```text
experiments/kg_bert_ablation/results/kg_bert_ablation_bert_cpu.json
```

Observed CPU BERT/SentenceTransformer result on the same fixture:

```text
precision=0.888889
recall=0.8
f1=0.842105
accuracy=0.8125
```

Comparison against the lexical baseline:

```text
f1_delta_bert_minus_non_bert=0.660287
recall_delta_bert_minus_non_bert=0.7
precision_delta_bert_minus_non_bert=-0.111111
```

Current GPU runtime validation status:

```text
experiments/kg_bert_ablation/results/kg_bert_ablation_gpu_runtime_2026-06-29_blocked_nvidia_ldconfig.json
```

The host has GTX 1080 Ti GPUs, but `docker run --gpus all` is blocked before
FormOwl code starts by the NVIDIA Container Toolkit `ldconfig` path. Repair the
host GPU container runtime, then rerun the GPU command above and commit the
resulting `kg_bert_ablation_bert_gpu_cu118.json` artifact.
