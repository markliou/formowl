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
plain text. FormOwl has two explicit execution modes: `direct_evidence_baseline`
allows authorized source/native retrieval without a semantic overlay, while
`ontology_aware_uat` requires a complete semantic-ingestion pass over its
_declared authorized scope_ before it may claim ontology-aware behavior. Native
evidence remains usable without an annotation in the baseline or as a bounded
fallback; that fact must not be mislabeled as ontology-aware UAT. Product
requirements and currently verified adapter capability are distinct; §14 records
the limited implemented slices.

---

## 3. Canonical Architecture

FormOwl has a knowledge-construction path and a query-execution path.

### 3.1 Knowledge construction

```text
heterogeneous sources
  -> Asset / EvidenceSnapshot
  -> ExtractorRun
  -> source-completeness reconciliation
  -> source-preserving Observation
       -> ontology-aware semantic ingestion for the declared scope
          (LLM semantic candidates with deterministic parser support)
       -> review and governance
       -> canonical KG + scoped ontology revisions
       -> permission-filtered EffectiveGraphView
```

The `direct_evidence_baseline` may branch from the Observation snapshot to
authorized retrieval/native structured execution without semantic annotations.
That branch is required for recovery and comparison, but it is not an
ontology-aware UAT completion path.

Evidence preservation precedes semantic interpretation. The graph and ontology
are governed reusable overlays linked to Observations; creating those overlays
is not an admission prerequisite for the explicitly named direct-evidence
baseline or its bounded fallback. It is required for an ontology-aware UAT
claim. Candidate review remains mandatory before canonical commit.

### 3.1.1 Explicit execution modes and ontology-aware UAT contract

**2026-10-18 product requirement — 待實作／待測, not deployed capability.**
These names describe required execution/claim boundaries, not flags already
implemented in the UAT. They share existing owners and one source pipeline;
they do not authorize a second answer service or a replacement ontology store.
The frozen issue #56 method, tokenizer, experimental arms, budgets and executable
authority remain unchanged. This product contract does not regrade old results
or permit changing a frozen experiment while `--require-ready` is nonzero.

Each run must record its intended mode and the actually exercised path:

| Mode | Semantic ingestion requirement | Allowed claim |
| --- | --- | --- |
| `direct_evidence_baseline` | Annotation may be absent; validate source integrity/permission and disclose coverage | Direct source retrieval/native execution; never ontology-completion evidence |
| `ontology_aware_uat` | Complete declared-scope inventory, extraction, semantic annotation, governance, and activated overlay are mandatory | Ontology-guided source selection, cross-source reasoning, and cited answers |

`ontology_aware_uat` is not satisfied by a regex/substring/entity-token index,
by a top-k RAG result, by a graph schema, or merely by recording ledger rows.
The LLM semantic reader must process all authorized source units in the
pinned scope, including mail bodies, threads, quoted/forwarded context where
available, and every authorized attachment through its native parser or an
explicitly recorded unsupported/failed result. A unit with no business fact is
still marked `annotated` with zero candidate assertions; it is not omitted.

Full reading is query-independent offline work, not the entire corpus in one
prompt. Bounded document/paragraph/page/sheet/range batches preserve parent,
header, row and conversation context; a document-level reconciliation then
resolves source-backed cross-chunk, cross-message and attachment relationships.
Truncated context or an unread attachment remains a coverage gap, not an
annotated zero. Source content is data, never instructions to the worker.
Parser/schema/regex extraction supports identifiers, coordinates and explicit
values; it cannot replace LLM interpretation of natural-language meaning.

Reuse a completed semantic read only when source hash, occurrence/permission
lineage, parser output, model/prompt/schema/profile and ontology pins still
match. Checkpoint bounded batches; interrupted/unvalidated output stays pending
or failed, retries have lineage, and changes produce new immutable revisions.
Do not regenerate annotations per question. New or revised source units are
processed incrementally, including affected cross-source links, before claiming
coverage for a new snapshot. Freeze scope before testing; do not exclude a
difficult attachment after seeing a failed question.

The required per-scope ledger distinguishes:

```text
source_inventory_status: complete | partial | pending | unsupported | failed
extraction_status: complete | partial | pending | unsupported | failed
annotation_status: annotated | pending | unsupported | failed
review_status: published | pending_review | rejected | superseded
projection_status: sealed | unsealed | missing | stale | failed
```

The ledger is required metadata owned by the existing IngestionJob/ExtractorRun,
Observation, semantic-candidate and governance services, not a new truth store.
The ledger binds the source inventory, Observation/ExtractorRun manifests,
annotation profile and model/prompt fingerprints, `OntologyRevision`, graph
revision, permission/effective-view revision, and a coverage fingerprint. Any
`pending`, `unsupported`, `failed`, partial, stale, or unexplained item prevents
a complete-coverage claim for the affected scope. `pending_review` describes
governance, not a synonym for parser/provider failure. Keep source, extraction,
annotation, review, projection, query coverage and answer support separate.
These gaps never prove `not_found`. Supported source facts may still be returned
with explicit coverage limits; unrelated pending units must not make the whole
UAT unavailable. Eligible baseline/source fallback remains bounded by §7.3.1,
including the ALL-requested-fields rule; a missing ledger is not a new retry
trigger. No inline rebuilding or extra request budget is authorized.

Ontology-aware query execution is therefore:

```text
validated natural-language intent
  -> ontology classes/entities/events/claims/relations/time frames
  -> source-linked candidate observations and bounded graph paths
  -> native source retrieval or deterministic structured execution
  -> temporal/conflict/supersession validation against original evidence
  -> cited EvidenceBundle / deterministic result
```

The ontology is a semantic index and reasoning overlay, not the source of truth.
Every returned value and every answer-relevant hop must be revalidated against
source-native evidence with a locator, revision, hash/lineage, and permission
binding. Trace actual selected annotation IDs, semantic-plan slots, source
Observations and final citations; merely loading an ontology does not prove use.
Mechanical pass completion does not prove semantic precision/recall; §15.6
requires independent source-backed answer acceptance.

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
validated explicit state when the tool contract supports it.
A new explicit target requiring workspace evidence needs its own governed lookup;
unrelated prior citations cannot substitute for current-target support. A closed
negative-source clause plus a fully supplied-text transformation remains ordinary
chat; mixed instructions that also request source facts do not inherit that exemption.
An MCP tool must never infer hidden conversation history from an under-specified
`query_text`.

**Closed supplied-input isolation — deployed since R39, retained in R55 / 待測, not release accepted.**
A trusted closed task over current supplied input must neither offer unrelated
retained evidence/citations nor accept them in its final answer. Only for that
turn, omit latest evidence and prior-visible/reference capability metadata from
current citation authority. The legacy/app-server path also omits bounded prior
history from provider input. The configured Responses path introduced in R54 and inherited by R55 instead keeps
its already-sent append-only journal and appends an explicit current supplied-input
boundary: historical text is not current evidence or citation authority. That new
path supersedes provider-history omission only, not deterministic isolation gates.
Preserve the original current prompt and use existing membership validation and
bounded finalization repair to reject hostile retained citations; do not append
citations or silently erase global session state. Genuine prior-answer transforms,
positive/mixed source requests, exact-capability paths and ordinary chat retain
their own gates. Tools-none/MCP0 is necessary but is not isolation proof; no new
provider allowance, source operation, public schema, permission relaxation or
budget change is granted. Isolation requires explicit supplied-input authority;
a bare prior-relative transformation recognizer is not sufficient. The corrected
[r3 focused80PASS](.formowl/uat-weekend-20261016/worker-anscombe-supplied-scope-r29/r3/verification.safe.json) and
[scoped peer AGREE](.formowl/uat-weekend-20261016/ops/reviewer-nash-supplied-scope-r29-r3-safe.json) are included in R39.
[R29-r6 supplied-task observations](.formowl/uat-weekend-20261016/ops/browser-r29-r6-manual-review-safe.json) support only their finite rubric;
r2's retained-context regression and failed R37/R38 integration remain preserved
in the [handoff](docs/agent-goals/handoff-log.md), not retroactively accepted.

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
turns, keeps at most `8` messages in its semantic-routing/legacy model-history
envelope, and expires a browser session after its existing `1` hour lifetime.
The configured Responses R54 provider journal below is separate from that smaller
envelope: its sent prefix is not truncated to eight messages. These are diagnostic implementation bounds,
not permanent product defaults or a cross-restart persistence guarantee.
Its runtime defaults are `0.0.0.0:8088` for `--temporary-lan-diagnostic` and
`127.0.0.1:8766` for normal UAT. Explicit `--host` and `--port` values
override those defaults. A temporary access code is optional; the temporary
LAN UAT remains usable when no access code is supplied.

**R55 closed supplied-text routing correction — diagnostic deployed / 待測.**
The shared recognizer may consume complete known negative-source clauses outside
one quoted supplied input, including between the supplied-text instruction and
input. The entire remaining exterior must be closed transformation instructions;
source-looking quoted text is data, while unresolved/mixed fresh-source clauses
retain governed routing. It does not rewrite the original request, change current
citation authority, or exempt arbitrary no-lookup requests. The later
[R55 actual-browser finite review](.formowl/uat-weekend-20261016/ops/provider-session-r55-manual-review.safe.json)
supports the supplied-text correction within its nine-question limited-pass batch;
original R54 C663 FAIL remains immutable. This is not arbitrary-language, full-UAT
or release acceptance, and does not make the broader regression green.

#### R54 configured Responses conversation contract

**Current user contract; diagnostic deployed in R54, inherited byte-identically by R55 / 待測, not release accepted.** Applies only to
Responses conversations explicitly configured by the trusted UAT runtime. Legacy
bridge/app-server behavior and dated acceptance evidence are not reinterpreted.

1. A server-owned UUID identifies one browser conversation. Every provider request
   in that conversation, including tool continuations and bounded repairs, uses the
   same UUID in the custom bridge header `X-Codex-Pool-Session` and `prompt_cache_key`.
   This is the configured provider contract, not a claim of universal OpenAI header
   support or guaranteed cache hits. Reload and failures retain the same journal;
   a new conversation gets a new UUID. Reset/new/logout/expiry/eviction dispose the
   old identity; an in-flight retired reply cannot dispatch MCP or resurrect it.
   The finite nonblocking reset proof covers the temporary-LAN/provider barrier,
   not nonblocking OAuth service reset; no cross-restart persistence is promised.
2. Instructions and the complete initially available tool catalog stay byte/order
   stable, including typed-field guidance. Include both mail and graph evidence
   tools only when actually available. Per-turn selected-tool routing, capability
   summary, original request/fields/terms and validation remain authoritative;
   fixed catalog presence grants no additional tool or source authority.
3. Input is append-only across turns, tool outputs and repairs, including failed
   send prefixes. Put clock/current request/capabilities/evidence and other dynamic
   data at the tail; do not reconstruct or trim the prefix from the eight-message
   routing history. A server-local clarification before the first provider send is
   not a missing-journal error. At the bounded journal limit, stop safely and ask
   for a new conversation; never silently truncate, rotate the UUID or rebuild it.
4. Ordinary chat, closed supplied tasks and no-tool finalization retain the stable
   `tools` catalog but use `tool_choice="none"`; server dispatch also rejects any
   forbidden call. Here “tools-none” means no executable tool permission, not an
   empty catalog. Current citation/identifier/native/source gates still reject
   unrelated historical evidence despite its text remaining in the journal.
