// Future agents: implement Project MCP server wiring in this file. Do not
// create another Project MCP server entrypoint unless SPEC.md is updated first.

import type { McpToolDescriptor } from "@formoowl/contract";
import type { ProjectSystemAdapter } from "./adapters/project-system-adapter";
import type { ToolCallLogger } from "./observability/tool-call-logger";
import type { EvidenceSnapshotStore } from "./storage/evidence-snapshot-store";
import type { ProjectMcpTools } from "./tools/project-tools";

export abstract class ProjectMcpServer {
  abstract readonly server_name: "project-mcp";
  abstract readonly tools: ProjectMcpTools;
  abstract readonly adapter: ProjectSystemAdapter;
  abstract readonly evidence_snapshot_store: EvidenceSnapshotStore;
  abstract readonly logger: ToolCallLogger;

  abstract list_tools(): readonly McpToolDescriptor[];
}
