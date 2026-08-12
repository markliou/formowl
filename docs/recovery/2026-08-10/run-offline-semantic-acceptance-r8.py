#!/usr/bin/env python3
"""Bounded offline adapter for internal diagnostic candidate-only acceptance.

Only the legacy bundle's immutable ``source_inventory_items`` and
``structural_observations`` arrays are decoded, one bundle at a time.  This
script does not import a PST, parser, extractor, or bridge module; it uses the
existing fresh-UAT publisher and exact structured executor only.
"""

from __future__ import annotations

import argparse
import json
import mmap
import os
from pathlib import Path
import shutil
import sys
from typing import Any, Iterator, Mapping, Sequence

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_PYTHON_ROOT = _REPOSITORY_ROOT / "python"
if str(_PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(_PYTHON_ROOT))
# This adapter invokes no tokenizer.  The package's unrelated import-time
# default requires a frozen SentencePiece artifact, so select the existing
# explicit legacy test mode solely to load the persistence/query contracts.
# It is not evidence retrieval and this script makes no tokenizer or
# methodology-quality claim.
os.environ.setdefault("FORMOWL_MAIL_TOKENIZER_MODE", "legacy_ascii_test")

from formowl_contract import (  # noqa: E402
    AdmissibleSemanticScope,
    ContractValidationError,
    CoverageScopeAuthorityVerifier,
    PermissionFirstSemanticPlanner,
    SemanticSchemaAliasMap,
    SemanticTaskSkeleton,
    sha256_json,
)
from formowl_mail.persistence import (  # noqa: E402
    FileDiagnosticStructuralShardStore,
    publish_fresh_uat_attestation,
    sha256_file,
)
from formowl_mail.query import execute_authorized_structured_set  # noqa: E402

_SHA256 = "sha256:"
_SELECTED_ARRAY_FIELDS = ("source_inventory_items", "structural_observations")
_FORBIDDEN_SELECTED_KEYS = frozenset(
    {"legacy_authority_id", "legacy_proof_id", "legacy_coverage_ledger_id"}
)


def _fail(message: str) -> None:
    raise ContractValidationError(message)


def _require_str(value: Mapping[str, Any], field: str) -> str:
    result = value.get(field)
    if not isinstance(result, str) or not result:
        _fail(f"legacy {field} is invalid")
    return result


def _skip_space(payload: mmap.mmap, cursor: int) -> int:
    while cursor < len(payload) and payload[cursor] in b" \t\r\n":
        cursor += 1
    return cursor


def _string_end(payload: mmap.mmap, cursor: int) -> int:
    if cursor >= len(payload) or payload[cursor] != ord('"'):
        _fail("legacy JSON string is invalid")
    escaped = False
    cursor += 1
    while cursor < len(payload):
        character = payload[cursor]
        if escaped:
            escaped = False
        elif character == ord("\\"):
            escaped = True
        elif character == ord('"'):
            return cursor + 1
        cursor += 1
    _fail("legacy JSON string is truncated")


def _json_value_end(payload: mmap.mmap, cursor: int) -> int:
    """Find one encoded JSON value end without decoding unrelated payloads."""

    if cursor >= len(payload):
        _fail("legacy JSON value is truncated")
    if payload[cursor] == ord('"'):
        return _string_end(payload, cursor)
    if payload[cursor] not in (ord("{"), ord("[")):
        while cursor < len(payload) and payload[cursor] not in b",}]\t\r\n ":
            cursor += 1
        return cursor
    stack = [ord("}") if payload[cursor] == ord("{") else ord("]")]
    in_string = False
    escaped = False
    cursor += 1
    while cursor < len(payload):
        character = payload[cursor]
        if in_string:
            if escaped:
                escaped = False
            elif character == ord("\\"):
                escaped = True
            elif character == ord('"'):
                in_string = False
        elif character == ord('"'):
            in_string = True
        elif character == ord("{"):
            stack.append(ord("}"))
        elif character == ord("["):
            stack.append(ord("]"))
        elif character in (ord("}"), ord("]")):
            if character != stack.pop():
                _fail("legacy JSON nesting is invalid")
            if not stack:
                return cursor + 1
        cursor += 1
    _fail("legacy JSON value is truncated")


