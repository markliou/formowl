# MCP Boundaries

<!-- Future agents: continue defining MCP boundaries in this file. Do not create another MCP boundary document unless SPEC.md is updated first. -->

MCP is an orchestration boundary, not the core data processing engine.

The connected FormOwl MCP Gateway is the only formal ChatGPT-facing service. It
exposes OAuth metadata and authorization routes plus the exact protected
Streamable HTTP resource `/mcp` on one canonical public HTTPS origin. Project
MCP, Wiki MCP, the hand-built semantic JSON-RPC runner, JSON-line commands, and
stdio remain compatibility services for bounded local tests and workflows.

For ChatGPT-facing deployments, MCP exposes semantic and governed operations,
not infrastructure. Synology NAS, PostgreSQL, MinIO or other object storage,
worker services, raw file paths, and scratch directories remain internal-only.

## Single Task Surface Rule

ChatGPT-facing MCP tools should keep users in one task-oriented surface. The
preferred surface is the ChatGPT conversation with structured task cards,
inline actions, or embedded FormOwl widgets. If a separate page is required,
it must be a narrow session-bound continuation of the current MCP task.

MCP tools should hide backend operation choices from normal users. They should not ask users to select storage backends, buckets, NAS paths, parser paths, worker queues, extractor implementations, database records, or job internals. The gateway and backend policies choose those details and record the decision for audit.

This boundary improves security and stability by reducing unvalidated inputs, accidental data exposure, path confusion, parser mismatch, and unaudited local files.

## Current Services

```text
ChatGPT or another approved OAuth client
  -> public HTTPS FormOwl origin
  -> connected MCP Gateway
       -> /.well-known/oauth-protected-resource
       -> /.well-known/oauth-authorization-server
       -> /oauth/authorize
       -> /oauth/google/callback
       -> /oauth/token
       -> exact /mcp protected resource
       -> identity, upload, evidence, graph, access, and projection workflows
       -> internal Project MCP and Wiki MCP compatibility services where configured
       -> formowl-contract for portable exchange objects
```

Project MCP must not generate wiki pages. Wiki MCP must not depend on project-system internals.

## Current Public Semantic Tools

`python/formowl_gateway/remote.py` is the source of truth for connected MCP
descriptors and OAuth security metadata. `python/formowl_gateway/semantic.py`
defines the governed semantic schemas used by configured handlers. `whoami` is
always required; other connected tools are exposed only when their handlers are
configured. The current connected tool set is:

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

These tools should expose reviewable operations. They should not let a client or external extractor directly mutate canonical graph state.

There is currently no public raw attachment reader, raw filesystem reader,
raw database query tool, or direct canonical mutation tool. Attachments must be
registered and extracted into governed observations or mail evidence before
they can support an answer.

## Planned Tools

The following capabilities remain planned and must not be described as current:

```text
capture_current_chatgpt_session
get_upload_session
complete_upload_session
get_ingestion_job
resolve_entity_candidate
commit_candidates_to_graph
list_types
get_type
propose_type
resolve_type_candidate
commit_types
search_assets
fetch_email_thread
fetch_evidence_snippet
approve_access_request
deny_access_request
revoke_grant
```

`select_actor` is not planned for the connected service. It belongs only to
the manual-trusted test/local compatibility facade. A connected client must not
select or submit a FormOwl user, workspace, session, membership, or grant.

Internal `upload_asset_reference` flows must not bypass `UploadSession` intent
capture for normal user uploads. They are reserved for controlled imports,
migration adapters, or trusted backend references that still create asset,
permission, and audit records.

`capture_current_chatgpt_session` is a convenience shortcut for the current ChatGPT conversation. It may skip the visible upload surface, but it must not skip identity, permission scope, source account metadata, asset registration, ingestion job creation, or audit.

## Upload Session Boundary

User-initiated uploads must be represented as task-oriented `UploadSession` workflows, not infrastructure browsing workflows.

ChatGPT-facing MCP tools may:

```text
create an UploadSession from user intent and scope
return a structured upload task card
return an inline upload action, embedded widget, or internal upload link bound to exactly one UploadSession
guide source preparation for a declared ingestion profile
inspect upload and processing status
create ingestion jobs after FormOwl registers the uploaded asset
```

