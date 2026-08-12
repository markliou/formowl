from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
from typing import Any, Callable, Iterator, Mapping, Protocol, Sequence, runtime_checkable

from formowl_contract import (
    AnswerClaim,
    ClaimRequirement,
    ContractValidationError,
    CoverageAuthorizationBinding,
    CoverageItemAuthorizationDecision,
    CoverageItemRelevanceDecision,
    CoverageLedger,
    CoverageObservationPartition,
    CoverageScopeAuthority,
    CoverageScopeAuthorityVerifier,
    CoverageScopePartition,
    CoverageScopePolicyBinding,
    CoverageProofRecord,
    CoverageVersionBinding,
    DisplayPagination,
    SourceInventory,
    SourceInventoryItem,
    StructuralCell,
    StructuralColumn,
    StructuralObservation,
    StructuralRow,
    VersionManifest,
    sha256_json,
    stable_resource_contract_id,
    validate_permission_scope,
)

from .bundle import (
    EmailMessage,
    EmailMessageOccurrence,
    MailEvidenceBundle,
    MailArchiveOccurrence,
    MailFolderOccurrence,
    MailImportSession,
    MailParseRun,
    _MAIL_EVIDENCE_PERSISTENCE_CONSUME_CAPABILITY,
)
from .query import MailEvidenceQueryResult

_SAFE_RECORD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_CANONICAL_JSON_WRITE_BUFFER_BYTES = 1024 * 1024
_DIAGNOSTIC_EXISTING_EXPORT_VERIFICATION_ARTIFACT_TYPE = (
    "diagnostic_existing_export_verification_v2"
)
DIAGNOSTIC_EXISTING_EXPORT_SCOPE_KIND = "fully_accounted_existing_export_structural_scope_v1"
DIAGNOSTIC_STRUCTURAL_BASELINE_SCOPE_KIND = "authorized_structural_baseline_v1"
DIAGNOSTIC_STRUCTURAL_SCOPE_POLICY_ID = "diagnostic_structural_baseline_scope"
DIAGNOSTIC_STRUCTURAL_SCOPE_POLICY_VERSION = "2"
DIAGNOSTIC_STRUCTURAL_BRIDGE_PRODUCER_TYPE = "local_companion_parser"
DIAGNOSTIC_STRUCTURAL_BRIDGE_IMPLEMENTATION_VERSION = "diagnostic_structural_bridge_v2"
_DIAGNOSTIC_STRUCTURAL_AGGREGATE_ARTIFACT_TYPE = "diagnostic_structural_aggregate_manifest_v4"
_DIAGNOSTIC_STRUCTURAL_AGGREGATE_CONTRACT_REVISION = "body_segment_source_split_v1"
_DIAGNOSTIC_STRUCTURAL_ALLOWED_BODY_SEGMENT_SOURCE_TYPES = frozenset(
    {"message_body", "attachment_text"}
)

MailEvidenceVerification = Callable[[MailEvidenceBundle], dict[str, Any]]


