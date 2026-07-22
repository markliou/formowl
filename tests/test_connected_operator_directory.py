from __future__ import annotations

import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone, tzinfo
import json
from pathlib import Path
import unittest

import _paths  # noqa: F401
from formowl_auth import ExternalIdentity, OAuthClientAuthorization, OAuthTokenSession
from formowl_contract import User, WorkspaceMember
from formowl_gateway.operator import OperatorDirectory, OperatorDirectoryError


_NOW = datetime(2026, 7, 12, 8, 0, tzinfo=timezone.utc)


class _DetachedTimezone(tzinfo):
    def utcoffset(self, _value: datetime | None) -> None:
        return None

    def dst(self, _value: datetime | None) -> None:
        return None

    def tzname(self, _value: datetime | None) -> str:
        return "private-detached-timezone"


class _ExplodingUtcoffsetTimezone(tzinfo):
    def __init__(self, private_detail: str) -> None:
        self.private_detail = private_detail

    def utcoffset(self, _value: datetime | None) -> timedelta:
        raise RuntimeError(self.private_detail)

    def dst(self, _value: datetime | None) -> timedelta:
        return timedelta(0)

    def tzname(self, _value: datetime | None) -> str:
        return "private-exploding-utcoffset"


class _ExplodingAstimezoneTimezone(tzinfo):
    def __init__(self, private_detail: str) -> None:
        self.private_detail = private_detail
        self.utcoffset_call_count = 0

    def utcoffset(self, _value: datetime | None) -> timedelta:
        self.utcoffset_call_count += 1
        if self.utcoffset_call_count == 1:
            return timedelta(hours=8)
        raise RuntimeError(self.private_detail)

    def dst(self, _value: datetime | None) -> timedelta:
        return timedelta(0)

    def tzname(self, _value: datetime | None) -> str:
        return "private-exploding-astimezone"


class _OperatorRepository:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.users: list[User] = []
        self.memberships: list[WorkspaceMember] = []
        self.removed_memberships: dict[tuple[str, str], str] = {}
        self.identities: list[ExternalIdentity] = []
        self.authorizations: list[OAuthClientAuthorization] = []
        self.sessions: list[OAuthTokenSession] = []
        self.audits = []
        self.failure: Exception | None = None
        self.audit_failure: Exception | None = None
        self.commit_count = 0
        self.rollback_count = 0

    def _record(self, name: str) -> None:
        self.calls.append(name)
        if self.failure is not None:
            raise self.failure

    def transaction(self):
        self.calls.append("transaction")
        return _OperatorUnitOfWork(self)

    def append_audit_log(self, audit_log) -> None:
        self.calls.append("append_audit_log")
        if self.audit_failure is not None:
            raise self.audit_failure
        audit_log.to_dict()
        self.audits.append(audit_log)

    def find_users_by_email(self, normalized_email: str) -> list[User]:
        self._record("find_users_by_email")
        return [user for user in self.users if user.email == normalized_email]

    def list_workspace_users(self, workspace_id: str):
        self._record("list_workspace_users")
        return [
            (user, membership)
            for membership in self.memberships
            for user in self.users
            if membership.workspace_id == workspace_id
            and user.user_id == membership.user_id
            and (membership.user_id, membership.workspace_id) not in self.removed_memberships
        ]

    def get_user(self, user_id: str) -> User | None:
        self._record("get_user")
        return next((user for user in self.users if user.user_id == user_id), None)

    def get_active_workspace_member(
        self,
        user_id: str,
        workspace_id: str,
        *,
        for_update: bool = False,
    ) -> WorkspaceMember | None:
        del for_update
        self._record("get_active_workspace_member")
        return next(
            (
                membership
                for membership in self.memberships
                if membership.user_id == user_id
                and membership.workspace_id == workspace_id
                and (user_id, workspace_id) not in self.removed_memberships
            ),
            None,
        )

    def get_removed_workspace_member(
        self,
        user_id: str,
        workspace_id: str,
        *,
        for_update: bool = False,
    ) -> WorkspaceMember | None:
        del for_update
        self._record("get_removed_workspace_member")
        if (user_id, workspace_id) not in self.removed_memberships:
            return None
        return next(
            (
                membership
                for membership in self.memberships
                if membership.user_id == user_id and membership.workspace_id == workspace_id
            ),
            None,
        )

    def list_active_workspace_members_in_workspace(
        self,
        workspace_id: str,
        *,
        for_update: bool = False,
    ) -> list[WorkspaceMember]:
        del for_update
        self._record("list_active_workspace_members_in_workspace")
        return sorted(
            (
                membership
                for membership in self.memberships
                if membership.workspace_id == workspace_id
                and (membership.user_id, workspace_id) not in self.removed_memberships
            ),
            key=lambda membership: membership.user_id,
        )

    def remove_workspace_member(
        self,
        user_id: str,
        workspace_id: str,
        *,
        removed_at: str,
    ) -> None:
        self._record("remove_workspace_member")
        if self.get_active_workspace_member(user_id, workspace_id) is not None:
            self.removed_memberships[(user_id, workspace_id)] = removed_at

    def restore_workspace_member(self, user_id: str, workspace_id: str) -> None:
        self._record("restore_workspace_member")
        self.removed_memberships.pop((user_id, workspace_id), None)

    def list_token_sessions(self, user_id: str, workspace_id: str) -> list[OAuthTokenSession]:
        self._record("list_token_sessions")
        return [
            session
            for session in self.sessions
            if session.user_id == user_id and session.current_workspace_id == workspace_id
        ]

    def revoke_active_token_sessions_for_membership(
        self,
        user_id: str,
        workspace_id: str,
        *,
        revoked_at: str,
        reason_code: str,
    ) -> None:
        self._record("revoke_active_token_sessions_for_membership")
        self.sessions = [
            replace(
                session,
                revoked_at=revoked_at,
                revocation_reason=reason_code,
            )
            if session.user_id == user_id
            and session.current_workspace_id == workspace_id
            and session.revoked_at is None
            else session
            for session in self.sessions
        ]

    def get_external_identity(self, external_identity_id: str) -> ExternalIdentity | None:
        self._record("get_external_identity")
        return next(
            (
                identity
                for identity in self.identities
                if identity.external_identity_id == external_identity_id
            ),
            None,
        )

    def get_client_authorization_by_id(
        self, oauth_client_authorization_id: str
    ) -> OAuthClientAuthorization | None:
        self._record("get_client_authorization_by_id")
        return next(
            (
                authorization
                for authorization in self.authorizations
                if authorization.oauth_client_authorization_id == oauth_client_authorization_id
            ),
            None,
        )

    def snapshot_state(self):
        return copy.deepcopy(
            (
                self.users,
                self.memberships,
                self.removed_memberships,
                self.identities,
                self.authorizations,
                self.sessions,
                self.audits,
            )
        )

    def restore_state(self, snapshot) -> None:
        (
            self.users,
            self.memberships,
            self.removed_memberships,
            self.identities,
            self.authorizations,
            self.sessions,
            self.audits,
        ) = copy.deepcopy(snapshot)


