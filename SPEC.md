# FormOwl Specification

## 1. Authority and Maintenance Rule

This document is the canonical product, knowledge-method, and architecture
specification for FormOwl.

FormOwl must not evolve by appending a new section that silently overrides an
older model. When the product model changes, the affected canonical sections
must be rewritten, obsolete statements must be removed, and subordinate
documents must be realigned.

The reading order inside this document is intentional:

1. the generalized evidence-to-knowledge methodology;
2. the invariant boundaries that every domain and implementation must obey;
3. the governed knowledge model;
4. domain portability and ontology rules;
5. provenance, identity, access, storage, and service boundaries;
6. current implementation status and acceptance criteria.

Later implementation examples do not redefine the methodology. Procurement,
mail, finance, project management, and wiki examples are applications of the
same method, not separate product cores.

Subordinate specifications may provide implementation detail, but they may not
replace or contradict this document:

- `RESOURCE_EXTRACTION_SPEC.md`
- `docs/architecture.md`
- `docs/provenance.md`
- `docs/workflows.md`
- `docs/mcp-boundaries.md`
- `docs/infra-spec.md`
- `docs/wiki-draft-schema.md`

---

## 2. Product Purpose

FormOwl is a source-preserving, graph-governed knowledge system.

Its purpose is to turn heterogeneous evidence into knowledge that is:

- traceable to its source;
- explicit about time, context, confidence, and permission;
- reviewable before it becomes governed shared state;
- reusable across departments and domains;
- adaptable to different users and tasks; and
- projectable into answers, dashboards, reports, wiki pages, or reviewed action
  proposals.

The product is not an email system, procurement system, finance system, wiki
generator, or document parser. Those are source systems, domain applications,
or output surfaces that use the same knowledge methodology.

The canonical pipeline is:

```text
Any Source
  -> Asset / EvidenceSnapshot
  -> Observation
  -> Candidate Knowledge
       - Business Object
       - Property Assertion
       - Relation Assertion
       - State Assertion
       - Event Assertion
       - Coordination Frame
  -> Governance
       - identity and type resolution
       - granularity policy
       - permission and scope review
       - human or policy decision
  -> Governed Canonical Knowledge Graph
  -> User / Task Effective Graph View
  -> Projection or Reviewed Action Proposal
```

The shortest statement of the FormOwl methodology is:

> Convert any source into evidence-backed, time- and context-bound candidate
> assertions about business objects; govern those assertions before they become
> reusable knowledge; then assemble task-specific views without losing source
> lineage.

---

## 3. Generalized Evidence-to-Knowledge Methodology

## 3.1 Step 1: Register the Source

Every participating source must enter FormOwl through a governed source or
asset boundary.

Sources may include:

```text
email and mail archives
documents and PDFs
spreadsheets and tabular exports
images and scanned material
audio and video
meeting and conversation transcripts
project-management systems
finance and ERP systems
CRM, HR, legal, laboratory, or operational systems
wiki and documentation systems
sensor and machine observations
ChatGPT or other captured sessions
```

A source is evidence, not canonical knowledge.

The source layer records:

```text
source identity
source system and occurrence
content or response hash
capture time
owner and workspace scope
permission scope
retention policy
stable FormOwl locator
```

For a managed `Asset`, source-of-truth status requires both:

```text
verified durable bytes in the authoritative ObjectStore
authoritative Asset identity, tenant/workspace/owner scope, occurrence lineage,
lifecycle, retention, permission, and audit metadata in PostgreSQL
```

An ingress filename, temporary upload, storage blob, or content hash alone is
not a governed source identity. Identical bytes may be reused by the storage
adapter, but every governed acquisition and authorization context remains
separately represented.

Physical paths, buckets, database connections, worker scratch locations, and
parser commands are implementation details and must not become knowledge
identifiers or public MCP fields.

## 3.2 Step 2: Produce Citeable Observations

An `Observation` is the smallest source-derived unit that can be independently
located and cited.

Examples:

```text
document paragraph
table row or cell range
PDF page block
OCR region
image description
transcript segment
video scene
sensor reading
ERP transaction row
project issue comment
wiki section
email-authored paragraph
email inline table
```

An observation records what was found without claiming that the interpretation
is canonical truth.

Minimum observation semantics:

```text
observation_id
asset_id or evidence_snapshot_id
observation_type
modality or source family
raw or normalized extracted value
source locator
extractor run and version
observed_at or captured_at
permission_scope
confidence, when applicable
warnings and review requirement
```

Deterministic extraction and semantic interpretation are separate operations.
File hashes, MIME types, table cells, timestamps, and source identifiers should
be deterministic where possible. Claims, object mentions, events, risks,
decisions, and relationships may require semantic models, rules, or review.

## 3.3 Step 3: Identify Business Objects

A business object is the subject or object that knowledge is about.

Examples:

```text
Person
Organization
Project
Document
Agreement
Transaction
Account
Invoice
Payment
PurchaseOrder
Part
Asset
Task
Milestone
Machine
Measurement
Policy
```

Source text does not directly create a canonical object. It first creates a
`CandidateMention` and, when sufficient structure exists, a
`CandidateBusinessObject`.

Business object identity must remain separate from:

- source occurrence identity;
- access permission;
- canonical merge decisions; and
- user-specific labels or groupings.

Two mentions may refer to the same object without granting access or
authorizing a canonical merge.

## 3.4 Step 4: Create Candidate Assertions

Candidate knowledge is expressed as one of five universal assertion families.

