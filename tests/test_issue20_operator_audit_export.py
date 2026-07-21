from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import _paths  # noqa: F401

import formowl_gateway.runtime as runtime_module
from formowl_auth.postgres import PostgreSQLOAuthRepository
from formowl_evidence import issue20_packet as packet_module
from formowl_gateway import container_entrypoint
from formowl_gateway.runtime import (
    ConnectedRuntime,
    ConnectedRuntimeError,
    main,
)


_WORKSPACE_ID = "workspace_issue20"
_CLIENT_ID = "chatgpt_closed_beta"
_OPERATOR_ID = "operator_issue20"
_OWNER_ID = "user_owner"
_MEMBER_ID = "user_member"
_OWNER_IDENTITY_ID = "extid_owner"
_MEMBER_IDENTITY_ID = "extid_member"


class _UnitOfWork:
    def __init__(self, *, fail_commit: bool = False) -> None:
        self.fail_commit = fail_commit
        self.committed = False
        self.rolled_back = False

    def __enter__(self) -> "_UnitOfWork":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if exc_type is not None or not self.committed:
            self.rolled_back = True
        return False

    def commit(self) -> None:
        if self.fail_commit:
            raise RuntimeError("private commit detail")
        self.committed = True


class _AuditRepository:
    def __init__(
        self,
        rows: list[dict[str, object]],
        *,
        read_error: Exception | None = None,
        fail_commit: bool = False,
    ) -> None:
        self.rows = rows
        self.read_error = read_error
        self.fail_commit = fail_commit
        self.transactions: list[_UnitOfWork] = []
        self.query_calls = 0

    def transaction(self) -> _UnitOfWork:
        unit = _UnitOfWork(fail_commit=self.fail_commit)
        self.transactions.append(unit)
        return unit

    def list_issue20_live_audit_rows(self, **_kwargs: object) -> list[dict[str, object]]:
        self.query_calls += 1
        if self.read_error is not None:
            raise self.read_error
        return [dict(row) for row in self.rows]

    def close(self) -> None:
        return None


def _runtime(repository: _AuditRepository) -> ConnectedRuntime:
    config = SimpleNamespace(
        oauth=SimpleNamespace(
            chatgpt_client_id=_CLIENT_ID,
            chatgpt_callback_mode="production_exact",
        ),
        owner_bootstrap_operator_service_id=_OPERATOR_ID,
    )
    return ConnectedRuntime(
        config=config,
        repository=repository,
        http_client=object(),
        google_client=object(),
        bridge=object(),
        application=object(),
    )


def _timestamp(index: int) -> str:
    return (datetime(2026, 7, 20, tzinfo=timezone.utc) + timedelta(seconds=index)).isoformat()


def _audit_row(
    audit_index: int,
    timestamp_index: int,
    *,
    action: str,
    target_type: str,
    target_id: str,
    session_id: str,
    status: str,
    reason_code: str,
    metadata: dict[str, object],
    actor_type: str = "user",
    actor_user_id: str | None = None,
    actor_service_id: str | None = None,
    workspace_id: str | None = None,
    external_identity_id: str | None = None,
    oauth_client_id: str | None = None,
    oauth_token_session_id: str | None = None,
    request_id: str | None = None,
    tool_call_id: str | None = None,
) -> dict[str, object]:
    return {
        "audit_log_id": f"audit_{audit_index:03d}",
        "actor_user_id": actor_user_id,
        "actor_service_id": actor_service_id,
        "actor_type": actor_type,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "session_id": session_id,
        "workspace_id": workspace_id,
        "status": status,
        "external_identity_id": external_identity_id,
        "oauth_client_id": oauth_client_id,
        "oauth_token_session_id": oauth_token_session_id,
        "request_id": request_id,
        "tool_call_id": tool_call_id,
        "reason_code": reason_code,
        "metadata": metadata,
        "timestamp": _timestamp(timestamp_index),
    }