def _find_selected_array(payload: mmap.mmap, field: str) -> tuple[int, int]:
    """Return one selected top-level JSON array byte range, fail-closed.

    Legacy canonical bundles use compact JSON.  A selected field token may not
    appear more than once; this rejects ambiguous content rather than guessing
    from any mail body or unrelated bridge envelope.
    """

    cursor = _skip_space(payload, 0)
    if cursor >= len(payload) or payload[cursor] != ord("{"):
        _fail("legacy bundle top-level value is invalid")
    cursor = _skip_space(payload, cursor + 1)
    selected: tuple[int, int] | None = None
    while cursor < len(payload) and payload[cursor] != ord("}"):
        key_start = cursor
        key_end = _string_end(payload, key_start)
        try:
            key = json.loads(bytes(payload[key_start:key_end]))
        except json.JSONDecodeError as exc:
            raise ContractValidationError("legacy bundle top-level key is invalid") from exc
        cursor = _skip_space(payload, key_end)
        if cursor >= len(payload) or payload[cursor] != ord(":"):
            _fail("legacy bundle top-level delimiter is invalid")
        value_start = _skip_space(payload, cursor + 1)
        value_end = _json_value_end(payload, value_start)
        if key == field:
            if selected is not None or payload[value_start] != ord("["):
                _fail(f"legacy {field} is missing, ambiguous, or not an array")
            selected = (value_start, value_end)
        cursor = _skip_space(payload, value_end)
        if cursor >= len(payload):
            _fail("legacy bundle top-level JSON is truncated")
        if payload[cursor] == ord("}"):
            break
        if payload[cursor] != ord(","):
            _fail("legacy bundle top-level delimiter is invalid")
        cursor = _skip_space(payload, cursor + 1)
    if selected is None:
        _fail(f"legacy {field} is missing")
    return selected


def _iter_selected_array(payload: mmap.mmap, field: str) -> Iterator[Mapping[str, Any]]:
    """Decode one selected array object at a time from a mapped bundle."""

    start, end = _find_selected_array(payload, field)
    cursor = _skip_space(payload, start + 1)
    if cursor < end and payload[cursor] == ord("]"):
        return
    while cursor < end:
        if payload[cursor] != ord("{"):
            _fail(f"legacy {field} array member is invalid")
        value_end = _json_value_end(payload, cursor)
        try:
            record = json.loads(bytes(payload[cursor:value_end]))
        except json.JSONDecodeError as exc:
            raise ContractValidationError(f"legacy {field} array member is invalid") from exc
        if not isinstance(record, Mapping):
            _fail(f"legacy {field} array member is invalid")
        yield record
        cursor = _skip_space(payload, value_end)
        if cursor >= end:
            _fail(f"legacy {field} array is truncated")
        if payload[cursor] == ord("]"):
            if cursor + 1 != end:
                _fail(f"legacy {field} array is invalid")
            return
        if payload[cursor] != ord(","):
            _fail(f"legacy {field} array delimiter is invalid")
        cursor = _skip_space(payload, cursor + 1)
    _fail(f"legacy {field} array is truncated")


def _forbid_legacy_control_ids(record: Mapping[str, Any], label: str) -> None:
    if _FORBIDDEN_SELECTED_KEYS.intersection(record) or any(
        any(token in key.casefold() for token in ("authority", "proof", "ledger"))
        for key in record
        if isinstance(key, str)
    ):
        _fail(f"{label} contains forbidden legacy authority/proof/ledger ids")


def _header(column: Mapping[str, Any], ordinal: int) -> str:
    for field in ("normalized_header", "original_header"):
        value = column.get(field)
        if isinstance(value, str) and value.strip():
            return value
    return f"column_{ordinal}"


def _rectangular_rows(
    observation: Mapping[str, Any],
    column_ordinals: tuple[int, ...],
) -> list[list[str]]:
    raw_rows = observation.get("rows")
    if not isinstance(raw_rows, list):
        _fail("legacy structural rows are invalid")
    rows: list[list[str]] = []
    for row_ordinal, raw_row in enumerate(raw_rows):
        if not isinstance(raw_row, Mapping) or raw_row.get("row_ordinal") != row_ordinal:
            _fail("legacy structural row ordinal is invalid")
        raw_cells = raw_row.get("cells")
        if not isinstance(raw_cells, list) or len(raw_cells) != len(column_ordinals):
            _fail("legacy structural rows are not rectangular")
        cells: dict[int, str] = {}
        for cell in raw_cells:
            if not isinstance(cell, Mapping):
                _fail("legacy structural cell is invalid")
            column_ordinal = cell.get("column_ordinal")
            if column_ordinal not in column_ordinals or column_ordinal in cells:
                _fail("legacy structural cell column is invalid")
            state = cell.get("cell_state")
            value = cell.get("value")
            if state == "populated" and isinstance(value, str):
                cells[column_ordinal] = value
            elif state in ("blank", "absent") and value is None:
                cells[column_ordinal] = ""
            else:
                _fail("legacy structural cell state/value is invalid")
        if tuple(sorted(cells)) != column_ordinals:
            _fail("legacy structural rows are not rectangular")
        rows.append([cells[column] for column in column_ordinals])
    return rows


