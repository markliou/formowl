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
