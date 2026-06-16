// Future agents: continue building the generic project-system adapter contract
// in this file. Do not create parallel adapter abstractions unless SPEC.md is
// updated first.

import type { ProjectRef, WorkItemRef } from "@formoowl/contract";
import type {
  GetProjectStatusInput,
  GetWorkItemContextInput,
  ListWorkItemActivitiesInput,
  ListWorkItemRelationsInput,
  SearchWorkItemsInput
} from "../tools/project-tools";
import type {
  ProjectStatusSummary,
  ProjectWorkItem,
  WorkItemActivity,
  WorkItemContextData,
  WorkItemRelation,
  WorkItemSearchResult
} from "../types";

export interface ProjectSystemAdapter {
  readonly source_system: string;
  readonly source_instance?: string;

  search_work_items(input: SearchWorkItemsInput): Promise<readonly WorkItemSearchResult[]>;
  get_work_item(source_ref: WorkItemRef): Promise<ProjectWorkItem | undefined>;
  get_work_item_context(input: GetWorkItemContextInput): Promise<WorkItemContextData | undefined>;
  list_work_item_activities(input: ListWorkItemActivitiesInput): Promise<readonly WorkItemActivity[]>;
  list_work_item_relations(input: ListWorkItemRelationsInput): Promise<readonly WorkItemRelation[]>;
  get_project_status(input: GetProjectStatusInput): Promise<ProjectStatusSummary | undefined>;
  resolve_project_ref(project_ref: ProjectRef): Promise<ProjectRef | undefined>;
}
