# Multimodal Ontology Term Extraction Decision

Date: 2026-07-09

Status: active normative default for text-bearing candidate generation and
evaluation. This is not a canonical-write or broad production-readiness claim.

## Default Candidate Evidence Retrieval

Term extraction feeds the source-neutral Candidate evidence method; it does
not define evidence cardinality by itself. Retrieval counts a stable logical
source item, applies access/context/time before query planning, avoids lexical
transitive closure, and treats ontology as a capped additive rerank.
Regex-only, parser-chunk, component-union, and ontology hard-pruning paths are
ablation-only.
The index-owned `CandidateEvidenceTextPolicyRuntime` must prove this
Unicode-NFKC/protected-ASCII/Jieba/corpus-bound SentencePiece/frozen-profile
stack and exact admission/model/corpus SHA-256 hashes. The binding also pins
the runtime id and tokenizer implementation hash; runtime code mismatch fails
closed. Default callers provide query text only and cannot supply raw tokens
or a free-form hash. Access and explicit context/time admissibility precede
tokenization; experiments use `retrieve_ablation`.
Raw query text may identify control intent, evidence count, and chronology
syntax only. Retrieval anchors, actor/topic vocabulary, and supported content
terms must come from runtime-produced tokens or a named `retrieve_ablation`
extension; regex-parsed raw terms must never be added back. Access uses a real
`CandidateEvidenceAccessBinding` whose four eligibility collections are
`frozenset` values of exact nonblank strings. Cross-context comparison
authorization must be an actual boolean; string values fail closed.

## Decision

FormOwl uses a data-driven mention and term extraction layer before ontology
selection, entity resolution, frame extraction, and KG fusion.

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

- Use Unicode/script normalization, protected ASCII identifier extraction,
  Jieba segmentation, corpus-bound SentencePiece segmentation, and the
  hash-bound frozen-profile candidate-admission policy as the default path for
  every text-bearing Observation.
- Treat raw Jieba plus SentencePiece output and regex-only tokenization as
  explicit ablations, not production/default retrieval policies.
- Fail closed when required segmenters are missing. A deployment may use a
  regex-only degraded fallback only when the extraction and evaluation output
  clearly labels that mode.
- Use corpus statistics, layout and role context, gazetteers, weak labels, and
  ablations as the primary source of term and ontology candidates.
- Use LLMs only for low-confidence explanation, naming suggestions, ambiguity
  notes, and candidate review assistance.
- Do not let an LLM directly create canonical ontology, canonical type, entity,
  relation, user-graph, grant, or wiki state.
- Do not rely on a top-down company ontology or fixed department list.
- Do not apply ontology as an early hard filter unless a high-confidence,
  calibrated gate has passed end-task ablation.

## Why This Is The Default

Legacy mail query, evidence, KG-fusion, and entity-resolution paths used simple
regex tokenization. That remains useful for ASCII identifiers, emails, domains,
and many part numbers, but it is not a general Chinese or mixed-script mention
extractor. Completed EXM experiments showed that broader Jieba plus
SentencePiece candidate generation improves recall, while the frozen admission
profile prevented the raw-token no-match collapse on that EXM benchmark. The
original MAY questions still fail no-match calibration, so rejection remains a
separate measured retrieval policy rather than an assumed tokenizer property.

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

The default is a corpus-adapted candidate stack, not a retrained supervised
segmenter:

1. Unicode normalization and script-aware normalization.
2. Protected regex extraction for ASCII identifiers, email addresses, domains,
   and part-number-like strings.
3. Jieba segmentation for Chinese term candidates.
4. Corpus-bound SentencePiece segmentation for mixed-script and corpus-adapted
   candidates.
5. Frozen-profile candidate admission with document-frequency limits,
   protected mention handling, and a hash-bound fixed score profile.
6. Candidate graph construction only from admitted terms plus governed Domain
   Pack protected vocabulary.
7. Optional phrase mining, gazetteers, layout/role context, and alias clustering
   as additional candidate signals, never as canonical writes.

