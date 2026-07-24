from __future__ import annotations

from dataclasses import replace
from copy import deepcopy
from pathlib import Path
import unittest

import _paths  # noqa: F401

from formowl_contract import (
    AnswerClaim,
    ClaimRequirement,
    ContractValidationError,
    CoverageAuthorizationBinding,
    CoverageItemAuthorizationDecision,
    CoverageItemRelevanceDecision,
    CoverageLedger,
    CoverageObservationPartition,
    CoverageProofRecord,
    CoverageScopePartition,
    CoverageScopeAuthority,
    CoverageScopePolicyBinding,
    CoverageVersionBinding,
    DisplayPagination,
    EXCLUSION_REASON_CODE_VALUES,
    SourceInventoryItem,
    StructuralCell,
    StructuralColumn,
    StructuralObservation,
    StructuralPublicScopeDecision,
    StructuralRow,
    SourceInventory,
    VersionManifest,
)
from formowl_graph.storage import (
    PostgreSQLMigrationRunner,
    PostgreSQLUnitOfWork,
    SQLStatement,
    migration_files,
)
from formowl_mail.bundle import (
    MailEvidenceBundle,
    MailImportSession,
    MailParseRun,
)
from formowl_mail.postgres import (
    PostgreSQLMailEvidenceStore,
    evidence_coverage_postgre_sql_tables,
)


FP = "sha256:" + "a" * 64
FP2 = "sha256:" + "b" * 64
SCOPE_POLICY_FP = "sha256:" + "c" * 64
_WP1_FAMILY_FIELDS_FOR_TESTS = (
    "source_inventory",
    "source_inventory_items",
    "structural_observations",
    "claim_requirements",
    "coverage_ledgers",
    "answer_claims",
    "version_manifests",
)


