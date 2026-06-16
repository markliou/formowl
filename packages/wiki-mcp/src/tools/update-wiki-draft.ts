// Future agents: implement the update_wiki_draft tool in this file. Do not
// create another wiki draft update tool file unless SPEC.md is updated first.

import type { McpResultEnvelope } from "@formowl/contract";
import type { UpdateWikiDraftData, UpdateWikiDraftInput } from "./wiki-tools";

export type UpdateWikiDraftTool = (
  input: UpdateWikiDraftInput,
) => Promise<McpResultEnvelope<UpdateWikiDraftData>>;

export abstract class UpdateWikiDraftHandler {
  abstract update_wiki_draft(
    input: UpdateWikiDraftInput,
  ): Promise<McpResultEnvelope<UpdateWikiDraftData>>;
}
