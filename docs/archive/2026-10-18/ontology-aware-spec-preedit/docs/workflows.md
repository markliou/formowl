# Workflows

FormOwl workflows are task-oriented and source-neutral. Users should work in
natural language through ChatGPT or a narrow FormOwl task surface, not through
storage browsers, parser controls, SQL consoles, or graph-maintenance UIs.

The active workflow is:

```text
source intent
  -> governed source capture
  -> source-preserving Observations
       -> authorized native retrieval / deterministic structured execution
       -> optional zero-to-many candidate annotations and knowledge
            -> review -> canonical KG + scoped ontology
            -> permission-filtered EffectiveGraphView when used
  -> bounded source-linked evidence bundle / deterministic result
  -> cited answer, projection, or reviewed action proposal
```

Mail is the first diagnostic example. Documents, standalone spreadsheets/XLSX,
tables/databases, images, speech, non-speech audio/music, video and connected
systems use the same governed boundary while preserving native evidence.
Direct authorized lookup and source-native table execution need no graph match
or ontology annotation; graph-required relation reasoning retains source-backed
reviewed paths.

## 1. Workflow Rules

Every workflow must preserve these boundaries:

- source evidence is not canonical knowledge;
- Observation is not a canonical fact;
- matching does not grant access;
- access does not authorize canonical merge;
- graph visibility does not grant evidence or raw asset access;
- inferred ontology mismatch does not delete admitted evidence;
- missing graph/ontology entries do not prove absence in the source;
- top-k retrieval does not prove a complete set or total count;
- LLM output is a proposal or rendering, not hidden authority;
- external writes are proposal-first; and
- public results do not expose paths, SQL, credentials, parser, storage,
  worker, oracle, or unrelated private content.

## 2. Connected Sign-In and ActorContext

The connected closed-beta journey is:

```text
operator creates a time-limited FormOwl invitation
  -> user connects FormOwl in ChatGPT
  -> ChatGPT follows the OAuth challenge for exact public HTTPS /mcp
  -> FormOwl validates predefined client, exact callback/resource, and PKCE S256
  -> user signs in through Google OIDC
  -> FormOwl verifies issuer, subject, and email
  -> FormOwl maps the identity through the invitation
  -> FormOwl issues its own resource-bound access token
  -> every protected call reloads current state and builds a fresh ActorContext
```

The predefined client ID is a stable non-secret selected and recorded by the
deployment operator before discovery. ChatGPT app management must use that
same client ID when its current predefined-client UI supports entry or
selection. ChatGPT supplies and displays only the production callback
`https://chatgpt.com/connector/oauth/{callback_id}`. The client ID must not be
invented or described as generated or displayed by ChatGPT. If the UI cannot
use it, stop and record an external live blocker.

Google tokens are never FormOwl MCP bearer tokens. FormOwl remains authoritative
for users, invitations, memberships, client authorization, token sessions,
workspaces, grants, revocation, and audit.

Failure behavior is fail-closed:

```text
missing, expired, or email-mismatched invitation -> no user or token state
revoked or expired token session -> protected call denied immediately
disabled user or external identity -> denied
removed workspace membership -> no fresh ActorContext for that workspace
successful reconnect -> new token session; old session stays unusable
```

Issue #20 remains open until live PostgreSQL, operator CLI, production container
lifecycle, MCP Inspector, live ChatGPT/Google, reviewer, and completion-audit
evidence passes. Local compatibility tests do not close those external gates.

## 3. Governed Source Capture

### 3.1 UploadSession

A user begins with intent, not a file path:

```text
User: Add this source to FormOwl for project X.
ChatGPT -> MCP Gateway: open_upload_session(intent, source family, scope, visibility)
Gateway -> backend: create audited UploadSession under fresh ActorContext
Gateway -> ChatGPT: task card with a session-bound upload action
User -> controlled upload surface: transfer bytes for that UploadSession
Backend: register Asset and occurrence, apply retention, create IngestionJob
```

The upload task captures:

```text
actor
owner/workspace/project/customer scope
source family
ingestion profile
visibility and permission scope
retention policy
expiration
processing state
```

Users do not choose NAS paths, buckets, object-store keys, parser binaries,
worker queues, database tables, or index implementations.

Issue #41 owns generic Asset tenant, owner, byte storage, occurrence, recovery,
retention, purge, transfer, and authorization. Source adapters consume that
boundary rather than creating parallel storage or permission systems.

### 3.2 External source capture

For APIs, project systems, calendars, databases, and other external systems:

```text
authorized connector call
  -> SourceRef and request/response hash
  -> EvidenceSnapshot or governed Asset occurrence
  -> permission and capture metadata
  -> extraction or normalization job
```

The capture stores stable FormOwl identifiers and safe source metadata. Raw
credentials, endpoints, queries, and provider payload internals remain private.

### 3.3 ChatGPT session capture

A convenience action may save the current conversation:

```text
User: Save this conversation.
  -> capture current session under fresh ActorContext
  -> register the source artifact and occurrence
  -> create normal ingestion/extraction work
  -> return task status
```

This shortcut does not turn ChatGPT memory into truth and does not skip source
account attribution, Asset registration, permission, retention, or audit.

## 4. Extraction and Source-Completeness Workflow

```text
registered source
  -> IngestionJob
  -> policy-selected ExtractorAdapter
  -> immutable ExtractorRun
  -> source-native Observations
  -> Observation manifest
  -> source-completeness reconciliation
```

Deterministic extraction produces hashes, identifiers, structure, locators, and
unambiguous normalization. Semantic extraction may propose entities, claims,
relations, states, events, frames, or descriptions.

Preserve native text, structured values and governed binary regions/intervals.
OCR/transcripts/descriptions remain derived representations and cannot alone
verify visual, acoustic, musical or motion-dependent facts. Spreadsheet
evidence preserves raw/formula/cached/display distinctions, types/precision/
units, blanks/nulls, merged headers, coordinates and same-row association.

Before methodology-quality evaluation, compare the authorized Observation
manifest with an independent raw-source or source-system inventory. Classify
missing units as policy redaction, unsupported feature, extractor failure,
normalization loss, occurrence loss, or unexplained loss. Only intentional
policy redaction may be absent without failing completeness. Measure native
source occurrences and features required for the claim, including unsupported
formulas/type/display semantics or media content, independently of annotation,
graph and index counts. Unexplained loss blocks the comparison.

Re-extraction creates a new ExtractorRun. Tokenizer or embedding changes rebuild
indexes from authorized Observations without reparsing or rewriting source
evidence.

## 5. Candidate and Canonical Graph Workflow

```text
Observations
  -> candidate mentions/business objects/assertions/relations/frames
  -> permission and evidence validation
  -> entity and relation resolution proposals
  -> type/ontology alignment candidates
  -> human or authorized policy review
  -> canonical graph commit inside an explicit scope
  -> lifecycle and audit events
```

Candidate review may accept, reject, correct, split, merge, defer, or mark an
item ambiguous. Uncertain entity matches remain candidates.

Candidate cardinality is zero-to-many per document and Observation; each
annotation retains all contributing source IDs/occurrences/locators. No semantic
candidate is required for source evidence admission. The reviewed KG is an
identity/relation overlay linked to evidence, not a replacement for native
cells or media content.

Canonical commit records source observations and occurrences, permission scope,
review decisions, policy and ontology revisions, previous/new graph revisions,
and audit lineage.

Lifecycle changes preserve old identifiers through split, merge, supersession,
deprecation, equivalence, derivation, and archive mappings.

## 6. Ontology Workflow

Ontology construction uses calibration and development evidence only:

```text
source/domain vocabulary candidates
  -> map to small stable core
  -> retain source-local types and occurrences
  -> review aliases, types, frames, and relations
  -> publish scoped OntologyRevision
  -> evaluate transfer and retrieval contribution
```

