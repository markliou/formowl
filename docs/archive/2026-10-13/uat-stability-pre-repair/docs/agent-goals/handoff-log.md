# Agent Handoff Log
Lifecycle label: `active`.
## Retention Rule
Keep the latest bounded checkpoint and at most 300 lines. Full pre-edit files,
including all unique earlier failures/results and archive pointers, were saved
byte-for-byte before compaction in the [immutable checkpoint](../archive/2026-10-12/delivery-resolution-pre-span-repair/README.md)
and its SHA256 manifest. Existing archives were not edited. Historical entries
are evidence, not current dispatch or restart instructions.

## Opt-in private UAT logging — 2026-10-13 UTC, diagnostic-only / 待測
- User assigned two clean code owners and focused tests, then these five docs
  only: SPEC/README/board/KG goal/handoff. No descendants; requested sol/high,
  actual worker metadata unverified. Code edits stopped unless reviewer finding.
- [Frozen package-r1](../../.formowl/uat-observability-20261013/package-r1.json):
  code4544e59ad637266fee705d97aa1195998966d6a7d7fe33f0b56c636e11f34ab7,
  copies r12 plus runtime/orchestrator and two tests only; unrelated dirty
  `dense_embedding.py`/`issue56_uat_web.py` drift remains untouched/excluded.
- Paired `--behavior-log`/`--record-raw-uat-interactions`, persistent restricted
  operator mount, regular0600 JSONL. Schema2 request_id is unique per turn,
  including identical prompt/session; safe provider/turn/MCP traces correlate.
  Private file holds prompt/query and service-visible status/answer/clarification/
  citations, validated contract/support, actual hash citation IDs at raw/presented/
  final stages and existing source-scan stop metadata. Non-hash IDs are hashed;
  pools cap100 with truncation flag, stage budget3 MCP+2 validations. Missing
  metadata is not invented. Runtime exceptions retain failure digest, not a
  reconstructed later HTTP envelope. Unsafe records fail safely; no raw paths,
  secrets/headers/cookies or public raw payload. Log failure preserves business
  result/original exception and emits safe category+ID. No query-budget/model change.
- Worker final canonical9 new logging+6 terminal cases PASS0.048s, Ruff/diff PASS;
  first new-suite run7 pass/1 error was a test selecting nonexistent `calls` key,
  corrected test only. Worker tests used mounted working tree, not frozen r1.
  Exact final command (output in tool exec session35352, no standalone log file):
  ```sh
  docker run --rm -v /home/markliou/formowl:/workspace -w /workspace -e PYTHONPATH=/workspace/tests:/workspace/python formowl-dev:local python -m unittest test_issue56_private_behavior_logging test_issue56_uat_web_e2e.Issue56UatTerminalTraceTests -v
  ```
- Earlier worker canonical15/15,98.115s,EXIT0 included opt-in recorder fixture;
  loaded before final provider correlation. Output is tool exec session2344 only,
  no standalone log; exact command adds this case to the preceding command:
  `test_issue56_uat_web_e2e.Issue56UatWebE2ETests.test_temporary_lan_uses_real_sealed_source_normal_mcp_and_opt_in_log`.
  Working-tree script/dense drift differs from frozen r12 runner; that pass is
  not a final-frozen integration claim or explanation of a later fixture failure.
- Master's [focused-r1b.log](../../.formowl/uat-observability-20261013/focused-r1b.log)
  canonical36/36,2.192s,EXIT0 verifies frozen bytes. Initial `focused-r1.log`/
  EXIT125 was Docker missing mountpoint/zero tests, not product failure; corrected
  `/checks` mount changed no package bytes. Frozen integration2: cookie PASS;
  opt-in fixture FAIL before service at `_prepare_package` -> candidate builder ->
  `persisted_private` validation, `private_artifact_fingerprint_invalid`.
  [integration-r1.log](../../.formowl/uat-observability-20261013/integration-r1.log)/
  EXIT1,20.501s. Root of runner/fixture difference unresolved; no source/index
  edit or broad source-anomaly chase. Final integration is not all green.
