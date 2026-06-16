// Future agents: implement evidence snapshot persistence through this file. Do
// not create another Project MCP evidence snapshot store file unless SPEC.md is
// updated first.

import type { EvidenceSnapshot, EvidenceSnapshotRef, JsonValue } from "@formoowl/contract";

export interface EvidenceSnapshotWrite {
  readonly snapshot: EvidenceSnapshot;
  readonly request_payload?: JsonValue;
  readonly response_payload?: JsonValue;
  readonly normalized_markdown?: string;
  readonly metadata?: JsonValue;
}

export interface EvidenceSnapshotStore {
  save_snapshot(write: EvidenceSnapshotWrite): Promise<EvidenceSnapshotRef>;
  get_snapshot(evidence_snapshot_id: string): Promise<EvidenceSnapshot | undefined>;
  get_snapshot_payload(evidence_snapshot_id: string): Promise<JsonValue | undefined>;
}
