# FormOwl System Backbone Agent Goal

## Role

FormOwl System Backbone Agent.

Durable role definition: `docs/agent-roles.md`.

Status: `active`

## Abstract

This file is the durable goal placeholder for the agent running on the other
machine. The owning agent should fill in its exact objective, status, blockers,
last verified commit, current owner paths, and next action before relying on
session-local state.

The system backbone track exists to build and harden the container-first
product and service skeleton that lets the Knowledge Graph Research Agent's
contracts and algorithms run safely. Its work should preserve governed
task-oriented interfaces and keep raw files, databases, object stores, worker
scratch paths, parser internals, and backend control planes out of
ChatGPT-facing tools.

## Expected Scope

Likely owned by this agent:

- Repository, container, dev-container, compose/runtime, and CI verification
  wiring.
- MCP transport, gateway plumbing, tool schemas, safe error envelopes, and
  session context handling.
- Project MCP and Wiki MCP service boundaries.
- Upload sessions, storage backend registry configuration, object-store
  integration, worker execution boundaries, and database-backed stores.
- Operational audit, logging, configuration loading, migrations, smoke
  harnesses, and production adapter boundaries.
- Retrieval gateway behavior for evidence snippets and raw asset access through
  FormOwl locators and permission checks.

## Current Objective

Continue the FormOwl System Backbone track after completing the Project MCP
real-backend adapter milestone, the Project/Wiki MCP JSON-RPC compatibility
gateway, and public tool schemas/error envelopes for the current gateway
surface, and retrieval gateway completion for governed evidence/raw-asset
access, plus storage backend registry configuration for local-first and
metadata-only object-store descriptors, worker execution, PostgreSQL-backed
ingestion record stores, the closed-beta readiness smoke, the local data
resource folder ingestion MVP, backend-specific Wiki MCP publish proposals, and
database-backed ingestion store same-interface workflow evidence. The remaining
work-board backbone blockers are complete on branch
`complete-remaining-backbone-slices` without claiming production readiness.

## Current Status

`active`

The latest remote merge is present at commit `9ba1528`. Merge conflicts from
the pre-merge stash were resolved by keeping the merged upstream versions for
shared KG/contract/wiki files.

The Project MCP real-backend adapter milestone is complete and verified. It is
one FormOwl backbone integration milestone, not the whole FormOwl plan.

The Project/Wiki MCP JSON-RPC compatibility gateway is also complete for the
current prototype server objects. Legacy JSON-line entrypoints remain available
for local testing, but existing Project/Wiki behavior now has JSON-RPC
transport coverage.

Public gateway schemas and safe error envelopes now cover upload, ingestion,
observation listing, candidate graph, access, and wiki projection workflows.
Unconfigured handlers return safe pending-review envelopes rather than backend
controls or raw implementation details.

Retrieval gateway plumbing now supports answer-only, evidence-snippet, and
raw-asset request modes. Raw-asset mode requires explicit
`asset_scoped_access` and returns governed FormOwl asset locators through an
injectable resolver path without returning raw content.

Storage backend registry configuration now exists in
`formowl_ingestion.storage`. Local filesystem backends can be configured from
environment values or structured JSON descriptors, while non-local descriptors
such as MinIO/S3-compatible backends require explicit stable backend ids and
remain metadata-only until concrete object-store adapters are added.

The `formowl_worker` package now provides the first ingestion worker boundary.
It processes pending `IngestionJob` records through the existing
`run_ingestion_job` path, respects backend `allowed_workers`, and keeps worker
lease/retry policy out of the job contract until database-backed coordination
lands.

PostgreSQL-backed ingestion record stores now exist behind the same
create/get/list surfaces as the file-backed `AssetStore`, `JobStore`,
`ExtractorRunStore`, `ObservationStore`, and `UploadSessionStore`. This is a
mocked-connection adapter-contract slice using parameterized SQL statements,
validated contract payloads, safe record ids, and the existing
`PostgreSQLUnitOfWork` rollback boundary. It does not expose database controls
through MCP or claim live PostgreSQL readiness.

The closed-beta readiness smoke now exists as a synthetic, trusted internal
gate. It composes Project/Wiki JSON-RPC, storage backend public-envelope
redaction, worker ingestion, observation-to-wiki draft bridging, governed
retrieval grant checks and raw-asset references, and the packaged KG-eval
facade. It does not claim production readiness, live database readiness,
automatic publishing, raw asset content access, canonical graph writes, or mail
adapter readiness. Its implementation, dev-container verification, and
user-authorized 3-reviewer test-hardening gate are complete.

