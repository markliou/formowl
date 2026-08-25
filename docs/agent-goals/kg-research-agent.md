# Knowledge Graph Research Agent Goal
## Lifecycle

- Label: `active-blocked`
- Active program: GitHub issue #56
- Historical pre-rewrite state:
  `../archive/2026-08-18/active/docs/agent-goals/kg-research-agent.md`
- Retention: keep this file at or below 180 lines.
## Role
Knowledge Graph Research Agent. Durable role: `../agent-roles.md`.
## Active Execution Model

Issue #56 uses one Master and exactly two implementation subagents:

```text
Master: global plan, decomposition, monitoring, integration review, acceptance
Worker A: gpt-5.6-sol, reasoning_effort=ultra
Worker B: gpt-5.6-sol, reasoning_effort=ultra
```

The Master does not implement or take over assigned edits. Workers receive
non-overlapping write sets. The five-step plan changes only for a concrete new
blocker; repeated failed routes require a changed decomposition or validation
method, not another retry.
## Objective

Implement and fairly evaluate
`evidence_to_knowledge_kg_ontology_v2_hybrid_v1` so FormOwl can use a governed
graph for heterogeneous-data integration and demonstrate a measurable
final-answer advantage over strong RAG on graph-required tasks.

The intended path is:

```text
source-complete authorized Observations
  -> strong RAG control
  -> conservative entity linking
  -> reviewed candidate/canonical graph topology
  -> temporal/provenance/coverage constraints
  -> scoped ontology with capped soft scoring
  -> deterministic exact executor or cited answer
```

Mail is the first source fixture. The method must transfer to a materially
different source family without question-specific core types or aliases.

## Status

`blocked` for methodology-quality UAT, comparative superiority, default-path
replacement, and objective completion. The pinned authority is valid but fail-closed
with four blocking gates. The normal runtime-method gate passes for
`evidence_to_knowledge_kg_ontology_v2_hybrid_v1` and
`jieba_sentencepiece_frozen_profile_candidate_admission_v1`. Remaining gates
are source completeness, accepted execution-fingerprint binding, same-pipeline
real-source ablation, and independent final-answer acceptance. The v3
promotion contract is repaired, but no passed evidence exists to promote.

## Diagnostic Checkpoint — 2026-08-23

The sealed `456`-Observation `workspace_only_v1` package has no tenant
dimension. Its earlier development one-shot is consumed: Hybrid `0/100`, graph
CI `[0,0]`, citations `0%`, no-answer false positives `100`, p95
`1510.841 ms`, and leakage `0`.
Read-only source tracing found zero occurrences for both identifiers from the
old synthetic fixed prompt at raw source, parser-native, and sealed retrieval
layers. The generalized root cause was prompt-to-approved-source mismatch.
The deterministic
`issue56_source_backed_connected_identifier_prompt_selection_v1` selector now
requires authorized exact-term/lexical lineage and an existing source-backed
connected path; its combined focused E2E passed `11/11`. Immutable mode
`issue56-sealed-source-real-prompt-phase-traced-diagnostic-20260823-v4`
consumed one real-source claim over the same `456` Observations for
`workspace_formowl`, actor/approver
`user_full_pst_domain_hard_case_eval_owner`, with no tenant dimension.
V4 passed with `2` anchors, `10` graph paths, and `1` citation.
Query/gateway/HTTP timings were `951.148333`, `953.544449`, and `982.203990 ms`;
`relation_projection` was the largest semantic phase at `717.357210 ms`, and
`deadline_exhausted_phase` was null. Loader time `678625.866681 ms` was
one-time source loading/selection outside request latency.
Bindings: claim `sha256:2b092814194dd90d597161dfcd04822be75c97fc5c5364478bbc8b52307098cb`;
claim/report bytes `sha256:76dda5b18801a7587b212631b0d4d7ae0544646910e143ced0883f14e5db69b8`,
`sha256:40f48fea0145d523f5d14e2943b41750a48923e111cdf6e6c5e3cd265903a458`;
trace/execution/source `sha256:4b518dd33bc406027f2fe0104559ead2cdb27a096b3357d9470acdac34e09ef4`,
`sha256:031cfe6f04c9b595bed6fd24375590a78df18dd03e07b68821c955bc03ad0b94`,
`sha256:b3959bba1267879ba3bcc6889fd063363f899987722b2447685aad844f6b53ae`;
gateway/owner selection `sha256:5c6bbbac6df98afb061d5aa4b21a7802fdcab7d9d09d32dadaec2f1ac0ab3c1a`,
`sha256:84857528eb34f4e03e343c078f5a9f89e6c8278a6807a6d84cc72fdc2d59b543`;
result/answer `sha256:cd4791354b612ae652da2f76d9733c28946bc18c63856b2a08f6e0a9bab63670`,
`sha256:025d02916a7c0c1a816fba06754d9578a327a7e442ff9d1e34b2f273d2af20f7`.
V1-v4 cannot be rerun/tuned. Full regression was `1873` total / `1781` passed /
`54` failures / `23` errors / `15` skips; blockers were `formowl-dev` Python
3.13 versus pinned E5 plus Issue #20/#33/authority drift. The sole related stale
v3 expectation passed pinned E5 `11/11`; full regression was not rerun and
remains non-green. V4 POC passed, but no repository-wide completion or quality,
UAT, holdout, transfer, readiness, or superiority claim is earned.
## Non-Negotiable Method

