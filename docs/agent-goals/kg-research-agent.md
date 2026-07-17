# Knowledge Graph Research Agent Goal

## Lifecycle

- Label: `active-blocked`
- Lossless history: `../archive/2026-07-11/kg-research-agent.md`
- Retention: keep role, current objective, status, blockers, and next action
  only; target at most 180 lines and archive before 250 lines.

## Role

Knowledge Graph Research Agent.

Durable role definition: `../agent-roles.md`.

## Current Objective

Complete the broad FormOwl KG real-evidence acceptance objective across
sessions: recent external literature comparison, fair external baselines,
ontology integration, multi-user fusion, multimodal enterprise validation,
annotation/adjudication evidence, production adapter evidence, and synchronized
total-acceptance authority.

Repository-side authority tooling is reproducible and synchronized, but broad
completion requires accepted real or public reproducible evidence rather than
additional synthetic fixtures or implementation-only proofs.

## Status

`blocked`

## Acceptance Criteria

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

Wait for operator-supplied or public reproducible response packets and
artifacts. When evidence arrives, validate the submission manifest, preflight
responses, execute candidate intakes, validate candidate manifests and
governance approval, promote only approved evidence, then rerun all broad
validators and total acceptance. Do not reinterpret an empty real-evidence
root or a passing repository-only harness as completion.
