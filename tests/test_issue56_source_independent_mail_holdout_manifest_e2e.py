from __future__ import annotations

import ast
import json
from pathlib import Path
import tempfile
import unittest

import _paths  # noqa: F401
from scripts.issue56_source_development_uat_manifest import (
    DEFAULT_BUNDLE_ARTIFACT,
    DEFAULT_RETRIEVAL_SNAPSHOT,
    _payload_fingerprint,
    _sha256_bytes,
)
from scripts.issue56_source_independent_mail_holdout_manifest import (
    CLASSIFICATION,
    DEFAULT_DEVELOPMENT_MANIFEST,
    DEFAULT_DEVELOPMENT_SAFE_REPORT,
    HOLDOUT_CASE_COUNT,
    HoldoutManifestError,
    _validated_development_exclusion_registry,
    author_independent_mail_holdout_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


class Issue56IndependentMailHoldoutManifestEndToEndTests(unittest.TestCase):
    def test_real_source_authors_sealed_disjoint_unexecuted_holdout(self) -> None:
        required = (
            DEFAULT_BUNDLE_ARTIFACT,
            DEFAULT_RETRIEVAL_SNAPSHOT,
            DEFAULT_DEVELOPMENT_MANIFEST,
            DEFAULT_DEVELOPMENT_SAFE_REPORT,
        )
        if not all(path.exists() for path in required):
            self.skipTest("private Issue #56 source/development artifacts unavailable")
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_root = Path(temporary_directory) / "holdout"
            artifacts = author_independent_mail_holdout_manifest(
                bundle_artifact_path=DEFAULT_BUNDLE_ARTIFACT,
                retrieval_snapshot_path=DEFAULT_RETRIEVAL_SNAPSHOT,
                development_manifest_path=DEFAULT_DEVELOPMENT_MANIFEST,
                development_safe_report_path=DEFAULT_DEVELOPMENT_SAFE_REPORT,
                manifest_output=output_root / "manifest.private.json",
                safe_report_output=output_root / "report.safe.json",
                expected_message_count=2_793,
            )
            manifest = artifacts.manifest
            report = artifacts.safe_report
            self.assertEqual(manifest["classification"], CLASSIFICATION)
            self.assertEqual(manifest["case_count"], HOLDOUT_CASE_COUNT)
            self.assertEqual(manifest["execution_status"], "not_run")
            self.assertEqual(manifest["quality_result_status"], "not_read")
            self.assertTrue(manifest["seal_required_before_execution"])
            self.assertTrue(manifest["author_evaluator_boundary"]["roles_are_distinct"])
            self.assertFalse(manifest["author_evaluator_boundary"]["evaluator_invoked"])
            self.assertEqual(
                manifest["disjointness"]["development_holdout_observation_overlap_count"],
                0,
            )
            self.assertEqual(
                manifest["disjointness"]["development_holdout_message_overlap_count"],
                0,
            )
            self.assertEqual(
                manifest["disjointness"]["development_holdout_thread_overlap_count"],
                0,
            )
            self.assertEqual(
                manifest["disjointness"]["holdout_observation_count"],
                2 * HOLDOUT_CASE_COUNT,
            )
            self.assertEqual(
                manifest["disjointness"]["holdout_message_count"],
                2 * HOLDOUT_CASE_COUNT,
            )
            self.assertEqual(report["seal_before_execution_status"], "passed")
            self.assertEqual(report["execution_status"], "not_run")
            self.assertEqual(report["quality_result_status"], "not_read")
            self.assertEqual(report["blocker_ids"], [])
            self.assertEqual(
                _sha256_bytes(artifacts.manifest_path.read_bytes()),
                artifacts.manifest_sha256,
            )
            self.assertEqual(
                manifest["manifest_fingerprint"],
                _payload_fingerprint(manifest, "manifest_fingerprint"),
            )
            public_text = json.dumps(report, ensure_ascii=True, sort_keys=True)
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

    def test_development_registry_seal_is_fail_closed(self) -> None:
        if not (DEFAULT_DEVELOPMENT_MANIFEST.exists() and DEFAULT_DEVELOPMENT_SAFE_REPORT.exists()):
            self.skipTest("sealed development exclusion registry unavailable")
        manifest_bytes = DEFAULT_DEVELOPMENT_MANIFEST.read_bytes()
        manifest = json.loads(manifest_bytes)
        safe_report = json.loads(DEFAULT_DEVELOPMENT_SAFE_REPORT.read_bytes())
        observation_ids, registry_fingerprint = _validated_development_exclusion_registry(
            manifest=manifest,
            manifest_bytes=manifest_bytes,
            safe_report=safe_report,
        )
        self.assertEqual(len(observation_ids), 200)
        self.assertRegex(registry_fingerprint, r"^sha256:[0-9a-f]{64}$")
        tampered_report = dict(safe_report)
        tampered_report["fingerprints"] = dict(safe_report["fingerprints"])
        tampered_report["fingerprints"]["manifest_sha256"] = "sha256:" + ("0" * 64)
        with self.assertRaisesRegex(
            HoldoutManifestError,
            "development_exclusion_registry_seal_mismatch",
        ):
            _validated_development_exclusion_registry(
                manifest=manifest,
                manifest_bytes=manifest_bytes,
                safe_report=tampered_report,
            )

    def test_author_has_no_evaluator_or_quality_execution_dependency(self) -> None:
        source = (
            ROOT / "scripts" / "issue56_source_independent_mail_holdout_manifest.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
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
        self.assertNotIn("scripts.issue56_simulated_uat", imported_modules)
        for forbidden in (
            "run_simulated_uat",
            "_quality_gate_report",
            "run_holdout",
            "evaluate_holdout",
        ):
            self.assertNotIn(forbidden, called_names)
            self.assertNotIn(forbidden, called_attributes)
        self.assertNotIn("development-quality", source)


if __name__ == "__main__":
    unittest.main()
