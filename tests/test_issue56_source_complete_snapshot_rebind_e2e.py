from __future__ import annotations

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import unittest

import _paths  # noqa: F401
from formowl_contract import Observation, SourceInventory, sha256_json
from formowl_core import load_issue56_target_mail_tokenizer_profile
from formowl_mail import (
    MailEvidenceBundle,
    MailEvidenceQueryGateway,
    build_existing_observation_snippet_index,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "issue56_source_complete_snapshot_rebind.py"
RECONCILIATION_TEST_PATH = ROOT / "tests" / "test_issue56_full_pst_source_reconciliation_e2e.py"
REAL_PST = ROOT / "tests" / "pst-exm" / "archive.pst"
REAL_PRESERVED_WORK_DIR = ROOT / ".test-tmp" / "exm-archive-domain-hard-work"
REAL_PARSER_MANIFEST = (
    ROOT
    / ".test-tmp"
    / "issue56-pst-parser-export-v1"
    / "finalized-v2"
    / "private-parser-manifest.json"
)
REAL_NATIVE_ROOT = ROOT / ".issue56-private-native-lineage-v1"
REAL_NATIVE_MANIFEST = REAL_NATIVE_ROOT / "native-private-manifest.json"
REAL_NATIVE_EXPORT = REAL_NATIVE_ROOT / "export"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


rebind = _load_module(
    "issue56_source_complete_snapshot_rebind",
    SCRIPT_PATH,
)
reconciliation_test = _load_module(
    "issue56_full_pst_source_reconciliation_test_fixture",
    RECONCILIATION_TEST_PATH,
)


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _native_sha256_json(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _native_source_local_key(kind: str, seed: str) -> str:
    return f"pstnative_{kind}_{sha256_json(seed).removeprefix('sha256:')[:32]}"


def _native_fixture(root: Path) -> tuple[Path, Path, Path]:
    export_root = root / "native-export"
    export_root.mkdir(parents=True)
    message_one = (
        "From: one@example.test\n"
        "To: two@example.test\n"
        "Subject: 供應鏈里程碑 CASE-ZH-2026-8842\n"
        "Message-ID: <case-zh-2026-8842@example.test>\n"
        "Content-Type: text/plain; charset=utf-8\n"
        "\n"
        "供應鏈里程碑已核准，追蹤識別碼 CASE-ZH-2026-8842。\n"
    ).encode()
    message_two = (
        "From: two@example.test\n"
        "To: one@example.test\n"
        "Subject: Routine status\n"
        "Message-ID: <routine-2026@example.test>\n"
        "Content-Type: text/plain; charset=utf-8\n"
        "\n"
        "Routine status remains unchanged.\n"
    ).encode()
    attachment_one = b"attachment-one"
    synthetic_body = b"synthetic-body"
    outputs = {
        "mail/one.eml": message_one,
        "mail/two.eml": message_two,
        "mail/one-att.bin": attachment_one,
        "mail/two-body.bin": synthetic_body,
    }
    for relative, payload in outputs.items():
        output = export_root / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)

    asset_hash = sha256_json("synthetic-native-pst")
    parser_config = {
        "flags": ["-S", "-t", "ea", "-j", "0", "-q"],
        "include_deleted_items": False,
        "msg_output_enabled": False,
        "source_native_lineage": True,
    }
    message_one_key = _native_source_local_key("message", "message-one")
    message_two_key = _native_source_local_key("message", "message-two")
    attachment_one_key = _native_source_local_key("attachment", "attachment-one")
    embedded_key = _native_source_local_key("attachment", "embedded-one")
    synthetic_key = _native_source_local_key("attachment", "synthetic-one")
    manifest = {
        "artifact_id": "formowl_issue56_pst_native_lineage_private_manifest_v1",
        "schema_version": 1,
        "status": "passed",
        "source_asset_sha256": asset_hash,
        "parser_source_commit": "d963f2adf9fb7e65cdccbf7d35ceb06c63100f80",
        "parser_binary_sha256": sha256_json("parser-binary"),
        "runtime_library_sha256": sha256_json("runtime-library"),
        "parser_config": parser_config,
        "parser_config_fingerprint": sha256_json(parser_config),
        "sidecar_sha256": sha256_json("sidecar"),
        "counts": {
            "message_occurrence_count": 2,
            "message_exported_count": 2,
            "message_unexplained_count": 0,
            "attachment_output_occurrence_count": 3,
            "attachment_nonzero_node_id_count": 2,
            "attachment_embedded_message_count": 1,
            "attachment_synthetic_representation_count": 1,
            "duplicate_attachment_identity_count": 0,
            "unsupported_non_message_record_count": 1,
            "failed_record_count": 0,
        },
        "blocker_ids": [],
        "messages": [
            {
                "source_local_key": message_one_key,
                "pst_folder_node_id": "0000000000000011",
                "pst_message_node_id": "0000000000000101",
                "pst_message_data_node_id": "0000000000000201",
                "export_disposition": "exported",
                "export_status": "passed",
                "export_reason": "none",
                "message_content_hash": _sha256_bytes(message_one),
                "byte_count": len(message_one),
                "relative_output_path": "mail/one.eml",
                "attachments": [
                    {
                        "source_local_key": attachment_one_key,
                        "pst_attachment_node_id": "0000000000000301",
                        "export_disposition": "separate_exported",
                        "export_status": "passed",
                        "export_reason": "none",
                        "attachment_content_hash": _sha256_bytes(attachment_one),
                        "byte_count": len(attachment_one),
                        "export_occurrence_ordinal": 1,
                        "relative_output_path": "mail/one-att.bin",
                    },
                    {
                        "source_local_key": embedded_key,
                        "pst_attachment_node_id": "0000000000000302",
                        "export_disposition": "embedded_message_exported",
                        "export_status": "passed",
                        "export_reason": "none",
                        "attachment_content_hash": sha256_json("embedded-bytes"),
                        "byte_count": 42,
                        "export_occurrence_ordinal": 1,
                        "relative_output_path": None,
                    },
                ],
            },
            {
                "source_local_key": message_two_key,
                "pst_folder_node_id": "0000000000000012",
                "pst_message_node_id": "0000000000000102",
                "pst_message_data_node_id": "0000000000000202",
                "export_disposition": "exported",
                "export_status": "passed",
                "export_reason": "none",
                "message_content_hash": _sha256_bytes(message_two),
                "byte_count": len(message_two),
                "relative_output_path": "mail/two.eml",
                "attachments": [
                    {
                        "source_local_key": synthetic_key,
                        "pst_attachment_node_id": "0000000000000000",
                        "export_disposition": "synthetic_body_exported",
                        "export_status": "passed",
                        "export_reason": "none",
                        "attachment_content_hash": _sha256_bytes(synthetic_body),
                        "byte_count": len(synthetic_body),
                        "export_occurrence_ordinal": 1,
                        "relative_output_path": "mail/two-body.bin",
                    }
                ],
            },
        ],
        "unsupported_non_message_records": [
            {
                "pst_folder_node_id": "0000000000000012",
                "pst_record_node_id": "0000000000000401",
                "pst_record_data_node_id": "0000000000000501",
                "export_disposition": "not_exported",
                "export_status": "passed",
                "export_reason": "unsupported_item_type",
            }
        ],
    }
    manifest["manifest_fingerprint"] = _native_sha256_json(manifest)
    manifest_path = root / "native-private-manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")

    work_dir = root / "governed-binding"
    asset_root = work_dir / "data" / "ingestion" / "assets"
    asset_root.mkdir(parents=True)
    asset = {
        "asset_id": "asset_issue56_native_fixture",
        "storage_backend_id": "storage_issue56_fixture",
        "object_uri": "formowl://evidence/issue56-native-fixture",
        "content_hash": asset_hash,
        "file_size": 123,
        "mime_type": "application/vnd.ms-outlook-pst",
        "created_at": "2026-08-18T08:00:00+00:00",
        "registered_at": "2026-08-18T08:00:00+00:00",
        "owner_user_id": "user_issue56_fixture",
        "workspace_id": "workspace_issue56_fixture",
        "project_id": "project_issue56_fixture",
        "permission_scope": {
            "scope_type": "project",
            "scope_id": "project_issue56_fixture",
            "visibility": "restricted",
        },
        "lifecycle_state": "active",
        "source_ref": {
            "source_system": "mail_archive",
            "source_type": "pst",
            "source_id": "issue56-native-fixture",
            "source_key": "authorized-fixture",
        },
    }
    (asset_root / "asset.json").write_text(
        json.dumps(asset, sort_keys=True),
        encoding="utf-8",
    )
    return manifest_path, export_root, work_dir