class _OperatorUnitOfWork:
    def __init__(self, repository: _OperatorRepository) -> None:
        self.repository = repository
        self.committed = False
        self.snapshot = None

    def __enter__(self):
        self.snapshot = self.repository.snapshot_state()
        return self

    def __exit__(self, exc_type, _exc, _traceback) -> bool:
        if exc_type is None and self.committed:
            self.repository.commit_count += 1
        else:
            if self.snapshot is not None:
                self.repository.restore_state(self.snapshot)
            self.repository.rollback_count += 1
        return False

    def commit(self) -> None:
        self.committed = True


def _fixture() -> tuple[_OperatorRepository, OperatorDirectory]:
    repository = _OperatorRepository()
    user = User(
        user_id="user_owner_001",
        display_name="Private Owner Name",
        email="owner@example.test",
        status="active",
        created_at=_NOW.isoformat(),
    )
    membership = WorkspaceMember(
        workspace_id="workspace_001",
        user_id=user.user_id,
        role="owner",
    )
    identity = ExternalIdentity(
        external_identity_id="extid_owner_001",
        provider="google",
        issuer="https://accounts.google.com",
        subject="private-google-subject",
        user_id=user.user_id,
        email="owner@example.test",
        email_verified=True,
        status="active",
        created_at=_NOW.isoformat(),
        last_authenticated_at=_NOW.isoformat(),
    )
    authorization = OAuthClientAuthorization(
        oauth_client_authorization_id="clientauth_owner_001",
        client_id="chatgpt_client",
        external_identity_id=identity.external_identity_id,
        user_id=user.user_id,
        granted_scopes=("formowl.use",),
        default_workspace_id=membership.workspace_id,
        created_at=_NOW.isoformat(),
    )
    session = OAuthTokenSession(
        token_session_id="oauthsid_owner_001",
        user_id=user.user_id,
        external_identity_id=identity.external_identity_id,
        oauth_client_authorization_id=authorization.oauth_client_authorization_id,
        client_id=authorization.client_id,
        current_workspace_id=membership.workspace_id,
        resource="https://formowl.example.test/mcp",
        scopes=("formowl.use",),
        token_jti_hash="sha256:" + "a" * 64,
        issued_at=_NOW.isoformat(),
        expires_at=(_NOW + timedelta(hours=1)).isoformat(),
    )
    repository.users.append(user)
    repository.memberships.append(membership)
    repository.identities.append(identity)
    repository.authorizations.append(authorization)
    repository.sessions.append(session)
    return repository, OperatorDirectory(
        repository=repository,
        expected_operator_service_id="operator_trusted",
    )


