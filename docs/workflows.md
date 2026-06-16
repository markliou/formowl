# Workflows

<!-- Future agents: continue building workflow documentation in this file. Do not create another workflow document unless SPEC.md is updated first. -->

FormOwl workflows must be natural-language-first and usable by non-technical project, administrative, and process owners.

Technical systems such as Git, object storage, schema validation, source hashes, and external wiki revision APIs may support the workflow, but they must not be required concepts in the normal user interface.

Engineering workflows should also preserve readability. Python is the first debugging layer for MCP behavior. Rust core code is used when correctness, performance, safety, or syntax shielding requires it, and it should be accessed through clear Python bindings.

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