class Issue51WP1ContractTests(unittest.TestCase):
    def test_structural_public_serialization_is_typed_and_leak_free(self) -> None:
        item, inventory, observation, authorization = _public_structural_fixture()
        decision = StructuralPublicScopeDecision.authorize(
            permission_scope=item.permission_scope,
            authorization_binding=authorization,
        )

        item_public = item.to_dict(scope_decision=decision)
        inventory_public = inventory.to_dict(scope_decision=decision)
        observation_public = observation.to_dict(
            scope_decision=decision,
            source_inventory_item=item,
        )
        for payload in (item_public, inventory_public, observation_public):
            serialized = repr(payload)
            self.assertEqual(payload["status"], "authorized")
            self.assertIn("governed_reference", payload)
            self.assertNotIn("private/table.pst", serialized)
            self.assertNotIn("Open", serialized)
            self.assertNotIn("open", serialized)
            self.assertNotIn(item.source_inventory_item_id, serialized)
            self.assertNotIn(inventory.source_inventory_id, serialized)
            self.assertNotIn(observation.structural_observation_id, serialized)
            self.assertNotIn(FP, serialized)
            self.assertNotIn(FP2, serialized)
            self.assertNotIn("permission_scope", serialized)
            self.assertNotIn("header_path", serialized)
            self.assertNotIn("row_ordinal", serialized)
            self.assertNotIn("column_ordinal", serialized)

        with self.assertRaises(ContractValidationError):
            item.to_dict()
        with self.assertRaises(ContractValidationError):
            item.to_dict(scope_decision=object())
        with self.assertRaises(ContractValidationError):
            item.to_dict(
                scope_decision=replace(
                    decision,
                    authorization_binding=replace(
                        authorization,
                        actor_context_id="actor_other",
                    ),
                )
            )
        with self.assertRaises(ContractValidationError):
            item.to_dict(
                scope_decision=replace(
                    decision,
                    authorization_binding=replace(
                        authorization,
                        permission_revision="permission_other",
                    ),
                )
            )
        with self.assertRaises(ContractValidationError):
            item.to_dict(
                scope_decision=replace(
                    decision,
                    authorization_binding=replace(
                        authorization,
                        grant_revision="grant_other",
                    ),
                )
            )

    def test_structural_public_denial_has_uniform_shape_without_existence_signal(self) -> None:
        item, inventory, observation, authorization = _public_structural_fixture()
        denied = StructuralPublicScopeDecision.deny(
            authorization_binding=authorization,
        )
        empty_item = replace(
            item,
            source_observation_ids=(),
            source_inventory_item_id="item_empty_public",
            source_inventory_id=None,
        )
        empty_inventory = SourceInventory.create(
            source_asset_id="asset_wp1",
            source_fingerprint=FP,
            parser_fingerprint=FP2,
            items=(empty_item,),
            created_at="2026-07-24T00:00:00+00:00",
        )
        empty_observation = replace(
            observation,
            source_inventory_item_id=empty_inventory.items[0].source_inventory_item_id,
            structural_observation_id="observation_empty_public",
        )
        self.assertEqual(
            item.to_dict(scope_decision=denied), {"status": "denied", "reason_code": "scope_denied"}
        )
        self.assertEqual(
            inventory.to_dict(scope_decision=denied),
            {"status": "denied", "reason_code": "scope_denied"},
        )
        self.assertEqual(
            observation.to_dict(scope_decision=denied),
            empty_observation.to_dict(scope_decision=denied),
        )

        populated_bundle = replace(
            _minimal_bundle(),
            source_inventory=[inventory],
            structural_observations=[observation],
        )
        empty_bundle = replace(
            _minimal_bundle(),
            source_inventory=[empty_inventory],
            structural_observations=[empty_observation],
        )
        genuinely_empty_bundle = _minimal_bundle()
        self.assertEqual(
            populated_bundle.to_public_dict(scope_decision=denied)["structural_evidence"],
            empty_bundle.to_public_dict(scope_decision=denied)["structural_evidence"],
        )
        self.assertEqual(
            populated_bundle.to_public_dict(scope_decision=denied)["structural_evidence"],
            genuinely_empty_bundle.to_public_dict(scope_decision=denied)["structural_evidence"],
        )
        populated_claim_bundle, _, _, _ = _inventory_bundle()
        self.assertEqual(
            genuinely_empty_bundle.to_public_dict(
                scope_decision=denied,
                include_answer_claims=True,
            ),
            {
                **genuinely_empty_bundle.to_public_dict(scope_decision=denied),
                "answer_claims": {"status": "denied", "reason_code": "scope_denied"},
            },
        )
        self.assertEqual(
            populated_claim_bundle.to_public_dict(
                scope_decision=denied,
                include_answer_claims=True,
            )["structural_evidence"],
            genuinely_empty_bundle.to_public_dict(
                scope_decision=denied,
                include_answer_claims=True,
            )["structural_evidence"],
        )
        self.assertEqual(
            populated_claim_bundle.to_public_dict(
                scope_decision=denied,
                include_answer_claims=True,
            )["answer_claims"],
            {"status": "denied", "reason_code": "scope_denied"},
        )

    def test_structural_private_serialization_round_trips_exactly(self) -> None:
        item, inventory, observation, _ = _public_structural_fixture()
        self.assertEqual(
            item.to_persistence_dict(),
            SourceInventoryItem.from_persistence_dict(
                item.to_persistence_dict()
            ).to_persistence_dict(),
        )
        self.assertEqual(
            inventory.to_persistence_dict(),
            SourceInventory.from_persistence_dict(
                inventory.to_persistence_dict()
            ).to_persistence_dict(),
        )
        self.assertEqual(
            observation.to_persistence_dict(),
            StructuralObservation.from_persistence_dict(
                observation.to_persistence_dict()
            ).to_persistence_dict(),
        )

    def test_populated_bundle_public_allowlist_cannot_traverse_private_records(self) -> None:
        bundle, inventory, requirement, ledger = _inventory_bundle()
        item = inventory.items[0]
        observation = StructuralObservation.create(
            source_inventory_item_id=item.source_inventory_item_id,
            source_asset_id=item.source_asset_id,
            source_observation_id="observation_bundle_public_wp1",
            structure_kind="html_table",
            columns=(
                StructuralColumn(
                    column_ordinal=0,
                    original_header="Status",
                    normalized_header="status",
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
                            value="Open",
                            normalized_value="open",
                        ),
                    ),
                ),
            ),
            header_relationships=({"header_path": ["Status"]},),
            source_fingerprint=inventory.source_fingerprint,
            parser_fingerprint=inventory.parser_fingerprint,
        )
        populated = replace(bundle, structural_observations=[observation])
        decision = StructuralPublicScopeDecision.authorize(
            permission_scope=item.permission_scope,
            authorization_binding=CoverageAuthorizationBinding(
                actor_context_id="actor_bundle_public_wp1",
                permission_revision="permission_bundle_public_wp1",
                grant_revision="grant_bundle_public_wp1",
            ),
        )

        public = populated.to_public_dict(scope_decision=decision)
        self.assertEqual(
            set(public),
            {
                "public_schema",
                "producer_type",
                "created_at",
                "mail_import",
                "parse_status",
                "structural_evidence",
            },
        )
        serialized = repr(public)
        for private_value in (
            item.source_inventory_item_id,
            inventory.source_inventory_id,
            observation.structural_observation_id,
            requirement.claim_requirement_id,
            ledger.coverage_ledger_id,
            FP,
            FP2,
            "Open",
            "open",
            "Status",
            "private/table.pst",
            "permission_scope",
            "version_manifest",
            "coverage_ledger",
            "claim_requirement",
            "mail_import_session_id",
            "email_message_id",
        ):
            self.assertNotIn(private_value, serialized)

        public_with_claim = populated.to_public_dict(
            scope_decision=decision,
            include_answer_claims=True,
        )
        self.assertEqual(
            set(public_with_claim["answer_claims"][0]),
            {
                "state",
                "reason_codes",
                "claim_requirement_id",
                "coverage_ledger_id",
                "evidence_snapshot_ids",
                "source_fingerprint",
                "parser_fingerprint",
                "tokenizer_fingerprint",
                "index_fingerprint",
            },
        )
        self.assertNotIn("version_manifests", public_with_claim)
        self.assertNotIn("coverage_ledgers", public_with_claim)
        self.assertNotIn("claim_requirements", public_with_claim)

    def test_governed_reference_is_actor_revision_scoped_and_opaque(self) -> None:
        item, inventory, observation, authorization = _public_structural_fixture()
        private_payload = observation.to_persistence_dict()

        def reference_for(binding: CoverageAuthorizationBinding) -> str:
            decision = StructuralPublicScopeDecision.authorize(
                permission_scope=item.permission_scope,
                authorization_binding=binding,
            )
            return observation.to_public_dict(
                scope_decision=decision,
                source_inventory_item=item,
            )["governed_reference"]

        baseline = reference_for(authorization)
        actor_variant = reference_for(replace(authorization, actor_context_id="actor_public_other"))
        permission_variant = reference_for(
            replace(authorization, permission_revision="permission_public_other")
        )
        grant_variant = reference_for(replace(authorization, grant_revision="grant_public_other"))
        self.assertEqual(observation.to_persistence_dict(), private_payload)
        self.assertEqual(len({baseline, actor_variant, permission_variant, grant_variant}), 4)
        for reference in (baseline, actor_variant, permission_variant, grant_variant):
            self.assertTrue(reference.startswith("governed:structural_observation:"))
            self.assertNotIn(observation.structural_observation_id, reference)
            self.assertNotIn(item.source_inventory_item_id, reference)
            self.assertNotIn(inventory.source_inventory_id, reference)
            self.assertNotIn(FP, reference)
            self.assertNotIn(FP2, reference)

    def test_claim_inclusion_requires_scope_even_without_structural_rows(self) -> None:
        bundle, inventory, requirement, ledger = _inventory_bundle()
        item = inventory.items[0]
        authorization = CoverageAuthorizationBinding(
            actor_context_id="actor_claim_public_wp1",
            permission_revision="permission_claim_public_wp1",
            grant_revision="grant_claim_public_wp1",
        )
        authorized_ledger = replace(
            ledger,
            authorization_binding=authorization,
            coverage_ledger_id="",
        )
        manifest = bundle.version_manifests[0]
        claim = AnswerClaim.create(
            state="INSUFFICIENT_COVERAGE",
            reason_codes=("incomplete_scope",),
            coverage_ledger=authorized_ledger,
            claim_requirement=requirement,
            source_inventory=inventory,
            version_manifest=manifest,
            authorization_binding=authorization,
            evidence_snapshot_ids=(),
        )
        claimed_bundle = replace(
            bundle,
            coverage_ledgers=[authorized_ledger],
            answer_claims=[claim],
        )
        self.assertEqual(claimed_bundle.structural_observations, [])
        decision = StructuralPublicScopeDecision.authorize(
            permission_scope=item.permission_scope,
            authorization_binding=authorization,
        )
        public = claimed_bundle.to_public_dict(
            scope_decision=decision,
            include_answer_claims=True,
        )
        self.assertEqual(len(public["answer_claims"]), 1)
        self.assertEqual(
            set(public["answer_claims"][0]),
            {
                "state",
                "reason_codes",
                "claim_requirement_id",
                "coverage_ledger_id",
                "evidence_snapshot_ids",
                "source_fingerprint",
                "parser_fingerprint",
                "tokenizer_fingerprint",
                "index_fingerprint",
            },
        )

        with self.assertRaises(ContractValidationError):
            claimed_bundle.to_public_dict(include_answer_claims=True)

    def test_claim_inclusion_rejects_mismatched_authorization_without_structural_rows(
        self,
    ) -> None:
        bundle, inventory, requirement, ledger = _inventory_bundle()
        item = inventory.items[0]
        authorization = CoverageAuthorizationBinding(
            actor_context_id="actor_claim_public_mismatch",
            permission_revision="permission_claim_public_mismatch",
            grant_revision="grant_claim_public_mismatch",
        )
        authorized_ledger = replace(
            ledger,
            authorization_binding=authorization,
            coverage_ledger_id="",
        )
        claim = AnswerClaim.create(
            state="INSUFFICIENT_COVERAGE",
            reason_codes=("incomplete_scope",),
            coverage_ledger=authorized_ledger,
            claim_requirement=requirement,
            source_inventory=inventory,
            version_manifest=bundle.version_manifests[0],
            authorization_binding=authorization,
            evidence_snapshot_ids=(),
        )
        claimed_bundle = replace(
            bundle,
            coverage_ledgers=[authorized_ledger],
            answer_claims=[claim],
        )
        self.assertEqual(claimed_bundle.structural_observations, [])
        mismatched = StructuralPublicScopeDecision.authorize(
            permission_scope=item.permission_scope,
            authorization_binding=replace(
                authorization,
                grant_revision="grant_claim_other",
            ),
        )
        with self.assertRaises(ContractValidationError):
            claimed_bundle.to_public_dict(
                scope_decision=mismatched,
                include_answer_claims=True,
            )
        denied = StructuralPublicScopeDecision.deny(
            authorization_binding=authorization,
        )
        denied_public = claimed_bundle.to_public_dict(
            scope_decision=denied,
            include_answer_claims=True,
        )
        self.assertEqual(
            denied_public["answer_claims"],
            {"status": "denied", "reason_code": "scope_denied"},
        )

    def test_contracts_are_deterministic_and_round_trip(self) -> None:
        item = SourceInventoryItem.create(
            source_asset_id="asset_wp1",
            structure_kind="html_table",
            content_type="text/html",
            ordinal=1,
            processing_state="parsed",
            raw_retention_state="retained",
            source_fingerprint=FP,
            parser_fingerprint=FP2,
            permission_scope={"scope_type": "asset", "scope_id": "asset_wp1"},
            location={"table_ordinal": 0, "message_ordinal": 3},
            source_observation_ids=("observation_wp1",),
        )
        self.assertEqual(
            item.source_inventory_item_id,
            SourceInventoryItem.create(**item.to_persistence_dict()).source_inventory_item_id,
        )
        observation = StructuralObservation.create(
            source_inventory_item_id=item.source_inventory_item_id,
            source_asset_id="asset_wp1",
            source_observation_id="observation_wp1",
            structure_kind="table",
            columns=(
                StructuralColumn(
                    column_ordinal=0,
                    original_header="Status",
                    normalized_header="status",
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
                            value="Open",
                            normalized_value="open",
                        ),
                    ),
                ),
                StructuralRow(
                    row_ordinal=1,
                    cells=(
                        StructuralCell(
                            cell_state="blank",
                            row_ordinal=1,
                            column_ordinal=0,
                        ),
                    ),
                ),
            ),
            header_relationships=({"column_ordinal": 0, "header_path": ["Status"]},),
            source_fingerprint=FP,
            parser_fingerprint=FP2,
            occurrence_lineage=("occurrence_wp1",),
            current_depth=0,
            quoted_depth=1,
        )
        requirement = ClaimRequirement.create(
            query_id="query_wp1",
            kind="latest_value",
            target="ticket",
            predicate="status",
            required_scope=("scope_wp1",),
        )
        source_inventory = SourceInventory.create(
            source_asset_id="asset_wp1",
            source_fingerprint=FP,
            parser_fingerprint=FP2,
            items=(item,),
            created_at="2026-07-24T00:00:00+00:00",
        )
        item = source_inventory.items[0]
        observation = replace(
            observation,
            source_inventory_item_id=item.source_inventory_item_id,
        )
        manifest = VersionManifest.create(
            source_fingerprint=FP,
            parser_fingerprint=FP2,
            tokenizer_fingerprint=FP,
            index_fingerprint=FP,
            implementation_fingerprint=FP,
            created_at="2026-07-24T00:00:00+00:00",
        )
        authorization = CoverageAuthorizationBinding(
            actor_context_id="actor_wp1",
            permission_revision="permission_wp1",
            grant_revision="grant_wp1",
        )
        proof = CoverageProofRecord.create(
            source_inventory_id=source_inventory.source_inventory_id,
            claim_requirement_id=requirement.claim_requirement_id,
            version_manifest_id=manifest.version_manifest_id,
            inventory_item_id=item.source_inventory_item_id,
            proof_kind="structural",
            structural_observation_ids=(observation.source_observation_id,),
        )
        scope_policy = CoverageScopePolicyBinding(
            scope_policy_id="scope-policy-wp1",
            scope_policy_version="1",
            scope_policy_fingerprint=SCOPE_POLICY_FP,
        )
        authorization_decisions = (
            CoverageItemAuthorizationDecision.create(
                source_inventory_item=item,
                authorization_binding=authorization,
                decision_state="authorized",
            ),
        )
        relevance_decisions = (
            CoverageItemRelevanceDecision.create(
                source_inventory_item=item,
                claim_requirement=requirement,
                scope_policy=scope_policy,
                decision_state="relevant",
            ),
        )
        scope_authority = CoverageScopeAuthority.create(
            source_inventory=source_inventory,
            claim_requirement=requirement,
            authorization_binding=authorization,
            version_manifest=manifest,
            scope_policy=scope_policy,
            authorization_decisions=authorization_decisions,
            relevance_decisions=relevance_decisions,
        )
        scope_partition = CoverageScopePartition.create(
            scope_authority=scope_authority,
            observation_partitions=(
                CoverageObservationPartition(
                    inventory_item_id=item.source_inventory_item_id,
                    structural_observation_ids=(observation.source_observation_id,),
                ),
            ),
        )
        ledger = CoverageLedger(
            query_id="query_wp1",
            claim_requirement_id=requirement.claim_requirement_id,
            source_inventory_id=source_inventory.source_inventory_id,
            relevant_inventory_item_ids=(item.source_inventory_item_id,),
            searched_structural_observation_ids=(observation.source_observation_id,),
            authorization_binding=authorization,
            version_binding=CoverageVersionBinding.from_manifest(manifest),
            scope_partition=scope_partition,
            proof_records=(proof,),
            complete_authorized_scope=True,
            display_pagination=DisplayPagination(
                page_size=10,
                page_number=1,
                displayed_count=1,
                has_more=True,
            ),
        )
        claim = AnswerClaim.create(
            state="FOUND",
            reason_codes=("direct_evidence",),
            coverage_ledger=ledger,
            claim_requirement=requirement,
            source_inventory=source_inventory,
            version_manifest=manifest,
            authorization_binding=authorization,
            scope_authority=scope_partition.scope_authority,
            claim_requirement_id=requirement.claim_requirement_id,
            coverage_ledger_id=ledger.coverage_ledger_id,
            evidence_snapshot_ids=("snapshot_wp1",),
            source_fingerprint=FP,
            parser_fingerprint=FP2,
            tokenizer_fingerprint=FP,
            index_fingerprint=FP,
        )
        self.assertEqual(
            item.to_persistence_dict(),
            SourceInventoryItem.from_persistence_dict(
                item.to_persistence_dict()
            ).to_persistence_dict(),
        )
        self.assertEqual(
            observation.to_persistence_dict(),
            StructuralObservation.from_persistence_dict(
                observation.to_persistence_dict()
            ).to_persistence_dict(),
        )
        self.assertEqual(
            ledger.to_dict(),
            CoverageLedger.from_dict(ledger.to_dict()).to_dict(),
        )
        with self.assertRaises(ContractValidationError):
            AnswerClaim.from_dict(claim.to_dict()).to_dict()
        self.assertIsInstance(ledger.display_pagination, DisplayPagination)
        self.assertTrue(ledger.claim_scope_complete)
        self.assertTrue(
            ledger.usable_for_claim(source_inventory, requirement, manifest, authorization)
        )

    def test_persisted_authoritative_claim_requires_external_scope_authority(self) -> None:
        from test_issue51_wp1_scope_partition import _complete_ledger, _fixture

        (
            source_inventory,
            requirement,
            manifest,
            authorization,
            partition,
            proofs,
        ) = _fixture()
        ledger = _complete_ledger(
            source_inventory,
            requirement,
            manifest,
            authorization,
            partition,
            proofs,
        )
        claim = AnswerClaim.create(
            state="FOUND",
            reason_codes=("complete_scope",),
            coverage_ledger=ledger,
            claim_requirement=requirement,
            source_inventory=source_inventory,
            version_manifest=manifest,
            scope_authority=partition.scope_authority,
            authorization_binding=authorization,
            evidence_snapshot_ids=(),
        )
        persisted = claim.to_persistence_dict()

        with self.assertRaises(ContractValidationError):
            AnswerClaim.from_persistence_dict(
                persisted,
                coverage_ledger=ledger,
                claim_requirement=requirement,
                source_inventory=source_inventory,
                version_manifest=manifest,
                authorization_binding=authorization,
            )

        with self.assertRaises(ContractValidationError):
            AnswerClaim.from_persistence_dict(
                {key: value for key, value in persisted.items() if key != "scope_authority"},
                coverage_ledger=ledger,
                claim_requirement=requirement,
                source_inventory=source_inventory,
                version_manifest=manifest,
                expected_scope_authority=partition.scope_authority,
                authorization_binding=authorization,
            )

        wrong_authority = replace(
            partition.scope_authority,
            scope_policy=replace(
                partition.scope_authority.scope_policy,
                scope_policy_id="scope-policy-other",
            ),
            authority_id="",
        )
        with self.assertRaises(ContractValidationError):
            AnswerClaim.from_persistence_dict(
                persisted,
                coverage_ledger=ledger,
                claim_requirement=requirement,
                source_inventory=source_inventory,
                version_manifest=manifest,
                scope_authority=wrong_authority,
                authorization_binding=authorization,
            )

        restored = AnswerClaim.from_persistence_dict(
            persisted,
            coverage_ledger=ledger,
            claim_requirement=requirement,
            source_inventory=source_inventory,
            version_manifest=manifest,
            scope_authority=partition.scope_authority,
            authorization_binding=authorization,
        )
        self.assertEqual(restored.to_persistence_dict(), persisted)

        from test_issue51_wp1_scope_partition import _bundle_with_ledger

        bundle = _bundle_with_ledger(source_inventory, requirement, manifest, ledger)
        bundle = replace(bundle, answer_claims=[claim])
        bundle_payload = bundle.to_persistence_dict()
        with self.assertRaises(ContractValidationError):
            MailEvidenceBundle.from_persistence_dict(bundle_payload)
        restored_bundle = MailEvidenceBundle.from_persistence_dict(
            bundle_payload,
            scope_authorities={ledger.coverage_ledger_id: partition.scope_authority},
        )
        self.assertEqual(restored_bundle.to_persistence_dict(), bundle_payload)

        from test_mail_evidence_postgres import _RecordingMailConnection

        connection = _RecordingMailConnection()
        store = PostgreSQLMailEvidenceStore(connection)
        with self.assertRaises(ContractValidationError):
            store.upsert_bundle(bundle)
        store.upsert_bundle(
            bundle,
            scope_authorities={ledger.coverage_ledger_id: partition.scope_authority},
        )
        restored_from_postgres = store.get_bundle(
            mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
            scope_authorities={ledger.coverage_ledger_id: partition.scope_authority},
        )
        self.assertIsNotNone(restored_from_postgres)
        self.assertEqual(restored_from_postgres.to_persistence_dict(), bundle_payload)

    def test_direct_claim_paths_require_external_scope_authority(self) -> None:
        from test_issue51_wp1_scope_partition import _complete_ledger, _fixture

        (
            source_inventory,
            requirement,
            manifest,
            authorization,
            partition,
            proofs,
        ) = _fixture()
        ledger = replace(
            _complete_ledger(
                source_inventory,
                requirement,
                manifest,
                authorization,
                partition,
                proofs,
            ),
            complete_authorized_scope=False,
            coverage_ledger_id="",
            proof_records=(
                replace(proofs[0], populated_value_fingerprint=FP),
                replace(proofs[1], populated_value_fingerprint=FP2),
            ),
        )
        self.assertFalse(
            ledger.has_direct_authorized_witness(
                source_inventory,
                requirement,
                manifest,
                authorization,
            )
        )
        self.assertFalse(
            ledger.has_direct_incompatible_values(
                source_inventory,
                requirement,
                manifest,
                authorization,
            )
        )
        self.assertTrue(
            ledger.has_direct_authorized_witness(
                source_inventory,
                requirement,
                manifest,
                authorization,
                partition.scope_authority,
            )
        )
        self.assertTrue(
            ledger.has_direct_incompatible_values(
                source_inventory,
                requirement,
                manifest,
                authorization,
                partition.scope_authority,
            )
        )

    def test_display_pagination_is_presentation_only_for_ledger_and_claim_identity(self) -> None:
        bundle, source_inventory, requirement, ledger = _inventory_bundle()
        manifest = bundle.version_manifests[0]
        pagination_variants = (
            DisplayPagination(page_size=10, page_number=1, displayed_count=0, has_more=False),
            DisplayPagination(page_size=1, page_number=2, displayed_count=0, has_more=False),
            DisplayPagination(page_size=1, page_number=1, displayed_count=1, has_more=False),
            DisplayPagination(page_size=1, page_number=1, displayed_count=0, has_more=True),
        )
        baseline_claim = AnswerClaim.create(
            state="INSUFFICIENT_COVERAGE",
            reason_codes=("incomplete_scope",),
            coverage_ledger=ledger,
            claim_requirement=requirement,
            source_inventory=source_inventory,
            version_manifest=manifest,
            evidence_snapshot_ids=(),
        )

        for pagination in pagination_variants:
            with self.subTest(pagination=pagination):
                variant = replace(ledger, display_pagination=pagination)
                claim = AnswerClaim.create(
                    state="INSUFFICIENT_COVERAGE",
                    reason_codes=("incomplete_scope",),
                    coverage_ledger=variant,
                    claim_requirement=requirement,
                    source_inventory=source_inventory,
                    version_manifest=manifest,
                    evidence_snapshot_ids=(),
                )
                self.assertEqual(variant.coverage_ledger_id, ledger.coverage_ledger_id)
                self.assertEqual(variant.claim_scope_complete, ledger.claim_scope_complete)
                self.assertEqual(claim.answer_claim_id, baseline_claim.answer_claim_id)
                self.assertEqual(claim.to_dict(), baseline_claim.to_dict())

                payload = replace(
                    bundle,
                    coverage_ledgers=[variant],
                    answer_claims=[claim],
                ).to_persistence_dict()
                restored = MailEvidenceBundle.from_persistence_dict(payload)
                self.assertEqual(restored.coverage_ledgers[0].display_pagination, pagination)
                self.assertEqual(
                    restored.coverage_ledgers[0].coverage_ledger_id,
                    ledger.coverage_ledger_id,
                )
                self.assertEqual(
                    restored.answer_claims[0].answer_claim_id,
                    baseline_claim.answer_claim_id,
                )
                self.assertEqual(restored.answer_claims[0].to_dict(), baseline_claim.to_dict())

                connection = _RowsConnection()
                store = PostgreSQLMailEvidenceStore(connection)
                store.upsert_bundle(restored)
                postgres_restored = store.get_bundle(
                    mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
                )
                assert postgres_restored is not None
                self.assertEqual(
                    postgres_restored.coverage_ledgers[0].display_pagination,
                    pagination,
                )
                self.assertEqual(
                    postgres_restored.coverage_ledgers[0].coverage_ledger_id,
                    ledger.coverage_ledger_id,
                )
                self.assertEqual(
                    postgres_restored.answer_claims[0].answer_claim_id,
                    baseline_claim.answer_claim_id,
                )
                self.assertEqual(
                    postgres_restored.answer_claims[0].to_dict(),
                    baseline_claim.to_dict(),
                )

        semantic_variant = replace(
            ledger,
            searched_ordinary_observation_ids=("ordinary_observation_wp1",),
            coverage_ledger_id="",
        )
        self.assertNotEqual(semantic_variant.coverage_ledger_id, ledger.coverage_ledger_id)
        semantic_claim = AnswerClaim.create(
            state="INSUFFICIENT_COVERAGE",
            reason_codes=("incomplete_scope",),
            coverage_ledger=semantic_variant,
            claim_requirement=requirement,
            source_inventory=source_inventory,
            version_manifest=manifest,
            evidence_snapshot_ids=(),
        )
        self.assertNotEqual(semantic_claim.answer_claim_id, baseline_claim.answer_claim_id)

        invalid_payload = replace(ledger, display_pagination=pagination_variants[-1]).to_dict()
        invalid_payload["coverage_ledger_id"] = "coverage_tampered"
        with self.assertRaises(ContractValidationError):
            CoverageLedger.from_dict(invalid_payload)

    def test_validation_is_strict_and_public_leaks_fail_closed(self) -> None:
        with self.assertRaises(ContractValidationError):
            SourceInventoryItem.create(
                source_asset_id="asset_wp1",
                structure_kind="message",
                content_type="message/rfc822",
                ordinal=True,
                processing_state="parsed",
                raw_retention_state="retained",
                source_fingerprint=FP,
                parser_fingerprint=FP,
                permission_scope={},
            )
        with self.assertRaises(ContractValidationError):
            SourceInventoryItem.create(
                source_asset_id="asset_wp1",
                structure_kind="message",
                content_type="message/rfc822",
                ordinal=0,
                processing_state="not_a_state",
                raw_retention_state="retained",
                source_fingerprint=FP,
                parser_fingerprint=FP,
                permission_scope={},
            )
        with self.assertRaises(ContractValidationError):
            SourceInventoryItem.create(
                source_asset_id="asset_wp1",
                structure_kind="message",
                content_type="message/rfc822",
                ordinal=0,
                processing_state="parsed",
                raw_retention_state="retained",
                source_fingerprint=FP,
                parser_fingerprint=FP,
                permission_scope={},
                location={"raw_path": "/private/archive.pst"},
            )
        with self.assertRaises(ContractValidationError):
            AnswerClaim.create(
                state="FOUND",
                reason_codes=("SELECT * FROM private_data",),
                claim_requirement_id="requirement_wp1",
                coverage_ledger_id="coverage_wp1",
                evidence_snapshot_ids=(),
                source_fingerprint=FP,
                parser_fingerprint=FP,
                tokenizer_fingerprint=FP,
                index_fingerprint=FP,
            )

    def test_intentionally_excluded_requires_closed_complete_proof(self) -> None:
        valid = _excluded_item().to_persistence_dict()
        proof_fields = (
            "exclusion_policy_version_id",
            "exclusion_authorized_actor_id",
            "exclusion_reason_code",
            "exclusion_claim_scope_proof_sha256",
        )
        for field_name in proof_fields:
            missing = dict(valid)
            missing.pop(field_name)
            with self.subTest(missing=field_name):
                with self.assertRaises(ContractValidationError):
                    SourceInventoryItem.from_dict(missing)

        wrong_types = {
            "exclusion_policy_version_id": 123,
            "exclusion_authorized_actor_id": 123,
            "exclusion_reason_code": 123,
            "exclusion_claim_scope_proof_sha256": 123,
        }
        for field_name, wrong_type in wrong_types.items():
            invalid = dict(valid)
            invalid[field_name] = wrong_type
            with self.subTest(wrong_type=field_name):
                with self.assertRaises(ContractValidationError):
                    SourceInventoryItem.from_dict(invalid)

        unsafe_values = {
            "exclusion_policy_version_id": "/private/policy",
            "exclusion_authorized_actor_id": "postgresql://actor",
            "exclusion_reason_code": "SELECT * FROM reasons",
            "exclusion_claim_scope_proof_sha256": "/private/proof",
        }
        for field_name, unsafe_value in unsafe_values.items():
            invalid = dict(valid)
            invalid[field_name] = unsafe_value
            with self.subTest(unsafe_value=field_name):
                with self.assertRaises(ContractValidationError):
                    SourceInventoryItem.from_dict(invalid)

        invalid_hash = dict(valid)
        invalid_hash["exclusion_claim_scope_proof_sha256"] = "sha256:" + "g" * 64
        with self.assertRaises(ContractValidationError):
            SourceInventoryItem.from_dict(invalid_hash)

        self.assertIn(valid["exclusion_reason_code"], EXCLUSION_REASON_CODE_VALUES)

    def test_exclusion_proof_is_rejected_for_non_excluded_states(self) -> None:
        for processing_state in (
            "parsed",
            "preserved_unparsed",
            "unsupported",
            "failed",
        ):
            invalid = dict(_excluded_item().to_persistence_dict())
            invalid["processing_state"] = processing_state
            with self.subTest(processing_state=processing_state):
                with self.assertRaises(ContractValidationError):
                    SourceInventoryItem.from_dict(invalid)

    def test_exclusion_proof_changes_deterministic_inventory_id(self) -> None:
        first = _excluded_item(proof=FP)
        second = _excluded_item(proof=FP2)
        self.assertNotEqual(
            first.source_inventory_item_id,
            second.source_inventory_item_id,
        )

    def test_answer_claim_has_one_exact_public_wire_and_separate_private_wire(self) -> None:
        bundle, source_inventory, requirement, ledger = _inventory_bundle()
        manifest = bundle.version_manifests[0]
        claim = AnswerClaim.create(
            answer_claim_id="answer_claim_wp1",
            state="INSUFFICIENT_COVERAGE",
            reason_codes=("incomplete_scope",),
            coverage_ledger=ledger,
            claim_requirement=requirement,
            source_inventory=source_inventory,
            version_manifest=manifest,
            claim_requirement_id=requirement.claim_requirement_id,
            coverage_ledger_id=ledger.coverage_ledger_id,
            evidence_snapshot_ids=("snapshot_wp1",),
            source_fingerprint=manifest.source_fingerprint,
            parser_fingerprint=manifest.parser_fingerprint,
            tokenizer_fingerprint=manifest.tokenizer_fingerprint,
            index_fingerprint=manifest.index_fingerprint,
            version_manifest_id=manifest.version_manifest_id,
            implementation_fingerprint=manifest.implementation_fingerprint,
        )
        expected_keys = {
            "state",
            "reason_codes",
            "claim_requirement_id",
            "coverage_ledger_id",
            "evidence_snapshot_ids",
            "source_fingerprint",
            "parser_fingerprint",
            "tokenizer_fingerprint",
            "index_fingerprint",
        }
        public = claim.to_dict()
        self.assertEqual(set(public), expected_keys)
        self.assertNotIn("answer_claim_id", public)
        self.assertNotIn("version_manifest_id", public)
        self.assertNotIn("implementation_fingerprint", public)
        self.assertEqual(AnswerClaim.from_dict(public).to_dict(), public)
        with self.assertRaises(ContractValidationError):
            AnswerClaim.from_dict(public).to_persistence_dict()

        private = claim.to_persistence_dict()
        self.assertIn("answer_claim_id", private)
        self.assertIn("version_manifest_id", private)
        self.assertIn("implementation_fingerprint", private)
        self.assertEqual(
            AnswerClaim.from_persistence_dict(
                private,
                coverage_ledger=ledger,
                claim_requirement=requirement,
                source_inventory=source_inventory,
                version_manifest=manifest,
            ).to_persistence_dict(),
            private,
        )
        with self.assertRaises(ContractValidationError):
            AnswerClaim.from_persistence_dict(
                private,
                coverage_ledger=ledger,
                claim_requirement=requirement,
                source_inventory=source_inventory,
            )
        for missing_key in (
            "coverage_ledger_id",
            "version_manifest_id",
            "implementation_fingerprint",
        ):
            missing_binding = dict(private)
            missing_binding.pop(missing_key)
            with self.subTest(missing_key=missing_key):
                with self.assertRaises(ContractValidationError):
                    AnswerClaim.from_persistence_dict(
                        missing_binding,
                        coverage_ledger=ledger,
                        claim_requirement=requirement,
                        source_inventory=source_inventory,
                        version_manifest=manifest,
                    )
        for extra_key in ("answer_claim_id", "answer_claim_state", "state_2"):
            invalid = dict(public)
            invalid[extra_key] = "CONFLICT"
            with self.subTest(extra_key=extra_key):
                with self.assertRaises(ContractValidationError):
                    AnswerClaim.from_dict(invalid)

    def test_incomplete_ledger_supports_insufficient_coverage_claim(self) -> None:
        bundle, source_inventory, requirement, ledger = _inventory_bundle()
        manifest = bundle.version_manifests[0]
        self.assertFalse(ledger.complete_authorized_scope)
        self.assertTrue(ledger.binding_valid_for_claim(source_inventory, requirement, manifest))
        claim = AnswerClaim.create(
            state="INSUFFICIENT_COVERAGE",
            reason_codes=("incomplete_scope",),
            coverage_ledger=ledger,
            claim_requirement=requirement,
            source_inventory=source_inventory,
            version_manifest=manifest,
            evidence_snapshot_ids=(),
        )
        private = claim.to_persistence_dict()
        restored = AnswerClaim.from_persistence_dict(
            private,
            coverage_ledger=ledger,
            claim_requirement=requirement,
            source_inventory=source_inventory,
            version_manifest=manifest,
        )
        self.assertEqual(restored.to_dict(), claim.to_dict())
        self.assertFalse(ledger.usable_for_claim(source_inventory, requirement, manifest))
        for state in (
            "FOUND",
            "CONFLICT",
            "NOT_FOUND_WITHIN_COMPLETE_SCOPE",
        ):
            with self.subTest(state=state):
                with self.assertRaises(ContractValidationError):
                    AnswerClaim.create(
                        state=state,
                        reason_codes=("wp1_binding_valid",),
                        coverage_ledger=ledger,
                        claim_requirement=requirement,
                        source_inventory=source_inventory,
                        version_manifest=manifest,
                        evidence_snapshot_ids=(),
                    )
        self.assertEqual(claim.state, "INSUFFICIENT_COVERAGE")

        invalid_private = dict(private)
        invalid_private["state"] = "FOUND"
        with self.assertRaises(ContractValidationError):
            AnswerClaim.from_persistence_dict(
                invalid_private,
                coverage_ledger=ledger,
                claim_requirement=requirement,
                source_inventory=source_inventory,
                version_manifest=manifest,
            )
        with self.assertRaises(ContractValidationError):
            AnswerClaim(
                state="FOUND",
                reason_codes=("wp1_binding_valid",),
                claim_requirement_id=requirement.claim_requirement_id,
                coverage_ledger_id=ledger.coverage_ledger_id,
                evidence_snapshot_ids=(),
                source_fingerprint=manifest.source_fingerprint,
                parser_fingerprint=manifest.parser_fingerprint,
                tokenizer_fingerprint=manifest.tokenizer_fingerprint,
                index_fingerprint=manifest.index_fingerprint,
                coverage_ledger=ledger,
                claim_requirement=requirement,
                source_inventory=source_inventory,
                version_manifest=manifest,
            )

    def test_answer_claim_state_matrix_and_typed_exception_paths(self) -> None:
        state_kinds = (
            "single_value",
            "latest_value",
            "current_value",
            "all_matching",
            "aggregation",
            "existential_witness",
        )
        for kind in state_kinds:
            with self.subTest(kind=kind):
                _, source_inventory, _, ledger = _inventory_bundle()
                requirement = ClaimRequirement.create(
                    query_id=f"query_matrix_{kind}",
                    kind=kind,
                    target="ticket",
                    parameters=(
                        {"support_only_completeness": False}
                        if kind == "existential_witness"
                        else {}
                    ),
                    created_at="2026-07-24T00:00:00+00:00",
                )
                ledger = replace(
                    ledger,
                    query_id=requirement.query_id,
                    claim_requirement_id=requirement.claim_requirement_id,
                    coverage_ledger_id="",
                )
                manifest = _inventory_bundle()[0].version_manifests[0]
                with self.assertRaises(ContractValidationError):
                    AnswerClaim.create(
                        state="FOUND",
                        reason_codes=("matrix",),
                        coverage_ledger=ledger,
                        claim_requirement=requirement,
                        source_inventory=source_inventory,
                        version_manifest=manifest,
                        evidence_snapshot_ids=(),
                    )
                with self.assertRaises(ContractValidationError):
                    AnswerClaim.create(
                        state="NOT_FOUND_WITHIN_COMPLETE_SCOPE",
                        reason_codes=("matrix",),
                        coverage_ledger=ledger,
                        claim_requirement=requirement,
                        source_inventory=source_inventory,
                        version_manifest=manifest,
                        evidence_snapshot_ids=(),
                    )
                with self.assertRaises(ContractValidationError):
                    AnswerClaim.create(
                        state="CONFLICT",
                        reason_codes=("matrix",),
                        coverage_ledger=ledger,
                        claim_requirement=requirement,
                        source_inventory=source_inventory,
                        version_manifest=manifest,
                        evidence_snapshot_ids=(),
                    )
                self.assertEqual(
                    AnswerClaim.create(
                        state="INSUFFICIENT_COVERAGE",
                        reason_codes=("matrix",),
                        coverage_ledger=ledger,
                        claim_requirement=requirement,
                        source_inventory=source_inventory,
                        version_manifest=manifest,
                        evidence_snapshot_ids=(),
                    ).state,
                    "INSUFFICIENT_COVERAGE",
                )

    def test_existential_support_only_requires_boolean_and_direct_witness(self) -> None:
        (
            source_inventory,
            requirement,
            manifest,
            authorization,
            ledger,
        ) = _direct_claim_fixture(
            kind="existential_witness",
            parameters={"support_only_completeness": True},
        )
        claim = AnswerClaim.create(
            state="FOUND",
            reason_codes=("direct_witness",),
            coverage_ledger=ledger,
            claim_requirement=requirement,
            source_inventory=source_inventory,
            version_manifest=manifest,
            authorization_binding=authorization,
            evidence_snapshot_ids=("snapshot_witness",),
        )
        self.assertEqual(claim.state, "FOUND")

        for parameters in ({}, {"support_only_completeness": False}):
            with self.subTest(parameters=parameters):
                (
                    source_inventory,
                    requirement,
                    manifest,
                    authorization,
                    ledger,
                ) = _direct_claim_fixture(
                    kind="existential_witness",
                    parameters=parameters,
                )
                with self.assertRaises(ContractValidationError):
                    AnswerClaim.create(
                        state="FOUND",
                        reason_codes=("direct_witness",),
                        coverage_ledger=ledger,
                        claim_requirement=requirement,
                        source_inventory=source_inventory,
                        version_manifest=manifest,
                        authorization_binding=authorization,
                        evidence_snapshot_ids=("snapshot_witness",),
                    )

        (
            source_inventory,
            requirement,
            manifest,
            authorization,
            ledger,
        ) = _direct_claim_fixture(
            kind="existential_witness",
            parameters={"support_only_completeness": "true"},
        )
        with self.assertRaises(ContractValidationError):
            AnswerClaim.create(
                state="FOUND",
                reason_codes=("direct_witness",),
                coverage_ledger=ledger,
                claim_requirement=requirement,
                source_inventory=source_inventory,
                version_manifest=manifest,
                authorization_binding=authorization,
                evidence_snapshot_ids=("snapshot_witness",),
            )

        (
            source_inventory,
            requirement,
            manifest,
            authorization,
            ledger,
        ) = _direct_claim_fixture(
            kind="existential_witness",
            parameters={"support_only_completeness": True},
            include_direct_proof=False,
        )
        with self.assertRaises(ContractValidationError):
            AnswerClaim.create(
                state="FOUND",
                reason_codes=("direct_witness",),
                coverage_ledger=ledger,
                claim_requirement=requirement,
                source_inventory=source_inventory,
                version_manifest=manifest,
                authorization_binding=authorization,
                evidence_snapshot_ids=("snapshot_witness",),
            )

    def test_partial_single_value_conflict_requires_typed_populated_values(self) -> None:
        for kind in ("single_value", "latest_value", "current_value"):
            with self.subTest(kind=kind):
                (
                    source_inventory,
                    requirement,
                    manifest,
                    authorization,
                    ledger,
                ) = _direct_claim_fixture(
                    kind=kind,
                    include_conflicting_values=True,
                )
                claim = AnswerClaim.create(
                    state="CONFLICT",
                    reason_codes=("conflicting_evidence",),
                    coverage_ledger=ledger,
                    claim_requirement=requirement,
                    source_inventory=source_inventory,
                    version_manifest=manifest,
                    authorization_binding=authorization,
                    evidence_snapshot_ids=("snapshot_one", "snapshot_two"),
                )
                self.assertEqual(claim.state, "CONFLICT")

        (
            source_inventory,
            requirement,
            manifest,
            authorization,
            ledger,
        ) = _direct_claim_fixture(
            kind="single_value",
            include_direct_proof=True,
        )
        with self.assertRaises(ContractValidationError):
            AnswerClaim.create(
                state="CONFLICT",
                reason_codes=("conflicting_evidence",),
                coverage_ledger=ledger,
                claim_requirement=requirement,
                source_inventory=source_inventory,
                version_manifest=manifest,
                authorization_binding=authorization,
                evidence_snapshot_ids=("snapshot_one", "snapshot_two"),
            )

        (
            source_inventory,
            requirement,
            manifest,
            authorization,
            ledger,
        ) = _direct_claim_fixture(
            kind="single_value",
            include_conflicting_values=True,
        )
        first_proof, second_proof = ledger.proof_records
        same_observation_proof = CoverageProofRecord.create(
            source_inventory_id=first_proof.source_inventory_id,
            claim_requirement_id=first_proof.claim_requirement_id,
            version_manifest_id=first_proof.version_manifest_id,
            inventory_item_id=first_proof.inventory_item_id,
            proof_kind="structural",
            structural_observation_ids=("observation_direct_wp1_a",),
            populated_value_fingerprint=FP2,
        )
        same_observation_ledger = replace(
            ledger,
            proof_records=(first_proof, same_observation_proof),
            coverage_ledger_id="",
        )
        self.assertEqual(
            second_proof.structural_observation_ids,
            ("observation_direct_wp1_b",),
        )
        with self.assertRaises(ContractValidationError):
            AnswerClaim.create(
                state="CONFLICT",
                reason_codes=("conflicting_evidence",),
                coverage_ledger=same_observation_ledger,
                claim_requirement=requirement,
                source_inventory=source_inventory,
                version_manifest=manifest,
                authorization_binding=authorization,
                evidence_snapshot_ids=("snapshot_one", "snapshot_two"),
            )

        for kind, parameters in (
            ("all_matching", {}),
            ("aggregation", {}),
            ("existential_witness", {"support_only_completeness": True}),
        ):
            with self.subTest(disallowed_kind=kind):
                (
                    source_inventory,
                    requirement,
                    manifest,
                    authorization,
                    ledger,
                ) = _direct_claim_fixture(
                    kind=kind,
                    parameters=parameters,
                    include_conflicting_values=True,
                )
                with self.assertRaises(ContractValidationError):
                    AnswerClaim.create(
                        state="CONFLICT",
                        reason_codes=("conflicting_evidence",),
                        coverage_ledger=ledger,
                        claim_requirement=requirement,
                        source_inventory=source_inventory,
                        version_manifest=manifest,
                        authorization_binding=authorization,
                        evidence_snapshot_ids=("snapshot_one", "snapshot_two"),
                    )

    def test_coverage_ledger_rejects_duplicate_proof_records(self) -> None:
        source_inventory, requirement, manifest, authorization, ledger = _direct_claim_fixture(
            kind="single_value",
            include_direct_proof=True,
        )
        proof = ledger.proof_records[0]
        duplicate_cases = (
            ("repeated_same_object", (proof, proof)),
            (
                "same_proof_id",
                (
                    proof,
                    replace(
                        proof,
                        structural_observation_ids=("observation_direct_wp1_b",),
                    ),
                ),
            ),
            (
                "semantic_duplicate",
                (
                    proof,
                    replace(proof, proof_id="proof_semantic_duplicate"),
                ),
            ),
        )
        for case_name, proof_records in duplicate_cases:
            with self.subTest(case_name=case_name):
                with self.assertRaises(ContractValidationError):
                    replace(
                        ledger,
                        proof_records=proof_records,
                        coverage_ledger_id="",
                    )

        for proof_kind, observation_field in (
            ("structural", "structural_observation_ids"),
            ("ordinary", "ordinary_observation_ids"),
        ):
            with self.subTest(repeated_observation_ids=proof_kind):
                with self.assertRaises(ContractValidationError):
                    CoverageProofRecord.create(
                        source_inventory_id=source_inventory.source_inventory_id,
                        claim_requirement_id=requirement.claim_requirement_id,
                        version_manifest_id=manifest.version_manifest_id,
                        inventory_item_id=source_inventory.items[0].source_inventory_item_id,
                        proof_kind=proof_kind,
                        **{
                            observation_field: (
                                "observation_direct_wp1_a",
                                "observation_direct_wp1_a",
                            )
                        },
                    )

        for proof_kind, observation_field in (
            ("structural", "structural_observation_ids"),
            ("ordinary", "ordinary_observation_ids"),
        ):
            with self.subTest(reversed_semantic_order=proof_kind):
                first = CoverageProofRecord.create(
                    source_inventory_id=source_inventory.source_inventory_id,
                    claim_requirement_id=requirement.claim_requirement_id,
                    version_manifest_id=manifest.version_manifest_id,
                    inventory_item_id=source_inventory.items[0].source_inventory_item_id,
                    proof_kind=proof_kind,
                    **{
                        observation_field: (
                            "observation_direct_wp1_a",
                            "observation_direct_wp1_b",
                        )
                    },
                )
                second = CoverageProofRecord.create(
                    source_inventory_id=source_inventory.source_inventory_id,
                    claim_requirement_id=requirement.claim_requirement_id,
                    version_manifest_id=manifest.version_manifest_id,
                    inventory_item_id=source_inventory.items[0].source_inventory_item_id,
                    proof_kind=proof_kind,
                    **{
                        observation_field: (
                            "observation_direct_wp1_b",
                            "observation_direct_wp1_a",
                        )
                    },
                )
                with self.assertRaises(ContractValidationError):
                    replace(
                        ledger,
                        proof_records=(first, second),
                        coverage_ledger_id="",
                    )

    def test_answer_claim_rejects_invalid_typed_bindings(self) -> None:
        bundle, source_inventory, requirement, ledger = _inventory_bundle()
        manifest = bundle.version_manifests[0]
        base = {
            "state": "INSUFFICIENT_COVERAGE",
            "reason_codes": ("incomplete_scope",),
            "evidence_snapshot_ids": (),
        }
        with self.assertRaises(ContractValidationError):
            AnswerClaim.create(**base)
        with self.assertRaises(ContractValidationError):
            AnswerClaim.create(
                **base,
                claim_requirement=requirement,
                source_inventory=source_inventory,
                version_manifest=manifest,
            )
        with self.assertRaises(ContractValidationError):
            AnswerClaim.create(
                **base,
                coverage_ledger=ledger,
                claim_requirement=requirement,
                source_inventory=source_inventory,
            )
        with self.assertRaises(ContractValidationError):
            AnswerClaim.create(
                **base,
                coverage_ledger=ledger.to_dict(),
                claim_requirement=requirement,
                source_inventory=source_inventory,
                version_manifest=manifest,
            )
        with self.assertRaises(ContractValidationError):
            AnswerClaim.create(
                **base,
                coverage_ledger=ledger,
                claim_requirement=requirement,
                source_inventory=source_inventory,
                version_manifest=manifest,
                source_fingerprint=FP2,
            )
        stale_manifest = replace(manifest, index_freshness="stale")
        with self.assertRaises(ContractValidationError):
            AnswerClaim.create(
                **base,
                coverage_ledger=ledger,
                claim_requirement=requirement,
                source_inventory=source_inventory,
                version_manifest=stale_manifest,
            )
        mismatched_ledger = replace(
            ledger,
            version_binding=CoverageVersionBinding.from_manifest(
                replace(manifest, index_fingerprint=FP2)
            ),
            coverage_ledger_id="",
        )
        with self.assertRaises(ContractValidationError):
            AnswerClaim.create(
                **base,
                coverage_ledger=mismatched_ledger,
                claim_requirement=requirement,
                source_inventory=source_inventory,
                version_manifest=manifest,
            )
        wrong_requirement = ClaimRequirement.create(
            query_id="query_other",
            kind="single_value",
            target="ticket",
        )
        with self.assertRaises(ContractValidationError):
            AnswerClaim.create(
                **base,
                coverage_ledger=ledger,
                claim_requirement=wrong_requirement,
                source_inventory=source_inventory,
                version_manifest=manifest,
            )
        wrong_inventory = SourceInventory.create(
            source_asset_id="asset_other",
            source_fingerprint=FP,
            parser_fingerprint=FP2,
            items=(
                SourceInventoryItem.create(
                    source_asset_id="asset_other",
                    structure_kind="message",
                    content_type="message/rfc822",
                    ordinal=0,
                    processing_state="parsed",
                    raw_retention_state="retained",
                    source_fingerprint=FP,
                    parser_fingerprint=FP2,
                    permission_scope={"scope_type": "asset", "scope_id": "asset_other"},
                ),
            ),
        )
        with self.assertRaises(ContractValidationError):
            AnswerClaim.create(
                **base,
                coverage_ledger=ledger,
                claim_requirement=requirement,
                source_inventory=wrong_inventory,
                version_manifest=manifest,
            )
        authorization = CoverageAuthorizationBinding(
            actor_context_id="actor_wp1",
            permission_revision="permission_wp1",
            grant_revision="grant_wp1",
        )
        authorized_ledger = replace(
            ledger,
            authorization_binding=authorization,
            coverage_ledger_id="",
        )
        wrong_authorization = replace(
            authorization,
            grant_revision="grant_other",
        )
        with self.assertRaises(ContractValidationError):
            AnswerClaim.create(
                **base,
                coverage_ledger=authorized_ledger,
                claim_requirement=requirement,
                source_inventory=source_inventory,
                version_manifest=manifest,
            )
        with self.assertRaises(ContractValidationError):
            AnswerClaim.create(
                **base,
                coverage_ledger=authorized_ledger,
                claim_requirement=requirement,
                source_inventory=source_inventory,
                version_manifest=manifest,
                authorization_binding=wrong_authorization,
            )

    def test_stale_and_mismatched_fingerprints_are_representable_but_unusable(self) -> None:
        fresh = VersionManifest.create(
            source_fingerprint=FP,
            parser_fingerprint=FP,
            tokenizer_fingerprint=FP,
            index_fingerprint=FP,
            implementation_fingerprint=FP,
        )
        stale = replace(fresh, index_freshness="stale")
        mismatch = replace(fresh, index_fingerprint=FP2)
        self.assertFalse(stale.usable_for_claim(fresh))
        self.assertFalse(mismatch.usable_for_claim(fresh))
        with self.assertRaises(ContractValidationError):
            stale.assert_usable_for_claim(fresh)
        with self.assertRaises(ContractValidationError):
            mismatch.assert_usable_for_claim(fresh)
        with self.assertRaises(ContractValidationError):
            CoverageLedger(
                query_id="query_wp1",
                claim_requirement_id="requirement_wp1",
                source_inventory_id="inventory_wp1",
                relevant_inventory_item_ids=(),
                version_binding=CoverageVersionBinding.from_manifest(stale),
                complete_authorized_scope=True,
            )

    def test_migration_006_is_discoverable_and_replay_is_idempotent(self) -> None:
        manifest = migration_files()
        self.assertEqual(manifest[-1].filename, "006_evidence_coverage.sql")
        self.assertGreaterEqual(manifest[-1].statement_count, 12)
        ddl = Path("python/formowl_graph/storage/migrations/006_evidence_coverage.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("CREATE TABLE IF NOT EXISTS source_inventory", ddl)
        self.assertIn(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_mail_import_session_scope",
            ddl,
        )
        self.assertIn(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_mail_import_session_asset_scope",
            ddl,
        )
        self.assertIn("workspace_id text NOT NULL", ddl)
        self.assertIn("owner_user_id text NOT NULL", ddl)
        self.assertIn(
            "FOREIGN KEY (\n    mail_import_session_id,\n    workspace_id,\n    owner_user_id\n  ) REFERENCES mail_import_session",
            ddl,
        )
        self.assertIn(
            "source_inventory_id,\n    mail_import_session_id,\n    workspace_id,\n    owner_user_id,\n    source_asset_id,\n    source_fingerprint,\n    parser_fingerprint\n  ) REFERENCES source_inventory",
            ddl,
        )
        self.assertIn(
            "source_inventory_item_id,\n    source_inventory_id,\n    mail_import_session_id,\n    workspace_id,\n    owner_user_id,\n    source_asset_id,\n    source_fingerprint,\n    parser_fingerprint\n  ) REFERENCES source_inventory_item",
            ddl,
        )
        self.assertIn(
            "FOREIGN KEY (\n    coverage_ledger_id,\n    claim_requirement_id,\n    mail_import_session_id,\n    workspace_id,\n    owner_user_id\n  ) REFERENCES coverage_ledger",
            ddl,
        )
        connection = _MigrationConnection()
        first = PostgreSQLMigrationRunner(connection).migration_replay()
        second = PostgreSQLMigrationRunner(connection).migration_replay()
        self.assertEqual(len(first), len(second))
        self.assertTrue(
            any("CREATE TABLE IF NOT EXISTS coverage_ledger" in item.sql for item in first)
        )

    def test_bundle_and_postgres_rows_round_trip_wp1_records(self) -> None:
        bundle = _minimal_bundle()
        item = SourceInventoryItem.create(
            source_asset_id="asset_wp1",
            structure_kind="message",
            content_type="message/rfc822",
            ordinal=0,
            processing_state="intentionally_excluded",
            raw_retention_state="externally_managed",
            source_fingerprint=FP,
            parser_fingerprint=FP2,
            permission_scope={"scope_type": "asset", "scope_id": "asset_wp1"},
            exclusion_policy_version_id="policy_version_wp1",
            exclusion_authorized_actor_id="actor_wp1",
            exclusion_reason_code="outside_claim_scope",
            exclusion_claim_scope_proof_sha256=FP2,
        )
        inventory = SourceInventory.create(
            source_asset_id="asset_wp1",
            source_fingerprint=FP,
            parser_fingerprint=FP2,
            items=(item,),
            created_at="2026-07-24T00:00:00+00:00",
        )
        item = inventory.items[0]
        requirement = ClaimRequirement.create(
            query_id="query_wp1",
            kind="existential_witness",
            target="ticket",
        )
        ledger = CoverageLedger(
            query_id=requirement.query_id,
            claim_requirement_id=requirement.claim_requirement_id,
            source_inventory_id=inventory.source_inventory_id,
            relevant_inventory_item_ids=(item.source_inventory_item_id,),
            version_binding=None,
            complete_authorized_scope=False,
        )
        manifest = VersionManifest.create(
            source_fingerprint=FP,
            parser_fingerprint=FP2,
            tokenizer_fingerprint=FP,
            index_fingerprint=FP,
            implementation_fingerprint=FP,
        )
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
            proof_kind="intentionally_excluded",
        )
        ledger = replace(
            ledger,
            authorization_binding=authorization,
            version_binding=CoverageVersionBinding.from_manifest(manifest),
            proof_records=(proof,),
            coverage_ledger_id="",
        )
        claim = AnswerClaim.create(
            answer_claim_id="answer_claim_wp1",
            state="INSUFFICIENT_COVERAGE",
            reason_codes=("incomplete_scope",),
            coverage_ledger=ledger,
            claim_requirement=requirement,
            source_inventory=inventory,
            version_manifest=manifest,
            authorization_binding=authorization,
            claim_requirement_id=requirement.claim_requirement_id,
            coverage_ledger_id=ledger.coverage_ledger_id,
            evidence_snapshot_ids=(),
            source_fingerprint=manifest.source_fingerprint,
            parser_fingerprint=manifest.parser_fingerprint,
            tokenizer_fingerprint=manifest.tokenizer_fingerprint,
            index_fingerprint=manifest.index_fingerprint,
            version_manifest_id=manifest.version_manifest_id,
            implementation_fingerprint=manifest.implementation_fingerprint,
        )
        populated = replace(
            bundle,
            source_inventory=[inventory],
            claim_requirements=[requirement],
            coverage_ledgers=[ledger],
            answer_claims=[claim],
            version_manifests=[manifest],
        )
        payload = populated.to_persistence_dict()
        restored = MailEvidenceBundle.from_persistence_dict(payload)
        self.assertEqual(restored.to_persistence_dict(), payload)

        connection = _RowsConnection()
        store = PostgreSQLMailEvidenceStore(connection)
        statements = store.upsert_bundle(restored)
        self.assertTrue(
            {
                "source_inventory",
                "source_inventory_item",
                "claim_requirement",
                "coverage_ledger",
                "version_manifest",
            }.issubset(
                {
                    statement.sql.split("INSERT INTO ", 1)[1].split(" ", 1)[0]
                    for statement in statements
                }
            )
        )
        source_inventory_statement = next(
            statement
            for statement in statements
            if "INSERT INTO source_inventory " in statement.sql
        )
        self.assertIn(
            "(source_inventory_id, mail_import_session_id, workspace_id, owner_user_id, "
            "source_asset_id, source_fingerprint, parser_fingerprint",
            source_inventory_statement.sql,
        )
        self.assertEqual(
            source_inventory_statement.parameters["workspace_id"],
            restored.mail_import_session.workspace_id,
        )
        self.assertEqual(
            source_inventory_statement.parameters["owner_user_id"],
            restored.mail_import_session.owner_user_id,
        )
        source_inventory_item_statement = next(
            statement
            for statement in statements
            if "INSERT INTO source_inventory_item " in statement.sql
        )
        self.assertIn(
            "(source_inventory_item_id, mail_import_session_id, workspace_id, owner_user_id, "
            "source_inventory_id, source_asset_id, source_fingerprint, parser_fingerprint",
            source_inventory_item_statement.sql,
        )
        coverage_statement = next(
            statement for statement in statements if "INSERT INTO coverage_ledger " in statement.sql
        )
        self.assertIn("source_inventory_id", coverage_statement.sql)
        answer_claim_statement = next(
            statement for statement in statements if "INSERT INTO answer_claim " in statement.sql
        )
        self.assertIn("claim_requirement_id", answer_claim_statement.sql)
        self.assertIn("coverage_ledger_id", answer_claim_statement.sql)
        round_trip = store.get_bundle(
            mail_import_session_id=restored.mail_import_session.mail_import_session_id
        )
        self.assertIsNotNone(round_trip)
        self.assertEqual(round_trip.to_persistence_dict(), payload)
        self.assertEqual(
            _selected_columns(connection.queries[0].sql),
            (
                "payload",
                "mail_import_session_id",
                "workspace_id",
                "owner_user_id",
                "mail_evidence_bundle_id",
                "producer_type",
                "bundle_created_at",
            ),
        )
        self.assertEqual(
            round_trip.source_inventory[0].items[0].exclusion_claim_scope_proof_sha256,
            FP2,
        )
        self.assertEqual(
            set(evidence_coverage_postgre_sql_tables()),
            {
                "source_inventory",
                "source_inventory_item",
                "structural_observation",
                "claim_requirement",
                "coverage_ledger",
                "answer_claim",
                "version_manifest",
            },
        )

    def test_private_bundle_requires_explicit_wp1_state_marker_and_families(self) -> None:
        payload = _minimal_bundle().to_persistence_dict()
        self.assertEqual(
            payload["wp1_persistence"]["family_counts"],
            {
                "source_inventory": 0,
                "source_inventory_items": 0,
                "structural_observations": 0,
                "claim_requirements": 0,
                "coverage_ledgers": 0,
                "answer_claims": 0,
                "version_manifests": 0,
            },
        )
        for field_name in ("wp1_persistence", *_WP1_FAMILY_FIELDS_FOR_TESTS):
            with self.subTest(field_name=field_name):
                malformed = deepcopy(payload)
                malformed.pop(field_name)
                with self.assertRaises(ContractValidationError):
                    MailEvidenceBundle.from_persistence_dict(malformed)

        malformed_marker = deepcopy(payload)
        malformed_marker["wp1_persistence"]["family_counts"]["coverage_ledgers"] = 1
        with self.assertRaises(ContractValidationError):
            MailEvidenceBundle.from_persistence_dict(malformed_marker)

    def test_genuinely_empty_private_bundle_round_trips_with_wp1_marker(self) -> None:
        payload = _minimal_bundle().to_persistence_dict()
        restored = MailEvidenceBundle.from_persistence_dict(payload)
        self.assertEqual(restored.to_persistence_dict(), payload)

    def test_bundle_order_is_canonical_for_file_and_postgres_round_trips(self) -> None:
        bundle, inventory, requirement, _ = _inventory_bundle()
        first_item = SourceInventoryItem.create(
            **{
                key: value
                for key, value in inventory.items[0].to_persistence_dict().items()
                if key != "source_inventory_id"
            }
        )
        second_item = SourceInventoryItem.create(
            source_asset_id=inventory.source_asset_id,
            structure_kind="message",
            content_type="message/rfc822",
            ordinal=1,
            processing_state="failed",
            raw_retention_state="retained",
            source_fingerprint=inventory.source_fingerprint,
            parser_fingerprint=inventory.parser_fingerprint,
            permission_scope={"scope_type": "asset", "scope_id": "asset_wp1"},
        )
        inventory = SourceInventory.create(
            source_asset_id=inventory.source_asset_id,
            source_fingerprint=inventory.source_fingerprint,
            parser_fingerprint=inventory.parser_fingerprint,
            items=(first_item, second_item),
            created_at=inventory.created_at,
        )
        manifest = bundle.version_manifests[0]
        ledger = CoverageLedger(
            query_id=requirement.query_id,
            claim_requirement_id=requirement.claim_requirement_id,
            source_inventory_id=inventory.source_inventory_id,
            relevant_inventory_item_ids=tuple(
                item.source_inventory_item_id for item in inventory.items
            ),
            version_binding=CoverageVersionBinding.from_manifest(manifest),
            complete_authorized_scope=False,
        )
        claim = AnswerClaim.create(
            answer_claim_id="answer_inventory_order_wp1",
            state="INSUFFICIENT_COVERAGE",
            reason_codes=("incomplete_scope",),
            coverage_ledger=ledger,
            claim_requirement=requirement,
            source_inventory=inventory,
            version_manifest=manifest,
            claim_requirement_id=requirement.claim_requirement_id,
            coverage_ledger_id=ledger.coverage_ledger_id,
            evidence_snapshot_ids=(),
        )
        bundle = replace(
            bundle,
            source_inventory=[inventory],
            coverage_ledgers=[ledger],
            answer_claims=[claim],
        )
        canonical_payload = bundle.to_persistence_dict()
        permuted_payload = deepcopy(canonical_payload)
        permuted_payload["source_inventory"][0]["items"].reverse()
        permuted_payload["source_inventory_items"].reverse()
        restored = MailEvidenceBundle.from_persistence_dict(permuted_payload)

        self.assertEqual(restored.to_persistence_dict(), canonical_payload)

        authorization = CoverageAuthorizationBinding(
            actor_context_id="actor_order_wp1",
            permission_revision="permission_order_wp1",
            grant_revision="grant_order_wp1",
        )
        decision = StructuralPublicScopeDecision.authorize(
            permission_scope=inventory.items[0].permission_scope,
            authorization_binding=authorization,
        )
        self.assertEqual(
            restored.to_public_dict(
                scope_decision=decision,
                include_answer_claims=True,
            ),
            bundle.to_public_dict(
                scope_decision=decision,
                include_answer_claims=True,
            ),
        )

        connection = _RowsConnection(reverse_query_rows=True)
        store = PostgreSQLMailEvidenceStore(connection)
        store.upsert_bundle(restored)
        postgres_restored = store.get_bundle(
            mail_import_session_id=restored.mail_import_session.mail_import_session_id
        )
        self.assertIsNotNone(postgres_restored)
        assert postgres_restored is not None
        self.assertEqual(postgres_restored.to_persistence_dict(), canonical_payload)
        self.assertEqual(
            postgres_restored.to_public_dict(
                scope_decision=decision,
                include_answer_claims=True,
            ),
            restored.to_public_dict(
                scope_decision=decision,
                include_answer_claims=True,
            ),
        )

    def test_postgres_rejects_legacy_and_partial_wp1_state(self) -> None:
        empty_bundle = _minimal_bundle()
        connection = _RowsConnection()
        store = PostgreSQLMailEvidenceStore(connection)
        store.upsert_bundle(empty_bundle)
        session_id = empty_bundle.mail_import_session.mail_import_session_id
        session_payload = connection.rows["mail_import_session"][session_id]["payload"]
        session_payload.pop("wp1_persistence")
        with self.assertRaises(ContractValidationError):
            store.get_bundle(mail_import_session_id=session_id)
        self.assertEqual(len(connection.queries), 1)

        populated_bundle, _, _, _ = _inventory_bundle()
        connection = _RowsConnection()
        store = PostgreSQLMailEvidenceStore(connection)
        store.upsert_bundle(populated_bundle)
        session_id = populated_bundle.mail_import_session.mail_import_session_id
        del connection.rows["version_manifest"]
        with self.assertRaises(ContractValidationError):
            store.get_bundle(mail_import_session_id=session_id)

    def test_source_inventory_insert_sql_matches_006_ddl_columns(self) -> None:
        bundle, inventory, _, _ = _inventory_bundle()
        statements = PostgreSQLMailEvidenceStore(_RowsConnection()).upsert_bundle(bundle)
        statement = next(
            statement
            for statement in statements
            if "INSERT INTO source_inventory " in statement.sql
        )

        insert_columns = _insert_columns(statement.sql)
        ddl = Path("python/formowl_graph/storage/migrations/006_evidence_coverage.sql").read_text(
            encoding="utf-8"
        )
        ddl_columns = _create_table_columns(ddl, "source_inventory")
        self.assertEqual(
            insert_columns,
            ddl_columns - {"updated_at"},
        )
        self.assertEqual(
            set(statement.parameters),
            insert_columns,
        )
        self.assertEqual(
            {
                "source_inventory_id",
                "mail_import_session_id",
                "source_asset_id",
                "source_fingerprint",
                "parser_fingerprint",
                "workspace_id",
                "owner_user_id",
                "payload",
                "payload_hash",
            },
            insert_columns,
        )
        self.assertEqual(
            statement.parameters["source_inventory_id"],
            inventory.source_inventory_id,
        )

    def test_all_scoped_wp1_insert_sql_matches_006_ddl_columns(self) -> None:
        bundle, inventory, _, _ = _inventory_bundle()
        observation = StructuralObservation.create(
            source_inventory_item_id=inventory.items[0].source_inventory_item_id,
            source_asset_id=inventory.source_asset_id,
            source_observation_id="observation_scope_wp1",
            structure_kind="table",
            columns=(),
            rows=(),
            header_relationships=(),
            source_fingerprint=inventory.source_fingerprint,
            parser_fingerprint=inventory.parser_fingerprint,
        )
        bundle = replace(bundle, structural_observations=[observation])
        statements = PostgreSQLMailEvidenceStore(_RowsConnection()).upsert_bundle(bundle)
        ddl = Path("python/formowl_graph/storage/migrations/006_evidence_coverage.sql").read_text(
            encoding="utf-8"
        )
        for table_name in (
            "source_inventory",
            "source_inventory_item",
            "structural_observation",
            "claim_requirement",
            "coverage_ledger",
            "answer_claim",
        ):
            with self.subTest(table_name=table_name):
                statement = next(
                    statement
                    for statement in statements
                    if f"INSERT INTO {table_name} " in statement.sql
                )
                insert_columns = _insert_columns(statement.sql)
                self.assertEqual(
                    insert_columns,
                    _create_table_columns(ddl, table_name) - {"updated_at"},
                )
                self.assertEqual(set(statement.parameters), insert_columns)

    def test_wp1_immutable_rows_are_idempotent_and_reject_collisions(self) -> None:
        bundle, inventory, _, _ = _inventory_bundle()
        observation = StructuralObservation.create(
            source_inventory_item_id=inventory.items[0].source_inventory_item_id,
            source_asset_id=inventory.source_asset_id,
            source_observation_id="observation_append_only_wp1",
            structure_kind="table",
            columns=(),
            rows=(),
            header_relationships=(),
            source_fingerprint=inventory.source_fingerprint,
            parser_fingerprint=inventory.parser_fingerprint,
        )
        bundle = replace(bundle, structural_observations=[observation])
        connection = _RowsConnection()
        store = PostgreSQLMailEvidenceStore(connection)

        statements = store.upsert_bundle(bundle)
        first_rows = deepcopy(connection.rows)
        store.upsert_bundle(bundle)
        self.assertEqual(connection.rows, first_rows)

        wp1_tables = (
            "source_inventory",
            "source_inventory_item",
            "structural_observation",
            "claim_requirement",
            "coverage_ledger",
            "answer_claim",
            "version_manifest",
        )
        ddl = Path("python/formowl_graph/storage/migrations/006_evidence_coverage.sql").read_text(
            encoding="utf-8"
        )
        for table_name in wp1_tables:
            with self.subTest(table_name=table_name):
                statement = next(
                    statement
                    for statement in statements
                    if f"INSERT INTO {table_name} " in statement.sql
                )
                self.assertIn("payload_hash = CASE", statement.sql)
                self.assertIn("IS NOT DISTINCT FROM EXCLUDED.payload", statement.sql)
                self.assertIn("IS NOT DISTINCT FROM EXCLUDED.payload_hash", statement.sql)
                self.assertIn("ELSE NULL", statement.sql)
                self.assertNotIn("payload = EXCLUDED.payload", statement.sql)
                id_field = statement.sql.split("(", 1)[1].split(",", 1)[0]
                for field_name in statement.parameters:
                    if field_name not in {id_field, "payload", "payload_hash"}:
                        self.assertIn(
                            f"{table_name}.{field_name} IS NOT DISTINCT FROM "
                            f"EXCLUDED.{field_name}",
                            statement.sql,
                        )
                table_ddl = ddl.split(f"CREATE TABLE IF NOT EXISTS {table_name} (", 1)[1].split(
                    ");", 1
                )[0]
                self.assertIn("payload_hash text NOT NULL", table_ddl)

                changed_payload = deepcopy(statement.parameters)
                changed_payload["payload"] = {
                    **changed_payload["payload"],
                    "append_only_collision": table_name,
                }
                with self.assertRaises(ContractValidationError):
                    connection.execute(
                        SQLStatement(
                            sql=statement.sql,
                            parameters=changed_payload,
                        )
                    )
                self.assertEqual(connection.rows, first_rows)

                changed_hash = deepcopy(statement.parameters)
                changed_hash["payload_hash"] = changed_hash["payload_hash"] + "-collision"
                with self.assertRaises(ContractValidationError):
                    connection.execute(
                        SQLStatement(
                            sql=statement.sql,
                            parameters=changed_hash,
                        )
                    )
                self.assertEqual(connection.rows, first_rows)

                relationship_field = next(
                    field_name
                    for field_name in statement.parameters
                    if field_name not in {id_field, "payload", "payload_hash"}
                )
                changed_relationship = deepcopy(statement.parameters)
                changed_relationship[relationship_field] = (
                    changed_relationship[relationship_field] + "-collision"
                )
                with self.assertRaises(ContractValidationError):
                    connection.execute(
                        SQLStatement(
                            sql=statement.sql,
                            parameters=changed_relationship,
                        )
                    )
                self.assertEqual(connection.rows, first_rows)

    def test_postgres_scoped_relationship_rows_fail_closed(self) -> None:
        bundle, inventory, _, ledger = _inventory_bundle()
        observation = StructuralObservation.create(
            source_inventory_item_id=inventory.items[0].source_inventory_item_id,
            source_asset_id=inventory.source_asset_id,
            source_observation_id="observation_scope_wp1",
            structure_kind="table",
            columns=(),
            rows=(),
            header_relationships=(),
            source_fingerprint=inventory.source_fingerprint,
            parser_fingerprint=inventory.parser_fingerprint,
        )
        bundle = replace(bundle, structural_observations=[observation])
        row_keys = (
            ("source_inventory", inventory.source_inventory_id),
            ("source_inventory_item", inventory.items[0].source_inventory_item_id),
            ("structural_observation", observation.structural_observation_id),
            ("claim_requirement", bundle.claim_requirements[0].claim_requirement_id),
            ("coverage_ledger", ledger.coverage_ledger_id),
            ("answer_claim", "answer_inventory_wp1"),
        )
        for table_name, row_key in row_keys:
            for scope_field in (
                "mail_import_session_id",
                "workspace_id",
                "owner_user_id",
            ):
                with self.subTest(table_name=table_name, scope_field=scope_field):
                    connection = _RowsConnection(ignore_import_scope_filter=True)
                    store = PostgreSQLMailEvidenceStore(connection)
                    store.upsert_bundle(bundle)
                    connection.rows[table_name][row_key][scope_field] = "scope_other"
                    with self.assertRaises(ContractValidationError):
                        store.get_bundle(
                            mail_import_session_id=(
                                bundle.mail_import_session.mail_import_session_id
                            )
                        )

    def test_postgres_scoped_relationship_columns_fail_closed(self) -> None:
        bundle, inventory, _, ledger = _inventory_bundle()
        observation = StructuralObservation.create(
            source_inventory_item_id=inventory.items[0].source_inventory_item_id,
            source_asset_id=inventory.source_asset_id,
            source_observation_id="observation_scope_wp1",
            structure_kind="table",
            columns=(),
            rows=(),
            header_relationships=(),
            source_fingerprint=inventory.source_fingerprint,
            parser_fingerprint=inventory.parser_fingerprint,
        )
        bundle = replace(bundle, structural_observations=[observation])
        cases = (
            (
                "source_inventory_item",
                inventory.items[0].source_inventory_item_id,
                "source_inventory_id",
            ),
            (
                "structural_observation",
                observation.structural_observation_id,
                "source_inventory_id",
            ),
            ("coverage_ledger", ledger.coverage_ledger_id, "source_inventory_id"),
            ("coverage_ledger", ledger.coverage_ledger_id, "claim_requirement_id"),
            ("answer_claim", "answer_inventory_wp1", "coverage_ledger_id"),
            ("answer_claim", "answer_inventory_wp1", "claim_requirement_id"),
        )
        for table_name, row_key, field_name in cases:
            with self.subTest(table_name=table_name, field_name=field_name):
                connection = _RowsConnection(ignore_import_scope_filter=True)
                store = PostgreSQLMailEvidenceStore(connection)
                store.upsert_bundle(bundle)
                connection.rows[table_name][row_key][field_name] = "relationship_other"
                with self.assertRaises(ContractValidationError):
                    store.get_bundle(
                        mail_import_session_id=bundle.mail_import_session.mail_import_session_id
                    )

    def test_source_inventory_relational_integrity_fails_closed_in_file_payloads(self) -> None:
        bundle, inventory, requirement, ledger = _inventory_bundle()
        payload = bundle.to_persistence_dict()

        mismatched_inventory = deepcopy(payload)
        mismatched_inventory["source_inventory"][0]["items"][0]["source_inventory_id"] = (
            "inventory_other"
        )
        with self.assertRaises(ContractValidationError):
            MailEvidenceBundle.from_persistence_dict(mismatched_inventory)

        mismatched_asset = deepcopy(payload)
        mismatched_asset["source_inventory"][0]["items"][0]["source_asset_id"] = "asset_other"
        with self.assertRaises(ContractValidationError):
            MailEvidenceBundle.from_persistence_dict(mismatched_asset)

        orphan_projection = deepcopy(payload)
        orphan_projection["source_inventory_items"].append(
            {
                **orphan_projection["source_inventory_items"][0],
                "source_inventory_item_id": "orphan_item_wp1",
            }
        )
        with self.assertRaises(ContractValidationError):
            MailEvidenceBundle.from_persistence_dict(orphan_projection)

        orphan_ledger = deepcopy(payload)
        orphan_ledger["coverage_ledgers"][0]["source_inventory_id"] = "inventory_other"
        with self.assertRaises(ContractValidationError):
            MailEvidenceBundle.from_persistence_dict(orphan_ledger)

        mismatched_ledger_claim = deepcopy(payload)
        mismatched_ledger_claim["coverage_ledgers"][0]["claim_requirement_id"] = "requirement_other"
        with self.assertRaises(ContractValidationError):
            MailEvidenceBundle.from_persistence_dict(mismatched_ledger_claim)

        orphan_claim = deepcopy(payload)
        orphan_claim["answer_claims"][0]["coverage_ledger_id"] = "coverage_other"
        with self.assertRaises(ContractValidationError):
            MailEvidenceBundle.from_persistence_dict(orphan_claim)

        mismatched_claim = deepcopy(payload)
        mismatched_claim["answer_claims"][0]["claim_requirement_id"] = "requirement_other"
        with self.assertRaises(ContractValidationError):
            MailEvidenceBundle.from_persistence_dict(mismatched_claim)

        self.assertEqual(
            ledger.source_inventory_id,
            inventory.source_inventory_id,
        )
        self.assertEqual(
            ledger.claim_requirement_id,
            requirement.claim_requirement_id,
        )

    def test_postgres_inventory_foreign_relationships_fail_closed_on_read(self) -> None:
        bundle, inventory, _, ledger = _inventory_bundle()
        connection = _RowsConnection()
        store = PostgreSQLMailEvidenceStore(connection)
        store.upsert_bundle(bundle)

        del connection.rows["source_inventory"][inventory.source_inventory_id]
        with self.assertRaises(ContractValidationError):
            store.get_bundle(
                mail_import_session_id=bundle.mail_import_session.mail_import_session_id
            )

        connection = _RowsConnection()
        store = PostgreSQLMailEvidenceStore(connection)
        store.upsert_bundle(bundle)
        child_row = connection.rows["source_inventory_item"][
            inventory.items[0].source_inventory_item_id
        ]
        child_row["payload"]["source_asset_id"] = "asset_other"
        with self.assertRaises(ContractValidationError):
            store.get_bundle(
                mail_import_session_id=bundle.mail_import_session.mail_import_session_id
            )

        connection = _RowsConnection()
        store = PostgreSQLMailEvidenceStore(connection)
        store.upsert_bundle(bundle)
        connection.rows["coverage_ledger"][ledger.coverage_ledger_id]["payload"][
            "source_inventory_id"
        ] = "inventory_other"
        with self.assertRaises(ContractValidationError):
            store.get_bundle(
                mail_import_session_id=bundle.mail_import_session.mail_import_session_id
            )

        connection = _RowsConnection()
        store = PostgreSQLMailEvidenceStore(connection)
        store.upsert_bundle(bundle)
        connection.rows["answer_claim"]["answer_inventory_wp1"]["payload"][
            "claim_requirement_id"
        ] = "requirement_other"
        with self.assertRaises(ContractValidationError):
            store.get_bundle(
                mail_import_session_id=bundle.mail_import_session.mail_import_session_id
            )

    def test_malformed_wp1_row_fails_before_return(self) -> None:
        bundle = _minimal_bundle()
        connection = _RowsConnection()
        store = PostgreSQLMailEvidenceStore(connection)
        store.upsert_bundle(bundle)
        connection.rows["source_inventory_item"] = {
            "bad": {
                "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
                "payload": {"processing_state": "invalid"},
            }
        }
        with self.assertRaises(ContractValidationError):
            store.get_bundle(
                mail_import_session_id=bundle.mail_import_session.mail_import_session_id
            )

    def test_wp1_write_rolls_back_without_partial_rows(self) -> None:
        bundle = _minimal_bundle()
        item = SourceInventoryItem.create(
            source_asset_id="asset_wp1",
            structure_kind="message",
            content_type="message/rfc822",
            ordinal=0,
            processing_state="failed",
            raw_retention_state="retained",
            source_fingerprint=FP,
            parser_fingerprint=FP2,
            permission_scope={"scope_type": "asset", "scope_id": "asset_wp1"},
        )
        inventory = SourceInventory.create(
            source_asset_id="asset_wp1",
            source_fingerprint=FP,
            parser_fingerprint=FP2,
            items=(item,),
            created_at="2026-07-24T00:00:00+00:00",
        )
        bundle = replace(bundle, source_inventory=[inventory])
        connection = _RowsConnection(fail_after_execute=2)
        with self.assertRaises(RuntimeError):
            with PostgreSQLUnitOfWork(connection) as unit:
                PostgreSQLMailEvidenceStore(connection).upsert_bundle(
                    bundle,
                    transaction=unit,
                )
                unit.commit()
        self.assertEqual(connection.rows, {})


