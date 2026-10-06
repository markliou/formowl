# Agent Handoff Log

This active log is a bounded recent window. Lossless prior history is preserved
at `../archive/2026-07-11/handoff-log.md`.

Lifecycle label: `active`.

## Retention Rule

- Keep entries from the latest 14 calendar days, with a hard cap of 300 lines.
- If either limit is exceeded, archive the oldest complete dated entries into a
  new immutable dated snapshot before appending more.
- Never split a dated entry, discard content, or rewrite archive history.
- Append only concise cross-agent facts, blockers, verification, and next action.

## 2026-07-10

- Issue #33 Work Package A completed on `issue-33-work-package-a` from merged
  Ontology v2 PR #31. The EXM evaluator now uses candidate-admission arm names,
  declares KG/type/frame stage boundaries, uses development/evaluation labels
  instead of same-corpus holdout language, excludes permission-denied
  auto-passes from primary retrieval accuracy, and emits eight closed-schema
  report sections. Reviewer fixes removed unsupported private-row recomputation
  and ontology/frame-semantic claims, bound frame/type/evidence/topology fields
  to exact derived values, and reject coherent permission-case reclassification
  that changes the configured evaluation mix. Canonical dev-container
  verification passes: focused evaluator tests 29 OK, full unittest 638 OK,
  full Ruff check passed, 303 files pass format-check, and `git diff --check`
  passed. The 3/3 read-only gate passed with explicit `RELEASE_DECISION: AGREE`
  from `Dalton` (engineering), `Kepler` (governance/safety), and `Faraday`
  (research method); no blocking findings remain.

- No-training candidate-admission ablation completed for the accepted active
  goal. The EXM/PST 50,000-case evaluator compared regex, raw
  `jieba + SentencePiece`, frequency-rule admission, frozen-profile admission,
  and the prior weak-label MLP admission policy in
  one run over the same generated benchmark shape. Safe tracked aggregate:
  `experiments/kg_ontology_v2_coordination/results/exm_no_training_programmatic_ontology_50000_summary_2026-07-10.json`.
  Result: regex admission 10,000/50,000; raw `jieba + SentencePiece`
  admission 18,176/50,000 with 0/5,000 no-match guards; frequency-rule
  admission 33,277/50,000 with all guards passing; frozen-profile admission
  43,976/50,000 with 33,976/40,000 positive cases,
  5,000/5,000 no-match guards, and 5,000/5,000 denied guards; weak-label MLP
  weak-label MLP admission 43,369/50,000 with 33,369/40,000 positives and all
  guards passing. Current method judgment: the bundled candidate-admission and
  graph-construction policy is effective on this generated benchmark, but this
  does not establish a type-compatibility or frame-semantic effect. The self-trained MLP is not
  justified as the stable default because the zero-training frozen profile is
  +607 passed cases better in this run. Engineering reviewer `Meitner` blocked
  once because the frozen profile model hash did not include the actual
  scoring coefficients; the blocker was fixed by data-binding
  `_FROZEN_PROFILE_SCORE_RULES` into both scoring and `model_hash`, then
  rerunning the 50,000-case evaluation. Verification after the fix:
  dev-container focused lexical ontology tests 21 OK, full 50,000-case
  evaluation completed, saved public report validation blockers=[], full
  unittest 630 OK, Ruff check/format-check passed, KG acceptance
  `passed_with_explicit_limits`, tracked summary JSON parse passed, and
  `git diff --check` passed. Reviewer gate passed 3/3: `Meitner`
  engineering agreed after the hash-binding fix, `Singer` governance/safety
  agreed, and `Gibbs` research method agreed. BGE-M3 through FlagEmbedding is
  documented as the preferred future optional true frozen neural adapter, but
  it was not executed in this default-dev-container slice. Claim remains
  candidate-only and excludes raw mail content, query payloads, private rows or
  paths, canonical graph/type/user-graph/wiki mutation, BGE execution evidence,
  parser readiness, business answer generation, and production readiness.

# 2026-07-10 — KG Research Agent — issue #36 release gate passed

- Completed the evidence-grounded MAY ChatGPT × FormOwl MCP evaluation with
  100 unique reviewer-grounded evidence cases and 50,000 rendered interaction
  variants. Production v4 and the standalone source-rebuild validator both
  passed with `blockers=[]`.
- The evaluator now binds closed `tools/list` schemas, recursively rejects
  caller-controlled identity/session/grant keys, separates expected outcomes
  from actual MCP semantics, executes same-session response-derived follow-ups,
  and validates private replay roots against an external trust anchor.
- Structured-answer gold and prediction use methodologically independent
  lifecycle/action/deadline/dependency extraction. Answerable false negatives
  score case/thread scope as an applicable zero, and standalone validation
  rebuilds grounded rows from the private manifest, trusted replay, and evidence
  bundle so coherent rehashing cannot pass.
