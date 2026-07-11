from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Mapping

from formowl_contract import (
    ContractValidationError,
    McpResultEnvelope,
    now_iso,
    sha256_json,
    to_plain,
)

_FORBIDDEN_PUBLIC_KEYS = {
    "absolute_path",
    "access_key",
    "bucket",
    "bucket_name",
    "connection_string",
    "database_url",
    "debug_path",
    "dsn",
    "exception_trace",
    "filesystem_path",
    "internal_backend_id",
    "internal_endpoint",
    "internal_sql",
    "internal_url",
    "minio_endpoint",
    "nas_path",
    "object_key",
    "object_store_key",
    "object_store_uri",
    "parser_debug",
    "presigned_url",
    "raw_path",
    "secret",
    "signed_url",
    "sql",
    "stack_trace",
    "storage_key",
    "token",
    "traceback",
    "worker_scratch",
}
_FORBIDDEN_PUBLIC_VALUE_PATTERNS = (
    re.compile(r"(^|[\"'\s])/(srv|home|tmp|var|mnt|opt|root)/", re.IGNORECASE),
    re.compile(r"\b[a-z]:\\", re.IGNORECASE),
    re.compile(
        r"\b(file|smb|nfs|s3|minio|object|webdav|gs|azure|postgres|postgresql|mysql|sqlite)://",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bhttps?://(localhost|127\.0\.0\.1|10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b("
        r"select\s+.+\s+from|"
        r"with\s+.+\s+as\s*\(|"
        r"copy\s+.+\s+from|"
        r"insert\s+into|"
        r"update\s+[A-Za-z_][\w.]*\s+set|"
        r"delete\s+from|"
        r"drop\s+table|"
        r"alter\s+table"
        r")\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bTraceback \(most recent call last\):", re.IGNORECASE),
)