def _excluded_item(*, proof: str = FP) -> SourceInventoryItem:
    return SourceInventoryItem.create(
        source_asset_id="asset_wp1",
        structure_kind="message",
        content_type="message/rfc822",
        ordinal=0,
        processing_state="intentionally_excluded",
        raw_retention_state="retained",
        source_fingerprint=FP,
        parser_fingerprint=FP2,
        permission_scope={"scope_type": "asset", "scope_id": "asset_wp1"},
        exclusion_policy_version_id="policy_version_wp1",
        exclusion_authorized_actor_id="actor_wp1",
        exclusion_reason_code="outside_claim_scope",
        exclusion_claim_scope_proof_sha256=proof,
    )


def _public_structural_fixture() -> (
    tuple[
        SourceInventoryItem,
        SourceInventory,
        StructuralObservation,
        CoverageAuthorizationBinding,
    ]
):
    authorization = CoverageAuthorizationBinding(
        actor_context_id="actor_public_wp1",
        permission_revision="permission_public_wp1",
        grant_revision="grant_public_wp1",
    )
    item = SourceInventoryItem.create(
        source_asset_id="asset_wp1",
        structure_kind="html_table",
        content_type="text/html",
        ordinal=0,
        processing_state="parsed",
        raw_retention_state="retained",
        source_fingerprint=FP,
        parser_fingerprint=FP2,
        permission_scope={
            "scope_type": "asset",
            "scope_id": "asset_wp1",
            "visibility": "restricted",
        },
        location={"location_detail": "private/table.pst", "table_ordinal": 0},
        source_observation_ids=("observation_public_wp1",),
    )
    inventory = SourceInventory.create(
        source_asset_id="asset_wp1",
        source_fingerprint=FP,
        parser_fingerprint=FP2,
        items=(item,),
        created_at="2026-07-24T00:00:00+00:00",
    )
    item = inventory.items[0]
    observation = StructuralObservation.create(
        source_inventory_item_id=item.source_inventory_item_id,
        source_asset_id=item.source_asset_id,
        source_observation_id="observation_public_wp1",
        structure_kind="html_table",
        columns=(
            StructuralColumn(
                column_ordinal=0,
                original_header="Status",
                normalized_header="status",
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
                        value="Open",
                        normalized_value="open",
                    ),
                ),
            ),
        ),
        header_relationships=({"header_path": ["Status"]},),
        source_fingerprint=FP,
        parser_fingerprint=FP2,
    )
    return item, inventory, observation, authorization


