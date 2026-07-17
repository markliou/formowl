# FormOwl Specification

## 1. Authority and Product Boundary

This document is the canonical product, knowledge-method, and architecture
specification for FormOwl.

When the product model changes, the affected canonical sections must be
rewritten and obsolete statements removed. A later addendum must not silently
override an older model. Subordinate documents may add implementation detail,
but they must not replace the methodology defined here.

FormOwl is a source-preserving, graph-governed knowledge system. It is not an
email product, procurement product, finance product, parser, wiki generator, or
project-management system. Those are source adapters, domain applications, or
projection targets that use the same method.

Its purpose is to turn heterogeneous evidence into knowledge that is:

- traceable to source observations;
- explicit about time, context, confidence, permission, and ontology lineage;
- reviewable before it becomes governed shared state;
- portable across departments and source formats; and
- projectable into answers, reports, wiki drafts, or reviewed action proposals.

The shortest statement of the methodology is:

> Convert any source into evidence-backed, time- and context-bound candidate
> assertions about business objects; govern those assertions before they become
> reusable knowledge; then assemble task-specific views without losing source
> lineage.

## 2. Generalized Evidence-to-Knowledge Methodology

The canonical pipeline is:

```text
Any governed source
  -> Asset or EvidenceSnapshot
  -> Observation
  -> Lexical and Mention Candidates for text-bearing observations
       - Unicode and script normalization
       - protected ASCII identifiers
       - Jieba segmentation
       - corpus-bound SentencePiece segmentation
       - frozen-profile candidate admission
  -> Candidate Knowledge
       - CandidateBusinessObject
       - property assertion
       - relation assertion
       - state assertion
       - event assertion
       - coordination assertion
  -> Governance
       - provenance and permission checks
       - type and ontology alignment
       - identity and relation resolution
       - temporal and contradiction checks
       - granularity and review policy
  -> Governed Canonical Knowledge Graph
  -> User or Task Effective Graph View
  -> Projection or Reviewed Action Proposal
```

### 2.1 Register the source

Every file, message, database response, project record, conversation, sensor
reading, image, audio segment, video segment, or application event enters
through a governed asset or evidence boundary. A source is evidence, not
canonical knowledge.

Physical paths, buckets, database connections, parser commands, and worker
scratch locations are implementation details. They must not become graph
identifiers or public MCP fields.

### 2.2 Produce citeable observations and stable retrieval units

An `Observation` is the smallest source-derived unit that can be independently
located and cited. It may be a paragraph, table cell range, OCR block,
transcript segment, ERP field group, application event, issue comment, slide
text box, or email-authored paragraph. Observation size follows citation and
extraction needs; it must not silently determine how many business records a
query has found.

Every observation preserves:

```text
observation id
asset or evidence lineage
extractor run
modality-specific locator
permission scope
observed, captured, or recorded time when available
confidence and extraction warnings
```

Retrieval additionally groups observations into a `LogicalSourceItem`. A
logical source item is the stable source-level unit counted as one piece of
evidence. Typical mappings are:

```text
mail archive        -> one authored message
PDF or document     -> one page, section, or source-defined record
PPT/PPTX            -> one slide
CSV/XLS/XLSX        -> one row or source-defined transaction record
OCR                 -> one page or region group from the same source record
audio/video         -> one utterance, scene, or source-defined event
project/wiki/chat   -> one issue activity, section, or authored message
application data    -> one immutable response row or event
```

The adapter chooses the mapping from source semantics and records it in
lineage. It must not choose a different retrieval algorithm for each
department. One logical source item may contain several observations, and
those observations may jointly support one query anchor set. Splitting a page,
slide, row, or message into more observations must not increase its document
frequency, evidence cardinality, or ranking weight.

A `ContextBoundary` is separate from both observation and logical source item.
It names the authorized container or business scope inside which evidence may
be compared, such as a mail thread, document, presentation deck, worksheet or
reporting period, inspection lot, project, contract, or case. Retrieval must
not join observations across context boundaries unless the caller explicitly
selects or is authorized for those contexts.

Every text-bearing observation uses the same lexical candidate method,
regardless of source format or department:

```text
Unicode and script normalization
  -> protected ASCII identifier extraction
  -> Jieba segmentation
  -> corpus-bound SentencePiece segmentation
  -> frozen-profile candidate admission
  -> source-neutral evidence planning and retrieval
```

This is the normative default. Regex-only tokenization is allowed only as an
explicit baseline or ablation, as protected ASCII extraction inside the
default stack, or as a clearly reported degraded fallback. A default path must
never silently switch to regex-only behavior.

Lexical candidate and retrieval outputs bind the normalization and
segmentation policy version, candidate-admission policy hash, model or
vocabulary hash, and corpus hash. A binding change requires re-extraction or
reevaluation.

### 2.3 Identify candidate business objects

A business object is the subject or object that knowledge is about. Source
occurrences first create mentions or `CandidateBusinessObject` records; they do
not directly create canonical entities.

Lexical segments are candidate generators only. The frozen-profile admission
gate decides which generated terms may enter candidate graph construction; it
does not turn a token, phrase, mention, or type guess into canonical knowledge.

Candidate object identity is distinct from:

- source occurrence identity;
- permission to read the source;
- canonical merge decisions; and
- user-specific labels or views.

### 2.4 Create candidate assertions

`CandidateAssertion` is the source-neutral semantic umbrella. Candidate
knowledge uses five universal assertion families:

```text
property      a value or characteristic of an object
relation      a relationship between business objects
state         an object's state during a time or validity interval
event         a change or occurrence
coordination  a request, commitment, decision, assignment, blocker, deadline,
              dependency, escalation, change, exception, constraint, or other
              core coordination frame
```

A candidate assertion records:

```text
assertion kind
subject business object
predicate or core coordination frame
object, value, actor, and counterparty when applicable
previous and proposed value when applicable
observed, effective, valid, asserted, and due time when applicable
reason and context
source observation ids and evidence spans
permission scope
confidence and review state
extractor run
ontology revision
Domain Pack id and content hash
```

`CandidateAtom`, `CandidateRelation`, `CandidateFrame`, and
`CandidateMention` remain specialized candidate contracts. They do not replace
the universal assertion methodology. `CandidateFrame` is the specialized
coordination representation; `CandidateAssertion` is the cross-domain semantic
envelope.

### 2.5 Govern before canonicalization

Extractor, rule, import, and LLM output is always candidate knowledge.
Candidates may be accepted, rejected, corrected, split, merged, deferred,
marked ambiguous, or superseded.

No extractor, LLM, Domain Pack, source adapter, or candidate store may directly
mutate:

```text
canonical graph state
canonical type state
user graph revisions
wiki revisions
external business systems
```

### 2.6 Commit governed knowledge

Canonical knowledge is reusable, reviewed knowledge within a defined scope.
Canonical commits must pin candidate ids, observations, evidence, reviewer or
policy decision, target scope, ontology revision, prior graph revision, and
governance policies.

Canonical does not mean universally true. Knowledge canonical in one owner,
workspace, project, customer, or grant scope may remain candidate-only or
invisible in another.

### 2.7 Assemble effective views

User and task views may select granularity, include or exclude authorized graph
fragments, apply task labels, add private notes, and redact inaccessible
evidence. The result is a versioned effective view, not a silent mutation of
canonical state.

Entity matching, data access, canonical merge, user-view assembly, and raw
asset access are separate decisions.

### 2.8 Project or propose action

Governed graph views may produce cited answers, reports, review queues,
dashboards, wiki drafts, or action proposals. Projection remains derived
output. External writes remain proposal-only unless an explicitly authorized
review workflow approves execution.

## 3. Domain Portability and Invariants

FormOwl uses one stable methodology plus scoped Domain Packs:

```text
evidence/source model
+ Observation model
+ CandidateBusinessObject
+ five universal assertion families
+ normalized TemporalContext, epistemic status, and assertion lifecycle status
+ stable coordination-frame core
+ closed core supertypes
+ scoped, content-hash-pinned Domain Packs
+ logical source items and context boundaries
+ permission-, context-, version-, and time-filtered candidate/effective views
+ governed projection definitions
```

A Domain Pack may define domain object labels, aliases, mappings to core
supertypes, assertion mappings, coordination-frame extensions, normalization
rules, temporal-role mappings, epistemic-status mappings, lifecycle-status
mappings, extraction hints, and projection vocabulary. Domain-specific labels
such as promised date, posting date, reporting period, contract effective date,
media timecode, or source recorded time must map into the shared temporal
vocabulary rather than creating department-specific time semantics.

A Domain Pack must be a durable, provenance-linked definition:

- it has a governed pack id and ontology revision;
- its normalized content has a stable SHA-256 hash;
- a `domain_pack_definition` Observation binds the definition payload to that
  hash;
- candidate business-object ids and metadata pin the pack, ontology revision,
  resolved supertype, and content hash; and
- candidate assertions pin the same pack id and content hash.

A Domain Pack must not replace the evidence-to-knowledge pipeline, bypass
candidate review, grant access, create an independent canonical graph, merge
scopes, or write an external system.

The closed, domain-neutral core supertypes are:

```text
Person
Organization
Project
Artifact
Document
Event
Concept
Location
Transaction
Account
Agreement
PhysicalObject
Measurement
```

The type system has three tiers:

```text
Core type       closed and stable; the only hard compatibility gate
Extension type  scoped candidate vocabulary; a soft signal only
Promoted type   governed within a scope and mapped to a core type
```

Adding procurement, finance, HR, legal, engineering, operations, or another
domain should not require a new ingestion, observation, candidate-governance,
canonical lifecycle, permission, or provenance pipeline. It should normally
require source adapters, the smallest necessary Domain Pack, evaluation
fixtures, and projections.

The invariant safety rules are:

1. raw resources and evidence snapshots remain source authority;
2. observations and all candidate objects remain derived, review-required
   records;
3. no cross-permission candidate relation or assertion is created;
4. no raw filesystem, object-store, database, credential, SQL, or worker
   locator enters candidate or public payloads;
5. stable ids bind the semantic and governance lineage that gives them meaning;
6. candidate persistence is all-or-nothing for one extraction batch;
7. candidate generation never implies canonical write;
8. canonical merge never implies access; and
9. projection never overwrites reviewed knowledge without a proposal;
10. world-valid time and system-known time remain separate; and
11. retrieval must exclude assertions that were not yet known at the requested
    knowledge time before lexical or vector ranking; and
12. every default text-bearing path uses the normative lexical candidate stack
    and binds its policy, model or vocabulary, and corpus hashes; regex-only
    behavior must be explicit and must never be a silent default; and
13. evidence cardinality and IDF use logical source items, so parser chunking
    cannot create extra evidence or ranking weight; and
14. ontology guidance is contract-bound, additive, and capped; it cannot bypass
    lexical support, permission, context, time, or candidate-only boundaries;
    and
15. candidate evidence retrieval requires a trusted access binding that pins
    eligible observations, stable source-identity policies, source versions,
    and permission scopes before query vocabulary, support counts, or IDF are
    inspected. Missing bindings fail closed, and request bindings may narrow
    but never broaden an index-level binding.

## 4. Current Implementation and Target Scope

The tested baseline remains:

```text
Project MCP
  -> ContextPackage and EvidenceSnapshot
  -> Wiki MCP
  -> sourced markdown draft
```

The resource and graph layers also contain candidate-only contracts and stores.
The current generalized minimum core supports:

```text
Observation
  -> default lexical candidates for text-bearing observations
       -> Jieba + corpus-bound SentencePiece
       -> frozen-profile candidate admission
  -> CandidateBusinessObject
  -> CandidateAssertion
       -> TemporalContext
       -> epistemic status
       -> lifecycle status
  -> CandidateTemporalView(as_of_world_time, known_as_of)
  -> CandidateEvidenceIndex
       -> trusted access binding
       -> logical source grouping by identity-policy + source-item id
       -> context boundary filtering
       -> query-derived evidence cardinality
       -> multi-observation anchor coverage
       -> bounded ontology reranking
  -> candidate-only file stores
```

Procurement email-shaped observations and finance ERP/application observations
use the same deterministic candidate-knowledge extractor. The extractor has no
source-family or department branch. Their Domain Packs map local vocabulary to
the same closed core, the same five assertion families, the same temporal
vocabulary, and separate epistemic and lifecycle vocabularies.

The tested lexical evaluator and MAY candidate-KG evaluator use the same
normative segmentation and frozen-profile admission method. Their policy
binding includes the segmentation version, admission-policy hash,
SentencePiece model hash, and training-corpus hash. Raw Jieba plus
SentencePiece without admission and regex-only retrieval remain explicit
ablation arms, not defaults.

The current minimum core:

- persists Domain Pack definitions, candidate business objects, and candidate
  assertions as one atomic batch;
- rejects missing or mismatched Domain Pack provenance;
- rejects unsafe locators, SQL, empty assertion semantics, non-core
  coordination predicates, duplicate candidate ids, and cross-permission
  references;
- validates normalized temporal field names and simple interval ordering;
- supports candidate-only world-time, knowledge-time, and epistemic-status
  filtering before ranking;
- counts logical source items rather than parser chunks and allows observations
  from one item to jointly cover query anchors;
- requires every retrievable evidence record to carry a stable
  source-identity-policy id, source-version id, and permission-scope id, and
  refuses retrieval without a trusted access binding over those fields;
- isolates finance periods, quality lots, documents, decks, threads, and other
  authorized contexts through one context-boundary filter;
- derives one, multiple, or explicit evidence counts from the query rather
  than from a department or file-format rule;
- binds ontology revision, supported signal vocabulary, and the complete
  ontology contract before applying a capped additive rerank;
- binds `TemporalContext.captured_at` to the latest source Observation capture
  time and includes it in the stable candidate assertion identity;
- also requires the candidate assertion's pipeline-owned `created_at` to be
  present and no later than `known_as_of`; source capture alone does not make a
  not-yet-materialized candidate visible;
- requires explicit offsets on timestamps used for ordering; date-only values
  remain calendar-day values;
- preserves pack, ontology, extractor, permission, observation, and evidence
  lineage; and
- sets `canonical_write_allowed` to false.

This is not a production procurement or finance integration. It does not claim
live ERP access, generalized source parsing, semantic fusion, canonical graph
commit, canonical type write, user-graph mutation, wiki mutation, or external
system write.

The full target still includes reviewed canonical graph commits, lifecycle,
entity and relation resolution, scoped ontology governance, effective user
views, retrieval gateways, graph-derived projections, and governed external
action proposals.

Development and verification are container-first. Python remains the primary
implementation and debugging boundary. Shared contracts, not direct component
dependencies, connect MCP services, extraction, graph governance, and
projection layers.

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
Observation
SemanticMetadata
CandidateAtom
CandidateRelation
CandidateMention
CandidateFrame
CandidateBusinessObject
CandidateAssertion
DomainPackDefinition
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

The Resource Extraction Layer converts raw resources into observations and semantic metadata.

For implementation-level details of multimedia extraction, extractor routing, observation schemas, semantic metadata schemas, and adapter boundaries, see `RESOURCE_EXTRACTION_SPEC.md`.

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
asset registration
storage backend registration
extractor selection
observation creation
extractor metadata capture
location metadata capture such as timestamp, page, bounding box, frame, speaker, or section
re-extraction when extractor versions or extraction policies change
```

For text-bearing observations, resource extraction and candidate generation
share one required lexical policy:

```text
normalized text
  -> protected ASCII identifiers
  -> Jieba
  -> corpus-bound SentencePiece
  -> frozen-profile candidate admission
```

Source adapters may produce different locators and text-quality warnings, but
they may not silently choose a different default tokenizer. Missing external
segmenters must fail closed or produce a clearly marked degraded fallback.
Policy, model or vocabulary, and corpus hashes are provenance, not optional
debug metadata.

Resource extraction does not own:

```text
final atom granularity
canonical entity merges
canonical relation commits
user graph assembly
wiki page generation
```

All extractor output must remain derived data until reviewed or committed through the graph assembly workflow.

Resource extraction must run from registered assets and object references, not from arbitrary storage paths. Raw storage locations are implementation details behind `StorageBackend`, `AssetStore`, and `ObjectStore`.

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

For internal company or lab deployments, raw data may remain on Synology NAS, internal object storage, MinIO, or controlled ingress folders behind the firewall. Public AWS S3 is not required for Phase 0. The required abstraction is an S3-like object interface and a central storage backend registry, not a specific public-cloud provider.

The layer owns:

```text
StorageBackend registry
Asset registration
ObjectStore adapters
ingress adapters
storage health tracking
worker locality metadata
local scratch policy
GPU worker capability metadata
backup and retention placement
```

PostgreSQL remains the source of truth for metadata, governance, permissions, audit, job state, and graph state. It should run on local SSD, NVMe, or reliable block storage, not ordinary NAS, SMB, WebDAV, or NFS-mounted storage.

Workers process registered assets by `asset_id` and `object_uri`. Large files should be copied to local scratch before parsing. Worker locality affects performance and scheduling, but it must not fragment graph identity.

## 5.8 Identity, Access, and MCP Gateway Layer

For the internal closed beta, FormOwl may use Manual Trusted Internal identity mode. A user selects their FormOwl identity at MCP session start, and that selected identity becomes the `actor_user_id` for MCP calls and audit records.

This is not production authentication. It is allowed only for trusted internal company or lab deployments and must sit behind an `AuthProvider` interface so company SSO, OIDC, SAML, or another provider can replace it later.

Even in Phase 0, FormOwl must model:

```text
User
SessionIdentity
WorkspaceMember
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
  "storage_uri": "/raw/evidence/project/2026/06/16/ev_project_20260616_001/"
}
```

Recommended storage layout:

```text id="injjtr"
/raw/evidence/{source}/{yyyy}/{mm}/{dd}/{evidence_snapshot_id}/
  request.json
  response.json
  normalized.md
  metadata.json
