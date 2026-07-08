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

## Ontology v2 Coordination-Frame Experiment

Issue #28 adds an ontology-method experiment because the scoped type ontology
is still too entity-centric for enterprise coordination. The v1 type system
remains useful as a baseline and compatibility gate, but it does not by itself
represent requests, commitments, decisions, blockers, deadlines, status
changes, dependencies, evidence spans, or follow-up obligations.

The additive v2 path is:

```text
Observation
  -> CandidateMention
  -> CandidateFrame
  -> CandidateBusinessObject
  -> CandidateRelation
  -> reviewed CanonicalFrame / CanonicalObject / CanonicalRelation
```

Current implementation files:

- `python/formowl_contract/models.py` defines `CandidateMention`,
  `CandidateFrame`, `CandidateBusinessObject`, and `CanonicalFrame`.
- `python/formowl_graph/coordination_frames.py` defines deterministic fixture
  extraction, domain-pack validation, candidate-store persistence, and
  competency-question answerability evaluation.
- `experiments/kg_ontology_v2_coordination/` contains the synthetic
  email-first cross-domain fixture, gold competency questions, and runner.
- `docs/ontology-v2-coordination-frames.md` records the method, results,
  limits, and PST boundary.

Current experiment result on the checked synthetic marker fixture:

| Arm | Candidate frames | Candidate atoms | Slot recall | Slot value recall | CQ answerability |
| --- | ---: | ---: | ---: | ---: | ---: |
| no ontology metadata only | 13 surrogate frames | 0 | 0.0 | 0.0 | 0.4375 |
| current atom path | 0 | 2 | 0.0 | 0.0 | 0.09375 |
| coordination frame v2 | 13 | 0 | 1.0 | 1.0 | 1.0 |
| hybrid v1 gate + v2 projection | 13 | 2 | 1.0 | 1.0 | 1.0 |

This is not a production parser result. It is a contract and methodology
experiment showing that the frame representation can carry the issue #28
competency-question structure under deterministic fixtures. It does not prove
production extraction quality, does not prove v2 fixes the observed email
regression, does not use raw PST content, does not commit canonical graph or
type records, does not mutate user graphs, and does not produce wiki revisions.

The current evaluator is scoped per gold case and requires complete
case-local evidence for the evidence-support competency question. Missing
locator/text-hash evidence or evidence from another case no longer counts as
answered.
The runner now reports slot-value recall, a synthetic hard-gate vs soft-gate
noise ablation, and a fixed redacted email replay effectiveness report. On the
redacted replay, KG without ontology scores exact match `0.666667`, KG plus
the current hard ontology gate scores `0.166667`, KG plus the soft ontology
gate scores `0.666667`, and both coordination-frame v2 and hybrid soft gate +
v2 score `1.0`. This reproduces the hard ontology regression on a fixed
redacted replay and gives a positive v2 effectiveness signal. It is still not
a production parser result or raw PST extraction claim; the production-quality
follow-up is to run the same five-arm rubric on private real/PST-redacted
parser output.

The first synthetic marker fixture remains available as first-version
round-trip evidence. A redesigned 100-case redacted hard challenge now adds a
larger ablation surface with 30 dev cases and 70 holdout cases. On that
challenge, KG without ontology scores exact match `0.46`, KG plus current hard
ontology scores `0.22`, KG plus soft ontology gate scores `0.74`,
coordination-frame v2 scores `0.82`, and hybrid soft gate + v2 scores `0.90`.
The 100-case result shows a real effect but not full coverage: hybrid is best,
hard ontology still regresses by `-0.24`, and 10 cases remain unsolved by the
best arm. This is still a designed redacted fixture, not private PST parser
output.

The same 100-case design is now scaled inside the runner to a deterministic
10,000-case redacted stress benchmark with 1,000 dev cases and 9,000 holdout
cases. The bucket mix is the same as the 100-case fixture, scaled by 100:
2,000 gate false rejects, 1,500 alignment-suppressed cases, 1,500 misleading
structure cases, 1,500 frame-confusion cases, 1,000 cross-thread dependency
cases, 1,000 follow-up/fallback cases, 1,000 false-positive guards, and 500
access/redaction-boundary cases. Because this benchmark repeats redacted
template families rather than using independent PST/parser output, the rates
match the 100-case stress design: KG without ontology `0.46`, hard ontology
`0.22`, soft gate `0.74`, v2 frame `0.82`, and hybrid `0.90` exact match.
The value of the 10,000-case run is count-level stress evidence: hard ontology
now produces 3,000 hard false rejects, KG without ontology produces 1,100
false positives, and the hybrid still has 100 false positives plus 900 partial
answers. It is not an independent held-out production claim.

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

## Candidate Generation Capability Profiles

