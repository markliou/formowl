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
heterogeneous evidence in its source-native forms. Product sources include
mail, standalone documents and spreadsheets/XLSX, tables and databases,
images, speech and non-speech audio including music, video, and connected
business systems. Each enters the same evidence, permission, governance, and
query architecture while retaining its native structure and modality.

It turns source material into knowledge that is:

- traceable to source occurrences;
- explicit about time, context, confidence, revision, and permission;
- reviewed before it becomes governed shared state;
- reusable across source systems and business domains;
- adaptable to different users and tasks; and
- projectable into cited answers, reports, dashboards, wiki drafts, review
  queues, or authorized action proposals.

Mail is the first diagnostic source fixture for the active research program.
It does not define product scope or require other sources to become mail or
plain text. Native evidence remains usable when it has no semantic annotation
or graph match. Product requirements and currently verified adapter capability
are distinct; §14 records the limited implemented slices.

---

## 3. Canonical Architecture

FormOwl has a knowledge-construction path and a query-execution path.

### 3.1 Knowledge construction

```text
heterogeneous sources
  -> Asset / EvidenceSnapshot
  -> ExtractorRun
  -> source-preserving Observation
       -> authorized source evidence for retrieval and structured execution
       -> optional candidate mentions, entities, claims, relations, and frames
            -> review and governance
            -> canonical KG + scoped ontology revisions
            -> permission-filtered EffectiveGraphView
```

Evidence preservation precedes semantic interpretation. The graph and ontology
are governed reusable overlays linked to Observations; creating those overlays
is not an admission prerequisite for direct evidence retrieval or source-native
table execution. Candidate review remains mandatory before canonical commit.

### 3.2 Query execution

```text
user prompt + bounded conversation state
  -> core Query Agent
  -> intent and coreference resolution
  -> actual source-schema, modality, and current MCP-capability discovery
     plus scoped ontology and EffectiveGraphView bindings when used
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

Human office-agent surfaces present a server-authoritative conversation
transcript rather than replacing one result panel on every turn. The visible
transcript and the model conversation-state envelope are separate bounded
records: display retention may be longer than model context, but neither is
infinite memory. Reload restores the current transcript through an opaque
server session; the browser does not supply trusted history. Pending,
successful, partial, clarification, and safe failure states remain attributable
to their own turns. Starting a new conversation clears retained model history,
prior evidence, and visible transcript state, and invalidates the old session
binding. A temporary UAT may retain this state only in memory and may lose it
after expiry, capacity eviction, or restart when that limitation is displayed.
The current issue #56 temporary LAN UAT profile retains at most `64` visible
turns, supplies at most `8` messages to the answer model, and expires an idle
browser session after `1` hour. These are diagnostic implementation bounds,
not permanent product defaults or a cross-restart persistence guarantee.
Its runtime defaults are `0.0.0.0:8088` for `--temporary-lan-diagnostic` and
`127.0.0.1:8766` for normal UAT. Explicit `--host` and `--port` values
override those defaults. A temporary access code is optional; the temporary
LAN UAT remains usable when no access code is supplied.

The method remains intentionally hybrid:

- strong RAG recovers source evidence through modality-appropriate retrieval;
- the KG contributes identity, cross-source joins, bounded topology, temporal
  structure, contradiction, provenance, and reusable integration semantics;
- the ontology contributes scoped vocabulary, reviewed mappings, plan
  validation, and a capped ranking prior;
- deterministic structured execution over validated source-native records owns
  exact-set, table calculation, and completeness claims;
- the answer model explains the authorized result and does not invent missing
  evidence.

Direct lookup can execute over authorized source evidence without a matching
graph node, edge, or ontology annotation. Relation reasoning uses the governed
overlay and verifies its hops against source evidence. Absence of an overlay
entry cannot establish absence in the source; projection availability and
source validity are separate conditions, governed by §7.2 and §7.3.1.

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
documents, PDFs, slides, standalone spreadsheets/XLSX, and native tables
databases, ERP, CRM, HR, legal, and finance systems
wiki and documentation systems
images and diagrams, speech, non-speech audio/music, and video
derived OCR, transcripts, captions, and other source-linked representations
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
spreadsheet cell, row, or bounded range with workbook/sheet coordinates
image region, audio/music interval, video frame or scene
source-linked OCR or transcript segment
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
modality and governed reference to native content where applicable
source-native locator
extractor run, version, configuration, and model metadata
captured_at, observed_at, and source time where available
permission scope
confidence, warnings, and review requirement
```

An Observation may retain text, structured values, or a governed reference to
binary evidence. OCR, transcripts, captions, summaries, embeddings, and graph
annotations are derived representations with their own provenance and limits;
they do not exhaust an image, recording, music passage, or video. Verification
must address the native region or interval needed for the claim. A text proxy
can support its extracted text within its accuracy limits, but cannot alone
prove a visual, acoustic, musical, or motion-dependent fact.

Spreadsheet evidence preserves raw values separately from displayed values,
source types, precision, units, explicit blanks/nulls, formulas and any cached
results, merged cells/header paths, row association, and workbook/sheet/table/
cell coordinates as applicable. A formula, its cached value, and a formatted
display are distinct evidence. Unsupported or unverified features must be
reported; a parser that reads only XML values cannot claim this full contract.

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
whether or not shared semantics are mapped into the graph. Completeness is
measured against the authorized source inventory and required native features,
not the number of text chunks, annotations, graph nodes, or indexed results.
Unsupported media regions or spreadsheet formula/type semantics remain source
coverage gaps. A missing graph/ontology or retrieval projection is a separate
derived-state condition and does not establish missing source content.

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

The graph is an identity and relation overlay, with links back to evidence.
Every answer-relevant node, edge, or hop must resolve to authorized
Observations. Node properties do not replace native cell values or media
content. Evidence may be retrieved and cited with no graph entry; unrepresented
or unmatched evidence remains evidence. Missing nodes or edges cannot support
a closed-world negative about the source.

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

