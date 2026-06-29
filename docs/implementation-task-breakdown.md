# Implementation Task Breakdown

This file is the working checklist for turning the current Phase 0 prototype into
the full FormOwl pipeline described by `SPEC.md` and
`RESOURCE_EXTRACTION_SPEC.md`.

Future agents should update this file as work lands:

- Change `[ ]` to `[x]` only after code, tests, and relevant docs are complete.
- Keep each task scoped to the listed ownership area when possible.
- Do not create parallel replacement modules when `SPEC.md` already defines a path.
- Prefer small vertical slices that prove one data flow end to end.

Durable long-running agent objectives live under `docs/agent-goals/`. This work
board records task completion; it is not a substitute for role goal and handoff
state.

## Status Legend

- `[x]` complete in the current repository.
- `[ ]` not started or not verified.
- `Owner paths` list the expected write area for an agent.
- `Proof` lists the minimum evidence before checking the item off.

## Completed Phase 0 Baseline

- [x] Container-first repository skeleton.
  - Owner paths: `containers/`, `.devcontainer/`, `Dockerfile`, `compose.yaml`
  - Proof: dev/runtime container files exist.
- [x] Python package root and project metadata.
  - Owner paths: `pyproject.toml`, `python/`
  - Proof: package discovery and unittest `pythonpath` are configured.
- [x] Shared contract models for current MCP workflow.
  - Owner paths: `python/formowl_contract/`
  - Proof: `SourceRef`, `PermissionScope`, `EvidenceSnapshot`, `Citation`,
    `ContextPackage`, `WikiRevision`, and `McpResultEnvelope` exist.
- [x] Pure Python core hashing and diff helpers.
  - Owner paths: `python/formowl_core/`
  - Proof: stable JSON hash test passes.
- [x] Project MCP JSON-line prototype.
  - Owner paths: `python/formowl_project_mcp/`
  - Proof: tools can list, retrieve, and package mocked OpenProject context.
- [x] Mock OpenProject adapter.
  - Owner paths: `python/formowl_project_mcp/adapters/openproject/`
  - Proof: work items, comments, activities, relations, attachments, and project
    status are available through adapter calls.
- [x] Evidence snapshot file storage.
  - Owner paths: `python/formowl_project_mcp/storage/`
  - Proof: snapshot metadata, request, response, and normalized markdown are
    persisted under test data directories.
- [x] Wiki MCP JSON-line prototype.
  - Owner paths: `python/formowl_wiki_mcp/`
  - Proof: drafts, page lookup, draft updates, publish proposals, and wiki
    snapshots are exposed as tools.
- [x] Markdown frontmatter provenance for generated drafts.
  - Owner paths: `python/formowl_wiki_mcp/markdown/`
  - Proof: generated markdown includes source refs, evidence snapshot ids, and
    citations.
- [x] Proposal-only write behavior for project comments and wiki publishing.
  - Owner paths: `python/formowl_project_mcp/tools/`,
    `python/formowl_wiki_mcp/tools/`
  - Proof: write tools return `pending_review` and do not mutate external
    systems.
- [x] MCP tool-call JSONL logging.
  - Owner paths: `python/formowl_project_mcp/observability/`,
    `python/formowl_wiki_mcp/observability/`
  - Proof: tool calls write hashes, status, latency, and evidence/draft ids.
- [x] Independent and integration tests for current workflow.
  - Owner paths: `tests/`
  - Proof: `python -m unittest discover -s tests` passes.

## Next Small Core Slice

Start here before broad parallel implementation. This slice introduces the
resource extraction spine without real OCR, audio, video, graph fusion, or
external storage dependencies.

Goal:

```text
local file or text payload
  -> Asset registration
  -> IngestionJob
  -> ExtractorRun
  -> Observation
  -> file-backed stores
  -> ContextPackage bridge
  -> existing Wiki MCP draft generation
  -> tests proving stable ids, hashes, provenance, and permission scope
```

Why this is first:

- It matches the pipeline extension order in `SPEC.md`.
- It gives all later extractors a stable contract and store boundary.
- It can be implemented with deterministic local code and no vendor services.
- It keeps graph governance and wiki projection separate, as required by the
  resource extraction boundary.

### Slice 1A: Resource Contract Models

- [x] Add contract dataclasses for `StorageBackend`, `Asset`, `AssetMetadata`,
  `IngestionJob`, `ExtractorRun`, `Observation`, and `SemanticMetadata`.
  - Owner paths: `python/formowl_contract/models.py`,
    `python/formowl_contract/__init__.py`
  - Proof: model round-trip tests pass and `to_dict()` validates required
    fields.
- [x] Add deterministic id/hash helpers for resource contracts.
  - Owner paths: `python/formowl_contract/`, `python/formowl_core/`
  - Proof: repeated construction from the same payload yields stable ids and
    hashes.
- [x] Add validators for the new resource contracts.
  - Owner paths: `python/formowl_contract/models.py`
  - Proof: malformed assets, runs, and observations raise
    `ContractValidationError`.
- [x] Add contract tests for the resource spine.
  - Owner paths: `tests/test_resource_contract.py`
  - Proof: new tests pass with existing tests.

### Slice 1B: Local Storage Backend

- [x] Add `formowl_ingestion` package skeleton following `SPEC.md`.
  - Owner paths: `python/formowl_ingestion/__init__.py`,
    `python/formowl_ingestion/assets.py`,
    `python/formowl_ingestion/jobs.py`,
    `python/formowl_ingestion/observations.py`,
    `python/formowl_ingestion/storage/`
  - Proof: package imports cleanly.
- [x] Implement a file-backed `StorageBackendRegistry`.
  - Owner paths: `python/formowl_ingestion/storage/`
  - Proof: tests can register and resolve a local backend without exposing raw
    paths through MCP envelopes.
- [x] Implement a file-backed `ObjectStore` for copied local bytes.
  - Owner paths: `python/formowl_ingestion/storage/`
  - Proof: content hash verification passes and stored objects use FormOwl
    locators.
- [x] Implement `AssetStore`, `JobStore`, `ExtractorRunStore`, and
  `ObservationStore`.
  - Owner paths: `python/formowl_ingestion/storage/`
  - Proof: create/get/list tests cover persisted JSON records.

### Slice 1C: Deterministic Text Extractor

- [x] Define an `ExtractorAdapter` protocol and extraction input/result objects.
  - Owner paths: `python/formowl_ingestion/extraction.py`
  - Proof: a simple adapter can declare name, version, supported MIME types, and
    extractor type.
- [x] Implement a deterministic plain-text/markdown observation extractor.
  - Owner paths: `python/formowl_ingestion/extractors/`
  - Proof: a `.txt` or `.md` asset produces observations with line-range
    locators, source refs, extractor run id, and confidence.
- [x] Keep semantic metadata extraction separate from deterministic observation
  extraction.
  - Owner paths: `python/formowl_ingestion/extractors/`
  - Proof: text extraction does not create candidate atoms or canonical graph
    records.
- [x] Add re-extraction behavior that creates a new `ExtractorRun`.
  - Owner paths: `python/formowl_ingestion/extraction.py`,
    `python/formowl_ingestion/storage/`
  - Proof: rerunning the same extractor preserves the old run and writes a new
    run record when config or version changes.

### Slice 1D: Minimal Ingestion Workflow

- [x] Implement `register_asset_from_local_file()` for trusted internal tests.
  - Owner paths: `python/formowl_ingestion/assets.py`
  - Proof: asset registration records technical metadata, hash, source ref,
    permission scope, and a FormOwl locator.
- [x] Implement `create_ingestion_job()` and `run_ingestion_job()` for local
  deterministic extractors.
  - Owner paths: `python/formowl_ingestion/jobs.py`
  - Proof: job status moves through pending/running/succeeded/failed and links
    to extractor runs and observations.
- [x] Add an integration test for Asset -> Job -> Run -> Observation.
  - Owner paths: `tests/test_ingestion_workflow.py`
  - Proof: end-to-end test passes and records remain queryable after process
    restart.
- [x] Document the small core workflow.
  - Owner paths: `docs/workflows.md`, this file
  - Proof: docs mention the local deterministic ingestion path and any
    intentional limitations.

### Slice 1E: Observation to Wiki Draft Bridge

- [x] Add a narrow helper that builds a `ContextPackage` from selected text
  observations.
  - Owner paths: `python/formowl_ingestion/observations.py`,
    `python/formowl_contract/`
  - Proof: the context package includes source refs, asset ids, extractor run
    ids, observation ids, citations, and permission scope.
- [x] Add an integration test for text asset -> observations -> context package
  -> existing Wiki MCP draft.
  - Owner paths: `tests/test_ingestion_to_wiki_workflow.py`
  - Proof: generated markdown includes the source title/content, citation
    lineage, and evidence/observation references without reading raw paths.
- [x] Keep this bridge reviewable and non-canonical.
  - Owner paths: `python/formowl_ingestion/`, `python/formowl_wiki_mcp/`
  - Proof: the bridge does not create `CandidateAtom`, `CanonicalAtom`,
    `WikiRevision`, or graph commit records.

## Parallel Work After Small Core

These groups can be split across multiple agents after Slice 1 is stable.

### Identity, Access, and Audit

- [x] Add contract models for `User`, `SessionIdentity`, `WorkspaceMember`,
  `AccessRequest`, `Grant`, and `AuditLog`.
  - Owner paths: `python/formowl_contract/`, `tests/test_identity_contract.py`
  - Proof: validation and serialization tests pass.
- [x] Implement `ManualTrustedInternalAuthProvider`.
  - Owner paths: `python/formowl_gateway/` or `python/formowl_auth/`
  - Proof: `select_actor` and `whoami` style calls produce actor context without
    claiming production authentication.
- [x] Add audit logging for actor selection, asset registration, ingestion job
  creation, evidence fetches, and permission denials.
  - Owner paths: shared observability/auth modules
  - Proof: tests assert audit records contain actor, workspace, action, target,
    status, and timestamp.

### Upload Session and ChatGPT Session Capture

- [x] Add `UploadSession` contract and store.
  - Owner paths: `python/formowl_contract/`, `python/formowl_ingestion/`
  - Proof: normal uploads cannot skip intent, actor, permission scope, and audit.
- [x] Add a controlled `upload_asset_reference` backend path.
  - Owner paths: `python/formowl_ingestion/`
  - Proof: trusted imports still create asset, permission, and audit records.
- [x] Add `capture_current_chatgpt_session` data model and workflow.
  - Owner paths: `python/formowl_ingestion/`, docs
  - Proof: captured sessions become assets and ingestion jobs, not untracked
    local exports.

### Real Extractor Adapters

- [x] Add technical metadata extractor adapters.
  - Owner paths: `python/formowl_ingestion/extractors/metadata/`
  - Proof: file size, MIME type, hash, and optional ExifTool/MediaInfo metadata
    are captured as observations or asset metadata.
- [x] Add document parsing adapters.
  - Owner paths: `python/formowl_ingestion/extractors/document/`
  - Proof: PDF/doc-like test fixtures create paragraph/table observations with
    page or block locators.
- [x] Add OCR adapters.
  - Owner paths: `python/formowl_ingestion/extractors/ocr/`
  - Proof: image/PDF fixtures create text observations with page/image locators.
- [x] Add audio transcription adapters.
  - Owner paths: `python/formowl_ingestion/extractors/audio/`
  - Proof: audio fixtures create transcript observations with time locators.
- [x] Add video scene and keyframe adapters.
  - Owner paths: `python/formowl_ingestion/extractors/video/`
  - Proof: video fixtures create scene/keyframe observations with time ranges.
- [x] Add mail/archive ingestion adapters.
  - Owner paths: `python/formowl_ingestion/extractors/mail/`
  - Proof: messages, attachments, occurrences, and archive identity remain
    distinct assets or observations.

### Semantic Metadata and Candidate Graph

- [x] Add contract models for `CandidateAtom`, `CandidateRelation`, and
  `ExternalGraphImport`.
  - Owner paths: `python/formowl_contract/`, tests
  - Proof: candidate records preserve source observation ids and extractor run
    provenance.

### Test Hardening Board for Completed Slices

- [x] Add coverage tooling to the canonical dev container.
  - Owner paths: `pyproject.toml`, `containers/dev/Dockerfile`, `README.md`,
    `.gitignore`
  - Proof: `coverage run -m unittest discover -s tests && coverage report`
    runs inside `formowl-dev:local`; current total coverage is 87%.
- [x] Add strict contract edge-case tests for completed identity, upload,
  semantic metadata, and candidate graph contracts.
  - Owner paths: `python/formowl_contract/`, `tests/`
  - Proof: non-string IDs, invalid review state, malformed provenance lists,
    and invalid permission scopes are rejected under dev-container tests.
- [x] Add store edge-case tests for completed file-backed record stores.
  - Owner paths: `python/formowl_ingestion/storage/`, `python/formowl_auth/`,
    `tests/`
  - Proof: unsafe record ids, dict payload validation, and restart persistence
    are covered under dev-container tests.
- [x] Add extractor negative-path tests for completed deterministic and fixture
  extractors.
  - Owner paths: `python/formowl_ingestion/extraction.py`,
    `python/formowl_ingestion/extractors/`, `tests/`
  - Proof: unsupported MIME, adapter exceptions, adapter-reported errors,
    empty fixtures, malformed fixtures, and object verification failures are
    covered under dev-container tests.
- [x] Add workflow edge-case tests for completed auth, audit, upload reference,
  evidence fetch, and ChatGPT capture workflows.
  - Owner paths: `python/formowl_auth/`, `python/formowl_ingestion/`,
    `python/formowl_project_mcp/storage/`, `tests/`
  - Proof: grant/request filtering, audit context requirements, invalid
    source refs, and scratch-file cleanup are covered under dev-container
    tests.
- [x] Run strict subagent review of completed-slice tests and triage findings
  one small unit at a time.
  - Owner paths: `tests/`, this file
  - Proof: every accepted finding has a focused test/code/doc patch and a
    dev-container verification command.
  - Note: accepted findings were fixed one unit at a time and verified by the
    canonical dev-container unittest plus coverage commands.
- [x] Reach the user-requested 9-reviewer test-release gate.
  - Owner paths: `tests/`, this file
  - Proof: 9 effective read-only subagent reviewers have checked the completed
    slice tests; errored or no-op agents do not count; every reviewer either
    explicitly agrees the tests can be released or its findings are fixed and
    re-reviewed.
  - Effective reviewer count: 9/9 (`Socrates`, `Meitner`, `Copernicus`,
    `Aristotle`, `Leibniz`, `Hypatia`, `Noether`, `Turing`, `Lovelace`).
  - Reviewer agreement count: 9/9 (`Socrates`, `Meitner`, `Copernicus`,
    `Aristotle`, `Leibniz`, `Hypatia`, `Noether`, `Turing`, `Lovelace`).
  - Reviewers with blocking findings: none.
  - Non-counted agents: `Anscombe`, `Nash`, and `Descartes` errored before
    review.
  - Active reviewers: `Euler`, `Curie`.
  - Canonical verification: `docker run --rm -v "$PWD:/workspace" -w
    /workspace formowl-dev:local python -m unittest discover -s tests` ran
    100 tests OK; `coverage run -m unittest discover -s tests && coverage
    report` passed with 87% total coverage.
- [x] Fix strict-review finding: failed extractor results must not link
  unpersisted observation ids from failed ingestion jobs.
  - Owner paths: `python/formowl_ingestion/jobs.py`,
    `tests/test_ingestion_workflow.py`
  - Proof: focused dev-container unittest for
    `test_failed_extractor_result_does_not_link_unpersisted_observations`
    passes.