- [Candidate8096 browser/log proof](../../.formowl/uat-observability-20261013/candidate-browser-log-safe.json):
  ChromiumEXIT0/screenshots inspected; chat twice MCP0, same prompt/distinct IDs;
  unrelated LQP lookup MCP1/provider2/citations2, partial. Private raw9/presented7/
  final2 IDs, persisted result exactly HTTP payload/DOM answer, file0600/dir0700.
  This proves the observed capture, not correctness of all COO answers.
- All3 scoped reviewers AGREE: Chandrasekhar engineering, Gibbs safety, Harvey
  evidence/methodology, `reviews/{engineering,safety,methodology}.json`.
  [Rollout gate](../../.formowl/uat-observability-20261013/rollout-gate.json) permits only
  private diagnostic logging activation, acknowledging the existing integration
  ERROR. Frozen Ruff+compile4 PASS in `lint-compile-r1.log`; owner/test hashes match.
- [Live readiness09:24:26Z](../../.formowl/uat-observability-20261013/live-ready-safe.json):
  current8088 `formowl-uat-observability-live-20261013`, code4544e59a…/252files/drift0,
  source/image/gpt-5.5 high/budgets unchanged. Paired flags enabled, persistent
  file0600/dir0700. Old `formowl-uat-live-8088-20261013` stopped/preserved rollback.
- [Live Chromium/capture](../../.formowl/uat-observability-20261013/live-browser-log-safe.json):
  EXIT0/screenshots inspected; ordinary11195ms MCP0/provider1; unrelated lookup
  23844ms MCP1/provider2/citations2/partial, both comparable/record=HTTP=DOM.
  Private raw9/presented7/final2 IDs. [Correlation](../../.formowl/uat-observability-20261013/live-correlation-safe.json)
  verifies matching provider/turn/MCP IDs, zero log failures, two private-log
  URL404 checks. Repeated-prompt distinct IDs remain candidate-only evidence.
- [Final cleanup09:28:05Z](../../.formowl/uat-observability-20261013/final-operational-safe.json):
  own candidate removed with persistent logs retained, live healthy/restart0/
  OOMfalse, old8088 rollback preserved, unrelated containers untouched.
  Underlying failing-MPN COO inconsistency remains unfixed; no new original-MPN
  query executed. User will retry; no further work/code without a new user request.
- Underlying COO-answer inconsistency remains unresolved. [Canonical authority](../../.formowl/uat-observability-20261013/authority-check.json)
  valid=true/ready=false/errors=[]/EXIT0, four gates blocked. Host startup check
  missing tokenizer dependencies/EXIT2 is supplemental only. No checkbox,
  standard, readiness, method completion or whole-regression-green promotion.
- Five complete pre-edit docs and SHA256 manifest: [immutable checkpoint](../archive/2026-10-13/uat-observability-checkpoint/SNAPSHOT.md).

## Prior r12 LAN8088 publication — 2026-10-13 UTC, historical scoped pass
- User-confirmed target8088: `formowl-uat-live-8088-20261013` served unchanged verified r12 (`b2f4fa44…`), inventory252/drift0, same partial source `5e222fc…`.
  [Readiness](../../.formowl/publication-20261013/uat-8088/ready-safe.json) and [final cutover](../../.formowl/publication-20261013/uat-8088/final-safe.json): old8088/8089 stopped/preserved, primary8088 health OK before/after stopping8089.
- [Cleanup](../../.formowl/publication-20261013/cleanup/final-safe.json): six test containers removed; logs/private artifacts retained, unrelated containers untouched; no image/volume/data changes.
- Publication selects tested r12 bytes in Git index, preserving later two-file working-tree changes; commit identity is in Git history.
  Selected75 paths/diff74: frozen `python/formowl_core/dense_embedding.py` already equals HEAD; later bytes in it and `scripts/issue56_uat_web.py` remain preserved/audit matches, unrelated Issue20 unstaged. Deployed r12 identity does not describe all working-tree bytes.
