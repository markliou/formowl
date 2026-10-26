# Agent Handoff Log
Lifecycle label: `active`.

## 2026-10-26 AI bounded document full read / 待審查、待測
Added one mode to the existing sealed-reference reader, requiring a complete
job-bound document inventory and both 200 paragraphs / 60,000 NFC code points.
Every item retains original hash/revision/lineage/permission/native-locator
validation; ordered batches are all presented before an answer opportunity.
Ordinary and mail paths retain existing limits and split behavior. New focused
real sealed-job test first failed on unchanged implementation (zero citations),
then the final canonical 12-case matrix passed (59.028s), including lexical-index,
NFC boundary, runtime binding and visible finalization disclosure. Requested 12
modules: 316 tests/319.067s, 34 failures with names exactly equal to the supplied
abf0c968 baseline; no new failure names. No provider/deploy/commit; parent owns exact recorded-request replay
and review. Canonical dev-container methodology --check is valid=true, ready=false, errors=[]
and blocked; the host missing-CJK probe is supplemental only. No readiness claim. Worker requested gpt-6.1-sol/high; actual model and
effort are unverified. Report: `/tmp/herdr-bus/codex-to-claude-workorder-20261026ai.md`.

## 2026-10-26 AC1′ bounded split refinement / 待審查、待測
One server-offered next proposal may strictly partition frozen terms after eligible
zero-result recovery; invalid next proposal or second zero stops, no second split.
Existing protected/retained/reviewed identities stay intact; unknown-name and
same-item AND relevance limits remain explicit. Canonical focused10 PASS/0.289s;
final configured journal-loop recheck PASS/0.145s; authority valid/blocked. Separate worker implemented180s browser waits/diagnostics.
No provider/deploy/commit; AC2 pending review/commit. Worker requested sol/high,
actual unverified. Report: `/tmp/herdr-bus/codex-to-claude-workorder-20261026ac.md`.

## 2026-10-26 AB2 bounded finalization diagnostics / 待審查、待測
Allowlisted safe reason codes survive existing diagnostic projection; typed parser
mode now matches the no-evidence schema, retaining citation_rejected and safe stop.
Existing one-shot repair gains fixed rule text/current field-count bounds without
draft replay or changed validation/attempt limits. Canonical focused 9 PASS/0.352s;
authority --check EXIT0 valid=true/ready=false/blocked. No provider/deploy/commit.
Requested worker gpt-6.1-sol/high, actual unverified. Evidence and initial fixture
failures: `/tmp/herdr-bus/codex-to-claude-workorder-20261026ab.md`; live follow-up pending.

## 2026-10-26 UAT model policy / Z preparation / 待測
The 2026-10-26 user override requests UAT `gpt-5.6-luna`/`reasoning_effort=xhigh`,
superseding the 2026-10-25 low request (which superseded 2026-10-15 gpt-6-luna/high).
Launcher/adapter defaults and current policy are synchronized; xhigh runtime/provider
support, observed model/effort binding and browser acceptance remain pending. No rollout
or methodology/release acceptance. Worker request remains gpt-6.1-sol/high; actual unverified.
X instruction changes were rejected and parked; baseline instructions remain. The 20
planner-only samples and provider acceptance checks are pending; no deployment before Claude review.

## Current checkpoint — 2026-10-25 UTC / scoped local semantic annotation + reconciliation + UAT relation intake / 待測
Authority remains valid-but-blocked; nothing here is UAT acceptance, completeness or methodology evidence.
User decisions (2026-10-25): annotation model Gemma 4 26B-A4B (local only); scope first, full later;
quotes differing ONLY in whitespace map to the one unique source span (other repeats/missing quotes
fail); cross-unit grouping option (b) across threads by exact target+property; relations reviewed by a
fixed auto-approval policy; a second host (Titan RTX + 3090 Ti, Ollama 0.40.2 per GPU on 127.0.0.1,
reached through an SSH tunnel on :11446/:11447) joins the local :11435 lane. Commits (local, not
pushed): a5d8a35/18e6d89/e40f38c local reader for the unchanged `read_and_store_source_unit` contract
(flat model records; adapter only assigns ids/identity refs/time-property copies, locates evidence
exactly, clears invented labels/subjects, fills the read inventory for an untruncated complete read,
gives retry feedback); d562a1b/503993c `scripts/issue56_semantic_annotation.py` scope/run/retry/report;
82df241 policy review tool + catalog fix (bindings omit a null type_surface); e3ec2c4 attachment 0.7.2
(date-time serials interpreted, rows carry `cell_date_values_iso`; applies on next re-extraction);
aca8a21/215dc71 cross-unit reconciliation (closed relation set; updates/supersedes need an exact update
quote from the later message and must follow message time; strict per group); ed75695 UAT reads
reviewed relations (optional relation receipt pages, additive selection over updates/supersedes/
contradicts, relations in evidence context/catalog; review tool approves only sources the serving
lookup resolves). Scope: Date-header month 2026-01, both PSTs plus attachments by lineage — 1,485
messages, 408 attachment assets, 9,543 units (`/Cache/formowl-annotation-2026-01/ops`, units
3a1a5bab…; code snapshot 18e6d89). Run `semrun_2026_01_a` in progress (~440 units/h, ~62% annotated,
gaps: repeated/inexact quotes, names outside quotes, truncation; retry pass pending). Sealed-loader
diagnostics: 1,612 reviewed atoms + 205 relations bind to revision-r2; 12 atoms citing
`container_member` were skipped because revision-r2's source lookup has no reference for them. Trial
reconciliation (93 groups): 196 same_fact, 9 refines, no updates/contradicts in that sample, a few
same_fact pairs over different values. Separately the official indexed finish for revision-r2 runs
into a dedicated pgvector container (`formowl-r2-projection-postgres`, internal network only):
references persisted; the attachment-parent phase repeats lookups for parentless assets. Not
deployed; 8088 untouched. Open: retry + reconciliation on the full scope, webpage questions on 8088
(SPEC §15.6), the two pre-existing `test_issue56_uat_web_e2e` failures, `container_member` lookup
coverage, quoted-history dedup before any full-corpus run.

