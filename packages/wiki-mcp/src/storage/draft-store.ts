// Future agents: implement draft persistence through this file. Do not create
// another Wiki MCP draft store file unless SPEC.md is updated first.

import type { WikiDraft } from "../types";

export interface DraftStore {
  save_draft(draft: WikiDraft): Promise<WikiDraft>;
  get_draft(draft_id: string): Promise<WikiDraft | undefined>;
  list_drafts(project?: string): Promise<readonly WikiDraft[]>;
}
