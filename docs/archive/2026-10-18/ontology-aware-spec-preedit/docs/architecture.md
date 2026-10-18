# Architecture

FormOwl uses one container-first, source-preserving architecture for
heterogeneous evidence integration. This file is the active architecture view;
historical snapshots are not implementation instructions.

## 1. Architectural Objective

FormOwl preserves native text, structured values and binary evidence for mail,
documents, standalone spreadsheets/XLSX, tables/databases, images, speech,
non-speech audio/music, video and connected systems. A reviewed graph/ontology
overlay supplies reusable integration semantics alongside direct source execution.

Knowledge construction:

```text
heterogeneous source adapters
  -> Asset / EvidenceSnapshot
  -> ExtractorRun
  -> source-preserving Observation
       -> authorized native evidence retrieval / structured execution
       -> optional zero-to-many annotations and candidate knowledge
            -> review -> canonical KG + scoped ontology revisions
            -> permission-filtered EffectiveGraphView
```

Query execution:

```text
user prompt + bounded conversation state
  -> core Query Agent: resolve intent/coreference, discover actual capabilities
  -> expanded, validated SemanticQueryPlan / tool plans
  -> authorized modality-appropriate retrieval / native structured execution
  -> optional conservative entity linking and source-backed graph traversal
  -> temporal/provenance/coverage filtering
  -> capped soft ontology scoring
  -> evidence-bundle reranking
  -> bounded coverage inspection / repair / native source-context selection
  -> deterministic executor or cited LLM answer
```

The reviewed KG is an identity/relation overlay linked to source Observations.
It adds cross-source joins, topology, time, contradiction, provenance and
governed semantics. Ontology supplies scoped/versioned vocabulary and optional
source-addressed annotations, zero-to-many per document and Observation.
Direct authorized retrieval and native structured execution need no graph match
or annotation. Missing nodes, edges or annotations cannot establish source
absence; inferred mismatch never prunes admitted evidence.

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

