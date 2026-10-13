# Agent Handoff Log
Lifecycle label: `active`.
This bounded active window is backed by
[docs/archive/2026-09-21/handoff-log.md](../../docs/archive/2026-09-21/handoff-log.md);
earlier entries are immutable. Detailed older logs remain at
`../archive/2026-08-25/handoff-log.md` and `../archive/2026-08-18/active/docs/agent-goals/handoff-log.md`.
## Retention Rule
- Keep the latest 14 calendar days and at most 300 lines.
- Archive a complete dated entry before trimming it.
- Record only current facts, blockers, verification, and next action.
- Historical pointers are not restart instructions.
## Current user override — single implementation worker
- Hard cap: one total implementation worker including nesting; reuse the same existing worker session in the A slot, with no replacement/descendant. Existing session ID: `01a0cc38-97d6-78c1-9640-9bb50dbeb646`. Explicit `codex exec resume` uses `--model gpt-6-luna` and `model_reasoning_effort=max` (verified on turn `01a0cca1-9235-7133-a2af-6d610f6dc479`); this does not independently prove historical Worker A identity.
- Every dispatch/resume must verify both persisted model and effort; ordinary `send_message` previously showed `xhigh`. Master stays orchestration-only; UAT `gpt-5.5`/`high`, three read-only reviewers, and four blocked methodology gates are unchanged.
## 2026-10-01 — Development POC versus security-review boundary
- Worker A added the explicit `SourceEvidenceExecutionPolicy` to the existing
  source-neutral retrieval owner. The default `development_poc_v1` boundary
  covers both authorized `mail` and standalone `document_text` rechecks and
  exposes only safe boundary metadata.
- `security_review_v1` is fail-closed until `--require-ready`, source
  completeness, execution-fingerprint binding, same-pipeline real-source
  ablation, independent final-answer acceptance, and exactly three reviewer
  agreements are present. No security-review claim is made by local POC tests.
- Canonical network-none focused source-neutral retrieval passed `23/23`;
  shared handler composition passed `40/40`; provider-free synthetic browser
  mail+document recheck passed `1/1`. Python compile, Ruff, and diff-check
  passed. No live private-mail/provider UAT, database, index rebuild, service
  restart, or external disclosure occurred.

