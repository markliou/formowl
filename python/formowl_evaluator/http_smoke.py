from __future__ import annotations

from dataclasses import dataclass
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
from typing import Any, Callable, Sequence

from formowl_contract import sha256_json
from formowl_mail import (
    MailUploadHttpSurfaceConfig,
    create_mail_upload_http_surface_server,
)


@dataclass(frozen=True)
class OpenedUploadSession:
    upload_session_id: str | None
    responses: list[dict[str, Any]]
    tool_names: set[str]
    persisted_count: int
    persisted_session: Any
    run: subprocess.CompletedProcess[str]


class RunningMailUploadHttpSurface:
    def __init__(self, config: MailUploadHttpSurfaceConfig) -> None:
        self.server = create_mail_upload_http_surface_server("127.0.0.1", 0, config)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> RunningMailUploadHttpSurface:
        self.thread.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[Any, bytes]:
        connection = http.client.HTTPConnection(
            self.server.server_address[0],
            self.server.server_address[1],
            timeout=5,
        )
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response, response.read()
        finally:
            connection.close()


def build_mail_upload_http_config(
    work_dir: Path,
    stores: dict[str, Any],
    *,
    storage_backend_id: str,
    actor_user_id: str,
    session_id: str,
    workspace_id: str,
    received_at: str,
    max_request_bytes: int = 1024 * 1024,
) -> MailUploadHttpSurfaceConfig:
    return MailUploadHttpSurfaceConfig(
        upload_session_store=stores["upload_session_store"],
        object_store=stores["object_store"],
        asset_store=stores["asset_store"],
        audit_store=stores["audit_store"],
        storage_backend_id=storage_backend_id,
        actor_user_id=actor_user_id,
        session_id=session_id,
        workspace_id=workspace_id,
        staging_dir=work_dir / "staging",
        received_at=received_at,
        max_request_bytes=max_request_bytes,
    )


