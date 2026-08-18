# Architecture

FormOwl uses one container-first, source-preserving architecture for
heterogeneous evidence integration. This file is the active architecture view;
historical snapshots are not implementation instructions.

## 1. Architectural Objective

FormOwl must make a governed graph useful for heterogeneous integration while
retaining a strong evidence-retrieval path.

Knowledge construction:

```text
heterogeneous source adapters
  -> Asset / EvidenceSnapshot
  -> ExtractorRun
  -> Observation
  -> candidate mentions/entities/claims/relations/frames
  -> review and canonical graph commit
  -> scoped ontology revision
  -> permission-filtered EffectiveGraphView
```

Query execution:

```text
query
  -> typed router
  -> validated SemanticQueryPlan
  -> lexical + dense evidence retrieval
  -> conservative entity linking
  -> bounded source-backed graph traversal
  -> temporal/provenance/coverage filtering
  -> capped soft ontology scoring
  -> evidence-bundle reranking
  -> deterministic executor or cited LLM answer
```

The graph does not replace evidence retrieval. It adds identity, cross-source
joins, topology, time, contradiction, provenance, and reusable governed
semantics. Ontology is a scoped and versioned aid, not a default hard filter on
otherwise valid evidence.

## 2. Ownership Boundary

The Knowledge Graph Research Agent owns semantic contracts, graph/ontology
behavior, query planning, evaluation, and research claim limits.

The FormOwl System Backbone Agent owns transport, identity, storage,
persistence, deployment, worker, and adapter plumbing behind those contracts.

The durable role split is in `docs/agent-roles.md`. A cross-track change uses a
contract-first handoff rather than creating a parallel implementation.

## 3. Logical Layers

### 3.1 Connected user boundary

```text
User / ChatGPT
  -> public HTTPS FormOwl origin
  -> FormOwl OAuth 2.1 and Google OIDC
  -> exact protected /mcp resource
  -> fresh gateway-controlled ActorContext
  -> governed semantic tools
```

The MCP Gateway is the only formal ChatGPT-facing service. Project MCP, Wiki
MCP, JSON-line, and hand-built JSON-RPC/stdio runners remain internal or local
compatibility surfaces.

### 3.2 Source and asset boundary

Every source that participates in extraction, retrieval, graph construction,
or projection is registered as an Asset or governed external evidence capture.

```text
source occurrence
  -> Asset / EvidenceSnapshot
  -> permission and retention metadata
  -> stable FormOwl locator
  -> IngestionJob or governed capture workflow
```

Byte identity, source occurrence, ownership, permission, entity identity, and
canonical merge are separate.

### 3.3 Extraction boundary

Workers run source-family adapters and write versioned ExtractorRuns,
Observations, warnings, and candidate-only semantic output.

```text
registered source
  -> deterministic technical/structural extraction
  -> source-native Observations
  -> optional semantic candidate extraction
```

Extraction cannot commit canonical graph/type state, user graph revisions, wiki
revisions, or external writes.

### 3.4 Graph-governance boundary

Graph governance owns:

```text
candidate preview and review
entity and relation resolution
source occurrence preservation
contradiction and supersession
atom granularity
scoped ontology mappings
canonical commits and lifecycle events
```

Entity matching creates proposals. It does not grant access or authorize merge.

### 3.5 Effective-view boundary

`EffectiveGraphView` combines only graph fragments currently visible to the
actor and task.

```text
canonical/user/workspace/project graph revisions
+ active grants
+ task/user assembly policy
- denied or redacted content
= EffectiveGraphView
```

Visibility of a graph assertion does not imply visibility of its evidence or
raw asset. Those are independently checked.

### 3.6 Query-execution boundary

The query engine owns:

```text
query class routing
SemanticQueryPlan validation
strong RAG retrieval
entity-aware grouping
bounded graph traversal
temporal/provenance/coverage checks
capped ontology scoring
evidence-bundle reranking
deterministic exact execution
answer claim limits
```

A planner LLM may propose a plan, but deterministic validation controls scope,
revisions, paths, budgets, coverage, and maximum claim strength.

### 3.7 Projection boundary

Answers, reports, dashboards, wiki drafts, and action proposals are derived
artifacts. They preserve evidence and execution lineage and never become
canonical graph state by implication.

## 4. Component View

```mermaid
flowchart TB
  user["User / ChatGPT"]
  edge["FormOwl OAuth + connected MCP Gateway"]
  actor["Fresh ActorContext"]
  router["Typed Router + Plan Validator"]
  executor["Hybrid Query Executor"]
  exact["Deterministic Exact Executor"]
  answer["Citation-Grounded Answer / Projection"]

  subgraph sources["Heterogeneous Sources"]
    mail["Mail"]
    cal["Calendar"]
    tickets["Tickets / Project"]
    docs["Documents / Drive"]
    db["Database / ERP / Other"]
  end

  subgraph evidence["Evidence and Extraction"]
    assets["Asset / EvidenceSnapshot"]
    workers["Extractor Workers"]
    observations["Observation Store"]
    lexical["Lexical Index"]
    dense["Dense Index"]
  end

  subgraph knowledge["Governed Knowledge"]
    candidates["Candidate Stores"]
    review["Review / Resolution"]
    graph["Canonical KG Revisions"]
    ontology["Scoped Ontology Revisions"]
    view["EffectiveGraphView"]
  end

  subgraph storage["Canonical Internal State"]
    postgres["PostgreSQL + pgvector"]
    objects["Object Store"]
    audit["Permission / Review / Audit"]
  end

  user --> edge --> actor --> router
  sources --> assets --> workers --> observations
  observations --> lexical
  observations --> dense
  observations --> candidates --> review --> graph
  review --> ontology
  graph --> view
  ontology --> view
  actor --> view
  router --> executor
  lexical --> executor
  dense --> executor
  view --> executor
  router --> exact
  observations --> exact
  executor --> answer
  exact --> answer
  assets --> objects
  assets --> postgres
  observations --> postgres
  candidates --> postgres
  graph --> postgres
  ontology --> postgres
  view --> postgres
  actor --> audit
  executor --> audit
  exact --> audit
```

