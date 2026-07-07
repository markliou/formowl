# formowl

<!-- Future agents: read AGENTS.md first, then use docs/implementation-task-breakdown.md as the shared checklist. Continue building from the SPEC.md Suggested Repository Layout section and do not create parallel replacement files unless the specification is updated first. -->

formowl is a source-preserving, graph-governed knowledge management system. Its target architecture turns multimodal resources, project execution data, conversations, and wiki/documentation systems into governed knowledge views.

Target pipeline:

```text
Raw Resources
  -> Resource Extraction
  -> Observation / Semantic Metadata
  -> Candidate Graph
  -> Governed Canonical Knowledge Graph
  -> User Knowledge Graph
  -> Wiki Projection / WikiRevision
```

The current repository starts with two decoupled MCP servers:

- Project MCP
- Wiki MCP

Project MCP retrieves project execution context from systems such as OpenProject.

Wiki MCP generates and manages markdown/wiki knowledge artifacts.

Both MCPs interoperate through `formowl_contract`. They are the first concrete entrypoints for source retrieval, evidence preservation, draft generation, and revision governance; they are not the full product boundary.

Future pipeline layers add asset ingestion, observation extraction, candidate graph review, canonical graph commits, user graph assembly policies, and projection-spec-driven wiki generation.

FormOwl is container-first. Development, testing, and deployment should run from Dockerfile-managed containers so the project does not depend on host-installed runtimes.

The Phase 0 implementation language is Python. Python is the readable orchestration, debugging, hashing, diffing, validation-glue, and service layer.

Core helper functionality is exposed through the pure-Python `formowl_core` API.

## Current Implementation

- Python contract models for source references, permission scopes, evidence snapshots, context packages, wiki revisions, and MCP result envelopes.
- Phase 0 identity, access request, grant, audit log, and upload session contract models.
- Manual trusted internal actor selection for Phase 0 tests; this is not production authentication.
- File-backed audit logs for actor selection, asset registration, ingestion job creation, evidence fetches, permission denials, and upload session creation.
- Controlled `upload_asset_reference` imports for trusted backend references that still create asset, permission, and audit records.
- ChatGPT session capture helper that turns the current conversation into a registered asset and ingestion job.
- Trusted local data resource inbox scanning for internal deployments. Stable
  files can become normal `Asset` and `IngestionJob` records, and configured
  `.txt` / `.md` inputs can run through the deterministic text extractor to
  produce `ExtractorRun` and `Observation` records without exposing local
  folder paths in the public scan report.
- Deterministic file technical metadata extractor for file size, MIME type, content hash, and FormOwl object locator observations.
- Deterministic fixture adapters for document structure, OCR text, audio transcripts, video scene/keyframe observations, and mail/archive observations.
- Official Mail Evidence Adapter boundary documented in
  `RESOURCE_EXTRACTION_SPEC.md` and `docs/workflows.md`: mail parsing starts
  from registered `Asset` / `IngestionJob` records, writes versioned
  `ExtractorRun` / `Observation` outputs, preserves occurrence identity, and
  does not create candidate graph, canonical graph, wiki, or case-progress QA
  outputs as a parsing side effect.
- Synthetic `formowl-mail` workflow helpers in `formowl_mail`: JSON-backed mail
  fixtures now emit thread, header, message, body, attachment, folder,
  fingerprint, and occurrence observations; local mail evidence packs provide a
  deterministic search index; mail evidence can become reviewable semantic
  metadata and candidate graph proposals; case-progress answers cite mail
  observations; and a preflight artifact marks synthetic readiness while
  deferring production PST/OST/MSG/EML parser readiness.
- Current #21 mail milestone direction: Phase 1 requires ordinary users to be
  able to upload a full PST through a session-bound FormOwl upload surface /
  iframe, after which server-side workers parse into PostgreSQL normalized mail
  evidence and raw PST retention is delete-after-success or policy-controlled.
  Local Companion import is optional / advanced / policy-triggered, and both
  parser locations must emit the same `MailEvidenceBundle` contract. KG
  construction from mail evidence is Phase 2.
- The current #21 internal workflow helper can run a synthetic
  UploadSession-bound server-side mail import through normal Asset /
  IngestionJob / FixtureMailArchiveExtractor records, build a
  `MailEvidenceBundle` with `upload_session_id`, write it through the
  PostgreSQL mail evidence store contract, and verify a store-backed JSON-RPC
  `query_mail_evidence` owner path. This is still synthetic/internal evidence:
  it does not claim real PST parsing, upload UI / iframe readiness, live
  PostgreSQL readiness, production worker leasing, KG writes, wiki projection,
  or production readiness.
- The current #21 ChatGPT-facing upload entrypoint can return a session-bound
  mail archive upload task card through `open_upload_session`, attach guided
  PST/OST/MSG/EML/MBOX source-preparation guidance, and create an audited
  `UploadSession` while rejecting user-supplied storage backends, parser
  controls, worker queues, raw paths, SQL-like values, and unsupported owner or
  visibility scopes. This is still only a task-card/session-entrypoint slice:
  it does not implement the real upload iframe, real mail parser, live
  PostgreSQL readiness, production worker leasing, or ChatGPT smoke completion.
- The semantic JSON-RPC runtime entrypoint for that task-card path is
  `formowl-semantic-mcp-jsonrpc`. It wires `open_upload_session` to the mail
  upload session handler. The current command preflight launches that console
  command, performs `initialize`, `tools/list`, and
  `tools/call open_upload_session`, verifies the persisted session-bound task
  card, and writes only hash/status/count report data. This still is not an
  actual ChatGPT connected smoke, and the command still does not transfer
  files, implement the upload iframe, or parse real mail archives.
