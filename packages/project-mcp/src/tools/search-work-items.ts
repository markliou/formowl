// Future agents: implement the search_work_items tool in this file. Do not
// create another search work items tool file unless SPEC.md is updated first.

import type { McpResultEnvelope } from "@formowl/contract";
import type {
  SearchWorkItemsData,
  SearchWorkItemsInput,
} from "./project-tools";

export type SearchWorkItemsTool = (
  input: SearchWorkItemsInput,
) => Promise<McpResultEnvelope<SearchWorkItemsData>>;

export abstract class SearchWorkItemsHandler {
  abstract search_work_items(
    input: SearchWorkItemsInput,
  ): Promise<McpResultEnvelope<SearchWorkItemsData>>;
}
