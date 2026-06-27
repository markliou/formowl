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

The goal file records the durable objective. The work board records task
completion. Git records the mergeable engineering state.

## Goal Files

- `kg-research-agent.md` - durable objective and acceptance gates for the
  Knowledge Graph Research Agent.
- `system-backbone-agent.md` - durable objective and handoff placeholder for
  the FormOwl System Backbone Agent.
- `handoff-log.md` - short chronological notes for cross-session and
  cross-machine handoffs.
- `reviewer-gate.md` - default 6-reviewer gate with 3 Codex/GPT reviewers and
  3 Antigravity Gemini reviewers through the local `agy` CLI.

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

Do not mark a goal `complete` unless code, tests, relevant docs, work-board
state, and canonical dev-container verification are aligned.

## Reviewer Gate

Use `docs/agent-goals/reviewer-gate.md` as the default review rule for future
completed slices. The current default is 6 effective read-only reviewers: 3
Codex/GPT reviewers and 3 Antigravity Gemini reviewers called through the real
local `agy` CLI.

## Safety Rules

Do not put secrets, credentials, raw backend paths, raw SQL, NAS paths,
object-store admin endpoints, worker scratch paths, or private source payloads
in goal files. Use stable FormOwl identifiers, commit ids, task names, and
summaries instead.
