"""Phase 1 of SPEC §7.5 reviewed header validation (loader read path only)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import MappingProxyType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from formowl_contract import ContractValidationError, Observation, sha256_json  # noqa: E402
from formowl_gateway.issue56_sealed_source_loader import (  # noqa: E402
    _effective_cell_structure_status,
    _exact_column_applicable,
)
from formowl_mail.issue56_sealed_source import (  # noqa: E402
    APPROVER_ACTOR,
    Issue56IngestionRevision,
    REVIEWED_HEADER_RECEIPT_ARTIFACT_ID,
    Issue56SealedSourceLoadError,
    REVIEWED_HEADER_CONFIG_ARTIFACT_ID,
    bind_issue56_reviewed_headers,
    reviewed_header_binding_key,
)

SOURCE_AUTHORITY = "sha256:" + "a" * 64
CANDIDATE_COLUMN = "sha256:" + "c" * 64
PROVIDED_COLUMN = "sha256:" + "d" * 64


def _cell(*, status="candidate_only", asset_id="asset_1", column_name="COO", cell_index=3):
    return Observation(
        observation_id="obs_cell", extractor_run_id="run_1", observation_type="table_cell",
        modality="document", confidence=1.0, permission_scope={"workspace_id": "w"},
        created_at="2026-10-23T00:00:00Z", asset_id=asset_id, text="JAPAN",
        location={"sheet_name": "Sheet1", "table_index": 0, "row_index": 5, "cell_index": cell_index},
        payload={"table_structure": {"structure_status": status, "column_name": column_name,
                                     "header_row_index": 2, "row_role": "data_candidate"}},
    )


def _revision(**overrides):
    values = dict(
        observations=(), bundles=(), session=None, snippet_index=None, graph_build=None,
        safe_binding=MappingProxyType({}),
        exact_lookup_manifest={
            "source_authority_fingerprint": SOURCE_AUTHORITY,
            "columns": [
                {"field": "COO", "column_hash": CANDIDATE_COLUMN, "inline_table": False,
                 "structure_status": "candidate_only", "candidate_hashes": [CANDIDATE_COLUMN]},
                {"field": "TIME", "column_hash": PROVIDED_COLUMN, "inline_table": False,
                 "structure_status": "source_provided", "candidate_hashes": [PROVIDED_COLUMN]},
            ],
        },
    )
    values.update(overrides)
    return Issue56IngestionRevision(**values)


def _config(**overrides):
    config = {
        "artifact_id": REVIEWED_HEADER_CONFIG_ARTIFACT_ID, "schema_version": 1,
        "source_authority_fingerprint": SOURCE_AUTHORITY, "policy_version": "structural_v1",
        "approver_user_id": APPROVER_ACTOR, "decision": "approve_reviewed_header",
        "approvals": [{"binding": reviewed_header_binding_key(_cell()), "column_hash": CANDIDATE_COLUMN}],
    }
    config.update(overrides)
    return config


class ReviewedHeaderValidationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _seal(self, name, value):
        path = Path(self._tmp.name) / name
        data = json.dumps(value, sort_keys=True).encode()
        path.write_bytes(data)
        os.chmod(path, 0o600)
        return path, "sha256:" + hashlib.sha256(data).hexdigest()

    def _write(self, config, **receipt_overrides):
        receipt = {
            "artifact_id": REVIEWED_HEADER_RECEIPT_ARTIFACT_ID, "approver_user_id": APPROVER_ACTOR,
            "decision": "approve_reviewed_header", "policy_version": config.get("policy_version"),
            "source_authority_fingerprint": config.get("source_authority_fingerprint"),
            "approvals_sha256": sha256_json(config.get("approvals")),
            "approval_count": len(config.get("approvals") or ()),
        }
        receipt.update(receipt_overrides)
        _, receipt_digest = self._seal("receipt.json", receipt)
        if "review_receipt_path" not in config:
            config = {**config, "review_receipt_path": "receipt.json", "review_receipt_sha256": receipt_digest}
        return self._seal("reviewed-headers.json", config)

    def test_binding_key_is_stable_and_source_bound(self):
        key = reviewed_header_binding_key(_cell())
        self.assertTrue(key.startswith("sha256:"))
        self.assertEqual(key, reviewed_header_binding_key(_cell()))
        self.assertNotEqual(key, reviewed_header_binding_key(_cell(asset_id="asset_2")))
        self.assertNotEqual(key, reviewed_header_binding_key(_cell(column_name="ORIGIN")))
        self.assertNotEqual(key, reviewed_header_binding_key(_cell(cell_index=4)))
        self.assertIsNone(reviewed_header_binding_key(_cell(status="source_provided")))

    def test_default_revision_keeps_existing_behavior(self):
        revision = _revision()
        candidate, provided = revision.exact_lookup_manifest["columns"]
        self.assertFalse(_exact_column_applicable(revision, candidate))
        self.assertTrue(_exact_column_applicable(revision, provided))
        row = {"structure_status": "candidate_only", "row_role": "data_candidate"}
        self.assertEqual(_effective_cell_structure_status(revision, _cell(), row), "candidate_only")

    def test_sealed_approval_upgrades_only_the_approved_table_header(self):
        path, digest = self._write(_config())
        revision = bind_issue56_reviewed_headers(_revision(), configuration_path=path, expected_sha256=digest)
        self.assertEqual(revision.safe_binding["reviewed_header_approval_count"], 1)
        candidate, _ = revision.exact_lookup_manifest["columns"]
        self.assertTrue(_exact_column_applicable(revision, candidate))
        row = {"structure_status": "candidate_only", "row_role": "data_candidate"}
        self.assertEqual(_effective_cell_structure_status(revision, _cell(), row), "reviewed_header")
        # Same label in another table/asset stays a candidate.
        self.assertEqual(
            _effective_cell_structure_status(revision, _cell(asset_id="asset_2"), row), "candidate_only")
        # The header row itself is never upgraded into data.
        header_row = {"structure_status": "candidate_only", "row_role": "header_candidate"}
        self.assertEqual(_effective_cell_structure_status(revision, _cell(), header_row), "candidate_only")

    def test_invalid_configurations_reject(self):
        bad = [
            _config(approver_user_id="someone_else"),
            _config(decision="approve"),
            _config(source_authority_fingerprint="sha256:" + "b" * 64),
            _config(approvals=[]),
            _config(approvals=[{"binding": reviewed_header_binding_key(_cell()), "column_hash": PROVIDED_COLUMN}]),
            _config(approvals=[{"binding": "not-a-hash", "column_hash": CANDIDATE_COLUMN}]),
            {**_config(), "extra": True},
        ]
        for config in bad:
            path, digest = self._write(config)
            with self.subTest(config=sorted(config)), self.assertRaises(ContractValidationError):
                bind_issue56_reviewed_headers(_revision(), configuration_path=path, expected_sha256=digest)
        for overrides in ({"policy_version": "other"}, {"approval_count": 2},
                          {"approvals_sha256": "sha256:" + "0" * 64}, {"approver_user_id": "x"}):
            path, digest = self._write(_config(), **overrides)
            with self.subTest(receipt=sorted(overrides)), self.assertRaises(ContractValidationError):
                bind_issue56_reviewed_headers(_revision(), configuration_path=path, expected_sha256=digest)
        path, digest = self._write({**_config(), "review_receipt_path": "receipt.json",
                                    "review_receipt_sha256": "sha256:" + "0" * 64})
        with self.assertRaises((ContractValidationError, Issue56SealedSourceLoadError)):
            bind_issue56_reviewed_headers(_revision(), configuration_path=path, expected_sha256=digest)
        path, _ = self._write(_config())
        with self.assertRaises((ContractValidationError, Issue56SealedSourceLoadError)):
            bind_issue56_reviewed_headers(_revision(), configuration_path=path,
                                          expected_sha256="sha256:" + "0" * 64)


if __name__ == "__main__":
    unittest.main()
