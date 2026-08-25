from __future__ import annotations

import json
from pathlib import Path
import stat
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from formowl_contract import (
    SourceInventory,
    assert_no_public_raw_references,
)
from formowl_ingestion.extractors.mail import pst as pst_module
from formowl_ingestion.extractors.mail.pst import (
    reconcile_pst_source_inventory,
    run_bounded_pst_source_completeness_poc,
)


NOW = "2026-08-18T12:00:00+08:00"


class Issue56SourceCompletenessE2ETests(unittest.TestCase):
    def test_source_inventory_is_persisted_before_observation_parity(self) -> None:
        root = _paths.fresh_test_dir("issue56-source-completeness-e2e")
        source = root / "source.pst"
        source.write_bytes(b"!BDN bounded real-source fixture")
        inventory_path = root / "private" / "source-inventory.json"
        parser = _fake_readpst(root)
        real_materializer = pst_module._mail_observations_from_messages
        materialization_checks: list[bool] = []

        def checked_materializer(messages, *, extraction_input, source_inventory):
            persisted = SourceInventory.from_dict(
                json.loads(inventory_path.read_text(encoding="utf-8"))
            )
            materialization_checks.append(persisted.to_dict() == source_inventory.to_dict())
            return real_materializer(
                messages,
                extraction_input=extraction_input,
                source_inventory=source_inventory,
            )

        with patch.object(
            pst_module,
            "_mail_observations_from_messages",
            side_effect=checked_materializer,
        ):
            result = run_bounded_pst_source_completeness_poc(
                source,
                inventory_path=inventory_path,
                source_asset_id="asset_issue56_source_completeness",
                permission_scope={
                    "scope_type": "project",
                    "scope_id": "project_issue56",
                    "visibility": "restricted",
                    "workspace_id": "workspace_formowl",
                    "owner_user_id": "user_owner",
                },
                extractor_run_id="extractor_run_issue56_source_completeness",
                created_at=NOW,
                parser_command=str(parser),
                scratch_parent=root / "scratch",
                max_exported_files=2,
                max_exported_bytes=1024 * 1024,
                timeout_seconds=5,
            )

        self.assertEqual(materialization_checks, [True])
        self.assertTrue(inventory_path.is_file())
        self.assertEqual(result.report["status"], "diagnostic_partial")
        self.assertEqual(
            result.report["processing_state_counts"],
            {
                "parsed": 2,
                "preserved_unparsed": 0,
                "unsupported": 1,
                "failed": 0,
                "intentionally_excluded": 0,
            },
        )
        self.assertEqual(result.report["unexplained_loss_count"], 0)
        self.assertEqual(
            result.report["expected_observation_binding_count"],
            result.report["matched_observation_binding_count"],
        )
        self.assertFalse(result.report["claim_boundary"]["source_complete"])
        self.assertFalse(result.report["claim_boundary"]["real_source_authority_gate_passed"])
        rendered = json.dumps(result.report, sort_keys=True)
        assert_no_public_raw_references(result.report, "issue56_report")
        for forbidden in (
            str(root),
            "source.pst",
            "message.eml",
            "unsupported.bin",
            "readpst",
            "private",
        ):
            self.assertNotIn(forbidden, rendered)

        missing_one = tuple(
            observation
            for observation in result.observations
            if observation.observation_type != "email_attachment_occurrence"
        )
        loss_report = reconcile_pst_source_inventory(
            result.source_inventory,
            missing_one,
            bounded_source_unit_count=2,
            bounded_overflow_count=0,
            parser_stop_reason="file_cap",
            parser_completed=False,
            persisted_round_trip_verified=True,
        )
        self.assertEqual(loss_report["unexplained_loss_count"], 1)
        self.assertFalse(loss_report["claim_boundary"]["source_complete"])


def _fake_readpst(root: Path) -> Path:
    executable = root / "bounded-parser"
    executable.write_text(
        """#!/usr/bin/env python3
from pathlib import Path
import sys
import time

args = sys.argv[1:]
output = Path(args[args.index("-o") + 1])
output.mkdir(parents=True, exist_ok=True)
(output / "message.eml").write_bytes(
    b"Message-ID: <issue56@example.test>\\n"
    b"Subject: bounded source\\n"
    b"From: source@example.test\\n"
    b"To: archive@example.test\\n"
    b"Date: Tue, 18 Aug 2026 12:00:00 +0800\\n"
    b"MIME-Version: 1.0\\n"
    b"Content-Type: multipart/mixed; boundary=x\\n\\n"
    b"--x\\nContent-Type: text/plain\\n\\nbody\\n"
    b"--x\\nContent-Type: text/plain\\n"
    b"Content-Disposition: attachment; filename=proof.txt\\n\\nproof\\n"
    b"--x--\\n"
)
(output / "unsupported.bin").write_bytes(b"not an RFC822 message")
time.sleep(30)
""",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable


if __name__ == "__main__":
    unittest.main()