- [x] Fix strict-review finding: `run_ingestion_job` must reject non-pending
  jobs without creating new runs or observations.
  - Owner paths: `python/formowl_ingestion/jobs.py`,
    `tests/test_ingestion_workflow.py`
  - Proof: succeeded/failed/running jobs cannot be rerun and stores remain
    unchanged.
  - Note: implementation and host-side supplemental tests now cover running,
    succeeded, and failed jobs without new run/observation records;
    canonical dev-container unittest and coverage passed.
- [x] Fix strict-review finding: multi-extractor partial failure policy must be
  explicit and tested.
  - Owner paths: `python/formowl_ingestion/jobs.py`,
    `tests/test_ingestion_workflow.py`
  - Proof: when one extractor succeeds and a later extractor fails, failed job
    state explicitly preserves only already-persisted successful observations.
  - Note: host-side supplemental tests cover both adapter-reported errors and
    missing-adapter exceptions after a prior successful extractor;
    canonical dev-container unittest and coverage passed.
- [x] Fix self-audit finding: ingestion job creation must reject malformed
  extractor names without persisting jobs.
  - Owner paths: `python/formowl_ingestion/jobs.py`,
    `tests/test_ingestion_workflow.py`
  - Proof: empty and non-string extractor names fail before job persistence.
  - Note: implementation and full host-side supplemental unittest are done;
    canonical dev-container unittest and coverage passed.
- [x] Fix self-audit finding: audit-bound asset and job helpers must validate
  actor/session identity before persistence.
  - Owner paths: `python/formowl_ingestion/assets.py`,
    `python/formowl_ingestion/jobs.py`, `tests/test_workflow_edge_cases.py`
  - Proof: missing or non-string audit identity fails before asset/object/audit
    writes and before job/audit writes.
  - Note: implementation and full host-side supplemental unittest are done;
    canonical dev-container unittest and coverage passed.
- [x] Fix Copernicus blocker: `PermissionScope` validation must reject
  malformed typed fields across upload and ChatGPT workflows.
  - Owner paths: `python/formowl_contract/models.py`,
    `tests/test_contract_edge_cases.py`, `tests/test_upload_session.py`,
    `tests/test_chatgpt_session_capture.py`
  - Proof: non-string `scope_type`, `visibility`, `scope_id`, and
    `inherited_from` fail through contract validation and relevant workflows.
  - Note: implementation and focused host-side supplemental tests are done;
    `Copernicus` agreed after re-review; dev-container verification is still
    required before checking this item.
- [x] Fix Copernicus blocker: ChatGPT capture must prevalidate optional
  project/customer fields before audit or object writes.
  - Owner paths: `python/formowl_ingestion/chatgpt.py`,
    `tests/test_chatgpt_session_capture.py`
  - Proof: malformed optional fields fail before audit, scratch, object,
    asset, job, or capture persistence.
  - Note: implementation and focused host-side supplemental test is done;
    `Copernicus` agreed after re-review; dev-container verification is still
    required before checking this item.
- [x] Fix Copernicus blocker: asset registration must prevalidate all
  user-supplied asset fields before object copy.
  - Owner paths: `python/formowl_ingestion/assets.py`,
    `tests/test_workflow_edge_cases.py`
  - Proof: malformed asset fields fail before asset, audit, payload, or object
    metadata writes.
  - Note: implementation and full host-side supplemental unittest are done;
    canonical dev-container unittest and coverage passed.
- [x] Fix Aristotle blocker: helper timestamp overrides must reject empty
  strings instead of silently normalizing them.
  - Owner paths: `python/formowl_ingestion/assets.py`,
    `python/formowl_ingestion/jobs.py`, `python/formowl_ingestion/uploads.py`,
    `tests/`
  - Proof: empty caller-provided timestamps fail before asset/object/job/upload
    or audit writes.
  - Note: implementation and focused host-side supplemental tests now cover
    asset/upload/job creation timestamps plus `run_ingestion_job` execution
    `started_at` and `completed_at` values. `Aristotle` agreed after re-review;
    canonical dev-container unittest and coverage passed.
- [x] Fix Aristotle blocker: ChatGPT capture message fields must reject
  malformed typed values before persistence.
  - Owner paths: `python/formowl_ingestion/chatgpt.py`,
    `tests/test_chatgpt_session_capture.py`
  - Proof: non-string `content`, `role`, or `message_id` fail before audit,
    scratch, object, asset, job, or capture writes.
  - Note: implementation and focused host-side supplemental test is done;
    `Aristotle` agreed after re-review; dev-container verification is still
    required before checking this item.
- [x] Fix Leibniz blocker: object metadata must not expose raw paths through
  `original_filename`.
  - Owner paths: `python/formowl_ingestion/storage/objects.py`,
    `tests/test_object_store.py`
  - Proof: path-like `original_filename` values are sanitized or rejected
    before metadata/MCP envelope exposure.
  - Note: implementation and focused host-side supplemental test are done;
    `Leibniz` agreed after re-review; dev-container verification is still
    required before checking this item.
- [x] Fix Leibniz blocker: storage backend public envelopes must not expose raw
  path-like `root_prefix` values.
  - Owner paths: `python/formowl_ingestion/storage/backends.py`,
    `python/formowl_contract/models.py`, `tests/test_storage_backend_registry.py`
  - Proof: raw-path root prefixes are rejected or omitted from public MCP
    backend envelopes.
  - Note: implementation and focused host-side supplemental test is done;
    `Leibniz` agreed after re-review; dev-container verification is still
    required before checking this item.
- [x] Fix Leibniz blocker: public locator contract fields must reject raw path
  strings.
  - Owner paths: `python/formowl_contract/models.py`,
    `python/formowl_ingestion/chatgpt.py`, `tests/`
  - Proof: `Asset.object_uri` and `ChatGptSessionCapture.asset_object_uri`
    reject Windows paths, POSIX paths, `file://` URLs, and internal raw paths.
  - Note: implementation and focused host-side supplemental tests are done;
    `Leibniz` agreed after re-review; dev-container verification is still
    required before checking this item.
- [x] Fix strict-review finding: partial observation persistence during
  observation validation failure must roll back or avoid orphan observations.
  - Owner paths: `python/formowl_ingestion/extraction.py`, `tests/`
  - Proof: adapter returns one valid and one invalid observation; failed run
    exists and no observations remain.
- [x] Fix strict-review finding: failed extractor results must not return
  unpersisted observations to callers.
  - Owner paths: `python/formowl_ingestion/extraction.py`,
    `tests/test_extraction_edge_cases.py`
  - Proof: adapter returns an error plus an observation; stored extraction
    result and observation store both contain no observations.
- [x] Fix strict-review finding: extractor observations must match the current
  asset id, extractor run id, and permission scope.
  - Owner paths: `python/formowl_ingestion/extraction.py`,
    `tests/test_extraction_edge_cases.py`
  - Proof: adapter returns schema-valid observations with mismatched lineage;
    failed run exists and no observations are persisted.
- [x] Fix strict-review finding: invalid `create_upload_session` input must not
  leave misleading `ok` audit records.
  - Owner paths: `python/formowl_ingestion/uploads.py`,
    `python/formowl_auth/`, `tests/`
  - Proof: invalid status raises and leaves no upload session plus an explicit
    audit policy result.
  - Note: host-side supplemental tests now cover invalid status, missing
    session id, and non-string actor id without upload-session or audit writes;
    canonical dev-container unittest and coverage passed.
- [x] Fix strict-review finding: invalid controlled upload references must not
  leave copied object-store payloads.
  - Owner paths: `python/formowl_ingestion/uploads.py`,
    `python/formowl_ingestion/assets.py`, `tests/`
  - Proof: invalid source ref raises and leaves no asset, audit, payload, or
    object metadata.
  - Note: host-side supplemental tests cover invalid source refs and missing
    controlled-import reasons without asset, audit, payload, or object metadata
    writes; canonical dev-container unittest and coverage passed.
- [x] Fix strict-review finding: ChatGPT capture downstream failure must not
  leave misleading capture/audit/asset/job state.
  - Owner paths: `python/formowl_ingestion/chatgpt.py`, `tests/`
  - Proof: invalid extractor names fail with scratch cleanup and explicit
    persistence/audit policy.
  - Note: host-side supplemental tests cover empty, duplicate, empty-string,
    and non-string extractor names plus malformed permission scope, empty
    visibility scope, and missing storage backend before
    audit/scratch/object/asset/job/capture writes; dev-container verification
    is still required before checking this item.
- [x] Fix strict-review finding: manual auth provider must filter expired
  grants, not only revoked grants.
  - Owner paths: `python/formowl_auth/provider.py`, `tests/`
  - Proof: selected actor active grants exclude grants expired at selection
    time.
  - Note: implementation and focused host-side supplemental test are done;
    canonical dev-container unittest and coverage passed.
- [x] Fix strict-review finding: `ChatGptSessionCapture` validation must reject
  malformed typed fields.
  - Owner paths: `python/formowl_ingestion/chatgpt.py`, `tests/`
  - Proof: non-string account ids, non-dict metadata, and invalid permission
    scopes are rejected.
  - Note: implementation and focused host-side supplemental test are done;
    canonical dev-container unittest and coverage passed.
- [x] Fix strict-review finding: coverage tooling should enforce a minimum
  threshold.
  - Owner paths: `pyproject.toml`, `README.md`
  - Proof: dev-container coverage command fails below the selected threshold.
  - Note: `pyproject.toml` now enforces `fail_under = 85` and README documents
    that `coverage report` enforces the threshold. Host coverage is not
    canonical dev-container coverage passed with 87% total coverage.
- [x] Fix strict-review finding: object store negative paths must cover
  malformed URIs, unsafe locator segments, and not-found envelopes.
  - Owner paths: `python/formowl_ingestion/storage/objects.py`,
    `tests/test_object_store.py`
  - Proof: malformed object URIs do not resolve or echo raw paths, `.`/`..`
    locator segments are rejected before payload writes, and missing safe
    FormOwl locators return `not_found`.
  - Note: implementation and full host-side supplemental unittest are done;
    canonical dev-container unittest and coverage passed.
- [x] Fix strict-review finding: fixture extractor edge coverage should include
  metadata size mismatch and video backwards scene time.
  - Owner paths: `python/formowl_ingestion/extractors/`, `tests/`
  - Proof: focused fixture tests cover the two missed branches.
  - Note: implementation and focused host-side supplemental tests are done;
    canonical dev-container unittest and coverage passed.
- [x] Fix strict-review finding: mail fixture identity fields must reject
  non-string archive, mailbox, folder, and message ids.
  - Owner paths: `python/formowl_ingestion/extractors/mail/`, `tests/`
  - Proof: non-string mail identity fields fail without persisted
    observations.
  - Note: implementation and focused host-side supplemental test are done;
    canonical dev-container unittest and coverage passed.
- [x] Fix Hypatia/Noether blocker: extractor exceptions inside
  `run_ingestion_job` must preserve persisted failed run lineage.
  - Owner paths: `python/formowl_ingestion/jobs.py`,
    `tests/test_ingestion_workflow.py`
  - Proof: adapter exceptions that persist a failed `ExtractorRun` leave the
    failed job linked to that run id, with no observations, and persisted state
    remains queryable after restart.
  - Note: implementation and focused host-side supplemental test are done;
    `python -m unittest discover -s tests -p test_ingestion_workflow.py` ran
    10 tests OK. `Hypatia` and `Noether` agreed after re-review;
    canonical dev-container unittest and coverage passed.
- [x] Fix Hypatia/Noether blocker: observation store write failures must not
  leave partial observations under failed extractor runs.
  - Owner paths: `python/formowl_ingestion/extraction.py`,
    `tests/test_extraction_edge_cases.py`
  - Proof: two schema-valid observations where a later unsafe record id fails
    leave a failed run and zero persisted observations.
  - Note: implementation and focused host-side supplemental test are done;
    `python -m unittest discover -s tests -p test_extraction_edge_cases.py`
    ran 11 tests OK. `Hypatia` and `Noether` agreed after re-review;
    canonical dev-container unittest and coverage passed.
- [x] Fix Hypatia blocker: ingestion job validation must reject raw-string and
  duplicate extractor name input before persistence.
  - Owner paths: `python/formowl_ingestion/jobs.py`,
    `tests/test_ingestion_workflow.py`
  - Proof: `extractor_names="abc"` and duplicate extractor names fail before
    job persistence.
  - Note: implementation and focused host-side supplemental test are done;
    `python -m unittest discover -s tests -p test_ingestion_workflow.py` ran
    10 tests OK. `Hypatia` and `Noether` agreed after re-review;
    canonical dev-container unittest and coverage passed.
- [x] Fix Noether blocker: `run_ingestion_job` must reject duplicate adapter
  names before mutating a pending job.
  - Owner paths: `python/formowl_ingestion/jobs.py`,
    `tests/test_ingestion_workflow.py`
  - Proof: duplicate adapter names fail with the original pending job unchanged
    and no extractor runs or observations.
  - Note: implementation and focused host-side supplemental test are done;
    `python -m unittest discover -s tests -p test_ingestion_workflow.py` ran
    10 tests OK. `Hypatia` and `Noether` agreed after re-review;
    canonical dev-container unittest and coverage passed.
- [x] Fix Hypatia blocker: `IngestionJob.error` must reject malformed typed
  values.
  - Owner paths: `python/formowl_contract/models.py`, `tests/`
  - Proof: non-string `error` values fail contract/store validation.
  - Note: implementation and focused host-side supplemental test are done;
    `python -m unittest discover -s tests -p test_store_edge_cases.py` ran
    3 tests OK. `Hypatia` and `Noether` agreed after re-review;
    canonical dev-container unittest and coverage passed.
- [x] Fix Noether blocker: `run_extractor` must reject empty caller-provided
  timestamps before persistence.
  - Owner paths: `python/formowl_ingestion/extraction.py`,
    `tests/test_extraction_edge_cases.py`
  - Proof: `started_at=""` and `completed_at=""` raise before run or
    observation writes.
  - Note: implementation and focused host-side supplemental test are done;
    `python -m unittest discover -s tests -p test_extraction_edge_cases.py`
    ran 11 tests OK. `Hypatia` and `Noether` agreed after re-review;
    canonical dev-container unittest and coverage passed.
- [x] Fix Turing/Lovelace blocker: direct job-store writes must reject
  malformed extractor name lists.
  - Owner paths: `python/formowl_contract/models.py`,
    `tests/test_store_edge_cases.py`
  - Proof: `JobStore.create(dict)` and `IngestionJob.from_dict()` reject empty,
    empty-string, and duplicate `extractor_names`.
  - Note: implementation and focused host-side supplemental test are done;
    `python -m unittest discover -s tests -p test_store_edge_cases.py` ran
    7 tests OK. `Turing` and `Lovelace` agreed after re-review;
    canonical dev-container unittest and coverage passed.
- [x] Fix Turing blocker: boolean observation confidence must not be normalized
  to numeric confidence.
  - Owner paths: `python/formowl_contract/models.py`,
    `tests/test_extraction_edge_cases.py`
  - Proof: an adapter returning `Observation(confidence=True)` creates a failed
    run and leaves no persisted observations.
  - Note: implementation and focused host-side supplemental test are done;
    `python -m unittest discover -s tests -p test_extraction_edge_cases.py`
    ran 12 tests OK. `Turing` and `Lovelace` agreed after re-review;
    canonical dev-container unittest and coverage passed.
- [x] Fix Turing blocker: helper execution timestamps must reject malformed
  non-empty timestamp strings.
  - Owner paths: `python/formowl_ingestion/jobs.py`,
    `python/formowl_ingestion/extraction.py`, `tests/`
  - Proof: `run_ingestion_job` and `run_extractor` reject `not-a-timestamp`
    before job/run/observation persistence.
  - Note: implementation and focused host-side supplemental tests are done;
    ingestion workflow ran 10 tests OK and extraction edge ran 12 tests OK.
    `Turing` and `Lovelace` agreed after re-review; dev-container verification
    is still required before checking this item.
