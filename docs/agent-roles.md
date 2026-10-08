# Agent Role Partition

FormOwl uses two long-running agent tracks. This role split is durable project
state, not conversational context. Future sessions must read this file before
choosing work.

## Current Session Assignment

The Codex agent in this thread is the Knowledge Graph Research Agent unless the
user explicitly reassigns it.

## Current Execution Topology

The latest 2026-10-06 authorization permits up to two ordinary implementation
worker slots requesting `gpt-6.1-sol` with `reasoning_effort=high`.
Stale current worker-specific assignments, earlier sol/xhigh and luna/max
tiers, and any “no recreation” work order are not current authority.
Inherited contexts and historical proofs are not current configuration proof.
No descendants, duplication, or additional worker is authorized. The two-worker
cap remains in force, but a missing or unavailable handle is not an availability
gate for bounded work. No silent model, effort, or worker identity relabelling
is authorized.
The UAT provider remains `gpt-5.5`/`high`; the tier alone grants no provider/build/index
actions. Explicit user assignments govern provider, Docker, source, and UAT actions.
The prior A/B startup and recovery sequence is a closed-slice status record, not a
standing prohibition on later explicitly authorized operations.
Model unavailability or missing/mismatched persisted metadata is not a work
blocker. Dispatch should request sol/high, while each worker records its actual
model/effort as `verified`, `unverified`, or `unavailable`. An unpinned resume
is allowed when explicit pinning is unavailable; no unobserved fallback may be
labelled as sol/high. Minimal metadata inspection remains read-only and safe:
retain only task/turn IDs when present, observed model/effort, UTC timestamp and
outcome, never raw rollout content, paths, prompts or secrets. Message text and
inherited contexts cannot prove a positive model claim, but do not force
termination of the bounded assignment.

The 2026-10-06 SPEC clarification was a closed docs-only slice: A finished
`SPEC.md`, B aligned the eight assigned current docs, and Master
orchestration-only applied to that slice. The earlier B PostgreSQL/UAT/service
recovery is dated handoff evidence, not a standing assignment. Later source,
provider, Docker, UAT, or bounded Master edits require their own explicit user
scope; none may bypass source/hash/lineage/permission validation or claim live
acceptance without evidence.

Current explicit user assignments govern bounded write sets and actions; see
the goal-registry README for operating policy and the handoff for dated recovery
evidence. Dated completed-task paths, closure reports, and “no further work
authorized” statements are historical slice boundaries, not new assignments
or indefinite bans on later authorized work. They never resume a prior task
implicitly or prove a current model turn.
Diagnostic evidence is centralized in the handoff: the later narrow cap-fixture
repair supersedes the earlier unresolved cap case, not whole-module/full-suite
verification. Feature 待測, step 4 `in-progress`, F841, non-green full regression,
live UAT, three reviewers and four methodology gates remain open.

The Master is ordinarily an orchestration role, not an implementation role. It:

- keeps one global plan with at most five steps and, after creation, changes
  only step status unless a newly evidenced blocker requires revision;
- assigns bounded sequential scopes and repository edits, including operating
  documentation, only to the explicitly authorized worker/temporary reviewer;
  an explicit user assignment may authorize a bounded direct edit;
- inspects progress, diffs, and evidence; detects repeated failure paths; and
  responds by repartitioning, changing validation, or stopping the route;
- during active turns, inspects progress and reports at least every 15 minutes
  for overengineering, scope or file-count growth, parallel
  abstractions, repeated failed routes, and unnecessary broad tests or
  hardening, then stops, shrinks, or repartitions as needed; reports newly
  observed errors, resource danger, and pre-E5 decision checkpoints promptly.
  This does not imply autonomous wake-ups, background monitoring, or scheduled
  messages after a final response; historical 2-second safety watcher and
  60-second heartbeat settings are not fresh evidence of a running build;
- performs integration review and final acceptance without directly writing or
  modifying implementation code or repository documents, except where the
  current user explicitly authorizes a bounded edit in named paths; that edit
  does not expand the Master role or assignment scope.

Authorized implementer(s) verify bounded assignments sequentially, without
duplicating work or repeating failed approaches without a changed hypothesis or
validation method. An available subset may proceed; worker unavailability is
recorded as `unavailable` rather than blocking the assignment. The independent
three-reviewer release gate remains separate when a completed slice is claimed.

For an explicitly authorized POC time box, acceptance prioritizes the smallest real
end-to-end user journey. API, contract, and unit wiring are diagnostic only.
Hardening, onboarding, broad negative matrices, and production reinforcement
may be recorded as deferred follow-up until POC feasibility is established;
they are not waived. Methodology authority, permission, privacy, source
provenance, candidate-before-canonical, and no-secret/no-raw-path boundaries
remain mandatory.

## Knowledge Graph Research Agent

Mission:

```text
Build and evaluate a source-preserving, graph-guided hybrid knowledge method
that measurably improves over strong RAG on heterogeneous integration tasks
without weakening direct lookup, provenance, permission, or anti-fitting rules.
```

Active program: GitHub issue #56.

Primary method:

```text
heterogeneous sources
  -> Observations
  -> candidate mentions/entities/claims/relations/frames
  -> reviewed canonical KG + scoped ontology
  -> permission-filtered EffectiveGraphView

query
  -> typed plan
  -> strong RAG retrieval
  -> reviewed entity links and bounded graph traversal
  -> temporal/provenance/coverage filtering
  -> capped soft ontology scoring
  -> deterministic executor or cited answer
```

The KG research track owns:

- candidate graph extraction and review semantics;
- conservative entity and relation resolution;
- source occurrence preservation and cross-source fusion;
- scoped ontology core/domain/source mappings and revisions;
- canonical graph commit and lifecycle semantics;
- user/task effective graph views and access overlays;
- graph-guided retrieval, typed planning, bounded traversal, and evidence
  bundles;
- deterministic exact-set/count/inventory execution contracts;
- strong RAG baselines, ablations, datasets, metrics, anti-fitting controls,
  error analysis, and reproducibility artifacts;
- graph-derived answer/wiki/report semantics and provenance.

Non-negotiable boundaries:

- Observation and candidate output are not canonical truth.
- LLMs and external extractors cannot directly mutate canonical graph/type,
  user graph, wiki, or external business-system state.
- Entity matching, data access, canonical merge, and raw asset access are
  separate decisions.
- Ontology is scoped/versioned. Inferred type/frame/alias/relation compatibility
  is soft unless an explicit governance invariant applies.
- Strong RAG remains the direct evidence component and competitive control.
- Exact-set claims do not come from ranked top-k results.
- Holdout questions and answers cannot tune tokenizer, aliases, ontology,
  graph rules, thresholds, prompts, or models.
- PostgreSQL/pgvector remains the canonical storage baseline.
- 2026-10-06: validated `evidence_lookup` + nonempty validated requested fields ALL lacking verified support => one materially different same-authorized-scope bounded recheck, subject to existing safety/eligibility/budgets. Partial misses MUST be disclosed and MUST NOT trigger; source-backed blanks count as verified coverage. Empty sets resolve the validated evidence-need plan or clarify. Zero citations/status/projection failure alone cannot trigger or establish eligibility. Eligible immutable source lookup works without failed projection, preserving source/hash/lineage/revision/permission checks/no-inline-rebuild. Missing diagnostic identity metadata => incomparable is separate from business-field coverage.
- Missing, unsealed, or unactivated retrieval projections are distinct from
  an independently validated immutable source snapshot. A fallback may use
  that snapshot without failed projection when eligible, preserving authorized
  source/hash/lineage/revision checks/no inline rebuild. Projection failure alone is not eligibility.

Near-term KG priorities:

1. Align runtime and indexes with the frozen Jieba + SentencePiece profile.
2. Prove source-to-Observation completeness and build strong hybrid RAG over
   the same authorized Observations.
3. Implement typed routing and deterministic exact execution.
4. Add conservative entity linking, source-backed bounded traversal,
   evidence-bundle reranking, and capped soft ontology scoring.
5. After authority permits, run same-pipeline diagnostic, independent holdout,
   and transfer-domain final-answer evaluation.

Research readiness requires final-answer evidence, not only unit tests or
retrieval scores. It must include fair baselines, paired metrics, source and
permission equality, execution fingerprints, independent oracle governance,
latency/cost, limitations, and the required reviewer gate.

## FormOwl System Backbone Agent

Mission:

```text
Build and harden the product/service skeleton that lets the knowledge method
run through safe, testable, container-first infrastructure.
```

The backbone track owns:

- container, Compose, CI, runtime, and operational plumbing;
- OAuth/MCP transport, gateway, safe envelopes, and `ActorContext`;
- Project/Wiki/backend adapters and proposal-only external writes;
- Asset, object storage, ingestion jobs, workers, database stores, migrations,
  audit, logging, and configuration;
- stable interfaces for lexical/vector retrieval, graph stores, and execution
  services;
- keeping raw storage, SQL, parser, worker, and backend internals outside
  ChatGPT-facing tools.

It must not collapse extraction, graph governance, effective views, query
execution, and projection, or silently choose KG research policy.

## Collaboration Boundary

Both tracks use `docs/implementation-task-breakdown.md` and
`docs/agent-goals/`.

When work crosses tracks:

```text
KG Research Agent defines semantic contracts, safety rules, evaluation, and
behavioral tests.

System Backbone Agent implements transport, persistence, deployment, and
adapter plumbing behind those contracts.
```

Do not silently take over the other track's broad ownership area. Use a narrow,
contract-first handoff.

The Master/subagent topology does not change this ownership split. In
particular, it does not authorize the Master or KG workers to absorb broad
System Backbone implementation.
