from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_auth import FileAuditLogStore, ManualTrustedInternalAuthProvider
from formowl_contract import AccessRequest, Grant, User, WorkspaceMember


class ManualTrustedInternalAuthProviderTests(unittest.TestCase):
    def test_select_actor_and_whoami_return_non_production_actor_context(self) -> None:
        temp_dir = _paths.fresh_test_dir("manual-auth-provider")
        audit_store = FileAuditLogStore(temp_dir)
        created_at = "2026-06-17T10:00:00+00:00"
        user = User(
            user_id="user_yifan",
            display_name="Yifan Chen",
            email="yifan@example.test",
            status="active",
            created_at=created_at,
        )
        provider = ManualTrustedInternalAuthProvider(
            users=[
                user,
                User(
                    user_id="user_disabled",
                    display_name="Disabled User",
                    status="disabled",
                    created_at=created_at,
                ),
            ],
            workspace_memberships=[
                WorkspaceMember(
                    workspace_id="workspace_formowl",
                    user_id="user_yifan",
                    role="owner",
                )
            ],
            grants=[
                Grant(
                    grant_id="grant_001",
                    owner_user_id="user_owner",
                    grantee_user_id="user_yifan",
                    scope_type="asset",
                    scope_id="asset_001",
                    permission="evidence_snippet",
                    expires_at="2026-06-18T10:00:00+00:00",
                )
            ],
            access_requests=[
                AccessRequest(
                    request_id="access_req_001",
                    requester_user_id="user_ren",
                    owner_user_id="user_yifan",
                    requested_scope_type="asset",
                    requested_scope_id="asset_002",
                    requested_access_level="answer_only",
                    reason="Need a status answer.",
                    status="pending",
                    created_at=created_at,
                )
            ],
            audit_store=audit_store,
        )

        context = provider.select_actor(
            "Yifan Chen",
            session_id="session_001",
            selected_at=created_at,
        )

        self.assertEqual(provider.whoami(), context)
        self.assertEqual(context.user.to_dict(), user.to_dict())
        self.assertEqual(context.session_identity.selected_user_id, "user_yifan")
        self.assertEqual(context.session_identity.selection_method, "manual_trusted_internal")
        self.assertEqual(context.workspace_memberships[0].workspace_id, "workspace_formowl")
        self.assertEqual(context.active_grants[0].grant_id, "grant_001")
        self.assertEqual(context.pending_access_requests[0].request_id, "access_req_001")
        self.assertFalse(context.production_authentication)
        self.assertIn("not production authentication", context.authentication_note)

        audit_logs = audit_store.list()
        self.assertEqual(len(audit_logs), 1)
        self.assertEqual(audit_logs[0].action, "actor_selected")
        self.assertEqual(audit_logs[0].actor_user_id, "user_yifan")
        self.assertEqual(audit_logs[0].workspace_id, "workspace_formowl")
        self.assertEqual(audit_logs[0].status, "ok")
        self.assertEqual(audit_logs[0].timestamp, created_at)

        with self.assertRaises(KeyError):
            provider.select_actor("Disabled User")


if __name__ == "__main__":
    unittest.main()