## Current checkpoint — 2026-10-24/25 UTC / single-run PST re-extraction + local annotation model bake-off / 待測
Authority remains valid-but-blocked; nothing here is UAT, completeness or methodology evidence.
Code: 43ea2fe (ZIP/gzip/tar, legacy .doc/.ppt, attached .msg/.eml), 9822d23 (Codex review:
gzip and compressed-RTF inside the expansion budget), 221ce71 (PST keeps attachment bytes
only when children are materialized; fixed an OOM introduced by 789dd38), 0d1bd12
(AttachmentDocumentExtractor 0.7.1: lenient PDF re-read, fallback to the last readable
revision when an appended incremental update is broken, one bad page no longer drops the file).
Re-extraction store `/Cache/formowl-reextract-20261024` (one complete run per PST, export
copied to NVMe and three-way hash verified): small PST 342,461 obs; big PST mail-only
5,790,047 obs; whole-export sidecar backfill 5,907,869 obs (77 non-partial child failures,
879 cell-limit). The user chose to keep working on this POC host despite bad non-ECC RAM:
one directory entry was written as `.Json` (single bit flip); its content was recovered by
inode and rewritten; all 6,132,508 root-job observations re-verified by recomputing their
content-derived ids (0 mismatches). Revision composition hit the one-child-failure-authority
rule (small PST had 2 failed children: one PDF with a broken appended update); 0d1bd12 removes
that failure; the small PST was re-extracted into its own store (`store-small-r2`; a re-run cannot
re-register child assets) and the existing backfill delta was reused unchanged (same sidecar parent
binding 539a82…, same ledger 1a426d…; it keeps parser 0.7.0, the small PST uses 0.7.1).
`revision-r2`: 5 jobs, 12,040,491 observations, revision fd2b34be…, lookup sqlite 63aef6d2…
(16.7 GB; 2,721,690 references, 1,613,538 helpers, 43,605,424 postings). Both seals re-hashed
from disk after page-cache eviction; the sealed loader opens it in 84 s and four diagnostic
source-start lookups (mail, attachment table, project document) returned cited evidence.
Not deployed; 8088 still runs v22. Dense/strong-RAG projection not built.
Annotation model bake-off (local only, 2x GTX 1080 Ti; host Ollama 0.21.2 cannot load
gemma4, so `formowl-ollama-new` = ollama/ollama:0.40.2 on :11435): 38 seeded units (whole
messages, attachment documents, attachment tables) plus an independent 38-unit holdout.
Gemma 4 26B-A4B with prompt v3 (records before the business flag, explicit proposal/request/
commitment/result roles, dedup + quote-grounding filter): 38/38 valid JSON, 37/38 units
annotated, 355 records, 100% quotes grounded on the holdout; Nemotron 3.5 Lightning 30B-A3B
left most attachments empty. Same prompt v3, both samples (valid JSON / annotated units /
records / s per unit): Qwen3.8-27B 37+37/34+34/569+447/145+118 (richest, ~5x slower);
Qwen3.6-35B-A3B 37+37/34+35/501+517/45+41 (often paraphrases values: 583/858 values verbatim
vs Gemma 619/655); Gemma-3-TAIDE-12B 24+27/21+23/148+203/106+93; Breeze 2 8B Q8
23+28/17+21/98+124/91+73 (TAIDE/Breeze: 30-40% invalid JSON and many false "not business").
Qwen was run only as a user-requested comparison (user prefers non-Chinese models). No model
chosen yet. Seen in tables: date cells reach the model as Excel serials (45212), so the table
text projection should carry display values too. Quoted-text measurement (small PST): new
text is 33.1% of mail body chars. Dense e5-small is CPU-only by profile: 12.8 passages/s at
~1,600 chars, 44.8/s at ~230 chars (6 threads) → about 10-35 h for 1.61M helpers; not started.
Private files: session scratchpad `bakeoff/`. Next (user decisions): annotation model, scoped
vs full annotation, deploy revision-r2, build dense, re-run backfill with parser 0.7.1.

