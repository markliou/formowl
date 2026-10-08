from __future__ import annotations

from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from zipfile import ZipFile

import _paths  # noqa: F401
from mcp.shared.version import LATEST_PROTOCOL_VERSION
from starlette.testclient import TestClient

import formowl_gateway.runtime as runtime_module
from formowl_auth import ActorContext, OAuthPrincipal
from formowl_contract import (
    Asset,
    ContractValidationError,
    Observation,
    PermissionScope,
    SessionIdentity,
    User,
    WorkspaceMember,
    sha256_json,
)
from formowl_gateway.runtime import ConnectedRuntime, ConnectedRuntimeConfig
from formowl_gateway.semantic import SemanticMcpGateway, validate_public_gateway_payload
from formowl_graph import EffectiveGraphView
from formowl_ingestion.extraction import ExtractionInput
from formowl_ingestion.extractors.document.attachment import AttachmentDocumentExtractor
from formowl_mail.hybrid import (
    SemanticPhaseTrace,
    attach_authorized_source_occurrence_providers,
    build_authorized_semantic_mail_session,
    build_authorized_semantic_observation_session,
    build_authorized_source_backed_effective_graph_view,
)
from formowl_mail.query import (
    MailAttachmentChildOccurrenceLineage,
    build_authorized_observation_snippet_index,
    normalized_authorized_observation_lineages,
    source_occurrence_lineage_from_observation,
    validate_source_neutral_attachment_observation_coverage,
)
from formowl_mail.exact import (
    authorized_source_occurrence_scope_fingerprint,
    execute_deterministic_source_occurrence_inventory,
)
from formowl_mail.semantic_plan import (
    AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
    deterministic_query_class,
    route_semantic_query,
    validated_authorized_semantic_source,
)
from test_connected_runtime import (
    _FakeHttpClient,
    _FakeRepository,
    _write_runtime_environment,
)
from test_issue56_semantic_execution_e2e import _contract_only_runtime


WORKSPACE_ID = "workspace_attachment_hybrid"
REQUESTER_ID = "user_attachment_hybrid"
SOURCE_SCOPE_ID = "mail_import_attachment_hybrid"
MESSAGE_OCCURRENCE_ID = "message_occurrence_attachment_hybrid"
PERMISSION_SCOPE = PermissionScope.project(SOURCE_SCOPE_ID).to_dict()


def _observation(
    *,
    observation_id: str,
    observation_type: str,
    text: str,
    message_occurrence_id: str = MESSAGE_OCCURRENCE_ID,
    asset_id: str = "asset_parent_mail",
    payload: dict[str, object] | None = None,
    permission_scope: dict[str, object] = PERMISSION_SCOPE,
) -> Observation:
    return Observation.from_dict(
        Observation(
            observation_id=observation_id,
            extractor_run_id="extractor_attachment_hybrid",
            observation_type=observation_type,
            modality="mail",
            location={"message_occurrence_id": message_occurrence_id},
            confidence=1.0,
            permission_scope=permission_scope,
            created_at="2026-08-29T00:00:00+00:00",
            asset_id=asset_id,
            text=text,
            payload={
                "message_occurrence_id": message_occurrence_id,
                **(payload or {}),
            },
        ).to_dict()
    )


def _attachment_child_observations(
    *,
    child_asset_id: str,
    query_text: str | None = None,
    content: bytes | None = None,
    suffix: str = ".csv",
) -> tuple[Observation, ...]:
    if content is None:
        if query_text is None:
            raise AssertionError("attachment fixture content is required")
        content = f"kind,value\npart,{query_text}\n".encode()
    with tempfile.NamedTemporaryFile(suffix=suffix) as child_file:
        child_file.write(content)
        child_file.flush()
        child_asset = Asset.from_dict(
            {
                "asset_id": child_asset_id,
                "storage_backend_id": "attachment_test_store",
                "object_uri": "formowl://asset/attachment-child",
                "content_hash": "sha256:" + hashlib.sha256(content).hexdigest(),
                "file_size": len(content),
                "mime_type": (
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    if suffix == ".xlsx"
                    else "text/csv"
                ),
                "created_at": "2026-08-29T00:00:00+00:00",
                "registered_at": "2026-08-29T00:00:00+00:00",
                "owner_user_id": REQUESTER_ID,
                "workspace_id": WORKSPACE_ID,
                "permission_scope": PERMISSION_SCOPE,
                "lifecycle_state": "active",
                "source_ref": {
                    "source_system": "formowl_mail_attachment",
                    "source_type": "email_attachment_occurrence",
                    "source_id": "attachment_inventory_item",
                },
            }
        )
        result = AttachmentDocumentExtractor().extract(
            ExtractionInput(
                asset=child_asset,
                object_path=Path(child_file.name),
                extractor_run_id="extractor_attachment_document",
                config={"parent_asset_id": "asset_parent_mail"},
                created_at="2026-08-29T00:00:00+00:00",
            )
        )
    if result.errors or result.warnings:
        raise AssertionError("attachment document fixture extraction failed")
    return tuple(result.observations)


def _formal_xlsx_bytes() -> bytes:
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/tables/table1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"/>
</Types>""",
        )
        archive.writestr(
            "xl/workbook.xml",
            """<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets>
</workbook>""",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            """<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <sheetData>
  <row r="1"><c r="A1" t="inlineStr"><is><t>Category</t></is></c><c r="B1" t="inlineStr"><is><t>Code</t></is></c></row>
  <row r="2"><c r="A2" t="inlineStr"><is><t>ROW-FILTER-42</t></is></c><c r="B2" t="inlineStr"><is><t>VALUE-7</t></is></c></row>
 </sheetData>
 <tableParts count="1"><tablePart r:id="rIdTable1"/></tableParts>
</worksheet>""",
        )
        archive.writestr(
            "xl/worksheets/_rels/sheet1.xml.rels",
            """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rIdTable1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/table" Target="../tables/table1.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "xl/tables/table1.xml",
            """<table xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 id="1" name="SourceTable" displayName="SourceTable" ref="A1:B2" headerRowCount="1">
 <tableColumns count="2"><tableColumn id="1" name="Category"/><tableColumn id="2" name="Code"/></tableColumns>
</table>""",
        )
    return output.getvalue()


def _source_provided_multilevel_xlsx_bytes() -> bytes:
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/tables/table1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"/>
</Types>""",
        )
        archive.writestr(
            "xl/workbook.xml",
            """<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets>
</workbook>""",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            """<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <sheetData>
  <row r="1"><c r="A1" t="inlineStr"><is><t>製造國</t></is></c><c r="B1" t="inlineStr"><is><t>供應商</t></is></c><c r="C1" t="inlineStr"><is><t>零件編號</t></is></c><c r="D1" t="inlineStr"><is><t>單價</t></is></c><c r="E1" t="inlineStr"><is><t>批</t></is></c><c r="F1" t="inlineStr"><is><t>部門</t></is></c><c r="G1" t="inlineStr"><is><t>款式</t></is></c><c r="H1" t="inlineStr"><is><t>狀態</t></is></c><c r="I1" t="inlineStr"><is><t>還有</t></is></c></row>
  <row r="2"><c r="A2" t="inlineStr"><is><t>中國</t></is></c><c r="B2" t="inlineStr"><is><t>供應甲</t></is></c><c r="C2" t="inlineStr"><is><t>CN-001</t></is></c><c r="D2"><v>100</v></c><c r="E2" t="inlineStr"><is><t>B-1</t></is></c><c r="F2" t="inlineStr"><is><t>研發</t></is></c><c r="G2" t="inlineStr"><is><t>ALPHA-42</t></is></c><c r="H2" t="inlineStr"><is><t>海外</t></is></c><c r="I2" t="inlineStr"><is><t>collision-a</t></is></c></row>
  <row r="3"><c r="A3" t="inlineStr"><is><t>日本</t></is></c><c r="B3" t="inlineStr"><is><t>供應乙</t></is></c><c r="C3" t="inlineStr"><is><t>JP-002</t></is></c><c r="D3"><v>200</v></c><c r="E3" t="inlineStr"><is><t>B-2</t></is></c><c r="F3" t="inlineStr"><is><t>狀態</t></is></c><c r="G3" t="inlineStr"><is><t>OTHER-1</t></is></c><c r="H3" t="inlineStr"><is><t>境內</t></is></c><c r="I3" t="inlineStr"><is><t>collision-b</t></is></c></row>
 </sheetData>
 <tableParts count="1"><tablePart r:id="rIdTable1"/></tableParts>
</worksheet>""",
        )
        archive.writestr(
            "xl/worksheets/_rels/sheet1.xml.rels",
            """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rIdTable1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/table" Target="../tables/table1.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "xl/tables/table1.xml",
            """<table xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 id="1" name="SourceParts" displayName="SourceParts" ref="A1:I3" headerRowCount="1">
 <tableColumns count="9"><tableColumn id="1" name="製造國"/><tableColumn id="2" name="供應商"/><tableColumn id="3" name="零件編號"/><tableColumn id="4" name="單價"/><tableColumn id="5" name="批"/><tableColumn id="6" name="部門"/><tableColumn id="7" name="款式"/><tableColumn id="8" name="狀態"/><tableColumn id="9" name="還有"/></tableColumns>
</table>""",
        )
    return output.getvalue()


