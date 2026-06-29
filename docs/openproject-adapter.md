# OpenProject Adapter

<!-- Future agents: continue building OpenProject adapter documentation in this file. Do not create another OpenProject adapter document unless SPEC.md is updated first. -->

The OpenProject adapter is the Project MCP boundary for real OpenProject API v3
reads. It normalizes OpenProject HAL+JSON into the same structures returned by
the mock adapter so `ProjectMcpTools` can keep emitting stable MCP envelopes,
evidence snapshots, and context packages.

## Configuration

The default Project MCP server still uses `MockOpenProjectAdapter` unless a
caller explicitly wires the real adapter. The real adapter can be built from
environment variables:

```python
from formowl_project_mcp.adapters.openproject import OpenProjectAdapter

adapter = OpenProjectAdapter.from_env()
```

Supported environment variables:

| Variable | Required | Purpose |
| --- | --- | --- |
| `FORMOWL_OPENPROJECT_BASE_URL` | yes | OpenProject origin, for example `https://openproject.example.com`. |
| `FORMOWL_OPENPROJECT_API_TOKEN` | no | API token for authenticated reads. |
| `FORMOWL_OPENPROJECT_AUTH_SCHEME` | no | `bearer` by default; `basic` uses username `apikey`; `none` sends no authorization header. |
| `FORMOWL_OPENPROJECT_SOURCE_INSTANCE` | no | Stable FormOwl source instance name. Defaults to `openproject`. |
| `FORMOWL_OPENPROJECT_TIMEOUT_SECONDS` | no | HTTP timeout in seconds. Defaults to `30`. |

The client uses Python standard-library `urllib` and accepts an injected opener
for tests or custom transport policy. It sends `GET` requests only.

## Auth

OpenProject API v3 supports API tokens as bearer tokens and through Basic Auth.
For Basic Auth, OpenProject expects username `apikey` and the API token as the
password. OAuth and browser session authentication are intentionally outside
this initial adapter.

Do not put live credentials in tests, docs examples, or checked-in config.

## Read Mapping

The adapter exposes the shape consumed by `ProjectMcpTools`:

- `search_work_items(input_data)`
- `get_work_item(source_ref)`
- `get_work_item_context(input_data)`
- `list_work_item_activities(input_data)`
- `list_work_item_relations(input_data)`
- `get_project_status(input_data)`
- `resolve_project_ref(project_ref)`

OpenProject work packages map to normalized work items:

- `subject` -> `title`
- `description.raw` -> `description`
- `_links.status.title` -> `status`
- `_links.type.title` -> `type`
- `_links.priority.title` -> `priority`
- `_links.assignee.title` -> `assignee`
- `_links.responsible.title` -> `responsible`
- `startDate`, `dueDate`, and `updatedAt` keep their OpenProject timestamps or
  date strings
- `_links.project.href` becomes a restricted project `permission_scope`
- work package IDs become `source_ref.source_id`; `source_ref.source_key` is a
  stable `OP-{id}` FormOwl key

Activities are read from `/api/v3/work_packages/{id}/activities`. Activities
with `comment.raw` also produce normalized comments. Non-comment activity
details are flattened into a readable activity body when OpenProject provides a
`raw` detail string.

Relations are read from `/api/v3/work_packages/{id}/relations` or the
work-package relation link. The mapper chooses the opposite work package as
`target_ref` when the requested work package appears on either side of the
relation. Each relation also carries `relation_source_ref` so evidence snapshots
can trace the relation resource itself in addition to the source and target work
packages.

Attachments are read from `/api/v3/work_packages/{id}/attachments` or the
work-package attachments link. Metadata is normalized to `attachment_id`,
`file_name`, `content_type`, `size_bytes`, `source_url`, and `source_ref`.
Attachment downloads are not fetched.

Project status reads a project, then its work package collection, and returns:

- `project_ref`
- `summary_markdown`
- `status_counts`
- `recent_updates`
- `source_refs`

## Write Policy

This adapter intentionally implements no live OpenProject writes. Project-system
write behavior remains proposal-only through Project MCP tools such as
`propose_work_item_comment`, which returns `pending_review` and does not call
OpenProject.

## Tests

`tests/test_openproject_adapter.py` uses a fake urllib opener. The tests assert
request paths, auth headers, query parameters, and normalized outputs without
network access or live OpenProject credentials.

The work-board item remains unchecked until the main agent completes strict
hardening/reviewer-gate verification and full canonical dev-container checks.