- [x] Fix Lovelace blocker: persisted job and extractor-run timestamps must be
  contract-validated.
  - Owner paths: `python/formowl_contract/models.py`,
    `tests/test_store_edge_cases.py`
  - Proof: job/run store writes reject empty optional timestamps and malformed
    required or optional ISO timestamp fields.
  - Note: implementation and focused host-side supplemental test are done;
    `python -m unittest discover -s tests -p test_store_edge_cases.py` ran
    7 tests OK. `Turing` and `Lovelace` agreed after re-review;
    canonical dev-container unittest and coverage passed.
- [x] Fix Lovelace blocker: optional extractor-run model fields and observation
  text fields must be typed.
  - Owner paths: `python/formowl_contract/models.py`,
    `tests/test_store_edge_cases.py`
  - Proof: non-string `model_name`, `model_version`, `prompt_hash`, `text`, and
    `caption` fail contract/store validation.
  - Note: implementation and focused host-side supplemental test are done;
    `python -m unittest discover -s tests -p test_store_edge_cases.py` ran
    7 tests OK. `Turing` and `Lovelace` agreed after re-review;
    canonical dev-container unittest and coverage passed.
- [x] Fix Lovelace blocker: malformed object URI MCP envelopes must have
  unambiguous redaction behavior.
  - Owner paths: `python/formowl_ingestion/storage/objects.py`,
    `tests/test_object_store.py`
  - Proof: malformed object URI envelopes omit `object_uri` entirely while safe
    missing FormOwl locators are echoed as safe not-found locators.
  - Note: implementation and focused host-side supplemental test are done;
    `python -m unittest discover -s tests -p test_object_store.py` ran 7 tests
    OK. `Turing` and `Lovelace` agreed after re-review; dev-container
    verification is still required before checking this item.

- [x] Implement `SemanticMetadataStore`, `CandidateAtomStore`, and
  `CandidateRelationStore`.
  - Owner paths: `python/formowl_graph/storage/` or
    `python/formowl_ingestion/storage/`
  - Proof: stores do not write canonical graph state.
  - Note: implemented file-backed graph proposal stores under
    `python/formowl_graph/storage/`; `tests/test_graph_record_stores.py`
    covers create/get/list, dict validation, safe ids, restart persistence, and
    verifies canonical graph collections are not created. First reviewer blockers were fixed by
    adding malformed dict-payload no-partial-write assertions, empty provenance
    id rejection, path-like graph reference id rejection including extractor run
    lineage, stable graph-reference id grammar, exact proposal-only graph
    directory assertions, and no-json side-effect checks for rejected malformed
    and unsafe ids. Reviewer gate passed 9/9. Canonical dev-container unittest
    ran 107 tests OK; canonical coverage passed with 87% total coverage.
  - Reviewer gate target: 9 effective read-only reviewers.
  - Effective reviewer count: 9/9.
  - Reviewer agreement count: 9/9.
  - Reviewers with blocking findings: none.
  - Non-counted agents: none.
  - Active reviewers: none.
- [x] Add a deterministic candidate extraction adapter for simple text fixtures.
  - Owner paths: `python/formowl_graph/candidates.py`
  - Proof: candidates are reviewable proposals and never canonical truth.
  - Test checklist:
    - [x] Deterministic text fixture markers create stable `pending_review`
      `CandidateAtom` proposals with source observation and extractor run
      provenance.
    - [x] Candidate extraction skips unsupported or empty fixture text without
      persisting partial candidate records.
    - [x] Candidate extraction rejects malformed observation lineage before
      candidate store writes.
    - [x] Tests assert candidate extraction does not create semantic metadata,
      canonical graph records, wiki revisions, or raw-path-facing state.
  - Note: implementation and host-side supplemental tests are in place;
    `python -m unittest discover -s tests -p test_candidate_extraction.py` ran
    10 tests OK and `python -m unittest discover -s tests` ran 117 tests OK.
    Initial reviewer blockers for source extractor-run lineage, raw
    path/locator leakage, malformed `created_at`, ID determinism across
    timestamps, and unmarked text handling have been fixed for re-review.
    Noether's follow-up blocker for non-ISO `created_at` strings was fixed by
    ISO timestamp validation and focused coverage.
    Confucius blockers for direct-store malformed candidate timestamps and raw
    path/locator marker labels were fixed with contract validation and
    no-write tests.
    Hegel/Singer blockers for source observation timestamps, punctuation-wrapped
    POSIX marker paths, and dict-payload candidate timestamp bypasses were fixed
    for re-review.
    Lorentz's blocker for later raw marker failures leaving earlier candidates
    partially persisted was fixed with a focused no-write test.
    Carson's blocker for generic absolute POSIX raw paths in marker labels was
    fixed by generic absolute-path detection and focused cases such as
    `/etc/passwd` and `/root/secret.txt`. Reviewer gate passed 9/9. Canonical
    dev-container unittest ran 121 tests OK; canonical coverage passed with 87%
    total coverage. Dev-container ruff check and format check passed for the new
    candidate extraction files.
  - Reviewer gate target: 9 effective read-only reviewers.
  - Effective reviewer count: 9/9.
  - Reviewer agreement count: 9/9.
  - Reviewers with blocking findings: none.
  - Non-counted agents: none.
  - Active reviewers: none.
- [x] Add candidate preview tooling.
  - Owner paths: `python/formowl_graph/`, optional MCP boundary
  - Proof: preview output includes warnings, confidence, provenance, and review
    actions.
  - Test checklist:
    - [x] Candidate atom previews include confidence, provenance, warnings, and
      review actions without mutating proposal stores.
    - [x] Candidate relation previews include endpoint lineage, confidence,
      warnings, and review actions without canonical graph side effects.
    - [x] Preview filters return only requested candidates and reject malformed
      filter ids without leaking raw paths or partial preview output.
    - [x] Preview output rejects raw path or internal locator values from
      labels, properties, and warning text.
  - Note: implementation, README documentation, focused tests, and reviewer
    blocker fixes are complete. Reviewer gate passed 9/9. Canonical
    dev-container unittest ran 127 tests OK; canonical coverage passed with 88%
    total coverage. Dev-container ruff check and format check passed for the
    new candidate preview files.
  - Reviewer gate target: 9 effective read-only reviewers.
  - Effective reviewer count: 9/9 (`Meitner`, `Gibbs`, `Boole`, `Kant`,
    `Pauli`, `Aristotle`, `Hilbert`, `Lovelace`, `Linnaeus`).
  - Reviewer agreement count: 9/9 (`Meitner`, `Gibbs`, `Boole`, `Kant`,
    `Pauli`, `Aristotle`, `Hilbert`, `Lovelace`, `Linnaeus`).
  - Reviewers with blocking findings: none.
  - Non-counted agents: none.
  - Active reviewers: none.
- [x] Fix Gibbs blocker: candidate preview relation filter negative paths must
  be independently covered.
  - Owner paths: `python/formowl_graph/preview.py`,
    `tests/test_candidate_preview.py`
  - Proof: selected relation filters, missing relation warnings, malformed
    `candidate_relation_ids`, and relation filters without a relation store are
    asserted.
  - Note: implementation, Gibbs/Meitner re-review, and canonical dev-container
    verification passed.
- [x] Fix Gibbs blocker: candidate relation preview must warn for missing
  source endpoints.
  - Owner paths: `python/formowl_graph/preview.py`,
    `tests/test_candidate_preview.py`
  - Proof: relation preview emits exact `source_candidate_atom_not_found`
    warnings when the source atom is missing.
  - Note: implementation, Gibbs re-review, and canonical dev-container
    verification passed.
- [x] Fix Gibbs blocker: closed candidate review states must have explicit
  preview warnings and actions.
  - Owner paths: `python/formowl_graph/preview.py`,
    `tests/test_candidate_preview.py`
  - Proof: approved, rejected, or deferred atom/relation previews expose
    `reopen_review` and `status_not_pending_review:<status>`.
  - Note: implementation, Gibbs/Meitner re-review, and canonical dev-container
    verification passed.
- [x] Fix Gibbs blocker: preview redaction failures must not echo raw paths or
  internal locators in errors.
  - Owner paths: `python/formowl_graph/preview.py`,
    `tests/test_candidate_preview.py`
  - Proof: raised `ContractValidationError` messages omit raw path and locator
    values.
  - Note: implementation, Gibbs re-review, and canonical dev-container
    verification passed.
- [x] Fix Gibbs follow-up blocker: filtered preview no-mutation assertions must
  snapshot state before preview calls.
  - Owner paths: `tests/test_candidate_preview.py`
  - Proof: graph JSON state is captured immediately after fixture persistence
    and compared after successful and invalid filtered preview calls.
  - Note: implementation, Gibbs re-review, and canonical dev-container
    verification passed.
- [x] Fix Gibbs follow-up blocker: malformed filter errors must not echo raw
  path or locator input.
  - Owner paths: `tests/test_candidate_preview.py`
  - Proof: atom and relation invalid-filter exceptions omit submitted raw
    filter values.
  - Note: implementation, Gibbs re-review, and canonical dev-container
    verification passed.
- [x] Fix Kant blocker: candidate preview filters must reject bare strings,
  bytes, and non-sequence values.
  - Owner paths: `python/formowl_graph/preview.py`,
    `tests/test_candidate_preview.py`
  - Proof: atom and relation filters reject bare `str`, `bytes`, and
    non-sequence values without graph mutations or raw-value echo.
  - Note: implementation, Boole/Kant re-review, and canonical dev-container
    verification passed.
- [x] Fix Kant blocker: preview redaction must inspect property keys as well as
  values.
  - Owner paths: `python/formowl_graph/preview.py`,
    `tests/test_candidate_preview.py`
  - Proof: atom and relation properties with raw path or internal locator keys
    fail preview without raw-key echo or graph mutations.
  - Note: implementation, Kant re-review, and canonical dev-container
    verification passed.
- [x] Fix Boole blocker: preview redaction must reject obvious relative raw
  file references.
  - Owner paths: `python/formowl_graph/preview.py`,
    `tests/test_candidate_preview.py`
  - Proof: relative POSIX paths and Windows-style relative paths in labels or
    properties fail preview without raw-value echo or graph mutations.
  - Note: implementation, Boole re-review, and canonical dev-container
    verification passed.
- [x] Fix Pauli blocker: preview redaction must reject Windows dot-relative
  file references.
  - Owner paths: `python/formowl_graph/preview.py`,
    `tests/test_candidate_preview.py`
  - Proof: `.\\customer-secret.pdf` and `..\\customer-secret.pdf` fail preview
    without raw-value echo or graph mutations.
  - Note: implementation, Pauli re-review, and canonical dev-container
    verification passed.
- [x] Fix Pauli blocker: closed-status preview tests must assert no graph
  mutation.
  - Owner paths: `tests/test_candidate_preview.py`
  - Proof: approved, rejected, and deferred preview scenarios snapshot graph
    state before preview and assert unchanged state plus no canonical side
    effects.
  - Note: implementation, Pauli/Aristotle re-review, and canonical
    dev-container verification passed.
- [x] Fix Aristotle blocker: preview redaction must reject extensionless
  relative raw file references.
  - Owner paths: `python/formowl_graph/preview.py`,
    `tests/test_candidate_preview.py`
  - Proof: extensionless `docs/secrets` and `scratch\\secret` fail preview
    without raw-value echo or graph mutations.
  - Note: implementation, Aristotle re-review, and canonical dev-container
    verification passed.
- [x] Fix Aristotle blocker: preview no-mutation assertions must include
  non-JSON graph side effects.
  - Owner paths: `tests/test_candidate_preview.py`
  - Proof: preview tests compare all graph-relative paths and file contents,
    not only `*.json` payloads.
  - Note: implementation, Aristotle re-review, and canonical dev-container
    verification passed.
- [x] Fix Lovelace blocker: preview redaction must reject POSIX single-file
  dot-relative references.
  - Owner paths: `python/formowl_graph/preview.py`,
    `tests/test_candidate_preview.py`
  - Proof: `./customer-secret.pdf`, `../customer-secret.pdf`, `./secrets`, and
    `../secrets` fail preview without raw-value echo or graph mutations.
  - Note: implementation, Lovelace re-review, and canonical dev-container
    verification passed.
- [x] Fix Hilbert blocker: preview warning text must be redacted like labels
  and properties.
  - Owner paths: `tests/test_candidate_preview.py`
  - Proof: top-level and item warning text containing internal locators or
    relative paths fail `to_dict()` without raw-value echo.
  - Note: implementation, Hilbert re-review, and canonical dev-container
    verification passed.
- [x] Fix Hilbert blocker: preview warning assertions must be exact enough to
  catch bogus or missing items.
  - Owner paths: `tests/test_candidate_preview.py`
  - Proof: atom, relation, and closed-status preview tests assert exact warning
    sets/lists and expected candidate ids.
  - Note: implementation, Hilbert/Linnaeus re-review, and canonical
    dev-container verification passed.

### Governance and Canonical Graph

- [x] Add contract models for `CanonicalAtom`, `CanonicalEntity`,
  `CanonicalRelation`, and `CanonicalGraphRevision`.
  - Owner paths: `python/formowl_contract/`, `python/formowl_graph/`
  - Proof: canonical ids remain stable across revisions.
  - Note: implemented contract dataclasses, validators, stable id helpers, and
    package exports under `python/formowl_contract/`. Focused tests cover
    round-trip serialization, malformed lineage/status/hash cases, and stable
    canonical atom/entity/relation ids across graph revisions. Canonical
    dev-container unittest ran 208 tests OK.
- [x] Add policy contracts for extraction, atom granularity, entity resolution,
  relation resolution, lifecycle, and wiki projection.
  - Owner paths: `python/formowl_contract/`, `python/formowl_graph/policies.py`
  - Proof: policies serialize with versioned ids.
  - Note: implemented `ExtractionPolicy`, `AtomGranularityPolicy`,
    `EntityResolutionPolicy`, `RelationResolutionPolicy`, `LifecyclePolicy`,
    and `WikiProjectionPolicy` contracts with validators, versioned
    `stable_policy_id`, package exports, and graph-layer policy reference/hash
    helpers. Focused policy tests cover round-trip serialization, versioned id
    stability, active/kind checks, and malformed rule/id/raw-reference inputs.
    Canonical dev-container unittest ran 211 tests OK.
- [x] Implement reviewed canonical graph commit workflow.
  - Owner paths: `python/formowl_graph/canonical.py`,
    `python/formowl_graph/resolution.py`
  - Proof: only governed backend code can create canonical commits.
  - Note: implemented `commit_reviewed_candidates_to_canonical_graph` and
    `CanonicalGraphStore` as a governed backend path. Focused tests prove only
    approved candidates can commit, ontology and policy pins plus review
    decisions are required, candidate/observation/source/evidence/citation
    lineage is preserved, relation endpoints must resolve, duplicate canonical
    relation IDs cannot overwrite lineage within or across commits, raw
    internal locators are rejected, failed writes roll back canonical side
    effects, and no user graph or wiki revision state is created. Bernoulli
    performed read-only re-review and returned `RELEASE_DECISION: AGREE`.
    Canonical dev-container verification passed: `ruff check` and
    `ruff format --check` on changed files, focused canonical workflow unittest
    ran 10 tests OK, and full `python -m unittest discover -s tests` ran 221
    tests OK.
  - Return note: 2026-06-27 KG review found this slice is not complete. The
    current commit workflow creates a child `CanonicalGraphRevision` from only
    the newly committed candidate atoms/relations instead of carrying parent
    revision graph membership forward, and candidate relations can only resolve
    to atoms included in the same commit. Rework must prove incremental commits
    preserve prior graph membership and can safely relate to existing canonical
    endpoints without lineage overwrite or partial writes.
  - Rework note: 2026-06-27 rework completed. Child canonical graph revisions
    now load and validate same-scope committed parent revision state, retain
    parent atom/entity/relation membership, allow reviewed relation-only commits
    to resolve endpoints through parent candidate-to-canonical atom mappings,
    reject empty commits, reject corrupt parent relation endpoints, and keep
    all persistence behind `_persist_reviewed_commit`. Dev-container
    verification passed: changed-file Ruff check and format check, focused
    canonical workflow unittest ran 16 tests OK, full unittest ran 252 tests OK,
    default KG acceptance returned `passed_with_explicit_limits`, strict KG
    acceptance failed only on the known `production_adapter_readiness` failed
    and `latency_scalability_enterprise_claims` blocked items, and KG-eval
    unittest ran 360 tests OK. Reviewer gate for this rework slice: GPT/Codex
    reviewers `Kuhn-GPT`, `Goodall-GPT`, and `Pasteur-GPT` agreed after
    Pasteur's test-coverage blocker was fixed; Antigravity Gemini reviewers
    `Lamport-Sandbox`, `Ada-Sandbox`, and `Curie-Sandbox` agreed on the
    implementation diff through `agy`. A later attempt to send the test-only
    final diff to `agy` was blocked by sandbox/tenant data-egress policy, so no
    workaround was attempted.