```

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

`StorageBackend` describes a physical or logical storage backend that may hold raw or derived bytes.

Recommended fields:

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

`Asset` describes a registered raw resource. It is the stable identity used by extraction, graph, search, and wiki projection layers.

Recommended fields:

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

The canonical graph must not reference raw storage paths. It should reference `asset_id`, `observation_id`, `extractor_run_id`, `evidence_id`, `entity_id`, `relation_id`, `workspace_id`, `user_id`, and `grant_id` where applicable.

## 6.9 Identity, AccessRequest, Grant, and AuditLog

Minimum Phase 0 identity objects:

```text
User
- user_id
- display_name
- email optional for Phase 0
- status: active | disabled
- created_at

SessionIdentity
- session_id
- selected_user_id
- selected_at
- selection_method: manual_trusted_internal

WorkspaceMember
- workspace_id
- user_id
- role: owner | member | viewer
```

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
- actor_user_id
- action
- target_type
- target_id
- grant_id optional
- session_id
- timestamp
```

Authentication must be replaceable:

```text
AuthProvider
- authenticate(request): AuthenticatedIdentity
- resolve_user(identity): User
```

Phase 0 provider:

```text
ManualTrustedInternalAuthProvider
```

Later providers may include company SSO, Google Workspace OIDC, Microsoft Entra OIDC, SAML, or external tenant providers. Authorization, grants, provenance, and audit must not depend on the Phase 0 authentication facade.

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

Wiki specifications must distinguish between raw resources, observations, candidate knowledge, reusable canonical graph parts, user knowledge graphs, and published wiki artifacts.

The system must not assume that one source document, work item, meeting recording, image, ChatGPT session, or wiki page has one correct knowledge graph. Different users may read the same evidence with different goals, attention, terminology, and preferred granularity. A project owner may want a coarse operational summary. A reviewer may care about policy exceptions. An engineer may inspect method details. These are all valid derived views if their provenance is preserved.

This chapter defines the model boundary. It requires the architecture to support the full pipeline even when a particular deployment implements only part of it.

## 9.1 Layered Knowledge Model

The knowledge model has seven layers:

```text id="knowledge-graph-layers"
Raw resource
EvidenceSnapshot / Citation / Asset
Observation / SemanticMetadata
Candidate graph
Governed canonical graph
User knowledge graph
WikiProjection / WikiRevision
```

Layer responsibilities:

```text id="knowledge-layer-responsibilities"
Raw resource -> source-of-truth records from files, external systems, captured sessions, media, documents, or wiki snapshots.
EvidenceSnapshot / Citation / Asset -> traceable captured evidence, source locators, and raw-resource metadata.
Observation / SemanticMetadata -> normalized extracted facts, spans, scenes, blocks, transcripts, OCR, captions, and semantic hints.
Candidate graph -> proposed business objects and assertions that have not yet passed governance.
Governed canonical graph -> source-grounded reusable atoms, entities, relations, and lifecycle mappings.
User knowledge graph -> a user's versioned assembly, filtering, grouping, labeling, weighting, and permission-aware view of canonical and user-authored knowledge.
WikiProjection / WikiRevision -> a governed output artifact such as a markdown page or published wiki page generated from a graph view and source evidence.
```

`WikiRevision` is output governance. It records a versioned artifact. It must not be overloaded to become the user's full knowledge graph.

## 9.1.1 Observation and Semantic Metadata

All resource extractors should produce `Observation` records before graph assembly.

An `Observation` is a normalized description of something found in a raw resource. Examples include transcript segments, video scenes, OCR blocks, document paragraphs, page regions, issue comments, wiki sections, or ChatGPT messages.

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

Text-bearing observations first pass through the normative lexical candidate
stack defined in Section 2.2. This rule is modality-neutral: text extracted
from OCR, documents, tables, slides, mail, transcripts, conversations, or
applications is segmented and admitted by the same policy before candidate
graph ranking. Regex-only processing is not the general path.

## 9.1.2 Candidate Graph

External extractors, LLM tools, rule-based processors, and user imports may produce graph-shaped output, but that output must first enter a candidate graph.

Candidate graph objects should include:

```text
CandidateBusinessObject
CandidateAssertion
CandidateAtom
CandidateRelation
CandidateMention
CandidateFrame
DomainPackDefinition
ExternalGraphImport
```

The general source-neutral path is:

```text
Observation
  -> CandidateBusinessObject
  -> CandidateAssertion
```

`CandidateAssertion` distinguishes five assertion kinds: `property`,
`relation`, `state`, `event`, and `coordination`. It carries business-object
references, values or state change, temporal and contextual semantics, evidence
spans, permission scope, extractor run, ontology revision, Domain Pack id and
content hash, confidence, and review state.

`CandidateAtom`, `CandidateRelation`, `CandidateMention`, and
`CandidateFrame` remain valid specialized candidate representations.
`CandidateFrame` represents the coordination family through stable core frame
types and named slots; it is not the general semantic umbrella.

