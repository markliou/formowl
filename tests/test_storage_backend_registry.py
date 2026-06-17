from __future__ import annotations

import json
import unittest

import _paths  # noqa: F401
from formowl_contract import StorageBackend
from formowl_ingestion.storage import StorageBackendRegistry


class StorageBackendRegistryTests(unittest.TestCase):
    def test_registers_and_resolves_local_backend_without_public_raw_path(self) -> None:
        temp_dir = _paths.fresh_test_dir("storage-backend-registry")
        local_root = temp_dir / "raw-local-bytes"
        registry = StorageBackendRegistry(temp_dir)

        backend = registry.register_local_backend(
            local_root,
            workspace_scope="workspace_formowl",
            display_name="Local test object store",
            allowed_workers=["worker_local"],
        )

        self.assertEqual(backend.type, "local_fs")
        self.assertTrue(backend.storage_backend_id.startswith("storage_"))
        self.assertEqual(backend.root_prefix, f"formowl://storage/{backend.storage_backend_id}")
        self.assertIsNone(backend.internal_endpoint)
        self.assertEqual(
            registry.resolve_local_root(backend.storage_backend_id), local_root.resolve()
        )

        reloaded = StorageBackendRegistry(temp_dir)
        self.assertEqual(reloaded.get_backend(backend.storage_backend_id), backend)
        self.assertEqual(reloaded.list_backends(), [backend])

        raw_record = json.loads(
            (
                temp_dir / "ingestion" / "storage-backends" / f"{backend.storage_backend_id}.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            raw_record["private"]["local_root_path"],
            str(local_root.resolve()),
        )

        public_backend = reloaded.public_backend_dict(backend.storage_backend_id)
        envelope = reloaded.backend_mcp_envelope(backend.storage_backend_id)
        public_json = json.dumps(
            {"backend": public_backend, "envelope": envelope},
            ensure_ascii=False,
            sort_keys=True,
        )
        self.assertNotIn(str(local_root.resolve()), public_json)
        self.assertNotIn("raw-local-bytes", public_json)
        self.assertNotIn("internal_endpoint", public_json)
        self.assertIn("formowl://storage/", public_json)

    def test_missing_backend_returns_not_found_envelope(self) -> None:
        temp_dir = _paths.fresh_test_dir("storage-backend-registry-missing")
        registry = StorageBackendRegistry(temp_dir)

        self.assertIsNone(registry.get_backend("storage_missing"))
        self.assertIsNone(registry.resolve_local_root("storage_missing"))
        self.assertEqual(
            registry.backend_mcp_envelope("storage_missing"),
            {
                "result_type": "storage_backend",
                "status": "not_found",
                "data": {"storage_backend_id": "storage_missing"},
                "warnings": [],
            },
        )

    def test_register_backend_keeps_internal_endpoint_private(self) -> None:
        temp_dir = _paths.fresh_test_dir("storage-backend-registry-private-endpoint")
        registry = StorageBackendRegistry(temp_dir)
        backend = StorageBackend(
            storage_backend_id="storage_private_endpoint",
            type="local_fs",
            display_name="Local private endpoint",
            access_mode="read_only",
            trust_level="trusted_internal",
            workspace_scope="workspace_formowl",
            health_status="healthy",
            internal_endpoint=str(temp_dir / "private-root"),
            root_prefix="formowl://storage/storage_private_endpoint",
        )

        registered = registry.register_backend(backend)

        self.assertIsNone(registered.internal_endpoint)
        self.assertNotIn(
            "internal_endpoint",
            registry.backend_mcp_envelope("storage_private_endpoint")["data"]["backend"],
        )

        raw_record = json.loads(
            (
                temp_dir / "ingestion" / "storage-backends" / "storage_private_endpoint.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(raw_record["private"]["internal_endpoint"], backend.internal_endpoint)


if __name__ == "__main__":
    unittest.main()