- [x] Add lifecycle events for split, merge, archive, deprecate, supersede, and
  equivalence.
  - Owner paths: `python/formowl_graph/`
  - Proof: previous atom/entity/relation ids remain resolvable.
  - Note: implemented `CanonicalLifecycleEvent`,
    `CanonicalLifecycleResolution`, `CanonicalLifecycleStore`,
    `record_canonical_lifecycle_event`, and
    `resolve_canonical_lifecycle_id` under `python/formowl_graph/lifecycle.py`.
    Lifecycle events are mapping records only; they do not rewrite canonical
    atoms, entities, relations, user graphs, or wiki revisions. Focused tests
    cover the full atom/entity/relation by split/merge/archive/deprecate/
    supersede/equivalence matrix, multi-hop split-to-merge resolution,
    explicit graph revision, ontology revision, lifecycle policy, review
    decision, creator, and timestamp requirements, duplicate previous/target
    ids, generated event-id collisions, cycles, public serialization
    validation, raw/internal locator rejection without safe slash-prose false
    positives, full no-write snapshots on failures, restart persistence, and a
    lifecycle-only state allowlist. Canonical dev-container verification
    passed: `ruff check` and `ruff format --check` on lifecycle files, focused
    lifecycle unittest ran 8 tests OK, and full
    `python -m unittest discover -s tests` ran 229 tests OK.
  - Reviewer gate target: 9 effective read-only reviewers.
  - Effective reviewer count: 9/9.
  - Reviewer agreement count: 9/9 (`Gibbs`, `Dewey`, `Meitner`, `Pasteur`,
    `Russell`, `Helmholtz`, `Averroes`, `Chandrasekhar`, `Ramanujan`).
  - Reviewers with blocking findings: none after re-review.
  - Non-counted agents: `Hume` found initial blockers and agreed before later
    final-version raw-redaction changes, so he is retained as blocker history
    but not counted in the final 9/9 gate.
  - Active reviewers: none.

### User Graphs and Collaboration

- [x] Add `UserGraphProfile`, `UserGraphAssemblyPolicy`, and
  `UserKnowledgeGraphRevision` contracts.
  - Owner paths: `python/formowl_contract/`, `python/formowl_graph/user_graphs.py`
  - Proof: two users can assemble different valid graph views from the same
    canonical graph fixtures.
  - Note: initial contract implementation and focused tests are in place under
    `python/formowl_contract/models.py`, `python/formowl_contract/__init__.py`,
    and `tests/test_user_graph_contract.py`. Tests cover round-trip
    serialization, stable user graph ids including view-defining exclusions,
    user-authored atoms, private note ids, source refs, evidence snapshot ids,
    and permission scope, two different user views from the same canonical graph
    revision, owner-scope binding, permission scope, provenance, malformed graph
    content, duplicate and overlapping membership lists, raw/internal reference
    rejection, side-effect claim guards for grants, raw assets, access overlays,
    graph-store mutation, canonical graph mutation, canonical merges, and wiki
    revisions, and safe slash prose. Host supplemental focused unittest ran 3
    tests OK and host full unittest ran 232 tests OK. Canonical dev-container
    Ruff format/check/format-check passed, focused user graph unittest ran 3
    tests OK, and full dev-container unittest ran 232 tests OK. Final
    read-only reviewer gate passed 9/9 after blocker fixes and final delta
    re-review.
  - Reviewer gate target: 9 effective read-only reviewers.
  - Effective reviewer count: 9/9.
  - Reviewer agreement count: 9/9 (`Avicenna`, `Hegel`, `Confucius`,
    `Maxwell`, `Noether`, `Zeno`, `Feynman`, `Faraday`, `Turing`).
  - Reviewers with blocking findings: none after re-review.
  - Non-counted agents: none.
  - Active reviewers: none.
- [x] Add access overlay and grant-aware effective graph view.
  - Owner paths: `python/formowl_graph/`, auth/access modules
  - Proof: private evidence is not leaked without a grant.
  - Note: implementation and focused tests are in place under
    `python/formowl_graph/user_graphs.py`, `python/formowl_graph/__init__.py`,
    and `tests/test_effective_graph_view.py`. The slice assembles an in-memory
    `EffectiveGraphView` from a `UserKnowledgeGraphRevision` and graph
    projection records, exposes private graph fragments only with graph-level
    grants, rejects answer-only/evidence/raw-asset grants as graph-view access,
    returns access-required scope summaries without private node labels/source
    ids, rejects raw scope ids and unsafe visibility/grant ids without echoing
    them, gates access to private user graph revisions before scanning
    projection records, rejects raw/evidence/internal locators in visible
    graph-view payloads, and makes no graph-store, canonical, user-graph,
    raw-asset, or wiki writes. Host supplemental focused unittest ran 6 tests
    OK and host full unittest ran 238 tests OK. Canonical dev-container focused
    effective graph view unittest ran 6 tests OK, full dev-container unittest
    ran 238 tests OK, full dev-container Ruff check passed, and changed-file
    dev-container Ruff format check passed. Full-repo Ruff format check is
    blocked by unrelated pre-existing formatting drift outside this slice.
  - Reviewer gate target: 9 effective read-only reviewers.
  - Effective reviewer count: 9/9.
  - Reviewer agreement count: 9/9 (`Einstein`, `Singer`, `Pascal`,
    `Epicurus`, `Euler`, `Hypatia`, `Banach`, `Herschel`, `Nash`).
  - Reviewers with blocking findings: none after re-review. Initial blockers
    from `Banach`, `Herschel`, and `Nash` were fixed before final agreement.
  - Non-counted agents: none.
  - Active reviewers: none.
- [x] Add entity matching separate from data access and canonical merge.
  - Owner paths: `python/formowl_graph/resolution.py`
  - Proof: match proposals do not grant raw asset or evidence access.
  - Note: implemented candidate-only lexical and structured-linkage-compatible
    fusion proposal surfaces under `python/formowl_graph/resolution.py`.
    Tests cover threshold/config hashes, ontology revision pins, false-merge
    type gates, private-pair redaction, requester-visible rendering that omits
    hidden endpoints, clerical review queue creation, permission-aware human
    clerical review queue export, and forbidden
    canonical-merge/raw-asset-read guards. RapidFuzz now has an optional
    package-adapter manifest/binding surface and Splink has both a
    model-config manifest boundary and optional package-adapter binding surface.
    A locked main-repo container smoke now exercises both optional package
    bindings as candidate-only outputs without canonical graph writes or raw
    access. A separate locked adapter-stack smoke composes retrieval, semantic
    gateway dispatch, RapidFuzz/Splink candidate-only outputs, clerical-review
    packet export, and graph-derived wiki projection in the dev container. The
    human review export is a packet handoff only; RapidFuzz still lacks
    four-specialist LLM-subagent-reviewed false-merge labels with fixed
    professional roles. Legacy human-reviewed labels remain only a
    backward-compatible route, and these smokes are not completed
    RapidFuzz/Splink production adapter readiness.

### Wiki Projection

- [x] Add `WikiProjectionSpec` contract.
  - Owner paths: `python/formowl_contract/`, `docs/wiki-draft-schema.md`
  - Proof: projection specs include graph revision, ontology revision, source
    refs, evidence snapshots, and citation behavior.
  - Note: implemented `WikiProjectionSpec`,
    `stable_wiki_projection_spec_id`, contract validation, focused tests, and
    docs. Public specs reject private-evidence inclusion, raw paths, SQL, and
    private locators. Projection-spec-driven draft generation is still a
    separate unchecked task.
- [x] Implement projection-spec-driven draft generation.
  - Owner paths: `python/formowl_wiki_mcp/`, `python/formowl_graph/`
  - Proof: graph-derived drafts preserve graph lineage in frontmatter.
  - Note: implemented `generate_wiki_draft_from_graph_view` plus
    `formowl_wiki_mcp.projection`. Tests cover visible-evidence-only graph
    views, ontology revision pins, source/evidence lineage, draft-not-publish
    behavior, diff-on-refresh, hidden evidence rejection, raw private evidence
    rejection, and graph/ontology revision mismatch rejection.
- [x] Extend `WikiRevision` lineage fields.
  - Owner paths: `python/formowl_contract/`,
    `python/formowl_wiki_mcp/markdown/`
  - Proof: wiki revisions can point back to user graph revisions and projection
    specs.
  - Note: `WikiRevision` now carries optional `projection_spec_id`,
    `graph_revision_id`, `ontology_revision_id`, `user_graph_revision_id`,
    `graph_view_hash`, and `evidence_snapshot_refs`; focused contract tests
    cover these lineage fields.

### KG Research Evaluation and Acceptance

- [x] Add scoped ontology/type governance contracts and KG research acceptance
  suite.
  - Owner paths: `python/formowl_contract/`, `python/formowl_graph/`,
    `scripts/`, `tests/`, `docs/`
  - Proof: type definitions keep core, extension, promoted, mapping, alias, and
    alignment candidate state separate; alignment candidates remain
    review-required and cannot grant access or write canonical type state; the
    acceptance suite reports literature, ontology, multi-user fusion,
    multimodal fixtures, four-specialist LLM subagent adjudication semantics
    with fixed professional roles, legacy human compatibility, production
    adapter boundary, metrics, ablations, and explicit failed/blocked
    readiness claims.
  - Note: implementation, docs, focused dev-container ontology tests, focused
    dev-container acceptance tests, and default acceptance script are in place.
    Reviewer blockers for direct `score_breakdown` validation, unexpected
    acceptance failures, and concrete error-analysis evidence have been fixed.
    Full canonical dev-container unittest passed, and the configured
    6-reviewer gate passed.
  - Reviewer gate target: 6 effective read-only reviewers: 3 Codex/GPT and 3
    Antigravity Gemini through `agy`.
  - Effective reviewer count: 6/6.
  - Reviewer agreement count: 6/6 (`Kuhn`, `Goodall`, `Pasteur`,
    `Ada-Sandbox`, `Lamport-Sandbox`, `Curie-Sandbox`).
  - Reviewers with blocking findings: none after re-review.
  - Non-counted agents: `Raman` found initial blockers and was replaced for
    re-review after being closed; initial Antigravity Gemini attempts were
    rejected by sandbox policy for external model data-egress risk and do not
    count; `Ada` timed out without a decision and does not count; `Ada-Retry`
    attempted to inspect repository files instead of staying within the
    bounded packet and was aborted/timed out, so it does not count.
  - Historical resume note: future sessions were previously told to ask the
    user at the start of this goal for explicit Antigravity Gemini
    bounded-review authorization. That rule is superseded by the 2026-06-28
    gate-policy checkpoint below: `agy` is disabled by default for FormOwl KG
    reviewer gates unless the user explicitly re-enables it after policy,
    platform, or MCP configuration changes.
  - Active reviewers: none.
  - Canonical verification: changed-file Ruff check and format check passed;
    focused dev-container ontology contract unittest ran 4 tests OK; focused
    KG research acceptance unittest ran 4 tests OK; full dev-container
    `python -m unittest discover -s tests` ran 246 tests OK; default
    `python scripts/kg_research_acceptance_suite.py` reports expected
    `production_adapter_readiness` failed and
    `latency_scalability_enterprise_claims` blocked with no unexpected failed
    or blocked items. On 2026-06-27, current-state re-verification passed:
    default KG research acceptance suite returned
    `passed_with_explicit_limits`, focused KG acceptance tests ran 4 OK,
    focused ontology tests ran 4 OK, and full dev-container unittest ran
    246 tests OK.

