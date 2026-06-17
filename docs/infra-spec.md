# Infrastructure Specification

<!-- Future agents: continue building FormOwl infrastructure requirements in this file. Do not create another infrastructure specification unless SPEC.md is updated first. -->

This document defines the infrastructure boundary for the FormOwl resource, graph, and storage architecture.

It complements `SPEC.md`, `docs/architecture.md`, `docs/provenance.md`, `docs/workflows.md`, and `docs/mcp-boundaries.md`. It does not replace the product model, contract schemas, or MCP tool specifications.

## Scope

FormOwl infrastructure must support a source-preserving, graph-governed knowledge pipeline:

```text
Raw Resource
  -> Resource Extraction
  -> Observation / Semantic Metadata
  -> Candidate Graph
  -> Governed Canonical Graph
  -> User Knowledge Graph
  -> Wiki Projection
  -> ChatGPT / MCP interaction
```

The infrastructure must preserve:

```text
raw resources
source locations
extraction versions
permission scopes
review records
graph lifecycle history
wiki citations
MCP and ChatGPT interaction audit
```

## Internal Deployment Assumptions

The first deployment target is an internal company or lab environment, not public SaaS.

Initial constraints:

```text
raw data remains inside the company or lab network
Synology NAS may provide internal file storage behind the firewall
public S3 is not required for Phase 0
PostgreSQL must not use ordinary NAS or NFS storage for PGDATA
ChatGPT must not directly reach NAS, PostgreSQL, MinIO, worker scratch paths, or raw storage endpoints
the only ChatGPT-facing service should be a governed FormOwl MCP Gateway
```

The infrastructure should provide an S3-like object abstraction, but it does not require AWS S3. Acceptable internal backends include a native S3-compatible enterprise storage endpoint, a correctly deployed MinIO service, or a transitional internal ingress adapter. Raw NAS paths are deployment details behind FormOwl storage adapters.

## Core Infrastructure Decisions

FormOwl v1 should use:

```text
PostgreSQL + pgvector
S3-compatible object storage
StorageBackend registry
Worker services
Project MCP and Wiki MCP services
Container-first runtime
```

PostgreSQL is the source of truth for governance, provenance, permissions, canonical graph state, user graph state, wiki revision metadata, job state, and audit records.

Object storage is the source of bytes for raw resources and large derived artifacts.

pgvector supports semantic retrieval. It does not replace relational graph tables.

Graph databases, dedicated vector databases, full-text search clusters, and event streaming platforms are optional projections or scaling additions. They are not required for the v1 source-of-truth architecture.

## Runtime Boundary

Containers are the canonical development, test, and deployment boundary.

Infrastructure must not require contributors or operators to install host-level Python, OCR libraries, media tools, database clients, or extractor dependencies when a container can provide them.

Local development should be runnable through Compose or an equivalent local orchestrator.

Production deployment should use explicit images, pinned dependencies, externalized persistent volumes, and managed secrets.

## Logical Services

```text
LLM host or UI
  -> Project MCP / Wiki MCP / future graph orchestration MCP tools
  -> FormOwl backend services
  -> PostgreSQL + pgvector
  -> S3-compatible object store
  -> worker services
```

### PostgreSQL

PostgreSQL owns:

```text
asset registry
asset occurrences
fingerprints
ingestion jobs
extractor runs
observation metadata
semantic metadata
candidate graph metadata
canonical graph tables
canonical graph lifecycle events
user graph revisions
graph scopes and preferences
wiki revision metadata
permission scopes
MCP tool-call audit
rebuild job state
```

Recommended extensions:

```text
pgvector
pgcrypto or equivalent UUID/hash helpers when useful
```

PostgreSQL must support transactions, foreign keys, unique constraints, partial indexes, upserts, JSONB metadata, full-text search where useful, audit records, concurrent workers, and migrations.

PostgreSQL storage policy:

```text
use local SSD, NVMe, or reliable block storage
do not place PGDATA on ordinary NAS, SMB, WebDAV, or NFS-mounted storage
back up PostgreSQL independently from raw object storage
```

### Object Store

Object storage owns large immutable or derived byte artifacts:

```text
raw PDF, Office, image, audio, video, PST, OST, MSG, EML, and archive files
EvidenceSnapshot payloads
API response snapshots
extractor output
Docling layout JSON
OCR JSONL
ASR transcript JSONL
frame captures
scene metadata
embedded attachment bytes
reviewable exported artifacts
```

PostgreSQL stores object references, not large payloads:

```text
object_uri
content hash
file size
mime type
metadata
source locator
permission scope
storage status
retention status
```

The preferred implementation is MinIO or another S3-compatible object store for local and team deployments.

MinIO should be treated as an internal object service, not as a thin unsafe wrapper over ordinary NAS or NFS paths. FormOwl code should depend on `ObjectStore` and `StorageBackend` interfaces, not scattered raw Synology, SMB, NFS, or filesystem paths.

Disallowed ChatGPT-facing exposure:

```text
Synology DSM
SMB
NFS
WebDAV
NAS raw paths
MinIO admin console
PostgreSQL
raw object storage endpoint without FormOwl authorization
```

### Worker Services

Workers own heavy or asynchronous backend work:

```text
resource ingestion
file type detection
extraction routing
document parsing
OCR
ASR
speaker diarization
scene detection
email and attachment traversal
code symbol extraction
semantic metadata extraction
candidate graph generation
embedding generation
projection rebuilds
selective reprocessing
```

Workers must be idempotent. Each job should record inputs, extractor versions, configuration hashes, pipeline versions, outputs, logs, status, retries, and failure reason.

For v1, PostgreSQL job tables may be the coordination mechanism. A dedicated queue or streaming platform should be added only when job volume or operational requirements justify it.

Workers should process registered assets by `asset_id` and `object_uri`. Large files should be copied to local scratch SSD before parsing instead of being parsed directly from NAS-mounted paths as the normal runtime model.

Worker scheduling should be storage-aware when raw data is distributed:

```text
asset_id
storage_backend_id
file size
media type
required extractor
required hardware class
preferred worker locality
```

Workers should declare:

```text
allowed_storage_backends
available scratch space
CPU class
GPU availability
network locality
extractor capabilities
```

GPU is an optional worker accelerator, not a control-plane requirement. Mail and PST ingestion are primarily CPU, disk I/O, memory, local scratch, and parser-stability workloads. GPU workers should be scheduled separately for ASR, diarization, image understanding, video analysis, local embedding models, rerankers, or local LLM graph candidate generation.

### MCP Services

MCP services are orchestration boundaries, not extraction or graph processing engines.

MCP tools may:

```text
create ingestion jobs
inspect job status
search observations
preview graph candidates
request candidate review
trigger governed graph commits
search graph context
retrieve evidence
generate wiki projections
update user graph preferences
```

MCP tools must not:

```text
expose raw SQL
run heavy extraction inline
directly mutate canonical graph state
decide permissions outside FormOwl policy
store user graph preferences in ChatGPT memory as source of truth
```

ChatGPT-facing MCP access must be routed through a FormOwl MCP Gateway or an equivalent governed service. Internal services such as Synology NAS, PostgreSQL, object storage, workers, and scratch directories remain internal-only.

MCP Gateway responsibilities:

```text
enforce session identity
enforce workspace, grant, and permission checks
return minimal snippets by default
redact when required
create and resolve access requests
log every tool call
never expose raw NAS paths
never allow arbitrary file reads
```

## Storage Boundaries

```text
StorageBackendRegistry -> physical storage backend metadata and health
AssetStore -> raw resource metadata and object references
ObjectStore -> raw and derived binary or large structured artifacts
ObservationStore -> extracted observations and semantic metadata
CandidateGraphStore -> uncommitted candidate atoms and relations
CanonicalGraphStore -> canonical atoms, entities, relations, lifecycle events, and graph revisions
UserGraphStore -> user-specific graph scopes, preferences, subscriptions, and revisions
FusionStore -> match candidates, resolution proposals, evidence links, effective graph views, and merge decisions
WikiStore -> wiki drafts, revisions, snapshots, projection specs, and publish proposals
VectorStore -> pgvector embeddings for semantic retrieval
JobStore -> ingestion, extraction, embedding, projection, and rebuild job state
AuditStore -> MCP tool calls, review decisions, evidence access, and graph commits
```

