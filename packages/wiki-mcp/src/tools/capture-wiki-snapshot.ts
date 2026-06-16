// Future agents: implement the capture_wiki_snapshot tool in this file. Do not
// create another wiki snapshot capture tool file unless SPEC.md is updated first.

import type { McpResultEnvelope } from "@formowl/contract";
import type { CaptureWikiSnapshotData, CaptureWikiSnapshotInput } from "./wiki-tools";

export type CaptureWikiSnapshotTool = (
  input: CaptureWikiSnapshotInput
) => Promise<McpResultEnvelope<CaptureWikiSnapshotData>>;

export abstract class CaptureWikiSnapshotHandler {
  abstract capture_wiki_snapshot(
    input: CaptureWikiSnapshotInput
  ): Promise<McpResultEnvelope<CaptureWikiSnapshotData>>;
}
