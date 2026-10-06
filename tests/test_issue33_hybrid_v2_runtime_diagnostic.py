from __future__ import annotations

from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, Observation, sha256_json
from formowl_core.tokenization import (
    build_ascii_identifier_regex_tokenizer_profile,
    build_frozen_jieba_sentencepiece_tokenizer_profile,
)
from formowl_mail.bundle import build_mail_evidence_bundle
from formowl_mail.query import (
    MailEvidenceQueryGateway,
    build_existing_observation_snippet_index,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "issue33_hybrid_v2_poc.json"


def _load_diagnostic_runner() -> object:
    spec = importlib.util.spec_from_file_location(
        "issue33_hybrid_v2_runtime_poc",
        ROOT / "scripts" / "issue33_hybrid_v2_runtime_poc.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("issue33 diagnostic runner is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DIAGNOSTIC_RUNNER = _load_diagnostic_runner()


class Issue33HybridV2RuntimeDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.observations = [Observation.from_dict(item) for item in cls.fixture["observations"]]
        cls.bundle = build_mail_evidence_bundle(
            cls.observations,
            workspace_id=cls.fixture["workspace_id"],
            owner_user_id=cls.fixture["owner_user_id"],
            source_asset_id=cls.fixture["source_asset_id"],
            archive_sha256=cls.fixture["archive_sha256"],
            upload_session_id=cls.fixture["upload_session_id"],
            parser_name="existing_observation_bridge_no_parser",
            parser_version="issue33_diagnostic_test_v1",
            created_at=cls.fixture["created_at"],
            started_at=cls.fixture["created_at"],
            completed_at=cls.fixture["created_at"],
        )

    def test_profile_fingerprint_mismatch_fails_closed(self) -> None:
        profile = build_ascii_identifier_regex_tokenizer_profile()
        index, _manifest = build_existing_observation_snippet_index(
            self.observations,
            bundle=self.bundle,
            tokenizer_profile=profile,
        )
        mismatched_profile = replace(
            profile,
            profile_fingerprint="sha256:" + ("0" * 64),
        )

        with self.assertRaisesRegex(
            ContractValidationError,
            "^mail evidence tokenizer profile mismatch$",
        ):
            MailEvidenceQueryGateway(
                [self.bundle],
                tokenizer_profile=mismatched_profile,
                snippet_index_by_bundle_id={
                    self.bundle.mail_evidence_bundle_id: index,
                },
            )

    def test_existing_observation_index_manifest_is_deterministic_and_source_free(
        self,
    ) -> None:
        profile = build_ascii_identifier_regex_tokenizer_profile()
        first_index, first_manifest = build_existing_observation_snippet_index(
            self.observations,
            bundle=self.bundle,
            tokenizer_profile=profile,
        )
        second_index, second_manifest = build_existing_observation_snippet_index(
            self.observations,
            bundle=self.bundle,
            tokenizer_profile=profile,
        )
        first_payload = first_manifest.to_safe_dict()
        second_payload = second_manifest.to_safe_dict()

        self.assertEqual(first_payload, second_payload)
        self.assertEqual(first_index.index_fingerprint, second_index.index_fingerprint)
        self.assertEqual(sha256_json(first_payload), sha256_json(second_payload))
        self.assertEqual(first_payload["input_kind"], "existing_observations_only")
        self.assertEqual(
            first_payload["query_profile_fingerprint"],
            profile.profile_fingerprint,
        )
        self.assertEqual(
            first_payload["evidence_profile_fingerprint"],
            profile.profile_fingerprint,
        )
        self.assertEqual(first_payload["raw_pst_read_count"], 0)
        self.assertEqual(first_payload["pst_parser_invocation_count"], 0)
        self.assertEqual(first_payload["new_extractor_run_count"], 0)
        self.assertEqual(first_payload["missing_lineage_count"], 0)

    def test_protected_identifier_near_miss_returns_no_evidence(self) -> None:
        near_miss_case = next(
            case
            for case in self.fixture["cases"]
            if case["case_id"] == "protected_identifier_near_miss"
        )
        with tempfile.TemporaryDirectory(prefix="formowl-issue33-test-") as temp_dir:
            model_path, model_sha256 = DIAGNOSTIC_RUNNER._train_safe_calibration_model(
                Path(temp_dir)
            )
            profile = build_frozen_jieba_sentencepiece_tokenizer_profile(
                model_path=model_path,
                model_sha256=model_sha256,
            )
            index, _manifest = build_existing_observation_snippet_index(
                self.observations,
                bundle=self.bundle,
                tokenizer_profile=profile,
            )
            gateway = MailEvidenceQueryGateway(
                [self.bundle],
                tokenizer_profile=profile,
                snippet_index_by_bundle_id={
                    self.bundle.mail_evidence_bundle_id: index,
                },
            )
            result = gateway.query_mail_evidence(
                query_text=near_miss_case["query_text"],
                requester_user_id=self.fixture["owner_user_id"],
                workspace_id=self.fixture["workspace_id"],
                session_id="session_issue33_test",
                mail_evidence_bundle_id=self.bundle.mail_evidence_bundle_id,
                now=self.fixture["created_at"],
            )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.evidence_snippets, [])
        self.assertEqual(result.citations, [])
        self.assertEqual(result.warnings, ["no_visible_mail_evidence_matched"])

    def test_runner_reports_safe_before_after_diagnostic_for_three_replicates(
        self,
    ) -> None:
        report = DIAGNOSTIC_RUNNER.run_diagnostic(
            fixture_path=FIXTURE_PATH,
            replicates=3,
        )
        serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)

        self.assertEqual(
            report["claim_state"],
            "query_evidence_extractive_answer_diagnostic_only",
        )
        self.assertTrue(report["final_answer_generated"])
        self.assertTrue(report["real_query_to_evidence_runtime_path_executed"])
        self.assertFalse(report["real_source_methodology_evidence"])
        self.assertFalse(report["methodology_ready"])
        self.assertEqual(report["authority"]["status"], "blocked")
        self.assertTrue(report["before_after"]["improvement_observed"])
        self.assertEqual(
            report["before_after"]["conclusion"],
            "diagnostic_root_cause_improvement_observed",
        )
        self.assertGreater(
            report["before_after"]["required_evidence_resolved_delta"],
            0,
        )
        self.assertLessEqual(
            report["before_after"]["no_answer_false_match_delta"],
            0,
        )
        self.assertEqual(
            report["before"]["inspection_summary"][
                "ontology_hard_gate_false_reject_count"
            ],
            1,
        )
        self.assertEqual(
            report["after"]["inspection_summary"][
                "ontology_hard_gate_false_reject_count"
            ],
            0,
        )
        self.assertGreater(
            report["after"]["inspection_summary"]["final_answer_generated_count"],
            0,
        )
        self.assertEqual(
            report["after"]["inspection_summary"]["unsupported_answer_count"],
            0,
        )
        self.assertEqual(
            report["after"]["inspection_summary"]["no_answer_false_match_count"],
            0,
        )
        no_answer_cases = [
            case
            for case in report["after"]["case_inspection"]
            if case["expected_outcome"] == "no_match"
        ]
        self.assertTrue(no_answer_cases)
        self.assertTrue(
            all(case["answer_outcome"] == "abstained" for case in no_answer_cases)
        )
        self.assertTrue(
            all(
                case["candidate_graph_trace"]["graph_kind"]
                == "runtime_token_anchor_candidate_graph_v1"
                for case in report["after"]["case_inspection"]
            )
        )
        for arm_name in ("before", "after"):
            arm = report[arm_name]
            self.assertTrue(arm["query_evidence_profile_fingerprint_equal"])
            self.assertEqual(arm["cold_latency_ms"]["sample_count"], 3)
            self.assertEqual(arm["warm_latency_ms"]["sample_count"], 3)
            self.assertEqual(
                arm["index_build_manifest"]["input_kind"],
                "existing_observations_only",
            )
            self.assertEqual(arm["index_build_manifest"]["raw_pst_read_count"], 0)
            self.assertEqual(
                arm["index_build_manifest"]["pst_parser_invocation_count"],
                0,
            )
            self.assertEqual(
                arm["index_build_manifest"]["new_extractor_run_count"],
                0,
            )
        for case in self.fixture["cases"]:
            self.assertNotIn(case["query_text"], serialized)
        for observation in self.fixture["observations"]:
            self.assertNotIn(observation["text"], serialized)


if __name__ == "__main__":
    unittest.main()
