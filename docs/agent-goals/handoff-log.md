# Agent Handoff Log
Lifecycle label: `active`.
## Retention Rule
Keep the latest bounded checkpoint and at most 300 lines. Full pre-edit files,
including all unique earlier failures/results and archive pointers, were saved
byte-for-byte before compaction in the [immutable checkpoint](../archive/2026-10-12/delivery-resolution-pre-span-repair/README.md)
and its SHA256 manifest. Existing archives were not edited. Historical entries
are evidence, not current dispatch or restart instructions.

## LAN8088 cutover and publication — 2026-10-13 UTC, scoped browser pass
- User-confirmed target8088: `formowl-uat-live-8088-20261013` serves unchanged verified r12 (`b2f4fa44…`), inventory252/drift0, same partial source `5e222fc…`.
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
- Live8089 now runs r12/new partial source; **this observed question's
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
- Current r12 code252/drift0, probe/live image and source target match; preparation
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

## Delivery-resolution repairs and verification — 2026-10-12 UTC
Evidence paths below are relative to `.formowl/delivery-resolution-20261012/`.
Only safe records, package metadata, synthetic verification summaries and
reviewer results were read; no private native source files were inspected.

### Storage, binder, materializer and diagnostic binding
- R4 O1/binder canonical **49/49**, zero errors/skips, **7.702s**, Ruff;
  `package/manifest-r4.json`, hash `8ec84475…`. O1's create-private-before-write
  and provisional contract freezing supersede the old r3/O1 pending statuses.
  Three scoped agreements are carried through the final r5 review; Archimedes'
  separate r4 materializer BLOCK remains historical and was closed only by r5.
- R5 materializer compatibility: **58/58**, zero failures/errors/skips,
  **58.198s**, Ruff; `package/verification-r5.json`, hash `48e7a112…`.
  Initial49 loader-name errors +9 materializer passes remain preserved.
  Archimedes/Hypatia/Lagrange AGREE for their exact scopes, excluding B binding
  and business/source/methodology acceptance. No global storage-layout revert.
- Subsequent finite sealed-export compatibility: ordinary Observations remain
  sharded; only the bounded sealed materializer explicitly exports flat records.
  Existing layouts, keyed/mixed reads, byte seals and no read-time writes remain.
  Worker red2:1 failure/1 error; green **20/20,116.233s**, Ruff/compile.
  `worker-a-materializer-evidence/flat-export-r1/safe-summary.json` preserves scope.
- B diagnostic-binding core **19/19,2.841s**, Ruff; Hypatia scoped AGREE in
  `reviews/hypatia-binding.json`. Trusted operator binding is not remote
  attestation; missing/forged bindings remain incomparable. Earlier combined
  citation failure and pre-B flat-consumer failure were not silently erased.

### Composer package omission and completed source preparation
- Fixed source-order 2048-parent r2 completed **17:10:00.575Z / EXIT0**, OOMfalse:
  **622,631 Observations / 7,211 runs** (run total per Master). Safe ledger reports
  6,575 incomplete runs and existing native-format/cell-limit warnings;
  `prefix-r2-completed-safe.json`. Not whole-corpus completeness or activation.
- Prep-r2 failed because its frozen package retained the old composer requiring
  nonempty repaired parents. Completed extraction was valid and reused, not
  re-extracted. `worker-a-composer-evidence/safe-summary.json`: exactly one
  reviewed composer function transplanted into NEW252-file package, existing
  helper ASTs unchanged; **29/29,0.113s**, Ruff/compile/helper precheck.
  Composer snapshot `4786884e…`; no binding relaxation or new source selection.
- Master reports corrected prep-r3 NEW source **EXIT0 at17:44:25Z**:
  **5,588,435 Observations / 1,100,143 references / 10,479,384 postings**.
  Pin `sha256:7c11bec0b264f1c9e2bdd41824cf4c4dc04beff5308b08b6d7836c0dc0e44256`
  is corroborated by `pipeline-breakpoint-redaction-safe.json`; **not activated**.
  Preparation success does not mean preserved field text or full-source coverage.

### R10 inventory and citation-fixture finding
- `package/manifest-r10.json`: exact **252 product /33 test files**;
  `sha256:89194b720fe3f8c015299495559256d7ac33155e973461dc08b726e152f176d8`.
  Rejected r8 packaging and unpublished r9 inventory assertion retained; only
  the NEW copy excluded the unmanifested test and `.orig` script. All252 declared
  product bytes unchanged. Archimedes/Lagrange scoped AGREE, not live acceptance.
- Combined canonical `package/focused-r10.log`: **82 tests,81 pass/1 failure,
  170.385s**. Answer paragraph was correct; the mock paired first evidence with
  the first independently sorted citation, which could identify a neighbor.
