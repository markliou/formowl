from __future__ import annotations

import re
from typing import Any, Callable, Mapping, Protocol, Sequence

from formowl_contract import (
    AnswerClaim,
    ClaimRequirement,
    ContractValidationError,
    CoverageLedger,
    Grant,
    SourceInventory,
    SourceInventoryItem,
    StructuralObservation,
    VersionManifest,
    sha256_json,
    to_plain,
)
from formowl_graph.storage.postgres import PostgreSQLUnitOfWork, SQLStatement

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
    _WP1_PERSISTENCE_FIELD,
    _WP1_PERSISTENCE_FAMILY_FIELDS,
    _validate_wp1_persistence_state,
    _wp1_persistence_state,
    canonical_family_for_id_field,
    canonical_order_records,
    canonical_table_family,
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
    "source_inventory",
    "source_inventory_item",
    "structural_observation",
    "claim_requirement",
    "coverage_ledger",
    "answer_claim",
    "version_manifest",
)
_PHASE1_TABLE_NAMES = _TABLE_NAMES[:12]


class PostgreSQLMailEvidenceConnection(Protocol):
    def execute(self, statement: SQLStatement) -> None: ...

    def query_one(self, statement: SQLStatement) -> dict[str, Any] | None: ...

    def query_all(self, statement: SQLStatement) -> list[dict[str, Any]]: ...

    def begin(self) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class PostgreSQLMailEvidenceStore:
    """Internal PostgreSQL adapter for normalized Phase 1 mail evidence rows."""

    def __init__(self, connection: PostgreSQLMailEvidenceConnection) -> None:
        self.connection = connection

    def upsert_bundle(
        self,
        bundle: MailEvidenceBundle | dict[str, Any],
        *,
        transaction: PostgreSQLUnitOfWork | None = None,
    ) -> list[SQLStatement]:
        """Persist one bundle atomically.

        When ``transaction`` is omitted, this method owns exactly one
        transaction and commits only after every statement succeeds.  An
        active unit of work for this same connection may be supplied when a
        caller must keep the write and a verification read in one outer
        transaction; that caller retains commit/rollback ownership.
        """

        if transaction is None:
            with PostgreSQLUnitOfWork(self.connection) as unit:
                statements = self._upsert_bundle_in_transaction(bundle)
                unit.commit()
                return statements
        if transaction.connection is not self.connection or not transaction.active:
            raise ContractValidationError(
                "mail evidence upsert requires an active transaction for its connection"
            )
        return self._upsert_bundle_in_transaction(bundle)

    def _upsert_bundle_in_transaction(
        self,
        bundle: MailEvidenceBundle | dict[str, Any],
    ) -> list[SQLStatement]:
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
                    "SELECT payload, mail_import_session_id, workspace_id, owner_user_id, "
                    "mail_evidence_bundle_id, producer_type, "
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

        session_payload = _payload(session_row)
        wp1_persistence = _validate_wp1_persistence_state(
            session_payload.get(_WP1_PERSISTENCE_FIELD)
        )
        import_session = MailImportSession.from_dict(session_payload)
        import_session_id = import_session.mail_import_session_id
        workspace_id = import_session.workspace_id
        owner_user_id = import_session.owner_user_id
        _validate_row_scope(
            session_row,
            mail_import_session_id=import_session_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
        )
        archive_occurrences = _sort_records(
            _query_import_rows(
                self.connection,
                table_name="mail_archive_occurrence",
                id_field="mail_archive_occurrence_id",
                mail_import_session_id=import_session_id,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                factory=MailArchiveOccurrence.from_dict,
            ),
            "mail_archive_occurrence_id",
        )
        folder_occurrences = _sort_records(
            _query_import_rows(
                self.connection,
                table_name="mail_folder_occurrence",
                id_field="mail_folder_occurrence_id",
                mail_import_session_id=import_session_id,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                factory=MailFolderOccurrence.from_dict,
            ),
            "mail_folder_occurrence_id",
        )
        message_occurrences = _sort_records(
            _query_import_rows(
                self.connection,
                table_name="email_message_occurrence",
                id_field="email_message_occurrence_id",
                mail_import_session_id=import_session_id,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                factory=EmailMessageOccurrence.from_dict,
            ),
            "email_message_occurrence_id",
        )
        body_segments = _sort_body_segments(
            _query_import_rows(
                self.connection,
                table_name="email_body_segment",
                id_field="email_body_segment_id",
                mail_import_session_id=import_session_id,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                factory=EmailBodySegment.from_dict,
            ),
        )
        attachment_occurrences = _sort_records(
            _query_import_rows(
                self.connection,
                table_name="email_attachment_occurrence",
                id_field="email_attachment_occurrence_id",
                mail_import_session_id=import_session_id,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                factory=EmailAttachmentOccurrence.from_dict,
            ),
            "email_attachment_occurrence_id",
        )
        quoted_message_candidates = _sort_records(
            _query_import_rows(
                self.connection,
                table_name="quoted_message_candidate",
                id_field="quoted_message_candidate_id",
                mail_import_session_id=import_session_id,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                factory=QuotedMessageCandidate.from_dict,
            ),
            "quoted_message_candidate_id",
        )
        embedded_message_relations = _sort_records(
            _query_import_rows(
                self.connection,
                table_name="embedded_message_relation",
                id_field="embedded_message_relation_id",
                mail_import_session_id=import_session_id,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                factory=EmbeddedMessageRelation.from_dict,
            ),
            "embedded_message_relation_id",
        )
        parse_runs = _sort_records(
            _query_import_rows(
                self.connection,
                table_name="mail_parse_run",
                id_field="mail_parse_run_id",
                mail_import_session_id=import_session_id,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                factory=MailParseRun.from_dict,
            ),
            "mail_parse_run_id",
        )
        parse_warnings = _sort_records(
            _query_import_rows(
                self.connection,
                table_name="mail_parse_warning",
                id_field="mail_parse_warning_id",
                mail_import_session_id=import_session_id,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                factory=MailParseWarning.from_dict,
            ),
            "mail_parse_warning_id",
        )
        source_inventories = _sort_records(
            _query_import_rows(
                self.connection,
                table_name="source_inventory",
                id_field="source_inventory_id",
                mail_import_session_id=import_session_id,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                scope_columns=(
                    "source_asset_id",
                    "source_fingerprint",
                    "parser_fingerprint",
                ),
                row_validator=lambda row, record: _validate_source_inventory_row(
                    row,
                    record,
                    import_session.source_asset_id,
                ),
                factory=SourceInventory.from_persistence_dict,
            ),
            "source_inventory_id",
        )
        source_inventory_items = _sort_records(
            _query_import_rows(
                self.connection,
                table_name="source_inventory_item",
                id_field="source_inventory_item_id",
                mail_import_session_id=import_session_id,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                scope_columns=(
                    "source_inventory_id",
                    "source_asset_id",
                    "source_fingerprint",
                    "parser_fingerprint",
                ),
                row_validator=_validate_source_inventory_item_row,
                factory=SourceInventoryItem.from_persistence_dict,
            ),
            "source_inventory_item_id",
        )
        _validate_source_inventory_rows(source_inventories, source_inventory_items)
        structural_observations = _sort_records(
            _query_import_rows(
                self.connection,
                table_name="structural_observation",
                id_field="structural_observation_id",
                mail_import_session_id=import_session_id,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                scope_columns=(
                    "source_inventory_item_id",
                    "source_inventory_id",
                    "source_asset_id",
                    "source_fingerprint",
                    "parser_fingerprint",
                ),
                row_validator=lambda row, record: _validate_structural_observation_row(
                    row,
                    record,
                    source_inventory_items,
                ),
                factory=StructuralObservation.from_persistence_dict,
            ),
            "structural_observation_id",
        )
        claim_requirements = _sort_records(
            _query_import_rows(
                self.connection,
                table_name="claim_requirement",
                id_field="claim_requirement_id",
                mail_import_session_id=import_session_id,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                factory=ClaimRequirement.from_dict,
            ),
            "claim_requirement_id",
        )
        coverage_ledgers = _sort_records(
            _query_import_rows(
                self.connection,
                table_name="coverage_ledger",
                id_field="coverage_ledger_id",
                mail_import_session_id=import_session_id,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                scope_columns=(
                    "query_id",
                    "claim_requirement_id",
                    "source_inventory_id",
                    "source_asset_id",
                    "source_fingerprint",
                    "parser_fingerprint",
                ),
                row_validator=lambda row, record: _validate_coverage_ledger_row(
                    row,
                    record,
                    source_inventories,
                    claim_requirements,
                ),
                factory=CoverageLedger.from_persistence_dict,
            ),
            "coverage_ledger_id",
        )
        version_manifests = _sort_records(
            _query_import_rows(
                self.connection,
                table_name="version_manifest",
                id_field="version_manifest_id",
                mail_import_session_id=import_session_id,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                factory=VersionManifest.from_dict,
            ),
            "version_manifest_id",
        )
        inventory_by_id = {item.source_inventory_id: item for item in source_inventories}
        requirement_by_id = {item.claim_requirement_id: item for item in claim_requirements}
        ledger_by_id = {item.coverage_ledger_id: item for item in coverage_ledgers}
        manifest_by_id = {item.version_manifest_id: item for item in version_manifests}
        answer_claims = _sort_records(
            _query_import_rows(
                self.connection,
                table_name="answer_claim",
                id_field="answer_claim_id",
                mail_import_session_id=import_session_id,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                scope_columns=("claim_requirement_id", "coverage_ledger_id"),
                row_validator=lambda row, record: _validate_answer_claim_row(
                    row,
                    record,
                    claim_requirements,
                    coverage_ledgers,
                ),
                factory=lambda payload: AnswerClaim.from_persistence_dict(
                    payload,
                    coverage_ledger=ledger_by_id.get(payload.get("coverage_ledger_id")),
                    claim_requirement=requirement_by_id.get(payload.get("claim_requirement_id")),
                    source_inventory=(
                        inventory_by_id.get(
                            ledger_by_id[payload["coverage_ledger_id"]].source_inventory_id
                        )
                        if payload.get("coverage_ledger_id") in ledger_by_id
                        else None
                    ),
                    version_manifest=manifest_by_id.get(payload.get("version_manifest_id")),
                    authorization_binding=(
                        ledger_by_id[payload["coverage_ledger_id"]].authorization_binding
                        if payload.get("coverage_ledger_id") in ledger_by_id
                        else None
                    ),
                ),
            ),
            "answer_claim_id",
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

        bundle_payload = {
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
            "embedded_message_relations": [item.to_dict() for item in embedded_message_relations],
            "mail_parse_run": parse_runs[0].to_dict(),
            "parse_warnings": [item.to_dict() for item in parse_warnings],
            "created_at": _safe_row_str(session_row, "bundle_created_at"),
            "source_inventory": [item.to_persistence_dict() for item in source_inventories],
            "source_inventory_items": [
                item.to_persistence_dict() for item in source_inventory_items
            ],
            "structural_observations": [
                item.to_persistence_dict() for item in structural_observations
            ],
            "claim_requirements": [item.to_dict() for item in claim_requirements],
            "coverage_ledgers": [item.to_dict() for item in coverage_ledgers],
            "answer_claims": [item.to_persistence_dict() for item in answer_claims],
            "version_manifests": [item.to_dict() for item in version_manifests],
            _WP1_PERSISTENCE_FIELD: wp1_persistence,
        }
        _validate_wp1_persistence_state(
            wp1_persistence,
            expected_counts={
                field_name: len(bundle_payload[field_name])
                for field_name in _WP1_PERSISTENCE_FAMILY_FIELDS
            },
        )
        return MailEvidenceBundle.from_persistence_dict(bundle_payload)


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


def mail_evidence_postgre_sql_tables(
    *,
    include_evidence_coverage: bool = False,
) -> tuple[str, ...]:
    """Return the legacy table manifest, with WP1 tables opt-in.

    The no-argument form remains compatible with existing Phase 1 adapters.
    New callers that need the complete normalized mail plus coverage schema
    pass ``include_evidence_coverage=True``.
    """

    return _TABLE_NAMES if include_evidence_coverage else _PHASE1_TABLE_NAMES


def evidence_coverage_postgre_sql_tables() -> tuple[str, ...]:
    return _TABLE_NAMES[12:]


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
        "idx_source_inventory_import",
        "idx_source_inventory_item_import",
        "idx_structural_observation_import",
        "idx_claim_requirement_query",
        "idx_coverage_ledger_query",
        "idx_answer_claim_ledger",
        "idx_version_manifest_import",
    )


