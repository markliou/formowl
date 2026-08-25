from __future__ import annotations

from dataclasses import replace
import inspect
import json
import math
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from typing import Iterator, Mapping, Sequence

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, Observation, sha256_json
from formowl_core import (
    DenseEmbeddingUnavailableError,
    ISSUE56_TARGET_DENSE_ENCODER_ID,
    ISSUE56_TARGET_DENSE_MODEL_ID,
    ISSUE56_TARGET_DENSE_MODEL_REVISION,
    ISSUE56_TARGET_DENSE_PROFILE_FINGERPRINT,
    Issue56TargetRuntimeComponents,
    SentenceTransformerDenseEncoder,
    build_issue56_execution_component_binding,
    issue56_target_dense_embedding_profile,
    load_issue56_target_mail_tokenizer_profile,
)
from formowl_mail import (
    build_authorized_hybrid_mail_index,
    run_authorized_hybrid_mail_query,
)
from formowl_mail import hybrid as hybrid_module
from scripts.issue56_hybrid_v2_poc import (
    REQUESTER_USER_ID,
    WORKSPACE_ID,
    build_poc_inputs,
)
from scripts import issue56_hybrid_v2_poc as hybrid_poc_module

ROOT = Path(__file__).resolve().parents[1]


class Issue56HybridRagEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract_model = _ContractOnlySentenceTransformerModel()
        cls.runtime = _contract_only_runtime(cls.contract_model)
        (
            cls.authorized_observations,
            cls.authorized_bundle,
            cls.denied_observations,
            cls.denied_bundle,
        ) = build_poc_inputs()

    def test_normal_api_has_no_dense_or_tokenizer_injection_surface(self) -> None:
        build_parameters = inspect.signature(build_authorized_hybrid_mail_index).parameters
        query_parameters = inspect.signature(run_authorized_hybrid_mail_query).parameters
        for forbidden in ("dense_encoder", "tokenizer_profile"):
            self.assertNotIn(forbidden, build_parameters)
            self.assertNotIn(forbidden, query_parameters)

    def test_new_runtime_helpers_are_module_bound(self) -> None:
        for helper_name in (
            "_deterministic_high_idf_proof_slots",
            "_minimal_candidate_proof_citations",
            "_select_coherent_bundle_results",
        ):
            self.assertTrue(callable(getattr(hybrid_module, helper_name)))
            self.assertNotIn(
                helper_name,
                inspect.getclosurevars(hybrid_module.AuthorizedHybridMailIndex.query).unbound,
            )

    def test_direct_lookup_uses_query_and_passage_e5_interfaces(self) -> None:
        self.contract_model.calls.clear()
        index = self._combined_index()
        result = index.query(
            query_text="PO470002002 交期",
            query_class="evidence_lookup",
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.dense_encoder_status, "pinned_real_e5")
        self.assertEqual(result.dense_encoder_id, ISSUE56_TARGET_DENSE_ENCODER_ID)
        self.assertEqual(
            result.dense_profile_fingerprint,
            ISSUE56_TARGET_DENSE_PROFILE_FINGERPRINT,
        )
        self.assertEqual(result.dense_model_id, ISSUE56_TARGET_DENSE_MODEL_ID)
        self.assertEqual(
            result.dense_model_revision,
            ISSUE56_TARGET_DENSE_MODEL_REVISION,
        )
        self.assertEqual(result.authorized_bundle_count, 1)
        self.assertEqual(result.denied_bundle_count, 1)
        self.assertGreater(result.materialized_candidate_count, 0)
        self.assertEqual(result.result_bundle_count, 1)
        self.assertTrue(any(call.startswith("passage: ") for call in self.contract_model.calls))
        self.assertTrue(any(call.startswith("query: ") for call in self.contract_model.calls))
        bundle_score = result.results[0]
        self.assertGreater(bundle_score.bm25_score, 0.0)
        self.assertGreater(bundle_score.dense_score, 0.0)
        self.assertGreater(bundle_score.fusion_score, 0.0)
        self.assertGreater(bundle_score.rerank_score, bundle_score.fusion_score)
        self.assertEqual(len(result.answer_citation_hashes), 1)
        self.assertTrue(
            set(result.answer_citation_hashes).issubset(
                {
                    candidate.source_observation_hash
                    for candidate in result.admitted_candidate_scores
                }
            )
        )

    def test_cross_message_join_and_protected_near_miss(self) -> None:
        index = self._combined_index()
        cross_message = index.query(
            query_text="PO470002002 交期 產地",
            query_class="evidence_lookup",
        )
        near_miss = index.query(
            query_text="PO470002003 交期",
            query_class="evidence_lookup",
        )

        self.assertEqual(cross_message.status, "ok")
        self.assertEqual(cross_message.result_bundle_count, 1)
        self.assertEqual(cross_message.results[0].unique_message_count, 2)
        self.assertGreaterEqual(
            sum(bundle_score.evidence_count for bundle_score in cross_message.results),
            2,
        )
        self.assertEqual(len(cross_message.answer_citation_hashes), 1)
        self.assertEqual(
            len(cross_message.answer_citation_hashes),
            len(set(cross_message.answer_citation_hashes)),
        )
        self.assertEqual(near_miss.status, "no_answer")
        self.assertEqual(near_miss.results, ())
        self.assertEqual(near_miss.answer_citation_hashes, ())

    def test_thread_coherent_union_covers_identifier_and_high_idf_concept(self) -> None:
        observations = hybrid_poc_module._mail_observations(
            namespace="union_coverage",
            messages=(
                ("識別資訊", "PO470002002"),
                ("時程資訊", "交期 2026-09-30"),
            ),
        )
        bundle = hybrid_poc_module._build_bundle(
            observations=observations,
            namespace="union_coverage",
            owner_user_id=REQUESTER_USER_ID,
        )
        with self._runtime_patch():
            index = build_authorized_hybrid_mail_index(
                observations_by_bundle_id={
                    bundle.mail_evidence_bundle_id: observations,
                },
                bundles=(bundle,),
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=WORKSPACE_ID,
            )

        result = index.query(
            query_text="PO470002002 交期",
            query_class="evidence_lookup",
        )
        near_miss = index.query(
            query_text="PO470002003 交期",
            query_class="evidence_lookup",
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.result_bundle_count, 1)
        self.assertEqual(result.results[0].unique_message_count, 2)
        self.assertEqual(len(result.answer_citation_hashes), 2)
        authorized_body_hashes = {
            sha256_json(observation.to_dict())
            for observation in observations
            if observation.observation_type == "email_body_segment"
        }
        self.assertTrue(
            set(result.answer_citation_hashes).issubset(
                authorized_body_hashes,
            )
        )
        self.assertEqual(near_miss.status, "no_answer")
        self.assertEqual(near_miss.answer_citation_hashes, ())

    def test_permission_filter_precedes_runtime_and_observation_materialization(
        self,
    ) -> None:
        tracking = _TrackingObservationMap(
            {
                self.authorized_bundle.mail_evidence_bundle_id: (self.authorized_observations),
                self.denied_bundle.mail_evidence_bundle_id: self.denied_observations,
            }
        )
        with self._runtime_patch():
            index = build_authorized_hybrid_mail_index(
                observations_by_bundle_id=tracking,
                bundles=(self.authorized_bundle, self.denied_bundle),
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=WORKSPACE_ID,
            )
        self.assertEqual(index.authorized_bundle_count, 1)
        self.assertIn(
            self.authorized_bundle.mail_evidence_bundle_id,
            tracking.value_accesses,
        )
        self.assertNotIn(
            self.denied_bundle.mail_evidence_bundle_id,
            tracking.value_accesses,
        )

        tracking.value_accesses.clear()
        with self._runtime_patch():
            denied = run_authorized_hybrid_mail_query(
                observations_by_bundle_id=tracking,
                bundles=(self.authorized_bundle, self.denied_bundle),
                query_text="ZX900001999 付款條件",
                query_class="evidence_lookup",
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=WORKSPACE_ID,
                mail_evidence_bundle_id=(self.denied_bundle.mail_evidence_bundle_id),
            )
        self.assertEqual(denied.status, "permission_denied")
        self.assertEqual(denied.materialized_candidate_count, 0)
        self.assertNotIn(
            self.denied_bundle.mail_evidence_bundle_id,
            tracking.value_accesses,
        )

        tracking.value_accesses.clear()
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            side_effect=DenseEmbeddingUnavailableError("multilingual_model_snapshot_unavailable"),
        ):
            with self.assertRaises(DenseEmbeddingUnavailableError):
                build_authorized_hybrid_mail_index(
                    observations_by_bundle_id=tracking,
                    bundles=(self.authorized_bundle, self.denied_bundle),
                    requester_user_id=REQUESTER_USER_ID,
                    workspace_id=WORKSPACE_ID,
                )
        self.assertEqual(tracking.value_accesses, [])

    def test_denied_evidence_cannot_change_authorized_index_or_scores(self) -> None:
        with self._runtime_patch():
            authorized_only = build_authorized_hybrid_mail_index(
                observations_by_bundle_id={
                    self.authorized_bundle.mail_evidence_bundle_id: (self.authorized_observations)
                },
                bundles=(self.authorized_bundle,),
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=WORKSPACE_ID,
            )
        combined = self._combined_index()
        self.assertEqual(
            authorized_only.index_fingerprint,
            combined.index_fingerprint,
        )
        authorized_result = authorized_only.query(
            query_text="PO470002002 交期",
            query_class="evidence_lookup",
        )
        combined_result = combined.query(
            query_text="PO470002002 交期",
            query_class="evidence_lookup",
        )
        self.assertEqual(
            authorized_result.to_safe_dict()["results"],
            combined_result.to_safe_dict()["results"],
        )

    def test_profile_index_and_execution_component_mismatch_fail_closed(self) -> None:
        with self._runtime_patch():
            with self.assertRaisesRegex(
                ContractValidationError,
                "tokenizer profile mismatch",
            ):
                build_authorized_hybrid_mail_index(
                    observations_by_bundle_id={
                        self.authorized_bundle.mail_evidence_bundle_id: (
                            self.authorized_observations
                        )
                    },
                    bundles=(self.authorized_bundle,),
                    requester_user_id=REQUESTER_USER_ID,
                    workspace_id=WORKSPACE_ID,
                    expected_profile_fingerprint="sha256:" + "f" * 64,
                )

        mismatched = replace(
            self._combined_index(),
            execution_component_fingerprint="sha256:" + "f" * 64,
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "execution component mismatch",
        ):
            mismatched.query(
                query_text="PO470002002 交期",
                query_class="evidence_lookup",
            )

    def test_exact_set_route_never_infers_from_top_k(self) -> None:
        with self._runtime_patch():
            result = run_authorized_hybrid_mail_query(
                observations_by_bundle_id={
                    self.authorized_bundle.mail_evidence_bundle_id: (self.authorized_observations)
                },
                bundles=(self.authorized_bundle,),
                query_text="列出全部採購單並計數",
                query_class="exact_set_or_inventory",
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=WORKSPACE_ID,
            )
        self.assertEqual(result.status, "route_blocked")
        self.assertEqual(result.exact_executor_status, "required_but_unavailable")
        self.assertEqual(result.materialized_candidate_count, 0)

    def test_normal_script_is_real_e5_or_explicit_safe_blocker(self) -> None:
        script_source = (ROOT / "scripts" / "issue56_hybrid_v2_poc.py").read_text()
        self.assertNotIn("DeterministicDiagnosticDenseEncoder", script_source)
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/issue56_hybrid_v2_poc.py",
                "--allow-blocked",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        report = json.loads(completed.stdout)
        serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)

        self.assertEqual(
            report["artifact_id"],
            "formowl_issue56_hybrid_rag_e2e_poc_v2",
        )
        self.assertFalse(report["fallback_used"])
        self.assertEqual(
            report["dense_retrieval"]["model_id"],
            ISSUE56_TARGET_DENSE_MODEL_ID,
        )
        self.assertEqual(
            report["dense_retrieval"]["model_revision"],
            ISSUE56_TARGET_DENSE_MODEL_REVISION,
        )
        if report["status"] == "blocked":
            self.assertFalse(report["e2e_executed"])
            self.assertIn("blocker", report)
        else:
            self.assertEqual(report["status"], "passed")
            self.assertTrue(report["e2e_executed"])
            self.assertEqual(
                report["dense_retrieval"]["status"],
                "pinned_real_e5",
            )
            self.assertTrue(
                report["permission_filter_invariance"]["authorized_index_fingerprint_unchanged"]
            )
            self.assertEqual(
                report["scenarios"]["permission_denied"]["status"],
                "permission_denied",
            )
        for private_value in (
            "PO470002002",
            "PO470002003",
            "ZX900001999",
            "RESTRICTED-NEBULA-742",
            "2026-09-30",
            "台灣",
            str(ROOT),
        ):
            self.assertNotIn(private_value, serialized)

    def test_real_e5_observation_to_result_path_when_snapshot_is_available(
        self,
    ) -> None:
        try:
            index = build_authorized_hybrid_mail_index(
                observations_by_bundle_id={
                    self.authorized_bundle.mail_evidence_bundle_id: (self.authorized_observations)
                },
                bundles=(self.authorized_bundle,),
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=WORKSPACE_ID,
            )
        except DenseEmbeddingUnavailableError as exc:
            self.skipTest(exc.reason_code)
        result = index.query(
            query_text="PO470002002 交期",
            query_class="evidence_lookup",
        )
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.dense_encoder_status, "pinned_real_e5")
        self.assertEqual(
            result.execution_component_fingerprint,
            index.execution_component_fingerprint,
        )

    def _runtime_patch(self):
        return patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=self.runtime,
        )

    def _combined_index(self):
        with self._runtime_patch():
            return build_authorized_hybrid_mail_index(
                observations_by_bundle_id={
                    self.authorized_bundle.mail_evidence_bundle_id: (self.authorized_observations),
                    self.denied_bundle.mail_evidence_bundle_id: (self.denied_observations),
                },
                bundles=(self.authorized_bundle, self.denied_bundle),
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=WORKSPACE_ID,
            )


