from __future__ import annotations

import re
from typing import Any, Callable, Protocol, Sequence

from formowl_contract import ContractValidationError, Grant, sha256_json, to_plain
from formowl_graph.storage import SQLStatement

from ._guards import safe_public_string
from .bundle import (
    EmailAttachment,
    EmailAttachmentOccurrence,
    EmailBodySegment,
    EmailMessage,
    EmailMessageOccurrence,
    EmbeddedMessageRelation,
    MailArchiveOccurrence,
    MailEvidenceBundle,
    MailFolderOccurrence,
    MailImportSession,
    MailParseRun,
    MailParseWarning,
    QuotedMessageCandidate,
)
from .query import MailEvidenceQueryGateway

_SAFE_RECORD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_TABLE_NAMES = (
    "mail_import_session",
    "mail_archive_occurrence",
    "mail_folder_occurrence",
    "email_message",
    "email_message_occurrence",
    "email_body_segment",
    "email_attachment",
    "email_attachment_occurrence",
    "quoted_message_candidate",
    "embedded_message_relation",
    "mail_parse_run",
    "mail_parse_warning",
)


class PostgreSQLMailEvidenceConnection(Protocol):
    def execute(self, statement: SQLStatement) -> None: ...

    def query_one(self, statement: SQLStatement) -> dict[str, Any] | None: ...

    def query_all(self, statement: SQLStatement) -> list[dict[str, Any]]: ...