PUBLIC_TOOL_SCHEMAS = [
    {
        "tool_name": "open_upload_session",
        "workflow": "upload",
        "input_keys": [
            "workspace_id",
            "requester_user_id",
            "intent",
            "intended_asset_type",
            "permission_scope",
        ],
        "output_keys": [
            "upload_session_id",
            "status",
            "next_required_action",
            "upload_task_card",
            "source_preparation_guidance",
        ],
        "result_type": "upload_session_request",
        "status_values": ["pending_review", "ok", "error"],
    },
    {
        "tool_name": "create_ingestion_job",
        "workflow": "ingestion",
        "input_keys": ["workspace_id", "requester_user_id", "asset_locator", "extractor_profile"],
        "output_keys": ["ingestion_job_id", "status", "next_required_action"],
        "result_type": "ingestion_job_request",
        "status_values": ["pending_review", "error"],
    },
    {
        "tool_name": "list_observations",
        "workflow": "observation",
        "input_keys": [
            "workspace_id",
            "requester_user_id",
            "asset_locator",
            "observation_filter",
        ],
        "output_keys": ["observations", "redaction_counts", "warnings"],
        "result_type": "observation_listing",
        "status_values": ["pending_review", "ok", "error"],
    },
    {
        "tool_name": "preview_graph_candidates",
        "workflow": "candidate_graph",
        "input_keys": ["workspace_id", "candidate_filter", "requester_user_id"],
        "output_keys": ["candidate_summaries", "redaction_counts", "warnings"],
        "result_type": "candidate_preview",
        "status_values": ["pending_review", "ok", "error"],
    },
    {
        "tool_name": "query_effective_graph",
        "workflow": "access",
        "compatibility": {
            "status": "deprecated_alias",
            "canonical_tool_name": "query_effective_graph_view",
        },
        "input_keys": ["workspace_id", "query_text", "requester_user_id"],
        "output_keys": ["answer", "citations", "visible_graph_snippets", "redaction_counts"],
        "result_type": "effective_graph_query",
        "status_values": ["pending_review", "ok", "permission_denied", "error"],
    },
    {
        "tool_name": "query_effective_graph_view",
        "workflow": "access",
        "compatibility": {"status": "canonical"},
        "input_keys": ["workspace_id", "query_text", "requester_user_id"],
        "output_keys": [
            "answer",
            "graph_hits",
            "evidence",
            "fallback_used",
            "fallback_reason",
            "evidence_coverage",
            "candidate_graph_proposal_seeds",
            "citations",
            "visible_graph_snippets",
            "redaction_counts",
            "warnings",
        ],
        "result_type": "effective_graph_query",
        "status_values": ["pending_review", "ok", "permission_denied", "error"],
    },
    {
        "tool_name": "query_mail_evidence",
        "workflow": "mail_evidence",
        "input_keys": [
            "workspace_id",
            "requester_user_id",
            "query_text",
            "mail_import_session_id",
            "mail_evidence_bundle_id",
        ],
        "output_keys": [
            "mail_import_session_id",
            "evidence_snippets",
            "citations",
            "redaction_counts",
            "warnings",
        ],
        "result_type": "mail_evidence_query",
        "status_values": ["pending_review", "ok", "not_found", "permission_denied", "error"],
    },
    {
        "tool_name": "answer_mail_case_progress",
        "workflow": "mail_evidence",
        "input_keys": [
            "workspace_id",
            "requester_user_id",
            "case_id",
            "mail_import_session_id",
            "mail_evidence_bundle_id",
        ],
        "output_keys": [
            "mail_import_session_id",
            "mail_evidence_bundle_id",
            "case_id",
            "latest_updates",
            "blockers",
            "responsible_parties",
            "next_actions",
            "deadlines",
            "citations",
            "redaction_counts",
            "warnings",
            "claim_boundary",
        ],
        "result_type": "mail_case_progress_answer",
        "status_values": ["pending_review", "ok", "not_found", "permission_denied", "error"],
    },
    {
        "tool_name": "request_graph_access",
        "workflow": "access",
        "input_keys": [
            "workspace_id",
            "requester_user_id",
            "owner_user_id",
            "requested_scope",
            "requested_access_level",
            "reason",
        ],
        "output_keys": ["access_request_id", "status", "next_required_action"],
        "result_type": "access_request",
        "status_values": ["pending_review", "error"],
    },
    {
        "tool_name": "submit_graph_review_decision",
        "workflow": "candidate_graph",
        "input_keys": ["proposal_id", "decision", "reviewer_user_id"],
        "output_keys": ["status", "audit_ref", "next_required_action"],
        "result_type": "graph_review_decision",
        "status_values": ["pending_review", "error"],
    },
    {
        "tool_name": "generate_wiki_draft_from_graph_view",
        "workflow": "wiki_projection",
        "input_keys": ["projection_spec_id", "requester_user_id"],
        "output_keys": ["draft_id", "revision_status", "citations", "redaction_counts"],
        "result_type": "wiki_projection_request",
        "status_values": ["pending_review", "ok", "error"],
    },
]
_PUBLIC_TOOL_NAMES = {schema["tool_name"] for schema in PUBLIC_TOOL_SCHEMAS}
_FORBIDDEN_TOOL_NAMES = {
    "direct_database_query_tool",
    "direct_filesystem_read_tool",
    "direct_canonical_mutation_tool",
}
_MAIL_CASE_PROGRESS_CLAIM_KEYS = {
    "supports_mail_case_progress_answer_claim",
    "supports_actual_chatgpt_connected_upload_claim",
    "supports_upload_ui_claim",
    "supports_production_iframe_readiness_claim",
    "supports_real_pst_parser_claim",
    "supports_live_postgresql_readiness_claim",
    "supports_production_worker_leasing_claim",
    "supports_kg_write_claim",
    "supports_wiki_projection_claim",
    "supports_production_ready_claim",
}
_MAIL_CASE_PROGRESS_FORBIDDEN_TRUE_CLAIMS = _MAIL_CASE_PROGRESS_CLAIM_KEYS - {
    "supports_mail_case_progress_answer_claim"
}


@dataclass(frozen=True)
class ToolCallLog:
    tool_call_log_id: str
    tool_name: str
    called_at: str
    arguments_hash: str
    response_hash: str
    status: str
    audit_log_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


