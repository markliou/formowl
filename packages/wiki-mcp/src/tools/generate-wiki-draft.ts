// Future agents: implement the generate_wiki_draft tool in this file. Do not
// create another wiki draft generation tool file unless SPEC.md is updated first.

import type { McpResultEnvelope } from "@formoowl/contract";
import type { GenerateWikiDraftData, GenerateWikiDraftInput } from "./wiki-tools";

export type GenerateWikiDraftTool = (
  input: GenerateWikiDraftInput
) => Promise<McpResultEnvelope<GenerateWikiDraftData>>;

export abstract class GenerateWikiDraftHandler {
  abstract generate_wiki_draft(
    input: GenerateWikiDraftInput
  ): Promise<McpResultEnvelope<GenerateWikiDraftData>>;
}