def _authorization_start(audit_index: int, timestamp_index: int, transaction_id: str):
    return _audit_row(
        audit_index,
        timestamp_index,
        action="oauth_authorization_started",
        target_type="oauth_transaction",
        target_id=transaction_id,
        session_id=transaction_id,
        status="ok",
        reason_code="authorization_started",
        actor_type="external_unauthenticated",
        oauth_client_id=_CLIENT_ID,
        metadata={
            "event_stage": "authorization",
            "provider": "google",
            "scopes": ["formowl.use"],
        },
    )


def _initial_callback_rows(
    audit_index: int,
    timestamp_index: int,
    *,
    transaction_id: str,
    user_id: str,
    identity_id: str,
    invitation_id: str,
    role: str,
) -> list[dict[str, object]]:
    common = {
        "actor_user_id": user_id,
        "workspace_id": _WORKSPACE_ID,
        "external_identity_id": identity_id,
        "oauth_client_id": _CLIENT_ID,
    }
    return [
        _audit_row(
            audit_index,
            timestamp_index,
            action="oauth_external_identity_created",
            target_type="external_identity",
            target_id=identity_id,
            session_id=transaction_id,
            status="ok",
            reason_code="external_identity_created",
            metadata={"event_stage": "identity_mapping", "identity_status": "created"},
            **common,
        ),
        _audit_row(
            audit_index + 1,
            timestamp_index,
            action="oauth_invitation_accepted",
            target_type="oauth_invitation",
            target_id=invitation_id,
            session_id=transaction_id,
            status="ok",
            reason_code="invitation_accepted",
            metadata={
                "event_stage": "first_login",
                "provider": "google",
                "membership_role": role,
            },
            **common,
        ),
        _audit_row(
            audit_index + 2,
            timestamp_index,
            action="google_authentication_succeeded",
            target_type="external_identity",
            target_id=identity_id,
            session_id=transaction_id,
            status="ok",
            reason_code="google_authentication_succeeded",
            metadata={"event_stage": "google_callback", "provider": "google"},
            **common,
        ),
        _audit_row(
            audit_index + 3,
            timestamp_index,
            action="oauth_authorization_code_issued",
            target_type="oauth_authorization_code",
            target_id=transaction_id,
            session_id=transaction_id,
            status="ok",
            reason_code="authorization_code_issued",
            metadata={"event_stage": "google_callback", "provider": "google"},
            **common,
        ),
    ]


def _relink_callback_rows(
    audit_index: int,
    timestamp_index: int,
    *,
    transaction_id: str,
) -> list[dict[str, object]]:
    common = {
        "actor_user_id": _MEMBER_ID,
        "workspace_id": _WORKSPACE_ID,
        "external_identity_id": _MEMBER_IDENTITY_ID,
        "oauth_client_id": _CLIENT_ID,
    }
    return [
        _audit_row(
            audit_index,
            timestamp_index,
            action="oauth_external_identity_resolved",
            target_type="external_identity",
            target_id=_MEMBER_IDENTITY_ID,
            session_id=transaction_id,
            status="ok",
            reason_code="external_identity_resolved",
            metadata={"event_stage": "identity_mapping", "identity_status": "resolved"},
            **common,
        ),
        _audit_row(
            audit_index + 1,
            timestamp_index,
            action="google_authentication_succeeded",
            target_type="external_identity",
            target_id=_MEMBER_IDENTITY_ID,
            session_id=transaction_id,
            status="ok",
            reason_code="google_authentication_succeeded",
            metadata={"event_stage": "google_callback", "provider": "google"},
            **common,
        ),
        _audit_row(
            audit_index + 2,
            timestamp_index,
            action="oauth_authorization_code_issued",
            target_type="oauth_authorization_code",
            target_id=transaction_id,
            session_id=transaction_id,
            status="ok",
            reason_code="authorization_code_issued",
            metadata={"event_stage": "google_callback", "provider": "google"},
            **common,
        ),
    ]


