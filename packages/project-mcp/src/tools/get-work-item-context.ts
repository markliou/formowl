// Future agents: implement the get_work_item_context tool in this file. Do not
// create another work item context tool file unless SPEC.md is updated first.

import type {
  GetWorkItemContextEnvelope,
  GetWorkItemContextInput,
} from "./project-tools";

export type GetWorkItemContextTool = (
  input: GetWorkItemContextInput,
) => Promise<GetWorkItemContextEnvelope>;

export abstract class GetWorkItemContextHandler {
  abstract get_work_item_context(
    input: GetWorkItemContextInput,
  ): Promise<GetWorkItemContextEnvelope>;
}