class _TrackingObservationMap(Mapping[str, Sequence[Observation]]):
    def __init__(self, values: Mapping[str, Sequence[Observation]]) -> None:
        self._values = dict(values)
        self.value_accesses: list[str] = []

    def __getitem__(self, key: str) -> Sequence[Observation]:
        self.value_accesses.append(key)
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


class _ContractOnlySentenceTransformerModel:
    """Test-only call recorder; never reachable from the normal mail API."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def encode(self, texts: Sequence[str], **_kwargs):
        rows = []
        for text in texts:
            self.calls.append(text)
            vector = [0.0] * 384
            for character in text.casefold():
                vector[ord(character) % len(vector)] += 1.0
            norm = math.sqrt(sum(value * value for value in vector))
            rows.append(_VectorRow(value / norm for value in vector))
        return rows


class _VectorRow(list[float]):
    def tolist(self) -> list[float]:
        return list(self)


def _contract_only_runtime(
    model: _ContractOnlySentenceTransformerModel,
) -> Issue56TargetRuntimeComponents:
    tokenizer_profile = load_issue56_target_mail_tokenizer_profile()
    dense_profile = issue56_target_dense_embedding_profile()
    encoder = SentenceTransformerDenseEncoder(
        profile=dense_profile,
        _model=model,
    )
    binding = build_issue56_execution_component_binding(
        tokenizer_profile=tokenizer_profile,
        dense_profile=dense_profile,
    )
    return Issue56TargetRuntimeComponents(
        tokenizer_profile=tokenizer_profile,
        dense_encoder=encoder,
        execution_binding=binding,
    )


if __name__ == "__main__":
    unittest.main()
