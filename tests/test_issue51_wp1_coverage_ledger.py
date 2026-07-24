from __future__ import annotations

from dataclasses import replace
import unittest

import _paths  # noqa: F401

from formowl_contract import (
    ClaimRequirement,
    ContractValidationError,
    CoverageAuthorizationBinding,
    CoverageFallbackUsage,
    CoverageLedger,
    CoverageProofRecord,
    CoverageVersionBinding,
    SourceInventory,
    SourceInventoryItem,
    VersionManifest,
)


FP = "sha256:" + "a" * 64
FP2 = "sha256:" + "b" * 64


class CoverageLedgerClosedProofTests(unittest.TestCase):
    def test_closed_typed_records_reject_unknown_and_wrong_types(self) -> None:
        authorization = CoverageAuthorizationBinding(
            actor_context_id="actor_wp1",
            permission_revision="permission_wp1",
            grant_revision=FP,
        )
        with self.assertRaises(ContractValidationError):
            CoverageAuthorizationBinding.from_dict(
                {
                    "actor_context_id": "actor_wp1",
                    "permission_revision": "permission_wp1",
                    "grant_revision": "grant_wp1",
                    "extra": "rejected",
                }
            )
        with self.assertRaises(ContractValidationError):
            CoverageAuthorizationBinding(
                actor_context_id=123,  # type: ignore[arg-type]
                permission_revision="permission_wp1",
                grant_revision=FP,
            )
        with self.assertRaises(ContractValidationError):
            CoverageFallbackUsage.from_dict(
                {
                    "status": "completed",
                    "items": True,
                    "bytes": 0,
                    "elapsed_ms": 0,
                    "attempt_count": 1,
                    "item_budget": 1,
                    "byte_budget": 0,
                    "elapsed_ms_budget": 0,
                    "attempt_budget": 1,
                }
            )
        with self.assertRaises(ContractValidationError):
            CoverageFallbackUsage.from_dict(
                {
                    "status": "completed",
                    "items": 1.0,
                    "bytes": 0,
                    "elapsed_ms": 0,
                    "attempt_count": 1,
                    "item_budget": 1,
                    "byte_budget": 0,
                    "elapsed_ms_budget": 0,
                    "attempt_budget": 1,
                }
            )
        with self.assertRaises(ContractValidationError):
            CoverageVersionBinding.from_dict(
                {
                    **CoverageVersionBinding.from_manifest(_manifest()).to_dict(),
                    "unknown": "rejected",
                }
            )
        self.assertEqual(authorization.grant_revision, FP)

    def test_fallback_statuses_and_budgets_fail_closed(self) -> None:
        with self.assertRaises(ContractValidationError):
            CoverageFallbackUsage(
                status="not_required",
                attempt_budget=1,
            )
        with self.assertRaises(ContractValidationError):
            CoverageFallbackUsage(
                status="completed",
                attempt_count=2,
                attempt_budget=1,
            )
        with self.assertRaises(ContractValidationError):
            CoverageFallbackUsage(
                status="budget_exhausted",
                attempt_count=1,
                attempt_budget=2,
            )
        completed = CoverageFallbackUsage(
            status="completed",
            items=2,
            bytes=100,
            elapsed_ms=20,
            attempt_count=1,
            item_budget=2,
            byte_budget=100,
            elapsed_ms_budget=20,
            attempt_budget=1,
        )
        self.assertEqual(
            CoverageFallbackUsage.from_dict(completed.to_dict()).to_dict(),
            completed.to_dict(),
        )

    def test_complete_scope_rejects_missing_or_unresolved_proof(self) -> None:
        inventory, requirement, manifest, authorization, proof = _fixture()
        common = {
            "query_id": requirement.query_id,
            "claim_requirement_id": requirement.claim_requirement_id,
            "source_inventory_id": inventory.source_inventory_id,
            "relevant_inventory_item_ids": (inventory.items[0].source_inventory_item_id,),
            "searched_structural_observation_ids": ("observation_wp1",),
            "authorization_binding": authorization,
            "version_binding": CoverageVersionBinding.from_manifest(manifest),
            "proof_records": (proof,),
            "complete_authorized_scope": True,
        }
        for field_name, value in (
            ("authorization_binding", None),
            ("version_binding", None),
            ("proof_records", ()),
            ("relevant_inventory_item_ids", ()),
            ("omitted_inventory_item_ids", (inventory.items[0].source_inventory_item_id,)),
            ("failed_inventory_item_ids", (inventory.items[0].source_inventory_item_id,)),
            ("unsupported_inventory_item_ids", (inventory.items[0].source_inventory_item_id,)),
            ("redacted_inventory_item_ids", (inventory.items[0].source_inventory_item_id,)),
        ):
            values = dict(common)
            values[field_name] = value
            with self.subTest(field_name=field_name):
                with self.assertRaises(ContractValidationError):
                    CoverageLedger(**values)
        for status in ("budget_exhausted", "failed", "cancelled"):
            values = dict(common)
            values["fallback_usage"] = (
                CoverageFallbackUsage(
                    status=status,
                    attempt_count=1,
                    attempt_budget=1,
                )
                if status == "budget_exhausted"
                else CoverageFallbackUsage(
                    status=status,
                    attempt_count=1,
                    attempt_budget=1,
                )
            )
            with self.subTest(status=status):
                with self.assertRaises(ContractValidationError):
                    CoverageLedger(**values)

    def test_usable_for_claim_validates_typed_bindings_and_processing(self) -> None:
        inventory, requirement, manifest, authorization, proof = _fixture()
        ledger = _complete_ledger(inventory, requirement, manifest, authorization, proof)
        self.assertTrue(ledger.usable_for_claim(inventory, requirement, manifest, authorization))
        self.assertFalse(
            ledger.usable_for_claim(
                inventory,
                requirement,
                replace(manifest, index_fingerprint=FP2),
                authorization,
            )
        )
        self.assertFalse(
            ledger.usable_for_claim(
                inventory,
                requirement,
                replace(manifest, index_freshness="stale"),
                authorization,
            )
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
                replace(requirement, query_id="query_other"),
                manifest,
                authorization,
            )
        )
        with self.assertRaises(ContractValidationError):
            ledger.usable_for_claim(object(), requirement, manifest, authorization)  # type: ignore[arg-type]
        with self.assertRaises(ContractValidationError):
            ledger.usable_for_claim(inventory, requirement, object(), authorization)  # type: ignore[arg-type]

    def test_usable_for_claim_rejects_unsearched_or_mismatched_proof(self) -> None:
        inventory, requirement, manifest, authorization, proof = _fixture()
        with self.assertRaises(ContractValidationError):
            replace(
                proof,
                ordinary_observation_ids=("observation_wp1",),
                proof_kind="ordinary",
            )
        for changed in (
            replace(proof, version_manifest_id="manifest_other"),
            replace(proof, source_inventory_id="inventory_other"),
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(ContractValidationError):
                    _complete_ledger(
                        inventory,
                        requirement,
                        manifest,
                        authorization,
                        changed,
                    )

        with self.assertRaises(ContractValidationError):
            changed = replace(proof, inventory_item_id="item_other")
            _complete_ledger(inventory, requirement, manifest, authorization, changed)
        changed = replace(proof, structural_observation_ids=("observation_other",))
        self.assertFalse(
            _complete_ledger(
                inventory,
                requirement,
                manifest,
                authorization,
                changed,
            ).usable_for_claim(inventory, requirement, manifest, authorization)
        )

        item = replace(inventory.items[0], processing_state="failed")
        failed_inventory = SourceInventory(
            source_inventory_id=inventory.source_inventory_id,
            source_asset_id=inventory.source_asset_id,
            source_fingerprint=inventory.source_fingerprint,
            parser_fingerprint=inventory.parser_fingerprint,
            items=(item,),
            created_at=inventory.created_at,
        )
        failed_ledger = _complete_ledger(
            failed_inventory,
            requirement,
            manifest,
            authorization,
            replace(proof, inventory_item_id=item.source_inventory_item_id),
        )
        self.assertFalse(
            failed_ledger.usable_for_claim(
                failed_inventory,
                requirement,
                manifest,
                authorization,
            )
        )

    def test_deterministic_ledger_id_and_round_trip_include_typed_proof(self) -> None:
        inventory, requirement, manifest, authorization, proof = _fixture()
        first = _complete_ledger(inventory, requirement, manifest, authorization, proof)
        second = CoverageLedger.from_dict(first.to_dict())
        self.assertEqual(first.coverage_ledger_id, second.coverage_ledger_id)
        self.assertEqual(first.to_dict(), second.to_dict())
        changed = replace(
            first,
            fallback_usage=CoverageFallbackUsage(
                status="completed",
                attempt_count=1,
                attempt_budget=1,
            ),
            complete_authorized_scope=False,
            coverage_ledger_id="",
        )
        self.assertNotEqual(first.coverage_ledger_id, changed.coverage_ledger_id)


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
        CoverageProofRecord,
    ]
):
    item = SourceInventoryItem.create(
        source_asset_id="asset_wp1",
        structure_kind="message",
        content_type="message/rfc822",
        ordinal=0,
        processing_state="parsed",
        raw_retention_state="retained",
        source_fingerprint=FP,
        parser_fingerprint=FP,
        permission_scope={"scope_type": "asset", "scope_id": "asset_wp1"},
        source_observation_ids=("observation_wp1",),
    )
    inventory = SourceInventory.create(
        source_asset_id="asset_wp1",
        source_fingerprint=FP,
        parser_fingerprint=FP,
        items=(item,),
        created_at="2026-07-24T00:00:00+00:00",
    )
    requirement = ClaimRequirement.create(
        query_id="query_wp1",
        kind="single_value",
        target="ticket",
        created_at="2026-07-24T00:00:00+00:00",
    )
    manifest = _manifest()
    authorization = CoverageAuthorizationBinding(
        actor_context_id="actor_wp1",
        permission_revision="permission_wp1",
        grant_revision="grant_wp1",
    )
    proof = CoverageProofRecord.create(
        source_inventory_id=inventory.source_inventory_id,
        claim_requirement_id=requirement.claim_requirement_id,
        version_manifest_id=manifest.version_manifest_id,
        inventory_item_id=item.source_inventory_item_id,
        proof_kind="structural",
        structural_observation_ids=("observation_wp1",),
    )
    return inventory, requirement, manifest, authorization, proof


def _complete_ledger(
    inventory: SourceInventory,
    requirement: ClaimRequirement,
    manifest: VersionManifest,
    authorization: CoverageAuthorizationBinding,
    proof: CoverageProofRecord,
) -> CoverageLedger:
    return CoverageLedger.create(
        query_id=requirement.query_id,
        claim_requirement_id=requirement.claim_requirement_id,
        source_inventory_id=inventory.source_inventory_id,
        relevant_inventory_item_ids=(inventory.items[0].source_inventory_item_id,),
        searched_structural_observation_ids=("observation_wp1",),
        authorization_binding=authorization,
        version_binding=CoverageVersionBinding.from_manifest(manifest),
        proof_records=(proof,),
        complete_authorized_scope=True,
    )


if __name__ == "__main__":
    unittest.main()