class PostgreSQLMailEvidenceStore:
    """Internal PostgreSQL adapter for normalized Phase 1 mail evidence rows."""

    def __init__(self, connection: PostgreSQLMailEvidenceConnection) -> None:
        self.connection = connection

    def upsert_bundle(self, bundle: MailEvidenceBundle | dict[str, Any]) -> list[SQLStatement]:
        validated = _validate_bundle(bundle)
        statements = _statements_for_bundle(validated)
        for statement in statements:
            self.connection.execute(statement)
        return statements

    def get_bundle(
        self,
        *,
        mail_import_session_id: str | None = None,
        mail_evidence_bundle_id: str | None = None,
    ) -> MailEvidenceBundle | None:
        if not mail_import_session_id and not mail_evidence_bundle_id:
            raise ContractValidationError(
                "mail_import_session_id or mail_evidence_bundle_id is required"
            )
        if mail_import_session_id is not None:
            _validate_record_id(mail_import_session_id, "mail_import_session_id")
        if mail_evidence_bundle_id is not None:
            _validate_record_id(mail_evidence_bundle_id, "mail_evidence_bundle_id")

        session_row = self.connection.query_one(
            SQLStatement(
                sql=(
                    "SELECT payload, mail_evidence_bundle_id, producer_type, "
                    "bundle_created_at FROM mail_import_session "
                    "WHERE (%(mail_import_session_id)s IS NULL "
                    "OR mail_import_session_id = %(mail_import_session_id)s) "
                    "AND (%(mail_evidence_bundle_id)s IS NULL "
                    "OR mail_evidence_bundle_id = %(mail_evidence_bundle_id)s)"
                ),
                parameters={
                    "mail_import_session_id": mail_import_session_id,
                    "mail_evidence_bundle_id": mail_evidence_bundle_id,
                },
            )
        )
        if session_row is None:
            return None

        import_session = MailImportSession.from_dict(_payload(session_row))
        import_session_id = import_session.mail_import_session_id
        archive_occurrences = _sort_records(
            _query_import_rows(
                self.connection,
                table_name="mail_archive_occurrence",
                mail_import_session_id=import_session_id,
                factory=MailArchiveOccurrence.from_dict,
            ),
            "mail_archive_occurrence_id",
        )
        folder_occurrences = _sort_records(
            _query_import_rows(
                self.connection,
                table_name="mail_folder_occurrence",
                mail_import_session_id=import_session_id,
                factory=MailFolderOccurrence.from_dict,
            ),
            "mail_folder_occurrence_id",
        )
        message_occurrences = _sort_records(
            _query_import_rows(
                self.connection,
                table_name="email_message_occurrence",
                mail_import_session_id=import_session_id,
                factory=EmailMessageOccurrence.from_dict,
            ),
            "email_message_occurrence_id",
        )
        body_segments = _sort_body_segments(
            _query_import_rows(
                self.connection,
                table_name="email_body_segment",
                mail_import_session_id=import_session_id,
                factory=EmailBodySegment.from_dict,
            ),
        )
        attachment_occurrences = _sort_records(
            _query_import_rows(
                self.connection,
                table_name="email_attachment_occurrence",
                mail_import_session_id=import_session_id,
                factory=EmailAttachmentOccurrence.from_dict,
            ),
            "email_attachment_occurrence_id",
        )
        quoted_message_candidates = _sort_records(
            _query_import_rows(
                self.connection,
                table_name="quoted_message_candidate",
                mail_import_session_id=import_session_id,
                factory=QuotedMessageCandidate.from_dict,
            ),
            "quoted_message_candidate_id",
        )
        embedded_message_relations = _sort_records(
            _query_import_rows(
                self.connection,
                table_name="embedded_message_relation",
                mail_import_session_id=import_session_id,
                factory=EmbeddedMessageRelation.from_dict,
            ),
            "embedded_message_relation_id",
        )
        parse_runs = _sort_records(
            _query_import_rows(
                self.connection,
                table_name="mail_parse_run",
                mail_import_session_id=import_session_id,
                factory=MailParseRun.from_dict,
            ),
            "mail_parse_run_id",
        )
        parse_warnings = _sort_records(
            _query_import_rows(
                self.connection,
                table_name="mail_parse_warning",
                mail_import_session_id=import_session_id,
                factory=MailParseWarning.from_dict,
            ),
            "mail_parse_warning_id",
        )
        if not parse_runs:
            raise ContractValidationError("mail evidence store row set is missing mail_parse_run")

        message_ids = (
            {item.email_message_id for item in message_occurrences}
            | {item.email_message_id for item in body_segments}
            | {item.email_message_id for item in attachment_occurrences}
            | {item.email_message_id for item in quoted_message_candidates}
            | {item.parent_email_message_id for item in embedded_message_relations}
            | {item.embedded_email_message_id for item in embedded_message_relations}
        )
        logical_messages = _query_rows_by_ids(
            self.connection,
            table_name="email_message",
            id_field="email_message_id",
            ids=sorted(message_ids),
            factory=EmailMessage.from_dict,
        )
        attachments = _query_rows_by_ids(
            self.connection,
            table_name="email_attachment",
            id_field="email_attachment_id",
            ids=sorted({item.email_attachment_id for item in attachment_occurrences}),
            factory=EmailAttachment.from_dict,
        )
        messages = _messages_for_import(logical_messages, message_occurrences)

        return MailEvidenceBundle.from_dict(
            {
                "mail_evidence_bundle_id": _safe_row_str(
                    session_row,
                    "mail_evidence_bundle_id",
                ),
                "producer_type": _safe_row_str(session_row, "producer_type"),
                "mail_import_session": import_session.to_dict(),
                "archive_occurrences": [item.to_dict() for item in archive_occurrences],
                "folder_occurrences": [item.to_dict() for item in folder_occurrences],
                "messages": [item.to_dict() for item in messages],
                "message_occurrences": [item.to_dict() for item in message_occurrences],
                "body_segments": [item.to_dict() for item in body_segments],
                "attachments": [item.to_dict() for item in attachments],
                "attachment_occurrences": [item.to_dict() for item in attachment_occurrences],
                "quoted_message_candidates": [item.to_dict() for item in quoted_message_candidates],
                "embedded_message_relations": [
                    item.to_dict() for item in embedded_message_relations
                ],
                "mail_parse_run": parse_runs[0].to_dict(),
                "parse_warnings": [item.to_dict() for item in parse_warnings],
                "created_at": _safe_row_str(session_row, "bundle_created_at"),
            }
        )


