# Resource Extraction Specification

## 1. Purpose

The Resource Extraction Layer converts uploaded or registered resources into governed intermediate representations.

It should produce:

```text
RawResource
AssetMetadata
ExtractorRun
Observation
SemanticMetadata
DomainPackDefinition
CandidateBusinessObject
CandidateAssertion
CandidateAtom
CandidateMention
CandidateFrame
ExtractionWarning
ExtractionError
```

The Resource Extraction Layer must not directly write to:

```text
CanonicalGraphStore
UserKnowledgeGraph
WikiRevision
```

Instead, it should write to intermediate stores such as:

```text
AssetStore
ObjectStore
ObservationStore
SemanticMetadataStore
DomainPackStore
CandidateBusinessObjectStore
CandidateAssertionStore
CandidateAtomStore
CandidateMentionStore
CandidateFrameStore
ExternalGraphImportStore
ExtractorRunStore
JobStore
```

The purpose of this layer is to make multimedia resources searchable, citeable, reviewable, and reusable by downstream graph and wiki systems.

FormOwl does not intend to train neural networks. The goal is an extractor-adapter pipeline that can use existing parsers, OCR engines, ASR tools, vision models, and LLM-based structured extraction tools when needed. Neural-network-based tools may be used as replaceable external extractors, but they are not FormOwl's core source of truth.

---

## 2. Design Principles

### 2.1 Raw resources are the source of truth

Raw files must be preserved.

Derived metadata, observations, transcripts, OCR blocks, captions, summaries, and graph candidates are all secondary artifacts.

Every derived artifact must retain a reference back to the raw resource.

### 2.2 Extractors are replaceable adapters

FormOwl should not hard-code one vendor, model, or parser.

Each extraction tool should be wrapped as an `ExtractorAdapter`.

Example adapters:

```text
exiftool_metadata_extractor
mediainfo_metadata_extractor
ffprobe_metadata_extractor
docling_document_extractor
unstructured_document_extractor
tesseract_ocr_extractor
paddleocr_ocr_extractor
whisperx_asr_extractor
pyscenedetect_video_scene_extractor
llm_semantic_metadata_extractor
llm_candidate_graph_extractor
```

### 2.3 Deterministic extraction and semantic extraction are separate

Technical metadata extraction should be deterministic whenever possible.

Examples:

```text
file size
mime type
sha256 hash
codec
duration
resolution
EXIF
page count
document structure
```

Semantic extraction may use AI or LLM-based tools.

Examples:

```text
image description
speech transcript
speaker diarization
entity extraction
relation extraction
claim extraction
decision extraction
action item extraction
risk extraction
requirement extraction
candidate graph extraction
```

### 2.4 Extractor provenance is mandatory

Every extraction output must include:

```text
resource_id
extractor_name
extractor_version
extractor_type
run_id
started_at
completed_at
input_hash
config_hash
model_name, if applicable
model_version, if applicable
prompt_hash, if applicable
confidence, if applicable
warnings
errors
location metadata
```

### 2.5 Observations are not canonical knowledge

Observations are evidence-like intermediate records.

They may later support candidate business objects, candidate assertions,
specialized candidate atoms or frames, wiki revisions, summaries, or retrieval
results, but they are not the canonical knowledge graph.

---

## 3. Core Data Model

### 3.1 RawResource

A `RawResource` represents a registered source asset.

Raw resources must be registered through the central FormOwl asset catalog before extraction. Extractors should receive stable identifiers such as `asset_id`, `resource_id`, `storage_backend_id`, and `object_uri`, not uncontrolled NAS paths. Raw storage locations are adapter details behind the asset and object-store layers.

Example schema:

```json
{
  "resource_id": "res_001",
  "asset_id": "asset_001",
  "workspace_id": "ws_001",
  "project_id": "proj_001",
  "storage_backend_id": "storage_minio_001",
  "source_type": "uploaded_file",
  "original_filename": "meeting_recording.mp4",
  "mime_type": "video/mp4",
  "storage_uri": "object://resources/res_001/original",
  "object_uri": "object://resources/res_001/original",
  "sha256": "sha256:...",
  "size_bytes": 123456789,
  "created_at": "2026-06-17T10:00:00Z",
  "registered_by": "user_001",
  "owner_user_id": "user_001",
  "permission_scope": "workspace"
}
```

### 3.2 AssetMetadata

`AssetMetadata` stores technical metadata that can usually be extracted without neural-network-based tools.

Example schema:

```json
{
  "resource_id": "res_001",
  "metadata_type": "technical",
  "mime_type": "video/mp4",
  "duration_sec": 3120.5,
  "width": 1920,
  "height": 1080,
  "codec": "h264",
  "audio_codec": "aac",
  "bitrate": 4800000,
  "frame_rate": 30,
  "extractor_run_id": "run_001"
}
```

### 3.3 ExtractorRun

An `ExtractorRun` records one execution of one extractor.

Example schema:

```json
{
  "run_id": "run_001",
  "resource_id": "res_001",
  "extractor_name": "ffprobe_metadata_extractor",
  "extractor_version": "0.1.0",
  "extractor_type": "technical_metadata",
  "input_hash": "sha256:...",
  "config_hash": "sha256:...",
  "started_at": "2026-06-17T10:01:00Z",
  "completed_at": "2026-06-17T10:01:02Z",
  "status": "succeeded",
  "warnings": [],
  "errors": []
}
```

### 3.4 Observation

An `Observation` is a citeable extracted unit from a raw resource.

Examples:

```text
document paragraph
PDF page block
OCR block
table
image region
transcript segment
speaker segment
video scene
keyframe caption
wiki section
project issue comment
```

Example schema:

```json
{
  "observation_id": "obs_001",
  "resource_id": "res_001",
  "extractor_run_id": "run_002",
  "observation_type": "transcript_segment",
  "modality": "audio",
  "text": "We decided not to use a graph database in the first version.",
  "location": {
    "start_sec": 312.4,
    "end_sec": 319.8,
    "speaker": "speaker_02"
  },
  "confidence": 0.91,
  "permission_scope": "workspace",
  "created_at": "2026-06-17T10:05:00Z"
}
```

### 3.5 LogicalSourceItem and ContextBoundary

Observation chunking is an extractor concern. Evidence counting and ranking
use a separate source-neutral retrieval identity:

```text
LogicalSourceItem
- source_item_id
- source_identity_policy_id
- source family and source-defined identity
- source_version_id
- source observation ids
- modality-specific locator
- observed / recorded / known time when available
- context ids
- permission_scope_id
- source-version lineage
```

Typical logical source items include one authored message, PDF page or
section, presentation slide, spreadsheet row, OCR page/region group,
transcript utterance, video scene, project activity, wiki section, or
application event. An adapter may choose another source-defined unit when its
lineage and stability are explicit. Retrieval identity is the pair
`(source_identity_policy_id, source_item_id)`, not the local item string alone.
Every retrievable observation also carries a source-version id and
permission-scope id.

Several observations may belong to one logical source item. For example, a PDF
page may produce separate heading, paragraph, table, and OCR observations; a
slide may produce title, body, speaker-note, and image-caption observations.
Those observations may jointly support one query, but they remain one evidence
item for cardinality and IDF.

`ContextBoundary` is the authorized container or business scope around source
items. Examples include a document, presentation deck, mail thread, worksheet,
reporting period, inspection lot, contract, project, or case. Adapters must
emit enough stable lineage to select these boundaries without exposing raw
paths. A shared context never creates evidence or graph edges by itself.
Accessible contexts and selected query contexts are separate. If a caller can
access several periods, lots, decks, documents, or threads, retrieval must not
compare or union them until the caller selects the query context. Selecting
more than one query context also requires explicit cross-context comparison
authorization.

### 3.6 SemanticMetadata

`SemanticMetadata` stores structured meaning extracted from one or more observations.

Examples:

```text
entity
relation
claim
decision
action item
risk
requirement
deadline
owner
topic
dependency
open question
```

Example schema:

```json
{
  "semantic_metadata_id": "sem_001",
  "source_observation_ids": ["obs_001", "obs_002"],
  "metadata_type": "decision",
  "value": {
    "decision": "Do not use a graph database in the first MVP.",
    "rationale": "Per-user small graphs and frequent rebuilds are better handled with pgvector and lightweight graph reconstruction."
  },
  "confidence": 0.78,
  "extractor_run_id": "run_003",
  "requires_review": true
}
```

### 3.7 Candidate Knowledge

The source-neutral minimum candidate path is:

```text
Observation
  -> Lexical and Mention Candidates when text is present
       -> Unicode and script normalization
       -> protected ASCII identifiers
       -> Jieba
       -> corpus-bound SentencePiece
       -> frozen-profile candidate admission
  -> CandidateBusinessObject
  -> CandidateAssertion
```

This lexical path is the default for every text-bearing observation. File type,
department, and modality do not select different tokenizer methodologies.
Regex-only tokenization is restricted to explicit baseline or ablation runs,
protected ASCII identifier extraction within the default stack, or a reported
degraded fallback. A default evaluator or extractor must not silently fall back
to regex-only behavior.

Candidate batches and evaluation reports must bind the segmentation policy
version, candidate-admission policy hash, model or vocabulary hash, and corpus
hash. A binding change requires re-extraction or reevaluation.

### 3.7.1 Default Candidate Evidence Retrieval

Candidate retrieval uses the same source-neutral evidence contract for every
modality and every new hardness or harness evaluation:

```text
structured Unicode/protected-ASCII/Jieba/SentencePiece/frozen-profile binding
  -> exact admission, model, and corpus hash match
trusted access binding over observation / identity-policy / version / permission
  -> context/time/status admissibility
  -> universal query intent and evidence-cardinality planning
  -> logical-source conjunctive anchor support
  -> logical-source IDF and ranking
  -> minimal observation coverage within independent source/observation budgets
  -> optional contract-bound capped ontology rerank
```

The index must own a `CandidateEvidenceTextPolicyRuntime` that binds the
structured `CandidateEvidenceTextPolicyBinding` to the query tokenizer it
actually invokes. The binding carries Unicode NFKC/script normalization,
protected ASCII extraction, Jieba, corpus-bound SentencePiece, frozen-profile
admission, and exact admission/model/corpus SHA-256 hashes. It also pins the
runtime id and tokenizer implementation hash; runtime code mismatch fails
closed. Default callers provide query text only; they cannot attest compliance
by supplying raw tokens or a free-form policy hash. Missing, placeholder,
regex-only, mismatched, or caller-overridden bindings fail closed.
Experimental token or ontology transforms use the named `retrieve_ablation`
entrypoint and cannot remove runtime-produced default tokens.
Raw query text may identify control intent, evidence count, and chronology
syntax only. Retrieval anchors, actor/topic vocabulary, and supported content
terms must come from runtime-produced tokens or a named `retrieve_ablation`
extension; regex-parsed raw terms must never be added back.

