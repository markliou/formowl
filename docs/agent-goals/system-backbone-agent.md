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

2026-07-04 priority reset: use issue #21, `Mail Evidence Reading via FormOwl
MCP`, as the active mail milestone. Do not continue issue #5 as the main line
of work. The issue #5 synthetic mail phase can be retained only as reusable
foundation: normalized JSON fixture observations, local evidence packs/search,
candidate-only bridge, case-progress QA helpers, and preflight artifact.
GitHub issue #5 was merged into #21 and closed as a duplicate on 2026-07-04.

Checkpoint O on 2026-07-06 proved the scoped local product-facing evidence
path for issue #21. The historical target path was:

```text
mail archive fixture
  -> governed Asset / IngestionJob / ExtractorRun / mail Observations
  -> retrieval or evidence-query handoff
  -> FormOwl MCP / JSON-RPC query surface
  -> permission-filtered mail evidence or case-progress answer with citations
  -> ChatGPT-free local harness
```

As of checkpoint O, the governed MCP evidence query path, denied-scope
behavior, raw/internal leak guards, cited case-progress answer path, and local
ChatGPT-free verification harness are implemented, reviewer-gated, and verified
in the dev container for synthetic normalized mail evidence. The completed
scope does not depend on the older synthetic `formowl_mail` helpers alone, and
it does not add live mailbox access, raw parser paths, parser-side QA,
parser-side candidate writes, canonical graph writes, direct wiki projection,
or production readiness claims.

2026-07-05 PM decision from GitHub #22 supersedes any Companion-first reading
of the mail plan. Phase 1 must support ordinary non-technical users uploading a
full PST archive through a session-bound FormOwl upload surface / iframe:

```text
User uploads full PST through UploadSession-bound surface
  -> PST enters ingest staging
  -> server-side worker parses incrementally
  -> PostgreSQL stores normalized mail evidence
  -> raw PST is deleted or retention-controlled after successful extraction
  -> governed FormOwl MCP / JSON-RPC queries normalized evidence
