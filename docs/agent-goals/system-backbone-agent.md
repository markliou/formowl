# FormOwl System Backbone Agent Goal

## Lifecycle

- Label: `active`
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

`active`

Completed backbone milestone history, verification counts, reviewer decisions,
and checkpoint claim boundaries are preserved in the dated archive.

## Blockers

- Issue #39's shared MCP protocol engine, JSONL compatibility runner, explicit
  handler delegation, and effective-graph alias policy are complete in the
  current working tree.
- Integrations that consume KG acceptance state must use the supported
  `formowl_kg_eval` interface rather than direct `.formowl/kg-eval` imports.
- The KG authority harness now passes independently in clean-clone and operator
  workspaces; its explicit blocked state must not be confused with completed
  real-evidence acceptance.

## Next Action

Continue only the next explicitly assigned System Backbone issue. Preserve the
governed Mail Evidence Reading boundary from issue #21, safe MCP envelopes,
permission filtering, proposal-only writes, and no raw backend/internal leaks.
Consult the archive for detailed checkpoint history before reopening old work.