5. Use honest `User-Agent: uat-web-backend/0.1.0`, matching [application version](pyproject.toml). Preserve configured model,
   reasoning, stream/store behavior and existing provider/tool/retry budgets. The
   explicitly bounded append-only provider context is the only new context scope;
   source500ms and all source/hash/revision/lineage/permission guards are unchanged.
6. Optional `request_shape.conversation_contract` proves actual serialized requests
   through hash-only UUID/header/cache-key, instructions/tools/input/settings hashes,
   counts and prior-prefix equality, plus safe UA/flags. No raw UUID, header, prompt,
   source text or credential is exposed. Local mocks are not actual browser proof.

The separate hosted public-terminology lookup cannot silently receive a second
UUID or private append-only context. For this configured path it is paused
with a safe unavailable result and no external call; the longer-term exception
decision is pending user approval. Its custom function may remain in the frozen
catalog, but that presence does not authorize hosted web execution. No new source,
provider or browser operation is authorized by this specification paragraph.

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
candidate assertion, or any number of source-addressed annotations, candidate
atoms, candidate entities/business objects, relations, and frames. This is a
cardinality rule, not permission to skip a scoped semantic read: in
`ontology_aware_uat`, every unit receives an annotation-ledger outcome, and a
legitimate zero-candidate unit is `annotation_status=annotated` with count zero.
A candidate may span multiple Observations, but every candidate keeps the
contributing Observation IDs and source occurrences; no layer may impose a
one-annotation-per-document or one-annotation-per-Observation rule.

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
canonical relation types. An annotation remains zero-to-many: one Observation
may support no candidate assertion or many, and an assertion may bind several
Observations while retaining every source locator. Zero-to-many describes the
semantic result cardinality; it does not mean that an ontology-aware run may
skip reading a source unit.

For `direct_evidence_baseline`, no annotation, type mapping, or compatible
ontology path is required to admit otherwise authorized evidence. For
`ontology_aware_uat`, the declared scope must have a complete source inventory,
attachment-aware extraction, semantic annotation ledger, review/governance
status, and pinned overlay before an ontology-aware completion claim is valid.
Missing, pending, unsupported, or failed overlay entries never establish source
absence; disclose the relevant coverage/review state and preserve supported
facts. Bounded fallback requires §7.3.1 eligibility, not the gap alone.

#### 6.2.1 Required semantic annotation content

The LLM semantic reader must interpret source meaning, not merely split
strings. For each in-scope mail/attachment or other source unit, it may emit
zero-to-many source-linked records for:

```text
entities and aliases
claims and asserted values
business events and state transitions
relations and cross-source identity links
temporal frames: asserted/effective/due/valid/superseded time
thread, reply, quote, forward, and attachment lineage
correction, contradiction, update, and supersession relations
```

Each record retains the source Observation IDs and native locators, raw span or
cell/range/media reference, normalized interpretation, date meaning and
precision, confidence, model/prompt/schema/profile revisions, permission scope,
and candidate/review status. The LLM may propose these records, but cannot
silently publish canonical types or graph truth.

A mail delivery-style domain pack is one example, not a hard-coded feature. It
can represent a requested/confirmed/updated delivery commitment, a shipment or
invoice event, and a `supersedes` relation across messages and attachments.
A materially different project/work-item pack can represent an owner,
deadline, status transition, dependency, and attached decision record. Both use
the same core `Actor`, `Artifact`, `Event`, `Claim`, `TimeInterval`, and
`StateTransition` concepts and must be validated against their original source.

Annotations are assertions about a target in context, not document tags alone.
Bind scope, subject/entity, line item or part, quantity/unit when relevant,
asserting actor, assertion/event type, time role, raw expression and supporting
spans/cells. Distinguish a request, tentative forecast, commitment, correction,
shipment, receipt and invoice. An invoice date is not a shipment/delivery date;
message time is not event time; a later message does not supersede all earlier
items. Supersession needs source-backed target/field/scope and update evidence;
unresolved alternatives remain conflicting candidates. Do not collapse several
order lines, lots, dates or organizations into one answer.

Mapping documents to a shared type (for example `Event`) is not an entity join.
Query plans combine target identity, requested semantic roles and time/scope
with supported links, not every document with a broad tag. Unknown concepts
remain source-local candidates for review; never force a wrong existing type.

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

**Closed prior-relative evidence presentation — R33 diagnostic deployed / 待測.**
Only when server-retained evidence is both present and citeable may a fully closed
translation/rewrite/reformat/summary describe the prior retrieval in a relative clause.
That clause is provenance, not a fresh lookup instruction; additional clauses must
only preserve citations or prohibit a new search. Unknown/mixed operations fall through
to existing routing. Protected targets, fresh source bindings/actions, explicit workspace
markers or quoted labels do not gain this new exemption. Supplied-text controls remain
separate; no citation grant, retained lifetime, permission, typed coverage, final validator,
retry, source500ms or other budget is relaxed. This removes unnecessary forced planning,
not a provider-incomplete cause/availability fix or proof of real retained translation.

**Explicit prior-visible citation preservation — R35 diagnostic deployed / 待測.**
For a fully closed prior-answer transformation with an explicit citation-preservation
clause, the obligation is exactly the immediately preceding successful visible answer's
citation IDs (`complete` or `partial`), not the retained-evidence union or an older turn.
Require nonempty IDs within the existing response cap and current compacted governed
retained membership before provider invocation. Failed/chat/reset/missing or compacted
prior authority clarifies; it cannot recover authority from model prose or older history.
Every non-clarification draft must include all required prior-visible IDs and pass the
existing availability, typed coverage and public-safety validators. Omission uses only
the existing one-shot no-tool repair (`tool_choice="none"` with a stable catalog
on configured R54 Responses; legacy offering unchanged); repeated omission stops, without appending or
fabricating citations. No new MCP, source read, provider allowance or budget. Ordinary
no-preservation subset semantics and mixed fresh-source/supplied-text gates remain.
Scoped synthetic review/integration is not real-browser no-drop or release acceptance.

The bounded protected-business-identifier implementation may retain one unique
server-owned identifier from an actually dispatched validated request with
citations, admitted only after a cited final answer or partial result. A reference
request must bind that same identifier in its tool query and conjunctive terms.
NFKC/casefold normalization applies before identifier extraction; an explicit
current identifier wins. The original current-prompt hash remains unchanged and
separate from the prior source-turn hash. Missing, ambiguous, reset or invalid-scope
references clarify/fail closed before provider or MCP execution; uncited/failed
turns cannot establish an anchor. Retention cannot widen source permissions or
parse arbitrary history. This narrow alphanumeric-ID capability does not establish
general numeric, person or natural-language coreference support.

Expanded tool queries must pass the existing query-content safety validation
before MCP dispatch. Rejected expansion may use only the existing bounded repair
allowance, preserving the validated identifier, request and authorized source
scope. A valid repaired expansion may then execute; invalid content must not reach
MCP. This adds no retry/budget allowance and leaves remote/global guards intact.

The server owns both conversation-state and transcript selection. Client
payloads may carry the current prompt, but cannot inject, replace, or extend
trusted prior turns. A failed turn may remain visible as a sanitized transcript
event while leaving the last valid model history and evidence state unchanged.
Transcript retention and model-context retention are independently bounded and
reported by the active surface.

Every query routes to one of four classes:

| Query class | Required execution |
| --- | --- |
| `evidence_lookup` | strong RAG over source-preserving Observations; in `ontology_aware_uat`, ontology-linked entities/events/claims/relations must guide source selection before raw-evidence validation |
| `relation_reasoning` | provenance-constrained typed traversal with source evidence for every hop |
| `exact_set_or_inventory` | deterministic structured enumeration with an explicit coverage contract |
| `global_summarization` | explicitly bounded, permission-filtered source/evidence set with incompleteness disclosure |

Queries asking for all, every, count, inventory, duplicates, missing items,
exact membership, completeness, or definitive absence route deterministically
to structured execution.

Business examples describe applications of this shared core, not separate
question-specific functions. A set of 30 target examples is not a claim that
30 functions are implemented. Generic native-table field lookup binds arbitrary
requested fields to the current authorized source schema, preserving identifier
and same-row constraints; unknown or ambiguous structured bindings require
clarification. An unrelated table schema must not divert ordinary text lookup.
Attachment text and independently registered document text use the same
governed query core with distinct source/parent bindings. Each application still
requires evidence for its actual native features, coverage and claim strength.

### 7.2 Capability discovery and validated plan set

Before planning execution, the Query Agent discovers and pins the actual
current capabilities available to the request:

```text
authorized source schemas, modalities, native locators, and field capabilities
current permission-filtered source occurrence providers
current semantic-annotation ledger, coverage fingerprint, and overlay activation state when ontology-aware
current EffectiveGraphView and scoped ontology revisions when used
current MCP tools and their actual input/output schemas
```

Descriptions, cached assumptions, public documentation, and model knowledge do
not override these runtime contracts. Tool arguments and source-field
projections are validated against the discovered schemas before execution.

An attachment is a container, not necessarily table evidence. Parsed mail
attachment text stays in `mail`; `attachment_table` denotes native tables;
`document_text` denotes independently registered documents. Local attachment
document qualifiers and explicitly literal source-label predicates must not
invent an independent-document requirement or become accidental AND filters.
The server supplies the required source-family scope before planning. The
current request schema and validator both admit up to three available families;
this capacity grants no access to an unavailable family. Repair may correct a
rejected scope, but cannot replace an already validated request boundary.

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
semantic_annotation_ledger_id and coverage fingerprint when ontology-aware
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

The current UAT provider bridge permits one transport recovery only for the
observed HTTP `408`/`invalid_request_error` signature reporting a stream closed
before `response.completed`, and only before any FormOwl/public tool execution.
It retries the same request using explicit SSE within the original deadline
and existing six-provider-request ceiling, sharing the single pre-tool recovery
allowance with empty-body recovery. Ordinary chat has no executable tool permission:
legacy requests offer no tools, while configured R54 Responses retain the fixed
catalog with `tool_choice="none"` and server-side call rejection.
Unrelated errors, repeated disconnections, missing terminal events and expired
budgets remain failures; post-tool failures preserve governed partial evidence.
Failed attempts remain in the bounded trace. This mechanism is **待測** for
live provider stability, not proof that the upstream service was repaired.
The direct-provider UAT entrypoint explicitly uses SSE from the initial request
to avoid waiting for a fully buffered JSON response. The reusable bridge retains
JSON compatibility by default. An already-streaming failure is not retried via
the same transport; a compact safe recovery-trigger record survives the bounded
attempt tail when legacy JSON recovery is used.

