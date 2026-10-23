#!/usr/bin/env python3
"""Phase 3 of SPEC §7.5 reviewed header validation: policy review + receipt.

Applies a pinned, versioned acceptance policy to reviewed-header proposals and,
only with ``--approve``, writes a sealed review receipt plus the reviewed-header
configuration consumed by ``bind_issue56_reviewed_headers``. Without
``--approve`` it only prints counts. Approval happens here, offline, by the
operator running this tool; never at query time and never by an answer model.

Policies:
- ``structural_accept_v1``: approve structural ``header_confirmed`` proposals
  whose label-level column is an indexed ``candidate_only`` exact column.
- ``structural_llm_accept_v1``: additionally approve structural ``ambiguous``
  proposals whose reasons are all LLM-resolvable (``LLM_ELIGIBLE_REASONS``) and
  for which an LLM proposal confirms the header. An LLM never overrides
  ``not_header`` or any other ambiguity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Any, Iterable

CONFIG_ARTIFACT_ID = "formowl_reviewed_header_validation_v1"
RECEIPT_ARTIFACT_ID = "formowl_reviewed_header_review_receipt_v1"
DECISION = "approve_reviewed_header"
POLICIES = ("structural_accept_v1", "structural_llm_accept_v1")
LLM_ELIGIBLE_REASONS = frozenset({"multi_level_header_path", "label_too_short"})
STRUCTURAL_PROPOSER = "structural_v1"
LLM_PROPOSER = "llm_v1"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def select_approvals(policy: str, structural: Iterable[dict[str, Any]], llm: Iterable[dict[str, Any]],
                     candidate_columns: set[tuple[str, bool]]) -> tuple[list[dict[str, str]], dict[str, int]]:
    """Pure policy application. Returns sorted approvals and decision counts."""
    if policy not in POLICIES:
        raise ValueError("unknown reviewed header policy")
    llm_confirmed = {item["binding"] for item in llm
                     if item.get("proposer_version") == LLM_PROPOSER and item.get("decision") == "header_confirmed"}
    approvals: dict[str, str] = {}
    counts = {"approved_structural": 0, "approved_llm": 0, "rejected_not_header": 0,
              "left_ambiguous": 0, "skipped_unindexed_or_conflict": 0}
    structural = list(structural)
    occurrences: dict[str, int] = {}
    for item in structural:
        if item.get("proposer_version") != STRUCTURAL_PROPOSER:
            raise ValueError("unexpected structural proposer version")
        occurrences[item["binding"]] = occurrences.get(item["binding"], 0) + 1
    for item in structural:
        binding, column = item["binding"], (item.get("column_hash"), item.get("inline_table"))
        if occurrences[binding] > 1 or column not in candidate_columns:
            counts["skipped_unindexed_or_conflict"] += 1
            continue
        if item["decision"] == "header_confirmed":
            approvals[binding] = item["column_hash"]
            counts["approved_structural"] += 1
        elif item["decision"] == "not_header":
            counts["rejected_not_header"] += 1
        elif (policy == "structural_llm_accept_v1" and item["reasons"]
              and set(item["reasons"]) <= LLM_ELIGIBLE_REASONS and binding in llm_confirmed):
            approvals[binding] = item["column_hash"]
            counts["approved_llm"] += 1
        else:
            counts["left_ambiguous"] += 1
    return [{"binding": key, "column_hash": approvals[key]} for key in sorted(approvals)], counts


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


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
    parser.add_argument("--structural-proposals", type=Path, required=True)
    parser.add_argument("--llm-proposals", type=Path)
    parser.add_argument("--exact-manifest", type=Path, required=True)
    parser.add_argument("--policy", choices=POLICIES, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--approve", action="store_true", help="write the sealed receipt and configuration")
    args = parser.parse_args(argv)
    if args.policy == "structural_llm_accept_v1" and args.llm_proposals is None:
        parser.error("structural_llm_accept_v1 requires --llm-proposals")
    from formowl_contract import sha256_json
    from formowl_mail.issue56_sealed_source import APPROVER_ACTOR

    manifest = json.loads(args.exact_manifest.read_bytes())
    candidate_columns = {(item["column_hash"], item["inline_table"])
                         for item in manifest["columns"] if item["structure_status"] == "candidate_only"}
    llm = _read_jsonl(args.llm_proposals) if args.llm_proposals else []
    approvals, counts = select_approvals(args.policy, _read_jsonl(args.structural_proposals), llm,
                                         candidate_columns)
    summary = {"policy_version": args.policy, "approval_count": len(approvals), "counts": counts}
    if not args.approve:
        print(json.dumps({**summary, "written": False}), flush=True)
        return 0
    if not approvals:
        parser.error("no approvals to write")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(args.output_dir, 0o700)
    receipt = {
        "artifact_id": RECEIPT_ARTIFACT_ID, "approver_user_id": APPROVER_ACTOR, "decision": DECISION,
        "policy_version": args.policy, "source_authority_fingerprint": manifest["source_authority_fingerprint"],
        "approvals_sha256": sha256_json(approvals), "approval_count": len(approvals), "counts": counts,
        "structural_proposals_sha256": _sha256_file(args.structural_proposals),
        "llm_proposals_sha256": _sha256_file(args.llm_proposals) if args.llm_proposals else None,
        "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    receipt_sha256 = _write_private(args.output_dir / "review-receipt.json", receipt)
    config = {
        "artifact_id": CONFIG_ARTIFACT_ID, "schema_version": 1,
        "source_authority_fingerprint": manifest["source_authority_fingerprint"],
        "policy_version": args.policy, "approver_user_id": APPROVER_ACTOR, "decision": DECISION,
        "approvals": approvals, "review_receipt_path": "review-receipt.json",
        "review_receipt_sha256": receipt_sha256,
    }
    config_sha256 = _write_private(args.output_dir / "reviewed-headers.json", config)
    print(json.dumps({**summary, "written": True, "reviewed_headers_sha256": config_sha256,
                      "review_receipt_sha256": receipt_sha256}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
