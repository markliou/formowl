// Future agents: implement the get_wiki_page tool in this file. Do not create
// another wiki page retrieval tool file unless SPEC.md is updated first.

import type { McpResultEnvelope } from "@formowl/contract";
import type { GetWikiPageData, GetWikiPageInput } from "./wiki-tools";

export type GetWikiPageTool = (input: GetWikiPageInput) => Promise<McpResultEnvelope<GetWikiPageData>>;

export abstract class GetWikiPageHandler {
  abstract get_wiki_page(input: GetWikiPageInput): Promise<McpResultEnvelope<GetWikiPageData>>;
}
