# FormOwl Graph-Guided Hybrid KG + Ontology Research Method

**Active program:** GitHub issue #56
**Frozen method id:** `evidence_to_knowledge_kg_ontology_v2_hybrid_v1`
**Frozen tokenizer id:** `jieba_sentencepiece_frozen_profile_candidate_admission_v1`
**Authority state on 2026-08-18:** valid but `blocked`

This document is the active research-method authority for retrieval, graph,
ontology, and comparative evaluation. Earlier mail-only, KG-first, hard-gate,
document-first, and issue #33 coordination plans are historical records only.
Their pre-rewrite text is preserved under `docs/archive/2026-08-18/`.

The objective is not to replace retrieval with a graph. The objective is to
show that a source-preserving graph can add measurable value over a **strong
RAG baseline** on questions that require heterogeneous integration, while
preserving RAG quality on direct evidence lookup.

## Research Claim

The hypothesis is:

> On source-complete, permission-equivalent evidence, graph-guided hybrid
> retrieval with reviewed entity links, bounded topology, temporal/provenance
> constraints, and capped soft ontology scoring improves final-answer quality
> on graph-required query strata over strong hybrid RAG, without material
> regression on direct lookup, citation support, no-answer behavior, privacy,
> latency, or cost.

This hypothesis is unproven. No active document may state that KG + ontology
already beats RAG. The executable authority gate must remain the claim guard.

## System Under Study

```text
heterogeneous sources
  -> Asset / EvidenceSnapshot
  -> ExtractorRun
  -> source-preserving Observation
  -> candidate mentions, entities, claims, relations, and frames
  -> reviewed/versioned canonical KG + scoped ontology mappings
  -> permission-filtered EffectiveGraphView

user query
  -> typed query router
  -> validated SemanticQueryPlan
  -> BM25 + dense candidate retrieval
  -> entity linking + bounded graph traversal
  -> temporal, provenance, and coverage filtering
  -> capped soft ontology scoring
  -> evidence-bundle reranking
  -> deterministic executor or citation-grounded LLM answer
```

Layer responsibilities are explicit:

- **RAG** recovers source evidence and remains the direct-lookup baseline.
- **KG** supplies identity resolution, cross-source joins, bounded paths,
  temporal/current-state structure, contradiction links, and provenance.
- **Ontology** supplies scoped vocabulary, type/frame mappings, validation, and
  a capped ranking prior; uncertain inferred types are not truth.
- **Deterministic execution** owns exact set, count, inventory, aggregation,
  and completeness claims.
- **The answer model** explains only the authorized evidence returned by the
  validated plan; it may not fill unresolved slots from model memory.

## Model Policy

There is no single model called “the FormOwl KG model.” A run must record each
model role separately:

```text
query planner model, if used
candidate extraction/linking model, if used
embedding model
reranker model, if used
final answer model
reasoning effort and decoding settings
prompt and output-schema hashes
```

The final answer LLM is a controlled experiment input, not a hidden advantage.
Every comparison arm must use the same answer model, reasoning effort, prompt,
context budget, and decoding settings. Changing the model creates a new
experiment and invalidates a paired comparison.

Historical candidate-generation work used
`BAAI/bge-large-en-v1.5`; the legacy CPU fallback used
`sentence-transformers/bert-base-nli-mean-tokens`. Those are embedding models,
not ontology models and not proof of a production answer LLM. The active
methodology does not name a production answer LLM until an execution manifest
pins one and the authority gate accepts the run.

## Anti-Fitting Rule

The current UAT questions are not training data, ontology source data, or an
alias dictionary. The data split is:

```text
calibration corpus -> tokenizer/profile vocabulary and protected identifiers
development corpus -> threshold selection and error analysis
evaluation corpus  -> frozen diagnostic comparison
independent holdout -> one sealed final run
transfer holdout    -> materially different source family
```

The independent holdout must be independently authored or separated by
source/time/thread, hash-sealed before execution, inaccessible to runtime
construction, and governed by a private oracle. It must not influence:

- tokenizer or SentencePiece training;
- protected-identifier patterns;
- aliases, synonyms, entity merges, or ontology mappings;
- graph construction rules;
- thresholds, routing, traversal budgets, prompts, or grading policy.

A change prompted by a failed holdout case requires a new version and a new
holdout. It may not be retroactively counted as the same frozen experiment.