## Current checkpoint — 2026-10-23 UTC / reviewed header validation plan / 待實作
Claude took over from the interrupted Codex session at user request. 8088 v17
failed only because host-side runs left `__pycache__` in the candidate tree;
caches removed, v18 restored, v19 deployed with turn cap 300 s and provider
request cap 240 s (provider latency is queue-dominated; a native-Codex-shaped
request was not faster in a non-private benchmark). Exact routing never fires
because 9417 of 9525 exact-cells columns are `candidate_only`; SPEC §7.5 now
defines reviewed header validation. Phased plan and progress:
`docs/reviewed-header-validation-plan.md`. Authority remains blocked.
Phase 1 (loader read path, default-off) landed in the candidate tree with 4/4
focused dev-container tests; 8088 now runs v20 without a reviewed-header file.
Phase 2 structural proposer written and unit-tested (4/4); full offline run over
all eight bound jobs started 2026-10-23 (switched to the exact-cells index after
the sequential pass proved disk-bound). Phases 3 (policy + sealed receipt, binder
now requires it) and 4 (fail-closed LLM proposer, synthetic live smoke only) are
coded and tested. Next: finish the structural run, regenerate pass 4, then
phase 5; real LLM batches need explicit user authorization.
Local semantic-reader probe (user asked for a non-Chinese local model): community
GGUF `mradermacher/Llama-Breeze2-8B-Instruct-text-only` Q4_K_M via host Ollama on one
GTX 1080 Ti (~50 tok/s, ~6 GB). On 20 seeded random `email_body_segment`s it gave
valid JSON 19/20 and grounded entities 24/28, but zero usable claims (4 empty
placeholders, 0/4 verbatim quotes). 9/20 segments were undecoded base64/RTF or
`redacted_mail_body_segment`, an ingestion decoding gap that blocks any semantic
reading. Private eval files: `.formowl/ontology-uat-20261019/private/breeze-eval/`.
Decoding root cause: readpst writes an mbox `From `/`>From ` line before every
attached `message/rfc822` message, so the stdlib parser sees no headers and the
whole embedded message (headers, boundaries, base64 attachments, RTF) became one
`text/plain` body. Every embedded message is affected: 4/4 in `source-export-2`
(2,699 messages, 3.4 MB) and 346/346 in `source-export-pending-j1-20261007`
(28,513 messages, 600 MB). Fix (uncommitted): `_parse_mail_bytes` in
`python/formowl_ingestion/extractors/mail/pst.py` re-parses only that shape;
`tests/test_pst_embedded_mbox_from.py` 3/3; existing `*pst*` suite unchanged
(same 1 failure + 4 errors before and after). Existing revisions still hold the
bad segments until a new ingestion revision is extracted.
Attachment coverage audit of those two exports (31,212 messages): embedded
messages hold 1,618 attachments (400 MB; 116 PDF, 50 xls/xlsx, 274 RTF bodies)
that were never extracted before the fix; they still need embedded-message
lineage (own sender/date/subject) before re-ingestion. Unsupported formats today:
RTF bodies (352 top-level + 274 embedded), images without OCR (~66k png/jpg/gif
top-level), archives (208 zip, 51 rar, 40 7z), OLE `.doc` (80), scanned PDFs.
Full audit (both exports): 66,837 top-level + 1,126 embedded images but only
17,850 unique; 5,961 PDFs of which 718 have no font object (likely scanned);
300+7 archives (862 MB); 56+6 nested .msg/.eml; 83+1 legacy Office.
Re-ingestion facts (2026-10-23): only two PST assets exist. The large one
(21.15 GB, `asset_c312…`) was fully extracted twice — job 1 (2026-10-06,
segment-capped, 82,232 body segments) and job 3 (2026-10-15 "fullbody",
uncapped, 1,312,616 segments) — and the current revision includes both, so all
28,513 of its messages and 200,627 headers are duplicated (59,724 =
2,698 + 2 x 28,513). A new revision must keep one uncapped extraction per PST.
Measured costs: large-PST extraction 2.1 h on the NVMe replica, attachment
backfill 0.75 h; existing readpst exports can be reused. Dense model is the
frozen `intfloat/multilingual-e5-small` (384-d, CPU-only torch in the image):
~26 passages/s on 12 CPU threads; the previous strong-RAG cache held 135,372
vectors (~1.5 h at that rate), so CPU is sufficient. `/Cache` NVMe has ~372 GB
free and should host the new revision.
Deployed-tree merge (2026-10-24, branch `merge/deployed-candidate-r39`, local
only): 7c9da6f snapshots root work, 1c43002 snapshots the exact 8088 v20 tree on
its closest ancestor cc8919f, 08b46db merges it (all five conflicts resolve to the
deployed side), 45339fe and 2c26f52 repair five deployed-runtime regressions
(mail-selector catalog dropped the graph tool; preferred table engine starved
later families; verbatim snippets via `span_label`; non-mapping annotation catalog
500; absent explicit parent job no longer fails the query) and align tests with
intended deployed behavior. Clean-worktree focused suites vs the pre-merge root:
0 new failures, 2 fixed, 57 pre-existing (issue56: 955 run, 45 failures, 32
errors). A read-only review request (items A1-A5, B1-B9, C1-C5) was sent to
Codex; its answer goes to `/tmp/herdr-bus/claude-wH-p1-review.json`.
Codex review (2026-10-24): agrees A1-A5 are bugs and B1-B9 are intended; C1/C3
modified (one complete run per PST with explicit dedupe/lineage; source inventory,
dedupe and completeness reconciliation before any rebuild; OCR keeps native
image/page citations; index speed is not readiness), C2/C4/C5 agreed with conditions.
Done since: 8088 deployed from git exports (v21 at 9280444, then v22 at 4081bcb with
`--reviewed-headers`, manifest source_binding_fingerprint d60bee…); RTF body support
(0209b3d, 345/352 real bodies readable); embedded-message lineage (789dd38);
reviewed headers: 360,077 approvals (327,842 structural + 32,235 LLM from 706
label groups; user directly authorized sending ambiguous labels/samples to the
provider), receipt in `.formowl/ontology-uat-20261019/private/reviewed-header-review/`.
HARDWARE BLOCKER (2026-10-24): host reads are silently non-deterministic. Hashing
the 24 GB `source-lookup.sqlite` twice gave two different SHA-256 values (only the
first matched); a job record parsed wrong from page cache (one flipped bit,
0x32->0x12) while an O_DIRECT read of the same bytes was correct. No EDAC/MCE
reporting (non-ECC). Seal checks catch it, but re-ingestion/rebuild must wait for
memory/disk diagnostics (memtest86+, SMART), otherwise corrupted reads can be sealed
into new artifacts. v22 is up and healthy.

