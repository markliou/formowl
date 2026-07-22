# formowl Specification

## 1. Overview

`formowl` is a source-preserving, graph-governed knowledge management system for turning multimodal resources, project execution data, conversations, and wiki/documentation systems into governed knowledge views.

The target architecture is a pipeline:

```text
Ingress / External Source
  -> Managed Asset in durable ObjectStore
  -> Resource Extraction
  -> Observation / Semantic Metadata
  -> Candidate Graph
  -> Governed Canonical Knowledge Graph
  -> User Knowledge Graph
  -> Wiki Projection / WikiRevision
```

`resources` or another controlled local folder is an ingress and processing
workspace, not the authoritative long-term byte store. Files accepted through
that ingress must be copied into a managed S3-compatible `ObjectStore`, verified,
registered as governed `Asset` records, and then removed from ingress according
to cleanup policy. MinIO, another S3-compatible service, or the local
`FileObjectStore` development implementation may satisfy the `ObjectStore`
interface; the contract must not depend on one vendor.

The current repository starts with independently maintained MCP servers and a shared contract package:

```text id="1b5hso"
Project MCP
Wiki MCP
formowl-contract
```

These components are not the whole product boundary. They are the first concrete entrypoints for retrieving source context, preserving evidence, generating wiki artifacts, and validating the contract model that later resource extraction and graph assembly layers must also use.

The goal is to keep managed source Assets, governed external source records,
project execution state, canonical graph state, user-specific graph views, and
wiki artifacts decoupled, while preserving provenance, citations, source
traceability, extraction lineage, graph governance, and revision history.

The system must be usable by people who are not software engineers. Administrative owners, project coordinators, reviewers, and process operators should be able to work through natural-language instructions and review-oriented actions. Technical mechanisms such as Git, object storage, schemas, hashes, and revision backends must remain implementation details unless an administrator explicitly asks to inspect them.

---

## 2. Core Concept

```text id="1mhwmd"
ChatGPT / LLM Host
  -> Project MCP
  -> Wiki MCP
  -> future ingestion and graph orchestration tools

Shared Contract
  -> formowl-contract

Knowledge Pipeline
  -> Observation
  -> Candidate Graph
  -> Governed Canonical Graph
  -> User Knowledge Graph
  -> WikiRevision
```

Project MCP is responsible for project execution context.

Wiki MCP is responsible for knowledge artifact creation and wiki publishing lifecycle.

Resource extraction and graph assembly are responsible for converting managed
source Assets and governed external source records into observations, candidate
atoms, canonical atoms, canonical entities, canonical relations, user graph
revisions, and projection-ready graph views.

`formowl-contract` defines the shared data structures that allow Project MCP, Wiki MCP, ingestion tools, and graph assembly tools to exchange information without depending on each other's internal implementation.

---

## 3. Design Principles

1. Raw source data is the source of truth. For a managed Asset, this means the
   verified durable bytes in ObjectStore plus the authoritative Asset identity,
   scope, lineage, lifecycle, and retention metadata in PostgreSQL.
2. Wiki pages are knowledge views, not source of truth.
3. LLM-generated summaries, drafts, extracted observations, candidate atoms, and graph proposals are derived data.
4. Project management systems own execution state.
5. Wiki systems own published knowledge views.
6. Managed source Assets and governed external source records do not directly
   generate wiki pages; they first become observations and semantic metadata.
7. Observations are the common intermediate form for audio, video, image, document, text, project, wiki, and conversation resources.
8. External extractors and LLM graph tools must write to observation stores, candidate stores, or import buffers, not directly to the canonical graph.
9. Candidate graph output is a proposal layer; it must pass granularity policy, entity resolution, relation resolution, lifecycle policy, and review policy before canonical commit.
10. Atom granularity is a first-class governance policy, not an incidental property of an extractor.
11. Canonical atoms, canonical entities, and canonical relations are reusable governed knowledge parts, not any user's final graph.
12. Different users may assemble different knowledge graphs from the same raw data, evidence snapshots, observations, candidate atoms, and canonical atoms.
13. User knowledge graphs are derived, versioned views. They may reflect changing user goals, attention, terminology, permissions, tasks, and preferred granularity.
14. Wiki projection must be controlled by projection specs and review flows, not by unconstrained one-off generation.
15. Every generated knowledge artifact must preserve source references.
16. Any external data used to generate knowledge must be traceable.
17. Any user graph assembly must preserve provenance back to raw data, evidence snapshots, citations, observations, and canonical atoms when available.
18. Write operations must use proposal and review flows.
19. The primary user workflow must be natural-language-first and non-technical-user-friendly.
20. Technical governance mechanisms must be hidden behind task-oriented actions such as save draft, submit for review, compare changes, publish, refresh from sources, and restore.
21. Wiki artifacts are versioned knowledge views derived from graph views and source evidence; they are not raw truth.
22. Regenerating a wiki artifact must create a reviewable proposal or diff, not silently overwrite reviewed or published knowledge.
23. Git may be used as a revision backend, audit mirror, or engineering workflow, but it must not be required as the user-facing wiki workflow.
24. Project MCP, Wiki MCP, ingestion tools, and graph assembly tools must remain independently maintainable.
25. Integration between components must happen through shared schemas, not direct dependencies.
26. Development, testing, and deployment must be container-first to maximize portability and avoid host-machine assumptions.
27. Python is the implementation language for Phase 0.
28. Python owns MCP service glue, workflows, adapters, tests, hashing helpers, diff helpers, and day-to-day debugging.
29. Additional systems languages must not be introduced unless a concrete parser, validator, large-data transform, or safety boundary requires them.
30. If a future system language is introduced, it must be hidden behind clear Python APIs and documented as a specific implementation boundary rather than a default architectural premise.
31. Physical storage may be distributed, but knowledge identity must be centralized.
32. Raw storage paths, NAS endpoints, PostgreSQL, object-store admin endpoints, worker scratch directories, and local filesystem paths must not be exposed through ChatGPT-facing MCP tools.
33. Files must be registered as FormOwl assets before they participate in extraction, search, graph construction, or wiki projection.
34. The only formal human identity flow for a connected deployment is the
    public HTTPS FormOwl MCP resource through FormOwl OAuth 2.1 and Google OIDC.
    Manual trusted actor selection is limited to tests and local compatibility
    tooling and must never be enabled on the connected service.
35. The MCP Gateway, not the caller, resolves the authenticated user, current
    workspace, memberships, grants, and session into a fresh `ActorContext` for
    every protected tool call.
36. Cross-user graph collaboration must use permissioned graph overlays and grants, not silent graph merging.
37. Controlled local resource folders are ingress, quarantine, and processing
    workspaces. They are not the authoritative permanent store and must not be
    used as the retrieval identity of an Asset.
38. Managed raw bytes must be durably committed to an S3-compatible
    `ObjectStore` before an ingress item is considered accepted. Local
    `FileObjectStore` is the development and test implementation of the same
    boundary, not a separate product architecture.
39. PostgreSQL is authoritative for Asset identity, tenant and workspace scope,
    ownership, permission, lineage, lifecycle, retention, and audit. Object
    storage is authoritative for managed raw bytes and large derived artifacts.
40. An ingress file may be deleted only after the object write, content-hash
    verification, Asset registration, and required audit records have
    succeeded. Failed, suspicious, or incomplete files must remain isolated in
    quarantine or failed-ingress state rather than being treated as Assets.
41. Attachments are generic nested resources. PDF, presentation, document,
    spreadsheet, image, audio, and video attachments must become independently
    governed Assets and use the normal MIME-routed extractor path. Mail-shaped
    attachments such as MSG, EML, and `message/rfc822` may recursively use the
    mail adapter.
42. Attachment extraction must preserve a relationship from the child Asset to
    the parent message, attachment occurrence, source archive, and import
    session. Byte deduplication must never erase occurrence lineage or merge
    authorization.
43. Normal answer generation should use permission-filtered observations and
    evidence snippets. Original-file preview or download must go through a
    Retrieval Gateway that checks `ActorContext`, Asset scope, grants,
    lifecycle, retention, and audit before issuing a bounded stream or
    short-lived opaque FormOwl download capability.
44. Object-store bucket names, keys, endpoints, credentials, and ingress paths
    are internal adapter details. Public tools use FormOwl identifiers and
    governed locators such as `formowl://asset/{asset_id}`.
45. Durable does not mean retained forever. Asset retention, legal hold,
    redaction, purge, and deletion are governed lifecycle decisions separate
    from ingress cleanup and worker scratch cleanup.

---

## 4. Current Implementation and Target Scope

The connected implementation provides this repository-side workflow:

```text id="lmvw9o"
ChatGPT
  -> public HTTPS FormOwl /mcp resource
  -> FormOwl OAuth 2.1 authorization with PKCE S256 and exact resource/callback binding
  -> Google OIDC login
  -> FormOwl invitation plus (issuer, subject) identity mapping
  -> resource-bound FormOwl access token
  -> fresh server-side ActorContext
  -> whoami and governed semantic tools
```

Project MCP and Wiki MCP continue to prove the bounded project-context to
sourced-wiki-draft workflow behind compatibility entrypoints. They are not
alternate connected identity or ChatGPT attachment paths.

Currently implemented or scaffolded:

```text id="ny0cw0"
Project MCP
Wiki MCP
FormOwl connected MCP Gateway on exact /mcp
OAuth protected-resource and authorization-server metadata
Google OIDC-backed FormOwl OAuth 2.1 bridge
Invitation and first-owner bootstrap lifecycle
PostgreSQL OAuth identity, authorization-session, and audit persistence
Resource-bound FormOwl access tokens and revocation
Gateway-controlled ActorContext and whoami
formowl-contract
OpenProject adapter for Project MCP
Markdown draft generation for Wiki MCP
SourceRef schema
EvidenceSnapshot schema
Citation schema
PermissionScope schema
ContextPackage schema
MCP tool-call logging
Natural-language-first wiki review workflow
Wiki revision abstraction
Container-first development and deployment baseline
Python-only Phase 0 implementation policy
```

The connected implementation has deterministic and container-backed repository
evidence. Real public HTTPS, Google account, ChatGPT connector, MCP Inspector,
restart, and operator-journey evidence remain external completion gates. This
section does not claim issue #20 closure or product production readiness.

Target architecture capabilities to add:

```text
Multimodal asset ingestion
Asset and object stores
Ingress promotion, quarantine, and verified cleanup
Generic AssetOccurrence and Asset relationship lineage
Generic nested-resource and attachment extraction with MIME-based routing
Retention, redaction, purge, and object lifecycle
Permission-checked original-file preview and download
Observation extraction for audio, video, image, document, text, project, wiki, and conversation resources
Semantic metadata extraction from observations
CandidateAtom and CandidateRelation stores
Candidate graph preview and review
AtomGranularityPolicy enforcement
Entity and relation resolution
Canonical graph commit workflow
CanonicalAtom, CanonicalEntity, and CanonicalRelation contract objects
AtomLifecycleEvent, EntityResolutionEvent, and RelationResolutionEvent records
UserGraphAssemblyPolicy and UserKnowledgeGraphRevision
WikiProjectionSpec-driven page generation
Graph-aware WikiRevision lineage
IngestionJob and ExtractorRun tracking
Vector search and optional graph storage
```

Capabilities that should not be assumed to exist until implemented:

```text id="lr46ln"
Full Jira adapter
Automatic wiki publishing
Automatic project write-back
Company-wide ontology
Full permission engine
User-facing Git workflow requirements
Host-machine-specific development requirements
```

This section is an implementation status boundary, not a product boundary. The product architecture is the full resource extraction, graph assembly, user graph, and wiki projection pipeline.

Current implementation alignment notes:

```text
The canonical connected ChatGPT-facing runtime is `formowl-connected-mcp`. It
uses the official MCP SDK's stateless Streamable HTTP transport on exact `/mcp`
and exposes FormOwl OAuth routes on the same origin. The Project MCP and Wiki
MCP JSON-line commands, plus the hand-built semantic JSON-RPC runner, remain
test and local compatibility surfaces only.

The earlier TypeScript workspace has been removed by architecture decision. The canonical runnable contract model is the Python `formowl_contract` package.

The earlier Rust core and Python binding scaffold has been removed by architecture decision. Current hashing and diff helpers are pure Python utilities under `formowl_core`.

The Python packages now use a single `python/` package root so package discovery, test paths, and local PYTHONPATH setup do not need per-package roots.
```

---

## 5. Component Responsibilities

## 5.1 Project MCP

Project MCP provides project execution context from project management systems.

Initial target system:

```text id="io3tq7"
OpenProject
```

Future target systems:

```text id="5tovdn"
Jira
GitHub Issues
Linear
YouTrack
```

Project MCP owns:

```text id="o763bs"
Project lookup
Work item lookup
Work item context retrieval
Work item comments
Work item activities
Work item relations
Work item attachment metadata
Project status summary
Evidence snapshot creation for project queries
Project write proposals
```

Project MCP does not own:

```text id="90mcy1"
Wiki page generation
Markdown artifact lifecycle
Wiki publishing
Knowledge page review status
Long-form knowledge curation
```

---

## 5.2 Wiki MCP

Wiki MCP manages knowledge artifacts.

Wiki MCP must expose wiki work as natural-language and review-oriented operations. Users should not need to understand Git, branches, commits, pull requests, storage paths, schema IDs, or hash values to create, review, update, publish, or restore wiki content.

Initial target artifact format:

```text id="55bbyy"
Markdown
```

Future publishing targets:

```text id="zqz1yl"
OpenProject Wiki
Wiki.js
MkDocs
Docusaurus
Confluence
Notion
GitBook
```

Wiki MCP owns:

```text id="e8xxo9"
Markdown draft generation
Wiki page lookup
Wiki draft and revision lifecycle
Wiki page metadata
Citation embedding
Frontmatter generation
Publishing proposals
Wiki snapshot capture
Revisioned artifact store abstraction
Change comparison and restore proposals
Natural-language operation mapping
Canonical graph and user graph view lifecycle
```

Wiki MCP does not own:

```text id="p4wf6l"
OpenProject API details
Jira API details
Project status interpretation
Work item state mutation
Project adapter logic
User-facing Git operations
```

