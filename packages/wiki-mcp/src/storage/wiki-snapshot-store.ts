// Future agents: implement wiki snapshot persistence through this file. Do not
// create another Wiki MCP wiki snapshot store file unless SPEC.md is updated first.

import type { JsonValue } from "@formowl/contract";
import type { WikiSnapshot } from "../types";

export interface WikiSnapshotWrite {
  readonly snapshot: WikiSnapshot;
  readonly raw_page?: JsonValue;
  readonly normalized_markdown?: string;
  readonly metadata?: JsonValue;
}

export interface WikiSnapshotStore {
  save_snapshot(write: WikiSnapshotWrite): Promise<WikiSnapshot>;
  get_snapshot(wiki_snapshot_id: string): Promise<WikiSnapshot | undefined>;
}
