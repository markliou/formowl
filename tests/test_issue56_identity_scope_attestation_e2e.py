from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import _paths  # noqa: F401
from scripts import issue56_identity_scope_attestation as attestation


APPROVED_AT = "2026-08-19T12:00:00+00:00"
WORKSPACE_ID = "workspace_issue56_fixture"
TENANT_ID = "tenant_issue56_fixture"
ASSET_ID = "asset_issue56_identity_scope_fixture"
ASSET_CONTENT_HASH = attestation._fingerprint_json("fixture-source-bytes")
SOURCE_FINGERPRINT = attestation._fingerprint_json("fixture-source-snapshot")
PERMISSION_FINGERPRINT = attestation._fingerprint_json("fixture-permission")
APPROVER_ACTOR = "actor_issue56_fixture_operator"
AUTHORITY_SOURCE = "authority_issue56_fixture_decision"
SPEC_APPROVAL_ID = "spec_approval_issue56_workspace_only_fixture"
REASON = "Fixture operator approved this bounded source identity scope."


class Issue56IdentityScopeAttestationE2ETests(unittest.TestCase):
    def test_tenant_workspace_cli_create_validate_and_byte_determinism(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first"
            second = root / "second"
            first_public = _run_create(
                output_root=first,
                mode=attestation.TENANT_WORKSPACE_MODE,
                tenant_id=TENANT_ID,
            )
            _run_create(
                output_root=second,
                mode=attestation.TENANT_WORKSPACE_MODE,
                tenant_id=TENANT_ID,
            )

            first_private_path = first / attestation.PRIVATE_ARTIFACT_FILENAME
            first_safe_path = first / attestation.SAFE_REPORT_FILENAME
            self.assertEqual(
                first_private_path.read_bytes(), (second / first_private_path.name).read_bytes()
            )
            self.assertEqual(
                first_safe_path.read_bytes(), (second / first_safe_path.name).read_bytes()
            )
            private = json.loads(first_private_path.read_text(encoding="utf-8"))
            self.assertEqual(
                private["identity_scope"],
                {
                    "mode": attestation.TENANT_WORKSPACE_MODE,
                    "tenant_id": TENANT_ID,
                    "workspace_id": WORKSPACE_ID,
                },
            )
            self.assertEqual(first_public["tenant_dimension_status"], "explicitly_bound")
            self.assertEqual(first_public["counts"]["tenant_binding_count"], 1)
            self.assertEqual(
                first_public["private_artifact_byte_sha256"],
                _sha256_path(first_private_path),
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = attestation.main(
                    [
                        "validate",
                        "--attestation",
                        str(first_private_path),
                        "--expected-attestation-sha256",
                        _sha256_path(first_private_path),
                        "--safe-report",
                        str(first_safe_path),
                        "--expected-safe-report-sha256",
                        _sha256_path(first_safe_path),
                    ]
                )
            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(stdout.getvalue()), first_public)

    def test_workspace_only_requires_spec_and_operator_approval_without_tenant_field(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "workspace-only"
            public = _run_create(
                output_root=output_root,
                mode=attestation.WORKSPACE_ONLY_MODE,
                tenant_id=None,
                spec_approval_id=SPEC_APPROVAL_ID,
            )
            private = json.loads(
                (output_root / attestation.PRIVATE_ARTIFACT_FILENAME).read_text(encoding="utf-8")
            )
            self.assertNotIn("tenant_id", private["identity_scope"])
            self.assertEqual(
                private["approval"]["approval_kind"],
                attestation.SPEC_OPERATOR_APPROVAL_KIND,
            )
            self.assertEqual(public["tenant_dimension_status"], "not_modeled_not_fabricated")
            self.assertEqual(public["spec_approval_status"], "passed_explicit")
            self.assertEqual(public["counts"]["tenant_binding_count"], 0)
            self.assertEqual(public["counts"]["spec_approval_count"], 1)

    def test_mode_specific_missing_or_fabricated_identity_fields_fail_closed(self) -> None:
        common = _build_kwargs()
        cases = (
            (
                {**common, "mode": attestation.TENANT_WORKSPACE_MODE, "tenant_id": None},
                "tenant_id_invalid",
            ),
            (
                {
                    **common,
                    "mode": attestation.WORKSPACE_ONLY_MODE,
                    "tenant_id": TENANT_ID,
                    "spec_approval_id": SPEC_APPROVAL_ID,
                },
                "workspace_only_tenant_fabrication",
            ),
            (
                {
                    **common,
                    "mode": attestation.WORKSPACE_ONLY_MODE,
                    "tenant_id": None,
                    "spec_approval_id": None,
                },
                "workspace_only_spec_approval_missing",
            ),
            (
                {
                    **common,
                    "mode": attestation.TENANT_WORKSPACE_MODE,
                    "tenant_id": TENANT_ID,
                    "operator_approved": False,
                },
                "operator_approval_missing",
            ),
        )
        for kwargs, reason_code in cases:
            with (
                self.subTest(reason_code=reason_code),
                self.assertRaisesRegex(
                    attestation.IdentityScopeAttestationError,
                    reason_code,
                ),
            ):
                attestation.build_identity_scope_attestation(**kwargs)

    def test_explicit_timestamp_reason_actor_and_authority_reject_missing_placeholders(
        self,
    ) -> None:
        common = {
            **_build_kwargs(),
            "mode": attestation.TENANT_WORKSPACE_MODE,
            "tenant_id": TENANT_ID,
        }
        cases = (
            ("approved_at", "", "approved_at_invalid"),
            ("approved_at", "2026-08-19T12:00:00", "approved_at_timezone_missing"),
            ("reason", "TBD", "reason_invalid"),
            ("approver_actor", "placeholder", "approver_actor_invalid"),
            ("authority_source", "unknown", "authority_source_invalid"),
        )
        for field, value, reason_code in cases:
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(
                    attestation.IdentityScopeAttestationError,
                    reason_code,
                ),
            ):
                attestation.build_identity_scope_attestation(**{**common, field: value})

    def test_private_self_fingerprint_tamper_and_byte_seal_drift_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "sealed"
            _run_create(
                output_root=output_root,
                mode=attestation.TENANT_WORKSPACE_MODE,
                tenant_id=TENANT_ID,
            )
            private_path = output_root / attestation.PRIVATE_ARTIFACT_FILENAME
            safe_path = output_root / attestation.SAFE_REPORT_FILENAME
            private = json.loads(private_path.read_text(encoding="utf-8"))
            tampered = deepcopy(private)
            tampered["permission_fingerprint"] = attestation._fingerprint_json("tampered")
            with self.assertRaisesRegex(
                attestation.IdentityScopeAttestationError,
                "attestation_self_fingerprint_invalid",
            ):
                attestation.validate_private_identity_scope_attestation(tampered)

            with self.assertRaisesRegex(
                attestation.IdentityScopeAttestationError,
                "identity_scope_attestation_byte_seal_mismatch",
            ):
                attestation.load_identity_scope_attestation(
                    private_path,
                    expected_sha256=attestation._fingerprint_json("different-bytes"),
                )
            safe = json.loads(safe_path.read_text(encoding="utf-8"))
            with self.assertRaisesRegex(
                attestation.IdentityScopeAttestationError,
                "safe_report_private_byte_seal_mismatch",
            ):
                attestation.validate_safe_identity_scope_report(
                    safe,
                    private_artifact_bytes=private_path.read_bytes() + b" ",
                )

    def test_no_overwrite_symlink_or_partial_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            existing = root / "existing"
            existing.mkdir()
            marker = existing / "marker"
            marker.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(
                attestation.IdentityScopeAttestationError,
                "immutable_output_already_exists",
            ):
                _create_direct(existing)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

            symlink = root / "symlink-output"
            symlink.symlink_to(existing, target_is_directory=True)
            with self.assertRaisesRegex(
                attestation.IdentityScopeAttestationError,
                "immutable_output_already_exists",
            ):
                _create_direct(symlink)

            failed = root / "failed"
            call_count = 0

            def fail_second(path: Path, payload: bytes) -> None:
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise attestation.IdentityScopeAttestationError("injected_second_write_failure")
                attestation._write_file_exclusive(path, payload)

            with self.assertRaisesRegex(
                attestation.IdentityScopeAttestationError,
                "injected_second_write_failure",
            ):
                _create_direct(failed, write_staged_file=fail_second)
            self.assertEqual(call_count, 2)
            self.assertFalse(failed.exists())
            self.assertEqual(list(root.glob(f".{failed.name}.staging-*")), [])

    def test_safe_report_is_hash_count_status_only_and_hides_private_values(self) -> None:
        private_reason = "Operator fixture decision SECRET-SCOPE-991 remains private."
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "safe"
            _, safe = attestation.create_identity_scope_attestation_artifacts(
                output_root=output_root,
                **{
                    **_build_kwargs(),
                    "mode": attestation.TENANT_WORKSPACE_MODE,
                    "tenant_id": TENANT_ID,
                    "reason": private_reason,
                },
            )
            rendered = (output_root / attestation.SAFE_REPORT_FILENAME).read_text(encoding="utf-8")
            for forbidden in (
                TENANT_ID,
                WORKSPACE_ID,
                ASSET_ID,
                APPROVER_ACTOR,
                AUTHORITY_SOURCE,
                private_reason,
                "SECRET-SCOPE-991",
                str(output_root),
            ):
                self.assertNotIn(forbidden, rendered)
            attestation._assert_hash_count_status_only(safe)


def _build_kwargs() -> dict[str, object]:
    return {
        "workspace_id": WORKSPACE_ID,
        "asset_id": ASSET_ID,
        "asset_content_hash": ASSET_CONTENT_HASH,
        "source_fingerprint": SOURCE_FINGERPRINT,
        "permission_fingerprint": PERMISSION_FINGERPRINT,
        "approver_actor": APPROVER_ACTOR,
        "authority_source": AUTHORITY_SOURCE,
        "approved_at": APPROVED_AT,
        "reason": REASON,
        "operator_approved": True,
        "spec_approval_id": None,
    }


def _create_direct(
    output_root: Path,
    *,
    write_staged_file=None,
) -> tuple[dict[str, object], dict[str, object]]:
    return attestation.create_identity_scope_attestation_artifacts(
        output_root=output_root,
        mode=attestation.TENANT_WORKSPACE_MODE,
        tenant_id=TENANT_ID,
        _write_staged_file=write_staged_file,
        **_build_kwargs(),
    )


def _run_create(
    *,
    output_root: Path,
    mode: str,
    tenant_id: str | None,
    spec_approval_id: str | None = None,
) -> dict[str, object]:
    argv = [
        "create",
        "--mode",
        mode,
        "--workspace-id",
        WORKSPACE_ID,
        "--asset-id",
        ASSET_ID,
        "--asset-content-hash",
        ASSET_CONTENT_HASH,
        "--source-fingerprint",
        SOURCE_FINGERPRINT,
        "--permission-fingerprint",
        PERMISSION_FINGERPRINT,
        "--approver-actor",
        APPROVER_ACTOR,
        "--authority-source",
        AUTHORITY_SOURCE,
        "--approved-at",
        APPROVED_AT,
        "--reason",
        REASON,
        "--operator-approved",
        "--output-root",
        str(output_root),
    ]
    if tenant_id is not None:
        argv.extend(["--tenant-id", tenant_id])
    if spec_approval_id is not None:
        argv.extend(["--spec-approval-id", spec_approval_id])
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        exit_code = attestation.main(argv)
    if exit_code != 0:
        raise AssertionError(stdout.getvalue())
    return json.loads(stdout.getvalue())


def _sha256_path(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


if __name__ == "__main__":
    unittest.main()