---

## 5.3 formowl-contract

`formowl-contract` is a shared schema package.

It defines portable objects used by both Project MCP and Wiki MCP.

Current core objects:

```text id="qv0xks"
SourceRef
ProjectRef
WorkItemRef
WikiPageRef
EvidenceSnapshot
EvidenceSnapshotRef
Citation
PermissionScope
ContextPackage
WikiRevision
MCPResultEnvelope
```

Target graph and ingestion objects:

```text
StorageBackend
Asset
AssetOccurrence
AssetRelationship
AssetLifecycleEvent
RetentionPolicy
Observation
SemanticMetadata
CandidateAtom
CandidateRelation
CandidateMention
CandidateFrame
CandidateBusinessObject
FusionCandidate
EntityResolutionProposal
EvidenceLink
CanonicalFrame
CanonicalAtom
CanonicalEntity
CanonicalRelation
ScopeAwareCanonicalGraph
EffectiveGraphView
MergeDecision
AtomGranularityPolicy
AtomLifecycleEvent
EntityResolutionEvent
RelationResolutionEvent
UserGraphAssemblyPolicy
UserKnowledgeGraphRevision
WikiProjectionSpec
IngestionJob
ExtractorRun
User
SessionIdentity
WorkspaceMember
AccessRequest
Grant
AuditLog
```

Both MCP servers must import or implement this contract.

No MCP server should depend on another MCP server's internal types.

---

## 5.4 Resource Extraction Layer

The Resource Extraction Layer converts registered managed Assets and governed
external source records into observations and semantic metadata.

For implementation-level details of multimedia extraction, extractor routing,
observation schemas, semantic metadata schemas, and adapter boundaries, see
`RESOURCE_EXTRACTION_SPEC.md`. That detailed specification must implement the
ingress, durable ObjectStore, Asset lifecycle, nested-resource, and Retrieval
Gateway boundaries defined here; it must not redefine `resources` as permanent
storage.

Supported resource families should include:

```text
audio
video
image
document
text
mail
project data
conversation
wiki source
```

Resource extraction owns:

```text
ingestion profile and extraction-job orchestration after Asset activation
MIME detection
extractor selection
observation creation
extractor metadata capture
location metadata capture such as timestamp, page, bounding box, frame, speaker, or section
attachment and embedded-member byte discovery
child Asset commit requests through the Storage, Deployment, and Worker Layer
parent-child and occurrence lineage metadata for nested resources
MIME-based child extractor routing after child Asset activation
re-extraction when extractor versions or extraction policies change
```

Resource extraction does not own:

```text
storage backend selection or registration
durable object commit, verification, or ingress cleanup
Asset, occurrence, relationship, lifecycle, retention, or purge persistence
original-file preview or download delivery
final atom granularity
canonical entity merges
canonical relation commits
user graph assembly
wiki page generation
```

All extractor output must remain derived data until reviewed or committed through the graph assembly workflow.

Resource extraction must run from registered assets and object references, not
from arbitrary storage paths. A local `resources` folder may feed the Storage
layer's ingress adapter, but an extractor must not open that folder as its
source. After durable object commit and Asset activation, workers resolve the
managed object through `asset_id` and internal `object_uri`. Raw storage
locations are implementation details behind `StorageBackend`, `AssetStore`,
and `ObjectStore`.

---

## 5.5 Knowledge Graph Assembly Layer

The Knowledge Graph Assembly Layer converts observations and semantic metadata into governed graph state.

The assembly flow is:

```text
Observation
  -> CandidateAtom / CandidateRelation
  -> Granularity policy
  -> Entity resolution
  -> Relation resolution
  -> CanonicalAtom / CanonicalEntity / CanonicalRelation
  -> UserKnowledgeGraphRevision
```

Graph assembly owns:

```text
candidate graph preview
granularity policy enforcement
entity resolution
relation resolution
canonical graph commits
atom lifecycle events
user graph assembly policies
graph revision lineage
```

Graph assembly must treat external extractor and LLM graph outputs as proposals. It must not trust them as canonical graph state.

Canonical graph state is scope-aware. A canonical entity or relation may be canonical within an owner graph, workspace graph, project graph, customer graph, or grant-scoped shared fragment without being globally canonical across every FormOwl scope.

Cross-scope fusion must not default to permanent merge. The default output of cross-scope fusion should be an equivalence proposal, same-as candidate, related-to candidate, overlay grant, or temporary effective view. A stronger canonical merge across scopes requires explicit governance, owner or maintainer approval where applicable, evidence review, permission inheritance review, revocation behavior review, and audit logging.

Entity matching, access overlay, and canonical merge are separate stages:

```text
A match proposal does not imply data access.
Data access does not imply canonical merge.
Canonical merge does not automatically grant raw data access.
```

Graph assembly may generate match proposals from deterministic keys, fuzzy matching, probabilistic linkage, semantic similarity, or manual hints, but those proposals must not expose private evidence or mutate canonical graph state. Access overlays use `AccessRequest`, `Grant`, permission scope, visibility scope, expiration, access count, and audit policy. Canonical merges are stronger operations that change graph state inside a target scope and must record a merge decision.

---

## 5.6 Governance and Policy Layer

Governance crosses every layer of the system.

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

The Governance and Policy Layer controls:

```text
which resources may be extracted
how extracted data becomes observations
what counts as one atom
when to split, merge, supersede, deprecate, or archive graph objects
which entities and relations may be auto-accepted
which candidates require human review
which graph granularity different users or tasks should receive
how wiki artifacts are projected from graph views
```

---

## 5.7 Storage, Deployment, and Worker Layer

The Storage, Deployment, and Worker Layer keeps physical storage flexible while preserving centralized knowledge identity.

For normal managed ingestion, controlled local folders such as `resources`
serve only as ingress, quarantine, or processing workspaces. Accepted raw bytes
must be copied into a durable managed `ObjectStore`. Public AWS S3 is not
required: MinIO, another S3-compatible internal service, or a local
`FileObjectStore` in development may implement the same interface. Synology,
SMB, NFS, or another external source may be configured as a read-only reference
or import source, but it must not blur the distinction between ingress and the
managed authoritative object copy. A deployment that deliberately keeps an
external source as the only authoritative byte location requires an explicit
storage policy and must not be represented as the default managed-ingestion
path.

The layer owns:

```text
StorageBackend registry
Asset registration
ObjectStore adapters
ingress adapters
durable object commit and verification
quarantine and failed-ingress isolation
ingress cleanup after successful commit
AssetOccurrence and Asset relationship persistence
byte-level deduplication without permission merging
retention, legal hold, redaction, deletion, and purge orchestration
preview and download delivery behind the Retrieval Gateway
storage health tracking
worker locality metadata
local scratch policy
GPU worker capability metadata
backup and retention placement
```

PostgreSQL remains the source of truth for metadata, governance, permissions,
Asset and occurrence lineage, lifecycle, retention, audit, job state, and graph
state. The managed `ObjectStore` remains the source of bytes for active Assets
and large derived artifacts. PostgreSQL should run on local SSD, NVMe, or
reliable block storage, not ordinary NAS, SMB, WebDAV, or NFS-mounted storage.

Workers process registered assets by `asset_id` and internal `object_uri`.
Large files may be copied from ObjectStore to local scratch before parsing.
Scratch is disposable and must be cleaned after the run. Worker locality
affects performance and scheduling, but it must not fragment Asset, occurrence,
or graph identity.

## 5.8 Identity, Access, and MCP Gateway Layer

For the internal closed beta, the sole connected human identity path is:

```text
public HTTPS /mcp
  -> OAuth protected-resource challenge
  -> FormOwl OAuth 2.1 authorization endpoint
  -> PKCE S256 and exact ChatGPT callback/resource validation
  -> Google OIDC authorization and callback
  -> verified Google (issuer, subject, email) mapping through a FormOwl invitation
  -> resource-bound FormOwl access token
  -> server-side token-session, user, membership, grant, and revocation lookup
  -> fresh ActorContext
  -> protected MCP tool
```

Google access tokens and Google ID tokens are never FormOwl MCP bearer tokens.
Google is the upstream authentication provider; FormOwl remains the OAuth
authorization server and the authority for users, workspace membership, grants,
client authorization, token-session state, revocation, and audit.

The predefined ChatGPT OAuth client must use PKCE S256, an exact registered
redirect URI, and the exact canonical FormOwl resource. The connected runtime
must use HTTPS except for explicit loopback-only tests. It must reject
caller-controlled user, workspace, session, grant, storage, parser, and worker
identity fields.

The predefined client ID is one stable non-secret value selected and recorded
by the deployment operator before discovery. ChatGPT app management must use
that exact value if its current predefined-client UI supports entry or
selection; if it does not, the live flow stops as an external blocker. ChatGPT
supplies and displays only the exact production callback
`https://chatgpt.com/connector/oauth/{callback_id}`. Operators must not invent
the client ID, claim that ChatGPT generated or displayed it, or silently
substitute another registration model.

Production FormOwl access tokens use a fixed 3600-second lifetime and a fixed
30-second validation clock skew. Expiry evidence must wait until trusted UTC is
strictly later than `expires_at + 30 seconds`.

The connected service uses the official MCP SDK's stateless Streamable HTTP
transport on exact `/mcp`. OAuth protected-resource metadata,
authorization-server metadata, JWKS, authorization routes, and `/mcp` must
agree on the same canonical public HTTPS origin.

On each protected tool call, the MCP Gateway verifies the FormOwl token, reloads
the token session and current authorization state from PostgreSQL, and builds a
fresh `ActorContext`. `ActorContext` carries the FormOwl user, external identity,
OAuth client and token-session lineage, current workspace and role, memberships,
and active grants. Authentication does not by itself authorize an Asset, raw
byte stream, graph fragment, or canonical mutation.

`ManualTrustedInternalAuthProvider`, the hand-built JSON-RPC runner, JSON-line
commands, and stdio session environment variables remain available only for
tests and local compatibility. They are not valid connected deployment modes
and must not be documented as a ChatGPT connection method.

Even in Phase 0, FormOwl must model:

```text
User
SessionIdentity
WorkspaceMember
ExternalIdentity
OAuthInvitation
OAuthOwnerBootstrap
OAuthClientAuthorization
OAuthTransaction
OAuthAuthorizationCode
OAuthTokenSession
ActorContext
AccessRequest
Grant
AuditLog
```

Cross-user graph collaboration is implemented through permissioned effective graph views, not silent graph merges. Sharing levels should include answer-only, graph snippet, evidence snippet, and controlled raw asset access. Raw access must use FormOwl locators such as `formowl://asset/{asset_id}` and must be checked by the MCP Gateway and Retrieval Gateway before any content is returned.

---

## 6. Shared Data Types

## 6.1 SourceRef

`SourceRef` identifies an object in an external source system.

Example for OpenProject:

```json id="fw7kp3"
{
  "source_system": "openproject",
  "source_instance": "markliou-openproject",
  "source_type": "work_package",
  "source_id": "123",
  "source_key": "OP-123",
  "source_url": "https://openproject.example.com/work_packages/123"
}
```

Example for Jira:

```json id="bemlqg"
{
  "source_system": "jira",
  "source_instance": "team-a-jira",
  "source_type": "issue",
  "source_id": "10001",
  "source_key": "ABC-456",
  "source_url": "https://jira.example.com/browse/ABC-456"
}
```

Required fields:

```text id="vny9eh"
source_system
source_type
source_id
```

Optional fields:

```text id="u3e2mf"
source_instance
source_key
source_url
```

---

## 6.2 EvidenceSnapshot

`EvidenceSnapshot` records the external data retrieved by an MCP tool call.

It is used when retrieved project or wiki data is later used to generate a knowledge artifact.

Example:

```json id="5xp9s7"
{
  "evidence_snapshot_id": "ev_project_20260616_001",
  "mcp_server": "project-mcp",
  "tool_name": "get_work_item_context",
  "requested_by": "person_yifan",
  "source_account_id": "chatgpt:yifanliou@gmail.com",
  "captured_at": "2026-06-16T12:00:00+08:00",
  "permission_scope": {
    "scope_type": "project",
    "scope_id": "formowl",
    "visibility": "restricted"
  },
  "source_refs": [
    {
      "source_system": "openproject",
      "source_type": "work_package",
      "source_id": "123"
    }
  ],
  "request_hash": "sha256:...",
  "response_hash": "sha256:...",
  "evidence_asset_id": "asset_evidence_project_20260616_001",
  "storage_locator": "formowl://asset/asset_evidence_project_20260616_001"
}
```

Recommended internal ObjectStore prefix shape:

```text id="injjtr"
evidence/{tenant_id}/{workspace_id}/{yyyy}/{mm}/{dd}/{evidence_snapshot_id}/
  request.json
  response.json
  normalized.md
  metadata.json
```

This prefix is an internal adapter detail. Public responses expose the
`evidence_snapshot_id`, the registered evidence Asset when one exists, and
permission-checked FormOwl locators. They must not expose a local filesystem
path, bucket name, object key, or storage credential.

---

## 6.3 Citation

A `Citation` links generated content back to a source.

```json id="olwr4r"
{
  "citation_id": "cit_001",
  "source_ref": {
    "source_system": "openproject",
    "source_type": "work_package",
    "source_id": "123"
  },
  "evidence_snapshot_id": "ev_project_20260616_001",
  "locator": {
    "type": "comment",
    "id": "activity_456"
  },
  "summary": "The work package discussion describes the retention requirement."
}
```

Rules:

```text id="ncm2lc"
Generated wiki drafts must include citations.
Citations should reference SourceRef and EvidenceSnapshot when available.
Long direct quotes should be avoided.
```

---

## 6.4 PermissionScope

`PermissionScope` describes who should be allowed to access the retrieved or generated data.

```json id="x62rtf"
{
  "scope_type": "project",
  "scope_id": "formowl",
  "visibility": "restricted",
  "inherited_from": "openproject:project:formowl"
}
```

Common scope types:

```text id="qn9q0m"
private_user
project
team
workspace
public
restricted
unknown
```

---

## 6.5 ContextPackage

`ContextPackage` is the portable data package passed between MCP tools or manually copied between workflow stages.

