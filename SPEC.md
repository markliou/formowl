# FormOwl Specification

## 1. Authority and Maintenance

This is the canonical product, knowledge-method, and architecture specification
for FormOwl.

When the product model changes, rewrite the affected canonical sections and
realign subordinate documents. Do not append a later exception that silently
leaves an older architecture looking active. Historical detail belongs in a
dated immutable archive, not in the current specification.

Current subordinate specifications are:

- `RESOURCE_EXTRACTION_SPEC.md`
- `docs/architecture.md`
- `docs/workflows.md`
- `docs/mcp-boundaries.md`
- `docs/provenance.md`
- `docs/infra-spec.md`
- `docs/wiki-draft-schema.md`
- `docs/kg-research-method.md`
- `docs/kg-ontology-v2-rd-boundary.md`
- `docs/kg-ontology-v2-runtime-evaluation-plan.md`
- `docs/methodology-authority.json`

The machine-readable methodology authority and its executable checker govern
whether comparative KG/ontology claims are permitted. Prose cannot override a
blocked gate.

---

## 2. Product Purpose

FormOwl is a source-preserving, graph-governed knowledge system for integrating
heterogeneous evidence.

It turns source material into knowledge that is:

- traceable to source occurrences;
- explicit about time, context, confidence, revision, and permission;
- reviewed before it becomes governed shared state;
- reusable across source systems and business domains;
- adaptable to different users and tasks; and
- projectable into cited answers, reports, dashboards, wiki drafts, review
  queues, or authorized action proposals.

FormOwl is not an email system, a document parser, a graph database product, or
a wiki generator. Mail, documents, calendars, tickets, project systems,
databases, finance systems, media, and future adapters are source families over
one common method.

---

## 3. Canonical Architecture

FormOwl has a knowledge-construction path and a query-execution path.

### 3.1 Knowledge construction

```text
heterogeneous sources
  -> Asset / EvidenceSnapshot
  -> ExtractorRun
  -> source-preserving Observation
  -> candidate mentions, entities, claims, relations, and frames
  -> review and governance
  -> canonical KG + scoped ontology revisions
  -> permission-filtered EffectiveGraphView
```

### 3.2 Query execution

```text
user prompt + bounded conversation state
  -> core Query Agent
  -> intent and coreference resolution
  -> actual source-schema, scoped-ontology, and current MCP-capability discovery
  -> candidate query expansion
  -> one or more validated SemanticQueryPlans and tool plans
  -> authorized execution
  -> requested-field and evidence-coverage inspection
  -> bounded adaptive repair or requery
  -> compact rich evidence context
  -> deterministic result or citation-grounded answer
```

The core Query Agent is the governed orchestrator of this path, not a license
for an LLM to bypass deterministic contracts. It receives only the current
prompt and an explicit, bounded, versioned conversation-state envelope.
Coreference must be resolved before an MCP query is issued, or transmitted as
validated explicit state when the tool contract supports it. An MCP tool must
never infer hidden conversation history from an under-specified `query_text`.

The method remains intentionally hybrid:

- strong RAG recovers source evidence;
- the KG contributes identity, cross-source joins, bounded topology, temporal
  structure, contradiction, provenance, and reusable integration semantics;
- the ontology contributes scoped vocabulary, reviewed mappings, plan
  validation, and a capped ranking prior;
- deterministic structured execution owns exact-set and completeness claims;
- the answer model explains the authorized result and does not invent missing
  evidence.

The Query Agent does not place every authorized record into model context. It
selects and stops retrieval according to requested-field coverage, evidence
diversity, contradiction and provenance needs, claim strength, and frozen
budgets. Query expansions are candidates only: they cannot grant access, widen
source scope, write canonical state, or convert public-web material into
internal fact.

No source adapter, extractor, LLM, retrieval path, or projection may bypass the
separation between evidence, candidate interpretation, governed canonical
state, effective views, and outputs.

---

## 4. Source, Asset, and Observation Model

### 4.1 Source registration

Every participating source enters FormOwl through a governed `Asset`,
governed external capture, or `EvidenceSnapshot` boundary.

Source families may include:

```text
mail and mail archives
calendar and meeting systems
tickets and project systems
documents, PDFs, slides, and spreadsheets
databases, ERP, CRM, HR, legal, and finance systems
wiki and documentation systems
images, OCR, audio, video, and transcripts
source repositories and operational records
sensor and machine observations
captured ChatGPT or other conversations
```

A source record preserves:

```text
source identity and source-system occurrence
content or response hash
capture and observation time
owner, workspace, project, customer, and grant scope
permission and retention policy
stable FormOwl locator
```

Raw filesystem paths, buckets, connection strings, SQL, parser commands, and
worker scratch locations are implementation details. They are not public
knowledge identifiers.

### 4.2 Observation

An `Observation` is the smallest independently locatable and citeable unit
produced from a source.

Examples include:

```text
document paragraph or table cell range
PDF page block or OCR region
spreadsheet row
transcript segment or video scene
project comment or ticket event
calendar occurrence
ERP transaction row
email-authored paragraph or attachment occurrence
```

An Observation records what the source exposed; it does not assert canonical
truth. Minimum semantics are:

```text
observation_id
asset_id or evidence_snapshot_id
source_ref and source occurrence
observation type and source family
raw and normalized extracted value
source-native locator
extractor run, version, configuration, and model metadata
captured_at, observed_at, and source time where available
permission scope
confidence, warnings, and review requirement
```

Deterministic extraction and semantic interpretation are separate operations.
Hashes, identifiers, timestamps, table coordinates, and source locators should
be deterministic where possible. Claims, events, relationships, risks, and
other interpretations remain semantic candidates.

### 4.3 Source completeness

Graph ranking cannot repair missing source evidence. Before methodology-quality
evaluation, an authorized Observation snapshot must be reconciled against a
raw-source or source-system oracle.

Every missing source unit is classified as:

```text
policy redaction
unsupported source feature
extractor failure
normalization loss
deduplication or occurrence-lineage loss
unknown unexplained loss
```

Only intentional policy redaction may be absent without failing the source
completeness gate. Each adapter preserves its source-native occurrence identity
while mapping shared semantics into the graph.

Detailed extraction rules are in `RESOURCE_EXTRACTION_SPEC.md`.

---

## 5. Candidate Knowledge and Governance

### 5.1 Universal candidate families

Source observations may produce candidate business objects and five assertion
families:

```text
PropertyAssertion
RelationAssertion
StateAssertion
EventAssertion
CoordinationFrame
```

A candidate assertion can express:

```text
subject or candidate business object
predicate, property, relation, frame, or value
actor and counterparty
previous, current, and proposed state
observed, asserted, effective, valid, due, and superseded time
reason and context
source observation IDs and occurrences
permission scope
confidence and review state
ontology, policy, extractor, prompt, and model revisions
```

The implementation may represent these through `CandidateMention`,
`CandidateBusinessObject`, `CandidateAtom`, `CandidateRelation`, and
`CandidateFrame`. These are proposals, not truth.

Candidate cardinality is zero-to-many at both the source document and
Observation boundaries. One document or Observation may therefore produce no
semantic annotation, or any number of source-addressed annotations, candidate
atoms, candidate entities/business objects, relations, and frames. A candidate
may span multiple Observations, but every candidate keeps the contributing
Observation IDs and source occurrences; no layer may impose a one-annotation-
per-document or one-annotation-per-Observation rule.

### 5.2 Candidate-before-canonical rule

Before canonical commit, FormOwl applies:

```text
source and evidence validation
permission and scope filtering
entity and relation resolution
type and ontology alignment
temporal normalization
contradiction and supersession analysis
granularity policy
confidence and review policy
human or authorized policy decision
```

A candidate may be accepted, rejected, corrected, split, merged with another
candidate, deferred, marked ambiguous, or superseded.

No extractor or LLM may directly mutate:

```text
canonical graph state
canonical type or ontology state
user graph revisions
wiki revisions
external business systems
```

### 5.3 Canonical knowledge

Canonical knowledge is reviewed, reusable knowledge within a declared scope.
Canonical does not mean universally true.

