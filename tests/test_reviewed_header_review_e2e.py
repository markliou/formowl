"""Phase 3 tool output is accepted by the phase 1 binder (SPEC §7.5)."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import MappingProxyType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
REVIEW_SCRIPT = os.environ.get("REVIEWED_HEADER_REVIEW_SCRIPT")

from formowl_contract import Observation  # noqa: E402
from formowl_mail.issue56_sealed_source import (  # noqa: E402
    Issue56IngestionRevision,
    bind_issue56_reviewed_headers,
    reviewed_header_binding_key,
)

SOURCE_AUTHORITY = "sha256:" + "a" * 64
COLUMN = "sha256:" + "c" * 64


@unittest.skipUnless(REVIEW_SCRIPT, "set REVIEWED_HEADER_REVIEW_SCRIPT to the phase 3 tool")
class ReviewToolBinderTests(unittest.TestCase):
    def test_written_configuration_binds(self):
        spec = importlib.util.spec_from_file_location("review_tool", REVIEW_SCRIPT)
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        cell = Observation(
            observation_id="obs_cell", extractor_run_id="run_1", observation_type="table_cell",
            modality="document", confidence=1.0, permission_scope={"workspace_id": "w"},
            created_at="2026-10-23T00:00:00Z", asset_id="asset_1", text="JAPAN",
            location={"sheet_name": "Sheet1", "table_index": 0, "row_index": 5, "cell_index": 3},
            payload={"table_structure": {"structure_status": "candidate_only", "column_name": "COO",
                                         "header_row_index": 2, "row_role": "data_candidate"}},
        )
        manifest = {"source_authority_fingerprint": SOURCE_AUTHORITY, "columns": [
            {"field": "COO", "column_hash": COLUMN, "inline_table": False,
             "structure_status": "candidate_only", "candidate_hashes": [COLUMN]}]}
        proposal = {"proposer_version": "structural_v1", "binding": reviewed_header_binding_key(cell),
                    "column_hash": COLUMN, "inline_table": False, "decision": "header_confirmed",
                    "reasons": ["structural_checks_passed"]}
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "proposals.jsonl").write_text(json.dumps(proposal) + "\n")
            (base / "manifest.json").write_text(json.dumps(manifest))
            out = base / "review"
            self.assertEqual(tool.main([
                "--structural-proposals", str(base / "proposals.jsonl"),
                "--exact-manifest", str(base / "manifest.json"),
                "--policy", "structural_accept_v1", "--output-dir", str(out), "--approve",
            ]), 0)
            config_path = out / "reviewed-headers.json"
            import hashlib
            digest = "sha256:" + hashlib.sha256(config_path.read_bytes()).hexdigest()
            revision = Issue56IngestionRevision(
                observations=(), bundles=(), session=None, snippet_index=None, graph_build=None,
                safe_binding=MappingProxyType({}), exact_lookup_manifest=manifest)
            bound = bind_issue56_reviewed_headers(revision, configuration_path=config_path,
                                                  expected_sha256=digest)
            self.assertEqual(bound.reviewed_header_bindings, frozenset({proposal["binding"]}))
            self.assertEqual(bound.reviewed_header_column_hashes, frozenset({COLUMN}))
            self.assertEqual(oct(config_path.stat().st_mode & 0o777), "0o600")


if __name__ == "__main__":
    unittest.main()
