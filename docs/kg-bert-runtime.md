# KG BERT Runtime

FormOwl supports neural candidate-generation runtimes for BERT or
SentenceTransformer-based KG experiments. These runtimes are optional and
separate from the normal dev container.

## Why It Is Separate

The default `formowl-dev:local` image is the canonical lightweight development
and test image. It should not silently grow PyTorch, Transformers, model caches,
or CUDA dependencies.

The BERT runtimes are separate because customer machines differ:

- low-spec machines should use deterministic and lexical candidate generation;
- standard CPU machines can run CPU-only embedding models;
- GPU or remote model workers can run larger BERT-family NER, relation
  extraction, local LLM graph extraction, or multimodal semantic adapters.

All of these paths must emit the same FormOwl candidate records and preserve the
same governance boundary.

## CPU Container

The CPU neural runtime is the lowest-common-denominator neural path. It works on
machines without NVIDIA Container Toolkit and is the fallback for small
customer deployments.

It lives at:

```text
containers/kg-bert-cpu/Dockerfile
containers/kg-bert-cpu/requirements.txt
```

Build it with:

```sh
docker build \
  -f containers/kg-bert-cpu/Dockerfile \
  -t formowl-kg-bert-cpu:local \
  .
```

Run the current BERT ablation harness:

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

## GPU Container

The GPU neural runtime lives at:

```text
containers/kg-bert-gpu/Dockerfile
containers/kg-bert-gpu/requirements.txt
```

It uses the official PyTorch CUDA image:

```text
pytorch/pytorch:2.5.1-cuda11.8-cudnn9-runtime
```

CUDA 11.8 is the conservative default for GTX 10-series style deployments.
Newer GPU worker images, such as CUDA 12.4, can be added later without removing
this compatibility path.

Build it with:

```sh
docker build \
  -f containers/kg-bert-gpu/Dockerfile \
  -t formowl-kg-bert-gpu:cu118 \
  .
```

The Dockerfile defaults to CUDA 11.8 / PyTorch 2.5.1, but it also supports
explicit build args for host-specific CUDA bases. This is useful when a customer
or test host already has a different compatible PyTorch CUDA image cached:

```sh
docker build \
  -f containers/kg-bert-gpu/Dockerfile \
  --build-arg FORMOWL_KG_BERT_GPU_BASE=pytorch/pytorch:2.10.0-cuda12.6-cudnn9-devel \
  --build-arg FORMOWL_KG_BERT_EXPECTED_TORCH_PREFIX=2.10.0 \
  --build-arg FORMOWL_KG_BERT_EXPECTED_CUDA=12.6 \
  -t formowl-kg-bert-gpu:cu126-host \
  .
```

Run the current BERT ablation harness on GPU:

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

For the host-specific CUDA 12.6 tag:

```sh
docker run --rm --gpus all \
  -v "$PWD:/workspace" \
  -v formowl-hf-cache:/models/huggingface \
  -w /workspace \
  formowl-kg-bert-gpu:cu126-host \
  python experiments/kg_bert_ablation/run_ablation.py \
    --output experiments/kg_bert_ablation/results/kg_bert_ablation_bert_gpu_cu126_host.json \
    --fail-if-bert-unavailable
```

The host must have a working NVIDIA driver and NVIDIA Container Toolkit. A
successful host `nvidia-smi` is not enough; `docker run --gpus all ...` must
also work.

On 2026-06-29 this host had two GTX 1080 Ti GPUs and driver `580.159.04`, but
GPU container startup was blocked before FormOwl code ran:

```text
nvidia-container-cli: ldcache error: open failed: /sbin/ldconfig.real: no such file or directory
```

The blocked validation artifact is preserved at:

```text
experiments/kg_bert_ablation/results/kg_bert_ablation_gpu_runtime_2026-06-29_blocked_nvidia_ldconfig.json
```

This is a host NVIDIA Container Toolkit configuration problem, not a BERT or KG
algorithm result.

The model defaults to:

```text
sentence-transformers/bert-base-nli-mean-tokens
```

Override it with `FORMOWL_BERT_ABLATION_MODEL`, either as a HuggingFace model
name or as a mounted local model directory.

## Artifact Rules

Every BERT vs non-BERT comparison must preserve a JSON artifact under:

```text
experiments/kg_bert_ablation/results/
```

The artifact must record:

- dataset id and dataset hash;
- model name or local model path;
- package availability and versions;
- torch version, CUDA availability, CUDA version, and visible device names;
- precision, recall, F1, accuracy, TP, FP, TN, FN;
- latency and pair throughput;
- candidate-only claim boundary;
- whether BERT actually ran or was blocked.

Do not use chat history, terminal screenshots, or untracked notebooks as the
source of truth for performance claims.

## Governance Boundary

The BERT runtime may generate:

- embeddings;
- semantic similarity scores;
- semantic metadata;
- candidate atoms;
- candidate relations;
- fusion candidates;
- type-alignment candidates.

It must not:

- mutate canonical graph state;
- mutate canonical type state;
- grant raw asset access;
- expose raw NAS, object-store, database, SQL, or worker scratch paths;
- replace the four-specialist adjudication route where reviewer evidence is
  required.

## Current State

The experiment branch currently has:

- a non-BERT baseline artifact from the default dev container;
- a completed CPU BERT/SentenceTransformer artifact from
  `formowl-kg-bert-cpu:local`;
- a completed host GPU BERT/SentenceTransformer artifact from
  `formowl-kg-bert-gpu:cu126-host`;
- a historical GPU runtime validation blocker artifact from before the host
  NVIDIA Container Toolkit fix.

The completed CPU BERT artifact is:

```text
experiments/kg_bert_ablation/results/kg_bert_ablation_bert_cpu.json
```

Observed fixture result:

```text
non-BERT lexical: precision=1.0, recall=0.1, f1=0.181818, accuracy=0.4375
CPU BERT + core type gate: precision=1.0, recall=0.8, f1=0.888889, accuracy=0.875
GPU BERT + core type gate: precision=1.0, recall=0.8, f1=0.888889, accuracy=0.875
```

The completed host GPU BERT artifact is:

```text
experiments/kg_bert_ablation/results/kg_bert_ablation_bert_gpu_cu126_host.json
```

It records `model_device=cuda:0`, `torch=2.10.0+cu126`, CUDA 12.6 available,
and two visible `NVIDIA GeForce GTX 1080 Ti` devices.

The current BERT algorithm is
`sentence_transformer_cosine_similarity_with_core_type_gate_v2`: BERT cosine
similarity proposes semantic matches, but ontology core-supertype compatibility
can still block a match. This removes the fixture's previous false positive
where identical text `Maya Chen` was wrongly matched across `Person` and
`Project`.

On the small 16-pair fixture, GPU total runtime is not faster because model
load and CUDA initialization dominate the run. The current recorded timing is:

```text
CPU BERT: total=119943.05ms, model_load=119794.55ms, embedding=145.185ms
GPU BERT: total=156686.003ms, model_load=156482.759ms, embedding=200.693ms
```

Do not claim GPU end-to-end latency superiority from this small fixture alone.
For throughput claims, add a larger batched fixture or repeat/stress benchmark
and preserve its JSON artifact.

The GPU base image manifest for
`pytorch/pytorch:2.5.1-cuda11.8-cudnn9-runtime` resolved successfully on
2026-06-29. The local image build was stopped after a slow registry download of
the 3.17GB base layer; this was not a Dockerfile or dependency failure.
