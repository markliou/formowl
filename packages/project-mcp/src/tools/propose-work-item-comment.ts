// Future agents: implement the propose_work_item_comment tool in this file.
// Do not create another work item comment proposal file unless SPEC.md is
// updated first.

import type { McpResultEnvelope } from "@formowl/contract";
import type { ProjectWriteProposalData } from "../types";
import type { ProposeWorkItemCommentInput } from "./project-tools";

export type ProposeWorkItemCommentTool = (
  input: ProposeWorkItemCommentInput,
) => Promise<McpResultEnvelope<ProjectWriteProposalData>>;

export abstract class ProposeWorkItemCommentHandler {
  abstract propose_work_item_comment(
    input: ProposeWorkItemCommentInput,
  ): Promise<McpResultEnvelope<ProjectWriteProposalData>>;
}