Provider SSE repair proceeds in separate evidence-gated stages (2026-10-12,
**待測**): (1) parse named and data-only error events before raising, including
the Responses flat `type: error` envelope; retain only bounded safe diagnostic
fields and distinguish explicit errors, failed/incomplete terminals, malformed
events, premature EOF and transport deadlines; (2) isolate a benign no-tool
request through direct provider and UAT bridge paths with pinned model/settings
and request/code bindings, then inspect bounded same-call failure evidence;
(3) apply a countermeasure only to the demonstrated failure class, without
speculative retry/timeout increases; (4) verify chat, governed MCP dispatch and
reload/reset through the browser. Protocol tests or one passing provider call
do not establish stability. Unknown upstream causes remain unknown; provider
errors never establish source absence. These stages require no index rebuild
and do not relax the existing retry, source, privacy or methodology boundaries.
Transport failures retain a bounded failure phase, allowlisted exception family,
cycle-safe nested cause/reason families and errno, request timeout and remaining
deadline, observed HTTP status, and hash-only request ID through HTTP/gateway
projections, attempt records and safe terminal traces. Received byte counts and
other wire metadata are retained at top level, through public projections and
safe terminal traces; causal/deadline/status/hash metadata is also retained per
attempt.
Raw exceptions, URLs, headers, bodies and private payloads are excluded. A close
failure cannot erase the primary read failure; diagnostic types do not alter
existing reason/retry/deadline/model/source policy. The 2026-10-12 isolated
browser pass used an intermediate snapshot preceding final diagnostic guards;
the historical continuation failure was not reproduced and its root is unproved.

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

### 7.2.1 Ontology-guided query execution and fallback

When the declared mode is `ontology_aware_uat`, the Query Agent must form a
semantic plan that identifies the requested entities, event/state types,
relations, temporal role, source family, and requested fields. It then uses the
pinned ontology/effective graph to select source-linked Observations and native
attachment/table records. The answer path must still validate the selected
values against original evidence; an ontology assertion, graph property, or
LLM summary alone is not evidence.
Keep ordinary chat tool-free and preserve the existing typed identifier/field
lookup ordering. Simple native exact lookups need no artificial graph detour;
record their actual direct path. Ontology-assisted semantic queries must show
real annotation use, without making a graph match an evidence-admission gate.

The plan must inspect the annotation/source ledger before declaring a miss:

```text
complete deterministic source coverage + no eligible evidence -> scoped negative
top-k miss or incomplete coverage/projection -> incomplete; eligible fallback or stop
parser/model/provider error -> operational error with root cause
permission denial/redaction -> denied/redacted, not no-data
```

A KG/ontology miss, empty projection, deferred attachment, or incomplete index
is never a definitive `not_found`. The fallback may use the independently
validated immutable source snapshot, strong RAG, native table execution, or a
bounded materially different recheck under the existing budgets. It may not
rebuild an index inline, widen permissions, or hardcode a user question.
Missing annotations/projections do not independently trigger automatic recovery:
§7.3.1 still requires validated `evidence_lookup` with a nonempty requested-field
set whose fields ALL lack verified support. Partial misses are disclosed, not
automatically rechecked; source-backed blanks count as covered. Normal planned
ontology/native/strong-RAG retrieval is separate from this one recheck.
Record the actual path, annotation IDs used, admitted evidence and stop reason;
fallback success remains source-answer evidence, not ontology-function proof.

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
does not cap the entire provider request/context size. Provider diagnostics must
carry the authoritative count (maximum `6`, derived from existing execution
budgets) and all safe attempt/timing records within that budget. Frozen r11's
latest-`3` truncation contradicts this contract; the prior r12 included the frozen
retention repair with canonical focused117/117 verified as described below.
All three retention-only scoped reviews agree. No timeout, execution
budget or retry allowance is increased.

**Full-envelope admission and diagnostics — 待測.** A proved `group_byte_budget`
rejection may reselect from at most `128` already-validated cached source units
against the same full `16 KiB` envelope, including metadata. Preserve complete
child/parent units, full text, provenance, dependencies and all coverage limits;
no orphan context, source-text clipping or source rereads. Harmless regrouping
is not evidence loss; exact inventory remains all-or-none.
The existing `500 ms` source-read/recheck phase is unchanged. Cached presentation
uses only the remaining existing scoped TURN deadline; without that scope it
retains the old source-phase deadline. No deadline reset or cap increase.
Native-family reservation uses existing item slots; cached backfill adds no reads.
The eligible ordinary overflow/material-loss selection contract below is an explicit presentation-priority exception, not a source-ranking change.

**Validated ordinary cache selection — design approved, candidate in progress / 待測; not deployed (2026-10-17).**
For validated `evidence_lookup` with nonempty validated requested fields, retain only already-guarded/projected plain mail body+own-header or independent document units before the original source deadline, including eligible prefix byte/item-overflow rejects. Reuse the existing presentation cache; cache membership does not grant callback admission, `last_anchor` or dependent-neighbor eligibility.
Only after normal reader/full-tail drain, and only for overflow or material full-envelope loss, may complete eligible staged+cached units be reselected using validated field strings, the frozen tokenizer and already-projected snippets: marginal field-token coverage/diversity; deterministic ties use staged units in existing order, then cached units in reservoir order, **not global source-arrival order**. These are soft relevance signals, never verified support, aliases or source absence.
**This narrow path supersedes admitted-first presentation priority:** earlier provisional groups may be evicted whole. Other paths retain legacy behavior; existing deadline-stopped deferred backfill outside this new eligibility keeps admitted-first/source-arrival order. No eligible cache leaves original compaction unchanged.
Keep one reservoir within `16 KiB` serialized groups and at most `128` combined distinct staged/deferred/cache units; deduplicate references. Preserve whole body/header units, caller item limits with header slots, and the actual final full-envelope `16 KiB` cap. Individually oversized groups are discarded, never clipped; bounded serialized size is not a measured heap bound.
Every trial uses existing compose/fit/compaction and rebuilds consistent citation/lineage/coverage/recovery/bundle fingerprints. Commit only a whole fit completed within the original remaining same-turn presentation deadline; a late trial cannot replace the safe fallback. No source read/callback/reprojection/permission lookup, deadline reset, refill or extra model call.
Source/helper/tail/permission/invalid-source failures remain fatal; existing structured-failure exclusions remain unchanged. Explicit exact, native/table, auto-exact and cross-unit same-source dependent-neighbor paths gain no new selection eligibility or dependency closure.
Keep incomplete/context-limit disclosure and unknown support; no corpus completeness, recall, latency or guaranteed known-case repair claim. Source `500 ms`/`8192` and all other budgets stay unchanged; the user3s proposal is unanswered. Earlier cache-only deadline-backfill behavior does not authorize source work after expiry.

Private compaction diagnostics contain only closed reason codes and aggregate
byte/group/count metadata, never query or source values. Proposal attempts remain
distinct from actual tool dispatches in stop labels. Provider `incomplete_status`
is not evidence of parsing failure and must not be labelled as one without proof.
These diagnostic contracts remain **待測**: no live business-answer acceptance,
methodology authority, readiness or release approval is established.

The source recheck uses sealed job/hash/permission/scope references outside
the canary; valid out-of-index document observations need not be canary
members. Each observation binds to its own authorized selector, source,
lineage and revision, not a guessed single selector for a multi-source request.
Original intent, claim ceiling, scope, and exact-output grammar stay bound.
Field-focused graph evidence retains supporting text beyond a 400-character
preamble with its source/citation group; citations alone cannot satisfy a
business field or upgrade missing-field/coverage metadata.
Source-start attachment projection likewise retains the full validated native
paragraph within the existing shared `16 KiB` budget, not an arbitrary leading
preview; provenance groups remain intact and cap-induced incompleteness explicit.
Validated `request_contract.requested_fields` express business-semantic evidence
needs for text as well as tables; they need not be literal source-column labels.
Explicit structured projections still bind to the authorized source schema.
Requested outputs are not conjunctive source-text predicates unless the original
request explicitly requires that literal content/value. Neither this distinction
nor fuller context changes first-valid-term freezing or automatic recheck eligibility.
**Optional field-query hints — 待測.** Graph `query_effective_graph_view`
accepts optional sibling `field_query_hints: [{field_index, text}]` only for
`evidence_lookup` with nonempty validated required terms/current requested fields.
At most 8 entries, exactly those keys: non-boolean integer current-field index,
1–80-character text. Normalize/deduplicate; reject invalid shape/safety/binding.
Fresh UNVERIFIED field-label/translation candidates affect only bounded soft
candidate preferences. Single-token behavior is unchanged. Multi-token lookup
first forms the same at-most-256 candidates through the existing hash-ordered
merge, then may rerank only that set: token coverage first, field-token overlap
second, original rank/hash for ties. Zero-overlap candidates remain eligible.
Indexed scoring uses only the original remaining deadline; interruption keeps
the complete original ordering, never partial scores. No extra source reads or
changes to downstream literal required-AND matching are permitted.
Exclude mail-tool, table/exact-inventory/exact-field and cursor requests. Drop whole
mixed ID/literal/value/number/date/assignment/assertion/comparison/instruction/
presentation candidates, never salvage substrings. Bare labels may be indistinguishable
from answer values: semantic purity/synonym equivalence is not guaranteed. Hints
prove no native binding, field support or canonical fact. Keep the five required contract keys (native extension below is optional),
IDs, literal AND, authorized scope, first-valid fields/terms, ALL-fields recheck
eligibility and all budgets unchanged. Retained-context rules stay unchanged:
no hint persistence/inheritance. Fingerprint accepted hints; hint-only differences
are neither progress nor requery permission. Scoped review is not deployment or
recall proof; browser and full-release acceptance remain open.

Repeated, reordered, or subset citations and rewritten prose are not new
evidence. Additional contract-bound, validated field support may count as
progress even when corpus coverage remains incomplete; operational errors or
denials do not. With no new evidence or verified field support, stop the repeated
lookup without discarding usable prior evidence. Existing bounded validation
repair remains distinct from evidence progress (2026-10-12, **待測**).
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

**Trusted provider-error presentation — 待測.**
A validated provider error envelope/event classified by the existing transport as
`reason_code=provider_error` is an upstream failure even when HTTP status is200.
Use the existing `provider_unavailable` stop/presentation class, preserving safe
reason, status and error-code diagnostics. Do not describe that event as local
JSON parsing or final-decision validation failure, or as missing source evidence.
Do not infer this class from raw error prose, answer text, or HTTP200 alone.
Malformed event/JSON/shape errors and genuine decision-validation failures keep
their original distinct handling; incomplete terminal responses keep their message.
No retry, attempt/read/time budget, provider transport or source behavior changes.
This is truthful classification/presentation only: upstream cause and availability
remain unproved. Synthetic checks do not prove browser repair or authorize rollout.

