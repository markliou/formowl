from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_contract import (
    Asset,
    AuditLog,
    CandidateAtom,
    CandidateRelation,
    ContractValidationError,
    ExternalGraphImport,
    SemanticMetadata,
    SourceRef,
    UploadSession,
    User,
)


class ContractEdgeCaseTests(unittest.TestCase):
    def test_candidate_atom_rejects_invalid_provenance_identity_and_review_fields(self) -> None:
        cases = [
            ("candidate_atom_id", 123),
            ("source_observation_ids", []),
            ("source_observation_ids", ["obs_001", 2]),
            ("source_semantic_metadata_ids", ["sem_001", 2]),
            ("atom_type", ["decision"]),
            ("label", {"text": "Decision"}),
            ("properties", []),
            ("confidence", "0.8"),
            ("confidence", 1.1),
            ("extractor_run_id", 123),
            ("status", "canonical"),
            ("requires_review", "yes"),
            ("created_at", 123),
        ]

        for field_name, invalid_value in cases:
            payload = _valid_candidate_atom()
            payload[field_name] = invalid_value
            with self.subTest(field_name=field_name, invalid_value=invalid_value):
                with self.assertRaises(ContractValidationError):
                    CandidateAtom.from_dict(payload)

    def test_candidate_relation_rejects_invalid_atom_links_and_payload_fields(self) -> None:
        cases = [
            ("candidate_relation_id", 123),
            ("source_candidate_atom_id", 123),
            ("target_candidate_atom_id", 123),
            ("relation_type", ["supports"]),
            ("source_observation_ids", []),
            ("source_semantic_metadata_ids", [None]),
            ("properties", "not-object"),
            ("confidence", -0.1),
            ("extractor_run_id", {"run": "run_001"}),
            ("status", "merged"),
            ("requires_review", 1),
        ]

        for field_name, invalid_value in cases:
            payload = _valid_candidate_relation()
            payload[field_name] = invalid_value
            with self.subTest(field_name=field_name, invalid_value=invalid_value):
                with self.assertRaises(ContractValidationError):
                    CandidateRelation.from_dict(payload)

    def test_external_graph_import_rejects_invalid_source_lists_and_metadata(self) -> None:
        cases = [
            ("external_graph_import_id", 123),
            ("source_system", 123),
            ("source_ref", {"source_system": "fixture"}),
            ("source_ref", {"source_system": "fixture", "source_type": "graph", "source_id": 1}),
            ("extractor_run_id", 123),
            ("imported_at", 123),
            ("candidate_atom_ids", ["catom_001", 2]),
            ("candidate_relation_ids", [None]),
            ("warnings", ["requires_review", 1]),
            ("errors", [False]),
            ("metadata", []),
        ]

        for field_name, invalid_value in cases:
            payload = _valid_external_graph_import()
            payload[field_name] = invalid_value
            with self.subTest(field_name=field_name, invalid_value=invalid_value):
                with self.assertRaises(ContractValidationError):
                    ExternalGraphImport.from_dict(payload)

    def test_semantic_metadata_rejects_bad_source_confidence_and_review_shape(self) -> None:
        cases = [
            ("semantic_metadata_id", 123),
            ("source_observation_ids", []),
            ("source_observation_ids", ["obs_001", 2]),
            ("metadata_type", ["decision"]),
            ("value", "not-object"),
            ("confidence", "0.5"),
            ("confidence", -0.01),
            ("extractor_run_id", 123),
            ("requires_review", "true"),
            ("created_at", 123),
        ]

        for field_name, invalid_value in cases:
            payload = _valid_semantic_metadata()
            payload[field_name] = invalid_value
            with self.subTest(field_name=field_name, invalid_value=invalid_value):
                with self.assertRaises(ContractValidationError):
                    SemanticMetadata.from_dict(payload)

    def test_identity_audit_and_upload_contracts_reject_silent_string_casts(self) -> None:
        invalid_payloads = [
            (User, {**_valid_user(), "user_id": 123}),
            (User, {**_valid_user(), "email": ["yifan@example.test"]}),
            (AuditLog, {**_valid_audit_log(), "timestamp": 123}),
            (AuditLog, {**_valid_audit_log(), "status": {"state": "ok"}}),
            (UploadSession, {**_valid_upload_session(), "intent": ["Upload notes"]}),
            (UploadSession, {**_valid_upload_session(), "project_id": 123}),
            (
                UploadSession,
                {
                    **_valid_upload_session(),
                    "permission_scope": {"scope_type": "project"},
                },
            ),
            (
                UploadSession,
                {
                    **_valid_upload_session(),
                    "permission_scope": {"scope_type": 123, "visibility": []},
                },
            ),
            (
                UploadSession,
                {
                    **_valid_upload_session(),
                    "permission_scope": {
                        "scope_type": "project",
                        "visibility": "workspace",
                        "scope_id": 123,
                    },
                },
            ),
            (
                UploadSession,
                {
                    **_valid_upload_session(),
                    "permission_scope": {
                        "scope_type": "project",
                        "visibility": "workspace",
                        "inherited_from": [],
                    },
                },
            ),
        ]

        for model_type, payload in invalid_payloads:
            with self.subTest(model_type=model_type.__name__, payload=payload):
                with self.assertRaises(ContractValidationError):
                    model_type.from_dict(payload)

    def test_public_locator_fields_reject_raw_paths(self) -> None:
        invalid_object_uris = [
            r"C:\workspace\object-root\payload.bin",
            "/tmp/object-root/payload.bin",
            "file:///tmp/object-root/payload.bin",
        ]

        for object_uri in invalid_object_uris:
            payload = _valid_asset()
            payload["object_uri"] = object_uri
            with self.subTest(object_uri=object_uri):
                with self.assertRaises(ContractValidationError):
                    Asset.from_dict(payload)


