// Future agents: implement the search_wiki_pages tool in this file. Do not
// create another wiki page search tool file unless SPEC.md is updated first.

import type { McpResultEnvelope } from "@formoowl/contract";
import type { SearchWikiPagesData, SearchWikiPagesInput } from "./wiki-tools";

export type SearchWikiPagesTool = (
  input: SearchWikiPagesInput
) => Promise<McpResultEnvelope<SearchWikiPagesData>>;

export abstract class SearchWikiPagesHandler {
  abstract search_wiki_pages(input: SearchWikiPagesInput): Promise<McpResultEnvelope<SearchWikiPagesData>>;
}
