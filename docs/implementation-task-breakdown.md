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
- [ ] Implement a file-backed `StorageBackendRegistry`.
  - Owner paths: `python/formowl_ingestion/storage/`
  - Proof: tests can register and resolve a local backend without exposing raw
    paths through MCP envelopes.
- [ ] Implement a file-backed `ObjectStore` for copied local bytes.
  - Owner paths: `python/formowl_ingestion/storage/`
  - Proof: content hash verification passes and stored objects use FormOwl
    locators.
- [ ] Implement `AssetStore`, `JobStore`, `ExtractorRunStore`, and
  `ObservationStore`.
  - Owner paths: `python/formowl_ingestion/storage/`
  - Proof: create/get/list tests cover persisted JSON records.

### Slice 1C: Deterministic Text Extractor

- [ ] Define an `ExtractorAdapter` protocol and extraction input/result objects.
  - Owner paths: `python/formowl_ingestion/extraction.py`
  - Proof: a simple adapter can declare name, version, supported MIME types, and
    extractor type.
- [ ] Implement a deterministic plain-text/markdown observation extractor.
  - Owner paths: `python/formowl_ingestion/extractors/`
  - Proof: a `.txt` or `.md` asset produces observations with line-range
    locators, source refs, extractor run id, and confidence.
- [ ] Keep semantic metadata extraction separate from deterministic observation
  extraction.
  - Owner paths: `python/formowl_ingestion/extractors/`
  - Proof: text extraction does not create candidate atoms or canonical graph
    records.
- [ ] Add re-extraction behavior that creates a new `ExtractorRun`.
  - Owner paths: `python/formowl_ingestion/extraction.py`,
    `python/formowl_ingestion/storage/`
  - Proof: rerunning the same extractor preserves the old run and writes a new
    run record when config or version changes.

### Slice 1D: Minimal Ingestion Workflow

- [ ] Implement `register_asset_from_local_file()` for trusted internal tests.
  - Owner paths: `python/formowl_ingestion/assets.py`
  - Proof: asset registration records technical metadata, hash, source ref,
    permission scope, and a FormOwl locator.
- [ ] Implement `create_ingestion_job()` and `run_ingestion_job()` for local
  deterministic extractors.
  - Owner paths: `python/formowl_ingestion/jobs.py`
  - Proof: job status moves through pending/running/succeeded/failed and links
    to extractor runs and observations.
- [ ] Add an integration test for Asset -> Job -> Run -> Observation.
  - Owner paths: `tests/test_ingestion_workflow.py`
  - Proof: end-to-end test passes and records remain queryable after process
    restart.
- [ ] Document the small core workflow.
  - Owner paths: `docs/workflows.md`, this file
  - Proof: docs mention the local deterministic ingestion path and any
    intentional limitations.

### Slice 1E: Observation to Wiki Draft Bridge

- [ ] Add a narrow helper that builds a `ContextPackage` from selected text
  observations.
  - Owner paths: `python/formowl_ingestion/observations.py`,
    `python/formowl_contract/`
  - Proof: the context package includes source refs, asset ids, extractor run
    ids, observation ids, citations, and permission scope.
- [ ] Add an integration test for text asset -> observations -> context package
  -> existing Wiki MCP draft.
  - Owner paths: `tests/test_ingestion_to_wiki_workflow.py`
  - Proof: generated markdown includes the source title/content, citation
    lineage, and evidence/observation references without reading raw paths.
- [ ] Keep this bridge reviewable and non-canonical.
  - Owner paths: `python/formowl_ingestion/`, `python/formowl_wiki_mcp/`
  - Proof: the bridge does not create `CandidateAtom`, `CanonicalAtom`,
    `WikiRevision`, or graph commit records.

## Parallel Work After Small Core

These groups can be split across multiple agents after Slice 1 is stable.

### Identity, Access, and Audit

- [ ] Add contract models for `User`, `SessionIdentity`, `WorkspaceMember`,
  `AccessRequest`, `Grant`, and `AuditLog`.
  - Owner paths: `python/formowl_contract/`, `tests/test_identity_contract.py`
  - Proof: validation and serialization tests pass.
- [ ] Implement `ManualTrustedInternalAuthProvider`.
  - Owner paths: `python/formowl_gateway/` or `python/formowl_auth/`
  - Proof: `select_actor` and `whoami` style calls produce actor context without
    claiming production authentication.
- [ ] Add audit logging for actor selection, asset registration, ingestion job
  creation, evidence fetches, and permission denials.
  - Owner paths: shared observability/auth modules
  - Proof: tests assert audit records contain actor, workspace, action, target,
    status, and timestamp.

### Upload Session and ChatGPT Session Capture

- [ ] Add `UploadSession` contract and store.
  - Owner paths: `python/formowl_contract/`, `python/formowl_ingestion/`
  - Proof: normal uploads cannot skip intent, actor, permission scope, and audit.
- [ ] Add a controlled `upload_asset_reference` backend path.
  - Owner paths: `python/formowl_ingestion/`
  - Proof: trusted imports still create asset, permission, and audit records.
- [ ] Add `capture_current_chatgpt_session` data model and workflow.
  - Owner paths: `python/formowl_ingestion/`, docs
  - Proof: captured sessions become assets and ingestion jobs, not untracked
    local exports.

### Real Extractor Adapters

- [ ] Add technical metadata extractor adapters.
  - Owner paths: `python/formowl_ingestion/extractors/metadata/`
  - Proof: file size, MIME type, hash, and optional ExifTool/MediaInfo metadata
    are captured as observations or asset metadata.
- [ ] Add document parsing adapters.
  - Owner paths: `python/formowl_ingestion/extractors/document/`
  - Proof: PDF/doc-like test fixtures create paragraph/table observations with
    page or block locators.
- [ ] Add OCR adapters.
  - Owner paths: `python/formowl_ingestion/extractors/ocr/`
  - Proof: image/PDF fixtures create text observations with page/image locators.
- [ ] Add audio transcription adapters.
  - Owner paths: `python/formowl_ingestion/extractors/audio/`
  - Proof: audio fixtures create transcript observations with time locators.
- [ ] Add video scene and keyframe adapters.
  - Owner paths: `python/formowl_ingestion/extractors/video/`
  - Proof: video fixtures create scene/keyframe observations with time ranges.
- [ ] Add mail/archive ingestion adapters.
  - Owner paths: `python/formowl_ingestion/extractors/mail/`
  - Proof: messages, attachments, occurrences, and archive identity remain
    distinct assets or observations.

### Semantic Metadata and Candidate Graph

- [ ] Add contract models for `CandidateAtom`, `CandidateRelation`, and
  `ExternalGraphImport`.
  - Owner paths: `python/formowl_contract/`, tests
  - Proof: candidate records preserve source observation ids and extractor run
    provenance.
- [ ] Implement `SemanticMetadataStore`, `CandidateAtomStore`, and
  `CandidateRelationStore`.
  - Owner paths: `python/formowl_graph/storage/` or
    `python/formowl_ingestion/storage/`
  - Proof: stores do not write canonical graph state.
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
- [ ] Add vector and optional graph storage after candidate review workflows
  stabilize.
  - Owner paths: graph/index modules
  - Proof: stale vectors cannot bypass permission checks.

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