### Property Assertion

Describes a value or characteristic of an object.

```text
Invoice amount is NTD 100,000.
Machine temperature is 85 degrees.
Document language is Chinese.
```

### Relation Assertion

Describes a relationship between objects.

```text
Invoice belongs to Project A.
Person B manages Cost Center C.
Part D is supplied by Organization E.
```

### State Assertion

Describes an object's state during a time or validity interval.

```text
Invoice is unpaid.
Order line is not accepted.
Machine is unavailable.
Task is blocked.
```

### Event Assertion

Describes a change or occurrence.

```text
Payment changed from pending to approved.
Delivery date changed from June 1 to July 15.
Machine crossed a temperature threshold.
Contract was signed.
```

### Coordination Frame

Describes how people or organizations coordinate work.

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

A candidate assertion should be able to express:

```text
assertion kind
subject business object or mention
predicate, property, relation, or frame type
value or object
actor and counterparty, when applicable
previous and proposed state, when applicable
observed, effective, valid, and due time
reason and context
source observation ids
permission scope
confidence
review state
ontology revision
```

`CandidateAssertion` is the semantic umbrella. The current contract may
represent an assertion through `CandidateAtom`, `CandidateRelation`,
`CandidateFrame`, `CandidateMention`, and `CandidateBusinessObject`. The
methodology is authoritative even when the implementation uses several
specialized contract classes.

## 3.5 Step 5: Govern Before Canonicalization

Extractor, rule, and LLM output is always candidate knowledge.

Before canonical commit, FormOwl applies:

```text
source and evidence validation
permission and scope filtering
business object resolution
type and ontology alignment
temporal normalization
contradiction and supersession checks
granularity policy
confidence and review policy
human or authorized policy decision
```

A candidate may be:

```text
accepted
rejected
corrected
split
merged with another candidate
deferred
marked ambiguous
superseded
```

No extractor or LLM may directly mutate:

```text
canonical graph state
canonical type state
user graph revisions
wiki revisions
external business systems
```

## 3.6 Step 6: Commit Governed Knowledge

Canonical knowledge is reusable, reviewed knowledge within a defined scope.

Canonical objects include:

```text
CanonicalAtom
CanonicalEntity
CanonicalRelation
CanonicalFrame
CanonicalGraphRevision
```

A canonical commit records:

```text
accepted and rejected candidate ids
source observation ids
evidence and source references
reviewer or approving policy
target scope
ontology revision
granularity and resolution policies
previous graph revision
new graph revision
commit time
```

Canonical does not mean universally true. Canonical state is scope-aware:

```text
owner graph
workspace graph
project graph
customer graph
grant-scoped shared fragment
```

Knowledge canonical in one scope may remain only a candidate or temporary
overlay in another.

## 3.7 Step 7: Assemble Effective Views

Users and tasks may require different valid views of the same governed
knowledge.

A user or task view may:

```text
include or exclude objects and assertions
select coarse or fine granularity
apply role- or task-specific labels
weight current attention or importance
add private notes
combine authorized graph overlays
redact inaccessible evidence
```

The result is a versioned `UserKnowledgeGraphRevision` or
`EffectiveGraphView`, not a mutation of the canonical graph.

Entity matching, data access, effective-view assembly, canonical merge, and raw
asset access are separate decisions.

## 3.8 Step 8: Project or Propose Action

Governed views may produce:

```text
answer with citations
dashboard or operational status view
review queue
report
wiki or document draft
risk or exception register
follow-up task proposal
project-system comment proposal
publish proposal
```

Projection is derived output. It must preserve evidence and graph lineage.

Writes to an external project, finance, wiki, or other business system are
proposal-only unless an explicitly configured and authorized workflow permits
execution after review.

---

## 4. Domain Portability

## 4.1 Stable Core and Scoped Domain Packs

FormOwl uses a stable methodological core and scoped domain packs.

```text
Evidence/source model
+ Observation model
+ universal assertion families
+ stable coordination-frame core
+ scoped domain object packs
+ governed projection definitions
```

A domain pack may define:

```text
business object types
preferred labels and aliases
mappings to core supertypes
domain relation types
domain process frames
validation and normalization rules
extraction hints
projection templates
```

A domain pack must not:

```text
replace the evidence-to-knowledge pipeline
bypass candidate governance
create an independent canonical graph
grant access
silently merge scopes
write external systems directly
turn one source format into a special ontology
```

## 4.2 Core Type System

The closed core remains small and domain-neutral.

Initial entity supertypes:

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
Core type
  closed and stable; the only hard compatibility gate

Extension type
  scoped candidate type; a soft signal only

Promoted type
  governed type canonical within a scope and mapped to a core type
