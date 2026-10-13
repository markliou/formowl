from __future__ import annotations

from dataclasses import replace
import importlib
from types import SimpleNamespace
import unittest

import _paths  # noqa: F401

from formowl_contract import (
    AdmissibleSemanticScope,
    ContractValidationError,
    CoverageScopeAuthorityVerifier,
    SemanticSchemaAliasMap,
    SourceInventory,
    SourceInventoryItem,
    StructuralCell,
    StructuralColumn,
    StructuralObservation,
    StructuralRow,
    stable_resource_contract_id,
)
from formowl_graph.task_answering import TaskAnsweringEngine
from formowl_mail.diagnostic_mcp import (
    DiagnosticSemanticProfile,
    _ResolvedSemanticScope,
    _derive_runtime_query_scope,
)
from formowl_mail.diagnostic_structural_bridge import _build_structural_semantic_bindings
from formowl_mail.persistence import DIAGNOSTIC_STRUCTURAL_BASELINE_SCOPE_KIND
from formowl_mail.query import StructuralObservationMatchFact


_CREATED_AT = "2026-08-12T00:00:00+00:00"
_SOURCE_FINGERPRINT = "sha256:" + ("1" * 64)
_PARSER_FINGERPRINT = "sha256:" + ("2" * 64)
_AUTHORITY_ROOT = b"track1-legacy-diagnostic-structural-canary"


def _profile() -> DiagnosticSemanticProfile:
    aliases = SemanticSchemaAliasMap(
        object_aliases={"html_table": ("html table", "table")},
        predicate_aliases={
            "coo": ("COO", "country of origin"),
            "p/n": ("P/N", "part number"),
        },
        value_aliases={},
        value_domains={
            "coo": "open_public_value",
            "p/n": "open_public_value",
        },
    )
    fingerprint = DiagnosticSemanticProfile.fingerprint_for(
        profile_id="track1-legacy-canary",
        profile_version="1",
        schema_alias_map=aliases,
        workspace_id="workspace-track1-canary",
        owner_user_id="owner-track1-canary",
        actor_context_id="actor-track1-canary",
        known_as_of=_CREATED_AT,
    )
    return DiagnosticSemanticProfile(
        profile_id="track1-legacy-canary",
        profile_version="1",
        profile_fingerprint=fingerprint,
        schema_alias_map=aliases,
        workspace_id="workspace-track1-canary",
        owner_user_id="owner-track1-canary",
        actor_context_id="actor-track1-canary",
        known_as_of=_CREATED_AT,
    )


def _inventory_and_observation() -> tuple[SourceInventory, StructuralObservation]:
    item = SourceInventoryItem.create(
        source_asset_id="asset-track1-legacy-canary",
        structure_kind="html_table",
        content_type="text/html",
        ordinal=0,
        processing_state="parsed",
        raw_retention_state="retained",
        source_fingerprint=_SOURCE_FINGERPRINT,
        parser_fingerprint=_PARSER_FINGERPRINT,
        permission_scope={
            "scope_type": "asset",
            "scope_id": "asset-track1-legacy-canary",
            "visibility": "restricted",
        },
        source_observation_ids=("observation-track1-legacy-canary",),
    )
    inventory = SourceInventory.create(
        source_asset_id=item.source_asset_id,
        source_fingerprint=item.source_fingerprint,
        parser_fingerprint=item.parser_fingerprint,
        items=(item,),
        created_at=_CREATED_AT,
    )
    bound_item = inventory.items[0]
    observation = StructuralObservation.create(
        source_inventory_item_id=bound_item.source_inventory_item_id,
        source_asset_id=bound_item.source_asset_id,
        source_observation_id="observation-track1-legacy-canary",
        structure_kind="html_table",
        columns=(
            StructuralColumn(
                column_ordinal=0,
                original_header="COO",
                normalized_header="coo",
            ),
            StructuralColumn(
                column_ordinal=1,
                original_header="P/N",
                normalized_header="p/n",
            ),
        ),
        rows=(
            StructuralRow(
                row_ordinal=0,
                cells=(
                    StructuralCell(
                        cell_state="populated",
                        row_ordinal=0,
                        column_ordinal=0,
                        value="Japan",
                        normalized_value="japan",
                    ),
                    StructuralCell(
                        cell_state="populated",
                        row_ordinal=0,
                        column_ordinal=1,
                        value="synthetic-part-001",
                        normalized_value="synthetic-part-001",
                    ),
                ),
            ),
        ),
        header_relationships=(),
        source_fingerprint=_SOURCE_FINGERPRINT,
        parser_fingerprint=_PARSER_FINGERPRINT,
    )
    return inventory, observation