Hard validation is reserved for permission, schema/arity, evidence lineage,
revision pins, canonical-write preconditions, and exact-set coverage.

Inferred type, frame, alias, relation, and preferred path are soft. The runtime
adds only a capped ontology bonus. Mismatch removes the bonus, not the evidence
candidate. Hard type/frame pruning is used only in an explicitly named negative
ablation.

The independent holdout is never used to add ontology terms, aliases, or
mappings.
Vocabulary, arity and allowed edge shapes govern optional source annotations;
they impose neither one annotation per Observation nor an annotation-count cap.
Unannotated or unmatched authorized evidence remains available to source execution.

## 7. Query Workflow

### 7.1 Common entry

```text
user prompt + bounded validated conversation state under fresh ActorContext
  -> Query Agent resolves intent/coreference
  -> discover authorized schemas/modalities/native locators/MCP capabilities
     and EffectiveGraphView / ontology bindings when used
  -> classify query
  -> expand and validate SemanticQueryPlan / tool plans
  -> execute under frozen revisions and budgets
  -> inspect requested-field coverage; bounded repair/requery or stop
  -> return structured evidence/result plus citations
```

A planner model may propose a plan. Deterministic validation enforces actor,
workspace, source, permission, graph/ontology bindings when used, policy, model, budget, path,
coverage, output schema, and maximum claim strength.

One bounded repair pass may fill unresolved required slots only inside the
original source and permission scope. This general plan repair must not bypass
the automatic all-requested-fields source-recheck rule in §7.2 below.

Each request reuses available activated, version-pinned KG/effective view and
lexical/dense indexes. Missing, unsealed, or unactivated retrieval projections
are distinct from an independently validated immutable source snapshot and its
authorized provider manifest. Projection failure grants no independent
eligibility under `SPEC.md` §7.3.1. Eligible fallback may use that snapshot
without the failed projection, but retains authorized source/hash/lineage/revision
checks, the same ActorContext, source/permission scope, and remaining budgets. Request
handling never rebuilds those projections inline.

### 7.2 Evidence lookup

```text
query
  -> typed identifier+field exact lookup when the request supplies both
  -> authorized source-native access / modality-appropriate strong RAG
     (frozen text control: BM25 + dense retrieval + fusion)
  -> optional entity-aware grouping and source-backed graph expansion
  -> temporal/provenance filtering
  -> capped ontology scoring
  -> evidence-bundle reranking
  -> coverage inspection; bounded validated expansion/repair
     automatic source recheck only when §7.3.1 eligibility holds
  -> compact verified native source context
  -> cited answer
```

Strong RAG is not a weak fallback. It is the evidence-retrieval component and
comparison baseline. Graph expansion is used only when it can add reviewed
identity, joins, topology, time, contradiction, provenance, or coverage.
Exact lookup and recovery preserve the original requested fields, row
association, citations, permission scope, and remaining deadline/budgets.
Authorized source execution requires no annotation/node/edge match. Table
access uses native schema/rows/cells; images use verified regions; audio/music
uses verified intervals; video uses verified clips/frames/scenes. Discover and
pin actual adapter/model/index capabilities. Unsupported native access is
unsupported/incomplete; a text proxy does not prove modality-dependent facts.
`no_authorized_evidence`, source blank, and permission denial are evidence
outcomes; provider errors and timeouts are operational failures and must be
reported distinctly rather than rendered as no-answer.

**2026-10-06 source-recheck rule — 待測:** validated `evidence_lookup` with a
nonempty validated requested-field set and **all** fields lacking verified
support triggers one materially different, same-authorized-scope bounded
source recheck when existing safety/eligibility and remaining budgets permit,
even with unrelated citations. Partial misses must be disclosed and must not
trigger this automatic recheck. An empty field set is not vacuously all missing:
use the existing validated evidence-need plan or clarify. Source-backed explicit
blanks count as verified coverage; citation count or status alone cannot trigger
recheck.
Mail and independent Markdown/plain-text document lookup share the core;
attachments are not independent documents. At most one shared source recheck
uses the existing `500 ms` / `8192` phase and pinned budgets in `SPEC.md`
§7.3.1. Exact deterministic execution, permission/schema/provider-error
exclusions, and no-inline-rebuild rules remain unchanged. Incomplete/timeouts
are not absence; a scoped complete negative requires complete coverage proof.

