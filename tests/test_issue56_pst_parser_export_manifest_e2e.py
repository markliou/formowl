from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import stat
import sys
import unittest

import _paths  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "issue56_pst_parser_export_manifest.py"
REAL_OUTPUT_ROOT = ROOT / ".test-tmp" / "issue56-pst-parser-export-v1"
REAL_FINALIZED_MANIFEST = REAL_OUTPUT_ROOT / "finalized-v2" / "private-parser-manifest.json"
REAL_FINALIZED_REPORT = REAL_OUTPUT_ROOT / "finalized-v2" / "public-report.json"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "issue56_pst_parser_export_manifest",
        SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


parser_export = _load_module()


class Issue56PstParserExportManifestE2ETests(unittest.TestCase):
    def test_one_time_parser_export_builds_private_manifest_and_safe_report(
        self,
    ) -> None:
        root = _paths.fresh_test_dir("issue56-parser-export-manifest")
        pst_path = root / "source.pst"
        pst_path.write_bytes(b"!BDN synthetic authorized parser fixture")
        parser_path = root / "fake-readpst"
        parser_path.write_text(
            """#!/usr/bin/env python3
from email.message import EmailMessage
from pathlib import Path
import sys

if "-V" in sys.argv:
    print("ReadPST / LibPST v0.6.76")
    raise SystemExit(0)
output = Path(sys.argv[sys.argv.index("-o") + 1])
folder = output / "Mailbox"
folder.mkdir(parents=True)
attachment = b"synthetic attachment bytes"
message = EmailMessage()
message["Subject"] = "Synthetic private subject"
message["From"] = "sender@example.test"
message["To"] = "receiver@example.test"
message["Date"] = "Tue, 18 Aug 2026 10:00:00 +0800"
message["Message-ID"] = "<synthetic@example.test>"
message.set_content("synthetic private body")
message.add_attachment(
    attachment,
    maintype="application",
    subtype="octet-stream",
    filename="private.bin",
)
(folder / "1").write_bytes(message.as_bytes())
(folder / "1-attachment.bin").write_bytes(attachment)
(folder / "1-rtf-body.rtf").write_bytes(b"{\\\\rtf1 synthetic body representation}")
""",
            encoding="utf-8",
        )
        parser_path.chmod(
            parser_path.stat().st_mode | stat.S_IXUSR,
        )
        output_root = root / "private-export"
        expected_asset_sha256 = parser_export._sha256_file(pst_path)

        artifacts = parser_export.run_parser_export_once(
            pst_path=pst_path,
            output_root=output_root,
            parser_command=str(parser_path),
            expected_asset_sha256=expected_asset_sha256,
            progress_interval_seconds=60,
        )

        self.assertEqual(artifacts.private_manifest["status"], "passed")
        self.assertEqual(artifacts.public_report["status"], "passed")
        self.assertEqual(
            artifacts.private_manifest["source_asset_sha256"],
            expected_asset_sha256,
        )
        self.assertEqual(
            artifacts.private_manifest["counts"]["message_count"],
            1,
        )
        self.assertEqual(
            artifacts.private_manifest["counts"]["embedded_attachment_count"],
            1,
        )
        self.assertEqual(
            artifacts.private_manifest["counts"]["matched_separate_attachment_count"],
            1,
        )
        self.assertEqual(
            artifacts.private_manifest["counts"]["rtf_body_sidecar_count"],
            1,
        )
        self.assertEqual(
            artifacts.private_manifest["counts"]["separate_attachment_count"],
            1,
        )
        self.assertEqual(
            artifacts.private_manifest["counts"]["unclassified_export_file_count"],
            0,
        )
        self.assertEqual(
            artifacts.private_manifest["counts"]["classified_export_file_count"],
            3,
        )
        message = artifacts.private_manifest["messages"][0]
        self.assertEqual(
            {
                "source_local_key",
                "message_content_hash",
                "body_hash",
                "folder_occurrence_hash",
                "folder_identity_fingerprint",
                "export_ordinal",
            }
            - message.keys(),
            set(),
        )
        attachment = message["attachments"][0]
        self.assertEqual(
            {
                "source_local_key",
                "attachment_content_hash",
                "folder_occurrence_hash",
                "export_ordinal",
            }
            - attachment.keys(),
            set(),
        )
        self.assertEqual(len(message["body_sidecars"]), 1)
        self.assertEqual(len(message["attachments"]), 2)
        self.assertEqual(
            message["body_sidecars"][0]["representation_kind"],
            "rtf_body_representation",
        )
        self.assertNotIn(
            message["body_sidecars"][0],
            message["attachments"],
        )
        self.assertEqual(
            json.loads((output_root / "private-parser-manifest.json").read_text(encoding="utf-8")),
            artifacts.private_manifest,
        )
        self.assertEqual(
            json.loads((output_root / "public-report.json").read_text(encoding="utf-8")),
            artifacts.public_report,
        )
        export_mode = stat.S_IMODE((output_root / "export" / "Mailbox" / "1").stat().st_mode)
        self.assertEqual(export_mode & 0o222, 0)
        rendered = json.dumps(artifacts.public_report, sort_keys=True).casefold()
        for forbidden in (
            "synthetic private subject",
            "sender@example.test",
            "synthetic private body",
            "private.bin",
            str(root).casefold(),
        ):
            self.assertNotIn(forbidden, rendered)
        with self.assertRaisesRegex(
            RuntimeError,
            "parser_export_output_root_not_new",
        ):
            parser_export.run_parser_export_once(
                pst_path=pst_path,
                output_root=output_root,
                parser_command=str(parser_path),
                expected_asset_sha256=expected_asset_sha256,
            )

    def test_existing_export_classifies_unsupported_main_without_readpst(
        self,
    ) -> None:
        root = _paths.fresh_test_dir("issue56-parser-export-unsupported-main")
        pst_path = root / "source.pst"
        pst_path.write_bytes(b"!BDN synthetic authorized parser fixture")
        output_root = root / "private-export"
        export_folder = output_root / "export" / "Mailbox"
        export_folder.mkdir(parents=True)
        (export_folder / "1").write_bytes(b"not an RFC822 message")
        (export_folder / "1-sidecar.bin").write_bytes(b"unresolved synthetic sidecar")
        expected_asset_sha256 = parser_export._sha256_file(pst_path)

        artifacts = parser_export.build_manifest_from_existing_export(
            pst_path=pst_path,
            output_root=output_root,
            parser_version="0.6.76",
            stdout_fingerprint=parser_export.sha256_json("stdout"),
            stderr_fingerprint=parser_export.sha256_json("stderr"),
            elapsed_seconds=0,
            expected_asset_sha256=expected_asset_sha256,
        )

        self.assertEqual(artifacts.private_manifest["status"], "blocked")
        self.assertEqual(
            artifacts.private_manifest["counts"]["unsupported_main_record_count"],
            1,
        )
        self.assertEqual(
            artifacts.private_manifest["counts"]["unsupported_export_file_count"],
            2,
        )
        self.assertEqual(
            artifacts.private_manifest["counts"]["classified_export_file_count"],
            2,
        )
        self.assertEqual(
            artifacts.private_manifest["counts"]["unclassified_export_file_count"],
            0,
        )
        unsupported = artifacts.private_manifest["unsupported_main_records"][0]
        self.assertEqual(len(unsupported["export_files"]), 2)
        self.assertEqual(
            {row["representation_kind"] for row in unsupported["export_files"]},
            {
                "unsupported_main_candidate",
                "unresolved_separate_sidecar",
            },
        )

    @unittest.skipUnless(
        REAL_FINALIZED_MANIFEST.is_file(),
        "real immutable parser export manifest is required",
    )
    def test_real_parser_manifest_is_asset_bound_and_round_trips(self) -> None:
        private_manifest = json.loads(REAL_FINALIZED_MANIFEST.read_text(encoding="utf-8"))
        public_report = json.loads(REAL_FINALIZED_REPORT.read_text(encoding="utf-8"))
        parser_export._validate_private_manifest(private_manifest)
        parser_export._validate_public_report(public_report)
        self.assertEqual(
            private_manifest["source_asset_sha256"],
            parser_export.EXPECTED_ASSET_SHA256,
        )
        self.assertEqual(
            public_report["private_manifest_fingerprint"],
            private_manifest["manifest_fingerprint"],
        )
        self.assertEqual(private_manifest["parser_id"], "readpst")
        self.assertEqual(
            private_manifest["parser_config"]["flags"],
            ["-S", "-t", "ea"],
        )
        self.assertEqual(
            private_manifest["counts"]["export_file_count"],
            7905,
        )
        self.assertEqual(
            private_manifest["counts"]["message_count"],
            2609,
        )
        self.assertEqual(
            private_manifest["counts"]["main_export_record_count"],
            2610,
        )
        self.assertEqual(
            private_manifest["counts"]["unsupported_main_record_count"],
            1,
        )
        self.assertEqual(
            private_manifest["counts"]["rtf_body_sidecar_count"],
            325,
        )
        self.assertEqual(
            private_manifest["counts"]["separate_attachment_count"],
            4970,
        )
        self.assertEqual(
            private_manifest["counts"]["unclassified_export_file_count"],
            0,
        )
        self.assertEqual(
            private_manifest["counts"]["classified_export_file_count"],
            7905,
        )


if __name__ == "__main__":
    unittest.main()