- The current #21 backend upload-intake checkpoint can receive a
  server-staged PST/OST/MSG/EML/MBOX upload for an existing matching
  `UploadSession`, register it as a governed `Asset` and ObjectStore payload,
  bind `UploadSession.asset_id`, write upload-receipt audit, reuse duplicate
  payload bytes for repeated rolling exports, and return only a
  hash/status/count public receipt. This is backend file-transfer receipt, not
  the actual iframe UI, actual ChatGPT connected upload, real mail parser,
  live PostgreSQL readiness, production worker leasing, KG writes, wiki
  projection, or production readiness.
- The current #21 local HTTP upload-surface contract checkpoint provides a
  stdlib `ThreadingHTTPServer` harness for a session-bound mail upload form.
  `GET /mail/upload/<upload_session_id>` renders a single-session
  multipart form, and `POST /mail/upload/<upload_session_id>` accepts one
  PST/OST/MSG/EML/MBOX `mail_archive` file, stages it temporarily, calls the
  backend upload-intake helper, cleans up the temporary staged body, and returns
  a safe JSON receipt. It rejects malformed multipart input, route/form/session
  mismatches, unsupported file names, oversized requests, wrong actor/status,
  and user-supplied storage/parser/worker fields before durable side effects.
  This is a local contract harness only: it does not claim actual ChatGPT
  connected upload, production iframe readiness, real mail parser readiness,
  live PostgreSQL readiness, production worker leasing, KG writes, wiki
  projection, or production readiness.
- The current #21 MCP-command-to-local-HTTP upload smoke connects the
  documented `formowl-semantic-mcp-jsonrpc` command path to the local HTTP
  upload-surface harness. It opens a mail `UploadSession` through JSON-RPC
  `open_upload_session`, serves the matching local HTTP form, posts synthetic
  multipart PST bytes to the same session, verifies the resulting
  `UploadSession.asset_id`, Asset/ObjectStore/audit records, staging cleanup,
  safe public report contract, and negative probes for wrong route/session,
  wrong workspace, infrastructure fields, duplicate multipart files, malformed
  multipart, oversized bodies, and startup/surface errors. This supports only
  the local command-to-HTTP upload contract; it is still not an actual ChatGPT
  connected upload, production iframe, real mail parser, live PostgreSQL
  deployment, production worker leasing, KG write, wiki projection, or
  production readiness claim.
- The current #21 local upload-to-import-and-query smoke extends that path
  with server-side synthetic mail import and store-backed evidence query. It
  opens a mail `UploadSession` through the configured MCP command, posts a
  session-bound multipart upload to the local HTTP surface, runs
  `run_upload_session_mail_import()` against the bound `asset_id`, writes
  normalized mail evidence through the PostgreSQL adapter contract, verifies
  owner and denied `query_mail_evidence` JSON-RPC behavior, and probes missing
  asset, wrong source ref, parser failure, evidence-store failure, and query
  failure paths. This is still a synthetic local contract smoke only: it does
  not claim actual ChatGPT connected upload, production iframe readiness, real
  PST/OST/MSG/EML/MBOX parsing, live PostgreSQL deployment, production worker
  leasing, KG write, wiki projection, or production readiness.
- The current #21 ChatGPT connection preflight packages the configured
  `formowl-semantic-mcp-jsonrpc` command path into a bounded manual ChatGPT
  MCP attach contract. It reuses the command smoke, validates a hash-only
  connection package shape, records the required environment-name count,
  required tool count, expected JSON-RPC sequence, and task-card/session shape
  hashes, and rejects package probes that include environment values, concrete
  upload locators, raw command paths, or ChatGPT overclaims. This is only a
  connection-readiness package for the next manual ChatGPT test; it does not
  claim actual ChatGPT connected upload, production iframe readiness, real
  parser readiness, live PostgreSQL deployment, production worker leasing, KG
  write, wiki projection, or production readiness.
- The current #21 ChatGPT result intake checkpoint validates a bounded
  operator-supplied result packet after a manual ChatGPT MCP session calls
  `open_upload_session`. The packet records only hashes, statuses, counts,
  expected sequence binding, tool availability, task-card shape, and operator
  attestation; it rejects environment values, upload locators, mail payload
  fields, raw command paths, static-contract hash tampering, and upload
  overclaims. This is result-packet intake only: it does not let Codex directly
  control ChatGPT, does not claim file transfer, and does not claim production
  readiness.
- The scoped #21 local Phase 1 Mail Evidence Reading proof is complete for
  synthetic evidence and ChatGPT testing readiness. The governed MCP / JSON-RPC
  surface now supports both `query_mail_evidence` and
  `answer_mail_case_progress` over normalized `MailEvidenceBundle` data,
  including owner/denied/forged-grant/trusted-grant and bundle-id probes,
  citation-preserving case-progress answers, hash-only transcripts, and
  explicit false claim boundaries. This completion does not claim actual
  ChatGPT connected upload or file transfer, production iframe readiness, real
  PST/OST/MSG/EML/MBOX parser readiness, live PostgreSQL deployment readiness,
  production worker leasing, KG writes, wiki projection, or production
  readiness.
- The current #21 mail evidence ChatGPT result-intake checkpoint validates a
  bounded operator-supplied result packet after a manual ChatGPT MCP session
  calls fixture-backed `query_mail_evidence` and `answer_mail_case_progress`.
  The packet records only hashes, statuses, counts, smoke-contract binding,
  owner/denied result shapes, positive owner citation counts, denied redaction
  counts, and operator attestation. It rejects raw ChatGPT transcripts, raw
  tool payloads, mail body/snippet/text fields, concrete mail identifiers,
  upload locators, environment values, paths, SQL, parser/storage/worker
  internals, static-contract hash tampering, duplicate response hashes, bool
  counts, permission-bypass claims, KG/wiki claims, and production overclaims.
  This is bounded result-packet intake only: it is not direct Codex-controlled
  ChatGPT verification, not cryptographic proof, not file transfer, not raw
  mail access, and not production readiness.
