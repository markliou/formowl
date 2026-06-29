from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Mapping

from formowl_contract import AuditLog, McpResultEnvelope, now_iso, sha256_json, to_plain

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
        r"\b(file|smb|nfs|s3|minio|gs|azure|postgres|postgresql|mysql|sqlite)://",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bhttps?://(localhost|127\.0\.0\.1|10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.)",
        re.IGNORECASE,
    ),
    re.compile(r"\b(select|with|copy|insert|update|delete|drop|alter)\b\s+", re.IGNORECASE),
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
        "output_keys": ["upload_session_id", "status", "next_required_action"],
        "result_type": "upload_session_request",
        "status_values": ["pending_review", "error"],
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
        "input_keys": ["workspace_id", "query_text", "requester_user_id"],
        "output_keys": ["answer", "citations", "visible_graph_snippets", "redaction_counts"],
        "result_type": "effective_graph_query",
        "status_values": ["pending_review", "ok", "permission_denied", "error"],
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
        preview_handler: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        retrieval_handler: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        wiki_projection_handler: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.preview_handler = preview_handler
        self.retrieval_handler = retrieval_handler
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
        elif tool_name == "query_effective_graph":
            envelope = self._query_effective_graph(dict(input_data))
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
        return _pending_workflow_envelope(
            result_type="upload_session_request",
            data={
                "upload_session_id": None,
                "status": "pending_review",
                "next_required_action": "upload_handler_not_configured",
            },
            warning="upload_handler_not_configured",
        )

    def _create_ingestion_job(self, input_data: dict[str, Any]) -> dict[str, Any]:
        return _pending_workflow_envelope(
            result_type="ingestion_job_request",
            data={
                "ingestion_job_id": None,
                "status": "pending_review",
                "next_required_action": "ingestion_handler_not_configured",
            },
            warning="ingestion_handler_not_configured",
        )

    def _list_observations(self, input_data: dict[str, Any]) -> dict[str, Any]:
        return _pending_workflow_envelope(
            result_type="observation_listing",
            data={
                "observations": [],
                "redaction_counts": {"hidden_observations": 0},
                "warnings": ["observation_handler_not_configured"],
            },
            warning="observation_handler_not_configured",
        )

    def _preview_graph_candidates(self, input_data: dict[str, Any]) -> dict[str, Any]:
        if self.preview_handler is None:
            return _envelope(
                result_type="candidate_preview",
                status="pending_review",
                data={
                    "candidate_summaries": [],
                    "redaction_counts": {"hidden_candidates": 0},
                    "warnings": ["preview_handler_not_configured"],
                },
                warnings=["preview_handler_not_configured"],
            )
        return _safe_handler_envelope(
            result_type="candidate_preview",
            handler_payload=self.preview_handler(input_data),
        )

    def _query_effective_graph(self, input_data: dict[str, Any]) -> dict[str, Any]:
        if self.retrieval_handler is None:
            return _envelope(
                result_type="effective_graph_query",
                status="pending_review",
                data={
                    "answer": None,
                    "citations": [],
                    "visible_graph_snippets": [],
                    "redaction_counts": {"hidden_records": 0},
                },
                warnings=["retrieval_handler_not_configured"],
            )
        return _safe_handler_envelope(
            result_type="effective_graph_query",
            handler_payload=self.retrieval_handler(input_data),
        )

    def _request_graph_access(self, input_data: dict[str, Any]) -> dict[str, Any]:
        requester_user_id = _safe_public_string(input_data.get("requester_user_id"), "requester")
        owner_user_id = _safe_public_string(input_data.get("owner_user_id"), "owner")
        scope = input_data.get("requested_scope")
        scope_hash = sha256_json(scope if isinstance(scope, Mapping) else {})
        request_payload = {
            "requester_user_id": requester_user_id,
            "owner_user_id": owner_user_id,
            "scope_hash": scope_hash,
            "requested_access_level": _safe_public_string(
                input_data.get("requested_access_level"), "answer_only"
            ),
        }
        access_request_id = f"access_request_{sha256_json(request_payload)[-24:]}"
        return _pending_workflow_envelope(
            result_type="access_request",
            data={
                "access_request_id": access_request_id,
                "status": "pending_review",
                "next_required_action": "owner_review_required",
            },
            warning="access_request_requires_review",
        )

    def _submit_graph_review_decision(self, input_data: dict[str, Any]) -> dict[str, Any]:
        proposal_id = _safe_public_string(input_data.get("proposal_id"), "proposal_unknown")
        decision = _safe_public_string(input_data.get("decision"), "defer")
        reviewer_user_id = _safe_public_string(input_data.get("reviewer_user_id"), "reviewer")
        audit_log = _audit_log(
            actor_user_id=reviewer_user_id,
            action="submit_graph_review_decision",
            target_id=proposal_id,
            status="pending_review",
        )
        return _envelope(
            result_type="graph_review_decision",
            status="pending_review",
            data={
                "status": "pending_review",
                "decision": decision,
                "audit_ref": audit_log.audit_log_id,
                "next_required_action": "governed_backend_review_required",
            },
        )

    def _generate_wiki_draft_from_graph_view(self, input_data: dict[str, Any]) -> dict[str, Any]:
        if self.wiki_projection_handler is None:
            return _envelope(
                result_type="wiki_projection_request",
                status="pending_review",
                data={
                    "draft_id": None,
                    "revision_status": "pending_projection",
                    "citations": [],
                    "redaction_counts": {"hidden_evidence": 0},
                },
                warnings=["wiki_projection_handler_not_configured"],
            )
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


def _safe_handler_envelope(*, result_type: str, handler_payload: dict[str, Any]) -> dict[str, Any]:
    envelope = _envelope(result_type=result_type, status="ok", data=handler_payload)
    validate_public_gateway_payload(envelope)
    return envelope


def _pending_workflow_envelope(
    *,
    result_type: str,
    data: dict[str, Any],
    warning: str,
) -> dict[str, Any]:
    return _envelope(
        result_type=result_type,
        status="pending_review",
        data=data,
        warnings=[warning],
    )


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


def _audit_log(
    *,
    actor_user_id: str,
    action: str,
    target_id: str,
    status: str,
) -> AuditLog:
    payload = {
        "actor_user_id": actor_user_id,
        "action": action,
        "target_id": target_id,
        "status": status,
        "timestamp": now_iso(),
    }
    return AuditLog(
        audit_log_id=f"audit_{sha256_json(payload)[-24:]}",
        actor_user_id=actor_user_id,
        action=action,
        target_type="semantic_gateway",
        target_id=target_id,
        session_id="semantic_gateway_session",
        timestamp=payload["timestamp"],
        status=status,
    )