def _legacy_scopes() -> (
    tuple[
        _ResolvedSemanticScope,
        _ResolvedSemanticScope,
        CoverageScopeAuthorityVerifier,
        StructuralObservation,
    ]
):
    profile = _profile()
    verifier = CoverageScopeAuthorityVerifier.from_external_root(_AUTHORITY_ROOT)
    inventory, observation = _inventory_and_observation()
    requirements, ledgers, manifests, authorities = _build_structural_semantic_bindings(
        source_inventory=inventory,
        structural_observations=(observation,),
        workspace_id=profile.workspace_id,
        owner_user_id=profile.owner_user_id,
        source_asset_id=inventory.source_asset_id,
        source_fingerprint=inventory.source_fingerprint,
        parser_name="synthetic-legacy-parser",
        parser_version="1",
        created_at=_CREATED_AT,
        scope_authority_verifier=verifier,
        semantic_profile=profile,
        existing_export_verification=None,
    )
    requirement = requirements[0]
    ledger = ledgers[0]
    manifest = manifests[0]
    authority = next(iter(authorities.values()))
    if ledger.authorization_binding is None:
        raise AssertionError("synthetic legacy ledger has no authorization binding")
    baseline_scope = _ResolvedSemanticScope(
        bundle=object(),  # type: ignore[arg-type]
        coverage_ledger=ledger,
        claim_requirement=requirement,
        source_inventory=inventory,
        version_manifest=manifest,
        scope_authority=authority,
        authorization_binding=ledger.authorization_binding,
        structural_observations=(observation,),
        authorized_inventory_item_ids=(inventory.items[0].source_inventory_item_id,),
        admissibility=AdmissibleSemanticScope(
            permission_admissible=True,
            source_admissible=True,
            version_admissible=True,
            context_admissible=True,
            time_admissible=True,
            status_admissible=True,
        ),
    )
    runtime_scope = _derive_runtime_query_scope(
        baseline_scope=baseline_scope,
        plan=SimpleNamespace(
            object_type="html_table",
            predicate="coo",
            page_size=10,
        ),
        authority_verifier=verifier,
    )
    return baseline_scope, runtime_scope, verifier, observation


def _issued_capability() -> (
    tuple[
        object,
        tuple[object, ...],
        object,
        _ResolvedSemanticScope,
        StructuralObservation,
    ]
):
    _baseline_scope, runtime_scope, _verifier, observation = _legacy_scopes()
    observations = (observation,)
    identity_bindings = (object(), object(), object(), object(), object())
    topology_attestation = (
        TaskAnsweringEngine._prepare_prevalidated_diagnostic_topology_attestation(
            identity_binding=identity_bindings[-1],
            structural_observations=observations,
        )
    )
    capability = TaskAnsweringEngine._prepare_prevalidated_diagnostic_structured_capability(
        identity_bindings=identity_bindings,
        topology_attestation=topology_attestation,
        coverage_ledger=runtime_scope.coverage_ledger,
        claim_requirement=runtime_scope.claim_requirement,
        source_inventory=runtime_scope.source_inventory,
        version_manifest=runtime_scope.version_manifest,
        scope_authority=runtime_scope.scope_authority,
        authorization_binding=runtime_scope.authorization_binding,
        structural_observations=observations,
    )
    return capability, identity_bindings, topology_attestation, runtime_scope, observation


