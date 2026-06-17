# Architecture

<!-- Future agents: continue building the system architecture documentation in this file. Do not create another architecture document unless SPEC.md is updated first. -->

FormOwl uses a container-first architecture and a graph-governed knowledge pipeline.

The canonical development, test, and deployment environment is a container. Host-installed runtimes are optional conveniences, not required assumptions.

## Target Knowledge Pipeline

```text
Raw Resources
  -> Resource Extraction Layer
  -> Observation Store
  -> Candidate Graph
  -> Governed Canonical Graph
  -> User Knowledge Graph
  -> Wiki Projection Layer
  -> WikiRevision
```

Raw resources include project system records, wiki pages, ChatGPT conversations, markdown, PDFs, office documents, images, audio, video, screenshots, and other captured files.

The pipeline rule is strict: raw resources do not directly become final wiki pages. They first become observations and semantic metadata, then candidate graph objects, then governed canonical graph state, then user-specific graph views, and only then projected wiki revisions.

## Governance Layer

Governance crosses every stage of the pipeline.

Policy objects should include:

```text
ExtractionPolicy
AtomGranularityPolicy
OntologyPolicy
EntityResolutionPolicy
RelationResolutionPolicy
LifecyclePolicy
UserGraphAssemblyPolicy
WikiProjectionPolicy
```

External extractors and LLM graph tools may create observations, candidate atoms, candidate relations, or external graph imports. They must not directly mutate canonical graph state.

## Store Boundaries

```text
AssetStore -> raw resource metadata
ObjectStore -> raw binary files
ObservationStore -> extracted observations
CandidateAtomStore -> uncommitted candidate atoms and relations
CanonicalGraphStore -> canonical atoms, entities, relations, lifecycle events, and graph revisions
UserGraphStore -> user-specific graph revisions
WikiStore -> wiki drafts, revisions, snapshots, and publish proposals
VectorStore -> embeddings for similarity search
JobStore -> ingestion and extraction job status
```

Project MCP and Wiki MCP are current service boundaries inside this larger architecture. Future ingestion and graph services should share contracts with them instead of depending on their internals.

## Language Boundaries

Python is the default language for MCP orchestration, adapters, workflow glue, review flows, test fixtures, and day-to-day debugging.

Rust owns heavy computing, safety-sensitive logic, parsers, canonical serializers, validation cores, hashing, integrity checks, concurrent processing, large raw-data transforms, and any feature whose Python implementation would expose strange or hard-to-maintain syntax.

Rust core functionality should be exposed to Python through stable bindings. Normal contributors should interact with clear Python APIs unless they are working on a core algorithm, safety boundary, or binding implementation.

## Syntax Shielding

When Python code would require unusual metaprogramming, deeply nested decorators, generated code, fragile regular expressions, complex DSLs, or unsafe dynamic evaluation, the complexity belongs behind a Rust core API.
