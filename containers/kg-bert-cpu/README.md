# FormOwl KG BERT CPU Container

This container is the reproducible CPU runtime for FormOwl KG neural
candidate-generation experiments. It is separate from `formowl-dev:local` so
the normal development image stays lightweight and non-neural deployments do
not inherit large ML dependencies.

Use this image for low-spec or NVIDIA-free customer machines. Use
`containers/kg-bert-gpu/Dockerfile` when a customer deployment has a working
NVIDIA driver and Docker GPU runtime.

This image intentionally preserves the legacy CPU neural profile:

```text
FORMOWL_BERT_ABLATION_MODEL_PROFILE=legacy_cpu_bert
FORMOWL_BERT_ABLATION_MODEL=sentence-transformers/bert-base-nli-mean-tokens
```

The newer GPU default model is not forced onto CPU-only customer machines. The
legacy CPU profile keeps threshold `0.70`.

## Build

```sh
docker build \
  -f containers/kg-bert-cpu/Dockerfile \
  -t formowl-kg-bert-cpu:local \
  .
```

The Dockerfile installs CPU-only PyTorch from the official PyTorch CPU wheel
index, then installs the shared pinned packages in
`containers/kg-bert-requirements.txt`.

## Run The Ablation

```sh
docker run --rm \
  -v "$PWD:/workspace" \
  -v formowl-hf-cache:/models/huggingface \
  -w /workspace \
  formowl-kg-bert-cpu:local \
  python experiments/kg_bert_ablation/run_ablation.py \
    --output experiments/kg_bert_ablation/results/kg_bert_ablation_bert_cpu.json \
    --fail-if-bert-unavailable
```

Override the model with:

```sh
-e FORMOWL_BERT_ABLATION_MODEL_PROFILE=legacy_cpu_bert
-e FORMOWL_BERT_ABLATION_MODEL=sentence-transformers/bert-base-nli-mean-tokens
```

`FORMOWL_BERT_ABLATION_MODEL` may also point to a mounted local model directory
for offline customer deployments.

## Customer Deployment Rule

Do not install `sentence-transformers`, `transformers`, or `torch` ad hoc on a
customer machine. Build or publish this image, preload or mount the model cache,
then run the same ablation command and preserve the JSON output artifact.

The runtime remains candidate-only. It may produce embeddings, semantic
similarity scores, candidate atoms, candidate relations, fusion candidates, or
type-alignment candidates. It must not write canonical graph/type state or
grant raw asset access.

Policy sentence: neural candidate-generation containers must not write
canonical graph/type state and must not grant raw asset access.