class Issue56SourceCompleteSnapshotRebindE2ETests(unittest.TestCase):
    def test_private_content_probe_prefers_bounded_low_frequency_protected_tokens(
        self,
    ) -> None:
        profile = load_issue56_target_mail_tokenizer_profile()

        class CountingProfile:
            def __init__(self) -> None:
                self.calls = 0

            def analyze(self, value: str):
                self.calls += 1
                return profile.analyze(value)

        snippets = []
        postings = {}
        token_to_observation_id = {}
        for index in range(96):
            surface = f"probe-{index:03d}@example.test"
            analysis = profile.analyze(surface)
            token = analysis.protected_identifiers[0].exact_token
            observation_id = f"observation_probe_{index:03d}"
            snippets.append(
                SimpleNamespace(
                    protected_identifier_tokens=frozenset({token}),
                    dense_evidence_text=f"private content {surface}",
                    payload={"source_observation_id": observation_id},
                )
            )
            postings[token] = (index,)
            token_to_observation_id[token] = observation_id
        snippet_index = SimpleNamespace(
            snippets=tuple(snippets),
            snippet_indexes_by_token=postings,
        )
        expected_token = min(postings, key=sha256_json)
        counting_profile = CountingProfile()

        query_text, observation_id = rebind._select_private_content_probe(
            snippet_index=snippet_index,
            tokenizer_profile=counting_profile,
        )

        self.assertEqual(query_text, expected_token)
        self.assertEqual(observation_id, token_to_observation_id[expected_token])
        self.assertLessEqual(
            counting_profile.calls,
            rebind._PRIVATE_PROBE_MAX_PROTECTED_CANDIDATES,
        )

    def test_native_authority_builds_new_source_complete_observation_snapshot(
        self,
    ) -> None:
        root = _paths.fresh_test_dir("issue56-native-source-complete")
        manifest_path, export_root, work_dir = _native_fixture(root)
        created_at = "2026-08-18T09:00:00+00:00"
        first = rebind.run_native_source_complete_snapshot(
            native_manifest_path=manifest_path,
            native_export_root=export_root,
            preserved_work_dir=work_dir,
            snapshot_output=root / "first-snapshot.json",
            report_output=root / "first-report.json",
            created_at=created_at,
        )
        second = rebind.run_native_source_complete_snapshot(
            native_manifest_path=manifest_path,
            native_export_root=export_root,
            preserved_work_dir=work_dir,
            snapshot_output=root / "second-snapshot.json",
            report_output=root / "second-report.json",
            created_at=created_at,
        )

        self.assertEqual(first.report["status"], "passed")
        self.assertEqual(
            first.report["source_completeness_gate_status"],
            "eligible",
        )
        self.assertEqual(first.report["canonical_fact_status"], "not_asserted")
        self.assertEqual(first.report["methodology_readiness_status"], "blocked")
        self.assertEqual(first.report["counts"]["folder_occurrence_count"], 2)
        self.assertEqual(first.report["counts"]["message_occurrence_count"], 2)
        self.assertEqual(
            first.report["counts"]["attachment_export_occurrence_count"],
            3,
        )
        self.assertEqual(
            first.report["counts"]["attachment_export_file_binding_count"],
            2,
        )
        self.assertEqual(
            first.report["counts"]["attachment_source_descriptor_binding_count"],
            1,
        )
        self.assertEqual(
            first.report["counts"]["unsupported_preserved_occurrence_count"],
            1,
        )
        self.assertEqual(first.report["counts"]["source_inventory_item_count"], 8)
        self.assertEqual(first.report["counts"]["observation_count"], 8)
        self.assertEqual(first.report["counts"]["unexplained_loss_count"], 0)
        self.assertEqual(first.report["counts"]["blocker_count"], 0)
        self.assertEqual(
            first.report["source_inventory_fingerprint"],
            second.report["source_inventory_fingerprint"],
        )
        self.assertEqual(
            first.report["observation_snapshot_fingerprint"],
            second.report["observation_snapshot_fingerprint"],
        )
        self.assertEqual(
            first.report["attachment_lineage_fingerprint"],
            second.report["attachment_lineage_fingerprint"],
        )
        inventory = SourceInventory.from_dict(first.snapshot["source_inventory"])
        observations = [Observation.from_dict(row) for row in first.snapshot["observations"]]
        self.assertEqual(len(inventory.items), len(observations))
        self.assertEqual(
            {observation.location["source_inventory_item_id"] for observation in observations},
            {item.source_inventory_item_id for item in inventory.items},
        )
        self.assertTrue(
            all(
                observation.payload["canonical_fact_status"] == "not_asserted"
                for observation in observations
            )
        )
        public_rendered = json.dumps(first.report, sort_keys=True).casefold()
        for forbidden in (
            "relative_output",
            "filename",
            "subject",
            "sender",
            "body",
            "payload",
            "object_uri",
        ):
            self.assertNotIn(forbidden, public_rendered)

    def test_native_source_complete_snapshot_builds_retrieval_ready_mail_bundle(
        self,
    ) -> None:
        root = _paths.fresh_test_dir("issue56-native-retrieval-ready")
        manifest_path, export_root, work_dir = _native_fixture(root)
        created_at = "2026-08-18T09:30:00+00:00"

        def build(run_name: str):
            run_root = root / run_name
            return rebind.run_native_retrieval_ready_mail_evidence(
                native_manifest_path=manifest_path,
                native_export_root=export_root,
                preserved_work_dir=work_dir,
                source_snapshot_output=run_root / "source-snapshot.json",
                source_report_output=run_root / "source-report.json",
                retrieval_snapshot_output=run_root / "retrieval-snapshot.json",
                bundle_output=run_root / "mail-bundle.json",
                report_output=run_root / "retrieval-report.json",
                created_at=created_at,
            )

        first = build("first")
        second = build("second")
        report = first.report
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["source_completeness_status"], "passed")
        self.assertEqual(report["retrieval_ready_status"], "passed")
        self.assertEqual(
            report["query_evidence_profile_binding_status"],
            "passed",
        )
        self.assertEqual(
            report["target_profile_status"],
            "passed_no_ascii_fallback",
        )
        self.assertEqual(report["authorized_query_status"], "passed")
        self.assertEqual(
            report["denied_query_status"],
            "passed_fail_closed",
        )
        self.assertEqual(report["canonical_fact_status"], "not_asserted")
        self.assertEqual(report["methodology_readiness_status"], "blocked")
        self.assertEqual(report["counts"]["source_inventory_item_count"], 8)
        self.assertEqual(
            report["counts"]["source_occurrence_observation_count"],
            8,
        )
        self.assertEqual(
            report["counts"]["parsed_message_observation_count"],
            2,
        )
        self.assertGreaterEqual(
            report["counts"]["parsed_header_observation_count"],
            8,
        )
        self.assertEqual(
            report["counts"]["parsed_body_segment_observation_count"],
            2,
        )
        self.assertEqual(
            report["counts"]["parsed_attachment_observation_count"],
            3,
        )
        self.assertEqual(
            report["counts"]["mail_bundle_message_occurrence_count"],
            2,
        )
        self.assertEqual(
            report["counts"]["mail_bundle_attachment_occurrence_count"],
            3,
        )
        self.assertEqual(report["counts"]["authorized_result_count"], 1)
        self.assertEqual(report["counts"]["denied_result_count"], 0)
        self.assertEqual(report["counts"]["unexplained_loss_count"], 0)
        self.assertEqual(
            report["retrieval_snapshot_fingerprint"],
            second.report["retrieval_snapshot_fingerprint"],
        )
        self.assertEqual(
            report["mail_evidence_bundle_fingerprint"],
            second.report["mail_evidence_bundle_fingerprint"],
        )
        self.assertEqual(
            report["index_fingerprint"],
            second.report["index_fingerprint"],
        )

        bundle = MailEvidenceBundle.from_dict(first.bundle["bundle"])
        observations = [
            Observation.from_dict(row)
            for row in first.retrieval_snapshot["source_occurrence_observations"]
            + first.retrieval_snapshot["parsed_mail_observations"]
        ]
        profile = load_issue56_target_mail_tokenizer_profile()
        snippet_index, manifest = build_existing_observation_snippet_index(
            observations,
            bundle=bundle,
            tokenizer_profile=profile,
        )
        gateway = MailEvidenceQueryGateway(
            [bundle],
            tokenizer_profile=profile,
            snippet_index_by_bundle_id={bundle.mail_evidence_bundle_id: snippet_index},
        )
        owner_result = gateway.query_mail_evidence(
            query_text="供應鏈 CASE-ZH-2026-8842",
            requester_user_id="user_issue56_fixture",
            workspace_id="workspace_issue56_fixture",
            session_id="issue56_native_owner_e2e",
            mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
            limit=5,
        )
        denied_result = gateway.query_mail_evidence(
            query_text="供應鏈 CASE-ZH-2026-8842",
            requester_user_id="user_issue56_denied",
            workspace_id="workspace_issue56_fixture",
            session_id="issue56_native_denied_e2e",
            mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
            limit=5,
        )
        self.assertEqual(owner_result.status, "ok")
        self.assertEqual(len(owner_result.citations), 1)
        self.assertEqual(denied_result.status, "permission_denied")
        self.assertEqual(denied_result.citations, [])
        self.assertEqual(denied_result.evidence_snippets, [])
        self.assertEqual(
            manifest.query_profile_fingerprint,
            manifest.evidence_profile_fingerprint,
        )
        cited_id = owner_result.citations[0]["source_observation_id"]
        cited = next(
            observation for observation in observations if observation.observation_id == cited_id
        )
        self.assertEqual(cited.observation_type, "email_body_segment")
        self.assertTrue(cited.location["source_local_key"].startswith("pstnative_message_"))
        self.assertRegex(
            cited.location["source_content_hash"],
            r"^sha256:[0-9a-f]{64}$",
        )
        self.assertIn("source_inventory_item_id", cited.location)
        public_rendered = json.dumps(report, sort_keys=True, ensure_ascii=False)
        for forbidden in (
            "供應鏈",
            "CASE-ZH-2026-8842",
            "one@example.test",
            "relative_output",
            "filename",
            "subject",
            "sender",
            "payload",
            ".test-tmp",
        ):
            self.assertNotIn(forbidden, public_rendered)

    def test_native_authority_fails_closed_on_export_hash_drift(self) -> None:
        root = _paths.fresh_test_dir("issue56-native-source-complete-drift")
        manifest_path, export_root, work_dir = _native_fixture(root)
        (export_root / "mail" / "one.eml").write_bytes(b"tampered")

        with self.assertRaisesRegex(
            RuntimeError,
            "output_(?:byte_count|content_hash)_drift",
        ):
            rebind.run_native_source_complete_snapshot(
                native_manifest_path=manifest_path,
                native_export_root=export_root,
                preserved_work_dir=work_dir,
                snapshot_output=root / "snapshot.json",
                report_output=root / "report.json",
                created_at="2026-08-18T09:00:00+00:00",
            )

    def test_ambiguous_duplicate_identity_is_not_guessed(self) -> None:
        root = _paths.fresh_test_dir("issue56-source-complete-rebind-ambiguous")
        pst_path, work_dir = reconciliation_test._fixture(
            root,
            raw_folders=[
                (
                    "Inbox",
                    [
                        ("Alice", "Duplicate", "2026-08-18 01:00:00"),
                        ("Alice", "Duplicate", "2026-08-18 01:00:00"),
                    ],
                )
            ],
            observed_messages=[("Inbox", "Alice", "Duplicate")],
        )
        artifacts = rebind.run_source_complete_snapshot_rebind(
            pst_path=pst_path,
            preserved_work_dir=work_dir,
            output_root=root / "intermediate",
            snapshot_output=root / "snapshot.json",
            report_output=root / "report.json",
            lspst_command=str(root / "fake-lspst"),
        )

        self.assertEqual(artifacts.report["status"], "blocked")
        self.assertEqual(
            artifacts.report["counts"]["raw_source_inventory_item_count"],
            2,
        )
        self.assertEqual(
            artifacts.report["counts"]["parsed_rebound_message_count"],
            0,
        )
        self.assertEqual(
            artifacts.report["counts"]["preserved_unparsed_raw_message_count"],
            2,
        )
        self.assertEqual(
            artifacts.report["counts"]["unrebound_observation_count"],
            1,
        )
        self.assertEqual(artifacts.snapshot["rebindings"], [])
        self.assertTrue(
            all(
                item["processing_state"] == "preserved_unparsed"
                for item in artifacts.snapshot["source_inventory"]["items"]
            )
        )

    @unittest.skipUnless(
        REAL_NATIVE_MANIFEST.is_file()
        and REAL_NATIVE_EXPORT.is_dir()
        and REAL_PRESERVED_WORK_DIR.is_dir(),
        "native manifest/export and governed asset binding are required",
    )
    def test_real_native_export_builds_new_source_complete_snapshot(self) -> None:
        root = _paths.fresh_test_dir("issue56-native-source-complete-real")
        old_observation_root = REAL_PRESERVED_WORK_DIR / "data" / "ingestion" / "observations"
        old_observation_count_before = len(list(old_observation_root.glob("*.json")))
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--preserved-work-dir",
                str(REAL_PRESERVED_WORK_DIR),
                "--native-manifest",
                str(REAL_NATIVE_MANIFEST),
                "--native-export-root",
                str(REAL_NATIVE_EXPORT),
                "--snapshot-output",
                str(root / "snapshot.json"),
                "--output",
                str(root / "report.json"),
                "--snapshot-created-at",
                "2026-08-18T10:00:00+00:00",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        persisted_report = json.loads((root / "report.json").read_text(encoding="utf-8"))
        snapshot = json.loads((root / "snapshot.json").read_text(encoding="utf-8"))
        self.assertEqual(report, persisted_report)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(
            report["source_asset_sha256"],
            "sha256:82dddb25fffd14cd0c5576a0791bc408aab0d15d5eb76be1727e14cff658caaf",
        )
        self.assertEqual(report["counts"]["folder_occurrence_count"], 3)
        self.assertEqual(report["counts"]["message_occurrence_count"], 2793)
        self.assertEqual(
            report["counts"]["message_source_inventory_binding_count"],
            2793,
        )
        self.assertEqual(report["counts"]["message_parent_lineage_count"], 2793)
        self.assertEqual(
            report["counts"]["attachment_export_occurrence_count"],
            5645,
        )
        self.assertEqual(
            report["counts"]["attachment_source_inventory_binding_count"],
            5645,
        )
        self.assertEqual(
            report["counts"]["attachment_parent_lineage_count"],
            5645,
        )
        self.assertEqual(
            report["counts"]["attachment_export_file_binding_count"],
            5641,
        )
        self.assertEqual(
            report["counts"]["attachment_source_descriptor_binding_count"],
            4,
        )
        self.assertEqual(
            report["counts"]["attachment_separate_export_count"],
            5178,
        )
        self.assertEqual(
            report["counts"]["attachment_embedded_message_count"],
            4,
        )
        self.assertEqual(
            report["counts"]["attachment_synthetic_representation_count"],
            463,
        )
        self.assertEqual(
            report["counts"]["unsupported_preserved_occurrence_count"],
            2,
        )
        self.assertEqual(report["counts"]["source_inventory_item_count"], 8443)
        self.assertEqual(report["counts"]["observation_count"], 8443)
        self.assertEqual(report["counts"]["unexplained_loss_count"], 0)
        self.assertEqual(report["counts"]["blocker_count"], 0)
        self.assertEqual(
            SourceInventory.from_dict(snapshot["source_inventory"]).to_dict(),
            snapshot["source_inventory"],
        )
        self.assertEqual(
            len([Observation.from_dict(row) for row in snapshot["observations"]]),
            8443,
        )
        self.assertEqual(
            len(list(old_observation_root.glob("*.json"))),
            old_observation_count_before,
        )
        rendered = completed.stdout.casefold()
        for forbidden in (
            "relative_output",
            "filename",
            "subject",
            "sender",
            "body",
            "payload",
            "object_uri",
            ".issue56-private",
            ".test-tmp",
        ):
            self.assertNotIn(forbidden, rendered)

    @unittest.skipUnless(
        os.environ.get("FORMOWL_RUN_ISSUE56_NATIVE_RETRIEVAL_E2E") == "1"
        and REAL_NATIVE_MANIFEST.is_file()
        and REAL_NATIVE_EXPORT.is_dir()
        and REAL_PRESERVED_WORK_DIR.is_dir(),
        "explicit real native retrieval E2E opt-in and private artifacts are required",
    )
    def test_real_native_export_builds_source_complete_mail_evidence_bundle(
        self,
    ) -> None:
        root = _paths.fresh_test_dir("issue56-native-retrieval-ready-real")
        old_observation_root = REAL_PRESERVED_WORK_DIR / "data" / "ingestion" / "observations"
        old_observation_count_before = len(list(old_observation_root.glob("*.json")))
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--preserved-work-dir",
                str(REAL_PRESERVED_WORK_DIR),
                "--native-manifest",
                str(REAL_NATIVE_MANIFEST),
                "--native-export-root",
                str(REAL_NATIVE_EXPORT),
                "--snapshot-output",
                str(root / "source-snapshot.json"),
                "--output",
                str(root / "source-report.json"),
                "--snapshot-created-at",
                "2026-08-18T11:00:00+00:00",
                "--retrieval-ready-output-root",
                str(root / "retrieval"),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=420,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        persisted_report = json.loads(
            (root / "retrieval" / "retrieval-ready-report.safe.json").read_text(encoding="utf-8")
        )
        snapshot = json.loads(
            (root / "retrieval" / "retrieval-ready-snapshot.private.json").read_text(
                encoding="utf-8"
            )
        )
        bundle_artifact = json.loads(
            (root / "retrieval" / "mail-evidence-bundle.private.json").read_text(encoding="utf-8")
        )
        self.assertEqual(report, persisted_report)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["source_completeness_status"], "passed")
        self.assertEqual(report["retrieval_ready_status"], "passed")
        self.assertEqual(
            report["source_asset_fingerprint"],
            "sha256:82dddb25fffd14cd0c5576a0791bc408aab0d15d5eb76be1727e14cff658caaf",
        )
        self.assertEqual(
            report["counts"]["source_inventory_item_count"],
            8443,
        )
        self.assertEqual(
            report["counts"]["source_occurrence_observation_count"],
            8443,
        )
        self.assertEqual(
            report["counts"]["parsed_message_observation_count"],
            2793,
        )
        self.assertGreater(
            report["counts"]["parsed_header_observation_count"],
            0,
        )
        self.assertGreater(
            report["counts"]["parsed_body_segment_observation_count"],
            0,
        )
        self.assertEqual(
            report["counts"]["parsed_attachment_observation_count"],
            5645,
        )
        self.assertEqual(
            report["counts"]["mail_bundle_message_occurrence_count"],
            2793,
        )
        self.assertEqual(
            report["counts"]["mail_bundle_attachment_occurrence_count"],
            5645,
        )
        self.assertGreater(report["counts"]["indexed_snippet_count"], 0)
        self.assertGreater(report["counts"]["authorized_result_count"], 0)
        self.assertEqual(report["counts"]["denied_result_count"], 0)
        self.assertEqual(report["counts"]["unexplained_loss_count"], 0)
        self.assertEqual(report["counts"]["blocker_count"], 0)
        self.assertEqual(
            snapshot["mail_evidence_bundle_fingerprint"],
            report["mail_evidence_bundle_fingerprint"],
        )
        self.assertEqual(
            bundle_artifact["bundle_fingerprint"],
            report["mail_evidence_bundle_fingerprint"],
        )
        self.assertEqual(
            len(list(old_observation_root.glob("*.json"))),
            old_observation_count_before,
        )
        rendered = completed.stdout.casefold()
        for forbidden in (
            "relative_output",
            "filename",
            "subject",
            "sender",
            "payload",
            ".issue56-private",
            ".test-tmp",
        ):
            self.assertNotIn(forbidden, rendered)

    @unittest.skipUnless(
        REAL_PST.is_file()
        and REAL_PRESERVED_WORK_DIR.is_dir()
        and REAL_PARSER_MANIFEST.is_file()
        and shutil.which("lspst") is not None,
        "full PST fixture, parser manifest, preserved snapshot, and lspst are required",
    )
    def test_real_existing_export_builds_parser_backed_rebind_and_stays_blocked(
        self,
    ) -> None:
        root = _paths.fresh_test_dir("issue56-source-complete-rebind-real")
        observation_count_before = len(
            list((REAL_PRESERVED_WORK_DIR / "data" / "ingestion" / "observations").glob("*.json"))
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--pst",
                str(REAL_PST),
                "--preserved-work-dir",
                str(REAL_PRESERVED_WORK_DIR),
                "--output-root",
                str(root / "intermediate"),
                "--snapshot-output",
                str(root / "snapshot.json"),
                "--output",
                str(root / "report.json"),
                "--parser-manifest",
                str(REAL_PARSER_MANIFEST),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(completed.returncode, 2, completed.stderr)
        report = json.loads(completed.stdout)
        snapshot = json.loads((root / "snapshot.json").read_text(encoding="utf-8"))
        persisted_report = json.loads((root / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report, persisted_report)
        self.assertEqual(
            snapshot["snapshot_fingerprint"],
            sha256_json(
                {key: value for key, value in snapshot.items() if key != "snapshot_fingerprint"}
            ),
        )
        self.assertEqual(
            report["source_asset_sha256"],
            "sha256:82dddb25fffd14cd0c5576a0791bc408aab0d15d5eb76be1727e14cff658caaf",
        )
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["counts"]["raw_message_count"], 2793)
        self.assertEqual(report["counts"]["observed_message_count"], 2668)
        self.assertEqual(
            report["counts"]["raw_source_inventory_item_count"],
            7929,
        )
        self.assertEqual(
            report["counts"]["parsed_rebound_message_count"],
            2476,
        )
        self.assertEqual(
            report["counts"]["preserved_unparsed_raw_message_count"],
            183,
        )
        self.assertEqual(
            report["counts"]["unrebound_observation_count"],
            192,
        )
        self.assertEqual(
            report["counts"]["source_inventory_gap_repaired_count"],
            2476,
        )
        self.assertEqual(
            report["counts"]["source_inventory_gap_remaining_count"],
            192,
        )
        self.assertEqual(
            report["counts"]["subject_unique_rebind_count"],
            1594,
        )
        self.assertEqual(
            report["counts"]["subject_sender_day_unique_rebind_count"],
            532,
        )
        self.assertEqual(
            report["counts"]["subject_sender_unique_rebind_count"],
            15,
        )
        self.assertEqual(
            report["counts"]["subject_day_unique_rebind_count"],
            17,
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
            report["counts"]["observed_attachment_count"],
            24,
        )
        self.assertEqual(
            report["counts"]["attachment_inventory_gap_count"],
            24,
        )
        self.assertEqual(
            report["counts"]["attachment_source_inventory_binding_count"],
            0,
        )
        self.assertEqual(report["counts"]["parser_message_count"], 2609)
        self.assertEqual(
            report["counts"]["parser_main_export_record_count"],
            2610,
        )
        self.assertEqual(
            report["counts"]["unsupported_main_record_count"],
            1,
        )
        self.assertEqual(
            report["counts"]["raw_parser_export_record_count_gap"],
            183,
        )
        self.assertEqual(
            report["counts"]["parser_observation_message_binding_count"],
            2476,
        )
        self.assertEqual(
            report["counts"]["parser_source_inventory_observation_binding_count"],
            2476,
        )
        self.assertEqual(
            report["counts"]["raw_parser_observation_message_binding_count"],
            1,
        )
        self.assertEqual(
            report["counts"]["parser_raw_identity_mismatch_count"],
            2608,
        )
        self.assertEqual(
            report["counts"]["unmatched_parser_message_count"],
            133,
        )
        self.assertEqual(
            report["counts"]["unmatched_observation_message_count"],
            192,
        )
        self.assertEqual(
            report["counts"]["parser_embedded_attachment_count"],
            24,
        )
        self.assertEqual(
            report["counts"]["parser_separate_attachment_count"],
            4970,
        )
        self.assertEqual(
            report["counts"]["parser_body_representation_count"],
            325,
        )
        self.assertEqual(
            report["counts"]["parser_attachment_count"],
            4994,
        )
        self.assertEqual(
            report["counts"]["unmatched_parser_attachment_count"],
            4994,
        )
        self.assertEqual(
            report["counts"]["attachment_parent_message_rebound_count"],
            24,
        )
        self.assertEqual(
            report["counts"]["forensic_additional_uniquely_proven_binding_count"],
            0,
        )
        self.assertEqual(
            report["counts"]["forensic_raw_parser_export_record_gap_count"],
            183,
        )
        self.assertEqual(
            report["counts"]["forensic_raw_parser_parsed_message_gap_count"],
            184,
        )
        self.assertEqual(
            report["counts"]["forensic_raw_parser_equal_singleton_raw_count"],
            1554,
        )
        self.assertEqual(
            report["counts"]["forensic_raw_parser_duplicate_equal_raw_count"],
            727,
        )
        self.assertEqual(
            report["counts"]["forensic_raw_parser_cardinality_mismatch_raw_count"],
            376,
        )
        self.assertEqual(
            report["counts"]["forensic_raw_parser_raw_only_coarse_identity_count"],
            135,
        )
        self.assertEqual(
            report["counts"]["forensic_raw_parser_raw_identity_unavailable_count"],
            1,
        )
        self.assertEqual(
            report["counts"]["forensic_raw_parser_equal_singleton_parser_count"],
            1554,
        )
        self.assertEqual(
            report["counts"]["forensic_raw_parser_duplicate_equal_parser_count"],
            727,
        )
        self.assertEqual(
            report["counts"]["forensic_raw_parser_cardinality_mismatch_parser_count"],
            294,
        )
        self.assertEqual(
            report["counts"]["forensic_raw_parser_parser_only_coarse_identity_count"],
            33,
        )
        self.assertEqual(
            report["counts"]["forensic_raw_parser_parser_identity_unavailable_count"],
            1,
        )
        self.assertEqual(
            report["counts"]["forensic_parser_observation_message_id_singleton_parser_count"],
            18,
        )
        self.assertEqual(
            report["counts"][
                "forensic_parser_observation_folder_subject_duplicate_equal_parser_count"
            ],
            4,
        )
        self.assertEqual(
            report["counts"][
                "forensic_parser_observation_folder_subject_cardinality_mismatch_parser_count"
            ],
            4,
        )
        self.assertEqual(
            report["counts"][
                "forensic_parser_observation_identity_component_unavailable_parser_count"
            ],
            7,
        )
        self.assertEqual(
            report["counts"]["forensic_parser_observation_no_shared_signature_parser_count"],
            93,
        )
        self.assertEqual(
            report["counts"]["forensic_parser_observation_message_id_singleton_observation_count"],
            18,
        )
        self.assertEqual(
            report["counts"][
                "forensic_parser_observation_folder_subject_duplicate_equal_observation_count"
            ],
            4,
        )
        self.assertEqual(
            report["counts"][
                "forensic_parser_observation_folder_subject_cardinality_mismatch_observation_count"
            ],
            2,
        )
        self.assertEqual(
            report["counts"][
                "forensic_parser_observation_identity_component_unavailable_observation_count"
            ],
            14,
        )
        self.assertEqual(
            report["counts"]["forensic_parser_observation_no_shared_signature_observation_count"],
            146,
        )
        self.assertEqual(
            report["counts"]["forensic_attachment_ordinal_only_candidate_observation_count"],
            24,
        )
        self.assertEqual(
            report["counts"]["forensic_parser_warning_body_segment_limit_reached_count"],
            773,
        )
        self.assertEqual(
            report["counts"]["forensic_parser_warning_body_segment_redacted_count"],
            2408,
        )
        self.assertEqual(
            report["counts"]["forensic_parser_warning_gap_attribution_count"],
            0,
        )
        self.assertEqual(
            sum(
                count
                for field, count in report["counts"].items()
                if field.startswith("forensic_parser_observation_")
                and field.endswith("_parser_count")
                and field != "forensic_parser_observation_unmatched_parser_count"
            ),
            133,
        )
        self.assertEqual(
            sum(
                count
                for field, count in report["counts"].items()
                if field.startswith("forensic_parser_observation_")
                and field.endswith("_observation_count")
                and field != "forensic_parser_observation_unmatched_observation_count"
            ),
            192,
        )
        self.assertEqual(
            sum(
                report["counts"][field]
                for field in (
                    "forensic_raw_parser_equal_singleton_raw_count",
                    "forensic_raw_parser_duplicate_equal_raw_count",
                    "forensic_raw_parser_cardinality_mismatch_raw_count",
                    "forensic_raw_parser_raw_only_coarse_identity_count",
                    "forensic_raw_parser_raw_identity_unavailable_count",
                )
            ),
            2793,
        )
        self.assertEqual(
            sum(
                report["counts"][field]
                for field in (
                    "forensic_raw_parser_equal_singleton_parser_count",
                    "forensic_raw_parser_duplicate_equal_parser_count",
                    "forensic_raw_parser_cardinality_mismatch_parser_count",
                    "forensic_raw_parser_parser_only_coarse_identity_count",
                    "forensic_raw_parser_parser_identity_unavailable_count",
                )
            ),
            2609,
        )
        self.assertEqual(report["gap_forensics_status"], "blocked")
        self.assertEqual(
            snapshot["gap_forensics"]["existing_artifact_binding_status"],
            "no_additional_unique_binding_proven",
        )
        self.assertEqual(
            snapshot["gap_forensics"]["required_source_capture_capability_status"],
            "missing",
        )
        self.assertEqual(
            report["gap_forensics_fingerprint"],
            snapshot["gap_forensics"]["forensics_fingerprint"],
        )
        self.assertEqual(
            report["parser_export_manifest_fingerprint"],
            json.loads(REAL_PARSER_MANIFEST.read_text(encoding="utf-8"))["manifest_fingerprint"],
        )
        self.assertEqual(
            SourceInventory.from_dict(snapshot["source_inventory"]).to_dict(),
            snapshot["source_inventory"],
        )
        self.assertEqual(
            report["round_trip_status"],
            {
                "observation_manifest": "passed",
                "public_report": "passed",
                "raw_oracle": "passed",
                "source_inventory_snapshot": "passed",
            },
        )
        observation_count_after = len(
            list((REAL_PRESERVED_WORK_DIR / "data" / "ingestion" / "observations").glob("*.json"))
        )
        self.assertEqual(observation_count_before, 27286)
        self.assertEqual(observation_count_after, observation_count_before)
        rendered = completed.stdout.casefold()
        for forbidden in (
            '"subject":',
            '"sender":',
            "folder_label",
            "filename",
            "object_uri",
            "pst-scratch",
        ):
            self.assertNotIn(forbidden, rendered)


if __name__ == "__main__":
    unittest.main()
