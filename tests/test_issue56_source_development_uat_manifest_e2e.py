from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import _paths  # noqa: F401
from formowl_contract import sha256_json
from scripts.issue56_source_development_uat_manifest import (
    CASE_COUNT,
    CLASSIFICATION,
    DEFAULT_BUNDLE_ARTIFACT,
    DEFAULT_RETRIEVAL_REPORT,
    DEFAULT_RETRIEVAL_SNAPSHOT,
    DevelopmentManifestError,
    _canonical_pretty_bytes,
    _payload_fingerprint,
    _persist_immutable_bytes,
    _sha256_bytes,
    author_development_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


class Issue56SourceDevelopmentUatManifestEndToEndTests(unittest.TestCase):
    def test_real_retrieval_ready_source_authors_sealed_development_manifest(
        self,
    ) -> None:
        required = (
            DEFAULT_BUNDLE_ARTIFACT,
            DEFAULT_RETRIEVAL_SNAPSHOT,
            DEFAULT_RETRIEVAL_REPORT,
        )
        if not all(path.exists() for path in required):
            self.skipTest("private retrieval-ready Issue #56 artifacts are unavailable")
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_root = Path(temporary_directory) / "development-uat"
            artifacts = author_development_manifest(
                bundle_artifact_path=DEFAULT_BUNDLE_ARTIFACT,
                retrieval_snapshot_path=DEFAULT_RETRIEVAL_SNAPSHOT,
                retrieval_report_path=DEFAULT_RETRIEVAL_REPORT,
                manifest_output=output_root / "manifest.private.json",
                safe_report_output=output_root / "report.safe.json",
                expected_message_count=2_793,
            )
            self.assertEqual(artifacts.manifest["classification"], CLASSIFICATION)
            self.assertEqual(artifacts.manifest["case_count"], CASE_COUNT)
            self.assertEqual(
                artifacts.manifest["distinct_required_observation_count"],
                2 * CASE_COUNT,
            )
            self.assertGreaterEqual(
                artifacts.manifest["distinct_required_message_occurrence_count"],
                CASE_COUNT,
            )
            self.assertTrue(
                all(
                    len(set(case["source_evidence_binding"]["required_message_occurrence_hashes"]))
                    == 2
                    for case in artifacts.manifest["cases"]
                )
            )
            self.assertEqual(
                artifacts.safe_report["counts"]["positive_graph_required_owner_case_count"],
                CASE_COUNT,
            )
            self.assertEqual(
                artifacts.safe_report["quality_evaluation_status"],
                "not_run",
            )
            self.assertEqual(artifacts.safe_report["blocker_ids"], [])
            self.assertEqual(
                _sha256_bytes(artifacts.manifest_path.read_bytes()),
                artifacts.manifest_sha256,
            )
            self.assertEqual(
                artifacts.manifest["manifest_fingerprint"],
                _payload_fingerprint(
                    artifacts.manifest,
                    "manifest_fingerprint",
                ),
            )
            public_text = json.dumps(
                artifacts.safe_report,
                ensure_ascii=True,
                sort_keys=True,
            )
            for private_key in (
                "query_text",
                "requester_user_id",
                "required_source_observation_ids",
                "mail_evidence_bundle_id",
                "mail_import_session_id",
                "archive_sha256",
                "manifest_path",
            ):
                self.assertNotIn(private_key, public_text)

            _persist_immutable_bytes(
                artifacts.manifest_path,
                artifacts.manifest_path.read_bytes(),
                private=True,
            )

    def test_immutable_writer_and_payload_fingerprint_reject_tamper(self) -> None:
        payload = {
            "artifact_id": "synthetic_development_manifest",
            "classification": CLASSIFICATION,
        }
        payload["manifest_fingerprint"] = _payload_fingerprint(
            payload,
            "manifest_fingerprint",
        )
        encoded = _canonical_pretty_bytes(payload)
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "manifest.private.json"
            _persist_immutable_bytes(path, encoded, private=True)
            self.assertEqual(_sha256_bytes(path.read_bytes()), _sha256_bytes(encoded))
            tampered = deepcopy(payload)
            tampered["classification"] = "holdout"
            with self.assertRaisesRegex(
                DevelopmentManifestError,
                "immutable_output_conflict",
            ):
                _persist_immutable_bytes(
                    path,
                    _canonical_pretty_bytes(tampered),
                    private=True,
                )
            self.assertNotEqual(
                sha256_json(
                    {key: value for key, value in tampered.items() if key != "manifest_fingerprint"}
                ),
                payload["manifest_fingerprint"],
            )

    def test_author_does_not_call_quality_execution(self) -> None:
        source = (ROOT / "scripts" / "issue56_source_development_uat_manifest.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertNotIn("run_simulated_uat", called_names)
        self.assertNotIn("run_simulated_uat", called_attributes)
        self.assertNotIn("_quality_gate_report", called_names)
        self.assertNotIn("_quality_gate_report", called_attributes)
        self.assertNotIn("quality_results", source)

    def test_sha256_seal_is_exact_file_bytes(self) -> None:
        payload = _canonical_pretty_bytes({"development": True, "case_count": 100})
        self.assertEqual(
            _sha256_bytes(payload),
            "sha256:" + hashlib.sha256(payload).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
