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
- Deterministic file technical metadata extractor for file size, MIME type, content hash, and FormOwl object locator observations.
- Deterministic fixture adapters for document structure, OCR text, audio transcripts, video scene/keyframe observations, and mail/archive observations.
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
- Optional graph-adapter manifests for RapidFuzz and Splink integration
  boundaries; RapidFuzz and Splink package-adapter bindings remain
  candidate-only and do not run by default unless the optional `graph-adapters`
  extra is installed. A narrow container smoke harness can exercise both
  package bindings as candidate-only outputs with no raw access or canonical
  graph writes, but this is not production entity-resolution adapter readiness.
- A locked production adapter stack smoke harness can compose the current
  file-backed retrieval gateway, semantic MCP gateway facade, RapidFuzz/Splink
  candidate-only package bindings, clerical-review packet export, and
  graph-derived wiki projection in the dev container. It is synthetic adapter
  boundary evidence only; it does not claim production readiness, enterprise
  entity-resolution quality, completed adjudication, raw asset access, or
  canonical graph commits.
- A deterministic KG research acceptance suite and method note covering recent
  literature comparison, scoped ontology integration, multi-user fusion,
  multimodal enterprise fixtures, four-specialist LLM subagent adjudication as
  the current Plan B target, legacy human compatibility where already
  supported, production adapter gates, metrics, ablations, and explicit known
  failed or blocked claims.
- ChatGPT-facing semantic gateway helpers with public tool schemas, safe error
  envelopes, proposal-only review/draft stubs, and bans on direct database,
  filesystem, raw SQL, worker-internal, and canonical mutation tools.
- Semantic MCP JSON-RPC compatibility gateway for `initialize`, `tools/list`,
  and `tools/call`, with session context, hash-only leak transcripts, and
  containerized smoke coverage. This is not an end-to-end production adapter
  claim.
- `WikiProjectionSpec` contract objects that pin graph revision, ontology
  revision, source references, evidence snapshots, citation behavior, and
  redaction policy before graph-aware wiki drafts are generated.
- Projection-spec-driven Wiki MCP draft generation for visible graph views,
  preserving graph/ontology/user-graph lineage in frontmatter and creating
  refresh diffs without publishing pages.
- Deterministic text-fixture candidate extraction that turns marked observations into reviewable candidate atom proposals.
- Candidate preview tooling that exposes review actions, warnings, confidence, and provenance without committing canonical graph state.
- Project MCP with a mocked OpenProject adapter, evidence snapshot file storage, context package generation, and proposal-only work item comments.
- Wiki MCP with markdown draft generation, frontmatter provenance, draft storage, wiki snapshot capture, and proposal-only publishing.
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
otherwise. The current local authority state has the broad KG real-evidence
gates clear at 12/12; this does not claim full product production readiness,
top-tier scientific validation, raw asset access, canonical graph writes, or
enterprise-scale latency/scalability.

The packaged integration facade is `formowl_kg_eval`, with CLI entry point
`formowl-kg-eval` after installation and `python -m formowl_kg_eval` as the
module fallback. System integrations should consume the stable summary instead
of importing repo-local harness scripts directly:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python -m formowl_kg_eval summary"
```

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace/.formowl/kg-eval formowl-dev:local bash -c "python kg_total_acceptance_suite.py && python real_evidence_preflight.py"
```

Run lint and formatting checks inside the dev container:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "ruff check python tests scripts && ruff format --check python tests scripts"
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

## MCP JSON Line Entry Points

Both Python MCP server modules currently accept one JSON request per stdin line and print one JSON response per line. This is a prototype transport for local testing, not standards-compliant MCP JSON-RPC over stdio yet.

Project MCP example:

```sh
python -m formowl_project_mcp
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

Wiki MCP example:

```sh
python -m formowl_wiki_mcp
```

Set `FORMOWL_DATA_DIR` to control evidence, draft, snapshot, and tool-call log storage. The default is `.formowl/data`.
