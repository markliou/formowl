# Agent Handoff Log
Lifecycle label: `active`.
This bounded active window is backed by
[docs/archive/2026-10-01/handoff-log.md](../../docs/archive/2026-10-01/handoff-log.md);
earlier entries are immutable. Detailed older logs remain at
`../archive/2026-08-25/handoff-log.md` and `../archive/2026-08-18/active/docs/agent-goals/handoff-log.md`.
## Retention Rule
- Keep the latest 14 calendar days and at most 300 lines.
- Archive a complete dated entry before trimming it.
- Record only current facts, blockers, verification, and next action.
- Historical pointers are not restart instructions.
## Latest status correction — 2026-10-04 UTC
- A own metadata verified before edits: task `01a1072a-1df8-7801-9333-4990432b6339`, turn `01a107e7-2c24-71b3-aea7-7daa398d3183`, UTC `2026-10-04T17:12:33.783Z`, model `gpt-6.1-sol`, effort `high`, status `verified_match`. Scope remains only board/KG goal/handoff; no descendants or code/runtime writes.
- User approved B recreation. Replacement B task `01a107d3-32d2-73f0-8f33-aef81b11d058`, native turn `01a107d3-336f-7b71-8472-849111f16f30`, UTC `2026-10-04T16:50:45.418Z`, sol/high, was verified by Master and B. Old B task `01a10765-95a0-7a73-b04d-7e3a2567f4b4` is closed and never resumed. Replacement handle was closed only to release the writer lock; exact CLI resume task identity was then verified by Master: turn `01a107e5-c9aa-7d00-9e17-51d82dd17fed`, UTC `2026-10-04T17:11:02.764Z`, sol/high. Total remains A+B two; no substitute.
- B changed only `python/formowl_graph/index/records.py` and `tests/test_graph_index_stores.py`, combining checkpoint/candidate helper reads. Master canonical graph-index test: `17` run / `16` passed / `1` skipped / `0.034s`; do not repeat the earlier `18`-pass count. Live performance impact is unproved; helper payload-id validation loss is B follow-up in progress. `/tmp/formowl-worker-b-replacement-followup.txt` was absent and is recorded pending.
- Master read-only evidence: active revision helper125/candidate125/posting3015, shortlist bound to revision125; out-of-index fallback is bounded sequential sealed refs, not full-source indexed search. EXPLAIN uses full MD5 token/helper observation_hash keys; warm synthetic-neutral SQL `3.23ms`/count0; COLLATE patch rejected because the diagnostic variant lost hash Index Cond. Earlier cold QueryCanceled450ms/wall818.166ms remains observed, not a single proved cause. Three PG samples showed graph_records SELECT/INSERT/INSERT with DataFileRead; indexes valid/ready, no bottleneck proved.
- Larger build latest safe sample `120640` candidates/`162159.674s`, dense commit `162162.249s`, still running/OOM false with unchanged start/caps; one snapshot build CPU `0.06%`/PostgreSQL `101.94%` remains historical. UAT active bounded125, started `2026-10-04T14:06:43.172703447Z`; no completion/seal/activation or acceptance claim.
- Pre-B-patch Master canonical authority: valid=true/ready=false/errors=[]/CJK=true, execution `sha256:68e84fd7a00f14d8f727aeb3bdd2403b9b0a77808bdb25b5d431c16308b09418`. Four gates, three reviewers, full regression non-green and 待測/step4 remain. Next is bounded searchable-coverage/build-throughput engineering; source seal/activation needs separate applicable authorization. No new provider/build/service/activation/browser action or acceptance.

