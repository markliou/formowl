# KG BERT Runtime

FormOwl supports neural candidate-generation runtimes for BERT or
SentenceTransformer-based KG experiments. These runtimes are optional and
separate from the normal dev container.

## Default Candidate Evidence Retrieval

Neural similarity changes candidate features; it does not replace the default
retrieval contract. End-task harnesses still count logical source items, apply
access/context/time before query planning, forbid lexical transitive closure,
and use ontology only as a capped additive rerank. The BGE-only, soft-score,
and hard-gate results below are historical model-selection ablations, not the
active retrieval default.
End-task indexes own a `CandidateEvidenceTextPolicyRuntime` for the
Unicode-NFKC/protected-ASCII/Jieba/corpus-bound SentencePiece/frozen-profile
stack and exact admission/model/corpus SHA-256 hashes. The binding also pins
the runtime id and tokenizer implementation hash; runtime code mismatch fails
closed. Default callers pass query text only; an embedding runtime cannot
replace the binding with raw tokens or a free-form hash. Access and explicit
context/time admissibility precede tokenization; experiments use
`retrieve_ablation`.
Raw query text may identify control intent, evidence count, and chronology
syntax only. Retrieval anchors, actor/topic vocabulary, and supported content
terms must come from runtime-produced tokens or a named `retrieve_ablation`
extension; regex-parsed raw terms must never be added back. Access uses a real
`CandidateEvidenceAccessBinding` whose four eligibility collections are
`frozenset` values of exact nonblank strings. Cross-context comparison
authorization must be an actual boolean; string values fail closed.

## Why It Is Separate

The default `formowl-dev:local` image is the canonical lightweight development
and test image. It should not silently grow PyTorch, Transformers, model caches,
or CUDA dependencies.

The BERT runtimes are separate because customer machines differ:

- low-spec machines should use deterministic and lexical candidate generation;
- standard CPU machines can run CPU-only embedding models;
- GPU or remote model workers can run larger BERT-family NER, relation
  extraction, local LLM graph extraction, larger embedding batches, or
  multimodal semantic adapters.

All of these paths must emit the same FormOwl candidate records and preserve the
same governance boundary.

## CPU Container

The CPU neural runtime is the lowest-common-denominator neural path. It works on
machines without NVIDIA Container Toolkit and is the fallback for small
customer deployments.

It lives at:

```text
containers/kg-bert-cpu/Dockerfile
containers/kg-bert-requirements.txt
```

The CPU container intentionally preserves the previous neural fallback model:

```text
FORMOWL_BERT_ABLATION_MODEL_PROFILE=legacy_cpu_bert
FORMOWL_BERT_ABLATION_MODEL=sentence-transformers/bert-base-nli-mean-tokens
```