class LegacyDiagnosticStructuralShardCanaryTests(unittest.TestCase):
    def test_legacy_compact_baseline_imports_and_executes_without_pst_io(self) -> None:
        pst = importlib.import_module("formowl_ingestion.extractors.mail.pst")
        bridge = importlib.import_module("formowl_mail.diagnostic_structural_bridge")
        required_pst_abi = (
            "PST_INVENTORY_CARRIER_OBSERVATION_TYPE",
            "PST_SOURCE_UNIT_OBSERVATION_TYPE",
            "PST_READPST_PARALLEL_JOBS",
            "PstMailArchiveExtractor",
            "PstReadpstMessageSelector",
            "_parser_config",
            "_pst_parser_fingerprint",
            "_PST_SOURCE_UNIT_ATTACHMENT",
            "_PST_SOURCE_UNIT_MESSAGE",
            "_PST_SOURCE_UNIT_SIDECAR",
            "_source_unit_kind_for_path",
            "export_pst_to_readpst_directory",
            "extract_readpst_export",
            "extract_selected_readpst_export",
            "select_readpst_export_messages",
        )
        self.assertTrue(all(hasattr(pst, name) for name in required_pst_abi))
        self.assertTrue(callable(bridge._build_structural_semantic_bindings))

        baseline_scope, _runtime_scope, _verifier, _observation = _legacy_scopes()
        self.assertEqual(
            baseline_scope.claim_requirement.query_id,
            stable_resource_contract_id(
                "query",
                "DiagnosticCompactBaseline",
                {"source_inventory_id": baseline_scope.source_inventory.source_inventory_id},
            ),
        )
        self.assertEqual(
            baseline_scope.claim_requirement.parameters["scope_kind"],
            DIAGNOSTIC_STRUCTURAL_BASELINE_SCOPE_KIND,
        )

        capability, _bindings, _attestation, scope, observation = _issued_capability()
        self.assertTrue(scope.coverage_ledger.complete_authorized_scope)
        fact = StructuralObservationMatchFact(
            source_observation_id=observation.source_observation_id,
            structural_observation_id=observation.structural_observation_id,
            source_inventory_item_id=observation.source_inventory_item_id,
            matched_row_ordinals=(0,),
        )
        outcome = TaskAnsweringEngine._answer_prevalidated_diagnostic_structured_claim(
            capability=capability,
            structural_observations=(observation,),
            matched_structural_facts=(fact,),
        )
        self.assertEqual(outcome.status, "ok")
        self.assertEqual(outcome.canonical_values, ("Japan",))

    def test_cloned_topology_is_not_accepted_as_the_issued_tuple(self) -> None:
        _capability, bindings, attestation, scope, observation = _issued_capability()
        cloned_observations = (replace(observation),)

        self.assertFalse(
            TaskAnsweringEngine._prevalidated_diagnostic_topology_attestation_is_valid(
                attestation,
                identity_binding=bindings[-1],
                structural_observations=cloned_observations,
            )
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "prevalidated diagnostic capability is invalid",
        ):
            TaskAnsweringEngine._prepare_prevalidated_diagnostic_structured_capability(
                identity_bindings=bindings,
                topology_attestation=attestation,
                coverage_ledger=scope.coverage_ledger,
                claim_requirement=scope.claim_requirement,
                source_inventory=scope.source_inventory,
                version_manifest=scope.version_manifest,
                scope_authority=scope.scope_authority,
                authorization_binding=scope.authorization_binding,
                structural_observations=cloned_observations,
            )

    def test_forged_capability_clone_is_rejected(self) -> None:
        capability, bindings, attestation, scope, observation = _issued_capability()
        forged_capability = replace(capability)

        self.assertFalse(
            TaskAnsweringEngine._prevalidated_diagnostic_capability_is_valid(
                forged_capability,
                identity_bindings=bindings,
                topology_attestation=attestation,
                structural_observations=(observation,),
                coverage_ledger=scope.coverage_ledger,
                claim_requirement=scope.claim_requirement,
                source_inventory=scope.source_inventory,
                version_manifest=scope.version_manifest,
                scope_authority=scope.scope_authority,
                authorization_binding=scope.authorization_binding,
            )
        )
        outcome = TaskAnsweringEngine._answer_prevalidated_diagnostic_structured_claim(
            capability=forged_capability,
            structural_observations=(observation,),
            matched_structural_facts=(),
        )
        self.assertEqual(outcome.status, "error")
        self.assertIsNotNone(outcome.error)
        self.assertEqual(outcome.error.code, "invalid_binding")  # type: ignore[union-attr]

    def test_forged_structural_fact_is_rejected(self) -> None:
        capability, _bindings, _attestation, _scope, observation = _issued_capability()
        forged_fact = StructuralObservationMatchFact(
            source_observation_id=observation.source_observation_id,
            structural_observation_id=stable_resource_contract_id(
                "structobs",
                "ForgedStructuralObservation",
                {"synthetic": True},
            ),
            source_inventory_item_id=observation.source_inventory_item_id,
            matched_row_ordinals=(0,),
        )
        outcome = TaskAnsweringEngine._answer_prevalidated_diagnostic_structured_claim(
            capability=capability,
            structural_observations=(observation,),
            matched_structural_facts=(forged_fact,),
        )
        self.assertEqual(outcome.status, "error")
        self.assertIsNotNone(outcome.error)
        self.assertEqual(outcome.error.code, "invalid_evidence")  # type: ignore[union-attr]


if __name__ == "__main__":
    unittest.main()
