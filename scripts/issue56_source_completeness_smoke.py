#!/usr/bin/env python3
"""Bounded real-PST source inventory -> persisted parity diagnostic."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_contract import (  # noqa: E402
    assert_no_public_raw_references,
    sha256_json,
    stable_resource_contract_id,
)
from formowl_ingestion.extractors.mail.pst import (  # noqa: E402
    run_bounded_pst_source_completeness_poc,
)


DEFAULT_FIXTURE = ROOT / "tests" / "pst-exm" / "archive.pst"
DEFAULT_REPORT = Path(tempfile.gettempdir()) / "formowl-issue56-source-completeness.json"
DEFAULT_INVENTORY = Path(tempfile.gettempdir()) / "formowl-issue56-source-inventory.json"
CREATED_AT = "2026-08-18T12:00:00+08:00"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--inventory-output", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--max-exported-files", type=int, default=4)
    parser.add_argument("--max-exported-bytes", type=int, default=16 * 1024 * 1024)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args()

    source_asset_id = stable_resource_contract_id(
        "asset",
        "Issue56BoundedPstDiagnostic",
        {"fixture_identity_fingerprint": sha256_json("issue56-real-pst-fixture")},
    )
    try:
        result = run_bounded_pst_source_completeness_poc(
            args.fixture,
            inventory_path=args.inventory_output,
            source_asset_id=source_asset_id,
            permission_scope={
                "scope_type": "project",
                "scope_id": "project_issue56_diagnostic",
                "visibility": "restricted",
                "workspace_id": "workspace_formowl",
                "owner_user_id": "user_issue56_operator",
            },
            extractor_run_id=stable_resource_contract_id(
                "extractor",
                "Issue56BoundedPstDiagnosticRun",
                {"source_asset_id": source_asset_id},
            ),
            created_at=CREATED_AT,
            max_exported_files=args.max_exported_files,
            max_exported_bytes=args.max_exported_bytes,
            timeout_seconds=args.timeout_seconds,
        )
        report = result.report
    except (OSError, ValueError) as exc:
        report = {
            "artifact_id": "issue56_source_completeness_diagnostic_v1",
            "status": "diagnostic_blocked",
            "blocker_status_hash": sha256_json(type(exc).__name__ + ":" + str(exc)),
            "processing_state_counts": {
                "parsed": 0,
                "preserved_unparsed": 0,
                "unsupported": 0,
                "failed": 0,
                "intentionally_excluded": 0,
            },
            "raw_retention_state_counts": {
                "retained": 0,
                "deleted_by_policy": 0,
                "externally_managed": 0,
            },
            "inventory_item_count": 0,
            "unexplained_loss_count": 0,
            "claim_boundary": {
                "source_complete": False,
                "real_source_authority_gate_passed": False,
                "diagnostic_partial_only": True,
            },
        }
        report["report_fingerprint"] = sha256_json(report)

    assert_no_public_raw_references(report, "issue56_source_completeness_smoke")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "diagnostic_partial" else 2


if __name__ == "__main__":
    raise SystemExit(main())