Domain Packs map scoped object and assertion vocabulary onto the closed core.
They are durable, content-hash-pinned definitions linked to
`domain_pack_definition` observations. They are configuration and candidate
lineage, not canonical type writes.

All records from one candidate-knowledge extraction are persisted atomically.
Any contract, permission, lineage, path-safety, duplicate-id, or write failure
must leave no partial Domain Pack, business-object, or assertion records.

Candidate graph state may be previewed, rejected, split, merged, revised, or committed. It must not be silently promoted to canonical graph state.

Candidate graph construction must consume admitted lexical or mention
candidates, not every raw Jieba or SentencePiece piece. The frozen admission
profile is the default because the completed no-training ablation improved
retrieval while preserving the no-match and permission guards in that EXM
benchmark. This is not a universal no-match guarantee; the original MAY
benchmark still requires separate rejection calibration. A different admission
policy is permitted only when it is versioned, hash-bound, and evaluated as an
explicit replacement or ablation.

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
Transaction
Account
Agreement
PhysicalObject
Measurement
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

## 9.5.2 Universal Assertion Core and Scoped Domain Packs

The scoped type ontology is combined with five universal assertion families:

```text
property
relation
state
event
coordination
```

These families are methodological primitives, not department schemas.
Procurement, finance, project, operations, legal, HR, research, and future
domains express their local semantics through the same families.

The coordination family uses a small stable frame core:

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

Scoped Domain Packs may add local business-object names, aliases, assertion
names, and process-frame extensions, but every mapping must resolve to a closed
core supertype, universal assertion kind, or core coordination frame:

```text
PurchaseOrderLine -> Transaction
Invoice -> Transaction
CostCenter -> Account
CustomerRequest -> coordination / Request
SupplierCommitment -> coordination / Commitment
InvoiceAmount -> property / invoice_amount
PaymentApproval -> event / payment_approval
```

The general candidate path is:

```text
Observation
  -> CandidateBusinessObject
  -> CandidateAssertion
  -> governance and review
  -> reviewed canonical objects, relations, states, events, or frames
  -> UserKnowledgeGraphRevision / EffectiveGraphView
  -> projection or reviewed action proposal
```

`CandidateAssertion` is the central cross-domain semantic abstraction.
`CandidateFrame` is the specialized coordination representation and may
continue to support coordination-specific experiments and slots.

Every Domain Pack has a governed id, ontology revision, source observations,
and normalized content hash. At least one source observation must carry the
matching `domain_pack_definition` payload. Candidate business-object ids and
candidate assertions pin the pack id and content hash so a pack revision cannot
silently reinterpret an existing candidate id.

Source formats do not define ontology. Email, spreadsheets, ERP rows,
application events, meetings, documents, project issues, images, and
transcripts are observation substrates that use the same candidate path.

The current repository retains the deterministic issue #28 coordination
experiment and adds a generalized procurement/finance candidate-only fixture.
Neither path claims production parsing, canonical graph commits, canonical
type writes, user graph mutation, wiki mutation, semantic fusion, or external
system writes.

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
  source of truth for assets, observations, graph state, permissions, grants, and audit records

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

## 9.7.2 Default Candidate Evidence Retrieval

FormOwl retrieval operates on evidence semantics, not file extensions,
departments, or mail-specific templates. The same planner must accept
observations from finance periods, quality lots, PDF pages, PPT slides,
spreadsheet rows, OCR regions, messages, project events, and future modalities.

This section is the default authority for every new retrieval evaluator and
harness. Regex-only retrieval, parser-chunk or Observation cardinality,
lexical/thread transitive components, and ontology hard-pruning are permitted
only as explicitly labeled ablation or historical baseline arms. They must not
define current gold, current pass/fail, or a silent fallback.

Every `CandidateEvidenceIndex` owns a
`CandidateEvidenceTextPolicyRuntime`. That runtime binds the structured
`CandidateEvidenceTextPolicyBinding` to the query tokenizer actually used by
the index. The binding proves Unicode NFKC/script normalization, protected
ASCII extraction, Jieba, corpus-bound SentencePiece, frozen-profile candidate
admission, and exact admission-policy, SentencePiece-model, and
training-corpus SHA-256 hashes. It also pins the runtime id and tokenizer
implementation hash; the runtime rejects a different callable or runtime id.
Default callers provide query text only, not raw query tokens or a
caller-supplied policy hash. A free-form hash, placeholder hash, missing
binding, regex-only declaration, or caller token override fails closed.
Explicit experiments use `retrieve_ablation`; an ablation may extend the
runtime-produced tokens but cannot silently replace or remove them.
Raw query text may determine control intent, evidence count, and chronology
syntax only. Retrieval anchors, actor/topic vocabulary, supported content
terms, and required lexical support must come from runtime-produced tokens or
a named `retrieve_ablation` extension. Regex-parsed raw terms must never be
reintroduced as retrieval vocabulary.

The input contract is:

```text
query text
index-owned CandidateEvidenceTextPolicyRuntime and structured binding
optional positive requested-source-item count from a governed query parser
trusted CandidateEvidenceAccessBinding
  eligible observation ids
  eligible stable source-identity policy ids
  eligible source-version ids
  eligible permission-scope ids
accessible context ids
explicitly selected query context ids
explicit cross-context comparison authorization when more than one query context is selected
explicit as_of_world_time and known_as_of for evaluation and harness runs
optional epistemic and lifecycle filters
independent logical-source and observation evidence budgets
query timezone when a chronology boundary is date-only
optional index-owned ontology query-signal resolver and ontology bindings
explicit retrieve_ablation identifier and transforms for non-default arms only
```

The canonical query sequence is:

```text
1. Require a trusted access binding. If both the index and request carry one,
   intersect them; a request may never broaden the index boundary.
2. Build the access-eligible observation universe before reading query
   vocabulary:
     stable source-identity policy
     permission scope
     source version
     observation id
3. Build the remaining admissible observation universe:
     accessible context boundaries
     explicitly selected query context boundaries
     known_as_of
     as_of_world_time
     epistemic status
     lifecycle status
   If this universe is empty, reject before invoking a query tokenizer,
   ontology resolver, support counter, IDF calculation, or ranker.
4. Invoke the index-owned runtime to normalize and tokenize the query with the
   same structured policy that produced the indexed evidence. Default
   `retrieve` has no raw-token or free-form query-policy-hash parameter.
5. Derive a universal evidence plan from the question and only the admissible
   vocabulary:
     general lookup
     actor/topic lookup
     chronology
     conflict or comparison
     approval/decision
     multi-source aggregation
6. Derive evidence cardinality from the question:
     governed structured count when supplied
     explicit source-unit number or classifier when present
     multi-source intent when stated
     otherwise one authoritative logical source item
   Numbers embedded in identifiers and quantities such as durations,
   percentages, or money are not evidence counts. If an explicit count exceeds
   the source-item budget, reject instead of silently lowering the count.
   Structured count input lets future language or modality-aware query parsers
   use the same retrieval core without adding a department-specific branch.
7. Choose supported anchors. Actor matching is enabled only for actor intent;
   domain words must not become accidental actor filters.
8. Compute frequency and ranking statistics over logical source items, never
   over observation chunks.
9. Match anchors conjunctively at the logical-source level. Several
   observations from the same source item may jointly cover the anchors.
10. Rank admissible logical source items and select the requested number.
11. Return the smallest observation set that covers the selected source items
   and anchors within the independent source-item and observation budgets.
12. Resolve governed observation locators and citations. Reject rather than
    return partial evidence when required anchors, chronology, permission, or
    cardinality cannot be satisfied.
13. Run experimental token, eligibility, or ontology transforms only through
    the explicitly named `retrieve_ablation` path after access and
    context/time admissibility. Token transforms may add signals but cannot
    remove the default runtime tokens.
```

These rules are mandatory:

- A logical source identity is the pair
  `(source_identity_policy_id, source_item_id)`. The same local item string
  under two adapters or identity policies is not silently treated as one
  source.
- Every retrievable evidence record carries `source_identity_policy_id`,
  `source_version_id`, and `permission_scope_id`. A trusted
  `CandidateEvidenceAccessBinding` authorizes specific values on all four
  access axes, including observation id. Absence of that binding rejects the
  request. Per-call eligibility filters are additional narrowing only.
- `CandidateEvidenceAccessBinding` is an exact immutable contract, not a
  duck-typed mapping. Its four eligibility collections are `frozenset` values
  containing exact nonblank strings. Index construction rejects malformed
  bindings; request-time malformed bindings reject without entering retrieval.
- Cross-context comparison authorization is an actual boolean. Strings,
  integers, and other truthy values fail closed and cannot authorize a
  multi-context query.
- Permission, source-identity policy, source version, context, time,
  epistemic status, and lifecycle filtering happen before support counts, IDF,
  query planning, and ranking.
  Inaccessible or future records must not influence a plan or reveal their
  vocabulary through ranking statistics.
- Evidence cardinality counts distinct logical source items. An identifier
  containing digits is not a request for that many records.
- Observation chunking is retrieval-invariant. Splitting one source page,
  slide, row, message, or event into many observations must not increase its
  IDF weight or make it appear to be multiple evidence items.
- Anchors may aggregate across observations only inside one logical source
  item. A shared term or context must not create lexical transitive closure
  across unrelated source items.
- Chronology uses normalized, offset-aware source timestamps. A source item
  without a usable time cannot become the earliest or latest result.
  `earliest`, `latest`, full-range, `before`, and `after` are distinct modes.
  A requested three-item range must return three ordered source items rather
  than collapsing to two endpoints. Date-only boundaries require an explicit
  query timezone and are converted to timezone-aware day boundaries before
  comparing instants; missing or invalid timezone context fails closed.
- Access scope and query scope are different. When several contexts are
  accessible, the caller must explicitly choose the query context. Comparing
  more than one selected context also requires explicit cross-context
  authorization. Merely having access to several periods, lots, decks,
  documents, or threads must not create a semantic union.
- A context boundary is not evidence by itself. Sharing a thread, deck,
  document, period, lot, or project does not prove that two observations answer
  the same question.
- No-match, permission-denied, and insufficient-evidence results are valid
  outcomes. The planner must not fill the budget with merely related evidence.

Ontology guidance is a bounded reranker, not a replacement retrieval path:

```text
ontology revision
+ supported signal vocabulary hash
+ complete TypeDefinition/TypeMapping contract hash
+ candidate evidence index binding
```

An ontology-bound query fails closed when these bindings do not match the
index. Only signals supported by the bound type definitions and mappings may
contribute. Actor, time, measurement, or relation evidence facets are retrieval
facets; they must not be reinterpreted as canonical `Person`, `Event`, or
`Measurement` entities merely because the query asks about them.

Evidence facets are derived from typed extraction metadata rather than source
text shape alone:

```text
observation_type
+ modality
+ semantic field/value roles
-> document, structured-record, audio/visual, image, event, artifact,
   actor-attributed, temporal, concept, or measurement-bearing evidence
```

PDF/PPT observations, ERP/table rows, audio transcripts, images, and
application events therefore do not all become `Document`. Digits in a lot
number, purchase-order id, invoice id, or other identifier do not imply
measurement. Measurement evidence requires an explicit semantic role such as
amount, quantity, rate, duration, percentage, score, or unit value.

Ontology overlap may add a capped score to lexically supported source items.
It must not delete the lexical candidate set, bypass required anchors, join
contexts, change permission or temporal admissibility, or create a canonical
type/graph write. This prevents a shallow or incomplete ontology from making
retrieval worse through hard pruning.

