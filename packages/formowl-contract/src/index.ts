// Future agents: continue building the shared contract in this file. Do not create
// parallel contract entrypoints unless SPEC.md is updated first.

export type JsonPrimitive = string | number | boolean | null;

export type JsonValue =
  | JsonPrimitive
  | { readonly [key: string]: JsonValue }
  | readonly JsonValue[];

export type ExtensibleString<T extends string> = T | (string & {});

export type SourceSystem = ExtensibleString<
  "openproject" | "jira" | "github_issues" | "linear" | "youtrack" | "markdown-store" | "openproject_wiki" | "chatgpt"
>;

export type SourceType = ExtensibleString<
  "project" | "work_package" | "issue" | "wiki_page" | "markdown_page" | "chatgpt_session" | "chatgpt_message"
>;

export interface SourceRef {
  readonly source_system: SourceSystem;
  readonly source_type: SourceType;
  readonly source_id: string;
  readonly source_instance?: string;
  readonly source_key?: string;
  readonly source_url?: string;
}

export type ProjectRef = SourceRef & {
  readonly source_type: "project";
};

export type WorkItemRef = SourceRef & {
  readonly source_type: ExtensibleString<"work_package" | "issue">;
};

export type WikiPageRef = SourceRef & {
  readonly source_type: ExtensibleString<"wiki_page" | "markdown_page">;
};

export type PermissionScopeType = ExtensibleString<
  "private_user" | "project" | "team" | "workspace" | "public" | "restricted" | "unknown"
>;

export type PermissionVisibility = ExtensibleString<"private" | "restricted" | "public" | "unknown">;

export interface PermissionScope {
  readonly scope_type: PermissionScopeType;
  readonly scope_id?: string;
  readonly visibility: PermissionVisibility;
  readonly inherited_from?: string;
}

export interface EvidenceSnapshot {
  readonly evidence_snapshot_id: string;
  readonly mcp_server: string;
  readonly tool_name: string;
  readonly requested_by?: string;
  readonly source_account_id?: string;
  readonly captured_at: string;
  readonly permission_scope: PermissionScope;
  readonly source_refs: readonly SourceRef[];
  readonly request_hash?: string;
  readonly response_hash?: string;
  readonly storage_uri?: string;
}

export interface EvidenceSnapshotRef {
  readonly evidence_snapshot_id: string;
  readonly storage_uri?: string;
}

export interface CitationLocator {
  readonly type: string;
  readonly id?: string;
  readonly path?: string;
  readonly line_start?: number;
  readonly line_end?: number;
}

export interface Citation {
  readonly citation_id: string;
  readonly source_ref: SourceRef;
  readonly evidence_snapshot_id?: string;
  readonly locator?: CitationLocator;
  readonly summary?: string;
}

export interface ContextPackage {
  readonly context_package_id: string;
  readonly context_type: string;
  readonly context_markdown: string;
  readonly source_refs: readonly SourceRef[];
  readonly evidence_snapshot_ids: readonly string[];
  readonly citations: readonly Citation[];
  readonly permission_scope?: PermissionScope;
}

export type McpResultStatus =
  | "ok"
  | "partial"
  | "not_found"
  | "permission_denied"
  | "pending_review"
  | "error";

export interface McpResultEnvelope<TData = unknown> {
  readonly result_type: string;
  readonly status: McpResultStatus;
  readonly data: TData;
  readonly context_package?: ContextPackage;
  readonly source_refs?: readonly SourceRef[];
  readonly evidence_snapshot_ids?: readonly string[];
  readonly citations?: readonly Citation[];
  readonly permission_scope?: PermissionScope;
  readonly warnings?: readonly string[];
}

export interface McpToolDescriptor<TInput = unknown> {
  readonly name: string;
  readonly description: string;
  readonly input_schema?: TInput;
}

export interface McpToolCallLogEvent {
  readonly event_type: "mcp_tool_call";
  readonly server_name: string;
  readonly tool_name: string;
  readonly request_id: string;
  readonly conversation_id?: string;
  readonly user_id?: string;
  readonly source_account_id?: string;
  readonly called_at: string;
  readonly arguments_hash?: string;
  readonly response_hash?: string;
  readonly status: McpResultStatus;
  readonly latency_ms?: number;
  readonly evidence_snapshot_id?: string;
  readonly wiki_draft_id?: string;
}

export interface ReviewProposal<TTarget = unknown> {
  readonly proposal_id: string;
  readonly target: TTarget;
  readonly diff_markdown: string;
  readonly reason?: string;
  readonly source_refs?: readonly SourceRef[];
  readonly evidence_snapshot_ids?: readonly string[];
}
