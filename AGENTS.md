# Agent Instructions

This repository is built from the FormOwl specification. Before changing code,
read these files in order:

1. `docs/implementation-task-breakdown.md`
2. `SPEC.md`
3. `RESOURCE_EXTRACTION_SPEC.md`
4. `README.md`

Use `docs/implementation-task-breakdown.md` as the shared work board.

## Working Rules

- Pick one unchecked task or the task explicitly assigned by the user.
- Stay inside the listed owner paths when possible.
- Do not create parallel replacement modules, schemas, or documents when the
  specification already names an expected path.
- Keep resource extraction, graph governance, user graph assembly, and wiki
  projection as separate layers.
- Do not expose raw filesystem, NAS, object-store, database, worker, or parser
  internals through ChatGPT-facing MCP tools.
- Mark a checklist item `[x]` only after code, tests, and relevant docs are
  complete.
- If a task is partially done, leave it unchecked and add a short note in the
  task breakdown file.

## Current Starting Point

The current tested baseline is:

```text
Project MCP
  -> ContextPackage and EvidenceSnapshot
  -> Wiki MCP
  -> sourced markdown draft
```

The next small core starts at:

```text
Asset
  -> IngestionJob
  -> ExtractorRun
  -> Observation
  -> ContextPackage bridge
  -> Wiki MCP draft
```

Run the existing Python tests before reporting completion:

```sh
PYTHONPATH=python python -m unittest discover -s tests
```
