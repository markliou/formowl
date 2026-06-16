// Future agents: implement Wiki MCP server wiring in this file. Do not create
// another Wiki MCP server entrypoint unless SPEC.md is updated first.

import type { McpToolDescriptor } from "@formowl/contract";
import type { MarkdownDraftRenderer, MarkdownFrontmatterBuilder } from "./markdown/frontmatter";
import type { ToolCallLogger } from "./observability/tool-call-logger";
import type { DraftStore } from "./storage/draft-store";
import type { WikiSnapshotStore } from "./storage/wiki-snapshot-store";
import type { WikiMcpTools } from "./tools/wiki-tools";

export abstract class WikiMcpServer {
  abstract readonly server_name: "wiki-mcp";
  abstract readonly tools: WikiMcpTools;
  abstract readonly draft_store: DraftStore;
  abstract readonly wiki_snapshot_store: WikiSnapshotStore;
  abstract readonly frontmatter_builder: MarkdownFrontmatterBuilder;
  abstract readonly draft_renderer: MarkdownDraftRenderer;
  abstract readonly logger: ToolCallLogger;

  abstract list_tools(): readonly McpToolDescriptor[];
}
