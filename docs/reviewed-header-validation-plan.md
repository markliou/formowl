# Reviewed Header Validation — Phased Plan

Lifecycle label: `active`. Status: **待實作／待測**. Contract: `SPEC.md` §7.5
"Reviewed header validation" and `RESOURCE_EXTRACTION_SPEC.md` §(XLSX tables).
Methodology authority remains blocked; nothing here is a readiness claim.

## Why

Automatic exact binding (SPEC §7.5) only accepts `source_provided` columns. The
attachment extractor marks only formal Excel Table objects as `source_provided`;
every ordinary header row is `candidate_only`. In the current sealed source
(`combined-uat-source-r17/admitted/exact-cells/manifest.json`):

| Column status | Count |
|---|---|
| `candidate_only` | 9417 |
| `unavailable` | 91 |
| `source_provided` | 17 |

So identifier+field questions never reach the exact engine and fall back to the
bounded lexical scan (always `incomplete`). The generic fix is to validate
candidate headers through governance, never to relax §7.5 at query time.

## Phases (one bounded slice per session)

Each phase ends with focused dev-container tests and a handoff-log entry. Keep
write sets disjoint from any other active agent.

1. **Loader read path (no behavior change by default).** Accept an optional
   sealed reviewed-header config (sha256-pinned, same shape as reviewed
   annotations). Expose approved columns as `reviewed_header`; let the §7.5
   applicability check (loader ~1025, ~1945) and the native row/cell projection
   gates (~5493, ~6870, ~6933, ~7025) accept `reviewed_header` with disclosure.
   Without the config, output must be byte-identical to today.
2. **Deterministic structural proposer.** Offline, resumable, bounded batch
   script over `candidate_only` columns: header text vs. sample data-row type
   consistency, uniqueness, non-empty, not numeric/date-like, not redacted,
   resolved merged paths. Emits candidate proposals bound to source hash,
   table fingerprint, header row index, column hash and native label.
3. **Review receipt + versioned acceptance policy.** Tool that applies a pinned
   policy to proposals and writes a sealed receipt (approver identity, decision,
   policy version, proposal fingerprint). No query-time or answer-model approval.
4. **LLM proposer for `ambiguous` only (optional).** Resumable offline batches
   within provider limits; candidates only; reviewed through phase 3.
5. **Deploy and UAT.** Rebuild deployment manifest (no `__pycache__` in the
   candidate tree), deploy, verify through real webpage questions, record results.

## Progress

- 2026-10-23: SPEC §7.5 clarification and RESOURCE_EXTRACTION_SPEC cross-reference
  written (uncommitted; independent three-reviewer acceptance pending).
- 2026-10-23 **Phase 1 done (candidate tree only, uncommitted; root port pending).**
  `issue56_sealed_source.py`: revision fields `reviewed_header_bindings` /
  `reviewed_header_column_hashes` / `reviewed_header_pin`,
  `reviewed_header_binding_key(cell)` (asset_id, extractor_run_id, sheet, table,
  header row, cell index, native label) and sealed binder
  `bind_issue56_reviewed_headers` (artifact `formowl_reviewed_header_validation_v1`,
  approver `APPROVER_ACTOR`, decision `approve_reviewed_header`, approvals =
  `{binding, column_hash}` where column_hash must be a manifest `candidate_only`
  column). Loader: `_exact_column_applicable` at both §7.5 applicability sites;
  `_effective_cell_structure_status` upgrades only approved candidate data-row
  cells to `reviewed_header`, which sets `source_proven_field_schema`. Answers
  suffix such cells with 「（欄位標題經審核驗證）」. Web flag
  `--reviewed-headers PATH --reviewed-headers-sha256`. Tests:
  `candidate-r39-routefix/tests/test_reviewed_header_validation.py` 4/4 in the dev
  container. Deployed as v20 without the flag (behavior unchanged); health ok.
  Not yet proven end-to-end through `_build_attachment_table_row_provider`; verify
  in phase 5 with a real approval file.
- 2026-10-23 **Phase 2 code done (root repo, uncommitted).**
  `scripts/issue56_reviewed_header_proposer.py` (proposer `structural_v1`) reads
  every bound completed job once and writes per-job `job-<i>.jsonl` +
  `job-<i>.done.json` (atomic, 0600, resumable) under the private dir
  `.formowl/ontology-uat-20261019/private/reviewed-header-proposals/`.
  Rules: ambiguous for non-indexed column, redacted/generic/too-short label,
  duplicate label in its header row, multi-level header path, <2 data values;
  not_header for label wider than 40 display columns, value-shaped label, no
  letters, or label repeated as ≥half the data; otherwise header_confirmed.
  Tests: `tests/test_issue56_reviewed_header_proposer.py` 4/4 in dev container.
  A full sequential pass over ~11.5M Observations was disk-bound (~0.45 MB/s on
  `/dev/sda`), so the proposer now uses the exact-cells row index: pass 1 picks
  rows with candidate-labelled cells, pass 2 reads one row per table to learn its
  region and picks sample data rows, pass 3 collects their cell ids, pass 4 reads
  only those cells (row-derived binding verified equal to cell binding on 62
  cells). Each pass has an atomic checkpoint for resumption.
  Run as root in the UAT image (sources are root-only) with candidate
  `python` and `scripts` on `PYTHONPATH`, `--network none`, sources read-only.
- 2026-10-23 **Phase 3 code done.** `scripts/issue56_reviewed_header_review.py`
  applies a pinned policy (`structural_accept_v1` or `structural_llm_accept_v1`)
  and, only with `--approve`, writes `review-receipt.json` (receipt artifact
  `formowl_reviewed_header_review_receipt_v1`: approver, decision, policy,
  approvals SHA-256/count, proposal file hashes) plus `reviewed-headers.json`
  (0600). The candidate binder now requires and verifies that receipt.
  LLM approval only for structural `ambiguous` items whose reasons are all in
  {`multi_level_header_path`, `label_too_short`}; an LLM never overrides
  `not_header`. Tests: root `tests/test_issue56_reviewed_header_review.py`;
  candidate `tests/test_reviewed_header_review_e2e.py` proves the binder accepts
  the tool's output.
- 2026-10-23 **Phase 4 code done.** `scripts/issue56_reviewed_header_llm_proposer.py`
  (`llm_v1`): resumable batches, strict JSON schema, labels/values marked as
  untrusted data, every failure fails closed to `ambiguous`. Tests in
  `tests/test_issue56_reviewed_header_llm_proposer.py`. A synthetic,
  non-private live smoke batch (3 items, ~50 s) worked and showed the model
  confirming a date-shaped label, so structural hard negatives now win over
  every ambiguity. Running it on real proposals sends native labels and sample
  values to the external provider and needs explicit user authorization.
  All reviewed-header tests: 13/13 root + 5/5 candidate in the dev container.
- Pending: the background structural run started before the hard-negative
  reorder; after it finishes, delete `proposals.jsonl` and `proposals.done.json`
  and rerun to regenerate pass 4 only.
- Earlier: 8088 ran `…-8088-20261022-v19` from `candidate-r39-routefix` with turn cap
  300 s and per-request provider cap 240 s; it also carries an unverified
  2026-10-23 16:17 loader edit left by the interrupted Codex session.