def build_postgre_sql_mail_evidence_query_handler(
    store: PostgreSQLMailEvidenceStore,
    *,
    grants: Sequence[Grant | dict[str, Any]] = (),
    now: str | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    trusted_grants = tuple(grants)

    def handler(input_data: dict[str, Any]) -> dict[str, Any]:
        _validate_query_before_store_read(
            input_data=input_data,
            grants=trusted_grants,
            now=now,
        )
        bundle = store.get_bundle(
            mail_import_session_id=input_data.get("mail_import_session_id"),
            mail_evidence_bundle_id=input_data.get("mail_evidence_bundle_id"),
        )
        gateway = MailEvidenceQueryGateway([] if bundle is None else [bundle])
        result = gateway.query_mail_evidence(
            query_text=input_data.get("query_text", ""),
            requester_user_id=input_data.get("requester_user_id", ""),
            workspace_id=input_data.get("workspace_id", ""),
            session_id=input_data.get("session_id", "semantic_gateway_session"),
            mail_import_session_id=input_data.get("mail_import_session_id"),
            mail_evidence_bundle_id=input_data.get("mail_evidence_bundle_id"),
            grants=trusted_grants,
            limit=input_data.get("limit", 5),
            now=now,
        )
        return result.to_dict()

    return handler


def postgre_sql_mail_evidence_store_interfaces() -> tuple[str, ...]:
    return (
        "PostgreSQLMailEvidenceStore",
        "build_postgre_sql_mail_evidence_query_handler",
    )


def mail_evidence_postgre_sql_tables() -> tuple[str, ...]:
    return _TABLE_NAMES


def mail_evidence_query_indexes() -> tuple[str, ...]:
    return (
        "idx_mail_import_session_workspace_owner",
        "idx_mail_import_session_upload_session",
        "idx_mail_archive_occurrence_import",
        "idx_mail_folder_occurrence_import",
        "idx_email_message_fingerprint",
        "idx_email_message_occurrence_import",
        "idx_email_body_segment_import_message",
        "idx_email_attachment_fingerprint",
        "idx_email_attachment_occurrence_import",
        "idx_quoted_message_candidate_import",
        "idx_embedded_message_relation_import",
        "idx_mail_parse_run_import",
        "idx_mail_parse_warning_import",
    )


def _statements_for_bundle(bundle: MailEvidenceBundle) -> list[SQLStatement]:
    workspace_id = bundle.mail_import_session.workspace_id
    owner_user_id = bundle.mail_import_session.owner_user_id
    import_session_id = bundle.mail_import_session.mail_import_session_id
    statements = [_mail_import_session_statement(bundle)]
    statements.extend(
        _import_scoped_statement(
            table_name="mail_archive_occurrence",
            id_field="mail_archive_occurrence_id",
            record=item,
            mail_import_session_id=import_session_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
        )
        for item in bundle.archive_occurrences
    )
    statements.extend(
        _import_scoped_statement(
            table_name="mail_folder_occurrence",
            id_field="mail_folder_occurrence_id",
            record=item,
            mail_import_session_id=import_session_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
        )
        for item in bundle.folder_occurrences
    )
    statements.extend(
        _logical_statement(
            table_name="email_message",
            id_field="email_message_id",
            fingerprint_field="message_fingerprint",
            record=item,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
        )
        for item in bundle.messages
    )
    statements.extend(
        _import_scoped_statement(
            table_name="email_message_occurrence",
            id_field="email_message_occurrence_id",
            record=item,
            mail_import_session_id=import_session_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            extra_parameters={"email_message_id": item.email_message_id},
        )
        for item in bundle.message_occurrences
    )
    statements.extend(
        _import_scoped_statement(
            table_name="email_body_segment",
            id_field="email_body_segment_id",
            record=item,
            mail_import_session_id=import_session_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            extra_parameters={"email_message_id": item.email_message_id},
        )
        for item in bundle.body_segments
    )
    statements.extend(
        _logical_statement(
            table_name="email_attachment",
            id_field="email_attachment_id",
            fingerprint_field="attachment_fingerprint",
            record=item,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
        )
        for item in bundle.attachments
    )
    statements.extend(
        _import_scoped_statement(
            table_name="email_attachment_occurrence",
            id_field="email_attachment_occurrence_id",
            record=item,
            mail_import_session_id=import_session_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            extra_parameters={
                "email_attachment_id": item.email_attachment_id,
                "email_message_id": item.email_message_id,
            },
        )
        for item in bundle.attachment_occurrences
    )
    statements.extend(
        _import_scoped_statement(
            table_name="quoted_message_candidate",
            id_field="quoted_message_candidate_id",
            record=item,
            mail_import_session_id=import_session_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            extra_parameters={"email_message_id": item.email_message_id},
        )
        for item in bundle.quoted_message_candidates
    )
    statements.extend(
        _import_scoped_statement(
            table_name="embedded_message_relation",
            id_field="embedded_message_relation_id",
            record=item,
            mail_import_session_id=import_session_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            extra_parameters={
                "parent_email_message_id": item.parent_email_message_id,
                "embedded_email_message_id": item.embedded_email_message_id,
            },
        )
        for item in bundle.embedded_message_relations
    )
    statements.append(
        _import_scoped_statement(
            table_name="mail_parse_run",
            id_field="mail_parse_run_id",
            record=bundle.mail_parse_run,
            mail_import_session_id=import_session_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
        )
    )
    statements.extend(
        _import_scoped_statement(
            table_name="mail_parse_warning",
            id_field="mail_parse_warning_id",
            record=item,
            mail_import_session_id=import_session_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            extra_parameters={"mail_parse_run_id": item.mail_parse_run_id},
        )
        for item in bundle.parse_warnings
    )
    return statements


def _validate_query_before_store_read(
    *,
    input_data: dict[str, Any],
    grants: Sequence[Grant | dict[str, Any]],
    now: str | None,
) -> None:
    # Preserve the public query validation order before any store reads happen.
    MailEvidenceQueryGateway([]).query_mail_evidence(
        query_text=input_data.get("query_text", ""),
        requester_user_id=input_data.get("requester_user_id", ""),
        workspace_id=input_data.get("workspace_id", ""),
        session_id=input_data.get("session_id", "semantic_gateway_session"),
        mail_import_session_id=input_data.get("mail_import_session_id"),
        mail_evidence_bundle_id=input_data.get("mail_evidence_bundle_id"),
        grants=grants,
        limit=input_data.get("limit", 5),
        now=now,
    )


def _mail_import_session_statement(bundle: MailEvidenceBundle) -> SQLStatement:
    payload = bundle.mail_import_session.to_dict()
    record_id = bundle.mail_import_session.mail_import_session_id
    _validate_record_id(record_id, "mail_import_session_id")
    _validate_record_id(bundle.mail_evidence_bundle_id, "mail_evidence_bundle_id")
    _validate_record_id(bundle.mail_import_session.workspace_id, "workspace_id")
    _validate_record_id(bundle.mail_import_session.owner_user_id, "owner_user_id")
    _validate_record_id(bundle.mail_import_session.source_asset_id, "source_asset_id")
    if bundle.mail_import_session.upload_session_id is not None:
        _validate_record_id(
            bundle.mail_import_session.upload_session_id,
            "upload_session_id",
        )
    return SQLStatement(
        sql=(
            "INSERT INTO mail_import_session "
            "(mail_import_session_id, mail_evidence_bundle_id, workspace_id, "
            "owner_user_id, source_asset_id, upload_session_id, archive_sha256, "
            "retention_policy, raw_archive_retention_decision, producer_type, "
            "status, bundle_created_at, payload, payload_hash) "
            "VALUES (%(mail_import_session_id)s, %(mail_evidence_bundle_id)s, "
            "%(workspace_id)s, %(owner_user_id)s, %(source_asset_id)s, "
            "%(upload_session_id)s, %(archive_sha256)s, %(retention_policy)s, "
            "%(raw_archive_retention_decision)s, %(producer_type)s, %(status)s, "
            "%(bundle_created_at)s, %(payload)s::jsonb, %(payload_hash)s) "
            "ON CONFLICT (mail_import_session_id) DO UPDATE SET "
            "mail_evidence_bundle_id = EXCLUDED.mail_evidence_bundle_id, "
            "status = EXCLUDED.status, "
            "raw_archive_retention_decision = EXCLUDED.raw_archive_retention_decision, "
            "payload = EXCLUDED.payload, payload_hash = EXCLUDED.payload_hash, "
            "updated_at = now()"
        ),
        parameters={
            "mail_import_session_id": record_id,
            "mail_evidence_bundle_id": bundle.mail_evidence_bundle_id,
            "workspace_id": bundle.mail_import_session.workspace_id,
            "owner_user_id": bundle.mail_import_session.owner_user_id,
            "source_asset_id": bundle.mail_import_session.source_asset_id,
            "upload_session_id": bundle.mail_import_session.upload_session_id,
            "archive_sha256": bundle.mail_import_session.archive_sha256,
            "retention_policy": bundle.mail_import_session.retention_policy,
            "raw_archive_retention_decision": (
                bundle.mail_import_session.raw_archive_retention_decision
            ),
            "producer_type": bundle.producer_type,
            "status": bundle.mail_import_session.status,
            "bundle_created_at": bundle.created_at,
            "payload": payload,
            "payload_hash": sha256_json(payload),
        },
    )


def _import_scoped_statement(
    *,
    table_name: str,
    id_field: str,
    record: Any,
    mail_import_session_id: str,
    workspace_id: str,
    owner_user_id: str,
    extra_parameters: dict[str, Any] | None = None,
) -> SQLStatement:
    _validate_table_name(table_name)
    payload = record.to_dict()
    record_id = str(payload[id_field])
    _validate_record_id(record_id, id_field)
    _validate_record_id(mail_import_session_id, "mail_import_session_id")
    _validate_record_id(workspace_id, "workspace_id")
    _validate_record_id(owner_user_id, "owner_user_id")
    extras = dict(extra_parameters or {})
    for key, value in extras.items():
        _validate_record_id(str(value), key)
    extra_columns = "".join(f", {key}" for key in extras)
    extra_values = "".join(f", %({key})s" for key in extras)
    return SQLStatement(
        sql=(
            f"INSERT INTO {table_name} "
            f"({id_field}, mail_import_session_id, workspace_id, owner_user_id"
            f"{extra_columns}, payload, payload_hash) "
            f"VALUES (%({id_field})s, %(mail_import_session_id)s, %(workspace_id)s, "
            f"%(owner_user_id)s{extra_values}, %(payload)s::jsonb, %(payload_hash)s) "
            f"ON CONFLICT ({id_field}) DO UPDATE SET "
            "payload = EXCLUDED.payload, payload_hash = EXCLUDED.payload_hash, "
            "updated_at = now()"
        ),
        parameters={
            id_field: record_id,
            "mail_import_session_id": mail_import_session_id,
            "workspace_id": workspace_id,
            "owner_user_id": owner_user_id,
            **extras,
            "payload": payload,
            "payload_hash": sha256_json(payload),
        },
    )


def _logical_statement(
    *,
    table_name: str,
    id_field: str,
    fingerprint_field: str,
    record: Any,
    workspace_id: str,
    owner_user_id: str,
) -> SQLStatement:
    _validate_table_name(table_name)
    payload = record.to_dict()
    record_id = str(payload[id_field])
    fingerprint = str(payload[fingerprint_field])
    _validate_record_id(record_id, id_field)
    _validate_record_id(workspace_id, "workspace_id")
    _validate_record_id(owner_user_id, "owner_user_id")
    safe_public_string(fingerprint, fingerprint_field)
    return SQLStatement(
        sql=(
            f"INSERT INTO {table_name} "
            f"({id_field}, {fingerprint_field}, workspace_id, owner_user_id, "
            "payload, payload_hash) "
            f"VALUES (%({id_field})s, %({fingerprint_field})s, %(workspace_id)s, "
            "%(owner_user_id)s, %(payload)s::jsonb, %(payload_hash)s) "
            f"ON CONFLICT ({id_field}) DO NOTHING"
        ),
        parameters={
            id_field: record_id,
            fingerprint_field: fingerprint,
            "workspace_id": workspace_id,
            "owner_user_id": owner_user_id,
            "payload": payload,
            "payload_hash": sha256_json(payload),
        },
    )


def _query_import_rows(
    connection: PostgreSQLMailEvidenceConnection,
    *,
    table_name: str,
    mail_import_session_id: str,
    factory: Callable[[dict[str, Any]], Any],
) -> list[Any]:
    _validate_table_name(table_name)
    _validate_record_id(mail_import_session_id, "mail_import_session_id")
    rows = connection.query_all(
        SQLStatement(
            sql=(
                f"SELECT payload FROM {table_name} "
                "WHERE mail_import_session_id = %(mail_import_session_id)s "
                "ORDER BY payload_hash"
            ),
            parameters={"mail_import_session_id": mail_import_session_id},
        )
    )
    return [factory(_payload(row)) for row in rows]


def _sort_records(records: Sequence[Any], id_field: str) -> list[Any]:
    return sorted(records, key=lambda item: str(item.to_dict()[id_field]))


def _sort_body_segments(records: Sequence[EmailBodySegment]) -> list[EmailBodySegment]:
    return sorted(
        records,
        key=lambda item: (
            item.email_message_id,
            item.segment_source_type,
            item.attachment_id or "",
            item.body_segment_index or 0,
            item.email_body_segment_id,
        ),
    )


def _messages_for_import(
    logical_messages: Sequence[EmailMessage],
    message_occurrences: Sequence[EmailMessageOccurrence],
) -> list[EmailMessage]:
    occurrences_by_message_id: dict[str, list[EmailMessageOccurrence]] = {}
    for occurrence in message_occurrences:
        occurrences_by_message_id.setdefault(occurrence.email_message_id, []).append(occurrence)

    messages: list[EmailMessage] = []
    for message in logical_messages:
        occurrence_lineage = occurrences_by_message_id.get(message.email_message_id, [])
        if not occurrence_lineage:
            messages.append(message)
            continue
        archive_ids = {item.archive_id for item in occurrence_lineage}
        mailbox_ids = {item.mailbox_id for item in occurrence_lineage}
        if len(archive_ids) != 1 or len(mailbox_ids) != 1:
            raise ContractValidationError("mail message occurrence lineage is inconsistent")
        payload = message.to_dict()
        payload.update(
            {
                "archive_id": next(iter(archive_ids)),
                "mailbox_id": next(iter(mailbox_ids)),
                "source_observation_ids": sorted(
                    {item.source_observation_id for item in occurrence_lineage}
                ),
            }
        )
        messages.append(EmailMessage.from_dict(payload))
    return _sort_records(messages, "email_message_id")


def _query_rows_by_ids(
    connection: PostgreSQLMailEvidenceConnection,
    *,
    table_name: str,
    id_field: str,
    ids: Sequence[str],
    factory: Callable[[dict[str, Any]], Any],
) -> list[Any]:
    _validate_table_name(table_name)
    for item in ids:
        _validate_record_id(item, id_field)
    if not ids:
        return []
    rows = connection.query_all(
        SQLStatement(
            sql=(
                f"SELECT payload FROM {table_name} "
                f"WHERE {id_field} = ANY(%({id_field}s)s) ORDER BY {id_field}"
            ),
            parameters={f"{id_field}s": list(ids)},
        )
    )
    return [factory(_payload(row)) for row in rows]


def _validate_bundle(bundle: MailEvidenceBundle | dict[str, Any]) -> MailEvidenceBundle:
    if isinstance(bundle, MailEvidenceBundle):
        payload = bundle.to_dict()
    elif isinstance(bundle, dict):
        payload = to_plain(bundle)
    else:
        raise ContractValidationError("mail evidence store requires a bundle")
    return MailEvidenceBundle.from_dict(payload)


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    if not isinstance(payload, dict):
        raise ContractValidationError("mail evidence row payload must be an object")
    return payload


def _safe_row_str(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"mail evidence row {key} must be a string")
    return safe_public_string(value, key)


def _validate_table_name(table_name: str) -> None:
    if table_name not in _TABLE_NAMES:
        raise ContractValidationError("unknown mail evidence table")


def _validate_record_id(record_id: str, field_name: str) -> None:
    if not isinstance(record_id, str) or not _SAFE_RECORD_ID.fullmatch(record_id):
        raise ContractValidationError(f"{field_name} must be a safe mail evidence id")


__all__ = [
    "PostgreSQLMailEvidenceConnection",
    "PostgreSQLMailEvidenceStore",
    "build_postgre_sql_mail_evidence_query_handler",
    "mail_evidence_postgre_sql_tables",
    "mail_evidence_query_indexes",
    "postgre_sql_mail_evidence_store_interfaces",
]
