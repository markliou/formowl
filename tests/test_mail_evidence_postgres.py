from __future__ import annotations

import json
import unittest
from typing import Any

import _paths  # noqa: F401
from formowl_contract import (
    ContractValidationError,
    Grant,
    PermissionScope,
    SourceRef,
    sha256_json,
)
from formowl_gateway import SemanticGatewaySession, SemanticMcpGateway, SemanticMcpJsonRpcGateway
from formowl_graph.storage import PostgreSQLUnitOfWork, migration_files
from formowl_ingestion.assets import register_asset_from_local_file
from formowl_ingestion.extraction import run_extractor
from formowl_ingestion.extractors import FixtureMailArchiveExtractor
from formowl_ingestion.storage import (
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    ObservationStore,
    StorageBackendRegistry,
)
from formowl_mail import (
    EmailMessage,
    EmbeddedMessageRelation,
    MailEvidenceBundle,
    MailParseWarning,
    PostgreSQLMailEvidenceStore,
    QuotedMessageCandidate,
    build_mail_evidence_bundle,
    build_postgre_sql_mail_evidence_query_handler,
    mail_evidence_postgre_sql_tables,
    mail_evidence_query_indexes,
    postgre_sql_mail_evidence_store_interfaces,
)

NOW = "2026-07-05T10:00:00+00:00"


