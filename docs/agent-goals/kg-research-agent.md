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
promotion contract is repaired, but no formal all-four-gate evidence exists to
promote.
## Step-4 Candidate Attachment Checkpoint — 2026-09-01
Pushed checkpoint `dfaf38b` (`feat(issue56): answer candidate attachment
tables`) carries the bounded candidate-table answer slice. A real
recovery-source attachment-table diagnostic used normal ASGI `/mcp` and
returned HTTP `200`, `candidate_interpretation`, four governed citations, and
about `908.085 ms` latency without deadline exhaustion.

The result remains `candidate_only` because the source HTML table had no
semantic header markup. It reports `canonical_kg=false`,
`deterministic_exact=false`, and no `exact_result`; ambiguous lookup remains
fail-closed. The diagnosed root cause was a source-selection/artifact-binding
scope gap, not permission expansion or deterministic exact evidence.

The source session, authorization, requester, workspace, scopes, authorized
Observations, and index are bound into the lookup seal. Cross-session reuse is
rejected. Candidate lookup/result types are private and their public claims are
fixed to the safe noncanonical, nonexact state. Identity remains
`workspace_only_v1` for `workspace_formowl`, actor/approver
`user_full_pst_domain_hard_case_eval_owner`; no tenant ID exists or may be
invented.

Clean committed-checkpoint verification passed `43` directly relevant focused
tests plus one real recovery-source `/mcp` run. Canonical-container authority
is valid but blocked: `authority_valid=true`, `methodology_ready=false`,
fingerprint
`sha256:3e694b04a2888ea829c1a558e7802e8720eeb69cc99ac91db9c534136616e858`.
Source completeness, accepted execution-fingerprint binding, same-pipeline
real-source ablation, and independent final-answer acceptance remain blocked.
This is not formal UAT or evidence of production readiness, methodology
readiness, Issue #56 completion, or comparative superiority. Step 4 remains
`in-progress`.

The earlier participant inventory remains independently `incomplete`: its
authorized scope is `2793`, split into `2069` matches, `174` proven nonmatches,
and `550` unresolved. The candidate attachment slice does not supersede or
close that coverage gap.
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

Remain within step 4. Close the source-selection/artifact-binding scope gap and
obtain source-backed or reviewed semantic header evidence before any
canonical-KG or deterministic-exact promotion. Do not treat candidate-only
interpretation as formal UAT, run blocked holdouts, or claim readiness,
superiority, production status, or Issue #56 completion.
