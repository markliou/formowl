from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

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


def _aliases() -> object:
    return _MODULE.SemanticSchemaAliasMap(
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


def _semantic_profile(
    *,
    workspace_id: str = "workspace-private",
    owner_user_id: str = "owner-private",
    actor_context_id: str = "actor-private",
    known_as_of: str = "2026-08-12T00:00:00+00:00",
) -> object:
    aliases = _aliases()
    return _MODULE.DiagnosticSemanticProfile(
        profile_id="diagnostic-synthetic",
        profile_version="1",
        profile_fingerprint=_MODULE.DiagnosticSemanticProfile.fingerprint_for(
            profile_id="diagnostic-synthetic",
            profile_version="1",
            schema_alias_map=aliases,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            actor_context_id=actor_context_id,
            known_as_of=known_as_of,
        ),
        schema_alias_map=aliases,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        actor_context_id=actor_context_id,
        known_as_of=known_as_of,
    )


def _write_semantic_profile(path: Path, profile: object) -> None:
    path.write_text(
        json.dumps(profile.to_private_dict(), ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def _canonical_list_of_lists_fingerprint(values: list[list[str]]) -> str:
    encoded = json.dumps(
        values,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


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

    def test_explicit_empty_or_non_tabular_observations_are_excluded(self) -> None:
        payload = _bundle()
        payload["source_inventory_items"].append(
            {
                "source_inventory_item_id": "empty_table_source",
                "structure_kind": "html_table",
                "content_type": "text/html",
                "ordinal": 11,
            }
        )
        payload["source_inventory_items"].append(
            {
                "source_inventory_item_id": "non_tabular_source",
                "structure_kind": "mail_metadata",
                "content_type": "text/plain",
                "ordinal": 12,
            }
        )
        payload["structural_observations"].extend(
            [
                {
                    "source_inventory_item_id": "empty_table_source",
                    "structure_kind": "html_table",
                    "columns": [],
                    "rows": [],
                },
                {
                    "source_inventory_item_id": "non_tabular_source",
                    "structure_kind": "mail_metadata",
                },
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = _write_bundle(Path(temporary), 0, payload)
            shard = _MODULE._normalized_shard(path, 0)

        normalized = shard["normalized_bundle"]
        self.assertEqual(len(normalized["source_items"]), 1)
        self.assertEqual(len(normalized["structural_observations"]), 1)

    def test_valid_header_only_table_remains_a_complete_table(self) -> None:
        payload = _bundle()
        payload["structural_observations"][0]["rows"] = []
        with tempfile.TemporaryDirectory() as temporary:
            path = _write_bundle(Path(temporary), 0, payload)
            shard = _MODULE._normalized_shard(path, 0)

        observation = shard["normalized_bundle"]["structural_observations"][0]
        self.assertEqual(observation["columns"], ["COO", "P/N", "column_2"])
        self.assertEqual(observation["rows"], [])

    def test_malformed_table_topology_fails_closed_instead_of_being_skipped(self) -> None:
        cases = (
            ("empty_columns_with_rows", [], [{"row_ordinal": 0, "cells": []}]),
            ("table_without_topology", None, None),
        )
        for label, columns, rows in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                payload = _bundle()
                observation = payload["structural_observations"][0]
                observation["structure_kind"] = "html_table"
                observation["columns"] = columns
                observation["rows"] = rows
                path = _write_bundle(Path(temporary), 0, payload)
                with self.assertRaisesRegex(Exception, "legacy structural"):
                    _MODULE._normalized_shard(path, 0)

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

    def test_projection_fingerprint_matches_canonical_list_of_lists_abi(self) -> None:
        projections = (
            ("Japan", "B-2"),
            ("Japan", "A-1"),
            ("Japan", "B-2"),
        )
        expected_rows = [["Japan", "A-1"], ["Japan", "B-2"]]
        expected = _canonical_list_of_lists_fingerprint(expected_rows)

        self.assertEqual(
            _MODULE._canonical_projection_tuples(projections), tuple(map(tuple, expected_rows))
        )
        self.assertEqual(_MODULE._projection_fingerprint(projections), expected)
        self.assertNotEqual(
            _MODULE._projection_fingerprint(projections),
            _MODULE.sha256_json({"distinct_projection_values": ["A-1", "B-2", "Japan"]}),
        )

    def test_validated_profile_declares_all_attestation_identity_inputs(self) -> None:
        profile = _semantic_profile()
        source_fingerprint = _MODULE.sha256_json({"synthetic": "source"})
        inputs = _MODULE._fresh_attestation_inputs(
            profile=profile,
            issued_at="2026-08-12T01:00:00+00:00",
            source_fingerprint=source_fingerprint,
        )

        self.assertEqual(inputs["workspace_id"], "workspace-private")
        self.assertEqual(inputs["owner_user_id"], "owner-private")
        self.assertEqual(inputs["actor_context_id"], "actor-private")
        self.assertEqual(inputs["known_as_of"], "2026-08-12T00:00:00+00:00")
        self.assertEqual(inputs["semantic_profile_fingerprint"], profile.profile_fingerprint)
        self.assertEqual(
            inputs["scope_policy_fingerprint"],
            _MODULE.sha256_json(
                {
                    "kind": "fresh_uat_scope_policy_v1",
                    "profile_fingerprint": profile.profile_fingerprint,
                    "source_fingerprint": source_fingerprint,
                    "workspace_id": "workspace-private",
                    "owner_user_id": "owner-private",
                    "actor_context_id": "actor-private",
                    "known_as_of": "2026-08-12T00:00:00+00:00",
                    "issued_at": "2026-08-12T01:00:00+00:00",
                }
            ),
        )
        with self.assertRaisesRegex(Exception, "precedes"):
            _MODULE._fresh_attestation_inputs(
                profile=profile,
                issued_at="2026-08-11T23:59:59+00:00",
                source_fingerprint=source_fingerprint,
            )

    def test_profile_loader_uses_validated_private_profile_not_file_sha(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile_path = Path(temporary) / "semantic-profile.private.json"
            profile = _semantic_profile()
            _write_semantic_profile(profile_path, profile)
            self.assertEqual(_MODULE._load_semantic_profile(profile_path), profile)

            payload = profile.to_private_dict()
            payload["profile_fingerprint"] = _MODULE.sha256_json({"file": "not-profile"})
            profile_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(Exception, "semantic profile is unavailable"):
                _MODULE._load_semantic_profile(profile_path)

    def test_main_binds_profile_identity_and_writes_only_safe_metadata_packet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "source"
            _write_bundle(source_root, 0, _bundle(include_empty_cell=False))
            profile_path = root / "semantic-profile.private.json"
            profile = _semantic_profile()
            _write_semantic_profile(profile_path, profile)
            authority_root = root / "scope-authority-root.bin"
            authority_root.write_bytes(b"synthetic-authority-root")
            output_dir = root / "fresh-output"
            packet_path = root / "packet.json"
            expected_fingerprint = _MODULE._projection_fingerprint((("A-1",),))
            arguments = argparse.Namespace(
                source_root=source_root,
                output_dir=output_dir,
                packet=packet_path,
                semantic_profile=profile_path,
                authority_root=authority_root,
                issued_at="2026-08-12T01:00:00+00:00",
                object_type="mail_table",
                predicate="coo",
                value="Japan",
                projection="p/n",
                expected_count=1,
                expected_fingerprint=expected_fingerprint,
            )
            receipt = SimpleNamespace(
                attestation_binding_fingerprint=_MODULE.sha256_json({"receipt": "synthetic"})
            )
            with (
                patch.object(_MODULE, "_arguments", return_value=arguments),
                patch.object(
                    _MODULE,
                    "publish_fresh_uat_attestation",
                    return_value=receipt,
                ) as publisher,
                patch.object(
                    _MODULE,
                    "_exact_candidate_result",
                    return_value=(1, expected_fingerprint),
                ),
            ):
                self.assertEqual(_MODULE.main(), 0)

            invocation = publisher.call_args.kwargs
            self.assertEqual(invocation["workspace_id"], profile.workspace_id)
            self.assertEqual(invocation["owner_user_id"], profile.owner_user_id)
            self.assertEqual(invocation["actor_context_id"], profile.actor_context_id)
            self.assertEqual(invocation["known_as_of"], profile.known_as_of)
            self.assertEqual(
                invocation["semantic_profile_fingerprint"],
                profile.profile_fingerprint,
            )
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            rendered = json.dumps(packet, ensure_ascii=False, sort_keys=True)
            self.assertEqual(packet["status"], "passed")
            self.assertEqual(packet["issued_at"], arguments.issued_at)
            self.assertEqual(packet["known_as_of"], profile.known_as_of)
            self.assertEqual(
                packet["semantic_profile_fingerprint"],
                profile.profile_fingerprint,
            )
            self.assertEqual(
                packet["attestation_binding_fingerprint"],
                receipt.attestation_binding_fingerprint,
            )
            for private_value in (
                profile.workspace_id,
                profile.owner_user_id,
                profile.actor_context_id,
                str(source_root),
            ):
                self.assertNotIn(private_value, rendered)

    def test_packet_write_failure_cleans_partial_packet_and_fresh_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "source"
            _write_bundle(source_root, 0, _bundle(include_empty_cell=False))
            profile_path = root / "semantic-profile.private.json"
            _write_semantic_profile(profile_path, _semantic_profile())
            authority_root = root / "scope-authority-root.bin"
            authority_root.write_bytes(b"synthetic-authority-root")
            output_dir = root / "fresh-output"
            packet_path = root / "packet.json"
            expected_fingerprint = _MODULE._projection_fingerprint((("A-1",),))
            arguments = argparse.Namespace(
                source_root=source_root,
                output_dir=output_dir,
                packet=packet_path,
                semantic_profile=profile_path,
                authority_root=authority_root,
                issued_at="2026-08-12T01:00:00+00:00",
                object_type="mail_table",
                predicate="coo",
                value="Japan",
                projection="p/n",
                expected_count=1,
                expected_fingerprint=expected_fingerprint,
            )

            def publish_with_synthetic_output(**_kwargs: object) -> object:
                output_dir.mkdir()
                (output_dir / "complete-publication-marker").write_text("present", encoding="utf-8")
                return SimpleNamespace(
                    attestation_binding_fingerprint=_MODULE.sha256_json({"receipt": "synthetic"})
                )

            def write_partial_packet_then_fail(packet_path: Path, _packet: object) -> None:
                packet_path.write_text("{", encoding="utf-8")
                raise OSError("synthetic packet write failure")

            with (
                patch.object(_MODULE, "_arguments", return_value=arguments),
                patch.object(
                    _MODULE,
                    "publish_fresh_uat_attestation",
                    side_effect=publish_with_synthetic_output,
                ),
                patch.object(
                    _MODULE,
                    "_exact_candidate_result",
                    return_value=(1, expected_fingerprint),
                ),
                patch.object(
                    _MODULE,
                    "_write_packet",
                    side_effect=write_partial_packet_then_fail,
                ),
            ):
                with self.assertRaisesRegex(OSError, "synthetic packet write failure"):
                    _MODULE.main()

            self.assertFalse(packet_path.exists())
            self.assertFalse(output_dir.exists())

    def test_strict_loader_candidate_executor_preserves_exact_value_selection(self) -> None:
        aliases = _aliases()
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
            _canonical_list_of_lists_fingerprint([["A-1"]]),
        )


if __name__ == "__main__":
    unittest.main()