- Worker A test-only correction: deterministic red1 failure7.297s; keyed citation
  selection with adversarial nonpositional ordering retained; exact **1/1,7.221s**
  and preceding-case sequence **2/2,68.202s**, Ruff/compile. Exact answer/hash,
  native locator, HTTP/MCP, no-inline/PG exclusion and redaction assertions remain.
  All252 r10 product hashes unchanged. Evidence `worker-a-citation-fixture-evidence/`;
  test SHA `5f6597f7d11705ac28b18252a4c3b7e89b19144136494da1bbb7e042cdbd8d03`.
  Hypatia **AGREE/closed** (`reviews/hypatia-citation-fixture.json`); subsequent
  r11 focused integration passes below. This fixes a mock, not the separate
  real-source redaction defect; original r10 failure remains preserved.

### Proved native-evidence redaction breakpoint and r11 replay
- `pipeline-breakpoint-redaction-safe.json`: one admitted successful native PDF
  run, three paragraphs, all collapsed to `[redacted_mail_evidence]`; original
  identifier present before redaction, no target identifier/date lookup postings.
  This is evidence loss in extraction/public redaction, **not source absence**.
- B synthetic reproduction proved detector/token-consumer mismatch for bare
  slash, Unicode paths and Windows roots. Only generic path-span consumption is
  repaired; detector/final unsafe guard and other redaction rules unchanged.
  Attachment extractor changes **VERSION ONLY0.6.1→0.6.2** for persisted output.
  No question literals, aliases, parser features, permission or budget relaxation.
- B frozen evidence `worker-b-span-redaction-evidence/{summary.txt,freeze.json}`:
  original red4 tests/20 failing subcases0.396s; intermediate two permission-scope
  fixture assertion failures retained despite the first-green log name; final
  **26/26,0.601s**, zero failures/errors/skips, Ruff. Synthetic native PDF and
  independent UTF-8 preserve content/hash/lineage/permissions/locator/version;
  not final-answer citations or real-browser acceptance.
- Master `package/manifest-r11.json`: exact **252 code /34 tests**,
  `sha256:ac409901ce675871e9f9d3f4d2b20c6253dd3fc5a424120cca61007213a4faec`.
  Two product deltas (`public_safety.py` span consumer; attachment version) plus
  citation-fixture correction. `package/verification-r11.json` and focused log:
  canonical **108/108,170.274s,EXIT0**, zero failures/errors/skips; exact252+34
  inventory verified before AND after. This supersedes pending verification,
  not whole-suite/source acceptance. Hypatia/Archimedes/Lagrange all r11 scoped
  **AGREE (3/3)** in `reviews/*-r11.json`; Hypatia's earlier pending-count field
  predates the final108 result, not a failed run or acceptance of later r12.
- `operations/fixture-r11.exit.json`: **EXIT0**. Real-provider Chromium synthetic
  native-PDF and independent-document cue/native citation/chat/reload/reset pass.
  `operations/fixture-r11-content-check-safe-v2.json` verifies all six responses
  remain incomparable: deployment/code/build missing; both business turns use
  four attempts but retain only three. The earlier null-field extraction remains
  superseded diagnostic history, not positive comparability proof. That fixture
  did not establish actual-source/browser acceptance; later evidence is below.
- Master additionally verified the native-original column distinction by host
  rendering without publishing private values. Canonical dev renderer unavailable
  is a recorded tooling limitation, not a test skip or canonical rendering proof.
- Later `operations/span-batch-start-safe.json` supersedes only manifest-r11's
  earlier not-started marker: NEW batch started **17:58:03.259Z**, same fixed
  source-order parent_start0/count2048, all formats, no query/filename filters,
  version0.6.2/r11. At that start checkpoint source was unactivated/live unchanged;
  watcher queued, not completed/admitted. Old runs/ledgers/pins remain preserved.
- Master reports corrected r3 batch **EXIT0 at18:57:38Z**, **622,631 Observations /
  7,211 runs**, and prep-r4 **EXIT0 at19:18:55Z**. The validated source was reopened:
  `sha256:5e222fc040811b1cc7b5f66855db364c9416a7de136461ba94f07110cebf8569`.
  `operations/validated-source.json`: **1,100,143 references /407,401 helpers /
  10,671,080 postings**, zero independent-document helpers, completeness=false.
  Admission verified a successful native PDF run and three preserved indexed
  paragraph hits. Preparation's activation=false is its earlier checkpoint,
  not a later candidate/live rollout result or a guarantee of subsequent stability.

### Serving r12 — focused integration verified / scoped review 3 of 3
- R11's latest-three diagnostic truncation conflicts with complete-history
  comparability for valid four-to-six-attempt turns. B froze the constant-only
  repair derived from the existing request cap6; all other product AST unchanged.
  No execution budget/model/deadline/retry change; missing/truncated identity
  remains incomparable. `worker-b-attempt-retention-evidence/freeze.json`:
  canonical **19/19,0.818s**, zero failures/errors/skips, Ruff; four/six-attempt
  positives and missing-history negatives, not a live comparability claim.
