// Future agents: keep the complete Wiki MCP tool surface in this file. Add
// implementation details to the per-tool files, not new parallel tool files.

import type {
  ContextPackage,
  McpResultEnvelope,
  WikiPageRef
} from "@formoowl/contract";
import type {
  WikiDraft,
  WikiDraftPatch,
  WikiPage,
  WikiPageSearchResult,
  WikiPageType,
  WikiPublishProposalData,
  WikiPublishTarget,
  WikiSnapshot
} from "../types";

export interface SearchWikiPagesInput {
  readonly query: string;
  readonly project?: string;
  readonly limit?: number;
}

export interface SearchWikiPagesData {
  readonly pages: readonly WikiPageSearchResult[];
}

export interface GetWikiPageInput {
  readonly page_ref: WikiPageRef;
}

export interface GetWikiPageData {
  readonly page: WikiPage;
}

export interface GenerateWikiDraftInput {
  readonly page_type: WikiPageType;
  readonly title: string;
  readonly context_package: ContextPackage;
}

export interface GenerateWikiDraftData {
  readonly draft_id: string;
  readonly markdown: string;
  readonly frontmatter: WikiDraft["frontmatter"];
}

export interface UpdateWikiDraftInput {
  readonly draft_id: string;
  readonly patch: WikiDraftPatch;
}

export interface UpdateWikiDraftData {
  readonly draft: WikiDraft;
}

export interface PublishWikiPageInput {
  readonly draft_id: string;
  readonly target: WikiPublishTarget;
  readonly require_review?: boolean;
}

export interface CaptureWikiSnapshotInput {
  readonly page_ref: WikiPageRef;
}

export interface CaptureWikiSnapshotData {
  readonly snapshot: WikiSnapshot;
}

export interface WikiMcpTools {
  search_wiki_pages(input: SearchWikiPagesInput): Promise<McpResultEnvelope<SearchWikiPagesData>>;
  get_wiki_page(input: GetWikiPageInput): Promise<McpResultEnvelope<GetWikiPageData>>;
  generate_wiki_draft(input: GenerateWikiDraftInput): Promise<McpResultEnvelope<GenerateWikiDraftData>>;
  update_wiki_draft(input: UpdateWikiDraftInput): Promise<McpResultEnvelope<UpdateWikiDraftData>>;
  publish_wiki_page(input: PublishWikiPageInput): Promise<McpResultEnvelope<WikiPublishProposalData>>;
  capture_wiki_snapshot(input: CaptureWikiSnapshotInput): Promise<McpResultEnvelope<CaptureWikiSnapshotData>>;
}
