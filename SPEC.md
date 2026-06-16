# formowl Specification

## 1. Overview

`formowl` is a knowledge management system designed to connect ChatGPT, project management systems, and wiki/documentation systems through MCP.

The first version contains two independently maintained MCP servers:

```text id="1b5hso"
Project MCP
Wiki MCP
```

They interoperate through a shared contract package:

```text id="xlg12u"
formowl-contract
```

The goal is to keep project execution data and wiki knowledge artifacts decoupled, while preserving provenance, citations, and source traceability.

The system must be usable by people who are not software engineers. Administrative owners, project coordinators, reviewers, and process operators should be able to work through natural-language instructions and review-oriented actions. Technical mechanisms such as Git, object storage, schemas, hashes, and revision backends must remain implementation details unless an administrator explicitly asks to inspect them.

---

## 2. Core Concept

```text id="1mhwmd"
ChatGPT / LLM Host
  ?? Project MCP
  ?? Wiki MCP

Shared Contract
  ?? formowl-contract
```

Project MCP is responsible for project execution context.

Wiki MCP is responsible for knowledge artifact creation and wiki publishing lifecycle.

`formowl-contract` defines the shared data structures that allow both MCPs to exchange information without depending on each other? internal implementation.

---

## 3. Design Principles

1. Raw data is the source of truth.
2. Wiki pages are knowledge views, not source of truth.
3. LLM-generated summaries, drafts, and extracted knowledge are derived data.
4. Project management systems own execution state.
5. Wiki systems own published knowledge views.
6. Project MCP and Wiki MCP must be independently maintainable.
7. Integration between MCPs must happen through shared schemas, not direct dependencies.
8. Every generated knowledge artifact must preserve source references.
9. Any external data used to generate knowledge must be traceable.
10. Write operations must use proposal and review flows.
11. The primary user workflow must be natural-language-first and non-technical-user-friendly.
12. Technical governance mechanisms must be hidden behind task-oriented actions such as save draft, submit for review, compare changes, publish, refresh from sources, and restore.
13. Wiki artifacts are versioned knowledge views derived from raw data; they are not raw truth.
14. Regenerating a wiki artifact must create a reviewable proposal or diff, not silently overwrite reviewed or published knowledge.
15. Git may be used as a revision backend, audit mirror, or engineering workflow, but it must not be required as the user-facing wiki workflow.
16. Development, testing, and deployment must be container-first to maximize portability and avoid host-machine assumptions.
17. Python and Rust are the primary implementation languages.
18. Python is the preferred language for orchestration, MCP service glue, workflows, adapters, tests, and day-to-day debugging.
19. Rust must own heavy computing, security-sensitive logic, parsers, validators, hash/signature work, data integrity checks, concurrency-sensitive code, and any feature whose Python implementation would expose strange, hard-to-read, or hard-to-maintain syntax.
20. Rust core functionality should be exposed to Python through stable bindings so most contributors can read and debug the Python-facing API without editing Rust internals.

---

## 4. First Version Scope

The first version should prove this workflow:

```text id="lmvw9o"
ChatGPT
  ??Project MCP retrieves project/work item context
  ??ChatGPT passes context to Wiki MCP
  ??Wiki MCP generates a markdown/wiki draft
  ??Generated draft includes source references and evidence snapshots
```

Included:

```text id="ny0cw0"
Project MCP
Wiki MCP
formowl-contract
OpenProject adapter for Project MCP
Markdown draft generation for Wiki MCP
SourceRef schema
EvidenceSnapshot schema
Citation schema
PermissionScope schema
ContextPackage schema
MCP tool-call logging
Natural-language-first wiki review workflow
Wiki revision abstraction
Container-first development and deployment baseline
Python/Rust implementation policy
```

Not included in the first version:

```text id="lr46ln"
Full Jira adapter
Full knowledge graph database
Automatic wiki publishing
Automatic project write-back
Company-wide ontology
Full permission engine
Full raw data ingestion pipeline
User-facing Git workflow requirements
Host-machine-specific development requirements
```

---

## 5. Component Responsibilities

## 5.1 Project MCP

Project MCP provides project execution context from project management systems.

Initial target system:

```text id="io3tq7"
OpenProject
```

Future target systems:

```text id="5tovdn"
Jira
GitHub Issues
Linear
YouTrack
```