ChatGPT-facing MCP tools must not:

```text
ask the user to choose NAS folders, buckets, volumes, or parser paths
ask the user to choose worker queues, parser implementations, or object-store locations
expose raw storage backend names unless needed for operator diagnostics
turn the upload surface into a generic file manager
accept arbitrary file paths from the user's machine as source-of-truth locators
give source preparation instructions that are detached from an UploadSession
```

The upload surface is a controlled FormOwl surface. It may receive bytes from the user, but storage routing, object placement, asset registration, parser selection, ingestion job creation, and graph integration remain backend responsibilities.

Authentication of `open_upload_session` establishes who requested the task; it
does not complete generic Asset authorization or storage governance. Issue #41
owns tenant and owner scope, byte storage, occurrence lineage, upload recovery,
lifecycle, retention, purge, and cross-scope authorization. Issue #21 consumes
that generic boundary for mail evidence and does not define a separate identity
or storage authority.

## ChatGPT Session Capture Shortcut Boundary

ChatGPT-facing MCP tools may provide a one-step "save this conversation" action for frequent use. This action is modeled as a capture shortcut over the same governed ingestion pipeline.

The shortcut may:

```text
capture the current ChatGPT session
return a capture task card
store the session dump as an internal source artifact
register the source artifact as an Asset / RawResource
create the normal ingestion or extraction job
show processing status in the current conversation
```

The shortcut must not:

```text
create an untracked local export
ask the user to choose a raw_folder or resource folder
expose object-store or filesystem paths
turn ChatGPT memory into the source of truth
skip source account and actor attribution
skip asset registration, permission scope, or audit
```

## Connected OAuth and ActorContext Boundary

The only formal human identity flow for the connected closed beta is:

```text
public HTTPS /mcp
  -> HTTP WWW-Authenticate points to FormOwl protected-resource metadata
  -> FormOwl OAuth 2.1 authorize request for the predefined ChatGPT app client
  -> exact callback, exact resource, and PKCE S256 validation
  -> Google OIDC authorization and callback
  -> verified Google (issuer, subject) mapped through a FormOwl invitation
  -> FormOwl authorization code and resource-bound FormOwl access token
  -> current PostgreSQL token-session, user, identity, client, membership, grant, and revocation checks
  -> fresh gateway-controlled ActorContext
  -> protected MCP tool
```

Google access and ID tokens are upstream identity evidence only; they are never
accepted as FormOwl MCP bearer tokens. FormOwl remains the authority for users,
workspace memberships, client authorization, scopes, token sessions,
revocation, grants, and audit.

Every connected tool descriptor must publish OAuth `securitySchemes`, an
`outputSchema`, and safety annotations. An HTTP authentication denial must
return `WWW-Authenticate`; a protected tool authorization denial must include
`_meta["mcp/www_authenticate"]`. Denials and allowed decisions must be audited
with request, tool-call, user or unauthenticated actor, external identity,
OAuth client, token session, workspace where proven, and a machine-safe reason.
Raw bearer tokens, authorization codes, PKCE verifiers, Google tokens, and
secrets must never enter audit records or public errors.

The exact reserved callback
`https://invalid.example.invalid/formowl-discovery-only` selects a separate
public-discovery mode; it is not a second authentication mode. In that mode the
gateway ignores bearer credentials, permits only `initialize` and
`tools/list`, and returns the standard OAuth challenge for every protected
tool. It does not validate old tokens and does not write HTTP-denial or MCP
authorization audit records, because no identity or authorization decision is
allowed. OAuth authorization, Google callback completion, code exchange,
bootstrap, invitations, operator mutations, and revocation are blocked before
stateful delegates. `/readyz` remains 503 and CLI preflight exits non-zero with
`status: discovery_only`; only after configuring an exact production
`https://chatgpt.com/connector/oauth/{callback_id}`, restarting, and reaching
ready may FormOwl create identity state or run protected tools.

