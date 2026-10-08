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

## Issue #56 Current Operating Mode — user override

- The latest 2026-10-06 authorization permits up to two ordinary
  worker slots requesting `gpt-6.1-sol`/`reasoning_effort=high`, superseding earlier
  sol/xhigh and luna/max settings. This is the requested tier, not a metadata
  gate: each worker records its actual configuration as verified, unverified,
  or unavailable and continues bounded work when persisted metadata is absent.
- No descendants, duplication, or additional worker is authorized. The two-worker
  cap remains in force, but a missing or unavailable handle is not an availability
  gate. The Master is ordinarily orchestration-only; an explicit user assignment
  may authorize a bounded repository edit, and worker metadata absence does not
  block it.
- The 2026-10-06 SPEC clarification was a closed docs-only slice: A finished
  `SPEC.md` and B aligned the eight assigned current docs; Master
  orchestration-only applied to that slice. The earlier B PostgreSQL/UAT/service
  recovery is dated handoff evidence, not a standing assignment from this file.
- The UAT recovery and acceptance goal remains open. Only work explicitly bounded
  by the current user assignment may proceed; this registry grants no source,
  provider, Docker, database, index, or UAT operation by itself. Preserve dirty
  edits, unique dated evidence, archives, and checkboxes.
- The 2026-10-07 source-native fallback reader, sealed artifact, focused-test,
  and policy work is a dated assignment recorded in the handoff and work board,
  not an instruction to restart that slice. Source/hash/lineage/permission and
  honest incomplete/absence boundaries remain mandatory for later authorized work.
- Current explicit user assignments take precedence over dated completed-task
  write sets and closure/no-further-work statements. Those statements constrain
  their own slice, not later authorized work; old tasks never resume implicitly.
  Earlier CLI/source-start assignments and metadata remain historical in the
  handoff, not current permissions or current worker verification.
- Dispatch requests sol/high when available, but an unpinned or resumed handle
  may continue when explicit configuration or persisted metadata is unavailable.
  Record only safe IDs, observed model/effort, UTC timestamp and status; never
  raw paths/content, prompts or secrets. Missing/mismatched metadata is
  diagnostic `unverified`, not a blocker. Never label an unobserved fallback as
  sol/high.
- The UAT provider runtime remains pinned to `gpt-5.5` with
  `reasoning_effort=high`.
- The independent release gate remains three effective read-only Codex/GPT
  reviewers across engineering, governance/safety, and research methodology.
- `reviewer-gate.md` retains the independent acceptance and safety requirements;
  its current worker tier is synchronized to this override.
- The dated 2026-09-16 `gpt-5.5` worker setting is retained in the handoff
  history as a superseded fact, not as the current worker specification.
- Dated diagnostic results are centralized in the handoff. The later narrow
  cap-fixture repair supersedes the earlier unresolved single case; the whole
  loader module/full regression were not rerun. F841, non-green full regression,
  live UAT, three reviewers and four methodology gates remain open. Feature
  待測, overall UAT goal ACTIVE; methodology claims active-blocked, step 4 `in-progress`.

## Current Source-Recheck Contract — 待測

[SPEC §7.3.1](../../SPEC.md#731-source-neutral-evidence-double-check--待測): 2026-10-06
validated `evidence_lookup` + nonempty validated fields **ALL lack verified support**
=> one materially different same-authorized-scope recheck, subject to safety/eligibility/budgets.
Partial misses MUST be disclosed and MUST NOT trigger; source-backed blanks are verified coverage.
Empty sets resolve the validated evidence-need plan/clarify. Zero citations/status/projection
failure alone cannot trigger or establish eligibility. Eligible immutable source lookup works
without failed projection, preserving source/hash/lineage/revision/permission checks/no rebuild.
Diagnostic identity gaps separately mean incomparable. Errors stay errors; incomplete is not
absence. Feature待測/four gates/three reviewers remain open; no UAT acceptance.

## Issue #56 Operating Mode — 2026-08-18 (historical; worker model superseded 2026-09-21)

- At that time, use one Master with exactly two implementation subagents. Both
  implementation workers used `gpt-5.5` with `reasoning_effort=high`. The UAT
  provider runtime remained pinned to `gpt-5.5` with `reasoning_effort=high`.
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
