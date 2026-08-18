# Hybrid KG + Ontology v2 Architecture Boundary

**Active program:** GitHub issue #56
**Method id:** `evidence_to_knowledge_kg_ontology_v2_hybrid_v1`
**Status on 2026-08-18:** architecture target frozen; runtime authority blocked

This document defines the implementation boundary for FormOwl's graph-guided
hybrid retrieval and answer path. It supersedes the active use of the old
issue #33 storage comparison, mail-first KG ranking, and hard ontology gate.
The pre-rewrite document is immutable history under
`docs/archive/2026-08-18/`.

## 1. Non-Negotiable Architecture

```text
source adapters
  -> Asset / EvidenceSnapshot
  -> ExtractorRun
  -> Observation
  -> candidate mentions/entities/claims/relations/frames
  -> reviewed canonical KG + scoped ontology
  -> permission-filtered EffectiveGraphView

query
  -> typed router
  -> validated SemanticQueryPlan
  -> lexical + dense retrieval
  -> entity linking + bounded graph traversal
  -> temporal/provenance/coverage filtering
  -> capped soft ontology scoring
  -> evidence-bundle reranking
  -> deterministic executor or cited LLM answer
```

There is one evidence-to-knowledge pipeline. Mail, calendar, tickets, project
systems, documents, databases, and future adapters may add source-specific
observations and mappings, but they must not create parallel truth stores,
ontologies, indexes, or answer services.

## 2. Layer Ownership

### Resource extraction

Owns deterministic and semantic extraction into Observations and candidate
records. It does not commit canonical truth or generate definitive business
answers.

### Graph governance

Owns entity/relation proposals, review, canonical commits, lifecycle,
contradiction/supersession, scoped ontology revisions, and source lineage.

### Effective view

Owns permission and grant filtering, graph revision selection, task/user scope,
and redaction. Entity matching does not grant access.

### Query execution

Owns routing, plan validation, candidate retrieval, bounded traversal,
evidence-bundle construction, deterministic structured execution, and answer
claim limits.

### Projection

Owns cited answers, reports, dashboards, wiki drafts, and reviewed action
proposals. A projection never becomes canonical graph state by implication.

## 3. Strong RAG Is a Required Component

FormOwl must not use graph retrieval as a substitute for source evidence.
Strong RAG is both a production fallback and the competitive baseline:

```text
BM25 or equivalent lexical retrieval
+ dense retrieval
+ deterministic fusion
+ evidence reranking
+ citation and answer-claim contract
```

The graph path must earn its use by adding identity, cross-source joins,
bounded topology, temporal state, contradiction, provenance, and coverage.
If those additions do not meet the frozen quality gate, strong RAG remains the
default answer-retrieval path.

## 4. Query Router

The router produces one of four classes:

| Class | Required path |
| --- | --- |
| `evidence_lookup` | strong RAG, with optional entity-aware grouping and bounded expansion |
| `relation_reasoning` | typed, provenance-constrained traversal plus source evidence for every hop |
| `exact_set_or_inventory` | deterministic structured executor and coverage contract |
| `global_summarization` | explicitly bounded authorized source/evidence set |

Routing is deterministic when the user asks for count, all, every, inventory,
missing, duplicate, exact membership, or a definitive negative. Ambiguous
claim strength must be reduced or clarified; it must not silently become an
exact-set claim.

## 5. SemanticQueryPlan Contract

An LLM may propose a plan, but executable validation is deterministic. A plan
must pin at least:

```text
plan schema version
query class
actor/workspace/task scope
allowed source families and source bounds
permission/effective-view revision
graph revision and ontology revision
entity and relation slots
allowed edge kinds and direction
hop, candidate, evidence, token, time, and repair budgets
temporal/current-state policy
coverage requirement
output schema and maximum claim strength
planner model/prompt/settings fingerprint, when used
```

Invalid, under-specified, scope-widening, or revision-unbound plans fail closed.
One bounded repair pass is allowed only inside the original source and
permission scope.

## 6. Candidate Retrieval and Scoring

The runtime materializes evidence candidates only after permission filtering.
A score may expose independently inspectable components:

```text
lexical score
dense score
entity-link score
graph-path score
temporal/current-state score
provenance and coverage score
capped ontology bonus
```

Rules:

- evidence bundles, not isolated chunks, are the reranking unit;
- each graph hop must resolve to one or more authorized Observations;
- traversal depth, edge kinds, fan-out, candidate count, and execution budget
  are capped;
- graph and ontology signals cannot compensate for absent source evidence;
- hidden or denied nodes are not materialized and do not influence scores;
- fallback retrieval creates no hidden candidate or canonical writes.

## 7. Hard Invariants and Soft Semantics

### Hard fail-closed invariants

