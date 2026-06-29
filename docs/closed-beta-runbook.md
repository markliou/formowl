# Closed Beta Runbook

This runbook defines the current FormOwl internal closed-beta readiness gate.
It is a trusted internal smoke, not production readiness.

## Scope

The closed-beta smoke validates one synthetic backbone path:

```text
Project MCP JSON-RPC
  -> ContextPackage and EvidenceSnapshot
  -> Wiki MCP draft and proposal-only publish
  -> Storage backend registry config
  -> Asset registration and worker ingestion
  -> Observation ContextPackage bridge
  -> Wiki MCP draft
  -> Retrieval gateway grant checks and raw-asset references
  -> KG-eval package facade summary
```

The smoke uses synthetic fixtures only. It must not require live PostgreSQL,
live object storage, live OpenProject, mail archives, production SSO, real raw
customer assets, or canonical graph writes.

## Prerequisites

- Run from the repository root.
- Use the dev container as the canonical environment.
- Ensure the dev image exists:

```sh
docker build -f containers/dev/Dockerfile -t formowl-dev:local .
```

## Command

Run the smoke inside the dev container:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local \
  python scripts/closed_beta_smoke.py --output /tmp/formowl-closed-beta-smoke.json
```

The command writes:

- `/tmp/formowl-closed-beta-smoke.json`
- `/tmp/formowl-closed-beta-smoke.md`

The report path is inside the container and is intended for immediate operator
inspection, not as a tracked completion artifact.

The smoke also refreshes the ignored KG-eval runtime reports under
`.formowl/kg-eval/results/` through the packaged `formowl_kg_eval` facade
before loading the redacted summary. Those reports are generated validation
state, not tracked product artifacts.

## Pass Criteria

The smoke passes only when all of these are true:

- JSON-RPC `initialize`, `tools/list`, and `tools/call` work for current Project
  MCP and Wiki MCP behavior.
- JSON-RPC transcripts retain only method names and request/response hashes.
- Wiki publishing remains proposal-only.
- The storage backend public envelope does not expose local roots, internal
  endpoints, object keys, buckets, or backend control-plane details.
- A registered text asset becomes an ingestion job, extractor run, and text
  observation through `IngestionWorker`.
- Worker result summaries do not expose source paths, object roots, or worker
  scratch internals.
- Observation-to-context-package bridging can generate a Wiki MCP draft.
- Retrieval denies evidence without a grant, returns evidence snippets after a
  project grant, denies raw-asset mode without `asset_scoped_access`, and
  returns only `formowl://asset/...` references with `content_returned=false`
  after the explicit raw-asset grant.
- The system integration reads KG status through `formowl-kg-eval summary` /
  `formowl_kg_eval`, not direct repo-local script imports.
- Public outputs pass raw path, SQL, backend internal, and worker-internal leak
  guards.
- No canonical graph artifacts are written by the smoke.

## Explicit Exclusions

Passing this smoke does not claim:

- Production readiness.
- Live PostgreSQL or pgvector readiness.
- Live object-store readiness.
- Automatic wiki publishing.
- Production authentication or SSO.
- Mail adapter readiness.
- Raw asset content access.
- Canonical graph or canonical type writes.
- Enterprise latency, scalability, or quality.
- Top-tier scientific validation.

## Failure Handling

If the command exits nonzero, inspect the generated markdown report first. Fix
the smallest failing surface, rerun the focused test for the changed area, and
then rerun the full closed-beta smoke inside the dev container.

Do not mark closed-beta readiness complete from host-only execution.
