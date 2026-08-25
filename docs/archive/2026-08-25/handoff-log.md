# Agent Handoff Log
Lifecycle label: `active`.
This is a bounded active window. Earlier entries are immutable history under
`docs/archive/`, including the complete pre-rewrite log at
`../archive/2026-08-18/active/docs/agent-goals/handoff-log.md`.
## Retention Rule
- Keep the latest 14 calendar days and at most 300 lines.
- Archive a complete dated entry before trimming it.
- Record only current facts, blockers, verification, and next action.
- Historical pointers are not restart instructions.
## 2026-08-25 — Offline relation-precompute v7 consumed and passed
- Formal mode `issue56-sealed-source-real-prompt-relation-projection-offline-equivalence-phase-traced-diagnostic-20260825-v7`
  consumed one claim over `456` Observations as `workspace_only_v1` for `workspace_formowl`; approved
  actor `user_full_pst_domain_hard_case_eval_owner`; no tenant exists.
- Both isolated views held `10281` nodes/`29748` edges; cold/after graph preseal
  was `61825.028571`/`61485.804325 ms`, and after relation precompute was `4344.986693 ms`.
- Post-claim cold binding/base/total was `633.968035`/`3196.093676`/`35771.614738 ms`,
  with exact cache transition `0/0 -> 1/1`.
- Both normal `1500 ms` ASGI `/mcp` arms completed: cold/after relation was
  `57.473886`/`58.790683 ms`, query `290.941898`/`298.654947 ms`, and HTTP
  `366.720007`/`361.008008 ms`; each had `10` paths, `1` citation, `48` scores,
  and null deadline exhaustion. All `13` timing-free equivalence groups, all
  cache acceptance checks, and all applicable boundary gates passed.
- Claim/claim-byte/report-byte are `sha256:879e903599e95d38d52e0bd1fb0d29fb6266371e7168289547d0bbc23a1d643b`,
  `sha256:4de4d694f042f46b3a0d6c68dd93101ca7c7610a0b3f97496f44be34f20b7a0c`,
  `sha256:5b34d191244391c560cda849c0666c2f7e41be1d220fd3799108b6ca738a99d0`; claim/report sizes are `1508`/`30893` bytes.
- Trace/execution/source/preflight are `sha256:9af61b1918c6ef2c31a91a8d6f73a875e796bbf678b13c49f7db44530189e6d6`,
  `sha256:a99e1fa89b01d2d383209ae09f742ee55cfddcd2095992c9391878d73b00c649`,
  `sha256:b5a8112dd88eb829b26ec7b795a6071ca81a6327362a0d265c1749d41c5f002e`,
  `sha256:10c44440e0cde947591af7c8ad9797ba47b755d50d027d280c0cfa464dd8baf0`.
- Offline-evidence/owner/precompute/cache are `sha256:bd6d0e962d07ba10f273caa83996a6e57114d6801d56660c551d3728a655fdf1`,
  `sha256:8f63bdcf6baa4d18b6574071905900baf002318d9227e0d0da0523bf297a293e`,
  `sha256:b2edcd214a19a6b3283abc475a8b67abd984753653a6136396b1630bfbfecf3b`,
  `sha256:d15cf0214e9112b1a28130496dc5ea0c554587606e32dd423886ee14364e110f`.
- Temporary evidence passed `51/51`; final cross-review found no blocker.
  With v6 latency necessity, this accepts only the behavior-neutral same-source
  relation-precompute POC. V1-v7 cannot be rerun; four authority gates remain
  blocked, Work D stays in progress, and no broader claim is earned.
## 2026-08-25 — Graph-presealed relation-projection v6 consumed and blocked
- Formal v6 consumed the same workspace-only `456` Observations with no tenant.
  Loader/preseal/owner precompute were `677442.490893`/`60990.781102`/`4245.079389 ms`.
  Cold relation exhausted at `1415.389724 ms` (`1520.515069` query/
  `1555.417065` HTTP; `0` paths/citations/scores); primed relation/query/HTTP
  were `57.939772`/`291.040282`/`346.270890 ms` with `10` paths/`1` citation/
  `48` scores. Caches were `0/0 -> 1/0` versus `1/1 -> 1/1`.