### 7.3 Relation reasoning

```text
entity-linked query
  -> allowlisted relation/direction plan
  -> bounded traversal
  -> resolve each node/edge/hop to authorized Observations
  -> reject unsupported hops
  -> rerank complete evidence bundles
  -> cited path answer
```

Hidden nodes are never materialized or used as score signals. A graph label
without source evidence cannot support an answer claim.

### 7.4 Exact set, count, inventory, and aggregation

```text
exact-set language
  -> deterministic exact_set_or_inventory route
  -> schema-validated native rows/cells or faithful revision-bound projection
     over explicit authorized source/effective-view scope
  -> duplicate and redaction policy
  -> coverage calculation
  -> structured result with evidence per item
  -> optional LLM rendering without membership changes
```

If coverage is incomplete, return `partial` or equivalent bounded status. Never
infer a complete set, total count, missing item, or definitive absence from
top-k retrieval.

Spreadsheet lookup, filtering, joins, sorting, aggregation and counts preserve
formula/raw/cached/display distinctions, source types/precision/units,
blanks/nulls, merged-header paths, coordinates and same-row association.
State value representation and calculation semantics; cached XML values alone
do not prove fresh formula results. Native cell/range citations, source lineage
and coverage are mandatory. Ambiguous headers, unsupported formula/type/display
features, redacted ranges or incomplete rows weaken/block exact claims. Graph
properties and annotation coverage cannot supply source values or completeness.

### 7.5 Global summarization

Global summaries operate over an explicitly bounded, permission-filtered source
or evidence set. The response discloses the boundary, policy redactions,
unsupported content, conflicts, and incompleteness.

## 8. Evidence Bundle and Answer Workflow

An evidence bundle contains the material needed to support a claim:

```text
selected native source Observations and citations
requested-field support/blank/unresolved coverage
entity links, review state and bounded graph path proof when used
temporal/current-state selection
contradiction or supersession context
coverage and redaction status
score components
pinned revisions and execution fingerprint
```

The final answer model receives only the validated plan and authorized bundle.
It uses the same model, reasoning effort, prompt, output schema, context budget,
and decoding settings across comparison arms.

Bounded context augmentation may read an adjacent paragraph/heading, relevant
header/cell range, image crop or media clip/frame. Revalidate source occurrence,
hash/revision/lineage/permission/native locator and remaining evidence/token/
time budgets for each read, retaining original region/range/time and
transformation metadata. Snippet access or graph visibility does not authorize
whole-asset access; no default large-asset/corpus dump enters model context.
Reads reuse valid sources/projections without inline extraction or rebuilding.
§7.3.1 automatic recheck remains separate and unchanged; its mail/text `16 KiB`
presentation cap is not a native-media limit or support claim.

The answer must cite evidence and disclose unresolved, conflicting, historical,
policy-redacted, unsupported or incomplete state. It must not fill missing
source evidence from pretrained knowledge.

## 9. Access Request and Shared Graph Workflow

```text
query requires another scope
  -> match or path candidate indicates unavailable evidence
  -> return access_required without private content
  -> create scoped AccessRequest when requested
  -> owner or authorized reviewer approves, narrows, denies, expires, or revokes
  -> Grant changes future EffectiveGraphViews
```

Access levels may include answer-only, graph snippet, evidence snippet, and
controlled raw asset reference. Raw access always uses a separate grant and a
governed locator.

Revocation changes future effective views. It does not rewrite source evidence,
canonical history, or prior audited decisions.

## 10. Projection and External Action Workflow

### 10.1 Cited answer or report

```text
validated query result
  -> projection spec
  -> cited answer/report/dashboard draft
  -> review and revision
```

### 10.2 Wiki projection

