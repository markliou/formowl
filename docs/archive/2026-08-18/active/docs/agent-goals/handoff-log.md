# Agent Handoff Log

This active log is a bounded recent window. Lossless prior history is preserved
in the tracked snapshot `../archive/2026-07-11/handoff-log.md`.

Lifecycle label: `active`.

## Retention Rule

- Keep entries from the latest 14 calendar days, with a hard cap of 300 lines.
- If either limit is exceeded, archive the oldest complete dated entries into a
  new immutable dated snapshot before appending more.
- Never split a dated entry, discard content, or rewrite archive history.
- Append only concise cross-agent facts, blockers, verification, and next action.

## 2026-08-06 — Existing-export diagnostic UAT resume
- The active POC remains `browser -> Codex sidecar -> one FormOwl MCP`; it uses the existing MAY export and must not invoke PST parsing again.
- Aggregate v3 passed 452,127 inventory items with every failure/rejection gate
  zero after its missing report-parent operational error was corrected.
- Native scope exposed and fixed a general ancillary-file/message-coverage bug;
  65/65 focused tests, Ruff, and 3/3 reviewers pass. Its constrained
  existing-export rerun is active; next is checkpoint-bound 256-item sharding,
  exact 15-item fingerprint, deployment, and browser UAT.
- 2026-08-11: `agy` is temporarily excluded from all subagent/reviewer work because its quota is exhausted; use Codex/GPT agents until explicit re-enablement.

## 2026-08-11 — Track 2 Hybrid-v2/runtime and storage diagnostic

- Methodology authority remains valid but blocked: authority `sha256:c8e3fc5ec13d690f33d27797942a3b9b090319d4be8f269c77bccd646d787177`, final execution `sha256:0a39785f9c8ed58a23158280dc8ca9ccb2dd08b15a6b9ce2715335c4e0a4ffd1`. No readiness, KG-versus-ontology, UAT, PST, or production claim is made.
- Existing-Observation-only Hybrid-v2 diagnostic improved required evidence from 1/2 to 2/2 while no-answer false matches stayed 0 and ontology hard-gate false rejects stayed 1; query/evidence fingerprints match within each run, all PST/parser/extractor counters are zero, and final-answer generation remains untested. Report: `build/issue33-hybrid-v2-runtime-diagnostic.json`.
- Disposable storage conformance report `build/issue33-storage-conformance-live.json` binds package `sha256:7a20198157696de8a8f4e75ac13af6d6eb4ade519bf8473e081ac13eee1a2644`; both PostgreSQL and Neo4j passed 24/24 faults in three cycles, exact retries, permission/provenance, lifecycle/schema, structured-set determinism, rollback, and destructive restore with zero operational failures.
- Corrected conformance latency/memory favored PostgreSQL, but the formal verdict is `decision_blocked`: cold samples did not provision a fresh server, traversal remains adapter/Python BFS rather than isolated native Neo4j traversal, and a corrected replicated full-workload campaign was not run. Retain PostgreSQL operationally; do not authorize migration or dual-write.
- Focused canonical container tests pass 14/14 storage, 4/4 diagnostic, 5/5 tokenizer, and 22/22 mail gateway; Ruff and format checks pass. The calibration SentencePiece model is not a production-packaged immutable artifact, so cross-run profile stability remains a blocker even though each report enforces query/evidence equality.

## 2026-08-12 — Track 2 ontology correction and Neo4j stop

- Maintainer decision: Neo4j is rejected for this project and PostgreSQL
  remains canonical. Do not resume Neo4j benchmarks, adapters, projections,
  migration analysis, dual-write, or related SPEC changes.
- The ontology retrieval correction replaces inferred-type hard pruning with a
  capped additive rerank: compatible inferred types may receive at most 0.2;
  inferred mismatches receive no bonus but are not removed. Explicit
  core-supertype governance remains unchanged.
- Canonical focused evidence: ontology suite 5/5 and Hybrid-v2 diagnostic 4/4.
  Existing-Observation results are required evidence 1/2 to 2/2, ontology
  false rejects 1 to 0, supported extractive answers 1 to 2, unsupported
  answers 0, and no-answer false matches 0 to 0. PST/parser/extractor
  invocation counters remain zero.
- The result remains diagnostic-only under valid blocked methodology
  authority. Repository-packaged immutable SentencePiece data, cross-process
  profile stability, raw-source completeness, independent holdout, and real
  user end-answer acceptance are still unproven.

## 2026-08-13 — UAT session restart checkpoint

- The active restart authority is `dual-track-uat-kg-coordinator.md`.
- Root-cause wording is frozen as `reviewed evidence/runtime startup
  compatibility`, with only v25-r5 historical producer identity and legacy
  semantic-alias execution identity. Their focused container tests pass 6/6
  plus Ruff.
- A prior checkpoint's non-exact semantic, claim, privacy, and execution
  contract had passed. This session did not rerun it, so it is not fresh
  evidence; the exact-set contract failed at runtime 69 versus oracle 77.
- Live web 8088 and old MCP 8091 remain online. Do not cut over until 8092
  returns exact count 77 and the frozen fingerprint. No active subagents remain.
- Restart verification preserved the integration worktree's existing UAT
  changes and confirmed the two existing rollback evidence hashes. Docker live
  state itself was not freshly read, so the next session must reverify
  containers before any MCP-only cutover.