- Claim/claim-byte/report-byte were `sha256:6b045800e19d82fa187ff4271ab2d854189726a3449bcd4cedf1c03c47c2639e`,
  `sha256:65b3b3d1f9889e1d82ec47ade77fb7dc44b4a9a3711f7bd37a538cdc9e986b61`,
  `sha256:ae10a358242f6f44b1f92267a80e48eac296ebd677eb1ac27bcc24f6111909f1`;
  execution/source/preseal/trace were `sha256:7ecf2c31901116ddb32d2a8a7cb41b0e3b504648006a68b3e23e89ee22b2c1cf`,
  `sha256:bbc67d7fc7051a597488034d277c772a4a5c68bc09dc8ce696bfd2bcc0d8db8b`,
  `sha256:4900fd366f300af097de355b59feeb6059a06b41574d01d9834e51576c4eed27`,
  `sha256:040cb86b70af99fd6f0467306423e0e556a6dfc41b1ed734227b613248c27a93`.
- Tests passed `6/6` and `31/31`; review found no blocker. V6 is immutable,
  blocked, and earns no readiness or superiority claim.
## 2026-08-23 — Source-backed real-prompt v4 diagnostic passed
- Source tracing found both synthetic fixed-prompt terms at count `0` in
  raw/parser/retrieval; the cause was prompt-to-approved-source mismatch.
- The deterministic source-backed connected selector passed `11/11`. V4 then
  consumed one claim over the same workspace-only `456` Observations with no
  tenant and passed with `2` anchors, `10` paths, and `1` citation.
- Query/gateway/HTTP were `951.148333`/`953.544449`/`982.203990 ms`;
  relation projection was `717.357210 ms`, deadline exhaustion was null, and
  one-time loader time was `678625.866681 ms`.
- Claim/claim-byte/report-byte were `sha256:2b092814194dd90d597161dfcd04822be75c97fc5c5364478bbc8b52307098cb`,
  `sha256:76dda5b18801a7587b212631b0d4d7ae0544646910e143ced0883f14e5db69b8`,
  `sha256:40f48fea0145d523f5d14e2943b41750a48923e111cdf6e6c5e3cd265903a458`;
  trace/execution/source were `sha256:4b518dd33bc406027f2fe0104559ead2cdb27a096b3357d9470acdac34e09ef4`,
  `sha256:031cfe6f04c9b595bed6fd24375590a78df18dd03e07b68821c955bc03ad0b94`,
  `sha256:b3959bba1267879ba3bcc6889fd063363f899987722b2447685aad844f6b53ae`.
- Full regression remains non-green (`1873` total / `1781` passed / `54`
  failures / `23` errors / `15` skips); V4 passed but earned no broad claim.
## 2026-08-21 — Sealed-source v3 diagnostic consumed and blocked
- Mode `issue56-sealed-source-phase-traced-diagnostic-20260821-v3` consumed its
  claim exactly once over `456` Observations as `workspace_only_v1` for
  `workspace_formowl` and approved actor
  `user_full_pst_domain_hard_case_eval_owner`; no tenant dimension exists.
- Cold lineage-crosswalk and relation-base precomputes completed outside the
  query in `1814.676079` and `5742.217351 ms`. The query crosswalk cache hit,
  Strong RAG, and relation projection completed in `0.039415`, `78.995342`, and
  `755.393432 ms`.
- The query completed in `935.503846 ms`, HTTP in `999.641434 ms`, and loading
  in `616997.490158 ms`. No deadline was exhausted; every semantic phase
  completed except skipped deterministic exact execution.
- The safe cited response remained blocked with `0` citations and `0` graph
  paths. Relation-base precompute succeeded, but relation projection remains
  the largest query phase and no cited graph proof was produced.
- Immutable bindings: claim
  `sha256:31e2c3dd9d401790ca202ed8d9caa35a30195880e4007cb6813b7b13852ecb47`
  (`916` bytes; byte seal
  `sha256:793a801d7786413211979c13218c4795cb71210c65dd36024c37fa3b1dfd6946`);
  report `10144` bytes,
  `sha256:29ebb91fed63f288a88eae6f966d30fa5b125c5da5b70cf35f5940b810dd0f57`;
  safe trace `sha256:c71ca6d55b1f911043ce50e9fb5c7fcceefd7965a6495eb1e6cce81f9f108dc8`;
  source binding
  `sha256:eb384e63374c72ee18509f5f396ca9a134b7a667447308effbf906409ee35249`.
- V3 must never be rerun, retried, or tuned. It is diagnostic-only evidence:
  no quality, holdout, transfer, readiness, completion, or superiority claim is
  earned. Issue #56 Work D and plan step 4 remain incomplete/in progress.
