from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from formowl_contract import sha256_json


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "issue56_full_pst_source_reconciliation.py"
SPEC = importlib.util.spec_from_file_location(
    "issue56_full_pst_source_reconciliation",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
reconciliation = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = reconciliation
SPEC.loader.exec_module(reconciliation)

REAL_PST = ROOT / "tests" / "pst-exm" / "archive.pst"
REAL_PRESERVED_WORK_DIR = ROOT / ".test-tmp" / "exm-archive-domain-hard-work"


class Issue56FullPstSourceReconciliationE2ETests(unittest.TestCase):
    def test_oracle_is_persisted_first_and_policy_exclusion_uses_typed_contract(
        self,
    ) -> None:
        root = _paths.fresh_test_dir("issue56-full-source-policy-exclusion")
        pst_path, work_dir = _fixture(
            root,
            raw_folders=[
                ("Inbox", [("Alice", "Keep", "2026-08-18 01:00:00")]),
                (
                    "Deleted Items",
                    [("Alice", "Excluded", "2026-08-18 02:00:00")],
                ),
            ],
            observed_messages=[("Inbox", "Alice", "Keep")],
        )
        oracle_output = root / "artifacts" / "oracle.json"
        observation_output = root / "artifacts" / "observations.json"
        report_output = root / "artifacts" / "report.json"
        original_builder = reconciliation._build_observation_manifest
        order_checks: list[bool] = []

        def checked_builder(**kwargs):
            persisted = json.loads(oracle_output.read_text(encoding="utf-8"))
            order_checks.append(
                persisted["pipeline_sequence"] == 1 and persisted["counts"]["message_count"] == 2
            )
            return original_builder(**kwargs)

        with patch.object(
            reconciliation,
            "_build_observation_manifest",
            side_effect=checked_builder,
        ):
            artifacts = reconciliation.run_full_pst_source_reconciliation(
                pst_path=pst_path,
                preserved_work_dir=work_dir,
                oracle_output=oracle_output,
                observation_output=observation_output,
                report_output=report_output,
                lspst_command=str(root / "fake-lspst"),
            )

        self.assertEqual(order_checks, [True])
        self.assertEqual(artifacts.report["status"], "passed")
        self.assertEqual(
            artifacts.report["source_completeness_gate_status"],
            "eligible",
        )
        self.assertEqual(
            artifacts.report["counts"]["net_message_occurrence_loss_count"],
            1,
        )
        self.assertEqual(
            artifacts.report["counts"]["intentionally_excluded_message_count"],
            1,
        )
        self.assertEqual(
            artifacts.report["counts"]["intentionally_excluded_folder_count"],
            1,
        )
        self.assertEqual(
            artifacts.report["counts"]["policy_excluded_count"],
            2,
        )
        self.assertEqual(
            artifacts.report["counts"]["unexplained_loss_count"],
            0,
        )
        self.assertEqual(
            artifacts.report["counts"]["unexplained_identity_count"],
            0,
        )
        self.assertEqual(
            artifacts.report["counts"]["occurrence_lineage_loss_count"],
            0,
        )
        self.assertEqual(
            artifacts.report["counts"]["matched_observation_occurrence_identity_count"],
            1,
        )
        self.assertEqual(
            json.loads(oracle_output.read_text(encoding="utf-8")),
            artifacts.oracle_manifest,
        )
        self.assertEqual(
            json.loads(observation_output.read_text(encoding="utf-8")),
            artifacts.observation_manifest,
        )
        self.assertEqual(
            json.loads(report_output.read_text(encoding="utf-8")),
            artifacts.report,
        )
        rendered = (
            oracle_output.read_text(encoding="utf-8")
            + observation_output.read_text(encoding="utf-8")
            + report_output.read_text(encoding="utf-8")
        )
        for forbidden in (
            "Alice",
            "Keep",
            "Excluded",
            "Deleted Items",
            str(root),
        ):
            self.assertNotIn(forbidden, rendered)

    def test_unknown_raw_identity_keeps_source_completeness_blocked(self) -> None:
        root = _paths.fresh_test_dir("issue56-full-source-unknown-loss")
        pst_path, work_dir = _fixture(
            root,
            raw_folders=[
                (
                    "Inbox",
                    [
                        ("Alice", "Keep", "2026-08-18 01:00:00"),
                        ("Alice", "Unknown", "2026-08-18 02:00:00"),
                    ],
                )
            ],
            observed_messages=[("Inbox", "Alice", "Keep")],
        )
        artifacts = reconciliation.run_full_pst_source_reconciliation(
            pst_path=pst_path,
            preserved_work_dir=work_dir,
            oracle_output=root / "oracle.json",
            observation_output=root / "observations.json",
            report_output=root / "report.json",
            lspst_command=str(root / "fake-lspst"),
        )

        self.assertEqual(artifacts.report["status"], "blocked")
        self.assertEqual(
            artifacts.report["source_completeness_gate_status"],
            "blocked",
        )
        self.assertEqual(
            artifacts.report["counts"]["raw_message_count"],
            2,
        )
        self.assertEqual(
            artifacts.report["counts"]["observed_message_count"],
            1,
        )
        self.assertEqual(
            artifacts.report["counts"]["unknown_raw_message_count"],
            1,
        )
        self.assertEqual(
            artifacts.report["counts"]["unexplained_loss_count"],
            1,
        )
        self.assertEqual(
            artifacts.report["counts"]["unexplained_identity_count"],
            1,
        )
        self.assertEqual(
            artifacts.report["counts"]["occurrence_lineage_loss_count"],
            0,
        )
        self.assertGreater(artifacts.report["counts"]["blocker_count"], 0)

    @unittest.skipUnless(
        REAL_PST.is_file()
        and REAL_PRESERVED_WORK_DIR.is_dir()
        and shutil.which("lspst") is not None,
        "full PST fixture, preserved snapshot, and lspst are required",
    )
    def test_real_full_asset_reconciliation_is_safe_and_honestly_blocked(
        self,
    ) -> None:
        root = _paths.fresh_test_dir("issue56-full-source-real-reconciliation")
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--pst",
                str(REAL_PST),
                "--preserved-work-dir",
                str(REAL_PRESERVED_WORK_DIR),
                "--oracle-output",
                str(root / "oracle.json"),
                "--observation-output",
                str(root / "observations.json"),
                "--output",
                str(root / "report.json"),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(completed.returncode, 2, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(
            report["source_asset_sha256"],
            "sha256:82dddb25fffd14cd0c5576a0791bc408aab0d15d5eb76be1727e14cff658caaf",
        )
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["counts"]["raw_message_count"], 2793)
        self.assertEqual(report["counts"]["observed_message_count"], 2668)
        self.assertEqual(
            report["counts"]["net_message_occurrence_loss_count"],
            125,
        )
        self.assertEqual(
            report["counts"]["matched_message_identity_count"],
            2636,
        )
        self.assertEqual(
            report["counts"]["raw_only_message_identity_count"],
            157,
        )
        self.assertEqual(
            report["counts"]["observation_only_message_identity_count"],
            32,
        )
        self.assertEqual(
            report["counts"]["policy_excluded_count"],
            0,
        )
        self.assertEqual(
            report["counts"]["unknown_raw_message_count"],
            157,
        )
        self.assertEqual(
            report["counts"]["unexplained_loss_count"],
            157,
        )
        self.assertEqual(
            report["counts"]["unexplained_identity_count"],
            189,
        )
        self.assertEqual(
            report["counts"]["unknown_observation_message_count"],
            32,
        )
        self.assertEqual(
            report["counts"]["matched_observation_occurrence_identity_count"],
            2636,
        )
        self.assertEqual(
            report["counts"]["preserved_exported_message_identity_count"],
            2668,
        )
        self.assertEqual(
            report["counts"]["missing_source_inventory_binding_count"],
            2668,
        )
        self.assertEqual(
            report["counts"]["occurrence_lineage_loss_count"],
            2668,
        )
        self.assertEqual(report["counts"]["raw_folder_count"], 3)
        self.assertEqual(report["counts"]["observed_folder_count"], 3)
        self.assertEqual(report["counts"]["observed_attachment_count"], 24)
        self.assertEqual(
            report["round_trip_status"],
            {
                "raw_oracle_manifest": "passed",
                "observation_manifest": "passed",
                "reconciliation_report": "passed",
            },
        )
        rendered = completed.stdout.casefold()
        for forbidden in (
            "subject",
            "sender",
            "folder_label",
            "filename",
            "object_uri",
            "pst-scratch",
        ):
            self.assertNotIn(forbidden, rendered)


def _fixture(
    root: Path,
    *,
    raw_folders: list[tuple[str, list[tuple[str, str, str]]]],
    observed_messages: list[tuple[str, str, str]],
) -> tuple[Path, Path]:
    pst_path = root / "source.pst"
    pst_path.write_bytes(b"!BDN issue56 source reconciliation fixture")
    source_asset_sha256 = (
        "sha256:" + __import__("hashlib").sha256(pst_path.read_bytes()).hexdigest()
    )
    work_dir = root / "preserved"
    ingestion_root = work_dir / "data" / "ingestion"
    for directory in ("assets", "extractor-runs", "observations"):
        (ingestion_root / directory).mkdir(parents=True, exist_ok=True)
    asset_id = "asset_issue56_full_source_fixture"
    permission_scope = {
        "scope_type": "project",
        "scope_id": "project_issue56",
        "visibility": "restricted",
        "workspace_id": "workspace_formowl",
        "owner_user_id": "user_issue56_operator",
    }
    _write_json(
        ingestion_root / "assets" / "asset.json",
        {
            "asset_id": asset_id,
            "content_hash": source_asset_sha256,
            "created_at": "2026-08-18T00:00:00+00:00",
            "permission_scope": permission_scope,
        },
    )
    _write_json(
        ingestion_root / "extractor-runs" / "run.json",
        {
            "asset_id": asset_id,
            "input_hash": source_asset_sha256,
            "status": "succeeded",
            "errors": [],
            "warnings": [],
            "extractor_name": "pst_mail_archive_extractor",
            "extractor_version": "0.1.0",
            "config_hash": sha256_json({"include_deleted_items": False}),
        },
    )
    folder_paths: dict[str, str] = {}
    for folder_index, folder_name in enumerate(
        dict.fromkeys(folder for folder, _sender, _subject in observed_messages),
        start=1,
    ):
        folder_path_fingerprint = sha256_json({"fixture_folder_index": folder_index})
        folder_paths[folder_name] = folder_path_fingerprint
        _write_json(
            ingestion_root / "observations" / f"folder-{folder_index}.json",
            {
                "asset_id": asset_id,
                "observation_type": "mail_folder_occurrence",
                "location": {
                    "folder_path_hash": folder_path_fingerprint,
                },
                "payload": {
                    "folder_path_hash": folder_path_fingerprint,
                    "folder_label": folder_name,
                },
            },
        )
    for message_index, (folder_name, sender, subject) in enumerate(
        observed_messages,
        start=1,
    ):
        _write_json(
            ingestion_root / "observations" / f"message-{message_index}.json",
            {
                "asset_id": asset_id,
                "observation_type": "email_message",
                "location": {
                    "folder_path_hash": folder_paths[folder_name],
                    "message_index": message_index,
                    "message_occurrence_id": f"mailocc_fixture_{message_index}",
                    "source_inventory_item_id": f"srcinvitem_fixture_{message_index}",
                },
                "payload": {
                    "subject": subject,
                    "sender": sender,
                    "sent_at": "2026-08-18T01:00:00+00:00",
                    "message_fingerprint": sha256_json(
                        {
                            "fixture_message_index": message_index,
                            "subject": subject,
                        }
                    ),
                },
            },
        )

    lines = ["#!/bin/sh", 'if [ "$1" = "-V" ]; then echo "lspst fixture 1"; exit 0; fi']
    for folder_name, messages in raw_folders:
        lines.append("printf '%s\\n' " + shlex.quote(f'Folder "{folder_name}"'))
        for sender, subject, date in messages:
            lines.append(
                "printf '%s\\n' "
                + shlex.quote(
                    "Email\t" + f"From: {sender}\t" + f"Subject: {subject}\t" + f"Date: {date}"
                )
            )
    parser = root / "fake-lspst"
    parser.write_text("\n".join(lines) + "\n", encoding="utf-8")
    parser.chmod(0o755)
    return pst_path, work_dir


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