## Prior status sync — 2026-10-04 (collation next action superseded by latest correction)
- Worker A reverified its own worker-owned persisted turn before this docs-only sync: task `01a1072a-1df8-7801-9333-4990432b6339`, turn `01a107ba-d2d4-7051-9d7b-b02a5e71a392`, UTC `2026-10-04T16:24:07.024Z`, outcome `verified_match`. No descendants or out-of-scope writes.
- Master reports B task `01a10765-95a0-7a73-b04d-7e3a2567f4b4`, turn `01a10775-ec95-72b0-b7c9-4c172bc2d3f3`, sol/high; B UTC was not supplied and is not inferred. B's MD5 lexical optimization retained raw-token collision equality.
- Subsequent browser business MCP1 completed in approximately `3.4s` without exception but returned `pending_review`/citations0. Latest recovery log reports `deadline`/`scanned_observation_count=0`; this is not a proved cause.
- B changed only the `test_typed_exact_request_fails_closed_without_exact_result` fixture in `tests/test_issue56_sealed_source_loader_e2e.py`; focused `1` and module `13`/`484.210s` passed. Earlier Master module `13`/`504.519s` had one sealed-source fixture error.
- Master verified the active-revision CLI digest and `store.reopen` seal. This establishes activation binding only, not source completeness, candidate equality, root cause, or UAT acceptance. Projection latest prior sample: `116736` candidates at `158784.149s`, still running. UAT bounded retrieval `128` started `2026-10-04T14:06:43.172703447Z`.
- Read-only neutral-term lookup recorded mail `QueryCanceled` wall `818.166ms` at SQL budget `450ms` (manifest `82.396ms`, setup `163.301ms`, query `504.929ms`); document lookup returned `0` rows in `258.186ms`. Existing indexes were used; full key use remains under investigation.
- Next: Master investigates execution-plan collation; B follows only with a narrow evidence-backed patch if justified. Feature remains 待測/`active-blocked`, step 4 `in-progress`, authority blocked, full regression non-green, and three independent reviewers/four methodology gates open. No runtime/code/provider/service writes or broad tests.

## Current operating boundary — latest 2026-10-04 override
- Exactly two ordinary workers use `gpt-6.1-sol` / `reasoning_effort=high` (not xhigh), superseding the earlier same-day sol/xhigh and luna/max tiers.
- Worker A verified its own worker-owned native `turn_context` before edits:
  task `01a1072a-1df8-7801-9333-4990432b6339`, turn `01a1072a-1e72-7543-a833-ad40395541d1`, UTC `2026-10-04T13:46:03.761Z`, `model=gpt-6.1-sol`, `effort=high`, outcome `verified_match`.
  Session task identity matched; the same sol/high turn was reverified before edits after the scope follow-up.
- Master independently reports current worker-owned sol/high verification for A above and B task `01a1072d-4f85-70a0-9ed4-f17c0598f6cc`, turn `01a1072d-5013-7643-af66-3b4043ccf498`, UTC `2026-10-04T13:49:33.374Z`, `model=gpt-6.1-sol`, `effort=high`, outcome `verified_match`. B evidence is Master-reported, not A's metadata inspection.
- Historical earlier 2026-10-04 xhigh evidence (preserved, not current-tier proof): Worker A verified worker-owned native records for
  A task `01a10623-0123-7b03-bbdc-9dfcd304e744`, turn `01a10623-01e1-7e40-9ca7-dbfd75fc5be6`, UTC `2026-10-04T08:58:41.085Z`, `model=gpt-6.1-sol`, `effort=xhigh`; and
  B task `01a10623-7d32-7b21-a364-2fbb2d7fe1a7`, turn `01a10623-7db5-73b1-b9d4-a55f188ed73b`, UTC `2026-10-04T08:59:12.103Z`, `model=gpt-6.1-sol`, `effort=xhigh`.
- First dispatch and every future resume explicitly configure both model and effort as sol/high; no unpinned `send_input`. Each worker verifies its own persisted turn before edits; inherited contexts, prompt text, or running status are not proof.
  Missing/mismatched metadata or model unavailability blocks work; minimal read-only inspection is authorized, retaining safe task/turn IDs, UTC, model, effort and outcome only, never raw paths/content, prompts or secrets.
- No descendants, substitution, duplication, additional worker, or old-worker resume. Prior old-A close lookup returned not found, not proof of closure; prior B and Hubble are closed per this handoff, and Hubble is not an active release reviewer.
- Historical luna/max tasks verified by Master on 2026-10-03: A `01a1011d-2f8d-75b0-afc1-17ccf9ce9f9b` at `2026-10-03T09:34:13.887Z`; B `01a1011d-af51-7733-9c67-23513ce95804` at `2026-10-03T09:34:45.960Z`. Do not resume them.
- Master remains orchestration-only/no repository writes. A owns only the seven authorized tier/status docs paths plus the explicitly added `reviewer-gate.md` current worker-tier paragraph; B separately owns ONLY bounded lexical optimization code/tests. Disjoint write sets; no provider, deployment, private-source, source/index rebuild, build activation, or live UAT action is authorized here.
- UAT remains `gpt-5.5`/`high`; feature 待測, role `active-blocked`, step 4 `in-progress`, four methodology gates blocked. Three independent read-only reviewers remain required; no acceptance/reviewer/release claim.
- Latest user-supplied 2026-10-04 checkpoint (not rerun by docs worker): bounded alias SQL patch preserved; graph-index `16` tests/`1` skip `OK`; integration `155` tests/`1` sealed-source fixture error, not proved baseline.
  Chromium ordinary chat/reload/reset MCP0 passed; business reached `query_effective_graph_view` MCP1 but `tool_execution_failed`/`mcp_exception`, citations0. PostgreSQL statement timeout at `source_family_lexical_lookup` is operational failure, not absence. Next is B's lexical optimization.