class PostgreSQLMailEvidenceStoreTests(unittest.TestCase):
    def test_upsert_bundle_writes_normalized_phase1_tables_and_round_trips(self) -> None:
        bundle = _mail_bundle(_paths.fresh_test_dir("mail-evidence-postgres-roundtrip"))
        connection = _RecordingMailConnection()
        statements = PostgreSQLMailEvidenceStore(connection).upsert_bundle(bundle)

        touched_tables = {
            statement.sql.split("INSERT INTO ", 1)[1].split(" ", 1)[0] for statement in statements
        }

        self.assertEqual(
            postgre_sql_mail_evidence_store_interfaces(),
            (
                "PostgreSQLMailEvidenceStore",
                "build_postgre_sql_mail_evidence_query_handler",
            ),
        )

        self.assertEqual(touched_tables, set(mail_evidence_postgre_sql_tables()))
        self.assertIn("004_mail_evidence.sql", [item.filename for item in migration_files()])
        self.assertIn(
            "idx_mail_import_session_workspace_owner",
            mail_evidence_query_indexes(),
        )
        self.assertTrue(
            {
                "idx_mail_archive_occurrence_import",
                "idx_mail_folder_occurrence_import",
                "idx_quoted_message_candidate_import",
                "idx_embedded_message_relation_import",
                "idx_mail_parse_warning_import",
            }.issubset(set(mail_evidence_query_indexes()))
        )
        self.assertTrue(all("%(" in statement.sql for statement in statements))
        self.assertTrue(
            all("Waiting on audit approval" not in statement.sql for statement in statements)
        )
        self.assertEqual(len(connection.rows["email_message"]), 2)
        self.assertEqual(len(connection.rows["email_message_occurrence"]), 2)
        self.assertEqual(len(connection.rows["email_attachment"]), 1)
        self.assertEqual(len(connection.rows["email_attachment_occurrence"]), 2)

        stored = PostgreSQLMailEvidenceStore(connection).get_bundle(
            mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
        )

        self.assertIsNotNone(stored)
        self.assertEqual(stored.to_dict(), bundle.to_dict())

    def test_duplicate_import_preserves_occurrences_without_overwriting_logical_rows(
        self,
    ) -> None:
        first = _mail_bundle(
            _paths.fresh_test_dir("mail-evidence-postgres-duplicate-one"),
            archive=_mail_archive(archive_id="archive_launch_one"),
            archive_sha256="sha256:archive-duplicate-one",
            upload_session_id="upload_session_mail_duplicate_001",
            include_optional_rows=False,
        )
        second = _mail_bundle(
            _paths.fresh_test_dir("mail-evidence-postgres-duplicate-two"),
            archive=_mail_archive(archive_id="archive_launch_two"),
            archive_sha256="sha256:archive-duplicate-two",
            upload_session_id="upload_session_mail_duplicate_002",
            include_optional_rows=False,
        )
        connection = _RecordingMailConnection()
        store = PostgreSQLMailEvidenceStore(connection)

        store.upsert_bundle(first)
        store.upsert_bundle(second)

        self.assertEqual(len(connection.rows["email_message"]), 1)
        self.assertEqual(len(connection.rows["email_attachment"]), 1)
        self.assertEqual(len(connection.rows["email_message_occurrence"]), 4)
        self.assertEqual(len(connection.rows["email_attachment_occurrence"]), 4)
        logical_message_sql = [
            statement.sql
            for statement in connection.statements
            if "INSERT INTO email_message " in statement.sql
        ]
        self.assertTrue(all("DO NOTHING" in sql for sql in logical_message_sql))

        stored_first = store.get_bundle(
            mail_import_session_id=first.mail_import_session.mail_import_session_id,
        )
        stored_second = store.get_bundle(
            mail_import_session_id=second.mail_import_session.mail_import_session_id,
        )

        self.assertEqual(stored_first.to_dict(), first.to_dict())
        self.assertEqual(stored_second.to_dict(), second.to_dict())

    def test_store_backed_query_handler_keeps_mcp_permission_filtering(self) -> None:
        bundle = _mail_bundle(_paths.fresh_test_dir("mail-evidence-postgres-query"))
        connection = _RecordingMailConnection()
        store = PostgreSQLMailEvidenceStore(connection)
        store.upsert_bundle(bundle)
        gateway = SemanticMcpJsonRpcGateway(
            semantic_gateway=SemanticMcpGateway(
                mail_evidence_handler=build_postgre_sql_mail_evidence_query_handler(
                    store,
                    now=NOW,
                )
            ),
            session=SemanticGatewaySession(
                session_id="session_postgres_other",
                actor_user_id="user_other",
                workspace_id="workspace_formowl",
            ),
        )

        denied = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "mail_denied",
                "method": "tools/call",
                "params": {
                    "name": "query_mail_evidence",
                    "arguments": {
                        "query_text": "audit approval",
                        "mail_import_session_id": (
                            bundle.mail_import_session.mail_import_session_id
                        ),
                    },
                },
            }
        )
        denied_content = denied["result"]["content"][0]["json"]

        self.assertEqual(denied_content["status"], "permission_denied")
        self.assertEqual(denied_content["data"]["evidence_snippets"], [])
        self.assertNotIn("Waiting on audit approval", str(denied_content))

        granted_gateway = SemanticMcpJsonRpcGateway(
            semantic_gateway=SemanticMcpGateway(
                mail_evidence_handler=build_postgre_sql_mail_evidence_query_handler(
                    store,
                    grants=[_mail_session_grant(bundle, grantee_user_id="user_other")],
                    now=NOW,
                )
            ),
            session=SemanticGatewaySession(
                session_id="session_postgres_other_granted",
                actor_user_id="user_other",
                workspace_id="workspace_formowl",
            ),
        )
        granted = granted_gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "mail_granted",
                "method": "tools/call",
                "params": {
                    "name": "query_mail_evidence",
                    "arguments": {
                        "query_text": "audit approval",
                        "mail_evidence_bundle_id": bundle.mail_evidence_bundle_id,
                    },
                },
            }
        )
        granted_content = granted["result"]["content"][0]["json"]

        self.assertEqual(granted_content["status"], "ok")
        self.assertIn(
            "Waiting on audit approval",
            str(granted_content["data"]["evidence_snippets"]),
        )
        self.assertNotIn("SELECT", str(granted_content).upper())
        self.assertNotIn("mail_import_session ", str(granted_content))
        self.assertNotIn("audit approval", str(granted_gateway.leak_transcript()))

    def test_private_body_round_trips_but_public_query_remains_redacted(self) -> None:
        bundle = _mail_bundle(_paths.fresh_test_dir("mail-evidence-postgres-private-body"))
        payload = bundle.to_dict()
        private_text = "Review C:\\private\\archive.pst and SELECT * FROM mailbox_messages"
        payload["body_segments"][0]["text"] = private_text
        private_bundle = MailEvidenceBundle.from_dict(payload)
        connection = _RecordingMailConnection()
        store = PostgreSQLMailEvidenceStore(connection)

        store.upsert_bundle(private_bundle)
        stored = store.get_bundle(
            mail_import_session_id=private_bundle.mail_import_session.mail_import_session_id,
        )

        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertIn(private_text, [segment.text for segment in stored.body_segments])
        result = build_postgre_sql_mail_evidence_query_handler(store, now=NOW)(
            {
                "query_text": "Review mailbox",
                "requester_user_id": "user_yifan",
                "workspace_id": "workspace_formowl",
                "session_id": "session_private_roundtrip",
                "mail_import_session_id": (
                    private_bundle.mail_import_session.mail_import_session_id
                ),
            }
        )
        rendered = json.dumps(result, sort_keys=True)
        self.assertNotIn(private_text, rendered)
        self.assertNotIn("C:\\private", rendered)
        self.assertNotIn("SELECT * FROM", rendered)
        self.assertIn("unsafe_mail_evidence_content_redacted", result["warnings"])

    def test_invalid_bundle_and_unsafe_lookup_fail_before_database_side_effects(self) -> None:
        bundle = _mail_bundle(_paths.fresh_test_dir("mail-evidence-postgres-invalid"))
        payload = bundle.to_dict()
        payload["mail_import_session"]["source_asset_id"] = "../asset_escape"
        connection = _RecordingMailConnection()

        with self.assertRaises(ContractValidationError):
            PostgreSQLMailEvidenceStore(connection).upsert_bundle(payload)
        self.assertEqual(connection.actions, [])

        with self.assertRaises(ContractValidationError):
            PostgreSQLMailEvidenceStore(connection).get_bundle(
                mail_import_session_id="../mail_escape",
            )
        self.assertEqual(connection.actions, [])

    def test_store_backed_handler_validates_public_query_before_store_read(self) -> None:
        bundle = _mail_bundle(_paths.fresh_test_dir("mail-evidence-postgres-preflight"))
        connection = _RecordingMailConnection()
        store = PostgreSQLMailEvidenceStore(connection)
        store.upsert_bundle(bundle)
        connection.actions.clear()
        handler = build_postgre_sql_mail_evidence_query_handler(store, now=NOW)

        with self.assertRaises(ContractValidationError):
            handler(
                {
                    "query_text": "select * from private_mail",
                    "requester_user_id": "user_yifan",
                    "workspace_id": "workspace_formowl",
                    "session_id": "session_safe",
                    "mail_import_session_id": (bundle.mail_import_session.mail_import_session_id),
                }
            )

        self.assertEqual(connection.actions, [])

        with self.assertRaises(ContractValidationError):
            handler(
                {
                    "query_text": "audit approval",
                    "requester_user_id": "user_yifan",
                    "workspace_id": "workspace_formowl",
                    "session_id": "session_safe",
                    "mail_import_session_id": (bundle.mail_import_session.mail_import_session_id),
                    "limit": True,
                }
            )

        self.assertEqual(connection.actions, [])

    def test_transaction_boundary_rolls_back_failed_mail_evidence_write(self) -> None:
        bundle = _mail_bundle(_paths.fresh_test_dir("mail-evidence-postgres-rollback"))
        connection = _RecordingMailConnection(fail_after_execute=2)

        with self.assertRaises(RuntimeError):
            with PostgreSQLUnitOfWork(connection):
                PostgreSQLMailEvidenceStore(connection).upsert_bundle(bundle)

        self.assertEqual(connection.actions, ["begin", "execute", "execute", "rollback"])
        self.assertEqual(connection.rows, {})

        successful_connection = _RecordingMailConnection()
        with PostgreSQLUnitOfWork(successful_connection) as unit:
            PostgreSQLMailEvidenceStore(successful_connection).upsert_bundle(bundle)
            unit.commit()

        self.assertEqual(successful_connection.actions[0], "begin")
        self.assertEqual(successful_connection.actions[-1], "commit")
        self.assertIn("mail_import_session", successful_connection.rows)


