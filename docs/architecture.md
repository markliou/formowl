# Architecture

<!-- Future agents: continue building the system architecture documentation in this file. Do not create another architecture document unless SPEC.md is updated first. -->

FormOwl uses a container-first architecture and a graph-governed knowledge pipeline.

The canonical development, test, and deployment environment is a container. Host-installed runtimes are optional conveniences, not required assumptions.

The central identity rule is:

```text
Physical storage may be distributed.
Knowledge identity must be centralized.
```

Raw bytes may live on multiple internal storage backends, including Synology volumes, NAS shares, S3-compatible object storage, MinIO, or controlled ingress folders. Any file that participates in extraction, graph construction, search, or wiki projection must first be registered in the central FormOwl asset catalog. The knowledge graph references stable FormOwl identifiers, not raw storage paths.

## Target Knowledge Pipeline

```text
Raw Resources
  -> Resource Extraction Layer
  -> Observation Store
  -> Candidate Graph
  -> Governed Canonical Graph
  -> User Knowledge Graph
  -> Wiki Projection Layer
  -> WikiRevision
```

Raw resources include project system records, wiki pages, ChatGPT conversations, markdown, PDFs, office documents, images, audio, video, screenshots, and other captured files.

The pipeline rule is strict: raw resources do not directly become final wiki pages. They first become observations and semantic metadata, then candidate graph objects, then governed canonical graph state, then user-specific graph views, and only then projected wiki revisions.

## Governance Layer

Governance crosses every stage of the pipeline.

Policy objects should include:

```text
ExtractionPolicy
AtomGranularityPolicy
OntologyPolicy
EntityResolutionPolicy
RelationResolutionPolicy
LifecyclePolicy
UserGraphAssemblyPolicy
WikiProjectionPolicy
```

External extractors and LLM graph tools may create observations, candidate atoms, candidate relations, or external graph imports. They must not directly mutate canonical graph state.

## Store Boundaries

```text
AssetStore -> raw resource metadata
ObjectStore -> raw binary files
ObservationStore -> extracted observations
CandidateAtomStore -> uncommitted candidate atoms and relations
CanonicalGraphStore -> canonical atoms, entities, relations, lifecycle events, and graph revisions
UserGraphStore -> user-specific graph revisions
WikiStore -> wiki drafts, revisions, snapshots, and publish proposals
VectorStore -> embeddings for similarity search
JobStore -> ingestion and extraction job status
```

Project MCP and Wiki MCP are current service boundaries inside this larger architecture. Future ingestion and graph services should share contracts with them instead of depending on their internals.

## Internal Storage and Deployment Boundary

The first deployment target is an internal company or lab environment. Raw data should remain inside the trusted network. Synology NAS, PostgreSQL, MinIO or other object storage, worker scratch directories, and raw file paths must not be exposed directly to ChatGPT or the public internet.

PostgreSQL is the source of truth for metadata, governance, job state, permissions, audit, and graph state. It should run on local SSD, NVMe, or reliable block storage, not ordinary NAS or NFS-mounted storage. NAS and object storage are appropriate for raw files, large derived artifacts, backups, snapshots, and retention.

Workers should process registered assets by `asset_id` and `object_uri`. Large files should be copied to local scratch before parsing. Worker scheduling may be storage-aware, but storage locality is a performance concern; it must not fragment knowledge identity.

## Identity and Collaborative Graphs

For the internal closed beta, FormOwl may use a manual trusted internal identity mode: a user selects their FormOwl identity at MCP session start, and the selected identity becomes the `actor_user_id` for tool calls and audit records. This is a temporary identity facade, not a production authentication model.

Stable `user_id`, `workspace_id`, asset ownership, access requests, grants, and audit logs must exist from the beginning so the authentication provider can later be replaced by company SSO, OIDC, SAML, or another provider without replacing authorization and provenance.

Cross-user graph collaboration should use permissioned overlays and grants. Another user's private graph must not be silently merged into the requester graph. Shared answers, graph snippets, evidence snippets, and raw asset access should each have explicit scope, provenance, and audit records.

## Language Boundary

Python is the implementation language for Phase 0. It owns MCP orchestration, adapters, workflow glue, review flows, test fixtures, hashing helpers, diff helpers, validation glue, and day-to-day debugging.

Additional runtime languages must not be introduced unless a concrete parser, validator, large-data transform, or safety boundary requires them and `SPEC.md` is updated first.

## Syntax Shielding

When Python code would require unusual metaprogramming, deeply nested decorators, generated code, fragile regular expressions, complex DSLs, or unsafe dynamic evaluation, the complexity belongs behind a clear Python API boundary. A systems-language backend can be introduced later only with a concrete need and a specification update.