Project MCP owns:

```text id="o763bs"
Project lookup
Work item lookup
Work item context retrieval
Work item comments
Work item activities
Work item relations
Work item attachment metadata
Project status summary
Evidence snapshot creation for project queries
Project write proposals
```

Project MCP does not own:

```text id="90mcy1"
Wiki page generation
Markdown artifact lifecycle
Wiki publishing
Knowledge page review status
Long-form knowledge curation
```

---

## 5.2 Wiki MCP

Wiki MCP manages knowledge artifacts.

Wiki MCP must expose wiki work as natural-language and review-oriented operations. Users should not need to understand Git, branches, commits, pull requests, storage paths, schema IDs, or hash values to create, review, update, publish, or restore wiki content.

Initial target artifact format:

```text id="55bbyy"
Markdown
```

Future publishing targets:

```text id="zqz1yl"
OpenProject Wiki
Wiki.js
MkDocs
Docusaurus
Confluence
Notion
GitBook
```

Wiki MCP owns:

```text id="e8xxo9"
Markdown draft generation
Wiki page lookup
Wiki draft and revision lifecycle
Wiki page metadata
Citation embedding
Frontmatter generation
Publishing proposals
Wiki snapshot capture
Revisioned artifact store abstraction
Change comparison and restore proposals
Natural-language operation mapping
```

Wiki MCP does not own:

```text id="p4wf6l"
OpenProject API details
Jira API details
Project status interpretation
Work item state mutation
Project adapter logic
User-facing Git operations
```

---

## 5.3 formowl-contract

`formowl-contract` is a shared schema package.

It defines portable objects used by both Project MCP and Wiki MCP.

Core objects:

```text id="qv0xks"
SourceRef
ProjectRef
WorkItemRef
WikiPageRef
EvidenceSnapshot
EvidenceSnapshotRef
Citation
PermissionScope
ContextPackage
WikiRevision
MCPResultEnvelope
```

Both MCP servers must import or implement this contract.

No MCP server should depend on another MCP server? internal types.

---

## 6. Shared Data Types

## 6.1 SourceRef

`SourceRef` identifies an object in an external source system.

Example for OpenProject:

```json id="fw7kp3"
{
  "source_system": "openproject",
  "source_instance": "markliou-openproject",
  "source_type": "work_package",
  "source_id": "123",
  "source_key": "OP-123",
  "source_url": "https://openproject.example.com/work_packages/123"
}
```

Example for Jira:

```json id="bemlqg"
{
  "source_system": "jira",
  "source_instance": "team-a-jira",
  "source_type": "issue",
  "source_id": "10001",
  "source_key": "ABC-456",
  "source_url": "https://jira.example.com/browse/ABC-456"
}
```

Required fields:

```text id="vny9eh"
source_system
source_type
source_id
```

Optional fields:

```text id="u3e2mf"
source_instance
source_key
source_url
```

---

## 6.2 EvidenceSnapshot

`EvidenceSnapshot` records the external data retrieved by an MCP tool call.

It is used when retrieved project or wiki data is later used to generate a knowledge artifact.

Example:

```json id="5xp9s7"
{
  "evidence_snapshot_id": "ev_project_20260616_001",
  "mcp_server": "project-mcp",
  "tool_name": "get_work_item_context",
  "requested_by": "person_yifan",
  "source_account_id": "chatgpt:yifanliou@gmail.com",
  "captured_at": "2026-06-16T12:00:00+08:00",
  "permission_scope": {
    "scope_type": "project",
    "scope_id": "formowl",
    "visibility": "restricted"
  },
  "source_refs": [
    {
      "source_system": "openproject",
      "source_type": "work_package",
      "source_id": "123"
    }
  ],
  "request_hash": "sha256:...",
  "response_hash": "sha256:...",
  "storage_uri": "/raw/evidence/project/2026/06/16/ev_project_20260616_001/"
}
```

Recommended storage layout:

```text id="injjtr"
/raw/evidence/{source}/{yyyy}/{mm}/{dd}/{evidence_snapshot_id}/
  request.json
  response.json
  normalized.md
  metadata.json
```

---

## 6.3 Citation

A `Citation` links generated content back to a source.

