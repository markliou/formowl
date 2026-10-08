# Implementation Task Breakdown
This is the bounded active work board. Current 2026-10-08 truth: UAT `8089` is online and healthy (`/api/health` HTTP `200`, `query_service_connected=true`). Canonical dev-container UAT web E2E ran `33` tests: `32` passed and `1` skipped; Chromium runner self-check passed. Fresh real browser smoke for `把嘉值交期調閱出來` exited `0`: ordinary MCP `0`, mail MCP `1`, HTTP `200`, `2` governed citations, provider finalization passed, no timeout/error, and incomplete coverage was visible. The earlier `劉一帆` rerun passed with MCP `1`, `10` citations and reload/reset/post-reset checks. `source_binding_verified=false` remains a diagnostic comparability gap; feature remains 待測 and no formal UAT/readiness/release claim is made. Old `8088` remains rollback. Existing ingestion/index facts and historical failure evidence remain below and in the handoff; do not relabel the full suite green.

> **Current worker-policy supersession (2026-10-07):** the requested
> `gpt-6.1-sol`/`high` worker tier is a traceability preference, not a
> precondition for bounded work. Missing, mismatched, unavailable, or
> unpinned worker metadata is recorded as `unverified`/`unavailable` and
> **must not stop** the assigned work. Never claim an unobserved fallback is
> sol/high. Dated bullets below preserve diagnostic history only; they are not
> current blocking instructions. This rule is aligned with `AGENTS.md`,
> `SPEC.md §8.1.1`, the role registry, and the handoff supersession note.