## Source and Graph Construction Method

### Source-complete observations

Graph ranking cannot repair missing evidence. Before comparative evaluation,
each source adapter must be checked against a raw-source oracle or an equivalent
source-system inventory. Every missing unit must be classified as:

```text
policy redaction
unsupported source feature
extractor failure
normalization loss
deduplication or occurrence-lineage loss
unknown unexplained loss
```

Only policy-redacted units may be intentionally absent without failing source
completeness. Mail is the first validation source, not the product ontology.
Future calendar, ticket/project, document, database, and other adapters must
preserve their source-specific occurrence identity while mapping shared
semantics into the same graph.

### Candidate before canonical

An Observation is evidence, not a canonical fact. Extractors and LLMs may emit
candidate mentions, entities, claims, relations, and frames. They may not
silently commit canonical nodes, edges, types, user-graph revisions, or output
revisions.

Entity resolution uses deterministic identifiers and reviewed mappings first,
then lexical, embedding, probabilistic, graph-neighborhood, or LLM-assisted
signals. Uncertain matches remain reviewable candidates. Matching never grants
access and never erases source occurrences.

### Scoped, data-first ontology

The ontology consists of:

1. a small stable cross-domain core;
2. source-specific mappings that preserve local meaning;
3. scoped domain packs induced from calibration/development evidence;
4. reviewed aliases, mappings, and promoted types;
5. versioned ontology revisions with provenance.

The stable core should remain small enough to transfer across domains. Candidate
concepts include Actor, Person, Organization, Artifact, Document,
Communication, Event, Claim, Identifier, Project, Case, WorkItem, TimeInterval,
StateTransition, and Location.

Hard fail-closed checks are limited to permission/scope, schema/arity,
evidence lineage, revision pins, canonical-write preconditions, and explicit
coverage contracts. Inferred type, frame, alias, relation, and ontology-path
compatibility are soft candidate signals.

The default ontology contribution is capped and additive. An inferred mismatch
receives no bonus but must not delete or zero an otherwise admitted evidence
candidate. The legacy hard type/frame gate exists only as a named negative
ablation.

## Query Classes and Execution

| Query class | Required execution |
| --- | --- |
| `evidence_lookup` | strong lexical+dense retrieval, optional entity linking and bounded evidence expansion |
| `relation_reasoning` | provenance-constrained typed traversal plus source evidence for every hop |
| `exact_set_or_inventory` | validated deterministic structured executor and explicit coverage contract |
| `global_summarization` | bounded, permission-filtered source/evidence set with incompleteness disclosure |

A `SemanticQueryPlan` may be proposed by an LLM, but deterministic validation
must enforce query class, workspace/scope, source bounds, graph and ontology
revisions, allowed relations, hop limits, candidate limits, time budget,
evidence budget, output schema, and maximum claim strength.

The runtime may perform one bounded repair pass when required entity, relation,
temporal, or evidence slots remain unresolved. It must not broaden permissions,
sources, or claim strength. The historical exactly-one-document-call POC is not
a methodology constraint.

No ranked top-k path may claim a complete set, definitive negative, or total
count. Those claims require deterministic enumeration and coverage evidence.

## Comparative Arms

Every arm shares source snapshot, permission view, tokenizer profile, answer
LLM, prompt, context budget, evaluator, and execution environment.

1. **Strong hybrid RAG:** BM25 + dense retrieval + evidence reranking.
2. **RAG + entity linking:** same retrieval plus identity-aware grouping.
3. **RAG + candidate KG:** bounded graph topology without ontology bonus.
4. **RAG + KG + soft ontology:** capped ontology/frame contribution.
5. **Legacy hard ontology gate:** negative ablation only.
6. **Deterministic structured execution:** mandatory for exact-set classes.

Candidate admission, graph topology, ontology treatment, and execution mode must
remain separate factors. Gains from tokenizer migration, better evidence
coverage, or candidate admission must not be relabeled as ontology gains.

## Evaluation Strata

Report each stratum separately:

- single-document direct lookup;
- cross-message and cross-source joins;
- entity ambiguity and identity resolution;
- temporal current/historical/superseded state;
- contradiction and provenance;
- exact set, count, inventory, and aggregation;
- no-answer and near-miss negatives;
- permission-denied and cross-scope cases.