class _RecordingMailConnection:
    def __init__(self, *, fail_after_execute: int | None = None) -> None:
        self.fail_after_execute = fail_after_execute
        self.actions: list[str] = []
        self.statements: list[Any] = []
        self.rows: dict[str, dict[str, dict[str, Any]]] = {}
        self.executed_count = 0
        self._transaction_snapshot: dict[str, dict[str, dict[str, Any]]] | None = None

    def execute(self, statement: Any) -> None:
        self.actions.append("execute")
        self.statements.append(statement)
        self.executed_count += 1
        if self.fail_after_execute is not None and self.executed_count >= self.fail_after_execute:
            raise RuntimeError("simulated mail evidence write failure")
        table_name = statement.sql.split("INSERT INTO ", 1)[1].split(" ", 1)[0]
        record_id = _statement_record_id(table_name, statement.parameters)
        if "DO NOTHING" in statement.sql and record_id in self.rows.get(table_name, {}):
            return
        self.rows.setdefault(table_name, {})[record_id] = {
            **statement.parameters,
            "payload": statement.parameters["payload"],
            "payload_hash": statement.parameters["payload_hash"],
        }

    def query_one(self, statement: Any) -> dict[str, Any] | None:
        self.actions.append("query_one")
        self.statements.append(statement)
        table_name = statement.sql.split(" FROM ", 1)[1].split(" ", 1)[0]
        rows = list(self.rows.get(table_name, {}).values())
        for row in rows:
            if _matches_optional(row, statement.parameters, "mail_import_session_id") and (
                _matches_optional(row, statement.parameters, "mail_evidence_bundle_id")
            ):
                return {
                    "payload": row["payload"],
                    "mail_evidence_bundle_id": row["mail_evidence_bundle_id"],
                    "producer_type": row["producer_type"],
                    "bundle_created_at": row["bundle_created_at"],
                }
        return None

    def query_all(self, statement: Any) -> list[dict[str, Any]]:
        self.actions.append("query_all")
        self.statements.append(statement)
        table_name = statement.sql.split(" FROM ", 1)[1].split(" ", 1)[0]
        rows = list(self.rows.get(table_name, {}).values())
        if "mail_import_session_id" in statement.parameters:
            expected = statement.parameters["mail_import_session_id"]
            rows = [row for row in rows if row.get("mail_import_session_id") == expected]
        for key, value in statement.parameters.items():
            if key.endswith("_ids"):
                id_field = key[:-1]
                allowed = set(value)
                rows = [row for row in rows if row.get(id_field) in allowed]
        return [
            {"payload": row["payload"]} for row in sorted(rows, key=lambda row: row["payload_hash"])
        ]

    def begin(self) -> None:
        self.actions.append("begin")
        self._transaction_snapshot = {
            table: {record_id: dict(row) for record_id, row in records.items()}
            for table, records in self.rows.items()
        }

    def commit(self) -> None:
        self.actions.append("commit")
        self._transaction_snapshot = None

    def rollback(self) -> None:
        self.actions.append("rollback")
        if self._transaction_snapshot is not None:
            self.rows = {
                table: {record_id: dict(row) for record_id, row in records.items()}
                for table, records in self._transaction_snapshot.items()
            }
            self._transaction_snapshot = None


