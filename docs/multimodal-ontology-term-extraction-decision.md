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
  -> bounded offline LLM semantic reading of complete declared source scope
  -> source-linked entity/claim/event/relation/time/lineage candidates + outcome ledger
     (protected identifiers and multilingual terms are supporting signals)
  -> candidate core/domain mappings
  -> evidence-backed review
  -> versioned scoped OntologyRevision
```

Do not create ontology terms from final UAT or independent holdout questions.
Do not use source format labels as enterprise-wide semantic truth.

The 2026-10-18 product clarification is owned by SPEC §3.1.1/§6.2.1/§15.6 and
remains **待實作／待測**, not a frozen-experiment change. Ontology vocabulary
construction and applying a frozen vocabulary to source documents are separate:
the former uses calibration/development evidence only; the latter processes
authorized source content without consulting holdout questions or answer keys.
Do not use source-only annotation as a loophole for holdout-driven tuning.
Required reading includes all scoped mail attachments, bounded context and
cross-document reconciliation; regex/term extraction alone is not semantic
annotation. Use existing owners, immutable pins, incremental resumable batches
and no query-time rebuild. Complete read coverage is not proof of semantic accuracy.

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

Vocabulary/identifier candidates may be supported through:

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

Ontology-aware source annotation additionally requires LLM interpretation of
target/item, assertion/event type, temporal role and evidence-backed update links.
Every unit receives an annotated/pending/unsupported/failed outcome; a valid
zero-candidate result is different from an unread or truncated unit. Unsupported
native modalities stay explicit. Missing annotations cannot prove source absence;
supported source answers and eligible §7.3.1 fallback remain available without
relabelling baseline success as ontology completion.

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

`ascii_identifier_regex_v1` without CJK support is the dated 2026-08-18 runtime,
not current authority. The 2026-10-02 canonical container probe aligned with the
frozen target/CJK support, but source completeness, accepted fingerprint binding,
same-pipeline ablation and independent final-answer acceptance remain blocked.
Consult the executable authority for current claims. Product ontology acceptance
requires real webpage answers and original-source citation/date/relationship
checks across mail and independent non-mail cases, not parser/ledger counts.
