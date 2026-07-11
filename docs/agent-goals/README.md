# Agent Goal Registry

This directory is the durable goal registry for long-running FormOwl agents.
Session-local goal state is useful while an agent is running, but it does not
travel across machines, sessions, or tools. Repo goal files do.

## Startup Rule

Every agent should read these files after `AGENTS.md`, the work board, and
`docs/agent-roles.md`:

1. This file.
2. The goal file for its assigned role.
3. `docs/agent-goals/handoff-log.md` for recent cross-agent notes.
4. `docs/agent-goals/reviewer-gate.md` before marking reviewed work complete.

Do not add `docs/archive/` to the normal startup sequence. Open the archive only
when older proof or handoff history is required.

The goal file records the durable objective. The work board records task
completion. Git records the mergeable engineering state.

## Goal Files

- `kg-research-agent.md` - durable objective and acceptance gates for the
  Knowledge Graph Research Agent.
- `system-backbone-agent.md` - durable objective and handoff placeholder for
  the FormOwl System Backbone Agent.
- `handoff-log.md` - short chronological notes for cross-session and
  cross-machine handoffs.
- `reviewer-gate.md` - default 3-reviewer gate with Codex/GPT reviewers.
  Antigravity/Gemini through `agy` is disabled by default unless the user
  explicitly re-enables it after the local policy or platform state changes.

## Lifecycle Labels

- `active` - current operational objective can proceed.
- `active-blocked` - current operational objective exists but cannot proceed or
  cannot be claimed complete until listed blockers clear.
- `complete` - objective is achieved and verified; move detailed history to a
  dated archive during the next archival cycle.
- `immutable-history` - archived evidence only; never treat it as current
  instructions or edit it in place.

## Size And Retention Policy

- Each role goal file contains only role, current objective, status, blockers,
  and next action. Target 180 lines; archive before 250 lines.
- `handoff-log.md` keeps the latest 14 calendar days and at most 300 lines.
  Archive the oldest complete dated entries before either limit is exceeded.
- The active work board keeps all unchecked work, current phase summaries, and
  at most five concise recent-completion summaries. Target 400 lines; archive
  before 500 lines.
- Every archival cycle creates a new dated snapshot plus hashes under
  `docs/archive/`. Existing dated snapshots are immutable.

## Update Protocol

Update the relevant goal file when:

- Starting or resuming a long-running goal in a new session.
- Changing objective, scope, owner paths, acceptance criteria, or status.
- Hitting a blocker that another agent or user must understand.
- Finishing a meaningful slice and before pausing for token limits,
  compaction, machine changes, or manual merge.

Append a short entry to `handoff-log.md` when the update affects another agent
or future session.

## Status Vocabulary

Use these statuses consistently:

- `active` - work is in progress and not complete.
- `waiting-for-owner` - the owning agent or user must fill in missing details.
- `blocked` - progress requires external input, access, tooling, or a merge.
- `complete` - objective is achieved and verified.

Lifecycle labels describe document use; status values describe objective state.
For example, a blocked current objective uses lifecycle `active-blocked` and
status `blocked`.

Do not mark a goal `complete` unless code, tests, relevant docs, work-board
state, and canonical dev-container verification are aligned.

## Reviewer Gate

Use `docs/agent-goals/reviewer-gate.md` as the default review rule for future
completed slices. The current default is 3 effective read-only Codex/GPT
reviewers. `agy` is not part of the default gate because repeated bounded
FormOwl KG packets were rejected before execution, and a 2026-06-28 MCP route
probe found no Codex-exposed Antigravity/agy MCP tool or configured
Antigravity MCP server.

## Safety Rules

Do not put secrets, credentials, raw backend paths, raw SQL, NAS paths,
object-store admin endpoints, worker scratch paths, or private source payloads
in goal files. Use stable FormOwl identifiers, commit ids, task names, and
summaries instead.