def _add_connected_user(
    repository: _OperatorRepository,
    *,
    user_id: str = "user_member_001",
    role: str = "member",
    workspace_id: str = "workspace_001",
) -> OAuthTokenSession:
    user = User(
        user_id=user_id,
        display_name="Private Member Name",
        email=f"{user_id}@example.test",
        status="active",
        created_at=_NOW.isoformat(),
    )
    membership = WorkspaceMember(
        workspace_id=workspace_id,
        user_id=user_id,
        role=role,
    )
    identity = ExternalIdentity(
        external_identity_id=f"extid_{user_id}",
        provider="google",
        issuer="https://accounts.google.com",
        subject=f"private-google-{user_id}",
        user_id=user_id,
        email=user.email or "",
        email_verified=True,
        status="active",
        created_at=_NOW.isoformat(),
        last_authenticated_at=_NOW.isoformat(),
    )
    authorization = OAuthClientAuthorization(
        oauth_client_authorization_id=f"clientauth_{user_id}",
        client_id="chatgpt_client",
        external_identity_id=identity.external_identity_id,
        user_id=user_id,
        granted_scopes=("formowl.use",),
        default_workspace_id=workspace_id,
        created_at=_NOW.isoformat(),
    )
    session = OAuthTokenSession(
        token_session_id=f"oauthsid_{user_id}",
        user_id=user_id,
        external_identity_id=identity.external_identity_id,
        oauth_client_authorization_id=authorization.oauth_client_authorization_id,
        client_id=authorization.client_id,
        current_workspace_id=workspace_id,
        resource="https://formowl.example.test/mcp",
        scopes=("formowl.use",),
        token_jti_hash="sha256:" + "d" * 64,
        issued_at=_NOW.isoformat(),
        expires_at=(_NOW + timedelta(hours=1)).isoformat(),
    )
    repository.users.append(user)
    repository.memberships.append(membership)
    repository.identities.append(identity)
    repository.authorizations.append(authorization)
    repository.sessions.append(session)
    return session


