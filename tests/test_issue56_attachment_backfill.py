from __future__ import annotations

from contextlib import redirect_stderr
import io
import inspect
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile
from types import SimpleNamespace

import _paths  # noqa: F401
from formowl_core import sha256_prefixed
from formowl_contract import ContractValidationError, Observation, PermissionScope, SourceRef, sha256_json
from formowl_ingestion.assets import register_asset_from_local_file
from formowl_ingestion.extraction import ExtractionResult
from formowl_ingestion.extractors.document import AttachmentDocumentExtractor
from formowl_ingestion.extractors.mail.pst import PstMailArchiveExtractor
from formowl_ingestion.jobs import create_ingestion_job, run_ingestion_job
from formowl_ingestion.storage import (
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    JobStore,
    ObservationStore,
    StorageBackendRegistry,
)
from formowl_ingestion.storage.objects import _hash_file as _object_hash_file
from scripts import issue56_attachment_backfill as backfill
from scripts.issue56_source_native_lookup import build_lookup
from formowl_mail.issue56_sealed_source import load_issue56_ingestion_revision
from formowl_retrieval.gateway import source_evidence_query_terms_scope
from formowl_core import load_issue56_target_mail_tokenizer_profile


NOW = "2026-10-09T00:00:00+00:00"
OWNER = "user_full_pst_domain_hard_case_eval_owner"
WORKSPACE = "workspace_formowl"
PERMISSION = PermissionScope.project("project_formowl")


def _docx_bytes() -> bytes:
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(
            "word/document.xml",
            """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Bound DOCX heading</w:t></w:r></w:p>
                <w:p><w:r><w:t>Bound DOCX paragraph</w:t></w:r></w:p>
              </w:body>
            </w:document>""",
        )
    return output.getvalue()


def _xlsx_bytes() -> bytes:
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            "<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'/>",
        )
        archive.writestr(
            "xl/workbook.xml",
            "<workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' "
            "xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'>"
            "<sheets><sheet name='Data' sheetId='1' r:id='rId1'/></sheets></workbook>",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"
            "<Relationship Id='rId1' Target='worksheets/sheet1.xml'/></Relationships>",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            "<worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'>"
            "<sheetData><row r='1'><c r='A1' t='inlineStr'><is><t>Key</t></is></c>"
            "<c r='B1' t='inlineStr'><is><t>Value</t></is></c></row>"
            "<row r='2'><c r='A2' t='inlineStr'><is><t>R-56</t></is></c>"
            "<c r='B2' t='inlineStr'><is><t>7</t></is></c></row></sheetData></worksheet>",
        )
    return output.getvalue()


def _mail_bytes() -> bytes:
    return (
        "Message-ID: <backfill-parent@example.test>\n"
        "Subject: Backfill parent\n"
        "From: owner@example.test\n"
        "To: team@example.test\n"
        "Date: Wed, 01 Jan 2025 00:00:00 +0000\n"
        "Content-Type: text/plain; charset=utf-8\n"
        "\n"
        "Parent message\n"
    ).encode()


class _Runner:
    def __init__(self, message: bytes) -> None:
        self.message = message

    def __call__(self, command, timeout):
        output = Path(command[command.index("-o") + 1])
        (output / "1.eml").write_bytes(self.message)
        from formowl_ingestion.extractors.mail.pst import _ParserCommandResult

        return _ParserCommandResult(0)


