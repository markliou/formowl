# Wiki Draft Schema

<!-- Future agents: continue building wiki draft schema documentation in this file. Do not create another wiki draft schema document unless SPEC.md is updated first. -->

Wiki drafts and published wiki pages are versioned knowledge views derived from raw data, observations, candidate graph review, canonical graph state, user graph revisions, and manual edits.

The wiki workflow must be usable by non-technical users. Normal authors should work through natural-language and review-oriented actions such as save draft, submit for review, compare changes, approve, publish, refresh from sources, and restore. Git, database rows, object storage paths, hashes, and external wiki revision IDs are backend details.

## Core Rules

1. Raw data and evidence snapshots remain the source of truth.
2. Wiki drafts and pages are derived artifacts.
3. Reviewed and published wiki revisions must be immutable.
4. Regenerating or refreshing a page must create a new draft revision and a diff.
5. Restoring a page must create a new revision; it must not delete history.
6. Git may be used as a backend or audit mirror, but it must not be the required user-facing workflow.
7. Wiki revisions are output artifacts; they are not the user's full knowledge graph.
8. Raw resources should not directly generate final wiki pages; graph-aware wiki drafts should come from a `WikiProjectionSpec` applied to a context package or user graph revision.
9. Graph-aware wiki drafts should preserve links to canonical atom and user graph revisions when available.

## WikiProjectionSpec Boundary

Graph-aware wiki generation should be controlled by a projection spec rather than free-form generation.

A projection spec is now represented by the `WikiProjectionSpec` contract. It
must define:

```text
projection_spec_id
projection_kind
title
graph_revision_id
ontology_revision_id
user_graph_revision_id, optional
source_refs
evidence_snapshot_ids
citation_behavior
redaction_policy
projection_rules
draft_target
permission_scope
created_by
created_at
```

The projection spec selects what should appear in the wiki view. `WikiRevision` records the output of applying that spec, including source refs, evidence snapshots, citations, graph lineage, generator metadata, and review state.

Public projection specs must keep `include_private_evidence` false. Private
evidence can influence a draft only after a separate permissioned graph view or
retrieval flow has produced visible evidence, citations, and redaction counts.

The current Wiki MCP can generate a reviewable graph-derived draft from a
`WikiProjectionSpec` and a visible graph view through
`generate_wiki_draft_from_graph_view`. The draft frontmatter pins
`projection_spec_id`, `graph_revision_id`, `ontology_revision_id`,
`user_graph_revision_id`, `graph_view_hash`, source refs, evidence snapshot
refs, citation behavior, redaction policy, included graph node ids, and
redaction counts. Refreshing the same projection spec creates a new draft with
a diff against the previous projection draft rather than publishing or silently
overwriting a reviewed page.

## User Graph Boundary

The full model is defined in `SPEC.md` under `Multimodal Knowledge Graph and Wiki Projection Model`.

Wiki drafts may be generated from a canonical atom graph or a user's graph. That does not make the wiki draft itself the graph. A `WikiRevision` remains a governed markdown or wiki artifact with provenance, review state, and publishing metadata.

Graph-aware frontmatter may include optional lineage fields:

```yaml
projection_spec_id: artifact_page_projection_v1
included_atom_ids:
  - atom_001
  - atom_002
atom_graph_revision_id: atom_graph_rev_20260616_001
ontology_revision_id: ontology_rev_workspace_formowl_20260616_001
atom_extraction_policy_id: atom_extraction_policy_v3
atom_granularity_policy_id: atom_granularity_policy_v2
user_graph_revision_id: user_graph_rev_person_yifan_20260616_001
graph_profile_id: graph_profile_person_yifan_research_detail
assembly_policy_id: assembly_policy_method_fine_intro_coarse
graph_view_hash: sha256:...
evidence_snapshot_refs:
  - evidence_snapshot_id: ev_project_001
```

These fields are required only when the draft is generated from graph-aware inputs. The current Project MCP to Wiki MCP flow must still preserve enough `source_refs`, `evidence_snapshot_ids`, and `citations` for later observation extraction, atom extraction, candidate graph review, and user graph assembly.

## Adaptive Granularity Boundary

Canonical atoms may be split, merged, archived, or superseded over time. These changes must be represented as lineage mappings, not destructive edits.

Future graph-aware wiki drafts should remain reproducible even when atom granularity changes later. If a draft or published page cites an old atom, the old atom identifier must remain resolvable through relations such as:

```text
split_into
merged_into
summarized_by
supersedes
deprecated_by
equivalent_to
derived_from
```

User behavior may suggest that atoms should be split or merged, but it must not silently rewrite canonical atoms for everyone. User-specific behavior should first affect a user graph assembly policy or create a reviewable canonical graph change proposal.

## Revision Metadata

Every governed wiki artifact should be traceable to a `WikiRevision`.

Recommended frontmatter fields:

```yaml
revision_id: rev_wiki_20260616_001
parent_revision_id: rev_wiki_20260615_001
change_kind: source_refresh
source_refs: []
evidence_snapshot_ids: []
citations: []
revision_backend:
  type: database
  id: wiki_revision_rows/123
```

`revision_backend.type` may be `database`, `git`, `markdown-store`, `openproject_wiki`, `confluence`, `notion`, or another implementation-specific backend.

## Backend-Specific Publish Adapter Boundary

Wiki publishing targets are backend-specific, but normal users should still see
reviewable wiki actions rather than backend controls. The current Wiki MCP
routes `publish_wiki_page` through a publish adapter registry. The
OpenProject Wiki adapter prepares a backend-specific `upsert_wiki_page`
proposal with a safe target summary, content hashes, revision ids, and source
references, but it does not write to OpenProject.

Automatic publishing remains disabled by default. If a caller asks for
automatic publishing without an explicitly approved backend configuration, the
tool still returns `pending_review`, records `publish_mode: proposal_only`,
sets `external_write_performed: false`, and omits backend-internal fields such
as API URLs, credentials, raw paths, SQL, or object-store details from the
public proposal.
