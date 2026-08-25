from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
import formowl_core.methodology_authority as methodology_authority
from formowl_core.methodology_authority import (
    AUTHORITY_RELATIVE_PATH,
    check_methodology_authority,
    probe_runtime_pipeline,
    probe_runtime_tokenizers,
)
from formowl_core.tokenization import ascii_identifier_regex_tokens

ROOT = Path(__file__).resolve().parents[1]


class MethodologyAuthorityTests(unittest.TestCase):
    def test_current_authority_is_valid_but_fail_closed_for_readiness(self) -> None:
        result = check_methodology_authority(repository_root=ROOT)
        report = result.to_safe_dict()

        self.assertTrue(report["authority_valid"])
        self.assertFalse(report["methodology_ready"])
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(
            report["current_method_id"],
            "evidence_to_knowledge_kg_ontology_v2_hybrid_v1",
        )
        self.assertEqual(
            report["current_tokenizer_id"],
            "jieba_sentencepiece_frozen_profile_candidate_admission_v1",
        )
        self.assertTrue(report["tokenizer_probe"]["cjk_support"])
        self.assertTrue(report["tokenizer_probe"]["ascii_identifier_support"])
        self.assertTrue(report["tokenizer_probe"]["runtime_probe_valid"])
        self.assertEqual(
            report["tokenizer_probe"]["query_tokenizer_id"],
            "jieba_sentencepiece_frozen_profile_candidate_admission_v1",
        )
        self.assertEqual(
            report["tokenizer_probe"]["evidence_tokenizer_id"],
            "jieba_sentencepiece_frozen_profile_candidate_admission_v1",
        )
        self.assertEqual(
            set(report["blocking_gate_ids"]),
            {
                "source_completeness_compared_with_raw_oracle",
                "evaluation_reports_bind_execution_fingerprint",
                "same_pipeline_real_source_ablation",
                "real_user_end_answer_acceptance",
            },
        )
        self.assertTrue(report["runtime_pipeline_probe"]["runtime_probe_valid"])
        self.assertEqual(
            report["runtime_pipeline_probe"]["method_id"],
            "evidence_to_knowledge_kg_ontology_v2_hybrid_v1",
        )
        self.assertTrue(report["runtime_pipeline_probe"]["legacy_or_ascii_fallback_absent"])
        self.assertIn("methodology_ready_for_quality_uat", report["blocked_claim_ids"])
        self.assertRegex(report["execution_fingerprint"], r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(report["authority_state_fingerprint"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(report["pipeline_source_binding_count"], 62)
        rendered = json.dumps(report, sort_keys=True)
        for forbidden in ("/home/", "/tmp/", "/workspace/", "postgresql://", "raw_path"):
            self.assertNotIn(forbidden, rendered)

    def test_runtime_probe_detects_tokenizer_drift_instead_of_trusting_manifest(self) -> None:
        def target_like_tokenizer(value: str) -> set[str]:
            if value.startswith("PO470002002"):
                return {
                    "po470002002",
                    "03.80503g301",
                    "supplier@example.test",
                }
            return {"查詢", "交期", "產地"}

        result = probe_runtime_tokenizers(
            query_tokenize=target_like_tokenizer,
            evidence_tokenize=target_like_tokenizer,
        )

        self.assertEqual(result.tokenizer_id, "unregistered_runtime_tokenizer")
        self.assertTrue(result.runtime_probe_valid)
        self.assertTrue(result.ascii_identifier_support)
        self.assertTrue(result.cjk_support)
        target = probe_runtime_tokenizers(
            query_tokenize=target_like_tokenizer,
            evidence_tokenize=target_like_tokenizer,
            query_tokenizer_id="jieba_sentencepiece_frozen_profile_candidate_admission_v1",
            evidence_tokenizer_id="jieba_sentencepiece_frozen_profile_candidate_admission_v1",
        )
        self.assertEqual(
            target.tokenizer_id,
            "jieba_sentencepiece_frozen_profile_candidate_admission_v1",
        )
        self.assertTrue(target.runtime_probe_valid)
        self.assertTrue(target.ascii_identifier_support)
        self.assertTrue(target.cjk_support)

    def test_ascii_tokenizer_capability_boundary_is_explicit(self) -> None:
        self.assertEqual(
            ascii_identifier_regex_tokens("PO470002002 03.80503G301 查詢交期"),
            {"po470002002", "03.80503g301"},
        )

    def test_future_target_fixture_requires_executable_validators_before_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository_root = Path(temp_dir)
            evidence_paths = self._build_future_ready_production_fixture(repository_root)
            ready = check_methodology_authority(repository_root=repository_root)
            blocked_gate = "same_pipeline_real_source_ablation"
            with patch.dict(
                methodology_authority._GATE_EXECUTABLE_VALIDATORS,
                {blocked_gate: lambda **_kwargs: False},
                clear=False,
            ):
                injected_failure = check_methodology_authority(repository_root=repository_root)
            script_path = ROOT / "scripts/methodology_authority_check.py"
            spec = importlib.util.spec_from_file_location(
                "methodology_authority_check_future_ready",
                script_path,
            )
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with patch.object(module, "ROOT", repository_root):
                with redirect_stdout(io.StringIO()):
                    require_ready_exit = module.main(["--require-ready"])

        self.assertTrue(ready.authority_valid, ready.errors)
        self.assertTrue(ready.methodology_ready)
        self.assertEqual(
            ready.current_tokenizer_id,
            "jieba_sentencepiece_frozen_profile_candidate_admission_v1",
        )
        self.assertTrue(ready.tokenizer_probe.cjk_support)
        self.assertFalse(injected_failure.authority_valid)
        self.assertFalse(injected_failure.methodology_ready)
        self.assertIn(
            f"passed_gate_missing_validated_evidence:{blocked_gate}",
            injected_failure.errors,
        )
        self.assertEqual(
            set(methodology_authority._GATE_EXECUTABLE_VALIDATORS),
            set(evidence_paths),
        )
        self.assertEqual(require_ready_exit, 0)

    def test_manifest_cannot_claim_ready_while_runtime_is_still_regex(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository_root = Path(temp_dir)
            self._copy_authority_fixture(repository_root)
            caller_names = {
                "query.py": ("_search_visible_bundles", "_build_snippet_index"),
                "evidence.py": ("search_mail_evidence", "_query_terms"),
            }
            for filename, callers in caller_names.items():
                (repository_root / "python/formowl_mail" / filename).write_text(
                    "from formowl_core import ascii_identifier_regex_tokens\n"
                    "MAIL_TOKENIZER_ID = 'ascii_identifier_regex_v1'\n"
                    + "".join(
                        f"def {caller}():\n    return _tokenize('probe')\n" for caller in callers
                    )
                    + "def _tokenize(value):\n"
                    "    return ascii_identifier_regex_tokens(value)\n",
                    encoding="utf-8",
                )
            authority_path = repository_root / AUTHORITY_RELATIVE_PATH
            payload = json.loads(authority_path.read_text(encoding="utf-8"))
            payload["status"] = "ready"
            payload["current_runtime"]["mail_query_tokenizer_id"] = "ascii_identifier_regex_v1"
            payload["current_runtime"]["mail_query_cjk_supported"] = False
            evidence_paths: dict[str, Path] = {}
            for gate in payload["required_gates"]:
                gate["status"] = "passed"
                if gate["gate_id"] == "runtime_pipeline_matches_target_method":
                    continue
                evidence_path = Path("evidence") / f"{gate['gate_id']}.json"
                gate["evidence"] = [evidence_path.as_posix()]
                evidence_paths[gate["gate_id"]] = evidence_path
            authority_path.write_text(json.dumps(payload), encoding="utf-8")
            provisional = check_methodology_authority(
                repository_root=repository_root,
            )
            self.assertIsNotNone(provisional.execution_fingerprint)
            for gate_id, relative_path in evidence_paths.items():
                path = repository_root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(
                        {
                            "artifact_id": "formowl_methodology_gate_evidence_v1",
                            "authority_id": provisional.authority_id,
                            "gate_id": gate_id,
                            "execution_fingerprint": provisional.execution_fingerprint,
                            "status": "passed",
                        }
                    ),
                    encoding="utf-8",
                )
            report_gate_id = "evaluation_reports_bind_execution_fingerprint"
            source_manifest_path = Path("evidence/source-manifest.json")
            source_manifest = {
                "artifact_id": "formowl_methodology_source_manifest_v1",
                "execution_fingerprint": provisional.execution_fingerprint,
                "source_kind": "real_source",
                "source_count": 1,
                "source_item_count": 100,
                "source_hashes": [f"sha256:{'1' * 64}"],
                "case_manifest_sha256": f"sha256:{'2' * 64}",
                "configuration_manifest_sha256": f"sha256:{'3' * 64}",
                "model_artifact_hashes": [f"sha256:{'4' * 64}"],
                "package_lock_sha256": f"sha256:{'5' * 64}",
            }
            source_manifest_bytes = json.dumps(source_manifest, sort_keys=True).encode()
            (repository_root / source_manifest_path).write_bytes(source_manifest_bytes)
            source_manifest_sha256 = f"sha256:{hashlib.sha256(source_manifest_bytes).hexdigest()}"
            result_artifact_path = Path("evidence/report-binding-result.json")
            result_artifact = {
                "artifact_id": "formowl_execution_report_binding_result_v1",
                "execution_fingerprint": provisional.execution_fingerprint,
                "source_manifest_sha256": source_manifest_sha256,
                "status": "passed",
                "report_count": 1,
                "bound_report_count": 1,
                "unbound_report_count": 0,
                "report_hashes": [f"sha256:{'6' * 64}"],
            }
            result_artifact_bytes = json.dumps(result_artifact, sort_keys=True).encode()
            (repository_root / result_artifact_path).write_bytes(result_artifact_bytes)
            (repository_root / evidence_paths[report_gate_id]).write_text(
                json.dumps(
                    {
                        "artifact_id": "formowl_methodology_gate_evidence_v2",
                        "authority_id": provisional.authority_id,
                        "gate_id": report_gate_id,
                        "execution_fingerprint": provisional.execution_fingerprint,
                        "validator_id": "execution_report_binding_validator_v1",
                        "source_manifest_path": source_manifest_path.as_posix(),
                        "source_manifest_sha256": source_manifest_sha256,
                        "result_artifact_path": result_artifact_path.as_posix(),
                        "result_artifact_sha256": (
                            f"sha256:{hashlib.sha256(result_artifact_bytes).hexdigest()}"
                        ),
                        "status": "passed",
                    }
                ),
                encoding="utf-8",
            )
            result = check_methodology_authority(repository_root=repository_root)

        self.assertFalse(result.authority_valid)
        self.assertFalse(result.methodology_ready)
        self.assertIn("passed_runtime_gate_requires_target_runtime_tokenizer", result.errors)
        self.assertIn("passed_runtime_gate_requires_cjk_runtime_support", result.errors)
        self.assertIn(
            "passed_gate_missing_validated_evidence:same_pipeline_real_source_ablation",
            result.errors,
        )
        self.assertNotIn(
            "passed_gate_executable_validator_unavailable:"
            "evaluation_reports_bind_execution_fingerprint",
            result.errors,
        )
        self.assertEqual(
            {
                error
                for error in result.errors
                if error.startswith("passed_gate_missing_validated_evidence:")
            },
            {f"passed_gate_missing_validated_evidence:{gate_id}" for gate_id in evidence_paths},
        )

    def test_manifest_cannot_silently_replace_the_frozen_target_method(self) -> None:
        payload = json.loads((ROOT / AUTHORITY_RELATIVE_PATH).read_text(encoding="utf-8"))
        payload["target_pipeline"]["tokenizer_id"] = "convenient_unreviewed_tokenizer_v1"

        with tempfile.TemporaryDirectory() as temp_dir:
            authority_path = Path(temp_dir) / "authority.json"
            authority_path.write_text(json.dumps(payload), encoding="utf-8")
            result = check_methodology_authority(
                repository_root=ROOT,
                authority_path=authority_path,
            )

        self.assertFalse(result.authority_valid)
        self.assertIn("frozen_target_pipeline_drift", result.errors)

    def test_production_validator_rejects_recomputed_diagnostic_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository_root = Path(temp_dir)
            self._build_future_ready_production_fixture(repository_root)
            gate_id = "source_completeness_compared_with_raw_oracle"
            oracle_path = repository_root / "evidence/production/raw-source-oracle.json"
            oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
            oracle["evidence_classification"] = "diagnostic"
            oracle = self._with_internal_fingerprint(oracle, "artifact_fingerprint")
            oracle_sha256 = self._write_json(oracle_path, oracle)
            result_path = repository_root / f"evidence/production/{gate_id}-result.json"
            dependency_manifest_path = (
                methodology_authority.methodology_gate_dependency_manifest_path(result_path)
            )
            dependency_manifest = json.loads(dependency_manifest_path.read_text(encoding="utf-8"))
            for entry in dependency_manifest["dependencies"]:
                if entry["role"] == "raw_source_oracle_manifest":
                    entry["byte_sha256"] = oracle_sha256
                    entry["internal_fingerprint"] = oracle["artifact_fingerprint"]
            dependency_manifest = self._with_internal_fingerprint(
                dependency_manifest,
                "manifest_fingerprint",
            )
            self._write_json(dependency_manifest_path, dependency_manifest)
            result = check_methodology_authority(repository_root=repository_root)

        self.assertFalse(result.authority_valid)
        self.assertFalse(result.methodology_ready)
        self.assertIn(
            f"passed_gate_missing_validated_evidence:{gate_id}",
            result.errors,
        )

    def test_dependency_manifest_rejects_unlisted_and_unsafe_paths(self) -> None:
        gate_id = "source_completeness_compared_with_raw_oracle"
        for mutation in ("unlisted", "/tmp/absolute.json", "../traversal.json", "tmp/item.json"):
            with self.subTest(mutation=mutation):
                with tempfile.TemporaryDirectory() as temp_dir:
                    repository_root = Path(temp_dir)
                    self._build_future_ready_production_fixture(repository_root)
                    result_path = repository_root / f"evidence/production/{gate_id}-result.json"
                    dependency_manifest_path = (
                        methodology_authority.methodology_gate_dependency_manifest_path(result_path)
                    )
                    dependency_manifest = json.loads(
                        dependency_manifest_path.read_text(encoding="utf-8")
                    )
                    if mutation == "unlisted":
                        oracle_path = repository_root / "evidence/production/raw-source-oracle.json"
                        oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
                        oracle["dependency_paths"] = ["evidence/production/not-listed.json"]
                        oracle = self._with_internal_fingerprint(
                            oracle,
                            "artifact_fingerprint",
                        )
                        oracle_sha256 = self._write_json(oracle_path, oracle)
                        for entry in dependency_manifest["dependencies"]:
                            if entry["role"] == "raw_source_oracle_manifest":
                                entry["byte_sha256"] = oracle_sha256
                                entry["internal_fingerprint"] = oracle["artifact_fingerprint"]
                    else:
                        for entry in dependency_manifest["dependencies"]:
                            if entry["role"] == "raw_source_oracle_manifest":
                                entry["path"] = mutation
                    dependency_manifest = self._with_internal_fingerprint(
                        dependency_manifest,
                        "manifest_fingerprint",
                    )
                    self._write_json(
                        dependency_manifest_path,
                        dependency_manifest,
                    )
                    result = check_methodology_authority(repository_root=repository_root)

                self.assertFalse(result.authority_valid)
                self.assertFalse(result.methodology_ready)
                self.assertIn(
                    f"passed_gate_missing_validated_evidence:{gate_id}",
                    result.errors,
                )

    def test_missing_or_unsealed_production_dependency_fails_closed(self) -> None:
        gate_id = "source_completeness_compared_with_raw_oracle"
        for mutation in ("missing_manifest", "unsealed_dependency"):
            with self.subTest(mutation=mutation):
                with tempfile.TemporaryDirectory() as temp_dir:
                    repository_root = Path(temp_dir)
                    self._build_future_ready_production_fixture(repository_root)
                    result_path = repository_root / f"evidence/production/{gate_id}-result.json"
                    dependency_manifest_path = (
                        methodology_authority.methodology_gate_dependency_manifest_path(result_path)
                    )
                    if mutation == "missing_manifest":
                        dependency_manifest_path.unlink()
                    else:
                        inventory_path = (
                            repository_root / "evidence/production/source-inventory.json"
                        )
                        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
                        del inventory["artifact_fingerprint"]
                        inventory_sha256 = self._write_json(
                            inventory_path,
                            inventory,
                        )
                        dependency_manifest = json.loads(
                            dependency_manifest_path.read_text(encoding="utf-8")
                        )
                        for entry in dependency_manifest["dependencies"]:
                            if entry["role"] == "source_inventory_manifest":
                                entry["byte_sha256"] = inventory_sha256
                                entry["internal_fingerprint"] = f"sha256:{'0' * 64}"
                        dependency_manifest = self._with_internal_fingerprint(
                            dependency_manifest,
                            "manifest_fingerprint",
                        )
                        self._write_json(
                            dependency_manifest_path,
                            dependency_manifest,
                        )
                    result = check_methodology_authority(repository_root=repository_root)

                self.assertFalse(result.authority_valid)
                self.assertFalse(result.methodology_ready)
                self.assertIn(
                    f"passed_gate_missing_validated_evidence:{gate_id}",
                    result.errors,
                )

    def test_gate_evidence_must_be_a_regular_repository_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            repository_root = temp_root / "repository"
            self._copy_authority_fixture(repository_root)
            outside_path = temp_root / "outside-evidence.json"
            outside_path.write_text("{}", encoding="utf-8")
            symlink_path = repository_root / "evidence/symlink.json"
            symlink_path.parent.mkdir(parents=True, exist_ok=True)
            symlink_path.symlink_to(outside_path)
            authority_path = repository_root / AUTHORITY_RELATIVE_PATH
            symlink_payload = json.loads(authority_path.read_text(encoding="utf-8"))
            symlink_payload["required_gates"][0]["evidence"] = ["evidence/symlink.json"]
            authority_path.write_text(json.dumps(symlink_payload), encoding="utf-8")
            symlink_result = check_methodology_authority(
                repository_root=repository_root,
            )

        self.assertFalse(symlink_result.authority_valid)
        self.assertIn(
            "methodology_gate_evidence_path_not_regular_repo_file",
            symlink_result.errors,
        )

    def test_target_runtime_method_binding_probe_fails_closed_on_legacy_default_drift(
        self,
    ) -> None:
        current = probe_runtime_pipeline(repository_root=ROOT)
        self.assertTrue(current.runtime_probe_valid)
        self.assertTrue(current.legacy_or_ascii_fallback_absent)

        with tempfile.TemporaryDirectory() as temp_dir:
            repository_root = Path(temp_dir)
            self._copy_authority_fixture(repository_root)
            hybrid_path = repository_root / "python/formowl_mail/hybrid.py"
            source = hybrid_path.read_text(encoding="utf-8")
            source = source.replace(
                '"legacy_hard_gate_default": False,',
                '"legacy_hard_gate_default": True,',
                1,
            )
            hybrid_path.write_text(source, encoding="utf-8")
            drifted = check_methodology_authority(repository_root=repository_root)

        self.assertFalse(drifted.authority_valid)
        self.assertFalse(drifted.runtime_pipeline_probe.runtime_probe_valid)
        self.assertIn("runtime_method_binding_drift", drifted.errors)

    def test_execution_fingerprint_binds_code_but_not_mutable_gate_state(self) -> None:
        original = check_methodology_authority(repository_root=ROOT)
        self.assertTrue(original.authority_valid)

        with tempfile.TemporaryDirectory() as temp_dir:
            repository_root = Path(temp_dir)
            self._copy_authority_fixture(repository_root)
            baseline = check_methodology_authority(repository_root=repository_root)
            authority_path = repository_root / AUTHORITY_RELATIVE_PATH
            authority_payload = json.loads(authority_path.read_text(encoding="utf-8"))
            authority_payload["required_gates"][0]["reason_code"] = (
                "still_blocked_with_updated_review_state"
            )
            authority_path.write_text(json.dumps(authority_payload), encoding="utf-8")
            state_drifted = check_methodology_authority(repository_root=repository_root)
            evaluation_path = (
                repository_root / "scripts/mail_full_pst_domain_hard_ontology_ablation_eval.py"
            )
            evaluation_path.write_text(
                evaluation_path.read_text(encoding="utf-8") + "\n# deliberate source drift\n",
                encoding="utf-8",
            )
            drifted = check_methodology_authority(repository_root=repository_root)

        self.assertTrue(baseline.authority_valid, baseline.errors)
        self.assertTrue(state_drifted.authority_valid)
        self.assertEqual(
            state_drifted.execution_fingerprint,
            baseline.execution_fingerprint,
        )
        self.assertNotEqual(
            state_drifted.authority_state_fingerprint,
            baseline.authority_state_fingerprint,
        )
        self.assertTrue(drifted.authority_valid)
        self.assertNotEqual(drifted.execution_fingerprint, baseline.execution_fingerprint)
        self.assertEqual(original.execution_fingerprint, baseline.execution_fingerprint)

    def test_runtime_binding_drift_invalidates_the_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository_root = Path(temp_dir)
            self._copy_authority_fixture(repository_root)
            caller_names = {
                "query.py": ("_search_visible_bundles", "_build_snippet_index"),
                "evidence.py": ("search_mail_evidence", "_query_terms"),
            }
            for filename, callers in caller_names.items():
                target = repository_root / "python/formowl_mail" / filename
                target.write_text(
                    "from formowl_core import ascii_identifier_regex_tokens\n"
                    "MAIL_TOKENIZER_ID = 'ascii_identifier_regex_v1'\n"
                    + "".join(
                        f"def {caller}():\n    return _tokenize('probe')\n" for caller in callers
                    )
                    + "def ascii_identifier_regex_tokens(value):\n"
                    "    return {'silently-shadowed'}\n"
                    "def _tokenize(value):\n"
                    "    return ascii_identifier_regex_tokens(value)\n",
                    encoding="utf-8",
                )
            shadowed = check_methodology_authority(repository_root=repository_root)
            self.assertFalse(shadowed.authority_valid)
            self.assertFalse(shadowed.methodology_ready)
            self.assertIn("runtime_tokenizer_binding_drift", shadowed.errors)
            self.assertIn("runtime_tokenizer_id_drift", shadowed.errors)

            for filename, callers in caller_names.items():
                target = repository_root / "python/formowl_mail" / filename
                target.write_text(
                    "from formowl_core import ascii_identifier_regex_tokens\n"
                    "MAIL_TOKENIZER_ID = 'ascii_identifier_regex_v1'\n"
                    f"def {callers[0]}():\n    return _tokenize('probe')\n"
                    f"def {callers[1]}():\n    return {{'bypassed'}}\n"
                    "def _tokenize(value):\n"
                    "    return ascii_identifier_regex_tokens(value)\n",
                    encoding="utf-8",
                )
            bypassed = check_methodology_authority(repository_root=repository_root)
            self.assertFalse(bypassed.authority_valid)
            self.assertIn("runtime_tokenizer_binding_drift", bypassed.errors)

            (repository_root / "python/formowl_core/__init__.py").write_text(
                "def ascii_identifier_regex_tokens(value):\n"
                "    if value.startswith('PO470002002'):\n"
                "        return {'po470002002', '03.80503g301', "
                "'supplier@example.test'}\n"
                "    return {'查詢', '交期', '與', '產地'}\n",
                encoding="utf-8",
            )
            reexport_drift = check_methodology_authority(repository_root=repository_root)
            self.assertFalse(reexport_drift.authority_valid)
            self.assertIn("runtime_tokenizer_id_drift", reexport_drift.errors)

    def test_unreadable_authority_fails_closed_without_partial_claims(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = check_methodology_authority(
                repository_root=ROOT,
                authority_path=Path(temp_dir) / "missing-authority.json",
            )

        self.assertFalse(result.authority_valid)
        self.assertFalse(result.methodology_ready)
        self.assertIsNone(result.execution_fingerprint)
        self.assertIsNone(result.authority_state_fingerprint)
        self.assertEqual(
            result.errors,
            ("methodology_authority_manifest_unreadable",),
        )

    def test_cli_distinguishes_valid_blocked_state_from_ready_state(self) -> None:
        check = subprocess.run(
            [sys.executable, "scripts/methodology_authority_check.py", "--check"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertFalse(json.loads(check.stdout)["methodology_ready"])

        require_ready = subprocess.run(
            [sys.executable, "scripts/methodology_authority_check.py", "--require-ready"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(require_ready.returncode, 1, require_ready.stderr)
        self.assertIn("same_pipeline_real_source_ablation", require_ready.stdout)

    def test_cli_main_runs_in_process_and_fails_closed_for_invalid_authority(self) -> None:
        script_path = ROOT / "scripts/methodology_authority_check.py"
        spec = importlib.util.spec_from_file_location(
            "methodology_authority_check_in_process",
            script_path,
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(["--check"]), 0)
            self.assertEqual(module.main(["--require-ready"]), 1)
            with tempfile.TemporaryDirectory() as temp_dir:
                authority_path = Path(temp_dir) / "invalid-authority.json"
                authority_path.write_text("{}", encoding="utf-8")
                self.assertEqual(
                    module.main(["--check", "--authority", str(authority_path)]),
                    2,
                )

    def test_startup_and_durable_status_cannot_hide_the_guard(self) -> None:
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        board = (ROOT / "docs/implementation-task-breakdown.md").read_text(encoding="utf-8")
        goal = (ROOT / "docs/agent-goals/kg-research-agent.md").read_text(encoding="utf-8")

        self.assertIn("docs/methodology-authority.json", agents)
        self.assertIn("methodology_authority_check.py --check", agents)
        self.assertIn("methodology_authority_check.py --require-ready", agents)
        self.assertNotIn("\npython scripts/methodology_authority_check.py", agents)
        self.assertIn(
            "- [ ] Align the real runtime with the active methodology authority",
            board,
        )
        self.assertIn("pinned authority is valid but fail-closed", goal.lower())
        self.assertIn("the executable authority still blocks", goal.lower())

    @classmethod
    def _build_future_ready_production_fixture(
        cls,
        repository_root: Path,
    ) -> dict[str, Path]:
        cls._copy_authority_fixture(repository_root)
        target_tokenizer_id = "jieba_sentencepiece_frozen_profile_candidate_admission_v1"
        target_helper = "jieba_sentencepiece_frozen_profile_candidate_admission_tokens"
        (repository_root / "python/formowl_core/tokenization.py").write_text(
            "def jieba_sentencepiece_frozen_profile_candidate_admission_tokens(value):\n"
            "    if value == 'PO470002002 03.80503G301 supplier@example.test':\n"
            "        return {'po470002002', '03.80503g301', "
            "'supplier@example.test'}\n"
            "    if value == '查詢交期與產地':\n"
            "        return {'查詢', '交期', '產地'}\n"
            "    return set()\n"
            "\n"
            "__all__ = [\n"
            "    'jieba_sentencepiece_frozen_profile_candidate_admission_tokens',\n"
            "]\n",
            encoding="utf-8",
        )
        (repository_root / "python/formowl_core/__init__.py").write_text(
            "from .core import diff_lines, sha256_prefixed, sha256_prefixed_id\n"
            "from .json_files import read_json_object, write_json_atomic\n"
            "from .tokenization import (\n"
            "    jieba_sentencepiece_frozen_profile_candidate_admission_tokens,\n"
            ")\n"
            "\n"
            "__all__ = [\n"
            "    'diff_lines',\n"
            "    'jieba_sentencepiece_frozen_profile_candidate_admission_tokens',\n"
            "    'read_json_object',\n"
            "    'sha256_prefixed',\n"
            "    'sha256_prefixed_id',\n"
            "    'write_json_atomic',\n"
            "]\n",
            encoding="utf-8",
        )
        caller_names = {
            "query.py": ("_search_visible_bundles", "_build_snippet_index"),
            "evidence.py": ("search_mail_evidence", "_query_terms"),
        }
        for filename, callers in caller_names.items():
            (repository_root / "python/formowl_mail" / filename).write_text(
                f"from formowl_core import {target_helper}\n"
                f"MAIL_TOKENIZER_ID = {target_tokenizer_id!r}\n"
                + "".join(f"def {caller}():\n    return _tokenize('probe')\n" for caller in callers)
                + "def _tokenize(value):\n"
                f"    return {target_helper}(value)\n",
                encoding="utf-8",
            )

        authority_path = repository_root / AUTHORITY_RELATIVE_PATH
        authority = json.loads(authority_path.read_text(encoding="utf-8"))
        authority["status"] = "ready"
        authority["current_runtime"] = {
            "method_id": authority["target_pipeline"]["method_id"],
            "mail_query_tokenizer_id": authority["target_pipeline"]["tokenizer_id"],
            "mail_query_cjk_supported": True,
            "ingestion_policy_id": authority["target_pipeline"]["ingestion_policy_id"],
            "evaluation_policy_id": authority["target_pipeline"]["evaluation_policy_id"],
        }
        evidence_paths: dict[str, Path] = {}
        for gate in authority["required_gates"]:
            gate["status"] = "passed"
            gate["reason_code"] = "production_validator_fixture_passed"
            if gate["gate_id"] != "runtime_pipeline_matches_target_method":
                evidence_path = Path("evidence/production") / f"{gate['gate_id']}-evidence.json"
                gate["evidence"] = [evidence_path.as_posix()]
                evidence_paths[gate["gate_id"]] = evidence_path
        authority_path.write_text(json.dumps(authority), encoding="utf-8")
        provisional = check_methodology_authority(repository_root=repository_root)
        execution_fingerprint = provisional.execution_fingerprint
        if execution_fingerprint is None:
            raise AssertionError(provisional.errors)

        production_root = repository_root / "evidence/production"
        production_root.mkdir(parents=True, exist_ok=True)
        source_item_path = Path("evidence/production/source-item.bin")
        model_artifact_path = Path("evidence/production/model-artifact.bin")
        package_lock_path = Path("evidence/production/package.lock")
        (repository_root / source_item_path).write_bytes(b"source-item")
        (repository_root / model_artifact_path).write_bytes(b"model-artifact")
        (repository_root / package_lock_path).write_bytes(b"package-lock")
        source_item_sha256 = cls._file_sha256(repository_root / source_item_path)
        model_artifact_sha256 = cls._file_sha256(repository_root / model_artifact_path)
        package_lock_sha256 = cls._file_sha256(repository_root / package_lock_path)

        case_manifest_path = Path("evidence/production/case-manifest.json")
        case_manifest = cls._source_root_dependency(
            artifact_id="formowl_methodology_case_manifest_dependency_v1",
            payload={
                "case_count": 100,
                "case_scope": "combined_independent_acceptance",
            },
        )
        case_manifest_sha256 = cls._write_json(
            repository_root / case_manifest_path,
            case_manifest,
        )
        configuration_manifest_path = Path("evidence/production/configuration-manifest.json")
        configuration_manifest = cls._source_root_dependency(
            artifact_id="formowl_methodology_configuration_manifest_dependency_v1",
            payload={
                "evaluation_policy_id": ("raw_source_oracle_same_pipeline_end_answer_v1"),
                "method_id": "evidence_to_knowledge_kg_ontology_v2_hybrid_v1",
                "tokenizer_id": ("jieba_sentencepiece_frozen_profile_candidate_admission_v1"),
            },
        )
        configuration_manifest_sha256 = cls._write_json(
            repository_root / configuration_manifest_path,
            configuration_manifest,
        )
        source_inventory_path = Path("evidence/production/source-inventory.json")
        source_inventory = cls._source_root_dependency(
            artifact_id="formowl_methodology_source_inventory_dependency_v1",
            dependency_paths=[source_item_path.as_posix()],
            payload={
                "source_count": 1,
                "source_item_count": 100,
                "source_hashes": [source_item_sha256],
                "source_paths": [source_item_path.as_posix()],
            },
        )
        source_inventory_sha256 = cls._write_json(
            repository_root / source_inventory_path,
            source_inventory,
        )

        source_manifest_path = Path("evidence/production/source-manifest.json")
        source_manifest = cls._with_internal_fingerprint(
            {
                "artifact_id": "formowl_methodology_source_manifest_v1",
                "execution_fingerprint": execution_fingerprint,
                "source_kind": "real_source",
                "source_count": 1,
                "source_item_count": 100,
                "source_hashes": [source_item_sha256],
                "case_manifest_sha256": case_manifest_sha256,
                "configuration_manifest_sha256": configuration_manifest_sha256,
                "model_artifact_hashes": [model_artifact_sha256],
                "package_lock_sha256": package_lock_sha256,
            },
            "manifest_fingerprint",
        )
        source_manifest_sha256 = cls._write_json(
            repository_root / source_manifest_path,
            source_manifest,
        )

        common_dependencies = [
            cls._dependency_entry(
                role="case_manifest",
                path=case_manifest_path,
                artifact=case_manifest,
                byte_sha256=case_manifest_sha256,
            ),
            cls._dependency_entry(
                role="configuration_manifest",
                path=configuration_manifest_path,
                artifact=configuration_manifest,
                byte_sha256=configuration_manifest_sha256,
            ),
            cls._dependency_entry(
                role="model_artifact",
                path=model_artifact_path,
                byte_sha256=model_artifact_sha256,
            ),
            cls._dependency_entry(
                role="package_lock",
                path=package_lock_path,
                byte_sha256=package_lock_sha256,
            ),
            cls._dependency_entry(
                role="source_inventory_manifest",
                path=source_inventory_path,
                artifact=source_inventory,
                byte_sha256=source_inventory_sha256,
            ),
            cls._dependency_entry(
                role="source_item",
                path=source_item_path,
                byte_sha256=source_item_sha256,
            ),
        ]

        for gate_id, evidence_path in evidence_paths.items():
            gate_dependencies: list[dict[str, object]] = []
            if gate_id == "source_completeness_compared_with_raw_oracle":
                oracle_path = Path("evidence/production/raw-source-oracle.json")
                oracle = cls._gate_dependency(
                    artifact_id=("formowl_methodology_raw_source_oracle_dependency_v1"),
                    gate_id=gate_id,
                    execution_fingerprint=execution_fingerprint,
                    source_manifest_sha256=source_manifest_sha256,
                    payload={
                        "raw_source_unit_count": 100,
                        "source_inventory_sha256": source_inventory_sha256,
                    },
                )
                oracle_sha256 = cls._write_json(repository_root / oracle_path, oracle)
                reconciliation_path = Path("evidence/production/observation-reconciliation.json")
                reconciliation = cls._gate_dependency(
                    artifact_id=("formowl_methodology_observation_reconciliation_dependency_v1"),
                    gate_id=gate_id,
                    execution_fingerprint=execution_fingerprint,
                    source_manifest_sha256=source_manifest_sha256,
                    payload={
                        "raw_source_unit_count": 100,
                        "emitted_observation_unit_count": 100,
                        "policy_redacted_unit_count": 0,
                        "unexplained_loss_unit_count": 0,
                        "loss_taxonomy_counts": {},
                        "raw_source_oracle_sha256": oracle_sha256,
                        "source_inventory_sha256": source_inventory_sha256,
                    },
                )
                reconciliation_sha256 = cls._write_json(
                    repository_root / reconciliation_path,
                    reconciliation,
                )
                result = {
                    "artifact_id": "formowl_raw_source_completeness_result_v1",
                    "execution_fingerprint": execution_fingerprint,
                    "source_manifest_sha256": source_manifest_sha256,
                    "status": "passed",
                    "raw_source_unit_count": 100,
                    "emitted_observation_unit_count": 100,
                    "policy_redacted_unit_count": 0,
                    "unexplained_loss_unit_count": 0,
                    "loss_taxonomy_counts": {},
                }
                gate_dependencies.extend(
                    (
                        cls._dependency_entry(
                            role="raw_source_oracle_manifest",
                            path=oracle_path,
                            artifact=oracle,
                            byte_sha256=oracle_sha256,
                        ),
                        cls._dependency_entry(
                            role="observation_reconciliation_report",
                            path=reconciliation_path,
                            artifact=reconciliation,
                            byte_sha256=reconciliation_sha256,
                        ),
                    )
                )
            elif gate_id == "evaluation_reports_bind_execution_fingerprint":
                report_path = Path("evidence/production/evaluation-report.json")
                report = cls._gate_dependency(
                    artifact_id="formowl_methodology_evaluation_report_dependency_v1",
                    gate_id=gate_id,
                    execution_fingerprint=execution_fingerprint,
                    source_manifest_sha256=source_manifest_sha256,
                    payload={
                        "case_manifest_sha256": case_manifest_sha256,
                        "evaluation_policy_fingerprint": (configuration_manifest_sha256),
                        "execution_status": "passed",
                        "quality_gate_status": "passed",
                        "report_kind": "completed_quality_report",
                    },
                )
                report_sha256 = cls._write_json(repository_root / report_path, report)
                report_index_path = Path("evidence/production/evaluation-report-index.json")
                report_index = cls._gate_dependency(
                    artifact_id=("formowl_methodology_evaluation_report_index_dependency_v1"),
                    gate_id=gate_id,
                    execution_fingerprint=execution_fingerprint,
                    source_manifest_sha256=source_manifest_sha256,
                    dependency_paths=[report_path.as_posix()],
                    payload={
                        "report_count": 1,
                        "report_hashes": [report_sha256],
                        "report_paths": [report_path.as_posix()],
                    },
                )
                report_index_sha256 = cls._write_json(
                    repository_root / report_index_path,
                    report_index,
                )
                result = {
                    "artifact_id": "formowl_execution_report_binding_result_v1",
                    "execution_fingerprint": execution_fingerprint,
                    "source_manifest_sha256": source_manifest_sha256,
                    "status": "passed",
                    "report_count": 1,
                    "bound_report_count": 1,
                    "unbound_report_count": 0,
                    "report_hashes": [report_sha256],
                }
                gate_dependencies.extend(
                    (
                        cls._dependency_entry(
                            role="evaluation_report",
                            path=report_path,
                            artifact=report,
                            byte_sha256=report_sha256,
                        ),
                        cls._dependency_entry(
                            role="evaluation_report_index",
                            path=report_index_path,
                            artifact=report_index,
                            byte_sha256=report_index_sha256,
                        ),
                    )
                )
            elif gate_id == "same_pipeline_real_source_ablation":
                result_hashes_by_arm: dict[str, str] = {}
                for arm_id in ("kg_only", "kg_plus_ontology_hybrid_v2"):
                    arm_path = Path(f"evidence/production/{arm_id}-result.json")
                    arm_result = cls._gate_dependency(
                        artifact_id=("formowl_methodology_ablation_arm_result_dependency_v1"),
                        gate_id=gate_id,
                        execution_fingerprint=execution_fingerprint,
                        source_manifest_sha256=source_manifest_sha256,
                        payload={
                            "arm_id": arm_id,
                            "case_count": 100,
                            "completed_case_count": 100,
                            "adjudicated_case_count": 100,
                            "case_manifest_sha256": case_manifest_sha256,
                            "evaluation_policy_fingerprint": (configuration_manifest_sha256),
                            "execution_status": "passed",
                            "quality_gate_status": "passed",
                        },
                    )
                    arm_sha256 = cls._write_json(
                        repository_root / arm_path,
                        arm_result,
                    )
                    result_hashes_by_arm[arm_id] = arm_sha256
                    gate_dependencies.append(
                        cls._dependency_entry(
                            role="ablation_arm_result",
                            path=arm_path,
                            artifact=arm_result,
                            byte_sha256=arm_sha256,
                        )
                    )
                result = {
                    "artifact_id": ("formowl_same_pipeline_real_source_ablation_result_v1"),
                    "execution_fingerprint": execution_fingerprint,
                    "source_manifest_sha256": source_manifest_sha256,
                    "status": "passed",
                    "arm_ids": ["kg_only", "kg_plus_ontology_hybrid_v2"],
                    "case_count": 100,
                    "completed_case_count": 100,
                    "adjudicated_case_count": 100,
                    "same_source_manifest": True,
                    "same_case_manifest": True,
                    "same_evaluation_policy": True,
                    "result_hashes_by_arm": result_hashes_by_arm,
                }
            else:
                final_report_path = Path("evidence/production/final-answer-acceptance-report.json")
                final_report_payload = {
                    "acceptance_profile_id": "real_user_end_answer_strict_v1",
                    "acceptance_scope": "independent_holdout_and_transfer",
                    "case_count": 100,
                    "adjudicated_case_count": 100,
                    "answerable_case_count": 90,
                    "correct_answer_count": 81,
                    "citation_supported_correct_count": 81,
                    "permission_denial_case_count": 10,
                    "permission_denial_pass_count": 10,
                    "observed_accuracy_ppm": 900_000,
                    "observed_citation_support_ppm": 1_000_000,
                    "case_manifest_sha256": case_manifest_sha256,
                    "evaluation_policy_fingerprint": configuration_manifest_sha256,
                    "execution_status": "passed",
                    "quality_gate_status": "passed",
                }
                final_report = cls._gate_dependency(
                    artifact_id=("formowl_methodology_final_answer_acceptance_dependency_v1"),
                    gate_id=gate_id,
                    execution_fingerprint=execution_fingerprint,
                    source_manifest_sha256=source_manifest_sha256,
                    payload=final_report_payload,
                )
                final_report_sha256 = cls._write_json(
                    repository_root / final_report_path,
                    final_report,
                )
                result = {
                    "artifact_id": "formowl_real_user_end_answer_result_v1",
                    "execution_fingerprint": execution_fingerprint,
                    "source_manifest_sha256": source_manifest_sha256,
                    "status": "passed",
                    **{
                        key: value
                        for key, value in final_report_payload.items()
                        if key
                        not in {
                            "acceptance_scope",
                            "case_manifest_sha256",
                            "evaluation_policy_fingerprint",
                            "execution_status",
                            "quality_gate_status",
                        }
                    },
                }
                gate_dependencies.append(
                    cls._dependency_entry(
                        role="final_answer_acceptance_report",
                        path=final_report_path,
                        artifact=final_report,
                        byte_sha256=final_report_sha256,
                    )
                )

            result = cls._with_internal_fingerprint(result, "result_fingerprint")
            result_path = Path(f"evidence/production/{gate_id}-result.json")
            result_sha256 = cls._write_json(repository_root / result_path, result)
            dependencies = sorted(
                [*common_dependencies, *gate_dependencies],
                key=lambda item: (str(item["role"]), str(item["path"])),
            )
            dependency_manifest = cls._with_internal_fingerprint(
                {
                    "artifact_id": ("formowl_methodology_gate_dependency_manifest_v1"),
                    "gate_id": gate_id,
                    "execution_fingerprint": execution_fingerprint,
                    "source_manifest_path": source_manifest_path.as_posix(),
                    "source_manifest_sha256": source_manifest_sha256,
                    "result_artifact_path": result_path.as_posix(),
                    "result_artifact_sha256": result_sha256,
                    "dependencies": dependencies,
                },
                "manifest_fingerprint",
            )
            dependency_manifest_path = (
                methodology_authority.methodology_gate_dependency_manifest_path(result_path)
            )
            dependency_manifest_sha256 = cls._write_json(
                repository_root / dependency_manifest_path,
                dependency_manifest,
            )
            evidence = cls._with_internal_fingerprint(
                {
                    "artifact_id": "formowl_methodology_gate_evidence_v3",
                    "schema_version": 1,
                    "authority_id": provisional.authority_id,
                    "gate_id": gate_id,
                    "execution_fingerprint": execution_fingerprint,
                    "validator_id": {
                        "source_completeness_compared_with_raw_oracle": (
                            "raw_source_completeness_validator_v1"
                        ),
                        "evaluation_reports_bind_execution_fingerprint": (
                            "execution_report_binding_validator_v1"
                        ),
                        "same_pipeline_real_source_ablation": (
                            "same_pipeline_real_source_ablation_validator_v1"
                        ),
                        "real_user_end_answer_acceptance": (
                            "real_user_end_answer_acceptance_validator_v1"
                        ),
                    }[gate_id],
                    "source_manifest_path": source_manifest_path.as_posix(),
                    "source_manifest_sha256": source_manifest_sha256,
                    "result_artifact_path": result_path.as_posix(),
                    "result_artifact_sha256": result_sha256,
                    "dependency_manifest_path": dependency_manifest_path.as_posix(),
                    "dependency_manifest_sha256": dependency_manifest_sha256,
                    "dependency_manifest_fingerprint": dependency_manifest["manifest_fingerprint"],
                    "dependency_count": len(dependencies),
                    "status": "passed",
                    "evidence_classification": "production",
                    "promotion_status": "not_performed",
                },
                "envelope_fingerprint",
            )
            cls._write_json(repository_root / evidence_path, evidence)
        return evidence_paths

    @classmethod
    def _source_root_dependency(
        cls,
        *,
        artifact_id: str,
        payload: dict[str, object],
        dependency_paths: list[str] | None = None,
    ) -> dict[str, object]:
        return cls._with_internal_fingerprint(
            {
                "artifact_id": artifact_id,
                "dependency_paths": sorted(dependency_paths or []),
                "payload": payload,
            },
            "artifact_fingerprint",
        )

    @classmethod
    def _gate_dependency(
        cls,
        *,
        artifact_id: str,
        gate_id: str,
        execution_fingerprint: str,
        source_manifest_sha256: str,
        payload: dict[str, object],
        dependency_paths: list[str] | None = None,
    ) -> dict[str, object]:
        return cls._with_internal_fingerprint(
            {
                "artifact_id": artifact_id,
                "gate_id": gate_id,
                "execution_fingerprint": execution_fingerprint,
                "source_manifest_sha256": source_manifest_sha256,
                "status": "passed",
                "evidence_classification": "production",
                "dependency_paths": sorted(dependency_paths or []),
                "payload": payload,
            },
            "artifact_fingerprint",
        )

    @staticmethod
    def _dependency_entry(
        *,
        role: str,
        path: Path,
        byte_sha256: str,
        artifact: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return {
            "role": role,
            "path": path.as_posix(),
            "artifact_id": artifact["artifact_id"] if artifact is not None else None,
            "byte_sha256": byte_sha256,
            "internal_fingerprint_field": (
                "artifact_fingerprint" if artifact is not None else None
            ),
            "internal_fingerprint": (
                artifact["artifact_fingerprint"] if artifact is not None else None
            ),
        }

    @staticmethod
    def _with_internal_fingerprint(
        payload: dict[str, object],
        field_name: str,
    ) -> dict[str, object]:
        result = dict(payload)
        result.pop(field_name, None)
        encoded = json.dumps(
            result,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        result[field_name] = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
        return result

    @staticmethod
    def _write_json(path: Path, payload: dict[str, object]) -> str:
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    @staticmethod
    def _file_sha256(path: Path) -> str:
        return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"

    @staticmethod
    def _copy_authority_fixture(repository_root: Path) -> None:
        paths = {
            Path("AGENTS.md"),
            Path("pyproject.toml"),
            Path("containers/dev/Dockerfile"),
            Path("SPEC.md"),
            Path("docs/methodology-authority.json"),
            Path("docs/agent-goals/kg-research-agent.md"),
            Path("docs/kg-ontology-v2-runtime-evaluation-plan.md"),
            Path("docs/kg-research-method.md"),
            Path(
                "experiments/kg_ontology_v2_coordination/results/"
                "procurement_full_pst_domain_hard_summary_2026-07-09.json"
            ),
            Path("RESOURCE_EXTRACTION_SPEC.md"),
            Path("scripts/methodology_authority_check.py"),
            Path("scripts/kg_research_acceptance_suite.py"),
            Path("scripts/issue56_semantic_execution_smoke.py"),
            Path("scripts/issue56_tokenizer_profile_smoke.py"),
            Path("scripts/mail_full_pst_domain_hard_case_eval.py"),
            Path("scripts/mail_full_pst_domain_hard_kg_fusion_eval.py"),
            Path("scripts/mail_full_pst_domain_hard_ontology_ablation_eval.py"),
            Path("scripts/mail_full_pst_domain_hard_ontology_factorial_eval.py"),
            Path("scripts/mail_full_pst_exm_lexical_ontology_eval.py"),
            Path("tests/test_issue56_semantic_execution_e2e.py"),
            Path("tests/test_issue56_tokenizer_profile_e2e.py"),
        }
        for relative_root in (
            Path("python/formowl_contract"),
            Path("python/formowl_core"),
            Path("python/formowl_graph"),
            Path("python/formowl_mail"),
        ):
            paths.update(
                source.relative_to(ROOT)
                for source in (ROOT / relative_root).rglob("*.py")
                if source.is_file()
            )
        paths.update(
            source.relative_to(ROOT)
            for source in (
                ROOT / "python/formowl_core/tokenizer_profiles/"
                "jieba_sentencepiece_frozen_profile_candidate_admission_v1"
            ).iterdir()
            if source.is_file()
        )
        for relative_path in sorted(paths):
            source = ROOT / relative_path
            target = repository_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())


if __name__ == "__main__":
    unittest.main()