def _valid_candidate_atom() -> dict[str, object]:
    return {
        "candidate_atom_id": "catom_001",
        "source_observation_ids": ["obs_001"],
        "source_semantic_metadata_ids": ["sem_001"],
        "atom_type": "decision",
        "label": "Preserve provenance",
        "properties": {"rationale": "Required for wiki citations"},
        "confidence": 0.8,
        "extractor_run_id": "run_001",
        "status": "pending_review",
        "requires_review": True,
        "created_at": "2026-06-17T10:00:00+00:00",
    }


def _valid_candidate_relation() -> dict[str, object]:
    return {
        "candidate_relation_id": "crel_001",
        "source_candidate_atom_id": "catom_001",
        "target_candidate_atom_id": "catom_002",
        "relation_type": "supports",
        "source_observation_ids": ["obs_001"],
        "source_semantic_metadata_ids": ["sem_001"],
        "properties": {"basis": "same source"},
        "confidence": 0.7,
        "extractor_run_id": "run_001",
        "status": "pending_review",
        "requires_review": True,
        "created_at": "2026-06-17T10:00:00+00:00",
    }


def _valid_external_graph_import() -> dict[str, object]:
    return {
        "external_graph_import_id": "egimp_001",
        "source_system": "fixture_graph_importer",
        "source_ref": SourceRef(
            source_system="fixture_graph_importer",
            source_type="candidate_graph",
            source_id="import_001",
        ).to_dict(),
        "extractor_run_id": "run_001",
        "imported_at": "2026-06-17T10:00:00+00:00",
        "candidate_atom_ids": ["catom_001"],
        "candidate_relation_ids": ["crel_001"],
        "warnings": ["requires_human_review"],
        "errors": [],
        "metadata": {"import_kind": "deterministic_fixture"},
    }


def _valid_semantic_metadata() -> dict[str, object]:
    return {
        "semantic_metadata_id": "sem_001",
        "source_observation_ids": ["obs_001"],
        "metadata_type": "decision",
        "value": {"decision": "Keep observations separate from graph state."},
        "confidence": 0.78,
        "extractor_run_id": "run_001",
        "requires_review": True,
        "created_at": "2026-06-17T10:00:00+00:00",
    }


def _valid_user() -> dict[str, object]:
    return {
        "user_id": "user_yifan",
        "display_name": "Yifan Chen",
        "email": "yifan@example.test",
        "status": "active",
        "created_at": "2026-06-17T10:00:00+00:00",
    }


def _valid_audit_log() -> dict[str, object]:
    return {
        "audit_log_id": "audit_001",
        "actor_user_id": "user_yifan",
        "action": "asset_registered",
        "target_type": "asset",
        "target_id": "asset_001",
        "session_id": "session_001",
        "workspace_id": "workspace_formowl",
        "status": "ok",
        "timestamp": "2026-06-17T10:00:00+00:00",
    }


def _valid_upload_session() -> dict[str, object]:
    return {
        "upload_session_id": "upload_001",
        "actor_user_id": "user_yifan",
        "workspace_id": "workspace_formowl",
        "owner_scope_type": "project",
        "owner_scope_id": "project_formowl",
        "intent": "Upload source notes.",
        "intended_asset_type": "document",
        "ingestion_profile": "plain_text",
        "visibility_scope": "workspace",
        "permission_scope": {"scope_type": "project", "visibility": "workspace"},
        "expires_at": "2026-06-18T10:00:00+00:00",
        "source_preparation_state": "not_started",
        "processing_status": "waiting_for_upload",
        "status": "pending",
        "created_at": "2026-06-17T10:00:00+00:00",
        "audit_log_id": "audit_001",
        "project_id": "project_formowl",
    }


def _valid_asset() -> dict[str, object]:
    return {
        "asset_id": "asset_001",
        "storage_backend_id": "storage_local_001",
        "object_uri": "formowl://object/storage_local_001/workspace_formowl/hash001",
        "content_hash": "sha256:abc123",
        "file_size": 12,
        "mime_type": "text/plain",
        "created_at": "2026-06-17T10:00:00+00:00",
        "registered_at": "2026-06-17T10:00:00+00:00",
        "owner_user_id": "user_yifan",
        "workspace_id": "workspace_formowl",
        "permission_scope": {"scope_type": "project", "visibility": "workspace"},
        "lifecycle_state": "active",
    }


if __name__ == "__main__":
    unittest.main()