A source-specific record retains its local source type, modality, structure,
and occurrence identity while optionally mapping to shared concepts. Email,
calendar, ticket, document, spreadsheet, database, and media records retain
their native evidence representations.

Ontology governs the vocabulary, arity, and allowed shapes of candidate and
canonical relation types. Applying that vocabulary produces optional
zero-to-many source-addressed annotations: one Observation may have none or
many, and an annotation may bind several Observations while retaining every
source locator. Ontology is not an exhaustive evidence index or a mandatory
one-annotation-per-evidence layer. It does not cap annotation cardinality or
collapse source occurrences to reduce edge count. No annotation, type mapping,
or compatible ontology path is required to admit otherwise authorized evidence,
and their absence cannot establish that a requested fact is absent.

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
current permission-filtered source bindings and available native capabilities
EffectiveGraphView bindings when graph signals are used
frozen execution budgets and policy revisions
```

The conversation-state envelope may contain only explicitly retained prior
turn references, previously validated entity or identifier bindings, user
clarifications, and their source turn hashes. It is not ambient model memory.
The Query Agent resolves intent and coreference before constructing MCP tool
arguments. If a reference remains missing or ambiguous, it asks for
clarification or fails closed; an MCP tool may not guess what an earlier turn
meant.

The server owns both conversation-state and transcript selection. Client
payloads may carry the current prompt, but cannot inject, replace, or extend
trusted prior turns. A failed turn may remain visible as a sanitized transcript
event while leaving the last valid model history and evidence state unchanged.
Transcript retention and model-context retention are independently bounded and
reported by the active surface.

Every query routes to one of four classes:

| Query class | Required execution |
| --- | --- |
| `evidence_lookup` | modality-appropriate strong RAG over source-preserving Observations, with optional entity grouping and bounded source-context expansion |
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
authorized source schemas, modalities, native locators, and field capabilities
current permission-filtered source occurrence providers
current EffectiveGraphView and scoped ontology revisions when used
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

The Query Agent must expand and validate a user request before forming a tool
query when intent, identifier, field, source, or schema semantics require
resolution. It must not forward the raw prompt or an under-specified
`query_text` in that case. Tool use is a bounded iteration: after each
governed call, the agent inspects result and requested-field coverage, then
stops, asks for clarification, or issues another newly validated expanded or
refined query/tool plan. Every iteration consumes the pinned attempt,
tool-call, evidence, token, time, and repair budgets; it never rebuilds the
KG or index.

An LLM may propose plans, but validation and execution limits are
deterministic. Every executable plan pins:

```text
plan schema version
query class and maximum claim strength
actor, workspace, task, source, and permission scope
source/provider and policy revisions
effective-view, graph, and ontology revisions when used
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

The KG, EffectiveGraphView, lexical/dense indexes, and any modality-specific
indexes are persistent, version-pinned derived projections. A normal request
reuses activated revisions; it must not rebuild, re-extract, re-embed, or re-materialize them
per prompt. A missing, stale, unsealed, unactivated, or unavailable projection
is an explicit runtime/configuration condition, distinct from an independently
validated immutable source snapshot and its authorized provider manifest.

For validated `evidence_lookup`, automatic source recheck follows the
2026-10-06 rule in §7.3.1: a nonempty validated requested-field set with all
fields lacking verified support triggers one materially different bounded
recheck when existing safety/eligibility and remaining budgets permit.
Partial misses must be disclosed and must not trigger this automatic recheck;
an empty field set uses the validated evidence-need plan or clarification.
Source-backed explicit blanks count as verified coverage; citation count or
status alone cannot trigger recheck. Projection failure grants no independent
eligibility. Eligible fallback uses the same request's
permission-filtered Observation/source providers without requiring the failed
projection. It retains authorized source/hash/lineage/revision validation,
ActorContext, workspace/source/permission scope, citation contract, and remaining
deadline, attempt, tool-call, evidence, token, and repair budgets. It may not
widen scope, select an unbound provider, or rebuild inline.

An identifier-plus-field request is a typed exact lookup: the protected
identifier is matched as an identifier, and the requested field is selected
from the current authorized source schema. Exact lookup runs before broader
semantic expansion and preserves row association and source citations. If it
misses, the bounded recovery path may expand validated aliases or field terms
and run the applicable source-native strong-RAG branch over the same authorized
Observation snapshot. For text this includes lexical+dense retrieval. Recovery
cannot substitute semantic similarity for an exact result or its coverage
contract. This is bounded query expansion, not a per-query index or KG rebuild.

The runtime distinguishes evidence outcomes from operational failures.
`no_authorized_evidence`, an explicit source blank, and permission denial are
not the same as a provider error or timeout. A provider error or timeout must
return a safe operational failure/stop reason and must never be projected as a
legitimate no-answer or as evidence that the requested fact is absent.

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

Each executed semantic phase and tool-call iteration also emits a safe phase
trace containing its phase/iteration identity, elapsed time, bounded outcome,
and stop/error reason. The trace is bound to the run fingerprint and must not
expose raw prompts, source content, credentials, SQL, filesystem paths, or
worker internals.

### 7.3 Strong RAG and bounded adaptive execution

Strong RAG is retrieval over source-preserving Observations using the
representations and capabilities appropriate to the requested evidence. Text
retrieval is one branch; converting every source into text does not satisfy
the product's multimodal contract. Applicable branches include:

| Evidence | Retrieval and verification requirement |
| --- | --- |
| Text, OCR text, or transcripts | Lexical+dense retrieval, fusion, reranking, and source-linked citations; disclose extraction accuracy and coverage limits |
| Spreadsheet/table | Native schema, identifier, row, cell, and range access; preserve source value/structure semantics and use §7.5 for exact operations |
| Image, chart, or diagram | Region-aware visual retrieval or inspection with image/page coordinates and verification of the relevant source crop |
| Speech, non-speech audio, or music | Task-appropriate audio retrieval/inspection with track or segment identity, time spans, and verified source clips; a transcript cannot establish nonverbal or musical properties |
| Video | Temporal/visual retrieval over the relevant frame, scene, or clip, joined to audio/transcript evidence where needed and verified against native content |

The validated plan discovers actual adapter/model support and pins the
applicable modality, representation, model/index revisions, and coverage
limits. Unsupported native access is disclosed as unsupported or incomplete;
it cannot silently become a successful text-only interpretation. Derived
captions or descriptions remain candidate interpretations. Real-source
verification and modality-specific acceptance are required before claiming a
branch works; the current fixture limits are in §14.

For the frozen issue #56 text-evidence control, the minimum competitive
retrieval path remains:

```text
BM25 or equivalent lexical retrieval
+ dense retrieval
+ deterministic fusion
+ evidence reranking
+ citation and answer-claim contract
```

A substring or regex-only retriever is not an adequate strong RAG baseline.
This product clarification does not change the frozen method/tokenizer,
comparison arms, or authority gates. Adding or evaluating a modality-specific
implementation requires its own authorized scope and evidence; mail/text
diagnostics cannot establish universal multimodal capability. The specific
mail and independent Markdown/plain-text recheck/promotion scope in §7.3.1
remains bounded to those functions.

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
canonical state, or treat public-web content as workspace evidence. This general
plan repair is distinct from §7.3.1 automatic source recheck and must not be
used to bypass its all-requested-fields-missing eligibility rule.

Execution stops when the requested fields have support sufficient for the
allowed claim, deterministic coverage is complete, no new authorized and
materially useful evidence is available, clarification is required, or a
budget or permission boundary is reached. The stop reason is explicit and
audited.

#### 7.3.1 Source-neutral evidence double-check — 待測

Contract reconciled to the **2026-10-06** user rule; feature **待測**, role
active-blocked, existing plan step 4
in-progress. Same-scope recovery diagnostics do not establish standard
functionality, whole-source search, business-answer success, or independent
release approval. Detailed results and earlier cited-but-partial mail/failure
evidence remain in the [dated handoff](docs/agent-goals/handoff-log.md).

Dated UAT, implementation, and verification records remain centralized in the
[dated handoff](docs/agent-goals/handoff-log.md); they are diagnostic evidence,
not current work orders or acceptance. The latest handoff supersedes the earlier
unresolved single-case report only for the narrow source-cap fixture: that
fixture was repaired and its focused checks passed. This does not establish the
whole loader module or the full regression suite; neither was rerun. Projection-
independent source start, live mail/document acceptance, three reviewers, and
all four methodology gates remain open. Feature remains **待測** and step 4 is
in progress; no runtime, full-suite, UAT, readiness, completion, or reviewer
acceptance claim is made.

**Historical diagnostic-only authority record (not fresh readiness or model
authority):** `valid=true`, `ready=false`, `errors=[]`, `CJK=true`, with four
methodology gates blocked; execution fingerprint
`sha256:a1ef525bcd80cb381ea3f1e0c54b5ef8231036d60b50cb6dc444c10c31b645dc`.

Evidence presentation has a shared `16 KiB` UTF-8 evidence-data budget:
provenance-linked groups stay whole and exact inventory is all-or-none. This
does not cap the entire provider request/context size. Provider diagnostics
carry the authoritative count (maximum `6`, derived from existing execution
budgets) and latest `3` attempt/timing records; no timeout, execution budget,
or retry allowance was increased.

The source recheck uses sealed job/hash/permission/scope references outside
the canary; valid out-of-index document observations need not be canary
members. Each observation binds to its own authorized selector, source,
lineage and revision, not a guessed single selector for a multi-source request.
Original intent, claim ceiling, scope, and exact-output grammar stay bound.
Field-focused graph evidence retains supporting text beyond a 400-character
preamble with its source/citation group; citations alone cannot satisfy a
business field or upgrade missing-field/coverage metadata.
Inherited source pins and visual citation samples are not independent oracle
proof; the historical browser's `source_binding_verified=false` remains
recorded in the handoff. Raw terms/query text are not retained in safe traces;
known prompts remain development smoke only and unseen questions stay frozen.

The same implementation must serve at least these two distinct functions:

| Function | Illustrative request | Evidence and citation contract |
| --- | --- | --- |
| Mail evidence organization | 整理某人的相關信件 | Authorized mail Observations with governed message/occurrence references |
| Independent document evidence lookup | 找出專案 A 的驗收條件並附引用 | Independently uploaded Markdown/plain-text Assets and Observations, with document revision and `line_start`/`line_end` citations |

The document case must not depend on a mail session, sender, message, or mail
attachment. Use the real `PlainTextObservationExtractor` in
`python/formowl_ingestion/extractors/text.py`; fixture-only document parsing
does not prove PDF/DOCX support. Examples illustrate intent, not runtime
keyword rules, aliases, expected answers, or holdout-tuning inputs.

**Development POC boundary versus security review**

The shared implementation records an explicit execution boundary through
`SourceEvidenceExecutionPolicy` in
`python/formowl_retrieval/gateway.py`:

| Boundary | Permitted evidence | Claim permitted | Required promotion evidence |
| --- | --- | --- | --- |
| `development_poc_v1` | Provider-free fixtures, local dev-container checks, and explicitly authorized source reads for `mail` or `document_text`; public outputs are safe summaries, statuses, counts, citations, and fingerprints only | Bounded diagnostic behavior and implementation progress; never methodology readiness, comparative superiority, production security, or default-path replacement | No global readiness/reviewer prerequisite for an ordinary authorized diagnostic read; existing safety, audit, and fail-closed rules still apply |
| `security_review_v1` | The same shared core, same authorized source scope, and the same source-neutral mail/document adapters; no synthetic fixture or POC result is sufficient by itself | Security-review evidence only, after all required gates pass; it is not inferred from a functional POC | `--require-ready`, source completeness, accepted execution-fingerprint binding, same-pipeline real-source ablation, independent final-answer acceptance, and exactly three effective reviewer agreements |

