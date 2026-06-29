# FormOwl KG Eval Package

`formowl_kg_eval` is the packaged facade for the Knowledge Graph Research
Agent's broad real-evidence acceptance harness. The authoritative validators
remain under `.formowl/kg-eval`; the package provides stable redacted summary
and benchmark API/CLI entry points so the System Backbone Agent does not need
to import repo-local scripts directly.

## What This Package Owns

- Running the KG research-evaluation authority commands for developer
  diagnostics, with local path redaction on captured stdout/stderr.
- Reading persisted broad acceptance reports.
- Producing a redacted summary for downstream integration.
- Preserving the research claim boundary:
  broad KG real-evidence acceptance may be complete while full product
  production readiness, top-tier scientific validation, raw asset access,
  canonical graph writes, autonomous business judgment, and enterprise-scale
  latency/scalability remain unclaimed.

## What This Package Does Not Own

- MCP transport, gateway, session, or tool-schema plumbing.
- Database, object-store, worker, or backend adapter implementation.
- Raw file, NAS, object-store, database, or worker-scratch access.
- Canonical graph mutation.
- Wiki publication.

Those remain System Backbone or product integration responsibilities.

## CLI

After installing the editable package, use:

```sh
formowl-kg-eval summary
formowl-kg-eval benchmarks
formowl-kg-eval total
formowl-kg-eval objective
formowl-kg-eval preflight
formowl-kg-eval work-orders
formowl-kg-eval progress
formowl-kg-eval all
```

In a dev container that has not refreshed console scripts after this package was
added, use the equivalent module entry point:

```sh
python -m formowl_kg_eval summary
```

Use `--repo-root` when calling from outside the checkout:

```sh
formowl-kg-eval --repo-root /workspace summary
python -m formowl_kg_eval --repo-root /workspace summary
```

`summary` is the preferred integration command. `benchmarks` is the preferred
benchmark-only integration command. They print stable JSON objects suitable for
product integration.

`summary` includes these top-level sections:

```text
artifact_id
claim_boundary
total_acceptance
objective_audit
remaining_evidence
preflight
work_orders
progress
candidate_generation_capabilities
kg_benchmark_results
integration_boundary
```

The summary intentionally reports no raw workspace path. It points downstream
systems to the stable authority workspace `.formowl/kg-eval`.

Use `benchmarks` when the integration only needs the BGE, lexical, and ontology
ablation evidence:

```sh
formowl-kg-eval benchmarks
python -m formowl_kg_eval benchmarks
```

The benchmark API is redacted for product integration: it includes dataset
counts, metrics, deltas, claim boundaries, and repo-relative SVG chart paths,
but omits per-pair samples and raw labels from the large experiment artifacts.

## Python API

```python
from formowl_kg_eval import (
    build_acceptance_summary,
    build_benchmark_summary,
    run_kg_eval_command,
)

summary = build_acceptance_summary(repository_root="/workspace")
benchmarks = build_benchmark_summary(repository_root="/workspace")
result = run_kg_eval_command("preflight", repository_root="/workspace")
```

`run_kg_eval_command()` supports:

```text
total
objective
preflight
work-orders
progress
```

The command result carries `command`, `script`, `returncode`, `stdout`,
`stderr`, and `passed`. Captured stdout/stderr are redacted for the configured
repository root and `.formowl/kg-eval` workspace. This runner remains a
developer diagnostic surface; product integrations should expose `summary` or
`benchmarks`, not raw validator stdout/stderr.

## Candidate Generation Capability Profiles

The package summary also exposes `candidate_generation_capabilities`. This is
the stable handoff surface for heterogeneous remote computers:

- `deterministic_cpu_candidate_generation_v1` is the low-spec path. It uses
  rules, gazetteers, deterministic text markers, Unicode normalization, and
  RapidFuzz-compatible lexical matching. It does not use neural networks.