```

Type objects include:

```text
TypeDefinition
TypeAlias
TypeMapping
TypeAlignmentCandidate
OntologyRevision
```

Type alignment across scopes is a candidate workflow. It does not imply access
or canonical type merge.

## 4.3 Cross-Domain Examples

The same assertion families apply across domains:

| Assertion family | Procurement | Finance | Project | Operations |
| --- | --- | --- | --- | --- |
| Property | order quantity | invoice amount | task priority | temperature |
| Relation | part supplied by vendor | invoice belongs to cost center | task belongs to project | machine belongs to line |
| State | order not accepted | invoice unpaid | task blocked | machine unavailable |
| Event | delivery date changed | payment approved | milestone delayed | threshold crossed |
| Coordination | supplier commitment | payment approval request | assignment | maintenance escalation |

Procurement and mail are evaluation fixtures, not core schemas. Finance, HR,
legal, engineering, research, and operations must use the same pipeline.

## 4.4 Domain Onboarding Method

Adding a domain follows this method:

1. collect representative governed evidence;
2. extract observations without adding domain truth;
3. annotate business object mentions and universal assertion families;
4. measure which concepts fit the stable core;
5. create the smallest scoped domain pack for residual vocabulary;
6. map domain types to core supertypes;
7. evaluate temporal, provenance, permission, and extraction correctness;
8. promote stable types or mappings only through governance;
9. define task-specific projections separately from canonical knowledge.

The domain-transfer acceptance rule is:

> Adding a new domain should not require a new ingestion, observation,
> governance, canonical lifecycle, permission, or provenance pipeline. It
> should normally require only source adapters, a scoped domain pack, evaluation
> evidence, and projections.

If a new domain requires changing the core, the change must be justified as a
general methodological gap rather than hidden inside the domain pack.

---

## 5. Knowledge and Graph Governance

## 5.1 Candidate Graph

Candidate graph objects include:

```text
CandidateMention
CandidateBusinessObject
CandidateAtom
CandidateRelation
CandidateFrame
ExternalGraphImport
FusionCandidate
EntityResolutionProposal
TypeAlignmentCandidate
EvidenceLink
```

Candidate objects must record:

```text
source observations
source and evidence references
generator or extractor metadata
confidence
permission scope
ontology revision
review state
```

External graph builders may write only to candidate or import-buffer stores.

## 5.2 Atom Granularity

A canonical atom is the smallest useful source-grounded knowledge unit that can
be cited, reviewed, reused, and assembled.

Atoms may represent:

```text
concept
definition
claim
decision
requirement
assumption
constraint
method step
evidence-backed state
risk
open question
exception
reified relationship or event
```

An atom should:

- remain understandable with its evidence context;
- be independently reviewable;
- be reusable across views;
- avoid unnecessary fragmentation; and
- preserve links to source observations.

Granularity is governed by a versioned `AtomGranularityPolicy`.

Potential split signals include repeated partial use, separable claims, local
review edits, and citations supporting different subclaims.

Potential merge signals include repeated co-use, near duplication, consistent
manual grouping, and no measurable retrieval or review benefit from separation.

## 5.3 Resolution

Entity and relation resolution may use:

```text
deterministic identifiers
normalized exact matching
aliases
fuzzy matching
embedding similarity
probabilistic record linkage
graph neighborhood evidence
type compatibility
LLM-assisted ambiguity adjudication
human review
```

Algorithms generate proposals. They do not commit canonical merges.

The required separation is:

```text
match proposal != data access
data access != canonical merge
canonical merge != raw asset access
```

## 5.4 Lifecycle

Knowledge changes are mappings and events, not destructive rewrites.

Lifecycle relations include:

```text
split_into
merged_into
summarized_by
supersedes
deprecated_by
equivalent_to
derived_from
archived_as
```

Old identifiers must remain resolvable for historical citations, graph
revisions, user views, and projections.

Lifecycle objects include:

```text
AtomLifecycleEvent
EntityResolutionEvent
RelationResolutionEvent
MergeDecision
CanonicalGraphCommit
```

## 5.5 Policy Families

Governed policy objects include:

```text
ExtractionPolicy
AtomGranularityPolicy
OntologyPolicy
EntityResolutionPolicy
RelationResolutionPolicy
LifecyclePolicy
UserGraphAssemblyPolicy
RetrievalPolicy
WikiProjectionPolicy
RetentionPolicy
```

Policies are versioned and scoped. A result that depends on a policy must pin
the relevant policy and ontology revisions.

---

## 6. Provenance, Time, Confidence, and Contradiction

## 6.1 Provenance Chain

Every derived object must be traceable through:

```text
Source / Asset / EvidenceSnapshot
  -> ExtractorRun
  -> Observation
  -> Candidate Knowledge
  -> Review Decision
  -> Canonical Commit
  -> User or Effective View
  -> Projection
```

Stable provenance identifiers include:

```text
asset_id
source_ref
evidence_snapshot_id
extractor_run_id
observation_id
candidate_id
review_event_id
canonical object id
graph_revision_id
user_graph_revision_id
projection_spec_id
wiki_revision_id
workspace_id
user_id
grant_id
```

Raw filesystem and object-store paths are not provenance identifiers.

## 6.2 SourceRef

`SourceRef` identifies an object in an external source system.

Minimum fields:

```text
source_system
source_type
source_id
```

Optional fields:

```text
source_instance
source_key
source_url
```

## 6.3 EvidenceSnapshot and Citation

`EvidenceSnapshot` records a governed capture from an external system or MCP
tool call.

It should include:

```text
evidence_snapshot_id
capturing service and operation
authenticated actor
captured_at
permission_scope
source_refs
request and response hashes
internal storage reference
```

A `Citation` links a generated statement or projection back to:

```text
SourceRef
EvidenceSnapshot
Observation locator
short evidence summary
```

Generated knowledge views must include citations or equivalent evidence
locators when they assert source-derived content.

## 6.4 Temporal Semantics

FormOwl must distinguish:

```text
captured_at       when FormOwl captured the source
observed_at       when the source observation was made
asserted_at       when an actor or system made the assertion
effective_at      when the assertion takes effect
valid_from/to     the interval in which a state is claimed to hold
due_at            a deadline
superseded_at     when a newer assertion replaced it
```

Raw time expressions must be retained when normalization is uncertain.

For example, values such as `TBD`, `TBC`, `9/E`, `next month`, or a date without
a year must not be silently coerced into a precise date. Store the raw value,
normalized candidate, precision, inference rule, and confidence.

## 6.5 Contradiction and Supersession

Conflicting assertions may coexist as candidates when they have different
sources, times, scopes, or confidence.

FormOwl must not erase an older assertion simply because a newer one exists.
It should record whether the newer assertion:

```text
confirms
corrects
contradicts
narrows
extends
or supersedes
```

Current-state views are projections over assertion history, not destructive
updates to evidence.

---

## 7. Identity, Permission, and Access

## 7.1 Connected Identity Boundary

The sole connected human identity path for the current internal closed beta is:

```text
public HTTPS /mcp
  -> OAuth protected-resource challenge
  -> FormOwl OAuth 2.1 authorization endpoint
  -> PKCE S256 and exact callback/resource validation
  -> Google OIDC login
  -> verified Google issuer/subject/email mapping through FormOwl invitation
  -> resource-bound FormOwl access token
  -> server-side authorization and revocation lookup
  -> fresh gateway-controlled ActorContext
  -> protected MCP tool
