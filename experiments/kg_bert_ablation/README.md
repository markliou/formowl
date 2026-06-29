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
FORMOWL_BERT_ABLATION_MODEL_PROFILE=legacy_cpu_bert \
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
name resolvable by `sentence_transformers`. The CPU neural runtime intentionally
keeps the previous `legacy_cpu_bert` profile for customers who need neural
matching without GPU hardware.

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

For this host, a cached PyTorch CUDA 12.6 base image can build a host-specific
tag without waiting for the CUDA 11.8 base image download:

```sh
docker build \
  -f containers/kg-bert-gpu/Dockerfile \
  --build-arg FORMOWL_KG_BERT_GPU_BASE=pytorch/pytorch:2.10.0-cuda12.6-cudnn9-devel \
  --build-arg FORMOWL_KG_BERT_EXPECTED_TORCH_PREFIX=2.10.0 \
  --build-arg FORMOWL_KG_BERT_EXPECTED_CUDA=12.6 \
  -t formowl-kg-bert-gpu:cu126-host \
  .
```

```sh
FORMOWL_BERT_ABLATION_MODEL_PROFILE=gpu_bge_large_en_v1_5 \
FORMOWL_BERT_ABLATION_MODEL=BAAI/bge-large-en-v1.5 \
docker run --rm --gpus all \
  -v "$PWD:/workspace" \
  -v formowl-hf-cache:/models/huggingface \
  -w /workspace \
  formowl-kg-bert-gpu:cu118 \
  python experiments/kg_bert_ablation/run_ablation.py \
    --output experiments/kg_bert_ablation/results/kg_bert_ablation_bge_large_gpu_cu118.json \
    --fail-if-bert-unavailable
```

For this host-specific tag:

```sh
FORMOWL_BERT_ABLATION_MODEL_PROFILE=gpu_bge_large_en_v1_5 \
FORMOWL_BERT_ABLATION_MODEL=BAAI/bge-large-en-v1.5 \
docker run --rm --gpus all \
  -v "$PWD:/workspace" \
  -v formowl-hf-cache:/models/huggingface \
  -w /workspace \
  formowl-kg-bert-gpu:cu126-host \
  python experiments/kg_bert_ablation/run_ablation.py \
    --output experiments/kg_bert_ablation/results/kg_bert_ablation_bge_large_gpu_cu126_host.json \
    --fail-if-bert-unavailable
```

The GPU profile floor is one NVIDIA GeForce GTX 1080 Ti class GPU with 11GB
VRAM. The old `sentence-transformers/bert-base-nli-mean-tokens` path remains
available through `--model-profile legacy_cpu_bert` or the CPU container
environment above. The BGE profile uses threshold `0.62` by default; override
with `--bert-threshold` when running a calibration or ablation.

## Metrics

The output records:

- precision, recall, F1, accuracy, true positives, false positives, true
  negatives, false negatives;
- total latency and pair throughput;
- per-pair scores and decisions;
- model/package availability;
- model profile, intended runtime, and minimum GPU floor where applicable;
- whether neural models were actually used.

Use the JSON artifact, not chat history, as the evidence for stakeholder
discussion.

## Large Benchmark Source Pool

The current fixed 16-pair fixture is only a smoke/regression benchmark. It is
not large enough for model selection.

The selected larger public enterprise benchmark manifest is:

```text
experiments/kg_bert_ablation/public_enterprise_benchmark_manifest.json
```

It targets at least 10,000 labeled pairs for model selection and 50,000 pairs
for stakeholder-facing evidence. The source families are mail/conversation,
office documents, financial QA, SEC financial reports, and contract documents.
The manifest artifact itself only selects and constrains the benchmark; run
artifacts below are the evidence that the 10,000-pair and 50,000-pair datasets
were actually executed.

## Public Enterprise Benchmark Run

The first public enterprise model-selection run is now preserved at:

```text
experiments/kg_bert_ablation/results/kg_public_enterprise_benchmark_2026-06-29_bge_gpu_cu126_host.json
```

