#!/usr/bin/env python3
"""Policy review of semantic-annotation candidates -> paged UAT review receipts.

Applies a pinned, versioned acceptance policy to candidate atoms written by
``read_and_store_source_unit`` and, only with ``--approve``, writes sealed review
receipts (at most 128 entries each) plus the ``formowl_uat_reviewed_annotation_config_v1``
consumed by ``bind_issue56_reviewed_annotations``. Without ``--approve`` it only prints
counts. Approval happens here, offline, by the operator running this tool; never at
query time and never by an answer model. A receipt is not canonical publication.

Policy ``contract_validated_target_v1``: approve a candidate atom when its ledger is
``annotated`` under one of ``--run-id``, the ledger's candidate hash matches the stored
atom, the atom is still ``pending_review``/``approved``, it names a non-empty target, and
its confidence is at least ``--min-confidence``. All of the atom's identity bindings
(each already exact-span validated against source evidence) are approved with it.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT / "python"), str(_ROOT)]

CONFIG_ARTIFACT_ID = "formowl_uat_reviewed_annotation_config_v1"
RECEIPT_ARTIFACT_ID = "formowl_uat_annotation_review_receipt_v1"
DECISION = "approve_for_uat_source_selection"
POLICIES = ("contract_validated_target_v1",)
PAGE_SIZE = 128
BINDING_KEYS = ("source_revision_sha256", "source_authority_fingerprint", "source_session_binding_fingerprint")


def select_entries(store_root: Path, run_ids: set[str], min_confidence: float) -> tuple[list[dict], dict]:
    """Pure policy application over the candidate stores; returns sorted entries and counts."""
    from formowl_contract import sha256_json
    from formowl_graph.storage import CandidateAtomStore, SemanticMetadataStore

    atoms, ledgers = CandidateAtomStore(store_root), SemanticMetadataStore(store_root)
    counts: collections.Counter = collections.Counter()
    entries = {}
    for ledger in ledgers.list():
        value = ledger.value
        if ledger.metadata_type != "source_unit_semantic_read" or ledger.extractor_run_id not in run_ids:
            continue
        if value.get("annotation_status") != "annotated":
            counts["ledger_not_annotated"] += 1
            continue
        counts["ledger_annotated"] += 1
        for candidate_id, candidate_hash in sorted(value.get("candidate_hashes", {}).items()):
            atom = atoms.get(candidate_id)
            if atom is None:
                counts["relation_or_missing"] += 1
                continue
            target = atom.properties.get("assertion", {}).get("target")
            if sha256_json(atom.to_dict()) != candidate_hash or atom.source_semantic_metadata_ids != [
                    ledger.semantic_metadata_id] or atom.status not in {"pending_review", "approved"}:
                counts["rejected_changed_or_reviewed"] += 1
            elif not isinstance(target, str) or not target.strip():
                counts["skipped_no_target"] += 1
            elif atom.confidence < min_confidence:
                counts["skipped_low_confidence"] += 1
            elif candidate_id in entries:
                counts["skipped_duplicate"] += 1
            else:
                entries[candidate_id] = {
                    "candidate_atom_id": candidate_id, "candidate_sha256": candidate_hash,
                    "semantic_metadata_id": ledger.semantic_metadata_id,
                    "semantic_metadata_sha256": sha256_json(ledger.to_dict()),
                    "target_identity_verified": True,
                    "approved_identity_binding_fingerprints": sorted(
                        sha256_json(binding) for binding in atom.properties.get("identity_bindings", ()))[:16],
                }
                counts["approved"] += 1
    return [entries[key] for key in sorted(entries)], dict(counts)


def _write_private(path: Path, value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    return "sha256:" + hashlib.sha256(data).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--store-root", type=Path, required=True, help="annotation output (contains graph/)")
    parser.add_argument("--run-id", action="append", required=True)
    parser.add_argument("--policy", choices=POLICIES, required=True)
    parser.add_argument("--min-confidence", type=float, default=0.0)
    parser.add_argument("--activation-pins", type=Path, required=True,
                        help="the serving revision's activation-pins.safe.json (source binding fingerprints)")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--served-output-dir", help="output dir path as mounted in the UAT server")
    parser.add_argument("--served-store-root", help="store root path as mounted in the UAT server")
    parser.add_argument("--approve", action="store_true", help="write the sealed receipts and configuration")
    args = parser.parse_args(argv)
    from formowl_contract import sha256_json
    from formowl_mail.issue56_sealed_source import APPROVER_ACTOR

    pins = json.loads(args.activation_pins.read_bytes())
    if any(not isinstance(pins.get(key), str) for key in BINDING_KEYS):
        parser.error("activation pins lack the source binding fingerprints")
    entries, counts = select_entries(args.store_root, set(args.run_id), args.min_confidence)
    summary = {"policy_version": args.policy, "min_confidence": args.min_confidence,
               "approval_count": len(entries), "page_count": -(-len(entries) // PAGE_SIZE), "counts": counts}
    if not args.approve:
        print(json.dumps({**summary, "written": False}, ensure_ascii=False), flush=True)
        return 0
    if not entries:
        parser.error("no approvals to write")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(args.output_dir, 0o700)
    served = Path(args.served_output_dir) if args.served_output_dir else args.output_dir
    reviewed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    pages = []
    for number, start in enumerate(range(0, len(entries), PAGE_SIZE), 1):
        page = entries[start:start + PAGE_SIZE]
        receipt = {"artifact_id": RECEIPT_ARTIFACT_ID, "reviewer_user_id": APPROVER_ACTOR, "decision": DECISION,
                   "policy_version": args.policy, "min_confidence": args.min_confidence,
                   "run_ids": sorted(args.run_id), "page": number, "reviewed_at": reviewed_at,
                   **{key: pins[key] for key in BINDING_KEYS}, "entries": page}
        name = f"review-receipt-{number:05d}.json"
        pages.append({"review_receipt_path": str(served / name),
                      "review_receipt_sha256": _write_private(args.output_dir / name, receipt)})
    config = {"artifact_id": CONFIG_ARTIFACT_ID, "store_root": args.served_store_root or str(args.store_root),
              **{key: pins[key] for key in BINDING_KEYS}, "review_receipt_pages": pages,
              "policy_version": args.policy, "entries_sha256": sha256_json(entries)}
    config_sha256 = _write_private(args.output_dir / "reviewed-annotations.json", config)
    print(json.dumps({**summary, "written": True, "reviewed_annotations_sha256": config_sha256},
                     ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