- Canonical authority remains valid but blocked on source completeness,
  accepted execution-fingerprint binding, same-pipeline real-source ablation,
  and independent final-answer acceptance.
- Next: stay in step 4; diagnose the generalized zero-path/zero-citation result
  and remaining relation-projection cost only under separate approval.
## 2026-08-21 — Sealed-source v2 diagnostic consumed and blocked
- Mode `issue56-sealed-source-phase-traced-diagnostic-20260821-v2` consumed its
  claim exactly once over `456` Observations. It ran as `workspace_only_v1` for
  `workspace_formowl`, approved actor
  `user_full_pst_domain_hard_case_eval_owner`, with no tenant dimension.
- Cold lineage crosswalk precompute completed outside the query in
  `1806.696423 ms`; the query cache hit took `0.027371 ms`. Strong RAG completed
  in `75.098477 ms`. `relation_projection` then exhausted the `1500 ms` budget
  after `1421.788584 ms`.
- Query, HTTP, and loader totals were `1508.602094`, `1536.543591`, and
  `612559.303406 ms`. The blocked result had `0` citations and `0` graph paths;
  traversal, scoring, proof/citation, fallback, lineage audit, and result
  projection were skipped.
- Safe bindings: claim
  `sha256:6f88dc0c21ba3323fa17e015f014a79603351d4ed52b5dbedb98b5f63a97e1a1`;
  claim bytes
  `sha256:24c81028643d8e959f2b3897a78ce70fdf702767a4ff7b4cdf842511718c94ab`;
  report bytes
  `sha256:13b8fa56d803c055c861ad029619fa822da4e5746d471d0570336f61053c3399`;
  safe trace
  `sha256:c0427da8cf969fe2d46cdbef4c2f971026334cf13cc3095beed6a33fc6123fbb`;
  source binding
  `sha256:362ed66da7ba3a8a3b9ebc4fd46d3b0c29ebf0340851961b108a8544f2fd6379`.
- Crosswalk optimization succeeded for this diagnostic and exposed
  `relation_projection` as the next bottleneck. It does not retroactively prove
  the earlier one-shot's `1510.841 ms` p95 cause.
- V2 is consumed and must never be rerun, retried, or tuned. This is diagnostic
  evidence only: no checkbox, readiness, completion, or superiority claim is
  earned. Authority remains valid but blocked on four gates; holdouts and
  transfer remain unexecuted.
- Next: stay in step 4 and require separate approval for any generalized
  relation-projection optimization/diagnostic version.
## 2026-08-20 — Versioned minimum MCP-to-Hybrid diagnostic passed
- The user approved a versioned, non-claim-bearing minimum E2E plus
  phase-tracing diagnostic slice. It used only a `synthetic_non_sealed`
  workspace-only fixture.
- The passing path was prompt -> Starlette/ASGI HTTP POST `/mcp` -> synthetic
  preverified principal -> `RemoteMcpDispatcher` actor-context injection ->
  `SemanticMcpGateway` -> `AuthorizedSemanticMailSession` -> deterministic
  safe cited response. It returned `2` citations and `2` graph paths.
- Canonical focused evidence records the existing `25` tests plus the new `5`
  tests passing. The safe phase trace can identify
  `deadline_exhausted_phase` for a new execution.
- This evidence does not retroactively identify the exact phase behind the
  consumed one-shot's `1510.841 ms` p95, and that 100-case execution remains
  consumed and prohibited from rerun, retry, or result-driven tuning.
- Sealed source assets, external Google OAuth exchange, browser UI, production
  store, production connected-tool policy, and a real LLM were not exercised.
- Methodology authority remains valid but blocked on source completeness,
  accepted execution-fingerprint binding, same-pipeline real-source ablation,
  and independent final-answer acceptance. No issue #56 checkbox, production
  readiness, methodology readiness, or superiority claim is earned.
## 2026-08-20 — Workspace-only development one-shot consumed and blocked
- The sealed development work root
  `.test-tmp/issue56-development-uat-v2-workspace-only-work` passed its exact
  `456`-Observation artifact and identity-scope contract.
- Identity scope is `workspace_only_v1` for `workspace_formowl`. No
  `tenant_id` field or key exists; none may be inferred or fabricated.
- The development diagnostic claim
  `issue56-development-workspace-only-diagnostic-one-shot-20260820-v1` has been
  consumed. It is exactly-once state and must not be rerun, retried, or tuned.
