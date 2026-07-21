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
  `Project`, `Artifact`, `Document`, `Event`, `Concept`, `Location`,
  `Transaction`, `Account`, `Agreement`, `PhysicalObject`, and `Measurement`.
- `TypeDefinition` separates `core`, `extension`, and `promoted` tiers.
- Core type definitions must use `core/formowl_core` scope.
- Extension and promoted types must use a non-core scope and source
  provenance.
- `TypeAlias` stores scoped aliases, not global synonyms.
- `TypeMapping` maps an extension or promoted type to a closed core
  supertype.
- `TypeAlignmentCandidate` is cross-scope, requires review, carries evidence
  links, and explicitly forbids canonical type writes and access grants.
- `core_supertypes_compatible()` is the only hard compatibility gate in the
  governed type-alignment workflow. It is not an evidence-retrieval gate.
  Extension and promoted labels are soft scoring signals only, and retrieval
  ontology remains capped and additive.
- `CandidateAssertion` is the source-neutral semantic umbrella for `property`,
  `relation`, `state`, `event`, and `coordination` assertions.
- `TemporalContext` gives every assertion family one vocabulary for phenomenon,
  source, observation, assertion, effective, valid, result, recorded, due, and
  supersession time. `epistemic_status` distinguishes expectations,
  commitments, requests, observations, and actual events. A separate
  `lifecycle_status` records active, cancelled, corrected, or superseded state;
  both remain separate from candidate review status.
- `captured_at` is not a Domain Pack opinion. The source-neutral pipeline binds
  it to the latest source Observation capture time, and it participates in the
  stable CandidateAssertion id and known-as-of filtering.
- Candidate materialization is a separate boundary:
  `CandidateAssertion.created_at` must not precede source capture, and
  `known_as_of` fails closed when it is absent or later than the requested
  knowledge time. It remains outside semantic identity so deterministic reruns
  can retain the same candidate id.
- `DomainPackDefinition` maps scoped object and assertion vocabulary to the
  closed core. Its normalized content hash is bound to a
  `domain_pack_definition` Observation and pinned by generated candidate ids.
  It may map domain time labels, epistemic status, and lifecycle status into the
  shared core but may not create a separate temporal pipeline.
- Procurement email observations and finance ERP/application observations use
  the same deterministic `Observation -> CandidateBusinessObject ->
  CandidateAssertion` path. Domain Packs specialize vocabulary; they do not
  create department-specific pipelines.

This keeps "Customer" in one workspace and "Client" in another workspace as a
reviewable alignment candidate. It does not grant either owner access to the
other scope's evidence and does not merge the type state.

### Data-Driven Term And Mention Extraction

The active default is recorded in
`docs/multimodal-ontology-term-extraction-decision.md`. Every text-bearing
Observation uses one source-neutral candidate stack before ontology selection,
coordination frames, entity resolution, and KG fusion:

```text
Unicode/script normalization
  -> protected ASCII identifiers
  -> Jieba
  -> corpus-bound SentencePiece
  -> frozen-profile candidate admission
```

This is broader than a tokenizer because admission, corpus evidence, Domain
Pack protection, provenance, and downstream candidate governance are part of
the method. Regex-only tokenization is now only an explicit baseline,
ablation, protected ASCII substep, or clearly reported degraded fallback. It
must not remain the silent default in any evaluator.

Large raw corpora are enough for vocabulary adaptation, phrase mining, weak
labels, and gazetteer induction. They are not, by themselves, a reliable source
of supervised typed labels. Trained models may be added later, but their output
remains candidate-only and must record model version, training manifest hash,
policy id, confidence, and source evidence.

## Universal Assertion And Coordination Experiments

Issue #28 established that a type ontology alone is too entity-centric for
enterprise coordination. The resulting `CandidateFrame` experiment remains a
specialized coordination representation for requests, commitments, decisions,
blockers, deadlines, status changes, dependencies, evidence spans, and
follow-up obligations.

The current general method is broader:

```text
Observation
  -> CandidateBusinessObject
  -> CandidateAssertion
       - property
       - relation
       - state
       - event
       - coordination
       - TemporalContext
       - epistemic_status
       - lifecycle_status
  -> CandidateTemporalView(as_of_world_time, known_as_of)
  -> governance and review
  -> reviewed canonical knowledge
```

`CandidateFrame` remains the specialized coordination path. It is not the
cross-domain umbrella and it does not make email a special ontology.

Current implementation files:

- `python/formowl_contract/models.py` defines `CandidateAssertion`,
  `CandidateMention`, `CandidateFrame`, `CandidateBusinessObject`, and
  `CanonicalFrame`.
