from __future__ import annotations

from importlib import util
import unittest

import _paths  # noqa: F401
from formowl_contract import ContractValidationError
from formowl_graph import (
    LexicalFusionCandidateGenerator,
    ResolutionPolicy,
    ResolutionRecord,
    SplinkPackageCandidateGenerator,
    StructuredLinkageCandidateGenerator,
    build_clerical_review_queue,
    canonical_merge,
    human_clerical_review_queue_export,
    no_raw_access_grant,
    rapid_fuzz_package_version_and_manifest_hash_in_main_repo,
    raw_asset_read,
    real_rapid_fuzz_package_adapter_binding,
    real_splink_package_adapter_binding,
    render_visible_fusion_candidates,
    splink_model_config_manifest_bound_to_main_repo,
)

CREATED_AT = "2026-06-21T00:00:00+00:00"


class GraphResolutionTests(unittest.TestCase):
    def test_lexical_candidate_only_output_keeps_match_separate_from_access_and_merge(
        self,
    ) -> None:
        policy = ResolutionPolicy(
            policy_id="lexical_policy_v1",
            same_as_threshold=0.86,
            clerical_review_min=0.65,
        )
        threshold_config_hash = policy.threshold_config_hash()
        generator = LexicalFusionCandidateGenerator(policy=policy)

        candidate_only_output = generator.candidate_only_output(
            [_record("left_acme_private", "Acme Corp", owner_user_id="user_finance")],
            [_record("right_acme_workspace", "ACME Corporation", owner_user_id="user_ops")],
            created_at=CREATED_AT,
        )

        self.assertEqual(len(candidate_only_output), 1)
        candidate = candidate_only_output[0]
        self.assertEqual(candidate.status, "same_as_candidate")
        self.assertEqual(candidate.threshold_config_hash, threshold_config_hash)
        self.assertFalse(candidate.canonical_merge_performed)
        self.assertFalse(candidate.raw_access_granted)
        self.assertTrue(no_raw_access_grant(candidate))
        self.assertEqual(candidate.ontology_revision_id, "ontology_revision_default_v1")

        requester_view = render_visible_fusion_candidates(
            candidate_only_output,
            visible_record_ids={"right_acme_workspace"},
        )
        self.assertEqual(requester_view, [])
        self.assertNotIn("obs_left_acme_private", str(requester_view))

        public = render_visible_fusion_candidates(
            candidate_only_output,
            visible_record_ids={"left_acme_private", "right_acme_workspace"},
        )[0]
        self.assertEqual(public["left_record"]["visible"], True)
        self.assertEqual(public["right_record"]["visible"], True)
        self.assertTrue(public["access_overlay_required"])
        self.assertNotIn("canonical_graph_revision_id", str(public))
        self.assertNotIn("grant_id", str(public))

    def test_private_pair_redaction_hides_hidden_labels_evidence_and_normalized_tokens(
        self,
    ) -> None:
        generator = LexicalFusionCandidateGenerator()
        candidates = generator.candidate_only_output(
            [
                _record(
                    "left_secret_org",
                    "Acme Secret Acquisition Corp",
                    owner_user_id="user_finance",
                    source_observation_ids=("obs_private_invoice",),
                )
            ],
            [
                _record(
                    "right_public_org",
                    "ACME Corporation",
                    owner_user_id="user_ops",
                    source_observation_ids=("obs_public_mail",),
                )
            ],
            created_at=CREATED_AT,
        )

        private_pair_redaction = candidates[0].to_public_dict(
            visible_record_ids={"right_public_org"}
        )

        public_text = str(private_pair_redaction)
        self.assertNotIn("Acme Secret Acquisition", public_text)
        self.assertNotIn("obs_private_invoice", public_text)
        self.assertNotIn("secret", public_text.lower())
        self.assertIn("obs_public_mail", public_text)
        self.assertTrue(private_pair_redaction["normalization_trace"]["left"]["redacted"])
        self.assertFalse(
            private_pair_redaction["normalization_trace"]["right"].get("redacted", False)
        )

    def test_false_merge_fixture_is_blocked_by_type_gate_and_forbidden_capability_guards(
        self,
    ) -> None:
        false_merge_fixture = LexicalFusionCandidateGenerator().candidate_only_output(
            [_record("left_maya_person", "Maya Chen", core_supertype="Person")],
            [_record("right_maya_project", "Maya Chen", core_supertype="Project")],
            created_at=CREATED_AT,
        )

        self.assertEqual(false_merge_fixture[0].status, "type_mismatch")
        self.assertEqual(false_merge_fixture[0].confidence, 0.0)
        with self.assertRaises(ContractValidationError):
            canonical_merge(false_merge_fixture[0])
        with self.assertRaises(ContractValidationError):
            raw_asset_read(false_merge_fixture[0])

    def test_structured_linkage_hashes_and_clerical_review_queue_are_candidate_only(
        self,
    ) -> None:
        policy = ResolutionPolicy(
            policy_id="structured_policy_v1",
            ontology_revision_id="ontology_revision_structured_fixture_v1",
            same_as_threshold=0.90,
            clerical_review_min=0.40,
            model_config={
                "blocking_rules": ["core_supertype", "city"],
                "comparisons": ["label", "city", "tax_id_last4"],
            },
            training_manifest={
                "training_policy": "fixture_only_no_enterprise_claim",
                "gold_manifest_id": "fixture_org_linkage_v1",
            },
        )
        model_config_hash = policy.model_config_hash()
        training_manifest_hash = policy.training_manifest_hash()
        generator = StructuredLinkageCandidateGenerator(policy=policy)

        candidates = generator.candidate_only_output(
            [
                _record(
                    "left_acme",
                    "Acme Corp",
                    attributes={"city": "Taipei", "tax_id_last4": "4431"},
                )
            ],
            [
                _record(
                    "right_acme",
                    "ACME Corporation",
                    attributes={"city": "Taipei", "tax_id_last4": "4431"},
                ),
                _record(
                    "right_acme_ambiguous",
                    "Acme Holdings",
                    attributes={"city": "Taipei", "tax_id_last4": "0000"},
                ),
            ],
            created_at=CREATED_AT,
        )
        clerical_review_queue = generator.clerical_review_queue(candidates)

        same_as = next(item for item in candidates if item.right_record.record_id == "right_acme")
        self.assertEqual(same_as.status, "same_as_candidate")
        self.assertEqual(same_as.model_config_hash, model_config_hash)
        self.assertEqual(same_as.training_manifest_hash, training_manifest_hash)
        self.assertEqual(
            same_as.ontology_revision_id,
            "ontology_revision_structured_fixture_v1",
        )
        self.assertFalse(same_as.canonical_merge_performed)
        self.assertFalse(same_as.raw_access_granted)
        self.assertTrue(clerical_review_queue)
        self.assertEqual(
            clerical_review_queue[0].reason,
            "ambiguous_score_requires_clerical_review",
        )

    def test_resolution_records_reject_raw_paths_and_do_not_emit_public_raw_values(
        self,
    ) -> None:
        with self.assertRaises(ContractValidationError):
            _record("left_bad", "/srv/customer/private.xlsx")

        with self.assertRaises(ContractValidationError):
            _record("left_bad_attr", "Acme", attributes={"debug_path": "smb://nas/raw"})

    def test_rapidfuzz_package_manifest_is_candidate_only_and_hash_bound(self) -> None:
        manifest = rapid_fuzz_package_version_and_manifest_hash_in_main_repo()

        self.assertEqual(manifest["adapter_id"], "rapidfuzz_lexical_matching")
        self.assertEqual(manifest["package_name"], "rapidfuzz")
        self.assertEqual(manifest["output_store"], "FusionCandidateStore")
        self.assertTrue(manifest["config_hash"].startswith("sha256"))
        self.assertTrue(manifest["package_manifest_hash"].startswith("sha256"))
        self.assertFalse(manifest["canonical_write_allowed"])
        self.assertFalse(manifest["raw_access_allowed"])
        self.assertNotIn("canonical_graph_revision_id", str(manifest))
        self.assertNotIn("raw_path", str(manifest))

    def test_rapidfuzz_package_adapter_requires_real_package_and_stays_candidate_only(
        self,
    ) -> None:
        generator = real_rapid_fuzz_package_adapter_binding()
        if util.find_spec("rapidfuzz") is None:
            with self.assertRaises(ContractValidationError):
                generator.candidate_only_output(
                    [_record("left_acme_pkg", "Acme Corp")],
                    [_record("right_acme_pkg", "ACME Corporation")],
                    created_at=CREATED_AT,
                )
            return

        candidates = generator.candidate_only_output(
            [_record("left_acme_pkg", "Acme Corp")],
            [_record("right_acme_pkg", "ACME Corporation")],
            created_at=CREATED_AT,
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].algorithm, "rapidfuzz_package_candidate_v1")
        self.assertFalse(candidates[0].canonical_merge_performed)
        self.assertFalse(candidates[0].raw_access_granted)
        public = candidates[0].to_public_dict(
            visible_record_ids={"left_acme_pkg", "right_acme_pkg"}
        )
        self.assertIn("package_manifest_hash", public["score_breakdown"])
        self.assertNotIn("grant_id", str(public))

    def test_splink_model_config_manifest_is_bound_without_claiming_execution(self) -> None:
        policy = ResolutionPolicy(
            policy_id="splink_manifest_policy_v1",
            model_config={"blocking_rules": ["core_supertype"], "comparisons": ["label"]},
            training_manifest={"source": "fixture_only_no_enterprise_claim"},
        )
        manifest = splink_model_config_manifest_bound_to_main_repo(policy=policy)

        self.assertEqual(manifest["adapter_id"], "splink_record_linkage")
        self.assertEqual(manifest["package_name"], "splink")
        self.assertEqual(manifest["config_hash"], policy.model_config_hash())
        self.assertEqual(manifest["training_manifest_hash"], policy.training_manifest_hash())
        self.assertEqual(
            manifest["candidate_output_mode"],
            "candidate_only_with_clerical_review_queue",
        )
        self.assertFalse(manifest["canonical_write_allowed"])
        self.assertFalse(manifest["raw_access_allowed"])

    def test_splink_package_adapter_requires_real_package_and_stays_candidate_only(
        self,
    ) -> None:
        policy = ResolutionPolicy(
            policy_id="splink_package_policy_v1",
            same_as_threshold=0.90,
            clerical_review_min=0.40,
            model_config={"blocking_rules": ["core_supertype"], "comparisons": ["label"]},
            training_manifest={"source": "fixture_only_no_enterprise_claim"},
        )
        generator = real_splink_package_adapter_binding(policy=policy)

        self.assertIsInstance(generator, SplinkPackageCandidateGenerator)
        if util.find_spec("splink") is None:
            with self.assertRaises(ContractValidationError):
                generator.candidate_only_output(
                    [_record("left_acme_splink_pkg", "Acme Corp")],
                    [_record("right_acme_splink_pkg", "ACME Corporation")],
                    created_at=CREATED_AT,
                )
            return

        candidates = generator.candidate_only_output(
            [_record("left_acme_splink_pkg", "Acme Corp", attributes={"city": "Taipei"})],
            [
                _record(
                    "right_acme_splink_pkg",
                    "ACME Corporation",
                    attributes={"city": "Taipei"},
                )
            ],
            created_at=CREATED_AT,
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].algorithm, "splink_package_candidate_v1")
        self.assertEqual(candidates[0].model_config_hash, policy.model_config_hash())
        self.assertEqual(
            candidates[0].training_manifest_hash,
            policy.training_manifest_hash(),
        )
        self.assertFalse(candidates[0].canonical_merge_performed)
        self.assertFalse(candidates[0].raw_access_granted)
        public = candidates[0].to_public_dict(
            visible_record_ids={"left_acme_splink_pkg", "right_acme_splink_pkg"}
        )
        self.assertIn("package_manifest_hash", public["score_breakdown"])
        self.assertNotIn("grant_id", str(public))
        self.assertNotIn("canonical_graph_revision_id", str(public))

    def test_human_clerical_review_queue_export_is_permission_aware_and_not_completed(
        self,
    ) -> None:
        policy = ResolutionPolicy(
            policy_id="structured_export_policy_v1",
            same_as_threshold=0.90,
            clerical_review_min=0.40,
            model_config={"blocking_rules": ["core_supertype"], "comparisons": ["label"]},
            training_manifest={"source": "fixture_only_no_enterprise_claim"},
        )
        candidates = StructuredLinkageCandidateGenerator(policy=policy).candidate_only_output(
            [_record("left_acme_export", "Acme Corp", attributes={"city": "Taipei"})],
            [
                _record(
                    "right_acme_export",
                    "Acme Holdings",
                    attributes={"city": "Taipei"},
                )
            ],
            created_at=CREATED_AT,
        )
        queue = build_clerical_review_queue(candidates, policy=policy)

        export = human_clerical_review_queue_export(
            queue,
            reviewer_user_id="reviewer_ops",
            reviewer_visible_record_ids={"left_acme_export", "right_acme_export"},
            created_at=CREATED_AT,
        )

        self.assertEqual(export["artifact_id"], "human_clerical_review_queue_export_v1")
        self.assertEqual(export["item_count"], 1)
        self.assertEqual(export["reviewable_item_count"], 1)
        self.assertEqual(export["redacted_item_count"], 0)
        self.assertTrue(
            export["claim_boundary"]["supports_human_clerical_review_queue_export_claim"]
        )
        self.assertFalse(export["claim_boundary"]["supports_human_review_completed_claim"])
        self.assertFalse(
            export["claim_boundary"]["supports_human_reviewed_false_merge_labels_claim"]
        )
        self.assertFalse(export["claim_boundary"]["supports_canonical_merge_claim"])
        self.assertFalse(export["claim_boundary"]["supports_raw_access_claim"])
        self.assertEqual(
            export["items"][0]["allowed_human_labels"],
            [
                "same_entity",
                "different_entity",
                "insufficient_evidence",
                "request_access_overlay",
            ],
        )
        self.assertEqual(export["items"][0]["next_required_action"], "label_candidate")
        self.assertFalse(export["items"][0]["candidate"]["canonical_merge_performed"])
        self.assertFalse(export["items"][0]["candidate"]["raw_access_granted"])
        self.assertNotIn("grant_id", str(export))
        self.assertNotIn("canonical_graph_revision_id", str(export))

    def test_human_clerical_review_queue_export_redacts_hidden_endpoint(self) -> None:
        policy = ResolutionPolicy(
            policy_id="structured_redacted_export_policy_v1",
            same_as_threshold=0.90,
            clerical_review_min=0.40,
            model_config={"blocking_rules": ["core_supertype"], "comparisons": ["label"]},
            training_manifest={"source": "fixture_only_no_enterprise_claim"},
        )
        candidates = StructuredLinkageCandidateGenerator(policy=policy).candidate_only_output(
            [
                _record(
                    "left_visible_export",
                    "Acme Corp",
                    source_observation_ids=("obs_visible_export",),
                    attributes={"city": "Taipei"},
                )
            ],
            [
                _record(
                    "right_hidden_export",
                    "Confidential Acme Holdings",
                    owner_user_id="user_private",
                    source_observation_ids=("obs_hidden_export",),
                    attributes={"city": "Taipei"},
                )
            ],
            created_at=CREATED_AT,
        )
        queue = build_clerical_review_queue(candidates, policy=policy)

        export = human_clerical_review_queue_export(
            queue,
            reviewer_user_id="reviewer_ops",
            reviewer_visible_record_ids={"left_visible_export"},
            created_at=CREATED_AT,
        )

        item = export["items"][0]
        self.assertFalse(item["reviewable_by_current_reviewer"])
        self.assertTrue(item["permission_review_required"])
        self.assertEqual(item["endpoint_redacted_count"], 1)
        self.assertEqual(export["reviewable_item_count"], 0)
        self.assertEqual(export["redacted_item_count"], 1)
        self.assertEqual(
            item["next_required_action"],
            "request_access_overlay_or_assign_authorized_reviewer",
        )
        public_text = str(export)
        self.assertIn("obs_visible_export", public_text)
        self.assertNotIn("Confidential Acme Holdings", public_text)
        self.assertNotIn("obs_hidden_export", public_text)
        self.assertNotIn("user_private", public_text)

    def test_human_clerical_review_queue_export_rejects_malformed_public_inputs(
        self,
    ) -> None:
        policy = ResolutionPolicy(clerical_review_min=0.40, same_as_threshold=0.90)
        candidates = StructuredLinkageCandidateGenerator(policy=policy).candidate_only_output(
            [_record("left_export_bad", "Acme Corp", attributes={"city": "Taipei"})],
            [_record("right_export_bad", "Acme Holdings", attributes={"city": "Taipei"})],
            created_at=CREATED_AT,
        )
        queue = build_clerical_review_queue(candidates, policy=policy)

        with self.assertRaises(ContractValidationError):
            human_clerical_review_queue_export(
                queue,
                reviewer_user_id="reviewer_ops",
                reviewer_visible_record_ids="left_export_bad",
            )
        with self.assertRaises(ContractValidationError):
            human_clerical_review_queue_export(
                queue,
                reviewer_user_id="/home/private/reviewer",
                reviewer_visible_record_ids={"left_export_bad"},
            )


def _record(
    record_id: str,
    label: str,
    *,
    core_supertype: str = "Organization",
    owner_user_id: str = "user_finance",
    scope_type: str = "private_user",
    scope_id: str | None = None,
    source_candidate_atom_id: str | None = None,
    source_observation_ids: tuple[str, ...] | None = None,
    attributes: dict[str, str] | None = None,
) -> ResolutionRecord:
    return ResolutionRecord.from_candidate_atom(
        record_id=record_id,
        label=label,
        atom_type=core_supertype,
        owner_user_id=owner_user_id,
        scope_type=scope_type,
        scope_id=scope_id or owner_user_id,
        source_candidate_atom_id=source_candidate_atom_id or f"catom_{record_id}",
        source_observation_ids=source_observation_ids or (f"obs_{record_id}",),
        attributes=attributes or {},
    )


if __name__ == "__main__":
    unittest.main()