def _token_row(
    audit_index: int,
    timestamp_index: int,
    *,
    user_id: str,
    identity_id: str,
    token_session_id: str,
    role: str,
) -> dict[str, object]:
    return _audit_row(
        audit_index,
        timestamp_index,
        action="oauth_token_session_issued",
        target_type="oauth_token_session",
        target_id=token_session_id,
        session_id=token_session_id,
        status="ok",
        reason_code="token_session_issued",
        actor_user_id=user_id,
        workspace_id=_WORKSPACE_ID,
        external_identity_id=identity_id,
        oauth_client_id=_CLIENT_ID,
        oauth_token_session_id=token_session_id,
        metadata={
            "event_stage": "token_exchange",
            "scopes": ["formowl.use"],
            "membership_role": role,
        },
    )


def _tool_row(
    audit_index: int,
    timestamp_index: int,
    *,
    user_id: str,
    identity_id: str,
    token_session_id: str,
    tool_name: str,
    allowed: bool,
) -> dict[str, object]:
    return _audit_row(
        audit_index,
        timestamp_index,
        action="mcp_authorization_allowed" if allowed else "mcp_authorization_denied",
        target_type="mcp_tool",
        target_id=tool_name,
        session_id=token_session_id,
        status="ok" if allowed else "permission_denied",
        reason_code="tool_authorized" if allowed else "invalid_tool_arguments",
        actor_user_id=user_id,
        workspace_id=_WORKSPACE_ID,
        external_identity_id=identity_id,
        oauth_client_id=_CLIENT_ID,
        oauth_token_session_id=token_session_id,
        request_id=f"request_{audit_index:03d}",
        tool_call_id=f"toolcall_{audit_index:03d}",
        metadata={
            "event_stage": "mcp_authorization",
            "workspace_decision": "allowed" if allowed else "denied",
        },
    )


def _http_denial(
    audit_index: int,
    timestamp_index: int,
    *,
    token_session_id: str,
    reason_code: str,
) -> dict[str, object]:
    return _audit_row(
        audit_index,
        timestamp_index,
        action="mcp_http_authentication_denied",
        target_type="mcp_resource",
        target_id="mcp",
        session_id=token_session_id,
        status="permission_denied",
        reason_code=reason_code,
        actor_user_id=_MEMBER_ID,
        workspace_id=_WORKSPACE_ID,
        external_identity_id=_MEMBER_IDENTITY_ID,
        oauth_client_id=_CLIENT_ID,
        oauth_token_session_id=token_session_id,
        request_id=f"http_request_{audit_index:03d}",
        metadata={
            "event_stage": "mcp_http_authentication",
            "lineage_source": "verified_token_session",
        },
    )


