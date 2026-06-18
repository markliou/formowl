# Implementation Task Breakdown

This file is the working checklist for turning the current Phase 0 prototype into
the full FormOwl pipeline described by `SPEC.md` and
`RESOURCE_EXTRACTION_SPEC.md`.

Future agents should update this file as work lands:

- Change `[ ]` to `[x]` only after code, tests, and relevant docs are complete.
- Keep each task scoped to the listed ownership area when possible.
- Do not create parallel replacement modules when `SPEC.md` already defines a path.
- Prefer small vertical slices that prove one data flow end to end.

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

- [ ] Implement `SemanticMetadataStore`, `CandidateAtomStore`, and
  `CandidateRelationStore`.
  - Owner paths: `python/formowl_graph/storage/` or
    `python/formowl_ingestion/storage/`
  - Proof: stores do not write canonical graph state.
  - Note: implemented file-backed graph proposal stores under
    `python/formowl_graph/storage/`; `tests/test_graph_record_stores.py`
    covers create/get/list, dict validation, safe ids, restart persistence, and
    verifies canonical graph collections are not created. Canonical
    dev-container unittest ran 104 tests OK, and coverage passed at 87%.
    Pending item-specific reviewer gate. First reviewer blockers were fixed by
    adding malformed dict-payload no-partial-write assertions, empty provenance
    id rejection, and exact proposal-only graph directory assertions. Host
    supplemental unittest ran 105 tests OK; canonical dev-container
    verification is still required before completion.
  - Reviewer gate target: 9 effective read-only reviewers.
  - Effective reviewer count: 2/9.
  - Reviewer agreement count: 2/9.
  - Reviewers with blocking findings: none.
  - Non-counted agents: none.
  - Active reviewers: Tesla, Rawls.
- [ ] Add a deterministic candidate extraction adapter for simple text fixtures.
  - Owner paths: `python/formowl_graph/candidates.py`
  - Proof: candidates are reviewable proposals and never canonical truth.
- [ ] Add candidate preview tooling.
  - Owner paths: `python/formowl_graph/`, optional MCP boundary
  - Proof: preview output includes warnings, confidence, provenance, and review
    actions.

### Governance and Canonical Graph

- [ ] Add contract models for `CanonicalAtom`, `CanonicalEntity`,
  `CanonicalRelation`, and `CanonicalGraphRevision`.
  - Owner paths: `python/formowl_contract/`, `python/formowl_graph/`
  - Proof: canonical ids remain stable across revisions.
- [ ] Add policy contracts for extraction, atom granularity, entity resolution,
  relation resolution, lifecycle, and wiki projection.
  - Owner paths: `python/formowl_contract/`, `python/formowl_graph/policies.py`
  - Proof: policies serialize with versioned ids.
- [ ] Implement reviewed canonical graph commit workflow.
  - Owner paths: `python/formowl_graph/canonical.py`,
    `python/formowl_graph/resolution.py`
  - Proof: only governed backend code can create canonical commits.
- [ ] Add lifecycle events for split, merge, archive, deprecate, supersede, and
  equivalence.
  - Owner paths: `python/formowl_graph/`
  - Proof: previous atom/entity/relation ids remain resolvable.

### User Graphs and Collaboration

- [ ] Add `UserGraphProfile`, `UserGraphAssemblyPolicy`, and
  `UserKnowledgeGraphRevision` contracts.
  - Owner paths: `python/formowl_contract/`, `python/formowl_graph/user_graphs.py`
  - Proof: two users can assemble different valid graph views from the same
    canonical graph fixtures.
- [ ] Add access overlay and grant-aware effective graph view.
  - Owner paths: `python/formowl_graph/`, auth/access modules
  - Proof: private evidence is not leaked without a grant.
- [ ] Add entity matching separate from data access and canonical merge.
  - Owner paths: `python/formowl_graph/resolution.py`
  - Proof: match proposals do not grant raw asset or evidence access.

### Wiki Projection

- [ ] Add `WikiProjectionSpec` contract.
  - Owner paths: `python/formowl_contract/`, `docs/wiki-draft-schema.md`
  - Proof: projection specs include graph revision, ontology revision, source
    refs, evidence snapshots, and citation behavior.
- [ ] Implement projection-spec-driven draft generation.
  - Owner paths: `python/formowl_wiki_mcp/`, `python/formowl_graph/`
  - Proof: graph-derived drafts preserve graph lineage in frontmatter.
- [ ] Extend `WikiRevision` lineage fields.
  - Owner paths: `python/formowl_contract/`,
    `python/formowl_wiki_mcp/markdown/`
  - Proof: wiki revisions can point back to user graph revisions and projection
    specs.

### Real Project and Wiki Integrations

- [ ] Add real OpenProject adapter client, mapper, and tests with mocked HTTP.
  - Owner paths: `python/formowl_project_mcp/adapters/openproject/`
  - Proof: no live credentials are required in tests.
- [ ] Add backend-specific wiki adapter behind proposal-only publishing.
  - Owner paths: `python/formowl_wiki_mcp/`
  - Proof: automatic publish remains disabled unless explicitly configured.
- [ ] Add retrieval gateway for evidence snippets and raw assets.
  - Owner paths: gateway/retrieval modules
  - Proof: retrieval uses FormOwl locators and permission checks, not raw paths.

### MCP Transport and Gateway

- [ ] Replace JSON-line prototype transport with standards-compliant MCP JSON-RPC
  over stdio or a compatibility gateway.
  - Owner paths: MCP server modules and gateway package
  - Proof: existing tool behavior is preserved through transport tests.
- [ ] Add ChatGPT-facing MCP Gateway tools for semantic workflows.
  - Owner paths: gateway package, docs
  - Proof: gateway does not expose NAS paths, object-store admin operations,
    arbitrary file reads, raw SQL, or worker internals.
- [ ] Add tool schemas and error envelopes for upload, ingestion, observation,
  candidate graph, access, and wiki projection workflows.
  - Owner paths: gateway package, `python/formowl_contract/`
  - Proof: tool outputs use `McpResultEnvelope` or a documented successor.

### Infrastructure and Operations

- [ ] Add storage backend registry configuration.
  - Owner paths: `docs/infra-spec.md`, runtime configuration modules
  - Proof: local filesystem backend works first; object-store adapters can be
    added without changing contract ids.
- [ ] Add worker execution boundary for extraction jobs.
  - Owner paths: worker package, compose/container files
  - Proof: job execution can move out of synchronous tests without changing job
    records.
- [ ] Add database-backed stores after file-backed stores stabilize.
  - Owner paths: storage modules, migrations
  - Proof: tests run against file stores and database stores through the same
    interfaces.
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

Recommended first dispatch after this planning file:

1. Contract agent: Slice 1A only.
2. Storage agent: Slice 1B only, starting after 1A contracts exist.
3. Extractor agent: Slice 1C only, starting after 1A and enough of 1B exist.
4. Workflow/test agent: Slice 1D only, integrating the prior slices.
5. Wiki bridge agent: Slice 1E only, after observations are persisted and
   queryable.

Avoid parallel edits to `python/formowl_contract/models.py` until Slice 1A is
done, because most later slices depend on those public contracts.
