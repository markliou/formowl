// Future agents: keep shared Wiki MCP logger contracts in this file. Runtime
// logger construction should continue from observability/logger.ts.

import type { McpToolCallLogEvent } from "@formowl/contract";

export interface ToolCallLogger {
  log_tool_call(event: McpToolCallLogEvent): Promise<void>;
}