These may initially share a PostgreSQL database and object store. The boundary is logical first. Physical separation can come later.

## Storage Backend Registry

FormOwl should maintain a central `StorageBackend` registry so physical storage can be distributed without fragmenting knowledge identity.

Recommended `StorageBackend` fields:

```text
storage_backend_id
type: synology_smb | synology_nfs | s3_compatible | minio | local_fs | ingress_only
display_name
internal_endpoint
root_prefix
access_mode: read_only | read_write | ingress_only
trust_level
workspace_scope
health_status
bandwidth_class
latency_class
allowed_workers
```

Recommended `Asset` storage fields:

```text
asset_id
storage_backend_id
object_uri
content_hash
file_size
mime_type
created_at
registered_at
owner_user_id
workspace_id
permission_scope
lifecycle_state
```

All files that participate in extraction, graph construction, search, or wiki projection must first be registered as assets. Unregistered storage is invisible to the knowledge graph.

## Infrastructure State Model

State fields must be explicit and narrow. A single `status` column must not mix byte availability, processing progress, review result, lifecycle, permission, and projection freshness.

Use lowercase snake_case values.

Recommended state axes:

```text
object_storage_state -> whether bytes exist and are verified
data_lifecycle_state -> whether data participates in active retrieval and rebuilds
processing_state -> whether a job or run is queued, running, failed, or complete
review_state -> whether a human or policy decision is pending or complete
canonical_lifecycle_state -> whether governed graph objects are current, superseded, archived, or redacted
projection_state -> whether derived projections and indexes are ready, stale, or rebuilding
service_health_state -> whether runtime services are healthy enough to accept work
```

Governed state transitions should append events. They should not destructively overwrite history.

### Object Storage State

Applies to object references for raw files, evidence snapshots, extractor outputs, exports, and other object-store payloads.

```text
registered -> metadata row exists, object bytes not yet available
uploading -> upload or copy has been issued
available -> bytes exist and hash verification passed
hash_mismatch -> bytes exist but verification failed
quarantined -> blocked by malware, policy, parser safety, or operator action
missing -> metadata points to bytes that are not currently accessible
redacted -> object access is intentionally removed or replaced by a redaction marker
purged -> bytes were removed by retention policy while metadata and audit remain
```

Normal transition:

```text
registered -> uploading -> available
```

Exception transitions:

```text
uploading -> missing
uploading -> hash_mismatch
available -> quarantined
available -> redacted
available -> purged
missing -> available
hash_mismatch -> quarantined
```

Raw resource deletion should normally become `redacted` or `purged`, not a hard deletion of lineage records.

### Data Lifecycle State

Applies to assets, observations, semantic metadata, graph objects, user graph revisions, wiki revisions, and projections.

```text
active -> participates in default graph assembly, retrieval, and wiki projection
warm -> available and searchable, but lower priority for default retrieval
archived -> retained and addressable, excluded from most default rebuilds and active views
frozen -> immutable historical record, available only through explicit lookup or citation resolution
redacted -> hidden from normal access; lineage remains only where policy allows
```

Lifecycle state controls participation. It must not be used to represent job execution progress.

### Asset State

Assets need both byte state and registry state.

```text
asset_state:
  registered -> asset metadata was created
  awaiting_object -> asset requires object bytes before extraction
  ready -> object bytes or external source reference are available for ingestion
  duplicate_of_existing -> asset content maps to an existing canonical asset
  ingestion_blocked -> policy, permission, safety, or missing dependency blocks ingestion
  redacted -> asset is no longer retrievable except through permitted audit paths
```

`AssetOccurrence` records do not disappear when an asset is deduplicated. Different appearances should remain queryable even when they point to the same underlying asset.

### Ingestion Job State

Applies to coarse jobs created by MCP tools, UI actions, scheduled rebuilds, or system maintenance.

```text
queued -> waiting for a worker
leased -> worker lease acquired, work not yet started
running -> worker is executing the job
waiting_external -> waiting for an external API, object upload, model, or manual dependency
retry_scheduled -> failed attempt will be retried
partial -> completed with usable output and recorded warnings
succeeded -> completed successfully
failed -> completed without usable output
cancelled -> intentionally stopped before completion
dead_lettered -> retry budget exhausted and operator review is required
```

