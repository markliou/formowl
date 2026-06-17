# formowl

<!-- Future agents: continue building from the files listed in the SPEC.md Suggested Repository Layout section. Do not create parallel replacement files unless the specification is updated first. -->

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

The primary implementation languages are Python and Rust. Python is the readable orchestration and debugging layer. Rust owns heavy computing, security-sensitive logic, parsers, validation, integrity checks, and any functionality whose Python implementation would expose strange or hard-to-maintain syntax.

Rust core functionality is exposed to Python through the `formowl_core` API. The initial binding scaffold uses a dependency-free C ABI plus `ctypes`, with a Python fallback for local debugging when the native library has not been built yet.

## Current Implementation

- Python contract models for source references, permission scopes, evidence snapshots, context packages, wiki revisions, and MCP result envelopes.
- Project MCP with a mocked OpenProject adapter, evidence snapshot file storage, context package generation, and proposal-only work item comments.
- Wiki MCP with markdown draft generation, frontmatter provenance, draft storage, wiki snapshot capture, and proposal-only publishing.
- Rust `formowl-core` crate for hashing, newline normalization, and simple diff utilities.
- Dockerfile-managed dev/runtime containers and `.devcontainer/devcontainer.json`.

## Architecture Direction

- Raw resources never directly become final wiki pages.
- Extractors produce observations and semantic metadata.
- Implementation-level extractor routing, metadata schemas, provenance requirements, and adapter boundaries are specified in `RESOURCE_EXTRACTION_SPEC.md`.
- Candidate atoms and relations are reviewed before canonical graph commit.
- Atom granularity, entity resolution, relation resolution, lifecycle changes, and wiki projection are governed by explicit policies.
- Different users can assemble different user knowledge graph revisions from the same canonical graph.
- Wiki revisions are governed output artifacts with citations, evidence snapshots, graph lineage, and review state.

## Development

Build the dev container image:

```sh
docker build -f containers/dev/Dockerfile -t formowl-dev:local .
```

Run tests on a host with Python available:

```sh
PYTHONPATH=python:python/formowl_project_mcp:python/formowl_wiki_mcp python -m unittest discover -s tests
```

Run tests inside the dev container:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python -m unittest discover -s tests && cargo test --workspace"
```

Install and run pre-commit checks:

```sh
python -m pip install -e ".[dev]"
npm install
pre-commit install
pre-commit run --all-files
```

The pre-commit suite checks credentials/secrets, merge conflict markers, large files, text whitespace, Python/JSON/TOML syntax, Python lint/format with Ruff, TypeScript/JSON/YAML/Markdown style with Prettier, TypeScript typecheck, Python unit tests, and Rust `fmt`/`check`/`clippy`. Run it in the dev container, or install Rust with `cargo`, `rustfmt`, and `clippy` on the host. On Windows PowerShell, use `npm.cmd install` if `npm.ps1` is blocked by execution policy.

The default commit-time secret checks include the lightweight local credential scanner and Gitleaks. For a deeper audit, run the manual secret scans:

```sh
pre-commit run gitleaks-history --hook-stage manual
pre-commit run trufflehog-history --hook-stage manual
```

The dev container installs Gitleaks for commit-time scanning. Outside the dev container, the Gitleaks and TruffleHog hooks run the official Docker images through the local Docker daemon, so no host-level scanner package install is required. TruffleHog remains manual because it is heavier; this repo runs it with verification disabled so the scan stays local.

On Windows PowerShell, use semicolon-separated `PYTHONPATH` values for host-side Python:

```powershell
$env:PYTHONPATH='python;python/formowl_project_mcp;python/formowl_wiki_mcp'
python -m unittest discover -s tests
```

## MCP JSON Line Entry Points

Both Python MCP server modules accept one JSON request per stdin line and print one JSON response per line.

Project MCP example:

```sh
python -m formowl_project_mcp.server
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
python -m formowl_wiki_mcp.server
```

Set `FORMOWL_DATA_DIR` to control evidence, draft, snapshot, and tool-call log storage. The default is `.formowl/data`.
