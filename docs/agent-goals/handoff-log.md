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
## 2026-07-23 — Issue #49 tokenizer replay completed

- Issue #49 is complete. The source-neutral implementation indexes once and
  queries many times. Bundle/source identity collision and missing required-term
  supporting citations were fixed and re-reviewed. Private post-index retrieval
  took 664.132ms and 662.973ms, both below 10 seconds, with zero rebuilds.
- The exhaustive oracle's 87 sources exactly matched verified and gateway
  identifiers plus citation hash. Permission denial occurred before retrieval,
  and supporting evidence was complete.
- The explicitly approved OpenAI Codex sidecar chat on July 23, 2026 returned
  HTTP 200 in 10093.685ms, below 30 seconds, invoked FormOwl once, and reported
  87 total sources, 10 displayed sources, and 10 citations. It preserved the
  exact required-term individual hash match, included all timing fields, and
  did not reach the 120-second timeout.
- Direct `all_matching` coverage was total/returned 87, displayed 10,
  `is_exhaustive=true`, `coverage.has_more=false`, and
  `projection.has_more=true`. Chat deterministically copied the original tool
  coverage unchanged; Faraday's re-review agreed that this is proof.
- Hume (high), Noether (medium), and Faraday (max) each returned
  `RELEASE_DECISION: AGREE` with no blockers after the correctness fixes.
  Canonical focused gateway (33) and UAT (41) tests passed. The full canonical
  suite reached 990 tests with one pre-existing out-of-scope tokenizer
  subprocess error because the evaluator lacks `MAIL_TOKENIZER_ID` /
  `_tokenize`. Ruff, format, and `git diff --check` passed.
- Cold index readiness was approximately 2,059,592.613ms with no SLA.
  Methodology authority remains valid-but-blocked; this is not
  methodology-quality UAT, a KG-vs-ontology result, general production
  readiness, or a general latency claim.
- Next action returns to the separate Task Answering reviewer gate and the four
  broad real-evidence blockers.

## 2026-07-23 — Issue #49 completion correction

- Independent verification reran the focused canonical gateway and UAT modules:
  33/33 and 41/41 passed, with targeted Ruff and diff checks passing.
- Three fresh anonymous live sessions replayed the same private UAT prompt. The
  full-chat HTTP outcomes were 500, 200, and 500. Every FormOwl retrieval
  completed first with the expected 87 total / 10 displayed sources and about
  674-685ms FormOwl orchestration, confirming the index-once/query-many slice.
- The successful chat completed in 14.106 seconds with exhaustive
  `all_matching` coverage, 10 unique primary citations, and three supporting
  citations. The two failures happened after successful retrieval and returned
  generic `request_failed`; the Codex answer/response stage is therefore still
  intermittent.
- Issue #49 is restored to unchecked. Do not call the full-chat slice complete
  until repeated fresh-session live replay succeeds reliably. Methodology
  authority remains valid-but-blocked.

## 2026-07-23 — Issue #49 multiprocessing deployment and stable replay

- The isolated UAT branch now parallelizes frozen Jieba + SentencePiece index
  tokenization with four Linux `fork` workers and deterministic parent merge.
  Exact index/result/citation parity, safe fallback, and worker fail-closed
  tests pass.
- Same-corpus cold readiness improved from 2368.108s to 859.372s, a 2.76x
  speedup and 63.71% reduction. Index build was 541146.486ms; sampled CPU
  averaged 409% during parallel work, peak memory was 17.38GiB, and no OOM
  occurred.
- The LAN UAT at `192.168.71.211:8080` now runs only the new four-worker
  upstream. Three fresh PO prompt sessions returned HTTP 200 three out of three
  with 87 total / 10 displayed sources and exhaustive coverage. The
  `03.80503G301` COO/origin prompt also returned HTTP 200 with the identifier
  present.
- Focused UAT-image proof passes gateway 38/38, orchestrator 20/20, HTTP 43/43,
  targeted Ruff/format, Node 20 UI smoke, and diff-check. Issue #49 remains
  unchecked pending its final post-change reviewer gate. Methodology authority
  remains valid-but-blocked.

## 2026-07-24 — Issue #50 authorized evidence rendering

- Authorization was already passing; generic public-payload redaction was
  incorrectly applied again to authorized body fields and could replace an
  entire message with `[redacted_mail_evidence]`.
- A dedicated evidence policy now preserves ordinary mail content and locally
  redacts only credentials and implementation details. Denied paths remain
  empty and control/metadata payloads remain strict.
- Codex turns now permit at most three bounded FormOwl refinements because live
  PO evidence required two calls; identical calls reuse the first result.
- Proof: 127 focused container tests, Ruff, Node UI smoke, and live PO/COO chat
  both HTTP 200 with zero full placeholders or chat errors. Methodology
  authority remains valid-but-blocked.