```text
EvidenceBundle or EffectiveGraphView
  -> WikiProjectionSpec pins source/graph/ontology/permission revisions
  -> Wiki MCP creates a draft with citations and frontmatter
  -> reviewer compares and edits
  -> reviewed revision becomes immutable
  -> publish remains a proposal until separately authorized
```

### 10.3 External write

```text
cited result or approved graph state
  -> target-specific action proposal
  -> explicit review and authorization
  -> validated no-partial-write execution path
  -> audit and external revision reference
```

No query or extractor performs an external write implicitly.

## 11. Mail-First Example

Mail validates the generic workflow:

```text
UploadSession or governed mailbox capture
  -> archive/message/attachment Assets and occurrences
  -> mail ExtractorRun
  -> thread/header/message/body/attachment Observations
  -> normalized mail evidence
       -> authorized source retrieval / structured execution and strong RAG index
       -> optional candidate entities/claims/relations/frames
            -> reviewed cross-message and cross-source graph
  -> validated source / graph-guided hybrid execution
```

The adapter preserves archive, mailbox, folder, message, thread, quoted,
forwarded, embedded, attachment, and table occurrences. Parsing does not answer
case-progress questions or commit graph state as a side effect.

The repository contains synthetic and bounded PST diagnostics. Those paths are
implementation evidence for their stated fixtures, not universal parser,
source-completeness, production, or KG-superiority evidence.

Standalone spreadsheet/XLSX is a first-class source requirement. The current
attachment extractor's bounded ZIP/XML values/coordinates/formal table metadata
and candidate merged-header paths retain formula/raw/cached metadata where
available but do not recalculate formulas or guarantee styles/display,
prove native types/units/nulls or full-workbook coverage, or establish its
standalone end-to-end path. OCR, audio-transcript and video-scene adapters use
`read_text()` fixtures. Real-image OCR/visual retrieval, real decoding/ASR,
acoustic/music verification and real-video temporal/clip/frame verification
remain unproved. [SPEC §14](../SPEC.md#14-current-implementation-and-methodology-status)
keeps native capability separate from MIME labels, coordinates and text proxies.

After mail-first validation, issue #56 requires a materially different transfer
source such as calendar, ticket/project, or document-section evidence without
adding question-specific core types or aliases.

## 12. Comparative Evaluation Workflow

```text
freeze source, Observation, permission, tokenizer, index, model, prompt,
budget, evaluator, code, image, and hardware manifests
  -> run strong RAG
  -> run RAG + entity linking
  -> run RAG + bounded candidate KG
  -> run RAG + KG + capped soft ontology
  -> run hard ontology negative ablation
  -> run deterministic exact executor where mandated
  -> compare final answers by pre-registered stratum
  -> seal diagnostic artifacts
  -> run one independent holdout
  -> run transfer-domain holdout
```

Calibration, development, evaluation, independent holdout, and transfer data
remain separate. Holdout content cannot tune tokenizer, aliases, ontology,
thresholds, routing, paths, prompts, models, or grading.

Before methodology-quality execution or a comparative claim:

```sh
python3 scripts/methodology_authority_check.py --require-ready
```

A nonzero exit blocks the claim. It does not justify question-specific fitting
or another unregistered pipeline.

## 13. Local Compatibility Workflows

File-backed stores, deterministic fixtures, Project/Wiki JSON-line runners,
and the hand-built semantic JSON-RPC runner remain useful for local tests.
They are not alternate connected identity paths and do not replace public HTTPS
`/mcp`, OAuth, Google OIDC, or fresh `ActorContext` resolution.

Public compatibility reports remain hash/status/count oriented and exclude raw
source content, local paths, environment values, SQL, parser/storage/worker
internals, credentials, and hidden oracle values.

## 14. Verification

Canonical verification runs in the dev container:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local \
  python -m unittest discover -s tests
```

Methodology authority is checked separately:

```sh
python3 scripts/methodology_authority_check.py --check
python3 scripts/methodology_authority_check.py --require-ready
```
