"""Source-start paragraph presentation; synthetic sources, no provider calls."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
import test_issue56_attachment_backfill as backfill_fixture
from formowl_contract import sha256_json
from formowl_contract.public_safety import redact_public_raw_references
from formowl_gateway import issue56_sealed_source_loader as loader
from formowl_ingestion.extractors.document.attachment import AttachmentDocumentExtractor
from formowl_ingestion.storage import ObservationStore
from formowl_mail.issue56_sealed_source import load_issue56_ingestion_revision
from formowl_retrieval.gateway import source_evidence_deadline_scope
from scripts.issue56_attachment_backfill import run_attachment_backfill
from scripts.issue56_source_native_lookup import build_lookup
from scripts.issue56_uat_web import _build_ingestion_revision
from test_attachment_document_extractor import _pdf_bytes
from test_issue56_uat_handler_composition import _source_start_preparation_fixture
from test_issue56_uat_handler_composition import _completed_registered_text_revision_fixture


def long_source_paragraph(filler="neutral glyph " * 430):
    """Synthetic review cue, deliberately unlike the requested field wording."""
    return "PARA-Z84 " + filler + "Review cue: violet lattice."


def build_source_context_fixture(paragraph_text=None):
    """Return root/revision/child/document for an independently driven runner.

    Caller closes revision.source_records.runtime_store and removes root.
    Source setup uses real PDF and independent text extraction, with no provider.
    """
    text = long_source_paragraph() if paragraph_text is None else paragraph_text
    root, stores, _, prior, manifest, export_root = backfill_fixture.AttachmentBackfillTests()._fixture()
    (export_root / "1-native.pdf").write_bytes(_pdf_bytes(text))
    report = run_attachment_backfill(
        store_directory=root, parent_binding_manifest_path=manifest,
        ledger_path=root / "context-ledger.json", existing_export_root=export_root,
    )
    if report["status_counts"] != {"succeeded": 1}:
        raise AssertionError("synthetic PDF backfill did not complete")
    delta = next(job for job in stores[1].list() if job.ingestion_job_id != prior.ingestion_job_id)
    children = [stores[3].get(key) for key in delta.observation_ids]
    child = next(item for item in children if item is not None
                 and item.observation_type == "paragraph" and item.payload.get("source_format") == "pdf")
    document_root = root / "standalone"
    document_root.mkdir()
    _, documents, authority = _completed_registered_text_revision_fixture(
        document_root, owner_user_id=loader.APPROVER_ACTOR,
        source_text=text.replace("PARA-Z84", "NOTE-V63"),
    )
    document = next(item for item in documents if item.observation_type == "paragraph")
    prepared = _build_ingestion_revision(
        root / "prepared", [[str(root), delta.ingestion_job_id],
                            [str(document_root), authority.ingestion_job_id]], prepare_only=True,
    )
    directory = Path(prepared["preparation_directory"])
    revision_hash = "sha256:" + hashlib.sha256((directory / "preparation.json").read_bytes()).hexdigest()
    lookup = root / "lookup"
    build_lookup(directory=directory, expected_revision_sha256=revision_hash, output_directory=lookup)
    admitted = Path(shutil.copytree(directory, root / "admitted"))
    for name in ("source-lookup-manifest.json", "source-lookup.sqlite"):
        shutil.copyfile(lookup / name, admitted / name)
    revision = load_issue56_ingestion_revision(admitted, expected_revision_sha256=revision_hash)
    return SimpleNamespace(root=root, revision=revision, child=child, document=document)


class SourceContextProjectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    @staticmethod
    def paragraph(filler="neutral glyph " * 430):
        return long_source_paragraph(filler)

    def prepare(self, text, *, pdf=False):
        if pdf:
            fixture = build_source_context_fixture(text)
            self.addCleanup(shutil.rmtree, fixture.root)
            self.root = fixture.root
            revision = fixture.revision
            paragraphs = [fixture.child]
            self.assertNotEqual(fixture.child.asset_id, fixture.document.asset_id)
            self.assertNotEqual(fixture.child.extractor_run_id, fixture.document.extractor_run_id)
        else:
            fixture = _source_start_preparation_fixture(
                self.root, families=("document_text",), document_text=text,
            )
            lookup = self.root / "lookup"
            build_lookup(
                directory=fixture.directory,
                expected_revision_sha256=fixture.preparation_sha256,
                output_directory=lookup,
            )
            for name in ("source-lookup-manifest.json", "source-lookup.sqlite"):
                shutil.copyfile(lookup / name, fixture.directory / name)
            revision = load_issue56_ingestion_revision(
                fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
            )
            paragraphs = [item for item in fixture.observations if item.observation_type == "paragraph"]
        self.revision = revision
        self.addCleanup(revision.source_records.runtime_store.close)
        self.assertIsNone(revision.session)
        self.assertIsNone(revision.graph_build)
        self.assertTrue(paragraphs)
        query = "Find PARA-Z84 review condition"
        arguments = {
            "query_text": query,
            "requester_user_id": loader.APPROVER_ACTOR,
            "workspace_id": loader.WORKSPACE_ID,
            "session_id": "synthetic-source-context",
            "page_size": 10,
            "required_terms": ["PARA-Z84"],
            "request_contract": {
                "original_query_hash": sha256_json(query),
                "query_class": "evidence_lookup",
                "source_family_scope": ["mail" if pdf else "document_text"],
                "requested_fields": ["review condition"],
                "maximum_claim_strength": "cited_evidence",
            },
        }
        return paragraphs, loader._build_source_start_semantic_handler(
            revision, mail_tool=False,
        ), arguments

    def query(self, handler, arguments):
        def hashes():
            return {str(path.relative_to(self.root)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in self.root.rglob("*") if path.is_file()}

        before = hashes()
        with (
            patch.object(ObservationStore, "create", side_effect=AssertionError("query write")),
            patch.object(ObservationStore, "list", side_effect=AssertionError("query enumeration")),
            patch.object(AttachmentDocumentExtractor, "extract", side_effect=AssertionError("query extraction")),
            patch.object(loader, "_execute_source_start_table", side_effect=AssertionError("field promotion")),
        ):
            result = handler(arguments)
        self.assertEqual(hashes(), before)
        self.assertLessEqual(sum(
            len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
            for item in result["evidence"]
        ), 16 * 1024)
        self.assertFalse(result.get("deterministic_exact", False))
        self.assertFalse(result.get("canonical_kg", False))
        self.assertNotEqual(result["status"], "not_found")
        coverage = result.get("requested_field_coverage")
        if coverage:
            self.assertEqual(coverage["supported_fields"], [])
            self.assertEqual(coverage["missing_fields"], ["review condition"])
            self.assertFalse(coverage["absence_claim"])
        return result

    def assert_source(self, result, source, *, pdf=False):
        source_hash = sha256_json(source.to_dict())
        item = next(item for item in result["evidence"] if item["citation_hash"] == source_hash)
        self.assertIn(source_hash, result["citations"])
        self.assertEqual(item["snippet"], redact_public_raw_references(source.text)[0])
        self.assertTrue(item["occurrence_lineage_fingerprint"].startswith("sha256:"))
        if pdf:
            self.assertEqual(item["source_observation_hash"], source_hash)
            self.assertEqual(item["attachment_locator"]["child_asset_id"], source.asset_id)
            self.assertEqual(item["attachment_locator"]["block_type"], "paragraph")
            self.assertTrue(item["attachment_locator"]["parent_attachment_observation_id"])
            for coordinate in ("page", "block_index"):
                self.assertEqual(item["attachment_locator"][coordinate], source.location[coordinate])
        else:
            self.assertEqual(item["document_locator"]["asset_id"], source.asset_id)
            self.assertEqual(item["document_locator"]["extractor_run_id"], source.extractor_run_id)
            for coordinate in ("line_start", "line_end"):
                self.assertEqual(item["document_locator"][coordinate], source.location[coordinate])
        return item

    def test_long_independent_paragraph_retains_late_value_and_native_citation(self):
        paragraphs, handler, arguments = self.prepare(self.paragraph())
        source = paragraphs[0]
        self.assertGreater(source.text.index("violet lattice"), 400)
        self.assertNotIn("review condition", source.text)
        self.assert_source(self.query(handler, arguments), source)

    def test_real_native_pdf_page_retains_late_value_and_native_citation(self):
        paragraphs, handler, arguments = self.prepare(self.paragraph(), pdf=True)
        source = paragraphs[0]
        self.assertTrue(source.payload["native_text"])
        self.assertEqual(source.payload["source_format"], "pdf")
        self.assertGreater(source.text.index("violet lattice"), 400)
        self.assertNotIn("review condition", source.text)
        self.assert_source(self.query(handler, arguments), source, pdf=True)

    def test_oversized_utf8_paragraph_is_explicitly_withheld_not_silently_clipped(self):
        text = self.paragraph("界" * 5500)
        self.assertLess(len(text), 16 * 1024)
        self.assertGreater(len(text.encode("utf-8")), 16 * 1024)
        _, handler, arguments = self.prepare(text)
        result = self.query(handler, arguments)
        self.assertEqual(result["evidence"], [])
        self.assertEqual(result["citations"], [])
        self.assertEqual(result["status"], "pending_review")
        scan = result["query_agent"]["context_bundle"]["source_recovery"]["scan"]
        self.assertFalse(scan["complete"])
        self.assertEqual(scan["stop_reason"], "context_limit")

    def test_shared_budget_keeps_whole_admitted_paragraph_and_stops_later_context(self):
        text = self.paragraph("neutral " * 1000)
        paragraphs, handler, arguments = self.prepare(text + "\n\n" + text.replace("violet", "amber"))
        result = self.query(handler, arguments)
        self.assertEqual(len(result["evidence"]), 1)
        source = next(source for source in paragraphs
                      if sha256_json(source.to_dict()) == result["evidence"][0]["citation_hash"])
        self.assert_source(result, source)
        scan = result["query_agent"]["context_bundle"]["source_recovery"]["scan"]
        self.assertFalse(scan["complete"])
        self.assertEqual(scan["stop_reason"], "context_limit")

    def test_late_raw_locator_is_redacted_without_changing_source_identity(self):
        text = self.paragraph() + " Internal locator: file:///synthetic/private.txt"
        paragraphs, handler, arguments = self.prepare(text)
        item = self.assert_source(self.query(handler, arguments), paragraphs[0])
        self.assertNotIn("file:///synthetic/private.txt", item["snippet"])
        self.assertNotIn("/synthetic/private.txt", item["snippet"])
        self.assertIn("violet lattice", item["snippet"])

    def test_permission_deadline_and_identifier_checks_still_exclude_evidence(self):
        _, handler, arguments = self.prepare(self.paragraph())
        denied = self.query(handler, {**arguments, "requester_user_id": "synthetic-denied"})
        self.assertEqual(denied["status"], "permission_denied")
        self.assertEqual(denied["evidence"], [])
        with source_evidence_deadline_scope(time.monotonic() - 1):
            expired = self.query(handler, arguments)
        self.assertEqual(expired["evidence"], [])
        self.assertEqual(expired["query_agent"]["context_bundle"]["source_recovery"]["scan"]["stop_reason"], "deadline")
        unmatched = self.query(handler, {**arguments, "required_terms": ["PARA-Y19"]})
        self.assertEqual(unmatched["evidence"], [])


if __name__ == "__main__":
    unittest.main()
