# `formowl_kg_eval` Compatibility Boundary

Lifecycle: **legacy diagnostic compatibility facade**.

`formowl_kg_eval` remains packaged because repository scripts, tests, and
backbone integrations consume its stable redacted JSON shapes. It is not the
active methodology authority for issue #56, and its historical broad harness
must not be used as a work board or completion gate.

Current authority is exclusively:

```text
docs/methodology-authority.json
python3 scripts/methodology_authority_check.py --check
python3 scripts/methodology_authority_check.py --require-ready
```

The active method, comparison design, and implementation plan are:

```text
docs/kg-research-method.md
docs/kg-ontology-v2-rd-boundary.md
docs/kg-ontology-v2-runtime-evaluation-plan.md
```

Historical package documentation is preserved at
`docs/archive/2026-08-18/active/docs/kg-eval-package.md`.

## 1. Why the Package Still Exists

The package provides a stable compatibility surface for:

- reading historical acceptance and benchmark artifacts;
- running legacy developer diagnostics under `.formowl/kg-eval`;
- returning redacted, path-safe summaries to internal integrations;
- preserving old CLI and Python imports while issue #56 is implemented; and
- making historical candidate-generation evidence inspectable without exposing
  private inputs or workspace paths.

It does **not** establish that the current runtime implements
`evidence_to_knowledge_kg_ontology_v2_hybrid_v1`, that the frozen tokenizer is
active, that source completeness passed, or that KG + ontology beats strong
RAG.

## 2. Claim Boundary

Every package result is interpreted as one of:

```text
legacy_harness_diagnostic
historical_candidate_generation_result
compatibility_integration_status
```

It cannot support these claims:

```text
methodology ready for quality UAT
current runtime matches the issue #56 target
source-complete heterogeneous evidence
strong-RAG versus Hybrid-v2 final-answer comparison
KG or ontology superiority
independent holdout acceptance
transfer-domain acceptance
production readiness
```

The package historically exposes a field named `authority_state`. That name is
retained for schema compatibility only. It describes self-consistency of the
legacy broad harness; it is not FormOwl methodology authority. Even
`authority_state.state=passed` would not override a blocked result from
`methodology_authority_check.py --require-ready`.

Likewise, historical broad-gate counts, BGE/lexical deltas, and ontology stress
results are diagnostic records. They are not active next actions and cannot
satisfy any issue #56 readiness gate.

## 3. Stable CLI

The compatibility commands remain:

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

Equivalent module entry point:

```sh
python -m formowl_kg_eval summary
```

Use `--repo-root` outside the checkout:

```sh
formowl-kg-eval --repo-root /workspace summary
python -m formowl_kg_eval --repo-root /workspace benchmarks
```

These commands may fail or report blocked when the legacy workspace is absent.
That result says nothing about issue #56 readiness. Conversely, a successful
legacy command does not permit an issue #56 methodology claim.

## 4. Stable Python API

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

`run_kg_eval_command()` retains these command names:

```text
total
objective
preflight
work-orders
progress
```

Captured stdout and stderr are developer diagnostics. They must remain redacted
for the repository root and `.formowl/kg-eval` workspace. ChatGPT-facing tools
must not expose those streams or the underlying workspace.

## 5. Summary Schema Interpretation

The current compatibility summary may include:

```text
artifact_id
claim_boundary
authority_state
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

Interpretation rules:

- `authority_state` means legacy-harness consistency only.
- `total_acceptance`, `objective_audit`, `work_orders`, and `progress` are
  historical broad-harness fields, not the active work board.
- `candidate_generation_capabilities` describes optional adapter capabilities,
  not required production routing.
- `kg_benchmark_results` contains candidate-level historical experiments, not
  final-answer evidence.
- `claim_boundary` must remain restrictive even when a legacy status passes.
- issue #56 status must be read from the executable methodology authority in a
  separate call.

A downstream integration must not collapse these fields into one green
"KG ready" flag.

## 6. Candidate-Generation Profiles

The facade may report compatibility profiles such as:

```text
deterministic_cpu_candidate_generation_v1
local_embedding_candidate_generation_v1
accelerated_neural_candidate_generation_v1
```

All profiles emit candidates only, for example:

```text
SemanticMetadata
CandidateMention
CandidateAtom
CandidateRelation
CandidateFrame
FusionCandidate
TypeAlignmentCandidate
```

They cannot write canonical graph or ontology state, grant access, choose the
final answer model, or define the issue #56 tokenizer. Historical model names,
hardware floors, and thresholds are preserved artifact metadata, not current
runtime defaults.

## 7. Historical Benchmark Interpretation

`build_benchmark_summary()` and `formowl-kg-eval benchmarks` expose old
candidate-matching experiments through a stable redacted API. Those experiments
may compare lexical, embedding, graph, or ontology-assisted candidate scores.
They do not share the complete issue #56 conditions:

```text
source-complete Observation snapshot
frozen same-profile query/evidence tokenizer
strong BM25+dense RAG control
validated SemanticQueryPlan
deterministic exact execution
same final answer model and prompt
independent holdout and transfer domain
one accepted execution fingerprint
```

Therefore they cannot be promoted to a current RAG/KG/ontology superiority
claim. Any metric shown by the package must retain its original candidate-only,
dataset-specific, and environment-specific boundary.

## 8. System Integration Contract

Safe compatibility use:

```text
System Backbone or developer tool
  -> formowl-kg-eval summary or benchmarks
  -> reads redacted legacy diagnostic fields
  -> presents them as historical/compatibility status
  -> separately runs methodology_authority_check.py
  -> blocks issue #56 claims while --require-ready is nonzero
```

Do not expose:

```text
.formowl/kg-eval paths or private files
raw evidence or oracle answers
per-example private labels
credentials, environment values, or backend locators
SQL, parser commands, worker scratch paths, or object-store keys
canonical graph write controls
```

Product status should prefer a narrow object that reports the executable
methodology authority and explicitly labels any package data as legacy
compatibility evidence.

## 9. Issue #56 Evaluation Output

New issue #56 reports are governed by
`docs/kg-ontology-v2-runtime-evaluation-plan.md` and
`docs/kg-research-method.md`, not by the legacy broad harness. An accepted
report must bind one execution fingerprint covering source, Observation,
tokenizer, indexes, graph, ontology, permission, models, prompts, budgets,
evaluator, code, container, and authority revisions.

Until those reports and all five authority gates pass, package maintenance is
compatibility work only.

## 10. Verification

Canonical package compatibility checks remain dev-container first:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local \
  python -m unittest discover -s tests -p 'test_kg_eval_package.py'

docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local \
  python -m formowl_kg_eval summary
```

The second command may report a blocked or unavailable legacy workspace. That
is a diagnostic outcome, not an issue #56 gate result. Always pair any status
review with:

```sh
python3 scripts/methodology_authority_check.py --check
python3 scripts/methodology_authority_check.py --require-ready
```
