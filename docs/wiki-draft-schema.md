# Wiki Draft and Projection Schema

Wiki drafts and published wiki pages are one governed output type of the active
source-preserving, graph-guided architecture. They are not the knowledge graph,
the ontology, the evidence store, or the universal endpoint of FormOwl.

Earlier atom-centric and wiki-first wording remains in repository history. The
broader pre-rewrite KG and methodology snapshot is indexed under
`docs/archive/2026-08-18/`. Current behavior is governed by `SPEC.md`,
`docs/provenance.md`, and this document.

## 1. Projection Inputs

A wiki projection may be built from one or more authorized inputs:

```text
bounded source Observations and citations
EvidenceBundle produced by a validated SemanticQueryPlan
deterministic exact result with a coverage contract
permission-filtered EffectiveGraphView
reviewed canonical graph objects
manual reviewed edits
```

A raw source adapter, parser, candidate extractor, or LLM must not publish a
final wiki page directly. Candidate knowledge must pass graph governance before
it is presented as canonical interpretation. Direct evidence-only drafts must
remain explicitly evidence-only and must not imply canonical graph truth.

The normal path is:

```text
validated input scope
  -> WikiProjectionSpec
  -> generated WikiRevision in draft state
  -> human or authorized policy review
  -> immutable reviewed/published revision
```

## 2. Core Rules

1. Source evidence and governed source captures remain the evidence authority.
2. Wiki content is derived and must preserve citations and execution lineage.
3. Reviewed and published revisions are immutable.
4. Refresh creates a new draft revision plus a diff; it never overwrites a
   reviewed revision.
5. Restore creates a new revision pointing to the historical source revision.
6. A wiki revision cannot silently mutate canonical graph or ontology state.
7. A canonical graph change cannot silently rewrite a wiki revision.
8. Hidden or denied evidence cannot affect generated content, section counts,
   graph summaries, or no-answer language.
9. External publication is proposal-first unless an explicitly authorized
   adapter and review policy permit execution.
10. Git, database rows, object-store paths, hashes, and backend revision IDs are
    backend details, not the required end-user workflow.

## 3. `WikiProjectionSpec`

A projection is controlled by a versioned `WikiProjectionSpec`, not an
unbounded free-form prompt.

Required or conditionally required fields:

```text
projection_spec_id
projection_spec_version
projection_kind
title and intended audience
source_refs and evidence_snapshot_ids
observation_ids or a safe bound-manifest reference
citation_behavior
redaction_policy
permission_scope
graph_revision_id when canonical graph content is used
ontology_revision_id when ontology mappings are used
policy_revision_id
effective_view_id when a user/task graph view is used
query_plan_id when query execution selected the evidence
query_execution_id
evidence_bundle_id or deterministic_result_id
coverage_status for exact/global content
execution_fingerprint
projection_rules and output schema
generator model, prompt, settings, and context-budget fingerprint
draft target
created_by and created_at
```

The specification must state the maximum claim strength. Evidence-only,
canonical interpretation, exact inventory, and global summary are different
projection classes and cannot silently substitute for one another.

Public projection specs keep `include_private_evidence=false`. Private evidence
may influence a draft only after a permission-filtered effective view or query
execution has produced visible evidence, safe citations, and redaction counts.

## 4. `WikiRevision`

Every draft, reviewed page, published page, refresh, and restore is represented
by a `WikiRevision`.

Minimum lineage:

```text
revision_id and parent_revision_id
projection_spec_id and version
change_kind
source refs, evidence snapshots, and Observation citations
graph, ontology, policy, effective-view, and index revisions
query plan, execution, evidence bundle, or deterministic result ids
execution fingerprint
included canonical object ids when applicable
coverage, conflict, incompleteness, and redaction summaries
generator model and prompt metadata
manual edit and reviewer lineage
review and publication state
backend target and revision reference when applicable
content hash and created_at
```

Recommended frontmatter:

```yaml
revision_id: wiki_rev_20260818_001
parent_revision_id: wiki_rev_20260817_004
change_kind: source_refresh
projection_spec_id: project_status_projection_v2
projection_spec_version: 2
source_refs: []
evidence_snapshot_ids: []
observation_ids: []
citations: []
graph_revision_id: graph_rev_20260818_003
ontology_revision_id: ontology_rev_20260818_002
policy_revision_id: policy_rev_20260818_001
effective_view_id: effective_view_20260818_user_001
query_plan_id: query_plan_20260818_021
query_execution_id: query_exec_20260818_021
evidence_bundle_id: evidence_bundle_20260818_021
coverage_status: bounded_complete
execution_fingerprint: sha256:...
redaction_count: 0
review_state: draft
external_write_performed: false
revision_backend:
  type: markdown-store
  id: governed-safe-reference
```

Backend references exposed to users must be governed safe identifiers. Raw
paths, URLs containing credentials, SQL identifiers, object-store keys, and
worker locations are forbidden.

## 5. Evidence and Graph Semantics

A projection may distinguish:

```text
source assertion
candidate interpretation
reviewed canonical interpretation
current-state graph projection
conflicting or superseded assertions
deterministic exact result
incomplete or policy-redacted result
```

Every answer-relevant node, relation, state, or event included from the graph
must resolve to visible source Observations. Ontology terms may organize
sections or labels, but inferred ontology mismatch must not remove already
admitted evidence.

Exact inventories, counts, duplicates, missing-item lists, and definitive
negative statements must come from a deterministic result with explicit scope
and coverage status. A ranked top-k EvidenceBundle cannot be relabeled as a
complete wiki inventory.

## 6. Refresh and Diff

Refreshing a projection pins a new source/evidence, graph, ontology, policy,
effective-view, index, model, prompt, and execution fingerprint as applicable.
It creates:

```text
new draft revision
parent revision reference
content and lineage diff
added, removed, changed, conflicted, superseded, and redacted summaries
review requirement
```

A changed model, prompt, tokenizer, index, graph revision, ontology revision, or
permission view is visible in the diff metadata. It is not treated as the same
execution.

## 7. Lifecycle and Identifier Stability

Canonical graph objects may be split, merged, summarized, superseded,
deprecated, or archived. Wiki revisions preserve the original cited identifiers
and resolve them through lifecycle mappings such as:

```text
split_into
merged_into
summarized_by
supersedes
deprecated_by
equivalent_to
derived_from
archived_as
```

User behavior may propose a different granularity or projection rule, but it
must not rewrite canonical objects for all users without governance.

Compatibility fields such as `included_atom_ids`, `atom_graph_revision_id`,
`atom_extraction_policy_id`, and `atom_granularity_policy_id` may still appear
in historical or serialized revisions. New projections should use the generic
canonical-object, graph-revision, policy-revision, and effective-view fields
above.

## 8. Review and Publication

Normal users work through review-oriented actions:

```text
save draft
compare changes
submit for review
approve or reject
publish
refresh from sources
restore a prior revision
```

The current Wiki MCP may prepare a graph-derived draft through
`generate_wiki_draft_from_graph_view`. It must receive a governed projection
spec and an authorized view; it cannot expand to hidden graph state.

Publishing adapters are backend-specific. The OpenProject adapter, for example,
prepares an `upsert_wiki_page` proposal with a safe target summary, hashes,
revision IDs, and source references. Unless an explicitly approved execution
path is configured, the result remains:

```text
status: pending_review
publish_mode: proposal_only
external_write_performed: false
```

No public proposal includes credentials, raw paths, SQL, object-store details,
or backend administration controls.

## 9. Acceptance Criteria

The wiki projection boundary is aligned when:

1. every generated claim traces to authorized evidence;
2. projection specs pin graph, ontology, permission, query, model, prompt, and
   execution revisions as applicable;
3. exact claims require deterministic coverage evidence;
4. refresh and restore create immutable new revisions and diffs;
5. denied evidence has no hidden influence;
6. candidate, canonical, and source assertions remain distinguishable;
7. publication is reviewed and auditable with no partial external write;
8. compatibility fields do not become the new canonical schema; and
9. public results expose only governed identifiers and safe summaries.
