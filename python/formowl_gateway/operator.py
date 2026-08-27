"""Safe deployment-operator directory views for connected OAuth state."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import hmac
import re
from typing import Any

from formowl_auth.models import OAuthTokenSession
from formowl_auth.postgres import OAuthRepository
from formowl_auth.security import generate_safe_id, normalize_verified_email
from formowl_contract import AuditLog, User, WorkspaceMember


_SAFE_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class OperatorDirectoryError(RuntimeError):
    """Machine-safe operator-directory denial without database detail."""

    def __init__(self, code: str) -> None:
        safe_code = code if _SAFE_ERROR_CODE.fullmatch(code) else "operator_directory_failed"
        self.code = safe_code
        super().__init__(safe_code)


class OperatorDirectory:
    """Expose only stable identifiers needed by invitation and revocation commands."""

    def __init__(
        self,
        *,
        repository: OAuthRepository,
        expected_operator_service_id: str | None,
    ) -> None:
        self.repository = repository
        self.expected_operator_service_id = expected_operator_service_id

    def lookup_user(
        self,
        *,
        email: str,
        workspace_id: str,
        operator_service_id: str,
    ) -> dict[str, Any]:
        return self._execute_audited(
            operation="operator_user_lookup",
            operator_service_id=operator_service_id,
            denied_target_type="workspace",
            denied_target_id=_safe_audit_target(workspace_id),
            now=datetime.now(timezone.utc),
            action=lambda: self._lookup_user_result(email=email, workspace_id=workspace_id),
        )

    def list_users(
        self,
        *,
        workspace_id: str,
        operator_service_id: str,
    ) -> dict[str, Any]:
        return self._execute_audited(
            operation="operator_user_list",
            operator_service_id=operator_service_id,
            denied_target_type="workspace",
            denied_target_id=_safe_audit_target(workspace_id),
            now=datetime.now(timezone.utc),
            action=lambda: self._list_users_result(workspace_id=workspace_id),
        )

    def remove_workspace_member(
        self,
        *,
        user_id: str,
        workspace_id: str,
        operator_service_id: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        resolved_now = _utc_now(now)
        return self._execute_audited(
            operation="operator_workspace_member_remove",
            operator_service_id=operator_service_id,
            denied_target_type="workspace_member",
            denied_target_id=_safe_membership_target(user_id, workspace_id),
            now=resolved_now,
            action=lambda: self._remove_workspace_member_result(
                user_id=user_id,
                workspace_id=workspace_id,
                now=resolved_now,
            ),
        )

    def restore_workspace_member(
        self,
        *,
        user_id: str,
        workspace_id: str,
        operator_service_id: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        resolved_now = _utc_now(now)
        return self._execute_audited(
            operation="operator_workspace_member_restore",
            operator_service_id=operator_service_id,
            denied_target_type="workspace_member",
            denied_target_id=_safe_membership_target(user_id, workspace_id),
            now=resolved_now,
            action=lambda: self._restore_workspace_member_result(
                user_id=user_id,
                workspace_id=workspace_id,
            ),
        )

    def lookup_token_session(
        self,
        *,
        user_id: str,
        workspace_id: str,
        operator_service_id: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        resolved_now = _utc_now(now)
        return self._execute_audited(
            operation="operator_token_session_lookup",
            operator_service_id=operator_service_id,
            denied_target_type="user",
            denied_target_id=_safe_audit_target(user_id),
            now=resolved_now,
            action=lambda: self._lookup_token_session_result(
                user_id=user_id,
                workspace_id=workspace_id,
                now=resolved_now,
            ),
        )

    def list_token_sessions(
        self,
        *,
        user_id: str,
        workspace_id: str,
        operator_service_id: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        resolved_now = _utc_now(now)
        return self._execute_audited(
            operation="operator_token_session_list",
            operator_service_id=operator_service_id,
            denied_target_type="user",
            denied_target_id=_safe_audit_target(user_id),
            now=resolved_now,
            action=lambda: self._list_token_sessions_result(
                user_id=user_id,
                workspace_id=workspace_id,
                now=resolved_now,
            ),
        )

    def _lookup_user_result(
        self,
        *,
        email: str,
        workspace_id: str,
    ) -> tuple[dict[str, Any], str, str, dict[str, Any]]:
        _require_safe_identifier(workspace_id)
        try:
            normalized_email = normalize_verified_email(email)
        except Exception:
            raise OperatorDirectoryError("operator_lookup_invalid") from None
        users = self.repository.find_users_by_email(normalized_email)
        if not users:
            raise OperatorDirectoryError("operator_user_not_found")
        if len(users) != 1:
            raise OperatorDirectoryError("operator_user_ambiguous")
        user = users[0]
        if user.status != "active":
            raise OperatorDirectoryError("operator_user_disabled")
        membership = self.repository.get_active_workspace_member(user.user_id, workspace_id)
        if membership is None:
            raise OperatorDirectoryError("operator_user_membership_not_found")
        return (
            {
                "status": "ok",
                "result_count": 1,
                "user": _safe_user_entry(user, membership),
            },
            "user",
            user.user_id,
            {"result_count": 1},
        )

    def _list_users_result(
        self,
        *,
        workspace_id: str,
    ) -> tuple[dict[str, Any], str, str, dict[str, Any]]:
        _require_safe_identifier(workspace_id)
        rows = self.repository.list_workspace_users(workspace_id)
        active = [
            _safe_user_entry(user, membership)
            for user, membership in rows
            if user.status == "active"
        ]
        inactive_count = len(rows) - len(active)
        return (
            {
                "status": "ok",
                "result_count": len(active),
                "inactive_user_count": inactive_count,
                "users": active,
            },
            "workspace",
            workspace_id,
            {"result_count": len(active), "inactive_user_count": inactive_count},
        )

    def _lookup_token_session_result(
        self,
        *,
        user_id: str,
        workspace_id: str,
        now: datetime,
    ) -> tuple[dict[str, Any], str, str, dict[str, Any]]:
        active, inactive_count = self._active_token_sessions(
            user_id=user_id,
            workspace_id=workspace_id,
            now=now,
        )
        if not active:
            raise OperatorDirectoryError("operator_token_session_not_found")
        if len(active) != 1:
            raise OperatorDirectoryError("operator_token_session_ambiguous")
        session = active[0]
        return (
            {
                "status": "ok",
                "result_count": 1,
                "inactive_session_count": inactive_count,
                "token_session": _safe_token_session_entry(session),
            },
            "oauth_token_session",
            session.token_session_id,
            {"result_count": 1, "inactive_session_count": inactive_count},
        )

    def _remove_workspace_member_result(
        self,
        *,
        user_id: str,
        workspace_id: str,
        now: datetime,
    ) -> tuple[dict[str, Any], str, str, dict[str, Any]]:
        _require_safe_identifier(user_id)
        _require_safe_identifier(workspace_id)
        user = self.repository.get_user(user_id)
        if user is None or user.status != "active":
            raise OperatorDirectoryError("operator_user_not_found")
        workspace_members = self.repository.list_active_workspace_members_in_workspace(
            workspace_id,
            for_update=True,
        )
        membership = next(
            (member for member in workspace_members if member.user_id == user_id),
            None,
        )
        if membership is None:
            raise OperatorDirectoryError("operator_membership_not_found")
        if (
            membership.role == "owner"
            and sum(member.role == "owner" for member in workspace_members) == 1
        ):
            raise OperatorDirectoryError("operator_last_owner_removal_denied")
        token_sessions = self.repository.list_token_sessions(user_id, workspace_id)
        active_session_count = sum(session.revoked_at is None for session in token_sessions)
        self.repository.remove_workspace_member(
            user_id,
            workspace_id,
            removed_at=now.isoformat(),
        )
        self.repository.revoke_active_token_sessions_for_membership(
            user_id,
            workspace_id,
            revoked_at=now.isoformat(),
            reason_code="workspace_membership_removed",
        )
        target_id = _safe_membership_target(user_id, workspace_id)
        return (
            {
                "status": "ok",
                "membership_removed": True,
                "user_id": user_id,
                "workspace_id": workspace_id,
            },
            "workspace_member",
            target_id,
            {
                "membership_role": membership.role,
                "membership_state": "removed",
                "revoked_token_session_count": active_session_count,
            },
        )

    def _restore_workspace_member_result(
        self,
        *,
        user_id: str,
        workspace_id: str,
    ) -> tuple[dict[str, Any], str, str, dict[str, Any]]:
        _require_safe_identifier(user_id)
        _require_safe_identifier(workspace_id)
        user = self.repository.get_user(user_id)
        if user is None or user.status != "active":
            raise OperatorDirectoryError("operator_user_not_found")
        membership = self.repository.get_removed_workspace_member(
            user_id,
            workspace_id,
            for_update=True,
        )
        if membership is None:
            raise OperatorDirectoryError("operator_removed_membership_not_found")
        self.repository.restore_workspace_member(user_id, workspace_id)
        target_id = _safe_membership_target(user_id, workspace_id)
        return (
            {
                "status": "ok",
                "membership_restored": True,
                "user_id": user_id,
                "workspace_id": workspace_id,
                "role": membership.role,
            },
            "workspace_member",
            target_id,
            {"membership_role": membership.role, "membership_state": "active"},
        )

    def _list_token_sessions_result(
        self,
        *,
        user_id: str,
        workspace_id: str,
        now: datetime,
    ) -> tuple[dict[str, Any], str, str, dict[str, Any]]:
        active, inactive_count = self._active_token_sessions(
            user_id=user_id,
            workspace_id=workspace_id,
            now=now,
        )
        return (
            {
                "status": "ok",
                "result_count": len(active),
                "inactive_session_count": inactive_count,
                "token_sessions": [_safe_token_session_entry(session) for session in active],
            },
            "user",
            user_id,
            {"result_count": len(active), "inactive_session_count": inactive_count},
        )

    def _execute_audited(
        self,
        *,
        operation: str,
        operator_service_id: str,
        denied_target_type: str,
        denied_target_id: str,
        now: datetime,
        action: Callable[[], tuple[dict[str, Any], str, str, dict[str, Any]]],
    ) -> dict[str, Any]:
        try:
            self._authorize(operator_service_id)
        except OperatorDirectoryError as denial:
            self._audit_unauthorized(operation=operation, now=now)
            raise denial
        try:
            denied: OperatorDirectoryError | None = None
            payload: dict[str, Any] | None = None
            target_type = denied_target_type
            target_id = denied_target_id
            metadata: dict[str, Any] = {}
            with self.repository.transaction() as unit:
                try:
                    payload, target_type, target_id, metadata = action()
                except OperatorDirectoryError as error:
                    denied = error
                self.repository.append_audit_log(
                    self._audit_log(
                        operation=operation,
                        actor_type="service",
                        actor_service_id=operator_service_id,
                        target_type=target_type,
                        target_id=target_id,
                        status="denied" if denied is not None else "ok",
                        reason_code=(
                            denied.code if denied is not None else "operator_directory_allowed"
                        ),
                        now=now,
                        metadata=metadata,
                    )
                )
                unit.commit()
            if denied is not None:
                raise denied
            if payload is None:
                raise OperatorDirectoryError("operator_directory_inconsistent")
            return payload
        except OperatorDirectoryError:
            raise
        except Exception:
            raise OperatorDirectoryError("operator_directory_unavailable") from None

    def _audit_unauthorized(self, *, operation: str, now: datetime) -> None:
        try:
            with self.repository.transaction() as unit:
                self.repository.append_audit_log(
                    self._audit_log(
                        operation=operation,
                        actor_type="external_unauthenticated",
                        actor_service_id=None,
                        target_type="operator_directory",
                        target_id="operator_directory",
                        status="denied",
                        reason_code="operator_unauthorized",
                        now=now,
                        metadata={},
                    )
                )
                unit.commit()
        except Exception:
            raise OperatorDirectoryError("operator_directory_unavailable") from None

    def _audit_log(
        self,
        *,
        operation: str,
        actor_type: str,
        actor_service_id: str | None,
        target_type: str,
        target_id: str,
        status: str,
        reason_code: str,
        now: datetime,
        metadata: dict[str, Any],
    ) -> AuditLog:
        audit_log_id = generate_safe_id("audit")
        return AuditLog(
            audit_log_id=audit_log_id,
            actor_user_id=None,
            actor_type=actor_type,
            actor_service_id=actor_service_id,
            action=operation,
            target_type=target_type,
            target_id=target_id,
            session_id=audit_log_id,
            status=status,
            reason_code=reason_code,
            timestamp=now.isoformat(),
            metadata={"event_stage": "operator_directory", "operation": operation, **metadata},
        )

    def _authorize(self, operator_service_id: str) -> None:
        expected = self.expected_operator_service_id
        if (
            not isinstance(expected, str)
            or not _SAFE_IDENTIFIER.fullmatch(expected)
            or not isinstance(operator_service_id, str)
            or not _SAFE_IDENTIFIER.fullmatch(operator_service_id)
            or not hmac.compare_digest(expected, operator_service_id)
        ):
            raise OperatorDirectoryError("operator_unauthorized")

    def _active_token_sessions(
        self,
        *,
        user_id: str,
        workspace_id: str,
        now: datetime,
    ) -> tuple[list[OAuthTokenSession], int]:
        _require_safe_identifier(user_id)
        _require_safe_identifier(workspace_id)
        user = self.repository.get_user(user_id)
        if user is None:
            raise OperatorDirectoryError("operator_user_not_found")
        if user.status != "active":
            raise OperatorDirectoryError("operator_user_disabled")
        membership = self.repository.get_active_workspace_member(user_id, workspace_id)
        if membership is None:
            raise OperatorDirectoryError("operator_user_membership_not_found")
        sessions = self.repository.list_token_sessions(user_id, workspace_id)
        active: list[OAuthTokenSession] = []
        inactive_count = 0
        for session in sessions:
            if session.user_id != user_id or session.current_workspace_id != workspace_id:
                raise OperatorDirectoryError("operator_directory_inconsistent")
            identity = self.repository.get_external_identity(session.external_identity_id)
            authorization = self.repository.get_client_authorization_by_id(
                session.oauth_client_authorization_id
            )
            if identity is None or authorization is None:
                raise OperatorDirectoryError("operator_directory_inconsistent")
            if (
                identity.user_id != user_id
                or authorization.user_id != user_id
                or authorization.external_identity_id != identity.external_identity_id
                or authorization.client_id != session.client_id
                or authorization.default_workspace_id != workspace_id
            ):
                raise OperatorDirectoryError("operator_directory_inconsistent")
            if identity.status != "active":
                raise OperatorDirectoryError("operator_external_identity_disabled")
            if authorization.revoked_at is not None:
                raise OperatorDirectoryError("operator_client_authorization_disabled")
            expires_at = _parse_timestamp(session.expires_at)
            if session.revoked_at is not None or expires_at <= now:
                inactive_count += 1
                continue
            active.append(session)
        active.sort(key=lambda session: (session.issued_at, session.token_session_id), reverse=True)
        return active, inactive_count


def _safe_user_entry(user: User, membership: WorkspaceMember) -> dict[str, str]:
    return {
        "user_id": user.user_id,
        "workspace_id": membership.workspace_id,
        "role": membership.role,
        "status": "active",
    }


def _safe_token_session_entry(session: OAuthTokenSession) -> dict[str, str]:
    return {
        "token_session_id": session.token_session_id,
        "user_id": session.user_id,
        "workspace_id": session.current_workspace_id,
        "status": "active",
        "issued_at": session.issued_at,
        "expires_at": session.expires_at,
    }


def _require_safe_identifier(value: str) -> None:
    if not isinstance(value, str) or not _SAFE_IDENTIFIER.fullmatch(value):
        raise OperatorDirectoryError("operator_lookup_invalid")


def _safe_audit_target(value: str) -> str:
    if isinstance(value, str) and _SAFE_IDENTIFIER.fullmatch(value):
        return value
    return "operator_directory"


def _safe_membership_target(user_id: str, workspace_id: str) -> str:
    if (
        isinstance(user_id, str)
        and _SAFE_IDENTIFIER.fullmatch(user_id)
        and isinstance(workspace_id, str)
        and _SAFE_IDENTIFIER.fullmatch(workspace_id)
    ):
        return f"{workspace_id}:{user_id}"
    return "operator_directory"


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise OperatorDirectoryError("operator_directory_inconsistent") from None
    if parsed.tzinfo is None:
        raise OperatorDirectoryError("operator_directory_inconsistent")
    return parsed.astimezone(timezone.utc)


def _utc_now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if not isinstance(value, datetime):
        raise OperatorDirectoryError("operator_lookup_invalid")
    try:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError
        return value.astimezone(timezone.utc)
    except Exception:
        raise OperatorDirectoryError("operator_lookup_invalid") from None


__all__ = [
    "OperatorDirectory",
    "OperatorDirectoryError",
]