Observations preserve text, structured values or governed native image-region,
audio/music-interval and video-clip/frame references. OCR/transcripts/captions
are derived representations with accuracy/coverage limits; modality-dependent
claims require native verification. Spreadsheet evidence retains raw/formula/
cached/display distinctions, source types/precision/units, blanks/nulls,
merged/header paths, coordinates and same-row association.

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
modality-appropriate strong RAG / source-native access
entity-aware grouping
bounded graph traversal
temporal/provenance/coverage checks
capped ontology scoring
evidence-bundle reranking
deterministic exact execution
answer claim limits
bounded native source-context and citation validation
```

A planner LLM may propose a plan, but deterministic validation controls scope,
revisions, paths, budgets, coverage, and maximum claim strength.
Actual source schemas, modalities, MCP contracts and graph/ontology revisions
when used are discovered and pinned. General coverage-driven plan repair remains
distinct from the §7.3.1 all-requested-fields-missing automatic recheck.

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
  executor["Authorized Source / Hybrid Query Executor"]
  exact["Deterministic Exact Executor"]
  answer["Citation-Grounded Answer / Projection"]

  subgraph sources["Heterogeneous Sources"]
    mail["Mail"]
    cal["Calendar"]
    tickets["Tickets / Project"]
    docs["Documents / Standalone XLSX"]
    media["Images / Speech / Audio / Music / Video"]
    db["Database / ERP / Other"]
  end

  subgraph evidence["Evidence and Extraction"]
    assets["Asset / EvidenceSnapshot"]
    workers["Extractor Workers"]
    observations["Source-Native Observation Store"]
    native["Authorized Native Evidence Provider"]
    modality["Modality Indexes When Supported"]
    lexical["Lexical Index"]
    dense["Dense Index"]
  end

  subgraph knowledge["Governed Knowledge"]
    candidates["Optional Zero-to-Many Candidate Annotations"]
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
  observations --> native
  observations --> modality
  observations --> candidates --> review --> graph
  review --> ontology
  graph --> view
  ontology --> view
  actor --> view
  router --> executor
  lexical --> executor
  dense --> executor
  view -. "when used; source-backed hops" .-> executor
  native --> executor
  modality --> executor
  router --> exact
  observations --> exact
  native --> exact
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

Strong RAG retrieves modality-appropriate evidence. The frozen issue #56 text
control remains:

```text
BM25 or equivalent lexical retrieval
+ dense retrieval
+ deterministic fusion
+ evidence reranking
```

Native spreadsheet access uses schemas/rows/cells/ranges; visual retrieval
verifies source regions; speech/non-speech audio/music verifies source intervals;
video verifies frames/scenes/clips with relevant audio. A text proxy cannot
prove native modality-dependent facts. Discover actual adapter/model/index
support and disclose unsupported or incomplete access. This product contract
does not change the frozen methodology/tokenizer or comparison scope.

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

Compact answer context may augment selected evidence with a bounded adjacent
paragraph/heading, table header/cell range, image crop or media clip/frame.
Each augmentation revalidates source/hash/revision/lineage/permission/native
locator and remaining budgets, retaining transformation metadata and citations.
Graph/snippet visibility grants no whole-asset access. No corpus dump or inline
extraction/index rebuild occurs; §7.3.1 automatic eligibility remains unchanged,
and its current mail/text `16 KiB` cap is not a native-media context limit.

### Source-neutral source recheck — 待測

Under the 2026-10-06 contract (`SPEC.md` §7.3.1), validated `evidence_lookup`
with a nonempty validated requested-field set and **all** fields lacking
verified support triggers one materially different, same-authorized-scope
bounded source recheck when existing safety/eligibility and remaining budgets
permit, even with unrelated citations. Partial misses must be disclosed and
must not trigger this automatic recheck. Empty field sets use the existing
validated evidence-need plan or clarification, not vacuous “all missing”.
Source-backed explicit blanks count as verified coverage; citation count or
status alone cannot trigger recheck.

The shared mail/independent-document core separates missing, unsealed, or
unactivated retrieval projections from independently validated immutable source
snapshots. Projection failure grants no independent §7.3.1 eligibility.
Eligible fallback may use those snapshots without the failed projection and
retain authorized source/hash/lineage/revision checks, permissions, and pinned budgets;
it never rebuilds inline. Exact deterministic execution and permission/schema/
provider-error boundaries remain unchanged. Incomplete scans/timeouts are not
absence; only complete source coverage proof supports a scoped complete negative.

## 6. Deterministic Exact Execution

Queries for all members, total counts, inventories, duplicates, missing items,
aggregations, complete sets, or definitive absence cannot be answered from
ranked top-k evidence.

A validated exact executor operates over an explicitly bounded authorized
source or effective view. Table lookup, filtering, joins, sorting, aggregation
and counts use validated native rows/cells/schema or a faithful revision-bound
structured projection with proved lineage/coverage. Preserve raw/formula/
cached/display distinctions, types/precision/units, blanks/nulls, merged headers,
coordinates and same-row association. The plan names value representation and
calculation semantics; cached XML alone cannot prove a fresh formula result.
Native cell/range citations and completeness are required independently of
graph/annotation coverage. Unsupported features, ambiguous headers or incomplete
rows weaken/block exact claims. The result returns:

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

The deployed bounded source-start implementation uses the existing sealed-cell reader,
typed binder and deterministic executor without a graph/dense projection.
Automatic identifier/field binding requires applicable source-provided schema,
preserves all same-row content constraints, and exposes extracted cell text.
It does not provide complete inventory, formula recalculation, native display
semantics or arbitrary arithmetic. Partial support is disclosed without an
automatic recheck; verified blanks count as support. An eligible ALL-fields
miss retains the existing same-scope recovery and remaining budgets.

## 7. Ontology Architecture

The ontology has four layers:

```text
small stable cross-domain core
source-specific mappings
scoped domain packs
reviewed aliases/type/frame/relation mappings
```

All are versioned through `OntologyRevision` and preserve provenance.
Applying vocabulary produces optional zero-to-many annotations with source
locators; it does not impose one annotation per document/Observation, cap
annotation cardinality or erase occurrences. Every answer-relevant KG hop links
to authorized evidence. Source evidence remains usable without an overlay entry.

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

At the current 2026-10-12 live checkpoint, frozen252-file r5 and validated partial
source-window000-r3 are activated on8089: mounted hashes match/drift0 and
loopback/LAN health are connected; previous live stopped/preserved for rollback.
Canonical43/43/compile/Ruff,3/3 scoped intent-delta reviews and candidate8095
native-paragraph/Observation-citation-hash/lifecycle proof passed. Post-live LAN
browser EXIT0 also verified that native paragraph/hash/citation and lifecycle.
The generic paired-verb/每 correction
supersedes r4's classifier omission; r2–r4 results remain revision-specific.
Source completeness remains false/independent-document helpers zero; post-live
known delivery remained PARTIAL/no verified date despite lifecycle EXIT0.
Missing deployment/code/build response identities
still mean `incomparable`; external content/mount proof does not override them.
Cleanup completed14:43:42Z:21 obsolete owned containers removed after evidence
preservation, no volumes/source data deleted; rollback retained and live healthy.
Finite source-order remainder backfill started14:40:41Z;
outputs are not validated/activated and the partial live source is unchanged. Code proof, partial-source activation and
full-feature/methodology acceptance remain distinct; feature待測/four gates blocked.
See the [dated handoff](agent-goals/handoff-log.md) for r5 evidence and prior failures.

Current implementation limits follow [SPEC §14](../SPEC.md#14-current-implementation-and-methodology-status):
attachment XLSX ZIP/XML values/coordinates/formal table metadata retain
formula/raw/cached metadata where available, but do not recalculate formulas or
guarantee styles/display formatting or prove native types/units/nulls or
whole-workbook coverage, or complete the standalone XLSX end-to-end path.
Merged-header paths are candidates. OCR, audio-transcript and video-scene
adapters use `read_text()` fixtures; real-image OCR/visual retrieval, real-audio
decoding/ASR/acoustic or music verification, and real-video temporal/clip/frame
verification remain unproved. Native source requirements are wider than these
diagnostic slices; unsupported features and coverage stay explicit.

The active methodology target is:

```text
evidence_to_knowledge_kg_ontology_v2_hybrid_v1
jieba_sentencepiece_frozen_profile_candidate_admission_v1
```

The recorded October 2, 2026 canonical dev-container probe matches the target
method/tokenizer with CJK support true. Readiness remains governed by the
executable authority; dated diagnostics cannot establish acceptance. Before any
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