```

Google tokens are not FormOwl MCP bearer tokens. Google authenticates the human;
FormOwl remains the authority for users, invitations, memberships, clients,
token sessions, workspaces, grants, revocation, and audit.

The predefined ChatGPT OAuth client must use PKCE S256, an exact registered
redirect URI, and the exact canonical FormOwl resource. Its predefined client
ID is a stable non-secret value selected and recorded by the deployment
operator before discovery. ChatGPT app management must use that same value if
its current predefined-client UI supports entry or selection; if it does not,
the live flow stops as an external blocker. ChatGPT supplies and displays only
the exact production callback
`https://chatgpt.com/connector/oauth/{callback_id}`. Operators must never invent
the ID or claim ChatGPT generated or displayed it. The current FormOwl
closed-beta design remains a predefined client and does not claim a CIMD
migration or DCR fallback.

Production FormOwl access tokens use a fixed 3600-second lifetime and a fixed
30-second validation clock skew. Expiry evidence must wait until trusted UTC is
strictly later than `expires_at + 30 seconds`; operators must not shorten the
lifetime or move clocks to accelerate the journey.

The connected service uses the official MCP SDK's stateless Streamable HTTP
transport on exact `/mcp`. OAuth protected-resource metadata,
authorization-server metadata, JWKS, authorization routes, and `/mcp` must
agree on the same canonical public HTTPS origin.

Every protected call must build a fresh `ActorContext` from current PostgreSQL
state. The context binds the FormOwl user, upstream external identity, OAuth
client and token-session lineage, current workspace and role, memberships, and
active grants.

Caller-controlled identity, workspace, session, grant, storage, parser, and
worker fields must be rejected or ignored in favor of gateway authority.

Authentication alone does not authorize access to an Asset, raw byte stream,
evidence snippet, graph fragment, or canonical mutation. `whoami` may report
only the authenticated FormOwl identity and current authorized workspace
context.

## 7.2 Identity Contracts

Identity objects include:

```text
User
ExternalIdentity
SessionIdentity
WorkspaceMember
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

`ManualTrustedInternalAuthProvider`, JSON-line commands, hand-built JSON-RPC,
stdio identity variables, and `manual_trusted_internal` selection exist only
for tests and local compatibility. They are not valid connected deployment
modes.

## 7.3 PermissionScope

Every source, observation, candidate, canonical object, user view, and
projection must carry or derive a permission scope.

Common scopes:

```text
private_user
owner
project
team
workspace
customer
grant_scoped
public
restricted
unknown
```

Unknown or missing scope fails closed.

## 7.4 Access Levels

Sharing may distinguish:

```text
answer only
graph summary
graph snippet
evidence snippet
controlled raw asset reference
```

Raw access requires an explicit grant and may expose only governed FormOwl
locators such as:

```text
formowl://asset/{asset_id}
formowl://observation/{observation_id}
formowl://evidence/{evidence_id}
```

Permission to see a graph assertion does not automatically grant permission to
the underlying raw asset.

## 7.5 Audit

Security-sensitive reads, denials, reviews, commits, grants, revocations, and
external write proposals must be auditable.

An `AuditLog` records:

```text
actor type and actor id
session and OAuth lineage
workspace
action
target type and id
grant, request, and tool-call lineage
reason code
timestamp
```

Audit failure must not produce an unaudited success or partial mutation.

---

## 8. Asset, Storage, and Extraction Boundary

## 8.1 Storage Principle

```text
Physical storage may be distributed.
Knowledge and authorization identity must be centralized.
```

PostgreSQL is the authority for:

```text
Asset identity and tenant/workspace/owner scope
Asset authorization, grants, and permission scope
AssetOccurrence and AssetRelationship lineage
Asset lifecycle events, retention, legal hold, redaction, and purge state
normalized observations
candidate and canonical graph state
ontology and policy revisions
jobs and extractor runs
identity, permission, grants, and audit
review and projection metadata
```

Object storage holds:

```text
authoritative managed source bytes
retention-controlled source archives
large derived media
attachment bytes
```

Raw bytes should not be stored in PostgreSQL by default merely because their
normalized content is queryable there.

Ingress, quarantine, and worker scratch are bounded processing roles, not
authoritative durable storage. Their cleanup policies are separate from Asset
retention and purge policies.

## 8.2 Asset Boundary

Every source that participates in extraction, graph construction, search, or
projection must be registered as an `Asset` or governed external evidence
capture.

Asset identity, byte-level deduplication, occurrence identity, ownership, and
authorization are separate concepts.

`Asset` is the stable governed identity used by extraction, graph, search, and
projection layers. It includes:

```text
asset_id
tenant_id
workspace_id
owner_scope_type and owner_scope_id
owner_user_id
storage_backend_id and internal object locator
content_hash, size, MIME type, and original filename
permission_scope
lifecycle_state
retention_policy_id and retention_until
legal_hold, redaction, and purge state
```

The public locator is `formowl://asset/{asset_id}`. Bucket/key pairs, NAS paths,
local paths, ingress filenames, and provider URLs are internal adapter details,
not Asset identity.