Possible scopes include:

```text
owner
workspace
project
customer
grant-scoped shared fragment
```

A canonical commit records:

```text
accepted and rejected candidate IDs
source observation IDs and occurrences
source refs and evidence snapshots
reviewer or approving policy
permission and target scope
ontology and policy revisions
previous and new graph revisions
commit time and audit lineage
```

Entity matching, data access, canonical merge, and raw asset access are separate
decisions.

### 5.4 Lifecycle

Graph changes are revisioned events and mappings, not destructive rewrites.
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

Old identifiers remain resolvable for citations, audits, effective views, and
historical projections.

---

## 6. Heterogeneous Graph and Ontology

### 6.1 Graph responsibility

The graph exists to integrate heterogeneous evidence through reviewed semantic
structure. It supplies:

- conservative identity resolution across sources;
- cross-source joins and relation paths;
- current, historical, conflicting, corrected, and superseded state;
- source-backed topology with bounded traversal;
- reusable provenance and lifecycle semantics; and
- permission-aware effective views.

The graph never replaces source evidence. Every answer-relevant node, edge, or
hop must resolve to authorized Observations.

### 6.2 Stable core and scoped packs

The ontology is:

```text
small stable cross-domain core
+ source-specific mappings
+ scoped domain packs
+ reviewed aliases, types, frames, and relations
+ versioned OntologyRevision
```

Candidate core concepts include:

```text
Actor
Person
Organization
Artifact
Document
Communication
Event
Claim
Identifier
Project
Case
WorkItem
TimeInterval
StateTransition
Location
```

A source-specific record retains its local source type and occurrence identity
while mapping to shared concepts. Email, calendar, ticket, document, and
database records do not become a single flattened source type.

Ontology constrains and compresses the vocabulary, arity, and allowed shapes of
candidate and canonical relation types so edge semantics and graph complexity
remain governed. It does not cap how many source-addressed annotations or
candidates a document or Observation may produce, and it does not collapse
distinct source occurrences merely to reduce edge count.

### 6.3 Hard invariants and soft semantics

Hard fail-closed checks are limited to:

- authentication, permission, tenant, workspace, and grant scope;
- schema and relation arity;
- evidence lineage;
- graph, ontology, policy, tokenizer, model, and evaluator revision pins;
- canonical-write review preconditions;
- exact-set coverage contracts; and
- public-output redaction.

The following are normally soft candidate signals:

- inferred entity type;
- frame compatibility;
- alias or synonym mapping;
- inferred relation;
- preferred ontology path;
- embedding and graph-neighborhood similarity.

Soft signals may add a capped score. An inferred mismatch receives no bonus but
must not delete or zero otherwise admitted evidence. Reviewed core-type
incompatibility may block a canonical merge proposal; it does not remove the
underlying authorized evidence from retrieval.

### 6.4 Domain portability

Adding a new domain should normally require:

```text
source adapter
source-completeness evidence
scoped source/domain mappings
evaluation data
projection definitions
```

It must not require a parallel ingestion pipeline, permission model, canonical
graph, ontology authority, index authority, or answer service.

---

## 7. Query Planning and Execution

### 7.1 Core Query Agent and query classes

The core Query Agent accepts:

```text
current user prompt
bounded validated conversation state
authenticated actor and workspace context
current permission-filtered source and EffectiveGraphView bindings
frozen execution budgets and policy revisions
```

The conversation-state envelope may contain only explicitly retained prior
turn references, previously validated entity or identifier bindings, user
clarifications, and their source turn hashes. It is not ambient model memory.
The Query Agent resolves intent and coreference before constructing MCP tool
arguments. If a reference remains missing or ambiguous, it asks for
clarification or fails closed; an MCP tool may not guess what an earlier turn
meant.

Every query routes to one of four classes:

| Query class | Required execution |
| --- | --- |
| `evidence_lookup` | strong lexical+dense retrieval with optional entity grouping and bounded evidence expansion |
| `relation_reasoning` | provenance-constrained typed traversal with source evidence for every hop |
| `exact_set_or_inventory` | deterministic structured enumeration with an explicit coverage contract |
| `global_summarization` | explicitly bounded, permission-filtered source/evidence set with incompleteness disclosure |