The POC boundary does not weaken authentication, authorization, provenance,
candidate-before-canonical, fail-closed, audit, redaction, no-secret, or
no-raw-path rules. When requested and authorized, a bounded query may search
all mail within the connected account's current permission-filtered scope;
this does not authorize a full-corpus dump to a model/provider. Only compact,
query-relevant, verified evidence and safe citations/summaries may be projected.
Ordinary authorized POC reads do not wait on methodology readiness, source-
completeness research gates, or broad review; those remain prerequisites for
methodology/security-review claims and promotion. The existing §10.3 audit
obligations remain in force, and an audit failure cannot produce an unaudited
success. This document does not itself authorize or perform live private-mail
or external-provider UAT; that operation requires separate authorization.
Requesting `security_review_v1` without its required evidence fails closed for
that review classification. Changing the label does not promote a POC artifact.

The known mail prompt for the first live UAT is a development smoke case only.
Future user questions remain unseen and frozen for acceptance; do not tune names,
aliases, expected answers, routes, or success logic to the smoke or holdout.
Before acceptance testing, freeze and fingerprint code, prompts/settings,
models, source snapshot/revisions, and applicable budgets. Any tuning prompted
by observed acceptance questions or outcomes requires a new version and a new
holdout.

**Discovery and shared execution**

1. Ordinary conversation stays with the LLM and makes zero MCP calls. Data
   requests select the appropriate currently exposed FormOwl MCP capability.
   Tool descriptions must state supported intents/source families, required
   authorized selectors, citation/coverage semantics, and when not to use the
   tool. Validate arguments against actual schemas; preserve names, identifiers,
   scope, requested fields, and quantifiers without adding “all”.
2. Resolve intent and authorization, validate the plan, and run the initial
   graph/hybrid retrieval. A graph miss alone does not establish absent data.
3. For a validated `evidence_lookup` with a nonempty validated requested-field
   set, **all** fields lacking verified supporting evidence triggers **one**
   materially different, same-authorized-scope bounded source recheck when
   existing safety/eligibility and remaining budgets permit, even if unrelated
   citations exist. Partial misses must be disclosed and **must not trigger**
   this automatic recheck. An empty requested-field set is not vacuously all
   missing: use the existing validated evidence-need
   plan or ask for clarification. A source-backed explicit blank counts as
   verified coverage; citation count or status alone cannot trigger recheck.
   When eligible, change the route materially by reading the matching immutable,
   authorized Observation/source snapshot rather than repeating the same
   index/KG lookup or merely rewording the prompt.
4. Revalidate access, source occurrence, content hash, lineage, snapshot seal
   and revision bindings before projecting governed citations. Return only
   supported evidence with explicit coverage, warnings, and stop reason.

**2026-10-06 automatic recheck decisions.** These are business-field coverage
decisions, not diagnostic identity-metadata checks.

| Validated requested business fields | Automatic source recheck |
| --- | --- |
| Nonempty; all lack verified support, even with unrelated citations | One materially different same-authorized-scope recheck, when existing safety/eligibility and remaining budgets permit |
| Some supported, some missing | Disclose missing fields; must not trigger automatic recheck |
| A source-backed explicit blank | Counts as verified coverage for that field, not a miss |
| Empty set | Resolve via validated evidence-need plan or clarify; never vacuous all-missing |
| Citation count/status or projection failure alone | No trigger or independent eligibility |

**Required miss/incomplete fallback contract.** An `index_miss`,
`index_incomplete`, `graph_miss`, or `graph_incomplete` outcome is not
`no_authorized_evidence`. A missing, stale, incomplete, unavailable, unsealed,
or unactivated retrieval projection is **not** an independent permission to
bypass the automatic recheck eligibility above. For a lookup that satisfies
that rule and the existing safety/eligibility and remaining-budget checks,
source-grounded fallback may use the strong-RAG lexical+dense path or its
source-native equivalent directly from an independently validated immutable
source snapshot, without requiring the failed projection. An empty field set
must first be resolved via the validated evidence-need plan or clarification;
projection failure cannot supply a vacuous field condition.

The fallback retains the original `ActorContext`, workspace and source scope,
authorized immutable source/hash/lineage/revision checks, permissions and
grants, requested-field coverage, citation contract, and remaining execution
budgets. It does not require the failed projection and never rebuilds one
inline. Every outcome records whether the index/graph path and the
source-grounded fallback were searched, together with coverage and citation
status. A source-backed explicit blank is a verified field outcome, not
retrieval missing; it must be reported as blank and does not itself trigger a
recheck. Citation count, including zero citations, is not field coverage.
Only `fallback_complete_no_match`, meaning the authorized source coverage was
completely examined and no matching evidence was found, may be projected as
`no_authorized_evidence` (or the existing complete-scan `not_found` contract).
`fallback_incomplete` and `fallback_timeout` must expose `retrieval_incomplete` and
`pending_review` (as applicable), must not be phrased as “no data” or
`no_authorized_evidence`, and may not be converted into a definitive
no-answer. A cited partial answer remains required to disclose its incomplete
coverage.

The UI and answer contract must show whether the source was searched and must
show governed citations when available; otherwise it must visibly report
`retrieval_incomplete`/`pending_review` rather than imply that no data exists.
The current POC's shared `500 ms` / `8192` source-fallback budget is only a
bounded diagnostic budget, not a guarantee of full-source retrieval or
complete coverage. It must not be used to claim `fallback_complete_no_match`
unless completeness is independently established.