def build_multipart_mail_archive(
    fields: Sequence[tuple[str, str]] | dict[str, str],
    *,
    files: Sequence[tuple[str, bytes]],
    file_content_type: str,
) -> tuple[bytes, str]:
    boundary = "----FormOwlMailUploadHttpBoundary"
    field_pairs = list(fields.items()) if isinstance(fields, dict) else list(fields)
    parts: list[bytes] = []
    for key, value in field_pairs:
        parts.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("ascii"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    for filename, content in files:
        parts.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                (
                    f'Content-Disposition: form-data; name="mail_archive"; '
                    f'filename="{filename}"\r\n'
                ).encode("ascii"),
                f"Content-Type: {file_content_type}\r\n\r\n".encode("ascii"),
                content,
                b"\r\n",
            ]
        )
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def run_gateway_command(
    requests: list[dict[str, Any]],
    *,
    command: Sequence[str] | None,
    default_command: Sequence[str],
    root: Path,
    python_root: Path,
    data_dir: Path,
    session_id: str,
    actor_user_id: str,
    workspace_id: str,
    expires_at: str,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(python_root)
    env["FORMOWL_DATA_DIR"] = str(data_dir)
    env["FORMOWL_MCP_SESSION_ID"] = session_id
    env["FORMOWL_MCP_ACTOR_USER_ID"] = actor_user_id
    env["FORMOWL_MCP_WORKSPACE_ID"] = workspace_id
    env["FORMOWL_MAIL_UPLOAD_EXPIRES_AT"] = expires_at
    input_text = "".join(json.dumps(request, sort_keys=True) + "\n" for request in requests)
    argv = resolve_command_argv(command or default_command, default_command=default_command)
    try:
        return subprocess.run(
            argv,
            input=input_text,
            text=True,
            capture_output=True,
            cwd=root,
            env=env,
            check=False,
        )
    except OSError:
        return subprocess.CompletedProcess(argv, 127, "", "command_start_failed")


def open_upload_session_via_command(
    data_dir: Path,
    *,
    command: Sequence[str] | None,
    default_command: Sequence[str],
    root: Path,
    python_root: Path,
    session_id: str,
    actor_user_id: str,
    workspace_id: str,
    project_id: str,
    expires_at: str,
    upload_session_store_factory: Callable[[Path], Any],
) -> OpenedUploadSession:
    requests = [
        {"jsonrpc": "2.0", "id": "initialize", "method": "initialize"},
        {"jsonrpc": "2.0", "id": "tools", "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": "open_upload_session",
            "method": "tools/call",
            "params": {
                "name": "open_upload_session",
                "arguments": {
                    "intent": "Upload PST for FormOwl mail evidence reading.",
                    "intended_asset_type": "pst",
                    "owner_scope_type": "project",
                    "owner_scope_id": project_id,
                    "project_id": project_id,
                },
            },
        },
    ]
    run = run_gateway_command(
        requests,
        command=command,
        default_command=default_command,
        root=root,
        python_root=python_root,
        data_dir=data_dir,
        session_id=session_id,
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
        expires_at=expires_at,
    )
    responses = decode_json_lines(run.stdout)
    tools_response = response_by_id(responses, "tools")
    tool_names = {
        tool["name"]
        for tool in tools_response.get("result", {}).get("tools", [])
        if isinstance(tool, dict)
    }
    upload_payload = tool_payload(response_by_id(responses, "open_upload_session"))
    upload_session_id = dict_or_empty(upload_payload.get("data")).get("upload_session_id")
    sessions = upload_session_store_factory(data_dir).list()
    return OpenedUploadSession(
        upload_session_id=upload_session_id if isinstance(upload_session_id, str) else None,
        responses=responses,
        tool_names=tool_names,
        persisted_count=len(sessions),
        persisted_session=sessions[0] if len(sessions) == 1 else None,
        run=run,
    )


def resolve_command_argv(
    command: Sequence[str],
    *,
    default_command: Sequence[str],
) -> list[str]:
    argv = list(command)
    if not argv:
        return list(default_command)
    executable = argv[0]
    if Path(executable).name != executable:
        return argv
    resolved = shutil.which(executable)
    if resolved is not None:
        argv[0] = resolved
    return argv


def decode_json_lines(value: str) -> list[dict[str, Any]]:
    responses: list[dict[str, Any]] = []
    for line in value.splitlines():
        if not line.strip():
            continue
        decoded = json.loads(line)
        if not isinstance(decoded, dict):
            raise ValueError("gateway response line must be a JSON object")
        responses.append(decoded)
    return responses


def decode_json_object(value: bytes) -> dict[str, Any]:
    decoded = json.loads(value.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("HTTP response body must be a JSON object")
    return decoded


def response_by_id(responses: list[dict[str, Any]], request_id: str) -> dict[str, Any]:
    for response in responses:
        if response.get("id") == request_id:
            return response
    return {}


def tool_payload(response: dict[str, Any]) -> dict[str, Any]:
    content = response.get("result", {}).get("content")
    if not isinstance(content, list) or not content:
        return {}
    first = content[0]
    if not isinstance(first, dict):
        return {}
    payload = first.get("json")
    return payload if isinstance(payload, dict) else {}


def jsonrpc_response_hash(response: dict[str, Any]) -> str:
    normalized: dict[str, Any] = {"jsonrpc": response.get("jsonrpc"), "id": response.get("id")}
    if "error" in response:
        error = dict_or_empty(response.get("error"))
        normalized["error"] = {"code": error.get("code"), "message": error.get("message")}
    result = dict_or_empty(response.get("result"))
    if result:
        normalized["result"] = {
            "protocolVersion": result.get("protocolVersion"),
            "isError": result.get("isError"),
        }
        tools = result.get("tools")
        if isinstance(tools, list):
            normalized["result"]["tool_names"] = sorted(
                tool.get("name") for tool in tools if isinstance(tool, dict)
            )
        payload = tool_payload(response)
        if payload:
            data = dict_or_empty(payload.get("data"))
            task_card = dict_or_empty(data.get("upload_task_card"))
            normalized["result"]["tool_payload"] = {
                "result_type": payload.get("result_type"),
                "status": payload.get("status"),
                "data_status": data.get("status"),
                "task_card_type": task_card.get("card_type"),
                "validation_passed": dict_or_empty(data.get("validation")).get("passed"),
            }
    return sha256_json(normalized)


def upload_session_shape_hash(
    value: Any,
    *,
    session_id: str,
    project_id: str,
    include_job_binding: bool,
) -> str:
    if value is None:
        return sha256_json("")
    normalized = {
        "actor_user_id": value.actor_user_id,
        "workspace_id": value.workspace_id,
        "owner_scope_type": value.owner_scope_type,
        "owner_scope_id": value.owner_scope_id,
        "intended_asset_type": value.intended_asset_type,
        "ingestion_profile": value.ingestion_profile,
        "visibility_scope": value.visibility_scope,
        "source_preparation_state": value.source_preparation_state,
        "processing_status": value.processing_status,
        "status": value.status,
        "session_bound": value.session_id == session_id,
        "asset_bound": isinstance(value.asset_id, str),
        "project_bound": value.project_id == project_id,
    }
    if include_job_binding:
        normalized["job_bound"] = isinstance(value.ingestion_job_id, str)
    return sha256_json(normalized)


def asset_shape_hash(asset: Any, upload_session: Any) -> str:
    if asset is None or upload_session is None:
        return sha256_json("")
    source_ref = dict_or_empty(asset.source_ref)
    return sha256_json(
        {
            "workspace_id": asset.workspace_id,
            "owner_user_id": asset.owner_user_id,
            "mime_type": asset.mime_type,
            "content_hash": asset.content_hash,
            "file_size": asset.file_size,
            "project_id": asset.project_id,
            "source_ref_bound_to_upload_session": source_ref.get("source_id")
            == upload_session.upload_session_id,
        }
    )


def dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def validate_hash_list(
    value: Any,
    *,
    expected_count: int,
    context: str,
    blockers: list[str],
) -> None:
    if not isinstance(value, list) or len(value) != expected_count:
        blockers.append(f"{context} must contain {expected_count} hashes")
        return
    sha256_re = re.compile(r"^sha256:[0-9a-f]{64}$")
    if not all(isinstance(item, str) and sha256_re.fullmatch(item) for item in value):
        blockers.append(f"{context} must contain sha256 hashes")
    if len(set(value)) != len(value):
        blockers.append(f"{context} must contain distinct hashes")


def validate_exact_keys(
    value: dict[str, Any],
    expected_keys: set[str],
    context: str,
    blockers: list[str],
    *,
    allowed_extra: set[str] | None = None,
) -> None:
    extra = sorted(set(value) - expected_keys - (allowed_extra or set()))
    missing = sorted(expected_keys - set(value))
    if extra:
        blockers.append(unknown_keys_message(context, extra))
    if missing:
        blockers.append(f"{context} missing keys: " + sha256_json(missing))


def unknown_keys_message(context: str, keys: Sequence[str]) -> str:
    return f"{context} contains unknown keys: count={len(keys)} hash={sha256_json(list(keys))}"


def validate_claim_boundary(
    claim_boundary: dict[str, Any],
    *,
    expected_claims: dict[str, bool],
    forbidden_true_claims: Sequence[str],
    blockers: list[str],
) -> None:
    validate_exact_keys(claim_boundary, set(expected_claims), "claim_boundary", blockers)
    for key, expected in expected_claims.items():
        if claim_boundary.get(key) is not expected:
            blockers.append(f"claim boundary mismatch: {key}")
    for claim in forbidden_true_claims:
        if claim_boundary.get(claim) is not False:
            blockers.append(f"forbidden claim is not explicitly false: {claim}")


def validate_embedded_validation(
    value: Any,
    *,
    expected_claims: dict[str, bool],
    claim_error_messages: dict[str, str],
    blockers: list[str],
) -> None:
    if not isinstance(value, dict):
        blockers.append("validation must be an object")
        return
    validate_exact_keys(value, {"passed", "blockers", "claim_boundary"}, "validation", blockers)
    if value.get("passed") is not True:
        blockers.append("validation.passed must be true")
    if value.get("blockers") != []:
        blockers.append("validation.blockers must be empty")
    claim_boundary = dict_or_empty(value.get("claim_boundary"))
    validate_exact_keys(
        claim_boundary,
        set(expected_claims),
        "validation.claim_boundary",
        blockers,
    )
    for key, expected in expected_claims.items():
        if claim_boundary.get(key) is not expected:
            blockers.append(claim_error_messages[key])


def reject_body_or_evidence_text_fields(
    value: Any,
    blockers: list[str],
    path: str = "",
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            normalized = re.sub(r"[^a-z0-9]+", "_", key_text.lower()).strip("_")
            if {"body", "snippet", "content", "text"} & set(normalized.split("_")):
                blockers.append("public report contains evidence text field: " + sha256_json(path))
                return
            reject_body_or_evidence_text_fields(
                item,
                blockers,
                f"{path}.{key_text}" if path else key_text,
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_body_or_evidence_text_fields(item, blockers, f"{path}[{index}]")