The KG method now treats BERT, SentenceTransformer, NER, relation extraction,
and local LLM graph extraction as optional candidate-generation capabilities,
not as the source of ontology or canonical graph truth.

This is a feature boundary for heterogeneous remote computers:

| Profile | Intended worker | Neural network use | Output |
| --- | --- | --- | --- |
| `deterministic_cpu_candidate_generation_v1` | low-spec CPU worker | no | lexical, rule, gazetteer, and RapidFuzz-compatible `FusionCandidate` / candidate graph proposals |
| `local_embedding_candidate_generation_v1` | standard CPU worker with local model files | yes, optional | SentenceTransformer or BERT-family embeddings, pgvector similarity candidates, embedding score breakdowns, and type-alignment candidates. The preserved CPU fallback model profile is `legacy_cpu_bert` / `sentence-transformers/bert-base-nli-mean-tokens` with threshold `0.70`. |
| `accelerated_neural_candidate_generation_v1` | GPU or remote model worker | yes, optional | BERT-family NER, BERT-family relation extraction, local LLM graph extraction, multimodal semantic candidates, and large embedding batches. The current GPU default profile is `gpu_bge_large_en_v1_5` / `BAAI/bge-large-en-v1.5`, with threshold `0.62` and a one-GTX-1080-Ti / 11GB-VRAM local floor. |

All profiles preserve the same governance boundary:

- neural adapters may create observations, semantic metadata, candidate atoms,
  candidate relations, fusion candidates, type alignment candidates, embedding
  rows, and score breakdowns;
- neural adapters must not define canonical ontology state by themselves;
- neural adapters must not write canonical graph/type state;
- neural adapters must not grant raw access;
- ontology policy, candidate review, relation/entity resolution, and canonical
  commit workflows remain the decision layers.

The current default package declares these profiles and implements the
deterministic baseline path. It does not claim that BERT inference is enabled
by default. A follow-up BERT ablation branch should compare the deterministic
profile against a neural profile and persist the benchmark artifacts so the
team can evaluate the cost/quality tradeoff with evidence.

The BERT ablation branch now carries a public enterprise benchmark source
manifest at `experiments/kg_bert_ablation/public_enterprise_benchmark_manifest.json`.
That manifest selects mail/conversation, office document, financial QA,
financial report, and contract-document sources. The first completed run is a
10,000-pair model-selection benchmark preserved at
`experiments/kg_bert_ablation/results/kg_public_enterprise_benchmark_2026-06-29_bge_gpu_cu126_host.json`.
It currently uses CUAD and SEC labeled pairs; FiQA, Enron, and RVL-CDIP are
source-locked/probed but not yet labeled in the runner.

The larger completed run reaches the manifest's 50,000-pair stakeholder
evidence target and is preserved at
`experiments/kg_bert_ablation/results/kg_public_enterprise_benchmark_2026-06-29_bge_gpu_50k_cu126_host.json`.
It uses CUAD contract, SEC financial-report/company, and BEIR FiQA
financial-QA pairs.

| Run | Pairs | Accuracy | Precision | Recall | F1 | Claim |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| lexical baseline | 10,000 | 0.5216 | 0.940367 | 0.041198 | 0.078937 | deterministic low-spec path |
| BGE large GPU | 10,000 | 0.7183 | 0.931627 | 0.468248 | 0.623245 | neural model-selection evidence |
| lexical baseline | 50,000 | 0.5225 | 0.921930 | 0.042316 | 0.080918 | deterministic stakeholder benchmark baseline |
| BGE large GPU | 50,000 | 0.79986 | 0.945935 | 0.633289 | 0.758664 | neural stakeholder benchmark evidence |

BGE improves accuracy by `+0.196700`, recall by `+0.427050`, and F1 by
`+0.544308`, while precision drops by `-0.008740`. The existing 16-pair fixture
remains only a smoke/regression fixture. The 10,000-pair result is not the
50,000-pair stakeholder-grade benchmark and does not claim production latency,
canonical graph writes, canonical type writes, or raw-access authority.

On the 50,000-pair run, BGE improves accuracy by `+0.277360`, recall by
`+0.590973`, F1 by `+0.677746`, and precision by `+0.024005` over the lexical
baseline. This result sets `stakeholder_grade_claim=true` inside the artifact
only because it reaches the benchmark size target; it still does not claim
production readiness, production latency, canonical graph writes, canonical
type writes, raw-access authority, or completed human adjudication. The chart
artifact is
`experiments/kg_bert_ablation/results/charts/kg_public_enterprise_benchmark_2026-06-29_bge_gpu_50k_cu126_host_metrics.svg`.