```json id="q8qorj"
{
  "context_package_id": "ctx_project_20260616_001",
  "context_type": "work_item_context",
  "context_markdown": "...",
  "source_refs": [
    {
      "source_system": "openproject",
      "source_type": "work_package",
      "source_id": "123"
    }
  ],
  "evidence_snapshot_ids": ["ev_project_20260616_001"],
  "citations": [],
  "permission_scope": {
    "scope_type": "project",
    "scope_id": "formowl",
    "visibility": "restricted"
  }
}
```

---

## 6.6 WikiRevision

`WikiRevision` records one versioned state of a wiki artifact.

It is a governance object for knowledge views. It does not make the wiki page a source of truth. It records which raw evidence, source references, human actions, and backend revision were involved in producing a specific version of a page.

Git may be one backend for a `WikiRevision`, but it is only an implementation detail. A user-facing workflow should expose actions such as save draft, submit for review, compare changes, publish, refresh from sources, and restore.

Example:

```json id="wiki-revision-example"
{
  "revision_id": "rev_wiki_20260616_001",
  "page_ref": {
    "source_system": "markdown-store",
    "source_type": "markdown_page",
    "source_id": "adr-data-retention"
  },
  "parent_revision_id": "rev_wiki_20260615_001",
  "title": "Data Retention Architecture Decision",
  "status": "reviewed",
  "change_kind": "source_refresh",
  "markdown_hash": "sha256:...",
  "source_refs": [
    {
      "source_system": "openproject",
      "source_type": "work_package",
      "source_id": "123"
    }
  ],
  "evidence_snapshot_ids": ["ev_project_20260616_001"],
  "author_id": "person_admin_owner",
  "reviewer_id": "person_process_reviewer",
  "created_at": "2026-06-16T12:00:00+08:00",
  "backend_ref": {
    "type": "database",
    "id": "wiki_revision_rows/123"
  }
}
```

Recommended statuses:

```text id="wiki-revision-statuses"
draft
reviewed
published
archived
```

Recommended change kinds:

```text id="wiki-change-kinds"
generated
regenerated
human_edit
source_refresh
publish_sync
restore
```

Recommended backend types:

```text id="wiki-backend-types"
database
git
markdown-store
openproject_wiki
confluence
notion
```

Rules:

```text id="wiki-revision-rules"
Reviewed and published wiki revisions must be immutable.
Draft revisions may be superseded, but must not overwrite reviewed or published revisions.
Refresh from raw data must create a new draft revision and a human-readable diff.
Restore must create a new revision that records the restored parent, not delete history.
Backend identifiers such as git commits must not be required in user-facing workflows.
```

---

## 6.7 MCPResultEnvelope

All MCP tool responses should follow a shared envelope format.

```json id="k01xam"
{
  "result_type": "work_item_context",
  "status": "ok",
  "data": {},
  "context_package": {},
  "source_refs": [],
  "evidence_snapshot_ids": [],
  "citations": [],
  "permission_scope": {},
  "warnings": []
}
```

Possible statuses:

```text id="k9yed0"
ok
partial
not_found
permission_denied
pending_review
error
```

---

## 6.8 StorageBackend and Asset

`StorageBackend` describes a physical or logical storage role. The role is
separate from the vendor or protocol:

```text
ingress -> accepts unstable or newly supplied bytes for bounded processing
quarantine -> isolates rejected, suspicious, or failed input
authoritative_object_store -> holds managed Asset bytes and large derived artifacts
external_reference -> identifies a governed read-only source that is not a FormOwl inbox
scratch -> disposable worker-local processing space
```

The default managed-ingestion path is:

```text
controlled resources/inbox or UploadSession body
  -> stability, size, type, and security checks
  -> content hash
  -> durable write to authoritative ObjectStore
  -> read-after-write or checksum verification
  -> Asset and AssetOccurrence registration in PostgreSQL
  -> required audit commit
  -> ingress cleanup
  -> IngestionJob / ExtractorRun
```

Extraction may begin only after the policy-required durable commit point.
Parsing directly from bounded staging is allowed only when the same transaction
or recovery protocol guarantees that accepted Asset bytes are durably committed
and that failure cannot leave successful metadata pointing to missing bytes.

Recommended fields:

```text
storage_backend_id
type: s3_compatible | minio | local_object_store | synology_smb | synology_nfs | external_reference | ingress_only | scratch
role: authoritative_object_store | external_reference | ingress | quarantine | scratch
display_name
internal_endpoint
root_prefix
access_mode: read_only | read_write | ingress_only | disposable
trust_level
tenant_scope
workspace_scope
health_status
bandwidth_class
latency_class
allowed_workers
```

`internal_endpoint` and `root_prefix` are configuration secrets or internal
deployment metadata. They must not appear in normal MCP results.

`Asset` describes one governed raw or derived resource identity. It is the
stable identity used by extraction, graph, search, and wiki projection layers.
An Asset is not a path and is not defined by the contents of the ingress folder.

Recommended fields:

```text
asset_id
tenant_id
workspace_id
owner_scope_type
owner_scope_id
storage_backend_id
object_uri
content_hash
file_size
mime_type
original_filename
created_at
registered_at
owner_user_id
permission_scope
lifecycle_state
retention_policy_id
retention_until
legal_hold
redacted_at
purged_at
```

`object_uri` is an internal adapter locator. The public locator for an Asset is
`formowl://asset/{asset_id}`. Knowledge and MCP records must not use an S3 URL,
bucket/key pair, NAS path, local path, or ingress filename as Asset identity.

`AssetOccurrence` records each governed appearance or acquisition of an Asset.
Identical bytes may share an immutable storage blob at the ObjectStore adapter
layer while retaining separate Asset identities and occurrences, owners,
permissions, source relationships, import sessions, and retention decisions.

Recommended fields:

```text
asset_occurrence_id
asset_id
tenant_id
workspace_id
owner_scope_type
owner_scope_id
source_ref
source_parent_asset_id optional
source_parent_occurrence_id optional
relationship_type: uploaded_as | attached_to | embedded_in | exported_from | captured_from | derived_from
source_message_id optional
source_attachment_occurrence_id optional
source_import_session_id optional
permission_scope
created_at
```

`AssetRelationship` represents parent-child or derived-resource lineage without
requiring two resources to share authorization:

```text
asset_relationship_id
from_asset_id
to_asset_id
relationship_type
source_occurrence_id
source_observation_id optional
created_at
```

`AssetLifecycleEvent` records every governed transition without rewriting
history:

```text
asset_lifecycle_event_id
asset_id
from_state
to_state
reason
policy_id optional
actor_user_id or service_actor_id
audit_event_id
occurred_at
```

`RetentionPolicy` governs the durable managed copy independently of ingress and
scratch cleanup:

```text
retention_policy_id
tenant_id
workspace_id optional
retention_period
retention_basis
legal_hold_behavior
redaction_behavior
purge_behavior
created_by
created_at
```

Byte deduplication and authorization must remain separate:

```text
same content_hash -> storage implementation may reuse one immutable byte object
same content_hash -> does not merge Asset ids, owner scope, permission scope, grants, retention, or occurrences
same attachment in multiple messages -> preserves every attachment occurrence and parent relationship
```

Recommended Asset lifecycle states:

```text
staged
active
quarantined
retention_hold
redacted
pending_purge
purged
superseded
```

Ingress cleanup and Asset retention are separate decisions:

```text
Ingress cleanup removes the temporary resources/inbox or upload-staging copy.
Asset retention governs the durable ObjectStore copy.
Worker scratch cleanup removes disposable parser-local copies.
Purge removes or cryptographically invalidates durable bytes only after policy,
authorization, legal-hold, lineage, and audit checks succeed.
```

For nested resources such as email attachments, archive members, and embedded
documents, the parser must create a child Asset and AssetOccurrence, preserve
the parent relationship, and route the child by detected MIME type. The
ObjectStore adapter may reuse an immutable byte blob by content hash, but that
optimization must not replace the child Asset or occurrence:

```text
PDF / DOCX / PPTX / XLSX -> document or tabular extractor
image -> image / OCR extractor
audio / video -> media extractor
MSG / EML / message/rfc822 -> mail extractor
unknown or unsafe -> quarantine or metadata-only observation according to policy
```

Normal retrieval resolves observations, evidence snippets, and citations.
Original-file access is a stronger operation:

```text
requester -> MCP Gateway ActorContext
  -> Retrieval Gateway
  -> Asset, occurrence, lifecycle, retention, and Grant checks
  -> audit
  -> bounded stream, preview rendition, or short-lived opaque gateway URL
```

ObjectStore signed URLs may be used only as internal delivery primitives. If a
provider URL reveals bucket names, object keys, internal endpoints, or storage
topology, the Retrieval Gateway must proxy it rather than return it to the
caller. User-facing download capabilities must be short-lived, opaque, scoped
to one Asset and operation, and must not expose object-store credentials or
administrative endpoints.

The canonical graph must not reference raw storage paths. It should reference
`asset_id`, `asset_occurrence_id`, `observation_id`, `extractor_run_id`,
`evidence_id`, `entity_id`, `relation_id`, `workspace_id`, `user_id`, and
`grant_id` where applicable.

## 6.9 Identity, OAuth Session, AccessRequest, Grant, and AuditLog

Minimum connected identity objects:

```text
User
- user_id
- display_name
- email
- status: active | disabled
- created_at

SessionIdentity
- session_id
- selected_user_id
- selected_at
- selection_method: google_oidc_oauth

WorkspaceMember
- workspace_id
- user_id
- role: owner | member | viewer

ExternalIdentity
- external_identity_id
- provider: google
- issuer
- subject
- user_id
- verified email
- status: active | disabled

OAuthInvitation / OAuthOwnerBootstrap
- invitation or bootstrap id
- normalized invited email
- workspace and role
- status and expiry
- operator or inviting-owner attribution

OAuthClientAuthorization
- predefined client id
- user and external identity
- granted scopes
- default workspace
- revocation state

OAuthTransaction / OAuthAuthorizationCode
- exact client, callback, resource, and scopes
- PKCE S256 challenge
- one-way state/code/nonce bindings
- expiry and one-time consumption state

OAuthTokenSession
- token_session_id
- user, external identity, client authorization, and workspace lineage
- resource and scopes
- one-way token-jti binding
- issue, expiry, and revocation state
```

`manual_trusted_internal` remains a valid `SessionIdentity.selection_method`
only for tests and local compatibility. A connected request must resolve to
`google_oidc_oauth` and must never accept user or workspace selection from the
MCP caller.

Access governance objects:

```text
AccessRequest
- request_id
- requester_user_id
- owner_user_id
- requested_scope_type
- requested_scope_id
- requested_access_level
- reason
- status: pending | approved | denied | expired
- created_at
- resolved_at

Grant
- grant_id
- owner_user_id
- grantee_user_id
- scope_type
- scope_id
- permission
- expires_at
- max_access_count optional
- revoked_at

AuditLog
- audit_log_id
- actor_type: user | service | external_unauthenticated
- actor_user_id optional according to actor_type
- actor_service_id optional according to actor_type
- action
- target_type
- target_id
- grant_id optional
- session_id
- workspace_id optional
- external_identity_id optional
- oauth_client_id optional
- oauth_token_session_id optional
- request_id optional
- tool_call_id optional
- reason_code
- timestamp
```

Authentication must be replaceable:

```text
AuthProvider
- authenticate(request): AuthenticatedIdentity
- resolve_user(identity): User
```

Connected provider and bridge:

```text
GoogleOidcClient
FormOwlOAuthBridge
PostgreSQLOAuthRepository
FormOwlTokenCodec
```

Google OIDC is the sole upstream human identity provider for the current
connected closed beta. Later providers may include Microsoft Entra OIDC, SAML,
or external tenant providers only after a separate architecture decision.
Authorization, grants, provenance, and audit remain FormOwl authority and must
not depend on Google group or storage semantics.

---

## 7. Project MCP Tools

## 7.1 search_work_items

Search work items.

Input:

```json id="flq3ve"
{
  "query": "retention policy",
  "project_ref": {
    "source_system": "openproject",
    "source_type": "project",
    "source_id": "formowl"
  },
  "limit": 10
}
```

Output:

```json id="ufxor3"
{
  "result_type": "work_item_search_results",
  "status": "ok",
  "data": {
    "items": []
  },
  "source_refs": [],
  "evidence_snapshot_ids": [],
  "citations": []
}
```

---

## 7.2 get_work_item

Retrieve one work item.

Input:

```json id="sjzgx3"
{
  "source_ref": {
    "source_system": "openproject",
    "source_type": "work_package",
    "source_id": "123"
  }
}
```

Output data should include:

```text id="zctvvn"
title
description
status
type
priority
assignee
responsible
start_date
due_date
updated_at
source_url
source_ref
```

---

## 7.3 get_work_item_context

Retrieve work item context suitable for ChatGPT or another LLM.

Input:

```json id="2loeb7"
{
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
```

Output:

```json id="2knh66"
{
  "result_type": "work_item_context",
  "status": "ok",
  "data": {
    "work_item": {},
    "comments": [],
    "activities": [],
    "relations": [],
    "attachments": []
  },
  "context_package": {
    "context_package_id": "ctx_project_20260616_001",
    "context_type": "work_item_context",
    "context_markdown": "...",
    "source_refs": [
      {
        "source_system": "openproject",
        "source_type": "work_package",
        "source_id": "123"
      }
    ],
    "evidence_snapshot_ids": ["ev_project_20260616_001"],
    "citations": []
  }
}
```

---

## 7.4 list_work_item_activities

Retrieve comments and activity history for a work item.

Input:

```json id="ha9io5"
{
  "source_ref": {
    "source_system": "openproject",
    "source_type": "work_package",
    "source_id": "123"
  },
  "limit": 50,
  "create_evidence_snapshot": true
}
```

---

## 7.5 list_work_item_relations

Retrieve related work items.

Input:

```json id="c5jp95"
{
  "source_ref": {
    "source_system": "openproject",
    "source_type": "work_package",
    "source_id": "123"
  }
}
```

---

## 7.6 get_project_status

Retrieve project-level status summary.

Input:

```json id="v0y0m7"
{
  "project_ref": {
    "source_system": "openproject",
    "source_type": "project",
    "source_id": "formowl"
  },
  "include_recent_updates": true,
  "create_evidence_snapshot": true
}
```

---

## 7.7 propose_work_item_comment

Prepare a project-system comment write proposal.

This tool must not write directly.

Input:

```json id="btxggc"
{
  "source_ref": {
    "source_system": "openproject",
    "source_type": "work_package",
    "source_id": "123"
  },
  "body": "Proposed comment text",
  "reason": "Generated from reviewed wiki draft"
}
```

Output:

```json id="twogq8"
{
  "result_type": "write_proposal",
  "status": "pending_review",
  "data": {
    "proposal_id": "proposal_comment_001",
    "target_source_ref": {
      "source_system": "openproject",
      "source_type": "work_package",
      "source_id": "123"
    },
    "diff_markdown": "..."
  }
}
```

---

## 8. Wiki MCP Tools

## 8.1 search_wiki_pages

Search existing wiki or markdown pages.

Input:

```json id="ddp37i"
{
  "query": "retention architecture",
  "project": "formowl",
  "limit": 10
}
```

---

## 8.2 get_wiki_page

Retrieve one wiki or markdown page.

Input:

```json id="xgjwgd"
{
  "page_ref": {
    "wiki_system": "markdown-store",
    "page_id": "adr-data-retention"
  }
}
```

---

## 8.3 generate_wiki_draft

Generate a markdown draft from a context package.

Input:

```json id="ci02tc"
{
  "page_type": "adr",
  "title": "Data Retention Architecture Decision",
  "context_package": {
    "context_package_id": "ctx_project_20260616_001",
    "context_type": "work_item_context",
    "context_markdown": "...",
    "source_refs": [
      {
        "source_system": "openproject",
        "source_type": "work_package",
        "source_id": "123"
      }
    ],
    "evidence_snapshot_ids": ["ev_project_20260616_001"],
    "citations": []
  }
}
```

Output:

```json id="e3hitw"
{
  "result_type": "wiki_draft",
  "status": "ok",
  "data": {
    "draft_id": "draft_adr_001",
    "markdown": "...",
    "frontmatter": {}
  },
  "source_refs": [
    {
      "source_system": "openproject",
      "source_type": "work_package",
      "source_id": "123"
    }
  ],
  "evidence_snapshot_ids": ["ev_project_20260616_001"],
  "citations": []
}
```

---

## 8.4 update_wiki_draft

Update an existing markdown draft.

Input:

```json id="vk0eri"
{
  "draft_id": "draft_adr_001",
  "patch": {
    "status": "reviewed",
    "content": "..."
  }
}
```

---

## 8.5 publish_wiki_page

Prepare a wiki publishing proposal.

This tool must not publish directly unless explicit auto-publish mode is configured.

Input:

```json id="4uph5b"
{
  "draft_id": "draft_adr_001",
  "target": {
    "target_system": "openproject_wiki",
    "project_id": "formowl",
    "page_slug": "data-retention-architecture"
  },
  "require_review": true
}
```

Output:

```json id="ppbpz5"
{
  "result_type": "publish_proposal",
  "status": "pending_review",
  "data": {
    "proposal_id": "publish_proposal_001",
    "target": {
      "target_system": "openproject_wiki",
      "project_id": "formowl",
      "page_slug": "data-retention-architecture"
    },
    "diff_markdown": "..."
  }
}
```

---

## 8.6 capture_wiki_snapshot

Capture a wiki page as raw source.

Input:

```json id="y9xn2q"
{
  "page_ref": {
    "wiki_system": "openproject_wiki",
    "page_id": "data-retention-architecture"
  }
}
```

---

## 8.7 Wiki Revision Governance

Wiki MCP must treat wiki revisions as governed knowledge views.

The user-facing operation should be natural-language-first. The system may translate requests into structured tool calls, but users should be able to express work like:

```text id="wiki-natural-language-ops"
Update this SOP using the latest OpenProject discussion.
Show me what changed before I approve it.
Publish this reviewed page to the project wiki.
Restore the previous approved version.
Refresh this page from source data, but keep my manual notes.
```

These user actions map to technical operations behind the scenes:

```text id="wiki-op-mapping"
save draft -> create or update a draft WikiRevision
submit for review -> mark a draft revision pending review
compare changes -> generate a human-readable diff between revisions
approve -> mark a revision reviewed
publish -> create a publish proposal and record the target backend revision
refresh from sources -> generate a new draft revision from raw evidence and show a diff
restore -> create a new revision from a previous reviewed or published revision
```

Future Wiki MCP tools may include:

```text id="wiki-future-revision-tools"
list_wiki_revisions
compare_wiki_revisions
propose_wiki_refresh
restore_wiki_revision
```

The current Wiki MCP implementation may model these through `generate_wiki_draft`, `update_wiki_draft`, `publish_wiki_page`, and an internal revision store. Graph-aware implementations should also record projection specs, user graph revisions, included atoms, and generator policy.

Git-specific operations such as commit, branch, pull request, merge, or rebase must not be required from normal wiki authors. If Git is used, the system should create commits or pull requests on behalf of the workflow and expose them only as optional audit details.

---

## 9. Multimodal Knowledge Graph and Wiki Projection Model

Wiki specifications must distinguish between managed source Assets or governed
external source records, observations, candidate knowledge, reusable canonical
graph parts, user knowledge graphs, and published wiki artifacts.

The system must not assume that one source document, work item, meeting recording, image, ChatGPT session, or wiki page has one correct knowledge graph. Different users may read the same evidence with different goals, attention, terminology, and preferred granularity. A project owner may want a coarse operational summary. A reviewer may care about policy exceptions. An engineer may inspect method details. These are all valid derived views if their provenance is preserved.

This chapter defines the model boundary. It requires the architecture to support the full pipeline even when a particular deployment implements only part of it.

## 9.1 Layered Knowledge Model

The knowledge model has seven layers:

```text id="knowledge-graph-layers"
Managed source resource: Asset or governed external SourceRef
AssetOccurrence / AssetRelationship / EvidenceSnapshot / Citation
Observation / SemanticMetadata
Candidate graph
Governed canonical graph
User knowledge graph
WikiProjection / WikiRevision
```

Layer responsibilities:

```text id="knowledge-layer-responsibilities"
Managed source resource -> verified durable Asset bytes in ObjectStore, or an explicitly governed external source record when policy permits reference-only access.
AssetOccurrence / AssetRelationship / EvidenceSnapshot / Citation -> Asset identity, acquisition and parent-child lineage, traceable captured evidence, and permission-checked source locators.
Observation / SemanticMetadata -> normalized extracted facts, spans, scenes, blocks, transcripts, OCR, captions, and semantic hints.
Candidate graph -> proposed atoms and relations that have not yet passed governance.
Governed canonical graph -> source-grounded reusable atoms, entities, relations, and lifecycle mappings.
User knowledge graph -> a user's versioned assembly, filtering, grouping, labeling, weighting, and permission-aware view of canonical and user-authored knowledge.
WikiProjection / WikiRevision -> a governed output artifact such as a markdown page or published wiki page generated from a graph view and source evidence.
```

`WikiRevision` is output governance. It records a versioned artifact. It must not be overloaded to become the user's full knowledge graph.

## 9.1.1 Observation and Semantic Metadata

All resource extractors should produce `Observation` records before graph assembly.

An `Observation` is a normalized description of something found in a managed
Asset or governed external source record. Examples include transcript segments,
video scenes, OCR blocks, document paragraphs, page regions, issue comments,
wiki sections, or ChatGPT messages.

An observation should carry:

```text
observation_id
asset_id or evidence_snapshot_id
type
modality
text, caption, structured payload, or extracted value
location metadata such as timestamp, page, bounding box, frame, speaker, section, or message sequence
extractor name, version, model, and run id
confidence
permission_scope
created_at
```

`SemanticMetadata` records optional structured interpretations extracted from observations, such as entities, relations, claims, decisions, action items, topics, events, requirements, risks, deadlines, owners, and unresolved questions.

Observation and semantic metadata are not canonical truth. They are the substrate for candidate graph generation.

## 9.1.2 Candidate Graph

External extractors, LLM tools, rule-based processors, and user imports may produce graph-shaped output, but that output must first enter a candidate graph.

Candidate graph objects should include:

```text
CandidateAtom
CandidateRelation
CandidateEntityMention
CandidateMention
CandidateFrame
CandidateBusinessObject
ExternalGraphImport
```

Candidate atoms and relations represent possible knowledge units and links. They must record source observations, extractor metadata, confidence, proposed atom type, proposed granularity, and review state.

Coordination-frame candidates represent enterprise coordination obligations
such as requests, commitments, decisions, blockers, deadlines, dependencies,
status changes, and open questions. A `CandidateFrame` should carry a stable
frame type, named slots, evidence spans, domain hints, access boundary,
granularity level, ontology revision id, source mention ids, linked candidate
business object ids, confidence, and review state. It is still a candidate
proposal and must not bypass canonical graph governance.

Candidate graph state may be previewed, rejected, split, merged, revised, or committed. It must not be silently promoted to canonical graph state.

## 9.2 Canonical Atom Model

A canonical atom is the smallest useful, source-grounded knowledge part that the system can cite, compare, reuse, and assemble.

Atoms may represent:

```text id="canonical-atom-types"
concept
definition
claim
decision
requirement
assumption
constraint
method_step
evidence_span
risk
open_question
exception
relationship
```

Future contract objects may include:

```text id="future-atom-contract-objects"
CanonicalAtom
CanonicalEntity
CanonicalRelation
CanonicalGraphRevision
CandidateAtom
CandidateRelation
TypeDefinition
TypeAlias
TypeMapping
TypeAlignmentCandidate
Observation
SemanticMetadata
ExtractionPolicy
AtomGranularityPolicy
OntologyPolicy
AtomLifecycleEvent
EntityResolutionEvent
RelationResolutionEvent
```

A future `CanonicalAtom` should carry at least:

```text id="knowledge-atom-minimum-fields"
atom_id
atom_type
canonical_text or normalized_summary
granularity_level
status
source_candidate_atom_ids
source_observation_ids
source_refs
evidence_snapshot_ids
citations
content_hash
extraction_policy_id
granularity_policy_id
confidence
created_at
```

Optional fields may include:

```text id="knowledge-atom-optional-fields"
parent_atom_ids
child_atom_ids
related_atom_ids
granularity_level
confidence
labels
language
domain
metadata
```

Canonical atoms are not a company-wide ontology. They are source-grounded parts that can later be organized into many graphs. A canonical graph may include atoms, entities, and relations, but the presence of a canonical graph object must still be traceable to evidence, a committed candidate, or an explicit human modeling action.

Canonical graph commits should be explicit events. A commit should record which candidates were accepted, changed, split, merged, or rejected; which policies were used; which `ontology_revision_id` and atom graph revision were used for type-sensitive resolution; who or what approved the change; and which graph revision was created.

Canonical graph state is scoped. The following scopes may each have their own canonical state:

```text
owner graph
workspace graph
project graph
customer graph
grant-scoped shared graph fragment
```

Design rule:

```text
Canonical within a scope does not mean canonical across all scopes.
```

For example, `Client X` may be canonical inside User B's owner graph while only being a same-as candidate, related-to candidate, or temporary overlay inside a workspace or grant-scoped view. Cross-scope canonical merge is allowed only through an explicit governance workflow.

## 9.3 Atom Granularity Rules

The system must avoid both extremes:

```text id="atom-granularity-extremes"
Atoms that are too coarse cannot support user graph assembly.
Atoms that are too fine become noise and lose useful meaning.
```

An atom should normally satisfy these rules:

```text id="atom-granularity-rules"
It can be traced to source evidence.
It can be independently reviewed or corrected.
It can be assembled into a larger view.
It has enough context to remain understandable.
Splitting it further would not materially improve reuse, review, or user-specific assembly.
```

Granularity is domain-sensitive. The system may extract a method section more finely for one workflow and an introduction more finely for another, as long as the extraction policy and evidence trail are recorded.

## 9.4 Adaptive Atom Granularity Evolution

The definition of the smallest useful atom must evolve over time. It may change as source data changes, user goals change, user behavior accumulates, review feedback is collected, and better extraction or summarization policies are introduced.

The system must not allow atom graphs to drift toward unlimited fragmentation. Fine-grained atoms that are rarely used, repeatedly displayed together, or no longer improve retrieval, review, wiki generation, or user graph assembly should become candidates for coarsening or fusion.

Granularity evolution should be governed by explicit policies, not ad hoc rewrites. A future `AtomGranularityPolicy` should record:

```text id="atom-granularity-policy-fields"
policy_id
parent_policy_id
policy_version
scope
split_rules
merge_rules
archive_rules
usage_signal_window
review_requirements
created_at
```

Related algorithm families include:

```text id="granularity-related-algorithm-families"
Minimum Description Length for balancing model complexity against explanatory value.
Graph summarization for compact graph representations.
Graph coarsening for merging strongly related nodes into supernodes.
User-specific graph summarization based on targets or workloads.
Incremental graph summarization for updating summaries as graph data changes.
Concept drift detection for deciding when behavior or data distributions changed enough to revise policies.
Ontology evolution and graph alignment for mapping old concepts and atoms to new versions.
```

The system should treat atom granularity as an optimization problem with reviewable decisions:

```text id="granularity-decision-rules"
Split when the task value of finer atoms exceeds the added complexity, maintenance cost, and revision churn.
Merge when the simplicity gained by coarser atoms exceeds the loss of detail, query precision, and provenance clarity.
Archive when an atom is obsolete or unused but must remain addressable for historical reproducibility.
Supersede when a new atom or super-atom better represents the current model without deleting the old atom.
```

Potential split signals:

```text id="atom-split-signals"
Users repeatedly expand the same atom.
Different users manually split the same atom in similar ways.
Queries often target different internal parts of the atom.
The atom contains multiple separable claims, decisions, requirements, or method steps.
The atom carries multiple citations that support different subclaims.
Reviewers repeatedly request local edits inside the atom.
Generated wiki drafts often need only part of the atom.
```

Potential merge or coarsening signals:

```text id="atom-merge-signals"
Atoms are rarely accessed directly.
Atoms are almost always cited, displayed, or exported together.
Atoms are semantically near-duplicates.
Users repeatedly collapse or manually group the same atoms.
Fine-grained atoms do not improve retrieval, summarization, review, or wiki generation.
The maintenance cost of separate atoms exceeds their observed value.
```

Atom lifecycle changes must be represented as mappings, not destructive edits:

```text id="atom-lifecycle-relations"
split_into
merged_into
summarized_by
supersedes
deprecated_by
equivalent_to
derived_from
```

Old atoms must remain resolvable for any existing `WikiRevision`, `UserKnowledgeGraphRevision`, citation, or evidence trail that refers to them. New graph revisions may prefer the newer atom, split atoms, or merged super-atom.

Canonical graph evolution should be slower and more governed than user graph evolution. User behavior may provide evidence for a canonical policy change, but it should first affect that user's `UserGraphAssemblyPolicy` or create a reviewable canonical change proposal. The system must not silently rewrite every user's graph because one user's habits changed.

## 9.5 Entity and Relation Resolution

Entity resolution decides whether entity mentions in observations or candidate atoms refer to the same canonical entity.

Entity resolution should combine:

```text
exact alias match
normalized string match
embedding similarity
graph neighborhood similarity
type compatibility checks
RapidFuzz-style fuzzy string similarity
pgvector semantic similarity
Splink-style probabilistic record linkage for structured records
LLM-assisted adjudication for ambiguous cases
human review for low-confidence merges
```

Entity resolution must not rely only on LLM generation. It must record an `EntityResolutionEvent` or `EntityResolutionProposal` when a candidate entity is matched, rejected, aliased, split, deferred for review, or proposed as equivalent across scopes.

Entity matching must not grant access by itself. A match proposal such as `A.CustomerX may be the same as B.ClientX` may produce a `FusionCandidate`, `same_as_candidate`, `related_to_candidate`, score breakdown, and evidence links, but it must not reveal B's private evidence or raw data to A.

Access overlay is a separate stage. It decides whether a requester may see another scope's graph fragment, evidence snippet, or raw asset by using `AccessRequest`, `Grant`, `permission_scope`, `visibility_scope`, expiration, access count, and audit policy.

Canonical merge is a third stage. It changes canonical graph state within a target owner, workspace, project, or customer scope and should record:

```text
merge_decision_id
target_scope_type
target_scope_id
left_entity_id
right_entity_id
reviewer_user_id
approval_reason
evidence_ids
conflict_notes
created_at
```

A canonical merge must never be an accidental side effect of search, matching, or temporary sharing.

Relation resolution decides whether a candidate relation should enter the canonical graph.

Relation resolution should consider:

```text
relation type compatibility
subject and object canonical entity mapping
temporal validity
confidence score
contradiction with existing graph state
redundancy with existing relations
whether the relation is semantically rich enough to become an atom node
```

Some relations should be represented as nodes rather than simple edges. For example, a decision should usually be represented as:

```text
(:Team)-[:MADE]->(:Decision)-[:TARGETS]->(:Artifact)
```

instead of only:

```text
(:Team)-[:DECIDED_TO_BUILD]->(:Artifact)
```

This allows the decision to carry metadata, lifecycle state, sources, confidence, review history, and wiki revision references.

Relation resolution must record a `RelationResolutionEvent` when a candidate relation is accepted, rejected, converted into an atom, superseded, or deferred for review.

## 9.5.1 Scoped Emergent Ontology

FormOwl must not adopt a top-down company-wide ontology, but entity resolution, relation resolution, and wiki projection still require a type system. The type system is governed knowledge about types. It reuses the same candidate to governance to canonical pipeline as atoms, entities, and relations.

Design principles:

```text
The ontology is bottom-up and emergent, not a top-down global schema.
Type knowledge is governed exactly like atom knowledge: candidate -> governance -> canonical.
Types are scoped. A type may be canonical within one scope and only a candidate in another.
Types are versioned. Resolution decisions must be reproducible against a type revision.
Deterministic and statistical tools generate type candidates; an LLM only adjudicates ambiguity.
Nothing an LLM produces is committed automatically; it enters the candidate type store.
```

The type model has three tiers:

```text
Core types -> closed, small, stable; changed only by updating this specification.
Extension types -> open, scoped, candidate; extractors, LLMs, or users may propose them.
Promoted types -> governed extension types that are canonical within a scope and mapped to a core type.
```

Resolution behavior by tier:

```text
Core types -> the only hard gate for type compatibility checks.
Extension types -> soft signals and weights only; they never gate resolution.
Promoted types -> participate through their mapping to a core type.
```

The closed core starts with a minimal, domain-neutral set. Labels may align loosely to schema.org for interoperability, but the core stays small and closed. FormOwl must not import a large upper ontology in v1.

Entity core supertypes:

```text
Person
Organization
Project
Artifact
Document
Event
Concept
Location
```

Relation supertypes should reuse the reified relation model above. For example, a decision is modeled as a `Decision` node with source, lifecycle, confidence, and review metadata rather than only as a `DECIDED` edge. Atom types reuse the canonical atom type seed in section 9.2.

Type compatibility is evaluated on the core supertype lattice, not on exact type strings. Finer extension or promoted types contribute match weight, but never a hard veto. Two mentions are type-incompatible only when their core supertypes are incompatible.

Type knowledge is stored as governed objects:

```text
TypeDefinition -> a type concept: core, extension, or promoted
TypeAlias -> an alternate label for a type
TypeMapping -> a mapping from a promoted or extension type to a core supertype
TypeAlignmentCandidate -> a proposed equivalence between types across scopes
```

A future `TypeDefinition` should carry at least:

```text
type_id
tier
core_supertype_id
pref_label
alt_labels
broader_type_ids
narrower_type_ids
related_type_ids
scope
status
source_observation_ids
source_candidate_ids
confidence
ontology_revision_id
created_at
```

Type lifecycle changes must use mappings, not destructive edits:

```text
split_into
merged_into
supersedes
deprecated_by
equivalent_to
derived_from
```

Old type ids must remain resolvable for any committed atom, relation, wiki revision, or citation that referenced them.

The type vocabulary uses a lightweight SKOS-style shape: `pref_label`, `alt_labels`, and `broader` / `narrower` / `related` links. PostgreSQL remains the source of truth for the vocabulary. `alt_labels` also support entity resolution alias matching. RDFLib and standard SKOS files are optional export and interchange concerns only. FormOwl does not adopt OWL, RDFS formal reasoning, or a triplestore for v1.

Cross-scope type alignment follows the same separation as entity fusion:

```text
A type alignment proposal does not imply data access.
Data access does not imply a canonical type merge.
A canonical type merge changes type state within a target scope and must be governed.
```

For example, "Scope A Customer may be the same as Scope B Client" produces a `TypeAlignmentCandidate` with a score breakdown and evidence links. It must not auto-merge and must not expose a private scope's evidence.

Canonical graph commits must pin an `ontology_revision_id` alongside the atom graph revision when type compatibility influenced resolution. Graph-derived wiki frontmatter must record `ontology_revision_id` when types influenced the draft.

The ontology mechanism follows the deterministic-first policy from section 9.7.1. An LLM is the last-resort adjudicator and a candidate generator for new type labels, never the primary mechanism.

Recommended implementation policy:

```text
Vocabulary storage and representation -> PostgreSQL relational tables in SKOS shape.
Label normalization and alias matching -> Unicode normalization and RapidFuzz-style matching.
Core supertype classification -> rules and gazetteers first, then NER labels, then pgvector similarity against core-type prototypes.
Hierarchy suggestions -> embedding similarity, lexical overlap, and worker-side graph analysis.
Cross-scope type alignment -> embedding plus lexical candidates, then governance review.
Type-graph validation -> application code, database constraints, and pydantic schemas.
LLM role -> adjudicate low-confidence ambiguity and propose candidate labels only.
```

Heavy ontology alignment frameworks such as LogMap, AgreementMakerLight, and OAEI-style tooling are deferred. v1 uses lexical and embedding candidate generation with human or policy review.

The governed, versioned type system also supports later training tasks without adding a new structure:

```text
Versioned promoted types provide an auditable label taxonomy.
alt_labels provide an alias and normalization dataset.
TypeAlignmentCandidate decisions provide a record-linkage training signal.
Outputs of trained type classifiers remain candidates and never mutate canonical type state directly.
```

## 9.5.2 Coordination-Frame Ontology

The scoped type ontology is not enough by itself for enterprise coordination.
FormOwl also needs a stable coordination-frame core that can represent what
people request, commit, decide, block, depend on, escalate, and follow up
across email, meetings, documents, project issues, wiki pages, and chat
transcripts.

Ontology v2 is layered:

```text
Evidence/source ontology
+ stable coordination-frame core
+ scoped domain object packs
+ projection/view ontology
```

The coordination core should remain small and stable. Initial frame types are:

```text
Request
Commitment
Decision
Assignment
StatusUpdate
StatusChange
Blocker
Risk
Issue
OpenQuestion
Deadline
Dependency
Escalation
Change
Exception
Constraint
```

Domain packs may add business objects and domain process frames, but they must
extend the core rather than bypass it:

```text
CustomerRequest -> Request
InventoryShortage -> Blocker
InvoiceApproval -> Decision
FirmwareCapabilityQuestion -> OpenQuestion
ShipmentDelay -> Issue or Blocker
CustomerCommitment -> Commitment
```

The required candidate path is:

```text
Observation
  -> CandidateMention
  -> CandidateFrame
  -> CandidateBusinessObject
  -> CandidateRelation
  -> reviewed CanonicalFrame / CanonicalObject / CanonicalRelation
  -> UserKnowledgeGraphRevision
  -> WikiProjection
```

`CandidateFrame` is the central abstraction. It is where evidence spans,
permission scope, domain hints, obligation granularity, and named coordination
slots meet. Email must not become a special ontology; it is only one source
substrate that can emit the same coordination frames as meetings, documents,
project issues, and chat transcripts.

The current repository includes a deterministic issue #28 experiment under
`experiments/kg_ontology_v2_coordination/`. It is a synthetic candidate-layer
ablation and does not claim production email parsing, raw PST extraction,
canonical frame commits, canonical type writes, user graph mutation, or wiki
revision mutation.

## 9.6 User Knowledge Graphs

Each user may have one or more user knowledge graphs.

A user graph is a derived, versioned assembly of canonical atoms and user-authored additions. It may include:

```text id="user-graph-assembly-actions"
include atom
exclude atom
merge atoms
split view over atoms
rename or relabel atom
group atoms into a topic
assign importance or attention weight
choose coarse or fine granularity
add private note
add user-specific relation
pin preferred source or citation
```

Future contract objects may include:

```text id="future-user-graph-contract-objects"
UserGraphProfile
UserKnowledgeGraphRevision
UserGraphAssemblyPolicy
UserGraphNode
UserGraphEdge
```

A future `UserKnowledgeGraphRevision` should carry at least:

```text id="user-graph-revision-minimum-fields"
user_graph_revision_id
user_id or owner_scope
parent_user_graph_revision_id
atom_graph_revision_id
assembly_policy_id
source_refs
evidence_snapshot_ids
included_atom_ids
created_at
status
permission_scope
```

User graph revisions may change when:

```text id="user-graph-change-reasons"
source evidence changes
canonical atom extraction changes
the user's goal changes
the user's preferred granularity changes
the user manually edits grouping, labels, weights, or notes
```

The same raw data may therefore produce multiple valid user graph revisions at the same time.

## 9.7 Wiki Projection and Relationship to WikiRevision

A `WikiRevision` may be generated from:

```text id="wiki-revision-generation-sources"
ContextPackage
EvidenceSnapshot
canonical atom graph revision
user knowledge graph revision
manual human edits
```

Graph-aware wiki generation should be controlled by a `WikiProjectionSpec`.

A `WikiProjectionSpec` should define:

```text
projection_id
page_type
target entity or query
source graph revision or user graph revision
sections
section source such as entity_summary, graph_query, graph_neighbors, source_observations, or manual_notes
filters such as atom_type, status, permission_scope, relation_type, and confidence
generator policy
review requirements
```

When a wiki page is generated from a user graph, the frontmatter may include:

```yaml id="future-graph-frontmatter"
projection_spec_id: artifact_page_projection_v1
included_atom_ids:
  - atom_001
  - atom_002
atom_graph_revision_id: atom_graph_rev_20260616_001
ontology_revision_id: ontology_rev_workspace_formowl_20260616_001
atom_extraction_policy_id: atom_extraction_policy_v3
atom_granularity_policy_id: atom_granularity_policy_v2
user_graph_revision_id: user_graph_rev_person_yifan_20260616_001
graph_profile_id: graph_profile_person_yifan_research_detail
assembly_policy_id: assembly_policy_method_fine_intro_coarse
```

These fields are required when a draft is generated from graph-aware inputs. Drafts generated only from current `ContextPackage` inputs must still preserve enough source, evidence, citation, and wiki revision metadata to support later observation extraction and graph assembly.

Publishing a user graph-derived wiki artifact to a project, team, or public wiki must follow the same review and proposal flow as other wiki revisions. Private user notes must not be published unless the user explicitly includes them and permissions allow it.

## 9.7.1 Knowledge Graph Fusion Implementation Policy

FormOwl v1 does not adopt a single end-to-end knowledge graph fusion framework. The product-level fusion workflow must preserve ownership, permission scope, grants, audit logs, evidence lineage, and revocation behavior, so algorithmic packages can only generate candidates.

Core v1 fusion flow:

```text
registered assets
-> extractor runs
-> observations / semantic metadata
-> candidate entities and relations
-> fusion candidates
-> access overlay or governance review
-> scope-aware canonical state or temporary effective view
```

Recommended v1 implementation components:

```text
PostgreSQL:
  source of truth for Asset identity and metadata, observations, graph state, permissions, grants, lifecycle, retention, and audit records

ObjectStore:
  source of truth for managed Asset bytes and large durable derived artifacts

pgvector:
  semantic candidate retrieval for entity descriptions, document sections, email summaries, and graph nodes

RapidFuzz:
  deterministic fuzzy string matching for names, organizations, projects, email subjects, and aliases

Splink:
  probabilistic record linkage for structured entities such as people, organizations, customers, projects, and contacts

Sentence Transformers or local embedding models:
  local semantic embeddings when raw or sensitive content should not leave the lab network

NetworkX:
  temporary worker-side graph analysis, connected component inspection, candidate cluster analysis, and graph traversal prototypes
```