def _statement_record_id(table_name: str, parameters: dict[str, Any]) -> str:
    id_fields = {
        "mail_import_session": "mail_import_session_id",
        "mail_archive_occurrence": "mail_archive_occurrence_id",
        "mail_folder_occurrence": "mail_folder_occurrence_id",
        "email_message": "email_message_id",
        "email_message_occurrence": "email_message_occurrence_id",
        "email_body_segment": "email_body_segment_id",
        "email_attachment": "email_attachment_id",
        "email_attachment_occurrence": "email_attachment_occurrence_id",
        "quoted_message_candidate": "quoted_message_candidate_id",
        "embedded_message_relation": "embedded_message_relation_id",
        "mail_parse_run": "mail_parse_run_id",
        "mail_parse_warning": "mail_parse_warning_id",
    }
    return str(parameters[id_fields[table_name]])


def _matches_optional(row: dict[str, Any], parameters: dict[str, Any], key: str) -> bool:
    return parameters.get(key) is None or row.get(key) == parameters[key]


def _mail_bundle(
    temp_dir,
    *,
    archive: dict | None = None,
    archive_sha256: str = "sha256:archive-launch",
    upload_session_id: str = "upload_session_mail_001",
    include_optional_rows: bool = True,
):
    stored = _run_mail_fixture(temp_dir, archive or _mail_archive())
    bundle = build_mail_evidence_bundle(
        stored.observations,
        workspace_id="workspace_formowl",
        owner_user_id="user_yifan",
        source_asset_id=stored.extractor_run.asset_id,
        archive_sha256=archive_sha256,
        upload_session_id=upload_session_id,
        created_at=NOW,
    )
    if not include_optional_rows:
        return bundle
    return _with_optional_phase1_rows(bundle)


