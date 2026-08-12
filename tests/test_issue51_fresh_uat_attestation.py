from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import unittest

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
    normalized_shards: tuple[dict[str, object], ...] | None = None,
    immutable_source_hashes: dict[str, str] | None = None,
) -> dict[str, object]:
    return {
        "output_dir": output_dir,
        "normalized_shards": normalized_shards or _two_shards(),
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


class FreshUatAttestationContractTests(unittest.TestCase):
    """Synthetic acceptance contract for fresh, current UAT attestation issuance."""

    def _publish(
        self,
        *,
        output_dir: Path,
        normalized_shards: tuple[dict[str, object], ...] | None = None,
        immutable_source_hashes: dict[str, str] | None = None,
    ) -> object:
        return _publisher()(
            **_issuer_kwargs(
                output_dir=output_dir,
                normalized_shards=normalized_shards,
                immutable_source_hashes=immutable_source_hashes,
            )
        )

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

    def test_legacy_authority_proof_and_ledger_fields_are_rejected(self) -> None:
        for legacy_field in (
            "legacy_authority_id",
            "legacy_proof_id",
            "legacy_coverage_ledger_id",
        ):
            with self.subTest(legacy_field=legacy_field), tempfile.TemporaryDirectory() as temporary:
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


if __name__ == "__main__":
    unittest.main()