- The current #21 real PST sampled parser checkpoint adds
  `PstMailArchiveExtractor` under the official mail `ExtractorAdapter`
  boundary and a `scripts/mail_real_pst_smoke.py` harness for the
  operator-provided `tests/pst-exm/archive.pst` fixture. The smoke runs the
  sampled real PST through UploadSession, Asset/ObjectStore, IngestionJob,
  ExtractorRun, mail observations, `MailEvidenceBundle`,
  `PostgreSQLMailEvidenceStore`, and JSON-RPC `query_mail_evidence`
  owner/denied probes. Public output is hash/status/count only, and the
  fixture directory is ignored so the 3GB PST is never added to Git or Docker
  build context. The current retention decision is `retained_by_policy` under
  `retain_7_days`; this checkpoint does not claim the raw PST object has been
  deleted after extraction. It proves sampled real PST parser integration only,
  not full PST parser readiness, actual ChatGPT upload/file transfer,
  production iframe readiness, live PostgreSQL deployment readiness,
  production worker leasing, raw mail access, KG writes, wiki projection, or
  production readiness.
- The current #21 full PST 100-case evaluation checkpoint adds
  `scripts/mail_full_pst_100_case_eval.py` for the operator-provided full PST
  fixture. It runs the full parser path with no `max_messages` sampling,
  builds a normalized `MailEvidenceBundle`, creates 100 deterministic
  manifest-bound mail evidence retrieval cases, preflights selected cases
  through the same governed JSON-RPC `query_mail_evidence` path, and validates
  only hash/status/count public report fields. The latest dev-container run
  passed 100/100 cases, including five AI/progress-related cases, with no
  duplicate response hashes and no staging/scratch leftovers. The query gateway
  now uses a reusable per-bundle inverted snippet index for repeated evidence
  queries, but the full PST import/parser pipeline remains the dominant runtime
  bottleneck and needs phase profiling before any native-parser rewrite. This
  proves only this operator-provided full PST deterministic evidence-reading evaluation;
  it does not claim general PST/OST/MSG/EML/MBOX parser readiness, actual
  ChatGPT upload/file transfer, production iframe readiness, live PostgreSQL
  deployment readiness, production worker leasing, raw mail access,
  delete-after-success retention, KG writes, wiki projection, or production
  readiness.
- The current #21 domain-hard full PST baseline adds
  `scripts/mail_full_pst_domain_hard_case_eval.py`. It keeps the same
  full-PST governed `query_mail_evidence` path but generates 100 harder
  practitioner-style retrieval cases across ten business-function lenses, with
  two positive cross-message cases per positive pattern plus no-match and
  permission-denied probes per domain. The latest dev-container baseline
  scored 20/100, with all permission-denied probes redacted and all no-match
  probes currently failing as hard near-miss retrieval cases. The public report
  is hash/status/count/timing-only, while the private manifest and work
  directory are preserved under `.test-tmp` for follow-up experiments. This is
  a baseline measurement only; it does not claim business answer generation,
  general parser readiness, actual ChatGPT upload/file transfer, production
  iframe readiness, live PostgreSQL readiness, production worker leasing, raw
  mail access, KG writes, wiki projection, or production readiness.
- The current #21 non-BERT KG fusion rescore adds
  `scripts/mail_full_pst_domain_hard_kg_fusion_eval.py`. It reuses the
  preserved domain-hard full-PST work directory and private manifest without
  reparsing the PST, builds deterministic candidate-only mail components from
  full-PST body observations, and scores the same 100 hard-domain cases. This
  path uses thread links and domain/conflict term overlap only; it does not yet
  use the formal scoped ontology contracts, core supertype lattice, type
  alignment candidates, ontology revision pins, BERT, SentenceTransformer,
  torch, transformers, canonical KG writes, or wiki projection. The first
  rescore improved the hard baseline from 20/100 to 30/100, with positives at
  20/80, no-match probes still 0/10, and permission-denied probes still
  10/10. This is a candidate-only research baseline, not business answer
  generation or production readiness.
- The current #21 ontology-guided ablation adds
  `scripts/mail_full_pst_domain_hard_ontology_ablation_eval.py`. It compares
  the same 100 hard-domain case hashes across three arms: baseline retrieval
  (20/100), non-BERT candidate KG (30/100), and ontology-guided non-BERT
  candidate KG (29/100). This arm uses FormOwl `TypeDefinition` and
  `TypeMapping` contracts, a hash-bound ontology revision, and domain-lens to
  closed-core-supertype mappings as candidate scoring/gating signals only. It
  still does not write canonical graph/type state, user graphs, grants, raw
  access, or wiki projections. The result is negative for quality: ontology
  guidance as currently implemented did not beat the simpler candidate KG arm.
- The next #21 ontology experiment is pre-registered in
  `docs/mail-ontology-native-factorial-design.md`. It treats the negative
  ablation above as KG-first evidence only, then defines an ontology-native
  324-arm grid plus 8 controls over typed mail frames, relations, query
  encoding, scoring/gating, and candidate-pool size. This document is a design
  checkpoint, not an experiment result.
