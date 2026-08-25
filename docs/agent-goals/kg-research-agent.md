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

## Diagnostic Checkpoint — 2026-08-25
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
Formal v6 mode `issue56-sealed-source-real-prompt-relation-projection-equivalence-phase-traced-diagnostic-20260825-v6`
consumed its claim over `456` Observations for `workspace_formowl`, approved actor `user_full_pst_domain_hard_case_eval_owner`, with no tenant. Loader, before graph
preseal, and owner relation-base precompute were `677442.490893`, `60990.781102`,
and `4245.079389 ms`. Before completed graph snapshot/Strong RAG
in `0.036742`/`90.802575 ms`, then relation projection exhausted after
`1415.389724 ms`; query/HTTP were `1520.515069`/`1555.417065 ms` with
`0` paths/citations/scores. After relation projection/query/HTTP were
`57.939772`/`291.040282`/`346.270890 ms`, with all required phases complete,
`10` paths, `1` citation, and `48` scores. Cache entries moved before `0/0->1/0`
and after `1/1->1/1`; graph/index/permission/plan/runtime gates passed.
Claim/claim-byte/report-byte are `sha256:6b045800e19d82fa187ff4271ab2d854189726a3449bcd4cedf1c03c47c2639e`,
`sha256:65b3b3d1f9889e1d82ec47ade77fb7dc44b4a9a3711f7bd37a538cdc9e986b61`,
`sha256:ae10a358242f6f44b1f92267a80e48eac296ebd677eb1ac27bcc24f6111909f1`;
execution/source/preseal/trace are `sha256:7ecf2c31901116ddb32d2a8a7cb41b0e3b504648006a68b3e23e89ee22b2c1cf`,
`sha256:bbc67d7fc7051a597488034d277c772a4a5c68bc09dc8ce696bfd2bcc0d8db8b`,
`sha256:4900fd366f300af097de355b59feeb6059a06b41574d01d9834e51576c4eed27`, `sha256:040cb86b70af99fd6f0467306423e0e556a6dfc41b1ed734227b613248c27a93`.
Temporary/combined tests passed `6/6` and `31/31`; cross-review found no blocker. V1-v6 cannot be rerun/tuned. V6 is blocked and earns no broad claim.
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
Any next diagnostic must be separately versioned and approved around the cold
graph-snapshot boundary; then close the four blocked authority gates without
executing holdouts prematurely.