Queries asking for all, every, count, inventory, duplicates, missing items,
exact membership, completeness, or definitive absence route deterministically
to structured execution.

### 7.2 Capability discovery and validated plan set

Before planning execution, the Query Agent discovers and pins the actual
current capabilities available to the request:

```text
authorized source schemas and source-provided field capabilities
current permission-filtered source occurrence providers
current EffectiveGraphView and scoped ontology revisions
current MCP tools and their actual input/output schemas
```

Descriptions, cached assumptions, public documentation, and model knowledge do
not override these runtime contracts. Tool arguments and source-field
projections are validated against the discovered schemas before execution.

The Query Agent may propose multiple query expansions, subqueries, and tool
plans when the request has multiple intents, fields, sources, or dependencies.
Each expansion remains a candidate. Each executable subquery is represented by
a validated `SemanticQueryPlan` or an equivalently governed tool plan, with
explicit dependencies and a mapping to the requested fields it is intended to
cover.

An LLM may propose plans, but validation and execution limits are
deterministic. Every executable plan pins:

```text
plan schema version
query class and maximum claim strength
actor, workspace, task, source, and permission scope
effective-view, graph, ontology, and policy revisions
entity, relation, temporal, and evidence slots
allowed edge kinds and directions
hop, fan-out, candidate, evidence, token, time, and repair budgets
coverage requirement
output schema
planner model, prompt, and settings fingerprint when applicable
```

An invalid, scope-widening, revision-unbound, ambiguous, or under-specified plan
fails closed. No expansion or repair may create a permission, source, field,
relation, alias, or canonical assertion that was not validated through the
current authorized contracts.

When a planner or LLM has low confidence about a user instruction, domain term,
schema concept, or MCP tool usage, it may use a redacted public-web search only
for semantic disambiguation, terminology or schema understanding, and
candidate tool-plan expansion. Before any tool call, the proposed plan must be
revalidated against the actual current MCP tool schema and the caller's current
permission scope. Public-web context remains untrusted and provenance-separated
from workspace evidence: no private prompt detail, source content, identifier,
value, secret, or tool result may be sent outward. Web material cannot grant
access, authorize an external or canonical write, mutate canonical KG state, or
replace source-grounded deterministic exact execution and its coverage
contract.

Every Query Agent run records versioned fingerprints for:

```text
user prompt and bounded conversation state
resolved intent and coreference bindings
discovered source-schema, ontology, and MCP capability revisions
candidate expansions and their disposition
validated subqueries and tool plans
tool calls and governed result bindings
requested-field and evidence-coverage checkpoints
repair or requery decisions
stop reason
final compact evidence-context bundle
deterministic result or cited-answer input
```

### 7.3 Strong RAG and bounded adaptive execution

The minimum competitive retrieval control is:

```text
BM25 or equivalent lexical retrieval
+ dense retrieval
+ deterministic fusion
+ evidence reranking
+ citation and answer-claim contract
```

A substring or regex-only retriever is not an adequate strong RAG baseline.

After each authorized execution step, the Query Agent inspects coverage for
every requested field and evidence need. Coverage distinguishes at least
direct source support, explicit source blank, unsupported or unresolved field,
conflict, policy denial or redaction, and no authorized evidence found.
Evidence selection also considers diversity across source occurrences, source
families, time, provenance, and contradictory assertions so repeated copies do
not crowd out materially different evidence.

Repair or requery is allowed only under a frozen attempt, tool-call, evidence,
token, and time budget. It may select another validated field, source, or tool
candidate; narrow or split a plan; or request clarification. It must not widen
authorization, silently invent an alias, promote candidate knowledge, write
canonical state, or treat public-web content as workspace evidence.

Execution stops when the requested fields have support sufficient for the
allowed claim, deterministic coverage is complete, no new authorized and
materially useful evidence is available, clarification is required, or a
budget or permission boundary is reached. The stop reason is explicit and
audited.

### 7.4 Graph-guided expansion

