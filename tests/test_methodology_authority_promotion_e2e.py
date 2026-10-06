from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from formowl_core.methodology_authority import (
    AUTHORITY_RELATIVE_PATH,
    check_methodology_authority,
    methodology_gate_dependency_manifest_path,
)
import test_methodology_authority as methodology_authority_tests

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/methodology_authority_promote.py"
SPEC = importlib.util.spec_from_file_location(
    "methodology_authority_promote_e2e",
    SCRIPT_PATH,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("methodology authority promotion script is unavailable")
PROMOTION = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROMOTION
SPEC.loader.exec_module(PROMOTION)


class _PromotionFixture:
    def __init__(self, repository_root: Path) -> None:
        self.repository_root = repository_root
        self.evidence_paths = methodology_authority_tests.MethodologyAuthorityTests._build_future_ready_production_fixture(
            repository_root
        )
        self.authority_relative_path = AUTHORITY_RELATIVE_PATH
        self.authority_path = repository_root / self.authority_relative_path
        self.candidate_relative_path = Path("promotion/candidate-methodology-authority.json")
        self.candidate_path = repository_root / self.candidate_relative_path
        self.candidate_path.parent.mkdir(parents=True, exist_ok=True)
        self.candidate_bytes = self.authority_path.read_bytes()
        self.candidate_path.write_bytes(self.candidate_bytes)

        self.current_bytes = (ROOT / AUTHORITY_RELATIVE_PATH).read_bytes()
        self.authority_path.write_bytes(self.current_bytes)
        self.current_sha256 = _sha256_bytes(self.current_bytes)
        self.candidate_sha256 = _sha256_bytes(self.candidate_bytes)
        self.claim_relative_path = Path("promotion/authority.claim.json")
        self.receipt_relative_path = Path("promotion/authority.receipt.json")
        self.claim_path = repository_root / self.claim_relative_path
        self.receipt_path = repository_root / self.receipt_relative_path
        self.dependency_paths = self._dependency_paths()

        current = check_methodology_authority(
            repository_root=repository_root,
            authority_path=self.authority_path,
        )
        candidate = check_methodology_authority(
            repository_root=repository_root,
            authority_path=self.candidate_path,
        )
        if not current.authority_valid or current.methodology_ready:
            raise AssertionError(current.errors)
        if not candidate.authority_valid or not candidate.methodology_ready:
            raise AssertionError(candidate.errors)

    def cli_arguments(self, mode: str) -> list[str]:
        arguments = [
            mode,
            "--repository-root",
            str(self.repository_root),
            "--authority",
            self.authority_relative_path.as_posix(),
            "--expected-current-authority-sha256",
            self.current_sha256,
            "--candidate-authority",
            self.candidate_relative_path.as_posix(),
            "--claim-path",
            self.claim_relative_path.as_posix(),
            "--receipt-path",
            self.receipt_relative_path.as_posix(),
        ]
        for gate_id in sorted(self.evidence_paths):
            arguments.extend(
                (
                    "--gate-evidence",
                    f"{gate_id}={self.evidence_paths[gate_id].as_posix()}",
                    "--gate-dependency-manifest",
                    f"{gate_id}={self.dependency_paths[gate_id].as_posix()}",
                )
            )
        return arguments

    def preflight(self) -> object:
        return PROMOTION.preflight_methodology_authority_promotion(
            repository_root=self.repository_root,
            authority_relative_path=self.authority_relative_path,
            expected_current_authority_sha256=self.current_sha256,
            candidate_authority_relative_path=self.candidate_relative_path,
            gate_evidence_relative_paths=self.evidence_paths,
            gate_dependency_manifest_relative_paths=self.dependency_paths,
            claim_relative_path=self.claim_relative_path,
            receipt_relative_path=self.receipt_relative_path,
        )

    def authority_stage_paths(self) -> list[Path]:
        return list(self.authority_path.parent.glob(f".{self.authority_path.name}.*.staged"))

    def _dependency_paths(self) -> dict[str, Path]:
        dependency_paths: dict[str, Path] = {}
        for gate_id, evidence_relative_path in self.evidence_paths.items():
            evidence = json.loads(
                (self.repository_root / evidence_relative_path).read_text(encoding="utf-8")
            )
            dependency_paths[gate_id] = methodology_gate_dependency_manifest_path(
                Path(evidence["result_artifact_path"])
            )
        return dependency_paths


class MethodologyAuthorityPromotionE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.fixture = _PromotionFixture(Path(self._temporary_directory.name))

    def test_preflight_then_atomic_promotion_publishes_auditable_receipt(
        self,
    ) -> None:
        for gate_id, evidence_relative_path in self.fixture.evidence_paths.items():
            evidence = _read_json(self.fixture.repository_root / evidence_relative_path)
            dependency_path = self.fixture.dependency_paths[gate_id]
            dependency = _read_json(self.fixture.repository_root / dependency_path)
            self.assertEqual(
                evidence["artifact_id"],
                "formowl_methodology_gate_evidence_v3",
            )
            self.assertEqual(evidence["schema_version"], 1)
            self.assertEqual(
                evidence["dependency_manifest_path"],
                dependency_path.as_posix(),
            )
            self.assertEqual(
                evidence["dependency_manifest_sha256"],
                _sha256_bytes((self.fixture.repository_root / dependency_path).read_bytes()),
            )
            self.assertEqual(
                evidence["dependency_manifest_fingerprint"],
                dependency["manifest_fingerprint"],
            )
            self.assertEqual(
                evidence["dependency_count"],
                len(dependency["dependencies"]),
            )
            _assert_internal_fingerprint(evidence, "envelope_fingerprint")

        preflight_exit, preflight_report = self._run_main("--preflight-only")

        self.assertEqual(preflight_exit, 0)
        self.assertEqual(
            preflight_report["status"],
            "preflight_passed_no_write",
        )
        self.assertEqual(preflight_report["validated_gate_count"], 4)
        self.assertEqual(
            self.fixture.authority_path.read_bytes(),
            self.fixture.current_bytes,
        )
        self.assertFalse(self.fixture.claim_path.exists())
        self.assertFalse(self.fixture.receipt_path.exists())
        self.assertEqual(self.fixture.authority_stage_paths(), [])
        self.assertNotIn(
            str(self.fixture.repository_root),
            json.dumps(preflight_report, sort_keys=True),
        )

        promotion_exit, promotion_report = self._run_main("--promote")

        self.assertEqual(promotion_exit, 0)
        self.assertEqual(promotion_report["status"], "promoted")
        self.assertEqual(
            self.fixture.authority_path.read_bytes(),
            self.fixture.candidate_bytes,
        )
        self.assertTrue(self.fixture.claim_path.is_file())
        self.assertTrue(self.fixture.receipt_path.is_file())
        self.assertEqual(self.fixture.authority_stage_paths(), [])
        self.assertEqual(
            stat.S_IMODE(self.fixture.claim_path.stat().st_mode),
            0o600,
        )
        self.assertEqual(
            stat.S_IMODE(self.fixture.receipt_path.stat().st_mode),
            0o600,
        )
        claim = _read_json(self.fixture.claim_path)
        receipt = _read_json(self.fixture.receipt_path)
        _assert_internal_fingerprint(claim, "claim_fingerprint")
        _assert_internal_fingerprint(receipt, "receipt_fingerprint")
        self.assertEqual(
            receipt["claim_byte_sha256"],
            _sha256_bytes(self.fixture.claim_path.read_bytes()),
        )
        self.assertEqual(
            promotion_report["receipt_byte_sha256"],
            _sha256_bytes(self.fixture.receipt_path.read_bytes()),
        )
        self.assertEqual(
            receipt["promoted_authority_sha256"],
            self.fixture.candidate_sha256,
        )
        self.assertEqual(len(receipt["gate_bindings"]), 4)
        post = check_methodology_authority(
            repository_root=self.fixture.repository_root,
            authority_path=self.fixture.authority_path,
        )
        self.assertTrue(post.authority_valid, post.errors)
        self.assertTrue(post.methodology_ready, post.errors)

        retry_exit, retry_report = self._run_main("--promote")

        self.assertEqual(retry_exit, 2)
        self.assertEqual(
            retry_report["reason_code"],
            "promotion_claim_already_exists",
        )
        self.assertEqual(
            self.fixture.authority_path.read_bytes(),
            self.fixture.candidate_bytes,
        )

    def test_v2_gate_evidence_downgrade_is_rejected(self) -> None:
        gate_id = sorted(self.fixture.evidence_paths)[0]
        evidence_path = self.fixture.repository_root / self.fixture.evidence_paths[gate_id]
        evidence = _read_json(evidence_path)
        evidence["artifact_id"] = "formowl_methodology_gate_evidence_v2"
        evidence = _with_internal_fingerprint(
            evidence,
            "envelope_fingerprint",
        )
        evidence_path.write_bytes(_canonical_json_bytes(evidence))

        exit_code, report = self._run_main("--preflight-only")

        self.assertEqual(exit_code, 2)
        self.assertEqual(report["reason_code"], "candidate_authority_invalid")
        self.assertEqual(
            self.fixture.authority_path.read_bytes(),
            self.fixture.current_bytes,
        )
        self.assertFalse(self.fixture.claim_path.exists())
        self.assertFalse(self.fixture.receipt_path.exists())

    def test_v3_dependency_manifest_envelope_fields_fail_closed(self) -> None:
        mutations = {
            "dependency_manifest_path": "evidence/production/other.dependencies.json",
            "dependency_manifest_sha256": _sha256_bytes(b"other-manifest"),
            "dependency_manifest_fingerprint": _sha256_bytes(b"other-manifest-fingerprint"),
            "dependency_count": 999,
        }
        for field_name, value in mutations.items():
            with self.subTest(field_name=field_name), tempfile.TemporaryDirectory() as temp_dir:
                fixture = _PromotionFixture(Path(temp_dir))
                gate_id = sorted(fixture.evidence_paths)[0]
                evidence_path = fixture.repository_root / fixture.evidence_paths[gate_id]
                evidence = _read_json(evidence_path)
                evidence[field_name] = value
                evidence = _with_internal_fingerprint(
                    evidence,
                    "envelope_fingerprint",
                )
                evidence_path.write_bytes(_canonical_json_bytes(evidence))

                output = io.StringIO()
                with redirect_stdout(output):
                    exit_code = PROMOTION.main(fixture.cli_arguments("--preflight-only"))
                report = json.loads(output.getvalue())

                self.assertEqual(exit_code, 2)
                self.assertEqual(
                    report["reason_code"],
                    "candidate_authority_invalid",
                )
                self.assertEqual(
                    fixture.authority_path.read_bytes(),
                    fixture.current_bytes,
                )
                self.assertFalse(fixture.claim_path.exists())
                self.assertFalse(fixture.receipt_path.exists())

    def test_dependency_tamper_is_rejected_even_with_resealed_manifest(
        self,
    ) -> None:
        gate_id = sorted(self.fixture.dependency_paths)[0]
        manifest_path = self.fixture.repository_root / self.fixture.dependency_paths[gate_id]
        manifest = _read_json(manifest_path)
        manifest["dependencies"][0]["byte_sha256"] = _sha256_bytes(b"self-asserted-tamper")
        manifest = _with_internal_fingerprint(
            manifest,
            "manifest_fingerprint",
        )
        manifest_path.write_bytes(_canonical_json_bytes(manifest))

        exit_code, report = self._run_main("--preflight-only")

        self.assertEqual(exit_code, 2)
        self.assertIn(
            report["reason_code"],
            {
                "candidate_authority_invalid",
                "gate_production_dependency_validation_failed",
            },
        )
        self.assertEqual(
            self.fixture.authority_path.read_bytes(),
            self.fixture.current_bytes,
        )
        self.assertFalse(self.fixture.claim_path.exists())
        self.assertFalse(self.fixture.receipt_path.exists())

    def test_stale_current_recheck_consumes_claim_without_replacing(
        self,
    ) -> None:
        preflight = self.fixture.preflight()
        stale_bytes = self.fixture.current_bytes + b"\n"

        def fault(checkpoint: str) -> None:
            if checkpoint == "before_stale_current_recheck":
                self.fixture.authority_path.write_bytes(stale_bytes)

        with patch.object(PROMOTION, "_fault_checkpoint", side_effect=fault):
            with self.assertRaises(PROMOTION.MethodologyAuthorityPromotionError) as raised:
                PROMOTION.promote_methodology_authority(preflight)

        self.assertEqual(
            raised.exception.reason_code,
            "stale_current_authority_recheck_failed",
        )
        self.assertEqual(self.fixture.authority_path.read_bytes(), stale_bytes)
        self.assertTrue(self.fixture.claim_path.is_file())
        self.assertFalse(self.fixture.receipt_path.exists())
        self.assertEqual(self.fixture.authority_stage_paths(), [])
        with self.assertRaises(PROMOTION.MethodologyAuthorityPromotionError) as retry:
            self.fixture.preflight()
        self.assertEqual(
            retry.exception.reason_code,
            "promotion_claim_already_exists",
        )

    def test_concurrent_promotions_have_exactly_one_winner(self) -> None:
        preflights = (self.fixture.preflight(), self.fixture.preflight())
        barrier = threading.Barrier(2)

        def fault(checkpoint: str) -> None:
            if checkpoint == "before_claim":
                barrier.wait(timeout=10)

        def promote(preflight: object) -> tuple[str, object]:
            try:
                return (
                    "passed",
                    PROMOTION.promote_methodology_authority(preflight),
                )
            except PROMOTION.MethodologyAuthorityPromotionError as exc:
                return ("blocked", exc.reason_code)

        with patch.object(PROMOTION, "_fault_checkpoint", side_effect=fault):
            with ThreadPoolExecutor(max_workers=2) as executor:
                outcomes = list(executor.map(promote, preflights))

        self.assertEqual(
            [status for status, _detail in outcomes].count("passed"),
            1,
        )
        self.assertEqual(
            [detail for status, detail in outcomes if status == "blocked"],
            ["promotion_claim_already_exists"],
        )
        self.assertEqual(
            self.fixture.authority_path.read_bytes(),
            self.fixture.candidate_bytes,
        )
        self.assertTrue(self.fixture.claim_path.is_file())
        self.assertTrue(self.fixture.receipt_path.is_file())
        self.assertEqual(self.fixture.authority_stage_paths(), [])

    def test_crash_before_replace_is_consumed_and_publishes_no_receipt(
        self,
    ) -> None:
        preflight = self.fixture.preflight()

        def fault(checkpoint: str) -> None:
            if checkpoint == "before_authority_replace":
                raise _SimulatedCrash("before replace")

        with patch.object(PROMOTION, "_fault_checkpoint", side_effect=fault):
            with self.assertRaises(_SimulatedCrash):
                PROMOTION.promote_methodology_authority(preflight)

        self.assertEqual(
            self.fixture.authority_path.read_bytes(),
            self.fixture.current_bytes,
        )
        self.assertTrue(self.fixture.claim_path.is_file())
        self.assertFalse(self.fixture.receipt_path.exists())
        self.assertEqual(self.fixture.authority_stage_paths(), [])
        self._assert_retry_blocked()

    def test_crash_after_replace_is_consumed_without_success_receipt(
        self,
    ) -> None:
        preflight = self.fixture.preflight()

        def fault(checkpoint: str) -> None:
            if checkpoint == "after_authority_replace":
                raise _SimulatedCrash("after replace")

        with patch.object(PROMOTION, "_fault_checkpoint", side_effect=fault):
            with self.assertRaises(_SimulatedCrash):
                PROMOTION.promote_methodology_authority(preflight)

        self.assertEqual(
            self.fixture.authority_path.read_bytes(),
            self.fixture.candidate_bytes,
        )
        self.assertTrue(self.fixture.claim_path.is_file())
        self.assertFalse(self.fixture.receipt_path.exists())
        self.assertEqual(self.fixture.authority_stage_paths(), [])
        self._assert_retry_blocked()

    def test_cli_exposes_no_force_retry_or_bypass_option(self) -> None:
        for unsupported in ("--force", "--retry", "--bypass"):
            with self.subTest(option=unsupported):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        PROMOTION.main(
                            [
                                "--preflight-only",
                                unsupported,
                            ]
                        )
                self.assertEqual(raised.exception.code, 2)

    def _run_main(self, mode: str) -> tuple[int, dict[str, object]]:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = PROMOTION.main(self.fixture.cli_arguments(mode))
        return exit_code, json.loads(output.getvalue())

    def _assert_retry_blocked(self) -> None:
        with self.assertRaises(PROMOTION.MethodologyAuthorityPromotionError) as retry:
            self.fixture.preflight()
        self.assertEqual(
            retry.exception.reason_code,
            "promotion_claim_already_exists",
        )


class _SimulatedCrash(BaseException):
    pass


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError("expected JSON object")
    return payload


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _with_internal_fingerprint(
    payload: dict[str, object],
    field_name: str,
) -> dict[str, object]:
    result = dict(payload)
    result.pop(field_name, None)
    result[field_name] = _sha256_bytes(_canonical_json_bytes(result))
    return result


def _assert_internal_fingerprint(
    payload: dict[str, object],
    field_name: str,
) -> None:
    expected = payload[field_name]
    unsigned = dict(payload)
    unsigned.pop(field_name)
    if expected != _sha256_bytes(_canonical_json_bytes(unsigned)):
        raise AssertionError(f"{field_name} mismatch")


if __name__ == "__main__":
    unittest.main()