- authentication, permission, workspace, tenant, and grant scope;
- source and evidence lineage;
- schema, relation arity, and identifier shape;
- pinned graph, ontology, policy, tokenizer, model, and evaluator revisions;
- canonical-write review preconditions;
- deterministic coverage contracts for exact-set claims;
- public-output redaction and internal-leak rules.

### Soft candidate signals

- inferred entity type;
- frame compatibility;
- alias or synonym mapping;
- inferred relation;
- preferred ontology path;
- embedding and neighborhood similarity.

Soft signals may boost an admitted candidate by a capped amount. An inferred
mismatch receives no boost but does not delete or zero the candidate. The
legacy hard type/frame gate is a negative ablation only.

Explicitly reviewed core-supertype incompatibility may block a **canonical
merge proposal**. That governance decision is separate from answer retrieval
and does not remove the underlying authorized evidence.

## 8. Ontology Boundary

The ontology is scoped and data-first:

```text
small stable core
+ source adapter mappings
+ scoped domain packs
+ reviewed aliases/type mappings/frame mappings
+ versioned OntologyRevision
```

Core types must remain cross-domain. Source-specific records retain their local
type and occurrence identity while mapping to shared concepts. Calibration and
development evidence may propose terms and mappings. Independent holdout
questions and answers may not.

Ontology construction does not train a neural network. Embedding or LLM tools
may generate candidates, but promotion requires evidence, scope, revision, and
review.

## 9. Exact-Set and Deterministic Boundary

Ranked retrieval cannot prove completeness. Queries asking for all members,
counts, inventory, duplicates, missing items, or definitive absence must use a
schema-validated executor over an explicitly bounded source/effective view.

The result must report:

```text
scope and revision
enumerated item count
coverage status
policy-redacted count
unresolved or unsupported count
duplicate policy
stable ordering
evidence lineage for each item
```

If coverage is incomplete, the output must say so and reduce claim strength.

## 10. Canonical Graph Boundary

Extractors, planners, retrieval, and answer models may not directly write:

```text
CanonicalGraphStore
canonical type state
UserKnowledgeGraph revision
WikiRevision
external business-system state
```

Canonical commits require reviewed candidates, source observations, permission
scope, ontology/policy revisions, previous and new graph revisions, and audit.
Lifecycle changes preserve old identifiers and occurrence lineage.

## 11. Model Boundary

The architecture does not depend on one vendor LLM. Each run separately pins
planner, extractor/linker, embedding, reranker, and answer-model identities.
All comparative arms use the same final answer model and settings.

Historical BGE/BERT candidate-generation containers remain optional experiment
tools. Their embeddings are not canonical truth, ontology, authorization, or a
final-answer model.

## 12. Storage Decision

PostgreSQL remains the canonical authority for graph, ontology, provenance,
permission, review, and audit state. pgvector remains the default vector
baseline. No Neo4j migration, projection benchmark, dual write, or architecture
change is active under issue #56. A graph data model does not require a graph
database.

## 13. Source Completeness and Provenance

Before graph comparison, the authorized Observation snapshot must be reconciled
against a raw-source or source-system oracle. Each Observation, candidate,
canonical assertion, graph hop, evidence bundle, and answer citation must retain
stable lineage to its source and execution revisions.

Required mail-first structure includes message/thread occurrence, participants,
subject/body spans, timestamps, quoted/forwarded links, attachments/tables,
identifiers, versions/conflicts/supersession, permissions, and extractor
provenance. Other adapters must provide equivalent source-native structure.

## 14. Security Boundary

Permission checks run before candidate materialization and at every traversal
hop. Matching, graph visibility, evidence visibility, raw asset access, and
canonical merge are independent decisions. Unknown scope fails closed.

Public output must not contain raw paths, SQL, storage or parser details,
credentials, oracle values, hidden identifiers, or unrelated private evidence.

## 15. Active Work Packages

- **A:** immutable target tokenizer/profile and same-profile query/evidence
  indexing.
- **B:** source-complete Observations and conservative graph construction.
- **C:** scoped data-first ontology with soft retrieval semantics.
- **D:** typed router, validated plan, hybrid retrieval, bounded traversal, and
  deterministic exact-set execution.
- **E:** controlled, citation-grounded LLM behavior.
- **F:** strong RAG comparison, anti-fitting split, independent holdout, and
  transfer-domain evaluation.

Implementation details and promotion gates are in
`docs/kg-ontology-v2-runtime-evaluation-plan.md`. Research claims and metrics
are in `docs/kg-research-method.md`.

## 16. Current Claim Boundary

`python3 scripts/methodology_authority_check.py --require-ready` currently exits
nonzero. Diagnostic implementation may proceed, but methodology-quality UAT,
KG/ontology superiority, default-path replacement, and completion claims may
not.

Issue #33 and the document-first issue #55 POC are historical only. They are not
active instructions and must not be used to bypass issue #56 or the executable
authority.
