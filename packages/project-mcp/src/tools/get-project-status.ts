// Future agents: implement the get_project_status tool in this file. Do not
// create another project status tool file unless SPEC.md is updated first.

import type { McpResultEnvelope } from "@formoowl/contract";
import type { ProjectStatusSummary } from "../types";
import type { GetProjectStatusInput } from "./project-tools";

export type GetProjectStatusTool = (
  input: GetProjectStatusInput
) => Promise<McpResultEnvelope<ProjectStatusSummary>>;

export abstract class GetProjectStatusHandler {
  abstract get_project_status(input: GetProjectStatusInput): Promise<McpResultEnvelope<ProjectStatusSummary>>;
}
