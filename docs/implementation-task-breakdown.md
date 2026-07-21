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
- Pre-feature structural cleanup is complete: repeated evaluator validation,
  HTTP smoke orchestration, PostgreSQL smoke lifecycle, mail payload
  validation, and atomic JSON persistence now use shared implementations.
- The general Candidate Assertion and Domain Pack minimum core is complete:
  procurement and finance fixtures use one candidate-only, source-neutral
  Observation pipeline with atomic persistence and no canonical writes.
- Issue #16 temporal-evidential POC is complete: the same procurement and
  finance pipeline now produces normalized temporal context, independent
  epistemic/lifecycle state, and fail-closed candidate temporal views without
  canonical writes.
- The source-neutral Candidate evidence retrieval iteration is complete:
  logical-source identity/cardinality, access-before-vocabulary filtering,
  chronology/context boundaries, and capped additive ontology reranking reach
  the bounded MAY target without canonical writes.
- Default Candidate Evidence Retrieval is now the enforced onboarding path for
  new hardness and harness work. It counts a stable logical source item;
  historical chunk-count, transitive-component, regex-only, and ontology
  hard-pruning methods remain ablation-only.
  A structured text policy binding proves Unicode/protected-ASCII/Jieba/
  corpus-bound SentencePiece/frozen-profile admission and its
  admission/model/corpus hashes; free-form hashes fail closed. The index-owned
  `CandidateEvidenceTextPolicyRuntime` is the only default query-token source,
  and the binding pins its runtime id and tokenizer implementation hash.
  Default callers provide query text only, explicit context/time admissibility
  precedes tokenization, and non-default transforms use `retrieve_ablation`.
  Raw query text may identify only control intent, evidence count, and
  chronology syntax. Retrieval anchors and supported content terms come only
  from runtime-produced tokens or a named `retrieve_ablation` extension.
  Access uses a real `CandidateEvidenceAccessBinding` with four immutable
  `frozenset` collections of exact nonblank strings, and cross-context
  comparison authorization must be an actual boolean.

## Current Unchecked Work

- [ ] Complete the source-neutral Task Answering methodology slice.
  - Owner paths: `python/formowl_graph/task_answering.py`,
    `python/formowl_graph/candidate_retrieval.py`, task-answering tests, and
    affected canonical specifications.
  - Current implementation: `TaskFrame` revisions preserve follow-up context;
    `EvidenceRequirement` supports sufficient, exact, at-least, and
    all-matching cardinality; retrieval reports total/returned source counts
    plus exhaustive/has-more state; permission-filtered source-item evidence
    assembly feeds content-first projection; and answerability distinguishes
    permission denial, missing target, absent property, partial evidence,
    conflict, and sufficiency.
  - Scope boundary: one method applies to mail, document, table, application,
    and future source shapes. No procurement-specific aliases, source-specific
    query path, canonical graph/type write, user-graph write, wiki write, or
    external action is authorized.
  - Verification: 895 canonical dev-container tests passed; full Ruff and
    345-file format checks passed; `git diff --check` passed.
  - Remaining gate: the required 3-reviewer gate. Keep unchecked until reviewer
    agreement is complete.
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

- [x] General Candidate Assertion, Domain Pack, and Issue #16
  temporal-evidential POC completed.
  Procurement mail-shaped and finance ERP/application fixtures use the same
  `Observation -> CandidateBusinessObject -> CandidateAssertion` pipeline and
  all five assertion kinds. Domain Packs are scoped and content-hash-pinned and
  map local dates into one `TemporalContext`. Candidate temporal views separate
  world time, source knowledge time, materialization time, epistemic status,
  and lifecycle status; missing knowledge boundaries fail closed. Persistence
  remains atomic and candidate-only. Proof: 774 canonical dev-container tests,
  full Ruff check and 338-file format check, `git diff --check`, and 3/3
  reviewer agreement. GitHub target Issue #16 is recorded here, but its remote
  comment remains unsent because both the GitHub connector and local `gh` token
  are invalidated.
- [x] Issue #21 governed mail evidence reading milestones completed through the
  tracked local deterministic checkpoints; no production-readiness claim.
- [x] Source-neutral Candidate evidence retrieval and bounded ontology rerank
  completed without canonical graph/type/user-graph/wiki/external writes.
  The final 100-case MAY run scored 93/100 for both Candidate and ontology:
  73/80 answerable, 10/10 no-match, and 10/10 permission; validators returned
  `blockers=[]`. Anti-overfitting coverage includes finance, quality,
  PDF/PPT/table/OCR/application shapes, English/Chinese cardinality and
  duration handling, identifier exclusion, four-axis access binding,
  access-before-query-vocabulary behavior, chronology/context isolation, and
  label-independent permission evaluation. Proof: 147 focused tests including
  the exact 11-test hardness/harness onboarding command, 884 full canonical
  dev-container tests, full Ruff/264-file format checks, `git diff --check`,
  and 3/3 agreement from Herschel, Popper, and Boole.
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

## Pre-Feature Structural Cleanup

- [x] Consolidate high-cost duplicated validation and smoke harness behavior
  before the next feature slice.
  - Eleven evaluator and smoke entrypoints now delegate common exact-key,
    SHA-256, privacy, HTTP, multipart, gateway-command, and report validation to
    shared evaluator modules while preserving their CLI and output contracts.
  - PostgreSQL live-smoke entrypoints share one startup, readiness, migration,
    and cleanup harness. Mail workflow payload checks and atomic JSON file
    persistence also have one implementation per architectural layer.
  - Real adapters, interfaces, and migrations are the primary tested surfaces.
    Previously exported name-list helpers remain thin compatibility wrappers so
    this maintenance pass does not introduce an unannounced package API break.
  - Total change: 1,334 additions and 1,514 deletions, net `-180` lines. Script
    and experiment entrypoints are net `-893` lines; the added production code
    is shared infrastructure replacing those repeated implementations.
  - Proof: canonical dev-container suite 730 tests OK, full Ruff check passed,
    331 files passed format check, `git diff --check`, and 3/3 reviewer gate passed.

## Agent Dispatch Notes

Choose the current unchecked task only when it belongs to the active role,
unless the user explicitly assigns cross-role work. Read dated archives only
when historical implementation detail or proof is needed.