- Current A host startup authority `--check` exited 2: dependencies unavailable, CJK=false, `passed_runtime_gate_requires_cjk_runtime_support`; supplemental only, not canonical runtime evidence. Canonical docs-focused checks pending; no broad tests.
- Master separately reports current canonical authority `--check` exit0: valid=true/ready=false/errors=[]/CJK=true, execution `sha256:c671ee613b915d2576a60f894d0cc0516b833ec5afe29b11835635c5085edfee`; four gates remain blocked.
- After this documentation sync, the canonical network-none/read-only container
  check remained valid=true/ready=false/errors=[]/CJK=true with four gates
  blocked; its current execution fingerprint is
  `sha256:68e84fd7a00f14d8f727aeb3bdd2403b9b0a77808bdb25b5d431c16308b09418`.
  The single documentation guard test passed; no broad tests were run.
- Historical Master canonical authority exited 0: valid=true/ready=false/errors=[]/CJK=true, execution `sha256:9224df402f112f32509bab1250ab836cfa8e9056898ac9249a4fa3b5553ff611`.
  Historical earlier A host check failed only for unavailable tokenizer dependencies. Earlier canonical read-only/network-none authority exited 0: valid=true/ready=false/errors=[]/CJK=true, four gates blocked, execution `sha256:a1c29a8cbee8518a7d94053d40a70da7b41126061eba71438dbe2b25b8e5db4a`.
  Historical tier-doc consistency `9/9` (`0.085s`), scoped diff-check passed; full regression/UAT/reviewer gate not run by that docs-only worker.
- Historical 2026-10-03 Master snapshot: projection started `2026-10-02T19:50:12Z`, running/OOM false under `8 GiB`/no swap/4 CPU; candidates `7584` at elapsed `49,661.086s`.
  Manifest `sealed=false`; `revision.json`, `revision.pending`, `build-report.json` absent. UAT unchanged `05:26:15Z` start; four frozen runtime/runner SHA256 fingerprints matched prior handoff, no production edits. Snapshot only, not completion/release proof.
- Historical B narrow-test correction: Master inspected canonical `1/1` in `1.824s` after source-bound fixture plus value-only rejection in `tests/test_issue56_hybrid_batch_encoding.py`; no runtime edit. Full regression remained non-green; other three known direct failures unresolved. Diagnostic only, no feature completion.

## 2026-10-03 — Browser/provider control checkpoint
- Two safe browser diagnostics: ordinary MCP `0`; both mail turns failed operationally (HTTP `200`, tool/citations `0/0`, empty body after `45.431s`/`45.316s`). No mail MCP, absence determination, or reload/reset; not acceptance.
- Controls: local reporter `RuntimeError` was not a provider failure; corrected forced/strict probes passed. Synthetic first planning selected FormOwl in `23.313s`, reads/MCP `0/0`; the full-schema synthetic first-planning control completed; both non-stream/SSE controls selected one FormOwl function; no MCP was executed. The paired controls are not exact live replay because history/capability metadata differ. HTTP `200` is UI/browser status only, not provider success. Workspace files are newer than the UAT start and loaded-code identity is unverified; this is a comparability blocker, not a proved cause.
- A later resume observed `gpt-6-astra`/`xhigh`; native-luna preflight completed at `xhigh`, received no write assignment; closure is unproved; B native retains `max`. No implementation/runtime/provider/test/service edits or live calls in this docs-only handoff; no completion claim.
- Follow-up probe: canonical `formowl-dev:local` network-none/read-only projection retained the valid attempt but dropped upstream HTTP status and top/attempt `request_shape`; absent fields cannot prove old loaded code. `offered_tool_fingerprint` hashes tool names only, not descriptors/request identity. Native TUI acknowledgement was insufficient; direct `multi_agent_v1.send_input` verified B `gpt-6-luna`/`max`. Runtime remains frozen; no root-cause or acceptance claim.