def _issue20_rows(*, include_post_restore_old_denial: bool = True):
    rows: list[dict[str, object]] = []
    audit_index = 1

    def add(row: dict[str, object]) -> None:
        nonlocal audit_index
        rows.append(row)
        audit_index += 1

    owner_invitation_id = "invite_owner"
    member_invitation_id = "invite_member"
    member_target = f"{_WORKSPACE_ID}:{_MEMBER_ID}"
    add(
        _audit_row(
            audit_index,
            1,
            action="oauth_owner_bootstrap_created",
            target_type="oauth_owner_bootstrap",
            target_id=owner_invitation_id,
            session_id=owner_invitation_id,
            status="ok",
            reason_code="owner_bootstrap_created",
            actor_type="service",
            actor_service_id=_OPERATOR_ID,
            workspace_id=_WORKSPACE_ID,
            metadata={"event_stage": "owner_bootstrap"},
        )
    )
    add(_authorization_start(audit_index, 2, "tx_owner"))
    rows.extend(
        _initial_callback_rows(
            audit_index,
            3,
            transaction_id="tx_owner",
            user_id=_OWNER_ID,
            identity_id=_OWNER_IDENTITY_ID,
            invitation_id=owner_invitation_id,
            role="owner",
        )
    )
    audit_index += 4
    add(
        _token_row(
            audit_index,
            4,
            user_id=_OWNER_ID,
            identity_id=_OWNER_IDENTITY_ID,
            token_session_id="oauthsid_owner",
            role="owner",
        )
    )
    add(
        _tool_row(
            audit_index,
            5,
            user_id=_OWNER_ID,
            identity_id=_OWNER_IDENTITY_ID,
            token_session_id="oauthsid_owner",
            tool_name="whoami",
            allowed=True,
        )
    )
    add(
        _tool_row(
            audit_index,
            6,
            user_id=_OWNER_ID,
            identity_id=_OWNER_IDENTITY_ID,
            token_session_id="oauthsid_owner",
            tool_name="open_upload_session",
            allowed=True,
        )
    )
    add(
        _audit_row(
            audit_index,
            7,
            action="oauth_invitation_create",
            target_type="oauth_invitation",
            target_id=member_invitation_id,
            session_id=member_invitation_id,
            status="ok",
            reason_code="invitation_created",
            actor_type="service",
            actor_service_id=_OPERATOR_ID,
            workspace_id=_WORKSPACE_ID,
            metadata={
                "event_stage": "invitation",
                "lineage_source": "owner_approval",
                "approval_user_id": _OWNER_ID,
            },
        )
    )
    add(_authorization_start(audit_index, 8, "tx_member_initial"))
    rows.extend(
        _initial_callback_rows(
            audit_index,
            9,
            transaction_id="tx_member_initial",
            user_id=_MEMBER_ID,
            identity_id=_MEMBER_IDENTITY_ID,
            invitation_id=member_invitation_id,
            role="member",
        )
    )
    audit_index += 4
    add(
        _token_row(
            audit_index,
            10,
            user_id=_MEMBER_ID,
            identity_id=_MEMBER_IDENTITY_ID,
            token_session_id="oauthsid_member_initial",
            role="member",
        )
    )
    add(
        _tool_row(
            audit_index,
            11,
            user_id=_MEMBER_ID,
            identity_id=_MEMBER_IDENTITY_ID,
            token_session_id="oauthsid_member_initial",
            tool_name="whoami",
            allowed=True,
        )
    )
    add(
        _audit_row(
            audit_index,
            12,
            action="oauth_invitation_create",
            target_type="workspace",
            target_id=_WORKSPACE_ID,
            session_id=_WORKSPACE_ID,
            status="denied",
            reason_code="invitation_owner_required",
            actor_type="service",
            actor_service_id=_OPERATOR_ID,
            workspace_id=_WORKSPACE_ID,
            metadata={
                "event_stage": "invitation",
                "lineage_source": "owner_approval",
                "approval_user_id": _MEMBER_ID,
            },
        )
    )
    add(
        _tool_row(
            audit_index,
            13,
            user_id=_MEMBER_ID,
            identity_id=_MEMBER_IDENTITY_ID,
            token_session_id="oauthsid_member_initial",
            tool_name="open_upload_session",
            allowed=False,
        )
    )
    add(
        _tool_row(
            audit_index,
            14,
            user_id=_MEMBER_ID,
            identity_id=_MEMBER_IDENTITY_ID,
            token_session_id="oauthsid_member_initial",
            tool_name="whoami",
            allowed=False,
        )
    )
    add(
        _audit_row(
            audit_index,
            15,
            action="operator_workspace_member_remove",
            target_type="workspace_member",
            target_id=member_target,
            session_id=f"audit_{audit_index:03d}",
            status="ok",
            reason_code="operator_directory_allowed",
            actor_type="service",
            actor_service_id=_OPERATOR_ID,
            metadata={
                "event_stage": "operator_directory",
                "operation": "operator_workspace_member_remove",
                "membership_role": "member",
                "membership_state": "removed",
                "revoked_token_session_count": 1,
            },
        )
    )
    add(
        _http_denial(
            audit_index,
            16,
            token_session_id="oauthsid_member_initial",
            reason_code="workspace_membership_inactive",
        )
    )
    add(
        _http_denial(
            audit_index,
            17,
            token_session_id="oauthsid_member_initial",
            reason_code="workspace_membership_inactive",
        )
    )
    add(_authorization_start(audit_index, 18, "tx_member_removed"))
    add(
        _audit_row(
            audit_index,
            19,
            action="google_authentication_failed",
            target_type="oauth_request",
            target_id="oauthdeny_removed",
            session_id="oauthdeny_removed",
            status="permission_denied",
            reason_code="workspace_membership_inactive",
            actor_type="external_unauthenticated",
            oauth_client_id=_CLIENT_ID,
            metadata={"event_stage": "google_callback"},
        )
    )
    add(
        _audit_row(
            audit_index,
            20,
            action="operator_workspace_member_restore",
            target_type="workspace_member",
            target_id=member_target,
            session_id=f"audit_{audit_index:03d}",
            status="ok",
            reason_code="operator_directory_allowed",
            actor_type="service",
            actor_service_id=_OPERATOR_ID,
            metadata={
                "event_stage": "operator_directory",
                "operation": "operator_workspace_member_restore",
                "membership_role": "member",
                "membership_state": "active",
            },
        )
    )
    add(_authorization_start(audit_index, 21, "tx_member_restore"))
    rows.extend(
        _relink_callback_rows(
            audit_index,
            22,
            transaction_id="tx_member_restore",
        )
    )
    audit_index += 3
    add(
        _token_row(
            audit_index,
            23,
            user_id=_MEMBER_ID,
            identity_id=_MEMBER_IDENTITY_ID,
            token_session_id="oauthsid_member_restore",
            role="member",
        )
    )
    add(
        _tool_row(
            audit_index,
            24,
            user_id=_MEMBER_ID,
            identity_id=_MEMBER_IDENTITY_ID,
            token_session_id="oauthsid_member_restore",
            tool_name="whoami",
            allowed=True,
        )
    )
    if include_post_restore_old_denial:
        add(
            _http_denial(
                audit_index,
                25,
                token_session_id="oauthsid_member_initial",
                reason_code="workspace_membership_inactive",
            )
        )
    add(
        _audit_row(
            audit_index,
            26,
            action="oauth_token_session_revoked",
            target_type="oauth_token_session",
            target_id="oauthsid_member_restore",
            session_id="oauthsid_member_restore",
            status="ok",
            reason_code="operator_test_revocation",
            actor_type="service",
            actor_service_id=_OPERATOR_ID,
            workspace_id=_WORKSPACE_ID,
            external_identity_id=_MEMBER_IDENTITY_ID,
            oauth_client_id=_CLIENT_ID,
            oauth_token_session_id="oauthsid_member_restore",
            metadata={"event_stage": "revocation", "token_session_status": "revoked"},
        )
    )
    add(
        _http_denial(
            audit_index,
            27,
            token_session_id="oauthsid_member_restore",
            reason_code="token_session_revoked",
        )
    )
    add(_authorization_start(audit_index, 28, "tx_member_post_revocation"))
    rows.extend(
        _relink_callback_rows(
            audit_index,
            29,
            transaction_id="tx_member_post_revocation",
        )
    )
    audit_index += 3
    add(
        _token_row(
            audit_index,
            30,
            user_id=_MEMBER_ID,
            identity_id=_MEMBER_IDENTITY_ID,
            token_session_id="oauthsid_member_post_revocation",
            role="member",
        )
    )
    add(
        _tool_row(
            audit_index,
            31,
            user_id=_MEMBER_ID,
            identity_id=_MEMBER_IDENTITY_ID,
            token_session_id="oauthsid_member_post_revocation",
            tool_name="whoami",
            allowed=True,
        )
    )
    add(
        _http_denial(
            audit_index,
            32,
            token_session_id="oauthsid_member_post_revocation",
            reason_code="token_session_expired",
        )
    )
    add(_authorization_start(audit_index, 33, "tx_member_post_expiry"))
    rows.extend(
        _relink_callback_rows(
            audit_index,
            34,
            transaction_id="tx_member_post_expiry",
        )
    )
    audit_index += 3
    add(
        _token_row(
            audit_index,
            35,
            user_id=_MEMBER_ID,
            identity_id=_MEMBER_IDENTITY_ID,
            token_session_id="oauthsid_member_post_expiry",
            role="member",
        )
    )
    add(
        _tool_row(
            audit_index,
            36,
            user_id=_MEMBER_ID,
            identity_id=_MEMBER_IDENTITY_ID,
            token_session_id="oauthsid_member_post_expiry",
            tool_name="whoami",
            allowed=True,
        )
    )
    return sorted(rows, key=lambda row: (str(row["timestamp"]), str(row["audit_log_id"])))