def _write_manifest(path: Path, *, asset, prior_job, prior_run, parent) -> None:
    location = parent.location
    payload = parent.payload or {}
    record = {
        "source_content_hash": location["source_content_hash"],
        "folder_path_hash": location["folder_path_hash"],
        "message_id": location["message_id"],
        "message_index": location["message_index"],
        "parent_observation_id": parent.observation_id,
        "parent_extractor_run_id": parent.extractor_run_id,
        "parent_source_inventory_id": location["source_inventory_id"],
        "parent_source_inventory_item_id": location["source_inventory_item_id"],
        "archive_id": location["archive_id"],
        "mailbox_id": location["mailbox_id"],
        "message_occurrence_id": location["message_occurrence_id"],
        "thread_id": location["thread_id"],
        "message_fingerprint": payload["message_fingerprint"],
        "existing_attachment_max_index": 0,
    }
    manifest = {
        "schema_version": 1,
        "source_asset_id": asset.asset_id,
        "source_fingerprint": asset.content_hash,
        "permission_scope_fingerprint": sha256_json(asset.permission_scope),
        "prior_ingestion_job_id": prior_job.ingestion_job_id,
        "prior_job_fingerprint": sha256_json(prior_job.to_dict()),
        "prior_parent_run_id": prior_run.extractor_run_id,
        "parent_binding_count": 1,
        "parent_binding_fingerprint": sha256_json([record]),
        "records": [record],
    }
    path.write_text(
        json.dumps(
            {**manifest, "artifact_fingerprint": sha256_json(manifest)},
            sort_keys=True,
        )
    )


