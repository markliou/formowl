from __future__ import annotations

import builtins
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import _paths  # noqa: F401


_HISTORICAL_PROVENANCE_STATUS = "legacy_authority_unverified"
_SHA256_PREFIX = "sha256:"
_ACTOR_CONTEXT_ID = "actor_fresh_uat"
_ISSUED_AT = "2026-08-12T00:00:00+00:00"
_KNOWN_AS_OF = "2026-08-12T00:00:00+00:00"


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _SHA256_PREFIX + hashlib.sha256(encoded).hexdigest()


def _sha256_text(value: str) -> str:
    return _SHA256_PREFIX + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalized_shard(ordinal: int) -> dict[str, object]:
    shard_key = f"synthetic-shard-{ordinal}"
    source_key = f"synthetic-source-{ordinal}"
    observation_key = f"synthetic-observation-{ordinal}"
    normalized_bundle = {
        "schema": "formowl_normalized_evidence_shard_v1",
        "shard_key": shard_key,
        "source_items": [
            {
                "source_key": source_key,
                "structure_kind": "message",
                "content_type": "message/rfc822",
                "ordinal": 0,
                "observation_keys": [observation_key],
            }
        ],
        "structural_observations": [
            {
                "observation_key": observation_key,
                "source_key": source_key,
                "structure_kind": "table",
                "columns": ["attribute"],
                "rows": [["synthetic-value"]],
            }
        ],
    }
    return {
        "ordinal": ordinal,
        "normalized_bundle": normalized_bundle,
        "normalized_bundle_sha256": _sha256_json(normalized_bundle),
        "immutable_source_hashes": {
            f"normalized-input-{ordinal}": _sha256_text(f"normalized-input-{ordinal}"),
        },
    }


def _normalized_shard_with_blank_cell(ordinal: int) -> dict[str, object]:
    shard = _normalized_shard(ordinal)
    normalized_bundle = shard["normalized_bundle"]
    normalized_bundle["structural_observations"][0]["columns"].append("optional")  # type: ignore[index]
    normalized_bundle["structural_observations"][0]["rows"][0].append("")  # type: ignore[index]
    shard["normalized_bundle_sha256"] = _sha256_json(normalized_bundle)
    return shard


def _two_shards() -> tuple[dict[str, object], dict[str, object]]:
    return (_normalized_shard(0), _normalized_shard(1))


def _immutable_source_hashes() -> dict[str, str]:
    return {
        "normalized-input-0": _sha256_text("normalized-input-0"),
        "normalized-input-1": _sha256_text("normalized-input-1"),
    }


def _issuer_kwargs(
    *,
    output_dir: Path,
    normalized_shards: object | None = None,
    immutable_source_hashes: dict[str, str] | None = None,
) -> dict[str, object]:
    return {
        "output_dir": output_dir,
        "normalized_shards": (
            normalized_shards if normalized_shards is not None else _two_shards()
        ),
        "immutable_source_hashes": immutable_source_hashes or _immutable_source_hashes(),
        "source_asset_id": "asset_fresh_uat",
        "source_fingerprint": _sha256_text("synthetic-source"),
        "workspace_id": "workspace_fresh_uat",
        "owner_user_id": "owner_fresh_uat",
        "permission_scope": {
            "scope_type": "asset",
            "scope_id": "asset_fresh_uat",
            "visibility": "restricted",
        },
        "actor_context_id": _ACTOR_CONTEXT_ID,
        "issued_at": _ISSUED_AT,
        "known_as_of": _KNOWN_AS_OF,
        "semantic_profile_fingerprint": _sha256_text("synthetic-semantic-profile"),
        "scope_manifest_id": "scope_fresh_uat",
        "scope_policy_id": "scope-policy-fresh-uat",
        "scope_policy_version": "1",
        "scope_policy_fingerprint": _sha256_text("scope-policy-fresh-uat"),
        "authority_verifier_root": "fresh-uat-test-authority-root",
    }


def _publisher():
    """Return the deliberately small public issuer API expected by this test."""

    try:
        module = importlib.import_module("formowl_mail.persistence")
    except ImportError as exc:
        raise AssertionError(
            "fresh UAT issuer module is unavailable before the public API can be checked"
        ) from exc
    publisher = getattr(module, "publish_fresh_uat_attestation", None)
    if not callable(publisher):
        raise AssertionError(
            "missing public API formowl_mail.persistence.publish_fresh_uat_attestation"
        )
    return publisher


