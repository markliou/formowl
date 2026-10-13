"""Small real-parser/MCP/browser diagnostic; not external-provider acceptance."""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import _paths  # noqa: F401
from formowl_contract import sha256_json
from formowl_gateway.issue56_uat_runtime import create_issue56_temporary_lan_query_service
from formowl_ingestion.storage import ObservationStore
from formowl_mail.human_uat_http import create_mail_human_uat_http_server
from formowl_mail.human_uat_orchestrator import UatConversationOutcome, UatEvidenceToolRequest
from formowl_mail.issue56_sealed_source import load_issue56_ingestion_revision
from scripts.issue56_attachment_backfill import run_attachment_backfill
from scripts.issue56_source_native_lookup import build_lookup
from scripts.issue56_uat_web import _build_ingestion_revision
import test_issue56_attachment_backfill as backfill_fixture
from test_issue56_uat_handler_composition import _completed_registered_text_revision_fixture


def _text_hash(value):
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


class AttachmentTextBrowserTests(unittest.TestCase):
    def _fixture(self):
        root, stores, _asset, prior, manifest, export_root = backfill_fixture.AttachmentBackfillTests()._fixture()
        self.addCleanup(shutil.rmtree, root)
        # Use the runner's literal "synthetic" constraint only in attachment
        # content, never in the parent message; keep the real DOCX parser.
        with ZipFile(io.BytesIO(backfill_fixture._docx_bytes())) as source:
            with ZipFile(export_root / "1-brief.docx", "w") as target:
                for entry in source.infolist():
                    target.writestr(entry, source.read(entry.filename).replace(
                        b"Bound DOCX paragraph", b"Synthetic DOCX paragraph",
                    ))
        report = run_attachment_backfill(
            store_directory=root, parent_binding_manifest_path=manifest,
            ledger_path=root / "browser-ledger.json", existing_export_root=export_root,
        )
        self.assertEqual(report["status_counts"], {"succeeded": 1})
        delta = next(job for job in stores[1].list() if job.ingestion_job_id != prior.ingestion_job_id)
        child = next(
            item for item in (stores[3].get(key) for key in delta.observation_ids)
            if item is not None and item.observation_type == "paragraph"
            and item.text == "Synthetic DOCX paragraph"
        )
        self.assertTrue(child.payload["lineage"]["parent_asset_id"])
        self.assertEqual(child.payload["lineage"]["child_asset_id"], child.asset_id)
        self.assertFalse(any("DOCX" in (stores[3].get(key).text or "") for key in prior.observation_ids))
        doc_root = root / "standalone"
        doc_root.mkdir()
        _, documents, document_authority = _completed_registered_text_revision_fixture(
            doc_root, owner_user_id=backfill_fixture.OWNER,
            source_text="Independent project requires written owner approval.\n",
        )
        document = next(item for item in documents if item.observation_type == "paragraph")
        prepared = _build_ingestion_revision(
            root / "prepared", [[str(root), delta.ingestion_job_id],
                                [str(doc_root), document_authority.ingestion_job_id]],
            prepare_only=True,
        )
        directory = Path(prepared["preparation_directory"])
        preparation_hash = "sha256:" + hashlib.sha256((directory / "preparation.json").read_bytes()).hexdigest()
        lookup = root / "lookup"
        self.assertEqual(build_lookup(
            directory=directory, expected_revision_sha256=preparation_hash,
            output_directory=lookup,
        )["status"], "created")
        admitted = Path(shutil.copytree(directory, root / "admitted"))
        for name in ("source-lookup.sqlite", "source-lookup-manifest.json"):
            shutil.copy2(lookup / name, admitted / name)
        revision = load_issue56_ingestion_revision(admitted, expected_revision_sha256=preparation_hash)
        self.addCleanup(revision.source_records.runtime_store.close)
        self.assertIsNone(revision.session)
        self.assertIsNone(revision.graph_build)
        return root, child, document, revision

    def test_docx_attachment_and_independent_document_without_dense_activation(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Canonical dev image requires Node/Chromium")
        _root, child, document, revision = self._fixture()
        # Retained/captured mail has no upload-session selector. Use the
        # existing source-scoped semantic tool, not a fabricated session.
        self.assertEqual(revision.source_records.authorized_mail_import_session_ids, ())
        expected = {
            "mail": {
                "source_family": "mail", "answer_fingerprint": _text_hash(child.text),
                "citation_fingerprints": [_text_hash(sha256_json(child.to_dict()))],
            },
            "document": {
                "source_family": "document_text", "answer_fingerprint": _text_hash(document.text),
                "citation_fingerprints": [_text_hash(sha256_json(document.to_dict()))],
            },
        }
        tool_results = []

        class FixtureConversationModel:
            model_name = "provider-free-real-docx-browser-diagnostic"

            def respond(self, *, user_text, evidence_tool, **_kwargs):
                if user_text == "你好，今天過得如何？":
                    return UatConversationOutcome(
                        response_kind="answer", answer_text="你好，今天很好，隨時可以幫忙。",
                        display_format="narrative", model_name=self.model_name,
                        coverage_status="not_applicable",
                    )
                mail = user_text == "Organize the authorized synthetic mail evidence."
                request = UatEvidenceToolRequest(
                    tool_name="query_effective_graph_view",
                    query_text="Synthetic DOCX paragraph" if mail else "written owner approval",
                    required_terms=("synthetic",) if mail else None,
                    request_contract={
                        "original_query_hash": sha256_json(user_text), "query_class": "evidence_lookup",
                        "source_family_scope": ["mail" if mail else "document_text"],
                        "requested_fields": ["content"], "maximum_claim_strength": "cited_evidence",
                    },
                )
                result = evidence_tool(request)
                tool_results.append(result)
                evidence = result.get("evidence_snippets") or result.get("evidence") or ()
                citations = tuple(item["citation_id"] if isinstance(item, Mapping) else item
                                  for item in result.get("citations", ()))
                if not evidence or not citations:
                    raise AssertionError("real parsed source returned no governed evidence")
                return UatConversationOutcome(
                    response_kind="answer", answer_text=evidence[0]["snippet"],
                    display_format="narrative", model_name=self.model_name,
                    citation_ids=(citations[0],), coverage_status="incomplete",
                    coverage_note="合成來源範圍不代表完整資料。",
                    tool_requests=(request,), tool_results=(result,),
                )

            def close(self):
                pass

            def discard_conversation(self, _safety_identifier):
                pass

        with (
            patch.object(ObservationStore, "list", side_effect=AssertionError("no query enumeration")),
            patch.object(ObservationStore, "create", side_effect=AssertionError("no query extraction/write")),
            create_issue56_temporary_lan_query_service(FixtureConversationModel(), ingestion_revision=revision) as service,
        ):
            server = create_mail_human_uat_http_server("127.0.0.1", 0, service)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            process = None
            try:
                process = subprocess.Popen(
                    [node, str(Path(__file__).resolve().parents[1] / "scripts/issue56_uat_chromium_acceptance.js"),
                     "--live", "--synthetic-source-neutral"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
                    env={"PATH": os.environ.get("PATH", os.defpath), "HOME": tempfile.gettempdir(),
                         "TMPDIR": tempfile.gettempdir(), "FORMOWL_UAT_TIMEOUT_MS": "15000",
                         "FORMOWL_UAT_URL": f"http://127.0.0.1:{server.server_address[1]}/",
                         "FORMOWL_UAT_EXPECTED_EVIDENCE_BINDINGS": json.dumps(expected)},
                )
                stdout, stderr = process.communicate(timeout=75)
            finally:
                if process is not None and process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
            self.assertEqual(process.returncode, 0, stdout)
            self.assertFalse(stderr)
            result = json.loads(stdout)
            self.assertEqual(result["status"], "source_neutral_passed")
            self.assertTrue(result["ordinary_mcp_zero"])
            self.assertTrue(result["mail_source_binding_verified"])
            self.assertTrue(result["document_source_binding_verified"])
            self.assertEqual((result["mail_tool_count"], result["document_tool_count"]), (1, 1))
            self.assertTrue(result["reload_content_preserved"])
            self.assertEqual((result["reload_transcript_count"], result["reset_transcript_count"],
                              result["post_reset_transcript_count"]), (3, 0, 1))
            self.assertEqual(len(tool_results), 2)
            evidence = tool_results[0].get("evidence_snippets") or tool_results[0].get("evidence")
            item = next(item for item in evidence if item["snippet"] == child.text)
            self.assertEqual(item["attachment_locator"]["paragraph_index"], 2)
            self.assertEqual(item["attachment_locator"]["child_asset_id"], child.asset_id)
            self.assertTrue(item["attachment_locator"]["parent_attachment_observation_id"])