class Issue20AuditProjectionTests(unittest.TestCase):
    def test_exact_47_projection_matches_governed_hash_chain_contract(self) -> None:
        rows = _issue20_rows()
        records = runtime_module._build_issue20_audit_records(
            rows,
            workspace_id=_WORKSPACE_ID,
            oauth_client_id=_CLIENT_ID,
            operator_service_id=_OPERATOR_ID,
            started_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
            ended_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
        )
        blockers: list[str] = []
        packet_module._validate_audit_records(records, blockers)
        self.assertEqual(blockers, [])
        self.assertEqual(len(records), 47)
        self.assertEqual(
            [record["event_name"] for record in records],
            list(runtime_module._ISSUE20_AUDIT_LINEAGE),
        )
        serialized = json.dumps(records, sort_keys=True)
        self.assertNotIn(f'"{_OWNER_ID}"', serialized)
        self.assertNotIn(f'"{_MEMBER_ID}"', serialized)
        self.assertNotIn(f'"{_OWNER_IDENTITY_ID}"', serialized)
        self.assertNotIn(f'"{_MEMBER_IDENTITY_ID}"', serialized)

    def test_wrong_workspace_missing_duplicate_and_malformed_rows_fail_closed(self) -> None:
        cases: list[list[dict[str, object]]] = []
        wrong_workspace = _issue20_rows()
        next(row for row in wrong_workspace if row["action"] == "oauth_token_session_issued")[
            "workspace_id"
        ] = "workspace_wrong"
        cases.append(wrong_workspace)
        missing = _issue20_rows()
        missing.pop()
        cases.append(missing)
        duplicate = _issue20_rows()
        duplicate[-1]["audit_log_id"] = duplicate[-2]["audit_log_id"]
        cases.append(duplicate)
        malformed = _issue20_rows()
        next(row for row in malformed if row["action"] == "oauth_authorization_started")[
            "metadata"
        ] = {"event_stage": ["private", object()]}
        cases.append(malformed)
        malformed_tool = _issue20_rows()
        next(row for row in malformed_tool if row["action"] == "mcp_authorization_allowed")[
            "metadata"
        ]["tool_name"] = "private_tool"
        cases.append(malformed_tool)
        malformed_http_denial = _issue20_rows()
        next(
            row
            for row in malformed_http_denial
            if row["action"] == "mcp_http_authentication_denied"
        )["metadata"]["request_path"] = "/private"
        cases.append(malformed_http_denial)

        for rows in cases:
            with self.subTest(case=len(rows)):
                with self.assertRaises(ValueError):
                    runtime_module._build_issue20_audit_records(
                        rows,
                        workspace_id=_WORKSPACE_ID,
                        oauth_client_id=_CLIENT_ID,
                        operator_service_id=_OPERATOR_ID,
                        started_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
                        ended_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
                    )


