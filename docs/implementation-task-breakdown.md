# Implementation Task Breakdown

This is the bounded active work board. The lossless board before issue #40
archival is preserved at
`docs/archive/2026-07-11/implementation-task-breakdown.md`.

## Retention Rule

- Keep every unchecked checklist item, current phase summaries, and at most five
  concise recent-completion summaries in this active file.
- Keep this file at or below 400 lines; archive before it exceeds 500 lines.
- Move older completed detail into a new dated immutable snapshot under
  `docs/archive/`; never delete or rewrite archived history.
- Preserve existing checklist states mechanically during archival. Historical
  `[x]` and `[ ]` states change only through the normal completion workflow.

## Status Legend

- `[x]` complete in the current repository.
- `[ ]` not started or not verified.
- Goal files hold durable role state; this board holds task completion.
- Archived proof remains authoritative for historical completed details.

## Current Phase Summary

- Phase 0 and the resource-extraction small core are complete.
- Identity, upload/session capture, extractor adapters, semantic candidates,
  graph governance, user graph, wiki projection, infrastructure, mail evidence,
  and completed-slice test hardening have completed tracked slices.
- One pre-existing broad objective remains unchecked: full KG real-evidence
  acceptance. Its complete historical proof requirements remain in the archive.
- Issue #38 authority state isolation and clean-clone reproducibility are
  complete; four explicit real-evidence gates remain blocked by missing
  accepted evidence rather than harness drift.
- Issue #39 MCP protocol and shadow-workflow consolidation is complete in this
  working tree.
- Issue #40 archival maintenance is complete in this working tree.
- Pre-feature production cleanup is complete: test-only gateway scenarios no
  longer ship as public production APIs, mail evidence permission helpers are
  shared, and deprecated Python import/query surfaces retain explicit
  compatibility boundaries.

## Current Unchecked Work

- [ ] Complete the full KG real-evidence objective across sessions.
  - Owner paths: `docs/agent-goals/`, `.formowl/kg-eval/`, KG-owned graph,
    ontology, evaluation, and test files.
  - Current state: blocked on four real-evidence gates. The state-independent
    authority harness now reports that blocked state consistently; do not
    reinterpret harness completion as KG objective completion.
  - Completion proof: canonical authority reports must agree on 12 passed gates,
    zero failed gates, zero remaining gates, and a complete objective audit;
    canonical dev-container checks and the required reviewer gate must pass.
  - Full historical requirements and checkpoint evidence:
    `docs/archive/2026-07-11/implementation-task-breakdown.md`.

## Recent Completions

- [x] Issue #36 evidence-grounded ChatGPT × FormOwl MCP evaluation completed
  with its documented deterministic offline claim boundary and reviewer gate.
- [x] Issue #21 governed mail evidence reading milestones completed through the
  tracked local deterministic checkpoints; no production-readiness claim.
- [x] Candidate KG, ontology-guided comparison, and governed effective graph
  query slices completed without canonical graph/type writes.
- [x] Remaining backbone storage, worker, folder-ingestion, and readiness-smoke
  slices completed with their historical verification evidence archived.
- [x] Completed-slice test hardening and required reviewer gates completed.

## Issues #38-#40 Maintenance Completion

- [x] Complete issues #38, #39, and #40 without weakening authority, MCP, or
  durable-history boundaries.
  - Proof: state-independent KG authority fixtures pass in operator and clean
    layouts, including a read-only repository mount for enterprise/preflight.
  - Proof: one shared MCP protocol engine and JSONL runner preserve entrypoints,
    fail closed on missing identity, reject identity forgery, and require
    injected semantic handlers.
  - Proof: byte-identical snapshots and SHA-256 manifest under
    `docs/archive/2026-07-11/`.
  - Proof: active-file retention rules, archive-integrity tests, canonical
    dev-container suites, and a 3/3 read-only reviewer gate pass.

## Pre-Feature Production Cleanup

- [x] Remove high-confidence dead and duplicate production code without
  changing KG, MCP, permission, or compatibility behavior.
  - Production Python changed by 103 additions and 256 deletions: net `-153`
    lines. Test scenarios moved out of `formowl_gateway`; mail bundle selection,
    grant normalization, and grant expiry now have one shared implementation.
  - Empty readiness markers and an unused JSON-RPC response helper were
    removed. Retrieval uses one private implementation while preserving the
    deprecated alias signature and canonical effective-view requirement.
  - Project and Wiki servers use shared observability directly; legacy import
    paths remain as documented deprecated re-exports.
  - Proof: canonical dev-container suite 726 tests OK, full Ruff check passed,
    325 files passed format check, and the 3/3 reviewer gate agreed.

## Agent Dispatch Notes

Choose the current unchecked task only when it belongs to the active role,
unless the user explicitly assigns cross-role work. Read dated archives only
when historical implementation detail or proof is needed.