After evidence admission and entity linking, the runtime may traverse only
allowlisted edge types and directions under frozen hop, fan-out, candidate,
evidence, and time budgets.

Scoring components remain inspectable:

```text
lexical score
dense score
entity-link score
graph-path score
temporal/current-state score
provenance and coverage score
capped ontology bonus
```

Evidence bundles, not isolated chunks, are the reranking unit. Hidden or denied
nodes are not materialized and do not influence results. Query-time fallback or
repair creates no hidden candidate or canonical writes.

### 7.5 Deterministic exact execution

Ranked top-k retrieval cannot prove a complete set, total count, inventory, or
definitive negative.

An exact result reports:

```text
bounded source/effective-view scope
revisions and coverage policy
enumerated item count
policy-redacted count
unsupported or unresolved count
duplicate policy
stable ordering
evidence lineage per item
coverage status
```

Incomplete coverage produces a partial result and a weaker claim.

### 7.6 Compact evidence context and answer generation

The Query Agent assembles a compact rich evidence-context bundle rather than
dumping the authorized corpus into the model context. The bundle contains only
the validated plans, requested-field coverage, selected source evidence,
provenance and citation bindings, conflicts, explicit blanks, and relevant
graph or ontology explanations needed for the answer. Its schema, contents,
ordering, budget, and fingerprint are recorded.

The final answer model receives only this authorized bundle and the maximum
claim contract. It must:

- cite source evidence;
- distinguish source assertion from canonical interpretation;
- disclose conflict, incompleteness, uncertainty, and policy redaction;
- obey the maximum claim strength; and
- avoid filling missing evidence from pretrained knowledge.

---

## 8. Model and Anti-Fitting Policy

### 8.1 Model roles

There is no single model called the FormOwl KG model. Every run records roles
separately:

```text
intent and coreference model, if used
query expansion and planner model, if used
candidate extraction or entity-linking model, if used
embedding model
reranker model, if used
final answer model
reasoning effort and decoding settings
prompt, output-schema, and context-budget hashes
```

The core Query Agent is an orchestration role governed by deterministic
validators, permission checks, capability discovery, coverage inspection,
budgets, and audit records. It is not synonymous with any one model. Models may
propose intent, coreference bindings, query expansions, plans, or answer text;
they may not authorize their own tools, invent conversation history, define
the current MCP schema, widen source scope, declare deterministic completeness,
or commit canonical knowledge.

All comparison arms use the same final answer model and settings. Model changes
create a new experiment.

External parsers, embedding models, rerankers, and LLMs are replaceable
candidate-generation or answer components. Their output is never ontology,
authorization, or canonical truth by itself.

### 8.2 Data split

Method construction and evaluation use separate data:

```text
calibration corpus -> tokenizer/profile and protected vocabulary
development corpus -> thresholds and error analysis
evaluation corpus  -> frozen diagnostic comparison
independent holdout -> one sealed final run
transfer holdout    -> materially different source family
```

The independent holdout must not influence:

- tokenizer or SentencePiece artifacts;
- protected identifiers;
- aliases, synonyms, entity merges, or ontology mappings;
- graph construction rules;
- thresholds, routing, traversal budgets, prompts, models, or grading policy.

A change motivated by holdout failure requires a new version and new holdout.

### 8.3 Fair comparison

Every RAG/KG/ontology arm shares:

```text
source and Observation manifest
permission and EffectiveGraphView
tokenizer and index profile
answer model, prompt, reasoning effort, and decoding
context, evidence, token, and time budget
evaluator, grader, container image, and hardware class
```

Candidate admission, graph topology, ontology contribution, and deterministic
execution are separate factors. Gains from better tokenization or source
coverage are not ontology gains.

---

## 9. Provenance, Time, Confidence, and Contradiction

### 9.1 End-to-end lineage

Every result is traceable through:

```text
Source / Asset / EvidenceSnapshot
  -> ExtractorRun
  -> Observation
  -> Candidate Knowledge
  -> Review Decision
  -> CanonicalGraphRevision and OntologyRevision
  -> EffectiveGraphView
  -> SemanticQueryPlan and execution
  -> EvidenceBundle or deterministic result
  -> cited answer or projection
```

