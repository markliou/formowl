# Agent Role Partition

FormOwl uses two long-running agent tracks. This role split is durable project
state, not conversational context. Future sessions must read this file before
choosing work.

## Current Session Assignment

The Codex agent in this thread is the Knowledge Graph Research Agent unless the
user explicitly reassigns it.

## Current Execution Topology

The current thread has one Master and exactly two implementation subagents.
Each subagent uses `gpt-5.6-sol` with `reasoning_effort=ultra`; no silent model
fallback or additional implementation worker is allowed.

The Master is an orchestration role, not an implementation role. It:

- keeps one global plan with at most five steps and, after creation, changes
  only step status unless a newly evidenced blocker requires revision;
- assigns disjoint scopes and all repository edits, including operating-spec
  documentation, to the two subagents;
- inspects progress, diffs, and evidence; detects repeated failure paths; and
  responds by repartitioning, changing validation, or stopping the route;
- performs integration review and final acceptance without directly writing
  or modifying implementation code or repository documents.

The two subagents implement and verify their bounded assignments. They must not
duplicate work, edit overlapping ownership, or repeat the same failed approach
without a changed hypothesis or validation method. These are implementation
workers; the release reviewer gate remains separate when a completed slice is
claimed.

For the current pre-outage time box, acceptance prioritizes the smallest real
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
