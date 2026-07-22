# Knowledge Graph Research Agent Goal

## Lifecycle

- Label: `active-blocked`
- Lossless history: `../archive/2026-07-11/kg-research-agent.md`
- Retention: keep role, current objective, status, blockers, and next action only;
  target at most 180 lines and archive before 250 lines.

## Role

Knowledge Graph Research Agent.

Durable role definition: `../agent-roles.md`.

## Current Objective

Complete the FormOwl Knowledge Graph method exploration and acceptance work:
fill in external recent literature comparison, ontology integration method,
multi-user KG and KG fusion experiments, multimodal enterprise-data validation,
annotation/adjudication workflow through either legacy human evidence or a
four-professional-specialist LLM subagent panel, production adapter gate, and a
total acceptance suite that clearly marks passed and failed items.

Historical source: Codex session `019eda5f-7dd6-74a2-ac56-4f84e5d58560`.

Status: `blocked` for the broad KG real-evidence acceptance objective. Current
repo-side tooling is synchronized, but four broad real-evidence gates still
require operator-supplied or public reproducible evidence before completion can
be claimed. Product-level production readiness, top-tier scientific validation,
raw access, canonical graph writes, autonomous business judgment, and
enterprise-scale latency/scalability remain outside any future completion
claim.

## Status

`blocked`

## Current Acceptance State

Do not treat the broad KG real-evidence acceptance objective as complete in the
current authority state. The stricter current state is blocked, and no broad
completion claim is supported until the four remaining gates have accepted
canonical packets and all authority reports are synchronized and passing.

## Current POC Execution State

- The maintainer-frozen target remains Hybrid KG + Ontology v2. This correction
  does not create or authorize a v3.
- Runtime mail tokenization now defaults fail-closed to the frozen Jieba +
  SentencePiece candidate-admission profile. Legacy ASCII tokenization is
  available only through the explicit test-only override.
- Complete body evidence, offsets, text-attachment observations, search/read
  separation, content-based PST occurrence identity, and source-completeness
  reporting are implemented in the isolated POC branch.
- The original private PST 100-question set is hash locked. Complete-source
  remapping currently resolves 128/138 frozen evidence observations exactly.
  The remaining 10 affect 11 cases and have no unique exact/hash-bound mapping;
  the evaluator remains blocked rather than regenerating questions, choosing
  duplicate occurrences, or using fuzzy evidence aliases.
- Full-bundle applicable canaries pass for long-tail body evidence,
  search-then-read cross-segment evidence, text attachments, the exact COO item
  query, and negative-claim fail-closed behavior. The fixed cross-message
  canary remains not applicable until frozen-manifest mapping is complete.
- This is POC diagnostic progress only. It does not establish methodology
  readiness or KG-versus-ontology superiority.

## Blockers

- The broad KG real-evidence objective remains unchecked on the active board.
- Issue #38's authority harness is state-independent and clean-clone
  reproducible. Its explicit blocked fixture still correctly reports the four
  unresolved real-evidence gates; that blocked evidence state is not harness
  drift.
- The fixed real-PST 100 cannot be replayed honestly until all frozen evidence
  observations have unique exact/hash-bound complete-source mappings. Ten
  observations currently remain unresolved because the old and new parser
  outputs are content-different or duplicate-ambiguous.
- No canonical completion claim is valid until the required packets, reports,
  dev-container checks, and reviewer gate agree.

## Next Action

Keep the fixed v2 method and original 100 questions unchanged. Diagnose the
remaining parser-output instability only through exact/hash-bound source
identity; do not add fuzzy mappings or case-specific aliases. Replay the fixed
100 only after 138/138 evidence mapping is available, then use the same-source
result as POC diagnostic evidence under the executable methodology-authority
gate. Keep candidate-before-canonical and no-raw-path boundaries intact.