- GitLab push NOT done: outside-sandbox glab auth valid; configured bot belongs to another project, no FormOwl remote; awaiting correct repository URL.
- [8088 Chromium](../../.formowl/publication-20261013/uat-8088/browser/acceptance-safe.json): EXIT0/screenshots reviewed; ordinary4505ms MCP0/provider1, delivery20774ms MCP1/provider2/citation1, COO31682ms MCP1/provider2/citations2; all comparable with trusted new deployment binding.
  Delivery/COO remain partial; answers/citations match prior source-verified evidence under identical code/source, not a fresh native-source reopen. Requested delivery is not shipment/latest supplier commitment; COO same-row mail evidence is not a formal certificate.
- [Canonical authority](../../.formowl/publication-20261013/authority-check.json): valid=true/ready=false/errors=[], four blocks. Cutover scope only; no release/feature/methodology completion or checkbox promotion; whole regression non-green, stability investigation parked/OPEN.
- This bounded assignment edits only board, KG goal and handoff; no code/git/Docker/provider edits, no archive churn; actual worker configuration unverified.

## Current worker policy and claim boundary
- Requested `gpt-6.1-sol`/`high`; Worker A actual configuration **unverified**.
  No descendants. Missing metadata does not block authorized bounded work.
- Current explicit assignments supersede dated closure/stop statements. This
  2026-10-12 checkpoint wrote the board, KG goal, this handoff and the named
  SPEC/extraction/README/reviewer-gate contract/status sections only. Seven full
  pre-edit docs are [archived](../archive/2026-10-12/delivery-resolution-r12-staged-checkpoint/SNAPSHOT.md)
  with hashes; no code/tests/probes/provider/source/container changes.
- At the prior checkpoint live8089 ran r12/new partial source; **this observed question's
  source-verified answer was obtained in the real LAN webpage**, with Archimedes
  scoped AGREE. First citation reopen failed completed-job validation; a later
  once-only instrumented pass verified both citations with original guards/results
  unchanged. Cause unresolved: stability/reproducibility remains blocked, not the
  demonstrated answer. No full-UAT, user-only blocker, phase-final or blanket stop.
- Canonical `.formowl/delivery-resolution-20261012/authority-resume4.json`:
  valid=true, ready=false, errors=[], EXIT0; execution fingerprint
  `sha256:26ceff23f1c209281b9c6a6e3e92dcad9fcfc30e2ac13cc7027abd474092a873`.
  Prior authority records remain preserved, not rewritten or re-probed here.
  Source completeness, accepted execution-fingerprint binding, same-pipeline
  real-source ablation and independent final-answer acceptance remain blocked.
  Host dependency probe exit2 is supplemental, not canonical readiness evidence.
  No fresh probe in this docs-only checkpoint; feature 待測, step4 in-progress.

## Completed-job anomaly investigation — 2026-10-13 UTC, parked / OPEN/待查
- User explicitly authorized the bounded investigation and parking if unprovable;
  no descendants, requested sol/high, actual metadata **unverified**. This later
  sequential assignment updates only the KG goal, handoff and board checkpoint;
  no further code/Docker/provider/source operations or archive edits.
- Evidence under `operations/reopen-investigation-20261013/`:
  `investigation-safe.json`, `same-call-safe.json`, `runtime-safe.json`, `probe.exit`
  and the read-only-reviewed `probe.py`. One full original loader read at
  **03:41:24–03:41:47Z**, **23.116s/EXIT0**: all three same-call expected/actual job
  fingerprints and observation counts match; original/hashlib/independent engines
  hash identical input bytes. Both original browser citations resolve.
- Helper capture retains original return values and rethrows failures, no retry;
  path metadata is compared before/after get and through authority construction.
  Metadata stable **for this call**. All observed job mtimes/ctimes predate the
  historical failure; this does not prove historical immutability or rule out
  transient path-target swaps. No private source payloads or crosswalk read here.