- `python/formowl_graph/domain_packs.py` defines governed scoped vocabulary,
  closed-core mappings, content hashes, and provenance validation.
- `python/formowl_graph/candidate_knowledge.py` defines the source-neutral
  procurement/finance candidate path and candidate-only safety checks.
- `python/formowl_contract/temporal.py` and
  `python/formowl_graph/temporal_views.py` define the normalized temporal
  contract and candidate-only bitemporal filtering POC.
- `python/formowl_graph/coordination_frames.py` retains deterministic
  coordination fixture extraction and competency-question evaluation.
- `experiments/kg_ontology_v2_coordination/` and
  `docs/ontology-v2-coordination-frames.md` preserve the historical
  coordination experiment, results, limits, and PST boundary.

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

The EXM lexical candidate-admission follow-up tested all currently available
EXM PST parsed corpora with `Jieba + SentencePiece` candidate generation
across 50,000 generated same-corpus cases. The historical aggregate
artifact remains at
`experiments/kg_ontology_v2_coordination/results/exm_lexical_ontology_50000_summary_2026-07-09.json`.
Regex candidate admission solved 0/40,000 positive cases. Jieba + SentencePiece
candidate admission solved 11,811/40,000 positive cases but failed all 5,000
no-match cases. Adding the category/type scoring proxy did not change either
arm. The result therefore shows candidate-admission and lexical-graph lift, not
incremental ontology or coordination-frame lift.

The next EXM follow-up applied a weak-label MLP candidate-admission policy
before KG construction. Its historical artifact remains at
`experiments/kg_ontology_v2_coordination/results/exm_programmatic_ontology_50000_summary_2026-07-09.json`.
The policy combines document-frequency gates, protected mention handling,
deterministic weak-label candidate scoring, and exact-candidate-only retrieval.
It solves 33,369/40,000 positive cases while preserving all no-match and
permission-safety cases. This is evidence for the bundled candidate-admission
and graph-construction policy. It does not isolate type compatibility, frame
semantics, slot-value quality, or evidence-span quality.

The no-training follow-up compared the weak-label MLP against frequency-rule
and frozen-profile candidate-admission controls. Its historical artifact
remains at
`experiments/kg_ontology_v2_coordination/results/exm_no_training_programmatic_ontology_50000_summary_2026-07-10.json`.
The frequency-rule arm solves 23,277/40,000 positive cases. The frozen-profile
arm solves 33,976/40,000, 607 more than the weak-label MLP, while all three
preserve the no-match and permission-safety cases. This result established the
normative engineering default used by text-bearing candidate and evaluation
paths: Jieba plus corpus-bound SentencePiece candidate generation followed by
the frozen profile. It is not a canonical-write, ontology-semantic, or broad
production-readiness claim.

Issue #33 Work Package A corrects the generated report boundary. New reports
use `development_case_count` and `evaluation_case_count`, never a holdout label
for cases generated from a corpus and vocabulary already seen by the policy.
Arm metadata separately declares candidate admission, KG construction, type
compatibility, and frame semantics. Primary retrieval accuracy excludes
permission-denied cases; no-answer behavior and permission safety are reported
separately. The report also carries explicit `frame_type_quality`,
`slot_value_quality`, `evidence_span_quality`, `latency_and_resource_use`, and
`graph_topology_diagnostics` sections. Unmeasured semantic quality sections are
marked not measured instead of inheriting candidate-admission gains.

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

### Default Candidate Evidence Retrieval

The active retrieval method replaces the earlier thread/domain-component
heuristic. Historical 20/100, 30/100, and 29/100 results remain useful failure
evidence, but they are not the current method.

This is the required base for new hardness and harness evaluations. Historical
regex-only retrieval, parser-chunk cardinality, lexical/thread transitive
components, and ontology hard-pruning remain explicit ablation arms only; they
must not become current gold or silently replace this method.

Every index owns a `CandidateEvidenceTextPolicyRuntime` that binds the actual
query tokenizer to Unicode NFKC/script normalization, protected ASCII
extraction, Jieba, corpus-bound SentencePiece, frozen-profile admission, and
exact admission/model/corpus SHA-256 hashes. The binding also pins the runtime
id and tokenizer implementation hash; runtime code mismatch fails closed.
Default callers provide query text only; raw token overrides, free-form or
placeholder hashes, and regex-only declarations fail closed. Access and
explicit context/time admissibility complete before tokenization or ontology
resolution. Non-default transforms use `retrieve_ablation`.
Raw query text may identify control intent, evidence count, and chronology
syntax only. Retrieval anchors, actor/topic vocabulary, and supported content
terms must come from runtime-produced tokens or a named `retrieve_ablation`
extension; regex-parsed raw terms must never be added back. Access uses a real
`CandidateEvidenceAccessBinding` whose four eligibility collections are
`frozenset` values of exact nonblank strings. Cross-context comparison
authorization must be an actual boolean; string values fail closed.

