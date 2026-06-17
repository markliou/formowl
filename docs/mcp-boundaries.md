# MCP Boundaries

<!-- Future agents: continue defining MCP boundaries in this file. Do not create another MCP boundary document unless SPEC.md is updated first. -->

MCP is an orchestration boundary, not the core data processing engine.

Project MCP and Wiki MCP are current MCP services. Future ingestion and graph services may expose MCP tools too, but heavy extraction, graph resolution, indexing, and storage work should run in FormOwl backend services.

For ChatGPT-facing deployments, MCP should expose semantic and governed operations, not infrastructure. The public or tunnel-exposed service is a FormOwl MCP Gateway. Synology NAS, PostgreSQL, MinIO or other object storage, worker services, raw file paths, and scratch directories remain internal-only.

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
upload_asset_reference
create_ingestion_job
get_ingestion_job
list_observations
extract_graph_candidates
preview_graph_candidates
resolve_entity_candidate
commit_candidates_to_graph
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
