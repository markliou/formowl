"""Synthetic gates for bounded diagnostic structural shard recovery."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("FORMOWL_MAIL_TOKENIZER_MODE", "legacy_ascii_test")

from formowl_contract import (  # noqa: E402
    Asset,
    ContractValidationError,
    CoverageScopeAuthorityVerifier,
    SemanticSchemaAliasMap,
    SourceInventory,
    StructuralCell,
    sha256_json,
)
from formowl_ingestion.extraction import ExtractionInput  # noqa: E402
from formowl_ingestion.extractors.mail.pst import extract_readpst_export  # noqa: E402
import formowl_mail.diagnostic_mcp as diagnostic_mcp  # noqa: E402
import formowl_mail.diagnostic_structural_bridge as diagnostic_structural_bridge  # noqa: E402
from formowl_mail.diagnostic_mcp import (  # noqa: E402
    CandidateGraphQueryRuntime,
    DiagnosticSemanticProfile,
    _SemanticMcpRequest,
    _semantic_evidence_time_admissible,
    validate_diagnostic_semantic_profile_binding,
)
from formowl_mail.diagnostic_structural_bridge import (  # noqa: E402
    DiagnosticStructuralScopeManifest,
    DiagnosticStructuralScopeSelector,
    _deterministic_path_batches,
    _selected_top_level_message_occurrence_ids,
    _scope_manifest_id,
    build_diagnostic_current_export_native_scope,
    load_diagnostic_current_export_native_selection_checkpoint,
    load_diagnostic_structural_scope_manifest,
    materialize_diagnostic_structural_scope,
    plan_diagnostic_structural_materialization,
    produce_diagnostic_structural_bridge,
    write_diagnostic_current_export_native_scope,
    write_diagnostic_structural_scope_manifest,
)
from formowl_mail.persistence import (  # noqa: E402
    DiagnosticExistingExportVerification,
    DiagnosticStructuralAggregateManifest,
    FileDiagnosticStructuralShardStore,
    FileMailEvidenceBundleStore,
    sha256_file,
)


_CREATED_AT = "2026-08-05T00:00:00+00:00"
_SOURCE_FINGERPRINT = "sha256:" + "a" * 64
_PERMISSION_SCOPE = {"scope_type": "project", "visibility": "workspace"}


def _message(message_id: str, projected_value: str) -> bytes:
    return (
        "From: sender@example.test\n"
        "To: recipient@example.test\n"
        f"Message-ID: <{message_id}>\n"
        "Subject: synthetic structural evidence\n"
        "Date: Tue, 04 Aug 2026 12:00:00 +0000\n"
        "MIME-Version: 1.0\n"
        "Content-Type: text/html; charset=utf-8\n"
        "\n"
        "<html><body><table>"
        "<tr><th>Item Code</th><th>Source Region</th></tr>"
        f"<tr><td>{projected_value}</td><td>Zone A</td></tr>"
        "</table></body></html>\n"
    ).encode()


def _message_with_ambiguous_headers(message_id: str, projected_value: str) -> bytes:
    """Produce a valid table whose duplicate header remains index-unavailable."""

    return (
        "From: sender@example.test\n"
        "To: recipient@example.test\n"
        f"Message-ID: <{message_id}>\n"
        "Subject: synthetic ambiguous structural evidence\n"
        "Date: Tue, 04 Aug 2026 12:00:00 +0000\n"
        "MIME-Version: 1.0\n"
        "Content-Type: text/html; charset=utf-8\n"
        "\n"
        "<html><body><table>"
        "<tr><th>Item Code</th><th>Source Region</th><th>Note</th><th>Note</th></tr>"
        f"<tr><td>{projected_value}</td><td>Zone A</td><td>One</td><td>Two</td></tr>"
        "</table></body></html>\n"
    ).encode()


def _message_with_fully_ambiguous_headers(message_id: str) -> bytes:
    """Produce a synthetic compact table with no exact schema index keys."""

    return _message_with_fully_ambiguous_rows(
        message_id,
        rows=(("First", "Zone A"),),
    )


def _message_with_fully_ambiguous_rows(
    message_id: str,
    *,
    rows: tuple[tuple[str, str], ...],
) -> bytes:
    """Produce an unindexed synthetic table with caller-selected rows."""

    rendered_rows = "".join(
        f"<tr><td>{item}</td><td>{item}</td>"
        f"<td>{region}</td><td>{region}</td></tr>"
        for item, region in rows
    )
    return (
        "From: sender@example.test\n"
        "To: recipient@example.test\n"
        f"Message-ID: <{message_id}>\n"
        "Subject: synthetic fully ambiguous structural evidence\n"
        "Date: Tue, 04 Aug 2026 12:00:00 +0000\n"
        "MIME-Version: 1.0\n"
        "Content-Type: text/html; charset=utf-8\n"
        "\n"
        "<html><body><table>"
        "<tr><th>Item Code</th><th>Item Code</th>"
        "<th>Source Region</th><th>Source Region</th></tr>"
        f"{rendered_rows}"
        "</table></body></html>\n"
    ).encode()


def _message_with_text_attachment(message_id: str, projected_value: str) -> bytes:
    return (
        "From: sender@example.test\n"
        "To: recipient@example.test\n"
        f"Message-ID: <{message_id}>\n"
        "Subject: synthetic structural evidence with text attachment\n"
        "Date: Tue, 04 Aug 2026 12:00:00 +0000\n"
        "MIME-Version: 1.0\n"
        'Content-Type: multipart/mixed; boundary="outer-boundary"\n'
        "\n"
        "--outer-boundary\n"
        "Content-Type: text/html; charset=utf-8\n"
        "\n"
        "<html><body><table>"
        "<tr><th>Item Code</th><th>Source Region</th></tr>"
        f"<tr><td>{projected_value}</td><td>Zone A</td></tr>"
        "</table></body></html>\n"
        "--outer-boundary\n"
        "Content-Type: text/plain; charset=utf-8\n"
        'Content-Disposition: attachment; filename="supplement.txt"\n'
        "\n"
        "Supplementary structured context.\n"
        "--outer-boundary--\n"
    ).encode()


def _message_with_embedded_table(
    *,
    message_id: str,
    projected_value: str,
    embedded_message_id: str,
    embedded_projected_value: str,
) -> bytes:
    return (
        "From: sender@example.test\n"
        "To: recipient@example.test\n"
        f"Message-ID: <{message_id}>\n"
        "Subject: synthetic structural evidence with child\n"
        "Date: Tue, 04 Aug 2026 12:00:00 +0000\n"
        "MIME-Version: 1.0\n"
        'Content-Type: multipart/mixed; boundary="outer-boundary"\n'
        "\n"
        "--outer-boundary\n"
        "Content-Type: text/html; charset=utf-8\n"
        "\n"
        "<html><body><table>"
        "<tr><th>Item Code</th><th>Source Region</th></tr>"
        f"<tr><td>{projected_value}</td><td>Zone A</td></tr>"
        "</table></body></html>\n"
        "--outer-boundary\n"
        "Content-Type: message/rfc822\n"
        'Content-Disposition: attachment; filename="embedded.eml"\n'
        "\n"
        "From: child@example.test\n"
        "To: recipient@example.test\n"
        f"Message-ID: <{embedded_message_id}>\n"
        "Subject: synthetic embedded structural evidence\n"
        "Date: Tue, 04 Aug 2026 12:00:00 +0000\n"
        "MIME-Version: 1.0\n"
        "Content-Type: text/html; charset=utf-8\n"
        "\n"
        "<html><body><table>"
        "<tr><th>Item Code</th><th>Source Region</th></tr>"
        f"<tr><td>{embedded_projected_value}</td><td>Zone A</td></tr>"
        "</table></body></html>\n"
        "--outer-boundary--\n"
    ).encode()


def _profile(
    *,
    actor_context_id: str = "actor_synthetic",
    known_as_of: str = _CREATED_AT,
    extra_predicate_aliases: dict[str, tuple[str, ...]] | None = None,
    extra_value_aliases: dict[str, dict[str, tuple[str, ...]]] | None = None,
) -> DiagnosticSemanticProfile:
    predicate_aliases = {
        "source region": ("origin",),
        "item code": ("code",),
    }
    value_aliases = {
        "source region": {"zone a": ("region alpha",)},
        "item code": {
            "alpha": ("item alpha",),
            "beta": ("item beta",),
        },
    }
    if extra_predicate_aliases is not None:
        predicate_aliases.update(extra_predicate_aliases)
    if extra_value_aliases is not None:
        value_aliases.update(extra_value_aliases)
    aliases = SemanticSchemaAliasMap(
        object_aliases={"html_table": ("table",)},
        predicate_aliases=predicate_aliases,
        value_aliases=value_aliases,
    )
    values = {
        "profile_id": "profile_synthetic",
        "profile_version": "1",
        "schema_alias_map": aliases,
        "workspace_id": "workspace_synthetic",
        "owner_user_id": "user_synthetic",
        "actor_context_id": actor_context_id,
        "known_as_of": known_as_of,
    }
    return DiagnosticSemanticProfile(
        profile_fingerprint=DiagnosticSemanticProfile.fingerprint_for(**values),
        **values,
    )


def _offset_timestamp(value: str, *, seconds: int) -> str:
    return (
        datetime.fromisoformat(value.replace("Z", "+00:00")) + timedelta(seconds=seconds)
    ).isoformat()


def _scope_manifest(export_root: Path) -> DiagnosticStructuralScopeManifest:
    asset = Asset(
        asset_id="asset_synthetic",
        storage_backend_id="diagnostic_test",
        object_uri="diagnostic://synthetic-export",
        content_hash=_SOURCE_FINGERPRINT,
        file_size=0,
        mime_type="application/vnd.ms-outlook",
        created_at=_CREATED_AT,
        registered_at=_CREATED_AT,
        owner_user_id="user_synthetic",
        workspace_id="workspace_synthetic",
        permission_scope=_PERMISSION_SCOPE,
        lifecycle_state="active",
    )
    result = extract_readpst_export(
        extraction_input=ExtractionInput(
            asset=asset,
            object_path=export_root,
            extractor_run_id="extractor_synthetic_manifest",
            config={"parser_workers": 1},
            created_at=_CREATED_AT,
        ),
        export_root=export_root,
    )
    messages = [item for item in result.observations if item.observation_type == "email_message"]
    body_segments = [
        item for item in result.observations if item.observation_type == "email_body_segment"
    ]
    counts: dict[tuple[str, str, str], int] = {}
    for message in messages:
        location = dict(message.location)
        payload = dict(message.payload or {})
        key = (
            location.get("message_id") or payload["message_id"],
            location["folder_path_hash"],
            payload["body_hash"],
        )
        counts[key] = counts.get(key, 0) + 1
    selectors = tuple(
        DiagnosticStructuralScopeSelector(
            selector_id=sha256_json(
                {
                    "message_id": message_id,
                    "folder_path_hash": folder_path_hash,
                    "body_hash": body_hash,
                }
            ),
            message_id=message_id,
            folder_path_hash=folder_path_hash,
            body_hash=body_hash,
            expected_occurrence_count=count,
        )
        for (message_id, folder_path_hash, body_hash), count in counts.items()
    )
    values = {
        "source_asset_id": asset.asset_id,
        "source_fingerprint": asset.content_hash,
        "workspace_id": asset.workspace_id,
        "owner_user_id": asset.owner_user_id,
        "permission_scope": asset.permission_scope,
        "expected_message_count": len(messages),
        "expected_body_segment_count": len(body_segments),
        "source_observation_set_fingerprint": sha256_json(
            sorted(item.observation_id for item in (*messages, *body_segments))
        ),
        "selectors": selectors,
    }
    return DiagnosticStructuralScopeManifest(
        scope_manifest_id=_scope_manifest_id(**values),
        **values,
    )


def _historical_manifest_with_projection_drift(
    current_manifest: DiagnosticStructuralScopeManifest,
) -> DiagnosticStructuralScopeManifest:
    selectors = tuple(
        DiagnosticStructuralScopeSelector(
            selector_id=sha256_json(
                {
                    "message_id": selector.message_id,
                    "folder_path_hash": selector.folder_path_hash,
                    "body_hash": "sha256:"
                    + hashlib.sha256(
                        f"historical-projection-{ordinal}".encode("ascii")
                    ).hexdigest(),
                }
            ),
            message_id=selector.message_id,
            folder_path_hash=selector.folder_path_hash,
            body_hash="sha256:"
            + hashlib.sha256(f"historical-projection-{ordinal}".encode("ascii")).hexdigest(),
            expected_occurrence_count=selector.expected_occurrence_count,
        )
        for ordinal, selector in enumerate(current_manifest.selectors)
    )
    values = {
        "source_asset_id": current_manifest.source_asset_id,
        "source_fingerprint": current_manifest.source_fingerprint,
        "workspace_id": current_manifest.workspace_id,
        "owner_user_id": current_manifest.owner_user_id,
        "permission_scope": current_manifest.permission_scope,
        "expected_message_count": current_manifest.expected_message_count,
        # Historical body projection accounting must remain immutable even
        # when the current parser materializes a different segment count.
        "expected_body_segment_count": current_manifest.expected_body_segment_count + 1,
        "source_observation_set_fingerprint": (current_manifest.source_observation_set_fingerprint),
        "selectors": selectors,
    }
    return DiagnosticStructuralScopeManifest(
        scope_manifest_id=_scope_manifest_id(**values),
        **values,
    )


def _write_historical_compatibility_checkpoint(
    *,
    path: Path,
    scope_manifest_path: Path,
    manifest: DiagnosticStructuralScopeManifest,
    selected_paths: tuple[str, ...],
    legacy_parser_sha256: str = "sha256:" + "f" * 64,
) -> None:
    selector_counts = {
        selector.selector_id: selector.expected_occurrence_count for selector in manifest.selectors
    }
    selector_coverage = [
        {"selector_id": selector_id, "occurrence_count": selector_counts[selector_id]}
        for selector_id in sorted(selector_counts)
    ]
    payload = {
        "artifact_type": "diagnostic_historical_scope_compatibility_checkpoint_v1",
        "scope_manifest_id": manifest.scope_manifest_id,
        "scope_manifest_sha256": (
            "sha256:" + hashlib.sha256(scope_manifest_path.read_bytes()).hexdigest()
        ),
        "legacy_parser_sha256": legacy_parser_sha256,
        "selected_path_count": len(selected_paths),
        "matched_occurrence_count": manifest.expected_message_count,
        "selector_coverage_fingerprint": sha256_json(selector_coverage),
        "path_bindings": [],
        "compatibility_groups": [
            {
                "group_id": "synthetic-group-1",
                "relative_paths": list(selected_paths),
                "selected_path_set_fingerprint": sha256_json(list(selected_paths)),
                "selector_coverage": selector_coverage,
                "selector_coverage_fingerprint": sha256_json(selector_coverage),
            }
        ],
    }
    path.write_text(
        json.dumps(payload, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    os.chmod(path, 0o600)


def _semantic_request(
    *,
    predicate_mention: str = "origin",
    value_mention: str = "region alpha",
    projection_mention: str = "code",
) -> _SemanticMcpRequest:
    return _SemanticMcpRequest.from_dict(
        {
            "query_class": "attribute_filter",
            "object_type_mention": "table",
            "predicate_mention": predicate_mention,
            "operator": "equals",
            "value_mention": value_mention,
            "projection_mention": projection_mention,
            "cardinality": "all_matching",
            "page_size": 10,
            "page_number": 1,
        }
    )


def _runtime(
    bridge_dir: Path,
    *,
    profile: DiagnosticSemanticProfile,
    verifier: CoverageScopeAuthorityVerifier,
    prevalidated_semantic_shard_templates: tuple[object, ...] = (),
) -> CandidateGraphQueryRuntime:
    candidate_index = SimpleNamespace(
        evidence_index=SimpleNamespace(),
        segment_by_observation_id={},
        text_policy_runtime=SimpleNamespace(tokenize=lambda _: ()),
    )
    return CandidateGraphQueryRuntime(
        candidate_index=candidate_index,
        access_binding=object(),
        retrieval_scope={},
        structural_shard_store=FileDiagnosticStructuralShardStore(
            bridge_dir,
            create=False,
        ),
        semantic_profile=profile,
        scope_authority_verifier=verifier,
        prevalidated_semantic_shard_templates=prevalidated_semantic_shard_templates,
    )


def _rebuild_aggregate(
    aggregate: DiagnosticStructuralAggregateManifest,
    *,
    expected_body_segment_count: int | None = None,
    shards: tuple | None = None,
    materialized_message_body_segment_count: int | None = None,
    materialized_attachment_text_segment_count: int | None = None,
) -> DiagnosticStructuralAggregateManifest:
    return DiagnosticStructuralAggregateManifest.create(
        scope_manifest_id=aggregate.scope_manifest_id,
        source_asset_id=aggregate.source_asset_id,
        source_fingerprint=aggregate.source_fingerprint,
        workspace_id=aggregate.workspace_id,
        owner_user_id=aggregate.owner_user_id,
        semantic_profile_fingerprint=aggregate.semantic_profile_fingerprint,
        existing_export_verification=aggregate.existing_export_verification,
        shard_batch_size=aggregate.shard_batch_size,
        selected_path_set_fingerprint=aggregate.selected_path_set_fingerprint,
        selector_coverage_fingerprint=aggregate.selector_coverage_fingerprint,
        expected_message_count=aggregate.expected_message_count,
        expected_body_segment_count=(
            aggregate.expected_body_segment_count
            if expected_body_segment_count is None
            else expected_body_segment_count
        ),
        aggregate_contract_revision=aggregate.aggregate_contract_revision,
        total_structural_observation_count=aggregate.total_structural_observation_count,
        shards=aggregate.shards if shards is None else shards,
        historical_compatibility_checkpoint_fingerprint=(
            aggregate.historical_compatibility_checkpoint_fingerprint
        ),
        selected_top_level_message_count=aggregate.selected_top_level_message_count,
        materialized_message_occurrence_count=aggregate.materialized_message_occurrence_count,
        materialized_body_segment_count=aggregate.materialized_body_segment_count,
        materialized_message_body_segment_count=(
            aggregate.materialized_message_body_segment_count
            if materialized_message_body_segment_count is None
            else materialized_message_body_segment_count
        ),
        materialized_attachment_text_segment_count=(
            aggregate.materialized_attachment_text_segment_count
            if materialized_attachment_text_segment_count is None
            else materialized_attachment_text_segment_count
        ),
    )


def _write_private_aggregate(
    store: FileDiagnosticStructuralShardStore,
    aggregate: DiagnosticStructuralAggregateManifest,
) -> None:
    store.aggregate_manifest_path.write_text(
        json.dumps(
            aggregate.to_private_dict(),
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    os.chmod(store.aggregate_manifest_path, 0o600)


class DiagnosticStructuralShardTests(unittest.TestCase):
    def _prepare(
        self,
        root: Path,
        *,
        projected_values: tuple[str, ...] = ("Alpha", "Alpha"),
        profile: DiagnosticSemanticProfile | None = None,
        messages: tuple[bytes, ...] | None = None,
    ) -> tuple[
        DiagnosticStructuralScopeManifest,
        DiagnosticSemanticProfile,
        CoverageScopeAuthorityVerifier,
        Path,
        Path,
    ]:
        export_root = root / "export"
        export_root.mkdir()
        if messages is None:
            messages = tuple(
                _message(
                    f"message-{ordinal}@example.test",
                    projected_value,
                )
                for ordinal, projected_value in enumerate(projected_values)
            )
        if not messages or any(not isinstance(message, bytes) for message in messages):
            raise ValueError("synthetic messages are invalid")
        for ordinal, message in enumerate(messages):
            (export_root / f"{len(messages) - ordinal:02d}.eml").write_bytes(message)
        manifest = _scope_manifest(export_root)
        profile = _profile() if profile is None else profile
        verifier = CoverageScopeAuthorityVerifier.from_external_root(b"x" * 32)
        bridge_dir = root / "bridge"
        checkpoint_dir = root / "checkpoint"
        return manifest, profile, verifier, bridge_dir, checkpoint_dir

    def _materialize(
        self,
        root: Path,
        *,
        projected_values: tuple[str, ...] = ("Alpha", "Alpha"),
        profile: DiagnosticSemanticProfile | None = None,
        messages: tuple[bytes, ...] | None = None,
        shard_batch_size: int = 1,
    ) -> tuple[
        DiagnosticStructuralScopeManifest,
        DiagnosticSemanticProfile,
        CoverageScopeAuthorityVerifier,
        Path,
        Path,
    ]:
        manifest, profile, verifier, bridge_dir, checkpoint_dir = self._prepare(
            root,
            projected_values=projected_values,
            profile=profile,
            messages=messages,
        )
        export_root = root / "export"
        materialize_diagnostic_structural_scope(
            manifest,
            bridge_dir=bridge_dir,
            checkpoint_dir=checkpoint_dir,
            created_at=_CREATED_AT,
            export_root=export_root,
            full_scope_source_asset_id=manifest.source_asset_id,
            full_scope_source_fingerprint=manifest.source_fingerprint,
            shard_batch_size=shard_batch_size,
            reader_uid=os.getuid(),
            reader_gid=os.getgid(),
            scope_authority_verifier=verifier,
            semantic_profile=profile,
        )
        return manifest, profile, verifier, bridge_dir, checkpoint_dir

    def _materialize_with_text_attachment(
        self,
        root: Path,
    ) -> tuple[
        DiagnosticStructuralScopeManifest,
        DiagnosticSemanticProfile,
        CoverageScopeAuthorityVerifier,
        Path,
        Path,
    ]:
        export_root = root / "export"
        export_root.mkdir()
        (export_root / "01.eml").write_bytes(
            _message_with_text_attachment("attachment@test", "Alpha")
        )
        manifest = _scope_manifest(export_root)
        profile = _profile()
        verifier = CoverageScopeAuthorityVerifier.from_external_root(b"y" * 32)
        bridge_dir = root / "bridge"
        checkpoint_dir = root / "checkpoint"
        materialize_diagnostic_structural_scope(
            manifest,
            bridge_dir=bridge_dir,
            checkpoint_dir=checkpoint_dir,
            created_at=_CREATED_AT,
            export_root=export_root,
            full_scope_source_asset_id=manifest.source_asset_id,
            full_scope_source_fingerprint=manifest.source_fingerprint,
            shard_batch_size=1,
            reader_uid=os.getuid(),
            reader_gid=os.getgid(),
            scope_authority_verifier=verifier,
            semantic_profile=profile,
        )
        return manifest, profile, verifier, bridge_dir, checkpoint_dir

    def _thin_topology_templates(
        self,
        *,
        bridge_dir: Path,
        profile: DiagnosticSemanticProfile,
        verifier: CoverageScopeAuthorityVerifier,
    ) -> tuple[object, ...]:
        store = FileDiagnosticStructuralShardStore(bridge_dir, create=False)
        aggregate = store.load_complete_manifest()
        baseline_templates = diagnostic_mcp.prepare_prevalidated_semantic_shard_templates(
            aggregate=aggregate,
            bundles=tuple(
                store.iter_bundles(
                    aggregate,
                    scope_authority_verifier=verifier,
                )
            ),
            profile=profile,
            scope_authority_verifier=verifier,
        )
        templates = []
        for baseline_template in baseline_templates:
            observation = baseline_template.baseline_scope.structural_observations[0]
            row = observation.rows[0]
            malformed_observation = replace(
                observation,
                rows=(
                    replace(
                        row,
                        cells=(
                            replace(
                                row.cells[0],
                                row_ordinal=row.row_ordinal + 1,
                            ),
                            *row.cells[1:],
                        ),
                    ),
                    *observation.rows[1:],
                ),
            )
            templates.append(
                diagnostic_mcp._prepare_prevalidated_semantic_shard_template(
                    aggregate=aggregate,
                    profile=profile,
                    scope_authority_verifier=verifier,
                    shard_record=baseline_template.shard_record,
                    baseline_scope=replace(
                        baseline_template.baseline_scope,
                        structural_observations=(malformed_observation,),
                    ),
                )
            )
        return tuple(templates)

    def _mutate_first_bundle_and_republish_aggregate(
        self,
        *,
        store: FileDiagnosticStructuralShardStore,
        mutate_payload: object,
    ) -> DiagnosticStructuralAggregateManifest:
        aggregate = store.load_complete_manifest()
        record = aggregate.shards[0]
        bundle_path = store.unique_bundle_path(record.ordinal)
        self.assertIsNotNone(bundle_path)
        assert bundle_path is not None
        payload = json.loads(bundle_path.read_text(encoding="utf-8"))
        mutate_payload(payload)
        bundle_path.write_text(
            json.dumps(payload, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )
        os.chmod(bundle_path, 0o600)
        changed_record = replace(record, bundle_fingerprint=sha256_file(bundle_path))
        changed_aggregate = _rebuild_aggregate(
            aggregate,
            shards=(changed_record, *aggregate.shards[1:]),
        )
        _write_private_aggregate(store, changed_aggregate)
        return changed_aggregate

    def _assert_runtime_denies_before_grounding(
        self,
        *,
        bridge_dir: Path,
        profile: DiagnosticSemanticProfile,
        verifier: CoverageScopeAuthorityVerifier,
    ) -> None:
        with (
            patch(
                "formowl_mail.diagnostic_mcp." "PermissionFirstSemanticPlanner.ground_all_matching"
            ) as grounding,
            patch("formowl_mail.diagnostic_mcp." "execute_authorized_structured_set") as execution,
        ):
            result = _runtime(
                bridge_dir,
                profile=profile,
                verifier=verifier,
            ).execute_semantic_request(_semantic_request())
        self.assertEqual(result["status"], "insufficient")
        grounding.assert_not_called()
        execution.assert_not_called()

    def test_attachment_text_split_is_recomputed_and_checkpoint_republish_skips_parser(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, profile, verifier, bridge_dir, checkpoint_dir = (
                self._materialize_with_text_attachment(root)
            )
            store = FileDiagnosticStructuralShardStore(bridge_dir, create=False)
            aggregate = store.load_complete_manifest()

            self.assertEqual(aggregate.expected_body_segment_count, 1)
            self.assertEqual(aggregate.materialized_message_body_segment_count, 1)
            self.assertEqual(aggregate.materialized_attachment_text_segment_count, 1)
            self.assertEqual(aggregate.materialized_body_segment_count, 2)

            store.aggregate_manifest_path.unlink()
            with (
                patch(
                    "formowl_mail.diagnostic_structural_bridge."
                    "produce_diagnostic_structural_bridge",
                    side_effect=AssertionError("checkpoint republish must not reparse a bundle"),
                ),
                patch(
                    "formowl_mail.diagnostic_structural_bridge." "_validated_shard_record",
                    side_effect=AssertionError(
                        "complete checkpoint republish must not fully revalidate a bundle"
                    ),
                ),
            ):
                publication = materialize_diagnostic_structural_scope(
                    manifest,
                    bridge_dir=bridge_dir,
                    checkpoint_dir=checkpoint_dir,
                    created_at=_CREATED_AT,
                    export_root=root / "export",
                    full_scope_source_asset_id=manifest.source_asset_id,
                    full_scope_source_fingerprint=manifest.source_fingerprint,
                    shard_batch_size=1,
                    reader_uid=os.getuid(),
                    reader_gid=os.getgid(),
                    scope_authority_verifier=verifier,
                    semantic_profile=profile,
                )
            self.assertTrue(publication.aggregate_created)
            republished = store.load_complete_manifest()
            self.assertEqual(republished, aggregate)

    def test_semantic_time_uses_evidence_known_time_and_keeps_source_time_strict(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, profile, verifier, bridge_dir, _ = self._materialize(root)
            store = FileDiagnosticStructuralShardStore(bridge_dir, create=False)
            aggregate = store.load_complete_manifest()
            bundle = next(
                store.iter_bundles(
                    aggregate,
                    scope_authority_verifier=verifier,
                )
            )
            original = bundle.structural_observations[0]
            without_source_world_time = replace(original, observed_at=None)
            missing_source_time_bundle = replace(
                bundle,
                structural_observations=[
                    without_source_world_time,
                    *bundle.structural_observations[1:],
                ],
            )

            self.assertTrue(
                _semantic_evidence_time_admissible(
                    profile=profile,
                    bundle=missing_source_time_bundle,
                    version_manifests=missing_source_time_bundle.version_manifests,
                    structural_observations=missing_source_time_bundle.structural_observations,
                )
            )
            validate_diagnostic_semantic_profile_binding(
                profile=profile,
                bundles=(missing_source_time_bundle,),
                scope_authority_verifier=verifier,
            )

            invalid_source_time_bundle = replace(
                bundle,
                structural_observations=[
                    replace(original, observed_at="not-an-instant"),
                    *bundle.structural_observations[1:],
                ],
            )
            future_source_time_bundle = replace(
                bundle,
                structural_observations=[
                    replace(
                        original,
                        observed_at=_offset_timestamp(
                            bundle.mail_parse_run.completed_at,
                            seconds=1,
                        ),
                    ),
                    *bundle.structural_observations[1:],
                ],
            )
            stale_profile = _profile(
                known_as_of=_offset_timestamp(_CREATED_AT, seconds=-1),
            )
            source_after_profile_cutoff_bundle = replace(
                bundle,
                structural_observations=[
                    replace(
                        original,
                        observed_at=_offset_timestamp(
                            stale_profile.known_as_of,
                            seconds=1,
                        ),
                    ),
                    *bundle.structural_observations[1:],
                ],
            )

            self.assertFalse(
                _semantic_evidence_time_admissible(
                    profile=profile,
                    bundle=invalid_source_time_bundle,
                    version_manifests=invalid_source_time_bundle.version_manifests,
                    structural_observations=invalid_source_time_bundle.structural_observations,
                )
            )
            self.assertFalse(
                _semantic_evidence_time_admissible(
                    profile=profile,
                    bundle=future_source_time_bundle,
                    version_manifests=future_source_time_bundle.version_manifests,
                    structural_observations=future_source_time_bundle.structural_observations,
                )
            )
            self.assertFalse(
                _semantic_evidence_time_admissible(
                    profile=stale_profile,
                    bundle=source_after_profile_cutoff_bundle,
                    version_manifests=source_after_profile_cutoff_bundle.version_manifests,
                    structural_observations=(
                        source_after_profile_cutoff_bundle.structural_observations
                    ),
                )
            )
            self.assertTrue(
                _semantic_evidence_time_admissible(
                    profile=stale_profile,
                    bundle=bundle,
                    version_manifests=bundle.version_manifests,
                    structural_observations=bundle.structural_observations,
                )
            )

    def test_complete_checkpoint_fast_republish_skips_full_shard_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, profile, verifier, bridge_dir, checkpoint_dir = self._materialize(root)
            store = FileDiagnosticStructuralShardStore(bridge_dir, create=False)
            store.aggregate_manifest_path.unlink()

            with (
                patch(
                    "formowl_mail.diagnostic_structural_bridge."
                    "produce_diagnostic_structural_bridge",
                    side_effect=AssertionError("checkpoint republish must not produce a bundle"),
                ),
                patch(
                    "formowl_mail.diagnostic_structural_bridge." "_validated_shard_record",
                    side_effect=AssertionError(
                        "checkpoint republish must not fully validate a bundle"
                    ),
                ),
            ):
                publication = materialize_diagnostic_structural_scope(
                    manifest,
                    bridge_dir=bridge_dir,
                    checkpoint_dir=checkpoint_dir,
                    created_at=_CREATED_AT,
                    export_root=root / "export",
                    full_scope_source_asset_id=manifest.source_asset_id,
                    full_scope_source_fingerprint=manifest.source_fingerprint,
                    shard_batch_size=1,
                    reader_uid=os.getuid(),
                    reader_gid=os.getgid(),
                    scope_authority_verifier=verifier,
                    semantic_profile=profile,
                )

            self.assertTrue(publication.aggregate_created)
            self.assertEqual(
                store.load_complete_manifest().aggregate_manifest_id,
                publication.aggregate_manifest_id,
            )

    def test_incomplete_or_invalid_checkpoint_set_does_not_use_fast_republish(self) -> None:
        cases = {
            "malformed_checkpoint": "shard checkpoint is invalid",
            "out_of_sequence_checkpoint": "checkpoint is out of sequence",
            "bundle_hash_drift": "checkpoint does not match bundle",
        }
        for case, expected_error in cases.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                manifest, profile, verifier, bridge_dir, checkpoint_dir = self._materialize(root)
                store = FileDiagnosticStructuralShardStore(bridge_dir, create=False)
                store.aggregate_manifest_path.unlink()
                checkpoint_path = checkpoint_dir / "shard-checkpoints.private" / "00000000.json"

                if case == "malformed_checkpoint":
                    checkpoint_path.write_text("{}", encoding="utf-8")
                    os.chmod(checkpoint_path, 0o600)
                elif case == "out_of_sequence_checkpoint":
                    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                    payload["ordinal"] = 1
                    checkpoint_path.write_text(
                        json.dumps(payload, separators=(",", ":"), sort_keys=True),
                        encoding="utf-8",
                    )
                    os.chmod(checkpoint_path, 0o600)
                else:
                    bundle_path = store.unique_bundle_path(0)
                    self.assertIsNotNone(bundle_path)
                    assert bundle_path is not None
                    bundle_path.write_bytes(bundle_path.read_bytes() + b"\n")

                with (
                    patch(
                        "formowl_mail.diagnostic_structural_bridge."
                        "produce_diagnostic_structural_bridge",
                        side_effect=AssertionError(
                            "an existing checkpoint-bound shard must not be replaced"
                        ),
                    ),
                    self.assertRaisesRegex(ValueError, expected_error),
                ):
                    materialize_diagnostic_structural_scope(
                        manifest,
                        bridge_dir=bridge_dir,
                        checkpoint_dir=checkpoint_dir,
                        created_at=_CREATED_AT,
                        export_root=root / "export",
                        full_scope_source_asset_id=manifest.source_asset_id,
                        full_scope_source_fingerprint=manifest.source_fingerprint,
                        shard_batch_size=1,
                        reader_uid=os.getuid(),
                        reader_gid=os.getgid(),
                        scope_authority_verifier=verifier,
                        semantic_profile=profile,
                    )
                self.assertFalse(store.aggregate_manifest_path.exists())

    def test_missing_or_unknown_body_segment_source_type_denies_before_grounding(self) -> None:
        for mutation in ("missing", "unknown"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _, profile, verifier, bridge_dir, _ = self._materialize(root)
                store = FileDiagnosticStructuralShardStore(bridge_dir, create=False)

                def mutate(payload: dict[str, object]) -> None:
                    segments = payload["body_segments"]
                    assert isinstance(segments, list)
                    segment = segments[0]
                    assert isinstance(segment, dict)
                    if mutation == "missing":
                        segment.pop("segment_source_type")
                    else:
                        segment["segment_source_type"] = "future_body_segment_source"

                self._mutate_first_bundle_and_republish_aggregate(
                    store=store,
                    mutate_payload=mutate,
                )
                self._assert_runtime_denies_before_grounding(
                    bridge_dir=bridge_dir,
                    profile=profile,
                    verifier=verifier,
                )

    def test_attachment_text_requires_matching_attachment_and_message_occurrence(self) -> None:
        for mutation in ("attachment", "message"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _, profile, verifier, bridge_dir, _ = self._materialize_with_text_attachment(root)
                store = FileDiagnosticStructuralShardStore(bridge_dir, create=False)

                def mutate(payload: dict[str, object]) -> None:
                    segments = payload["body_segments"]
                    assert isinstance(segments, list)
                    attachment_segment = next(
                        segment
                        for segment in segments
                        if isinstance(segment, dict)
                        and segment.get("segment_source_type") == "attachment_text"
                    )
                    assert isinstance(attachment_segment, dict)
                    if mutation == "attachment":
                        attachment_segment["attachment_id"] = "attachment_missing"
                    else:
                        attachment_segment["message_occurrence_id"] = "message_missing"

                self._mutate_first_bundle_and_republish_aggregate(
                    store=store,
                    mutate_payload=mutate,
                )
                self._assert_runtime_denies_before_grounding(
                    bridge_dir=bridge_dir,
                    profile=profile,
                    verifier=verifier,
                )

    def test_reclassified_message_body_and_forged_ancillary_count_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, profile, verifier, bridge_dir, _ = self._materialize_with_text_attachment(root)
            store = FileDiagnosticStructuralShardStore(bridge_dir, create=False)

            def reclassify(payload: dict[str, object]) -> None:
                segments = payload["body_segments"]
                assert isinstance(segments, list)
                attachment_segment = next(
                    segment
                    for segment in segments
                    if isinstance(segment, dict)
                    and segment.get("segment_source_type") == "attachment_text"
                )
                message_segment = next(
                    segment
                    for segment in segments
                    if isinstance(segment, dict)
                    and segment.get("segment_source_type") == "message_body"
                )
                assert isinstance(attachment_segment, dict)
                assert isinstance(message_segment, dict)
                message_segment["segment_source_type"] = "attachment_text"
                message_segment["attachment_id"] = attachment_segment["attachment_id"]

            reclassified_aggregate = self._mutate_first_bundle_and_republish_aggregate(
                store=store,
                mutate_payload=reclassify,
            )
            self._assert_runtime_denies_before_grounding(
                bridge_dir=bridge_dir,
                profile=profile,
                verifier=verifier,
            )

            # Rebuild a syntactically coherent aggregate with a false split:
            # its total remains unchanged, but loader-side recomputation must
            # reject declared ancillary counts before semantic grounding.
            forged = _rebuild_aggregate(
                reclassified_aggregate,
                expected_body_segment_count=2,
                materialized_message_body_segment_count=2,
                materialized_attachment_text_segment_count=0,
            )
            _write_private_aggregate(store, forged)
            with self.assertRaisesRegex(ValueError, "body segment accounting is inconsistent"):
                store.load_complete_manifest()

    def test_historical_compatibility_uses_checkpoint_coverage_despite_identity_and_body_drift(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current_manifest, profile, verifier, bridge_dir, checkpoint_dir = self._prepare(
                root,
                projected_values=("Alpha", "Beta"),
            )
            historical_manifest = _historical_manifest_with_projection_drift(current_manifest)
            scope_manifest_path = root / "historical-scope.private.json"
            compatibility_path = root / "historical-compatibility.private.json"
            write_diagnostic_structural_scope_manifest(
                historical_manifest,
                scope_manifest_path,
            )
            _write_historical_compatibility_checkpoint(
                path=compatibility_path,
                scope_manifest_path=scope_manifest_path,
                manifest=historical_manifest,
                selected_paths=("01.eml", "02.eml"),
            )
            (root / "export" / "extra.eml").write_bytes(
                _message("unselected-current@example.test", "Gamma")
            )

            publication = materialize_diagnostic_structural_scope(
                historical_manifest,
                bridge_dir=bridge_dir,
                checkpoint_dir=checkpoint_dir,
                created_at=_CREATED_AT,
                export_root=root / "export",
                full_scope_source_asset_id=historical_manifest.source_asset_id,
                full_scope_source_fingerprint=historical_manifest.source_fingerprint,
                shard_batch_size=1,
                reader_uid=os.getuid(),
                reader_gid=os.getgid(),
                scope_authority_verifier=verifier,
                semantic_profile=profile,
                historical_compatibility_checkpoint=compatibility_path,
                scope_manifest_path=scope_manifest_path,
            )
            aggregate = FileDiagnosticStructuralShardStore(
                bridge_dir,
                create=False,
            ).load_complete_manifest()

        self.assertTrue(publication.aggregate_created)
        self.assertEqual(aggregate.expected_message_count, 2)
        self.assertEqual(aggregate.selected_top_level_message_count, 2)
        self.assertEqual(aggregate.materialized_message_occurrence_count, 2)
        self.assertNotEqual(
            aggregate.expected_body_segment_count,
            aggregate.materialized_body_segment_count,
        )
        self.assertIsNotNone(aggregate.historical_compatibility_checkpoint_fingerprint)
        self.assertEqual(
            aggregate.existing_export_verification.export_message_file_count,
            3,
        )
        self.assertEqual(
            aggregate.existing_export_verification.parsed_export_message_count,
            2,
        )
        self.assertEqual(
            aggregate.existing_export_verification.nonparsed_export_message_count,
            1,
        )

    def test_historical_compatibility_excludes_embedded_structural_rows_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            export_root = root / "export"
            export_root.mkdir()
            (export_root / "top.eml").write_bytes(
                _message_with_embedded_table(
                    message_id="top@example.test",
                    projected_value="Alpha",
                    embedded_message_id="child@example.test",
                    embedded_projected_value="Beta",
                )
            )
            manifest = _scope_manifest(export_root)
            profile = _profile()
            verifier = CoverageScopeAuthorityVerifier.from_external_root(b"x" * 32)
            bridge_dir = root / "historical-bridge"
            checkpoint_dir = root / "historical-checkpoint"
            scope_manifest_path = root / "scope.private.json"
            compatibility_path = root / "compatibility.private.json"
            write_diagnostic_structural_scope_manifest(manifest, scope_manifest_path)
            _write_historical_compatibility_checkpoint(
                path=compatibility_path,
                scope_manifest_path=scope_manifest_path,
                manifest=manifest,
                selected_paths=("top.eml",),
            )

            materialize_diagnostic_structural_scope(
                manifest,
                bridge_dir=bridge_dir,
                checkpoint_dir=checkpoint_dir,
                created_at=_CREATED_AT,
                export_root=export_root,
                full_scope_source_asset_id=manifest.source_asset_id,
                full_scope_source_fingerprint=manifest.source_fingerprint,
                shard_batch_size=1,
                reader_uid=os.getuid(),
                reader_gid=os.getgid(),
                scope_authority_verifier=verifier,
                semantic_profile=profile,
                historical_compatibility_checkpoint=compatibility_path,
                scope_manifest_path=scope_manifest_path,
            )
            shard_store = FileDiagnosticStructuralShardStore(bridge_dir, create=False)
            aggregate = shard_store.load_complete_manifest()
            historical_bundle = next(
                shard_store.iter_bundles(
                    aggregate,
                    scope_authority_verifier=verifier,
                )
            )
            top_level_lineage_ids = {
                str(item.location["source_local_key"])
                for item in historical_bundle.source_inventory[0].items
                if item.structure_kind == "exported_message_occurrence"
            }
            child_result = _runtime(
                bridge_dir,
                profile=profile,
                verifier=verifier,
            ).execute_semantic_request(
                _semantic_request(
                    predicate_mention="code",
                    value_mention="item beta",
                )
            )
            top_result = _runtime(
                bridge_dir,
                profile=profile,
                verifier=verifier,
            ).execute_semantic_request(
                _semantic_request(
                    predicate_mention="code",
                    value_mention="item alpha",
                )
            )
            ordinary_publication = produce_diagnostic_structural_bridge(
                export_root=export_root,
                selected_message_paths=("top.eml",),
                bridge_dir=root / "ordinary-bridge",
                source_asset_id=manifest.source_asset_id,
                source_fingerprint=manifest.source_fingerprint,
                workspace_id=manifest.workspace_id,
                owner_user_id=manifest.owner_user_id,
                permission_scope=manifest.permission_scope,
                created_at=_CREATED_AT,
                scope_authority_verifier=verifier,
                semantic_profile=profile,
            )
            ordinary_bundle = FileMailEvidenceBundleStore._read(ordinary_publication.bundle_path)

        self.assertEqual(aggregate.selected_top_level_message_count, 1)
        self.assertEqual(aggregate.materialized_message_occurrence_count, 2)
        self.assertEqual(aggregate.shards[0].embedded_message_occurrence_count, 1)
        self.assertEqual(len(historical_bundle.message_occurrences), 2)
        self.assertEqual(
            {
                observation.message_lineage_id
                for observation in historical_bundle.structural_observations
            },
            top_level_lineage_ids,
        )
        self.assertEqual(len(historical_bundle.structural_observations), 1)
        self.assertEqual(child_result["status"], "ok")
        self.assertEqual(
            child_result["claim_state"],
            "NOT_FOUND_WITHIN_COMPLETE_SCOPE",
        )
        self.assertEqual(child_result["complete_projection"]["values"], [])
        self.assertEqual(top_result["status"], "ok")
        self.assertEqual(top_result["claim_state"], "FOUND")
        self.assertEqual(
            top_result["complete_projection"]["values"],
            [{"values": ["Alpha"]}],
        )
        self.assertEqual(len(ordinary_bundle.structural_observations), 2)
        ordinary_lineage_ids = {
            observation.message_lineage_id
            for observation in ordinary_bundle.structural_observations
        }
        self.assertTrue(
            top_level_lineage_ids < ordinary_lineage_ids,
        )

    def test_historical_compatibility_resume_rejects_changed_checkpoint_fingerprint(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current_manifest, profile, verifier, bridge_dir, checkpoint_dir = self._prepare(root)
            historical_manifest = _historical_manifest_with_projection_drift(current_manifest)
            scope_manifest_path = root / "historical-scope.private.json"
            initial_checkpoint = root / "initial.private.json"
            changed_checkpoint = root / "changed.private.json"
            write_diagnostic_structural_scope_manifest(
                historical_manifest,
                scope_manifest_path,
            )
            _write_historical_compatibility_checkpoint(
                path=initial_checkpoint,
                scope_manifest_path=scope_manifest_path,
                manifest=historical_manifest,
                selected_paths=("01.eml", "02.eml"),
            )
            materialize_diagnostic_structural_scope(
                historical_manifest,
                bridge_dir=bridge_dir,
                checkpoint_dir=checkpoint_dir,
                created_at=_CREATED_AT,
                export_root=root / "export",
                full_scope_source_asset_id=historical_manifest.source_asset_id,
                full_scope_source_fingerprint=historical_manifest.source_fingerprint,
                shard_batch_size=1,
                reader_uid=os.getuid(),
                reader_gid=os.getgid(),
                scope_authority_verifier=verifier,
                semantic_profile=profile,
                historical_compatibility_checkpoint=initial_checkpoint,
                scope_manifest_path=scope_manifest_path,
            )
            _write_historical_compatibility_checkpoint(
                path=changed_checkpoint,
                scope_manifest_path=scope_manifest_path,
                manifest=historical_manifest,
                selected_paths=("01.eml", "02.eml"),
                legacy_parser_sha256="sha256:" + "e" * 64,
            )

            with self.assertRaisesRegex(
                ValueError,
                "checkpoint compatibility binding is invalid",
            ):
                materialize_diagnostic_structural_scope(
                    historical_manifest,
                    bridge_dir=bridge_dir,
                    checkpoint_dir=checkpoint_dir,
                    created_at=_CREATED_AT,
                    export_root=root / "export",
                    full_scope_source_asset_id=historical_manifest.source_asset_id,
                    full_scope_source_fingerprint=historical_manifest.source_fingerprint,
                    shard_batch_size=1,
                    reader_uid=os.getuid(),
                    reader_gid=os.getgid(),
                    scope_authority_verifier=verifier,
                    semantic_profile=profile,
                    historical_compatibility_checkpoint=changed_checkpoint,
                    scope_manifest_path=scope_manifest_path,
                )

    def test_selected_top_level_inventory_accepts_r22_message_topology_without_kind(
        self,
    ) -> None:
        selected_path = "01.eml"
        source_key = "file:" + hashlib.sha256(selected_path.encode("utf-8")).hexdigest()[:24]
        top_level_id = "top_level_occurrence"
        bundle = SimpleNamespace(
            source_inventory=(
                SimpleNamespace(
                    items=(
                        SimpleNamespace(
                            structure_kind="exported_file",
                            processing_state="parsed",
                            content_type="message/rfc822",
                            location={
                                "source_local_key": source_key,
                            },
                        ),
                        SimpleNamespace(
                            structure_kind="exported_message_occurrence",
                            processing_state="parsed",
                            location={
                                "source_local_key": f"{source_key}:message",
                                "parent_source_local_key": source_key,
                                "message_occurrence_id": top_level_id,
                            },
                        ),
                    )
                ),
            )
        )
        selected_top_level_ids = _selected_top_level_message_occurrence_ids(
            bundle,
            selected_paths=(selected_path,),
        )
        current_parser_occurrence_ids = {*selected_top_level_ids, "embedded_occurrence"}

        self.assertEqual(selected_top_level_ids, {top_level_id})
        self.assertEqual(len(current_parser_occurrence_ids) - len(selected_top_level_ids), 1)

    def test_selected_top_level_inventory_rejects_attachment_and_ambiguous_topology(
        self,
    ) -> None:
        selected_path = "01.eml"
        source_key = "file:" + hashlib.sha256(selected_path.encode("utf-8")).hexdigest()[:24]

        def bundle(
            *,
            content_type: str = "message/rfc822",
            message_kind: str = "exported_message_occurrence",
            parent_source_local_key: str | None = None,
            duplicate_file: bool = False,
        ) -> SimpleNamespace:
            file_item = SimpleNamespace(
                structure_kind="exported_file",
                processing_state="parsed",
                content_type=content_type,
                location={"source_local_key": source_key},
            )
            items = [file_item]
            if duplicate_file:
                items.append(
                    SimpleNamespace(
                        structure_kind="exported_file",
                        processing_state="parsed",
                        content_type="message/rfc822",
                        location={"source_local_key": source_key},
                    )
                )
            items.append(
                SimpleNamespace(
                    structure_kind=message_kind,
                    processing_state="parsed",
                    content_type="message/rfc822",
                    location={
                        "source_local_key": f"{source_key}:message",
                        "parent_source_local_key": (
                            source_key
                            if parent_source_local_key is None
                            else parent_source_local_key
                        ),
                        "message_occurrence_id": "top_level_occurrence",
                    },
                )
            )
            return SimpleNamespace(source_inventory=(SimpleNamespace(items=tuple(items)),))

        invalid_cases = {
            "non_message_file": bundle(content_type="text/plain"),
            "attached_message": bundle(message_kind="attached_message_occurrence"),
            "wrong_parent": bundle(parent_source_local_key=f"{source_key}:attachment:0"),
            "duplicate_exported_file": bundle(duplicate_file=True),
        }
        for name, candidate in invalid_cases.items():
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "top-level|ambiguous"):
                _selected_top_level_message_occurrence_ids(
                    candidate,
                    selected_paths=(selected_path,),
                )

    def test_selected_top_level_inventory_rejects_malformed_relevant_source_key(
        self,
    ) -> None:
        selected_path = "01.eml"
        source_key = "file:" + hashlib.sha256(selected_path.encode("utf-8")).hexdigest()[:24]

        valid_items = (
            SimpleNamespace(
                structure_kind="exported_file",
                processing_state="parsed",
                content_type="message/rfc822",
                location={
                    "source_local_key": source_key,
                    "source_unit_kind": "message",
                },
            ),
            SimpleNamespace(
                structure_kind="exported_message_occurrence",
                processing_state="parsed",
                content_type="message/rfc822",
                location={
                    "source_local_key": f"{source_key}:message",
                    "parent_source_local_key": source_key,
                    "message_occurrence_id": "top_level_occurrence",
                },
            ),
        )
        malformed_cases = {
            "missing_extra_occurrence_key": SimpleNamespace(
                structure_kind="exported_message_occurrence",
                processing_state="parsed",
                content_type="message/rfc822",
                location={
                    "parent_source_local_key": source_key,
                    "message_occurrence_id": "malformed_occurrence",
                },
            ),
            "non_string_extra_file_key": SimpleNamespace(
                structure_kind="exported_file",
                processing_state="unsupported",
                content_type="application/octet-stream",
                location={
                    "source_local_key": 7,
                    "source_unit_kind": "sidecar",
                },
            ),
        }
        for name, malformed_item in malformed_cases.items():
            candidate = SimpleNamespace(
                source_inventory=(SimpleNamespace(items=(*valid_items, malformed_item)),)
            )
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(
                    ValueError,
                    "top-level source binding is invalid",
                ),
            ):
                _selected_top_level_message_occurrence_ids(
                    candidate,
                    selected_paths=(selected_path,),
                )

    def test_selected_top_level_inventory_accepts_closed_ancillary_states(self) -> None:
        selected_path = "01.eml"
        source_key = "file:" + hashlib.sha256(selected_path.encode("utf-8")).hexdigest()[:24]
        ancillary_key = "file:" + hashlib.sha256(b"01-sidecar").hexdigest()[:24]

        for source_unit_kind, processing_state in (
            ("sidecar", "unsupported"),
            ("attachment", "preserved_unparsed"),
        ):
            candidate = SimpleNamespace(
                source_inventory=(
                    SimpleNamespace(
                        items=(
                            SimpleNamespace(
                                structure_kind="exported_file",
                                processing_state="parsed",
                                content_type="message/rfc822",
                                location={
                                    "source_local_key": source_key,
                                    "source_unit_kind": "message",
                                },
                            ),
                            SimpleNamespace(
                                structure_kind="exported_message_occurrence",
                                processing_state="parsed",
                                content_type="message/rfc822",
                                location={
                                    "source_local_key": f"{source_key}:message",
                                    "parent_source_local_key": source_key,
                                    "message_occurrence_id": "top_level_occurrence",
                                },
                            ),
                            SimpleNamespace(
                                structure_kind="exported_file",
                                processing_state=processing_state,
                                content_type="application/octet-stream",
                                location={
                                    "source_local_key": ancillary_key,
                                    "source_unit_kind": source_unit_kind,
                                },
                            ),
                        )
                    ),
                )
            )

            with self.subTest(
                source_unit_kind=source_unit_kind,
                processing_state=processing_state,
            ):
                self.assertEqual(
                    _selected_top_level_message_occurrence_ids(
                        candidate,
                        selected_paths=(selected_path,),
                    ),
                    {"top_level_occurrence"},
                )

    def test_selected_top_level_inventory_rejects_unknown_or_failed_ancillary_source(
        self,
    ) -> None:
        selected_path = "01.eml"
        source_key = "file:" + hashlib.sha256(selected_path.encode("utf-8")).hexdigest()[:24]
        sidecar_key = "file:" + hashlib.sha256(b"01.size").hexdigest()[:24]

        def bundle(*, source_unit_kind: str, processing_state: str) -> SimpleNamespace:
            return SimpleNamespace(
                source_inventory=(
                    SimpleNamespace(
                        items=(
                            SimpleNamespace(
                                structure_kind="exported_file",
                                processing_state="parsed",
                                content_type="message/rfc822",
                                location={
                                    "source_local_key": source_key,
                                    "source_unit_kind": "message",
                                },
                            ),
                            SimpleNamespace(
                                structure_kind="exported_message_occurrence",
                                processing_state="parsed",
                                content_type="message/rfc822",
                                location={
                                    "source_local_key": f"{source_key}:message",
                                    "parent_source_local_key": source_key,
                                    "message_occurrence_id": "top_level_occurrence",
                                },
                            ),
                            SimpleNamespace(
                                structure_kind="exported_file",
                                processing_state=processing_state,
                                content_type="application/octet-stream",
                                location={
                                    "source_local_key": sidecar_key,
                                    "source_unit_kind": source_unit_kind,
                                },
                            ),
                        )
                    ),
                )
            )

        invalid_cases = {
            "unknown_kind": bundle(
                source_unit_kind="unknown",
                processing_state="unsupported",
            ),
            "failed_sidecar": bundle(
                source_unit_kind="sidecar",
                processing_state="failed",
            ),
            "unrecognized_sidecar": bundle(
                source_unit_kind="sidecar",
                processing_state="unrecognized",
            ),
            "intentionally_excluded_attachment": bundle(
                source_unit_kind="attachment",
                processing_state="intentionally_excluded",
            ),
        }
        for name, candidate in invalid_cases.items():
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(
                    ValueError,
                    "top-level source binding is invalid",
                ),
            ):
                _selected_top_level_message_occurrence_ids(
                    candidate,
                    selected_paths=(selected_path,),
                )

    def test_batches_are_deterministic_for_different_source_order(self) -> None:
        first = _deterministic_path_batches(
            ("c.eml", "a.eml", "b.eml"),
            shard_batch_size=2,
        )
        second = _deterministic_path_batches(
            ("b.eml", "c.eml", "a.eml"),
            shard_batch_size=2,
        )

        self.assertEqual(first, second)
        self.assertEqual(first, (("a.eml", "b.eml"), ("c.eml",)))

    def test_memory_plan_accounts_for_whole_shard_payload_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, _, _, _, _ = self._prepare(
                root,
                projected_values=("Alpha", "Beta"),
            )
            one_message = plan_diagnostic_structural_materialization(
                manifest,
                export_root=root / "export",
                full_scope_source_asset_id=manifest.source_asset_id,
                full_scope_source_fingerprint=manifest.source_fingerprint,
                shard_batch_size=1,
            )
            two_messages = plan_diagnostic_structural_materialization(
                manifest,
                export_root=root / "export",
                full_scope_source_asset_id=manifest.source_asset_id,
                full_scope_source_fingerprint=manifest.source_fingerprint,
                shard_batch_size=2,
            )

        self.assertGreaterEqual(
            two_messages.estimated_peak_memory_bytes - one_message.estimated_peak_memory_bytes,
            2 * 25 * 1024 * 1024,
        )

    def test_current_export_native_scope_is_private_and_skips_selector_rescan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            export_root = root / "export"
            (export_root / "Inbox").mkdir(parents=True)
            (export_root / "Inbox" / "001.eml").write_bytes(_message("first@test", "Alpha"))
            (export_root / "Inbox" / "002.eml").write_bytes(_message("second@test", "Beta"))
            scope = build_diagnostic_current_export_native_scope(
                export_root=export_root,
                source_asset_id="asset_synthetic",
                source_fingerprint=_SOURCE_FINGERPRINT,
                workspace_id="workspace_synthetic",
                owner_user_id="user_synthetic",
                permission_scope=_PERMISSION_SCOPE,
                created_at=_CREATED_AT,
            )
            scope_dir = root / "native-scope.private"
            manifest_path, selection_path = write_diagnostic_current_export_native_scope(
                scope,
                scope_dir,
            )
            manifest = load_diagnostic_structural_scope_manifest(manifest_path)
            checkpoint = load_diagnostic_current_export_native_selection_checkpoint(
                selection_path,
                manifest=manifest,
                scope_manifest_path=manifest_path,
                parser_worker_count=1,
                max_message_file_bytes=25 * 1024 * 1024,
            )
            self.assertEqual(manifest, scope.manifest)
            self.assertEqual(checkpoint, scope.selection_checkpoint)
            self.assertEqual(oct(scope_dir.stat().st_mode & 0o777), "0o700")
            self.assertEqual(oct(manifest_path.stat().st_mode & 0o777), "0o600")
            self.assertEqual(oct(selection_path.stat().st_mode & 0o777), "0o600")

            bridge_dir = root / "bridge"
            checkpoint_dir = root / "materialization"
            verifier = CoverageScopeAuthorityVerifier.from_external_root(b"n" * 32)
            with patch(
                "formowl_mail.diagnostic_structural_bridge." "select_readpst_export_messages",
                side_effect=AssertionError("native checkpoint must skip selector rescan"),
            ):
                publication = materialize_diagnostic_structural_scope(
                    manifest,
                    bridge_dir=bridge_dir,
                    checkpoint_dir=checkpoint_dir,
                    created_at=_CREATED_AT,
                    export_root=export_root,
                    full_scope_source_asset_id=manifest.source_asset_id,
                    full_scope_source_fingerprint=manifest.source_fingerprint,
                    native_selection_checkpoint=selection_path,
                    scope_manifest_path=manifest_path,
                    shard_batch_size=1,
                    reader_uid=os.getuid(),
                    reader_gid=os.getgid(),
                    scope_authority_verifier=verifier,
                    semantic_profile=_profile(),
                )

        self.assertEqual(publication.selected_export_message_count, 2)
        self.assertEqual(publication.pst_scan_count, 0)
        self.assertEqual(publication.existing_export_verification.export_message_file_count, 2)

    def test_current_export_native_scope_rejects_parser_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            export_root = Path(temporary) / "export"
            export_root.mkdir()
            with (
                patch(
                    "formowl_mail.diagnostic_structural_bridge.extract_readpst_export",
                    return_value=SimpleNamespace(
                        errors=["pst_parser_failed"],
                        source_inventory=None,
                        observations=[],
                    ),
                ),
                self.assertRaisesRegex(ValueError, "parser reported errors"),
            ):
                build_diagnostic_current_export_native_scope(
                    export_root=export_root,
                    source_asset_id="asset_synthetic",
                    source_fingerprint=_SOURCE_FINGERPRINT,
                    workspace_id="workspace_synthetic",
                    owner_user_id="user_synthetic",
                    permission_scope=_PERMISSION_SCOPE,
                    created_at=_CREATED_AT,
                )

    def test_current_export_native_scope_excludes_unsupported_sidecar_from_message_coverage(
        self,
    ) -> None:
        """A complete message export may also preserve non-message sidecars."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            export_root = root / "export"
            export_root.mkdir()
            (export_root / "001.eml").write_bytes(_message("top@test", "Alpha"))
            (export_root / "001.size").write_bytes(b"synthetic sidecar")

            scope = build_diagnostic_current_export_native_scope(
                export_root=export_root,
                source_asset_id="asset_synthetic",
                source_fingerprint=_SOURCE_FINGERPRINT,
                workspace_id="workspace_synthetic",
                owner_user_id="user_synthetic",
                permission_scope=_PERMISSION_SCOPE,
                created_at=_CREATED_AT,
            )

        self.assertEqual(scope.selection_checkpoint.selected_message_paths, ("001.eml",))
        self.assertEqual(scope.selection_checkpoint.scanned_message_count, 1)
        self.assertEqual(scope.manifest.expected_message_count, 1)

    def test_current_export_native_scope_rejects_missing_top_level_message_occurrence(
        self,
    ) -> None:
        """A real message source still requires its exact top-level occurrence."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            export_root = root / "export"
            export_root.mkdir()
            (export_root / "001.eml").write_bytes(_message("top@test", "Alpha"))
            original_extract = extract_readpst_export

            def remove_top_level_occurrence(**kwargs: object) -> object:
                result = original_extract(**kwargs)
                inventory = result.source_inventory
                self.assertIsNotNone(inventory)
                unbound_items = []
                for item in inventory.items:
                    if item.structure_kind == "exported_message_occurrence":
                        continue
                    item_values = item.to_persistence_dict()
                    item_values.pop("source_inventory_item_id")
                    item_values["source_inventory_id"] = None
                    unbound_items.append(type(item).create(**item_values))
                missing_occurrence_inventory = SourceInventory.create(
                    source_asset_id=inventory.source_asset_id,
                    source_fingerprint=inventory.source_fingerprint,
                    parser_fingerprint=inventory.parser_fingerprint,
                    items=unbound_items,
                    created_at=inventory.created_at,
                )
                return SimpleNamespace(
                    errors=result.errors,
                    source_inventory=missing_occurrence_inventory,
                    observations=result.observations,
                )

            with (
                patch(
                    "formowl_mail.diagnostic_structural_bridge.extract_readpst_export",
                    side_effect=remove_top_level_occurrence,
                ),
                self.assertRaisesRegex(ValueError, "top-level source coverage is incomplete"),
            ):
                build_diagnostic_current_export_native_scope(
                    export_root=export_root,
                    source_asset_id="asset_synthetic",
                    source_fingerprint=_SOURCE_FINGERPRINT,
                    workspace_id="workspace_synthetic",
                    owner_user_id="user_synthetic",
                    permission_scope=_PERMISSION_SCOPE,
                    created_at=_CREATED_AT,
                )

    def test_current_export_native_scope_accepts_preserved_unparsed_child_and_blocks_true_failed(
        self,
    ) -> None:
        from formowl_contract import PermissionScope, SourceRef
        from formowl_ingestion.assets import register_asset_from_local_file
        from formowl_ingestion.storage import (
            AssetStore,
            FileObjectStore,
            StorageBackendRegistry,
        )

        with tempfile.TemporaryDirectory() as temporary:
            temp_dir = Path(temporary)
            export_root = temp_dir / "export"
            export_root.mkdir()
            eml_path = export_root / "001.eml"
            eml_path.write_bytes(
                b"From: sender@example.test\n"
                b"To: recipient@example.test\n"
                b"Subject: Synthetic Structural Test\n"
                b"Message-ID: <synthetic1@example.test>\n"
                b"Date: Wed, 05 Aug 2026 00:00:00 +0000\n"
                b"MIME-Version: 1.0\n"
                b'Content-Type: multipart/mixed; boundary="boundary1"\n\n'
                b"--boundary1\n"
                b"Content-Type: text/plain; charset=utf-8\n\n"
                b"Main body text\n"
                b"--boundary1\n"
                b'Content-Type: application/octet-stream; name="data.bin"\n'
                b"Content-Transfer-Encoding: base64\n"
                b'Content-Disposition: attachment; filename="data.bin"\n\n'
                b"INVALID-BASE64-!!!\n"
                b"--boundary1--\n"
            )

            registry = StorageBackendRegistry(temp_dir)
            backend = registry.register_local_backend(
                temp_dir / "object-root",
                workspace_scope="workspace_synthetic",
                storage_backend_id="storage_synthetic",
            )
            object_store = FileObjectStore(registry)
            asset_store = AssetStore(temp_dir)
            asset = register_asset_from_local_file(
                eml_path,
                object_store=object_store,
                asset_store=asset_store,
                storage_backend_id=backend.storage_backend_id,
                workspace_id="workspace_synthetic",
                owner_user_id="user_synthetic",
                permission_scope=PermissionScope.project("project_synthetic"),
                source_ref=SourceRef(
                    source_system="test",
                    source_type="mail",
                    source_id="synthetic_1",
                ),
                mime_type="message/rfc822",
                created_at=_CREATED_AT,
                registered_at=_CREATED_AT,
            )

            # 1. Unmocked real parser execution over synthetic export with semantic-unavailable child
            scope = build_diagnostic_current_export_native_scope(
                export_root=export_root,
                source_asset_id=asset.asset_id,
                source_fingerprint=asset.content_hash,
                workspace_id=asset.workspace_id,
                owner_user_id=asset.owner_user_id,
                permission_scope=asset.permission_scope,
                created_at=_CREATED_AT,
            )
            self.assertIsNotNone(scope)
            self.assertEqual(len(scope.selection_checkpoint.selected_message_paths), 1)

            # Verify inventory child state and commitment
            from formowl_ingestion.extraction import ExtractionInput
            from formowl_ingestion.extractors.mail.pst import extract_readpst_export

            res = extract_readpst_export(
                extraction_input=ExtractionInput(
                    asset=asset,
                    extractor_run_id="run_1",
                    object_path=asset.object_uri,
                    created_at=_CREATED_AT,
                ),
                export_root=export_root,
            )
            inv_items = res.source_inventory.items
            att_items = [
                item for item in inv_items if item.structure_kind == "regular_attachment_occurrence"
            ]
            self.assertEqual(len(att_items), 1)
            att_item = att_items[0]
            self.assertEqual(att_item.processing_state, "preserved_unparsed")
            self.assertEqual(att_item.location.get("attachment_text_extraction_state"), "failed")
            self.assertTrue(att_item.source_fingerprint.startswith("sha256:"))

            # 2. An actual selected-source read failure remains failed and blocks scope.
            original_read_bytes = Path.read_bytes

            def fail_selected_source_read(path: Path) -> bytes:
                if path == eml_path:
                    raise OSError("synthetic selected-source read failure")
                return original_read_bytes(path)

            with patch.object(
                Path,
                "read_bytes",
                autospec=True,
                side_effect=fail_selected_source_read,
            ):
                with self.assertRaisesRegex(ValueError, "parser reported errors"):
                    build_diagnostic_current_export_native_scope(
                        export_root=export_root,
                        source_asset_id=asset.asset_id,
                        source_fingerprint=asset.content_hash,
                        workspace_id=asset.workspace_id,
                        owner_user_id=asset.owner_user_id,
                        permission_scope=asset.permission_scope,
                        created_at=_CREATED_AT,
                    )

    def test_current_export_native_checkpoint_rejects_stale_parser_settings_before_work(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            export_root = root / "export"
            export_root.mkdir()
            (export_root / "001.eml").write_bytes(_message("first@test", "Alpha"))
            scope = build_diagnostic_current_export_native_scope(
                export_root=export_root,
                source_asset_id="asset_synthetic",
                source_fingerprint=_SOURCE_FINGERPRINT,
                workspace_id="workspace_synthetic",
                owner_user_id="user_synthetic",
                permission_scope=_PERMISSION_SCOPE,
                created_at=_CREATED_AT,
            )
            manifest_path, selection_path = write_diagnostic_current_export_native_scope(
                scope,
                root / "native-scope.private",
            )
            verifier = CoverageScopeAuthorityVerifier.from_external_root(b"p" * 32)

            with (
                patch(
                    "formowl_mail.diagnostic_structural_bridge." "select_readpst_export_messages"
                ) as selector,
                patch(
                    "formowl_mail.diagnostic_structural_bridge."
                    "produce_diagnostic_structural_bridge"
                ) as producer,
                self.assertRaisesRegex(ValueError, "selection checkpoint is stale"),
            ):
                materialize_diagnostic_structural_scope(
                    scope.manifest,
                    bridge_dir=root / "bridge",
                    checkpoint_dir=root / "materialization",
                    created_at=_CREATED_AT,
                    export_root=export_root,
                    full_scope_source_asset_id=scope.manifest.source_asset_id,
                    full_scope_source_fingerprint=scope.manifest.source_fingerprint,
                    native_selection_checkpoint=selection_path,
                    scope_manifest_path=manifest_path,
                    max_message_file_bytes=1024,
                    reader_uid=os.getuid(),
                    reader_gid=os.getgid(),
                    scope_authority_verifier=verifier,
                    semantic_profile=_profile(),
                )

            selector.assert_not_called()
            producer.assert_not_called()

    def test_current_export_native_checkpoint_rejects_changed_manifest_bytes_before_work(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            export_root = root / "export"
            export_root.mkdir()
            (export_root / "001.eml").write_bytes(_message("first@test", "Alpha"))
            scope = build_diagnostic_current_export_native_scope(
                export_root=export_root,
                source_asset_id="asset_synthetic",
                source_fingerprint=_SOURCE_FINGERPRINT,
                workspace_id="workspace_synthetic",
                owner_user_id="user_synthetic",
                permission_scope=_PERMISSION_SCOPE,
                created_at=_CREATED_AT,
            )
            manifest_path, selection_path = write_diagnostic_current_export_native_scope(
                scope,
                root / "native-scope.private",
            )
            manifest_path.write_bytes(manifest_path.read_bytes() + b"\n")
            verifier = CoverageScopeAuthorityVerifier.from_external_root(b"m" * 32)

            with (
                patch(
                    "formowl_mail.diagnostic_structural_bridge." "select_readpst_export_messages"
                ) as selector,
                patch(
                    "formowl_mail.diagnostic_structural_bridge."
                    "produce_diagnostic_structural_bridge"
                ) as producer,
                self.assertRaisesRegex(ValueError, "selection checkpoint is stale"),
            ):
                materialize_diagnostic_structural_scope(
                    scope.manifest,
                    bridge_dir=root / "bridge",
                    checkpoint_dir=root / "materialization",
                    created_at=_CREATED_AT,
                    export_root=export_root,
                    full_scope_source_asset_id=scope.manifest.source_asset_id,
                    full_scope_source_fingerprint=scope.manifest.source_fingerprint,
                    native_selection_checkpoint=selection_path,
                    scope_manifest_path=manifest_path,
                    reader_uid=os.getuid(),
                    reader_gid=os.getgid(),
                    scope_authority_verifier=verifier,
                    semantic_profile=_profile(),
                )

            selector.assert_not_called()
            producer.assert_not_called()

    def test_current_export_native_scope_constructor_rejects_invalid_full_scope_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            export_root = root / "export"
            export_root.mkdir()
            (export_root / "001.eml").write_bytes(_message("first@test", "Alpha"))
            (export_root / "002.eml").write_bytes(_message("second@test", "Beta"))
            original_extract = extract_readpst_export
            captured: dict[str, object] = {}

            def capture_extract(**kwargs: object) -> object:
                result = original_extract(**kwargs)
                captured["result"] = result
                return result

            with patch(
                "formowl_mail.diagnostic_structural_bridge.extract_readpst_export",
                side_effect=capture_extract,
            ):
                build_diagnostic_current_export_native_scope(
                    export_root=export_root,
                    source_asset_id="asset_synthetic",
                    source_fingerprint=_SOURCE_FINGERPRINT,
                    workspace_id="workspace_synthetic",
                    owner_user_id="user_synthetic",
                    permission_scope=_PERMISSION_SCOPE,
                    created_at=_CREATED_AT,
                )
            result = captured["result"]
            observations = tuple(result.observations)  # type: ignore[union-attr]
            messages = tuple(
                observation
                for observation in observations
                if observation.observation_type == "email_message"
            )
            self.assertEqual(len(messages), 2)
            first, second = messages

            def invalid_result(mutated_observations: tuple[object, ...]) -> SimpleNamespace:
                return SimpleNamespace(
                    errors=(),
                    source_inventory=result.source_inventory,  # type: ignore[union-attr]
                    observations=mutated_observations,
                )

            duplicate_occurrence_location = dict(second.location)
            duplicate_occurrence_location["message_occurrence_id"] = first.location[
                "message_occurrence_id"
            ]
            duplicate_occurrence_payload = dict(second.payload or {})
            duplicate_occurrence_payload["message_occurrence_id"] = first.payload[
                "message_occurrence_id"
            ]
            duplicate_occurrence = replace(
                second,
                location=duplicate_occurrence_location,
                payload=duplicate_occurrence_payload,
            )
            cases = {
                "wrong_message_count": (
                    tuple(observation for observation in observations if observation is not second),
                    "message coverage is incomplete",
                ),
                "duplicate_occurrence_identity": (
                    tuple(
                        duplicate_occurrence if observation is second else observation
                        for observation in observations
                    ),
                    "message identities are duplicated",
                ),
                "duplicate_observation_identity": (
                    tuple(
                        replace(second, observation_id=first.observation_id)
                        if observation is second
                        else observation
                        for observation in observations
                    ),
                    "observations are duplicated",
                ),
            }
            for name, (mutated_observations, error_message) in cases.items():
                with (
                    self.subTest(name=name),
                    patch(
                        "formowl_mail.diagnostic_structural_bridge.extract_readpst_export",
                        return_value=invalid_result(mutated_observations),
                    ),
                    self.assertRaisesRegex(ValueError, error_message),
                ):
                    build_diagnostic_current_export_native_scope(
                        export_root=export_root,
                        source_asset_id="asset_synthetic",
                        source_fingerprint=_SOURCE_FINGERPRINT,
                        workspace_id="workspace_synthetic",
                        owner_user_id="user_synthetic",
                        permission_scope=_PERMISSION_SCOPE,
                        created_at=_CREATED_AT,
                    )

            embedded_root = root / "embedded-export"
            embedded_root.mkdir()
            (embedded_root / "001.eml").write_bytes(
                _message_with_embedded_table(
                    message_id="top@test",
                    projected_value="Alpha",
                    embedded_message_id="child@test",
                    embedded_projected_value="Beta",
                )
            )
            embedded_capture: dict[str, object] = {}

            def capture_embedded_extract(**kwargs: object) -> object:
                embedded_result = original_extract(**kwargs)
                embedded_capture["result"] = embedded_result
                return embedded_result

            with (
                patch(
                    "formowl_mail.diagnostic_structural_bridge.extract_readpst_export",
                    side_effect=capture_embedded_extract,
                ),
                self.assertRaisesRegex(ValueError, "message coverage is incomplete"),
            ):
                build_diagnostic_current_export_native_scope(
                    export_root=embedded_root,
                    source_asset_id="asset_synthetic",
                    source_fingerprint=_SOURCE_FINGERPRINT,
                    workspace_id="workspace_synthetic",
                    owner_user_id="user_synthetic",
                    permission_scope=_PERMISSION_SCOPE,
                    created_at=_CREATED_AT,
                )
            embedded_result = embedded_capture["result"]
            embedded_observations = tuple(embedded_result.observations)  # type: ignore[union-attr]
            embedded_child = next(
                observation
                for observation in embedded_observations
                if (
                    observation.observation_type == "email_message"
                    and observation.location.get("parent_message_occurrence_id") is not None
                )
            )
            embedded_topology_result = SimpleNamespace(
                errors=(),
                source_inventory=embedded_result.source_inventory,  # type: ignore[union-attr]
                observations=tuple(
                    observation
                    for observation in embedded_observations
                    if observation.observation_type != "email_message"
                    or observation is embedded_child
                ),
            )
            with (
                patch(
                    "formowl_mail.diagnostic_structural_bridge.extract_readpst_export",
                    return_value=embedded_topology_result,
                ),
                self.assertRaisesRegex(ValueError, "embedded message topology is unsupported"),
            ):
                build_diagnostic_current_export_native_scope(
                    export_root=embedded_root,
                    source_asset_id="asset_synthetic",
                    source_fingerprint=_SOURCE_FINGERPRINT,
                    workspace_id="workspace_synthetic",
                    owner_user_id="user_synthetic",
                    permission_scope=_PERMISSION_SCOPE,
                    created_at=_CREATED_AT,
                )

            outside_path = root / "outside.eml"
            outside_path.write_bytes(_message("outside@test", "Outside"))
            unsafe_path = export_root / "unsafe-link.eml"
            unsafe_path.symlink_to(outside_path)
            with (
                patch(
                    "formowl_mail.diagnostic_structural_bridge.extract_readpst_export",
                    return_value=result,
                ),
                self.assertRaisesRegex(ValueError, "current-export traversal is invalid"),
            ):
                build_diagnostic_current_export_native_scope(
                    export_root=export_root,
                    source_asset_id="asset_synthetic",
                    source_fingerprint=_SOURCE_FINGERPRINT,
                    workspace_id="workspace_synthetic",
                    owner_user_id="user_synthetic",
                    permission_scope=_PERMISSION_SCOPE,
                    created_at=_CREATED_AT,
                )

    def test_current_export_native_scope_publication_is_atomic_on_second_write_and_rename(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            export_root = root / "export"
            export_root.mkdir()
            (export_root / "001.eml").write_bytes(_message("first@test", "Alpha"))
            scope = build_diagnostic_current_export_native_scope(
                export_root=export_root,
                source_asset_id="asset_synthetic",
                source_fingerprint=_SOURCE_FINGERPRINT,
                workspace_id="workspace_synthetic",
                owner_user_id="user_synthetic",
                permission_scope=_PERMISSION_SCOPE,
                created_at=_CREATED_AT,
            )

            second_write_output = root / "second-write.private"
            original_atomic_private_json = diagnostic_structural_bridge._atomic_private_json
            atomic_write_count = 0

            def fail_second_private_write(path: Path, payload: object) -> None:
                nonlocal atomic_write_count
                atomic_write_count += 1
                if atomic_write_count == 2:
                    raise OSError("synthetic second artifact write failure")
                original_atomic_private_json(path, payload)

            with (
                patch(
                    "formowl_mail.diagnostic_structural_bridge._atomic_private_json",
                    side_effect=fail_second_private_write,
                ),
                self.assertRaisesRegex(OSError, "second artifact write failure"),
            ):
                write_diagnostic_current_export_native_scope(scope, second_write_output)

            self.assertFalse(second_write_output.exists())
            self.assertFalse(any(root.glob(".second-write.private.*.tmp")))
            recovered_manifest, recovered_checkpoint = write_diagnostic_current_export_native_scope(
                scope,
                second_write_output,
            )
            self.assertTrue(recovered_manifest.is_file())
            self.assertTrue(recovered_checkpoint.is_file())

            rename_output = root / "rename.private"
            original_replace = os.replace

            def fail_final_rename(
                source: str | bytes | Path, destination: str | bytes | Path
            ) -> None:
                if Path(destination) == rename_output:
                    raise OSError("synthetic final rename failure")
                original_replace(source, destination)

            with (
                patch(
                    "formowl_mail.diagnostic_structural_bridge.os.replace",
                    side_effect=fail_final_rename,
                ),
                self.assertRaisesRegex(OSError, "final rename failure"),
            ):
                write_diagnostic_current_export_native_scope(scope, rename_output)

            self.assertFalse(rename_output.exists())
            self.assertFalse(any(root.glob(".rename.private.*.tmp")))
            recovered_manifest, recovered_checkpoint = write_diagnostic_current_export_native_scope(
                scope,
                rename_output,
            )
            self.assertTrue(recovered_manifest.is_file())
            self.assertTrue(recovered_checkpoint.is_file())

    def test_current_export_native_selection_rejects_duplicate_paths_and_source_drift(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            export_root = root / "export"
            export_root.mkdir()
            message_path = export_root / "001.eml"
            message_path.write_bytes(_message("first@test", "Alpha"))
            scope = build_diagnostic_current_export_native_scope(
                export_root=export_root,
                source_asset_id="asset_synthetic",
                source_fingerprint=_SOURCE_FINGERPRINT,
                workspace_id="workspace_synthetic",
                owner_user_id="user_synthetic",
                permission_scope=_PERMISSION_SCOPE,
                created_at=_CREATED_AT,
            )
            scope_dir = root / "native-scope.private"
            manifest_path, selection_path = write_diagnostic_current_export_native_scope(
                scope,
                scope_dir,
            )
            manifest = load_diagnostic_structural_scope_manifest(manifest_path)
            payload = json.loads(selection_path.read_text(encoding="utf-8"))
            payload["selected_message_paths"] *= 2
            selection_path.write_text(
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
                encoding="utf-8",
            )
            os.chmod(selection_path, 0o600)
            with self.assertRaisesRegex(ValueError, "checkpoint paths are invalid"):
                load_diagnostic_current_export_native_selection_checkpoint(
                    selection_path,
                    manifest=manifest,
                    scope_manifest_path=manifest_path,
                    parser_worker_count=1,
                    max_message_file_bytes=25 * 1024 * 1024,
                )

            selection_path.unlink()
            _, selection_path = write_diagnostic_current_export_native_scope(
                scope,
                root / "native-scope-rebuilt.private",
            )
            message_path.write_bytes(_message("first@test", "Changed"))
            verifier = CoverageScopeAuthorityVerifier.from_external_root(b"d" * 32)
            with self.assertRaisesRegex(ValueError, "source drift is detected"):
                materialize_diagnostic_structural_scope(
                    manifest,
                    bridge_dir=root / "bridge",
                    checkpoint_dir=root / "materialization",
                    created_at=_CREATED_AT,
                    export_root=export_root,
                    full_scope_source_asset_id=manifest.source_asset_id,
                    full_scope_source_fingerprint=manifest.source_fingerprint,
                    native_selection_checkpoint=selection_path,
                    scope_manifest_path=manifest_path,
                    reader_uid=os.getuid(),
                    reader_gid=os.getgid(),
                    scope_authority_verifier=verifier,
                    semantic_profile=_profile(),
                )

    def test_second_shard_failure_never_publishes_aggregate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, profile, verifier, bridge_dir, checkpoint_dir = self._prepare(root)
            call_count = 0

            def fail_second_shard(**kwargs: object):
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise RuntimeError("synthetic shard failure")
                return produce_diagnostic_structural_bridge(**kwargs)

            with (
                patch(
                    "formowl_mail.diagnostic_structural_bridge."
                    "produce_diagnostic_structural_bridge",
                    side_effect=fail_second_shard,
                ),
                self.assertRaisesRegex(RuntimeError, "synthetic shard failure"),
            ):
                materialize_diagnostic_structural_scope(
                    manifest,
                    bridge_dir=bridge_dir,
                    checkpoint_dir=checkpoint_dir,
                    created_at=_CREATED_AT,
                    export_root=root / "export",
                    full_scope_source_asset_id=manifest.source_asset_id,
                    full_scope_source_fingerprint=manifest.source_fingerprint,
                    shard_batch_size=1,
                    reader_uid=os.getuid(),
                    reader_gid=os.getgid(),
                    scope_authority_verifier=verifier,
                    semantic_profile=profile,
                )

            store = FileDiagnosticStructuralShardStore(bridge_dir, create=False)
            self.assertFalse(store.aggregate_manifest_path.exists())
            self.assertTrue(
                (checkpoint_dir / "shard-checkpoints.private" / "00000000.json").is_file()
            )
            self.assertFalse(
                (checkpoint_dir / "shard-checkpoints.private" / "00000001.json").exists()
            )

    def test_resume_reuses_checkpoints_and_recovers_missing_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, profile, verifier, bridge_dir, checkpoint_dir = self._materialize(root)
            store = FileDiagnosticStructuralShardStore(bridge_dir, create=False)
            store.aggregate_manifest_path.unlink()
            with patch(
                "formowl_mail.diagnostic_structural_bridge." "produce_diagnostic_structural_bridge",
                side_effect=AssertionError("completed shard must not be reparsed"),
            ):
                materialize_diagnostic_structural_scope(
                    manifest,
                    bridge_dir=bridge_dir,
                    checkpoint_dir=checkpoint_dir,
                    created_at=_CREATED_AT,
                    export_root=root / "export",
                    full_scope_source_asset_id=manifest.source_asset_id,
                    full_scope_source_fingerprint=manifest.source_fingerprint,
                    shard_batch_size=1,
                    reader_uid=os.getuid(),
                    reader_gid=os.getgid(),
                    scope_authority_verifier=verifier,
                    semantic_profile=profile,
                )

            store.aggregate_manifest_path.unlink()
            (checkpoint_dir / "shard-checkpoints.private" / "00000000.json").unlink()
            with patch(
                "formowl_mail.diagnostic_structural_bridge." "produce_diagnostic_structural_bridge",
                side_effect=AssertionError("published bundle must repair its checkpoint"),
            ):
                materialize_diagnostic_structural_scope(
                    manifest,
                    bridge_dir=bridge_dir,
                    checkpoint_dir=checkpoint_dir,
                    created_at=_CREATED_AT,
                    export_root=root / "export",
                    full_scope_source_asset_id=manifest.source_asset_id,
                    full_scope_source_fingerprint=manifest.source_fingerprint,
                    shard_batch_size=1,
                    reader_uid=os.getuid(),
                    reader_gid=os.getgid(),
                    scope_authority_verifier=verifier,
                    semantic_profile=profile,
                )
            self.assertTrue(
                (checkpoint_dir / "shard-checkpoints.private" / "00000000.json").is_file()
            )

    def test_partial_or_tampered_aggregate_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, profile, verifier, bridge_dir, _ = self._materialize(root)
            store = FileDiagnosticStructuralShardStore(bridge_dir, create=False)
            first_path = next(store.iter_bundle_paths(store.load_complete_manifest()))
            first_path.write_bytes(first_path.read_bytes() + b"\n")

            result = _runtime(
                bridge_dir,
                profile=profile,
                verifier=verifier,
            ).execute_semantic_request(_semantic_request())

            self.assertEqual(result["status"], "insufficient")
            self.assertEqual(result["complete_projection"]["values"], [])

    def test_missing_completed_shard_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, profile, verifier, bridge_dir, _ = self._materialize(root)
            store = FileDiagnosticStructuralShardStore(bridge_dir, create=False)
            manifest = store.load_complete_manifest()
            first_path = next(store.iter_bundle_paths(manifest))
            first_path.unlink()

            result = _runtime(
                bridge_dir,
                profile=profile,
                verifier=verifier,
            ).execute_semantic_request(_semantic_request())

            self.assertEqual(result["status"], "insufficient")
            self.assertEqual(result["complete_projection"]["values"], [])

    def test_legacy_bundle_without_export_verification_fails_before_grounding(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, profile, verifier, bridge_dir, _ = self._prepare(root)
            publication = produce_diagnostic_structural_bridge(
                export_root=root / "export",
                selected_message_paths=("01.eml", "02.eml"),
                bridge_dir=bridge_dir,
                source_asset_id=manifest.source_asset_id,
                source_fingerprint=manifest.source_fingerprint,
                workspace_id=manifest.workspace_id,
                owner_user_id=manifest.owner_user_id,
                permission_scope=manifest.permission_scope,
                created_at=_CREATED_AT,
                scope_authority_verifier=verifier,
                semantic_profile=profile,
            )
            bundle = FileMailEvidenceBundleStore._read(publication.bundle_path)
            trusted = {}
            for ledger in bundle.coverage_ledgers:
                authority = ledger.scope_partition.scope_authority
                trusted[f"{ledger.claim_requirement_id}:{ledger.source_inventory_id}"] = (
                    verifier.revalidate(authority)
                )
            bundle = replace(bundle, _expected_scope_authorities=trusted)
            validate_diagnostic_semantic_profile_binding(
                profile=profile,
                bundles=(bundle,),
                scope_authority_verifier=verifier,
            )
            candidate_index = SimpleNamespace(
                evidence_index=SimpleNamespace(),
                segment_by_observation_id={},
                text_policy_runtime=SimpleNamespace(tokenize=lambda _: ()),
            )
            runtime = CandidateGraphQueryRuntime(
                candidate_index=candidate_index,
                access_binding=object(),
                retrieval_scope={},
                structural_bundles=(bundle,),
                semantic_profile=profile,
                scope_authority_verifier=verifier,
            )

            with (
                patch(
                    "formowl_mail.diagnostic_mcp."
                    "PermissionFirstSemanticPlanner.ground_all_matching"
                ) as grounding,
                patch(
                    "formowl_mail.diagnostic_mcp." "execute_authorized_structured_set"
                ) as execution,
            ):
                result = runtime.execute_semantic_request(_semantic_request())

            self.assertEqual(result["status"], "insufficient")
            grounding.assert_not_called()
            execution.assert_not_called()

    def test_missing_existing_export_verification_fails_before_grounding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, profile, verifier, bridge_dir, _ = self._materialize(root)
            store = FileDiagnosticStructuralShardStore(bridge_dir, create=False)
            payload = json.loads(store.aggregate_manifest_path.read_text(encoding="utf-8"))
            payload.pop("existing_export_verification")
            store.aggregate_manifest_path.write_text(
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
                encoding="utf-8",
            )

            with (
                patch(
                    "formowl_mail.diagnostic_mcp."
                    "PermissionFirstSemanticPlanner.ground_all_matching"
                ) as grounding,
                patch(
                    "formowl_mail.diagnostic_mcp." "execute_authorized_structured_set"
                ) as execution,
            ):
                result = _runtime(
                    bridge_dir,
                    profile=profile,
                    verifier=verifier,
                ).execute_semantic_request(_semantic_request())

            self.assertEqual(result["status"], "insufficient")
            grounding.assert_not_called()
            execution.assert_not_called()

    def test_coherently_tampered_verification_fails_before_grounding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, profile, verifier, bridge_dir, _ = self._materialize(root)
            store = FileDiagnosticStructuralShardStore(bridge_dir, create=False)
            aggregate = store.load_complete_manifest()
            original = aggregate.existing_export_verification
            tampered = DiagnosticExistingExportVerification.create(
                scope_manifest_id=original.scope_manifest_id,
                source_inventory_id=original.source_inventory_id,
                operator_scope_binding_fingerprint=(original.operator_scope_binding_fingerprint),
                raw_byte_export_traversal_fingerprint=sha256_json(
                    {"tampered": (original.raw_byte_export_traversal_fingerprint)}
                ),
                export_file_count=original.export_file_count,
                export_message_file_count=original.export_message_file_count,
                parsed_export_message_count=(original.parsed_export_message_count),
                nonparsed_export_message_count=(original.nonparsed_export_message_count),
                matched_message_occurrence_count=(original.matched_message_occurrence_count),
            )
            tampered_records = tuple(
                replace(
                    record,
                    existing_export_verification_fingerprint=(tampered.verification_fingerprint),
                )
                for record in aggregate.shards
            )
            tampered_aggregate = DiagnosticStructuralAggregateManifest.create(
                scope_manifest_id=aggregate.scope_manifest_id,
                source_asset_id=aggregate.source_asset_id,
                source_fingerprint=aggregate.source_fingerprint,
                workspace_id=aggregate.workspace_id,
                owner_user_id=aggregate.owner_user_id,
                semantic_profile_fingerprint=(aggregate.semantic_profile_fingerprint),
                existing_export_verification=tampered,
                shard_batch_size=aggregate.shard_batch_size,
                selected_path_set_fingerprint=(aggregate.selected_path_set_fingerprint),
                selector_coverage_fingerprint=(aggregate.selector_coverage_fingerprint),
                expected_message_count=aggregate.expected_message_count,
                expected_body_segment_count=(aggregate.expected_body_segment_count),
                total_structural_observation_count=(aggregate.total_structural_observation_count),
                shards=tampered_records,
            )
            store.aggregate_manifest_path.write_text(
                json.dumps(
                    tampered_aggregate.to_private_dict(),
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            with (
                patch(
                    "formowl_mail.diagnostic_mcp."
                    "PermissionFirstSemanticPlanner.ground_all_matching"
                ) as grounding,
                patch(
                    "formowl_mail.diagnostic_mcp." "execute_authorized_structured_set"
                ) as execution,
            ):
                result = _runtime(
                    bridge_dir,
                    profile=profile,
                    verifier=verifier,
                ).execute_semantic_request(_semantic_request())

            self.assertEqual(result["status"], "insufficient")
            grounding.assert_not_called()
            execution.assert_not_called()

    def test_unaccounted_export_message_never_publishes_aggregate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, profile, verifier, bridge_dir, checkpoint_dir = self._prepare(root)
            (root / "export" / "extra.eml").write_bytes(
                _message("extra-message@example.test", "Gamma")
            )

            with self.assertRaisesRegex(
                ValueError,
                "message accounting is incomplete",
            ):
                materialize_diagnostic_structural_scope(
                    manifest,
                    bridge_dir=bridge_dir,
                    checkpoint_dir=checkpoint_dir,
                    created_at=_CREATED_AT,
                    export_root=root / "export",
                    full_scope_source_asset_id=manifest.source_asset_id,
                    full_scope_source_fingerprint=manifest.source_fingerprint,
                    shard_batch_size=1,
                    reader_uid=os.getuid(),
                    reader_gid=os.getgid(),
                    scope_authority_verifier=verifier,
                    semantic_profile=profile,
                )

            self.assertFalse(
                (
                    bridge_dir
                    / "diagnostic-shards.private"
                    / "complete-aggregate-manifest.private.json"
                ).exists()
            )

    def test_iterator_aggregates_and_deduplicates_without_list_bundles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, profile, verifier, bridge_dir, _ = self._materialize(
                root,
                projected_values=("Beta", "Alpha", "Alpha"),
            )
            with patch.object(
                FileMailEvidenceBundleStore,
                "list_bundles",
                side_effect=AssertionError("streaming path must not load all bundles"),
            ):
                result = _runtime(
                    bridge_dir,
                    profile=profile,
                    verifier=verifier,
                ).execute_semantic_request(_semantic_request())

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["claim_state"], "FOUND")
            self.assertEqual(
                result["complete_projection"]["values"],
                [{"values": ["Alpha"]}, {"values": ["Beta"]}],
            )
            self.assertEqual(result["citation_handles"], [])
            rendered = json.dumps(result, sort_keys=True)
            for forbidden in ("bundle_path", "shard_id", "storage_path"):
                self.assertNotIn(forbidden, rendered)

    def test_thin_topology_compatibility_emits_candidate_only_positive_matches(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, profile, verifier, bridge_dir, _ = self._materialize(
                root,
                messages=(
                    _message_with_fully_ambiguous_headers("ambiguous@example.test"),
                ),
                shard_batch_size=1,
            )
            store = FileDiagnosticStructuralShardStore(bridge_dir, create=False)
            aggregate = store.load_complete_manifest()
            baseline_template = diagnostic_mcp.prepare_prevalidated_semantic_shard_templates(
                aggregate=aggregate,
                bundles=tuple(
                    store.iter_bundles(
                        aggregate,
                        scope_authority_verifier=verifier,
                    )
                ),
                profile=profile,
                scope_authority_verifier=verifier,
            )[0]
            baseline_observation = baseline_template.baseline_scope.structural_observations[0]
            baseline_row = baseline_observation.rows[0]
            malformed_cell = replace(
                baseline_row.cells[0],
                row_ordinal=baseline_row.row_ordinal + 1,
            )
            self.assertIsInstance(malformed_cell, StructuralCell)
            malformed_observation = replace(
                baseline_observation,
                rows=(
                    replace(
                        baseline_row,
                        cells=(malformed_cell, *baseline_row.cells[1:]),
                    ),
                    *baseline_observation.rows[1:],
                ),
            )
            malformed_scope = replace(
                baseline_template.baseline_scope,
                structural_observations=(malformed_observation,),
            )

            with patch(
                "formowl_mail.diagnostic_mcp."
                "TaskAnsweringEngine._prepare_prevalidated_diagnostic_topology_attestation",
                side_effect=AssertionError(
                    "thin compatibility must not issue a canonical topology attestation"
                ),
            ):
                template = diagnostic_mcp._prepare_prevalidated_semantic_shard_template(
                    aggregate=baseline_template.aggregate,
                    profile=profile,
                    scope_authority_verifier=verifier,
                    shard_record=baseline_template.shard_record,
                    baseline_scope=malformed_scope,
                )

            self.assertTrue(template.thin_topology_compatibility)
            self.assertIsNone(template.topology_attestation)
            self.assertEqual(template.prevalidated_execution_scopes, {})
            with (
                patch(
                    "formowl_mail.diagnostic_mcp._derive_runtime_query_scope",
                    side_effect=AssertionError("request must not derive a scope"),
                ) as derive_scope,
                patch(
                    "formowl_mail.diagnostic_mcp.execute_authorized_structured_set",
                    wraps=diagnostic_mcp.execute_authorized_structured_set,
                ) as execution,
                patch(
                    "formowl_graph.task_answering._validate_structural_topology",
                    side_effect=AssertionError("request must not replay topology"),
                ) as topology,
                patch(
                    "formowl_mail.diagnostic_mcp."
                    "TaskAnsweringEngine._answer_prevalidated_diagnostic_structured_claim",
                    side_effect=AssertionError(
                        "thin compatibility must not construct a canonical claim"
                    ),
                ) as canonical_claim,
            ):
                result = _runtime(
                    bridge_dir,
                    profile=profile,
                    verifier=verifier,
                    prevalidated_semantic_shard_templates=(template,),
                ).execute_semantic_request(_semantic_request())

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["claim_state"], "CANDIDATE_MATCHES")
            self.assertEqual(result["retrieval_layer"], "candidate_only_kg_evidence")
            self.assertFalse(result["canonical_kg"])
            self.assertEqual(execution.call_count, 1)
            derive_scope.assert_not_called()
            topology.assert_not_called()
            canonical_claim.assert_not_called()

    def test_thin_topology_aggregate_skips_no_match_shard_and_collects_later_matches(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, profile, verifier, bridge_dir, _ = self._materialize(
                root,
                messages=(
                    _message_with_fully_ambiguous_rows(
                        "no-match@example.test",
                        rows=(("Ignored", "Zone B"),),
                    ),
                    _message_with_fully_ambiguous_rows(
                        "positive@example.test",
                        rows=tuple(
                            (f"Item {ordinal:02d}", "Zone A")
                            for ordinal in range(1, 16)
                        ),
                    ),
                ),
                shard_batch_size=1,
            )
            templates = self._thin_topology_templates(
                bridge_dir=bridge_dir,
                profile=profile,
                verifier=verifier,
            )

            with patch(
                "formowl_mail.diagnostic_mcp.execute_authorized_structured_set",
                wraps=diagnostic_mcp.execute_authorized_structured_set,
            ) as execution:
                result = _runtime(
                    bridge_dir,
                    profile=profile,
                    verifier=verifier,
                    prevalidated_semantic_shard_templates=templates,
                ).execute_semantic_request(_semantic_request())

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["claim_state"], "CANDIDATE_MATCHES")
            self.assertEqual(result["retrieval_layer"], "candidate_only_kg_evidence")
            self.assertFalse(result["canonical_kg"])
            self.assertEqual(len(result["complete_projection"]["values"]), 15)
            self.assertEqual(execution.call_count, 2)

    def test_thin_topology_aggregate_all_no_match_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, profile, verifier, bridge_dir, _ = self._materialize(
                root,
                messages=(
                    _message_with_fully_ambiguous_rows(
                        "no-match-one@example.test",
                        rows=(("Ignored One", "Zone B"),),
                    ),
                    _message_with_fully_ambiguous_rows(
                        "no-match-two@example.test",
                        rows=(("Ignored Two", "Zone C"),),
                    ),
                ),
                shard_batch_size=1,
            )
            templates = self._thin_topology_templates(
                bridge_dir=bridge_dir,
                profile=profile,
                verifier=verifier,
            )

            with patch(
                "formowl_mail.diagnostic_mcp.execute_authorized_structured_set",
                wraps=diagnostic_mcp.execute_authorized_structured_set,
            ) as execution:
                result = _runtime(
                    bridge_dir,
                    profile=profile,
                    verifier=verifier,
                    prevalidated_semantic_shard_templates=templates,
                ).execute_semantic_request(_semantic_request())

            self.assertEqual(result["status"], "insufficient")
            self.assertEqual(result["claim_state"], "UNRESOLVED")
            self.assertFalse(result["canonical_kg"])
            self.assertEqual(execution.call_count, 2)

    def test_authority_failure_precedes_alias_grounding_and_row_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, profile, _, bridge_dir, _ = self._materialize(root)
            wrong_verifier = CoverageScopeAuthorityVerifier.from_external_root(b"y" * 32)
            with (
                patch(
                    "formowl_mail.diagnostic_mcp."
                    "PermissionFirstSemanticPlanner.ground_all_matching"
                ) as grounding,
                patch(
                    "formowl_mail.diagnostic_mcp." "execute_authorized_structured_set"
                ) as execution,
            ):
                result = _runtime(
                    bridge_dir,
                    profile=profile,
                    verifier=wrong_verifier,
                ).execute_semantic_request(_semantic_request())

            self.assertEqual(result["status"], "insufficient")
            grounding.assert_not_called()
            execution.assert_not_called()


if __name__ == "__main__":
    unittest.main()
