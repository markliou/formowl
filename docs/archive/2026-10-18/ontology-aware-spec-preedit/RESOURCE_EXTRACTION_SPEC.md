# Resource Extraction Specification

## 1. Purpose and Authority

The Resource Extraction Layer converts registered heterogeneous sources into
source-preserving, citeable Observations and optional reviewable semantic candidates.

It is the evidence boundary beneath graph governance, strong RAG, graph-guided
retrieval, deterministic execution, and projections. It does not decide
canonical truth and it does not generate definitive business answers as a side
effect of parsing.

This specification applies to mail, documents, standalone spreadsheets/XLSX,
tables/databases, images, speech, non-speech audio/music, video, and connected
business systems. Native structure and modality are preserved; mail is the
first diagnostic fixture. Product requirements do not establish adapter support.

The layer may produce:

```text
Asset and AssetOccurrence metadata
ExtractorRun
Observation
SemanticMetadata
CandidateMention
CandidateBusinessObject
CandidateAtom
CandidateRelation
CandidateFrame
ExtractionWarning
ExtractionError
source-completeness evidence
```

The **2026-10-15** requested UAT answer model is `gpt-6-luna` with
`reasoning_effort=high`; runtime/provider verification and browser acceptance
remain pending. This does not change extractor, embedding, or worker model roles
or authorize re-extraction. See [SPEC §8.1.1](SPEC.md#811-development-worker-tier-and-metadata-recording)
for the separate development worker policy and recovery authorization.

It must not directly write:

```text
CanonicalGraphStore
canonical type or ontology state
UserKnowledgeGraph revisions
WikiRevision
external business-system state
```

FormOwl does not intend to train neural networks as its product method.
Existing parsers, OCR, ASR, embedding, vision, and LLM tools may be wrapped as
replaceable adapters. Their output remains source-derived observation or
candidate material, never truth or authorization by itself.

---

## 2. Non-Negotiable Principles

### 2.1 Registered source first

Every source must already be registered as a governed `Asset`, captured through
a governed `EvidenceSnapshot`, or represented by an equivalent source-system
capture before extraction starts.

Extractors receive stable FormOwl identifiers such as:

```text
asset_id or evidence_snapshot_id
source_ref and source occurrence
object_uri or governed external locator
workspace, owner, project, customer, and grant scope
permission_scope
retention policy
ingestion profile
```

They do not receive caller-controlled NAS paths, database credentials, object
store administration, parser commands, or worker scratch paths as public
identity.

### 2.2 Raw source and occurrence preservation

Raw resources or governed source captures remain the evidence authority.
Derived metadata, text, OCR, transcripts, captions, summaries, embeddings, and
graph candidates are rebuildable artifacts.

Observations retain text, structured values, or governed references to native
binary regions/intervals. OCR/transcripts/descriptions have separate provenance,
accuracy, and coverage limits; they cannot alone verify visual, acoustic,
musical, or motion-dependent claims. Native evidence remains usable without
ontology annotation or graph match.

Deduplication may reuse bytes or normalized content, but it must not erase
source occurrences. The same message, file, attachment, row, or event appearing
in multiple exports, folders, accounts, or systems retains each occurrence and
its permission lineage.

### 2.3 Deterministic and semantic extraction are separate

Deterministic extraction includes:

```text
content hash and size
MIME and container metadata
source identifiers and occurrence coordinates
page, table, row, cell, bbox, timestamp, or message locators
file and response structure
stable normalization where unambiguous
```

Semantic extraction includes:

```text
entity and alias candidates
claim and relation candidates
state, event, and coordination-frame candidates
risk, decision, request, commitment, owner, deadline, and dependency candidates
image or scene descriptions
ambiguous time or identity interpretation
```

A deterministic output may default to no review when its parser contract is
satisfied. A semantic output normally requires review.

### 2.4 Candidate before canonical

Semantic adapters may emit `SemanticMetadata` and candidate graph records.
They cannot commit canonical graph or ontology state. Candidate confidence,
embedding similarity, LLM certainty, or type compatibility never grants
permission or merge authority.

### 2.5 Source completeness before methodology claims

Graph ranking and answer generation cannot compensate for missing source
content. Before methodology-quality comparison, each adapter must reconcile an
authorized Observation manifest against an independent raw-source or
source-system inventory.

Every missing unit is classified as:

```text
policy redaction
unsupported source feature
extractor failure
normalization loss
deduplication or occurrence-lineage loss
unknown unexplained loss
```

Only intentional policy redaction may be absent without failing source
completeness. Reconciliation covers authorized source occurrences and native
features needed for the claim, including formulas/types/display semantics and
media regions, not counts of chunks, annotations, graph nodes, or indexed hits.
Missing derived graph/ontology/index state is distinct from missing source
content. Unexplained loss blocks the source-completeness gate.

Public redaction must consume the complete unsafe span recognized by its
existing detector, including path roots and Unicode suffixes, while preserving
safe surrounding source text. The final unsafe-content guard remains fail-closed;
no allowlist, question-specific exception or raw-source rewrite is implied.
Accidental whole-paragraph erasure is evidence loss, not intentional policy
redaction or proof of absence. Attachment version0.6.2 records the
changed persisted output: a new governed offline job/source revision is required,
not query-time repair, mutation of old runs/pins, or silent reuse as new policy.
Content hash, source/run/permission bindings and native locators remain required.

---

## 3. Core Data Model

### 3.1 Asset and source occurrence

An `Asset` identifies governed content or a governed external source object.
An `AssetOccurrence` identifies where and under which scope that content
appeared.

Byte identity, source occurrence, ownership, permission, and canonical entity
identity are separate.

Minimum source metadata:

```text
asset_id or evidence_snapshot_id
source_ref
source family and source-native type
source occurrence ID
content or response hash
captured_at
owner and workspace scope
permission_scope
retention and lifecycle state
stable FormOwl locator
```

Issue #41 owns the generic Asset tenant, owner, storage, occurrence, retention,
purge, transfer, and authorization boundary. A source adapter must not create a
parallel asset system.

### 3.2 ExtractorRun

Each adapter execution creates an immutable `ExtractorRun` record:

```text
extractor_run_id
asset_id or evidence_snapshot_id
extractor name, version, category, and adapter revision
input and source-manifest hashes
configuration and policy hashes
model, prompt, tokenizer, and package revisions when applicable
worker and container image fingerprint
started_at and completed_at
status
warnings, errors, and retry lineage
output manifest hash
```

Re-extraction creates a new run. Earlier runs and their outputs remain
historically resolvable.

### 3.3 Observation

An `Observation` is the smallest independently locatable and citeable unit
produced by an extractor.

Minimum fields:

```text
observation_id
asset_id or evidence_snapshot_id
source_ref and source occurrence
extractor_run_id
observation_type
source family and modality
raw extracted value
normalized value, when applicable
source-native location
captured_at and observed_at
source time fields where available
permission_scope
confidence
warnings and requires_review
content hash
```

An Observation may contain text, structured values, or a safe reference to
native binary content. Native content references preserve regions, cell ranges,
or time spans and any transformation metadata. It is evidence, not a canonical
fact. Source-native observations support authorized retrieval and structured
execution independently of semantic annotation or graph admission.

### 3.4 SemanticMetadata and candidate knowledge

`SemanticMetadata` records a model- or rule-derived interpretation of one or
more Observations. Candidate graph records express possible business objects,
properties, relations, states, events, and coordination frames.

Every semantic or candidate record includes:

```text
source_observation_ids and occurrences
source_refs and evidence snapshots
extractor or generator metadata
prompt, model, and schema revision when applicable
candidate type or assertion family
raw and normalized values
confidence and score components
permission_scope
ontology revision used for interpretation
review state
```

Candidate output may be accepted, corrected, split, merged, rejected, deferred,
or superseded only through the graph-governance workflow.

Cardinality is zero-to-many: each source document and each Observation may
produce no semantic annotation, or any number of source-addressed
`SemanticMetadata`, candidate atoms, candidate entities/business objects,
relations, and frames. A candidate may bind multiple Observations, but it
retains every contributing Observation ID and source occurrence. Neither an
adapter nor an ontology may impose one annotation per document or Observation.
Ontology may constrain and compress relation vocabulary, arity, and allowed
edge shapes; it does not cap source-addressed candidate cardinality or erase
distinct occurrences to reduce graph complexity.
No annotation, type mapping, or graph entry is required to admit otherwise
authorized evidence. Missing annotations or unmatched graph nodes never prove
source absence; reviewed KG identity/relation overlays keep evidence links.

### 3.5 Source-completeness artifact

Each methodology-bearing source snapshot produces a completeness artifact that
binds:

```text
source inventory or oracle manifest
authorized Asset/EvidenceSnapshot manifest
ExtractorRun manifest
Observation manifest
source-unit and Observation counts
loss taxonomy and counts
policy-redacted count
unsupported count
unexplained count
adapter, code, package, and image revisions
execution fingerprint
```

The artifact exposes safe hashes and counts publicly. Raw oracle answers,
private source content, paths, credentials, and parser internals remain outside
public reports.

---

## 4. Adapter Contract

A conceptual adapter interface is:

```python
class ExtractorAdapter(Protocol):
    def name(self) -> str: ...
    def version(self) -> str: ...
    def supported_source_families(self) -> list[str]: ...
    def supported_mime_types(self) -> list[str]: ...
    def category(self) -> str: ...
    def extract(self, input: ExtractionInput, policy: ExtractionPolicy) -> ExtractionResult: ...
```

`ExtractionInput` contains governed references and policy, not user-supplied
infrastructure controls.

`ExtractionResult` contains:

```text
ExtractorRun
Observation records
optional SemanticMetadata and candidate records
warnings and errors
output manifest and completeness counters
no canonical write side effects
```

Adapters are versioned, deterministic for the same pinned inputs where their
underlying tools permit, and fail without partial canonical mutation.

---

## 5. Source-Family Requirements

### 5.1 Documents and PDFs

Expected observation types include:

```text
document title and metadata
heading and heading path
paragraph and list item
page block and footnote
table, row, and cell range
caption, formula, and embedded-object occurrence
```

Preserve page, section, paragraph, table, cell, bounding-box, and reading-order
locators. Scanned and text PDFs remain distinguishable.

Representative adapters may wrap Docling, Unstructured, Apache Tika, PyMuPDF,
pdfplumber, `python-docx`, `python-pptx`, or `openpyxl`.

### 5.2 OCR and images

Expected observation types include:

```text
image technical metadata
ocr block, line, and word
image text region
visual caption candidate
diagram or chart element candidate
```

Preserve page/image ID, bounding box, OCR language, confidence, orientation,
and model/parser revision. AI-generated descriptions are explicitly marked as
model-generated candidates.

Retain a governed native image/region reference, crop coordinates and any
transformation lineage. OCR text does not exhaust an image, chart, or diagram.
Visual claims require authorized source-region inspection; unsupported native
access is disclosed rather than treated as a successful text-only interpretation.

Representative tools include Tesseract, PaddleOCR, EasyOCR, Docling OCR,
ExifTool, and governed vision-model adapters.

### 5.3 Speech, non-speech audio/music, and video

Expected observation types include:

```text
transcript segment
speaker segment
word timestamp
native audio/music interval and track/channel occurrence
non-speech acoustic or musical interpretation candidate
audio event candidate
video scene
native clip/keyframe reference and keyframe OCR
visual or screen-step candidate
```

Preserve track/channel identity, start/end time, speaker label and confidence
when applicable, scene/frame indexes, bounding boxes, audio/video technical
metadata, governed native references, and transformation lineage. Speech
transcripts do not represent nonverbal sound, music, visual content, or motion.
Native clips/frames must verify modality-dependent claims; ASR, captions,
scene descriptions, speaker identification, and musical interpretations retain
their own confidence, review state, and unsupported-feature disclosures.

Representative tools include FFmpeg, ffprobe, MediaInfo, Whisper or WhisperX,
pyannote, and PySceneDetect.

### 5.4 Standalone spreadsheets/XLSX, attachment tables, and databases

Expected observations include:

```text
workbook, sheet, table, and schema metadata
row and cell raw values, source types, and displayed values
formula text, cached results, and result/recalculation provenance when available
merged ranges, header paths, explicit blanks/nulls, and row associations
query or export snapshot occurrence
transaction or record occurrence
primary/business identifier candidates
```

Standalone spreadsheets/XLSX enter through the generic Asset boundary without
a mail dependency. Preserve workbook/sheet/table identity, cell coordinates,
row/column or record key, export/query revision, source-system timestamps,
types/precision/units and explicit blank/null semantics. Raw values, formulas,
cached results and formatted display are distinct evidence; a cached XML value
does not prove a freshly calculated formula result. Keep merged/header paths
and same-row association; inferred headers remain candidates until validated.

Deterministic lookup, filtering, joins, sorting, aggregation and counts use
validated native rows/cells/schema or a faithful revision-bound projection with
proved lineage/coverage. Cite cells/ranges and state which value representation
and calculation semantics the operation uses. Graph properties, generated
summaries and top-k chunks cannot substitute for source values. Unsupported
formulas/types/display features, ambiguous headers, incomplete rows or redacted
ranges weaken or block exact claims. A row or cell is evidence; it does not
directly become a canonical entity or relation.

### 5.5 Calendar, ticket, project, and business systems

Expected observations include source-native event, record, comment, status,
assignee, participant, relation, and change-log occurrences.

Preserve the source event or revision identity, actors, timestamps, current and
historical state, attachments, and permission scope. Adapter-local labels map
to shared ontology candidates without losing the original source type.

### 5.6 Mail and archive sources

Mail follows the same generic boundary:

```text
UploadSession or governed source capture
  -> Asset and archive occurrence
  -> IngestionJob
  -> mail ExtractorRun
  -> source-preserving mail Observations
  -> normalized MailEvidenceBundle or equivalent evidence view
  -> downstream indexes and candidate extraction
```

PST, OST, MSG, EML, and MBOX are import carriers. The adapter preserves:

```text
archive and mailbox occurrence
folder occurrence
message and thread occurrence
sender, recipient, participant, and actor-role evidence
subject, authored body, quoted, forwarded, and embedded spans
sent, received, asserted, and effective time
attachment and table occurrence plus origin lineage
message fingerprints and source identifiers
reply, quote, forward, correction, conflict, and supersession candidates
permission scope and extractor provenance
```

Quoted or forwarded text is not automatically promoted to a distinct message
record. It remains a quoted-message candidate until reliable matching or review
resolves it.

Deduplication may reuse message bodies or attachment bytes, but every archive,
mailbox, folder, message, and attachment occurrence remains recorded.

A mail adapter may parse and normalize mail observations. It must not:

- watch or mutate user folders directly;
- create a separate mail-only ingress or permission model;
- expose mail paths, credentials, parser scratch, SQL, or object-store details;
- create canonical graph/type state;
- answer case-progress questions as a parsing side effect; or
- publish wiki or external-system state.

The JSON-backed fixture adapter and bounded PST adapter are conformance and
diagnostic implementations of this contract. They do not establish universal
mail parser or methodology readiness.

---

## 6. Location and Temporal Metadata

Use the most precise source-native locator available:

```text
page
section and heading path
paragraph or block index
table, row, column, and cell address
bbox
start_sec and end_sec
frame and scene index
speaker
byte or character offsets
source revision or event sequence
message, thread, folder, and attachment occurrence
calendar occurrence
ticket or work-item event ID
database table/export and record key
URI fragment or governed source locator
```

Time fields remain distinct:

```text
captured_at
observed_at
asserted_at
effective_at
valid_from and valid_to
due_at
superseded_at
```

Ambiguous source time is preserved as raw text plus a normalized candidate,
precision, inference rule, and confidence. Extraction does not silently turn
`TBD`, `next month`, or a date without a year into a precise fact.

---

## 7. Confidence, Warnings, and Failure

Every output supports:

```text
confidence
requires_review
warnings
errors
```

Representative warning codes include:

```text
partial_extraction
unsupported_source_feature
ocr_low_confidence
asr_low_confidence
speaker_uncertain
table_structure_uncertain
formula_result_unverified
native_value_semantics_unsupported
native_media_access_unsupported
time_normalization_uncertain
quoted_message_unresolved
attachment_skipped
model_generated_description_requires_review
permission_redaction
source_occurrence_unresolved
```

A failed adapter run records failure and produces no successful canonical side
effect. Partial observation output is allowed only when the run explicitly
records partial status, exact output manifest, missing-source taxonomy, and
claim limits.

Known attachment parser exclusions are handled per child, not as successful
extraction: the existing materializer may retain a failed child Asset/ExtractorRun
for bounded byte/table/cell limits and explicit generic, XLS, PDF parsing/text
extraction, or PPTX parsing failure codes. The parent may finish processing only
with `attachment_child_extraction_incomplete`, the original error codes, and
`partial_extraction`; failed-child content is not successful evidence. Downstream
consumption still requires the existing bound failure-exclusion contract where
applicable. Unknown/mixed errors, exceptions, and invalid source/hash/permission
bindings still fail; no wildcard error suppression or relabelling is allowed.
Retries use new batch/run identities and preserve previous failed ledgers.
This diagnostic implementation remains **待測** for real-source UAT acceptance.

---

## 8. Tokenization, Indexing, and Retrieval Boundary

Extraction produces source-preserving text, structured and native-media
Observations. Modality-appropriate retrieval indexes are derived projections;
text lexical/dense retrieval is one branch. Spreadsheet access uses native
schemas/coordinates, image retrieval verifies regions, audio/music verifies
intervals, and video verifies scenes/clips/frames. Actual adapter/model/index
capabilities and revisions must be discovered; unsupported branches remain
explicitly unsupported/incomplete, never source absence.

The active target tokenizer/profile is:

```text
jieba_sentencepiece_frozen_profile_candidate_admission_v1
```

The index builder, not the source parser, owns tokenization and embedding
projection. Changing the tokenizer or embedding profile should re-index
existing authorized Observations without reparsing raw sources or rewriting
observation content.

Required index rules:

- query and evidence use the same immutable profile fingerprint;
- protected identifiers are preserved before segmentation;
- permission filtering occurs before candidate materialization;
- index rows bind Observation, profile, model, policy, and revision IDs;
- old index revisions remain rollback-capable;
- no silent ASCII-regex, substring, stale-index, or unpinned-model fallback;
- indexing does not create canonical graph writes.

The query-independent offline batch contract is [SPEC §11.1](SPEC.md#111-query-independent-offline-batch-indexing--待測).
Reuse the existing PostgreSQL JSONB Observation owner/pgvector baseline; the
recovered UAT stores remain file-backed. Existing SQLite derivatives persist
sealed reference/occurrence/attachment-parent and document neighbor locators,
not source truth. Admitted keyed artifacts support mail and independent real
PlainText/Markdown extraction paths without request-time tail scans or
`list.index`; selected source/hash/job/revision/permission/native locators are
revalidated within existing caps. Native rows/cells stay with their existing
sealed owner. Shortlists/misses remain incomplete; coverage separately reports
unsupported extraction, parse failure, truncation and unavailable projections.
This slice is 待測, not live document coverage, full RAG or source completeness.

Strong RAG and graph-guided retrieval consume the same Observation snapshot.
Graph or ontology ranking cannot hide source-completeness failure.
Activated lexical/dense index revisions and provider manifests are persistent
derived projections reused by request handling. A prompt must not trigger
re-extraction, re-embedding, KG construction, or index construction inline.
Under the 2026-10-06 rule in `SPEC.md` §7.3.1, validated `evidence_lookup`
with a nonempty validated requested-field set and **all** fields lacking
verified support triggers one materially different, same-authorized-scope
bounded source recheck when existing safety/eligibility and remaining budgets
permit, even with unrelated citations. Partial misses must be disclosed and
must not trigger this automatic recheck. An empty field set is not vacuously
all missing: use the existing validated evidence-need plan
or clarify. A source-backed explicit blank counts as verified coverage;
citation count or status alone cannot trigger recheck. Feature remains **待測**.

For a protected identifier plus a requested field, the retrieval contract first
performs a typed exact lookup against the current authorized source schema.
Bounded validated expansion may recover through the applicable source-native
strong-RAG branch, lexical+dense for text, under the existing contracts.
A provider timeout/error is an
operational failure and must not be reported as no source evidence or a
definitive absent value.

The agent, not the MCP tool, owns query enrichment. When the request needs
intent, identifier, field, source, or schema resolution, the agent must form an
expanded and schema-validated query before the first tool call. Each follow-up
call is another validated refinement or expansion after inspecting the prior
result and coverage. This is a bounded iteration under the request's pinned
budgets, not an unbounded retry and not a reason to rebuild the KG or index.
Safe per-phase and per-iteration timing/outcome traces are retained with the
request fingerprint without exposing raw source or infrastructure details.

Authorized direct retrieval and native structured execution need no matching
graph node/edge or ontology annotation. Optional graph/ontology signals retain
source evidence for every contributing hop. Bounded source context may include
adjacent paragraphs/headings, headers/cell ranges, image crops or media clips;
revalidate source occurrence/hash/revision/lineage/permission/native locator and
remaining budgets. Snippet grants do not grant whole assets. These reads reuse
valid sources/projections without inline extraction, re-embedding or rebuild;
automatic recheck still obeys §7.3.1, and its mail/text `16 KiB` presentation cap
is not a universal native-media context limit or capability proof.

### 8.1 Current adapter evidence and gaps

This is a product/extraction contract clarification, not implementation,
native-media acceptance or methodology completion. [SPEC §14](SPEC.md#14-current-implementation-and-methodology-status)
records current slices:

| Adapter slice | Current evidence and limit |
| --- | --- |
| Mail and independent text | Diagnostic mail and real `PlainTextObservationExtractor` for Markdown/plain-text; live §7.3.1 acceptance remains open. |
| `AttachmentDocumentExtractor` | Bounded XLSX/XLSM, XLS, native-text PDF, DOCX/PPTX, plain text/Markdown and CSV/TSV parsing. XLSX preserves raw/cached/formula/date/precision/blank metadata and coordinates where available; merged-header paths are candidates. It does not recalculate formulas or guarantee display/style/unit/null semantics or whole-workbook proof. XLS formula identity and scan-only PDF/OCR remain unsupported. Parser tests do not establish standalone-document/live UAT or activated RAG coverage. |
| `FixtureOcrExtractor` | `read_text()` page/bbox fixtures; no real-image OCR, visual retrieval or native-region proof. |
| `FixtureAudioTranscriptExtractor` | `read_text()` timestamp/speaker/transcript fixtures; no real decoding/ASR, acoustic verification or non-speech/music path proof. |
| `FixtureVideoSceneExtractor` | `read_text()` scene/keyframe descriptions; no real decoding, temporal/visual retrieval or native-clip/frame proof. |

Parser capability, query-path capability and activated source coverage are
separate evidence. The deployed bounded source-start path indexes and rehydrates parsed
attachment `paragraph`/`heading`/`list_item` content under `mail`, with genuine
parent/child/run/hash/revision/permission and native-locator checks; an attachment
does not become an independent document. Independent Markdown/plain-text stays
`document_text`. The attachment-inclusive lexical surface policy requires a
matching new offline artifact; an older attachment-omitting artifact or clone
cannot acquire that coverage from a code deployment alone.

The 2026-10-12 bounded integration targets native-table field retrieval, DOCX
attachment content and a standalone clause. Existing exact-cell tests verify
source-provided column labels, same-row constraints, explicit blanks and partial
coverage; the executor currently exposes `extracted_cell_text`, not complete
spreadsheet calculation semantics. UnitPrice/Quantity retrieval is a bounded
target, not aggregation, currency math or latest-revision completeness proof.
At the 2026-10-12 checkpoint, r12/new partial source runs on live8089, full252/drift0;
candidate8096 was deployed/proved, then removed at19:35:25Z. Old r5 remains
stopped/preserved for rollback. Earlier
fixed2048 r2/prep-r3 success did not preserve all text: the safe audit proved a
successful PDF run's three paragraphs were erased by redaction, not source absence.
R11 span-consumer repair leaves detector/final guard unchanged; output version0.6.2
required a NEW same2048/all-formats replay, not a query-time fix or old-run mutation.
R3 completed18:57:38Z/EXIT0,622,631 Observations/7,211 runs; prep-r4 completed
19:18:55Z/EXIT0. Pin `5e222fc…` has1,100,143 references/407,401 helpers/
10,671,080 postings, zero independent-document helpers, partial coverage.
Admission verified one successful native PDF run and three preserved indexed hits.

R11 exact252+34 passed108/108,170.274s/EXIT0, zero failures/errors/skips and
three scoped agreements; worker26/26 and original red/fixture failures retained.
Fixture-r11 EXIT0 PDF/independent-document cue/citation/lifecycle remains diagnostic:
six responses incomparable, missing deployment/code/build; four-attempt business
turns retained three. R12 retention derives from unchanged cap6, local19/19,
final focused117/117,174.049s/EXIT0, zero failures/errors/skips, exact252+34
pre/post/current inventory checked and Hypatia/Archimedes/Lagrange scoped AGREE3/3.
Active serving manifest is r12; extraction remains the recorded r11/version0.6.2 job.

Candidate source crosswalk passed19:26Z: both original-attachment citations
reopened/hash/run/parent checked; requested-delivery column visually verified,
not PO/approval dates, shipment or latest supplier schedule. Unrelated attachment
paragraph/native hash proof is not independent-document registration proof.
Live Chromium LAN EXIT0/all four comparable, delivery and unrelated attachment
each MCP1/provider2/citation1, chat/reload/reset pass; evidence coverage stays partial.
First live citation reopen failed
`ContractValidationError: ingestion revision completed job changed`.
Once-only instrumentation then passed the unchanged original loader/guards;
all three job digests agreed across engines, both LIVE citations reopened/hash/
run/parent checked. Archimedes scoped AGREE supports this observed source-correct
answer in the real LAN webpage. The first failure remains preserved/unexplained
and blocks stability/reproducibility acceptance, not the demonstrated answer;
no mutation/corruption/root-fix, full-UAT or source-completeness claim.

Canonical authority-resume4: valid=true/ready=false/errors=[]/EXIT0;
feature待測/four methodology gates stay blocked. Trusted diagnostic bindings are
not remote attestation, source stability or retrospective repair of unbound records.
See [SPEC §14](SPEC.md#14-current-implementation-and-methodology-status) and the
[dated handoff](docs/agent-goals/handoff-log.md) for exact pins and preserved failures.

MIME/modality declarations and fixture locators cannot establish native support.
These limits leave source coverage explicit while preserving the wider product
requirements, frozen method/tokenizer, strong RAG control and issue #56 gates.

---

## 9. Model and LLM Boundary

Model roles are separate:

```text
semantic/candidate extraction
entity or relation linking
embedding generation
reranking
query planning
final answer generation
```

An extractor run records the exact model, revision, prompt, schema, settings,
and package/container fingerprint when applicable.

No model may:

- infer permission from content;
- turn high confidence into canonical authority;
- build aliases or ontology mappings from the independent holdout;
- fill missing source content from pretrained knowledge;
- expose private content or hidden oracle data in public output; or
- silently broaden the source scope requested by a validated query plan.

The same final answer model and settings are used across comparison arms. A
candidate-generation model is not automatically the answer model.

When an LLM has low confidence about a user instruction, domain term, schema
concept, or MCP tool usage, it may consult redacted public-web information only
to disambiguate semantics, understand terminology or schemas, or propose a
candidate MCP tool-plan expansion. The resulting plan is not executable until
it is checked against the actual current MCP tool schema and current caller
permissions. Public-web context remains untrusted and separate from workspace
evidence and provenance; private source content, prompt details, identifiers,
values, secrets, and tool results must not be sent outward. Web material cannot
authorize access or writes, create canonical KG or ontology state, or replace
source-grounded deterministic exact execution and coverage evidence.

---

## 10. Re-Extraction and Rebuild Policy

Create a new `ExtractorRun` when:

```text
source content or source-system revision changes
extractor or parser version changes
configuration or extraction policy changes
model, prompt, tokenizer, or schema revision changes
permission or redaction policy requires a new visible output
operator requests governed regeneration
```

Do not overwrite prior runs by default. Preserve enough lineage to diff old and
new outputs and to reproduce projections that used older observations.

Selective rebuild boundaries are:

```text
raw source -> preserved according to retention policy
Observation -> rebuilt only through a new ExtractorRun
lexical/dense index -> rebuildable from authorized Observations
candidate graph -> rebuildable from Observations and pinned policies
canonical graph -> changes only through governed commits and lifecycle events
projection -> rebuildable from pinned evidence and graph revisions
```

These rebuilds are explicit offline or governed lifecycle operations. A query
miss, exact-lookup miss, provider retry, or answer request never starts a
per-query rebuild. Missing, unsealed, or unactivated retrieval projections are
distinct from an independently validated immutable source snapshot, not
independent permission to bypass `SPEC.md` §7.3.1 eligibility. Eligible
same-authorized Observation/source fallback may use that snapshot without the
failed projection, but retains authorized scope and source/hash/lineage/revision
checks and existing budgets. Invalid source bindings, permission/schema/provider
errors, and exact-query boundaries remain fail-closed. Incomplete scans and
timeouts are not absence; only proven complete source coverage can support a
scoped complete negative.

Under [SPEC §11.1](SPEC.md#111-query-independent-offline-batch-indexing--待測),
source/policy/extractor changes require explicit offline jobs and versioned
artifacts, not question-driven ingestion. Reopen/reuse validated batch artifacts;
legacy missing locator metadata stays unavailable, with no inline migration.
Offline clone mode preserves verified postings without retokenization and does
not fill missing lexical surfaces. Raw assets and prior source lineage remain
preserved; no new canonical store or schema service is introduced.

---

## 11. Storage and Security Boundary

Resource extraction may write through governed interfaces to:

```text
AssetStore
ObjectStore
ObservationStore
SemanticMetadataStore
Candidate stores
ExtractorRunStore
JobStore
index projection stores
```

PostgreSQL is canonical for metadata, provenance, permission, review, and graph
state. Raw and large binary payloads live behind an object-store abstraction.

Before extraction, object verification must bind the expected hash/size to a
complete, stable descriptor read and the still-current governed path/target.
Path replacement, symlink retargeting, detectable file mutation, short reads
and mismatches fail without invoking an extractor. Operator diagnostics retain
only same-call hash/count/stability/completion facts and safe reason codes;
never raw paths or exception text. Do not retry until a hash happens to pass,
repin source expectations, or present later verification as the failed call's
evidence. These guards do not by themselves explain historical inconsistent
digests or certify whole-source completeness.

Opt-in immutable object reuse in `scripts/issue56_attachment_backfill.py` remains **待測**.
`--preserve-existing-objects` selects the existing `FileObjectStore` policy; defaults are unchanged.
Reuse verifies the full byte hash/size and stored URI/backend/workspace identity,
then reuses existing metadata/filename unchanged, without payload or metadata writes.
Corrupt, incomplete or mismatched existing objects reject; normal verification/hash
algorithms and source checks are unchanged. New objects may still be created.
Cleanup uses only instance-created namespace receipts; valid reuse retains creation
receipts, invalid reuse revokes them. No broad concurrency/transactionality guarantee is made.
Opt-in binds to ledger inputs and extraction config/job identity; policy changes reject ledger reuse.
Canonical storage ownership, IDs, permissions and lineage remain unchanged;
no source/backend remap, alternate truth store or canonical KG writes are introduced.
Review/integration acceptance remains pending: this is not live deployment, complete
attachment coverage, source admission, launch readiness or browser acceptance.

Graph and projection records reference stable FormOwl identifiers:

```text
asset_id
source_ref and occurrence
observation_id
extractor_run_id
evidence_snapshot_id
candidate_id
graph_revision_id
ontology_revision_id
workspace_id
user_id
grant_id
```

Allowed public locators are governed references such as:

```text
formowl://asset/{asset_id}
formowl://observation/{observation_id}
formowl://evidence/{evidence_id}
```

Disallowed public fields include raw NAS, SMB, NFS, WebDAV, local scratch,
object-store, database, parser, worker, credential, SQL, and oracle internals.

---

## 12. Acceptance Criteria

Resource Extraction is aligned when:

1. every source enters through a governed Asset or evidence-capture boundary;
2. source occurrences and permission lineage survive deduplication;
3. deterministic metadata, Observations, semantic metadata, and candidate
   knowledge remain distinct;
4. every derived artifact pins extractor, policy, model, prompt, package, and
   source revisions as applicable;
5. heterogeneous adapters preserve native text/structure/media, locators and
   time semantics; text proxies cannot establish native-media capability;
6. source completeness is compared with an independent source inventory and
   unexplained loss fails the gate;
7. re-extraction creates a new run and never overwrites historical evidence;
8. tokenizer/embedding re-indexing can reuse authorized Observations without
   reparsing source content;
9. activated indexes and graph projections are reused by requests without a
   per-query rebuild; eligible validated index/graph misses preserve the same
   authorized source scope, and agent-expanded tool calls iterate only within
   pinned budgets;
10. semantic tools and LLMs remain replaceable candidate generators;
11. no extractor writes canonical graph/type, user graph, wiki, or external
    business-system state;
12. unannotated evidence remains retrievable, native table operations preserve
    formula/raw/cached/display/type/coordinate/row semantics and coverage,
    and bounded source context retains native citations and separate access checks;
13. public records expose only governed identifiers and safe summaries; and
14. canonical dev-container tests cover positive, partial, failed, denied,
    duplicate-occurrence, re-extraction, and leak-guard behavior.
