from __future__ import annotations

import json
import unittest

import _paths  # noqa: F401
from formowl_contract import PermissionScope, SourceRef
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


class MailExtractionTests(unittest.TestCase):
    def test_mail_archive_fixture_preserves_message_attachment_and_occurrence_identity(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("mail-extraction")
        source_path = temp_dir / "incoming" / "mail-archive.json"
        source_path.parent.mkdir(parents=True)
        archive = {
            "archive_id": "archive_001",
            "mailbox_id": "mailbox_yifan",
            "folders": [
                {
                    "folder_path_hash": "sha256:folder-inbox",
                    "label": "Inbox",
                }
            ],
            "messages": [
                {
                    "message_id": "<msg-001@example.test>",
                    "folder_path_hash": "sha256:folder-inbox",
                    "subject": "Launch checklist",
                    "sender": "pm@example.test",
                    "sent_at": "2026-06-17T10:00:00+00:00",
                    "body": "Review source preservation.\n\nConfirm audit records.",
                    "body_hash": "sha256:body001",
                    "attachments": [
                        {
                            "attachment_id": "att_001",
                            "filename": "brief.pdf",
                            "mime_type": "application/pdf",
                            "content_hash": "sha256:attachment001",
                            "size_bytes": 128,
                        }
                    ],
                }
            ],
        }
        source_path.write_text(json.dumps(archive, sort_keys=True), encoding="utf-8")
        registry = StorageBackendRegistry(temp_dir)
        backend = registry.register_local_backend(
            temp_dir / "object-root",
            workspace_scope="workspace_formowl",
        )
        object_store = FileObjectStore(registry)
        source_ref = SourceRef(
            source_system="local",
            source_type="mail_archive",
            source_id="mail-archive.json",
        )
        asset = register_asset_from_local_file(
            source_path,
            object_store=object_store,
            asset_store=AssetStore(temp_dir),
            storage_backend_id=backend.storage_backend_id,
            workspace_id="workspace_formowl",
            owner_user_id="user_yifan",
            permission_scope=PermissionScope.project("project_formowl"),
            source_ref=source_ref,
            mime_type="application/vnd.formowl.mail-archive+json",
            created_at="2026-06-17T10:00:00+00:00",
            registered_at="2026-06-17T10:00:00+00:00",
        )

        stored = run_extractor(
            asset=asset,
            object_store=object_store,
            extractor_run_store=ExtractorRunStore(temp_dir),
            observation_store=ObservationStore(temp_dir),
            adapter=FixtureMailArchiveExtractor(),
            started_at="2026-06-17T10:01:00+00:00",
            completed_at="2026-06-17T10:01:00+00:00",
        )

        by_type = _observations_by_type(stored.observations)
        self.assertEqual(stored.extractor_run.status, "succeeded")
        self.assertEqual(stored.extractor_run.extractor_type, "mail_archive")
        self.assertEqual(len(by_type["mail_folder_occurrence"]), 1)
        self.assertEqual(len(by_type["email_message"]), 1)
        self.assertEqual(len(by_type["email_body_segment"]), 2)
        self.assertEqual(len(by_type["email_attachment_occurrence"]), 1)

        message = by_type["email_message"][0]
        attachment = by_type["email_attachment_occurrence"][0]
        self.assertEqual(message.location["archive_id"], "archive_001")
        self.assertEqual(message.location["mailbox_id"], "mailbox_yifan")
        self.assertEqual(message.location["folder_path_hash"], "sha256:folder-inbox")
        self.assertEqual(message.location["message_id"], "<msg-001@example.test>")
        self.assertEqual(attachment.location["attachment_id"], "att_001")
        self.assertEqual(attachment.payload["content_hash"], "sha256:attachment001")
        self.assertEqual(attachment.payload["source_ref"], source_ref.to_dict())
        self.assertNotIn(str(source_path), json.dumps(attachment.to_dict(), sort_keys=True))

        persisted = ObservationStore(temp_dir).get(attachment.observation_id)
        self.assertEqual(persisted.to_dict(), attachment.to_dict())


def _observations_by_type(observations):
    by_type = {}
    for observation in observations:
        by_type.setdefault(observation.observation_type, []).append(observation)
    return by_type


if __name__ == "__main__":
    unittest.main()
