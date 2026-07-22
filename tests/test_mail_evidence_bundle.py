from __future__ import annotations

import copy
import hashlib
import json
import unittest

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, Observation, PermissionScope, SourceRef
from formowl_ingestion.assets import register_asset_from_local_file
from formowl_ingestion.extraction import run_extractor
from formowl_ingestion.extractors import FixtureMailArchiveExtractor
from formowl_ingestion.storage import (
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    ObservationStore,
    StorageBackendRegistry,
)
from formowl_mail import MailEvidenceBundle, build_mail_evidence_bundle


class MailEvidenceBundleTests(unittest.TestCase):
    def test_fixture_observations_build_phase1_bundle_with_occurrence_preserving_dedup(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-bundle")
        stored = _run_mail_fixture(temp_dir, _duplicate_mail_archive())
        before_bundle_snapshot = _tree_snapshot(temp_dir)

        bundle = build_mail_evidence_bundle(
            stored.observations,
            workspace_id="workspace_formowl",
            owner_user_id="user_yifan",
            source_asset_id=stored.extractor_run.asset_id,
            archive_sha256="sha256:archive-launch",
            producer_type="server_side_parser",
            parser_name="fixture_mail_archive_extractor",
            parser_version="0.1.0",
            upload_session_id="upload_session_mail_001",
            created_at="2026-07-05T10:00:00+00:00",
            started_at="2026-07-05T10:01:00+00:00",
            completed_at="2026-07-05T10:02:00+00:00",
        )
        self.assertEqual(_tree_snapshot(temp_dir), before_bundle_snapshot)
        rebuilt = build_mail_evidence_bundle(
            stored.observations,
            workspace_id="workspace_formowl",
            owner_user_id="user_yifan",
            source_asset_id=stored.extractor_run.asset_id,
            archive_sha256="sha256:archive-launch",
            producer_type="server_side_parser",
            parser_name="fixture_mail_archive_extractor",
            parser_version="0.1.0",
            upload_session_id="upload_session_mail_001",
            created_at="2026-07-05T10:00:00+00:00",
            started_at="2026-07-05T10:01:00+00:00",
            completed_at="2026-07-05T10:02:00+00:00",
        )

        self.assertEqual(bundle.mail_evidence_bundle_id, rebuilt.mail_evidence_bundle_id)
        self.assertEqual(bundle.to_dict(), rebuilt.to_dict())
        self.assertEqual(
            MailEvidenceBundle.from_dict(bundle.to_dict()).to_dict(),
            bundle.to_dict(),
        )
        self.assertEqual(bundle.producer_type, "server_side_parser")
        self.assertEqual(
            bundle.mail_import_session.retention_policy,
            "retain_7_days",
        )
        self.assertEqual(
            bundle.mail_import_session.raw_archive_retention_decision,
            "retained_by_policy",
        )
        self.assertEqual(
            bundle.mail_parse_run.extractor_run_id,
            stored.extractor_run.extractor_run_id,
        )
        self.assertEqual(
            bundle.mail_parse_run.mail_import_session_id,
            bundle.mail_import_session.mail_import_session_id,
        )

        self.assertEqual(len(bundle.archive_occurrences), 1)
        self.assertEqual(len(bundle.folder_occurrences), 2)
        self.assertEqual(len(bundle.messages), 1)
        self.assertEqual(len(bundle.message_occurrences), 2)
        self.assertEqual(len(bundle.body_segments), 2)
        self.assertEqual(len(bundle.attachments), 1)
        self.assertEqual(len(bundle.attachment_occurrences), 2)

        message_id = bundle.messages[0].email_message_id
        occurrence_ids = {
            occurrence.message_occurrence_id for occurrence in bundle.message_occurrences
        }
        self.assertEqual(
            {occurrence.email_message_id for occurrence in bundle.message_occurrences},
            {message_id},
        )
        self.assertEqual(
            {segment.email_message_id for segment in bundle.body_segments},
            {message_id},
        )
        self.assertEqual(
            {segment.message_occurrence_id for segment in bundle.body_segments},
            occurrence_ids,
        )
        self.assertEqual(
            {occurrence.email_message_id for occurrence in bundle.attachment_occurrences},
            {message_id},
        )
        self.assertEqual(
            {occurrence.email_attachment_id for occurrence in bundle.attachment_occurrences},
            {bundle.attachments[0].email_attachment_id},
        )
        self.assertEqual(
            {occurrence.message_occurrence_id for occurrence in bundle.attachment_occurrences},
            occurrence_ids,
        )

        serialized = json.dumps(bundle.to_dict(), sort_keys=True)
        self.assertNotIn(str(temp_dir), serialized)
        self.assertNotIn("object://", serialized)
        self.assertNotIn("postgres://", serialized)
        self.assertNotIn("CandidateAtom", serialized)
        self.assertFalse((temp_dir / "wiki").exists())
        self.assertFalse((temp_dir / "graph").exists())

    def test_producer_locations_emit_the_same_public_bundle_shape(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-bundle-producer-shape")
        stored = _run_mail_fixture(temp_dir, _duplicate_mail_archive())
        bundles = [
            build_mail_evidence_bundle(
                stored.observations,
                workspace_id="workspace_formowl",
                owner_user_id="user_yifan",
                source_asset_id=stored.extractor_run.asset_id,
                archive_sha256="sha256:archive-launch",
                producer_type=producer_type,
                parser_name="fixture_mail_archive_extractor",
                parser_version="0.1.0",
                upload_session_id="upload_session_mail_001",
                created_at="2026-07-05T10:00:00+00:00",
            )
            for producer_type in (
                "server_side_parser",
                "local_companion_parser",
                "fixture_parser",
            )
        ]

        shape = _bundle_shape(bundles[0].to_dict())
        self.assertEqual([_bundle_shape(bundle.to_dict()) for bundle in bundles], [shape] * 3)
        self.assertEqual(
            [len(bundle.messages) for bundle in bundles],
            [1, 1, 1],
        )
        self.assertEqual(
            [len(bundle.message_occurrences) for bundle in bundles],
            [2, 2, 2],
        )
        self.assertEqual(
            [bundle.producer_type for bundle in bundles],
            ["server_side_parser", "local_companion_parser", "fixture_parser"],
        )
        self.assertEqual(
            [bundle.to_dict()["producer_type"] for bundle in bundles],
            ["server_side_parser", "local_companion_parser", "fixture_parser"],
        )

    def test_cross_import_logical_message_ids_are_archive_independent(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-bundle-cross-import")
        archive_a = _duplicate_mail_archive()
        archive_b = _duplicate_mail_archive()
        archive_b["archive_id"] = "archive_launch_second_export"
        archive_b["mailbox_id"] = "mailbox_yifan_second_export"
        stored_a = _run_mail_fixture(temp_dir / "a", archive_a)
        stored_b = _run_mail_fixture(temp_dir / "b", archive_b)

        bundle_a = build_mail_evidence_bundle(
            stored_a.observations,
            workspace_id="workspace_formowl",
            owner_user_id="user_yifan",
            source_asset_id=stored_a.extractor_run.asset_id,
            archive_sha256="sha256:archive-launch-a",
            upload_session_id="upload_session_mail_a",
            created_at="2026-07-05T10:00:00+00:00",
        )
        bundle_b = build_mail_evidence_bundle(
            stored_b.observations,
            workspace_id="workspace_formowl",
            owner_user_id="user_yifan",
            source_asset_id=stored_b.extractor_run.asset_id,
            archive_sha256="sha256:archive-launch-b",
            upload_session_id="upload_session_mail_b",
            created_at="2026-07-05T10:00:00+00:00",
        )

        self.assertEqual(len(bundle_a.messages), 1)
        self.assertEqual(len(bundle_b.messages), 1)
        self.assertEqual(
            bundle_a.messages[0].message_fingerprint,
            bundle_b.messages[0].message_fingerprint,
        )
        self.assertEqual(
            bundle_a.messages[0].email_message_id,
            bundle_b.messages[0].email_message_id,
        )
        self.assertNotEqual(
            bundle_a.archive_occurrences[0].mail_archive_occurrence_id,
            bundle_b.archive_occurrences[0].mail_archive_occurrence_id,
        )

    def test_duplicate_carrier_imports_keep_distinct_import_occurrences(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-bundle-duplicate-carrier")
        stored = _run_mail_fixture(temp_dir, _duplicate_mail_archive())

        bundle_a = build_mail_evidence_bundle(
            stored.observations,
            workspace_id="workspace_formowl",
            owner_user_id="user_yifan",
            source_asset_id=stored.extractor_run.asset_id,
            archive_sha256="sha256:same-archive-bytes",
            upload_session_id="upload_session_mail_a",
            created_at="2026-07-05T10:00:00+00:00",
        )
        bundle_b = build_mail_evidence_bundle(
            stored.observations,
            workspace_id="workspace_formowl",
            owner_user_id="user_yifan",
            source_asset_id=stored.extractor_run.asset_id,
            archive_sha256="sha256:same-archive-bytes",
            upload_session_id="upload_session_mail_b",
            created_at="2026-07-05T10:00:00+00:00",
        )

        self.assertNotEqual(
            bundle_a.mail_import_session.mail_import_session_id,
            bundle_b.mail_import_session.mail_import_session_id,
        )
        self.assertNotEqual(
            bundle_a.archive_occurrences[0].mail_archive_occurrence_id,
            bundle_b.archive_occurrences[0].mail_archive_occurrence_id,
        )
        self.assertEqual(
            {message.email_message_id for message in bundle_a.messages},
            {message.email_message_id for message in bundle_b.messages},
        )
        self.assertEqual(
            {attachment.email_attachment_id for attachment in bundle_a.attachments},
            {attachment.email_attachment_id for attachment in bundle_b.attachments},
        )

    def test_duplicate_folder_occurrences_preserve_source_lineage(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-bundle-duplicate-folder")
        archive = _duplicate_mail_archive()
        archive["folders"].append(
            {"folder_path_hash": "sha256:folder-inbox", "label": "Inbox duplicate export"}
        )
        stored = _run_mail_fixture(temp_dir, archive)

        bundle = build_mail_evidence_bundle(
            stored.observations,
            workspace_id="workspace_formowl",
            owner_user_id="user_yifan",
            source_asset_id=stored.extractor_run.asset_id,
            archive_sha256="sha256:archive-launch",
            upload_session_id="upload_session_mail_001",
            created_at="2026-07-05T10:00:00+00:00",
        )

        inbox_occurrences = [
            folder
            for folder in bundle.folder_occurrences
            if folder.folder_path_hash == "sha256:folder-inbox"
        ]
        self.assertEqual(len(bundle.folder_occurrences), 3)
        self.assertEqual(len(inbox_occurrences), 2)
        self.assertEqual(
            len({folder.mail_folder_occurrence_id for folder in inbox_occurrences}),
            2,
        )
        self.assertEqual(
            len({folder.source_observation_id for folder in inbox_occurrences}),
            2,
        )

    def test_invalid_retention_and_producer_values_are_rejected(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-bundle-invalid-enums")
        stored = _run_mail_fixture(temp_dir, _duplicate_mail_archive())
        base_kwargs = {
            "workspace_id": "workspace_formowl",
            "owner_user_id": "user_yifan",
            "source_asset_id": stored.extractor_run.asset_id,
            "archive_sha256": "sha256:archive-launch",
            "upload_session_id": "upload_session_mail_001",
            "created_at": "2026-07-05T10:00:00+00:00",
        }

        with self.assertRaises(ContractValidationError):
            build_mail_evidence_bundle(
                stored.observations,
                **base_kwargs,
                producer_type="desktop_parser",
            )
        with self.assertRaises(ContractValidationError):
            build_mail_evidence_bundle(
                stored.observations,
                **base_kwargs,
                retention_policy="store_forever_by_default",
            )
        with self.assertRaises(ContractValidationError):
            build_mail_evidence_bundle(
                stored.observations,
                **base_kwargs,
                raw_archive_retention_decision="kept_in_postgresql",
            )

    def test_server_side_parser_requires_upload_session_identity(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-bundle-upload-required")
        stored = _run_mail_fixture(temp_dir, _duplicate_mail_archive())

        with self.assertRaises(ContractValidationError):
            build_mail_evidence_bundle(
                stored.observations,
                workspace_id="workspace_formowl",
                owner_user_id="user_yifan",
                source_asset_id=stored.extractor_run.asset_id,
                archive_sha256="sha256:archive-launch",
                producer_type="server_side_parser",
                created_at="2026-07-05T10:00:00+00:00",
            )

    def test_bundle_from_dict_rejects_missing_required_lineage_arrays(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-bundle-required-arrays")
        stored = _run_mail_fixture(temp_dir, _duplicate_mail_archive())
        bundle = build_mail_evidence_bundle(
            stored.observations,
            workspace_id="workspace_formowl",
            owner_user_id="user_yifan",
            source_asset_id=stored.extractor_run.asset_id,
            archive_sha256="sha256:archive-launch",
            upload_session_id="upload_session_mail_001",
            created_at="2026-07-05T10:00:00+00:00",
        )

        required_arrays = [
            "archive_occurrences",
            "folder_occurrences",
            "messages",
            "message_occurrences",
            "body_segments",
            "attachments",
            "attachment_occurrences",
            "quoted_message_candidates",
            "embedded_message_relations",
        ]
        for field_name in required_arrays:
            with self.subTest(field_name=field_name):
                payload = bundle.to_dict()
                payload.pop(field_name)
                with self.assertRaises(ContractValidationError):
                    MailEvidenceBundle.from_dict(payload)

        payload_without_optional_warnings = bundle.to_dict()
        payload_without_optional_warnings.pop("parse_warnings")
        parsed = MailEvidenceBundle.from_dict(payload_without_optional_warnings)
        self.assertEqual(parsed.parse_warnings, [])

    def test_builder_rejects_empty_mixed_and_orphan_mail_observations(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-bundle-lineage-reject")
        stored = _run_mail_fixture(temp_dir, _duplicate_mail_archive())
        base_kwargs = {
            "workspace_id": "workspace_formowl",
            "owner_user_id": "user_yifan",
            "source_asset_id": stored.extractor_run.asset_id,
            "archive_sha256": "sha256:archive-launch",
            "upload_session_id": "upload_session_mail_001",
            "created_at": "2026-07-05T10:00:00+00:00",
        }

        with self.assertRaises(ContractValidationError):
            build_mail_evidence_bundle([], **base_kwargs)

        mixed = [
            Observation.from_dict(observation.to_dict()) for observation in stored.observations
        ]
        mixed_index = next(
            index
            for index, observation in enumerate(mixed)
            if observation.observation_type == "email_message"
        )
        mixed_payload = mixed[mixed_index].to_dict()
        mixed_payload["location"] = {
            **mixed_payload["location"],
            "archive_id": "archive_other",
        }
        mixed[mixed_index] = Observation.from_dict(mixed_payload)
        with self.assertRaises(ContractValidationError):
            build_mail_evidence_bundle(mixed, **base_kwargs)

        orphan_body = [
            Observation.from_dict(observation.to_dict()) for observation in stored.observations
        ]
        orphan_body_index = next(
            index
            for index, observation in enumerate(orphan_body)
            if observation.observation_type == "email_body_segment"
        )
        orphan_body_payload = orphan_body[orphan_body_index].to_dict()
        orphan_body_payload["location"] = {
            **orphan_body_payload["location"],
            "message_occurrence_id": "mailocc_missing",
        }
        orphan_body[orphan_body_index] = Observation.from_dict(orphan_body_payload)
        with self.assertRaises(ContractValidationError):
            build_mail_evidence_bundle(orphan_body, **base_kwargs)

        orphan_attachment = [
            Observation.from_dict(observation.to_dict()) for observation in stored.observations
        ]
        orphan_attachment_index = next(
            index
            for index, observation in enumerate(orphan_attachment)
            if observation.observation_type == "email_attachment_occurrence"
        )
        orphan_attachment_payload = orphan_attachment[orphan_attachment_index].to_dict()
        orphan_attachment_payload["location"] = {
            **orphan_attachment_payload["location"],
            "message_occurrence_id": "mailocc_missing",
        }
        orphan_attachment[orphan_attachment_index] = Observation.from_dict(
            orphan_attachment_payload
        )
        with self.assertRaises(ContractValidationError):
            build_mail_evidence_bundle(orphan_attachment, **base_kwargs)

    def test_private_body_is_preserved_but_unsafe_envelope_values_are_rejected(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-bundle-raw-reject")
        stored = _run_mail_fixture(temp_dir, _duplicate_mail_archive())
        before_failure_snapshot = _tree_snapshot(temp_dir)
        observations = list(stored.observations)
        body_index = next(
            index
            for index, observation in enumerate(observations)
            if observation.observation_type == "email_body_segment"
        )
        unsafe = Observation.from_dict(
            {
                **observations[body_index].to_dict(),
                "text": "Investigate object://mail/raw/private-archive",
            }
        )
        observations[body_index] = unsafe

        private_bundle = build_mail_evidence_bundle(
            observations,
            workspace_id="workspace_formowl",
            owner_user_id="user_yifan",
            source_asset_id=stored.extractor_run.asset_id,
            archive_sha256="sha256:archive-launch",
            upload_session_id="upload_session_mail_001",
            created_at="2026-07-05T10:00:00+00:00",
        )
        self.assertIn(
            "Investigate object://mail/raw/private-archive",
            [segment.text for segment in private_bundle.body_segments],
        )
        self.assertEqual(_tree_snapshot(temp_dir), before_failure_snapshot)
        with self.assertRaises(ContractValidationError):
            build_mail_evidence_bundle(
                stored.observations,
                workspace_id="workspace_formowl",
                owner_user_id="user_yifan",
                source_asset_id=stored.extractor_run.asset_id,
                archive_sha256="sha256:archive-launch",
                upload_session_id="upload_session_mail_001",
                parse_warnings=["parser saw C:\\private\\archive.pst"],
                created_at="2026-07-05T10:00:00+00:00",
            )
        self.assertEqual(_tree_snapshot(temp_dir), before_failure_snapshot)

        sql_observations = list(stored.observations)
        sql_observations[body_index] = Observation.from_dict(
            {
                **sql_observations[body_index].to_dict(),
                "text": "SELECT * FROM mailbox_messages",
            }
        )
        sql_bundle = build_mail_evidence_bundle(
            sql_observations,
            workspace_id="workspace_formowl",
            owner_user_id="user_yifan",
            source_asset_id=stored.extractor_run.asset_id,
            archive_sha256="sha256:archive-launch",
            upload_session_id="upload_session_mail_001",
            created_at="2026-07-05T10:00:00+00:00",
        )
        self.assertIn(
            "SELECT * FROM mailbox_messages",
            [segment.text for segment in sql_bundle.body_segments],
        )
        self.assertEqual(_tree_snapshot(temp_dir), before_failure_snapshot)

        with self.assertRaises(ContractValidationError):
            build_mail_evidence_bundle(
                stored.observations,
                workspace_id="workspace_formowl",
                owner_user_id="user_yifan",
                source_asset_id=stored.extractor_run.asset_id,
                archive_sha256="sha256:archive-launch",
                upload_session_id="upload_session_mail_001",
                parse_warnings=["parser warning api_key=super-secret-value"],
                created_at="2026-07-05T10:00:00+00:00",
            )
        self.assertEqual(_tree_snapshot(temp_dir), before_failure_snapshot)

        bundle = build_mail_evidence_bundle(
            stored.observations,
            workspace_id="workspace_formowl",
            owner_user_id="user_yifan",
            source_asset_id=stored.extractor_run.asset_id,
            archive_sha256="sha256:archive-launch",
            upload_session_id="upload_session_mail_001",
            created_at="2026-07-05T10:00:00+00:00",
        )
        unsafe_payload = copy.deepcopy(bundle.to_dict())
        unsafe_payload["messages"][0]["api_key"] = "not-public"
        with self.assertRaises(ContractValidationError):
            MailEvidenceBundle.from_dict(unsafe_payload)
        unsafe_segment_payload = copy.deepcopy(bundle.to_dict())
        unsafe_segment_payload["body_segments"][0]["api_key"] = "not-public"
        with self.assertRaises(ContractValidationError):
            MailEvidenceBundle.from_dict(unsafe_segment_payload)
        self.assertEqual(_tree_snapshot(temp_dir), before_failure_snapshot)

        self.assertFalse((temp_dir / "mail").exists())
        self.assertFalse((temp_dir / "graph").exists())
        self.assertFalse((temp_dir / "wiki").exists())


def _run_mail_fixture(temp_dir, archive: dict):
    source_path = temp_dir / "incoming" / "mail-archive.json"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(json.dumps(archive, sort_keys=True), encoding="utf-8")
    registry = StorageBackendRegistry(temp_dir)
    backend = registry.register_local_backend(
        temp_dir / "object-root",
        workspace_scope="workspace_formowl",
    )
    object_store = FileObjectStore(registry)
    asset = register_asset_from_local_file(
        source_path,
        object_store=object_store,
        asset_store=AssetStore(temp_dir),
        storage_backend_id=backend.storage_backend_id,
        workspace_id="workspace_formowl",
        owner_user_id="user_yifan",
        permission_scope=PermissionScope.project("project_formowl"),
        source_ref=SourceRef(
            source_system="local",
            source_type="mail_archive",
            source_id="mail-archive.json",
        ),
        mime_type="application/vnd.formowl.mail-archive+json",
        created_at="2026-06-17T10:00:00+00:00",
        registered_at="2026-06-17T10:00:00+00:00",
    )
    return run_extractor(
        asset=asset,
        object_store=object_store,
        extractor_run_store=ExtractorRunStore(temp_dir),
        observation_store=ObservationStore(temp_dir),
        adapter=FixtureMailArchiveExtractor(),
        started_at="2026-06-17T10:01:00+00:00",
        completed_at="2026-06-17T10:01:00+00:00",
    )


def _duplicate_mail_archive() -> dict:
    return {
        "archive_id": "archive_launch",
        "mailbox_id": "mailbox_yifan",
        "folders": [
            {"folder_path_hash": "sha256:folder-inbox", "label": "Inbox"},
            {"folder_path_hash": "sha256:folder-project", "label": "Project"},
        ],
        "messages": [
            {
                "message_id": "<launch-001@example.test>",
                "thread_id": "thread_launch",
                "folder_path_hash": "sha256:folder-inbox",
                "subject": "Launch checklist",
                "sender": "pm@example.test",
                "sent_at": "2026-06-17T10:00:00+00:00",
                "body": "Update: Launch checklist reviewed",
                "body_hash": "sha256:body-launch",
                "attachments": [
                    {
                        "attachment_id": "att_launch_brief",
                        "filename": "launch-brief.pdf",
                        "mime_type": "application/pdf",
                        "content_hash": "sha256:attachment-launch",
                        "size_bytes": 256,
                    }
                ],
            },
            {
                "message_id": "<launch-001@example.test>",
                "thread_id": "thread_launch",
                "folder_path_hash": "sha256:folder-project",
                "subject": "Re: Launch checklist",
                "sender": "pm@example.test",
                "sent_at": "2026-06-17T10:00:00+00:00",
                "body": "Update: Duplicate folder occurrence retained",
                "body_hash": "sha256:body-launch",
                "attachments": [
                    {
                        "attachment_id": "att_launch_brief",
                        "filename": "launch-brief.pdf",
                        "mime_type": "application/pdf",
                        "content_hash": "sha256:attachment-launch",
                        "size_bytes": 256,
                    }
                ],
            },
        ],
    }


def _bundle_shape(value):
    if isinstance(value, dict):
        return {key: _bundle_shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_bundle_shape(value[0])] if value else []
    return type(value).__name__


def _tree_snapshot(root) -> dict[str, str]:
    root.mkdir(parents=True, exist_ok=True)
    snapshot = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        snapshot[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


if __name__ == "__main__":
    unittest.main()