class Issue20AuditRepositoryTests(unittest.TestCase):
    def test_repository_query_is_parameterized_allowlisted_and_bounded(self) -> None:
        class Connection:
            def __init__(self) -> None:
                self.statement = None

            def query_all(self, statement):
                self.statement = statement
                return []

        connection = Connection()
        repository = PostgreSQLOAuthRepository(connection)
        started_at = datetime(2026, 7, 20, tzinfo=timezone.utc)
        ended_at = started_at + timedelta(hours=1)
        rows = repository.list_issue20_live_audit_rows(
            started_at=started_at,
            ended_at=ended_at,
            actions=("oauth_authorization_started",),
            row_limit=47,
        )
        self.assertEqual(rows, [])
        statement = connection.statement
        self.assertIn("action = ANY(%(actions)s)", statement.sql)
        self.assertIn("LIMIT %(row_limit)s", statement.sql)
        self.assertNotIn("oauth_authorization_started", statement.sql)
        self.assertEqual(statement.parameters["started_at"], started_at)
        self.assertEqual(statement.parameters["ended_at"], ended_at)
        self.assertEqual(statement.parameters["actions"], ["oauth_authorization_started"])
        self.assertEqual(statement.parameters["row_limit"], 47)

        invalid_cases = (
            {"started_at": "invalid"},
            {"ended_at": started_at},
            {"actions": ()},
            {"actions": ("",)},
            {"row_limit": True},
            {"row_limit": 258},
        )
        for changes in invalid_cases:
            with self.subTest(changes=changes):
                arguments = {
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "actions": ("oauth_authorization_started",),
                    "row_limit": 47,
                    **changes,
                }
                with self.assertRaisesRegex(ValueError, "^Issue #20 audit query is invalid$"):
                    repository.list_issue20_live_audit_rows(**arguments)
        self.assertIs(connection.statement, statement)