`AssetOccurrence` records each governed appearance or acquisition of an Asset,
including tenant/workspace/owner scope, source reference, import or upload
session, permission scope, and parent occurrence when applicable.

`AssetRelationship` records parent-child and derivation lineage such as:

```text
uploaded_as
attached_to
embedded_in
exported_from
captured_from
derived_from
```

`AssetLifecycleEvent` records every state transition with the prior and next
state, reason, governing policy, actor or service identity, audit event, and
timestamp. Lifecycle history is appended, not rewritten.

`RetentionPolicy` governs the durable managed copy independently of ingress or
scratch cleanup. It defines retention basis and period, legal-hold behavior,
redaction behavior, and purge behavior for the applicable tenant and optional
workspace scope.

Recommended lifecycle states include:

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

Byte/blob deduplication and governed identity must remain separate:

```text
same content_hash -> storage may reuse one immutable byte blob
same content_hash -> does not merge Asset ids, owners, workspaces, permissions,
                     grants, retention policies, lifecycle, or occurrences
same nested file in multiple parents -> preserves every occurrence and
                                       parent relationship
```

Nested attachments, archive members, and embedded documents become child
Assets with their own `AssetOccurrence` and `AssetRelationship` lineage. The
child routes through its detected MIME extractor; blob reuse must not replace
the child Asset or its occurrence history.

Issue #41 owns the generic Asset tenant, owner, lifecycle, retention, rollback,
purge, and authorization boundary. A domain adapter must not invent a parallel
asset system.

## 8.3 UploadSession

User-initiated file ingestion begins with an `UploadSession`.

It captures:

```text
authenticated actor
owner, workspace, project, and customer scope
intended source family
ingestion profile
visibility
expiration
preparation guidance
processing state
```

FormOwl selects storage backend, parser, and worker. Normal users do not choose
NAS paths, buckets, parser commands, SQL, or worker queues.

The durable activation sequence is:

```text
bounded ingress or UploadSession body
  -> stability, size, type, security, archive, and policy checks
  -> content hash
  -> durable ObjectStore write
  -> checksum or read-after-write verification
  -> PostgreSQL Asset, AssetOccurrence, relationship, permission, lifecycle,
     and required audit commit
  -> Asset activation
  -> post-commit ingress cleanup
  -> IngestionJob / ExtractorRun
```

Extraction may begin only after the required durable byte and metadata commit
has succeeded. No successful metadata may point to missing bytes, and no
unverified object may be exposed as an active Asset.

The upload workflow must be recoverable across process or container failure:

```text
failure before durable verification -> retain or quarantine recoverable ingress
failure after object write but before metadata commit -> compensate safely or
                                                        record an orphan for reconciliation
failure during metadata or audit commit -> roll back the transaction and do not activate
failure after activation but before ingress cleanup -> keep the active Asset and
                                                      retry idempotent cleanup
startup/reconciliation -> resume staged commits, repair safe partial state,
                          quarantine ambiguity, and purge confirmed orphan blobs
                          only after lineage, retention, legal-hold, and audit checks
```

Activation, rollback, orphan recovery, ingress cleanup, retention expiry,
redaction, and purge are distinct lifecycle operations. Recovery must be
idempotent and must never merge authorization merely because two pending items
share a content hash.

## 8.4 Resource Extraction

Resource extraction converts registered sources into governed intermediate
representations.

Workers resolve registered Assets through `asset_id` and internal adapters, not
through caller-supplied paths. When extraction discovers a nested resource, it
requests the same durable child-Asset commit and activation workflow before
the child is routed to another extractor.

It may write:

```text
AssetStore
ObservationStore
SemanticMetadataStore
Candidate stores
ExtractorRunStore
JobStore
```

It must not write:

```text
CanonicalGraphStore
UserKnowledgeGraph
WikiRevision
external business-system state
```

Extractor routing, provenance, location metadata, modality-specific behavior,
mail occurrence rules, and re-extraction behavior are defined in
`RESOURCE_EXTRACTION_SPEC.md`.

## 8.5 Source Formats Are Adapters, Not Ontologies

Email, PDF, spreadsheet, image, project-system record, finance transaction,
meeting transcript, and sensor event are source substrates.

They may require different extractors, but all must emit the same observation
and candidate-knowledge methodology.

For example:

```text
email authored text
spreadsheet row
PDF table
ERP transaction
meeting statement
```

may all support the same `PaymentCommitment`, `Deadline`, `StatusChange`, or
`Exception` candidate.

Mail-specific normalized evidence may live in PostgreSQL, while raw archives
and attachments follow generic Asset retention. Mail is not a second knowledge
pipeline.

---

## 9. Component Responsibilities

## 9.1 FormOwl MCP Gateway

