# formowl

<!-- Future agents: read AGENTS.md first. Current methodology authority lives in docs/methodology-authority.json, docs/kg-research-method.md, and GitHub issue #56. Historical files and archived snapshots are not current instructions. -->

FormOwl is a source-preserving, graph-governed knowledge system for integrating
heterogeneous enterprise evidence in native forms: mail, documents, standalone
spreadsheets/XLSX, tables/databases, images, speech, non-speech audio/music,
video, and connected business systems. Email is the first diagnostic fixture.
All adapters enter the same evidence, governance, permission, and query architecture.
An explicitly requested, sealed complete document-only scope may use bounded full reading after an initial zero-citation lookup (at most 200 paragraphs and 60,000 NFC Unicode characters); this direct-source recovery remains 待測 and does not establish ontology-aware readiness.

## Active Architecture

Knowledge construction:

```text
heterogeneous sources
  -> Asset / EvidenceSnapshot
  -> ExtractorRun
  -> source-completeness ledger
  -> source-preserving Observation
       -> ontology-aware semantic read/annotation for the declared scope
          (zero-to-many source-linked candidates per unit)
       -> review -> canonical KG + scoped ontology mappings
       -> permission-filtered EffectiveGraphView
```

The explicitly named `direct_evidence_baseline` may retrieve authorized
Observations without this overlay; it is a fallback/control, not ontology-aware
UAT.

Query execution:

```text
user prompt + bounded conversation state
  -> Query Agent: intent/coreference and current capability discovery
  -> expanded, validated SemanticQueryPlan / tool plans
  -> authorized modality-appropriate retrieval / native structured execution
  -> graph/ontology signals when used, each hop bound to source evidence
  -> temporal, provenance, and coverage filtering
  -> capped soft ontology scoring
  -> evidence-bundle reranking
  -> bounded coverage inspection / repair / source-context selection
  -> deterministic executor or citation-grounded LLM answer
```

The layers have different jobs:

- **Strong RAG** retrieves native source evidence and is both a required component
  and the competitive control. The frozen issue #56 text control remains
  lexical/BM25 + dense retrieval, fusion, and reranking.
- **The KG** contributes reviewed identity, cross-source joins, bounded paths,
  temporal/current-state structure, contradiction, provenance, and reusable
  integration semantics.
- **The ontology** is small-core, scoped, data-first and versioned; it is not
  merely a ranking bonus. LLM reading of the source models
  entities, claims, events, temporal meaning, relations, attachment/thread
  lineage and supersession. Its ranking contribution is capped/additive;
  inferred mismatch does not remove evidence.
- **Deterministic execution** handles exact sets, counts, inventories,
  native table lookups/calculations, aggregation, completeness, and
  definitive-negative claims over validated source records and coverage.
- **The answer model** may explain only the authorized evidence produced by a
  validated plan; it may not fill missing evidence from model memory.

Sources and model output are not canonical truth. Extractors and LLMs may
create reviewable candidates, but they may not silently mutate canonical graph
or type state, user graph revisions, wiki revisions, or external systems.

Ontology supplies a semantic overlay, not a regex index: the semantic reader
links zero-to-many entities, claims, events, temporal frames, relations,
thread/attachment lineage, and supersession records to source Observations.
Direct authorized lookup and structured execution require no graph match only
in the explicit baseline/fallback. In ontology-aware UAT, incomplete annotation
or projection is `partial`/`pending_review`, never source absence. Native image
regions, audio/music intervals, and video frames/clips remain evidence; OCR,
transcripts, and descriptions have their own accuracy and coverage limits.

Answers receive bounded verified source context with native citations, such as
an adjacent paragraph, table header/cell range, image crop, or media clip.
Each read revalidates source/hash/revision/lineage/permission and remaining
budgets; graph visibility or an evidence-snippet grant does not grant whole-asset
access. Spreadsheet operations preserve raw values, formulas, cached results,
displayed values, types/precision/units, blanks/nulls, merged headers,
coordinates, and same-row association. Exact claims need source coverage;
graph properties and top-k chunks cannot substitute for native values.

## Ontology-aware UAT contract

For complete `ontology_aware_uat` acceptance, the system must read the declared
authorized scope with an LLM in offline, resumable batches. Mail means message/thread content and
all authorized attachments; a spreadsheet, PDF, document, ticket, or project
record is a source unit in its own right under the generic Asset/Observation
boundary. Each unit receives an annotation-ledger status and source-linked
semantic candidates, even when candidate count is zero. The query then uses the
ontology to find relevant evidence and validates the answer against the original
source and citation locator. Missing KG/index entries never prove absence.
Incomplete processing allows supported answers with coverage limits and eligible
bounded fallback; it must not make the whole UAT wait for ingestion. Automatic
recheck still obeys SPEC §7.3.1 ALL-fields eligibility, not a new ledger-gap rule.