def _normalized_shard(bundle_path: Path, ordinal: int) -> dict[str, Any]:
    """Convert one bundle's selected immutable fields into v1 normalized facts."""

    if bundle_path.is_symlink() or not bundle_path.is_file():
        _fail("legacy bundle path is invalid")
    bundle_hash = sha256_file(bundle_path)
    with (
        bundle_path.open("rb") as handle,
        mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as raw,
    ):
        sources: dict[str, dict[str, Any]] = {}
        for item in _iter_selected_array(raw, "source_inventory_items"):
            _forbid_legacy_control_ids(item, "legacy source inventory item")
            legacy_id = _require_str(item, "source_inventory_item_id")
            if legacy_id in sources:
                _fail("legacy source inventory item id is duplicated")
            source_ordinal = item.get("ordinal")
            if type(source_ordinal) is not int or source_ordinal < 0:
                _fail("legacy source inventory ordinal is invalid")
            sources[legacy_id] = {
                # The old identifier is used only as an in-memory join key.  It
                # is never emitted; this opaque deterministic key is path-free.
                "source_key": sha256_json(
                    {
                        "kind": "fresh_uat_source_key_v1",
                        "legacy_bundle_sha256": bundle_hash,
                        "structure_kind": _require_str(item, "structure_kind"),
                        "content_type": _require_str(item, "content_type"),
                        "ordinal": source_ordinal,
                    }
                ),
                "structure_kind": _require_str(item, "structure_kind"),
                "content_type": _require_str(item, "content_type"),
                "source_ordinal": source_ordinal,
                "observation_keys": [],
            }
        observations: list[dict[str, Any]] = []
        for observation_ordinal, observation in enumerate(
            _iter_selected_array(raw, "structural_observations")
        ):
            _forbid_legacy_control_ids(observation, "legacy structural observation")
            source = sources.get(_require_str(observation, "source_inventory_item_id"))
            if source is None:
                _fail("legacy structural observation is not joined to an inventory item")
            raw_columns = observation.get("columns")
            if not isinstance(raw_columns, list) or not raw_columns:
                _fail("legacy structural columns are invalid")
            columns_by_ordinal: dict[int, Mapping[str, Any]] = {}
            for column in raw_columns:
                if not isinstance(column, Mapping):
                    _fail("legacy structural column is invalid")
                column_ordinal = column.get("column_ordinal")
                if (
                    type(column_ordinal) is not int
                    or column_ordinal < 0
                    or column_ordinal in columns_by_ordinal
                ):
                    _fail("legacy structural column ordinal is invalid")
                columns_by_ordinal[column_ordinal] = column
            column_ordinals = tuple(sorted(columns_by_ordinal))
            if column_ordinals != tuple(range(len(column_ordinals))):
                _fail("legacy structural columns are not contiguous")
            columns = [_header(columns_by_ordinal[index], index) for index in column_ordinals]
            rows = _rectangular_rows(observation, column_ordinals)
            observation_key = sha256_json(
                {
                    "kind": "fresh_uat_structural_observation_key_v1",
                    "legacy_bundle_sha256": bundle_hash,
                    "source_key": source["source_key"],
                    "ordinal": observation_ordinal,
                    "structure_kind": _require_str(observation, "structure_kind"),
                    "columns": columns,
                    "rows": rows,
                }
            )
            source["observation_keys"].append(observation_key)
            observations.append(
                {
                    "observation_key": observation_key,
                    "source_key": source["source_key"],
                    "structure_kind": _require_str(observation, "structure_kind"),
                    "columns": columns,
                    "rows": rows,
                }
            )

    selected_sources = [source for source in sources.values() if source["observation_keys"]]
    if not selected_sources or not observations:
        _fail("legacy bundle has no selected structural evidence")
    selected_sources.sort(key=lambda source: (source["source_ordinal"], source["source_key"]))
    source_items: list[dict[str, Any]] = []
    for normalized_ordinal, source in enumerate(selected_sources):
        source_items.append(
            {
                "source_key": source["source_key"],
                "structure_kind": source["structure_kind"],
                "content_type": source["content_type"],
                "ordinal": normalized_ordinal,
                "observation_keys": sorted(source["observation_keys"]),
            }
        )
    normalized_bundle = {
        "schema": "formowl_normalized_evidence_shard_v1",
        "shard_key": sha256_json(
            {"kind": "fresh_uat_shard_key_v1", "legacy_bundle_sha256": bundle_hash}
        ),
        "source_items": source_items,
        "structural_observations": observations,
    }
    return {
        "ordinal": ordinal,
        "normalized_bundle": normalized_bundle,
        "normalized_bundle_sha256": sha256_json(normalized_bundle),
        "immutable_source_hashes": {bundle_hash: bundle_hash},
    }