- Candidate graph contract models for `CandidateAtom`, `CandidateRelation`, and `ExternalGraphImport` proposal records.
- Canonical graph contract models for `CanonicalAtom`, `CanonicalEntity`,
  `CanonicalRelation`, and `CanonicalGraphRevision`; canonical commit workflow
  remains a separate governed implementation slice.
- Governance policy contract models for extraction, atom granularity, entity
  resolution, relation resolution, lifecycle, and wiki projection, with
  versioned policy ids and graph-layer policy references.
- Scoped ontology contract models for core, extension, and promoted type
  definitions, aliases, mappings, and cross-scope type alignment candidates.
  Alignment candidates require review and cannot carry access grants or
  canonical type writes.
- File-backed proposal stores for semantic metadata, candidate atoms, and candidate relations.
- File-backed vector and optional graph projection stores for derived retrieval
  indexes; stale vector results still require the same permission and grant
  checks as ready results.
- PostgreSQL/pgvector production-adapter contract slice with redacted
  connection config, migration manifest, repository/unit-of-work interfaces,
  migration replay runner, pgvector repository boundary, permission-filtered
  SQL builders, a locked pgvector live-smoke harness, and negative raw-path/SQL
  leak tests. A locked live PostgreSQL transaction-rollback smoke validates the
  metadata-store migration's partial-failure rollback behavior for graph and
  audit rows. This is not end-to-end PostgreSQL/pgvector production adapter
  readiness.
- PostgreSQL-backed ingestion record store adapters for assets, ingestion jobs,
  extractor runs, observations, and upload sessions behind the same create/get/list
  surfaces as the current file-backed stores. These use the internal
  connection protocol and parameterized SQL over validated contract payloads;
  the same asset/job/run/observation workflow now runs against both file-backed
  stores and PostgreSQL-backed stores through shared store protocols. This is
  container-backed same-interface adapter evidence, not live PostgreSQL
  readiness or a ChatGPT-facing database control surface.
- Candidate-only graph resolution helpers that produce fusion proposals,
  score breakdowns, ontology revision pins, clerical review items, and
  permission-aware human review queue exports without granting raw access or
  committing canonical graph merges.
- User graph contract models for `UserGraphProfile`,
  `UserGraphAssemblyPolicy`, and `UserKnowledgeGraphRevision`, including
  stable IDs sensitive to graph membership, source refs, evidence snapshots,
  and permission scope; raw-reference rejection; and guards that keep grants,
  raw assets, access overlays, graph-store mutations, canonical graph mutations,
  canonical merges, and wiki revisions as separate later workflows.
- Grant-aware effective graph view assembly that combines user graph revisions
  with graph projection records, exposes private graph fragments only through
  graph-level grants, returns access-required scope summaries without private
  content, requires requester access to private user graph revisions before
  projection scanning, rejects raw/evidence/internal locators in visible view
  payloads, and keeps raw asset access and canonical merges out of the view.
- Retrieval gateway plumbing for answer-only, evidence-snippet, and raw-asset
  request modes. Raw-asset mode requires an explicit grant and returns only
  governed `formowl://asset/...` locators through an injectable resolver path;
  it does not read raw content or expose filesystem/object-store locations.
- Storage backend registry configuration helpers for local-first deployments
  and metadata-only MinIO/S3-compatible descriptors. Public backend records use
  stable FormOwl storage locators while local roots, internal endpoints, and
  object-store adapter metadata remain private.
- Ingestion worker boundary package that can process pending ingestion jobs
  outside MCP request handling while reusing the existing `IngestionJob`
  records, extractor adapters, stores, and permissioned storage backend
  routing.
- Optional graph-adapter manifests for RapidFuzz and Splink integration
  boundaries; RapidFuzz and Splink package-adapter bindings remain
  candidate-only and do not run by default unless the optional `graph-adapters`
  extra is installed. A narrow container smoke harness can exercise both
  package bindings as candidate-only outputs with no raw access or canonical
  graph writes, but this is not production entity-resolution adapter readiness.
- Candidate-generation capability profiles for heterogeneous remote computers:
  low-spec CPU workers can use deterministic lexical/rule-based generation,
  standard CPU workers keep the legacy BERT/SentenceTransformer embedding
  adapter profile, and high-spec GPU or remote model workers have a BGE large
  embedding default plus BERT-family NER/relation extraction and local LLM
  graph-extraction adapter slots. The current local GPU floor is one NVIDIA
  GeForce GTX 1080 Ti class device with 11GB VRAM. These profiles are
  candidate-only and do not authorize canonical graph/type writes or raw asset
  access.
- Public enterprise KG matching benchmark artifacts comparing the deterministic
  lexical path with the BGE large GPU profile. The 10,000-pair CUAD/SEC
  model-selection run improved from lexical F1 0.078937 to BGE F1 0.623245.
  The 50,000-pair CUAD/SEC/FiQA stakeholder benchmark improved from lexical
  F1 0.080918 to BGE F1 0.758664, with accuracy rising from 0.5225 to
  0.79986. These artifacts remain candidate-only and do not claim production
  latency, canonical graph/type writes, raw asset access, or completed human
  adjudication.
- An ontology-guidance ablation showing why BGE similarity should remain
  ontology-aware. On the 20,000-pair stress benchmark, BGE-only F1 was
  0.342860 with 10,000 cross-type stress false positives; BGE plus the
  ontology gate reached F1 0.757744 and reduced stress false positives to 0.
  This is ablation evidence, not canonical ontology/type mutation authority.
- A locked production adapter stack smoke harness can compose the current
  file-backed retrieval gateway, semantic MCP gateway facade, RapidFuzz/Splink
  candidate-only package bindings, clerical-review packet export, and
  graph-derived wiki projection in the dev container. It is synthetic adapter
  boundary evidence only; it does not claim production readiness, enterprise
  entity-resolution quality, completed adjudication, raw asset access, or
  canonical graph commits.
