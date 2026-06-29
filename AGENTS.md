# Agent Instructions

This repository is built from the FormOwl specification. At the start of every
new agent session, and again after any context compaction, resume, or long
interruption, read this file first. Before changing code, read these files in
order:

1. `docs/implementation-task-breakdown.md`
2. `docs/agent-roles.md`
3. `docs/agent-goals/README.md`
4. The active role's goal file under `docs/agent-goals/`
5. `docs/agent-goals/handoff-log.md`
6. `docs/agent-goals/reviewer-gate.md`
7. `SPEC.md`
8. `RESOURCE_EXTRACTION_SPEC.md`
9. `README.md`

Use `docs/implementation-task-breakdown.md` as the shared work board. Use
`docs/agent-goals/` as the durable cross-session and cross-machine goal
registry.

## Active Agent Role

This thread's Codex agent is the Knowledge Graph Research Agent. The durable
role split is documented in `docs/agent-roles.md`.

Prioritize knowledge graph, ontology, graph fusion, canonical graph governance,
lifecycle, user graph, graph-derived wiki semantics, and research-evaluation
work. Leave broad system backbone work to the FormOwl System Backbone Agent
unless the user explicitly assigns it here.

## Working Rules

- Treat these instructions as session startup requirements, not one-time
  background context. If a session has already started and you are unsure
  whether the files above were read in the current context, read them again
  before editing.
- Pick one unchecked task or the task explicitly assigned by the user.
- Treat session-local goal state as temporary. If a goal must survive a new
  session, a different computer, or a manual merge, record it in
  `docs/agent-goals/`.
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
- Before pausing, handing work to another agent, or resuming a long-running
  goal, update the relevant `docs/agent-goals/*.md` file and append a concise
  note to `docs/agent-goals/handoff-log.md` when the change affects another
  agent or future session.
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