One source-neutral core owns eligibility, budgets, validation, and outcome
semantics; source adapters supply authorized reads and native citation
locations. Its required inputs must not contain mail-only session/sender
fields. Reuse the existing retrieval/evidence-resolver owners in
`python/formowl_retrieval/gateway.py` and `kg_first.py`, with integration through
`python/formowl_gateway/semantic.py` and the actual
`python/formowl_gateway/issue56_uat_runtime.py` composition. Adapt the existing
mail handler in `python/formowl_mail/query.py`; do not create two independent
fallbacks, parallel services, schemas, indexes, or truth stores. An older
fixture gateway alone is not proof of live composition.

For mail and eligible graph `evidence_lookup` recovery, the bounded
`required_terms` list contains `1–8` terms of
at most `80` characters. The request binder accepts only terms that occur as
contiguous spans in the original request under NFKC/casefold normalization,
then freezes the first valid set for that turn; retries cannot remove or
replace it. The same AND predicate applies to initial cited observations and
the same-scope source recheck. These terms constrain relevance, not
authorization; no name list, alias, or smoke-specific rule is permitted.
This does not require every graph relation/summary plan to use same-item AND
or provide terms for this recovery route. Generic source-family-only term
rejection remains mail-only, not graph/document. Without explicit grounded
terms, legacy mail calls retain all-lexical-term matching; standalone document
lookup retains protected-identifier checks plus lexical token intersection,
not full-natural-language-query subset matching.

**Eligibility, limits, and outcome contract**

- Preserve the same actor, workspace, grants, authorized selector/source
  scope, query meaning, and revision pins. Entity matching cannot grant access;
  recheck cannot rebuild an index/KG, re-extract sources, or write canonical state.
- Preserve the existing mail eligibility statuses:
  `ok/not_found/no_answer/incomplete/partial/pending_review/unsupported`, with
  a validated evidence-only plan and field-level coverage metadata. Zero
  citations alone is not the trigger and does not establish field coverage.
  Error, permission denial, exact intent/typed-binding warnings, and
  `replan_required` do not
  enter this source scan merely by status reinterpretation. For graph recovery,
  an outer adaptive public-replan marker must not hide a validated underlying
  eligible miss; retain actual subquery status and failure provenance. Genuine
  provider, schema, permission and operational failures remain failures, not
  no-data. No duplicate full semantic retrieval or exact fallback is permitted.
- Exact sets, counts, inventories, aggregation, and definitive negatives stay
  with deterministic structured execution, never top-k fallback. Unresolved
  exact intent/binding requires clarification (`pending_review`), not guessing.
- Pin attempt, tool-call, observation, evidence, token, time, and repair limits
  before execution; no recursive fallback, timeout inflation, or budget reset.
  Semantic budget remains `1500 ms`; source recheck is one shared `500 ms` /
  `8192` scanned-Observation phase across applicable mail selectors and
  independent document families, not a fresh budget per family/selector.
  Give applicable readers bounded opportunity; unfinished scans remain
  incomplete. At most `128` evidence items or a smaller request cap survive.
- The shared helper accepts an optional trusted finite numeric absolute
  `deadline_monotonic` and `source_evidence_deadline_scope(...)` using a
  token-reset ContextVar. The earliest explicit/scoped/current 500ms deadline
  governs; None/no scope preserves the existing bound. Check before/after
  preparation, reads and callbacks; an already expired deadline invokes no
  callbacks. Runtime captures the active turn deadline before thread handoff
  and scopes normal TestClient `client.post`; this is server-owned state,
  never provider/public arguments or headers. Shared-helper tests alone do
  not prove propagation; synthetic actual-TestClient coverage is separate.
  These phase checks are not a guaranteed total wall-clock timeout.
- Missing reader, zero result limit, exhausted budget, or incomplete source
  coverage with no citations yields `pending_review`, not “the data does not
  exist”. Only a complete bounded scan AND complete sealed-source coverage may
  yield `not_found`, meaning no verified match by that method in that scope.
- Verified citations may support `ok` with explicit incomplete warnings; this
  does not prove an exhaustive set or total. Permission/operational failures
  and invalid hash/lineage/seal fail closed, never success or legitimate absence.
- Provider replan is separate: at most one changed plan when existing execution
  controls/budgets allow it, not a guaranteed second provider/MCP call.
  Attempted, bound evidence-lookup recovery with zero citations and explicit
  terminal/incomplete scan metadata stops safely without redundant provider
  continuation; incomplete stop requests clarification, not an absence claim.
  This separate provider plan repair must not bypass the automatic all-fields
  source-recheck rule. For graph results, outer
  `unsupported/planner_stopped_partial` qualifies
  only with validated eligible subquery provenance and the matching recovery,
  query, original-request, scope and scan bindings. This is not blanket
  admission of unsupported/errors; non-attempted graph replans, genuine
  operational/permission failures and exact plans keep their exclusions.
  Private graph recovery tracing derives only enums/counts/hashes from
  validated responses, never raw text, terms or identifiers.
  Public diagnostics contain safe statuses/counts/timings/fingerprints only,
  never raw paths, private source payloads, secrets, or hidden-source internals.

**Diagnostic comparability/observability precondition — 待測**

Before a browser/provider result may support root-cause attribution or
promotion, bind the loaded deployment to the frozen code/build/source
fingerprints and retain, at both request top level and each provider attempt,
the canonical request-shape, full tool-descriptor fingerprint (not names only),
upstream HTTP status, terminal outcome, and valid-attempt marker. UI HTTP
status is separate from upstream provider status.

If any required binding or field is missing, classify the artifact as
`diagnostic_only/incomparable`; it must not support a loaded-code mismatch,
no-data, provider-success, root-cause, or UAT-acceptance claim. Do not output
raw queries, source payloads, headers, or secrets.

