from __future__ import annotations

import unittest

import _paths  # noqa: F401


class IngestionPackageTests(unittest.TestCase):
    def test_ingestion_package_skeleton_imports(self) -> None:
        import formowl_ingestion
        from formowl_ingestion import assets, extraction, extractors, jobs, observations, storage

        self.assertEqual(
            formowl_ingestion.__all__,
            ["assets", "extraction", "extractors", "jobs", "observations", "storage"],
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
        self.assertEqual(extractors.__all__, ["PlainTextObservationExtractor"])
        self.assertEqual(jobs.__all__, ["create_ingestion_job", "run_ingestion_job"])
        self.assertEqual(observations.__all__, ["build_context_package_from_text_observations"])
        self.assertEqual(
            storage.__all__,
            [
                "AssetStore",
                "ExtractorRunStore",
                "FileObjectStore",
                "JobStore",
                "ObservationStore",
                "StoredObject",
                "StorageBackendRegistry",
            ],
        )


if __name__ == "__main__":
    unittest.main()