A trusted access binding is mandatory. It pins eligible observation ids,
source-identity policy ids, source-version ids, and permission-scope ids.
Missing bindings fail closed. If an index-level and request-level binding are
both present, retrieval intersects them; the request cannot broaden the index.
The binding must be a real `CandidateEvidenceAccessBinding`; all four
eligibility collections are immutable `frozenset` values containing exact
nonblank strings. Cross-context comparison authorization must be an actual
boolean. Duck-typed bindings, mutable collections, string booleans, and other
truthy substitutes fail closed.
Those access axes, followed by context, `known_as_of`, `as_of_world_time`,
epistemic status, and lifecycle status, are applied before query tokenization,
ontology-signal resolution, support counts, IDF, planning, or ranking. An empty
admissible universe returns without invoking those query-dependent steps.
Observation chunk counts must not change retrieval results. Several
observations may cover different anchors only when they share the same logical
source identity; no shared token or context may create transitive closure
across unrelated items.

Evidence cardinality comes from source-unit syntax or classifiers, not a
department vocabulary. Explicit counts such as report, lot, page, row, slide,
event, or equivalent classifier phrases use the requested count. Digits inside
identifiers and values denoting time, money, percentages, or measurements do
not. An explicit count beyond the source budget fails closed rather than being
silently reduced. A governed upstream query parser may instead provide a
positive structured source-item count, allowing future languages and input
surfaces to reuse the same planner without a department-specific parser fork.

Chronology has separate `earliest`, `latest`, `range`, `before`, and `after`
modes. Range selection preserves the requested number of ordered logical
sources instead of always collapsing to two endpoints. Date-only boundaries
require an explicit query timezone and are converted to timezone-aware day
boundaries before comparing source instants. Missing timezone or source time
fails closed.

Primary retrieval evaluation stores stable logical-source ids as gold and
scores logical-source recall so a harmless re-chunking does not change the
pass/fail result. Evaluators must not reconstruct that primary gold from the
current Observation ids during scoring. Exact Observation citation recall,
precision, and stale/unmapped citation diagnostics remain separate metrics and
cannot fail an otherwise correct logical-source selection.

Optional evidence ontology facets are derived from `observation_type`,
`modality`, and explicit semantic field/value roles. PDF/PPT content, ERP/table
rows, audio/video transcripts, images, and application events retain distinct
evidence facets. Digits in an identifier are not measurement evidence;
measurement requires a role such as amount, quantity, rate, duration,
percentage, score, or unit value.

### 3.7.2 Task evidence assembly boundary

Source adapters emit observations and normalized evidence fields. They do not
decide which fields should dominate a user-facing answer.

Every source shape should expose the richest citeable content that its governed
extractor can support:

```text
mail                 -> body content plus separately named header metadata
PDF/TXT/document     -> paragraph, section, table, and semantic fields
CSV/XLS/XLSX         -> row content plus named cell or property fields
project/application  -> authored content, event content, and named state fields
image/audio/video    -> OCR, transcript, caption, event, and semantic fields
```

These mappings remain presentation-neutral. A mail adapter must not declare
sender or recipient to be more important than body content. A spreadsheet
adapter must not force every answer into a table. A PDF adapter must not decide
that filenames or page numbers replace paragraph content. The downstream
`ProjectionSpec` owns that decision.

The task-answering layer consumes these fields through:

```text
TaskFrame
  -> EvidenceRequirement
  -> CandidateEvidenceIndex
  -> permission-filtered selected logical source items
  -> all admissible observations for those selected source items
  -> EvidenceCoverage
  -> AnswerabilityDecision
  -> AnswerProjection
```

Retrieval keeps minimal supporting observation ids for citation and search
diagnostics. Evidence assembly may additionally read normalized fields from all
admissible observations inside the selected logical source item. It must not
cross permission, source-version, context, or selected-source boundaries.

The normalized default answer field is `content`. Header, participant,
filename, locator label, and source-system metadata are secondary unless an
explicit task asks for those fields. If no primary content is available, the
answering layer reports partial evidence; it must not silently substitute a
metadata-only card.

Evidence cardinality and presentation cardinality remain separate. Extractors
and adapters must not truncate evidence to a UI page size. The downstream
retriever reports total matching source items, returned source items,
`is_exhaustive`, and `has_more`; the projection independently reports how many
items are displayed on the current page.

`CandidateBusinessObject` identifies the proposed subject or object of
knowledge and maps its domain label to one closed core supertype.

`CandidateAssertion` expresses one of five universal semantic families:

```text
property
relation
state
event
coordination
```

Each assertion must preserve source observations, evidence spans, permission
scope, extractor run, normalized `TemporalContext`, epistemic status, assertion
lifecycle status, contextual semantics, ontology revision, Domain Pack id and
content hash, confidence, and review state.

The shared temporal vocabulary separates source, observation, assertion,
effective/world-valid, result, recorded/known, due, and supersession times.
Domain Packs may map local labels into these fields, but they may not add a
department-specific temporal pipeline. The shared epistemic vocabulary
distinguishes planned, expected, predicted, requested, committed, asserted,
observed, and actual assertions. A separate lifecycle field distinguishes
active, cancelled, corrected, and superseded assertions, so an actual fact can
also be corrected or superseded. Ordered timestamps must include an explicit
offset; date-only values remain calendar-day values.

