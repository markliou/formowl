# MCP Boundaries

MCP is FormOwl's governed orchestration and review boundary. It is not the
source parser, database console, graph engine, model runtime, or infrastructure
control plane.

The connected FormOwl MCP Gateway is the only formal ChatGPT-facing service.
Project MCP, Wiki MCP, JSON-line commands, and the hand-built semantic
JSON-RPC/stdio runner are internal or local compatibility surfaces.

## 1. Public Service Boundary

```text
ChatGPT or another approved OAuth client
  -> one canonical public HTTPS FormOwl origin
       -> /.well-known/oauth-protected-resource
       -> /.well-known/oauth-authorization-server
       -> /oauth/authorize
       -> /oauth/google/callback
       -> /oauth/token
       -> JWKS
       -> /healthz and /readyz
       -> exact protected /mcp resource
  -> governed FormOwl services
  -> internal PostgreSQL, object storage, workers, and compatibility services
```

ChatGPT never connects directly to PostgreSQL, object storage, NAS, parser
workers, model workers, graph stores, or private source systems.

## 2. Single Task Surface

User-facing tools expose business and knowledge operations:

```text
capture or upload a source
inspect processing status
search or answer from authorized evidence
preview and review graph candidates
request access
inspect a governed graph view
create a cited projection or action proposal
```

They do not ask normal users to select:

```text
NAS folder or local path
bucket or object-store key
parser binary or command
worker queue
embedding service
vector or graph database
SQL table or query
model cache or scratch directory
```

A separate upload page or widget, when required, is bound to one
`UploadSession` and continues the current task. It is not a generic file
manager or backend console.

## 3. Connected OAuth and ActorContext

The connected identity flow is:

```text
public HTTPS /mcp request
  -> OAuth challenge and protected-resource metadata
  -> FormOwl authorization for the predefined client
  -> exact callback/resource and PKCE S256 validation
  -> Google OIDC login
  -> verified Google issuer, subject, and email
  -> FormOwl invitation and external-identity mapping
  -> FormOwl authorization code and resource-bound token
  -> current PostgreSQL authorization and revocation checks
  -> fresh gateway-controlled ActorContext
  -> governed tool
```

The predefined client ID is a stable non-secret selected and recorded by the
deployment operator before discovery. ChatGPT app management must use that
same client ID when its predefined-client UI supports it. ChatGPT supplies and
displays only the production callback
`https://chatgpt.com/connector/oauth/{callback_id}`. FormOwl must not invent the
client ID or claim ChatGPT generated or displayed it. Missing UI support is an
external live blocker.

Google access and ID tokens are upstream identity evidence only. They are never
accepted as FormOwl MCP bearer tokens. FormOwl remains the authority for users,
invitations, memberships, OAuth clients, token sessions, workspaces, grants,
revocation, and audit.

Every protected call rebuilds `ActorContext` from current server-side state.
The gateway rejects or overwrites caller-controlled actor, workspace, session,
membership, reviewer, grant, storage, parser, worker, and model-routing fields
before a semantic handler executes.

`whoami` reports the current FormOwl identity and authorized workspace. It does
not select identity.

## 4. Discovery-Only Boundary

The exact reserved callback
`https://invalid.example.invalid/formowl-discovery-only` selects the
`discovery_only` state. It exists only so a client can discover the public MCP
shape before the production callback is known.

In `discovery_only`:

- only `initialize` and `tools/list` are available as public discovery;
- every protected tool returns the standard OAuth challenge;
- bearer credentials are not treated as an authenticated session;
- bootstrap, invitations, OAuth completion, token exchange, operator mutation,
  and protected semantic execution are blocked;
- no authorization audit is created for a protected tool because no identity
  or authorization decision is permitted;
- `/readyz` remains 503 while `/healthz` may keep the process health-visible;
- CLI preflight exits nonzero with `status: discovery_only`; and
- the deployment must be stopped, configured with the production callback, and
  restarted before identity or protected tool state is created.

The discovery sentinel is not a second authentication mode and must never be
used as a production callback or client ID.

## 5. Current Public Semantic Surface

`python/formowl_gateway/remote.py` is the connected tool-descriptor authority.
`python/formowl_gateway/semantic.py` defines governed schemas for configured
handlers.

The current connected runtime may expose:

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
`select_actor` is never a connected tool.

Tools without a configured safe backend handler remain absent or return a
review/pending boundary. They must not be presented as fully implemented.

## 6. Hybrid Query Tool Boundary

A current or future general query tool must execute this architecture:

```text
fresh ActorContext
  -> permission-filtered source bounds and EffectiveGraphView
  -> typed query class
  -> validated SemanticQueryPlan
  -> BM25 + dense evidence retrieval
  -> conservative entity linking and bounded graph traversal
  -> temporal/provenance/coverage filtering
  -> capped soft ontology scoring
  -> evidence-bundle reranking
  -> deterministic exact result or cited answer
```

The public schema should express business intent, source/task scope, requested
claim type, and safe output preferences. It must not expose internal SQL,
index, graph-engine, model-server, parser, or worker controls.

### 6.1 Plan validation

A planner model may propose a plan. The backend validates:

```text
query class
actor/workspace/source/permission scope
effective-view, graph, ontology, policy, tokenizer, and model revisions
entity and relation slots
allowed paths and directions
hop, fan-out, candidate, evidence, time, token, and repair budgets
coverage requirement
output schema and maximum claim strength
```

Invalid, scope-widening, or unpinned plans fail closed. A bounded repair pass
cannot broaden permissions or source scope.

### 6.2 Evidence lookup and relation reasoning

The query tool may return:

```text
safe answer or structured result
citations and governed observation locators
source/evidence coverage status
conflict, historical, superseded, or incomplete warnings
redaction counts
safe execution and revision identifiers
```

Every answer-relevant graph hop resolves to authorized Observations. Graph
labels, inferred types, or model memory alone cannot support a high-trust claim.

### 6.3 Exact queries

Queries for all, every, count, inventory, duplicates, missing items,
aggregation, completeness, or definitive absence route to a deterministic
executor. The result includes scope, coverage, redaction, unresolved counts,
stable ordering, and evidence per item.

Top-k retrieval cannot be labeled complete.

### 6.4 Query side effects

Retrieval, traversal, plan repair, and answer generation do not create hidden
candidate, canonical, ontology, user-graph, wiki, or external-system writes.
A query may return a separate review-required proposal seed only when the
public contract says so.

## 7. Upload and Source-Capture Boundary

ChatGPT-facing tools may:

```text
create an audited UploadSession from intent and scope
return a session-bound upload task card or widget
provide source-preparation guidance attached to that session
inspect upload and processing status
create ingestion work after FormOwl registers the source
capture the current ChatGPT session under the same Asset/permission rules
```

They must not:

```text
accept arbitrary local/NAS paths as public source identity
ask the user to choose storage, parser, worker, or database controls
turn an upload surface into a file manager
skip Asset registration, occurrence lineage, permission, retention, or audit
```

Authentication of `open_upload_session` identifies the requester. It does not
by itself complete Issue #41's generic Asset authorization and lifecycle rules.

## 8. Candidate, Review, and Canonical-Write Boundary

External tools, extractors, and LLMs may write only reviewable intermediate
records through governed handlers:

```text
Observation
SemanticMetadata
CandidateMention
CandidateBusinessObject
CandidateAtom
CandidateRelation
CandidateFrame
ExternalGraphImport
```

Only the graph-governance backend may create a canonical commit:

```text
reviewed candidate set
  -> evidence and permission validation
  -> entity/relation/type resolution
  -> canonical-write precondition validation
  -> atomic CanonicalGraphCommit
  -> lifecycle and audit events
```

An MCP tool may submit or approve a proposal according to policy, but the
client does not directly write graph tables or choose a merge implementation.

Ontology term, alias, mapping, and promotion operations follow the same
candidate/review/revision model.

## 9. Collaborative Graph and Access Boundary

An effective view may combine:

```text
actor-owned graph
workspace/project graph
currently granted graph fragments
```

If required evidence belongs to another scope and no grant exists, return an
access-required response without private content. A separate request workflow
may create, approve, narrow, deny, expire, or revoke access.

Possible access levels include:

```text
answer_only
graph_snippet
evidence_snippet
controlled raw_asset reference
```

Raw access requires an explicit grant and a governed locator such as
`formowl://asset/{asset_id}`. It never returns a filesystem or object-store
administration path.

Entity matching, access overlay, canonical merge, and raw access remain
separate workflows.

## 10. Projection and External Writes

MCP tools may create cited drafts and reviewable proposals:

```text
answer/report/dashboard draft
wiki draft or refresh proposal
project comment proposal
work-item update proposal
access decision proposal
canonical graph commit proposal
```

External execution requires explicit authorization, current permission, a
validated target, audit, and no-partial-write behavior. Automatic publishing or
business-system mutation is disabled unless a separately approved workflow
makes it explicit.

## 11. Forbidden Tool Shapes

ChatGPT-facing MCP must not expose:

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
select_embedding_server(name)
execute_graph_query_raw(query)
read_private_oracle(case_id)
```

Public errors and tool results must not contain credentials, tokens, private
keys, raw source payloads, raw paths, SQL, parser commands, worker scratch,
model-cache paths, hidden oracle values, or unrelated private identifiers.

## 12. Audit Boundary

Audit covers:

```text
OAuth authorization and identity mapping
invitation, bootstrap, token issue, expiry, and revocation
HTTP and MCP authentication/authorization decisions
source capture, upload, ingestion, and evidence access
query-plan validation and repair
graph traversal and deterministic exact execution
access requests and grants
candidate review and canonical commits
projection and external write proposals
```

Audit records use safe identifiers, reason codes, hashes, timestamps, and
revision lineage. Raw bearer tokens, authorization codes, PKCE verifiers,
Google tokens, secrets, raw request bodies, private source text, paths, SQL, and
full third-party responses are forbidden.

Audit failure cannot yield an unaudited success or partial mutation.

## 13. Local Compatibility Boundary

`ManualTrustedInternalAuthProvider`, JSON-line commands, the hand-built
JSON-RPC runner, stdio session variables, fixture stores, and local HTTP upload
harnesses are test/local compatibility only. They are never documented as
connected ChatGPT authentication or identity-selection paths.

Safe compatibility reports use hashes, statuses, counts, and explicit claim
boundaries. They do not prove live ChatGPT, OAuth, public TLS, production
PostgreSQL, source completeness, KG superiority, or production readiness.

## 14. Issue and Methodology Boundary

Issue #20 owns the connected Google-backed OAuth bridge and fresh
`ActorContext`. Its repository implementation does not prove the remaining
external deployment and reviewer gates, so Issue #20 remains open.

Issue #41 owns generic Asset tenant/owner binding, byte storage, occurrence,
recovery, retention, purge, transfer, and authorization.

GitHub issue #56 owns the graph-guided Hybrid KG + Ontology v2 methodology.
Before methodology-quality UAT, comparison, or completion:

```sh
python3 scripts/methodology_authority_check.py --require-ready
```

A nonzero result blocks the claim. MCP tools may expose a safe blocked status,
but they may not reinterpret it as readiness or route around it.