- `package/manifest-r12.json`: exact252 code/34 tests, serving candidate
  `sha256:b2f4fa44a916e1dafe11192c4bac60adb4dc65512969f8b9686e73afa6553cf5`.
  `package/verification-r12.json` records final canonical focused r12
  **117/117,174.049s,EXIT0**, zero failures/errors/skips, exact252 code/34 tests
  verified pre/post and current inventory recheck. This supersedes the earlier
  running status only, not full-suite/source acceptance. All three scoped
  **AGREE**: Hypatia/Archimedes/Lagrange, `reviews/*-r12.json` and
  `operations/review-gate-r12.json`. Lagrange inspected hashes and complete,
  malformed/truncated-history tests; no concrete blocker in retention-only scope.
  This test/review packet alone did not establish broad-feature or live acceptance.
  After source preparation, `package/manifest-active.json` now selects r12 for
  serving; the completed source batch still records its actual r11/version0.6.2
  execution. No package/manifest edit is performed by this docs checkpoint.
- Initial freeze helper TypeError read nested baseline metadata as a digest;
  `package/freeze-r12-precheck-error.json` and empty unpublished tree preserved.
  No product/test bytes copied by that failure. Corrected freeze verified; earlier
  failure is tooling evidence, not a failed product/test run or source change.
- Earlier Master I/O sample advanced about5GB/min with no observed OOM/failure;
  that sample/PDF parser activity was progress only, superseded by the completed
  batch/preparation facts above, not proof of final live source stability.

### Candidate acceptance / observed live answer verified with unresolved first failure
- Candidate8096 was deployed full252 product files, drift0, r12/new source pin above;
  its proof is historical after the scoped removal recorded below.
  Actual Chromium journey EXIT0: ordinary MCP0; delivery **20.597s**, unrelated
  actual attachment **19.580s**, each MCP1/provider2; reload/reset/postreset MCP0.
  `operations/browser-candidate-diagnostics-safe.json`: all four responses
  comparable with trusted bindings, claim_scope=diagnostic_only. Both evidence
  turns remain partial; comparability does not establish corpus completeness.
- At **19:26:19Z**, `operations/browser-candidate-native-acceptance-safe.json`
  and `operations/rollout-gate.json` verify candidate original-source acceptance:
  two citations reopened/hash/run/parent checked, source crosswalk EXIT0.
  Master viewed candidate screenshot and native PDF page1. Field meaning is
  `purchase_order_requested_delivery`, not PO/approval dates, actual shipment
  or latest supplier schedule. Unrelated actual attachment exact paragraph/native
  input hash verified; this is **not independently registered document proof**.
  This supersedes only the earlier candidate semantics-not-yet-verified marker;
  later live proof and the first live reopen failure are separately recorded below.
- Deployment helper readonly-template chmod failure retained. Master corrected
  only the operator helper to use the existing private tmpfs-copy approach;
  no product or secret changes. Old r5 stopped/preserved for rollback.
- Live8089 deployed r12+`5e222fc…`, full252/drift0. Chromium LAN EXIT0 (~19:28Z);
  `operations/browser-live-diagnostics-safe.json`: all four comparable.
  Ordinary **3.112s/MCP0**; delivery **22.829s** and unrelated attachment
  **17.833s**, each MCP1/provider2/citation1. Reload preserves, reset empties,
  postreset MCP0. Master viewed the live answer: requested-delivery field for
  visible line items, honest partial coverage, no shipment/latest-revision claim.
- **First live citation reopen FAILED**:
  `ContractValidationError: ingestion revision completed job changed` at
  `python/formowl_mail/issue56_sealed_source.py:2010`,
  `open_ingestion_revision_job_authorities`. Preserved in
  `operations/live-citation-first-failure-safe.json`; the initial mismatch detail
  was not retained, source mutation is not established and cause remains unresolved.
- Once-only operator instrumentation retained the original job-hash result and
  compared independent `_sha2`/hashlib digests of the same serialized job bytes;
  original source guards/results were not overridden. All three jobs' original/
  expected/count checks and engines agreed
  (`operations/live-job-fingerprint-measured-safe.json`). Full original loader
  succeeded; `operations/live-citation-instrumented.exit` (content `0`)/log and
  `operations/browser-live-native-acceptance-safe.json` at19:33:20Z record two LIVE
  citations reopened/hash/run/parent checked. Master verified source/date meaning
  and unrelated attachment exact paragraph/native input hash.
- `reviews/archimedes-live-answer.json`: **AGREE only for the bounded observed
  live source-correct answer**, requested delivery on native page1/visible items1–4.
  This successful real LAN answer is supported; no blanket current date-KPI UNMET.
  The first failed reopen is not erased or diagnosed by the later pass: it still
  blocks stability/reproducibility acceptance. No corruption, root-fix, full-UAT,
  source-complete, methodology or docs acceptance claim; partial coverage explicit.
- Cleanup completed **19:35:25Z**: `operations/scoped-cleanup-safe.json` and
  `operations/final-runtime-safe.json` record removal ONLY of candidate8096 and
  two current Chromium test containers, logs retained/no volumes deleted.
  Live8089 remains r12; old r5/provider rollback, background baseline builder and
  source-helper containers remain. Candidate proof is retained, not a running service.

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