def _legacy_bundle_paths(source_root: Path) -> tuple[Path, ...]:
    if source_root.is_symlink() or not source_root.is_dir():
        _fail("legacy diagnostic shard root is invalid")
    shard_directories = tuple(
        sorted(
            (path for path in source_root.iterdir() if path.is_dir() and path.name.isdecimal()),
            key=lambda path: path.name,
        )
    )
    if not shard_directories or tuple(path.name for path in shard_directories) != tuple(
        f"{ordinal:08d}" for ordinal in range(len(shard_directories))
    ):
        _fail("legacy diagnostic shard layout is invalid")
    bundle_paths: list[Path] = []
    for shard in shard_directories:
        bundle_directory = shard / "mail-evidence" / "canonical-bundles.private"
        if bundle_directory.is_symlink() or not bundle_directory.is_dir():
            _fail("legacy diagnostic bundle directory is invalid")
        candidates = tuple(
            path
            for path in bundle_directory.iterdir()
            if path.is_file() and not path.is_symlink() and path.suffix == ".json"
        )
        if len(candidates) != 1:
            _fail("legacy diagnostic shard must have exactly one bundle")
        bundle_paths.append(candidates[0])
    return tuple(bundle_paths)


def _load_aliases(profile_path: Path) -> SemanticSchemaAliasMap:
    try:
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractValidationError("semantic profile is unreadable") from exc
    if not isinstance(payload, Mapping) or not isinstance(payload.get("aliases"), Mapping):
        _fail("semantic profile aliases are invalid")
    aliases = payload["aliases"]
    return SemanticSchemaAliasMap(
        object_aliases=aliases.get("object_aliases"),
        predicate_aliases=aliases.get("predicate_aliases"),
        value_aliases=aliases.get("value_aliases"),
        value_domains=aliases.get("value_domains", {}),
    )


def _projection_fingerprint(values: Sequence[str]) -> str:
    return sha256_json({"distinct_projection_values": sorted(set(values))})


