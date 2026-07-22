# FormOwl System Backbone Agent Goal

## Lifecycle

- Label: `active-blocked`
- Lossless history: `../archive/2026-07-11/system-backbone-agent.md`
- Retention: keep role, current objective, status, blockers, and next action
  only; target at most 180 lines and archive before 250 lines.

## Role

FormOwl System Backbone Agent. Durable role definition: `../agent-roles.md`.

## Current Objective

Maintain and extend the system backbone behind the accepted FormOwl contracts:
service, storage, transport, adapter, worker, governed retrieval, mail evidence,
and Wiki proposal plumbing. Do not claim production readiness from completed
prototype or deterministic evaluation checkpoints.

## Status

`blocked`

Completed backbone milestone history, verification counts, reviewer decisions,
and checkpoint claim boundaries are preserved in the dated archive.

## Blockers

- Final local authority is 689/689/689 changed/manifested/onboarded,
  509/509/509/509 requested/resolved/run/pass, 1,390 checked evidence pairs,
  direct trace expected/covered 689/689 with missing 0 and blockers `[]`, and
  `test_id_count` 1,521. Pending, binding mismatch, validator, resolution, and
  execution blocker counts are zero.
- Repository implementation includes Google-backed FormOwl OAuth, exact
  stateless Streamable HTTP `/mcp`, PostgreSQL OAuth/audit persistence,
  operator and migration flows, fixed 3600-second token lifetime, fixed
  30-second validation skew, and fresh gateway-controlled `ActorContext`.
- The operator records one stable non-secret predefined client ID before
  discovery. ChatGPT supplies and displays only the exact callback. If the
  current app UI cannot use that predefined ID, the live flow stops as an
  external blocker.
- The retrieval audit timestamp and semantic mapping-key collision fixes are
  included in the current source and must remain covered by their focused
  tests and regenerated manifest evidence.
- All required external layers remain `not_supplied`: `live_postgresql`,
  `operator_cli_postgresql`, `production_container_lifecycle`, `mcp_inspector`,
  `live_chatgpt_google`, `reviewer_gate`, and `completion_audit`. Issue #20
  remains open and no production-readiness claim is supported.

## Next Action

Freeze the post-cleanup source and regenerate local authority, then run the governed
`live_postgresql`, `operator_cli_postgresql`,
`production_container_lifecycle`, `mcp_inspector`, and
`live_chatgpt_google` campaigns with the operator-recorded predefined client ID
and ChatGPT-displayed callback; stop if app management cannot use that same ID.
Prepare the frozen-source Issue-wide
`reviewer_gate` packet only after those campaigns, then run the independent
`completion_audit`. Keep Issue #20 open until all seven layers agree.
