from __future__ import annotations

import json
import unittest

import _paths  # noqa: F401
from formowl_contract import PermissionScope, SourceRef
from formowl_ingestion.assets import register_asset_from_local_file
from formowl_ingestion.extractors import PlainTextObservationExtractor
from formowl_ingestion.jobs import create_ingestion_job, run_ingestion_job
from formowl_ingestion.observations import build_context_package_from_text_observations
from formowl_ingestion.storage import (
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    JobStore,
    ObservationStore,
    StorageBackendRegistry,
)
from formowl_wiki_mcp import create_default_server


class IngestionToWikiWorkflowTests(unittest.TestCase):
    def test_text_asset_observations_build_context_package_and_wiki_draft(self) -> None:
        temp_dir = _paths.fresh_test_dir("ingestion-to-wiki")
        source_path = temp_dir / "incoming" / "decision-notes.md"
        source_path.parent.mkdir(parents=True)
        source_path.write_text(
            "# Decision Notes\n\nUse observations before graph governance.\n",
            encoding="utf-8",
        )
        registry = StorageBackendRegistry(temp_dir)
        backend = registry.register_local_backend(
            temp_dir / "object-root",
            workspace_scope="workspace_formowl",
        )
        object_store = FileObjectStore(registry)
        asset_store = AssetStore(temp_dir)
        job_store = JobStore(temp_dir)
        run_store = ExtractorRunStore(temp_dir)
        observation_store = ObservationStore(temp_dir)
        permission_scope = PermissionScope.project("project_formowl")
        source_ref = SourceRef(
            source_system="local",
            source_type="file",
            source_id="decision-notes.md",
            source_key="decision-notes.md",
        )
        asset = register_asset_from_local_file(
            source_path,
            object_store=object_store,
            asset_store=asset_store,
            storage_backend_id=backend.storage_backend_id,
            workspace_id="workspace_formowl",
            owner_user_id="user_yifan",
            permission_scope=permission_scope,
            source_ref=source_ref,
            created_at="2026-06-17T10:00:00+00:00",
            registered_at="2026-06-17T10:00:00+00:00",
        )
        job = create_ingestion_job(
            asset=asset,
            job_store=job_store,
            requested_by="user_yifan",
            extractor_adapters=[PlainTextObservationExtractor()],
            created_at="2026-06-17T10:00:00+00:00",
        )
        completed = run_ingestion_job(
            ingestion_job_id=job.ingestion_job_id,
            asset_store=asset_store,
            job_store=job_store,
            object_store=object_store,
            extractor_run_store=run_store,
            observation_store=observation_store,
            extractor_adapters=[PlainTextObservationExtractor()],
            started_at="2026-06-17T10:01:00+00:00",
            completed_at="2026-06-17T10:01:00+00:00",
        )
        observations = [
            observation_store.get(observation_id) for observation_id in completed.observation_ids
        ]
        runs = [run_store.get(run_id) for run_id in completed.extractor_run_ids]

        context_package = build_context_package_from_text_observations(
            observations,
            assets=[asset],
            extractor_runs=runs,
            title="Decision Notes Source",
        )
        repeated_context_package = build_context_package_from_text_observations(
            observations,
            assets=[asset],
            extractor_runs=runs,
            title="Decision Notes Source",
        )
        context_data = context_package.to_dict()

        self.assertEqual(
            context_package.context_package_id, repeated_context_package.context_package_id
        )
        self.assertEqual(context_data["permission_scope"], permission_scope.to_dict())
        self.assertEqual(context_data["source_refs"], [source_ref.to_dict()])
        self.assertEqual(len(context_data["citations"]), 2)
        self.assertEqual(
            context_data["citations"][0]["locator"]["asset_id"],
            asset.asset_id,
        )
        self.assertEqual(
            context_data["citations"][0]["locator"]["extractor_run_id"],
            completed.extractor_run_ids[0],
        )
        self.assertIn(completed.observation_ids[0], context_data["context_markdown"])
        self.assertIn(asset.asset_id, context_data["context_markdown"])
        self.assertIn("decision-notes.md", context_data["context_markdown"])
        self.assertIn("Use observations before graph governance.", context_data["context_markdown"])

        wiki_server = create_default_server(temp_dir)
        draft = wiki_server.call_tool(
            "generate_wiki_draft",
            {
                "page_type": "meeting-notes",
                "title": "Decision Notes Draft",
                "context_package": context_data,
            },
        )
        markdown = draft["data"]["markdown"]
        serialized = json.dumps(
            {
                "context": context_data,
                "draft": draft,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

        self.assertEqual(draft["status"], "ok")
        self.assertIn("Decision Notes Source", markdown)
        self.assertIn("Use observations before graph governance.", markdown)
        self.assertIn("cit_obs_001", markdown)
        self.assertIn(completed.observation_ids[0], markdown)
        self.assertIn(completed.extractor_run_ids[0], markdown)
        self.assertIn(asset.asset_id, markdown)
        self.assertIn("## Evidence Snapshots", markdown)
        self.assertIn("_No evidence snapshots supplied._", markdown)
        self.assertNotIn(str(source_path), serialized)
        self.assertNotIn(str((temp_dir / "object-root").resolve()), serialized)
        self.assertNotIn("CandidateAtom", serialized)
        self.assertNotIn("CanonicalAtom", serialized)
        self.assertNotIn("WikiRevision", context_data)


if __name__ == "__main__":
    unittest.main()