Required stable identifiers include:

```text
asset_id
source_ref and source occurrence
evidence_snapshot_id
extractor_run_id
observation_id
candidate_id
review_event_id
canonical object ID
graph_revision_id
ontology_revision_id
effective_view_id
query_plan_id
execution_fingerprint
projection_spec_id
workspace_id
user_id
grant_id
```

### 9.2 Temporal semantics

FormOwl distinguishes:

```text
captured_at
observed_at
asserted_at
effective_at
valid_from and valid_to
due_at
superseded_at
```

Ambiguous values such as `TBD`, `9/E`, `next month`, or dates without a year
retain their raw expression, normalized candidate, precision, inference rule,
and confidence.

### 9.3 Contradiction

Conflicting assertions may coexist when sources, times, scopes, or confidence
differ. New evidence may confirm, correct, contradict, narrow, extend, or
supersede older evidence. Current-state views are projections over history, not
destructive replacement of source records.

Detailed lineage rules are in `docs/provenance.md`.

---

## 10. Identity, Permission, and Access

### 10.1 Connected identity

The connected internal closed-beta path is:

```text
public HTTPS /mcp
  -> OAuth protected-resource challenge
  -> FormOwl OAuth 2.1 authorization
  -> exact callback/resource and PKCE S256 validation
  -> Google OIDC login
  -> verified Google issuer/subject/email mapped through a FormOwl invitation
  -> resource-bound FormOwl access token
  -> current server-side authorization and revocation lookup
  -> fresh gateway-controlled ActorContext
  -> governed MCP tool
```

The predefined client ID is a stable non-secret value selected and recorded by
the deployment operator before discovery. ChatGPT app management uses that
same client ID when supported. ChatGPT supplies and displays only the
production callback `https://chatgpt.com/connector/oauth/{callback_id}`. The
client ID must not be invented or described as generated by ChatGPT. Lack of
predefined-client support is an external live blocker.

Google tokens are upstream identity evidence, not FormOwl MCP bearer tokens.
FormOwl remains the authority for users, invitations, memberships, clients,
token sessions, workspaces, grants, revocation, and audit.

Every protected call builds a fresh `ActorContext` from current PostgreSQL
state. Caller-supplied actor, workspace, session, grant, storage, parser, and
worker fields cannot replace gateway authority.

### 10.2 Permission propagation

Every Asset, Observation, candidate, canonical object, ontology mapping,
effective view, query result, and projection carries or derives a permission
scope. Unknown scope fails closed.

Possible access levels include:

```text
answer only
graph summary
graph snippet
evidence snippet
controlled raw asset reference
```

Graph visibility does not grant evidence visibility. Evidence visibility does
not grant raw asset access. Raw access uses explicit grants and governed
locators such as `formowl://asset/{asset_id}`.

### 10.3 Audit

Security-sensitive reads, denials, plan validation, graph traversal, exact
execution, reviews, commits, grants, revocations, and external write proposals
are auditable. Audit failure must not produce an unaudited success or partial
mutation.

Manual trusted authentication, JSON-line commands, hand-built JSON-RPC, and
stdio identity variables are test/local compatibility only.

---

## 11. Storage, Runtime, and Infrastructure

FormOwl is container-first. Python is the Phase 0 orchestration, contract,
policy, validation, evaluation, and debugging language.

PostgreSQL is canonical for:

```text
asset and source occurrence metadata
normalized observations and lexical index state
candidate and canonical graph state
ontology and policy revisions
permissions, grants, reviews, and audit
query-plan and execution metadata
jobs and projection metadata
```

pgvector is the default dense-retrieval baseline. Raw or large binary assets
live behind an object-store abstraction.

A graph data model does not require a graph database. Dedicated graph or search
engines may be considered only as rebuildable projections after a demonstrated
requirement; they do not replace PostgreSQL governance authority.

Heavy extraction, embedding, reranking preparation, and projection rebuilds
run outside MCP request handling. Runtime indexes and projections are
versioned, rebuildable from authorized Observations, and never become source
truth.