Terminal states:

```text
succeeded
partial
failed
cancelled
dead_lettered
```

Allowed retry path:

```text
queued -> leased -> running -> retry_scheduled -> queued
```

Jobs must record retry count, lease owner, lease expiry, started time, completed time, input hashes, output references, and failure reason.

### Extractor Run State

Applies to each extractor invocation or cache decision.

```text
planned -> extractor run selected but not started
cache_hit -> matching extractor output already exists
running -> extractor process is executing
succeeded -> output is complete and verified
partial -> output is incomplete but usable
failed -> output is not usable
skipped -> extractor was intentionally bypassed
invalidated -> output should not be used because policy, model, config, or source changed
superseded -> newer extractor output should be preferred
```

`cache_hit`, `succeeded`, `partial`, `failed`, and `skipped` are terminal for that run. A later extraction creates a new run instead of mutating the old one.

### Observation State

Observations are derived records, not canonical truth.

```text
created -> observation was produced by an extractor or import
indexed -> observation is available for search or downstream processing
low_confidence -> usable only with caution or review
invalidated -> extractor output or source context is no longer trusted
superseded -> newer observation should be preferred
archived -> retained but excluded from default active processing
redacted -> hidden from normal access
```

Observation state should preserve `extractor_run_id`, source locator, confidence, and permission scope so invalidation or redaction can be selective.

### Semantic Metadata State

Semantic metadata is a derived interpretation of observations.

```text
generated -> metadata was produced
indexed -> metadata is available for candidate graph generation or retrieval
stale -> source observation, extractor policy, or semantic policy changed
invalidated -> metadata should not be used
superseded -> newer metadata should be preferred
redacted -> hidden from normal access
```

Stale semantic metadata can trigger candidate graph rebuilds without touching raw resources.

### Candidate Graph State

Applies to candidate atoms, candidate relations, candidate entity mentions, and external graph imports.

```text
generated -> candidate was created from observations or imports
preview_ready -> candidate is ready for human or policy review
pending_review -> review is required before commit
needs_changes -> reviewer requested edits, split, merge, or clarification
approved -> candidate may proceed to resolution and commit
rejected -> candidate will not be committed
deferred -> decision intentionally postponed
committed -> candidate contributed to a canonical graph commit
superseded -> newer candidate replaces this candidate before commit
```

Candidate state may change through review events. Canonical state must not be changed directly by an extractor.

### Review Decision State

Applies to human review queues and policy-assisted review records.

```text
pending_review -> waiting for a reviewer or policy adjudication
approved -> accepted as proposed
approved_with_changes -> accepted after split, merge, edit, or remapping
rejected -> rejected with a reason
deferred -> postponed with a reason or dependency
cancelled -> review item was withdrawn before decision
```

Review decisions should record actor, policy, reason, source object ids, and created output ids.

### Fusion Decision State

Applies to cross-scope entity matching, access overlays, and canonical merge decisions.

```text
fusion_candidate_state:
  proposed -> candidate was generated by deterministic, fuzzy, probabilistic, semantic, or manual matching
  needs_access -> candidate may require another owner's private graph or evidence
  access_requested -> an AccessRequest exists
  overlay_granted -> a Grant allows a temporary effective view
  merge_review_pending -> canonical merge is awaiting explicit governance review
  merged_in_scope -> canonical merge was approved inside a target scope
  rejected -> candidate was rejected
  revoked -> grant or visibility was revoked
  expired -> candidate or grant expired
```

Matching, access overlay, and canonical merge must not share a single overloaded status. They are separate governed transitions with separate audit records.

### Canonical Graph State

Canonical graph objects evolve through lifecycle events, not destructive rewrites.

```text
canonical_lifecycle_state:
  active -> current canonical object
  superseded -> replaced by a newer atom, entity, relation, or super-atom
  deprecated -> discouraged for new projections but still resolvable
  archived -> historical and excluded from default active graph assembly
  redacted -> hidden from normal access while preserving permitted lineage
```

Canonical lifecycle event types:

```text
create
split
merge
supersede
deprecate
archive
reactivate
redact
mark_equivalent
derive_from
```

`split` and `merge` are events, not final states. The resulting old object state should usually become `superseded`, while new objects become `active`.

Every canonical lifecycle transition must preserve old identifiers for citation resolution, audit lookup, and historical wiki revisions.

### User Graph State

User graph scopes and revisions are derived, versioned views.

```text
graph_scope_state:
  active -> available for routing and retrieval
  muted -> available only when explicitly requested
  archived -> no longer used in default routing
  disabled -> blocked by policy or administrator action
  redacted -> hidden from normal access
```

```text
user_graph_revision_state:
  draft -> assembled but not active
  active -> preferred current revision for the scope
  superseded -> replaced by a newer revision
  archived -> retained for history
  redacted -> hidden from normal access
```

Only one revision should be `active` for the same graph scope and routing profile unless a policy explicitly allows concurrent active variants.

### Wiki Revision and Projection State

`WikiRevision.status` should remain compatible with `SPEC.md`:

```text
draft
reviewed
published
archived
```

Additional review state may be recorded separately:

```text
pending_review
changes_requested
approved
rejected
cancelled
```

Projection runs should use a separate state:

```text
queued -> projection job is waiting
running -> projection job is generating output
draft_created -> projection produced a draft WikiRevision
failed -> projection did not produce usable output
cancelled -> projection was intentionally stopped
superseded -> a newer projection run should be preferred
```

Reviewed and published wiki revisions are immutable. Refresh and restore operations create new revisions.

### Vector Index State

Applies to embedding rows and aggregate index readiness.

```text
pending -> embedding or index work is needed
indexing -> embedding or index work is running
ready -> vector is available for retrieval
stale -> source content, model, policy, or permissions changed
rebuilding -> replacement vector or index is being built
failed -> vector or index build failed
disabled -> vector retrieval is intentionally unavailable
```

Stale vectors must not bypass permission checks. A stale vector may still be usable for degraded retrieval only when policy permits and the caller is told the result is stale.

### Optional Projection State

Applies to optional Graph DB, search engine, or external vector database projections.

```text
disabled -> projection is not configured
pending -> projection needs to be created or refreshed
building -> projection is being built
ready -> projection can serve reads
stale -> source-of-truth state has changed
failed -> projection build failed
rebuilding -> replacement projection is being built
```

Optional projections are rebuildable. They must not become the only place where governed state exists.

### Service Health State

Applies to runtime services and worker pools.

```text
not_configured -> service is intentionally absent in this deployment
starting -> service is booting or migrating
healthy -> service can accept normal work
degraded -> service can serve partial or limited work
unavailable -> service cannot serve required work
maintenance -> service is intentionally paused
```

MCP tools should surface `degraded`, `unavailable`, or `maintenance` states as structured warnings or errors instead of hiding infrastructure failures.

### Migration and Backup State

Database migrations:

```text
pending
running
applied
failed
rolled_back
```

Backups:

```text
scheduled
running
completed
failed
verified
expired
```

`completed` backups are not sufficient for recovery guarantees. Production backups should reach `verified` on a defined schedule.

## Object Layout

Object paths should be deterministic enough for operations and debugging, but database IDs remain the source of truth.

Recommended object prefixes:

```text
raw/{workspace_id}/{asset_id}/{filename}
evidence/{workspace_id}/{evidence_snapshot_id}/payload.json
extractor-runs/{workspace_id}/{extractor_run_id}/output.jsonl
extractor-runs/{workspace_id}/{extractor_run_id}/artifacts/
attachments/{workspace_id}/{asset_id}/{attachment_asset_id}/{filename}
exports/{workspace_id}/{artifact_type}/{artifact_id}/
```

Objects should be content-addressed or content-hash verified where practical.

## Deduplication Infrastructure

Deduplication must reduce processing cost without discarding source occurrences.

```text
same content -> one Asset
different appearances -> multiple AssetOccurrence records
```

Asset-level exact dedup keys:

```text
sha256
file_size
mime_type
```

Extractor-run cache keys:

```text
asset_sha256
extractor_name
extractor_version
extractor_config_hash
pipeline_version
```

