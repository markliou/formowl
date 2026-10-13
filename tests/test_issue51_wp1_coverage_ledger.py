from __future__ import annotations

from dataclasses import replace
from copy import deepcopy
import unittest

import _paths  # noqa: F401

from formowl_contract import (
    ClaimRequirement,
    ContractValidationError,
    COVERAGE_FALLBACK_LIMIT_POLICY_FINGERPRINT,
    COVERAGE_FALLBACK_LIMIT_POLICY_ID,
    COVERAGE_FALLBACK_LIMIT_POLICY_VERSION,
    COVERAGE_FALLBACK_MAX_ATTEMPTS,
    COVERAGE_FALLBACK_MAX_BYTES,
    COVERAGE_FALLBACK_MAX_ELAPSED_MS,
    COVERAGE_FALLBACK_MAX_ITEMS,
    CoverageAuthorizationBinding,
    CoverageItemAuthorizationDecision,
    CoverageItemRelevanceDecision,
    CoverageFallbackUsage,
    CoverageLedger,
    CoverageObservationPartition,
    CoverageProofRecord,
    CoverageScopePartition,
    CoverageScopeAuthority,
    CoverageScopeAuthorityVerifier,
    CoverageScopePolicyBinding,
    CoverageVersionBinding,
    IntentionalExclusionProof,
    StructuralPublicScopeDecision,
    SourceInventory,
    SourceInventoryItem,
    VersionManifest,
)


FP = "sha256:" + "a" * 64
FP2 = "sha256:" + "b" * 64
SCOPE_POLICY_FP = "sha256:" + "c" * 64
AUTHORITY_ROOT = "issue51-wp1-test-authority-root-v2"


