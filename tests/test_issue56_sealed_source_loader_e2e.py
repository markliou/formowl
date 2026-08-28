from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import _paths  # noqa: F401
from formowl_contract import (
    Observation,
    PermissionScope,
    SourceInventory,
    SourceInventoryItem,
    sha256_json,
)
from formowl_gateway.issue56_diagnostic import Issue56SealedSourceDiagnosticInput
from formowl_gateway import issue56_sealed_source_loader as gateway_loader
from formowl_mail import build_mail_evidence_bundle
from formowl_mail import issue56_sealed_source as sealed_source
from formowl_mail.query import source_occurrence_lineage_from_observation

from scripts import issue56_identity_scope_attestation as identity_attestation
from scripts import issue56_materialize_development_uat_observations as materializer
from scripts import issue56_prompt_mcp_hybrid_diagnostic as diagnostic_cli
from scripts import issue56_source_identifier_candidates as candidate_builder
import test_issue56_materialize_development_uat_observations_e2e as materializer_fixture


CREATED_AT = "2026-08-20T09:00:00+00:00"
WORKSPACE_PERMISSION_SCOPE = PermissionScope(
    scope_type="workspace",
    scope_id=sealed_source.WORKSPACE_ID,
    visibility="restricted",
)


class _PreparedPackage:
    def __init__(
        self,
        *,
        fixture: object,
        work_dir: Path,
        materialization_private_sha256: str,
        materialization_safe_sha256: str,
        attestation_root: Path,
        attestation_private_sha256: str,
        attestation_safe_sha256: str,
        identity_scope_fingerprint: str,
        candidate_root: Path,
        candidate_private_sha256: str,
        candidate_safe_sha256: str,
    ) -> None:
        self.fixture = fixture
        self.work_dir = work_dir
        self.materialization_private_sha256 = materialization_private_sha256
        self.materialization_safe_sha256 = materialization_safe_sha256
        self.attestation_root = attestation_root
        self.attestation_private_sha256 = attestation_private_sha256
        self.attestation_safe_sha256 = attestation_safe_sha256
        self.identity_scope_fingerprint = identity_scope_fingerprint
        self.candidate_root = candidate_root
        self.candidate_private_sha256 = candidate_private_sha256
        self.candidate_safe_sha256 = candidate_safe_sha256


