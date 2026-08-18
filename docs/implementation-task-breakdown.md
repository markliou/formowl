# Implementation Task Breakdown

This is the bounded active work board. Lossless history is indexed in
`docs/archive/README.md`; archived files are not current instructions.

## Retention Rule

- Keep every unchecked checklist item.
- Keep current phase summaries and at most five concise recent completions.
- Keep this file at or below 400 lines; archive before 500.
- Never edit an existing dated archive.

## Status Legend

- `[x]` complete and verified for its stated scope.
- `[ ]` incomplete, blocked, or not verified.
- Goal files hold durable role state; this board holds task completion.

## Current Phase Summary — 2026-08-18

- The active KG program is GitHub issue #56, not the historical issue #33 plan
  or issue #55 document-first POC.
- Frozen method and tokenizer remain
  `evidence_to_knowledge_kg_ontology_v2_hybrid_v1` and
  `jieba_sentencepiece_frozen_profile_candidate_admission_v1`.
- Methodology authority is valid but blocked. Current runtime still uses
  `mail_candidate_kg_broad_ontology_diagnostic_v1` and
  `ascii_identifier_regex_v1` without CJK support.
- Strong RAG is a required component/control. KG adds heterogeneous identity,
  joins, bounded topology, time, contradiction, provenance, and coverage.
  Ontology is scoped/data-first/capped soft scoring. Exact sets use a
  deterministic executor.
- PostgreSQL/pgvector remains canonical. Neo4j work is not active.
- Pre-rewrite KG/methodology/coordination documents were preserved losslessly
  under `docs/archive/2026-08-18/` before active documents were rewritten.

## Current Unchecked Work

- [ ] Implement issue #20 Google-backed ChatGPT MCP OAuth identity mapping and
  gateway-controlled `ActorContext`.
  - Owner: System Backbone Agent.
  - Repository implementation and local harness slices are extensive, but
    validator blockers; seven external layers remain `not_supplied`, so #20
  stays open.
  - This bounded batch reviewer
    gate is not the Issue #20-wide reviewer external layer, which remains
    `not_supplied`.
  - Remaining state: issue #20 stays unchecked and open. Repository authority is
    the existing Issue #20 runbook, evidence packet, and completion transition.
  - External state: `live_postgresql`, `operator_cli_postgresql`,
    `production_container_lifecycle`, `mcp_inspector`, `live_chatgpt_google`,
    `reviewer_gate`, and `completion_audit` remain `not_supplied`.
  - Next: freeze docs/local harness, run all seven external layers, and keep #20 unchecked.

- [ ] Implement issue #41 generic Core Asset Storage identity binding, tenant
  isolation, lifecycle, retention, and authorization.
  - Owner: System Backbone Agent.
  - Preserve one generic Asset/Occurrence/permission boundary across every
    source family; duplicate bytes must not merge authorization.
  - Completion requires cross-tenant denial, upload/rollback/orphan/transfer/
    redaction/purge/retention proof in the canonical dev container.

- [ ] Complete the full KG real-evidence objective across sessions.
  - Owner: Knowledge Graph Research Agent.
  - Historical broad-objective requirements remain at
    `docs/archive/2026-07-11/implementation-task-breakdown.md`.
  - This objective now closes only through issue #56's strong-RAG comparison,
    independent holdout, transfer domain, final-answer review, executable
    authority, and reviewer gate.

- [ ] Align the real runtime with the active methodology authority before any further methodology-quality UAT or KG-versus-ontology claim.
  - Implement the frozen tokenizer/profile and same-profile query/evidence
    index without fallback.
  - Prove raw/source-system-to-Observation completeness.
  - Bind source, index, graph, ontology, model, prompt, evaluator, code, image,
    and authority revisions into one execution fingerprint.
  - Keep `python3 scripts/methodology_authority_check.py --require-ready`
    fail-closed until all five gates pass.

- [ ] Implement GitHub issue #56 graph-guided Hybrid KG + Ontology v2 and make it earn a measurable win over strong RAG.
  - Work A: immutable Jieba + SentencePiece profile and re-index.
  - Work B: source-complete, source-preserving graph input.
  - Work C: small-core scoped ontology with capped soft scoring.
  - Work D: typed router, validated plan, bounded traversal, evidence bundles,
    and deterministic exact execution.
  - Work E: controlled, citation-grounded LLM roles with the same answer model
    across arms.
  - Work F: strong RAG control, anti-fitting split, diagnostic evaluation,
    independent holdout, and transfer-domain final-answer evaluation.
  - Implementation completion is not comparative close. Keep the issue open
    until the pre-registered quality/safety/cost gates and executable authority
    pass.

## Recent Completions

- [x] Methodology authority guard and runtime tokenizer probe were installed;
  current state is valid but blocked.
- [x] Candidate graph, canonical graph, lifecycle, user/effective graph, scoped
  ontology, and graph-derived projection contract slices exist.
- [x] Source/Asset/Observation, mail evidence, Project MCP, Wiki MCP, connected
  gateway, and container-first backbone slices exist within their documented
  claim boundaries.
- [x] Historical issue #55 document-first POC completed as a bounded non-KG
  smoke; it is no longer an active methodology direction.
- [x] Active KG/methodology documentation was losslessly archived and rewritten
  around issue #56 on 2026-08-18.

## Pre-Feature Production Cleanup

The completed production-cleanup record remains immutable history in
`docs/archive/2026-08-18/active/docs/implementation-task-breakdown.md`. It is
retained as a completion boundary for Issue #20 finalization tooling, not as a
new KG task.

## Pre-Feature Structural Cleanup

The completed structural-cleanup record is preserved in the same archive. No
historical cleanup item is reopened by the issue #56 documentation rewrite.

## Dispatch

Choose an unchecked item owned by the active role unless the user explicitly
assigns cross-role work. Do not use archived or historical-pointer documents as
next-action authority.
