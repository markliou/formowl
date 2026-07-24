from __future__ import annotations

from dataclasses import replace
import unittest

import _paths  # noqa: F401

from formowl_contract import (
    ClaimRequirement,
    ContractValidationError,
    CoverageAuthorizationBinding,
    CoverageLedger,
    CoverageObservationPartition,
    CoverageProofRecord,
    CoverageScopePartition,
    CoverageVersionBinding,
    SourceInventory,
    SourceInventoryItem,
    VersionManifest,
)
from formowl_mail import MailEvidenceBundle
from formowl_mail import PostgreSQLMailEvidenceStore


FP = "sha256:" + "a" * 64
FP2 = "sha256:" + "b" * 64


class CoverageScopePartitionTests(unittest.TestCase):
    def test_complete_scope_requires_the_total_independent_partition(self) -> None:
        inventory, requirement, manifest, authorization, partition, proofs = _fixture()
        ledger = _complete_ledger(
            inventory,
            requirement,
            manifest,
            authorization,
            partition,
            proofs,
        )
        self.assertTrue(ledger.usable_for_claim(inventory, requirement, manifest, authorization))

        missing_relevant = CoverageScopePartition.create(
            source_inventory=inventory,
            claim_requirement=requirement,
            authorization_binding=authorization,
            version_manifest=manifest,
            authorized_relevant_item_ids=(inventory.items[0].source_inventory_item_id,),
            authorized_irrelevant_item_ids=(inventory.items[2].source_inventory_item_id,),
            ineligible_item_ids=(inventory.items[3].source_inventory_item_id,),
            observation_partitions=(partition.observation_partitions[0],),
        )
        incomplete_partition_ledger = CoverageLedger.create(
            query_id=requirement.query_id,
            claim_requirement_id=requirement.claim_requirement_id,
            source_inventory_id=inventory.source_inventory_id,
            relevant_inventory_item_ids=(inventory.items[0].source_inventory_item_id,),
            searched_structural_observation_ids=("obs_a_struct",),
            searched_ordinary_observation_ids=("obs_a_ordinary",),
            authorization_binding=authorization,
            version_binding=CoverageVersionBinding.from_manifest(manifest),
            scope_partition=missing_relevant,
            proof_records=(proofs[0],),
            complete_authorized_scope=True,
        )
        self.assertFalse(
            incomplete_partition_ledger.usable_for_claim(
                inventory,
                requirement,
                manifest,
                authorization,
            )
        )

    def test_explicit_irrelevant_and_ineligible_items_are_not_searchable(self) -> None:
        inventory, requirement, manifest, authorization, partition, proofs = _fixture()
        ledger = _complete_ledger(
            inventory,
            requirement,
            manifest,
            authorization,
            partition,
            proofs,
        )
        self.assertEqual(
            set(partition.authorized_irrelevant_item_ids),
            {inventory.items[2].source_inventory_item_id},
        )
        self.assertEqual(
            set(partition.ineligible_item_ids),
            {inventory.items[3].source_inventory_item_id},
        )
        self.assertTrue(ledger.usable_for_claim(inventory, requirement, manifest, authorization))

        with self.assertRaises(ContractValidationError):
            CoverageLedger.create(
                query_id=requirement.query_id,
                claim_requirement_id=requirement.claim_requirement_id,
                source_inventory_id=inventory.source_inventory_id,
                relevant_inventory_item_ids=(
                    inventory.items[0].source_inventory_item_id,
                    inventory.items[2].source_inventory_item_id,
                ),
                authorization_binding=authorization,
                version_binding=CoverageVersionBinding.from_manifest(manifest),
                scope_partition=partition,
                proof_records=proofs,
                complete_authorized_scope=False,
            )

    def test_partition_bindings_and_malformed_item_partitions_fail_closed(self) -> None:
        inventory, requirement, manifest, authorization, partition, proofs = _fixture()
        ledger = _complete_ledger(
            inventory,
            requirement,
            manifest,
            authorization,
            partition,
            proofs,
        )
        self.assertFalse(
            ledger.usable_for_claim(
                inventory,
                requirement,
                manifest,
                replace(authorization, grant_revision=FP2),
            )
        )
        self.assertFalse(
            ledger.usable_for_claim(
                inventory,
                requirement,
                replace(manifest, index_fingerprint=FP2),
                authorization,
            )
        )

        with self.assertRaises(ContractValidationError):
            CoverageObservationPartition(
                inventory_item_id=inventory.items[0].source_inventory_item_id,
                structural_observation_ids=("obs_a_struct", "obs_a_struct"),
            )
        with self.assertRaises(ContractValidationError):
            CoverageObservationPartition(
                inventory_item_id=inventory.items[0].source_inventory_item_id,
                structural_observation_ids=("obs_a_struct",),
                ordinary_observation_ids=("obs_a_struct",),
            )
        with self.assertRaises(ContractValidationError):
            CoverageProofRecord.create(
                source_inventory_id=inventory.source_inventory_id,
                claim_requirement_id=requirement.claim_requirement_id,
                version_manifest_id=manifest.version_manifest_id,
                inventory_item_id=inventory.items[0].source_inventory_item_id,
                proof_kind="combined",
                structural_observation_ids=("obs_a_struct",),
                ordinary_observation_ids=("obs_a_struct",),
            )
        with self.assertRaises(ContractValidationError):
            CoverageScopePartition(
                source_inventory_id=inventory.source_inventory_id,
                claim_requirement_id=requirement.claim_requirement_id,
                authorization_binding=authorization,
                version_binding=CoverageVersionBinding.from_manifest(manifest),
                authorized_relevant_item_ids=(
                    inventory.items[0].source_inventory_item_id,
                    inventory.items[0].source_inventory_item_id,
                ),
                authorized_irrelevant_item_ids=(),
                ineligible_item_ids=(),
                observation_partitions=(),
            )
        with self.assertRaises(ContractValidationError):
            CoverageScopePartition(
                source_inventory_id=inventory.source_inventory_id,
                claim_requirement_id=requirement.claim_requirement_id,
                authorization_binding=authorization,
                version_binding=CoverageVersionBinding.from_manifest(manifest),
                authorized_relevant_item_ids=(inventory.items[0].source_inventory_item_id,),
                authorized_irrelevant_item_ids=(inventory.items[0].source_inventory_item_id,),
                ineligible_item_ids=(),
                observation_partitions=(),
            )
        unknown_item_partition = CoverageScopePartition.create(
            source_inventory=inventory,
            claim_requirement=requirement,
            authorization_binding=authorization,
            version_manifest=manifest,
            authorized_relevant_item_ids=("item_unknown",),
            authorized_irrelevant_item_ids=(inventory.items[2].source_inventory_item_id,),
            ineligible_item_ids=(inventory.items[3].source_inventory_item_id,),
            observation_partitions=(
                CoverageObservationPartition(
                    inventory_item_id="item_unknown",
                    structural_observation_ids=("obs_a_struct",),
                ),
            ),
        )
        unknown_item_ledger = CoverageLedger.create(
            query_id=requirement.query_id,
            claim_requirement_id=requirement.claim_requirement_id,
            source_inventory_id=inventory.source_inventory_id,
            relevant_inventory_item_ids=("item_unknown",),
            searched_structural_observation_ids=("obs_a_struct",),
            authorization_binding=authorization,
            version_binding=CoverageVersionBinding.from_manifest(manifest),
            scope_partition=unknown_item_partition,
            proof_records=(
                CoverageProofRecord.create(
                    source_inventory_id=inventory.source_inventory_id,
                    claim_requirement_id=requirement.claim_requirement_id,
                    version_manifest_id=manifest.version_manifest_id,
                    inventory_item_id="item_unknown",
                    proof_kind="structural",
                    structural_observation_ids=("obs_a_struct",),
                ),
            ),
            complete_authorized_scope=True,
        )
        self.assertFalse(
            unknown_item_ledger.usable_for_claim(
                inventory,
                requirement,
                manifest,
                authorization,
            )
        )

    def test_observation_accounting_is_total_and_exact(self) -> None:
        inventory, requirement, manifest, authorization, partition, proofs = _fixture()
        with self.assertRaises(ContractValidationError):
            _complete_ledger(
                inventory,
                requirement,
                manifest,
                authorization,
                partition,
                (replace(proofs[0], ordinary_observation_ids=()), proofs[1]),
                searched_ordinary=(),
            )
        with self.assertRaises(ContractValidationError):
            CoverageLedger.create(
                query_id=requirement.query_id,
                claim_requirement_id=requirement.claim_requirement_id,
                source_inventory_id=inventory.source_inventory_id,
                relevant_inventory_item_ids=partition.authorized_relevant_item_ids,
                searched_structural_observation_ids=("obs_a_struct",),
                searched_ordinary_observation_ids=("obs_a_struct",),
                authorization_binding=authorization,
                version_binding=CoverageVersionBinding.from_manifest(manifest),
                scope_partition=partition,
                proof_records=proofs,
                complete_authorized_scope=False,
            )

        with self.assertRaises(ContractValidationError):
            _complete_ledger(
                inventory,
                requirement,
                manifest,
                authorization,
                partition,
                proofs,
                searched_ordinary=(),
            )

        wrong_item_partition = CoverageScopePartition.create(
            source_inventory=inventory,
            claim_requirement=requirement,
            authorization_binding=authorization,
            version_manifest=manifest,
            authorized_relevant_item_ids=(
                inventory.items[0].source_inventory_item_id,
                inventory.items[1].source_inventory_item_id,
            ),
            authorized_irrelevant_item_ids=(inventory.items[2].source_inventory_item_id,),
            ineligible_item_ids=(inventory.items[3].source_inventory_item_id,),
            observation_partitions=(
                CoverageObservationPartition(
                    inventory_item_id=inventory.items[0].source_inventory_item_id,
                    structural_observation_ids=("obs_b_struct",),
                    ordinary_observation_ids=("obs_a_ordinary",),
                ),
                CoverageObservationPartition(
                    inventory_item_id=inventory.items[1].source_inventory_item_id,
                ),
            ),
        )
        wrong_item_ledger = CoverageLedger.create(
            query_id=requirement.query_id,
            claim_requirement_id=requirement.claim_requirement_id,
            source_inventory_id=inventory.source_inventory_id,
            relevant_inventory_item_ids=wrong_item_partition.authorized_relevant_item_ids,
            searched_structural_observation_ids=("obs_b_struct",),
            searched_ordinary_observation_ids=("obs_a_ordinary",),
            authorization_binding=authorization,
            version_binding=CoverageVersionBinding.from_manifest(manifest),
            scope_partition=wrong_item_partition,
            proof_records=(
                replace(proofs[0], structural_observation_ids=("obs_b_struct",)),
                replace(proofs[1], proof_kind="fallback", structural_observation_ids=()),
            ),
            complete_authorized_scope=True,
        )
        self.assertFalse(
            wrong_item_ledger.usable_for_claim(
                inventory,
                requirement,
                manifest,
                authorization,
            )
        )

    def test_scope_partition_and_bundle_round_trip_are_deterministic(self) -> None:
        inventory, requirement, manifest, authorization, partition, proofs = _fixture()
        reversed_partition = CoverageScopePartition.create(
            source_inventory=inventory,
            claim_requirement=requirement,
            authorization_binding=authorization,
            version_manifest=manifest,
            authorized_relevant_item_ids=tuple(reversed(partition.authorized_relevant_item_ids)),
            authorized_irrelevant_item_ids=tuple(
                reversed(partition.authorized_irrelevant_item_ids)
            ),
            ineligible_item_ids=tuple(reversed(partition.ineligible_item_ids)),
            observation_partitions=tuple(
                replace(
                    item,
                    structural_observation_ids=tuple(reversed(item.structural_observation_ids)),
                    ordinary_observation_ids=tuple(reversed(item.ordinary_observation_ids)),
                )
                for item in reversed(partition.observation_partitions)
            ),
        )
        self.assertEqual(
            partition.scope_partition_id,
            reversed_partition.scope_partition_id,
        )
        self.assertEqual(
            partition.to_persistence_dict(),
            CoverageScopePartition.from_persistence_dict(
                partition.to_persistence_dict()
            ).to_persistence_dict(),
        )

        ledger = _complete_ledger(
            inventory,
            requirement,
            manifest,
            authorization,
            partition,
            proofs,
        )
        self.assertEqual(
            ledger.to_persistence_dict(),
            CoverageLedger.from_persistence_dict(
                ledger.to_persistence_dict()
            ).to_persistence_dict(),
        )

        bundle = _bundle_with_ledger(inventory, requirement, manifest, ledger)
        restored = MailEvidenceBundle.from_persistence_dict(bundle.to_persistence_dict())
        self.assertEqual(
            restored.coverage_ledgers[0].to_persistence_dict(),
            ledger.to_persistence_dict(),
        )

        from test_mail_evidence_postgres import _RecordingMailConnection

        connection = _RecordingMailConnection()
        PostgreSQLMailEvidenceStore(connection).upsert_bundle(bundle)
        postgres_restored = PostgreSQLMailEvidenceStore(connection).get_bundle(
            mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
        )
        self.assertIsNotNone(postgres_restored)
        self.assertEqual(
            postgres_restored.coverage_ledgers[0].to_persistence_dict(),
            ledger.to_persistence_dict(),
        )

    def test_public_claim_shape_has_no_partition_or_hidden_cardinality(self) -> None:
        inventory, requirement, manifest, authorization, partition, proofs = _fixture()
        ledger = _complete_ledger(
            inventory,
            requirement,
            manifest,
            authorization,
            partition,
            proofs,
        )
        from formowl_contract import AnswerClaim

        claim = AnswerClaim.create(
            state="FOUND",
            reason_codes=("complete_scope",),
            coverage_ledger=ledger,
            claim_requirement=requirement,
            source_inventory=inventory,
            version_manifest=manifest,
            authorization_binding=authorization,
            evidence_snapshot_ids=(),
        )
        public = claim.to_dict()
        self.assertNotIn("scope_partition", public)
        self.assertNotIn("authorized_relevant_item_ids", public)
        self.assertNotIn("ineligible_item_ids", public)
        self.assertNotIn(partition.scope_partition_id, repr(public))


