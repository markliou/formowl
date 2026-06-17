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

Physical storage may be distributed, but provenance identity is centralized. Raw storage paths are not provenance identifiers. Provenance should use stable FormOwl identifiers such as `asset_id`, `observation_id`, `extractor_run_id`, `evidence_id`, `entity_id`, `relation_id`, `workspace_id`, `user_id`, and `grant_id`.

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

## Shared Graph Provenance

When a user uses knowledge from another user's graph or private evidence, the resulting answer, graph overlay, or wiki proposal must preserve permission provenance.

Shared graph content should record:

```text
source_owner_user_id
source_scope_type
source_scope_id
source_asset_id
source_evidence_id
source_observation_id when available
extractor_run_id when available
grant_id
visible_to_user_id
visibility_scope: answer_only | graph_snippet | evidence_snippet | raw_asset
access_request_id when applicable
audit_event_id
```

For v1, prefer linked references over imported copies. A linked reference remains visible only while the grant is valid; if the owner revokes the grant, visibility is removed from the grantee's effective graph. Durable imported copies should be deferred until retention, revocation, and policy semantics are explicit.

Scope-aware canonical provenance must distinguish:

```text
match proposal -> possible equivalence or relation, no data access by itself
access overlay -> permissioned visibility, no canonical merge by itself
canonical merge -> explicit graph-state change inside a target scope
```

Canonical within one owner, workspace, project, customer, or grant-scoped fragment does not mean canonical across all scopes. Cross-scope merge decisions should record the target scope, participating entity ids, reviewer, evidence ids, conflict notes, grant context when applicable, and audit event id.

Allowed raw access locators are controlled FormOwl locators:

```text
formowl://asset/{asset_id}
formowl://evidence/{evidence_id}
formowl://message/{message_id}
```

Disallowed provenance and sharing locators include raw NAS, SMB, NFS, WebDAV, local scratch, and object-store admin paths.