- Safe results: governed mail retrieval 11/100, candidate KG 19/100, ontology
  KG 19/100; 326 retrieval-only factorial arms produced zero better than
  KG-only, two equal, and 324 worse. The replay exposed 10 expected no-match
  false positives while enforcing all 10 expected permission denials.
- Response-conditioned trajectory accounting records 60,000 tool calls per
  FormOwl arm. Non-triggered correction/refinement/permission conditions do not
  add a second call, turn, or simulated cost.
- Canonical final verification passed 713 dev-container tests, full Ruff check,
  316-file format check, and `git diff --check`. Reviewer gate passed 3/3 with
  explicit `RELEASE_DECISION: AGREE` from the product-usefulness,
  evidence/citation, and engineering/governance reviewers.
- Claim boundary remains deterministic offline replay/usefulness evaluation:
  no live ChatGPT execution, production-readiness claim, autonomous business
  judgment, raw-mail MCP access, or canonical KG/type/user-graph/wiki writes.

## 2026-07-11

- Completed a user-requested whole-repository maintenance review across
  production Python, tests/scripts, research harnesses, containers, MCP
  boundaries, and durable documentation. Static import analysis found no
  orphan production module; canonical root verification passed 713 tests plus
  Ruff check and format check.
- Removed four unused projection acceptance markers, one unused OpenProject
  mapper wrapper, and one unreferenced incomplete benchmark. The older Wiki
  projection builder and forbidden-tool marker exports were reviewed but kept
  as public compatibility surfaces. Consolidated identical Project and Wiki
  JSONL logger implementations and identical CPU/GPU neural dependency files
  while preserving compatibility imports and container entrypoints.
- Deleted the obsolete MCP abstract after moving current service/tool truth into
  `docs/mcp-boundaries.md`, and labeled ontology/mail documents by lifecycle.
  The duplicate KG restart history remains unchanged in this patch; issue #40
  tracks its safe archival together with the canonical durable registry.
- The independent `.formowl/kg-eval` suite is currently not state-independent:
  a clean archive lacks ignored result snapshots, while the operator workspace
  contains ignored evidence that rebuilds validator output to 12/12 although
  tracked tests/checklists and the durable goal still assert the historical
  8/12 state. Do not report that harness as passing until issue #38 resolves the
  state-drift and clean-clone reproducibility contract.
- Follow-up issues: #38 for KG authority state-independent tests, #39 for MCP
  protocol/shadow-workflow consolidation, and #40 for durable history archival.
- Final cleanup reviewer gate passed 3/3 after compatibility and documentation
  blockers were fixed: dead-code/evidence, runtime compatibility, and
  docs/governance reviewers all returned `RELEASE_DECISION: AGREE`. Public Wiki
  projection and forbidden-tool marker surfaces were retained; the authority
  harness state-drift remains isolated to #38 and is not claimed as passing.

## 2026-07-11 — Issues #38–#40 completion update

- Issue #38 now isolates blocked and completed authority fixtures, cleans up
  partial fixture setup failures, avoids writes to operator-controlled ignored
  state, and passes the authority suite from both operator and clean-clone
  layouts. The four broad real-evidence gates remain intentionally blocked;
  harness reproducibility does not complete those evidence requirements.
- Issue #39 now uses one shared MCP JSON-RPC engine and JSONL compatibility
  runner, fails closed without authenticated session identity, binds Project,
  Wiki, and semantic calls to gateway-controlled identity, records rejected and
  denied transcript status, delegates semantic work only to injected handlers,
  and exposes the effective-graph alias deprecation policy.
- Issue #40 moved prior board, role-goal, and handoff history into immutable
  dated snapshots with manifest hashes and bounded active startup files. A
  deterministic archive-integrity test enforces hashes, links, retention limits,
  checklist preservation, and current-versus-archive authority boundaries.
- Final issues #38-#40 reviewer gate passed 3/3. Franklin verified shared
  protocol and fixture cleanup correctness; Carver verified identity,
  transcript, alias, and no-new-capability governance; Helmholtz verified
  clean-state authority, completed fixture coherence, archive integrity, and
  status honesty. All returned `RELEASE_DECISION: AGREE` with no blockers.
- Final canonical evidence before publication: root suite 725 tests OK, KG
  authority suite 589 tests OK, MCP focused 132 tests OK, read-only repository
  enterprise/preflight 60 tests OK, archive integrity 4 tests OK, and full Ruff
  check/format check passed for 323 files.

## 2026-07-11 — Pre-feature production cleanup