The active method is implemented by `CandidateEvidenceIndex` and treats mail
as one adapter instance rather than the ontology or retrieval model. Every
observation is mapped to:

```text
one logical source item under an explicit source-identity policy
one source-version id
zero or more context boundaries
one permission-scope id
observed / known / valid time when available
epistemic and lifecycle status when available
lexical tokens and optional ontology evidence facets
```

Retrieval also requires a trusted access binding over eligible observation
ids, source-identity policies, source versions, and permission scopes. Missing
bindings fail closed. If both the index and request carry a binding, their
intersection is used so the request cannot broaden the index boundary.
Missing or empty effective access is resolved before query tokens or ontology
signals are materialized. The evaluators therefore bind requester access before
calling the corpus-bound tokenizer or ontology query-signal extractor.
Logical-source equality is
`(source_identity_policy_id, source_item_id)`, preventing equal local ids from
different adapters or identity policies from collapsing.

The planner uses universal question intents: general lookup, actor/topic,
chronology, conflict/comparison, approval/decision, and multi-source
aggregation. It derives evidence cardinality from source-unit syntax or
classifiers, never from a department or file extension. Identifier digits and
duration, money, percentage, or measurement values are not evidence counts;
this includes compact and labeled business identifiers, English and Chinese
duration phrases, and generic Chinese classifiers that are not followed by a
source noun. Periodic report nouns remain valid evidence units. An explicit
count beyond the source budget fails closed. A governed query parser may
provide the positive structured count directly, so future languages or
interfaces do not require a new retrieval branch. Support counts and IDF
operate on logical source items, so one PDF page split into many blocks, one
slide split into title/body observations, or one message split into body
segments remains one evidence item.

Permission, source-identity policy, source version, context, world time, known
time, epistemic status, and lifecycle status are applied before
supported-vocabulary planning, IDF, and ranking. Several observations may
jointly cover anchors only when they belong to the same logical source item.
Shared terms or contexts never create lexical transitive closure between
unrelated items. Chronology excludes source items without usable time from
earliest/latest selection. Accessible contexts and selected query contexts are
separate; multiple selected contexts require explicit comparison
authorization. `earliest`, `latest`, `range`, `before`, and `after` are
distinct modes, date-only boundaries require an explicit query timezone, and
range selection preserves requested cardinality. Logical-source and
observation budgets are independent.

The ontology arm now binds:

```text
ontology revision
supported evidence-signal vocabulary hash
complete TypeDefinition/TypeMapping contract hash
CandidateEvidenceIndex
```

Only signals supported by the bound ontology contract can rerank evidence.
Evidence facets derive from observation type, modality, and explicit semantic
roles, so documents/slides, structured rows, audio/video, images, and events
remain distinct. Numeric identifiers do not imply measurement. Ontology overlap
is capped and additive; it cannot delete a lexical candidate, bypass required
anchors, cross permission/context boundaries, or convert actor, time,
measurement, or relation evidence facets into canonical entity types.

The final implementation-bound 100-case MAY run on July 17, 2026 produced:

| Arm | Total | Answerable | No-match | Permission |
| --- | ---: | ---: | ---: | ---: |
| governed baseline | 11/100 | 1/80 | 0/10 | 10/10 |
| source-neutral Candidate KG | 93/100 | 73/80 | 10/10 | 10/10 |
| contract-bound ontology rerank | 93/100 | 73/80 | 10/10 | 10/10 |

Both public reports and standalone validators completed with `blockers=[]`.
The largest candidate component was 6 observations; no oversized component was
reported. The ontology arm lost zero Candidate KG passes and gained zero, which
is the intended safety result for a shallow ontology: it is usable without
hard-pruning evidence that the lexical method can support.

Primary retrieval pass/fail uses manifest-bound stable logical-source gold,
not exact parser chunk ids or source ids reconstructed from the current
Observation layout. On this run logical-source recall was 95.00%; exact
Observation citation recall was 94.37% and precision was 93.78%. Re-chunking
one stable logical source therefore leaves the main score unchanged while
stale/unmapped Observation ids, citation precision, and citation recall remain
visible as separate quality signals.

