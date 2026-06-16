// Future agents: continue building Wiki MCP domain types in this file. Do not
// create parallel domain type files unless SPEC.md is updated first.

import type {
  Citation,
  JsonValue,
  PermissionScope,
  SourceRef,
  WikiChangeKind,
  WikiPageRef,
  WikiRevisionBackendRef,
} from "@formowl/contract";

export type {
  WikiChangeKind,
  WikiRevision,
  WikiRevisionBackendRef,
} from "@formowl/contract";

export type WikiPageType =
  | "adr"
  | "project-hub"
  | "meeting-notes"
  | "decision-log"
  | "risk-register"
  | (string & {});

export type WikiDraftStatus = "draft" | "reviewed" | "published" | "archived";

export interface MarkdownFrontmatter {
  readonly title: string;
  readonly type: WikiPageType;
  readonly status: WikiDraftStatus;
  readonly revision_id?: string;
  readonly parent_revision_id?: string;
  readonly change_kind?: WikiChangeKind;
  readonly project?: string;
  readonly owner?: string | null;
  readonly generated: boolean;
  readonly generated_by?: string;
  readonly review_status?: string;
  readonly created_at: string;
  readonly last_reviewed?: string | null;
  readonly source_refs: readonly SourceRef[];
  readonly evidence_snapshot_ids: readonly string[];
  readonly related_work_items?: readonly SourceRef[];
  readonly citations: readonly Citation[];
  readonly permission_scope?: PermissionScope;
  readonly revision_backend?: WikiRevisionBackendRef;
}

export interface WikiDraft {
  readonly draft_id: string;
  readonly page_type: WikiPageType;
  readonly title: string;
  readonly markdown: string;
  readonly frontmatter: MarkdownFrontmatter;
  readonly status: WikiDraftStatus;
  readonly source_refs: readonly SourceRef[];
  readonly evidence_snapshot_ids: readonly string[];
  readonly citations: readonly Citation[];
  readonly created_at?: string;
  readonly updated_at?: string;
}

export interface WikiDraftPatch {
  readonly status?: WikiDraftStatus;
  readonly title?: string;
  readonly content?: string;
  readonly frontmatter?: Partial<MarkdownFrontmatter>;
}

export interface WikiPage {
  readonly page_ref: WikiPageRef;
  readonly title: string;
  readonly markdown?: string;
  readonly frontmatter?: MarkdownFrontmatter;
  readonly source_url?: string;
  readonly updated_at?: string;
  readonly permission_scope?: PermissionScope;
  readonly raw?: JsonValue;
}

export interface WikiPageSearchResult {
  readonly page: WikiPage;
  readonly score?: number;
  readonly matched_fields?: readonly string[];
}

export interface WikiPublishTarget {
  readonly target_system: string;
  readonly project_id?: string;
  readonly page_slug: string;
  readonly source_instance?: string;
}

export interface WikiPublishProposalData {
  readonly proposal_id: string;
  readonly target: WikiPublishTarget;
  readonly diff_markdown: string;
  readonly draft_id: string;
  readonly revision_id?: string;
}

export interface WikiSnapshot {
  readonly wiki_snapshot_id: string;
  readonly page_ref: WikiPageRef;
  readonly captured_at: string;
  readonly source_refs: readonly SourceRef[];
  readonly storage_uri?: string;
  readonly raw?: JsonValue;
}