def _statements_for_bundle(bundle: MailEvidenceBundle) -> list[SQLStatement]:
    workspace_id = bundle.mail_import_session.workspace_id
    owner_user_id = bundle.mail_import_session.owner_user_id
    import_session_id = bundle.mail_import_session.mail_import_session_id
    inventory_by_id = {item.source_inventory_id: item for item in bundle.source_inventory}
    inventory_by_item_id = {
        child.source_inventory_item_id: (inventory, child)
        for inventory in bundle.source_inventory
        for child in inventory.items
    }
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
    statements.extend(
        _import_scoped_statement(
            table_name="source_inventory",
            id_field="source_inventory_id",
            record=inventory,
            mail_import_session_id=import_session_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            append_only=True,
            extra_parameters={
                "source_asset_id": inventory.source_asset_id,
                "source_fingerprint": inventory.source_fingerprint,
                "parser_fingerprint": inventory.parser_fingerprint,
            },
        )
        for inventory in bundle.source_inventory
    )
    statements.extend(
        _import_scoped_statement(
            table_name="source_inventory_item",
            id_field="source_inventory_item_id",
            record=item,
            mail_import_session_id=import_session_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            append_only=True,
            extra_parameters={
                "source_inventory_id": item.source_inventory_id,
                "source_asset_id": item.source_asset_id,
                "source_fingerprint": item.source_fingerprint,
                "parser_fingerprint": item.parser_fingerprint,
            },
        )
        for item in bundle.source_inventory_items
    )
    statements.extend(
        _import_scoped_statement(
            table_name="structural_observation",
            id_field="structural_observation_id",
            record=item,
            mail_import_session_id=import_session_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            append_only=True,
            extra_parameters={
                "source_inventory_item_id": item.source_inventory_item_id,
                "source_inventory_id": inventory_by_item_id[item.source_inventory_item_id][
                    0
                ].source_inventory_id,
                "source_asset_id": item.source_asset_id,
                "source_fingerprint": item.source_fingerprint,
                "parser_fingerprint": item.parser_fingerprint,
            },
        )
        for item in bundle.structural_observations
    )
    statements.extend(
        _import_scoped_statement(
            table_name="claim_requirement",
            id_field="claim_requirement_id",
            record=item,
            mail_import_session_id=import_session_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            append_only=True,
            extra_parameters={"query_id": item.query_id},
        )
        for item in bundle.claim_requirements
    )
    statements.extend(
        _import_scoped_statement(
            table_name="coverage_ledger",
            id_field="coverage_ledger_id",
            record=item,
            mail_import_session_id=import_session_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            append_only=True,
            extra_parameters={
                "query_id": item.query_id,
                "claim_requirement_id": item.claim_requirement_id,
                "source_inventory_id": item.source_inventory_id,
                "source_asset_id": inventory_by_id[item.source_inventory_id].source_asset_id,
                "source_fingerprint": inventory_by_id[item.source_inventory_id].source_fingerprint,
                "parser_fingerprint": inventory_by_id[item.source_inventory_id].parser_fingerprint,
            },
        )
        for item in bundle.coverage_ledgers
    )
    statements.extend(
        _import_scoped_statement(
            table_name="answer_claim",
            id_field="answer_claim_id",
            record=item,
            mail_import_session_id=import_session_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            append_only=True,
            extra_parameters={
                "claim_requirement_id": item.claim_requirement_id,
                "coverage_ledger_id": item.coverage_ledger_id,
            },
        )
        for item in bundle.answer_claims
    )
    statements.extend(
        _import_scoped_statement(
            table_name="version_manifest",
            id_field="version_manifest_id",
            record=item,
            mail_import_session_id=import_session_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            append_only=True,
        )
        for item in bundle.version_manifests
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
    payload[_WP1_PERSISTENCE_FIELD] = _wp1_persistence_state(bundle)
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
    append_only: bool = False,
    extra_parameters: dict[str, Any] | None = None,
) -> SQLStatement:
    _validate_table_name(table_name)
    payload = _record_payload(record)
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
    immutable_columns = (
        "mail_import_session_id",
        "workspace_id",
        "owner_user_id",
        *extras,
        "payload",
        "payload_hash",
    )
    conflict_predicate = " AND ".join(
        f"{table_name}.{column} IS NOT DISTINCT FROM EXCLUDED.{column}"
        for column in immutable_columns
    )
    conflict_update = (
        f"ON CONFLICT ({id_field}) DO UPDATE SET "
        f"payload = {table_name}.payload, "
        "payload_hash = CASE "
        f"WHEN {conflict_predicate} THEN {table_name}.payload_hash "
        "ELSE NULL END, "
        f"updated_at = {table_name}.updated_at"
        if append_only
        else (
            f"ON CONFLICT ({id_field}) DO UPDATE SET "
            "payload = EXCLUDED.payload, payload_hash = EXCLUDED.payload_hash, "
            "updated_at = now()"
        )
    )
    return SQLStatement(
        sql=(
            f"INSERT INTO {table_name} "
            f"({id_field}, mail_import_session_id, workspace_id, owner_user_id"
            f"{extra_columns}, payload, payload_hash) "
            f"VALUES (%({id_field})s, %(mail_import_session_id)s, %(workspace_id)s, "
            f"%(owner_user_id)s{extra_values}, %(payload)s::jsonb, %(payload_hash)s) "
            f"{conflict_update}"
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


def _record_payload(record: Any) -> dict[str, Any]:
    serializer = getattr(record, "to_persistence_dict", None)
    if callable(serializer):
        payload = serializer()
    else:
        payload = record.to_dict()
    if not isinstance(payload, dict):
        raise ContractValidationError("persisted mail evidence record must serialize to an object")
    return payload


def _validate_source_inventory_rows(
    inventories: Sequence[SourceInventory],
    items: Sequence[SourceInventoryItem],
) -> None:
    expected = {
        item.source_inventory_item_id: item.to_persistence_dict()
        for inventory in inventories
        for item in inventory.items
    }
    actual = {item.source_inventory_item_id: item.to_persistence_dict() for item in items}
    if len(actual) != len(items) or actual != expected:
        raise ContractValidationError(
            "postgres source inventory child rows do not match persisted aggregates"
        )


def _validate_row_scope(
    row: dict[str, Any],
    *,
    mail_import_session_id: str,
    workspace_id: str,
    owner_user_id: str,
) -> None:
    expected = {
        "mail_import_session_id": mail_import_session_id,
        "workspace_id": workspace_id,
        "owner_user_id": owner_user_id,
    }
    for field_name, expected_value in expected.items():
        value = row.get(field_name)
        if not isinstance(value, str) or value != expected_value:
            raise ContractValidationError("persisted mail evidence row scope is inconsistent")


def _validate_row_relationship(
    row: dict[str, Any],
    expected: Mapping[str, str],
) -> None:
    for field_name, expected_value in expected.items():
        value = row.get(field_name)
        if not isinstance(value, str) or value != expected_value:
            raise ContractValidationError(
                "persisted mail evidence row relationship scope is inconsistent"
            )


def _validate_source_inventory_row(
    row: dict[str, Any],
    record: SourceInventory,
    import_session_source_asset_id: str,
) -> None:
    if record.source_asset_id != import_session_source_asset_id:
        raise ContractValidationError(
            "persisted source inventory asset does not match import session"
        )
    _validate_row_relationship(
        row,
        {
            "source_inventory_id": record.source_inventory_id,
            "source_asset_id": record.source_asset_id,
            "source_fingerprint": record.source_fingerprint,
            "parser_fingerprint": record.parser_fingerprint,
        },
    )


def _validate_source_inventory_item_row(
    row: dict[str, Any],
    record: SourceInventoryItem,
) -> None:
    if record.source_inventory_id is None:
        raise ContractValidationError("persisted inventory item is not bound to an aggregate")
    _validate_row_relationship(
        row,
        {
            "source_inventory_item_id": record.source_inventory_item_id,
            "source_inventory_id": record.source_inventory_id,
            "source_asset_id": record.source_asset_id,
            "source_fingerprint": record.source_fingerprint,
            "parser_fingerprint": record.parser_fingerprint,
        },
    )


def _validate_structural_observation_row(
    row: dict[str, Any],
    record: StructuralObservation,
    source_inventory_items: Sequence[SourceInventoryItem],
) -> None:
    item_by_id = {item.source_inventory_item_id: item for item in source_inventory_items}
    inventory_item = item_by_id.get(record.source_inventory_item_id)
    if inventory_item is None or inventory_item.source_inventory_id is None:
        raise ContractValidationError(
            "persisted structural observation references an orphan inventory item"
        )
    _validate_row_relationship(
        row,
        {
            "source_inventory_item_id": record.source_inventory_item_id,
            "source_inventory_id": inventory_item.source_inventory_id,
            "source_asset_id": record.source_asset_id,
            "source_fingerprint": record.source_fingerprint,
            "parser_fingerprint": record.parser_fingerprint,
        },
    )


def _validate_coverage_ledger_row(
    row: dict[str, Any],
    record: CoverageLedger,
    source_inventories: Sequence[SourceInventory],
    claim_requirements: Sequence[ClaimRequirement],
) -> None:
    inventory_by_id = {item.source_inventory_id: item for item in source_inventories}
    requirement_by_id = {item.claim_requirement_id: item for item in claim_requirements}
    inventory = inventory_by_id.get(record.source_inventory_id)
    requirement = requirement_by_id.get(record.claim_requirement_id)
    if inventory is None or requirement is None:
        raise ContractValidationError("persisted coverage ledger references an orphan relationship")
    _validate_row_relationship(
        row,
        {
            "query_id": record.query_id,
            "claim_requirement_id": requirement.claim_requirement_id,
            "source_inventory_id": inventory.source_inventory_id,
            "source_asset_id": inventory.source_asset_id,
            "source_fingerprint": inventory.source_fingerprint,
            "parser_fingerprint": inventory.parser_fingerprint,
        },
    )


def _validate_answer_claim_row(
    row: dict[str, Any],
    record: AnswerClaim,
    claim_requirements: Sequence[ClaimRequirement],
    coverage_ledgers: Sequence[CoverageLedger],
) -> None:
    requirement_ids = {item.claim_requirement_id for item in claim_requirements}
    ledger_by_id = {item.coverage_ledger_id: item for item in coverage_ledgers}
    ledger = ledger_by_id.get(record.coverage_ledger_id)
    if record.claim_requirement_id not in requirement_ids or ledger is None:
        raise ContractValidationError("persisted answer claim references an orphan relationship")
    if ledger.claim_requirement_id != record.claim_requirement_id:
        raise ContractValidationError("persisted answer claim relationship scope is inconsistent")
    _validate_row_relationship(
        row,
        {
            "claim_requirement_id": record.claim_requirement_id,
            "coverage_ledger_id": record.coverage_ledger_id,
        },
    )


def _query_import_rows(
    connection: PostgreSQLMailEvidenceConnection,
    *,
    table_name: str,
    id_field: str,
    mail_import_session_id: str,
    workspace_id: str,
    owner_user_id: str,
    scope_columns: Sequence[str] = (),
    row_validator: Callable[[dict[str, Any], Any], None] | None = None,
    factory: Callable[[dict[str, Any]], Any],
) -> list[Any]:
    _validate_table_name(table_name)
    _validate_record_id(id_field, "id_field")
    _validate_record_id(mail_import_session_id, "mail_import_session_id")
    _validate_record_id(workspace_id, "workspace_id")
    _validate_record_id(owner_user_id, "owner_user_id")
    for column_name in scope_columns:
        if not _SAFE_RECORD_ID.fullmatch(column_name):
            raise ContractValidationError("invalid persisted scope column")
    selected_columns = ", ".join(
        (id_field, "payload", "mail_import_session_id", "workspace_id", "owner_user_id")
        + tuple(scope_columns)
    )
    rows = connection.query_all(
        SQLStatement(
            sql=(
                f"SELECT {selected_columns} FROM {table_name} "
                "WHERE mail_import_session_id = %(mail_import_session_id)s "
                "ORDER BY payload_hash"
            ),
            parameters={"mail_import_session_id": mail_import_session_id},
        )
    )
    records = []
    for row in rows:
        _validate_row_scope(
            row,
            mail_import_session_id=mail_import_session_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
        )
        record = factory(_payload(row))
        record_payload = _record_payload(record)
        if row.get(id_field) != record_payload.get(id_field):
            raise ContractValidationError("persisted mail evidence row identifier is inconsistent")
        if row_validator is not None:
            row_validator(row, record)
        records.append(record)
    return records


def _sort_records(records: Sequence[Any], id_field: str) -> list[Any]:
    return canonical_order_records(canonical_family_for_id_field(id_field), records)


def _sort_body_segments(records: Sequence[EmailBodySegment]) -> list[EmailBodySegment]:
    return canonical_order_records("body_segments", records)


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
    records = [factory(_payload(row)) for row in rows]
    return canonical_order_records(canonical_table_family(table_name), records)


def _validate_bundle(bundle: MailEvidenceBundle | dict[str, Any]) -> MailEvidenceBundle:
    if isinstance(bundle, MailEvidenceBundle):
        payload = bundle.to_persistence_dict()
    elif isinstance(bundle, dict):
        payload = to_plain(bundle)
    else:
        raise ContractValidationError("mail evidence store requires a bundle")
    return MailEvidenceBundle.from_persistence_dict(payload)


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
    "evidence_coverage_postgre_sql_tables",
    "mail_evidence_postgre_sql_tables",
    "mail_evidence_query_indexes",
    "postgre_sql_mail_evidence_store_interfaces",
]