```json id="olwr4r"
{
  "citation_id": "cit_001",
  "source_ref": {
    "source_system": "openproject",
    "source_type": "work_package",
    "source_id": "123"
  },
  "evidence_snapshot_id": "ev_project_20260616_001",
  "locator": {
    "type": "comment",
    "id": "activity_456"
  },
  "summary": "The work package discussion describes the retention requirement."
}
```

Rules:

```text id="ncm2lc"
Generated wiki drafts must include citations.
Citations should reference SourceRef and EvidenceSnapshot when available.
Long direct quotes should be avoided.
```

---

## 6.4 PermissionScope

`PermissionScope` describes who should be allowed to access the retrieved or generated data.

```json id="x62rtf"
{
  "scope_type": "project",
  "scope_id": "formowl",
  "visibility": "restricted",
  "inherited_from": "openproject:project:formowl"
}
```

Common scope types:

```text id="qn9q0m"
private_user
project
team
workspace
public
restricted
unknown
```

---

## 6.5 ContextPackage

`ContextPackage` is the portable data package passed between MCP tools or manually copied between workflow stages.

```json id="q8qorj"
{
  "context_package_id": "ctx_project_20260616_001",
  "context_type": "work_item_context",
  "context_markdown": "...",
  "source_refs": [
    {
      "source_system": "openproject",
      "source_type": "work_package",
      "source_id": "123"
    }
  ],
  "evidence_snapshot_ids": [
    "ev_project_20260616_001"
  ],
  "citations": [],
  "permission_scope": {
    "scope_type": "project",
    "scope_id": "formowl",
    "visibility": "restricted"
  }
}
```

---

## 6.6 WikiRevision

`WikiRevision` records one versioned state of a wiki artifact.

It is a governance object for knowledge views. It does not make the wiki page a source of truth. It records which raw evidence, source references, human actions, and backend revision were involved in producing a specific version of a page.

Git may be one backend for a `WikiRevision`, but it is only an implementation detail. A user-facing workflow should expose actions such as save draft, submit for review, compare changes, publish, refresh from sources, and restore.

Example:

```json id="wiki-revision-example"
{
  "revision_id": "rev_wiki_20260616_001",
  "page_ref": {
    "source_system": "markdown-store",
    "source_type": "markdown_page",
    "source_id": "adr-data-retention"
  },
  "parent_revision_id": "rev_wiki_20260615_001",
  "title": "Data Retention Architecture Decision",
  "status": "reviewed",
  "change_kind": "source_refresh",
  "markdown_hash": "sha256:...",
  "source_refs": [
    {
      "source_system": "openproject",
      "source_type": "work_package",
      "source_id": "123"
    }
  ],
  "evidence_snapshot_ids": [
    "ev_project_20260616_001"
  ],
  "author_id": "person_admin_owner",
  "reviewer_id": "person_process_reviewer",
  "created_at": "2026-06-16T12:00:00+08:00",
  "backend_ref": {
    "type": "database",
    "id": "wiki_revision_rows/123"
  }
}
```

Recommended statuses:

```text id="wiki-revision-statuses"
draft
reviewed
published
archived
```

Recommended change kinds:

```text id="wiki-change-kinds"
generated
regenerated
human_edit
source_refresh
publish_sync
restore
```

Recommended backend types:

```text id="wiki-backend-types"
database
git
markdown-store
openproject_wiki
confluence
notion
```

Rules:

```text id="wiki-revision-rules"
Reviewed and published wiki revisions must be immutable.
Draft revisions may be superseded, but must not overwrite reviewed or published revisions.
Refresh from raw data must create a new draft revision and a human-readable diff.
Restore must create a new revision that records the restored parent, not delete history.
Backend identifiers such as git commits must not be required in user-facing workflows.
```

---

## 6.7 MCPResultEnvelope

All MCP tool responses should follow a shared envelope format.

```json id="k01xam"
{
  "result_type": "work_item_context",
  "status": "ok",
  "data": {},
  "context_package": {},
  "source_refs": [],
  "evidence_snapshot_ids": [],
  "citations": [],
  "permission_scope": {},
  "warnings": []
}
```

Possible statuses:

```text id="k9yed0"
ok
partial
not_found
permission_denied
pending_review
error
```

---

## 7. Project MCP Tools

## 7.1 search_work_items

Search work items.

Input:

```json id="flq3ve"
{
  "query": "retention policy",
  "project_ref": {
    "source_system": "openproject",
    "source_type": "project",
    "source_id": "formowl"
  },
  "limit": 10
}
```

Output:

```json id="ufxor3"
{
  "result_type": "work_item_search_results",
  "status": "ok",
  "data": {
    "items": []
  },
  "source_refs": [],
  "evidence_snapshot_ids": [],
  "citations": []
}
```

---

## 7.2 get_work_item

Retrieve one work item.

Input:

```json id="sjzgx3"
{
  "source_ref": {
    "source_system": "openproject",
    "source_type": "work_package",
    "source_id": "123"
  }
}
```

Output data should include:

```text id="zctvvn"
title
description
status
type
priority
assignee
responsible
start_date
due_date
updated_at
source_url
source_ref
```

---

## 7.3 get_work_item_context

Retrieve work item context suitable for ChatGPT or another LLM.

Input:

```json id="2loeb7"
{
  "source_ref": {
    "source_system": "openproject",
    "source_type": "work_package",
    "source_id": "123"
  },
  "include_comments": true,
  "include_activities": true,
  "include_relations": true,
  "include_attachments": true,
  "create_evidence_snapshot": true
}
```

Output:

```json id="2knh66"
{
  "result_type": "work_item_context",
  "status": "ok",
  "data": {
    "work_item": {},
    "comments": [],
    "activities": [],
    "relations": [],
    "attachments": []
  },
  "context_package": {
    "context_package_id": "ctx_project_20260616_001",
    "context_type": "work_item_context",
    "context_markdown": "...",
    "source_refs": [
      {
        "source_system": "openproject",
        "source_type": "work_package",
        "source_id": "123"
      }
    ],
    "evidence_snapshot_ids": [
      "ev_project_20260616_001"
    ],
    "citations": []
  }
}
```

---

## 7.4 list_work_item_activities

Retrieve comments and activity history for a work item.

Input:

```json id="ha9io5"
{
  "source_ref": {
    "source_system": "openproject",
    "source_type": "work_package",
    "source_id": "123"
  },
  "limit": 50,
  "create_evidence_snapshot": true
}
```

---

## 7.5 list_work_item_relations

Retrieve related work items.

Input:

```json id="c5jp95"
{
  "source_ref": {
    "source_system": "openproject",
    "source_type": "work_package",
    "source_id": "123"
  }
}
```

---

## 7.6 get_project_status

Retrieve project-level status summary.

Input:

```json id="v0y0m7"
{
  "project_ref": {
    "source_system": "openproject",
    "source_type": "project",
    "source_id": "formowl"
  },
  "include_recent_updates": true,
  "create_evidence_snapshot": true
}
```

---

## 7.7 propose_work_item_comment

Prepare a project-system comment write proposal.

This tool must not write directly.

Input:

```json id="btxggc"
{
  "source_ref": {
    "source_system": "openproject",
    "source_type": "work_package",
    "source_id": "123"
  },
  "body": "Proposed comment text",
  "reason": "Generated from reviewed wiki draft"
}
```

Output:

```json id="twogq8"
{
  "result_type": "write_proposal",
  "status": "pending_review",
  "data": {
    "proposal_id": "proposal_comment_001",
    "target_source_ref": {
      "source_system": "openproject",
      "source_type": "work_package",
      "source_id": "123"
    },
    "diff_markdown": "..."
  }
}
```

---

## 8. Wiki MCP Tools

## 8.1 search_wiki_pages

Search existing wiki or markdown pages.

Input:

```json id="ddp37i"
{
  "query": "retention architecture",
  "project": "formowl",
  "limit": 10
}
```

---

## 8.2 get_wiki_page

Retrieve one wiki or markdown page.

Input:

```json id="xgjwgd"
{
  "page_ref": {
    "wiki_system": "markdown-store",
    "page_id": "adr-data-retention"
  }
}
```

---

## 8.3 generate_wiki_draft

Generate a markdown draft from a context package.

Input:

```json id="ci02tc"
{
  "page_type": "adr",
  "title": "Data Retention Architecture Decision",
  "context_package": {
    "context_package_id": "ctx_project_20260616_001",
    "context_type": "work_item_context",
    "context_markdown": "...",
    "source_refs": [
      {
        "source_system": "openproject",
        "source_type": "work_package",
        "source_id": "123"
      }
    ],
    "evidence_snapshot_ids": [
      "ev_project_20260616_001"
    ],
    "citations": []
  }
}
```