The ontology-guidance ablation is preserved at
`experiments/kg_bert_ablation/results/kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host.json`.
It adds 10,000 cross-type hard negatives to the same public enterprise source
families. BGE-only scores accuracy `0.3999`, precision `0.235272`, recall
`0.631759`, and F1 `0.342860`, with `10177` false positives. BGE plus the
hard ontology gate scores accuracy `0.8999`, precision `0.946493`, recall
`0.631759`, and F1 `0.757744`, with `177` false positives. The ontology gate
therefore improves F1 by `+0.414884`, precision by `+0.711221`, and removes
`10000` cross-type false positives without lowering recall on this mixed
slice. The charts are
`experiments/kg_bert_ablation/results/charts/kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host_metrics.svg`
and
`experiments/kg_bert_ablation/results/charts/kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host_ontology_stress.svg`.

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

### Full-PST Mail KG Fusion Rescore Without BERT

On 2026-07-07, the #21 hard-domain full-PST baseline was rescored through a
non-BERT candidate-only KG fusion probe. The experiment reuses the preserved
full-PST domain-hard work directory and private manifest from checkpoint S, so
it does not reparse the PST and does not create new raw-mail artifacts. Public
results remain hash/status/count/timing only.

The tested graph method is intentionally narrow:

- each email body observation is treated as a candidate graph node;
- observations sharing a thread identifier are connected into candidate
  components;
- observations sharing bounded domain/conflict vocabulary terms are connected
  when the term is not too common; and
- hard-domain cases are rescored by whether the required evidence can be
  reached from the ranked candidate components.

This is not the full FormOwl ontology integration method. It does not use
`TypeDefinition`, the closed core supertype lattice, scoped extension/promoted
types, `TypeAlignmentCandidate`, ontology revision pins, BERT,
SentenceTransformer, torch, transformers, canonical KG writes, user graph
assembly, or wiki projection. It is best understood as a deterministic
candidate-graph structure ablation over mail observations.

The first preserved-workdir non-BERT KG run improved the domain-hard baseline
from 20/100 to 30/100. Positive evidence retrieval improved to 20/80,
permission-denied cases remained 10/10, and no-match near-miss cases remained
0/10. The KG graph summary had 4,965 candidate nodes, 3,460 candidate
relations, 1,505 components, largest component size 1,193, largest component
share 2,402 basis points, zero oversized components, and 103 searchable terms.
Host timing for the rescore path was 14,060 ms observation loading, 44 ms graph
build, 83 ms scoring, and 14,360 ms total, compared with the baseline import
bottleneck of 3,160,357 ms. The canonical dev-container bind-mount rerun
preserved the same counts but took 190,596 ms total, dominated by 190,366 ms
observation loading; KG build and scoring were only 28 ms and 60 ms.

A follow-up ontology-guided ablation compared the same 100 case hashes across
three arms: baseline retrieval, non-BERT candidate KG, and ontology-guided
non-BERT candidate KG. The ontology arm uses FormOwl `TypeDefinition` and
`TypeMapping` contracts, maps the ten business-function lenses into the closed
core supertype lattice as `Concept`, records a hash-bound ontology revision,
and uses type evidence as a candidate scoring/gating signal only.

That ontology-guided arm did not improve quality. It scored 29/100, compared
with 20/100 for baseline retrieval and 30/100 for the simpler candidate KG. It
kept permission-denied probes at 10/10 and no-match probes at 0/10, but
positive evidence retrieval fell from 20/80 in the pure KG arm to 19/80. The
ontology summary had 10 type definitions, 10 type mappings, zero invalid
mappings, 784 typed candidate nodes, 229 typed components, 1,571
ontology-supported relations, 1,579 basis points type-evidence coverage, 4,181
missing type-evidence nodes, and 412 conflicting type-evidence nodes.
The canonical dev-container bind-mount run preserved the same counts and took
190,695 ms total, with 190,371 ms observation loading, 70 ms KG/ontology build,
and 127 ms scoring.

The result is useful but still weak: candidate graph structure recovered 13
cases that the baseline missed, but the ontology-guided variant recovered 12
and lost one case that the simpler KG arm passed. This means the current
ontology use is valid as a candidate-only ablation, but too shallow to improve
hard mail evidence retrieval. The next research step should type observations
more precisely than broad business-function lenses, test incompatible-core
pruning on real false-positive components, and preserve ontology revision pins
without writing canonical graph/type state.

A second follow-up factorial experiment tested whether simply combining more
deterministic ontology operators would fix the quality gap. The script
`scripts/mail_full_pst_domain_hard_ontology_factorial_eval.py` evaluates every
ordered subset of five non-neural operators in one shared-load run:
`broad_domain`, `skos_expansion`, `fine_type`, `relation_slot`, and
`shacl_pruning`. With five operators this produces 326 KG arms, including the
empty operator sequence as the KG-only control. The canonical dev-container
run over the same preserved work directory completed and validated with no
blockers. Results: baseline retrieval 20/100, KG-only 30/100, best factorial
arm 30/100, best delta versus KG-only 0. Thirty-seven arms tied KG-only at
30/100 and 289 arms scored 29/100; no ordered ontology combination beat the
existing KG-only control. The best arm by the configured tie-breaker was the
empty KG-only sequence. Positive, no-match, and permission-denied counts for
the best arm remained 20/80, 0/10, and 10/10. The factorial run took 332,262 ms
total in the dev container, dominated by 310,180 ms observation loading; KG
build took 63 ms and all 326 arm scorings took 21,893 ms.