```

Local Companion remains an optional / advanced / policy-triggered path for
rolling repeated PST imports, privacy-sensitive imports, bandwidth-limited
sites, or manifest-first workspace policy. Server-side parsing and Companion
parsing must emit the same `MailEvidenceBundle` contract. NAS/object storage is
storage, not parser or dedup compute. PostgreSQL normalized mail evidence is
the Phase 1 operational evidence layer; KG construction is Phase 2.

The issue-specific gate for #21 is stricter than the repository default:
every completed #21 implementation or durable handoff slice requires 6
effective read-only Codex/GPT subagent reviewers with explicit
`RELEASE_DECISION: AGREE`. Antigravity/`agy` remains disabled by default and
must not be faked or substituted.

2026-07-05 MailEvidenceBundle contract checkpoint: the Phase 1
`MailEvidenceBundle` contract/builder slice is implemented in
`python/formowl_mail/bundle.py`, exported from `formowl_mail`, and hardened
with focused tests in `tests/test_mail_evidence_bundle.py`. The slice covers
same-shape parser producer types, explicit server-side `UploadSession`
identity, occurrence-preserving archive/message/folder/attachment lineage,
archive-independent logical message fingerprints, duplicate carrier imports,
required lineage arrays, retention enum validation, public raw/backend/SQL and
secret-assignment guards, and no file/tree side effects. It is not the full
#21 MCP/JSON-RPC evidence query path and does not implement real PST parsing.
Supplemental host checks passed: touched-file `py_compile`, focused mail tests
17 OK, extraction edge tests 13 OK, and `git diff --check`. The issue-specific
6-reviewer code/test gate agreed after blocker fixes with `Goodall`, `Curie`,
`Mill`, `Hilbert`, `Euclid`, and `Jason`. Canonical dev-container verification
is still blocked because Docker Desktop reports `Docker Desktop is unable to
start`; do not mark the slice or #21 complete until the required container
checks run.

2026-07-05 MCP/JSON-RPC mail evidence query checkpoint B is implemented but
not complete. The current slice adds `python/formowl_mail/query.py`, exports
the query gateway from `formowl_mail`, adds `query_mail_evidence` to
`SemanticMcpGateway`, binds JSON-RPC tool calls to the authenticated session
identity, and adds focused coverage in `tests/test_mail_evidence_mcp_gateway.py`
plus semantic gateway regressions. It queries normalized `MailEvidenceBundle`
records only; it does not implement real PST parsing, upload UI, PostgreSQL
mail tables, case-progress QA, KG writes, or wiki projection. Reviewer blockers
found and fixed so far: JSON-RPC identity override, forged public `grants`,
missing invalid-grant denial coverage, and missing
`mail_evidence_bundle_id` JSON-RPC coverage. Latest supplemental host checks
passed: mail evidence MCP tests 9 OK, semantic gateway tests 8 OK, semantic
JSON-RPC tests 5 OK, `test_mail_*.py` 26 OK, extraction edge tests 13 OK,
touched-file `py_compile`, long-line scan, and `git diff --check`. The
checkpoint B reviewer gate passed 6/6 after blocker fixes with `Socrates`,
`Cicero`, `Euler`, `Ptolemy`, `Hume`, and `Halley`; accepted blockers covered
JSON-RPC identity override, forged public `grants`, invalid-grant denial
coverage, `mail_evidence_bundle_id` JSON-RPC coverage, and stale durable docs.
Canonical dev-container verification is still blocked by Docker Desktop unable
to start, and #21 remains open for the upload/parser/PostgreSQL/full harness
requirements.

2026-07-05 checkpoint C is implemented and passed the issue-specific 6/6
reviewer gate: a ChatGPT-free mail evidence MCP smoke harness at
`scripts/mail_evidence_mcp_smoke.py` with tests in
`tests/test_mail_evidence_mcp_smoke_script.py`. It creates a synthetic mail
archive, registers it as a governed asset, creates and runs an ingestion job
through `FixtureMailArchiveExtractor`, builds a normalized `MailEvidenceBundle`,
and exercises JSON-RPC `query_mail_evidence` owner, denied, forged-grant,
trusted-grant, and bundle-id paths. The public report contains hashes, statuses,
counts, and claim boundaries only; it must not expose mail body text, raw paths,
SQL, backend locators, or production readiness claims. Accepted reviewer
blockers fixed CLI coverage, report validation, body-leak checks,
work-directory sentinel behavior, deterministic safe outputs, owner-matched
trusted grants, exact report contracts, and unknown-key no-echo behavior.
Effective reviewers `Poincare`, `Hooke`, `Schrodinger`, `James`, `Gibbs`, and
`Pasteur` returned `RELEASE_DECISION: AGREE` before the post-gate host
portability fix. A follow-up Windows host portability hardening changed
`tests/_paths.py` to avoid `os.getuid()` when unavailable and changed the smoke
CLI default work directory from hard-coded `/tmp` to the platform temp
directory. A fresh recheck of the latest diff passed 6/6 with `Poincare`,
`Hooke`, `Schrodinger`, `James`, `Gibbs`, and `Pasteur`. Supplemental host
checks after latest validation hardening and host portability fix: smoke tests
13 OK, direct smoke CLI exited 0 with validation passed, mail evidence MCP
tests 9 OK, semantic gateway tests 8 OK, semantic JSON-RPC tests 5 OK,
`test_mail_*.py` 39 OK, extraction edge tests 13 OK, touched-file
`py_compile`, long-line scan, and `git diff --check` passed. Canonical
dev-container verification is still blocked by Docker Desktop unable to start,
and #21 remains open for the upload/parser/PostgreSQL/full path requirements.

2026-07-05 checkpoint D is implemented and reviewer-gated: a
normalized PostgreSQL mail evidence adapter contract at
`python/formowl_mail/postgres.py`, migration
`python/formowl_graph/storage/migrations/004_mail_evidence.sql`, package
exports from `formowl_mail`, and focused tests in
`tests/test_mail_evidence_postgres.py`. The slice stores `MailEvidenceBundle`
rows across the 12 Phase 1 mail evidence tables, rehydrates bundles by
`mail_import_session_id` or `mail_evidence_bundle_id`, provides a
store-backed `query_mail_evidence` handler, builds parameterized SQL only,
adds import-session query indexes, preserves duplicate logical message and
attachment occurrences without overwriting logical rows, round-trips
attachment, quoted candidate, embedded relation, and parse-warning rows,
validates unsafe ids and unsafe public query inputs before store side effects,
and represents rollback through `PostgreSQLUnitOfWork`. The checkpoint D
reviewer gate passed 6/6 after blocker fixes with `Anscombe`, `Erdos`,
`Dirac`, `Plato`, `Maxwell`, and `Planck`. Latest supplemental host checks
passed: focused mail evidence
PostgreSQL tests 6 OK, PostgreSQL adapter contract tests 11 OK, mail tests 45
OK, PostgreSQL tests 20 OK, focused mail evidence MCP tests 9 OK,
touched-file `py_compile`, long-line scan, and `git diff --check`. This is
still a mocked-connection adapter-contract slice only; it does not implement
real PST parsing, upload UI / iframe, live PostgreSQL readiness, production
worker leasing, KG writes, wiki projection, or ChatGPT-facing database
controls. Canonical dev-container verification remains blocked: host Docker
API access first failed, and the escalated canonical command reached Docker but
returned `Docker Desktop is unable to start`. #21 remains open for canonical
dev-container verification plus upload/parser/full-path requirements.

2026-07-05 checkpoint E is implemented and passed the issue-specific
6-reviewer gate: an UploadSession-bound server-side mail import workflow at
`python/formowl_mail/import_workflow.py`, package exports from `formowl_mail`,
and focused tests in `tests/test_mail_upload_import_workflow.py`. The slice
requires an existing matching mail `UploadSession` before durable side effects,
registers the staged archive as a normal `Asset`, creates/runs an
`IngestionJob` through `FixtureMailArchiveExtractor`, builds a server-side
`MailEvidenceBundle` carrying `upload_session_id`, writes it through
`PostgreSQLMailEvidenceStore` inside `PostgreSQLUnitOfWork`, verifies a
store-backed JSON-RPC `query_mail_evidence` owner path, and updates the
UploadSession to succeeded only after the evidence-store write and query path
succeed. Focused tests cover invalid-session no-write behavior, public-summary
leak/overclaim rejection, duplicate rolling upload storage pressure
(`payload.bin` shared by content hash) with occurrence-preserving logical mail
dedup, and evidence-store rollback/session failure behavior. Reviewer blockers
strengthened the session binding contract so new `UploadSession` records
persist `session_id` and the workflow rejects a mismatched session before side
effects; focused coverage also proves parser/job failure marks the
UploadSession failed without PostgreSQL mail evidence side effects.
Reviewer gate passed 6/6 after blocker fixes with `Carson`, `Galileo`,
`Einstein`, `Ohm`, `Sartre`, and `Laplace` returning explicit
`RELEASE_DECISION: AGREE`; no blocking findings remain.
Supplemental host checks passed: upload import workflow tests 7 OK, upload
session tests 3 OK, contract tests 8 OK, mail tests 52 OK, PostgreSQL tests 20
OK, semantic MCP tests 13 OK, touched-file `py_compile`, directly touched-file
long-line scan, and `git diff --check`. Host `ruff` is unavailable; full host
unittest is not clean due unrelated Windows temp-directory permission errors in
KG-eval/benchmark tests and one pre-existing local-folder observation ordering
difference. Canonical dev-container verification remains blocked: host Docker
API access first failed, and the escalated canonical command reached Docker but
returned `Docker Desktop is unable to start`. This is still a synthetic/internal
workflow slice: it does not implement real PST parsing, upload UI / iframe,
live PostgreSQL readiness, production worker leasing, KG writes, wiki
projection, production readiness, or a direct ChatGPT production connection.

2026-07-05 checkpoint F is implemented and passed the issue-specific
6-reviewer gate: a ChatGPT-facing mail archive upload task/session entrypoint
at `python/formowl_mail/upload_session.py`, package exports from
`formowl_mail`, injectable `SemanticMcpGateway.open_upload_session` handler
support, and focused tests in `tests/test_mail_upload_session_gateway.py`.
The slice creates an audited `UploadSession` and returns a session-bound mail
upload task card with `formowl_upload_session:<upload_id>` as the public
locator, source-preparation guidance, PST/OST/MSG/EML/MBOX accepted types, and
claim boundaries that explicitly deny real iframe, real PST parser, live
PostgreSQL readiness, production worker leasing, KG writes, wiki projection,
and production readiness. It hardens the public input surface with exact
top-level allowlists, camelCase ignored-key rejection, nested
infrastructure-control rejection, owner-scope allowlisting, visibility-scope
allowlisting, restricted matching `permission_scope`, validator overclaim
checks, generic error redaction, audit failure no-write behavior, and audit
rollback if session-store creation fails. Reviewer gate passed 6/6 after
blocker fixes with `Hegel`, `Pauli`, `Leibniz`, `Kuhn`, `Volta`, and
`Avicenna` returning explicit `RELEASE_DECISION: AGREE`; no blocking findings
remain. Supplemental host checks passed: mail upload session gateway tests
8 OK, upload session tests 5 OK, semantic MCP tests 8 OK, semantic JSON-RPC
tests 5 OK, mail upload import workflow tests 7 OK, mail evidence MCP tests
9 OK, ingestion package tests 1 OK, contract glob tests 8 OK, touched-file
`py_compile`, touched-file long-line scan, and `git diff --check`. Canonical
dev-container verification remains blocked because Docker Desktop reports
`Docker Desktop is unable to start`. This is not a completed #21 claim: the
real upload iframe/surface, real PST parser, live PostgreSQL deployment,
production worker leasing, and ChatGPT smoke test remain open.

2026-07-05 checkpoint G is implemented and passed the issue-specific
6-reviewer gate: configured semantic JSON-RPC runtime wiring for the
ChatGPT-facing mail upload task-card path. `python/formowl_gateway/jsonrpc.py`
now provides `create_mail_upload_semantic_jsonrpc_gateway()`,
`python/formowl_gateway/cli.py` is the command wrapper, and `pyproject.toml`
registers `formowl-semantic-mcp-jsonrpc`. This runtime wires
`open_upload_session` to the mail upload session handler with file-backed
`UploadSessionStore` and `FileAuditLogStore`, uses sanitized environment
session identity, and serves stdin/stdout JSON-RPC so a ChatGPT MCP command can
reach the configured mail upload task-card path. Reviewer blockers fixed the
direct module `RuntimeWarning`, non-object JSON line traceback behavior,
secret-like env session leakage, and gateway startup traceback behavior for bad
data-dir/store initialization. Reviewer gate passed 6/6 after blocker fixes
with `Kierkegaard`, `Helmholtz`, `Beauvoir`, `Carver`, `Hubble`, and
`Chandrasekhar` returning explicit `RELEASE_DECISION: AGREE`; no blocking
findings remain. Supplemental host checks passed: semantic JSON-RPC gateway
tests 11 OK, mail upload session gateway tests 8 OK, semantic MCP gateway
tests 8 OK, upload session tests 5 OK, touched-file `py_compile`, and
`git diff --check` with CRLF warnings only. Canonical dev-container
verification remains blocked because Docker Desktop reports
`Docker Desktop is unable to start`. This is still not a completed #21 claim:
the real upload iframe/surface, real mail parser, live PostgreSQL deployment,
production worker leasing, and ChatGPT smoke test remain open.

2026-07-05 checkpoint H is implemented and passed the issue-specific
6-reviewer gate: a ChatGPT-compatible mail upload MCP command preflight at
`scripts/mail_upload_mcp_command_smoke.py`, with focused tests in
`tests/test_mail_upload_mcp_command_smoke_script.py`. The smoke launches the
documented `formowl-semantic-mcp-jsonrpc` console command through a subprocess,
sends JSON-RPC `initialize`, `tools/list`, and
`tools/call open_upload_session`, verifies the command lists
`open_upload_session`, returns a valid `status=ok` mail upload task card, and
persists an `UploadSession` bound to the configured MCP session identity. The
task-card `upload_session_id` and `formowl_upload_session:<upload_id>` locator
must resolve to that exact persisted record. Reviewer hardening added
infrastructure-control rejection with no upload-session or audit side effects,
safe non-object report validation, exact response/hash/count validation,
distinct response hashes, bool-as-int count rejection, secret-like public
report value rejection, startup-failure redaction, and fixed command-surface
wording. Reviewer gate passed 6/6 after blocker fixes with `Gauss`, `Singer`,
`Aquinas`, `Aristotle`, `Epicurus`, and `Godel` returning explicit
`RELEASE_DECISION: AGREE`; no blocking findings remain. Supplemental host
checks passed: H smoke tests 10 OK, direct PATH-shim command smoke and
`--validate-report` exited 0, semantic JSON-RPC tests 11 OK, mail upload
session gateway tests 8 OK, `test_mail_*.py` 70 OK, touched-file
`py_compile`, direct line-length scan, and `git diff --check` with CRLF
warnings only. Host Ruff remains unavailable. Canonical dev-container
verification remains blocked because Docker Desktop reports
`Docker Desktop is unable to start`. This is still not a completed #21 claim:
the real upload iframe/surface, file transfer, real mail parser, live
PostgreSQL deployment, production worker leasing, and actual ChatGPT connected
smoke test remain open.

2026-07-05 checkpoint I is implemented and passed the issue-specific
6-reviewer gate: UploadSession-bound backend upload-surface intake at
`python/formowl_mail/upload_surface.py`, public exports from `formowl_mail`,
rollback support in file-backed `AssetStore` and `FileObjectStore`,
`upload_session_file_received` audit logging, an import-workflow path for
UploadSessions that already have a registered `asset_id`, and focused tests in
`tests/test_mail_upload_surface.py` plus
`tests/test_mail_upload_import_workflow.py`. The slice lets a trusted server
upload surface receive a server-staged PST/OST/MSG/EML/MBOX upload for an
existing matching mail `UploadSession`, reject mismatched
actor/session/profile/status and user-supplied infrastructure controls before
side effects, register the upload as a governed `Asset` and ObjectStore
payload, bind `UploadSession.asset_id`, write asset and upload-receipt audit
events, reuse duplicate object payload bytes for rolling PST exports, and
return only a hash/status/count public receipt. Reviewer blockers fixed during
the gate: duplicate-preexistence detection now uses verified object payload
state instead of metadata presence; metadata-only or corrupt object records are
rolled back as newly written side effects; bound-asset import requires
`uploading` / `archive_uploaded` receipt state and an Asset `source_ref` bound
to the same UploadSession before job/run/observation/evidence side effects;
and the public receipt explicitly denies actual ChatGPT connected upload with
`supports_actual_chatgpt_connected_upload_claim=false`. Reviewer gate passed
6/6 with `Pascal`, `Bacon`, `Mencius`, `Locke`, `Faraday`, and `Tesla`
returning explicit `RELEASE_DECISION: AGREE`; no blocking findings remain.
Supplemental host checks after reviewer blocker fixes passed: upload surface
tests 8 OK, mail upload import workflow tests 9 OK, `test_mail_*.py` 80 OK,
semantic JSON-RPC gateway tests 11 OK, mail upload session gateway tests 8 OK,
upload session tests 5 OK, ingestion package regression 1 OK, object store
tests 7 OK, store edge tests 7 OK, workflow edge tests 8 OK, upload asset
reference tests 2 OK, touched-file `py_compile`, touched-file line-length
scan, and `git diff --check` with CRLF warnings only. This is backend upload
intake / file-transfer receipt only. It does not implement the actual iframe
UI, actual ChatGPT connected upload, real mail parser, live PostgreSQL
deployment, production worker leasing, KG writes, wiki projection, production
readiness, or a completed #21 claim. Canonical dev-container verification
remains blocked because Docker Desktop reports `Docker Desktop is unable to
start`.

2026-07-05 checkpoint J is implemented and passed the issue-specific
6-reviewer gate: a local
HTTP mail upload-surface contract harness at `python/formowl_mail/upload_http.py`,
public exports from `formowl_mail`, focused tests in
`tests/test_mail_upload_http_surface.py`, and docs in `README.md` and
`docs/workflows.md`. The stdlib `ThreadingHTTPServer` handler renders `GET
/mail/upload/<upload_session_id>` as a single-session mail archive form and
accepts `POST /mail/upload/<upload_session_id>` multipart uploads with one
`mail_archive` file. It validates route/form/workspace binding,
`Content-Length`, multipart boundary, duplicate file/field parts, parser
defects such as missing close boundary, short HTTP body reads, supported
filename, request size, actor/session/status, and user-supplied
storage/parser/worker fields before durable side effects; stages bytes only
temporarily; calls the backend `receive_mail_archive_upload()` helper; removes
the temporary staged body; and returns a safe JSON receipt. Supplemental host
checks before reviewer gate passed: HTTP upload surface tests 11 OK, backend
upload surface regression tests
8 OK, mail upload session gateway tests 8 OK, mail upload import workflow tests
9 OK, clean-temp-root `test_mail_*.py` 91 OK, touched-file `py_compile`
passed, touched-file line-length scan passed, and `git diff --check` passed
with CRLF warnings only. Reviewer blockers fixed during the gate: wrong and
missing `workspace_id` route/form binding tests, duplicate `mail_archive` file
and duplicate hidden-field tests, and truncated multipart / short-read parser
hardening with no durable side effects. Reviewer gate passed 6/6 after blocker
fixes with `Popper`, `Russell`, `Peirce`, `Huygens`, `Turing`, and
`Heisenberg` returning explicit `RELEASE_DECISION: AGREE`; no blocking
findings remain. This is a local HTTP contract harness for future iframe/portal
integration, not actual ChatGPT connected upload, production iframe readiness,
real mail parser readiness, live PostgreSQL deployment, production worker
leasing, KG writes, wiki projection, production readiness, or a completed #21
claim. Canonical dev-container verification remains blocked because Docker
Desktop reports `Docker Desktop is unable to start`.

2026-07-05 checkpoint K is implemented and passed the issue-specific
6-reviewer gate: a local MCP-command-to-HTTP mail upload smoke at
`scripts/mail_upload_mcp_http_smoke.py`, focused tests in
`tests/test_mail_upload_mcp_http_smoke_script.py`, and docs in `README.md`
and `docs/workflows.md`. The smoke launches the configured
`formowl-semantic-mcp-jsonrpc` command, sends JSON-RPC `initialize`,
`tools/list`, and `tools/call open_upload_session`, resolves the persisted
`UploadSession`, starts the local HTTP upload surface with the same data
directory and trusted session identity, posts synthetic multipart PST bytes to
`/mail/upload/<upload_session_id>`, verifies `UploadSession.asset_id`,
Asset/ObjectStore/audit side effects, staging cleanup, and a safe
hash/status/count public report. Negative probes cover missing route, wrong
session route, wrong workspace, user-supplied infrastructure fields, duplicate
multipart files, malformed multipart, oversized bodies, and command startup
redaction with no durable upload side effects. Supplemental host checks before
reviewer gate passed: MCP HTTP smoke tests 7 OK, MCP command preflight
regression 10 OK, local HTTP upload surface tests 11 OK, `test_mail_*.py`
98 OK, touched-file `py_compile`, touched-file line-length scan, and
`git diff --check` with CRLF warnings only. Reviewer gate passed 6/6 with
`Descartes`, `Bohr`, `Ampere`, `Hypatia`, `Sagan`, and `Rawls` returning
explicit `RELEASE_DECISION: AGREE`; no blocking findings remain. This is a local
MCP-command-to-HTTP upload contract smoke only. It does not implement actual
ChatGPT connected upload, production iframe readiness, real mail parser, live
PostgreSQL deployment, production worker leasing, KG writes, wiki projection,
production readiness, or a completed #21 claim. Canonical dev-container
verification remains blocked because Docker Desktop reports
`Docker Desktop is unable to start`.

2026-07-05 checkpoint L is implemented and passed the issue-specific
6-reviewer gate: a local upload-to-import-and-query smoke at
`scripts/mail_upload_mcp_http_import_smoke.py`, focused tests in
`tests/test_mail_upload_mcp_http_import_smoke_script.py`, docs in `README.md`
and `docs/workflows.md`, query-verification rollback hardening in
`python/formowl_mail/import_workflow.py`, and Windows host JSON temp-replace
hardening in `python/formowl_ingestion/storage/records.py`. The smoke launches
the configured `formowl-semantic-mcp-jsonrpc` command, sends JSON-RPC
`initialize`, `tools/list`, and `tools/call open_upload_session`, uploads a
synthetic JSON-backed mail fixture through the local HTTP surface with the same
`UploadSession`, runs `run_upload_session_mail_import()` against the bound
`asset_id`, writes normalized mail evidence through the PostgreSQL adapter
contract, verifies store-backed JSON-RPC `query_mail_evidence` owner and denied
paths, and emits only hash/status/count public report data. Negative probes
cover missing bound asset, wrong asset `source_ref`, parser failure,
evidence-store failure, and query-verification failure. Reviewer blockers
fixed during the gate: evidence writes and verification query now share one
transaction so query-verification failure rolls back normalized mail evidence
rows before the UploadSession remains failed; denied store-backed query
validation now proves zero visible results, zero citations, hidden bundle
count, and strict `int` zero rather than a bool-as-int bypass. Supplemental
host checks after blocker fixes passed: upload-to-import smoke tests 7 OK,
upload import workflow tests 9 OK, MCP HTTP upload smoke tests 7 OK, local HTTP
upload surface tests 11 OK, MCP command preflight tests 10 OK, `test_mail_*.py`
105 OK, touched-file `py_compile`, touched-file long-line scan, and
`git diff --check` with CRLF warnings only. Reviewer gate passed 6/6 with
`Kepler`, `Archimedes`, `Kant`, `Dewey`, `Dalton`, and `Confucius` returning
explicit `RELEASE_DECISION: AGREE` after blocker fixes; no blocking findings
remain. This remains a local synthetic MCP-command-to-HTTP-to-import and
store-backed evidence-query contract smoke only. It does not implement actual
ChatGPT connected upload, production iframe readiness, real PST/OST/MSG/EML/
MBOX parser, live PostgreSQL deployment, production worker leasing, KG writes,
wiki projection, production readiness, or a completed #21 claim. Canonical
dev-container verification remains blocked because Docker Desktop reports
`Docker Desktop is unable to start`.

2026-07-05 checkpoint M is implemented and passed the issue-specific
6-reviewer gate: a ChatGPT MCP connection preflight package at
`scripts/mail_upload_chatgpt_connection_preflight.py`, focused tests in
`tests/test_mail_upload_chatgpt_connection_preflight.py`, and docs in
`README.md` and `docs/workflows.md`. The preflight reuses the configured
`formowl-semantic-mcp-jsonrpc` command smoke, validates a bounded manual
ChatGPT MCP attach package shape, emits only hashes/statuses/counts for the
required environment-name count, required tool count, expected JSON-RPC
sequence, command-smoke report, upload-session shape, and task-card shape, and
rejects package variants that contain environment values, concrete upload
locators, raw command paths, or an actual ChatGPT-connected upload overclaim.
Reviewer blocker fixed during the gate: static contract hash fields now
validate against exact `sha256_json(...)` values for required environment
names, required tool names, expected JSON-RPC sequence, and negative package
probe names; focused tests now cover tampered static hashes, duplicate probe
hashes, and embedded validation overclaims. Supplemental host checks after
blocker fixes passed: M focused tests 8 OK, M touched-file `py_compile`, MCP
command smoke tests 10 OK, K smoke tests 7 OK, L smoke tests 7 OK,
`test_mail_*.py` 113 OK, new-file long-line scan, and `git diff --check` with
CRLF warnings only. Reviewer gate passed 6/6 with `Bernoulli`, `Boole`,
`Copernicus`, `Wegener`, `Nietzsche`, and `Arendt` returning explicit
`RELEASE_DECISION: AGREE` after blocker fixes. This is only a local
connection-readiness package for the next manual ChatGPT test. It does not
claim actual ChatGPT connected upload, production iframe readiness, real mail
parser readiness, live PostgreSQL deployment, production worker leasing, KG
writes, wiki projection, production readiness, or #21 completion. Canonical
dev-container verification remains blocked because Docker Desktop reports
`Docker Desktop is unable to start`.

2026-07-05 checkpoint N is implemented and passed the issue-specific
6-reviewer gate: a ChatGPT MCP result packet intake at
`scripts/mail_upload_chatgpt_result_intake.py`, focused tests in
`tests/test_mail_upload_chatgpt_result_intake.py`, and docs in `README.md`
and `docs/workflows.md`. After an operator manually connects ChatGPT to the
configured `formowl-semantic-mcp-jsonrpc` MCP server and calls
`open_upload_session`, the intake validates a bounded hash/status/count result
packet for the preflight static contract, expected JSON-RPC sequence, observed
required tool, task-card shape, upload-session shape, and operator
attestation. It rejects environment values, concrete upload locators or upload
session IDs, private mail payload fields, raw command paths, static-contract
hash tampering, duplicate response hashes, and actual upload / production
overclaims. Supplemental host checks passed: focused result-intake tests 7 OK,
`test_mail_*.py` 120 OK, touched-file `py_compile`, new-file long-line scan,
and `git diff --check` with CRLF warnings only. Reviewer blocker fixes then
made negative packet probes valid-packet-only, malformed nested packets safe,
packet-derived safe outputs sanitized, CLI JSON load failures bounded,
`--input` and `--validate-report` mutually exclusive, and packet-level
duplicate hash / bool count / invalid hash / asset-type / non-object /
KG-overclaim coverage explicit. Supplemental host checks after blocker fixes
passed: focused result-intake tests 10 OK, `test_mail_*.py` 123 OK,
touched-file `py_compile`, new-file long-line scan, and `git diff --check`
with CRLF warnings only. Host Ruff is unavailable.
Canonical dev-container verification remains blocked: unprivileged Docker
access returned npipe permission denied, and the escalated canonical focused
command reached Docker but returned `Docker Desktop is unable to start`.
Reviewer gate passed 6/6 with `Linnaeus`, `Raman`, `Herschel`, `Fermat`,
`Harvey`, and `Mendel` returning explicit `RELEASE_DECISION: AGREE` after
blocker fixes. This is result-packet intake only: it does not let Codex
directly control ChatGPT, prove actual file transfer, prove production iframe
readiness, implement real PST/OST/MSG/EML/MBOX parsing, prove live PostgreSQL
deployment readiness, implement production worker leasing, write KG/wiki
state, claim production readiness, or complete #21.

2026-07-06 checkpoint O completes the scoped issue #21 local Phase 1 proof:
governed mail case-progress answers through FormOwl MCP / JSON-RPC. The final
slice adds `MailCaseProgressGateway` and `build_mail_case_progress_handler()`
in `python/formowl_mail/qa.py`, exposes `answer_mail_case_progress` through
`SemanticMcpGateway`, extends `scripts/mail_evidence_mcp_smoke.py` with
owner/denied/forged/trusted/bundle-id case-progress probes, and hardens
focused tests in `tests/test_mail_evidence_mcp_gateway.py`,
`tests/test_mail_evidence_mcp_smoke_script.py`,
`tests/test_semantic_mcp_gateway.py`, and
`tests/test_semantic_mcp_jsonrpc_gateway.py`. Three onboarding test-design
subagents (`James`, `Arendt`, and `Curie`) shaped the harness coverage before
the final reviewer gate. Reviewer blockers fixed during the gate: `Curie`
blocked OR-style dual-id lookup, so bundle matching now requires every supplied
identifier to match the same bundle; `Arendt` blocked missing configured
handler claim-boundary enforcement, so the gateway now requires exact
case-progress claim keys and rejects unsupported true claims before public
envelope emission. The checkpoint O reviewer gate passed 6/6 with `Kuhn`,
`Ampere`, `James`, `Arendt`, `Curie`, and `Pascal` returning explicit
`RELEASE_DECISION: AGREE`.

Canonical dev-container verification is no longer blocked after the Docker
restart. Latest canonical evidence: `test_mail_evidence_mcp_gateway.py` ran
16 OK; `test_mail_evidence_mcp_smoke_script.py` ran 15 OK; direct
`scripts/mail_evidence_mcp_smoke.py --output
/tmp/formowl-mail-evidence-mcp-smoke.json` exited 0; touched-file Ruff check
and format check passed; `test_mail_*.py` ran 132 OK; full
`python -m unittest discover -s tests` ran 493 OK in 743.175s. This proves the
local synthetic Mail Evidence Reading via FormOwl MCP path and ChatGPT testing
readiness. It does not by itself satisfy GitHub #21's final ChatGPT smoke
result requirement, and it still does not claim actual ChatGPT connected upload
or file transfer, production iframe readiness, real PST/OST/MSG/EML/MBOX
parser readiness, live PostgreSQL deployment readiness, production worker
leasing, KG writes, wiki projection, or production readiness.

2026-07-06 checkpoint P completes issue #21's scoped Phase 1 Mail Evidence
Reading via FormOwl MCP proof for fixture-backed ChatGPT testing readiness:
bounded mail evidence ChatGPT MCP result-packet intake in
`scripts/mail_evidence_chatgpt_result_intake.py`, focused tests in
`tests/test_mail_evidence_chatgpt_result_intake.py`, and docs in `README.md`
and `docs/workflows.md`. After an operator manually connects ChatGPT to a
fixture-backed FormOwl MCP mail evidence server and calls `query_mail_evidence`
plus `answer_mail_case_progress` for owner and denied paths, the intake
validates a hash/status/count-only packet bound to the checkpoint O smoke
contract, required tools, expected JSON-RPC sequence, owner citation counts,
denied redaction counts, response/request shape hashes, operator attestation,
and explicit claim boundaries. Guardrails reject raw ChatGPT transcripts, raw
tool payloads, mail body/snippet/text fields, concrete mail identifiers,
upload locators, environment values, paths, SQL, parser/storage/worker
internals, malformed nested packets, unknown packet/report keys without
echoing names, static-contract hash tampering, duplicate response hashes,
bool-as-int counts, missing tool calls, pending handler fallbacks,
permission-bypass claims, actual upload/file-transfer claims, KG/wiki claims,
and production overclaims. Three onboarding test-design subagents (`Ohm`,
`Raman`, and `Confucius`) shaped the harness before implementation.

Reviewer blockers fixed: exact `mail_import_session_hash` selector-kind
allowlisting plus no-echo tests; checkpoint O smoke validation required before
packet/report acceptance; packet and saved-report binding to fixture smoke
hash, fixture id hashes, and observation count; and exact request-shape hash
binding for owner/denied query and case-progress calls. Reviewer gate passed
6/6 with `Hume`, `Carson`, `Nietzsche`, `Mencius`, `Newton`, and `Meitner`;
`Hume`, `Carson`, and `Newton` initially blocked on selector-kind and
smoke/request/report binding gaps, then agreed after fixes. No blocking
findings remain.

Canonical verification after reviewer fixes and formatting: focused
`test_mail_evidence_chatgpt_result_intake.py` ran 12 OK; direct intake CLI and
`--validate-report` exited 0 with a bounded test packet; direct
`scripts/mail_evidence_mcp_smoke.py --output
/tmp/formowl-mail-evidence-mcp-smoke.json` exited 0; `test_mail_*.py` ran 144
OK; full Ruff check and format check for `python`, `tests`, and `scripts`
passed; full `python -m unittest discover -s tests` ran 505 OK in 682.461s.
Completion boundary: this validates bounded operator-supplied ChatGPT result
packets only. It does not let Codex directly control ChatGPT, prove actual
ChatGPT upload/file transfer, claim production iframe readiness, implement
real PST/OST/MSG/EML/MBOX parsing, prove live PostgreSQL deployment readiness,
implement production worker leasing, write KG/wiki state, expose raw mail
access, or claim production readiness.

2026-07-06 checkpoint Q completes the sampled real PST parser proof. It adds
`PstMailArchiveExtractor` under `python/formowl_ingestion/extractors/mail/`,
installs `pst-utils` in the dev container, keeps `tests/pst-exm/` out of Git
and Docker build context, and exercises the operator-provided
`tests/pst-exm/archive.pst` fixture through the Phase 1 mail evidence path:
`UploadSession -> Asset/ObjectStore -> IngestionJob -> ExtractorRun ->
PstMailArchiveExtractor -> ObservationStore -> MailEvidenceBundle ->
PostgreSQLMailEvidenceStore -> JSON-RPC query_mail_evidence`. PST MIME import
selects the PST adapter rather than the JSON fixture adapter.

The latest sampled real PST smoke ran in the dev container with sample limit
25 and validation passed. Safe report counts were fixture size `3152323584`,
`message_count=25`, `observation_count=234`, `body_segment_count=45`,
`folder_occurrence_count=2`, `attachment_occurrence_count=0`,
`mail_evidence_row_count=132`, owner query `ok` with one citation, denied
query `permission_denied` with zero visible results and hidden bundle count
one, and staging/scratch leftovers zero. The public report is
hash/status/count-only; a leak scan found no PST path, object-store locator,
parser command, parser scratch path, traceback, or Windows drive-path token.

Reviewer blockers fixed: full-parser claim flags are forced false for
this sampled slice, embedded validation full-parser overclaims are rejected,
all public count fields reject bool-as-int tampering, malformed
`--validate-report` input returns bounded validation JSON, raw archive
retention now honestly records `retain_7_days` / `retained_by_policy` instead
of claiming deletion, `query_mail_evidence` dual selectors now require AND
matching, JSON-RPC public arguments are validated before dispatch, recursive
semantic control keys are rejected before handler dispatch, public `session_id`
is only a trusted-session-overridden field, and PST unit tests cover the
`readpst` command contract plus scratch cleanup on failures.

Reviewer gate passed 6/6 for checkpoint Q. Effective reviewers were `Hilbert`,
`Hubble`, `Hooke`, `Einstein`, `Hypatia`, and `Fermat`; all returned
`RELEASE_DECISION: AGREE` after blocker fixes. Final canonical verification:
focused semantic JSON-RPC tests ran 12 OK; mail upload session gateway tests
ran 8 OK; mail evidence MCP smoke tests ran 15 OK; `test_mail_*.py` ran 155
OK; sampled real PST smoke plus `--validate-report` exited 0; Ruff check and
format check for `python`, `tests`, and `scripts` passed; full
`python -m unittest discover -s tests` ran 524 OK in 781.345s.

Completion boundary: checkpoint Q proves sampled real PST parser integration
only. It does not prove full PST/OST/MSG/EML/MBOX parser readiness, actual
ChatGPT upload or file transfer, production iframe readiness, live PostgreSQL
deployment readiness, production worker leasing, raw mail access,
delete-after-success retention, KG writes, wiki projection, or production
readiness.

2026-07-07 checkpoint R full PST 100-case evidence-reading evaluation is
implemented, performance-hardened, reviewer-gated, and canonically verified.
The new `scripts/mail_full_pst_100_case_eval.py` harness runs the
operator-provided full PST fixture with no sampling, builds a normalized
`MailEvidenceBundle`, generates 100 deterministic manifest-bound retrieval
cases, preflights selected cases through the same governed JSON-RPC
`query_mail_evidence` path, scores a fresh pass over the final manifest, and
publishes only hash/status/count report fields. Public output excludes query
text, mail body/snippets, subjects, senders, message ids, observation ids,
object locators, raw paths, parser commands, scratch paths, SQL, and
environment values.

Implementation hardening includes a reusable in-memory inverted query index
inside `MailEvidenceQueryGateway`, so query execution scores only
token-candidate snippets instead of scanning every snippet; a reusable full-PST
case query runner so 100 cases do not rebuild the handler/index for each query;
deterministic case eligibility preflight; top-k-retrievable multi-message
required sources; separate no-match/permission-denied meaning checks;
case-bound response hashes; and row-derived report validation for aggregate
counts, category counts, category passed counts, duplicate response hashes,
manifest hash, and result hash. The Semantic Gateway SQL leak guard was
narrowed so normal progress-update mail phrases are not rejected while real
SQL-shaped values remain blocked.

Performance follow-up after the user flagged runtime: three read-only
subagents (`Euler`, `Mendel`, and `Euclid`) proposed onboarding test coverage,
and `Copernicus` reviewed the speed architecture. Accepted coverage now proves
non-matching snippets are not scanned/materialized and that a
`MailEvidenceQueryGateway` builds one snippet index per bundle across repeated
owner, no-match, and denied queries. This is a Python query-index optimization
only; it does not claim the full PST import/parser bottleneck is solved. The
next speed slice should add safe phase profiling for hashing/copying, external
PST export, exported-message parsing, observation persistence, bundle
construction, evidence-store writes, index build, manifest preflight, and final
scoring before considering a native parser or systems-language module.

Latest safe full-PST evidence after the inverted-query-index performance
follow-up: full eval exited 0 in the dev container and saved
`.test-tmp/formowl-mail-full-pst-100-case-eval.json`; subsequent
`--validate-report` exited 0 with `blockers=[]`. Safe counts/timings:
`fixture_size_bytes=3152323584`, `full_parse_executed=true`,
`sample_message_limit=0`, `sampling_config_used=false`,
`parser_worker_count=8`, `message_count=2776`, `observation_count=28509`,
`body_segment_count=5076`, `mail_evidence_row_count=14110`,
`parse_warning_count=3428`, `case_count=100`, `passed_case_count=100`,
`failed_case_count=0`, `pass_rate_basis_points=10000`,
`owner_match_case_count=90`, `no_match_case_count=5`,
`permission_denied_case_count=5`, `ai_progress_related_case_count=5`,
`ai_progress_related_passed_count=5`, `duplicate_response_hash_count=0`,
`import_elapsed_ms=161583`, `case_manifest_elapsed_ms=31320`,
`scoring_elapsed_ms=11091`, and all staging/scratch/work-dir cleanup counts
passed.

Canonical verification after the performance follow-up: focused
`test_mail_evidence_mcp_gateway.py` ran 20 OK; focused
`test_mail_full_pst_100_case_eval_script.py` ran 17 OK; full-PST eval plus
saved-report validation exited 0 with `blockers=[]`; full
`python -m unittest discover -s tests` ran 544 OK in 711.056s; full Ruff
check/format-check passed with 211 files already formatted. Three onboarding
test-design subagents (`Gibbs`, `Tesla`, and `Zeno`) shaped the full-PST
harness before implementation. The checkpoint R reviewer gate passed 6/6 with
`Euler`, `Mendel`, `Huygens`, `Copernicus`, `Euclid`, and `Maxwell`; `Maxwell`
initially blocked recursive cleanup without a sentinel guard, then agreed after
`_prepare_work_dir()` and `_cleanup()` were hardened and focused tests were
added. The performance follow-up also passed a fresh 6/6 read-only reviewer
gate with `Euler`, `Mendel`, `Euclid`, `Copernicus`, `Huygens`, and `Maxwell`;
all returned `RELEASE_DECISION: AGREE` with no blocking findings.

Claim boundary: checkpoint R proves only the operator-provided full PST
100-case deterministic evidence-reading evaluation. It does not prove general
PST/OST/MSG/EML/MBOX parser readiness, actual ChatGPT upload/file transfer,
production iframe readiness, live PostgreSQL readiness, production worker
leasing, raw mail access, delete-after-success retention, KG writes, wiki
projection, or production readiness.

2026-07-07 checkpoint S records the harder full-PST domain baseline requested
after checkpoint R. `scripts/mail_full_pst_domain_hard_case_eval.py` builds 100
harder governed retrieval cases across ten business-function lenses, preserves
the private manifest and work directory under `.test-tmp`, and emits only
hash/status/count/timing public report data. Latest dev-container baseline and
saved-report validation both exited 0 with `blockers=[]`. Safe results:
100 cases scored, 20 passed, 80 failed, pass rate `2000` basis points, 80
positive cases, 10 no-match cases, 10 permission-denied cases, all
permission-denied probes redacted, all no-match near-miss probes failed,
duplicate response hash count `0`, message count `2746`, observation count
`28163`, mail evidence row count `13861`, parse warning count `3350`, upload
`308409ms`, import `3160357ms`, bundle read `50147ms`, manifest generation
`1938ms`, scoring `66156ms`, query loop `65824ms`, staging/scratch leftovers
`0`, and work dir cleaned false. Focused hard-domain tests ran 11 OK in the dev
container, and touched-file Ruff check/format-check passed. This is a baseline
measurement only; it does not claim 99/100 quality, business answer generation,
general parser readiness, actual ChatGPT upload/file transfer, production
iframe readiness, live PostgreSQL readiness, production worker leasing, raw mail
access, KG writes, wiki projection, or production readiness.

2026-07-07 KG follow-up checkpoints T/U are measurement-only for the preserved
checkpoint S intermediate data. Non-BERT candidate KG rescore improved the
hard-domain score from 20/100 to 30/100. The ontology-guided non-BERT
candidate arm used formal FormOwl `TypeDefinition`/`TypeMapping` contracts and
a hash-bound ontology revision as candidate scoring/gating only, but scored
29/100, so it did not beat the simpler candidate KG arm. Permission-denied
cases stayed 10/10, and no-match near-miss cases stayed 0/10. This does not
change system readiness: no PST reparse, no BERT/neural runtime, no canonical
KG/type writes, no user graph writes, no grants/raw access, no wiki projection,
and no business answer generation or production readiness claim.
Canonical dev-container verification for the T/U measurement slice passed:
focused KG tests 9 OK, focused ontology-ablation tests 9 OK, saved-report
validation for both container-generated reports with `blockers=[]`, full
unittest 573 OK in 835.841s, and full Ruff check/format-check with 217 files
already formatted. The #21 reviewer gate passed 6/6 with no blocking findings.

## Handoff Notes For KG Research Agent

The System Backbone Agent will not edit KG-eval internals or expose
`.formowl/kg-eval` paths through MCP. The packaged `formowl_kg_eval` facade is
the integration boundary for product-facing status.

## Boundary Reminder

The system backbone work must not collapse ingestion, graph governance, user
graph assembly, and wiki projection into one direct pipeline. It should provide
stable infrastructure and service boundaries that allow the KG research layer
to evolve without rewriting service plumbing.