- Its safe report is blocked: Hybrid `0/100`, graph paired CI `[0,0]`, citation
  support `0%`, no-answer false positives `100`, p95 latency `1510.841 ms`,
  and permission leakage `0`.
- This execution was a development diagnostic, not an independent holdout. It
  cannot support authority promotion, KG/ontology superiority, methodology
  readiness, or completion.
- The methodology authority remains valid but blocked on source completeness,
  accepted execution-fingerprint binding, same-pipeline real-source ablation,
  and real-user final-answer acceptance.
- The production v3 gate-evidence/atomic-promotion contract blocker is fixed
  and focused tests pass. No passed gate evidence currently exists to promote.
- The sealed 41-case and additive 59-case independent mail holdouts and the
  GitHub transfer holdout have not executed.
- Plan step 4 and all corresponding board tasks remain unchecked. The sole next
  action is a governance/specification decision plus a read-only postmortem;
  another execution is prohibited.
## 2026-08-19 — Issue #56 step-4 development diagnostic status
- The pinned methodology authority is valid but blocked. The normal runtime-method
  gate is passed; four gates remain blocked: source completeness, accepted
  execution-fingerprint binding, same-pipeline real-source ablation, and independent final-answer acceptance.
- The `node-term-lineage-v3` development run remains diagnostic: Hybrid `60/100`,
  graph-required paired gain `+60` percentage points with the paired-CI check passing,
  citation precision `98.74%`, and authorized hop evidence `4083/4083`.
- Acceptance is still blocked by positive-case no-answer false positives `3 > 1`
  and Hybrid p95 latency `4036.462 ms > 3000 ms`; Hybrid p50 was `2782.821 ms`.
- Phase timing was strict projection p50/p95 `33.084/33.823 ms`, fallback repair
  p50/p95 `0/1287.977 ms`, and graph traversal p50/p95 `2126.683/2155.965 ms`.
  Strict proof passed `62` cases and failed `38`; fallback ran `38` times and targeted retraversal ran `4` times.
- The behavior-neutral three-case `v5` diagnostic preserved the corresponding
  `v3` runtime results. Across 30 paths, rejection counts were
  `path_term_support_missing=29` and
  `support_only_on_connected_off_path_node=1`; evidence-budget rejection was
  zero. This localizes the remaining family to incomplete selected-path
  projection of source-bound required-slot support, not a budget rejection.
- Safe artifacts:
  `issue56-node-term-lineage-v5.diagnostic.safe.json`
  (`sha256:a053bf9252fa642373fba326474b08aab51e4090b5df6471359f42186de720c7`)
  and `issue56-node-term-lineage-v5.trace.safe.json`
  (`sha256:2d3a3952005dbac94c5b434bf818aa70d2dab3d0a30077064d4d654e2ab75490`).
  They are diagnostic-only and cannot support quality, budget, completion, or
  methodology claims.
- Copernicus dispatch as the required `gpt-5.6-sol`, `reasoning_effort=ultra`
  second worker failed twice with `prompt_cache_retention`; the team did not
  substitute a model, add a worker, or let the Master implement.
- Plan step 4 remains `in-progress`; the existing five-step wording is
  unchanged. Next, after restoring the second-worker slot, split disjoint work
  into a per-query projection cache and bounded source-backed proof-completion
  E2E. Do not execute a sealed independent holdout yet.
## 2026-08-18 — Master plus two-worker, POC-first operating mode
- The user set the issue #56 execution topology to one Master plus exactly two
  implementation subagents. Both workers use `gpt-5.6-sol` with
  `reasoning_effort=ultra`.
- The Master owns a global plan capped at five steps, non-overlapping work
  assignment, progress monitoring, duplicate/loop prevention, integration
  review, and final acceptance. The Master does not implement code; all
  implementation is delegated to the two workers.
- Worker write sets must not overlap. If the same blocker or method fails
  repeatedly, the Master must change the decomposition, owner, or validation
  route rather than continue an unlimited retry loop.
- POC acceptance requires a real source/Observation-to-result end-to-end path.
  API, contract, schema, mock, or unit wiring by itself is insufficient.
- The operator reported an approximately six-hour window before a power outage
  on 2026-08-18. The immediate decision is therefore fast E2E POC first;
  optional hardening, onboarding, and broad suites may wait until feasibility
  is shown.