## 2026-09-23 — Generic double-check design recorded, 待測
- User granted a one-time Master docs-only exception; no code, worker-setting, provider, or deployment changes. [SPEC §7.3.1](../../SPEC.md#731-source-neutral-evidence-double-check--待測) defines one shared core for mail organization and independent Markdown/plain-text document lookup (not mail attachments): initial miss -> one materially different same-scope source recheck -> verified citations/coverage. Incomplete/unavailable => `pending_review`; exact/error/denial boundaries remain.
- Local diagnostics later passed line citations `16/16` and shared core with mail plus independently extracted Markdown/plain-text/resolver `54/54`; Ruff, `py_compile`, and `git diff --check` passed. Actual revision/runtime text composition and both live browser/provider/MCP recovery paths remain outstanding; feature stays 待測 and no independent review occurred. All promotion gates in SPEC §7.3.1 remain required.
- Earlier docs-only authority was valid but blocked (`CJK=true`), execution `sha256:aef5cd0495f7429218238354ff64097ceadb6583af09c77a14d954755e51f022`; later docs checkpoint `sha256:3b49379637c0b7fcec78d149c831ed79a91dfdbb14daca74b5912258769f81b7` is historical. Both had four blocked gates, step 4 in-progress, and no browser/provider acceptance or reviewer gate.
## 2026-09-22 — Historical token-driven two-worker cap
- At that checkpoint the cap was two including nesting: reuse A/B, no duplicate/third/replacement/descendant; Master orchestration-only; workers `gpt-5.6-luna`/`max`, UAT `gpt-5.5`/`high`.
- Historical safety, blocked-authority and three-reviewer gates unchanged; focused `101/101`. Browser ordinary HTTP `200`/MCP `0` final passed; mail had 2 MCP calls, citations `0/0`, attempt 3 `empty_response_body` ~45s. `UNKNOWN` was runner-enum omission; no owner exception, follow-ups, or live rerun; UAT not accepted and five-step plan unchanged.
## 2026-09-21 — Worker specification at that checkpoint and composition-test handoff
- At that checkpoint, issue #56 used exactly two implementation
  workers on `gpt-5.6-luna` with `reasoning_effort=max`; the UAT provider remained
  pinned to `gpt-5.5` with `reasoning_effort=high`.
- The independent release gate remains three effective read-only Codex/GPT
  reviewers. `agy` remains unavailable and was not invoked. The dated
  2026-09-16 `gpt-5.5` worker setting is preserved as historical context and
  superseded for current dispatch.
- Worker A inspected the handler-composition coverage. Summary-vs-exact routing,
  authorized-selector graph-miss filtering, and wrong-selector permission
  behavior were already covered; the focused test now explicitly asserts
  graph miss is public `not_found` and preserves a semantic operational
  `error` distinctly from no-data. Canonical dev-container verification passed
  `13/13` for `test_issue56_uat_handler_composition.py`; no runtime or
  provider-bridge code changed.
- Methodology remains `active-blocked`; no readiness, superiority, UAT, or
  completion claim is made. No concrete Worker B defect was identified and no
  duplicate provider bridge work is requested.
- Current bounded experiment checks are `58+13+7+6`; the web slice is `16 passed / 1 skipped`.
- Fresh real-browser diagnostic: ordinary HTTP `200`, MCP `0`, rendered text length `25`, about `5.1 s`; mail upstream HTTP `408` `invalid_request_error`, pre-MCP `0`, citations `0`, about `22.8 s`.
- This is diagnostic only, not UAT acceptance; the same four methodology gates remain blocked, step 4 remains `in-progress`, and no readiness, superiority, or completion claim is supported.
- The temporary Firefox runner now captures ordinary and mail success screenshots separately and supports `--ordinary-only`; no live request was made in this Worker A edit.
- Subsequent same-version ordinary-only verification failed provider HTTP `408` `invalid_request_error`, MCP `0`, about `25.2 s`; no screenshot was produced and mail was not sent. The prior ordinary pass is intermittent, not stable acceptance or proof of the tool-choice fix; no further live repeat is authorized without a new discriminator.
## 2026-09-16 — Worker model specification override
- The user explicitly overrode the prior worker model specification:
  exactly two implementation workers now use `gpt-5.5` with
  `reasoning_effort=high`; the UAT provider uses the same runtime setting.
- The earlier `gpt-5.6-luna` capacity blocker is no longer the active
  specification target. The independent release gate still requires three
  effective read-only Codex/GPT reviewers.
- This is a specification and handoff update only; UAT routing, provider
  secrets, private source data, and raw internal details remain unchanged.
## 2026-09-15 — UAT/provider integration checkpoint
- UAT non-2xx responses now project a safe frontend error state and repair
  transcript consistency. Provider finalization/citation retention preserve the
  existing bounded browser -> MCP -> provider -> answer loop.
- Canonical evidence: UAT `16 tests / 1 skip`; provider bridge `44/44`; the
  five-file Ruff check/format, `py_compile`, and `git diff --check` checks passed.
- The user now authorizes the existing provider only for permission-filtered
  evidence/citations; secrets, raw paths, raw business payloads, and
  unauthorized sources remain forbidden. No reroute or unchanged-route retry.
- A direct benign greeting reached the provider with HTTP `200` and non-empty
-  text in about `11.8 s`; the daily greeting provider smoke succeeded, but
  this is not business-prompt acceptance. The existing FormOwl `/api/chat` path
  for the same greeting returned HTTP `200` but projected `status=error`,
  `reason_code=http_error`, `citation_count=0`, in about `47.95 s`.
- The provider attempt for `整理劉一帆信件` returned pre-MCP HTTP `408`
  `invalid_request_error` with safe MCP `call_count=0`; it failed before an
  MCP/KG evidence query and is not evidence that KG found no data. No business
  answer or citations were accepted.
- The pre-MCP provider-failure repair is now landed: HTTP `408` with
  `invalid_request_error` and zero evidence is classified as the safe
  `provider_pre_mcp_failure` diagnostic, distinct from KG no-data. Do not
  infer root cause or external UAT success. The canonical dev-container
  `methodology_authority_check.py --check` recheck completed with exit `0`,
  `authority_valid=true`, `methodology_ready=false`, `errors=[]`, and `CJK=true`;
  execution fingerprint
  `sha256:7b2c65dc73492438b5bc4880fc7a34740219b13d792c993eb04315e3dc209782`.
  The implementation workers use `gpt-5.5` with
  `reasoning_effort=high`; the UAT provider runtime remains pinned to
  `gpt-5.5` with `reasoning_effort=high`.
- Goal remains `active-blocked`; step 4 remains `in-progress`; all four
  methodology gates remain blocked. No checkbox or overall completion claim.
- Safe chain summary from the reviewed modules: report only public status and
  citation counts plus allowlisted phase/reason/HTTP/stop fields, bounded MCP
  call status/timeout/failure reason/request shape/timing, and hashes. Classify
  `mcp_failed`/timeout as MCP failure; successful MCP with zero citations as no
  evidence; citation-bearing incomplete projection as partial evidence. The
  reviewed HTTP surface names transcript as `/api/transcript` and reset as
  `/api/conversation/reset`; no `/api/conversation` route is defined here.
  Worker B made no provider call and did not rerun a consumptive diagnostic.
## 2026-09-14 — Bounded implementation checkpoint
- Worker A changed `tests/test_issue56_uat_web_e2e.py` so the target test uses a
  localhost `ThreadingHTTPServer` Responses wire stub and exercises the full
  `browser /api/chat -> normal MCP -> function_call_output -> provider
  finalization failure -> cited snippet` path. The stub is not an actual
  external provider.
- Canonical focused evidence passed: UAT `14 tests / 1 skip`; provider bridge
  `43/43`; mail gateway `23/23`; and the specified file's Ruff,
  `py_compile`, and `git diff --check` checks.
- Worker B fixed the `Any` import and recovery-helper `F821` in
  `scripts/issue56_uat_web.py`; its Ruff and `py_compile` checks passed.
- This is bounded implementation evidence only, not external-provider
  acceptance, methodology readiness, KG/ontology superiority, or objective
  completion. Goal status remains `active-blocked`.
- The four authority gates remain blocked: source completeness, accepted
  execution-fingerprint binding, same-pipeline real-source ablation, and
  independent final-answer acceptance.
- Next: perform external acceptance only if an actual provider credential and
  endpoint become available; otherwise preserve the claim boundary and do not
  promote this stub evidence.
## 2026-09-14 — Worker A lazy mail-query handoff
- The native bundle probe was bounded to the existing private bundle and safe
  retrieval report, validating `2,793` messages and `64,718` body segments in
  `133.996 s`; it then entered the eager gateway index at `134.008 s`, grew
  through the recorded RSS checkpoints, and never reached a query or citation.
- The bounded implementation fix makes `MailEvidenceQueryGateway(...,
  lazy_index=True)` avoid absent-index construction and scan existing frozen
  body/subject/sender/message-id text at query time, capped at `4,096`
  segments. Default eager behavior, source bindings, and redaction boundaries
  remain unchanged; no participant-only route or parallel index was added.
- Focused dev-container test
  `MailEvidenceMcpGatewayTests.test_mail_evidence_query_lazy_index_scans_source_text_with_citation`
  passed `1/1`; the native `64,718`-segment query was deliberately not rerun.
- This remains implementation evidence. Worker B's next bounded source-backed
  attempt must retain phase/RSS evidence and real citation reporting; no UAT,
  readiness, superiority, or completion claim is supported.
## 2026-09-13 — Bounded loader regression checkpoint
- Retained the streaming sealed-shard reader and strict owner-seam rejection;
  removed the unproven runtime pre-bound-session bypass.
- Loader regression passed `1/1`; compact focused result was `3` passed,
  `2` skipped. No long test rerun.
- Prior live UAT still failed with provider timings around `9.856 s`/`11.621 s`,
  MCP timeout around `50.142 s`/`48.376 s`, `0` citations, and clarification
  required. No UAT acceptance.
## 2026-09-07 — Forward ingestion/read-path repair, not yet deployed
- The unresolved generic path was worker/folder child materialization,
  parent/child Observation aggregation, HTML/MIME lineage, and separation of
  private input from public redaction. Current A/B edits preserve those
  boundaries and existing source-neutral index/candidate graph ownership;
  `issue56_uat_web.py` builds a new revision and retains sealed rollback.
- Bundle/import passed `21/21`, stage/contract `2/2`, and the pinned offline CPU
  E5 canary `1/1`; the urgent partial-child reader passed `1/1`. The broad
  unittest run was non-green and was not repeated.
- A's authorized two-root ingestion and B's index/KG activation, staged load,
  and browser query were not completed. Completed-job validation must precede
  consumption; no curated replacement corpus is allowed.
- Next remains completed authorized jobs -> pinned E5 revision -> staged
  public-output proof -> rollback-capable activation -> real cited browser
  answer. Step 4 and all four gates remain blocked.
## 2026-09-07 — Existing-source inline-table coverage diagnosis
- The `2,793` base-mail inventory and supplemental tables have different asset
  roots. The supplemental capture contains `401` structures (`294` XLSX,
  `107` HTML), while the selected partition references only `14` XLSX and no
  HTML; unreferenced structures are not proof of whole-input completeness.
- The live loader remains pinned to the partial Observation artifact and does
  not discover the broader capture. Inline content has no attachment ordinal,
  header semantics and original message attribution remain unresolved, and the
  first-selection predicate is unknown. Do not infer a reviewed-only or `14`
  item cap, fabricate lineage, or treat labels as formal headers.
- No runtime repair or browser acceptance of the newly located evidence was
  completed. The intermittent external HTTP `200` zero-body root remains
  separate and unresolved; the prior host-side authority issue is superseded
  by the canonical dev-container check and is not evidence of the live CJK
  path or the source cause.
- Next is generic ingestion -> parent/child aggregation -> authorized
  source-neutral index activation -> cited UAT, while preserving candidate,
  permission, lineage, header, and exclusion state.
## 2026-09-07 — Restart-4 bounded browser result
- Multi-call/readable-mail checks passed `36/36`; normal MCP passed `1/1`.
  Eight readable date/subject/sender associations and `24/24` source-derived
  fields were observed, but labels may be abbreviated and prior `2069`/`550`
  coverage was not revalidated. Five lead-time values and eight CRI/L/T pairs
  were supported; eight MPN associations remained unassessable.
- A real response made two valid calls without fallback/provider exception, but
  the unresolved zero-body root still needs route/version, correlation/timing,
  status/byte, completion/error, and finalizing-hop evidence. No unchanged
  route retry was authorized.
## 2026-09-06 — Browser session and final acceptance limitations
- Integrated Chromium retained five bounded turns and reload state, returned
  `12` same-row CRI/L/T pairs with `24` citations, and cleared state on reset;
  focused checks passed `4/4` and `8/8`. This proves only that bounded path,
  not general, production, or readiness behavior.
- Later `session-v1` turns produced clarification/rejected-zero calls; the last
  retry failed because the source-backed answer omitted citations. Source rows
  and semantic pair correctness remain incompletely compared. No code,
  restart, or broad rerun followed.
## Older unresolved Issue #56 checkpoints — retained as compact state
- The September 1 candidate attachment-table checkpoint remains candidate-only;
  it did not establish canonical graph or answer acceptance.
- The August 29 actual-user participant inventory remains incomplete (`2069`
  matches, `174` proven nonmatches, `550` unresolved in the authorized `2793`
  scope); “all” and production readiness are unsupported.
- The August 28 direct-source inventory remains incomplete and cannot be used
  for a full-coverage claim. The August 27 source-to-promotion binding slice
  and pinned-E5 focused checks passed locally, but no formal evidence bundle was
  authored/promoted.
- The August 25 source-completeness report passed its own sealed contract, while
  formal authority promotion remains blocked. The same-pipeline real-source
  ablation and independent final-answer acceptance were not run.
- The August 25 v7 relation-precompute diagnostic passed its bounded checks;
  v6 graph projection was consumed and blocked. Both are immutable diagnostics,
  not readiness or superiority evidence.
- The August 23 source-backed v4 diagnostic passed with a bounded cited path,
  but full regression remained non-green (`1873` total / `1781` passed /
  `54` failures / `23` errors / `15` skips); no broad claim was earned.
- The August 21 v2/v3 sealed-source diagnostics were consumed and blocked with
  zero-citation or zero-path outcomes; they must not be rerun, retried, or
  tuned. The August 20 minimum MCP slice passed on a synthetic fixture, while
  the development one-shot was consumed and blocked; neither supports
  methodology readiness, superiority, or completion.
## Current carry-forward
- Frozen target/tokenizer and strong-RAG control remain unchanged; KG/ontology
  claims require source-preserving, permission-filtered, same-pipeline evidence.
- Full-source activation, holdouts, transfer, source-complete UAT, provider
  acceptance, and final-answer review remain incomplete; step 4 is
  `in-progress`.
- Preserve candidate-before-canonical, provenance, permissions, redaction,
  no-secret/no-raw-path, fail-closed authority, and no-rerun boundaries.
## 2026-09-16 — Bounded UAT/runner safety handoff
- Focused UAT/MCP checks were green while authority remained
  `methodology_ready=false`. The runner preserves safe status/count/timing
  diagnostics, keeps ordinary-before-mail and cited-mail predicates fail-closed,
  and emits no raw prompt, mail text, provider body, secret, URL, or path.
- No external-provider retry, readiness, superiority, or completion claim was
  made.
## 2026-09-21 — Source fallback lineage handoff
- Inventory-only mail records are filtered before message-lineage validation;
  valid-message records missing lineage remain rejected.
- Focused canonical tests passed `23/23`. Provider-free same-selector replay
  returned HTTP `200`, `payload_validated`, exceptions `0`, but
  `pending_review`/citations `0`, scanned `249`, callbacks/matches `0`, and
  stop reason `deadline`.
- The UAT service was not restarted; no new live/provider retry occurred after
  the patch. Acceptance is **NOT complete**.
- Next: investigate eligible-observation access/scan startup within the existing
  immutable source reader and pinned budgets; no blind timeout inflation, data
  or index rebuild, or lineage bypass.
## 2026-09-22 — Historical runner checkpoint
- Historical A/B total cap was `2`, both `gpt-5.6-luna`/`max`; no new worker.
- Focused `101/101`; authority `valid=true`, `ready=false`, `errors=[]`, `CJK=true`; four gates blocked.
- Chromium `2026-09-22T14:39:29.814Z`–`14:40:32.888Z`: ordinary HTTP `200`, MCP `0`, final passed; mail `2` MCP calls, citations `0/0`, attempt 3 `empty_response_body` ~45s.
- `UNKNOWN` statuses reflected runner enum omission, not proof of success; no owner exception was seen; follow-ups did not run.
- Runner enum self-check passed; no live rerun; A was collecting provider-free same-revision evidence.
- UAT acceptance was **NOT complete**; five-step plan unchanged.
## 2026-09-23–24 — Final bounded operational checkpoint
- At that operational checkpoint the worker-slot setting was `gpt-5.6-luna`/`max` (historical, not independent proof of Worker A session identity);
  no new agent, provider call, private-mail E2E, commit, push, or broad test
  campaign was run in this checkpoint.
- Master confirms only FormOwl UAT8088 and retained PostgreSQL are running;
  unrelated project services are unchanged. UAT root/health on LAN and loopback
  returned HTTP `200`, `status=ok`, `query_service_connected=true`; PostgreSQL
  is healthy. Raw interaction logging is disabled; current UAT start
  `2026-09-23T01:19:06Z` and OOM `false` are unchanged.
- Thirty-seven confirmed unused FormOwl containers were removed with backups;
  data volumes, images, and other projects were untouched. Conservative
  leftovers remain; do not claim all unused resources were removed.
- Focused canonical suite: `117` run, `115` passed, `2` skipped, `170.626 s`.
  Chromium basic-only passed `2026-09-23T01:30:13.483Z`–
  `2026-09-23T01:30:29.045Z`: benign greeting -> reload persistence -> real
  reset -> post-reset greeting, MCP `0`; HTTP health/session/reset checks passed.
- Private-mail E2E was not run because security approval denied possible
  disclosure to an unconfirmed provider; do not bypass this boundary. Full
  canonical regression finished exit `1`: `2185` tests, `2830.032 s`, `887`
  failures, `49` errors, `20` skips. Subtests are included; without a baseline,
  do not calculate a pass count or label failures pre-existing.
- First UAT8088 start exited `1` with OOM false on completed-job-changed
  validation; unchanged second start succeeded in `45.3 s`. The anomaly root
  remains unresolved, not fixed. Canonical authority exit `0` is
  `valid=true`, `ready=false`, `errors=[]`, `CJK=true`, execution
  `sha256:aef5cd0495f7429218238354ff64097ceadb6583af09c77a14d954755e51f022`.
- Four methodology gates remain blocked and plan step 4 remains `in-progress`;
  no UAT, release, research-completion, or `[x]` claim is earned. The workspace
  read-only mount is mutable deployment input, not immutable evidence. All
  evidence here is operational and unreviewed, not release authority.
- Resumed connected diagnostic: temporary-LAN now passes an explicit planner seam to the existing production builder; only an underlying validated `no_answer` reaches the shared source recheck, preserving public replan metadata and fail-closed exclusions. Provider-free browser/HTTP real Markdown path passed `1/1` with document_text scope, native paragraph line/revision/lineage citation, greeting MCP `0`, same-session reload and real reset; paired focused handler/web run passed `2/2`. `py_compile` and Ruff check passed; format check reports pre-existing dirty-file reformat needs. No private provider/live browser acceptance or independent review.
- Latest canonical authority: `valid=true`, `ready=false`, `errors=[]`, `CJK=true`, execution `sha256:d7a1ddfde571afecb8675c6ef41f5b3c104afa527ebc0982238ccd10545d77e2`; preceding callback-only `sha256:a79838ef48f944cc87f1ce74c2d3ad1af24ad40dc086b864d5812d13687b42f6` is historical. Four gates remain blocked. Feature 待測, step 4 `in-progress`; no acceptance/promotion claim.
- Prior authority fingerprint `sha256:13268af51e1bf04c5a59a822662c4d39eb236ad4bfc5d345dbe4995f815d4143` is historical; latest canonical status remains valid but blocked, four gates, step 4 `in-progress`, feature 待測.
- Indexed stored-reference non-iteration is blocked: canonical test `test_persisted_session_graph_reopen_and_normal_query_without_source_scan` returned `OK (skipped=1)` because `FORMOWL_TEST_PROJECTION_POSTGRES_PASSWORD_FILE` is unset; isolated PostgreSQL fixture unavailable. Do not start a database or rebuild indexes. Live provider/browser acceptance, authority gates, and independent review remain open.
- Latest Master verification supersedes the pre-browser canonical `137/135/2` snapshot (`sha256:694d873d9e1d21c250114efd13cbc872d88fafef23742eca843c5337279d99f3`; its Chromium-tooling and PostgreSQL-fixture skips remain historical): four focused modules `138` total/`137` passed/`1` stored-reference PostgreSQL-credential skip (`168.380s`, exit `0`); two targeted browser tests passed `2/2` (`4.014s`), proving synthetic loopback rendered greeting/MCP `0`, reload, real reset after synthetic evidence seed, and a new session with no history/evidence. Five-file Python compilation/Ruff, JS syntax and diff-check passed; seven hashes stayed stable.
  Verified image `sha256:be432d14a9339a3bc08688c4a5cf2d561a91d5f335fa556ab62822ed3edef82f` is canonical base `sha256:bc2c2a2aa911994d2f4d8b2fe975838e060c0113bc980ebbd7b40f1d3a974787` plus one Node/Chromium package layer (Node `20.19.2`, Chromium `153.0.8010.52`, Python `3.12.11`); the same image was verified then retagged `formowl-dev:local`, prior image retained, full Dockerfile rebuild not run, live UAT/DB untouched. Canonical authority is `valid=true`, `ready=false`, `errors=[]`, `CJK=true`, four gates blocked, pre-doc-sync `sha256:e3c4878b12a5eb281c5229da36684dd1be26a1ad8b4ed897cab6b7415fe73ff4`. The sole skip was the missing PostgreSQL fixture credential (no DB start). Native pre-MCP error/reload/MCP `0` and prior-history preservation remain provider-free diagnostics; actual provider `408` cause is unproven. Full suite remains non-green/not rerun, independent review open, provider-disclosure denial binding. No live provider/private source or real mail/document E2E; feature 待測, step 4 `in-progress`, not delivered. Next: cited mail and independent-document first-miss recovery through the same core and the remaining approved acceptance gates.
- Sep24 follow-up: benign Chromium basic-only passed 00:19:23.586–00:19:32.783Z (MCP 0, reload, real reset, post-reset MCP 0); synthetic provider-free shared-core mail+independent-document browser 1/1 (5.678s), browser trio 3/3 (9.745s), web module 61 total/OK with 1 skip (164.455s). Master canonical discovery stopped at 78 tests/19.255s/1 error on `test_completed_ingestion_inline_and_attachment_rows_reach_candidate_index`: request-scoped candidate rows omitted their sealed table header. Loader now follows only the selected candidate-only row’s header locator through the same sealed exact-cell shard and revalidates job/hash/permission; candidate result/citation assertions added. Post-edit canonical test pending: host attempt stopped before import (`mcp` missing); `py_compile`/diff-check passed, Ruff unavailable. Master pre-edit authority `valid=true/ready=false/errors=[]/CJK=true`, `sha256:eefe5297cbfcf001385f9df5f17f63fa27bb56a1f3c082124aec5f087a8f6b2b`; host-only check invalid from missing CJK dependencies, not canonical. Four gates/reviewer/full regression open; full suite earlier interrupted exit 130. Private-mail live UAT remains explicitly denied; no provider/source call. Feature 待測, step 4 in-progress, not delivered; next run only the named canonical regression. Current first-finding update: Master reports the prior candidate-header test passed canonical `1/1` (`11.180s`); follow-on module `8`/`22.116s` had one error+one failure. Static trace identified the first test’s patched `query` shim passing `phase_trace` twice; it now overwrites the kwarg, retaining strict `isError=false` and result-type checks. The canonical rerun passed; the safe MCP error envelope remains unchanged and no malformed envelope is accepted. The focused network-none canonical test then passed `1/1` (`2.760s`) using `docker run --rm --network none -v "$PWD:/workspace:ro" -w /workspace -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/workspace/python:/workspace/tests formowl-dev:local python -m unittest test_connected_attachment_hybrid_e2e.ConnectedAttachmentHybridE2ETests.test_missing_projection_capabilities_return_filter_only_inventory_over_asgi`; the initial Docker API denial was resolved by approved escalation. The bounded next finding is `test_multilevel_attachment_headers_filter_and_project_over_asgi`. Master module run: `8` tests/`30.133s`, only this failure at line 1359 (lexical+grammar ledger count `0 != 2`). A network-none canonical diagnostic of the single test (`2.437s`, failed at the same assertion) inspected its real call/result boundary: class `evidence_lookup`, filter hashes `1`, projection hashes/pairs/ledgers `0`, provider binding absent; status `ok`, no exact result, structured values, governed refs, or citations. This is not typed planning superseding the old expectation: the source-backed query did not bind a table projection. At that earlier checkpoint no test/code edits had been made. The proposed hybrid query-time resolver was subsequently rejected because it traversed all provider occurrences and built a parallel projection map; that helper has been removed. Master canonical authority at that checkpoint was `valid=true/ready=false/errors=[]/CJK=true`, four gates blocked, `sha256:eefe5297cbfcf001385f9df5f17f63fa27bb56a1f3c082124aec5f087a8f6b2b`; the host CJK dependency failure is supplemental, not canonical. Later bounded repair: loader source-schema admission now adds `sha256_json(normalized_field)` only when the table row and cell are both validated `source_provided` and the tokenizer yields no tokens. Existing sealed capability mapping comparison remains in force; candidate-only rows are not promoted. `hybrid.py` has no residual helper/callsite changes. The strict test proves provider fingerprint, source-bound filter/projection hashes and ledgers, complete exact same-row `批=B-1`, and governed citation/lineage; an absent synthetic identifier returns `incomplete`, safe warning, no exact result, and no answer citations. Canonical command (read-only repo, network none): `docker run --rm --network none -v "$PWD:/workspace:ro" -w /workspace -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/workspace/python:/workspace/tests formowl-dev:local python -m unittest test_connected_attachment_hybrid_e2e.ConnectedAttachmentHybridE2ETests.test_multilevel_attachment_headers_filter_and_project_over_asgi`; after the Master-reported projection-binding failure (1/2.357s), first local canonical attempt failed at the stale missing-id exception assertion (1/3.287s), and the second/final attempt passed (1/4.169s, `OK`). The assertion now requires fail-closed incomplete/no-exact/no-citation behavior. Citation correction: the earlier probe measured only `exact_result` reference/citation fields; general `answer_citation_hashes` were not inspected, so total citations are unknown (no zero-total claim). Startup host authority check, run before this edit, was invalid only because CJK dependencies were unavailable (`sha256:a8590350adb7f062ea92174714d022fb9e1f72954b338b581c532986b16dcf7a`); it is supplemental. Master then ran post-edit canonical `python3 scripts/methodology_authority_check.py --check` (exit 0): `authority_valid=true`, `methodology_ready=false`, `errors=[]`, `CJK=true`, four gates blocked, `sha256:eefe5297cbfcf001385f9df5f17f63fa27bb56a1f3c082124aec5f087a8f6b2b`. Fingerprint unchanged; the check does not itself establish changed-loader execution acceptance. Master canonical `python -m unittest test_connected_attachment_hybrid_e2e` passed `8` tests in `26.148s` (OK, exit 0). In-memory compilation passed `3/3`; canonical Ruff `--no-cache` on loader and attachment test reported “All checks passed.” Loader, hybrid, and attachment-test SHA256 bytes stayed stable through verification. No provider/private source, database, index, or service actions. Feature 待測, step 4 `in-progress`, four authority gates and reviewer/full-regression/live mail+document acceptance remain open; not delivered. Coordination-frame compatibility slice: `ontology.py` and the historical experiment runner matched HEAD; the soft high-confidence mismatch remains non-hard and non-pruning. Test-only assertions now report the synthetic soft/hybrid false positive honestly and retain hard-gate rejection. Master canonical focused test `1/1` (`1.682s`) passed; module `15` tests (`18.428s`) has two remaining failures in 100-case/stress hybrid-delta expectations (`0.44` expected, `0.34` observed). No runtime/runner/scoring/threshold/fixture/report changes. Next bounded review: determine whether the two aggregate delta expectations are stale under the declared soft-signal contract; make no runner changes absent evidence. Master authority `valid=true`, `ready=false`, `errors=[]`, `CJK=true`, four gates blocked, `sha256:eefe5297cbfcf001385f9df5f17f63fa27bb56a1f3c082124aec5f087a8f6b2b`; this host-only check is supplemental and invalid solely for missing CJK dependencies. Feature 待測, step 4 in-progress; review, full regression, live mail/document acceptance and four gates remain open; no superiority/delivery claim. Correction/addendum: the preceding focused `1/1` (`1.682s`) and module `15` (`18.428s`, two failures) were Worker evidence, not Master evidence; the failed expectations (`0.44` vs `0.34`) are superseded by the current canonical module run. Master-provided runner summary confirms for both synthetic sets hybrid delta `0.34`, best arm `coordination_frame_v2_redacted`, hybrid exact/F1/false positives `0.8`/`0.94859`/`11` and `0.8`/`0.94859`/`1100`; soft exact/false positives `0.63`/`11` and `0.63`/`1100`, soft-vs-hard delta `0.41`, hard/v2 unchanged. Only the two test functions’ stale expectations/explicit false-positive checks changed. Canonical read-only network-none `python -m unittest test_coordination_frame_experiment`: `15` tests, `18.383s`, `OK`, zero skips. Master also reports independent ontology-contract test `1/1` (`0.000s`) and canonical in-memory syntax plus Ruff `--no-cache` pass. Master canonical authority is valid=true/ready=false/errors=[]/CJK=true, four gates blocked, `sha256:eefe5297cbfcf001385f9df5f17f63fa27bb56a1f3c082124aec5f087a8f6b2b`; separate Worker host-only authority check was invalid only for missing CJK dependencies and is not canonical. Feature 待測, step 4 in-progress; full regression, reviewer, non-live acceptance and four gates remain open; no completion/superiority claim. Archive-manifest integrity finding (Sep24): Master canonical fail-fast discovery was `431` tests/`103.258s`, `1` failure/`4` skips at `test_durable_archive_integrity.test_manifest_matches_every_lossless_snapshot`; this is not a passing full regression. The test matched HEAD before this slice. Before editing, read-only checks verified `docs/archive/2026-08-25/manifest.json` (`300` bytes/`12` lines, SHA-256 `80949f6e0290fa7e6890452c13778c5fab10f9e15cf9dd14cd257e62b72015ef`) and its sole snapshot `docs/archive/2026-08-25/handoff-log.md` (`20665` bytes/`300` lines, SHA-256 `476b5ca39860af6349b47f8eb633448d418c16752b7c9939e328a11a5a40ecf4`); both worktree files byte-match commit `04181cd`, and snapshot metadata matches manifest. Added only the explicit `SNAPSHOT_FILE_COUNTS["2026-08-25"] = 1`; no dated archive was modified and no dynamic inference added. One canonical network-none/read-only run of `test_durable_archive_integrity`: `4` tests/`0.018s`/`OK`, zero skips; Ruff `--no-cache` and in-memory `compile()` passed. Docker socket was initially denied in sandbox; the same bounded run succeeded after approved escalation. Master authority snapshot remains `valid=true/ready=false/errors=[]/CJK=true`, four gates blocked, `sha256:eefe5297cbfcf001385f9df5f17f63fa27bb56a1f3c082124aec5f087a8f6b2b`; not rerun here. Full regression is still not green/not rerun; feature 待測, step 4 in-progress, reviewer and live mail+independent-document acceptance remain open. Sep29 browser citation-boundary follow-up: the prior classify contract accepted arbitrary well-formed citation IDs when DOM labels matched. The runner now requires, only for `--synthetic-source-neutral`, an explicit safe expected binding from the fixture: source family plus answer and citation SHA-256 fingerprints; browser computes these locally and exposes only boolean verification/counts. Missing binding and a valid-looking arbitrary mail citation with unrelated answer both fail closed in the self-check. Existing synthetic mail and independent-document Chromium acceptance passed with `mail_source_binding_verified=true` and `document_source_binding_verified=true`; canonical two-test network-none/read-only run `2/2` in `5.828s` (`OK`). JS syntax, Ruff `--no-cache`, in-memory Python compile, and scoped diff-check passed. No provider/private source/live UAT, runtime, ingestion, service, DB, or index changes. Master authority remains valid but blocked with four gates; feature 待測, step 4 in-progress, reviewer/full regression/live mail+document acceptance open; no delivery claim. Issue #20 canonical onboarding follow-up (2026-09-29): stable AST serializer restored; focused completion_finalization + oauth_harness_execution passed 57/57. Onboarding fail-fast first failure remains changed=3065 vs manifest=713; canonical aggregate was 103 tests/6 failures. A bounded search of 56 reachable candidate commits and 26 unreachable commits found no matching 713-entry snapshot (the only unreachable manifest had 689 entries). The current 713-entry manifest is untracked and has no source-snapshot provenance. Do not adjust counts or hashes; next requires an authorized immutable snapshot or a fresh Issue #20 scope decision. Issue #20 remains open and unchecked. Latest Master-verified per-turn MCP deadline change evidence: focused tests `3/3`; full `tests.test_issue56_uat_web_e2e` passed `62` tests with `1` skip in `160.855 s`; in-memory compile, Ruff, and `git diff --check` passed. This remains provider-free evidence: live provider/private-source/deployment acceptance is blocked; feature remains 待測 and step 4 `in-progress`.
## 2026-09-29 — Earlier bounded UAT checkpoint
- Focused dev-container regression passed `131` tests with `1` skip; Node self-check, `py_compile`, Ruff, and diff-check passed.
- First live Chromium ordinary path passed MCP `0`; mail initially failed with `tool_execution_failed`/`0` citations at PostgreSQL `statement_timeout`.
- Warm-cache diagnostic passed HTTP `200`, MCP `1`/`ok`, raw citations `15`, presented citations `8`, partial cited result; reload/reset/post-reset passed.
- `source_binding_verified=false`, `methodology_ready=false`; feature remains **待測** and no standard, production, readiness, or timeout-boundary claim is supported. Security, permission, provenance, and existing `1.5s` timeout boundaries were preserved; archive files remain unchanged.
## 2026-09-29 — Current bounded mail/UAT checkpoint
- Worker A runtime is recorded as `gpt-6-luna`/`reasoning_effort=max`; bounded multi-selector mail fallback is in `python/formowl_mail/query.py` with focused regression in `tests/test_issue56_uat_handler_composition.py`.
- Focused handler/provider suite `108/108`; canonical web module `63` tests, `1` skipped, `OK`; canonical authority `--check` `valid=true`, `methodology_ready=false`, four gates blocked.
- Local Chromium basic passed ordinary MCP `0` plus reload/reset/post-reset. Real provider-backed mail passed `mail_cited_result`, HTTP `200`, MCP `1` status `ok`, `8` citations, selector hash `df85...`; reload/reset/ordinary follow-ups passed with MCP `0`.
- Provider finalization still had `empty_response_body`/partial outcomes; no complete provider final answer or 待測 promotion to 標準功能. Lifecycle remains `active-blocked`; no methodology/comparative claim.
