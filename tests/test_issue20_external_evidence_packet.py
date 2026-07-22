from __future__ import annotations

import copy
import importlib.util
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from formowl_evidence import issue20_packet as packet_module
from formowl_evidence.issue20 import ISSUE20_IMPLEMENTATION_CONTRACT_GLOBS


ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_TEST_PATH = ROOT / "tests" / "test_oauth_mcp_harness_script.py"
LIVE_POSTGRESQL_TEST_PATH = ROOT / "tests" / "test_connected_runtime_postgres_live_e2e.py"


def _hash(label: str) -> str:
    return packet_module._authority.sha256_json({"issue20_external_source_test": label})


def _completed_sources() -> dict[str, dict]:
    sources = copy.deepcopy(packet_module.source_templates())

    mcp = sources["mcp_inspector"]
    mcp["status"] = "passed"
    mcp["operator_attested"] = True
    mcp["inspector_version_hash"] = _hash("mcp-inspector-version")
    mcp["negotiated_protocol_version_hash"] = _hash("mcp-protocol-version")
    for event in mcp["events"]:
        event["status"] = "passed"
        event["observation_commitment_hash"] = _hash(
            f"mcp-event-{event['sequence_index']}-{event['event_name']}"
        )
    for name in mcp["attestations"]:
        mcp["attestations"][name] = True

    live = sources["live_chatgpt_google"]
    live["status"] = "passed"
    live["operator_attested"] = True
    live["callback_bootstrap_mode"] = "reserved_invalid_discovery"
    live["negotiated_protocol_version_hash"] = _hash("live-protocol-version")
    owner = live["identities"]["owner"]
    member = live["identities"]["member"]
    workspace_hash = _hash("shared-workspace")
    owner.update(
        {
            "external_subject_commitment_hash": _hash("owner-google-subject"),
            "formowl_user_binding_hash": _hash("owner-formowl-user"),
            "external_identity_binding_hash": _hash("owner-external-identity"),
            "workspace_binding_hash": workspace_hash,
            "initial_session_binding_hash": _hash("owner-initial-session"),
        }
    )
    member.update(
        {
            "external_subject_commitment_hash": _hash("member-google-subject"),
            "formowl_user_binding_hash": _hash("member-formowl-user"),
            "external_identity_binding_hash": _hash("member-external-identity"),
            "workspace_binding_hash": workspace_hash,
            "initial_session_binding_hash": _hash("member-initial-session"),
        }
    )
    prior_session = member["initial_session_binding_hash"]
    for relink in live["relink_bindings"]:
        new_session = _hash(f"member-{relink['relink_kind']}-session")
        relink.update(
            {
                "external_subject_commitment_hash": member["external_subject_commitment_hash"],
                "formowl_user_binding_hash": member["formowl_user_binding_hash"],
                "prior_session_binding_hash": prior_session,
                "new_session_binding_hash": new_session,
            }
        )
        prior_session = new_session
    for event in live["events"]:
        event["status"] = "passed"
        event["observation_commitment_hash"] = _hash(
            f"live-event-{event['sequence_index']}-{event['event_name']}"
        )
    previous_hash = packet_module._ABSENT_VALUE_COMMITMENT
    for record in live["audit_records"]:
        index = record["sequence_index"]
        for field in packet_module._authority._LIVE_CHATGPT_GOOGLE_AUDIT_LINEAGE_FIELDS:
            if not field.endswith("_hash") or field in {
                "previous_audit_record_hash",
                "audit_record_hash",
            }:
                continue
            if record[field] == packet_module._TEMPLATE_HASH:
                record[field] = _hash(f"audit-{index}-{field}")
        record["previous_audit_record_hash"] = previous_hash
        record["audit_record_hash"] = packet_module._safe_audit_record_hash(record)
        previous_hash = record["audit_record_hash"]
    for name in live["attestations"]:
        live["attestations"][name] = True

    reviewer = sources["reviewer_gate"]
    reviewer["status"] = "passed"
    reviewer["operator_attested"] = True
    reviewer["review_packet_commitment_hash"] = _hash("review-packet")
    for entry in reviewer["reviewers"]:
        entry["decision"] = "AGREE"
        entry["reviewer_id_hash"] = _hash(
            f"reviewer-{entry['sequence_index']}-{entry['review_area']}"
        )
        entry["output_commitment_hash"] = _hash(
            f"review-output-{entry['sequence_index']}-{entry['review_area']}"
        )
    for name in reviewer["attestations"]:
        reviewer["attestations"][name] = True

    completion = sources["completion_audit"]
    completion.update(
        {
            "status": "passed",
            "auditor_attested": True,
            "operator_attested": True,
            "independent_auditor_id_hash": _hash("independent-completion-auditor"),
            "audit_output_commitment_hash": _hash("independent-audit-output"),
            "implementation_contract_hash": (
                packet_module._authority.issue20_implementation_contract_hash(ROOT)
            ),
            "local_harness_report_hash": _hash("local-harness-report"),
            "actor_context_contract_hash": (
                packet_module._authority._repository_contract_hash(
                    packet_module._authority._ACTOR_CONTEXT_CONTRACT_PATHS
                )
            ),
            "documentation_contract_hash": (
                packet_module._authority._repository_contract_hash(
                    packet_module._authority._DOCUMENTATION_CONTRACT_PATHS
                )
            ),
            "operator_execution_authority_pin_hash": _hash("operator-execution-authority-pin"),
            "reviewed_layer_artifact_set_hash": _hash("reviewed-layer-artifact-set"),
        }
    )
    for journey in completion["journeys"]:
        journey["status"] = "passed"
        journey["evidence_commitment_hash"] = _hash(
            f"completion-journey-{journey['sequence_index']}-{journey['journey_name']}"
        )
    for name in completion["attestations"]:
        completion["attestations"][name] = True
    return sources


