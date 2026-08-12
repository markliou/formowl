from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import _paths  # noqa: F401


_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "docs/recovery/2026-08-10/run-offline-semantic-acceptance-r8.py"
)
_SPEC = importlib.util.spec_from_file_location("offline_semantic_acceptance_r8", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def _bundle(
    *,
    legacy_source_id: str = "inventory_legacy_source",
    include_empty_cell: bool = True,
) -> dict[str, object]:
    columns = [
        {"column_ordinal": 0, "normalized_header": "COO"},
        {"column_ordinal": 1, "original_header": "P/N"},
    ]
    cells = [
        {"cell_state": "populated", "column_ordinal": 0, "value": "Japan"},
        {"cell_state": "populated", "column_ordinal": 1, "value": "A-1"},
    ]
    if include_empty_cell:
        columns.append({"column_ordinal": 2})
        cells.append({"cell_state": "blank", "column_ordinal": 2, "value": None})
    return {
        "legacy_authority_id": "ignored-top-level-legacy-control",
        "source_inventory_items": [
            {
                "source_inventory_item_id": legacy_source_id,
                "structure_kind": "mail_table",
                "content_type": "text/html",
                "ordinal": 9,
                "location": {"private": "not-used"},
            },
            {
                "source_inventory_item_id": "unreferenced_legacy_source",
                "structure_kind": "mail_attachment",
                "content_type": "text/plain",
                "ordinal": 10,
            },
        ],
        "structural_observations": [
            {
                "structural_observation_id": "legacy_structural_observation",
                "source_inventory_item_id": legacy_source_id,
                "source_observation_id": "legacy_source_observation",
                "structure_kind": "mail_table",
                "columns": columns,
                "rows": [
                    {
                        "row_ordinal": 0,
                        "cells": cells,
                    }
                ],
            }
        ],
        "unselected_huge_legacy_payload": ["x"] * 2,
    }


def _write_bundle(root: Path, ordinal: int, payload: dict[str, object]) -> Path:
    directory = root / f"{ordinal:08d}" / "mail-evidence" / "canonical-bundles.private"
    directory.mkdir(parents=True)
    path = directory / f"bundle-{ordinal}.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    return path


class OfflineSemanticAcceptanceR8Tests(unittest.TestCase):
    def test_normalizes_only_joined_inventory_and_structural_topology(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = _write_bundle(Path(temporary), 0, _bundle())
            shard = _MODULE._normalized_shard(path, 0)
            bundle_hash = _MODULE.sha256_file(path)

        bundle = shard["normalized_bundle"]
        self.assertEqual(bundle["schema"], "formowl_normalized_evidence_shard_v1")
        self.assertEqual(len(bundle["source_items"]), 1)
        self.assertEqual(bundle["source_items"][0]["ordinal"], 0)
        self.assertEqual(bundle["source_items"][0]["structure_kind"], "mail_table")
        observation = bundle["structural_observations"][0]
        self.assertEqual(observation["columns"], ["COO", "P/N", "column_2"])
        self.assertEqual(observation["rows"], [["Japan", "A-1", ""]])
        rendered = json.dumps(shard, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("inventory_legacy_source", rendered)
        self.assertNotIn("legacy_structural_observation", rendered)
        self.assertNotIn("private", rendered)
        self.assertEqual(
            shard["immutable_source_hashes"],
            {bundle_hash: bundle_hash},
        )

    def test_rejects_legacy_control_id_in_selected_record(self) -> None:
        payload = _bundle()
        source = payload["source_inventory_items"][0]
        source["legacy_authority_id"] = "forbidden"
        with tempfile.TemporaryDirectory() as temporary:
            path = _write_bundle(Path(temporary), 0, payload)
            with self.assertRaisesRegex(Exception, "forbidden legacy"):
                _MODULE._normalized_shard(path, 0)

    def test_rejects_non_rectangular_structural_rows(self) -> None:
        payload = _bundle()
        observation = payload["structural_observations"][0]
        observation["rows"][0]["cells"].pop()
        with tempfile.TemporaryDirectory() as temporary:
            path = _write_bundle(Path(temporary), 0, payload)
            with self.assertRaisesRegex(Exception, "not rectangular"):
                _MODULE._normalized_shard(path, 0)

    def test_accepts_absent_cells_as_rectangular_empty_values(self) -> None:
        payload = _bundle()
        payload["structural_observations"][0]["rows"][0]["cells"][-1]["cell_state"] = "absent"
        with tempfile.TemporaryDirectory() as temporary:
            path = _write_bundle(Path(temporary), 0, payload)
            shard = _MODULE._normalized_shard(path, 0)
        self.assertEqual(
            shard["normalized_bundle"]["structural_observations"][0]["rows"],
            [["Japan", "A-1", ""]],
        )

    def test_requires_complete_contiguous_shard_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_bundle(root, 1, _bundle())
            with self.assertRaisesRegex(Exception, "shard layout"):
                _MODULE._legacy_bundle_paths(root)

    def test_adapter_uses_no_forbidden_raw_bridge_or_parser_imports(self) -> None:
        source = _SCRIPT.read_text(encoding="utf-8")
        for forbidden in (
            "diagnostic_structural_bridge",
            "formowl_ingestion.extractors.mail.pst",
            "pypff",
            "libpff",
        ):
            self.assertNotIn(forbidden, source)

    def test_strict_loader_candidate_executor_preserves_exact_value_selection(self) -> None:
        aliases = _MODULE.SemanticSchemaAliasMap(
            object_aliases={"mail_table": ("mail_table",)},
            predicate_aliases={
                "coo": ("coo",),
                "p/n": ("p/n",),
            },
            value_aliases={},
            value_domains={
                "coo": "open_public_value",
                "p/n": "open_public_value",
            },
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy = _write_bundle(
                root / "legacy",
                0,
                _bundle(include_empty_cell=False),
            )
            shard = _MODULE._normalized_shard(legacy, 0)
            output = root / "fresh"
            authority_root = b"synthetic-authority-root-32-bytes!"
            _MODULE.publish_fresh_uat_attestation(
                output_dir=output,
                normalized_shards=(shard,),
                immutable_source_hashes=shard["immutable_source_hashes"],
                source_asset_id="asset_fresh_uat",
                source_fingerprint=_MODULE.sha256_json({"source": "synthetic"}),
                workspace_id="workspace_fresh_uat",
                owner_user_id="owner_fresh_uat",
                permission_scope={
                    "scope_type": "asset",
                    "scope_id": "asset_fresh_uat",
                    "visibility": "restricted",
                },
                actor_context_id="actor_fresh_uat",
                issued_at="2026-08-12T00:00:00+00:00",
                known_as_of="2026-08-12T00:00:00+00:00",
                semantic_profile_fingerprint=_MODULE.sha256_json({"profile": "synthetic"}),
                scope_manifest_id="scope_fresh_uat",
                scope_policy_id="scope_policy_fresh_uat",
                scope_policy_version="1",
                scope_policy_fingerprint=_MODULE.sha256_json({"scope": "synthetic"}),
                authority_verifier_root=authority_root,
            )
            count, fingerprint = _MODULE._exact_candidate_result(
                output_dir=output,
                authority_root=authority_root,
                aliases=aliases,
                object_type="mail_table",
                predicate="coo",
                value="Japan",
                projection="p/n",
            )
        self.assertEqual(count, 1)
        self.assertEqual(
            fingerprint,
            _MODULE.sha256_json({"distinct_projection_values": ["A-1"]}),
        )


if __name__ == "__main__":
    unittest.main()