`TemporalContext.captured_at` is pipeline-owned. The candidate extractor binds
it to the latest `Observation.created_at` among the assertion's source
observations, and stable candidate assertion ids include the resulting
temporal context. A Domain Pack may not forge an earlier source-capture time.
`CandidateAssertion.created_at` separately records candidate materialization.
It must not precede source capture, and `known_as_of` requires both source
capture/recording boundaries and candidate materialization to have occurred.
Materialization time is not part of semantic candidate identity, so a
deterministic rerun may retain the same candidate id while producing a later
materialization timestamp.

A `DomainPackDefinition` is a scoped vocabulary and mapping definition, not an
ontology bypass. Its normalized content hash is bound to a
`domain_pack_definition` Observation. Candidate business-object ids and
assertion ids pin that hash.

`CandidateAtom`, `CandidateRelation`, `CandidateMention`, and
`CandidateFrame` remain specialized candidate representations. They must not
be considered canonical until reviewed and committed by graph governance.

Regex-only retrieval, parser-chunk cardinality, lexical/thread transitive
components, and ontology hard-pruning remain explicit ablation or historical
baseline paths. They are not default candidate evidence retrieval and must not
be silently selected by an extractor, evaluator, or harness.

Example candidate assertion:

```json
{
  "candidate_assertion_id": "cassert_example",
  "assertion_kind": "state",
  "subject_candidate_business_object_id": "cbobj_invoice_example",
  "predicate": "payment_status",
  "value": "unpaid",
  "source_observation_ids": ["obs_invoice_row"],
  "extractor_run_id": "run_candidate_knowledge",
  "ontology_revision_id": "ontology_rev_candidate_core_v1",
  "domain_pack_id": "domain_pack_finance_v1",
  "domain_pack_content_hash": "sha256:<normalized-pack-hash>",
  "status": "pending_review",
  "requires_review": true,
  "metadata": {
    "canonical_write_allowed": false
  }
}
```

---

## 4. Extractor Categories and Recommended Tools

### 4.1 File registration and technical metadata

Purpose:

```text
file name
mime type
file size
sha256 hash
created_at
modified_at
duration
codec
resolution
bitrate
EXIF
IPTC
XMP
container metadata
```

Recommended tools:

```text
libmagic / file
SHA-256 hashing
ExifTool
MediaInfo
ffprobe / FFmpeg
```

These tools do not require LLMs or neural-network inference.

### 4.2 Document parsing

Target formats:

```text
PDF
DOCX
PPTX
HTML
Markdown
CSV
Excel
plain text
scanned PDF
```

Recommended tools:

```text
Docling
Unstructured
Apache Tika
PyMuPDF
pdfplumber
python-docx
python-pptx
openpyxl
```

Expected observation types:

```text
document_title
heading
paragraph
table
list_item
page_block
section
footnote
caption
formula
embedded_image
```

Document extraction should preserve locators:

```text
page number
section heading
paragraph index
table index
cell coordinate
bounding box, if available
```

### 4.3 OCR and image text extraction

Target resources:

```text
scanned PDF
image with text
screenshot
whiteboard photo
presentation screenshot
video keyframe
```

Recommended tools:

```text
Tesseract
PaddleOCR
EasyOCR
Docling OCR pipeline
cloud OCR adapter, optional
```

Expected observation types:

```text
ocr_block
ocr_line
ocr_word
image_text_region
```

Example location metadata:

```json
{
  "page": 3,
  "bbox": [120, 80, 640, 180]
}
```

### 4.4 Audio transcription and speaker metadata

Target resources:

```text
meeting recording
voice memo
podcast
interview
call recording
video extracted audio
```

Recommended tools:

```text
FFmpeg
WhisperX
Whisper
faster-whisper
pyannote.audio
```

Expected observation types:

```text
transcript_segment
speaker_segment
word_timestamp
audio_event
```

Example location metadata:

```json
{
  "start_sec": 312.4,
  "end_sec": 319.8,
  "speaker": "speaker_02"
}
```

### 4.5 Video scene extraction

Target resources:

```text
meeting video
screen recording
demo video
lecture video
field recording
```

Recommended tools:

```text
FFmpeg
ffprobe
MediaInfo
PySceneDetect
OCR on keyframes
vision model / multimodal LLM, optional
```

Expected pipeline:

```text
video file
-> technical metadata
-> audio track extraction
-> ASR / diarization
-> scene detection
-> keyframe extraction
-> OCR on keyframes
-> optional visual description
-> semantic metadata
```

Expected observation types:

```text
video_scene
keyframe
keyframe_ocr_block
visual_caption
screen_step
demo_action
```

### 4.6 Image semantic metadata

Target resources:

```text
photo
diagram
chart
screenshot
whiteboard image
scanned note
```

Recommended tools:

```text
ExifTool
OCR tools
vision model adapter, optional
multimodal LLM adapter, optional
```

Expected observation types:

```text
image_metadata
image_text_region
visual_caption
diagram_element
chart_description
```

AI-generated image descriptions must be marked as model-generated and reviewable.

### 4.7 Mail and PST ingestion

Mail archives should be ingested through a formal asset pipeline, not by a parser directly watching and mutating folders.

For Phase 1, the primary user path is direct upload through a session-bound
FormOwl upload surface / iframe. Local Companion import is optional, advanced,
or policy-triggered; it is not required for ordinary Phase 1 users. The two
parser locations must share one ingestion contract and emit the same
`MailEvidenceBundle` shape so downstream stores, retrieval, and MCP tools do
not fork by parser location.

Recommended flow:

```text
user creates UploadSession for PST, OST, MSG, EML, or MBOX import
-> user uploads full archive through the session-bound upload surface / iframe
-> archive enters ingest staging
-> compute archive sha256 and technical metadata
-> register immutable Asset metadata in PostgreSQL
-> create IngestionJob and mail import session
-> server-side worker leases job
-> worker parses incrementally from staging/local scratch
-> parser emits MailEvidenceBundle
-> PostgreSQL stores normalized mail evidence
-> raw archive is deleted or retention-controlled after successful extraction
-> semantic metadata, candidate graph, and KG projection are generated later
```

PST, OST, MSG, EML, and MBOX inputs are import carriers. For Phase 1, the
normalized mail evidence rows become the operational evidence layer after
successful extraction. Raw archives and attachment bytes stay in ObjectStore /
staging / retention-controlled storage, not PostgreSQL, and the raw archive is
not permanent default storage unless a legal, audit, or explicit retention
policy requires it. The parser must not directly mutate the canonical graph.
It emits a versioned `ExtractorRun`, a mail parse run, warnings/errors, mail
evidence rows, observations where the current implementation uses
ObservationStore, and attachment asset or attachment byte references required
by policy.

Recommended Phase 1 normalized mail evidence tables/contracts:

```text
mail_import_session
mail_archive_occurrence
mail_folder_occurrence
email_message
email_message_occurrence
email_body_segment
email_attachment
email_attachment_occurrence
quoted_message_candidate
embedded_message_relation
mail_parse_run
mail_parse_warning
```

Attachments should keep occurrence links back to the source message and source archive. Email deduplication must preserve occurrence because the same message or attachment may appear in multiple folders, exports, or user mailboxes.

Suggested email identity and fingerprint inputs:

```text
Internet Message-ID
MAPI EntryID or SearchKey
normalized subject
sender
sent_at
body_hash
body simhash
attachment hash set
source PST asset_id
folder occurrence
mailbox occurrence
```

Expected observation types:

```text
email_message
email_thread
email_header
email_body_segment
email_attachment_occurrence
mail_folder_occurrence
```

Logical email message modeling:

```text
top-level PST mail item -> email_message
embedded .msg / .eml / message/rfc822 attachment -> embedded email_message
quoted or forwarded body text -> quoted_message_candidate first
```

Quoted body content must not automatically become a formal `email_message`
because it may be partial, edited, reformatted, or duplicated in reply chains.
It should link to an existing `email_message` only when matching is reliable.

Dedup bypass behavior must preserve lineage:

```text
known archive hash -> skip exact duplicate carrier processing when policy allows
known message fingerprint -> skip duplicate body insertion and downstream work,
  still insert email_message_occurrence
known attachment sha256 -> skip duplicate byte storage,
  still insert email_attachment_occurrence
known embedded message -> skip duplicate message body,
  still insert embedded_message_relation / occurrence lineage
```

#### Official FormOwl Mail Evidence Adapter boundary

The FormOwl Mail Evidence Adapter is an `ExtractorAdapter` boundary for
registered mail assets. It begins after a mail source has already been captured
as a governed `Asset` through `UploadSession`, the trusted local folder ingress,
or another controlled import path. It ends after the adapter has produced a
versioned `ExtractorRun`, persisted mail observations, and any attachment asset
records required by the ingestion policy.

The boundary accepts only FormOwl-managed asset references and extraction
inputs. A mail adapter may parse PST, OST, MSG, EML, MBOX, or synthetic fixture
archives, but it must receive FormOwl identifiers such as `asset_id`,
`object_uri`, `storage_backend_id`, `permission_scope`, `workspace_id`, and
`source_ref`. It must not use raw local paths, NAS paths, mailbox account
credentials, or parser scratch locations as public identity.

Server-side parser adapters and optional Local Companion adapters are both
inside this boundary. Server-side adapters parse uploaded archives from ingest
staging; Companion adapters may parse locally or emit manifest/delta output.
Both must produce the same `MailEvidenceBundle` contract.

Within this boundary a mail adapter may:

- read the immutable registered mail asset through the object-store layer;
- parse folders, messages, headers, body segments, threads, and attachments;
- normalize mail identity and fingerprint inputs;
- emit `mail_folder_occurrence`, `email_message`, `email_header`,
  `email_body_segment`, `email_attachment_occurrence`, and `email_thread`
  observations when the implementation supports them;
- create attachment assets when extraction policy treats attachment bytes as
  independent resources;
- preserve archive, mailbox, folder, message, thread, body segment, attachment,
  and occurrence identity separately; and
- report parser warnings or failures on the `ExtractorRun` without overwriting
  earlier runs.

The mail adapter must not:

- watch or mutate user mail folders directly;
- implement a mail-only folder scanner separate from the shared asset ingress
  pipeline;
- expose raw file paths, PST locations, object-store roots, parser scratch
  paths, SQL, backend endpoints, or mailbox credentials through MCP-facing
  records;
- drop occurrence lineage during deduplication;
- grant access to another user's mail evidence;
- create `SemanticMetadata`, `CandidateAtom`, `CandidateRelation`, canonical
  graph records, user graph revisions, wiki revisions, or project/wiki writes
  as a side effect of parsing; or
- decide case-progress answers directly.

Mail semantic metadata, candidate graph proposals, case-progress QA, retrieval
indexes, and wiki projection are downstream consumers of mail observations.
They must remain separate workflows with their own permission checks, review
state, and tests.

The current `FixtureMailArchiveExtractor` is the official synthetic conformance
baseline for this boundary. It proves archive, mailbox, folder, message, body
segment, attachment occurrence, source provenance, permission scope, stable
observation IDs, and raw-path non-exposure for JSON-backed mail fixtures. The
extractor itself still only parses observations; the synthetic completion
profile below adds separate evidence/search, candidate bridge, case-progress
QA, and preflight helpers for JSON fixtures. This is not a production
PST/OST/MSG/EML parser or real mailbox retrieval/index readiness claim.