- [x] Complete the full KG real-evidence objective across sessions.
  - Owner paths: `docs/agent-goals/`, `.formowl/kg-eval/`, KG-owned graph,
    ontology, evaluation, and test files.
  - Proof: `.formowl/kg-eval/results/kg_total_acceptance_snapshot.json`
    reports `overall_passed=true`, 12 passed gates, and 0 failed gates;
    `.formowl/kg-eval/remaining_evidence_checklist.json` reports
    `remaining_gates=[]`; `.formowl/kg-eval/results/kg_objective_completion_audit.json`
    reports `objective_complete=true` with 9 proved requirements and 0
    incomplete requirements; canonical dev-container KG-eval and main-repo
    tests pass; broad preflight/work-order/progress reports show no remaining
    broad real-evidence work; and the four-professional-specialist LLM subagent
    adjudication route is bound into the accepted evidence where Plan B is used.
    Main-repo `scripts/kg_research_acceptance_suite.py --strict` still exits 1
    for the intentionally unclaimed product-level limits
    `production_adapter_readiness` and `latency_scalability_enterprise_claims`;
    that strict product boundary is not part of this broad KG real-evidence
    completion claim.
  - Current failed broad gates: none.
  - Current cleared broad gates:
    `fair_external_baseline_comparison`, `annotation_adjudication_protocol`,
    `multimodal_semantic_validation`, and `production_adapter_paths` all have
    accepted canonical packets, validator-clear status, and four-specialist LLM
    subagent approval where Plan B adjudication is used. The annotation route
    does not claim completed human annotation.
  - 2026-06-28 broad KG real-evidence completion sync:
    Broad KG-eval is now `overall_passed=true` with 12 passed gates and 0
    failed gates. `remaining_evidence_checklist.json` has
    `overall_passed=true`, `passed_gate_count=12`, `failed_gate_count=0`, and
    `remaining_gates=[]`. Current hashes: gate status
    `9e68c2a78681c86ff52f6ef25f20d3f6112183dcb681f137f6d349e7e4c96aba`,
    objective audit
    `b37edc1a2cf5d9891557f91f669608204998d3a8112fa0a299e3a99d082bb44d`.
    `real_evidence_preflight.py` reports
    `preflight_state=validator_clear_for_all_broad_gates`; work orders report
    `work_order_count=0`; gate progress reports `gate_count=0`. Claim boundary:
    this closes KG broad real-evidence acceptance only, not full product
    production readiness, top-tier scientific validation, raw asset access,
    canonical graph writes, autonomous business judgment, or enterprise-scale
    latency/scalability.
  - 2026-06-29 package facade handoff:
    added the `formowl_kg_eval` package and `formowl-kg-eval` CLI as the stable
    integration facade over the `.formowl/kg-eval` research harness. The System
    Backbone Agent should call `formowl-kg-eval summary` or the
    `build_acceptance_summary()` API instead of importing repo-local evaluator
    scripts directly. `docs/kg-eval-package.md` documents the CLI, Python API,
    claim boundary, and system integration contract. Focused package tests cover
    workspace resolution, authoritative script invocation, redacted summary
    shape, and CLI JSON output.
  - 2026-06-28 annotation-promotion status sync:
    Broad KG-eval is now `overall_passed=false` with 10 passed gates and 2
    failed gates. The remaining failed gates are
    `multimodal_semantic_validation` and `production_adapter_paths`; both are
    still at `missing_operator_response`, with empty real roots and absent
    canonical packets. The objective audit is still incomplete with 7 proved
    requirements and 2 incomplete requirements. Do not mark this work-board
    item complete until both remaining gates have accepted canonical packets
    and strict acceptance passes. This note is superseded by the 12/12 broad KG
    real-evidence completion sync above.
  - 2026-06-28 earlier status-tool drift fix:
    KG-eval preflight, work orders, gate progress, and dependent tests now use
    the non-cleared failed gate set for remaining work while still monitoring
    the historical four-gate evidence surface. Canonical dev-container
    verification passed for full KG-eval unittest 586 OK, main repo unittest
    252 OK, refreshed broad reports, guide/template/progress checks, and full
    Ruff check/format-check. At that checkpoint broad KG-eval was
    `overall_passed=false`, 9 passed gates, and 3 failed gates; this is
    superseded by the 10/12 annotation-promotion status sync above.
  - 2026-06-28 operator response-packet preflight note:
    the four candidate-only response-intake CLIs now support
    `--preflight-response`, and the submission-manifest intake plan, work
    orders, and operator guide expose paired response-preflight commands before
    candidate-only intake. The preflight validates response-packet shape,
    work-packet/output binding, planned artifact surfaces, raw/internal guards,
    and no-overwrite/parent-dir surfaces without writing candidate artifacts,
    candidate manifests, or canonical broad packets. Reviewer blocker fix:
    enterprise-multimodal and production-adapter intake now reject forged
    same-type work packets by comparing the generated work-packet state, roots,
    canonical target, collection plans, validator expectation, and
    `work_packet_sha256`. Canonical dev-container verification passed for
    focused response-intake/submission/work-order/operator-guide unittest
    162 OK, full KG-eval unittest 524 OK, main repo unittest 252 OK,
    guide/template checks, refreshed broad reports, full Ruff check,
    format-check, and `git diff --check`. The item remains unchecked
    because broad KG-eval still reports `overall_passed=false`, 8 passed
    gates, and the same four failed real-evidence gates; all four stages are
    still `missing_operator_response` with empty real roots and absent
    canonical broad packets.
  - 2026-06-28 submission-manifest response-preflight runner checkpoint:
    `real_evidence_submission_manifest.py --preflight-responses` now validates
    the operator-filled submission manifest first, then runs the four fixed
    response-intake helper `--preflight-response` argv without a shell. It
    requires existing response packets, refuses pre-existing canonical packet
    path hazards before subprocess launch, stops on the first failed response
    preflight, and fails closed if a helper leaves a final-state canonical
    packet surface, candidate output surface, or candidate-manifest output
    changed. The runner reads response-packet contents only through the
    existing preflight helpers; it writes no candidate artifacts, writes no
    candidate manifest, promotes no evidence, writes no canonical broad
    packets, and does not count as an acceptance gate. Canonical dev-container
    verification passed: focused submission/guide unittest 63 OK, full
    KG-eval unittest 531 OK, main repo unittest 252 OK, guide/template/
    approval-template/response-template/progress checks, refreshed broad
    reports, default main KG acceptance `passed_with_explicit_limits`, strict
    main KG acceptance exits 1 only for known limits, full Ruff check and
    format-check. Reviewer gate passed 3/3: `Huygens`, `Gauss`, and `Ohm`
    returned `RELEASE_DECISION: AGREE` after Huygens' direct canonical-drift
    test suggestion was implemented. The item remains unchecked because this
    hardening accepts no evidence and broad KG-eval still reports
    `overall_passed=false`, 8 passed gates, and the same four failed
    real-evidence gates; all four stages remain `missing_operator_response`
    with empty real roots and absent canonical broad packets.
  - 2026-06-28 blocked audit after `1e2010f`: current-state inspection found
    no operator/user-supplied files under the four ignored `inputs/*_real/`
    roots, no operator-filled submission/candidate/approval surfaces under
    `work_packets/`, and no canonical broad evidence packets. Progress remains
    four gates at `missing_operator_response` with zero candidate manifests,
    zero clear candidate-validation reports, zero valid approvals, and zero
    canonical validator clears. The item remains unchecked and is now blocked
    on external operator/user evidence; additional repository-side hardening
    should not be treated as checkpoint progress unless it accompanies real
    evidence intake, validation, approval, promotion, and validator acceptance.
  - Note: the checked item above is only the scoped ontology and
    method/acceptance-harness slice. It does not prove fair external baseline
    execution, real adjudication through the current Plan B four-specialist LLM
    subagent panel with fixed professional roles, real enterprise multimodal
    validation, production adapter evidence, or production
    latency/scalability. Existing validators still keep legacy human evidence
    as a backward-compatible route.
  - Portability note: on 2026-06-27, the sanitized `.formowl/kg-eval` harness,
    restart note, fixtures, templates, work orders, preview packets, and
    non-authoritative blocked-state snapshots were made git-trackable so
    another session can reproduce the stricter broad gate. Runtime generated
    `results/`, local long-form handoff history, operator real artifact roots,
    and canonical real evidence packets remain ignored. The item stays
    unchecked because the four broad real-evidence gates still fail.
  - 2026-06-28 status-only resume note: work-board unchecked engineering item
    count remains 9 total, consisting of this KG-owned full real-evidence
    objective plus 8 System Backbone/product-infra items. Dev-container
    KG-eval unittest ran 450 OK and main repo unittest ran 252 OK during this
    resume. A subsequent dev-container report refresh was blocked by
    environment approval policy; sandbox host-level supplemental reports still
    show the same blocked state, all four real roots empty, and all four
    canonical broad evidence packets absent.
  - 2026-06-28 intake-plan partial-write hardening note:
    `real_evidence_submission_manifest.py --emit-intake-plan` now uses a
    temporary file plus atomic no-overwrite link so an interrupted operator
    intake-plan write does not leave a partial final or temporary JSON plan.
    Host verification passed for focused submission-manifest unittest 41 OK,
    full KG-eval unittest 451 OK, main repo unittest 252 OK, guide/template
    checks, and host main KG acceptance with the same known limits. The item
    stays unchecked because this hardening accepts no evidence and the four
    broad real-evidence gates still fail.
  - 2026-06-28 real-root churn preflight hardening note:
    `real_evidence_preflight.py` now records files that disappear during
    `inputs/*_real` scanning as unstable non-evidence via
    `disappeared_file_count` and `disappeared_file_paths`; disappearing files
    are not counted as files or candidate artifacts and cannot make a root
    ready. Host verification passed for focused preflight unittest 18 OK,
    focused submission-manifest unittest 41 OK, full KG-eval unittest 452 OK,
    main repo unittest 252 OK, broad report refresh, guide/template checks,
    and host main KG acceptance with the same known limits. The item stays
    unchecked because this hardening accepts no evidence and the four broad
    real-evidence gates still fail.
  - 2026-06-28 work-order disappeared-file contract hardening note:
    `real_evidence_collection_work_orders.py` now requires each per-gate
    preflight row to expose `disappeared_file_count` as a non-bool integer and
    to keep it at `0` before normal collection work orders are emitted. The
    work-order `preflight_snapshot` includes
    `real_root_disappeared_file_count`, and disappeared real-root files now
    fail closed as preflight contract drift instead of being treated as clean
    absence. Reviewer blocker fix: real-root scanning now uses `lstat()` before
    file-type classification, so a path that disappears before the old
    `is_file()` check is reported through `disappeared_file_count` instead of
    being silently treated as clean absence. Canonical dev-container
    verification passed for focused current-slice KG-eval unittest 79 OK, full
    KG-eval unittest 454 OK, main repo unittest 252 OK, guide/template checks,
    refreshed broad reports, default main KG acceptance with the same known
    limits, full Ruff check and format-check, and `git diff --check`. Reviewer
    gate passed 3/3 after blocker fixes: `Curie`, `Erdos`, and `Hume` returned
    `RELEASE_DECISION: AGREE`. The item stays unchecked because this hardening
    accepts no evidence and the four broad real-evidence gates still fail.
  - 2026-06-28 historical blocked audit note, superseded later the same day by
    user authorization and canonical verification: canonical dev-container
    Docker verification had been rejected by the approval reviewer, so reviewer
    gate and commit/push could not proceed at that time. This is no longer the
    current Docker/Git state for this run. The item remains unchecked because
    the four broad real-evidence gates still require real operator/user-supplied
    evidence packets.
  - 2026-06-28 resume authorization note: the user explicitly authorized
    collecting failed-gate evidence, Docker/dev-container access, and Git
    commit/push. The previous Docker/Git approval blocker is cleared for this
    run, and canonical dev-container verification plus the 3 Codex/GPT reviewer
    gate for the current hardening slice have passed. The item remains unchecked
    because full KG acceptance still requires real operator/user-supplied
    evidence and validator-accepted canonical packets for the four broad gates.
  - 2026-06-28 post-push note: the work-order/preflight hardening slice above
    was committed and pushed to `complete-slice-1` as `8fc5a55`
    (`Harden KG real-evidence preflight work orders`). The worktree was clean
    and local `HEAD` matched `origin/complete-slice-1` before the follow-up
    status-doc checkpoint. The item remains unchecked because the four broad
    real-evidence gates still require real operator/user-supplied artifacts and
    validator-accepted canonical packets.
  - 2026-06-28 candidate-runner canonical packet integrity checkpoint:
    `real_evidence_submission_manifest.py --execute-candidate-intakes` and
    `--validate-candidate-manifests` now snapshot the four canonical broad
    packet paths before subprocess execution and fail closed if a subprocess
    exits with a canonical packet path created or changed. The guard reports
    `canonical_packet_integrity`, stops immediately on final-state canonical
    packet drift, and keeps the runner outputs non-evidence. The tracked
    operator guide documents this final-state boundary. This accepts no
    evidence, promotes no evidence, writes no canonical broad packets, and does
    not count as acceptance. Canonical dev-container verification passed:
    focused submission/guide unittest 51 OK, full KG-eval unittest 456 OK,
    main repo unittest 252 OK, guide/template checks, refreshed broad reports,
    default main KG acceptance `passed_with_explicit_limits`, strict main KG
    acceptance exits 1 only for known limits, and full Ruff check/format-check.
    Broad KG-eval remains incomplete with `overall_passed=false`, 8 passed
    gates, and the same four failed real-evidence gates. Reviewer gate passed
    3/3: `Sagan`, `Hooke`, and `Laplace` agreed. A mistaken no-op `Banach`
    subagent is not counted. The item remains unchecked because real
    operator/user-supplied artifacts and validator-accepted canonical packets
    are still missing for the four broad gates.
  - 2026-06-28 candidate-runner pre-existing canonical packet hazard
    checkpoint: `real_evidence_submission_manifest.py
    --execute-candidate-intakes` and `--validate-candidate-manifests` now fail
    closed before subprocess launch if any canonical broad packet path is
    already a symlink, hardlink alias, non-regular file, or unreadable /
    metadata-unavailable surface. In that state the execution reports
    `canonical_packet_baseline`, sets `executed_gate_count=0`, reads no
    response packet or candidate manifest contents, writes no candidate
    artifacts, promotes no evidence, and writes no canonical broad packets.
    The tracked operator guide documents the boundary. Canonical dev-container
    verification passed: focused submission/guide unittest 55 OK, full KG-eval
    unittest 460 OK, main repo unittest 252 OK, guide/template checks,
    refreshed broad reports, default main KG acceptance
    `passed_with_explicit_limits`, strict main KG acceptance exits 1 only for
    known limits, full Ruff check/format-check, and `git diff --check`. Broad
    KG-eval remains incomplete with `overall_passed=false`, 8 passed gates,
    and the same four failed real-evidence gates. Reviewer gate passed 3/3:
    `Wegener` agreed on engineering correctness after the canonical packet
    test helper was changed to preserve pre-existing path surfaces by rename;
    `Feynman` agreed on governance/safety; and `Kuhn` agreed on status
    honesty.
    The item remains unchecked because real operator/user-supplied artifacts
    and validator-accepted canonical packets are still missing for the four
    broad gates.
  - 2026-06-28 governed approval-bridge checkpoint:
    `real_evidence_governance_approval.py` now provides the controlled
    non-evidence bridge from a validate-only candidate report to an approved
    canonical packet update. It validates exact approval manifest fields,
    human approver identity, exact approval scope and claim boundary, current
    candidate validation report hash, current candidate manifest hash, a
    passing target-gate validation row with exact validate-only argv, safe
    report/manifest names, a missing target canonical packet, and a
    hazard-free canonical packet baseline. Execute mode uses fixed assembler
    `--promote` argv plus `--assembly-manifest-sha256` so the manifest bytes
    consumed by the assembler must match the approved candidate-manifest hash;
    it also rehashes the candidate manifest after the subprocess, verifies only
    the target canonical packet changed, and rolls back a newly created target
    packet when candidate-manifest drift is detected. The four packet
    assemblers now use temporary-file plus atomic no-overwrite hard-link
    promotion and reject mismatched approved manifest bytes before assembly or
    promotion; candidate validation reports include
    `candidate_manifest_sha256`; canonical packet surface checks reject parent
    symlinks, missing parents, metadata-unavailable parents, and non-directory
    parents; and the operator guide documents approval validation and
    `--execute-approved-promotion`. Canonical dev-container verification
    passed: focused approval/assembler/operator-guide unittest 78 OK;
    approval-template,
    operator-guide, and submission-template checks; full KG-eval unittest
    474 OK; main repo unittest 252 OK; full Ruff check and format-check;
    refreshed broad reports; default KG acceptance
    `passed_with_explicit_limits`; strict KG acceptance exits 1 only for known
    limits. All four real roots remain empty and the four canonical broad
    packets remain absent. Reviewer gate passed 3/3 after Bernoulli's
    candidate-manifest TOCTOU blocker was fixed and re-reviewed:
    `Bernoulli`, `Popper`, and `Dalton` returned `RELEASE_DECISION: AGREE`.
    The item remains unchecked because real operator/user-supplied
    artifacts and validator-accepted canonical packets are still missing for
    the four broad gates.
  - 2026-06-28 governed approval promotion failure rollback checkpoint:
    `real_evidence_governance_approval.py --execute-approved-promotion` now
    removes a newly created target canonical broad packet when an approved
    promotion subprocess fails after creation. The rollback covers nonzero
    subprocess return, subprocess `OSError`, and Pasteur's hardlink-alias
    blocker where assembler promotion fails after `os.link(temp_path,
    output_path)` but before removing the temporary file. This accepts no
    evidence, writes no durable canonical broad packet on failure, and does
    not count as acceptance. Canonical dev-container verification passed after
    the hardlink fix: focused approval/operator-guide/submission unittest
    68 OK, full KG-eval unittest 500 OK, main repo unittest 252 OK,
    guide/template checks, refreshed broad reports, default KG acceptance
    `passed_with_explicit_limits`, strict KG acceptance exits 1 only for known
    limits, full Ruff check/format-check, and `git diff --check`. Broad
    KG-eval remains incomplete with `overall_passed=false`, 8 passed gates,
    and the same four failed real-evidence gates. Reviewer gate passed 3/3
    after Pasteur's hardlink-alias rollback blocker was fixed and re-reviewed:
    `Chandrasekhar`, `Pasteur`, and `Locke` returned
    `RELEASE_DECISION: AGREE`. The item remains unchecked because real
    operator/user-supplied artifacts and validator-accepted canonical packets
    are still missing for the four broad gates.
  - 2026-06-28 gate-progress report checkpoint:
    `.formowl/kg-eval/real_evidence_gate_progress.py` now writes a
    non-authoritative status report at
    `.formowl/kg-eval/results/real_evidence_gate_progress.json` that maps the
    four remaining real-evidence gates to explicit collection stages:
    `missing_operator_response`,
    `candidate_artifacts_present_without_manifest`,
    `candidate_manifest_present_pending_validation`,
    `candidate_validation_failed_or_stale`,
    `candidate_validation_clear_pending_approval`,
    `approval_valid_pending_promotion`,
    `canonical_packet_present_needs_validator_clear`, or
    `canonical_packet_validator_clear`. It reads persisted
    preflight/work-order reports plus safe `work_packets/` candidate manifest,
    candidate-validation report, and approval-manifest surfaces; it does not
    refresh preflight, read operator response packets, read candidate artifact
    contents, write candidate artifacts, promote evidence, write canonical
    packets, or count as acceptance. The
    tracked operator guide now includes the progress-report command. Current
    refreshed progress still reports all four gates at
    `missing_operator_response`, with zero candidate manifests, zero clear
    validation reports, zero valid approval manifests, empty real roots, and
    absent canonical broad packets. Canonical dev-container verification after
    reviewer blocker fixes passed: focused progress/operator-guide unittest
    20 OK, full KG-eval unittest 512 OK, main repo unittest 252 OK,
    guide/progress checks,
    refreshed broad reports, default KG acceptance `passed_with_explicit_limits`,
    strict KG acceptance exits 1 only for known limits, full Ruff
    check/format-check, and `git diff --check`. Reviewer gate passed 3/3:
    `Plato` agreed on status honesty after the stage-label docs were
    completed, `Carson` agreed after the candidate-manifest symlink/hardlink
    hash-current blocker was fixed, and `Russell` agreed after source-report
    contract withholding plus rejected approval-surface reporting were added.
    The item remains unchecked because this status aid accepts no evidence and
    the four broad gates still require real operator/user-supplied artifacts
    plus validator-accepted canonical packets.
  - 2026-06-28 enterprise-multimodal response-intake parity hardening
    checkpoint: `enterprise_multimodal_response_intake.py` now matches the
    hardened candidate-only response-intake baseline for raw/internal field
    names and custody-phase rollback. Operator-supplied enterprise multimodal
    artifact payloads recursively reject raw/internal field names such as
    backend connection strings, database/object-store locators, raw SQL,
    scratch paths, and raw paths even when the submitted value is otherwise
    benign. Custody receipt construction, optional assembly-manifest hashing,
    custody write, and custody receipt hashing are now inside rollback
    handling, so intake-created candidate artifacts and optional manifests are
    removed if custody hashing or custody write fails after writes. The
    enterprise work-order response contract and tracked operator guide now
    list output-dir binding, top-level/validation wrapper allowlisting,
    raw/internal field-name rejection, parent-dir preflight, after-open
    cleanup, rollback, and optional manifest custody hashing. Canonical
    dev-container verification passed: focused
    enterprise-intake/work-order/operator-guide unittest 47 OK, full KG-eval
    unittest 514 OK, main repo unittest 252 OK, guide/progress checks, full
    Ruff check/format-check, and `git diff --check`. Broad KG-eval remains
    incomplete with `overall_passed=false`, 8 passed gates, and the same four
    failed gates; all four real roots remain empty and canonical broad packets
    remain absent. Reviewer gate passed 3/3: `Socrates` agreed on engineering
    correctness, `Gibbs` agreed on governance/safety, and `Pascal` agreed on
    status honesty. The item remains unchecked because this hardening accepts
    no evidence, writes no canonical broad packet, and the four broad
    real-evidence gates still require real operator/user-supplied artifacts
    plus validator-accepted canonical packets.
  - 2026-06-28 operator response-packet template checkpoint:
    `.formowl/kg-eval/real_evidence_response_packet_templates.py` now emits
    and checks four tracked non-evidence operator response-packet templates
    under `work_packets/` for the remaining gates:
    `fair_baseline_response_packet.template.json`,
    `human_annotation_response_packet.template.json`,
    `enterprise_multimodal_response_packet.template.json`, and
    `production_adapter_response_packet.template.json`. The templates provide
    an operator-fillable starting shape for the first missing response packets
    and are generated from validator constants for required baselines,
    modalities, and adapter components where applicable. They deliberately
    include `template_only`, `do_not_submit_as_evidence`, `gate_id`,
    `claim_boundary`, and operator instructions, and tests prove each template
    is rejected by its response-intake helper as-is without candidate artifact,
    candidate manifest, or canonical packet writes. The tracked operator guide
    now lists the templates and check command. Canonical dev-container
    verification passed: focused response-template/operator-guide unittest
    11 OK, full KG-eval unittest 517 OK, main repo unittest 252 OK,
    response-template/operator-guide/submission-template/approval-template/
    progress checks, full Ruff check/format-check, and `git diff --check`.
    Reviewer gate passed 3/3: `Euclid` agreed on engineering correctness,
    `Schrodinger` agreed on governance/safety, and `Franklin` agreed on status
    honesty. The item remains unchecked because this slice accepts no evidence,
    writes no real artifacts, writes no canonical broad packet, and all four
    broad real-evidence gates still require real operator/user-supplied
    artifacts plus validator-accepted canonical packets.
  - 2026-06-28 human annotation response-intake hardening checkpoint:
    `human_annotation_response_intake.py` now requires response-packet
    top-level allowlisting, `operator_run_id` binding to the candidate output
    directory, unsupported nested field rejection, raw/internal field-name
    rejection, parent directory preflight, nested default real-root output-dir
    rejection, after-open partial write cleanup, and rollback of already
    created candidate artifacts plus optional candidate manifests when
    assembly or validation execution raises after writes. A completed
    validate-only report with `passed=false` remains candidate-only evidence
    state, not canonical evidence. It also emits a non-authoritative response
    custody receipt binding the operator response packet hash,
    candidate packet hash, candidate artifact hashes, and optional
    candidate-manifest hash. The tracked operator guide now lists these
    controls for `annotation_adjudication_protocol`. Canonical dev-container
    verification passed: focused human-intake/work-order/operator-guide
    unittest 48 OK, full KG-eval unittest 482 OK, main repo unittest 252 OK,
    guide/template checks, refreshed broad reports, default KG acceptance
    `passed_with_explicit_limits`, strict KG acceptance exits 1 only for known
    limits, full Ruff check/format-check, and `git diff --check`. The item
    remains unchecked because this hardening accepts no evidence, writes no
    canonical broad packet, and the four broad real-evidence gates still
    require real operator/user-supplied artifacts plus validator-accepted
    canonical packets. Reviewer gate passed 3/3: `Socrates` agreed on
    engineering correctness, `Gibbs` agreed on governance/safety after the
    validation-report wording was narrowed, and `Pascal` agreed on status
    honesty after the same wording update.
  - 2026-06-28 fair-baseline response-intake hardening checkpoint:
    `fair_baseline_response_intake.py` now requires response-packet
    top-level allowlisting, `operator_run_id` binding to the candidate output
    directory, baseline-run and adjudication/graph-quality/permission-probe
    wrapper-field allowlisting, raw/internal field-name rejection throughout
    the response payload, parent directory preflight, default real-root
    output-dir restriction to
    `inputs/fair_baseline_real/<operator_run_id>`, after-open partial write
    cleanup, and rollback of already-created candidate artifacts plus optional
    candidate manifests when assembly or validation execution raises after
    writes. It still emits only non-authoritative candidate artifacts and a
    response custody receipt binding the operator response packet hash,
    candidate packet hash, candidate artifact hashes, and optional
    candidate-manifest hash. The tracked operator guide now lists these
    controls for `fair_external_baseline_comparison`. Canonical
    dev-container verification passed: focused fair-intake/work-order/operator
    guide unittest 46 OK, full KG-eval unittest 490 OK, main repo unittest
    252 OK, guide/submission-template/approval-template checks, refreshed
    broad reports, default KG acceptance `passed_with_explicit_limits`,
    strict KG acceptance exits 1 only for known limits, full Ruff check and
    format-check, and `git diff --check`. Broad KG-eval remains incomplete
    with `overall_passed=false`, 8 passed gates, and the same four failed
    gates; all four real roots remain empty and canonical broad packets remain
    absent. Reviewer gate passed 3/3 after blocker fixes: `Arendt` agreed on
    engineering correctness after the final delta, `Confucius` agreed on
    governance/safety after the work-order report stopped emitting an
    absolute local workspace path, and `Lorentz` agreed on status honesty
    after the operator guide/control inventory listed parent-dir preflight,
    after-open cleanup, and rollback controls. The item remains unchecked
    because this hardening accepts no evidence, writes no canonical broad
    packet, and the four broad real-evidence gates still require real
    operator/user-supplied artifacts plus validator-accepted canonical packets.
  - 2026-06-28 production-adapter response-intake parity hardening
    checkpoint: `production_adapter_response_intake.py` now rejects
    raw/internal field names throughout operator-supplied artifact payloads,
    including backend connection-string, database/object-store/raw SQL/worker
    scratch, and bucket/object-key field names whose values are otherwise
    benign. It also removes files created by exclusive open when serialization
    or write fails after open, catches raw `OSError` write and custody-hash
    failures so earlier candidate artifacts roll back, and focused tests now
    cover raw/internal field-name rejection, backend connection-string
    field-name rejection, assembler-failure rollback, raw `OSError` rollback,
    custody-phase hash failure rollback, and after-open partial-write cleanup.
    The production work-order response
    contract and tracked operator guide now list the same parent-dir
    preflight, after-open cleanup, rollback, output-dir binding, allowlisting,
    and manifest-custody controls that the intake implements. Canonical
    dev-container verification passed: focused production-intake/work-order/
    operator-guide unittest 47 OK, full KG-eval unittest 497 OK, main repo
    unittest 252 OK, guide/submission-template/approval-template checks,
    refreshed broad reports, default KG acceptance
    `passed_with_explicit_limits`, strict KG acceptance exits 1 only for known
    limits, full Ruff check/format-check, and `git diff --check`. Broad
    KG-eval remains incomplete with `overall_passed=false`, 8 passed gates,
    and the same four failed gates; all four real roots remain empty and all
    four canonical broad packets remain absent. Reviewer gate passed 3/3:
    `Heisenberg` agreed on status honesty after the restart note stopped
    claiming commit/push readiness, `Curie` agreed after backend
    connection-string field-name rejection was added, and `Raman` agreed after
    raw write and custody-phase rollback gaps were fixed. The item remains
    unchecked because this hardening accepts no
    evidence, writes no canonical broad packet, and the four broad
    real-evidence gates still require real operator/user-supplied artifacts
    plus validator-accepted canonical packets.
  - 2026-06-27 fair-baseline response-intake note: candidate-only intake is
    implemented for `fair_external_baseline_comparison` and wired into the
    collection work orders. It can seal operator-supplied fair-baseline
    response JSON into candidate artifacts and custody receipts without writing
    the canonical fair-baseline packet or changing acceptance state.
    Reviewer blockers for manifest custody hashing, post-write assembler
    failures, parent-file partial writes, and production-shaped test cleanup
    were fixed. Dev-container KG-eval unittest ran 372 tests OK; main repo
    unittest ran 252 tests OK; changed-file Ruff check and format-check passed;
    refreshed broad KG-eval reports still show `overall_passed=false`, 8
    passed gates, and 4 failed gates. GPT/Codex reviewer gate is 3/3 agreed
    after blocker fixes. Antigravity Gemini reviewer gate is blocked at 0/3 by
    tenant policy rejection of both code/diff and closed-book bounded `agy`
    packets; no external-channel workaround was attempted.
  - 2026-06-27 production-adapter response-intake checkpoint:
    candidate-only intake is implemented for `production_adapter_paths` and
    wired into the collection work orders. It can seal operator-supplied
    production-adapter response JSON into candidate artifacts under
    `inputs/production_adapter_real/<operator-run-id>` and optional candidate
    manifests under `work_packets/`, records response/candidate/artifact and
    manifest custody hashes, rejects unsafe paths, symlinks, overwrites,
    parent-file collisions, raw/internal/template payloads, duplicate/missing
    adapter components, and promotion arguments, and never writes
    `inputs/production_adapter_evidence_packet.json`. Dev-container
    verification passed so far: changed-file Ruff check and format-check,
    focused KG-eval unittest 27 OK, full KG-eval unittest 383 OK, main repo
    unittest 252 OK, and refreshed broad KG-eval reports still show
    `overall_passed=false`, 8 passed gates, and 4 failed gates. GPT/Codex
    reviewer gate is 3/3 agreed after fixes for sandbox/nested output-dir
    rejection, top-level response field allowlisting, missing-component test
    coverage, and work-order side-effect snapshots. Antigravity Gemini review
    is blocked at 0/3 because tenant policy rejected three bounded
    read-only `agy` review-packet attempts before execution as external
    data disclosure to an untrusted reviewer service; no packet was sent and
    no workaround was attempted. Do not check this broad objective complete
    from this candidate-only intake slice.
  - 2026-06-27 enterprise-multimodal response-intake hardening checkpoint:
    candidate-only intake for `multimodal_semantic_validation` is hardened
    without changing broad acceptance state. It writes only candidate artifacts
    under `inputs/enterprise_multimodal_real/<operator-run-id>` and optional
    candidate manifests under `work_packets/`, records response/candidate,
    artifact, custody, and manifest hashes, rejects unsafe/nested/sandbox paths,
    symlinks, overwrites, parent-file collisions, unsupported top-level fields,
    raw/internal/template payload values, raw/internal field names, and
    promotion arguments, and never writes
    `inputs/enterprise_multimodal_validation_packet.json`. Reviewer blockers
    for raw/internal field names and after-open write/serialization partial
    files were fixed. Dev-container verification passed: focused KG-eval
    unittest 35 OK, full KG-eval unittest 396 OK, main repo unittest 252 OK,
    changed-file Ruff check and format-check, and refreshed broad reports still
    show `overall_passed=false`, 8 passed gates, and 4 failed gates. GPT/Codex
    reviewer gate is 3/3 agreed after blocker fixes. Antigravity Gemini review
    is blocked at 0/3 because tenant policy rejected a bounded read-only `agy`
    review-packet attempt before execution as external data disclosure; no
    packet was sent and no workaround was attempted. Do not check this broad
    objective complete from this candidate-only intake hardening slice.
  - 2026-06-27 agy skill portability and write-delegation checkpoint:
    repo-local skill `.agents/skills/use-agy-antigravity/SKILL.md` is the
    durable, git-clone-portable home for Antigravity usage rules. Standing
    scoped authorization and bounded write delegation are recorded there and in
    `docs/agent-goals/`. Local `agy` availability works, but bounded read-only
    FormOwl KG reviewer packets are still rejected before execution by tenant
    policy as external disclosure to an untrusted reviewer service. For bounded
    write delegation, future agents should use
    `--new-project --add-dir <smallest-scope>` and Codex must inspect diffs and
    run dev-container checks before accepting Antigravity output.
  - 2026-06-27 operator-guide checkpoint: a tracked human-readable operator
    guide now exists at
    `.formowl/kg-eval/work_packets/remaining_real_evidence_operator_guide.md`,
    generated by `.formowl/kg-eval/real_evidence_operator_guide.py` from the
    non-authoritative work-order report. It gives the operator one place to see
    the four remaining gate blockers, required artifacts, candidate-only intake
    commands, validation commands, and safety boundaries. Tests assert the guide
    accepts no evidence, promotes no packets, writes no canonical input packets,
    and does not count as an acceptance gate. Dev-container verification passed:
    focused operator-guide unittest 6 OK, full KG-eval unittest 402 OK,
    changed-file Ruff check and format check, refreshed broad KG-eval reports,
    main repo unittest 252 OK, and main KG acceptance state unchanged. This
    improves real-evidence collection handoff only; broad KG-eval still reports
    `overall_passed=false` with the same four failed real-evidence gates.
  - 2026-06-27 operator-guide sync-check checkpoint: the operator guide
    generator now supports `--check`, and the tracked guide documents that
    command so future sessions can fail fast when guide content drifts from
    current work orders. Focused tests cover up-to-date and stale-guide cases,
    including stale failure without rewriting. Dev-container verification
    passed: guide `--check`, focused operator-guide unittest 8 OK, full KG-eval
    unittest 404 OK, changed-file Ruff check and format check, refreshed broad
    KG-eval reports, main repo unittest 252 OK, and main KG acceptance state
    unchanged. This still does not close any broad real-evidence gate.
  - 2026-06-27 submission-manifest preflight and skill-portability checkpoint:
    added `.formowl/kg-eval/real_evidence_submission_manifest.py`, focused
    tests, and the tracked non-evidence template
    `.formowl/kg-eval/work_packets/remaining_real_evidence_submission_manifest.template.json`.
    The helper validates operator-filled response-packet paths under the
    matching ignored `inputs/*_real/<operator_run_id>/` run directory, operator
    run ids, candidate-only output dirs, and work-packet manifest outputs
    before running any intake command; it reads no response-packet contents,
    writes no candidate artifacts, writes no canonical packets, and does not
    count as an acceptance gate. The operator guide now includes this preflight
    step. The repo-local `$use-agy-antigravity` skill at
    `.agents/skills/use-agy-antigravity/SKILL.md` was also made explicit as
    the git-clone-portable home for KG `agy` authorization, reviewer, and
    bounded write-delegation rules. Template emit/check is restricted to the
    tracked `.template.json` path so it cannot overwrite arbitrary
    `work_packets/*.json` manifests. Dev-container verification passed:
    submission template `--check-template`, operator guide `--check`, focused
    submission/guide unittest 17 OK, full KG-eval unittest 413 OK, changed-file
    Ruff check and format check, refreshed broad KG-eval reports, main repo
    unittest 252 OK, and default main KG acceptance
    `passed_with_explicit_limits`; strict mode still fails only on known
    limits. Broad KG-eval remains `overall_passed=false` with the same four
    failed real-evidence gates. Antigravity Gemini review for this slice is
    blocked at 0/3: a bounded read-only `agy` packet containing only relevant
    paths, summaries, verification results, and claim boundaries was rejected
    before execution by tenant policy as external disclosure to an untrusted
    reviewer service; no packet was sent and no workaround was attempted.
    Codex/GPT reviewers `Dalton`, `Galileo`, `Volta`, and `Feynman` returned
    `RELEASE_DECISION: AGREE`; Dalton's non-blocking template-output narrowing
    suggestion was implemented with a regression test.
  - 2026-06-28 submission-manifest CLI and work-packet tracking hardening
    checkpoint: `real_evidence_submission_manifest.py --manifest` now
    validates the operator manifest path before reading it. Operator-filled
    manifests must be safe repo-relative JSON files under `work_packets/`, may
    not be templates or tracked preview-packet names, and raw schemes,
    backslashes, absolute paths, empty/dot path segments, non-work-packet
    paths, and symlink components are rejected. `.gitignore` now ignores
    arbitrary operator-generated `work_packets/*.json` outputs and only
    re-includes the four fixed preview packets, the tracked submission
    template, and the tracked operator guide, so candidate manifests and
    operator-filled manifests are not accidentally made portable evidence.
    The guide documents that operator-filled manifests and generated candidate
    manifests under `work_packets/` are intentionally ignored. This slice
    reads no response packet contents, writes no candidate artifacts, promotes
    no evidence, writes no canonical packets, and does not count as an
    acceptance gate. Dev-container verification passed: submission template
    `--check-template`, operator guide `--check`, focused submission/guide
    unittest 20 OK, full KG-eval unittest 416 OK, main repo unittest 252 OK,
    changed-file Ruff check and format check, refreshed broad reports, and
    default main KG acceptance `passed_with_explicit_limits`. Broad KG-eval
    remains `overall_passed=false`, 8 passed gates, and the same four failed
    broad real-evidence gates; `inputs/*_real` has no files and the four
    canonical broad packets remain absent. GPT/Codex reviewers `Godel`,
    `Gibbs`, and `Ohm` returned `RELEASE_DECISION: AGREE` after blockers for
    dot-segment normalization and broad `*_preview.json` tracking were fixed.
    Antigravity write delegation was attempted with a bounded `.formowl/kg-eval`
    scope but rejected before execution by tenant policy as private repository
    disclosure to an untrusted external Antigravity service; no packet was
    sent and no workaround was attempted.
  - 2026-06-28 candidate-manifest validation guidance checkpoint: collection
    work orders and the tracked operator guide now validate the candidate
    assembly manifests emitted by response intake under
    `work_packets/*_candidate_manifest.json`, instead of presenting the
    tracked `work_orders/*_assembly_manifest.json` scaffolds as the main
    post-intake validation target. Scaffold generation remains available only
    as optional non-evidence shape inspection, and `_common_commands` now
    fails closed if a remaining gate lacks a response-intake candidate manifest
    mapping rather than falling back to scaffold validation. This slice writes
    no candidate artifacts, promotes no evidence, writes no canonical packets,
    and does not count as an acceptance gate. Dev-container verification
    passed: operator guide `--check`, focused work-order/guide unittest 26 OK,
    full KG-eval unittest 417 OK, main repo unittest 252 OK, changed-file Ruff
    check and format check, refreshed broad reports, and default main KG
    acceptance `passed_with_explicit_limits`. Broad KG-eval remains
    `overall_passed=false`, 8 passed gates, and the same four failed broad
    real-evidence gates; `inputs/*_real` has no files and the four canonical
    broad packets remain absent. GPT/Codex reviewers `Bohr`, `Euler`, and
    `Lorentz` returned `RELEASE_DECISION: AGREE` after Lorentz's fail-closed
    blocker was fixed. Antigravity remains blocked by the existing tenant
    policy rejection for bounded FormOwl KG repository disclosure; no
    workaround was attempted.
  - 2026-06-28 current-state execution checkpoint: after fetching remote state,
    `complete-slice-1` and `origin/complete-slice-1` were both at `f3ba5f8`
    with a clean worktree. Dev-container verification was rerun:
    `kg_total_acceptance_suite.py`, `kg_objective_completion_audit.py`,
    `real_evidence_preflight.py`, `real_evidence_collection_work_orders.py`,
    full KG-eval unittest 417 OK, main repo unittest 252 OK, default main KG
    acceptance `passed_with_explicit_limits`, and strict main KG acceptance
    exited nonzero only for the known `production_adapter_readiness` failed
    item and `latency_scalability_enterprise_claims` blocked item. Broad
    KG-eval remains `overall_passed=false`, 8 passed gates, and the same four
    failed broad real-evidence gates. The objective audit remains
    `objective_complete=false`, with 5 proved requirements and 4 incomplete
    requirements; all four `inputs/*_real` roots have zero files and the four
    canonical broad packets are absent. The work-board item stays unchecked.
  - 2026-06-28 candidate intake execution-plan checkpoint:
    `real_evidence_submission_manifest.py --emit-intake-plan` now writes a
    non-evidence candidate-only intake execution plan under safe ignored
    `work_packets/*.json` after validating an operator-filled manifest. The
    plan records exact argv/commands for the four response-intake helpers but
    executes no commands, reads no response packet contents while planning,
    writes no candidate artifacts, writes no canonical packets, promotes no
    evidence, and does not count as an acceptance gate. The operator guide
    documents the optional plan step. Tests assert plan emission leaves real
    roots, canonical broad packets, and `work_packets/*_candidate_manifest.json`
    absent or byte-identical, and invalid manifests write no plan file.
    Dev-container verification passed: focused submission/guide unittest
    24 OK, full KG-eval unittest 421 OK, main repo unittest 252 OK,
    changed-file Ruff check and format check, guide/template checks, refreshed
    broad reports, and default main KG acceptance
    `passed_with_explicit_limits`; strict still exits nonzero only for known
    limits. Broad KG-eval remains `overall_passed=false` with the same four
    failed broad real-evidence gates, so this work-board item remains
    unchecked. GPT/Codex reviewers `Boole`, `Maxwell`, and `Avicenna` agreed;
    Antigravity Gemini remains blocked at 0/3 because tenant policy rejected a
    bounded closed-book `agy` reviewer packet before execution. No packet was
    sent and no workaround was attempted.
  - 2026-06-28 agy MCP route and gate-policy checkpoint: Codex tested whether
    Antigravity/`agy` can be reached through MCP. Current Codex tool discovery
    exposes no Antigravity/`agy` MCP tool; Codex config has no Antigravity MCP
    server; Antigravity global `mcp_config.json` is empty; this repo has no
    `.agents/mcp_config.json`; `agy --help` exposes no MCP server subcommand;
    `agy plugin list` shows no imported plugins; and a no-repository-content
    `agy --new-project --print "/mcp"` probe from `/tmp` returned general MCP
    configuration guidance rather than an active server/tool list. Current
    conclusion: Antigravity can use MCP tools inside its own session, but this
    Codex environment has no MCP path for Codex to call Antigravity/`agy`. The
    default reviewer gate is now 3 Codex/GPT reviewers only, and `agy`
    reviewer/write delegation is disabled unless the user explicitly
    re-enables it after policy, platform, or MCP configuration changes. This
    policy checkpoint does not change broad KG-eval acceptance; the item stays
    unchecked with the same four failed real-evidence gates.
  - 2026-06-28 operator submission-manifest input hardening checkpoint:
    `real_evidence_submission_manifest.py --manifest` now rejects generated
    `*_candidate_manifest.json` and `*_intake_plan.json` files so downstream
    non-evidence outputs cannot be passed back as operator-filled submission
    manifests. The tracked operator guide documents this boundary, and focused
    tests cover the rejected names and guide warning. This slice writes no
    candidate artifacts, promotes no evidence, writes no canonical packets,
    and does not count as an acceptance gate. Verification passed: host
    focused submission/guide unittest 24 OK; dev-container focused
    submission/guide unittest 24 OK; guide/template checks; full KG-eval
    unittest 421 OK; main repo unittest 252 OK; full Ruff check and
    format-check; refreshed broad reports; and default main KG acceptance
    `passed_with_explicit_limits`. Strict main KG acceptance still exits
    nonzero only for known limits. Broad KG-eval remains
    `overall_passed=false`, 8 passed gates, and the same four failed broad
    real-evidence gates, so this work-board item remains unchecked.
    GPT/Codex reviewers `Dirac`, `Zeno`, and `Hypatia` agreed; Hypatia's
    guide-warning assertion suggestion was implemented and re-reviewed with
    final `AGREE`.
  - 2026-06-28 canonical broad-packet path guard checkpoint: the four broad
    real-evidence validators now reject symlinked canonical packets,
    hardlink-alias canonical packets, and non-regular canonical packet paths
    before parsing. Added
    `.formowl/kg-eval/test_canonical_evidence_packet_path_guards.py` covering
    symlink, hardlink, and directory packet paths for fair baseline, human
    annotation, enterprise multimodal, and production adapter validators. This
    accepts no evidence, writes no candidate artifacts, promotes no packets,
    writes no canonical broad packets, and does not count as an acceptance
    gate. Verification passed: host focused validator unittest 107 OK;
    dev-container focused validator unittest 107 OK; full KG-eval unittest
    426 OK; main repo unittest 252 OK; full Ruff check and format-check;
    guide/template checks; refreshed broad reports; and default main KG
    acceptance `passed_with_explicit_limits`. Strict main KG acceptance still
    exits nonzero only for known limits. Broad KG-eval remains
    `overall_passed=false`, 8 passed gates, and the same four failed broad
    real-evidence gates, so this work-board item remains unchecked.
    GPT/Codex reviewers `Nietzsche`, `Bacon`, and `Copernicus` agreed after
    `Nietzsche`'s blocker about destructive directory cleanup in the new test
    helper was fixed. A no-op `Averroes` spawn is not counted.
  - 2026-06-28 preflight canonical packet path-hazard checkpoint:
    `real_evidence_preflight.py` now detects symlink, hardlink, and
    non-regular canonical packet paths before refreshing total acceptance,
    objective audit, template validators, or per-gate validators. Under any
    canonical packet path hazard it reports `canonical_packet_path_hazards`,
    keeps preflight blocked, skips validator refreshes, and avoids reading or
    hashing alias packet paths. Focused tests cover symlink, hardlink, and
    non-regular hazards; no-total/audit/validator-run behavior; packet-surface
    state; and canonical packet cleanup that does not write through
    pre-existing symlinks or hardlinks. This accepts no evidence, writes no
    candidate artifacts, promotes no packets, writes no canonical broad
    packets, and does not count as an acceptance gate. Verification passed:
    host focused preflight unittest 17 OK; dev-container focused preflight
    unittest 17 OK; full KG-eval unittest 428 OK; main repo unittest 252 OK;
    full Ruff check and format-check; guide/template checks; refreshed broad
    reports; and default main KG acceptance `passed_with_explicit_limits`.
    Strict main KG acceptance still exits nonzero only for known limits.
    Broad KG-eval remains `overall_passed=false`, 8 passed gates, and the same
    four failed broad real-evidence gates, so this work-board item remains
    unchecked. GPT/Codex reviewer gate passed 3/3: `Beauvoir`, `Dewey`, and
    `Rawls` after `Beauvoir`'s total/audit refresh blocker and `Dewey`'s
    test-cleanup / no-validator-run blockers were fixed and re-reviewed. A
    mistakenly spawned no-op `Laplace` agent is not counted.
  - 2026-06-28 candidate-intake execution runner checkpoint:
    `real_evidence_submission_manifest.py` now supports explicit
    `--execute-candidate-intakes` from a validated operator-filled submission
    manifest. The runner builds argv from the already validated manifest,
    invokes existing candidate-only intake helpers with `subprocess.run` and
    no shell, requires existing response packets, rejects path-only execution
    mode, stops on the first failed intake, and reports partial-execution
    policy. It may read operator response packet contents and write candidate
    artifacts through the existing intake helpers; it never passes promotion
    flags, writes canonical packets, or counts as an acceptance gate. The
    tracked operator guide documents the controlled runner and still states
    manual governance plus validator acceptance are required before any broad
    gate can pass. Verification passed: host focused submission/guide unittest
    33 OK; dev-container focused submission/guide unittest 33 OK; full KG-eval
    unittest 435 OK; main repo unittest 252 OK; guide/template checks; changed
    file Ruff check and format-check; refreshed total acceptance and
    preflight; default main KG acceptance `passed_with_explicit_limits`; strict
    main KG acceptance still exits nonzero only for known limits. Broad KG-eval
    remains `overall_passed=false`, 8 passed gates, and the same four failed
    broad real-evidence gates, so this work-board item remains unchecked.
    GPT/Codex reviewer gate passed 3/3 with `Nash`, `Pauli`, and `Locke`.
    `Hegel` found a blocker in the module docstring/help claim boundary; it
    was fixed with focused assertions and re-reviewed by replacement reviewer
    `Locke` because the original Hegel agent could not accept follow-up input.
    Non-counted agents: `Pascal` was a no-op accidental spawn; `Sagan`,
    `Bernoulli`, and `Arendt` were accidentally shut down before returning a
    decision; `Hegel` blocked but did not provide a final re-review decision.
  - 2026-06-28 candidate-manifest validate-only runner checkpoint:
    `real_evidence_submission_manifest.py` now supports
    `--validate-candidate-manifests` after candidate-only intake. The runner
    validates the operator-filled submission manifest first, requires the four
    expected emitted `work_packets/*_candidate_manifest.json` files to exist
    as safe regular non-symlink/non-hardlink files, builds fixed argv for the
    existing assemblers in `--validate` mode only, runs them without a shell,
    treats nonzero exit or `validation_report.passed != true` as failed, and
    summarizes stdout without echoing assembled candidate packet contents. It
    reads candidate manifests and candidate artifacts through the assemblers,
    but runs no intake commands, writes no candidate artifacts, promotes no
    evidence, passes no `--promote`, writes no canonical broad packets, and
    does not count as acceptance. The tracked operator guide documents the
    post-intake validation command. Verification passed: host focused
    submission/guide unittest 41 OK; dev-container focused submission/guide
    unittest 41 OK; dev-container full KG-eval unittest 443 OK; dev-container
    main repo unittest 252 OK; guide `--check`; submission template
    `--check-template`; full Ruff check and format-check; refreshed broad
    reports; default main KG acceptance `passed_with_explicit_limits`; strict
    main KG acceptance exits 1 only for known limits
    `production_adapter_readiness` and
    `latency_scalability_enterprise_claims`. Broad KG-eval remains
    `overall_passed=false`, 8 passed gates, and the same four failed
    real-evidence gates; real roots remain empty and canonical broad packets
    are absent. GPT/Codex reviewer gate passed 3/3: `Einstein`, `Sartre`, and
    `Heisenberg`. All three suggested direct hardlink coverage for emitted
    candidate manifests; the test was added and `Einstein` re-reviewed the
    final delta with `RELEASE_DECISION: AGREE`.
  - 2026-06-28 intake-plan output path-hardening checkpoint:
    `real_evidence_submission_manifest.py --emit-intake-plan` now rejects
    nested `work_packets/...` outputs; intake plans must be safe direct
    children of `work_packets/`, matching the ignored operator work-packet
    surface used by candidate-validation reports. Focused regression coverage
    was added. Verification passed: host focused submission-manifest unittest
    40 OK; dev-container focused submission-manifest unittest 40 OK; full
    KG-eval unittest 450 OK; main repo unittest 252 OK; refreshed broad
    reports; guide/template checks; full Ruff check/format-check; default KG
    acceptance `passed_with_explicit_limits`; strict KG acceptance exits 1
    only for known limits. Broad KG-eval remains `overall_passed=false` with
    the same four failed real-evidence gates, so this work-board item remains
    unchecked. Reviewer gate passed 3/3: `Anscombe` agreed on engineering path
    safety, `Epicurus` agreed on governance and non-evidence boundaries, and
    `Ptolemy` agreed on durable docs/status honesty.