class SemanticMcpGateway:
    """Public semantic MCP facade with safe envelopes and proposal boundaries."""

    def __init__(
        self,
        *,
        upload_session_handler: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        ingestion_handler: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        observation_handler: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        preview_handler: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        retrieval_handler: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        mail_evidence_handler: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        mail_case_progress_handler: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        access_request_handler: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        review_decision_handler: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        wiki_projection_handler: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.upload_session_handler = upload_session_handler
        self.ingestion_handler = ingestion_handler
        self.observation_handler = observation_handler
        self.preview_handler = preview_handler
        self.retrieval_handler = retrieval_handler
        self.mail_evidence_handler = mail_evidence_handler
        self.mail_case_progress_handler = mail_case_progress_handler
        self.access_request_handler = access_request_handler
        self.review_decision_handler = review_decision_handler
        self.wiki_projection_handler = wiki_projection_handler
        self.tool_call_logs: list[ToolCallLog] = []

    def public_tool_schema(self) -> dict[str, Any]:
        envelope = _envelope(
            result_type="semantic_gateway_tool_schema",
            status="ok",
            data={
                "tools": [
                    {
                        **schema,
                        "forbidden_output_keys": sorted(_FORBIDDEN_PUBLIC_KEYS),
                    }
                    for schema in PUBLIC_TOOL_SCHEMAS
                ]
            },
        )
        self._record_tool_call("public_tool_schema", {}, envelope)
        return envelope

    def dispatch_tool(self, tool_name: str, input_data: Mapping[str, Any]) -> dict[str, Any]:
        if tool_name in _FORBIDDEN_TOOL_NAMES:
            envelope = safe_workflow_error_envelope(
                workflow="semantic_gateway",
                tool_name=tool_name,
                error_code="forbidden_tool",
            )
            self._record_tool_call(tool_name, dict(input_data), envelope)
            return envelope
        if tool_name not in _PUBLIC_TOOL_NAMES:
            envelope = safe_workflow_error_envelope(
                workflow="semantic_gateway",
                tool_name=tool_name,
                error_code="unknown_tool",
            )
            self._record_tool_call(tool_name, dict(input_data), envelope)
            return envelope

        if tool_name == "open_upload_session":
            envelope = self._open_upload_session(dict(input_data))
        elif tool_name == "create_ingestion_job":
            envelope = self._create_ingestion_job(dict(input_data))
        elif tool_name == "list_observations":
            envelope = self._list_observations(dict(input_data))
        elif tool_name == "preview_graph_candidates":
            envelope = self._preview_graph_candidates(dict(input_data))
        elif tool_name in {"query_effective_graph", "query_effective_graph_view"}:
            envelope = self._query_effective_graph(dict(input_data))
            if tool_name == "query_effective_graph":
                envelope = dict(envelope)
                envelope["warnings"] = [
                    *envelope.get("warnings", []),
                    "deprecated_alias_use_query_effective_graph_view",
                ]
        elif tool_name == "query_mail_evidence":
            envelope = self._query_mail_evidence(dict(input_data))
        elif tool_name == "answer_mail_case_progress":
            envelope = self._answer_mail_case_progress(dict(input_data))
        elif tool_name == "request_graph_access":
            envelope = self._request_graph_access(dict(input_data))
        elif tool_name == "submit_graph_review_decision":
            envelope = self._submit_graph_review_decision(dict(input_data))
        else:
            envelope = self._generate_wiki_draft_from_graph_view(dict(input_data))
        self._record_tool_call(tool_name, dict(input_data), envelope)
        return envelope

    def safe_error_envelope(
        self,
        *,
        tool_name: str,
        error_code: str = "gateway_error",
        workflow: str = "semantic_gateway",
    ) -> dict[str, Any]:
        envelope = safe_workflow_error_envelope(
            workflow=workflow,
            tool_name=tool_name,
            error_code=error_code,
        )
        self._record_tool_call(tool_name, {}, envelope)
        return envelope

    def _open_upload_session(self, input_data: dict[str, Any]) -> dict[str, Any]:
        if self.upload_session_handler is None:
            return _handler_not_configured("open_upload_session")
        return _safe_handler_envelope(
            result_type="upload_session_request",
            handler_payload=self.upload_session_handler(input_data),
            status_from_payload=True,
        )

    def _create_ingestion_job(self, input_data: dict[str, Any]) -> dict[str, Any]:
        if self.ingestion_handler is None:
            return _handler_not_configured("create_ingestion_job")
        return _safe_handler_envelope(
            result_type="ingestion_job_request",
            handler_payload=self.ingestion_handler(input_data),
            status_from_payload=True,
        )

    def _list_observations(self, input_data: dict[str, Any]) -> dict[str, Any]:
        if self.observation_handler is None:
            return _handler_not_configured("list_observations")
        return _safe_handler_envelope(
            result_type="observation_listing",
            handler_payload=self.observation_handler(input_data),
            status_from_payload=True,
        )

    def _preview_graph_candidates(self, input_data: dict[str, Any]) -> dict[str, Any]:
        if self.preview_handler is None:
            return _handler_not_configured("preview_graph_candidates")
        return _safe_handler_envelope(
            result_type="candidate_preview",
            handler_payload=self.preview_handler(input_data),
        )

    def _query_effective_graph(self, input_data: dict[str, Any]) -> dict[str, Any]:
        if self.retrieval_handler is None:
            return _handler_not_configured("query_effective_graph_view")
        return _safe_handler_envelope(
            result_type="effective_graph_query",
            handler_payload=self.retrieval_handler(input_data),
        )

    def _query_mail_evidence(self, input_data: dict[str, Any]) -> dict[str, Any]:
        if self.mail_evidence_handler is None:
            return _handler_not_configured("query_mail_evidence")
        return _safe_handler_envelope(
            result_type="mail_evidence_query",
            handler_payload=self.mail_evidence_handler(input_data),
            status_from_payload=True,
        )

    def _answer_mail_case_progress(self, input_data: dict[str, Any]) -> dict[str, Any]:
        if self.mail_case_progress_handler is None:
            return _handler_not_configured("answer_mail_case_progress")
        handler_payload = self.mail_case_progress_handler(input_data)
        _validate_mail_case_progress_handler_payload(handler_payload)
        return _safe_handler_envelope(
            result_type="mail_case_progress_answer",
            handler_payload=handler_payload,
            status_from_payload=True,
        )

    def _request_graph_access(self, input_data: dict[str, Any]) -> dict[str, Any]:
        if self.access_request_handler is None:
            return _handler_not_configured("request_graph_access")
        return _safe_handler_envelope(
            result_type="access_request",
            handler_payload=self.access_request_handler(input_data),
            status_from_payload=True,
        )

    def _submit_graph_review_decision(self, input_data: dict[str, Any]) -> dict[str, Any]:
        if self.review_decision_handler is None:
            return _handler_not_configured("submit_graph_review_decision")
        return _safe_handler_envelope(
            result_type="graph_review_decision",
            handler_payload=self.review_decision_handler(input_data),
            status_from_payload=True,
        )

    def _generate_wiki_draft_from_graph_view(self, input_data: dict[str, Any]) -> dict[str, Any]:
        if self.wiki_projection_handler is None:
            return _handler_not_configured("generate_wiki_draft_from_graph_view")
        return _safe_handler_envelope(
            result_type="wiki_projection_request",
            handler_payload=self.wiki_projection_handler(input_data),
        )

    def _record_tool_call(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        envelope: dict[str, Any],
    ) -> None:
        self.tool_call_logs.append(
            ToolCallLog(
                tool_call_log_id=f"tool_call_{sha256_json([tool_name, input_data])[-24:]}",
                tool_name=tool_name,
                called_at=now_iso(),
                arguments_hash=sha256_json(input_data),
                response_hash=sha256_json(envelope),
                status=str(envelope.get("status", "unknown")),
                audit_log_id=envelope.get("data", {}).get("audit_ref"),
            )
        )


def public_tool_schema() -> dict[str, Any]:
    return SemanticMcpGateway().public_tool_schema()


def safe_error_envelope(
    *,
    tool_name: str,
    error_code: str = "gateway_error",
) -> dict[str, Any]:
    return safe_workflow_error_envelope(
        workflow="semantic_gateway",
        tool_name=tool_name,
        error_code=error_code,
    )


def safe_workflow_error_envelope(
    *,
    workflow: str,
    tool_name: str,
    error_code: str = "gateway_error",
) -> dict[str, Any]:
    workflow_name = _safe_public_string(workflow, "semantic_gateway")
    tool = _safe_public_string(tool_name, "unknown_tool")
    error = _safe_public_string(error_code, "gateway_error")
    return _envelope(
        result_type=f"{workflow_name}_gateway_error",
        status="error",
        data={
            "workflow": workflow_name,
            "tool_name": tool,
            "error_code": error,
            "message": "The FormOwl gateway rejected this request.",
        },
        warnings=["safe_error_envelope"],
    )


def _handler_not_configured(tool_name: str) -> dict[str, Any]:
    return safe_workflow_error_envelope(
        workflow="semantic_gateway",
        tool_name=tool_name,
        error_code="handler_not_configured",
    )


def validate_public_gateway_payload(payload: Any) -> None:
    violations: list[str] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key)
                next_path = f"{path}.{key_text}" if path else key_text
                if key_text.lower() in _FORBIDDEN_PUBLIC_KEYS:
                    violations.append(f"forbidden public key: {next_path}")
                walk(item, next_path)
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
            return
        if isinstance(value, str):
            for pattern in _FORBIDDEN_PUBLIC_VALUE_PATTERNS:
                if pattern.search(value):
                    violations.append(f"forbidden public value: {path}")
                    break

    walk(payload, "")
    if violations:
        from formowl_contract import ContractValidationError

        raise ContractValidationError("; ".join(violations))


