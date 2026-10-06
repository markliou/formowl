# FormOwl Durable History Archive

Lifecycle label: `immutable-history`.

This directory contains lossless snapshots moved out of bounded startup files.
Active operational state remains in `docs/implementation-task-breakdown.md` and
`docs/agent-goals/`. Archived files are historical evidence, not current task or
role instructions.

## Snapshot 2026-07-11

- [`implementation-task-breakdown.md`](2026-07-11/implementation-task-breakdown.md)
- [`kg-research-agent.md`](2026-07-11/kg-research-agent.md)
- [`system-backbone-agent.md`](2026-07-11/system-backbone-agent.md)
- [`handoff-log.md`](2026-07-11/handoff-log.md)
- [`manifest.json`](2026-07-11/manifest.json) records source paths, byte counts,
  line counts, and SHA-256 hashes for mechanical comparison.

## Snapshot 2026-07-16

- [`handoff-log.md`](2026-07-16/handoff-log.md) preserves the complete
  300-line active handoff log immediately before the retention trim.
- [`manifest.json`](2026-07-16/manifest.json) records its source path, byte
  count, line count, and SHA-256 hash for mechanical comparison.

## Snapshot 2026-07-19

- [`handoff-log.md`](2026-07-19/handoff-log.md) preserves the complete
  300-line active handoff log immediately before the retention trim.
- [`manifest.json`](2026-07-19/manifest.json) records its source path, byte
  count, line count, and SHA-256 hash for mechanical comparison.

## Snapshot 2026-07-21

- [`handoff-log.md`](2026-07-21/handoff-log.md) preserves the byte-identical
  298-line task-start active handoff log before the 2026-07-21 update.
- [`manifest.json`](2026-07-21/manifest.json) records its source path, byte
  count, line count, and SHA-256 hash for mechanical comparison.

## Snapshot 2026-08-13

- [`dual-track-uat-kg-coordinator.md`](2026-08-13/dual-track-uat-kg-coordinator.md)
  preserves the complete coordinator goal immediately before the UAT restart
  checkpoint rewrite.
- [`manifest.json`](2026-08-13/manifest.json) records its source path, byte
  count, line count, and SHA-256 hash for mechanical comparison.

## Snapshot 2026-08-18

- [`active/`](2026-08-18/active/) preserves 28 active KG, ontology, retrieval,
  evaluation, architecture, coordination, and startup documents immediately
  before they were rewritten around GitHub issue #56.
- [`active/AGENTS.md`](2026-08-18/active/AGENTS.md) and
  [`active/README.md`](2026-08-18/active/README.md) are representative entry
  points into that historical state. They are not current instructions.
- [`manifest.json`](2026-08-18/manifest.json) records every original source
  path, archive path, byte count, line count, and SHA-256 hash.

## Snapshot 2026-08-25

- [`handoff-log.md`](2026-08-25/handoff-log.md) preserves the complete
  byte-identical 300-line active handoff immediately before its retention trim.
- [`manifest.json`](2026-08-25/manifest.json) records its source path, byte
  count, line count, and SHA-256 hash for mechanical comparison.

## Archive Rules

- Snapshots are byte-identical to active source files immediately before archival.
- Never edit a dated snapshot in place. Create a new dated snapshot for later
  archival cycles.
- Keep archive links relative and verify them after every archival cycle.
- Do not use archived lifecycle labels or statuses as current operational state.