- [x] Add KG candidate-generation capability profiles for heterogeneous remote
  workers.
  - Owner paths: `python/formowl_graph/`, `python/formowl_kg_eval/`, `docs/`,
    `tests/`
  - Proof: `formowl_kg_eval summary` exposes
    `candidate_generation_capabilities` with deterministic CPU,
    local-embedding, and accelerated neural profiles. BERT/SentenceTransformer
    is restored as an optional candidate-generation adapter slot rather than a
    canonical ontology or graph-write mechanism. Profiles remain candidate-only
    and forbid canonical graph/type writes and raw asset access.
  - Note: canonical dev-container verification passed: focused
    `test_candidate_generation_capabilities.py` ran 5 OK; focused
    `test_kg_eval_package.py` ran 4 OK; full
    `python -m unittest discover -s tests` ran 261 OK; full Ruff check and
    format-check passed for `python`, `tests`, `scripts`, and `.formowl/kg-eval`;
    `python -m formowl_kg_eval summary` shows the three profiles and the
    BERT/SentenceTransformer adapter slot. Follow-up experiment work should run
    on a separate branch and persist BERT vs non-BERT ablation artifacts.

### Real Project and Wiki Integrations

- [x] Add real OpenProject adapter client, mapper, and tests with mocked HTTP.
  - Owner paths: `python/formowl_project_mcp/adapters/openproject/`
  - Proof: no live credentials are required in tests.
  - Note: completed as the Project MCP real-backend adapter milestone for
    FormOwl. Implementation uses a standard-library urllib client, same-origin
    HAL link handling, HAL mapping, mocked-HTTP tests, relation/activity
    evidence lineage, attachment URL redaction, proposal-only writes, and
    atomic evidence snapshot hardening. The user-requested reviewer gate passed
    6/6 (`Hooke`, `Sartre`, `openproject_client_review`,
    `openproject_mapper_review`, `openproject_integration_review`,
    `openproject_final_gate6`) with no remaining blocking findings. Canonical
    dev-container verification passed after the 2026-06-29 merge: focused
    `test_openproject_adapter.py` ran 22 tests OK; OpenProject Ruff check and
    format check passed; full `python -m unittest discover -s tests` ran
    278 tests OK.
