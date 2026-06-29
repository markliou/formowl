# FormOwl KG Research Method And Acceptance

This document records the current Knowledge Graph Research Agent method for
the FormOwl KG layer. It is an engineering and research acceptance artifact:
it explains why the repository uses candidate-only extraction, scoped ontology
governance, permission-aware fusion, and explicit adjudication before
canonical graph or type mutation. The current Plan B adjudication route is a
four-professional-specialist LLM subagent panel; legacy human review remains a
backward-compatible route where already supported.

## External Literature And System Comparison

Current comparison date: 2026-06-27.

| Source or system | Relevant claim | FormOwl decision |
| --- | --- | --- |
| GraphRAG paper, "From Local to Global: A Graph RAG Approach to Query-Focused Summarization" (2024), and Microsoft GraphRAG docs | GraphRAG builds a graph index from text units, extracts entities/relations/claims, clusters communities, and uses graph structures for private-corpus reasoning. | Use graph-shaped retrieval and wiki projection, but do not let LLM graph extraction write canonical graph or canonical type state. GraphRAG-style output enters candidate graph or review packets only. |
| "LLM-empowered knowledge graph construction: A survey" (2025) | LLM-based KG construction spans ontology engineering, knowledge extraction, and fusion, with schema-based and schema-free variants. | Keep deterministic extraction, ontology governance, and fusion as separate layers. LLMs may propose type labels, candidate atoms, and adjudication notes, not canonical state. |
| "Multi-Modal Knowledge Graph Construction and Application: A Survey" (2022) and MR-MKG (2024) | Multimodal KGs must align text/image and other modality evidence, not collapse everything into text-only triples. | Use `Observation` as the common multimodal substrate and preserve modality-specific locators before candidate graph generation. |
| OAEI 2024 | Ontology alignment evaluation remains track-specific and benchmark-driven across anatomy, conference, food, digital humanities, knowledge graph, pharmacogenomics, and SemTab tasks. | Defer heavy ontology matchers for v1. Use a closed core lattice plus governed scoped alignment candidates, then add OAEI-style tracks only when stable datasets exist. |
| RapidFuzz docs | RapidFuzz provides fuzzy string metrics and Python-friendly matching for labels. | Use RapidFuzz-compatible lexical matching as deterministic candidate generation only. It cannot grant access or merge canonical graph/type records. |
| Splink docs | Splink is a probabilistic record-linkage package with evaluation, graph metrics, blocking, term-frequency adjustment, and scalable backends. | Use Splink-compatible linkage for structured candidate generation and clerical review packet export. Its output is not production adapter readiness without labels, backend-scale tests, and reviewer adjudication. |
| RAGAS (2023), ARES (2023), and KILT (2020) | RAG/KG evaluation needs retrieval relevance, faithfulness, answer relevance, provenance, and human annotations or calibrated judges. | Acceptance records extraction coverage, fusion safety, ontology alignment, provenance completeness, permission safety, adjudication claim boundaries, ablations, and known missing latency/scalability evidence. |

## Ontology Integration Method

FormOwl uses a scoped emergent ontology, not a global top-down ontology.

The current code-level method is:

- `CORE_SUPERTYPE_IDS` is closed and small: `Person`, `Organization`,
  `Project`, `Artifact`, `Document`, `Event`, `Concept`, and `Location`.
- `TypeDefinition` separates `core`, `extension`, and `promoted` tiers.
- Core type definitions must use `core/formowl_core` scope.
- Extension and promoted types must use a non-core scope and source
  provenance.
- `TypeAlias` stores scoped aliases, not global synonyms.
- `TypeMapping` maps an extension or promoted type to a closed core
  supertype.
- `TypeAlignmentCandidate` is cross-scope, requires review, carries evidence
  links, and explicitly forbids canonical type writes and access grants.
- `core_supertypes_compatible()` is the only hard compatibility gate in v1.
  Extension and promoted labels are soft scoring signals only.

This keeps "Customer" in one workspace and "Client" in another workspace as a
reviewable alignment candidate. It does not grant either owner access to the
other scope's evidence and does not merge the type state.

## Multi-User KG And Fusion Experiments