class Issue56SealedSourceLoaderE2ETests(unittest.TestCase):
    def test_sealed_package_builds_existing_session_graph_and_gateway_contract(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = _prepare_package(root)
            loaded = sealed_source.load_issue56_sealed_source(**_loader_kwargs(package))

            self.assertEqual(len(loaded.observations), 456)
            self.assertEqual(loaded.index.authorized_bundle_count, 1)
            self.assertEqual(loaded.index.denied_bundle_count, 0)
            self.assertEqual(
                loaded.graph_build.graph_policy_id,
                sealed_source.SOURCE_GRAPH_POLICY_ID,
            )
            self.assertEqual(
                loaded.graph_build.identifier_mention_count,
                loaded.identifier_mention_batch.occurrence_count,
            )
            self.assertGreater(loaded.graph_build.edge_count, 0)
            self.assertEqual(
                loaded.safe_binding["counts"]["selected_observation_count"],
                456,
            )
            self.assertEqual(
                loaded.safe_binding["counts"]["authorized_observation_count"],
                456,
            )
            self.assertEqual(loaded.safe_binding["counts"]["overflow_count"], 0)
            precompute = loaded.safe_binding["lineage_crosswalk_precompute"]
            self.assertEqual(precompute["status"], "passed")
            self.assertEqual(precompute["cache_status"], "primed")
            self.assertEqual(precompute["helper_invocation_count"], 1)
            self.assertGreaterEqual(precompute["elapsed_ms"], 0)
            self.assertEqual(
                precompute["index_fingerprint"],
                loaded.safe_binding["index_fingerprint"],
            )
            self.assertEqual(
                precompute["graph_revision_fingerprint"],
                loaded.safe_binding["graph_revision_fingerprint"],
            )
            self.assertEqual(
                precompute["source_session_binding_fingerprint"],
                loaded.session.source_session_binding_fingerprint,
            )
            relation_precompute = loaded.safe_binding["relation_projection_base_precompute"]
            self.assertEqual(relation_precompute["status"], "passed")
            self.assertEqual(relation_precompute["cache_status"], "primed")
            self.assertEqual(relation_precompute["helper_invocation_count"], 1)
            self.assertGreaterEqual(relation_precompute["elapsed_ms"], 0)
            self.assertEqual(
                relation_precompute["index_fingerprint"],
                loaded.safe_binding["index_fingerprint"],
            )
            self.assertEqual(
                relation_precompute["graph_revision_fingerprint"],
                loaded.safe_binding["graph_revision_fingerprint"],
            )

            rendered_safe = json.dumps(
                dict(loaded.safe_binding),
                ensure_ascii=True,
                sort_keys=True,
            )
            self.assertNotIn(str(root), rendered_safe)
            self.assertNotIn("CASE-", rendered_safe)
            self.assertNotIn("obs_body_", rendered_safe)
            self.assertNotIn('"tenant_id"', rendered_safe)

            environment = _loader_environment(package)
            resolved = diagnostic_cli.resolve_sealed_source_loader(gateway_loader.LOADER_SPEC)
            self.assertIs(
                resolved,
                gateway_loader.load_issue56_sealed_source_diagnostic_input,
            )
            with (
                mock.patch.dict(os.environ, environment, clear=False),
                mock.patch.object(
                    gateway_loader,
                    "load_issue56_sealed_source",
                    return_value=loaded,
                ) as core_loader,
            ):
                diagnostic_input = resolved()
            core_loader.assert_called_once()
            self.assertIsInstance(
                diagnostic_input,
                Issue56SealedSourceDiagnosticInput,
            )
            self.assertEqual(diagnostic_input.observation_count, 456)
            self.assertEqual(
                diagnostic_input.loader_contract_fingerprint,
                gateway_loader.LOADER_CONTRACT_FINGERPRINT,
            )
            self.assertEqual(
                diagnostic_input.lineage_crosswalk_precompute.crosswalk_fingerprint,
                precompute["crosswalk_fingerprint"],
            )
            self.assertEqual(
                diagnostic_input.lineage_crosswalk_precompute.helper_invocation_count,
                1,
            )
            self.assertEqual(
                diagnostic_input.relation_projection_base_precompute.precompute_fingerprint,
                relation_precompute["precompute_fingerprint"],
            )
            self.assertEqual(
                diagnostic_input.relation_projection_base_precompute.helper_invocation_count,
                1,
            )
            self.assertTrue(diagnostic_input.allowed_relation_types)

            expanded = sealed_source.load_issue56_sealed_source(
                **_loader_kwargs(package),
                include_participant_authorization_observations=True,
            )
            selected_hashes = tuple(
                sorted(
                    (
                        observation.observation_id,
                        sha256_json(observation.to_dict()),
                    )
                    for observation in expanded.observations
                )
            )
            self.assertEqual(expanded.session.retrieval_observation_hashes, selected_hashes)
            self.assertTrue(
                set(selected_hashes).issubset(
                    set(expanded.session.authorized_observation_hashes)
                )
            )
            self.assertEqual(
                expanded.safe_binding["counts"]["selected_observation_count"],
                len(expanded.observations),
            )
            self.assertGreater(
                expanded.safe_binding["counts"]["authorized_observation_count"],
                len(expanded.observations),
            )
            self.assertEqual(
                expanded.safe_binding["counts"]["graph_source_observation_count"],
                len(expanded.observations),
            )

    def test_gateway_rejects_owner_precompute_safe_binding_drift(self) -> None:
        index_fingerprint = sha256_json("index")
        graph_revision_fingerprint = sha256_json("graph")
        source_session_binding_fingerprint = sha256_json("authorized source set")
        tokenizer_profile_fingerprint = sha256_json("tokenizer")
        relation_counts = {
            "authorized_observation_count": 1,
            "candidate_count": 1,
            "projected_node_count": 2,
            "observation_bound_node_group_count": 1,
            "adjacency_node_count": 2,
            "adjacency_transition_count": 2,
            "authorized_index_vocabulary_hash_count": 1,
            "authorized_graph_vocabulary_hash_count": 1,
        }
        relation_payload = {
            "cache_binding_fingerprint": sha256_json("cache"),
            "graph_revision_fingerprint": graph_revision_fingerprint,
            "index_fingerprint": index_fingerprint,
            "tokenizer_profile_fingerprint": tokenizer_profile_fingerprint,
            "authorized_observation_set_fingerprint": sha256_json("authorized"),
            "candidate_set_fingerprint": sha256_json("candidates"),
            **relation_counts,
        }
        binding = {
            "status": "passed",
            "identity_scope_mode_status": sealed_source.IDENTITY_SCOPE_MODE,
            "tenant_dimension_status": "not_modeled_not_fabricated",
            "index_fingerprint": index_fingerprint,
            "graph_revision_fingerprint": graph_revision_fingerprint,
            "candidate_admission_profile_fingerprint": tokenizer_profile_fingerprint,
            "source_asset_fingerprint": sha256_json("asset"),
            "counts": {
                "authorized_observation_count": 1,
                "graph_observation_node_count": 1,
                "graph_entity_node_count": 1,
                "graph_edge_count": 1,
            },
            "lineage_crosswalk_precompute": {
                "index_fingerprint": index_fingerprint,
                "graph_revision_fingerprint": graph_revision_fingerprint,
                "source_session_binding_fingerprint": (
                    source_session_binding_fingerprint
                ),
                "cache_key_fingerprint": sha256_json(
                    {
                        "artifact_id": (
                            "formowl_issue56_evidence_identity_lineage_cache_key_v1"
                        ),
                        "index_fingerprint": index_fingerprint,
                        "graph_revision_fingerprint": graph_revision_fingerprint,
                        "source_session_binding_fingerprint": (
                            source_session_binding_fingerprint
                        ),
                    }
                ),
                "counts": {"authorized_evidence_count": 1},
            },
            "relation_projection_base_precompute": {
                "artifact_id": "formowl_issue56_relation_projection_base_precompute_v1",
                "schema_version": 1,
                "status": "passed",
                "cache_status": "primed",
                "helper_invocation_count": 1,
                "elapsed_ms": 1.0,
                "cache_binding_fingerprint": relation_payload["cache_binding_fingerprint"],
                "graph_revision_fingerprint": graph_revision_fingerprint,
                "index_fingerprint": index_fingerprint,
                "candidate_admission_profile_fingerprint": (tokenizer_profile_fingerprint),
                "authorized_observation_set_fingerprint": relation_payload[
                    "authorized_observation_set_fingerprint"
                ],
                "candidate_set_fingerprint": relation_payload["candidate_set_fingerprint"],
                "counts": relation_counts,
                "precompute_fingerprint": sha256_json(
                    {
                        "artifact_id": ("formowl_issue56_relation_projection_base_precompute_v1"),
                        **relation_payload,
                    }
                ),
            },
        }
        binding["binding_fingerprint"] = sha256_json(binding)
        gateway_loader._validated_owner_safe_binding(
            binding,
            source_session_binding_fingerprint=(
                source_session_binding_fingerprint
            ),
        )

        different_authorization_cache_key = sha256_json(
            {
                "artifact_id": (
                    "formowl_issue56_evidence_identity_lineage_cache_key_v1"
                ),
                "index_fingerprint": index_fingerprint,
                "graph_revision_fingerprint": graph_revision_fingerprint,
                "source_session_binding_fingerprint": sha256_json(
                    "different authorized source set"
                ),
            }
        )
        self.assertNotEqual(
            binding["lineage_crosswalk_precompute"]["cache_key_fingerprint"],
            different_authorization_cache_key,
        )
        wrong_cache_key = deepcopy(binding)
        wrong_cache_key["lineage_crosswalk_precompute"]["cache_key_fingerprint"] = (
            different_authorization_cache_key
        )
        wrong_cache_key["binding_fingerprint"] = sha256_json(
            {
                key: value
                for key, value in wrong_cache_key.items()
                if key != "binding_fingerprint"
            }
        )
        with self.assertRaisesRegex(
            Exception,
            "owner precompute binding mismatch",
        ):
            gateway_loader._validated_owner_safe_binding(
                wrong_cache_key,
                source_session_binding_fingerprint=(
                    source_session_binding_fingerprint
                ),
            )

        drifted = deepcopy(binding)
        drifted["lineage_crosswalk_precompute"]["graph_revision_fingerprint"] = sha256_json(
            "drifted"
        )
        with self.assertRaisesRegex(
            Exception,
            "owner safe binding seal mismatch",
        ):
            gateway_loader._validated_owner_safe_binding(
                drifted,
                source_session_binding_fingerprint=(
                    source_session_binding_fingerprint
                ),
            )

        cross_binding_drift = deepcopy(binding)
        cross_binding_drift["relation_projection_base_precompute"]["graph_revision_fingerprint"] = (
            sha256_json("different graph")
        )
        cross_binding_drift["binding_fingerprint"] = sha256_json(
            {
                key: value
                for key, value in cross_binding_drift.items()
                if key != "binding_fingerprint"
            }
        )
        with self.assertRaisesRegex(
            Exception,
            "owner relation projection precompute binding mismatch",
        ):
            gateway_loader._validated_owner_safe_binding(
                cross_binding_drift,
                source_session_binding_fingerprint=(
                    source_session_binding_fingerprint
                ),
            )

    def test_fixed_identity_mismatches_fail_before_source_loading(self) -> None:
        missing = Path("/not/read/by/fixed-identity-validation")
        base = {
            "retrieval_snapshot_path": missing,
            "expected_retrieval_snapshot_sha256": sha256_json("missing"),
            "bundle_artifact_path": missing,
            "expected_bundle_artifact_sha256": sha256_json("missing"),
            "retrieval_report_path": missing,
            "expected_retrieval_report_sha256": sha256_json("missing"),
            "materialized_work_dir": missing,
            "expected_materialization_artifact_sha256": sha256_json("missing"),
            "expected_materialization_safe_report_sha256": sha256_json("missing"),
            "identity_scope_attestation_path": missing,
            "expected_identity_scope_attestation_sha256": sha256_json("missing"),
            "identity_scope_safe_report_path": missing,
            "expected_identity_scope_safe_report_sha256": sha256_json("missing"),
            "source_identifier_candidate_artifact_path": missing,
            "expected_source_identifier_candidate_artifact_sha256": sha256_json("missing"),
            "source_identifier_candidate_safe_report_path": missing,
            "expected_source_identifier_candidate_safe_report_sha256": sha256_json("missing"),
            "expected_identity_scope_fingerprint": sha256_json("scope"),
            "identity_scope_mode": sealed_source.IDENTITY_SCOPE_MODE,
            "workspace_id": sealed_source.WORKSPACE_ID,
            "approver_actor": sealed_source.APPROVER_ACTOR,
            "requester_user_id": sealed_source.APPROVER_ACTOR,
        }
        mutations = (
            ("identity_scope_mode", "tenant_workspace_v1", "identity_scope_mode_mismatch"),
            ("workspace_id", "workspace_other", "workspace_binding_mismatch"),
            ("approver_actor", "user_other", "approver_binding_mismatch"),
            ("requester_user_id", "user_other", "requester_approver_binding_mismatch"),
        )
        for field_name, value, reason in mutations:
            with self.subTest(field_name=field_name):
                kwargs = {**base, field_name: value}
                with self.assertRaisesRegex(
                    sealed_source.Issue56SealedSourceLoadError,
                    f"^{reason}$",
                ):
                    sealed_source.load_issue56_sealed_source(**kwargs)

    def test_materialized_record_and_candidate_safe_seal_tamper_fail_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = _prepare_package(root)
            record_path = next(
                (package.work_dir / materializer.OBSERVATION_RELATIVE_DIRECTORY).glob("*.json")
            )
            record_path.write_bytes(record_path.read_bytes() + b" ")
            with self.assertRaisesRegex(
                sealed_source.Issue56SealedSourceLoadError,
                "materialization_observation_record_byte_seal_mismatch",
            ):
                sealed_source.load_issue56_sealed_source(**_loader_kwargs(package))

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = _prepare_package(root)
            safe_path = package.candidate_root / candidate_builder.SAFE_REPORT_FILENAME
            safe_path.write_bytes(safe_path.read_bytes() + b" ")
            with self.assertRaisesRegex(
                sealed_source.Issue56SealedSourceLoadError,
                "^source_identifier_candidate_safe_report_byte_seal_mismatch$",
            ):
                sealed_source.load_issue56_sealed_source(**_loader_kwargs(package))

    def test_any_tenant_id_key_is_rejected_before_candidate_use(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = _prepare_package(root)
            attestation_path = (
                package.attestation_root / identity_attestation.PRIVATE_ARTIFACT_FILENAME
            )
            private = json.loads(attestation_path.read_text(encoding="utf-8"))
            private["identity_scope"]["tenant_id"] = "forbidden"
            private["attestation_fingerprint"] = _payload_fingerprint(
                private,
                "attestation_fingerprint",
            )
            attestation_path.write_bytes(_json_bytes(private))
            kwargs = _loader_kwargs(package)
            kwargs["expected_identity_scope_attestation_sha256"] = _sha256_path(attestation_path)
            with self.assertRaisesRegex(
                sealed_source.Issue56SealedSourceLoadError,
                "^identity_scope_attestation_tenant_id_forbidden$",
            ):
                sealed_source.load_issue56_sealed_source(**kwargs)

    def test_gateway_environment_is_complete_and_never_accepts_tenant(self) -> None:
        required_names = set(gateway_loader._ENVIRONMENT_FIELDS.values())
        self.assertNotIn("FORMOWL_ISSUE56_TENANT_ID", required_names)
        self.assertTrue(all("TENANT" not in name for name in required_names))
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                Exception,
                "sealed source loader environment is incomplete",
            ):
                gateway_loader.load_issue56_sealed_source_diagnostic_input()

    def test_direct_identifier_provider_preserves_authorized_occurrence_lineage(
        self,
    ) -> None:
        shared_identifier = "CASE-7777"
        shared_identifier_hash = sha256_json(shared_identifier.casefold())
        with tempfile.TemporaryDirectory() as temp_dir:
            package = _prepare_package(
                Path(temp_dir),
                shared_direct_identifier=shared_identifier,
            )
            loaded = sealed_source.load_issue56_sealed_source(
                **_loader_kwargs(package),
                include_participant_authorization_observations=True,
            )
            matching_mentions = tuple(
                mention
                for mention in loaded.identifier_mention_batch.candidate_mentions
                if mention.normalized_label == shared_identifier_hash
            )
            source_occurrence_count = sum(
                observation.text is not None
                and shared_identifier.casefold() in observation.text.casefold()
                for observation in (
                    Observation.from_dict(row)
                    for row in package.fixture.snapshot["parsed_mail_observations"]
                )
            )
            self.assertGreater(source_occurrence_count, len(matching_mentions))

            with mock.patch.dict(
                os.environ,
                _loader_environment(package),
                clear=False,
            ):
                providers = gateway_loader._build_mail_source_occurrence_providers(
                    loaded,
                    safe_binding=loaded.safe_binding,
                )
            matching_providers = tuple(
                provider
                for provider in providers
                if any(
                    shared_identifier_hash in binding[:2]
                    for occurrence in provider.occurrences
                    for binding in occurrence.value_bindings
                )
            )
            direct_identifier_providers = tuple(
                provider
                for provider in providers
                if provider.provider_id
                == "mail_message_occurrence_direct_source_identifier_provider_v1"
            )
            self.assertEqual(len(direct_identifier_providers), 1)
            self.assertEqual(len(matching_providers), 1)
            provider = matching_providers[0]
            self.assertIs(provider, direct_identifier_providers[0])
            authorized_hash_by_id = dict(loaded.session.authorized_observation_hashes)
            lineage_by_id = {
                lineage.source_observation_id: lineage
                for lineage in loaded.session.occurrence_lineages
            }
            retrieval_occurrence_ids = {
                lineage_by_id[observation_id].occurrence_id
                for observation_id, _ in loaded.session.retrieval_observation_hashes
            }
            authorized_occurrence_ids = {
                lineage.occurrence_id for lineage in loaded.session.occurrence_lineages
            }
            projected_occurrence_ids = {
                lineage_by_id[observation_id].occurrence_id
                for mention in loaded.identifier_mention_batch.candidate_mentions
                if mention.mention_type == "protected_identifier:business_identifier"
                for observation_id in mention.source_observation_ids
            }
            self.assertLess(
                len(retrieval_occurrence_ids),
                len(authorized_occurrence_ids),
            )
            self.assertEqual(
                authorized_occurrence_ids,
                {
                    occurrence.message_occurrence_id
                    for occurrence in loaded.source_bundle.message_occurrences
                },
            )
            self.assertEqual(
                provider.unresolved_count,
                len(authorized_occurrence_ids - projected_occurrence_ids),
            )
            expected_references = {
                (
                    authorized_hash_by_id[observation_id],
                    lineage_by_id[observation_id].lineage_fingerprint,
                )
                for mention in matching_mentions
                for observation_id in mention.source_observation_ids
            }
            actual_references = {
                (citation_hash, lineage_fingerprint)
                for occurrence in provider.occurrences
                for (
                    normalized_hash,
                    variant_hash,
                    citation_hash,
                    lineage_fingerprint,
                ) in occurrence.value_bindings
                if shared_identifier_hash in {normalized_hash, variant_hash}
            }
            self.assertEqual(actual_references, expected_references)
            self.assertEqual(
                sum(
                    any(shared_identifier_hash in binding[:2] for binding in occurrence.value_bindings)
                    for occurrence in provider.occurrences
                ),
                len(matching_mentions),
            )

            routed_session = replace(
                loaded.session,
                source_occurrence_providers=providers,
            )
            cursor = None
            while True:
                result = routed_session.query(
                    query_text=f"list all {shared_identifier} messages",
                    effective_graph_view=loaded.effective_graph_view,
                    exact_inventory_kind="mail_message_occurrence",
                    page_size=100,
                    cursor=cursor,
                )
                assert result.exact_result is not None
                page = result.exact_result.source_occurrence_page
                assert page is not None
                cursor = page["next_cursor"]
                if cursor is None:
                    break
            self.assertEqual(result.status, "incomplete")
            self.assertEqual(page["coverage_status"], "incomplete")
            self.assertGreater(page["unresolved_count"], 0)

            source_observation = next(
                observation
                for observation in loaded.session.authorized_observations
                if observation.observation_type == "email_message"
            )
            extra_occurrence_id = (
                str(source_observation.location["message_occurrence_id"])
                + "_authorization_only"
            )
            extra_payload = dict(source_observation.payload or {})
            extra_payload["message_occurrence_id"] = extra_occurrence_id
            extra_payload["message_fingerprint"] = sha256_json(extra_occurrence_id)
            extra_location = dict(source_observation.location)
            extra_location["message_occurrence_id"] = extra_occurrence_id
            extra_observation = Observation.from_dict(
                {
                    **source_observation.to_dict(),
                    "observation_id": (
                        source_observation.observation_id + "_authorization_only"
                    ),
                    "location": extra_location,
                    "payload": extra_payload,
                }
            )
            assert loaded.session.authorized_source is not None
            extra_lineage = source_occurrence_lineage_from_observation(
                extra_observation,
                authorized_source=loaded.session.authorized_source,
            )
            extra_observation_hash = sha256_json(extra_observation.to_dict())
            expanded_session = replace(
                loaded.session,
                authorized_observations=tuple(
                    sorted(
                        (*loaded.session.authorized_observations, extra_observation),
                        key=lambda observation: observation.observation_id,
                    )
                ),
                authorized_observation_hashes=tuple(
                    sorted(
                        (
                            *loaded.session.authorized_observation_hashes,
                            (extra_observation.observation_id, extra_observation_hash),
                        )
                    )
                ),
                occurrence_lineages=tuple(
                    sorted(
                        (*loaded.session.occurrence_lineages, extra_lineage),
                        key=lambda lineage: lineage.source_observation_id,
                    )
                ),
            )
            with mock.patch.dict(
                os.environ,
                _loader_environment(package),
                clear=False,
            ):
                with self.assertRaisesRegex(
                    Exception,
                    "production direct source identifier occurrence scope is invalid",
                ):
                    gateway_loader._build_mail_source_occurrence_providers(
                        replace(loaded, session=expanded_session),
                        safe_binding=loaded.safe_binding,
                    )


def _prepare_package(
    root: Path,
    *,
    shared_direct_identifier: str | None = None,
) -> _PreparedPackage:
    fixture = _write_workspace_fixture(
        root / "source",
        shared_direct_identifier=shared_direct_identifier,
    )
    work_dir = root / "materialized"
    materialized = materializer.materialize_development_uat_observations(
        **materializer_fixture._build_kwargs(fixture, work_dir)
    )
    materialization_private_sha256 = _sha256_path(materialized.private_artifact_path)
    materialization_safe_sha256 = _sha256_path(materialized.safe_report_path)

    snapshot = fixture.snapshot
    attestation_root = root / "identity"
    _, safe_attestation = identity_attestation.create_identity_scope_attestation_artifacts(
        output_root=attestation_root,
        mode=identity_attestation.WORKSPACE_ONLY_MODE,
        workspace_id=sealed_source.WORKSPACE_ID,
        tenant_id=None,
        asset_id=snapshot["source_inventory"]["source_asset_id"],
        asset_content_hash=snapshot["source_asset_sha256"],
        source_fingerprint=snapshot["source_snapshot_fingerprint"],
        permission_fingerprint=snapshot["permission_fingerprint"],
        approver_actor=sealed_source.APPROVER_ACTOR,
        authority_source="issue56_fixture_explicit_operator_approval",
        approved_at=CREATED_AT,
        reason="Synthetic sealed-source loader contract fixture approval.",
        operator_approved=True,
        spec_approval_id="issue56_fixture_workspace_only_spec_approval",
    )
    attestation_private_path = attestation_root / identity_attestation.PRIVATE_ARTIFACT_FILENAME
    attestation_safe_path = attestation_root / identity_attestation.SAFE_REPORT_FILENAME

    candidate_root = root / "candidates"
    candidates = candidate_builder.build_source_identifier_candidate_artifacts(
        retrieval_snapshot_path=fixture.snapshot_path,
        expected_retrieval_snapshot_sha256=fixture.snapshot_sha256,
        retrieval_report_path=fixture.report_path,
        expected_retrieval_report_sha256=fixture.report_sha256,
        identity_scope_attestation_path=attestation_private_path,
        expected_identity_scope_attestation_sha256=_sha256_path(attestation_private_path),
        materialized_work_dir=work_dir,
        expected_materialization_artifact_sha256=(materialization_private_sha256),
        expected_materialization_safe_report_sha256=(materialization_safe_sha256),
        output_root=candidate_root,
    )
    return _PreparedPackage(
        fixture=fixture,
        work_dir=work_dir,
        materialization_private_sha256=materialization_private_sha256,
        materialization_safe_sha256=materialization_safe_sha256,
        attestation_root=attestation_root,
        attestation_private_sha256=_sha256_path(attestation_private_path),
        attestation_safe_sha256=_sha256_path(attestation_safe_path),
        identity_scope_fingerprint=safe_attestation["identity_scope_fingerprint"],
        candidate_root=candidate_root,
        candidate_private_sha256=_sha256_path(candidates.private_artifact_path),
        candidate_safe_sha256=_sha256_path(candidates.safe_report_path),
    )


def _write_workspace_fixture(
    root: Path,
    *,
    shared_direct_identifier: str | None = None,
) -> object:
    fixture = materializer_fixture._write_fixture(root, body_count=500)
    snapshot = deepcopy(fixture.snapshot)
    manifest = deepcopy(fixture.manifest)
    old_inventory = SourceInventory.from_dict(snapshot["source_inventory"])
    item_id_map: dict[str, str] = {}
    new_items: list[SourceInventoryItem] = []
    for old_item in old_inventory.items:
        new_item = SourceInventoryItem.create(
            source_asset_id=old_item.source_asset_id,
            structure_kind=old_item.structure_kind,
            content_type=old_item.content_type,
            ordinal=old_item.ordinal,
            processing_state=old_item.processing_state,
            raw_retention_state=old_item.raw_retention_state,
            source_fingerprint=old_item.source_fingerprint,
            parser_fingerprint=old_item.parser_fingerprint,
            permission_scope=WORKSPACE_PERMISSION_SCOPE.to_dict(),
            location=old_item.location,
        )
        item_id_map[old_item.source_inventory_item_id] = new_item.source_inventory_item_id
        new_items.append(new_item)
    new_inventory = SourceInventory.create(
        source_asset_id=old_inventory.source_asset_id,
        items=new_items,
        source_fingerprint=old_inventory.source_fingerprint,
        parser_fingerprint=old_inventory.parser_fingerprint,
        created_at=old_inventory.created_at,
    )

    observations: list[Observation] = []
    for raw_observation in snapshot["parsed_mail_observations"]:
        row = deepcopy(raw_observation)
        if shared_direct_identifier is not None and row["observation_type"] == "email_body_segment":
            ordinal = int(str(row["observation_id"]).rsplit("_", 1)[1])
            if ordinal == 1 or ordinal > 200:
                row["text"] = (
                    f"Synthetic evidence segment {ordinal:04d} "
                    f"references {shared_direct_identifier}."
                )
        row["permission_scope"] = WORKSPACE_PERMISSION_SCOPE.to_dict()
        row["location"]["source_inventory_item_id"] = item_id_map[
            row["location"]["source_inventory_item_id"]
        ]
        observations.append(Observation.from_dict(row))

    bundle = build_mail_evidence_bundle(
        observations,
        workspace_id=sealed_source.WORKSPACE_ID,
        owner_user_id=sealed_source.APPROVER_ACTOR,
        source_asset_id=old_inventory.source_asset_id,
        archive_sha256=snapshot["source_asset_sha256"],
        producer_type="server_side_parser",
        parser_name="fixture_parser",
        parser_version="1",
        upload_session_id="upload_issue56_sealed_source_loader",
        created_at=materializer_fixture.CREATED_AT,
        started_at=materializer_fixture.CREATED_AT,
        completed_at=materializer_fixture.CREATED_AT,
    )
    bundle_payload = bundle.to_dict()
    bundle_artifact = {
        "artifact_id": "formowl_issue56_native_mail_evidence_bundle_v1",
        "schema_version": 1,
        "status": "passed",
        "source_snapshot_fingerprint": snapshot["source_snapshot_fingerprint"],
        "source_inventory_fingerprint": sha256_json(new_inventory.to_dict()),
        "source_provenance_fingerprint": snapshot["source_provenance_fingerprint"],
        "bundle": bundle_payload,
        "bundle_fingerprint": sha256_json(bundle_payload),
    }
    bundle_artifact["artifact_fingerprint"] = _payload_fingerprint(
        bundle_artifact,
        "artifact_fingerprint",
    )

    snapshot["source_inventory"] = new_inventory.to_dict()
    snapshot["source_inventory_fingerprint"] = sha256_json(new_inventory.to_dict())
    snapshot["permission_fingerprint"] = sha256_json(WORKSPACE_PERMISSION_SCOPE.to_dict())
    snapshot["parsed_mail_observations"] = [observation.to_dict() for observation in observations]
    snapshot["parsed_observation_fingerprint"] = sha256_json(snapshot["parsed_mail_observations"])
    snapshot["mail_evidence_bundle_fingerprint"] = bundle_artifact["bundle_fingerprint"]
    snapshot["snapshot_fingerprint"] = _payload_fingerprint(
        snapshot,
        "snapshot_fingerprint",
    )

    report = deepcopy(fixture.retrieval_report)
    report_bindings = {
        "source_snapshot_fingerprint": snapshot["source_snapshot_fingerprint"],
        "source_inventory_fingerprint": snapshot["source_inventory_fingerprint"],
        "source_provenance_fingerprint": snapshot["source_provenance_fingerprint"],
        "permission_fingerprint": snapshot["permission_fingerprint"],
        "parsed_observation_fingerprint": snapshot["parsed_observation_fingerprint"],
        "mail_evidence_bundle_fingerprint": bundle_artifact["bundle_fingerprint"],
        "candidate_admission_profile_fingerprint": snapshot["tokenizer_profile_fingerprint"],
        "retrieval_snapshot_fingerprint": snapshot["snapshot_fingerprint"],
        "bundle_artifact_fingerprint": bundle_artifact["artifact_fingerprint"],
    }
    report.update(report_bindings)
    report["report_fingerprint"] = _payload_fingerprint(
        report,
        "report_fingerprint",
    )

    observation_by_id = {observation.observation_id: observation for observation in observations}
    for case in manifest["cases"]:
        case["requester_user_id"] = sealed_source.APPROVER_ACTOR
        selected = [
            observation_by_id[observation_id]
            for observation_id in case["required_source_observation_ids"]
        ]
        case["source_evidence_binding"]["required_observation_hashes"] = sorted(
            sha256_json(observation.to_dict()) for observation in selected
        )
        case["private_fingerprint"] = _payload_fingerprint(
            case,
            "private_fingerprint",
        )

    snapshot_bytes = _json_bytes(snapshot)
    bundle_bytes = _json_bytes(bundle_artifact)
    report_bytes = _json_bytes(report)
    manifest["mail_evidence_bundle_id"] = bundle.mail_evidence_bundle_id
    manifest["mail_import_session_id"] = bundle.mail_import_session.mail_import_session_id
    manifest["archive_sha256"] = bundle.mail_import_session.archive_sha256
    manifest["source_bindings"].update(
        {
            "bundle_artifact_byte_hash": _sha256_bytes(bundle_bytes),
            "bundle_artifact_fingerprint": bundle_artifact["artifact_fingerprint"],
            "mail_evidence_bundle_fingerprint": bundle_artifact["bundle_fingerprint"],
            "retrieval_snapshot_byte_hash": _sha256_bytes(snapshot_bytes),
            "retrieval_snapshot_fingerprint": snapshot["snapshot_fingerprint"],
            "source_snapshot_fingerprint": snapshot["source_snapshot_fingerprint"],
            "source_inventory_fingerprint": snapshot["source_inventory_fingerprint"],
            "source_provenance_fingerprint": snapshot["source_provenance_fingerprint"],
            "permission_fingerprint": snapshot["permission_fingerprint"],
            "tokenizer_profile_fingerprint": snapshot["tokenizer_profile_fingerprint"],
            "index_fingerprint": snapshot["index_fingerprint"],
            "retrieval_report_byte_hash": _sha256_bytes(report_bytes),
        }
    )
    manifest["manifest_fingerprint"] = _payload_fingerprint(
        manifest,
        "manifest_fingerprint",
    )
    fixture.snapshot_path.write_bytes(snapshot_bytes)
    fixture.bundle_path.write_bytes(bundle_bytes)
    fixture.report_path.write_bytes(report_bytes)
    fixture.manifest_path.write_bytes(_json_bytes(manifest))
    return materializer_fixture._Fixture(
        snapshot_path=fixture.snapshot_path,
        bundle_path=fixture.bundle_path,
        report_path=fixture.report_path,
        manifest_path=fixture.manifest_path,
        snapshot=snapshot,
        bundle_artifact=bundle_artifact,
        retrieval_report=report,
        manifest=manifest,
    )


def _loader_kwargs(package: _PreparedPackage) -> dict[str, object]:
    fixture = package.fixture
    return {
        "retrieval_snapshot_path": fixture.snapshot_path,
        "expected_retrieval_snapshot_sha256": fixture.snapshot_sha256,
        "bundle_artifact_path": fixture.bundle_path,
        "expected_bundle_artifact_sha256": fixture.bundle_sha256,
        "retrieval_report_path": fixture.report_path,
        "expected_retrieval_report_sha256": fixture.report_sha256,
        "materialized_work_dir": package.work_dir,
        "expected_materialization_artifact_sha256": (package.materialization_private_sha256),
        "expected_materialization_safe_report_sha256": (package.materialization_safe_sha256),
        "identity_scope_attestation_path": (
            package.attestation_root / identity_attestation.PRIVATE_ARTIFACT_FILENAME
        ),
        "expected_identity_scope_attestation_sha256": (package.attestation_private_sha256),
        "identity_scope_safe_report_path": (
            package.attestation_root / identity_attestation.SAFE_REPORT_FILENAME
        ),
        "expected_identity_scope_safe_report_sha256": (package.attestation_safe_sha256),
        "source_identifier_candidate_artifact_path": (
            package.candidate_root / candidate_builder.PRIVATE_ARTIFACT_FILENAME
        ),
        "expected_source_identifier_candidate_artifact_sha256": (package.candidate_private_sha256),
        "source_identifier_candidate_safe_report_path": (
            package.candidate_root / candidate_builder.SAFE_REPORT_FILENAME
        ),
        "expected_source_identifier_candidate_safe_report_sha256": (package.candidate_safe_sha256),
        "expected_identity_scope_fingerprint": (package.identity_scope_fingerprint),
        "identity_scope_mode": sealed_source.IDENTITY_SCOPE_MODE,
        "workspace_id": sealed_source.WORKSPACE_ID,
        "approver_actor": sealed_source.APPROVER_ACTOR,
        "requester_user_id": sealed_source.APPROVER_ACTOR,
    }


def _loader_environment(package: _PreparedPackage) -> dict[str, str]:
    kwargs = _loader_kwargs(package)
    return {
        environment_name: str(kwargs[field_name])
        for field_name, environment_name in gateway_loader._ENVIRONMENT_FIELDS.items()
    }


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _payload_fingerprint(
    payload: dict[str, object],
    fingerprint_field: str,
) -> str:
    return sha256_json({key: value for key, value in payload.items() if key != fingerprint_field})


def _sha256_bytes(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


if __name__ == "__main__":
    unittest.main()
