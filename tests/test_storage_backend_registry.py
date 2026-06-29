from __future__ import annotations

import json
import unittest

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, StorageBackend
from formowl_ingestion.storage import (
    StorageBackendConfig,
    StorageBackendRegistry,
    configure_storage_backend_registry,
    configure_storage_backend_registry_from_env,
)


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

    def test_register_backend_rejects_raw_path_root_prefix_before_public_record(self) -> None:
        temp_dir = _paths.fresh_test_dir("storage-backend-registry-raw-root-prefix")
        registry = StorageBackendRegistry(temp_dir)
        backend = StorageBackend(
            storage_backend_id="storage_raw_root_prefix",
            type="local_fs",
            display_name="Local raw root prefix",
            access_mode="read_only",
            trust_level="trusted_internal",
            workspace_scope="workspace_formowl",
            health_status="healthy",
            root_prefix=str((temp_dir / "private-root").resolve()),
        )

        with self.assertRaises(ContractValidationError):
            registry.register_backend(backend)

        self.assertIsNone(registry.get_backend("storage_raw_root_prefix"))
        self.assertFalse(
            (temp_dir / "ingestion" / "storage-backends" / "storage_raw_root_prefix.json").exists()
        )

    def test_configures_local_backend_from_environment_without_public_raw_path(self) -> None:
        temp_dir = _paths.fresh_test_dir("storage-backend-registry-env-local")
        local_root = temp_dir / "configured-local-root"
        registry = StorageBackendRegistry(temp_dir)

        configured = configure_storage_backend_registry_from_env(
            registry,
            {
                "FORMOWL_STORAGE_BACKEND_ID": "storage_configured_local",
                "FORMOWL_STORAGE_BACKEND_ROOT": str(local_root),
                "FORMOWL_STORAGE_BACKEND_DISPLAY_NAME": "Configured local object store",
                "FORMOWL_STORAGE_ALLOWED_WORKERS": "worker_a, worker_b",
                "FORMOWL_WORKSPACE_ID": "workspace_formowl",
            },
        )

        self.assertEqual(len(configured), 1)
        backend = configured[0]
        self.assertEqual(backend.storage_backend_id, "storage_configured_local")
        self.assertEqual(backend.type, "local_fs")
        self.assertEqual(backend.workspace_scope, "workspace_formowl")
        self.assertEqual(backend.allowed_workers, ["worker_a", "worker_b"])
        self.assertEqual(registry.resolve_local_root(backend.storage_backend_id), local_root)

        public_json = json.dumps(
            registry.backend_mcp_envelope("storage_configured_local"),
            ensure_ascii=False,
            sort_keys=True,
        )
        self.assertNotIn(str(local_root), public_json)
        self.assertNotIn("configured-local-root", public_json)
        self.assertIn("formowl://storage/storage_configured_local", public_json)

    def test_configures_nonlocal_descriptor_without_changing_contract_id(self) -> None:
        temp_dir = _paths.fresh_test_dir("storage-backend-registry-env-object")
        registry = StorageBackendRegistry(temp_dir)
        config = StorageBackendConfig(
            storage_backend_id="storage_minio_primary",
            type="minio",
            display_name="Primary object backend",
            access_mode="read_write",
            trust_level="trusted_internal",
            workspace_scope="workspace_formowl",
            health_status="not_configured",
            internal_endpoint="http://minio.internal:9000",
            private_config={"bucket": "formowl-raw", "region": "local"},
        )

        first = configure_storage_backend_registry(registry, [config])[0]
        second = configure_storage_backend_registry(
            registry,
            [
                StorageBackendConfig(
                    storage_backend_id="storage_minio_primary",
                    type="minio",
                    display_name="Primary object backend",
                    access_mode="read_write",
                    trust_level="trusted_internal",
                    workspace_scope="workspace_formowl",
                    health_status="degraded",
                    internal_endpoint="http://minio-replacement.internal:9000",
                    private_config={"bucket": "formowl-raw", "region": "local"},
                )
            ],
        )[0]

        self.assertEqual(first.storage_backend_id, "storage_minio_primary")
        self.assertEqual(second.storage_backend_id, "storage_minio_primary")
        self.assertEqual(second.root_prefix, "formowl://storage/storage_minio_primary")
        self.assertIsNone(registry.resolve_local_root("storage_minio_primary"))

        raw_record = json.loads(
            (temp_dir / "ingestion" / "storage-backends" / "storage_minio_primary.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            raw_record["private"]["internal_endpoint"],
            "http://minio-replacement.internal:9000",
        )
        self.assertEqual(raw_record["private"]["bucket"], "formowl-raw")
        public_json = json.dumps(
            registry.backend_mcp_envelope("storage_minio_primary"),
            ensure_ascii=False,
            sort_keys=True,
        )
        self.assertNotIn("minio-replacement", public_json)
        self.assertNotIn("formowl-raw", public_json)
        self.assertNotIn("internal_endpoint", public_json)

    def test_storage_backend_config_rejects_public_raw_locators_and_secrets(self) -> None:
        temp_dir = _paths.fresh_test_dir("storage-backend-registry-config-rejects")
        bad_public_registry = StorageBackendRegistry(temp_dir / "bad-public")
        with self.assertRaises(ValueError):
            configure_storage_backend_registry(
                bad_public_registry,
                [
                    {
                        "type": "local_fs",
                        "workspace_scope": "workspace_formowl",
                        "display_name": str(temp_dir / "private-root"),
                        "root_path": str(temp_dir / "private-root"),
                    }
                ],
            )

        bad_secret_registry = StorageBackendRegistry(temp_dir / "bad-secret")
        with self.assertRaises(ValueError):
            configure_storage_backend_registry(
                bad_secret_registry,
                [
                    {
                        "type": "local_fs",
                        "workspace_scope": "workspace_formowl",
                        "root_path": str(temp_dir / "private-root"),
                        "private_config": {"secret_access_key": "do-not-store"},
                    }
                ],
            )

        no_id_registry = StorageBackendRegistry(temp_dir / "no-id")
        with self.assertRaises(ValueError):
            configure_storage_backend_registry(
                no_id_registry,
                [
                    StorageBackendConfig(
                        type="minio",
                        workspace_scope="workspace_formowl",
                        internal_endpoint="http://minio.internal:9000",
                    )
                ],
            )

        self.assertEqual(bad_public_registry.list_backends(), [])
        self.assertEqual(bad_secret_registry.list_backends(), [])
        self.assertEqual(no_id_registry.list_backends(), [])


if __name__ == "__main__":
    unittest.main()
