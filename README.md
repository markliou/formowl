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