def _inventory_bundle() -> (
    tuple[
        MailEvidenceBundle,
        SourceInventory,
        ClaimRequirement,
        CoverageLedger,
    ]
):
    bundle = _minimal_bundle()
    item = SourceInventoryItem.create(
        source_asset_id="asset_wp1",
        structure_kind="message",
        content_type="message/rfc822",
        ordinal=0,
        processing_state="parsed",
        raw_retention_state="retained",
        source_fingerprint=FP,
        parser_fingerprint=FP2,
        permission_scope={"scope_type": "asset", "scope_id": "asset_wp1"},
        source_observation_ids=(),
    )
    inventory = SourceInventory.create(
        source_asset_id="asset_wp1",
        source_fingerprint=FP,
        parser_fingerprint=FP2,
        items=(item,),
        created_at="2026-07-24T00:00:00+00:00",
    )
    requirement = ClaimRequirement.create(
        query_id="query_inventory_wp1",
        kind="single_value",
        target="ticket",
        created_at="2026-07-24T00:00:00+00:00",
    )
    manifest = VersionManifest.create(
        source_fingerprint=FP,
        parser_fingerprint=FP2,
        tokenizer_fingerprint=FP,
        index_fingerprint=FP,
        implementation_fingerprint=FP,
        created_at="2026-07-24T00:00:00+00:00",
    )
    ledger = CoverageLedger(
        query_id=requirement.query_id,
        claim_requirement_id=requirement.claim_requirement_id,
        source_inventory_id=inventory.source_inventory_id,
        relevant_inventory_item_ids=(inventory.items[0].source_inventory_item_id,),
        version_binding=CoverageVersionBinding.from_manifest(manifest),
        complete_authorized_scope=False,
    )
    claim = AnswerClaim.create(
        answer_claim_id="answer_inventory_wp1",
        state="INSUFFICIENT_COVERAGE",
        reason_codes=("incomplete_scope",),
        coverage_ledger=ledger,
        claim_requirement=requirement,
        source_inventory=inventory,
        version_manifest=manifest,
        claim_requirement_id=requirement.claim_requirement_id,
        coverage_ledger_id=ledger.coverage_ledger_id,
        evidence_snapshot_ids=(),
    )
    populated = replace(
        bundle,
        source_inventory=[inventory],
        claim_requirements=[requirement],
        coverage_ledgers=[ledger],
        answer_claims=[claim],
        version_manifests=[manifest],
    )
    return populated, inventory, requirement, ledger


