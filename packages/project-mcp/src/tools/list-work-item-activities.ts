// Future agents: implement the list_work_item_activities tool in this file.
// Do not create another activities tool file unless SPEC.md is updated first.

import type { McpResultEnvelope } from "@formowl/contract";
import type { ListWorkItemActivitiesData, ListWorkItemActivitiesInput } from "./project-tools";

export type ListWorkItemActivitiesTool = (
  input: ListWorkItemActivitiesInput
) => Promise<McpResultEnvelope<ListWorkItemActivitiesData>>;

export abstract class ListWorkItemActivitiesHandler {
  abstract list_work_item_activities(
    input: ListWorkItemActivitiesInput
  ): Promise<McpResultEnvelope<ListWorkItemActivitiesData>>;
}