Focused tests exercise Chinese actor, chronology, and multi-record questions;
finance reporting-period and quality-lot contexts; PDF document and PPT deck
contexts; multimodal source families; observation-split anchor aggregation;
logical-source IDF invariance; explicit evidence counts; permission/time/status
admissibility; cross-context authorization; timezone-aware chronology;
source-neutral ontology facets; and ontology binding mismatches. These are
structural anti-overfitting tests, not claims of production accuracy on real
finance, quality, PDF, PPT, or OCR corpora.

This remains a candidate-only evidence-selection POC. It does not generate a
business answer, read raw assets through public tools, write canonical
graph/type state, mutate user graphs or wiki revisions, or prove production
multilingual and multimodal quality.

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
- The earlier thread/domain-component method scored 30/100 and the broad
  ontology variant scored 29/100. Those results identify component overreach
  and ontology hard-pruning as historical failure modes, not active defaults.
- The active source-neutral Candidate KG scored 93/100: 73/80 answerable,
  10/10 no-match, and 10/10 permission. It computes evidence support and IDF
  over logical source items, requires a trusted observation /
  identity-policy / source-version / permission binding, and applies
  context/time/status admissibility before planning.
- The contract-bound ontology rerank also scored 93/100 and lost zero Candidate
  KG passes. This shows that capped additive ontology guidance can avoid the
  earlier regression; it does not prove incremental ontology lift.
- Observation chunk-count invariance, multilingual query intent, explicit
  source-unit cardinality, identifier/duration-number exclusion, periodic
  report handling, context selection/comparison, timezone-aware chronology,
  source-neutral modality facets, non-whitespace access axes, access-before-
  query-vocabulary ordering, access-binding narrowing, and multi-observation
  anchor coverage are now explicit anti-overfitting tests. The factorial
  permission arm must execute retrieval and obtain `no_accessible_evidence`;
  its expected label cannot auto-pass.
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
| source_component_overreach | Thread/domain-term components retrieve related but insufficient evidence and let chunk count affect topology. | The active method has no lexical transitive closure, counts logical source items, uses conjunctive anchors, and reports a largest component of 6 on the formal run. |
| ontology_hard_pruning | A shallow ontology deletes lexically supported evidence or maps an evidence facet to the wrong entity type. | Ontology revision, signal vocabulary, and complete type/mapping contracts are hash-bound; reranking is additive/capped and lost zero Candidate KG passes. |
| context_union | Similar words from different periods, lots, documents, decks, or threads are combined as one answer. | Accessible and selected query contexts are separate; multiple query contexts require explicit comparison authorization before planning/ranking. |
| observation_chunk_bias | A parser that emits more blocks changes IDF, evidence count, or selected sources. | IDF and cardinality use logical source items; a 100-extra-chunk invariance test preserves the result. |
| missing_or_broadened_access_binding | Retrieval defaults to every indexed observation or a request overrides an index restriction. | The production index fails closed without a trusted binding and intersects request and index bindings across observation, identity-policy, version, and permission axes before planning. |
| local_source_id_collision | Two adapters emit the same local item id and are silently treated as one source. | Logical-source identity includes the source-identity-policy id; cross-policy collision tests keep the sources distinct. |
| explicit_cardinality_misread | A domain noun list misses “inspection reports” or “lots,” or an identifier/duration digit becomes an evidence count. | Source-unit grammar/classifier tests cover English and Chinese counts, while identifier and duration numbers are excluded and over-budget counts fail closed. |
| chronology_offset_inversion | Local source dates from different UTC offsets are compared as if they shared one timezone. | Chronology compares instants; date-only boundaries require an explicit query timezone and range mode preserves requested cardinality. |
| numeric_identifier_as_measurement | A lot, PO, invoice, or other numeric identifier is typed as measurement evidence. | Evidence facets use observation type, modality, and semantic roles; digits alone never activate measurement. |
| evaluator_chunk_overfit | Exact parser Observation ids determine the main pass/fail score. | Manifests store stable logical-source gold; scoring never reconstructs it from the current chunks. Exact Observation citation recall, precision, and stale/unmapped diagnostics are separate metrics. |

Known limitations:

- Literature comparison is design support, not a benchmark paper.
- Multimodal validation uses deterministic fixtures, not production OCR/ASR or
  video understanding.
- Human review export is not completed human annotation.
- No production-sized latency/scalability benchmark is available.
- RapidFuzz and Splink package bindings are candidate-only boundaries, not
  enterprise matching quality evidence.
- The 93/100 run is still one private mail-derived corpus. Structural tests
  cover finance, quality, PDF, PPT, table, OCR-style, and Chinese query shapes,
  but real cross-domain/multimodal corpora are still required before a
  production generalization claim.
- The method selects citeable evidence; it does not yet prove business answer
  generation, raw access, canonical graph writes, wiki projection, or
  production readiness.

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
