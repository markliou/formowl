// Future agents: implement frontmatter and markdown draft rendering from this
// file. Do not create another frontmatter file unless SPEC.md is updated first.

import type { ContextPackage } from "@formoowl/contract";
import type { MarkdownFrontmatter, WikiPageType } from "../types";

export interface FrontmatterBuildInput {
  readonly page_type: WikiPageType;
  readonly title: string;
  readonly context_package: ContextPackage;
  readonly project?: string;
  readonly owner?: string | null;
}

export interface MarkdownFrontmatterBuilder {
  build_frontmatter(input: FrontmatterBuildInput): Promise<MarkdownFrontmatter>;
  serialize_frontmatter(frontmatter: MarkdownFrontmatter): Promise<string>;
}

export interface MarkdownDraftRenderer {
  render_draft(input: FrontmatterBuildInput): Promise<string>;
}