- A closed-beta readiness smoke harness can compose the current trusted
  internal path through Project/Wiki JSON-RPC, storage backend configuration,
  worker ingestion, observation-to-wiki draft bridging, governed retrieval, and
  the packaged KG-eval facade. It is synthetic closed-beta gate evidence only;
  it does not claim production readiness, live database readiness, automatic
  publishing, raw asset content access, canonical graph writes, or mail adapter
  readiness.
- A deterministic KG research acceptance suite and method note covering recent
  literature comparison, scoped ontology integration, multi-user fusion,
  multimodal enterprise fixtures, four-specialist LLM subagent adjudication as
  the current Plan B target, legacy human compatibility where already
  supported, production adapter gates, metrics, ablations, and explicit known
  failed or blocked claims.
- ChatGPT-facing gateway helpers with public tool schemas and safe error
  envelopes for upload, ingestion, observation listing, candidate graph,
  access, and wiki projection workflows. The gateway uses `McpResultEnvelope`
  outputs, proposal/pending-review stubs where handlers are not configured,
  and bans on direct database, filesystem, raw SQL, worker-internal, and
  canonical mutation tools.
- MCP JSON-RPC compatibility gateway for `initialize`, `tools/list`, and
  `tools/call`. Coverage includes the semantic gateway plus existing Project
  MCP and Wiki MCP server behavior, with session context, hash-only leak
  transcripts, and raw/internal payload rejection. This is not an end-to-end
  production adapter claim.
- `WikiProjectionSpec` contract objects that pin graph revision, ontology
  revision, source references, evidence snapshots, citation behavior, and
  redaction policy before graph-aware wiki drafts are generated.
- Projection-spec-driven Wiki MCP draft generation for visible graph views,
  preserving graph/ontology/user-graph lineage in frontmatter and creating
  refresh diffs without publishing pages.
- Deterministic text-fixture candidate extraction that turns marked observations into reviewable candidate atom proposals.
- Candidate preview tooling that exposes review actions, warnings, confidence, and provenance without committing canonical graph state.
- Canonical graph contract models for atoms, entities, relations, and graph revisions, with stable canonical object IDs across revisions.
- Project MCP with a mocked OpenProject adapter, evidence snapshot file storage, context package generation, and proposal-only work item comments.
- Wiki MCP with markdown draft generation, frontmatter provenance, draft storage, wiki snapshot capture, and proposal-only publishing.
- Wiki MCP publish proposals route through a backend-specific adapter registry.
  The current OpenProject Wiki adapter prepares safe `upsert_wiki_page`
  proposals with content hashes and revision IDs while keeping automatic
  publishing disabled and omitting API URLs, credentials, raw paths, SQL, and
  other backend internals from public results.
- Dockerfile-managed dev/runtime containers and `.devcontainer/devcontainer.json`.

## Architecture Direction

- Raw resources never directly become final wiki pages.
- Extractors produce observations and semantic metadata.
- Implementation-level extractor routing, metadata schemas, provenance requirements, and adapter boundaries are specified in `RESOURCE_EXTRACTION_SPEC.md`.
- Candidate atoms and relations are reviewed before canonical graph commit.
- Atom granularity, entity resolution, relation resolution, lifecycle changes, and wiki projection are governed by explicit policies.
- Different users can assemble different user knowledge graph revisions from the same canonical graph.
- Wiki revisions are governed output artifacts with citations, evidence snapshots, graph lineage, and review state.

## Specifications

- `SPEC.md` - the main product and architecture specification, including the knowledge graph and wiki projection model.
- `RESOURCE_EXTRACTION_SPEC.md` - extractor routing, observation and semantic metadata schemas, provenance requirements, and adapter boundaries.
- `docs/agent-roles.md` - durable split between the Knowledge Graph Research Agent and the FormOwl System Backbone Agent.
- `docs/architecture.md` - system architecture, knowledge pipeline, and language/storage boundaries.
- `docs/infra-spec.md` - infrastructure, storage backends, workers, and the infrastructure state model.
- `docs/provenance.md` - provenance and source-traceability model.
- `docs/workflows.md` - end-to-end workflow examples.
- `docs/mcp-boundaries.md` - what MCP tools may and may not do.
- `docs/mcp-server-abstract.md` - abstract responsibilities of the Project and Wiki MCP servers.
- `docs/wiki-draft-schema.md` - wiki draft and frontmatter schema.
- `docs/kg-research-method.md` - KG research method, literature comparison,
  acceptance evidence, and known limits.
- `docs/kg-eval-package.md` - packaged KG evaluation facade and integration
  contract for the System Backbone Agent.
- `docs/kg-bert-runtime.md` - optional BERT/SentenceTransformer KG
  candidate-generation runtimes, CPU/GPU Dockerfiles, benchmark manifest, model
  profiles, and artifact rules.
- `docs/closed-beta-runbook.md` - trusted internal closed-beta smoke command,
  pass criteria, and explicit exclusions.
- `docs/local-data-resource-inbox.md` - trusted local folder ingress behavior,
  stability policy, idempotency, and public report boundary.
- `docs/openproject-adapter.md` - OpenProject adapter mapping.
- `docs/implementation-task-breakdown.md` - shared implementation checklist for contributors and agents.

## Development

Build the dev container image:

```sh
docker build -f containers/dev/Dockerfile -t formowl-dev:local .
```

Run tests inside the dev container:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python -m unittest discover -s tests"
```

Run tests with coverage inside the dev container:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "coverage run -m unittest discover -s tests && coverage report"
```