## 5. Strong RAG and Graph-Guided Retrieval

Strong RAG is a first-class runtime component:

```text
BM25 or equivalent lexical retrieval
+ dense retrieval
+ deterministic fusion
+ evidence reranking
```

The graph-guided path uses the same authorized Observation snapshot. It may add:

```text
reviewed entity grouping
cross-source relation expansion
current/historical state selection
contradiction and supersession links
source coverage constraints
capped ontology bonus
```

All graph hops require authorized Observation evidence. Traversal depth,
fan-out, relation kinds, candidate count, evidence count, time, and token budget
are capped.

The runtime reranks evidence bundles rather than isolated chunks. A bundle may
contain the source observations, entity links, path proof, temporal state,
coverage status, and citations needed for one answer claim.

## 6. Deterministic Exact Execution

Queries for all members, total counts, inventories, duplicates, missing items,
aggregations, complete sets, or definitive absence cannot be answered from
ranked top-k evidence.

A validated exact executor operates over an explicitly bounded source or
effective view and returns:

```text
enumerated records
stable ordering
duplicate policy
coverage state
policy-redacted and unsupported counts
evidence lineage for every item
partial status when completeness is not proven
```

The final LLM may render this structured result, but it cannot change its
membership or coverage claim.

## 7. Ontology Architecture

The ontology has four layers:

```text
small stable cross-domain core
source-specific mappings
scoped domain packs
reviewed aliases/type/frame/relation mappings
```

All are versioned through `OntologyRevision` and preserve provenance.

Hard checks apply to permission, schema/arity, lineage, revision pins,
canonical-write preconditions, and exact-set coverage. Inferred type, frame,
alias, relation, or preferred path is a soft candidate signal. An inferred
mismatch removes only the ontology bonus, not the evidence candidate.

## 8. Model Runtime Boundary

There is no single KG model service. Runtime roles are independently
configurable and fingerprinted:

```text
planner
semantic extractor or entity linker
embedding model
reranker
final answer model
```

Every paired comparison uses the same final answer model, prompt, reasoning
effort, output schema, context budget, and generation settings.

Embedding and LLM workers write derived candidates or index projections. They
do not write canonical graph/type state or grant access.

## 9. Storage Architecture

The central identity rule is:

```text
Physical storage may be distributed.
Knowledge, authorization, and revision identity are centralized.
```

PostgreSQL is canonical for:

```text
assets and source occurrences
observations and index revisions
candidate and canonical graph state
ontology and policy revisions
permissions, grants, reviews, jobs, and audit
query plans, execution manifests, and projection metadata
```

pgvector is the dense-retrieval baseline. Raw and large binary content lives in
an object-store abstraction.

A graph data model does not require a graph database. Dedicated graph or search
engines, if ever justified, are rebuildable projections and cannot replace
PostgreSQL governance authority.

The current file-backed `FORMOWL_DATA_DIR` stores are local compatibility
implementations of the same logical interfaces, not production authority.

## 10. Identity and Permission Architecture

The connected closed beta uses one predefined OAuth client. Its client ID is a
stable non-secret selected and recorded by the deployment operator before
discovery. ChatGPT supplies and displays only the production callback
`https://chatgpt.com/connector/oauth/{callback_id}`. If the UI cannot use the
predefined client, the campaign stops as an external live blocker.

Google authenticates the human. FormOwl remains authoritative for users,
invitations, memberships, clients, token sessions, workspaces, grants,
revocation, and audit. Every protected call reloads current PostgreSQL state and
builds a fresh `ActorContext`.

Permission checks occur:

1. before source/effective-view selection;
2. before retrieval candidate materialization;
3. at every graph hop;
4. before evidence resolution;
5. before raw asset access; and
6. before review, canonical commit, projection, or external write.

Unknown scope fails closed.

## 11. Compatibility Services

Project MCP and Wiki MCP remain decoupled compatibility services behind the
connected gateway when configured.

Project MCP owns project evidence capture and proposal-only project writes.
Wiki MCP owns governed wiki draft/revision behavior and proposal-only
publishing. Both exchange portable `formowl_contract` objects and preserve
source/evidence lineage.

Their local JSON-line and JSON-RPC/stdio runners are not alternate ChatGPT
identity or authorization paths.

## 12. Deployment and Verification

Containers are the canonical development, test, and deployment boundary.
Workers process registered sources by stable identifiers and use internal
scratch space without exposing it publicly.

The active methodology target is:

```text
evidence_to_knowledge_kg_ontology_v2_hybrid_v1
jieba_sentencepiece_frozen_profile_candidate_admission_v1
```

The current runtime remains blocked on the older method/tokenizer. Before any
methodology-quality UAT or comparison claim:

```sh
python3 scripts/methodology_authority_check.py --require-ready
```

A nonzero result blocks the claim. It does not authorize another architecture
or a question-specific shortcut.

Canonical repository verification is:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local \
  python -m unittest discover -s tests
```
