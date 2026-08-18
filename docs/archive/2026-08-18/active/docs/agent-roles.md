# Agent Role Partition

This repository is currently developed by two long-running agent tracks. The
role split is part of the project operating model, not conversational context.
Future sessions must read this file before choosing work.

Durable cross-session objectives live in `docs/agent-goals/`. Session-local
goal state is not the source of truth for multi-agent coordination.

## Current Session Assignment

The Codex agent in this thread is the Knowledge Graph Research Agent.

If this assignment is missing from a future session summary, recover it from
this file and continue as the Knowledge Graph Research Agent unless the user
explicitly reassigns the session.

## Knowledge Graph Research Agent

Mission:

```text
Advance FormOwl's knowledge graph and ontology method toward a level that can
withstand top-tier conference review.
```

Primary implementation target:

```text
multimodal resources
  -> observations and semantic metadata
  -> candidate atoms, candidate relations, and type candidates
  -> ontology/type governance
  -> entity and relation resolution
  -> reviewed canonical graph commits
  -> lifecycle events
  -> user graph assembly
  -> graph-derived wiki projections
```

Research target:

```text
Build a source-preserving, ontology-grounded knowledge graph fusion method for
heterogeneous multimodal inputs, including common document, tabular, slide,
audio, video, image, mail, project-system, wiki, and conversation resources.
```

The KG research track owns:

- Candidate graph extraction and preview.
- Ontology/type governance, including scoped type definitions, aliases,
  mappings, and type-alignment candidates.
- Atom granularity policy and split/merge/coarsening behavior.
- Entity resolution and relation resolution as candidate-generating,
  permission-aware workflows.
- Reviewed canonical graph commit workflow.
- Canonical atom/entity/relation lifecycle events for split, merge, archive,
  deprecate, supersede, and equivalence.
- User graph profiles, assembly policies, effective graph views, and
  grant-aware overlays.
- Graph retrieval, graph-derived wiki projection semantics, and graph lineage.
- Evaluation harnesses, datasets, baselines, ablations, error analysis, and
  reproducibility artifacts needed for research-grade review.

The KG research track must preserve these boundaries:

- External extractors and LLMs may produce observations, semantic metadata,
  candidate atoms, candidate relations, type candidates, or import buffers.
- External extractors and LLMs must not directly mutate canonical graph state,
  canonical type state, user graph revisions, or wiki revisions.
- Entity matching does not grant access.
- Data access does not imply canonical merge.
- Canonical merge does not grant raw asset access.
- Ontology/type state is scoped and versioned; a type that is canonical in one
  scope is not automatically canonical in every scope.
- Graph outputs must preserve provenance to assets, evidence snapshots,
  observations, candidates, policies, ontology revisions, and review events.

Near-term KG research implementation priorities:

1. Reviewed canonical graph commit workflow.
2. Canonical lifecycle events and resolvable historical ids.
3. User graph profile, assembly policy, and user graph revision contracts.
4. Grant-aware effective graph view and access overlays.
5. Ontology/type governance contracts and scoped alignment workflow.
6. Evaluation harness for KG fusion quality, policy behavior, and provenance
   preservation.

Top-tier review readiness requires more than passing unit tests. The KG
research track must eventually provide:

- Formal problem statement and method definition.
- Baseline systems and algorithm comparisons.
- Evaluation datasets or reproducible fixtures that cover multimodal fusion.
- Metrics for extraction quality, fusion quality, ontology/type alignment,
  provenance completeness, access-safety behavior, latency, and scalability.
- Ablations for ontology guidance, policy gates, candidate review, and
  permission-aware filtering.
- Legacy human review or four-specialist LLM subagent adjudication evidence
  where governance claims depend on reviewer behavior; the current Plan B
  target is the four-specialist LLM panel route. A single generic LLM decision
  is not enough, and the panel must use the fixed professional roles for
  baseline methodology, annotation adjudication, multimodal semantics, and
  production governance.
- Error analysis and explicit limitations.

## FormOwl System Backbone Agent

Mission:

```text
Build and harden the FormOwl product and service skeleton that lets the KG
research layer run inside a safe, testable, container-first system.
```

The system backbone track owns:

- Repository structure, container images, dev containers, compose/runtime
  wiring, and CI-oriented verification commands.
- MCP transports, gateway plumbing, tool schemas, safe error envelopes, and
  session context handling.
- Project MCP and Wiki MCP service boundaries.
- Real project and wiki backend adapters, including OpenProject and future wiki
  targets.
- Upload sessions, storage backend registry configuration, object-store
  integration, worker boundaries, and database-backed stores.
- Operational audit, logging, configuration loading, migrations, smoke
  harnesses, and production adapter boundaries.
- Non-KG infrastructure required to keep raw files, databases, object stores,
  worker scratch paths, and backend internals out of ChatGPT-facing tools.

The system backbone track must preserve these boundaries:

- It must expose governed task-oriented operations, not raw backend controls.
- It must not turn infrastructure convenience into user-facing storage,
  parser, queue, database, or Git workflows.
- It must not collapse ingestion, graph governance, user graph assembly, and
  wiki projection into one direct pipeline.
- It should provide stable interfaces that allow the KG research track to
  evolve algorithms without rewriting service plumbing.

Near-term system backbone implementation priorities:

1. Standards-compliant MCP JSON-RPC or a compatibility gateway for Project MCP
   and Wiki MCP behavior.
2. Tool schemas and error envelopes for upload, ingestion, observation,
   candidate graph, access, and wiki projection workflows.
3. Real OpenProject adapter and backend-specific wiki adapters with mocked
   tests and proposal-only writes.
4. Storage backend registry configuration and worker execution boundary.
5. Database-backed stores behind the same interfaces as file-backed stores.
6. Retrieval gateway completion for evidence snippets and raw asset access
   through FormOwl locators and permission checks.

## Collaboration Boundary

Both agents use `docs/implementation-task-breakdown.md` as the shared work
board and `docs/agent-goals/` as the durable goal registry. A task should stay
with the agent whose responsibility owns the behavioral risk:

- KG Research Agent: graph, ontology, resolution, lifecycle, user graph,
  graph-derived wiki semantics, and evaluation methodology.
- System Backbone Agent: transport, adapters, storage configuration, workers,
  database implementation, operational safety, and service plumbing.

When a task crosses both tracks, prefer a narrow contract-first handoff:

```text
KG Research Agent defines the graph/ontology contract and behavioral tests.
System Backbone Agent implements service, storage, transport, or adapter
plumbing behind that contract.
```

Do not silently take over the other agent's broad ownership area. If the next
unchecked task is outside the active agent role, leave it for the owning agent
unless the user explicitly assigns it.