This **ANY required diagnostic identity metadata missing → incomparable**
predicate is separate from **ALL requested business fields missing → source
recheck**; the business-field rule does not relax metadata safety.

**Promotion gate: 待測 → 標準功能**

- [ ] Both functions use the same core through the actual browser -> provider
  -> normal MCP -> authorized evidence -> cited answer path. For each, retain
  first-pass-miss evidence and successful source-recheck recovery evidence.
- [ ] Browser order: benign everyday chat (correct nonempty LLM response,
  MCP=0), mail request, independent-document request, reload, real server-state
  reset, then contextless chat (MCP=0). Verify citation content and source
  identity, not just HTTP success or nonzero citation counts.
- [ ] Both adapters pass incomplete/unavailable/deadline/cap, permission denial,
  invalid lineage/revision, exact-query exclusion, no-mutation, and leak checks;
  ordinary chat must not be forced through MCP.
- [ ] Freeze scope, source and code revisions, model/settings, budgets, and safe
  trace fingerprints; record commands, outcomes, timing, citation validation,
  and shared-core execution evidence. No question-specific fitting or consumed
  diagnostic/holdout reruns.
- [ ] Required canonical dev-container focused/full regression, changed-Python
  compilation, `git diff --check`, and existing three-reviewer gate pass;
  synchronize the specification, work board, role goal, and handoff with the
  acceptance evidence before changing the label.

Provider continuation after a `function_call_output` uses bounded SSE and
passes only a complete `response.completed`, `response.failed`, or
`response.incomplete` terminal object to existing response validation; an
error or EOF without a terminal object fails. The final-answer runner requires
the latest raw finalization validation to be `passed` and the final model to
cite at least one source; when provider attempts are present, the last record
must be valid and completed. A malformed trailing record cannot be skipped in
favor of an older success. Incomplete source coverage may still accompany a
valid cited answer. Synthetic SSE/runner tests are protocol diagnostics, not
live-provider acceptance.

Existing mail composition/provider `97/97` (12.317 s), `py_compile`, and
adaptive `3/3` results are historical partial diagnostics, not generic/browser
acceptance. Later bounded diagnostic tests above do not promote the feature.
The four methodology gates remain unpassed. Before
methodology-quality UAT or standard/default-path promotion, `--require-ready`
must pass; diagnostic implementation/testing can only retain the blocked claim
boundary. A functional diagnostic pass alone cannot claim research completion.

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
nodes are not materialized and do not influence results. Authorized source
evidence with no linked node or annotation remains available to the validated
retrieval plan. Graph and ontology signals may guide selection, but their
absence is not a source-coverage result. Query-time fallback or repair creates
no hidden candidate or canonical writes.

### 7.5 Deterministic exact execution

Ranked top-k retrieval cannot prove a complete set, total count, inventory, or
definitive negative.

Spreadsheet/table lookup, filtering, joins, sorting, aggregation, and counts
execute deterministically over the validated authorized source-native rows,
cells, and schema, or a faithful revision-bound structured projection with
proved lineage and coverage. A graph node property, generated summary, or
top-k chunk is not the authoritative value for such an operation. Preserve
same-row association, identifiers, header paths including merged headers,
coordinates, source types/precision/units, null/blank semantics, and the
distinction between raw value, formula, cached result, and displayed value.

The plan states which value representation and calculation semantics it uses.
A formula-dependent answer must verify the source formula and applicable
result/recalculation provenance; a cached XML value alone does not prove a
fresh formula result. Ambiguous headers, unsupported formula/type/display
features, incomplete rows, and permission-redacted ranges weaken or block the
corresponding exact claim. Native cell/range citations and completeness proof
are required even when graph links help identify the table. A definitive
negative requires complete authorized source coverage for the requested
predicate, independent of annotation or graph coverage.

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

Incomplete coverage produces a partial result and a weaker claim. Missing
graph or ontology entries cannot turn that partial result into a complete set
or a definitive negative.

### 7.6 Compact evidence context and answer generation

The Query Agent assembles a compact, modality-appropriate evidence-context
bundle containing the validated plans, requested-field coverage, selected
source evidence, provenance/citation bindings, conflicts, explicit blanks,
and relevant graph or ontology explanations. Its schema, contents, ordering,
budget, and fingerprint are recorded.

Bounded source-context augmentation may include an adjacent paragraph or
heading, a table header plus the relevant cell range, an image crop, or an
audio/music/video clip or frame needed to verify the selected evidence. Each
augmentation revalidates source occurrence, hash, revision, lineage,
permissions, native locator, and remaining evidence/token/time budgets. A
governed pointer and supported content representation retain the original
region/range/time span and any transformation metadata. An evidence-snippet
grant does not grant whole-asset access; graph visibility does not authorize
the crop, clip, or cells. No whole large asset or authorized-corpus dump enters
model context by default, and unsupported model/modality access remains an
explicit limitation. These reads reuse valid sources and projections rather
than starting inline extraction or rebuilding indexes. Automatic source
recheck remains governed by the unchanged §7.3.1 eligibility contract. That
section's `16 KiB` evidence-presentation cap belongs to the current mail/text
diagnostic profile; it is not a universal image/audio/music/video context
limit or proof that those modalities are supported.

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

#### 8.1.1 Development worker tier and metadata recording

As reaffirmed by the **2026-10-06 user authorization**, development permits an
orchestration-only Master and up to two ordinary implementation worker slots,
requesting `gpt-6.1-sol` with `reasoning_effort=high`. Current explicit bounded
assignments govern the disjoint worker write sets. The Master normally makes no
implementation or durable repository-document edits; an explicit current user
assignment may authorize a bounded edit in named paths. Dated task
scopes, closure records, old metadata, and “no further work” statements are
historical evidence, not future work bans. No descendants, duplication, or
additional workers are authorized. No substitution means no silent relabelling
of the observed model, effort, or worker identity; it does not prohibit
continuing explicitly bounded work through an available execution path.
UAT remains `gpt-5.5`/`high`, and the methodology authority and independent
three-reviewer gate remain unchanged.

