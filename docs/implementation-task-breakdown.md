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

## Current Phase Summary — 2026-08-25

- The active KG program is GitHub issue #56, not the historical issue #33 plan
  or issue #55 document-first POC.
- Frozen method and tokenizer remain
  `evidence_to_knowledge_kg_ontology_v2_hybrid_v1` and
  `jieba_sentencepiece_frozen_profile_candidate_admission_v1`.
- Pinned methodology authority is valid but blocked. The normal runtime-method
  gate is passed; source completeness, accepted execution-fingerprint binding,
  same-pipeline real-source ablation, and independent final-answer acceptance
  remain blocked.
- Strong RAG is a required component/control. KG adds heterogeneous identity,
  joins, bounded topology, time, contradiction, provenance, and coverage.
  Ontology is scoped/data-first/capped soft scoring. Exact sets use a
  deterministic executor.
- The existing five-step POC plan is unchanged and step 4 remains
  `in-progress`.
- The sealed workspace-only development package over exactly `456`
  Observations passed its artifact/identity-scope contract. Its mode is
  `workspace_only_v1`, and no `tenant_id` field or key exists.
- Read-only source tracing established that the earlier synthetic fixed
  prompt did not bind to the approved source: both requested terms had zero
  occurrences in raw source, parser-native output, and sealed retrieval.
  This was a prompt-to-source mismatch, not a graph traversal defect.
- The development diagnostic one-shot claim
  `issue56-development-workspace-only-diagnostic-one-shot-20260820-v1` was
  consumed. It must not be rerun, retried, or parameter-tuned. Its report is
  blocked: Hybrid `0/100`, graph paired CI `[0,0]`, citation support `0%`,
  no-answer false positives `100`, p95 `1510.841 ms`, and permission leakage
  `0`.
- The user separately approved a versioned, non-claim-bearing minimum E2E plus
  phase-tracing diagnostic slice. Its synthetic, non-sealed path passed:
  prompt -> ASGI `/mcp` -> synthetic preverified workspace-only principal ->
  dispatcher actor injection -> `SemanticMcpGateway` ->
  `AuthorizedSemanticMailSession` -> deterministic cited response, with `2`
  citations and `2` graph paths. Canonical focused evidence is `25+5` passing
  tests, including the new five-test slice.
- The deterministic
  `issue56_source_backed_connected_identifier_prompt_selection_v1` selector
  now chooses only real protected identifiers with authorized exact-term and
  lexical lineage plus an existing source-backed connected path. Its focused
  selector/gateway E2E evidence passed `11/11`.
- One canonical full regression ran `1873` total / `1781` passed /
  `54` failures / `23` errors / `15` skips. Primary blockers were the
  `formowl-dev` Python 3.13 versus pinned E5 runtime mismatch and existing
  Issue #20/#33/authority drift. The sole directly related stale v3 test
  expectation was corrected and passed in pinned E5 `11/11`; the full suite
  was not rerun and remains non-green. The real V4 POC diagnostic passed, but
  repository-wide completion cannot be claimed.
- Immutable mode
  `issue56-sealed-source-real-prompt-phase-traced-diagnostic-20260823-v4`
  consumed one real-source diagnostic claim over the same `456` Observations.
  It ran as `workspace_only_v1` for `workspace_formowl`, actor/approver
  `user_full_pst_domain_hard_case_eval_owner`, with no tenant dimension.
- V4 passed its bounded path with `2` lexical anchors, `10` graph paths, and
  `1` citation. Query/gateway/HTTP timings were `951.148333`, `953.544449`,
  and `982.203990 ms`; `relation_projection` was the largest semantic phase at
  `717.357210 ms`, and `deadline_exhausted_phase` was null.
- Loader time was `678625.866681 ms` for one-time sealed source loading,
  precompute, and prompt selection outside the request. It is not request
  latency.
- V4 immutable hashes are claim
  `sha256:2b092814194dd90d597161dfcd04822be75c97fc5c5364478bbc8b52307098cb`
  (byte seal
  `sha256:76dda5b18801a7587b212631b0d4d7ae0544646910e143ced0883f14e5db69b8`),
  report byte seal
  `sha256:40f48fea0145d523f5d14e2943b41750a48923e111cdf6e6c5e3cd265903a458`,
  trace `sha256:4b518dd33bc406027f2fe0104559ead2cdb27a096b3357d9470acdac34e09ef4`,
  and execution
  `sha256:031cfe6f04c9b595bed6fd24375590a78df18dd03e07b68821c955bc03ad0b94`.
- Source, gateway selection, owner selection, result, and answer bindings are
  `sha256:b3959bba1267879ba3bcc6889fd063363f899987722b2447685aad844f6b53ae`,
  `sha256:5c6bbbac6df98afb061d5aa4b21a7802fdcab7d9d09d32dadaec2f1ac0ab3c1a`,
  `sha256:84857528eb34f4e03e343c078f5a9f89e6c8278a6807a6d84cc72fdc2d59b543`,
  `sha256:cd4791354b612ae652da2f76d9733c28946bc18c63856b2a08f6e0a9bab63670`,
  and `sha256:025d02916a7c0c1a816fba06754d9578a327a7e442ff9d1e34b2f273d2af20f7`.