Email-level fingerprints should prefer:

```text
Internet Message-ID
MAPI EntryID or SearchKey
normalized subject + from + sent_at + body_hash
body simhash
attachment hash set
```

Attachments are independent assets. The system must preserve every email, thread, sender, and folder occurrence where the attachment appeared.

Near-dedup fingerprints may include:

```text
image pHash / dHash / aHash
audio Chromaprint or acoustic fingerprint
video keyframe pHash + audio fingerprint
scanned document OCR text hash + page image pHash
```

## Extraction Tooling

Apache Tika may be used as a universal parser adapter, file type detector, metadata fallback, embedded-file traversal tool, or fallback extractor.

Tika must not be the only extraction intelligence for:

```text
PDF layout understanding
high-quality OCR
Chinese scanned documents
audio/video transcription
speaker diarization
email thread graph reconstruction
knowledge graph granularity
entity and relation resolution
canonical graph commits
```

Recommended specialized extractor families:

```text
Docling -> PDF / Office layout, reading order, tables, page and bbox locators
PaddleOCR -> OCR blocks, confidence, bbox, scanned document text
ExifTool -> image and media metadata
FFmpeg -> media extraction and normalization
Whisper / WhisperX -> ASR transcript and timestamps
pyannote or equivalent -> diarization
PySceneDetect -> video scene segmentation
libpff / pypff / readpst -> PST and OST parsing
extract-msg and Python email parsers -> MSG, EML, MBOX handling
Microsoft Graph API -> online mailbox ingestion where authorized
tree-sitter -> repository and source-code structure
```

Each extractor run must be recorded as derived data with versioned inputs and outputs.

## Graph and Vector Infrastructure

Canonical graph and user graph state should be represented in PostgreSQL relational tables in v1:

```text
canonical_nodes
canonical_edges
canonical_graph_commits
canonical_graph_lifecycle_events
user_graph_scopes
user_graph_subscriptions
user_graph_preferences
user_graph_activity_events
user_graph_revisions
user_graph_nodes
user_graph_edges
graph_projection_runs
```

pgvector stores embeddings for:

```text
query embeddings
observation embeddings
canonical node embeddings
wiki section embeddings
graph scope summary embeddings
user preference profile embeddings
recent activity summary embeddings
```

Retrieval must be hybrid:

```text
permission_allowed
+ user_subscribed
+ role_default
+ semantically_relevant
+ recently_used
+ task_appropriate
```

Vector similarity alone must not decide permission, graph scope, or final answer context.

## Rebuild Policy

The whole database should not be dropped and rebuilt as a normal operating mode.

Do not rebuild destructively:

```text
raw resources
asset records
asset occurrence records
canonical graph history
canonical lifecycle events
review decisions
audit logs
published or reviewed wiki revisions
```

May be selectively rebuilt:

```text
semantic metadata
candidate atoms
candidate relations
user graph projections
wiki draft projections
embedding indexes
optional Graph DB projections
optional search indexes
```

Observation records are usually stable derived data. Rebuild them only when extractor versions, policies, source content, or quality requirements justify a new extractor run.

Canonical graph evolution must use lifecycle events such as:

```text
split
merge
supersede
deprecated
archived
reactivated
```

Old graph identifiers must remain resolvable for citations, audit history, and wiki revisions.

## Permission and Audit Requirements

Permission scopes must be recorded on source assets, observations, candidate graph objects, canonical graph objects, user graph revisions, wiki revisions, and evidence retrieval events where applicable.

ChatGPT and external clients must not receive direct database credentials.

Phase 0 internal beta may use manual trusted identity selection, but authorization and audit models must still exist from the beginning. Minimum identity and collaboration records:

```text
User
SessionIdentity
WorkspaceMember
AccessRequest
Grant
AuditLog
```

For Phase 0, users may manually select their FormOwl identity at session start. The selected identity becomes `actor_user_id` for MCP calls. This is not production authentication, and it must sit behind an `AuthProvider` interface so SSO, OIDC, SAML, or external tenant auth can replace it later.

Raw data access should be scoped, not all-or-nothing. Grant scopes should support:

```text
answer_only
graph_snippet
evidence_snippet
one_time_raw_asset_access
session_access
asset_scoped_access
query_scoped_access
project_scoped_access
```

Every MCP tool call should record:

```text
actor
workspace
tool name
input parameters
evidence accessed
output citations
permission scope
grant id when applicable
timestamp
result status
```

Every governed graph commit should record:

```text
source candidate ids
source observation ids
policy ids
review decision ids
approver or automation identity
commit timestamp
created lifecycle event ids
```

## Security Baseline

Infrastructure must assume raw resources and extracted artifacts may contain confidential project, customer, legal, financial, personal, or security-sensitive information.

Baseline requirements:

```text
private object buckets
least-privilege service credentials
separate application and migration credentials where practical
secret values outside source control
permission-aware retrieval
audit of evidence access
hash verification for stored objects
backup encryption where supported
no public object URLs by default
no direct NAS path exposure through MCP
no arbitrary MCP file reads
no direct PostgreSQL, MinIO admin, SMB, NFS, or WebDAV exposure to ChatGPT
```

Signed URLs or temporary object access should be issued only through permission-checked backend paths.

## Backup and Recovery

PostgreSQL backup is mandatory because it holds governance, lineage, permissions, graph state, and audit records.

Object storage backup is mandatory because it holds raw resources and large derived artifacts.

Recommended recovery order:

```text
restore PostgreSQL
restore object store
verify object hashes referenced by PostgreSQL
rebuild vector indexes if needed
rebuild optional search or graph projections if needed
replay or inspect failed jobs
```

Backups must preserve enough data to recover reviewed wiki revisions, canonical graph history, evidence snapshots, and source citations.

## Configuration

Common deployment configuration should include:

```text
FORMOWL_DATA_DIR
FORMOWL_DATABASE_URL
FORMOWL_OBJECT_STORE_ENDPOINT
FORMOWL_OBJECT_STORE_BUCKET
FORMOWL_OBJECT_STORE_REGION
FORMOWL_OBJECT_STORE_ACCESS_KEY_ID
FORMOWL_OBJECT_STORE_SECRET_ACCESS_KEY
FORMOWL_WORKSPACE_ID
FORMOWL_LOG_LEVEL
FORMOWL_EXTRACTOR_WORKER_CONCURRENCY
```

The current file-backed `FORMOWL_DATA_DIR` behavior is acceptable for early MCP prototypes. Team deployments should move source-of-truth metadata to PostgreSQL and raw or large payloads to object storage.

## Observability

Infrastructure should expose:

```text
MCP tool-call logs
job lifecycle logs
extractor run logs
graph commit logs
evidence access audit
worker retry and dead-letter state
object hash verification failures
database migration history
service health checks
```

Logs should preserve correlation identifiers across MCP calls, backend jobs, extractor runs, graph commits, and wiki projection jobs.

## Deferred Infrastructure

Do not add these systems to v1 without a concrete requirement:

```text
Graph DB
Elasticsearch
Qdrant
Kafka
Neo4j
Memgraph
Kuzu
```

They may be introduced later as rebuildable projections or scaling components, not as replacements for PostgreSQL governance state.

## Acceptance Criteria

The infrastructure satisfies this specification when:

```text
1. FormOwl can run from containers without host runtime assumptions.
2. Raw resources and large derived artifacts live in object storage or an equivalent object-store abstraction.
3. PostgreSQL owns metadata, governance, provenance, permissions, graph state, jobs, and audit.
4. pgvector supports semantic retrieval without replacing graph tables.
5. Workers perform heavy extraction, embedding, and rebuild work outside MCP request execution.
6. MCP services expose permission-aware orchestration tools, not raw SQL or direct canonical graph mutation.
7. Deduplication preserves every source occurrence.
8. Derived projections can be rebuilt without deleting raw resources, audit records, or canonical graph history.
9. ChatGPT is never the source of truth for permissions, user graph preferences, or graph routing.
10. Backups can restore source evidence, graph history, wiki revision lineage, and audit records.
11. Infrastructure state fields separate byte availability, data lifecycle, processing progress, review outcome, projection freshness, and service health.
12. Canonical graph lifecycle changes are represented as events and mappings, not destructive overwrites.
```
