from __future__ import annotations

import copy
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import _paths  # noqa: F401


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "oauth_mcp_harness.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("oauth_mcp_harness", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load issue #20 OAuth MCP harness")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OAuthMcpHarnessScriptTests(unittest.TestCase):
    def test_primary_harness_passes_without_live_or_closure_overclaim(self) -> None:
        module = _load_module()

        # The real CLI is the independent primary gate. A unittest that invokes
        # that gate can be selected by the manifest and recursively run itself.
        report = _run_passing_report(module)
        local_context = _passing_local_completion_context(module)

        self.assertTrue(report["validation"]["passed"])
        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["metrics"]["deterministic_fake_e2e_passed"])
        self.assertTrue(report["claim_boundary"]["supports_deterministic_fake_oauth_mcp_e2e_claim"])
        self.assertFalse(report["claim_boundary"]["supports_live_postgresql_rollback_claim"])
        self.assertFalse(report["claim_boundary"]["supports_operator_cli_postgresql_claim"])
        self.assertFalse(report["claim_boundary"]["supports_production_container_lifecycle_claim"])
        self.assertFalse(report["claim_boundary"]["supports_mcp_inspector_remote_claim"])
        self.assertFalse(report["claim_boundary"]["supports_live_https_chatgpt_google_claim"])
        self.assertFalse(
            report["claim_boundary"]["supports_external_evidence_packet_contract_claim"]
        )
        self.assertFalse(report["claim_boundary"]["supports_issue20_closure_claim"])
        self.assertTrue(report["claim_boundary"]["requires_independent_issue20_completion_audit"])
        self.assertFalse(report["claim_boundary"]["supports_production_ready_claim"])
        self.assertTrue(
            module.validate_report(report, _local_completion_context=local_context)["passed"]
        )

    def test_run_oauth_mcp_harness_direct_success_is_safe_and_side_effect_free(
        self,
    ) -> None:
        module = _load_module()
        private_marker = "private-path-marker:/not/a/public/report"
        evidence = {**_passing_evidence(), "private_marker": private_marker}
        evidence_before = copy.deepcopy(evidence)
        manifest = module.load_function_harness_manifest()
        manifest_before = copy.deepcopy(manifest)
        runner_inputs: list[object] = []
        suite_inputs: list[object] = []

        def run_evidence():
            runner_inputs.append(None)
            return evidence

        def run_suite(received_manifest):
            suite_inputs.append(received_manifest)
            return _passing_suite_evidence(received_manifest)

        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.object(
                module,
                "load_function_harness_manifest",
                return_value=manifest,
            ),
            patch.object(
                module,
                "validate_function_harness_manifest",
                side_effect=lambda value: _passing_onboarding(module, value),
            ),
            patch.object(module, "write_json_atomic") as atomic_writer,
            patch.object(Path, "mkdir") as mkdir,
            patch.object(Path, "replace") as replace,
            patch.object(Path, "unlink") as unlink,
            patch.object(Path, "write_bytes") as write_bytes,
            patch.object(Path, "write_text") as write_text,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            report = module.run_oauth_mcp_harness(
                runner=run_evidence,
                manifest_suite_runner=run_suite,
            )

        self.assertEqual(runner_inputs, [None])
        self.assertEqual(suite_inputs, [manifest])
        self.assertEqual(evidence, evidence_before)
        self.assertEqual(manifest, manifest_before)
        self.assertEqual(
            set(report),
            {
                "report_type",
                "status",
                "implementation_base_hash",
                "metrics",
                "safe_outputs",
                "evidence_layers",
                "claim_boundary",
                "validation",
            },
        )
        self.assertEqual(report["status"], "passed")
        self.assertEqual(
            report["validation"],
            {"passed": True, "status": "passed", "blocker_count": 0},
        )
        self.assertTrue(report["metrics"]["deterministic_fake_e2e_passed"])
        self.assertTrue(report["claim_boundary"]["supports_deterministic_fake_oauth_mcp_e2e_claim"])
        self.assertFalse(
            report["claim_boundary"]["supports_external_evidence_packet_contract_claim"]
        )
        self.assertFalse(report["claim_boundary"]["supports_issue20_closure_claim"])
        self.assertTrue(report["claim_boundary"]["requires_independent_issue20_completion_audit"])
        self.assertFalse(report["claim_boundary"]["supports_production_ready_claim"])
        module.assert_safe_harness_report(report)
        rendered = json.dumps(report, sort_keys=True)
        self.assertNotIn(private_marker, rendered)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        atomic_writer.assert_not_called()
        mkdir.assert_not_called()
        replace.assert_not_called()
        unlink.assert_not_called()
        write_bytes.assert_not_called()
        write_text.assert_not_called()

    def test_report_shape_is_hash_status_count_boolean_only_and_deterministic(self) -> None:
        module = _load_module()
        first = _run_passing_report(module)
        second = _run_passing_report(module)

        self.assertEqual(first["safe_outputs"], second["safe_outputs"])
        self.assertTrue(first["validation"]["passed"])
        rendered = json.dumps(first, sort_keys=True)
        for forbidden in (
            "invited-alpha@example.test",
            "authorization: bearer",
            "code_verifier",
            "id_token",
            "client_state",
            "select * from",
            "/workspace/",
        ):
            self.assertNotIn(forbidden, rendered.lower())

    def test_validator_rejects_sensitive_fields_tampering_and_live_overclaims(self) -> None:
        module = _load_module()
        base = _run_passing_report(module)
        local_context = _passing_local_completion_context(module)
        cases = []

        leaked = copy.deepcopy(base)
        leaked["access_token"] = "eyJhbGciOiJSUzI1NiJ9.payload.signature"
        cases.append(leaked)

        overclaim = copy.deepcopy(base)
        overclaim["claim_boundary"]["supports_live_https_chatgpt_google_claim"] = True
        overclaim["claim_boundary"]["supports_issue20_closure_claim"] = True
        cases.append(overclaim)

        inconsistent = copy.deepcopy(base)
        inconsistent["metrics"]["revocation_immediate"] = False
        inconsistent["metrics"]["deterministic_fake_e2e_passed"] = True
        cases.append(inconsistent)

        raw_path = copy.deepcopy(base)
        raw_path["safe_outputs"]["scenario_contract_hash"] = "/workspace/private/result.json"
        cases.append(raw_path)

        for index, report in enumerate(cases):
            with self.subTest(index=index):
                validation = module.validate_report(
                    report,
                    _local_completion_context=local_context,
                )
                self.assertFalse(validation["passed"])
                self.assertGreater(validation["blocker_count"], 0)

    def test_validator_rejects_unsupported_operator_cli_postgresql_status(self) -> None:
        module = _load_module()
        report = _run_passing_report(module)
        local_context = _passing_local_completion_context(module)
        report.pop("validation")
        report["evidence_layers"]["operator_cli_postgresql_status"] = "unsupported"

        validation = module.validate_report(
            report,
            _local_completion_context=local_context,
        )

        self.assertFalse(validation["passed"])
        self.assertGreater(validation["blocker_count"], 0)

    def test_validator_rejects_forged_external_claims_without_source_packet(self) -> None:
        module = _load_module()
        report = _run_passing_report(module)
        local_context = _passing_local_completion_context(module)
        report.pop("validation")
        for status_key in module._EXTERNAL_REPORT_STATUS_FIELDS.values():
            report["evidence_layers"][status_key] = "passed"
        hash_keys = (
            "external_evidence_packet_hash",
            *module._EXTERNAL_REPORT_ARTIFACT_FIELDS.values(),
        )
        for index, hash_key in enumerate(hash_keys, start=1):
            report["safe_outputs"][hash_key] = f"sha256:{index:064x}"
        report["safe_outputs"]["external_evidence_blocker_count"] = 0
        for claim_key in (
            "supports_live_postgresql_rollback_claim",
            "supports_operator_cli_postgresql_claim",
            "supports_production_container_lifecycle_claim",
            "supports_mcp_inspector_remote_claim",
            "supports_live_https_chatgpt_google_claim",
            "supports_external_evidence_packet_contract_claim",
        ):
            report["claim_boundary"][claim_key] = True

        validation = module.validate_report(
            report,
            _local_completion_context=local_context,
        )

        self.assertFalse(validation["passed"])
        self.assertGreater(validation["blocker_count"], 0)

    def test_external_claim_report_revalidation_rejects_missing_packet(self) -> None:
        module = _load_module()
        packet = _valid_external_evidence(module)
        report = _run_passing_report(module, external_evidence=packet)
        local_context = _passing_local_completion_context(module)

        validation = module.validate_report(
            report,
            _local_completion_context=local_context,
        )

        self.assertFalse(validation["passed"])
        self.assertGreater(validation["blocker_count"], 0)

    def test_external_claim_report_revalidation_rejects_wrong_packet(self) -> None:
        module = _load_module()
        packet = _valid_external_evidence(module)
        report = _run_passing_report(module, external_evidence=packet)
        local_context = _passing_local_completion_context(module)
        wrong_packet = copy.deepcopy(packet)
        wrong_packet["layers"]["reviewer_gate"]["source_evidence_artifact_hash"] = (
            module.sha256_json({"external_evidence": "wrong-reviewer-source"})
        )

        validation = module.validate_report(
            report,
            external_evidence=wrong_packet,
            operator_execution_authority_pin=(_valid_operator_journey_authority_pin(module)),
            _local_completion_context=local_context,
        )

        self.assertFalse(validation["passed"])
        self.assertGreater(validation["blocker_count"], 0)

    def test_external_claim_report_revalidation_accepts_matching_packet(self) -> None:
        module = _load_module()
        packet = _valid_external_evidence(module)
        report = _run_passing_report(module, external_evidence=packet)
        local_context = _passing_local_completion_context(module)

        validation = module.validate_report(
            report,
            external_evidence=packet,
            operator_execution_authority_pin=(_valid_operator_journey_authority_pin(module)),
            _local_completion_context=local_context,
        )

        self.assertTrue(validation["passed"])
        self.assertEqual(validation["blocker_count"], 0)

    def test_cli_validation_returns_nonzero_for_tampered_report(self) -> None:
        module = _load_module()
        temp_dir = _paths.fresh_test_dir("issue20-oauth-mcp-harness-tampered-validation")
        report_path = temp_dir / "tampered-report.json"
        output_path = temp_dir / "validation.json"
        report = _run_passing_report(module)
        local_context = _passing_local_completion_context(module)
        report["claim_boundary"]["supports_production_ready_claim"] = True
        report.pop("validation")
        report["validation"] = module.validate_report(
            report,
            _local_completion_context=local_context,
        )
        self.assertFalse(report["validation"]["passed"])
        report_path.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")

        with patch.object(
            module,
            "_run_local_completion_context",
            return_value=local_context,
        ):
            exit_code = module.main(
                [
                    "--validate-report",
                    str(report_path),
                    "--output",
                    str(output_path),
                ]
            )

        self.assertEqual(exit_code, 1)
        validation = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertFalse(validation["passed"])

    def test_valid_external_packet_enables_bounded_claims_but_not_issue_closure(self) -> None:
        module = _load_module()
        packet = _valid_external_evidence(module)

        external_validation = _validate_external_packet(module, packet)
        report = _run_passing_report(module, external_evidence=packet)

        self.assertTrue(external_validation["passed"])
        self.assertEqual(external_validation["blocker_count"], 0)
        self.assertEqual(set(external_validation["layer_statuses"].values()), {"passed"})
        source_commitments = [
            packet["layers"][layer_name][field]
            for layer_name, field in module._EXTERNAL_SOURCE_COMMITMENT_FIELDS
        ]
        self.assertEqual(len(source_commitments), len(set(source_commitments)))
        public_artifacts = [
            packet["layers"][layer_name]["evidence_artifact_hash"]
            for layer_name in module._EXTERNAL_LAYER_FIELDS
        ]
        self.assertTrue(set(source_commitments).isdisjoint(public_artifacts))
        self.assertTrue(report["validation"]["passed"])
        self.assertTrue(report["claim_boundary"]["supports_live_postgresql_rollback_claim"])
        self.assertTrue(report["claim_boundary"]["supports_operator_cli_postgresql_claim"])
        self.assertTrue(report["claim_boundary"]["supports_production_container_lifecycle_claim"])
        self.assertTrue(report["claim_boundary"]["supports_mcp_inspector_remote_claim"])
        self.assertTrue(report["claim_boundary"]["supports_live_https_chatgpt_google_claim"])
        self.assertTrue(
            report["claim_boundary"]["supports_external_evidence_packet_contract_claim"]
        )
        self.assertFalse(report["claim_boundary"]["supports_issue20_closure_claim"])
        self.assertTrue(report["claim_boundary"]["requires_independent_issue20_completion_audit"])
        self.assertFalse(report["claim_boundary"]["supports_production_ready_claim"])

    def test_external_layer_count_validator_accepts_exact_layers_without_mutation(self) -> None:
        module = _load_module()
        layers = _valid_external_evidence(module)["layers"]

        self.assertEqual(set(layers), set(module._EXTERNAL_LAYER_FIELDS))
        for layer_name, layer in layers.items():
            with self.subTest(layer=layer_name):
                original = copy.deepcopy(layer)
                blockers: list[str] = []

                module._validate_external_layer_counts(layer_name, layer, blockers)

                self.assertEqual(blockers, [])
                self.assertEqual(layer, original)

    def test_external_layer_count_validator_rejects_invalid_counts_without_mutation(
        self,
    ) -> None:
        module = _load_module()
        layers = _valid_external_evidence(module)["layers"]

        for layer_name, layer in layers.items():
            count_fields = sorted(
                field
                for field in module._EXTERNAL_LAYER_FIELDS[layer_name]
                if field.endswith("_count")
            )
            self.assertTrue(count_fields)
            for field in count_fields:
                with self.subTest(layer=layer_name, field=field, invalid="bool"):
                    invalid = copy.deepcopy(layer)
                    invalid[field] = True
                    original = copy.deepcopy(invalid)
                    blockers = ["existing blocker"]

                    module._validate_external_layer_counts(layer_name, invalid, blockers)

                    self.assertEqual(blockers[0], "existing blocker")
                    self.assertIn(
                        f"external evidence count is invalid: {layer_name}.{field}",
                        blockers,
                    )
                    self.assertEqual(invalid, original)

        for invalid_value in ("1", -1):
            with self.subTest(invalid=invalid_value):
                invalid = copy.deepcopy(layers["reviewer_gate"])
                invalid["reviewer_count"] = invalid_value
                original = copy.deepcopy(invalid)
                blockers: list[str] = []

                module._validate_external_layer_counts(
                    "reviewer_gate",
                    invalid,
                    blockers,
                )

                self.assertIn(
                    "external evidence count is invalid: reviewer_gate.reviewer_count",
                    blockers,
                )
                self.assertEqual(invalid, original)

        lifecycle_one_run_updates = {
            "run_count": 1,
            "pass_count": 1,
            "stateful_restart_count": 1,
        }
        for field in module._LIFECYCLE_EXTERNAL_COUNT_SOURCES:
            if field != "compose_service_count":
                lifecycle_one_run_updates[field] = (
                    layers["production_container_lifecycle"][field] // 2
                )

        cases = (
            (
                "live_postgresql",
                {"endpoint_scheme": "https"},
                "live PostgreSQL evidence must identify only the postgresql scheme",
            ),
            (
                "live_postgresql",
                {"run_count": 0, "pass_count": 0},
                "live PostgreSQL evidence must include at least one executed run",
            ),
            (
                "live_postgresql",
                {"pass_count": 0},
                "live PostgreSQL evidence run and pass counts must match",
            ),
            (
                "live_postgresql",
                {"failure_count": 1},
                "live PostgreSQL evidence cannot contain failures or skips",
            ),
            (
                "live_postgresql",
                {"skip_count": 1},
                "live PostgreSQL evidence cannot contain failures or skips",
            ),
            (
                "live_postgresql",
                {"transaction_rollback_probe_count": 0},
                "live PostgreSQL evidence must include a rollback probe",
            ),
            (
                "live_postgresql",
                {"production_smoke_probe_count": 0},
                "live PostgreSQL evidence must include a production smoke probe",
            ),
            (
                "live_postgresql",
                {"expiry_denial_count": 0},
                "live PostgreSQL evidence requires expiry_denial_count=1",
            ),
            (
                "live_postgresql",
                {"persisted_audit_count": 0},
                "live PostgreSQL evidence must include persisted audit rows",
            ),
            (
                "live_postgresql",
                {"private_signing_key_exposure_count": 1},
                "live PostgreSQL evidence requires private_signing_key_exposure_count=0",
            ),
            (
                "operator_cli_postgresql",
                {"endpoint_scheme": "postgresql"},
                "operator CLI PostgreSQL evidence must use container scope",
            ),
            (
                "operator_cli_postgresql",
                {"run_count": 0},
                "operator CLI PostgreSQL evidence requires run_count=1",
            ),
            (
                "production_container_lifecycle",
                {"endpoint_scheme": "https"},
                "production container lifecycle evidence must use container scope",
            ),
            (
                "production_container_lifecycle",
                lifecycle_one_run_updates,
                "production container lifecycle requires two fresh runs",
            ),
            (
                "production_container_lifecycle",
                {"pass_count": 1},
                "production container lifecycle run and pass counts must match",
            ),
            (
                "production_container_lifecycle",
                {"failure_count": 1},
                "production container lifecycle cannot contain failures or skips",
            ),
            (
                "production_container_lifecycle",
                {"skip_count": 1},
                "production container lifecycle cannot contain failures or skips",
            ),
            (
                "production_container_lifecycle",
                {"sigterm_clean_exit_count": 7},
                "production container lifecycle requires sigterm_clean_exit_count=8",
            ),
            (
                "production_container_lifecycle",
                {"compose_service_count": 9},
                "production container lifecycle requires at least five Compose services per run",
            ),
            (
                "mcp_inspector",
                {"endpoint_scheme": "http"},
                "MCP Inspector evidence must use a remote HTTPS endpoint",
            ),
            (
                "mcp_inspector",
                {"protected_tool_challenge_count": 0},
                "MCP Inspector evidence requires protected_tool_challenge_count=1",
            ),
            (
                "live_chatgpt_google",
                {"endpoint_scheme": "http"},
                "live ChatGPT and Google evidence must use public HTTPS",
            ),
            (
                "live_chatgpt_google",
                {"expiry_denial_count": 0},
                "live ChatGPT and Google evidence requires expiry_denial_count=1",
            ),
            (
                "reviewer_gate",
                {"reviewer_count": 2, "agreement_count": 2},
                "reviewer evidence must contain the configured three reviewers",
            ),
            (
                "reviewer_gate",
                {"agreement_count": 2},
                "every configured reviewer must explicitly agree",
            ),
            (
                "reviewer_gate",
                {"blocking_finding_count": 1},
                "reviewer evidence cannot retain a blocking finding",
            ),
            (
                "completion_audit",
                {"journey_count": len(module._ISSUE20_COMPLETION_JOURNEYS) - 1},
                (
                    "completion audit requires "
                    f"journey_count={len(module._ISSUE20_COMPLETION_JOURNEYS)}"
                ),
            ),
            (
                "completion_audit",
                {"passed_journey_count": len(module._ISSUE20_COMPLETION_JOURNEYS) - 1},
                (
                    "completion audit requires "
                    f"passed_journey_count={len(module._ISSUE20_COMPLETION_JOURNEYS)}"
                ),
            ),
            (
                "completion_audit",
                {"missing_journey_count": 1},
                "completion audit cannot omit a required journey",
            ),
            (
                "completion_audit",
                {"blocking_finding_count": 1},
                "completion audit cannot retain a blocking finding",
            ),
        )
        for layer_name, updates, expected_blocker in cases:
            with self.subTest(layer=layer_name, updates=updates):
                invalid = copy.deepcopy(layers[layer_name])
                invalid.update(updates)
                original = copy.deepcopy(invalid)
                blockers: list[str] = []

                module._validate_external_layer_counts(layer_name, invalid, blockers)

                self.assertIn(expected_blocker, blockers)
                self.assertEqual(invalid, original)

    def test_lifecycle_reports_aggregate_and_bind_without_enabling_completion(self) -> None:
        module = _load_module()
        first = _valid_lifecycle_report(module, "first")
        second = _valid_lifecycle_report(module, "second")

        layer = module.aggregate_production_container_lifecycle_reports(
            [first, second],
            operator_attested=True,
        )
        layer_validation = module.validate_production_container_lifecycle_external_layer(layer)
        report = _run_passing_report(
            module,
            production_container_lifecycle_evidence=layer,
        )

        self.assertTrue(layer_validation["passed"])
        self.assertEqual(layer["run_count"], 2)
        self.assertEqual(layer["pass_count"], 2)
        self.assertEqual(layer["runtime_process_start_count"], 8)
        self.assertEqual(layer["sigterm_clean_exit_count"], 8)
        self.assertEqual(layer["database_release_count"], 8)
        self.assertEqual(layer["operator_owned_0400_secret_count"], 14)
        self.assertEqual(layer["compose_migration_success_count"], 2)
        self.assertEqual(layer["compose_preflight_success_count"], 2)
        self.assertEqual(layer["compose_secret_snapshot_count"], 6)
        self.assertEqual(layer["compose_old_snapshot_retirement_count"], 4)
        self.assertEqual(layer["compose_runtime_process_uid"], 10001)
        self.assertEqual(layer["runtime_process_uid"], 10001)
        self.assertEqual(layer["jwks_overlap_public_key_count"], 4)
        expected_run_report_set_hash = module.sha256_json(
            {
                "binding_type": "production_container_lifecycle_run_report_set_v1",
                "report_hashes": sorted([module.sha256_json(first), module.sha256_json(second)]),
            }
        )
        self.assertEqual(layer["run_report_set_hash"], expected_run_report_set_hash)
        layer_without_artifact_hash = {
            key: value for key, value in layer.items() if key != "evidence_artifact_hash"
        }
        self.assertEqual(
            layer["evidence_artifact_hash"],
            module.sha256_json(
                {
                    "binding_type": module._LIFECYCLE_EXTERNAL_LAYER_BINDING_TYPE,
                    "layer_without_artifact_hash": layer_without_artifact_hash,
                }
            ),
        )
        hash_values = [
            layer[field]
            for field in module._EXTERNAL_LAYER_FIELDS["production_container_lifecycle"]
            if field.endswith("_hash")
        ]
        self.assertEqual(len(hash_values), len(set(hash_values)))
        self.assertTrue(report["validation"]["passed"])
        self.assertEqual(
            report["evidence_layers"]["production_container_lifecycle_status"],
            "passed",
        )
        self.assertTrue(report["claim_boundary"]["supports_production_container_lifecycle_claim"])
        self.assertEqual(
            report["safe_outputs"]["production_container_lifecycle_artifact_hash"],
            layer["evidence_artifact_hash"],
        )
        self.assertFalse(report["claim_boundary"]["supports_live_postgresql_rollback_claim"])
        self.assertFalse(report["claim_boundary"]["supports_mcp_inspector_remote_claim"])
        self.assertFalse(report["claim_boundary"]["supports_live_https_chatgpt_google_claim"])
        self.assertFalse(
            report["claim_boundary"]["supports_external_evidence_packet_contract_claim"]
        )
        self.assertFalse(report["claim_boundary"]["supports_issue20_closure_claim"])
        self.assertFalse(report["claim_boundary"]["supports_production_ready_claim"])

    def test_lifecycle_claim_report_revalidation_requires_matching_source_layer(self) -> None:
        module = _load_module()
        layer = module.aggregate_production_container_lifecycle_reports(
            [
                _valid_lifecycle_report(module, "first"),
                _valid_lifecycle_report(module, "second"),
            ],
            operator_attested=True,
        )
        report = _run_passing_report(
            module,
            production_container_lifecycle_evidence=layer,
        )
        local_context = _passing_local_completion_context(module)
        wrong_layer = copy.deepcopy(layer)
        wrong_layer["run_report_set_hash"] = module.sha256_json(
            {"external_evidence": "wrong-lifecycle-source"}
        )

        missing_validation = module.validate_report(
            report,
            _local_completion_context=local_context,
        )
        matching_validation = module.validate_report(
            report,
            production_container_lifecycle_evidence=layer,
            _local_completion_context=local_context,
        )
        wrong_validation = module.validate_report(
            report,
            production_container_lifecycle_evidence=wrong_layer,
            _local_completion_context=local_context,
        )

        self.assertFalse(missing_validation["passed"])
        self.assertTrue(matching_validation["passed"])
        self.assertFalse(wrong_validation["passed"])

    def test_lifecycle_aggregate_rejects_duplicate_tampered_and_unattested_reports(self) -> None:
        module = _load_module()
        first = _valid_lifecycle_report(module, "first")
        second = _valid_lifecycle_report(module, "second")
        forward = module.aggregate_production_container_lifecycle_reports(
            [first, second],
            operator_attested=True,
        )
        reversed_order = module.aggregate_production_container_lifecycle_reports(
            [second, first],
            operator_attested=True,
        )

        self.assertEqual(forward, reversed_order)

        cases = []
        cases.append(("lifecycle_duplicate_report_rejected", [first, first], True))
        tampered = copy.deepcopy(second)
        tampered["claim_boundary"]["production_readiness"] = True
        cases.append(("lifecycle_report_invalid", [first, tampered], True))
        stale_schema = copy.deepcopy(second)
        stale_schema["safe_hashes"]["migration_initial_result_hash"] = "sha256:" + "f" * 64
        cases.append(("lifecycle_static_fingerprint_mismatch", [first, stale_schema], True))
        cases.append(("lifecycle_operator_attestation_missing", [first, second], False))

        for expected_code, reports, attested in cases:
            with self.subTest(code=expected_code):
                with self.assertRaises(module.LifecycleEvidenceError) as raised:
                    module.aggregate_production_container_lifecycle_reports(
                        reports,
                        operator_attested=attested,
                    )
                self.assertEqual(raised.exception.code, expected_code)

    def test_evidence_errors_map_hostile_codes_to_generic_fallbacks_without_side_effects(
        self,
    ) -> None:
        module = _load_module()
        temp_dir = _paths.fresh_test_dir("issue20-evidence-error-hostile-code")
        sentinel_path = temp_dir / "sentinel.json"
        sentinel_bytes = b'{"authority":"unchanged"}\n'
        sentinel_path.write_bytes(sentinel_bytes)
        hostile_code = "private/path/secret"
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            lifecycle_error = module.LifecycleEvidenceError(hostile_code)
            operator_error = module.OperatorEvidenceError(hostile_code)

        self.assertEqual(lifecycle_error.code, "lifecycle_evidence_invalid")
        self.assertEqual(lifecycle_error.args, ("lifecycle_evidence_invalid",))
        self.assertEqual(str(lifecycle_error), "lifecycle_evidence_invalid")
        self.assertEqual(operator_error.code, "operator_evidence_invalid")
        self.assertEqual(operator_error.args, ("operator_evidence_invalid",))
        self.assertEqual(str(operator_error), "operator_evidence_invalid")
        rendered = json.dumps(
            {
                "lifecycle_code": lifecycle_error.code,
                "lifecycle_message": str(lifecycle_error),
                "operator_code": operator_error.code,
                "operator_message": str(operator_error),
            },
            sort_keys=True,
        )
        self.assertNotIn(hostile_code, rendered)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(sentinel_path.read_bytes(), sentinel_bytes)
        self.assertEqual([path.name for path in temp_dir.iterdir()], ["sentinel.json"])

    def test_cli_aggregates_and_binds_lifecycle_reports_without_exposing_paths(self) -> None:
        module = _load_module()
        temp_dir = _paths.fresh_test_dir("issue20-lifecycle-external-layer-cli")
        first_path = temp_dir / "first-private-report.json"
        second_path = temp_dir / "second-private-report.json"
        layer_path = temp_dir / "lifecycle-layer.json"
        harness_path = temp_dir / "harness-report.json"
        validation_path = temp_dir / "harness-validation.json"
        missing_source_validation_path = temp_dir / "missing-source-validation.json"
        tampered_layer_path = temp_dir / "tampered-lifecycle-layer.json"
        tampered_validation_path = temp_dir / "tampered-source-validation.json"
        first_path.write_text(
            json.dumps(_valid_lifecycle_report(module, "first"), sort_keys=True),
            encoding="utf-8",
        )
        second_path.write_text(
            json.dumps(_valid_lifecycle_report(module, "second"), sort_keys=True),
            encoding="utf-8",
        )

        aggregate_exit = module.main(
            [
                "--aggregate-lifecycle-reports",
                str(first_path),
                str(second_path),
                "--operator-attest-lifecycle",
                "--output",
                str(layer_path),
            ]
        )
        layer = json.loads(layer_path.read_text(encoding="utf-8"))
        expected_report = _run_passing_report(
            module,
            production_container_lifecycle_evidence=layer,
        )
        local_context = _passing_local_completion_context(module)
        with patch.object(
            module,
            "run_oauth_mcp_harness",
            return_value=expected_report,
        ) as run_harness:
            bind_exit = module.main(
                [
                    "--production-container-lifecycle-evidence",
                    str(layer_path),
                    "--output",
                    str(harness_path),
                ]
            )
        with patch.object(
            module,
            "_run_local_completion_context",
            return_value=local_context,
        ):
            validation_exit = module.main(
                [
                    "--validate-report",
                    str(harness_path),
                    "--production-container-lifecycle-evidence",
                    str(layer_path),
                    "--output",
                    str(validation_path),
                ]
            )
            missing_source_exit = module.main(
                [
                    "--validate-report",
                    str(harness_path),
                    "--output",
                    str(missing_source_validation_path),
                ]
            )
        tampered_layer = copy.deepcopy(layer)
        tampered_layer["run_report_set_hash"] = module.sha256_json(
            {"external_evidence": "tampered-lifecycle-cli-source"}
        )
        tampered_layer_path.write_text(
            json.dumps(tampered_layer, sort_keys=True),
            encoding="utf-8",
        )
        with patch.object(
            module,
            "_run_local_completion_context",
            return_value=local_context,
        ):
            tampered_source_exit = module.main(
                [
                    "--validate-report",
                    str(harness_path),
                    "--production-container-lifecycle-evidence",
                    str(tampered_layer_path),
                    "--output",
                    str(tampered_validation_path),
                ]
            )

        self.assertEqual(aggregate_exit, 0)
        self.assertEqual(bind_exit, 0)
        self.assertEqual(validation_exit, 0)
        self.assertEqual(missing_source_exit, 1)
        self.assertEqual(tampered_source_exit, 1)
        run_harness.assert_called_once_with(
            production_container_lifecycle_evidence=layer,
        )
        report = json.loads(harness_path.read_text(encoding="utf-8"))
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
        missing_source_validation = json.loads(
            missing_source_validation_path.read_text(encoding="utf-8")
        )
        tampered_validation = json.loads(tampered_validation_path.read_text(encoding="utf-8"))
        rendered = json.dumps(
            {
                "layer": layer,
                "report": report,
                "validation": validation,
                "missing_source_validation": missing_source_validation,
                "tampered_validation": tampered_validation,
            },
            sort_keys=True,
        )
        self.assertTrue(validation["passed"])
        self.assertFalse(missing_source_validation["passed"])
        self.assertFalse(tampered_validation["passed"])
        self.assertTrue(report["claim_boundary"]["supports_production_container_lifecycle_claim"])
        self.assertFalse(
            report["claim_boundary"]["supports_external_evidence_packet_contract_claim"]
        )
        self.assertFalse(report["claim_boundary"]["supports_issue20_closure_claim"])
        self.assertFalse(report["claim_boundary"]["supports_production_ready_claim"])
        self.assertNotIn(str(first_path), rendered)
        self.assertNotIn(str(second_path), rendered)
        self.assertNotIn(str(layer_path), rendered)
        self.assertNotIn(str(tampered_layer_path), rendered)

    def test_cli_builds_operator_layer_and_requires_explicit_attestation(self) -> None:
        module = _load_module()
        temp_dir = _paths.fresh_test_dir("issue20-operator-external-layer-cli")
        report_path = temp_dir / "operator-private-report.json"
        legacy_report_path = temp_dir / "operator-legacy-private-report.json"
        relabelled_report_path = temp_dir / "operator-relabelled-private-report.json"
        authority_path = temp_dir / "operator-authority.json"
        authority_pin_path = temp_dir / "operator-authority-pin.json"
        layer_path = temp_dir / "operator-layer.json"
        unattested_path = temp_dir / "operator-layer-unattested.json"
        legacy_layer_path = temp_dir / "operator-legacy-layer.json"
        relabelled_layer_path = temp_dir / "operator-relabelled-layer.json"
        report_path.write_text(
            json.dumps(_valid_operator_journey_report(module), sort_keys=True),
            encoding="utf-8",
        )
        authority_path.write_text(
            json.dumps(_valid_operator_journey_authority(module), sort_keys=True),
            encoding="utf-8",
        )
        authority_pin_path.write_text(
            json.dumps(_valid_operator_journey_authority_pin(module), sort_keys=True),
            encoding="utf-8",
        )
        legacy_report = _legacy_operator_journey_report(module)
        self.assertTrue(module._operator_journey.validate_report(legacy_report)["passed"])
        legacy_report_path.write_text(json.dumps(legacy_report, sort_keys=True), encoding="utf-8")
        relabelled_report = copy.deepcopy(legacy_report)
        relabelled_report["schema_version"] = 2
        relabelled_report["counts"] = _valid_operator_journey_report(module)["counts"]
        relabelled_report_path.write_text(
            json.dumps(relabelled_report, sort_keys=True),
            encoding="utf-8",
        )

        exit_code = module.main(
            [
                "--operator-cli-postgresql-report",
                str(report_path),
                "--operator-cli-postgresql-authority",
                str(authority_path),
                "--operator-cli-postgresql-authority-pin",
                str(authority_pin_path),
                "--operator-attest-postgresql",
                "--output",
                str(layer_path),
            ]
        )
        unattested_exit = module.main(
            [
                "--operator-cli-postgresql-report",
                str(report_path),
                "--operator-cli-postgresql-authority",
                str(authority_path),
                "--operator-cli-postgresql-authority-pin",
                str(authority_pin_path),
                "--output",
                str(unattested_path),
            ]
        )
        legacy_exit = module.main(
            [
                "--operator-cli-postgresql-report",
                str(legacy_report_path),
                "--operator-cli-postgresql-authority",
                str(authority_path),
                "--operator-cli-postgresql-authority-pin",
                str(authority_pin_path),
                "--operator-attest-postgresql",
                "--output",
                str(legacy_layer_path),
            ]
        )
        relabelled_exit = module.main(
            [
                "--operator-cli-postgresql-report",
                str(relabelled_report_path),
                "--operator-cli-postgresql-authority",
                str(authority_path),
                "--operator-cli-postgresql-authority-pin",
                str(authority_pin_path),
                "--operator-attest-postgresql",
                "--output",
                str(relabelled_layer_path),
            ]
        )

        layer = json.loads(layer_path.read_text(encoding="utf-8"))
        unattested = json.loads(unattested_path.read_text(encoding="utf-8"))
        legacy = json.loads(legacy_layer_path.read_text(encoding="utf-8"))
        relabelled = json.loads(relabelled_layer_path.read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 0)
        self.assertTrue(
            module.validate_operator_cli_postgresql_external_layer(
                layer,
                trusted_execution_authority_pin=(_valid_operator_journey_authority_pin(module)),
            )["passed"]
        )
        self.assertEqual(layer["source_schema_version"], 2)
        self.assertEqual(layer["operator_cli_success_count"], 10)
        self.assertEqual(layer["operator_cli_denial_count"], 3)
        self.assertEqual(layer["operator_audit_total_count"], 13)
        self.assertEqual(layer["transaction_rollback_probe_count"], 1)
        self.assertEqual(layer["transaction_rollback_preserved_state_count"], 1)
        self.assertEqual(unattested_exit, 1)
        self.assertEqual(unattested["error_code"], "operator_evidence_attestation_missing")
        self.assertEqual(legacy_exit, 1)
        self.assertEqual(legacy["error_code"], "operator_evidence_schema_v2_required")
        self.assertEqual(relabelled_exit, 1)
        self.assertEqual(relabelled["error_code"], "operator_evidence_report_invalid")
        rendered = json.dumps(
            {
                "layer": layer,
                "unattested": unattested,
                "legacy": legacy,
                "relabelled": relabelled,
            },
            sort_keys=True,
        )
        self.assertNotIn(str(report_path), rendered)
        self.assertNotIn("operator-private-report.json", rendered)

    def test_full_packet_recomputes_operator_layer_artifact_binding(self) -> None:
        module = _load_module()
        packet = _valid_external_evidence(module)
        original_artifact_hash = packet["layers"]["operator_cli_postgresql"][
            "evidence_artifact_hash"
        ]
        packet["layers"]["operator_cli_postgresql"]["runtime_image_id_hash"] = module.sha256_json(
            {"external_evidence": "tampered-operator-runtime-image-id"}
        )

        validation = _validate_external_packet(module, packet)

        self.assertEqual(
            packet["layers"]["completion_audit"]["operator_cli_postgresql_artifact_hash"],
            original_artifact_hash,
        )
        self.assertFalse(validation["passed"])
        self.assertEqual(
            validation["layer_statuses"]["operator_cli_postgresql"],
            "failed",
        )
        self.assertIn(
            "operator CLI PostgreSQL dedicated validation failed",
            validation["blockers"],
        )

    def test_full_packet_recomputes_live_postgresql_layer_artifact_binding(self) -> None:
        module = _load_module()
        packet = _valid_external_evidence(module)
        original_artifact_hash = packet["layers"]["live_postgresql"]["evidence_artifact_hash"]
        packet["layers"]["live_postgresql"]["schema_state_hash"] = module.sha256_json(
            {"external_evidence": "tampered-live-postgresql-schema-state"}
        )

        validation = _validate_external_packet(module, packet)

        self.assertEqual(
            packet["layers"]["completion_audit"]["live_postgresql_artifact_hash"],
            original_artifact_hash,
        )
        self.assertFalse(validation["passed"])
        self.assertEqual(
            validation["layer_statuses"]["live_postgresql"],
            "failed",
        )
        self.assertIn(
            "live PostgreSQL dedicated validation failed",
            validation["blockers"],
        )

    def test_full_packet_recomputes_lifecycle_layer_artifact_binding(self) -> None:
        module = _load_module()
        packet = _valid_external_evidence(module)
        original_artifact_hash = packet["layers"]["production_container_lifecycle"][
            "evidence_artifact_hash"
        ]
        packet["layers"]["production_container_lifecycle"]["runtime_image_contract_hash"] = (
            module.sha256_json({"external_evidence": "tampered-lifecycle-runtime-image-contract"})
        )

        validation = _validate_external_packet(module, packet)

        self.assertEqual(
            packet["layers"]["completion_audit"]["production_container_lifecycle_artifact_hash"],
            original_artifact_hash,
        )
        self.assertFalse(validation["passed"])
        self.assertEqual(
            validation["layer_statuses"]["production_container_lifecycle"],
            "failed",
        )
        self.assertIn(
            "production container lifecycle dedicated validation failed",
            validation["blockers"],
        )

    def test_full_packet_recomputes_mcp_inspector_layer_artifact_binding(self) -> None:
        module = _load_module()
        packet = _valid_external_evidence(module)
        original_artifact_hash = packet["layers"]["mcp_inspector"]["evidence_artifact_hash"]
        packet["layers"]["mcp_inspector"]["inspector_version_hash"] = module.sha256_json(
            {"external_evidence": "tampered-mcp-inspector-version"}
        )

        validation = _validate_external_packet(module, packet)

        self.assertEqual(
            packet["layers"]["completion_audit"]["mcp_inspector_artifact_hash"],
            original_artifact_hash,
        )
        self.assertFalse(validation["passed"])
        self.assertEqual(
            validation["layer_statuses"]["mcp_inspector"],
            "failed",
        )
        self.assertIn(
            "MCP Inspector dedicated validation failed",
            validation["blockers"],
        )

    def test_mcp_inspector_builder_source_hash_and_leak_guards(self) -> None:
        module = _load_module()
        layer = _valid_external_evidence(module)["layers"]["mcp_inspector"]

        self.assertEqual(set(layer), module._EXTERNAL_LAYER_FIELDS["mcp_inspector"])
        for forbidden_field in (
            "authenticated_tool_call_count",
            "oauth_login_count",
            "whoami_count",
            "upload_session_count",
            "forgery_denial_count",
            "cross_workspace_denial_count",
        ):
            self.assertNotIn(forbidden_field, layer)
        self.assertEqual(module.build_mcp_inspector_external_layer(layer), layer)
        self.assertTrue(module.validate_mcp_inspector_external_layer(layer)["passed"])
        self.assertNotEqual(
            layer["source_evidence_artifact_hash"],
            layer["evidence_artifact_hash"],
        )

        missing_source = copy.deepcopy(layer)
        del missing_source["source_evidence_artifact_hash"]
        self.assertFalse(module.validate_mcp_inspector_external_layer(missing_source)["passed"])

        invalid_source = copy.deepcopy(layer)
        invalid_source["source_evidence_artifact_hash"] = "not-a-sha256"
        _rebind_mcp_inspector_layer_artifact(module, invalid_source)
        self.assertFalse(module.validate_mcp_inspector_external_layer(invalid_source)["passed"])

        leaked_source = copy.deepcopy(layer)
        leaked_source["source_evidence_artifact_hash"] = (
            "/workspace/private/inspector-evidence.json"
        )
        _rebind_mcp_inspector_layer_artifact(module, leaked_source)
        self.assertFalse(module.validate_mcp_inspector_external_layer(leaked_source)["passed"])

        for field, invalid_value in (
            ("unauthenticated_initialize_count", 0),
            ("unauthenticated_tools_list_count", 0),
            ("protected_tool_challenge_count", 0),
            ("invalid_bearer_challenge_count", 0),
            ("semantic_result_count", 1),
            ("partial_state_write_count", 1),
        ):
            with self.subTest(field=field):
                invalid_probe = copy.deepcopy(layer)
                invalid_probe[field] = invalid_value
                _rebind_mcp_inspector_layer_artifact(module, invalid_probe)
                self.assertFalse(
                    module.validate_mcp_inspector_external_layer(invalid_probe)["passed"]
                )

        authenticated_overclaim = copy.deepcopy(layer)
        authenticated_overclaim["authenticated_tool_call_count"] = 1
        self.assertFalse(
            module.validate_mcp_inspector_external_layer(authenticated_overclaim)["passed"]
        )

    def test_full_packet_recomputes_live_chatgpt_google_artifact_binding(self) -> None:
        module = _load_module()
        packet = _valid_external_evidence(module)
        original_artifact_hash = packet["layers"]["live_chatgpt_google"]["evidence_artifact_hash"]
        packet["layers"]["live_chatgpt_google"]["audit_lineage_hash"] = module.sha256_json(
            {"external_evidence": "tampered-chatgpt-audit-lineage"}
        )

        validation = _validate_external_packet(module, packet)

        self.assertEqual(
            packet["layers"]["completion_audit"]["live_chatgpt_google_artifact_hash"],
            original_artifact_hash,
        )
        self.assertFalse(validation["passed"])
        self.assertEqual(
            validation["layer_statuses"]["live_chatgpt_google"],
            "failed",
        )
        self.assertIn(
            "live ChatGPT/Google dedicated validation failed",
            validation["blockers"],
        )

    def test_live_chatgpt_google_builder_and_dedicated_guards(self) -> None:
        module = _load_module()
        layer = _valid_external_evidence(module)["layers"]["live_chatgpt_google"]
        self._assert_chatgpt_google_builder_and_dedicated_guards(module, layer)

    def test_chatgpt_google_builder_and_dedicated_guards_local_contract(self) -> None:
        module = _load_module()
        layer = _valid_live_chatgpt_google_layer(module)
        self._assert_chatgpt_google_builder_and_dedicated_guards(module, layer)

    def _assert_chatgpt_google_builder_and_dedicated_guards(
        self,
        module,
        layer,
    ) -> None:
        self.assertEqual(module.build_live_chatgpt_google_external_layer(layer), layer)
        self.assertTrue(module.validate_live_chatgpt_google_external_layer(layer)["passed"])
        self.assertNotEqual(
            layer["source_evidence_artifact_hash"],
            layer["evidence_artifact_hash"],
        )

        missing_source = copy.deepcopy(layer)
        del missing_source["source_evidence_artifact_hash"]
        self.assertFalse(
            module.validate_live_chatgpt_google_external_layer(missing_source)["passed"]
        )

        invalid_source = copy.deepcopy(layer)
        invalid_source["source_evidence_artifact_hash"] = "not-a-sha256"
        _rebind_live_chatgpt_google_layer_artifact(module, invalid_source)
        self.assertFalse(
            module.validate_live_chatgpt_google_external_layer(invalid_source)["passed"]
        )

        invalid_count = copy.deepcopy(layer)
        invalid_count["google_authorization_count"] = 2
        _rebind_live_chatgpt_google_layer_artifact(module, invalid_count)
        self.assertFalse(
            module.validate_live_chatgpt_google_external_layer(invalid_count)["passed"]
        )

        invalid_attestation = copy.deepcopy(layer)
        invalid_attestation["attestations"]["no_simulated_chatgpt_client"] = False
        _rebind_live_chatgpt_google_layer_artifact(module, invalid_attestation)
        self.assertFalse(
            module.validate_live_chatgpt_google_external_layer(invalid_attestation)["passed"]
        )

        leaked_source = copy.deepcopy(layer)
        leaked_source["source_evidence_artifact_hash"] = (
            "/workspace/private/chatgpt-google-evidence.json"
        )
        _rebind_live_chatgpt_google_layer_artifact(module, leaked_source)
        self.assertFalse(
            module.validate_live_chatgpt_google_external_layer(leaked_source)["passed"]
        )

        for field, invalid_value in (
            ("distinct_external_subject_count", 1),
            ("distinct_formowl_user_count", 1),
            ("owner_only_denial_semantic_result_count", 1),
            ("cross_workspace_denial_partial_state_write_count", 1),
            ("removed_relink_authorization_code_issued_count", 1),
            ("removed_relink_token_session_created_count", 1),
            ("removed_relink_membership_write_count", 1),
            ("removal_revoked_session_count", 0),
            ("post_restore_old_session_denial_count", 0),
            ("restore_relink_same_subject_user_new_session_count", 0),
            ("post_revocation_relink_same_subject_user_new_session_count", 0),
            ("post_expiry_relink_same_subject_user_new_session_count", 0),
            ("owner_attributed_membership_mutation_count", 1),
        ):
            with self.subTest(field=field):
                invalid_probe = copy.deepcopy(layer)
                invalid_probe[field] = invalid_value
                _rebind_live_chatgpt_google_layer_artifact(module, invalid_probe)
                self.assertFalse(
                    module.validate_live_chatgpt_google_external_layer(invalid_probe)["passed"]
                )

    def test_live_chatgpt_google_audit_manifest_is_named_exact_and_unique(self) -> None:
        module = _load_module()

        self.assertEqual(len(module._LIVE_CHATGPT_GOOGLE_AUDIT_LINEAGE), 47)
        self.assertEqual(
            len(set(module._LIVE_CHATGPT_GOOGLE_AUDIT_LINEAGE)),
            len(module._LIVE_CHATGPT_GOOGLE_AUDIT_LINEAGE),
        )
        self.assertEqual(
            module._LIVE_CHATGPT_GOOGLE_AUDIT_LINEAGE[0],
            "owner_bootstrap_created_service",
        )
        self.assertNotIn(
            "removed_session_revoked_by_membership_removal",
            module._LIVE_CHATGPT_GOOGLE_AUDIT_LINEAGE,
        )
        for event_name in (
            "second_user_invitation_created_service",
            "second_user_owner_only_denied",
            "second_user_cross_workspace_denied",
            "second_user_membership_removed_service",
            "removed_relink_google_callback_denied",
            "second_user_membership_restored_service",
            "restore_relink_token_session_issued",
            "post_revocation_relink_token_session_issued",
            "post_expiry_relink_token_session_issued",
        ):
            self.assertIn(event_name, module._LIVE_CHATGPT_GOOGLE_AUDIT_LINEAGE)
        self.assertEqual(
            module._LIVE_CHATGPT_GOOGLE_AUDIT_LINEAGE_FIELDS[-2:],
            ("previous_audit_record_hash", "audit_record_hash"),
        )

    def test_full_packet_recomputes_reviewer_gate_artifact_binding(self) -> None:
        module = _load_module()
        packet = _valid_external_evidence(module)
        original_artifact_hash = packet["layers"]["reviewer_gate"]["evidence_artifact_hash"]
        packet["layers"]["reviewer_gate"]["review_packet_hash"] = module.sha256_json(
            {"external_evidence": "tampered-review-packet"}
        )

        validation = _validate_external_packet(module, packet)

        self.assertEqual(
            packet["layers"]["completion_audit"]["reviewer_gate_artifact_hash"],
            original_artifact_hash,
        )
        self.assertFalse(validation["passed"])
        self.assertEqual(
            validation["layer_statuses"]["reviewer_gate"],
            "failed",
        )
        self.assertIn(
            "reviewer-gate dedicated validation failed",
            validation["blockers"],
        )

    def test_reviewer_gate_builder_and_dedicated_guards(self) -> None:
        module = _load_module()
        layer = _valid_external_evidence(module)["layers"]["reviewer_gate"]

        self.assertEqual(module.build_reviewer_gate_external_layer(layer), layer)
        self.assertTrue(module.validate_reviewer_gate_external_layer(layer)["passed"])
        self.assertNotEqual(
            layer["source_evidence_artifact_hash"],
            layer["evidence_artifact_hash"],
        )

        missing_source = copy.deepcopy(layer)
        del missing_source["source_evidence_artifact_hash"]
        self.assertFalse(module.validate_reviewer_gate_external_layer(missing_source)["passed"])

        invalid_source = copy.deepcopy(layer)
        invalid_source["source_evidence_artifact_hash"] = "not-a-sha256"
        _rebind_reviewer_gate_layer_artifact(module, invalid_source)
        self.assertFalse(module.validate_reviewer_gate_external_layer(invalid_source)["passed"])

        duplicate_source = copy.deepcopy(layer)
        duplicate_source["source_evidence_artifact_hash"] = duplicate_source["review_packet_hash"]
        _rebind_reviewer_gate_layer_artifact(module, duplicate_source)
        self.assertFalse(module.validate_reviewer_gate_external_layer(duplicate_source)["passed"])

        wrong_count = copy.deepcopy(layer)
        wrong_count["reviewer_count"] = 2
        wrong_count["agreement_count"] = 2
        _rebind_reviewer_gate_layer_artifact(module, wrong_count)
        self.assertFalse(module.validate_reviewer_gate_external_layer(wrong_count)["passed"])

        missing_agreement = copy.deepcopy(layer)
        missing_agreement["agreement_count"] = 2
        _rebind_reviewer_gate_layer_artifact(module, missing_agreement)
        self.assertFalse(module.validate_reviewer_gate_external_layer(missing_agreement)["passed"])

        invalid_attestation = copy.deepcopy(layer)
        invalid_attestation["attestations"]["no_outstanding_blockers"] = False
        _rebind_reviewer_gate_layer_artifact(module, invalid_attestation)
        self.assertFalse(
            module.validate_reviewer_gate_external_layer(invalid_attestation)["passed"]
        )

        leaked_source = copy.deepcopy(layer)
        leaked_source["source_evidence_artifact_hash"] = "/workspace/private/reviewer-output.json"
        _rebind_reviewer_gate_layer_artifact(module, leaked_source)
        self.assertFalse(module.validate_reviewer_gate_external_layer(leaked_source)["passed"])

    def test_full_packet_rejects_coherently_rebound_duplicate_source_commitments(self) -> None:
        module = _load_module()
        packet = _valid_external_evidence(module)
        inspector_source_hash = packet["layers"]["mcp_inspector"]["source_evidence_artifact_hash"]
        chatgpt_layer = packet["layers"]["live_chatgpt_google"]
        chatgpt_layer["source_evidence_artifact_hash"] = inspector_source_hash
        _rebind_live_chatgpt_google_layer_artifact(module, chatgpt_layer)
        packet["layers"]["completion_audit"]["live_chatgpt_google_artifact_hash"] = chatgpt_layer[
            "evidence_artifact_hash"
        ]
        _rebind_completion_audit_layer_artifact(
            module,
            packet["layers"]["completion_audit"],
        )

        self.assertTrue(
            module.validate_mcp_inspector_external_layer(packet["layers"]["mcp_inspector"])[
                "passed"
            ]
        )
        self.assertTrue(module.validate_live_chatgpt_google_external_layer(chatgpt_layer)["passed"])
        self.assertTrue(
            module.validate_completion_audit_external_layer(packet["layers"]["completion_audit"])[
                "passed"
            ]
        )

        validation = _validate_external_packet(module, packet)

        self.assertFalse(validation["passed"])
        self.assertEqual(validation["layer_statuses"]["mcp_inspector"], "failed")
        self.assertEqual(
            validation["layer_statuses"]["live_chatgpt_google"],
            "failed",
        )
        self.assertGreaterEqual(
            validation["blockers"].count("external evidence source commitments must be distinct"),
            2,
        )

    def test_full_packet_rejects_coherently_rebound_source_public_collision(self) -> None:
        module = _load_module()
        packet = _valid_external_evidence(module)
        inspector_public_artifact = packet["layers"]["mcp_inspector"]["evidence_artifact_hash"]
        chatgpt_layer = packet["layers"]["live_chatgpt_google"]
        chatgpt_layer["source_evidence_artifact_hash"] = inspector_public_artifact
        _rebind_live_chatgpt_google_layer_artifact(module, chatgpt_layer)
        packet["layers"]["completion_audit"]["live_chatgpt_google_artifact_hash"] = chatgpt_layer[
            "evidence_artifact_hash"
        ]
        _rebind_completion_audit_layer_artifact(
            module,
            packet["layers"]["completion_audit"],
        )

        self.assertTrue(
            module.validate_mcp_inspector_external_layer(packet["layers"]["mcp_inspector"])[
                "passed"
            ]
        )
        self.assertTrue(module.validate_live_chatgpt_google_external_layer(chatgpt_layer)["passed"])
        self.assertTrue(
            module.validate_completion_audit_external_layer(packet["layers"]["completion_audit"])[
                "passed"
            ]
        )
        source_commitments = [
            packet["layers"][layer_name][field]
            for layer_name, field in module._EXTERNAL_SOURCE_COMMITMENT_FIELDS
        ]
        self.assertEqual(len(source_commitments), len(set(source_commitments)))

        validation = _validate_external_packet(module, packet)

        self.assertFalse(validation["passed"])
        self.assertEqual(validation["layer_statuses"]["mcp_inspector"], "failed")
        self.assertEqual(
            validation["layer_statuses"]["live_chatgpt_google"],
            "failed",
        )
        self.assertGreaterEqual(
            validation["blockers"].count(
                "external evidence source commitments must be disjoint from public artifacts"
            ),
            2,
        )

    def test_full_packet_recomputes_completion_audit_artifact_binding(self) -> None:
        module = _load_module()
        packet = _valid_external_evidence(module)
        original_artifact_hash = packet["layers"]["completion_audit"]["evidence_artifact_hash"]
        packet["layers"]["completion_audit"]["evidence_artifact_hash"] = module.sha256_json(
            {"external_evidence": "replaced-completion-audit-artifact"}
        )

        validation = _validate_external_packet(module, packet)

        self.assertNotEqual(
            packet["layers"]["completion_audit"]["evidence_artifact_hash"],
            original_artifact_hash,
        )
        self.assertFalse(validation["passed"])
        self.assertEqual(
            validation["layer_statuses"]["completion_audit"],
            "failed",
        )
        self.assertIn(
            "completion audit dedicated validation failed",
            validation["blockers"],
        )

    def test_missing_any_external_or_completion_layer_cannot_enable_production_claim(self) -> None:
        module = _load_module()

        for layer_name in module._EXTERNAL_LAYER_FIELDS:
            with self.subTest(layer=layer_name):
                packet = _valid_external_evidence(module)
                del packet["layers"][layer_name]

                validation = _validate_external_packet(module, packet)
                report = _run_passing_report(module, external_evidence=packet)

                self.assertFalse(validation["passed"])
                self.assertFalse(
                    report["claim_boundary"]["supports_external_evidence_packet_contract_claim"]
                )
                self.assertFalse(report["claim_boundary"]["supports_production_ready_claim"])
                if layer_name == "production_container_lifecycle":
                    self.assertFalse(
                        report["claim_boundary"]["supports_production_container_lifecycle_claim"]
                    )
                if layer_name == "operator_cli_postgresql":
                    self.assertFalse(
                        report["claim_boundary"]["supports_operator_cli_postgresql_claim"]
                    )
                self.assertTrue(report["validation"]["passed"])

    def test_external_packet_rejects_sensitive_fake_or_inconsistent_evidence(self) -> None:
        module = _load_module()
        base = _valid_external_evidence(module)
        cases: list[tuple[str, dict[str, object]]] = []

        access_token = copy.deepcopy(base)
        access_token["access_token"] = "eyJhbGciOiJSUzI1NiJ9.private.signature"
        cases.append(("access_token", access_token))

        transcript = copy.deepcopy(base)
        transcript["layers"]["mcp_inspector"]["raw_transcript"] = "private transcript"
        cases.append(("transcript", transcript))

        email = copy.deepcopy(base)
        email["layers"]["live_chatgpt_google"]["evidence_artifact_hash"] = "operator@example.test"
        cases.append(("email", email))

        raw_path = copy.deepcopy(base)
        raw_path["layers"]["live_chatgpt_google"]["endpoint_scheme"] = (
            "/workspace/private/result.json"
        )
        cases.append(("raw_path", raw_path))

        raw_sql = copy.deepcopy(base)
        raw_sql["layers"]["live_postgresql"]["endpoint_scheme"] = (
            "select access_token from oauth_token_sessions"
        )
        cases.append(("raw_sql", raw_sql))

        simulated_client = copy.deepcopy(base)
        simulated_client["layers"]["live_chatgpt_google"]["attestations"][
            "no_simulated_chatgpt_client"
        ] = False
        cases.append(("simulated_client", simulated_client))

        sequence = copy.deepcopy(base)
        sequence["layers"]["mcp_inspector"]["sequence_hash"] = "sha256:" + "f" * 64
        cases.append(("sequence", sequence))

        counts = copy.deepcopy(base)
        counts["layers"]["live_postgresql"]["pass_count"] = 0
        cases.append(("counts", counts))

        stale_schema_version = copy.deepcopy(base)
        stale_schema_version["schema_version"] = 2
        cases.append(("stale_schema_version", stale_schema_version))

        lifecycle = copy.deepcopy(base)
        lifecycle["layers"]["production_container_lifecycle"]["sigterm_clean_exit_count"] = 7
        cases.append(("lifecycle", lifecycle))

        stale_live_postgres = copy.deepcopy(base)
        stale_live_postgres["layers"]["live_postgresql"]["schema_state_hash"] = "sha256:" + "4" * 64
        stale_live_postgres["layers"]["live_postgresql"]["implementation_contract_hash"] = (
            "sha256:" + "f" * 64
        )
        stale_live_postgres["layers"]["live_postgresql"]["evidence_artifact_hash"] = (
            module.sha256_json({"external_evidence": "stale-live-postgresql-artifact"})
        )
        stale_live_postgres["layers"]["completion_audit"]["live_postgresql_artifact_hash"] = (
            stale_live_postgres["layers"]["live_postgresql"]["evidence_artifact_hash"]
        )
        cases.append(("stale_live_postgresql", stale_live_postgres))

        stale_operator = copy.deepcopy(base)
        stale_operator["layers"]["operator_cli_postgresql"]["implementation_contract_hash"] = (
            "sha256:" + "e" * 64
        )
        _rebind_operator_layer_artifact(
            module,
            stale_operator["layers"]["operator_cli_postgresql"],
        )
        stale_operator["layers"]["completion_audit"]["operator_cli_postgresql_artifact_hash"] = (
            stale_operator["layers"]["operator_cli_postgresql"]["evidence_artifact_hash"]
        )
        cases.append(("stale_operator", stale_operator))

        duplicate_operator_hash = copy.deepcopy(base)
        duplicate_operator_hash["layers"]["operator_cli_postgresql"]["migration_result_hash"] = (
            duplicate_operator_hash["layers"]["operator_cli_postgresql"]["runtime_image_id_hash"]
        )
        _rebind_operator_layer_artifact(
            module,
            duplicate_operator_hash["layers"]["operator_cli_postgresql"],
        )
        duplicate_operator_hash["layers"]["completion_audit"][
            "operator_cli_postgresql_artifact_hash"
        ] = duplicate_operator_hash["layers"]["operator_cli_postgresql"]["evidence_artifact_hash"]
        cases.append(("duplicate_operator_hash", duplicate_operator_hash))

        tampered_operator_count = copy.deepcopy(base)
        tampered_operator_count["layers"]["operator_cli_postgresql"][
            "operator_cli_success_count"
        ] = 3
        _rebind_operator_layer_artifact(
            module,
            tampered_operator_count["layers"]["operator_cli_postgresql"],
        )
        tampered_operator_count["layers"]["completion_audit"][
            "operator_cli_postgresql_artifact_hash"
        ] = tampered_operator_count["layers"]["operator_cli_postgresql"]["evidence_artifact_hash"]
        cases.append(("tampered_operator_count", tampered_operator_count))

        legacy_operator_packet = copy.deepcopy(base)
        legacy_operator_packet["layers"]["operator_cli_postgresql"]["source_schema_version"] = 1
        _rebind_operator_layer_artifact(
            module,
            legacy_operator_packet["layers"]["operator_cli_postgresql"],
        )
        legacy_operator_packet["layers"]["completion_audit"][
            "operator_cli_postgresql_artifact_hash"
        ] = legacy_operator_packet["layers"]["operator_cli_postgresql"]["evidence_artifact_hash"]
        _rebind_completion_audit_layer_artifact(
            module,
            legacy_operator_packet["layers"]["completion_audit"],
        )
        cases.append(("legacy_operator_schema_v1", legacy_operator_packet))

        coherently_rebound_legacy_counts = copy.deepcopy(base)
        coherently_rebound_legacy_counts["layers"]["operator_cli_postgresql"].update(
            {
                "operator_cli_success_count": 4,
                "operator_cli_denial_count": 1,
                "operator_audit_total_count": 5,
                "operator_audit_allowed_count": 4,
                "operator_audit_denied_count": 1,
                "transaction_rollback_probe_count": 0,
                "transaction_rollback_preserved_state_count": 0,
            }
        )
        _rebind_operator_layer_artifact(
            module,
            coherently_rebound_legacy_counts["layers"]["operator_cli_postgresql"],
        )
        coherently_rebound_legacy_counts["layers"]["completion_audit"][
            "operator_cli_postgresql_artifact_hash"
        ] = coherently_rebound_legacy_counts["layers"]["operator_cli_postgresql"][
            "evidence_artifact_hash"
        ]
        _rebind_completion_audit_layer_artifact(
            module,
            coherently_rebound_legacy_counts["layers"]["completion_audit"],
        )
        cases.append(
            ("coherently_rebound_legacy_operator_counts", coherently_rebound_legacy_counts)
        )

        leaked_operator = copy.deepcopy(base)
        leaked_operator["layers"]["operator_cli_postgresql"]["raw_path"] = (
            "/workspace/private/operator.json"
        )
        cases.append(("leaked_operator", leaked_operator))

        reviewer = copy.deepcopy(base)
        reviewer["layers"]["reviewer_gate"]["reviewer_count"] = 2
        reviewer["layers"]["reviewer_gate"]["agreement_count"] = 2
        cases.append(("reviewer", reviewer))

        for name, packet in cases:
            with self.subTest(name=name):
                validation = _validate_external_packet(module, packet)
                report = _run_passing_report(module, external_evidence=packet)
                self.assertFalse(validation["passed"])
                self.assertGreater(validation["blocker_count"], 0)
                self.assertFalse(report["claim_boundary"]["supports_issue20_closure_claim"])
                self.assertTrue(report["validation"]["passed"])

    def test_missing_any_required_whole_journey_field_fails_packet_contract(self) -> None:
        module = _load_module()
        required_fields = {
            "live_postgresql": (
                "source_report_commitment_hash",
                "implementation_contract_hash",
                "schema_state_hash",
                "first_owner_bootstrap_state_hash",
                "persisted_auth_upload_audit_state_hash",
                "restart_state_hash",
                "second_user_invitation_state_hash",
                "revocation_expiry_relink_state_hash",
                "signing_key_rotation_state_hash",
                "fresh_database_count",
                "migration_count",
                "first_owner_bootstrap_count",
                "persisted_auth_count",
                "persisted_upload_count",
                "persisted_audit_count",
                "restart_recovery_count",
                "second_user_invitation_count",
                "revocation_count",
                "post_relink_old_token_denial_count",
                "revoked_token_sessions_after_relink_count",
                "relink_distinct_token_session_count",
                "expiry_denial_count",
                "relink_count",
                "signing_key_rotation_count",
                "overlap_old_token_verification_count",
                "overlap_jwks_public_key_count",
                "new_key_token_verification_count",
                "post_overlap_old_token_denial_count",
                "post_overlap_jwks_public_key_count",
                "post_overlap_new_token_verification_count",
                "private_signing_key_exposure_count",
            ),
            "operator_cli_postgresql": (
                "source_schema_version",
                "implementation_contract_hash",
                "runtime_image_id_hash",
                "postgres_image_digest_hash",
                "operator_authority_contract_hash",
                "journey_script_hash",
                "journey_report_hash",
                "secret_initialization_contract_hash",
                "migration_result_hash",
                "operator_output_set_hash",
                "operator_denial_hash",
                "run_count",
                "pass_count",
                "failure_count",
                "skip_count",
                "runtime_image_build_count",
                "fresh_database_count",
                "generated_secret_count",
                "idempotent_secret_rerun_count",
                "migration_success_count",
                "operator_cli_success_count",
                "operator_cli_denial_count",
                "operator_audit_total_count",
                "operator_audit_allowed_count",
                "operator_audit_denied_count",
                "owner_bootstrap_success_count",
                "member_invitation_success_count",
                "member_approval_denial_count",
                "explicit_token_revocation_count",
                "last_owner_removal_denial_count",
                "membership_remove_success_count",
                "membership_restore_success_count",
                "post_restore_active_session_count",
                "post_restore_inactive_session_count",
                "transaction_rollback_probe_count",
                "transaction_rollback_preserved_state_count",
            ),
            "production_container_lifecycle": (
                "implementation_contract_hash",
                "sequence_hash",
                "run_report_set_hash",
                "runtime_image_contract_hash",
                "compose_runtime_wiring_hash",
                "compose_live_journey_hash",
                "compose_live_security_contract_hash",
                "compose_secret_snapshot_set_hash",
                "oauth_seed_state_hash",
                "first_client_result_hash",
                "restart_client_result_hash",
                "persistent_core_state_hash",
                "readiness_shape_hash",
                "jwks_phase_set_hash",
                "runtime_log_hash",
                "compose_healthcheck_success_count",
                "compose_migration_success_count",
                "compose_old_snapshot_retirement_count",
                "compose_postgres_0400_secret_read_count",
                "compose_preflight_success_count",
                "compose_runtime_process_uid",
                "compose_runtime_ready_count",
                "compose_secret_snapshot_count",
                "operator_owned_0400_secret_count",
                "compose_service_count",
                "runtime_process_start_count",
                "runtime_ready_count",
                "sigterm_clean_exit_count",
                "database_release_count",
                "stateful_restart_count",
                "bearer_whoami_success_count",
                "upload_session_count",
                "forgery_denial_count",
                "persisted_user_count",
                "persisted_external_identity_count",
                "persisted_token_session_count",
                "persisted_file_audit_count",
                "postgres_mcp_allowed_audit_count",
                "postgres_mcp_denied_audit_count",
                "persisted_state_snapshot_count",
                "jwks_initial_public_key_count",
                "jwks_overlap_public_key_count",
                "jwks_retired_public_key_count",
                "runtime_process_uid",
            ),
            "mcp_inspector": (
                "source_evidence_artifact_hash",
                "public_initialize_shape_hash",
                "public_tools_list_shape_hash",
                "protected_tool_challenge_hash",
                "invalid_bearer_challenge_hash",
                "unauthenticated_initialize_count",
                "unauthenticated_tools_list_count",
                "protected_tool_challenge_count",
                "invalid_bearer_challenge_count",
                "semantic_result_count",
                "partial_state_write_count",
            ),
            "live_chatgpt_google": (
                "source_evidence_artifact_hash",
                "public_initialize_shape_hash",
                "public_tools_list_shape_hash",
                "protected_tool_challenge_hash",
                "second_user_invitation_lineage_hash",
                "second_user_distinct_subject_commitment_hash",
                "second_user_member_workspace_shape_hash",
                "owner_only_denial_hash",
                "cross_workspace_denial_hash",
                "forgery_denial_hash",
                "membership_removal_service_audit_hash",
                "removed_session_revocation_state_hash",
                "removed_token_denial_hash",
                "restart_removed_token_denial_hash",
                "removed_membership_relink_denial_hash",
                "removed_membership_relink_zero_state_hash",
                "membership_restore_service_audit_hash",
                "post_restore_old_session_denial_hash",
                "restore_relink_identity_session_hash",
                "post_revocation_relink_identity_session_hash",
                "post_expiry_relink_identity_session_hash",
                "revocation_lineage_hash",
                "expiry_lineage_hash",
                "audit_lineage_hash",
                "audit_lineage_manifest_hash",
                "audit_lineage_field_set_hash",
                "discovery_initialize_count",
                "discovery_tools_list_count",
                "protected_tool_challenge_count",
                "google_authorization_count",
                "google_callback_count",
                "token_exchange_count",
                "whoami_count",
                "upload_session_count",
                "second_user_invitation_count",
                "second_user_google_login_count",
                "second_user_whoami_count",
                "distinct_external_subject_count",
                "distinct_formowl_user_count",
                "second_user_member_workspace_binding_count",
                "owner_only_denial_count",
                "cross_workspace_denial_count",
                "forgery_denial_count",
                "owner_only_denial_semantic_result_count",
                "owner_only_denial_partial_state_write_count",
                "cross_workspace_denial_semantic_result_count",
                "cross_workspace_denial_partial_state_write_count",
                "forgery_denial_semantic_result_count",
                "forgery_denial_partial_state_write_count",
                "membership_removal_count",
                "membership_removal_service_audit_count",
                "removal_revoked_session_count",
                "removed_token_denial_count",
                "restart_removed_token_denial_count",
                "removed_membership_relink_denial_count",
                "removed_relink_authorization_code_issued_count",
                "removed_relink_token_session_created_count",
                "removed_relink_membership_write_count",
                "membership_restore_count",
                "membership_restore_service_audit_count",
                "owner_attributed_membership_mutation_count",
                "post_restore_old_session_denial_count",
                "restore_relink_same_subject_user_new_session_count",
                "post_revocation_relink_same_subject_user_new_session_count",
                "post_expiry_relink_same_subject_user_new_session_count",
                "revocation_count",
                "revoked_token_denial_count",
                "expiry_denial_count",
                "relink_count",
                "relinked_whoami_count",
                "audit_lineage_event_count",
            ),
            "reviewer_gate": ("source_evidence_artifact_hash",),
            "completion_audit": (
                "source_evidence_artifact_hash",
                "implementation_contract_hash",
                "local_harness_report_hash",
                "operator_cli_postgresql_artifact_hash",
                "production_container_lifecycle_artifact_hash",
                "actor_context_contract_hash",
                "documentation_contract_hash",
                "journey_manifest_hash",
                "journey_count",
                "passed_journey_count",
                "missing_journey_count",
                "blocking_finding_count",
            ),
        }

        for layer_name, fields in required_fields.items():
            for field in fields:
                with self.subTest(layer=layer_name, field=field):
                    packet = _valid_external_evidence(module)
                    del packet["layers"][layer_name][field]
                    validation = _validate_external_packet(module, packet)
                    report = _run_passing_report(module, external_evidence=packet)

                    self.assertFalse(validation["passed"])
                    self.assertFalse(
                        report["claim_boundary"]["supports_external_evidence_packet_contract_claim"]
                    )
                    self.assertFalse(report["claim_boundary"]["supports_issue20_closure_claim"])

    def test_completion_audit_artifact_references_must_bind_to_layer_artifacts(self) -> None:
        module = _load_module()
        packet = _valid_external_evidence(module)
        packet["layers"]["completion_audit"]["mcp_inspector_artifact_hash"] = module.sha256_json(
            {"external_evidence": "unbound-inspector-artifact"}
        )

        validation = _validate_external_packet(module, packet)
        report = _run_passing_report(module, external_evidence=packet)

        self.assertFalse(validation["passed"])
        self.assertFalse(
            report["claim_boundary"]["supports_external_evidence_packet_contract_claim"]
        )
        self.assertFalse(report["claim_boundary"]["supports_issue20_closure_claim"])

    def test_completion_audit_local_actor_context_and_docs_hashes_are_recomputed(self) -> None:
        module = _load_module()
        cases = (
            ("local_harness_report_hash", "a"),
            ("actor_context_contract_hash", "b"),
            ("documentation_contract_hash", "c"),
        )

        for field, digit in cases:
            with self.subTest(field=field):
                packet = _valid_external_evidence(module)
                packet["layers"]["completion_audit"][field] = "sha256:" + digit * 64

                validation = _validate_external_packet(module, packet)
                report = _run_passing_report(module, external_evidence=packet)

                self.assertFalse(validation["passed"])
                self.assertFalse(
                    report["claim_boundary"]["supports_external_evidence_packet_contract_claim"]
                )
                self.assertFalse(report["claim_boundary"]["supports_issue20_closure_claim"])

    def test_completion_documentation_hash_rejects_stale_operator_critical_docs(self) -> None:
        module = _load_module()
        required = {
            "deploy/connected/secrets/README.md",
            "docs/closed-beta-runbook.md",
            "docs/infra-spec.md",
        }
        self.assertTrue(required.issubset(module._DOCUMENTATION_CONTRACT_PATHS))
        with tempfile.TemporaryDirectory(
            prefix="formowl-issue20-docs-",
            dir=tempfile.gettempdir(),
        ) as value:
            root = Path(value)
            for relative_path in module._DOCUMENTATION_CONTRACT_PATHS:
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"current:{relative_path}\n", encoding="utf-8")
            current = module._repository_contract_hash(
                module._DOCUMENTATION_CONTRACT_PATHS,
                root=root,
            )
            operator_doc = root / "deploy/connected/secrets/README.md"
            operator_doc.write_text("stale operator secret guidance\n", encoding="utf-8")
            stale = module._repository_contract_hash(
                module._DOCUMENTATION_CONTRACT_PATHS,
                root=root,
            )

        self.assertNotEqual(current, stale)

    def test_runbook_requires_packet_for_external_report_revalidation(self) -> None:
        runbook = (
            Path(__file__).resolve().parents[1] / "docs" / "issue20-oauth-evidence-runbook.md"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "--validate-report .test-tmp/issue20-oauth-mcp-harness.json",
            runbook,
        )
        self.assertIn(
            "--external-evidence .test-tmp/issue20-external-evidence.json",
            runbook,
        )
        self.assertIn(
            "--validate-report .test-tmp/issue20-oauth-lifecycle-bound.json",
            runbook,
        )
        self.assertIn(
            "--production-container-lifecycle-evidence \\\n  .test-tmp/issue20-lifecycle-external-layer.json",
            runbook,
        )
        self.assertIn("safe receipts, not trusted", runbook)

    def test_runbooks_keep_original_operator_trust_inputs_across_every_cli_layer(
        self,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        evidence_runbook = (root / "docs/issue20-oauth-evidence-runbook.md").read_text(
            encoding="utf-8"
        )
        closed_beta_runbook = (root / "docs/closed-beta-runbook.md").read_text(encoding="utf-8")

        for runbook in (evidence_runbook, closed_beta_runbook):
            self.assertIn("$ISSUE20_SCRATCH_ROOT/trust-inputs", runbook)
            self.assertIn("mode `0700`", runbook)
            self.assertIn("mode `0400`", runbook)
            self.assertIn("reports directory is never the trust source", runbook)
            self.assertIn("governed reset of the entire scratch root", runbook)
            self.assertIn(
                '--trusted-execution-authority "$OPERATOR_AUTHORITY"',
                runbook,
            )
            self.assertIn(
                '--trusted-execution-authority-pin "$OPERATOR_AUTHORITY_PIN"',
                runbook,
            )
            self.assertIn(
                '--operator-cli-postgresql-authority "$OPERATOR_AUTHORITY"',
                runbook,
            )
            self.assertIn(
                '--operator-cli-postgresql-authority-pin "$OPERATOR_AUTHORITY_PIN"',
                runbook,
            )

        self.assertEqual(
            evidence_runbook.count(
                '--operator-cli-postgresql-execution-authority "$OPERATOR_AUTHORITY"'
            ),
            4,
        )
        self.assertEqual(
            evidence_runbook.count(
                "--operator-cli-postgresql-execution-authority-pin " '"$OPERATOR_AUTHORITY_PIN"'
            ),
            4,
        )
        self.assertIn("current schema-v5 authority validator", evidence_runbook)
        self.assertIn("current packet `schema_version` is `5`", evidence_runbook)
        self.assertNotIn("schema-v4 packet", evidence_runbook)
        self.assertIn("Assemble packet schema version `5`", closed_beta_runbook)

    def test_cli_accepts_hash_only_external_packet_without_outputting_input_path(self) -> None:
        module = _load_module()
        packet = _valid_external_evidence(module)
        temp_dir = _paths.fresh_test_dir("issue20-external-evidence-cli")
        packet_path = temp_dir / "operator-external-evidence.json"
        authority_pin_path = temp_dir / "operator-authority-pin.json"
        output_path = temp_dir / "harness-report.json"
        validation_path = temp_dir / "harness-validation.json"
        missing_packet_validation_path = temp_dir / "missing-packet-validation.json"
        packet_path.write_text(json.dumps(packet, sort_keys=True), encoding="utf-8")
        authority_pin = _valid_operator_journey_authority_pin(module)
        authority_pin_path.write_text(
            json.dumps(authority_pin, sort_keys=True),
            encoding="utf-8",
        )
        expected_report = _run_passing_report(module, external_evidence=packet)
        local_context = _passing_local_completion_context(module)

        with patch.object(
            module,
            "run_oauth_mcp_harness",
            return_value=expected_report,
        ) as run_harness:
            exit_code = module.main(
                [
                    "--external-evidence",
                    str(packet_path),
                    "--operator-cli-postgresql-authority-pin",
                    str(authority_pin_path),
                    "--output",
                    str(output_path),
                ]
            )
        with patch.object(
            module,
            "_run_local_completion_context",
            return_value=local_context,
        ):
            validation_exit = module.main(
                [
                    "--validate-report",
                    str(output_path),
                    "--external-evidence",
                    str(packet_path),
                    "--operator-cli-postgresql-authority-pin",
                    str(authority_pin_path),
                    "--output",
                    str(validation_path),
                ]
            )
            missing_packet_exit = module.main(
                [
                    "--validate-report",
                    str(output_path),
                    "--output",
                    str(missing_packet_validation_path),
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(validation_exit, 0)
        self.assertEqual(missing_packet_exit, 1)
        run_harness.assert_called_once_with(
            external_evidence=packet,
            operator_execution_authority_pin=authority_pin,
        )
        report = json.loads(output_path.read_text(encoding="utf-8"))
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
        rendered = json.dumps({"report": report, "validation": validation}, sort_keys=True)
        self.assertTrue(validation["passed"])
        self.assertTrue(
            report["claim_boundary"]["supports_external_evidence_packet_contract_claim"]
        )
        self.assertFalse(report["claim_boundary"]["supports_issue20_closure_claim"])
        self.assertNotIn(str(packet_path), rendered)
        self.assertNotIn("operator-external-evidence.json", rendered)

    def test_cli_revalidation_rejects_synthetic_green_report_against_current_authority(
        self,
    ) -> None:
        module = _load_module()
        packet = _valid_external_evidence(module)
        report = _run_passing_report(module, external_evidence=packet)
        temp_dir = _paths.fresh_test_dir("issue20-current-local-authority-revalidation")
        packet_path = temp_dir / "synthetic-external-evidence.json"
        authority_pin_path = temp_dir / "operator-authority-pin.json"
        report_path = temp_dir / "synthetic-green-report.json"
        output_path = temp_dir / "current-authority-validation.json"
        packet_path.write_text(json.dumps(packet, sort_keys=True), encoding="utf-8")
        authority_pin_path.write_text(
            json.dumps(_valid_operator_journey_authority_pin(module), sort_keys=True),
            encoding="utf-8",
        )
        report_path.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")

        exit_code = module.main(
            [
                "--validate-report",
                str(report_path),
                "--external-evidence",
                str(packet_path),
                "--operator-cli-postgresql-authority-pin",
                str(authority_pin_path),
                "--output",
                str(output_path),
            ]
        )

        validation = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 1)
        self.assertFalse(validation["passed"])
        self.assertGreater(validation["blocker_count"], 0)
        rendered = json.dumps(validation, sort_keys=True)
        self.assertNotIn(str(packet_path), rendered)
        self.assertNotIn(str(report_path), rendered)

    def test_cli_invalid_external_packet_exits_nonzero_with_safe_report(self) -> None:
        module = _load_module()
        temp_dir = _paths.fresh_test_dir("issue20-invalid-external-evidence-cli")
        packet_path = temp_dir / "invalid.json"
        output_path = temp_dir / "harness-report.json"
        packet_path.write_text("{not-json", encoding="utf-8")
        invalid_packet = {"external_evidence_input_invalid": True}
        expected_report = _run_passing_report(module, external_evidence=invalid_packet)

        with patch.object(
            module,
            "run_oauth_mcp_harness",
            return_value=expected_report,
        ) as run_harness:
            exit_code = module.main(
                [
                    "--external-evidence",
                    str(packet_path),
                    "--output",
                    str(output_path),
                ]
            )

        self.assertEqual(exit_code, 1)
        run_harness.assert_called_once_with(
            external_evidence=invalid_packet,
            operator_execution_authority_pin=None,
        )
        report = json.loads(output_path.read_text(encoding="utf-8"))
        rendered = json.dumps(report, sort_keys=True)
        self.assertTrue(report["validation"]["passed"])
        self.assertFalse(
            report["claim_boundary"]["supports_external_evidence_packet_contract_claim"]
        )
        self.assertNotIn(str(packet_path), rendered)

    def test_main_direct_success_atomically_replaces_existing_safe_report(self) -> None:
        module = _load_module()
        temp_dir = _paths.fresh_test_dir("issue20-oauth-mcp-harness-main-success")
        output_path = temp_dir / "authoritative-report.json"
        private_marker = "private/path/from/previous/report"
        previous_output = json.dumps(
            {"status": "stale", "private_marker": private_marker},
            sort_keys=True,
        ).encode()
        output_path.write_bytes(previous_output)
        expected_report = _run_passing_report(module)
        initial_entries = {path.name for path in temp_dir.iterdir()}
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            patch.object(
                module,
                "run_oauth_mcp_harness",
                return_value=expected_report,
            ) as run_harness,
            patch.object(
                module,
                "write_json_atomic",
                wraps=module.write_json_atomic,
            ) as atomic_writer,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = module.main(["--output", str(output_path)])

        self.assertEqual(exit_code, 0)
        run_harness.assert_called_once_with(
            external_evidence=None,
            operator_execution_authority_pin=None,
        )
        atomic_writer.assert_called_once_with(output_path, expected_report)
        self.assertEqual(json.loads(output_path.read_text(encoding="utf-8")), expected_report)
        self.assertNotEqual(output_path.read_bytes(), previous_output)
        self.assertEqual(initial_entries, {output_path.name})
        self.assertEqual({path.name for path in temp_dir.iterdir()}, {output_path.name})
        self.assertFalse(output_path.with_suffix(f"{output_path.suffix}.tmp").exists())
        self.assertEqual(list(temp_dir.glob(f".{output_path.name}.*.tmp")), [])
        rendered = output_path.read_text(encoding="utf-8")
        self.assertNotIn(private_marker, rendered)
        self.assertNotIn(str(temp_dir), rendered)
        module.assert_safe_harness_report(expected_report)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_cli_output_write_failure_preserves_previous_artifact_and_cleans_temp(
        self,
    ) -> None:
        module = _load_module()
        temp_dir = _paths.fresh_test_dir("issue20-oauth-mcp-harness-output-write-failure")
        output_path = temp_dir / "authoritative-report.json"
        previous_output = b'{"authority":"previous"}\n'
        output_path.write_bytes(previous_output)
        report = {
            "status": "passed",
            "validation": {"passed": True},
            "claim_boundary": {
                "supports_external_evidence_packet_contract_claim": False,
            },
        }
        original_os_write = os.write
        write_failure_injected = False

        def fail_output_write(descriptor: int, value) -> int:
            nonlocal write_failure_injected
            if not write_failure_injected:
                write_failure_injected = True
                partial = memoryview(value)[: min(len(value), 17)]
                original_os_write(descriptor, partial)
                raise OSError("synthetic private/path/secret")
            return original_os_write(descriptor, value)

        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.object(module, "run_oauth_mcp_harness", return_value=report),
            patch("formowl_core.json_files.os.write", side_effect=fail_output_write),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = module.main(["--output", str(output_path)])

        self.assertEqual(exit_code, 1)
        self.assertTrue(write_failure_injected)
        self.assertEqual(output_path.read_bytes(), previous_output)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(
            json.loads(stderr.getvalue()),
            {
                "artifact_type": "issue20_external_evidence_cli_error_v1",
                "error_code": "output_write_failed",
                "status": "failed",
            },
        )
        self.assertNotIn("private/path/secret", stderr.getvalue())
        self.assertFalse(output_path.with_suffix(f"{output_path.suffix}.tmp").exists())
        self.assertEqual(
            list(temp_dir.glob(f".{output_path.name}.*.tmp")),
            [],
        )
        self.assertEqual(
            list(temp_dir.glob(f".{output_path.name}.*.bak")),
            [],
        )


def _run_passing_report(
    module,
    *,
    external_evidence=None,
    operator_execution_authority_pin=None,
    production_container_lifecycle_evidence=None,
):
    if external_evidence is not None and operator_execution_authority_pin is None:
        operator_execution_authority_pin = _valid_operator_journey_authority_pin(module)
    with patch.object(
        module,
        "validate_function_harness_manifest",
        side_effect=lambda manifest: _passing_onboarding(module, manifest),
    ):
        return module.run_oauth_mcp_harness(
            runner=_passing_evidence,
            manifest_suite_runner=_passing_suite_evidence,
            external_evidence=external_evidence,
            operator_execution_authority_pin=operator_execution_authority_pin,
            production_container_lifecycle_evidence=(production_container_lifecycle_evidence),
        )


def _validate_external_packet(module, packet):
    return module.validate_external_evidence_packet(
        packet,
        expected_local_harness_report_hash=_passing_local_completion_hash(module),
        expected_operator_execution_authority_pin=(_valid_operator_journey_authority_pin(module)),
    )


def _passing_onboarding(module, manifest):
    entries = manifest["functions"]
    test_ids = {test_id for entry in entries for test_id in entry.get("test_ids", [])}
    function_count = len(entries)
    return {
        "passed": True,
        "blockers": [],
        "function_entry_count": function_count,
        "onboarded_function_count": function_count,
        "pending_function_count": 0,
        "changed_function_count": function_count,
        "test_id_count": len(test_ids),
        "manifest_hash": module.sha256_json(manifest),
        "changed_function_set_hash": module.sha256_json(
            sorted((entry["module"], entry["qualname"]) for entry in entries)
        ),
    }


def _passing_local_completion_context(module):
    with patch.object(
        module,
        "validate_function_harness_manifest",
        side_effect=lambda manifest: _passing_onboarding(module, manifest),
    ):
        return module._run_local_completion_context(
            runner=_passing_evidence,
            manifest_suite_runner=_passing_suite_evidence,
        )


def _passing_local_completion_hash(module):
    return _passing_local_completion_context(module).local_completion_audit_report_hash


def _valid_operator_journey_body(module):
    journey = module._operator_journey

    def evidence_hash(label):
        return module.sha256_json({"operator_journey_evidence": label})

    return {
        "artifact_id": journey.ARTIFACT_ID,
        "schema_version": 2,
        "status": "passed",
        "implementation_contract_hash": module.issue20_implementation_contract_hash(module.ROOT),
        "runtime_image_id_hash": evidence_hash("runtime-image-id"),
        "journey_script_hash": journey._sha256_bytes(Path(journey.__file__).read_bytes()),
        "secret_initialization_contract_hash": evidence_hash("secret-initialization"),
        "migration_result_hash": evidence_hash("migration-result"),
        "operator_output_hashes": {
            "bootstrap-owner": evidence_hash("bootstrap-owner"),
            "invite-member": evidence_hash("invite-member"),
            "lookup-owner": evidence_hash("lookup-owner"),
            "list-users": evidence_hash("list-users"),
            "list-member-sessions-before": evidence_hash("list-member-sessions-before"),
            "revoke-member-session": evidence_hash("revoke-member-session"),
            "lookup-member-session-after-revoke": evidence_hash(
                "lookup-member-session-after-revoke"
            ),
            "remove-member": evidence_hash("remove-member"),
            "restore-member": evidence_hash("restore-member"),
            "list-member-sessions-after-restore": evidence_hash(
                "list-member-sessions-after-restore"
            ),
            "operator-audit-contract": evidence_hash("operator-audit-contract"),
            "operator-rollback-state": evidence_hash("operator-rollback-state"),
        },
        "operator_denial_hash": evidence_hash("operator-denial"),
        "counts": {
            "fresh_postgresql_database_count": 1,
            "generated_secret_count": 6,
            "idempotent_secret_rerun_count": 1,
            "migration_command_success_count": 1,
            "operator_cli_success_count": 10,
            "operator_cli_denial_count": 3,
            "operator_audit_total_count": 13,
            "operator_audit_allowed_count": 10,
            "operator_audit_denied_count": 3,
            "runtime_image_build_count": 1,
            "owner_bootstrap_success_count": 1,
            "member_invitation_success_count": 1,
            "member_approval_denial_count": 1,
            "explicit_token_revocation_count": 1,
            "last_owner_removal_denial_count": 1,
            "membership_remove_success_count": 1,
            "membership_restore_success_count": 1,
            "post_restore_active_session_count": 0,
            "post_restore_inactive_session_count": 2,
            "transaction_rollback_probe_count": 1,
            "transaction_rollback_preserved_state_count": 1,
        },
        "attestations": {
            "actual_connected_cli_executed": True,
            "clean_temporary_secret_set_used": True,
            "current_runtime_image_built_from_worktree": True,
            "fresh_postgresql_database_used": True,
            "google_credential_injected_outside_initializer": True,
            "inside_probe_used_installed_runtime_package": True,
            "operator_allow_and_deny_audits_persisted": True,
            "operator_outputs_excluded_sensitive_identity_and_backend_detail": True,
            "report_contains_only_safe_status_count_and_hash_evidence": True,
            "exact_operator_lifecycle_exercised": True,
            "member_approval_denial_audited": True,
            "membership_rollback_verified": True,
            "immutable_runtime_and_postgres_images_used": True,
        },
    }


def _valid_operator_journey_material(module):
    journey = module._operator_journey
    body = _valid_operator_journey_body(module)
    signing_key = journey.Ed25519PrivateKey.from_private_bytes(bytes([17]) * 32)
    authority, signing_key = journey.create_execution_authority(
        implementation_contract_hash=body["implementation_contract_hash"],
        runtime_image_id_hash=body["runtime_image_id_hash"],
        journey_script_hash=body["journey_script_hash"],
        campaign_nonce=bytes([34]) * 32,
        signing_key=signing_key,
    )
    authority_pin = journey.create_execution_authority_pin(authority)
    report = journey.attach_execution_receipt(
        body,
        authority,
        authority_pin,
        signing_key,
    )
    return report, authority, authority_pin


def _valid_operator_journey_report(module):
    return _valid_operator_journey_material(module)[0]


def _valid_operator_journey_authority(module):
    return _valid_operator_journey_material(module)[1]


def _valid_operator_journey_authority_pin(module):
    return _valid_operator_journey_material(module)[2]


def _legacy_operator_journey_report(module):
    journey = module._operator_journey

    def evidence_hash(label):
        return module.sha256_json({"legacy_operator_journey_evidence": label})

    return {
        "artifact_id": journey.ARTIFACT_ID,
        "schema_version": 1,
        "status": "passed",
        "implementation_contract_hash": module.issue20_implementation_contract_hash(module.ROOT),
        "runtime_image_id_hash": evidence_hash("runtime-image-id"),
        "journey_script_hash": journey._sha256_bytes(Path(journey.__file__).read_bytes()),
        "secret_initialization_contract_hash": evidence_hash("secret-initialization"),
        "migration_result_hash": evidence_hash("migration-result"),
        "operator_output_hashes": {
            "lookup-user": evidence_hash("lookup-user"),
            "list-users": evidence_hash("list-users"),
            "lookup-token-session": evidence_hash("lookup-token-session"),
            "list-token-sessions": evidence_hash("list-token-sessions"),
        },
        "operator_denial_hash": evidence_hash("operator-denial"),
        "counts": {
            "fresh_postgresql_database_count": 1,
            "generated_secret_count": 6,
            "idempotent_secret_rerun_count": 1,
            "migration_command_success_count": 1,
            "operator_cli_success_count": 4,
            "operator_cli_denial_count": 1,
            "operator_audit_total_count": 5,
            "operator_audit_allowed_count": 4,
            "operator_audit_denied_count": 1,
            "runtime_image_build_count": 1,
        },
        "attestations": {
            "actual_connected_cli_executed": True,
            "clean_temporary_secret_set_used": True,
            "current_runtime_image_built_from_worktree": True,
            "fresh_postgresql_database_used": True,
            "google_credential_injected_outside_initializer": True,
            "inside_probe_used_installed_runtime_package": True,
            "operator_allow_and_deny_audits_persisted": True,
            "operator_outputs_excluded_sensitive_identity_and_backend_detail": True,
            "report_contains_only_safe_status_count_and_hash_evidence": True,
        },
    }


def _rebind_operator_layer_artifact(module, layer):
    layer_without_artifact_hash = {
        key: value for key, value in layer.items() if key != "evidence_artifact_hash"
    }
    layer["evidence_artifact_hash"] = module.sha256_json(
        {
            "binding_type": module._OPERATOR_EXTERNAL_LAYER_BINDING_TYPE,
            "layer_without_artifact_hash": layer_without_artifact_hash,
        }
    )


def _rebind_live_postgresql_layer_artifact(module, layer):
    layer_without_artifact_hash = {
        key: value for key, value in layer.items() if key != "evidence_artifact_hash"
    }
    layer["evidence_artifact_hash"] = module.sha256_json(
        {
            "evidence_kind": "live_postgresql_external_layer_v3",
            "value": layer_without_artifact_hash,
        }
    )


def _rebind_mcp_inspector_layer_artifact(module, layer):
    bound = module.build_mcp_inspector_external_layer(layer)
    if not bound:
        raise AssertionError("MCP Inspector test layer cannot be bound")
    layer.clear()
    layer.update(bound)


def _rebind_live_chatgpt_google_layer_artifact(module, layer):
    bound = module.build_live_chatgpt_google_external_layer(layer)
    if not bound:
        raise AssertionError("live ChatGPT/Google test layer cannot be bound")
    layer.clear()
    layer.update(bound)


def _valid_live_chatgpt_google_layer(module):
    layer = {}
    for field in module._EXTERNAL_LAYER_FIELDS["live_chatgpt_google"]:
        if field == "evidence_artifact_hash":
            continue
        if field == "status":
            layer[field] = "passed"
        elif field == "operator_attested":
            layer[field] = True
        elif field == "endpoint_scheme":
            layer[field] = "https"
        elif field == "attestations":
            layer[field] = {
                name: True for name in module._EXTERNAL_ATTESTATIONS["live_chatgpt_google"]
            }
        elif field in module._LIVE_CHATGPT_GOOGLE_EXACT_COUNTS:
            layer[field] = module._LIVE_CHATGPT_GOOGLE_EXACT_COUNTS[field]
        elif field == "sequence_hash":
            layer[field] = module.sha256_json(module._LIVE_CHATGPT_GOOGLE_SEQUENCE)
        elif field == "audit_lineage_manifest_hash":
            layer[field] = module.sha256_json(module._LIVE_CHATGPT_GOOGLE_AUDIT_LINEAGE)
        elif field == "audit_lineage_field_set_hash":
            layer[field] = module.sha256_json(module._LIVE_CHATGPT_GOOGLE_AUDIT_LINEAGE_FIELDS)
        elif field.endswith("_hash"):
            layer[field] = module.sha256_json({"test_evidence_field": field})
        else:
            raise AssertionError(f"unhandled live ChatGPT/Google field: {field}")
    return module.build_live_chatgpt_google_external_layer(layer)


def _rebind_reviewer_gate_layer_artifact(module, layer):
    bound = module.build_reviewer_gate_external_layer(layer)
    if not bound:
        raise AssertionError("reviewer-gate test layer cannot be bound")
    layer.clear()
    layer.update(bound)


def _rebind_completion_audit_layer_artifact(module, layer):
    layer_without_artifact_hash = {
        key: value for key, value in layer.items() if key != "evidence_artifact_hash"
    }
    layer["evidence_artifact_hash"] = module.sha256_json(
        {
            "binding_type": "issue20_completion_audit_external_layer_v1",
            "layer_without_artifact_hash": layer_without_artifact_hash,
        }
    )


def _valid_external_evidence(module):
    def evidence_hash(label):
        return module.sha256_json({"external_evidence": label})

    postgres_artifact = evidence_hash("postgres-artifact")
    operator_layer = module.build_operator_cli_postgresql_external_layer(
        _valid_operator_journey_report(module),
        operator_attested=True,
        trusted_execution_authority=_valid_operator_journey_authority(module),
        trusted_execution_authority_pin=_valid_operator_journey_authority_pin(module),
    )
    operator_artifact = operator_layer["evidence_artifact_hash"]
    lifecycle_layer = module.aggregate_production_container_lifecycle_reports(
        [
            _valid_lifecycle_report(module, "external-first"),
            _valid_lifecycle_report(module, "external-second"),
        ],
        operator_attested=True,
    )
    lifecycle_artifact = lifecycle_layer["evidence_artifact_hash"]
    inspector_source_artifact = evidence_hash("inspector-source-artifact")
    inspector_artifact = evidence_hash("inspector-public-artifact-placeholder")
    chatgpt_source_artifact = evidence_hash("chatgpt-source-artifact")
    chatgpt_artifact = evidence_hash("chatgpt-public-artifact-placeholder")
    reviewer_source_artifact = evidence_hash("reviewer-source-artifact")
    reviewer_artifact = evidence_hash("reviewer-public-artifact-placeholder")
    implementation_contract_hash = module.issue20_implementation_contract_hash(module.ROOT)
    packet = {
        "packet_type": module._EXTERNAL_PACKET_TYPE,
        "schema_version": module._EXTERNAL_PACKET_SCHEMA_VERSION,
        "layers": {
            "live_postgresql": {
                "status": "passed",
                "operator_attested": True,
                "endpoint_scheme": "postgresql",
                "evidence_artifact_hash": postgres_artifact,
                "source_report_commitment_hash": evidence_hash("postgres-source-report-commitment"),
                "implementation_contract_hash": implementation_contract_hash,
                "command_contract_hash": module._live_postgresql._command_contract_hash(
                    implementation_contract_hash
                ),
                "schema_state_hash": evidence_hash("postgres-schema"),
                "rollback_state_hash": evidence_hash("postgres-rollback"),
                "first_owner_bootstrap_state_hash": evidence_hash("postgres-bootstrap"),
                "persisted_auth_upload_audit_state_hash": evidence_hash("postgres-persisted-state"),
                "restart_state_hash": evidence_hash("postgres-restart"),
                "second_user_invitation_state_hash": evidence_hash("postgres-second-user"),
                "revocation_expiry_relink_state_hash": evidence_hash(
                    "postgres-revocation-expiry-relink"
                ),
                "signing_key_rotation_state_hash": evidence_hash("postgres-signing-key-rotation"),
                "run_count": 1,
                "pass_count": 1,
                "failure_count": 0,
                "skip_count": 0,
                "fresh_database_count": 1,
                "migration_count": 1,
                "first_owner_bootstrap_count": 1,
                "persisted_auth_count": 1,
                "persisted_upload_count": 1,
                "persisted_audit_count": 12,
                "restart_recovery_count": 1,
                "second_user_invitation_count": 1,
                "revocation_count": 1,
                "post_relink_old_token_denial_count": 1,
                "revoked_token_sessions_after_relink_count": 1,
                "relink_distinct_token_session_count": 1,
                "expiry_denial_count": 1,
                "relink_count": 1,
                "transaction_rollback_probe_count": 1,
                "production_smoke_probe_count": 1,
                "signing_key_rotation_count": 1,
                "overlap_old_token_verification_count": 1,
                "overlap_jwks_public_key_count": 2,
                "new_key_token_verification_count": 1,
                "post_overlap_old_token_denial_count": 1,
                "post_overlap_jwks_public_key_count": 1,
                "post_overlap_new_token_verification_count": 1,
                "private_signing_key_exposure_count": 0,
                "attestations": {
                    "live_server_observed": True,
                    "production_repository_used": True,
                    "no_fake_database": True,
                    "no_sensitive_material_in_packet": True,
                },
            },
            "operator_cli_postgresql": operator_layer,
            "production_container_lifecycle": lifecycle_layer,
            "mcp_inspector": {
                "status": "passed",
                "operator_attested": True,
                "endpoint_scheme": "https",
                "evidence_artifact_hash": inspector_artifact,
                "source_evidence_artifact_hash": inspector_source_artifact,
                "inspector_version_hash": evidence_hash("inspector-version"),
                "sequence_hash": module.sha256_json(module._MCP_INSPECTOR_SEQUENCE),
                "negotiated_protocol_version_hash": evidence_hash("inspector-protocol"),
                "public_initialize_shape_hash": evidence_hash("inspector-public-initialize"),
                "public_tools_list_shape_hash": evidence_hash("inspector-public-tools-list"),
                "protected_tool_challenge_hash": evidence_hash(
                    "inspector-protected-tool-challenge"
                ),
                "invalid_bearer_challenge_hash": evidence_hash(
                    "inspector-invalid-bearer-challenge"
                ),
                "unauthenticated_initialize_count": 1,
                "unauthenticated_tools_list_count": 1,
                "protected_tool_challenge_count": 1,
                "invalid_bearer_challenge_count": 1,
                "semantic_result_count": 0,
                "partial_state_write_count": 0,
                "attestations": {
                    "remote_https_endpoint_observed": True,
                    "real_mcp_inspector_used": True,
                    "no_simulated_inspector": True,
                    "public_discovery_without_oauth_observed": True,
                    "protected_tool_challenge_observed": True,
                    "invalid_bearer_challenge_observed": True,
                    "inspector_oauth_login_not_attempted": True,
                    "inspector_authenticated_journey_not_claimed": True,
                    "no_raw_bearer_supplied": True,
                    "no_semantic_result_or_partial_state": True,
                    "no_sensitive_material_in_packet": True,
                },
            },
            "live_chatgpt_google": {
                "status": "passed",
                "operator_attested": True,
                "endpoint_scheme": "https",
                "evidence_artifact_hash": chatgpt_artifact,
                "source_evidence_artifact_hash": chatgpt_source_artifact,
                "sequence_hash": module.sha256_json(module._LIVE_CHATGPT_GOOGLE_SEQUENCE),
                "audit_lineage_hash": evidence_hash("chatgpt-audit-lineage"),
                "audit_lineage_manifest_hash": module.sha256_json(
                    module._LIVE_CHATGPT_GOOGLE_AUDIT_LINEAGE
                ),
                "audit_lineage_field_set_hash": module.sha256_json(
                    module._LIVE_CHATGPT_GOOGLE_AUDIT_LINEAGE_FIELDS
                ),
                "negotiated_protocol_version_hash": evidence_hash("chatgpt-protocol"),
                "public_initialize_shape_hash": evidence_hash("chatgpt-public-initialize"),
                "public_tools_list_shape_hash": evidence_hash("chatgpt-public-tools-list"),
                "protected_tool_challenge_hash": evidence_hash("chatgpt-protected-tool-challenge"),
                "second_user_invitation_lineage_hash": evidence_hash(
                    "chatgpt-second-user-invitation"
                ),
                "second_user_distinct_subject_commitment_hash": evidence_hash(
                    "chatgpt-second-user-distinct-subject"
                ),
                "second_user_member_workspace_shape_hash": evidence_hash(
                    "chatgpt-second-user-member-workspace-shape"
                ),
                "owner_only_denial_hash": evidence_hash("chatgpt-owner-only-denial"),
                "cross_workspace_denial_hash": evidence_hash("chatgpt-cross-workspace-denial"),
                "forgery_denial_hash": evidence_hash("chatgpt-forgery-denial"),
                "membership_removal_service_audit_hash": evidence_hash(
                    "chatgpt-membership-removal-service-audit"
                ),
                "removed_session_revocation_state_hash": evidence_hash(
                    "chatgpt-removed-session-revocation-state"
                ),
                "removed_token_denial_hash": evidence_hash("chatgpt-removed-token-denial"),
                "restart_removed_token_denial_hash": evidence_hash(
                    "chatgpt-restart-removed-token-denial"
                ),
                "removed_membership_relink_denial_hash": evidence_hash(
                    "chatgpt-removed-membership-relink-denial"
                ),
                "removed_membership_relink_zero_state_hash": evidence_hash(
                    "chatgpt-removed-membership-relink-zero-state"
                ),
                "membership_restore_service_audit_hash": evidence_hash(
                    "chatgpt-membership-restore-service-audit"
                ),
                "post_restore_old_session_denial_hash": evidence_hash(
                    "chatgpt-post-restore-old-session-denial"
                ),
                "restore_relink_identity_session_hash": evidence_hash(
                    "chatgpt-restore-relink-identity-session"
                ),
                "post_revocation_relink_identity_session_hash": evidence_hash(
                    "chatgpt-post-revocation-relink-identity-session"
                ),
                "post_expiry_relink_identity_session_hash": evidence_hash(
                    "chatgpt-post-expiry-relink-identity-session"
                ),
                "revocation_lineage_hash": evidence_hash("chatgpt-revocation-lineage"),
                "expiry_lineage_hash": evidence_hash("chatgpt-expiry-lineage"),
                "discovery_initialize_count": 1,
                "discovery_tools_list_count": 1,
                "protected_tool_challenge_count": 1,
                "google_authorization_count": 6,
                "google_callback_count": 6,
                "token_exchange_count": 5,
                "whoami_count": 5,
                "upload_session_count": 1,
                "second_user_invitation_count": 1,
                "second_user_google_login_count": 1,
                "second_user_whoami_count": 1,
                "distinct_external_subject_count": 2,
                "distinct_formowl_user_count": 2,
                "second_user_member_workspace_binding_count": 1,
                "owner_only_denial_count": 1,
                "cross_workspace_denial_count": 1,
                "forgery_denial_count": 1,
                "owner_only_denial_semantic_result_count": 0,
                "owner_only_denial_partial_state_write_count": 0,
                "cross_workspace_denial_semantic_result_count": 0,
                "cross_workspace_denial_partial_state_write_count": 0,
                "forgery_denial_semantic_result_count": 0,
                "forgery_denial_partial_state_write_count": 0,
                "membership_removal_count": 1,
                "membership_removal_service_audit_count": 1,
                "removal_revoked_session_count": 1,
                "removed_token_denial_count": 1,
                "restart_removed_token_denial_count": 1,
                "removed_membership_relink_denial_count": 1,
                "removed_relink_authorization_code_issued_count": 0,
                "removed_relink_token_session_created_count": 0,
                "removed_relink_membership_write_count": 0,
                "membership_restore_count": 1,
                "membership_restore_service_audit_count": 1,
                "owner_attributed_membership_mutation_count": 0,
                "post_restore_old_session_denial_count": 1,
                "restore_relink_same_subject_user_new_session_count": 1,
                "post_revocation_relink_same_subject_user_new_session_count": 1,
                "post_expiry_relink_same_subject_user_new_session_count": 1,
                "revocation_count": 1,
                "revoked_token_denial_count": 1,
                "expiry_denial_count": 1,
                "relink_count": 3,
                "relinked_whoami_count": 3,
                "audit_lineage_event_count": len(module._LIVE_CHATGPT_GOOGLE_AUDIT_LINEAGE),
                "attestations": {
                    "real_chatgpt_connector_used": True,
                    "live_google_login_observed": True,
                    "public_https_endpoint_observed": True,
                    "no_fake_google_provider": True,
                    "no_simulated_chatgpt_client": True,
                    "public_discovery_without_oauth_observed": True,
                    "protected_tool_challenge_observed": True,
                    "second_real_google_user_observed": True,
                    "second_user_distinct_from_owner_observed": True,
                    "second_user_member_role_and_workspace_observed": True,
                    "owner_only_and_cross_workspace_denials_distinct": True,
                    "fake_google_or_postgresql_not_used_for_second_person": True,
                    "membership_removal_restart_restore_observed": True,
                    "removed_membership_relink_denied": True,
                    "removed_membership_relink_zero_partial_state_observed": True,
                    "old_session_remained_denied_after_restore": True,
                    "all_successful_relinks_preserved_subject_user_and_created_new_session": True,
                    "operator_membership_actions_service_attributed": True,
                    "operator_never_attributed_as_owner_user": True,
                    "denials_returned_no_semantic_result_or_partial_state": True,
                    "exact_audit_lineage_observed": True,
                    "no_sensitive_material_in_packet": True,
                },
            },
            "reviewer_gate": {
                "status": "passed",
                "operator_attested": True,
                "evidence_artifact_hash": reviewer_artifact,
                "source_evidence_artifact_hash": reviewer_source_artifact,
                "reviewer_set_hash": evidence_hash("reviewer-set"),
                "review_packet_hash": evidence_hash("review-packet"),
                "reviewer_count": 3,
                "agreement_count": 3,
                "blocking_finding_count": 0,
                "attestations": {
                    "read_only_reviewers_used": True,
                    "no_outstanding_blockers": True,
                    "scoped_packet_excluded_sensitive_material": True,
                },
            },
            "completion_audit": {
                "status": "passed",
                "operator_attested": True,
                "evidence_artifact_hash": evidence_hash("completion-audit-artifact"),
                "source_evidence_artifact_hash": evidence_hash("completion-audit-source-artifact"),
                "implementation_contract_hash": implementation_contract_hash,
                "local_harness_report_hash": _passing_local_completion_hash(module),
                "live_postgresql_artifact_hash": postgres_artifact,
                "operator_cli_postgresql_artifact_hash": operator_artifact,
                "operator_execution_authority_pin_hash": module.sha256_json(
                    _valid_operator_journey_authority_pin(module)
                ),
                "production_container_lifecycle_artifact_hash": lifecycle_artifact,
                "mcp_inspector_artifact_hash": inspector_artifact,
                "live_chatgpt_google_artifact_hash": chatgpt_artifact,
                "reviewer_gate_artifact_hash": reviewer_artifact,
                "actor_context_contract_hash": module._repository_contract_hash(
                    module._ACTOR_CONTEXT_CONTRACT_PATHS
                ),
                "documentation_contract_hash": module._repository_contract_hash(
                    module._DOCUMENTATION_CONTRACT_PATHS
                ),
                "journey_manifest_hash": module.sha256_json(module._ISSUE20_COMPLETION_JOURNEYS),
                "journey_count": len(module._ISSUE20_COMPLETION_JOURNEYS),
                "passed_journey_count": len(module._ISSUE20_COMPLETION_JOURNEYS),
                "missing_journey_count": 0,
                "blocking_finding_count": 0,
                "attestations": {
                    "independent_completion_audit_used": True,
                    "all_layer_artifacts_recomputed": True,
                    "actor_context_contract_reviewed": True,
                    "documentation_state_reviewed": True,
                    "work_board_remains_authoritative": True,
                    "no_sensitive_material_in_packet": True,
                },
            },
        },
    }
    live_postgresql_layer = packet["layers"]["live_postgresql"]
    _rebind_live_postgresql_layer_artifact(module, live_postgresql_layer)
    packet["layers"]["completion_audit"]["live_postgresql_artifact_hash"] = live_postgresql_layer[
        "evidence_artifact_hash"
    ]
    mcp_inspector_layer = packet["layers"]["mcp_inspector"]
    _rebind_mcp_inspector_layer_artifact(module, mcp_inspector_layer)
    packet["layers"]["completion_audit"]["mcp_inspector_artifact_hash"] = mcp_inspector_layer[
        "evidence_artifact_hash"
    ]
    live_chatgpt_google_layer = packet["layers"]["live_chatgpt_google"]
    _rebind_live_chatgpt_google_layer_artifact(module, live_chatgpt_google_layer)
    packet["layers"]["completion_audit"]["live_chatgpt_google_artifact_hash"] = (
        live_chatgpt_google_layer["evidence_artifact_hash"]
    )
    reviewer_gate_layer = packet["layers"]["reviewer_gate"]
    _rebind_reviewer_gate_layer_artifact(module, reviewer_gate_layer)
    packet["layers"]["completion_audit"]["reviewer_gate_artifact_hash"] = reviewer_gate_layer[
        "evidence_artifact_hash"
    ]
    _rebind_completion_audit_layer_artifact(
        module,
        packet["layers"]["completion_audit"],
    )
    return packet


def _valid_lifecycle_report(module, label):
    lifecycle = module._lifecycle_probe
    core_hash = lifecycle._sha256_json({"core": label})
    runtime_image_id = lifecycle._sha256_json({"runtime_image_id": "stable"})
    security_contracts = [
        {
            "process_uid": lifecycle.RUNTIME_UID,
            "process_gid": lifecycle.RUNTIME_UID,
            "process_supplementary_group_count": 0,
            "process_capability_count": 0,
            "process_no_new_privileges": 1,
            "probe_uid": lifecycle.RUNTIME_UID,
            "probe_gid": lifecycle.RUNTIME_UID,
            "probe_supplementary_group_count": 0,
            "probe_root_regain_denied": True,
            "health_uses_privilege_drop_launcher": True,
            "health_status_healthy": True,
            "successful_healthcheck_count": 1,
        }
        for _ in range(3)
    ]
    secret_snapshots = [
        {
            "file_count": count,
            "content_hash": lifecycle._sha256_json(
                {"compose_secret_content": label, "generation": index}
            ),
            "instance_hash": lifecycle._sha256_json(
                {"compose_secret_instance": label, "generation": index}
            ),
        }
        for index, count in enumerate((5, 6, 5), start=1)
    ]
    compose_jwks_phases = [
        {
            "key_count": count,
            "kid_set_hash": lifecycle._sha256_json({"compose_jwks": label, "generation": index}),
        }
        for index, count in enumerate((1, 2, 1), start=1)
    ]
    evidence = {
        "runtime_image_id": runtime_image_id,
        "image_contract": {
            "runtime_image_id": runtime_image_id,
            "entrypoint": ["formowl-connected-mcp"],
            "cmd": ["serve"],
            "user": "formowl",
            "working_dir": "/home/formowl",
            "implementation_contract_hash": (
                lifecycle._current_issue20_implementation_contract_hash()
            ),
        },
        "compose_projection": {
            "connected_command": ["serve"],
            "migrate_command": ["migrate"],
            "read_only": True,
            "cap_drop": ["ALL"],
            "cap_add": sorted(lifecycle.LAUNCHER_CAPABILITIES),
            "security_opt": ["no-new-privileges:true"],
            "tmpfs": ["/run/formowl-secrets", "/tmp"],
            "stop_grace_period": "30s",
            "health_uses_readyz": True,
            "health_uses_privilege_drop_launcher": True,
            "dockerfile": "containers/runtime/Dockerfile",
            "connected_image_id": runtime_image_id,
            "migrate_image_id": runtime_image_id,
            "project_image_id": runtime_image_id,
            "wiki_image_id": runtime_image_id,
            "postgres_image": lifecycle.PINNED_POSTGRES_IMAGE,
            "connected_secret_sources": sorted(lifecycle._RUNTIME_SECRET_NAMES),
            "migrate_secret_sources": sorted(lifecycle._RUNTIME_SECRET_NAMES),
            "postgres_secret_sources": ["formowl_postgres_password"],
            "project_command": ["python", "-m", "formowl_project_mcp"],
            "wiki_command": ["python", "-m", "formowl_wiki_mcp"],
            "pre_secret_bootstrap_mode": "built_runtime_image_docker_run",
            "operator_owned_0400_secret_count": 7,
            "secret_owner_distinct_from_runtime": True,
        },
        "compose_service_count": 5,
        "compose_journey": {
            "postgres_secret_contract": {
                "secret_mount_read_only": True,
                "password_file_environment_present": True,
                "plaintext_password_environment_absent": True,
            },
            "migration": {
                "status": "ok",
                "applied_migration_count": lifecycle.EXPECTED_MIGRATION_COUNT,
                "skipped_migration_count": 0,
            },
            "preflight_check_count": 2,
            "runtime_ready_count": 3,
            "healthcheck_success_count": 3,
            "retired_container_count": 2,
            "runtime_process_uid": lifecycle.RUNTIME_UID,
            "security_contracts": security_contracts,
            "secret_snapshots": secret_snapshots,
            "jwks_phases": compose_jwks_phases,
            "runtime_log_hashes": [
                lifecycle._sha256_json({"compose_log": label, "generation": index})
                for index in range(1, 4)
            ],
        },
        "initial_migration": {
            "status": "ok",
            "applied_migration_count": 5,
            "skipped_migration_count": 0,
        },
        "restart_migration": {
            "status": "ok",
            "applied_migration_count": 0,
            "skipped_migration_count": 5,
        },
        "oauth_seed": {
            "status": "ok",
            "seed_count": 1,
            "seed_state_hash": lifecycle._sha256_json({"seed": "stable"}),
        },
        "first_client": {
            "status": "ok",
            "allowed_count": 2,
            "denied_count": 1,
            "result_shape_hash": lifecycle._sha256_json({"first_client": label}),
        },
        "restart_client": {
            "status": "ok",
            "allowed_count": 1,
            "denied_count": 0,
            "result_shape_hash": lifecycle._sha256_json({"restart_client": label}),
        },
        "first_state": {
            "status": "ok",
            "counts": {
                "user_count": 1,
                "external_identity_count": 1,
                "token_session_count": 1,
                "upload_session_count": 1,
                "file_audit_count": 1,
                "mcp_allowed_count": 2,
                "mcp_denied_count": 1,
            },
            "core_state_hash": core_hash,
            "snapshot_hash": lifecycle._sha256_json({"first_state": label}),
        },
        "restart_state": {
            "status": "ok",
            "counts": {
                "user_count": 1,
                "external_identity_count": 1,
                "token_session_count": 1,
                "upload_session_count": 1,
                "file_audit_count": 1,
                "mcp_allowed_count": 3,
                "mcp_denied_count": 1,
            },
            "core_state_hash": core_hash,
            "snapshot_hash": lifecycle._sha256_json({"restart_state": label}),
        },
        "migration_applied_count": 5,
        "migration_restart_skipped_count": 5,
        "readiness_shapes": [{"status": "ready", "checks": ["database", "runtime"]}] * 4,
        "jwks_phases": [
            {"key_count": 1, "kid_set_hash": lifecycle._sha256_json(["a"])},
            {"key_count": 2, "kid_set_hash": lifecycle._sha256_json(["a", "b"])},
            {"key_count": 1, "kid_set_hash": lifecycle._sha256_json(["b"])},
        ],
        "security_contract": {
            "process_uid": lifecycle.RUNTIME_UID,
            "read_only": True,
        },
        "runtime_log_hashes": [lifecycle._sha256_json({"log": "stable"})] * 4,
        "runtime_log_line_count": 0,
        "data_state_hash": lifecycle._sha256_json({"data": "stable"}),
    }
    return lifecycle._build_success_report(evidence)


def _passing_evidence() -> dict[str, object]:
    return {
        "metadata_and_jwks_verified": True,
        "protocol_negotiation_verified": True,
        "unauthenticated_challenges_verified": True,
        "authorization_code_pkce_flow_verified": True,
        "google_identity_mapping_verified": True,
        "bearer_streamable_http_mcp_verified": True,
        "whoami_verified": True,
        "allowed_workspace_upload_session_verified": True,
        "cross_workspace_and_forgery_denied": True,
        "revocation_immediate": True,
        "same_subject_reconnect_verified": True,
        "negative_matrix_verified": True,
        "rollback_matrix_verified": True,
        "audit_lineage_verified": True,
        "leak_scan_verified": True,
        "scenario_contract_hash": "sha256:" + "1" * 64,
        "http_exchange_shape_hash": "sha256:" + "2" * 64,
        "audit_lineage_shape_hash": "sha256:" + "3" * 64,
        "negotiated_protocol_version_hash": "sha256:" + "4" * 64,
        "supported_protocol_matrix_hash": "sha256:" + "5" * 64,
        "http_exchange_count": 18,
        "negative_case_count": 24,
        "rollback_case_count": 8,
        "audit_event_count": 16,
    }


def _passing_suite_evidence(manifest):
    from oauth_harness import sha256_json

    test_ids = sorted(
        {test_id for entry in manifest["functions"] for test_id in entry.get("test_ids", [])}
    )
    coverage = {test_id: [] for test_id in test_ids}
    pairs = []
    for entry in manifest["functions"]:
        key = [entry["module"], entry["qualname"]]
        for test_id in entry.get("test_ids", []):
            coverage[test_id].append(key)
            pairs.append((test_id, *key))
    count = len(test_ids)
    return {
        "passed": True,
        "requested_test_count": count,
        "resolved_test_count": count,
        "run_count": count,
        "pass_count": count,
        "skip_count": 0,
        "failure_count": 0,
        "error_count": 0,
        "expected_failure_count": 0,
        "unexpected_success_count": 0,
        "resolution_blocker_count": 0,
        "test_set_hash": sha256_json(test_ids),
        "executed_test_set_hash": sha256_json(test_ids),
        "coverage_pairs_hash": sha256_json(sorted(pairs)),
        "covered_function_count": len(
            {(entry["module"], entry["qualname"]) for entry in manifest["functions"]}
        ),
        "_coverage_by_test": coverage,
    }


if __name__ == "__main__":
    unittest.main()