The connected FormOwl MCP Gateway is the sole public ChatGPT-facing service
boundary.

It owns:

```text
OAuth-protected exact /mcp transport
fresh ActorContext resolution
public tool schemas
permission and grant enforcement
safe result envelopes
audit
dispatch to governed services
raw/internal leak prevention
```

It does not expose raw storage, SQL, parser, worker, or backend controls.

## 9.2 Project MCP Compatibility Service

Project MCP provides project execution evidence from systems such as
OpenProject.

It owns:

```text
project and work-item lookup
comments, activities, relations, and attachment metadata
project status evidence capture
ContextPackage generation
proposal-only project writes
```

It does not own the universal knowledge model or wiki lifecycle.

Its JSON-line entrypoint is local compatibility only.

## 9.3 Wiki MCP Compatibility Service

Wiki MCP manages governed knowledge artifacts.

It owns:

```text
wiki and markdown lookup
draft and revision lifecycle
citations and frontmatter
projection-spec-driven generation
human-readable diffs
review, restore, and publish proposals
backend-specific wiki adapters
```

Wiki is one projection surface. `WikiRevision` is not the canonical graph or a
user's complete knowledge graph.

Its JSON-line entrypoint is local compatibility only.

## 9.4 Knowledge Graph Assembly

Graph assembly owns:

```text
candidate preview
assertion and object resolution
granularity and ontology policy
review workflow
canonical commits
lifecycle events
user graph assembly
effective graph views
```

## 9.5 Retrieval Gateway

Cross-resource retrieval uses:

```text
query
  -> query-scored permission-filtered EffectiveGraphView
  -> source observation resolution
  -> evidence coverage decision
  -> fallback retrieval only for miss, low confidence, or incomplete evidence
  -> review-required candidate seeds
```

Graph labels alone are not sufficient evidence for a high-trust answer.
Supporting observations must resolve under current permission.

Fallback retrieval must not create hidden candidate or canonical writes.

## 9.6 Worker and Storage Layer

Heavy extraction runs outside the MCP request lifecycle.

Workers receive stable FormOwl asset and object references, use policy-selected
extractors, and report versioned runs and observations. Worker locality and
scratch paths are operational details.

---

## 10. Portable Contract Model

`formowl_contract` is the shared schema boundary.

Core source and evidence contracts:

```text
SourceRef
EvidenceSnapshot
EvidenceSnapshotRef
Citation
PermissionScope
ContextPackage
MCPResultEnvelope
```

Asset and extraction contracts:

```text
StorageBackend
Asset
AssetOccurrence
UploadSession
IngestionJob
ExtractorRun
Observation
SemanticMetadata
```

Candidate knowledge contracts:

```text
CandidateMention
CandidateBusinessObject
CandidateAtom
CandidateRelation
CandidateFrame
ExternalGraphImport
FusionCandidate
EntityResolutionProposal
EvidenceLink
TypeAlignmentCandidate
```

Canonical and lifecycle contracts:

```text
CanonicalAtom
CanonicalEntity
CanonicalRelation
CanonicalFrame
CanonicalGraphRevision
AtomLifecycleEvent
EntityResolutionEvent
RelationResolutionEvent
MergeDecision
OntologyRevision
```

User and projection contracts:

```text
UserGraphProfile
UserGraphAssemblyPolicy
UserKnowledgeGraphRevision
EffectiveGraphView
WikiProjectionSpec
WikiRevision
```

Identity and access contracts:

```text
User
ExternalIdentity
SessionIdentity
WorkspaceMember
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

No MCP service should depend on another service's private types.

## 10.1 ContextPackage

`ContextPackage` is a portable, evidence-bearing compatibility handoff.

It carries:

```text
context identity and type
context markdown or structured payload
source refs
evidence snapshot ids
citations
permission scope
```

It is useful before full graph assembly and must preserve enough lineage for
later observation and candidate extraction.

## 10.2 MCPResultEnvelope

Public tool results use a shared envelope with:

```text
result_type
status
data
context package, when applicable
source refs
evidence snapshot ids
citations
permission scope
warnings
```

Statuses include:

```text
ok
partial
not_found
permission_denied
pending_review
error
```

Error results must not expose raw paths, SQL, credentials, backend endpoints,
parser commands, or private evidence.

---

## 11. MCP Tool and Action Boundary

## 11.1 Current Connected Semantic Surface

The connected runtime exposes `whoami` and whichever governed handlers are
configured. The current semantic set includes:

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

`query_effective_graph_view` is the canonical effective-view query surface.
`query_effective_graph` remains a deprecated compatibility alias.

`select_actor` is not a connected tool.

## 11.2 Planned Generalized Tools

Planned tool families include:

```text
source capture and upload
asset and ingestion status
observation retrieval
candidate assertion and object preview
review decisions
type and ontology governance
effective graph search
evidence retrieval
access request and grant lifecycle
projection and external write proposals
```

Tool names may evolve, but they must preserve the methodology and boundaries in
this specification.

## 11.3 Forbidden Tool Shapes

ChatGPT-facing tools must not expose:

```text
list_nas_folder(path)
read_file(path)
open_smb_path(path)
download_raw_archive(path)
mount_share()
run_parser_on_path(path)
query_postgres_raw(sql)
choose_storage_backend(name)
choose_parser_path(path)
choose_worker_queue(name)
```

MCP is an orchestration and review interface, not the data-processing engine or
infrastructure control plane.

## 11.4 External Writes

External writes are reviewable proposals by default.

Examples:

```text
project comment proposal
work-item update proposal
wiki publish proposal
finance or ERP adjustment proposal
access approval proposal
canonical graph commit proposal
```

An executed write requires an explicit authorization path, current permission,
validated target, audit, and protection against partial mutation.

---

## 12. Projection and WikiRevision

A projection converts an effective graph view and evidence into a task-specific
artifact.

`WikiProjectionSpec` defines:

```text
projection identity and kind
target entity or query
source graph and ontology revisions
optional user graph revision
sections and filters
citation behavior
redaction policy
generator policy
review requirements
target backend
```

`WikiRevision` records one output revision.

Rules:

```text
reviewed and published revisions are immutable
refresh creates a new draft and diff
restore creates a new revision
private notes are not published without explicit inclusion and permission
Git is an optional backend detail, not a required user workflow
```

The same projection method may generate a wiki page, status report, finance
brief, risk register, or operational dashboard. Wiki is not the only valid
projection.

Detailed frontmatter and wiki lifecycle fields are defined in
`docs/wiki-draft-schema.md`.

---

## 13. Current Implementation Boundary

The current repository provides:

```text
Python contract and policy models
Asset, ingestion job, extractor run, and observation workflows
deterministic fixture extractors for multiple modalities
candidate atoms, relations, mentions, frames, and business objects
scoped ontology contracts and candidate-only resolution helpers
canonical graph contract models
user graph and effective-view contracts
graph-derived wiki projection
Project MCP and Wiki MCP compatibility services
OpenProject and wiki adapter boundaries
PostgreSQL adapter contracts and migrations
file-backed compatibility stores
governed retrieval and mail-evidence workflows
container-first development and runtime images
connected FormOwl MCP Gateway on exact /mcp
Google OIDC-backed FormOwl OAuth 2.1
gateway-controlled ActorContext and whoami
```

The current tested product path includes:

```text
Project evidence
  -> ContextPackage and EvidenceSnapshot
  -> Wiki MCP
  -> sourced markdown draft