The deterministic experiment in `python/formowl_graph/research_acceptance.py`
uses two users and scopes:

- `user_ops` sees a workspace organization record.
- `user_finance` owns a private organization record.
- Lexical fusion generates a same-as style candidate with score breakdown and
  ontology revision pin.
- A requester-visible rendering redacts the hidden endpoint unless both
  endpoints are visible.
- Candidate output sets `canonical_merge_performed=false` and
  `raw_access_granted=false`.

Existing focused tests also cover user graph revisions, grant-aware effective
views, and graph projection redaction:

- `tests/test_user_graph_contract.py`
- `tests/test_effective_graph_view.py`
- `tests/test_graph_resolution.py`
- `tests/test_graph_wiki_projection.py`

## Multimodal Enterprise-Data Validation

The acceptance suite checks locked observations for these enterprise resource
families:

- document/table: table observation with page/table locator
- mail/conversation: email body segment with message locator
- project/wiki: wiki section observation
- audio-style: transcript segment with time locator
- video-style: scene/keyframe locator

The repository also contains focused extractor fixtures for document, OCR,
audio, video, mail, technical metadata, text, ingestion, and wiki bridging.
These fixtures validate contract shape and provenance. They are not claims
that production OCR, ASR, diarization, video understanding, or enterprise mail
quality has been achieved.

## Human Operation, Annotation, And Adjudication Workflow

Human governance evidence is modeled as a review packet, not as completed
truth:

1. Candidate generation produces fusion/type candidates with score breakdowns.
2. Ambiguous score bands enter a clerical review queue.
3. `human_clerical_review_queue_export()` creates a packet with allowed labels:
   `same_entity`, `different_entity`, `insufficient_evidence`, and
   `request_access_overlay`.
4. Packet export can redact endpoints not visible to the assigned reviewer.
5. The packet schema says adjudication is required before a gold label.
6. The current claim boundary explicitly does not claim completed legacy human
   review, completed four-specialist LLM subagent adjudication, false-merge
   labels, canonical merge, or raw access.

Production adjudication operations still need UI/task-card work, reviewer or
subagent-panel assignment state, disagreement resolution records, and
production labels.

## Production Adapter Gate

Production adapter readiness is split into two gates:

- Candidate-only boundary gate: passed when external packages produce only
  candidates/review packets and their manifests forbid canonical writes and
  raw access.
- Broad KG real-evidence production-adapter path gate: passed in the current
  `.formowl/kg-eval` authority state through public reproducible evidence,
  rollback/permission/audit artifacts, and four-specialist
  LLM-subagent-reviewed labels using the fixed professional roles.
- Full product production readiness gate: still intentionally unclaimed until
  product-scale backend adapters, production-sized datasets, latency/scalability
  runs, and end-to-end gateway behavior are complete. Legacy human-reviewed
  labels remain accepted only for backwards compatibility where validators
  already support them.

The locked adapter stack smoke is useful boundary evidence. It does not claim:

- production entity-resolution quality
- completed legacy human review or four-specialist LLM subagent adjudication
- raw asset access
- canonical graph commits
- real OpenProject/wiki backend readiness
- database-backed production throughput

## Broad Real-Evidence Acceptance

The stricter broad KG real-evidence harness under `.formowl/kg-eval` currently
reports 12/12 broad gates passed:

- `external_recent_literature_baseline_protocol`
- `fair_baseline_config_artifact_content_binding`
- `scoped_ontology_integration_method`
- `different_user_kg_fusion_method`
- `annotation_protocol_controls_recovery`
- `multimodal_enterprise_controls_recovery`
- `production_adapter_controls_recovery`
- `fair_external_baseline_comparison`
- `annotation_adjudication_protocol`
- `multimodal_semantic_validation`
- `production_adapter_paths`
- `overclaim_guard`

The authority hashes are:

- gate status:
  `9e68c2a78681c86ff52f6ef25f20d3f6112183dcb681f137f6d349e7e4c96aba`
- objective audit:
  `b37edc1a2cf5d9891557f91f669608204998d3a8112fa0a299e3a99d082bb44d`

