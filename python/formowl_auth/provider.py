"""Manual trusted internal identity provider for Phase 0."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from formowl_contract import (
    AccessRequest,
    Grant,
    SessionIdentity,
    User,
    WorkspaceMember,
    now_iso,
    stable_resource_contract_id,
    to_plain,
)

from .audit import FileAuditLogStore, record_actor_selection


@dataclass(frozen=True)
class ActorContext:
    user: User
    session_identity: SessionIdentity
    workspace_memberships: list[WorkspaceMember] = field(default_factory=list)
    active_grants: list[Grant] = field(default_factory=list)
    pending_access_requests: list[AccessRequest] = field(default_factory=list)
    auth_mode: str = "manual_trusted_internal"
    production_authentication: bool = False
    authentication_note: str = (
        "manual_trusted_internal is a Phase 0 trusted internal identity facade, "
        "not production authentication"
    )

    def to_dict(self) -> dict[str, object]:
        return to_plain(self)


class ManualTrustedInternalAuthProvider:
    """Selects a known FormOwl user without claiming production authentication."""

    selection_method = "manual_trusted_internal"

    def __init__(
        self,
        *,
        users: list[User],
        workspace_memberships: list[WorkspaceMember] | None = None,
        grants: list[Grant] | None = None,
        access_requests: list[AccessRequest] | None = None,
        audit_store: FileAuditLogStore | None = None,
    ) -> None:
        self.users = list(users)
        self.workspace_memberships = list(workspace_memberships or [])
        self.grants = list(grants or [])
        self.access_requests = list(access_requests or [])
        self.audit_store = audit_store
        # This provider trusts a pre-seeded internal user list; it does not
        # verify passwords, SSO assertions, cookies, or external credentials.
        self._selected_context: ActorContext | None = None

    def select_actor(
        self,
        display_name_or_user_id: str,
        *,
        session_id: str | None = None,
        selected_at: str | None = None,
    ) -> ActorContext:
        user = self._resolve_selectable_user(display_name_or_user_id)
        timestamp = selected_at or now_iso()
        resolved_session_id = session_id or stable_resource_contract_id(
            "session",
            "SessionIdentity",
            {
                "selected_user_id": user.user_id,
                "selected_at": timestamp,
                "selection_method": self.selection_method,
            },
        )
        session_identity = SessionIdentity(
            session_id=resolved_session_id,
            selected_user_id=user.user_id,
            selected_at=timestamp,
            selection_method=self.selection_method,
        )
        context = ActorContext(
            user=user,
            session_identity=session_identity,
            workspace_memberships=self._memberships_for(user.user_id),
            active_grants=self._active_grants_for(user.user_id, selected_at=timestamp),
            pending_access_requests=self._pending_requests_for(user.user_id),
        )
        self._selected_context = context

        if self.audit_store is not None:
            record_actor_selection(
                self.audit_store,
                actor_user_id=user.user_id,
                session_id=session_identity.session_id,
                workspace_id=_first_workspace_id(context.workspace_memberships),
                timestamp=timestamp,
            )

        return context

    def whoami(self) -> ActorContext | None:
        return self._selected_context

    def _resolve_selectable_user(self, display_name_or_user_id: str) -> User:
        query = display_name_or_user_id.strip()
        query_lower = query.lower()
        for user in self.users:
            if user.status != "active":
                continue
            if user.user_id == query:
                return user
            if user.display_name.lower() == query_lower:
                return user
            if user.email is not None and user.email.lower() == query_lower:
                return user
        raise KeyError(f"selectable active user was not found: {display_name_or_user_id}")

    def _memberships_for(self, user_id: str) -> list[WorkspaceMember]:
        return [member for member in self.workspace_memberships if member.user_id == user_id]

    def _active_grants_for(self, user_id: str, *, selected_at: str) -> list[Grant]:
        return [
            grant
            for grant in self.grants
            if grant.grantee_user_id == user_id and grant.revoked_at is None
            and _parse_iso(grant.expires_at) > _parse_iso(selected_at)
        ]

    def _pending_requests_for(self, user_id: str) -> list[AccessRequest]:
        return [
            request
            for request in self.access_requests
            if request.status == "pending"
            and (request.owner_user_id == user_id or request.requester_user_id == user_id)
        ]


def _first_workspace_id(memberships: list[WorkspaceMember]) -> str | None:
    if not memberships:
        return None
    return memberships[0].workspace_id


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
