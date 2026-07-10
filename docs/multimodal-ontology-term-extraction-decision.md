# Multimodal Ontology Term Extraction Decision

Date: 2026-07-09

Status: design decision. This is not an implementation completion claim.

## Decision

FormOwl will add a data-driven mention and term extraction layer before
ontology selection, entity resolution, frame extraction, and KG fusion.

This layer is broader than a tokenizer. Tokenization is one replaceable adapter
inside a governed pipeline:

```text
RawResource
  -> modality extractor
  -> Observation
  -> normalized text/layout/time region
  -> term and mention candidates
  -> typed mention candidates
  -> alias and entity candidates
  -> candidate graph and frame extraction
  -> ontology health report and type proposals
  -> governed canonical ontology/type/graph changes
```

The initial policy is data-driven first:

- Use corpus statistics, layout and role context, gazetteers, weak labels, and
  ablations as the primary source of term and ontology candidates.
- Use LLMs only for low-confidence explanation, naming suggestions, ambiguity
  notes, and candidate review assistance.
- Do not let an LLM directly create canonical ontology, canonical type, entity,
  relation, user-graph, grant, or wiki state.
- Do not rely on a top-down company ontology or fixed department list.
- Do not apply ontology as an early hard filter unless a high-confidence,
  calibrated gate has passed end-task ablation.

## Why This Is Needed

The current mail query, evidence, KG-fusion, and entity-resolution paths use
simple regex tokenization. That is usable for ASCII identifiers, emails,
domains, and many part numbers, but it is not a Chinese mention extractor and
does not reliably preserve terms such as Chinese company names.

For example, a Chinese organization name should enter the KG pipeline as a
`CandidateMention` or candidate entity instance typed as `Organization`. The
organization name itself is not an ontology type. The ontology type is
`Organization`; the name is an instance or alias candidate with source
evidence.

Future multimodal data makes this boundary more important. PDF, PowerPoint,
OCR, audio, video, screenshots, and mail all produce different locators and
error modes. FormOwl therefore needs one shared candidate layer that can compare
evidence across modalities without turning a modality-specific parser output
into ontology truth.

## Multimodal Evidence Boundary

Every modality-specific extractor must output `Observation` records first.
Term and mention extraction reads observations, not raw backend paths or private
parser internals.

Supported locator styles include:

- Mail: message occurrence, body segment, header, attachment occurrence.
- PDF and document: page, section, paragraph, table, cell, bounding box.
- PowerPoint: slide, shape, notes, embedded object, image region.
- OCR and image: page or image id, text region, line, word, bounding box.
- Audio: transcript segment, word timestamp, speaker segment.
- Video: scene, keyframe, transcript segment, OCR region, timestamp.

The same surface form can receive evidence from multiple modalities. A company
name in an email, a supplier field in a PDF, an OCR block in a scanned quote,
and a transcript mention in a meeting should become separate candidate mentions
that may later support one candidate entity.

## Term Extraction Policy

The first production-quality direction is not to retrain a supervised segmenter
from scratch. The first direction is a corpus-adapted term extraction stack:

1. Unicode normalization and script-aware normalization.
2. Existing regex tokenization retained for ASCII identifiers, email addresses,
   domains, and part-number-like strings.
3. CJK span generation that does not depend on whitespace.
4. Corpus phrase mining using frequency, document/thread spread, left and right
   entropy, accessor variety, PMI-like association, and repeated layout fields.
5. Domain lexicon induction from high-stability phrases across documents,
   threads, senders, departments, and attachments.
6. Gazetteer and suffix rules for organization, person, location, document,
   artifact, amount, quantity, date, and project candidates.
7. Context-role scoring from nearby cues such as supplier, vendor, customer,
   buyer, quotation, invoice, purchase order, payment, shipment, owner, and
   approver.
8. Alias clustering across spelling variants, abbreviations, OCR variants,
   email domains, document fields, and repeated graph neighborhoods.

The output is a scored candidate set, not a single irreversible segmentation:

```text
surface: <redacted enterprise term>
candidate_types:
  Organization: 0.91
  Artifact: 0.04
  Project: 0.03
  Unknown: 0.02
evidence:
  observation_count: ...
  modality_count: ...
  thread_or_document_spread: ...
  role_contexts: ...
```

Tracked public reports must aggregate or hash sensitive surface forms unless the
surface is already a safe public fixture term.

## Training Policy

Large raw corpora are useful immediately, but they do not by themselves provide
trusted typed labels.

Use large raw corpora for:

- tokenizer vocabulary adaptation;
- phrase and terminology mining;
- weak-label generation;
- domain gazetteer induction;
- alias and spelling-variant discovery;
- hard-case selection for annotation or review.

Do not claim a reliable supervised mention/type classifier from raw data alone.
Typed training requires one or more governed label sources:

- high-confidence weak labels with rule ids and error estimates;
- reviewed `CandidateMention`, `TypeDefinition`, `TypeMapping`, and
  `TypeAlignmentCandidate` outcomes;