The local data resource folder ingestion MVP now provides a trusted internal
folder scanner for issue #9. It uses caller-held stability snapshots before any
durable writes, registers stable files as normal FormOwl assets, creates
idempotent ingestion jobs, can run configured deterministic `.txt` / `.md`
extraction through the existing plain-text extractor, persists extractor runs
and observations, and returns a safe public scan report without trusted folder
paths, source filenames, object-store roots, parser-local paths, or internal
stability tokens. This is generic infrastructure only; it does not implement
mail parsing, financial reconciliation, canonical graph writes, or wiki
publishing.

Backend-specific Wiki MCP publish proposals now route through
`WikiPublishAdapterRegistry`. The current OpenProject Wiki adapter prepares
safe `upsert_wiki_page` proposals with sanitized target fields, content/diff
hashes, source references, `publish_mode: proposal_only`,
`automatic_publish_enabled: false`, and `external_write_performed: false`.
Target API URLs, tokens, raw paths, SQL-like values, and backend-internal fields
are omitted or rejected before any publish side effect. This does not implement
automatic publishing or live OpenProject Wiki writes.

The database-backed store item is now closed as container-backed
same-interface adapter evidence. The ingestion helpers depend on shared store
protocols, and the same asset registration, job creation, extractor execution,
run persistence, and observation persistence workflow runs against both
file-backed stores and PostgreSQL-backed stores. This remains an internal
adapter boundary: it does not expose database controls through MCP and does not
claim live PostgreSQL deployment or production readiness.

## Owner Paths

- `python/formowl_project_mcp/adapters/openproject/`
- `python/formowl_project_mcp/storage/evidence_snapshot_store.py`
- `python/formowl_project_mcp/tools/project_tools.py`
- `docs/openproject-adapter.md`
- `tests/test_openproject_adapter.py`
- `python/formowl_ingestion/storage/config.py`
- `python/formowl_ingestion/storage/postgres.py`
- `python/formowl_graph/storage/migrations/003_ingestion_records.sql`
- `python/formowl_worker/`
- `scripts/closed_beta_smoke.py`
- `tests/test_closed_beta_smoke_script.py`
- `docs/closed-beta-runbook.md`
- `python/formowl_ingestion/folder_inbox.py`
- `python/formowl_ingestion/storage/interfaces.py`
- `python/formowl_wiki_mcp/adapters/`
- `python/formowl_wiki_mcp/tools/wiki_tools.py`
- `tests/test_local_folder_ingestion.py`
- `tests/test_database_backed_ingestion_workflow.py`
- `tests/test_wiki_mcp.py`
- `docs/local-data-resource-inbox.md`
- `docs/wiki-draft-schema.md`
- `docs/workflows.md`
- `docs/infra-spec.md`
- `docs/implementation-task-breakdown.md`
- `README.md`

## Acceptance Criteria

- Real OpenProject reads use a bounded HTTP client, same-origin HAL links, and
  mocked tests with no live credentials.
- Mapping preserves source refs for work packages, activities, relations, and
  attachments without leaking raw or internal locators.
- Project writes remain proposal-only.
- Evidence snapshots are written atomically and incomplete snapshots are not
  retrievable.
- Focused Project MCP real-backend adapter tests pass in the dev container.
- Full test suite passes in the dev container.
- The user-requested 6-reviewer OpenProject gate remains recorded with no
  blocking findings.
- Closed-beta smoke passes in the dev container while preserving proposal-only
  publishing, raw/internal leak guards, governed raw-asset references, KG-eval
  facade boundaries, and no canonical graph writes.
- Local folder inbox MVP passes focused and full dev-container checks, defers
  unstable files with zero durable side effects, keeps public scan output
  redacted, and passes the default 3-reviewer gate.
- Wiki publish adapters return backend-specific proposals while preserving
  proposal-only publishing, automatic-publish disablement, safe target
  redaction, and no external write side effects.
- File-backed and PostgreSQL-backed ingestion record stores pass the same
  asset/job/run/observation workflow through shared interfaces without
  exposing database controls or claiming live PostgreSQL readiness.

Canonical verification commands:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local \
  python -m unittest discover -s tests -p 'test_openproject_adapter.py'

docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local \
  python -m unittest discover -s tests

docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local \
  python scripts/closed_beta_smoke.py --output /tmp/formowl-closed-beta-smoke.json