## 2026-10-03 — Read-only deployment/request comparability investigation handoff
- UAT started `2026-10-02T05:26:15Z`; workspace bind-mount files were newer than that start. Browser ordinary passed MCP `0`; mail had two HTTP `200` UI-only attempts, MCP/citations `0/0`, `empty_response_body` after approximately `45.431s`/`45.316s`; source absence was not established and exact live root cause remains unproved.
- Upstream status/request-shape projection was lost, and names-only tool fingerprints are insufficient. Feature remains 待測, `active-blocked`, step 4 `in-progress`; no acceptance claim.

## Prior 2026-10-03 — Dense/candidate projection and frozen runner checkpoint
- The latest authorization covers the three engineering items and a full
  same-owner build, not release. Mixed preparation contains `11,386,697`
  observations; `prepared_source_metadata_ready` completed `2,710,517`
  references in `43,192.612s`.
- The build remains in dense/candidate processing, OOM false under
  `8 GiB`/no-swap/4-CPU caps. Latest persisted candidate count is `3136` at
  elapsed `46,063.165s`, RSS `2,482,438,144` bytes; this is a timestamped
  snapshot, not a completion/equality claim. Manifest `sealed=false`;
  `revision.json`, `revision.pending`, and build-report are absent.
- A bounded `29`-batch log analysis measured dense-commit→candidate-persist
  median `22.9s` and candidate-batch interval `26.824s`, including conversion
  and persistence; it is not exclusive SQL timing or an ETA.
- UAT remains unchanged, health connected/OK, with bounded retrieval `128`. The prior real browser
  basic chat/reload/reset/post-reset path passed MCP=0. Mail prompt
  `把嘉值交期調閱出來` failed with two MCP calls, `pending_review`, citations0,
  and `clarification_required`; this is not absence or acceptance.
- Manual stop/trace fixtures missed the actual `_call → TestClient → MCP`
  `unsupported/planner_stopped_partial` case; the narrow provenance-bound
  correction passed focused verification but remains undeployed/synthetic.
- The frozen live-document runner correction uses manifest-bound citation IDs,
  source/revision fingerprints, positive line ranges, and required snippets
  without a preknown answer hash. SHA256 is
  `29e8c7ad273681906eaaaa255d15f0e3ac7059b0482102a6e716073a80e5b02e`.
  Master’s network-none resource-limited runner self-check/basic/source-neutral
  browser checks passed `3/3` in `34.401s`; this is not live provider proof.
- Next safe sequence after the build is seal/reopen/fresh load, then in-place
  original UAT with chat, mail prompt `嘉值`, independent document, reload, and
  reset/contextless chat. No alternate service/index, raw reingestion, or unchanged canary retry.
- Canonical authority `--check` exited 0: valid=true, ready=false, errors=[],
  CJK=true, execution
  `sha256:9224df402f112f32509bab1250ab836cfa8e9056898ac9249a4fa3b5553ff611`.
  Full regression session69745 exited 1: `2317` tests / `3767.629s`, `91`
  failures, `49` errors, `19` skips (subtests included); truncated tool output
  retains totals, not a complete per-test failure inventory. No pass count or
  pre-existing label is inferred; the four focused failures log is retained externally.
- Master independently reproduced the directly related failures in canonical
  network-none read-only `formowl-dev` at `2 GiB`/2 CPU: `4` tests / `2.894s` /
  errors4 / exit1. Read-only review found the untyped enumeration failure is a
  value-only `combined_present_intersection_v1` fixture lacking the required
  distinct projection binding, not a demonstrated runtime defect; the smallest
  correction is test-only and was not implemented/tested. A separate
  candidate-table case is a test provider-policy/resource-kind mismatch, not a
  general document-provider regression. The two requested-projection fixtures
  fail before assertions because their SimpleNamespace index lacks
  `_runtime_store`; none of these cases classifies all 49 errors as fixtures.
- Host `8088` maps to container `8766`; host `/api/health` returned HTTP 200,
  `status=ok`, `query_service_connected=true`. The earlier inside-container
  `127.0.0.1:8088` refusal used the wrong port and is not a UAT outage; no
  restart/start-time change occurred. Code remains frozen, ordinary worker
  model unavailable. Feature 待測, active-blocked, step 4 `in-progress`;
  four gates, live acceptance, independent reviewers, and release/standard
  claims remain open. No code/test/service/DB/build changes or live reruns,
  launch, or completion claim.

