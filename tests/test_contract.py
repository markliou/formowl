from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_contract import (
    ContextPackage,
    PermissionScope,
    SourceRef,
    sha256_json,
    validate_context_package,
)


class ContractTests(unittest.TestCase):
    def test_context_package_is_contract_shaped(self) -> None:
        source_ref = SourceRef(
            source_system="openproject",
            source_type="work_package",
            source_id="123",
            source_key="OP-123",
        )
        context_package = ContextPackage(
            context_package_id="ctx_001",
            context_type="work_item_context",
            context_markdown="# Context\n",
            source_refs=[source_ref],
            evidence_snapshot_ids=["ev_001"],
            citations=[],
            permission_scope=PermissionScope.project("formowl"),
        ).to_dict()

        validate_context_package(context_package)
        self.assertEqual(context_package["source_refs"][0]["source_system"], "openproject")
        self.assertEqual(context_package["permission_scope"]["visibility"], "restricted")

    def test_sha256_json_is_stable(self) -> None:
        left = {"b": 2, "a": 1}
        right = {"a": 1, "b": 2}
        self.assertEqual(sha256_json(left), sha256_json(right))


if __name__ == "__main__":
    unittest.main()