NetworkX is not the production graph database. PyKEEN, OpenEA, and RDFLib are deferred or optional research/export components, not v1 core dependencies.

Algorithmic packages may generate `FusionCandidate`, `EntityResolutionProposal`, `TypeAlignmentCandidate`, and `EvidenceLink` records, but they must never mutate the canonical graph or canonical type state directly.

## 9.7.2 KG-First Evidence-Backed Cross-Resource Retrieval

ChatGPT-facing cross-resource retrieval must query a permission-filtered
`EffectiveGraphView` before using metadata, full-text, vector, or
observation-level fallback retrieval. Graph matching must be query-scored; the
gateway must not present every permission-visible graph node as though it
matched the question.

The governed query sequence is:

```text
query text
-> query-scored EffectiveGraphView hits
-> source_observation_ids
-> permission-checked Observation resolution
-> evidence coverage decision
-> fallback retrieval only for graph miss, low confidence, or incomplete evidence
-> reviewable Candidate KG proposal seeds from fallback evidence
```

Each public graph hit must identify the graph object, object type, review state,
confidence, permission scope, source observation ids, source asset ids, and
resolved `formowl://observation/{observation_id}` evidence locators. Answering
from a graph label alone is not sufficient for the normal high-trust path; the
supporting observations must resolve before the gateway treats the graph path
as complete.

Fallback proposal seeds are candidate-layer handoffs only. They must require
review, must not create `CandidateAtom` or `CandidateRelation` records as a
hidden side effect, and must never write canonical graph state. Raw asset mode
continues to require an explicit grant and may expose only governed
`formowl://asset/{asset_id}` references with no raw content.

## 9.8 Storage and Tool Boundaries

The system should maintain separate stores for separate responsibilities:

```text
StorageBackendRegistry -> physical storage backend metadata and health
IngressStore -> bounded arrival, quarantine, and processing state
AssetStore -> PostgreSQL identity, scope, lineage, lifecycle, retention, and audit metadata
AssetRelationshipStore -> occurrence, parent-child, attachment, and derivation lineage
ObjectStore -> authoritative managed source bytes and large derived artifacts
ObservationStore -> extracted observations
CandidateAtomStore -> uncommitted candidate atoms and relations
CanonicalGraphStore -> canonical atoms, entities, relations, and graph revisions
UserGraphStore -> user-specific graph revisions
WikiStore -> wiki pages, drafts, revisions, and publish metadata
VectorStore -> embeddings for similarity search
JobStore -> ingestion and extraction jobs
```

For normal managed ingestion, `resources`, an UploadSession body, or another
controlled arrival location feeds `IngressStore`; it is not an additional
permanent store. The required transition is:

```text
ingress item
  -> stability, safety, size, and type checks
  -> content hash
  -> durable ObjectStore write
  -> checksum or read-after-write verification
  -> Asset, AssetOccurrence, permission, and audit commit in PostgreSQL
  -> ingress cleanup
  -> IngestionJob / ExtractorRun
```

If any required commit step fails, the item remains recoverable in ingress or
quarantine and must not appear as an active Asset. All managed files that
participate in extraction, graph construction, search, or wiki projection must
first pass this commit point and be registered in the central FormOwl catalog.
Distributed physical storage does not imply distributed Asset or graph
identity.

Container members, mail attachments, embedded documents, and similar nested
resources must use the same boundary. The parent parser emits attachment or
member bytes, FormOwl commits them as child Assets with AssetOccurrence records,
records parent and occurrence lineage, and routes each child by detected MIME
type. The ObjectStore adapter may reuse an immutable byte blob by content hash,
but that optimization does not replace the child Asset or occurrence. PDF,
PPTX, DOCX, spreadsheets, images, audio, and video use their normal extractors;
MSG, EML, and `message/rfc822` may recursively enter the mail extractor.
Deduplicating bytes must not merge owners, permissions, grants, retention, or
occurrence history.

External tools may be used for media parsing, OCR, ASR, speaker diarization, scene detection, document parsing, candidate graph extraction, graph visualization, and graph-assisted retrieval.

Examples include:

```text
WhisperX
Docling
Unstructured
PySceneDetect
Neo4j LLM Graph Builder
LlamaIndex PropertyGraphIndex
LangChain LLMGraphTransformer
GraphRAG-style tools
```

External tools must not directly write to `CanonicalGraphStore`.

They may only write to:

```text
ObservationStore
CandidateAtomStore
ExternalGraphImport
```

FormOwl then performs:

```text
CandidateGraph
  -> GranularityPolicyEngine
  -> EntityResolver
  -> RelationResolver
  -> CanonicalGraphCommit
```

MCP is an orchestration interface, not the core data processing engine. Heavy extraction jobs should run in FormOwl backend services, with MCP tools used to create jobs, inspect status, review candidates, and trigger approved commits.

ChatGPT-facing MCP tools must go through a governed FormOwl MCP Gateway. Internal services such as Synology NAS, PostgreSQL, MinIO or other object storage, workers, and raw scratch paths must not be exposed directly.

Normal users should stay in a single task-oriented surface whenever possible. ChatGPT, structured MCP task cards, inline actions, and embedded or session-bound FormOwl task surfaces are the user-facing layer. Backend control planes are not part of normal usage.

Hiding backend operations is both a usability rule and a safety rule. Storage routing, parser choice, worker scheduling, object placement, asset registration, permission checks, and graph integration are FormOwl responsibilities, not user decisions.

User-initiated uploads must begin with an `UploadSession`. The UploadSession captures intent before file transfer begins:

```text
authenticated actor
owner scope
workspace scope
project scope
customer scope
intended asset type
ingestion profile
visibility scope
upload expiration
source preparation state
processing status
```

The physical storage backend is selected by FormOwl according to storage routing policy. Users see the business and knowledge scope of the upload, not NAS folders, buckets, volumes, parser-specific paths, worker queues, or object-store locations.

Source preparation guidance must remain attached to an UploadSession. For example, guided PST preparation may teach the user how to export a PST, OST, MSG, or EML file, but the guidance must not leave the user with an untracked local file and no corresponding FormOwl upload task.

The required principle is:

```text
Source preparation produces a file.
UploadSession determines how that file enters FormOwl ingress.
FormOwl commits and verifies the durable ObjectStore copy before Asset activation.
Storage routing, parser execution, Asset registration, ingress cleanup, and graph integration are handled by FormOwl.
```

Current connected MCP tools include `whoami` plus whichever governed semantic
handlers are configured by the connected runtime. The semantic set currently
includes:

```text
whoami
open_upload_session
create_ingestion_job
list_observations
preview_graph_candidates
query_effective_graph
query_effective_graph_view
query_mail_evidence
answer_mail_case_progress
request_graph_access
submit_graph_review_decision
generate_wiki_draft_from_graph_view
```

Planned tools include:

```text
capture_current_chatgpt_session
get_upload_session
prepare_upload_source
get_upload_task_card
complete_upload_session
upload_asset_reference
get_ingestion_job
extract_graph_candidates
resolve_entity_candidate
commit_candidates_to_graph
list_types
get_type
propose_type
propose_type_alias
resolve_type_candidate
commit_types
propose_type_alignment
get_entity
search_graph
search_assets
search_mail
fetch_email_thread
fetch_evidence_snippet
create_access_request
list_pending_access_requests
approve_access_request
deny_access_request
revoke_grant
generate_wiki_page
```

`select_actor` is not a connected tool. Identity selection exists only inside
the manual-trusted test/local compatibility facade.

Disallowed MCP tool shapes include:

```text
list_nas_folder(path)
read_file(path)
open_smb_path(path)
download_raw_pst(path)
mount_share()
run_parser_on_path(path)
query_postgres_raw(sql)
choose_storage_backend(name)
choose_parser_path(path)
choose_worker_queue(name)
```

`upload_asset_reference` must not bypass UploadSession intent capture for normal user uploads. It is reserved for controlled imports, migration adapters, or trusted backend references that still create asset, permission, and audit records.

`capture_current_chatgpt_session` is a convenience shortcut, not a separate
ingestion backbone. It should capture the current ChatGPT conversation into a
governed ChatGPT session artifact with the authenticated actor, current
workspace scope, permission scope, source account metadata, capture method, and
audit records. After capture, it must still commit and verify the artifact in
ObjectStore, register an Asset and occurrence, and create the normal ingestion
or extraction job path.

## 9.9 Current Implementation Boundary

The current implementation does not yet require:

```text id="current-graph-nonrequirements"
a graph database
canonical atom extraction
automatic user graph assembly
company-wide ontology management
user graph visualization
```

This is a sequencing status, not a product constraint. A full graph database, extraction backend, and user graph store are expected parts of the target architecture once the atom model, provenance rules, user assembly semantics, and review workflow have been validated.

The current implementation can still be useful without a graph database because:

```text id="full-graph-db-deferral-rationale"
Provenance and review correctness can be validated without graph storage.
Atom granularity rules should be tested before they are hardened into a database schema.
User graph assembly behavior depends on real user workflows and should not be guessed too early.
WikiRevision governance must remain useful even when graph infrastructure is absent.
Managed Asset bytes and metadata, governed external source records, evidence snapshots, and citations must remain source-of-truth layers regardless of storage backend.
```

The current implementation must still avoid designs that would block this model later. In particular, wiki drafts, citations, evidence snapshots, and revision metadata should preserve enough source traceability for future observation extraction, candidate graph generation, canonical graph commits, and user graph assembly.

---

## 10. Markdown Frontmatter Standard

Every generated markdown page must include frontmatter.

Example:

```yaml id="21j7uv"
---
title: Data Retention Architecture Decision
type: adr
status: draft
revision_id: rev_wiki_20260616_001
parent_revision_id: rev_wiki_20260615_001
change_kind: source_refresh
project: formowl
owner: null
generated: true
generated_by: chatgpt
review_status: pending
created_at: 2026-06-16T12:00:00+08:00
last_reviewed: null

source_refs:
  - source_system: openproject
    source_type: work_package
    source_id: "123"
    source_url: "https://openproject.example.com/work_packages/123"

evidence_snapshot_ids:
  - ev_project_20260616_001

related_work_items:
  - source_system: openproject
    source_type: work_package
    source_id: "123"

citations:
  - citation_id: cit_001
    evidence_snapshot_id: ev_project_20260616_001
    source_system: openproject
    source_type: work_package
    source_id: "123"

permission_scope:
  scope_type: project
  scope_id: formowl
  visibility: restricted

revision_backend:
  type: database
  id: wiki_revision_rows/123
---
```

---

## 11. ChatGPT Session Capture

ChatGPT session capture uses the same provenance model.

A captured ChatGPT session must include source account metadata.

### ChatGPT Session Capture Shortcut

Because ChatGPT is the primary discussion surface, FormOwl should provide a small shortcut for the common action "save this conversation into FormOwl." This shortcut is allowed for convenience, but it must not become a parallel ingestion backbone.

The shortcut should behave as:

```text
User asks ChatGPT to save the current session
  -> MCP Gateway calls capture_current_chatgpt_session
  -> FormOwl creates a ChatGPT session capture record
  -> FormOwl serializes the session dump in bounded processing space
  -> FormOwl hashes, durably writes, and verifies the dump in ObjectStore
  -> FormOwl registers the dump as an Asset and AssetOccurrence
  -> FormOwl removes the temporary processing copy
  -> FormOwl creates the normal IngestionJob / ExtractorRun path
```

The shortcut may skip a visible upload page because the source is already the current ChatGPT session. It must not skip identity, scope, permission, provenance, asset registration, storage routing, or audit.

The shortcut output should be a task card that shows:

```text
capture ID
authenticated actor
workspace / project / customer scope
visibility scope
source account status
capture method
processing status
```

The stored session dump is a managed source Asset. The public capture record
uses `asset_id` and a governed `formowl://asset/{asset_id}` locator.
ObjectStore bucket names, object keys, local processing folders, and any
`raw_folder`-style field remain internal adapter details and must not appear in
the user-facing capture contract.

If the captured session includes uploaded files, each file must be committed as
a child Asset with an AssetOccurrence and relationship to the session or
message. Its detected MIME type determines whether it enters the PDF,
presentation, document, spreadsheet, image, audio, video, mail, or quarantine
path.

Minimum capture metadata:

```json id="wwd8d3"
{
  "capture_id": "cap_20260616_chatgpt_yifan_001",
  "source_system": "chatgpt",
  "source_account_id": "chatgpt:yifanliou@gmail.com",
  "source_account_identity_hash": "sha256:...",
  "capture_method": "manual_export",
  "captured_by": "person_yifan",
  "captured_at": "2026-06-16T10:30:00+08:00",
  "ingested_at": "2026-06-16T10:35:00+08:00",
  "permission_scope": "private:user_yifan",
  "asset_id": "asset_chatgpt_session_20260616_001",
  "storage_locator": "formowl://asset/asset_chatgpt_session_20260616_001",
  "manifest_hash": "sha256:..."
}
```

User message record:

```json id="5yjvec"
{
  "session_id": "session-20260616-km",
  "capture_id": "cap_20260616_chatgpt_yifan_001",
  "message_id": "001",
  "sequence_id": 1,
  "role": "user",
  "actor_type": "human",
  "actor_id": "person_yifan",
  "actor_source": "source_account",
  "source_account_id": "chatgpt:yifanliou@gmail.com",
  "timestamp": null,
  "content": "Please turn the project discussion into a wiki draft.",
  "attachment_asset_ids": [],
  "authorship": {
    "message_author": "person_yifan",
    "verification_level": "source_account_attributed"
  }
}
```

Assistant message record:

```json id="kth9i3"
{
  "session_id": "session-20260616-km",
  "capture_id": "cap_20260616_chatgpt_yifan_001",
  "message_id": "002",
  "sequence_id": 2,
  "role": "assistant",
  "actor_type": "ai_model",
  "actor_id": "openai_chatgpt",
  "source_account_id": "chatgpt:yifanliou@gmail.com",
  "model": "unknown-or-captured-model",
  "content": "Drafted summary content generated for the captured account.",
  "authorship": {
    "message_author": "openai_chatgpt",
    "generated_for_account": "chatgpt:yifanliou@gmail.com",
    "verification_level": "platform_generated"
  }
}
```

Rule:

```text id="w3md25"
A ChatGPT session Asset without source_account_id must not enter the verified managed Asset pool.
It may only enter an unverified import queue.
```

---

## 12. Workflow Examples

## 12.1 Project Context to Wiki Draft

```text id="kscw3h"
User:
  Create an ADR wiki draft from OpenProject #123.
ChatGPT:
  1. Calls Project MCP: get_work_item_context(OP #123)
  2. Receives ContextPackage
  3. Calls Wiki MCP: generate_wiki_draft(ContextPackage)
  4. Returns markdown draft to user
```

---

## 12.2 Staged Workflow

If only one MCP is available at a time:

```text id="hrgbnr"
Stage 1:
  Use Project MCP to generate ContextPackage.

Stage 2:
  Use Wiki MCP to generate markdown from ContextPackage.
```

The handoff object is:

```json id="m35tij"
{
  "context_package_id": "ctx_project_20260616_001",
  "context_type": "work_item_context",
  "context_markdown": "...",
  "source_refs": [],
  "evidence_snapshot_ids": [],
  "citations": [],
  "permission_scope": {}
}
```

---

## 12.3 Managed Resource Ingress and Nested Attachment

```text
User or source adapter supplies a file to resources/inbox or an UploadSession.
FormOwl:
  1. Creates bounded ingress state and waits for the input to become stable.
  2. Applies size, type, malware, archive, and policy checks.
  3. Computes the content hash.
  4. Writes the bytes to the authoritative ObjectStore.
  5. Verifies the durable write by checksum or read-after-write.
  6. Registers Asset, AssetOccurrence, permission, lineage, lifecycle, and audit records in PostgreSQL.
  7. Removes the ingress copy only after the durable and metadata commits succeed.
  8. Creates IngestionJob and ExtractorRun records.
  9. When a parser finds an attachment or embedded member, commits it as a child Asset and AssetOccurrence; the ObjectStore adapter may independently reuse an immutable byte blob.
  10. Records parent, attachment occurrence, archive/import, and derivation lineage.
  11. Routes PDF, PPTX, DOCX, spreadsheet, image, audio, video, MSG, EML, and other child Assets by detected MIME type.
  12. Quarantines unsafe, unsupported, or failed content without representing it as an active Asset.
```

Preview and download later resolve by `asset_id` through the Retrieval Gateway;
they do not read from `resources`, worker scratch, a bucket/key supplied by the
caller, or the original attachment path.

## 12.4 Multimodal Resource to Wiki Projection

```text
User:
  Turn this meeting recording and related project issues into a meeting page and update the project hub.
FormOwl:
  1. Accepts the audio/video file through managed ingress.
  2. Commits and verifies the durable ObjectStore copy.
  3. Registers the Asset, occurrence, scope, lineage, lifecycle, and audit metadata.
  4. Cleans the ingress copy and creates an ingestion job.
  5. Runs ASR, speaker diarization, scene detection, OCR, and project context extraction.
  6. Stores transcript segments, scene descriptions, OCR blocks, and issue records as observations.
  7. Extracts candidate decisions, action items, topics, risks, and dependencies.
  8. Shows the candidate graph for review.
  9. Applies atom granularity, entity resolution, relation resolution, and lifecycle policies.
  10. Commits approved candidates to the canonical graph.
  11. Assembles a project-manager user graph.
  12. Applies meeting-page and project-hub WikiProjectionSpec objects.
  13. Generates reviewable WikiRevision drafts with citations and graph lineage.
```

## 12.5 Candidate Graph Review Workflow

```text
Observation batch
  -> CandidateAtom and CandidateRelation extraction
  -> Candidate graph preview
  -> Human or policy review
  -> Split / merge / reject / defer / approve
  -> Entity and relation resolution
  -> Canonical graph commit
  -> User graph revision
  -> Wiki projection
```

---

## 13. Observability

Every MCP tool call must be logged.

Minimum log fields:

```json id="1l0rs6"
{
  "event_type": "mcp_tool_call",
  "server_name": "project-mcp",
  "tool_name": "get_work_item_context",
  "request_id": "req_001",
  "conversation_id": "optional",
  "user_id": "optional",
  "source_account_id": "optional",
  "called_at": "2026-06-16T12:00:00+08:00",
  "arguments_hash": "sha256:...",
  "response_hash": "sha256:...",
  "status": "ok",
  "latency_ms": 1200,
  "evidence_snapshot_id": "ev_project_20260616_001"
}
```

Logs must support answering:

```text id="mf4hll"
Which MCP tool was called?
When was it called?
Which user or source account triggered it?
Which evidence snapshot was created?
Which wiki draft used which evidence snapshot?
Did ChatGPT use Project MCP and Wiki MCP in the same workflow?
```

---

## 14. Runtime, Language, and Container Policy

FormOwl must be container-first.

The canonical development, test, and deployment environment is a container image. Local host tooling may be used for convenience, but it must not become a hidden requirement for contributors or operators.

Container requirements:

```text id="container-policy"
Container images must include the required Python runtime and service dependencies.
MCP servers must be runnable from containers without requiring host-installed Python or system libraries.
Development containers should support repeatable local testing and linting.
Production containers should prefer small runtime images and explicit dependency pinning.
Compose or equivalent local orchestration should be available for Project MCP,
Wiki MCP, controlled ingress, the durable ObjectStore, PostgreSQL metadata, and
workers when those services exist.
Container volume mounts for `resources`, upload staging, quarantine, or worker
scratch must be labeled and operated as temporary processing storage. They must
not be documented, backed up, or restored as the authoritative Asset store.
ObjectStore durability and PostgreSQL backup/restore must be tested as separate
responsibilities.
```

Implementation language:

```text id="language-policy"
Python
```

TypeScript is not a runtime implementation language for this repository. The prior TypeScript workspace, package metadata, tsconfig files, and typecheck hooks have been removed. Future agents should not recreate TypeScript packages unless the language policy is explicitly changed first.

Python owns all Phase 0 implementation:

```text id="python-owns"
MCP server orchestration
External service adapters
Workflow logic
Natural-language operation mapping
Review and proposal flow glue
Configuration loading
Test fixtures and integration tests
Day-to-day debugging entrypoints
Human-readable diagnostics
Hashing helpers
Diff helpers
Validation glue
```

Future systems-language use is optional and must be justified by a concrete implementation boundary:

```text id="future-systems-language-criteria"
large binary parsers
memory-sensitive transforms
high-throughput local media processing
cryptographic signing or verification beyond standard-library hashing
sandbox-like safety boundaries
validated performance bottlenecks that Python cannot reasonably handle
```

Syntax shielding rule:

```text id="syntax-shielding-rule"
If a Python implementation would require unusual metaprogramming, deeply nested decorators, generated code, fragile regular expressions, complex DSLs, unsafe dynamic evaluation, or other syntax that ordinary maintainers should not be expected to read and edit, the implementation should be hidden behind a clear Python API. A systems-language backend may be introduced later only if there is a concrete need.
The Python layer should expose clear functions, classes, and typed data objects.
Normal debugging should start from Python.
```

Removed language stacks:

```text id="removed-language-stacks"
TypeScript workspace removed.
Rust workspace and Python native binding scaffold removed.
Current formowl_core helpers are pure Python.
```

---

## 15. Suggested Repository Layout

```text id="cf1xgs"
formowl/
  README.md
  SPEC.md
  RESOURCE_EXTRACTION_SPEC.md
  LICENSE
  Containerfile
  compose.yaml
  pyproject.toml

  .devcontainer/
    devcontainer.json

  containers/
    dev/
      Containerfile
    runtime/
      Containerfile

  resources/
    README.md       # documents runtime-only ingress and cleanup policy
    inbox/          # temporary; never authoritative
    quarantine/     # temporary isolation pending policy/recovery
    processing/     # disposable bounded staging

  schemas/
    storage-backend.schema.json
    asset.schema.json
    asset-occurrence.schema.json
    asset-relationship.schema.json
    asset-lifecycle-event.schema.json
    retention-policy.schema.json
    observation.schema.json
    semantic-metadata.schema.json
    candidate-atom.schema.json
    candidate-relation.schema.json
    canonical-atom.schema.json
    canonical-entity.schema.json
    canonical-relation.schema.json
    atom-granularity-policy.schema.json
    atom-lifecycle-event.schema.json
    entity-resolution-event.schema.json
    relation-resolution-event.schema.json
    user-graph-assembly-policy.schema.json
    user-knowledge-graph-revision.schema.json
    wiki-projection-spec.schema.json
    ingestion-job.schema.json
    extractor-run.schema.json
    source-ref.schema.json
    evidence-snapshot.schema.json
    citation.schema.json
    permission-scope.schema.json
    context-package.schema.json
    wiki-revision.schema.json
    mcp-result-envelope.schema.json

  python/
    formowl_contract/
      __init__.py
      models.py

    formowl_ingestion/
      __init__.py
      assets.py
      extraction.py
      ingress.py
      jobs.py
      lifecycle.py
      observations.py
      retrieval.py
      extractors/
      storage/
        object_store.py
        asset_store.py
        relationship_store.py

    formowl_graph/
      __init__.py
      candidates.py
      canonical.py
      policies.py
      resolution.py
      user_graphs.py
      storage/

    formowl_observability/
      __init__.py
      logger.py

    formowl_project_mcp/
      __init__.py
      server.py
      tools/
        search_work_items.py
        get_work_item.py
        get_work_item_context.py
        list_work_item_activities.py
        list_work_item_relations.py
        get_project_status.py
        propose_work_item_comment.py
      adapters/
        openproject/
          client.py
          mapper.py
          schemas.py
      storage/
        evidence_snapshot_store.py
      observability/
        __init__.py  # deprecated compatibility import
        logger.py    # deprecated compatibility import

    formowl_wiki_mcp/
      __init__.py
      server.py
      tools/
        search_wiki_pages.py
        get_wiki_page.py
        generate_wiki_draft.py
        update_wiki_draft.py
        publish_wiki_page.py
        capture_wiki_snapshot.py
      markdown/
        frontmatter.py
        templates/
          adr.md
          project-hub.md
          meeting-notes.md
          decision-log.md
          risk-register.md
      storage/
        draft_store.py
        wiki_snapshot_store.py
      observability/
        __init__.py  # deprecated compatibility import
        logger.py    # deprecated compatibility import

  docs/
    architecture.md
    mcp-boundaries.md
    provenance.md
    workflows.md
    openproject-adapter.md
    wiki-draft-schema.md

  examples/
    context-package.json
    wiki-draft-input.json
    generated-adr.md

  tests/
    contract/
    project-mcp/
    wiki-mcp/
    integration/
```

---

## 16. README Summary

````md id="3mp5w0"
# formowl

formowl is a source-preserving, graph-governed knowledge management system that
turns managed source resources into governed wiki views:

```text
Ingress / External Source
  -> Managed Asset in durable ObjectStore
  -> Observation / Semantic Metadata
  -> Candidate Graph
  -> Governed Canonical Graph
  -> User Knowledge Graph
  -> Wiki Projection / WikiRevision
```
````

The current repository starts with two decoupled MCP servers:

- Project MCP
- Wiki MCP

Project MCP retrieves project execution context from systems such as OpenProject.

Wiki MCP generates and manages markdown/wiki knowledge artifacts.

Both MCPs interoperate through `formowl-contract`, which currently defines shared schemas for source references, evidence snapshots, citations, permission scopes, context packages, wiki revisions, and MCP result envelopes. The target contract expands to assets, observations, candidate graph objects, canonical graph objects, user graph revisions, projection specs, ingestion jobs, and extractor runs.

FormOwl is container-first. The canonical development, test, and runtime environment is provided by containers.

The implementation language for Phase 0 is Python. Python owns readable orchestration, debugging, hashing helpers, diff helpers, validation glue, and service behavior.

`resources` is a temporary ingress, quarantine, and processing workspace. It is
not permanent storage. PostgreSQL is authoritative for Asset identity, scope,
lineage, lifecycle, retention, and audit; the S3-compatible ObjectStore is
authoritative for managed bytes. Attachments and embedded files become child
Assets and are routed through the same MIME-specific extractor pipeline.

## Core Principle

Project systems own execution state.

Wiki systems own published knowledge views.

Managed source Assets do not directly become final wiki pages. They first
become observations, candidate graph proposals, governed canonical graph
commits, user graph revisions, and projection-spec-driven wiki revisions.

````

---

## 17. Implementation Order

Recommended order:

```text id="994n05"
1. Create container-first monorepo skeleton
2. Implement formowl-contract JSON schemas
3. Add Python contract models generated or validated from schemas
4. Implement Project MCP with mocked OpenProject data in Python
5. Implement EvidenceSnapshot storage
6. Implement Wiki MCP draft generator in Python
7. Add markdown frontmatter provenance
8. Add MCP tool-call logging
9. Test Project MCP independently
10. Test Wiki MCP independently
11. Test Project MCP to ContextPackage to Wiki MCP workflow
12. Add real OpenProject adapter
````

Pipeline extension order:

```text id="pipeline-extension-order"
1. Define StorageBackend, Asset, AssetOccurrence, AssetRelationship, AssetLifecycleEvent, and RetentionPolicy contract schemas.
2. Add StorageBackendRegistry, PostgreSQL Asset and relationship stores, and the authoritative ObjectStore interface.
3. Implement controlled resources/UploadSession ingress, stability and safety checks, durable object commit, checksum verification, quarantine, recovery, and post-commit ingress cleanup.
4. Implement Asset lifecycle, retention, legal hold, redaction, deletion, purge, and immutable lifecycle-event audit.
5. Define User, SessionIdentity, WorkspaceMember, OAuth identity/session, AccessRequest, Grant, AuditLog, ActorContext, and AuthProvider contracts.
6. Implement Google-backed FormOwl OAuth 2.1 and gateway-controlled ActorContext for connected deployment; retain ManualTrustedInternalAuthProvider only for tests/local compatibility.
7. Implement the Retrieval Gateway for permission-checked evidence snippets, previews, bounded streams, and short-lived opaque download capabilities.
8. Define Observation, SemanticMetadata, IngestionJob, ExtractorRun, and extraction-policy contract schemas and stores.
9. Implement generic MIME detection, extractor routing, and child Asset/occurrence creation for archive members, attachments, and embedded resources.
10. Implement resource extraction for project data, markdown/wiki pages, ChatGPT sessions, and document blocks.
11. Add audio, video, image, presentation, spreadsheet, PDF, and word-processing extractors behind the same Observation contract.
12. Add PST/mail ingestion as Asset -> IngestionJob -> ExtractorRun -> Observation; reuse the generic nested-resource path for attachments and recurse only for mail MIME types.
13. Define CandidateAtom, CandidateRelation, and ExternalGraphImport contract schemas.
14. Implement candidate graph extraction and preview from observations.
15. Define CanonicalAtom, CanonicalEntity, CanonicalRelation, and CanonicalGraphRevision contract schemas.
16. Define ExtractionPolicy, AtomGranularityPolicy, EntityResolutionPolicy, RelationResolutionPolicy, LifecyclePolicy, and WikiProjectionPolicy.
17. Implement granularity policy enforcement, entity resolution, and relation resolution.
18. Define AtomLifecycleEvent, EntityResolutionEvent, and RelationResolutionEvent mappings.
19. Implement reviewed canonical graph commits with provenance.
20. Define UserGraphProfile, UserGraphAssemblyPolicy, and UserKnowledgeGraphRevision contract schemas.
21. Implement user graph assembly policies, permissioned overlays, grants, and revision history.
22. Define FusionCandidate, EntityResolutionProposal, EvidenceLink, EffectiveGraphView, ScopeAwareCanonicalGraph, and MergeDecision contracts.
23. Implement matching, access overlay, and canonical merge as separate governed workflows.
24. Define WikiProjectionSpec and add graph lineage fields to markdown frontmatter.
25. Implement projection-spec-driven wiki generation from user graph revisions.
26. Implement usage-signal collection for split and merge proposals.
27. Implement reviewed atom split, merge, archive, deprecate, supersede, and equivalence workflows.
28. Add vector search and graph storage once the contract and review workflows stabilize.
```

Implementation alignment cleanup order:

```text
1. Keep the official stateless Streamable HTTP `/mcp` runtime as the only
   connected ChatGPT-facing transport; retain JSON-line, hand-built JSON-RPC,
   and stdio only as explicit test/local compatibility entrypoints.
2. Add real graph fusion contracts and workflows for matching, access overlay, and canonical merge.
```

---

## 18. Acceptance Criteria

The current implementation is usable when:

```text id="8fvc4g"
Project can be developed and tested inside a container.
Project does not require host-installed Python for normal development.
Python is the primary debugging entrypoint for MCP behavior.
Project MCP can return a ContextPackage for an OpenProject work package.
Project MCP can persist an EvidenceSnapshot.
Wiki MCP can generate a markdown draft from a ContextPackage.
Generated markdown includes source_refs and evidence_snapshot_ids.
Both MCPs can be tested independently.
Tool-call logs show when Project MCP and Wiki MCP are called.
Project-system writes are proposal-only.
Wiki publishing is proposal-only unless explicitly configured otherwise.
```

The connected identity implementation is repository-complete only when:

```text
The public MCP resource is exactly the canonical HTTPS /mcp URL.
OAuth protected-resource and authorization-server metadata agree on that origin.
The predefined ChatGPT client uses PKCE S256 and exact callback/resource binding.
The operator-recorded predefined client ID is stable across discovery and final OAuth.
The exact callback is the value displayed by ChatGPT; lack of predefined-client UI support is an external blocker.
Google OIDC issuer and subject map through a valid FormOwl invitation.
Google tokens are never accepted as FormOwl MCP bearer tokens.
FormOwl access tokens are signed, resource-bound, fixed at 3600 seconds, validated with a fixed 30-second skew, and backed by server-side token sessions.
Every protected tool call resolves a fresh ActorContext from current PostgreSQL state.
Caller-supplied identity, workspace, session, and grant fields are rejected or overwritten by gateway authority.
whoami reports only the authenticated FormOwl user and current workspace.
Revocation, disabled identity/user/client authorization, expiry, and membership removal fail closed and are audited.
Manual trusted, JSON-line, hand-built JSON-RPC, and stdio identity flows are test/local compatibility only.
```

Repository-complete does not mean issue #20 is closed. Fresh PostgreSQL,
restart persistence, first-owner and second-user journeys, signing-key rotation,
real MCP Inspector, real ChatGPT plus Google, documentation alignment, and the
configured reviewer gate must all have accepted external evidence first.

The current repository implements the Google-backed FormOwl OAuth bridge,
PostgreSQL-backed OAuth and audit state, fixed token lifetime/skew, exact
stateless Streamable HTTP `/mcp`, operator and migration flows, and fresh
gateway-controlled `ActorContext` resolution. This is repository-side
implementation status only. Issue #20 remains open until the seven documented
external evidence layers, including reviewer and independent completion audit
layers, are accepted.

The target pipeline is usable when:

```text
Physical storage can be distributed across registered storage backends without fragmenting graph identity.
Controlled resources folders and upload staging are treated as temporary ingress, not permanent Asset storage.
A managed ingress item becomes active only after hashing, durable ObjectStore write, verification, PostgreSQL Asset/occurrence registration, and required audit commit.
Ingress cleanup occurs only after the durable byte and metadata commit succeeds; failed, incomplete, or suspicious inputs remain recoverable in ingress or quarantine.
PostgreSQL is authoritative for Asset identity, tenant/workspace scope, ownership, permission, lineage, lifecycle, retention, and audit.
The S3-compatible ObjectStore is authoritative for active managed bytes and large durable derived artifacts.
Managed source resources can be registered as Assets with permission scope, source lineage, lifecycle state, and retention policy.
Resource extractors can create observations with location metadata and extractor runs.
Mail and PST ingestion can preserve archive, message, attachment, and occurrence identity.
PDF, presentation, document, spreadsheet, image, audio, video, MSG, and EML attachments become child Assets with AssetOccurrence records and are routed by detected MIME type.
Attachment lineage preserves the parent message, attachment occurrence, source archive/import session, and derivation relationship.
Byte deduplication never merges Asset authorization, owner scope, grants, retention, or occurrence history.
Semantic metadata can produce candidate atoms and relations without committing them as truth.
Candidate graph previews can be reviewed, split, merged, rejected, or committed.
Entity and relation resolution events are recorded for canonical graph changes.
Canonical atoms, entities, relations, and lifecycle mappings remain resolvable across revisions.
The type system has a closed core, scoped extension types, governed promoted types, and versioned ontology revisions.
Type compatibility checks hard-depend only on the closed core supertype lattice.
Cross-scope type alignment is a governed candidate, never an automatic merge, and never leaks a private scope's evidence.
User graph revisions can assemble different valid views from the same canonical graph.
Cross-user graph sharing uses AccessRequest, Grant, permissioned overlays, and audit logs.
Entity matching can generate same-as or related-to candidates without granting access.
Access overlays can expose approved fragments without merging canonical graph state.
Canonical merges are explicit governed events within a target scope.
WikiProjectionSpec can generate reviewable wiki drafts from user graph revisions.
Wiki revisions preserve graph lineage, source refs, evidence snapshots, citations, and generator metadata.
Canonical graph commits and graph-derived wiki frontmatter pin ontology_revision_id when type resolution influenced the result.
External tools cannot directly mutate canonical graph state.
External tools and LLMs cannot directly mutate canonical type state.
ChatGPT-facing MCP tools cannot expose raw NAS paths, arbitrary file reads, raw SQL, or object-store admin endpoints.
User-initiated uploads start with an UploadSession and do not require users to choose storage backends, buckets, parser paths, or worker queues.
Public records and tools identify originals with `asset_id` or `formowl://asset/{asset_id}`, never ingress paths, local paths, bucket names, object keys, or credentials.
Original-file preview and download go through the Retrieval Gateway with fresh ActorContext, permission, grant, lifecycle, retention, and audit checks.
Short-lived download capabilities are opaque, scoped to one Asset and operation, and do not expose bucket names, object keys, storage credentials, or administrative endpoints.
Retention expiry does not bypass legal hold, authorization, lineage, or audit requirements for redaction, deletion, or purge.
```

---

## 19. Non-Goals

```text id="qpfu4w"
Do not make Wiki MCP depend on OpenProject internals.
Do not make Project MCP generate wiki pages.
Do not assume ChatGPT always exposes every workspace MCP in every session.
Do not allow automatic project-system writes without approval.
Do not treat LLM-generated output as source of truth.
Do not let external extractors or LLM graph tools write directly to the canonical graph.
Do not treat transcript chunks, OCR blocks, PDF paragraphs, or issue comments as canonical atoms without governance.
Do not generate final wiki pages directly from managed source Assets or
governed external source records without observation, graph, projection, and
review boundaries.
Do not require a full knowledge graph database before the graph contracts and workflows are stable.
Do not treat a canonical atom graph as a company-wide ontology.
Do not create a standalone ontology subsystem outside the candidate -> canonical governance pipeline.
Do not import a large upper ontology, OWL reasoner, or triplestore into v1.
Do not let LLM-generated type labels mutate canonical type state directly.
Do not collapse user knowledge graph state into WikiRevision.
Do not silently rewrite canonical atoms based only on one user's behavior.
Do not require non-engineering wiki authors to use Git or inspect backend revision IDs.
Do not require contributors to install host-level runtimes when a container can provide them.
Do not expose Synology NAS, SMB, NFS, WebDAV, MinIO admin, PostgreSQL, raw object storage, or worker scratch paths directly to ChatGPT.
Do not build the canonical graph from raw storage paths.
Do not use `resources`, upload staging, quarantine, or worker scratch as the authoritative permanent Asset store.
Do not mark an ingress file active or delete its temporary copy before durable ObjectStore verification, Asset registration, and audit commit succeed.
Do not expose bucket names, object keys, S3/MinIO URLs, storage credentials, local paths, or attachment extraction paths as public Asset identity.
Do not let byte-level deduplication merge Asset ids, owners, permissions, grants, retention policies, or attachment occurrence lineage.
Do not special-case mail attachments as opaque mail-only blobs when their detected MIME type belongs to the generic PDF, presentation, document, spreadsheet, image, audio, or video extraction path.
Do not serve original Asset bytes or download capabilities without Retrieval Gateway authorization and audit.
Do not equate ingress cleanup, worker scratch cleanup, durable retention expiry, redaction, and purge; they are separate lifecycle decisions.
Do not make normal users switch into backend control planes, storage browsers, parser configuration screens, or worker queues.
Do not let source preparation guidance produce untracked local files without an UploadSession.
Do not treat test/local manual identity selection as connected authentication.
Do not enable manual trusted identity selection, caller-supplied identity
environment variables, JSON-line, hand-built JSON-RPC, or stdio as the
connected ChatGPT authentication path.
Do not silently merge another user's private graph into the requester's graph.
Do not grant raw asset access without FormOwl permission checks, grant scope, and audit.
Do not treat entity matching as data access.
Do not treat data access as canonical merge.
Do not treat canonical merge as raw asset access.
Do not introduce TypeScript, Rust, or another runtime language without changing this specification first.
```

---

## 20. Final Architecture Statement

formowl's target architecture is a governed knowledge pipeline:

```text
Ingress / External Source
  -> Managed Asset in durable ObjectStore
  -> Observation / SemanticMetadata
  -> Candidate Graph
  -> Governed Canonical Graph
  -> User Knowledge Graph
  -> WikiProjection / WikiRevision
```

The current connected implementation uses one governed public gateway and keeps
the two original MCP services as compatibility boundaries:

```text id="kbd0ln"
FormOwl connected MCP Gateway = public HTTPS OAuth and protected /mcp boundary
Project MCP compatibility service = project execution context
Wiki MCP compatibility service = knowledge artifact lifecycle
```

They interoperate through:

```text id="7119o7"
SourceRef
EvidenceSnapshot
Citation
PermissionScope
ContextPackage
MCPResultEnvelope
```

Graph and wiki work must preserve this separation:

```text id="final-graph-boundary-summary"
Controlled resources folders, upload staging, quarantine, and worker scratch are temporary processing layers, not permanent Asset storage.
The S3-compatible ObjectStore is authoritative for managed source bytes and large durable derived artifacts.
PostgreSQL is authoritative for Asset identity, tenant/workspace scope, ownership, permissions, occurrence and parent-child lineage, lifecycle, retention, grants, and audit.
Managed Assets, governed external source records, evidence snapshots, and citations remain source-of-truth and locator layers.
Physical storage may be distributed, but FormOwl Asset and graph identity are centralized.
Attachments and embedded members become child Assets with AssetOccurrence records, preserve parent and import lineage, and route through the normal MIME-specific extractor path; immutable byte blobs may be deduplicated separately.
Preview and download resolve governed Asset identifiers through the Retrieval Gateway; public tools never expose ingress paths, bucket/key pairs, credentials, or storage administration.
Observations and semantic metadata are extracted intermediate data.
Candidate graphs are reviewable proposals.
Canonical atoms, entities, and relations are reusable governed graph parts.
Canonical graph state is scope-aware; canonical within a scope does not mean canonical across all scopes.
User knowledge graphs are versioned assemblies for roles, tasks, permissions, and preferred granularity.
Wiki revisions are governed output artifacts generated through projection specs and review flows.
MCP exposes governed semantic operations, not raw storage, raw database,
object-store administration, worker control, or parser internals.
Connected human identity flows through FormOwl OAuth 2.1 and Google OIDC, then
resolves a fresh gateway-controlled ActorContext from current FormOwl state.
Manual trusted identity, JSON-line, hand-built JSON-RPC, and stdio remain
test/local compatibility surfaces only.
```

Issue #20 establishes connected identity and fresh gateway-controlled
`ActorContext`. Generic Asset governance and downstream source-specific
consumers remain outside this issue's completion claim.