class AttachmentBackfillTests(unittest.TestCase):
    def test_root_verifier_failure_reports_actual_digest_without_extraction_or_retry(self):
        root, stores, asset, prior, manifest, export_root = self._fixture()
        store = FileObjectStore(StorageBackendRegistry(root))
        payload = store.resolve_object_path(asset.object_uri)
        original = payload.read_bytes()
        altered = b"?" + original[1:]
        payload.write_bytes(altered)
        source_before = (root / "source.pst").read_bytes()
        asset_before = stores[0].get(asset.asset_id).to_dict()
        runs_before = [run.to_dict() for run in stores[2].list()]
        observations_before = [item.to_dict() for item in stores[3].list()]
        captured = io.StringIO()
        ledger = root / "verifier-failure-ledger.json"
        with redirect_stderr(captured), patch.object(
            backfill.ReadpstSidecarBackfillExtractor, "extract",
            side_effect=AssertionError("verification failure reached extraction"),
        ), patch("formowl_ingestion.storage.objects._hash_file", wraps=_object_hash_file) as reader:
            report = backfill.run_attachment_backfill(
                store_directory=root, parent_binding_manifest_path=manifest,
                ledger_path=ledger, existing_export_root=export_root,
            )
        self.assertEqual(reader.call_count, 1)
        self.assertEqual(report["status_counts"], {"failed": 1})
        self.assertEqual(report["observation_count"], 0)
        self.assertFalse(report["source_completeness_certified"])
        diagnostic = json.loads(captured.getvalue())
        self.assertEqual(diagnostic["phase"], "object_verification")
        self.assertEqual(diagnostic["reason_code"], "hash_mismatch")
        self.assertEqual(diagnostic["expected_content_hash"], asset.content_hash)
        self.assertEqual(diagnostic["actual_content_hash"], sha256_prefixed(altered))
        self.assertEqual(diagnostic["expected_file_size"], len(original))
        self.assertEqual(diagnostic["actual_file_size"], len(original))
        self.assertTrue(diagnostic["read_completed"])
        self.assertTrue(diagnostic["file_stat_stable"])
        self.assertTrue(diagnostic["path_stat_matches"])
        self.assertNotIn(str(root), captured.getvalue())
        delta = next(job for job in stores[1].list() if job.ingestion_job_id != prior.ingestion_job_id)
        self.assertEqual(delta.extractor_run_ids, [])
        self.assertEqual(delta.observation_ids, [])
        self.assertEqual([run.to_dict() for run in stores[2].list()], runs_before)
        self.assertEqual([item.to_dict() for item in stores[3].list()], observations_before)
        self.assertEqual(stores[0].get(asset.asset_id).to_dict(), asset_before)
        self.assertEqual(payload.read_bytes(), altered)
        self.assertEqual((root / "source.pst").read_bytes(), source_before)
        preserved = ledger.read_bytes()
        with patch.object(FileObjectStore, "verify_object", side_effect=AssertionError("blind retry")):
            self.assertEqual(backfill.run_attachment_backfill(
                store_directory=root, parent_binding_manifest_path=manifest,
                ledger_path=ledger, existing_export_root=export_root,
            ), report)
        self.assertEqual(ledger.read_bytes(), preserved)

    def test_known_document_failures_preserve_child_and_partial_parent(self):
        codes = (
            "attachment_document_xls_parse_failed",
            "attachment_document_pdf_parse_failed",
            "attachment_document_pdf_text_extract_failed",
            "attachment_document_pptx_parse_failed",
        )
        extract = AttachmentDocumentExtractor.extract
        for code in codes:
            with self.subTest(code=code):
                root, stores, asset, prior, manifest, export_root = self._fixture()
                ledger = root / "partial-ledger.json"

                def extract_with_failure(adapter, source):
                    if b"word/document.xml" in source.object_path.read_bytes():
                        return ExtractionResult(errors=[code])
                    return extract(adapter, source)

                with patch.object(AttachmentDocumentExtractor, "extract", extract_with_failure):
                    report = backfill.run_attachment_backfill(
                        store_directory=root, parent_binding_manifest_path=manifest,
                        ledger_path=ledger, existing_export_root=export_root,
                    )
                self.assertEqual(report["status_counts"], {"succeeded": 1})
                self.assertFalse(report["source_completeness_certified"])
                self.assertFalse(report["rag_activation_performed"])
                self.assertEqual(report["error_code_counts"], {code: 1})
                self.assertIn("partial_extraction", report["warning_code_counts"])
                delta = next(job for job in stores[1].list()
                             if job.ingestion_job_id != prior.ingestion_job_id)
                runs = [stores[2].get(run_id) for run_id in delta.extractor_run_ids]
                failed = next(run for run in runs if run.status == "failed")
                self.assertEqual(failed.errors, [code])
                parent = next(run for run in runs if run.asset_id == asset.asset_id)
                self.assertEqual(parent.status, "succeeded")
                self.assertIn("attachment_child_extraction_incomplete", parent.warnings)
                child = stores[0].get(failed.asset_id)
                self.assertIsNotNone(child)
                observations = [stores[3].get(key) for key in delta.observation_ids]
                self.assertTrue(any(item.observation_type == "email_attachment_occurrence"
                                    and item.payload.get("child_asset_id") == child.asset_id
                                    for item in observations))
                self.assertFalse(any(item.extractor_run_id == failed.extractor_run_id
                                     for item in observations))
                self.assertTrue(any(item.observation_type == "table_cell" for item in observations))
                sealed = ledger.read_bytes()
                with patch.object(AttachmentDocumentExtractor, "extract",
                                  side_effect=AssertionError("immutable resume reparsed")):
                    resumed = backfill.run_attachment_backfill(
                        store_directory=root, parent_binding_manifest_path=manifest,
                        ledger_path=ledger, existing_export_root=export_root,
                    )
                self.assertEqual(resumed, report)
                self.assertEqual(ledger.read_bytes(), sealed)

    def test_unknown_document_failures_still_fail_and_roll_back_child(self):
        for failure in (
            ExtractionResult(errors=["unknown_document_failure"]),
            ExtractionResult(errors=["attachment_document_pdf_parse_failed", "unknown_document_failure"]),
            RuntimeError("unknown_document_exception"),
        ):
            with self.subTest(failure=failure):
                root, stores, asset, prior, manifest, export_root = self._fixture()
                before_assets = [item.asset_id for item in stores[0].list()]
                before_observations = [item.observation_id for item in stores[3].list()]
                options = {"side_effect": failure} if isinstance(failure, Exception) else {"return_value": failure}
                with patch.object(AttachmentDocumentExtractor, "extract", **options):
                    report = backfill.run_attachment_backfill(
                        store_directory=root, parent_binding_manifest_path=manifest,
                        ledger_path=root / "failed-ledger.json", existing_export_root=export_root,
                    )
                self.assertEqual(report["status_counts"], {"failed": 1})
                self.assertEqual(report["observation_count"], 0)
                self.assertFalse(report["source_completeness_certified"])
                self.assertEqual([item.asset_id for item in stores[0].list()], before_assets)
                self.assertEqual([item.observation_id for item in stores[3].list()], before_observations)
                delta = next(job for job in stores[1].list()
                             if job.ingestion_job_id != prior.ingestion_job_id)
                self.assertEqual(delta.status, "failed")
                self.assertFalse(delta.observation_ids)

    def _fixture(self):
        root = Path(tempfile.mkdtemp(prefix="issue56-backfill-"))
        source = root / "source.pst"
        source.write_bytes(b"!BDN synthetic pst root")
        registry = StorageBackendRegistry(root)
        backend = registry.register_local_backend(
            root / "objects",
            workspace_scope=WORKSPACE,
            storage_backend_id="storage_issue56_backfill",
        )
        object_store = FileObjectStore(registry)
        assets = AssetStore(root)
        asset = register_asset_from_local_file(
            source,
            object_store=object_store,
            asset_store=assets,
            storage_backend_id=backend.storage_backend_id,
            workspace_id=WORKSPACE,
            owner_user_id=OWNER,
            permission_scope=PERMISSION,
            source_ref=SourceRef(
                source_system="formowl_upload_session",
                source_type="mail_archive_upload",
                source_id="upload_issue56_backfill",
            ),
            mime_type="application/vnd.ms-outlook",
            created_at=NOW,
            registered_at=NOW,
        )
        message = _mail_bytes()
        adapter = PstMailArchiveExtractor(
            runner=_Runner(message), scratch_parent=root / "scratch"
        )
        stores = (
            assets,
            JobStore(root),
            ExtractorRunStore(root),
            ObservationStore(root),
        )
        prior = create_ingestion_job(
            asset=asset,
            job_store=stores[1],
            requested_by=OWNER,
            extractor_adapters=[adapter],
            created_at=NOW,
        )
        prior = run_ingestion_job(
            ingestion_job_id=prior.ingestion_job_id,
            asset_store=assets,
            job_store=stores[1],
            object_store=object_store,
            extractor_run_store=stores[2],
            observation_store=stores[3],
            extractor_adapters=[adapter],
            started_at=NOW,
            completed_at=NOW,
        )
        parent = next(
            item
            for item in (stores[3].get(item_id) for item_id in prior.observation_ids)
            if item is not None and item.observation_type == "email_message"
        )
        prior_run = stores[2].get(prior.extractor_run_ids[0])
        assert prior_run is not None
        manifest = root / "sidecar-parent-binding.json"
        _write_manifest(manifest, asset=asset, prior_job=prior, prior_run=prior_run, parent=parent)
        export_parent = root / "readpst" / "export"
        export_parent.mkdir(parents=True)
        export_bytes = message
        (export_parent / "1").write_bytes(export_bytes)
        (export_parent / "1-report.xlsx").write_bytes(_xlsx_bytes())
        (export_parent / "1-brief.docx").write_bytes(_docx_bytes())
        (export_parent / "1-photo.png").write_bytes(b"\x89PNG\r\n\x1a\nimage")
        marker = {"source_fingerprint": asset.content_hash, "export_kind": "readpst-S"}
        (export_parent.parent / "readpst-export-complete.json").write_text(
            json.dumps(marker, sort_keys=True)
        )
        return root, stores, asset, prior, manifest, export_parent

    def test_sidecar_backfill_is_immutable_resumable_and_prepares_child_text(self):
        root, stores, asset, prior, manifest, export_root = self._fixture()
        ledger = root / "backfill-ledger.json"
        with patch.object(ObservationStore, "list", side_effect=AssertionError("no enumeration")):
            first = backfill.run_attachment_backfill(
                store_directory=root,
                parent_binding_manifest_path=manifest,
                ledger_path=ledger,
                existing_export_root=export_root,
                mode="pst-sidecar",
                config={"attachment_max_document_blocks": 20},
            )
            second = backfill.run_attachment_backfill(
                store_directory=root,
                parent_binding_manifest_path=manifest,
                ledger_path=ledger,
                existing_export_root=export_root,
                mode="pst-sidecar",
                config={"attachment_max_document_blocks": 20},
            )
        self.assertEqual(first, second)
        self.assertEqual(first["status_counts"], {"succeeded": 1})
        self.assertGreater(first["observation_count"], 2)
        self.assertNotIn("set(job.observation_ids)", inspect.getsource(backfill._source))

        jobs = stores[1]
        # The stable backfill job is the only newly-created job for this root.
        all_jobs = jobs.list()
        delta = next(job for job in all_jobs if job.ingestion_job_id != prior.ingestion_job_id)
        observations = stores[3]
        occurrence = next(
            observations.get(item_id)
            for item_id in delta.observation_ids
            if observations.get(item_id) is not None
            and observations.get(item_id).observation_type == "email_attachment_occurrence"
            and observations.get(item_id).payload.get("filename") == "brief.docx"
        )
        child_id = occurrence.payload["child_asset_id"]
        child_text = [
            observations.get(item_id)
            for item_id in delta.observation_ids
            if observations.get(item_id) is not None
            and observations.get(item_id).asset_id == child_id
        ]
        self.assertIn("heading", {item.observation_type for item in child_text})
        self.assertTrue(all(item.payload["lineage"]["parent_asset_id"] == asset.asset_id for item in child_text))
        self.assertTrue(any(item.location["paragraph_index"] == 2 for item in child_text))

        image_occurrence = next(
            observations.get(item_id)
            for item_id in delta.observation_ids
            if observations.get(item_id) is not None
            and observations.get(item_id).observation_type == "email_attachment_occurrence"
            and observations.get(item_id).payload.get("filename") == "photo.png"
        )
        image_asset = stores[0].get(image_occurrence.payload["child_asset_id"])
        self.assertIsNotNone(image_asset)
        image_runs = [run for run in stores[2].list() if run.asset_id == image_asset.asset_id]
        self.assertEqual(len(image_runs), 1)
        self.assertIn("attachment_document_unsupported_content", image_runs[0].warnings)

        # The existing preparation owner consumes the completed sidecar job;
        # child document text is sealed as a parent-bound reference, not a
        # detached source family.
        from scripts.issue56_uat_web import _build_ingestion_revision

        prepared = _build_ingestion_revision(
            root / "revision",
            [[str(root), delta.ingestion_job_id]],
            prepare_only=True,
        )
        snapshot = json.loads((Path(prepared["preparation_directory"]) / "observations.json").read_bytes())
        ids = {reference[1] for reference in snapshot["observation_references"]}
        self.assertTrue({item.observation_id for item in child_text} & ids)

    def test_prepared_child_text_is_marked_retrievable_by_existing_index_owner(self):
        from formowl_mail.issue56_sealed_source import IngestionRevisionSourceRecords

        child = Observation(
            observation_id="child-paragraph",
            extractor_run_id="child-run",
            observation_type="paragraph",
            modality="document",
            location={"page": 1, "paragraph_index": 2},
            confidence=1.0,
            permission_scope=PERMISSION,
            created_at=NOW,
            asset_id="child-asset",
            text="retrievable child text",
            payload={
                "lineage": {
                    "child_asset_id": "child-asset",
                    "child_content_hash": "sha256:" + "1" * 64,
                    "parent_asset_id": "mail-root",
                }
            },
        )

        class RuntimeStore:
            binding = {"binding": "test"}

            def __init__(self):
                self.items = []

            def checkpoint_cursor(self, name):
                return None

            def put_helpers(self, items):
                self.items.extend(items)

            def checkpoint(self, name, cursor, binding):
                return None

            def iter_helpers(self, after_id=None, limit=256):
                if after_id is None and self.items:
                    return list(self.items)
                return []

            def helper_for_attachment_asset(self, child_asset_id):
                return {
                    "observation_id": "attachment-parent",
                    "permission_scope": PERMISSION.to_dict(),
                    "lineage": {"message_occurrence_id": "occurrence-1"},
                }

        authority = SimpleNamespace(
            asset=SimpleNamespace(
                owner_user_id=OWNER,
                workspace_id=WORKSPACE,
                lifecycle_state="active",
            ),
            permission_scope=PERMISSION.to_dict(),
            job_fingerprint="sha256:" + "2" * 64,
            load_indexed_observation=lambda observation_id, **kwargs: child,
        )
        runtime_store = RuntimeStore()
        records = IngestionRevisionSourceRecords(
            runtime_store=runtime_store,
            job_authorities=[authority],
            requester_user_id=OWNER,
            workspace_id=WORKSPACE,
            observation_references=[],
        )
        records.index_prepared_references(
            [[0, child.observation_id, sha256_json(child.to_dict())]],
            authorized_source=None,
        )
        child_items = [
            item for item in runtime_store.items
            if item["observation_id"] == child.observation_id
        ]
        self.assertTrue(child_items)
        self.assertTrue(child_items[-1]["retrieval"])
        self.assertEqual(child_items[-1]["retrieval_source_family"], "mail")