Use this profile for customers who need neural matching but do not have a GPU.
It is not the default GPU quality profile. Its preserved default matching
threshold is `0.70`.

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
containers/kg-bert-requirements.txt
```

It uses the official PyTorch CUDA image:

```text
pytorch/pytorch:2.5.1-cuda11.8-cudnn9-runtime
```

CUDA 11.8 is the conservative default for GTX 10-series style deployments.
Newer GPU worker images, such as CUDA 12.4, can be added later without removing
this compatibility path.

The GPU container now defaults to the newer BGE large embedding profile:

```text
FORMOWL_BERT_ABLATION_MODEL_PROFILE=gpu_bge_large_en_v1_5
FORMOWL_BERT_ABLATION_MODEL=BAAI/bge-large-en-v1.5
FORMOWL_KG_BERT_MIN_GPU_CLASS=gtx_1080_ti_11gb
```

The deployment floor for the GPU profile is one NVIDIA GeForce GTX 1080 Ti
class device with 11GB VRAM. Stronger GPUs or remote model workers may use
larger future profiles, but the default local GPU profile must keep this floor
unless the project explicitly raises the customer hardware requirement.
The preliminary small-fixture default threshold for this profile is `0.62`;
large-benchmark calibration must replace this before any production-quality
claim.

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
    --output experiments/kg_bert_ablation/results/kg_bert_ablation_bge_large_gpu_cu118.json \
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
    --output experiments/kg_bert_ablation/results/kg_bert_ablation_bge_large_gpu_cu126_host.json \
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

The CPU legacy profile defaults to:

```text
sentence-transformers/bert-base-nli-mean-tokens
```

The GPU profile defaults to:

```text
BAAI/bge-large-en-v1.5
```

Override it with `FORMOWL_BERT_ABLATION_MODEL`, either as a HuggingFace model
name or as a mounted local model directory. Override the profile with
`FORMOWL_BERT_ABLATION_MODEL_PROFILE` or `--model-profile` when running the
ablation harness. Override the profile threshold with `--bert-threshold`.

## Public Enterprise Benchmark Manifest

The 16-pair fixture is only a regression and smoke benchmark. It is not large
enough for model selection.

The selected larger public benchmark pool is tracked at:

```text
experiments/kg_bert_ablation/public_enterprise_benchmark_manifest.json
```

The manifest targets at least 10,000 labeled pairs for model selection and
50,000 pairs for stakeholder-facing evidence. It covers these enterprise-shaped
source families:

- mail/conversation: Enron email corpus;
- office documents: RVL-CDIP document images;
- financial QA: BEIR FiQA;
- financial reports: SEC EDGAR company submissions and company facts;
- contract documents: CUAD.

The manifest is a source-selection and sampling plan. The first completed
10,000-pair model-selection result is preserved at:

```text
experiments/kg_bert_ablation/results/kg_public_enterprise_benchmark_2026-06-29_bge_gpu_cu126_host.json
```

It uses 7,000 CUAD contract pairs and 3,000 SEC financial-report/company pairs.
FiQA, Enron, and RVL-CDIP are source-locked or probed in this first run, but
are not yet converted into labeled pairs. Large runs must download or mount
public corpora outside Git, write source locks and sampling manifests, then
preserve JSON artifacts under `experiments/kg_bert_ablation/results/`.

Completed 10,000-pair result:

| Run | NN | Accuracy | Precision | Recall | F1 | Total latency | Throughput |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| lexical baseline | no | 0.5216 | 0.940367 | 0.041198 | 0.078937 | 2654.877 ms | 3766.652 pairs/s |
| BGE large GPU | yes | 0.7183 | 0.931627 | 0.468248 | 0.623245 | 418861.960 ms | 23.874 pairs/s |

Delta from lexical to BGE GPU:

```text
accuracy +0.196700
f1       +0.544308
recall   +0.427050
precision -0.008740
```

The BGE run used `BAAI/bge-large-en-v1.5`, threshold `0.62`,
`sentence-transformers=3.3.1`, `torch=2.10.0+cu126`, CUDA 12.6, and
`model_device=cuda:0` on one visible NVIDIA GeForce GTX 1080 Ti. The batch-size
32 attempt failed with a CUDA illegal memory access; the completed run used
single-GPU batch size 8.

This is model-selection evidence, not stakeholder-grade evidence. The artifact
sets `stakeholder_grade_claim=false` because the run is below the 50,000-pair
target. It also remains candidate-only: no canonical graph/type writes and no
raw-access grants are allowed. Its SVG chart is:

```text
experiments/kg_bert_ablation/results/charts/kg_public_enterprise_benchmark_2026-06-29_bge_gpu_cu126_host_metrics.svg
```

The completed 50,000-pair public enterprise BGE artifact is:

```text
experiments/kg_bert_ablation/results/kg_public_enterprise_benchmark_2026-06-29_bge_gpu_50k_cu126_host.json
```

Completed 50,000-pair result:

| Run | NN | Accuracy | Precision | Recall | F1 | Total latency | Throughput |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| lexical baseline | no | 0.5225 | 0.921930 | 0.042316 | 0.080918 | 10171.713 ms | 4915.593 pairs/s |
| BGE large GPU | yes | 0.79986 | 0.945935 | 0.633289 | 0.758664 | 783070.479 ms | 63.851 pairs/s |

Delta from lexical to BGE GPU:

```text
accuracy +0.277360
f1       +0.677746
recall   +0.590973
precision +0.024005
```

The 50,000-pair result uses 22,500 contract-document pairs, 15,000 SEC
financial-report/company pairs, and 12,500 FiQA financial-QA pairs. Its chart
is:

```text
experiments/kg_bert_ablation/results/charts/kg_public_enterprise_benchmark_2026-06-29_bge_gpu_50k_cu126_host_metrics.svg
```

This artifact sets `stakeholder_grade_claim=true` because it reaches the
manifest target. It still does not claim production readiness, production
latency, canonical graph/type writes, raw-access grants, or completed human
adjudication.

The completed ontology-guidance ablation artifact is:

```text
experiments/kg_bert_ablation/results/kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host.json
```

Completed ontology ablation:

| Run | Accuracy | Precision | Recall | F1 | FP | Stress FP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| lexical only | 0.2618 | 0.020063 | 0.041364 | 0.027020 | 10013 | 10000 |
| lexical + hard ontology gate | 0.7618 | 0.940367 | 0.041364 | 0.079242 | 13 | 0 |
| BGE only | 0.3999 | 0.235272 | 0.631759 | 0.342860 | 10177 | 10000 |
| BGE + hard ontology gate | 0.8999 | 0.946493 | 0.631759 | 0.757744 | 177 | 0 |
| BGE + soft ontology score | 0.8999 | 0.946493 | 0.631759 | 0.757744 | 177 | 0 |

The ontology-guided BGE variants improve F1 by `+0.414884` over BGE-only and
remove `10000` cross-type stress false positives. The charts are:

```text
experiments/kg_bert_ablation/results/charts/kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host_metrics.svg
experiments/kg_bert_ablation/results/charts/kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host_ontology_stress.svg
```

This ablation remains candidate-only and does not authorize canonical type
writes, canonical graph writes, or raw access.

## Artifact Rules

Every BERT vs non-BERT comparison must preserve a JSON artifact under:

```text
experiments/kg_bert_ablation/results/
```

The artifact must record:

- dataset id and dataset hash;
- public enterprise benchmark manifest id and hash;
- model name or local model path;
- model profile id and intended runtime;
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
- a public enterprise benchmark manifest and completed 10,000-pair BGE GPU
  model-selection result;
- a completed 50,000-pair public enterprise BGE GPU stakeholder benchmark
  artifact;
- a completed ontology-guidance ablation artifact and SVG charts;
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

These recorded CPU/GPU artifacts used the previous
`sentence-transformers/bert-base-nli-mean-tokens` model on the small fixture.
Future GPU artifacts should use `gpu_bge_large_en_v1_5` /
`BAAI/bge-large-en-v1.5` unless the run explicitly documents a different
profile. The BGE profile uses threshold `0.62` unless `--bert-threshold`
overrides it.

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

The upgraded host GPU BGE artifact is:

```text
experiments/kg_bert_ablation/results/kg_bert_ablation_bge_large_gpu_cu126_host.json
```

Observed small-fixture result:

```text
GPU BGE large + core type gate: precision=1.0, recall=0.9, f1=0.947368, accuracy=0.9375
threshold=0.62
model_device=cuda:0
visible_devices=2 x NVIDIA GeForce GTX 1080 Ti
embedding_latency=202.781ms
```

This improves over the old 16-pair BERT+type-gate artifact, but it is still not
large enough for stakeholder-grade model selection. Use the public enterprise
benchmark manifest before claiming that BGE is generally better for FormOwl
deployments.

The completed 10,000-pair public enterprise BGE artifact is:

```text
experiments/kg_bert_ablation/results/kg_public_enterprise_benchmark_2026-06-29_bge_gpu_cu126_host.json
```

Observed model-selection result:

```text
lexical baseline: accuracy=0.5216, precision=0.940367, recall=0.041198, f1=0.078937
BGE large GPU: accuracy=0.7183, precision=0.931627, recall=0.468248, f1=0.623245
delta: accuracy=+0.196700, f1=+0.544308, recall=+0.427050, precision=-0.008740
dataset: 10000 pairs, 7000 contract_document, 3000 financial_report
```

This gives a concrete quality reason to keep the GPU neural profile available:
it materially improves recall and F1 on the 10,000-pair public benchmark. It
does not prove production latency or final matching quality.

The completed 50,000-pair public enterprise BGE artifact is:

```text
experiments/kg_bert_ablation/results/kg_public_enterprise_benchmark_2026-06-29_bge_gpu_50k_cu126_host.json
```

Observed stakeholder benchmark result:

```text
lexical baseline: accuracy=0.5225, precision=0.921930, recall=0.042316, f1=0.080918
BGE large GPU: accuracy=0.79986, precision=0.945935, recall=0.633289, f1=0.758664
delta: accuracy=+0.277360, f1=+0.677746, recall=+0.590973, precision=+0.024005
dataset: 50000 pairs, 22500 contract_document, 15000 financial_report, 12500 financial_qa
chart: experiments/kg_bert_ablation/results/charts/kg_public_enterprise_benchmark_2026-06-29_bge_gpu_50k_cu126_host_metrics.svg
```

This run reaches the 50,000-pair stakeholder evidence threshold and includes
FiQA financial-QA pairs. It is still candidate-only benchmark evidence and does
not prove production latency, production matching quality, canonical graph/type
writes, raw-access grants, or completed human adjudication.

The completed ontology-guidance ablation artifact is:

```text
experiments/kg_bert_ablation/results/kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host.json
```

Observed ontology result:

```text
BGE only: accuracy=0.3999, precision=0.235272, recall=0.631759, f1=0.342860, false_positive=10177
BGE + hard ontology gate: accuracy=0.8999, precision=0.946493, recall=0.631759, f1=0.757744, false_positive=177
BGE + soft ontology score: accuracy=0.8999, precision=0.946493, recall=0.631759, f1=0.757744, false_positive=177
delta hard gate vs BGE-only: accuracy=+0.500000, f1=+0.414884, precision=+0.711221, recall=+0.000000, false_positive=-10000
charts: experiments/kg_bert_ablation/results/charts/kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host_metrics.svg
        experiments/kg_bert_ablation/results/charts/kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host_ontology_stress.svg
```

This run shows that type compatibility can be useful in a controlled pairwise
matching stress ablation. It does not authorize ontology hard-pruning in
Candidate evidence retrieval and does not override the logical source item
default. A hard gate may remain an explicit matching ablation, but promotion
would require a specification rewrite plus independent cross-domain
false-reject and end-task evidence.

The GPU base image manifest for
`pytorch/pytorch:2.5.1-cuda11.8-cudnn9-runtime` resolved successfully on
2026-06-29. The local image build was stopped after a slow registry download of
the 3.17GB base layer; this was not a Dockerfile or dependency failure.
