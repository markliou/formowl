# FormOwl KG BERT GPU Container

This container is the CUDA runtime for FormOwl KG neural candidate-generation
experiments. It is separate from `formowl-dev:local` and from the CPU neural
image so customer deployments can choose the right runtime for the available
hardware.

The default GPU image uses PyTorch 2.5.1 with CUDA 11.8:

```text
pytorch/pytorch:2.5.1-cuda11.8-cudnn9-runtime
```

CUDA 11.8 is the conservative default for GTX 10-series and other older NVIDIA
deployments. Newer GPU worker images can be added later, for example CUDA 12.4,
without replacing this compatibility path.

## Build

```sh
docker build \
  -f containers/kg-bert-gpu/Dockerfile \
  -t formowl-kg-bert-gpu:cu118 \
  .
```

## Run The Ablation

```sh
docker run --rm --gpus all \
  -v "$PWD:/workspace" \
  -v formowl-hf-cache:/models/huggingface \
  -w /workspace \
  formowl-kg-bert-gpu:cu118 \
  python experiments/kg_bert_ablation/run_ablation.py \
    --output experiments/kg_bert_ablation/results/kg_bert_ablation_bert_gpu_cu118.json \
    --fail-if-bert-unavailable
```

Override the model with:

```sh
-e FORMOWL_BERT_ABLATION_MODEL=sentence-transformers/bert-base-nli-mean-tokens
```

`FORMOWL_BERT_ABLATION_MODEL` may also point to a mounted local model directory
for offline customer deployments.

## Host Requirements

The host must have:

- an NVIDIA driver compatible with CUDA 11.8 containers;
- NVIDIA Container Toolkit configured for Docker;
- `docker run --gpus all ...` working before FormOwl-specific tests are run.

If `nvidia-smi` works on the host but `docker run --gpus all` fails, fix the
host NVIDIA Container Toolkit first. That is a host runtime problem, not a KG
algorithm result.

## Governance Boundary

The runtime remains candidate-only. It may produce embeddings, semantic
similarity scores, candidate atoms, candidate relations, fusion candidates, or
type-alignment candidates. It must not write canonical graph/type state and
must not grant raw asset access.
