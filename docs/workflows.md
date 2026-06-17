# Workflows

<!-- Future agents: continue building workflow documentation in this file. Do not create another workflow document unless SPEC.md is updated first. -->

FormOwl workflows must be natural-language-first and usable by non-technical project, administrative, and process owners.

Technical systems such as Git, object storage, schema validation, source hashes, and external wiki revision APIs may support the workflow, but they must not be required concepts in the normal user interface.

Engineering workflows should also preserve readability. Python is the first debugging layer for MCP behavior. Rust core code is used when correctness, performance, safety, or syntax shielding requires it, and it should be accessed through clear Python bindings.

The target workflow is pipeline-first:

```text
Raw resource
  -> Observation
  -> Candidate graph
  -> Governed canonical graph
  -> User knowledge graph
  -> Wiki projection
```

Users should experience this as task-oriented review work, not as manual graph maintenance.

## Project Context to Wiki Revision

```text
User asks for a wiki update in natural language
  -> Project MCP retrieves source context
  -> Project MCP stores evidence snapshots when needed
  -> Wiki MCP generates or refreshes a draft revision
  -> Wiki MCP shows a human-readable diff and citations
  -> Reviewer approves or requests changes
  -> Wiki MCP records an immutable reviewed revision
  -> Wiki MCP prepares a publish proposal
  -> Publish adapter writes to the target wiki if approved
```

## User-Facing Actions

```text
save draft
submit for review
compare changes
approve
publish
refresh from sources
restore previous version
```

## Hidden Backend Actions

```text
create WikiRevision records
persist raw evidence snapshots
calculate markdown and response hashes
record backend revision IDs
optionally mirror reviewed or published revisions to Git
call Rust core APIs through Python bindings for validation, hashing, diffing, or syntax-shielded logic
```

## Multimodal Resource to Wiki Projection

```text
User asks for a meeting page, project hub update, or decision page from mixed resources
  -> FormOwl registers files, project records, wiki pages, and conversations as assets
  -> FormOwl creates ingestion jobs
  -> Extractors produce observations such as transcript segments, document blocks, OCR spans, scenes, and issue comments
  -> Semantic metadata extraction proposes decisions, action items, risks, entities, relations, topics, and requirements
  -> Candidate graph preview is shown for review
  -> Reviewers approve, reject, split, merge, or defer candidate atoms and relations
  -> Entity and relation resolution commits approved graph changes
  -> User graph assembly selects the role/task-specific view
  -> WikiProjectionSpec generates a draft WikiRevision with citations and graph lineage
  -> Reviewer compares, edits, approves, and publishes through the normal wiki workflow
```

## Candidate Graph Review

```text
preview graph candidates
adjust atom granularity
resolve entity aliases
resolve relation conflicts
commit approved candidates
record lifecycle events
generate or refresh a user graph revision
project a wiki draft from that graph revision
```

External tools and LLMs can help create candidates, but they do not approve canonical graph changes on their own.