- Removed test-only MCP gateway scenarios and assertion markers from production,
  deleted unused retrieval/JSON-RPC marker helpers, and centralized mail bundle
  selection, grant normalization, and grant-expiry behavior in one private mail
  access helper. Production Python is net 153 lines smaller.
- Retrieval now has one private implementation while the deprecated
  `query_effective_graph` alias retains its full keyword-only signature and the
  canonical `query_effective_graph_view` still requires an effective graph
  view. Shared observability is canonical; Project/Wiki legacy imports remain
  deprecated compatibility re-exports and `SPEC.md` documents that boundary.
- Canonical dev-container verification passed 726 tests, full Ruff check, and
  325-file format check. Engineering, governance/safety, and maintainability
  reviewers returned 3/3 `RELEASE_DECISION: AGREE` after signature and
  specification compatibility blockers were fixed.

## 2026-07-11 — Pre-feature structural cleanup

- Consolidated duplicated evaluator validation, ChatGPT intake validation,
  HTTP smoke orchestration, PostgreSQL container lifecycle, mail payload
  validation, and atomic JSON persistence. Eleven evaluation/smoke entrypoints
  are thinner while retaining their CLI, report schema, error, privacy, and
  claim-boundary contracts.
- Tests now validate real adapters, interfaces, and migration content as the
  primary surfaces. Previously exported name-list helpers remain thin
  compatibility wrappers to avoid an unannounced API break. A private
  graph-storage write seam remains as an alias to the shared atomic writer so
  rollback failure injection stays testable without restoring duplicate
  persistence code.
- The second cleanup phase changes 1,334 lines added and 1,514 deleted, net
  `-180`; scripts and experiment entrypoints are net `-893`. Canonical
  dev-container verification passed 730 tests, full Ruff check, 331-file format
  check, and `git diff --check`. Production/API, evaluator/privacy, and
  shell/safety reviewers returned 3/3 `RELEASE_DECISION: AGREE`.

## 2026-07-15 — Candidate Assertion and Domain Pack minimum core

- Completed the bounded implementation in isolated worktree
  `/tmp/formowl-candidate-assertion-domain-pack` on branch
  `goal/candidate-assertion-domain-pack-core`; the primary working tree was not
  modified.
- Procurement mail-shaped and finance ERP/application fixtures use one
  source-neutral `Observation -> CandidateBusinessObject ->
  CandidateAssertion` pipeline with all five assertion kinds. Scoped Domain
  Packs bind core mappings, ontology revision, provenance, and normalized
  content hash.
- Persistence is atomic and candidate-only. Reviewer hardening closed
  participant permission/source-lineage bypasses, same-ID overwrite,
  tuple/backend/SQL public-safety bypasses, and legacy stable-ID compatibility.
  No canonical graph/type, user-graph, wiki, or external-system write is
  authorized.
- Canonical verification passed 764 unit tests, full Ruff check, 256-file
  format check, and `git diff --check`. Planck, Bohr, and Kant returned 3/3
  `RELEASE_DECISION: AGREE`.
- The branch remains uncommitted and ready for deliberate integration. The
  durable KG goal returns to the separate four-gate broad real-evidence blocker.

## 2026-07-16 — Issue #16 temporal-evidential candidate graph POC

- Extended the same isolated worktree and branch with one normalized
  `TemporalContext`, Domain Pack temporal-role mappings, independent
  epistemic/lifecycle axes, and candidate-only temporal views for
  `as_of_world_time` and `known_as_of`.
- Procurement and finance continue through the same source-neutral pipeline.
  Source capture is bound to Observation lineage; candidate materialization is
  a separate required knowledge boundary; missing source or materialization
  time fails closed. Due dates do not hide already known future commitments.
- The POC remains candidate-only: no canonical write, database migration,
  SHACL runtime, full interval algebra, causal inference, temporal entity
  resolution, or broad production-hardening claim.
- Canonical verification passed 774 unit tests, full Ruff check, 338-file
  format check, and `git diff --check`. Hubble, Aristotle, and Chandrasekhar
  returned 3/3 `RELEASE_DECISION: AGREE`.
- The Issue #16 scope is durable in the work board. The remote GitHub comment
  could not be sent because both the GitHub connector and local `gh` token are
  invalidated; re-authentication is required before synchronization.

## 2026-07-16 — Original MAY 100-case / 50,000-variant retest restored

- The exact reviewer-grounded MAY business-question evaluation can run again
  against the authorized private corpus. The failure was a false-positive
  public-safety regression: ordinary mail disclaimer and telephone prose was
  classified as SQL by over-broad `COPY ... FROM/TO` and `CALL` patterns.
- The SQL patterns were narrowed to statement-shaped syntax while retaining
  rejection of actual `COPY ... TO STDOUT`, `COPY ... FROM STDIN/file`, and
  `CALL procedure()` payloads. Private mail text remains private; public report
  leak validation remains enabled.
