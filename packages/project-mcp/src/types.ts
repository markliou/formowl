// Future agents: continue building Project MCP domain types in this file. Do
// not create parallel domain type files unless SPEC.md is updated first.

import type {
  JsonValue,
  PermissionScope,
  ProjectRef,
  SourceRef,
  WorkItemRef
} from "@formowl/contract";

export interface ProjectWorkItem {
  readonly title: string;
  readonly description?: string;
  readonly status?: string;
  readonly type?: string;
  readonly priority?: string;
  readonly assignee?: string;
  readonly responsible?: string;
  readonly start_date?: string;
  readonly due_date?: string;
  readonly updated_at?: string;
  readonly source_url?: string;
  readonly source_ref: WorkItemRef;
  readonly permission_scope?: PermissionScope;
  readonly raw?: JsonValue;
}

export interface WorkItemActivity {
  readonly activity_id: string;
  readonly type: string;
  readonly actor?: string;
  readonly body?: string;
  readonly created_at?: string;
  readonly source_ref?: SourceRef;
  readonly raw?: JsonValue;
}

export interface WorkItemComment {
  readonly comment_id: string;
  readonly body: string;
  readonly author?: string;
  readonly created_at?: string;
  readonly updated_at?: string;
  readonly source_ref?: SourceRef;
  readonly raw?: JsonValue;
}

export interface WorkItemRelation {
  readonly relation_id: string;
  readonly relation_type: string;
  readonly source_ref: WorkItemRef;
  readonly target_ref: WorkItemRef;
  readonly description?: string;
  readonly raw?: JsonValue;
}

export interface WorkItemAttachment {
  readonly attachment_id: string;
  readonly file_name: string;
  readonly content_type?: string;
  readonly size_bytes?: number;
  readonly source_url?: string;
  readonly source_ref?: SourceRef;
  readonly raw?: JsonValue;
}

export interface WorkItemSearchResult {
  readonly item: ProjectWorkItem;
  readonly score?: number;
  readonly matched_fields?: readonly string[];
}

export interface ProjectStatusSummary {
  readonly project_ref: ProjectRef;
  readonly summary_markdown?: string;
  readonly status_counts?: Readonly<Record<string, number>>;
  readonly recent_updates?: readonly WorkItemActivity[];
  readonly source_refs: readonly SourceRef[];
  readonly raw?: JsonValue;
}

export interface WorkItemContextData {
  readonly work_item: ProjectWorkItem;
  readonly comments: readonly WorkItemComment[];
  readonly activities: readonly WorkItemActivity[];
  readonly relations: readonly WorkItemRelation[];
  readonly attachments: readonly WorkItemAttachment[];
}

export interface ProjectWriteProposalData {
  readonly proposal_id: string;
  readonly target_source_ref: WorkItemRef;
  readonly diff_markdown: string;
  readonly reason?: string;
}