def _contract_validation_error() -> type[Exception]:
    module = importlib.import_module("formowl_contract")
    error_type = getattr(module, "ContractValidationError", None)
    if not isinstance(error_type, type) or not issubclass(error_type, Exception):
        raise AssertionError("formowl_contract.ContractValidationError is unavailable")
    return error_type


def _strict_loader(output_dir: Path):
    persistence = importlib.import_module("formowl_mail.persistence")
    store_type = getattr(persistence, "FileDiagnosticStructuralShardStore", None)
    verifier_type = getattr(
        importlib.import_module("formowl_contract"),
        "CoverageScopeAuthorityVerifier",
        None,
    )
    if not callable(store_type) or verifier_type is None:
        raise AssertionError("fresh UAT strict-loader contract is unavailable")
    store = store_type(output_dir)
    manifest = store.load_complete_manifest()
    verifier = verifier_type.from_external_root("fresh-uat-test-authority-root")
    return manifest, tuple(store.iter_bundles(manifest, scope_authority_verifier=verifier))


def _receipt_verifier():
    """Return the public receipt verifier used for binding mismatch rejection."""

    persistence = importlib.import_module("formowl_mail.persistence")
    verifier = getattr(persistence, "verify_fresh_uat_attestation_receipt", None)
    if not callable(verifier):
        raise AssertionError(
            "missing public API " "formowl_mail.persistence.verify_fresh_uat_attestation_receipt"
        )
    return verifier


def _attestation_binding_kwargs() -> dict[str, object]:
    values = _issuer_kwargs(output_dir=Path("/metadata-only-output"))
    return {
        field_name: values[field_name]
        for field_name in (
            "actor_context_id",
            "issued_at",
            "known_as_of",
            "semantic_profile_fingerprint",
            "permission_scope",
            "scope_manifest_id",
            "scope_policy_id",
            "scope_policy_version",
            "scope_policy_fingerprint",
            "authority_verifier_root",
        )
    }


def _assert_no_partial_output(test_case: unittest.TestCase, output_dir: Path) -> None:
    if not output_dir.exists():
        return
    files = tuple(path for path in output_dir.rglob("*") if path.is_file())
    test_case.assertEqual(files, (), "atomic publication left a partial output file")


