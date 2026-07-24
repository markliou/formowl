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
    CoverageLedger,
    CoverageProofRecord,
    CoverageVersionBinding,
    DisplayPagination,
    EXCLUSION_REASON_CODE_VALUES,
    SourceInventoryItem,
    StructuralCell,
    StructuralColumn,
    StructuralObservation,
    StructuralRow,
    SourceInventory,
    VersionManifest,
)
from formowl_graph.storage import (
    PostgreSQLMigrationRunner,
    PostgreSQLUnitOfWork,
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


class Issue51WP1ContractTests(unittest.TestCase):
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
            SourceInventoryItem.create(**item.to_dict()).source_inventory_item_id,
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
        ledger = CoverageLedger(
            query_id="query_wp1",
            claim_requirement_id=requirement.claim_requirement_id,
            source_inventory_id=source_inventory.source_inventory_id,
            relevant_inventory_item_ids=(item.source_inventory_item_id,),
            searched_structural_observation_ids=(observation.source_observation_id,),
            authorization_binding=authorization,
            version_binding=CoverageVersionBinding.from_manifest(manifest),
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
            claim_requirement_id=requirement.claim_requirement_id,
            coverage_ledger_id=ledger.coverage_ledger_id,
            evidence_snapshot_ids=("snapshot_wp1",),
            source_fingerprint=FP,
            parser_fingerprint=FP2,
            tokenizer_fingerprint=FP,
            index_fingerprint=FP,
        )
        self.assertEqual(
            item.to_dict(),
            SourceInventoryItem.from_dict(item.to_dict()).to_dict(),
        )
        self.assertEqual(
            observation.to_dict(),
            StructuralObservation.from_dict(observation.to_dict()).to_dict(),
        )
        self.assertEqual(
            ledger.to_dict(),
            CoverageLedger.from_dict(ledger.to_dict()).to_dict(),
        )
        self.assertEqual(
            claim.to_dict(),
            AnswerClaim.from_dict(claim.to_dict()).to_dict(),
        )
        self.assertIsInstance(ledger.display_pagination, DisplayPagination)
        self.assertTrue(ledger.claim_scope_complete)
        self.assertTrue(
            ledger.usable_for_claim(source_inventory, requirement, manifest, authorization)
        )

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
        valid = _excluded_item().to_dict()
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
            invalid = dict(_excluded_item().to_dict())
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
        claim = AnswerClaim.create(
            answer_claim_id="answer_claim_wp1",
            state="FOUND",
            reason_codes=("direct_evidence",),
            claim_requirement_id="requirement_wp1",
            coverage_ledger_id="coverage_wp1",
            evidence_snapshot_ids=("snapshot_wp1",),
            source_fingerprint=FP,
            parser_fingerprint=FP2,
            tokenizer_fingerprint=FP,
            index_fingerprint=FP2,
            version_manifest_id="version_wp1",
            implementation_fingerprint=FP,
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

        private = claim.to_persistence_dict()
        self.assertIn("answer_claim_id", private)
        self.assertIn("version_manifest_id", private)
        self.assertIn("implementation_fingerprint", private)
        self.assertEqual(
            AnswerClaim.from_persistence_dict(private).to_persistence_dict(),
            private,
        )
        for extra_key in ("answer_claim_id", "answer_claim_state", "state_2"):
            invalid = dict(public)
            invalid[extra_key] = "CONFLICT"
            with self.subTest(extra_key=extra_key):
                with self.assertRaises(ContractValidationError):
                    AnswerClaim.from_dict(invalid)

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
        self.assertIn("workspace_id text NOT NULL", ddl)
        self.assertIn("owner_user_id text NOT NULL", ddl)
        self.assertIn(
            "source_inventory_id text NOT NULL REFERENCES source_inventory(source_inventory_id)",
            ddl,
        )
        self.assertIn(
            "source_inventory_item_id text NOT NULL\n    REFERENCES source_inventory_item(source_inventory_item_id)",
            ddl,
        )
        self.assertIn(
            "FOREIGN KEY (coverage_ledger_id, claim_requirement_id)",
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
            complete_authorized_scope=False,
        )
        manifest = VersionManifest.create(
            source_fingerprint=FP,
            parser_fingerprint=FP2,
            tokenizer_fingerprint=FP,
            index_fingerprint=FP,
            implementation_fingerprint=FP,
            index_freshness="stale",
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
        )
        claim = AnswerClaim.create(
            answer_claim_id="answer_claim_wp1",
            state="INSUFFICIENT_COVERAGE",
            reason_codes=("stale_index",),
            claim_requirement_id=requirement.claim_requirement_id,
            coverage_ledger_id=ledger.coverage_ledger_id,
            evidence_snapshot_ids=(),
            source_fingerprint=FP,
            parser_fingerprint=FP2,
            tokenizer_fingerprint=FP,
            index_fingerprint=FP,
            version_manifest_id=manifest.version_manifest_id,
            implementation_fingerprint=FP2,
        )
        populated = replace(
            bundle,
            source_inventory=[inventory],
            claim_requirements=[requirement],
            coverage_ledgers=[ledger],
            answer_claims=[claim],
            version_manifests=[manifest],
        )
        payload = populated.to_dict()
        restored = MailEvidenceBundle.from_dict(payload)
        self.assertEqual(restored.to_dict(), payload)

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
        self.assertEqual(round_trip.to_dict(), payload)
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

    def test_source_inventory_relational_integrity_fails_closed_in_file_payloads(self) -> None:
        bundle, inventory, requirement, ledger = _inventory_bundle()
        payload = bundle.to_dict()

        mismatched_inventory = deepcopy(payload)
        mismatched_inventory["source_inventory"][0]["items"][0]["source_inventory_id"] = (
            "inventory_other"
        )
        with self.assertRaises(ContractValidationError):
            MailEvidenceBundle.from_dict(mismatched_inventory)

        mismatched_asset = deepcopy(payload)
        mismatched_asset["source_inventory"][0]["items"][0]["source_asset_id"] = "asset_other"
        with self.assertRaises(ContractValidationError):
            MailEvidenceBundle.from_dict(mismatched_asset)

        orphan_projection = deepcopy(payload)
        orphan_projection["source_inventory_items"].append(
            {
                **orphan_projection["source_inventory_items"][0],
                "source_inventory_item_id": "orphan_item_wp1",
            }
        )
        with self.assertRaises(ContractValidationError):
            MailEvidenceBundle.from_dict(orphan_projection)

        orphan_ledger = deepcopy(payload)
        orphan_ledger["coverage_ledgers"][0]["source_inventory_id"] = "inventory_other"
        with self.assertRaises(ContractValidationError):
            MailEvidenceBundle.from_dict(orphan_ledger)

        mismatched_ledger_claim = deepcopy(payload)
        mismatched_ledger_claim["coverage_ledgers"][0]["claim_requirement_id"] = "requirement_other"
        with self.assertRaises(ContractValidationError):
            MailEvidenceBundle.from_dict(mismatched_ledger_claim)

        orphan_claim = deepcopy(payload)
        orphan_claim["answer_claims"][0]["coverage_ledger_id"] = "coverage_other"
        with self.assertRaises(ContractValidationError):
            MailEvidenceBundle.from_dict(orphan_claim)

        mismatched_claim = deepcopy(payload)
        mismatched_claim["answer_claims"][0]["claim_requirement_id"] = "requirement_other"
        with self.assertRaises(ContractValidationError):
            MailEvidenceBundle.from_dict(mismatched_claim)

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
                PostgreSQLMailEvidenceStore(connection).upsert_bundle(bundle)
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
    ledger = CoverageLedger(
        query_id=requirement.query_id,
        claim_requirement_id=requirement.claim_requirement_id,
        source_inventory_id=inventory.source_inventory_id,
        relevant_inventory_item_ids=(inventory.items[0].source_inventory_item_id,),
        complete_authorized_scope=False,
    )
    claim = AnswerClaim.create(
        answer_claim_id="answer_inventory_wp1",
        state="INSUFFICIENT_COVERAGE",
        reason_codes=("incomplete_scope",),
        claim_requirement_id=requirement.claim_requirement_id,
        coverage_ledger_id=ledger.coverage_ledger_id,
        evidence_snapshot_ids=(),
        source_fingerprint=FP,
        parser_fingerprint=FP2,
        tokenizer_fingerprint=FP,
        index_fingerprint=FP,
    )
    populated = replace(
        bundle,
        source_inventory=[inventory],
        claim_requirements=[requirement],
        coverage_ledgers=[ledger],
        answer_claims=[claim],
    )
    return populated, inventory, requirement, ledger


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
    def __init__(self, *, fail_after_execute: int | None = None) -> None:
        self.rows: dict[str, dict[str, dict[str, object]]] = {}
        self.fail_after_execute = fail_after_execute
        self.execute_count = 0
        self.snapshot: dict[str, dict[str, dict[str, object]]] | None = None

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
            "claim_requirement": "claim_requirement_id",
            "coverage_ledger": "coverage_ledger_id",
            "version_manifest": "version_manifest_id",
            "answer_claim": "answer_claim_id",
        }.get(table, next(iter(statement.parameters)))
        self.rows.setdefault(table, {})[str(statement.parameters[key])] = dict(statement.parameters)

    def query_one(self, statement: object) -> dict[str, object] | None:
        rows = self.rows.get("mail_import_session", {})
        for row in rows.values():
            if (
                statement.parameters["mail_import_session_id"] is None
                or row["mail_import_session_id"] == statement.parameters["mail_import_session_id"]
            ) and (
                statement.parameters["mail_evidence_bundle_id"] is None
                or row["mail_evidence_bundle_id"] == statement.parameters["mail_evidence_bundle_id"]
            ):
                return row
        return None

    def query_all(self, statement: object) -> list[dict[str, object]]:
        sql = statement.sql
        table = sql.split(" FROM ", 1)[1].split(" ", 1)[0]
        import_id = statement.parameters.get("mail_import_session_id")
        result = [
            row
            for row in self.rows.get(table, {}).values()
            if row.get("mail_import_session_id") == import_id
        ]
        return [{"payload": row["payload"]} for row in result]


class _MigrationConnection:
    def execute(self, _statement: object) -> None:
        return None


def _insert_columns(sql: str) -> set[str]:
    columns = sql.split("(", 1)[1].split(") VALUES", 1)[0]
    return {column.strip() for column in columns.split(",")}


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