```

Latest verification:

- Focused adapter tests: 22 tests OK.
- OpenProject slice Ruff check and format check: passed.
- Full canonical dev-container suite: 278 tests OK.
- Project/Wiki JSON-RPC focused tests: 4 tests OK.
- Semantic JSON-RPC focused tests: 5 tests OK.
- Gateway Ruff check and format check: passed.
- Full canonical dev-container suite after JSON-RPC gateway changes:
  282 tests OK.
- Public schema/error-envelope focused tests: 8 tests OK.
- Project/Wiki JSON-RPC regression after schema expansion: 4 tests OK.
- Full canonical dev-container suite after public schema/error-envelope
  changes: 283 tests OK.
- Retrieval gateway focused tests: 8 tests OK.
- Retrieval Ruff check and format check: passed.
- Full canonical dev-container suite after retrieval gateway changes:
  286 tests OK.
- Storage backend registry focused tests: 7 tests OK.
- Ingestion package export regression: 1 test OK.
- Storage config changed-file Ruff check and format check: passed.
- Full canonical dev-container suite after storage registry configuration:
  289 tests OK.
- Ingestion worker focused tests: 3 tests OK.
- Worker changed-file Ruff check and format check: passed.
- Full canonical dev-container suite after worker boundary: 292 tests OK.
- PostgreSQL ingestion store focused tests: 20 tests OK.
- Ingestion package export regression after PostgreSQL store exports:
  1 test OK.
- PostgreSQL ingestion store touched-file Ruff check and format check: passed.
- Full canonical dev-container suite after PostgreSQL ingestion store slice:
  302 tests OK.
- Closed-beta smoke focused tests: 14 tests OK.
- Closed-beta smoke CLI:
  `python scripts/closed_beta_smoke.py --output /tmp/formowl-closed-beta-smoke.json`
  exited 0 in the dev container.
- Ruff check and format check for `python`, `tests`, and `scripts`: passed.
- Full canonical dev-container suite after closed-beta smoke slice:
  316 tests OK.
- Closed-beta smoke 3-reviewer test-hardening gate: passed 3/3 with
  `closed_beta_reviewer_engineering`, `closed_beta_reviewer_safety`, and
  `closed_beta_reviewer_release` after accepted validation/status findings were
  fixed and re-reviewed.
- Local folder inbox focused tests: 10 tests OK.
- Ingestion package export regression after folder inbox export: 1 test OK.
- Ruff check and format-check for `python`, `tests`, and `scripts`: passed.
- Full canonical dev-container suite after local folder inbox slice:
  326 tests OK.
- Local folder inbox 3-reviewer gate: passed 3/3 with
  `folder_inbox_gate_engineering_v2`, `folder_inbox_gate_safety_v2`, and
  `folder_inbox_gate_release_v3`; the safety blocker about public
  `source_file_token` exposure was fixed and re-reviewed.
- Backend-specific Wiki MCP publish adapter focused tests: 4 tests OK.
- Database-backed same-interface ingestion workflow focused tests: 3 tests OK.
- Ingestion package export regression after store protocol exports: 1 test OK.
- Project/Wiki JSON-RPC regression after Wiki publish adapter change:
  4 tests OK.
- Closed-beta smoke script regression after remaining slices: 14 tests OK.
- Closed-beta smoke CLI after remaining slices:
  `python scripts/closed_beta_smoke.py --output /tmp/formowl-closed-beta-smoke.json`
  exited 0 in the dev container.
- Ruff check and format-check for `python`, `tests`, and `scripts`: passed.
- Full canonical dev-container suite after remaining backbone slices:
  352 tests OK.
- Remaining backbone slices 3-reviewer gate: passed 3/3 with
  `remaining_slices_engineering_reviewer`,
  `remaining_slices_safety_reviewer`, and
  `remaining_slices_release_reviewer`; no blocking findings remained.

## Known Blockers And Dependencies

- `.test-tmp-resume/` is an untracked host-side test artifact with permission
  denied subdirectories. It is not part of the OpenProject slice.
- Pre-merge graph/wiki untracked test artifacts from the local stash were
  removed because they duplicated or predated merged KG/user-graph/wiki
  projection work and caused `unittest discover` import failures.
- System Backbone integrations that need KG acceptance status should use
  `formowl_kg_eval` / `formowl-kg-eval summary`, not direct imports from
  `.formowl/kg-eval`.

## Last Verified Commit And Branch

- Branch: `complete-remaining-backbone-slices`
- Base remote commit: `e469a0e`
- Canonical dev-container verification passed after the backend-specific Wiki
  adapter and database-backed store same-interface workflow slices.

## Next Action

The user explicitly assigned issue #5 follow-up on 2026-06-30. The synthetic
mail phase is now implemented in repository code, tests, and docs: normalized
fixture observations, local evidence packs/search, candidate-only bridge,
case-progress QA, integration coverage, and preflight readiness artifact. Do
not treat this as production PST/OST/MSG/EML parser readiness or real mailbox
support; that remains a separate future assignment.

## Handoff Notes For KG Research Agent

The System Backbone Agent will not edit KG-eval internals or expose
`.formowl/kg-eval` paths through MCP. The packaged `formowl_kg_eval` facade is
the integration boundary for product-facing status.

## Boundary Reminder

The system backbone work must not collapse ingestion, graph governance, user
graph assembly, and wiki projection into one direct pipeline. It should provide
stable infrastructure and service boundaries that allow the KG research layer
to evolve without rewriting service plumbing.