## 2026-10-01 UTC (Oct 2 Asia/Taipei) — Historical cited-mail UAT checkpoint
- Master’s seven-module canonical provider-free regression passed `241` tests / `199.943s` / `OK` / `1` skip; imported handler tests include a duplicate, so this is not full-repository regression. Modules: evidence-presentation budget, provider finalization, Codex provider bridge, mail UAT HTTP, UAT handler composition, UAT web E2E, KG-first cross-resource retrieval. The earlier expanded run was `156` / `201.343s`, `5` failures, `1` error, `1` skip; test-only expectation/fixture corrections preceded the pass. Scoped Ruff and Node self-check passed.
- Canonical authority: valid=true, ready=false, errors=[], CJK=true; four gates remain blocked; execution `sha256:c9d9e2dc183926f9c7c9fbff266759fa7b03b8256ed0810830b406ed1794b401`.
- Chromium `2026-10-01T20:49:09.753Z–20:50:42.936Z` (Oct 2 Taipei): ordinary passed MCP `0` / `5.284s`; mail was `mail_cited_result` but HTTP/UI remained partial / `82.778s`, MCP `1` `ok` / `2.976s`, `87` raw → `19` presented → `19` final/browser citations. Finalization passed without repair; all `3` provider attempts completed.
- Reload preserved content/shape; real reset returned empty; contextless chat passed MCP `0` / `3.854s`. UI partial and ~`82.8s` latency are not complete-inventory or performance acceptance.
- Prior `116.477s` browser attempt was marked failed because diagnostics truncated a bounded repair that produced `9` valid citations; it was not accepted and follow-ups were absent. An earlier `120.338s` partial turn also timed out at finalization; preserve both as failures.
- No deployed runtime changed after latest browser: checked source-tree fingerprint `ba8e04d6f30cfdb1495a7c3e4e1cdbb4a669ecadf7ba80450653d87b96276114`; only two test-file hashes changed afterward. Shared evidence-presentation budget is `16 KiB` UTF-8 evidence data, preserving whole provenance groups and omitting exact inventory all-or-none; it is not a whole-request/context-size cap. Provider diagnostics retain authoritative count (max `6`, from existing budgets) and latest `3` records; no timeout/retry/execution budget increased.
- Recheck reads sealed job/hash/permission/scope references beyond the `125` retrieval canary, capped at `500ms` / `8192`; incomplete is not absence. Original intent/claim/scope, same-item AND, and exact grammar remain bound; source-family-only required-term rejection is mail-only, not graph/document.
- Browser used inherited source pin `d83b2d92330cafc6b46bd93eabef3b8aa624817d9a6223b1f401589ec5a1d4e5`, not fresh oracle proof. `source_binding_verified=false`; Master’s visual first-topic/citation sample was not an independent source audit. Raw expanded tool-query/required-term values were not retained in safe traces.
- Feature remains 待測, step 4 `in-progress`; live independent-document acceptance, full repository regression, three reviewers, and all four methodology gates remain open. Known mail prompt is development smoke only; unseen questions remain frozen. Next: independent-document acceptance and remaining gates; no smoke-specific tuning. No additional tests/provider calls were made in this docs-only sync.

## 2026-10-01 — Earlier bounded POC/UAT-preparation scope
- Authorized scope: distinguish development POC from security-review acceptance in
  `SPEC.md` and active instructions, plus at most one generic synthetic mail
  selector regression. No runtime-policy/routing changes or live private-mail/
  provider UAT; the known mail prompt is a smoke case, not a tuning or holdout
  target. Future questions stay unseen/frozen; freeze code/prompt/model/source
  fingerprints before acceptance, and use a new version/new holdout after tuning.
- An authorized all-mail request may search the connected account's bounded,
  permission-filtered scope, but must not dump the corpus to a provider. Ordinary
  chat remains MCP=0; mail and standalone Markdown/plain-text lookup retain the
  same recheck core and existing minimum audit/fail-closed boundaries.
- Feature remains 待測 and plan step 4 `in-progress`; methodology claims remain
  blocked. Master will run the focused canonical tests after handoff.
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

## 2026-10-01 — Earlier UAT and retrieval-coverage checkpoint (superseded)
- Canonical six-module integration: `180` tests in `177.397s`, `OK`, `1` skip
  (not full regression). Provider bridge: `75/75` in `2.053s`; Ruff passed.
  Canonical authority `--check`: valid=true, ready=false, errors=[], CJK=true;
  four gates blocked.
- Latest Chromium `2026-10-01T17:28:13.143Z–17:28:36.031Z`: ordinary chat
  passed (MCP `0`, `6.701s`); mail failed after `15.640s` (MCP `1`,
  `pending_review`, zero citations), source recheck used/incomplete,
  `required_term_count=2`. Same terms fingerprint as the previous attempt;
  raw expanded tool-query/required-term values were not retained in safe
  traces. The browser prompt remains in runner/screenshot artifacts; the safe
  artifact is retained outside this durable handoff. Runtime tree and 18 hashes
  are unchanged.