```

The extraction and graph path includes implemented slices of:

```text
Asset
  -> IngestionJob
  -> ExtractorRun
  -> Observation
  -> candidate knowledge
  -> effective graph and governed projection
```

Implementation evidence does not imply:

```text
general production readiness
automatic canonical graph writes
automatic external business decisions
full real-world parser coverage
enterprise-scale latency or scalability
completed KG real-evidence acceptance
```

## 13.1 Connected Identity Status Boundary

The repository contains deterministic and container-backed OAuth/MCP evidence.

Issue #20 may be marked complete only after accepted external evidence covers
the configured public HTTPS origin, real Google accounts, the ChatGPT app,
MCP Inspector, restart behavior, multi-user journeys, revocation, key rotation,
documentation agreement, the configured reviewer gate, the independent
completion audit, and the governed post-audit completion transition.

Issue #20 establishes connected identity and `ActorContext`. It does not
complete issue #41's generic Asset tenant, owner, byte-storage, occurrence,
retention, lifecycle, purge, or authorization boundary.

## 13.2 Mail Status Boundary

Mail is one source adapter and evaluation domain.

Normalized mail evidence may support retrieval and candidate extraction, but
mail parsing must not directly create canonical graph state, user graph
revisions, wiki revisions, or business answers.

Existing mail and PST evaluations demonstrate bounded repository behavior for
specified fixtures. They do not establish universal parser or production
readiness.

---

## 14. Runtime, Language, and Development Policy

FormOwl is container-first.

The canonical development, verification, and deployment environments are
Dockerfile-managed containers. Host tools are optional conveniences.

Phase 0 implementation language:

```text
Python
```

Python owns:

```text
MCP and service orchestration
adapter boundaries
contracts and validation
workflow and governance logic
hashing and diff helpers
tests and evaluation harnesses
human-readable diagnostics
```

TypeScript and Rust are not current runtime stacks.

A systems language may be introduced only after a specification change and a
concrete need such as a large binary parser, memory-sensitive transform,
validated performance bottleneck, or safety boundary.

Implementation must remain readable. Complex parser or model internals should
be hidden behind clear Python interfaces.

The canonical test command is:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local \
  python -m unittest discover -s tests
```

---

## 15. Example Applications

These examples illustrate the methodology. They are not separate architectures.

## 15.1 Procurement

```text
supplier email / spreadsheet / PDF / ERP row
  -> observations
  -> PurchaseOrderLine candidate object
  -> delivery StateAssertion
  -> rejection or commitment Event/CoordinationFrame
  -> reviewed current-state view
  -> exception dashboard or follow-up proposal
```

## 15.2 Finance

```text
invoice / ERP transaction / approval message / bank record
  -> observations
  -> Invoice and Payment candidate objects
  -> amount PropertyAssertion
  -> project RelationAssertion
  -> payment StateAssertion and approval EventAssertion
  -> reviewed finance graph view
  -> reconciliation or approval projection
```

## 15.3 Project Work

```text
work item / comment / meeting transcript
  -> observations
  -> Task and Milestone objects
  -> Assignment, Blocker, Decision, and Deadline frames
  -> governed project view
  -> sourced project brief or comment proposal
```

## 15.4 Operations

```text
sensor / machine log / image / maintenance report
  -> observations
  -> Machine and Measurement objects
  -> property and state assertions
  -> threshold-crossing event and maintenance escalation
  -> governed operational view
  -> alert or maintenance proposal
```

---

## 16. Acceptance Criteria