This contract is generic. A delivery/update case and a project-work-item
deadline/status case are two transfer examples using the same core concepts;
question-specific literals and hard-coded answers are forbidden. Current
implementation and methodology authority remain blocked/待測; this README is a
contract clarification, not acceptance evidence. [SPEC §3.1.1](SPEC.md#311-explicit-execution-modes-and-ontology-aware-uat-contract)
and [§15.6](SPEC.md#156-ontology-aware-webpage-acceptance--待實作待測) own the
contract: actual webpage questions and visible source-correct answers across
mail/attachments and independent non-mail sources, not index/MCP/log success.
The new mode names are requirements, not existing deployed flags.

## Active KG Research Program

GitHub issue #56 is the sole active KG methodology program:

```text
Implement graph-guided Hybrid KG + Ontology v2 that measurably outperforms
strong RAG.
```

Frozen target:

```text
method: evidence_to_knowledge_kg_ontology_v2_hybrid_v1
tokenizer: jieba_sentencepiece_frozen_profile_candidate_admission_v1
```

Historical runtime truth on August 18, 2026 (not current instructions):

```text
method: mail_candidate_kg_broad_ontology_diagnostic_v1
tokenizer: ascii_identifier_regex_v1
CJK support: false
methodology status: blocked
```

Check the executable authority before making a methodology claim:

```sh
python3 scripts/methodology_authority_check.py --check
python3 scripts/methodology_authority_check.py --require-ready
```

The recorded October 2, 2026 canonical dev-container `--check` was valid with
the target method/tokenizer and CJK support true; this is dated diagnostic
evidence, not proof of current readiness. `--require-ready` remains blocked
until source completeness, execution-bound reports,
same-pipeline real-source ablation, and real-user final-answer acceptance all
pass. Diagnostic implementation may continue, but no active document or report
may claim that KG + ontology already beats strong RAG.

## Model Policy

The **2026-10-26 user override** requests `gpt-5.6-luna` with
`reasoning_effort=xhigh` for UAT, superseding the 2026-10-25
`gpt-5.6-luna/low` request (which superseded the dated 2026-10-15
`gpt-6-luna/high` request). Runtime/provider support, observed model/effort binding, and browser
acceptance remain pending; this is not rollout evidence.
The same 2026-10-26 choice keeps `xhigh` throughout the turn. The Chromium
acceptance runner's per-turn wait default and CDP command timeout are both
180 seconds, with provider-attempt and MCP-total elapsed diagnostics aligned to
that bound. Provider 240-second and overall turn 300-second budgets remain
unchanged. The webpage fetch has no shorter application response timer.
Development workers continue to request `gpt-6.1-sol`/`high`, recording actual
configuration as unverified when it is not observed. Dated model evidence keeps
its original identity. See [SPEC §8.1.1](SPEC.md#811-development-worker-tier-and-metadata-recording).
Downtime repair is permitted under Master's bounded, time-based recovery plan.
Missing July/newer snapshot mail is an accepted coverage limitation, not a
user-export blocker; source integrity and incomplete-answer disclosures remain required.

There is no single “FormOwl KG LLM.” Every run records model roles separately:

```text
planner model, if any
candidate extraction or entity-linking model, if any
embedding model
reranker model, if any
final answer model
reasoning effort, decoding, prompt, schema, and context-budget hashes
```

Every comparison arm must use the same final answer model and settings. A model
change creates a new experiment; it is not a free improvement for one arm.
Historical `BAAI/bge-large-en-v1.5` and
`sentence-transformers/bert-base-nli-mean-tokens` runs are candidate-generation
experiments, not ontology models and not a production answer-model decision.

## Anti-Fitting Rule

Current UAT questions are not tokenizer training data, ontology source data,
alias dictionaries, graph rules, or prompt-tuning material. Use separate
calibration, development, frozen evaluation, independent holdout, and transfer
sets. The independent holdout must not influence tokenizer artifacts, aliases,
ontology mappings, thresholds, routing, traversal budgets, prompts, models, or
grading policy. A change motivated by holdout failure requires a new version
and a new holdout.

## Current R55 / ledger536 recovery checkpoint — 2026-10-17 UTC / 待測
[R55 cutover](.formowl/uat-weekend-20261016/ops/cutover-code-r55-result-safe.json) EXIT0/2026-10-17 20:01:55Z, **live8088**, code `d580faeab634…`; **R54 retained rollback**, no cleanup. Deployment authority is the exact frozen [package-r55](.formowl/uat-weekend-20261016/package-r55.json)/code-r55/tests-r55 inventory, not dirty root product files; this docs slice does not synchronize root code. [Final read-only state](.formowl/uat-weekend-20261016/ops/provider-session-r55-final-state.safe.json) confirms exact252code/93tests, pinned image running and8088 HTTP200/statusok/query service connected; health is not release acceptance.
[Canonical focused91PASS](.formowl/uat-weekend-20261016/ops/provider-session-r55-differential.safe.json) is bounded proof. [Broader integration](.formowl/uat-weekend-20261016/ops/integration-code-r55-safe.json) =**283 tests /22FAIL+1ERROR /13.005s, NON-GREEN**; all23 inherited assertion tails match R54, no new/resolved failures, Ruff0/compile0/exact252+93. Neither focused green nor inherited failure identity is whole-suite or release acceptance.
[Dated R54 manual review](.formowl/uat-weekend-20261016/ops/provider-session-r54-manual-review.safe.json) =**7 functional LIMITED_PASS +1FAIL (C663)**, four lifecycle checks, source verifier EXIT0 and all9 sent provider requests wire-contract valid. [Formal ledger527](.formowl/uat-weekend-20261016/ops/provider-session-r54-ledger.safe.json) =519+8 submissions, not passes; C663's original pre-provider clarification failure remains immutable.
[Final R55 manual review](.formowl/uat-weekend-20261016/ops/provider-session-r55-manual-review.safe.json) records **9 browser questions LIMITED_PASS +4 lifecycle PASS**, finite batch only. [Wire verifier](.formowl/uat-weekend-20261016/ops/provider-session-r55-wire.safe.json) EXIT0: all11 sent requests/9 cases contract-valid, `failure_findings=[]`. [Formal ledger536](.formowl/uat-weekend-20261016/ops/provider-session-r55-ledger.safe.json) =527+9 submissions, **not passes**, no automatic retries. Whole-UAT/release/methodology acceptance remains false; original R54 C663 FAIL is not regraded.
[Fresh source verifier](.formowl/uat-weekend-20261016/ops/provider-session-r55-source.safe.json) EXIT0 plus the later manual/native review establish all5 citation occurrences/3 unique citations resolve and match. Four requested capacitor values and origin field have same-target/header support; manufacturing location remains unverified. This proves only the returned finite evidence, not full-source coverage, cache-hit rate or upstream routing effectiveness.
[R55 frozen grammar correction](.formowl/uat-weekend-20261016/worker-anscombe-supplied-negative-r55/handoff.safe.json) changes only shared closed supplied-text recognition: whole exterior negative-source constraints plus explicit quoted input, not a no-source override for mixed lookup. Same final tests RED12 subcases→6PASS, related69PASS, [scoped peer AGREE](.formowl/uat-weekend-20261016/ops/reviewer-nash-supplied-negative-r55-safe.json); original/earlier failures remain preserved. C600 FAIL/unrerun and C601 compound-price-unit FAIL remain open; R52 C628/C651 observations prove only the exact-capability boundary, not full-source absence.
[Six provider-request requirements](SPEC.md) §3.2 are inherited byte-identically from R54: stable server conversation UUID/header/cache key, fixed instructions/tool order, append-only provider input with dynamic tail, honest UA `uat-web-backend/0.1.0` matching application version, unchanged model/stream/store and current authority guards. Smaller eight-message routing history is separate. Cap/expiry stop safely without silent ID rotation; no cross-restart durability or nonblocking OAuth-reset claim. Public hosted terminology stays paused pending an explicit exception.
PDF/parser/topology work remains **paused**; [native-PDF review](.formowl/uat-weekend-20261016/ops/native-pdf-r53-master-review-safe.json) is not a proven compound-unit fix. [Last lineage receipt](.formowl/uat-weekend-20261016/ops/hybrid-current-r1/lineage-progress-safe.json) is not full index/embedding/activation; no new source/index operation or completion forecast here.
[Fresh canonical authority](.formowl/uat-weekend-20261016/ops/authority-r55-final-tmpfs-container.json) EXIT0 with existing tmpfs config: valid=true/ready=false/errors=[], CJKtrue, execution `0eaba758e881…`. [Initial read-only/no-tmpfs probe](.formowl/uat-weekend-20261016/ops/authority-r55-final-container.json) EXIT2 remains preserved; no product change or gate promotion. Four methodology gates and independent three-reviewer release gate remain open; feature待測/step4 in-progress. Source500ms/caps/guards and requested models unchanged; actual model/effort unverified, 3s unanswered.
[New lossless five-file preimages](docs/archive/2026-10-18/weekend-r55-provider-status-preedit/SHA256SUMS.json) preserve every replaced checkpoint, prior failure and archive link. No prior archive edit, checkbox promotion, root product edit or mirror update.

## Current Product Boundary

Implemented repository slices include:

- shared Python contracts for sources, observations, candidates, canonical
  graph objects, effective views, projections, identity, permissions, and
  audit;
- Asset, ingestion-job, extractor-run, and Observation workflows with
  deterministic heterogeneous-source fixture adapters;
- governed mail ingestion and evidence-query fixtures, plus bounded real-PST
  parser diagnostics;
- candidate extraction and review contracts, canonical graph lifecycle
  contracts, scoped ontology contracts, user/effective graph views, and
  graph-derived wiki drafts;
- PostgreSQL/pgvector adapter contracts and file-backed compatibility stores;
- Project MCP and Wiki MCP compatibility services;
- the connected FormOwl MCP Gateway on exact `/mcp` with Google-backed FormOwl
  OAuth 2.1 and a fresh gateway-controlled `ActorContext`.

These slices do not establish production readiness, source-complete
heterogeneous integration, automatic canonical writes, general parser
coverage, or KG + ontology superiority.

Business examples are target applications of one generic query core, not 30
implemented functions. Native-table fields bind to the actual authorized schema;
attachment content retains its mail parent, while standalone documents retain
independent source bindings. The bounded integration target is exact
UnitPrice/Quantity retrieval, DOCX attachment content and a standalone clause.
It does not establish aggregation, currency math or latest-revision completeness.

### Dated UAT evidence — not current deployment or dispatch

At the historical 2026-10-12 checkpoint, serving manifest r12 (`b2f4fa44…`) ran on
live8089, full252 product files/drift0; candidate8096 was deployed/proved, then
removed at19:35:25Z. Old r5 remains stopped/preserved for rollback.
Canonical focused **117/117,174.049s,EXIT0**, zero
failures/errors/skips, exact252 code/34 tests verified pre/post and rechecked;
Hypatia/Archimedes/Lagrange retention-only scoped **AGREE3/3**. The retention
constant derives from unchanged request cap6 (local19/19,0.818s/Ruff);
no model/budget/deadline change or full-suite/standard promotion.

R11's108/108,170.274s/EXIT0 and three scoped agreements remain bounded.
Fixture-r11 EXIT0 proved synthetic PDF/independent-document cue/citation/lifecycle,
but all six responses remain incomparable: deployment/code/build absent, with
four-attempt business turns retaining three records. Later bindings do not
retrospectively repair them. Freeze-helper TypeError/empty tree and readonly-
template chmod failure are retained; the latter was fixed only in the operator
helper's private tmpfs-copy handling, no product/secret change.

The safe audit proved native PDF text was erased by redaction, not absent.
Generic span preservation leaves detector/final guard unchanged; version0.6.2
required a new offline job/revision. Same2048/all-formats r3 completed
18:57:38Z/EXIT0 (622,631 Observations/7,211 runs), prep-r4 completed19:18:55Z/EXIT0.
New partial pin `5e222fc…`:1,100,143 references/407,401 helpers/10,671,080 postings,
zero independent-document helpers; native PDF admission retained three indexed
paragraphs. Old runs/pins/failures remain preserved. Ordinary Observation writes
stay sharded; only the finite sealed materializer explicitly keeps flat export
([SPEC §11.1](SPEC.md#111-query-independent-offline-batch-indexing--待測)).

Candidate original-source acceptance passed19:26Z: both citations reopened/hash/
run/parent checked; requested delivery, not PO/approval dates, shipment or latest
supplier schedule. The unrelated actual attachment proof is not independently
registered document proof. Live Chromium LAN EXIT0: all four responses comparable,
delivery22.829s and unrelated attachment17.833s, each MCP1/provider2/citation1;
ordinary/reload/reset/postreset MCP0. Evidence turns honestly remain partial.
First live citation reopen failed
`ContractValidationError: ingestion revision completed job changed`.
Once-only instrumentation then verified both LIVE citations and original-source
meaning with loader/guards unchanged and all three job digests agreeing across
engines. Archimedes scoped **AGREE**: **this observed question's source-verified
answer was obtained in the real LAN webpage**. The first failure remains
unexplained and blocks stability/reproducibility acceptance, not that observed
answer. No corruption/root-fix, full-UAT, source-complete or docs acceptance claim.

The bounded diagnostic producer binds trusted frozen manifest/operator attestation
to read-only full-inventory/runtime and image/settings/validated-source identity.
This is not remote attestation or formal readiness; missing/mismatched/truncated
identity remains incomparable. Canonical authority-resume4 is
valid=true/ready=false/errors=[]/EXIT0. Feature待測, step4 in-progress and all four
blocked gates remain unchanged; no user-only blocker. Safe evidence and next
action: [handoff](docs/agent-goals/handoff-log.md).

For explicitly authorized temporary LAN UAT diagnostics, the existing launcher
requires both opt-in flags together:

```text
--behavior-log /uat-private/behavior.jsonl --record-raw-uat-interactions
```

The operator must provide a persistent writable mount at the chosen log
directory, restricted to the service/operator, outside browser-served content.
The recorder enforces a regular `0600` JSONL file and rejects symlink files.
Raw prompt, expanded query and available visible answer stay only in this private
file; public diagnostics/stderr contain safe metadata and request correlation,
never raw content, credentials, headers, cookies or backend storage paths.
Schema v2 distinguishes repeated questions and records citation membership at
raw/presented/final stages plus available validated plan, field support and scan
stop metadata. Recording errors retain the business result and emit a safe
failure event. Operator persistence must survive container replacement; the
file is not an HTTP/MCP download or a general logging exemption.

Historical **2026-10-13 logging activation evidence**, diagnostic-only / 待測:
its frozen package is
[package-r1.json](.formowl/uat-observability-20261013/package-r1.json). Canonical36/36
and observed candidate/live browser/log capture passed; three scoped reviewers
Chandrasekhar/Gibbs/Harvey AGREE for logging activation only. At that activation,8088 served
`formowl-uat-observability-live-20261013`, code4544e59a…/252files/drift0, same
source/image/gpt-5.5 high/budgets; old r12 is stopped/preserved for rollback.
Live ordinary chat MCP0 and unrelated lookup MCP1/provider2/citations2 passed;
private file=HTTP=DOM, raw9/presented7/final2 IDs, matching provider/turn/MCP IDs,
zero log failures and private-log URL404 checks. Repeated-prompt verification is
candidate evidence, not a repeated live test. Candidate cleanup completed with
logs retained and live healthy; unrelated containers untouched. Frozen fixture
integration retains one PASS/one pre-service artifact-fingerprint ERROR, root
unresolved; it is not all green. The COO-answer
inconsistency is still unresolved, and all four methodology
gates remain blocked. Contract and limitations: [SPEC](SPEC.md#731-source-neutral-evidence-double-check--待測)
and [handoff](docs/agent-goals/handoff-log.md).

Historical **2026-10-13 UAT consistency repair checkpoint / 待測**
(not current deployment or a standing next-action assignment).
[Baseline](.formowl/uat-stability-20261013/baseline-safe.json): ten actual browser
turns/file=HTTP=DOM, five cited partial answers, one chat, two unexpected
clarifications, one honest incomplete lookup and one provider error; eight
comparable. Demonstrated causes include `country` matching the `count` substring
and provider chat routing using lossy prior evidence while runtime retained
citeability. Synthetic repros separately prove source-family/selector starvation,
read-cap accounting loss and duplicate parent reads; the historical 500 ms cause
is not established. Generic fixes preserve budgets, source guards and exact/all-fields contracts.

[Frozen r4](.formowl/uat-stability-20261013/package-r4.json), `dd731bfc…`, is a
**diagnostic rollout with observed live proof**. [Verification](.formowl/uat-stability-20261013/r4-verification-safe.json):
pinned-image153/153 PASS254.897s, integration3/3 PASS110.247s, lint/compile12 PASS;
exact252 code+37 tests/post-run hashes verified. Native-stop32/32+115subtests and
query-guard29/29+34subtests passed with Ruff. Prior32tests/3ERROR and r1/r2 failures
remain preserved; the native negative fixture was corrected without weaker guards.

The server binds only a unique validated cited protected alphanumeric identifier
for followups; explicit NFKC IDs win and original current/source-turn hashes remain
separate. Missing/ambiguous/reset/scope-invalid references stop before provider/MCP;
no general numeric/person or arbitrary-history inference. Expanded queries now pass
the shared safety check before MCP; existing bounded repair keeps the same ID/scope.
Private logging may retain hashes/status only with content_redacted=true and
exact_result_preserved=false, which cannot prove exact log/HTTP/DOM equality.
Contracts: [SPEC §7.1](SPEC.md#71-core-query-agent-and-query-classes) and
[§7.3.1](SPEC.md#731-source-neutral-evidence-double-check--待測).

R3 passed150 focused+3integration but browser8 had only6passes, one MCP contract
error and dependent missing-reference clarification; no failed private record.
The original cause remains unproved. The unsafe-expansion repair has controlled
synthetic proof; r4 candidate did not trigger either query guard or redacted logging.
R4 initial8:7comparable/correct and one provider HTTP502/connect_headers1.044s after
valid cited MCP. Separate predeclared fresh-chat+delivery recheck2/2 passed;
original failure stays failed/incomparable. All10 unique candidate records match
log/HTTP/DOM exactly. Citations match prior same-source proof; no native reopen.

Nash engineering/Bacon safety/Linnaeus methodology all AGREE for bounded diagnostic
deployment. [Readiness15:04:37Z](.formowl/uat-stability-20261013/live-r4-ready-safe.json)
confirms8088 serves r4 `dd731bfc…`,252files/drift0, same image/source/settings/budgets,
logs0600/dir0700; old observability is stopped/preserved for rollback.
[Actual LAN matrix](.formowl/uat-stability-20261013/live-r4-safe.json) and verifier
EXIT0:14/14 known checks PASS, all14 log=HTTP=DOM text/citations. Eight cited partial,
four ordinary-chat MCP0, one honest incomplete unknown (provider1/MCP1), one reset
missing-reference clarification (no provider/MCP). Thirteen provider turns are
comparable; reset clarification is local/identity-exempt, not provider-comparable.
Repeated/fresh/rephrase answers retain the same origin citation; same-row manufacturer,
unrelated-part origin/manufacturer and PO delivery match prior same-source evidence. Master
reviewed manufacturer/delivery screenshots; PO page1/3 is partial requested-delivery
evidence, not shipment/latest commitment. Reload/reset/postreset chat pass. No fresh
native reopen; source pin unchanged. [Cleanup15:11:45Z](.formowl/uat-stability-20261013/final-operational-r4-safe.json):
8088 healthy/exact252/drift0/restart0/OOMfalse; four own candidates removed, logs
and rollback retained; source/index/DB/unrelated containers untouched.14private
records/IDs, zero recording failures/redacted/unsafe-query events, private URLs404
twice, file0600/dir0700.
This is observed known-regression proof only. Upstream/provider,
r3 incident and source/artifact anomalies remain OPEN. Four methodology gates
blocked, step4 in-progress; no whole-UAT/provider-stability/standard promotion.
[Handoff](docs/agent-goals/handoff-log.md) and unchanged [pre-edit archive](docs/archive/2026-10-13/uat-stability-r3-pre-verification/SNAPSHOT.md)
preserve dated errors, tooling differences and prior review boundaries.

Current adapter limits are explicit in [SPEC §14](SPEC.md#14-current-implementation-and-methodology-status):

| Slice | Evidence and remaining gap |
| --- | --- |
| Mail and independent Markdown/plain-text | Diagnostic mail and the real `PlainTextObservationExtractor`; §7.3.1 live mail/document acceptance remains open. |
| XLSX/delimited attachment tables | `AttachmentDocumentExtractor` reads bounded ZIP/XML values, row/cell coordinates, formula/raw/cached/date/precision/blank metadata where available, and formal table metadata, with candidate merged-header paths. It does not recalculate formulas or guarantee native display/style/type/unit/null semantics or full-workbook completeness, and does not establish the standalone XLSX end-to-end product path. |
| OCR/images | `FixtureOcrExtractor` uses `read_text()` on page/bbox fixtures; real-image OCR, visual retrieval, and source-region verification are unproved. |
| Audio/music | `FixtureAudioTranscriptExtractor` uses `read_text()` on timestamp/speaker/transcript fixtures; real decoding/ASR, acoustic verification, non-speech audio and music paths are unproved. |
| Video | `FixtureVideoSceneExtractor` uses `read_text()` on scene/keyframe descriptions; real decoding, temporal/visual retrieval, and native clip/frame verification are unproved. |

Unsupported native features remain coverage gaps. MIME/modality labels and
cited text proxies do not establish native media capability. This SPEC/doc
clarification changes no runtime, frozen methodology/tokenizer, comparison
arms, UAT status, readiness, or independent reviewer acceptance.

The connected closed-beta identity path uses one stable non-secret predefined
client ID selected and recorded by the deployment operator before discovery.
ChatGPT supplies and displays only the production callback
`https://chatgpt.com/connector/oauth/{callback_id}`. If the current ChatGPT UI
cannot use the recorded predefined client, the live flow stops as an external
live blocker. The reserved
`https://invalid.example.invalid/formowl-discovery-only` callback is only the
`discovery_only` state for `initialize` and `tools/list`; `/readyz` remains
unready, protected tools return an OAuth challenge without authorization audit,
and bootstrap is blocked until the production callback is configured and the
runtime is restarted. The external evidence and review campaign required for
Issue #20 closure has not yet passed.

Issue #41 separately owns generic Asset tenant/owner binding, byte storage,
occurrence lineage, upload recovery, retention, purge, and authorization. A
source adapter must not create a parallel asset or permission system.

Attachment format expansion also implements bounded XLS/XLSM, native-text PDF,
DOCX/PPTX and text/delimited parsing through the same Observation owner. Known
child parser failures remain failed and disclose partial parent coverage; unknown
errors still fail the batch. Offline backfill and RAG activation are separate
from parser support and remain unaccepted for live UAT. Scan-only PDF/OCR, XLS
formula identity and complete native display semantics are not established.

### Source-neutral evidence recheck — 待測

The 2026-10-06 contract in `SPEC.md` §7.3.1 applies to validated
`evidence_lookup` for both mail and independent Markdown/plain-text documents.
Parsed mail attachment text remains mail evidence; it does not satisfy the
independent-document acceptance case. A nonempty validated requested-field set with **all
fields** lacking verified support triggers one materially different,
same-authorized-scope bounded source recheck when existing safety/eligibility
and remaining budgets permit, even with unrelated citations. Partial misses
must be disclosed and must not trigger this automatic recheck. An empty field
set uses the validated evidence-need plan or clarification, never vacuous
“all missing”; source-backed
explicit blanks count as verified coverage. Citation count or status alone
cannot trigger recheck.

Missing, unsealed, or unactivated retrieval projections are distinct from an
independently validated immutable source snapshot, not independent permission
to bypass §7.3.1 eligibility. Eligible fallback may use that snapshot without
the failed projection, but preserves authorized source/hash/lineage/
revision checks, permission scope, and existing bounded budgets; no inline
rebuild. Exact deterministic, permission, schema, and provider-error boundaries
are unchanged. Incomplete scans/timeouts never prove absence; scoped complete
negatives require complete coverage proof. Feature remains **待測**; this is
not implementation, live UAT, review, or methodology acceptance evidence.

## Storage and Runtime Direction

FormOwl is container-first. Python remains the Phase 0 orchestration and policy
language. PostgreSQL is the canonical authority for metadata, provenance,
permissions, graph/ontology revisions, reviews, jobs, and audit; pgvector is
the default dense-retrieval baseline. Raw and large binary assets live behind
an object-store abstraction. A graph data model does not require migration to a
graph database.

All user-facing access goes through governed MCP/service operations. Raw paths,
SQL, object-store administration, parser controls, worker scratch locations,
or hidden oracle values must not appear in public tool schemas or results.

## Historical Compatibility Evidence

Legacy benchmark readers and tests retain two candidate-matching numbers:
`0.758664` and `0.757744`. They are **candidate-only** historical evidence.
They do not compare the frozen issue #56 runtime, do not measure final-answer
quality against strong RAG, and do not authorize a hard ontology gate.

## Documentation Map

Current authority:

- `AGENTS.md` — startup rules, active role, and current methodology boundary.
- `SPEC.md` — canonical product and architecture specification.
- `RESOURCE_EXTRACTION_SPEC.md` — source-complete heterogeneous extraction and
  Observation contract.
- `docs/methodology-authority.json` — machine-readable readiness authority.
- `docs/kg-research-method.md` — active research hypothesis, comparison arms,
  metrics, anti-fitting rules, and decision gates.
- `docs/kg-ontology-v2-rd-boundary.md` — Hybrid v2 implementation boundary.
- `docs/kg-ontology-v2-runtime-evaluation-plan.md` — issue #56 work packages and
  same-pipeline evaluation plan.
- `docs/kg-ontology-pretrained-model-explanation.md` — plain-language model,
  RAG, KG, ontology, and fitting explanation.
- `docs/architecture.md`, `docs/workflows.md`, `docs/mcp-boundaries.md`,
  `docs/provenance.md`, and `docs/infra-spec.md` — aligned system boundaries.
- `docs/implementation-task-breakdown.md` and `docs/agent-goals/` — bounded
  active work and durable role state.

Diagnostic integration:

- `docs/kg-eval-package.md` — compatibility boundary for the packaged
  evaluation facade; it is not a substitute for methodology authority.
- `docs/kg-bert-runtime.md` — optional candidate-generation model runtimes and
  historical artifact compatibility.

Historical pointer files:

- `docs/mail-ontology-native-factorial-design.md`
- `docs/ontology-v2-coordination-plan.md`
- `docs/ontology-v2-coordination-frames.md`
- `docs/ontology-v2-review-comments.md`
- `docs/agent-goals/dual-track-uat-kg-coordinator.md`

Those filenames remain only to redirect readers to current authority and the
immutable pre-rewrite snapshot under `docs/archive/2026-08-18/`. They are not
work orders.

## Development

Build the dev container image:

```sh
docker build -f containers/dev/Dockerfile -t formowl-dev:local .
```

### Connected OAuth/MCP operator sequence

The production-shaped repository entrypoint is `formowl-connected-mcp`. Start
from a clean clone by building the runtime image and generating the six local
FormOwl/PostgreSQL secrets:

```sh
docker build -f containers/runtime/Dockerfile -t formowl-runtime:local .
docker run --rm --user "$(id -u):$(id -g)" \
  -v "$PWD/deploy/connected/secrets:/secrets" \
  formowl-runtime:local init-secrets --output-dir /secrets
```

This creates a single-active-key manifest plus an unused
`signing-previous.pem` standby mount slot. It does not create the Google OAuth
client secret and it does not prove preflight readiness. Import the real Google
client secret separately as a mode-`0400` file. The tracked non-secret
`deploy/connected/compose.env.example` is the field/template contract; the
operator copies it to the real ignored, mode-`0600`
`.formowl/issue20/compose.env`; the containerized operator helper validates and
rewrites that same operator file, which every Compose command receives through
`--env-file`. Before discovery, the operator uses the containerized helper to
derive or validate and record one stable non-secret predefined client ID; this
requires no host Python. ChatGPT Apps management must use that same ID if its
current predefined-client UI supports entry or selection. If it does not, stop
and record an external live blocker. ChatGPT supplies and displays only the
production callback; never invent the ID or claim ChatGPT generated/displayed
it, and do not claim migration to a different client-registration model. Full
creation commands, file meanings, safe interrupted-initialization recovery,
and the no-placeholder rule are in `docs/closed-beta-runbook.md` and
`deploy/connected/secrets/README.md`. Do not put secret values on the command
line, in environment variables, tracked files, screenshots, logs, evidence
packets, or ChatGPT messages.

`deploy/connected/Caddyfile.example` is the concrete TLS reverse-proxy sample.
It keeps FormOwl published only on `127.0.0.1:8000`; Compose publishes no
PostgreSQL port. The exact discovery-only start/check/stop/finalize commands,
standalone Caddy command, final Compose TLS profile, and official public-only
MCP Inspector flow are in `docs/closed-beta-runbook.md`. Launch Inspector from
the operator workstation and connect it to the public HTTPS `/mcp` endpoint:

```sh
npx @modelcontextprotocol/inspector@latest
```

Production accepts only
`https://chatgpt.com/connector/oauth/{callback_id}` with one non-empty
RFC-unreserved callback-id segment. The sole placeholder is
`https://invalid.example.invalid/formowl-discovery-only`, used only when public
`initialize`/`tools/list` discovery is required to reveal the real callback.
This sentinel state is the literal `discovery_only` boundary. In sentinel mode,
`/readyz` returns 503, protected tools only challenge without audit, and
bootstrap/OAuth/operator mutations are blocked. Stop and remove the discovery
containers, replace the sentinel with the exact callback, restart the final
configuration, and only then start PostgreSQL, migrate, run normal preflight,
bootstrap, or OAuth.

```sh
COMPOSE_ENV=.formowl/issue20/compose.env
docker compose --env-file "$COMPOSE_ENV" --file compose.yaml \
  up -d postgres
docker compose --env-file "$COMPOSE_ENV" --file compose.yaml \
  run --rm connected-migrate
docker compose --env-file "$COMPOSE_ENV" --file compose.yaml \
  run --rm connected-mcp preflight
docker compose --env-file "$COMPOSE_ENV" --file compose.yaml \
  run --rm connected-mcp bootstrap-owner \
  --workspace-id <workspace-id> \
  --email <invited-owner-email> \
  --expires-at <RFC3339-expiry> \
  --idempotency-key <operator-generated-idempotency-key> \
  --operator-service-id <authorized-operator-service-id>
docker compose --env-file "$COMPOSE_ENV" --file compose.yaml \
  up -d connected-mcp
```

After the first real Google login creates the invited owner, an authorized
deployment shell can obtain stable IDs without temporary SQL:

```sh
docker compose --env-file "$COMPOSE_ENV" --file compose.yaml \
  run --rm connected-mcp lookup-user \
  --email <owner-email> \
  --workspace-id <workspace-id> \
  --operator-service-id <authorized-operator-service-id>
docker compose --env-file "$COMPOSE_ENV" --file compose.yaml \
  run --rm connected-mcp list-users \
  --workspace-id <workspace-id> \
  --operator-service-id <authorized-operator-service-id>
docker compose --env-file "$COMPOSE_ENV" --file compose.yaml \
  run --rm connected-mcp lookup-token-session \
  --user-id <user-id> \
  --workspace-id <workspace-id> \
  --operator-service-id <authorized-operator-service-id>
docker compose --env-file "$COMPOSE_ENV" --file compose.yaml \
  run --rm connected-mcp list-token-sessions \
  --user-id <user-id> \
  --workspace-id <workspace-id> \
  --operator-service-id <authorized-operator-service-id>
```

Use the returned owner `user_id` for an operator-authorized invitation:

```sh
docker compose --env-file "$COMPOSE_ENV" --file compose.yaml \
  run --rm connected-mcp invite-user \
  --workspace-id <workspace-id> \
  --email <invited-user-email> \
  --role member \
  --invited-by-user-id <owner-user-id> \
  --operator-service-id <authorized-operator-service-id> \
  --expires-at <RFC3339-expiry>
```

Membership removal and restore are explicit operator commands, not MCP tools:

```sh
docker compose --env-file "$COMPOSE_ENV" --file compose.yaml \
  run --rm connected-mcp remove-workspace-member \
  --user-id <user-id> \
  --workspace-id <workspace-id> \
  --operator-service-id <authorized-operator-service-id>
docker compose --env-file "$COMPOSE_ENV" --file compose.yaml \
  run --rm connected-mcp restore-workspace-member \
  --user-id <user-id> \
  --workspace-id <workspace-id> \
  --operator-service-id <authorized-operator-service-id>
```

Removal preserves membership history and revokes every unrevoked token session
for that user/workspace. Restore never reactivates those sessions; the user must
complete the Google-backed FormOwl OAuth flow again. Use a returned active
`token_session_id` for `revoke-token-session`. Lookup/list results omit email,
display name, bearer/JTI material, scopes, provider subject, raw paths, SQL, and
backend details. Allow and deny decisions are audited; an audit write failure
returns no result or membership mutation.

`operator_service_id` is an attribution identifier, not a password or remote
authorization credential. These commands are not MCP tools. Their actual
security boundary is access to the controlled deployment shell, Docker daemon,
Compose configuration, and mounted secret files. The full migrate, bootstrap,
lookup, invite, restart, revocation, signing-key rotation, MCP Inspector, and
live ChatGPT/Google sequence is in `docs/closed-beta-runbook.md`. Those external
journeys are not yet accepted completion evidence. GitHub #20 retains its
scoped offline-work/external-activation closure; the unresolved obligations
remain tracked through #63, without a production-readiness claim.

Issue #20 establishes connected identity and fresh `ActorContext` only. Issue
#41 separately owns generic Asset tenant/owner binding, byte storage,
occurrence lineage, upload recovery, lifecycle, retention, purge, and
authorization. Issue #21 is a downstream governed mail-evidence consumer of
that generic Asset boundary and does not define another identity or connected
transport path.

Run tests inside the dev container:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python -m unittest discover -s tests"
```

Run tests with coverage inside the dev container:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "coverage run -m unittest discover -s tests && coverage report"
```

The coverage report enforces the minimum threshold configured in
`pyproject.toml`.

Run the KG research acceptance suite inside the dev container:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/kg_research_acceptance_suite.py"
```

Use `--strict` when the command should fail on any failed or blocked acceptance
item. The default command exits successfully while clearly marking known limits
such as production adapter readiness and enterprise latency/scalability.

The `.formowl/kg-eval` workspace and packaged `formowl_kg_eval` interface are
legacy diagnostic compatibility surfaces. They are retained for repository
tests, historical artifact readers, and redacted integration output; they are
not the issue #56 work board or methodology authority. The package field named
`authority_state` describes only legacy-harness self-consistency. It cannot
override `docs/methodology-authority.json` or a nonzero
`methodology_authority_check.py --require-ready` result.

The CLI entry point remains `formowl-kg-eval`, with
`python -m formowl_kg_eval` as the module fallback. `summary` and `benchmarks`
may expose historical candidate-generation capabilities and candidate-level
benchmark results. They do not establish source completeness, a strong-RAG
control, the frozen tokenizer, final-answer quality, independent holdout
acceptance, transfer-domain acceptance, or KG + ontology superiority. See
`docs/kg-eval-package.md` for the exact compatibility boundary.

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python -m formowl_kg_eval summary"
```

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python -m formowl_kg_eval benchmarks"
```

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace/.formowl/kg-eval formowl-dev:local bash -c "python kg_total_acceptance_suite.py && python real_evidence_preflight.py"
```

The third command runs the historical broad harness only. Treat its output as a
legacy diagnostic even if it passes.

Run lint and formatting checks inside the dev container:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "ruff check python tests scripts && ruff format --check python tests scripts"
```

Run the closed-beta readiness smoke inside the dev container:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/closed_beta_smoke.py --output /tmp/formowl-closed-beta-smoke.json"
```

Run the issue #21 mail evidence MCP smoke inside the dev container:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_evidence_mcp_smoke.py --output /tmp/formowl-mail-evidence-mcp-smoke.json"
```

This smoke uses a synthetic mail fixture to exercise the ChatGPT-free local path
from asset/job/extractor records to governed JSON-RPC `query_mail_evidence` and
`answer_mail_case_progress` calls. It validates permission filtering,
citations, hash-only transcripts, and hash/status/count public reporting. It
does not claim actual ChatGPT connected upload, production iframe readiness,
real PST/OST/MSG/EML/MBOX parsing, live PostgreSQL deployment readiness,
production worker leasing, KG writes, wiki projection, or production readiness.

The local semantic JSON-RPC compatibility command for #21 mail upload task-card
testing is:

```sh
FORMOWL_DATA_DIR=.formowl/data formowl-semantic-mcp-jsonrpc
```

Set `FORMOWL_MCP_SESSION_ID`, `FORMOWL_MCP_ACTOR_USER_ID`, and
`FORMOWL_MCP_WORKSPACE_ID` to bind the trusted internal session context for a
local smoke. Unsafe secret-like values are rejected to safe defaults. These
variables are forbidden by the connected runtime and must never be used to
configure the formal ChatGPT connection.

Run the #21 mail upload MCP command preflight:

```sh
python scripts/mail_upload_mcp_command_smoke.py --output /tmp/formowl-mail-upload-mcp-command-smoke.json
```

This preflight checks the configured command path and upload task-card session
creation only. It does not claim actual ChatGPT connection, file transfer, real
upload iframe readiness, real mail parser readiness, live PostgreSQL readiness,
production worker leasing, KG writes, wiki projection, or production readiness.

Run the #21 mail upload-surface intake focused tests:

```sh
python -m unittest discover -s tests -p "test_mail_upload_surface.py"
```

These tests cover backend receipt and rollback for a session-bound upload
surface. They do not perform an actual iframe or ChatGPT connected upload.

Run the #21 local HTTP upload-surface contract focused tests:

```sh
python -m unittest discover -s tests -p "test_mail_upload_http_surface.py"
```

These tests exercise the stdlib local HTTP GET/POST multipart harness and its
handoff into backend upload intake. They still do not perform an actual ChatGPT
connected upload or production iframe test.

Run the #21 MCP-command-to-local-HTTP upload smoke:

```sh
python scripts/mail_upload_mcp_http_smoke.py --output /tmp/formowl-mail-upload-mcp-http-smoke.json
```

This smoke proves the configured command can open the upload task and that the
local HTTP surface can receive one synthetic session-bound mail archive upload.
It still does not perform an actual ChatGPT connected upload, production iframe
test, real mail parsing, live PostgreSQL deployment, production worker leasing,
KG writes, wiki projection, or production readiness.

Run the #21 local upload-to-import-and-query smoke:

```sh
python scripts/mail_upload_mcp_http_import_smoke.py --output /tmp/formowl-mail-upload-mcp-http-import-smoke.json
```

This smoke extends the local command-to-HTTP path through the synthetic
server-side import workflow and store-backed `query_mail_evidence` JSON-RPC
surface. It still does not perform an actual ChatGPT connected upload,
production iframe test, real PST/OST/MSG/EML/MBOX parsing, live PostgreSQL
deployment, production worker leasing, KG writes, wiki projection, or
production readiness.

Run the #21 sampled real PST ingestion smoke inside the dev container after
placing the operator-provided PST at `tests/pst-exm/archive.pst`:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_real_pst_smoke.py --output .test-tmp/formowl-real-pst-sampled-smoke.json --mode sampled --sample-message-limit 25"
```

Validate the saved public report:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_real_pst_smoke.py --validate-report .test-tmp/formowl-real-pst-sampled-smoke.json --output .test-tmp/formowl-real-pst-sampled-validation.json"
```

This smoke requires `readpst` from the dev image's `pst-utils` package. The
report must remain hash/status/count-only: do not paste PST contents, concrete
message identifiers, subjects, senders, attachment names, body text, object
store locators, parser command lines, scratch paths, SQL, or environment values
into public reports. The sampled smoke may set
`supports_real_pst_sampled_parser_claim=true` only after the report validator
passes. It must keep full-parser, production, ChatGPT upload/file-transfer,
iframe, worker-leasing, raw-mail-access, KG, and wiki claims false.

Run the #21 full PST 100-case mail evidence evaluation inside the dev container
after placing the operator-provided PST at `tests/pst-exm/archive.pst`:

```sh
docker run --rm -e FORMOWL_RUN_FULL_PST_100_CASE_EVAL=1 -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_full_pst_100_case_eval.py --output .test-tmp/formowl-mail-full-pst-100-case-eval.json"
```

Validate the saved public report:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_full_pst_100_case_eval.py --validate-report .test-tmp/formowl-mail-full-pst-100-case-eval.json --output .test-tmp/formowl-mail-full-pst-100-case-validation.json"
```

This evaluation performs a full parse with no message sampling, then scores 100
manifest-bound governed `query_mail_evidence` cases. The public report must
remain hash/status/count-only and must not include query text, PST contents,
concrete message identifiers, subjects, senders, attachment names, body text,
object-store locators, parser command lines, scratch paths, SQL, or
environment values. Passing this evaluator supports only the operator-provided
full PST 100-case evidence-reading evaluation claim; it is not a general mail
parser, ChatGPT upload, production iframe, live PostgreSQL, worker-leasing,
raw-mail-access, KG, wiki, or production readiness claim.

Run the #21 domain-hard full PST mail evidence baseline inside the dev
container:

```sh
docker run --rm -e FORMOWL_RUN_FULL_PST_DOMAIN_HARD_CASE_EVAL=1 -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_full_pst_domain_hard_case_eval.py --output .test-tmp/formowl-mail-domain-hard-case-baseline.json --work-dir .test-tmp/formowl-mail-domain-hard-case-baseline-work"
```

Validate the saved public report:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_full_pst_domain_hard_case_eval.py --validate-report .test-tmp/formowl-mail-domain-hard-case-baseline.json --output .test-tmp/formowl-mail-domain-hard-case-baseline-validation.json"
```

This baseline intentionally allows low pass rates so difficult cases can expose
retrieval and performance gaps. The public report must remain
hash/status/count/timing-only. Do not paste query text, PST contents, concrete
message identifiers, subjects, senders, body text, private manifest contents,
object-store locators, parser command lines, scratch paths, SQL, or environment
values into public reports.

Run the #21 non-BERT candidate-only KG fusion rescore over a preserved
domain-hard work directory:

```sh
docker run --rm -e FORMOWL_RUN_FULL_PST_DOMAIN_HARD_KG_FUSION_EVAL=1 -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_full_pst_domain_hard_kg_fusion_eval.py --baseline-report .test-tmp/formowl-mail-domain-hard-case-baseline-v4.json --work-dir .test-tmp/formowl-mail-domain-hard-case-baseline-work-v4 --output .test-tmp/formowl-mail-domain-hard-kg-fusion-eval-v1.json"
```

Validate the saved KG fusion public report:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_full_pst_domain_hard_kg_fusion_eval.py --validate-report .test-tmp/formowl-mail-domain-hard-kg-fusion-eval-v1.json --output .test-tmp/formowl-mail-domain-hard-kg-fusion-eval-v1-validation.json"
```

This rescore does not reparse the PST and does not use BERT or any neural
package. It is a candidate-only graph-structure experiment over existing
observations; the current implementation has not yet integrated formal ontology
governance or canonical graph state.

Run the #21 ontology-guided non-BERT ablation over the same preserved
domain-hard work directory:

```sh
docker run --rm -e FORMOWL_RUN_FULL_PST_DOMAIN_HARD_ONTOLOGY_ABLATION_EVAL=1 -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_full_pst_domain_hard_ontology_ablation_eval.py --baseline-report .test-tmp/formowl-mail-domain-hard-case-baseline-v4.json --work-dir .test-tmp/formowl-mail-domain-hard-case-baseline-work-v4 --output .test-tmp/formowl-mail-domain-hard-ontology-ablation-eval-v1.json"
```

Validate the saved ontology ablation public report:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_full_pst_domain_hard_ontology_ablation_eval.py --validate-report .test-tmp/formowl-mail-domain-hard-ontology-ablation-eval-v1.json --output .test-tmp/formowl-mail-domain-hard-ontology-ablation-eval-v1-validation.json"
```

The ontology arm is a candidate-only ablation. It validates formal ontology
contract usage and a revision hash, but it does not claim completed ontology
governance, canonical type writes, canonical KG writes, raw access, wiki
projection, business answer generation, or production readiness.

Run the historical #21 local-compatibility stdio attachment preflight package:

```sh
python scripts/mail_upload_chatgpt_connection_preflight.py --output /tmp/formowl-mail-upload-chatgpt-connection-preflight.json
```

This preflight proves the local compatibility command can be packaged without
exposing environment values, local paths, upload
locators, parser controls, storage controls, or backend internals in its public
report. A bounded local compatibility test may use the stdio command
`formowl-semantic-mcp-jsonrpc` and operator-supplied local values for
`FORMOWL_DATA_DIR`, `FORMOWL_MCP_SESSION_ID`,
`FORMOWL_MCP_ACTOR_USER_ID`, `FORMOWL_MCP_WORKSPACE_ID`, and
`FORMOWL_MAIL_UPLOAD_EXPIRES_AT`. This is not the formal connected path. The
live test must use the public HTTPS `/mcp` resource, FormOwl OAuth, and Google
OIDC as specified in `docs/closed-beta-runbook.md`.

Run the historical #21 result-packet intake after a manual local-compatibility test:

```sh
python scripts/mail_upload_chatgpt_result_intake.py --input /tmp/formowl-chatgpt-result-packet.json --output /tmp/formowl-mail-upload-chatgpt-result-intake.json
```

The input packet must be a bounded operator summary of the ChatGPT MCP session:
hashes, statuses, counts, expected `initialize` / `tools/list` /
`tools/call open_upload_session` sequence, task-card shape hashes, and explicit
attestation that raw ChatGPT detail payloads, environment values, upload
locators, and mail payloads were excluded. Do not paste raw ChatGPT transcripts,
PST contents, upload session IDs, local paths, or environment values into the
packet.

Run the historical #21 mail-evidence result-packet intake after a manual
fixture-backed local-compatibility evidence-reading smoke:

```sh
python scripts/mail_evidence_chatgpt_result_intake.py --input /tmp/formowl-mail-evidence-chatgpt-result-packet.json --output /tmp/formowl-mail-evidence-chatgpt-result-intake.json
```

The input packet must be a bounded operator summary of the ChatGPT MCP session:
hashes, statuses, counts, the expected `initialize` / `tools/list` /
`query_mail_evidence` owner/denied / `answer_mail_case_progress` owner/denied
sequence, fixture-smoke contract hashes, owner citation counts, denied
redaction counts, and explicit attestation that raw transcripts, raw tool
payloads, mail text, concrete mail identifiers, environment values, upload
locators, paths, SQL, and parser/storage/worker internals were excluded. Do
not paste raw ChatGPT transcripts, mail body/snippet text, concrete bundle or
message IDs, local paths, SQL, or environment values into the packet.

## Repository Skills

Reusable Codex workflow skills live under `.agents/skills/` so Codex can
discover them as repo-scoped skills when launched from this repository.
Available repo skills include `$harden-completed-slice-tests` for strict
completed-slice test hardening and `$use-agy-antigravity` for the historical
Antigravity `agy` workflow and bounded delegation rules. The 2026-08-05 Herdr
authorization is temporarily dormant as of 2026-08-11 because the `agy` quota
is exhausted; do not assign `agy` as a worker, reviewer, implementation
subagent, UAT agent, or coordinator until the user explicitly re-enables it. The canonical
tracked Antigravity skill file is
`.agents/skills/use-agy-antigravity/SKILL.md`; keep KG `agy` authorization,
reviewer, bounded write-delegation, MCP-route probe, and disablement notes
there so they travel with Git.

To use the same skill on another host, copy the repository with its `.agents`
directory intact, start a new Codex session from the repo, and confirm the skill
appears in `/skills`.

## Agent Goal Registry

Durable multi-agent goals live under `docs/agent-goals/`. These files make
long-running objectives portable across sessions and machines:

- `docs/agent-goals/kg-research-agent.md`
- `docs/agent-goals/system-backbone-agent.md`
- `docs/agent-goals/handoff-log.md`
- `docs/agent-goals/reviewer-gate.md`
- `docs/archive/README.md` - `immutable-history` index for lossless dated
  snapshots of completed board, goal, and handoff detail. It is consulted on
  demand and is not part of the default agent startup sequence.

Use `docs/implementation-task-breakdown.md` for checkbox task completion and
`docs/agent-goals/` for current objective, scope, blockers, status, and handoff
state. Active files are bounded: the board retains every unchecked item,
current phase summaries, and up to five recent completion summaries; role goals
retain role/objective/status/blockers/next action; handoffs retain 14 days and
at most 300 lines. The lifecycle labels are `active`, `active-blocked`,
`complete`, and `immutable-history`; detailed rules live in
`docs/agent-goals/README.md`.

Install and run pre-commit checks from inside the dev container:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "pre-commit run --all-files"
```

The pre-commit suite checks credentials/secrets, merge conflict markers, large files, text whitespace, Python/JSON/TOML syntax, Python lint/format with Ruff, and Python unit tests. Host-side Python may be used for quick local inspection, but container results are the completion baseline.

The default commit-time secret checks include the lightweight local credential scanner and Gitleaks. For a deeper audit, run the manual secret scans:

```sh
pre-commit run gitleaks-history --hook-stage manual
pre-commit run trufflehog-history --hook-stage manual
```

The dev container installs Gitleaks for commit-time scanning. TruffleHog remains manual because it is heavier; this repo runs it with verification disabled so the scan stays local.

## MCP JSON Line Compatibility Entry Points

The legacy Python MCP server modules still accept one JSON request per stdin
line and print one JSON response per line for local compatibility testing only.
Packaged console scripts use explicit compatibility names:
`formowl-project-mcp-jsonline-compat` and
`formowl-wiki-mcp-jsonline-compat`. The FormOwl gateway package provides the
JSON-RPC compatibility wrapper for existing MCP server objects and semantic
gateway tools; Project/Wiki behavior is preserved through transport tests.

`formowl-semantic-mcp-jsonrpc` is likewise a hand-built local compatibility
runner. None of these commands is an approved connected ChatGPT authentication
or identity-selection path; connected clients use the public HTTPS `/mcp`
resource and FormOwl OAuth 2.1.

Project MCP compatibility example:

```sh
formowl-project-mcp-jsonline-compat
```

Request:

```json
{
  "tool": "get_work_item_context",
  "arguments": {
    "source_ref": {
      "source_system": "openproject",
      "source_type": "work_package",
      "source_id": "123"
    },
    "include_comments": true,
    "include_activities": true,
    "include_relations": true,
    "include_attachments": true,
    "create_evidence_snapshot": true
  }
}
```

Wiki MCP compatibility example:

```sh
formowl-wiki-mcp-jsonline-compat
```

Set `FORMOWL_DATA_DIR` to control evidence, draft, snapshot, and tool-call log storage. The default is `.formowl/data`.