## Current UAT checkpoint — 2026-10-22/23 UTC / field-aware source shortlist repair / 待測
User authorized private-source use and live UAT acceptance. Root cause for the COO miss was a bounded lexical shortlist: the validated料號 token had 21 mail postings, the known row containing `COO=JAPAN` was present at position 11, and single-token identity lookups skipped optional requested-field reranking before the source deadline. This was retrieval ordering, not missing attachment data or an authorization failure.

The candidate source reader now performs bounded optional-field reranking even for a single identity token; the identifier remains the required matcher and every selected Observation still crosses the existing hash, permission, lineage and source checks. v16 is running on 8088 with health `status=ok/query_service_connected=true` and manifest `sha256:d2f20103057dda33ce9eaad7b18659f5e4048595ea9a20df1617104c36dd85c0`.

Live webpage checks (HTTP 200) passed for the three requested prompts: PO470002002 / 20.QCS64G901 returned CRD `2026-03-04` and ETD `2026-07-13`; 470002138 returned delivery date `2026-05-14` with page-coverage disclosure; 03.80503G301 returned COO/origin `JAPAN` with citation `sha256:822699…`. All are finite `partial` answers because source coverage/field support remains incomplete; this is not methodology readiness, release acceptance or a whole-suite claim. Focused dev-container tests: 18/18 pass. Authority `--check` remains blocked (`methodology_ready=false`, CJK host dependency error and four gates open).

## Current UAT checkpoint — 2026-10-22 07:41 UTC / bounded finalization-budget repair / 待測
The relayed 8088 diagnosis identified the dominant failure as provider latency plus a late second finalization call: the source MCP result was citeable but the 120-second turn budget expired while the answer provider was still streaming. The bounded repair adds a 45-second finalization reserve. When an evidence result is governed and citeable, has `partial` or `incomplete` status, and the reserve is exhausted, the orchestrator returns the preserved source evidence with an explicit incomplete-coverage note; it does not issue a second provider request. Graph and mail evidence tools use the same rule. The requested model and reasoning setting are unchanged.

The candidate deployment is `formowl-ontology-uat-r53-occurrence-expansion-8088-20261022-v10`, health `status=ok/query_service_connected=true`. Manifest `sha256:deaefbb6fcef16f2ffe5ea8b9ef5c817df9ce2560ed9f17ca90bf2ba66b2a5f9`, candidate orchestrator `sha256:e7c5b66a4a79ffdb61fc8b7591bf8978a2c7c07143553d7ceec278ce98f7a648` and source binding `sha256:5be36d6228e4243ef274f0e2612b41fee2e0d27a96cf3f4f6439352feac9a42d` are recorded in the private handoff bus. The source binding was recomputed in an isolated 8GB diagnostic container with the same `/out` mount and matched the manifest; no source files were written. A sequential cutover fixed the v9 port-race. The v7 full-observation diagnostic exit 137 and v8/v9 stopped containers remain preserved history.

Focused provider bridge tests for the repair are 4/4 passing. The whole provider bridge module remains non-green (95 tests, 11 inherited descriptor/loop failures); this bounded result is not whole-suite acceptance. Live private-source prompts have not yet been rerun because the execution review requested an explicit confirmation for sending UAT evidence to the configured external provider. Methodology authority remains blocked; feature remains 待測 and no readiness/release/comparative claim is made.

## Current UAT checkpoint — 2026-10-21 UTC / bounded delivery-query remediation / 待測
The provider connection follows the OpenAI-compatible Responses path documented by the referenced codex-provider service. The live 8088 UAT container was restarted with deployment manifest `sha256:14120e7388024a8e6d557a57aa944dfbc0f2304902ef93cfd3820fe3a3c04b58`; the prior manifest and attestation are preserved as `r39-8088-pre-remediation-v3-20261021-*`.
The original webpage question returned one cited same-row result for PO470002002 and 20.QCS64G901 with `CRD 2026-03-04` and `ETD 2026-07-13`; the former Excel serial `46216` is no longer exposed. Trace evidence records two required terms, source families `attachment_table` and `mail`, provider attempts completed, and MCP projection preserved.
Bounded code changes: restore all protected identifiers for attachment scope through the provider-term binder; preserve native spreadsheet `display_value` or verified `date_value_iso` beside raw values; guide the answer model to use that source presentation. Focused bridge/projection tests passed (3 tests).
The result remains a finite UAT diagnostic with coverage `partial` because the source has CRD/ETD but no canonical field literally named 交期. Methodology authority remains blocked and feature remains 待測; no readiness, release, whole-suite, or comparative claim is made.
[Lossless pre-edit checkpoint and hashes](../archive/2026-10-21/uat-delivery-remediation-preedit/) preserve the replaced status.