class FreshUatAttestationContractTests(unittest.TestCase):
    """Synthetic acceptance contract for fresh, current UAT attestation issuance."""

    def _publish(
        self,
        *,
        output_dir: Path,
        normalized_shards: object | None = None,
        immutable_source_hashes: dict[str, str] | None = None,
    ) -> object:
        return _publisher()(
            **_issuer_kwargs(
                output_dir=output_dir,
                normalized_shards=normalized_shards,
                immutable_source_hashes=immutable_source_hashes,
            )
        )

    def test_lazy_shards_are_consumed_once_and_bundles_are_not_prebuilt(self) -> None:
        persistence = importlib.import_module("formowl_mail.persistence")
        original_builder = persistence._build_fresh_uat_bundle
        original_publisher = persistence.FileMailEvidenceBundleStore.publish_verified_bundle
        first, second = deepcopy(_two_shards())
        build_calls: list[int] = []
        published_count = 0

        class OnePassShards:
            def __init__(self) -> None:
                self.iteration_count = 0

            def __iter__(self):
                self.iteration_count += 1
                if self.iteration_count != 1:
                    raise AssertionError("publisher must not re-iterate lazy normalized shards")
                for shard in (first, second):
                    yield shard

        def bounded_builder(**kwargs: object):
            ordinal = kwargs["normalized_shard"]["ordinal"]  # type: ignore[index]
            self.assertEqual(
                published_count,
                ordinal,
                "publisher must persist each shard before building the next",
            )
            build_calls.append(ordinal)
            self.assertEqual(
                build_calls,
                list(range(len(build_calls))),
                "publisher must build and persist shards in source order",
            )
            return original_builder(**kwargs)

        def bounded_publisher(*args: object, **kwargs: object):
            nonlocal published_count
            publication = original_publisher(*args, **kwargs)
            published_count += 1
            return publication

        source = OnePassShards()
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(
                persistence,
                "_build_fresh_uat_bundle",
                side_effect=bounded_builder,
            ),
            patch.object(
                persistence.FileMailEvidenceBundleStore,
                "publish_verified_bundle",
                side_effect=bounded_publisher,
                autospec=True,
            ),
        ):
            receipt = self._publish(
                output_dir=Path(temporary),
                normalized_shards=source,
            )

        self.assertTrue(receipt.aggregate_manifest_id)
        self.assertEqual(source.iteration_count, 1)
        self.assertEqual(build_calls, [0, 1])
        self.assertEqual(published_count, 2)

    def test_current_strict_loader_round_trip_has_unverified_legacy_provenance_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            receipt = self._publish(output_dir=output_dir)

            self.assertEqual(
                receipt.historical_provenance_status,
                _HISTORICAL_PROVENANCE_STATUS,
            )
            self.assertTrue(receipt.aggregate_manifest_id)
            manifest, bundles = _strict_loader(output_dir)
            self.assertEqual(len(manifest.shards), 2)
            self.assertEqual(
                tuple(record.ordinal for record in manifest.shards),
                (0, 1),
            )
            self.assertEqual(len(bundles), 2)

    def test_normalized_empty_cell_round_trips_as_contract_blank(self) -> None:
        shard = _normalized_shard_with_blank_cell(0)
        immutable_source_hashes = dict(shard["immutable_source_hashes"])
        with tempfile.TemporaryDirectory() as temporary:
            self._publish(
                output_dir=Path(temporary),
                normalized_shards=(shard,),
                immutable_source_hashes=immutable_source_hashes,
            )
            _manifest, bundles = _strict_loader(Path(temporary))

        cells = bundles[0].structural_observations[0].rows[0].cells
        self.assertEqual(cells[-1].cell_state, "blank")
        self.assertIsNone(cells[-1].value)
        self.assertIsNone(cells[-1].normalized_value)

    def test_legacy_authority_proof_and_ledger_fields_are_rejected(self) -> None:
        for legacy_field in (
            "legacy_authority_id",
            "legacy_proof_id",
            "legacy_coverage_ledger_id",
        ):
            with (
                self.subTest(legacy_field=legacy_field),
                tempfile.TemporaryDirectory() as temporary,
            ):
                first, second = deepcopy(_two_shards())
                first[legacy_field] = "legacy-value"
                with self.assertRaises(_contract_validation_error()):
                    self._publish(
                        output_dir=Path(temporary),
                        normalized_shards=(first, second),
                    )

    def test_missing_or_wrong_normalized_bundle_sha_is_rejected(self) -> None:
        with self.subTest("missing"), tempfile.TemporaryDirectory() as temporary:
            first, second = deepcopy(_two_shards())
            first.pop("normalized_bundle_sha256")
            with self.assertRaises(_contract_validation_error()):
                self._publish(
                    output_dir=Path(temporary),
                    normalized_shards=(first, second),
                )

        with self.subTest("wrong"), tempfile.TemporaryDirectory() as temporary:
            first, second = deepcopy(_two_shards())
            first["normalized_bundle_sha256"] = _sha256_text("wrong-normalized-bundle")
            with self.assertRaises(_contract_validation_error()):
                self._publish(
                    output_dir=Path(temporary),
                    normalized_shards=(first, second),
                )

    def test_two_shard_reorder_and_payload_tamper_are_rejected(self) -> None:
        with self.subTest("reorder"), tempfile.TemporaryDirectory() as temporary:
            first, second = deepcopy(_two_shards())
            with self.assertRaises(_contract_validation_error()):
                self._publish(
                    output_dir=Path(temporary),
                    normalized_shards=(second, first),
                )

        with self.subTest("tamper"), tempfile.TemporaryDirectory() as temporary:
            first, second = deepcopy(_two_shards())
            first["normalized_bundle"]["source_items"][0]["content_type"] = "text/plain"  # type: ignore[index]
            with self.assertRaises(_contract_validation_error()):
                self._publish(
                    output_dir=Path(temporary),
                    normalized_shards=(first, second),
                )

    def test_attestation_actor_time_profile_scope_and_verifier_mismatches_are_rejected(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = self._publish(output_dir=Path(temporary))
            bindings = _attestation_binding_kwargs()
            _receipt_verifier()(receipt=receipt, **bindings)

            mismatches = {
                "actor": {"actor_context_id": "actor_other"},
                "issued_at": {"issued_at": "2026-08-13T00:00:00+00:00"},
                "known_as_of": {"known_as_of": "2026-08-13T00:00:00+00:00"},
                "profile": {"semantic_profile_fingerprint": _sha256_text("other-semantic-profile")},
                "scope": {
                    "permission_scope": {
                        "scope_type": "asset",
                        "scope_id": "asset_other",
                        "visibility": "restricted",
                    }
                },
                "verifier": {"authority_verifier_root": "other-authority-root"},
            }
            for mismatch_name, replacement in mismatches.items():
                with self.subTest(mismatch=mismatch_name):
                    expected = dict(bindings)
                    expected.update(replacement)
                    with self.assertRaises(_contract_validation_error()):
                        _receipt_verifier()(receipt=receipt, **expected)

    def test_shard_remove_or_add_against_bound_immutable_input_is_rejected(self) -> None:
        first, second = deepcopy(_two_shards())
        with self.subTest("remove"), tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(_contract_validation_error()):
                self._publish(
                    output_dir=Path(temporary),
                    normalized_shards=(first,),
                    immutable_source_hashes=_immutable_source_hashes(),
                )

        with self.subTest("add"), tempfile.TemporaryDirectory() as temporary:
            third = _normalized_shard(2)
            with self.assertRaises(_contract_validation_error()):
                self._publish(
                    output_dir=Path(temporary),
                    normalized_shards=(first, second, third),
                    immutable_source_hashes=_immutable_source_hashes(),
                )

    def test_publisher_does_not_mutate_immutable_source_hashes_input(self) -> None:
        immutable_source_hashes = _immutable_source_hashes()
        original = deepcopy(immutable_source_hashes)
        with tempfile.TemporaryDirectory() as temporary:
            self._publish(
                output_dir=Path(temporary),
                immutable_source_hashes=immutable_source_hashes,
            )
        self.assertEqual(immutable_source_hashes, original)

    def test_publisher_never_traverses_raw_pst_export_parser_or_extractor_entrypoints(self) -> None:
        forbidden_modules = (
            "formowl_mail.diagnostic_structural_bridge",
            "formowl_ingestion.extractors.mail.pst",
        )
        previously_loaded = {
            module_name: sys.modules.pop(module_name, None) for module_name in forbidden_modules
        }
        original_import = builtins.__import__
        original_import_module = importlib.import_module

        def reject_raw_module(module_name: str) -> None:
            if module_name in forbidden_modules or module_name.startswith(
                tuple(f"{name}." for name in forbidden_modules)
            ):
                raise AssertionError(
                    f"publisher must not import raw traversal module: {module_name}"
                )

        def guarded_import(
            name: str,
            globals: object = None,
            locals: object = None,
            fromlist: object = (),
            level: int = 0,
        ) -> object:
            reject_raw_module(name)
            return original_import(name, globals, locals, fromlist, level)

        def guarded_import_module(name: str, package: str | None = None) -> object:
            reject_raw_module(name)
            return original_import_module(name, package)

        try:
            with (
                patch.object(builtins, "__import__", side_effect=guarded_import),
                patch.object(importlib, "import_module", side_effect=guarded_import_module),
                tempfile.TemporaryDirectory() as temporary,
            ):
                self._publish(output_dir=Path(temporary))
        finally:
            for module_name in forbidden_modules:
                sys.modules.pop(module_name, None)
                if previously_loaded[module_name] is not None:
                    sys.modules[module_name] = previously_loaded[module_name]

    def test_atomic_write_failures_leave_no_partial_output(self) -> None:
        persistence = importlib.import_module("formowl_mail.persistence")
        for operation in ("open", "fsync", "replace"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as temporary:
                output_dir = Path(temporary) / "fresh-uat-output"
                with patch.object(
                    persistence.os,
                    operation,
                    side_effect=OSError(f"synthetic {operation} failure"),
                ):
                    with self.assertRaises(OSError):
                        self._publish(output_dir=output_dir)
                _assert_no_partial_output(self, output_dir)

    def test_receipt_is_metadata_only_and_excludes_private_or_legacy_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = self._publish(output_dir=Path(temporary))

        serializer = getattr(receipt, "to_dict", None)
        if not callable(serializer):
            raise AssertionError("fresh UAT receipt must expose metadata through to_dict")
        payload = serializer()
        self.assertIsInstance(payload, dict)
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        for forbidden in (
            "normalized_bundle",
            "source_items",
            "structural_observations",
            "synthetic-value",
            "/private/",
            "legacy_authority_id",
            "legacy_proof_id",
            "legacy_coverage_ledger_id",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