def _manifest() -> VersionManifest:
    return VersionManifest.create(
        source_fingerprint=FP,
        parser_fingerprint=FP,
        tokenizer_fingerprint=FP,
        index_fingerprint=FP,
        implementation_fingerprint=FP,
        created_at="2026-07-24T00:00:00+00:00",
    )


def _fixture() -> (
    tuple[
        SourceInventory,
        ClaimRequirement,
        VersionManifest,
        CoverageAuthorizationBinding,
        CoverageScopePartition,
        tuple[CoverageProofRecord, CoverageProofRecord],
    ]
):
    raw_items = (
        SourceInventoryItem.create(
            source_asset_id="asset_scope_wp1",
            structure_kind="message",
            content_type="message/rfc822",
            ordinal=0,
            processing_state="parsed",
            raw_retention_state="retained",
            source_fingerprint=FP,
            parser_fingerprint=FP,
            permission_scope={"scope_type": "asset", "scope_id": "asset_scope_wp1"},
            source_observation_ids=("obs_a_struct", "obs_a_ordinary"),
        ),
        SourceInventoryItem.create(
            source_asset_id="asset_scope_wp1",
            structure_kind="message",
            content_type="message/rfc822",
            ordinal=1,
            processing_state="parsed",
            raw_retention_state="retained",
            source_fingerprint=FP,
            parser_fingerprint=FP,
            permission_scope={"scope_type": "asset", "scope_id": "asset_scope_wp1"},
            source_observation_ids=("obs_b_struct",),
        ),
        SourceInventoryItem.create(
            source_asset_id="asset_scope_wp1",
            structure_kind="message",
            content_type="message/rfc822",
            ordinal=2,
            processing_state="parsed",
            raw_retention_state="retained",
            source_fingerprint=FP,
            parser_fingerprint=FP,
            permission_scope={"scope_type": "asset", "scope_id": "asset_scope_wp1"},
            source_observation_ids=("obs_irrelevant",),
        ),
        SourceInventoryItem.create(
            source_asset_id="asset_scope_wp1",
            structure_kind="message",
            content_type="message/rfc822",
            ordinal=3,
            processing_state="unsupported",
            raw_retention_state="retained",
            source_fingerprint=FP,
            parser_fingerprint=FP,
            permission_scope={"scope_type": "asset", "scope_id": "asset_scope_wp1"},
            source_observation_ids=("obs_ineligible",),
        ),
    )
    inventory = SourceInventory.create(
        source_asset_id="asset_scope_wp1",
        source_fingerprint=FP,
        parser_fingerprint=FP,
        items=raw_items,
        created_at="2026-07-24T00:00:00+00:00",
    )
    requirement = ClaimRequirement.create(
        query_id="query_scope_wp1",
        kind="single_value",
        target="ticket",
        created_at="2026-07-24T00:00:00+00:00",
    )
    manifest = _manifest()
    authorization = CoverageAuthorizationBinding(
        actor_context_id="actor_scope_wp1",
        permission_revision="permission_scope_wp1",
        grant_revision="grant_scope_wp1",
    )
    partition = CoverageScopePartition.create(
        source_inventory=inventory,
        claim_requirement=requirement,
        authorization_binding=authorization,
        version_manifest=manifest,
        authorized_relevant_item_ids=(
            inventory.items[0].source_inventory_item_id,
            inventory.items[1].source_inventory_item_id,
        ),
        authorized_irrelevant_item_ids=(inventory.items[2].source_inventory_item_id,),
        ineligible_item_ids=(inventory.items[3].source_inventory_item_id,),
        observation_partitions=(
            CoverageObservationPartition(
                inventory_item_id=inventory.items[0].source_inventory_item_id,
                structural_observation_ids=("obs_a_struct",),
                ordinary_observation_ids=("obs_a_ordinary",),
            ),
            CoverageObservationPartition(
                inventory_item_id=inventory.items[1].source_inventory_item_id,
                structural_observation_ids=("obs_b_struct",),
            ),
        ),
    )
    proofs = (
        CoverageProofRecord.create(
            source_inventory_id=inventory.source_inventory_id,
            claim_requirement_id=requirement.claim_requirement_id,
            version_manifest_id=manifest.version_manifest_id,
            inventory_item_id=inventory.items[0].source_inventory_item_id,
            proof_kind="combined",
            structural_observation_ids=("obs_a_struct",),
            ordinary_observation_ids=("obs_a_ordinary",),
        ),
        CoverageProofRecord.create(
            source_inventory_id=inventory.source_inventory_id,
            claim_requirement_id=requirement.claim_requirement_id,
            version_manifest_id=manifest.version_manifest_id,
            inventory_item_id=inventory.items[1].source_inventory_item_id,
            proof_kind="structural",
            structural_observation_ids=("obs_b_struct",),
        ),
    )
    return inventory, requirement, manifest, authorization, partition, proofs