def _direct_claim_fixture(
    *,
    kind: str,
    parameters: dict[str, object] | None = None,
    include_direct_proof: bool = True,
    include_conflicting_values: bool = False,
) -> tuple[
    SourceInventory,
    ClaimRequirement,
    VersionManifest,
    CoverageAuthorizationBinding,
    CoverageLedger,
]:
    item = SourceInventoryItem.create(
        source_asset_id="asset_direct_wp1",
        structure_kind="message",
        content_type="message/rfc822",
        ordinal=0,
        processing_state="parsed",
        raw_retention_state="retained",
        source_fingerprint=FP,
        parser_fingerprint=FP2,
        permission_scope={"scope_type": "asset", "scope_id": "asset_direct_wp1"},
        source_observation_ids=(
            "observation_direct_wp1_a",
            "observation_direct_wp1_b",
        ),
    )
    inventory = SourceInventory.create(
        source_asset_id="asset_direct_wp1",
        source_fingerprint=FP,
        parser_fingerprint=FP2,
        items=(item,),
        created_at="2026-07-24T00:00:00+00:00",
    )
    requirement = ClaimRequirement.create(
        query_id=f"query_direct_{kind}",
        kind=kind,
        target="ticket",
        parameters=parameters or {},
        created_at="2026-07-24T00:00:00+00:00",
    )
    manifest = VersionManifest.create(
        source_fingerprint=FP,
        parser_fingerprint=FP2,
        tokenizer_fingerprint=FP,
        index_fingerprint=FP,
        implementation_fingerprint=FP,
        created_at="2026-07-24T00:00:00+00:00",
    )
    authorization = CoverageAuthorizationBinding(
        actor_context_id="actor_direct_wp1",
        permission_revision="permission_direct_wp1",
        grant_revision="grant_direct_wp1",
    )
    proof_records: list[CoverageProofRecord] = []
    if include_direct_proof:
        proof_records.append(
            CoverageProofRecord.create(
                source_inventory_id=inventory.source_inventory_id,
                claim_requirement_id=requirement.claim_requirement_id,
                version_manifest_id=manifest.version_manifest_id,
                inventory_item_id=inventory.items[0].source_inventory_item_id,
                proof_kind="structural",
                structural_observation_ids=("observation_direct_wp1_a",),
                populated_value_fingerprint=(FP if include_conflicting_values else None),
            )
        )
    if include_conflicting_values:
        proof_records.append(
            CoverageProofRecord.create(
                source_inventory_id=inventory.source_inventory_id,
                claim_requirement_id=requirement.claim_requirement_id,
                version_manifest_id=manifest.version_manifest_id,
                inventory_item_id=inventory.items[0].source_inventory_item_id,
                proof_kind="structural",
                structural_observation_ids=("observation_direct_wp1_b",),
                populated_value_fingerprint=FP2,
            )
        )
    ledger = CoverageLedger.create(
        query_id=requirement.query_id,
        claim_requirement_id=requirement.claim_requirement_id,
        source_inventory_id=inventory.source_inventory_id,
        relevant_inventory_item_ids=(inventory.items[0].source_inventory_item_id,),
        searched_structural_observation_ids=(
            "observation_direct_wp1_a",
            "observation_direct_wp1_b",
        ),
        authorization_binding=authorization,
        version_binding=CoverageVersionBinding.from_manifest(manifest),
        proof_records=proof_records,
        complete_authorized_scope=False,
    )
    return inventory, requirement, manifest, authorization, ledger