- The time box does not relax permission, privacy, provenance,
  candidate-before-canonical, no-secret, no-raw-path, redaction, audit, or
  fail-closed methodology authority. A POC is not production readiness,
  implementation completion, comparative superiority, or methodology
  completion.
- Two-worker E2E evidence may support rapid POC continuation after Master
  integration review. Formal implementation completion, release, and
  production hardening still require the existing three independent read-only
  Codex/GPT reviewer decisions unless the user explicitly changes that count.
- Issue #56 remains `active-blocked`. The frozen method is
  `evidence_to_knowledge_kg_ontology_v2_hybrid_v1`; the frozen tokenizer is
  `jieba_sentencepiece_frozen_profile_candidate_admission_v1`. No checklist
  item was completed or checked by this operating-mode update.
## 2026-08-18 — Issue #56 becomes the sole active KG methodology program
- GitHub issue #56 defines the active objective: graph-guided Hybrid KG +
  Ontology v2 must earn a measurable final-answer win over strong RAG on
  heterogeneous integration tasks.
- Frozen target remains
  `evidence_to_knowledge_kg_ontology_v2_hybrid_v1` with
  `jieba_sentencepiece_frozen_profile_candidate_admission_v1`; no v3 was
  created.
- Architecture is strong RAG retrieval plus reviewed entity links, bounded
  graph traversal, temporal/provenance/coverage filtering, capped soft ontology
  scoring, evidence-bundle reranking, and deterministic exact-set execution.
- Inferred ontology mismatch no longer prunes admitted evidence. The old hard
  gate is a negative ablation only.
- The final answer model is not an architectural shortcut: every arm must pin
  and share the same model, prompt, reasoning effort, schema, and budget.
- Independent holdout questions cannot influence tokenizer, aliases, ontology,
  graph rules, thresholds, prompts, or model choice.
- PostgreSQL/pgvector remains canonical. Do not resume Neo4j benchmarks,
  migration, projection, or dual-write work.
- Issue #55's document-first exactly-one-call POC and issue #33 plans are
  historical only. Their complete active-file state before this rewrite is
  preserved under `docs/archive/2026-08-18/`.
- Methodology authority check is valid but blocked. Runtime remains
  `ascii_identifier_regex_v1` with CJK support false, and all five readiness
  gates remain unresolved.
- Next KG action: implement the immutable target tokenizer/profile and
  same-profile query/evidence binding, then source-completeness reconciliation
  and a strong RAG control. No methodology-quality comparison may start while
  `--require-ready` exits nonzero.
- The Issue #20 operator helper now derives or validates one safe non-secret predefined client ID; app configuration replaces only the ChatGPT-displayed callback; if the same client ID cannot be used, the live campaign stops as an external blocker.
- Issue #20 remains open and unchecked; this KG documentation rewrite does not change its external evidence state.
## 2026-08-18 — Active-document rewrite verification
- Active KG, architecture, workflow, provenance, infrastructure, evaluation,
  role, goal, and startup documents now point to issue #56 and the frozen
  Hybrid-v2 target. Superseded mail-only, issue #33, and issue #55 files are
  explicit historical pointers; their pre-rewrite content remains immutable
  under `docs/archive/2026-08-18/`.
- `python3 scripts/methodology_authority_check.py --check` passes with 56 bound
  sources. Authority remains valid but blocked; all five readiness gates remain
  unresolved and `--require-ready` must continue to exit nonzero.
- The focused documentation/methodology/container suite passed 150 tests with
  one skip. The canonical full suite ran 1,558 tests and is not green:
  11 failures and one error remain in legacy coordination-frame metrics,
  Issue #20 function-onboarding state, and an unrelated PST extractor test.
  Those failures are outside this documentation rewrite's write set and were
  not hidden or broadly repaired.
- Issue #20 remains open and unchecked; this documentation-only verification
  does not change its external evidence or closure state.
- Next KG action remains Work Package A: immutable Jieba + SentencePiece
  profile packaging and same-profile query/evidence indexing, followed by
  source-completeness reconciliation and the strong RAG control.
## 2026-08-20 — Sealed-source loader verification boundary
- The full `formowl-dev:local` suite ran `1,849` tests with `20` failures,
  `19` errors, and `15` skips. In that image, the same focused `26`-test slice
  had `15` `DenseEmbeddingUnavailableError:
  python_runtime_version_mismatch` errors; the pinned E5 image passed all
  `26`. The full canonical suite is therefore not green, and this slice remains
  non-complete and non-release.