This does not prove ontology is useless. It proves that these five lightweight
operators, implemented as deterministic query expansion, broad/fine type
scoring, relation-slot scoring, and SHACL-style pruning over the current
candidate components, still do not add enough evidence-specific structure. The
next useful ontology attempt needs stronger typed candidate extraction from
mail content itself: explicit entities, documents, decisions, blockers,
commitments, dates, owners, customer/vendor/supplier roles, and typed relations
between them. Merely rearranging vocabulary-based ontology operators is now a
measured dead end for this 100-case benchmark.

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
reports blocked broad authority: 8 gates passed, 4 gates failed, and no broad
completion claim is supported.

Current passed gates:

- `external_recent_literature_baseline_protocol`
- `fair_baseline_config_artifact_content_binding`
- `scoped_ontology_integration_method`
- `different_user_kg_fusion_method`
- `annotation_protocol_controls_recovery`
- `multimodal_enterprise_controls_recovery`
- `production_adapter_controls_recovery`
- `overclaim_guard`

Current failed real-evidence gates:

- `fair_external_baseline_comparison`
- `annotation_adjudication_protocol`
- `multimodal_semantic_validation`
- `production_adapter_paths`

The authority hashes are:

- gate status:
  `596eef5f887952b4e4666f7e6b970a9199d8d3148a630cd4491ac53f0faeca1a`
- objective audit:
  `86d550fd05bfb1ab1b453e805bcfe56827a476da43186bb32e962a0b41275039`

Current status tools report `overall_passed=false`,
`objective_complete=false`, `preflight_state=blocked`, four remaining work
orders, and four progress rows at `missing_operator_response`. This blocked
state does not claim top-tier scientific validation, full product production
readiness, raw asset access, canonical graph writes, autonomous business
judgment, or enterprise-scale latency/scalability. The main repo deterministic
method suite still uses `passed_with_explicit_limits` for product-level limits.

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
- In the 20,000-pair ontology ablation, BGE-only produces `10000` false
  positives on the cross-type stress slice; BGE plus hard or soft ontology
  guidance reduces stress false positives to `0` and raises overall F1 from
  `0.342860` to `0.757744`.
- In the #21 full-PST domain-hard mail comparison, deterministic candidate
  graph componenting without BERT improved the retrieval score from 20/100 to
  30/100, but no-match near-miss cases still scored 0/10 and total quality
  remains far below the user's earlier 99/100 target.
- In the same #21 comparison, ontology-guided non-BERT candidate scoring with
  formal `TypeDefinition`/`TypeMapping` contracts scored 29/100. This is a
  negative ablation result: the current broad business-function ontology lens
  did not beat the simpler candidate KG structure.
- That negative #21 ontology result is now treated as KG-first evidence only.
  The next registered method is `docs/mail-ontology-native-factorial-design.md`:
  it builds typed mail frames, slots, values, and relations before graph fusion
  and evaluates a 324-arm ontology-native grid plus 8 controls on identical
  hard-domain case hashes.
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
| full_pst_mail_component_overreach | Deterministic thread/domain-term components retrieve related but insufficient evidence for hard business questions. | Public row-derived metrics show the 30/100 baseline, no-match failures, component size, and no canonical KG/write claim; next ablation must add ontology pins and stricter candidate typing. |
| full_pst_mail_broad_ontology_lens | A broad business-function lens maps many mail observations to `Concept` but does not distinguish the evidence relation needed by hard questions. | The ontology-guided ablation scores 29/100 versus 30/100 for pure candidate KG; future work needs finer typed atoms/relations and real false-positive pruning evidence. |

Known limitations:

- Literature comparison is design support, not a benchmark paper.
- Multimodal validation uses deterministic fixtures, not production OCR/ASR or
  video understanding.
- Human review export is not completed human annotation.
- No production-sized latency/scalability benchmark is available.
- RapidFuzz and Splink package bindings are candidate-only boundaries, not
  enterprise matching quality evidence.
- The full-PST mail KG fusion rescore is candidate-only and non-BERT; it does
  not yet prove ontology-aware mail reasoning, business answer generation, raw
  mail access, canonical graph writes, wiki projection, or production readiness.
- The ontology-native #21 factorial plan is only a pre-registered design until
  its harness, public report validation, reviewer share-back, and any required
  reruns are complete.

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
