#!/usr/bin/env python3
"""Bounded offline adapter for internal diagnostic candidate-only acceptance.

Only the legacy bundle's immutable ``source_inventory_items`` and
``structural_observations`` arrays are decoded, one bundle at a time.  This
script does not import a PST, parser, extractor, or bridge module; it uses the
existing fresh-UAT publisher and exact structured executor only.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import mmap
import os
from pathlib import Path
import shutil
import sys
from typing import Any, Iterator, Mapping, Sequence
import unicodedata

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
from formowl_mail.diagnostic_mcp import DiagnosticSemanticProfile  # noqa: E402
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


def _require_sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != len(_SHA256) + 64
        or not value.startswith(_SHA256)
        or any(character not in "0123456789abcdef" for character in value[len(_SHA256) :])
    ):
        _fail(f"{label} is invalid")
    return value


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


def _is_tabular_structure_kind(value: str) -> bool:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip().replace("-", "_")
    return normalized == "table" or normalized.endswith("_table")


def _is_explicitly_excludable_structural_observation(
    *,
    structure_kind: str,
    raw_columns: object,
    raw_rows: object,
) -> bool:
    """Allow only explicit empty or non-tabular facts to leave this adapter.

    A table with headers but zero rows remains a valid table and is preserved.
    A table-shaped observation with any incomplete topology is not an empty
    fact; it falls through to the strict rectangular validation below.
    """

    if raw_columns == [] and raw_rows == []:
        return True
    return (
        not _is_tabular_structure_kind(structure_kind) and raw_columns is None and raw_rows is None
    )


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
            structure_kind = _require_str(observation, "structure_kind")
            raw_columns = observation.get("columns")
            raw_rows = observation.get("rows")
            if _is_explicitly_excludable_structural_observation(
                structure_kind=structure_kind,
                raw_columns=raw_columns,
                raw_rows=raw_rows,
            ):
                # An explicitly empty structural observation or a non-tabular
                # observation without tabular topology has no executable
                # structured facts. It is deterministically inadmissible to
                # this table-only normalized set.
                continue
            if not isinstance(raw_columns, list) or not raw_columns:
                _fail("legacy structural columns are invalid")
            if not isinstance(raw_rows, list):
                _fail("legacy structural rows are invalid")
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
                    "structure_kind": structure_kind,
                    "columns": columns,
                    "rows": rows,
                }
            )
            source["observation_keys"].append(observation_key)
            observations.append(
                {
                    "observation_key": observation_key,
                    "source_key": source["source_key"],
                    "structure_kind": structure_kind,
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


def _load_semantic_profile(profile_path: Path) -> DiagnosticSemanticProfile:
    try:
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            _fail("semantic profile is invalid")
        return DiagnosticSemanticProfile.from_private_dict(payload)
    except (
        OSError,
        TypeError,
        ValueError,
        UnicodeError,
        json.JSONDecodeError,
        ContractValidationError,
    ) as exc:
        raise ContractValidationError("semantic profile is unavailable") from exc


def _normalized_semantic_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _canonical_projection_tuples(
    projections: Sequence[tuple[str, ...]],
) -> tuple[tuple[str, ...], ...]:
    checked: list[tuple[str, ...]] = []
    for projection in projections:
        if (
            not isinstance(projection, tuple)
            or not projection
            or any(not isinstance(value, str) or not value.strip() for value in projection)
        ):
            _fail("candidate projection values are invalid")
        checked.append(projection)
    return tuple(
        sorted(
            set(checked),
            key=lambda values: (
                tuple(_normalized_semantic_text(value) for value in values),
                values,
            ),
        )
    )


def _projection_fingerprint(projections: Sequence[tuple[str, ...]]) -> str:
    ordered = _canonical_projection_tuples(projections)
    return sha256_json([list(projection) for projection in ordered])


def _parse_iso_instant(value: str, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        _fail(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail(f"{label} is invalid")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(f"{label} is invalid")
    return parsed


def _fresh_attestation_inputs(
    *,
    profile: DiagnosticSemanticProfile,
    issued_at: str,
    source_fingerprint: str,
) -> dict[str, Any]:
    if not isinstance(profile, DiagnosticSemanticProfile):
        _fail("semantic profile is invalid")
    _require_sha256(source_fingerprint, "fresh source fingerprint")
    issued_at_value = _parse_iso_instant(issued_at, "operator issued-at")
    known_as_of_value = _parse_iso_instant(profile.known_as_of, "semantic profile known-as-of")
    if issued_at_value < known_as_of_value:
        _fail("operator issued-at precedes semantic profile known-as-of")
    return {
        "workspace_id": profile.workspace_id,
        "owner_user_id": profile.owner_user_id,
        "actor_context_id": profile.actor_context_id,
        "issued_at": issued_at,
        "known_as_of": profile.known_as_of,
        "semantic_profile_fingerprint": profile.profile_fingerprint,
        "scope_policy_fingerprint": sha256_json(
            {
                "kind": "fresh_uat_scope_policy_v1",
                "profile_fingerprint": profile.profile_fingerprint,
                "source_fingerprint": source_fingerprint,
                "workspace_id": profile.workspace_id,
                "owner_user_id": profile.owner_user_id,
                "actor_context_id": profile.actor_context_id,
                "known_as_of": profile.known_as_of,
                "issued_at": issued_at,
            }
        ),
    }


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
    projections: set[tuple[str, ...]] = set()
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
            projections.add(match.projection_values)
    ordered_projections = _canonical_projection_tuples(tuple(projections))
    return len(ordered_projections), _projection_fingerprint(ordered_projections)


def _write_packet(packet_path: Path, packet: Mapping[str, Any]) -> None:
    """Write the diagnostic metadata packet after the bounded acceptance run."""

    packet_path.parent.mkdir(parents=True, exist_ok=True)
    packet_path.write_text(
        json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--semantic-profile", type=Path, required=True)
    parser.add_argument("--authority-root", type=Path, required=True)
    parser.add_argument("--issued-at", required=True)
    parser.add_argument("--object-type", required=True)
    parser.add_argument("--predicate", required=True)
    parser.add_argument("--value", required=True)
    parser.add_argument("--projection", required=True)
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--expected-fingerprint", required=True)
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    if arguments.output_dir.exists() or arguments.output_dir.is_symlink():
        _fail("fresh output directory must not already exist")
    if arguments.expected_count < 0:
        _fail("expected semantic acceptance result is invalid")
    _require_sha256(arguments.expected_fingerprint, "expected semantic acceptance result")
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
    profile = _load_semantic_profile(arguments.semantic_profile)
    attestation_inputs = _fresh_attestation_inputs(
        profile=profile,
        issued_at=arguments.issued_at,
        source_fingerprint=source_fingerprint,
    )
    try:
        receipt = publish_fresh_uat_attestation(
            output_dir=arguments.output_dir,
            normalized_shards=(
                _normalized_shard(path, ordinal) for ordinal, path in enumerate(bundle_paths)
            ),
            immutable_source_hashes=immutable_hashes,
            source_asset_id="fresh_uat_asset_r8",
            source_fingerprint=source_fingerprint,
            workspace_id=attestation_inputs["workspace_id"],
            owner_user_id=attestation_inputs["owner_user_id"],
            permission_scope={
                "scope_type": "asset",
                "scope_id": "fresh_uat_asset_r8",
                "visibility": "restricted",
            },
            actor_context_id=attestation_inputs["actor_context_id"],
            issued_at=attestation_inputs["issued_at"],
            known_as_of=attestation_inputs["known_as_of"],
            semantic_profile_fingerprint=attestation_inputs["semantic_profile_fingerprint"],
            scope_manifest_id="fresh_uat_scope_r8",
            scope_policy_id="fresh_uat_scope_policy_r8",
            scope_policy_version="1",
            scope_policy_fingerprint=attestation_inputs["scope_policy_fingerprint"],
            authority_verifier_root=authority_root,
        )
        count, fingerprint = _exact_candidate_result(
            output_dir=arguments.output_dir,
            authority_root=authority_root,
            aliases=profile.schema_alias_map,
            object_type=arguments.object_type,
            predicate=arguments.predicate,
            value=arguments.value,
            projection=arguments.projection,
        )
        passed = count == arguments.expected_count and fingerprint == arguments.expected_fingerprint
        packet = {
            "artifact_type": "formowl_offline_semantic_acceptance_r8",
            "status": "passed" if passed else "failed",
            "release_decision": ("CANDIDATE_EXACT_AGREE" if passed else "CANDIDATE_EXACT_DISAGREE"),
            "count": count,
            "fingerprint": fingerprint,
            "oracle_missing_count": 0 if passed else None,
            "oracle_unexpected_count": 0 if passed else None,
            "retrieval_path": "mail_authorized_structured_set",
            "claim_state": "CANDIDATE_MATCHES",
            "canonical_kg": False,
            "source_count": 0,
            "citation_count": 0,
            # The packet binds the validated private profile without exposing
            # its aliases, workspace, owner, actor, or source contents.
            "issued_at": attestation_inputs["issued_at"],
            "known_as_of": attestation_inputs["known_as_of"],
            "semantic_profile_fingerprint": attestation_inputs["semantic_profile_fingerprint"],
            "attestation_binding_fingerprint": receipt.attestation_binding_fingerprint,
        }
        _write_packet(arguments.packet, packet)
        return 0 if passed else 1
    except Exception:
        arguments.packet.unlink(missing_ok=True)
        if arguments.output_dir.exists():
            shutil.rmtree(arguments.output_dir)
        raise


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ContractValidationError as error:
        print(f"offline semantic acceptance failed closed: {error}", file=sys.stderr)
        raise SystemExit(2) from error