Detailed infrastructure requirements are in `docs/infra-spec.md`.

---

## 12. Services and Portable Contracts

### 12.1 Connected MCP Gateway

The FormOwl MCP Gateway is the sole formal ChatGPT-facing service. It owns:

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

It does not expose raw storage, SQL, parser, worker, oracle, or backend
controls.

### 12.2 Compatibility services

Project MCP retrieves project evidence and prepares proposal-only project
writes. Wiki MCP creates and manages governed wiki artifacts and proposal-only
publishing. Their JSON-line and hand-built JSON-RPC/stdio surfaces are local
compatibility paths, not alternate connected identity paths.

### 12.3 Contract boundary

`formowl_contract` is the shared schema boundary. Major families include:

```text
SourceRef / EvidenceSnapshot / Citation / PermissionScope
Asset / AssetOccurrence / UploadSession / IngestionJob / ExtractorRun / Observation
CandidateMention / CandidateBusinessObject / CandidateAtom / CandidateRelation / CandidateFrame
CanonicalAtom / CanonicalEntity / CanonicalRelation / CanonicalFrame / CanonicalGraphRevision
OntologyRevision / TypeDefinition / TypeAlias / TypeMapping / TypeAlignmentCandidate
UserKnowledgeGraphRevision / EffectiveGraphView
WikiProjectionSpec / WikiRevision
User / ExternalIdentity / WorkspaceMember / ActorContext / AccessRequest / Grant / AuditLog
ContextPackage / MCPResultEnvelope
```

No MCP service depends on another service's private implementation types.

### 12.4 Current semantic tools

The configured connected runtime may expose:

```text
whoami
open_upload_session
create_ingestion_job
list_observations
preview_graph_candidates
query_effective_graph_view
query_mail_evidence
answer_mail_case_progress
request_graph_access
submit_graph_review_decision
generate_wiki_draft_from_graph_view
```

`query_effective_graph` is a deprecated compatibility alias when present.
`select_actor` is not a connected tool.

Tool names may evolve, but the evidence, permission, plan-validation,
canonical-write, and output boundaries do not.

---

## 13. Projection and External Writes

A projection converts governed evidence or an effective graph view into a
task-specific artifact:

```text
cited answer
status or risk view
report or dashboard
review queue
wiki or document draft
external write proposal
```

A `WikiProjectionSpec` or equivalent projection contract pins source, graph,
ontology, permission, citation, redaction, generator, and review policy.
Reviewed and published revisions are immutable. Refresh and restore create new
revisions and diffs.

External writes are proposal-first. Execution requires explicit authorization,
current permission, a validated target, audit, and no-partial-write behavior.
An answer, wiki page, or external-system update never becomes canonical graph
state by implication.

---

## 14. Current Implementation and Methodology Status

Implemented repository slices include:

```text
shared contracts and policy models
Asset, ingestion, extractor-run, and Observation workflows
deterministic heterogeneous-source fixture extractors
mail evidence and bounded PST diagnostics
candidate graph and scoped ontology contracts
canonical graph lifecycle contracts
user/effective graph views
graph-derived wiki drafts
PostgreSQL/pgvector adapter contracts
Project MCP and Wiki MCP compatibility services
connected FormOwl MCP Gateway and Google-backed FormOwl OAuth
```

Current tested compatibility paths do not prove source-complete heterogeneous
integration, automatic canonical commits, universal parser coverage,
enterprise-scale readiness, or KG + ontology superiority.

The active research target is:

```text
method: evidence_to_knowledge_kg_ontology_v2_hybrid_v1
tokenizer: jieba_sentencepiece_frozen_profile_candidate_admission_v1
```

The current runtime still reports:

```text
method: mail_candidate_kg_broad_ontology_diagnostic_v1
tokenizer: ascii_identifier_regex_v1
CJK support: false
```

Before methodology-quality UAT, comparative claims, default-path replacement,
or methodology completion, run:

```sh
python3 scripts/methodology_authority_check.py --require-ready
```

A nonzero result blocks the claim. Diagnostic implementation may continue only
with an explicit blocked boundary.

