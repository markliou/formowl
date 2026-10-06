# Resource Extraction Specification

## 1. Purpose and Authority

The Resource Extraction Layer converts registered heterogeneous sources into
source-preserving, citeable Observations and reviewable semantic candidates.

It is the evidence boundary beneath graph governance, strong RAG, graph-guided
retrieval, deterministic execution, and projections. It does not decide
canonical truth and it does not generate definitive business answers as a side
effect of parsing.

This specification applies to every source family. Mail is the first large
fixture, not a special extraction architecture.

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

Unexplained loss blocks the source-completeness gate.

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
binary content. It is evidence, not a canonical fact.

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

Representative tools include Tesseract, PaddleOCR, EasyOCR, Docling OCR,
ExifTool, and governed vision-model adapters.

### 5.3 Audio and video

Expected observation types include:

```text
transcript segment
speaker segment
word timestamp
audio event
video scene
keyframe and keyframe OCR
visual or screen-step candidate
```

Preserve start/end time, speaker label and confidence, scene/frame indexes,
bounding boxes, and audio/video technical metadata.

Representative tools include FFmpeg, ffprobe, MediaInfo, Whisper or WhisperX,
pyannote, and PySceneDetect.

### 5.4 Spreadsheets and databases

Expected observations include:

```text
workbook, sheet, table, and schema metadata
row and cell values
query or export snapshot occurrence
transaction or record occurrence
primary/business identifier candidates
```

Preserve sheet/table name, row/column or record key, export/query revision,
source-system timestamp, null semantics, and type precision. A database row or
spreadsheet cell is evidence; it does not directly become a canonical entity or
relation.

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

---

## 8. Tokenization, Indexing, and Retrieval Boundary

Extraction produces source-preserving Observations. Query-time lexical/dense
indexes are derived projections over authorized Observations.

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

Strong RAG and graph-guided retrieval consume the same Observation snapshot.
Graph or ontology ranking cannot hide source-completeness failure.

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
5. heterogeneous adapters preserve source-native locators and time semantics;
6. source completeness is compared with an independent source inventory and
   unexplained loss fails the gate;
7. re-extraction creates a new run and never overwrites historical evidence;
8. tokenizer/embedding re-indexing can reuse authorized Observations without
   reparsing source content;
9. semantic tools and LLMs remain replaceable candidate generators;
10. no extractor writes canonical graph/type, user graph, wiki, or external
    business-system state;
11. public records expose only governed identifiers and safe summaries; and
12. canonical dev-container tests cover positive, partial, failed, denied,
    duplicate-occurrence, re-extraction, and leak-guard behavior.