def _run_mail_fixture(temp_dir, archive: dict):
    source_path = temp_dir / "incoming" / "mail-archive.json"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(json.dumps(archive, sort_keys=True), encoding="utf-8")
    registry = StorageBackendRegistry(temp_dir)
    backend = registry.register_local_backend(
        temp_dir / "object-root",
        workspace_scope="workspace_formowl",
    )
    object_store = FileObjectStore(registry)
    asset = register_asset_from_local_file(
        source_path,
        object_store=object_store,
        asset_store=AssetStore(temp_dir),
        storage_backend_id=backend.storage_backend_id,
        workspace_id="workspace_formowl",
        owner_user_id="user_yifan",
        permission_scope=PermissionScope.project("project_formowl"),
        source_ref=SourceRef(
            source_system="local",
            source_type="mail_archive",
            source_id="mail-archive.json",
        ),
        mime_type="application/vnd.formowl.mail-archive+json",
        created_at=NOW,
        registered_at=NOW,
    )
    return run_extractor(
        asset=asset,
        object_store=object_store,
        extractor_run_store=ExtractorRunStore(temp_dir),
        observation_store=ObservationStore(temp_dir),
        adapter=FixtureMailArchiveExtractor(),
        started_at=NOW,
        completed_at=NOW,
    )