class AttachmentTextSourceStartSafetyTests(unittest.TestCase):
    """Focused sealed child-text safety checks; browser delivery is separate."""

    def _admitted_delta(self):
        from scripts.issue56_uat_web import _build_ingestion_revision
        from test_attachment_document_extractor import _pdf_bytes

        root, stores, _asset, prior, manifest, export_root = AttachmentBackfillTests()._fixture()
        (export_root / "1-brief.txt").write_text(
            "Unique TXT child source term.", encoding="utf-8",
        )
        (export_root / "1-native.pdf").write_bytes(_pdf_bytes("Unique PDF child source term"))
        report = backfill.run_attachment_backfill(
            store_directory=root,
            parent_binding_manifest_path=manifest,
            ledger_path=root / "source-start-safety-ledger.json",
            existing_export_root=export_root,
        )
        self.assertEqual(report["status_counts"], {"succeeded": 1})
        delta = next(job for job in stores[1].list() if job.ingestion_job_id != prior.ingestion_job_id)
        prepared = _build_ingestion_revision(
            root / "source-start-prepared",
            [[str(root), delta.ingestion_job_id]],
            prepare_only=True,
        )
        directory = Path(prepared["preparation_directory"])
        import hashlib
        revision_hash = "sha256:" + hashlib.sha256(
            (directory / "preparation.json").read_bytes()
        ).hexdigest()
        lookup = root / "source-start-lookup"
        self.assertEqual(
            build_lookup(
                directory=directory,
                expected_revision_sha256=revision_hash,
                output_directory=lookup,
            )["status"],
            "created",
        )
        admitted = Path(shutil.copytree(directory, root / "source-start-admitted"))
        for name in ("source-lookup.sqlite", "source-lookup-manifest.json"):
            shutil.copy2(lookup / name, admitted / name)
        revision = load_issue56_ingestion_revision(
            admitted, expected_revision_sha256=revision_hash,
        )
        self.addCleanup(revision.source_records.runtime_store.close)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        observations = [stores[3].get(item_id) for item_id in delta.observation_ids]
        children = [
            item for item in observations
            if item is not None
            and item.observation_type in {"heading", "paragraph", "list_item"}
            and (item.payload or {}).get("lineage", {}).get("child_asset_id") == item.asset_id
        ]
        return revision, children

    def test_docx_txt_pdf_children_are_mail_family_and_document_family_excludes_them(self):
        revision, children = self._admitted_delta()
        by_text = {item.text: item for item in children}
        expected_terms = {
            "Bound DOCX paragraph",
            "Unique TXT child source term.",
            "Unique PDF child source term",
        }
        self.assertTrue(expected_terms <= set(by_text))
        profile = load_issue56_target_mail_tokenizer_profile()
        emitted = []
        terms = tuple(profile.analyze(" ".join(expected_terms)).tokens)
        with source_evidence_query_terms_scope(terms):
            scan = revision.source_records.scan_authorized_observations(
                source_family="mail",
                max_observations=128,
                observation_callback=lambda observation, scope: emitted.append(observation) or True,
            )
        self.assertFalse(scan.complete, scan)
        self.assertIn(scan.stop_reason, {"indexed_shortlist", "indexed_shortlist_miss"})
        emitted_ids = [item.observation_id for item in emitted]
        parent_by_child = {
            (item.payload or {}).get("child_asset_id"): item
            for item in emitted
            if item.observation_type == "email_attachment_occurrence"
        }
        for child in by_text.values():
            self.assertIn(child.observation_id, emitted_ids)
            parent = parent_by_child.get(child.asset_id)
            self.assertIsNotNone(parent)
            self.assertLess(emitted_ids.index(parent.observation_id), emitted_ids.index(child.observation_id))
        self.assertTrue(any(item.observation_type == "email_attachment_occurrence" for item in emitted))
        mail_emitted_ids = set(emitted_ids)
        document_emitted = []
        document_scan = revision.source_records.scan_authorized_observations(
            source_family="document_text",
            source_scope_ids=(revision.source_records.job_authorities[0].permission_scope["scope_id"],),
            max_observations=128,
            observation_callback=lambda observation, scope: document_emitted.append(observation) or True,
        )
        self.assertFalse(mail_emitted_ids & {item.observation_id for item in document_emitted})
        self.assertFalse({item.observation_id for item in by_text.values()}
                         & {item.observation_id for item in document_emitted})
        self.assertFalse(document_scan.complete)
        self.assertIn(document_scan.stop_reason, {"indexed_query_terms_unavailable", "indexed_shortlist_miss"})

    def test_missing_parent_is_incomplete_without_child_evidence(self):
        revision, children = self._admitted_delta()
        child = next(item for item in children if "TXT child" in item.text)
        lookup = revision.source_records.runtime_store
        with patch.object(lookup, "helper_for_attachment_asset", return_value=None):
            profile = load_issue56_target_mail_tokenizer_profile()
            with source_evidence_query_terms_scope(profile.analyze(child.text).tokens):
                scan = revision.source_records.scan_authorized_observations(
                    source_family="mail", max_observations=128,
                )
        self.assertFalse(scan.complete)
        self.assertEqual(scan.stop_reason, "source_parent_binding_unresolved")
        self.assertNotIn(child.observation_id, {item.observation_id for item, _ in scan.observations})

    def test_child_parent_hash_or_permission_tamper_is_rejected(self):
        from dataclasses import replace
        revision, children = self._admitted_delta()
        child = next(item for item in children if "TXT child" in item.text)
        authority = revision.source_records.job_authorities[0]
        original_get = authority.observation_store.get
        for tampered in (
            replace(child, text="tampered child"),
            replace(child, permission_scope={**dict(child.permission_scope), "scope_id": "other_scope"}),
        ):
            with self.subTest(tamper=tampered.text), patch.object(
                authority.observation_store, "get",
                side_effect=lambda observation_id, tampered=tampered: (
                    tampered if observation_id == child.observation_id else original_get(observation_id)
                ),
            ):
                profile = load_issue56_target_mail_tokenizer_profile()
                with source_evidence_query_terms_scope(profile.analyze(child.text).tokens):
                    with self.assertRaises(ContractValidationError):
                        revision.source_records.scan_authorized_observations(
                            source_family="mail", max_observations=128,
                        )

    def test_source_start_query_respects_read_cap_deadline_and_no_writes(self):
        revision, children = self._admitted_delta()
        profile = load_issue56_target_mail_tokenizer_profile()
        with (
            patch.object(revision.source_records.job_authorities[0].observation_store, "list",
                         side_effect=AssertionError("query enumeration")),
            patch.object(Path, "write_bytes", side_effect=AssertionError("query write")),
            patch.object(Path, "write_text", side_effect=AssertionError("query write")),
            source_evidence_query_terms_scope(profile.analyze(children[0].text).tokens),
        ):
            capped = revision.source_records.scan_authorized_observations(
                source_family="mail", max_observations=1,
            )
            self.assertFalse(capped.complete)
            self.assertLessEqual(capped.scanned_observation_count, 1)
            deadline = revision.source_records.scan_authorized_observations(
                source_family="mail", max_observations=128, deadline_monotonic=0,
            )
            self.assertEqual(deadline.stop_reason, "deadline")


if __name__ == "__main__":
    unittest.main()