def _authority_verifier() -> CoverageScopeAuthorityVerifier:
    return CoverageScopeAuthorityVerifier.from_external_root(AUTHORITY_ROOT)


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
                    "limit_policy_id": COVERAGE_FALLBACK_LIMIT_POLICY_ID,
                    "limit_policy_version": COVERAGE_FALLBACK_LIMIT_POLICY_VERSION,
                    "limit_policy_fingerprint": COVERAGE_FALLBACK_LIMIT_POLICY_FINGERPRINT,
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
                    "limit_policy_id": COVERAGE_FALLBACK_LIMIT_POLICY_ID,
                    "limit_policy_version": COVERAGE_FALLBACK_LIMIT_POLICY_VERSION,
                    "limit_policy_fingerprint": COVERAGE_FALLBACK_LIMIT_POLICY_FINGERPRINT,
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

    def test_fallback_limits_are_closed_versioned_and_finite(self) -> None:
        boundary_values = (
            ("items", "item_budget", COVERAGE_FALLBACK_MAX_ITEMS),
            ("bytes", "byte_budget", COVERAGE_FALLBACK_MAX_BYTES),
            ("elapsed_ms", "elapsed_ms_budget", COVERAGE_FALLBACK_MAX_ELAPSED_MS),
            ("attempt_count", "attempt_budget", COVERAGE_FALLBACK_MAX_ATTEMPTS),
        )
        for usage_name, budget_name, maximum in boundary_values:
            with self.subTest(usage_name=usage_name):
                values = {
                    "status": "completed",
                    "items": 0,
                    "bytes": 0,
                    "elapsed_ms": 0,
                    "attempt_count": 1,
                    "item_budget": 0,
                    "byte_budget": 0,
                    "elapsed_ms_budget": 0,
                    "attempt_budget": 1,
                }
                values[usage_name] = maximum
                values[budget_name] = maximum
                bounded = CoverageFallbackUsage(**values)
                self.assertEqual(
                    CoverageFallbackUsage.from_dict(bounded.to_dict()).to_dict(),
                    bounded.to_dict(),
                )

                over_limit = dict(values)
                over_limit[usage_name] = maximum + 1
                over_limit[budget_name] = maximum + 1
                with self.assertRaises(ContractValidationError):
                    CoverageFallbackUsage(**over_limit)

                budget_over_limit = dict(values)
                budget_over_limit[usage_name] = 0
                budget_over_limit[budget_name] = maximum + 1
                with self.assertRaises(ContractValidationError):
                    CoverageFallbackUsage(**budget_over_limit)

        base = CoverageFallbackUsage(
            status="completed",
            attempt_count=1,
            attempt_budget=1,
        ).to_dict()
        for policy_field in (
            "limit_policy_id",
            "limit_policy_version",
            "limit_policy_fingerprint",
        ):
            with self.subTest(policy_field=policy_field):
                missing = dict(base)
                missing.pop(policy_field)
                with self.assertRaises(ContractValidationError):
                    CoverageFallbackUsage.from_dict(missing)

                mismatched = dict(base)
                mismatched[policy_field] = (
                    "different-policy" if policy_field != "limit_policy_fingerprint" else FP2
                )
                with self.assertRaises(ContractValidationError):
                    CoverageFallbackUsage.from_dict(mismatched)

        for numeric_field in (
            "items",
            "bytes",
            "elapsed_ms",
            "attempt_count",
            "item_budget",
            "byte_budget",
            "elapsed_ms_budget",
            "attempt_budget",
        ):
            for invalid in (True, -1, 10**100):
                with self.subTest(numeric_field=numeric_field, invalid=invalid):
                    malformed = dict(base)
                    malformed[numeric_field] = invalid
                    with self.assertRaises(ContractValidationError):
                        CoverageFallbackUsage.from_dict(malformed)

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
        self.assertTrue(
            ledger.usable_for_claim(
                inventory,
                requirement,
                manifest,
                authorization,
                ledger.scope_partition.scope_authority,
            )
        )
        self.assertFalse(
            ledger.usable_for_claim(
                inventory,
                requirement,
                _manifest(index_fingerprint=FP2),
                authorization,
                ledger.scope_partition.scope_authority,
            )
        )
        self.assertFalse(
            ledger.usable_for_claim(
                inventory,
                requirement,
                _manifest(index_freshness="stale"),
                authorization,
                ledger.scope_partition.scope_authority,
            )
        )
        self.assertFalse(
            ledger.usable_for_claim(
                inventory,
                requirement,
                manifest,
                replace(authorization, grant_revision=FP2),
                ledger.scope_partition.scope_authority,
            )
        )
        self.assertFalse(
            ledger.usable_for_claim(
                inventory,
                ClaimRequirement.create(
                    query_id="query_other",
                    kind=requirement.kind,
                    target=requirement.target,
                    predicate=requirement.predicate,
                    parameters=dict(requirement.parameters),
                    required_scope=requirement.required_scope,
                    created_at=requirement.created_at,
                ),
                manifest,
                authorization,
                ledger.scope_partition.scope_authority,
            )
        )
        with self.assertRaises(ContractValidationError):
            ledger.usable_for_claim(
                object(),
                requirement,
                manifest,
                authorization,
                ledger.scope_partition.scope_authority,
            )  # type: ignore[arg-type]
        with self.assertRaises(ContractValidationError):
            ledger.usable_for_claim(
                inventory,
                requirement,
                object(),
                authorization,
                ledger.scope_partition.scope_authority,
            )  # type: ignore[arg-type]

    def test_usable_for_claim_rejects_unsearched_or_mismatched_proof(self) -> None:
        inventory, requirement, manifest, authorization, proof = _fixture()
        with self.assertRaises(ContractValidationError):
            replace(
                proof,
                ordinary_observation_ids=("observation_wp1",),
                proof_kind="ordinary",
            )
        for changed in (
            _proof_variant(proof, version_manifest_id="manifest_other"),
            _proof_variant(proof, source_inventory_id="inventory_other"),
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
            changed = _proof_variant(proof, inventory_item_id="item_other")
            _complete_ledger(inventory, requirement, manifest, authorization, changed)
        changed = _proof_variant(proof, structural_observation_ids=("observation_other",))
        with self.assertRaises(ContractValidationError):
            _complete_ledger(
                inventory,
                requirement,
                manifest,
                authorization,
                changed,
            )

        failed_item_payload = inventory.items[0].to_persistence_dict()
        failed_item_payload.pop("source_inventory_item_id")
        failed_item_payload["source_inventory_id"] = None
        failed_item_payload["processing_state"] = "failed"
        item = SourceInventoryItem.create(**failed_item_payload)
        failed_inventory = SourceInventory.create(
            source_asset_id=inventory.source_asset_id,
            source_fingerprint=inventory.source_fingerprint,
            parser_fingerprint=inventory.parser_fingerprint,
            items=(item,),
            created_at=inventory.created_at,
        )
        failed_item = failed_inventory.items[0]
        failed_ledger = _complete_ledger(
            failed_inventory,
            requirement,
            manifest,
            authorization,
            CoverageProofRecord.create(
                source_inventory_id=failed_inventory.source_inventory_id,
                claim_requirement_id=requirement.claim_requirement_id,
                version_manifest_id=manifest.version_manifest_id,
                inventory_item_id=failed_item.source_inventory_item_id,
                proof_kind="structural",
                structural_observation_ids=("observation_wp1",),
            ),
        )
        self.assertFalse(
            failed_ledger.usable_for_claim(
                failed_inventory,
                requirement,
                manifest,
                authorization,
                failed_ledger.scope_partition.scope_authority,
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


def _manifest(
    *,
    index_fingerprint: str = FP,
    index_freshness: str = "fresh",
) -> VersionManifest:
    return VersionManifest.create(
        source_fingerprint=FP,
        parser_fingerprint=FP,
        tokenizer_fingerprint=FP,
        index_fingerprint=index_fingerprint,
        implementation_fingerprint=FP,
        index_freshness=index_freshness,
        created_at="2026-07-24T00:00:00+00:00",
    )


def _proof_variant(
    proof: CoverageProofRecord,
    **changes: object,
) -> CoverageProofRecord:
    payload = proof.to_persistence_dict()
    payload.update(changes)
    payload.pop("proof_id")
    return CoverageProofRecord.create(**payload)


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
    item = inventory.items[0]
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
    policy = CoverageScopePolicyBinding(
        scope_policy_id="scope-policy-wp1",
        scope_policy_version="1",
        scope_policy_fingerprint=SCOPE_POLICY_FP,
    )
    authorizations = tuple(
        CoverageItemAuthorizationDecision.create(
            source_inventory_item=item,
            authorization_binding=authorization,
            decision_state="authorized",
        )
        for item in inventory.items
    )
    relevance = tuple(
        CoverageItemRelevanceDecision.create(
            source_inventory_item=item,
            claim_requirement=requirement,
            scope_policy=policy,
            decision_state="relevant",
        )
        for item in inventory.items
    )
    authority = CoverageScopeAuthority.create(
        source_inventory=inventory,
        claim_requirement=requirement,
        authorization_binding=authorization,
        version_manifest=manifest,
        scope_policy=policy,
        authorization_decisions=authorizations,
        relevance_decisions=relevance,
        authority_verifier=_authority_verifier(),
    )
    scope_partition = CoverageScopePartition.create(
        scope_authority=authority,
        observation_partitions=(
            CoverageObservationPartition(
                inventory_item_id=inventory.items[0].source_inventory_item_id,
                structural_observation_ids=("observation_wp1",),
            ),
        ),
    )
    return CoverageLedger.create(
        query_id=requirement.query_id,
        claim_requirement_id=requirement.claim_requirement_id,
        source_inventory_id=inventory.source_inventory_id,
        relevant_inventory_item_ids=(inventory.items[0].source_inventory_item_id,),
        searched_structural_observation_ids=("observation_wp1",),
        authorization_binding=authorization,
        version_binding=CoverageVersionBinding.from_manifest(manifest),
        scope_partition=scope_partition,
        proof_records=(proof,),
        complete_authorized_scope=True,
    )


# Synthetic wire identities captured from clean Track2 HEAD cc8919f.
_LEGACY_WIRES = {
    "item": {
        "source_inventory_item_id": "srcinvitem_c2869f30aa86134c395c7bb0",
        "source_asset_id": "asset_legacy",
        "structure_kind": "message",
        "content_type": "message/rfc822",
        "ordinal": 0,
        "processing_state": "parsed",
        "raw_retention_state": "retained",
        "source_fingerprint": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "parser_fingerprint": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "permission_fingerprint": "sha256:4cf29db6ae86dbf00716e9824e4320a451af351d86d15e3510eb9eca2a976313",
        "permission_scope": {
            "scope_type": "asset",
            "scope_id": "asset_legacy",
            "owner_id": "actor_legacy",
        },
        "location": {"source_local_key": "unit_legacy"},
    },
    "inventory": {
        "source_inventory_id": "srcinv_fdf4658882d47c84297f5e3a",
        "source_asset_id": "asset_legacy",
        "source_fingerprint": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "parser_fingerprint": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "permission_fingerprint": "sha256:4cf29db6ae86dbf00716e9824e4320a451af351d86d15e3510eb9eca2a976313",
        "items": [
            {
                "source_inventory_item_id": "srcinvitem_c2869f30aa86134c395c7bb0",
                "source_asset_id": "asset_legacy",
                "structure_kind": "message",
                "content_type": "message/rfc822",
                "ordinal": 0,
                "processing_state": "parsed",
                "raw_retention_state": "retained",
                "source_fingerprint": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "parser_fingerprint": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "permission_fingerprint": "sha256:4cf29db6ae86dbf00716e9824e4320a451af351d86d15e3510eb9eca2a976313",
                "permission_scope": {
                    "scope_type": "asset",
                    "scope_id": "asset_legacy",
                    "owner_id": "actor_legacy",
                },
                "location": {"source_local_key": "unit_legacy"},
            }
        ],
        "created_at": "2026-10-14T00:00:00+00:00",
    },
    "empty": {
        "source_inventory_id": "srcinv_a336785356ef49aa0a589295",
        "source_asset_id": "asset_legacy",
        "source_fingerprint": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "parser_fingerprint": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "permission_fingerprint": "sha256:4cf29db6ae86dbf00716e9824e4320a451af351d86d15e3510eb9eca2a976313",
        "items": [],
        "created_at": "2026-10-14T00:00:00+00:00",
    },
    "excluded": {
        "source_inventory_item_id": "srcinvitem_8056b289cef99f6e3cfebbd8",
        "source_asset_id": "asset_legacy",
        "structure_kind": "message",
        "content_type": "message/rfc822",
        "ordinal": 0,
        "processing_state": "intentionally_excluded",
        "raw_retention_state": "retained",
        "source_fingerprint": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "parser_fingerprint": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "permission_fingerprint": "sha256:4cf29db6ae86dbf00716e9824e4320a451af351d86d15e3510eb9eca2a976313",
        "permission_scope": {
            "scope_type": "asset",
            "scope_id": "asset_legacy",
            "owner_id": "actor_legacy",
        },
        "location": {"source_local_key": "unit_legacy"},
        "exclusion_policy_id": "policy_legacy",
        "exclusion_out_of_scope_proof_fingerprint": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        "exclusion_authorized_actor_id": "actor_legacy",
        "exclusion_reason": "outside_claim_scope",
        "exclusion_policy_version": "1",
    },
}


class LegacySourceInventoryCompatibilityTests(unittest.TestCase):
    def test_legacy_constructor_preserves_item_and_aggregate_wire_identity(self) -> None:
        wire = deepcopy(_LEGACY_WIRES["item"])
        values = {
            k: v
            for k, v in wire.items()
            if k not in {"source_inventory_item_id", "permission_fingerprint"}
        }
        item = SourceInventoryItem.create(**values)
        self.assertEqual(item.to_persistence_dict(), wire)
        inventory = SourceInventory.create(
            source_asset_id=wire["source_asset_id"],
            source_fingerprint=wire["source_fingerprint"],
            parser_fingerprint=wire["parser_fingerprint"],
            items=(item,),
            created_at=_LEGACY_WIRES["inventory"]["created_at"],
            permission_fingerprint=wire["permission_fingerprint"],
        )
        self.assertEqual(inventory.to_persistence_dict(), _LEGACY_WIRES["inventory"])

    def test_legacy_wire_restore_and_private_round_trip_are_lossless(self) -> None:
        for key in ("item", "excluded", "inventory", "empty"):
            with self.subTest(key=key):
                record_type = (
                    SourceInventoryItem if key in {"item", "excluded"} else SourceInventory
                )
                for reader in (record_type.from_dict, record_type.from_persistence_dict):
                    self.assertEqual(
                        reader(deepcopy(_LEGACY_WIRES[key])).to_persistence_dict(),
                        _LEGACY_WIRES[key],
                    )
        wire = _LEGACY_WIRES["empty"]
        self.assertEqual(
            SourceInventory.create(
                **{k: v for k, v in wire.items() if k != "source_inventory_id"}
            ).to_persistence_dict(),
            wire,
        )

    def test_both_wire_families_keep_public_scope_gate_and_uniform_denial(self) -> None:
        legacy = SourceInventory.from_dict(deepcopy(_LEGACY_WIRES["inventory"]))
        typed, _, _, authorization, _ = _fixture()
        denied = StructuralPublicScopeDecision.deny(authorization_binding=authorization)
        for inventory in (legacy, typed):
            decision = StructuralPublicScopeDecision.authorize(
                permission_scope=inventory.items[0].permission_scope,
                authorization_binding=authorization,
            )
            for record in (inventory, inventory.items[0]):
                with self.assertRaises(ContractValidationError):
                    record.to_dict()
                with self.assertRaises(ContractValidationError):
                    record.to_dict(scope_decision=object())
                self.assertEqual(
                    record.to_dict(scope_decision=denied),
                    {"status": "denied", "reason_code": "scope_denied"},
                )
                public = record.to_dict(scope_decision=decision)
                self.assertEqual(public["status"], "authorized")
                self.assertNotIn("permission_scope", public)
                self.assertNotIn("source_inventory_item_id", public)
                self.assertNotIn("items", public)

    def test_legacy_validation_rejects_tampering_mixed_fields_and_mixed_families(self) -> None:
        for changes in (
            {"permission_fingerprint": FP2},
            {"source_inventory_item_id": "srcinvitem_forged"},
            {"source_observation_ids": []},
            {"source_inventory_id": "inventory_other"},
            {"location": {"source_local_key": "unit_legacy", "raw_path": "/private/raw"}},
        ):
            with self.subTest(changes=tuple(changes)):
                with self.assertRaises(ContractValidationError):
                    SourceInventoryItem.from_dict({**deepcopy(_LEGACY_WIRES["item"]), **changes})
        inventory, _, _, _, _ = _fixture()
        legacy = SourceInventoryItem.from_dict(deepcopy(_LEGACY_WIRES["item"]))
        with self.assertRaises(ContractValidationError):
            SourceInventory.create(
                source_asset_id=legacy.source_asset_id,
                items=(legacy, inventory.items[0]),
                source_fingerprint=legacy.source_fingerprint,
                parser_fingerprint=legacy.parser_fingerprint,
                permission_fingerprint=legacy.permission_fingerprint,
            )
        typed = inventory.items[0].to_persistence_dict()
        with self.assertRaises(ContractValidationError):
            SourceInventoryItem.from_dict({**typed, "exclusion_policy_id": "policy_legacy"})

    def test_existing_constructor_fields_discriminate_without_cross_upgrade(self) -> None:
        values = deepcopy(_LEGACY_WIRES["item"])
        values.pop("source_inventory_item_id")
        values.pop("permission_fingerprint")
        legacy = SourceInventoryItem.create(**values)
        structural = SourceInventoryItem.create(**values, source_observation_ids=[])
        self.assertTrue(legacy.source_inventory_item_id.startswith("srcinvitem_"))
        self.assertTrue(structural.source_inventory_item_id.startswith("inventory_"))
        for item in (legacy, structural):
            self.assertEqual(SourceInventoryItem.from_dict(item.to_persistence_dict()), item)
        with self.assertRaises(ContractValidationError):
            SourceInventoryItem.create(**legacy.to_persistence_dict(), source_observation_ids=[])

    def test_original_legacy_aggregate_and_exclusion_validators_remain_closed(self) -> None:
        for changes in (
            {"source_inventory_id": "srcinv_forged"},
            {"permission_fingerprint": FP2},
            {"source_fingerprint": FP2},
            {"parser_fingerprint": FP},
            {"created_at": "not-a-timestamp"},
            {"items": [_LEGACY_WIRES["item"], _LEGACY_WIRES["item"]]},
            {"unexpected": "rejected"},
        ):
            with self.subTest(changes=tuple(changes)):
                with self.assertRaises(ContractValidationError):
                    SourceInventory.from_dict({**deepcopy(_LEGACY_WIRES["inventory"]), **changes})
        for key in (
            "exclusion_policy_id",
            "exclusion_policy_version",
            "exclusion_authorized_actor_id",
            "exclusion_reason",
            "exclusion_out_of_scope_proof_fingerprint",
        ):
            wire = deepcopy(_LEGACY_WIRES["excluded"])
            wire.pop(key)
            with self.subTest(missing=key), self.assertRaises(ContractValidationError):
                SourceInventoryItem.from_dict(wire)
        for fingerprint in (FP, FP2, _LEGACY_WIRES["item"]["permission_fingerprint"]):
            with self.subTest(proof=fingerprint), self.assertRaises(ContractValidationError):
                SourceInventoryItem.from_dict(
                    {
                        **deepcopy(_LEGACY_WIRES["excluded"]),
                        "exclusion_out_of_scope_proof_fingerprint": fingerprint,
                    }
                )
        inventory = SourceInventory.from_dict(_LEGACY_WIRES["inventory"])
        with self.assertRaises(ContractValidationError):
            inventory.to_safe_payload()
        with self.assertRaises(ContractValidationError):
            SourceInventory.from_persistence_dict(
                deepcopy(_LEGACY_WIRES["inventory"]), consume_input=True
            )

    def test_legacy_scalar_exclusion_never_satisfies_typed_claim_scope_proof(self) -> None:
        legacy = SourceInventoryItem.from_dict(deepcopy(_LEGACY_WIRES["excluded"]))
        self.assertIsNone(legacy.intentional_exclusion_proof)
        self.assertEqual(legacy.to_persistence_dict(), _LEGACY_WIRES["excluded"])
        inventory, requirement, manifest, authorization, _ = _fixture()
        policy = CoverageScopePolicyBinding(
            scope_policy_id="scope-policy-wp1",
            scope_policy_version="1",
            scope_policy_fingerprint=SCOPE_POLICY_FP,
        )
        with self.assertRaises(ContractValidationError):
            IntentionalExclusionProof.create(
                source_inventory_item=legacy,
                claim_requirement=requirement,
                version_manifest=manifest,
                authorization_binding=authorization,
                scope_policy=policy,
                exclusion_policy_version_id="policy_legacy",
            )
        self.assertEqual(
            SourceInventory.from_persistence_dict(inventory.to_persistence_dict()), inventory
        )


if __name__ == "__main__":
    unittest.main()
