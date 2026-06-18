from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_contract import (
    AccessRequest,
    AuditLog,
    ContractValidationError,
    Grant,
    SessionIdentity,
    User,
    WorkspaceMember,
)


class IdentityContractTests(unittest.TestCase):
    def test_identity_access_and_audit_models_round_trip(self) -> None:
        created_at = "2026-06-17T10:00:00+00:00"

        models = [
            User(
                user_id="user_yifan",
                display_name="Yifan Chen",
                email="yifan@example.test",
                status="active",
                created_at=created_at,
            ),
            SessionIdentity(
                session_id="session_001",
                selected_user_id="user_yifan",
                selected_at=created_at,
                selection_method="manual_trusted_internal",
            ),
            WorkspaceMember(
                workspace_id="workspace_formowl",
                user_id="user_yifan",
                role="owner",
            ),
            AccessRequest(
                request_id="access_req_001",
                requester_user_id="user_ren",
                owner_user_id="user_yifan",
                requested_scope_type="asset",
                requested_scope_id="asset_001",
                requested_access_level="evidence_snippet",
                reason="Need a cited snippet for project status review.",
                status="pending",
                created_at=created_at,
            ),
            Grant(
                grant_id="grant_001",
                owner_user_id="user_yifan",
                grantee_user_id="user_ren",
                scope_type="asset",
                scope_id="asset_001",
                permission="evidence_snippet",
                expires_at="2026-06-18T10:00:00+00:00",
                max_access_count=3,
            ),
            AuditLog(
                audit_log_id="audit_001",
                actor_user_id="user_yifan",
                action="grant_created",
                target_type="grant",
                target_id="grant_001",
                grant_id="grant_001",
                session_id="session_001",
                workspace_id="workspace_formowl",
                status="ok",
                timestamp=created_at,
                metadata={"request_id": "access_req_001"},
            ),
        ]

        for model in models:
            data = model.to_dict()
            round_tripped = type(model).from_dict(data).to_dict()
            self.assertEqual(round_tripped, data)

    def test_identity_contract_to_dict_validates_enums_and_required_fields(self) -> None:
        created_at = "2026-06-17T10:00:00+00:00"

        with self.assertRaises(ContractValidationError):
            User(
                user_id="user_yifan",
                display_name="Yifan Chen",
                status="pending",
                created_at=created_at,
            ).to_dict()

        with self.assertRaises(ContractValidationError):
            SessionIdentity(
                session_id="session_001",
                selected_user_id="user_yifan",
                selected_at=created_at,
                selection_method="oidc",
            ).to_dict()

        with self.assertRaises(ContractValidationError):
            WorkspaceMember(
                workspace_id="workspace_formowl",
                user_id="user_yifan",
                role="admin",
            ).to_dict()

        with self.assertRaises(ContractValidationError):
            AccessRequest(
                request_id="access_req_001",
                requester_user_id="user_ren",
                owner_user_id="user_yifan",
                requested_scope_type="asset",
                requested_scope_id="asset_001",
                requested_access_level="evidence_snippet",
                reason="Need a cited snippet for project status review.",
                status="cancelled",
                created_at=created_at,
            ).to_dict()

    def test_identity_contract_validates_numeric_and_metadata_fields(self) -> None:
        created_at = "2026-06-17T10:00:00+00:00"

        with self.assertRaises(ContractValidationError):
            Grant(
                grant_id="grant_001",
                owner_user_id="user_yifan",
                grantee_user_id="user_ren",
                scope_type="asset",
                scope_id="asset_001",
                permission="evidence_snippet",
                expires_at="2026-06-18T10:00:00+00:00",
                max_access_count=-1,
            ).to_dict()

        with self.assertRaises(ContractValidationError):
            AuditLog(
                audit_log_id="audit_001",
                actor_user_id="user_yifan",
                action="grant_created",
                target_type="grant",
                target_id="grant_001",
                session_id="session_001",
                timestamp=created_at,
                metadata="access_req_001",
            ).to_dict()


if __name__ == "__main__":
    unittest.main()