def _minimal_bundle() -> MailEvidenceBundle:
    session = MailImportSession(
        mail_import_session_id="mailimport_wp1",
        workspace_id="workspace_wp1",
        owner_user_id="owner_wp1",
        source_asset_id="asset_wp1",
        archive_sha256=FP,
        retention_policy="retain_7_days",
        raw_archive_retention_decision="retained_by_policy",
        created_at="2026-07-24T00:00:00+00:00",
        upload_session_id="upload_wp1",
    )
    parse_run = MailParseRun(
        mail_parse_run_id="mailparse_wp1",
        mail_import_session_id=session.mail_import_session_id,
        extractor_run_id="run_wp1",
        parser_name="parser_wp1",
        parser_version="1",
        input_hash=FP,
        config_hash=FP2,
        status="succeeded",
        started_at=session.created_at,
        completed_at=session.created_at,
    )
    return MailEvidenceBundle(
        mail_evidence_bundle_id="bundle_wp1",
        producer_type="fixture_parser",
        mail_import_session=session,
        archive_occurrences=[],
        folder_occurrences=[],
        messages=[],
        message_occurrences=[],
        body_segments=[],
        attachments=[],
        attachment_occurrences=[],
        quoted_message_candidates=[],
        embedded_message_relations=[],
        mail_parse_run=parse_run,
        created_at=session.created_at,
    )


