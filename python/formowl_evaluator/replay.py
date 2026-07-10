from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import uuid
from typing import Any, Callable, Mapping, Sequence

from formowl_contract import ContractValidationError, sha256_json
from formowl_gateway import (
    SemanticGatewaySession,
    SemanticMcpGateway,
    SemanticMcpJsonRpcGateway,
)
from formowl_ingestion.storage import AssetStore, ObservationStore, UploadSessionStore
from formowl_mail import MailEvidenceBundle, build_mail_evidence_bundle
from formowl_mail.query import build_mail_evidence_query_handler


@dataclass(frozen=True)
class ReplayCase:
    case_fingerprint: str
    requester_user_id: str
    query_text: str
    result_kind: str
    limit: int

    @classmethod
    def from_private_manifest_row(cls, row: Mapping[str, Any]) -> ReplayCase:
        result_kind = _required_string(row, "result_kind")
        if result_kind not in {"owner_match", "no_match", "permission_denied"}:
            raise ContractValidationError("unsupported replay result_kind")
        limit = row.get("limit")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ContractValidationError("replay limit must be between 1 and 100")
        return cls(
            case_fingerprint=_required_string(row, "private_fingerprint"),
            requester_user_id=_required_string(row, "requester_user_id"),
            query_text=_required_string(row, "query_text"),
            result_kind=result_kind,
            limit=limit,
        )


@dataclass(frozen=True)
class ReplayArtifact:
    unique_evidence_case_count: int
    tools_list_response: dict[str, Any]
    tools_list_response_hash: str
    public_rows: tuple[dict[str, Any], ...]
    private_rows: tuple[dict[str, Any], ...]
    public_rows_root_hash: str
    private_rows_root_hash: str
    attestation_hash: str

    @property
    def tools_list_schema_hash(self) -> str:
        return self.tools_list_response_hash

    def public_binding(self) -> dict[str, Any]:
        return {
            "unique_evidence_case_count": self.unique_evidence_case_count,
            "tools_list_response_hash": self.tools_list_response_hash,
            "public_rows_root_hash": self.public_rows_root_hash,
            "private_rows_root_hash": self.private_rows_root_hash,
            "attestation_hash": self.attestation_hash,
        }

    def to_private_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": "mail_evidence_jsonrpc_replay_private",
            "artifact_version": 2,
            "unique_evidence_case_count": self.unique_evidence_case_count,
            "tools_list_response": self.tools_list_response,
            "tools_list_response_hash": self.tools_list_response_hash,
            "public_rows": list(self.public_rows),
            "private_rows": list(self.private_rows),
            "public_rows_root_hash": self.public_rows_root_hash,
            "private_rows_root_hash": self.private_rows_root_hash,
            "attestation_hash": self.attestation_hash,
        }

    @classmethod
    def from_private_dict(cls, payload: Mapping[str, Any]) -> ReplayArtifact:
        if payload.get("artifact_type") != "mail_evidence_jsonrpc_replay_private":
            raise ContractValidationError("replay artifact type mismatch")
        if payload.get("artifact_version") != 2:
            raise ContractValidationError("replay artifact version mismatch")
        artifact = cls(
            unique_evidence_case_count=_required_integer(payload, "unique_evidence_case_count"),
            tools_list_response=dict(_required_mapping(payload, "tools_list_response")),
            tools_list_response_hash=_required_string(payload, "tools_list_response_hash"),
            public_rows=tuple(_mapping_list(payload, "public_rows")),
            private_rows=tuple(_mapping_list(payload, "private_rows")),
            public_rows_root_hash=_required_string(payload, "public_rows_root_hash"),
            private_rows_root_hash=_required_string(payload, "private_rows_root_hash"),
            attestation_hash=_required_string(payload, "attestation_hash"),
        )
        validate_replay_artifact(artifact)
        return artifact


def rebuild_may_mail_evidence_bundle(
    corpus_root: Path,
    private_manifest: Mapping[str, Any],
) -> MailEvidenceBundle:
    data_dir = corpus_root / "data"
    assets = AssetStore(data_dir).list()
    upload_sessions = UploadSessionStore(data_dir).list()
    observations = ObservationStore(data_dir).list()
    if len(assets) != 1 or len(upload_sessions) != 1 or not observations:
        raise ContractValidationError("MAY corpus ingestion records are incomplete")
    asset = assets[0]
    upload_session = upload_sessions[0]
    archive_sha256 = _required_string(private_manifest, "archive_sha256")
    bundle = build_mail_evidence_bundle(
        observations,
        workspace_id=asset.workspace_id,
        owner_user_id=asset.owner_user_id,
        source_asset_id=asset.asset_id,
        archive_sha256=archive_sha256,
        parser_version=_required_string(private_manifest, "parser_version"),
        upload_session_id=upload_session.upload_session_id,
        created_at=upload_session.created_at,
        started_at=upload_session.created_at,
        completed_at=upload_session.completed_at or upload_session.created_at,
    )
    expected_session_id = _required_string(private_manifest, "mail_import_session_id")
    expected_bundle_id = _required_string(private_manifest, "mail_evidence_bundle_id")
    if bundle.mail_import_session.mail_import_session_id != expected_session_id:
        raise ContractValidationError("rebuilt MAY mail import session binding mismatch")
    if bundle.mail_evidence_bundle_id != expected_bundle_id:
        raise ContractValidationError("rebuilt MAY evidence bundle binding mismatch")
    return bundle