ChatGPT-facing cross-resource retrieval first applies this method to a
permission-filtered `EffectiveGraphView`. Graph hits then resolve
`source_observation_ids` through governed
`formowl://observation/{observation_id}` locators. A graph label alone is not
high-trust evidence.

Fallback metadata, full-text, vector, or observation retrieval is allowed only
for graph miss, low confidence, or incomplete evidence. Fallback output may
seed review-required Candidate KG proposals, but must not write candidate,
canonical, user-graph, wiki, or external-system state as a hidden side effect.
Raw asset access remains a separate explicitly granted operation.

The current POC implements candidate-only logical-source grouping,
query-derived cardinality, multi-observation coverage, context/time/status
admissibility, chronology modes with timezone-aware date boundaries,
logical-source IDF, separate source/observation budgets, chunk-invariant
logical-source evaluation, separate observation-citation metrics, and bounded
source-neutral ontology reranking. It does not claim full interval algebra,
temporal entity resolution, causal inference, canonical bitemporal storage,
production multilingual parsing, or production quality across every domain
and modality.

## 9.8 Storage and Tool Boundaries

The system should maintain separate stores for separate responsibilities:

```text
StorageBackendRegistry -> physical storage backend metadata and health
AssetStore -> raw resource metadata
ObjectStore -> raw binary files
ObservationStore -> extracted observations
CandidateAtomStore -> uncommitted candidate atoms and relations
CanonicalGraphStore -> canonical atoms, entities, relations, and graph revisions
UserGraphStore -> user-specific graph revisions
WikiStore -> wiki pages, drafts, revisions, and publish metadata
VectorStore -> embeddings for similarity search
JobStore -> ingestion and extraction jobs
```

All files that participate in extraction, graph construction, search, or wiki projection must first be registered in the central FormOwl catalog. Distributed physical storage does not imply distributed graph identity.

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
selected user
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
UploadSession determines where and how that file enters FormOwl.
Storage routing, parser execution, asset registration, and graph integration are handled by FormOwl.
```

Recommended future MCP tools include:

```text
select_actor
whoami
capture_current_chatgpt_session
create_upload_session
get_upload_session
prepare_upload_source
get_upload_task_card
complete_upload_session
upload_asset_reference
create_ingestion_job
get_ingestion_job
list_observations
extract_graph_candidates
preview_graph_candidates
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
query_effective_graph
query_effective_graph_view
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

`capture_current_chatgpt_session` is a convenience shortcut, not a separate ingestion backbone. It should capture the current ChatGPT conversation into a governed ChatGPT session artifact with selected user, workspace scope, permission scope, source account metadata, capture method, and audit records. After capture, it must still register an Asset or RawResource and create the normal ingestion or extraction job path.

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
Raw data, evidence snapshots, and citations must remain source-of-truth layers regardless of storage backend.
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
  -> FormOwl stores the session dump as an internal raw artifact
  -> FormOwl registers the dump as an Asset / RawResource
  -> FormOwl creates the normal IngestionJob / ExtractorRun path
```

The shortcut may skip a visible upload page because the source is already the current ChatGPT session. It must not skip identity, scope, permission, provenance, asset registration, storage routing, or audit.

The shortcut output should be a task card that shows:

```text
capture ID
selected user
workspace / project / customer scope
visibility scope
source account status
capture method
processing status
```

The stored session dump should be treated as a source artifact. `raw_folder` or any object-store locator is an internal storage locator, not a user-selected destination.

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
  "raw_folder": "/raw/sessions/chatgpt/2026/06/16/session-id/",
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
  "attachments": [],
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
A ChatGPT raw session without source_account_id must not enter the verified raw data pool.
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

## 12.3 Multimodal Resource to Wiki Projection

```text
User:
  Turn this meeting recording and related project issues into a meeting page and update the project hub.
FormOwl:
  1. Registers the audio/video file and project references as assets.
  2. Creates an ingestion job.
  3. Runs ASR, speaker diarization, scene detection, OCR, and project context extraction.
  4. Stores transcript segments, scene descriptions, OCR blocks, and issue records as observations.
  5. Extracts candidate decisions, action items, topics, risks, and dependencies.
  6. Shows the candidate graph for review.
  7. Applies atom granularity, entity resolution, relation resolution, and lifecycle policies.
  8. Commits approved candidates to the canonical graph.
  9. Assembles a project-manager user graph.
  10. Applies meeting-page and project-hub WikiProjectionSpec objects.
  11. Generates reviewable WikiRevision drafts with citations and graph lineage.
```

## 12.4 Candidate Graph Review Workflow

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
Compose or equivalent local orchestration should be available for Project MCP, Wiki MCP, raw data storage, and metadata storage when those services exist.
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

  schemas/
    asset.schema.json
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
      jobs.py
      observations.py
      extractors/
      storage/

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

formowl is a source-preserving, graph-governed knowledge management system that turns raw resources into governed wiki views:

```text
Raw Resources
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

## Core Principle

Project systems own execution state.

Wiki systems own published knowledge views.