class _RowsConnection:
    def __init__(
        self,
        *,
        fail_after_execute: int | None = None,
        ignore_import_scope_filter: bool = False,
        reverse_query_rows: bool = False,
    ) -> None:
        self.rows: dict[str, dict[str, dict[str, object]]] = {}
        self.fail_after_execute = fail_after_execute
        self.ignore_import_scope_filter = ignore_import_scope_filter
        self.reverse_query_rows = reverse_query_rows
        self.execute_count = 0
        self.snapshot: dict[str, dict[str, dict[str, object]]] | None = None
        self.queries: list[object] = []

    def begin(self) -> None:
        self.snapshot = deepcopy(self.rows)

    def commit(self) -> None:
        self.snapshot = None

    def rollback(self) -> None:
        self.rows = {} if self.snapshot is None else self.snapshot
        self.snapshot = None

    def execute(self, statement: object) -> None:
        self.execute_count += 1
        if self.fail_after_execute is not None and self.execute_count >= self.fail_after_execute:
            raise RuntimeError("simulated WP1 write failure")
        sql = statement.sql
        table = sql.split("INSERT INTO ", 1)[1].split(" ", 1)[0]
        key = {
            "mail_import_session": "mail_import_session_id",
            "source_inventory": "source_inventory_id",
            "source_inventory_item": "source_inventory_item_id",
            "structural_observation": "structural_observation_id",
            "claim_requirement": "claim_requirement_id",
            "coverage_ledger": "coverage_ledger_id",
            "version_manifest": "version_manifest_id",
            "answer_claim": "answer_claim_id",
        }.get(table, next(iter(statement.parameters)))
        record_id = str(statement.parameters[key])
        existing = self.rows.get(table, {}).get(record_id)
        if existing is not None and "payload_hash = CASE" in sql:
            immutable_fields = set(statement.parameters) - {"payload", "payload_hash"}
            if any(
                existing.get(field_name) != statement.parameters.get(field_name)
                for field_name in immutable_fields
            ) or existing.get("payload") != statement.parameters.get("payload"):
                raise ContractValidationError("immutable persisted mail evidence record collision")
            if existing.get("payload_hash") != statement.parameters.get("payload_hash"):
                raise ContractValidationError("immutable persisted mail evidence record collision")
            return
        self.rows.setdefault(table, {})[record_id] = dict(statement.parameters)

    def query_one(self, statement: object) -> dict[str, object] | None:
        self.queries.append(statement)
        rows = self.rows.get("mail_import_session", {})
        for row in rows.values():
            if (
                statement.parameters["mail_import_session_id"] is None
                or row["mail_import_session_id"] == statement.parameters["mail_import_session_id"]
            ) and (
                statement.parameters["mail_evidence_bundle_id"] is None
                or row["mail_evidence_bundle_id"] == statement.parameters["mail_evidence_bundle_id"]
            ):
                return {key: row[key] for key in _selected_columns(statement.sql) if key in row}
        return None

    def query_all(self, statement: object) -> list[dict[str, object]]:
        self.queries.append(statement)
        sql = statement.sql
        table = sql.split(" FROM ", 1)[1].split(" ", 1)[0]
        import_id = statement.parameters.get("mail_import_session_id")
        result = [
            row
            for row in self.rows.get(table, {}).values()
            if self.ignore_import_scope_filter or row.get("mail_import_session_id") == import_id
        ]
        if self.reverse_query_rows:
            result.reverse()
        return [
            {key: row[key] for key in _selected_columns(statement.sql) if key in row}
            for row in result
        ]


class _MigrationConnection:
    def execute(self, _statement: object) -> None:
        return None


def _insert_columns(sql: str) -> set[str]:
    columns = sql.split("(", 1)[1].split(") VALUES", 1)[0]
    return {column.strip() for column in columns.split(",")}


def _selected_columns(sql: str) -> tuple[str, ...]:
    columns = sql.split("SELECT ", 1)[1].split(" FROM ", 1)[0]
    return tuple(column.strip() for column in columns.split(","))


def _create_table_columns(ddl: str, table_name: str) -> set[str]:
    block = ddl.split(f"CREATE TABLE IF NOT EXISTS {table_name} (", 1)[1].split(");", 1)[0]
    columns = set()
    in_constraint = False
    for line in block.splitlines():
        stripped = line.strip().rstrip(",")
        if not stripped:
            continue
        if stripped.startswith(("UNIQUE", "FOREIGN KEY", "CONSTRAINT")):
            in_constraint = True
            continue
        if in_constraint:
            if stripped == ")":
                in_constraint = False
            continue
        columns.add(stripped.split(None, 1)[0])
    return columns
