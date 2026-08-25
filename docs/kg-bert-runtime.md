# KG Embedding and Model Runtime

This document describes optional model containers and the active role boundary
for embeddings, rerankers, planners, extractors, and answer generation. The
current research program is issue #56. Model runtime evidence is candidate-only
unless an accepted execution manifest states otherwise.

## Role Separation

FormOwl must record model roles separately:

```text
planner
candidate extractor / entity linker
embedding
reranker
final answer generator
```

An embedding model is not an ontology, answer model, permission authority, or
canonical truth source. Every comparison arm uses the same final answer model
and settings.

## CPU Container

The historical CPU experiment remains reproducible:

```sh
docker build \
  -f containers/kg-bert-cpu/Dockerfile \
  -t formowl-kg-bert-cpu:local \
  .

docker run --rm \
  -v "$PWD:/workspace" \
  -w /workspace \
  formowl-kg-bert-cpu:local \
  python experiments/kg_bert_ablation/run_ablation.py
```

It pins `sentence-transformers/bert-base-nli-mean-tokens`. This is a legacy CPU
fallback and not the active multilingual target.

## GPU Container

The historical GPU candidate-generation profile uses
`BAAI/bge-large-en-v1.5` and assumes at least a GTX 1080 Ti class 11GB device.

CUDA 11.8 image:

```sh
docker build \
  -f containers/kg-bert-gpu/Dockerfile \
  -t formowl-kg-bert-gpu:cu118 \
  .

docker run --rm --gpus all \
  -v "$PWD:/workspace" \
  -w /workspace \
  formowl-kg-bert-gpu:cu118 \
  python experiments/kg_bert_ablation/run_ablation.py \
  --output experiments/kg_bert_ablation/results/kg_bert_ablation_bge_large_gpu_cu118.json
```

CUDA 12.6 host-compatible image:

```sh
docker build \
  --build-arg FORMOWL_KG_BERT_GPU_BASE=pytorch/pytorch:2.5.1-cuda12.6-cudnn9-runtime \
  --build-arg FORMOWL_KG_BERT_EXPECTED_CUDA=12.6 \
  -f containers/kg-bert-gpu/Dockerfile \
  -t formowl-kg-bert-gpu:cu126-host \
  .

docker run --rm --gpus all \
  -v "$PWD:/workspace" \
  -w /workspace \
  formowl-kg-bert-gpu:cu126-host \
  python experiments/kg_bert_ablation/run_ablation.py \
  --output experiments/kg_bert_ablation/results/kg_bert_ablation_bge_large_gpu_cu126_host.json
```

The active commands intentionally do not overwrite old BERT result names.

## Issue #56 Runtime Rules

- The frozen query/evidence tokenizer is
  `jieba_sentencepiece_frozen_profile_candidate_admission_v1`; BGE tokenization
  does not replace that retrieval-profile authority.
- Embeddings are built only from authorized Observations and carry source,
  profile, model, index, and permission-view revisions.
- Changing an embedding or reranker model creates a new arm/version.
- Strong RAG and graph-guided arms use identical embedding/reranker settings
  unless the model itself is the declared factor.
- Final answer generation is evaluated separately from candidate matching.
- No model output may write canonical graph/type state or grant access.

## Artifact Manifest

A model artifact records:

```text
profile id
model repository/name and exact revision
model/config/tokenizer file hashes
framework and dependency locks
container image digest
hardware class
input Observation/source manifest
permission/effective-view revision
index revision
prompt/schema/settings hashes, when applicable
output artifact hashes
```

Missing or mutable model identity makes the report diagnostic only.

## Historical Compatibility Evidence — Not Active Methodology

The following markers remain for repository compatibility tests and traceability:

- `kg_public_enterprise_benchmark_2026-06-29_bge_gpu_cu126_host.json` reported
  BGE candidate F1 `0.623245` as model-selection evidence.
- `kg_public_enterprise_benchmark_2026-06-29_bge_gpu_50k_cu126_host.json`
  reported candidate F1 `0.758664`.
- `kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host.json` reported historical
  candidate-only F1 `0.757744` in an artificial cross-type stress setup.

These are not same-pipeline final-answer comparisons against strong RAG. The
historical hard gate is not the active retrieval policy.

Historical result file names still referenced by container tests include:

```text
kg_bert_ablation_bge_large_gpu_cu118.json
kg_bert_ablation_bge_large_gpu_cu126_host.json
```

## Governance Boundary

Model runtimes:

- may generate embeddings, candidates, proposed plans, and cited answer drafts;
- must not write canonical graph/type state;
- must not grant raw asset access;
- must not infer authorization from similarity;
- must not receive independent holdout answers or unrelated private evidence;
- must not expose raw paths, credentials, storage/parser internals, or oracle
  values in public artifacts.

PostgreSQL/pgvector remains the canonical baseline. No Neo4j migration or dual
write is part of this runtime plan.

## Current State

The current production query path has not migrated to the frozen Hybrid-v2
profile, and no production answer LLM is authorized by this document. Run
`python3 scripts/methodology_authority_check.py --require-ready` before any
methodology-quality claim; it is expected to remain nonzero until all gates are
satisfied.
