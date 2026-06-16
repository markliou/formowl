// Future agents: implement the publish_wiki_page proposal tool in this file.
// Do not create another wiki publishing tool file unless SPEC.md is updated first.

import type { McpResultEnvelope } from "@formowl/contract";
import type { WikiPublishProposalData } from "../types";
import type { PublishWikiPageInput } from "./wiki-tools";

export type PublishWikiPageTool = (
  input: PublishWikiPageInput,
) => Promise<McpResultEnvelope<WikiPublishProposalData>>;

export abstract class PublishWikiPageHandler {
  abstract publish_wiki_page(
    input: PublishWikiPageInput,
  ): Promise<McpResultEnvelope<WikiPublishProposalData>>;
}