#### Synthetic mail phase completion profile

The synthetic `formowl-mail` phase completes the repository-side contracts and
workflow proof for JSON-backed fixtures, not real mailbox ingestion. In this
profile:

- `FixtureMailArchiveExtractor` emits `email_thread`, `email_header`,
  `email_message`, `email_body_segment`, `email_attachment_occurrence`, and
  `mail_folder_occurrence` observations.
- Message payloads carry a `formowl_mail_fingerprint_v1` fingerprint,
  normalized subject, thread id, and message occurrence id. Duplicate message
  appearances preserve separate occurrence ids even when the message
  fingerprint is the same.
- `formowl_mail.build_mail_evidence_pack()` groups persisted mail observations
  into local evidence packs with a deterministic search index over safe mail
  metadata and body snippets.
- `formowl_mail.extract_and_store_mail_candidates()` converts selected mail
  evidence into reviewable `SemanticMetadata`, `CandidateAtom`, and
  `CandidateRelation` proposals. It does not commit canonical graph state.
- `formowl_mail.build_case_progress_answer()` answers case-progress questions
  from cited mail observations for updates, blockers, responsible parties,
  next actions, and deadlines.
- `formowl_mail.build_mail_preflight_readiness_review()` records the readiness
  artifact for the synthetic phase and explicitly defers real PST/OST/MSG/EML
  parser readiness.

### 4.8 Semantic metadata and candidate graph extraction

Input:

```text
transcript segments
OCR blocks
document paragraphs
tables
video scenes
image captions
project issue comments
wiki sections
conversation logs
email messages
email threads
```

Output:

```text
entities
relations
claims
decisions
action items
risks
requirements
deadlines
owners
topics
dependencies
open questions
candidate atoms
candidate graph edges
coordination frames
business object candidates
property assertions
relation assertions
state assertions
event assertions
coordination assertions
```

Possible tools:

```text
LLM structured extraction
LangChain LLMGraphTransformer
LlamaIndex PropertyGraphIndex
Neo4j LLM Graph Builder
GraphRAG-style extraction tools
rule-based extractor
NER model
relation extraction model
```

These tools may write only to:

```text
SemanticMetadataStore
DomainPackStore
CandidateBusinessObjectStore
CandidateAssertionStore
CandidateAtomStore
CandidateMentionStore
CandidateFrameStore
ExternalGraphImportStore
```

Different source formats and departments must use the same candidate-knowledge
method. Source adapters may normalize email, ERP, application, document,
table, image, audio, video, or project records into observations, but they must
not introduce separate source-specific candidate ontologies or source-specific
task-answering methods. They emit content, semantic properties, and metadata as
separate normalized fields; they do not determine answer priority, evidence
completeness, or UI pagination.

For every normalized text-bearing observation, the required candidate method
is:

```text
Unicode/script normalization
  -> protected ASCII identifier extraction
  -> Jieba segmentation
  -> corpus-bound SentencePiece segmentation
  -> frozen-profile candidate admission
  -> candidate graph construction and retrieval
```

Jieba and SentencePiece generate candidates; they do not authorize graph edges
by themselves. The frozen profile admits candidates before graph construction
and preserved no-match behavior in the EXM benchmark that selected this
default. That result is not a universal no-match guarantee; every domain
evaluation still requires explicit rejection-calibration metrics. Domain Pack
protected vocabulary may supplement admitted candidates, but it does not
replace the shared tokenizer or create a department-specific pipeline.

If required segmenters are unavailable, the normal path must fail closed.
Deployments that intentionally allow a degraded regex fallback must label that
mode in the extraction and evaluation output. Silent regex-only fallback is a
specification violation.

Candidate retrieval must not infer evidence count from the number of parser
chunks. Adapters provide stable logical-source and context lineage; the shared
retriever then:

```text
requires trusted observation / identity-policy / version / permission binding
-> filters context, time, epistemic, and lifecycle state
-> derives universal intent and evidence cardinality from the query
-> computes support and IDF over logical source items
-> permits same-source observations to jointly cover anchors
-> returns minimal citeable observations inside independent source/observation budgets
```

Assertions or observations not yet recorded and visible at `known_as_of`, not
valid at `as_of_world_time`, outside the selected context, or outside caller
permission are excluded before planning and ranking. Undated source items
cannot become earliest/latest chronology evidence.

Optional ontology guidance must bind the ontology revision, supported signal
vocabulary hash, and complete `TypeDefinition`/`TypeMapping` contract hash.
Ontology overlap may provide a capped additive rerank only. It must not remove
lexically supported candidates, bypass source evidence, or turn an evidence
facet into a canonical entity/type assertion.

One candidate-knowledge extraction must persist its Domain Pack definition,
business objects, and assertions atomically. Missing or mismatched Domain Pack
provenance, cross-permission references, unsafe internal references, duplicate
ids, invalid mappings, empty semantics, or a write failure must leave no
partial candidate records.

They must not directly write to:

```text
CanonicalGraphStore
UserKnowledgeGraph
WikiRevision
```

---

## 5. Extractor Routing

The Resource Extraction Layer should select extractors based on MIME type, file extension, workspace policy, project policy, resource size, and user permissions.

Example routing table:

| Resource Type         | Technical Metadata             | Content Extraction                            | Optional Semantic Extraction           |
| --------------------- | ------------------------------ | --------------------------------------------- | -------------------------------------- |
| Image                 | ExifTool                       | OCR if text-like                              | Vision caption / diagram parser        |
| PDF with text         | pdf parser / Docling           | paragraphs, tables, sections                  | LLM semantic extraction                |
| Scanned PDF           | pdf metadata                   | OCR / layout OCR                              | LLM semantic extraction                |
| Audio                 | ffprobe / MediaInfo            | ASR / diarization                             | decision / action item extraction      |
| Video                 | ffprobe / MediaInfo            | audio ASR, scene detection, keyframes         | screen-step / scene summary extraction |
| DOCX                  | document parser                | paragraphs, tables, headings                  | LLM semantic extraction                |
| PPTX                  | document parser                | slide text, speaker notes, images             | slide-level summary                    |
| CSV / XLSX            | schema parser                  | rows, columns, sheets                         | table summary / entity extraction      |
| Markdown              | markdown parser                | sections, links, code blocks                  | topic / claim extraction               |
| PST / OST / MSG / EML | archive hash and mail metadata | messages, folders, attachments, body segments | thread summary / entity extraction     |

---

## 6. Location Metadata Standard

Every observation should include the most precise locator possible.

Supported locator fields:

```text
page
section
heading_path
paragraph_index
table_index
row_index
column_index
bbox
start_sec
end_sec
frame_index
timestamp_sec
speaker
slide_index
sheet
cell_address
byte_offset
char_start
char_end
uri_fragment
message_id
mailbox_id
folder_path_hash
attachment_index
```

### 6.1 PDF paragraph

```json
{
  "page": 5,
  "paragraph_index": 12,
  "bbox": [80, 320, 510, 390]
}
```

### 6.2 Audio transcript

```json
{
  "start_sec": 51.2,
  "end_sec": 68.9,
  "speaker": "speaker_01"
}
```

### 6.3 Spreadsheet cell

```json
{
  "sheet": "Budget",
  "cell_address": "D12"
}
```

### 6.4 Video keyframe

```json
{
  "timestamp_sec": 120.5,
  "frame_index": 3615,
  "bbox": [200, 100, 800, 500]
}
```

---

## 7. Confidence, Warnings, and Review

Every extractor output should support:

```text
confidence
requires_review
warnings
errors
```

Examples of warnings:

```text
ocr_low_confidence
asr_low_confidence
speaker_diarization_uncertain
model_generated_description_requires_review
unsupported_file_type
partial_extraction
large_file_truncated
password_protected_document
embedded_media_skipped
table_structure_uncertain
```

Generated semantic metadata should usually default to:

```json
{
  "requires_review": true
}
```

Technical metadata from deterministic tools may default to:

```json
{
  "requires_review": false
}
```

---

## 8. Re-extraction Policy

Re-extraction should be possible when:

```text
extractor version changes
model version changes
extraction config changes
workspace policy changes
resource content hash changes
user requests regeneration
downstream graph policy changes
```

The system should not overwrite previous extraction runs by default.

Instead, it should create a new `ExtractorRun` and preserve prior outputs for auditability and diffing.

---

## 9. Adapter Interface

Define a conceptual interface like:

```python
class ExtractorAdapter(Protocol):
    def name(self) -> str: ...
    def version(self) -> str: ...
    def supported_mime_types(self) -> list[str]: ...
    def extractor_type(self) -> ExtractorType: ...
    def extract(self, input: ExtractionInput, policy: ExtractionPolicy) -> ExtractionResult: ...
```

Conceptual types:

```text
ExtractorType:
  technical_metadata
  document_structure
  ocr
  asr
  speaker_diarization
  video_scene_detection
  image_captioning
  semantic_metadata
  candidate_graph
```

The actual implementation may differ, but the specification should make the adapter boundary explicit.

---

## 10. Storage Boundary

Resource Extraction may write to:

```text
StorageBackendRegistry
AssetStore
ObjectStore
ObservationStore
SemanticMetadataStore
DomainPackStore
CandidateBusinessObjectStore
CandidateAssertionStore
CandidateAtomStore
CandidateMentionStore
CandidateFrameStore
ExternalGraphImportStore
ExtractorRunStore
JobStore
```

Resource Extraction must not directly write to:

```text
CanonicalGraphStore
UserKnowledgeGraph
WikiRevision
```

Downstream conversion should follow this path:

```text
Observation
-> SemanticMetadata
-> DomainPackDefinition
-> CandidateBusinessObject
-> CandidateAssertion
-> optional CandidateMention / CandidateFrame / CandidateAtom / CandidateRelation
-> GranularityPolicyEngine
-> EntityResolver
-> RelationResolver
-> CanonicalGraphCommit
-> UserKnowledgeGraph projection
-> Wiki projection
```

Do not collapse resource extraction, graph governance, and wiki generation into a single pipeline. Resource Extraction creates evidence-like intermediate artifacts. It does not decide canonical truth, directly generate final wiki pages, or directly mutate the canonical knowledge graph.

The canonical graph must never reference raw storage paths directly. Graph evidence should reference stable FormOwl identifiers such as:

```text
asset_id
observation_id
extractor_run_id
evidence_id
entity_id
relation_id
workspace_id
user_id
grant_id
```

Allowed retrieval locators are FormOwl-controlled identifiers such as
`formowl://asset/{asset_id}`, `formowl://observation/{observation_id}`, or
`formowl://evidence/{evidence_id}`. A KG-first query may use graph evidence
links to resolve observations, but the resolver must apply the observation's
permission scope before returning text, captions, modality-specific location
fields, or asset references. Disallowed locators include NAS, SMB, NFS,
WebDAV, local scratch, and raw object-store paths exposed through MCP.

