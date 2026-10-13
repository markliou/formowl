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

## 2026-09-22 — Token-driven two-worker hard cap
- Canonical AGENTS.md (AGENT.md absent) caps total implementation workers at two, including nested workers.
- Reuse the existing A/B pair for follow-ups; no duplicate delegations.
- No third, replacement, new worker, or descendants without explicit new user authorization.
- Master remains orchestration-only; workers stay `gpt-5.6-luna`/`max`, UAT `gpt-5.5`/`high`.
- Safety, blocked methodology authority, and three-reviewer acceptance gates remain unchanged; no reviewer gate claimed.

## 2026-09-21 — Current worker specification and composition-test handoff
- The current issue #56 worker specification is exactly two implementation
  workers on `gpt-5.6-luna` with `reasoning_effort=max`; the UAT provider remains
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

## 2026-09-16 — Bounded UAT/MCP safety handoff
- The bounded UAT/MCP safety slice is focused-green: MCP gate `4/4`, provider
  bridge `46/46`, authority `23/23`, and UAT web `17 passed / 1 skipped`.
- Provider classification now requires zero FormOwl attempts for
  `provider_pre_mcp_failure`; a post-MCP HTTP `408` remains `http_error`, with
  bounded evidence/citations retained and private provider detail redacted.
- Canonical authority `--check` is valid but `methodology_ready=false`;
  `--require-ready` exits nonzero with the four existing gates blocked.
- Full discovery reached `2114` tests with `868` failures, `50` errors, and
  `19` skips in the already-dirty broad workspace; this is not a slice
  acceptance blocker.
- Restart blocker: after restart, the named UAT exited `1` with `OOM=false`;
  it has not been retried, so no live acceptance is established.
- No external provider retry, readiness, superiority, or completion claim is
  made.

## 2026-09-16 — Bounded Chromium acceptance preparation
- Worker B removed the redundant provider-only greeting override and added a
  composition regression test proving the provider consults the shared
  semantic-plan gate. No Worker A path, transport, budget, or model was
  changed.
- Prepared `/tmp/formowl-uat-chromium-acceptance.js`: real Chromium/CDP,
  fresh browser context, initial empty-transcript assertion, ordinary chat
  first, mail second only after ordinary success, response observation without
  stubbing, and output restricted to safe status/count/timing/visible-text
  fields. `node --check` and `--self-check` passed.
- Do not treat self-check or focused unit checks as external acceptance. Docker
  validator rerun was blocked by rejected socket escalation; no restart and no
  provider request occurred. Await Master GO plus A's focused result.

## 2026-09-16 — Chromium runner safe diagnostic projection
- After Master GO, Worker B changed only `/tmp/formowl-uat-chromium-acceptance.js`
  and this handoff entry. Acceptance predicates remain unchanged: ordinary chat
  must pass first, and mail still requires a visible cited result.
- Safe runner output now retains bounded HTTP/response status, reason code,
  provider phase and stop enums, provider phase timings, MCP call/status/
  timeout/failure reason, and payload citation count. No prompt, mail text,
  provider body, secret, URL, or filesystem path is emitted.
- `node --check /tmp/formowl-uat-chromium-acceptance.js` and
  `node /tmp/formowl-uat-chromium-acceptance.js --self-check` passed.
  No provider request, service restart, or container metadata read occurred.
- This is runner diagnostic evidence only; external acceptance, methodology
  readiness, superiority, and completion remain blocked.

## 2026-09-21 — Bounded browser partial-fallback handoff
- Safe browser evidence: ordinary HTTP `200`/MCP `0`; mail HTTP `200` with
  two MCP calls (`ok`, `mcp_failed`), `8` projected citations, `partial`
  public fallback, and provider empty-body finalization failure.
- `mail_unsafe_failure` is expected: the runner's `hasFailure` gate prevents a
  cited-success claim after any MCP failure; the operational-failure branch
  intentionally requires an error turn with zero citations. The public
  fallback is explicitly incomplete and bounded, not definitive no-data.
- No code or live/provider rerun was performed. Worker A owns the next
  investigation of structured `tool_execution_failed`; do not weaken the
  browser acceptance predicate.

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
- 2026-09-22 current checkpoint: cap=2; both workers are
  `gpt-5.6-luna`/`max`, with no new worker or descendant. Master canonical
  focused verification passed `100/100`. Canonical authority is
  `authority_valid=true`, `methodology_ready=false`; four methodology gates
  remain blocked. After the single controlled UAT restart, startup completed;
  existing Playwright Chromium ordinary chat passed with MCP `0`, while mail
  returned HTTP `200` with `ContractValidationError`/`tool_execution_failed`,
  `0` citations, then empty provider finalization. Reload/reset/post-reset
  follow-ups did not run; UAT acceptance is **NOT complete**. Two resident-log
  owner entries were `semantic_plan.route_semantic_query:808`, but association
  with the latest browser run is unconfirmed; no lineage-mismatch root-cause
  claim is made. `本次 live owner 尚待 request/trace 關聯確認`.