Issue #20 remains open until its external PostgreSQL, container lifecycle, MCP
Inspector, live ChatGPT/Google, reviewer, and completion-audit evidence passes.
Issue #41 remains the authority for generic Asset tenant, owner, storage,
occurrence, retention, purge, transfer, and authorization semantics.

---

## 15. Acceptance Criteria

### 15.1 Method and source

- multiple source families produce citeable Observations through adapters;
- source completeness is reconciled against an independent oracle;
- source occurrences survive deduplication and entity resolution;
- deterministic and semantic extraction remain separate;
- candidate output cannot silently mutate canonical state.

### 15.2 Graph and ontology

- canonical commits are scoped, reviewed, revisioned, and source-backed;
- every answer-relevant graph hop resolves to authorized Observations;
- the stable ontology core transfers across at least two materially different
  source/domain families;
- inferred ontology mismatch does not remove admitted evidence;
- contradiction, correction, supersession, split, and merge preserve history.

### 15.3 Query and answer

- strong RAG is implemented over the same source-complete Observations;
- the core Query Agent accepts the user prompt plus bounded, versioned
  conversation state and resolves intent and coreference before MCP execution;
- ambiguous references fail closed or request clarification, and MCP tools do
  not infer hidden history from `query_text`;
- actual authorized source schemas, scoped ontology revisions, and current MCP
  capabilities are discovered, pinned, and revalidated before tool calls;
- query expansions remain candidates, and every executed subquery or tool plan
  is independently validated, permission-bounded, versioned, and audited;
- requested-field coverage and evidence diversity govern bounded repair,
  requery, context selection, and the recorded stop reason;
- the final model context is a compact, fingerprinted, citation-bound evidence
  bundle rather than an authorized-corpus dump;
- exact-set claims use deterministic enumeration and coverage evidence;
- answers cite evidence and disclose conflict or incompleteness;
- no-answer and permission-denied behavior fail safely; and
- unseen pre-registered prompts pass without question-specific identifiers,
  aliases, expected answers, or success-pattern fitting.

### 15.4 Evaluation

- comparison arms share source, permission, tokenizer, answer model, prompt,
  budgets, evaluator, and environment;
- holdout content cannot influence construction or tuning;
- final-answer, citation, identity, relation, temporal, exact-set, no-answer,
  privacy, latency, and cost metrics are reported by stratum;
- every accepted report binds one execution fingerprint;
- independent holdout and transfer-domain evidence pass the pre-registered
  decision gate before a superiority claim.

### 15.5 Product and security

- permission scope propagates through every layer and unknown scope fails
  closed;
- matching does not grant access and graph access does not grant raw access;
- public tools hide raw paths, SQL, credentials, parser, worker, storage, and
  oracle internals;
- external writes are proposal-first and audited;
- canonical container verification passes for the claimed slice.

---

## 16. Non-Goals and Final Statement

FormOwl must not:

```text
fit runtime behavior to UAT or holdout questions
add question-specific aliases, literals, expected answers, or success patterns
make mail or another source family the product ontology
replace strong RAG with graph-only retrieval
infer complete sets from top-k ranking
place all authorized data into an answer-model context
let MCP tools guess unprovided conversation history or coreference
let query expansion, repair, or tool selection widen authorization
use public-web material as internal source evidence or canonical fact
use inferred ontology mismatch as a default hard evidence filter
let an extractor or LLM create canonical truth automatically
merge matching, authorization, canonicalization, and raw access
create a parallel truth store, ontology, index, or answer service per adapter
expose raw infrastructure through MCP
require a graph database before a demonstrated infrastructure need
claim methodology readiness while executable authority is blocked
```

The center of FormOwl is:

```text
Any Source
  -> Source-Preserving Observation
  -> Evidence-Backed Candidate Knowledge
  -> Governed Canonical KG + Scoped Ontology
  -> Permission-Aware Effective View
  -> Core Query Agent + Validated Adaptive Hybrid Execution
  -> Cited Answer, Projection, or Reviewed Action Proposal
```

The graph earns its place by integrating evidence across sources and improving
measured graph-required tasks over a strong RAG control. It does not earn that
place merely by existing.
