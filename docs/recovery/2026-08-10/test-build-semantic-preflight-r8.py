from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "build-semantic-preflight-r8.py"
CORRECTED_CANONICAL_SEMANTIC_REQUEST_SHA256 = (
    "sha256:20f30eb32c7525b9bedaf68b358fa0140c43cc6a77f2af03cec124a5e1dc012b"
)
STALE_SEMANTIC_REQUEST_SHA256 = (
    "sha256:dff10d0427201c7199874fdf51c23d27bd6dd31485be20c39eddb18be5948222"
)
SPEC = importlib.util.spec_from_file_location("build_semantic_preflight_r8", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
preflight = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = preflight
SPEC.loader.exec_module(preflight)


class SemanticPreflightR8Tests(unittest.TestCase):
    def test_semantic_request_contract_hash_is_corrected_canonical_value(self) -> None:
        self.assertEqual(
            preflight.CANONICAL_SEMANTIC_REQUEST_SHA256,
            CORRECTED_CANONICAL_SEMANTIC_REQUEST_SHA256,
        )

    def _candidate_exact_report(self, binding_sha256: str) -> dict[str, object]:
        commitments = {
            key: "sha256:" + format(index + 1, "064x")
            for index, key in enumerate(sorted(preflight.CANDIDATE_EXACT_REQUIRED_COMMITMENTS))
        }
        commitments["reviewed_structural_binding_sha256"] = binding_sha256
        execution_bindings = {
            "candidate_union_execution_handoff_sha256": commitments[
                "candidate_union_execution_handoff_sha256"
            ],
            "frozen_projection_fingerprint": preflight.EXPECTED_FINGERPRINT,
            "runtime_projection_fingerprint": preflight.EXPECTED_FINGERPRINT,
            "oracle_file_sha256": commitments["private_oracle_sha256"],
            "semantic_request_sha256": preflight.CANONICAL_SEMANTIC_REQUEST_SHA256,
        }
        return {
            "artifact_type": preflight.CANDIDATE_EXACT_REPORT_ARTIFACT_TYPE,
            "status": "passed",
            "release_decision": preflight.CANDIDATE_EXACT_RELEASE_DECISION,
            "expected_distinct_projection_count": 77,
            "observed_distinct_projection_count": 77,
            "count_match": True,
            "expected_fingerprint": preflight.EXPECTED_FINGERPRINT,
            "observed_fingerprint": preflight.EXPECTED_FINGERPRINT,
            "fingerprint_match": True,
            "oracle_intersection_count": 77,
            "oracle_missing_count": 0,
            "oracle_unexpected_count": 0,
            "retrieval_path": "mail_authorized_structured_set",
            "claim_state": "CANDIDATE_MATCHES",
            "canonical_kg": False,
            "citation_count": 0,
            "source_count": 0,
            "deterministic_repeat_match": True,
            "runtime_projection_matches_handoff": True,
            "failure_categories": [],
            "validation_status": {key: True for key in preflight.CANDIDATE_EXACT_VALIDATION_KEYS},
            "implementation_source_commitments": commitments,
            "execution_bindings": execution_bindings,
            "disclaimed_semantics": dict(preflight.CANDIDATE_DISCLAIMERS),
            "diagnostic_only": True,
        }

    def _paths(self, root: Path) -> tuple[Path, Path]:
        report = root / "acceptance.json"
        binding = root / "binding.json"
        binding.write_text('{"private":"redacted"}\n', encoding="utf-8")
        report.write_text(
            json.dumps(self._candidate_exact_report(preflight._sha256(binding))),
            encoding="utf-8",
        )
        return report, binding

    def _payload(self, report: Path) -> dict[str, object]:
        return json.loads(report.read_text(encoding="utf-8"))

    def test_exact_candidate_acceptance_builds_deployment_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report, binding = self._paths(Path(temporary))
            result = preflight.build_preflight(
                acceptance_report=report,
                binding=binding,
            )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(
            result["candidate_exact_report_artifact_type"],
            preflight.CANDIDATE_EXACT_REPORT_ARTIFACT_TYPE,
        )
        self.assertEqual(
            result["candidate_exact_release_decision"],
            preflight.CANDIDATE_EXACT_RELEASE_DECISION,
        )
        self.assertEqual(result["retrieval_path"], "mail_authorized_structured_set")
        self.assertEqual(result["claim_state"], "CANDIDATE_MATCHES")
        self.assertFalse(result["canonical_kg"])
        self.assertEqual(result["citation_count"], 0)
        self.assertEqual(result["source_count"], 0)
        self.assertEqual(result["observed_distinct_projection_count"], 77)
        self.assertEqual(result["observed_fingerprint"], preflight.EXPECTED_FINGERPRINT)
        self.assertEqual(result["oracle_intersection_count"], 77)
        self.assertEqual(result["oracle_missing_count"], 0)
        self.assertEqual(result["oracle_unexpected_count"], 0)
        self.assertTrue(result["deterministic_repeat_match"])
        self.assertTrue(result["runtime_projection_matches_handoff"])
        self.assertEqual(
            set(result["candidate_exact_validation_status"]),
            preflight.CANDIDATE_EXACT_VALIDATION_KEYS,
        )
        self.assertEqual(
            set(result["implementation_source_commitments"]),
            preflight.CANDIDATE_EXACT_REQUIRED_COMMITMENTS,
        )
        self.assertEqual(
            set(result["execution_bindings"]),
            preflight.CANDIDATE_EXACT_EXECUTION_BINDING_KEYS,
        )
        self.assertEqual(
            result["execution_bindings"]["semantic_request_sha256"],
            preflight.CANONICAL_SEMANTIC_REQUEST_SHA256,
        )
        self.assertEqual(
            result["candidate_disclaimed_semantics"],
            preflight.CANDIDATE_DISCLAIMERS,
        )
        self.assertRegex(result["acceptance_report_sha256"], r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(result["candidate_binding_sha256"], r"^sha256:[0-9a-f]{64}$")

    def test_legacy_aggregate_report_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report, binding = self._paths(root)
            report.write_text(
                json.dumps(
                    {
                        "artifact_type": "formowl_aggregate_semantic_acceptance_report_v1",
                        "status": "passed",
                        "release_decision": "AGREE",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                preflight.PreflightFailure,
                "candidate exact acceptance is incomplete",
            ):
                preflight.build_preflight(
                    acceptance_report=report,
                    binding=binding,
                )

    def test_partial_or_mismatched_candidate_exact_reports_are_rejected(self) -> None:
        def remove_validation_key(payload: dict[str, object]) -> None:
            payload["validation_status"].pop("oracle_loaded_after_package_runtime_freeze")

        def runtime_handoff_false(payload: dict[str, object]) -> None:
            payload["runtime_projection_matches_handoff"] = False

        def wrong_binding(payload: dict[str, object]) -> None:
            payload["implementation_source_commitments"]["reviewed_structural_binding_sha256"] = (
                "sha256:" + "0" * 64
            )

        def missing_candidate_plan(payload: dict[str, object]) -> None:
            payload["implementation_source_commitments"].pop("candidate_union_plan_sha256")

        def projection_mismatch(payload: dict[str, object]) -> None:
            payload["execution_bindings"]["runtime_projection_fingerprint"] = "sha256:" + "0" * 64

        def oracle_order_false(payload: dict[str, object]) -> None:
            payload["validation_status"]["oracle_loaded_after_package_runtime_freeze"] = False

        def disclaimer_weakened(payload: dict[str, object]) -> None:
            payload["disclaimed_semantics"]["source_complete"] = True

        def semantic_request_mismatch(payload: dict[str, object]) -> None:
            payload["execution_bindings"]["semantic_request_sha256"] = "sha256:" + "0" * 64

        def stale_semantic_request(payload: dict[str, object]) -> None:
            payload["execution_bindings"]["semantic_request_sha256"] = STALE_SEMANTIC_REQUEST_SHA256

        cases = (
            ("partial_validation", remove_validation_key),
            ("runtime_handoff", runtime_handoff_false),
            ("binding", wrong_binding),
            ("candidate_plan", missing_candidate_plan),
            ("projection", projection_mismatch),
            ("oracle_order", oracle_order_false),
            ("disclaimer", disclaimer_weakened),
            ("semantic_request", semantic_request_mismatch),
            ("stale_semantic_request", stale_semantic_request),
        )
        for name, mutate in cases:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    report, binding = self._paths(root)
                    payload = self._payload(report)
                    mutate(payload)
                    report.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaisesRegex(
                        preflight.PreflightFailure,
                        "candidate exact acceptance is incomplete",
                    ):
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