class ConnectedAttachmentHybridE2ETests(unittest.IsolatedAsyncioTestCase):
    def test_completed_ingestion_inline_and_attachment_rows_reach_candidate_index(self) -> None:
        from email.message import EmailMessage
        from formowl_ingestion.extractors.mail.pst import PstMailArchiveExtractor
        from formowl_mail import PostgreSQLMailEvidenceStore
        from formowl_mail.import_workflow import (
            load_completed_ingestion_job_inputs, run_upload_session_mail_import,
        )
        import formowl_mail.issue56_sealed_source as source_owner
        import formowl_mail.hybrid as hybrid_owner
        import formowl_gateway.issue56_sealed_source_loader as gateway_owner
        from test_mail_upload_import_workflow import (
            _workflow_stores, _create_mail_upload_session, _write_pst_archive,
            _RecordingMailConnection, _pst_runner_with_messages,
            STORAGE_BACKEND_ID, OWNER_USER_ID, SESSION_ID, NOW,
            WORKSPACE_ID as IMPORT_WORKSPACE_ID,
        )

        root = _paths.fresh_test_dir("ordinary-ingestion-inline-index")
        stores = _workflow_stores(root)
        upload = _create_mail_upload_session(
            stores["upload_session_store"], audit_store=stores["audit_store"],
        )
        message = EmailMessage()
        message["From"] = "source.sender@example.test"
        message["To"] = "reader@example.test"
        message["Subject"] = "source inventory"
        message.set_content("Source inventory attached and inline. object://private/source")
        message.add_alternative(
            "<html><body><table><tr><th>Part</th><th>Origin</th></tr>"
            "<tr><td>PART-ALPHA-42</td><td>Exampleland</td></tr>"
            "</table></body></html>", subtype="html",
        )
        message.add_attachment(
            _formal_xlsx_bytes(), maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename="source.xlsx",
        )
        store = PostgreSQLMailEvidenceStore(_RecordingMailConnection())
        result = run_upload_session_mail_import(
            _write_pst_archive(root),
            upload_session_id=upload.upload_session_id,
            **{key: stores[key] for key in (
                "upload_session_store", "object_store", "asset_store", "job_store",
                "extractor_run_store", "observation_store",
            )},
            mail_evidence_store=store, storage_backend_id=STORAGE_BACKEND_ID,
            actor_user_id=OWNER_USER_ID, session_id=SESSION_ID,
            query_text="inventory", created_at=NOW,
            asset_mime_type="application/vnd.ms-outlook",
            adapter=PstMailArchiveExtractor(
                runner=_pst_runner_with_messages([message.as_bytes()]),
                scratch_parent=root / "scratch",
            ),
        )
        asset, job, observations, runs = load_completed_ingestion_job_inputs(
            result.ingestion_job_id,
            **{key: stores[key] for key in (
                "job_store", "asset_store", "observation_store", "extractor_run_store",
            )},
            requester_user_id=OWNER_USER_ID, workspace_id=IMPORT_WORKSPACE_ID,
        )
        self.assertEqual(set(job.observation_ids), {item.observation_id for item in observations})
        self.assertEqual(len(runs), 2)
        bundle = store.get_bundle(mail_import_session_id=result.mail_import_session_id)
        runtime = _contract_only_runtime()
        # The persisted owner format is float32, as emitted by the real pinned
        # encoder. Keep this contract double at that same storage precision.
        import numpy as np
        encode = runtime.dense_encoder._model.encode
        runtime.dense_encoder._model.encode = lambda texts, **kwargs: np.asarray(
            encode(texts, **kwargs), dtype=np.float32,
        )
        with (
            patch.object(source_owner, "load_issue56_target_runtime_components", return_value=runtime),
            patch.object(hybrid_owner, "_require_issue56_runtime_components", return_value=runtime),
        ):
            revision = source_owner.build_issue56_ingestion_revision(
                observations=observations, bundles=(bundle,),
                source_binding={"job_hash": sha256_json(job.to_dict()), "root_hash": asset.content_hash},
                requester_user_id=OWNER_USER_ID, workspace_id=IMPORT_WORKSPACE_ID,
            )
        inline = [
            item for item in observations
            if (item.payload or {}).get("lineage", {}).get("source_family") == "mail_inline_table"
        ]
        self.assertTrue(inline)
        self.assertTrue(all(item.asset_id == asset.asset_id for item in inline))
        self.assertTrue(all(item.payload["table_structure"]["structure_status"] == "candidate_only"
                            for item in inline))
        indexed = dict(revision.session.retrieval_observation_hashes)
        self.assertTrue(all(item.observation_id in indexed for item in inline))
        provider = gateway_owner._build_attachment_table_row_provider(
            revision.session, authorized_scope_fingerprint=sha256_json("test-scope"),
            inline_tables=True,
        )
        self.assertIsNotNone(provider)
        self.assertEqual(hybrid_owner._source_occurrence_provider_family(provider), "mail")
        self.assertTrue(all(item.structure_status == "candidate_only" for item in provider.occurrences))
        mail_hashes = hybrid_owner._source_observation_hashes_for_families(revision.session, {"mail"})
        self.assertTrue({sha256_json(item.to_dict()) for item in inline} <= mail_hashes)
        self.assertIsNotNone(gateway_owner._build_candidate_table_ledger(revision.session))
        self.assertGreater(revision.graph_build.observation_node_count, 0)
        providers = gateway_owner._build_ingestion_source_occurrence_providers(revision.session)
        self.assertIn("mail_inline_table_row_occurrence", {item.resource_kind for item in providers})
        from scripts.issue56_uat_web import _build_ingestion_revision
        with (
            patch.object(source_owner, "load_issue56_target_runtime_components", return_value=runtime),
            patch.object(hybrid_owner, "_require_issue56_runtime_components", return_value=runtime),
            patch.object(source_owner, "APPROVER_ACTOR", OWNER_USER_ID),
            patch.object(source_owner, "WORKSPACE_ID", IMPORT_WORKSPACE_ID),
            patch.object(gateway_owner, "APPROVER_ACTOR", OWNER_USER_ID),
            patch.object(gateway_owner, "WORKSPACE_ID", IMPORT_WORKSPACE_ID),
        ):
            staged = root / "staged-revision"
            report = _build_ingestion_revision(staged, [[str(root), job.ingestion_job_id]])
            loaded = source_owner.load_issue56_ingestion_revision(
                staged, expected_revision_sha256=report["revision_sha256"],
            )
            self.assertEqual(loaded.graph_build.graph_revision_fingerprint,
                             report["graph"]["graph_revision_fingerprint"])
            handler = gateway_owner.build_issue56_production_semantic_retrieval_handler(
                ingestion_revision=loaded,
            )
            payload = handler({
                "query_text": "PART-ALPHA-42的Origin", "requester_user_id": OWNER_USER_ID,
                "workspace_id": IMPORT_WORKSPACE_ID, "session_id": SESSION_ID,
            })
        public = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("extracted_value", public)
        self.assertNotIn("object://", public)
        self.assertIn("Exampleland", public)
        candidate = payload["candidate_interpretation"]
        self.assertEqual(candidate["status"], "candidate_interpretation")
        self.assertEqual(candidate["structure_status"], "candidate_only")
        self.assertEqual(candidate["value"], "Exampleland")
        self.assertFalse(candidate["canonical_kg"])
        self.assertFalse(candidate["deterministic_exact"])
        self.assertIsNone(candidate["exact_result"])
        self.assertEqual(len(candidate["governed_citations"]), 4)
        self.assertTrue(all(
            item["observation_hash"].startswith("sha256:")
            and item["lineage_fingerprint"].startswith("sha256:")
            for item in candidate["governed_citations"]
        ))
        self.assertIsNone(payload["exact_result"])
        self.assertEqual(payload["coverage"]["status"], "incomplete")
        self.assertFalse(payload["coverage"]["source_completeness_certified"])
        self.assertTrue(any(
            item["structure_status"] == "candidate_only"
            for item in payload["query_agent"]["authorized_capability_summary"]["projection_fields"]
        ))

    def test_attachment_table_structure_is_source_bound_and_region_stable(
        self,
    ) -> None:
        formal = _attachment_child_observations(
            child_asset_id="asset_formal_structure",
            content=_formal_xlsx_bytes(),
            suffix=".xlsx",
        )
        self.assertTrue(formal)
        self.assertTrue(all(isinstance(item, Observation) for item in formal))
        formal_data_row = next(
            item
            for item in formal
            if item.observation_type == "table_row"
            and item.location["row_index"] == 2
        )
        formal_data_cell = next(
            item
            for item in formal
            if item.observation_type == "table_cell"
            and item.location["row_index"] == 2
            and item.location["cell_index"] == 2
        )
        self.assertEqual(
            formal_data_row.payload["table_structure"],
            {
                "structure_status": "source_provided",
                "formal_table_index": 1,
                "table_name": "SourceTable",
                "table_ref": "A1:B2",
                "min_column_index": 1,
                "max_column_index": 2,
                "min_row_index": 1,
                "max_row_index": 2,
                "header_enabled": True,
                "header_row_index": 1,
                "totals_row_index": None,
                "columns": [
                    {"cell_index": 1, "name": "Category"},
                    {"cell_index": 2, "name": "Code"},
                ],
                "row_role": "data",
            },
        )
        self.assertEqual(
            formal_data_cell.payload["table_structure"]["column_name"],
            "Code",
        )

        candidate = _attachment_child_observations(
            child_asset_id="asset_candidate_structure",
            content=(
                b"Report,\n"
                b"Column A,Column B\n"
                b"first value,first code\n"
                b"second value,second code\n"
            ),
        )
        candidate_rows = {
            item.location["row_index"]: item
            for item in candidate
            if item.observation_type == "table_row"
        }
        self.assertEqual(
            candidate_rows[1].payload["table_structure"]["structure_status"],
            "unavailable",
        )
        for row_index in (2, 3, 4):
            structure = candidate_rows[row_index].payload["table_structure"]
            self.assertEqual(structure["structure_status"], "candidate_only")
            self.assertEqual(structure["header_row_index"], 2)
            self.assertEqual(structure["region_start_row_index"], 1)
            self.assertEqual(structure["region_end_row_index"], 4)
        self.assertEqual(
            candidate_rows[2].payload["table_structure"]["row_role"],
            "header_candidate",
        )
        self.assertEqual(
            candidate_rows[4].payload["table_structure"]["columns"],
            [
                {"cell_index": 1, "name": "Column A"},
                {"cell_index": 2, "name": "Column B"},
            ],
        )

    def test_table_provider_partitions_rows_and_reports_asset_gaps_separately(
        self,
    ) -> None:
        from formowl_gateway import issue56_sealed_source_loader as gateway_loader

        formal_parent = _observation(
            observation_id="observation_formal_parent",
            observation_type="email_attachment_occurrence",
            text="formal attachment",
            payload={"child_asset_id": "asset_formal_provider"},
        )
        candidate_parent = _observation(
            observation_id="observation_candidate_parent",
            observation_type="email_attachment_occurrence",
            text="candidate attachment",
            payload={"child_asset_id": "asset_candidate_provider"},
        )
        unsupported_parent = _observation(
            observation_id="observation_unsupported_parent",
            observation_type="email_attachment_occurrence",
            text="unsupported attachment",
            payload={"attachment_extraction_status": "unsupported"},
        )
        formal = _attachment_child_observations(
            child_asset_id="asset_formal_provider",
            content=_formal_xlsx_bytes(),
            suffix=".xlsx",
        )
        candidate = _attachment_child_observations(
            child_asset_id="asset_candidate_provider",
            content=b"Category,Code\nROW-FILTER-42,CANDIDATE-CODE\n",
        )
        observations = (
            formal_parent,
            candidate_parent,
            unsupported_parent,
            *formal,
            *candidate,
        )
        authorized_source = validated_authorized_semantic_source(
            source_kind=AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
            workspace_id=WORKSPACE_ID,
            source_scope_ids=(SOURCE_SCOPE_ID,),
            authorized_permission_scopes=(PermissionScope.project(SOURCE_SCOPE_ID),),
        )
        parent_lineages = tuple(
            source_occurrence_lineage_from_observation(
                observation,
                authorized_source=authorized_source,
            )
            for observation in (
                formal_parent,
                candidate_parent,
                unsupported_parent,
            )
        )
        lineages = normalized_authorized_observation_lineages(
            observations,
            authorized_source=authorized_source,
            occurrence_lineages=parent_lineages,
        )
        authorized_hashes = tuple(
            sorted(
                (
                    observation.observation_id,
                    sha256_json(observation.to_dict()),
                )
                for observation in observations
            )
        )
        provider = gateway_loader._build_attachment_table_row_provider(
            SimpleNamespace(
                authorized_observations=observations,
                authorized_observation_hashes=authorized_hashes,
                occurrence_lineages=lineages,
                index=SimpleNamespace(
                    _runtime_components=_contract_only_runtime(),
                ),
                requester_user_id=REQUESTER_ID,
                workspace_id=WORKSPACE_ID,
                authorized_source_scope_ids=(SOURCE_SCOPE_ID,),
            ),
            authorized_scope_fingerprint=sha256_json("table-row-scope"),
        )
        assert provider is not None
        self.assertEqual(provider.authorized_occurrence_scope_count, 3)
        self.assertEqual(provider.extractable_occurrence_scope_count, 2)
        self.assertEqual(provider.unresolved_count, 1)
        self.assertEqual(provider.unsupported_count, 0)
        self.assertEqual(provider.encrypted_count, 0)
        self.assertEqual(
            provider.source_asset_reason_counts,
            (("unsupported", 1),),
        )
        self.assertEqual(len(provider.occurrences), 2)

        runtime_components = _contract_only_runtime()
        query_text = "哪些 Code 的 Category 是 ROW-FILTER-42，Code"
        grounding = runtime_components.tokenizer_profile.analyze_query_grounding(
            query_text
        )
        ordered_lexical_candidates = tuple(
            (
                sha256_json(
                    [
                        "ordered_query_grounding_term_v1",
                        term.start,
                        term.end,
                        term.normalized_term,
                        term.grammar_role,
                    ]
                ),
                tuple(
                    sha256_json(token)
                    for token in sorted(
                        runtime_components.tokenizer_profile.analyze(
                            term.normalized_term
                        ).tokens,
                        key=lambda token: (
                            token != term.normalized_term,
                            -len(token),
                            token,
                        ),
                    )
                ),
            )
            for term in grounding.terms
            if term.grammar_role == "lexical"
        )
        grammar_ledger = tuple(
            (
                sha256_json(
                    [
                        "ordered_query_grounding_term_v1",
                        term.start,
                        term.end,
                        term.normalized_term,
                        term.grammar_role,
                    ]
                ),
                term.grammar_role,
            )
            for term in grounding.terms
            if term.grammar_role != "lexical"
        )
        partition = provider.partition_ordered_lexical_candidates(
            ordered_lexical_candidates
        )
        self.assertGreaterEqual(
            len(partition.lexical_term_ledger),
            len({binding[2] for binding in partition.lexical_term_ledger}),
        )
        plan = route_semantic_query(
            query_text=query_text,
            requester_user_id=REQUESTER_ID,
            workspace_id=WORKSPACE_ID,
            source_scope_ids=(SOURCE_SCOPE_ID,),
            effective_graph_view=EffectiveGraphView(
                requester_user_id=REQUESTER_ID,
                user_graph_revision_id="user_graph_table_row",
                canonical_graph_revision_id="canonical_graph_table_row",
                ontology_revision_id="ontology_table_row",
                assembly_policy_id="assembly_table_row",
            ),
            exact_inventory_kind=provider.resource_kind,
            exact_filter_term_hashes=partition.filter_term_hashes,
            exact_projection_term_hashes=partition.projection_column_hashes,
            exact_column_value_hash_pairs=partition.column_value_hash_pairs,
            exact_lexical_term_ledger=partition.lexical_term_ledger,
            exact_grammar_term_ledger=grammar_ledger,
            exact_grammar_policy_fingerprint=(
                grounding.grammar_policy_fingerprint
            ),
            exact_source_occurrence_provider_fingerprint=(
                provider.provider_fingerprint
            ),
            exact_topic_term_hashes=partition.filter_term_hashes,
            exact_normalized_field=provider.normalized_field,
            exact_predicate=provider.predicate,
            exact_operator=provider.operator,
            authorized_source=authorized_source,
            query_class_override="exact_set_or_inventory",
        )
        result = execute_deterministic_source_occurrence_inventory(
            plan=plan,
            provider=provider,
            expected_authorized_scope_fingerprint=provider.authorized_scope_fingerprint,
            page_size=10,
            cursor=None,
        )
        self.assertEqual(result.status, "incomplete")
        self.assertFalse(result.coverage.authorized_scope_complete)
        self.assertEqual(
            result.source_occurrence_page["authorized_occurrence_scope_count"],
            3,
        )
        self.assertEqual(
            result.source_occurrence_page["extractable_occurrence_scope_count"],
            2,
        )
        self.assertEqual(
            result.source_occurrence_page["source_asset_reason_counts"],
            [{"reason": "unsupported", "asset_count": 1}],
        )
        source_provided = next(
            item
            for item in provider.occurrences
            if item.structure_status == "source_provided"
        )
        candidate_only = next(
            item
            for item in provider.occurrences
            if item.structure_status == "candidate_only"
        )
        self.assertEqual(result.exact_count, 1)
        self.assertEqual(result.returned_item_count, 1)
        self.assertEqual(
            {item.item_hash for item in result.items},
            {source_provided.item_hash},
        )
        self.assertNotIn(
            candidate_only.item_hash,
            {item.item_hash for item in result.items},
        )
        self.assertEqual(result.items[0].structure_status, "source_provided")
        self.assertTrue(result.items[0].structured_values)
        self.assertTrue(result.items[0].governed_references)
        self.assertEqual(
            result.source_occurrence_page["candidate_only_occurrence_count"],
            1,
        )

        candidate_only_provider = replace(
            provider,
            provider_id="candidate_only_table_row_provider_v1",
            occurrences=(candidate_only,),
            authorized_occurrence_scope_count=1,
            extractable_occurrence_scope_count=1,
            unresolved_count=0,
            source_asset_reason_counts=(),
        )
        candidate_only_result = execute_deterministic_source_occurrence_inventory(
            plan=replace(
                plan,
                exact_source_occurrence_provider_fingerprint=(
                    candidate_only_provider.provider_fingerprint
                ),
            ),
            provider=candidate_only_provider,
            expected_authorized_scope_fingerprint=(
                candidate_only_provider.authorized_scope_fingerprint
            ),
            page_size=1,
            cursor=None,
        )
        self.assertEqual(candidate_only_result.status, "incomplete")
        self.assertFalse(
            candidate_only_result.coverage.authorized_scope_complete
        )
        self.assertEqual(candidate_only_result.exact_count, 0)
        self.assertEqual(candidate_only_result.returned_item_count, 0)
        self.assertEqual(candidate_only_result.cited_observation_count, 0)
        self.assertEqual(candidate_only_result.items, ())
        self.assertIsNone(
            candidate_only_result.source_occurrence_page["next_cursor"]
        )
        self.assertEqual(
            candidate_only_result.source_occurrence_page[
                "candidate_only_occurrence_count"
            ],
            1,
        )

        filter_pair, projection_column = plan.exact_column_value_hash_pairs[0], plan.exact_projection_term_hashes[0]
        candidate_filter = next(binding for binding in candidate_only.structured_column_bindings if (binding[0], binding[2]) == filter_pair)
        candidate_projection = next(binding for binding in candidate_only.structured_column_bindings if binding[0] == projection_column)
        link_column = sha256_json("candidate-link-column")
        link_value = candidate_projection[2]
        candidate_source = replace(
            candidate_only,
            structured_column_bindings=(candidate_filter, (link_column, *candidate_projection[1:])),
        )
        target_projection = next(binding for binding in source_provided.structured_column_bindings if binding[0] == projection_column)
        target_link = (
            link_column, sha256_json("candidate-link"), link_value,
            "candidate-link", candidate_projection[4], *target_projection[5:],
        )
        source_target = replace(
            source_provided,
            value_bindings=tuple(
                sorted((*source_provided.value_bindings,
                        (link_value, link_value, *target_projection[5:])))
            ),
            projection_bindings=(*source_provided.projection_bindings, target_link[3:]),
            structured_column_bindings=tuple(
                binding for binding in (*source_provided.structured_column_bindings, target_link)
                if (binding[0], binding[2]) != filter_pair
            ),
        )
        candidate_link_provider = replace(
            provider,
            provider_id="candidate_filter_source_link_provider_v1",
            occurrences=(candidate_source, source_target),
            authorized_occurrence_scope_count=2,
            extractable_occurrence_scope_count=2,
            unresolved_count=0,
            source_asset_reason_counts=(),
        )
        candidate_link_result = execute_deterministic_source_occurrence_inventory(
            plan=replace(
                plan,
                exact_source_occurrence_provider_fingerprint=candidate_link_provider.provider_fingerprint,
            ),
            provider=candidate_link_provider,
            expected_authorized_scope_fingerprint=candidate_link_provider.authorized_scope_fingerprint,
            page_size=1,
            cursor=None,
        )
        self.assertEqual(candidate_link_result.status, "incomplete")
        self.assertEqual(
            (candidate_link_result.exact_count, candidate_link_result.returned_item_count,
             candidate_link_result.cited_observation_count, candidate_link_result.items),
            (0, 0, 0, ()),
        )
        self.assertNotEqual(
            plan.plan_fingerprint,
            replace(plan, exact_projection_term_hashes=()).plan_fingerprint,
        )
        missing_required_hash = sha256_json("missing table row value")
        with self.assertRaisesRegex(
            ContractValidationError,
            "query filter slots are inconsistent",
        ):
            execute_deterministic_source_occurrence_inventory(
                plan=replace(
                    plan,
                    exact_filter_term_hashes=tuple(
                        sorted((*plan.exact_filter_term_hashes, missing_required_hash))
                    ),
                    exact_topic_term_hashes=tuple(
                        sorted((*plan.exact_topic_term_hashes, missing_required_hash))
                    ),
                ),
                provider=provider,
                expected_authorized_scope_fingerprint=(
                    provider.authorized_scope_fingerprint
                ),
                page_size=10,
                cursor=None,
            )
    def test_provider_build_accepts_mixed_mail_and_table_row_retrieval(
        self,
    ) -> None:
        from formowl_gateway import issue56_sealed_source_loader as gateway_loader

        mail_observation = _observation(
            observation_id="observation_mixed_mail",
            observation_type="email_message",
            text="mail participant evidence",
            payload={"sender": "Alice <alice@example.test>"},
        )
        parent_attachment = _observation(
            observation_id="observation_mixed_parent",
            observation_type="email_attachment_occurrence",
            text="mixed attachment",
            payload={"child_asset_id": "asset_mixed_child"},
        )
        child_observations = _attachment_child_observations(
            child_asset_id="asset_mixed_child",
            query_text="MIXED-ROW-42",
        )
        child_row = next(
            item
            for item in child_observations
            if item.observation_type == "table_row"
        )
        observations = (mail_observation, parent_attachment, *child_observations)
        retrieval_observations = (mail_observation, parent_attachment, child_row)
        authorized_source = validated_authorized_semantic_source(
            source_kind=AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
            workspace_id=WORKSPACE_ID,
            source_scope_ids=(SOURCE_SCOPE_ID,),
            authorized_permission_scopes=(PermissionScope.project(SOURCE_SCOPE_ID),),
        )
        lineages = normalized_authorized_observation_lineages(
            observations,
            authorized_source=authorized_source,
            occurrence_lineages=tuple(
                source_occurrence_lineage_from_observation(
                    item,
                    authorized_source=authorized_source,
                )
                for item in observations
                if item.modality == "mail"
            ),
        )
        authorized_hashes = {
            item.observation_id: sha256_json(item.to_dict())
            for item in observations
        }
        retrieval_hashes = {
            item.observation_id: authorized_hashes[item.observation_id]
            for item in retrieval_observations
        }
        binding = sha256_json("mixed-provider-binding")
        session = SimpleNamespace(
            authorized_source=authorized_source,
            authorized_observations=observations,
            authorized_observation_hashes=authorized_hashes,
            retrieval_observation_hashes=retrieval_hashes,
            occurrence_lineages=lineages,
            requester_user_id=REQUESTER_ID,
            workspace_id=WORKSPACE_ID,
            authorized_source_scope_ids=(SOURCE_SCOPE_ID,),
            source_session_binding_fingerprint=binding,
            index=SimpleNamespace(
                _runtime_components=_contract_only_runtime(),
            ),
        )
        scope_fingerprint = authorized_source_occurrence_scope_fingerprint(
            requester_user_id=session.requester_user_id,
            workspace_id=session.workspace_id,
            source_scope_ids=session.authorized_source_scope_ids,
            authorized_observation_hashes=session.authorized_observation_hashes,
            source_session_binding_fingerprint=binding,
        )
        table_provider = gateway_loader._build_attachment_table_row_provider(
            session,
            authorized_scope_fingerprint=scope_fingerprint,
        )
        assert table_provider is not None
        capability_mapping: dict[str, set[str]] = {}
        for occurrence in table_provider.occurrences:
            for column_hash, candidate_hash, *_rest in (
                occurrence.structured_column_bindings
            ):
                capability_mapping.setdefault(column_hash, set()).add(candidate_hash)
        occurrence_ids = tuple(sorted({
            item.message_occurrence_id for item in lineages
        }))
        mention_fingerprint = sha256_json("mixed-provider-mentions")
        loaded = SimpleNamespace(
            session=session,
            identifier_mention_batch=SimpleNamespace(
                identity_scope_mode="workspace_only_v1",
                workspace_id=WORKSPACE_ID,
                tenant_id=None,
                occurrence_count=0,
                candidate_mentions=(),
                batch_fingerprint=mention_fingerprint,
            ),
            graph_build=SimpleNamespace(
                identifier_mention_count=0,
                authorized_identifier_mention_count=0,
            ),
            source_bundle=SimpleNamespace(
                message_occurrences=tuple(
                    SimpleNamespace(message_occurrence_id=item)
                    for item in occurrence_ids
                )
            ),
        )
        snapshot = {
            "snapshot_fingerprint": "snapshot_mixed_provider",
            "source_snapshot_fingerprint": "source_mixed_provider",
            "parsed_mail_observations": [
                item.to_dict() for item in observations if item.modality == "mail"
            ],
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            snapshot_path = Path(temporary_directory) / "retrieval.json"
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
            snapshot_sha256 = "sha256:" + hashlib.sha256(
                snapshot_path.read_bytes()
            ).hexdigest()
            safe_binding = {
                "retrieval_snapshot_byte_sha256": snapshot_sha256,
                "retrieval_snapshot_fingerprint": snapshot[
                    "snapshot_fingerprint"
                ],
                "source_snapshot_fingerprint": snapshot[
                    "source_snapshot_fingerprint"
                ],
                "source_identifier_mention_batch_fingerprint": mention_fingerprint,
            }
            with (
                patch.dict(
                    os.environ,
                    {
                        "FORMOWL_ISSUE56_RETRIEVAL_SNAPSHOT_PATH": str(
                            snapshot_path
                        ),
                        "FORMOWL_ISSUE56_RETRIEVAL_SNAPSHOT_SHA256": snapshot_sha256,
                    },
                    clear=False,
                ),
                patch.object(
                    gateway_loader,
                    "_load_source_schema_capability_mapping",
                    return_value={
                        column_hash: frozenset(candidate_hashes)
                        for column_hash, candidate_hashes in capability_mapping.items()
                    },
                ),
            ):
                providers = (
                    gateway_loader._build_mail_source_occurrence_providers(
                        loaded,
                        safe_binding=safe_binding,
                    )
                )
        fields = {provider.normalized_field for provider in providers}
        self.assertIn("participant.any.local_part", fields)
        self.assertIn("participant.from.local_part", fields)
        self.assertIn(
            "message_occurrence.direct_source_identifier_v1",
            fields,
        )
        self.assertIn("table.row.cell_value", fields)
        self.assertEqual(len(providers), 7)
        runtime_components = _contract_only_runtime()
        query_lineages = tuple(
            source_occurrence_lineage_from_observation(
                observation,
                authorized_source=authorized_source,
            )
            for observation in observations
            if observation.modality == "mail"
        )
        snippet_index, _ = build_authorized_observation_snippet_index(
            retrieval_observations,
            authorized_source=authorized_source,
            occurrence_lineages=query_lineages,
            authorized_observation_hash_by_id=retrieval_hashes,
            tokenizer_profile=runtime_components.tokenizer_profile,
        )
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=runtime_components,
        ):
            query_session = build_authorized_semantic_observation_session(
                authorized_source=authorized_source,
                snippet_index=snippet_index,
                authorized_observations=observations,
                retrieval_observations=retrieval_observations,
                occurrence_lineages=query_lineages,
                requester_user_id=REQUESTER_ID,
            )
        graph_view = build_authorized_source_backed_effective_graph_view(
            session=query_session,
            source_binding_fingerprint=sha256_json("mixed-provider-query"),
        ).effective_graph_view
        query_scope_fingerprint = authorized_source_occurrence_scope_fingerprint(
            requester_user_id=query_session.requester_user_id,
            workspace_id=query_session.workspace_id,
            source_scope_ids=query_session.authorized_source_scope_ids,
            authorized_observation_hashes=query_session.authorized_observation_hashes,
            source_session_binding_fingerprint=(
                query_session.source_session_binding_fingerprint or ""
            ),
        )
        query_providers = tuple(
            replace(
                provider,
                authorized_scope_fingerprint=query_scope_fingerprint,
            )
            for provider in providers
        )
        attached_session = attach_authorized_source_occurrence_providers(
            query_session,
            query_providers,
        )
        participant_provider = next(
            provider
            for provider in query_providers
            if provider.normalized_field == "participant.any.local_part"
        )
        participant_result = attached_session.query(
            query_text="alice@example.test",
            effective_graph_view=graph_view,
            exact_inventory_kind=participant_provider.inventory_kind_alias,
            exact_field=participant_provider.normalized_field,
        )
        self.assertEqual(
            participant_result.exact_result.returned_item_count,
            1,
        )

    async def test_multilevel_attachment_headers_filter_and_project_over_asgi(
        self,
    ) -> None:
        from formowl_auth import FileAuditLogStore
        from formowl_gateway import issue56_sealed_source_loader as gateway_loader
        from formowl_ingestion.storage import UploadSessionStore
        from formowl_mail import build_mail_upload_session_handler

        row_filter = "ALPHA-42"
        query_text = f"{row_filter} 的 批"
        paraphrased_query_text = f"批 {row_filter}"
        self.assertEqual(deterministic_query_class(query_text), "evidence_lookup")
        parent_attachment = _observation(
            observation_id="observation_attachment_occurrence",
            observation_type="email_attachment_occurrence",
            text="Authorized attachment occurrence",
            payload={
                "attachment_id": "attachment_opaque_1",
                "child_asset_id": "asset_attachment_child",
            },
        )
        child_asset_id = "asset_attachment_child"
        child_observations = _attachment_child_observations(
            child_asset_id=child_asset_id,
            content=_source_provided_multilevel_xlsx_bytes(),
            suffix=".xlsx",
        )
        child_row = next(
            observation
            for observation in child_observations
            if observation.observation_type == "table_row"
            and row_filter in (observation.text or "")
        )
        japan_row = next(
            observation
            for observation in child_observations
            if observation.observation_type == "table_row"
            and "日本" in (observation.text or "")
        )
        child_cell = next(
            observation
            for observation in child_observations
            if observation.observation_type == "table_cell"
            and observation.text == row_filter
        )
        observations = (parent_attachment, *child_observations)
        retrieval_observations = (parent_attachment, child_row)
        authorized_source = validated_authorized_semantic_source(
            source_kind=AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
            workspace_id=WORKSPACE_ID,
            source_scope_ids=(SOURCE_SCOPE_ID,),
            authorized_permission_scopes=(PermissionScope.project(SOURCE_SCOPE_ID),),
        )
        lineages = tuple(
            source_occurrence_lineage_from_observation(
                observation,
                authorized_source=authorized_source,
            )
            for observation in observations
            if observation.modality == "mail"
        )
        authorized_hashes = {
            observation.observation_id: sha256_json(observation.to_dict())
            for observation in observations
        }
        retrieval_hashes = {
            observation.observation_id: authorized_hashes[observation.observation_id]
            for observation in retrieval_observations
        }
        runtime_components = _contract_only_runtime()
        snippet_index, _ = build_authorized_observation_snippet_index(
            retrieval_observations,
            authorized_source=authorized_source,
            occurrence_lineages=lineages,
            authorized_observation_hash_by_id=retrieval_hashes,
            tokenizer_profile=runtime_components.tokenizer_profile,
        )
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=runtime_components,
        ):
            session = build_authorized_semantic_observation_session(
                authorized_source=authorized_source,
                snippet_index=snippet_index,
                authorized_observations=observations,
                retrieval_observations=retrieval_observations,
                occurrence_lineages=lineages,
                requester_user_id=REQUESTER_ID,
            )
        candidate_by_hash = {
            candidate.source_observation_hash: candidate
            for candidate in session.index.candidates
        }
        self.assertEqual(
            session.authorized_observation_hashes,
            tuple(sorted(authorized_hashes.items())),
        )
        self.assertEqual(
            session.retrieval_observation_hashes,
            tuple(sorted(retrieval_hashes.items())),
        )
        self.assertEqual(set(candidate_by_hash), set(retrieval_hashes.values()))
        self.assertEqual(
            candidate_by_hash[
                authorized_hashes[parent_attachment.observation_id]
            ].coherence_group_hash,
            candidate_by_hash[authorized_hashes[child_row.observation_id]].coherence_group_hash,
        )
        child_cell_hashes = {
            authorized_hashes[observation.observation_id]
            for observation in child_observations
            if observation.observation_type == "table_cell"
        }
        self.assertTrue(
            child_cell_hashes.issubset(dict(session.authorized_observation_hashes).values())
        )
        self.assertTrue(child_cell_hashes.isdisjoint(candidate_by_hash))
        cell_lineage = next(
            lineage
            for lineage in session.occurrence_lineages
            if lineage.source_observation_id == child_cell.observation_id
        )
        self.assertIsInstance(cell_lineage, MailAttachmentChildOccurrenceLineage)
        self.assertEqual(
            cell_lineage.parent_attachment_observation_id,
            parent_attachment.observation_id,
        )

        graph_build = build_authorized_source_backed_effective_graph_view(
            session=session,
            source_binding_fingerprint=sha256_json(
                "attachment_hybrid_source_binding"
            ),
        )
        graph_view = graph_build.effective_graph_view
        graph_source_observation_ids = {
            observation_id
            for item in (*graph_view.visible_nodes, *graph_view.visible_edges)
            for observation_id in item.properties.get("source_observation_ids", ())
        }
        self.assertEqual(graph_build.source_observation_count, len(retrieval_observations))
        self.assertEqual(graph_source_observation_ids, set(retrieval_hashes))
        self.assertTrue(
            {
                observation.observation_id
                for observation in child_observations
                if observation.observation_type == "table_cell"
            }.isdisjoint(graph_source_observation_ids)
        )
        tampered_node = replace(
            graph_view.visible_nodes[0],
            properties={
                **graph_view.visible_nodes[0].properties,
                "source_observation_ids": [child_cell.observation_id],
            },
        )
        tampered_graph_view = replace(
            graph_view,
            visible_nodes=[tampered_node, *graph_view.visible_nodes[1:]],
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "effective graph content snapshot is unavailable",
        ):
            session.query(
                query_text=query_text,
                effective_graph_view=tampered_graph_view,
            )
        table_provider = gateway_loader._build_attachment_table_row_provider(
            session,
            authorized_scope_fingerprint=authorized_source_occurrence_scope_fingerprint(
                requester_user_id=session.requester_user_id,
                workspace_id=session.workspace_id,
                source_scope_ids=session.authorized_source_scope_ids,
                authorized_observation_hashes=session.authorized_observation_hashes,
                source_session_binding_fingerprint=(
                    session.source_session_binding_fingerprint or ""
                ),
            ),
        )
        assert table_provider is not None
        self.assertTrue(table_provider.occurrences)
        self.assertTrue(
            all(
                occurrence.structure_status == "source_provided"
                for occurrence in table_provider.occurrences
            )
        )
        part_number_hash = sha256_json(
            runtime_components.tokenizer_profile.normalize_exact_identifier_surface(
                "零件編號"
            )
        )
        self.assertIn(
            part_number_hash,
            {
                candidate_hash
                for occurrence in table_provider.occurrences
                for _column_hash, candidate_hash, *_ in (
                    occurrence.structured_column_bindings
                )
            },
        )
        structured_session = attach_authorized_source_occurrence_providers(
            session,
            (table_provider,),
        )
        structured_query_text = "把海外的部門跟款式還有狀態整理出來"
        structured_trace = SemanticPhaseTrace()
        structured_result = structured_session.query(
            query_text=structured_query_text,
            effective_graph_view=graph_view,
            phase_trace=structured_trace,
        )
        self.assertEqual(
            {
                item["phase"]: item["outcome"]
                for item in structured_trace.to_safe_dict()["phases"]
            }["routing_plan"],
            "completed",
        )
        self.assertEqual(
            structured_result.query_class,
            "exact_set_or_inventory",
        )
        structured_exact = structured_result.exact_result
        assert structured_exact is not None
        self.assertEqual(structured_exact.status, "complete_authorized_scope")
        self.assertTrue(structured_exact.coverage.authorized_scope_complete)
        self.assertEqual(
            structured_exact.source_occurrence_page[
                "candidate_only_occurrence_count"
            ],
            0,
        )
        self.assertTrue(structured_exact.items)
        self.assertTrue(
            all(item.governed_references for item in structured_exact.items)
        )
        structured_fields = {
            field
            for item in structured_exact.items
            for field, _value, _citation, _lineage in item.structured_values
        }
        self.assertEqual(structured_fields, {"部門", "款式", "狀態"})
        self.assertNotIn("還有", structured_fields)
        with self.assertRaisesRegex(
            ContractValidationError,
            "source occurrence query projection binding is ambiguous",
        ):
            structured_session.query(
                query_text="把海外的部門月球款式還有狀態整理出來",
                effective_graph_view=graph_view,
            )
        operator_terms = {
            term.normalized_term: term.grammar_role
            for term in runtime_components.tokenizer_profile.analyze_query_grounding(
                paraphrased_query_text
            ).terms
        }
        self.assertEqual(operator_terms["批"], "operator")
        with patch(
            "formowl_mail.hybrid.route_semantic_query",
            wraps=route_semantic_query,
        ) as routed:
            paraphrased_result = structured_session.query(
                query_text=paraphrased_query_text,
                effective_graph_view=graph_view,
            )
        routed_arguments = routed.call_args.kwargs
        source_provided_bindings = tuple(
            binding
            for occurrence in table_provider.occurrences
            if occurrence.structure_status == "source_provided"
            for binding in occurrence.structured_column_bindings
        )
        filter_bindings = tuple(
            binding for binding in source_provided_bindings
            if binding[3] == "款式" and binding[4] == row_filter
        )
        projection_bindings = tuple(
            binding for binding in source_provided_bindings
            if binding[3] == "批" and binding[4] == "B-1"
        )
        expected_projection_values = {
            (binding[3], binding[4], binding[5], binding[6])
            for binding in projection_bindings
        }
        self.assertEqual(len({binding[0] for binding in filter_bindings}), 1)
        self.assertEqual(len(expected_projection_values), 1)
        self.assertEqual(
            routed_arguments["exact_source_occurrence_provider_fingerprint"],
            table_provider.provider_fingerprint,
        )
        routed_filter_pairs = set(routed_arguments["exact_column_value_hash_pairs"])
        self.assertEqual(len(routed_filter_pairs), 1)
        self.assertTrue(
            routed_filter_pairs
            <= {(binding[0], binding[2]) for binding in filter_bindings}
        )
        self.assertEqual(
            tuple(routed_arguments["exact_filter_term_hashes"]),
            (next(iter(routed_filter_pairs))[1],),
        )
        self.assertEqual(
            tuple(routed_arguments["exact_projection_term_hashes"]),
            tuple(sorted({binding[0] for binding in projection_bindings})),
        )
        self.assertEqual(
            len(routed_arguments["exact_lexical_term_ledger"])
            + len(routed_arguments["exact_grammar_term_ledger"]),
            len(operator_terms),
        )
        self.assertEqual(
            {binding[1] for binding in routed_arguments["exact_lexical_term_ledger"]},
            {"filter_value", "projection_field"},
        )
        self.assertEqual(paraphrased_result.query_class, "exact_set_or_inventory")
        assert paraphrased_result.exact_result is not None
        self.assertEqual(paraphrased_result.exact_result.status, "complete_authorized_scope")
        self.assertTrue(paraphrased_result.exact_result.coverage.authorized_scope_complete)
        self.assertEqual(paraphrased_result.exact_result.returned_item_count, 1)
        self.assertEqual(len(paraphrased_result.exact_result.items), 1)
        paraphrased_item = paraphrased_result.exact_result.items[0]
        self.assertEqual(
            paraphrased_item.structured_values,
            tuple(sorted(expected_projection_values)),
        )
        expected_references = {
            (binding[5], binding[6])
            for binding in (*filter_bindings, *projection_bindings)
        }
        self.assertTrue(expected_references <= set(paraphrased_item.governed_references))
        self.assertTrue(
            {citation_hash for citation_hash, _ in expected_references}
            <= set(paraphrased_item.cited_observation_hashes)
        )
        cjk_projection_result = structured_session.query(
            query_text=f"{row_filter} 的 部門",
            effective_graph_view=graph_view,
        )
        self.assertEqual(
            cjk_projection_result.query_class,
            "exact_set_or_inventory",
        )
        assert cjk_projection_result.exact_result is not None
        self.assertTrue(cjk_projection_result.exact_result.items)
        overlap_result = structured_session.query(
            query_text=f"{row_filter} 的 狀態",
            effective_graph_view=graph_view,
        )
        self.assertEqual(overlap_result.query_class, "exact_set_or_inventory")
        overlap_exact = overlap_result.exact_result
        assert overlap_exact is not None
        self.assertTrue(overlap_exact.items)
        self.assertEqual(
            {
                field
                for item in overlap_exact.items
                for field, _value, _citation, _lineage in item.structured_values
            },
            {"狀態"},
        )
        self.assertTrue(
            all(item.governed_references for item in overlap_exact.items)
        )
        missing_identifier_result = structured_session.query(
            query_text="MISSING-99 的 批",
            effective_graph_view=graph_view,
        )
        self.assertEqual(missing_identifier_result.status, "incomplete")
        self.assertEqual(missing_identifier_result.query_class, "evidence_lookup")
        self.assertEqual(
            missing_identifier_result.warnings,
            ("authorized_evidence_identifier_not_found",),
        )
        self.assertIsNone(missing_identifier_result.exact_result)
        self.assertEqual(missing_identifier_result.answer_citation_hashes, ())
        ambiguous_result = replace(
            structured_session,
            source_occurrence_providers=(
                table_provider,
                replace(
                    table_provider,
                    provider_id="attachment_table_row_peer_provider_v1",
                ),
            ),
        ).query(
            query_text=query_text,
            effective_graph_view=graph_view,
        )
        self.assertEqual(ambiguous_result.query_class, "evidence_lookup")
        self.assertIsNone(ambiguous_result.exact_result)
        loaded = SimpleNamespace(
            session=session,
            effective_graph_view=graph_view,
            safe_binding={},
            observations=session.authorized_observations,
            query_bundle=SimpleNamespace(
                mail_import_session=SimpleNamespace(
                    mail_import_session_id=SOURCE_SCOPE_ID,
                ),
            ),
        )
        with (
            patch.object(gateway_loader, "APPROVER_ACTOR", REQUESTER_ID),
            patch.object(gateway_loader, "WORKSPACE_ID", WORKSPACE_ID),
            patch.object(
                gateway_loader,
                "_load_approved_sealed_source",
                return_value=loaded,
            ),
            patch.object(
                gateway_loader,
                "_validated_owner_safe_binding",
                return_value={},
            ),
            patch.object(
                gateway_loader,
                "_build_mail_source_occurrence_providers",
                return_value=(table_provider,),
            ),
        ):
            retrieval_handler = (
                gateway_loader.build_issue56_production_semantic_retrieval_handler()
            )

        with tempfile.TemporaryDirectory() as temporary_directory:
            environment = _write_runtime_environment(Path(temporary_directory))
            config = ConnectedRuntimeConfig.from_env_and_secrets(environment)
            upload_handler = build_mail_upload_session_handler(
                upload_session_store=UploadSessionStore(config.data_dir),
                audit_store=FileAuditLogStore(config.data_dir),
                expires_at_provider=lambda: "2030-01-01T00:00:00+00:00",
            )
            with patch.object(
                runtime_module.PostgreSQLOAuthRepository,
                "connect",
                return_value=_FakeRepository(),
            ):
                connected = await ConnectedRuntime.compose(
                    config,
                    semantic_gateway=SemanticMcpGateway(
                        upload_session_handler=upload_handler,
                        retrieval_handler=retrieval_handler,
                    ),
                    http_client=_FakeHttpClient(),
                )
            connected.preflight = AsyncMock(return_value={"status": "ready"})
            principal = OAuthPrincipal(
                user_id=REQUESTER_ID,
                external_identity_id="external_attachment_hybrid",
                oauth_client_id="chatgpt_closed_beta",
                token_session_id="oauth_attachment_hybrid",
                scopes=("formowl.use",),
                resource=config.oauth.resource,
            )
            timestamp = "2026-08-29T00:00:00+00:00"
            actor = ActorContext(
                user=User(
                    user_id=REQUESTER_ID,
                    display_name="Attachment hybrid owner",
                    status="active",
                    created_at=timestamp,
                ),
                session_identity=SessionIdentity(
                    session_id=principal.token_session_id,
                    selected_user_id=REQUESTER_ID,
                    selected_at=timestamp,
                    selection_method="google_oidc_oauth",
                ),
                workspace_memberships=[
                    WorkspaceMember(
                        user_id=REQUESTER_ID,
                        workspace_id=WORKSPACE_ID,
                        role="owner",
                    )
                ],
                current_workspace_id=WORKSPACE_ID,
                current_workspace_role="owner",
                external_identity_id=principal.external_identity_id,
                oauth_client_id=principal.oauth_client_id,
                oauth_token_session_id=principal.token_session_id,
                auth_mode="google_oidc_oauth",
                production_authentication=True,
            )
            try:
                with (
                    patch.object(
                        connected.bridge,
                        "authenticate_access_token",
                        return_value=principal,
                    ),
                    patch.object(
                        connected.bridge,
                        "resolve_actor_context",
                        return_value=actor,
                    ),
                    patch.object(
                        connected.bridge,
                        "record_mcp_authorization_decision",
                        return_value=None,
                    ),
                    TestClient(
                        connected.application.app,
                        raise_server_exceptions=False,
                    ) as client,
                ):
                    response = client.post(
                        "/mcp",
                        headers={
                            "Authorization": "Bearer synthetic.token",
                            "Accept": "application/json, text/event-stream",
                            "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
                        },
                        json={
                            "jsonrpc": "2.0",
                            "id": "attachment-hybrid",
                            "method": "tools/call",
                            "params": {
                                "name": "query_effective_graph_view",
                                "arguments": {
                                    "query_text": (
                                        "把中國的供應商跟零件編號還有單價整理出來"
                                    )
                                },
                            },
                        },
                    ).json()["result"]
                self.assertFalse(response["isError"])
                data = response["structuredContent"]["data"]
                validate_public_gateway_payload(data)
                inventory = data["exact_inventory"]
                self.assertEqual(
                    inventory["query_class"],
                    "exact_set_or_inventory",
                )
                self.assertEqual(
                    inventory["plan"]["resource_kind"],
                    table_provider.resource_kind,
                )
                self.assertEqual(inventory["coverage_status"], "complete")
                self.assertEqual(
                    inventory["candidate_only_occurrence_count"],
                    0,
                )
                self.assertEqual(inventory["returned_count"], 1)
                self.assertEqual(len(inventory["items"]), 1)
                self.assertEqual(
                    {
                        item["field"]
                        for item in inventory["items"][0]["structured_values"]
                    },
                    {"供應商", "零件編號", "單價"},
                )
                child_hash = authorized_hashes[child_row.observation_id]
                china_citation_hashes = {
                    authorized_hashes[item.observation_id]
                    for item in child_observations
                    if item.location.get("row_index")
                    == child_row.location["row_index"]
                    and (
                        item.observation_type == "table_row"
                        or item.location.get("cell_index") in {1, 2, 3, 4}
                    )
                }
                japan_row_hashes = {
                    authorized_hashes[item.observation_id]
                    for item in child_observations
                    if item.location.get("row_index")
                    == japan_row.location["row_index"]
                }
                inventory_citations = {
                    reference["citation_hash"]
                    for item in inventory["items"]
                    for reference in item["governed_references"]
                }
                self.assertTrue(
                    china_citation_hashes.issubset(inventory_citations)
                )
                self.assertTrue(japan_row_hashes.isdisjoint(inventory_citations))
                self.assertTrue(
                    inventory_citations.issubset(set(data["citations"]))
                )
                self.assertNotIn("storage://", str(data))
                self.assertNotIn("object_uri", str(data))
                self.assertNotIn("tenant", str(data))
                coverage = validate_source_neutral_attachment_observation_coverage(
                    observations,
                    matched_child_observation_hashes=(child_hash,),
                )
                self.assertEqual(
                    coverage["authorized_attachment_occurrence_count"],
                    1,
                )
                self.assertEqual(
                    coverage["returned_attachment_occurrence_count"],
                    1,
                )
                self.assertEqual(
                    coverage["unresolved_attachment_occurrence_count"],
                    0,
                )
                self.assertEqual(
                    coverage["query_matched_attachment_occurrence_count"],
                    1,
                )
                self.assertTrue(coverage["authorized_scope_complete"])
            finally:
                await connected.aclose()

        tampered_cell = replace(
            child_cell,
            permission_scope={
                "scope_type": "mail_import_session",
                "visibility": "shared",
                "scope_id": SOURCE_SCOPE_ID,
                "permission_tamper": "authorization_only",
            },
        )
        tampered_session = replace(
            session,
            authorized_observations=tuple(
                tampered_cell if item == child_cell else item
                for item in observations
            ),
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "authorized semantic session binding mismatch",
        ):
            tampered_session.query(
                query_text=query_text,
                effective_graph_view=graph_view,
            )

    async def test_missing_projection_capabilities_return_filter_only_inventory_over_asgi(
        self,
    ) -> None:
        import formowl_mail.hybrid as hybrid_module

        from formowl_auth import FileAuditLogStore
        from formowl_gateway import issue56_sealed_source_loader as gateway_loader
        from formowl_ingestion.storage import UploadSessionStore
        from formowl_mail import build_mail_upload_session_handler

        parent = _observation(
            observation_id="observation_filter_only_attachment",
            observation_type="email_attachment_occurrence",
            text="Authorized filter-only attachment",
            payload={"child_asset_id": "asset_filter_only_child"},
        )
        children = _attachment_child_observations(
            child_asset_id="asset_filter_only_child",
            content=_formal_xlsx_bytes(),
            suffix=".xlsx",
        )
        data_rows = tuple(
            item
            for item in children
            if item.observation_type == "table_row"
            and item.payload["table_structure"]["row_role"] == "data"
        )
        observations = (parent, *children)
        retrieval_observations = (parent, *data_rows)
        authorized_source = validated_authorized_semantic_source(
            source_kind=AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
            workspace_id=WORKSPACE_ID,
            source_scope_ids=(SOURCE_SCOPE_ID,),
            authorized_permission_scopes=(PermissionScope.project(SOURCE_SCOPE_ID),),
        )
        lineages = (
            source_occurrence_lineage_from_observation(
                parent,
                authorized_source=authorized_source,
            ),
        )
        authorized_hashes = {
            item.observation_id: sha256_json(item.to_dict())
            for item in observations
        }
        retrieval_hashes = {
            item.observation_id: authorized_hashes[item.observation_id]
            for item in retrieval_observations
        }
        runtime_components = _contract_only_runtime()
        snippet_index, _ = build_authorized_observation_snippet_index(
            retrieval_observations,
            authorized_source=authorized_source,
            occurrence_lineages=lineages,
            authorized_observation_hash_by_id=retrieval_hashes,
            tokenizer_profile=runtime_components.tokenizer_profile,
        )
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=runtime_components,
        ):
            session = build_authorized_semantic_observation_session(
                authorized_source=authorized_source,
                snippet_index=snippet_index,
                authorized_observations=observations,
                retrieval_observations=retrieval_observations,
                occurrence_lineages=lineages,
                requester_user_id=REQUESTER_ID,
            )
        graph_view = build_authorized_source_backed_effective_graph_view(
            session=session,
            source_binding_fingerprint=sha256_json("filter_only_source_binding"),
        ).effective_graph_view
        provider = gateway_loader._build_attachment_table_row_provider(
            session,
            authorized_scope_fingerprint=authorized_source_occurrence_scope_fingerprint(
                requester_user_id=session.requester_user_id,
                workspace_id=session.workspace_id,
                source_scope_ids=session.authorized_source_scope_ids,
                authorized_observation_hashes=session.authorized_observation_hashes,
                source_session_binding_fingerprint=(
                    session.source_session_binding_fingerprint or ""
                ),
            ),
        )
        assert provider is not None
        self.assertTrue(provider.occurrences)
        self.assertTrue(
            all(
                occurrence.structure_status == "source_provided"
                for occurrence in provider.occurrences
            )
        )
        loaded = SimpleNamespace(
            session=session,
            effective_graph_view=graph_view,
            safe_binding={},
            observations=session.authorized_observations,
            query_bundle=SimpleNamespace(
                mail_import_session=SimpleNamespace(
                    mail_import_session_id=SOURCE_SCOPE_ID,
                ),
            ),
        )
        with (
            patch.object(gateway_loader, "APPROVER_ACTOR", REQUESTER_ID),
            patch.object(gateway_loader, "WORKSPACE_ID", WORKSPACE_ID),
            patch.object(
                gateway_loader,
                "_load_approved_sealed_source",
                return_value=loaded,
            ),
            patch.object(
                gateway_loader,
                "_validated_owner_safe_binding",
                return_value={},
            ),
            patch.object(
                gateway_loader,
                "_build_mail_source_occurrence_providers",
                return_value=(provider,),
            ),
        ):
            retrieval_handler = (
                gateway_loader.build_issue56_production_semantic_retrieval_handler()
            )

        with tempfile.TemporaryDirectory() as temporary_directory:
            config = ConnectedRuntimeConfig.from_env_and_secrets(
                _write_runtime_environment(Path(temporary_directory))
            )
            upload_handler = build_mail_upload_session_handler(
                upload_session_store=UploadSessionStore(config.data_dir),
                audit_store=FileAuditLogStore(config.data_dir),
                expires_at_provider=lambda: "2030-01-01T00:00:00+00:00",
            )
            with patch.object(
                runtime_module.PostgreSQLOAuthRepository,
                "connect",
                return_value=_FakeRepository(),
            ):
                connected = await ConnectedRuntime.compose(
                    config,
                    semantic_gateway=SemanticMcpGateway(
                        upload_session_handler=upload_handler,
                        retrieval_handler=retrieval_handler,
                    ),
                    http_client=_FakeHttpClient(),
                )
            connected.preflight = AsyncMock(return_value={"status": "ready"})
            principal = OAuthPrincipal(
                user_id=REQUESTER_ID,
                external_identity_id="external_filter_only",
                oauth_client_id="chatgpt_closed_beta",
                token_session_id="oauth_filter_only",
                scopes=("formowl.use",),
                resource=config.oauth.resource,
            )
            timestamp = "2026-09-01T00:00:00+00:00"
            actor = ActorContext(
                user=User(
                    user_id=REQUESTER_ID,
                    display_name="Filter-only attachment owner",
                    status="active",
                    created_at=timestamp,
                ),
                session_identity=SessionIdentity(
                    session_id=principal.token_session_id,
                    selected_user_id=REQUESTER_ID,
                    selected_at=timestamp,
                    selection_method="google_oidc_oauth",
                ),
                workspace_memberships=[
                    WorkspaceMember(
                        user_id=REQUESTER_ID,
                        workspace_id=WORKSPACE_ID,
                        role="owner",
                    )
                ],
                current_workspace_id=WORKSPACE_ID,
                current_workspace_role="owner",
                external_identity_id=principal.external_identity_id,
                oauth_client_id=principal.oauth_client_id,
                oauth_token_session_id=principal.token_session_id,
                auth_mode="google_oidc_oauth",
                production_authentication=True,
            )
            unsupported_query_text = (
                "把 UNBOUND-CONTEXT-9 ROW-FILTER-42 的 "
                "Category 跟 Code 整理 出來"
            )
            unsupported_arguments = {
                "query_text": unsupported_query_text,
                "exact_inventory_kind": provider.resource_kind,
            }
            ordered_terms, _ = hybrid_module._ordered_source_occurrence_query_grounding(
                unsupported_query_text,
                tokenizer_profile=runtime_components.tokenizer_profile,
            )
            particle_index = next(
                index for index, (_, role, _, control) in enumerate(ordered_terms)
                if role == "particle" and control == "none"
            )
            requested_projection_hashes = {
                term_hash for index, (term_hash, role, candidates, control)
                in enumerate(ordered_terms) if index > particle_index
                and role in {"lexical", "operator"} and candidates and control == "none"
            }
            self.assertTrue(requested_projection_hashes)
            missing_query_text = "Find SYNTH-MISSING-88421 SourceRegion ManufactureRegion"
            missing_tokens = frozenset(
                span.exact_token for span in runtime_components.tokenizer_profile.analyze(missing_query_text).protected_identifiers
            )
            self.assertEqual(missing_tokens, frozenset({"synth-missing-88421"}))
            self.assertTrue(all(
                missing_tokens.isdisjoint(candidate.protected_identifier_tokens |
                                          candidate.observation_protected_identifier_tokens)
                for candidate in session.index.candidates
            ))
            missing_trace, captured_missing, session_query = SemanticPhaseTrace(), [], type(session).query
            def traced_query(bound_session, **kwargs):
                kwargs["phase_trace"] = missing_trace
                result = session_query(bound_session, **kwargs)
                captured_missing.append(result)
                return result
            try:
                with (
                    patch.object(
                        connected.bridge,
                        "authenticate_access_token",
                        return_value=principal,
                    ),
                    patch.object(
                        connected.bridge,
                        "resolve_actor_context",
                        return_value=actor,
                    ),
                    patch.object(
                        connected.bridge,
                        "record_mcp_authorization_decision",
                        return_value=None,
                    ),
                    patch(
                        "formowl_mail.hybrid.route_semantic_query",
                        wraps=route_semantic_query,
                    ) as routed,
                    patch.object(
                        hybrid_module,
                        "_mark_partial_projection_exact_result",
                        wraps=hybrid_module._mark_partial_projection_exact_result,
                    ) as marked_partial,
                    TestClient(
                        connected.application.app,
                        raise_server_exceptions=False,
                    ) as client,
                ):
                    mcp_headers = {"Authorization": "Bearer synthetic.token",
                                   "Accept": "application/json, text/event-stream",
                                   "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION}
                    request = {
                        "jsonrpc": "2.0",
                        "id": "attachment-unsupported-structured",
                        "method": "tools/call",
                        "params": {"name": "query_effective_graph_view",
                                   "arguments": unsupported_arguments},
                    }
                    unsupported_response = client.post("/mcp", headers=mcp_headers, json=request)
                    request["id"] = "attachment-missing-identifier"
                    request["params"]["arguments"] = {"query_text": missing_query_text}
                    with patch.object(type(session), "query", new=traced_query):
                        missing_response = client.post("/mcp", headers=mcp_headers, json=request)
                self.assertEqual(unsupported_response.status_code, 200)
                unsupported_result = unsupported_response.json()["result"]
                self.assertFalse(unsupported_result["isError"])
                structured = unsupported_result["structuredContent"]
                self.assertEqual(structured["result_type"], "effective_graph_query")
                self.assertIn(structured["status"], {"ok", "partial"})
                unsupported_data = structured["data"]
                self.assertEqual(unsupported_data["status"], "incomplete")
                unsupported_inventory = unsupported_data["exact_inventory"]
                self.assertEqual(
                    unsupported_inventory["query_class"],
                    "exact_set_or_inventory",
                )
                self.assertEqual(unsupported_inventory["status"], "incomplete")
                self.assertEqual(
                    unsupported_inventory["coverage_status"],
                    "incomplete",
                )
                self.assertEqual(unsupported_inventory["total_count"], 0)
                self.assertEqual(unsupported_inventory["returned_count"], 0)
                self.assertEqual(unsupported_inventory["items"], [])
                self.assertEqual(
                    unsupported_inventory["candidate_only_occurrence_count"],
                    0,
                )
                self.assertGreater(unsupported_inventory["unsupported_count"], 0)
                self.assertEqual(unsupported_data["citations"], [])
                routed_arguments = next(
                    call.kwargs
                    for call in routed.call_args_list
                    if call.kwargs.get("query_text") == unsupported_query_text
                )
                self.assertEqual(routed_arguments["exact_projection_term_hashes"], ())
                self.assertNotIn(
                    "projection_field",
                    {item[1] for item in routed_arguments["exact_lexical_term_ledger"]},
                )
                partial_call = marked_partial.call_args
                self.assertEqual(
                    partial_call.args[0].query_hash,
                    sha256_json(unsupported_query_text),
                )
                self.assertTrue(
                    requested_projection_hashes
                    <= set(partial_call.kwargs["unsupported_projection_hashes"])
                )
                missing_result = missing_response.json()["result"]
                self.assertFalse(missing_result["isError"])
                self.assertEqual(
                    missing_result["structuredContent"]["result_type"],
                    "effective_graph_query",
                )
                missing_data = missing_result["structuredContent"]["data"]
                self.assertEqual(
                    (missing_response.status_code, missing_result["isError"],
                     missing_data["status"], missing_data["answer"]["status"],
                     len(missing_data["evidence"]), len(missing_data["citations"]),
                     missing_data["graph_hits"]["count"]),
                    (200, False, "incomplete", "unsupported", 0, 0, 0),
                )
                execution = captured_missing[0]
                self.assertEqual(
                    (execution.claim_strength, execution.semantic_result_count,
                     execution.graph_path_count, execution.exact_executor_status,
                     execution.exact_result, bool(execution.index_fingerprint),
                     execution.materialized_candidate_count),
                    ("no_claim", 0, 0, "not_started", None, True,
                     len(session.index.candidates)),
                )
                phase = missing_trace.to_safe_dict()
                strong_rag = next(
                    item for item in phase["phases"] if item["phase"] == "strong_rag"
                )
                self.assertEqual(
                    (phase["terminal_status"], strong_rag["attempt"],
                     strong_rag["outcome"], strong_rag["elapsed_ms"]),
                    ("completed", 0, "skipped", 0.0),
                )
            finally:
                await connected.aclose()

    def test_project_attachment_scope_binding_is_explicit_and_exact(self) -> None:
        observation = _observation(
            observation_id="observation_project_scope_binding",
            observation_type="email_attachment_occurrence",
            text="project-bound attachment",
        )
        observation_hashes = {
            observation.observation_id: sha256_json(observation.to_dict())
        }
        profile = _contract_only_runtime().tokenizer_profile

        def build(source):
            lineages = (
                source_occurrence_lineage_from_observation(
                    observation,
                    authorized_source=source,
                ),
            )
            return build_authorized_observation_snippet_index(
                (observation,),
                authorized_source=source,
                occurrence_lineages=lineages,
                authorized_observation_hash_by_id=observation_hashes,
                tokenizer_profile=profile,
            )

        unbound_source = validated_authorized_semantic_source(
            source_kind=AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
            workspace_id=WORKSPACE_ID,
            source_scope_ids=(SOURCE_SCOPE_ID,),
        )
        with self.assertRaisesRegex(ContractValidationError, "permission scope mismatch"):
            build(unbound_source)

        bound_source = validated_authorized_semantic_source(
            source_kind=AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
            workspace_id=WORKSPACE_ID,
            source_scope_ids=(SOURCE_SCOPE_ID,),
            authorized_permission_scopes=(PermissionScope.project(SOURCE_SCOPE_ID),),
        )
        for altered_scope in (
            {
                "scope_type": "project",
                "scope_id": SOURCE_SCOPE_ID,
                "visibility": "shared",
            },
            {
                "scope_type": "project",
                "scope_id": SOURCE_SCOPE_ID,
                "visibility": "restricted",
                "inherited_from": "different-parent",
            },
            {
                "scope_type": "project",
                "scope_id": "cross-project",
                "visibility": "restricted",
            },
        ):
            altered = replace(observation, permission_scope=altered_scope)
            altered_hashes = {
                altered.observation_id: sha256_json(altered.to_dict())
            }
            lineage = (
                source_occurrence_lineage_from_observation(
                    altered,
                    authorized_source=bound_source,
                ),
            )
            with self.assertRaisesRegex(
                ContractValidationError,
                "permission scope mismatch",
            ):
                build_authorized_observation_snippet_index(
                    (altered,),
                    authorized_source=bound_source,
                    occurrence_lineages=lineage,
                    authorized_observation_hash_by_id=altered_hashes,
                    tokenizer_profile=profile,
                )

    def test_legacy_project_scope_graph_keeps_scope_id_compatibility(self) -> None:
        from scripts.issue56_semantic_execution_smoke import (
            REQUESTER_USER_ID as LEGACY_REQUESTER_ID,
            WORKSPACE_ID as LEGACY_WORKSPACE_ID,
            build_semantic_poc_inputs,
        )

        inputs = build_semantic_poc_inputs()
        source_observations = inputs.observations_by_bundle_id[
            inputs.current_bundle.mail_evidence_bundle_id
        ]
        project_scope_id = source_observations[0].permission_scope["scope_id"]
        legacy_bundle = replace(
            inputs.current_bundle,
            mail_evidence_bundle_id=project_scope_id,
        )
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=_contract_only_runtime(),
        ):
            session = build_authorized_semantic_mail_session(
                observations_by_bundle_id={
                    project_scope_id: source_observations,
                },
                bundles=(legacy_bundle,),
                requester_user_id=LEGACY_REQUESTER_ID,
                workspace_id=LEGACY_WORKSPACE_ID,
            )
        graph_build = build_authorized_source_backed_effective_graph_view(
            session=session,
            source_binding_fingerprint=sha256_json(
                "legacy_project_scope_graph_compatibility"
            ),
        )
        self.assertEqual(
            graph_build.source_observation_count,
            len(session.retrieval_observation_hashes),
        )


if __name__ == "__main__":
    unittest.main()