- Formal v6 mode
  `issue56-sealed-source-real-prompt-relation-projection-equivalence-phase-traced-diagnostic-20260825-v6`
  consumed its canonical claim over the same `456` Observations as
  `workspace_only_v1` for `workspace_formowl`, approved actor
  `user_full_pst_domain_hard_case_eval_owner`; no tenant dimension exists.
- V6 is blocked. Outside request execution, sealed loading, before-arm graph
  content preseal, and owner relation-base precompute took `677442.490893`,
  `60990.781102`, and `4245.079389 ms`.
- The before arm completed `graph_snapshot` in `0.036742 ms` and Strong RAG in
  `90.802575 ms`, then exhausted the `1500 ms` budget in
  `relation_projection` after `1415.389724 ms`. Query/HTTP were
  `1520.515069`/`1555.417065 ms`; it returned `0` graph paths, citations, and
  scores.
- The after arm completed every required semantic phase. Relation projection,
  query, and HTTP took `57.939772`, `291.040282`, and `346.270890 ms`; it
  returned `10` graph paths, `1` citation, and `48` scores.
- Relation binding/base cache entries moved before `0/0 -> 1/0` and after
  `1/1 -> 1/1`. Graph, index, permission, plan, and runtime gates passed; the
  remaining equivalence groups failed because the before arm exhausted its
  deadline before traversal and result production.
- V6 claim/claim-byte/report-byte hashes are
  `sha256:6b045800e19d82fa187ff4271ab2d854189726a3449bcd4cedf1c03c47c2639e`,
  `sha256:65b3b3d1f9889e1d82ec47ade77fb7dc44b4a9a3711f7bd37a538cdc9e986b61`,
  and `sha256:ae10a358242f6f44b1f92267a80e48eac296ebd677eb1ac27bcc24f6111909f1`.
  Execution/source/preseal/trace bindings are
  `sha256:7ecf2c31901116ddb32d2a8a7cb41b0e3b504648006a68b3e23e89ee22b2c1cf`,
  `sha256:bbc67d7fc7051a597488034d277c772a4a5c68bc09dc8ce696bfd2bcc0d8db8b`,
  `sha256:4900fd366f300af097de355b59feeb6059a06b41574d01d9834e51576c4eed27`,
  and `sha256:040cb86b70af99fd6f0467306423e0e556a6dfc41b1ed734227b613248c27a93`.
- Temporary v6 tests passed `6/6`, the combined focused suite passed `31/31`,
  and independent cross-review found no blocker. The formal v6 root is
  consumed; this diagnostic-only evidence does not establish methodology
  readiness, quality, or KG/ontology superiority.
- Diagnostic versions v1, v2, v3, v4, v5, and v6 are consumed and must never be
  rerun, retried, or tuned.
- V4 is neither an independent holdout nor promotion evidence and
  cannot support KG/ontology superiority. The sealed 41-case and additive
  59-case mail holdouts and the GitHub transfer holdout remain unexecuted.
- The v3 gate-evidence-to-atomic-promotion contract is implemented and focused
  tests pass, but no passed production gate evidence exists to promote.
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
    fail-closed until all remaining gates pass.
  - The `2026-08-20` workspace-only development diagnostic was a consumed,
    blocked one-shot, not authority evidence. Do not execute it again.

- [ ] Implement GitHub issue #56 graph-guided Hybrid KG + Ontology v2 and make it earn a measurable win over strong RAG.
  - Work A: immutable Jieba + SentencePiece profile and re-index.
  - Work B: source-complete, source-preserving graph input.
  - Work C: small-core scoped ontology with capped soft scoring.
  - Work D: typed router, validated plan, bounded traversal, evidence bundles,
    and deterministic exact execution.
  - Step 4 / Work D status remains `in-progress`; no checkbox is earned by the
    non-claim-bearing v4 or blocked v5/v6 diagnostics.
  - The next action remains inside step 4 and requires separate approval; v6
    must not be rerun, and all four blocked authority gates still require
    legitimate production evidence.
  - Work E: controlled, citation-grounded LLM roles with the same answer model
    across arms.
  - Work F: strong RAG control, anti-fitting split, diagnostic evaluation,
    independent holdout, and transfer-domain final-answer evaluation.
    The 41-case and 59-case mail holdouts and GitHub transfer holdout have not
    executed.
  - Implementation completion is not comparative close. Keep the issue open
    until the pre-registered quality/safety/cost gates and executable authority
    pass.

## Recent Completions

- [x] Methodology authority guard/runtime tokenizer probe and candidate,
  canonical, lifecycle, user/effective graph, scoped ontology, and projection
  contract slices exist; authority remains valid but blocked.
- [x] The bounded deterministic source-backed prompt selector plus immutable v4
  real-source diagnostic slice passed its stated non-claim-bearing scope.
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
