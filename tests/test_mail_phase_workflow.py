from __future__ import annotations

import json
import unittest

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, PermissionScope, SourceRef
from formowl_graph.storage import CandidateAtomStore, CandidateRelationStore, SemanticMetadataStore
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
from formowl_mail import (
    MailEvidencePackStore,
    build_case_progress_answer,
    build_mail_evidence_pack,
    build_mail_preflight_readiness_review,
    extract_and_store_mail_candidates,
    search_mail_evidence,
)


class MailPhaseWorkflowTests(unittest.TestCase):
    def test_mail_phase_builds_evidence_candidates_qa_and_preflight_artifact(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-phase-workflow")
        stored = _run_mail_fixture(temp_dir, _mail_archive())
        observations = stored.observations
        by_type = _observations_by_type(observations)

        self.assertEqual(len(by_type["email_thread"]), 1)
        self.assertEqual(len(by_type["email_message"]), 2)
        self.assertGreaterEqual(len(by_type["email_header"]), 8)
        self.assertEqual(len(by_type["email_body_segment"]), 2)
        fingerprints = {item.payload["message_fingerprint"] for item in by_type["email_message"]}
        occurrence_ids = {
            item.payload["message_occurrence_id"] for item in by_type["email_message"]
        }
        self.assertEqual(len(fingerprints), 1)
        self.assertEqual(len(occurrence_ids), 2)

        pack = build_mail_evidence_pack(
            observations,
            created_at="2026-06-30T10:00:00+00:00",
        )
        persisted_pack = MailEvidencePackStore(temp_dir).create(pack)
        self.assertEqual(persisted_pack.to_dict(), pack.to_dict())
        self.assertEqual(
            MailEvidencePackStore(temp_dir).get(pack.mail_evidence_pack_id).to_dict(),
            pack.to_dict(),
        )

        search_results = search_mail_evidence(pack, query="audit approval")
        self.assertEqual(len(search_results), 1)
        self.assertTrue(
            any(
                "Waiting on audit approval" in " ".join(result.snippets)
                for result in search_results
            )
        )

        bridge_result = extract_and_store_mail_candidates(
            observations,
            semantic_metadata_store=SemanticMetadataStore(temp_dir),
            candidate_atom_store=CandidateAtomStore(temp_dir),
            candidate_relation_store=CandidateRelationStore(temp_dir),
            extractor_run_id="mail_candidate_run_001",
            created_at="2026-06-30T10:01:00+00:00",
        )
        atom_types = {atom.atom_type for atom in bridge_result.candidate_atoms}
        self.assertIn("mail_thread", atom_types)
        self.assertIn("status_update", atom_types)
        self.assertIn("blocker", atom_types)
        self.assertIn("next_action", atom_types)
        self.assertIn("deadline", atom_types)
        self.assertTrue(bridge_result.candidate_relations)
        self.assertEqual(
            len(SemanticMetadataStore(temp_dir).list()),
            len(bridge_result.semantic_metadata),
        )
        self.assertEqual(
            len(CandidateAtomStore(temp_dir).list()), len(bridge_result.candidate_atoms)
        )
        self.assertEqual(
            len(CandidateRelationStore(temp_dir).list()),
            len(bridge_result.candidate_relations),
        )

        answer = build_case_progress_answer(
            pack,
            case_id="case_launch",
            generated_at="2026-06-30T10:02:00+00:00",
        )
        self.assertEqual(answer.blockers[0].text, "Waiting on audit approval")
        self.assertEqual(answer.responsible_parties[0].text, "Yifan")
        self.assertEqual(answer.next_actions[0].text, "Confirm audit records")
        self.assertEqual(answer.deadlines[0].text, "2026-06-20")
        self.assertTrue(answer.citations)

        readiness = build_mail_preflight_readiness_review(
            reviewed_at="2026-06-30T10:03:00+00:00",
        )
        self.assertEqual(
            readiness.status,
            "synthetic_mail_phase_ready_production_parser_deferred",
        )
        self.assertIn("835", readiness.completed_work_packages)
        self.assertTrue(readiness.production_expansion_blockers)

        graph_entries = {entry.name for entry in (temp_dir / "graph").iterdir()}
        self.assertEqual(
            graph_entries, {"semantic-metadata", "candidate-atoms", "candidate-relations"}
        )
        self.assertFalse(
            any("canonical" in path.as_posix() for path in (temp_dir / "graph").rglob("*"))
        )
        self.assertFalse((temp_dir / "wiki").exists())
        serialized = json.dumps(
            {
                "pack": pack.to_dict(),
                "bridge": [atom.to_dict() for atom in bridge_result.candidate_atoms],
                "answer": answer.to_dict(),
                "readiness": readiness.to_dict(),
            },
            sort_keys=True,
        )
        self.assertNotIn(str(temp_dir), serialized)
        self.assertNotIn("smb://", serialized)
        self.assertNotIn("postgres://", serialized)

    def test_mail_candidate_bridge_rejects_raw_paths_without_partial_writes(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-phase-raw-candidate")
        archive = _mail_archive()
        archive["messages"][0]["body"] = "Action Item: review C:\\secret\\mail.pst"
        stored = _run_mail_fixture(temp_dir, archive)

        with self.assertRaises(ContractValidationError):
            extract_and_store_mail_candidates(
                stored.observations,
                semantic_metadata_store=SemanticMetadataStore(temp_dir),
                candidate_atom_store=CandidateAtomStore(temp_dir),
                candidate_relation_store=CandidateRelationStore(temp_dir),
                extractor_run_id="mail_candidate_run_raw",
                created_at="2026-06-30T10:01:00+00:00",
            )

        self.assertEqual(SemanticMetadataStore(temp_dir).list(), [])
        self.assertEqual(CandidateAtomStore(temp_dir).list(), [])
        self.assertEqual(CandidateRelationStore(temp_dir).list(), [])


def _mail_archive() -> dict:
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
                "headers": {
                    "Message-ID": "<launch-001@example.test>",
                    "From": "pm@example.test",
                    "Subject": "Launch checklist",
                    "Date": "2026-06-17T10:00:00+00:00",
                },
                "body": "\n".join(
                    [
                        "Update: Launch checklist reviewed",
                        "Blocker: Waiting on audit approval",
                        "Owner: Yifan",
                        "Next Action: Confirm audit records",
                        "Deadline: 2026-06-20",
                    ]
                ),
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


def _observations_by_type(observations):
    by_type = {}
    for observation in observations:
        by_type.setdefault(observation.observation_type, []).append(observation)
    return by_type


if __name__ == "__main__":
    unittest.main()