---

## 11. MVP Recommendation

The first implementation should focus on a minimal but extensible extractor stack.

Recommended MVP stack:

```text
Asset / technical metadata:
  - libmagic
  - sha256 hashing
  - ExifTool
  - MediaInfo
  - ffprobe / FFmpeg

Document:
  - Docling
  - Unstructured
  - PyMuPDF or pdfplumber as fallback

OCR:
  - Tesseract or PaddleOCR
  - Docling OCR path for PDFs/images

Audio:
  - FFmpeg
  - WhisperX

Video:
  - FFmpeg
  - MediaInfo
  - PySceneDetect
  - OCR on keyframes

Semantic metadata:
  - Unicode/script normalization
  - protected ASCII identifier extraction
  - Jieba segmentation
  - corpus-bound SentencePiece segmentation
  - frozen-profile candidate admission
  - LLM structured extraction adapter
  - later: LangChain LLMGraphTransformer / LlamaIndex PropertyGraphIndex / Neo4j LLM Graph Builder

Storage:
  - AssetStore
  - ObjectStore
  - ObservationStore
  - SemanticMetadataStore
  - DomainPackStore
  - CandidateBusinessObjectStore
  - CandidateAssertionStore
  - CandidateAtomStore
  - CandidateMentionStore
  - CandidateFrameStore
  - ExtractorRunStore
  - JobStore
```

---

## 12. Acceptance Criteria

The Resource Extraction implementation is aligned with this specification when:

```text
RESOURCE_EXTRACTION_SPEC.md exists.
It clearly states that FormOwl does not train neural networks.
It explains that neural-network-based tools may be used only as replaceable external extractors.
It defines the difference between raw resources, technical metadata, observations, semantic metadata, candidate knowledge, and canonical graph state.
It defines CandidateBusinessObject and the five CandidateAssertion families as the source-neutral minimum core.
It defines Domain Packs as provenance-linked, content-hash-pinned scoped mappings rather than source- or department-specific ontologies.
It defines one TemporalContext plus separate epistemic and lifecycle vocabularies shared by all source modalities and Domain Packs.
It requires future-knowledge exclusion before ranking when a known-as-of query boundary is supplied.
It defines LogicalSourceItem separately from Observation chunks and ContextBoundary separately from both.
It defines logical source identity as source-identity-policy id plus source-item id and requires source-version and permission-scope ids on retrievable evidence.
It requires a trusted access binding over eligible observations, source-identity policies, source versions, and permission scopes; missing bindings fail closed and request bindings cannot broaden index bindings.
It requires evidence cardinality and IDF to count logical source items rather than parser chunks.
It allows multiple observations to cover anchors only within the same logical source item.
It requires permission, source-identity-policy, source-version, context, time, epistemic, and lifecycle admissibility before planning and ranking.
It derives explicit evidence cardinality from source-unit syntax/classifiers, excludes identifiers and measurement units, and rejects counts beyond the source budget.
It separates accessible contexts from explicitly selected query contexts and requires authorization for multi-context comparison.
It requires chronology modes to preserve requested cardinality, exclude undated items, and use an explicit query timezone for date-only boundaries.
It keeps logical-source and observation budgets independent.
It defines TaskFrame, EvidenceRequirement, EvidenceCoverage,
AnswerabilityDecision, and ProjectionSpec as separate downstream contracts.
It defines explicit sufficient, exact, at-least, and all-matching cardinality
modes without treating corpus size or UI page size as the requested count.
It requires retrieval to report total/returned logical-source counts plus
is-exhaustive and has-more state.
It requires evidence assembly to gather normalized fields from admissible
observations inside selected logical source items without crossing access or
source boundaries.
It makes content the default primary projection field and keeps sender,
recipient, headers, filenames, and other metadata secondary unless explicitly
requested.
It distinguishes permission denied, target not found, property absent, partial
evidence, conflicting evidence, and sufficient evidence before presentation.
It stores stable logical-source gold, scores primary retrieval at logical-source level, and reports exact Observation citation and stale/unmapped diagnostics separately.
It derives ontology evidence facets from observation type, modality, and semantic roles and forbids numeric-identifier-as-measurement inference.
It binds ontology-guided reranking to the ontology revision, signal vocabulary, and complete type/mapping contract.
It limits ontology guidance to a capped additive rerank that cannot delete lexically supported candidates.
It defines Jieba plus corpus-bound SentencePiece candidate generation with frozen-profile admission as the default for every text-bearing Observation.
It restricts regex-only tokenization to protected ASCII extraction, explicit baselines/ablations, or a clearly reported degraded fallback.
It requires tokenizer, admission-policy, model/vocabulary, and corpus hash bindings and forbids silent regex-only fallback.
It requires atomic candidate-only persistence and forbids direct canonical, user-graph, wiki, and external-system writes.
It lists recommended tools for file metadata, document parsing, OCR, ASR, speaker diarization, video scene detection, and semantic extraction.
It defines extractor provenance requirements.
It defines locator metadata standards.
It defines confidence, warning, error, and review behavior.
It defines re-extraction policy.
It defines storage boundaries.
It prevents Resource Extraction from writing directly to CanonicalGraphStore, UserKnowledgeGraph, or WikiRevision.
SPEC.md references this file.
README.md references this file where repository documentation is listed or summarized.
```