- That investigation matched r12 code252/drift0, probe/live image and source target; preparation
  hash matches unchanged pin `5e222fc…`. First host runtime-metadata `PermissionError`
  remains in `runtime-probe-first-error-safe.json`; corrected read-only container
  method passed without chmod, permission or source changes. It was not a source
  validation failure. First failed process runtime identity remains **unbound**;
  job index, mismatch branch and expected/actual values were not retained.
- Static r12 inspection found no local serialization nondeterminism. Completed-job
  replacement/path-target race and different ordering/code/runtime binding remain
  **unproved hypotheses**, not incident causes; one exception merges hash/count
  mismatches. Current passes do not explain or erase the historical failure.
- **Park pending recurrence or contemporaneous first-failure evidence**; root cause
  unresolved, stability/reproducibility acceptance **OPEN/待查**. If mismatch recurs,
  capture same-call job index, expected/actual fingerprints and counts, frozen loaded
  code/image/source identity and read-bound file identity/stability **before any
  retry**. Never repin, weaken guards or repeatedly reload to chase a pass.
- Operator helper only; no product diagnostics, patch/deploy/rebuild/retry changes.
  Historical observed requested-date/native citation proof and scoped review remain
  supported. This is partial diagnostic status, not full-UAT/release/completion
  authority; **no acceptance or release gate sought**, no checkbox promotion.
- Fresh canonical check recorded in `investigation-safe.json`: valid=true,
  ready=false, errors=[], EXIT0; execution fingerprint
  `sha256:1123ffb98ddbb0cd1ed57ddd10051af2f6978423bd496259654bd47737ed2df4`.
  Four methodology gates remain blocked; host missing dependencies supplemental.
  No probe rerun in this docs update; feature 待測, step4 in-progress.

## Archived delivery-resolution repairs and verification — 2026-10-12 UTC
The [complete pre-edit handoff](../archive/2026-10-13/uat-observability-checkpoint/docs/agent-goals/handoff-log.md)
and manifest preserve every original command/result, timing, failure, artifact,
source pin, reviewer decision and earlier archive link byte-for-byte. That dated
history is not current instructions. Its evidence includes r4 storage/binder49,
r5 materializer58, r10 inventory252+33 and81/82 with one keyed-fixture failure,
r11 span-preservation/extractor0.6.2,108/108, r12 retention117/117 and scoped3/3.
Successful fixed2048 extraction/preparation and partial source5e222fc… do not
prove whole-source coverage. The observed native requested-delivery answer and
unrelated attachment were verified; the first completed-job reopen failure is
still unresolved. Old private-source/rollback/cleanup evidence remains archived.
No old failed attempt, non-green result or acceptance boundary was erased.

## Preserved history and next action
- Lossless snapshots retain r1 paragraph-budget60/60 and r2 field-guidance25/25,
  initial helper errors, r1/r3 browser failures and r2 fixture-only pass; none
  become final-code/business acceptance. R3 storage31/31 followed tooling errors,
  then O1 and binder findings; later proofs supersede only those exact scopes.
- Initial128 admission missed original parents; first2048 failed ext4 directory
  index ENOSPC, not disk capacity. Separate remainder metadata_unreadable cause
  remains unproved. Failed jobs/ledgers/original pins and source-integrity results
  remain preserved; no migration/deletion/repin or current-corruption inference.
- Earlier partial live/source, SSE/provider failures, cleanup/rollback records,
  consumed diagnostic boundaries and September/October archive pointers are in
  the full snapshots. Historical stop statements are not current blanket stops.
- User-authorized anomaly investigation is parked pending recurrence as above;
  stability/reproducibility acceptance stays OPEN/待查. This observed live answer has source/native proof and scoped review,
  not broad acceptance. No blanket stop or user-only blocker. Diagnostic-producer/
  storage-export/span-redaction contracts match r11 extraction and r12 serving;
  not remote attestation, formal readiness or standard promotion.
  Missing/truncated identity stays incomparable. Full-source, independent-document,
  holdout, transfer, provider-stability and methodology acceptance remain open;
  no checkbox or plan completion changes. Worker A stops only this bounded docs
  write turn after document checks; Master's authorized work continues.