- active-learning review of low-confidence or high-impact spans;
- sampled held-out annotations for term-boundary and type accuracy.

Trained models may produce candidates only. Their outputs must record model
version, training manifest hash, extraction policy id, confidence, and evidence
links. They must not directly mutate canonical ontology or canonical graph
state.

## Ontology Selection Policy

Ontology promotion must be decided by policy and data, not by a fixed number of
types and not by LLM preference.

Candidate types or domain packs may be promoted only when they pass configured
selection thresholds such as:

- corpus coverage across enough documents, threads, cases, modalities, or
  departments;
- stability across time windows;
- positive KG retrieval or QA lift under ablation;
- reduced false positives without unacceptable false rejects;
- low permission-boundary risk;
- low type conflict rate;
- clear mapping to the closed core or an approved scoped promoted type;
- reproducible provenance through source observations and candidate ids.

The system should choose the smallest effective set. If adding more terms or
types does not improve end-task quality, those candidates remain scoped,
experimental, or archived.

## Multimodal Evaluation Gates

The layer is not effective until it improves measured behavior. Required
evaluation families:

- Term-boundary evaluation for Chinese, mixed Chinese/English, identifiers, and
  OCR-noisy text.
- Mention typing accuracy for core supertypes such as `Organization`, `Person`,
  `Artifact`, `Document`, `Project`, `Location`, `Event`, and `Concept`.
- Alias/entity clustering precision and recall.
- KG retrieval and QA lift against KG-only and regex-tokenizer baselines.
- Ontology ablation showing which term/type candidates actually contribute.
- Cross-modality agreement tests, for example mail plus PDF plus transcript.
- False-reject metrics for any hard gate.
- Permission and redaction safety checks.

No hard type or ontology gate should ship without false-reject instrumentation.

## Relationship To Ontology v2

Ontology v2 remains useful for coordination frames: request, commitment,
decision, blocker, deadline, dependency, escalation, and follow-up semantics.

This decision adds the missing upstream layer:

```text
term and mention extraction
  -> typed candidate mentions/entities
  -> coordination frames and business objects
  -> candidate KG fusion
  -> ontology health and promotion policy
```

The change is therefore not "replace v2". It is "make v2 data-driven and
multimodal-ready before any broader ontology claim".

## Current EXM Lexical Evaluation

The 2026-07-09 EXM 50,000-case lexical ontology run supports this decision.
The `jieba + SentencePiece` lexical policy improved positive cross-message
retrieval versus regex-only matching, but it also failed every no-match guard
case because the lexical graph collapsed into very large components. The
ontology-scored lexical arm tied the lexical KG arm, so the measured lift came
from broader lexical matching, not from ontology selection.

This result means the tokenizer stack should remain an upstream candidate
generator. It should not be promoted directly into production retrieval,
canonical ontology, canonical type, or canonical graph state. The next stable
method needs term-quality scores, document-spread or IDF caps, component
splitting, alias/entity clustering checks, and no-match calibration before
ontology promotion decisions use those terms.

The graph-neural programmatic ontology follow-up implements that principle as
an executable policy. The policy accepts or rejects candidate terms before KG
edge construction using document-frequency gates, protected mention typing, a
deterministic CPU-bounded weak-label MLP scorer, and exact-candidate-only
ontology retrieval. On the 50,000-case EXM evaluation, this bundled policy
keeps all no-match and permission-denied guards while improving positive
retrieval over raw `jieba + SentencePiece`. This supports the design rule that
ontology should be compiled into tested graph behavior before it can influence
retrieval or promotion decisions.

The 2026-07-10 no-training control run further narrows the default method. A
hashable fixed CJK scoring profile with zero training examples and zero
training epochs scored 43,976/50,000 on the same generated EXM benchmark,
while the weak-label MLP scored 43,369/50,000. The stable default should
therefore be data-driven-first programmatic ontology with a frozen scoring
profile, not a self-trained MLP. BGE-M3 through FlagEmbedding remains the best
next optional true frozen neural adapter candidate, but it should run in a
separate neural experiment/runtime image because the default dev container
does not include torch, transformers, FlagEmbedding, GLiNER, HanLP, or CKIP.

## Implementation Implications

Future implementation should introduce contracts and reports along these lines:

- `TermExtractionPolicy` or an extension of `ExtractionPolicy`.
- `TermCandidateBatch` for corpus-level safe aggregate term candidates.
- `TypedMentionCandidate` metadata, likely using or extending
  `CandidateMention`.
- `OntologyHealthReport` for coverage, conflict, stability, utility, and
  boundary-risk metrics.
- `OntologySelectionPolicy` for promotion thresholds and ablation requirements.

These should remain separate from canonical ontology/type stores. Candidate
generation, governance, canonical graph commits, user graph assembly, and wiki
projection stay as separate layers.

## Current Claim Boundary

This document sets direction only.

It does not claim that FormOwl currently has:

- a production Chinese tokenizer;
- a trained mention/type classifier;
- production multimodal extraction quality;
- canonical ontology auto-promotion;
- business answer generation;
- raw private data access through public tools;
- production readiness.
