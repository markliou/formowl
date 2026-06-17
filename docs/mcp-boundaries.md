# MCP Boundaries

<!-- Future agents: continue defining MCP boundaries in this file. Do not create another MCP boundary document unless SPEC.md is updated first. -->

MCP is an orchestration boundary, not the core data processing engine.

Project MCP and Wiki MCP are current MCP services. Future ingestion and graph services may expose MCP tools too, but heavy extraction, graph resolution, indexing, and storage work should run in FormOwl backend services.

For ChatGPT-facing deployments, MCP should expose semantic and governed operations, not infrastructure. The public or tunnel-exposed service is a FormOwl MCP Gateway. Synology NAS, PostgreSQL, MinIO or other object storage, worker services, raw file paths, and scratch directories remain internal-only.

## Single Task Surface Rule

ChatGPT-facing MCP tools should keep users in one task-oriented surface. The preferred surface is the ChatGPT conversation with structured task cards, inline actions, or embedded FormOwl widgets. If a separate page is required in Phase 0, it must be a narrow session-bound continuation of the current MCP task.

MCP tools should hide backend operation choices from normal users. They should not ask users to select storage backends, buckets, NAS paths, parser paths, worker queues, extractor implementations, database records, or job internals. The gateway and backend policies choose those details and record the decision for audit.

This boundary improves security and stability by reducing unvalidated inputs, accidental data exposure, path confusion, parser mismatch, and unaudited local files.

## Current Boundaries

```text
LLM host
  -> Project MCP for project execution context
  -> Wiki MCP for wiki draft, revision, snapshot, and publish proposal workflows
  -> formowl-contract for portable exchange objects
```

Project MCP must not generate wiki pages. Wiki MCP must not depend on project-system internals.

## Future Pipeline Tools

Recommended future MCP tools:

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

These tools should expose reviewable operations. They should not let a client or external extractor directly mutate canonical graph state.

`upload_asset_reference` must not bypass `UploadSession` intent capture for normal user uploads. It is reserved for controlled imports, migration adapters, or trusted backend references that still create asset, permission, and audit records.

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

## Phase 0 Identity Boundary

For the internal closed beta, FormOwl may use manual trusted identity selection. At MCP session start, the human selects a FormOwl user identity:

```text
select_actor(display_name_or_user_id)
```

The MCP Gateway returns the selected user, workspace memberships, active grants, and pending requests assigned to that user. The selected identity becomes `actor_user_id` for subsequent MCP calls and audit logs.

This is not production authentication. It is acceptable only for trusted internal users on the company or lab network, and it must sit behind an `AuthProvider` interface so company SSO, OIDC, SAML, or another provider can replace it later.

## Collaborative Graph Access

The effective graph for a request may include:

```text
user-owned graph
workspace graph
graph fragments currently granted to the selected user
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

The MCP Gateway and Retrieval Gateway must check selected user identity, grant validity, scope match, expiration, access count, workspace membership, and audit policy before returning a redacted snippet, rendered preview, controlled stream, metadata, or permission denial.

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

Every governance-relevant operation should be audited, including actor selection, shared graph queries, access request creation, approval, denial, grant creation, grant revocation, evidence fetch, raw asset fetch, ingestion job submission, and graph commit requests.