**Explicit indexed/source pairing — diagnostic integration / 待測 (2026-10-17).**
The existing indexed-serving loader may accept paired operator-only original
preparation directory and byte-SHA options. Load the indexed revision normally,
then independently validate the original source preparation with existing seals,
ordered job/store authorities, source/access bindings, exact/parent/exclusion and
lookup guards. Require matching preparation fingerprint and full snapshot/bindings;
never infer a neighboring preparation or substitute the indexed revision SHA.
Retain both validated pins in execution identity. A scan-only independent reader
serves the existing eligible recheck and later projection-reopen fallback; ordinary
indexed keyed reads and graph/session objects remain unchanged. Initial indexed
DB/load errors still fail closed; source-only startup remains a separately pinned
route, not a blanket catch. No copied truth store, inline rebuild, ranking change,
canonical write or expanded budget is introduced. Full-scale startup cost, actual
indexed/source parity and browser acceptance remain unproved; synthetic verification
cannot establish them. Both snapshots are independently validated before sharing
retained references; peak startup memory/IO is not yet measured.

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
replace it except for the **2026-10-26 user-authorized split-only refinement**:
after the first frozen lookup returns zero citations and bound source recovery
has no non-null recheck variant or explicit differing term fingerprints, with
query budget remaining, the server may offer one next-proposal refinement.
Each new term must remain a normalized contiguous span of the original request.
Each frozen term must be exactly reconstructed from an ordered subset of new
terms, skipping only original whitespace/Unicode punctuation between pieces;
every new term must participate in a reconstruction. No added, dropped,
substituted or rewritten content is allowed. Newly split pieces must have at
least two characters; unchanged short terms retain their existing rules.
Frozen terms identified by protected identifiers, server-validated retained
identity, or the shared complete-term reviewed-identity matcher remain intact.
No name list or guessed identity classification is added. Unknown unreviewed
names cannot be guaranteed indivisible: the fixed model instruction says to
preserve person, company and product names whole, but formal split equivalence
does not establish those roles. Splitting changes the contiguous-term condition
to same-item AND and may admit unrelated candidates; citation validation remains
mandatory and is not a guarantee of semantic correctness. All other scope,
permission, contract and identity checks remain in force. The opportunity is
consumed by the next proposal even if invalid; accepted terms are re-frozen,
no second split is allowed, and a second exhausted zero-result lookup stops.
This exception does not apply to cited, comparison, exact/native structured,
operational-error or exhausted-budget paths. The retained-reference exception is the unique server-validated
cited protected identifier above, with explicit current/source-turn provenance;
all other terms still require current-request grounding. The same AND predicate applies to initial cited observations and
the same-scope source recheck. These terms constrain relevance, not
authorization; no name list, alias, or smoke-specific rule is permitted.
This does not require every graph relation/summary plan to use same-item AND
or provide terms for this recovery route. Generic source-family-only term
rejection remains mail-only, not graph/document. Without explicit grounded
terms, legacy mail calls retain all-lexical-term matching; standalone document
lookup retains protected-identifier checks plus lexical token intersection,
not full-natural-language-query subset matching.

**Private server-bound term placement — R47 diagnostic deployed / 待測, not general source-fix acceptance.**
[Frozen impl-r3 peer](.formowl/uat-weekend-20261016/ops/reviewer-anscombe-term-placement-r41-r3-safe.json) and R47 integration bind this narrow exception to flat same-item AND.
[Occurrence4 limited browser/source proof](.formowl/uat-weekend-20261016/ops/browser-occurrence-r47-manual-review-safe.json) does not prove general recall or completeness;
strict legacy matching remains the default. Only the immutable original user prompt
and authorized server scope may derive one closed positive mail qualifier plus at
least one child-required term. No provider-expanded query, optional hint, alias,
identifier shape or public wire parameter grants placement authority.
All original grounded terms remain mandatory: **full AND over one guarded plain
own-job body + outer-header pair**, never sibling union or parent-only target support.
Child predicates stay on child body, not copied headers. Occurrence-context mode
may match that body OR the separately cited outer subject/sent_at fields, each
field independently; it is not semantic relatedness or full-thread coverage.
Explicit subject-contains and subject-equals use only verified outer subject and
remain distinct from context mode. Explicit body/literal intent overrides borrowing;
ambiguous/mixed/negative qualifiers do not enable this exception.
Derive the obligation before candidate terms, validate complete terms/roles/scope,
then freeze them atomically on the first valid proposal. Missing/split qualifiers,
mutation or omission after freeze cannot remove the obligation. Missing trusted
roles retain legacy semantics; an invalid/mismatched active binding fails, not downgrades.
Carry private immutable original-hash/contract/actor/workspace binding across the
existing worker/TestClient path and clear request/callback scope in finally; no
public schema/header, new planner/store, provider call or permission bypass.
Only child terms accelerate the existing shortlist; this changes discovery order,
not full-AND admission. Postvalidate all contextual predicates against the already
read guarded full-key pair on initial, recheck and cached paths; no extra reads.
Admit only the whole separately cited group within existing caps; unavailable,
redacted, late or unbound required surfaces cannot establish success. Attachments,
cross-run/custom/dependent paths, exact/native and documents are unsupported;
unqualified graph/retained/no-tool evidence cannot bypass an active obligation.
Source500ms/8192, shortlist256, presentation16KiB/128, deadlines, permissions,
seals/lineage and full fatal drain stay unchanged. No recall/latency guarantee,
known-target recovery claim, document-title inference or silent required-term removal.
The implementation remains five existing owners/two existing tests; scoped frozen review,
R47 integration and the finite occurrence4 proof do not establish full-source or release acceptance.

**Optional native attachment-page obligation — deployed since R50, retained in R52 / 待測, not native-answer acceptance.**
[Native r2 peer](.formowl/uat-weekend-20261016/ops/reviewer-anscombe-native-page-r43-r2-safe.json) is scoped code/test review; [R50 cutover](.formowl/uat-weekend-20261016/ops/cutover-code-r50-result-safe.json) establishes deployment, not source acceptance.
Keep the original five required request-contract keys. The sixth allowed property is
optional `native_locator`: exactly `{kind, page}`, `kind=attachment_page`, strict integer
`page>=1` (not boolean), both required inside the object, no unknown keys.
Only a grounded original current-request coordinate and existing source target with
trusted server capability authorize it; literal “page N” content predicates remain AND,
not removable locator noise. Freeze original terms/fields/locator together; no new planner,
store, public source authority, implicit capability or relaxation of exact/legacy guards.
The fresh obligation needs a current, qualified child for the requested page, including
source-title-only requests without a protected ID. Wrong/missing page, parent-only,
stale or unqualified retained evidence cannot satisfy it, including a no-tool final;
outer headers supply metadata only. Keep original target and same-source/native guards.
Ordinary chat and existing closed transforms of genuinely present/citeable prior evidence
retain their original paths. Historical R48 integration failed2 obsolete schema assertions; the
[16PASS schema2 correction](.formowl/uat-weekend-20261016/worker-anscombe-native-schema-fixtures-r49/handoff.safe.json) is test-only. [R50 362PASS integration](.formowl/uat-weekend-20261016/ops/integration-code-r50-safe.json) includes the reviewed native candidate.
The historical first live native-page fields case failed before MCP with provider HTTP400.
The [R51 descriptor repair](.formowl/uat-weekend-20261016/worker-nash-native-descriptor-r51/handoff.safe.json) is now live.
Same-route synthetic schema-only preflight: [old HTTP400](.formowl/uat-weekend-20261016/worker-nash-native-descriptor-r51/master-preflight/old-safe.json) / [new completed](.formowl/uat-weekend-20261016/worker-nash-native-descriptor-r51/master-preflight/new-safe.json), two calls/no MCP/source/retry; strict mode and server guards unchanged.
[R51 manual/source review](.formowl/uat-weekend-20261016/ops/browser-fields-r51-manual-review-safe.json) confirms C601 scalar/page recovery, but its original compound-price-unit rubric remains FAIL.
Neither schema completion nor a correct scalar establishes native table/unit semantics or full native-answer acceptance; all limits unchanged.

**Finite representative selection / per-selected-output scope — r4 deployed since R50, retained in R52 / 待測.**
One explicit positive bounded source selection can bind compatible local per-selected-record
metadata output; that output does not by itself request an all-source inventory.
Fresh selection still requires governed evidence, not supplied-only chat or a
no-tool permission state; a stable offered catalog alone does not satisfy it.
Preserve original prompt/hash, targets, literal/source/date predicates, requested fields,
first-valid binding and existing caps. Independent all/count/absence operations remain exact;
negated, quoted, mixed-target or ambiguous selection/anaphora receives no exemption.
Do not early-return ordinary lookup merely on an example word or number, infer sample size
from dates/properties, add aliases/answer dictionaries, or claim representativeness/completeness
from top-k. Missing requested examples/fields remain disclosed; no citation padding.
[r1 synthetic61PASS](.formowl/uat-weekend-20261016/worker-nash-bounded-examples-r50/impl-r1/handoff.safe.json) never closed its original-class failure;
[r1 B01 BLOCK](.formowl/uat-weekend-20261016/ops/reviewer-anscombe-bounded-examples-r50-r1-safe.json) and [r3 B02 BLOCK](.formowl/uat-weekend-20261016/ops/reviewer-anscombe-bounded-examples-r50-r3-safe.json) remain immutable.
[r4 scoped AGREE](.formowl/uat-weekend-20261016/ops/reviewer-anscombe-bounded-examples-r50-r4-safe.json) / [exact r4 offline original-class PASS](.formowl/uat-weekend-20261016/ops/preflight-r50-r4-frozen-routing-safe.json) and R50 integration/cutover establish the deployed revision, not universal grammar or business correctness.
The retained-two run records four IDs held on an MCP0 transform; [later manual/source review](.formowl/uat-weekend-20261016/ops/browser-retained-four-r50-manual-review-safe.json) is 2LIMITED_PASS with source bindings preserved, not whole-source or release acceptance.

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
  A trusted `evidence_lookup` source-start caller may opt into fixed, non-refilling
  batches of at most three shortlist anchor hydrations through the existing
  concrete file-backed Observation reader (**待測**). The default, exact/native,
  small-cap and custom-store paths remain serial. The coordinator retains helper,
  scope, parent and callback checks; rank order is unchanged except for the
  ready-pair mail window below. Reserve up to two dependency reads per outstanding
  mail anchor within the same read cap. Charge every submitted
  anchor without refund, including a worker that declines an expired start.
  Each worker checks the original absolute deadline immediately before its guarded
  read. After stop/expiry/error, issue no further reads or callbacks and join all
  started work before returning; inspect unused-tail failures and fail closed.
  Draining an already-started blocking read may overrun the phase wall time and
  leave later families incomplete. This is neither cancellation nor a hard elapsed-
  time guarantee, serial error/read-count equivalence, a new budget, or proof of
  retrieval improvement. No public/provider concurrency control is exposed.
  **Ready-parent fixed-window scheduling — deployed since R36, retained in R52 / 待測, not accepted:**
  R36 replaces only the all-anchor progress barrier below, not final settlement
  or error draining; deployment does not establish business acceptance.
  For the existing trusted evidence-lookup and concrete original read-only file-store
  opt-in only, preserve the fixed three-anchor window, same max-three pool, original
  absolute family deadline and >=9 remaining-read reservation. Within that window,
  a completed eligible plain mail body may plan and submit its own authorized parent
  before unrelated anchors settle; held serial-only siblings wait. Independent jobs
  may share a window, never a parent authority. Use full job/run/asset/scope/
  occurrence + parent ID/hash identity for guarded reuse/dedup. Submit at most three
  parents, charge each submission without refund, and admit validated ready pairs on
  the coordinator with own-parent-before-child. Original rank breaks ties only among
  currently ready pairs: global ranked admission within a window is deliberately relaxed.
  Before planning/submission and each callback, inspect completed anchor AND parent
  errors and deadline/stop; reuse full-key pending parent reads without duplicate charges.
  All submitted anchor/parent work must settle, inspect completed errors, and drain
  fatally before returning or refilling the next window; no callback after stop,
  expiry or error. Defer serial-only siblings until all anchors settle and eligible
  dependencies finish; process them in original relative order. No next-window refill before this drain.
  Attachment, explicit/crossrun-linked (including body-shaped linkage),
  missing-helper, custom-store, exact/native, small-cap and nonshortlist routes retain
  original guards/serial behavior; no source/ranking/hints/loader/budget change.
  Unused-tail failures remain fatal even after staged callbacks; arbitrary external
  callback rollback is not promised. Caps remain 500ms phase/8192 reads/16KiB,
  with reservation 3+U+2*(3-E)<=9 for E eligible anchors and U<=E unique parents.
  Slow anchors and mandatory draining can still exceed phase elapsed time or consume
  later-family opportunity. No hard timeout/cancellation, real speedup, recall,
  full-top-k, exact count, business acceptance, or release claim. This is a
  diagnostically deployed ordering contract, not full-browser or release acceptance.
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
  Mail/document `indexed_shortlist_miss` and native-table `source_table_shortlist`
  must retain their distinct stop metadata through the same validated terminal
  decision. The r4 diagnostic package includes this native-table terminal handling;
  an enum alone cannot bypass attempted/binding/scope/exact/error guards.
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

