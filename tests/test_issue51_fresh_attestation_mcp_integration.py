from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unicodedata
import unittest
from unittest.mock import patch

import _paths  # noqa: F401

from formowl_contract import (
    ContractValidationError,
    CoverageScopeAuthorityVerifier,
    SemanticSchemaAliasMap,
    sha256_json,
)
from formowl_mail.diagnostic_mcp import (
    CandidateGraphQueryRuntime,
    DiagnosticSemanticProfile,
    FormOwlDiagnosticMcpService,
    prepare_prevalidated_semantic_shard_templates,
)
from formowl_mail.persistence import (
    FileDiagnosticStructuralShardStore,
    publish_fresh_uat_attestation,
)


_AUTHORITY_ROOT = b"issue51-agent-c-fresh-attestation-root"
_WRONG_AUTHORITY_ROOT = b"issue51-agent-c-wrong-attestation-root"
_ISSUED_AT = "2026-08-12T00:00:00+00:00"
_SOURCE_ASSET_ID = "asset-fresh-attestation-integration"
_SCOPE_MANIFEST_ID = "scope-fresh-attestation-integration"


class _UnusedTextPolicyRuntime:
    """Satisfy the candidate runtime constructor without exercising retrieval."""

    @staticmethod
    def tokenize(_query_text: str) -> set[str]:
        return set()


def _canonical_projection_tuples(
    values: tuple[tuple[str, ...], ...],
) -> tuple[tuple[str, ...], ...]:
    return tuple(
        sorted(
            set(values),
            key=lambda projection: (
                tuple(_normalized_semantic_text(value) for value in projection),
                projection,
            ),
        )
    )