## 16.1 Methodology Acceptance

The generalized methodology is satisfied when:

```text
multiple source formats produce citeable observations through adapter boundaries
candidate knowledge distinguishes properties, relations, states, events, and coordination
business objects are resolved separately from access and canonical merge
raw values, normalized values, time precision, confidence, and evidence are preserved
candidate outputs cannot silently mutate canonical knowledge
canonical commits are scoped, reviewed, revisioned, and traceable
user and task views do not rewrite canonical state
projections preserve citations and graph lineage
adding a new domain normally requires only adapters, a domain pack, evaluation, and projections
```

Cross-domain acceptance must include at least two materially different domains.
Procurement/mail alone is not sufficient proof of generality. A finance or
another non-mail domain should be used as a transfer evaluation.

## 16.2 Source and Extraction Acceptance

```text
raw or externally captured evidence remains traceable
extractor provenance and location metadata are recorded
deterministic and semantic extraction remain separate
re-extraction creates a new run instead of overwriting history
source adapters cannot directly write canonical graph, user graph, or projections
large raw bytes remain outside PostgreSQL by default
managed bytes are verified in the authoritative ObjectStore before Asset activation
PostgreSQL preserves Asset tenant/workspace/owner scope, permission, occurrence,
relationship, lifecycle, retention, legal-hold, and audit authority
failed durable commits cannot produce active metadata pointing to missing bytes
rollback and restart recovery preserve staged inputs and reconcile orphan blobs safely
post-commit ingress cleanup is idempotent and separate from durable retention
nested resources preserve child Asset, occurrence, parent, import, and derivation lineage
byte/blob deduplication never merges Asset ids, permissions, grants, ownership,
retention, lifecycle, or occurrence history
redaction and purge require policy, authorization, legal-hold, lineage, and audit checks
```

## 16.3 Governance Acceptance

```text
candidate review actions are explicit
canonical commits pin ontology and policy revisions
contradictions and supersession remain historically resolvable
split, merge, archive, and deprecation preserve lineage
external algorithms generate proposals only
```

## 16.4 Permission Acceptance

```text
permission scope propagates through every layer
unknown scope fails closed
cross-scope matching does not grant access
graph access does not grant raw asset access
revocation changes effective views without rewriting source evidence
denials and sensitive operations are audited
```

## 16.5 Connected Identity Acceptance

Repository completion requires:

```text
exact public HTTPS /mcp resource
matching OAuth metadata
PKCE S256 and exact callback/resource binding
Google issuer and subject mapped through FormOwl invitation
Google tokens rejected as FormOwl MCP bearer tokens
signed short-lived resource-bound FormOwl tokens backed by server-side sessions
fresh ActorContext on every protected call
caller identity and workspace forgery rejected
revocation, expiry, disabled users or external identities, revoked client authorization, and removed membership fail closed
manual trusted and local compatibility paths unavailable in connected mode
```

Issue #20 completion additionally requires the documented external evidence and
review gates.

## 16.6 Product-Surface Acceptance

```text
normal users operate through task-oriented actions
backend paths, SQL, storage selection, parser controls, and worker controls are hidden
external writes are proposal-first
answers and projections include citations or evidence locators
technical backends such as Git are optional audit details, not required user workflows
```

---

## 17. Non-Goals

FormOwl must not:

```text
become a separate hard-coded system for every department
make email or mail a special knowledge ontology
create one ingestion and graph pipeline per domain
treat source text, parser output, or LLM output as canonical truth
flatten every semantic distinction into an ungoverned JSON blob
require a graph database before contracts and governance stabilize
adopt a large top-down company ontology in v1
let domain packs bypass the stable core
silently merge private or cross-scope graphs
treat matching as authorization
treat graph access as raw asset access
expose raw infrastructure through MCP
perform automatic project, finance, wiki, or canonical writes without authorization and review
require non-technical users to understand Git, databases, buckets, parsers, or worker queues
introduce another runtime language without a specification change
use ingress, quarantine, or worker scratch as permanent Asset storage
activate an Asset before durable byte verification and authoritative metadata/audit commit
delete recoverable ingress merely because an object write or parser step started
let byte/blob deduplication merge Asset ids, ownership, permissions, grants,
retention, lifecycle, or occurrence lineage
equate ingress cleanup, scratch cleanup, retention expiry, redaction, and purge
purge durable bytes while legal hold, authorization, lineage, or audit gates remain unresolved
expose bucket names, object keys, provider URLs, storage credentials, or local
paths as public Asset identity
```

---

## 18. Final Architecture Statement

FormOwl has one generalized methodology:

```text
Any Source
  -> Governed Asset / AssetOccurrence or EvidenceSnapshot
  -> Source-Preserving Observation
  -> Evidence-Backed Candidate Assertion
  -> Governed Canonical Knowledge
  -> Permission-Aware User or Task View
  -> Cited Projection or Reviewed Action Proposal
```

The core question is not whether the source is an email, spreadsheet, finance
system, document, meeting, image, sensor, or project issue.

The core questions are:

```text
What object is this evidence about?
What property, relation, state, event, or coordination does it assert?
At what time and in what context is the assertion claimed?
What evidence, confidence, scope, and policy support it?
Has it been reviewed strongly enough to become governed knowledge?
Which users and tasks are allowed to see which view of it?
```

Procurement, finance, HR, legal, project management, research, and operations
are domain packs and evaluation settings over this same architecture.

This methodology, rather than any single source format, department, MCP
service, or output surface, is the center of FormOwl.
