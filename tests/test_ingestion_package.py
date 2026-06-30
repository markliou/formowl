from __future__ import annotations

import unittest

import _paths  # noqa: F401


class IngestionPackageTests(unittest.TestCase):
    def test_ingestion_package_skeleton_imports(self) -> None:
        import formowl_ingestion
        from formowl_ingestion import (
            assets,
            chatgpt,
            extraction,
            extractors,
            folder_inbox,
            jobs,
            observations,
            storage,
            uploads,
        )

        self.assertEqual(
            formowl_ingestion.__all__,
            [
                "assets",
                "chatgpt",
                "extraction",
                "extractors",
                "folder_inbox",
                "jobs",
                "observations",
                "storage",
                "uploads",
            ],
        )
        self.assertEqual(
            chatgpt.__all__,
            [
                "ChatGptSessionCapture",
                "ChatGptSessionCaptureResult",
                "ChatGptSessionCaptureStore",
                "capture_current_chatgpt_session",
            ],
        )
        self.assertEqual(assets.__all__, ["register_asset_from_local_file"])
        self.assertEqual(
            extraction.__all__,
            [
                "ExtractionInput",
                "ExtractionResult",
                "ExtractorAdapter",
                "StoredExtractionResult",
                "extraction_config_hash",
                "run_extractor",
            ],
        )
        self.assertEqual(
            extractors.__all__,
            [
                "FileTechnicalMetadataExtractor",
                "FixtureAudioTranscriptExtractor",
                "FixtureDocumentParserExtractor",
                "FixtureMailArchiveExtractor",
                "FixtureOcrExtractor",
                "FixtureVideoSceneExtractor",
                "PlainTextObservationExtractor",
            ],
        )
        self.assertEqual(
            folder_inbox.__all__,
            [
                "FolderFileStabilitySnapshot",
                "FolderInboxItemResult",
                "FolderInboxScanResult",
                "scan_local_data_resource_folder",
            ],
        )
        self.assertEqual(jobs.__all__, ["create_ingestion_job", "run_ingestion_job"])
        self.assertEqual(observations.__all__, ["build_context_package_from_text_observations"])
        self.assertEqual(
            storage.__all__,
            [
                "AssetRecordStore",
                "AssetStore",
                "ExtractorRunRecordStore",
                "ExtractorRunStore",
                "FileObjectStore",
                "JobRecordStore",
                "JobStore",
                "ObservationRecordStore",
                "ObservationStore",
                "PostgreSQLAssetStore",
                "PostgreSQLExtractorRunStore",
                "PostgreSQLJobStore",
                "PostgreSQLObservationStore",
                "PostgreSQLUploadSessionStore",
                "StorageBackendConfig",
                "StoredObject",
                "StorageBackendRegistry",
                "UploadSessionRecordStore",
                "UploadSessionStore",
                "configure_storage_backend_registry",
                "configure_storage_backend_registry_from_env",
                "ingestion_record_store_interface_names",
                "load_storage_backend_configs_from_env",
                "postgre_sql_ingestion_store_interfaces",
            ],
        )
        self.assertEqual(uploads.__all__, ["create_upload_session", "upload_asset_reference"])


if __name__ == "__main__":
    unittest.main()