Output:

```json id="e3hitw"
{
  "result_type": "wiki_draft",
  "status": "ok",
  "data": {
    "draft_id": "draft_adr_001",
    "markdown": "...",
    "frontmatter": {}
  },
  "source_refs": [
    {
      "source_system": "openproject",
      "source_type": "work_package",
      "source_id": "123"
    }
  ],
  "evidence_snapshot_ids": [
    "ev_project_20260616_001"
  ],
  "citations": []
}
```

---

## 8.4 update_wiki_draft

Update an existing markdown draft.

Input:

```json id="vk0eri"
{
  "draft_id": "draft_adr_001",
  "patch": {
    "status": "reviewed",
    "content": "..."
  }
}
```

---

## 8.5 publish_wiki_page

Prepare a wiki publishing proposal.

This tool must not publish directly unless explicit auto-publish mode is configured.

Input:

```json id="4uph5b"
{
  "draft_id": "draft_adr_001",
  "target": {
    "target_system": "openproject_wiki",
    "project_id": "formowl",
    "page_slug": "data-retention-architecture"
  },
  "require_review": true
}
```

Output:

```json id="ppbpz5"
{
  "result_type": "publish_proposal",
  "status": "pending_review",
  "data": {
    "proposal_id": "publish_proposal_001",
    "target": {
      "target_system": "openproject_wiki",
      "project_id": "formowl",
      "page_slug": "data-retention-architecture"
    },
    "diff_markdown": "..."
  }
}
```

---

## 8.6 capture_wiki_snapshot

Capture a wiki page as raw source.

Input:

```json id="y9xn2q"
{
  "page_ref": {
    "wiki_system": "openproject_wiki",
    "page_id": "data-retention-architecture"
  }
}
```

---

## 8.7 Wiki Revision Governance

Wiki MCP must treat wiki revisions as governed knowledge views.

The user-facing operation should be natural-language-first. The system may translate requests into structured tool calls, but users should be able to express work like:

```text id="wiki-natural-language-ops"
Update this SOP using the latest OpenProject discussion.
Show me what changed before I approve it.
Publish this reviewed page to the project wiki.
Restore the previous approved version.
Refresh this page from source data, but keep my manual notes.
```

These user actions map to technical operations behind the scenes:

```text id="wiki-op-mapping"
save draft -> create or update a draft WikiRevision
submit for review -> mark a draft revision pending review
compare changes -> generate a human-readable diff between revisions
approve -> mark a revision reviewed
publish -> create a publish proposal and record the target backend revision
refresh from sources -> generate a new draft revision from raw evidence and show a diff
restore -> create a new revision from a previous reviewed or published revision
```

Future Wiki MCP tools may include:

```text id="wiki-future-revision-tools"
list_wiki_revisions
compare_wiki_revisions
propose_wiki_refresh
restore_wiki_revision
```

MVP implementations may model these through `generate_wiki_draft`, `update_wiki_draft`, `publish_wiki_page`, and an internal revision store.

Git-specific operations such as commit, branch, pull request, merge, or rebase must not be required from normal wiki authors. If Git is used, the system should create commits or pull requests on behalf of the workflow and expose them only as optional audit details.

---

## 9. Markdown Frontmatter Standard

Every generated markdown page must include frontmatter.

Example:

```yaml id="21j7uv"
---
title: Data Retention Architecture Decision
type: adr
status: draft
revision_id: rev_wiki_20260616_001
parent_revision_id: rev_wiki_20260615_001
change_kind: source_refresh
project: formowl
owner: null
generated: true
generated_by: chatgpt
review_status: pending
created_at: 2026-06-16T12:00:00+08:00
last_reviewed: null

source_refs:
  - source_system: openproject
    source_type: work_package
    source_id: "123"
    source_url: "https://openproject.example.com/work_packages/123"

evidence_snapshot_ids:
  - ev_project_20260616_001

related_work_items:
  - source_system: openproject
    source_type: work_package
    source_id: "123"

citations:
  - citation_id: cit_001
    evidence_snapshot_id: ev_project_20260616_001
    source_system: openproject
    source_type: work_package
    source_id: "123"

permission_scope:
  scope_type: project
  scope_id: formowl
  visibility: restricted

revision_backend:
  type: database
  id: wiki_revision_rows/123
---
```

