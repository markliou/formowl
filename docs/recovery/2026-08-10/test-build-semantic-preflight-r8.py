from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "build-semantic-preflight-r8.py"
SPEC = importlib.util.spec_from_file_location("build_semantic_preflight_r8", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
preflight = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = preflight
SPEC.loader.exec_module(preflight)


class SemanticPreflightR8Tests(unittest.TestCase):
    def _report(self) -> dict[str, object]:
        return {
            "artifact_type": "formowl_aggregate_semantic_acceptance_report_v1",
            "status": "passed",
            "release_decision": "AGREE",
            "expected_distinct_projection_count": 77,
            "observed_distinct_projection_count": 77,
            "count_match": True,
            "expected_fingerprint": preflight.EXPECTED_FINGERPRINT,
            "observed_fingerprint": preflight.EXPECTED_FINGERPRINT,
            "fingerprint_match": True,
            "failure_categories": [],
            "validation_status": {
                key: True for key in preflight.EXPECTED_VALIDATION_KEYS
            },
            "implementation_source_commitments": {
                "source_fingerprint": "sha256:" + "a" * 64
            },
        }

    def _paths(self, root: Path) -> tuple[Path, Path]:
        report = root / "acceptance.json"
        binding = root / "binding.json"
        report.write_text(json.dumps(self._report()), encoding="utf-8")
        binding.write_text('{"private":"redacted"}\n', encoding="utf-8")
        return report, binding

    def test_exact_acceptance_builds_deployment_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report, binding = self._paths(Path(temporary))
            result = preflight.build_preflight(
                acceptance_report=report,
                binding=binding,
            )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["retrieval_path"], "mail_authorized_structured_set")
        self.assertEqual(result["claim_state"], "CANDIDATE_MATCHES")
        self.assertFalse(result["canonical_kg"])
        self.assertEqual(result["citation_count"], 0)
        self.assertEqual(result["source_count"], 0)
        self.assertEqual(result["observed_distinct_projection_count"], 77)
        self.assertEqual(result["observed_fingerprint"], preflight.EXPECTED_FINGERPRINT)
        self.assertRegex(result["acceptance_report_sha256"], r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(result["candidate_binding_sha256"], r"^sha256:[0-9a-f]{64}$")

    def test_incomplete_validation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report, binding = self._paths(root)
            payload = self._report()
            payload["validation_status"]["every_shard_bound"] = False
            report.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                preflight.PreflightFailure,
                "acceptance is incomplete",
            ):
                preflight.build_preflight(
                    acceptance_report=report,
                    binding=binding,
                )

    def test_count_or_fingerprint_mismatch_is_rejected(self) -> None:
        for field, value in (
            ("observed_distinct_projection_count", 76),
            ("observed_fingerprint", "sha256:" + "0" * 64),
            ("failure_categories", ["projection_count_mismatch"]),
        ):
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    report, binding = self._paths(root)
                    payload = self._report()
                    payload[field] = value
                    report.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaises(preflight.PreflightFailure):
                        preflight.build_preflight(
                            acceptance_report=report,
                            binding=binding,
                        )

    def test_symlink_binding_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report, binding = self._paths(root)
            symlink = root / "binding-link.json"
            symlink.symlink_to(binding)
            with self.assertRaisesRegex(
                preflight.PreflightFailure,
                "required input is unavailable",
            ):
                preflight.build_preflight(
                    acceptance_report=report,
                    binding=symlink,
                )


if __name__ == "__main__":
    unittest.main()