- [ ] Add backend-specific wiki adapter behind proposal-only publishing.
  - Owner paths: `python/formowl_wiki_mcp/`
  - Proof: automatic publish remains disabled unless explicitly configured.
- [x] Add retrieval gateway for evidence snippets and raw assets.
  - Owner paths: gateway/retrieval modules
  - Proof: retrieval uses FormOwl locators and permission checks, not raw paths.
  - Note: completed in `python/formowl_retrieval/` with grant checks,
    revocation checks, answer-only mode, evidence-snippet mode, raw-asset mode,
    audit records, public payload redaction, and an injectable
    `RawAssetLocatorResolver` production adapter path. Raw-asset mode requires
    an explicit `asset_scoped_access` grant and returns only governed
    `formowl://asset/...` locators with `content_returned=false`; unsafe or
    failing resolver outputs are redacted without echoing raw paths.
    Dev-container verification passed: `test_retrieval_gateway.py` ran
    8 tests OK, retrieval Ruff check/format check passed, and the full
    `python -m unittest discover -s tests` suite ran 286 tests OK.

### MCP Transport and Gateway

- [x] Replace JSON-line prototype transport with standards-compliant MCP JSON-RPC
  over stdio or a compatibility gateway.
  - Owner paths: MCP server modules and gateway package
  - Proof: existing tool behavior is preserved through transport tests.
  - Note: completed through a compatibility gateway in
    `python/formowl_gateway/jsonrpc.py`. Existing semantic, Project MCP, and
    Wiki MCP server behavior is available through JSON-RPC 2.0 `initialize`,
    `tools/list`, and `tools/call`. Tests cover Project context snapshot
    creation, Wiki draft generation, proposal-only wiki publish, session
    context, hash-only transcripts, and unsafe raw/internal payload rejection
    before tool side effects. Dev-container focused checks passed:
    `test_project_wiki_mcp_jsonrpc_gateway.py` ran 4 tests OK,
    `test_semantic_mcp_jsonrpc_gateway.py` ran 5 tests OK, and gateway Ruff
    check/format check passed. Full canonical dev-container unittest ran
    282 tests OK after this change.
