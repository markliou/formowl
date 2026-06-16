# Wiki Draft Schema

<!-- Future agents: continue building wiki draft schema documentation in this file. Do not create another wiki draft schema document unless SPEC.md is updated first. -->

Wiki drafts and published wiki pages are versioned knowledge views derived from raw data.

The wiki workflow must be usable by non-technical users. Normal authors should work through natural-language and review-oriented actions such as save draft, submit for review, compare changes, approve, publish, refresh from sources, and restore. Git, database rows, object storage paths, hashes, and external wiki revision IDs are backend details.

## Core Rules

1. Raw data and evidence snapshots remain the source of truth.
2. Wiki drafts and pages are derived artifacts.
3. Reviewed and published wiki revisions must be immutable.
4. Regenerating or refreshing a page must create a new draft revision and a diff.
5. Restoring a page must create a new revision; it must not delete history.
6. Git may be used as a backend or audit mirror, but it must not be the required user-facing workflow.
7. Wiki revisions are output artifacts; they are not the user's full personal knowledge graph.
8. Future graph-aware wiki drafts should preserve links to canonical atom and user graph revisions when available.

## Personal Graph Boundary

The full model is defined in `SPEC.md` under `Personal Knowledge Graph and Canonical Atom Model`.

Wiki drafts may eventually be generated from a canonical atom graph or a user's personal graph. That does not make the wiki draft itself the graph. A `WikiRevision` remains a governed markdown or wiki artifact with provenance, review state, and publishing metadata.

Future frontmatter may include optional graph lineage fields:

```yaml
atom_graph_revision_id: atom_graph_rev_20260616_001
atom_extraction_policy_id: atom_extraction_policy_v3
atom_granularity_policy_id: atom_granularity_policy_v2
user_graph_revision_id: user_graph_rev_person_yifan_20260616_001
graph_profile_id: graph_profile_person_yifan_research_detail
assembly_policy_id: assembly_policy_method_fine_intro_coarse
```

These fields are not required for the first version. The first version must preserve enough `source_refs`, `evidence_snapshot_ids`, and `citations` for later atom extraction and personal graph assembly.

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

User behavior may suggest that atoms should be split or merged, but it must not silently rewrite canonical atoms for everyone. User-specific behavior should first affect a personal assembly policy or create a reviewable canonical graph change proposal.

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