def _canonical_json_utf8_chunks(payload: Mapping[str, Any]) -> Iterator[bytes]:
    write_limit = _CANONICAL_JSON_WRITE_BUFFER_BYTES
    if not isinstance(write_limit, int) or isinstance(write_limit, bool) or write_limit < 4:
        raise ContractValidationError("canonical JSON write buffer must be at least four bytes")
    max_characters = max(1, write_limit // 4)
    for chunk in json.JSONEncoder(
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).iterencode(payload):
        for offset in range(0, len(chunk), max_characters):
            encoded = chunk[offset : offset + max_characters].encode("utf-8")
            if len(encoded) > write_limit:
                raise ContractValidationError("canonical JSON chunk exceeds the write buffer")
            yield encoded


def _canonical_bundle_persistence_fingerprint(bundle: MailEvidenceBundle) -> str:
    if not isinstance(bundle, MailEvidenceBundle):
        raise ContractValidationError("canonical persistence fingerprint requires a typed bundle")
    payload = bundle.to_persistence_dict()
    digest = hashlib.sha256()
    chunks = _canonical_json_utf8_chunks(payload)
    try:
        for encoded in chunks:
            digest.update(encoded)
    finally:
        del chunks
        del payload
    return f"sha256:{digest.hexdigest()}"


def _write_canonical_bundle_persistence(
    descriptor: int,
    bundle: MailEvidenceBundle,
) -> str:
    if not isinstance(descriptor, int) or descriptor < 0:
        raise ContractValidationError("mail evidence persistence descriptor is invalid")
    if not isinstance(bundle, MailEvidenceBundle):
        raise ContractValidationError("mail evidence persistence requires a typed bundle")
    payload = bundle.to_persistence_dict()
    digest = hashlib.sha256()
    chunks = _canonical_json_utf8_chunks(payload)
    buffer = bytearray()
    try:
        for encoded in chunks:
            digest.update(encoded)
            if buffer and len(buffer) + len(encoded) > _CANONICAL_JSON_WRITE_BUFFER_BYTES:
                _write_all(descriptor, bytes(buffer))
                buffer.clear()
            if len(encoded) >= _CANONICAL_JSON_WRITE_BUFFER_BYTES:
                _write_all(descriptor, encoded)
            else:
                buffer.extend(encoded)
        if buffer:
            _write_all(descriptor, bytes(buffer))
    finally:
        del chunks
        del payload
    return f"sha256:{digest.hexdigest()}"


def _write_all(descriptor: int, payload: bytes | bytearray) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("mail evidence bundle write failed")
        remaining = remaining[written:]


@dataclass(frozen=True)
class VerifiedMailEvidencePublication:
    write_count: int
    owner_query: dict[str, Any]
    created: bool


@dataclass(frozen=True)
class FreshUatAttestationReceipt:
    """Metadata-only receipt for a fresh internal diagnostic-UAT publication."""

    historical_provenance_status: str
    aggregate_manifest_id: str

    def __post_init__(self) -> None:
        if self.historical_provenance_status != "legacy_authority_unverified":
            raise ContractValidationError("fresh UAT provenance status is invalid")
        _validate_task_record_id(self.aggregate_manifest_id, "aggregate_manifest_id")


_FRESH_UAT_SHARD_FIELDS = frozenset(
    {
        "ordinal",
        "normalized_bundle",
        "normalized_bundle_sha256",
        "immutable_source_hashes",
    }
)
_FRESH_UAT_LEGACY_FIELDS = frozenset(
    {
        "legacy_authority_id",
        "legacy_proof_id",
        "legacy_coverage_ledger_id",
    }
)


def _validate_fresh_uat_attestation_input(
    *,
    normalized_shards: Sequence[Mapping[str, Any]],
    immutable_source_hashes: Mapping[str, str],
) -> tuple[Mapping[str, Any], ...]:
    """Validate only current, hash-pinned normalized shard facts before writes."""

    if (
        isinstance(normalized_shards, (str, bytes))
        or not isinstance(normalized_shards, Sequence)
        or not normalized_shards
    ):
        raise ContractValidationError("fresh UAT normalized shards are invalid")
    if not isinstance(immutable_source_hashes, Mapping):
        raise ContractValidationError("fresh UAT immutable source hashes are invalid")

    normalized = tuple(normalized_shards)
    expected_immutable_hashes: dict[str, str] = {}
    for expected_ordinal, shard in enumerate(normalized):
        if not isinstance(shard, Mapping):
            raise ContractValidationError("fresh UAT normalized shard is invalid")
        shard_fields = set(shard)
        if shard_fields & _FRESH_UAT_LEGACY_FIELDS or shard_fields != _FRESH_UAT_SHARD_FIELDS:
            raise ContractValidationError("fresh UAT legacy provenance is not accepted")
        if shard.get("ordinal") != expected_ordinal:
            raise ContractValidationError("fresh UAT shard ordinal is invalid")
        normalized_bundle = shard.get("normalized_bundle")
        supplied_hash = shard.get("normalized_bundle_sha256")
        if (
            not isinstance(normalized_bundle, Mapping)
            or not isinstance(supplied_hash, str)
            or not _SHA256.fullmatch(supplied_hash)
            or sha256_json(dict(normalized_bundle)) != supplied_hash
        ):
            raise ContractValidationError("fresh UAT normalized bundle hash is invalid")
        per_shard_hashes = shard.get("immutable_source_hashes")
        if not isinstance(per_shard_hashes, Mapping) or not per_shard_hashes:
            raise ContractValidationError("fresh UAT immutable source hashes are invalid")
        for source_key, source_hash in per_shard_hashes.items():
            if (
                not isinstance(source_key, str)
                or not source_key
                or not isinstance(source_hash, str)
                or not _SHA256.fullmatch(source_hash)
                or source_key in expected_immutable_hashes
            ):
                raise ContractValidationError("fresh UAT immutable source hashes are invalid")
            expected_immutable_hashes[source_key] = source_hash

    supplied_immutable_hashes = dict(immutable_source_hashes)
    if (
        supplied_immutable_hashes != expected_immutable_hashes
        or any(
            not isinstance(source_key, str)
            or not source_key
            or not isinstance(source_hash, str)
            or not _SHA256.fullmatch(source_hash)
            for source_key, source_hash in supplied_immutable_hashes.items()
        )
    ):
        raise ContractValidationError("fresh UAT immutable source hashes are inconsistent")
    return normalized


def _build_fresh_uat_bundle(
    *,
    normalized_shard: Mapping[str, Any],
    source_asset_id: str,
    source_fingerprint: str,
    workspace_id: str,
    owner_user_id: str,
    permission_scope: Mapping[str, Any],
    actor_context_id: str,
    issued_at: str,
    semantic_profile_fingerprint: str,
    scope_manifest_id: str,
    scope_policy_id: str,
    scope_policy_version: str,
    scope_policy_fingerprint: str,
    authority_verifier_root: str | bytes,
) -> tuple[MailEvidenceBundle, CoverageScopeAuthorityVerifier]:
    """Project one normalized current shard into strict-loadable typed evidence."""

    if not isinstance(normalized_shard, Mapping):
        raise ContractValidationError("fresh UAT normalized shard is invalid")
    normalized_bundle = normalized_shard.get("normalized_bundle")
    normalized_bundle_sha256 = normalized_shard.get("normalized_bundle_sha256")
    if (
        not isinstance(normalized_bundle, Mapping)
        or not isinstance(normalized_bundle_sha256, str)
        or sha256_json(dict(normalized_bundle)) != normalized_bundle_sha256
        or set(normalized_bundle)
        != {"schema", "shard_key", "source_items", "structural_observations"}
        or normalized_bundle.get("schema") != "formowl_normalized_evidence_shard_v1"
    ):
        raise ContractValidationError("fresh UAT normalized bundle is invalid")
    shard_key = normalized_bundle.get("shard_key")
    source_items = normalized_bundle.get("source_items")
    structural_rows = normalized_bundle.get("structural_observations")
    if (
        not isinstance(shard_key, str)
        or not shard_key
        or not isinstance(source_items, list)
        or not source_items
        or not isinstance(structural_rows, list)
        or not structural_rows
    ):
        raise ContractValidationError("fresh UAT normalized bundle is invalid")
    normalized_scope = validate_permission_scope(permission_scope)
    parser_fingerprint = sha256_json(
        {
            "materializer": "fresh_uat_normalized_shard_v1",
            "normalized_bundle_sha256": normalized_bundle_sha256,
        }
    )
    observations_by_source: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
    for observation in structural_rows:
        if (
            not isinstance(observation, Mapping)
            or set(observation)
            != {
                "observation_key",
                "source_key",
                "structure_kind",
                "columns",
                "rows",
            }
            or not isinstance(observation.get("observation_key"), str)
            or not observation["observation_key"]
            or not isinstance(observation.get("source_key"), str)
            or not observation["source_key"]
            or not isinstance(observation.get("structure_kind"), str)
            or not observation["structure_kind"]
            or not isinstance(observation.get("columns"), list)
            or not observation["columns"]
            or any(not isinstance(column, str) or not column for column in observation["columns"])
            or not isinstance(observation.get("rows"), list)
        ):
            raise ContractValidationError("fresh UAT normalized structural observation is invalid")
        observation_id = stable_resource_contract_id(
            "freshuatobservation",
            "FreshUatNormalizedObservation",
            {
                "shard_key": shard_key,
                "observation_key": observation["observation_key"],
                "normalized_bundle_sha256": normalized_bundle_sha256,
            },
        )
        observations_by_source.setdefault(observation["source_key"], []).append(
            (observation_id, observation)
        )

    unbound_items: list[SourceInventoryItem] = []
    item_specs: dict[str, Mapping[str, Any]] = {}
    for expected_ordinal, source_item in enumerate(source_items):
        if (
            not isinstance(source_item, Mapping)
            or set(source_item)
            != {
                "source_key",
                "structure_kind",
                "content_type",
                "ordinal",
                "observation_keys",
            }
            or not isinstance(source_item.get("source_key"), str)
            or not source_item["source_key"]
            or source_item["source_key"] in item_specs
            or not isinstance(source_item.get("structure_kind"), str)
            or not source_item["structure_kind"]
            or not isinstance(source_item.get("content_type"), str)
            or not source_item["content_type"]
            or source_item.get("ordinal") != expected_ordinal
            or not isinstance(source_item.get("observation_keys"), list)
        ):
            raise ContractValidationError("fresh UAT normalized source item is invalid")
        source_key = source_item["source_key"]
        source_observation_ids = tuple(
            observation_id for observation_id, _ in observations_by_source.get(source_key, ())
        )
        if not source_observation_ids:
            raise ContractValidationError("fresh UAT normalized source coverage is incomplete")
        item_specs[source_key] = source_item
        unbound_items.append(
            SourceInventoryItem.create(
                source_asset_id=source_asset_id,
                structure_kind=source_item["structure_kind"],
                content_type=source_item["content_type"],
                ordinal=expected_ordinal,
                processing_state="parsed",
                raw_retention_state="externally_managed",
                source_fingerprint=source_fingerprint,
                parser_fingerprint=parser_fingerprint,
                permission_scope=normalized_scope,
                location={"normalized_source_key": source_key},
                source_observation_ids=source_observation_ids,
            )
        )
    if set(observations_by_source) != set(item_specs):
        raise ContractValidationError("fresh UAT normalized source coverage is incomplete")
    inventory = SourceInventory.create(
        source_asset_id=source_asset_id,
        source_fingerprint=source_fingerprint,
        parser_fingerprint=parser_fingerprint,
        items=unbound_items,
        created_at=issued_at,
    )
    item_by_source_key = {
        str(dict(item.location)["normalized_source_key"]): item for item in inventory.items
    }
    structural_observations: list[StructuralObservation] = []
    for source_key, source_observations in observations_by_source.items():
        inventory_item = item_by_source_key.get(source_key)
        if inventory_item is None:
            raise ContractValidationError("fresh UAT normalized source coverage is incomplete")
        for observation_id, observation in source_observations:
            columns = tuple(
                StructuralColumn(
                    column_ordinal=ordinal,
                    original_header=header,
                    normalized_header=header,
                )
                for ordinal, header in enumerate(observation["columns"])
            )
            rows: list[StructuralRow] = []
            for row_ordinal, row in enumerate(observation["rows"]):
                if (
                    not isinstance(row, list)
                    or len(row) != len(columns)
                    or any(not isinstance(value, str) for value in row)
                ):
                    raise ContractValidationError("fresh UAT normalized structural row is invalid")
                rows.append(
                    StructuralRow(
                        row_ordinal=row_ordinal,
                        cells=tuple(
                            StructuralCell(
                                cell_state="populated" if value else "empty",
                                row_ordinal=row_ordinal,
                                column_ordinal=column_ordinal,
                                value=value or None,
                                normalized_value=value or None,
                            )
                            for column_ordinal, value in enumerate(row)
                        ),
                    )
                )
            structural_observations.append(
                StructuralObservation.create(
                    structural_observation_id=observation_id,
                    source_inventory_item_id=inventory_item.source_inventory_item_id,
                    source_asset_id=source_asset_id,
                    source_observation_id=observation_id,
                    structure_kind=observation["structure_kind"],
                    columns=columns,
                    rows=tuple(rows),
                    header_relationships=(),
                    source_fingerprint=source_fingerprint,
                    parser_fingerprint=parser_fingerprint,
                )
            )
    structural_observations.sort(key=lambda item: item.structural_observation_id)
    version_manifest = VersionManifest.create(
        source_fingerprint=source_fingerprint,
        parser_fingerprint=parser_fingerprint,
        tokenizer_fingerprint=sha256_json(
            {"semantic_profile_fingerprint": semantic_profile_fingerprint}
        ),
        index_fingerprint=sha256_json(
            {
                "normalized_bundle_sha256": normalized_bundle_sha256,
                "source_inventory": inventory.to_persistence_dict(),
                "structural_observations": [
                    observation.to_persistence_dict() for observation in structural_observations
                ],
            }
        ),
        implementation_fingerprint=sha256_json(
            {
                "materializer": "fresh_uat_normalized_shard_v1",
                "scope_manifest_id": scope_manifest_id,
                "semantic_profile_fingerprint": semantic_profile_fingerprint,
            }
        ),
        parser_version="fresh_uat_normalized_v1",
        tokenizer_version="fresh_uat_structural_v1",
        index_version="fresh_uat_structural_v1",
        implementation_version="fresh_uat_attestation_v1",
        created_at=issued_at,
    )
    requirement = ClaimRequirement.create(
        query_id=stable_resource_contract_id(
            "query",
            "FreshUatStructuralScope",
            {"scope_manifest_id": scope_manifest_id, "shard_key": shard_key},
        ),
        kind="all_matching",
        target="structural_row",
        predicate="fresh_uat_structural_scope",
        parameters={
            "scope_kind": "internal_diagnostic_uat",
            "normalized_bundle_sha256": normalized_bundle_sha256,
        },
        required_scope=tuple(item.source_inventory_item_id for item in inventory.items),
        created_at=issued_at,
    )
    authorization = CoverageAuthorizationBinding(
        actor_context_id=actor_context_id,
        permission_revision=sha256_json(
            {
                "workspace_id": workspace_id,
                "owner_user_id": owner_user_id,
                "source_asset_id": source_asset_id,
                "permission_scope": normalized_scope,
            }
        ),
        grant_revision=sha256_json(
            {
                "source_inventory_id": inventory.source_inventory_id,
                "source_fingerprint": source_fingerprint,
            }
        ),
    )
    scope_policy = CoverageScopePolicyBinding.create(
        scope_policy_id=scope_policy_id,
        scope_policy_version=scope_policy_version,
        scope_policy_fingerprint=scope_policy_fingerprint,
    )
    verifier = CoverageScopeAuthorityVerifier.from_external_root(authority_verifier_root)
    authority = CoverageScopeAuthority.create(
        source_inventory=inventory,
        claim_requirement=requirement,
        authorization_binding=authorization,
        version_manifest=version_manifest,
        scope_policy=scope_policy,
        authorization_decisions=tuple(
            CoverageItemAuthorizationDecision.create(
                source_inventory_item=item,
                authorization_binding=authorization,
                decision_state="authorized",
            )
            for item in inventory.items
        ),
        relevance_decisions=tuple(
            CoverageItemRelevanceDecision.create(
                source_inventory_item=item,
                claim_requirement=requirement,
                scope_policy=scope_policy,
                decision_state="relevant",
            )
            for item in inventory.items
        ),
        authority_verifier=verifier,
    )
    observation_ids_by_item: dict[str, list[str]] = {}
    for observation in structural_observations:
        observation_ids_by_item.setdefault(observation.source_inventory_item_id, []).append(
            observation.structural_observation_id
        )
    partitions = tuple(
        CoverageObservationPartition(
            inventory_item_id=item.source_inventory_item_id,
            structural_observation_ids=tuple(
                sorted(observation_ids_by_item.get(item.source_inventory_item_id, ()))
            ),
        )
        for item in inventory.items
    )
    if any(not partition.structural_observation_ids for partition in partitions):
        raise ContractValidationError("fresh UAT normalized source coverage is incomplete")
    scope_partition = CoverageScopePartition.create(
        scope_authority=authority,
        observation_partitions=partitions,
    )
    proofs = tuple(
        CoverageProofRecord.create(
            source_inventory_id=inventory.source_inventory_id,
            claim_requirement_id=requirement.claim_requirement_id,
            version_manifest_id=version_manifest.version_manifest_id,
            inventory_item_id=partition.inventory_item_id,
            proof_kind="structural",
            structural_observation_ids=partition.structural_observation_ids,
        )
        for partition in partitions
    )
    ledger = CoverageLedger.create(
        query_id=requirement.query_id,
        claim_requirement_id=requirement.claim_requirement_id,
        source_inventory_id=inventory.source_inventory_id,
        relevant_inventory_item_ids=tuple(item.source_inventory_item_id for item in inventory.items),
        searched_structural_observation_ids=tuple(
            observation.structural_observation_id for observation in structural_observations
        ),
        authorization_binding=authorization,
        version_binding=CoverageVersionBinding.from_manifest(version_manifest),
        scope_partition=scope_partition,
        proof_records=proofs,
        complete_authorized_scope=True,
        display_pagination=DisplayPagination(page_size=1),
    )
    import_session_id = stable_resource_contract_id(
        "mailimport",
        "FreshUatMailImport",
        {"source_asset_id": source_asset_id, "shard_key": shard_key, "source": source_fingerprint},
    )
    import_session = MailImportSession(
        mail_import_session_id=import_session_id,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        source_asset_id=source_asset_id,
        archive_sha256=source_fingerprint,
        retention_policy="retain_indefinitely",
        raw_archive_retention_decision="retained_by_policy",
        created_at=issued_at,
        import_profile="fresh_internal_diagnostic_uat",
        status="succeeded",
    )
    archive_id = stable_resource_contract_id(
        "archive", "FreshUatArchive", {"session": import_session_id}
    )
    mailbox_id = stable_resource_contract_id(
        "mailbox", "FreshUatMailbox", {"session": import_session_id}
    )
    archive_occurrence = MailArchiveOccurrence(
        mail_archive_occurrence_id=stable_resource_contract_id(
            "mailarchiveocc", "FreshUatArchiveOccurrence", {"session": import_session_id}
        ),
        mail_import_session_id=import_session_id,
        source_asset_id=source_asset_id,
        archive_id=archive_id,
        mailbox_id=mailbox_id,
        archive_sha256=source_fingerprint,
        created_at=issued_at,
    )
    first_observation_id = structural_observations[0].source_observation_id
    folder_hash = sha256_json({"mailbox_id": mailbox_id, "shard_key": shard_key})
    email_message_id = stable_resource_contract_id(
        "email", "FreshUatMessage", {"session": import_session_id}
    )
    message_id = stable_resource_contract_id(
        "message", "FreshUatMessageIdentity", {"session": import_session_id}
    )
    message_occurrence_id = stable_resource_contract_id(
        "messageocc", "FreshUatMessageOccurrence", {"session": import_session_id}
    )
    message = EmailMessage(
        email_message_id=email_message_id,
        message_fingerprint=sha256_json(
            {"normalized_bundle_sha256": normalized_bundle_sha256, "shard_key": shard_key}
        ),
        message_id=message_id,
        archive_id=archive_id,
        mailbox_id=mailbox_id,
        source_observation_ids=[first_observation_id],
        body_evidence_state="not_present",
    )
    bundle = MailEvidenceBundle(
        mail_evidence_bundle_id=stable_resource_contract_id(
            "mailevidencebundle",
            "FreshUatMailEvidenceBundle",
            {
                "mail_import_session_id": import_session_id,
                "source_inventory_id": inventory.source_inventory_id,
                "version_manifest_id": version_manifest.version_manifest_id,
            },
        ),
        producer_type="fixture_parser",
        mail_import_session=import_session,
        archive_occurrences=[archive_occurrence],
        folder_occurrences=[
            MailFolderOccurrence(
                mail_folder_occurrence_id=stable_resource_contract_id(
                    "mailfolderocc", "FreshUatFolder", {"session": import_session_id}
                ),
                mail_archive_occurrence_id=archive_occurrence.mail_archive_occurrence_id,
                archive_id=archive_id,
                mailbox_id=mailbox_id,
                folder_path_hash=folder_hash,
                source_observation_id=first_observation_id,
            )
        ],
        messages=[message],
        message_occurrences=[
            EmailMessageOccurrence(
                email_message_occurrence_id=stable_resource_contract_id(
                    "emailmessageocc", "FreshUatMessageOccurrence", {"session": import_session_id}
                ),
                email_message_id=email_message_id,
                mail_archive_occurrence_id=archive_occurrence.mail_archive_occurrence_id,
                message_occurrence_id=message_occurrence_id,
                message_id=message_id,
                archive_id=archive_id,
                mailbox_id=mailbox_id,
                folder_path_hash=folder_hash,
                source_observation_id=first_observation_id,
            )
        ],
        body_segments=[],
        attachments=[],
        attachment_occurrences=[],
        quoted_message_candidates=[],
        embedded_message_relations=[],
        mail_parse_run=MailParseRun(
            mail_parse_run_id=stable_resource_contract_id(
                "mailparserun", "FreshUatParseRun", {"session": import_session_id}
            ),
            mail_import_session_id=import_session_id,
            extractor_run_id=stable_resource_contract_id(
                "extractor", "FreshUatNormalizedMaterializer", {"shard_key": shard_key}
            ),
            parser_name="fresh_uat_normalized_materializer",
            parser_version="1",
            input_hash=source_fingerprint,
            config_hash=parser_fingerprint,
            status="succeeded",
            started_at=issued_at,
            completed_at=issued_at,
        ),
        created_at=issued_at,
        source_inventory=[inventory],
        structural_observations=structural_observations,
        claim_requirements=[requirement],
        coverage_ledgers=[ledger],
        version_manifests=[version_manifest],
        _expected_scope_authorities={
            f"{requirement.claim_requirement_id}:{inventory.source_inventory_id}": authority
        },
    )
    bundle.to_persistence_dict()
    return bundle, verifier


def publish_fresh_uat_attestation(
    *,
    output_dir: str | Path,
    normalized_shards: Sequence[Mapping[str, Any]],
    immutable_source_hashes: Mapping[str, str],
    source_asset_id: str,
    source_fingerprint: str,
    workspace_id: str,
    owner_user_id: str,
    permission_scope: Mapping[str, Any],
    actor_context_id: str,
    issued_at: str,
    known_as_of: str,
    semantic_profile_fingerprint: str,
    scope_manifest_id: str,
    scope_policy_id: str,
    scope_policy_version: str,
    scope_policy_fingerprint: str,
    authority_verifier_root: str | bytes,
) -> FreshUatAttestationReceipt:
    """Issue current diagnostic-UAT evidence only from explicit normalized facts."""

    del (
        output_dir,
        source_asset_id,
        source_fingerprint,
        workspace_id,
        owner_user_id,
        permission_scope,
        actor_context_id,
        issued_at,
        known_as_of,
        semantic_profile_fingerprint,
        scope_manifest_id,
        scope_policy_id,
        scope_policy_version,
        scope_policy_fingerprint,
        authority_verifier_root,
    )
    _validate_fresh_uat_attestation_input(
        normalized_shards=normalized_shards,
        immutable_source_hashes=immutable_source_hashes,
    )
    raise ContractValidationError("fresh UAT materialization is unavailable")


@dataclass(frozen=True)
class DiagnosticExistingExportVerification:
    """Path-free proof that one existing export was fully traversed.

    This record proves the exported files and selected message-file accounting
    used by the diagnostic bridge. It deliberately does not claim that the raw
    PST was replayed in this process, so the independent query oracle remains
    mandatory.
    """

    verification_fingerprint: str
    scope_manifest_id: str
    source_inventory_id: str
    operator_scope_binding_fingerprint: str
    raw_byte_export_traversal_fingerprint: str
    export_file_count: int
    export_message_file_count: int
    parsed_export_message_count: int
    nonparsed_export_message_count: int
    matched_message_occurrence_count: int
    source_archive_replay_unproven: bool = True
    requires_query_oracle: bool = True
    historical_compatibility_checkpoint_fingerprint: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("scope_manifest_id", "source_inventory_id"):
            _validate_task_record_id(getattr(self, field_name), field_name)
        for field_name in (
            "verification_fingerprint",
            "operator_scope_binding_fingerprint",
            "raw_byte_export_traversal_fingerprint",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise ContractValidationError("diagnostic existing-export verification is invalid")
        compatibility_fingerprint = self.historical_compatibility_checkpoint_fingerprint
        if compatibility_fingerprint is not None and (
            not isinstance(compatibility_fingerprint, str)
            or not _SHA256.fullmatch(compatibility_fingerprint)
        ):
            raise ContractValidationError("diagnostic existing-export verification is invalid")
        for field_name in (
            "export_file_count",
            "export_message_file_count",
            "parsed_export_message_count",
            "nonparsed_export_message_count",
            "matched_message_occurrence_count",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ContractValidationError("diagnostic existing-export verification is invalid")
        ordinary_selection = compatibility_fingerprint is None
        if (
            self.export_file_count < self.export_message_file_count
            or self.parsed_export_message_count + self.nonparsed_export_message_count
            != self.export_message_file_count
            or (
                ordinary_selection
                and (
                    self.nonparsed_export_message_count != 0
                    or self.parsed_export_message_count != self.export_message_file_count
                    or self.matched_message_occurrence_count != self.parsed_export_message_count
                )
            )
            or (not ordinary_selection and self.parsed_export_message_count < 1)
            or self.source_archive_replay_unproven is not True
            or self.requires_query_oracle is not True
            or self.verification_fingerprint != sha256_json(self._identity_payload())
        ):
            raise ContractValidationError("diagnostic existing-export verification is invalid")

    @classmethod
    def create(
        cls,
        *,
        scope_manifest_id: str,
        source_inventory_id: str,
        operator_scope_binding_fingerprint: str,
        raw_byte_export_traversal_fingerprint: str,
        export_file_count: int,
        export_message_file_count: int,
        parsed_export_message_count: int,
        nonparsed_export_message_count: int,
        matched_message_occurrence_count: int,
        historical_compatibility_checkpoint_fingerprint: str | None = None,
    ) -> "DiagnosticExistingExportVerification":
        values = {
            "scope_manifest_id": scope_manifest_id,
            "source_inventory_id": source_inventory_id,
            "operator_scope_binding_fingerprint": operator_scope_binding_fingerprint,
            "raw_byte_export_traversal_fingerprint": raw_byte_export_traversal_fingerprint,
            "export_file_count": export_file_count,
            "export_message_file_count": export_message_file_count,
            "parsed_export_message_count": parsed_export_message_count,
            "nonparsed_export_message_count": nonparsed_export_message_count,
            "matched_message_occurrence_count": matched_message_occurrence_count,
            "source_archive_replay_unproven": True,
            "requires_query_oracle": True,
            "historical_compatibility_checkpoint_fingerprint": (
                historical_compatibility_checkpoint_fingerprint
            ),
        }
        return cls(
            verification_fingerprint=sha256_json(cls._identity_payload_static(values)),
            **values,
        )

    def _identity_payload(self) -> dict[str, Any]:
        return self._identity_payload_static(
            {
                "scope_manifest_id": self.scope_manifest_id,
                "source_inventory_id": self.source_inventory_id,
                "operator_scope_binding_fingerprint": (self.operator_scope_binding_fingerprint),
                "raw_byte_export_traversal_fingerprint": (
                    self.raw_byte_export_traversal_fingerprint
                ),
                "export_file_count": self.export_file_count,
                "export_message_file_count": self.export_message_file_count,
                "parsed_export_message_count": self.parsed_export_message_count,
                "nonparsed_export_message_count": self.nonparsed_export_message_count,
                "matched_message_occurrence_count": (self.matched_message_occurrence_count),
                "source_archive_replay_unproven": (self.source_archive_replay_unproven),
                "requires_query_oracle": self.requires_query_oracle,
                "historical_compatibility_checkpoint_fingerprint": (
                    self.historical_compatibility_checkpoint_fingerprint
                ),
            }
        )

    @staticmethod
    def _identity_payload_static(values: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "scope_manifest_id": values["scope_manifest_id"],
            "source_inventory_id": values["source_inventory_id"],
            "operator_scope_binding_fingerprint": values["operator_scope_binding_fingerprint"],
            "raw_byte_export_traversal_fingerprint": values[
                "raw_byte_export_traversal_fingerprint"
            ],
            "export_file_count": values["export_file_count"],
            "export_message_file_count": values["export_message_file_count"],
            "parsed_export_message_count": values["parsed_export_message_count"],
            "nonparsed_export_message_count": values["nonparsed_export_message_count"],
            "matched_message_occurrence_count": values["matched_message_occurrence_count"],
            "source_archive_replay_unproven": values["source_archive_replay_unproven"],
            "requires_query_oracle": values["requires_query_oracle"],
            "historical_compatibility_checkpoint_fingerprint": values[
                "historical_compatibility_checkpoint_fingerprint"
            ],
        }

    def authority_binding(self) -> dict[str, Any]:
        """Return the exact safe fields committed by each shard authority."""

        payload = {
            "verification_fingerprint": self.verification_fingerprint,
            **self._identity_payload(),
        }
        if self.historical_compatibility_checkpoint_fingerprint is None:
            payload.pop("historical_compatibility_checkpoint_fingerprint")
        return payload

    def to_private_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": _DIAGNOSTIC_EXISTING_EXPORT_VERIFICATION_ARTIFACT_TYPE,
            "verification_fingerprint": self.verification_fingerprint,
            **self._identity_payload(),
        }

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "scope_kind": DIAGNOSTIC_EXISTING_EXPORT_SCOPE_KIND,
            "verification_fingerprint": self.verification_fingerprint,
            **self._identity_payload(),
        }

    @classmethod
    def from_private_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "DiagnosticExistingExportVerification":
        required = {
            "artifact_type",
            "verification_fingerprint",
            "scope_manifest_id",
            "source_inventory_id",
            "operator_scope_binding_fingerprint",
            "raw_byte_export_traversal_fingerprint",
            "export_file_count",
            "export_message_file_count",
            "parsed_export_message_count",
            "nonparsed_export_message_count",
            "matched_message_occurrence_count",
            "source_archive_replay_unproven",
            "requires_query_oracle",
            "historical_compatibility_checkpoint_fingerprint",
        }
        if (
            not isinstance(value, Mapping)
            or set(value) != required
            or value.get("artifact_type") != _DIAGNOSTIC_EXISTING_EXPORT_VERIFICATION_ARTIFACT_TYPE
        ):
            raise ContractValidationError("diagnostic existing-export verification is invalid")
        return cls(
            verification_fingerprint=value["verification_fingerprint"],
            scope_manifest_id=value["scope_manifest_id"],
            source_inventory_id=value["source_inventory_id"],
            operator_scope_binding_fingerprint=value["operator_scope_binding_fingerprint"],
            raw_byte_export_traversal_fingerprint=value["raw_byte_export_traversal_fingerprint"],
            export_file_count=value["export_file_count"],
            export_message_file_count=value["export_message_file_count"],
            parsed_export_message_count=value["parsed_export_message_count"],
            nonparsed_export_message_count=value["nonparsed_export_message_count"],
            matched_message_occurrence_count=value["matched_message_occurrence_count"],
            source_archive_replay_unproven=value["source_archive_replay_unproven"],
            requires_query_oracle=value["requires_query_oracle"],
            historical_compatibility_checkpoint_fingerprint=value[
                "historical_compatibility_checkpoint_fingerprint"
            ],
        )


def diagnostic_structural_baseline_parameters(
    verification: DiagnosticExistingExportVerification,
) -> dict[str, Any]:
    if not isinstance(verification, DiagnosticExistingExportVerification):
        raise ContractValidationError("diagnostic structural export verification is invalid")
    return {
        "scope_kind": DIAGNOSTIC_STRUCTURAL_BASELINE_SCOPE_KIND,
        "existing_export_verification": verification.authority_binding(),
    }


def diagnostic_structural_scope_policy_fingerprint(
    verification: DiagnosticExistingExportVerification,
) -> str:
    return sha256_json(
        {
            "scope_policy_id": DIAGNOSTIC_STRUCTURAL_SCOPE_POLICY_ID,
            "scope_policy_version": DIAGNOSTIC_STRUCTURAL_SCOPE_POLICY_VERSION,
            "mode": "complete_authorized_structural_baseline",
            "existing_export_verification": verification.authority_binding(),
        }
    )


def diagnostic_structural_implementation_fingerprint(
    *,
    producer_type: str,
    parser_name: str,
    parser_version: str,
    semantic_profile_fingerprint: str,
    verification: DiagnosticExistingExportVerification,
) -> str:
    for field_name, value in (
        ("producer_type", producer_type),
        ("parser_name", parser_name),
        ("parser_version", parser_version),
    ):
        if not isinstance(value, str) or not value:
            raise ContractValidationError(f"diagnostic structural {field_name} is invalid")
    if not isinstance(semantic_profile_fingerprint, str) or not _SHA256.fullmatch(
        semantic_profile_fingerprint
    ):
        raise ContractValidationError(
            "diagnostic structural semantic profile fingerprint is invalid"
        )
    if not isinstance(verification, DiagnosticExistingExportVerification):
        raise ContractValidationError("diagnostic structural export verification is invalid")
    return sha256_json(
        {
            "producer_type": producer_type,
            "parser_name": parser_name,
            "parser_version": parser_version,
            "semantic_profile_fingerprint": semantic_profile_fingerprint,
            "semantic_materialization": DIAGNOSTIC_STRUCTURAL_BASELINE_SCOPE_KIND,
            "existing_export_verification": verification.authority_binding(),
        }
    )


@dataclass(frozen=True)
class DiagnosticStructuralShardRecord:
    """Private, path-free accounting for one deterministic structural shard."""

    ordinal: int
    mail_evidence_bundle_id: str
    bundle_fingerprint: str
    existing_export_verification_fingerprint: str
    selected_path_fingerprint: str
    selector_coverage_fingerprint: str
    selected_message_count: int
    body_segment_count: int
    structural_observation_count: int
    selected_top_level_message_count: int
    embedded_message_occurrence_count: int
    historical_compatibility_checkpoint_fingerprint: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.ordinal, int) or isinstance(self.ordinal, bool) or self.ordinal < 0:
            raise ContractValidationError("diagnostic structural shard ordinal is invalid")
        _validate_task_record_id(
            self.mail_evidence_bundle_id,
            "mail_evidence_bundle_id",
        )
        for field_name in (
            "bundle_fingerprint",
            "existing_export_verification_fingerprint",
            "selected_path_fingerprint",
            "selector_coverage_fingerprint",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise ContractValidationError(
                    f"diagnostic structural shard {field_name} is invalid"
                )
        compatibility_fingerprint = self.historical_compatibility_checkpoint_fingerprint
        if compatibility_fingerprint is not None and (
            not isinstance(compatibility_fingerprint, str)
            or not _SHA256.fullmatch(compatibility_fingerprint)
        ):
            raise ContractValidationError(
                "diagnostic structural shard compatibility checkpoint is invalid"
            )
        for field_name in (
            "selected_message_count",
            "body_segment_count",
            "structural_observation_count",
            "selected_top_level_message_count",
            "embedded_message_occurrence_count",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ContractValidationError(
                    f"diagnostic structural shard {field_name} is invalid"
                )
        if self.selected_message_count < 1:
            raise ContractValidationError(
                "diagnostic structural shard selected message count is invalid"
            )
        if (
            self.selected_top_level_message_count < 1
            or self.selected_message_count
            != self.selected_top_level_message_count + self.embedded_message_occurrence_count
        ):
            raise ContractValidationError(
                "diagnostic structural shard top-level message accounting is invalid"
            )

    def to_private_dict(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "mail_evidence_bundle_id": self.mail_evidence_bundle_id,
            "bundle_fingerprint": self.bundle_fingerprint,
            "existing_export_verification_fingerprint": (
                self.existing_export_verification_fingerprint
            ),
            "selected_path_fingerprint": self.selected_path_fingerprint,
            "selector_coverage_fingerprint": self.selector_coverage_fingerprint,
            "selected_message_count": self.selected_message_count,
            "body_segment_count": self.body_segment_count,
            "structural_observation_count": self.structural_observation_count,
            "selected_top_level_message_count": self.selected_top_level_message_count,
            "embedded_message_occurrence_count": self.embedded_message_occurrence_count,
            "historical_compatibility_checkpoint_fingerprint": (
                self.historical_compatibility_checkpoint_fingerprint
            ),
        }

    @classmethod
    def from_private_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "DiagnosticStructuralShardRecord":
        required = {
            "ordinal",
            "mail_evidence_bundle_id",
            "bundle_fingerprint",
            "existing_export_verification_fingerprint",
            "selected_path_fingerprint",
            "selector_coverage_fingerprint",
            "selected_message_count",
            "body_segment_count",
            "structural_observation_count",
            "selected_top_level_message_count",
            "embedded_message_occurrence_count",
            "historical_compatibility_checkpoint_fingerprint",
        }
        if not isinstance(value, Mapping) or set(value) != required:
            raise ContractValidationError("diagnostic structural shard record is invalid")
        return cls(
            ordinal=value["ordinal"],
            mail_evidence_bundle_id=value["mail_evidence_bundle_id"],
            bundle_fingerprint=value["bundle_fingerprint"],
            existing_export_verification_fingerprint=value[
                "existing_export_verification_fingerprint"
            ],
            selected_path_fingerprint=value["selected_path_fingerprint"],
            selector_coverage_fingerprint=value["selector_coverage_fingerprint"],
            selected_message_count=value["selected_message_count"],
            body_segment_count=value["body_segment_count"],
            structural_observation_count=value["structural_observation_count"],
            selected_top_level_message_count=value["selected_top_level_message_count"],
            embedded_message_occurrence_count=value["embedded_message_occurrence_count"],
            historical_compatibility_checkpoint_fingerprint=value[
                "historical_compatibility_checkpoint_fingerprint"
            ],
        )


@dataclass(frozen=True)
class DiagnosticStructuralBodySegmentAccounting:
    """Closed body-segment split recomputed from one aggregate's bundles."""

    total_body_segment_count: int
    message_body_segment_count: int
    attachment_text_segment_count: int

    def __post_init__(self) -> None:
        for field_name in (
            "total_body_segment_count",
            "message_body_segment_count",
            "attachment_text_segment_count",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ContractValidationError(
                    "diagnostic structural aggregate body segment accounting is invalid"
                )
        if self.total_body_segment_count != (
            self.message_body_segment_count + self.attachment_text_segment_count
        ):
            raise ContractValidationError(
                "diagnostic structural aggregate body segment accounting is invalid"
            )


@dataclass(frozen=True)
class DiagnosticStructuralAggregateManifest:
    """Complete private publication authority for deterministic shard iteration."""

    aggregate_manifest_id: str
    scope_manifest_id: str
    source_asset_id: str
    source_fingerprint: str
    workspace_id: str
    owner_user_id: str
    semantic_profile_fingerprint: str
    existing_export_verification: DiagnosticExistingExportVerification
    shard_batch_size: int
    selected_path_set_fingerprint: str
    selector_coverage_fingerprint: str
    expected_message_count: int
    expected_body_segment_count: int
    aggregate_contract_revision: str
    total_structural_observation_count: int
    shards: tuple[DiagnosticStructuralShardRecord, ...]
    historical_compatibility_checkpoint_fingerprint: str | None = None
    selected_top_level_message_count: int | None = None
    materialized_message_occurrence_count: int | None = None
    materialized_body_segment_count: int | None = None
    materialized_message_body_segment_count: int | None = None
    materialized_attachment_text_segment_count: int | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "aggregate_manifest_id",
            "scope_manifest_id",
            "source_asset_id",
            "workspace_id",
            "owner_user_id",
        ):
            _validate_task_record_id(getattr(self, field_name), field_name)
        for field_name in (
            "source_fingerprint",
            "semantic_profile_fingerprint",
            "selected_path_set_fingerprint",
            "selector_coverage_fingerprint",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise ContractValidationError(
                    f"diagnostic structural aggregate {field_name} is invalid"
                )
        compatibility_fingerprint = self.historical_compatibility_checkpoint_fingerprint
        if compatibility_fingerprint is not None and (
            not isinstance(compatibility_fingerprint, str)
            or not _SHA256.fullmatch(compatibility_fingerprint)
        ):
            raise ContractValidationError(
                "diagnostic structural aggregate compatibility checkpoint is invalid"
            )
        shards = tuple(self.shards)
        if (
            not shards
            or any(not isinstance(item, DiagnosticStructuralShardRecord) for item in shards)
            or tuple(item.ordinal for item in shards) != tuple(range(len(shards)))
        ):
            raise ContractValidationError(
                "diagnostic structural aggregate shards are not canonical"
            )
        if not isinstance(
            self.existing_export_verification,
            DiagnosticExistingExportVerification,
        ):
            raise ContractValidationError(
                "diagnostic structural aggregate export verification is invalid"
            )
        verification = self.existing_export_verification
        if (
            verification.scope_manifest_id != self.scope_manifest_id
            or verification.operator_scope_binding_fingerprint
            != sha256_json(
                {
                    "scope_manifest_id": self.scope_manifest_id,
                    "source_asset_id": self.source_asset_id,
                    "source_fingerprint": self.source_fingerprint,
                }
            )
            or verification.historical_compatibility_checkpoint_fingerprint
            != compatibility_fingerprint
            or verification.matched_message_occurrence_count != self.expected_message_count
            or (
                compatibility_fingerprint is None
                and (
                    verification.export_message_file_count != self.expected_message_count
                    or verification.parsed_export_message_count != self.expected_message_count
                )
            )
            or any(
                item.existing_export_verification_fingerprint
                != verification.verification_fingerprint
                or item.historical_compatibility_checkpoint_fingerprint != compatibility_fingerprint
                for item in shards
            )
        ):
            raise ContractValidationError(
                "diagnostic structural aggregate export verification is inconsistent"
            )
        if (
            not isinstance(self.shard_batch_size, int)
            or isinstance(self.shard_batch_size, bool)
            or self.shard_batch_size < 1
        ):
            raise ContractValidationError(
                "diagnostic structural aggregate shard batch size is invalid"
            )
        if self.aggregate_contract_revision != _DIAGNOSTIC_STRUCTURAL_AGGREGATE_CONTRACT_REVISION:
            raise ContractValidationError(
                "diagnostic structural aggregate contract revision is invalid"
            )
        for field_name in (
            "expected_message_count",
            "expected_body_segment_count",
            "total_structural_observation_count",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ContractValidationError(
                    f"diagnostic structural aggregate {field_name} is invalid"
                )
        selected_top_level_message_count = self.selected_top_level_message_count
        materialized_message_occurrence_count = self.materialized_message_occurrence_count
        materialized_body_segment_count = self.materialized_body_segment_count
        materialized_message_body_segment_count = self.materialized_message_body_segment_count
        materialized_attachment_text_segment_count = self.materialized_attachment_text_segment_count
        for field_name, value in (
            ("selected_top_level_message_count", selected_top_level_message_count),
            ("materialized_message_occurrence_count", materialized_message_occurrence_count),
            ("materialized_body_segment_count", materialized_body_segment_count),
            (
                "materialized_message_body_segment_count",
                materialized_message_body_segment_count,
            ),
            (
                "materialized_attachment_text_segment_count",
                materialized_attachment_text_segment_count,
            ),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ContractValidationError(
                    f"diagnostic structural aggregate {field_name} is invalid"
                )
        if (
            sum(item.selected_top_level_message_count for item in shards)
            != selected_top_level_message_count
            or selected_top_level_message_count != verification.parsed_export_message_count
        ):
            raise ContractValidationError(
                "diagnostic structural aggregate top-level message accounting is incomplete"
            )
        if (
            sum(item.selected_message_count for item in shards)
            != materialized_message_occurrence_count
            or sum(item.body_segment_count for item in shards) != materialized_body_segment_count
        ):
            raise ContractValidationError(
                "diagnostic structural aggregate current materialization accounting is incomplete"
            )
        if materialized_body_segment_count != (
            materialized_message_body_segment_count + materialized_attachment_text_segment_count
        ):
            raise ContractValidationError(
                "diagnostic structural aggregate body segment accounting is incomplete"
            )
        if compatibility_fingerprint is None and (
            selected_top_level_message_count != self.expected_message_count
            or materialized_message_occurrence_count != self.expected_message_count
            or materialized_message_body_segment_count != self.expected_body_segment_count
        ):
            raise ContractValidationError(
                "diagnostic structural aggregate ordinary accounting is incomplete"
            )
        if (
            sum(item.structural_observation_count for item in shards)
            != self.total_structural_observation_count
        ):
            raise ContractValidationError(
                "diagnostic structural aggregate observation accounting is incomplete"
            )
        expected_id = stable_resource_contract_id(
            "diagnosticaggregate",
            "DiagnosticStructuralAggregateManifest",
            self._identity_payload(shards),
        )
        if self.aggregate_manifest_id != expected_id:
            raise ContractValidationError("diagnostic structural aggregate identity is invalid")
        object.__setattr__(self, "shards", shards)

    @classmethod
    def create(
        cls,
        *,
        scope_manifest_id: str,
        source_asset_id: str,
        source_fingerprint: str,
        workspace_id: str,
        owner_user_id: str,
        semantic_profile_fingerprint: str,
        existing_export_verification: DiagnosticExistingExportVerification,
        shard_batch_size: int,
        selected_path_set_fingerprint: str,
        selector_coverage_fingerprint: str,
        expected_message_count: int,
        expected_body_segment_count: int,
        total_structural_observation_count: int,
        shards: tuple[DiagnosticStructuralShardRecord, ...],
        aggregate_contract_revision: str = _DIAGNOSTIC_STRUCTURAL_AGGREGATE_CONTRACT_REVISION,
        historical_compatibility_checkpoint_fingerprint: str | None = None,
        selected_top_level_message_count: int | None = None,
        materialized_message_occurrence_count: int | None = None,
        materialized_body_segment_count: int | None = None,
        materialized_message_body_segment_count: int | None = None,
        materialized_attachment_text_segment_count: int | None = None,
    ) -> "DiagnosticStructuralAggregateManifest":
        values = {
            "scope_manifest_id": scope_manifest_id,
            "source_asset_id": source_asset_id,
            "source_fingerprint": source_fingerprint,
            "workspace_id": workspace_id,
            "owner_user_id": owner_user_id,
            "semantic_profile_fingerprint": semantic_profile_fingerprint,
            "existing_export_verification": existing_export_verification,
            "shard_batch_size": shard_batch_size,
            "selected_path_set_fingerprint": selected_path_set_fingerprint,
            "selector_coverage_fingerprint": selector_coverage_fingerprint,
            "expected_message_count": expected_message_count,
            "expected_body_segment_count": expected_body_segment_count,
            "aggregate_contract_revision": aggregate_contract_revision,
            "total_structural_observation_count": total_structural_observation_count,
            "shards": tuple(shards),
            "historical_compatibility_checkpoint_fingerprint": (
                historical_compatibility_checkpoint_fingerprint
            ),
            "selected_top_level_message_count": (
                selected_top_level_message_count
                if selected_top_level_message_count is not None
                else expected_message_count
            ),
            "materialized_message_occurrence_count": (
                materialized_message_occurrence_count
                if materialized_message_occurrence_count is not None
                else expected_message_count
            ),
            "materialized_body_segment_count": (
                materialized_body_segment_count
                if materialized_body_segment_count is not None
                else expected_body_segment_count
            ),
            "materialized_message_body_segment_count": (
                materialized_message_body_segment_count
                if materialized_message_body_segment_count is not None
                else expected_body_segment_count
            ),
            "materialized_attachment_text_segment_count": (
                materialized_attachment_text_segment_count
                if materialized_attachment_text_segment_count is not None
                else 0
            ),
        }
        aggregate_manifest_id = stable_resource_contract_id(
            "diagnosticaggregate",
            "DiagnosticStructuralAggregateManifest",
            cls._identity_payload_static(values),
        )
        return cls(aggregate_manifest_id=aggregate_manifest_id, **values)

    def _identity_payload(
        self,
        shards: tuple[DiagnosticStructuralShardRecord, ...],
    ) -> dict[str, Any]:
        return self._identity_payload_static(
            {
                "scope_manifest_id": self.scope_manifest_id,
                "source_asset_id": self.source_asset_id,
                "source_fingerprint": self.source_fingerprint,
                "workspace_id": self.workspace_id,
                "owner_user_id": self.owner_user_id,
                "semantic_profile_fingerprint": self.semantic_profile_fingerprint,
                "existing_export_verification": (self.existing_export_verification),
                "shard_batch_size": self.shard_batch_size,
                "selected_path_set_fingerprint": self.selected_path_set_fingerprint,
                "selector_coverage_fingerprint": self.selector_coverage_fingerprint,
                "expected_message_count": self.expected_message_count,
                "expected_body_segment_count": self.expected_body_segment_count,
                "aggregate_contract_revision": self.aggregate_contract_revision,
                "total_structural_observation_count": (self.total_structural_observation_count),
                "shards": shards,
                "historical_compatibility_checkpoint_fingerprint": (
                    self.historical_compatibility_checkpoint_fingerprint
                ),
                "selected_top_level_message_count": self.selected_top_level_message_count,
                "materialized_message_occurrence_count": (
                    self.materialized_message_occurrence_count
                ),
                "materialized_body_segment_count": self.materialized_body_segment_count,
                "materialized_message_body_segment_count": (
                    self.materialized_message_body_segment_count
                ),
                "materialized_attachment_text_segment_count": (
                    self.materialized_attachment_text_segment_count
                ),
            }
        )

    @staticmethod
    def _identity_payload_static(values: Mapping[str, Any]) -> dict[str, Any]:
        shards = tuple(values["shards"])
        return {
            "scope_manifest_id": values["scope_manifest_id"],
            "source_asset_id": values["source_asset_id"],
            "source_fingerprint": values["source_fingerprint"],
            "workspace_id": values["workspace_id"],
            "owner_user_id": values["owner_user_id"],
            "semantic_profile_fingerprint": values["semantic_profile_fingerprint"],
            "existing_export_verification": values[
                "existing_export_verification"
            ].to_private_dict(),
            "shard_batch_size": values["shard_batch_size"],
            "selected_path_set_fingerprint": values["selected_path_set_fingerprint"],
            "selector_coverage_fingerprint": values["selector_coverage_fingerprint"],
            "expected_message_count": values["expected_message_count"],
            "expected_body_segment_count": values["expected_body_segment_count"],
            "aggregate_contract_revision": values["aggregate_contract_revision"],
            "total_structural_observation_count": values["total_structural_observation_count"],
            "shards": [item.to_private_dict() for item in shards],
            "historical_compatibility_checkpoint_fingerprint": values[
                "historical_compatibility_checkpoint_fingerprint"
            ],
            "selected_top_level_message_count": values["selected_top_level_message_count"],
            "materialized_message_occurrence_count": values[
                "materialized_message_occurrence_count"
            ],
            "materialized_body_segment_count": values["materialized_body_segment_count"],
            "materialized_message_body_segment_count": values[
                "materialized_message_body_segment_count"
            ],
            "materialized_attachment_text_segment_count": values[
                "materialized_attachment_text_segment_count"
            ],
        }

    def to_private_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": _DIAGNOSTIC_STRUCTURAL_AGGREGATE_ARTIFACT_TYPE,
            "aggregate_manifest_id": self.aggregate_manifest_id,
            **self._identity_payload(self.shards),
        }

    @classmethod
    def from_private_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "DiagnosticStructuralAggregateManifest":
        required = {
            "artifact_type",
            "aggregate_manifest_id",
            "scope_manifest_id",
            "source_asset_id",
            "source_fingerprint",
            "workspace_id",
            "owner_user_id",
            "semantic_profile_fingerprint",
            "existing_export_verification",
            "shard_batch_size",
            "selected_path_set_fingerprint",
            "selector_coverage_fingerprint",
            "expected_message_count",
            "expected_body_segment_count",
            "aggregate_contract_revision",
            "total_structural_observation_count",
            "shards",
            "historical_compatibility_checkpoint_fingerprint",
            "selected_top_level_message_count",
            "materialized_message_occurrence_count",
            "materialized_body_segment_count",
            "materialized_message_body_segment_count",
            "materialized_attachment_text_segment_count",
        }
        if (
            not isinstance(value, Mapping)
            or set(value) != required
            or value.get("artifact_type") != _DIAGNOSTIC_STRUCTURAL_AGGREGATE_ARTIFACT_TYPE
            or not isinstance(value.get("shards"), list)
        ):
            raise ContractValidationError("diagnostic structural aggregate manifest is invalid")
        return cls(
            aggregate_manifest_id=value["aggregate_manifest_id"],
            scope_manifest_id=value["scope_manifest_id"],
            source_asset_id=value["source_asset_id"],
            source_fingerprint=value["source_fingerprint"],
            workspace_id=value["workspace_id"],
            owner_user_id=value["owner_user_id"],
            semantic_profile_fingerprint=value["semantic_profile_fingerprint"],
            existing_export_verification=(
                DiagnosticExistingExportVerification.from_private_dict(
                    value["existing_export_verification"]
                )
            ),
            shard_batch_size=value["shard_batch_size"],
            selected_path_set_fingerprint=value["selected_path_set_fingerprint"],
            selector_coverage_fingerprint=value["selector_coverage_fingerprint"],
            expected_message_count=value["expected_message_count"],
            expected_body_segment_count=value["expected_body_segment_count"],
            aggregate_contract_revision=value["aggregate_contract_revision"],
            total_structural_observation_count=value["total_structural_observation_count"],
            shards=tuple(
                DiagnosticStructuralShardRecord.from_private_dict(item) for item in value["shards"]
            ),
            historical_compatibility_checkpoint_fingerprint=value[
                "historical_compatibility_checkpoint_fingerprint"
            ],
            selected_top_level_message_count=value["selected_top_level_message_count"],
            materialized_message_occurrence_count=value["materialized_message_occurrence_count"],
            materialized_body_segment_count=value["materialized_body_segment_count"],
            materialized_message_body_segment_count=value[
                "materialized_message_body_segment_count"
            ],
            materialized_attachment_text_segment_count=value[
                "materialized_attachment_text_segment_count"
            ],
        )


@dataclass(frozen=True)
class MailEvidenceTaskComponentReference:
    ordinal: int
    mail_import_session_id: str
    mail_evidence_bundle_id: str
    source_inventory_id: str
    version_manifest_id: str
    scope_authority_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.ordinal, int) or isinstance(self.ordinal, bool) or self.ordinal < 0:
            raise ContractValidationError("task component ordinal is invalid")
        for field_name in (
            "mail_import_session_id",
            "mail_evidence_bundle_id",
            "source_inventory_id",
            "version_manifest_id",
            "scope_authority_id",
        ):
            _validate_task_record_id(getattr(self, field_name), field_name)

    def to_persistence_dict(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "mail_import_session_id": self.mail_import_session_id,
            "mail_evidence_bundle_id": self.mail_evidence_bundle_id,
            "source_inventory_id": self.source_inventory_id,
            "version_manifest_id": self.version_manifest_id,
            "scope_authority_id": self.scope_authority_id,
        }

    @classmethod
    def from_persistence_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "MailEvidenceTaskComponentReference":
        if not isinstance(value, Mapping):
            raise ContractValidationError("task component reference must be an object")
        required = {
            "ordinal",
            "mail_import_session_id",
            "mail_evidence_bundle_id",
            "source_inventory_id",
            "version_manifest_id",
            "scope_authority_id",
        }
        if set(value) != required:
            raise ContractValidationError("task component reference fields are invalid")
        return cls(
            ordinal=value["ordinal"],
            mail_import_session_id=value["mail_import_session_id"],
            mail_evidence_bundle_id=value["mail_evidence_bundle_id"],
            source_inventory_id=value["source_inventory_id"],
            version_manifest_id=value["version_manifest_id"],
            scope_authority_id=value["scope_authority_id"],
        )


@dataclass(frozen=True)
class MailEvidenceTaskQueryRecord:
    """Private durable owner for one canonical aggregate query outcome.

    The record persists the existing ledger and AnswerClaim contracts with the
    ordered real component bindings that validated them. It is independent of
    any single ``MailEvidenceBundle`` and does not create a merged inventory or
    a second public claim schema.
    """

    task_query_id: str
    workspace_id: str
    owner_user_id: str
    query_hash: str
    query_result: MailEvidenceQueryResult
    claim_requirement: ClaimRequirement
    coverage_ledger: CoverageLedger
    answer_claim: AnswerClaim
    component_references: tuple[MailEvidenceTaskComponentReference, ...]
    source_inventories: tuple[SourceInventory, ...]
    version_manifests: tuple[VersionManifest, ...]
    scope_authorities: tuple[CoverageScopeAuthority, ...]
    authorization_bindings: tuple[CoverageAuthorizationBinding, ...]

    def __post_init__(self) -> None:
        for field_name in ("task_query_id", "workspace_id", "owner_user_id"):
            _validate_task_record_id(getattr(self, field_name), field_name)
        if not isinstance(self.query_hash, str) or not _SHA256.fullmatch(self.query_hash):
            raise ContractValidationError("task query hash is invalid")
        if not isinstance(self.query_result, MailEvidenceQueryResult):
            raise ContractValidationError("task query result must be typed")
        if self.query_result.query_hash != self.query_hash:
            raise ContractValidationError("task query result hash does not match")
        if not isinstance(self.claim_requirement, ClaimRequirement):
            raise ContractValidationError("task query claim requirement must be typed")
        if not isinstance(self.coverage_ledger, CoverageLedger):
            raise ContractValidationError("task query coverage ledger must be typed")
        if not self.coverage_ledger.is_aggregate:
            raise ContractValidationError("task query persistence requires aggregate coverage")
        if not isinstance(self.answer_claim, AnswerClaim):
            raise ContractValidationError("task query answer claim must be typed")
        references = tuple(self.component_references)
        inventories = tuple(self.source_inventories)
        manifests = tuple(self.version_manifests)
        authorities = tuple(self.scope_authorities)
        authorizations = tuple(self.authorization_bindings)
        if not (
            len(references)
            == len(inventories)
            == len(manifests)
            == len(authorities)
            == len(authorizations)
            == len(self.coverage_ledger.source_inventory_ids)
        ):
            raise ContractValidationError("task query component bindings are incomplete")
        if tuple(reference.ordinal for reference in references) != tuple(range(len(references))):
            raise ContractValidationError("task query component ordinals are not canonical")
        if tuple(reference.source_inventory_id for reference in references) != (
            self.coverage_ledger.source_inventory_ids
        ):
            raise ContractValidationError("task query component inventory order is invalid")
        if tuple(inventory.source_inventory_id for inventory in inventories) != (
            self.coverage_ledger.source_inventory_ids
        ):
            raise ContractValidationError("task query inventories are not canonical")
        if tuple(reference.version_manifest_id for reference in references) != tuple(
            manifest.version_manifest_id for manifest in manifests
        ):
            raise ContractValidationError("task query component manifests are inconsistent")
        if tuple(reference.scope_authority_id for reference in references) != tuple(
            authority.authority_id for authority in authorities
        ):
            raise ContractValidationError("task query component authorities are inconsistent")
        if tuple(self.coverage_ledger.version_bindings) != tuple(
            authority.version_binding for authority in authorities
        ):
            raise ContractValidationError("task query ledger versions are inconsistent")
        if tuple(self.coverage_ledger.authorization_bindings) != authorizations:
            raise ContractValidationError("task query ledger authorizations are inconsistent")
        if tuple(self.coverage_ledger.scope_authorities) != authorities:
            raise ContractValidationError("task query ledger authorities are inconsistent")
        if self.claim_requirement.claim_requirement_id != self.coverage_ledger.claim_requirement_id:
            raise ContractValidationError("task query claim requirement does not bind coverage")
        if (
            self.answer_claim.claim_requirement_id != self.claim_requirement.claim_requirement_id
            or self.answer_claim.coverage_ledger_id != self.coverage_ledger.coverage_ledger_id
        ):
            raise ContractValidationError("task query answer claim does not bind coverage")
        self.answer_claim.to_persistence_dict()

    def to_persistence_dict(self) -> dict[str, Any]:
        return {
            "task_query_id": self.task_query_id,
            "workspace_id": self.workspace_id,
            "owner_user_id": self.owner_user_id,
            "query_hash": self.query_hash,
            "query_result": self.query_result.to_dict(),
            "claim_requirement": self.claim_requirement.to_persistence_dict(),
            "coverage_ledger": self.coverage_ledger.to_persistence_dict(),
            "answer_claim": self.answer_claim.to_persistence_dict(),
            "component_references": [
                reference.to_persistence_dict() for reference in self.component_references
            ],
            "source_inventories": [
                inventory.to_persistence_dict() for inventory in self.source_inventories
            ],
            "version_manifests": [
                manifest.to_persistence_dict() for manifest in self.version_manifests
            ],
            "scope_authorities": [
                authority.to_persistence_dict() for authority in self.scope_authorities
            ],
            "authorization_bindings": [
                binding.to_dict() for binding in self.authorization_bindings
            ],
        }

    @classmethod
    def from_persistence_dict(
        cls,
        value: Mapping[str, Any],
        *,
        expected_scope_authorities: Mapping[str, CoverageScopeAuthority] | None = None,
    ) -> "MailEvidenceTaskQueryRecord":
        if not isinstance(value, Mapping):
            raise ContractValidationError("task query record must be an object")
        required = {
            "task_query_id",
            "workspace_id",
            "owner_user_id",
            "query_hash",
            "query_result",
            "claim_requirement",
            "coverage_ledger",
            "answer_claim",
            "component_references",
            "source_inventories",
            "version_manifests",
            "scope_authorities",
            "authorization_bindings",
        }
        if set(value) != required:
            raise ContractValidationError("task query record fields are invalid")
        references = tuple(
            MailEvidenceTaskComponentReference.from_persistence_dict(item)
            for item in _task_record_list(value, "component_references")
        )
        inventories = tuple(
            SourceInventory.from_persistence_dict(item)
            for item in _task_record_list(value, "source_inventories")
        )
        manifests = tuple(
            VersionManifest.from_persistence_dict(item)
            for item in _task_record_list(value, "version_manifests")
        )
        persisted_authorities = tuple(
            CoverageScopeAuthority.from_persistence_dict(item)
            for item in _task_record_list(value, "scope_authorities")
        )
        authorizations = tuple(
            CoverageAuthorizationBinding.from_dict(item)
            for item in _task_record_list(value, "authorization_bindings")
        )
        requirement = ClaimRequirement.from_persistence_dict(
            _task_record_mapping(value, "claim_requirement")
        )
        ledger = CoverageLedger.from_persistence_dict(
            _task_record_mapping(value, "coverage_ledger")
        )
        answer_payload = _task_record_mapping(value, "answer_claim")
        authorities = _task_query_scope_authorities(
            references=references,
            persisted=persisted_authorities,
            claim_requirement=requirement,
            expected=expected_scope_authorities,
            definitive=answer_payload.get("state") != "INSUFFICIENT_COVERAGE",
        )
        answer_claim = AnswerClaim.from_persistence_dict(
            answer_payload,
            coverage_ledger=ledger,
            claim_requirement=requirement,
            source_inventory=inventories[0] if inventories else None,
            version_manifest=manifests[0] if manifests else None,
            expected_scope_authority=(
                authorities[0]
                if authorities and answer_payload.get("state") != "INSUFFICIENT_COVERAGE"
                else None
            ),
            authorization_binding=authorizations[0] if authorizations else None,
            source_inventories=inventories,
            version_manifests=manifests,
            scope_authorities=authorities,
            authorization_bindings=authorizations,
        )
        return cls(
            task_query_id=value["task_query_id"],
            workspace_id=value["workspace_id"],
            owner_user_id=value["owner_user_id"],
            query_hash=value["query_hash"],
            query_result=_mail_query_result_from_persistence(
                _task_record_mapping(value, "query_result")
            ),
            claim_requirement=requirement,
            coverage_ledger=ledger,
            answer_claim=answer_claim,
            component_references=references,
            source_inventories=inventories,
            version_manifests=manifests,
            scope_authorities=authorities,
            authorization_bindings=authorizations,
        )

    def trusted_scope_authority_map(self) -> dict[str, CoverageScopeAuthority]:
        return {authority.authority_id: authority for authority in self.scope_authorities}


@runtime_checkable
class MailEvidenceBundleStore(Protocol):
    """Atomic persistence boundary for the canonical MailEvidenceBundle shape."""

    def publish_verified_bundle(
        self,
        bundle: MailEvidenceBundle,
        *,
        verify: MailEvidenceVerification,
    ) -> VerifiedMailEvidencePublication: ...

    def get_bundle(
        self,
        *,
        mail_import_session_id: str | None = None,
        mail_evidence_bundle_id: str | None = None,
    ) -> MailEvidenceBundle | None: ...


class FileMailEvidenceBundleStore:
    """Private durable store for exact canonical bundle persistence.

    The store does not define another evidence schema. Each file is exactly one
    ``MailEvidenceBundle.to_persistence_dict()`` payload. Verification runs
    against a round-tripped temporary file before the file becomes visible.
    """

    def __init__(self, base_dir: str | Path, *, create: bool = True) -> None:
        root = Path(base_dir)
        if root.is_symlink():
            raise ContractValidationError("mail evidence state directory must not be a symlink")
        if create:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(root, 0o700)
        elif not root.is_dir():
            raise ContractValidationError("mail evidence state directory is unavailable")
        self.root = root / "mail-evidence" / "canonical-bundles.private"
        if self.root.is_symlink():
            raise ContractValidationError("mail evidence bundle directory must not be a symlink")
        if create:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self.root, 0o700)
        elif not self.root.is_dir():
            raise ContractValidationError("mail evidence bundle directory is unavailable")

    def publish_verified_bundle(
        self,
        bundle: MailEvidenceBundle,
        *,
        verify: MailEvidenceVerification,
    ) -> VerifiedMailEvidencePublication:
        if not isinstance(bundle, MailEvidenceBundle):
            raise ContractValidationError("mail evidence publication requires a typed bundle")
        final_path = self._record_path(bundle.mail_evidence_bundle_id)
        if final_path.exists():
            expected_fingerprint = _canonical_bundle_persistence_fingerprint(bundle)
            del bundle
            existing = self._read(final_path)
            if _canonical_bundle_persistence_fingerprint(existing) != expected_fingerprint:
                raise ContractValidationError(
                    "mail evidence bundle id already exists with different canonical content"
                )
            return VerifiedMailEvidencePublication(
                write_count=1,
                owner_query=verify(existing),
                created=False,
            )

        temporary_path = self.root / (
            f".{bundle.mail_evidence_bundle_id}.{secrets.token_hex(8)}.tmp"
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary_path, flags, 0o600)
        try:
            expected_fingerprint = _write_canonical_bundle_persistence(
                descriptor,
                bundle,
            )
            os.fsync(descriptor)
            os.fchmod(descriptor, 0o600)
        except Exception:
            os.close(descriptor)
            temporary_path.unlink(missing_ok=True)
            raise
        else:
            os.close(descriptor)
        del bundle

        try:
            restored = self._read(temporary_path)
            if _canonical_bundle_persistence_fingerprint(restored) != expected_fingerprint:
                raise ContractValidationError(
                    "mail evidence bundle round trip changed canonical content"
                )
            owner_query = verify(restored)
            os.replace(temporary_path, final_path)
            os.chmod(final_path, 0o600)
            self._fsync_root()
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        return VerifiedMailEvidencePublication(
            write_count=1,
            owner_query=owner_query,
            created=True,
        )

    def get_bundle(
        self,
        *,
        mail_import_session_id: str | None = None,
        mail_evidence_bundle_id: str | None = None,
    ) -> MailEvidenceBundle | None:
        if not mail_import_session_id and not mail_evidence_bundle_id:
            raise ContractValidationError(
                "mail_import_session_id or mail_evidence_bundle_id is required"
            )
        if mail_evidence_bundle_id is not None:
            path = self._record_path(mail_evidence_bundle_id)
            if not path.exists():
                return None
            bundle = self._read(path)
            if (
                mail_import_session_id is not None
                and bundle.mail_import_session.mail_import_session_id != mail_import_session_id
            ):
                return None
            return bundle
        for bundle in self.list_bundles():
            if bundle.mail_import_session.mail_import_session_id == mail_import_session_id:
                return bundle
        return None

    def get_by_archive_hash(self, archive_sha256: str) -> MailEvidenceBundle | None:
        for bundle in self.list_bundles():
            if bundle.mail_import_session.archive_sha256 == archive_sha256:
                return bundle
        return None

    def list_bundles(self) -> list[MailEvidenceBundle]:
        bundles: list[MailEvidenceBundle] = []
        for bundle in self.iter_bundles():
            bundles.append(bundle)
        return bundles

    def iter_bundle_paths(self) -> Iterator[Path]:
        """Yield canonical files deterministically without retaining all bundles."""

        for path in sorted(self.root.glob("*.json"), key=lambda item: item.name):
            if path.is_symlink() or not path.is_file():
                raise ContractValidationError("mail evidence bundle store is invalid")
            yield path

    def iter_bundles(self) -> Iterator[MailEvidenceBundle]:
        """Load at most one canonical bundle per iterator step."""

        for path in self.iter_bundle_paths():
            yield self._read(path)

    def delete_bundle(self, mail_evidence_bundle_id: str) -> None:
        path = self._record_path(mail_evidence_bundle_id)
        if path.is_symlink():
            raise ContractValidationError("mail evidence bundle path is invalid")
        path.unlink(missing_ok=True)
        self._fsync_root()

    def delete_by_archive_hash(self, archive_sha256: str) -> MailEvidenceBundle | None:
        bundle = self.get_by_archive_hash(archive_sha256)
        if bundle is None:
            return None
        self.delete_bundle(bundle.mail_evidence_bundle_id)
        return bundle

    def _record_path(self, mail_evidence_bundle_id: str) -> Path:
        if not isinstance(mail_evidence_bundle_id, str) or not _SAFE_RECORD_ID.fullmatch(
            mail_evidence_bundle_id
        ):
            raise ContractValidationError("mail evidence bundle id is invalid")
        return self.root / f"{mail_evidence_bundle_id}.json"

    @staticmethod
    def _read(path: Path) -> MailEvidenceBundle:
        if path.is_symlink() or not path.is_file():
            raise ContractValidationError("mail evidence bundle path is invalid")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ContractValidationError("mail evidence bundle payload must be an object")
        return MailEvidenceBundle.from_persistence_dict(
            payload,
            consume_input=True,
            _consume_capability=_MAIL_EVIDENCE_PERSISTENCE_CONSUME_CAPABILITY,
        )

    def _fsync_root(self) -> None:
        if not hasattr(os, "O_DIRECTORY"):
            return
        descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class FileDiagnosticStructuralShardStore:
    """Private deterministic layout for bounded structural shard publication."""

    _AGGREGATE_MANIFEST_NAME = "complete-aggregate-manifest.private.json"

    def __init__(self, base_dir: str | Path, *, create: bool = True) -> None:
        base = Path(base_dir)
        if base.is_symlink():
            raise ContractValidationError("diagnostic structural shard state directory is invalid")
        self.root = base / "diagnostic-shards.private"
        if create:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self.root, 0o700)
        elif self.root.is_symlink() or not self.root.is_dir():
            raise ContractValidationError("diagnostic structural shard state is unavailable")
        if self.root.is_symlink() or not self.root.is_dir():
            raise ContractValidationError("diagnostic structural shard state directory is invalid")
        self.aggregate_manifest_path = self.root / self._AGGREGATE_MANIFEST_NAME

    def shard_dir(self, ordinal: int, *, create: bool = False) -> Path:
        if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
            raise ContractValidationError("diagnostic structural shard ordinal is invalid")
        path = self.root / f"{ordinal:08d}"
        if create:
            path.mkdir(parents=False, exist_ok=True, mode=0o700)
            os.chmod(path, 0o700)
        if path.is_symlink() or not path.is_dir():
            raise ContractValidationError("diagnostic structural shard directory is invalid")
        return path

    def bundle_store(
        self,
        ordinal: int,
        *,
        create: bool = False,
    ) -> FileMailEvidenceBundleStore:
        return FileMailEvidenceBundleStore(
            self.shard_dir(ordinal, create=create),
            create=create,
        )

    def unique_bundle_path(self, ordinal: int) -> Path | None:
        store = self.bundle_store(ordinal)
        paths = tuple(store.iter_bundle_paths())
        if len(paths) > 1:
            raise ContractValidationError("diagnostic structural shard contains multiple bundles")
        return paths[0] if paths else None

    def publish_complete_manifest(
        self,
        manifest: DiagnosticStructuralAggregateManifest,
    ) -> bool:
        if not isinstance(manifest, DiagnosticStructuralAggregateManifest):
            raise ContractValidationError("diagnostic structural aggregate publication is invalid")
        self._validate_manifest_bundles(manifest)
        encoded = json.dumps(
            manifest.to_private_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if self.aggregate_manifest_path.exists():
            existing = self.load_complete_manifest()
            if existing != manifest:
                raise ContractValidationError(
                    "diagnostic structural aggregate already exists with different content"
                )
            return False
        temporary = self.root / (f".{self._AGGREGATE_MANIFEST_NAME}.{secrets.token_hex(8)}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600)
        try:
            _write_all(descriptor, encoded)
            os.fsync(descriptor)
            os.fchmod(descriptor, 0o600)
        except Exception:
            os.close(descriptor)
            temporary.unlink(missing_ok=True)
            raise
        else:
            os.close(descriptor)
        try:
            os.replace(temporary, self.aggregate_manifest_path)
            os.chmod(self.aggregate_manifest_path, 0o600)
            self._fsync_root()
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return True

    def load_complete_manifest(self) -> DiagnosticStructuralAggregateManifest:
        path = self.aggregate_manifest_path
        if path.is_symlink() or not path.is_file():
            raise ContractValidationError("diagnostic structural aggregate is incomplete")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractValidationError(
                "diagnostic structural aggregate manifest is invalid"
            ) from exc
        manifest = DiagnosticStructuralAggregateManifest.from_private_dict(payload)
        self._validate_manifest_bundles(manifest)
        return manifest

    def iter_bundle_paths(
        self,
        manifest: DiagnosticStructuralAggregateManifest,
    ) -> Iterator[Path]:
        if not isinstance(manifest, DiagnosticStructuralAggregateManifest):
            raise ContractValidationError("diagnostic structural aggregate manifest is invalid")
        for record in manifest.shards:
            yield self._bundle_path_for_record(record)

    def recompute_body_segment_accounting(
        self,
        records: tuple[DiagnosticStructuralShardRecord, ...],
    ) -> DiagnosticStructuralBodySegmentAccounting:
        """Read checkpoint-bound bundles and return their closed source split.

        Shard checkpoints deliberately bind only the total body-segment count.
        The aggregate contract owns the split, so it is always recomputed from
        the canonical persisted bundle envelopes rather than inferred from
        checkpoint fields or trusted from an aggregate declaration.
        """

        normalized_records = tuple(records)
        if (
            not normalized_records
            or any(
                not isinstance(record, DiagnosticStructuralShardRecord)
                for record in normalized_records
            )
            or tuple(record.ordinal for record in normalized_records)
            != tuple(range(len(normalized_records)))
        ):
            raise ContractValidationError(
                "diagnostic structural aggregate body segment accounting is invalid"
            )
        total_body_segment_count = 0
        message_body_segment_count = 0
        attachment_text_segment_count = 0
        for record in normalized_records:
            path = self._bundle_path_for_record(record)
            bundle = FileMailEvidenceBundleStore._read(path)
            accounting = _body_segment_accounting_from_persisted_bundle(
                bundle_path=path,
                bundle=bundle,
            )
            if accounting.total_body_segment_count != record.body_segment_count:
                raise ContractValidationError(
                    "diagnostic structural aggregate body segment accounting is incomplete"
                )
            total_body_segment_count += accounting.total_body_segment_count
            message_body_segment_count += accounting.message_body_segment_count
            attachment_text_segment_count += accounting.attachment_text_segment_count
        return DiagnosticStructuralBodySegmentAccounting(
            total_body_segment_count=total_body_segment_count,
            message_body_segment_count=message_body_segment_count,
            attachment_text_segment_count=attachment_text_segment_count,
        )

    def checkpoint_bound_bundle_path(
        self,
        record: DiagnosticStructuralShardRecord,
    ) -> Path:
        """Return one canonical bundle only when its checkpoint binding holds."""

        return self._bundle_path_for_record(record)

    def iter_bundles(
        self,
        manifest: DiagnosticStructuralAggregateManifest,
        *,
        scope_authority_verifier: CoverageScopeAuthorityVerifier,
    ) -> Iterator[MailEvidenceBundle]:
        if not isinstance(
            scope_authority_verifier,
            CoverageScopeAuthorityVerifier,
        ):
            raise ContractValidationError(
                "diagnostic structural shard authority verifier is unavailable"
            )
        for record, path in zip(
            manifest.shards,
            self.iter_bundle_paths(manifest),
            strict=True,
        ):
            bundle = FileMailEvidenceBundleStore._read(path)
            if bundle.mail_evidence_bundle_id != record.mail_evidence_bundle_id:
                raise ContractValidationError(
                    "diagnostic structural aggregate bundle identity is invalid"
                )
            trusted: dict[str, CoverageScopeAuthority] = {}
            for ledger in bundle.coverage_ledgers:
                partition = ledger.scope_partition
                authority = partition.scope_authority if partition is not None else None
                if not isinstance(authority, CoverageScopeAuthority):
                    continue
                revalidated = scope_authority_verifier.revalidate(authority)
                trusted[f"{ledger.claim_requirement_id}:{ledger.source_inventory_id}"] = revalidated
            if bundle.coverage_ledgers and not trusted:
                raise ContractValidationError("diagnostic structural shard authority is incomplete")
            yield replace(bundle, _expected_scope_authorities=trusted)

    def _validate_manifest_bundles(
        self,
        manifest: DiagnosticStructuralAggregateManifest,
    ) -> None:
        expected_names = {f"{record.ordinal:08d}" for record in manifest.shards}
        actual_names = {
            path.name for path in self.root.iterdir() if path.is_dir() and path.name.isdigit()
        }
        if actual_names != expected_names:
            raise ContractValidationError("diagnostic structural aggregate shard set is incomplete")
        accounting = self.recompute_body_segment_accounting(manifest.shards)
        if (
            accounting.total_body_segment_count != manifest.materialized_body_segment_count
            or accounting.message_body_segment_count
            != manifest.materialized_message_body_segment_count
            or accounting.attachment_text_segment_count
            != manifest.materialized_attachment_text_segment_count
        ):
            raise ContractValidationError(
                "diagnostic structural aggregate body segment accounting is inconsistent"
            )

    def _bundle_path_for_record(
        self,
        record: DiagnosticStructuralShardRecord,
    ) -> Path:
        if not isinstance(record, DiagnosticStructuralShardRecord):
            raise ContractValidationError("diagnostic structural aggregate shard is incomplete")
        path = self.unique_bundle_path(record.ordinal)
        if (
            path is None
            or path.name != f"{record.mail_evidence_bundle_id}.json"
            or sha256_file(path) != record.bundle_fingerprint
        ):
            raise ContractValidationError("diagnostic structural aggregate shard is incomplete")
        return path

    def _fsync_root(self) -> None:
        if not hasattr(os, "O_DIRECTORY"):
            return
        descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _body_segment_accounting_from_persisted_bundle(
    *,
    bundle_path: Path,
    bundle: MailEvidenceBundle,
) -> DiagnosticStructuralBodySegmentAccounting:
    """Validate explicit body-segment source envelopes and their bindings."""

    if (
        not isinstance(bundle_path, Path)
        or bundle_path.is_symlink()
        or not bundle_path.is_file()
        or not isinstance(bundle, MailEvidenceBundle)
    ):
        raise ContractValidationError(
            "diagnostic structural aggregate body segment accounting is invalid"
        )
    try:
        payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractValidationError(
            "diagnostic structural aggregate body segment accounting is invalid"
        ) from exc
    raw_segments = payload.get("body_segments") if isinstance(payload, Mapping) else None
    if not isinstance(raw_segments, list):
        raise ContractValidationError(
            "diagnostic structural aggregate body segment accounting is invalid"
        )

    typed_by_id = {segment.email_body_segment_id: segment for segment in bundle.body_segments}
    if len(typed_by_id) != len(bundle.body_segments) or len(raw_segments) != len(typed_by_id):
        raise ContractValidationError(
            "diagnostic structural aggregate body segment accounting is invalid"
        )
    raw_by_id: dict[str, Mapping[str, Any]] = {}
    for raw_segment in raw_segments:
        if not isinstance(raw_segment, Mapping):
            raise ContractValidationError(
                "diagnostic structural aggregate body segment accounting is invalid"
            )
        segment_id = raw_segment.get("email_body_segment_id")
        source_type = raw_segment.get("segment_source_type")
        if (
            not isinstance(segment_id, str)
            or not segment_id
            or segment_id in raw_by_id
            or source_type not in _DIAGNOSTIC_STRUCTURAL_ALLOWED_BODY_SEGMENT_SOURCE_TYPES
        ):
            raise ContractValidationError(
                "diagnostic structural aggregate body segment accounting is invalid"
            )
        raw_by_id[segment_id] = raw_segment
    if set(raw_by_id) != set(typed_by_id):
        raise ContractValidationError(
            "diagnostic structural aggregate body segment accounting is invalid"
        )

    message_occurrence_by_id = {}
    for occurrence in bundle.message_occurrences:
        existing = message_occurrence_by_id.setdefault(
            occurrence.message_occurrence_id,
            occurrence,
        )
        if existing is not occurrence:
            raise ContractValidationError(
                "diagnostic structural aggregate body segment accounting is invalid"
            )
    attachment_occurrence_keys = {
        (
            occurrence.attachment_id,
            occurrence.email_message_id,
            occurrence.message_occurrence_id,
        )
        for occurrence in bundle.attachment_occurrences
    }
    message_body_segment_count = 0
    attachment_text_segment_count = 0
    for segment_id, segment in typed_by_id.items():
        raw_segment = raw_by_id[segment_id]
        source_type = raw_segment["segment_source_type"]
        if segment.segment_source_type != source_type:
            raise ContractValidationError(
                "diagnostic structural aggregate body segment accounting is invalid"
            )
        message_occurrence = message_occurrence_by_id.get(segment.message_occurrence_id)
        if (
            message_occurrence is None
            or message_occurrence.email_message_id != segment.email_message_id
        ):
            raise ContractValidationError(
                "diagnostic structural aggregate body segment accounting is invalid"
            )
        if source_type == "message_body":
            message_body_segment_count += 1
            continue
        attachment_id = segment.attachment_id
        if (
            not isinstance(attachment_id, str)
            or not attachment_id
            or (
                attachment_id,
                segment.email_message_id,
                segment.message_occurrence_id,
            )
            not in attachment_occurrence_keys
        ):
            raise ContractValidationError(
                "diagnostic structural aggregate body segment accounting is invalid"
            )
        attachment_text_segment_count += 1
    return DiagnosticStructuralBodySegmentAccounting(
        total_body_segment_count=len(typed_by_id),
        message_body_segment_count=message_body_segment_count,
        attachment_text_segment_count=attachment_text_segment_count,
    )


def sha256_file(path: str | Path) -> str:
    """Hash one private file with a fixed buffer and no whole-file read."""

    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise ContractValidationError("diagnostic structural shard file is invalid")
    digest = hashlib.sha256()
    with candidate.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


class FileMailEvidenceTaskQueryStore:
    """Private file owner for aggregate task/query results."""

    def __init__(self, base_dir: str | Path) -> None:
        root = Path(base_dir)
        if root.is_symlink():
            raise ContractValidationError("task query state directory must not be a symlink")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(root, 0o700)
        self.root = root / "mail-evidence" / "task-query-results.private"
        if self.root.is_symlink():
            raise ContractValidationError("task query result directory must not be a symlink")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)

    def put(self, record: MailEvidenceTaskQueryRecord) -> None:
        if not isinstance(record, MailEvidenceTaskQueryRecord):
            raise ContractValidationError("task query store requires a typed record")
        payload = record.to_persistence_dict()
        validated = MailEvidenceTaskQueryRecord.from_persistence_dict(
            payload,
            expected_scope_authorities=record.trusted_scope_authority_map(),
        )
        final_path = self._record_path(validated.task_query_id)
        encoded = json.dumps(
            validated.to_persistence_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        temporary_path = self.root / f".{validated.task_query_id}.{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary_path, flags, 0o600)
        try:
            remaining = memoryview(encoded)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError("task query result write failed")
                remaining = remaining[written:]
            os.fsync(descriptor)
            os.fchmod(descriptor, 0o600)
        except Exception:
            os.close(descriptor)
            temporary_path.unlink(missing_ok=True)
            raise
        else:
            os.close(descriptor)
        try:
            os.replace(temporary_path, final_path)
            os.chmod(final_path, 0o600)
            self._fsync_root()
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise

    def get(
        self,
        task_query_id: str,
        *,
        expected_scope_authorities: Mapping[str, CoverageScopeAuthority],
    ) -> MailEvidenceTaskQueryRecord | None:
        path = self._record_path(task_query_id)
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise ContractValidationError("task query result path is invalid")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return MailEvidenceTaskQueryRecord.from_persistence_dict(
            payload,
            expected_scope_authorities=expected_scope_authorities,
        )

    def _record_path(self, task_query_id: str) -> Path:
        _validate_task_record_id(task_query_id, "task_query_id")
        return self.root / f"{task_query_id}.json"

    def _fsync_root(self) -> None:
        if not hasattr(os, "O_DIRECTORY"):
            return
        descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _validate_task_record_id(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not _SAFE_RECORD_ID.fullmatch(value):
        raise ContractValidationError(f"{field_name} is invalid")


def _task_record_list(value: Mapping[str, Any], field_name: str) -> list[Mapping[str, Any]]:
    result = value.get(field_name)
    if not isinstance(result, list) or any(not isinstance(item, Mapping) for item in result):
        raise ContractValidationError(f"{field_name} must be a list of objects")
    return result


def _task_record_mapping(value: Mapping[str, Any], field_name: str) -> Mapping[str, Any]:
    result = value.get(field_name)
    if not isinstance(result, Mapping):
        raise ContractValidationError(f"{field_name} must be an object")
    return result


def _task_query_scope_authorities(
    *,
    references: tuple[MailEvidenceTaskComponentReference, ...],
    persisted: tuple[CoverageScopeAuthority, ...],
    claim_requirement: ClaimRequirement,
    expected: Mapping[str, CoverageScopeAuthority] | None,
    definitive: bool,
) -> tuple[CoverageScopeAuthority, ...]:
    expected_map = dict(expected or {})
    if any(
        not isinstance(key, str) or not isinstance(authority, CoverageScopeAuthority)
        for key, authority in expected_map.items()
    ):
        raise ContractValidationError("expected task query authorities are invalid")
    resolved: list[CoverageScopeAuthority] = []
    for reference, persisted_authority in zip(references, persisted, strict=True):
        candidates = (
            expected_map.get(reference.scope_authority_id),
            expected_map.get(reference.source_inventory_id),
            expected_map.get(
                f"{claim_requirement.claim_requirement_id}:{reference.source_inventory_id}"
            ),
        )
        trusted = next(
            (
                candidate
                for candidate in candidates
                if isinstance(candidate, CoverageScopeAuthority)
            ),
            None,
        )
        if trusted is None:
            trusted = next(
                (
                    candidate
                    for candidate in expected_map.values()
                    if candidate.authority_id == reference.scope_authority_id
                ),
                None,
            )
        if trusted is not None and trusted.to_persistence_dict() != (
            persisted_authority.to_persistence_dict()
        ):
            raise ContractValidationError("task query authority does not match persistence")
        if definitive and trusted is None:
            raise ContractValidationError(
                "authoritative task query restore requires trusted component authorities"
            )
        resolved.append(trusted or persisted_authority)
    return tuple(resolved)


def _mail_query_result_from_persistence(
    value: Mapping[str, Any],
) -> MailEvidenceQueryResult:
    allowed = {
        "status",
        "mail_import_session_id",
        "query_hash",
        "evidence_snippets",
        "citations",
        "redaction_counts",
        "warnings",
        "evidence_completeness",
        "answerability_state",
    }
    required = allowed - {"mail_import_session_id"}
    if not required.issubset(value) or set(value) - allowed:
        raise ContractValidationError("task query result fields are invalid")
    if not isinstance(value["evidence_snippets"], list) or not isinstance(value["citations"], list):
        raise ContractValidationError("task query evidence payload is invalid")
    if not isinstance(value["redaction_counts"], Mapping) or not isinstance(
        value["warnings"], list
    ):
        raise ContractValidationError("task query result metadata is invalid")
    return MailEvidenceQueryResult(
        status=value["status"],
        mail_import_session_id=value.get("mail_import_session_id"),
        query_hash=value["query_hash"],
        evidence_snippets=list(value["evidence_snippets"]),
        citations=list(value["citations"]),
        redaction_counts=dict(value["redaction_counts"]),
        warnings=list(value["warnings"]),
        evidence_completeness=value["evidence_completeness"],
        answerability_state=value["answerability_state"],
    )


__all__ = [
    "DIAGNOSTIC_EXISTING_EXPORT_SCOPE_KIND",
    "DIAGNOSTIC_STRUCTURAL_BASELINE_SCOPE_KIND",
    "DIAGNOSTIC_STRUCTURAL_BRIDGE_IMPLEMENTATION_VERSION",
    "DIAGNOSTIC_STRUCTURAL_BRIDGE_PRODUCER_TYPE",
    "DIAGNOSTIC_STRUCTURAL_SCOPE_POLICY_ID",
    "DIAGNOSTIC_STRUCTURAL_SCOPE_POLICY_VERSION",
    "DiagnosticExistingExportVerification",
    "DiagnosticStructuralAggregateManifest",
    "DiagnosticStructuralShardRecord",
    "FileDiagnosticStructuralShardStore",
    "FileMailEvidenceBundleStore",
    "FileMailEvidenceTaskQueryStore",
    "MailEvidenceBundleStore",
    "MailEvidenceVerification",
    "MailEvidenceTaskComponentReference",
    "MailEvidenceTaskQueryRecord",
    "VerifiedMailEvidencePublication",
    "diagnostic_structural_baseline_parameters",
    "diagnostic_structural_implementation_fingerprint",
    "diagnostic_structural_scope_policy_fingerprint",
    "sha256_file",
]