This completion is scoped to broad KG real-evidence acceptance. It does not
claim top-tier scientific validation, full product production readiness, raw
asset access, canonical graph writes, autonomous business judgment, or
enterprise-scale latency/scalability. The main repo deterministic method suite
therefore still uses `passed_with_explicit_limits` for product-level limits.

## Metrics, Ablations, And Error Analysis

Current deterministic metrics:

- extraction fixture family coverage: document, mail, wiki/project, audio, video
- fusion safety checks: redacted hidden endpoint, no raw access, no canonical
  merge, access overlay required
- ontology alignment checks: closed core, scoped type definitions, review
  required, no canonical type write
- provenance completeness: extension/promoted types require observation or
  candidate provenance
- permission safety: private endpoint is hidden unless both endpoints are
  visible
- adjudication claim boundary: review packet export exists, completed label
  claim is false

Current ablations:

- Without the core supertype gate, type alignment can produce false merges
  across incompatible classes.
- Without candidate review, package outputs would be overclaimed as truth.
- Without permission-aware rendering, hidden endpoints leak through fusion
  candidates.
- Without provenance requirements, type and graph revisions cannot be
  reproduced or audited.

Current error analysis cases:

| Error case | Failure mode | Detection or mitigation |
| --- | --- | --- |
| same_label_different_core_supertype | Two labels look similar but refer to incompatible classes, such as a person label and document label. | Closed core supertype gate rejects or defers the alignment candidate. |
| hidden_endpoint_visible_without_grant | A requester-visible fusion candidate exposes the other user's private endpoint. | Permission-aware rendering redacts hidden endpoints and asks for an access overlay. |
| package_output_treated_as_truth | RapidFuzz, Splink, or an LLM output is treated as canonical state. | Adapter manifests and claim boundaries keep output in candidate or review packet stores. |
| alignment_without_provenance | A type decision cannot be traced to observations or candidate records. | Extension and promoted type validators require source provenance before acceptance. |

Known limitations:

- Literature comparison is design support, not a benchmark paper.
- Multimodal validation uses deterministic fixtures, not production OCR/ASR or
  video understanding.
- Human review export is not completed human annotation.
- No production-sized latency/scalability benchmark is available.
- RapidFuzz and Splink package bindings are candidate-only boundaries, not
  enterprise matching quality evidence.

## Total Acceptance Suite

Run:

```sh
python scripts/kg_research_acceptance_suite.py
```

Use `--strict` when a CI job should fail if any requirement is failed or
blocked. The default command exits successfully because the report is intended
to expose known failed and blocked claims without hiding them.

Current expected status:

| Requirement | Expected status | Evidence |
| --- | --- | --- |
| external_recent_literature_comparison | passed | this document |
| ontology_integration_method | passed | `tests/test_ontology_contract.py` |
| multi_user_kg_fusion_experiment | passed | `tests/test_graph_resolution.py` and acceptance suite |
| multimodal_enterprise_resource_validation | passed | extractor fixture tests and acceptance suite |
| review_adjudication_claim_boundary | passed | review packet export and acceptance suite |
| production_adapter_candidate_only_boundary | passed | package manifests and adapter stack smoke boundary |
| production_adapter_readiness | failed | explicitly not claimed |
| metrics_ablations_error_analysis | passed | this document and acceptance suite |
| latency_scalability_enterprise_claims | blocked | needs production-sized datasets and backends |

## References

- GraphRAG paper: https://arxiv.org/abs/2404.16130
- Microsoft GraphRAG documentation: https://microsoft.github.io/graphrag/
- LLM-empowered KG construction survey: https://arxiv.org/abs/2510.20345
- Multi-modal KG survey: https://arxiv.org/abs/2202.05786
- MR-MKG multimodal reasoning paper: https://arxiv.org/abs/2406.02030
- OAEI 2024 results: https://oaei.ontologymatching.org/2024/results/
- RapidFuzz documentation: https://rapidfuzz.github.io/RapidFuzz/
- Splink documentation: https://moj-analytical-services.github.io/splink/
- RAGAS: https://arxiv.org/abs/2309.15217
- ARES: https://arxiv.org/abs/2311.09476
- KILT: https://arxiv.org/abs/2009.02252