The requested worker configuration is `gpt-6.1-sol` with `reasoning_effort=high`.
Dispatch should request that configuration and record the actual configuration
when it is observable, but persisted `session_meta`, `task_started`, and
`turn_context` are diagnostic metadata rather than an execution gate. Missing,
mismatched, unavailable, or unpinned worker metadata must be recorded as
`unverified`/`unavailable` and must not stop a bounded assignment. A worker may
continue through the available configured handle; it must not describe an
unobserved fallback as sol/high. Inherited context and prompt text remain
insufficient evidence for a positive model claim, but they are not reasons to
abort work. Durable records retain only safe task/turn IDs when present,
observed model/effort, UTC timestamp, and verification outcome; no raw rollout
paths, content, prompts, credentials, or source payloads.

This worker-tier paragraph alone grants no provider, deployment, source/index
rebuild, live UAT, full-suite, or reviewer acceptance action. An explicit current
user assignment may grant those operations within its named scope. Feature remains **待測**, step 4 is
in-progress, F841/full regression/live UAT/three reviewers/four methodology
gates remain open, and no standard functionality, readiness, completion, or
reviewer acceptance is established. Permission, privacy, audit, provenance,
and candidate-before-canonical protections remain unchanged.

The explicit **2026-10-07 bounded assignment** supersedes closed-slice wording
for its named paths and outcomes. It does not grant canonical writes, unsafe
permission bypass, source/index rebuild outside a named artifact, methodology
readiness, or reviewer acceptance. Provider, Docker, source, and live-UAT
operations remain governed by the latest explicit user assignment rather than
by this generic tier paragraph.

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

Every result is traceable to its authorized source and executed plan. Direct
source retrieval and source-native structured execution use:

```text
Source / Asset / EvidenceSnapshot
  -> ExtractorRun
  -> Observation
  -> SemanticQueryPlan and execution
  -> EvidenceBundle or deterministic result
  -> cited answer or projection
```

When candidate, graph, or ontology interpretation contributes to a result,
its additional lineage is recorded:

```text
Observation(s)
  -> Candidate Knowledge
  -> Review Decision before canonical commit
  -> CanonicalGraphRevision / OntologyRevision as applicable
  -> permission-filtered EffectiveGraphView when used
  -> the bound query execution and source-linked EvidenceBundle
```

The source chain is mandatory; derived chains are mandatory for the derived
signals actually used. Candidate, review, canonical-object, graph, ontology,
and effective-view IDs are conditional on those stages participating, not
preconditions for citing unannotated source evidence. Candidate-only
interpretation retains its source lineage and review state without implying
a canonical commit. Stable identifiers,
as applicable to the source and execution, include:

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

The request path reuses activated projections where available and may use an
independently validated immutable authorized Observation/source snapshot for
fallback eligible under §7.3.1 without the failed projection. Projection
failure grants no independent eligibility. Source/hash/lineage/revision
checks remain required. Rebuilds are explicit offline or
governed lifecycle jobs triggered by source, policy, model, tokenizer, schema,
or operator changes; a KG miss, exact-lookup miss, or prompt retry never starts
one.

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

Current source support must be read at the following granularity:

| Source slice | Current code evidence and limit |
| --- | --- |
| Mail and independent text | Mail is the first diagnostic fixture; the real `PlainTextObservationExtractor` handles independent Markdown/plain-text. §7.3.1 retains its mail/text-only diagnostic and promotion boundary, with live acceptance still open. |
| XLSX and delimited attachment tables | [`AttachmentDocumentExtractor`](python/formowl_ingestion/extractors/document/attachment.py) reads bounded XLSX ZIP/XML values (`<v>`, shared strings, inline strings), emits row/cell Observations and coordinates, reads formal table metadata, and derives bounded candidate header paths using merged ranges. It does not retain `<f>` formulas or cell styles/display formatting and does not prove formula, displayed-value, native-type/unit/null, or whole-workbook completeness. Candidate header structure is not verified source-provided schema. Standalone spreadsheet/XLSX is a first-class product requirement; this attachment slice does not establish its complete end-to-end path. |
| OCR/images | [`FixtureOcrExtractor`](python/formowl_ingestion/extractors/ocr/fixture.py) reads text-backed fixtures with page/bbox locators via `read_text()`. It proves fixture contracts, not real-image OCR, visual retrieval, or source-region understanding. |
| Audio | [`FixtureAudioTranscriptExtractor`](python/formowl_ingestion/extractors/audio/fixture.py) reads text-backed timestamp/speaker/transcript fixtures via `read_text()`. Real-audio decoding, ASR, acoustic retrieval/verification, and a music or non-speech audio path are not proven. |
| Video | [`FixtureVideoSceneExtractor`](python/formowl_ingestion/extractors/video/fixture.py) reads text-backed scene/keyframe descriptions and locators via `read_text()`. Real-video decoding, temporal/visual retrieval, and native clip/frame verification are not proven. |

MIME declarations, modality labels, fixture coordinates/timestamps, and cited
text proxies do not establish native media support. These are implementation
limits within the wider product architecture, not a restriction of the product
to mail/text and not permission to infer source absence from unsupported
features or missing projections.

The active research target is:

```text
method: evidence_to_knowledge_kg_ontology_v2_hybrid_v1
tokenizer: jieba_sentencepiece_frozen_profile_candidate_admission_v1
```

Historical runtime on August 18, 2026 (not current runtime authority):

```text
method: mail_candidate_kg_broad_ontology_diagnostic_v1
tokenizer: ascii_identifier_regex_v1
CJK support: false
```