Raw resources do not directly become final wiki pages. They first become observations, candidate graph proposals, governed canonical graph commits, user graph revisions, and projection-spec-driven wiki revisions.

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
1. Define StorageBackend, Asset, Observation, SemanticMetadata, IngestionJob, and ExtractorRun contract schemas
2. Add StorageBackendRegistry, AssetStore, ObjectStore, ObservationStore, and JobStore
3. Define User, SessionIdentity, WorkspaceMember, AccessRequest, Grant, AuditLog, and AuthProvider contracts
4. Implement Phase 0 ManualTrustedInternalAuthProvider for trusted internal deployment
5. Implement resource extraction for project data, markdown/wiki pages, ChatGPT sessions, document blocks, and mail archives
6. Add audio/video/image extractors behind the same Observation contract
7. Add PST/mail ingestion as Asset -> IngestionJob -> ExtractorRun -> Observation, with attachments as independent Assets
8. Define CandidateAtom, CandidateRelation, and ExternalGraphImport contract schemas
9. Implement candidate graph extraction and preview from observations
10. Define CanonicalAtom, CanonicalEntity, CanonicalRelation, and CanonicalGraphRevision contract schemas
11. Define ExtractionPolicy, AtomGranularityPolicy, EntityResolutionPolicy, RelationResolutionPolicy, LifecyclePolicy, and WikiProjectionPolicy
12. Implement granularity policy enforcement, entity resolution, and relation resolution
13. Define AtomLifecycleEvent, EntityResolutionEvent, and RelationResolutionEvent mappings
14. Implement reviewed canonical graph commits with provenance
15. Define UserGraphProfile, UserGraphAssemblyPolicy, and UserKnowledgeGraphRevision contract schemas
16. Implement user graph assembly policies, permissioned overlays, grants, and revision history
17. Define FusionCandidate, EntityResolutionProposal, EvidenceLink, EffectiveGraphView, ScopeAwareCanonicalGraph, and MergeDecision contracts
18. Implement matching, access overlay, and canonical merge as separate governed workflows
19. Define WikiProjectionSpec and add graph lineage fields to markdown frontmatter
20. Implement projection-spec-driven wiki generation from user graph revisions
21. Implement controlled Retrieval Gateway access for evidence snippets and raw assets
22. Implement usage-signal collection for split and merge proposals
23. Implement reviewed atom split, merge, archive, deprecate, supersede, and equivalence workflows
24. Add vector search and graph storage once the contract and review workflows stabilize
```

Implementation alignment cleanup order:

```text
1. Replace the JSON-line MCP-shaped prototype transport with standards-compliant MCP JSON-RPC over stdio or implement a compatibility gateway.
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

The target pipeline is usable when:

```text
Physical storage can be distributed across registered storage backends without fragmenting graph identity.
Raw resources can be registered as assets with permission scope and source lineage.
Resource extractors can create observations with location metadata and extractor runs.
Mail and PST ingestion can preserve archive, message, attachment, and occurrence identity.
Observations can produce CandidateBusinessObject and CandidateAssertion records through one source-neutral pipeline.
Candidate assertions distinguish property, relation, state, event, and coordination semantics.
Domain Packs are provenance-linked, content-hash-pinned, and map scoped vocabulary onto the closed core.
Candidate business-object and assertion ids pin Domain Pack and ontology lineage.
One candidate-knowledge extraction persists its Domain Pack, business objects, and assertions atomically.
Candidate extraction rejects cross-permission references, unsafe internal references, empty semantics, and non-core coordination mappings.
Every retrievable observation maps to a stable logical source item under an explicit source-identity policy and carries a source-version id, permission-scope id, and zero or more explicit context boundaries.
Candidate evidence retrieval requires a trusted access binding over eligible observation ids, source-identity policies, source versions, and permission scopes; missing bindings fail closed and request bindings cannot broaden an index binding.
Evidence cardinality and IDF count logical source items rather than parser chunks.
Multiple observations from one logical source item may jointly cover anchors without creating transitive links to other items.
Permission, source-identity-policy, source-version, context, time, epistemic, and lifecycle admissibility precede query planning and ranking.
Accessible contexts and explicitly selected query contexts remain separate; multi-context comparison requires explicit authorization.
Chronology distinguishes earliest/latest/range/before/after, returns the requested range cardinality, excludes undated evidence, and requires a query timezone for date-only boundaries.
Logical-source and observation budgets are independent.
Primary retrieval evaluation gold is recorded as stable logical source item ids,
not reconstructed from the current parser chunk ids. Exact observation
citation recall, precision, and stale/unmapped citation diagnostics are
reported separately and cannot change the primary pass/fail result.
Evidence ontology facets derive from observation type, modality, and semantic roles; numeric identifiers do not imply measurement.
Ontology-guided retrieval binds the ontology revision, signal vocabulary, and complete type/mapping contract.
Ontology guidance is a capped additive rerank and cannot remove lexically supported candidates or bypass candidate-only boundaries.
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
Do not generate final wiki pages directly from raw resources without observation, graph, projection, and review boundaries.
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
Do not make normal users switch into backend control planes, storage browsers, parser configuration screens, or worker queues.
Do not let source preparation guidance produce untracked local files without an UploadSession.
Do not treat Phase 0 manual identity selection as production authentication.
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
Raw Resources
  -> Observation / SemanticMetadata
  -> Candidate Graph
  -> Governed Canonical Graph
  -> User Knowledge Graph
  -> WikiProjection / WikiRevision
```

The current implementation uses two decoupled MCP servers:

```text id="kbd0ln"
Project MCP = project execution context
Wiki MCP = knowledge artifact lifecycle
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
Raw resources, assets, evidence snapshots, and citations remain source-of-truth and locator layers.
Physical storage may be distributed, but FormOwl asset and graph identity are centralized.
Observations and semantic metadata are extracted intermediate data.
Candidate graphs are reviewable proposals.
Canonical atoms, entities, and relations are reusable governed graph parts.
Canonical graph state is scope-aware; canonical within a scope does not mean canonical across all scopes.
User knowledge graphs are versioned assemblies for roles, tasks, permissions, and preferred granularity.
Wiki revisions are governed output artifacts generated through projection specs and review flows.
MCP exposes governed semantic operations, not raw storage, raw database
queries, parser controls, or worker internals.
Evidence retrieval counts source records, not parser chunks, and preserves
permission, context, time, ontology, and citation lineage before projection.
```

The architectural rule is:

> Preserve source evidence, create candidates, govern shared knowledge, and
> derive views. Never turn extraction, retrieval, or ontology scoring into an
> implicit canonical write.