def direct_database_query_tool() -> None:
    """Forbidden marker: direct_database_query_tool."""


def direct_filesystem_read_tool() -> None:
    """Forbidden marker: direct_filesystem_read_tool."""


def direct_canonical_mutation_tool() -> None:
    """Forbidden marker: direct_canonical_mutation_tool."""


def _validate_mail_case_progress_handler_payload(payload: dict[str, Any]) -> None:
    claim_boundary = payload.get("claim_boundary")
    if not isinstance(claim_boundary, dict):
        raise ContractValidationError("mail case-progress claim_boundary is required")
    extra = set(claim_boundary) - _MAIL_CASE_PROGRESS_CLAIM_KEYS
    missing = _MAIL_CASE_PROGRESS_CLAIM_KEYS - set(claim_boundary)
    if extra or missing:
        raise ContractValidationError("mail case-progress claim_boundary keys are invalid")
    if not isinstance(
        claim_boundary.get("supports_mail_case_progress_answer_claim"),
        bool,
    ):
        raise ContractValidationError("mail case-progress support claim must be boolean")
    for claim in _MAIL_CASE_PROGRESS_FORBIDDEN_TRUE_CLAIMS:
        if claim_boundary.get(claim) is not False:
            raise ContractValidationError("mail case-progress overclaims unsupported work")


def _safe_handler_envelope(
    *,
    result_type: str,
    handler_payload: dict[str, Any],
    status_from_payload: bool = False,
) -> dict[str, Any]:
    status = "ok"
    if status_from_payload:
        payload_status = handler_payload.get("status")
        status = payload_status if isinstance(payload_status, str) else "ok"
    envelope = _envelope(result_type=result_type, status=status, data=handler_payload)
    validate_public_gateway_payload(envelope)
    return envelope


def _envelope(
    *,
    result_type: str,
    status: str,
    data: dict[str, Any],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    envelope = McpResultEnvelope(
        result_type=result_type,
        status=status,  # type: ignore[arg-type]
        data=data,
        warnings=warnings or [],
    ).to_dict()
    validate_public_gateway_payload(envelope)
    return envelope


def _safe_public_string(value: Any, fallback: str) -> str:
    if not isinstance(value, str) or not value:
        return fallback
    try:
        validate_public_gateway_payload(value)
    except Exception:
        return fallback
    return value