The recorded October 2, 2026 canonical dev-container probe matches the frozen
method/tokenizer with CJK support true; this is a dated diagnostic, not
production or completion evidence. Current readiness is determined by the
executable authority, not this historical runtime block.

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
- standalone spreadsheet/XLSX and image/audio/music/video requirements retain
  native structure, modality, locators, and authorized source references;
- source completeness is reconciled against an independent oracle;
- completeness includes the source-native features needed for the claim,
  with unsupported formulas, display/type semantics, or media content disclosed;
- source occurrences survive deduplication and entity resolution;
- deterministic and semantic extraction remain separate;
- candidate output cannot silently mutate canonical state.

### 15.2 Graph and ontology

- canonical commits are scoped, reviewed, revisioned, and source-backed;
- every answer-relevant graph hop resolves to authorized Observations;
- zero-to-many source-addressed annotations are optional; unannotated evidence
  remains retrievable, and missing graph/ontology entries never prove absence;
- the stable ontology core transfers across at least two materially different
  source/domain families;
- inferred ontology mismatch does not remove admitted evidence;
- contradiction, correction, supersession, split, and merge preserve history.

### 15.3 Query and answer

- strong RAG uses modality-appropriate retrieval over the same source-complete
  Observations; lexical+dense text retrieval is one branch, and real native
  media verification is required for visual/acoustic/musical/video claims;
- the core Query Agent accepts the user prompt plus bounded, versioned
  conversation state and resolves intent and coreference before MCP execution;
- a human office-agent surface appends attributable per-turn results, restores
  its bounded server transcript after reload, preserves sanitized failed turns,
  and starts a new conversation by clearing server state rather than only the
  page;
- visible transcript retention is distinct from the smaller bounded model
  context, and the UI discloses temporary expiry, eviction, and restart limits;
- ambiguous references fail closed or request clarification, and MCP tools do
  not infer hidden history from `query_text`;
- actual authorized source schemas, native modalities/locators, current MCP
  capabilities, and graph/ontology revisions when used are discovered, pinned,
  and revalidated before tool calls;
- activated KG/index revisions are reused across requests; a validated evidence
  lookup eligible under §7.3.1 may fall back after an index/graph miss or
  projection failure
  to the same authorized Observation/source scope without a per-query rebuild;
  a KG miss alone does not establish absent data;
- identifier-plus-field requests use typed exact lookup before agent-expanded,
  bounded iterative query-expansion/strong-RAG recovery, while preserving row
  association, citations, permission scope, and the remaining deadline/budget;
- query expansions remain candidates, and every executed subquery or tool plan
  is independently validated, permission-bounded, versioned, and audited;
- requested-field coverage and evidence diversity govern bounded iterative
  repair/requery, context selection, phase tracing, and the recorded stop
  reason;
- for validated `evidence_lookup`, a nonempty validated requested-field set
  with all fields lacking verified support triggers one materially different
  same-authorized-scope bounded source recheck when existing safety/eligibility
  and remaining budgets permit, even with unrelated citations; partial misses
  must be disclosed and must not trigger this automatic recheck, empty sets
  use the validated evidence-need plan or clarification, and source-backed
  explicit blanks count as verified coverage;
- retrieval-projection availability is independent of authorized immutable
  source snapshot validation; fallback does not require the failed projection
  or rebuild inline, but projection failure grants no independent eligibility;
  citation count/status alone cannot trigger, and incomplete/timeouts never
  establish absence;
- the final model context is a compact, fingerprinted, citation-bound evidence
  bundle; bounded authorized source context may include crops, clips, or cell
  ranges with native provenance and separate raw-access checks;
- native spreadsheet/table operations use validated rows/cells and source
  semantics, preserving formula/raw/display distinctions, types, units,
  nulls, merged headers, coordinates, row association, and completeness;
- exact-set claims use deterministic enumeration and coverage evidence, with
  no graph-property or top-k substitution for source-native values;
- answers cite evidence and disclose conflict or incompleteness;
- provider errors and timeouts remain operational failures distinct from
  no-authorized-evidence or legitimate no-answer outcomes;
- no-answer and permission-denied behavior fail safely; and
- unseen pre-registered prompts pass without question-specific identifiers,
  aliases, expected answers, or success-pattern fitting.

### 15.4 Evaluation

- comparison arms share source, permission, tokenizer, answer model, prompt,
  budgets, evaluator, and environment;
- holdout content cannot influence construction or tuning;
- final-answer, citation, identity, relation, temporal, exact-set, no-answer,
  privacy, latency, and cost metrics are reported by stratum;
- native source/modality capability is verified separately from text-proxy or
  fixture behavior; new modality evidence cannot silently change the frozen
  issue #56 comparison scope, profiles, or gates;
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

The center of FormOwl is reusable source evidence with governed overlays:

```text
Any Source
  -> Governed Asset / EvidenceSnapshot
  -> Source-Preserving Observation (text, structured, or native media reference)
       -> Authorized Modality-Appropriate Retrieval / Native Structured Execution
       -> Optional Evidence-Backed Candidate Knowledge
            -> Review -> Canonical KG + Scoped Ontology -> EffectiveGraphView

Core Query Agent + Validated Plan
  -> Authorized Source Execution with Governed Graph/Ontology Signals When Used
  -> Bounded Verified EvidenceBundle / Deterministic Result
  -> Cited Answer, Projection, or Reviewed Action Proposal
```

Direct authorized retrieval and exact table execution do not require a graph
match or ontology annotation. Graph-required relation reasoning retains the
source-backed governed path. The frozen issue #56 program still evaluates
graph-guided hybrid execution against its strong RAG control under the same
authority and acceptance gates; this schematic makes no methodology-change,
readiness, or superiority claim. The graph earns its place through measured
integration benefits with source evidence, permission, and provenance intact.
