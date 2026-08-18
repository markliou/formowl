# Workflows

FormOwl workflows are task-oriented and source-neutral. Users should work in
natural language through ChatGPT or a narrow FormOwl task surface, not through
storage browsers, parser controls, SQL consoles, or graph-maintenance UIs.

The active workflow is:

```text
source intent
  -> governed source capture
  -> source-preserving Observations
  -> reviewable candidate knowledge
  -> governed canonical KG + scoped ontology
  -> permission-filtered EffectiveGraphView
  -> strong-RAG + graph-guided execution
  -> cited answer, projection, or reviewed action proposal
```

Mail is the first large example. Other sources follow the same stages.

## 1. Workflow Rules

Every workflow must preserve these boundaries:

- source evidence is not canonical knowledge;
- Observation is not a canonical fact;
- matching does not grant access;
- access does not authorize canonical merge;
- graph visibility does not grant evidence or raw asset access;
- inferred ontology mismatch does not delete admitted evidence;
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

Before methodology-quality evaluation, compare the authorized Observation
manifest with an independent raw-source or source-system inventory. Classify
missing units as policy redaction, unsupported feature, extractor failure,
normalization loss, occurrence loss, or unexplained loss. Unexplained loss
blocks the comparison.

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

## 7. Query Workflow

### 7.1 Common entry

```text
user query under fresh ActorContext
  -> choose permission-filtered EffectiveGraphView and source bounds
  -> classify query
  -> create and validate SemanticQueryPlan
  -> execute under frozen revisions and budgets
  -> return structured evidence/result plus citations
```

A planner model may propose a plan. Deterministic validation enforces actor,
workspace, source, permission, graph, ontology, policy, model, budget, path,
coverage, output schema, and maximum claim strength.

One bounded repair pass may fill unresolved required slots only inside the
original source and permission scope.

### 7.2 Evidence lookup

```text
query
  -> BM25 lexical retrieval
  -> dense retrieval
  -> deterministic fusion
  -> optional entity-aware grouping and bounded graph expansion
  -> temporal/provenance filtering
  -> capped ontology scoring
  -> evidence-bundle reranking
  -> cited answer
```

Strong RAG is not a weak fallback. It is the evidence-retrieval component and
comparison baseline. Graph expansion is used only when it can add reviewed
identity, joins, topology, time, contradiction, provenance, or coverage.

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
  -> schema-validated enumeration over an explicit source/effective-view scope
  -> duplicate and redaction policy
  -> coverage calculation
  -> structured result with evidence per item
  -> optional LLM rendering without membership changes
```

If coverage is incomplete, return `partial` or equivalent bounded status. Never
infer a complete set, total count, missing item, or definitive absence from
top-k retrieval.

### 7.5 Global summarization

Global summaries operate over an explicitly bounded, permission-filtered source
or evidence set. The response discloses the boundary, policy redactions,
unsupported content, conflicts, and incompleteness.

## 8. Evidence Bundle and Answer Workflow

An evidence bundle contains the material needed to support a claim:

```text
source Observations and citations
entity links and review state
bounded graph path proof
temporal/current-state selection
contradiction or supersession context
coverage and redaction status
score components
pinned revisions and execution fingerprint
```

The final answer model receives only the validated plan and authorized bundle.
It uses the same model, reasoning effort, prompt, output schema, context budget,
and decoding settings across comparison arms.

The answer must cite evidence and disclose unresolved, conflicting, historical,
policy-redacted, or incomplete state. It must not fill missing graph slots from
pretrained knowledge.

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
  -> strong RAG index
  -> candidate entities/claims/relations/frames
  -> reviewed cross-message and cross-source graph
  -> Hybrid v2 query execution
```

The adapter preserves archive, mailbox, folder, message, thread, quoted,
forwarded, embedded, attachment, and table occurrences. Parsing does not answer
case-progress questions or commit graph state as a side effect.

The repository contains synthetic and bounded PST diagnostics. Those paths are
implementation evidence for their stated fixtures, not universal parser,
source-completeness, production, or KG-superiority evidence.

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
