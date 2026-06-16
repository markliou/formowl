// Future agents: implement the get_work_item tool in this file. Do not create
// another get work item tool file unless SPEC.md is updated first.

import type { McpResultEnvelope } from "@formowl/contract";
import type { GetWorkItemData, GetWorkItemInput } from "./project-tools";

export type GetWorkItemTool = (
  input: GetWorkItemInput,
) => Promise<McpResultEnvelope<GetWorkItemData>>;

export abstract class GetWorkItemHandler {
  abstract get_work_item(
    input: GetWorkItemInput,
  ): Promise<McpResultEnvelope<GetWorkItemData>>;
}
