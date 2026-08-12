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

## 2026-07-24 — Final live human-UAT repair handoff

- The live image is the human-readable + dynamic-tool-racefix +
  mobile-clearance build; the LAN surface is ready with automatic restart.
- Desktop uses a 1120px, content-dominant result table. Mobile uses labeled
  stacked cards, Taipei-formatted times, safe long-text wrapping, and explicit
  composer clearance. Independent synthetic browser UX passed with 196px
  last-card clearance and no horizontal overflow.
- Turn completion could previously outrun an in-flight dynamic tool. Requests
  are now pre-registered, and completion drains accepted tools with a bounded
  timeout. Focused verification passes HTTP 47/47, orchestrator 25/25, JS UI
  smoke, Ruff/format, and diff checks.
- One authorized source-backed independent pre-fix test blocked when the
  request failed; existing non-content event evidence led to the race repair.
  Both private-evidence sidecar authorizations are exhausted, so no post-fix
  source-backed automated retest ran. Next action: the user's manual live
  webpage query.
- Methodology authority remains valid-but-blocked. This is human-UAT surface
  engineering evidence, not methodology-quality UAT, a KG-vs-ontology
  comparison, issue #33 closure, broad KG completion, or production readiness.

## 2026-07-24 — Issue #51 execution contract approved

- Gate 0 is clean at `79bc129`; `--check` is valid-but-blocked and `--require-ready` exits 1.
- Three read-only reviewers agreed on the source-neutral WP1-WP6 contract posted as issue #51 comment `5070970116`.
- Issue #53 is a hard reviewed lifecycle prerequisite before WP5; issue #52 remains the sole independent raw-PST oracle gate.
- Next: push the integration baseline, then delegate only the contract's disjoint packages; never claim methodology-quality UAT while authority is blocked.

## 2026-07-25 — Issue #51 WP1 interface freeze and integration

- WP1 code is frozen at `0f2e69b`; the reviewed code-plus-packet head is
  `eac8473d`, with durable packet `docs/issue51-wp1-interface-freeze.md`.
- Russell and Herschel both returned `RELEASE_DECISION: AGREE` with no blockers
  on exact packet head `eac8473d`; the cumulative packet review remains the
  current freeze gate.
- Integration merge `9e8a5f6` has parents `bed52a4` and `eac8473d`. Integrated
  canonical WP1 evidence is the exact 8-module suite (118 tests OK), targeted
  Ruff/format pass, and passing diff checks.
- Authority remains valid-but-blocked: authority fingerprint
  `sha256:c8e3fc5ec13d690f33d27797942a3b9b090319d4be8f269c77bccd646d787177`,
  execution fingerprint
  `sha256:291c7ea5c5737079cc9ae9d4100fd9ce94f926adfff1a112235ed0aa93cf9665`,
  binding count `64`.
- Next package is WP2: complete raw inventory/structural extraction and
  independent raw-oracle reconciliation, consuming but not mutating the frozen
  WP1 interface.

## 2026-08-12 — Track 2 bounded implementation lane closed

- Final commits are `8730e21`, `ead8d97`, and `8f10404`: immutable
  content-bound tokenizer packaging, exact authority-count alignment, and
  fail-closed contradictory package-plus-legacy configuration.
- Canonical focused verification passed tokenizer 14/14, ontology 5/5, and
  authority 15/15 with Ruff, format, and diff checks passing; 3/3 reviewers
  returned `AGREE`.
- PostgreSQL remains canonical. Do not dispatch duplicate Track 2 tokenizer,
  ontology, or Neo4j implementation. The missing maintainer-approved model
  artifact and corpus hash are separate readiness inputs.
- Methodology authority remains valid-but-blocked. This closes only the bounded
  implementation lane, not Issue #33's broader independent-holdout,
  same-pipeline comparison, end-answer, or research-acceptance gates.
