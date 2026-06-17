# MCP Boundaries

<!-- Future agents: continue defining MCP boundaries in this file. Do not create another MCP boundary document unless SPEC.md is updated first. -->

MCP is an orchestration boundary, not the core data processing engine.

Project MCP and Wiki MCP are current MCP services. Future ingestion and graph services may expose MCP tools too, but heavy extraction, graph resolution, indexing, and storage work should run in FormOwl backend services.

## Current Boundaries

```text
LLM host
  -> Project MCP for project execution context
  -> Wiki MCP for wiki draft, revision, snapshot, and publish proposal workflows
  -> formowl-contract for portable exchange objects
```

Project MCP must not generate wiki pages. Wiki MCP must not depend on project-system internals.

## Future Pipeline Tools

Recommended future MCP tools:

```text
upload_asset_reference
create_ingestion_job
get_ingestion_job
list_observations
extract_graph_candidates
preview_graph_candidates
resolve_entity_candidate
commit_candidates_to_graph
get_entity
search_graph
generate_wiki_page
```

These tools should expose reviewable operations. They should not let a client or external extractor directly mutate canonical graph state.

## Tool Boundary Rule

External tools may write to:

```text
ObservationStore
CandidateAtomStore
ExternalGraphImport
```

Only FormOwl graph assembly may create canonical graph commits:

```text
CandidateGraph
  -> GranularityPolicyEngine
  -> EntityResolver
  -> RelationResolver
  -> CanonicalGraphCommit
```

MCP tools may request or approve these operations according to permission and review policy, but the canonical commit remains a governed backend operation.
