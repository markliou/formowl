// Future agents: implement the list_work_item_relations tool in this file.
// Do not create another relations tool file unless SPEC.md is updated first.

import type { McpResultEnvelope } from "@formowl/contract";
import type {
  ListWorkItemRelationsData,
  ListWorkItemRelationsInput,
} from "./project-tools";

export type ListWorkItemRelationsTool = (
  input: ListWorkItemRelationsInput,
) => Promise<McpResultEnvelope<ListWorkItemRelationsData>>;

export abstract class ListWorkItemRelationsHandler {
  abstract list_work_item_relations(
    input: ListWorkItemRelationsInput,
  ): Promise<McpResultEnvelope<ListWorkItemRelationsData>>;
}