It builds 10,000 labeled candidate pairs from public sources:

```text
contract_document=7000
financial_report=3000
positive_pairs=4976
negative_pairs=5024
```

The current runner source-locks CUAD, SEC company tickers, FiQA, Enron, and
RVL-CDIP, but only CUAD and SEC are used as labeled pairs in this first result.
FiQA, Enron, and RVL-CDIP remain locked/probed source families for later qrel,
mail-label, or OCR builders.

Run command used for the completed host GPU artifact:

```sh
docker run --rm --gpus 'device=0' \
  -e CUDA_VISIBLE_DEVICES=0 \
  -e TOKENIZERS_PARALLELISM=false \
  -e FORMOWL_BERT_ABLATION_MODEL_PROFILE=gpu_bge_large_en_v1_5 \
  -e FORMOWL_BERT_ABLATION_MODEL=BAAI/bge-large-en-v1.5 \
  -v "$PWD:/workspace" \
  -v formowl-hf-cache:/models/huggingface \
  -w /workspace \
  formowl-kg-bert-gpu:cu126-host \
  python experiments/kg_bert_ablation/run_public_benchmark.py \
    --mode both \
    --pair-limit 10000 \
    --embedding-model BAAI/bge-large-en-v1.5 \
    --embedding-threshold 0.62 \
    --embedding-batch-size 8 \
    --output experiments/kg_bert_ablation/results/kg_public_enterprise_benchmark_2026-06-29_bge_gpu_cu126_host.json \
    --fail-if-embedding-unavailable
```

The earlier batch-size-32 attempt failed around 60% with a CUDA illegal memory
access on this GTX 1080 Ti host. The single-GPU batch-size-8 run completed.

| Run | NN | Threshold | Accuracy | Precision | Recall | F1 | TP | FP | TN | FN | Total latency | Throughput |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| lexical baseline | no | 0.70 | 0.5216 | 0.940367 | 0.041198 | 0.078937 | 205 | 13 | 5011 | 4771 | 2654.877 ms | 3766.652 pairs/s |
| BGE large GPU | yes | 0.62 | 0.7183 | 0.931627 | 0.468248 | 0.623245 | 2330 | 171 | 4853 | 2646 | 418861.960 ms | 23.874 pairs/s |

Delta from lexical to BGE GPU:

```text
accuracy +0.196700
f1       +0.544308
recall   +0.427050
precision -0.008740
```

BGE's total latency includes model download/cache preparation and model load.
The recorded BGE latency breakdown is:

```text
model_load=313152.923ms
embedding=103680.571ms
scoring=2024.413ms
```

The 10,000-pair chart is preserved at:

```text
experiments/kg_bert_ablation/results/charts/kg_public_enterprise_benchmark_2026-06-29_bge_gpu_cu126_host_metrics.svg
```

This 10,000-pair result is model-selection evidence, not stakeholder-grade or
production readiness evidence. It is candidate-only, writes no canonical
graph/type state, grants no raw access, and does not exercise the 50,000-pair
stakeholder target. The CUAD and SEC labels are deterministic public labels
with known limitations, not completed human adjudication.

## 50,000-Pair Stakeholder Benchmark

The 50,000-pair public enterprise benchmark is now preserved at:

```text
experiments/kg_bert_ablation/results/kg_public_enterprise_benchmark_2026-06-29_bge_gpu_50k_cu126_host.json
```

It builds 50,000 labeled candidate pairs from public sources:

```text
contract_document=22500
financial_report=15000
financial_qa=12500
positive_pairs=24837
negative_pairs=25163
```

Run command used for the completed host GPU artifact:

```sh
docker run --rm --gpus 'device=0' \
  -e CUDA_VISIBLE_DEVICES=0 \
  -e TOKENIZERS_PARALLELISM=false \
  -e FORMOWL_BERT_ABLATION_MODEL_PROFILE=gpu_bge_large_en_v1_5 \
  -e FORMOWL_BERT_ABLATION_MODEL=BAAI/bge-large-en-v1.5 \
  -v "$PWD:/workspace" \
  -v formowl-hf-cache:/models/huggingface \
  -w /workspace \
  formowl-kg-bert-gpu:cu126-host \
  python experiments/kg_bert_ablation/run_public_benchmark.py \
    --mode both \
    --pair-limit 50000 \
    --embedding-model BAAI/bge-large-en-v1.5 \
    --embedding-threshold 0.62 \
    --embedding-batch-size 8 \
    --output experiments/kg_bert_ablation/results/kg_public_enterprise_benchmark_2026-06-29_bge_gpu_50k_cu126_host.json \
    --fail-if-embedding-unavailable
```

| Run | NN | Threshold | Accuracy | Precision | Recall | F1 | TP | FP | TN | FN | Total latency | Throughput |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| lexical baseline | no | 0.70 | 0.5225 | 0.921930 | 0.042316 | 0.080918 | 1051 | 89 | 25074 | 23786 | 10171.713 ms | 4915.593 pairs/s |
| BGE large GPU | yes | 0.62 | 0.79986 | 0.945935 | 0.633289 | 0.758664 | 15729 | 899 | 24264 | 9108 | 783070.479 ms | 63.851 pairs/s |

Delta from lexical to BGE GPU:

```text
accuracy +0.277360
f1       +0.677746
recall   +0.590973
precision +0.024005
```

The 50,000-pair chart is preserved at:

```text
experiments/kg_bert_ablation/results/charts/kg_public_enterprise_benchmark_2026-06-29_bge_gpu_50k_cu126_host_metrics.svg
```

The artifact sets `stakeholder_grade_claim=true` because it reaches the
manifest's 50,000-pair evidence target. This is still candidate-only benchmark
evidence: it does not claim production readiness, production latency,
canonical graph/type writes, raw-access grants, or completed human
adjudication.

## Ontology Ablation

The ontology-guidance ablation is now preserved at:

```text
experiments/kg_bert_ablation/results/kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host.json
```

It uses 20,000 pairs:

```text
contract_document=4500
financial_report=3000
financial_qa=2500
ontology_stress=10000
positive_pairs=4956
negative_pairs=15044
```

The `ontology_stress` slice contains cross-type hard negatives with the same
surface label across incompatible core supertypes. This makes the ontology
effect measurable without granting access or mutating canonical type state.

| Run | Accuracy | Precision | Recall | F1 | FP | Stress FP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| lexical only | 0.2618 | 0.020063 | 0.041364 | 0.027020 | 10013 | 10000 |
| lexical + hard ontology gate | 0.7618 | 0.940367 | 0.041364 | 0.079242 | 13 | 0 |
| BGE only | 0.3999 | 0.235272 | 0.631759 | 0.342860 | 10177 | 10000 |
| BGE + hard ontology gate | 0.8999 | 0.946493 | 0.631759 | 0.757744 | 177 | 0 |
| BGE + soft ontology score | 0.8999 | 0.946493 | 0.631759 | 0.757744 | 177 | 0 |

Ontology guidance improves BGE by:

```text
accuracy +0.500000
f1       +0.414884
precision +0.711221
recall   +0.000000
false_positive -10000
```

The ontology charts are preserved at:

```text
experiments/kg_bert_ablation/results/charts/kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host_metrics.svg
experiments/kg_bert_ablation/results/charts/kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host_ontology_stress.svg
```

This is ablation evidence only. It demonstrates that ontology/type compatibility
materially reduces cross-type false positives, but it does not create canonical
ontology definitions, write canonical graph state, grant raw access, or prove
production matching quality by itself.

## Current Branch Artifact

Current dev-container result:

```text
experiments/kg_bert_ablation/results/kg_bert_ablation_2026-06-29_devcontainer_bge_manifest_no_bert_dependency.json
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

Observed CPU BERT/SentenceTransformer plus core-type gate result on the same
fixture:

```text
precision=1.0
recall=0.8
f1=0.888889
accuracy=0.875
false_positive=0
```

This CPU artifact uses the legacy CPU BERT profile:

```text
legacy_cpu_bert -> sentence-transformers/bert-base-nli-mean-tokens
```

Current host GPU neural result:

```text
experiments/kg_bert_ablation/results/kg_bert_ablation_bert_gpu_cu126_host.json
```

Observed GPU BERT/SentenceTransformer plus core-type gate result on the same
fixture:

```text
precision=1.0
recall=0.8
f1=0.888889
accuracy=0.875
false_positive=0
model_device=cuda:0
torch=2.10.0+cu126
cuda_available=true
visible_devices=2 x NVIDIA GeForce GTX 1080 Ti
```

This recorded GPU artifact is historical evidence from the previous model. The
new GPU default profile is:

```text
gpu_bge_large_en_v1_5 -> BAAI/bge-large-en-v1.5
default_threshold=0.62
minimum_gpu=NVIDIA GeForce GTX 1080 Ti
minimum_vram_gb=11
```

Current host GPU BGE artifact:

```text
experiments/kg_bert_ablation/results/kg_bert_ablation_bge_large_gpu_cu126_host.json
```

Observed small-fixture result:

```text
precision=1.0
recall=0.9
f1=0.947368
accuracy=0.9375
threshold=0.62
model_device=cuda:0
visible_devices=2 x NVIDIA GeForce GTX 1080 Ti
```

This is evidence that the upgraded model/profile works on the local GPU floor,
but it is still a 16-pair fixture result. Use the public enterprise benchmark
manifest before claiming stakeholder-grade model superiority.

The type gate prevents pure BERT string/semantic similarity from merging
different ontology core supertypes. In the fixture, `Maya Chen` vs `Maya Chen`
keeps its raw cosine score of `1.0`, but it is correctly marked
`type_mismatch` because the left side is `Person` and the right side is
`Project`.

On this small 16-pair fixture, total runtime is dominated by model load and
CUDA initialization, not embedding. The current recorded breakdown is:

```text
CPU BERT: total=119943.05ms, model_load=119794.55ms, embedding=145.185ms
GPU BERT: total=156686.003ms, model_load=156482.759ms, embedding=200.693ms
```

Interpretation: this fixture is too small and too startup-heavy for GPU latency
claims. Use the JSON artifacts for exact comparison and do not claim GPU
end-to-end latency is faster from this small fixture alone.

Comparison against the lexical baseline:

```text
accuracy_delta_bert_minus_non_bert=0.4375
f1_delta_bert_minus_non_bert=0.707071
recall_delta_bert_minus_non_bert=0.7
precision_delta_bert_minus_non_bert=0.0
```

Historical GPU runtime validation blocker:

```text
experiments/kg_bert_ablation/results/kg_bert_ablation_gpu_runtime_2026-06-29_blocked_nvidia_ldconfig.json
```

The host previously had GTX 1080 Ti GPUs but `docker run --gpus all` was
blocked before FormOwl code started by the NVIDIA Container Toolkit `ldconfig`
path. That host issue was fixed by the operator, and the GPU artifact above now
supersedes the blocker for this host.

## Package API For Integration

The experiment artifacts are available through the packaged KG evaluation
facade so downstream agents do not need to parse the large JSON files directly:

```sh
python -m formowl_kg_eval benchmarks
python -m formowl_kg_eval summary
```

Python API:

```python
from formowl_kg_eval import build_benchmark_summary

benchmarks = build_benchmark_summary(repository_root="/workspace")
```

`build_benchmark_summary()` returns dataset counts, metrics, deltas, claim
boundaries, and repo-relative SVG chart paths. It intentionally omits
`pair_result_sample` and raw labels. The API remains candidate-only research
evidence: it grants no raw access and writes no canonical graph or type state.