## Retention Rule
- Keep every unchecked checklist item.
- Keep current phase summaries and at most five concise recent completions.
- Keep this file at or below 400 lines; archive before 500.
- Never edit an existing dated archive.
## Status Legend
- `[x]` complete and verified for its stated scope.
- `[ ]` incomplete, blocked, or not verified.
- Goal files hold durable role state; this board holds task completion.
## Source-neutral descriptor + evidence double-check — 待測
- [ ] Implement and verify the approved shared contract in [SPEC §7.3.1](../SPEC.md#731-source-neutral-evidence-double-check--待測); not yet 標準功能.
  - Mail and independent Markdown/plain-text lookup share one core; attachments are not independent documents. 2026-10-06 SPEC §7.3.1: validated `evidence_lookup` + nonempty validated requested fields **ALL lack verified support (所有要求欄位都缺少)** => one materially different same-authorized-scope recheck when safety/eligibility/budgets permit, even with unrelated citations. Partial misses MUST be disclosed/MUST NOT trigger; blanks are verified coverage; empty resolve validated plan/clarify. Zero citations/status/projection failure alone cannot trigger/establish eligibility. Eligible immutable source lookup needs no failed projection, keeps source/hash/lineage/revision/permission/no-rebuild. ANY missing diagnostic identity => incomparable is separate. Exact stays deterministic; errors/denial stay errors, incomplete never means absence. Docs fixed; runtime all-fields predicate/tests/UAT remain 待測.
  - Acceptance verifies citations against source/content, not counts alone; retain ordinary-chat MCP=0, both mail and independent-document paths, reload/reset, and contextless-chat MCP=0. Promotion still requires safety/exact/incomplete checks, full regression, three reviewers, and authority gates.
  - 2026-10-07 current UAT remains unaccepted: dated first-source lifecycle `09:55:11.467–09:56:54.434Z` exited `0` with `10` shown citations but incomplete coverage and `source_binding_verified=false`; earlier `08:59` lifecycle with `11` shown citations, `08:20` projection HTTP `500`, `08:29` timeout, `08:01` lifecycle failure, `08:08` basic pass, and `08:10` delivery `pending_review`/zero citations remain distinct evidence. That dated pass and the 2026-10-07 timeout remain historical evidence; the 2026-10-08 browser smoke now passes ordinary chat and `嘉值交期` with MCP/citations, but `source_binding_verified=false` keeps formal acceptance open. The smoke does not reproduce the earlier projection error or prove its root. Source-start/mail/document checks, routing/provider/projection-integrity/JSONRPC/OAuth checks, native-hash checks, and focused runtime checks are diagnostic only and do not establish live acceptance or readiness.
  - Historical 2026-10-04–2026-10-06 runtime, worker, browser, parser, and retention diagnostics remain in the handoff and immutable snapshots; they are superseded evidence, not current work orders, and do not authorize reruns.
  - [ ] Verify the diagnostic comparability/observability precondition: bind loaded deployment/code/build/source fingerprints and preserve top-level/per-attempt canonical request-shape, full tool-descriptor fingerprint, upstream HTTP status, terminal outcome, and valid-attempt marker. This is not a fifth methodology gate; missing evidence yields `diagnostic_only/incomparable`, and provider failure never becomes absence/`not_found`.
## Phase Summary — 2026-08-29 baseline
- Historical 2026-10-02 worker setting retained under this 2026-08-29 baseline, not current dispatch authority: user-supplied two ordinary `gpt-5.6-luna`/`max` workers differed from older disk one `gpt-6-luna`/`max` A; requested model was unavailable, with no substitution/dispatch. A was paused, B closed; temporary `gpt-6-astra`/`xhigh` reviewer had bounded authority only, no descendants or independent release credit for its code. Master was orchestration-only/15-minute active monitoring; UAT `gpt-5.5`/`high`. See [roles](agent-roles.md).
- Dated worker settings and operational snapshots below are historical, not current dispatch/restart authority; the current five-step plan and independent three-reviewer gate remain unchanged.
- The active KG program is GitHub issue #56, not the historical issue #33 plan or issue #55 document-first POC.
- Frozen method and tokenizer remain `evidence_to_knowledge_kg_ontology_v2_hybrid_v1` and `jieba_sentencepiece_frozen_profile_candidate_admission_v1`.
- Pinned methodology authority is valid but blocked. The normal runtime-method gate is passed;
  source completeness, accepted execution-fingerprint binding, same-pipeline real-source ablation, and independent final-answer acceptance remain blocked.
- The existing safe source-completeness report passes its own sealed contract:
  `8,443` raw/source inventory units reconcile to `8,443` Observations with
  unexplained loss `0`. Its report/snapshot fingerprints are
  `sha256:9bf59781bb846f87934511fe7378626eddd380cbe9e1acea201aa0625f11f8b6`
  and
  `sha256:55df0dc7d96a7822271f4b7f4509b4da1bbb94f26bb7710e3919f8134d28f2d1`.
  The authority gate remains blocked because no formal all-four-gate evidence
  bundle has been authored and atomically promoted.
- Commits `6e4663a` and `ad08b22` implement the current source-to-promotion
  binding slice: the source evidence author validates the exact complete
  execution bundle against report, source, counts, and authority before
  output, while promotion preflight accepts the existing v3
  `execution_binding` and cross-binds it to the single validated dependency.
- Pinned-E5 focused E2E passed `48/48`; both cross-reviews returned `AGREE`
  after one private-helper dependency blocker was corrected to use the public
  bundle loader.
- The generic participant-any deterministic inventory now runs an actual-user
  request through `ConnectedRuntime`, OAuth, and normal ASGI `/mcp` with typed
  intent. The raw request is not retained; its request fingerprint is
  `sha256:ace0484e2706d363d53a4733e269e1c0814fc9629d5ad8ebf2f1a645f4621d1d`.
- The run completed `21` bound-cursor pages with
  returned/total/union `2069/2069/2069`, duplicate count `0`, and `2086`
  governed references/citations. Per-page HTTP latency was
  `260.323–319.288 ms`, total query HTTP time was `6415.888 ms`, and one-time
  compose/load time was `600090.276 ms`.
- Coverage correctly remains `incomplete`: the full permission-authorized
  scope is `2793`, partitioned into `2069` matches, `174` proven nonmatches,
  and `550` unresolved occurrences, with unsupported/redacted `0/0`. The
  unresolved source gap is primarily legacy or malformed participant evidence
  that the standard mailbox parser cannot recover. Therefore neither “all”
  nor production readiness is supported.
- The source-native conversation-closure experiment was removed. This run did
  not use the `317` oracle; that count belongs to a different private prompt
  and cannot be compared with this actual-user request.
- Full coverage is measured against the permission-authorized sealed-source
  occurrence scope, not the smaller retrieval projection. The lineage
  crosswalk cache key and owner/gateway validation bind the same
  index/graph/source-session fingerprints.
- The latest focused pinned-E5 verification passed `62` tests with `0`
  skipped. `authority_valid=true` and `methodology_ready=false`; the authority
  execution fingerprint is
  `sha256:78cebbb2af8c6e4bcde3f2819436c6f62bd34e957f381dff610bf8a0a477711d`.
- No formal evidence was authored or promoted, and no methodology-quality UAT,
  independent holdout, transfer, or v1-v7 diagnostic rerun occurred. The same
  four authority gates remain blocked; no readiness, superiority, or
  completion claim is supported.
- Strong RAG is a required component/control. KG adds heterogeneous identity,
  joins, bounded topology, time, contradiction, provenance, and coverage.
  Ontology is scoped/data-first/capped soft scoring. Exact sets use a
  deterministic executor.
- The existing five-step POC plan is unchanged and step 4 remains `in-progress`.
- Actual ingestion now composes `11,386,691` Observations into `2,688,156`
  retrieval units with `668,391` unique dense texts. Replacement v3 completed
  preprocessing and waits resident before E5 at `36.95 GiB`; its marker is
  absent and all source/preparation checkpoints remain preserved.
- The original eager v3 `48 GiB` route is not bounded through completion: measured vector
  objects require `7.694 GiB` retained/`9.699 GiB` minimum overlap, while graph
  construction, full serialization, and reload add whole-corpus copies and
  reload loses vector sharing while ignoring the written graph artifact. The
  isolated `13.2 h` embedding extrapolation is not an ETA.
- Old UAT is unchanged. Step 4 earns no checkbox, quality/readiness claim, or
  #56 close. September 8 user authorized wider existing-owner compact/lazy
  integration through first MCP query; heavy run/staging awaits resource review.
- September 8 existing-owner compact/lazy diagnostic uses isolated FormOwl PG
  with existing five migrations/schema installed and container memory limit `2 GiB`.
  Source-neutral `64` prepared refs -> `61` candidates/`57` real pinned-E5 unique
  texts; stored build passed in `145.968 s`, peak `1.606 GB`; fresh reload
  passed, peak `2.127 GB`. This is not a full-source result.
- Initial normal MCP rejected provider scope whole-collection iteration; A
  fixed keyed validation. Preserved replay: HTTP `200`, tool error false,
  owner exceptions `0`, status `replan_required`, class `global_summarization`,
  citations `0`, coverage `incomplete`, stop `external_replan_required` /
  `review_authorized_capabilities`. No actual browser-GPT prompt completed.
  Master September 8 09:46 read-only check: full v3 running/unpaused/OOM false
  at `48 GiB`, resume marker absent; old UAT and isolated PG (`2 GiB`) running;
  separate canary browserstagev2 running/OOM false at `2 GiB`, not an activated
  replacement. No services were stopped or restarted for this handoff.
- September 9 05:10 +08 supersedes earlier capacity/canary waits: same-model
  B resumed; batch-store fixture passed, SQL calls `29->15`, contents equal.
  Metadata-repaired browser canary reached two MCP replans then clarification,
  `0` citations: pipeline diagnostic only, not cited-answer/UAT acceptance.
- Full helper v2 completed reference indexing of the composed preparation/revision:
  ALL `2710511/2710511` refs committed at `60729.727 s`, RSS `1.02 GiB`.
  Metadata/child-parent closure remains pending; no metadata-ready/pre-E5 event.
  Helper/PG running/OOM false; `8 GiB`/no swap helper cap, all markers absent.
  V1 intentional stop was exit `137`, OOM false; stopped, PG-postrestart and
  actual v2-reader cursors all `648448`, at most `256` idempotent replay refs.
- Isolated PG initially had `2 GiB`; after one approved settings restart
  (`shared_buffers=512MiB`, `max_wal_size=4GiB`, durability ON), measured cgroup
  pressure justified a live cap-only increase to `8 GiB`/no swap at 12:36:34.
  That update restarted nothing; helper, PG, original v3 and old8088 retain
  their process starts and are running/OOM false. Host available was `16.85 GiB`
  at 13:03. Adjacent 32768-ref windows `727.628->538.773 s` are not a validated ETA.
- Original v3 remains resident pre-E5; all three release markers are absent.
  Helper safetywatch pauses at RSS/anon `6 GiB` or host available below `8 GiB`.
  No raw-source rerun, E5, graph, activation, additional tuning or code changes
  are authorized. PG restart invalidated private-canary connections; artifacts
  remain preserved, not query-ready. At 16:40 all four services remain running,
  OOM false, original PIDs/start times; all three release markers absent. Helper
  and safetywatch run independently; workers idle without pending actions. Master
  checks only during active turns, not after final. Notify pre-E5, do not release.
- September 9 06:11: one-line owner ORDER parentheses fix plus exact page-index
  C-collation deployment aligned; A guard/lint passed, corrected EXPLAIN no Sort.
  V2 intentional stop exit137/OOMfalse; same-revision helper v3 launched06:08.
  Actual refs resume2710511/zero replay and saved metadata cursor verified;
  subsequent exact-PK cursor advanced. Only corrected public index remains.
  September9 09:49:40 Master-approved pre-E5 ONLY released after verified closure.
  First32vectors/49152bytes durable, then32candidates persisted;09:51 snapshot
  323uniquevectors/352candidates/496128bytes,firstblockchecksum verified. RSS1.22GiB;
  CPU E5profile39185d72...,batch32/threads4/safety unchanged; no validated ETA.
  CURRENT Sept9 10:44: helperv3 exited1/OOMfalse10:29:45, frozen text-lineage
  mismatch; A owns fix. Durable5232vectors/8036352bytes,6688candidates preserved.
  BbulkDMLworkspaceONLY: samefixturebefore/afterPASS;upserts3->1/4->1/4->2.
  Integrated2/2PASS8.098s+lint; approvedv4 launchedSept9 11:42:44+08/runningOOMfalse.
  Refs2710511/finalmetadataresume verified;192candidates replayed by11:47 using
  preserved5232-vectorcache;6688boundary pending. Pregraph/original gates absent.
  Samecaps/watchers; fourmethodologygatesblocked, no graph/UAT/ETAclaim.
- The 2026-09-06 integrated real Chromium LAN UAT preserved five turns and
  reload, returned `12` browser-visible same-row CRI part-number/L/T pairs with
  `24` citations, retained the pairs through table reformat, and cleared real
  server state before a contextless clarification. Request timings were
  `29.062`, `58.304`, and `32.187 s`; the post-reset clarification was
  `4.854 s`. Temporary bounds are `64` visible turns, `8` model messages, and
  `1` hour without cross-restart persistence. Focused checks passed `4/4` and
  `8/8`; the full suite remains interrupted/non-green. This is a bounded POC,
  not a checkbox, production/readiness, generality, or superiority result.
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
- Formal v7 mode
  `issue56-sealed-source-real-prompt-relation-projection-offline-equivalence-phase-traced-diagnostic-20260825-v7`
  consumed its canonical claim and passed over the same `456` Observations as
  `workspace_only_v1` for `workspace_formowl`, approved actor
  `user_full_pst_domain_hard_case_eval_owner`; no tenant dimension exists.
- The two isolated presealed views each bound `10281` nodes and `29748` edges.
  Cold/after graph preseal took `61825.028571`/`61485.804325 ms`; the after-arm
  relation precompute took `4344.986693 ms`.
- After the persistent claim, the cold binding snapshot and base builder took
  `633.968035` and `3196.093676 ms`; offline precompute total was
  `35771.614738 ms`, and its cache moved exactly `0/0 -> 1/1`.
- Both arms then used the normal `1500 ms` budget through complete ASGI `/mcp`.
  Cold/after query times were `290.941898`/`298.654947 ms`, HTTP times were
  `366.720007`/`361.008008 ms`, and relation projection was
  `57.473886`/`58.790683 ms`. Each returned `10` paths, `1` citation, and `48`
  scores with no exhausted deadline.
- All `13` timing-free semantic equivalence groups, all `5` cache acceptance
  checks, and every applicable boundary gate passed.
- V7 claim/claim-byte/report-byte hashes are
  `sha256:879e903599e95d38d52e0bd1fb0d29fb6266371e7168289547d0bbc23a1d643b`,
  `sha256:4de4d694f042f46b3a0d6c68dd93101ca7c7610a0b3f97496f44be34f20b7a0c`,
  and `sha256:5b34d191244391c560cda849c0666c2f7e41be1d220fd3799108b6ca738a99d0`;
  claim/report sizes are `1508`/`30893` bytes.
- Trace/execution/source/preflight/offline-evidence/owner/precompute/cache bindings are
  `sha256:9af61b1918c6ef2c31a91a8d6f73a875e796bbf678b13c49f7db44530189e6d6`,
  `sha256:a99e1fa89b01d2d383209ae09f742ee55cfddcd2095992c9391878d73b00c649`,
  `sha256:b5a8112dd88eb829b26ec7b795a6071ca81a6327362a0d265c1749d41c5f002e`,
  `sha256:10c44440e0cde947591af7c8ad9797ba47b755d50d027d280c0cfa464dd8baf0`,
  `sha256:bd6d0e962d07ba10f273caa83996a6e57114d6801d56660c551d3728a655fdf1`,
  `sha256:8f63bdcf6baa4d18b6574071905900baf002318d9227e0d0da0523bf297a293e`,
  `sha256:b2edcd214a19a6b3283abc475a8b67abd984753653a6136396b1630bfbfecf3b`,
  and `sha256:d15cf0214e9112b1a28130496dc5ea0c554587606e32dd423886ee14364e110f`.
- Temporary v7 evidence passed `51/51`; final cross-review found no blocker.
  Together with v6's latency-necessity evidence, v7 establishes the bounded,
  behavior-neutral, same-real-source relation-precompute POC. It is not
  methodology, UAT, holdout, readiness, completion, or superiority evidence.
- Diagnostic versions v1 through v7 are consumed and must never be rerun,
  retried, or tuned. The four methodology authority gates remain blocked.
- V4 is neither an independent holdout nor promotion evidence and
  cannot support KG/ontology superiority. The sealed 41-case and additive
  59-case mail holdouts and the GitHub transfer holdout remain unexecuted.
- The v3 gate-evidence-to-atomic-promotion contract is implemented and focused
  tests pass, but no formal all-four-gate evidence bundle exists to promote.
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
    bounded v4/v7 POC diagnostics or blocked v5/v6 diagnostics.
  - The participant-any inventory sub-slice is generic and verified, but its
    actual-user execution remains incomplete over the full authorized scope:
    `2069` matches, `174` proven nonmatches, and `550` unresolved occurrences.
    Work D therefore stays unchecked; no conversation expansion or comparison
    with the unrelated private-prompt `317` oracle is authorized.
  - The next action remains inside step 4; v1-v7 must not be rerun, and all four
    blocked authority gates still require legitimate production evidence.
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
- [x] The bounded deterministic source-backed prompt selector and immutable
  v4/v7 real-source diagnostic POC slices passed their stated non-claim-bearing
  scopes.
- [x] Source/Asset/Observation, mail evidence, Project MCP, Wiki MCP, connected
  gateway, and container-first backbone slices exist within their documented
  claim boundaries.
- [x] Historical issue #55 document-first POC completed as a bounded non-KG
  smoke; it is no longer an active methodology direction.
- [x] Active KG/methodology documentation was losslessly archived and rewritten
  around issue #56 on 2026-08-18.

## Pre-Feature Cleanup

Completed production and structural cleanup records remain immutable history under `docs/archive/2026-08-18/active/`; no historical cleanup item is reopened by the issue #56 rewrite.

## Dispatch

Choose an unchecked item owned by the active role unless the user explicitly
assigns cross-role work. Do not use archived or historical-pointer documents as
next-action authority.
