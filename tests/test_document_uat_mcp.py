from __future__ import annotations

import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

import _paths  # noqa: F401


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_DIRECT_SCRIPT = _REPOSITORY_ROOT / "python" / "formowl_mail" / "document_uat_mcp.py"
_FORBIDDEN_DOCUMENT_KEYS = {
    "answer",
    "answer_items",
    "complete_projection",
    "final_answer",
    "kg",
    "oracle",
    "path",
}


def _write_snapshot(
    root: Path,
    *,
    status_value: str = "Complete",
) -> tuple[Path, str]:
    snapshot_path = root / "authorized-existing-export.json"
    payload = {
        "artifact_type": "formowl_diagnostic_current_export_table_snapshot_v2",
        "schema_version": 2,
        "record_count": 1,
        "source": {
            "workspace_id": "workspace_document_uat",
            "owner_user_id": "user_document_uat",
        },
        "records": [
            {
                "structural_observation": {
                    "columns": [
                        {"column_ordinal": 0, "original_header": "Task"},
                        {"column_ordinal": 1, "original_header": "Status"},
                    ],
                    "rows": [
                        {
                            "row_ordinal": 0,
                            "cells": [
                                {
                                    "column_ordinal": 0,
                                    "cell_state": "populated",
                                    "value": "Synthetic acceptance task",
                                },
                                {
                                    "column_ordinal": 1,
                                    "cell_state": "populated",
                                    "value": status_value,
                                },
                            ],
                        }
                    ],
                }
            }
        ],
    }
    snapshot_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    expected_sha256 = "sha256:" + hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    return snapshot_path, expected_sha256


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _module_environment() -> dict[str, str]:
    environment = dict(os.environ)
    python_paths = [
        str(_REPOSITORY_ROOT / "python"),
        str(_REPOSITORY_ROOT / "tests"),
    ]
    if environment.get("PYTHONPATH"):
        python_paths.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(python_paths)
    return environment


def _request_json(
    port: int,
    method: str,
    route: str,
    payload: dict[str, object] | None = None,
) -> tuple[int, dict[str, object]]:
    body = None
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request(method, route, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read().decode("utf-8"))
    finally:
        connection.close()


def _all_mapping_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = {key for key in value if isinstance(key, str)}
        for item in value.values():
            keys.update(_all_mapping_keys(item))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for item in value:
            keys.update(_all_mapping_keys(item))
        return keys
    return set()


