from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_auth import FileAuditLogStore, ManualTrustedInternalAuthProvider
from formowl_contract import (
    AccessRequest,
    ContractValidationError,
    EvidenceSnapshot,
    Grant,
    PermissionScope,
    SourceRef,
    User,
    WorkspaceMember,
)
from formowl_ingestion.chatgpt import (
    ChatGptSessionCaptureStore,
    capture_current_chatgpt_session,
)
from formowl_ingestion.assets import register_asset_from_local_file
from formowl_ingestion.jobs import create_ingestion_job
from formowl_ingestion.storage import (
    AssetStore,
    FileObjectStore,
    JobStore,
    StorageBackendRegistry,
)
from formowl_ingestion.uploads import upload_asset_reference
from formowl_project_mcp.storage import FileEvidenceSnapshotStore


class WorkflowEdgeCaseTests(unittest.TestCase):
    def test_manual_auth_provider_selects_by_email_or_user_id_and_filters_context(self) -> None:
        created_at = "2026-06-17T10:00:00+00:00"
        user = User(
            user_id="user_yifan",
            display_name="Yifan Chen",
            email="yifan@example.test",
            status="active",
            created_at=created_at,
        )
        provider = ManualTrustedInternalAuthProvider(
            users=[user],
            workspace_memberships=[
                WorkspaceMember(
                    workspace_id="workspace_formowl",
                    user_id="user_yifan",
                    role="owner",
                )
            ],
            grants=[
                Grant(
                    grant_id="grant_active",
                    owner_user_id="user_owner",
                    grantee_user_id="user_yifan",
                    scope_type="asset",
                    scope_id="asset_001",
                    permission="evidence_snippet",
                    expires_at="2026-06-18T10:00:00+00:00",
                ),
                Grant(
                    grant_id="grant_revoked",
                    owner_user_id="user_owner",
                    grantee_user_id="user_yifan",
                    scope_type="asset",
                    scope_id="asset_002",
                    permission="evidence_snippet",
                    expires_at="2026-06-18T10:00:00+00:00",
                    revoked_at=created_at,
                ),
                Grant(
                    grant_id="grant_expired",
                    owner_user_id="user_owner",
                    grantee_user_id="user_yifan",
                    scope_type="asset",
                    scope_id="asset_003",
                    permission="evidence_snippet",
                    expires_at="2026-06-17T09:00:00+00:00",
                ),
            ],
            access_requests=[
                AccessRequest(
                    request_id="req_owned",
                    requester_user_id="user_ren",
                    owner_user_id="user_yifan",
                    requested_scope_type="asset",
                    requested_scope_id="asset_001",
                    requested_access_level="answer_only",
                    reason="Need an answer.",
                    status="pending",
                    created_at=created_at,
                ),
                AccessRequest(
                    request_id="req_requested",
                    requester_user_id="user_yifan",
                    owner_user_id="user_ren",
                    requested_scope_type="asset",
                    requested_scope_id="asset_002",
                    requested_access_level="graph_snippet",
                    reason="Need a graph snippet.",
                    status="pending",
                    created_at=created_at,
                ),
                AccessRequest(
                    request_id="req_approved",
                    requester_user_id="user_yifan",
                    owner_user_id="user_ren",
                    requested_scope_type="asset",
                    requested_scope_id="asset_003",
                    requested_access_level="graph_snippet",
                    reason="Already decided.",
                    status="approved",
                    created_at=created_at,
                ),
            ],
        )

        self.assertIsNone(provider.whoami())
        by_email = provider.select_actor(
            "yifan@example.test",
            session_id="session_email",
            selected_at=created_at,
        )
        by_user_id = provider.select_actor(
            "user_yifan",
            session_id="session_user_id",
            selected_at=created_at,
        )

        self.assertEqual(by_email.user.user_id, "user_yifan")
        self.assertEqual(by_user_id.session_identity.session_id, "session_user_id")
        self.assertEqual(provider.whoami(), by_user_id)
        self.assertEqual([grant.grant_id for grant in by_user_id.active_grants], ["grant_active"])
        self.assertEqual(
            {request.request_id for request in by_user_id.pending_access_requests},
            {"req_owned", "req_requested"},
        )
        self.assertFalse(by_user_id.production_authentication)

    def test_evidence_fetch_requires_full_audit_context_and_records_not_found(self) -> None:
        temp_dir = _paths.fresh_test_dir("workflow-edge-evidence-audit")
        created_at = "2026-06-17T10:00:00+00:00"
        source_ref = SourceRef(
            source_system="openproject",
            source_type="work_package",
            source_id="123",
        )
        evidence_store = FileEvidenceSnapshotStore(temp_dir)
        evidence_store.save_snapshot(
            {
                "snapshot": EvidenceSnapshot(
                    evidence_snapshot_id="ev_001",
                    mcp_server="project-mcp",
                    tool_name="get_work_item_context",
                    captured_at=created_at,
                    permission_scope=PermissionScope.project("project_formowl"),
                    source_refs=[source_ref],
                ),
                "request_payload": {},
                "response_payload": {"ok": True},
                "normalized_markdown": "Evidence",
            }
        )

        audit_store = FileAuditLogStore(temp_dir)
        with self.assertRaises(ValueError):
            evidence_store.get_snapshot(
                "ev_001",
                audit_store=audit_store,
                actor_user_id="user_yifan",
                session_id="session_001",
            )
        with self.assertRaises(ValueError):
            evidence_store.get_snapshot_payload(
                "ev_missing",
                audit_store=audit_store,
                actor_user_id="user_yifan",
                workspace_id="workspace_formowl",
            )

        self.assertIsNone(
            evidence_store.get_snapshot(
                "ev_missing",
                audit_store=audit_store,
                actor_user_id="user_yifan",
                session_id="session_001",
                workspace_id="workspace_formowl",
                timestamp=created_at,
            )
        )
        logs = audit_store.list()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].action, "evidence_fetched")
        self.assertEqual(logs[0].target_id, "ev_missing")
        self.assertEqual(logs[0].status, "not_found")

    def test_upload_asset_reference_rejects_invalid_source_ref_without_asset_or_audit_write(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("workflow-edge-upload-reference-invalid-source")
        source_path = temp_dir / "incoming" / "source.txt"
        source_path.parent.mkdir(parents=True)
        source_path.write_text("Invalid source refs must not register assets.\n", encoding="utf-8")
        object_root = temp_dir / "object-root"
        registry = StorageBackendRegistry(temp_dir)
        backend = registry.register_local_backend(
            object_root,
            workspace_scope="workspace_formowl",
        )
        audit_store = FileAuditLogStore(temp_dir)
        asset_store = AssetStore(temp_dir)

        with self.assertRaises(ContractValidationError):
            upload_asset_reference(
                source_path,
                object_store=FileObjectStore(registry),
                asset_store=asset_store,
                audit_store=audit_store,
                storage_backend_id=backend.storage_backend_id,
                workspace_id="workspace_formowl",
                owner_user_id="user_yifan",
                actor_user_id="user_yifan",
                session_id="session_001",
                permission_scope=PermissionScope.project("project_formowl"),
                source_ref={"source_system": "migration"},
                controlled_import_reason="migration test",
                created_at="2026-06-17T10:00:00+00:00",
                registered_at="2026-06-17T10:00:00+00:00",
            )

        self.assertEqual(asset_store.list(), [])
        self.assertEqual(audit_store.list(), [])
        self.assertEqual(list(object_root.glob("objects/**/payload.bin")), [])
        self.assertEqual(list(object_root.glob("objects/**/metadata.json")), [])

    def test_asset_registration_requires_audit_identity_before_writes(self) -> None:
        invalid_cases = [
            {"actor_user_id": None, "session_id": "session_001"},
            {"actor_user_id": "user_yifan", "session_id": None},
            {"actor_user_id": 123, "session_id": "session_001"},
        ]

        for kwargs in invalid_cases:
            with self.subTest(**kwargs):
                temp_dir = _paths.fresh_test_dir("workflow-edge-asset-audit-identity")
                source_path = temp_dir / "incoming" / "source.txt"
                source_path.parent.mkdir(parents=True)
                source_path.write_text(
                    "Audit identity must exist before asset writes.\n",
                    encoding="utf-8",
                )
                object_root = temp_dir / "object-root"
                registry = StorageBackendRegistry(temp_dir)
                backend = registry.register_local_backend(
                    object_root,
                    workspace_scope="workspace_formowl",
                )
                asset_store = AssetStore(temp_dir)
                audit_store = FileAuditLogStore(temp_dir)

                with self.assertRaises(ValueError):
                    register_asset_from_local_file(
                        source_path,
                        object_store=FileObjectStore(registry),
                        asset_store=asset_store,
                        storage_backend_id=backend.storage_backend_id,
                        workspace_id="workspace_formowl",
                        owner_user_id="user_yifan",
                        permission_scope=PermissionScope.project("project_formowl"),
                        source_ref=SourceRef(
                            source_system="local",
                            source_type="file",
                            source_id="source.txt",
                        ),
                        audit_store=audit_store,
                        actor_user_id=kwargs["actor_user_id"],  # type: ignore[arg-type]
                        session_id=kwargs["session_id"],  # type: ignore[arg-type]
                    )

                self.assertEqual(asset_store.list(), [])
                self.assertEqual(audit_store.list(), [])
                self.assertEqual(list(object_root.glob("objects/**/payload.bin")), [])
                self.assertEqual(list(object_root.glob("objects/**/metadata.json")), [])

    def test_asset_registration_prevalidates_asset_fields_before_object_copy(self) -> None:
        cases = [
            ("direct-created-at", "register_asset", {"created_at": 123}),
            ("direct-empty-created-at", "register_asset", {"created_at": ""}),
            ("direct-empty-registered-at", "register_asset", {"registered_at": ""}),
            ("direct-owner", "register_asset", {"owner_user_id": 123}),
            ("upload-project", "upload_reference", {"project_id": 123}),
            ("upload-empty-registered-at", "upload_reference", {"registered_at": ""}),
        ]

        for case_name, helper_name, invalid_kwargs in cases:
            with self.subTest(case_name=case_name):
                temp_dir = _paths.fresh_test_dir(f"workflow-edge-asset-preflight-{case_name}")
                source_path = temp_dir / "incoming" / "source.txt"
                source_path.parent.mkdir(parents=True)
                source_path.write_text(
                    "Invalid asset fields must not copy bytes.\n",
                    encoding="utf-8",
                )
                object_root = temp_dir / "object-root"
                registry = StorageBackendRegistry(temp_dir)
                backend = registry.register_local_backend(
                    object_root,
                    workspace_scope="workspace_formowl",
                )
                asset_store = AssetStore(temp_dir)
                audit_store = FileAuditLogStore(temp_dir)
                common_kwargs = {
                    "source_path": source_path,
                    "object_store": FileObjectStore(registry),
                    "asset_store": asset_store,
                    "storage_backend_id": backend.storage_backend_id,
                    "workspace_id": "workspace_formowl",
                    "owner_user_id": "user_yifan",
                    "permission_scope": PermissionScope.project("project_formowl"),
                    "source_ref": SourceRef(
                        source_system="local",
                        source_type="file",
                        source_id="source.txt",
                    ),
                }

                with self.assertRaises(ContractValidationError):
                    if helper_name == "register_asset":
                        register_asset_from_local_file(
                            **{**common_kwargs, **invalid_kwargs},
                        )
                    else:
                        upload_asset_reference(
                            source_path,
                            object_store=FileObjectStore(registry),
                            asset_store=asset_store,
                            audit_store=audit_store,
                            storage_backend_id=backend.storage_backend_id,
                            workspace_id="workspace_formowl",
                            owner_user_id="user_yifan",
                            actor_user_id="user_yifan",
                            session_id="session_001",
                            permission_scope=PermissionScope.project("project_formowl"),
                            source_ref=common_kwargs["source_ref"],
                            controlled_import_reason="migration test",
                            **invalid_kwargs,
                        )

                self.assertEqual(asset_store.list(), [])
                self.assertEqual(audit_store.list(), [])
                self.assertEqual(list(object_root.glob("objects/**/payload.bin")), [])
                self.assertEqual(list(object_root.glob("objects/**/metadata.json")), [])

    def test_ingestion_job_creation_rejects_empty_created_at_before_job_write(self) -> None:
        temp_dir = _paths.fresh_test_dir("workflow-edge-job-empty-created-at")
        source_path = temp_dir / "incoming" / "source.txt"
        source_path.parent.mkdir(parents=True)
        source_path.write_text("Empty job timestamps must not create jobs.\n", encoding="utf-8")
        registry = StorageBackendRegistry(temp_dir)
        backend = registry.register_local_backend(
            temp_dir / "object-root",
            workspace_scope="workspace_formowl",
        )
        asset = register_asset_from_local_file(
            source_path,
            object_store=FileObjectStore(registry),
            asset_store=AssetStore(temp_dir),
            storage_backend_id=backend.storage_backend_id,
            workspace_id="workspace_formowl",
            owner_user_id="user_yifan",
            permission_scope=PermissionScope.project("project_formowl"),
            source_ref=SourceRef(
                source_system="local",
                source_type="file",
                source_id="source.txt",
            ),
        )
        job_store = JobStore(temp_dir)
        audit_store = FileAuditLogStore(temp_dir)

        with self.assertRaises(ContractValidationError):
            create_ingestion_job(
                asset=asset,
                job_store=job_store,
                requested_by="user_yifan",
                extractor_names=["plain_text_extractor"],
                created_at="",
                audit_store=audit_store,
                actor_user_id="user_yifan",
                session_id="session_001",
            )

        self.assertEqual(job_store.list(), [])
        self.assertEqual(audit_store.list(), [])

    def test_ingestion_job_creation_requires_audit_identity_before_job_write(self) -> None:
        invalid_cases = [
            {"actor_user_id": None, "session_id": "session_001"},
            {"actor_user_id": "user_yifan", "session_id": None},
            {"actor_user_id": 123, "session_id": "session_001"},
        ]

        for kwargs in invalid_cases:
            with self.subTest(**kwargs):
                temp_dir = _paths.fresh_test_dir("workflow-edge-job-audit-identity")
                source_path = temp_dir / "incoming" / "source.txt"
                source_path.parent.mkdir(parents=True)
                source_path.write_text(
                    "Audit identity must exist before job writes.\n",
                    encoding="utf-8",
                )
                registry = StorageBackendRegistry(temp_dir)
                backend = registry.register_local_backend(
                    temp_dir / "object-root",
                    workspace_scope="workspace_formowl",
                )
                asset = register_asset_from_local_file(
                    source_path,
                    object_store=FileObjectStore(registry),
                    asset_store=AssetStore(temp_dir),
                    storage_backend_id=backend.storage_backend_id,
                    workspace_id="workspace_formowl",
                    owner_user_id="user_yifan",
                    permission_scope=PermissionScope.project("project_formowl"),
                    source_ref=SourceRef(
                        source_system="local",
                        source_type="file",
                        source_id="source.txt",
                    ),
                )
                job_store = JobStore(temp_dir)
                audit_store = FileAuditLogStore(temp_dir)

                with self.assertRaises(ValueError):
                    create_ingestion_job(
                        asset=asset,
                        job_store=job_store,
                        requested_by="user_yifan",
                        extractor_names=["plain_text_extractor"],
                        audit_store=audit_store,
                        actor_user_id=kwargs["actor_user_id"],  # type: ignore[arg-type]
                        session_id=kwargs["session_id"],  # type: ignore[arg-type]
                    )

                self.assertEqual(job_store.list(), [])
                self.assertEqual(audit_store.list(), [])

    def test_chatgpt_session_capture_removes_scratch_file_and_keeps_audited_records(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("workflow-edge-chatgpt-capture-scratch")
        object_root = temp_dir / "object-root"
        registry = StorageBackendRegistry(temp_dir)
        backend = registry.register_local_backend(
            object_root,
            workspace_scope="workspace_formowl",
        )
        audit_store = FileAuditLogStore(temp_dir)
        result = capture_current_chatgpt_session(
            messages=[
                {
                    "message_id": "msg_001",
                    "role": "user",
                    "content": "Capture this session.",
                }
            ],
            capture_store=ChatGptSessionCaptureStore(temp_dir),
            object_store=FileObjectStore(registry),
            asset_store=AssetStore(temp_dir),
            job_store=JobStore(temp_dir),
            audit_store=audit_store,
            storage_backend_id=backend.storage_backend_id,
            actor_user_id="user_yifan",
            session_id="session_001",
            workspace_id="workspace_formowl",
            permission_scope=PermissionScope.project("project_formowl"),
            source_account_id="chatgpt:yifan@example.test",
            visibility_scope="workspace",
            capture_method="manual_export",
            captured_at="2026-06-17T10:00:00+00:00",
            ingested_at="2026-06-17T10:01:00+00:00",
            extractor_names=["plain_text_extractor"],
        )

        scratch_dir = object_root / "scratch" / "chatgpt-session-captures"
        self.assertEqual(list(scratch_dir.glob("*.md")), [])
        self.assertEqual(
            {audit_log.action for audit_log in audit_store.list()},
            {"chatgpt_session_captured", "asset_registered", "ingestion_job_created"},
        )
        self.assertEqual(result.capture.asset_id, result.asset.asset_id)
        self.assertEqual(result.capture.ingestion_job_id, result.ingestion_job.ingestion_job_id)


if __name__ == "__main__":
    unittest.main()
