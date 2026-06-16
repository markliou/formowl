// Future agents: keep the complete Project MCP tool surface in this file. Add
// implementation details to the per-tool files, not new parallel tool files.

import type {
  ContextPackage,
  McpResultEnvelope,
  ProjectRef,
  SourceRef,
  WorkItemRef,
} from "@formowl/contract";
import type {
  ProjectStatusSummary,
  ProjectWorkItem,
  ProjectWriteProposalData,
  WorkItemActivity,
  WorkItemContextData,
  WorkItemRelation,
  WorkItemSearchResult,
} from "../types";

export interface SearchWorkItemsInput {
  readonly query: string;
  readonly project_ref?: ProjectRef;
  readonly limit?: number;
}

export interface SearchWorkItemsData {
  readonly items: readonly WorkItemSearchResult[];
}

export interface GetWorkItemInput {
  readonly source_ref: WorkItemRef;
}

export interface GetWorkItemData {
  readonly work_item: ProjectWorkItem;
}

export interface GetWorkItemContextInput {
  readonly source_ref: WorkItemRef;
  readonly include_comments?: boolean;
  readonly include_activities?: boolean;
  readonly include_relations?: boolean;
  readonly include_attachments?: boolean;
  readonly create_evidence_snapshot?: boolean;
}

export interface GetWorkItemContextEnvelope extends McpResultEnvelope<WorkItemContextData> {
  readonly context_package?: ContextPackage;
}

export interface ListWorkItemActivitiesInput {
  readonly source_ref: WorkItemRef;
  readonly limit?: number;
  readonly create_evidence_snapshot?: boolean;
}

export interface ListWorkItemActivitiesData {
  readonly activities: readonly WorkItemActivity[];
}

export interface ListWorkItemRelationsInput {
  readonly source_ref: WorkItemRef;
}

export interface ListWorkItemRelationsData {
  readonly relations: readonly WorkItemRelation[];
}

export interface GetProjectStatusInput {
  readonly project_ref: ProjectRef;
  readonly include_recent_updates?: boolean;
  readonly create_evidence_snapshot?: boolean;
}

export interface ProposeWorkItemCommentInput {
  readonly source_ref: WorkItemRef;
  readonly body: string;
  readonly reason?: string;
}

export interface ProjectMcpTools {
  search_work_items(
    input: SearchWorkItemsInput,
  ): Promise<McpResultEnvelope<SearchWorkItemsData>>;
  get_work_item(
    input: GetWorkItemInput,
  ): Promise<McpResultEnvelope<GetWorkItemData>>;
  get_work_item_context(
    input: GetWorkItemContextInput,
  ): Promise<GetWorkItemContextEnvelope>;
  list_work_item_activities(
    input: ListWorkItemActivitiesInput,
  ): Promise<McpResultEnvelope<ListWorkItemActivitiesData>>;
  list_work_item_relations(
    input: ListWorkItemRelationsInput,
  ): Promise<McpResultEnvelope<ListWorkItemRelationsData>>;
  get_project_status(
    input: GetProjectStatusInput,
  ): Promise<McpResultEnvelope<ProjectStatusSummary>>;
  propose_work_item_comment(
    input: ProposeWorkItemCommentInput,
  ): Promise<McpResultEnvelope<ProjectWriteProposalData>>;
}

export interface ProjectContextBuilder {
  build_context_markdown(data: WorkItemContextData): Promise<string>;
  build_context_package(
    data: WorkItemContextData,
    source_refs: readonly SourceRef[],
  ): Promise<ContextPackage>;
}
