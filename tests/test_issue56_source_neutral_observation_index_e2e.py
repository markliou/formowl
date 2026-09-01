from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, Observation, sha256_json
from formowl_core import load_issue56_target_mail_tokenizer_profile
from formowl_graph import EffectiveGraphView
from formowl_mail import query as query_module
from formowl_mail.hybrid import _sealed_source_neutral_observation
from formowl_mail.query import (
    GitHubProjectOccurrenceLineage,
    build_authorized_observation_snippet_index,
    build_existing_observation_snippet_index,
    source_occurrence_lineage_from_observation,
)
from formowl_mail.semantic_plan import (
    AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
    GITHUB_PROJECT_OBSERVATION_SOURCE_KIND,
    route_semantic_query,
    validated_authorized_semantic_source,
    validate_semantic_query_plan,
)
from scripts.issue56_semantic_execution_smoke import build_semantic_poc_inputs


WORKSPACE_ID = "workspace_source_neutral_fixture"
PROJECT_SCOPE_ID = "project_source_neutral_fixture"
REQUESTER_ID = "user_source_neutral_fixture"


def _view() -> EffectiveGraphView:
    return EffectiveGraphView(
        requester_user_id=REQUESTER_ID,
        user_graph_revision_id="user_graph_source_neutral_fixture",
        canonical_graph_revision_id="canonical_graph_source_neutral_fixture",
        ontology_revision_id="ontology_source_neutral_fixture",
        assembly_policy_id="assembly_source_neutral_fixture",
    )


def _github_observation(
    *,
    observation_id: str,
    record_kind: str,
    source_local_key: str,
    source_record_fingerprint: str,
    text: str,
    parent_source_local_key: str | None = None,
) -> Observation:
    location: dict[str, object] = {
        "source_local_key": source_local_key,
        "source_record_fingerprint": source_record_fingerprint,
        "record_kind": record_kind,
    }
    if parent_source_local_key is not None:
        location["parent_source_local_key"] = parent_source_local_key
    payload: dict[str, object] = {
        **location,
        "issue_number": 56,
        "created_at": "2026-08-19T00:00:00+00:00",
        "updated_at": "2026-08-19T01:00:00+00:00",
        "source_native_issue_references": [51],
    }
    if record_kind == "issue_record":
        payload["state"] = "open"
        payload["label_names"] = ["kg", "transfer"]
    return Observation.from_dict(
        Observation(
            observation_id=observation_id,
            extractor_run_id="extractor_source_neutral_fixture",
            observation_type=record_kind,
            modality="project",
            location=location,
            confidence=1.0,
            permission_scope={
                "scope_type": "project",
                "visibility": "shared",
                "scope_id": PROJECT_SCOPE_ID,
            },
            created_at="2026-08-19T01:00:00+00:00",
            asset_id="asset_source_neutral_fixture",
            text=text,
            payload=payload,
        ).to_dict()
    )


class Issue56SourceNeutralObservationIndexEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = load_issue56_target_mail_tokenizer_profile()
        cls.source = validated_authorized_semantic_source(
            source_kind=GITHUB_PROJECT_OBSERVATION_SOURCE_KIND,
            workspace_id=WORKSPACE_ID,
            source_scope_ids=(PROJECT_SCOPE_ID,),
        )
        issue_key = "srclocal_issue_source_neutral_fixture"
        cls.issue = _github_observation(
            observation_id="observation_github_issue_source_neutral",
            record_kind="issue_record",
            source_local_key=issue_key,
            source_record_fingerprint=sha256_json("github-issue-record"),
            text="Issue 56 tracks source-neutral semantic execution.",
        )
        cls.comment = _github_observation(
            observation_id="observation_github_comment_source_neutral",
            record_kind="top_level_issue_comment",
            source_local_key="srclocal_comment_source_neutral_fixture",
            source_record_fingerprint=sha256_json("github-comment-record"),
            text="The project comment references issue 51 and the typed plan.",
            parent_source_local_key=issue_key,
        )
        cls.observations = (cls.issue, cls.comment)
        cls.authorized_hashes = {
            observation.observation_id: sha256_json(observation.to_dict())
            for observation in cls.observations
        }
        cls.lineages = tuple(
            source_occurrence_lineage_from_observation(
                observation,
                authorized_source=cls.source,
            )
            for observation in cls.observations
        )

    def test_github_issue_comment_occurrences_round_trip_deterministically(self) -> None:
        first_index, first_manifest = build_authorized_observation_snippet_index(
            self.observations,
            authorized_source=self.source,
            occurrence_lineages=self.lineages,
            authorized_observation_hash_by_id=self.authorized_hashes,
            tokenizer_profile=self.profile,
        )
        second_index, second_manifest = build_authorized_observation_snippet_index(
            tuple(reversed(self.observations)),
            authorized_source=self.source,
            occurrence_lineages=tuple(reversed(self.lineages)),
            authorized_observation_hash_by_id=dict(reversed(self.authorized_hashes.items())),
            tokenizer_profile=self.profile,
        )

        self.assertEqual(first_index.index_fingerprint, second_index.index_fingerprint)
        self.assertEqual(first_manifest, second_manifest)
        self.assertEqual(first_manifest.observation_count, 2)
        self.assertEqual(first_manifest.indexed_observation_count, 2)
        self.assertEqual(first_manifest.missing_lineage_count, 0)
        self.assertEqual(
            [snippet.payload["source_observation_id"] for snippet in first_index.snippets],
            sorted(self.authorized_hashes),
        )
        issue_lineage, comment_lineage = sorted(
            self.lineages,
            key=lambda lineage: lineage.source_observation_id,
        )
        self.assertIsInstance(issue_lineage, GitHubProjectOccurrenceLineage)
        self.assertIsInstance(comment_lineage, GitHubProjectOccurrenceLineage)
        self.assertEqual(
            {lineage.record_kind for lineage in (issue_lineage, comment_lineage)},
            {"issue_record", "top_level_issue_comment"},
        )
        self.assertTrue(
            any(
                lineage.parent_source_local_key is not None
                for lineage in (issue_lineage, comment_lineage)
            )
        )

    def test_owner_snapshot_uses_one_detached_boundary_round_trip(self) -> None:
        expected_index, expected_manifest = build_authorized_observation_snippet_index(
            self.observations,
            authorized_source=self.source,
            occurrence_lineages=self.lineages,
            authorized_observation_hash_by_id=self.authorized_hashes,
            tokenizer_profile=self.profile,
        )
        sealed_observations = tuple(
            _sealed_source_neutral_observation(observation)
            for observation in self.observations
        )
        sealed_hashes = {
            observation.observation_id: sha256_json(observation.to_dict())
            for observation in sealed_observations
        }
        original_to_dict = Observation.to_dict
        with (
            patch.object(
                query_module.Observation,
                "to_dict",
                autospec=True,
                side_effect=original_to_dict,
            ) as serialized_snapshots,
            patch.object(
                query_module.Observation,
                "from_dict",
                wraps=Observation.from_dict,
            ) as boundary_snapshots,
        ):
            actual_index, actual_manifest = build_authorized_observation_snippet_index(
                sealed_observations,
                authorized_source=self.source,
                occurrence_lineages=self.lineages,
                authorized_observation_hash_by_id=sealed_hashes,
                tokenizer_profile=self.profile,
            )

        self.assertEqual(serialized_snapshots.call_count, len(sealed_observations))
        self.assertEqual(boundary_snapshots.call_count, len(sealed_observations))
        self.assertEqual(actual_index, expected_index)
        self.assertEqual(actual_manifest, expected_manifest)

    def test_denied_missing_authorization_and_mixed_source_fail_before_indexing(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ContractValidationError,
            "authorization binding mismatch",
        ):
            build_authorized_observation_snippet_index(
                self.observations,
                authorized_source=self.source,
                occurrence_lineages=self.lineages,
                authorized_observation_hash_by_id={
                    self.issue.observation_id: self.authorized_hashes[self.issue.observation_id]
                },
                tokenizer_profile=self.profile,
            )
        denied_comment = replace(
            self.comment,
            permission_scope={
                "scope_type": "project",
                "visibility": "shared",
                "scope_id": "project_not_authorized",
            },
        )
        denied_observations = (self.issue, denied_comment)
        denied_hashes = {
            observation.observation_id: sha256_json(observation.to_dict())
            for observation in denied_observations
        }
        denied_lineages = tuple(
            source_occurrence_lineage_from_observation(
                observation,
                authorized_source=self.source,
            )
            for observation in denied_observations
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "permission scope mismatch",
        ):
            build_authorized_observation_snippet_index(
                denied_observations,
                authorized_source=self.source,
                occurrence_lineages=denied_lineages,
                authorized_observation_hash_by_id=denied_hashes,
                tokenizer_profile=self.profile,
            )

        mail_observation = replace(
            self.issue,
            observation_id="observation_mail_mixed_source",
            modality="mail",
            observation_type="email_body_segment",
            location={"message_occurrence_id": "mail_occurrence_mixed_source"},
            payload={"message_occurrence_id": "mail_occurrence_mixed_source"},
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "GitHub source occurrence schema mismatch",
        ):
            source_occurrence_lineage_from_observation(
                mail_observation,
                authorized_source=self.source,
            )

    def test_exact_inventory_plan_is_pinned_to_github_source(self) -> None:
        class NonIterableVisibleNodes(list[object]):
            def __iter__(self):
                raise AssertionError("seedless exact plans must not scan graph nodes")

        view = replace(_view(), visible_nodes=NonIterableVisibleNodes())
        plan = route_semantic_query(
            query_text="How many issue records are in the complete inventory?",
            requester_user_id=REQUESTER_ID,
            workspace_id=WORKSPACE_ID,
            source_scope_ids=(PROJECT_SCOPE_ID,),
            effective_graph_view=view,
            exact_inventory_kind="project_observation",
            authorized_source=self.source,
        )

        self.assertEqual(plan.query_class, "exact_set_or_inventory")
        self.assertEqual(plan.source_kind, GITHUB_PROJECT_OBSERVATION_SOURCE_KIND)
        self.assertEqual(plan.exact_inventory_kind, "project_observation")
        self.assertEqual(
            validate_semantic_query_plan(
                plan,
                effective_graph_view=view,
                authorized_workspace_id=WORKSPACE_ID,
                authorized_source_scope_ids=(PROJECT_SCOPE_ID,),
                supported_relation_types=(),
                authorized_source=self.source,
            ),
            plan,
        )

    def test_source_kind_scope_and_arbitrary_source_mismatch_fail_closed(self) -> None:
        plan = route_semantic_query(
            query_text="Find the project issue evidence.",
            requester_user_id=REQUESTER_ID,
            workspace_id=WORKSPACE_ID,
            source_scope_ids=(PROJECT_SCOPE_ID,),
            effective_graph_view=_view(),
            authorized_source=self.source,
        )
        mail_source = validated_authorized_semantic_source(
            source_kind=AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
            workspace_id=WORKSPACE_ID,
            source_scope_ids=(PROJECT_SCOPE_ID,),
        )
        with self.assertRaisesRegex(ContractValidationError, "source kind mismatch"):
            validate_semantic_query_plan(
                plan,
                effective_graph_view=_view(),
                authorized_workspace_id=WORKSPACE_ID,
                authorized_source_scope_ids=(PROJECT_SCOPE_ID,),
                supported_relation_types=(),
                authorized_source=mail_source,
            )
        with self.assertRaisesRegex(
            ContractValidationError,
            "authorized source scope mismatch",
        ):
            route_semantic_query(
                query_text="Find the project issue evidence.",
                requester_user_id=REQUESTER_ID,
                workspace_id=WORKSPACE_ID,
                source_scope_ids=(PROJECT_SCOPE_ID,),
                effective_graph_view=_view(),
                authorized_source=validated_authorized_semantic_source(
                    source_kind=GITHUB_PROJECT_OBSERVATION_SOURCE_KIND,
                    workspace_id=WORKSPACE_ID,
                    source_scope_ids=("different_project_scope",),
                ),
            )
        with self.assertRaisesRegex(ContractValidationError, "unsupported"):
            validated_authorized_semantic_source(
                source_kind="caller_supplied_unregistered_source",
                workspace_id=WORKSPACE_ID,
                source_scope_ids=(PROJECT_SCOPE_ID,),
            )

    def test_existing_mail_wrapper_and_default_plan_fingerprints_are_unchanged(
        self,
    ) -> None:
        inputs = build_semantic_poc_inputs()
        bundle = inputs.current_bundle
        observations = inputs.observations_by_bundle_id[bundle.mail_evidence_bundle_id]
        first_index, first_manifest = build_existing_observation_snippet_index(
            observations,
            bundle=bundle,
            tokenizer_profile=self.profile,
        )
        second_index, second_manifest = build_existing_observation_snippet_index(
            observations,
            bundle=bundle,
            tokenizer_profile=self.profile,
        )
        self.assertEqual(
            first_manifest.artifact_id,
            "formowl_existing_observation_mail_index_manifest_v1",
        )
        self.assertEqual(first_index.index_fingerprint, second_index.index_fingerprint)
        self.assertEqual(first_manifest, second_manifest)

        source_scope_ids = (bundle.mail_evidence_bundle_id,)
        default_plan = route_semantic_query(
            query_text="Find the authorized mail evidence.",
            requester_user_id=REQUESTER_ID,
            workspace_id=WORKSPACE_ID,
            source_scope_ids=source_scope_ids,
            effective_graph_view=_view(),
        )
        explicit_plan = route_semantic_query(
            query_text="Find the authorized mail evidence.",
            requester_user_id=REQUESTER_ID,
            workspace_id=WORKSPACE_ID,
            source_scope_ids=source_scope_ids,
            effective_graph_view=_view(),
            authorized_source=validated_authorized_semantic_source(
                source_kind=AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
                workspace_id=WORKSPACE_ID,
                source_scope_ids=source_scope_ids,
            ),
        )
        self.assertEqual(default_plan, explicit_plan)
        self.assertEqual(default_plan.plan_fingerprint, explicit_plan.plan_fingerprint)


if __name__ == "__main__":
    unittest.main()