The predefined client ID is a stable non-secret value selected and recorded by
the deployment operator before discovery. ChatGPT app management must use that
same value if its current predefined-client UI supports entry or selection; if
it does not, the live flow stops as an external blocker. ChatGPT supplies and
displays only the exact production callback. FormOwl must never invent the ID
or claim ChatGPT generated/displayed it. This boundary retains one predefined
app client and does not claim a CIMD migration or DCR fallback.

The gateway constructs `ActorContext` from current server-side state on every
protected call. It rejects or overwrites caller-controlled identity, workspace,
session, reviewer, and grant fields before a semantic handler runs. `whoami`
returns the authenticated FormOwl user and current workspace; it is not an
identity-selection tool.

`ManualTrustedInternalAuthProvider`, JSON-line, hand-built JSON-RPC, and stdio
session environment variables are test/local compatibility surfaces only. The
connected runtime requires `FORMOWL_AUTH_MODE=oauth_google` and rejects manual
identity environment variables.

## Collaborative Graph Access

The effective graph for a request may include:

```text
user-owned graph
workspace graph
graph fragments currently granted to the authenticated actor
```

If User A asks about User B's private data and no grant exists, the MCP Gateway must not leak B's content. It should return an access-required response and create an explicit request when asked:

```text
access_required: true
owner_user_id
requestable_scope
recommended_access_level: answer_only | graph_snippet | evidence_snippet | raw_asset
```

Owner approval tools may then approve, deny, narrow, expire, or revoke the request. Grant types should be scoped, such as answer-only, graph snippet, evidence snippet, one-time raw asset access, session access, asset-scoped access, query-scoped access, or project-scoped access.

Raw access must go through FormOwl locators and permission checks:

```text
formowl://asset/{asset_id}
formowl://evidence/{evidence_id}
formowl://message/{message_id}
```

The MCP Gateway and Retrieval Gateway must check the authenticated actor, grant
validity, scope match, expiration, access count, current workspace membership,
and audit policy before returning a redacted snippet, rendered preview,
controlled stream, metadata, or permission denial.

Entity matching, access overlay, and canonical merge must remain separate MCP-level workflows:

```text
match proposal does not imply data access
data access does not imply canonical merge
canonical merge does not grant raw asset access
```

MCP tools may return match candidates, request access to another scope, or submit a merge decision for review, but no MCP query should silently merge another user's private graph into the requester graph.

## Tool Boundary Rule

External tools may write to:

```text
ObservationStore
CandidateAtomStore
ExternalGraphImport
```

Only FormOwl graph assembly may create canonical graph commits:

```text
CandidateGraph
  -> GranularityPolicyEngine
  -> EntityResolver
  -> RelationResolver
  -> CanonicalGraphCommit
```

MCP tools may request or approve these operations according to permission and review policy, but the canonical commit remains a governed backend operation.

MCP tools must not expose raw infrastructure operations:

```text
list_nas_folder(path)
read_file(path)
open_smb_path(path)
download_raw_pst(path)
mount_share()
run_parser_on_path(path)
query_postgres_raw(sql)
```

Every governance-relevant operation should be audited, including OAuth
authorization, identity mapping, invitation/bootstrap, token issue and
revocation, MCP authentication and authorization decisions, shared graph
queries, access request creation, approval, denial, grant creation, grant
revocation, evidence fetch, raw asset fetch, ingestion job submission, and
graph commit requests. Manual actor selection is audited only inside the
test/local compatibility facade.

## Issue and Evidence Boundary

Issue #20 owns the connected Google-backed OAuth bridge and fresh
gateway-controlled `ActorContext`. Its repository implementation does not by
itself prove a public HTTPS deployment, fresh-database and restart journey,
signing-key rotation, MCP Inspector interoperability, or a real ChatGPT plus
Google login. Those external gates remain required before issue #20 can close;
this document makes no production-readiness claim.

Issue #41 separately owns generic Asset tenant and owner binding, byte storage,
occurrence lineage, upload recovery, lifecycle, retention, purge, and
cross-scope authorization. Issue #21 is a downstream governed mail-evidence
consumer of that generic Asset boundary and does not create an alternate
identity, storage, or connected MCP authority.