- An earlier descriptor-only live attempt (`17:09:38Z–17:10:20Z`) also failed
  mail after `37.679s`. Thus current MCP description and provider instruction
  consistency fixes do not establish live success. Master is preparing a
  private observer diagnostic of provider argument roles and matcher-rejection
  counts only; it is not acceptance and must not retain/reconstruct terms.
- The sealed-reference reader now loads authorized observations by validated
  job/hash/scope references instead of relying only on the `125` retrieval
  canary. It remains bounded at `500ms`/`8192`; incomplete scan/coverage remains
  `pending_review`, not absence. Earlier canary-only behavior is superseded.
- Original intent, claim ceiling, and scope are bound across provider expansion;
  shared exact-output grammar retains its three-part tuple. Mail descriptor and
  provider guidance specify grounded `required_terms`, same-item AND, content
  versus scope routing, and trusted `request_contract`, with graph-only
  prohibitions retained. Provider-free explicit-term normal-MCP returned `60`
  citations with terms preserved; it was not an unknown-arguments replay.
- Bounded SSE continuation and strict finalization acceptance have synthetic
  diagnostics only. Feature remains 待測, step 4 `in-progress`; full regression,
  live mail and independent-document acceptance, three reviewers, and all four
  methodology gates remain open. Known prompt is development smoke only and is
  retained in runner/screenshot artifacts; no name/alias tuning or new holdout use.

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
## Current carry-forward
- Frozen target/tokenizer and strong-RAG control remain unchanged; KG/ontology
  claims require source-preserving, permission-filtered, same-pipeline evidence.
- Full-source activation, holdouts, transfer, source-complete UAT, provider
  acceptance, and final-answer review remain incomplete; step 4 is
  `in-progress`.
