# Heterogeneous-Source Ontology Term and Mapping Decision

**Active program:** GitHub issue #56
**Decision date:** 2026-08-18
**Status:** active design; runtime methodology authority remains blocked

This is the active decision for term extraction, multilingual tokenization,
source mappings, and ontology candidate promotion. It replaces the earlier
mail/OCR-centered active interpretation. Historical text is preserved under
`docs/archive/2026-08-18/`.

## Decision

Use a data-first, source-preserving, scoped ontology process:

```text
heterogeneous Observations
  -> protected identifier and multilingual term candidates
  -> source-local mentions and relations
  -> candidate core/domain mappings
  -> evidence-backed review
  -> versioned scoped OntologyRevision
```

Do not create ontology terms from final UAT or independent holdout questions.
Do not use source format labels as enterprise-wide semantic truth.

## Stable Core

Keep a small cross-domain core. Initial candidates include:

```text
Actor
Person
Organization
Artifact
Document
Communication
Event
Claim
Identifier
Project
Case
WorkItem
TimeInterval
StateTransition
Location
```

The core is intentionally smaller than any source schema. Email, calendar,
ticket, project, document, database, audio, image, and other source types retain
source-local identity and map into the core where evidence supports it.

## Source and Domain Packs

A source pack defines deterministic local structure and mappings, for example:

```text
email_message -> Communication and Artifact
calendar_event -> Event
ticket -> WorkItem
document_section -> Artifact / Document
project_comment -> Claim or CoordinationFrame candidate
```

A scoped domain pack may add reviewed types, relations, frames, aliases, and
validation rules. It must not bypass candidate review, create another canonical
graph, or grant access.

## Multilingual and Identifier Policy

The target profile is
`jieba_sentencepiece_frozen_profile_candidate_admission_v1`.

Before segmentation, preserve protected spans such as:

- email addresses and URLs;
- dates, time expressions, currency, and measurements;
- part, purchase-order, invoice, ticket, project, and other configured business
  identifiers;
- mixed Chinese/English/alphanumeric identifiers;
- exact reviewed aliases.

Query and evidence use the same immutable profile fingerprint. A profile
records normalization, Jieba dictionaries, SentencePiece model/vocabulary,
protected-span policy, and candidate-admission hashes.

SentencePiece may be trained only on the calibration corpus. It is a tokenizer,
not an ontology model and not a source of canonical semantics.

## Candidate Extraction

Candidate terms and mappings may be generated through:

```text
deterministic schema/field names
frequency and contextual diversity
termhood and phrase mining
source-local identifiers
NER and relation extraction
embedding neighborhoods
LLM structured proposals
cross-source co-reference evidence
reviewer corrections
```

Every candidate records source Observation ids, source family, scope,
extractor/model/prompt revision, confidence, and proposed core/domain mapping.
LLM output remains a candidate.

## Promotion Rules

A term or mapping may be promoted only when it has:

- representative calibration/development evidence;
- defined scope and source/domain applicability;
- mapping to a stable core type where appropriate;
- ambiguity and collision analysis;
- provenance and revision pins;
- reviewer approval;
- no dependence on independent holdout content.

Low-frequency terms may still be valid identifiers. Frequency alone neither
promotes nor rejects a term.

## Retrieval Use

Ontology mappings support query planning, entity linking, evidence grouping,
and capped reranking. Inferred type/frame mismatches must not prune admitted
evidence. Hard ontology checks are reserved for governed schema, lineage,
permission, revision, and canonical-write constraints.

The legacy hard semantic gate is a negative ablation only.

## Evaluation

Evaluate separately:

- protected identifier preservation;
- Chinese/English token consistency;
- term and mention precision/recall;
- entity-link precision/recall;
- type/frame mapping precision/recall;
- false-reject count caused by ontology signals;
- cross-source mapping quality;
- transfer to a materially different source family;
- retrieval and final-answer deltas over strong RAG.

Splits are calibration, development, frozen evaluation, independent holdout,
and transfer holdout. Holdout data cannot update vocabulary, aliases, ontology,
or thresholds.

## Model Boundary

FormOwl does not train a foundation model. Existing embedding, NER, ASR,
vision, or LLM services are replaceable candidate generators. Their outputs do
not mutate canonical graph/type state or grant raw access.

The final answer model is pinned separately and held constant across RAG and
KG/ontology arms.

## Current Claim Boundary

The current runtime still reports `ascii_identifier_regex_v1` with no CJK
support. This decision describes the frozen target; it does not prove runtime
migration, source completeness, same-pipeline superiority, or methodology
readiness.