def load_or_rebuild_may_mail_evidence_bundle(
    corpus_root: Path,
    private_manifest: Mapping[str, Any],
    *,
    cache_path: Path | None = None,
) -> MailEvidenceBundle:
    if cache_path is not None and cache_path.exists():
        if cache_path.is_symlink() or not cache_path.is_file():
            raise ContractValidationError("MAY bundle cache path is unsafe")
        bundle = MailEvidenceBundle.from_dict(json.loads(cache_path.read_text(encoding="utf-8")))
        _validate_bundle_manifest_binding(bundle, private_manifest)
        return bundle
    bundle = rebuild_may_mail_evidence_bundle(corpus_root, private_manifest)
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if cache_path.parent.is_symlink() or cache_path.is_symlink():
            raise ContractValidationError("MAY bundle cache path is unsafe")
        os.chmod(cache_path.parent, 0o700)
        temporary = cache_path.with_name(f".{cache_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                os.chmod(temporary, 0o600)
                json.dump(
                    bundle.to_dict(),
                    handle,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, cache_path)
            os.chmod(cache_path, 0o600)
        finally:
            temporary.unlink(missing_ok=True)
    return bundle


def load_replay_artifact(
    path: Path,
    *,
    trust_anchor_path: Path | None = None,
    expected_attestation_hash: str | None = None,
) -> ReplayArtifact:
    if path.is_symlink() or not path.is_file():
        raise ContractValidationError("replay artifact path is unsafe")
    artifact = ReplayArtifact.from_private_dict(json.loads(path.read_text(encoding="utf-8")))
    anchored_hash = expected_attestation_hash
    if anchored_hash is None:
        anchor_path = trust_anchor_path or _default_trust_anchor_path(path)
        anchored_hash = _load_replay_trust_anchor(anchor_path)
    validate_replay_artifact(artifact, expected_attestation_hash=anchored_hash)
    return artifact


def load_replay_artifact_for_repair(path: Path) -> Mapping[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ContractValidationError("replay artifact path is unsafe")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ContractValidationError("repair replay artifact is invalid")
    if payload.get("artifact_type") != "mail_evidence_jsonrpc_replay_private":
        raise ContractValidationError("repair replay artifact type mismatch")
    _mapping_list(payload, "public_rows")
    _mapping_list(payload, "private_rows")
    return payload


def write_replay_artifact(
    path: Path,
    artifact: ReplayArtifact,
    *,
    trust_anchor_path: Path | None = None,
) -> Path:
    validate_replay_artifact(artifact)
    anchor_path = trust_anchor_path or _default_trust_anchor_path(path)
    _validate_private_output_path(path)
    _validate_private_output_path(anchor_path)
    _write_private_json_atomic(path, artifact.to_private_dict())
    _write_private_json_atomic(
        anchor_path,
        {
            "artifact_type": "mail_evidence_jsonrpc_replay_trust_anchor",
            "artifact_version": 1,
            "attestation_hash": artifact.attestation_hash,
        },
    )
    return anchor_path


def replay_attestation_hash(artifact: ReplayArtifact) -> str:
    return sha256_json(_attestation_payload(artifact))


def execute_mail_evidence_replays(
    bundle: MailEvidenceBundle,
    cases: Sequence[ReplayCase],
    *,
    now: str,
    session_id: str = "session_chatgpt_mcp_offline_eval",
    stateful_follow_up_case_fingerprints: set[str] | None = None,
) -> ReplayArtifact:
    semantic_gateway = SemanticMcpGateway(
        mail_evidence_handler=build_mail_evidence_query_handler([bundle], now=now)
    )
    gateways: dict[str, SemanticMcpJsonRpcGateway] = {}

    def gateway_for(requester_user_id: str) -> SemanticMcpJsonRpcGateway:
        gateway = gateways.get(requester_user_id)
        if gateway is None:
            gateway = SemanticMcpJsonRpcGateway(
                semantic_gateway=semantic_gateway,
                session=SemanticGatewaySession(
                    session_id=session_id,
                    actor_user_id=requester_user_id,
                    workspace_id=bundle.mail_import_session.workspace_id,
                ),
            )
            gateways[requester_user_id] = gateway
        return gateway

    return execute_jsonrpc_replays(
        cases,
        gateway_for=gateway_for,
        mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
        stateful_follow_up_case_fingerprints=stateful_follow_up_case_fingerprints,
    )


def repair_mail_evidence_replays(
    existing_artifact: ReplayArtifact | Mapping[str, Any],
    bundle: MailEvidenceBundle,
    cases: Sequence[ReplayCase],
    *,
    now: str,
    session_id: str = "session_chatgpt_mcp_offline_eval",
    stateful_follow_up_case_fingerprints: set[str] | None = None,
) -> tuple[ReplayArtifact, dict[str, int]]:
    semantic_gateway = SemanticMcpGateway(
        mail_evidence_handler=build_mail_evidence_query_handler([bundle], now=now)
    )
    gateways: dict[str, SemanticMcpJsonRpcGateway] = {}

    def gateway_for(requester_user_id: str) -> SemanticMcpJsonRpcGateway:
        gateway = gateways.get(requester_user_id)
        if gateway is None:
            gateway = SemanticMcpJsonRpcGateway(
                semantic_gateway=semantic_gateway,
                session=SemanticGatewaySession(
                    session_id=session_id,
                    actor_user_id=requester_user_id,
                    workspace_id=bundle.mail_import_session.workspace_id,
                ),
            )
            gateways[requester_user_id] = gateway
        return gateway

    return repair_jsonrpc_replays(
        existing_artifact,
        cases,
        gateway_for=gateway_for,
        mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
        stateful_follow_up_case_fingerprints=stateful_follow_up_case_fingerprints,
    )


def execute_jsonrpc_replays(
    cases: Sequence[ReplayCase],
    *,
    gateway_for: Callable[[str], SemanticMcpJsonRpcGateway],
    mail_import_session_id: str,
    stateful_follow_up_case_fingerprints: set[str] | None = None,
) -> ReplayArtifact:
    if not cases:
        raise ContractValidationError("replay cases must not be empty")
    first_gateway = gateway_for(cases[0].requester_user_id)
    tools_list_response = first_gateway.handle_json_rpc(
        {"jsonrpc": "2.0", "id": "tools_list", "method": "tools/list"}
    )
    _validate_tools_list_response(tools_list_response)
    tools_list_response_hash = sha256_json(tools_list_response)
    selected_follow_ups = stateful_follow_up_case_fingerprints or set()
    rows = [
        _execute_case_rows(
            case,
            ordinal=ordinal,
            gateway=gateway_for(case.requester_user_id),
            mail_import_session_id=mail_import_session_id,
            tools_list_response_hash=tools_list_response_hash,
            execute_follow_up=case.case_fingerprint in selected_follow_ups,
        )
        for ordinal, case in enumerate(cases)
    ]
    artifact = _assemble_replay_artifact(tools_list_response, rows)
    validate_replay_artifact(artifact)
    return artifact


def repair_jsonrpc_replays(
    existing_artifact: ReplayArtifact | Mapping[str, Any],
    cases: Sequence[ReplayCase],
    *,
    gateway_for: Callable[[str], SemanticMcpJsonRpcGateway],
    mail_import_session_id: str,
    stateful_follow_up_case_fingerprints: set[str] | None = None,
) -> tuple[ReplayArtifact, dict[str, int]]:
    if not cases:
        raise ContractValidationError("replay cases must not be empty")
    tools_list_response = gateway_for(cases[0].requester_user_id).handle_json_rpc(
        {"jsonrpc": "2.0", "id": "tools_list", "method": "tools/list"}
    )
    _validate_tools_list_response(tools_list_response)
    tools_list_response_hash = sha256_json(tools_list_response)
    selected_follow_ups = stateful_follow_up_case_fingerprints or set()
    source_public_rows, source_private_rows = _repair_source_rows(existing_artifact)
    existing_public = {
        row.get("case_fingerprint"): row
        for row in source_public_rows
        if isinstance(row.get("case_fingerprint"), str)
    }
    existing_private = {
        row.get("case_fingerprint"): row
        for row in source_private_rows
        if isinstance(row.get("case_fingerprint"), str)
    }
    rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    reused = 0
    reexecuted = 0
    for ordinal, case in enumerate(cases):
        public_row = existing_public.get(case.case_fingerprint)
        private_row = existing_private.get(case.case_fingerprint)
        execute_follow_up = case.case_fingerprint in selected_follow_ups
        reusable_steps = _reusable_replay_steps(
            public_row,
            private_row,
            case=case,
            ordinal=ordinal,
            mail_import_session_id=mail_import_session_id,
            execute_follow_up=execute_follow_up,
        )
        if reusable_steps is not None:
            rows.append(
                _rows_from_steps(
                    case,
                    reusable_steps,
                    tools_list_response_hash=tools_list_response_hash,
                )
            )
            reused += 1
        else:
            rows.append(
                _execute_case_rows(
                    case,
                    ordinal=ordinal,
                    gateway=gateway_for(case.requester_user_id),
                    mail_import_session_id=mail_import_session_id,
                    tools_list_response_hash=tools_list_response_hash,
                    execute_follow_up=execute_follow_up,
                )
            )
            reexecuted += 1
    artifact = _assemble_replay_artifact(tools_list_response, rows)
    validate_replay_artifact(artifact)
    return artifact, {"reused_case_count": reused, "reexecuted_case_count": reexecuted}


def _execute_case_rows(
    case: ReplayCase,
    *,
    ordinal: int,
    gateway: SemanticMcpJsonRpcGateway,
    mail_import_session_id: str,
    tools_list_response_hash: str,
    execute_follow_up: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    request = _case_request(case, ordinal=ordinal, mail_import_session_id=mail_import_session_id)
    response = gateway.handle_json_rpc(request)
    first_step = _replay_step(request, response, expected_result_kind=case.result_kind)
    steps = [first_step]
    if execute_follow_up:
        follow_up_request, follow_up_style = _derive_follow_up_request(
            case,
            first_step,
            mail_import_session_id=mail_import_session_id,
            ordinal=ordinal,
        )
        follow_up_response = gateway.handle_json_rpc(follow_up_request)
        steps.append(
            _replay_step(
                follow_up_request,
                follow_up_response,
                expected_result_kind=_classify_replay_response(follow_up_response),
                follow_up_style=follow_up_style,
            )
        )
    return _rows_from_steps(case, steps, tools_list_response_hash=tools_list_response_hash)


def _case_request(
    case: ReplayCase,
    *,
    ordinal: int,
    mail_import_session_id: str,
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": f"replay_{ordinal:04d}",
        "method": "tools/call",
        "params": {
            "name": "query_mail_evidence",
            "arguments": {
                "query_text": case.query_text,
                "mail_import_session_id": mail_import_session_id,
                "limit": case.limit,
            },
        },
    }


def _rows_from_steps(
    case: ReplayCase,
    steps: Sequence[Mapping[str, Any]],
    *,
    tools_list_response_hash: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    first_step = steps[0]
    trajectory_root_hash = sha256_json([step["step_hash"] for step in steps])
    public_row = {
        "case_fingerprint": case.case_fingerprint,
        "result_kind": case.result_kind,
        "expected_result_kind": case.result_kind,
        "semantic_kind": first_step["semantic_kind"],
        "result_kind_match": first_step["result_kind_match"],
        "request_hash": first_step["request_hash"],
        "response_hash": first_step["response_hash"],
        "response_status": first_step["response_status"],
        "is_error": first_step["is_error"],
        "evidence_count": first_step["evidence_count"],
        "citation_count": first_step["citation_count"],
        "tools_list_response_hash": tools_list_response_hash,
        "step_count": len(steps),
        "trajectory_root_hash": trajectory_root_hash,
        "follow_up_style": steps[1].get("follow_up_style") if len(steps) > 1 else None,
        "follow_up_response_status": (steps[1]["response_status"] if len(steps) > 1 else None),
    }
    public_row["row_hash"] = sha256_json(public_row)
    private_row = {
        "case_fingerprint": case.case_fingerprint,
        "request": first_step["request"],
        "response": first_step["response"],
        "request_hash": first_step["request_hash"],
        "response_hash": first_step["response_hash"],
        "steps": [dict(step) for step in steps],
        "trajectory_root_hash": trajectory_root_hash,
        "public_row_hash": public_row["row_hash"],
    }
    private_row["private_row_hash"] = sha256_json(private_row)
    return public_row, private_row


def _assemble_replay_artifact(
    tools_list_response: Mapping[str, Any],
    rows: Sequence[tuple[dict[str, Any], dict[str, Any]]],
) -> ReplayArtifact:
    public_rows = tuple(row[0] for row in rows)
    private_rows = tuple(row[1] for row in rows)
    provisional = ReplayArtifact(
        unique_evidence_case_count=len(rows),
        tools_list_response=dict(tools_list_response),
        tools_list_response_hash=sha256_json(tools_list_response),
        public_rows=public_rows,
        private_rows=private_rows,
        public_rows_root_hash=sha256_json([row["row_hash"] for row in public_rows]),
        private_rows_root_hash=sha256_json([row["private_row_hash"] for row in private_rows]),
        attestation_hash="sha256:" + "0" * 64,
    )
    return replace(provisional, attestation_hash=replay_attestation_hash(provisional))


def _repair_source_rows(
    existing_artifact: ReplayArtifact | Mapping[str, Any],
) -> tuple[Sequence[Mapping[str, Any]], Sequence[Mapping[str, Any]]]:
    if isinstance(existing_artifact, ReplayArtifact):
        return existing_artifact.public_rows, existing_artifact.private_rows
    return (
        _mapping_list(existing_artifact, "public_rows"),
        _mapping_list(existing_artifact, "private_rows"),
    )


def _reusable_replay_steps(
    public_row: Any,
    private_row: Any,
    *,
    case: ReplayCase,
    ordinal: int,
    mail_import_session_id: str,
    execute_follow_up: bool,
) -> list[dict[str, Any]] | None:
    if not isinstance(public_row, Mapping) or not isinstance(private_row, Mapping):
        return None
    try:
        expected_request = _case_request(
            case,
            ordinal=ordinal,
            mail_import_session_id=mail_import_session_id,
        )
        if private_row.get("case_fingerprint") != case.case_fingerprint:
            return None
        if public_row.get("case_fingerprint") != case.case_fingerprint:
            return None
        if public_row.get("result_kind") != case.result_kind:
            return None
        if private_row.get("request") != expected_request:
            return None
        if sha256_json(expected_request) != private_row.get("request_hash"):
            return None
        response = _required_mapping(private_row, "response")
        if sha256_json(response) != private_row.get("response_hash"):
            return None
        session = _required_mapping(_required_mapping(response, "result"), "session")
        if session.get("actor_user_id") != case.requester_user_id:
            return None
        steps = private_row.get("steps")
        if steps is None:
            steps = [
                _replay_step(expected_request, response, expected_result_kind=case.result_kind)
            ]
        if not isinstance(steps, list) or len(steps) != (2 if execute_follow_up else 1):
            return None
        for step in steps:
            _validate_replay_step(step)
        if "private_row_hash" in private_row:
            expected_trajectory_root = sha256_json([step["step_hash"] for step in steps])
            if private_row.get("trajectory_root_hash") != expected_trajectory_root:
                return None
            without_private_hash = {
                key: value for key, value in private_row.items() if key != "private_row_hash"
            }
            if sha256_json(without_private_hash) != private_row.get("private_row_hash"):
                return None
        if steps[0].get("expected_result_kind") != case.result_kind:
            return None
        if steps[0].get("result_kind_match") is not (
            steps[0].get("semantic_kind") == case.result_kind
        ):
            return None
        if execute_follow_up:
            expected_follow_up, expected_style = _derive_follow_up_request(
                case,
                steps[0],
                mail_import_session_id=mail_import_session_id,
                ordinal=ordinal,
            )
            if steps[1].get("request") != expected_follow_up:
                return None
            if steps[1].get("follow_up_style") != expected_style:
                return None
        without_public_hash = {key: value for key, value in public_row.items() if key != "row_hash"}
        if sha256_json(without_public_hash) != public_row.get("row_hash"):
            return None
        if private_row.get("public_row_hash") != public_row.get("row_hash"):
            return None
        if public_row.get("request_hash") != private_row.get("request_hash"):
            return None
        if public_row.get("response_hash") != private_row.get("response_hash"):
            return None
        return [dict(step) for step in steps]
    except (ContractValidationError, KeyError, TypeError):
        return None


def validate_replay_artifact(
    artifact: ReplayArtifact,
    *,
    expected_attestation_hash: str | None = None,
) -> None:
    _validate_tools_list_response(artifact.tools_list_response)
    if sha256_json(artifact.tools_list_response) != artifact.tools_list_response_hash:
        raise ContractValidationError("complete tools/list response binding mismatch")
    if artifact.unique_evidence_case_count != len(artifact.public_rows):
        raise ContractValidationError("replay public row count mismatch")
    if len(artifact.private_rows) != len(artifact.public_rows):
        raise ContractValidationError("replay private row count mismatch")
    public_by_hash = {row.get("row_hash"): row for row in artifact.public_rows}
    if len(public_by_hash) != len(artifact.public_rows):
        raise ContractValidationError("replay public row hashes must be unique")
    for private_row in artifact.private_rows:
        request = private_row.get("request")
        response = private_row.get("response")
        if not isinstance(request, Mapping) or not isinstance(response, Mapping):
            raise ContractValidationError("replay private row is incomplete")
        if sha256_json(request) != private_row.get("request_hash"):
            raise ContractValidationError("replay request binding mismatch")
        if sha256_json(response) != private_row.get("response_hash"):
            raise ContractValidationError("replay response binding mismatch")
        steps = private_row.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ContractValidationError("replay trajectory steps are missing")
        for step in steps:
            _validate_replay_step(step)
        expected_trajectory_root = sha256_json([step["step_hash"] for step in steps])
        if expected_trajectory_root != private_row.get("trajectory_root_hash"):
            raise ContractValidationError("replay trajectory root binding mismatch")
        without_private_hash = {
            key: value for key, value in private_row.items() if key != "private_row_hash"
        }
        if sha256_json(without_private_hash) != private_row.get("private_row_hash"):
            raise ContractValidationError("replay private row hash mismatch")
        public_row = public_by_hash.get(private_row.get("public_row_hash"))
        if public_row is None:
            raise ContractValidationError("replay public/private row binding mismatch")
        if public_row.get("request_hash") != private_row.get("request_hash"):
            raise ContractValidationError("replay public request binding mismatch")
        if public_row.get("response_hash") != private_row.get("response_hash"):
            raise ContractValidationError("replay public response binding mismatch")
        if public_row.get("trajectory_root_hash") != private_row.get("trajectory_root_hash"):
            raise ContractValidationError("replay public trajectory binding mismatch")
        if public_row.get("tools_list_response_hash") != artifact.tools_list_response_hash:
            raise ContractValidationError("replay public tools/list binding mismatch")
        if public_row.get("step_count") != len(steps):
            raise ContractValidationError("replay public step count mismatch")
        first_step = steps[0]
        expected_result_kind = first_step.get("expected_result_kind")
        semantic_kind = first_step.get("semantic_kind")
        result_kind_match = first_step.get("result_kind_match")
        if public_row.get("result_kind") != expected_result_kind:
            raise ContractValidationError("replay public expected result binding mismatch")
        if public_row.get("expected_result_kind") != expected_result_kind:
            raise ContractValidationError("replay public expected result summary mismatch")
        if public_row.get("semantic_kind") != semantic_kind:
            raise ContractValidationError("replay public actual result summary mismatch")
        if public_row.get("result_kind_match") is not result_kind_match:
            raise ContractValidationError("replay public result match summary mismatch")
        if expected_result_kind == "permission_denied" and semantic_kind != "permission_denied":
            raise ContractValidationError("expected permission denial was not enforced")
        for key in ("response_status", "is_error", "evidence_count", "citation_count"):
            if public_row.get(key) != first_step.get(key):
                raise ContractValidationError("replay public semantic summary mismatch")
        without_hash = {key: value for key, value in public_row.items() if key != "row_hash"}
        if sha256_json(without_hash) != public_row.get("row_hash"):
            raise ContractValidationError("replay public row hash mismatch")
    expected_root = sha256_json([row["row_hash"] for row in artifact.public_rows])
    if expected_root != artifact.public_rows_root_hash:
        raise ContractValidationError("replay public root binding mismatch")
    expected_private_root = sha256_json([row["private_row_hash"] for row in artifact.private_rows])
    if expected_private_root != artifact.private_rows_root_hash:
        raise ContractValidationError("replay private root binding mismatch")
    computed_attestation_hash = replay_attestation_hash(artifact)
    if computed_attestation_hash != artifact.attestation_hash:
        raise ContractValidationError("replay attestation binding mismatch")
    if (
        expected_attestation_hash is not None
        and expected_attestation_hash != artifact.attestation_hash
    ):
        raise ContractValidationError("replay external trust anchor mismatch")


def _tool_input_schema(response: Mapping[str, Any], tool_name: str) -> Mapping[str, Any]:
    result = response.get("result")
    tools = result.get("tools") if isinstance(result, Mapping) else None
    if not isinstance(tools, list):
        raise ContractValidationError("tools/list response is invalid")
    for tool in tools:
        if isinstance(tool, Mapping) and tool.get("name") == tool_name:
            schema = tool.get("inputSchema")
            if isinstance(schema, Mapping):
                return schema
    raise ContractValidationError("query_mail_evidence schema is missing")


def _validate_tools_list_response(response: Mapping[str, Any]) -> None:
    if response.get("jsonrpc") != "2.0" or "error" in response:
        raise ContractValidationError("tools/list response is an error")
    schema = _tool_input_schema(response, "query_mail_evidence")
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise ContractValidationError("query_mail_evidence schema is not closed")
    required = schema.get("required")
    if not isinstance(required, list) or "query_text" not in required:
        raise ContractValidationError("query_mail_evidence schema required fields are incomplete")
    any_of = schema.get("anyOf")
    selectors = (
        {
            tuple(item.get("required", ()))
            for item in any_of
            if isinstance(item, Mapping) and isinstance(item.get("required"), list)
        }
        if isinstance(any_of, list)
        else set()
    )
    if selectors != {("mail_import_session_id",), ("mail_evidence_bundle_id",)}:
        raise ContractValidationError("query_mail_evidence selector schema is incomplete")


def _tool_payload(response: Mapping[str, Any]) -> Mapping[str, Any]:
    result = response.get("result")
    content = result.get("content") if isinstance(result, Mapping) else None
    if not isinstance(content, list) or not content:
        raise ContractValidationError("tools/call response content is missing")
    first = content[0]
    payload = first.get("json") if isinstance(first, Mapping) else None
    if not isinstance(payload, Mapping):
        raise ContractValidationError("tools/call response payload is invalid")
    return payload


def _replay_step(
    request: Mapping[str, Any],
    response: Mapping[str, Any],
    *,
    expected_result_kind: str,
    follow_up_style: str | None = None,
) -> dict[str, Any]:
    payload = _tool_payload(response)
    semantic_kind = _classify_replay_response(response)
    data = payload.get("data") if isinstance(payload.get("data"), Mapping) else {}
    evidence = data.get("evidence_snippets") if isinstance(data, Mapping) else []
    citations = data.get("citations") if isinstance(data, Mapping) else []
    if not isinstance(evidence, list) or not isinstance(citations, list):
        raise ContractValidationError("replay evidence/citation payload must be lists")
    if expected_result_kind not in {"owner_match", "no_match", "permission_denied"}:
        raise ContractValidationError("unsupported expected replay result_kind")
    step = {
        "request": dict(request),
        "response": dict(response),
        "request_hash": sha256_json(request),
        "response_hash": sha256_json(response),
        "response_status": payload.get("status"),
        "is_error": bool(response.get("result", {}).get("isError", False)),
        "evidence_count": len(evidence),
        "citation_count": len(citations),
        "expected_result_kind": expected_result_kind,
        "semantic_kind": semantic_kind,
        "result_kind_match": semantic_kind == expected_result_kind,
        "follow_up_style": follow_up_style,
    }
    step["step_hash"] = sha256_json(step)
    return step


def _validate_replay_step(step: Any) -> None:
    if not isinstance(step, Mapping):
        raise ContractValidationError("replay trajectory step is invalid")
    request = step.get("request")
    response = step.get("response")
    if not isinstance(request, Mapping) or not isinstance(response, Mapping):
        raise ContractValidationError("replay trajectory step is incomplete")
    if sha256_json(request) != step.get("request_hash"):
        raise ContractValidationError("replay step request binding mismatch")
    if sha256_json(response) != step.get("response_hash"):
        raise ContractValidationError("replay step response binding mismatch")
    semantic_kind = _classify_replay_response(response)
    if semantic_kind != step.get("semantic_kind"):
        raise ContractValidationError("replay step semantic classification mismatch")
    expected_result_kind = step.get("expected_result_kind")
    if expected_result_kind not in {"owner_match", "no_match", "permission_denied"}:
        raise ContractValidationError("replay step expected result kind is invalid")
    if step.get("result_kind_match") is not (semantic_kind == expected_result_kind):
        raise ContractValidationError("replay step result match binding mismatch")
    payload = _tool_payload(response)
    data = payload.get("data") if isinstance(payload.get("data"), Mapping) else {}
    evidence = data.get("evidence_snippets") if isinstance(data, Mapping) else []
    citations = data.get("citations") if isinstance(data, Mapping) else []
    if step.get("response_status") != payload.get("status"):
        raise ContractValidationError("replay step status summary mismatch")
    if step.get("is_error") is not False:
        raise ContractValidationError("production replay artifacts must not contain errors")
    if step.get("evidence_count") != len(evidence) or step.get("citation_count") != len(citations):
        raise ContractValidationError("replay step count summary mismatch")
    without_hash = {key: value for key, value in step.items() if key != "step_hash"}
    if sha256_json(without_hash) != step.get("step_hash"):
        raise ContractValidationError("replay step hash mismatch")


def _classify_replay_response(response: Mapping[str, Any]) -> str:
    if "error" in response:
        raise ContractValidationError("production replay contains JSON-RPC error")
    result = response.get("result")
    if not isinstance(result, Mapping):
        raise ContractValidationError("production replay contains MCP tool error")
    if result.get("isError") is not False:
        payload = _tool_payload(response)
        data = payload.get("data") if isinstance(payload.get("data"), Mapping) else {}
        error_code = data.get("error_code") if isinstance(data, Mapping) else None
        safe_code = (
            error_code
            if error_code in {"unsafe_tool_payload", "tool_execution_failed"}
            else "unknown_tool_error"
        )
        raise ContractValidationError(f"production replay contains MCP tool error: {safe_code}")
    payload = _tool_payload(response)
    if payload.get("result_type") != "mail_evidence_query":
        raise ContractValidationError("replay response result type mismatch")
    status = payload.get("status")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise ContractValidationError("replay response data is missing")
    evidence = data.get("evidence_snippets")
    citations = data.get("citations")
    warnings = data.get("warnings", payload.get("warnings", []))
    redactions = data.get("redaction_counts")
    if not isinstance(evidence, list) or not isinstance(citations, list):
        raise ContractValidationError("replay response evidence/citations are invalid")
    if not isinstance(warnings, list) or not isinstance(redactions, Mapping):
        raise ContractValidationError("replay response safety metadata is invalid")
    if status == "permission_denied":
        if evidence or citations:
            raise ContractValidationError("permission-denied replay exposed evidence")
        hidden_bundles = redactions.get("hidden_bundles")
        hidden_messages = redactions.get("hidden_messages")
        if (
            not isinstance(hidden_bundles, int)
            or not isinstance(hidden_messages, int)
            or hidden_bundles < 1
            or hidden_messages < 1
            or "mail_evidence_permission_denied" not in warnings
        ):
            raise ContractValidationError("permission-denied replay lacks redaction semantics")
        return "permission_denied"
    if status != "ok":
        raise ContractValidationError("production replay response status is unsupported")
    if evidence:
        if not citations:
            raise ContractValidationError("owner-match replay lacks citations")
        return "owner_match"
    if citations or "no_visible_mail_evidence_matched" not in warnings:
        raise ContractValidationError("visible zero-match replay semantics are invalid")
    hidden_bundles = redactions.get("hidden_bundles")
    hidden_messages = redactions.get("hidden_messages")
    if hidden_bundles != 0 or hidden_messages != 0:
        raise ContractValidationError("visible zero-match replay must not report hidden evidence")
    return "no_match"


def _derive_follow_up_request(
    case: ReplayCase,
    first_step: Mapping[str, Any],
    *,
    mail_import_session_id: str,
    ordinal: int,
) -> tuple[dict[str, Any], str]:
    response = _required_mapping(first_step, "response")
    payload = _tool_payload(response)
    data = _required_mapping(payload, "data")
    evidence = data.get("evidence_snippets")
    if not isinstance(evidence, list):
        raise ContractValidationError("follow-up evidence payload is invalid")
    semantic_kind = _required_string(first_step, "semantic_kind")
    if semantic_kind == "owner_match":
        first_evidence = evidence[0] if evidence and isinstance(evidence[0], Mapping) else {}
        subject = first_evidence.get("subject") if isinstance(first_evidence, Mapping) else None
        evidence_seed = (
            subject.strip() if isinstance(subject, str) and subject.strip() else case.query_text
        )
        query_text = f"{evidence_seed} deadline blocker owner next action"
        limit = min(100, max(1, min(case.limit, len(evidence) + 2)))
        style = "evidence_refinement"
    elif semantic_kind == "no_match":
        query_tokens = case.query_text.split()
        query_text = " ".join(query_tokens[:-1]) if len(query_tokens) > 1 else case.query_text
        limit = min(100, max(case.limit + 1, case.limit * 2))
        style = "zero_match_broadening"
    else:
        query_text = f"{case.query_text} permission-safe retry"
        limit = 1
        style = "permission_safe_retry"
    return (
        {
            "jsonrpc": "2.0",
            "id": f"replay_{ordinal:04d}_follow_up",
            "method": "tools/call",
            "params": {
                "name": "query_mail_evidence",
                "arguments": {
                    "query_text": query_text,
                    "mail_import_session_id": mail_import_session_id,
                    "limit": limit,
                },
            },
        },
        style,
    )


def _attestation_payload(artifact: ReplayArtifact) -> dict[str, Any]:
    return {
        "artifact_type": "mail_evidence_jsonrpc_replay_attestation",
        "artifact_version": 1,
        "unique_evidence_case_count": artifact.unique_evidence_case_count,
        "tools_list_response_hash": artifact.tools_list_response_hash,
        "public_rows_root_hash": artifact.public_rows_root_hash,
        "private_rows_root_hash": artifact.private_rows_root_hash,
    }


def _default_trust_anchor_path(path: Path) -> Path:
    return path.with_name(path.name + ".trust-anchor.json")


def _load_replay_trust_anchor(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ContractValidationError("replay trust anchor path is unsafe")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ContractValidationError("replay trust anchor is invalid")
    if payload.get("artifact_type") != "mail_evidence_jsonrpc_replay_trust_anchor":
        raise ContractValidationError("replay trust anchor type mismatch")
    return _required_string(payload, "attestation_hash")


def _write_private_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    _validate_private_output_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            os.chmod(temporary, 0o600)
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_private_output_path(path: Path) -> None:
    if path.is_symlink() or (path.parent.exists() and path.parent.is_symlink()):
        raise ContractValidationError("private replay path is unsafe")


def _required_string(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ContractValidationError(f"{key} must be a non-empty string")
    return item


def _required_integer(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise ContractValidationError(f"{key} must be a non-negative integer")
    return item


def _mapping_list(value: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    item = value.get(key)
    if not isinstance(item, list) or not all(isinstance(row, Mapping) for row in item):
        raise ContractValidationError(f"{key} must be a list of objects")
    return item


def _required_mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    item = value.get(key)
    if not isinstance(item, Mapping):
        raise ContractValidationError(f"{key} must be an object")
    return item


def _validate_bundle_manifest_binding(
    bundle: MailEvidenceBundle,
    private_manifest: Mapping[str, Any],
) -> None:
    if bundle.mail_import_session.mail_import_session_id != _required_string(
        private_manifest, "mail_import_session_id"
    ):
        raise ContractValidationError("cached MAY mail import session binding mismatch")
    if bundle.mail_evidence_bundle_id != _required_string(
        private_manifest, "mail_evidence_bundle_id"
    ):
        raise ContractValidationError("cached MAY evidence bundle binding mismatch")