The bounded diagnostic producer uses a trusted frozen manifest and explicit
operator attestation, read-only verification of the complete immutable code
inventory and runtime identity, and image/settings/source-revision bindings.
Operator-attested image identity is not remote attestation. Source identity
comes from the validated ingestion revision, not arbitrary caller hashes or a
plain JSON assertion. This is bounded diagnostic binding, not formal readiness
or live deployment acceptance; external mount checks alone cannot repair an
unbound response.

Observed r11 diagnostic defect: the recorder retained only the latest three
attempt records although the existing turn budget permits six. Requiring a
complete history therefore made otherwise valid four-to-six-attempt turns
incomparable. This three-record truncation is not the desired contract. B's
frozen repair derives the diagnostic-retention constant from the unchanged
six-request cap; all other product AST is unchanged. Canonical local19/19,
zero failures/errors/skips,0.818s/Ruff verifies four/six-attempt positives and
missing-history negatives. The prior r12 included this repair; final canonical focused
117/117 passed,174.049s,EXIT0, zero failures/errors/skips, exact252 code/34 tests
verified pre/post and rechecked. Hypatia/Archimedes/Lagrange scoped AGREE3/3. It changes
no execution budget/model/deadline or retry allowance, and genuinely missing/
truncated identity stays incomparable. Candidate and live r12 each retain four
comparable trusted-bound responses; this diagnostic identity proof does not
resolve the first live source-reopen failure recorded alongside later native
proof in §14.

If any required binding or field is missing, mismatched, or truncated (including
provider-attempt history), classify the artifact as
`diagnostic_only/incomparable`; it must not support a loaded-code mismatch,
no-data, provider-success, root-cause, or UAT-acceptance claim. Public payloads
and stderr must not output raw queries, source payloads, headers, or secrets.

This **ANY required diagnostic identity metadata missing → incomparable**
predicate is separate from **ALL requested business fields missing → source
recheck**; the business-field rule does not relax metadata safety.

`repair_recovered` may be comparable only with complete validated attempt history,
latest completed outcome and provider response, and latest sanitized passed
finalization with `repair_attempted=true`. All deployment/code/build/source,
HTTP and MCP error/timeout checks remain mandatory. Missing, malformed, truncated,
over-cap or latest-failed records remain incomparable. Local15/15 comparator
verification and subsequent frozen integration are scoped evidence below.

**Typed evidence notes — v2 candidate / 待測 (2026-10-17).** The bounded
Responses UAT path explicitly opts into server-owned `typed_evidence_notes_v2`;
the reusable model defaults off and the app-server path remains legacy. Bind the
policy version and enabled state to execution/config identity, separately from
requested model identity. After current or eligible retained governed evidence
is presented, enabled decisions use the existing six keys plus `field_limitations`.
Each of at most eight entries has exactly `{field_index, reason, scope}`: a unique
strict integer (not boolean) index into the current frozen requested-field catalog,
a closed `not_established`, `ambiguous`, or `conflicting` reason, and an explicit scope:

- `presented_evidence`: model-assessed uncertainty within the presented evidence.
  All three reasons remain valid regardless of retrieval completeness; render this
  scope explicitly and preserve genuine ambiguity/conflict, not a coverage-only warning.
- `unverified_requested_remainder`: only `not_established`, and only when current
  presented governed metadata positively establishes incomplete coverage. Describe
  the unresolved requested remainder without denying a supported cited subset or
  asserting that additional records exist. Unknown coverage, missing structured
  support, retained evidence alone, model prose and citation presence do not grant
  this scope. Never infer a missing scope or reclassify a supplied discriminator.

Reject missing/extra keys, invalid or stale indices, duplicates, unknown reasons
and unsupported scope/reason combinations. The provider must leave `coverage_note`
empty; activation remains strict through finalization and the existing single
repair, with fail-closed exhaustion and no legacy downgrade or new allowance.
The renderer consumes the typed field before public projection and fills the
existing string note. Any field limitation requires an incomplete outcome.
Retrieval disclosure uses validated presented coverage/truncation/stop metadata:
authoritative incomplete/unknown envelope signals precede nested completeness.
Include presented retained evidence in that disclosure only when the final answer
cites it; unused prior evidence must not downgrade clean current evidence. Retained
evidence never supplies the current field catalog. Retained-only evidence without a
current validated catalog requires empty limitations and generic overall uncertainty;
clarification and exact/empty-field catalogs also retain empty limitations.
Missing structured support attestation is a metadata limitation, not absent facts;
omitted field indices prove no support. Do not invent page/row/clip inventories from
source text or treat incomplete retrieval alone as factual uncertainty. Ordinary
uncited chat, source-backed blanks, citation/exact/source guards, ALL-fields recheck
eligibility and every request/read/time cap stay unchanged. This constrains the note
channel, not arbitrary `answer_text` grounding or whole-source completeness.
Historical v1 evidence remains in immutable preimages; v2 candidate verification
is not deployment, browser acceptance or methodology readiness.

**Explicit unsupported exact-capability terminal — deployed since R39, retained in R55 / 待測.** Only after
an existing validated `exact_set_or_inventory` request returns a clean citation-free
governed result may trusted `query_contract.complete_inventory_supported is False`
permit the existing guarded capability notice and stop before another plan or
finalization. Incomplete coverage alone, missing/unknown/true/nonboolean capability,
or zero citations alone cannot authorize this new terminal. Preserve original
request/query hashes and authorized scope, no pending comparison, and all
current-result/error exclusions. An unrelated retained citeable catalog does not
veto this terminal for the newly validated current exact request when the trusted
capability is explicitly False and the clean citation-free result/binding guards
pass. Use the existing capability notice without retained citation IDs; do not
clear or mutate retained conversation state. Current cited/native/exact results
and prior-only transforms retain their original paths. Native exact success
continues normal validation; a failed proposal is never reinterpreted as capability.
Invalid arguments, permission/provider/schema errors, ambiguity, binding mismatch
or missing-binding warnings retain precedence. Preserve any earlier rejection
trace and charged attempt when a later valid call reaches this terminal. The
operation-neutral notice cannot certify a complete authorized-scope set/count,
estimate totals from top-k, or establish absence. Public shape, read/retry/time
caps, ordinary-chat MCP0 and the existing nonterminal no-progress path stay intact.
**Current R55 / ledger536 checkpoint** — 2026-10-17 UTC / 待測
[R55 cutover](.formowl/uat-weekend-20261016/ops/cutover-code-r55-result-safe.json) EXIT0/2026-10-17 20:01:55Z, **live8088**, code `d580faeab634…`; **R54 retained rollback**, no cleanup. Deployment authority is the exact frozen [package-r55](.formowl/uat-weekend-20261016/package-r55.json)/code-r55/tests-r55 inventory, not dirty root product files; this docs slice does not synchronize root code. [Final read-only state](.formowl/uat-weekend-20261016/ops/provider-session-r55-final-state.safe.json) confirms exact252code/93tests, pinned image running and8088 HTTP200/statusok/query service connected; health is not release acceptance.
[Canonical focused91PASS](.formowl/uat-weekend-20261016/ops/provider-session-r55-differential.safe.json) is bounded proof. [Broader integration](.formowl/uat-weekend-20261016/ops/integration-code-r55-safe.json) =**283 tests /22FAIL+1ERROR /13.005s, NON-GREEN**; all23 inherited assertion tails match R54, no new/resolved failures, Ruff0/compile0/exact252+93. Neither focused green nor inherited failure identity is whole-suite or release acceptance.
[Dated R54 manual review](.formowl/uat-weekend-20261016/ops/provider-session-r54-manual-review.safe.json) =**7 functional LIMITED_PASS +1FAIL (C663)**, four lifecycle checks, source verifier EXIT0 and all9 sent provider requests wire-contract valid. [Formal ledger527](.formowl/uat-weekend-20261016/ops/provider-session-r54-ledger.safe.json) =519+8 submissions, not passes; C663's original pre-provider clarification failure remains immutable.
[Final R55 manual review](.formowl/uat-weekend-20261016/ops/provider-session-r55-manual-review.safe.json) records **9 browser questions LIMITED_PASS +4 lifecycle PASS**, finite batch only. [Wire verifier](.formowl/uat-weekend-20261016/ops/provider-session-r55-wire.safe.json) EXIT0: all11 sent requests/9 cases contract-valid, `failure_findings=[]`. [Formal ledger536](.formowl/uat-weekend-20261016/ops/provider-session-r55-ledger.safe.json) =527+9 submissions, **not passes**, no automatic retries. Whole-UAT/release/methodology acceptance remains false; original R54 C663 FAIL is not regraded.
[Fresh source verifier](.formowl/uat-weekend-20261016/ops/provider-session-r55-source.safe.json) EXIT0 plus the later manual/native review establish all5 citation occurrences/3 unique citations resolve and match. Four requested capacitor values and origin field have same-target/header support; manufacturing location remains unverified. This proves only the returned finite evidence, not full-source coverage, cache-hit rate or upstream routing effectiveness.
[R55 frozen grammar correction](.formowl/uat-weekend-20261016/worker-anscombe-supplied-negative-r55/handoff.safe.json) changes only shared closed supplied-text recognition: whole exterior negative-source constraints plus explicit quoted input, not a no-source override for mixed lookup. Same final tests RED12 subcases→6PASS, related69PASS, [scoped peer AGREE](.formowl/uat-weekend-20261016/ops/reviewer-nash-supplied-negative-r55-safe.json); original/earlier failures remain preserved. C600 FAIL/unrerun and C601 compound-price-unit FAIL remain open; R52 C628/C651 observations prove only the exact-capability boundary, not full-source absence.
[Six provider-request requirements](SPEC.md) §3.2 are inherited byte-identically from R54: stable server conversation UUID/header/cache key, fixed instructions/tool order, append-only provider input with dynamic tail, honest UA `uat-web-backend/0.1.0` matching application version, unchanged model/stream/store and current authority guards. Smaller eight-message routing history is separate. Cap/expiry stop safely without silent ID rotation; no cross-restart durability or nonblocking OAuth-reset claim. Public hosted terminology stays paused pending an explicit exception.
PDF/parser/topology work remains **paused**; [native-PDF review](.formowl/uat-weekend-20261016/ops/native-pdf-r53-master-review-safe.json) is not a proven compound-unit fix. [Last lineage receipt](.formowl/uat-weekend-20261016/ops/hybrid-current-r1/lineage-progress-safe.json) is not full index/embedding/activation; no new source/index operation or completion forecast here.
[Fresh canonical authority](.formowl/uat-weekend-20261016/ops/authority-r55-final-tmpfs-container.json) EXIT0 with existing tmpfs config: valid=true/ready=false/errors=[], CJKtrue, execution `0eaba758e881…`. [Initial read-only/no-tmpfs probe](.formowl/uat-weekend-20261016/ops/authority-r55-final-container.json) EXIT2 remains preserved; no product change or gate promotion. Four methodology gates and independent three-reviewer release gate remain open; feature待測/step4 in-progress. Source500ms/caps/guards and requested models unchanged; actual model/effort unverified, 3s unanswered.
[New lossless five-file preimages](docs/archive/2026-10-18/weekend-r55-provider-status-preedit/SHA256SUMS.json) preserve every replaced checkpoint, prior failure and archive link. No prior archive edit, checkbox promotion, root product edit or mirror update.

