# MCP Server Abstract

<!-- Future agents: continue maintaining MCP server abstract notes in this file. Do not create another MCP server abstract document unless SPEC.md is updated first. -->

This repository currently defines the abstract boundaries for the first FormOwl MCP services inside the larger multimodal knowledge pipeline.

MCP service implementations should be Python-first for readability and debugging. Shared heavy or safety-sensitive core behavior should live in Rust and be called from Python through bindings.

## Packages

- `@formowl/contract`
  - Shared portable contract objects.
  - Currently owns `SourceRef`, `EvidenceSnapshot`, `Citation`, `PermissionScope`, `ContextPackage`, `WikiRevision`, `McpResultEnvelope`, and MCP tool-call log events.
  - Target contract scope also includes assets, observations, candidate graph objects, canonical graph objects, user graph revisions, projection specs, ingestion jobs, and extractor runs.
- `@formowl/project-mcp`
  - Abstract Project MCP server.
  - Owns project/work-item tools, project-system adapter boundaries, evidence snapshot storage, and tool-call logging.
  - Does not generate wiki pages.
- `@formowl/wiki-mcp`
  - Abstract Wiki MCP server.
  - Owns markdown draft lifecycle, frontmatter generation, wiki lookup, publishing proposals, wiki snapshots, and tool-call logging.
  - Does not depend on OpenProject internals.

## Runtime Boundary

- Containers are the canonical development, test, and runtime boundary.
- Python owns MCP orchestration, adapters, workflow glue, and human-readable diagnostics.
- Rust owns heavy computing, parsers, validators, hashing, integrity checks, and syntax-shielded core behavior.
- Python bindings expose Rust core APIs to the MCP service layer.

## Current Non-Implementation

The current code intentionally does not include:

- MCP SDK server startup.
- Stdio, HTTP, SSE, or streamable HTTP transport.
- OpenProject API calls.
- Markdown rendering implementation.
- File, database, or object-storage persistence.
- Approval workflow execution.
- Automatic wiki publishing or project write-back.
- Multimodal asset ingestion.
- Observation extraction.
- Candidate graph extraction and review.
- Canonical graph commit storage.
- User graph assembly.

## Abstract Flow

```text
LLM host
  -> Project MCP tool interface
  -> Project system adapter
  -> Evidence snapshot store
  -> ContextPackage
  -> Wiki MCP tool interface
  -> Draft store / publish proposal
```

Project and Wiki MCP packages only exchange data through `@formowl/contract`.

## Target Pipeline Flow

```text
LLM host or UI
  -> MCP orchestration tools
  -> ingestion jobs
  -> observations
  -> candidate graph preview
  -> governed canonical graph commit
  -> user graph revision
  -> wiki projection
  -> WikiRevision review and publish proposal
```

MCP services may coordinate this flow, but extraction, graph resolution, indexing, and canonical commits remain backend responsibilities with policy checks and review records.
