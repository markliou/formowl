# MCP Server Abstract

<!-- Future agents: continue maintaining MCP server abstract notes in this file. Do not create another MCP server abstract document unless SPEC.md is updated first. -->

This repository currently defines the abstract boundaries for the first formoowl MCP architecture.

## Packages

- `@formoowl/contract`
  - Shared portable contract objects.
  - Owns `SourceRef`, `EvidenceSnapshot`, `Citation`, `PermissionScope`, `ContextPackage`, `McpResultEnvelope`, and MCP tool-call log events.
- `@formoowl/project-mcp`
  - Abstract Project MCP server.
  - Owns project/work-item tools, project-system adapter boundaries, evidence snapshot storage, and tool-call logging.
  - Does not generate wiki pages.
- `@formoowl/wiki-mcp`
  - Abstract Wiki MCP server.
  - Owns markdown draft lifecycle, frontmatter generation, wiki lookup, publishing proposals, wiki snapshots, and tool-call logging.
  - Does not depend on OpenProject internals.

## Current Non-Implementation

The current code intentionally does not include:

- MCP SDK server startup.
- Stdio, HTTP, SSE, or streamable HTTP transport.
- OpenProject API calls.
- Markdown rendering implementation.
- File, database, or object-storage persistence.
- Approval workflow execution.
- Automatic wiki publishing or project write-back.

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

Project and Wiki MCP packages only exchange data through `@formoowl/contract`.