**Private actual-browser source-phase trace — R33 native aggregates diagnostic deployed / 待測, not accepted (2026-10-17).**
Only paired `--behavior-log` + `--record-raw-uat-interactions` enable this private diagnostic;
no new provider/public control. Four existing owners: `python/formowl_retrieval/gateway.py`,
`python/formowl_gateway/issue56_uat_runtime.py`, `python/formowl_mail/issue56_sealed_source.py`,
and `python/formowl_gateway/issue56_sealed_source_loader.py`; no new module/logger/store owner.
The request/call/query/source/code-bound scope crosses the original Thread/TestClient handoff.
Coordinator allocation is capped at **256 combined detail cells, including at most the first64 read attempts**,
plus at most **256 shortlist hashes TOTAL per MCP**; fixed-key counters survive detail exhaustion.
Dropped/truncated/unobserved data stays explicit UNKNOWN; a prefix fingerprint is not full-order proof.
Workers update only their own coordinator-allocated cell; role is assigned at dispatch, not inferred from helper name.
Observe existing lookup/helper/barrier/parent-wait/serial-sibling/project/admit/defer/envelope decisions without repeating predicates.
Read attempts, callbacks, projection, admission and publication are distinct; callback true does not mean admission.
Native/exact/context-neighbor per-read timing remains **UNKNOWN**, with aggregate boundaries only.
Native evidence-fallback planning adds only to the existing engine cell in
`python/formowl_gateway/issue56_sealed_source_loader.py`: the fixed12 numeric fields
`native_{terms,values,rows}_{attempted,completed,wall_ms,cpu_ms}`. Terms covers existing
term/tokenizer/hash-set planning; values/rows accumulate the original shard-reader calls.
Candidate filtering, hydration/callback and other residual work are outside these timings.
Completed means normal call return, including absent shards or bounded overflow, NOT a
match, physical read, admission or completeness proof; opened shards retain full seals.
Attempted minus completed distinguishes interruption; timing finalizes even on deadline stop.
Optional `native_phase_failed=1` invalidates stage measurements after an observer fault.
The request-local dictionary exists only with an allocated engine cell; default-None exact
callers and disabled tracing collect nothing. No new detail cells, per-line/per-file events,
reads/hashes, logger, locks or upward imports; underlying shard-reader behavior is unchanged.
Fatal paths without original engine finalization remain UNKNOWN. Source500ms/8192, family
allocation, guards, scheduling, error/drain and timeout-without-snapshot semantics stay intact.
After the original full drain, only the request worker creates the immutable queued snapshot;
**runtime timeout publishes incomplete metadata without reading mutable cells**. Late work cannot mutate a logged or later turn.
Bounded identity hashes/serialization use existing metadata after drain, never source-body rehash/read or SQL/Path/store wrapping;
no hot-path logging I/O/locks. Diagnostic-only faults cannot swallow original errors or replace original results.
Disabled tracing allocates no collector/cells or diagnostic clocks. Private behavior output only, no public/provider/MCP payload change.
Private numeric count names (`required_term_count`, `preferred_term_count` in frozen R31) and every emitted trace field
MUST pass the existing recursive whole-record writer guard; numeric values do not exempt unsafe field names.
Verify source-start → `_call` → real `_append_behavior_log`, including unsafe prompt/key fallback and timeout/fault markers;
snapshot JSON or public-safe projection alone is insufficient. No guard/logger bypass, allowlist exception or safety weakening.
R24's three redacted business records lost their calls/phase cells; later synthetic success cannot restore them or prove historical timing.
Guards, eligibility, scheduling/order, ranking/hints, charged reads, budgets and fatal-tail draining remain unchanged.
Observer overhead is **unmeasured** and may perturb deadlines; intervals overlap and trace completion is not source completeness.
Future actual-browser evidence requires separate frozen deployment/authorization and explains only that call, not historical failures.
No warmup/replay, semantic repair, recall/performance/business/release claim. [Frozen proposal](.formowl/uat-weekend-20261016/worker-anscombe-phase-trace-r24/SPEC-proposal.md) records the original contract; R33 activation does not establish business, performance or whole-browser acceptance.

**Opt-in private UAT interaction recorder — diagnostic-only / 待測 (2026-10-13)**

Explicitly authorized temporary LAN UAT may pair `--behavior-log` with
`--record-raw-uat-interactions`. Only that private operator file may retain the
raw prompt, expanded tool query and available visible answer. The file is JSONL,
mode `0600`, on an operator-owned persistent writable mount; it is never served
through the browser, MCP, public diagnostics or stderr. Credentials, headers,
cookies, raw storage paths and hidden-source internals remain excluded. If content
is unsafe to record, the private fallback retains only safe hashes/status metadata
with `content_redacted=true` and `exact_result_preserved=false`; it retains no raw
content. Such a record cannot establish file=HTTP=DOM equality or exact result
preservation. A recording failure still emits only a safe failure event.

Schema v2 uses a unique per-turn `request_id` even for repeated prompts in one
session, correlated with safe provider/turn terminal and MCP traces. It retains
the service-visible status/answer/clarification/citations, actual validated
request contract and query when available, verified field-support hashes and
existing source-recheck/scan-stop metadata. Missing plans or coverage are not
inferred. Runtime exceptions retain a failure fingerprint and available result;
the later HTTP error envelope is not reconstructed by this recorder.
Private per-call diagnostics may also retain the accepted normalized optional
field-query hints as at most eight field-index/text-hash pairs, their count,
fingerprint, and validated MCP-argument presence. Original omitted, empty, and
wholly dropped proposals collapse in the typed request and remain indistinguishable;
no request or legacy missing diagnostic means unavailable, never zero. These
records prove neither actual transport completion nor downstream hint use, field
support, or recall improvement. Raw hint values stay excluded and public safe
trace schemas are unchanged. This observability extension remains 待測.
Private raw-governed, compacted-presented, final-model and final-answer citation
sets preserve hash IDs and hash non-hash identifiers, with count/fingerprint,
encoding and explicit truncation above 100 IDs per set. Stage capture is bounded
by the existing three MCP calls and two finalization validation records.
Recording failure must preserve the business result/original exception and emit
only a safe failure category plus request ID. Retrieval, execution budgets,
models and public diagnostic schemas remain unchanged.

The frozen observability package passed canonical36/36, Ruff/compile4 and observed
candidate/live browser capture. Three scoped reviewers (Chandrasekhar/Gibbs/Harvey)
agreed to logging activation only. At that activation,8088 served `4544e59a…` in
`formowl-uat-observability-live-20261013` (252 files/drift0, same source/image/model/
budgets): private file=HTTP=DOM answer, raw9/presented7/final2 IDs, provider/turn/MCP
correlation, zero recording failures and two private-log URL404 checks.
Repeated-prompt distinct IDs were verified in the earlier candidate, not rerun live.
The old r12 container is stopped/preserved for rollback; candidate cleanup completed
with logs retained. Frozen integration still has one PASS/one pre-service ERROR
in candidate-artifact fingerprint validation; that failure is not
erased by candidate proof or an earlier working-tree fixture pass. The underlying
COO-answer inconsistency is unresolved. Four methodology gates, source guards
and promotion rules remain unchanged; this exception grants no general raw
logging or completion claim. Dated evidence: [handoff](docs/agent-goals/handoff-log.md).

**UAT consistency assessment — IN-PROGRESS / 待測 (2026-10-13)**

The newly authorized bounded repair follows the closed logging slice.
[Baseline](.formowl/uat-stability-20261013/baseline-safe.json) records ten actual
browser turns with file=HTTP=DOM: five cited partial answers, one ordinary chat,
two unexpected clarifications, one honest incomplete unknown lookup and one
provider error; eight turns are comparable. The rephrase exposed `count`
substring matching inside `country`; ordinary-chat routing consulted a lossy
prior-evidence envelope while runtime retained citeability. Controlled synthetic
repros separately demonstrated source-family/selector starvation, read-cap
accounting loss and duplicate parent hydration. These do not prove the
historical 500 ms subcause. Generic repairs retain exact/native execution,
ALL-requested-fields eligibility, source/hash/lineage/permission guards and budgets.

[Frozen r4](.formowl/uat-stability-20261013/package-r4.json), code `dd731bfc…`,
has observed live diagnostic proof. [Verification](.formowl/uat-stability-20261013/r4-verification-safe.json)
records pinned-image153/153 PASS254.897s, integration3/3 PASS110.247s and
lint/compile12 PASS, exact252 code+37 test files with post-run hashes verified.
Native terminal32/32+115subtests PASS27.697s/Ruff and query guard29/29+34subtests
PASS0.184s/Ruff are local evidence. Prior native32tests/3ERROR28.468s was an invalid
negative table-query fixture; that failure remains preserved without an inferred
pass count. R3's150 focused+3integration passes preceded browser8/6pass, one
MCPContractValidationError and dependent missing-reference clarification; the
failed private record was absent. Its actual expanded query/root remains unproved.
A controlled shared unsafe-expansion repro (3tests/3failing subcases/2errors)
justifies the pre-MCP guard and safe logging fallback, not historical attribution.

R4 initial candidate8 turns:7comparable/correct, one provider HTTP502 at
connect_headers after valid cited MCP (1.044s). A predeclared separate fresh-chat
and delivery recheck passed2/2; the original failed/incomparable turn is retained.
All10 candidate records have unique IDs and exact log/HTTP/DOM correspondence;
neither unsafe-query guard nor redacted fallback triggered live, so those paths
have synthetic proof only. Citations match prior same-source proof; no fresh
native reopening occurred. Budgets, remote/global guards and source checks remain.
Nash engineering, Bacon safety and Linnaeus methodology all AGREE on the same r4
fingerprint for bounded diagnostic deployment. The rollout gate preserves the
original candidate failure. [Live readiness](.formowl/uat-stability-20261013/live-r4-ready-safe.json)
at15:04:37Z confirms8088 serves `formowl-uat-stability-live-r4-20261013`,dd731bfc…,
252files/drift0, same image/source/settings/budgets, logs0600/dir0700. The old
observability container is stopped/preserved for rollback.

