"""Bounded Issue #56 continuation and real MCP-response harness helpers."""

from __future__ import annotations

import hashlib
import json
import argparse
import os
from pathlib import Path
import tempfile
from collections.abc import Mapping
from typing import Any

from formowl_contract import ContractValidationError

MAX_BOUNDED_CANDIDATES = 128


def write_bounded_metadata(metadata_path: Path, metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Publish one bounded metadata object with an atomic same-directory replace."""
    if not isinstance(metadata, Mapping):
        raise ContractValidationError("bounded metadata must be an object")
    encoded = json.dumps(
        dict(metadata), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{metadata_path.name}.", dir=metadata_path.parent
    )
    temporary = Path(temporary_name)
    os.fchmod(descriptor, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, metadata_path)
    finally:
        temporary.unlink(missing_ok=True)
    loaded = json.loads(metadata_path.read_bytes())
    if not isinstance(loaded, dict) or loaded != dict(metadata):
        raise ContractValidationError("bounded metadata is not one JSON object")
    return loaded


def bounded_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-candidates",
        required=True,
        type=int,
        help="required positive candidate bound for this bounded run",
    )
    return parser


def parse_bounded_args(argv: list[str] | None = None) -> argparse.Namespace:
    args = bounded_argument_parser().parse_args(argv)
    if not 1 <= args.max_candidates <= MAX_BOUNDED_CANDIDATES:
        raise ContractValidationError("bounded candidate limit is invalid")
    return args


def _workspace_path(workspace_root: Path, relative_path: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ContractValidationError("workspace relative path is invalid")
    relative = Path(relative_path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ContractValidationError("workspace relative path is unsafe")
    root = workspace_root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ContractValidationError("workspace path escapes root") from exc
    return path


def bounded_reference_prefix(references: Any, max_candidates: int) -> Any:
    if (
        isinstance(max_candidates, bool)
        or not isinstance(max_candidates, int)
        or not 1 <= max_candidates <= MAX_BOUNDED_CANDIDATES
    ):
        raise ContractValidationError("bounded candidate limit is invalid")
    if not hasattr(references, "__getitem__"):
        raise ContractValidationError("prepared references must be sliceable")
    return references[:max_candidates]


def bounded_revision_id(base_revision_id: str, candidate_limit: int) -> str:
    if (
        not isinstance(base_revision_id, str)
        or not base_revision_id
        or "/" in base_revision_id
        or "\\" in base_revision_id
        or not isinstance(candidate_limit, int)
        or isinstance(candidate_limit, bool)
        or not 1 <= candidate_limit <= MAX_BOUNDED_CANDIDATES
    ):
        raise ValueError("bounded revision identity is invalid")
    return f"{base_revision_id}.bounded-{candidate_limit}"


def load_bounded_metadata(
    metadata_path: Path,
    *,
    expected_path: Path,
    workspace_root: Path,
    candidate_limit: int,
) -> dict[str, Any]:
    if metadata_path.resolve() != expected_path.resolve():
        raise ContractValidationError("bounded metadata path mismatch")
    if (
        isinstance(candidate_limit, bool)
        or not isinstance(candidate_limit, int)
        or not 1 <= candidate_limit <= MAX_BOUNDED_CANDIDATES
    ):
        raise ValueError("bounded candidate limit is invalid")
    try:
        metadata = json.loads(metadata_path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractValidationError("bounded metadata is unreadable") from exc
    if not isinstance(metadata, dict):
        raise ContractValidationError("bounded metadata must be an object")
    if metadata.get("bounded_canary_candidate_count") != candidate_limit:
        raise ContractValidationError("bounded metadata limit mismatch")
    if not isinstance(metadata.get("binding"), dict):
        raise ContractValidationError("bounded source binding is missing")
    checkpoint = metadata.get("candidate_checkpoint")
    if (
        not isinstance(checkpoint, dict)
        or not isinstance(checkpoint.get("revision_id"), str)
        or not checkpoint["revision_id"]
    ):
        raise ContractValidationError("bounded checkpoint binding is missing")
    code_hashes = metadata.get("code_hashes")
    if not isinstance(code_hashes, dict) or not code_hashes:
        raise ContractValidationError("bounded metadata code hashes are missing")
    for relative_path, expected_hash in code_hashes.items():
        if not isinstance(relative_path, str) or not isinstance(expected_hash, str):
            raise ContractValidationError("bounded metadata code hash is invalid")
        path = _workspace_path(workspace_root, relative_path)
        if not path.is_file():
            raise ContractValidationError(
                f"bounded code hash path is not a regular file: {relative_path}"
            )
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            raise ContractValidationError(
                f"bounded code hash mismatch: {relative_path}"
            )
    return metadata


def validate_bounded_revision_report(
    report: Mapping[str, Any],
    *,
    revision_id: str,
    candidate_limit: int,
    workspace_root: Path,
) -> None:
    if (
        isinstance(candidate_limit, bool)
        or not isinstance(candidate_limit, int)
        or not 1 <= candidate_limit <= MAX_BOUNDED_CANDIDATES
    ):
        raise ContractValidationError("bounded candidate limit is invalid")
    if report.get("phase") != "staged_not_activated":
        raise ContractValidationError("bounded revision was not staged")
    if report.get("bounded_canary_candidate_count") != candidate_limit:
        raise ContractValidationError("bounded revision limit is missing")
    if report.get("revision_id") != revision_id:
        raise ContractValidationError("bounded report revision id is missing or mismatched")
    revision_path = report.get("revision_path")
    path = _workspace_path(workspace_root, revision_path)
    if not path.is_file():
        raise ContractValidationError("bounded report revision path is not a file")
    try:
        revision = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractValidationError("bounded report revision path is unreadable") from exc
    if not isinstance(revision, dict) or revision.get("revision_id") != revision_id:
        raise ContractValidationError("bounded report revision path does not match revision")
    if report.get("source_observation_count", 0) <= 0:
        raise ContractValidationError("bounded revision source binding is missing")


def extract_mcp_citation_response(response: Any) -> dict[str, Any]:
    actual_status = response.status_code
    if actual_status != 200:
        raise ContractValidationError(
            f"MCP query HTTP status was {actual_status}"
        )
    try:
        envelope = response.json()
    except ValueError as exc:
        raise ContractValidationError("MCP response was not JSON") from exc
    result = envelope.get("result") if isinstance(envelope, dict) else None
    if not isinstance(result, dict):
        raise ContractValidationError("MCP result envelope is missing")
    tool_is_error = result.get("isError", False)
    if not isinstance(tool_is_error, bool):
        raise ContractValidationError("MCP isError is invalid")
    if tool_is_error:
        raise ContractValidationError("MCP tool response reported an error")
    structured = result.get("structuredContent")
    data = structured.get("data") if isinstance(structured, dict) else None
    answer = data.get("answer") if isinstance(data, dict) else None
    citation_count = answer.get("citation_count") if isinstance(answer, dict) else None
    if not isinstance(citation_count, int) or citation_count < 0:
        raise ContractValidationError("MCP citation count is missing")
    return {
        "http_status": actual_status,
        "tool_is_error": tool_is_error,
        "citation_count": citation_count,
    }


def execute_mcp_citation_request(client: Any, prompt: str) -> dict[str, Any]:
    from formowl_gateway.issue56_diagnostic import (
        mcp_headers,
        mcp_initialize_request,
        mcp_query_request,
    )

    initialize = client.post(
        "/mcp",
        headers=mcp_headers(),
        json=mcp_initialize_request(),
    )
    if initialize.status_code != 200:
        raise ContractValidationError(
            f"MCP initialize HTTP status was {initialize.status_code}"
        )
    response = client.post(
        "/mcp",
        headers=mcp_headers(),
        json=mcp_query_request(prompt),
    )
    return extract_mcp_citation_response(response)