---

## 10. ChatGPT Session Capture

ChatGPT session capture uses the same provenance model.

A captured ChatGPT session must include source account metadata.

Minimum capture metadata:

```json id="wwd8d3"
{
  "capture_id": "cap_20260616_chatgpt_yifan_001",
  "source_system": "chatgpt",
  "source_account_id": "chatgpt:yifanliou@gmail.com",
  "source_account_identity_hash": "sha256:...",
  "capture_method": "manual_export",
  "captured_by": "person_yifan",
  "captured_at": "2026-06-16T10:30:00+08:00",
  "ingested_at": "2026-06-16T10:35:00+08:00",
  "permission_scope": "private:user_yifan",
  "raw_folder": "/raw/sessions/chatgpt/2026/06/16/session-id/",
  "manifest_hash": "sha256:..."
}
```

User message record:

```json id="5yjvec"
{
  "session_id": "session-20260616-km",
  "capture_id": "cap_20260616_chatgpt_yifan_001",
  "message_id": "001",
  "sequence_id": 1,
  "role": "user",
  "actor_type": "human",
  "actor_id": "person_yifan",
  "actor_source": "source_account",
  "source_account_id": "chatgpt:yifanliou@gmail.com",
  "timestamp": null,
  "content": "???潸??冽?",
  "attachments": [],
  "authorship": {
    "message_author": "person_yifan",
    "verification_level": "source_account_attributed"
  }
}
```

Assistant message record:

```json id="kth9i3"
{
  "session_id": "session-20260616-km",
  "capture_id": "cap_20260616_chatgpt_yifan_001",
  "message_id": "002",
  "sequence_id": 2,
  "role": "assistant",
  "actor_type": "ai_model",
  "actor_id": "openai_chatgpt",
  "source_account_id": "chatgpt:yifanliou@gmail.com",
  "model": "unknown-or-captured-model",
  "content": "LLM ???冽?",
  "authorship": {
    "message_author": "openai_chatgpt",
    "generated_for_account": "chatgpt:yifanliou@gmail.com",
    "verification_level": "platform_generated"
  }
}
```

Rule:

```text id="w3md25"
A ChatGPT raw session without source_account_id must not enter the verified raw data pool.
It may only enter an unverified import queue.
```

---

## 11. Workflow Examples

## 11.1 Project Context to Wiki Draft

```text id="kscw3h"
User:
  ?寞? OpenProject #123 ?Ｙ? ADR wiki draft??
ChatGPT:
  1. Calls Project MCP: get_work_item_context(OP #123)
  2. Receives ContextPackage
  3. Calls Wiki MCP: generate_wiki_draft(ContextPackage)
  4. Returns markdown draft to user
```

---

## 11.2 Staged Workflow

If only one MCP is available at a time:

```text id="hrgbnr"
Stage 1:
  Use Project MCP to generate ContextPackage.

Stage 2:
  Use Wiki MCP to generate markdown from ContextPackage.
```

The handoff object is:

```json id="m35tij"
{
  "context_package_id": "ctx_project_20260616_001",
  "context_type": "work_item_context",
  "context_markdown": "...",
  "source_refs": [],
  "evidence_snapshot_ids": [],
  "citations": [],
  "permission_scope": {}
}
```

---

## 12. Observability

Every MCP tool call must be logged.

Minimum log fields:

```json id="1l0rs6"
{
  "event_type": "mcp_tool_call",
  "server_name": "project-mcp",
  "tool_name": "get_work_item_context",
  "request_id": "req_001",
  "conversation_id": "optional",
  "user_id": "optional",
  "source_account_id": "optional",
  "called_at": "2026-06-16T12:00:00+08:00",
  "arguments_hash": "sha256:...",
  "response_hash": "sha256:...",
  "status": "ok",
  "latency_ms": 1200,
  "evidence_snapshot_id": "ev_project_20260616_001"
}
```

Logs must support answering:

```text id="mf4hll"
Which MCP tool was called?
When was it called?
Which user or source account triggered it?
Which evidence snapshot was created?
Which wiki draft used which evidence snapshot?
Did ChatGPT use Project MCP and Wiki MCP in the same workflow?
```