class ConnectedOperatorDirectoryTests(unittest.TestCase):
    def test_user_lookup_and_list_return_only_active_stable_ids(self) -> None:
        repository, directory = _fixture()
        disabled = User(
            user_id="user_disabled_001",
            display_name="Disabled Private Name",
            email="disabled@example.test",
            status="disabled",
            created_at=_NOW.isoformat(),
        )
        repository.users.append(disabled)
        repository.memberships.append(
            WorkspaceMember(
                workspace_id="workspace_001",
                user_id=disabled.user_id,
                role="member",
            )
        )

        lookup = directory.lookup_user(
            email=" OWNER@EXAMPLE.TEST ",
            workspace_id="workspace_001",
            operator_service_id="operator_trusted",
        )
        listing = directory.list_users(
            workspace_id="workspace_001",
            operator_service_id="operator_trusted",
        )

        self.assertEqual(
            lookup,
            {
                "status": "ok",
                "result_count": 1,
                "user": {
                    "user_id": "user_owner_001",
                    "workspace_id": "workspace_001",
                    "role": "owner",
                    "status": "active",
                },
            },
        )
        self.assertEqual(listing["result_count"], 1)
        self.assertEqual(listing["inactive_user_count"], 1)
        self.assertEqual(listing["users"], [lookup["user"]])
        self.assertEqual(len(repository.audits), 2)
        self.assertTrue(all(audit.actor_type == "service" for audit in repository.audits))
        self.assertTrue(
            all(audit.actor_service_id == "operator_trusted" for audit in repository.audits)
        )
        self.assertTrue(all(audit.status == "ok" for audit in repository.audits))
        rendered = json.dumps({"lookup": lookup, "listing": listing}, sort_keys=True)
        for forbidden in (
            "owner@example.test",
            "Private Owner Name",
            "disabled@example.test",
            "Disabled Private Name",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_user_lookup_rejects_unauthorized_invalid_disabled_and_ambiguous(self) -> None:
        repository, directory = _fixture()
        with self.assertRaises(OperatorDirectoryError) as unauthorized:
            directory.lookup_user(
                email="owner@example.test",
                workspace_id="workspace_001",
                operator_service_id="operator_removed",
            )
        self.assertEqual(unauthorized.exception.code, "operator_unauthorized")
        self.assertEqual(len(repository.audits), 1)
        self.assertEqual(repository.audits[-1].actor_type, "external_unauthenticated")
        self.assertIsNone(repository.audits[-1].actor_service_id)
        self.assertEqual(repository.audits[-1].status, "denied")
        self.assertEqual(repository.audits[-1].reason_code, "operator_unauthorized")

        with self.assertRaises(OperatorDirectoryError) as invalid:
            directory.lookup_user(
                email="not-an-email/private",
                workspace_id="workspace_001",
                operator_service_id="operator_trusted",
            )
        self.assertEqual(invalid.exception.code, "operator_lookup_invalid")
        self.assertNotIn("not-an-email", str(invalid.exception))
        self.assertEqual(repository.audits[-1].actor_type, "service")
        self.assertEqual(repository.audits[-1].status, "denied")
        self.assertEqual(repository.audits[-1].reason_code, "operator_lookup_invalid")

        repository.users[0] = replace(repository.users[0], status="disabled")
        with self.assertRaises(OperatorDirectoryError) as disabled:
            directory.lookup_user(
                email="owner@example.test",
                workspace_id="workspace_001",
                operator_service_id="operator_trusted",
            )
        self.assertEqual(disabled.exception.code, "operator_user_disabled")

        repository.users[0] = replace(repository.users[0], status="active")
        repository.users.append(replace(repository.users[0], user_id="user_duplicate_email_001"))
        with self.assertRaises(OperatorDirectoryError) as ambiguous:
            directory.lookup_user(
                email="owner@example.test",
                workspace_id="workspace_001",
                operator_service_id="operator_trusted",
            )
        self.assertEqual(ambiguous.exception.code, "operator_user_ambiguous")

    def test_token_lookup_and_list_filter_inactive_without_sensitive_lineage(self) -> None:
        repository, directory = _fixture()
        repository.sessions.extend(
            [
                replace(
                    repository.sessions[0],
                    token_session_id="oauthsid_revoked_001",
                    token_jti_hash="sha256:" + "b" * 64,
                    revoked_at=(_NOW - timedelta(minutes=5)).isoformat(),
                    revocation_reason="operator_revoked",
                ),
                replace(
                    repository.sessions[0],
                    token_session_id="oauthsid_expired_001",
                    token_jti_hash="sha256:" + "c" * 64,
                    issued_at=(_NOW - timedelta(hours=2)).isoformat(),
                    expires_at=(_NOW - timedelta(hours=1)).isoformat(),
                ),
            ]
        )

        lookup = directory.lookup_token_session(
            user_id="user_owner_001",
            workspace_id="workspace_001",
            operator_service_id="operator_trusted",
            now=_NOW,
        )
        listing = directory.list_token_sessions(
            user_id="user_owner_001",
            workspace_id="workspace_001",
            operator_service_id="operator_trusted",
            now=_NOW,
        )

        self.assertEqual(lookup["result_count"], 1)
        self.assertEqual(lookup["inactive_session_count"], 2)
        self.assertEqual(lookup["token_session"]["token_session_id"], "oauthsid_owner_001")
        self.assertEqual(listing["result_count"], 1)
        self.assertEqual(listing["inactive_session_count"], 2)
        self.assertEqual(listing["token_sessions"], [lookup["token_session"]])
        self.assertEqual(len(repository.audits), 2)
        self.assertTrue(all(audit.actor_type == "service" for audit in repository.audits))
        self.assertTrue(all(audit.status == "ok" for audit in repository.audits))
        rendered = json.dumps({"lookup": lookup, "listing": listing}, sort_keys=True)
        for forbidden in (
            "sha256:" + "a" * 64,
            "sha256:" + "b" * 64,
            "sha256:" + "c" * 64,
            "extid_owner_001",
            "clientauth_owner_001",
            "chatgpt_client",
            "formowl.use",
            "https://formowl.example.test/mcp",
            "operator_revoked",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_token_lookup_rejects_ambiguity_and_disabled_authorization_state(self) -> None:
        repository, directory = _fixture()
        repository.sessions.append(
            replace(
                repository.sessions[0],
                token_session_id="oauthsid_owner_002",
                token_jti_hash="sha256:" + "d" * 64,
                issued_at=(_NOW + timedelta(minutes=1)).isoformat(),
            )
        )
        with self.assertRaises(OperatorDirectoryError) as ambiguous:
            directory.lookup_token_session(
                user_id="user_owner_001",
                workspace_id="workspace_001",
                operator_service_id="operator_trusted",
                now=_NOW,
            )
        self.assertEqual(ambiguous.exception.code, "operator_token_session_ambiguous")

        repository.sessions.pop()
        repository.identities[0] = replace(repository.identities[0], status="disabled")
        with self.assertRaises(OperatorDirectoryError) as identity_disabled:
            directory.list_token_sessions(
                user_id="user_owner_001",
                workspace_id="workspace_001",
                operator_service_id="operator_trusted",
                now=_NOW,
            )
        self.assertEqual(
            identity_disabled.exception.code,
            "operator_external_identity_disabled",
        )

        repository.identities[0] = replace(repository.identities[0], status="active")
        repository.authorizations[0] = replace(
            repository.authorizations[0],
            revoked_at=(_NOW - timedelta(minutes=1)).isoformat(),
        )
        with self.assertRaises(OperatorDirectoryError) as authorization_disabled:
            directory.list_token_sessions(
                user_id="user_owner_001",
                workspace_id="workspace_001",
                operator_service_id="operator_trusted",
                now=_NOW,
            )
        self.assertEqual(
            authorization_disabled.exception.code,
            "operator_client_authorization_disabled",
        )

    def test_token_lookup_rejects_naive_and_detached_now_without_state_change(
        self,
    ) -> None:
        invalid_now_values = (
            ("naive", datetime(2026, 7, 12, 8, 0)),
            (
                "detached_timezone",
                datetime(2026, 7, 12, 8, 0, tzinfo=_DetachedTimezone()),
            ),
        )

        for case_name, invalid_now in invalid_now_values:
            with self.subTest(case_name=case_name):
                repository, directory = _fixture()
                baseline = repository.snapshot_state()

                with self.assertRaises(OperatorDirectoryError) as invalid:
                    directory.lookup_token_session(
                        user_id="user_owner_001",
                        workspace_id="workspace_001",
                        operator_service_id="operator_trusted",
                        now=invalid_now,
                    )

                self.assertEqual(invalid.exception.code, "operator_lookup_invalid")
                self.assertEqual(str(invalid.exception), "operator_lookup_invalid")
                self.assertEqual(repository.snapshot_state(), baseline)
                self.assertEqual(repository.calls, [])
                self.assertEqual(repository.commit_count, 0)
                self.assertEqual(repository.rollback_count, 0)
                self.assertEqual(repository.audits, [])
                self.assertNotIn("private", str(invalid.exception))
                self.assertNotIn("timezone", str(invalid.exception))

    def test_token_lookup_normalizes_non_utc_now_to_utc_output_and_audit(
        self,
    ) -> None:
        repository, directory = _fixture()
        directory_state = dict(directory.__dict__)
        non_utc_now = datetime(
            2026,
            7,
            12,
            16,
            0,
            tzinfo=timezone(timedelta(hours=8)),
        )

        result = directory.lookup_token_session(
            user_id="user_owner_001",
            workspace_id="workspace_001",
            operator_service_id="operator_trusted",
            now=non_utc_now,
        )

        self.assertEqual(
            result,
            {
                "status": "ok",
                "result_count": 1,
                "inactive_session_count": 0,
                "token_session": {
                    "token_session_id": "oauthsid_owner_001",
                    "user_id": "user_owner_001",
                    "workspace_id": "workspace_001",
                    "status": "active",
                    "issued_at": _NOW.isoformat(),
                    "expires_at": (_NOW + timedelta(hours=1)).isoformat(),
                },
            },
        )
        self.assertEqual(directory.__dict__, directory_state)
        self.assertEqual(repository.commit_count, 1)
        self.assertEqual(repository.rollback_count, 0)
        self.assertEqual(len(repository.audits), 1)
        self.assertEqual(repository.audits[0].timestamp, _NOW.isoformat())
        self.assertEqual(
            datetime.fromisoformat(repository.audits[0].timestamp).utcoffset(),
            timedelta(0),
        )
        for timestamp_field in ("issued_at", "expires_at"):
            self.assertEqual(
                datetime.fromisoformat(result["token_session"][timestamp_field]).utcoffset(),
                timedelta(0),
            )

    def test_token_lookup_remaps_utcoffset_failure_without_state_change_or_leak(
        self,
    ) -> None:
        private_detail = "private-utcoffset-backend-detail"
        repository, directory = _fixture()
        baseline = repository.snapshot_state()
        directory_state = dict(directory.__dict__)
        malicious_now = datetime(
            2026,
            7,
            12,
            16,
            0,
            tzinfo=_ExplodingUtcoffsetTimezone(private_detail),
        )

        with self.assertRaises(OperatorDirectoryError) as invalid:
            directory.lookup_token_session(
                user_id="user_owner_001",
                workspace_id="workspace_001",
                operator_service_id="operator_trusted",
                now=malicious_now,
            )

        self.assertIs(type(invalid.exception), OperatorDirectoryError)
        self.assertEqual(invalid.exception.args, ("operator_lookup_invalid",))
        self.assertEqual(invalid.exception.code, "operator_lookup_invalid")
        self.assertEqual(str(invalid.exception), "operator_lookup_invalid")
        self.assertNotIn(private_detail, repr(invalid.exception))
        self.assertTrue(invalid.exception.__suppress_context__)
        self.assertEqual(repository.snapshot_state(), baseline)
        self.assertEqual(repository.calls, [])
        self.assertEqual(repository.commit_count, 0)
        self.assertEqual(repository.rollback_count, 0)
        self.assertEqual(repository.audits, [])
        self.assertEqual(directory.__dict__, directory_state)

    def test_token_lookup_remaps_astimezone_failure_without_state_change_or_leak(
        self,
    ) -> None:
        private_detail = "private-astimezone-backend-detail"
        repository, directory = _fixture()
        baseline = repository.snapshot_state()
        directory_state = dict(directory.__dict__)
        malicious_timezone = _ExplodingAstimezoneTimezone(private_detail)
        malicious_now = datetime(
            2026,
            7,
            12,
            16,
            0,
            tzinfo=malicious_timezone,
        )

        with self.assertRaises(OperatorDirectoryError) as invalid:
            directory.lookup_token_session(
                user_id="user_owner_001",
                workspace_id="workspace_001",
                operator_service_id="operator_trusted",
                now=malicious_now,
            )

        self.assertEqual(malicious_timezone.utcoffset_call_count, 2)
        self.assertIs(type(invalid.exception), OperatorDirectoryError)
        self.assertEqual(invalid.exception.args, ("operator_lookup_invalid",))
        self.assertEqual(invalid.exception.code, "operator_lookup_invalid")
        self.assertEqual(str(invalid.exception), "operator_lookup_invalid")
        self.assertNotIn(private_detail, repr(invalid.exception))
        self.assertTrue(invalid.exception.__suppress_context__)
        self.assertEqual(repository.snapshot_state(), baseline)
        self.assertEqual(repository.calls, [])
        self.assertEqual(repository.commit_count, 0)
        self.assertEqual(repository.rollback_count, 0)
        self.assertEqual(repository.audits, [])
        self.assertEqual(directory.__dict__, directory_state)

    def test_membership_removal_revokes_sessions_and_restore_keeps_them_revoked(self) -> None:
        repository, directory = _fixture()
        member_session = _add_connected_user(repository)

        removed = directory.remove_workspace_member(
            user_id=member_session.user_id,
            workspace_id=member_session.current_workspace_id,
            operator_service_id="operator_trusted",
            now=_NOW,
        )

        self.assertEqual(
            removed,
            {
                "status": "ok",
                "membership_removed": True,
                "user_id": "user_member_001",
                "workspace_id": "workspace_001",
            },
        )
        self.assertIsNone(
            repository.get_active_workspace_member("user_member_001", "workspace_001")
        )
        removed_membership = repository.get_removed_workspace_member(
            "user_member_001",
            "workspace_001",
        )
        self.assertIsNotNone(removed_membership)
        self.assertEqual(removed_membership.role, "member")
        revoked_session = next(
            session
            for session in repository.sessions
            if session.token_session_id == member_session.token_session_id
        )
        self.assertEqual(revoked_session.revoked_at, _NOW.isoformat())
        self.assertEqual(
            revoked_session.revocation_reason,
            "workspace_membership_removed",
        )
        self.assertIsNone(repository.sessions[0].revoked_at)
        removal_audit = repository.audits[-1]
        self.assertEqual(removal_audit.actor_type, "service")
        self.assertEqual(removal_audit.actor_service_id, "operator_trusted")
        self.assertEqual(removal_audit.action, "operator_workspace_member_remove")
        self.assertEqual(removal_audit.status, "ok")
        self.assertEqual(removal_audit.reason_code, "operator_directory_allowed")
        self.assertEqual(
            removal_audit.metadata,
            {
                "event_stage": "operator_directory",
                "operation": "operator_workspace_member_remove",
                "membership_role": "member",
                "membership_state": "removed",
                "revoked_token_session_count": 1,
            },
        )

        restarted_removed_directory = OperatorDirectory(
            repository=repository,
            expected_operator_service_id="operator_trusted",
        )
        with self.assertRaises(OperatorDirectoryError) as removed_session:
            restarted_removed_directory.lookup_token_session(
                user_id="user_member_001",
                workspace_id="workspace_001",
                operator_service_id="operator_trusted",
                now=_NOW + timedelta(seconds=30),
            )
        self.assertEqual(
            removed_session.exception.code,
            "operator_user_membership_not_found",
        )

        restored = restarted_removed_directory.restore_workspace_member(
            user_id="user_member_001",
            workspace_id="workspace_001",
            operator_service_id="operator_trusted",
            now=_NOW + timedelta(minutes=1),
        )

        self.assertEqual(restored["membership_restored"], True)
        self.assertEqual(restored["role"], "member")
        restore_audit = repository.audits[-1]
        self.assertEqual(restore_audit.actor_type, "service")
        self.assertEqual(restore_audit.actor_service_id, "operator_trusted")
        self.assertEqual(restore_audit.action, "operator_workspace_member_restore")
        self.assertEqual(restore_audit.status, "ok")
        self.assertEqual(restore_audit.reason_code, "operator_directory_allowed")
        self.assertEqual(
            restore_audit.metadata,
            {
                "event_stage": "operator_directory",
                "operation": "operator_workspace_member_restore",
                "membership_role": "member",
                "membership_state": "active",
            },
        )
        self.assertIsNotNone(
            repository.get_active_workspace_member("user_member_001", "workspace_001")
        )
        self.assertIsNone(
            repository.get_removed_workspace_member("user_member_001", "workspace_001")
        )
        still_revoked = next(
            session
            for session in repository.sessions
            if session.token_session_id == member_session.token_session_id
        )
        self.assertEqual(still_revoked.revoked_at, _NOW.isoformat())
        restarted_restored_directory = OperatorDirectory(
            repository=repository,
            expected_operator_service_id="operator_trusted",
        )
        with self.assertRaises(OperatorDirectoryError) as old_session:
            restarted_restored_directory.lookup_token_session(
                user_id="user_member_001",
                workspace_id="workspace_001",
                operator_service_id="operator_trusted",
                now=_NOW + timedelta(minutes=2),
            )
        self.assertEqual(old_session.exception.code, "operator_token_session_not_found")

        fresh_session = replace(
            member_session,
            token_session_id="oauthsid_user_member_001_relinked",
            token_jti_hash="sha256:" + "e" * 64,
            issued_at=(_NOW + timedelta(minutes=3)).isoformat(),
            expires_at=(_NOW + timedelta(hours=1)).isoformat(),
            revoked_at=None,
            revocation_reason=None,
        )
        repository.sessions.append(fresh_session)
        relinked = restarted_restored_directory.lookup_token_session(
            user_id="user_member_001",
            workspace_id="workspace_001",
            operator_service_id="operator_trusted",
            now=_NOW + timedelta(minutes=3),
        )
        self.assertEqual(
            relinked["token_session"]["token_session_id"],
            fresh_session.token_session_id,
        )
        self.assertEqual(relinked["inactive_session_count"], 1)
        self.assertEqual(
            [(audit.action, audit.status, audit.reason_code) for audit in repository.audits],
            [
                (
                    "operator_workspace_member_remove",
                    "ok",
                    "operator_directory_allowed",
                ),
                (
                    "operator_token_session_lookup",
                    "denied",
                    "operator_user_membership_not_found",
                ),
                (
                    "operator_workspace_member_restore",
                    "ok",
                    "operator_directory_allowed",
                ),
                (
                    "operator_token_session_lookup",
                    "denied",
                    "operator_token_session_not_found",
                ),
                (
                    "operator_token_session_lookup",
                    "ok",
                    "operator_directory_allowed",
                ),
            ],
        )
        rendered = json.dumps(
            {
                "removed": removed,
                "restored": restored,
                "relinked": relinked,
                "audits": [audit.to_dict() for audit in repository.audits],
            },
            sort_keys=True,
        )
        for forbidden in (
            member_session.token_jti_hash,
            fresh_session.token_jti_hash,
            member_session.external_identity_id,
            member_session.oauth_client_authorization_id,
            member_session.resource,
            "private-google-user_member_001",
            "user_member_001@example.test",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_membership_removal_denials_are_audited_without_mutation(self) -> None:
        repository, directory = _fixture()
        member_session = _add_connected_user(repository)

        with self.assertRaises(OperatorDirectoryError) as unauthorized_restore:
            directory.restore_workspace_member(
                user_id=member_session.user_id,
                workspace_id=member_session.current_workspace_id,
                operator_service_id="operator_removed",
                now=_NOW,
            )
        self.assertEqual(unauthorized_restore.exception.code, "operator_unauthorized")
        self.assertIsNotNone(
            repository.get_active_workspace_member("user_member_001", "workspace_001")
        )
        self.assertEqual(repository.audits[-1].actor_type, "external_unauthenticated")
        self.assertIsNone(repository.audits[-1].actor_service_id)
        self.assertEqual(repository.audits[-1].reason_code, "operator_unauthorized")

        with self.assertRaises(OperatorDirectoryError) as missing_removed_membership:
            directory.restore_workspace_member(
                user_id=member_session.user_id,
                workspace_id=member_session.current_workspace_id,
                operator_service_id="operator_trusted",
                now=_NOW,
            )
        self.assertEqual(
            missing_removed_membership.exception.code,
            "operator_removed_membership_not_found",
        )
        self.assertIsNotNone(
            repository.get_active_workspace_member("user_member_001", "workspace_001")
        )
        self.assertEqual(repository.audits[-1].actor_type, "service")
        self.assertEqual(repository.audits[-1].actor_service_id, "operator_trusted")
        self.assertEqual(repository.audits[-1].status, "denied")
        self.assertEqual(
            repository.audits[-1].reason_code,
            "operator_removed_membership_not_found",
        )

        with self.assertRaises(OperatorDirectoryError) as invalid_restore:
            directory.restore_workspace_member(
                user_id="user/private/path",
                workspace_id="workspace_001",
                operator_service_id="operator_trusted",
                now=_NOW,
            )
        self.assertEqual(invalid_restore.exception.code, "operator_lookup_invalid")
        self.assertEqual(repository.audits[-1].actor_type, "service")
        self.assertEqual(repository.audits[-1].actor_service_id, "operator_trusted")
        self.assertEqual(repository.audits[-1].status, "denied")
        self.assertEqual(repository.audits[-1].reason_code, "operator_lookup_invalid")
        self.assertNotIn("private", str(repository.audits[-1].to_dict()))

        with self.assertRaises(OperatorDirectoryError) as unauthorized:
            directory.remove_workspace_member(
                user_id=member_session.user_id,
                workspace_id=member_session.current_workspace_id,
                operator_service_id="operator_removed",
                now=_NOW,
            )
        self.assertEqual(unauthorized.exception.code, "operator_unauthorized")
        self.assertIsNotNone(
            repository.get_active_workspace_member("user_member_001", "workspace_001")
        )
        self.assertIsNone(repository.sessions[-1].revoked_at)
        self.assertEqual(repository.audits[-1].actor_type, "external_unauthenticated")
        self.assertIsNone(repository.audits[-1].actor_service_id)
        self.assertEqual(repository.audits[-1].reason_code, "operator_unauthorized")

        with self.assertRaises(OperatorDirectoryError) as invalid:
            directory.remove_workspace_member(
                user_id="user/private/path",
                workspace_id="workspace_001",
                operator_service_id="operator_trusted",
                now=_NOW,
            )
        self.assertEqual(invalid.exception.code, "operator_lookup_invalid")
        self.assertEqual(repository.audits[-1].actor_type, "service")
        self.assertEqual(repository.audits[-1].actor_service_id, "operator_trusted")
        self.assertEqual(repository.audits[-1].status, "denied")
        self.assertEqual(repository.audits[-1].reason_code, "operator_lookup_invalid")
        self.assertNotIn("private", str(repository.audits[-1].to_dict()))

        last_owner_repository, last_owner_directory = _fixture()
        with self.assertRaises(OperatorDirectoryError) as last_owner:
            last_owner_directory.remove_workspace_member(
                user_id="user_owner_001",
                workspace_id="workspace_001",
                operator_service_id="operator_trusted",
                now=_NOW,
            )
        self.assertEqual(
            last_owner.exception.code,
            "operator_last_owner_removal_denied",
        )
        self.assertIsNotNone(
            last_owner_repository.get_active_workspace_member(
                "user_owner_001",
                "workspace_001",
            )
        )
        self.assertIsNone(last_owner_repository.sessions[0].revoked_at)
        self.assertEqual(last_owner_repository.audits[-1].actor_type, "service")
        self.assertEqual(
            last_owner_repository.audits[-1].reason_code,
            "operator_last_owner_removal_denied",
        )

    def test_membership_mutation_rolls_back_when_audit_write_fails(self) -> None:
        repository, directory = _fixture()
        _add_connected_user(repository)
        baseline = repository.snapshot_state()
        repository.audit_failure = RuntimeError("private audit backend failure")

        with self.assertRaises(OperatorDirectoryError) as removal_failed:
            directory.remove_workspace_member(
                user_id="user_member_001",
                workspace_id="workspace_001",
                operator_service_id="operator_trusted",
                now=_NOW,
            )

        self.assertEqual(removal_failed.exception.code, "operator_directory_unavailable")
        self.assertEqual(repository.snapshot_state(), baseline)
        self.assertGreaterEqual(repository.rollback_count, 1)

        repository.audit_failure = None
        directory.remove_workspace_member(
            user_id="user_member_001",
            workspace_id="workspace_001",
            operator_service_id="operator_trusted",
            now=_NOW,
        )
        removed_state = repository.snapshot_state()
        repository.audit_failure = RuntimeError("private audit backend failure")
        with self.assertRaises(OperatorDirectoryError) as restore_failed:
            directory.restore_workspace_member(
                user_id="user_member_001",
                workspace_id="workspace_001",
                operator_service_id="operator_trusted",
                now=_NOW + timedelta(minutes=1),
            )
        self.assertEqual(restore_failed.exception.code, "operator_directory_unavailable")
        self.assertEqual(repository.snapshot_state(), removed_state)
        self.assertIsNone(
            repository.get_active_workspace_member("user_member_001", "workspace_001")
        )
        self.assertIsNotNone(
            repository.get_removed_workspace_member("user_member_001", "workspace_001")
        )

    def test_backend_failure_and_invalid_identifiers_return_only_safe_codes(self) -> None:
        repository, directory = _fixture()
        with self.assertRaises(OperatorDirectoryError) as invalid:
            directory.list_token_sessions(
                user_id="user/private/path",
                workspace_id="workspace_001",
                operator_service_id="operator_trusted",
                now=_NOW,
            )
        self.assertEqual(invalid.exception.code, "operator_lookup_invalid")
        self.assertNotIn("private", str(invalid.exception))

        repository.failure = RuntimeError("SELECT bearer_jti FROM private_backend")
        with self.assertRaises(OperatorDirectoryError) as failed:
            directory.list_users(
                workspace_id="workspace_001",
                operator_service_id="operator_trusted",
            )
        self.assertEqual(failed.exception.code, "operator_directory_unavailable")
        self.assertNotIn("SELECT", str(failed.exception))
        self.assertNotIn("bearer", str(failed.exception))

        repository.failure = None
        repository.audit_failure = RuntimeError("audit backend secret path /private/audit")
        audit_count = len(repository.audits)
        with self.assertRaises(OperatorDirectoryError) as audit_failed:
            directory.list_users(
                workspace_id="workspace_001",
                operator_service_id="operator_trusted",
            )
        self.assertEqual(audit_failed.exception.code, "operator_directory_unavailable")
        self.assertEqual(len(repository.audits), audit_count)
        self.assertGreaterEqual(repository.rollback_count, 1)
        self.assertNotIn("secret", str(audit_failed.exception))
        self.assertNotIn("/private", str(audit_failed.exception))

    def test_operator_runbook_uses_governed_cli_not_identifier_as_remote_credential(self) -> None:
        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text(encoding="utf-8")
        runbook = (root / "docs/closed-beta-runbook.md").read_text(encoding="utf-8")

        for document in (readme, runbook):
            self.assertIn("lookup-user", document)
            self.assertIn("list-users", document)
            self.assertIn("invite-user", document)
            self.assertIn("remove-workspace-member", document)
            self.assertIn("restore-workspace-member", document)
            self.assertIn("lookup-token-session", document)
            self.assertIn("list-token-sessions", document)
            self.assertIn("not a password", document)
            self.assertIn("deployment shell", document)
            self.assertIn("not MCP", document)
            self.assertIn("audit", document)
        self.assertNotIn("query_postgres_raw", runbook)
        self.assertNotIn("SELECT * FROM formowl", runbook)


if __name__ == "__main__":
    unittest.main()