Tokenizer and admission outputs must bind segmentation-policy version,
admission-policy hash, model or vocabulary hash, and corpus hash. A policy or
binding change requires re-extraction or reevaluation.

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
- False-reject metrics for every explicit non-default hard-gate ablation.
- Permission and redaction safety checks.

No hard type or ontology gate may replace Default Candidate Evidence Retrieval
without a specification rewrite, independent cross-domain end-task evidence,
and false-reject instrumentation.

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

The 2026-07-09 EXM 50,000-case lexical candidate-admission run supports this decision.
The `jieba + SentencePiece` lexical policy improved positive cross-message
retrieval versus regex-only matching, but it also failed every no-match guard
case because the lexical graph collapsed into very large components. The
type-compatibility proxy arm tied the lexical KG arm, so the measured lift came
from broader lexical matching, not from ontology selection.

This result means raw tokenizer output must remain candidate generation rather
than direct graph admission. The raw lexical arm is retained only as an
ablation. The default retrieval method uses the later frozen-profile admission
policy before graph construction; tokenizer output still never becomes
canonical ontology, canonical type, or canonical graph state directly.

The weak-label MLP candidate-admission follow-up implements that principle as
an executable policy. The policy accepts or rejects candidate terms before KG
edge construction using document-frequency gates, protected mention typing, a
deterministic CPU-bounded weak-label MLP scorer, and exact-candidate-only
category/type-proxy retrieval. On the 50,000-case EXM evaluation, this bundled policy
keeps all no-match and permission-denied guards while improving positive
retrieval over raw `jieba + SentencePiece`. This supports the design rule that
candidate admission must be tested before graph construction. It does not
establish a coordination-frame or ontology-semantic effect.

The 2026-07-10 no-training control run established the default method. A
hashable fixed CJK scoring profile with zero training examples and zero
training epochs scored 43,976/50,000 on the same generated EXM benchmark,
while the weak-label MLP scored 43,369/50,000. The stable default should
therefore be data-driven-first candidate admission with the frozen scoring
profile, not a self-trained MLP.

The MAY evaluator now keeps that tokenizer/admission stack but no longer treats
token overlap as transitive graph connectivity. Its active retrieval method
requires a trusted access binding over observation ids, source-identity
policies, source versions, and permission scopes; filters those axes plus
context, time, epistemic status, and lifecycle status before planning; counts
and ranks logical source identities as `(policy, item id)` rather than
observation chunks; derives evidence cardinality from source-unit syntax or
classifiers while excluding identifier and duration numbers; and allows
observations to aggregate anchors only within one source item.

On the formal July 17, 2026 MAY 100-case run, the source-neutral Candidate KG
scored 93/100: 73/80 answerable, 10/10 no-match, and 10/10 permission. The
contract-bound capped ontology rerank also scored 93/100 and lost no Candidate
KG passes. Both reports validated with `blockers=[]`; logical-source recall was
95.00%, exact Observation citation recall was 94.37%, citation precision was
93.78%, and the largest component contained 6 observations. Stable
logical-source gold determines primary pass/fail; current parser chunk ids
affect citation diagnostics only. The earlier 17/100 and 20/100
tokenizer-only results remain historical evidence that a correct tokenizer is
necessary but not sufficient.

BGE-M3 through FlagEmbedding remains an optional neural ablation in a separate
runtime image. The current 93/100 result is evidence-selection quality on one
private mail-derived corpus, not a production generalization claim for
finance, quality, PDF, PPT, OCR, or other modalities.

## Required Implementation Contracts

Implementations use contracts and reports along these lines:

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

This document does claim the normative default candidate method and its use by
the tested EXM and MAY evaluators. It does not claim that every source adapter
is already integrated, nor does it claim:

- a trained mention/type classifier;
- production multimodal extraction quality;
- canonical ontology auto-promotion;
- business answer generation;
- raw private data access through public tools;
- production readiness.