def _normalized_semantic_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _canonical_projection_fingerprint(values: tuple[tuple[str, ...], ...]) -> str:
    """Use the direct-canary ABI: canonical tuple sequence -> list-of-lists."""

    canonical = _canonical_projection_tuples(values)
    encoded = json.dumps(
        [list(projection) for projection in canonical],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _profile(*, actor_context_id: str = "actor-fresh-attestation") -> DiagnosticSemanticProfile:
    aliases = SemanticSchemaAliasMap(
        object_aliases={
            "html_table": ("html table", "table", "表格"),
        },
        predicate_aliases={
            "coo": ("COO", "country of origin"),
            "p/n": ("P/N", "part number", "料號"),
        },
        value_aliases={},
        value_domains={
            "coo": "open_public_value",
            "p/n": "open_public_value",
        },
    )
    fingerprint = DiagnosticSemanticProfile.fingerprint_for(
        profile_id="fresh-attestation-integration",
        profile_version="1",
        schema_alias_map=aliases,
        workspace_id="workspace-fresh-attestation",
        owner_user_id="owner-fresh-attestation",
        actor_context_id=actor_context_id,
        known_as_of=_ISSUED_AT,
    )
    return DiagnosticSemanticProfile(
        profile_id="fresh-attestation-integration",
        profile_version="1",
        profile_fingerprint=fingerprint,
        schema_alias_map=aliases,
        workspace_id="workspace-fresh-attestation",
        owner_user_id="owner-fresh-attestation",
        actor_context_id=actor_context_id,
        known_as_of=_ISSUED_AT,
    )


def _normalized_shard() -> dict[str, object]:
    normalized_bundle = {
        "schema": "formowl_normalized_evidence_shard_v1",
        "shard_key": "tiny-fresh-attestation-shard",
        "source_items": [
            {
                "source_key": "tiny-source",
                "structure_kind": "html_table",
                "content_type": "text/html",
                "ordinal": 0,
                "observation_keys": ["tiny-observation"],
            }
        ],
        "structural_observations": [
            {
                "observation_key": "tiny-observation",
                "source_key": "tiny-source",
                "structure_kind": "html_table",
                "columns": ["COO", "P/N"],
                "rows": [
                    ["Japan", "part-002"],
                    ["Japan", "part-001"],
                    ["Korea", "excluded-part"],
                ],
            }
        ],
    }
    return {
        "ordinal": 0,
        "normalized_bundle": normalized_bundle,
        "normalized_bundle_sha256": sha256_json(normalized_bundle),
        "immutable_source_hashes": {
            "normalized-input-tiny": sha256_json({"normalized_input": "tiny"}),
        },
    }


def _publish_tiny_attestation(
    *,
    output_dir: Path,
    profile: DiagnosticSemanticProfile,
) -> FileDiagnosticStructuralShardStore:
    shard = _normalized_shard()
    publish_fresh_uat_attestation(
        output_dir=output_dir,
        normalized_shards=(shard,),
        immutable_source_hashes=shard["immutable_source_hashes"],  # type: ignore[arg-type]
        source_asset_id=_SOURCE_ASSET_ID,
        source_fingerprint=sha256_json({"source": "fresh-attestation-integration"}),
        workspace_id=profile.workspace_id,
        owner_user_id=profile.owner_user_id,
        permission_scope={
            "scope_type": "asset",
            "scope_id": _SOURCE_ASSET_ID,
            "visibility": "restricted",
        },
        actor_context_id=profile.actor_context_id,
        issued_at=_ISSUED_AT,
        known_as_of=profile.known_as_of,
        semantic_profile_fingerprint=profile.profile_fingerprint,
        scope_manifest_id=_SCOPE_MANIFEST_ID,
        scope_policy_id="policy-fresh-attestation-integration",
        scope_policy_version="1",
        scope_policy_fingerprint=sha256_json({"policy": "fresh-attestation-integration"}),
        authority_verifier_root=_AUTHORITY_ROOT,
    )
    return FileDiagnosticStructuralShardStore(output_dir, create=False)


def _projection_values(payload: object) -> tuple[tuple[str, ...], ...]:
    if not isinstance(payload, dict):
        raise AssertionError("MCP structured payload is invalid")
    complete_projection = payload.get("complete_projection")
    if not isinstance(complete_projection, dict):
        raise AssertionError("MCP complete projection is invalid")
    values = complete_projection.get("values")
    if not isinstance(values, list):
        raise AssertionError("MCP complete projection values are invalid")
    projections: list[tuple[str, ...]] = []
    for entry in values:
        if not isinstance(entry, dict) or not isinstance(entry.get("values"), list):
            raise AssertionError("MCP projection entry is invalid")
        projection = tuple(entry["values"])
        if not projection or any(type(value) is not str or not value for value in projection):
            raise AssertionError("MCP projection values are invalid")
        projections.append(projection)
    return _canonical_projection_tuples(tuple(projections))


def _unexpected_source_or_citation_fields(
    value: object,
    *,
    path: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Reject raw source/citation payloads while allowing zero root counts."""

    unexpected: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            nested_path = (*path, key_text)
            tokens = {token for token in key_text.replace("-", "_").casefold().split("_") if token}
            allowed_empty_root_field = not path and (
                (key_text == "citation_handles" and nested == [])
                or (key_text in {"source_count", "citation_count"} and nested == 0)
            )
            if tokens.intersection({"source", "sources", "citation", "citations"}) and not (
                allowed_empty_root_field
            ):
                unexpected.append(".".join(nested_path))
            unexpected.extend(_unexpected_source_or_citation_fields(nested, path=nested_path))
    elif isinstance(value, list):
        for ordinal, nested in enumerate(value):
            unexpected.extend(
                _unexpected_source_or_citation_fields(
                    nested,
                    path=(*path, str(ordinal)),
                )
            )
    return tuple(sorted(set(unexpected)))


def _semantic_arguments() -> dict[str, object]:
    return {
        "query_text": "List synthetic parts whose COO is Japan.",
        "semantic_request": {
            "query_class": "attribute_filter",
            "object_type_mention": "table",
            "predicate_mention": "COO",
            "operator": "equals",
            "value_mention": "Japan",
            "projection_mention": "P/N",
            "cardinality": "all_matching",
            "page_size": 100,
            "page_number": 1,
        },
    }


def _candidate_runtime(
    *,
    store: FileDiagnosticStructuralShardStore,
    profile: DiagnosticSemanticProfile,
    verifier: CoverageScopeAuthorityVerifier,
    templates: tuple[object, ...],
) -> CandidateGraphQueryRuntime:
    return CandidateGraphQueryRuntime(
        candidate_index=SimpleNamespace(
            evidence_index=object(),
            segment_by_observation_id={},
            text_policy_runtime=_UnusedTextPolicyRuntime(),
        ),
        access_binding=object(),
        retrieval_scope={},
        structural_shard_store=store,
        semantic_profile=profile,
        scope_authority_verifier=verifier,
        prevalidated_semantic_shard_templates=templates,
    )


class FreshAttestationActualMcpIntegrationTests(unittest.TestCase):
    """Actual strict-MCP gate for current fresh attestation publication."""

    def test_fresh_attestation_reaches_exactly_one_actual_mcp_tools_call(self) -> None:
        profile = _profile()
        verifier = CoverageScopeAuthorityVerifier.from_external_root(_AUTHORITY_ROOT)
        with tempfile.TemporaryDirectory() as temporary:
            store = _publish_tiny_attestation(
                output_dir=Path(temporary),
                profile=profile,
            )
            aggregate = store.load_complete_manifest()
            bundles = tuple(
                store.iter_bundles(
                    aggregate,
                    scope_authority_verifier=verifier,
                )
            )
            templates = prepare_prevalidated_semantic_shard_templates(
                aggregate=aggregate,
                bundles=bundles,
                profile=profile,
                scope_authority_verifier=verifier,
            )
            service = FormOwlDiagnosticMcpService(
                runtime=_candidate_runtime(
                    store=store,
                    profile=profile,
                    verifier=verifier,
                    templates=templates,
                )
            )
            request = {
                "jsonrpc": "2.0",
                "id": "one-actual-tools-call",
                "method": "tools/call",
                "params": {
                    "name": "query_effective_graph_view",
                    "arguments": _semantic_arguments(),
                },
            }
            original_call_tool = FormOwlDiagnosticMcpService._call_tool
            tool_call_count = 0

            def counted_call_tool(
                instance: FormOwlDiagnosticMcpService,
                request_id: object,
                params: object,
            ) -> dict[str, object]:
                nonlocal tool_call_count
                tool_call_count += 1
                return original_call_tool(instance, request_id, params)  # type: ignore[arg-type]

            with patch.object(
                FormOwlDiagnosticMcpService,
                "_call_tool",
                new=counted_call_tool,
            ):
                response = service.handle(request)

        self.assertEqual(tool_call_count, 1)
        self.assertIsInstance(response, dict)
        result = response.get("result")  # type: ignore[union-attr]
        self.assertIsInstance(result, dict)
        payload = result.get("structuredContent")  # type: ignore[union-attr]
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["retrieval_path"], "mail_authorized_structured_set")
        self.assertEqual(payload["claim_state"], "CANDIDATE_MATCHES")
        self.assertIs(payload["canonical_kg"], False)

        expected_projections = _canonical_projection_tuples((("part-002",), ("part-001",)))
        observed_projections = _projection_values(payload)
        self.assertEqual(observed_projections, expected_projections)
        self.assertEqual(
            _canonical_projection_fingerprint(observed_projections),
            _canonical_projection_fingerprint(expected_projections),
        )

        citations = payload.get("citation_handles")
        self.assertEqual(citations, [])
        self.assertEqual(payload["source_count"], 0)
        self.assertEqual(payload["citation_count"], 0)
        self.assertEqual(
            len(citations),
            0,
            "citation_count must remain zero until an explicit evidence request",
        )
        self.assertEqual(
            _unexpected_source_or_citation_fields(payload),
            (),
            "source_count must remain zero in the one-call set projection",
        )

    def test_tamper_profile_and_scope_mismatch_fail_closed(self) -> None:
        profile = _profile()
        verifier = CoverageScopeAuthorityVerifier.from_external_root(_AUTHORITY_ROOT)

        with self.subTest("profile_mismatch"), tempfile.TemporaryDirectory() as temporary:
            store = _publish_tiny_attestation(
                output_dir=Path(temporary),
                profile=profile,
            )
            aggregate = store.load_complete_manifest()
            bundles = tuple(
                store.iter_bundles(
                    aggregate,
                    scope_authority_verifier=verifier,
                )
            )
            with self.assertRaises(ContractValidationError):
                prepare_prevalidated_semantic_shard_templates(
                    aggregate=aggregate,
                    bundles=bundles,
                    profile=_profile(actor_context_id="different-actor"),
                    scope_authority_verifier=verifier,
                )

        with (
            self.subTest("scope_authority_root_mismatch"),
            tempfile.TemporaryDirectory() as temporary,
        ):
            store = _publish_tiny_attestation(
                output_dir=Path(temporary),
                profile=profile,
            )
            aggregate = store.load_complete_manifest()
            wrong_verifier = CoverageScopeAuthorityVerifier.from_external_root(
                _WRONG_AUTHORITY_ROOT
            )
            with self.assertRaises(ContractValidationError):
                tuple(
                    store.iter_bundles(
                        aggregate,
                        scope_authority_verifier=wrong_verifier,
                    )
                )

        with self.subTest("persisted_bundle_tamper"), tempfile.TemporaryDirectory() as temporary:
            store = _publish_tiny_attestation(
                output_dir=Path(temporary),
                profile=profile,
            )
            aggregate = store.load_complete_manifest()
            bundle_path = next(store.iter_bundle_paths(aggregate))
            bundle_path.write_text(
                bundle_path.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ContractValidationError):
                store.load_complete_manifest()


if __name__ == "__main__":
    unittest.main()