Mail-first evaluation must be followed by at least one transfer-domain holdout,
such as calendar, ticket/project, or document-section evidence. The core
ontology and plan schema must transfer without question-specific core types or
aliases.

## Metrics and Decision Gate

Required metrics include:

- final-answer correctness by stratum;
- required-evidence Recall@k and evidence-bundle coverage;
- citation support precision and recall;
- entity-resolution precision and recall;
- relation/path precision and unsupported-hop count;
- temporal/current-state accuracy;
- exact-set precision, recall, F1, duplicate rate, and coverage status;
- no-answer precision/recall and false-positive count;
- permission leakage and cross-scope traversal attempts;
- p50/p95 latency, CPU, peak memory, model tokens, and cost;
- paired arm transitions and confidence intervals.

Pre-registered initial replacement gate:

- graph-required strata improve final-answer correctness by at least 10
  percentage points over strong RAG with a positive paired confidence interval;
- direct lookup regresses by no more than 2 percentage points;
- citation support precision is at least 95%;
- no-answer false-positive performance does not regress;
- permission/private-evidence leakage remains zero;
- every returned graph assertion resolves to authorized Observation evidence;
- latency and cost remain inside a separately frozen budget.

If the gate fails, strong RAG remains the answer-retrieval default. KG may still
serve integration, governance, provenance, lifecycle, and reviewed projection
use cases, but no superiority claim is allowed.

## External Literature And System Comparison

The comparison set is used to define competitive baselines and evaluation
practice, not to import an external system as FormOwl's architecture.

- **GraphRAG** motivates separating source-text retrieval, graph-derived global
  structure, and answer synthesis; FormOwl additionally requires governed
  permissions, canonical review, and source-resolvable graph assertions.
- **OAEI** motivates explicit ontology-alignment tasks, gold mappings, and
  precision/recall reporting rather than assuming type labels are correct.
- **RapidFuzz** is a deterministic lexical candidate-generation baseline, not
  an entity-resolution decision maker.
- **Splink** represents probabilistic record-linkage baselines whose scores
  create review candidates rather than access or merge authority.
- **RAGAS** represents answer/retrieval evaluation patterns; FormOwl also
  requires deterministic exact-set metrics, permission leakage checks,
  execution fingerprints, and independent oracle governance.
- BM25, dense retrieval, reciprocal-rank or learned fusion, and evidence
  reranking form the minimum strong RAG control.

External comparison must use equivalent evidence, budgets, permissions, and
answer generation. A weak regex or substring baseline is not sufficient.

## Historical Compatibility Evidence — Not Active Methodology

The following strings remain in this active file only because repository tests
and packaged historical benchmark readers verify that old artifacts stay
traceable. They do **not** establish the current target runtime, real-source
superiority, or a recommended hard ontology gate.

- `kg_public_enterprise_benchmark_2026-06-29_bge_gpu_cu126_host.json` reported
  BGE candidate-matching F1 `0.623245` and was described as model-selection evidence.
- `kg_public_enterprise_benchmark_2026-06-29_bge_gpu_50k_cu126_host.json`
  reported candidate-matching F1 `0.758664`.
- `kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host.json` reported historical
  candidate-only F1 `0.757744` for an artificial cross-type stress ablation.

These artifacts compare candidate matching under their historical manifests.
They are not same-pipeline final-answer evidence and may not be used to claim
that KG + ontology beats strong RAG.

## Authority and Completion

Before methodology-quality UAT, comparative claims, or completion:

```sh
python3 scripts/methodology_authority_check.py --require-ready
```

As of 2026-08-18 it exits nonzero because:

- runtime method/tokenizer do not match the frozen target;
- raw-source-to-Observation completeness is unverified;
- reports do not bind one accepted execution fingerprint;
- same-pipeline real-source ablation is missing;
- real-user final-answer acceptance is missing.

Diagnostic development may continue while every report states this blocked
boundary. Implementation completion and comparative close are separate:

- **Implementation complete:** target path, tests, fingerprints, frozen
  diagnostic evaluation, docs, and reviewer gate are complete.
- **Comparative close:** independent holdout and transfer-domain results pass
  the pre-registered quality/safety/cost gate and executable authority becomes
  ready.

GitHub issue #56 remains the active work program. Issues #33 and #55 are
historical context only; neither is an active execution plan or evidence that
the target method works.