The coverage report enforces the minimum threshold configured in
`pyproject.toml`.

Run the KG research acceptance suite inside the dev container:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/kg_research_acceptance_suite.py"
```

Use `--strict` when the command should fail on any failed or blocked acceptance
item. The default command exits successfully while clearly marking known limits
such as production adapter readiness and enterprise latency/scalability.

The stricter broad KG real-evidence harness lives under `.formowl/kg-eval`.
Its code, fixtures, templates, work orders, preview packets, restart note, and
non-authoritative state snapshots are tracked so the broad gate authority is
reproducible across sessions. Runtime `results/`, operator-supplied or public
reproducible evidence under `inputs/*_real/`, and canonical real evidence
packets remain ignored unless a governed evidence process explicitly decides
otherwise. The current local authority state is blocked at 8/12: the remaining
gates are `fair_external_baseline_comparison`,
`annotation_adjudication_protocol`, `multimodal_semantic_validation`, and
`production_adapter_paths`. This does not claim full product production
readiness, top-tier scientific validation, raw asset access, canonical graph
writes, or enterprise-scale latency/scalability.

The packaged integration facade is `formowl_kg_eval`, with CLI entry point
`formowl-kg-eval` after installation and `python -m formowl_kg_eval` as the
module fallback. System integrations should consume the stable summary instead
of importing repo-local harness scripts directly. The summary includes an
`authority_state` consistency gate and supports the broad completion claim only
when total acceptance, objective audit, preflight, work orders, progress, and
the tracked checklist are all synchronized and passing. The summary also includes
`candidate_generation_capabilities`, which maps low-spec, standard CPU, GPU,
and remote model workers to deterministic or neural candidate-generation
profiles. It also includes `kg_benchmark_results`; integrations that only need
the BGE/lexical/ontology benchmark evidence can call
`python -m formowl_kg_eval benchmarks` for a redacted summary with metrics,
deltas, claim boundaries, and repo-relative SVG chart paths:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python -m formowl_kg_eval summary"
```

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python -m formowl_kg_eval benchmarks"
```

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace/.formowl/kg-eval formowl-dev:local bash -c "python kg_total_acceptance_suite.py && python real_evidence_preflight.py"
```

Run lint and formatting checks inside the dev container:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "ruff check python tests scripts && ruff format --check python tests scripts"
```

Run the closed-beta readiness smoke inside the dev container:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/closed_beta_smoke.py --output /tmp/formowl-closed-beta-smoke.json"
```

Run the issue #21 mail evidence MCP smoke inside the dev container:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_evidence_mcp_smoke.py --output /tmp/formowl-mail-evidence-mcp-smoke.json"
```

This smoke uses a synthetic mail fixture to exercise the ChatGPT-free local path
from asset/job/extractor records to governed JSON-RPC `query_mail_evidence` and
`answer_mail_case_progress` calls. It validates permission filtering,
citations, hash-only transcripts, and hash/status/count public reporting. It
does not claim actual ChatGPT connected upload, production iframe readiness,
real PST/OST/MSG/EML/MBOX parsing, live PostgreSQL deployment readiness,
production worker leasing, KG writes, wiki projection, or production readiness.

The current configured semantic JSON-RPC command for ChatGPT-facing mail upload
task-card testing is:

```sh
FORMOWL_DATA_DIR=.formowl/data formowl-semantic-mcp-jsonrpc
```

Set `FORMOWL_MCP_SESSION_ID`, `FORMOWL_MCP_ACTOR_USER_ID`, and
`FORMOWL_MCP_WORKSPACE_ID` to bind the trusted internal session context for a
local smoke. Unsafe secret-like values are rejected to safe defaults.

Run the #21 mail upload MCP command preflight:

```sh
python scripts/mail_upload_mcp_command_smoke.py --output /tmp/formowl-mail-upload-mcp-command-smoke.json
```

This preflight checks the configured command path and upload task-card session
creation only. It does not claim actual ChatGPT connection, file transfer, real
upload iframe readiness, real mail parser readiness, live PostgreSQL readiness,
production worker leasing, KG writes, wiki projection, or production readiness.

Run the #21 mail upload-surface intake focused tests:

```sh
python -m unittest discover -s tests -p "test_mail_upload_surface.py"
```

These tests cover backend receipt and rollback for a session-bound upload
surface. They do not perform an actual iframe or ChatGPT connected upload.

Run the #21 local HTTP upload-surface contract focused tests:

```sh
python -m unittest discover -s tests -p "test_mail_upload_http_surface.py"
```

These tests exercise the stdlib local HTTP GET/POST multipart harness and its
handoff into backend upload intake. They still do not perform an actual ChatGPT
connected upload or production iframe test.

Run the #21 MCP-command-to-local-HTTP upload smoke:

```sh
python scripts/mail_upload_mcp_http_smoke.py --output /tmp/formowl-mail-upload-mcp-http-smoke.json
```

This smoke proves the configured command can open the upload task and that the
local HTTP surface can receive one synthetic session-bound mail archive upload.
It still does not perform an actual ChatGPT connected upload, production iframe
test, real mail parsing, live PostgreSQL deployment, production worker leasing,
KG writes, wiki projection, or production readiness.

Run the #21 local upload-to-import-and-query smoke:

```sh
python scripts/mail_upload_mcp_http_import_smoke.py --output /tmp/formowl-mail-upload-mcp-http-import-smoke.json
```

This smoke extends the local command-to-HTTP path through the synthetic
server-side import workflow and store-backed `query_mail_evidence` JSON-RPC
surface. It still does not perform an actual ChatGPT connected upload,
production iframe test, real PST/OST/MSG/EML/MBOX parsing, live PostgreSQL
deployment, production worker leasing, KG writes, wiki projection, or
production readiness.

Run the #21 sampled real PST ingestion smoke inside the dev container after
placing the operator-provided PST at `tests/pst-exm/archive.pst`:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_real_pst_smoke.py --output .test-tmp/formowl-real-pst-sampled-smoke.json --mode sampled --sample-message-limit 25"
```

Validate the saved public report:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_real_pst_smoke.py --validate-report .test-tmp/formowl-real-pst-sampled-smoke.json --output .test-tmp/formowl-real-pst-sampled-validation.json"
```

This smoke requires `readpst` from the dev image's `pst-utils` package. The
report must remain hash/status/count-only: do not paste PST contents, concrete
message identifiers, subjects, senders, attachment names, body text, object
store locators, parser command lines, scratch paths, SQL, or environment values
into public reports. The sampled smoke may set
`supports_real_pst_sampled_parser_claim=true` only after the report validator
passes. It must keep full-parser, production, ChatGPT upload/file-transfer,
iframe, worker-leasing, raw-mail-access, KG, and wiki claims false.

Run the #21 full PST 100-case mail evidence evaluation inside the dev container
after placing the operator-provided PST at `tests/pst-exm/archive.pst`:

```sh
docker run --rm -e FORMOWL_RUN_FULL_PST_100_CASE_EVAL=1 -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_full_pst_100_case_eval.py --output .test-tmp/formowl-mail-full-pst-100-case-eval.json"
```

Validate the saved public report:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_full_pst_100_case_eval.py --validate-report .test-tmp/formowl-mail-full-pst-100-case-eval.json --output .test-tmp/formowl-mail-full-pst-100-case-validation.json"
```

This evaluation performs a full parse with no message sampling, then scores 100
manifest-bound governed `query_mail_evidence` cases. The public report must
remain hash/status/count-only and must not include query text, PST contents,
concrete message identifiers, subjects, senders, attachment names, body text,
object-store locators, parser command lines, scratch paths, SQL, or
environment values. Passing this evaluator supports only the operator-provided
full PST 100-case evidence-reading evaluation claim; it is not a general mail
parser, ChatGPT upload, production iframe, live PostgreSQL, worker-leasing,
raw-mail-access, KG, wiki, or production readiness claim.

Run the #21 domain-hard full PST mail evidence baseline inside the dev
container:

```sh
docker run --rm -e FORMOWL_RUN_FULL_PST_DOMAIN_HARD_CASE_EVAL=1 -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_full_pst_domain_hard_case_eval.py --output .test-tmp/formowl-mail-domain-hard-case-baseline.json --work-dir .test-tmp/formowl-mail-domain-hard-case-baseline-work"
```

Validate the saved public report:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_full_pst_domain_hard_case_eval.py --validate-report .test-tmp/formowl-mail-domain-hard-case-baseline.json --output .test-tmp/formowl-mail-domain-hard-case-baseline-validation.json"
```

This baseline intentionally allows low pass rates so difficult cases can expose
retrieval and performance gaps. The public report must remain
hash/status/count/timing-only. Do not paste query text, PST contents, concrete
message identifiers, subjects, senders, body text, private manifest contents,
object-store locators, parser command lines, scratch paths, SQL, or environment
values into public reports.

Run the #21 non-BERT candidate-only KG fusion rescore over a preserved
domain-hard work directory:

```sh
docker run --rm -e FORMOWL_RUN_FULL_PST_DOMAIN_HARD_KG_FUSION_EVAL=1 -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_full_pst_domain_hard_kg_fusion_eval.py --baseline-report .test-tmp/formowl-mail-domain-hard-case-baseline-v4.json --work-dir .test-tmp/formowl-mail-domain-hard-case-baseline-work-v4 --output .test-tmp/formowl-mail-domain-hard-kg-fusion-eval-v1.json"
```

Validate the saved KG fusion public report:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_full_pst_domain_hard_kg_fusion_eval.py --validate-report .test-tmp/formowl-mail-domain-hard-kg-fusion-eval-v1.json --output .test-tmp/formowl-mail-domain-hard-kg-fusion-eval-v1-validation.json"
```

This rescore does not reparse the PST and does not use BERT or any neural
package. It is a candidate-only graph-structure experiment over existing
observations; the current implementation has not yet integrated formal ontology
governance or canonical graph state.

Run the #21 ontology-guided non-BERT ablation over the same preserved
domain-hard work directory:

```sh
docker run --rm -e FORMOWL_RUN_FULL_PST_DOMAIN_HARD_ONTOLOGY_ABLATION_EVAL=1 -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_full_pst_domain_hard_ontology_ablation_eval.py --baseline-report .test-tmp/formowl-mail-domain-hard-case-baseline-v4.json --work-dir .test-tmp/formowl-mail-domain-hard-case-baseline-work-v4 --output .test-tmp/formowl-mail-domain-hard-ontology-ablation-eval-v1.json"
```

Validate the saved ontology ablation public report:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_full_pst_domain_hard_ontology_ablation_eval.py --validate-report .test-tmp/formowl-mail-domain-hard-ontology-ablation-eval-v1.json --output .test-tmp/formowl-mail-domain-hard-ontology-ablation-eval-v1-validation.json"
```

The ontology arm is a candidate-only ablation. It validates formal ontology
contract usage and a revision hash, but it does not claim completed ontology
governance, canonical type writes, canonical KG writes, raw access, wiki
projection, business answer generation, or production readiness.

Run the #21 ChatGPT MCP connection preflight package:

```sh
python scripts/mail_upload_chatgpt_connection_preflight.py --output /tmp/formowl-mail-upload-chatgpt-connection-preflight.json
```

This preflight proves the command path can be packaged for manual ChatGPT MCP
configuration without exposing environment values, local paths, upload
locators, parser controls, storage controls, or backend internals in its public
report. The manual ChatGPT MCP server configuration should use the stdio command
`formowl-semantic-mcp-jsonrpc` and operator-supplied local values for
`FORMOWL_DATA_DIR`, `FORMOWL_MCP_SESSION_ID`,
`FORMOWL_MCP_ACTOR_USER_ID`, `FORMOWL_MCP_WORKSPACE_ID`, and
`FORMOWL_MAIL_UPLOAD_EXPIRES_AT`. The next live ChatGPT test must still prove
the actual ChatGPT-connected session separately.

Run the #21 ChatGPT MCP result packet intake after a manual ChatGPT MCP test:

```sh
python scripts/mail_upload_chatgpt_result_intake.py --input /tmp/formowl-chatgpt-result-packet.json --output /tmp/formowl-mail-upload-chatgpt-result-intake.json
```

The input packet must be a bounded operator summary of the ChatGPT MCP session:
hashes, statuses, counts, expected `initialize` / `tools/list` /
`tools/call open_upload_session` sequence, task-card shape hashes, and explicit
attestation that raw ChatGPT detail payloads, environment values, upload
locators, and mail payloads were excluded. Do not paste raw ChatGPT transcripts,
PST contents, upload session IDs, local paths, or environment values into the
packet.

Run the #21 mail evidence ChatGPT result packet intake after a manual
fixture-backed ChatGPT MCP evidence-reading smoke:

```sh
python scripts/mail_evidence_chatgpt_result_intake.py --input /tmp/formowl-mail-evidence-chatgpt-result-packet.json --output /tmp/formowl-mail-evidence-chatgpt-result-intake.json
```

The input packet must be a bounded operator summary of the ChatGPT MCP session:
hashes, statuses, counts, the expected `initialize` / `tools/list` /
`query_mail_evidence` owner/denied / `answer_mail_case_progress` owner/denied
sequence, fixture-smoke contract hashes, owner citation counts, denied
redaction counts, and explicit attestation that raw transcripts, raw tool
payloads, mail text, concrete mail identifiers, environment values, upload
locators, paths, SQL, and parser/storage/worker internals were excluded. Do
not paste raw ChatGPT transcripts, mail body/snippet text, concrete bundle or
message IDs, local paths, SQL, or environment values into the packet.

## Repository Skills

Reusable Codex workflow skills live under `.agents/skills/` so Codex can
discover them as repo-scoped skills when launched from this repository.
Available repo skills include `$harden-completed-slice-tests` for strict
completed-slice test hardening and `$use-agy-antigravity` for the historical
Antigravity `agy` workflow and current disablement rules. The canonical
tracked Antigravity skill file is
`.agents/skills/use-agy-antigravity/SKILL.md`; keep KG `agy` authorization,
reviewer, bounded write-delegation, MCP-route probe, and disablement notes
there so they travel with Git.

To use the same skill on another host, copy the repository with its `.agents`
directory intact, start a new Codex session from the repo, and confirm the skill
appears in `/skills`.

## Agent Goal Registry

Durable multi-agent goals live under `docs/agent-goals/`. These files make
long-running objectives portable across sessions and machines:

- `docs/agent-goals/kg-research-agent.md`
- `docs/agent-goals/system-backbone-agent.md`
- `docs/agent-goals/handoff-log.md`
- `docs/agent-goals/reviewer-gate.md`

Use `docs/implementation-task-breakdown.md` for checkbox task completion and
`docs/agent-goals/` for current objective, scope, blockers, status, and handoff
state.

Install and run pre-commit checks from inside the dev container:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "pre-commit run --all-files"
```

The pre-commit suite checks credentials/secrets, merge conflict markers, large files, text whitespace, Python/JSON/TOML syntax, Python lint/format with Ruff, and Python unit tests. Host-side Python may be used for quick local inspection, but container results are the completion baseline.

The default commit-time secret checks include the lightweight local credential scanner and Gitleaks. For a deeper audit, run the manual secret scans:

```sh
pre-commit run gitleaks-history --hook-stage manual
pre-commit run trufflehog-history --hook-stage manual
```

The dev container installs Gitleaks for commit-time scanning. TruffleHog remains manual because it is heavier; this repo runs it with verification disabled so the scan stays local.

## MCP JSON Line Compatibility Entry Points

The legacy Python MCP server modules still accept one JSON request per stdin
line and print one JSON response per line for local compatibility testing only.
Packaged console scripts use explicit compatibility names:
`formowl-project-mcp-jsonline-compat` and
`formowl-wiki-mcp-jsonline-compat`. The FormOwl gateway package provides the
JSON-RPC compatibility wrapper for existing MCP server objects and semantic
gateway tools; Project/Wiki behavior is preserved through transport tests.

Project MCP compatibility example:

```sh
formowl-project-mcp-jsonline-compat
```

Request:

```json
{
  "tool": "get_work_item_context",
  "arguments": {
    "source_ref": {
      "source_system": "openproject",
      "source_type": "work_package",
      "source_id": "123"
    },
    "include_comments": true,
    "include_activities": true,
    "include_relations": true,
    "include_attachments": true,
    "create_evidence_snapshot": true
  }
}
```

Wiki MCP compatibility example:

```sh
formowl-wiki-mcp-jsonline-compat
```

Set `FORMOWL_DATA_DIR` to control evidence, draft, snapshot, and tool-call log storage. The default is `.formowl/data`.