class Issue20AuditContainerEntrypointTests(unittest.TestCase):
    def test_export_command_uses_connected_runtime_and_stages_secrets(self) -> None:
        self.assertEqual(
            container_entrypoint._resolved_command(
                ["export-issue20-live-audit", "--workspace-id", _WORKSPACE_ID]
            ),
            [
                "formowl-connected-mcp",
                "export-issue20-live-audit",
                "--workspace-id",
                _WORKSPACE_ID,
            ],
        )
        self.assertTrue(
            container_entrypoint._requires_connected_secrets(
                ["export-issue20-live-audit"],
                {},
            )
        )


class Issue20AuditExportTests(unittest.TestCase):
    def test_export_writes_private_artifact_and_returns_only_count_and_hash(self) -> None:
        repository = _AuditRepository(_issue20_rows())
        connected_runtime = _runtime(repository)
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            os.chmod(root, 0o700)
            output = root / "live-audit.json"
            payload = connected_runtime.export_issue20_live_audit(
                workspace_id=_WORKSPACE_ID,
                started_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
                ended_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
                operator_service_id=_OPERATOR_ID,
                output_path=output,
            )
            artifact = json.loads(output.read_text(encoding="utf-8"))
            output_mode = stat.S_IMODE(output.stat().st_mode)

        self.assertEqual(
            set(payload),
            {"status", "audit_record_count", "audit_manifest_hash"},
        )
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["audit_record_count"], 47)
        self.assertEqual(payload["audit_manifest_hash"], artifact["audit_manifest_hash"])
        self.assertEqual(len(artifact["audit_records"]), 47)
        self.assertEqual(output_mode, 0o600)
        self.assertTrue(repository.transactions[0].committed)

    def test_read_and_commit_failures_leave_no_artifact(self) -> None:
        for repository in (
            _AuditRepository(
                _issue20_rows(),
                read_error=RuntimeError("postgresql://private:secret@database/internal"),
            ),
            _AuditRepository(_issue20_rows(), fail_commit=True),
        ):
            with self.subTest(fail_commit=repository.fail_commit):
                connected_runtime = _runtime(repository)
                with tempfile.TemporaryDirectory() as value:
                    root = Path(value)
                    os.chmod(root, 0o700)
                    output = root / "live-audit.json"
                    with self.assertRaisesRegex(
                        ConnectedRuntimeError,
                        f"^{runtime_module._ISSUE20_AUDIT_EXPORT_ERROR}$",
                    ):
                        connected_runtime.export_issue20_live_audit(
                            workspace_id=_WORKSPACE_ID,
                            started_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
                            ended_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
                            operator_service_id=_OPERATOR_ID,
                            output_path=output,
                        )
                    self.assertFalse(output.exists())

    def test_symlink_and_non_regular_outputs_fail_before_database_read(self) -> None:
        for output_kind in ("symlink", "fifo"):
            with self.subTest(output_kind=output_kind):
                repository = _AuditRepository(_issue20_rows())
                connected_runtime = _runtime(repository)
                with tempfile.TemporaryDirectory() as value:
                    root = Path(value)
                    os.chmod(root, 0o700)
                    output = root / "live-audit.json"
                    if output_kind == "symlink":
                        target = root / "target.json"
                        target.write_text("private-prior", encoding="utf-8")
                        os.chmod(target, 0o600)
                        output.symlink_to(target)
                    else:
                        os.mkfifo(output, 0o600)
                    with self.assertRaises(ConnectedRuntimeError):
                        connected_runtime.export_issue20_live_audit(
                            workspace_id=_WORKSPACE_ID,
                            started_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
                            ended_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
                            operator_service_id=_OPERATOR_ID,
                            output_path=output,
                        )
                    self.assertEqual(repository.query_calls, 0)

    def test_atomic_replace_failure_preserves_existing_bytes_and_cleans_temp(self) -> None:
        repository = _AuditRepository(_issue20_rows())
        connected_runtime = _runtime(repository)
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            os.chmod(root, 0o700)
            output = root / "live-audit.json"
            output.write_bytes(b"prior-private-artifact\n")
            os.chmod(output, 0o600)
            with (
                patch.object(
                    runtime_module.os,
                    "replace",
                    side_effect=OSError("private replace detail"),
                ),
                self.assertRaises(ConnectedRuntimeError),
            ):
                connected_runtime.export_issue20_live_audit(
                    workspace_id=_WORKSPACE_ID,
                    started_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
                    ended_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
                    operator_service_id=_OPERATOR_ID,
                    output_path=output,
                )
            self.assertEqual(output.read_bytes(), b"prior-private-artifact\n")
            self.assertEqual([path.name for path in root.iterdir()], ["live-audit.json"])

    def test_cli_success_and_failure_outputs_do_not_disclose_private_values(self) -> None:
        class FakeRuntime:
            def __init__(self, *, fail: bool) -> None:
                self.fail = fail
                self.close_calls = 0

            def export_issue20_live_audit(self, **_kwargs: object):
                if self.fail:
                    raise ConnectedRuntimeError(runtime_module._ISSUE20_AUDIT_EXPORT_ERROR)
                return {
                    "status": "ok",
                    "audit_record_count": 47,
                    "audit_manifest_hash": "sha256:" + ("a" * 64),
                }

            async def aclose(self) -> None:
                self.close_calls += 1

        with tempfile.TemporaryDirectory(prefix="private-audit-path-") as value:
            output_path = str(Path(value) / "secret-audit.json")
            argv = [
                "export-issue20-live-audit",
                "--workspace-id",
                _WORKSPACE_ID,
                "--started-at",
                "2026-07-20T00:00:00+00:00",
                "--ended-at",
                "2026-07-21T00:00:00+00:00",
                "--operator-service-id",
                _OPERATOR_ID,
                "--output",
                output_path,
            ]
            for fail in (False, True):
                with self.subTest(fail=fail):
                    fake_runtime = FakeRuntime(fail=fail)
                    stdout = StringIO()
                    stderr = StringIO()
                    with (
                        patch.object(
                            runtime_module.ConnectedRuntimeConfig,
                            "from_env_and_secrets",
                            return_value=object(),
                        ),
                        patch.object(
                            ConnectedRuntime,
                            "compose",
                            new=AsyncMock(return_value=fake_runtime),
                        ),
                        redirect_stdout(stdout),
                        redirect_stderr(stderr),
                    ):
                        exit_code = main(argv, environ={})
                    rendered = stdout.getvalue() + stderr.getvalue()
                    self.assertEqual(exit_code, 1 if fail else 0)
                    self.assertNotIn(output_path, rendered)
                    self.assertNotIn(_WORKSPACE_ID, rendered)
                    self.assertNotIn(_OPERATOR_ID, rendered)
                    if fail:
                        self.assertEqual(
                            json.loads(stderr.getvalue()),
                            {
                                "status": "error",
                                "error": runtime_module._ISSUE20_AUDIT_EXPORT_ERROR,
                            },
                        )
                    else:
                        self.assertEqual(
                            set(json.loads(stdout.getvalue())),
                            {"status", "audit_record_count", "audit_manifest_hash"},
                        )


if __name__ == "__main__":
    unittest.main()