class DocumentUatMcpCliTests(unittest.TestCase):
    def test_cli_serves_health_and_exactly_one_read_only_document_tool(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot_path, expected_sha256 = _write_snapshot(Path(directory))
            port = _unused_local_port()
            command = [
                sys.executable,
                "-m",
                "formowl_mail.document_uat_mcp",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--snapshot",
                str(snapshot_path),
                "--expected-sha256",
                expected_sha256,
                "--workspace-id",
                "workspace_document_uat",
                "--actor-user-id",
                "user_document_uat",
                "--session-id",
                "session_document_uat",
            ]
            process = subprocess.Popen(
                command,
                cwd=_REPOSITORY_ROOT,
                env=_module_environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                health: dict[str, object] | None = None
                for _attempt in range(50):
                    if process.poll() is not None:
                        stdout, stderr = process.communicate()
                        self.fail(f"document MCP exited early: stdout={stdout!r} stderr={stderr!r}")
                    try:
                        status, candidate = _request_json(port, "GET", "/health")
                    except (ConnectionError, OSError):
                        time.sleep(0.05)
                        continue
                    self.assertEqual(status, 200)
                    health = candidate
                    break
                self.assertIsNotNone(health, "document MCP health did not become ready")
                assert health is not None
                self.assertEqual(
                    set(health),
                    {
                        "status",
                        "snapshot_sha256",
                        "authorization_binding_sha256",
                        "table_count",
                        "tool_count",
                        "successful_mcp_call_count",
                    },
                )
                self.assertEqual(health["status"], "ok")
                self.assertEqual(health["snapshot_sha256"], expected_sha256)
                self.assertEqual(health["table_count"], 1)
                self.assertEqual(health["tool_count"], 1)
                self.assertEqual(health["successful_mcp_call_count"], 0)

                status, tool_list = _request_json(
                    port,
                    "POST",
                    "/mcp",
                    {
                        "jsonrpc": "2.0",
                        "id": "list-tools",
                        "method": "tools/list",
                        "params": {},
                    },
                )
                self.assertEqual(status, 200)
                self.assertEqual(
                    [tool["name"] for tool in tool_list["result"]["tools"]],
                    ["read_authorized_documents"],
                )

                status, tool_response = _request_json(
                    port,
                    "POST",
                    "/mcp",
                    {
                        "jsonrpc": "2.0",
                        "id": "read-once",
                        "method": "tools/call",
                        "params": {
                            "name": "read_authorized_documents",
                            "arguments": {
                                "query_text": "Synthetic acceptance task status",
                                "required_terms": ["Synthetic acceptance task"],
                                "limit": 5,
                            },
                        },
                    },
                )
                self.assertEqual(status, 200)
                structured = tool_response["result"]["structuredContent"]
                self.assertEqual(structured["status"], "ok")
                self.assertEqual(structured["result_count"], 1)
                self.assertIn("Synthetic acceptance task", structured["results"][0]["content"])
                self.assertTrue(
                    _FORBIDDEN_DOCUMENT_KEYS.isdisjoint(_all_mapping_keys(tool_response))
                )

                status, final_health = _request_json(port, "GET", "/health")
                self.assertEqual(status, 200)
                self.assertEqual(final_health["successful_mcp_call_count"], 1)
            finally:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=5)

    def test_direct_file_cli_serves_health_and_one_document_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot_path, expected_sha256 = _write_snapshot(Path(directory))
            port = _unused_local_port()
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(_DIRECT_SCRIPT),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--snapshot",
                    str(snapshot_path),
                    "--expected-sha256",
                    expected_sha256,
                    "--workspace-id",
                    "workspace_document_uat",
                    "--actor-user-id",
                    "user_document_uat",
                    "--session-id",
                    "session_document_uat_direct",
                ],
                cwd=_REPOSITORY_ROOT,
                env=_module_environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                health: dict[str, object] | None = None
                for _attempt in range(50):
                    if process.poll() is not None:
                        stdout, stderr = process.communicate()
                        self.fail(
                            "direct document MCP exited early: "
                            f"stdout={stdout!r} stderr={stderr!r}"
                        )
                    try:
                        status, candidate = _request_json(port, "GET", "/health")
                    except (ConnectionError, OSError):
                        time.sleep(0.05)
                        continue
                    self.assertEqual(status, 200)
                    health = candidate
                    break
                self.assertIsNotNone(health, "direct document MCP health did not become ready")
                assert health is not None
                self.assertEqual(health["status"], "ok")
                self.assertEqual(health["snapshot_sha256"], expected_sha256)
                self.assertEqual(health["successful_mcp_call_count"], 0)

                status, tool_response = _request_json(
                    port,
                    "POST",
                    "/mcp",
                    {
                        "jsonrpc": "2.0",
                        "id": "direct-read-once",
                        "method": "tools/call",
                        "params": {
                            "name": "read_authorized_documents",
                            "arguments": {
                                "query_text": "Synthetic acceptance task status",
                                "required_terms": ["Synthetic acceptance task"],
                                "limit": 5,
                            },
                        },
                    },
                )
                self.assertEqual(status, 200)
                structured = tool_response["result"]["structuredContent"]
                self.assertEqual(structured["status"], "ok")
                self.assertEqual(structured["result_count"], 1)
                self.assertIn(
                    "Synthetic acceptance task",
                    structured["results"][0]["content"],
                )
                self.assertTrue(
                    _FORBIDDEN_DOCUMENT_KEYS.isdisjoint(_all_mapping_keys(tool_response))
                )

                status, final_health = _request_json(port, "GET", "/health")
                self.assertEqual(status, 200)
                self.assertEqual(final_health["successful_mcp_call_count"], 1)
            finally:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=5)

    def test_direct_file_cli_wrong_snapshot_hash_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot_path, _expected_sha256 = _write_snapshot(Path(directory))
            result = subprocess.run(
                [
                    sys.executable,
                    str(_DIRECT_SCRIPT),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "0",
                    "--snapshot",
                    str(snapshot_path),
                    "--expected-sha256",
                    "sha256:" + ("0" * 64),
                    "--workspace-id",
                    "workspace_document_uat",
                    "--actor-user-id",
                    "user_document_uat",
                    "--session-id",
                    "session_document_uat_direct",
                ],
                cwd=_REPOSITORY_ROOT,
                env=_module_environment(),
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(
            result.stderr.strip(),
            "document UAT MCP startup validation failed",
        )
        self.assertEqual(result.stdout, "")
        self.assertNotIn(str(snapshot_path), result.stderr)

    def test_cli_wrong_snapshot_hash_fails_closed_before_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot_path, _expected_sha256 = _write_snapshot(Path(directory))
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "formowl_mail.document_uat_mcp",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "0",
                    "--snapshot",
                    str(snapshot_path),
                    "--expected-sha256",
                    "sha256:" + ("0" * 64),
                    "--workspace-id",
                    "workspace_document_uat",
                    "--actor-user-id",
                    "user_document_uat",
                    "--session-id",
                    "session_document_uat",
                ],
                cwd=_REPOSITORY_ROOT,
                env=_module_environment(),
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(
            result.stderr.strip(),
            "document UAT MCP startup validation failed",
        )
        self.assertEqual(result.stdout, "")
        self.assertNotIn(str(snapshot_path), result.stderr)

    def test_cli_mismatched_snapshot_authorization_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot_path, expected_sha256 = _write_snapshot(Path(directory))
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "formowl_mail.document_uat_mcp",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "0",
                    "--snapshot",
                    str(snapshot_path),
                    "--expected-sha256",
                    expected_sha256,
                    "--workspace-id",
                    "workspace_not_authorized",
                    "--actor-user-id",
                    "user_document_uat",
                    "--session-id",
                    "session_document_uat",
                ],
                cwd=_REPOSITORY_ROOT,
                env=_module_environment(),
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(
            result.stderr.strip(),
            "document UAT MCP startup validation failed",
        )
        self.assertEqual(result.stdout, "")
        self.assertNotIn(str(snapshot_path), result.stderr)


if __name__ == "__main__":
    unittest.main()