def _mail_archive(*, archive_id: str = "archive_launch") -> dict:
    return {
        "archive_id": archive_id,
        "mailbox_id": "mailbox_yifan",
        "folders": [
            {"folder_path_hash": "sha256:folder-inbox", "label": "Inbox"},
            {"folder_path_hash": "sha256:folder-review", "label": "Review"},
        ],
        "messages": [
            {
                "message_id": "<launch-001@example.test>",
                "thread_id": "thread_launch",
                "folder_path_hash": "sha256:folder-inbox",
                "subject": "Launch checklist",
                "sender": "pm@example.test",
                "sent_at": NOW,
                "body": "Update: Launch reviewed\n\nBlocker: Waiting on audit approval",
                "body_hash": "sha256:body-launch",
                "attachments": [
                    {
                        "attachment_id": "attachment_audit_pdf",
                        "filename": "audit-approval.pdf",
                        "mime_type": "application/pdf",
                        "content_hash": "sha256:attachment-audit",
                        "size_bytes": 1200,
                    }
                ],
            },
            {
                "message_id": "<launch-001@example.test>",
                "thread_id": "thread_launch",
                "folder_path_hash": "sha256:folder-review",
                "subject": "Launch checklist",
                "sender": "pm@example.test",
                "sent_at": NOW,
                "body": "Update: Launch reviewed\n\nBlocker: Waiting on audit approval",
                "body_hash": "sha256:body-launch",
                "attachments": [
                    {
                        "attachment_id": "attachment_audit_pdf",
                        "filename": "audit-approval.pdf",
                        "mime_type": "application/pdf",
                        "content_hash": "sha256:attachment-audit",
                        "size_bytes": 1200,
                    }
                ],
            },
        ],
    }


def _with_optional_phase1_rows(bundle: MailEvidenceBundle) -> MailEvidenceBundle:
    payload = bundle.to_dict()
    parent_message = bundle.messages[0]
    embedded_message = EmailMessage(
        email_message_id="emailmsg_embedded_audit_001",
        message_fingerprint=sha256_json(
            {
                "message_id": "<embedded-audit-001@example.test>",
                "normalized_subject": "embedded audit note",
                "sender": "auditor@example.test",
                "sent_at": NOW,
                "body_hash": "sha256:body-embedded-audit",
            }
        ),
        message_id="<embedded-audit-001@example.test>",
        archive_id=bundle.archive_occurrences[0].archive_id,
        mailbox_id=bundle.archive_occurrences[0].mailbox_id,
        source_observation_ids=["obs_embedded_audit_001"],
        subject="Embedded audit note",
        normalized_subject="embedded audit note",
        sender="auditor@example.test",
        sent_at=NOW,
        body_hash="sha256:body-embedded-audit",
        thread_id="thread_embedded_audit",
    )
    payload["messages"].append(embedded_message.to_dict())
    payload["quoted_message_candidates"].append(
        QuotedMessageCandidate(
            quoted_message_candidate_id="quotedmsg_audit_001",
            email_message_id=parent_message.email_message_id,
            source_observation_id=parent_message.source_observation_ids[0],
            quoted_text_hash="sha256:quoted-audit",
            confidence=0.42,
        ).to_dict()
    )
    payload["embedded_message_relations"].append(
        EmbeddedMessageRelation(
            embedded_message_relation_id="embeddedrel_audit_001",
            parent_email_message_id=parent_message.email_message_id,
            embedded_email_message_id=embedded_message.email_message_id,
            source_attachment_occurrence_id=(
                bundle.attachment_occurrences[0].email_attachment_occurrence_id
            ),
            source_observation_id=bundle.attachment_occurrences[0].source_observation_id,
        ).to_dict()
    )
    payload["parse_warnings"].append(
        MailParseWarning(
            mail_parse_warning_id="mailparsewarn_audit_001",
            mail_parse_run_id=bundle.mail_parse_run.mail_parse_run_id,
            warning_code="quoted_text_candidate_requires_review",
            message="Quoted body text was retained as a candidate only.",
            source_observation_id=parent_message.source_observation_ids[0],
        ).to_dict()
    )
    return MailEvidenceBundle.from_dict(payload)


def _mail_session_grant(
    bundle,
    *,
    grantee_user_id: str,
) -> Grant:
    return Grant(
        grant_id=f"grant_postgres_mail_{grantee_user_id}",
        owner_user_id="user_yifan",
        grantee_user_id=grantee_user_id,
        scope_type="mail_import_session",
        scope_id=bundle.mail_import_session.mail_import_session_id,
        permission="evidence_snippet",
        expires_at="2026-07-06T00:00:00+00:00",
    )


if __name__ == "__main__":
    unittest.main()
