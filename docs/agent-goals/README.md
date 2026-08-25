# Agent Goal Registry

This directory is the durable active-goal registry. Session-local goal state
does not survive machines or context resets; these files do.

## Startup Rule

After `AGENTS.md`, the work board, methodology authority, and role partition,
read:

1. this file;
2. the active role goal;
3. `handoff-log.md`;
4. `reviewer-gate.md` before completion claims.

Do not add `docs/archive/` to normal startup. Archived files are immutable
history, not current instructions. A file explicitly marked “Historical” or
“Not Current Instructions” is a pointer only.

## Active Goal Files

- `kg-research-agent.md` — active-blocked issue #56 objective for the Knowledge
  Graph Research Agent.
- `system-backbone-agent.md` — active backbone objective and Issue #20/#41
  authority.
- `handoff-log.md` — bounded recent cross-session facts and next actions.
- `reviewer-gate.md` — default 3-reviewer rule.

`dual-track-uat-kg-coordinator.md` is a retired historical pointer. It is not an
active goal and must not be selected for restart.

## Issue #56 Operating Mode — 2026-08-18

- Use one Master with exactly two implementation subagents. Both subagents use
  `gpt-5.6-sol` with `reasoning_effort=ultra`.
- The Master owns global planning, work decomposition, non-overlapping write-set
  assignment, progress monitoring, loop detection, integration review, and
  final acceptance. The Master does not implement code or take over a worker's
  assigned edits; implementation work belongs to the two subagents.
- A plan has at most five steps. After it is established, update status rather
  than repeatedly rewriting scope. Change the plan only for a new blocker
  supported by evidence.
- The two workers must have disjoint write sets. If the same blocker or method
  fails repeatedly, the Master changes the decomposition, owner, or validation
  route instead of authorizing an unbounded retry loop.
- POC proof requires a real end-to-end path. API, contract, schema, or unit
  wiring by itself is not proof that the path works.
- The approximately six-hour pre-outage window on 2026-08-18 is POC-first:
  prioritize the narrowest useful end-to-end proof and defer optional
  hardening, onboarding, and broad suites until feasibility is established.
  Permission, privacy, provenance, no-secret, no-raw-path, fail-closed
  methodology authority, and honest claim boundaries are never deferred.
- See `reviewer-gate.md` for the distinction between fast POC evidence and the
  unchanged three-reviewer completion/release gate.

## Lifecycle Labels

- `active` — current objective can proceed.
- `active-blocked` — implementation may proceed, but listed gates block the
  claim or completion.
- `complete` — achieved and verified.
- `immutable-history` — archived evidence only.
- `complete-historical-pointer` — active-path filename retained only to point
  to immutable history.

## Retention

- Role goals: target at most 180 lines; archive before 250.
- Handoff log: latest 14 calendar days and at most 300 lines.
- Work board: every unchecked item, current summary, at most five concise recent
  completions; target at most 400 lines, archive before 500.
- Every archive cycle creates a new dated snapshot and hash manifest. Existing
  dated archives are never edited.

## Update Protocol

Update the active role goal when objective, scope, blocker, next action, or
status changes. Append a concise handoff when another agent or future session
must know the change.

For issue #56, plan edits follow the five-step and evidence-backed blocker rule
above. Do not use goal-file churn to create new scope or conceal repeated
failure.

Do not mark complete unless code, tests, docs, work-board state, executable
authority, and canonical dev-container verification agree for the claimed
scope.

## Reviewer Gate

Use `reviewer-gate.md`. The default is three effective read-only Codex/GPT
reviewers across engineering, governance/safety, and research methodology.
Antigravity/`agy` remains unavailable while the recorded quota suspension is
active; do not count or invoke it until the user explicitly re-enables it.

## Safety

Goal files contain stable ids, repo-relative paths, status, blockers, and safe
summaries only. Do not store secrets, private source payloads, raw paths, SQL,
backend endpoints, oracle answers, or worker/parser internals.