---

## 13. Runtime, Language, and Container Policy

FormOwl must be container-first.

The canonical development, test, and deployment environment is a container image. Local host tooling may be used for convenience, but it must not become a hidden requirement for contributors or operators.

Container requirements:

```text id="container-policy"
Container images must include the required Python runtime, Rust toolchain, binding build tools, and service dependencies.
MCP servers must be runnable from containers without requiring host-installed Python, Rust, Node, TypeScript, or system libraries.
Development containers should support repeatable local testing, linting, and binding builds.
Production containers should prefer small runtime images and explicit dependency pinning.
Compose or equivalent local orchestration should be available for Project MCP, Wiki MCP, raw data storage, and metadata storage when those services exist.
```

Primary implementation languages:

```text id="language-policy"
Python
Rust
```

Python owns:

```text id="python-owns"
MCP server orchestration
External service adapters
Workflow logic
Natural-language operation mapping
Review and proposal flow glue
Configuration loading
Test fixtures and integration tests
Day-to-day debugging entrypoints
Human-readable diagnostics
```

Rust owns:

```text id="rust-owns"
Heavy computing
Security-sensitive logic
Parsers and canonical serializers
Schema and policy validation cores
Hashing, signing, and integrity checks
Concurrent or memory-sensitive processing
Large raw data transforms
Diff engines when correctness or performance matters
Sandbox-like boundaries
Any feature whose Python implementation would expose strange, hard-to-read, or hard-to-maintain syntax
```

Syntax shielding rule:

```text id="syntax-shielding-rule"
If a Python implementation would require unusual metaprogramming, deeply nested decorators, generated code, fragile regular expressions, complex DSLs, unsafe dynamic evaluation, or other syntax that ordinary maintainers should not be expected to read and edit, that feature must be implemented behind a Rust core API.
The Python layer should expose clear functions, classes, and typed data objects.
Normal debugging should start from Python.
Rust internals should be inspected only when debugging the core algorithm, safety boundary, or binding itself.
```

Python/Rust binding policy:

```text id="binding-policy"
Rust core libraries should expose stable Python bindings.
The preferred binding stack is PyO3 plus maturin.
Python wrappers must hide Rust memory, lifetime, ownership, and build details from normal workflow code.
Bindings must return contract-shaped data structures or simple Python objects.
Binding failures must produce actionable Python exceptions with enough context for non-Rust debugging.
```

This policy does not mean all difficult code belongs in Rust. Business workflows, connector logic, review state machines, and user-facing orchestration should remain in Python when the Python version is clear, debuggable, and safe enough.

---

## 14. Suggested Repository Layout

```text id="cf1xgs"
formowl/
  README.md
  SPEC.md
  LICENSE
  Containerfile
  compose.yaml
  pyproject.toml
  Cargo.toml

  .devcontainer/
    devcontainer.json

  containers/
    dev/
      Containerfile
    runtime/
      Containerfile

  schemas/
    source-ref.schema.json
    evidence-snapshot.schema.json
    citation.schema.json
    permission-scope.schema.json
    context-package.schema.json
    wiki-revision.schema.json
    mcp-result-envelope.schema.json

  python/
    formowl_contract/
      __init__.py
      models.py

    formowl_project_mcp/
      README.md
      formowl_project_mcp/
        server.py
        tools/
          search_work_items.py
          get_work_item.py
          get_work_item_context.py
          list_work_item_activities.py
          list_work_item_relations.py
          get_project_status.py
          propose_work_item_comment.py
        adapters/
          openproject/
            client.py
            mapper.py
            schemas.py
        storage/
          evidence_snapshot_store.py
        observability/
          logger.py

    formowl_wiki_mcp/
      README.md
      formowl_wiki_mcp/
        server.py
        tools/
          search_wiki_pages.py
          get_wiki_page.py
          generate_wiki_draft.py
          update_wiki_draft.py
          publish_wiki_page.py
          capture_wiki_snapshot.py
        markdown/
          frontmatter.py
          templates/
            adr.md
            project-hub.md
            meeting-notes.md
            decision-log.md
            risk-register.md
        storage/
          draft_store.py
          wiki_snapshot_store.py
        observability/
          logger.py

  crates/
    formowl-core/
      Cargo.toml
      src/
        lib.rs
        validation/
        hashing/
        diff/

    formowl-python-bindings/
      Cargo.toml
      pyproject.toml
      src/
        lib.rs

  docs/
    architecture.md
    mcp-boundaries.md
    provenance.md
    workflows.md
    openproject-adapter.md
    wiki-draft-schema.md

  examples/
    context-package.json
    wiki-draft-input.json
    generated-adr.md

  tests/
    contract/
    project-mcp/
    wiki-mcp/
    rust-core/
    integration/
```