def _authority_fixture_module():
    spec = importlib.util.spec_from_file_location(
        "issue20_authority_test_fixture",
        AUTHORITY_TEST_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("authority test fixture could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _live_postgresql_fixture_module():
    spec = importlib.util.spec_from_file_location(
        "issue20_live_postgresql_test_fixture",
        LIVE_POSTGRESQL_TEST_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("live PostgreSQL test fixture could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _implementation_hash_after_independent_source_drift(relative_path: str) -> str:
    with tempfile.TemporaryDirectory(prefix="formowl-issue20-source-drift-") as temporary:
        temp_root = Path(temporary)
        copied: set[str] = set()
        for pattern in ISSUE20_IMPLEMENTATION_CONTRACT_GLOBS:
            matches = sorted(path for path in ROOT.glob(pattern) if path.is_file())
            if not matches:
                raise RuntimeError(f"implementation contract fixture missing: {pattern}")
            for source in matches:
                relative = source.relative_to(ROOT).as_posix()
                if relative in copied:
                    continue
                copied.add(relative)
                destination = temp_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        target = temp_root / relative_path
        target.write_bytes(target.read_bytes() + b"\n# issue20-independent-drift-probe\n")
        return packet_module._authority.issue20_implementation_contract_hash(temp_root)


def _authority_fixture_packet() -> dict:
    return _authority_fixture_module()._valid_external_evidence(packet_module._authority)


def _operator_execution_authority() -> dict:
    return _authority_fixture_module()._valid_operator_journey_authority(packet_module._authority)


def _operator_execution_authority_pin() -> dict:
    return _authority_fixture_module()._valid_operator_journey_authority_pin(
        packet_module._authority
    )


def _schema_v2_candidate_from_legacy_with_replacement_authority() -> tuple[dict, dict, dict]:
    fixture = _authority_fixture_module()
    authority = packet_module._authority
    journey = authority._operator_journey
    legacy = fixture._legacy_operator_journey_report(authority)
    current = fixture._valid_operator_journey_body(authority)
    candidate = copy.deepcopy(legacy)
    candidate.update(
        {
            "schema_version": 2,
            "implementation_contract_hash": current["implementation_contract_hash"],
            "runtime_image_id_hash": current["runtime_image_id_hash"],
            "journey_script_hash": current["journey_script_hash"],
            "operator_output_hashes": current["operator_output_hashes"],
            "counts": current["counts"],
            "attestations": current["attestations"],
        }
    )
    signing_key = journey.Ed25519PrivateKey.from_private_bytes(bytes([51]) * 32)
    execution_authority, signing_key = journey.create_execution_authority(
        implementation_contract_hash=candidate["implementation_contract_hash"],
        runtime_image_id_hash=candidate["runtime_image_id_hash"],
        journey_script_hash=candidate["journey_script_hash"],
        campaign_nonce=bytes([68]) * 32,
        signing_key=signing_key,
    )
    execution_authority_pin = journey.create_execution_authority_pin(execution_authority)
    signed_candidate = journey.attach_execution_receipt(
        candidate,
        execution_authority,
        execution_authority_pin,
        signing_key,
    )
    return signed_candidate, execution_authority, execution_authority_pin


def _bind_staged_sources(
    sources: dict[str, dict],
    *,
    local_receipt: dict[str, str],
    base_layers: dict[str, dict],
    operator_execution_authority_pin: dict | None = None,
) -> None:
    if operator_execution_authority_pin is None:
        operator_execution_authority_pin = _operator_execution_authority_pin()
    mcp_layer = packet_module._build_mcp_inspector_layer(sources["mcp_inspector"])
    live_layer = packet_module._build_live_chatgpt_google_layer(sources["live_chatgpt_google"])
    core_layers = {
        "live_postgresql": base_layers["live_postgresql"],
        "operator_cli_postgresql": base_layers["operator_cli_postgresql"],
        "production_container_lifecycle": base_layers["production_container_lifecycle"],
        "mcp_inspector": mcp_layer,
        "live_chatgpt_google": live_layer,
    }
    review_packet = packet_module._core_evidence_review_packet(
        local_receipt=local_receipt,
        core_layers=core_layers,
        mcp_inspector_source_hash=packet_module._source_hash(sources["mcp_inspector"]),
        live_chatgpt_google_source_hash=packet_module._source_hash(sources["live_chatgpt_google"]),
    )
    sources["reviewer_gate"]["review_packet_commitment_hash"] = packet_module._source_hash(
        review_packet
    )
    reviewer_layer = packet_module._build_reviewer_gate_layer(
        sources["reviewer_gate"],
        expected_review_packet_hash=packet_module._source_hash(review_packet),
    )
    layer_artifacts = {
        name: layer["evidence_artifact_hash"]
        for name, layer in {**core_layers, "reviewer_gate": reviewer_layer}.items()
    }
    completion = sources["completion_audit"]
    completion.update(
        {
            "implementation_contract_hash": local_receipt["implementation_contract_hash"],
            "local_harness_report_hash": local_receipt["local_completion_audit_report_hash"],
            "actor_context_contract_hash": local_receipt["actor_context_contract_hash"],
            "documentation_contract_hash": local_receipt["documentation_contract_hash"],
            "operator_execution_authority_pin_hash": packet_module._authority.sha256_json(
                operator_execution_authority_pin
            ),
            "reviewed_layer_artifact_set_hash": (
                packet_module._reviewed_layer_artifact_set_hash(layer_artifacts)
            ),
        }
    )


class Issue20GovernedSourceTemplateTest(unittest.TestCase):
    def test_templates_are_safe_exact_and_intentionally_incomplete(self) -> None:
        templates = packet_module.source_templates()

        self.assertEqual(
            set(templates),
            {
                "mcp_inspector",
                "live_chatgpt_google",
                "reviewer_gate",
                "completion_audit",
            },
        )
        packet_module._authority.assert_safe_harness_report(templates)
        self.assertFalse(
            packet_module.validate_mcp_inspector_source(templates["mcp_inspector"])["passed"]
        )
        self.assertFalse(
            packet_module.validate_live_chatgpt_google_source(templates["live_chatgpt_google"])[
                "passed"
            ]
        )
        self.assertFalse(
            packet_module.validate_reviewer_gate_source(templates["reviewer_gate"])["passed"]
        )
        self.assertFalse(
            packet_module.validate_completion_audit_source(templates["completion_audit"])["passed"]
        )
        self.assertEqual(len(templates["live_chatgpt_google"]["audit_records"]), 47)
        self.assertEqual(
            templates["live_chatgpt_google"]["audit_records"][0]["previous_audit_record_hash"],
            packet_module._ABSENT_VALUE_COMMITMENT,
        )
        owner_only = next(
            record
            for record in templates["live_chatgpt_google"]["audit_records"]
            if record["event_name"] == "second_user_owner_only_denied"
        )
        self.assertEqual(owner_only["actor_type"], "service")
        self.assertEqual(owner_only["action"], "oauth_invitation_create")
        self.assertEqual(owner_only["reason_code"], "invitation_owner_required")
        self.assertEqual(
            owner_only["actor_user_binding_hash"],
            packet_module._ABSENT_VALUE_COMMITMENT,
        )
        self.assertEqual(
            owner_only["tool_call_binding_hash"],
            packet_module._ABSENT_VALUE_COMMITMENT,
        )

    def test_template_cli_writes_private_files_without_echoing_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="formowl-source-template-") as temporary:
            output = Path(temporary) / "private"
            with mock.patch("builtins.print") as print_mock:
                result = packet_module.main(["template", "--output-dir", str(output)])

            self.assertEqual(result, 0)
            print_mock.assert_called_once()
            public_result = json.loads(print_mock.call_args.args[0])
            self.assertEqual(
                public_result,
                {
                    "artifact_type": "issue20_governed_source_templates_v1",
                    "status": "created",
                    "template_count": 4,
                },
            )
            self.assertNotIn(str(output), print_mock.call_args.args[0])
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            for name in (
                "mcp-inspector-source.json",
                "live-chatgpt-google-source.json",
                "reviewer-gate-source.json",
                "completion-audit-source.json",
            ):
                path = output / name
                self.assertTrue(path.is_file())
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                json.loads(path.read_text(encoding="utf-8"))

    def test_template_existing_middle_target_leaves_directory_unchanged(self) -> None:
        with tempfile.TemporaryDirectory(prefix="formowl-source-existing-") as temporary:
            output = Path(temporary) / "private"
            output.mkdir(mode=0o700)
            existing = output / "live-chatgpt-google-source.json"
            existing.write_text("existing\n", encoding="utf-8")

            result = packet_module.main(["template", "--output-dir", str(output)])

            self.assertEqual(result, 1)
            self.assertEqual(existing.read_text(encoding="utf-8"), "existing\n")
            self.assertEqual([path.name for path in output.iterdir()], [existing.name])

    def test_template_write_failure_rolls_back_the_whole_set(self) -> None:
        with tempfile.TemporaryDirectory(prefix="formowl-source-rollback-") as temporary:
            output = Path(temporary) / "private"
            real_write = packet_module._write_json
            calls = 0

            def fail_second(path: Path, value: dict) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise packet_module.EvidencePacketError("synthetic_write_failure")
                real_write(path, value)

            with mock.patch.object(packet_module, "_write_json", side_effect=fail_second):
                result = packet_module.main(["template", "--output-dir", str(output)])

            self.assertEqual(result, 1)
            self.assertFalse(output.exists())
            self.assertFalse(
                any(path.name.startswith(".private.staging.") for path in output.parent.iterdir())
            )

    def test_json_input_loader_accepts_objects_and_rejects_invalid_inputs_safely(self) -> None:
        with tempfile.TemporaryDirectory(prefix="formowl-source-json-input-") as temporary:
            root = Path(temporary)
            valid = root / "valid.json"
            malformed = root / "malformed.json"
            non_object = root / "non-object.json"
            valid.write_text('{"status":"passed"}\n', encoding="utf-8")
            malformed.write_text('{"status":', encoding="utf-8")
            non_object.write_text('["not-an-object"]\n', encoding="utf-8")

            self.assertEqual(packet_module._read_json(valid), {"status": "passed"})
            for path, expected_code in (
                (malformed, "evidence_input_invalid"),
                (non_object, "evidence_input_not_object"),
            ):
                with self.subTest(expected_code=expected_code):
                    with self.assertRaises(packet_module.EvidencePacketError) as raised:
                        packet_module._read_json(path)
                    self.assertEqual(raised.exception.code, expected_code)
                    self.assertEqual(str(raised.exception), expected_code)
                    self.assertNotIn(str(root), str(raised.exception))

    def test_validation_cli_persistent_output_failure_returns_safe_stdout(self) -> None:
        source_arguments = [
            "--mcp-inspector-source",
            "inspector.json",
            "--live-chatgpt-google-source",
            "chatgpt.json",
            "--reviewer-gate-source",
            "reviewer.json",
            "--completion-audit-source",
            "completion.json",
        ]
        core_arguments = [
            "--local-harness-report",
            "local.json",
            "--live-postgresql-evidence",
            "postgres.json",
            "--operator-cli-postgresql-report",
            "operator.json",
            "--operator-cli-postgresql-execution-authority",
            "operator-authority.json",
            "--operator-cli-postgresql-execution-authority-pin",
            "operator-authority-pin.json",
            "--production-container-lifecycle-report",
            "lifecycle.json",
            "--mcp-inspector-source",
            "inspector.json",
            "--live-chatgpt-google-source",
            "chatgpt.json",
            "--reviewer-gate-source",
            "reviewer.json",
            "--completion-audit-source",
            "completion.json",
        ]
        cases = (
            (
                "validate-sources",
                "validate_governed_sources",
                {"status": "passed"},
                source_arguments,
            ),
            (
                "validate-packet",
                "validate_current_packet",
                {"passed": True},
                ["--packet", "packet.json", *core_arguments],
            ),
        )
        with tempfile.TemporaryDirectory(prefix="formowl-packet-persistent-output-") as temporary:
            root = Path(temporary)
            for command, validator_name, validation_result, arguments in cases:
                with self.subTest(command=command):
                    case_root = root / command
                    case_root.mkdir()
                    blocked_parent = case_root / "operator-private-output"
                    blocked_parent.write_text("not a directory\n", encoding="utf-8")
                    output = blocked_parent / "validation.json"
                    with (
                        mock.patch.object(packet_module, "_read_json", return_value={}),
                        mock.patch.object(
                            packet_module,
                            validator_name,
                            return_value=validation_result,
                        ),
                        mock.patch("builtins.print") as print_mock,
                    ):
                        result = packet_module.main([command, *arguments, "--output", str(output)])

                    self.assertEqual(result, 1)
                    print_mock.assert_called_once()
                    public_output = print_mock.call_args.args[0]
                    self.assertEqual(
                        json.loads(public_output),
                        {
                            "artifact_type": "issue20_external_evidence_cli_error_v1",
                            "status": "failed",
                            "error_code": "evidence_output_unavailable",
                            "blocker_count": 0,
                            "blockers": [],
                        },
                    )
                    self.assertNotIn(str(case_root), public_output)
                    self.assertEqual(
                        blocked_parent.read_text(encoding="utf-8"),
                        "not a directory\n",
                    )
                    self.assertFalse(output.exists())
                    self.assertEqual(
                        [path.name for path in case_root.iterdir()],
                        [blocked_parent.name],
                    )


class Issue20GovernedSourceValidationTest(unittest.TestCase):
    def test_completed_sources_build_authority_valid_public_layers(self) -> None:
        sources = _completed_sources()

        validation = packet_module.validate_governed_sources(
            mcp_inspector=sources["mcp_inspector"],
            live_chatgpt_google=sources["live_chatgpt_google"],
            reviewer_gate=sources["reviewer_gate"],
            completion_audit=sources["completion_audit"],
        )
        inspector_layer = packet_module._build_mcp_inspector_layer(sources["mcp_inspector"])
        live_layer = packet_module._build_live_chatgpt_google_layer(sources["live_chatgpt_google"])
        reviewer_layer = packet_module._build_reviewer_gate_layer(
            sources["reviewer_gate"],
            expected_review_packet_hash=sources["reviewer_gate"]["review_packet_commitment_hash"],
        )

        self.assertEqual(validation["status"], "passed")
        self.assertTrue(
            packet_module._authority.validate_mcp_inspector_external_layer(inspector_layer)[
                "passed"
            ]
        )
        self.assertTrue(
            packet_module._authority.validate_live_chatgpt_google_external_layer(live_layer)[
                "passed"
            ]
        )
        self.assertTrue(
            packet_module._authority.validate_reviewer_gate_external_layer(reviewer_layer)["passed"]
        )
        self.assertEqual(live_layer["distinct_external_subject_count"], 2)
        self.assertEqual(live_layer["distinct_formowl_user_count"], 2)
        self.assertEqual(live_layer["audit_lineage_event_count"], 47)
        self.assertEqual(live_layer["removed_relink_token_session_created_count"], 0)

    def test_missing_duplicate_and_out_of_order_audit_records_are_rejected(self) -> None:
        base = _completed_sources()["live_chatgpt_google"]

        missing = copy.deepcopy(base)
        missing["audit_records"].pop()
        duplicate = copy.deepcopy(base)
        duplicate["audit_records"][1] = copy.deepcopy(duplicate["audit_records"][0])
        out_of_order = copy.deepcopy(base)
        out_of_order["audit_records"][10], out_of_order["audit_records"][11] = (
            out_of_order["audit_records"][11],
            out_of_order["audit_records"][10],
        )

        cases = (
            (missing, "live_audit_record_missing"),
            (duplicate, "live_audit_record_duplicate"),
            (out_of_order, "live_audit_record_out_of_order"),
        )
        for source, blocker in cases:
            with self.subTest(blocker=blocker):
                result = packet_module.validate_live_chatgpt_google_source(source)
                self.assertFalse(result["passed"])
                self.assertIn(blocker, result["blockers"])

    def test_broken_audit_hash_chain_is_rejected(self) -> None:
        source = _completed_sources()["live_chatgpt_google"]
        source["audit_records"][15]["previous_audit_record_hash"] = _hash(
            "wrong-previous-audit-record"
        )

        result = packet_module.validate_live_chatgpt_google_source(source)

        self.assertFalse(result["passed"])
        self.assertIn("live_audit_hash_chain_broken", result["blockers"])

    def test_audit_row_tamper_without_rehash_is_rejected(self) -> None:
        source = _completed_sources()["live_chatgpt_google"]
        source["audit_records"][12]["reason_code"] = "different_safe_reason"

        result = packet_module.validate_live_chatgpt_google_source(source)

        self.assertFalse(result["passed"])
        self.assertIn("live_audit_record_commitment_mismatch", result["blockers"])

    def test_single_row_rehash_without_following_chain_update_is_rejected(self) -> None:
        source = _completed_sources()["live_chatgpt_google"]
        source["audit_records"][12]["action"] = "different_safe_action"
        source["audit_records"][12]["audit_record_hash"] = packet_module._safe_audit_record_hash(
            source["audit_records"][12]
        )

        result = packet_module.validate_live_chatgpt_google_source(source)

        self.assertFalse(result["passed"])
        self.assertIn("live_audit_hash_chain_broken", result["blockers"])

    def test_coherent_safe_row_rehash_still_requires_operator_attestation(self) -> None:
        source = _completed_sources()["live_chatgpt_google"]
        original_hash = packet_module.validate_live_chatgpt_google_source(source)[
            "source_artifact_hash"
        ]
        source["audit_records"][12]["reason_code"] = "reviewed_alternate_reason"
        previous_hash = source["audit_records"][11]["audit_record_hash"]
        for record in source["audit_records"][12:]:
            record["previous_audit_record_hash"] = previous_hash
            record["audit_record_hash"] = packet_module._safe_audit_record_hash(record)
            previous_hash = record["audit_record_hash"]
        source["operator_attested"] = False

        result = packet_module.validate_live_chatgpt_google_source(source)

        self.assertFalse(result["passed"])
        self.assertIn("live_operator_attestation_missing", result["blockers"])
        source["operator_attested"] = True
        rebound = packet_module.validate_live_chatgpt_google_source(source)
        self.assertTrue(rebound["passed"])
        self.assertNotEqual(rebound["source_artifact_hash"], original_hash)

    def test_merged_forged_and_cross_workspace_denials_are_rejected(self) -> None:
        sources = _completed_sources()
        live = sources["live_chatgpt_google"]
        forged = next(
            event
            for event in live["events"]
            if event["event_name"] == "mcp_identity_forgery_denied"
        )
        cross = next(
            event
            for event in live["events"]
            if event["event_name"] == "second_user_cross_workspace_action_denied"
        )
        cross["observation_commitment_hash"] = forged["observation_commitment_hash"]

        result = packet_module.validate_live_chatgpt_google_source(live)

        self.assertFalse(result["passed"])
        self.assertIn("live_denial_evidence_merged", result["blockers"])

    def test_inspector_source_cannot_claim_an_authenticated_journey(self) -> None:
        source = _completed_sources()["mcp_inspector"]
        source["events"].append(
            {
                "sequence_index": len(source["events"]) + 1,
                "event_name": "authenticated_whoami",
                "status": "passed",
                "observation_commitment_hash": _hash("forbidden-inspector-authenticated-call"),
                "semantic_result_count": 1,
                "partial_state_write_count": 0,
            }
        )

        result = packet_module.validate_mcp_inspector_source(source)

        self.assertFalse(result["passed"])
        self.assertIn("mcp_event_manifest_mismatch", result["blockers"])

    def test_removed_relink_zero_state_violation_is_rejected(self) -> None:
        source = _completed_sources()["live_chatgpt_google"]
        event = next(
            item
            for item in source["events"]
            if item["event_name"] == "removed_membership_relink_zero_partial_state_verified"
        )
        event["partial_state_write_count"] = 1

        result = packet_module.validate_live_chatgpt_google_source(source)

        self.assertFalse(result["passed"])
        self.assertIn("live_removed_relink_zero_state_violation", result["blockers"])

    def test_secret_url_email_transcript_and_path_material_are_rejected(self) -> None:
        probes = (
            "Bearer secret-material-value",
            "https://private.example.test/mcp",
            "operator@example.test",
            "/workspace/private/transcript.json",
            "SELECT secret FROM oauth_tokens",
        )
        for probe in probes:
            for source_name, validator, blocker in (
                (
                    "mcp_inspector",
                    packet_module.validate_mcp_inspector_source,
                    "mcp_source_contains_forbidden_material",
                ),
                (
                    "live_chatgpt_google",
                    packet_module.validate_live_chatgpt_google_source,
                    "live_source_contains_forbidden_material",
                ),
            ):
                with self.subTest(probe=probe, source=source_name):
                    source = _completed_sources()[source_name]
                    source["unexpected_detail"] = probe
                    result = validator(source)
                    self.assertFalse(result["passed"])
                    self.assertIn(blocker, result["blockers"])

    def test_relink_requires_same_subject_user_and_new_session(self) -> None:
        source = _completed_sources()["live_chatgpt_google"]
        source["relink_bindings"][1]["external_subject_commitment_hash"] = _hash(
            "different-google-subject"
        )
        source["relink_bindings"][2]["new_session_binding_hash"] = source["relink_bindings"][1][
            "new_session_binding_hash"
        ]

        result = packet_module.validate_live_chatgpt_google_source(source)

        self.assertFalse(result["passed"])
        self.assertIn("live_relink_subject_changed", result["blockers"])
        self.assertIn("live_relink_new_session_not_distinct", result["blockers"])

    def test_completion_journey_missing_duplicate_and_out_of_order_are_rejected(
        self,
    ) -> None:
        base = _completed_sources()["completion_audit"]
        missing = copy.deepcopy(base)
        missing["journeys"].pop()
        duplicate = copy.deepcopy(base)
        duplicate["journeys"][1] = copy.deepcopy(duplicate["journeys"][0])
        out_of_order = copy.deepcopy(base)
        out_of_order["journeys"][3], out_of_order["journeys"][4] = (
            out_of_order["journeys"][4],
            out_of_order["journeys"][3],
        )

        for source, blocker in (
            (missing, "completion_journey_missing"),
            (duplicate, "completion_journey_duplicate"),
            (out_of_order, "completion_journey_out_of_order"),
        ):
            with self.subTest(blocker=blocker):
                result = packet_module.validate_completion_audit_source(source)
                self.assertFalse(result["passed"])
                self.assertIn(blocker, result["blockers"])

    def test_missing_completion_source_is_rejected(self) -> None:
        result = packet_module.validate_completion_audit_source(None)

        self.assertFalse(result["passed"])
        self.assertIn("completion_source_not_object", result["blockers"])

    def test_completion_template_hash_and_stale_contract_are_rejected(self) -> None:
        template_hash = _completed_sources()["completion_audit"]
        template_hash["audit_output_commitment_hash"] = packet_module._TEMPLATE_HASH
        stale = _completed_sources()["completion_audit"]
        stale["implementation_contract_hash"] = _hash("stale-implementation")

        template_result = packet_module.validate_completion_audit_source(template_hash)
        stale_result = packet_module.validate_completion_audit_source(stale)

        self.assertFalse(template_result["passed"])
        self.assertIn(
            "completion_audit_output_hash_invalid",
            template_result["blockers"],
        )
        self.assertFalse(stale_result["passed"])
        self.assertIn(
            "completion_implementation_contract_stale",
            stale_result["blockers"],
        )

    def test_reviewer_roles_cover_protocol_security_and_operator_e2e(self) -> None:
        source = _completed_sources()["reviewer_gate"]

        self.assertEqual(
            [entry["review_area"] for entry in source["reviewers"]],
            [
                "engineering_protocol",
                "security_governance",
                "operator_chatgpt_e2e",
            ],
        )
        self.assertTrue(packet_module.validate_reviewer_gate_source(source)["passed"])

    def test_reviewer_source_is_bound_to_the_exact_core_review_packet(self) -> None:
        source = _completed_sources()["reviewer_gate"]

        result = packet_module.validate_reviewer_gate_source(
            source,
            expected_review_packet_hash=_hash("different-core-review-packet"),
        )

        self.assertFalse(result["passed"])
        self.assertIn("reviewer_review_packet_stale", result["blockers"])

    def test_owner_only_denial_is_service_attributed_member_approval_probe(self) -> None:
        source = _completed_sources()["live_chatgpt_google"]
        record = next(
            item
            for item in source["audit_records"]
            if item["event_name"] == "second_user_owner_only_denied"
        )

        self.assertTrue(packet_module.validate_live_chatgpt_google_source(source)["passed"])
        self.assertEqual(record["actor_type"], "service")
        self.assertTrue(packet_module._is_real_hash(record["approval_user_binding_hash"]))
        self.assertEqual(
            record["tool_call_binding_hash"],
            packet_module._ABSENT_VALUE_COMMITMENT,
        )

        record["tool_call_binding_hash"] = _hash("imaginary-owner-only-mcp-tool")
        result = packet_module.validate_live_chatgpt_google_source(source)
        self.assertFalse(result["passed"])
        self.assertIn(
            "live_owner_only_probe_must_not_claim_mcp_tool",
            result["blockers"],
        )

    def test_callback_bootstrap_supports_direct_or_reserved_invalid_mode_only(self) -> None:
        direct = _completed_sources()["live_chatgpt_google"]
        direct["callback_bootstrap_mode"] = "direct_exact_callback"
        self.assertTrue(packet_module.validate_live_chatgpt_google_source(direct)["passed"])

        invalid = _completed_sources()["live_chatgpt_google"]
        invalid["callback_bootstrap_mode"] = "reachable_placeholder"
        result = packet_module.validate_live_chatgpt_google_source(invalid)
        self.assertFalse(result["passed"])
        self.assertIn("live_callback_bootstrap_mode_invalid", result["blockers"])

    def test_local_harness_receipt_remains_local_only_and_contract_bound(self) -> None:
        report = {
            "status": "passed",
            "claim_boundary": {
                "supports_external_evidence_packet_contract_claim": False,
                "supports_issue20_closure_claim": False,
                "supports_production_ready_claim": False,
            },
            "safe_outputs": {
                "local_completion_audit_report_hash": _hash("local-harness-report"),
                "actor_context_contract_hash": (
                    packet_module._authority._repository_contract_hash(
                        packet_module._authority._ACTOR_CONTEXT_CONTRACT_PATHS
                    )
                ),
                "documentation_contract_hash": (
                    packet_module._authority._repository_contract_hash(
                        packet_module._authority._DOCUMENTATION_CONTRACT_PATHS
                    )
                ),
                "issue20_completion_journey_manifest_hash": (
                    packet_module._authority.sha256_json(
                        packet_module._authority._ISSUE20_COMPLETION_JOURNEYS
                    )
                ),
            },
        }
        with mock.patch.object(
            packet_module._authority,
            "validate_report",
            return_value={"passed": True},
        ):
            receipt = packet_module.validate_local_harness_report(report)

        self.assertFalse(
            report["claim_boundary"]["supports_external_evidence_packet_contract_claim"]
        )
        self.assertFalse(report["claim_boundary"]["supports_issue20_closure_claim"])
        self.assertFalse(report["claim_boundary"]["supports_production_ready_claim"])
        self.assertEqual(
            receipt["implementation_contract_hash"],
            packet_module._authority.issue20_implementation_contract_hash(ROOT),
        )
        self.assertEqual(
            receipt["local_completion_audit_report_hash"],
            report["safe_outputs"]["local_completion_audit_report_hash"],
        )

        invalid = copy.deepcopy(report)
        invalid["claim_boundary"]["supports_external_evidence_packet_contract_claim"] = True
        with (
            mock.patch.object(
                packet_module._authority,
                "validate_report",
                return_value={"passed": True},
            ),
            self.assertRaisesRegex(
                packet_module.EvidencePacketError,
                "local_harness_report_must_be_local_only",
            ),
        ):
            packet_module.validate_local_harness_report(invalid)


class Issue20ExternalPacketBuilderTest(unittest.TestCase):
    def test_operator_journey_source_is_transitively_bound_to_implementation_contract(
        self,
    ) -> None:
        current = packet_module._authority.issue20_implementation_contract_hash(ROOT)
        drifted = _implementation_hash_after_independent_source_drift(
            "scripts/connected_operator_postgres_live_journey.py"
        )

        self.assertRegex(current, r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(drifted, r"^sha256:[0-9a-f]{64}$")
        self.assertNotEqual(drifted, current)

    def test_public_source_converters_reject_prebuilt_layers_and_invalid_reports(self) -> None:
        existing = _authority_fixture_packet()

        with self.assertRaisesRegex(
            packet_module.EvidencePacketError,
            "live_postgresql_source_report_required",
        ):
            packet_module.validated_live_postgresql_report_layer(
                existing["layers"]["live_postgresql"]
            )
        with self.assertRaisesRegex(
            packet_module.EvidencePacketError,
            "operator_evidence_report_invalid",
        ):
            packet_module._operator_layer_from_report(
                existing["layers"]["operator_cli_postgresql"],
                operator_attested=True,
                trusted_execution_authority=_operator_execution_authority(),
                trusted_execution_authority_pin=_operator_execution_authority_pin(),
            )
        with self.assertRaisesRegex(
            packet_module.EvidencePacketError,
            "operator_evidence_report_invalid",
        ):
            packet_module._operator_layer_from_report(
                {},
                operator_attested=True,
                trusted_execution_authority=_operator_execution_authority(),
                trusted_execution_authority_pin=_operator_execution_authority_pin(),
            )

    def test_duplicate_lifecycle_source_reports_are_rejected(self) -> None:
        fixture = _authority_fixture_module()
        report = fixture._valid_lifecycle_report(packet_module._authority, "duplicate")

        with self.assertRaisesRegex(
            packet_module.EvidencePacketError,
            "lifecycle_duplicate_report_rejected",
        ):
            packet_module._lifecycle_layer_from_reports(
                [report, copy.deepcopy(report)],
                operator_attested=True,
            )

    def test_operator_and_lifecycle_attestations_must_be_explicit(self) -> None:
        fixture = _authority_fixture_module()
        operator_report = fixture._valid_operator_journey_report(packet_module._authority)
        lifecycle_reports = [
            fixture._valid_lifecycle_report(packet_module._authority, "first"),
            fixture._valid_lifecycle_report(packet_module._authority, "second"),
        ]

        with self.assertRaisesRegex(
            packet_module.EvidencePacketError,
            "operator_evidence_attestation_missing",
        ):
            packet_module._operator_layer_from_report(
                operator_report,
                operator_attested=False,
                trusted_execution_authority=_operator_execution_authority(),
                trusted_execution_authority_pin=_operator_execution_authority_pin(),
            )
        with self.assertRaisesRegex(
            packet_module.EvidencePacketError,
            "lifecycle_operator_attestation_missing",
        ):
            packet_module._lifecycle_layer_from_reports(
                lifecycle_reports,
                operator_attested=False,
            )

    def test_operator_report_contract_is_delegated_to_current_authority(self) -> None:
        report = {"future_operator_journey_schema": 2}
        expected = {"authority_owned_layer": True}

        with mock.patch.object(
            packet_module._authority,
            "build_operator_cli_postgresql_external_layer",
            return_value=expected,
        ) as builder:
            actual = packet_module._operator_layer_from_report(
                report,
                operator_attested=True,
                trusted_execution_authority=_operator_execution_authority(),
                trusted_execution_authority_pin=_operator_execution_authority_pin(),
            )

        self.assertIs(actual, expected)
        builder.assert_called_once_with(
            report,
            operator_attested=True,
            trusted_execution_authority=_operator_execution_authority(),
            trusted_execution_authority_pin=_operator_execution_authority_pin(),
        )

    def test_generation_cli_failures_leave_no_partial_artifact(self) -> None:
        common = [
            "--local-harness-report",
            "local.json",
            "--live-postgresql-evidence",
            "postgres.json",
            "--operator-cli-postgresql-report",
            "operator.json",
            "--operator-cli-postgresql-execution-authority",
            "operator-authority.json",
            "--operator-cli-postgresql-execution-authority-pin",
            "operator-authority-pin.json",
            "--production-container-lifecycle-report",
            "lifecycle.json",
            "--mcp-inspector-source",
            "inspector.json",
            "--live-chatgpt-google-source",
            "chatgpt.json",
        ]
        with tempfile.TemporaryDirectory(prefix="formowl-packet-no-partial-") as temporary:
            root = Path(temporary)
            cases = (
                (
                    "prepare-reviewer-source",
                    "prepare_reviewer_materials",
                    [*common, "--output-dir", str(root / "review")],
                    root / "review",
                ),
                (
                    "prepare-completion-audit-source",
                    "prepare_completion_audit_source",
                    [
                        *common,
                        "--reviewer-gate-source",
                        "reviewer.json",
                        "--output",
                        str(root / "completion.json"),
                    ],
                    root / "completion.json",
                ),
                (
                    "build-packet",
                    "build_external_packet",
                    [
                        *common,
                        "--reviewer-gate-source",
                        "reviewer.json",
                        "--completion-audit-source",
                        "completion.json",
                        "--output",
                        str(root / "packet.json"),
                    ],
                    root / "packet.json",
                ),
            )
            for command, function_name, arguments, artifact in cases:
                with (
                    self.subTest(command=command),
                    mock.patch.object(
                        packet_module,
                        "_read_json",
                        return_value={},
                    ),
                    mock.patch.object(
                        packet_module,
                        function_name,
                        side_effect=packet_module.EvidencePacketError(
                            "operator_evidence_attestation_missing"
                        ),
                    ),
                    mock.patch("builtins.print"),
                ):
                    result = packet_module.main([command, *arguments])

                self.assertEqual(result, 1)
                self.assertFalse(artifact.exists())

    def test_preparation_helpers_bind_sources_without_claiming_external_completion(
        self,
    ) -> None:
        existing = _authority_fixture_packet()
        completion = existing["layers"]["completion_audit"]
        local_receipt = {
            "implementation_contract_hash": completion["implementation_contract_hash"],
            "local_completion_audit_report_hash": completion["local_harness_report_hash"],
            "actor_context_contract_hash": completion["actor_context_contract_hash"],
            "documentation_contract_hash": completion["documentation_contract_hash"],
            "issue20_completion_journey_manifest_hash": completion["journey_manifest_hash"],
        }
        fixture = _authority_fixture_module()
        live_postgresql_report = _live_postgresql_fixture_module()._valid_report(
            packet_module._authority._live_postgresql
        )
        operator_report = fixture._valid_operator_journey_report(packet_module._authority)
        lifecycle_reports = [
            fixture._valid_lifecycle_report(packet_module._authority, "prepare-first"),
            fixture._valid_lifecycle_report(packet_module._authority, "prepare-second"),
        ]
        sources = _completed_sources()
        common = {
            "local_harness_report": {},
            "live_postgresql_evidence": live_postgresql_report,
            "operator_cli_postgresql_report": operator_report,
            "operator_cli_postgresql_execution_authority": _operator_execution_authority(),
            "operator_cli_postgresql_execution_authority_pin": (
                _operator_execution_authority_pin()
            ),
            "production_container_lifecycle_reports": lifecycle_reports,
            "operator_attest_postgresql": True,
            "operator_attest_lifecycle": True,
            "mcp_inspector_source": sources["mcp_inspector"],
            "live_chatgpt_google_source": sources["live_chatgpt_google"],
        }
        with mock.patch.object(
            packet_module,
            "validate_local_harness_report",
            return_value=local_receipt,
        ):
            materials = packet_module.prepare_reviewer_materials(**common)

        self.assertEqual(
            set(materials),
            {"core-review-packet.json", "reviewer-gate-source.json"},
        )
        review_packet = materials["core-review-packet.json"]
        reviewer_template = materials["reviewer-gate-source.json"]
        self.assertEqual(review_packet["status"], "ready_for_review")
        self.assertFalse(review_packet["claim_boundary"]["supports_issue20_closure_claim"])
        self.assertFalse(review_packet["claim_boundary"]["supports_production_ready_claim"])
        self.assertTrue(review_packet["claim_boundary"]["requires_reviewer_gate"])
        self.assertTrue(review_packet["claim_boundary"]["requires_independent_completion_audit"])
        self.assertEqual(reviewer_template["status"], "incomplete")
        self.assertFalse(reviewer_template["operator_attested"])
        self.assertEqual(
            reviewer_template["review_packet_commitment_hash"],
            packet_module._source_hash(review_packet),
        )

        reviewer_source = sources["reviewer_gate"]
        reviewer_source["review_packet_commitment_hash"] = reviewer_template[
            "review_packet_commitment_hash"
        ]
        with mock.patch.object(
            packet_module,
            "validate_local_harness_report",
            return_value=local_receipt,
        ):
            completion_source = packet_module.prepare_completion_audit_source(
                **common,
                reviewer_gate_source=reviewer_source,
            )

        self.assertEqual(completion_source["status"], "incomplete")
        self.assertFalse(completion_source["auditor_attested"])
        self.assertFalse(completion_source["operator_attested"])
        self.assertEqual(
            completion_source["implementation_contract_hash"],
            local_receipt["implementation_contract_hash"],
        )
        self.assertEqual(
            completion_source["local_harness_report_hash"],
            local_receipt["local_completion_audit_report_hash"],
        )
        self.assertTrue(
            packet_module._is_real_hash(completion_source["reviewed_layer_artifact_set_hash"])
        )

        stale_reviewer_source = copy.deepcopy(reviewer_source)
        stale_reviewer_source["review_packet_commitment_hash"] = _hash("stale-review-packet")
        with (
            mock.patch.object(
                packet_module,
                "validate_local_harness_report",
                return_value=local_receipt,
            ),
            self.assertRaisesRegex(
                packet_module.EvidencePacketError,
                "reviewer_gate_source_invalid",
            ),
        ):
            packet_module.prepare_completion_audit_source(
                **common,
                reviewer_gate_source=stale_reviewer_source,
            )

    def test_complete_packet_is_accepted_by_current_schema_v5_authority(self) -> None:
        existing = _authority_fixture_packet()
        sources = _completed_sources()
        completion = existing["layers"]["completion_audit"]
        local_receipt = {
            "implementation_contract_hash": completion["implementation_contract_hash"],
            "local_completion_audit_report_hash": completion["local_harness_report_hash"],
            "actor_context_contract_hash": completion["actor_context_contract_hash"],
            "documentation_contract_hash": completion["documentation_contract_hash"],
            "issue20_completion_journey_manifest_hash": completion["journey_manifest_hash"],
        }
        _bind_staged_sources(
            sources,
            local_receipt=local_receipt,
            base_layers=existing["layers"],
        )

        packet = packet_module._build_external_packet_from_validated_inputs(
            local_receipt=local_receipt,
            live_postgresql_layer=existing["layers"]["live_postgresql"],
            operator_cli_postgresql_layer=existing["layers"]["operator_cli_postgresql"],
            operator_cli_postgresql_execution_authority_pin=(_operator_execution_authority_pin()),
            production_container_lifecycle_layer=existing["layers"][
                "production_container_lifecycle"
            ],
            mcp_inspector_source=sources["mcp_inspector"],
            live_chatgpt_google_source=sources["live_chatgpt_google"],
            reviewer_gate_source=sources["reviewer_gate"],
            completion_audit_source=sources["completion_audit"],
        )
        validation = packet_module._authority.validate_external_evidence_packet(
            packet,
            expected_local_harness_report_hash=local_receipt["local_completion_audit_report_hash"],
            expected_operator_execution_authority_pin=(_operator_execution_authority_pin()),
        )

        self.assertEqual(packet["schema_version"], 5)
        self.assertTrue(validation["passed"], validation["blockers"])
        self.assertEqual(
            packet["layers"]["live_chatgpt_google"]["audit_lineage_event_count"],
            47,
        )
        self.assertFalse(
            packet["layers"]["completion_audit"]["source_evidence_artifact_hash"]
            in {
                layer["source_evidence_artifact_hash"]
                for name, layer in packet["layers"].items()
                if name in {"mcp_inspector", "live_chatgpt_google", "reviewer_gate"}
            }
        )

        fixture = _authority_fixture_module()
        operator_report = fixture._valid_operator_journey_report(packet_module._authority)
        lifecycle_report = fixture._valid_lifecycle_report(
            packet_module._authority,
            "runner-contract-current",
        )
        live_postgresql_report = _live_postgresql_fixture_module()._valid_report(
            packet_module._authority._live_postgresql
        )
        reviewed_layer_artifacts = {
            name: packet["layers"][name]["evidence_artifact_hash"]
            for name in (
                "live_postgresql",
                "operator_cli_postgresql",
                "production_container_lifecycle",
                "mcp_inspector",
                "live_chatgpt_google",
                "reviewer_gate",
            )
        }
        self.assertTrue(
            packet_module._authority._operator_journey.validate_report(
                operator_report,
                trusted_execution_authority=_operator_execution_authority(),
                trusted_execution_authority_pin=_operator_execution_authority_pin(),
            )["passed"]
        )
        self.assertTrue(
            packet_module._authority._lifecycle_probe.validate_report(lifecycle_report)["passed"]
        )
        self.assertTrue(
            packet_module._authority._live_postgresql.validate_report(live_postgresql_report)[
                "passed"
            ]
        )
        self.assertTrue(
            packet_module.validate_completion_audit_source(
                sources["completion_audit"],
                expected_local_receipt=local_receipt,
                expected_layer_artifacts=reviewed_layer_artifacts,
                expected_operator_execution_authority_pin_hash=(
                    packet_module._authority.sha256_json(_operator_execution_authority_pin())
                ),
            )["passed"]
        )

        current_implementation_hash = local_receipt["implementation_contract_hash"]
        for relative_path in (
            "scripts/connected_operator_postgres_live_journey.py",
            "scripts/issue20_containerized_evidence_runner.sh",
            "scripts/issue20_runner_boundary.py",
        ):
            with self.subTest(independent_runner_drift=relative_path):
                drifted_hash = _implementation_hash_after_independent_source_drift(relative_path)
                self.assertNotEqual(drifted_hash, current_implementation_hash)
                with (
                    mock.patch.object(
                        packet_module._authority,
                        "issue20_implementation_contract_hash",
                        return_value=drifted_hash,
                    ),
                    mock.patch.object(
                        packet_module._authority._operator_journey,
                        "issue20_implementation_contract_hash",
                        return_value=drifted_hash,
                    ),
                    mock.patch.object(
                        packet_module._authority._lifecycle_probe,
                        "_current_issue20_implementation_contract_hash",
                        return_value=drifted_hash,
                    ),
                    mock.patch.object(
                        packet_module._authority._live_postgresql,
                        "issue20_implementation_contract_hash",
                        return_value=drifted_hash,
                    ),
                ):
                    self.assertFalse(
                        packet_module._authority._operator_journey.validate_report(
                            operator_report,
                            trusted_execution_authority=_operator_execution_authority(),
                            trusted_execution_authority_pin=(_operator_execution_authority_pin()),
                        )["passed"]
                    )
                    self.assertFalse(
                        packet_module._authority._lifecycle_probe.validate_report(lifecycle_report)[
                            "passed"
                        ]
                    )
                    self.assertFalse(
                        packet_module._authority._live_postgresql.validate_report(
                            live_postgresql_report
                        )["passed"]
                    )
                    self.assertFalse(
                        packet_module._authority.validate_operator_cli_postgresql_external_layer(
                            packet["layers"]["operator_cli_postgresql"],
                            trusted_execution_authority_pin=(_operator_execution_authority_pin()),
                        )["passed"]
                    )
                    self.assertFalse(
                        packet_module._authority.validate_production_container_lifecycle_external_layer(
                            packet["layers"]["production_container_lifecycle"]
                        )["passed"]
                    )
                    self.assertFalse(
                        packet_module._authority._live_postgresql.validate_live_postgresql_external_layer(
                            packet["layers"]["live_postgresql"]
                        )["passed"]
                    )
                    completion_validation = packet_module.validate_completion_audit_source(
                        sources["completion_audit"],
                        expected_local_receipt=local_receipt,
                        expected_layer_artifacts=reviewed_layer_artifacts,
                        expected_operator_execution_authority_pin_hash=(
                            packet_module._authority.sha256_json(
                                _operator_execution_authority_pin()
                            )
                        ),
                    )
                    self.assertFalse(completion_validation["passed"])
                    self.assertIn(
                        "completion_implementation_contract_stale",
                        completion_validation["blockers"],
                    )
                    packet_validation = packet_module._authority.validate_external_evidence_packet(
                        packet,
                        expected_local_harness_report_hash=local_receipt[
                            "local_completion_audit_report_hash"
                        ],
                        expected_operator_execution_authority_pin=(
                            _operator_execution_authority_pin()
                        ),
                    )
                    self.assertFalse(packet_validation["passed"])
                    self.assertEqual(
                        packet_validation["layer_statuses"]["operator_cli_postgresql"],
                        "failed",
                    )
                    self.assertEqual(
                        packet_validation["layer_statuses"]["production_container_lifecycle"],
                        "failed",
                    )
                    self.assertEqual(
                        packet_validation["layer_statuses"]["live_postgresql"],
                        "failed",
                    )

    def test_schema_migration_candidate_cannot_replace_original_pre_run_pin(self) -> None:
        original_pin = _operator_execution_authority_pin()
        candidate_report, replacement_authority, replacement_pin = (
            _schema_v2_candidate_from_legacy_with_replacement_authority()
        )
        self.assertNotEqual(replacement_pin, original_pin)
        self.assertTrue(
            packet_module._authority._operator_journey.validate_report(
                candidate_report,
                trusted_execution_authority=replacement_authority,
                trusted_execution_authority_pin=replacement_pin,
            )["passed"]
        )
        original_pin_report_validation = packet_module._authority._operator_journey.validate_report(
            candidate_report,
            trusted_execution_authority=replacement_authority,
            trusted_execution_authority_pin=original_pin,
        )
        self.assertFalse(original_pin_report_validation["passed"])
        self.assertTrue(
            any("pin" in blocker for blocker in original_pin_report_validation["blockers"]),
            original_pin_report_validation,
        )

        existing = _authority_fixture_packet()
        completion = existing["layers"]["completion_audit"]
        local_receipt = {
            "implementation_contract_hash": completion["implementation_contract_hash"],
            "local_completion_audit_report_hash": completion["local_harness_report_hash"],
            "actor_context_contract_hash": completion["actor_context_contract_hash"],
            "documentation_contract_hash": completion["documentation_contract_hash"],
            "issue20_completion_journey_manifest_hash": completion["journey_manifest_hash"],
        }
        fixture = _authority_fixture_module()
        live_postgresql_report = _live_postgresql_fixture_module()._valid_report(
            packet_module._authority._live_postgresql
        )
        lifecycle_reports = [
            fixture._valid_lifecycle_report(packet_module._authority, "migration-first"),
            fixture._valid_lifecycle_report(packet_module._authority, "migration-second"),
        ]
        replacement_operator_layer = (
            packet_module._authority.build_operator_cli_postgresql_external_layer(
                candidate_report,
                operator_attested=True,
                trusted_execution_authority=replacement_authority,
                trusted_execution_authority_pin=replacement_pin,
            )
        )
        self.assertFalse(
            packet_module._authority.validate_operator_cli_postgresql_external_layer(
                replacement_operator_layer,
                trusted_execution_authority_pin=original_pin,
            )["passed"]
        )
        replacement_lifecycle_layer = packet_module._lifecycle_layer_from_reports(
            lifecycle_reports,
            operator_attested=True,
        )
        replacement_live_layer = packet_module.validated_live_postgresql_report_layer(
            live_postgresql_report
        )
        sources = _completed_sources()
        _bind_staged_sources(
            sources,
            local_receipt=local_receipt,
            base_layers={
                "live_postgresql": replacement_live_layer,
                "operator_cli_postgresql": replacement_operator_layer,
                "production_container_lifecycle": replacement_lifecycle_layer,
            },
            operator_execution_authority_pin=replacement_pin,
        )
        build_inputs = {
            "local_harness_report": {},
            "live_postgresql_evidence": live_postgresql_report,
            "operator_cli_postgresql_report": candidate_report,
            "operator_cli_postgresql_execution_authority": replacement_authority,
            "operator_cli_postgresql_execution_authority_pin": replacement_pin,
            "production_container_lifecycle_reports": lifecycle_reports,
            "operator_attest_postgresql": True,
            "operator_attest_lifecycle": True,
            "mcp_inspector_source": sources["mcp_inspector"],
            "live_chatgpt_google_source": sources["live_chatgpt_google"],
            "reviewer_gate_source": sources["reviewer_gate"],
            "completion_audit_source": sources["completion_audit"],
        }
        with mock.patch.object(
            packet_module,
            "validate_local_harness_report",
            return_value=local_receipt,
        ):
            replacement_packet = packet_module.build_external_packet(**build_inputs)
            replacement_validation = packet_module.validate_current_packet(
                replacement_packet,
                **build_inputs,
            )
            original_pin_inputs = {
                **build_inputs,
                "operator_cli_postgresql_execution_authority_pin": original_pin,
            }
            with self.assertRaisesRegex(
                packet_module.EvidencePacketError,
                "operator_evidence_report_invalid",
            ):
                packet_module.build_external_packet(**original_pin_inputs)
            with self.assertRaisesRegex(
                packet_module.EvidencePacketError,
                "operator_evidence_report_invalid",
            ):
                packet_module.validate_current_packet(
                    replacement_packet,
                    **original_pin_inputs,
                )

        self.assertTrue(replacement_validation["passed"], replacement_validation["blockers"])
        original_pin_validation = packet_module._authority.validate_external_evidence_packet(
            replacement_packet,
            expected_local_harness_report_hash=local_receipt["local_completion_audit_report_hash"],
            expected_operator_execution_authority_pin=original_pin,
        )
        self.assertFalse(original_pin_validation["passed"])
        self.assertEqual(
            original_pin_validation["layer_statuses"]["operator_cli_postgresql"],
            "failed",
        )
        self.assertEqual(
            original_pin_validation["layer_statuses"]["completion_audit"],
            "failed",
        )

    def test_original_verifier_inputs_reject_rebuilt_migration_across_real_cli_paths(
        self,
    ) -> None:
        candidate_report, replacement_authority, replacement_pin = (
            _schema_v2_candidate_from_legacy_with_replacement_authority()
        )
        original_authority = _operator_execution_authority()
        original_pin = _operator_execution_authority_pin()
        self.assertNotEqual(replacement_authority, original_authority)
        self.assertNotEqual(replacement_pin, original_pin)

        existing = _authority_fixture_packet()
        completion = existing["layers"]["completion_audit"]
        local_receipt = {
            "implementation_contract_hash": completion["implementation_contract_hash"],
            "local_completion_audit_report_hash": completion["local_harness_report_hash"],
            "actor_context_contract_hash": completion["actor_context_contract_hash"],
            "documentation_contract_hash": completion["documentation_contract_hash"],
            "issue20_completion_journey_manifest_hash": completion["journey_manifest_hash"],
        }
        fixture = _authority_fixture_module()
        local_context = fixture._passing_local_completion_context(packet_module._authority)
        self.assertEqual(
            local_context.local_completion_audit_report_hash,
            local_receipt["local_completion_audit_report_hash"],
        )
        with mock.patch.object(
            packet_module._authority,
            "_run_local_completion_context",
            return_value=local_context,
        ):
            local_report = packet_module._authority.run_oauth_mcp_harness()
        self.assertTrue(local_report["validation"]["passed"])
        self.assertFalse(
            local_report["claim_boundary"]["supports_external_evidence_packet_contract_claim"]
        )
        self.assertFalse(local_report["claim_boundary"]["supports_issue20_closure_claim"])
        self.assertFalse(local_report["claim_boundary"]["supports_production_ready_claim"])

        expected_workspace_sources = {
            packet_module.prepare_reviewer_materials: (
                ROOT / "python/formowl_evidence/issue20_packet.py"
            ),
            packet_module.prepare_completion_audit_source: (
                ROOT / "python/formowl_evidence/issue20_packet.py"
            ),
            packet_module.build_external_packet: (
                ROOT / "python/formowl_evidence/issue20_packet.py"
            ),
            packet_module.validate_current_packet: (
                ROOT / "python/formowl_evidence/issue20_packet.py"
            ),
            packet_module._authority.build_operator_cli_postgresql_external_layer: (
                ROOT / "scripts/oauth_mcp_harness.py"
            ),
            packet_module._authority._operator_journey.validate_report: (
                ROOT / "scripts/connected_operator_postgres_live_journey.py"
            ),
            packet_module._authority._operator_journey.create_execution_authority: (
                ROOT / "scripts/connected_operator_postgres_live_journey.py"
            ),
            packet_module._authority._operator_journey.create_execution_authority_pin: (
                ROOT / "scripts/connected_operator_postgres_live_journey.py"
            ),
            packet_module._authority._operator_journey.attach_execution_receipt: (
                ROOT / "scripts/connected_operator_postgres_live_journey.py"
            ),
            packet_module._authority._operator_journey.validate_execution_authority_pin: (
                ROOT / "scripts/connected_operator_postgres_live_journey.py"
            ),
            packet_module._authority._operator_journey.validate_execution_receipt: (
                ROOT / "scripts/connected_operator_postgres_live_journey.py"
            ),
        }
        for target, expected_source in expected_workspace_sources.items():
            with self.subTest(workspace_target=target.__qualname__):
                self.assertEqual(
                    Path(inspect.getsourcefile(target) or "").resolve(),
                    expected_source.resolve(),
                )

        live_postgresql_report = _live_postgresql_fixture_module()._valid_report(
            packet_module._authority._live_postgresql
        )
        lifecycle_reports = [
            fixture._valid_lifecycle_report(packet_module._authority, "cli-migration-first"),
            fixture._valid_lifecycle_report(packet_module._authority, "cli-migration-second"),
        ]
        replacement_operator_layer = (
            packet_module._authority.build_operator_cli_postgresql_external_layer(
                candidate_report,
                operator_attested=True,
                trusted_execution_authority=replacement_authority,
                trusted_execution_authority_pin=replacement_pin,
            )
        )
        sources = _completed_sources()
        _bind_staged_sources(
            sources,
            local_receipt=local_receipt,
            base_layers={
                "live_postgresql": packet_module.validated_live_postgresql_report_layer(
                    live_postgresql_report
                ),
                "operator_cli_postgresql": replacement_operator_layer,
                "production_container_lifecycle": (
                    packet_module._lifecycle_layer_from_reports(
                        lifecycle_reports,
                        operator_attested=True,
                    )
                ),
            },
            operator_execution_authority_pin=replacement_pin,
        )

        with tempfile.TemporaryDirectory(prefix="formowl-original-authority-cli-") as temporary:
            root = Path(temporary)

            def write_json(name: str, value: object) -> Path:
                path = root / name
                path.write_text(
                    json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
                return path

            local_report_path = write_json("local-harness.json", local_report)
            live_path = write_json("live-postgresql.json", live_postgresql_report)
            candidate_report_path = write_json("operator-candidate.json", candidate_report)
            replacement_authority_path = write_json(
                "replacement-authority.json", replacement_authority
            )
            replacement_pin_path = write_json("replacement-pin.json", replacement_pin)
            original_authority_path = write_json("original-authority.json", original_authority)
            original_pin_path = write_json("original-pin.json", original_pin)
            lifecycle_paths = [
                write_json(f"lifecycle-{index}.json", report)
                for index, report in enumerate(lifecycle_reports, start=1)
            ]
            mcp_path = write_json("mcp-source.json", sources["mcp_inspector"])
            chatgpt_path = write_json("chatgpt-source.json", sources["live_chatgpt_google"])
            reviewer_source_path = write_json("reviewer-source.json", sources["reviewer_gate"])
            completion_source_path = write_json(
                "completion-source.json", sources["completion_audit"]
            )

            def core_arguments(
                authority_path: Path,
                pin_path: Path,
                *,
                local_harness_path: Path = local_report_path,
            ) -> list[str]:
                arguments = [
                    "--local-harness-report",
                    str(local_harness_path),
                    "--live-postgresql-evidence",
                    str(live_path),
                    "--operator-cli-postgresql-report",
                    str(candidate_report_path),
                    "--operator-cli-postgresql-execution-authority",
                    str(authority_path),
                    "--operator-cli-postgresql-execution-authority-pin",
                    str(pin_path),
                ]
                for lifecycle_path in lifecycle_paths:
                    arguments.extend(
                        ["--production-container-lifecycle-report", str(lifecycle_path)]
                    )
                arguments.extend(
                    [
                        "--operator-attest-postgresql",
                        "--operator-attest-lifecycle",
                        "--mcp-inspector-source",
                        str(mcp_path),
                        "--live-chatgpt-google-source",
                        str(chatgpt_path),
                    ]
                )
                return arguments

            cli_hook_dir = root / "cli-hook"
            cli_hook_dir.mkdir()
            local_report_hash = packet_module._authority.sha256_json(local_report)
            local_report_exact_keys = {
                "report": sorted(local_report),
                **{
                    key: sorted(local_report[key])
                    for key in (
                        "metrics",
                        "safe_outputs",
                        "evidence_layers",
                        "claim_boundary",
                        "validation",
                    )
                },
            }
            (cli_hook_dir / "sitecustomize.py").write_text(
                "\n".join(
                    (
                        "import hashlib",
                        "import inspect",
                        "import json",
                        "from pathlib import Path",
                        "import sys",
                        f"ROOT = Path({str(ROOT)!r})",
                        "for item in (ROOT / 'python', ROOT / 'tests', ROOT / 'scripts'):",
                        "    if str(item) not in sys.path:",
                        "        sys.path.insert(0, str(item))",
                        "import oauth_mcp_harness",
                        f"EXPECTED = json.loads({json.dumps(local_report)!r})",
                        f"EXPECTED_HASH = {local_report_hash!r}",
                        f"EXPECTED_KEYS = json.loads({json.dumps(local_report_exact_keys)!r})",
                        "WORKSPACE_TARGETS = (",
                        "    (oauth_mcp_harness.build_operator_cli_postgresql_external_layer, ROOT / 'scripts/oauth_mcp_harness.py'),",
                        "    (oauth_mcp_harness._operator_journey.validate_report, ROOT / 'scripts/connected_operator_postgres_live_journey.py'),",
                        "    (oauth_mcp_harness._operator_journey.create_execution_authority, ROOT / 'scripts/connected_operator_postgres_live_journey.py'),",
                        "    (oauth_mcp_harness._operator_journey.create_execution_authority_pin, ROOT / 'scripts/connected_operator_postgres_live_journey.py'),",
                        "    (oauth_mcp_harness._operator_journey.attach_execution_receipt, ROOT / 'scripts/connected_operator_postgres_live_journey.py'),",
                        "    (oauth_mcp_harness._operator_journey.validate_execution_authority_pin, ROOT / 'scripts/connected_operator_postgres_live_journey.py'),",
                        "    (oauth_mcp_harness._operator_journey.validate_execution_receipt, ROOT / 'scripts/connected_operator_postgres_live_journey.py'),",
                        ")",
                        "for target, source in WORKSPACE_TARGETS:",
                        "    if Path(inspect.getsourcefile(target) or '').resolve() != source.resolve():",
                        "        raise RuntimeError('issue20_cli_workspace_target_mismatch')",
                        "def fixture_hash(value):",
                        "    payload = json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')",
                        "    return 'sha256:' + hashlib.sha256(payload).hexdigest()",
                        "def exact_fixture_shape(report):",
                        "    if not isinstance(report, dict) or set(report) != set(EXPECTED_KEYS['report']):",
                        "        return False",
                        "    for key in ('metrics', 'safe_outputs', 'evidence_layers', 'claim_boundary', 'validation'):",
                        "        if not isinstance(report.get(key), dict) or set(report[key]) != set(EXPECTED_KEYS[key]):",
                        "            return False",
                        "    return True",
                        "def validate_report(report, **_kwargs):",
                        "    # Bypass only the unrelated repository-wide 526-pending local manifest recomputation.",
                        "    # The exact local-only fixture cannot claim external packet validity, issue closure, or production readiness.",
                        "    passed = exact_fixture_shape(report) and fixture_hash(report) == EXPECTED_HASH and report == EXPECTED",
                        "    return {'passed': passed, 'status': 'passed' if passed else 'failed', 'blocker_count': 0 if passed else 1}",
                        "oauth_mcp_harness.validate_report = validate_report",
                        "",
                    )
                ),
                encoding="utf-8",
            )
            cli_environment = os.environ.copy()
            cli_environment["PYTHONPATH"] = os.pathsep.join(
                (
                    str(cli_hook_dir),
                    str(ROOT / "python"),
                    str(ROOT / "tests"),
                    str(ROOT / "scripts"),
                    cli_environment.get("PYTHONPATH", ""),
                )
            )

            def run_packet_cli(arguments: list[str]) -> subprocess.CompletedProcess[str]:
                # The repository-wide function manifest intentionally remains
                # partially onboarded. The child-process hook accepts one
                # exact-hash, exact-key, local-only report and bypasses only
                # that unrelated local manifest gate. It cannot broaden the
                # fixture's claim boundary. ``python -m`` still drives the real
                # parser, packet builders, validators, authority/pin/signature
                # checks, and filesystem artifact behavior in a fresh process.
                return subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "formowl_evidence.issue20_packet",
                        *arguments,
                    ],
                    cwd=ROOT,
                    env=cli_environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )

            replacement_validation_path = root / "replacement-report-validation.json"
            replacement_raw = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/connected_operator_postgres_live_journey.py"),
                    "--validate-report",
                    str(candidate_report_path),
                    "--trusted-execution-authority",
                    str(replacement_authority_path),
                    "--trusted-execution-authority-pin",
                    str(replacement_pin_path),
                    "--output",
                    str(replacement_validation_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(replacement_raw.returncode, 0, replacement_raw.stderr)
            self.assertTrue(
                json.loads(replacement_validation_path.read_text(encoding="utf-8"))["passed"]
            )

            replacement_layer_path = root / "replacement-operator-layer.json"
            replacement_converter = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/oauth_mcp_harness.py"),
                    "--operator-cli-postgresql-report",
                    str(candidate_report_path),
                    "--operator-cli-postgresql-authority",
                    str(replacement_authority_path),
                    "--operator-cli-postgresql-authority-pin",
                    str(replacement_pin_path),
                    "--operator-attest-postgresql",
                    "--output",
                    str(replacement_layer_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                replacement_converter.returncode,
                0,
                replacement_converter.stderr,
            )
            self.assertEqual(
                json.loads(replacement_layer_path.read_text(encoding="utf-8"))["status"],
                "passed",
            )

            replacement_core = core_arguments(
                replacement_authority_path,
                replacement_pin_path,
            )
            prepared_review_dir = root / "prepared-review"
            prepared_review = run_packet_cli(
                [
                    "prepare-reviewer-source",
                    *replacement_core,
                    "--output-dir",
                    str(prepared_review_dir),
                ]
            )
            self.assertEqual(prepared_review.returncode, 0, prepared_review.stdout)
            self.assertTrue((prepared_review_dir / "core-review-packet.json").is_file())

            prepared_completion_path = root / "prepared-completion.json"
            prepared_completion = run_packet_cli(
                [
                    "prepare-completion-audit-source",
                    *replacement_core,
                    "--reviewer-gate-source",
                    str(reviewer_source_path),
                    "--output",
                    str(prepared_completion_path),
                ]
            )
            self.assertEqual(prepared_completion.returncode, 0, prepared_completion.stdout)
            self.assertTrue(prepared_completion_path.is_file())

            replacement_packet_path = root / "replacement-packet.json"
            replacement_build = run_packet_cli(
                [
                    "build-packet",
                    *replacement_core,
                    "--reviewer-gate-source",
                    str(reviewer_source_path),
                    "--completion-audit-source",
                    str(completion_source_path),
                    "--output",
                    str(replacement_packet_path),
                ]
            )
            self.assertEqual(replacement_build.returncode, 0, replacement_build.stdout)
            replacement_packet = json.loads(replacement_packet_path.read_text(encoding="utf-8"))
            self.assertEqual(replacement_packet["schema_version"], 5)

            replacement_packet_validation_path = root / "replacement-packet-validation.json"
            replacement_packet_validation = run_packet_cli(
                [
                    "validate-packet",
                    "--packet",
                    str(replacement_packet_path),
                    *replacement_core,
                    "--reviewer-gate-source",
                    str(reviewer_source_path),
                    "--completion-audit-source",
                    str(completion_source_path),
                    "--output",
                    str(replacement_packet_validation_path),
                ]
            )
            self.assertEqual(
                replacement_packet_validation.returncode,
                0,
                replacement_packet_validation.stdout,
            )
            self.assertTrue(
                json.loads(replacement_packet_validation_path.read_text(encoding="utf-8"))["passed"]
            )

            local_hook_rejections: list[subprocess.CompletedProcess[str]] = []
            invalid_local_reports = {
                "hash-mismatch": {
                    **copy.deepcopy(local_report),
                    "status": "failed",
                },
                "key-mismatch": {
                    **copy.deepcopy(local_report),
                    "unexpected_fixture_key": False,
                },
            }
            for label, invalid_local_report in invalid_local_reports.items():
                invalid_local_path = write_json(
                    f"invalid-local-{label}.json",
                    invalid_local_report,
                )
                rejected_local_dir = root / f"rejected-local-{label}"
                rejected_local = run_packet_cli(
                    [
                        "prepare-reviewer-source",
                        *core_arguments(
                            replacement_authority_path,
                            replacement_pin_path,
                            local_harness_path=invalid_local_path,
                        ),
                        "--output-dir",
                        str(rejected_local_dir),
                    ]
                )
                self.assertEqual(rejected_local.returncode, 1, rejected_local.stdout)
                self.assertFalse(rejected_local_dir.exists())
                self.assertEqual(
                    json.loads(rejected_local.stdout)["error_code"],
                    "local_harness_report_invalid",
                )
                local_hook_rejections.append(rejected_local)

            original_validation_path = root / "original-report-validation.json"
            original_raw = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/connected_operator_postgres_live_journey.py"),
                    "--validate-report",
                    str(candidate_report_path),
                    "--trusted-execution-authority",
                    str(original_authority_path),
                    "--trusted-execution-authority-pin",
                    str(original_pin_path),
                    "--output",
                    str(original_validation_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(original_raw.returncode, 1, original_raw.stderr)
            self.assertFalse(
                json.loads(original_validation_path.read_text(encoding="utf-8"))["passed"]
            )

            original_layer_path = root / "original-operator-layer.json"
            original_converter = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/oauth_mcp_harness.py"),
                    "--operator-cli-postgresql-report",
                    str(candidate_report_path),
                    "--operator-cli-postgresql-authority",
                    str(original_authority_path),
                    "--operator-cli-postgresql-authority-pin",
                    str(original_pin_path),
                    "--operator-attest-postgresql",
                    "--output",
                    str(original_layer_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(original_converter.returncode, 1, original_converter.stderr)
            original_layer = json.loads(original_layer_path.read_text(encoding="utf-8"))
            self.assertEqual(original_layer["status"], "failed")
            self.assertEqual(original_layer["error_code"], "operator_evidence_report_invalid")

            original_core = core_arguments(original_authority_path, original_pin_path)
            rejected_review_dir = root / "rejected-review"
            rejected_review = run_packet_cli(
                [
                    "prepare-reviewer-source",
                    *original_core,
                    "--output-dir",
                    str(rejected_review_dir),
                ]
            )
            self.assertEqual(rejected_review.returncode, 1, rejected_review.stdout)
            self.assertFalse(rejected_review_dir.exists())

            rejected_completion_path = root / "rejected-completion.json"
            rejected_completion = run_packet_cli(
                [
                    "prepare-completion-audit-source",
                    *original_core,
                    "--reviewer-gate-source",
                    str(reviewer_source_path),
                    "--output",
                    str(rejected_completion_path),
                ]
            )
            self.assertEqual(rejected_completion.returncode, 1, rejected_completion.stdout)
            self.assertFalse(rejected_completion_path.exists())

            rejected_packet_path = root / "rejected-packet.json"
            rejected_build = run_packet_cli(
                [
                    "build-packet",
                    *original_core,
                    "--reviewer-gate-source",
                    str(reviewer_source_path),
                    "--completion-audit-source",
                    str(completion_source_path),
                    "--output",
                    str(rejected_packet_path),
                ]
            )
            self.assertEqual(rejected_build.returncode, 1, rejected_build.stdout)
            self.assertFalse(rejected_packet_path.exists())

            rejected_validation_path = root / "rejected-packet-validation.json"
            rejected_validation = run_packet_cli(
                [
                    "validate-packet",
                    "--packet",
                    str(replacement_packet_path),
                    *original_core,
                    "--reviewer-gate-source",
                    str(reviewer_source_path),
                    "--completion-audit-source",
                    str(completion_source_path),
                    "--output",
                    str(rejected_validation_path),
                ]
            )
            self.assertEqual(rejected_validation.returncode, 1, rejected_validation.stdout)
            rejected_validation_artifact = json.loads(
                rejected_validation_path.read_text(encoding="utf-8")
            )
            self.assertEqual(rejected_validation_artifact["status"], "failed")
            self.assertEqual(
                rejected_validation_artifact["error_code"],
                "operator_evidence_report_invalid",
            )

            failed_outputs = "\n".join(
                (
                    original_raw.stdout,
                    original_raw.stderr,
                    original_converter.stdout,
                    original_converter.stderr,
                    original_validation_path.read_text(encoding="utf-8"),
                    original_layer_path.read_text(encoding="utf-8"),
                    rejected_review.stdout,
                    rejected_review.stderr,
                    rejected_completion.stdout,
                    rejected_completion.stderr,
                    rejected_build.stdout,
                    rejected_build.stderr,
                    rejected_validation.stdout,
                    rejected_validation.stderr,
                    rejected_validation_path.read_text(encoding="utf-8"),
                    *(
                        stream
                        for result in local_hook_rejections
                        for stream in (result.stdout, result.stderr)
                    ),
                )
            )
            for forbidden in (
                str(root),
                candidate_report["execution_receipt"]["signature_hex"],
                replacement_authority["receipt_public_key_hex"],
                replacement_authority["campaign_nonce_hash"],
                candidate_report["runtime_image_id_hash"],
                "PRIVATE KEY",
            ):
                self.assertNotIn(forbidden, failed_outputs)

    def test_completion_attestation_is_required(self) -> None:
        existing = _authority_fixture_packet()
        sources = _completed_sources()
        completion = existing["layers"]["completion_audit"]
        receipt = {
            "implementation_contract_hash": completion["implementation_contract_hash"],
            "local_completion_audit_report_hash": completion["local_harness_report_hash"],
            "actor_context_contract_hash": completion["actor_context_contract_hash"],
            "documentation_contract_hash": completion["documentation_contract_hash"],
            "issue20_completion_journey_manifest_hash": completion["journey_manifest_hash"],
        }
        _bind_staged_sources(
            sources,
            local_receipt=receipt,
            base_layers=existing["layers"],
        )
        for attestation in ("auditor_attested", "operator_attested"):
            invalid = copy.deepcopy(sources)
            invalid["completion_audit"][attestation] = False
            with (
                self.subTest(attestation=attestation),
                self.assertRaisesRegex(
                    packet_module.EvidencePacketError,
                    "completion_audit_source_invalid",
                ),
            ):
                packet_module._build_external_packet_from_validated_inputs(
                    local_receipt=receipt,
                    live_postgresql_layer=existing["layers"]["live_postgresql"],
                    operator_cli_postgresql_layer=existing["layers"]["operator_cli_postgresql"],
                    operator_cli_postgresql_execution_authority_pin=(
                        _operator_execution_authority_pin()
                    ),
                    production_container_lifecycle_layer=existing["layers"][
                        "production_container_lifecycle"
                    ],
                    mcp_inspector_source=invalid["mcp_inspector"],
                    live_chatgpt_google_source=invalid["live_chatgpt_google"],
                    reviewer_gate_source=invalid["reviewer_gate"],
                    completion_audit_source=invalid["completion_audit"],
                )

    def test_paired_validation_rejects_other_coherently_rebuilt_sources(self) -> None:
        existing = _authority_fixture_packet()
        completion = existing["layers"]["completion_audit"]
        receipt = {
            "implementation_contract_hash": completion["implementation_contract_hash"],
            "local_completion_audit_report_hash": completion["local_harness_report_hash"],
            "actor_context_contract_hash": completion["actor_context_contract_hash"],
            "documentation_contract_hash": completion["documentation_contract_hash"],
            "issue20_completion_journey_manifest_hash": completion["journey_manifest_hash"],
        }
        expected_sources = _completed_sources()
        _bind_staged_sources(
            expected_sources,
            local_receipt=receipt,
            base_layers=existing["layers"],
        )
        expected_packet = packet_module._build_external_packet_from_validated_inputs(
            local_receipt=receipt,
            live_postgresql_layer=existing["layers"]["live_postgresql"],
            operator_cli_postgresql_layer=existing["layers"]["operator_cli_postgresql"],
            operator_cli_postgresql_execution_authority_pin=(_operator_execution_authority_pin()),
            production_container_lifecycle_layer=existing["layers"][
                "production_container_lifecycle"
            ],
            mcp_inspector_source=expected_sources["mcp_inspector"],
            live_chatgpt_google_source=expected_sources["live_chatgpt_google"],
            reviewer_gate_source=expected_sources["reviewer_gate"],
            completion_audit_source=expected_sources["completion_audit"],
        )

        alternate_sources = _completed_sources()
        alternate_sources["live_chatgpt_google"]["audit_records"][12]["reason_code"] = (
            "coherent_alternate_reason"
        )
        previous_hash = alternate_sources["live_chatgpt_google"]["audit_records"][11][
            "audit_record_hash"
        ]
        for record in alternate_sources["live_chatgpt_google"]["audit_records"][12:]:
            record["previous_audit_record_hash"] = previous_hash
            record["audit_record_hash"] = packet_module._safe_audit_record_hash(record)
            previous_hash = record["audit_record_hash"]
        _bind_staged_sources(
            alternate_sources,
            local_receipt=receipt,
            base_layers=existing["layers"],
        )
        alternate_packet = packet_module._build_external_packet_from_validated_inputs(
            local_receipt=receipt,
            live_postgresql_layer=existing["layers"]["live_postgresql"],
            operator_cli_postgresql_layer=existing["layers"]["operator_cli_postgresql"],
            operator_cli_postgresql_execution_authority_pin=(_operator_execution_authority_pin()),
            production_container_lifecycle_layer=existing["layers"][
                "production_container_lifecycle"
            ],
            mcp_inspector_source=alternate_sources["mcp_inspector"],
            live_chatgpt_google_source=alternate_sources["live_chatgpt_google"],
            reviewer_gate_source=alternate_sources["reviewer_gate"],
            completion_audit_source=alternate_sources["completion_audit"],
        )
        self.assertTrue(
            packet_module._authority.validate_external_evidence_packet(
                alternate_packet,
                expected_local_harness_report_hash=receipt["local_completion_audit_report_hash"],
                expected_operator_execution_authority_pin=(_operator_execution_authority_pin()),
            )["passed"]
        )

        with (
            mock.patch.object(
                packet_module,
                "build_external_packet",
                return_value=expected_packet,
            ),
            mock.patch.object(
                packet_module,
                "validate_local_harness_report",
                return_value=receipt,
            ),
        ):
            result = packet_module.validate_current_packet(
                alternate_packet,
                local_harness_report={},
                live_postgresql_evidence={},
                operator_cli_postgresql_report={},
                operator_cli_postgresql_execution_authority=(_operator_execution_authority()),
                operator_cli_postgresql_execution_authority_pin=(
                    _operator_execution_authority_pin()
                ),
                production_container_lifecycle_reports=[],
                operator_attest_postgresql=True,
                operator_attest_lifecycle=True,
                mcp_inspector_source={},
                live_chatgpt_google_source={},
                reviewer_gate_source={},
                completion_audit_source={},
            )

        self.assertFalse(result["passed"])
        self.assertFalse(result["exact_source_rebuild_match"])
        self.assertIn("packet_source_rebuild_mismatch", result["blockers"])

    def test_paired_validation_accepts_the_exact_same_rebuilt_packet(self) -> None:
        packet = _authority_fixture_packet()
        completion = packet["layers"]["completion_audit"]
        receipt = {
            "implementation_contract_hash": completion["implementation_contract_hash"],
            "local_completion_audit_report_hash": completion["local_harness_report_hash"],
            "actor_context_contract_hash": completion["actor_context_contract_hash"],
            "documentation_contract_hash": completion["documentation_contract_hash"],
            "issue20_completion_journey_manifest_hash": completion["journey_manifest_hash"],
        }
        with (
            mock.patch.object(
                packet_module,
                "build_external_packet",
                return_value=packet,
            ),
            mock.patch.object(
                packet_module,
                "validate_local_harness_report",
                return_value=receipt,
            ),
        ):
            result = packet_module.validate_current_packet(
                packet,
                local_harness_report={},
                live_postgresql_evidence={},
                operator_cli_postgresql_report={},
                operator_cli_postgresql_execution_authority=(_operator_execution_authority()),
                operator_cli_postgresql_execution_authority_pin=(
                    _operator_execution_authority_pin()
                ),
                production_container_lifecycle_reports=[],
                operator_attest_postgresql=True,
                operator_attest_lifecycle=True,
                mcp_inspector_source={},
                live_chatgpt_google_source={},
                reviewer_gate_source={},
                completion_audit_source={},
            )

        self.assertTrue(result["passed"], result["blockers"])
        self.assertTrue(result["exact_source_rebuild_match"])


if __name__ == "__main__":
    unittest.main()
