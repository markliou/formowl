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
## Prior bounded checkpoints — 2026-09-02–2026-09-08
- Attachment/table and Route-A diagnostics exercised normal `/mcp`, typed planning,
  source-provided values, citations, lineage, reload/reset, and bounded
  multi-call behavior; they remained partial diagnostics, not general UAT.
- The approved source pair is partial: `2,793` base-mail messages are separate
  from the supplemental root; captured structures include `401` tables, while
  unreferenced HTML/XLSX, inline attachment identity, header attribution, and
  first-selection predicates remain unresolved. Do not fabricate lineage or a
  reviewed-only/`14`-item cap.
- Composed ingestion and compact/lazy canaries preserved source/checkpoint
  bindings, but full-source E5/graph activation was not completed. The eager
  v3 route exceeded the bounded resource shape; an initial normal MCP replay
  replanned with zero citations, and no cited browser-GPT success was accepted.
- The intermittent external HTTP `200` zero-body root remains unresolved. Step 4
  is still in progress; no consumed diagnostic, holdout, readiness, superiority,
  or completion claim may be rerun or inferred.
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
## 2026-09-14 — Bounded implementation checkpoint
- Worker A changed `tests/test_issue56_uat_web_e2e.py` so the target test uses a
  localhost `ThreadingHTTPServer` Responses wire stub and exercises the complete
  `browser /api/chat -> normal MCP -> function_call_output -> provider
  finalization failure -> cited snippet` path. The stub is not an external
  provider.
- Canonical focused evidence: UAT `14` tests / `1` skip; provider bridge `43/43`;
  mail gateway `23/23`; the specified file's Ruff, `py_compile`, and
  `git diff --check` checks passed.
- Worker B fixed the `Any` import and recovery-helper `F821` in
  `scripts/issue56_uat_web.py`; its Ruff and `py_compile` checks passed.
- These are bounded implementation evidence only, not external-provider
  acceptance, methodology readiness, KG/ontology superiority, or objective
  completion. Lifecycle remains `active-blocked`; step 4 remains in progress.
## 2026-09-15 — Bounded provider permission/UAT checkpoint
- The user authorized the existing provider only for permission-filtered
  evidence/citations; secrets, raw paths, raw business payloads, and
  unauthorized sources remain forbidden. No reroute or unchanged-route retry.
- A direct benign greeting reached the provider with HTTP `200` and non-empty
  text in about `11.8 s`; the daily greeting provider smoke succeeded, but this
  is not business-prompt acceptance. The existing FormOwl `/api/chat` path for
  the same greeting returned HTTP `200` but projected `status=error`,
  `reason_code=http_error`, `citation_count=0`, in about `47.95 s`.
- The provider attempt for `整理劉一帆信件` returned pre-MCP HTTP `408`
  `invalid_request_error` with safe MCP `call_count=0`; it therefore failed
  before an MCP/KG evidence query and is not evidence that KG found no data.
  No business answer or citations were accepted.
- The pre-MCP provider-failure repair is now landed: HTTP `408` with
  `invalid_request_error` and zero evidence is classified as the safe
  `provider_pre_mcp_failure` diagnostic, distinct from KG no-data. Do not
  infer root cause or external UAT success. The canonical dev-container
  `methodology_authority_check.py --check` recheck completed with exit `0`,
  `authority_valid=true`, `methodology_ready=false`, `errors=[]`, and `CJK=true`;
  execution fingerprint
  `sha256:7b2c65dc73492438b5bc4880fc7a34740219b13d792c993eb04315e3dc209782`.
  The implementation workers use `gpt-5.5` with
  `reasoning_effort=high`; the UAT provider runtime remains pinned to
  `gpt-5.5` with `reasoning_effort=high`.
- This remains bounded diagnostic evidence only: lifecycle `active-blocked`,
  step 4 `in-progress`, all four methodology gates blocked, and no checkbox or
  completion claim.
## Next Action
Preserve the provider-greeting success versus FormOwl `/api/chat` error and the
pre-MCP `408`/zero-MCP business-prompt failure for Master review. The repair is
local and safe, but real external provider acceptance remains unsuccessful;
do not retry provider/UAT blindly. Keep all four methodology gates blocked.

## 2026-09-16 — Worker B UAT runner/checkpoint
- Startup repair remains provisional and not restarted: the final
  `validate_codex_runtime_state("/run/formowl/issue56-uat/codex-state")`
  invocation passed after atomic state replacement; prior safe tool evidence is
  reference `334715`.
- Focused canonical checks previously recorded: UAT web/HTTP/composition
  `24 passed, 1 skipped` in `162.538 s`; provider bridge `2 passed` in
  `0.157 s`. A fresh validator rerun was not possible because Docker socket
  escalation was rejected; this is an execution blocker, not a validation
  bypass.
- Worker B removed the duplicate provider-local greeting override. Provider
  evidence gating now uses the imported `semantic_plan.requires_workspace_evidence`
  result only. The browser runner self-check passed; no live browser/provider
  request was made and the named UAT container was not restarted.
- Changed implementation paths in this checkpoint are
  `python/formowl_mail/human_uat_orchestrator.py` and
  `tests/test_issue56_uat_handler_composition.py`. External acceptance remains
  pending Master GO and A's integrated focused checks.

## 2026-09-21 — Bounded browser/provider diagnostic checkpoint
- Current bounded experiment checks are `58+13+7+6`; the web slice is
  `16 passed / 1 skipped`.
- Fresh real-browser ordinary chat completed with HTTP `200`, MCP call count
  `0`, rendered text length `25`, and about `5.1 s`. The mail attempt returned
  upstream HTTP `408` `invalid_request_error` before MCP (`0` calls), with
  citations `0`, in about `22.8 s`.
- A subsequent same-version `--ordinary-only` screenshot verification failed
  with provider HTTP `408` `invalid_request_error`, MCP `0`, and about `25.2 s`;
  no screenshot was produced and mail was not sent. The earlier ordinary pass
  is intermittent, not stable chat acceptance or proof of the tool-choice fix.
- No further live repeat is authorized without a new discriminator.
- This is diagnostic evidence only, not external UAT acceptance. The same four
  methodology gates remain blocked, step 4 remains `in-progress`, and no
  readiness, superiority, or completion claim is supported.

## 2026-09-21 — Browser partial-fallback classification review
- The supplied safe browser artifact shows ordinary chat passed with HTTP `200`,
  MCP `0`; mail reached two MCP calls (`ok`, then `mcp_failed`) and retained
  `8` projected citations in an HTTP `partial` response, followed by a provider
  empty-body finalization failure.
- Runner `mail_unsafe_failure` is the conservative and intended result: any MCP
  failure blocks the cited-success branch, while the operational-failure branch
  requires an error turn with zero citations. The public fallback explicitly
  identifies incomplete finalization and bounded partial coverage, so this is
  not a no-data claim and must not be promoted to acceptance.
- No runner, HTTP, orchestrator, or Worker A path was changed for this finding;
  no live/provider rerun was made. Next action is Worker A investigation of the
  structured `tool_execution_failed` response; keep the acceptance predicate
  unchanged.
