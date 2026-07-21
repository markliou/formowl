# Knowledge Graph Research Agent Goal

## Lifecycle

- Label: `active`
- Lossless history: `../archive/2026-07-11/kg-research-agent.md`
- Retention: keep role, current objective, status, blockers, and next action
  only; target at most 180 lines and archive before 250 lines.

## Role

Knowledge Graph Research Agent.

Durable role definition: `../agent-roles.md`.

## Current Objective

Complete the bounded source-neutral Task Answering methodology slice while
preserving the separate broad FormOwl KG real-evidence objective across
sessions.

The active bounded slice separates:

```text
TaskFrame revision
-> EvidenceRequirement
-> Candidate evidence retrieval
-> permission-filtered source-item field assembly
-> EvidenceCoverage
-> AnswerabilityDecision
-> content-first AnswerProjection
```

It must generalize across mail, documents, tables, application events, and
future source shapes. It must not introduce procurement-specific aliases,
source-specific query methods, UI-defined evidence completeness, canonical
writes, or external actions.

Repository-side authority tooling is reproducible and synchronized, but broad
completion requires accepted real or public reproducible evidence rather than
additional synthetic fixtures or implementation-only proofs.

## Status

`active`

## Acceptance Criteria

- TaskFrame follow-ups preserve prior anchors, hard constraints, retrieval
  semantics, and evidence requirements unless the new utterance revises them.
- Retrieval reports total and returned logical-source counts plus explicit
  exhaustive/has-more state; all-matching does not use corpus size as a fake
  exact count.
- Evidence assembly can recover content from admissible observations inside a
  selected logical source item even when another observation matched search.
- Projection defaults to content and keeps sender, recipient, headers,
  filenames, and other metadata secondary unless explicitly requested.
- Answerability distinguishes permission denial, missing target, absent
  property, partial evidence, conflict, and sufficiency.
- Mail, PDF/TXT, XLSX/table, and application-event tests use the same contracts.
- Canonical dev-container verification, relevant docs, and the required
  reviewer gate pass before the board item is marked complete.

- Canonical authority reports agree on 12 passed gates, zero failed gates, zero
  remaining gates, and a complete objective audit.
- Each broad gate is backed by an accepted canonical evidence packet rather than
  a template, preview, candidate-only packet, or local ignored artifact.
- Total acceptance, objective audit, preflight, work orders, progress, and the
  tracked checklist all describe the same passing authority state.
- Canonical dev-container verification, relevant research checks, full Ruff,
  `git diff --check`, durable docs, and the required reviewer gate pass.
- Claims remain bounded: broad acceptance does not imply raw asset access,
  autonomous business judgment, canonical graph/type writes, or unrestricted
  production readiness.

## Blockers

The bounded Task Answering slice passed 895 canonical dev-container tests,
full Ruff, 345-file format check, and `git diff --check`. The required
3-reviewer gate remains before completion.

Four real-evidence gates still lack accepted canonical evidence:

- `fair_external_baseline_comparison`
- `annotation_adjudication_protocol`
- `multimodal_semantic_validation`
- `production_adapter_paths`

The completed Candidate Assertion, Domain Pack, Issue #16
temporal-evidential POC, and 93/100 source-neutral Candidate evidence retrieval
iteration are bounded candidate-layer implementation slices. They add no
canonical writes and do not satisfy or weaken these four broad evidence gates.

Default Candidate Evidence Retrieval remains the mandatory base for any future
response packet or evaluation harness: stable logical source item counting,
access/time/context filtering before planning, no lexical transitive closure,
and capped additive ontology reranking. Regex-only, parser-chunk,
component-union, and ontology hard-pruning behavior is ablation-only.
The index-owned `CandidateEvidenceTextPolicyRuntime` binds the actual query
tokenizer to the structured Unicode-NFKC/protected-ASCII/Jieba/corpus-bound
SentencePiece/frozen-profile policy and exact SHA-256 hashes. The binding also
pins the runtime id and tokenizer implementation hash; runtime code mismatch
fails closed. Default callers provide query text only and cannot supply raw
tokens or a free-form hash. Access and explicit context/time admissibility
precede tokenization; experiments use `retrieve_ablation`.
Raw query text may identify control intent, evidence count, and chronology
syntax only. Retrieval anchors, actor/topic vocabulary, and supported content
terms must come from runtime-produced tokens or a named `retrieve_ablation`
extension; regex-parsed raw terms must never be added back. Access uses a real
`CandidateEvidenceAccessBinding` whose four eligibility collections are
`frozenset` values of exact nonblank strings. Cross-context comparison
authorization must be an actual boolean; string values fail closed.

## Next Action

Complete the required reviewer gate for the Task Answering slice before marking
the work-board item complete. After that bounded slice, return to waiting for
operator-supplied or public reproducible response packets for the four broad
real-evidence gates. Do not reinterpret a passing repository-only harness as
broad KG objective completion.