- Preserve candidate-before-canonical, provenance, permissions, redaction,
  no-secret/no-raw-path, fail-closed authority, and no-rerun boundaries.
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
- Sep24 follow-up: benign Chromium basic-only passed 00:19:23.586–00:19:32.783Z (MCP 0, reload, real reset, post-reset MCP 0); synthetic provider-free shared-core mail+independent-document browser 1/1 (5.678s), browser trio 3/3 (9.745s), web module 61 total/OK with 1 skip (164.455s). Master canonical discovery stopped at 78 tests/19.255s/1 error on `test_completed_ingestion_inline_and_attachment_rows_reach_candidate_index`: request-scoped candidate rows omitted their sealed table header. Loader now follows only the selected candidate-only row’s header locator through the same sealed exact-cell shard and revalidates job/hash/permission; candidate result/citation assertions added. Post-edit canonical test pending: host attempt stopped before import (`mcp` missing); `py_compile`/diff-check passed, Ruff unavailable. Master pre-edit authority `valid=true/ready=false/errors=[]/CJK=true`, `sha256:eefe5297cbfcf001385f9df5f17f63fa27bb56a1f3c082124aec5f087a8f6b2b`; host-only check invalid from missing CJK dependencies, not canonical. Four gates/reviewer/full regression open; full suite earlier interrupted exit 130. Private-mail live UAT remains explicitly denied; no provider/source call. Feature 待測, step 4 in-progress, not delivered; next run only the named canonical regression. Current first-finding update: Master reports the prior candidate-header test passed canonical `1/1` (`11.180s`); follow-on module `8`/`22.116s` had one error+one failure. Static trace identified the first test’s patched `query` shim passing `phase_trace` twice; it now overwrites the kwarg, retaining strict `isError=false` and result-type checks. The canonical rerun passed; the safe MCP error envelope remains unchanged and no malformed envelope is accepted. The focused network-none canonical test then passed `1/1` (`2.760s`) using `the canonical network-none container unittest command test_connected_attachment_hybrid_e2e.ConnectedAttachmentHybridE2ETests.test_missing_projection_capabilities_return_filter_only_inventory_over_asgi`; the initial Docker API denial was resolved by approved escalation. The bounded next finding is `test_multilevel_attachment_headers_filter_and_project_over_asgi`. Master module run: `8` tests/`30.133s`, only this failure at line 1359 (lexical+grammar ledger count `0 != 2`). A network-none canonical diagnostic of the single test (`2.437s`, failed at the same assertion) inspected its real call/result boundary: class `evidence_lookup`, filter hashes `1`, projection hashes/pairs/ledgers `0`, provider binding absent; status `ok`, no exact result, structured values, governed refs, or citations. This is not typed planning superseding the old expectation: the source-backed query did not bind a table projection. At that earlier checkpoint no test/code edits had been made. The proposed hybrid query-time resolver was subsequently rejected because it traversed all provider occurrences and built a parallel projection map; that helper has been removed. Master canonical authority at that checkpoint was `valid=true/ready=false/errors=[]/CJK=true`, four gates blocked, `sha256:eefe5297cbfcf001385f9df5f17f63fa27bb56a1f3c082124aec5f087a8f6b2b`; the host CJK dependency failure is supplemental, not canonical. Later bounded repair: loader source-schema admission now adds `sha256_json(normalized_field)` only when the table row and cell are both validated `source_provided` and the tokenizer yields no tokens. Existing sealed capability mapping comparison remains in force; candidate-only rows are not promoted. `hybrid.py` has no residual helper/callsite changes. The strict test proves provider fingerprint, source-bound filter/projection hashes and ledgers, complete exact same-row `批=B-1`, and governed citation/lineage; an absent synthetic identifier returns `incomplete`, safe warning, no exact result, and no answer citations. Canonical command (read-only repo, network none): `the canonical network-none container unittest command test_connected_attachment_hybrid_e2e.ConnectedAttachmentHybridE2ETests.test_multilevel_attachment_headers_filter_and_project_over_asgi`; after the Master-reported projection-binding failure (1/2.357s), first local canonical attempt failed at the stale missing-id exception assertion (1/3.287s), and the second/final attempt passed (1/4.169s, `OK`). The assertion now requires fail-closed incomplete/no-exact/no-citation behavior. Citation correction: the earlier probe measured only `exact_result` reference/citation fields; general `answer_citation_hashes` were not inspected, so total citations are unknown (no zero-total claim). Startup host authority check, run before this edit, was invalid only because CJK dependencies were unavailable (`sha256:a8590350adb7f062ea92174714d022fb9e1f72954b338b581c532986b16dcf7a`); it is supplemental. Master then ran post-edit canonical `python3 scripts/methodology_authority_check.py --check` (exit 0): `authority_valid=true`, `methodology_ready=false`, `errors=[]`, `CJK=true`, four gates blocked, `sha256:eefe5297cbfcf001385f9df5f17f63fa27bb56a1f3c082124aec5f087a8f6b2b`. Fingerprint unchanged; the check does not itself establish changed-loader execution acceptance. Master canonical `python -m unittest test_connected_attachment_hybrid_e2e` passed `8` tests in `26.148s` (OK, exit 0). In-memory compilation passed `3/3`; canonical Ruff `--no-cache` on loader and attachment test reported “All checks passed.” Loader, hybrid, and attachment-test SHA256 bytes stayed stable through verification. No provider/private source, database, index, or service actions. Feature 待測, step 4 `in-progress`, four authority gates and reviewer/full-regression/live mail+document acceptance remain open; not delivered. Coordination-frame compatibility slice: `ontology.py` and the historical experiment runner matched HEAD; the soft high-confidence mismatch remains non-hard and non-pruning. Test-only assertions now report the synthetic soft/hybrid false positive honestly and retain hard-gate rejection. Master canonical focused test `1/1` (`1.682s`) passed; module `15` tests (`18.428s`) has two remaining failures in 100-case/stress hybrid-delta expectations (`0.44` expected, `0.34` observed). No runtime/runner/scoring/threshold/fixture/report changes. Next bounded review: determine whether the two aggregate delta expectations are stale under the declared soft-signal contract; make no runner changes absent evidence. Master authority `valid=true`, `ready=false`, `errors=[]`, `CJK=true`, four gates blocked, `sha256:eefe5297cbfcf001385f9df5f17f63fa27bb56a1f3c082124aec5f087a8f6b2b`; this host-only check is supplemental and invalid solely for missing CJK dependencies. Feature 待測, step 4 in-progress; review, full regression, live mail/document acceptance and four gates remain open; no superiority/delivery claim. Correction/addendum: the preceding focused `1/1` (`1.682s`) and module `15` (`18.428s`, two failures) were Worker evidence, not Master evidence; the failed expectations (`0.44` vs `0.34`) are superseded by the current canonical module run. Master-provided runner summary confirms for both synthetic sets hybrid delta `0.34`, best arm `coordination_frame_v2_redacted`, hybrid exact/F1/false positives `0.8`/`0.94859`/`11` and `0.8`/`0.94859`/`1100`; soft exact/false positives `0.63`/`11` and `0.63`/`1100`, soft-vs-hard delta `0.41`, hard/v2 unchanged. Only the two test functions’ stale expectations/explicit false-positive checks changed. Canonical read-only network-none `python -m unittest test_coordination_frame_experiment`: `15` tests, `18.383s`, `OK`, zero skips. Master also reports independent ontology-contract test `1/1` (`0.000s`) and canonical in-memory syntax plus Ruff `--no-cache` pass. Master canonical authority is valid=true/ready=false/errors=[]/CJK=true, four gates blocked, `sha256:eefe5297cbfcf001385f9df5f17f63fa27bb56a1f3c082124aec5f087a8f6b2b`; separate Worker host-only authority check was invalid only for missing CJK dependencies and is not canonical. Feature 待測, step 4 in-progress; full regression, reviewer, non-live acceptance and four gates remain open; no completion/superiority claim. Archive-manifest integrity finding (Sep24): Master canonical fail-fast discovery was `431` tests/`103.258s`, `1` failure/`4` skips at `test_durable_archive_integrity.test_manifest_matches_every_lossless_snapshot`; this is not a passing full regression. The test matched HEAD before this slice. Before editing, read-only checks verified `docs/archive/2026-08-25/manifest.json` (`300` bytes/`12` lines, SHA-256 `80949f6e0290fa7e6890452c13778c5fab10f9e15cf9dd14cd257e62b72015ef`) and its sole snapshot `docs/archive/2026-08-25/handoff-log.md` (`20665` bytes/`300` lines, SHA-256 `476b5ca39860af6349b47f8eb633448d418c16752b7c9939e328a11a5a40ecf4`); both worktree files byte-match commit `04181cd`, and snapshot metadata matches manifest. Added only the explicit `SNAPSHOT_FILE_COUNTS["2026-08-25"] = 1`; no dated archive was modified and no dynamic inference added. One canonical network-none/read-only run of `test_durable_archive_integrity`: `4` tests/`0.018s`/`OK`, zero skips; Ruff `--no-cache` and in-memory `compile()` passed. Docker socket was initially denied in sandbox; the same bounded run succeeded after approved escalation. Master authority snapshot remains `valid=true/ready=false/errors=[]/CJK=true`, four gates blocked, `sha256:eefe5297cbfcf001385f9df5f17f63fa27bb56a1f3c082124aec5f087a8f6b2b`; not rerun here. Full regression is still not green/not rerun; feature 待測, step 4 in-progress, reviewer and live mail+independent-document acceptance remain open. Sep29 browser citation-boundary follow-up: the prior classify contract accepted arbitrary well-formed citation IDs when DOM labels matched. The runner now requires, only for `--synthetic-source-neutral`, an explicit safe expected binding from the fixture: source family plus answer and citation SHA-256 fingerprints; browser computes these locally and exposes only boolean verification/counts. Missing binding and a valid-looking arbitrary mail citation with unrelated answer both fail closed in the self-check. Existing synthetic mail and independent-document Chromium acceptance passed with `mail_source_binding_verified=true` and `document_source_binding_verified=true`; canonical two-test network-none/read-only run `2/2` in `5.828s` (`OK`). JS syntax, Ruff `--no-cache`, in-memory Python compile, and scoped diff-check passed. No provider/private source/live UAT, runtime, ingestion, service, DB, or index changes. Master authority remains valid but blocked with four gates; feature 待測, step 4 in-progress, reviewer/full regression/live mail+document acceptance open; no delivery claim. Issue #20 canonical onboarding follow-up (2026-09-29): stable AST serializer restored; focused completion_finalization + oauth_harness_execution passed 57/57. Onboarding fail-fast first failure remains changed=3065 vs manifest=713; canonical aggregate was 103 tests/6 failures. A bounded search of 56 reachable candidate commits and 26 unreachable commits found no matching 713-entry snapshot (the only unreachable manifest had 689 entries). The current 713-entry manifest is untracked and has no source-snapshot provenance. Do not adjust counts or hashes; next requires an authorized immutable snapshot or a fresh Issue #20 scope decision. Issue #20 remains open and unchecked. Latest Master-verified per-turn MCP deadline change evidence: focused tests `3/3`; full `tests.test_issue56_uat_web_e2e` passed `62` tests with `1` skip in `160.855 s`; in-memory compile, Ruff, and `git diff --check` passed. This remains provider-free evidence: live provider/private-source/deployment acceptance is blocked; feature remains 待測 and step 4 `in-progress`.
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
