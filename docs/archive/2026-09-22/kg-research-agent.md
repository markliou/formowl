# Knowledge Graph Research Agent Goal
## Lifecycle
- Label: `active-blocked`
- Active program: GitHub issue #56
- Historical pre-rewrite state:
  `../archive/2026-08-18/active/docs/agent-goals/kg-research-agent.md`
- Retention: keep this file at or below 180 lines.
## Role
Knowledge Graph Research Agent. Durable role: `../agent-roles.md`.
## Active Execution Model — current 2026-09-21
Issue #56 uses one Master and exactly two implementation subagents:

```text
Master: global plan, decomposition, monitoring, integration review, acceptance
Worker A: gpt-5.6-luna, reasoning_effort=max
Worker B: gpt-5.6-luna, reasoning_effort=max
```
The UAT provider remains pinned to `gpt-5.5`/`reasoning_effort=high`; the
independent release gate remains three effective read-only Codex/GPT reviewers.
Dated model settings in later checkpoint entries are historical and superseded
by this current specification.
The Master does not implement or take over assigned edits. Workers receive
non-overlapping write sets. The five-step plan changes only for a concrete new
blocker; repeated failed routes require a changed decomposition or validation
method, not another retry.
As of 2026-09-22, token scarcity makes AGENTS.md's two-worker total cap
mandatory across nesting: reuse the existing pair without duplicate delegation,
and create no third, replacement, new worker, or descendants without explicit
new user authorization.
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
`active-blocked` for methodology-quality UAT, comparative superiority, default-path
replacement, and objective completion. The pinned authority is valid but fail-closed
for readiness in the canonical dev-container authority
check completed with exit `0`, `authority_valid=true`, `methodology_ready=false`,
`errors=[]`, and `CJK=true`; execution fingerprint
`sha256:7b2c65dc73492438b5bc4880fc7a34740219b13d792c993eb04315e3dc209782`.
Four gates remain blocked: source completeness, accepted execution-fingerprint
binding, same-pipeline real-source ablation, and independent final-answer
acceptance. Target method and tokenizer remain pinned; no formal all-four-gate
evidence exists to promote.
## Archived earlier checkpoints
Detailed pre-2026-09-14 diagnostics, partial-source findings, and consumed-route
restrictions are preserved losslessly in
[docs/archive/2026-09-21/kg-research-agent.md](../../docs/archive/2026-09-21/kg-research-agent.md);
they are not restart instructions.
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
- Tool queries are agent-expanded and schema-validated before execution. The
  agent may iterate through bounded refinements/requeries after inspecting
  coverage, with safe phase traces and no per-query KG/index rebuild.
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
## 2026-09-14–2026-09-21 — Bounded implementation record
- Focused UAT, provider-bridge, mail-gateway, and runner checks remain
  diagnostic evidence only; no external-provider, readiness, superiority, or
  completion claim is supported.
- Ordinary browser evidence was HTTP `200`/MCP `0`. The mail path reached a
  bounded partial response with an MCP failure and was correctly rejected by
  the runner; the acceptance predicate remains fail-closed.

## 2026-09-21 — Source fallback lineage handoff
- Inventory-only mail records are filtered before message-lineage validation;
  valid-message records missing lineage remain rejected.
- Focused canonical tests passed `23/23`. Provider-free same-selector replay
  returned HTTP `200`, `payload_validated`, exceptions `0`, but
  `pending_review`/citations `0`, scanned `249`, callbacks/matches `0`, and
  stop reason `deadline`.
- The UAT service was not restarted; no new live/provider retry occurred after
  the patch. Acceptance is **NOT complete**.

## Next Action
Investigate eligible-observation access/scan startup within the existing
immutable source reader and pinned budgets; no blind timeout inflation, data or
index rebuild, or lineage bypass.

## 2026-09-22 — Current checkpoint
- The implementation pair remains capped at exactly two workers, both
  `gpt-5.6-luna` with `reasoning_effort=max`; no new worker or descendant was
  created.
- Master canonical focused verification passed `100/100`. Canonical authority
  is `authority_valid=true`, `methodology_ready=false`; all four methodology
  gates remain blocked.
- After the single controlled UAT restart, startup eventually completed and
  the existing Playwright Chromium runner reached the service. Ordinary chat
  passed with MCP `0`; the mail turn returned HTTP `200` with
  `ContractValidationError`/`tool_execution_failed`, `0` citations, and then
  empty provider finalization. Reload/reset/post-reset follow-ups did not run.
  UAT acceptance is **NOT complete**.
- Two resident-log owner entries were
  `semantic_plan.route_semantic_query:808`, but their association with the
  latest browser run is not confirmed. No lineage-mismatch root-cause claim is
  made; `本次 live owner 尚待 request/trace 關聯確認`.
