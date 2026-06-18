# Agent Instructions

This repository is built from the FormOwl specification. At the start of every
new agent session, and again after any context compaction, resume, or long
interruption, read this file first. Before changing code, read these files in
order:

1. `docs/implementation-task-breakdown.md`
2. `SPEC.md`
3. `RESOURCE_EXTRACTION_SPEC.md`
4. `README.md`

Use `docs/implementation-task-breakdown.md` as the shared work board.

## Working Rules

- Treat these instructions as session startup requirements, not one-time
  background context. If a session has already started and you are unsure
  whether the files above were read in the current context, read them again
  before editing.
- Pick one unchecked task or the task explicitly assigned by the user.
- Repo-scoped Codex skills live under `.agents/skills/`. If the user names a
  repo-local skill that is not visible in the active `@skills` list, check
  `.agents/skills/<skill-name>/SKILL.md` before declaring it unavailable.
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
- Use the dev container as the canonical development and verification
  environment. Host commands may be used only for quick inspection or as clearly
  labeled supplemental checks; do not report host-only results as completion
  evidence.
- If a required test, linter, or helper is missing from the dev container, treat
  that as a container/tooling bug to fix or document before reporting the task
  complete.

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
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local \
  python -m unittest discover -s tests
```