## Documentation publication handoff — 2026-10-18 / #63
User authorized commit/push. The publication branch is based on main `8dc9fc5`,
not the old dirty branch; only current ontology/issue docs, role-entry consistency
and selected immutable history are included. Main's distinct PR #62 integration
history is preserved in the [main/local preimages](../archive/2026-10-18/ontology-issue63-publication-preedit/),
and its frozen text-admission/tokenizer contract remains in workflows §1.1.
GitHub #20 scoped-closure wording is synchronized in SPEC/README/workflows; no
external acceptance is inferred. Private `.formowl` receipt links remain local-only;
no evidence payload, secret, provider/source operation, runtime code or deployment
is published by this slice. Remote commit identity is the publication commit/branch,
not a new R55 acceptance receipt. At that publication checkpoint, #63 T0 and all implementation gates were pending.
Publication checks: 22 active docs plus selected historical preimages; 48 archive
hashes and 32 new public links verified, frozen provider/recheck/experimental
contracts preserved, diff/privacy heuristic clean. Canonical readonly dev-container
`--check` EXIT0: valid=true, ready=false, errors=[]; all four gates remain blocked.
No full product test suite or live service validation was performed for this docs push.

## Completed issue-reconciliation handoff — 2026-10-18 UTC
User authorized merging/closing stale GitHub issues against the current version
and opening the semantic-annotation/retrieval/checkpoint work. Created
[#63](https://github.com/markliou/formowl/issues/63), A/B implementation plus CP0–CP3,
generic mail/attachment and independent non-mail browser acceptance; T0 then unstarted.
Reopened #56 (research incomplete); transferred #54 A–E and all fourteen regressions
to #51 plus #52 independent actual-artifact/full-manifest acceptance; closed #54
`not_planned`/superseded, not completed. Transferred all six #48 risk responsibilities
to #63 and linked existing owners; #48 closed superseded without changing OpenProject.
#19/#41/#53 retain distinct open scopes; #20 stays closed with its historical
offline/external-activation limitation clarified, not current full acceptance.

GitHub readback at 2026-10-18T04:20:24Z verified nine edited bodies/states, the new
issue, three transfer comments, original #48/#54 body preservation and the full
fourteen-regression transfer. Open issues: 19/41/51/52/53/56/63. The
[safe receipt and three tracking preimages](../archive/2026-10-18/github-issue-reconciliation-preedit/)
bind this reconciliation. Only board/role-goal/handoff bookkeeping and new immutable
preimages were written locally; unrelated dirty work preserved. No commit/push,
worker dispatch, product code, provider, private-source, index, container or UAT run.
Host startup authority check EXIT2 remains supplemental dependency/CJK-unavailable
evidence, not a live regression; the preceding canonical valid-but-blocked result
below remains dated. Four methodology gates/independent release review are open;
feature待測/step4 in-progress and existing program plan unchanged. Checkpoint
creation is not an activated engineering clock, feasibility proof or delivery.

## Completed documentation handoff — 2026-10-18 UTC / 待實作／待測
User authorized comprehensive active-spec synchronization. SPEC §3.1.1/§6.2.1/
§7.2.1/§15.6 now require offline bounded LLM source reading, typed source-linked
annotations, per-unit processing coverage, governed overlays, actual annotation
use in retrieval and native-evidence validation. This replaces ambiguous
optional-annotation/regex-only interpretations, not the frozen experiment.
The explicit direct baseline/fallback remains usable; source facts and chat
need not wait for full annotation. Gaps do not prove absence or authorize extra
rechecks beyond §7.3.1 ALL-fields eligibility. Actual webpage answers and citations
across mail/attachments and independent non-mail cases are the product acceptance
boundary; logs, ledger counts, index/MCP success and abstention on answerable
positive cases cannot establish completion.

Scope: 20 active Markdown files covering SPEC/extraction, README/AGENTS, architecture,
workflows/provenance, the three KG method docs, model/term explanations, role/MCP/
infra/wiki contracts and work-board/goal/handoff/reviewer instructions. Existing
historical records and checkboxes are preserved. Frozen methodology authority,
worker/UAT model policies, code and deployment were not changed. Runtime feature,
four methodology gates and independent release review remain open; the mode/ledger names are
pending requirements, not observed deployed fields. Stale worktree/build copies
are not current instructions and were not mutated.

One read-only sidecar: task `01a14d0c-1c98-7691-a949-4e0ed7483ee3`, requested
`gpt-6.1-sol/high`, actual model/effort unverified, 2026-10-18 UTC. It identified
four linked-doc gaps, now patched. Its follow-up found no blocking contradictions
in those four files and SPEC §§3.1.1/6.2.1/7.2.1/15.6; this is a limited document
review, not three-reviewer release acceptance. The sidecar is closed.
Preimages are losslessly preserved in the 2026-10-18 `ontology-aware-spec-preedit`,
`ontology-aware-spec-preedit-governance`, `ontology-aware-spec-explanatory-preedit`
and `ontology-aware-spec-linked-preedit` archives with hash manifests.
Scoped checks: `git diff --check` EXIT0; 20 active documents changed versus the
preimages; all 22 archived preimage hashes, five new Markdown links/anchors,
balanced fences and active-file retention limits verified. Exact comparisons
preserve SPEC §3.2 provider/query contract, §7.3.1 recheck/budgets, frozen arms
and decision rules, the five-step program plan and existing board checkboxes.
The broad active-doc wording scan leaves no unqualified optional-annotation or
current-ASCII-runtime instruction; archives/build/worktree copies are historical.

Authority: host `--check` EXIT2, dependency probe unavailable/CJK false
(`passed_runtime_gate_requires_cjk_runtime_support`), supplemental only.
Initial container attempts failed first at sandbox Docker access, then at the
image's default UID reading the host-owned 0600 script; neither reached a valid
authority result. With the matching non-root UID 1000:1000, existing
`formowl-dev:local`, read-only repository/rootfs, network none, dropped caps and
temporary `/tmp`, canonical root-workspace `--check` EXIT0: valid=true,
ready=false, errors=[], CJK=true, execution fingerprint
`sha256:6adb0555f5428320e6785f43a1f4016cad3d4c4f24aa8ce0196a498663e43e29`.
No permissions, gates or dependency files were changed. This is a dev-container
probe, not live R55 validation. No `--require-ready` success, product test suite,
UAT question, source/provider operation, runtime implementation, deployment,
commit or push is claimed. Next engineering follows the unchecked generic work
and must obtain actual webpage acceptance; documentation is not feature delivery.

## Dated R55 / ledger536 checkpoint — 2026-10-17 UTC / 待測
### Live, finite reviewed evidence, and open acceptance gates
- [R55 cutover](../../.formowl/uat-weekend-20261016/ops/cutover-code-r55-result-safe.json) EXIT0/2026-10-17 20:01:55Z, **live8088**, code `d580faeab634…`; **R54 retained rollback**, no cleanup. Deployment authority is the exact frozen [package-r55](../../.formowl/uat-weekend-20261016/package-r55.json)/code-r55/tests-r55 inventory, not dirty root product files; this docs slice does not synchronize root code. [Final read-only state](../../.formowl/uat-weekend-20261016/ops/provider-session-r55-final-state.safe.json) confirms exact252code/93tests, pinned image running and8088 HTTP200/statusok/query service connected; health is not release acceptance.
- [Canonical focused91PASS](../../.formowl/uat-weekend-20261016/ops/provider-session-r55-differential.safe.json) is bounded proof. [Broader integration](../../.formowl/uat-weekend-20261016/ops/integration-code-r55-safe.json) =**283 tests /22FAIL+1ERROR /13.005s, NON-GREEN**; all23 inherited assertion tails match R54, no new/resolved failures, Ruff0/compile0/exact252+93. Neither focused green nor inherited failure identity is whole-suite or release acceptance.
- [Dated R54 manual review](../../.formowl/uat-weekend-20261016/ops/provider-session-r54-manual-review.safe.json) =**7 functional LIMITED_PASS +1FAIL (C663)**, four lifecycle checks, source verifier EXIT0 and all9 sent provider requests wire-contract valid. [Formal ledger527](../../.formowl/uat-weekend-20261016/ops/provider-session-r54-ledger.safe.json) =519+8 submissions, not passes; C663's original pre-provider clarification failure remains immutable.
- [Final R55 manual review](../../.formowl/uat-weekend-20261016/ops/provider-session-r55-manual-review.safe.json) records **9 browser questions LIMITED_PASS +4 lifecycle PASS**, finite batch only. [Wire verifier](../../.formowl/uat-weekend-20261016/ops/provider-session-r55-wire.safe.json) EXIT0: all11 sent requests/9 cases contract-valid, `failure_findings=[]`. [Formal ledger536](../../.formowl/uat-weekend-20261016/ops/provider-session-r55-ledger.safe.json) =527+9 submissions, **not passes**, no automatic retries. Whole-UAT/release/methodology acceptance remains false; original R54 C663 FAIL is not regraded.
- [Fresh source verifier](../../.formowl/uat-weekend-20261016/ops/provider-session-r55-source.safe.json) EXIT0 plus the later manual/native review establish all5 citation occurrences/3 unique citations resolve and match. Four requested capacitor values and origin field have same-target/header support; manufacturing location remains unverified. This proves only the returned finite evidence, not full-source coverage, cache-hit rate or upstream routing effectiveness.
- [R55 frozen grammar correction](../../.formowl/uat-weekend-20261016/worker-anscombe-supplied-negative-r55/handoff.safe.json) changes only shared closed supplied-text recognition: whole exterior negative-source constraints plus explicit quoted input, not a no-source override for mixed lookup. Same final tests RED12 subcases→6PASS, related69PASS, [scoped peer AGREE](../../.formowl/uat-weekend-20261016/ops/reviewer-nash-supplied-negative-r55-safe.json); original/earlier failures remain preserved. C600 FAIL/unrerun and C601 compound-price-unit FAIL remain open; R52 C628/C651 observations prove only the exact-capability boundary, not full-source absence.
- [Six provider-request requirements](../../SPEC.md) §3.2 are inherited byte-identically from R54: stable server conversation UUID/header/cache key, fixed instructions/tool order, append-only provider input with dynamic tail, honest UA `uat-web-backend/0.1.0` matching application version, unchanged model/stream/store and current authority guards. Smaller eight-message routing history is separate. Cap/expiry stop safely without silent ID rotation; no cross-restart durability or nonblocking OAuth-reset claim. Public hosted terminology stays paused pending an explicit exception.
- PDF/parser/topology work remains **paused**; [native-PDF review](../../.formowl/uat-weekend-20261016/ops/native-pdf-r53-master-review-safe.json) is not a proven compound-unit fix. [Last lineage receipt](../../.formowl/uat-weekend-20261016/ops/hybrid-current-r1/lineage-progress-safe.json) is not full index/embedding/activation; no new source/index operation or completion forecast here.
- [Fresh canonical authority](../../.formowl/uat-weekend-20261016/ops/authority-r55-final-tmpfs-container.json) EXIT0 with existing tmpfs config: valid=true/ready=false/errors=[], CJKtrue, execution `0eaba758e881…`. [Initial read-only/no-tmpfs probe](../../.formowl/uat-weekend-20261016/ops/authority-r55-final-container.json) EXIT2 remains preserved; no product change or gate promotion. Four methodology gates and independent three-reviewer release gate remain open; feature待測/step4 in-progress. Source500ms/caps/guards and requested models unchanged; actual model/effort unverified, 3s unanswered.
- [New lossless five-file preimages](../archive/2026-10-18/weekend-r55-provider-status-preedit/SHA256SUMS.json) preserve every replaced checkpoint, prior failure and archive link. No prior archive edit, checkbox promotion, root product edit or mirror update.
- Native r2 and bounded r4 are deployed via R50; [r4 peer](../../.formowl/uat-weekend-20261016/ops/reviewer-anscombe-bounded-examples-r50-r4-safe.json) and [r4 original-class preflight](../../.formowl/uat-weekend-20261016/ops/preflight-r50-r4-frozen-routing-safe.json) are scoped, not release acceptance. R39 supplied-isolation/exact-capability/numeric repairs and R47 occurrence/field-hint/composition repairs remain inherited.
- Preserve [R48 failed325/2](../../.formowl/uat-weekend-20261016/ops/integration-code-r48-safe.json), [bounded r1 B01 BLOCK](../../.formowl/uat-weekend-20261016/ops/reviewer-anscombe-bounded-examples-r50-r1-safe.json) and [r3 B02 BLOCK](../../.formowl/uat-weekend-20261016/ops/reviewer-anscombe-bounded-examples-r50-r3-safe.json), prior original-class failures and every original failure log. Later scoped evidence does not rewrite those outcomes.

### Earlier finite browser evidence — immutable dated R47/R39 records
- [R47 occurrence4 final](../../.formowl/uat-weekend-20261016/ops/browser-occurrence-r47-manual-review-safe.json): **limited4PASS**, correlation4/4, all4 full DOM+PNG/visible notes reviewed; fresh source verifier EXIT0 plus Master native semantics, **8 occurrences/4 unique citations**. C583 preserves the preceding2 citations/MCP0, not a four-citation scenario. Dated ledger493 is immutable.
- [Retained-four final](../../.formowl/uat-weekend-20261016/ops/browser-retained-four-r47-manual-review-safe.json): **C590 FAIL**, bounded-source examples misclassified exact/unsupported-capability stop,0citations; **C591 SCENARIO_NOT_PROVEN**, no cited predecessor. Both full captures reviewed/correlation2of2; no returned citations to verify. [Ledger495](../../.formowl/uat-weekend-20261016/ops/browser-retained-four-r47-ledger-safe.json) =493+2 actual submissions, no retries/reset; not passes.
- Earlier [R29-r6](../../.formowl/uat-weekend-20261016/ops/browser-r29-r6-manual-review-safe.json)12 question rubricPASS/2lifecycle (3 cited factual/2 safe boundary) and [retained-r40](../../.formowl/uat-weekend-20261016/ops/browser-retained-r40-manual-review-safe.json)C523 limitedPASS/C524 SCENARIO_NOT_PROVEN remain dated limited evidence. Actual two-citation preservation and C545's one citation never close historical four-to-two loss.

### Historical failures remain immutable
- [C524 original FAIL](../../.formowl/uat-weekend-20261016/ops/browser-r28-adjudication-safe.json); [R30-r2](../../.formowl/uat-weekend-20261016/ops/browser-r30-r2-manual-review-safe.json)3PASS/3FAIL including C560/C562/C563; [R30 original sixFAIL](../../.formowl/uat-weekend-20261016/ops/browser-r30-manual-review-safe.json) unchanged. C580 is a later original-prompt finite pass, not a retrospective regrade of C562 or a whole-source claim.
- [R37 failed156/4](../../.formowl/uat-weekend-20261016/ops/r37-integration-block-safe.json), [R38 failed187/4](../../.formowl/uat-weekend-20261016/ops/integration-code-r38-safe.json), [A changed-fixture BLOCK](../../.formowl/uat-weekend-20261016/ops/reviewer-anscombe-context-fixtures-r38-safe.json) and [B changed-fixture BLOCK](../../.formowl/uat-weekend-20261016/ops/reviewer-nash-context-fixtures-r38-safe.json) preserved. [R41 timeout](../../.formowl/uat-weekend-20261016/ops/integration-code-r41-safe.json) and [split EXIT1/7 failures correction](../../.formowl/uat-weekend-20261016/ops/integration-code-r41-split-correction-safe.json) remain; substring-parser false-green was corrected, not accepted. Composition r1 rejection/older full91 test hash remains distinct from accepted r2 same-test RED→GREEN and R47 integration.

### Operations and next-action boundary
- R55 is live; R54 is retained rollback. No cleanup was performed or authorized in this checkpoint. This five-doc slice performed no cleanup, index, runtime, product/test, source/provider/browser or Docker operation.
- Historical R52r3 frozen manifest `05b484327515…`, product `74044bceaa31…`: R51 preservation3PASS → r2 same-test RED16 → r3 GREEN8; related69PASS/2.390s/Ruff0/compile3. Same-A scoped AGREE; r1/r2 BLOCKs and all prior logs remain immutable. Master integration160PASS (69 routing + 91 composition)/158.174s, Ruff0/compile3/exact252+91 preceded the now-recorded R52 cutover. C628/C651 offline exact-class proof is superseded only for their finite actual-browser boundary observations, not full-suite/business absence acceptance.
- Historical R54 author packet: runtime manifest `5ec884d1…`, unchanged runtime `1607df6f…`, and test-only r2 manifest `0dadedeb…` are frozen. Configure per browser session through `configure_conversation_tools(*, safety_identifier, tool_descriptors)` with both actually enabled evidence descriptors; keep current selected descriptor/capabilities and validators. A's observed `preserve_conversation_on_failure=True` is required for persistent Responses failure handling; app-server behavior remains separate. Final two-module42PASS/6.847s used A snapshot `cba3fc7e…`, not an assertion about later A pins or live provider behavior. R55 now inherits final R54 provider `4a0691f2…` and runtime `1607df6f…` byte-identically; dated R54 wire/browser evidence is separate above.
- Preserve runtime original39/1FAIL and its same R52 baseline FAIL. The separately authorized r2 test-only correction retains all six attempt diagnostics (including middle/latest), baseline1PASS and B-only39PASS; it is contract repair, not semantic RED. Runtime reset/wire/header/cache/input projection tests are synthetic; no real provider/source/browser acceptance follows.
- Final R55 receipts are bound above:9 LIMITED_PASS/4 lifecycle PASS, wire11/9, source5 occurrences/3 unique citations plus native review; formal ledger536. Next: Master exact five-doc diff/link/hash review. No pending R55 grading remains for this finite batch; no full-suite/full-UAT acceptance, replay, cleanup or further engineering is granted. PDF/parser/topology remain paused.
- Targeted scan also found stale R51 checkpoint/omission/tools-empty wording in the four diversity worktree mirrors. They are outside this five-file write set and remain unchanged; use this current handoff and root SPEC for this checkpoint, with any mirror-pointer edit separately scoped.
- [R53 diagnosis](../../.formowl/uat-weekend-20261016/worker-nash-unit-semantics-r53/diagnosis.safe.json) and Master native-PDF review distinguish observed representation loss from unproved sole parser/model cause. Original verifier-r1 source-pin typo is an operator error before source admission, not source corruption; its failure is preserved.
- Semantic1500ms, source500ms/8192, shortlist256, presentation16KiB/128, existing repair/model-call caps, source/hash/lineage/permission and fatal-drain rules unchanged. Only R54's explicitly bounded append-only provider context supersedes eight-message provider-prefix truncation on its configured path; eight-message routing/legacy state remains. The 3s proposal remains unanswered; no latency guarantee, checkbox promotion or completion claim.
- Worker policy unchanged: requested `gpt-6.1-sol/high`; the 2026-10-25 user override requests UAT `gpt-5.6-luna/low`, superseding the dated `gpt-6-luna/high` request. Actual model/effort remains unverified. Fresh canonical authority with existing tmpfs is valid/blocked; initial no-tmpfs EXIT2 is preserved above. The earlier host startup probe lacked tokenizer dependencies and returned invalid/blocked (supplemental only), not a canonical regression or readiness override.

## Retention and next-action boundary
Keep this file at most300 lines; archive distinct lossless preimages before replacing history.
Preserve all old FAILs/BLOCKs and unchecked work. The current user’s bounded weekend
recovery/testing grant supersedes stale docs-only next-action constraints, but each
implementation/operator/source/provider/browser action still needs its explicit owner/scope.
No automatic replay, autonomous monitoring, descendants or release permission follows from this log. U1/U2 report: `/tmp/herdr-bus/codex-to-claude-workorder-20261026u.md` (U2 blocked on private revision access).

## Immutable history
[Complete distinct pre-edit history](../archive/2026-10-17/weekend-r37-contract-correction-preedit/root/docs/agent-goals/handoff-log.md) retains every earlier checkpoint, failure, archive pointer and superseded status.
[SHA256 manifest](../archive/2026-10-17/weekend-r37-contract-correction-preedit/SHA256SUMS.json) binds all eight preimages; old archives remain unchanged. Historical evidence is not a standing dispatch or retry authorization.