- Two independent agents agree on the exact private aggregate:
  oracle 77, runtime 69, intersection 15, missing 62, unexpected 54, and
  symmetric difference 116.
- All 89 selected columns match reviewed authority, but the alternate projection
  explains only 3/116 differences and no general runtime rule covers all gaps.
- Two bounded Stage 3 joins produced no acceptable artifact; 116/116 six-field
  lineage records remain incomplete. The blockers are the source-complete
  revision crosswalk and authoritative missing-side reviewed-occurrence lineage
  key.
- No PST reparse, production/repository UAT-code change, hardness/onboarding
  run, 8091 cutover, or canary rerun occurred. Next build a bijective crosswalk
  from old alternate-tie context to current reviewed coordinates, then link
  oracle decisions through reviewed source/table/row occurrences to current
  binding/row/projection. Require traceability for 77 oracle records and 69
  runtime values, individual materialization of 116 differences, and no orphan
  or undocumented many-to-one links. Any missing/ambiguous key keeps the gate
  blocked; delegate a production patch only after one general rule is proven.

## 2026-08-17 — Document-first UAT POC completed

- This entry supersedes the 2026-08-13 exact-77 reconciliation route as the
  active UAT completion path. The completed architecture is
  `UAT webpage -> Codex sidecar/thread -> exactly one read-only document MCP ->
  authorized existing-export content -> Codex synthesis -> DOM`.
- Direct HTTP smoke returned HTTP `200`, a readable non-placeholder assistant
  result, `30` authorized document results, attempted/successful MCP deltas
  `1/1`, no second call, equal response/reinjection commitment
  `sha256:d01549bbf07f6116035406721d36034d780f5433453ae2c1ee49451a9c2c1a24`,
  and nonempty final commitment
  `sha256:d3ff5e19f0b6b3578e09ac380905244615f6e6de77a8a38ab5f4e03fd29d4935`.
  Its safe report commitment is
  `sha256:2eaad16203a30fe3f8f40e9f5a088c039547723561d906a03644e9550f720d78`.
- The one permitted real Chromium click produced one same-origin
  `POST /api/chat` with HTTP `200`; the new DOM answer exactly equaled
  `assistant_text` and was readable/non-placeholder. Attempted/successful MCP
  deltas were `1/1`, dynamic invocation count was `1`, and no second call,
  fallback, or retry occurred. Response/reinjection commitment was
  `sha256:2f65efa86b8d5085b1be06661d6efbbe9b8f579879c1ead68783d9da47c28b22`;
  final commitment was
  `sha256:c7a22fa4fc63aa24444c44e0fb05318899db84b07df526c96456e0fc214d9611`;
  safe browser report commitment was
  `sha256:ffdb74692f236c5a7ddeca85bfc0ec0d9e0dbdb8d2c8ba5845e7b2443a9c41fc`.
- The observer-bootstrap correction passed focused dev-container tests `9/9`,
  targeted Ruff/format, diff-check, a no-submit live CDP probe, and reviewer
  `AGREE`.
- UAT web `8089`, read-only document MCP `8093`, the Codex sidecar, and
  persistent Chrome/FormOwl tab remained running after acceptance.
- Methodology authority remains valid but blocked. PST/extraction was not
  rerun; KG/ontology and canonical graph writes were not invoked. This is not
  methodology-quality UAT, KG-versus-ontology evidence, production readiness,
  or production hardening.
- GitHub issue #55 is closed and completed; successful completion comment ID
  `5315010812`.

## 2026-08-17 — LAN and independent-oracle final acceptance

- The final live surface is Web `192.168.71.211:8089`, read-only document MCP
  `127.0.0.1:8093`, and loopback-only CDP. LAN connections to `8093`, `9222`,
  and `9233` remained refused.
- One local real-Chromium click produced one same-origin `POST /api/chat` with
  HTTP `200`, MCP attempted/successful delta `1/1`, one dynamic invocation,
  DOM equal to nonempty `assistant_text`, equal response/reinjection and summary
  commitments, and no second call.
- Recursive public response/network JSON and DOM checks found zero leaked
  document `content` or `snippet`, sentinel values, or raw references. The
  dedicated document-UAT internal path remains isolated; the global `_guards`
  allowlist was not broadened.
- Agy independently used its private oracle for one click and one HTTP `200`
  POST. The answer was present and oracle-matched, with no error, retry, second
  submit, or second MCP call. Server chat/MCP-attempted/MCP-successful counters
  moved `1/1/1 -> 2/2/2`, delta `+1/+1/+1`, and remained stable for eight
  seconds.
- Safe local-acceptance and post-Agy-accounting JSON SHA-256 values are
  `sha256:6e3f25bdc4329129ecb5571a33d66815d04e4ea646904b16497d9254a13941cc`
  and
  `sha256:26689a84986462100268971d75ed71cdffd41c3d1edcce258980112439de7c06`.
- Two reviewer checkpoints returned `AGREE`. All three UAT services and the
  ordinary-bridge browser remain running.
- Methodology authority remains valid but blocked. This is a non-production,
  non-KG/ontology/PST POC result and does not establish methodology quality,
  comparative performance, production readiness, or production hardening.