def _complete_ledger(
    inventory: SourceInventory,
    requirement: ClaimRequirement,
    manifest: VersionManifest,
    authorization: CoverageAuthorizationBinding,
    partition: CoverageScopePartition,
    proofs: tuple[CoverageProofRecord, CoverageProofRecord],
    *,
    searched_ordinary: tuple[str, ...] = ("obs_a_ordinary",),
) -> CoverageLedger:
    return CoverageLedger.create(
        query_id=requirement.query_id,
        claim_requirement_id=requirement.claim_requirement_id,
        source_inventory_id=inventory.source_inventory_id,
        relevant_inventory_item_ids=partition.authorized_relevant_item_ids,
        searched_structural_observation_ids=("obs_a_struct", "obs_b_struct"),
        searched_ordinary_observation_ids=searched_ordinary,
        authorization_binding=authorization,
        version_binding=CoverageVersionBinding.from_manifest(manifest),
        scope_partition=partition,
        proof_records=proofs,
        complete_authorized_scope=True,
    )


def _bundle_with_ledger(
    inventory: SourceInventory,
    requirement: ClaimRequirement,
    manifest: VersionManifest,
    ledger: CoverageLedger,
) -> MailEvidenceBundle:
    from test_issue51_wp1_contracts import _minimal_bundle

    return replace(
        _minimal_bundle(),
        mail_import_session=replace(
            _minimal_bundle().mail_import_session,
            source_asset_id=inventory.source_asset_id,
        ),
        source_inventory=[inventory],
        claim_requirements=[requirement],
        coverage_ledgers=[ledger],
        version_manifests=[manifest],
    )


if __name__ == "__main__":
    unittest.main()