def _exact_candidate_result(
    *,
    output_dir: Path,
    authority_root: bytes,
    aliases: SemanticSchemaAliasMap,
    object_type: str,
    predicate: str,
    value: str,
    projection: str,
) -> tuple[int, str]:
    plan = PermissionFirstSemanticPlanner().ground_all_matching(
        skeleton=SemanticTaskSkeleton(
            query_class="attribute_filter",
            projection_slots=("projection",),
            constraint_slots=("object_type", "predicate", "value"),
        ),
        scope=AdmissibleSemanticScope(
            permission_admissible=True,
            source_admissible=True,
            version_admissible=True,
            context_admissible=True,
            time_admissible=True,
            status_admissible=True,
        ),
        aliases=aliases,
        object_type=object_type,
        predicate=predicate,
        value=value,
        projection=projection,
        page_size=10_000,
    )
    store = FileDiagnosticStructuralShardStore(output_dir, create=False)
    manifest = store.load_complete_manifest()
    verifier = CoverageScopeAuthorityVerifier.from_external_root(authority_root)
    projections: set[str] = set()
    for bundle in store.iter_bundles(manifest, scope_authority_verifier=verifier):
        inventory = bundle.source_inventory[0]
        execution = execute_authorized_structured_set(
            plan=plan,
            structural_observations=bundle.structural_observations,
            authorized_inventory_item_ids=tuple(
                item.source_inventory_item_id for item in inventory.items
            ),
            coverage_ledger=bundle.coverage_ledgers[0],
        )
        for match in execution.matches:
            projections.update(match.projection_values)
    values = tuple(sorted(projections))
    return len(values), _projection_fingerprint(values)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--semantic-profile", type=Path, required=True)
    parser.add_argument("--authority-root", type=Path, required=True)
    parser.add_argument("--object-type", required=True)
    parser.add_argument("--predicate", required=True)
    parser.add_argument("--value", required=True)
    parser.add_argument("--projection", required=True)
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--expected-fingerprint", required=True)
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    if arguments.output_dir.exists():
        _fail("fresh output directory must not already exist")
    if arguments.expected_count < 0 or not arguments.expected_fingerprint.startswith(_SHA256):
        _fail("expected semantic acceptance result is invalid")
    bundle_paths = _legacy_bundle_paths(arguments.source_root)
    # First streaming byte-hash pass gives the existing publisher its complete
    # immutable input map without decoding any legacy JSON.  The new publisher
    # consumes normalized shards in the second pass one at a time.
    immutable_hashes: dict[str, str] = {}
    for path in bundle_paths:
        bundle_hash = sha256_file(path)
        immutable_hashes[bundle_hash] = bundle_hash
    if len(immutable_hashes) != len(bundle_paths):
        _fail("legacy bundle byte fingerprints are not distinct")
    authority_root = arguments.authority_root.read_bytes()
    source_fingerprint = sha256_json(
        {"immutable_bundle_sha256": tuple(sorted(immutable_hashes.values()))}
    )
    aliases = _load_aliases(arguments.semantic_profile)
    try:
        publish_fresh_uat_attestation(
            output_dir=arguments.output_dir,
            normalized_shards=(
                _normalized_shard(path, ordinal) for ordinal, path in enumerate(bundle_paths)
            ),
            immutable_source_hashes=immutable_hashes,
            source_asset_id="fresh_uat_asset_r8",
            source_fingerprint=source_fingerprint,
            workspace_id="fresh_uat_workspace_r8",
            owner_user_id="fresh_uat_owner_r8",
            permission_scope={
                "scope_type": "asset",
                "scope_id": "fresh_uat_asset_r8",
                "visibility": "restricted",
            },
            actor_context_id="fresh_uat_actor_r8",
            issued_at="2026-08-12T00:00:00+00:00",
            known_as_of="2026-08-12T00:00:00+00:00",
            semantic_profile_fingerprint=sha256_file(arguments.semantic_profile),
            scope_manifest_id="fresh_uat_scope_r8",
            scope_policy_id="fresh_uat_scope_policy_r8",
            scope_policy_version="1",
            scope_policy_fingerprint=sha256_json({"scope_policy": "fresh_uat_r8"}),
            authority_verifier_root=authority_root,
        )
        count, fingerprint = _exact_candidate_result(
            output_dir=arguments.output_dir,
            authority_root=authority_root,
            aliases=aliases,
            object_type=arguments.object_type,
            predicate=arguments.predicate,
            value=arguments.value,
            projection=arguments.projection,
        )
        passed = count == arguments.expected_count and fingerprint == arguments.expected_fingerprint
        packet = {
            "status": "passed" if passed else "failed",
            "release_decision": "CANDIDATE_EXACT_AGREE" if passed else "CANDIDATE_EXACT_DISAGREE",
            "count": count,
            "fingerprint": fingerprint,
            "oracle_missing_count": 0 if passed else None,
            "oracle_unexpected_count": 0 if passed else None,
            "retrieval_path": "mail_authorized_structured_set",
            "claim_state": "CANDIDATE_MATCHES",
            "canonical_kg": False,
            "source_count": 0,
            "citation_count": 0,
        }
        arguments.packet.parent.mkdir(parents=True, exist_ok=True)
        arguments.packet.write_text(
            json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 0 if passed else 1
    except Exception:
        if arguments.output_dir.exists():
            shutil.rmtree(arguments.output_dir)
        raise


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ContractValidationError as error:
        print(f"offline semantic acceptance failed closed: {error}", file=sys.stderr)
        raise SystemExit(2) from error
