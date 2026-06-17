from __future__ import annotations

import unittest

import _paths  # noqa: F401


class IngestionPackageTests(unittest.TestCase):
    def test_ingestion_package_skeleton_imports(self) -> None:
        import formowl_ingestion
        from formowl_ingestion import assets, jobs, observations, storage

        self.assertEqual(
            formowl_ingestion.__all__,
            ["assets", "jobs", "observations", "storage"],
        )
        self.assertEqual(assets.__all__, [])
        self.assertEqual(jobs.__all__, [])
        self.assertEqual(observations.__all__, [])
        self.assertEqual(storage.__all__, [])


if __name__ == "__main__":
    unittest.main()
