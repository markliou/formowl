"""Attachment containers end to end: a ZIP holding an .eml reaches a source query
with its member chain and the inner message's own sender/date/subject."""

from __future__ import annotations

from email.message import EmailMessage
import hashlib
import io
from pathlib import Path
import shutil
import unittest
from zipfile import ZipFile

import _paths  # noqa: F401
import test_issue56_attachment_backfill as backfill_fixture
from formowl_contract import sha256_json
from formowl_gateway import issue56_sealed_source_loader as loader
from formowl_mail.issue56_sealed_source import load_issue56_ingestion_revision
from scripts.issue56_attachment_backfill import run_attachment_backfill
from scripts.issue56_source_native_lookup import build_lookup
from scripts.issue56_uat_web import _build_ingestion_revision


def _zipped_message() -> bytes:
    message = EmailMessage()
    message["From"], message["Subject"] = "Carol <carol@example.com>", "Forwarded KQ-417 note"
    message["Date"] = "Thu, 02 Jul 2026 21:46:40 +0800"
    message.set_content("KQ-417 review cue: amber lattice.")
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("mail/fwd.eml", message.as_bytes())
    return buffer.getvalue()


class ContainerAttachmentEndToEndTests(unittest.TestCase):
    def test_zip_eml_body_is_cited_with_member_chain_and_inner_message_context(self):
        root, stores, _, prior, manifest, export_root = backfill_fixture.AttachmentBackfillTests()._fixture()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        (export_root / "1-bundle.zip").write_bytes(_zipped_message())
        report = run_attachment_backfill(
            store_directory=root, parent_binding_manifest_path=manifest,
            ledger_path=root / "container-ledger.json", existing_export_root=export_root,
        )
        self.assertEqual(report["status_counts"], {"succeeded": 1})
        delta = next(job for job in stores[1].list() if job.ingestion_job_id != prior.ingestion_job_id)
        children = [stores[3].get(key) for key in delta.observation_ids]
        body = next(item for item in children if item is not None and item.observation_type == "paragraph"
                    and "KQ-417 review cue" in item.text)
        self.assertEqual([member["name"] for member in body.location["container_members"]], ["fwd.eml"])
        records = [item for item in children if item is not None and item.observation_type == "container_member"]
        self.assertEqual([(item.text, item.payload["member_status"]) for item in records], [("fwd.eml", "extracted")])

        prepared = _build_ingestion_revision(root / "prepared", [[str(root), delta.ingestion_job_id]],
                                             prepare_only=True)
        directory = Path(prepared["preparation_directory"])
        revision_hash = "sha256:" + hashlib.sha256((directory / "preparation.json").read_bytes()).hexdigest()
        build_lookup(directory=directory, expected_revision_sha256=revision_hash, output_directory=root / "lookup")
        for name in ("source-lookup-manifest.json", "source-lookup.sqlite"):
            shutil.copyfile(root / "lookup" / name, directory / name)
        revision = load_issue56_ingestion_revision(directory, expected_revision_sha256=revision_hash)
        self.addCleanup(revision.source_records.runtime_store.close)
        query = "Find KQ-417 review cue"
        result = loader._build_source_start_semantic_handler(revision, mail_tool=False)({
            "query_text": query,
            "requester_user_id": loader.APPROVER_ACTOR,
            "workspace_id": loader.WORKSPACE_ID,
            "session_id": "synthetic-container-attachment",
            "page_size": 10,
            "required_terms": ["KQ-417"],
            "request_contract": {
                "original_query_hash": sha256_json(query),
                "query_class": "evidence_lookup",
                "source_family_scope": ["mail"],
                "requested_fields": ["review cue"],
                "maximum_claim_strength": "cited_evidence",
            },
        })
        item = next(item for item in result["evidence"]
                    if item["citation_hash"] == sha256_json(body.to_dict()))
        self.assertIn("KQ-417 review cue: amber lattice.", item["snippet"])
        context = item["source_context"]
        self.assertEqual(context["relationship"], "attachment_parent")
        self.assertEqual(context["container_member_names"], ["fwd.eml"])
        self.assertEqual(context["embedded_message"], {
            "sender": "Carol <carol@example.com>", "sent_at": "2026-07-02T13:46:40Z",
            "subject": "Forwarded KQ-417 note",
        })


if __name__ == "__main__":
    unittest.main()
