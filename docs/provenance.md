# Provenance

<!-- Future agents: continue building provenance rules in this file. Do not create another provenance document unless SPEC.md is updated first. -->

Provenance is the invariant that connects raw resources, extracted observations, graph state, user graph revisions, and wiki artifacts.

## Traceability Chain

```text
Raw Resource
  -> Asset / EvidenceSnapshot / Citation
  -> Observation / SemanticMetadata
  -> CandidateAtom / CandidateRelation
  -> CanonicalAtom / CanonicalEntity / CanonicalRelation
  -> UserKnowledgeGraphRevision
  -> WikiProjectionSpec
  -> WikiRevision
```

Every generated or derived object should preserve enough identifiers to trace backward to the source material and forward to the artifacts that used it.

## Minimum Lineage Rules

Observations should record:

```text
asset_id or evidence_snapshot_id
source_ref
extractor name, version, model, and run id
location metadata such as timestamp, page, bounding box, frame, speaker, section, or message sequence
confidence
permission_scope
```

Candidate graph objects should record:

```text
source_observation_ids
source_refs
evidence_snapshot_ids
extractor or generator metadata
candidate granularity
confidence
review state
```

Canonical graph objects should record:

```text
source_candidate_ids
source_observation_ids
source_refs
evidence_snapshot_ids
policy ids
commit event ids
lifecycle event ids
confidence or review status
```

User graph revisions should record:

```text
canonical graph revision id
assembly policy id
included atom ids
excluded atom ids where relevant
permission scope
created_at
status
```

Wiki revisions should record:

```text
source_refs
evidence_snapshot_ids
citations
projection_spec_id when graph-aware
user_graph_revision_id when graph-aware
included_atom_ids when graph-aware
generator metadata
review state
backend revision reference
```

Source preservation alone is necessary but not sufficient. The core provenance contract must also explain how extracted semantic metadata became candidate graph state, how candidates became canonical graph state, and how graph state became a wiki artifact.
