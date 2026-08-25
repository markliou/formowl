from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from scripts import issue56_holdout_oracle_free_projection as projection_builder
from scripts import issue56_independent_mail_holdout_uat as holdout_uat


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _fingerprint(value: object) -> str:
    return _sha256_bytes(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _payload_fingerprint(value: dict[str, object], field_name: str) -> str:
    return _fingerprint({key: item for key, item in value.items() if key != field_name})


def _case(
    *,
    case_number: int,
    stratum: str,
    result_kind: str,
    required_count: int,
    forbidden_count: int,
) -> dict[str, object]:
    required_ids = [
        f"observation-required-{case_number}-{index}" for index in range(required_count)
    ]
    forbidden_ids = [
        f"observation-forbidden-{case_number}-{index}" for index in range(forbidden_count)
    ]
    authoring_ids = required_ids or forbidden_ids
    case: dict[str, object] = {
        "case_id": f"holdout-case-{case_number:03d}",
        "domain": "mail",
        "intent_kind": (
            "relation_reasoning"
            if stratum == "graph_required"
            else "exact_inventory"
            if stratum.startswith("exact_")
            else "evidence_lookup"
        ),
        "pattern": stratum,
        "result_kind": result_kind,
        "query_text": f"sealed oracle-free query {case_number}",
        "requester_user_id": (
            f"denied-requester-{case_number}" if stratum == "permission_denied" else "owner-fixture"
        ),
        "required_source_observation_ids": required_ids,
        "forbidden_source_observation_ids": forbidden_ids,
        "authoring_source_observation_ids": authoring_ids,
        "required_match_count": required_count,
        "limit": 10,
        "private_fingerprint": _fingerprint(
            {
                "case_number": case_number,
                "stratum": stratum,
            }
        ),
        "stratum_id": stratum,
        "source_evidence_binding": {
            "source_snapshot_fingerprint": _fingerprint("source-snapshot"),
            "case_evidence_fingerprint": _fingerprint(authoring_ids),
        },
        "answer_oracle": {"fixture": f"private-answer-{case_number}"},
        "expected_private": {"fixture": f"private-score-{case_number}"},
    }
    return case


def _cases() -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    case_number = 0
    for _ in range(30):
        case_number += 1
        cases.append(
            _case(
                case_number=case_number,
                stratum="graph_required",
                result_kind="owner_match",
                required_count=2,
                forbidden_count=0,
            )
        )
    for _ in range(4):
        case_number += 1
        cases.append(
            _case(
                case_number=case_number,
                stratum="single_document_direct_lookup",
                result_kind="source_evidence",
                required_count=1,
                forbidden_count=0,
            )
        )
    for stratum in ("exact_set", "exact_count", "exact_aggregation"):
        case_number += 1
        cases.append(
            _case(
                case_number=case_number,
                stratum=stratum,
                result_kind=stratum,
                required_count=1,
                forbidden_count=0,
            )
        )
    for _ in range(2):
        case_number += 1
        cases.append(
            _case(
                case_number=case_number,
                stratum="no_answer_near_miss_negative",
                result_kind="no_answer",
                required_count=0,
                forbidden_count=1,
            )
        )
    for _ in range(2):
        case_number += 1
        cases.append(
            _case(
                case_number=case_number,
                stratum="permission_denied",
                result_kind="permission_denied",
                required_count=0,
                forbidden_count=1,
            )
        )
    return cases


class _Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.private_manifest_path = root / "holdout-manifest.private.json"
        self.preflight_path = root / "holdout-preflight.safe.json"
        self.source_lineage_path = root / "source-lineage.safe.json"
        self.development_disjointness_path = root / "development-disjointness.safe.json"
        self.cases = _cases()

        self.source_oracle_bindings = {
            "bundle_artifact_sha256": _fingerprint("bundle-bytes"),
            "bundle_artifact_fingerprint": _fingerprint("bundle-artifact"),
            "mail_evidence_bundle_fingerprint": _fingerprint("mail-evidence-bundle"),
            "retrieval_snapshot_sha256": _fingerprint("retrieval-snapshot-bytes"),
            "source_report_sha256": _fingerprint("source-report-bytes"),
            "source_snapshot_fingerprint": _fingerprint("source-snapshot"),
            "source_inventory_fingerprint": _fingerprint("source-inventory"),
            "source_provenance_fingerprint": _fingerprint("source-provenance"),
            "index_fingerprint": _fingerprint("index"),
            "tokenizer_profile_fingerprint": _fingerprint("tokenizer"),
        }
        self.development_exclusion_binding = {
            "development_case_count": 100,
            "development_manifest_fingerprint": _fingerprint("development-manifest"),
            "development_manifest_sha256": _fingerprint("development-manifest-bytes"),
            "development_registry_fingerprint": _fingerprint("development-registry"),
            "development_safe_report_sha256": _fingerprint("development-report-bytes"),
        }
        authoring_ids = {
            observation_id
            for case in self.cases
            for observation_id in case["authoring_source_observation_ids"]
        }
        self.disjointness = {
            "status": "passed",
            "development_holdout_observation_overlap_count": 0,
            "development_holdout_message_overlap_count": 0,
            "development_holdout_thread_overlap_count": 0,
            "holdout_authoring_observation_count": len(authoring_ids),
            "holdout_authoring_message_count": len(authoring_ids),
            "holdout_authoring_thread_count": len(authoring_ids) - 1,
            "holdout_observation_set_fingerprint": _fingerprint(
                sorted(_fingerprint(value) for value in authoring_ids)
            ),
            "holdout_message_set_fingerprint": _fingerprint("holdout-message-set"),
            "holdout_thread_set_fingerprint": _fingerprint("holdout-thread-set"),
        }
        self.private_manifest = self._private_manifest()
        self.private_manifest_sha256 = self.write(
            self.private_manifest_path,
            self.private_manifest,
        )
        self.preflight = self._preflight()
        self.preflight_sha256 = self.write(self.preflight_path, self.preflight)
        self.source_lineage = self._source_lineage()
        self.source_lineage_sha256 = self.write(
            self.source_lineage_path,
            self.source_lineage,
        )
        self.development_disjointness = self._development_disjointness()
        self.development_disjointness_sha256 = self.write(
            self.development_disjointness_path,
            self.development_disjointness,
        )

    @staticmethod
    def write(path: Path, value: object) -> str:
        payload = _canonical_bytes(value)
        path.write_bytes(payload)
        return _sha256_bytes(payload)

    def _private_manifest(self) -> dict[str, object]:
        manifest: dict[str, object] = {
            "artifact_id": holdout_uat.HOLDOUT_ARTIFACT_ID,
            "schema_version": 2,
            "classification": "independent_mail_holdout",
            "claim_boundary_status": ("sealed_independent_holdout_manifest_not_executed"),
            "execution_status": "not_run",
            "quality_result_status": "not_read",
            "seal_required_before_execution": True,
            "source_oracle_bindings": self.source_oracle_bindings,
            "development_exclusion_binding": self.development_exclusion_binding,
            "partition_fingerprint": _fingerprint("partition"),
            "disjointness": self.disjointness,
            "case_count": projection_builder.EXPECTED_CASE_COUNT,
            "case_strata_counts": dict(projection_builder.EXPECTED_STRATA_COUNTS),
            "cases": self.cases,
        }
        manifest["manifest_fingerprint"] = holdout_uat._payload_fingerprint(
            manifest,
            "manifest_fingerprint",
        )
        return manifest

    def _preflight(self) -> dict[str, object]:
        report: dict[str, object] = {
            "artifact_id": projection_builder.HOLDOUT_PREFLIGHT_ARTIFACT_ID,
            "schema_version": 2,
            "status": "passed",
            "classification": "independent_mail_holdout",
            "claim_boundary_status": "holdout_manifest_only",
            "execution_status": "not_run",
            "quality_result_status": "not_read",
            "development_quality_output_status": "not_read",
            "source_lineage_status": "passed",
            "source_oracle_status": "passed",
            "disjointness_status": "passed",
            "strata_coverage_status": "passed",
            "seal_before_execution_status": "passed",
            "counts": {
                "case_count": projection_builder.EXPECTED_CASE_COUNT,
                "holdout_authoring_observation_count": self.disjointness[
                    "holdout_authoring_observation_count"
                ],
                "holdout_authoring_message_count": self.disjointness[
                    "holdout_authoring_message_count"
                ],
                "holdout_authoring_thread_count": self.disjointness[
                    "holdout_authoring_thread_count"
                ],
                "development_holdout_observation_overlap_count": 0,
                "development_holdout_message_overlap_count": 0,
                "development_holdout_thread_overlap_count": 0,
                "source_unexplained_loss_count": 0,
                "blocker_count": 0,
            },
            "strata_counts": dict(projection_builder.EXPECTED_STRATA_COUNTS),
            "hashes": {
                "manifest_sha256": self.private_manifest_sha256,
                "manifest_fingerprint": self.private_manifest["manifest_fingerprint"],
                "partition_fingerprint": self.private_manifest["partition_fingerprint"],
                "development_manifest_sha256": self.development_exclusion_binding[
                    "development_manifest_sha256"
                ],
                "development_registry_fingerprint": self.development_exclusion_binding[
                    "development_registry_fingerprint"
                ],
                "source_snapshot_fingerprint": self.source_oracle_bindings[
                    "source_snapshot_fingerprint"
                ],
                "source_inventory_fingerprint": self.source_oracle_bindings[
                    "source_inventory_fingerprint"
                ],
                "source_provenance_fingerprint": self.source_oracle_bindings[
                    "source_provenance_fingerprint"
                ],
                "index_fingerprint": self.source_oracle_bindings["index_fingerprint"],
                "segmentation_profile_fingerprint": self.source_oracle_bindings[
                    "tokenizer_profile_fingerprint"
                ],
                "holdout_observation_set_fingerprint": self.disjointness[
                    "holdout_observation_set_fingerprint"
                ],
                "holdout_message_set_fingerprint": self.disjointness[
                    "holdout_message_set_fingerprint"
                ],
                "holdout_thread_set_fingerprint": self.disjointness[
                    "holdout_thread_set_fingerprint"
                ],
            },
            "blocker_ids": [],
        }
        report["report_fingerprint"] = _payload_fingerprint(
            report,
            "report_fingerprint",
        )
        return report

    def _source_lineage(self) -> dict[str, object]:
        source_lineage: dict[str, object] = {
            "artifact_id": projection_builder.SOURCE_LINEAGE_ARTIFACT_ID,
            "schema_version": projection_builder.SCHEMA_VERSION,
            "status": "passed",
            "execution_status": "not_run",
            "quality_result_status": "not_read",
            "holdout_preflight_safe_sha256": self.preflight_sha256,
            "private_manifest_sha256": self.private_manifest_sha256,
            "manifest_fingerprint": self.private_manifest["manifest_fingerprint"],
            "partition_fingerprint": self.private_manifest["partition_fingerprint"],
            "case_count": projection_builder.EXPECTED_CASE_COUNT,
            "case_strata_counts": dict(projection_builder.EXPECTED_STRATA_COUNTS),
            "source_oracle_bindings": self.source_oracle_bindings,
            "cases": [
                {
                    key: value
                    for key, value in case.items()
                    if key not in {"answer_oracle", "expected_private"}
                }
                for case in self.cases
            ],
        }
        source_lineage["source_lineage_fingerprint"] = _payload_fingerprint(
            source_lineage,
            "source_lineage_fingerprint",
        )
        return source_lineage

    def _development_disjointness(self) -> dict[str, object]:
        artifact: dict[str, object] = {
            "artifact_id": projection_builder.DEVELOPMENT_DISJOINTNESS_ARTIFACT_ID,
            "schema_version": projection_builder.SCHEMA_VERSION,
            "status": "passed",
            "execution_status": "not_run",
            "quality_result_status": "not_read",
            "holdout_preflight_safe_sha256": self.preflight_sha256,
            "private_manifest_sha256": self.private_manifest_sha256,
            "manifest_fingerprint": self.private_manifest["manifest_fingerprint"],
            "partition_fingerprint": self.private_manifest["partition_fingerprint"],
            "case_count": projection_builder.EXPECTED_CASE_COUNT,
            "case_strata_counts": dict(projection_builder.EXPECTED_STRATA_COUNTS),
            "development_exclusion_binding": self.development_exclusion_binding,
            "disjointness": self.disjointness,
        }
        artifact["development_disjointness_fingerprint"] = _payload_fingerprint(
            artifact,
            "development_disjointness_fingerprint",
        )
        return artifact

    def build(
        self,
        output_root: Path,
        *,
        source_lineage_path: Path | None = None,
        source_lineage_sha256: str | None = None,
        development_path: Path | None = None,
        development_sha256: str | None = None,
        write_staged_file: object | None = None,
    ) -> projection_builder.HoldoutOracleFreeProjectionArtifacts:
        kwargs: dict[str, object] = {}
        if write_staged_file is not None:
            kwargs["_write_staged_file"] = write_staged_file
        return projection_builder.build_holdout_oracle_free_projection_artifacts(
            holdout_preflight_safe_path=self.preflight_path,
            expected_holdout_preflight_safe_sha256=self.preflight_sha256,
            private_holdout_manifest_path=self.private_manifest_path,
            expected_private_holdout_manifest_sha256=self.private_manifest_sha256,
            source_lineage_safe_path=source_lineage_path or self.source_lineage_path,
            expected_source_lineage_safe_sha256=(
                source_lineage_sha256 or self.source_lineage_sha256
            ),
            development_disjointness_safe_path=(
                development_path or self.development_disjointness_path
            ),
            expected_development_disjointness_safe_sha256=(
                development_sha256 or self.development_disjointness_sha256
            ),
            output_root=output_root,
            **kwargs,
        )


class HoldoutOracleFreeProjectionE2ETest(unittest.TestCase):
    def test_build_matches_runner_projection_and_never_decodes_private_manifest(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            private_bytes = fixture.private_manifest_path.read_bytes()
            decoded_payloads: list[bytes] = []
            original_loads = json.loads

            def guarded_loads(payload: object, *args: object, **kwargs: object) -> object:
                encoded = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
                if encoded == private_bytes:
                    raise AssertionError("private holdout oracle decoded before claim")
                decoded_payloads.append(encoded)
                return original_loads(payload, *args, **kwargs)

            with mock.patch.object(
                projection_builder.json,
                "loads",
                side_effect=guarded_loads,
            ):
                artifacts = fixture.build(root / "projection")

            expected = holdout_uat.build_oracle_free_holdout_projection(
                private_manifest=fixture.private_manifest,
                private_manifest_sha256=fixture.private_manifest_sha256,
            )
            self.assertEqual(artifacts.projection, expected)
            self.assertEqual(len(decoded_payloads), 3)
            self.assertNotIn(private_bytes, decoded_payloads)
            self.assertEqual(
                artifacts.safe_report["private_manifest_decode_status"],
                "not_performed",
            )
            self.assertEqual(
                artifacts.safe_report["hashes"]["projection_byte_sha256"],
                _sha256_bytes(artifacts.projection_path.read_bytes()),
            )
            self.assertNotIn("answer_oracle", artifacts.projection_path.read_text())
            self.assertNotIn("expected_private", artifacts.projection_path.read_text())

    def test_cli_publishes_hash_count_status_safe_report(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            output_root = root / "cli-output"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/issue56_holdout_oracle_free_projection.py",
                    "--holdout-preflight-safe",
                    str(fixture.preflight_path),
                    "--expected-holdout-preflight-safe-sha256",
                    fixture.preflight_sha256,
                    "--private-holdout-manifest",
                    str(fixture.private_manifest_path),
                    "--expected-private-holdout-manifest-sha256",
                    fixture.private_manifest_sha256,
                    "--source-lineage-safe",
                    str(fixture.source_lineage_path),
                    "--expected-source-lineage-safe-sha256",
                    fixture.source_lineage_sha256,
                    "--development-disjointness-safe",
                    str(fixture.development_disjointness_path),
                    "--expected-development-disjointness-safe-sha256",
                    fixture.development_disjointness_sha256,
                    "--output-root",
                    str(output_root),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            stdout = json.loads(result.stdout)
            self.assertEqual(stdout["status"], "passed")
            self.assertEqual(stdout["counts"]["case_count"], 41)
            self.assertNotIn("query_text", result.stdout)
            self.assertNotIn("observation-required", result.stdout)
            self.assertTrue((output_root / projection_builder.PROJECTION_FILENAME).is_file())
            self.assertTrue((output_root / projection_builder.SAFE_REPORT_FILENAME).is_file())

    def test_tamper_and_cross_binding_drift_fail_without_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)

            tampered_bytes = fixture.source_lineage_path.read_bytes() + b" "
            fixture.source_lineage_path.write_bytes(tampered_bytes)
            with self.assertRaisesRegex(
                projection_builder.HoldoutOracleFreeProjectionError,
                "source_lineage_safe_seal_mismatch",
            ):
                fixture.build(root / "tampered-output")
            self.assertFalse((root / "tampered-output").exists())

            source_lineage = fixture._source_lineage()
            source_lineage["source_oracle_bindings"]["index_fingerprint"] = _fingerprint(
                "drifted-index"
            )
            source_lineage["source_lineage_fingerprint"] = _payload_fingerprint(
                source_lineage,
                "source_lineage_fingerprint",
            )
            drift_path = root / "source-lineage-drift.safe.json"
            drift_sha = fixture.write(drift_path, source_lineage)
            with self.assertRaisesRegex(
                projection_builder.HoldoutOracleFreeProjectionError,
                "source_lineage_preflight_mismatch",
            ):
                fixture.build(
                    root / "drift-output",
                    source_lineage_path=drift_path,
                    source_lineage_sha256=drift_sha,
                )
            self.assertFalse((root / "drift-output").exists())

    def test_missing_fields_and_oracle_fields_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)

            missing = fixture._source_lineage()
            missing.pop("cases")
            missing["source_lineage_fingerprint"] = _payload_fingerprint(
                missing,
                "source_lineage_fingerprint",
            )
            missing_path = root / "source-lineage-missing.safe.json"
            missing_sha = fixture.write(missing_path, missing)
            with self.assertRaisesRegex(
                projection_builder.HoldoutOracleFreeProjectionError,
                "source_lineage_safe_invalid",
            ):
                fixture.build(
                    root / "missing-output",
                    source_lineage_path=missing_path,
                    source_lineage_sha256=missing_sha,
                )

            oracle = fixture._source_lineage()
            oracle["cases"][0]["expected_private"] = {"must_not": "appear"}
            oracle["source_lineage_fingerprint"] = _payload_fingerprint(
                oracle,
                "source_lineage_fingerprint",
            )
            oracle_path = root / "source-lineage-oracle.safe.json"
            oracle_sha = fixture.write(oracle_path, oracle)
            with self.assertRaisesRegex(
                projection_builder.HoldoutOracleFreeProjectionError,
                "oracle_field_present_in_safe_artifact",
            ):
                fixture.build(
                    root / "oracle-output",
                    source_lineage_path=oracle_path,
                    source_lineage_sha256=oracle_sha,
                )

    def test_deterministic_outputs_and_no_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            first = fixture.build(root / "first")
            second = fixture.build(root / "second")
            self.assertEqual(
                first.projection_path.read_bytes(), second.projection_path.read_bytes()
            )
            self.assertEqual(
                first.safe_report_path.read_bytes(), second.safe_report_path.read_bytes()
            )
            with self.assertRaisesRegex(
                projection_builder.HoldoutOracleFreeProjectionError,
                "immutable_output_already_exists",
            ):
                fixture.build(root / "first")

    def test_injected_write_failure_leaves_no_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            calls = 0

            def fail_after_first(path: Path, payload: bytes, mode: int) -> None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    projection_builder._write_file_exclusive(path, payload, mode)
                    return
                raise projection_builder.HoldoutOracleFreeProjectionError("injected_write_failure")

            output_root = root / "partial-output"
            with self.assertRaisesRegex(
                projection_builder.HoldoutOracleFreeProjectionError,
                "injected_write_failure",
            ):
                fixture.build(
                    output_root,
                    write_staged_file=fail_after_first,
                )
            self.assertFalse(output_root.exists())
            self.assertEqual(
                list(root.glob(f".{output_root.name}.staging-*")),
                [],
            )


if __name__ == "__main__":
    unittest.main()