- `local_embedding_candidate_generation_v1` is the standard CPU path. It is the
  adapter slot for SentenceTransformer or BERT-family encoder embeddings,
  pgvector similarity candidates, and embedding-backed type alignment. Its
  preserved default model profile is `legacy_cpu_bert` with
  `sentence-transformers/bert-base-nli-mean-tokens` and threshold `0.70`.
- `accelerated_neural_candidate_generation_v1` is the high-spec worker path.
  It is the adapter slot for BERT-family NER, BERT-family relation extraction,
  local LLM graph extraction, multimodal semantic adapters, and large embedding
  batches. Its current default embedding profile is
  `gpu_bge_large_en_v1_5` with `BAAI/bge-large-en-v1.5`, and the local GPU
  floor is one NVIDIA GeForce GTX 1080 Ti class device with 11GB VRAM. Its
  preliminary threshold is `0.62` until the large benchmark calibrates it.

All three profiles emit candidate-only records such as `SemanticMetadata`,
`CandidateAtom`, `CandidateRelation`, `FusionCandidate`, and
`TypeAlignmentCandidate`. None of the profiles may write canonical graph/type
state or grant raw asset access.

This section intentionally does not claim that a BERT model is already running
in the default dev container. It records the integration contract that lets the
System Backbone Agent route low-spec machines to deterministic generation and
route high-spec or remote model workers to neural candidate adapters.

The package summary is also the handoff surface for model routing: CPU neural
workers should use the legacy CPU BERT profile, while GPU workers meeting the
1080 Ti floor should use the BGE large profile unless a run artifact explicitly
pins another model.

## Benchmark Result API

`build_benchmark_summary()` and `formowl-kg-eval benchmarks` expose the current
research benchmark evidence as a package-level contract for downstream system
work:

```text
artifact_id
claim_boundary
headline_results
artifacts
integration_boundary
```

Current headline results:

| Evidence | Pair count | Result |
| --- | ---: | --- |
| Public enterprise BGE vs lexical | 50,000 | F1 delta +0.677746 |
| Ontology-guided BGE vs BGE-only | 20,000 | F1 delta +0.414884 |
| Ontology stress false positives | 10,000 stress negatives | 10000 -> 0 |

The benchmark summary keeps the same claim boundary as the source artifacts:
candidate-only, no raw access, no canonical graph/type write authority, no
production latency claim, and no completed human-adjudication claim. Chart
paths are repo-relative so a product integration can render them without
receiving host-specific filesystem paths.

## System Backbone Integration Contract

The System Backbone Agent should call the package facade, not repo-local
validator modules:

```text
System Backbone Agent
  -> formowl-kg-eval summary
  -> reads claim_boundary and total_acceptance
  -> reads candidate_generation_capabilities for worker routing
  -> optionally reads kg_benchmark_results or formowl-kg-eval benchmarks
  -> decides whether product-level integration can proceed
```

Do not expose `.formowl/kg-eval` internals through ChatGPT-facing MCP tools.
If a user needs status, expose the package summary or a narrower product-owned
status object. Do not expose raw evidence artifacts, local filesystem paths,
database locators, object-store keys, SQL, worker scratch paths, or canonical
graph write controls.

## Current Authority State

The current local broad KG real-evidence state is 12/12:

```text
overall_passed=true
passed_gate_count=12
failed_gate_count=0
remaining_gates=[]
```

Current hashes:

```text
gate_status_sha256=9e68c2a78681c86ff52f6ef25f20d3f6112183dcb681f137f6d349e7e4c96aba
objective_audit_sha256=b37edc1a2cf5d9891557f91f669608204998d3a8112fa0a299e3a99d082bb44d
```

## Verification

Canonical verification remains dev-container first:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local \
  python -m unittest discover -s tests -p 'test_kg_eval_package.py'

docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local \
  python -m formowl_kg_eval summary

docker run --rm -v "$PWD:/workspace" -w /workspace/.formowl/kg-eval formowl-dev:local \
  python -m unittest discover -s . -p 'test_*.py'
```