- The exact 100 source questions and 500 deterministic variants per question
  completed and independently validated with zero blockers. Directly
  comparable results are unchanged from the accepted prior run: governed mail
  retrieval 11/100, Candidate KG 19/100, and ontology-guided KG 19/100. This
  removes the operational regression but does not improve business-answer
  quality.
- Canonical verification after the fix passed 776 dev-container tests, full
  Ruff check and format check, and `git diff --check`.

## 2026-07-16 — Default tokenizer/admission made normative and retested

- Rewrote the main specification, resource-extraction specification, README,
  KG method, multimodal term-extraction decision, and active experiment README
  so every text-bearing Observation defaults to Unicode/script normalization,
  protected ASCII extraction, Jieba, corpus-bound SentencePiece, and
  frozen-profile admission. Silent regex-only default behavior is forbidden.
- The original MAY Candidate KG, ontology, factorial consumers, and grounded
  50,000-variant evaluator now use the same hash-bound query/corpus tokenizer
  path. Candidate/evaluation policy identity binds normalization,
  segmentation, admission, model, and corpus hashes. No canonical writes were
  added.
- Focused dev-container tests passed: KG evaluator 9, ontology evaluator 9,
  factorial evaluator 5, and ChatGPT 50,000 evaluator 17. The exact 100
  questions times 500 variants completed and the independent saved-report
  validator returned `blockers=[]`.
- Result: mail evidence retrieval stayed 5,500/50,000; Candidate KG changed
  from 9,500 to 8,500; ontology changed from 9,500 to 10,000 only because it
  passed all no-match and permission variants while solving 0/40,000
  answerable variants. Candidate grounded usefulness fell from 0.078432 to
  0.070775; ontology grounded usefulness fell to 0. The default tokenizer is
  corrected, but graph component collapse, rejection calibration, evidence
  ranking, and ontology over-pruning remain the actual quality blockers.

## 2026-07-17 — Source-neutral MAY retrieval target completed

- The final private 100-case MAY run scored 93/100 for both Candidate evidence
  retrieval and the contract-bound ontology rerank: 73/80 answerable, 10/10
  no-match, and 10/10 permission. Both saved-report validators returned
  `blockers=[]`; no private question, mail content, answer, or identifier was
  added to tracked output.
- The default counts logical source items and resolves exact immutable access,
  context, and time before vocabulary. Raw query text controls only intent,
  count, and chronology; anchors come from runtime-produced tokens or named
  `retrieve_ablation` extensions. Cross-context authorization is an actual
  boolean, and ontology remains a capped additive rerank.
- The grounded 50,000 evaluator now uses the same `CandidateEvidenceIndex`
  path. All 18 active retrieval documents are rewritten to reject regex-only,
  parser-chunk, component-union, raw-term bypass, and ontology hard-pruning as
  defaults; onboarding tests enforce that inventory.
- Verification passed 147 focused tests, the exact 11-test hardness/harness
  command, 884 full canonical dev-container tests, full Ruff and 264-file
  format checks, and `git diff --check`. No PST, MSG, private question, answer,
  or generated evaluation artifact is tracked.
- Herschel, Popper, and Boole returned 3/3 `RELEASE_DECISION: AGREE`.
- This remains candidate-only evidence selection: no canonical graph/type,
  user-graph, wiki, raw-access, or external-system write is authorized, and the
  four broad real-evidence acceptance gates remain blocked.
## 2026-07-21 — Active isolated methodology and UAT orchestration work
- `goal/task-answering-methodology` separates TaskFrame, all-matching coverage, source-item assembly, answerability, and content-first projection across source shapes; 895 canonical tests and full Ruff/format pass, with the 3-reviewer gate remaining.
- User-assigned issue #44 is complete on `uat/issue-44-orchestrator`: `/api/chat` reaches pinned `codex-cli 0.144.6` app-server threads through a private Unix socket and a narrow JSONL/WebSocket bridge; Codex decides whether to call the single FormOwl evidence tool. The explicitly authorized server ChatGPT auth cache is copied once into isolated state; serving mounts no developer Codex home or auth input. Real protocol tracing required final agent output from `item/completed` because `turn/completed.itemsView` is `notLoaded`; persistent threads make deletion real. Verification passed 951 canonical tests, full Ruff/275-file format, Node 20 UI smoke, runtime attestation, image build, and `git diff --check`; Plato, Volta, and Mencius had already agreed 3/3. The deployed `8088` live gate passed with zero FormOwl calls for a greeting and exactly one `search_formowl_evidence` call returning six governed items for the 文顥/pull-in request; the test thread was deleted.