[Live matrix](.formowl/uat-stability-20261013/live-r4-safe.json) and verifier EXIT0:
14/14 known checks PASS, all14 log=HTTP=DOM text/citations. Eight cited partial
answers, four ordinary-chat turns with MCP0, one honest incomplete unknown lookup
(provider1/MCP1), and one reset missing-reference clarification (no provider/MCP).
Thirteen provider turns are comparable; the reset clarification is local,
identity-exempt and not a comparable provider turn. Repeated/fresh/rephrased
identifier answers retain the same origin citation; manufacturer evidence is same-row,
unrelated-part origin/manufacturer and PO delivery retain known citations/date. Master
reviewed manufacturer/delivery screenshots. PO page1/3 remains partial requested
delivery evidence, not shipment or latest commitment. Reload preserves transcript;
reset clears server state and postreset chat uses MCP0. No fresh native reopening;
source pin is unchanged and citation content relies on prior same-source proof.
This proves only the observed known regression path. [Cleanup15:11:45Z](.formowl/uat-stability-20261013/final-operational-r4-safe.json):
8088 healthy/r4 exact252/drift0/restart0/OOMfalse; four own candidates removed,
all logs/old observability rollback retained; source/index/DB/unrelated containers
untouched. Fourteen private IDs/records, zero recording failures/redacted/unsafe-query
events; private URLs404 twice, file0600/dir0700. R3 incident, provider502,
historical source/artifact anomalies and upstream causes remain OPEN. No whole-UAT,
provider-stability, standard or methodology promotion; four gates blocked,
step4 in-progress, requested sol/high actual metadata unverified. Exact failures,
counts and next action: [handoff](docs/agent-goals/handoff-log.md). The unchanged
[pre-edit archive](docs/archive/2026-10-13/uat-stability-r3-pre-verification/SNAPSHOT.md)
preserves earlier r1/r2 results, tooling differences, contracts and review history.

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

Projection-independent identifier/field execution (2026-10-12, **待測**) uses
the existing sealed native-cell reader and deterministic executor. Automatic
binding requires applicable source-provided requested-field schema; an unrelated
table schema must not divert ordinary evidence lookup. Preserve all validated
content constraints on the same row, not just the identifier. Explicit invalid
or ambiguous table plans still clarify. When every requested field lacks verified
support, an eligible automatic exact miss may continue through the existing
same-scope source reader using the original remaining deadline/read/evidence/
context budgets; partial support and source-backed blanks do not trigger recheck.
Native date/display/formula/merged-header limitations remain explicit. A bounded
exact shortlist never certifies complete inventory or source absence.

Reviewed header validation (2026-10-23, **待實作／待測**) is the only path by
which an inferred spreadsheet/attachment header (`candidate_only`) may become
applicable requested-field schema. It is generic over every admitted table; it
never targets a question, field name, identifier or UAT case.

1. Proposal: an offline, resumable, bounded batch reads each candidate header
   region (header path plus a bounded sample of its own data rows) and proposes,
   per column, `header_confirmed`, `not_header` or `ambiguous`. Proposers may be
   deterministic structural checks or an LLM; output is a candidate only and is
   bound to source content hash, sheet/table fingerprint, header row index,
   column hash and the native header text. Proposals never rename, translate,
   alias or merge labels; the native label stays the field identity.
2. Review: a sealed review receipt (same contract shape as reviewed UAT
   annotations: sealed configuration plus receipt SHA-256, approver identity,
   decision and a versioned acceptance policy) approves or rejects proposals.
   Approval is never inferred at query time and never comes from the answer model.
3. Effect: an approved column is exposed as `reviewed_header`, distinct from
   `source_provided`, with its receipt fingerprint. Automatic binding and
   deterministic same-row lookup may use `source_provided` or `reviewed_header`
   columns; answers disclose reviewed-header provenance. Requested-field matching
   remains normalized native-label equality.
4. Limits: `ambiguous`, duplicate or redacted labels, unresolved merged/multi-level
   paths, and source revisions that change the bound hash remain `candidate_only`.
   Header validation does not certify row, table, workbook or source completeness;
   exact set/count/inventory/negative claims keep every existing completeness rule.

Projection-independent mail-occurrence execution (2026-10-16, **待測**) is a
primary exact route, not an exception to the automatic recheck exclusion. A
validated mail-only exact request with one unambiguous native protected identifier
may reuse the authorized source reader and existing direct-identifier occurrence
provider/executor without a retrieval projection. Keep all validated required
terms as AND constraints; no prefix stripping, numeric substring identity,
class downgrade, new index, or inline rebuild. The same inherited 500ms/8192-read,
request evidence cap (at most128), and16KiB evidence budget apply. Query-local
provider scope is always explicitly unresolved: found occurrences do not establish
a complete timeline, total, latest state, or negative. This inventory establishes
which admitted native message occurrences contain the exact identifier, not which
authors made new business assertions or events. Quoted history may establish
textual presence, never a new update or commitment at the enclosing message date.
Evidence labels and retained context explicitly mark authorship and event timing
unverified; requested authored-event fields remain unsupported without their own
source proof. Native outer headers retain separate citations; they describe the
containing message, not the date of an embedded statement. Neighbor-only text
cannot become an identifier hit. Independent documents/attachments are not mail members;
unsupported or ambiguous exact requests remain pending rather than guessed.
Synthetic/focused checks do not establish webpage or release acceptance.

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
The methodology authority and independent three-reviewer gate remain unchanged.

Under the **2026-10-26 user override**, the requested UAT answer model is
`gpt-5.6-luna` with `reasoning_effort=xhigh`, superseding the 2026-10-25
`gpt-5.6-luna/low` request (which superseded the dated 2026-10-15
`gpt-6-luna/high` request). Runtime/provider support, the observed model/effort
binding, and browser acceptance remain pending. Record requested and observed
identities separately; this policy change does not prove support or rollout.
Dated earlier model evidence retains its original identity and claim boundary.
Development worker policy remains `gpt-6.1-sol`/`high`.
Under the same 2026-10-26 user decision, UAT stays xhigh throughout and the
browser acceptance runner's per-turn response wait and CDP command timeout
default to180 seconds, with the corresponding elapsed diagnostic validation
upper bound aligned to180 seconds. Provider240s and turn300s limits remain unchanged; the
existing page fetch has no shorter full-response deadline. This waiting policy
does not establish browser acceptance.

The same authorization permits downtime repair within Master's bounded recovery
assignment. Master records a time-based recovery plan with milestones, time
budgets, evidence checkpoints, and stop conditions in the work board and
handoff. Missing July/newer snapshot mail is an accepted coverage limitation,
not a user-export blocker. Disclose the available time range and unsupported
answers; source/hash/lineage/permission checks and methodology gates still apply.

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

For future product-contract diagnostics, additionally bind the semantic ledger
and annotation profile/coverage; use explicit not-applicable for the control arm.
Graph/ontology arms isolating scoring must share the same annotation artifacts;
do not credit different extraction quality or an extra LLM call to ontology.
These diagnostics do not change frozen arms or permit retroactive comparison.

---

## 9. Provenance, Time, Confidence, and Contradiction

### 9.1 End-to-end lineage

Every result is traceable to its authorized source and executed plan. Direct
source retrieval and source-native structured execution use:

```text
Source / Asset / EvidenceSnapshot
  -> ExtractorRun
  -> Observation
  -> semantic-annotation ledger when ontology-aware
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
semantic_annotation_ledger_id
coverage_fingerprint
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

Object verification binds one complete read to the expected hash and size,
checks opened-descriptor stability and path identity, and re-resolves the
governed locator to reject a changed symlink target. Failure diagnostics record
that same call's safe digest/count/completion/stability facts, not a later
replacement read. A mismatch never changes the expected pin or authorizes
extraction/rebuild. A later passing read does not erase an earlier mismatch or
establish its root cause; the historical large-source inconsistency remains
unresolved until independently explained.

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

### 11.1 Query-independent offline batch indexing — 待測

Preserve raw Assets and the existing Observation owner. The PostgreSQL adapter
in [`python/formowl_ingestion/storage/postgres.py`](python/formowl_ingestion/storage/postgres.py)
already persists unstructured Observation payloads as JSONB; PostgreSQL/pgvector
remains the canonical baseline. The recovered UAT source stores are currently
file-backed, not a proven live PostgreSQL migration. The existing source-native
SQLite accelerator is a rebuildable derived locator/index artifact, not another
truth store or a new MongoDB, Neo4j, or schema service.

Offline batches persist sealed reference keys/ordinals, occurrence and attachment
parent helpers, and document neighbor locators for reuse across unrelated queries.
Bind artifact schema/capabilities, source revision/snapshot/authority, frozen
profile, and artifact hashes; reopen/reuse matching versions without ingestion
or indexing per request. Source, policy, or extractor changes require an explicit
offline job and new version at the applicable extraction/index boundary; user
prompts, KG misses, and retries never trigger ingestion or rebuild.

Offline `index_prepared_references` hydration opt-in (2026-10-17, **待測 / unactivated**): `allow_parallel_file_reads=false` by default.
Only exact-original `CompletedIngestionJobAuthority` and concrete `ObservationStore`/`_JsonRecordStore` read-only getter paths qualify; injected/subclassed/overridden owners remain serial.
Fixed two-reference windows join/drain all submitted futures and inspect every error, including submission/read failures, before metadata handoff or return.
Source order is retained; only the coordinator performs metadata work, writes and checkpoints.
Hydration/metadata errors prevent current-batch writes; earlier commits and existing put-before-checkpoint failure semantics remain unchanged.
Each pair creates its own pool, not one lazy shared pool; cost/benefit is unproved and needs separately authorized measurement before build use.
The original offline callsite is **not yet wired** to opt in; online caps/guards, parent traversal and storage ownership are unchanged.
Independent review is pending; no activation, performance, acceptance or completion claim is made.

With an admitted keyed artifact, eligible mail and independent PlainText/Markdown
lookup uses bounded keyed hydration and at most four context references per side,
not a sealed-reference tail scan or `list.index`. Revalidate selected source/hash,
job/run/revision, permissions, occurrence and native locators through existing
owners. Native row/cell evidence retains its existing sealed exact-cell owner and
same-row provenance; locator metadata does not grant access or prove field schema.
Existing eligibility, exact semantics and shared `500ms`/`8192` observations/
`128` evidence/`16KiB` context caps are unchanged.

Shortlists and misses remain incomplete, never proof of source absence. Coverage
must distinguish unsupported extraction, parse failure, truncation, and missing
projection. Legacy missing metadata is explicitly unavailable, never migrated
inline. Offline clone mode retains verified postings without retokenization and
does **not** build missing lexical surfaces. See
[`RESOURCE_EXTRACTION_SPEC.md` §§8/10](RESOURCE_EXTRACTION_SPEC.md#8-tokenization-indexing-and-retrieval-boundary).

Explicit offline prefix seeding independently validates old and new preparations
and pins, the base SQLite hash, frozen profile and lexical-surface policy; active
writes or incompatible policy reject. Reuse only an unchanged ordered job/reference
prefix with identical authority fingerprints, native-source bindings, permissions,
hashes and reference order. In a NEW copy, discard replaced-suffix postings,
helpers, parents and locators before validating and indexing the new references.
New helpers/parents retain full authority checks; mixed, reordered or tampered
prefixes reject. Never mutate the base/pins, silently relabel old policy, inherit
an unproved suffix, or extend inline. This is the existing derived lookup owner,
not another index or truth store.

File-backed recovery uses the existing ObservationStore: ordinary new records
are sharded under the same collection (`_shards/XX/id.json`), while keyed reads
and inventories support legacy flat and sharded records and reject duplicate
logical identities. Existing records retain their physical location; legacy
replacements stage on the same filesystem in a shard bucket rather than create
new entries in an exhausted flat directory. No bulk migration or query-time
writes/enumeration are introduced; IDs, hashes and permissions remain intact.
The finite sealed UAT materializer explicitly selects `write_layout="flat"` to
preserve its established byte-sealed export format. This bounded export policy
is not a global sharding revert, new truth store, PG migration or activation.
Metadata publication uses an exclusive same-filesystem temporary and atomic replacement,
with private permissions established BEFORE writing any bytes and intended final
permissions preserved. Failure before publication must retain valid old metadata;
partial first publications must not appear valid. Synthetic failure/concurrency
proof does not establish the cause of a historical unreadable-metadata incident.

Generic attachment backfill uses the existing Asset/ExtractorRun/Observation
owners. Known parser failures retain failed child runs and explicit partial-parent
coverage; unknown errors still fail, and failed runs/ledgers are never overwritten.
Bounded XLSX/XLSM/XLS, native-text PDF, DOCX/PPTX and text/delimited parsers do not
by themselves establish activated lexical+dense coverage or live UAT acceptance.
Missing fields on any matching source row keep exact projection coverage
incomplete; a source-backed explicit blank is distinct from an absent cell.
See extraction §7 for the failure boundary. Status remains **待測**.

Opt-in immutable object reuse in `scripts/issue56_attachment_backfill.py` remains **待測**.
`--preserve-existing-objects` selects the existing `FileObjectStore` policy; defaults are unchanged.
Reuse verifies the full byte hash/size and stored URI/backend/workspace identity,
then reuses existing metadata/filename unchanged, without payload or metadata writes.
Corrupt, incomplete or mismatched existing objects reject; normal verification/hash
algorithms and source checks are unchanged. New objects may still be created.
Cleanup uses only instance-created namespace receipts; valid reuse retains creation
receipts, invalid reuse revokes them. No broad concurrency/transactionality guarantee is made.
Opt-in binds to ledger inputs and extraction config/job identity; policy changes reject ledger reuse.
Canonical storage ownership, IDs, permissions and lineage remain unchanged;
no source/backend remap, alternate truth store or canonical KG writes are introduced.
Review/integration acceptance remains pending: this is not live deployment, complete
attachment coverage, source admission, launch readiness or browser acceptance.

Interruption recovery may use explicitly configured fixed source-order parent
windows in the existing offline sidecar batch owner (2026-10-12, **待測**).
Selection is by inventory position/count, never question terms or expected
answers; native sidecar ordinals and authorized parent bindings remain intact.
Seal the selected parent/attachment bytes and pin window/batch identity in the
extractor profile, including the preceding sidecar ordinal offset; preceding
membership drift must invalidate reuse even when selected bytes are unchanged.
Preserve old interrupted jobs, child records and ledgers;
a new retry uses a new batch identity, while an unchanged completed window
reuses its verified output without re-extraction. Changed persisted redaction
requires a new extractor/policy version and explicit offline job/revision;
attachment version0.6.2 preserves safe text around unsafe path spans
without weakening the detector or final fail-closed guard. Old output is not
silently repaired/relabelled, and a query never starts the replay. A completed window is partial
source coverage, not whole-corpus completion or permission to activate it.
Validate and compose only completed outputs through the existing source owner
before source-native querying; no online ingestion or new truth store. The
sidecar composer reuses the existing atomic link-or-copy helper across storage
mounts: only `EXDEV` selects the copy path; other I/O errors remain errors.
Source bytes/bindings stay unchanged and failed composition is not activation.

Offline vector reuse uses `DenseEvidenceVectorCache.seed_from` in the existing
`python/formowl_core/dense_embedding.py` owner. The indexed preparation-finish
CLI may explicitly supply `--seed-dense-cache-from` once for a **new** target;
omit it on ordinary resume. Validate the frozen encoder/profile/dimension,
exact UTF-8 text hashes, committed journal offsets and payload checksums under
the source lock. Reject active writers, incompatible/corrupt/torn bases and
existing targets without publishing a partial target. Copy numerical cache
files only, never hardlink or mutate the base or inherit source/permission
authority; each target freshly validates source and projection bindings.
Current Linux no-replace publication and bounded reads (4 KiB profile,
8 KiB journal record, 256 MiB journal, 8 GiB vectors) are implementation limits.
Ordinary interrupted-writer recovery remains separate. Focused cache tests
and scoped review do not establish real-cache activation or full RAG/UAT
acceptance; the overall feature remains **待測**.

The source-start attachment-text slice admits parsed document-modality
`paragraph`/`heading`/`list_item` evidence under its **mail** source family,
including captured mail without an upload-session selector. It must rehydrate
and validate the genuine attachment parent, child run/content hash, permission,
job and revision bindings before returning child text and native locators.
Missing parent stays incomplete; tampered bindings reject. An attachment is
not an independent `document_text` source. This path requires neither dense
activation nor a graph match and performs no query-time extraction or rebuild;
existing shared caps remain unchanged. Small real-parser/MCP/browser checks
are diagnostic, not corpus completeness, live-provider or business-field proof.
The offline lexical surface policy is versioned separately from the unchanged
frozen tokenizer: outputs or clone bases that omit attachment text must not be
accepted as the new capability. Build a fresh artifact offline; never rewrite
the old manifest or fill missing postings during a query.

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
enterprise-scale readiness, or KG + ontology superiority. As of 2026-10-18,
the `ontology_aware_uat` contract in §3.1.1/§6.2.1 is a required target whose
end-to-end implementation and acceptance have not been established. Existing
R55 browser diagnostics prove only their recorded retrieval/transport scopes,
not complete semantic ingestion, and remain **待測**. The new mode/ledger names
are not evidence that corresponding runtime fields already exist.

The current live R55 / R54 rollback checkpoint and finite R55 browser/source/wire evidence are recorded in §7.3.1 above. Earlier r12/r16 deployments,
focused checks, partial-source proof, failed reopens and reviewer limits are
[losslessly archived](docs/archive/2026-10-17/weekend-r37-contract-correction-preedit/root/SPEC.md); they do not prove current availability,
whole-source completeness or stability. In particular, the dated r12 native answer
proof did not resolve its first reopen failure. Old receipts and archives are unchanged.

Current source support must be read at the following granularity:

| Source slice | Current code evidence and limit |
| --- | --- |
| Mail and independent text | Mail is the first diagnostic fixture; the real `PlainTextObservationExtractor` handles independent Markdown/plain-text. §7.3.1 retains its mail/text-only diagnostic and promotion boundary, with live acceptance still open. |
| Attachment text | Bounded native-text PDF, DOCX/PPTX and text parsers produce source-addressed content. The deployed bounded source-start lexical/reader/gateway path retains parsed attachment text under `mail` with genuine parent/child/run/hash/permission bindings. Earlier parser/provider-free diagnostics alone do not establish full live acceptance or whole-corpus coverage; the r12 observed live native proof above does not resolve the first source-reopen failure. Scan-only PDF/OCR and native rendering remain unsupported. |
| XLSX and delimited attachment tables | [`AttachmentDocumentExtractor`](python/formowl_ingestion/extractors/document/attachment.py) reads bounded XLSX ZIP/XML values (`<v>`, shared strings, inline strings), emits row/cell Observations and coordinates, retains formula/raw/cached/date/precision/blank metadata where available, reads formal table metadata, and derives bounded candidate header paths using merged ranges. It does not recalculate formulas or guarantee native display semantics, full style fidelity, native type/unit/null coverage, or whole-workbook completeness. Candidate header structure is not verified source-provided schema. Standalone spreadsheet/XLSX is a first-class product requirement; this attachment slice does not establish its complete end-to-end path. |
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

GitHub issue #20 is a scoped closed/deferred external-activation record, not
proof of live acceptance. Its external PostgreSQL, container lifecycle, MCP
Inspector, live ChatGPT/Google, reviewer, and completion-audit obligations remain
unaccepted; current risk/dependency tracking is in issue #63.
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
- `direct_evidence_baseline` permits unannotated evidence retrieval, but
  `ontology_aware_uat` requires a complete declared-scope semantic annotation
  ledger and reviewed/pinned overlay before claiming ontology behavior;
- semantic records are zero-to-many per Observation and must capture entities,
  claims, events, relations, temporal meaning, attachment/thread lineage, and
  supersession where present; a zero-candidate unit is still processed and
  recorded;
- incomplete annotation, extraction, projection, or source coverage remains
  `partial`/`pending_review` and never proves source absence;
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

### 15.6 Ontology-aware webpage acceptance — 待實作／待測

Declare the source snapshot, coverage scope, implementation/version pins and
expected source-backed results before a diagnostic run. Missing newer mail is
an explicit snapshot limit, never an excuse for missing in-snapshot evidence.
Do not narrow the scope after observing failures. Final product acceptance is
**a question entered through the UAT webpage and its visible answer/citations**;
API output, worker completion, index activation, HTTP 200, MCP calls and logs
are debugging evidence, not substitutes for the visible answer.

The same generic pipeline must pass at least:

| Scenario | Required visible result |
| --- | --- |
| Mail + attachment event/update chain | Correct per-item facts and date roles, distinguishing request/commitment/update/shipment; no automatic newest-message-wins rule |
| Independent project/work-item + document history | Correct owner/deadline/status/decision update with citations; no mail/session dependency or new answer service |
| Identity ambiguity, quoted old content and conflicting revisions | Correct distinction or explicit ambiguity/conflict, not a plausible invented join |
| Unannotated/failed attachment or missing projection | Supported facts where available and an honest coverage limit; never false absence or a fabricated date |
| Native rows/cells and independently checkable negative case | Same-row/item binding and native citation; a definitive negative only with deterministic complete coverage |
| Chat, multi-turn target change, reload and new conversation | Ordinary chat preserved; current-target MCP evidence when needed; no stale citations or session-contract regression |

Authorized reviewers independently read original mail/attachments/documents,
including relevant surrounding text and headers, to establish expected values,
date meaning, item association and citations. Inspect visible answers against
that oracle; safe abstention on an answerable positive case is still a failure.
Reported cases and known PO questions are development regressions, not unseen
holdout. Add independently selected, source-backed questions with different
identifiers, wording and source families; never tune runtime to expected answers.

Internal traces must corroborate that annotations actually selected the cited
source and supported temporal/relationship reasoning. A browser pass via direct
RAG alone does not establish ontology use, and a valid internal trace cannot
rescue a wrong visible answer. Keep the feature **待測** until this end-to-end
evidence and required review pass; whole-method/release claims still require
the existing authority and independent three-reviewer gates.

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
  -> Source-completeness reconciliation
  -> Source-Preserving Observation (text, structured, or native media reference)

`direct_evidence_baseline`:
  -> Authorized Modality-Appropriate Retrieval / Native Structured Execution

`ontology_aware_uat`:
  -> Complete semantic read/annotation ledger for the declared scope
  -> Review -> Canonical KG + Scoped Ontology -> EffectiveGraphView
  -> Ontology-linked source selection
  -> Raw/native evidence validation

Core Query Agent + Validated Plan
  -> Bounded Verified EvidenceBundle / Deterministic Result
  -> Cited Answer, Projection, or Reviewed Action Proposal
```

Direct authorized retrieval and exact table execution do not require a graph
match or ontology annotation **when the run is explicitly the baseline or a
bounded fallback**. They cannot be used to claim that ontology-aware UAT has
completed. In ontology-aware mode, graph/ontology selection is useful only when
it is linked to source evidence and coverage status; a KG miss falls through to
bounded source retrieval and cannot become a false absence. The frozen issue
#56 program still evaluates graph-guided hybrid execution against its strong RAG
control under the same authority and acceptance gates; this schematic makes no
methodology-readiness or superiority claim.