- Strong RAG means lexical/BM25 + dense retrieval + fusion + evidence
  reranking over the same Observations.
- KG adds reviewed identity, cross-source joins, bounded traversal, temporal
  state, contradiction, provenance, and coverage.
- Ontology is small-core, scoped, data-first, versioned, and capped additive.
  Inferred mismatch cannot prune admitted evidence.
- Permission, schema/arity, lineage, revision pins, canonical-write
  preconditions, and exact-set coverage remain hard invariants.
- Exact set/count/inventory/aggregation/definitive-negative queries use a
  deterministic executor, not top-k inference.
- The final answer model, prompt, reasoning effort, schema, and context budget
  are identical across comparison arms.
- Independent holdout content cannot tune tokenizer, aliases, ontology,
  graph rules, thresholds, prompts, or models.
- PostgreSQL/pgvector remains canonical; no Neo4j work is authorized.

## Current Blockers

The authority blocks source completeness, execution-fingerprint binding,
same-pipeline real-source ablation, and real-user final-answer acceptance.
Historical, candidate-only, synthetic, and consumed diagnostics cannot satisfy
them.

## Current Five-Step POC Plan

1. The Master freezes two disjoint worker write sets and one real end-to-end
   success path, then records only status changes unless evidence reveals a new
   blocker.
2. Worker A implements the immutable target tokenizer/profile and same-profile
   query/evidence indexing without fallback, including the smallest runnable
   path that proves the profile is actually used.
3. Worker B implements the complementary source-preserving strong-RAG/control
   path needed to carry an authorized Observation through real retrieval and
   result production; contract-only wiring is insufficient.
4. The workers extend their non-overlapping slices into one bounded issue #56
   path covering typed routing, deterministic exact execution where applicable,
   conservative graph expansion, and capped soft ontology scoring.
5. The Master integrates and inspects the end-to-end evidence, redirects any
   repeated blocker instead of retrying blindly, and accepts only the claim
   actually proven. Independent holdout, transfer evaluation, broad hardening,
   and release review remain later gates.

Plan status: step 4 is `in-progress`; the five-step wording remains frozen. No
further execution of the consumed development one-shot is authorized.

## Acceptance Boundary

Implementation completion and comparative close are distinct.

POC evidence must cover this real path:

```text
authorized source/Observation
  -> frozen query/evidence profile and index
  -> strong RAG plus bounded graph/ontology execution
  -> deterministic result or cited answer
```

Contracts, schemas, mocks, or isolated tests alone are insufficient. POC
evidence never relaxes permission, privacy, provenance, candidate-before-
canonical, no-secret/no-raw-path, fail-closed authority, or public-output
boundaries, and cannot earn readiness, superiority, or completion claims.

Implementation completion requires target runtime, source-complete graph input,
strong RAG, typed plans, deterministic exact execution, graph/ontology path,
generalized tests, frozen diagnostic artifacts, synchronized docs, canonical
container verification, and 3/3 reviewer agreement.

Comparative close additionally requires the independent holdout and transfer
domain to pass pre-registered correctness, citation, no-answer, privacy,
latency, and cost gates, plus:

```sh
python3 scripts/methodology_authority_check.py --require-ready
```

exiting zero.

## Next Action

Remain within step 4, but do not rerun or tune any consumed diagnostic.
Run only a separately approved behavior-neutral `relation_projection` latency
POC, then close the four blocked authority gates; do not execute holdouts.
