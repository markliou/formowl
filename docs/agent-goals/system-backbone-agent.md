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

- Issue #20 repository authority is locally complete: 689 changed, 689
  manifested, and 689 onboarded functions. Pending, missing, extra, duplicate,
  source-binding mismatch, N/A hygiene, and validator blocker counts are zero.
- Final local authority is 689/689/689 changed/manifested/onboarded,
  508/508/508/508 requested/resolved/run/pass, 1,388 checked evidence pairs,
  direct trace expected/covered 689/689 with missing 0 and blockers `[]`, and
  `test_id_count` 1,521. Skips, failures, errors, resolution/execution blockers,
  and validator blockers are zero.
- Cross-UID failure-diagnostic custody now uses a validated inner mode-`0444`
  ephemeral handoff and runner-owned mode-`0400` final diagnostic. Operator
  28/28, runner 38/38, target harness 25/25 across 51 pairs, target trace 33/33,
  and canonical static checks pass. The original governance reviewer closed
  the finding with a finding-specific 1/1 `RELEASE_DECISION: AGREE`; author and
  verification-only agents do not count, and the existing connected-operator
  batch reviewer gate remains 3/3.
- `_runtime_data_stores_ready()` no longer returns from `finally`.
  `tests.test_connected_runtime.ConnectedRuntimeLifecycleTests.test_upload_store_readiness_probe_is_atomic_clean_and_fail_closed`
  proves cleanup after descriptor-close failure and fail-closed readiness;
  focused runtime verification passes 36/36.
- The implementation contract binds tracked deploy templates and examples,
  including `Caddyfile.example`, `compose.env.example`, operator config,
  secret guidance, and signing-key example, rather than ignored operator-local
  Caddy/env copies. The real BuildKit regression proves the current source and
  frozen snapshot produce the same implementation-contract hash.
- Finalization computation faults are converted into one generic failed
  validation result instead of leaking computation detail or escaping the CLI;
  the strengthened regression and onboarding-manifest update are included in
  the final harness authority.
- The canonical full suite is `Ran 1521 tests in 964.613s`,
  `OK (skipped=7)`. Ruff check passed; Ruff format reports 306 files already
  formatted; runner shell syntax, JSON parse, and `git diff --check` passed.
- Latest harness artifact:
  `/tmp/formowl-issue20-postfix-local-harness-20260721T100124Z.json`, SHA-256
  `1adaeaf752148e730f421e0e385b0faa4a1aef4273d437def902bdb212e352b1`.
- Connector-confirmed GitHub current main remains
  `342e588aa6162ccbdd14a257bfc09e58e7a619ad`; no newer remote main was
  reported. This is source-baseline context, not external completion evidence.
- Three earlier read-only source reviewers agreed the repository was ready for
  a fresh external campaign, but their reviews predate the final
  warning/snapshot cleanup and do not satisfy the Issue-wide reviewer layer.
- All required external layers remain `not_supplied`: `live_postgresql`,
  `operator_cli_postgresql`, `production_container_lifecycle`, `mcp_inspector`,
  `live_chatgpt_google`, `reviewer_gate`, and `completion_audit`. Issue #20
  remains open and no production-readiness claim is supported.
- The clean-clone operator contract now has a tracked non-secret Compose env
  template, ignored operator copy workflow, Caddy loopback TLS sample, exact
  discovery stop-before-migrate sequence, official public-only `npx` Inspector
  command, and container-first evidence commands. The operator records one safe
  non-secret predefined client ID before discovery; ChatGPT app management must
  use that same ID and supplies only the callback. Missing predefined-client UI
  support, public TLS/domain, Google credentials/accounts, and all live
  campaigns remain external prerequisites or blockers.
- Issue #41 still owns generic Asset tenant/owner binding, byte storage,
  occurrence lineage, lifecycle, retention, purge, and authorization. Issue
  #21 remains a governed downstream mail-evidence consumer.

## Next Action

Freeze the final docs and local harness authority, then run the governed
`live_postgresql`, `operator_cli_postgresql`,
`production_container_lifecycle`, `mcp_inspector`, and
`live_chatgpt_google` campaigns with the operator-recorded predefined client ID
and ChatGPT-displayed callback; stop if app management cannot use that same ID.
Prepare the frozen-source Issue-wide
`reviewer_gate` packet only after those campaigns, then run the independent
`completion_audit`. Keep Issue #20 open until all seven layers agree.

Campaign prerequisite: freeze the final post-cleanup source, preserve stale
scratch as non-authoritative history, and run all eight local stages in order.
The Issue-wide reviewer packet must be freshly generated after that freeze.