---

## 15. README Summary

```md id="3mp5w0"
# formowl

formowl is a source-preserving knowledge management system built around two decoupled MCP servers:

- Project MCP
- Wiki MCP

Project MCP retrieves project execution context from systems such as OpenProject.

Wiki MCP generates and manages markdown/wiki knowledge artifacts.

Both MCPs interoperate through `formowl-contract`, which defines shared schemas for source references, evidence snapshots, citations, permission scopes, and context packages.

FormOwl is container-first. The canonical development, test, and runtime environment is provided by containers.

The primary implementation languages are Python and Rust. Python owns readable orchestration and debugging. Rust owns heavy computing, safety-sensitive logic, and syntactically complex core functionality exposed to Python through bindings.

## Core Principle

Project systems own execution state.

Wiki systems own published knowledge views.

Raw data and evidence snapshots preserve source traceability.
```

---

## 16. Implementation Order

Recommended order:

```text id="994n05"
1. Create container-first monorepo skeleton
2. Implement formowl-contract JSON schemas
3. Add Python contract models generated or validated from schemas
4. Add Rust core crate for validation, hashing, diffing, and safety-sensitive utilities
5. Expose Rust core to Python through bindings
6. Implement Project MCP with mocked OpenProject data in Python
7. Implement EvidenceSnapshot storage
8. Implement Wiki MCP draft generator in Python
9. Add markdown frontmatter provenance
10. Add MCP tool-call logging
11. Test Rust core independently
12. Test Python bindings independently
13. Test Project MCP independently
14. Test Wiki MCP independently
15. Test Project MCP to ContextPackage to Wiki MCP workflow
16. Add real OpenProject adapter
```

---

## 17. Acceptance Criteria

The first version is usable when:

```text id="8fvc4g"
Project can be developed and tested inside a container.
Project does not require host-installed Python, Rust, Node, or TypeScript for normal development.
Python is the primary debugging entrypoint for MCP behavior.
Rust core can be called from Python through bindings.
Project MCP can return a ContextPackage for an OpenProject work package.
Project MCP can persist an EvidenceSnapshot.
Wiki MCP can generate a markdown draft from a ContextPackage.
Generated markdown includes source_refs and evidence_snapshot_ids.
Both MCPs can be tested independently.
Tool-call logs show when Project MCP and Wiki MCP are called.
Project-system writes are proposal-only.
Wiki publishing is proposal-only unless explicitly configured otherwise.
```

---

## 18. Non-Goals

```text id="qpfu4w"
Do not make Wiki MCP depend on OpenProject internals.
Do not make Project MCP generate wiki pages.
Do not assume ChatGPT always exposes every workspace MCP in every session.
Do not allow automatic project-system writes without approval.
Do not treat LLM-generated output as source of truth.
Do not require a full knowledge graph database in the first version.
Do not require non-engineering wiki authors to use Git or inspect backend revision IDs.
Do not require contributors to install host-level runtimes when a container can provide them.
Do not implement hard-to-read Python syntax when a Rust core API can hide the complexity.
```

---

## 19. Final Architecture Statement

formowl uses two decoupled MCP servers:

```text id="kbd0ln"
Project MCP = project execution context
Wiki MCP = knowledge artifact lifecycle
```

They interoperate through:

```text id="7119o7"
SourceRef
EvidenceSnapshot
Citation
PermissionScope
ContextPackage
MCPResultEnvelope
```

The runtime policy is:

```text id="runtime-policy-summary"
Container first
Python for readable orchestration and debugging
Rust for heavy, safety-sensitive, or syntactically complex core logic
Python bindings over Rust core APIs
```

The system prioritizes maintainability, portability, provenance, source traceability, and non-technical-user-friendly operation.