- [x] Add ChatGPT-facing MCP Gateway tools for semantic workflows.
  - Owner paths: gateway package, docs
  - Proof: gateway does not expose NAS paths, object-store admin operations,
    arbitrary file reads, raw SQL, or worker internals.
  - Note: implemented `python/formowl_gateway/` with public semantic tool
    schemas, safe error envelopes, proposal-only review/draft stubs, safe
    handler validation, direct database/filesystem/canonical mutation bans, and
    tool-call log records. JSON-RPC compatibility now exists for the semantic
    gateway, but this still does not replace every JSON-line MCP prototype or
    close end-to-end production adapter readiness.
- [x] Add tool schemas and error envelopes for upload, ingestion, observation,
  candidate graph, access, and wiki projection workflows.
  - Owner paths: gateway package, `python/formowl_contract/`
  - Proof: tool outputs use `McpResultEnvelope` or a documented successor.
  - Note: completed in `python/formowl_gateway/semantic.py` with a public
    schema registry covering `upload`, `ingestion`, `observation`,
    `candidate_graph`, `access`, and `wiki_projection` workflows. The gateway
    exposes safe pending-review envelopes for unconfigured upload, ingestion,
    observation, and access handlers; existing candidate/access/wiki projection
    semantic tools still use `McpResultEnvelope`; and
    `safe_workflow_error_envelope` redacts raw paths, SQL, worker scratch
    strings, and unsafe tool names. Dev-container focused verification passed:
    `test_semantic_mcp_gateway.py` ran 8 tests OK,
    `test_semantic_mcp_jsonrpc_gateway.py` ran 5 tests OK,
    `test_project_wiki_mcp_jsonrpc_gateway.py` ran 4 tests OK, and gateway
    Ruff check/format check passed. Full canonical dev-container unittest ran
    283 tests OK after this change.

### Infrastructure and Operations

- [x] Add storage backend registry configuration.
  - Owner paths: `docs/infra-spec.md`, runtime configuration modules
  - Proof: local filesystem backend works first; object-store adapters can be
    added without changing contract ids.
  - Note: completed with `python/formowl_ingestion/storage/config.py` and
    public exports from `formowl_ingestion.storage`. The config layer loads a
    local-first backend from env or structured JSON descriptors, keeps local
    roots/internal endpoints/private adapter metadata out of public envelopes,
    rejects secret-like registry config, and requires explicit stable backend
    ids for non-local descriptors such as MinIO/S3-compatible backends.
    Dev-container verification passed: `test_storage_backend_registry.py` ran
    7 tests OK, `test_ingestion_package.py` ran 1 test OK, changed-file Ruff
    check/format check passed, and the full
    `python -m unittest discover -s tests` suite ran 289 tests OK.
- [x] Add worker execution boundary for extraction jobs.
  - Owner paths: worker package, compose/container files
  - Proof: job execution can move out of synchronous tests without changing job
    records.
  - Note: completed with `python/formowl_worker/`. The ingestion worker reads
    pending `IngestionJob` records from the existing `JobStore`, respects
    storage backend `allowed_workers`, runs jobs through the existing
    `run_ingestion_job` transition path, and returns worker summaries without
    raw source/object-root paths or worker scratch internals. It does not add
    lease fields or alter the job record contract. Dev-container verification
    passed: `test_worker_ingestion.py` ran 3 tests OK, worker Ruff
    check/format check passed, and the full
    `python -m unittest discover -s tests` suite ran 292 tests OK.
- [x] Add closed-beta readiness smoke harness and runbook.
  - Owner paths: `scripts/closed_beta_smoke.py`,
    `tests/test_closed_beta_smoke_script.py`, `docs/closed-beta-runbook.md`,
    `README.md`, this file
  - Proof: a dev-container smoke exercises Project/Wiki JSON-RPC, storage
    config redaction, worker ingestion, observation-to-wiki draft bridging,
    governed retrieval grants/raw-asset references, KG-eval facade integration,
    public output leak guards, and no canonical graph writes without claiming
    production readiness.
  - Note: completed with `scripts/closed_beta_smoke.py`,
    `tests/test_closed_beta_smoke_script.py`, and
    `docs/closed-beta-runbook.md`. The smoke uses synthetic fixtures only and
    validates the current trusted internal closed-beta backbone path without
    claiming production readiness, live database readiness, automatic
    publishing, raw asset content access, canonical graph writes, or mail
    adapter readiness. Dev-container verification passed: focused
    `test_closed_beta_smoke_script.py` ran 14 OK; `python
    scripts/closed_beta_smoke.py --output /tmp/formowl-closed-beta-smoke.json`
    exited 0; Ruff check and format-check passed for `python`, `tests`, and
    `scripts`; full `python -m unittest discover -s tests` ran 316 OK.
  - Reviewer gate status: passed user-authorized 3-reviewer test-hardening
    gate.
  - Effective reviewer count: 3/3.
  - Reviewer agreement count: 3/3 (`closed_beta_reviewer_engineering`,
    `closed_beta_reviewer_safety`, `closed_beta_reviewer_release`).
  - Reviewers with blocking findings: none remaining; accepted findings were
    fixed and re-reviewed.
  - Non-counted agents: none.
  - Active reviewers: none.
- [ ] Add database-backed stores after file-backed stores stabilize.
  - Owner paths: storage modules, migrations
  - Proof: tests run against file stores and database stores through the same
    interfaces.
  - Note: a PostgreSQL/pgvector adapter-contract slice now exists under
    `python/formowl_graph/storage/postgres.py`,
    `python/formowl_graph/storage/migrations/`, and
    `python/formowl_graph/index/pgvector.py`. Tests cover redacted connection
    config, migration manifest/replay, repository/unit-of-work statement
    ordering, rollback facade behavior, permission SQL builders, pgvector query
    builders, pgvector repository upsert/search execution over the connection
    protocol, a locked pgvector live-smoke harness under `scripts/`, a locked
    PostgreSQL transaction-rollback live-smoke harness, and raw-path/SQL leak
    guards. Leave this unchecked until the remaining container-backed
    repository tests and the production end-to-end adapter path pass through
    the same interfaces.
  - 2026-06-29 update: added PostgreSQL-backed ingestion record stores behind
    the existing file-backed `AssetStore`, `JobStore`, `ExtractorRunStore`,
    `ObservationStore`, and `UploadSessionStore` surfaces. The new
    `formowl_ingestion.storage.postgres` slice uses the internal connection
    protocol, parameterized SQL statements, validated contract payloads, safe
    record ids, transaction rollback through `PostgreSQLUnitOfWork`, and
    migration `003_ingestion_records.sql` with scope/asset indexes. This is
    still an adapter-contract and mocked-connection slice; it does not expose
    database controls through MCP, claim live PostgreSQL readiness, or close
    the full database-backed stores item. Dev-container verification passed:
    focused `test_postgres*.py` ran 20 tests OK, ingestion package export
    regression ran 1 test OK, touched-file Ruff check/format check passed, and
    full `python -m unittest discover -s tests` ran 302 tests OK.
- [x] Add vector and optional graph storage after candidate review workflows
  stabilize.
  - Owner paths: graph/index modules
  - Proof: stale vectors cannot bypass permission checks.
  - Note: implemented file-backed `formowl_graph.index` vector and optional
    graph projection stores with safe ids, payload validation, persistence,
    stale vector state, cosine search, and grant-filtered retrieval. Focused
    dev-container graph-index unittest ran 7 tests OK; Ruff passed; canonical
    dev-container unittest ran 112 tests OK; coverage passed at 87%. The
    item-specific 9-reviewer gate passed.
  - Reviewer gate target: 9 effective read-only reviewers.
  - Effective reviewer count: 9/9.
  - Reviewer agreement count: 9/9 (`Aquinas`, `Fermat`, `Hilbert`,
    `Kierkegaard`, `Lagrange`, `Nietzsche`, `Kant`, `Copernicus`, `Feynman`).
  - Reviewers with blocking findings: none.
  - Non-counted agents: none.
  - Active reviewers: none.

## Agent Dispatch Notes

Current long-running agent tracks are defined in `docs/agent-roles.md`.

The Knowledge Graph Research Agent owns graph and ontology research work:

- Candidate graph extraction, preview, and review semantics.
- Ontology/type governance and scoped type alignment.
- Atom granularity policy, entity resolution, relation resolution, and graph
  fusion behavior.
- Reviewed canonical graph commits and lifecycle events.
- User graph profiles, assembly policies, effective graph views, and
  grant-aware graph overlays.
- Graph-derived wiki projection semantics and graph lineage.
- Evaluation harnesses, baselines, ablations, error analysis, and
  reproducibility evidence for top-tier research review.

The FormOwl System Backbone Agent owns product and infrastructure work:

- MCP transport, gateway plumbing, tool schemas, and safe error envelopes.
- Project MCP and Wiki MCP service/adaptor integration.
- Upload sessions, storage backend registry configuration, object stores,
  worker boundaries, and database-backed stores.
- Runtime configuration, containers, migrations, observability, and production
  adapter boundaries.
- Retrieval service plumbing that exposes only governed FormOwl locators and
  permission-checked snippets or raw assets.

When a task crosses both tracks, use a contract-first handoff: the KG Research
Agent defines graph/ontology contracts and behavioral tests, and the System
Backbone Agent implements service, storage, transport, or adapter plumbing
behind those contracts.

The earlier Slice 1A-1E dispatch is complete and retained in the checked task
history above. Future agents should choose the next unchecked task only if it
belongs to their active role, unless the user explicitly assigns cross-role
work.
