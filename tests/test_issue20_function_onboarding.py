from __future__ import annotations

import copy
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from oauth_harness import (
    ISSUE20_BASE_COMMIT,
    ISSUE20_FUNCTION_EXCLUSION_RULES,
    ISSUE20_FUNCTION_SCOPE_GLOBS,
    REQUIRED_HARNESS_CATEGORIES,
    changed_scoped_function_bindings,
    changed_scoped_functions,
    collect_unittest_test_ids,
    load_function_harness_manifest,
    validate_function_harness_manifest,
)


def lifecycle_probe_onboarding_contract() -> (
    tuple[
        str,
        dict[str, str],
        dict[str, dict[str, list[str] | str]],
    ]
):
    module = "scripts.connected_runtime_container_lifecycle_probe"
    prefix = "tests.test_connected_runtime_container." "ConnectedRuntimeContainerTests."

    def test_id(name: str) -> str:
        return prefix + name

    container_removed = test_id("test_assert_container_removed_accepts_only_docker_not_found")
    atomic_failures = test_id(
        "test_atomic_write_failures_preserve_prior_bytes_and_clean_temporary_files"
    )
    actual_compose = test_id(
        "test_actual_compose_journey_runs_migrate_preflight_and_fresh_secret_generations"
    )
    actual_compose_validation_failure = test_id(
        "test_actual_compose_journey_validation_failure_cleans_up_without_partial_success_evidence"
    )
    actual_compose_cleanup_failure = test_id(
        "test_actual_compose_journey_cleanup_failure_is_generic_and_suppresses_success_evidence"
    )
    all_runtime_paths = test_id("test_all_lifecycle_runtime_run_paths_use_the_exact_iid")
    bearer_failures = test_id("test_inside_seed_bearer_file_failures_clean_up_for_safe_retry")
    bearer_success = test_id("test_inside_seed_bearer_file_completes_short_writes_at_mode_0400")
    build_runtime = test_id("test_lifecycle_build_captures_and_inspects_exact_runtime_iid")
    client_invalid = test_id(
        "test_inside_client_rejects_result_without_exact_error_flag_after_cleanup"
    )
    client_success = test_id(
        "test_inside_client_sequence_returns_phase_specific_success_after_ordered_cleanup"
    )
    compose_command = test_id("test_compose_command_is_exact_argv_without_shell_expansion")
    compose_container_id = test_id(
        "test_compose_container_id_requires_one_lowercase_hex_identifier"
    )
    compose_resolution = test_id(
        "test_compose_resolution_is_bound_to_runtime_iid_and_postgres_digest"
    )
    compose_secret = test_id(
        "test_compose_postgres_secret_contract_is_exact_and_rejects_malformed_mounts"
    )
    container_json = test_id(
        "test_container_json_rejects_top_level_object_without_leaks_or_mutation"
    )
    data_hash = test_id("test_data_state_hash_is_bound_to_file_content")
    data_hash_invalid = test_id("test_data_state_hash_rejects_symlinks_without_leaking_paths")
    database_count = test_id(
        "test_database_connection_count_rejects_negative_count_without_leaks_or_mutation"
    )
    fetch_jwks = test_id("test_fetch_public_jwks_pins_exec_and_bounds_payload_failures")
    forged_seed = test_id("test_inside_seed_rejects_forged_client_state_before_token_exchange")
    hardened_launcher = test_id(
        "test_lifecycle_probe_uses_real_entrypoint_and_hardened_container_flags"
    )
    helper_invalid = test_id("test_inside_helper_result_rejects_malformed_stdout")
    helper_success = test_id("test_inside_helper_result_delegates_exact_success_contract")
    image_bound_invalid = test_id(
        "test_image_bound_helpers_reject_invalid_image_identity_before_downstream_work"
    )
    invalid_iid = test_id("test_lifecycle_invalid_iid_stops_before_inspect_or_runtime_run")
    jsonable_invalid = test_id("test_jsonable_rejects_stringified_mapping_key_collision_safely")
    jsonable_success = test_id("test_jsonable_supported_value_matrix_is_exact_and_non_mutating")
    main_failure = test_id(
        "test_main_failure_reports_use_atomic_output_and_do_not_leak_write_faults"
    )
    membership_invalid = test_id(
        "test_inside_persisted_state_rejects_inactive_current_membership_after_cleanup"
    )
    membership_success = test_id(
        "test_inside_persisted_state_returns_valid_current_membership_snapshots_after_cleanup"
    )
    model_dump_invalid = test_id("test_model_dump_rejects_non_callable_attribute_without_rendering")
    model_dump_success = test_id("test_model_dump_invokes_real_callable_once_with_exact_contract")
    postgres_start = test_id("test_postgres_start_uses_only_the_pinned_digest")
    private_report = test_id("test_lifecycle_probe_rejects_private_jwk_and_unsafe_failure_detail")
    probe_seed_failure = test_id(
        "test_lifecycle_probe_seed_failures_and_probe_directory_are_bounded"
    )
    reserve_port = test_id("test_reserve_loopback_port_binds_loopback_and_releases_socket")
    run_command = test_id("test_run_command_pins_subprocess_contract_and_bounds_failures")
    run_compose = test_id("test_run_compose_command_pins_argv_env_and_redacts_outputs")
    run_probe_output = test_id(
        "test_run_probe_success_report_uses_atomic_output_without_clobbering_prior_bytes"
    )
    run_runtime = test_id("test_run_runtime_command_pins_argv_and_bounds_public_output")
    runtime_output_invalid = test_id(
        "test_stop_runtime_rejects_unsafe_logs_before_database_drain_or_remove"
    )
    runtime_security = test_id(
        "test_runtime_security_contract_requires_all_five_capability_sets_zero"
    )
    safe_report = test_id("test_lifecycle_probe_safe_report_contract_is_bounded")
    staged_snapshot = test_id(
        "test_staged_secret_snapshot_rejects_negative_file_count_without_leaks_or_mutation"
    )
    start_runtime = test_id("test_start_runtime_pins_detached_serve_argv_and_propagates_failure")
    stop_runtime_invalid = test_id(
        "test_stop_runtime_rejects_malformed_state_before_logs_or_cleanup"
    )
    stop_runtime_success = test_id("test_stop_runtime_success_orders_cleanup_and_returns_safe_logs")
    wait_healthy = test_id(
        "test_wait_for_healthy_container_rejects_malformed_state_without_sleep_or_leaks"
    )
    wait_ready = test_id("test_wait_for_ready_behavior_matrix_pins_polling_and_failures")
    wait_ready_invalid = test_id("test_wait_for_ready_rejects_malformed_state_before_exec_or_sleep")
    wait_zero_connections = test_id(
        "test_wait_for_zero_database_connections_polls_boundedly_and_fails_safely"
    )
    signing_manifest_invalid = test_id(
        "test_write_signing_manifest_rejects_invalid_phase_and_missing_overlap_expiry_before_write"
    )

    groups = {
        private_report: {
            "LifecycleProbeFailure.__init__",
            "_contains_forbidden_report_text",
            "_validate_public_jwks",
        },
        container_removed: {"_assert_container_removed"},
        run_runtime: {"_assert_runtime_output_safe", "_run_runtime_command"},
        atomic_failures: {"_atomic_write"},
        build_runtime: {"_build_runtime_image", "_require_runtime_image_id"},
        safe_report: {
            "_build_success_report",
            "_current_issue20_implementation_contract_hash",
            "_runtime_command_contract_hash",
            "validate_report",
        },
        compose_command: {"_compose_command"},
        compose_container_id: {"_compose_container_id"},
        compose_resolution: {
            "_compose_environment",
            "_host_secret_source_contract",
            "_validate_compose_config",
        },
        compose_secret: {"_compose_postgres_secret_contract"},
        container_json: {"_container_json"},
        data_hash: {"_data_state_hash", "_sha256_json"},
        database_count: {"_database_connection_count"},
        main_failure: {"_failure_report", "main"},
        fetch_jwks: {"_fetch_public_jwks"},
        all_runtime_paths: {
            "_generate_signing_keys",
            "_prepare_data_directory",
            "_read_persisted_state",
            "_remove_runtime_image",
            "_restore_data_directory_ownership",
            "_run_official_container_client",
            "_seed_oauth_state",
        },
        client_success: {"_inside_client_sequence"},
        helper_success: {"_inside_helper_result", "_json_line"},
        membership_success: {"_inside_persisted_state"},
        forged_seed: {
            "_inside_seed_oauth_state",
            "_inside_seed_oauth_state.<locals>._SeedGoogleClient.__init__",
            "_inside_seed_oauth_state.<locals>._SeedGoogleClient.authenticate_code",
            "_inside_seed_oauth_state.<locals>._SeedGoogleClient.build_authorization_url",
        },
        probe_seed_failure: {"_inside_seed_step", "_prepare_probe_directory"},
        jsonable_success: {"_jsonable"},
        hardened_launcher: {
            "_launcher_security_args",
            "_runtime_environment",
            "_runtime_run_command",
            "_runtime_secret_mount_args",
        },
        model_dump_success: {"_model_dump"},
        reserve_port: {"_reserve_loopback_port"},
        actual_compose: {
            "_run_actual_compose_journey",
            "_write_signing_manifest",
        },
        run_command: {"_run_command", "_safe_runtime_error_code"},
        run_compose: {"_run_compose_command"},
        runtime_security: {"_runtime_security_contract"},
        staged_snapshot: {"_staged_secret_snapshot"},
        postgres_start: {"_require_pinned_postgres_image", "_start_postgres"},
        start_runtime: {"_start_runtime"},
        stop_runtime_success: {"_stop_runtime"},
        wait_healthy: {"_wait_for_healthy_container"},
        wait_ready: {"_wait_for_ready"},
        wait_zero_connections: {"_wait_for_zero_database_connections"},
        bearer_success: {"_write_inside_seed_bearer_file"},
        run_probe_output: {"run_probe"},
    }
    primary_test_by_qualname = {
        qualname: evidence_test
        for evidence_test, qualnames in groups.items()
        for qualname in qualnames
    }
    function_roles = {
        "LifecycleProbeFailure.__init__": (
            "stores one bounded lifecycle stage and safe error code"
        ),
        "_assert_container_removed": (
            "verifies that one retired container is absent after cleanup"
        ),
        "_assert_runtime_output_safe": (
            "rejects secret, path, SQL, and credential material in runtime output"
        ),
        "_atomic_write": ("atomically replaces one bounded report or secret manifest file"),
        "_build_runtime_image": (
            "builds the runtime image and binds the immutable image identifier"
        ),
        "_build_success_report": (
            "projects internal lifecycle evidence into the fixed public report"
        ),
        "_compose_command": ("constructs one shell-free Docker Compose argument vector"),
        "_compose_container_id": ("resolves one exact lowercase hexadecimal Compose container id"),
        "_compose_environment": (
            "constructs the private Compose environment bound to pinned images"
        ),
        "_compose_postgres_secret_contract": (
            "validates the PostgreSQL secret mount and health contract"
        ),
        "_container_json": ("reads and validates one Docker container inspection object"),
        "_contains_forbidden_report_text": (
            "recursively detects forbidden material in a public report"
        ),
        "_current_issue20_implementation_contract_hash": (
            "computes the pinned Issue #20 implementation contract digest"
        ),
        "_data_state_hash": ("hashes the bounded persisted data tree without following symlinks"),
        "_database_connection_count": (
            "reads one validated nonnegative PostgreSQL connection count"
        ),
        "_failure_report": ("projects one bounded lifecycle failure into a fixed public envelope"),
        "_fetch_public_jwks": ("fetches and parses the public JWKS through the runtime container"),
        "_generate_signing_keys": (
            "generates the two transient signing keys used by the lifecycle probe"
        ),
        "_host_secret_source_contract": ("summarizes host secret source modes and content hashes"),
        "_inside_client_sequence": ("executes the phase-specific protected MCP client sequence"),
        "_inside_helper_result": (
            "executes one in-container helper and validates its safe JSON result"
        ),
        "_inside_persisted_state": (
            "reads persisted identity, membership, token, upload, and audit state"
        ),
        "_inside_seed_oauth_state": (
            "runs the deterministic Google-backed OAuth seed transaction sequence"
        ),
        "_inside_seed_oauth_state.<locals>._SeedGoogleClient.__init__": (
            "initializes the deterministic seed-only Google client state"
        ),
        "_inside_seed_oauth_state.<locals>._SeedGoogleClient.authenticate_code": (
            "validates the deterministic Google code and nonce during seed login"
        ),
        "_inside_seed_oauth_state.<locals>._SeedGoogleClient.build_authorization_url": (
            "records the deterministic Google state and nonce for seed login"
        ),
        "_inside_seed_step": ("wraps one seed operation with a fixed non-leaking failure code"),
        "_json_line": ("parses one exact JSON line from a bounded subprocess result"),
        "_jsonable": ("normalizes supported internal values into canonical JSON-safe data"),
        "_launcher_security_args": (
            "constructs the fixed nonroot and no-new-privileges launcher flags"
        ),
        "_model_dump": (
            "extracts one supported model dictionary through the exact callable contract"
        ),
        "_prepare_data_directory": (
            "prepares the private lifecycle data directory for the runtime uid"
        ),
        "_prepare_probe_directory": ("creates the bounded probe directory with the required mode"),
        "_read_persisted_state": (
            "launches the read-only persisted-state helper in the pinned image"
        ),
        "_remove_runtime_image": ("removes the ephemeral runtime image during lifecycle cleanup"),
        "_require_pinned_postgres_image": ("accepts only the compile-time PostgreSQL image digest"),
        "_require_runtime_image_id": ("accepts only an immutable sha256 runtime image identifier"),
        "_reserve_loopback_port": ("reserves and releases one loopback-only TCP port"),
        "_restore_data_directory_ownership": (
            "restores lifecycle data ownership after container execution"
        ),
        "_run_actual_compose_journey": (
            "orchestrates migrate, preflight, restart, rotation, and cleanup in Compose"
        ),
        "_run_command": ("executes one bounded local subprocess with fixed capture semantics"),
        "_run_compose_command": (
            "executes one bounded Docker Compose command with private environment"
        ),
        "_run_official_container_client": (
            "launches the official MCP client inside the pinned runtime image"
        ),
        "_run_runtime_command": ("executes one runtime container command and returns safe JSON"),
        "_runtime_command_contract_hash": ("hashes the fixed runtime and Compose command contract"),
        "_runtime_environment": ("constructs the fixed private runtime environment mapping"),
        "_runtime_run_command": ("constructs one hardened Docker run command for the pinned image"),
        "_runtime_secret_mount_args": (
            "constructs the fixed read-only runtime secret mount arguments"
        ),
        "_runtime_security_contract": (
            "validates uid, gid, groups, capability sets, and no-new-privileges"
        ),
        "_safe_runtime_error_code": (
            "extracts one allowlisted safe error code from subprocess streams"
        ),
        "_seed_oauth_state": ("launches the in-container OAuth seed helper with private mounts"),
        "_sha256_json": ("returns one deterministic digest for canonical JSON"),
        "_staged_secret_snapshot": (
            "summarizes one staged signing-secret generation by counts and hashes"
        ),
        "_start_postgres": ("starts the lifecycle PostgreSQL container from the pinned digest"),
        "_start_runtime": ("starts the hardened connected runtime container in detached mode"),
        "_stop_runtime": ("stops, drains, inspects, and removes one runtime container"),
        "_validate_compose_config": (
            "validates resolved Compose wiring, commands, mounts, and pinned images"
        ),
        "_validate_public_jwks": (
            "validates the exact public-only JWKS key set for one rotation phase"
        ),
        "_wait_for_healthy_container": (
            "polls one container until its health state is valid and healthy"
        ),
        "_wait_for_ready": ("polls the runtime readiness route through bounded in-container HTTP"),
        "_wait_for_zero_database_connections": (
            "polls until the runtime releases all PostgreSQL connections"
        ),
        "_write_inside_seed_bearer_file": (
            "writes the seed bearer token with exclusive mode 0400 semantics"
        ),
        "_write_signing_manifest": (
            "writes one current and optional previous signing-key manifest"
        ),
        "main": ("dispatches the local lifecycle CLI and emits only a safe failure envelope"),
        "run_probe": ("orchestrates the full lifecycle probe and atomically writes its report"),
        "validate_report": ("validates the closed public lifecycle report and claim boundary"),
    }
    invalid_tests = {
        "LifecycleProbeFailure.__init__": private_report,
        "_assert_container_removed": container_removed,
        "_assert_runtime_output_safe": runtime_output_invalid,
        "_atomic_write": atomic_failures,
        "_build_runtime_image": invalid_iid,
        "_build_success_report": safe_report,
        "_compose_command": compose_command,
        "_compose_container_id": compose_container_id,
        "_compose_environment": compose_resolution,
        "_compose_postgres_secret_contract": compose_secret,
        "_container_json": container_json,
        "_contains_forbidden_report_text": private_report,
        "_current_issue20_implementation_contract_hash": safe_report,
        "_data_state_hash": data_hash_invalid,
        "_database_connection_count": database_count,
        "_failure_report": main_failure,
        "_fetch_public_jwks": fetch_jwks,
        "_generate_signing_keys": image_bound_invalid,
        "_host_secret_source_contract": compose_resolution,
        "_inside_client_sequence": client_invalid,
        "_inside_helper_result": helper_invalid,
        "_inside_persisted_state": membership_invalid,
        "_inside_seed_oauth_state": forged_seed,
        "_inside_seed_oauth_state.<locals>._SeedGoogleClient.__init__": forged_seed,
        "_inside_seed_oauth_state.<locals>._SeedGoogleClient.authenticate_code": (forged_seed),
        "_inside_seed_oauth_state.<locals>._SeedGoogleClient.build_authorization_url": (
            forged_seed
        ),
        "_inside_seed_step": probe_seed_failure,
        "_json_line": helper_invalid,
        "_jsonable": jsonable_invalid,
        "_model_dump": model_dump_invalid,
        "_prepare_data_directory": image_bound_invalid,
        "_read_persisted_state": image_bound_invalid,
        "_remove_runtime_image": image_bound_invalid,
        "_require_pinned_postgres_image": postgres_start,
        "_require_runtime_image_id": invalid_iid,
        "_restore_data_directory_ownership": image_bound_invalid,
        "_run_actual_compose_journey": actual_compose_validation_failure,
        "_run_command": run_command,
        "_run_compose_command": run_compose,
        "_run_official_container_client": image_bound_invalid,
        "_run_runtime_command": run_runtime,
        "_runtime_run_command": image_bound_invalid,
        "_runtime_command_contract_hash": safe_report,
        "_runtime_security_contract": runtime_security,
        "_safe_runtime_error_code": run_command,
        "_seed_oauth_state": image_bound_invalid,
        "_staged_secret_snapshot": staged_snapshot,
        "_start_postgres": postgres_start,
        "_start_runtime": start_runtime,
        "_stop_runtime": stop_runtime_invalid,
        "_validate_compose_config": compose_resolution,
        "_validate_public_jwks": private_report,
        "_wait_for_healthy_container": wait_healthy,
        "_wait_for_ready": wait_ready_invalid,
        "_wait_for_zero_database_connections": wait_zero_connections,
        "_write_inside_seed_bearer_file": bearer_failures,
        "_write_signing_manifest": signing_manifest_invalid,
        "main": main_failure,
        "run_probe": run_probe_output,
        "validate_report": private_report,
    }
    temporal_tests = {
        "_build_success_report": safe_report,
        "_inside_persisted_state": membership_invalid,
        "_inside_seed_oauth_state": forged_seed,
        "_inside_seed_oauth_state.<locals>._SeedGoogleClient.__init__": forged_seed,
        "_inside_seed_oauth_state.<locals>._SeedGoogleClient.authenticate_code": (forged_seed),
        "_inside_seed_oauth_state.<locals>._SeedGoogleClient.build_authorization_url": (
            forged_seed
        ),
        "_run_actual_compose_journey": actual_compose,
        "_validate_public_jwks": actual_compose,
        "_write_signing_manifest": actual_compose,
        "validate_report": safe_report,
    }
    rollback_tests = {
        "_atomic_write": atomic_failures,
        "_build_runtime_image": invalid_iid,
        "_inside_seed_oauth_state": forged_seed,
        "_run_actual_compose_journey": actual_compose_validation_failure,
        "_start_runtime": start_runtime,
        "_stop_runtime": stop_runtime_success,
        "_write_inside_seed_bearer_file": bearer_failures,
        "_write_signing_manifest": actual_compose,
        "main": main_failure,
        "run_probe": run_probe_output,
    }
    audit_tests = {
        "_inside_persisted_state": membership_invalid,
        "_inside_seed_oauth_state": forged_seed,
    }
    leak_tests = {
        "LifecycleProbeFailure.__init__": private_report,
        "_assert_container_removed": container_removed,
        "_assert_runtime_output_safe": runtime_output_invalid,
        "_atomic_write": atomic_failures,
        "_build_runtime_image": invalid_iid,
        "_build_success_report": safe_report,
        "_compose_command": compose_command,
        "_compose_container_id": compose_container_id,
        "_compose_environment": compose_resolution,
        "_compose_postgres_secret_contract": compose_secret,
        "_container_json": container_json,
        "_contains_forbidden_report_text": private_report,
        "_current_issue20_implementation_contract_hash": safe_report,
        "_data_state_hash": data_hash_invalid,
        "_database_connection_count": database_count,
        "_failure_report": main_failure,
        "_fetch_public_jwks": fetch_jwks,
        "_host_secret_source_contract": compose_resolution,
        "_inside_client_sequence": client_invalid,
        "_inside_helper_result": helper_invalid,
        "_inside_persisted_state": membership_invalid,
        "_inside_seed_oauth_state": forged_seed,
        "_inside_seed_oauth_state.<locals>._SeedGoogleClient.__init__": forged_seed,
        "_inside_seed_oauth_state.<locals>._SeedGoogleClient.authenticate_code": (forged_seed),
        "_inside_seed_oauth_state.<locals>._SeedGoogleClient.build_authorization_url": (
            forged_seed
        ),
        "_inside_seed_step": probe_seed_failure,
        "_json_line": helper_invalid,
        "_jsonable": jsonable_invalid,
        "_model_dump": model_dump_invalid,
        "_require_pinned_postgres_image": postgres_start,
        "_require_runtime_image_id": invalid_iid,
        "_run_actual_compose_journey": actual_compose_cleanup_failure,
        "_run_command": run_command,
        "_run_compose_command": run_compose,
        "_run_runtime_command": run_runtime,
        "_runtime_command_contract_hash": safe_report,
        "_runtime_security_contract": runtime_security,
        "_safe_runtime_error_code": run_command,
        "_sha256_json": safe_report,
        "_staged_secret_snapshot": staged_snapshot,
        "_start_postgres": postgres_start,
        "_start_runtime": start_runtime,
        "_stop_runtime": runtime_output_invalid,
        "_validate_compose_config": compose_resolution,
        "_validate_public_jwks": private_report,
        "_wait_for_healthy_container": wait_healthy,
        "_wait_for_ready": wait_ready_invalid,
        "_wait_for_zero_database_connections": wait_zero_connections,
        "_write_inside_seed_bearer_file": bearer_failures,
        "main": main_failure,
        "run_probe": run_probe_output,
        "validate_report": private_report,
    }
    remote_tests = {
        "_fetch_public_jwks": fetch_jwks,
        "_inside_client_sequence": client_invalid,
        "_wait_for_ready": wait_ready,
    }
    category_tests = {
        "invalid_or_protocol": invalid_tests,
        "expiry_replay_or_revocation": temporal_tests,
        "rollback_or_no_partial_state": rollback_tests,
        "audit_lineage": audit_tests,
        "leak_safety": leak_tests,
        "remote_http": remote_tests,
    }

    def not_applicable_reason(qualname: str, category: str) -> str:
        identity = f"{module}.{qualname}"
        role = function_roles[qualname]
        details = {
            "invalid_or_protocol": (
                "it has no caller-controlled input and does not parse protocol input "
                "at this layer; the enclosing validator or command boundary owns "
                "malformed external input."
            ),
            "expiry_replay_or_revocation": (
                "it has no temporal state and does not own expiry, replay, or "
                "revocation; the OAuth seed, persisted-state, client-phase, or "
                "signing-rotation boundary owns lifecycle decisions."
            ),
            "rollback_or_no_partial_state": (
                "it does not open a transaction and performs no durable governed-state "
                "write at this layer; the enclosing atomic writer, repository, or "
                "container cleanup boundary owns partial-state recovery."
            ),
            "audit_lineage": (
                "it does not emit audit and does not persist audit; the OAuth seed, "
                "protected MCP runtime, and persisted-state verifier own durable "
                "audit lineage."
            ),
            "leak_safety": (
                "it returns no caller-visible data; its internal value remains inside "
                "the lifecycle runner until fixed report validation or a dedicated "
                "redaction boundary."
            ),
            "remote_http": (
                "it is not an HTTP boundary and does not perform HTTP; any remote "
                "request is owned by the in-container MCP client, readiness poller, "
                "or JWKS fetcher."
            ),
        }
        return f"{identity} {role}; {details[category]}"

    expected_by_qualname: dict[str, dict[str, list[str] | str]] = {}
    for qualname, primary_test in sorted(primary_test_by_qualname.items()):
        expected: dict[str, list[str] | str] = {"success": [primary_test]}
        for category, test_map in category_tests.items():
            expected[category] = (
                [test_map[qualname]]
                if qualname in test_map
                else not_applicable_reason(qualname, category)
            )
        expected_by_qualname[qualname] = expected

    return module, function_roles, expected_by_qualname


class Issue20FunctionOnboardingTests(unittest.TestCase):
    def assert_batch_status_partition(
        self,
        manifest: dict,
        target_keys: set[tuple[str, str]],
    ) -> None:
        target_entries = [
            entry
            for entry in manifest["functions"]
            if (entry["module"], entry["qualname"]) in target_keys
        ]
        unrelated_entries = [
            entry
            for entry in manifest["functions"]
            if (entry["module"], entry["qualname"]) not in target_keys
        ]

        self.assertEqual(
            {(entry["module"], entry["qualname"]) for entry in target_entries},
            target_keys,
        )
        self.assertTrue(target_entries)
        self.assertTrue(all(entry["status"] == "onboarded" for entry in target_entries))
        self.assertEqual(len(target_entries) + len(unrelated_entries), len(manifest["functions"]))
        self.assertEqual(
            sum(entry["status"] == "onboarded" for entry in manifest["functions"]),
            len(target_entries)
            + sum(entry["status"] == "onboarded" for entry in unrelated_entries),
        )
        self.assertEqual(
            sum(entry["status"] == "pending" for entry in manifest["functions"]),
            sum(entry["status"] == "pending" for entry in unrelated_entries),
        )
        self.assertEqual(
            sum(entry["status"] in {"onboarded", "pending"} for entry in manifest["functions"]),
            len(manifest["functions"]),
        )

    def test_packet_batch_partition_ignores_unrelated_status_transition(self) -> None:
        current = load_function_harness_manifest()
        target_module = "formowl_evidence.issue20_packet"
        unrelated_key = next(
            (entry["module"], entry["qualname"])
            for entry in current["functions"]
            if entry["module"] != target_module
        )
        baseline = copy.deepcopy(current)
        baseline_entry = next(
            entry
            for entry in baseline["functions"]
            if (entry["module"], entry["qualname"]) == unrelated_key
        )
        baseline_entry["status"] = "pending"
        transitioned = copy.deepcopy(baseline)
        transitioned_entry = next(
            entry
            for entry in transitioned["functions"]
            if (entry["module"], entry["qualname"]) == unrelated_key
        )
        transitioned_entry["status"] = "onboarded"

        for unrelated_status, manifest in (
            ("pending", baseline),
            ("onboarded", transitioned),
        ):
            with (
                self.subTest(unrelated_status=unrelated_status),
                patch(
                    f"{__name__}.load_function_harness_manifest",
                    return_value=manifest,
                ),
            ):
                self.test_issue20_external_packet_batch_is_manifest_onboarded()

    def test_callback_discovery_only_function_slice_is_manifest_onboarded(
        self,
    ) -> None:
        manifest = load_function_harness_manifest()
        root = Path(__file__).resolve().parents[1]
        bindings = changed_scoped_function_bindings(
            root,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}

        config_post = ("formowl_auth.config", "OAuthBridgeConfig.__post_init__")
        config_public = ("formowl_auth.config", "OAuthBridgeConfig.to_public_dict")
        http_error = ("formowl_auth.http", "_authorization_error_response")
        service_keys = {
            ("formowl_auth.service", "FormOwlOAuthBridge._require_stateful_oauth"),
            ("formowl_auth.service", "FormOwlOAuthBridge.bootstrap_owner_invitation"),
            ("formowl_auth.service", "FormOwlOAuthBridge.complete_google_callback"),
            ("formowl_auth.service", "FormOwlOAuthBridge.complete_google_denial"),
            ("formowl_auth.service", "FormOwlOAuthBridge.exchange_authorization_code"),
            ("formowl_auth.service", "FormOwlOAuthBridge.provision_invitation"),
            (
                "formowl_auth.service",
                "FormOwlOAuthBridge.record_mcp_authorization_decision",
            ),
            (
                "formowl_auth.service",
                "FormOwlOAuthBridge.record_mcp_http_authentication_denial",
            ),
            ("formowl_auth.service", "FormOwlOAuthBridge.record_oauth_denial"),
            ("formowl_auth.service", "FormOwlOAuthBridge.revoke_token_session"),
            (
                "formowl_auth.service",
                "FormOwlOAuthBridge.revoke_token_session_as_operator",
            ),
            ("formowl_auth.service", "FormOwlOAuthBridge.start_authorization"),
        }
        remote_record_decision = (
            "formowl_gateway.remote",
            "RemoteMcpDispatcher._record_decision",
        )
        remote_call_tool = (
            "formowl_gateway.remote",
            "RemoteMcpDispatcher.call_tool",
        )
        remote_redacting_lookup = (
            "formowl_gateway.remote",
            "_RedactingMcpServer._get_cached_tool_definition",
        )
        remote_keys = {
            ("formowl_gateway.remote", "BearerAuthenticationMiddleware.__call__"),
            ("formowl_gateway.remote", "BearerAuthenticationMiddleware.__init__"),
            ("formowl_gateway.remote", "RemoteMcpDispatcher.__init__"),
            remote_record_decision,
            remote_call_tool,
            remote_redacting_lookup,
            ("formowl_gateway.remote", "create_connected_mcp_application"),
        }
        runtime_operator_keys = {
            ("formowl_gateway.runtime", "ConnectedRuntime._require_stateful_oauth"),
            ("formowl_gateway.runtime", "ConnectedRuntime.bootstrap_owner"),
            ("formowl_gateway.runtime", "ConnectedRuntime.invite_user"),
            ("formowl_gateway.runtime", "ConnectedRuntime.list_token_sessions"),
            ("formowl_gateway.runtime", "ConnectedRuntime.list_users"),
            ("formowl_gateway.runtime", "ConnectedRuntime.lookup_token_session"),
            ("formowl_gateway.runtime", "ConnectedRuntime.lookup_user"),
            ("formowl_gateway.runtime", "ConnectedRuntime.remove_workspace_member"),
            ("formowl_gateway.runtime", "ConnectedRuntime.restore_workspace_member"),
            ("formowl_gateway.runtime", "ConnectedRuntime.revoke_token_session"),
        }
        runtime_edge_keys = {
            ("formowl_gateway.runtime", "ConnectedRuntime.readiness"),
            ("formowl_gateway.runtime", "ConnectedRuntime.serve"),
        }
        selected_keys = {
            config_post,
            config_public,
            http_error,
            *service_keys,
            *remote_keys,
            *runtime_operator_keys,
            *runtime_edge_keys,
        }
        self.assertEqual(len(selected_keys), 34)
        self.assertTrue(selected_keys.issubset(entries))

        config_valid = (
            "tests.test_oauth_config_routes.OAuthConfigRouteTests."
            "test_valid_production_and_explicit_loopback_configs"
        )
        config_matrix = (
            "tests.test_oauth_config_routes.OAuthConfigRouteTests."
            "test_chatgpt_callback_shape_and_reserved_sentinel_matrix"
        )
        config_no_write = (
            "tests.test_oauth_config_routes.OAuthConfigRouteTests."
            "test_invalid_url_and_clock_skew_matrix_leaves_repository_unchanged"
        )
        cli_attacker = (
            "tests.test_connected_runtime.ConnectedRuntimeCliTests."
            "test_cli_invalid_arbitrary_https_callback_fails_before_external_effects"
        )
        http_discovery = (
            "tests.test_oauth_http_routes.OAuthHttpRouteTests."
            "test_discovery_only_http_is_no_write_and_exact_restart_restores_oauth"
        )
        service_discovery = (
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_discovery_only_rejects_every_oauth_state_writer_before_transaction"
        )
        remote_discovery = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_discovery_only_lists_tools_and_challenges_without_auth_or_audit"
        )
        remote_unknown_tool_audit_failure = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_unknown_tool_denial_audit_failure_returns_safe_server_error"
        )
        remote_missing_principal_audit_failure = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_missing_principal_denial_audit_failure_returns_safe_server_error"
        )
        remote_actor_context_audit_failure = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_actor_context_denial_audit_failure_returns_safe_server_error"
        )
        remote_invalid_arguments_audit_failure = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_invalid_tool_arguments_denial_audit_failure_returns_safe_server_error_and_"
            "skips_handler"
        )
        remote_viewer_audit_failure = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_viewer_denial_audit_failure_blocks_upload_handler_and_success"
        )
        remote_removed_membership = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_removed_membership_and_audit_failure_fail_closed_before_handler"
        )
        remote_closed_policy = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_closed_tool_policy_allows_only_declared_roles_without_grants"
        )
        remote_denial_audited = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_viewer_upload_grants_cannot_elevate_and_denial_is_audited"
        )
        remote_unknown_tool_log_redaction = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_unknown_tool_name_is_redacted_from_sdk_logs_before_dispatch"
        )
        remote_invalid_semantic_payload = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_dispatcher_invalid_semantic_payloads_return_fixed_error_after_authorization"
        )
        remote_coroutine_result = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_dispatcher_closes_coroutine_result_without_awaiting_or_leaking"
        )
        remote_async_handler = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_dispatcher_rejects_configured_async_handler_before_dispatch_without_warning"
        )
        remote_cancellation = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_dispatcher_does_not_swallow_cancellation"
        )
        runtime_operators = (
            "tests.test_connected_runtime.ConnectedRuntimeLifecycleTests."
            "test_discovery_only_blocks_operator_state_and_audited_lookup_entrypoints"
        )
        runtime_edge = (
            "tests.test_connected_runtime.ConnectedRuntimeLifecycleTests."
            "test_discovery_preflight_is_not_ready_but_serve_allows_public_discovery"
        )
        expected = {
            key: {category: set() for category in REQUIRED_HARNESS_CATEGORIES}
            for key in selected_keys
        }
        expected[config_post]["success"].add(config_valid)
        expected[config_post]["invalid_or_protocol"].add(config_matrix)
        expected[config_post]["rollback_or_no_partial_state"].add(config_no_write)
        expected[config_post]["leak_safety"].add(cli_attacker)
        expected[config_public]["success"].add(config_valid)
        expected[config_public]["leak_safety"].add(config_valid)
        for category in (
            "success",
            "invalid_or_protocol",
            "rollback_or_no_partial_state",
            "audit_lineage",
            "leak_safety",
            "remote_http",
        ):
            expected[http_error][category].add(http_discovery)
        for key in service_keys:
            for category in (
                "success",
                "invalid_or_protocol",
                "rollback_or_no_partial_state",
                "audit_lineage",
                "leak_safety",
            ):
                expected[key][category].add(service_discovery)
        for qualname in (
            "FormOwlOAuthBridge.revoke_token_session",
            "FormOwlOAuthBridge.revoke_token_session_as_operator",
        ):
            expected[("formowl_auth.service", qualname)]["expiry_replay_or_revocation"].add(
                service_discovery
            )
        for key in remote_keys - {
            remote_record_decision,
            remote_call_tool,
            remote_redacting_lookup,
        }:
            for category in REQUIRED_HARNESS_CATEGORIES:
                expected[key][category].add(remote_discovery)
        for category in (
            "success",
            "invalid_or_protocol",
            "rollback_or_no_partial_state",
            "audit_lineage",
            "leak_safety",
            "remote_http",
        ):
            expected[remote_redacting_lookup][category].add(remote_unknown_tool_log_redaction)
        expected[remote_call_tool]["success"].add(remote_closed_policy)
        expected[remote_call_tool]["invalid_or_protocol"].update(
            {
                remote_coroutine_result,
                remote_invalid_semantic_payload,
                remote_async_handler,
                remote_unknown_tool_audit_failure,
                remote_missing_principal_audit_failure,
                remote_invalid_arguments_audit_failure,
            }
        )
        expected[remote_call_tool]["expiry_replay_or_revocation"].update(
            {
                remote_actor_context_audit_failure,
                remote_removed_membership,
            }
        )
        remote_fail_closed = {
            remote_unknown_tool_audit_failure,
            remote_missing_principal_audit_failure,
            remote_actor_context_audit_failure,
            remote_invalid_arguments_audit_failure,
            remote_viewer_audit_failure,
            remote_removed_membership,
        }
        remote_execution_boundary = {
            remote_coroutine_result,
            remote_invalid_semantic_payload,
            remote_async_handler,
        }
        for category in (
            "rollback_or_no_partial_state",
            "leak_safety",
            "remote_http",
        ):
            expected[remote_call_tool][category].update(remote_fail_closed)
        for category in (
            "rollback_or_no_partial_state",
            "audit_lineage",
            "leak_safety",
        ):
            expected[remote_call_tool][category].update(remote_execution_boundary)
        expected[remote_call_tool]["rollback_or_no_partial_state"].add(remote_cancellation)
        expected[remote_call_tool]["audit_lineage"].add(remote_cancellation)
        expected[remote_call_tool]["leak_safety"].add(remote_unknown_tool_log_redaction)
        expected[remote_call_tool]["remote_http"].add(remote_unknown_tool_log_redaction)
        expected[remote_call_tool]["audit_lineage"].update(
            {
                remote_closed_policy,
                remote_denial_audited,
            }
        )
        expected[remote_record_decision]["success"].add(remote_closed_policy)
        expected[remote_record_decision]["rollback_or_no_partial_state"].update(remote_fail_closed)
        expected[remote_record_decision]["audit_lineage"].update(
            {
                remote_closed_policy,
                remote_denial_audited,
            }
        )
        expected[remote_record_decision]["leak_safety"].update(remote_fail_closed)
        for key in runtime_operator_keys:
            for category in (
                "success",
                "invalid_or_protocol",
                "rollback_or_no_partial_state",
                "audit_lineage",
                "leak_safety",
            ):
                expected[key][category].add(runtime_operators)
        expected[("formowl_gateway.runtime", "ConnectedRuntime.revoke_token_session")][
            "expiry_replay_or_revocation"
        ].add(runtime_operators)
        for key in runtime_edge_keys:
            for category in (
                "success",
                "invalid_or_protocol",
                "leak_safety",
                "remote_http",
            ):
                expected[key][category].add(runtime_edge)
        expected[("formowl_gateway.runtime", "ConnectedRuntime.serve")][
            "rollback_or_no_partial_state"
        ].add(runtime_edge)

        collected = collect_unittest_test_ids(Path(__file__).resolve().parent)
        for key in sorted(selected_keys):
            with self.subTest(function_key=key):
                entry = entries[key]
                self.assertEqual(entry["status"], "onboarded")
                self.assertEqual(entry["source_binding"], bindings[key])
                self.assertEqual(set(entry["categories"]), set(REQUIRED_HARNESS_CATEGORIES))
                category_test_union: set[str] = set()
                for category in REQUIRED_HARNESS_CATEGORIES:
                    evidence = entry["categories"][category]
                    category_tests = set(evidence["test_ids"])
                    category_test_union.update(category_tests)
                    if key in {
                        remote_record_decision,
                        remote_call_tool,
                        remote_redacting_lookup,
                    }:
                        self.assertEqual(expected[key][category], category_tests)
                    else:
                        self.assertTrue(expected[key][category].issubset(category_tests))
                    self.assertTrue(category_tests.issubset(collected))
                    self.assertIn(evidence["pending_reason"], (None, ""))
                    if category_tests:
                        self.assertIn(evidence["not_applicable_reason"], (None, ""))
                    else:
                        self.assertIsInstance(evidence["not_applicable_reason"], str)
                        self.assertTrue(evidence["not_applicable_reason"].strip())
                self.assertTrue(entry["categories"]["success"]["test_ids"])
                self.assertEqual(category_test_union, set(entry["test_ids"]))

    def test_semantic_handler_payload_guard_slice_is_manifest_onboarded(self) -> None:
        manifest = load_function_harness_manifest()
        root = Path(__file__).resolve().parents[1]
        bindings = changed_scoped_function_bindings(
            root,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}
        answer_key = (
            "formowl_gateway.semantic",
            "SemanticMcpGateway._answer_mail_case_progress",
        )
        envelope_key = ("formowl_gateway.semantic", "_safe_handler_envelope")
        mail_success = (
            "tests.test_mail_evidence_mcp_gateway.MailEvidenceMcpGatewayTests."
            "test_semantic_gateway_exposes_mail_case_progress_tool_with_safe_handler"
        )
        dispatcher_coroutine = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_dispatcher_closes_coroutine_returned_by_sync_configured_handler_"
            "without_warning"
        )
        dispatcher_non_mapping = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_dispatcher_rejects_non_mapping_payloads_from_sync_configured_handler_"
            "without_partial_state"
        )
        dispatcher_nested_coroutine = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_dispatcher_closes_nested_coroutine_from_sync_configured_handler_"
            "without_warning"
        )
        dispatcher_nested_custom = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_dispatcher_rejects_nested_custom_awaitable_without_custom_close_or_"
            "partial_state"
        )
        dispatcher_stateful_snapshot = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_dispatcher_uses_one_stateful_container_snapshot_without_coroutine_"
            "injection"
        )
        dispatcher_cycle_guard = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_dispatcher_rejects_cyclic_nested_coroutine_graph_without_partial_state"
        )
        dispatcher_finite_float = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_real_semantic_handler_finite_float_result_is_canonical_success"
        )
        dispatcher_non_finite_float = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_real_semantic_handler_non_finite_result_cannot_leave_false_success_log"
        )
        handler_stateful_snapshot = (
            "tests.test_semantic_mcp_gateway.SemanticMcpGatewayTests."
            "test_handler_payload_snapshot_reads_stateful_containers_once_before_mail_"
            "validation"
        )
        hostile_iteration = (
            "tests.test_semantic_mcp_gateway.SemanticMcpGatewayTests."
            "test_handler_payload_snapshot_wraps_hostile_iteration_and_closes_yielded_"
            "coroutines"
        )
        mail_coroutine = (
            "tests.test_semantic_mcp_gateway.SemanticMcpGatewayTests."
            "test_mail_case_progress_sync_handler_coroutine_is_closed_before_claim_"
            "validation"
        )
        mail_nested_coroutine = (
            "tests.test_semantic_mcp_gateway.SemanticMcpGatewayTests."
            "test_mail_case_progress_nested_coroutine_is_closed_before_claim_validation"
        )
        nested_lifecycle_boundary = (
            "tests.test_semantic_mcp_gateway.SemanticMcpGatewayTests."
            "test_nested_custom_and_started_awaitables_are_rejected_without_lifecycle_"
            "mutation"
        )
        recursive_cycle_guard = (
            "tests.test_semantic_mcp_gateway.SemanticMcpGatewayTests."
            "test_recursive_handler_payload_guard_rejects_cycles_and_closes_every_"
            "created_coroutine"
        )
        expected = {
            answer_key: {
                "success": {handler_stateful_snapshot, mail_success},
                "invalid_or_protocol": {
                    handler_stateful_snapshot,
                    mail_success,
                    mail_coroutine,
                    mail_nested_coroutine,
                    recursive_cycle_guard,
                },
                "expiry_replay_or_revocation": set(),
                "rollback_or_no_partial_state": {
                    handler_stateful_snapshot,
                    mail_coroutine,
                    mail_nested_coroutine,
                    recursive_cycle_guard,
                },
                "audit_lineage": set(),
                "leak_safety": {
                    handler_stateful_snapshot,
                    mail_success,
                    mail_coroutine,
                    mail_nested_coroutine,
                    recursive_cycle_guard,
                },
                "remote_http": set(),
            },
            envelope_key: {
                "success": {
                    dispatcher_finite_float,
                    dispatcher_stateful_snapshot,
                    handler_stateful_snapshot,
                    mail_success,
                },
                "invalid_or_protocol": {
                    dispatcher_coroutine,
                    dispatcher_cycle_guard,
                    dispatcher_nested_coroutine,
                    dispatcher_nested_custom,
                    dispatcher_non_mapping,
                    dispatcher_non_finite_float,
                    dispatcher_stateful_snapshot,
                    handler_stateful_snapshot,
                    hostile_iteration,
                    mail_coroutine,
                    mail_nested_coroutine,
                    nested_lifecycle_boundary,
                    recursive_cycle_guard,
                },
                "expiry_replay_or_revocation": set(),
                "rollback_or_no_partial_state": set(),
                "audit_lineage": {
                    dispatcher_coroutine,
                    dispatcher_cycle_guard,
                    dispatcher_nested_coroutine,
                    dispatcher_nested_custom,
                    dispatcher_non_mapping,
                    dispatcher_non_finite_float,
                    dispatcher_stateful_snapshot,
                },
                "leak_safety": {
                    dispatcher_coroutine,
                    dispatcher_cycle_guard,
                    dispatcher_nested_coroutine,
                    dispatcher_nested_custom,
                    dispatcher_non_mapping,
                    dispatcher_non_finite_float,
                    dispatcher_stateful_snapshot,
                    handler_stateful_snapshot,
                    hostile_iteration,
                    mail_coroutine,
                    mail_nested_coroutine,
                    nested_lifecycle_boundary,
                    recursive_cycle_guard,
                },
                "remote_http": {
                    dispatcher_finite_float,
                    dispatcher_non_finite_float,
                },
            },
        }
        expected_na_reasons = {
            (
                answer_key,
                "expiry_replay_or_revocation",
            ): (
                "formowl_gateway.semantic.SemanticMcpGateway._answer_mail_case_progress "
                "does not own expiry, replay, or revocation decisions; it adapts one "
                "already-authorized handler result and owns no token or grant lifecycle "
                "state."
            ),
            (
                answer_key,
                "audit_lineage",
            ): (
                "formowl_gateway.semantic.SemanticMcpGateway._answer_mail_case_progress "
                "does not emit audit or persist audit lineage; connected authorization "
                "decision audit emission is owned by RemoteMcpDispatcher before semantic "
                "dispatch."
            ),
            (
                answer_key,
                "remote_http",
            ): (
                "formowl_gateway.semantic.SemanticMcpGateway._answer_mail_case_progress "
                "does not perform HTTP and is not an HTTP boundary; the current connected "
                "tool policy omits this tool, so no truthful remote execution path exists "
                "in this slice."
            ),
            (
                envelope_key,
                "expiry_replay_or_revocation",
            ): (
                "formowl_gateway.semantic._safe_handler_envelope validates an in-memory "
                "handler payload; it does not own expiry, replay, or revocation state "
                "because token-session lifecycle is resolved before semantic dispatch."
            ),
            (
                envelope_key,
                "rollback_or_no_partial_state",
            ): (
                "formowl_gateway.semantic._safe_handler_envelope performs no durable "
                "write and does not open a transaction; it validates and detaches a "
                "handler result only after the configured handler returns. Because it "
                "receives no repository, unit of work, or rollback callback, each "
                "stateful handler must own and test its transaction and "
                "no-partial-business-state boundary separately."
            ),
        }
        collected = collect_unittest_test_ids(Path(__file__).resolve().parent)

        self.assertEqual(set(expected), {answer_key, envelope_key})
        for key, expected_categories in expected.items():
            with self.subTest(function_key=key):
                entry = entries[key]
                self.assertEqual(entry["status"], "onboarded")
                self.assertEqual(entry["source_binding"], bindings[key])
                self.assertEqual(set(entry["categories"]), set(REQUIRED_HARNESS_CATEGORIES))
                category_test_union: set[str] = set()
                for category in REQUIRED_HARNESS_CATEGORIES:
                    evidence = entry["categories"][category]
                    category_tests = set(evidence["test_ids"])
                    category_test_union.update(category_tests)
                    self.assertEqual(category_tests, expected_categories[category])
                    self.assertTrue(category_tests.issubset(collected))
                    self.assertIn(evidence["pending_reason"], (None, ""))
                    if category_tests:
                        self.assertIn(evidence["not_applicable_reason"], (None, ""))
                    else:
                        self.assertEqual(
                            evidence["not_applicable_reason"],
                            expected_na_reasons[(key, category)],
                        )
                self.assertEqual(category_test_union, set(entry["test_ids"]))

    def test_callback_transaction_binding_hardening_is_manifest_onboarded(self) -> None:
        manifest = load_function_harness_manifest()
        client_state_test = (
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_callback_client_state_decryption_failures_leave_repository_byte_identical"
        )
        initial_binding_test = (
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_callback_rejects_initial_transaction_config_binding_mismatches_before_google"
        )
        locked_binding_test = (
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_callback_rejects_every_locked_transaction_immutable_field_change_atomically"
        )
        http_binding_test = (
            "tests.test_oauth_http_routes.OAuthHttpRouteTests."
            "test_callback_transaction_binding_mismatch_is_generic_and_no_write"
        )
        entry = next(
            item
            for item in manifest["functions"]
            if item["module"] == "formowl_auth.service"
            and item["qualname"] == "FormOwlOAuthBridge.complete_google_callback"
        )

        for test_id in (
            client_state_test,
            initial_binding_test,
            locked_binding_test,
            http_binding_test,
        ):
            self.assertIn(test_id, entry["test_ids"])
        for category in (
            "invalid_or_protocol",
            "rollback_or_no_partial_state",
        ):
            self.assertTrue(
                {
                    client_state_test,
                    initial_binding_test,
                    locked_binding_test,
                    http_binding_test,
                }.issubset(entry["categories"][category]["test_ids"])
            )
        for category in ("audit_lineage", "leak_safety"):
            self.assertTrue(
                {
                    initial_binding_test,
                    locked_binding_test,
                    http_binding_test,
                }.issubset(entry["categories"][category]["test_ids"])
            )
        self.assertIn(
            http_binding_test,
            entry["categories"]["remote_http"]["test_ids"],
        )
        self.assertTrue(
            {
                client_state_test,
                initial_binding_test,
                locked_binding_test,
                http_binding_test,
            }.issubset(collect_unittest_test_ids(Path(__file__).resolve().parent))
        )

    def test_service_leak_safety_na_reasons_match_real_data_semantics(self) -> None:
        manifest = load_function_harness_manifest()
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}
        expected_reasons = {
            "FormOwlOAuthBridge.__init__": (
                "formowl_auth.service.FormOwlOAuthBridge.__init__ accepts secret-bearing "
                "OAuthBridgeConfig and token-codec dependencies, but only stores those "
                "injected objects on the bridge; it performs no serialization, logging, "
                "audit emission, or public response and returns no caller-visible data."
            ),
            "FormOwlOAuthBridge._validate_pending_transaction": (
                "formowl_auth.service.FormOwlOAuthBridge._validate_pending_transaction "
                "receives an OAuthTransaction containing encrypted client state and hashed "
                "state and nonce values, but only checks pending status, consumption, and "
                "expiry and raises fixed reason codes; it does not serialize, log, audit, "
                "or return transaction material, so it returns no caller-visible data on "
                "success."
            ),
            "_iso": (
                "formowl_auth.service._iso is a timestamp-only datetime-to-ISO "
                "transformation; it receives no arbitrary payload, performs no logging or "
                "public-envelope construction, and cannot expose a raw path or "
                "secret-bearing object through its ISO timestamp result."
            ),
            "_parse_iso": (
                "formowl_auth.service._parse_iso is a timestamp-only ISO-to-datetime "
                "parser; it does not inspect arbitrary payload fields, log input, or build "
                "public envelopes, and cannot expose a raw path or secret-bearing object "
                "through its datetime result."
            ),
            "_require_aware": (
                "formowl_auth.service._require_aware only validates timezone awareness and "
                "returns None on success; it does not serialize values, log data, emit "
                "audit records, or construct a public envelope, so it returns no "
                "caller-visible data."
            ),
        }
        forbidden_phrases = (
            "does not receive secret material",
            "returns only a fixed public shape",
        )

        for qualname, expected_reason in expected_reasons.items():
            with self.subTest(qualname=qualname):
                entry = entries[("formowl_auth.service", qualname)]
                evidence = entry["categories"]["leak_safety"]
                reason = evidence["not_applicable_reason"]
                self.assertEqual(reason, expected_reason)
                self.assertEqual(evidence["test_ids"], [])
                self.assertIn(evidence["pending_reason"], (None, ""))
                self.assertGreaterEqual(len(reason), 80)
                self.assertLessEqual(len(reason), 700)
                for forbidden_phrase in forbidden_phrases:
                    self.assertNotIn(forbidden_phrase, reason)

    def test_internal_oauth_record_closed_schema_slice_is_manifest_onboarded(
        self,
    ) -> None:
        manifest = load_function_harness_manifest()
        root = Path(__file__).resolve().parents[1]
        bindings = changed_scoped_function_bindings(
            root,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}
        qualnames = {
            "ExternalIdentity.from_dict",
            "OAuthInvitation.from_dict",
            "OAuthClientAuthorization.from_dict",
            "OAuthTransaction.from_dict",
            "OAuthAuthorizationCode.from_dict",
            "OAuthTokenSession.from_dict",
            "_validate_external_identity",
            "_validate_invitation",
            "_validate_client_authorization",
            "_validate_transaction",
            "_validate_authorization_code",
            "_validate_token_session",
            "_validate_scopes",
        }
        keys = {("formowl_auth.models", qualname) for qualname in qualnames}
        success_test = (
            "tests.test_oauth_contracts_and_security.OAuthContractsAndSecurityTests."
            "test_internal_oauth_records_round_trip_and_keep_workspace_server_side"
        )
        invalid_test = (
            "tests.test_oauth_contracts_and_security.OAuthContractsAndSecurityTests."
            "test_internal_oauth_record_decoders_reject_unknown_fields_without_leak_or_"
            "construction"
        )
        scope_validation_test = (
            "tests.test_oauth_contracts_and_security.OAuthContractsAndSecurityTests."
            "test_scope_bearing_oauth_decoders_reject_unhashable_items_without_leak_or_"
            "mutation"
        )
        scope_helper_success_test = (
            "tests.test_oauth_contracts_and_security.OAuthContractsAndSecurityTests."
            "test_validate_scopes_accepts_non_empty_unique_list_and_tuple"
        )
        scope_validation_qualnames = {
            "OAuthClientAuthorization.from_dict",
            "OAuthTransaction.from_dict",
            "OAuthAuthorizationCode.from_dict",
            "OAuthTokenSession.from_dict",
            "_validate_client_authorization",
            "_validate_transaction",
            "_validate_authorization_code",
            "_validate_token_session",
            "_validate_scopes",
        }
        expected = {
            "success": {success_test},
            "invalid_or_protocol": {invalid_test},
            "expiry_replay_or_revocation": set(),
            "rollback_or_no_partial_state": set(),
            "audit_lineage": set(),
            "leak_safety": {invalid_test},
            "remote_http": set(),
        }
        collected = collect_unittest_test_ids(Path(__file__).resolve().parent)

        self.assertEqual(len(keys), 13)
        self.assertTrue(
            {
                success_test,
                invalid_test,
                scope_validation_test,
                scope_helper_success_test,
            }.issubset(collected)
        )
        for key in sorted(keys):
            with self.subTest(function_key=key):
                entry = entries[key]
                expected_for_entry = {
                    category: set(test_ids) for category, test_ids in expected.items()
                }
                if key[1] in scope_validation_qualnames:
                    expected_for_entry["invalid_or_protocol"].add(scope_validation_test)
                    expected_for_entry["rollback_or_no_partial_state"].add(scope_validation_test)
                    expected_for_entry["leak_safety"].add(scope_validation_test)
                if key[1] == "_validate_scopes":
                    expected_for_entry["success"] = {scope_helper_success_test}
                    expected_for_entry["invalid_or_protocol"].discard(invalid_test)
                    expected_for_entry["leak_safety"].discard(invalid_test)
                self.assertEqual(entry["status"], "onboarded")
                self.assertEqual(entry["source_binding"], bindings[key])
                self.assertEqual(set(entry["categories"]), set(REQUIRED_HARNESS_CATEGORIES))
                for category in REQUIRED_HARNESS_CATEGORIES:
                    evidence = entry["categories"][category]
                    self.assertEqual(set(evidence["test_ids"]), expected_for_entry[category])
                    self.assertIn(evidence["pending_reason"], (None, ""))
                    if expected_for_entry[category]:
                        self.assertIn(evidence["not_applicable_reason"], (None, ""))
                    else:
                        self.assertIsInstance(evidence["not_applicable_reason"], str)
                        self.assertTrue(evidence["not_applicable_reason"].strip())
                expected_test_ids = set().union(*expected_for_entry.values())
                self.assertEqual(set(entry["test_ids"]), expected_test_ids)

        owner_counts = {
            test_id: sum(test_id in entry["test_ids"] for entry in manifest["functions"])
            for test_id in (
                success_test,
                invalid_test,
                scope_validation_test,
                scope_helper_success_test,
            )
        }
        self.assertEqual(
            owner_counts,
            {
                success_test: 12,
                invalid_test: 12,
                scope_validation_test: 9,
                scope_helper_success_test: 1,
            },
        )

    def test_google_authorization_denial_flow_is_manifest_onboarded(self) -> None:
        manifest = load_function_harness_manifest()
        collected = collect_unittest_test_ids(Path(__file__).resolve().parent)
        service_success = (
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_google_authorization_denial_fails_transaction_and_preserves_identity_state"
        )
        service_atomic = (
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_google_authorization_denial_replay_invalid_state_and_write_failures_are_atomic"
        )
        http_success = (
            "tests.test_oauth_http_routes.OAuthHttpRouteTests."
            "test_google_authorization_denial_redirects_generic_error_and_ignores_upstream_detail"
        )
        http_invalid = (
            "tests.test_oauth_http_routes.OAuthHttpRouteTests."
            "test_google_authorization_denial_invalid_shapes_fail_closed_without_redirect"
        )
        http_rollback = (
            "tests.test_oauth_http_routes.OAuthHttpRouteTests."
            "test_google_authorization_denial_write_failures_return_generic_500_and_roll_back"
        )
        postgres_test = (
            "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
            "test_fail_transaction_is_parameterized_and_only_consumes_pending_state"
        )
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}
        expected = {
            (
                "formowl_auth.service",
                "FormOwlOAuthBridge.complete_google_denial",
            ): {service_success, service_atomic, http_success, http_invalid, http_rollback},
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.fail_transaction",
            ): {postgres_test},
            ("formowl_auth.http", "oauth_routes"): {
                http_success,
                http_invalid,
                http_rollback,
            },
            (
                "formowl_auth.http",
                "oauth_routes.<locals>.google_callback_endpoint",
            ): {http_success, http_invalid, http_rollback},
        }

        for function_key, test_ids in expected.items():
            with self.subTest(function_key=function_key):
                self.assertTrue(test_ids.issubset(entries[function_key]["test_ids"]))
                self.assertTrue(test_ids.issubset(collected))

    def test_first_owner_bootstrap_flow_is_manifest_onboarded(self) -> None:
        manifest = load_function_harness_manifest()
        collected = collect_unittest_test_ids(Path(__file__).resolve().parent)
        contract_test = (
            "tests.test_oauth_contracts_and_security.OAuthContractsAndSecurityTests."
            "test_owner_bootstrap_and_service_audit_contracts_are_explicit"
        )
        service_success = (
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_owner_bootstrap_is_atomic_idempotent_and_creates_no_fake_user"
        )
        service_rejection = (
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_owner_bootstrap_rejects_nonempty_conflicts_and_rolls_back_every_write"
        )
        service_login = (
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_bootstrapped_owner_google_login_creates_real_user_and_completes_bootstrap"
        )
        service_completion_rollback = (
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_bootstrap_completion_write_failure_rolls_back_google_identity_atomically"
        )
        service_invalid_state = (
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_bootstrap_login_rejects_incompatible_state_without_partial_identity"
        )
        postgres_test = (
            "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
            "test_owner_bootstrap_sql_uses_unique_upsert_row_locks_and_parameters"
        )
        psycopg_test = (
            "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
            "test_psycopg_adapter_uses_parameters_and_maps_rows"
        )
        http_non_exposure = (
            "tests.test_oauth_http_routes.OAuthHttpRouteTests."
            "test_route_set_metadata_jwks_and_urls_are_exact_and_host_independent"
        )
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}
        expected = {
            ("formowl_contract.models", "AuditLog.from_dict"): {contract_test},
            ("formowl_contract.models", "validate_audit_log"): {contract_test},
            ("formowl_auth.audit", "write_audit_log"): {contract_test},
            ("formowl_auth.audit", "write_oauth_audit_event"): {contract_test},
            ("formowl_auth.models", "OAuthOwnerBootstrap.to_dict"): {contract_test},
            ("formowl_auth.models", "OAuthOwnerBootstrap.from_dict"): {contract_test},
            ("formowl_auth.models", "_validate_owner_bootstrap"): {contract_test},
            (
                "formowl_auth.service",
                "FormOwlOAuthBridge.bootstrap_owner_invitation",
            ): {
                service_success,
                service_rejection,
                service_login,
                service_completion_rollback,
                http_non_exposure,
            },
            (
                "formowl_auth.service",
                "FormOwlOAuthBridge._resolve_or_bind_identity",
            ): {service_login, service_completion_rollback, service_invalid_state},
            ("formowl_auth.postgres", "PsycopgOAuthConnection.execute"): {
                psycopg_test,
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.count_active_workspace_members",
            ): {service_rejection, postgres_test},
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_invitation",
            ): {service_success, service_login, postgres_test},
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.find_pending_owner_invitations",
            ): {service_rejection, postgres_test},
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.upsert_owner_bootstrap",
            ): {service_success, service_rejection, postgres_test},
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_owner_bootstrap",
            ): {service_success, service_login, postgres_test},
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_owner_bootstrap_by_invitation",
            ): {service_login, postgres_test},
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.complete_owner_bootstrap",
            ): {service_login, service_completion_rollback, postgres_test},
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.append_audit_log",
            ): {contract_test, service_success, service_rejection, postgres_test},
        }

        for function_key, test_ids in expected.items():
            with self.subTest(function_key=function_key):
                self.assertTrue(test_ids.issubset(entries[function_key]["test_ids"]))
                self.assertTrue(test_ids.issubset(collected))

    def test_server_side_binding_hardening_is_manifest_onboarded(self) -> None:
        manifest = load_function_harness_manifest()
        collected = collect_unittest_test_ids(Path(__file__).resolve().parent)
        binding_test = (
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_client_authorization_binding_is_revalidated_for_token_and_actor_context"
        )
        code_test = (
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_code_exchange_rejects_each_misbound_authorization_field_atomically"
        )
        identity_test = (
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_external_identity_user_and_google_issuer_binding_is_revalidated"
        )
        session_test = (
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_token_session_ids_are_bound_to_jwt_principal_and_authorization"
        )
        expected = {
            "FormOwlOAuthBridge.exchange_authorization_code": {code_test, identity_test},
            "FormOwlOAuthBridge.authenticate_access_token": {
                binding_test,
                identity_test,
                session_test,
            },
            "FormOwlOAuthBridge.resolve_actor_context": {
                binding_test,
                identity_test,
                session_test,
            },
            "FormOwlOAuthBridge._validate_client_authorization": {
                binding_test,
                code_test,
                identity_test,
                session_test,
            },
            "FormOwlOAuthBridge._validate_live_token_session": {
                binding_test,
                session_test,
            },
            "FormOwlOAuthBridge._validate_principal_session": {
                binding_test,
                session_test,
            },
        }
        entries = {
            item["qualname"]: item
            for item in manifest["functions"]
            if item["module"] == "formowl_auth.service"
        }

        for qualname, test_ids in expected.items():
            with self.subTest(qualname=qualname):
                self.assertTrue(test_ids.issubset(entries[qualname]["test_ids"]))
                self.assertTrue(test_ids.issubset(collected))

    def test_revocation_authority_hardening_is_manifest_onboarded(self) -> None:
        manifest = load_function_harness_manifest()
        entry = next(
            item
            for item in manifest["functions"]
            if item["module"] == "formowl_auth.service"
            and item["qualname"] == "FormOwlOAuthBridge.revoke_token_session"
        )
        expected = {
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_revocation_authority_allows_self_and_current_workspace_owner_with_audit",
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_revocation_authority_denies_nonowners_removed_and_disabled_without_writes",
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_revocation_missing_replay_and_audit_failure_are_atomic",
        }

        self.assertTrue(expected.issubset(entry["test_ids"]))
        self.assertTrue(
            expected.issubset(collect_unittest_test_ids(Path(__file__).resolve().parent))
        )

    def test_temporal_claim_hardening_is_manifest_onboarded(self) -> None:
        manifest = load_function_harness_manifest()
        collected = collect_unittest_test_ids(Path(__file__).resolve().parent)
        formowl_test = (
            "tests.test_oauth_tokens_google.OAuthTokenAndGoogleTests."
            "test_formowl_temporal_claims_require_strict_integer_dates_and_valid_order"
        )
        google_test = (
            "tests.test_oauth_tokens_google.OAuthTokenAndGoogleTests."
            "test_google_temporal_claims_require_strict_integer_dates_and_valid_order"
        )
        callback_test = (
            "tests.test_oauth_tokens_google.OAuthTokenAndGoogleTests."
            "test_google_temporal_denial_precedes_callback_mutation"
        )
        expected = {
            ("formowl_auth.tokens", "FormOwlTokenCodec._validate_claims"): {formowl_test},
            ("formowl_auth.tokens", "_numeric_date"): {formowl_test},
            ("formowl_auth.google_oidc", "_validate_google_claims"): {
                google_test,
                callback_test,
            },
            ("formowl_auth.google_oidc", "_numeric_date"): {
                google_test,
                callback_test,
            },
        }
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}

        for function_key, test_ids in expected.items():
            with self.subTest(function_key=function_key):
                self.assertTrue(test_ids.issubset(entries[function_key]["test_ids"]))
                self.assertTrue(test_ids.issubset(collected))

    def test_canonical_config_route_hardening_is_manifest_onboarded(self) -> None:
        manifest = load_function_harness_manifest()
        entry = next(
            item
            for item in manifest["functions"]
            if item["module"] == "formowl_auth.config"
            and item["qualname"] == "_validate_endpoint_url"
        )
        expected = {
            "tests.test_oauth_config_routes.OAuthConfigRouteTests."
            "test_valid_production_and_explicit_loopback_configs",
            "tests.test_oauth_config_routes.OAuthConfigRouteTests."
            "test_invalid_url_and_clock_skew_matrix_leaves_repository_unchanged",
            "tests.test_oauth_config_routes.OAuthConfigRouteTests."
            "test_metadata_properties_and_starlette_routes_are_exact",
        }

        self.assertTrue(expected.issubset(entry["test_ids"]))
        self.assertTrue(
            expected.issubset(collect_unittest_test_ids(Path(__file__).resolve().parent))
        )
        self.assertEqual(
            tuple(manifest["scope"]["exclusion_rules"]),
            ISSUE20_FUNCTION_EXCLUSION_RULES,
        )

    def test_pkce_verifier_hardening_is_manifest_onboarded(self) -> None:
        manifest = load_function_harness_manifest()
        entry = next(
            item
            for item in manifest["functions"]
            if item["module"] == "formowl_auth.service"
            and item["qualname"] == "FormOwlOAuthBridge.exchange_authorization_code"
        )
        expected = {
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_pkce_verifier_matrix_fails_closed_before_code_consumption",
            "tests.test_oauth_http_routes.OAuthHttpRouteTests."
            "test_token_pkce_verifier_errors_are_safe_audited_and_atomic",
        }

        self.assertTrue(expected.issubset(entry["test_ids"]))
        self.assertTrue(
            expected.issubset(collect_unittest_test_ids(Path(__file__).resolve().parent))
        )

    def test_token_exchange_membership_lock_is_manifest_onboarded(self) -> None:
        manifest = load_function_harness_manifest()
        root = Path(__file__).resolve().parents[1]
        key = (
            "formowl_auth.service",
            "FormOwlOAuthBridge.exchange_authorization_code",
        )
        entry = next(
            item for item in manifest["functions"] if (item["module"], item["qualname"]) == key
        )
        test_id = (
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_token_exchange_locks_membership_before_session_issuance"
        )
        bindings = changed_scoped_function_bindings(
            root,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )

        self.assertEqual(entry["source_binding"], bindings[key])
        self.assertIn(test_id, entry["categories"]["success"]["test_ids"])
        self.assertIn(
            test_id,
            entry["categories"]["rollback_or_no_partial_state"]["test_ids"],
        )
        self.assertIn(test_id, entry["test_ids"])
        self.assertIn(test_id, collect_unittest_test_ids(root / "tests"))

    def test_membership_removal_restore_lifecycle_is_manifest_onboarded(self) -> None:
        manifest = load_function_harness_manifest()
        collected = collect_unittest_test_ids(Path(__file__).resolve().parent)
        repository_test = (
            "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
            "test_membership_lifecycle_queries_lock_rows_and_mutations_are_parameterized"
        )
        lifecycle_test = (
            "tests.test_connected_operator_directory.ConnectedOperatorDirectoryTests."
            "test_membership_removal_revokes_sessions_and_restore_keeps_them_revoked"
        )
        denial_test = (
            "tests.test_connected_operator_directory.ConnectedOperatorDirectoryTests."
            "test_membership_removal_denials_are_audited_without_mutation"
        )
        rollback_test = (
            "tests.test_connected_operator_directory.ConnectedOperatorDirectoryTests."
            "test_membership_mutation_rolls_back_when_audit_write_fails"
        )
        relink_test = (
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_operator_membership_removal_survives_restart_and_requires_relink"
        )
        validator_test = (
            "tests.test_oauth_contracts_and_security.OAuthContractsAndSecurityTests."
            "test_generic_audit_metadata_rejects_secret_variants_without_write_or_echo"
        )
        repository_keys = {
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.remove_workspace_member",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.restore_workspace_member",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.revoke_active_token_sessions_for_membership",
            ),
        }
        operator_keys = {
            (
                "formowl_gateway.operator",
                "OperatorDirectory._remove_workspace_member_result",
            ),
            (
                "formowl_gateway.operator",
                "OperatorDirectory._restore_workspace_member_result",
            ),
            (
                "formowl_gateway.operator",
                "OperatorDirectory.remove_workspace_member",
            ),
            (
                "formowl_gateway.operator",
                "OperatorDirectory.restore_workspace_member",
            ),
        }
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}

        validator_entry = entries[("formowl_contract.models", "_validate_audit_metadata")]
        self.assertEqual(validator_entry["status"], "onboarded")
        self.assertIn(validator_test, validator_entry["test_ids"])
        for key in repository_keys:
            with self.subTest(key=key):
                self.assertEqual(entries[key]["status"], "onboarded")
                self.assertIn(repository_test, entries[key]["test_ids"])
        for key in operator_keys:
            with self.subTest(key=key):
                self.assertEqual(entries[key]["status"], "onboarded")
                self.assertTrue(
                    {lifecycle_test, denial_test, rollback_test, relink_test}.issubset(
                        entries[key]["test_ids"]
                    )
                )
        self.assertTrue(
            {
                repository_test,
                lifecycle_test,
                denial_test,
                rollback_test,
                relink_test,
                validator_test,
            }.issubset(collected)
        )

    def test_operator_directory_pending_batch_is_manifest_onboarded(self) -> None:
        manifest = load_function_harness_manifest()
        root = Path(__file__).resolve().parents[1]
        bindings = changed_scoped_function_bindings(
            root,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}
        pending_qualnames = {
            "OperatorDirectory.__init__",
            "OperatorDirectory._active_token_sessions",
            "OperatorDirectory._audit_log",
            "OperatorDirectory._audit_unauthorized",
            "OperatorDirectory._authorize",
            "OperatorDirectory._execute_audited",
            "OperatorDirectory._list_token_sessions_result",
            "OperatorDirectory._list_users_result",
            "OperatorDirectory._lookup_token_session_result",
            "OperatorDirectory._lookup_user_result",
            "OperatorDirectory.list_token_sessions",
            "OperatorDirectory.list_users",
            "OperatorDirectory.lookup_token_session",
            "OperatorDirectory.lookup_user",
            "OperatorDirectoryError.__init__",
            "_parse_timestamp",
            "_require_safe_identifier",
            "_safe_audit_target",
            "_safe_membership_target",
            "_safe_token_session_entry",
            "_safe_user_entry",
            "_utc_now",
        }
        already_onboarded_siblings = {
            "OperatorDirectory._remove_workspace_member_result",
            "OperatorDirectory._restore_workspace_member_result",
            "OperatorDirectory.remove_workspace_member",
            "OperatorDirectory.restore_workspace_member",
        }
        target_keys = {("formowl_gateway.operator", qualname) for qualname in pending_qualnames}
        sibling_keys = {
            ("formowl_gateway.operator", qualname) for qualname in already_onboarded_siblings
        }
        operator_keys = {key for key in entries if key[0] == "formowl_gateway.operator"}
        self.assertEqual(len(target_keys), 22)
        self.assertTrue(target_keys.isdisjoint(sibling_keys))
        self.assertEqual(operator_keys, target_keys | sibling_keys)
        self.assertTrue(target_keys.issubset(bindings))
        for key in sibling_keys:
            self.assertEqual(entries[key]["status"], "onboarded")

        user_success = (
            "tests.test_connected_operator_directory.ConnectedOperatorDirectoryTests."
            "test_user_lookup_and_list_return_only_active_stable_ids"
        )
        user_denial = (
            "tests.test_connected_operator_directory.ConnectedOperatorDirectoryTests."
            "test_user_lookup_rejects_unauthorized_invalid_disabled_and_ambiguous"
        )
        token_success = (
            "tests.test_connected_operator_directory.ConnectedOperatorDirectoryTests."
            "test_token_lookup_and_list_filter_inactive_without_sensitive_lineage"
        )
        token_denial = (
            "tests.test_connected_operator_directory.ConnectedOperatorDirectoryTests."
            "test_token_lookup_rejects_ambiguity_and_disabled_authorization_state"
        )
        safe_failures = (
            "tests.test_connected_operator_directory.ConnectedOperatorDirectoryTests."
            "test_backend_failure_and_invalid_identifiers_return_only_safe_codes"
        )
        timestamp_guard = (
            "tests.test_connected_operator_directory.ConnectedOperatorDirectoryTests."
            "test_token_lookup_rejects_naive_and_detached_now_without_state_change"
        )
        timezone_normalization = (
            "tests.test_connected_operator_directory.ConnectedOperatorDirectoryTests."
            "test_token_lookup_normalizes_non_utc_now_to_utc_output_and_audit"
        )
        utcoffset_failure = (
            "tests.test_connected_operator_directory.ConnectedOperatorDirectoryTests."
            "test_token_lookup_remaps_utcoffset_failure_without_state_change_or_leak"
        )
        astimezone_failure = (
            "tests.test_connected_operator_directory.ConnectedOperatorDirectoryTests."
            "test_token_lookup_remaps_astimezone_failure_without_state_change_or_leak"
        )
        membership_lifecycle = (
            "tests.test_connected_operator_directory.ConnectedOperatorDirectoryTests."
            "test_membership_removal_revokes_sessions_and_restore_keeps_them_revoked"
        )
        membership_denial = (
            "tests.test_connected_operator_directory.ConnectedOperatorDirectoryTests."
            "test_membership_removal_denials_are_audited_without_mutation"
        )
        membership_rollback = (
            "tests.test_connected_operator_directory.ConnectedOperatorDirectoryTests."
            "test_membership_mutation_rolls_back_when_audit_write_fails"
        )

        def categories(**evidence: set[str]) -> dict[str, set[str]]:
            expected = {category: set() for category in REQUIRED_HARNESS_CATEGORIES}
            expected.update(evidence)
            return expected

        expected = {
            ("formowl_gateway.operator", "OperatorDirectory.__init__"): categories(
                success={user_success},
            ),
            (
                "formowl_gateway.operator",
                "OperatorDirectory._active_token_sessions",
            ): categories(
                success={token_success},
                invalid_or_protocol={token_denial, safe_failures},
                expiry_replay_or_revocation={token_success, token_denial},
                leak_safety={token_success, safe_failures},
            ),
            ("formowl_gateway.operator", "OperatorDirectory._audit_log"): categories(
                success={user_success, token_success},
                audit_lineage={user_success, user_denial, token_success},
                leak_safety={safe_failures},
            ),
            (
                "formowl_gateway.operator",
                "OperatorDirectory._audit_unauthorized",
            ): categories(
                success={user_denial},
                invalid_or_protocol={user_denial, membership_denial},
                rollback_or_no_partial_state={membership_denial},
                audit_lineage={user_denial, membership_denial},
                leak_safety={user_denial, membership_denial},
            ),
            ("formowl_gateway.operator", "OperatorDirectory._authorize"): categories(
                success={user_success},
                invalid_or_protocol={user_denial},
                leak_safety={user_denial},
            ),
            (
                "formowl_gateway.operator",
                "OperatorDirectory._execute_audited",
            ): categories(
                success={user_success, token_success},
                invalid_or_protocol={user_denial, token_denial},
                expiry_replay_or_revocation={token_success, token_denial},
                rollback_or_no_partial_state={safe_failures, membership_rollback},
                audit_lineage={
                    user_success,
                    user_denial,
                    token_success,
                    token_denial,
                },
                leak_safety={safe_failures},
            ),
            (
                "formowl_gateway.operator",
                "OperatorDirectory._list_token_sessions_result",
            ): categories(
                success={token_success},
                invalid_or_protocol={token_denial, safe_failures},
                expiry_replay_or_revocation={token_success, token_denial},
                audit_lineage={token_success},
                leak_safety={token_success, safe_failures},
            ),
            (
                "formowl_gateway.operator",
                "OperatorDirectory._list_users_result",
            ): categories(
                success={user_success},
                invalid_or_protocol={safe_failures},
                audit_lineage={user_success},
                leak_safety={user_success, safe_failures},
            ),
            (
                "formowl_gateway.operator",
                "OperatorDirectory._lookup_token_session_result",
            ): categories(
                success={token_success, membership_lifecycle},
                invalid_or_protocol={token_denial},
                expiry_replay_or_revocation={
                    token_success,
                    token_denial,
                    membership_lifecycle,
                },
                audit_lineage={token_success},
                leak_safety={token_success, membership_lifecycle},
            ),
            (
                "formowl_gateway.operator",
                "OperatorDirectory._lookup_user_result",
            ): categories(
                success={user_success},
                invalid_or_protocol={user_denial},
                audit_lineage={user_success, user_denial},
                leak_safety={user_success, user_denial},
            ),
            (
                "formowl_gateway.operator",
                "OperatorDirectory.list_token_sessions",
            ): categories(
                success={token_success},
                invalid_or_protocol={token_denial, safe_failures},
                expiry_replay_or_revocation={token_success, token_denial},
                rollback_or_no_partial_state={safe_failures},
                audit_lineage={token_success, token_denial},
                leak_safety={token_success, safe_failures},
            ),
            ("formowl_gateway.operator", "OperatorDirectory.list_users"): categories(
                success={user_success},
                invalid_or_protocol={safe_failures},
                rollback_or_no_partial_state={safe_failures},
                audit_lineage={user_success, safe_failures},
                leak_safety={user_success, safe_failures},
            ),
            (
                "formowl_gateway.operator",
                "OperatorDirectory.lookup_token_session",
            ): categories(
                success={
                    token_success,
                    membership_lifecycle,
                    timezone_normalization,
                },
                invalid_or_protocol={
                    token_denial,
                    timestamp_guard,
                    utcoffset_failure,
                    astimezone_failure,
                },
                expiry_replay_or_revocation={
                    token_success,
                    token_denial,
                    membership_lifecycle,
                },
                rollback_or_no_partial_state={
                    timestamp_guard,
                    utcoffset_failure,
                    astimezone_failure,
                },
                audit_lineage={
                    token_success,
                    token_denial,
                    membership_lifecycle,
                    timezone_normalization,
                    utcoffset_failure,
                    astimezone_failure,
                },
                leak_safety={
                    token_success,
                    timestamp_guard,
                    membership_lifecycle,
                    utcoffset_failure,
                    astimezone_failure,
                },
            ),
            ("formowl_gateway.operator", "OperatorDirectory.lookup_user"): categories(
                success={user_success},
                invalid_or_protocol={user_denial},
                rollback_or_no_partial_state={user_denial},
                audit_lineage={user_success, user_denial},
                leak_safety={user_success, user_denial},
            ),
            (
                "formowl_gateway.operator",
                "OperatorDirectoryError.__init__",
            ): categories(
                success={user_denial},
                invalid_or_protocol={
                    user_denial,
                    timestamp_guard,
                    utcoffset_failure,
                    astimezone_failure,
                },
                leak_safety={
                    user_denial,
                    timestamp_guard,
                    utcoffset_failure,
                    astimezone_failure,
                },
            ),
            ("formowl_gateway.operator", "_parse_timestamp"): categories(
                success={token_success, membership_lifecycle},
                invalid_or_protocol={token_denial},
                expiry_replay_or_revocation={
                    token_success,
                    token_denial,
                    membership_lifecycle,
                },
                leak_safety={token_success, membership_lifecycle},
            ),
            ("formowl_gateway.operator", "_require_safe_identifier"): categories(
                success={user_success, token_success},
                invalid_or_protocol={safe_failures, membership_denial},
                leak_safety={safe_failures, membership_denial},
            ),
            ("formowl_gateway.operator", "_safe_audit_target"): categories(
                success={user_success, token_success},
                invalid_or_protocol={safe_failures},
                audit_lineage={user_denial, token_success},
                leak_safety={user_denial, safe_failures},
            ),
            ("formowl_gateway.operator", "_safe_membership_target"): categories(
                success={membership_lifecycle},
                invalid_or_protocol={membership_denial},
                audit_lineage={membership_lifecycle, membership_denial},
                leak_safety={membership_denial},
            ),
            ("formowl_gateway.operator", "_safe_token_session_entry"): categories(
                success={token_success, membership_lifecycle},
                leak_safety={token_success, membership_lifecycle},
            ),
            ("formowl_gateway.operator", "_safe_user_entry"): categories(
                success={user_success},
                leak_safety={user_success, safe_failures},
            ),
            ("formowl_gateway.operator", "_utc_now"): categories(
                success={
                    token_success,
                    membership_lifecycle,
                    timezone_normalization,
                },
                invalid_or_protocol={
                    timestamp_guard,
                    utcoffset_failure,
                    astimezone_failure,
                },
                rollback_or_no_partial_state={
                    timestamp_guard,
                    utcoffset_failure,
                    astimezone_failure,
                },
                audit_lineage={
                    timezone_normalization,
                    utcoffset_failure,
                    astimezone_failure,
                },
                leak_safety={
                    timestamp_guard,
                    utcoffset_failure,
                    astimezone_failure,
                },
            ),
        }
        self.assertEqual(set(expected), target_keys)

        n_a_templates = {
            "invalid_or_protocol": (
                "{identity} accepts no protocol input at this boundary; its arguments "
                "are internal collaborators, records, or machine values supplied by "
                "the surrounding operator workflow rather than parsed remote syntax."
            ),
            "expiry_replay_or_revocation": (
                "{identity} does not own expiry, replay, or revocation policy; it "
                "neither decides token-session lifecycle nor mutates revocation state "
                "inside this function."
            ),
            "rollback_or_no_partial_state": (
                "{identity} performs no durable write and mutates no repository state; "
                "transaction commit, rollback, and audit persistence are owned by the "
                "audited operator workflow or repository unit of work."
            ),
            "audit_lineage": (
                "{identity} does not emit audit or persist audit records; audit "
                "emission is owned by OperatorDirectory._execute_audited after this "
                "function returns its value, target metadata, or denial."
            ),
            "leak_safety": (
                "{identity} returns no caller-visible data; it only stores the injected "
                "repository reference and operator attribution identifier without "
                "reading or serializing repository records."
            ),
            "remote_http": (
                "{identity} runs below the HTTP boundary and does not perform HTTP; it "
                "owns no request routing, OAuth challenge, status, header, redirect, "
                "or response-body behavior."
            ),
        }
        n_a_overrides = {
            (
                "formowl_gateway.operator",
                "_utc_now",
                "audit_lineage",
            ): (
                "formowl_gateway.operator._utc_now has no audit side effect and does "
                "not emit audit records; public operator methods call it before "
                "OperatorDirectory._execute_audited, so an invalid timestamp fails "
                "before any audit transaction or lineage record."
            ),
        }
        collected = collect_unittest_test_ids(root / "tests")
        target_test_owners: dict[str, set[tuple[str, str]]] = {}
        for key in sorted(target_keys):
            with self.subTest(function_key=key):
                identity = ".".join(key)
                entry = entries[key]
                self.assertEqual(entry["status"], "onboarded")
                self.assertEqual(entry["source_binding"], bindings[key])
                self.assertEqual(
                    set(entry["categories"]),
                    set(REQUIRED_HARNESS_CATEGORIES),
                )
                category_union: set[str] = set()
                for category in REQUIRED_HARNESS_CATEGORIES:
                    evidence = entry["categories"][category]
                    test_ids = set(evidence["test_ids"])
                    self.assertEqual(test_ids, expected[key][category])
                    self.assertTrue(test_ids.issubset(collected))
                    self.assertIn(evidence["pending_reason"], (None, ""))
                    if test_ids:
                        self.assertIn(evidence["not_applicable_reason"], (None, ""))
                    else:
                        self.assertEqual(
                            evidence["not_applicable_reason"],
                            n_a_overrides.get(
                                (*key, category),
                                n_a_templates[category].format(identity=identity),
                            ),
                        )
                    category_union.update(test_ids)
                self.assertEqual(entry["test_ids"], sorted(category_union))
                for test_id in category_union:
                    target_test_owners.setdefault(test_id, set()).add(key)

        self.assertEqual(
            {test_id: len(owners) for test_id, owners in target_test_owners.items()},
            {
                astimezone_failure: 3,
                membership_denial: 3,
                membership_lifecycle: 6,
                membership_rollback: 1,
                safe_failures: 10,
                timestamp_guard: 3,
                timezone_normalization: 2,
                token_denial: 7,
                token_success: 12,
                user_denial: 8,
                user_success: 11,
                utcoffset_failure: 3,
            },
        )
        evidence_owners: dict[str, set[tuple[str, str]]] = {}
        for item in manifest["functions"]:
            key = (item["module"], item["qualname"])
            for test_id in item["test_ids"]:
                evidence_owners.setdefault(test_id, set()).add(key)
        self.assertLessEqual(max(map(len, evidence_owners.values())), 12)
        self.assert_batch_status_partition(manifest, target_keys)

    def test_connected_runtime_startup_secret_batch_is_manifest_onboarded(
        self,
    ) -> None:
        manifest = load_function_harness_manifest()
        root = Path(__file__).resolve().parents[1]
        bindings = changed_scoped_function_bindings(
            root,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}
        container_module = "formowl_gateway.container_entrypoint"
        secret_module = "formowl_gateway.secret_init"
        container_qualnames = {
            "ContainerEntrypointError.__init__",
            "_drop_privileges",
            "_expected_source_path",
            "_prepare_staging_root",
            "_read_secret",
            "_requires_connected_secrets",
            "_resolved_command",
            "_source_path",
            "_stage_signing_manifest",
            "_write_staged_secret",
            "main",
            "stage_configured_secrets",
        }
        secret_qualnames = {
            "SecretInitializationError.__init__",
            "_acquire_initialization_lock",
            "_build_postgres_dsn",
            "_generate_private_key_pem",
            "_initialization_contract_hash",
            "_prepare_secret_payloads",
            "_public_key_numbers",
            "_quarantine_partial_secret_set",
            "_validate_existing_secret_set",
            "_validate_initialization_arguments",
            "_validate_postgres_dsn",
            "_write_new_secret_set",
            "initialize_connected_secrets",
        }
        target_keys = {
            *((container_module, qualname) for qualname in container_qualnames),
            *((secret_module, qualname) for qualname in secret_qualnames),
        }
        self.assertEqual(len(target_keys), 25)
        self.assertEqual(
            {key for key in entries if key[0] in {container_module, secret_module}},
            target_keys,
        )
        self.assertTrue(target_keys.issubset(bindings))

        command_gating = (
            "tests.test_connected_container_entrypoint.ConnectedContainerEntrypointTests."
            "test_command_gating_keeps_init_secrets_direct_and_connected_commands_staged"
        )
        manifest_rollback = (
            "tests.test_connected_container_entrypoint.ConnectedContainerEntrypointTests."
            "test_late_invalid_signing_manifest_rolls_back_stage_and_environment"
        )
        partial_staged_write = (
            "tests.test_connected_container_entrypoint.ConnectedContainerEntrypointTests."
            "test_partial_staged_secret_write_is_removed"
        )
        privilege_drop = (
            "tests.test_connected_container_entrypoint.ConnectedContainerEntrypointTests."
            "test_privilege_drop_verifies_uid_groups_caps_no_new_privs_and_no_regain"
        )
        privilege_drop_control = (
            "tests.test_connected_container_entrypoint.ConnectedContainerEntrypointTests."
            "test_capability_probe_control_noops_only_bounding_drop_and_fails_closed"
        )
        privilege_drop_failure = (
            "tests.test_connected_container_entrypoint.ConnectedContainerEntrypointTests."
            "test_privilege_drop_bounding_set_failure_is_generic_and_stops_before_uid_drop"
        )
        privilege_drop_verification = (
            "tests.test_connected_container_entrypoint.ConnectedContainerEntrypointTests."
            "test_privilege_drop_rejects_nonzero_bounding_or_ambient_capabilities"
        )
        main_success = (
            "tests.test_connected_container_entrypoint.ConnectedContainerEntrypointTests."
            "test_main_root_connected_serve_stages_drops_and_execs_with_rewritten_environment"
        )
        public_failure = (
            "tests.test_connected_container_entrypoint.ConnectedContainerEntrypointTests."
            "test_public_failure_is_bounded"
        )
        ownership_rollback = (
            "tests.test_connected_container_entrypoint.ConnectedContainerEntrypointTests."
            "test_public_final_ownership_failure_rolls_back_and_retry_succeeds"
        )
        public_partial_write = (
            "tests.test_connected_container_entrypoint.ConnectedContainerEntrypointTests."
            "test_public_partial_write_failure_rolls_back_and_retry_succeeds"
        )
        invalid_sources = (
            "tests.test_connected_container_entrypoint.ConnectedContainerEntrypointTests."
            "test_rejects_symlink_path_escape_unknown_and_duplicate_manifest_keys"
        )
        staged_mode_order = (
            "tests.test_connected_container_entrypoint.ConnectedContainerEntrypointTests."
            "test_staged_file_mode_is_fixed_before_ownership_changes"
        )
        stage_success = (
            "tests.test_connected_container_entrypoint.ConnectedContainerEntrypointTests."
            "test_stages_0400_secrets_and_rewrites_only_allowed_signing_paths"
        )
        source_close_failure = (
            "tests.test_connected_container_entrypoint.ConnectedContainerEntrypointTests."
            "test_source_descriptor_close_failure_is_safe_rollback_and_retry_succeeds"
        )
        secret_cli = (
            "tests.test_connected_secret_init.ConnectedSecretInitializationTests."
            "test_cli_bypasses_runtime_secrets_and_never_prints_generated_values_or_path"
        )
        secret_create = (
            "tests.test_connected_secret_init.ConnectedSecretInitializationTests."
            "test_create_and_rerun_are_atomic_minimal_and_secret_free"
        )
        secret_publish_rollback = (
            "tests.test_connected_secret_init.ConnectedSecretInitializationTests."
            "test_injected_publish_failure_removes_every_new_target"
        )
        invalid_complete_set = (
            "tests.test_connected_secret_init.ConnectedSecretInitializationTests."
            "test_invalid_dsn_manifest_and_key_fail_without_overwrite_then_retry"
        )
        invalid_postgres_shape = (
            "tests.test_connected_secret_init.ConnectedSecretInitializationTests."
            "test_invalid_postgres_shape_fails_before_creating_secret_files"
        )
        lock_contention = (
            "tests.test_connected_secret_init.ConnectedSecretInitializationTests."
            "test_lock_contention_is_safe_and_retry_succeeds"
        )
        partial_recovery = (
            "tests.test_connected_secret_init.ConnectedSecretInitializationTests."
            "test_partial_invalid_and_conflicting_sets_fail_without_overwrite"
        )
        quarantine_rollback = (
            "tests.test_connected_secret_init.ConnectedSecretInitializationTests."
            "test_recovery_quarantine_failure_restores_original_entries_and_retry_succeeds"
        )
        quarantine_rollback_incomplete = (
            "tests.test_connected_secret_init.ConnectedSecretInitializationTests."
            "test_recovery_rollback_failure_preserves_operator_entries_and_retry_succeeds"
        )

        def categories(**evidence: set[str]) -> dict[str, set[str]]:
            expected = {category: set() for category in REQUIRED_HARNESS_CATEGORIES}
            expected.update(evidence)
            return expected

        expected = {
            (container_module, "ContainerEntrypointError.__init__"): categories(
                success={public_failure},
                invalid_or_protocol={public_failure},
                leak_safety={public_failure},
            ),
            (container_module, "_drop_privileges"): categories(
                success={privilege_drop},
                invalid_or_protocol={
                    privilege_drop_control,
                    privilege_drop_failure,
                    privilege_drop_verification,
                },
                rollback_or_no_partial_state={privilege_drop_failure},
                leak_safety={privilege_drop_failure},
            ),
            (container_module, "_expected_source_path"): categories(
                success={stage_success},
                invalid_or_protocol={invalid_sources},
                leak_safety={invalid_sources},
            ),
            (container_module, "_prepare_staging_root"): categories(
                success={stage_success},
                rollback_or_no_partial_state={manifest_rollback},
            ),
            (container_module, "_read_secret"): categories(
                success={stage_success},
                invalid_or_protocol={invalid_sources},
                leak_safety={invalid_sources, source_close_failure},
            ),
            (container_module, "_requires_connected_secrets"): categories(
                success={command_gating},
                invalid_or_protocol={command_gating},
            ),
            (container_module, "_resolved_command"): categories(
                success={command_gating},
                invalid_or_protocol={command_gating},
            ),
            (container_module, "_source_path"): categories(
                success={stage_success},
                invalid_or_protocol={invalid_sources},
                leak_safety={invalid_sources},
            ),
            (container_module, "_stage_signing_manifest"): categories(
                success={stage_success},
                invalid_or_protocol={manifest_rollback},
                expiry_replay_or_revocation={stage_success},
                rollback_or_no_partial_state={manifest_rollback},
                leak_safety={manifest_rollback},
            ),
            (container_module, "_write_staged_secret"): categories(
                success={staged_mode_order},
                invalid_or_protocol={partial_staged_write},
                rollback_or_no_partial_state={partial_staged_write},
                leak_safety={partial_staged_write},
            ),
            (container_module, "main"): categories(
                success={main_success},
                invalid_or_protocol={public_failure},
                rollback_or_no_partial_state={ownership_rollback},
                leak_safety={public_failure, ownership_rollback},
            ),
            (container_module, "stage_configured_secrets"): categories(
                success={stage_success},
                invalid_or_protocol={manifest_rollback},
                expiry_replay_or_revocation={stage_success},
                rollback_or_no_partial_state={
                    manifest_rollback,
                    ownership_rollback,
                    public_partial_write,
                    source_close_failure,
                },
                leak_safety={
                    manifest_rollback,
                    ownership_rollback,
                    source_close_failure,
                },
            ),
            (secret_module, "SecretInitializationError.__init__"): categories(
                success={lock_contention},
                invalid_or_protocol={lock_contention},
                leak_safety={lock_contention},
            ),
            (secret_module, "_acquire_initialization_lock"): categories(
                success={lock_contention},
                invalid_or_protocol={lock_contention},
                rollback_or_no_partial_state={lock_contention},
                leak_safety={lock_contention},
            ),
            (secret_module, "_build_postgres_dsn"): categories(
                success={secret_create},
                leak_safety={secret_create},
            ),
            (secret_module, "_generate_private_key_pem"): categories(
                success={secret_create},
                leak_safety={secret_create},
            ),
            (secret_module, "_initialization_contract_hash"): categories(
                success={secret_create},
                leak_safety={secret_cli},
            ),
            (secret_module, "_prepare_secret_payloads"): categories(
                success={secret_create},
                leak_safety={secret_create},
            ),
            (secret_module, "_public_key_numbers"): categories(
                success={secret_create},
                invalid_or_protocol={invalid_complete_set},
                leak_safety={invalid_complete_set},
            ),
            (secret_module, "_quarantine_partial_secret_set"): categories(
                success={partial_recovery},
                rollback_or_no_partial_state={
                    quarantine_rollback,
                    quarantine_rollback_incomplete,
                },
                leak_safety={
                    quarantine_rollback,
                    quarantine_rollback_incomplete,
                },
            ),
            (secret_module, "_validate_existing_secret_set"): categories(
                success={secret_create},
                invalid_or_protocol={invalid_complete_set},
                leak_safety={invalid_complete_set},
            ),
            (secret_module, "_validate_initialization_arguments"): categories(
                success={secret_create},
                invalid_or_protocol={invalid_postgres_shape},
                leak_safety={invalid_postgres_shape},
            ),
            (secret_module, "_validate_postgres_dsn"): categories(
                success={secret_create},
                invalid_or_protocol={invalid_complete_set},
                leak_safety={invalid_complete_set},
            ),
            (secret_module, "_write_new_secret_set"): categories(
                success={secret_create},
                rollback_or_no_partial_state={secret_publish_rollback},
                leak_safety={secret_publish_rollback},
            ),
            (secret_module, "initialize_connected_secrets"): categories(
                success={secret_create},
                invalid_or_protocol={
                    invalid_complete_set,
                    invalid_postgres_shape,
                },
                rollback_or_no_partial_state={
                    invalid_complete_set,
                    invalid_postgres_shape,
                    lock_contention,
                    quarantine_rollback,
                    quarantine_rollback_incomplete,
                    secret_publish_rollback,
                },
                leak_safety={
                    invalid_complete_set,
                    quarantine_rollback,
                    quarantine_rollback_incomplete,
                    secret_cli,
                },
            ),
        }
        self.assertEqual(set(expected), target_keys)

        def not_applicable_reason(
            key: tuple[str, str],
            category: str,
        ) -> str:
            identity = ".".join(key)
            if category == "invalid_or_protocol":
                if key[0] == container_module:
                    return (
                        f"{identity} accepts no protocol input at this boundary; it "
                        "receives only process-local constants or launcher-selected "
                        "configuration and does not parse remote request syntax."
                    )
                return (
                    f"{identity} accepts no protocol input at this boundary; it receives "
                    "only validated initialization values or internally generated "
                    "material, not caller-controlled remote syntax."
                )
            if category == "expiry_replay_or_revocation":
                if key[0] == container_module:
                    return (
                        f"{identity} has no token or session temporal state and does not "
                        "own expiry, replay, or revocation decisions; it only performs "
                        "process startup work before the connected OAuth runtime runs."
                    )
                return (
                    f"{identity} has no token or session temporal state and does not own "
                    "expiry, replay, or revocation decisions; secret initialization "
                    "creates deployment material before OAuth session lifecycle exists."
                )
            if category == "rollback_or_no_partial_state":
                if key == (container_module, "_drop_privileges"):
                    return (
                        f"{identity} does not open a transaction or mutate repository "
                        "state; it changes only the current launcher process credentials, "
                        "and any failure terminates startup before exec or durable runtime "
                        "state."
                    )
                return (
                    f"{identity} performs no durable write and mutates no repository "
                    "state; it only validates, reads, or derives an in-memory value, so "
                    "transaction rollback and public write cleanup are owned by its "
                    "calling startup workflow."
                )
            if category == "audit_lineage":
                return (
                    f"{identity} runs before connected-runtime actor resolution and audit "
                    "storage are available; it does not emit audit or persist audit "
                    "records, so authorization lineage is owned by later runtime "
                    "operations."
                )
            if category == "leak_safety":
                return (
                    f"{identity} returns no caller-visible data and does not receive "
                    "secret material for serialization; its internal result is consumed "
                    "only by the local startup workflow and is never a public response."
                )
            if category == "remote_http":
                return (
                    f"{identity} is not an HTTP boundary and does not perform HTTP; it "
                    "runs in local container startup before request routing and owns no "
                    "status, header, redirect, challenge, or response-body behavior."
                )
            self.fail(f"success evidence cannot be N/A for {identity}")

        collected = collect_unittest_test_ids(root / "tests")
        target_test_owners: dict[str, set[tuple[str, str]]] = {}
        for key in sorted(target_keys):
            with self.subTest(function_key=key):
                entry = entries[key]
                self.assertEqual(entry["status"], "onboarded")
                self.assertEqual(entry["source_binding"], bindings[key])
                self.assertEqual(
                    set(entry["categories"]),
                    set(REQUIRED_HARNESS_CATEGORIES),
                )
                category_union: set[str] = set()
                for category in REQUIRED_HARNESS_CATEGORIES:
                    evidence = entry["categories"][category]
                    test_ids = set(evidence["test_ids"])
                    self.assertEqual(test_ids, expected[key][category])
                    self.assertTrue(test_ids.issubset(collected))
                    self.assertIn(evidence["pending_reason"], (None, ""))
                    if test_ids:
                        self.assertIn(evidence["not_applicable_reason"], (None, ""))
                    else:
                        self.assertEqual(
                            evidence["not_applicable_reason"],
                            not_applicable_reason(key, category),
                        )
                    category_union.update(test_ids)
                self.assertEqual(entry["test_ids"], sorted(category_union))
                for test_id in category_union:
                    target_test_owners.setdefault(test_id, set()).add(key)

        self.assertEqual(
            {test_id: len(owners) for test_id, owners in target_test_owners.items()},
            {
                command_gating: 2,
                invalid_complete_set: 4,
                invalid_postgres_shape: 2,
                invalid_sources: 3,
                lock_contention: 3,
                main_success: 1,
                manifest_rollback: 3,
                ownership_rollback: 2,
                partial_recovery: 1,
                partial_staged_write: 1,
                privilege_drop: 1,
                privilege_drop_control: 1,
                privilege_drop_failure: 1,
                privilege_drop_verification: 1,
                public_failure: 2,
                public_partial_write: 1,
                quarantine_rollback: 2,
                quarantine_rollback_incomplete: 2,
                secret_cli: 2,
                secret_create: 10,
                secret_publish_rollback: 2,
                source_close_failure: 2,
                stage_success: 6,
                staged_mode_order: 1,
            },
        )
        self.assertEqual(
            {
                test_id: {
                    key
                    for key in target_keys
                    if test_id in expected[key]["rollback_or_no_partial_state"]
                }
                for test_id in (
                    invalid_complete_set,
                    invalid_postgres_shape,
                    lock_contention,
                    manifest_rollback,
                    ownership_rollback,
                    partial_staged_write,
                    privilege_drop_failure,
                    public_partial_write,
                    quarantine_rollback,
                    quarantine_rollback_incomplete,
                    secret_publish_rollback,
                    source_close_failure,
                )
            },
            {
                invalid_complete_set: {
                    (secret_module, "initialize_connected_secrets"),
                },
                invalid_postgres_shape: {
                    (secret_module, "initialize_connected_secrets"),
                },
                lock_contention: {
                    (secret_module, "_acquire_initialization_lock"),
                    (secret_module, "initialize_connected_secrets"),
                },
                manifest_rollback: {
                    (container_module, "_prepare_staging_root"),
                    (container_module, "_stage_signing_manifest"),
                    (container_module, "stage_configured_secrets"),
                },
                ownership_rollback: {
                    (container_module, "main"),
                    (container_module, "stage_configured_secrets"),
                },
                partial_staged_write: {
                    (container_module, "_write_staged_secret"),
                },
                privilege_drop_failure: {
                    (container_module, "_drop_privileges"),
                },
                public_partial_write: {
                    (container_module, "stage_configured_secrets"),
                },
                source_close_failure: {
                    (container_module, "stage_configured_secrets"),
                },
                quarantine_rollback: {
                    (secret_module, "_quarantine_partial_secret_set"),
                    (secret_module, "initialize_connected_secrets"),
                },
                quarantine_rollback_incomplete: {
                    (secret_module, "_quarantine_partial_secret_set"),
                    (secret_module, "initialize_connected_secrets"),
                },
                secret_publish_rollback: {
                    (secret_module, "_write_new_secret_set"),
                    (secret_module, "initialize_connected_secrets"),
                },
            },
        )
        evidence_owners: dict[str, set[tuple[str, str]]] = {}
        for item in manifest["functions"]:
            key = (item["module"], item["qualname"])
            for test_id in item["test_ids"]:
                evidence_owners.setdefault(test_id, set()).add(key)
        self.assertLessEqual(max(map(len, evidence_owners.values())), 12)
        self.assert_batch_status_partition(manifest, target_keys)

    def test_http_and_service_batch_is_manifest_onboarded(self) -> None:
        manifest = load_function_harness_manifest()
        root = Path(__file__).resolve().parents[1]
        bindings = changed_scoped_function_bindings(
            root,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}
        http_qualnames = {
            "_append_query",
            "_aware_now",
            "_is_exact_callback",
            "_oauth_error_response",
            "_record_denial_safely",
            "_token_form",
            "_unique_query_parameters",
            "authorization_server_metadata",
            "create_oauth_asgi_app",
            "oauth_routes.<locals>.authorization_server_endpoint",
            "oauth_routes.<locals>.authorize_endpoint",
            "oauth_routes.<locals>.jwks_endpoint",
            "oauth_routes.<locals>.protected_resource_endpoint",
            "oauth_routes.<locals>.token_endpoint",
            "protected_resource_metadata",
        }
        service_qualnames = {
            "FormOwlOAuthBridge.__init__",
            "FormOwlOAuthBridge._audit_log",
            "FormOwlOAuthBridge._http_denial_reason_matches_state",
            "FormOwlOAuthBridge._require_active_identity",
            "FormOwlOAuthBridge._require_active_user",
            "FormOwlOAuthBridge._trusted_http_denial_token_session",
            "FormOwlOAuthBridge._validate_authorization_code",
            "FormOwlOAuthBridge._validate_pending_transaction",
            "FormOwlOAuthBridge._validate_token_session_binding",
            "FormOwlOAuthBridge.validate_authorization_request",
            "FormOwlOAuthBridge.whoami_payload",
            "_iso",
            "_parse_iso",
            "_require_aware",
            "_safe_id",
        }
        target_keys = {
            *(("formowl_auth.http", qualname) for qualname in http_qualnames),
            *(("formowl_auth.service", qualname) for qualname in service_qualnames),
        }
        route_dependency_test = (
            "tests.test_oauth_http_routes.OAuthHttpRouteTests."
            "test_route_dependencies_must_match_the_bridge_instances"
        )
        callback_redirect_test = (
            "tests.test_oauth_http_routes.OAuthHttpRouteTests."
            "test_callback_redirect_requires_exact_internal_query_and_no_fragment"
        )
        direct_whoami_test = (
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_direct_whoami_payload_is_minimal_and_side_effect_free"
        )
        expected_test_ids = {
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_audit_decisions_and_denials_preserve_safe_lineage",
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_authorization_scope_rejects_non_space_separators_without_mutation",
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_code_exchange_rejects_each_misbound_authorization_field_atomically",
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_different_subject_expiry_replay_and_code_replay_fail_without_partial_state",
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_direct_mcp_authorization_decision_persists_safe_lineage_and_is_atomic",
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_direct_start_authorization_persists_hash_only_transaction_and_is_atomic",
            direct_whoami_test,
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_http_authentication_denial_audit_failure_rolls_back",
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_http_denial_lineage_covers_verified_server_side_account_revocations",
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_http_denial_lineage_requires_verified_token_and_server_session",
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_revoked_or_disabled_binding_and_removed_membership_fail_closed",
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_start_authorization_rejects_detached_timezone_without_mutation",
            "tests.test_oauth_bridge_service.OAuthBridgeServiceTests."
            "test_token_session_ids_are_bound_to_jwt_principal_and_authorization",
            "tests.test_oauth_http_routes.OAuthHttpRouteTests."
            "test_aware_now_rejects_detached_timezone_clock",
            "tests.test_oauth_mcp_e2e.OAuthMcpEndToEndTests."
            "test_every_repository_write_and_audit_failure_rolls_back_byte_for_byte",
            "tests.test_oauth_mcp_e2e.OAuthMcpEndToEndTests."
            "test_oauth_discovery_and_challenges_match_protected_resource",
            "tests.test_oauth_mcp_e2e.OAuthMcpEndToEndTests."
            "test_oauth_negative_matrix_fails_closed_without_partial_state_or_leaks",
            "tests.test_oauth_mcp_e2e.OAuthMcpEndToEndTests."
            "test_remote_http_invited_user_reconnect_revocation_and_workspace_boundary",
            callback_redirect_test,
            "tests.test_oauth_http_routes.OAuthHttpRouteTests."
            "test_denial_audit_failure_keeps_all_other_state_unchanged",
            "tests.test_oauth_http_routes.OAuthHttpRouteTests."
            "test_duplicate_authorize_callback_and_token_fields_only_add_one_redacted_audit",
            "tests.test_oauth_http_routes.OAuthHttpRouteTests."
            "test_full_http_authorization_callback_and_token_exchange",
            "tests.test_oauth_http_routes.OAuthHttpRouteTests."
            "test_route_set_metadata_jwks_and_urls_are_exact_and_host_independent",
            "tests.test_oauth_http_routes.OAuthHttpRouteTests."
            "test_token_form_rejects_transport_malformed_requests_without_state_mutation",
            "tests.test_oauth_http_routes.OAuthHttpRouteTests."
            "test_token_form_stops_streaming_as_soon_as_the_body_limit_is_crossed",
            "tests.test_oauth_http_routes.OAuthHttpRouteTests."
            "test_trusted_authorization_error_redirect_contains_only_error_and_client_state",
            "tests.test_oauth_http_routes.OAuthHttpRouteTests."
            "test_untrusted_authorization_redirect_is_never_followed_or_reflected",
        }

        self.assertEqual(len(target_keys), 30)
        self.assertEqual(target_keys & entries.keys(), target_keys)
        self.assert_batch_status_partition(manifest, target_keys)
        collected = collect_unittest_test_ids(Path(__file__).resolve().parent)
        batch_test_ids: set[str] = set()
        for key in sorted(target_keys):
            with self.subTest(function_key=key):
                entry = entries[key]
                self.assertEqual(entry["status"], "onboarded")
                self.assertEqual(entry["source_binding"], bindings[key])
                self.assertEqual(set(entry["categories"]), set(REQUIRED_HARNESS_CATEGORIES))
                category_test_ids: set[str] = set()
                for category in REQUIRED_HARNESS_CATEGORIES:
                    evidence = entry["categories"][category]
                    test_ids = set(evidence["test_ids"])
                    category_test_ids.update(test_ids)
                    self.assertTrue(test_ids.issubset(collected))
                    self.assertIn(evidence["pending_reason"], (None, ""))
                    if test_ids:
                        self.assertIn(evidence["not_applicable_reason"], (None, ""))
                    else:
                        self.assertIsInstance(evidence["not_applicable_reason"], str)
                        self.assertTrue(evidence["not_applicable_reason"].strip())
                self.assertTrue(entry["categories"]["success"]["test_ids"])
                self.assertEqual(set(entry["test_ids"]), category_test_ids)
                batch_test_ids.update(category_test_ids)
        self.assertEqual(batch_test_ids, expected_test_ids)
        whoami_key = ("formowl_auth.service", "FormOwlOAuthBridge.whoami_payload")
        for category in (
            "success",
            "invalid_or_protocol",
            "rollback_or_no_partial_state",
            "audit_lineage",
            "leak_safety",
        ):
            self.assertIn(
                direct_whoami_test,
                entries[whoami_key]["categories"][category]["test_ids"],
            )
        self.assertIn(direct_whoami_test, entries[whoami_key]["test_ids"])
        oauth_routes_key = ("formowl_auth.http", "oauth_routes")
        for category in ("invalid_or_protocol", "rollback_or_no_partial_state"):
            self.assertIn(
                route_dependency_test,
                entries[oauth_routes_key]["categories"][category]["test_ids"],
            )
        for callback_key in {
            oauth_routes_key,
            ("formowl_auth.http", "oauth_routes.<locals>.google_callback_endpoint"),
        }:
            for category in (
                "success",
                "invalid_or_protocol",
                "rollback_or_no_partial_state",
                "leak_safety",
                "remote_http",
            ):
                self.assertIn(
                    callback_redirect_test,
                    entries[callback_key]["categories"][category]["test_ids"],
                )
            self.assertIn(callback_redirect_test, entries[callback_key]["test_ids"])
        for callback_key in {
            oauth_routes_key,
            ("formowl_auth.http", "oauth_routes.<locals>.google_callback_endpoint"),
        }:
            self.assertEqual(entries[callback_key]["source_binding"], bindings[callback_key])

    def test_remote_helper_batch_is_manifest_onboarded(self) -> None:
        manifest = load_function_harness_manifest()
        root = Path(__file__).resolve().parents[1]
        bindings = changed_scoped_function_bindings(
            root,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}

        def categories(**evidence: set[str]) -> dict[str, set[str]]:
            expected = {category: set() for category in REQUIRED_HARNESS_CATEGORIES}
            expected.update(evidence)
            return expected

        missing_bearer = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_missing_bearer_returns_mcp_tool_error_with_canonical_challenge"
        )
        nested_tampering = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_nested_session_identity_tampering_fails_closed_before_handler"
        )
        invalid_structured = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_invalid_token_unknown_tool_and_handler_failure_have_no_structured_content"
        )
        valid_bearer = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_valid_bearer_resolves_fresh_actor_context_for_every_tool_call"
        )
        detached_timezone = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_connected_factory_rejects_detached_timezone_before_any_effect"
        )
        invalid_bearer = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_invalid_or_multiple_bearer_is_http_denial_without_token_echo"
        )
        canonical_challenge = (
            "tests.test_mcp_oauth_gateway.RemoteMcpDescriptorTests."
            "test_challenge_is_canonical_and_rejects_header_injection"
        )
        quoted_challenge = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_challenge_quoted_strings_escape_once_without_side_effects"
        )
        malformed_denial = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_malformed_denial_http_response_and_audit_use_only_normalized_values"
        )
        generated_identifier = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_generated_identifier_guard_is_safe_and_fails_before_any_effect"
        )
        workspace_upload = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_current_workspace_upload_is_bound_and_forgery_fails_before_handler"
        )
        safe_denial = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_safe_denial_normalizes_malformed_attributes_without_leaks_or_effects"
        )
        successful_payload = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_successful_tool_result_preserves_canonical_safe_payload_and_error_flag"
        )
        rejected_payload = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_successful_tool_result_rejects_unsafe_payloads_before_serialization"
        )
        rejected_non_json_payload = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_successful_tool_result_rejects_non_json_non_finite_and_serializer_failures"
        )
        unsafe_handler_payload = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_unsafe_handler_payload_returns_generic_error_after_truthful_authorization"
        )
        expected = {
            (
                "formowl_gateway.remote",
                "RemoteMcpDispatcher._authorization_error",
            ): categories(
                success={missing_bearer},
                invalid_or_protocol={nested_tampering},
                expiry_replay_or_revocation={invalid_structured},
                rollback_or_no_partial_state={nested_tampering},
                audit_lineage={nested_tampering},
                leak_safety={nested_tampering},
                remote_http={missing_bearer},
            ),
            ("formowl_gateway.remote", "_aware_now"): categories(
                success={valid_bearer},
                invalid_or_protocol={detached_timezone},
                expiry_replay_or_revocation={invalid_bearer},
                rollback_or_no_partial_state={detached_timezone},
                audit_lineage={valid_bearer},
                leak_safety={detached_timezone},
                remote_http={invalid_bearer},
            ),
            ("formowl_gateway.remote", "_extract_bearer_token"): categories(
                success={valid_bearer},
                invalid_or_protocol={invalid_bearer},
                leak_safety={invalid_bearer},
                remote_http={invalid_bearer},
            ),
            ("formowl_gateway.remote", "_header_value"): categories(
                success={canonical_challenge},
                invalid_or_protocol={canonical_challenge},
                leak_safety={quoted_challenge},
                remote_http={malformed_denial},
            ),
            ("formowl_gateway.remote", "_new_safe_id"): categories(
                success={generated_identifier},
                invalid_or_protocol={generated_identifier},
                rollback_or_no_partial_state={generated_identifier},
                audit_lineage={invalid_bearer},
                leak_safety={generated_identifier},
                remote_http={generated_identifier},
            ),
            ("formowl_gateway.remote", "_prepare_tool_arguments"): categories(
                success={workspace_upload},
                invalid_or_protocol={workspace_upload},
                rollback_or_no_partial_state={workspace_upload},
                audit_lineage={workspace_upload},
                leak_safety={workspace_upload},
                remote_http={workspace_upload},
            ),
            ("formowl_gateway.remote", "_quote_header_value"): categories(
                success={quoted_challenge},
                invalid_or_protocol={quoted_challenge},
                leak_safety={quoted_challenge},
                remote_http={malformed_denial},
            ),
            ("formowl_gateway.remote", "_safe_denial"): categories(
                success={safe_denial},
                invalid_or_protocol={safe_denial},
                expiry_replay_or_revocation={invalid_bearer},
                leak_safety={malformed_denial},
                remote_http={malformed_denial},
            ),
            ("formowl_gateway.remote", "_send_http_oauth_denial"): categories(
                success={invalid_bearer},
                invalid_or_protocol={invalid_bearer},
                expiry_replay_or_revocation={invalid_bearer},
                rollback_or_no_partial_state={malformed_denial},
                audit_lineage={malformed_denial},
                leak_safety={malformed_denial},
                remote_http={invalid_bearer},
            ),
            ("formowl_gateway.remote", "_successful_tool_result"): categories(
                success={successful_payload},
                invalid_or_protocol={
                    rejected_non_json_payload,
                    rejected_payload,
                },
                rollback_or_no_partial_state={
                    rejected_non_json_payload,
                    rejected_payload,
                },
                leak_safety={
                    rejected_non_json_payload,
                    rejected_payload,
                },
                remote_http={unsafe_handler_payload},
            ),
            ("formowl_gateway.remote", "_validate_actor_context"): categories(
                success={valid_bearer},
                invalid_or_protocol={nested_tampering},
                rollback_or_no_partial_state={nested_tampering},
                audit_lineage={nested_tampering},
                leak_safety={nested_tampering},
                remote_http={nested_tampering},
            ),
            (
                "formowl_gateway.remote",
                "_validate_current_workspace_upload",
            ): categories(
                success={workspace_upload},
                invalid_or_protocol={workspace_upload},
                rollback_or_no_partial_state={workspace_upload},
                audit_lineage={workspace_upload},
                leak_safety={workspace_upload},
                remote_http={workspace_upload},
            ),
            (
                "formowl_gateway.remote",
                "build_www_authenticate_challenge",
            ): categories(
                success={canonical_challenge},
                invalid_or_protocol={canonical_challenge},
                leak_safety={quoted_challenge},
                remote_http={invalid_bearer},
            ),
        }
        target_keys = set(expected)

        self.assertEqual(len(target_keys), 13)
        self.assertEqual(target_keys & entries.keys(), target_keys)
        self.assertEqual(set(entries), set(bindings))
        collected = collect_unittest_test_ids(root / "tests")
        expected_test_ids: set[str] = set()
        for key in sorted(target_keys):
            with self.subTest(function_key=key):
                entry = entries[key]
                self.assertEqual(entry["status"], "onboarded")
                self.assertEqual(entry["source_binding"], bindings[key])
                self.assertEqual(
                    set(entry["categories"]),
                    set(REQUIRED_HARNESS_CATEGORIES),
                )
                category_union: set[str] = set()
                for category in REQUIRED_HARNESS_CATEGORIES:
                    evidence = entry["categories"][category]
                    test_ids = set(evidence["test_ids"])
                    self.assertEqual(test_ids, expected[key][category])
                    self.assertTrue(test_ids.issubset(collected))
                    self.assertIn(evidence["pending_reason"], (None, ""))
                    if test_ids:
                        self.assertIn(evidence["not_applicable_reason"], (None, ""))
                    else:
                        self.assertIsInstance(evidence["not_applicable_reason"], str)
                        self.assertTrue(evidence["not_applicable_reason"].strip())
                    category_union.update(test_ids)
                self.assertEqual(entry["test_ids"], sorted(category_union))
                expected_test_ids.update(category_union)
        self.assertTrue(expected_test_ids.issubset(collected))
        self.assert_batch_status_partition(manifest, target_keys)
        self.assertEqual(
            entries[
                (
                    "formowl_gateway.remote",
                    "build_www_authenticate_challenge",
                )
            ]["categories"]["expiry_replay_or_revocation"]["not_applicable_reason"],
            "formowl_gateway.remote.build_www_authenticate_challenge has no temporal "
            "state and only validates and renders one OAuth challenge header; bearer "
            "expiry, replay, and revocation are resolved before this header renderer "
            "is called.",
        )
        source_mismatch_count = sum(
            entries[key]["source_binding"] != bindings[key] for key in bindings
        )
        self.assertEqual(source_mismatch_count, 0)

    def test_external_identity_to_dict_is_manifest_onboarded(self) -> None:
        manifest = load_function_harness_manifest()
        root = Path(__file__).resolve().parents[1]
        bindings = changed_scoped_function_bindings(
            root,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}
        key = ("formowl_auth.models", "ExternalIdentity.to_dict")
        regression_test = (
            "tests.test_oauth_contracts_and_security.OAuthContractsAndSecurityTests."
            "test_external_identity_to_dict_is_exact_and_fails_closed_without_leak_or_"
            "side_effects"
        )
        expected = {
            "success": {regression_test},
            "invalid_or_protocol": {regression_test},
            "expiry_replay_or_revocation": set(),
            "rollback_or_no_partial_state": {regression_test},
            "audit_lineage": set(),
            "leak_safety": {regression_test},
            "remote_http": set(),
        }
        expected_n_a = {
            "expiry_replay_or_revocation": (
                "formowl_auth.models.ExternalIdentity.to_dict serializes and validates "
                "one in-memory identity record but has no temporal state and does not own "
                "expiry, replay, or revocation enforcement; those decisions require current "
                "repository-backed OAuth session and identity status checks."
            ),
            "audit_lineage": (
                "formowl_auth.models.ExternalIdentity.to_dict does not emit audit or persist "
                "audit records; it only returns validated identity data, while the calling "
                "OAuth bridge and gateway workflows own authenticated event lineage."
            ),
            "remote_http": (
                "formowl_auth.models.ExternalIdentity.to_dict is not an HTTP boundary and "
                "does not perform HTTP; it serializes one internal identity record below "
                "OAuth route and connected MCP transport handling."
            ),
        }

        entry = entries[key]
        self.assertEqual(entry["status"], "onboarded")
        self.assertEqual(entry["source_binding"], bindings[key])
        self.assertEqual(set(entry["categories"]), set(REQUIRED_HARNESS_CATEGORIES))
        collected = collect_unittest_test_ids(root / "tests")
        category_union: set[str] = set()
        for category in REQUIRED_HARNESS_CATEGORIES:
            evidence = entry["categories"][category]
            test_ids = set(evidence["test_ids"])
            self.assertEqual(test_ids, expected[category])
            self.assertTrue(test_ids.issubset(collected))
            self.assertIn(evidence["pending_reason"], (None, ""))
            if test_ids:
                self.assertIn(evidence["not_applicable_reason"], (None, ""))
            else:
                self.assertEqual(
                    evidence["not_applicable_reason"],
                    expected_n_a[category],
                )
            category_union.update(test_ids)
        self.assertEqual(entry["test_ids"], sorted(category_union))

    def test_oauth_model_serializer_and_helper_batch_is_manifest_onboarded(
        self,
    ) -> None:
        manifest = load_function_harness_manifest()
        root = Path(__file__).resolve().parents[1]
        bindings = changed_scoped_function_bindings(
            root,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}
        serializer_test = (
            "tests.test_oauth_contracts_and_security.OAuthContractsAndSecurityTests."
            "test_oauth_record_serializers_are_exact_and_fail_before_copy_hooks"
        )
        denial_test = (
            "tests.test_oauth_contracts_and_security.OAuthContractsAndSecurityTests."
            "test_oauth_access_denied_requires_exact_types_and_revalidates_safe_payload"
        )
        helper_test = (
            "tests.test_oauth_contracts_and_security.OAuthContractsAndSecurityTests."
            "test_oauth_model_helpers_are_exact_direct_and_non_mutating"
        )
        owner_bootstrap_contract_test = (
            "tests.test_oauth_contracts_and_security.OAuthContractsAndSecurityTests."
            "test_owner_bootstrap_and_service_audit_contracts_are_explicit"
        )
        owner_bootstrap_codec_test = (
            "tests.test_oauth_contracts_and_security.OAuthContractsAndSecurityTests."
            "test_owner_bootstrap_codecs_reject_unknown_caller_fields_without_echo"
        )
        serializer_qualnames = {
            "OAuthAuthorizationCode.to_dict",
            "OAuthClientAuthorization.to_dict",
            "OAuthInvitation.to_dict",
            "OAuthOwnerBootstrap.to_dict",
            "OAuthPrincipal.to_dict",
            "OAuthTokenSession.to_dict",
            "OAuthTransaction.to_dict",
        }
        denial_qualnames = {
            "OAuthAccessDenied.__init__",
            "OAuthAccessDenied.to_safe_dict",
        }
        helper_qualnames = {
            "_mapping",
            "_optional_safe_ids",
            "_optional_timestamps",
            "_required_safe_ids",
            "_required_string",
            "_validate_code_challenge",
            "_validate_hash",
            "_validate_timestamp",
        }
        test_by_qualname = {
            **{qualname: serializer_test for qualname in serializer_qualnames},
            **{qualname: denial_test for qualname in denial_qualnames},
            **{qualname: helper_test for qualname in helper_qualnames},
        }
        keys = {
            ("formowl_auth.models", qualname)
            for qualname in (serializer_qualnames | denial_qualnames | helper_qualnames)
        }

        self.assertEqual(len(keys), 17)
        self.assertTrue(keys.issubset(entries))
        collected = collect_unittest_test_ids(root / "tests")
        self.assertTrue(
            {
                serializer_test,
                denial_test,
                helper_test,
                owner_bootstrap_contract_test,
                owner_bootstrap_codec_test,
            }.issubset(collected)
        )

        for key in sorted(keys):
            with self.subTest(function_key=key):
                identity = ".".join(key)
                test_id = test_by_qualname[key[1]]
                entry = entries[key]
                if key[1] == "OAuthOwnerBootstrap.to_dict":
                    expected = {
                        "success": {owner_bootstrap_contract_test, serializer_test},
                        "invalid_or_protocol": {
                            owner_bootstrap_codec_test,
                            serializer_test,
                        },
                        "expiry_replay_or_revocation": set(),
                        "rollback_or_no_partial_state": {serializer_test},
                        "audit_lineage": {owner_bootstrap_contract_test},
                        "leak_safety": {
                            owner_bootstrap_codec_test,
                            serializer_test,
                        },
                        "remote_http": set(),
                    }
                    expected_n_a = {
                        "expiry_replay_or_revocation": (
                            "formowl_auth.models.OAuthOwnerBootstrap.to_dict does not own "
                            "expiry, replay, or revocation state; it validates and renders "
                            "one immutable bootstrap record after service lifecycle "
                            "decisions."
                        ),
                        "remote_http": (
                            "formowl_auth.models.OAuthOwnerBootstrap.to_dict is not an HTTP "
                            "boundary and has no remote transport behavior; it produces only "
                            "an internal dictionary for repository or service callers."
                        ),
                    }
                else:
                    expected = {
                        "success": {test_id},
                        "invalid_or_protocol": {test_id},
                        "expiry_replay_or_revocation": set(),
                        "rollback_or_no_partial_state": {test_id},
                        "audit_lineage": set(),
                        "leak_safety": {test_id},
                        "remote_http": set(),
                    }
                    expected_n_a = {
                        "expiry_replay_or_revocation": (
                            f"{identity} validates one in-memory OAuth record boundary but "
                            "does not own expiry, replay, or revocation authority decisions; "
                            "current repository-backed OAuth state is enforced by the "
                            "calling bridge, token, and gateway workflows."
                        ),
                        "audit_lineage": (
                            f"{identity} does not emit audit or persist audit records; it "
                            "only validates or serializes an in-memory OAuth value, while "
                            "the calling authorization and gateway workflows own durable "
                            "actor, session, workspace, and decision lineage."
                        ),
                        "remote_http": (
                            f"{identity} is not an HTTP boundary and does not perform HTTP; "
                            "it runs below OAuth route and connected MCP transport handling "
                            "and does not choose remote status, header, redirect, or "
                            "response-body behavior."
                        ),
                    }

                self.assertEqual(entry["status"], "onboarded")
                self.assertEqual(entry["source_binding"], bindings[key])
                self.assertEqual(
                    set(entry["categories"]),
                    set(REQUIRED_HARNESS_CATEGORIES),
                )
                category_union: set[str] = set()
                for category in REQUIRED_HARNESS_CATEGORIES:
                    evidence = entry["categories"][category]
                    test_ids = set(evidence["test_ids"])
                    self.assertEqual(test_ids, expected[category])
                    self.assertTrue(test_ids.issubset(collected))
                    self.assertIn(evidence["pending_reason"], (None, ""))
                    if test_ids:
                        self.assertIn(evidence["not_applicable_reason"], (None, ""))
                    else:
                        self.assertEqual(
                            evidence["not_applicable_reason"],
                            expected_n_a[category],
                        )
                    category_union.update(test_ids)
                self.assertEqual(entry["test_ids"], sorted(category_union))

    def test_issue20_implementation_contract_hash_is_manifest_onboarded(self) -> None:
        manifest = load_function_harness_manifest()
        root = Path(__file__).resolve().parents[1]
        bindings = changed_scoped_function_bindings(
            root,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}
        key = (
            "formowl_evidence.issue20",
            "issue20_implementation_contract_hash",
        )
        success_test = (
            "tests.test_connected_runtime_postgres_live_e2e."
            "ConnectedRuntimePostgresLiveE2ETests."
            "test_implementation_contract_hash_changes_with_runtime_or_migration_source"
        )
        missing_glob_test = (
            "tests.test_connected_runtime_postgres_live_e2e."
            "ConnectedRuntimePostgresLiveE2ETests."
            "test_implementation_contract_hash_missing_required_glob_fails_closed_"
            "without_mutation_or_leak"
        )
        contract_prefix = "tests.test_issue20_contract_hash.Issue20ContractHashTests."
        stable_contract_test = (
            contract_prefix + "test_hash_is_stable_and_changes_with_required_source"
        )
        transitive_operator_journey_test = (
            "tests.test_issue20_external_evidence_packet."
            "Issue20ExternalPacketBuilderTest."
            "test_operator_journey_source_is_transitively_bound_to_implementation_contract"
        )
        invalid_contract_tests = {
            contract_prefix
            + "test_hash_rejects_non_regular_required_file_without_blocking_or_mutation",
            contract_prefix
            + "test_hash_rejects_required_file_symlink_without_reading_external_target",
            contract_prefix + "test_hash_rejects_symlinked_required_directory_path_escape",
        }
        expected = {
            "success": {
                success_test,
                stable_contract_test,
                transitive_operator_journey_test,
            },
            "invalid_or_protocol": {missing_glob_test, *invalid_contract_tests},
            "expiry_replay_or_revocation": set(),
            "rollback_or_no_partial_state": {missing_glob_test, *invalid_contract_tests},
            "audit_lineage": set(),
            "leak_safety": {missing_glob_test, *invalid_contract_tests},
            "remote_http": set(),
        }

        entry = entries[key]
        self.assertEqual(entry["status"], "onboarded")
        self.assertEqual(entry["source_binding"], bindings[key])
        self.assertEqual(set(entry["categories"]), set(REQUIRED_HARNESS_CATEGORIES))
        collected = collect_unittest_test_ids(root / "tests")
        category_union: set[str] = set()
        for category in REQUIRED_HARNESS_CATEGORIES:
            evidence = entry["categories"][category]
            test_ids = set(evidence["test_ids"])
            self.assertEqual(test_ids, expected[category])
            self.assertTrue(test_ids.issubset(collected))
            self.assertIn(evidence["pending_reason"], (None, ""))
            if test_ids:
                self.assertIn(evidence["not_applicable_reason"], (None, ""))
            else:
                reason = evidence["not_applicable_reason"]
                self.assertIsInstance(reason, str)
                self.assertIn(
                    "formowl_evidence.issue20.issue20_implementation_contract_hash", reason
                )
            category_union.update(test_ids)
        self.assertEqual(entry["test_ids"], sorted(category_union))

    def test_manual_auth_select_actor_is_manifest_onboarded(self) -> None:
        manifest = load_function_harness_manifest()
        root = Path(__file__).resolve().parents[1]
        bindings = changed_scoped_function_bindings(
            root,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}
        key = (
            "formowl_auth.provider",
            "ManualTrustedInternalAuthProvider.select_actor",
        )
        success_test = (
            "tests.test_manual_auth_provider.ManualTrustedInternalAuthProviderTests."
            "test_select_actor_and_whoami_return_non_production_actor_context"
        )
        audit_failure_test = (
            "tests.test_manual_auth_provider.ManualTrustedInternalAuthProviderTests."
            "test_audit_failure_preserves_previous_actor_context_and_audit_bytes"
        )
        access_state_test = (
            "tests.test_workflow_edge_cases.WorkflowEdgeCaseTests."
            "test_manual_auth_provider_selects_by_email_or_user_id_and_filters_context"
        )
        expected = {
            "success": {success_test},
            "invalid_or_protocol": {success_test},
            "expiry_replay_or_revocation": {access_state_test},
            "rollback_or_no_partial_state": {audit_failure_test},
            "audit_lineage": {success_test, audit_failure_test},
            "leak_safety": {audit_failure_test},
            "remote_http": set(),
        }

        entry = entries[key]
        self.assertEqual(entry["status"], "onboarded")
        self.assertEqual(entry["source_binding"], bindings[key])
        self.assertEqual(set(entry["categories"]), set(REQUIRED_HARNESS_CATEGORIES))
        collected = collect_unittest_test_ids(root / "tests")
        category_union: set[str] = set()
        for category in REQUIRED_HARNESS_CATEGORIES:
            evidence = entry["categories"][category]
            test_ids = set(evidence["test_ids"])
            self.assertEqual(test_ids, expected[category])
            self.assertTrue(test_ids.issubset(collected))
            self.assertIn(evidence["pending_reason"], (None, ""))
            if test_ids:
                self.assertIn(evidence["not_applicable_reason"], (None, ""))
            else:
                self.assertEqual(
                    evidence["not_applicable_reason"],
                    "formowl_auth.provider.ManualTrustedInternalAuthProvider.select_actor "
                    "does not perform HTTP; it is a tests/local-compatibility identity "
                    "selector, while connected requests use FormOwl OAuth 2.1 and a "
                    "gateway-resolved ActorContext.",
                )
            category_union.update(test_ids)
        self.assertEqual(entry["test_ids"], sorted(category_union))

    def test_exact_mcp_to_open_upload_session_batch_is_manifest_onboarded(self) -> None:
        manifest = load_function_harness_manifest()
        root = Path(__file__).resolve().parents[1]
        bindings = changed_scoped_function_bindings(
            root,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}

        remote_direct = (
            "tests.test_mcp_oauth_gateway.RemoteSafeExceptionMiddlewareTests."
            "test_direct_composition_helpers_enforce_exact_safe_boundaries"
        )
        middleware_direct = (
            "tests.test_mcp_oauth_gateway.RemoteSafeExceptionMiddlewareTests."
            "test_started_http_exception_closes_incomplete_body_without_leak"
        )
        runtime_direct = (
            "tests.test_connected_runtime.ConnectedRuntimeConfigTests."
            "test_direct_runtime_and_mail_upload_helpers_preserve_safe_governed_boundaries"
        )
        exact_http = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_initialize_and_tool_list_are_public_on_exact_mcp_path"
        )
        missing_bearer = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_missing_bearer_returns_mcp_tool_error_with_canonical_challenge"
        )
        descriptor_contract = (
            "tests.test_mcp_oauth_gateway.RemoteMcpDescriptorTests."
            "test_descriptors_have_oauth_output_schema_and_complete_annotations"
        )
        detached_clock = (
            "tests.test_mcp_oauth_gateway.RemoteMcpHttpTests."
            "test_connected_factory_rejects_detached_timezone_before_any_effect"
        )
        middleware_lifespan = (
            "tests.test_mcp_oauth_gateway.RemoteSafeExceptionMiddlewareTests."
            "test_lifespan_startup_exception_is_not_swallowed"
        )
        middleware_500 = (
            "tests.test_mcp_oauth_gateway.RemoteSafeExceptionMiddlewareTests."
            "test_http_exception_returns_generic_500_without_logging_secret"
        )
        signing_rotation = (
            "tests.test_connected_runtime.ConnectedRuntimeConfigTests."
            "test_file_mounted_signing_key_rotation_survives_restart_overlap"
        )
        signing_invalid = (
            "tests.test_connected_runtime.ConnectedRuntimeConfigTests."
            "test_signing_key_manifest_invalid_layouts_fail_closed_without_leak"
        )
        secret_config_invalid = (
            "tests.test_connected_runtime.ConnectedRuntimeConfigTests."
            "test_secret_and_config_failures_use_only_machine_safe_codes"
        )
        secret_content_invalid = (
            "tests.test_connected_runtime.ConnectedRuntimeConfigTests."
            "test_secret_file_content_negative_matrix_is_safe"
        )
        readiness = (
            "tests.test_connected_runtime.ConnectedRuntimeLifecycleTests."
            "test_upload_store_readiness_probe_is_atomic_clean_and_fail_closed"
        )
        readiness_http = (
            "tests.test_connected_runtime.ConnectedRuntimeHttpTests."
            "test_health_ready_exact_path_and_identity_only_tools_are_safe"
        )
        operator_directory = (
            "tests.test_connected_runtime.ConnectedRuntimeOperatorDirectoryWrapperTests."
            "test_directory_factory_and_all_safe_wrappers_delegate"
        )
        governed_upload = (
            "tests.test_connected_runtime.ConnectedRuntimeHttpTests."
            "test_production_runtime_open_upload_session_persists_governed_state"
        )
        mail_success = (
            "tests.test_mail_upload_session_gateway.MailUploadSessionGatewayTests."
            "test_jsonrpc_open_upload_session_creates_session_bound_mail_task_card"
        )
        mail_invalid = (
            "tests.test_mail_upload_session_gateway.MailUploadSessionGatewayTests."
            "test_user_infrastructure_controls_fail_before_session_or_audit_side_effects"
        )
        mail_audit_failure = (
            "tests.test_mail_upload_session_gateway.MailUploadSessionGatewayTests."
            "test_audit_write_failure_leaves_no_upload_session_side_effect"
        )
        mail_store_failure = (
            "tests.test_mail_upload_session_gateway.MailUploadSessionGatewayTests."
            "test_session_store_failure_rolls_back_chatgpt_upload_audit"
        )

        def categories(**evidence: set[str]) -> dict[str, set[str]]:
            expected = {category: set() for category in REQUIRED_HARNESS_CATEGORIES}
            expected.update(evidence)
            return expected

        expected = {
            ("formowl_gateway.remote", "ExactMcpPathApp.__call__"): categories(
                success={remote_direct, exact_http},
                invalid_or_protocol={remote_direct, exact_http},
                rollback_or_no_partial_state={remote_direct},
                leak_safety={remote_direct},
                remote_http={remote_direct, exact_http},
            ),
            ("formowl_gateway.remote", "ExactMcpPathApp.__init__"): categories(
                success={remote_direct, exact_http},
                invalid_or_protocol={remote_direct},
                rollback_or_no_partial_state={remote_direct},
                leak_safety={remote_direct},
                remote_http={exact_http},
            ),
            ("formowl_gateway.remote", "_SessionManagerLifespan.__call__"): categories(
                success={remote_direct, exact_http},
                rollback_or_no_partial_state={remote_direct},
            ),
            ("formowl_gateway.remote", "_SessionManagerLifespan.__init__"): categories(
                success={remote_direct, exact_http},
            ),
            ("formowl_gateway.remote", "_canonical_metadata_url"): categories(
                success={remote_direct, missing_bearer},
                invalid_or_protocol={remote_direct},
                leak_safety={remote_direct, missing_bearer},
                remote_http={missing_bearer},
            ),
            ("formowl_gateway.remote", "_no_store_headers"): categories(
                success={remote_direct},
                leak_safety={remote_direct, middleware_500},
                remote_http={remote_direct, middleware_500},
            ),
            ("formowl_gateway.remote", "_required_scope"): categories(
                success={remote_direct},
                invalid_or_protocol={remote_direct},
            ),
            ("formowl_gateway.remote", "_tool_descriptor"): categories(
                success={remote_direct, descriptor_contract},
                leak_safety={descriptor_contract},
            ),
            ("formowl_gateway.remote", "_validate_connected_dependencies"): categories(
                success={remote_direct},
                invalid_or_protocol={remote_direct, detached_clock},
                rollback_or_no_partial_state={remote_direct, detached_clock},
                leak_safety={remote_direct, detached_clock},
            ),
            ("formowl_gateway.remote", "create_connected_mcp_asgi_app"): categories(
                success={remote_direct},
            ),
            ("formowl_gateway.remote", "SafeExceptionMiddleware.__call__"): categories(
                success={middleware_direct, middleware_500},
                invalid_or_protocol={
                    middleware_direct,
                    middleware_lifespan,
                    middleware_500,
                },
                rollback_or_no_partial_state={middleware_direct, middleware_500},
                leak_safety={middleware_direct, middleware_500},
                remote_http={middleware_direct, middleware_500},
            ),
            (
                "formowl_gateway.remote",
                "SafeExceptionMiddleware.__call__.<locals>.safe_send",
            ): categories(
                success={middleware_direct},
                invalid_or_protocol={middleware_direct},
                rollback_or_no_partial_state={middleware_direct},
                leak_safety={middleware_direct},
                remote_http={middleware_direct},
            ),
            ("formowl_gateway.remote", "SafeExceptionMiddleware.__init__"): categories(
                success={middleware_direct, middleware_lifespan, middleware_500},
                remote_http={middleware_500},
            ),
            ("formowl_gateway.runtime", "ConnectedRuntime._operator_directory"): categories(
                success={runtime_direct, operator_directory},
                leak_safety={runtime_direct},
            ),
            ("formowl_gateway.runtime", "ConnectedRuntimeError.__init__"): categories(
                success={runtime_direct},
                invalid_or_protocol={runtime_direct},
                leak_safety={
                    runtime_direct,
                    secret_config_invalid,
                    secret_content_invalid,
                },
            ),
            ("formowl_gateway.runtime", "_build_runtime_semantic_gateway"): categories(
                success={runtime_direct, governed_upload},
                expiry_replay_or_revocation={runtime_direct},
                rollback_or_no_partial_state={governed_upload},
                audit_lineage={governed_upload},
                leak_safety={runtime_direct, governed_upload},
                remote_http={governed_upload},
            ),
            (
                "formowl_gateway.runtime",
                "_build_runtime_semantic_gateway.<locals>.expires_at_provider",
            ): categories(
                success={runtime_direct},
                expiry_replay_or_revocation={runtime_direct},
                leak_safety={runtime_direct},
            ),
            ("formowl_gateway.runtime", "_load_signing_key_manifest"): categories(
                success={runtime_direct, signing_rotation},
                invalid_or_protocol={signing_invalid, secret_content_invalid},
                expiry_replay_or_revocation={signing_rotation},
                leak_safety={
                    runtime_direct,
                    signing_invalid,
                    secret_content_invalid,
                },
            ),
            ("formowl_gateway.runtime", "_read_secret_file"): categories(
                success={runtime_direct},
                invalid_or_protocol={secret_config_invalid, secret_content_invalid},
                leak_safety={
                    runtime_direct,
                    secret_config_invalid,
                    secret_content_invalid,
                },
            ),
            ("formowl_gateway.runtime", "_runtime_data_stores_ready"): categories(
                success={runtime_direct, readiness, readiness_http},
                invalid_or_protocol={readiness},
                rollback_or_no_partial_state={readiness},
                leak_safety={runtime_direct, readiness, readiness_http},
                remote_http={readiness_http},
            ),
            ("formowl_mail.upload_session", "build_mail_upload_session_handler"): categories(
                success={runtime_direct, governed_upload, mail_success},
                invalid_or_protocol={runtime_direct},
                expiry_replay_or_revocation={runtime_direct},
                leak_safety={runtime_direct},
            ),
            (
                "formowl_mail.upload_session",
                "build_mail_upload_session_handler.<locals>.handler",
            ): categories(
                success={runtime_direct, governed_upload, mail_success},
                invalid_or_protocol={governed_upload, mail_invalid},
                expiry_replay_or_revocation={runtime_direct},
                rollback_or_no_partial_state={
                    governed_upload,
                    mail_audit_failure,
                    mail_store_failure,
                },
                audit_lineage={runtime_direct, governed_upload, mail_success},
                leak_safety={runtime_direct, governed_upload, mail_invalid},
                remote_http={governed_upload},
            ),
        }
        n_a_templates = {
            "invalid_or_protocol": (
                "{identity} accepts no protocol input at this boundary; its internal "
                "collaborators and configuration have already been validated before "
                "invocation, so malformed remote request semantics are outside this "
                "function."
            ),
            "expiry_replay_or_revocation": (
                "{identity} has no temporal state and does not own expiry, replay, or "
                "revocation decisions; current bearer and session lifecycle authority "
                "is enforced by the OAuth bridge and gateway before this function runs."
            ),
            "rollback_or_no_partial_state": (
                "{identity} performs no durable write and mutates no repository state; "
                "its read or composition step cannot open a transaction or leave "
                "partially persisted state inside this function."
            ),
            "audit_lineage": (
                "{identity} does not emit audit or persist audit records; authorization "
                "and lifecycle audit emission is owned by the gateway, bridge, operator "
                "directory, or upload workflow that calls this function."
            ),
            "leak_safety": (
                "{identity} returns no caller-visible data and does not receive secret "
                "material; it only binds an internal collaborator, so it cannot expose "
                "a raw path, credential, or backend payload."
            ),
            "remote_http": (
                "{identity} is not an HTTP boundary and does not perform HTTP; it runs "
                "below or beside the remote transport and does not choose request "
                "routing, status, headers, redirects, or response bodies."
            ),
        }
        n_a_overrides = {
            (
                "formowl_gateway.remote",
                "SafeExceptionMiddleware.__call__",
                "expiry_replay_or_revocation",
            ): (
                "formowl_gateway.remote.SafeExceptionMiddleware.__call__ does not "
                "hold token or session temporal state and does not own expiry, replay, "
                "or revocation decisions; it wraps and forwards the request to the "
                "downstream ASGI application. Expiry, replay, and revocation are "
                "determined by downstream stateful OAuth and session components, not "
                "by this function."
            ),
            (
                "formowl_gateway.remote",
                "SafeExceptionMiddleware.__call__",
                "audit_lineage",
            ): (
                "formowl_gateway.remote.SafeExceptionMiddleware.__call__ does not "
                "hold authorization or lifecycle audit state; it does not emit audit "
                "records or persist audit records. It wraps and forwards requests to "
                "the downstream ASGI application. The downstream OAuth, gateway, "
                "operator, and upload components independently own their related "
                "authorization and lifecycle audit responsibilities; this function "
                "does not."
            ),
            (
                "formowl_gateway.remote",
                "SafeExceptionMiddleware.__call__.<locals>.safe_send",
                "expiry_replay_or_revocation",
            ): (
                "formowl_gateway.remote.SafeExceptionMiddleware.__call__.<locals>."
                "safe_send does not hold token or session temporal state and does not "
                "own expiry, replay, or revocation decisions; it forwards downstream "
                "ASGI response messages while tracking response completion. Expiry, "
                "replay, and revocation are determined by downstream stateful OAuth "
                "and session components, not by this function."
            ),
            (
                "formowl_gateway.remote",
                "SafeExceptionMiddleware.__call__.<locals>.safe_send",
                "audit_lineage",
            ): (
                "formowl_gateway.remote.SafeExceptionMiddleware.__call__.<locals>."
                "safe_send does not hold authorization or lifecycle audit state; it "
                "does not emit audit records or persist audit records. It only "
                "observes and forwards ASGI response messages emitted by the "
                "downstream application. The downstream OAuth, gateway, operator, and "
                "upload components independently own their related authorization and "
                "lifecycle audit responsibilities; this function does not."
            ),
            (
                "formowl_gateway.remote",
                "SafeExceptionMiddleware.__init__",
                "expiry_replay_or_revocation",
            ): (
                "formowl_gateway.remote.SafeExceptionMiddleware.__init__ does not "
                "hold token or session temporal state and does not own expiry, replay, "
                "or revocation decisions; it only stores the downstream ASGI "
                "application that the middleware will wrap. Expiry, replay, and "
                "revocation are determined by downstream stateful OAuth and session "
                "components, not by this function."
            ),
            (
                "formowl_gateway.remote",
                "SafeExceptionMiddleware.__init__",
                "audit_lineage",
            ): (
                "formowl_gateway.remote.SafeExceptionMiddleware.__init__ does not "
                "hold authorization or lifecycle audit state; it does not emit audit "
                "records or persist audit records. It only stores the downstream ASGI "
                "application that the middleware will wrap. The downstream OAuth, "
                "gateway, operator, and upload components independently own their "
                "related authorization and lifecycle audit responsibilities; this "
                "function does not."
            ),
        }

        target_keys = set(expected)
        self.assertEqual(len(target_keys), 22)
        self.assertTrue(target_keys.issubset(entries))
        collected = collect_unittest_test_ids(root / "tests")
        primary_owners = {
            test_id: {key for key in target_keys if test_id in set(entries[key]["test_ids"])}
            for test_id in (remote_direct, middleware_direct, runtime_direct)
        }
        self.assertEqual(len(primary_owners[remote_direct]), 10)
        self.assertEqual(len(primary_owners[middleware_direct]), 3)
        self.assertEqual(len(primary_owners[runtime_direct]), 9)

        for key in sorted(target_keys):
            with self.subTest(function_key=key):
                identity = ".".join(key)
                entry = entries[key]
                self.assertEqual(entry["status"], "onboarded")
                self.assertEqual(entry["source_binding"], bindings[key])
                self.assertEqual(
                    set(entry["categories"]),
                    set(REQUIRED_HARNESS_CATEGORIES),
                )
                category_union: set[str] = set()
                for category in REQUIRED_HARNESS_CATEGORIES:
                    evidence = entry["categories"][category]
                    test_ids = set(evidence["test_ids"])
                    self.assertEqual(test_ids, expected[key][category])
                    self.assertTrue(test_ids.issubset(collected))
                    self.assertIn(evidence["pending_reason"], (None, ""))
                    if test_ids:
                        self.assertIn(evidence["not_applicable_reason"], (None, ""))
                    else:
                        self.assertEqual(
                            evidence["not_applicable_reason"],
                            n_a_overrides.get(
                                (*key, category),
                                n_a_templates[category].format(identity=identity),
                            ),
                        )
                    category_union.update(test_ids)
                self.assertEqual(entry["test_ids"], sorted(category_union))

        evidence_owners: dict[str, set[tuple[str, str]]] = {}
        for item in manifest["functions"]:
            key = (item["module"], item["qualname"])
            for test_id in item["test_ids"]:
                evidence_owners.setdefault(test_id, set()).add(key)
        self.assertLessEqual(max(map(len, evidence_owners.values())), 12)
        self.assert_batch_status_partition(manifest, target_keys)

    def test_runtime_na_hygiene_is_precise_and_evidence_backed(self) -> None:
        manifest = load_function_harness_manifest()
        root = Path(__file__).resolve().parents[1]
        bindings = changed_scoped_function_bindings(
            root,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )
        collected = collect_unittest_test_ids(root / "tests")
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}
        module = "formowl_gateway.runtime"
        discovery_preflight = (
            "tests.test_connected_runtime.ConnectedRuntimeLifecycleTests."
            "test_discovery_preflight_is_not_ready_but_serve_allows_public_discovery"
        )
        readiness_failure = (
            "tests.test_connected_runtime.ConnectedRuntimeLifecycleTests."
            "test_upload_store_readiness_probe_is_atomic_clean_and_fail_closed"
        )
        readiness_http_failure = (
            "tests.test_connected_runtime.ConnectedRuntimeHttpTests."
            "test_ready_upload_probe_failure_is_generic_and_cleans_partial_state"
        )
        signing_rotation = (
            "tests.test_connected_runtime.ConnectedRuntimeConfigTests."
            "test_file_mounted_signing_key_rotation_survives_restart_overlap"
        )
        cli_dispatch = (
            "tests.test_connected_runtime.ConnectedRuntimeCliTests."
            "test_cli_dispatches_all_commands_and_closes_runtime"
        )
        cli_invalid_timestamp = (
            "tests.test_connected_runtime.ConnectedRuntimeCliTests."
            "test_cli_rejects_invalid_bootstrap_timestamp_without_leak"
        )
        cli_discovery_serve = (
            "tests.test_connected_runtime.ConnectedRuntimeCliTests."
            "test_cli_discovery_serve_starts_public_surface"
        )
        expected_test_ids = {
            ("ConnectedRuntime.preflight", "remote_http"): [discovery_preflight],
            ("ConnectedRuntime.preflight", "rollback_or_no_partial_state"): [readiness_failure],
            ("ConnectedRuntime.readiness", "rollback_or_no_partial_state"): [readiness_failure],
            (
                "ConnectedRuntimeConfig.from_env_and_secrets",
                "expiry_replay_or_revocation",
            ): [signing_rotation],
            (
                "FileDeploymentSecretSource.load",
                "expiry_replay_or_revocation",
            ): [signing_rotation],
            ("_parse_timestamp", "expiry_replay_or_revocation"): [
                cli_dispatch,
                cli_invalid_timestamp,
            ],
            ("_run_command", "expiry_replay_or_revocation"): [cli_dispatch],
            ("main", "expiry_replay_or_revocation"): [cli_dispatch],
            ("_run_command", "remote_http"): [cli_discovery_serve],
            ("main", "remote_http"): [cli_discovery_serve],
            ("_readyz_endpoint", "rollback_or_no_partial_state"): [readiness_http_failure],
        }

        def na(qualname: str, detail: str) -> str:
            return f"{module}.{qualname} {detail}"

        expected_na_reasons = {
            (
                "ConnectedRuntime.aclose",
                "expiry_replay_or_revocation",
            ): na(
                "ConnectedRuntime.aclose",
                "has no temporal state and does not own expiry, replay, or "
                "revocation; it only closes already-created runtime resources "
                "after stateful OAuth lifecycle decisions have been made elsewhere.",
            ),
            (
                "ConnectedRuntime.aclose",
                "audit_lineage",
            ): na(
                "ConnectedRuntime.aclose",
                "does not emit audit or persist audit records; it only closes "
                "runtime resources, while each stateful OAuth workflow owns its "
                "authorization and lifecycle audit lineage.",
            ),
            (
                "ConnectedRuntime.aclose",
                "remote_http",
            ): na(
                "ConnectedRuntime.aclose",
                "is not an HTTP boundary and does not perform HTTP; it closes "
                "internal runtime resources without choosing request routing, "
                "response status, headers, or bodies.",
            ),
            (
                "ConnectedRuntime.compose",
                "expiry_replay_or_revocation",
            ): na(
                "ConnectedRuntime.compose",
                "has no temporal state and does not own expiry, replay, or "
                "revocation; it assembles validated runtime collaborators while "
                "the OAuth bridge and repository enforce current lifecycle state.",
            ),
            (
                "ConnectedRuntime.compose",
                "audit_lineage",
            ): na(
                "ConnectedRuntime.compose",
                "does not emit audit or persist audit records; it assembles runtime "
                "collaborators, while invoked OAuth, operator, and upload workflows "
                "own their durable audit lineage.",
            ),
            (
                "ConnectedRuntime.lifespan",
                "expiry_replay_or_revocation",
            ): na(
                "ConnectedRuntime.lifespan",
                "has no temporal state and does not own expiry, replay, or "
                "revocation; it enters and exits runtime resources while stateful "
                "OAuth components enforce lifecycle decisions.",
            ),
            (
                "ConnectedRuntime.lifespan",
                "audit_lineage",
            ): na(
                "ConnectedRuntime.lifespan",
                "does not emit audit or persist audit records; it manages resource "
                "lifetime only, while protected OAuth and operator operations "
                "retain their own audit lineage.",
            ),
            (
                "ConnectedRuntime.migrate",
                "expiry_replay_or_revocation",
            ): na(
                "ConnectedRuntime.migrate",
                "has no temporal state and does not own expiry, replay, or "
                "revocation; it delegates schema migration while token and session "
                "lifecycle authority remains in OAuth state.",
            ),
            (
                "ConnectedRuntime.migrate",
                "audit_lineage",
            ): na(
                "ConnectedRuntime.migrate",
                "does not emit audit or persist audit records; it delegates the "
                "versioned migration operation, whose deployment evidence is "
                "separate from user OAuth audit lineage.",
            ),
            (
                "ConnectedRuntime.migrate",
                "remote_http",
            ): na(
                "ConnectedRuntime.migrate",
                "is not an HTTP boundary and does not perform HTTP; it runs as an "
                "operator command without selecting remote routes, statuses, "
                "headers, or response bodies.",
            ),
            (
                "ConnectedRuntime.preflight",
                "expiry_replay_or_revocation",
            ): na(
                "ConnectedRuntime.preflight",
                "has no temporal state and does not own expiry, replay, or "
                "revocation; it evaluates startup configuration and readiness "
                "while OAuth state remains authoritative elsewhere.",
            ),
            (
                "ConnectedRuntime.preflight",
                "audit_lineage",
            ): na(
                "ConnectedRuntime.preflight",
                "does not emit audit or persist audit records; it reports startup "
                "readiness, while protected OAuth and operator workflows own "
                "authorization audit lineage.",
            ),
            (
                "ConnectedRuntimeConfig.from_env_and_secrets",
                "rollback_or_no_partial_state",
            ): na(
                "ConnectedRuntimeConfig.from_env_and_secrets",
                "performs no durable write and mutates no repository state; it "
                "reads and validates deployment configuration without opening a "
                "transaction or leaving partially persisted state.",
            ),
            (
                "ConnectedRuntimeConfig.from_env_and_secrets",
                "audit_lineage",
            ): na(
                "ConnectedRuntimeConfig.from_env_and_secrets",
                "does not emit audit or persist audit records; it constructs "
                "validated deployment configuration before any protected workflow "
                "establishes user or operator audit lineage.",
            ),
            (
                "ConnectedRuntimeConfig.from_env_and_secrets",
                "remote_http",
            ): na(
                "ConnectedRuntimeConfig.from_env_and_secrets",
                "is not an HTTP boundary and does not perform HTTP; it reads local "
                "deployment inputs without routing requests or constructing remote "
                "responses.",
            ),
            (
                "FileDeploymentSecretSource.load",
                "rollback_or_no_partial_state",
            ): na(
                "FileDeploymentSecretSource.load",
                "performs no durable write and mutates no repository state; it "
                "reads validated mounted material without opening a transaction or "
                "leaving partially persisted application state.",
            ),
            (
                "FileDeploymentSecretSource.load",
                "audit_lineage",
            ): na(
                "FileDeploymentSecretSource.load",
                "does not emit audit or persist audit records; it loads deployment "
                "material before protected OAuth workflows establish authorization "
                "and lifecycle audit lineage.",
            ),
            (
                "FileDeploymentSecretSource.load",
                "remote_http",
            ): na(
                "FileDeploymentSecretSource.load",
                "is not an HTTP boundary and does not perform HTTP; it reads "
                "deployment material locally without selecting routes, statuses, "
                "headers, or response bodies.",
            ),
            (
                "_build_parser",
                "expiry_replay_or_revocation",
            ): na(
                "_build_parser",
                "has no temporal state and does not own expiry, replay, or "
                "revocation; it declares command syntax while runtime OAuth "
                "components enforce current token and session lifecycle.",
            ),
            (
                "_build_parser",
                "rollback_or_no_partial_state",
            ): na(
                "_build_parser",
                "performs no durable write and mutates no repository state; it "
                "constructs an in-memory argument parser without opening a "
                "transaction or leaving partially persisted state.",
            ),
            (
                "_build_parser",
                "audit_lineage",
            ): na(
                "_build_parser",
                "does not emit audit or persist audit records; it declares operator "
                "command arguments, while dispatched stateful operations own their "
                "authorization and lifecycle audit lineage.",
            ),
            (
                "_build_parser",
                "remote_http",
            ): na(
                "_build_parser",
                "is not an HTTP boundary and does not perform HTTP; it builds local "
                "command-line parsing rules without routing requests or serializing "
                "remote responses.",
            ),
            (
                "_healthz_endpoint",
                "expiry_replay_or_revocation",
            ): na(
                "_healthz_endpoint",
                "has no temporal state and does not own expiry, replay, or "
                "revocation; it reports runtime liveness while the OAuth bridge and "
                "repository enforce current lifecycle authority.",
            ),
            (
                "_healthz_endpoint",
                "rollback_or_no_partial_state",
            ): na(
                "_healthz_endpoint",
                "performs no durable write and mutates no repository state; it "
                "reads liveness state only, so it does not open a transaction or "
                "leave partially persisted state.",
            ),
            (
                "_healthz_endpoint",
                "audit_lineage",
            ): na(
                "_healthz_endpoint",
                "does not emit audit or persist audit records; it exposes only "
                "runtime liveness, while protected requests and stateful workflows "
                "retain their own audit lineage.",
            ),
            (
                "_parse_timestamp",
                "rollback_or_no_partial_state",
            ): na(
                "_parse_timestamp",
                "performs no durable write and mutates no repository state; it "
                "parses one command value in memory without opening a transaction "
                "or leaving partially persisted state.",
            ),
            (
                "_parse_timestamp",
                "audit_lineage",
            ): na(
                "_parse_timestamp",
                "does not emit audit or persist audit records; it normalizes one "
                "command timestamp, while the consuming operator workflow owns any "
                "durable audit lineage.",
            ),
            (
                "_parse_timestamp",
                "remote_http",
            ): na(
                "_parse_timestamp",
                "is not an HTTP boundary and does not perform HTTP; it parses a "
                "local command value without routing requests, setting headers, or "
                "serializing remote responses.",
            ),
            (
                "_readyz_endpoint",
                "expiry_replay_or_revocation",
            ): na(
                "_readyz_endpoint",
                "has no temporal state and does not own expiry, replay, or "
                "revocation; it reports dependency readiness while stateful OAuth "
                "components enforce token and session lifecycle.",
            ),
            (
                "_readyz_endpoint",
                "audit_lineage",
            ): na(
                "_readyz_endpoint",
                "does not emit audit or persist audit records; it exposes "
                "dependency readiness, while protected OAuth requests and operator "
                "actions own their audit lineage.",
            ),
            (
                "_repository_schema_ready",
                "expiry_replay_or_revocation",
            ): na(
                "_repository_schema_ready",
                "has no temporal state and does not own expiry, replay, or "
                "revocation; it checks schema presence while OAuth repositories "
                "enforce current session lifecycle separately.",
            ),
            (
                "_repository_schema_ready",
                "audit_lineage",
            ): na(
                "_repository_schema_ready",
                "does not emit audit or persist audit records; it performs a "
                "readiness query, while protected workflows own authorization and "
                "lifecycle audit lineage.",
            ),
            (
                "_run_command",
                "audit_lineage",
            ): na(
                "_run_command",
                "does not emit audit or persist audit records itself; it dispatches "
                "validated commands, while each stateful operator or OAuth "
                "operation owns its durable audit lineage.",
            ),
            (
                "main",
                "audit_lineage",
            ): na(
                "main",
                "does not emit audit or persist audit records itself; it parses and "
                "dispatches the selected command, while invoked stateful operations "
                "own their durable audit lineage.",
            ),
        }
        target_category_keys = set(expected_test_ids) | set(expected_na_reasons)
        target_qualnames = {qualname for qualname, _ in target_category_keys}
        self.assertEqual(len(target_qualnames), 15)
        self.assertEqual(len(expected_test_ids), 11)
        self.assertEqual(len(expected_na_reasons), 34)
        self.assertEqual(len(target_category_keys), 45)
        self.assertTrue(set(expected_test_ids).isdisjoint(expected_na_reasons))

        for qualname in sorted(target_qualnames):
            key = (module, qualname)
            with self.subTest(function_key=key):
                entry = entries[key]
                self.assertEqual(entry["status"], "onboarded")
                self.assertEqual(entry["source_binding"], bindings[key])
                self.assertEqual(
                    set(entry["categories"]),
                    set(REQUIRED_HARNESS_CATEGORIES),
                )
                category_union = {
                    test_id
                    for evidence in entry["categories"].values()
                    for test_id in evidence["test_ids"]
                }
                self.assertEqual(set(entry["test_ids"]), category_union)
                self.assertTrue(category_union.issubset(collected))

        for qualname, category in sorted(target_category_keys):
            with self.subTest(qualname=qualname, category=category):
                evidence = entries[(module, qualname)]["categories"][category]
                self.assertEqual(
                    evidence["test_ids"],
                    expected_test_ids.get((qualname, category), []),
                )
                self.assertEqual(
                    evidence["not_applicable_reason"],
                    expected_na_reasons.get((qualname, category)),
                )
                self.assertIn(evidence["pending_reason"], (None, ""))

    def test_postgres_migration_transaction_batch_is_manifest_onboarded(self) -> None:
        manifest = load_function_harness_manifest()
        root = Path(__file__).resolve().parents[1]
        bindings = changed_scoped_function_bindings(
            root,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )
        collected = collect_unittest_test_ids(root / "tests")
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}
        target_keys = {
            ("formowl_auth.postgres", "PostgreSQLOAuthRepository.__init__"),
            ("formowl_auth.postgres", "PostgreSQLOAuthRepository.apply_migrations"),
            ("formowl_auth.postgres", "PostgreSQLOAuthRepository.close"),
            ("formowl_auth.postgres", "PostgreSQLOAuthRepository.connect"),
            ("formowl_auth.postgres", "PostgreSQLOAuthRepository.health_check"),
            ("formowl_auth.postgres", "PostgreSQLOAuthRepository.transaction"),
            ("formowl_auth.postgres", "PsycopgOAuthConnection.__init__"),
            ("formowl_auth.postgres", "PsycopgOAuthConnection.begin"),
            ("formowl_auth.postgres", "PsycopgOAuthConnection.close"),
            ("formowl_auth.postgres", "PsycopgOAuthConnection.commit"),
            ("formowl_auth.postgres", "PsycopgOAuthConnection.query_all"),
            ("formowl_auth.postgres", "PsycopgOAuthConnection.query_one"),
            ("formowl_auth.postgres", "PsycopgOAuthConnection.rollback"),
            ("formowl_auth.postgres", "oauth_migration_path"),
            (
                "formowl_graph.storage.postgres",
                "PostgreSQLMigrationResult.to_safe_dict",
            ),
            (
                "formowl_graph.storage.postgres",
                "PostgreSQLMigrationRunner.apply_pending",
            ),
            (
                "formowl_graph.storage.postgres",
                "PostgreSQLMigrationRunner.migration_replay",
            ),
            ("formowl_graph.storage.postgres", "PostgresMigration.from_file"),
            ("formowl_graph.storage.postgres", "_contains_executable_sql"),
            ("formowl_graph.storage.postgres", "_migration_ledger_sql"),
            ("formowl_graph.storage.postgres", "_migration_version"),
            ("formowl_graph.storage.postgres", "_split_sql_statements"),
            ("formowl_graph.storage.postgres", "_validate_applied_migration"),
            ("formowl_graph.storage.postgres", "_validated_migration_ledger"),
            ("formowl_graph.storage.postgres", "_validated_migration_manifest"),
        }
        expected_target_tests = {
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.__init__",
                "success",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_transaction_commit_and_rollback_are_explicit"
            ],
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.apply_migrations",
                "success",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_health_migration_and_migration_path_cover_oauth_schema"
            ],
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.apply_migrations",
                "rollback_or_no_partial_state",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_apply_migrations_rolls_back_partial_state_on_failure"
            ],
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.apply_migrations",
                "leak_safety",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_health_migration_and_migration_path_cover_oauth_schema"
            ],
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.close",
                "success",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_connect_factory_owns_connection_and_returns_safe_failure"
            ],
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.close",
                "leak_safety",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_connect_factory_owns_connection_and_returns_safe_failure"
            ],
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.connect",
                "success",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_connect_factory_owns_connection_and_returns_safe_failure"
            ],
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.connect",
                "invalid_or_protocol",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_connect_factory_owns_connection_and_returns_safe_failure"
            ],
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.connect",
                "rollback_or_no_partial_state",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_connect_factory_owns_connection_and_returns_safe_failure"
            ],
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.connect",
                "leak_safety",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_connect_factory_owns_connection_and_returns_safe_failure"
            ],
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.health_check",
                "success",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_health_migration_and_migration_path_cover_oauth_schema"
            ],
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.health_check",
                "invalid_or_protocol",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_health_migration_and_migration_path_cover_oauth_schema"
            ],
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.health_check",
                "leak_safety",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_health_migration_and_migration_path_cover_oauth_schema"
            ],
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.transaction",
                "success",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_transaction_commit_and_rollback_are_explicit"
            ],
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.transaction",
                "rollback_or_no_partial_state",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_transaction_commit_and_rollback_are_explicit"
            ],
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.__init__",
                "success",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_psycopg_adapter_uses_parameters_and_maps_rows"
            ],
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.begin",
                "success",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_psycopg_adapter_uses_parameters_and_maps_rows"
            ],
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.begin",
                "rollback_or_no_partial_state",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_psycopg_adapter_uses_parameters_and_maps_rows"
            ],
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.close",
                "success",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_psycopg_adapter_uses_parameters_and_maps_rows"
            ],
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.commit",
                "success",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_psycopg_adapter_uses_parameters_and_maps_rows"
            ],
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.commit",
                "rollback_or_no_partial_state",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_psycopg_adapter_uses_parameters_and_maps_rows"
            ],
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.query_all",
                "success",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_psycopg_adapter_uses_parameters_and_maps_rows"
            ],
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.query_all",
                "invalid_or_protocol",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_psycopg_adapter_uses_parameters_and_maps_rows"
            ],
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.query_all",
                "leak_safety",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_psycopg_adapter_uses_parameters_and_maps_rows"
            ],
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.query_one",
                "success",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_psycopg_adapter_uses_parameters_and_maps_rows"
            ],
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.query_one",
                "invalid_or_protocol",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_psycopg_adapter_uses_parameters_and_maps_rows"
            ],
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.query_one",
                "leak_safety",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_psycopg_adapter_uses_parameters_and_maps_rows"
            ],
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.rollback",
                "success",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_psycopg_adapter_uses_parameters_and_maps_rows"
            ],
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.rollback",
                "rollback_or_no_partial_state",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_psycopg_adapter_uses_parameters_and_maps_rows"
            ],
            (
                "formowl_auth.postgres",
                "oauth_migration_path",
                "success",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_health_migration_and_migration_path_cover_oauth_schema"
            ],
            (
                "formowl_auth.postgres",
                "oauth_migration_path",
                "leak_safety",
            ): [
                "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
                "test_health_migration_and_migration_path_cover_oauth_schema"
            ],
            (
                "formowl_graph.storage.postgres",
                "PostgreSQLMigrationResult.to_safe_dict",
                "success",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_apply_pending_locks_records_checksums_and_exact_replay_is_a_noop"
            ],
            (
                "formowl_graph.storage.postgres",
                "PostgreSQLMigrationResult.to_safe_dict",
                "leak_safety",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_apply_pending_locks_records_checksums_and_exact_replay_is_a_noop"
            ],
            (
                "formowl_graph.storage.postgres",
                "PostgreSQLMigrationRunner.apply_pending",
                "success",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_apply_pending_locks_records_checksums_and_exact_replay_is_a_noop"
            ],
            (
                "formowl_graph.storage.postgres",
                "PostgreSQLMigrationRunner.apply_pending",
                "invalid_or_protocol",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_checksum_version_and_history_drift_fail_closed"
            ],
            (
                "formowl_graph.storage.postgres",
                "PostgreSQLMigrationRunner.apply_pending",
                "expiry_replay_or_revocation",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_apply_pending_locks_records_checksums_and_exact_replay_is_a_noop",
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_checksum_version_and_history_drift_fail_closed",
            ],
            (
                "formowl_graph.storage.postgres",
                "PostgreSQLMigrationRunner.apply_pending",
                "rollback_or_no_partial_state",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_checksum_version_and_history_drift_fail_closed",
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_failed_pending_migration_rolls_back_prior_ledger_writes",
            ],
            (
                "formowl_graph.storage.postgres",
                "PostgreSQLMigrationRunner.apply_pending",
                "leak_safety",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_apply_pending_locks_records_checksums_and_exact_replay_is_a_noop",
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_checksum_version_and_history_drift_fail_closed",
            ],
            (
                "formowl_graph.storage.postgres",
                "PostgreSQLMigrationRunner.migration_replay",
                "success",
            ): [
                "tests.test_postgres_adapter_contracts."
                "PostgreSQLMetadataAdapterContractTests."
                "test_migration_runner_replays_locked_manifest_without_public_connection_details"
            ],
            (
                "formowl_graph.storage.postgres",
                "PostgreSQLMigrationRunner.migration_replay",
                "invalid_or_protocol",
            ): [
                "tests.test_postgres_adapter_contracts."
                "PostgreSQLMetadataAdapterContractTests."
                "test_migration_runner_replays_locked_manifest_without_public_connection_details"
            ],
            (
                "formowl_graph.storage.postgres",
                "PostgreSQLMigrationRunner.migration_replay",
                "rollback_or_no_partial_state",
            ): [
                "tests.test_postgres_adapter_contracts."
                "PostgreSQLMetadataAdapterContractTests."
                "test_migration_runner_replays_locked_manifest_without_public_connection_details"
            ],
            (
                "formowl_graph.storage.postgres",
                "PostgreSQLMigrationRunner.migration_replay",
                "leak_safety",
            ): [
                "tests.test_postgres_adapter_contracts."
                "PostgreSQLMetadataAdapterContractTests."
                "test_migration_runner_replays_locked_manifest_without_public_connection_details"
            ],
            (
                "formowl_graph.storage.postgres",
                "PostgresMigration.from_file",
                "success",
            ): [
                "tests.test_postgres_adapter_contracts."
                "PostgreSQLMetadataAdapterContractTests."
                "test_migration_runner_replays_locked_manifest_without_public_connection_details"
            ],
            (
                "formowl_graph.storage.postgres",
                "PostgresMigration.from_file",
                "leak_safety",
            ): [
                "tests.test_postgres_adapter_contracts."
                "PostgreSQLMetadataAdapterContractTests."
                "test_migration_runner_replays_locked_manifest_without_public_connection_details"
            ],
            (
                "formowl_graph.storage.postgres",
                "_contains_executable_sql",
                "success",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_sql_splitter_ignores_semicolons_in_comments_quotes_and_dollar_blocks"
            ],
            (
                "formowl_graph.storage.postgres",
                "_contains_executable_sql",
                "leak_safety",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_sql_splitter_ignores_semicolons_in_comments_quotes_and_dollar_blocks"
            ],
            (
                "formowl_graph.storage.postgres",
                "_migration_ledger_sql",
                "success",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_apply_pending_locks_records_checksums_and_exact_replay_is_a_noop"
            ],
            (
                "formowl_graph.storage.postgres",
                "_migration_ledger_sql",
                "leak_safety",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_apply_pending_locks_records_checksums_and_exact_replay_is_a_noop"
            ],
            (
                "formowl_graph.storage.postgres",
                "_migration_version",
                "success",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_apply_pending_locks_records_checksums_and_exact_replay_is_a_noop"
            ],
            (
                "formowl_graph.storage.postgres",
                "_migration_version",
                "invalid_or_protocol",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_checksum_version_and_history_drift_fail_closed"
            ],
            (
                "formowl_graph.storage.postgres",
                "_migration_version",
                "expiry_replay_or_revocation",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_checksum_version_and_history_drift_fail_closed"
            ],
            (
                "formowl_graph.storage.postgres",
                "_migration_version",
                "rollback_or_no_partial_state",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_checksum_version_and_history_drift_fail_closed"
            ],
            (
                "formowl_graph.storage.postgres",
                "_migration_version",
                "leak_safety",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_checksum_version_and_history_drift_fail_closed"
            ],
            (
                "formowl_graph.storage.postgres",
                "_split_sql_statements",
                "success",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_sql_splitter_ignores_semicolons_in_comments_quotes_and_dollar_blocks"
            ],
            (
                "formowl_graph.storage.postgres",
                "_split_sql_statements",
                "invalid_or_protocol",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_sql_splitter_ignores_semicolons_in_comments_quotes_and_dollar_blocks"
            ],
            (
                "formowl_graph.storage.postgres",
                "_split_sql_statements",
                "leak_safety",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_sql_splitter_ignores_semicolons_in_comments_quotes_and_dollar_blocks"
            ],
            (
                "formowl_graph.storage.postgres",
                "_validate_applied_migration",
                "success",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_apply_pending_locks_records_checksums_and_exact_replay_is_a_noop"
            ],
            (
                "formowl_graph.storage.postgres",
                "_validate_applied_migration",
                "invalid_or_protocol",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_checksum_version_and_history_drift_fail_closed"
            ],
            (
                "formowl_graph.storage.postgres",
                "_validate_applied_migration",
                "expiry_replay_or_revocation",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_checksum_version_and_history_drift_fail_closed"
            ],
            (
                "formowl_graph.storage.postgres",
                "_validate_applied_migration",
                "rollback_or_no_partial_state",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_checksum_version_and_history_drift_fail_closed"
            ],
            (
                "formowl_graph.storage.postgres",
                "_validate_applied_migration",
                "leak_safety",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_checksum_version_and_history_drift_fail_closed"
            ],
            (
                "formowl_graph.storage.postgres",
                "_validated_migration_ledger",
                "success",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_apply_pending_locks_records_checksums_and_exact_replay_is_a_noop"
            ],
            (
                "formowl_graph.storage.postgres",
                "_validated_migration_ledger",
                "invalid_or_protocol",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_checksum_version_and_history_drift_fail_closed"
            ],
            (
                "formowl_graph.storage.postgres",
                "_validated_migration_ledger",
                "expiry_replay_or_revocation",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_checksum_version_and_history_drift_fail_closed"
            ],
            (
                "formowl_graph.storage.postgres",
                "_validated_migration_ledger",
                "rollback_or_no_partial_state",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_checksum_version_and_history_drift_fail_closed"
            ],
            (
                "formowl_graph.storage.postgres",
                "_validated_migration_ledger",
                "leak_safety",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_checksum_version_and_history_drift_fail_closed"
            ],
            (
                "formowl_graph.storage.postgres",
                "_validated_migration_manifest",
                "success",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_apply_pending_locks_records_checksums_and_exact_replay_is_a_noop"
            ],
            (
                "formowl_graph.storage.postgres",
                "_validated_migration_manifest",
                "invalid_or_protocol",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_checksum_version_and_history_drift_fail_closed"
            ],
            (
                "formowl_graph.storage.postgres",
                "_validated_migration_manifest",
                "expiry_replay_or_revocation",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_checksum_version_and_history_drift_fail_closed"
            ],
            (
                "formowl_graph.storage.postgres",
                "_validated_migration_manifest",
                "rollback_or_no_partial_state",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_checksum_version_and_history_drift_fail_closed"
            ],
            (
                "formowl_graph.storage.postgres",
                "_validated_migration_manifest",
                "leak_safety",
            ): [
                "tests.test_postgres_migration_lifecycle.PostgreSQLMigrationLifecycleTests."
                "test_checksum_version_and_history_drift_fail_closed"
            ],
        }
        expected_target_n_a = {
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.__init__",
                "invalid_or_protocol",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.__init__ receives only "
                "validated input as an injected internal connection and ownership flag; "
                "it does not parse protocol input or caller-controlled request payloads."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.__init__",
                "expiry_replay_or_revocation",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.__init__ does not own "
                "expiry, replay, or revocation state; it only stores the injected "
                "connection and whether repository close owns that connection."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.__init__",
                "rollback_or_no_partial_state",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.__init__ performs no "
                "durable write and does not open a transaction; construction only "
                "records already-created internal dependencies."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.__init__",
                "audit_lineage",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.__init__ does not emit "
                "audit or persist audit lineage; audited service operations own their "
                "actor, target, reason, and session records."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.__init__",
                "leak_safety",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.__init__ returns no "
                "caller-visible data and does not receive secret material directly; it "
                "only retains an opaque internal connection object."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.__init__",
                "remote_http",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.__init__ is not an "
                "HTTP boundary and does not perform HTTP; it constructs only the "
                "internal PostgreSQL repository adapter."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.apply_migrations",
                "invalid_or_protocol",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.apply_migrations has "
                "no caller-controlled input and does not parse protocol input; it "
                "replays the repository-owned locked migration manifest."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.apply_migrations",
                "expiry_replay_or_revocation",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.apply_migrations does "
                "not own expiry, OAuth replay, or revocation state; migration replay "
                "here means immutable schema application only."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.apply_migrations",
                "audit_lineage",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.apply_migrations does "
                "not emit audit or persist audit lineage; the immutable migration "
                "ledger is schema history rather than actor audit."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.apply_migrations",
                "remote_http",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.apply_migrations is "
                "not an HTTP boundary and does not perform HTTP; it runs below startup "
                "and operator transport handling."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.close",
                "invalid_or_protocol",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.close has no "
                "caller-controlled input and does not parse protocol input; it follows "
                "the ownership flag fixed at construction."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.close",
                "expiry_replay_or_revocation",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.close does not own "
                "expiry, replay, or revocation state; it only releases a "
                "repository-owned database connection."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.close",
                "rollback_or_no_partial_state",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.close performs no "
                "durable write and does not open a transaction; transaction completion "
                "remains owned by the unit of work."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.close",
                "audit_lineage",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.close does not emit "
                "audit or persist audit lineage; it performs only internal connection "
                "lifecycle cleanup."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.close",
                "remote_http",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.close is not an HTTP "
                "boundary and does not perform HTTP; it runs below all request and "
                "response handling."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.connect",
                "expiry_replay_or_revocation",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.connect does not own "
                "expiry, replay, or revocation state; it only establishes the "
                "configured PostgreSQL adapter connection."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.connect",
                "audit_lineage",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.connect does not emit "
                "audit or persist audit lineage; deployment startup owns operational "
                "connection failure reporting."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.connect",
                "remote_http",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.connect is not an "
                "HTTP boundary and does not perform HTTP; it runs only as internal "
                "database startup plumbing."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.health_check",
                "expiry_replay_or_revocation",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.health_check does not "
                "own expiry, replay, or revocation state; it only reports whether a "
                "fixed internal database probe succeeds."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.health_check",
                "rollback_or_no_partial_state",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.health_check is "
                "read-only and performs no durable write; it does not open a "
                "transaction or leave partial repository state."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.health_check",
                "audit_lineage",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.health_check does not "
                "emit audit or persist audit lineage; operational health reporting is "
                "separate from actor audit events."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.health_check",
                "remote_http",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.health_check is not "
                "an HTTP boundary and does not perform HTTP; readiness routes consume "
                "only its bounded boolean result."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.transaction",
                "invalid_or_protocol",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.transaction has no "
                "caller-controlled input and does not parse protocol input; it creates "
                "an internal unit of work around the injected connection."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.transaction",
                "expiry_replay_or_revocation",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.transaction does not "
                "own expiry, replay, or revocation decisions; domain services validate "
                "lifecycle state within the transaction."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.transaction",
                "audit_lineage",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.transaction does not "
                "emit audit or persist audit lineage by itself; service operations "
                "append their own audit records inside the unit of work."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.transaction",
                "leak_safety",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.transaction does not "
                "receive secret material and returns only an internal unit-of-work "
                "boundary without SQL or connection details."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.transaction",
                "remote_http",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.transaction is not an "
                "HTTP boundary and does not perform HTTP; it runs below authenticated "
                "service orchestration."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.__init__",
                "invalid_or_protocol",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.__init__ receives only "
                "validated input as an already-created psycopg connection and does not "
                "parse protocol input or request payloads."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.__init__",
                "expiry_replay_or_revocation",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.__init__ does not own "
                "expiry, replay, or revocation state; it only stores an opaque database "
                "connection adapter."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.__init__",
                "rollback_or_no_partial_state",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.__init__ performs no "
                "durable write and does not open a transaction; construction only "
                "stores the injected raw connection."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.__init__",
                "audit_lineage",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.__init__ does not emit "
                "audit or persist audit lineage; repository and service operations own "
                "their audited events."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.__init__",
                "leak_safety",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.__init__ returns no "
                "caller-visible data and does not receive secret material directly; "
                "the connection remains internal."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.__init__",
                "remote_http",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.__init__ is not an HTTP "
                "boundary and does not perform HTTP; it constructs only a local "
                "database adapter."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.begin",
                "invalid_or_protocol",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.begin has no "
                "caller-controlled input and does not parse protocol input; it emits "
                "the fixed internal BEGIN statement."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.begin",
                "expiry_replay_or_revocation",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.begin does not own "
                "expiry, replay, or revocation state; it only opens the surrounding "
                "repository transaction."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.begin",
                "audit_lineage",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.begin does not emit "
                "audit or persist audit lineage; transaction callers own any related "
                "domain audit event."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.begin",
                "leak_safety",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.begin returns no "
                "caller-visible data and does not receive secret material; it executes "
                "only a fixed statement."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.begin",
                "remote_http",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.begin is not an HTTP "
                "boundary and does not perform HTTP; it runs below repository "
                "transaction handling."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.close",
                "invalid_or_protocol",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.close has no "
                "caller-controlled input and does not parse protocol input; it closes "
                "only its stored raw connection."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.close",
                "expiry_replay_or_revocation",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.close does not own "
                "expiry, replay, or revocation state; it only releases the internal "
                "database connection."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.close",
                "rollback_or_no_partial_state",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.close performs no "
                "durable write and does not open a transaction; the enclosing unit of "
                "work owns rollback."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.close",
                "audit_lineage",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.close does not emit "
                "audit or persist audit lineage; connection cleanup is not an actor "
                "audit event."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.close",
                "leak_safety",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.close returns no "
                "caller-visible data and does not receive secret material; it "
                "delegates only to raw connection close."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.close",
                "remote_http",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.close is not an HTTP "
                "boundary and does not perform HTTP; it is local connection lifecycle "
                "plumbing."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.commit",
                "invalid_or_protocol",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.commit has no "
                "caller-controlled input and does not parse protocol input; it commits "
                "only the current internal transaction."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.commit",
                "expiry_replay_or_revocation",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.commit does not own "
                "expiry, replay, or revocation decisions; repository services validate "
                "lifecycle state before commit."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.commit",
                "audit_lineage",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.commit does not emit "
                "audit or persist audit lineage; audited domain records must already "
                "be part of the committed unit of work."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.commit",
                "leak_safety",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.commit returns no "
                "caller-visible data and does not receive secret material; it "
                "delegates only to the raw commit operation."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.commit",
                "remote_http",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.commit is not an HTTP "
                "boundary and does not perform HTTP; it runs below repository "
                "transaction handling."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.query_all",
                "expiry_replay_or_revocation",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.query_all does not own "
                "expiry, replay, or revocation state; it only maps rows returned by a "
                "repository-generated statement."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.query_all",
                "rollback_or_no_partial_state",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.query_all is read-only "
                "and performs no durable write; it does not open a transaction or "
                "leave partial state."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.query_all",
                "audit_lineage",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.query_all does not emit "
                "audit or persist audit lineage; calling repository services own any "
                "audit requirements."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.query_all",
                "remote_http",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.query_all is not an HTTP "
                "boundary and does not perform HTTP; it runs below repository and "
                "transport layers."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.query_one",
                "expiry_replay_or_revocation",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.query_one does not own "
                "expiry, replay, or revocation state; it only maps one row returned by "
                "a repository-generated statement."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.query_one",
                "rollback_or_no_partial_state",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.query_one is read-only "
                "and performs no durable write; it does not open a transaction or "
                "leave partial state."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.query_one",
                "audit_lineage",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.query_one does not emit "
                "audit or persist audit lineage; calling repository services own any "
                "audit requirements."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.query_one",
                "remote_http",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.query_one is not an HTTP "
                "boundary and does not perform HTTP; it runs below repository and "
                "transport layers."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.rollback",
                "invalid_or_protocol",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.rollback has no "
                "caller-controlled input and does not parse protocol input; it rolls "
                "back only the current internal transaction."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.rollback",
                "expiry_replay_or_revocation",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.rollback does not own "
                "expiry, replay, or revocation decisions; it reverses only the current "
                "database transaction."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.rollback",
                "audit_lineage",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.rollback does not emit "
                "audit or persist audit lineage; the enclosing service records any "
                "denial or failure audit atomically."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.rollback",
                "leak_safety",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.rollback returns no "
                "caller-visible data and does not receive secret material; it "
                "delegates only to raw rollback."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.rollback",
                "remote_http",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.rollback is not an HTTP "
                "boundary and does not perform HTTP; it runs below repository "
                "transaction handling."
            ),
            (
                "formowl_auth.postgres",
                "oauth_migration_path",
                "invalid_or_protocol",
            ): (
                "formowl_auth.postgres.oauth_migration_path has no caller-controlled "
                "input and does not parse protocol input; it resolves one "
                "repository-owned migration filename."
            ),
            (
                "formowl_auth.postgres",
                "oauth_migration_path",
                "expiry_replay_or_revocation",
            ): (
                "formowl_auth.postgres.oauth_migration_path does not own expiry, "
                "replay, or revocation state; it only identifies the immutable OAuth "
                "schema migration file."
            ),
            (
                "formowl_auth.postgres",
                "oauth_migration_path",
                "rollback_or_no_partial_state",
            ): (
                "formowl_auth.postgres.oauth_migration_path performs no durable write "
                "and does not open a transaction; it constructs only an internal "
                "pathlib value."
            ),
            (
                "formowl_auth.postgres",
                "oauth_migration_path",
                "audit_lineage",
            ): (
                "formowl_auth.postgres.oauth_migration_path does not emit audit or "
                "persist audit lineage; schema path resolution is not an actor or "
                "lifecycle audit event."
            ),
            (
                "formowl_auth.postgres",
                "oauth_migration_path",
                "remote_http",
            ): (
                "formowl_auth.postgres.oauth_migration_path is not an HTTP boundary "
                "and does not perform HTTP; it runs below migration and startup "
                "orchestration."
            ),
        }
        expected_target_n_a.update(
            {
                (
                    "formowl_graph.storage.postgres",
                    "PostgreSQLMigrationResult.to_safe_dict",
                    "invalid_or_protocol",
                ): (
                    "formowl_graph.storage.postgres.PostgreSQLMigrationResult."
                    "to_safe_dict receives only validated input from its immutable "
                    "result fields and does not parse protocol input or caller payloads."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "PostgreSQLMigrationResult.to_safe_dict",
                    "expiry_replay_or_revocation",
                ): (
                    "formowl_graph.storage.postgres.PostgreSQLMigrationResult."
                    "to_safe_dict does not own expiry, replay, or revocation state; it "
                    "summarizes completed schema migration counts only."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "PostgreSQLMigrationResult.to_safe_dict",
                    "rollback_or_no_partial_state",
                ): (
                    "formowl_graph.storage.postgres.PostgreSQLMigrationResult."
                    "to_safe_dict performs no durable write and does not open a "
                    "transaction; it creates a detached scalar dictionary."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "PostgreSQLMigrationResult.to_safe_dict",
                    "audit_lineage",
                ): (
                    "formowl_graph.storage.postgres.PostgreSQLMigrationResult."
                    "to_safe_dict does not emit audit or persist audit lineage; it "
                    "serializes operational migration summary data only."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "PostgreSQLMigrationResult.to_safe_dict",
                    "remote_http",
                ): (
                    "formowl_graph.storage.postgres.PostgreSQLMigrationResult."
                    "to_safe_dict is not an HTTP boundary and does not perform HTTP; "
                    "callers decide whether to expose its fixed safe shape."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "PostgreSQLMigrationRunner.apply_pending",
                    "audit_lineage",
                ): (
                    "formowl_graph.storage.postgres.PostgreSQLMigrationRunner."
                    "apply_pending does not emit audit or persist actor audit lineage; "
                    "the migration ledger records immutable schema history only."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "PostgreSQLMigrationRunner.apply_pending",
                    "remote_http",
                ): (
                    "formowl_graph.storage.postgres.PostgreSQLMigrationRunner."
                    "apply_pending is not an HTTP boundary and does not perform HTTP; "
                    "startup orchestration owns transport responses."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "PostgreSQLMigrationRunner.migration_replay",
                    "expiry_replay_or_revocation",
                ): (
                    "formowl_graph.storage.postgres.PostgreSQLMigrationRunner."
                    "migration_replay does not own expiry, OAuth replay, or revocation "
                    "state; its replay is limited to deterministic schema statements."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "PostgreSQLMigrationRunner.migration_replay",
                    "audit_lineage",
                ): (
                    "formowl_graph.storage.postgres.PostgreSQLMigrationRunner."
                    "migration_replay does not emit audit or persist actor audit "
                    "lineage; it is an isolated compatibility migration helper."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "PostgreSQLMigrationRunner.migration_replay",
                    "remote_http",
                ): (
                    "formowl_graph.storage.postgres.PostgreSQLMigrationRunner."
                    "migration_replay is not an HTTP boundary and does not perform "
                    "HTTP; adapter tests call it below transport handling."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "PostgresMigration.from_file",
                    "invalid_or_protocol",
                ): (
                    "formowl_graph.storage.postgres.PostgresMigration.from_file "
                    "receives only validated input from private repository migration "
                    "discovery and does not parse caller protocol payloads."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "PostgresMigration.from_file",
                    "expiry_replay_or_revocation",
                ): (
                    "formowl_graph.storage.postgres.PostgresMigration.from_file has no "
                    "temporal state and does not own expiry, replay, or revocation "
                    "decisions; it builds immutable migration metadata."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "PostgresMigration.from_file",
                    "rollback_or_no_partial_state",
                ): (
                    "formowl_graph.storage.postgres.PostgresMigration.from_file "
                    "performs no durable write and does not open a transaction; it "
                    "returns one detached immutable descriptor."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "PostgresMigration.from_file",
                    "audit_lineage",
                ): (
                    "formowl_graph.storage.postgres.PostgresMigration.from_file does "
                    "not emit audit or persist actor lineage; schema migration "
                    "orchestration owns operational reporting."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "PostgresMigration.from_file",
                    "remote_http",
                ): (
                    "formowl_graph.storage.postgres.PostgresMigration.from_file is not "
                    "an HTTP boundary and does not perform HTTP; it reads a "
                    "repository-owned migration file locally."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "_contains_executable_sql",
                    "invalid_or_protocol",
                ): (
                    "formowl_graph.storage.postgres._contains_executable_sql accepts no "
                    "protocol input and examines only an internal SQL fragment already "
                    "isolated by the migration splitter."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "_contains_executable_sql",
                    "expiry_replay_or_revocation",
                ): (
                    "formowl_graph.storage.postgres._contains_executable_sql has no "
                    "temporal state and does not own expiry, replay, or revocation; it "
                    "returns one boolean classification."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "_contains_executable_sql",
                    "rollback_or_no_partial_state",
                ): (
                    "formowl_graph.storage.postgres._contains_executable_sql performs "
                    "no durable write and mutates no repository state; it evaluates a "
                    "temporary string only."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "_contains_executable_sql",
                    "audit_lineage",
                ): (
                    "formowl_graph.storage.postgres._contains_executable_sql does not "
                    "emit audit and has no audit side effect; migration orchestration "
                    "records schema history separately."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "_contains_executable_sql",
                    "remote_http",
                ): (
                    "formowl_graph.storage.postgres._contains_executable_sql runs below "
                    "the HTTP boundary and has no remote transport behavior; it "
                    "performs local string classification."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "_migration_ledger_sql",
                    "invalid_or_protocol",
                ): (
                    "formowl_graph.storage.postgres._migration_ledger_sql accepts no "
                    "protocol input and returns one fixed internal ledger definition "
                    "without caller-controlled fields."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "_migration_ledger_sql",
                    "expiry_replay_or_revocation",
                ): (
                    "formowl_graph.storage.postgres._migration_ledger_sql does not own "
                    "expiry, replay, or revocation state; it defines immutable "
                    "schema-history columns and constraints."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "_migration_ledger_sql",
                    "rollback_or_no_partial_state",
                ): (
                    "formowl_graph.storage.postgres._migration_ledger_sql performs no "
                    "durable write and does not open a transaction; the runner "
                    "executes its returned statement."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "_migration_ledger_sql",
                    "audit_lineage",
                ): (
                    "formowl_graph.storage.postgres._migration_ledger_sql does not emit "
                    "audit or persist actor lineage; it constructs only internal "
                    "schema-history SQL."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "_migration_ledger_sql",
                    "remote_http",
                ): (
                    "formowl_graph.storage.postgres._migration_ledger_sql is not an "
                    "HTTP boundary and does not perform HTTP; database startup code "
                    "consumes the internal string."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "_migration_version",
                    "audit_lineage",
                ): (
                    "formowl_graph.storage.postgres._migration_version does not emit "
                    "audit and has no audit side effect; it validates one migration "
                    "identifier locally."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "_migration_version",
                    "remote_http",
                ): (
                    "formowl_graph.storage.postgres._migration_version is not an HTTP "
                    "boundary and does not perform HTTP; it returns an internal positive "
                    "integer."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "_split_sql_statements",
                    "expiry_replay_or_revocation",
                ): (
                    "formowl_graph.storage.postgres._split_sql_statements has no "
                    "temporal state and does not own expiry, replay, or revocation; it "
                    "tokenizes one in-memory SQL document."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "_split_sql_statements",
                    "rollback_or_no_partial_state",
                ): (
                    "formowl_graph.storage.postgres._split_sql_statements performs no "
                    "durable write and mutates no repository state; it returns a "
                    "detached tuple of strings."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "_split_sql_statements",
                    "audit_lineage",
                ): (
                    "formowl_graph.storage.postgres._split_sql_statements does not emit "
                    "audit or persist audit lineage; migration execution records "
                    "operational history elsewhere."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "_split_sql_statements",
                    "remote_http",
                ): (
                    "formowl_graph.storage.postgres._split_sql_statements runs below "
                    "the HTTP boundary and has no remote transport behavior; it parses "
                    "repository migration text locally."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "_validate_applied_migration",
                    "audit_lineage",
                ): (
                    "formowl_graph.storage.postgres._validate_applied_migration does "
                    "not emit audit or persist actor lineage; it compares one ledger "
                    "row with immutable manifest metadata."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "_validate_applied_migration",
                    "remote_http",
                ): (
                    "formowl_graph.storage.postgres._validate_applied_migration is not "
                    "an HTTP boundary and does not perform HTTP; the migration runner "
                    "calls it inside a database transaction."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "_validated_migration_ledger",
                    "audit_lineage",
                ): (
                    "formowl_graph.storage.postgres._validated_migration_ledger does "
                    "not emit audit and has no audit side effect; it validates "
                    "schema-history rows before migration replay."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "_validated_migration_ledger",
                    "remote_http",
                ): (
                    "formowl_graph.storage.postgres._validated_migration_ledger runs "
                    "below the HTTP boundary and has no remote transport behavior; it "
                    "returns an internal lookup."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "_validated_migration_manifest",
                    "audit_lineage",
                ): (
                    "formowl_graph.storage.postgres._validated_migration_manifest does "
                    "not emit audit or persist actor lineage; it validates immutable "
                    "migration descriptors before execution."
                ),
                (
                    "formowl_graph.storage.postgres",
                    "_validated_migration_manifest",
                    "remote_http",
                ): (
                    "formowl_graph.storage.postgres._validated_migration_manifest is "
                    "not an HTTP boundary and does not perform HTTP; it returns a "
                    "validated internal tuple."
                ),
            }
        )
        expected_hygiene_n_a = {
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.append_audit_log",
                "expiry_replay_or_revocation",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.append_audit_log does "
                "not own expiry, replay, or revocation decisions; it persists an audit "
                "record whose lifecycle outcome was already determined by the calling "
                "service."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.append_audit_log",
                "remote_http",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.append_audit_log is "
                "not an HTTP boundary and does not perform HTTP; it persists one "
                "repository audit model below the transport layer."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.complete_owner_bootstrap",
                "audit_lineage",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "complete_owner_bootstrap does not emit audit or persist audit lineage; "
                "it changes bootstrap completion state while the calling bridge owns "
                "the service audit event."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.complete_owner_bootstrap",
                "remote_http",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "complete_owner_bootstrap is not an HTTP boundary and does not perform "
                "HTTP; it updates bootstrap state inside repository transaction "
                "orchestration."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.count_active_workspace_members",
                "invalid_or_protocol",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "count_active_workspace_members receives only validated input from the "
                "OAuth service and does not parse protocol input; its workspace "
                "identifier is a parameterized query value."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.count_active_workspace_members",
                "expiry_replay_or_revocation",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "count_active_workspace_members does not own expiry, replay, or "
                "revocation decisions; it counts current membership rows without "
                "applying token or invitation lifecycle policy."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.count_active_workspace_members",
                "rollback_or_no_partial_state",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "count_active_workspace_members is read-only and performs no durable "
                "write; it returns a scalar count without opening or committing a "
                "transaction itself."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.count_active_workspace_members",
                "audit_lineage",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "count_active_workspace_members does not emit audit or persist audit "
                "lineage; it performs only a membership count for higher-level "
                "authorization logic."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.count_active_workspace_members",
                "remote_http",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "count_active_workspace_members is not an HTTP boundary and has no "
                "remote transport behavior; repository callers consume its integer "
                "result below response serialization."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.fail_transaction",
                "rollback_or_no_partial_state",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.fail_transaction does "
                "not open a transaction or commit partial state; it issues one guarded "
                "update inside the enclosing unit of work that owns rollback."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.fail_transaction",
                "audit_lineage",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.fail_transaction does "
                "not emit audit or persist audit lineage; the OAuth service owns the "
                "corresponding audited failure decision."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.fail_transaction",
                "remote_http",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.fail_transaction is "
                "not an HTTP boundary and does not perform HTTP; it executes a guarded "
                "repository update below transport handling."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.find_pending_owner_invitations",
                "rollback_or_no_partial_state",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "find_pending_owner_invitations is read-only and performs no durable "
                "write; optional row locks remain scoped to the enclosing unit of work."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.find_pending_owner_invitations",
                "audit_lineage",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "find_pending_owner_invitations does not emit audit or persist audit "
                "lineage; it returns matching invitation models for audited service "
                "decisions."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.find_pending_owner_invitations",
                "remote_http",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "find_pending_owner_invitations is not an HTTP boundary and has no "
                "remote transport behavior; it performs a parameterized repository "
                "query."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_invitation",
                "invalid_or_protocol",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.get_invitation "
                "receives only validated input from the OAuth service and does not "
                "parse protocol input; the invitation identifier is parameterized."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_invitation",
                "expiry_replay_or_revocation",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.get_invitation does "
                "not own expiry, replay, or revocation decisions; it returns persisted "
                "invitation state for caller-side lifecycle validation."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_invitation",
                "rollback_or_no_partial_state",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.get_invitation is "
                "read-only and performs no durable write; it converts at most one "
                "selected row into a detached contract model."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_invitation",
                "audit_lineage",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.get_invitation does "
                "not emit audit and has no audit side effect; higher-level invitation "
                "workflows own decision lineage."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_invitation",
                "remote_http",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.get_invitation is not "
                "an HTTP boundary and does not perform HTTP; it returns an internal "
                "model beneath the connected response layer."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_owner_bootstrap",
                "invalid_or_protocol",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.get_owner_bootstrap "
                "receives only validated input from the OAuth service and does not "
                "parse protocol input; workspace lookup values are parameterized."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_owner_bootstrap",
                "rollback_or_no_partial_state",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.get_owner_bootstrap "
                "is read-only and performs no durable write; optional row locking "
                "remains controlled by the enclosing transaction."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_owner_bootstrap",
                "audit_lineage",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.get_owner_bootstrap "
                "does not emit audit or persist audit lineage; bootstrap workflow "
                "decisions remain owned by the calling bridge."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_owner_bootstrap",
                "remote_http",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository.get_owner_bootstrap "
                "is not an HTTP boundary and has no remote transport behavior; it "
                "performs one internal repository lookup."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_owner_bootstrap_by_invitation",
                "expiry_replay_or_revocation",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "get_owner_bootstrap_by_invitation does not own expiry, replay, or "
                "revocation decisions; it returns persisted bootstrap state for bridge "
                "validation."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_owner_bootstrap_by_invitation",
                "rollback_or_no_partial_state",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "get_owner_bootstrap_by_invitation is read-only and performs no "
                "durable write; any requested row lock belongs to the enclosing unit "
                "of work."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_owner_bootstrap_by_invitation",
                "audit_lineage",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "get_owner_bootstrap_by_invitation does not emit audit and has no audit "
                "side effect; callers own bootstrap decision lineage."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_owner_bootstrap_by_invitation",
                "remote_http",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "get_owner_bootstrap_by_invitation is not an HTTP boundary and does "
                "not perform HTTP; it returns one internal contract model."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.upsert_owner_bootstrap",
                "audit_lineage",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "upsert_owner_bootstrap does not emit audit or persist audit lineage; "
                "the bridge records service attribution around the guarded bootstrap "
                "insert."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.upsert_owner_bootstrap",
                "remote_http",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "upsert_owner_bootstrap is not an HTTP boundary and has no remote "
                "transport behavior; it executes a parameterized repository insert."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.execute",
                "invalid_or_protocol",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.execute receives only "
                "validated input as repository-generated SQLStatement values and does "
                "not parse protocol input at the adapter boundary."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.execute",
                "expiry_replay_or_revocation",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.execute does not own "
                "expiry, replay, or revocation decisions; it forwards one "
                "already-authorized statement to the database driver."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.execute",
                "rollback_or_no_partial_state",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.execute does not open a "
                "transaction or commit partial state; the enclosing repository unit of "
                "work exclusively owns commit and rollback."
            ),
            (
                "formowl_auth.postgres",
                "PsycopgOAuthConnection.execute",
                "remote_http",
            ): (
                "formowl_auth.postgres.PsycopgOAuthConnection.execute is not an HTTP "
                "boundary and does not perform HTTP; it operates entirely below the "
                "connected transport and response layers."
            ),
        }
        expected_preserved_n_a = {
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.remove_workspace_member",
                "expiry_replay_or_revocation",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "remove_workspace_member does not own expiry, replay, or revocation "
                "policy; it updates only the membership removed_at column under an "
                "active-row guard while the caller orchestrates token-session "
                "lifecycle."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.remove_workspace_member",
                "rollback_or_no_partial_state",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "remove_workspace_member emits one parameterized UPDATE through an "
                "injected connection and does not open a transaction; the operator "
                "unit of work owns commit, rollback, and cross-write atomicity."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.remove_workspace_member",
                "audit_lineage",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "remove_workspace_member does not emit audit or persist audit lineage; "
                "the audited OperatorDirectory transaction owns actor, target, reason, "
                "and membership lineage."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.remove_workspace_member",
                "remote_http",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "remove_workspace_member is not an HTTP boundary and has no remote "
                "transport behavior; it only emits local parameterized SQL below route "
                "and response handling."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.restore_workspace_member",
                "expiry_replay_or_revocation",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "restore_workspace_member does not own expiry, replay, or revocation "
                "policy; it only clears membership removed_at under a removed-row "
                "guard and never changes OAuth token-session state."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.restore_workspace_member",
                "rollback_or_no_partial_state",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "restore_workspace_member emits one parameterized UPDATE through an "
                "injected connection and does not open a transaction; the operator "
                "unit of work owns commit, rollback, and cross-write atomicity."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.restore_workspace_member",
                "audit_lineage",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "restore_workspace_member does not emit audit or persist audit lineage; "
                "the audited OperatorDirectory transaction owns actor, target, reason, "
                "and membership lineage."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.restore_workspace_member",
                "remote_http",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "restore_workspace_member is not an HTTP boundary and has no remote "
                "transport behavior; it only emits local parameterized SQL below route "
                "and response handling."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository." "revoke_active_token_sessions_for_membership",
                "rollback_or_no_partial_state",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "revoke_active_token_sessions_for_membership emits one parameterized "
                "UPDATE through an injected connection and does not open a transaction; "
                "the operator unit of work owns commit, rollback, and cross-write "
                "atomicity."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository." "revoke_active_token_sessions_for_membership",
                "audit_lineage",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "revoke_active_token_sessions_for_membership does not emit audit or "
                "persist audit lineage; the audited OperatorDirectory transaction owns "
                "actor, target, reason, and revoked-session count lineage."
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository." "revoke_active_token_sessions_for_membership",
                "remote_http",
            ): (
                "formowl_auth.postgres.PostgreSQLOAuthRepository."
                "revoke_active_token_sessions_for_membership is not an HTTP boundary "
                "and has no remote transport behavior; it only emits local "
                "parameterized SQL below route and response handling."
            ),
        }
        expected_later_onboarded_auth_keys = {
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.list_issue20_live_audit_rows",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.consume_authorization_code",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.consume_transaction",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.find_active_invitations",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.find_external_identity",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.find_users_by_email",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_active_workspace_member",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_authorization_code",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_client_authorization",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_client_authorization_by_id",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_external_identity",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_removed_workspace_member",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_token_session",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_transaction_by_state_hash",
            ),
            ("formowl_auth.postgres", "PostgreSQLOAuthRepository.get_user"),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.insert_authorization_code",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.insert_client_authorization",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.insert_external_identity",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.insert_invitation",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.insert_token_session",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.insert_transaction",
            ),
            ("formowl_auth.postgres", "PostgreSQLOAuthRepository.insert_user"),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.insert_workspace_member",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.list_active_grants",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.list_active_workspace_members",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository." "list_active_workspace_members_in_workspace",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.list_token_sessions",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.list_workspace_users",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.mark_invitation_accepted",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.revoke_token_session",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.update_external_identity_profile",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.update_user_profile",
            ),
            ("formowl_auth.postgres", "_iso_row"),
            ("formowl_auth.postgres", "_user_from_row"),
        }
        expected_category_keys = {
            (*key, category) for key in target_keys for category in REQUIRED_HARNESS_CATEGORIES
        }
        self.assertEqual(len(target_keys), 25)
        self.assertEqual(len(expected_target_tests), 71)
        self.assertEqual(len(expected_target_n_a), 104)
        self.assertTrue(set(expected_target_tests).isdisjoint(expected_target_n_a))
        self.assertEqual(
            set(expected_target_tests) | set(expected_target_n_a),
            expected_category_keys,
        )
        self.assertEqual(len(expected_hygiene_n_a), 34)
        self.assertEqual(len(expected_preserved_n_a), 11)
        self.assertEqual(len(expected_later_onboarded_auth_keys), 34)
        self.assertTrue(target_keys.issubset(bindings))
        self.assertTrue(target_keys.issubset(entries))

        target_auth_keys = {key for key in target_keys if key[0] == "formowl_auth.postgres"}
        target_graph_keys = target_keys - target_auth_keys
        hygiene_keys = {(module, qualname) for module, qualname, _ in expected_hygiene_n_a}
        preserved_keys = {(module, qualname) for module, qualname, _ in expected_preserved_n_a}
        auth_entries = {
            key: entry for key, entry in entries.items() if key[0] == "formowl_auth.postgres"
        }
        self.assertEqual(
            set(auth_entries),
            target_auth_keys | hygiene_keys | preserved_keys | expected_later_onboarded_auth_keys,
        )
        self.assertEqual(
            {
                key
                for key, entry in auth_entries.items()
                if entry["status"] == "onboarded" and key not in target_auth_keys
            },
            hygiene_keys | preserved_keys | expected_later_onboarded_auth_keys,
        )
        self.assertEqual(
            {key for key, entry in auth_entries.items() if entry["status"] == "pending"},
            set(),
        )

        def actual_n_a_reasons(
            keys: set[tuple[str, str]],
        ) -> dict[tuple[str, str, str], str]:
            return {
                (*key, category): reason
                for key in keys
                for category in REQUIRED_HARNESS_CATEGORIES
                if (reason := auth_entries[key]["categories"][category]["not_applicable_reason"])
                is not None
            }

        self.assertEqual(actual_n_a_reasons(hygiene_keys), expected_hygiene_n_a)
        self.assertEqual(actual_n_a_reasons(preserved_keys), expected_preserved_n_a)
        for key in sorted(hygiene_keys | preserved_keys):
            with self.subTest(non_target_auth_function=key):
                self.assertEqual(auth_entries[key]["status"], "onboarded")

        for key in sorted(expected_later_onboarded_auth_keys):
            with self.subTest(later_onboarded_auth_function=key):
                entry = auth_entries[key]
                self.assertEqual(entry["status"], "onboarded")
                self.assertEqual(entry["source_binding"], bindings[key])
                self.assertEqual(
                    set(entry["categories"]),
                    set(REQUIRED_HARNESS_CATEGORIES),
                )
                category_union: set[str] = set()
                for category in REQUIRED_HARNESS_CATEGORIES:
                    evidence = entry["categories"][category]
                    test_ids = evidence["test_ids"]
                    reason = evidence["not_applicable_reason"]
                    self.assertIn(evidence["pending_reason"], (None, ""))
                    self.assertNotEqual(bool(test_ids), bool(reason))
                    self.assertTrue(set(test_ids).issubset(collected))
                    category_union.update(test_ids)
                self.assertTrue(category_union)
                self.assertEqual(entry["test_ids"], sorted(category_union))

        for key in sorted(target_keys):
            with self.subTest(function_key=key):
                entry = entries[key]
                self.assertEqual(entry["status"], "onboarded")
                self.assertEqual(entry["source_binding"], bindings[key])
                self.assertEqual(
                    set(entry["categories"]),
                    set(REQUIRED_HARNESS_CATEGORIES),
                )
                category_union: set[str] = set()
                for category in REQUIRED_HARNESS_CATEGORIES:
                    category_key = (*key, category)
                    expected_ids = expected_target_tests.get(category_key, [])
                    expected_reason = expected_target_n_a.get(category_key)
                    evidence = entry["categories"][category]
                    self.assertEqual(evidence["test_ids"], expected_ids)
                    self.assertEqual(
                        evidence["not_applicable_reason"],
                        expected_reason,
                    )
                    self.assertIn(evidence["pending_reason"], (None, ""))
                    self.assertTrue(set(expected_ids).issubset(collected))
                    category_union.update(expected_ids)
                self.assertEqual(entry["test_ids"], sorted(category_union))

        evidence_owners: dict[str, set[tuple[str, str]]] = {}
        for item in manifest["functions"]:
            key = (item["module"], item["qualname"])
            for test_id in item["test_ids"]:
                evidence_owners.setdefault(test_id, set()).add(key)
        self.assertLessEqual(max(map(len, evidence_owners.values())), 12)

        protected_isolation_keys = set(auth_entries) | target_graph_keys
        protected_entries = {key: copy.deepcopy(entries[key]) for key in protected_isolation_keys}
        isolated_manifest = copy.deepcopy(manifest)
        expected_pending_blockers: set[str] = set()
        for entry in isolated_manifest["functions"]:
            key = (entry["module"], entry["qualname"])
            identity = ".".join(key)
            # Keep real auth and graph-batch evidence intact so isolated validation
            # cannot hide a mismatch in the rows this regression is responsible for.
            if key not in protected_isolation_keys:
                entry["status"] = "pending"
                entry["test_ids"] = []
                for category in REQUIRED_HARNESS_CATEGORIES:
                    evidence = entry["categories"][category]
                    evidence["test_ids"] = []
                    evidence["not_applicable_reason"] = None
                    evidence["pending_reason"] = (
                        f"{identity} is pending "
                        f"{category.replace('_', ' ')} evidence for current source diff "
                        f"{entry['source_binding']['diff_sha256']}; add a canonical "
                        "executable test or precise category-specific probe after the "
                        "production diff is frozen."
                    )
            if entry["status"] == "pending":
                expected_pending_blockers.add(f"changed function remains pending: {identity}")

        isolated_entries = {
            (entry["module"], entry["qualname"]): entry for entry in isolated_manifest["functions"]
        }
        self.assertEqual(
            {key: isolated_entries[key] for key in protected_isolation_keys},
            protected_entries,
        )
        validation = validate_function_harness_manifest(isolated_manifest)
        self.assertEqual(set(validation["blockers"]), expected_pending_blockers)
        self.assertEqual(len(validation["blockers"]), len(expected_pending_blockers))

    def test_postgres_crud_row_mapping_batch_is_manifest_onboarded(self) -> None:
        manifest = load_function_harness_manifest()
        root = Path(__file__).resolve().parents[1]
        bindings = changed_scoped_function_bindings(
            root,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )
        collected = collect_unittest_test_ids(root / "tests")
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}
        transaction_code_keys = {
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.consume_authorization_code",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.consume_transaction",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_authorization_code",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_transaction_by_state_hash",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.insert_authorization_code",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.insert_transaction",
            ),
        }
        invitation_keys = {
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.find_active_invitations",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.insert_invitation",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.mark_invitation_accepted",
            ),
        }
        identity_keys = {
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.find_external_identity",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.find_users_by_email",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_external_identity",
            ),
            ("formowl_auth.postgres", "PostgreSQLOAuthRepository.get_user"),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.insert_external_identity",
            ),
            ("formowl_auth.postgres", "PostgreSQLOAuthRepository.insert_user"),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.update_external_identity_profile",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.update_user_profile",
            ),
        }
        membership_keys = {
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_active_workspace_member",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_removed_workspace_member",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.insert_workspace_member",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.list_active_grants",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.list_active_workspace_members",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository." "list_active_workspace_members_in_workspace",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.list_workspace_users",
            ),
        }
        client_token_keys = {
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_client_authorization",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_client_authorization_by_id",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_token_session",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.insert_client_authorization",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.insert_token_session",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.list_token_sessions",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.revoke_token_session",
            ),
        }
        row_mapping_keys = {
            ("formowl_auth.postgres", "_iso_row"),
            ("formowl_auth.postgres", "_user_from_row"),
        }
        target_keys = (
            transaction_code_keys
            | invitation_keys
            | identity_keys
            | membership_keys
            | client_token_keys
            | row_mapping_keys
        )

        self.assertEqual(len(transaction_code_keys), 6)
        self.assertEqual(len(invitation_keys), 3)
        self.assertEqual(len(identity_keys), 8)
        self.assertEqual(len(membership_keys), 7)
        self.assertEqual(len(client_token_keys), 7)
        self.assertEqual(len(row_mapping_keys), 2)
        self.assertEqual(len(target_keys), 33)
        self.assertTrue(target_keys.issubset(bindings))
        self.assertTrue(target_keys.issubset(entries))
        self.assertTrue(collected)
        expected_unrelated_auth_keys = {
            ("formowl_auth.postgres", "PostgreSQLOAuthRepository.__init__"),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.append_audit_log",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.apply_migrations",
            ),
            ("formowl_auth.postgres", "PostgreSQLOAuthRepository.close"),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.complete_owner_bootstrap",
            ),
            ("formowl_auth.postgres", "PostgreSQLOAuthRepository.connect"),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.count_active_workspace_members",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.fail_transaction",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.find_pending_owner_invitations",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_invitation",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_owner_bootstrap",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_owner_bootstrap_by_invitation",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.health_check",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.list_issue20_live_audit_rows",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.remove_workspace_member",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.restore_workspace_member",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository." "revoke_active_token_sessions_for_membership",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.transaction",
            ),
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.upsert_owner_bootstrap",
            ),
            ("formowl_auth.postgres", "PsycopgOAuthConnection.__init__"),
            ("formowl_auth.postgres", "PsycopgOAuthConnection.begin"),
            ("formowl_auth.postgres", "PsycopgOAuthConnection.close"),
            ("formowl_auth.postgres", "PsycopgOAuthConnection.commit"),
            ("formowl_auth.postgres", "PsycopgOAuthConnection.execute"),
            ("formowl_auth.postgres", "PsycopgOAuthConnection.query_all"),
            ("formowl_auth.postgres", "PsycopgOAuthConnection.query_one"),
            ("formowl_auth.postgres", "PsycopgOAuthConnection.rollback"),
            ("formowl_auth.postgres", "oauth_migration_path"),
        }
        expected_unrelated_module_keys = {
            (
                "formowl_graph.storage.postgres",
                "PostgreSQLMigrationResult.to_safe_dict",
            ),
            (
                "formowl_graph.storage.postgres",
                "PostgreSQLMigrationRunner.apply_pending",
            ),
            (
                "formowl_graph.storage.postgres",
                "PostgreSQLMigrationRunner.migration_replay",
            ),
            ("formowl_graph.storage.postgres", "PostgresMigration.from_file"),
            ("formowl_graph.storage.postgres", "_contains_executable_sql"),
            ("formowl_graph.storage.postgres", "_migration_ledger_sql"),
            ("formowl_graph.storage.postgres", "_migration_version"),
            ("formowl_graph.storage.postgres", "_split_sql_statements"),
            ("formowl_graph.storage.postgres", "_validate_applied_migration"),
            ("formowl_graph.storage.postgres", "_validated_migration_ledger"),
            ("formowl_graph.storage.postgres", "_validated_migration_manifest"),
        }
        auth_entries = {
            key: entry for key, entry in entries.items() if key[0] == "formowl_auth.postgres"
        }
        self.assertEqual(
            set(auth_entries),
            target_keys | expected_unrelated_auth_keys,
        )
        self.assertEqual(
            {key for key, entry in auth_entries.items() if entry["status"] == "pending"},
            set(),
        )
        for key in sorted(expected_unrelated_auth_keys | expected_unrelated_module_keys):
            with self.subTest(unchanged_onboarded_key=key):
                self.assertEqual(entries[key]["status"], "onboarded")
                self.assertEqual(entries[key]["source_binding"], bindings[key])

        transaction_crud = (
            "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
            "test_transaction_and_code_crud_map_rows_and_bind_every_value"
        )
        transaction_parameter_binding = (
            "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
            "test_repository_keeps_untrusted_values_parameterized_and_uses_row_locks"
        )
        consume_code = (
            "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
            "test_consume_authorization_code_is_single_use_bound_and_transactional"
        )
        insert_code = (
            "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
            "test_insert_authorization_code_persists_only_hash_and_rolls_back_on_failure"
        )
        invitation_crud = (
            "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
            "test_invitation_and_identity_crud_map_rows_and_bind_every_value"
        )
        identity_reads = (
            "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
            "test_identity_reads_pin_keyed_sql_and_not_found_without_side_effects"
        )
        membership_crud = (
            "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
            "test_membership_and_grant_crud_map_rows_and_bind_every_value"
        )
        client_token_crud = (
            "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
            "test_client_authorization_and_token_crud_map_rows_and_bind_every_value"
        )
        token_session_lifecycle = (
            "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
            "test_token_session_reads_preserve_revoked_and_expired_rows_without_side_effects"
        )
        get_client_authorization = (
            "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
            "test_get_client_authorization_uses_composite_key_and_returns_revoked_rows"
        )
        get_client_authorization_by_id = (
            "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
            "test_get_client_authorization_by_id_is_parameterized_and_returns_revoked_rows"
        )
        insert_client_authorization = (
            "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
            "test_insert_client_authorization_preserves_bindings_and_rolls_back_unique_failure"
        )
        expected_category_map: dict[
            tuple[str, str],
            dict[str, list[str] | str],
        ] = {
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.consume_authorization_code",
            ): {
                "success": [transaction_crud],
                "invalid_or_protocol": [consume_code],
                "expiry_replay_or_revocation": [consume_code],
                "rollback_or_no_partial_state": [consume_code],
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "consume_authorization_code does not emit audit or persist audit "
                    "lineage; the OAuth bridge records the exchange decision inside "
                    "the same enclosing transaction."
                ),
                "leak_safety": [consume_code],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "consume_authorization_code is not an HTTP boundary and does not "
                    "perform HTTP; it executes one guarded parameterized update below "
                    "the token route."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.consume_transaction",
            ): {
                "success": [transaction_crud],
                "invalid_or_protocol": [transaction_crud],
                "expiry_replay_or_revocation": [transaction_crud],
                "rollback_or_no_partial_state": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "consume_transaction does not open a transaction or commit partial "
                    "state; it issues one guarded update inside the enclosing OAuth "
                    "unit of work."
                ),
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "consume_transaction does not emit audit or persist audit lineage; "
                    "the OAuth bridge owns the callback decision audit in the enclosing "
                    "transaction."
                ),
                "leak_safety": [transaction_crud],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "consume_transaction is not an HTTP boundary and does not perform "
                    "HTTP; it updates transaction state below callback transport "
                    "handling."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_authorization_code",
            ): {
                "success": [transaction_crud],
                "invalid_or_protocol": [transaction_parameter_binding],
                "expiry_replay_or_revocation": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "get_authorization_code does not own expiry, replay, or revocation "
                    "decisions; it returns persisted code state for the exchange "
                    "service to validate."
                ),
                "rollback_or_no_partial_state": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "get_authorization_code is read-only and performs no durable write; "
                    "an optional row lock remains scoped to the enclosing transaction."
                ),
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "get_authorization_code does not emit audit and has no audit side "
                    "effect; the exchange service owns decision lineage."
                ),
                "leak_safety": [transaction_parameter_binding],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "get_authorization_code is not an HTTP boundary and has no remote "
                    "transport behavior; it maps one internal repository row."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_transaction_by_state_hash",
            ): {
                "success": [transaction_crud],
                "invalid_or_protocol": [transaction_parameter_binding],
                "expiry_replay_or_revocation": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "get_transaction_by_state_hash does not own expiry, replay, or "
                    "revocation decisions; it returns persisted transaction state for "
                    "callback validation."
                ),
                "rollback_or_no_partial_state": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "get_transaction_by_state_hash is read-only and performs no durable "
                    "write; an optional row lock remains scoped to the enclosing "
                    "transaction."
                ),
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "get_transaction_by_state_hash does not emit audit or persist audit "
                    "lineage; callback orchestration owns the decision audit."
                ),
                "leak_safety": [transaction_parameter_binding],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "get_transaction_by_state_hash is not an HTTP boundary and does not "
                    "perform HTTP; it maps one internal repository row."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.insert_authorization_code",
            ): {
                "success": [transaction_crud],
                "invalid_or_protocol": [insert_code],
                "expiry_replay_or_revocation": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_authorization_code does not own expiry, replay, or "
                    "revocation decisions; it persists the already-validated one-time "
                    "code record."
                ),
                "rollback_or_no_partial_state": [insert_code],
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_authorization_code does not emit audit or persist audit "
                    "lineage; authorization issuance audit is owned by the bridge "
                    "transaction."
                ),
                "leak_safety": [insert_code],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_authorization_code is not an HTTP boundary and does not "
                    "perform HTTP; it persists one hashed-code row below response "
                    "generation."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.insert_transaction",
            ): {
                "success": [transaction_crud],
                "invalid_or_protocol": [transaction_crud],
                "expiry_replay_or_revocation": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_transaction does not own expiry, replay, or revocation "
                    "decisions; it persists the bridge-validated initial transaction "
                    "state."
                ),
                "rollback_or_no_partial_state": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_transaction does not open a transaction or commit partial "
                    "state; it emits one insert inside the enclosing authorization unit "
                    "of work."
                ),
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_transaction does not emit audit or persist audit lineage; "
                    "the authorization bridge owns request lineage in the same unit of "
                    "work."
                ),
                "leak_safety": [transaction_crud],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_transaction is not an HTTP boundary and has no remote "
                    "transport behavior; it persists one internal OAuth transaction "
                    "record."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.find_active_invitations",
            ): {
                "success": [invitation_crud],
                "invalid_or_protocol": [invitation_crud],
                "expiry_replay_or_revocation": [invitation_crud],
                "rollback_or_no_partial_state": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "find_active_invitations is read-only and performs no durable "
                    "write; its optional row lock remains scoped to the enclosing "
                    "callback transaction."
                ),
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "find_active_invitations does not emit audit or persist audit "
                    "lineage; callback orchestration owns the invitation decision "
                    "audit."
                ),
                "leak_safety": [invitation_crud],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "find_active_invitations is not an HTTP boundary and does not "
                    "perform HTTP; it returns guarded invitation rows below callback "
                    "transport handling."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.insert_invitation",
            ): {
                "success": [invitation_crud],
                "invalid_or_protocol": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_invitation does not parse protocol input or validate an "
                    "untrusted payload; it accepts an already-validated "
                    "OAuthInvitation contract."
                ),
                "expiry_replay_or_revocation": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_invitation does not own expiry, replay, or revocation "
                    "decisions; it persists only the bridge-validated initial "
                    "invitation state, while service workflows evaluate temporal "
                    "validity, acceptance, and current state."
                ),
                "rollback_or_no_partial_state": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_invitation does not open a transaction or commit "
                    "independently; it executes one parameter-bound insert inside the "
                    "caller's existing provisioning unit of work, which owns rollback "
                    "and atomicity."
                ),
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_invitation does not emit audit or persist audit lineage; "
                    "invitation provisioning owns the audit in the same transaction."
                ),
                "leak_safety": [invitation_crud],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_invitation is not an HTTP boundary and has no remote "
                    "transport behavior; it persists one internal invitation record."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.mark_invitation_accepted",
            ): {
                "success": [invitation_crud],
                "invalid_or_protocol": [invitation_crud],
                "expiry_replay_or_revocation": [invitation_crud],
                "rollback_or_no_partial_state": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "mark_invitation_accepted does not open a transaction or commit "
                    "independently; it executes one guarded parameter-bound update "
                    "inside the caller's existing callback unit of work, which owns "
                    "rollback and atomicity."
                ),
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "mark_invitation_accepted does not emit audit or persist audit "
                    "lineage; the callback transaction records the accepted-login "
                    "decision."
                ),
                "leak_safety": [invitation_crud],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "mark_invitation_accepted is not an HTTP boundary and does not "
                    "perform HTTP; it applies one current-state update below callback "
                    "transport handling."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.find_external_identity",
            ): {
                "success": [invitation_crud],
                "invalid_or_protocol": [identity_reads],
                "expiry_replay_or_revocation": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "find_external_identity does not own expiry, replay, or revocation "
                    "decisions; it returns only persisted identity candidates, while "
                    "the OAuth bridge validates current lifecycle state and "
                    "authorization."
                ),
                "rollback_or_no_partial_state": [identity_reads],
                "audit_lineage": [identity_reads],
                "leak_safety": [identity_reads],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "find_external_identity is not an HTTP boundary and does not "
                    "perform HTTP; it maps one internal identity row."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.find_users_by_email",
            ): {
                "success": [invitation_crud],
                "invalid_or_protocol": [identity_reads],
                "expiry_replay_or_revocation": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "find_users_by_email does not own expiry, replay, or revocation "
                    "decisions; it returns only persisted candidate user rows, while "
                    "the caller evaluates current lifecycle state and authorization."
                ),
                "rollback_or_no_partial_state": [identity_reads],
                "audit_lineage": [identity_reads],
                "leak_safety": [identity_reads],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "find_users_by_email is not an HTTP boundary and has no remote "
                    "transport behavior; it maps internal user rows."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_external_identity",
            ): {
                "success": [invitation_crud],
                "invalid_or_protocol": [identity_reads],
                "expiry_replay_or_revocation": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "get_external_identity does not own expiry, replay, or revocation "
                    "decisions; it returns only persisted identity state, while the "
                    "caller performs current authorization and lifecycle checks."
                ),
                "rollback_or_no_partial_state": [identity_reads],
                "audit_lineage": [identity_reads],
                "leak_safety": [identity_reads],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "get_external_identity is not an HTTP boundary and does not perform "
                    "HTTP; it maps one internal identity row."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_user",
            ): {
                "success": [invitation_crud],
                "invalid_or_protocol": [identity_reads],
                "expiry_replay_or_revocation": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository.get_user does not "
                    "own expiry, replay, or revocation decisions; it returns only "
                    "persisted user status, while the caller validates current "
                    "lifecycle state and authorization."
                ),
                "rollback_or_no_partial_state": [identity_reads],
                "audit_lineage": [identity_reads],
                "leak_safety": [identity_reads],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository.get_user is not an "
                    "HTTP boundary and has no remote transport behavior; it maps one "
                    "internal user row."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.insert_external_identity",
            ): {
                "success": [invitation_crud],
                "invalid_or_protocol": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_external_identity does not parse protocol input or validate "
                    "an untrusted payload; it accepts an already-validated "
                    "ExternalIdentity contract."
                ),
                "expiry_replay_or_revocation": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_external_identity does not own expiry, replay, or revocation "
                    "enforcement; it persists only the bridge-validated initial identity "
                    "state, while the OAuth bridge and protected service resolve current "
                    "repository-backed identity authorization."
                ),
                "rollback_or_no_partial_state": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_external_identity does not open a transaction or commit "
                    "independently; it executes one parameter-bound insert inside the "
                    "caller's existing login unit of work, which owns rollback and "
                    "atomicity."
                ),
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_external_identity does not emit audit or persist audit "
                    "lineage; login provisioning owns audit in the same transaction."
                ),
                "leak_safety": [invitation_crud],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_external_identity is not an HTTP boundary and does not "
                    "perform HTTP; it persists one internal identity record."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.insert_user",
            ): {
                "success": [invitation_crud],
                "invalid_or_protocol": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository.insert_user does "
                    "not parse protocol input or validate an untrusted payload; it "
                    "accepts an already-validated User contract."
                ),
                "expiry_replay_or_revocation": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository.insert_user does "
                    "not own expiry, replay, or revocation decisions; it persists only "
                    "the provisioning workflow's validated initial user state, while "
                    "service authority evaluates current status and authorization."
                ),
                "rollback_or_no_partial_state": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository.insert_user does "
                    "not open a transaction or commit independently; it executes one "
                    "parameter-bound insert inside the caller's existing provisioning "
                    "unit of work, which owns rollback and atomicity."
                ),
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository.insert_user does "
                    "not emit audit or persist audit lineage; provisioning owns audit "
                    "in the same transaction."
                ),
                "leak_safety": [invitation_crud],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository.insert_user is not "
                    "an HTTP boundary and has no remote transport behavior; it persists "
                    "one internal user record."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.update_external_identity_profile",
            ): {
                "success": [invitation_crud],
                "invalid_or_protocol": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "update_external_identity_profile does not parse protocol input; "
                    "the Google callback validates and normalizes profile values before "
                    "this repository update."
                ),
                "expiry_replay_or_revocation": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "update_external_identity_profile does not own expiry, replay, or "
                    "revocation decisions; it updates only profile metadata after "
                    "current identity authorization, while callback and service "
                    "authority validate identity state."
                ),
                "rollback_or_no_partial_state": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "update_external_identity_profile does not open a transaction or "
                    "commit independently; it executes one parameter-bound update "
                    "inside the caller's existing callback unit of work, which owns "
                    "rollback and atomicity."
                ),
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "update_external_identity_profile does not emit audit or persist "
                    "audit lineage; callback orchestration owns the login audit."
                ),
                "leak_safety": [invitation_crud],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "update_external_identity_profile is not an HTTP boundary and does "
                    "not perform HTTP; it updates internal profile fields."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.update_user_profile",
            ): {
                "success": [invitation_crud],
                "invalid_or_protocol": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "update_user_profile does not parse protocol input; the Google "
                    "callback validates and normalizes profile values before this "
                    "repository update."
                ),
                "expiry_replay_or_revocation": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "update_user_profile does not own expiry, replay, or revocation "
                    "decisions; it updates only profile metadata after current identity "
                    "authorization, while callback and service authority validate user "
                    "state."
                ),
                "rollback_or_no_partial_state": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "update_user_profile does not open a transaction or commit "
                    "independently; it executes one parameter-bound update inside the "
                    "caller's existing callback unit of work, which owns rollback and "
                    "atomicity."
                ),
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "update_user_profile does not emit audit or persist audit lineage; "
                    "callback orchestration owns the login audit."
                ),
                "leak_safety": [invitation_crud],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "update_user_profile is not an HTTP boundary and has no remote "
                    "transport behavior; it updates internal profile fields."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_active_workspace_member",
            ): {
                "success": [membership_crud],
                "invalid_or_protocol": [membership_crud],
                "expiry_replay_or_revocation": [membership_crud],
                "rollback_or_no_partial_state": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "get_active_workspace_member is read-only and performs no durable "
                    "write; its optional row lock remains scoped to the enclosing "
                    "authorization transaction."
                ),
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "get_active_workspace_member does not emit audit or persist audit "
                    "lineage; the protected operation owns membership decision audit."
                ),
                "leak_safety": [membership_crud],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "get_active_workspace_member is not an HTTP boundary and does not "
                    "perform HTTP; it maps one current membership row."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_removed_workspace_member",
            ): {
                "success": [membership_crud],
                "invalid_or_protocol": [membership_crud],
                "expiry_replay_or_revocation": [membership_crud],
                "rollback_or_no_partial_state": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "get_removed_workspace_member is read-only and performs no durable "
                    "write; its optional row lock remains scoped to the enclosing "
                    "operator transaction."
                ),
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "get_removed_workspace_member does not emit audit or persist audit "
                    "lineage; the operator workflow owns membership decision audit."
                ),
                "leak_safety": [membership_crud],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "get_removed_workspace_member is not an HTTP boundary and does not "
                    "perform HTTP; it maps one removed membership row."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.insert_workspace_member",
            ): {
                "success": [membership_crud],
                "invalid_or_protocol": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_workspace_member does not parse protocol input or validate "
                    "an untrusted payload; it accepts an already-validated "
                    "WorkspaceMember contract."
                ),
                "expiry_replay_or_revocation": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_workspace_member does not own expiry, replay, or revocation "
                    "decisions; it persists only the provisioning workflow's validated "
                    "active membership, while service authority evaluates current "
                    "membership state."
                ),
                "rollback_or_no_partial_state": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_workspace_member does not open a transaction or commit "
                    "independently; it executes one parameter-bound insert inside the "
                    "caller's existing provisioning unit of work, which owns rollback "
                    "and atomicity."
                ),
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_workspace_member does not emit audit or persist audit "
                    "lineage; provisioning owns audit in the same transaction."
                ),
                "leak_safety": [membership_crud],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_workspace_member is not an HTTP boundary and has no remote "
                    "transport behavior; it persists one internal membership record."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.list_active_grants",
            ): {
                "success": [membership_crud],
                "invalid_or_protocol": [membership_crud],
                "expiry_replay_or_revocation": [membership_crud],
                "rollback_or_no_partial_state": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "list_active_grants is read-only, performs no durable write, and "
                    "issues only a parameterized query for current grant rows without "
                    "opening a transaction or mutating repository state."
                ),
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "list_active_grants does not emit audit or persist audit lineage; "
                    "the protected operation owns grant decision audit."
                ),
                "leak_safety": [membership_crud],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "list_active_grants is not an HTTP boundary and does not perform "
                    "HTTP; it maps current internal grant rows."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.list_active_workspace_members",
            ): {
                "success": [membership_crud],
                "invalid_or_protocol": [membership_crud],
                "expiry_replay_or_revocation": [membership_crud],
                "rollback_or_no_partial_state": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "list_active_workspace_members is read-only, performs no durable "
                    "write, and issues only a parameterized query for current "
                    "membership rows without opening a transaction or mutating "
                    "repository state."
                ),
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "list_active_workspace_members does not emit audit or persist audit "
                    "lineage; the protected operation owns membership decision audit."
                ),
                "leak_safety": [membership_crud],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "list_active_workspace_members is not an HTTP boundary and has no "
                    "remote transport behavior; it maps current membership rows."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository." "list_active_workspace_members_in_workspace",
            ): {
                "success": [membership_crud],
                "invalid_or_protocol": [membership_crud],
                "expiry_replay_or_revocation": [membership_crud],
                "rollback_or_no_partial_state": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "list_active_workspace_members_in_workspace is read-only and "
                    "performs no durable write; its optional row locks remain scoped to "
                    "the enclosing operator transaction."
                ),
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "list_active_workspace_members_in_workspace does not emit audit or "
                    "persist audit lineage; the operator workflow owns membership "
                    "decision audit."
                ),
                "leak_safety": [membership_crud],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "list_active_workspace_members_in_workspace is not an HTTP boundary "
                    "and does not perform HTTP; it maps current membership rows."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.list_workspace_users",
            ): {
                "success": [membership_crud],
                "invalid_or_protocol": [membership_crud],
                "expiry_replay_or_revocation": [membership_crud],
                "rollback_or_no_partial_state": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "list_workspace_users performs only a parameterized read, does not "
                    "open a transaction, and mutates no durable repository state, so "
                    "rollback or partial-write behavior is semantically absent."
                ),
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "list_workspace_users does not emit audit or persist audit lineage; "
                    "the authorized operator lookup owns audit."
                ),
                "leak_safety": [membership_crud],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "list_workspace_users is not an HTTP boundary and does not perform "
                    "HTTP; it maps joined internal user and membership rows."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_client_authorization",
            ): {
                "success": [client_token_crud],
                "invalid_or_protocol": [get_client_authorization],
                "expiry_replay_or_revocation": [get_client_authorization],
                "rollback_or_no_partial_state": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "get_client_authorization is read-only, performs no durable write, "
                    "and executes only a parameterized composite-key lookup without "
                    "opening a transaction, committing state, or mutating repository "
                    "records."
                ),
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "get_client_authorization does not emit audit or persist audit "
                    "lineage; the OAuth bridge owns the client-authorization decision "
                    "audit."
                ),
                "leak_safety": [get_client_authorization],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "get_client_authorization is not an HTTP boundary and does not "
                    "perform HTTP; it maps one internal client-authorization row."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_client_authorization_by_id",
            ): {
                "success": [client_token_crud],
                "invalid_or_protocol": [get_client_authorization_by_id],
                "expiry_replay_or_revocation": [get_client_authorization_by_id],
                "rollback_or_no_partial_state": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "get_client_authorization_by_id is read-only and performs no "
                    "durable write; it executes one parameterized identifier lookup "
                    "without opening a transaction, committing, or mutating repository "
                    "state."
                ),
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "get_client_authorization_by_id does not emit audit or persist "
                    "audit lineage; the protected operation owns the authorization "
                    "decision audit."
                ),
                "leak_safety": [get_client_authorization_by_id],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "get_client_authorization_by_id is not an HTTP boundary and has no "
                    "remote transport behavior; it maps one internal authorization "
                    "row."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.get_token_session",
            ): {
                "success": [client_token_crud],
                "invalid_or_protocol": [client_token_crud],
                "expiry_replay_or_revocation": [token_session_lifecycle],
                "rollback_or_no_partial_state": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "get_token_session is read-only, performs no durable write, and "
                    "executes only a parameterized lookup without opening a "
                    "transaction, committing state, or mutating repository records."
                ),
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "get_token_session does not emit audit or persist audit lineage; "
                    "the protected call or operator lookup owns token-session decision "
                    "audit."
                ),
                "leak_safety": [client_token_crud],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "get_token_session is not an HTTP boundary and does not perform "
                    "HTTP; it maps one internal token-session row."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.insert_client_authorization",
            ): {
                "success": [client_token_crud],
                "invalid_or_protocol": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_client_authorization does not parse protocol input or "
                    "validate an untrusted payload; it accepts an already-validated "
                    "OAuthClientAuthorization contract."
                ),
                "expiry_replay_or_revocation": [insert_client_authorization],
                "rollback_or_no_partial_state": [insert_client_authorization],
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_client_authorization does not emit audit or persist audit "
                    "lineage; the OAuth bridge owns authorization issuance audit in "
                    "the same transaction."
                ),
                "leak_safety": [insert_client_authorization],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_client_authorization is not an HTTP boundary and has no "
                    "remote transport behavior; it persists one internal authorization "
                    "record."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.insert_token_session",
            ): {
                "success": [client_token_crud],
                "invalid_or_protocol": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_token_session does not parse protocol input or validate an "
                    "untrusted payload; it accepts an already-validated "
                    "OAuthTokenSession contract."
                ),
                "expiry_replay_or_revocation": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_token_session does not own expiry, replay, or revocation "
                    "decisions; it persists only the token service's validated initial "
                    "session state, while service authority evaluates current session "
                    "lifecycle."
                ),
                "rollback_or_no_partial_state": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_token_session does not open a transaction or commit "
                    "independently; it executes one parameter-bound insert inside the "
                    "caller's existing token-exchange unit of work, which owns rollback "
                    "and atomicity."
                ),
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_token_session does not emit audit or persist audit lineage; "
                    "the token exchange owns issuance audit in the same transaction."
                ),
                "leak_safety": [client_token_crud],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "insert_token_session is not an HTTP boundary and does not perform "
                    "HTTP; it persists one internal token-session record."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.list_token_sessions",
            ): {
                "success": [client_token_crud],
                "invalid_or_protocol": [client_token_crud],
                "expiry_replay_or_revocation": [token_session_lifecycle],
                "rollback_or_no_partial_state": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "list_token_sessions is read-only, performs no durable write, and "
                    "issues only a parameterized query for token-session rows without "
                    "opening a transaction or mutating repository state."
                ),
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "list_token_sessions does not emit audit or persist audit lineage; "
                    "the authorized operator directory owns lookup audit."
                ),
                "leak_safety": [client_token_crud],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "list_token_sessions is not an HTTP boundary and has no remote "
                    "transport behavior; it maps internal token-session rows."
                ),
            },
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.revoke_token_session",
            ): {
                "success": [client_token_crud],
                "invalid_or_protocol": [client_token_crud],
                "expiry_replay_or_revocation": [client_token_crud],
                "rollback_or_no_partial_state": [client_token_crud],
                "audit_lineage": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "revoke_token_session does not emit audit or persist audit lineage; "
                    "the audited revocation workflow owns actor, reason, and session "
                    "lineage."
                ),
                "leak_safety": [client_token_crud],
                "remote_http": (
                    "formowl_auth.postgres.PostgreSQLOAuthRepository."
                    "revoke_token_session is not an HTTP boundary and does not perform "
                    "HTTP; it emits one guarded internal session update."
                ),
            },
            ("formowl_auth.postgres", "_iso_row"): {
                "success": [membership_crud],
                "invalid_or_protocol": (
                    "formowl_auth.postgres._iso_row does not parse protocol input or "
                    "validate an untrusted payload; it normalizes one internal "
                    "repository row before a typed contract constructor runs."
                ),
                "expiry_replay_or_revocation": (
                    "formowl_auth.postgres._iso_row does not own expiry, replay, or "
                    "revocation decisions; it only preserves persisted lifecycle "
                    "values while normalizing datetime representation, and the caller "
                    "performs current authorization."
                ),
                "rollback_or_no_partial_state": (
                    "formowl_auth.postgres._iso_row is a pure in-memory row mapper and "
                    "performs no durable write or transaction operation."
                ),
                "audit_lineage": (
                    "formowl_auth.postgres._iso_row does not emit audit or persist "
                    "audit lineage; the repository operation and enclosing workflow "
                    "own decision audit."
                ),
                "leak_safety": (
                    "formowl_auth.postgres._iso_row returns no caller-visible data; it "
                    "normalizes one internal repository row only for typed constructors "
                    "and neither logs values, renders SQL, creates an error envelope, "
                    "nor exposes raw paths."
                ),
                "remote_http": (
                    "formowl_auth.postgres._iso_row is not an HTTP boundary and has no "
                    "remote transport behavior; it normalizes one in-memory database "
                    "row."
                ),
            },
            ("formowl_auth.postgres", "_user_from_row"): {
                "success": [invitation_crud],
                "invalid_or_protocol": (
                    "formowl_auth.postgres._user_from_row does not parse protocol input; "
                    "it maps one internal repository row through the validated User "
                    "contract."
                ),
                "expiry_replay_or_revocation": (
                    "formowl_auth.postgres._user_from_row does not own expiry, replay, "
                    "or revocation decisions; it only preserves persisted user status "
                    "while rebuilding the typed User, and the caller's repository "
                    "workflow performs current authorization."
                ),
                "rollback_or_no_partial_state": (
                    "formowl_auth.postgres._user_from_row is a pure in-memory mapper and "
                    "performs no durable write or transaction operation."
                ),
                "audit_lineage": (
                    "formowl_auth.postgres._user_from_row does not emit audit or persist "
                    "audit lineage; the authorized repository workflow owns lookup "
                    "decision audit."
                ),
                "leak_safety": (
                    "formowl_auth.postgres._user_from_row returns no caller-visible "
                    "data; it rebuilds one internal database row as a typed User only "
                    "for the repository caller and neither logs values nor creates a "
                    "public or error envelope."
                ),
                "remote_http": (
                    "formowl_auth.postgres._user_from_row is not an HTTP boundary and "
                    "does not perform HTTP; it maps one internal database row."
                ),
            },
        }
        self.assertEqual(
            set(expected_category_map),
            transaction_code_keys
            | invitation_keys
            | identity_keys
            | membership_keys
            | client_token_keys
            | row_mapping_keys,
        )
        for key in sorted(target_keys):
            with self.subTest(function_key=key):
                entry = entries[key]
                self.assertEqual(entry["status"], "onboarded")
                self.assertEqual(entry["source_binding"], bindings[key])
                self.assertEqual(
                    set(entry["categories"]),
                    set(REQUIRED_HARNESS_CATEGORIES),
                )
                category_union: set[str] = set()
                for category in REQUIRED_HARNESS_CATEGORIES:
                    expected = expected_category_map[key][category]
                    expected_ids = expected if isinstance(expected, list) else []
                    expected_reason = expected if isinstance(expected, str) else None
                    evidence = entry["categories"][category]
                    self.assertEqual(evidence["test_ids"], expected_ids)
                    self.assertEqual(
                        evidence["not_applicable_reason"],
                        expected_reason,
                    )
                    self.assertIn(evidence["pending_reason"], (None, ""))
                    self.assertTrue(set(expected_ids).issubset(collected))
                    category_union.update(expected_ids)
                self.assertTrue(category_union)
                self.assertEqual(entry["test_ids"], sorted(category_union))

        evidence_owners: dict[str, set[tuple[str, str]]] = {}
        for item in manifest["functions"]:
            key = (item["module"], item["qualname"])
            for test_id in item["test_ids"]:
                evidence_owners.setdefault(test_id, set()).add(key)
        self.assertLessEqual(max(map(len, evidence_owners.values())), 12)

    def test_runner_boundary_batch_is_manifest_onboarded(self) -> None:
        manifest = load_function_harness_manifest()
        root = Path(__file__).resolve().parents[1]
        bindings = changed_scoped_function_bindings(
            root,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )
        collected = collect_unittest_test_ids(root / "tests")
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}
        module = "scripts.issue20_runner_boundary"
        newly_onboarded_qualnames = {
            "acquire_invocation_lock",
            "decode_mountinfo_field",
            "invocation_lock_address",
            "main",
            "mount_options",
            "process_status",
            "trusted_executable",
            "trusted_invocation_lock_descriptor",
            "trusted_private_directory",
            "verify_held_invocation_lock",
        }
        refreshed_onboarded_qualnames = {"verify_inner_boundary"}
        affected_qualnames = newly_onboarded_qualnames | refreshed_onboarded_qualnames
        target_keys = {(module, qualname) for qualname in affected_qualnames}
        self.assertEqual(len(newly_onboarded_qualnames), 10)
        self.assertEqual(len(refreshed_onboarded_qualnames), 1)
        self.assertTrue(newly_onboarded_qualnames.isdisjoint(refreshed_onboarded_qualnames))
        self.assertEqual(len(target_keys), 11)
        self.assertTrue(target_keys.issubset(bindings))
        self.assertTrue(target_keys.issubset(entries))

        test_prefix = (
            "tests.test_issue20_containerized_evidence_runner."
            "Issue20ContainerizedEvidenceRunnerContractTest."
        )
        acquire_failures = (
            test_prefix + "test_acquire_invocation_lock_failure_matrix_closes_handles_and_retries"
        )
        decode_literal = (
            test_prefix
            + "test_mountinfo_decode_does_not_recursively_reinterpret_literal_escape_text"
        )
        lock_lifecycle = (
            test_prefix + "test_invocation_lock_is_fixed_kernel_bound_and_reusable_after_close"
        )
        path_swap = test_prefix + "test_lock_and_exec_keeps_validated_runner_inode_across_path_swap"
        main_dup2 = test_prefix + "test_main_dup2_failure_preserves_existing_fd9_and_releases_lock"
        main_exec_restore = (
            test_prefix
            + "test_main_post_dup2_exec_failure_restores_existing_fd9_and_closes_temporaries"
        )
        main_trust_predicates = (
            test_prefix
            + "test_main_lock_and_exec_rejects_aliases_and_each_untrusted_metadata_predicate"
        )
        main_failures = (
            test_prefix + "test_main_open_metadata_inheritable_and_dup_failures_are_bounded"
        )
        main_verify = test_prefix + "test_main_verify_held_lock_traces_success_and_closed_failure"
        kernel_parsers = (
            test_prefix + "test_mount_and_process_parsers_fail_closed_and_use_topmost_mount"
        )
        mount_decode = test_prefix + "test_mount_options_decodes_each_kernel_path_escape_once"
        prebound_busy = (
            test_prefix + "test_prebound_same_uid_address_returns_only_bounded_busy_error"
        )
        trusted_executable = (
            test_prefix + "test_trusted_executable_covers_metadata_and_oserror_matrix"
        )
        trusted_lock = (
            test_prefix
            + "test_lock_descriptor_validation_covers_type_address_and_duplicate_lifetime"
        )
        trusted_private = (
            test_prefix + "test_trusted_private_directory_covers_identity_errors_without_mutation"
        )
        inner_boundary = (
            test_prefix + "test_inner_boundary_rejects_forged_authority_and_scratch_links"
        )

        def n_a(qualname: str, detail: str) -> str:
            return f"{module}.{qualname} {detail}"

        expected: dict[str, dict[str, list[str] | str]] = {
            "acquire_invocation_lock": {
                "success": [acquire_failures, lock_lifecycle],
                "invalid_or_protocol": [acquire_failures, lock_lifecycle],
                "expiry_replay_or_revocation": n_a(
                    "acquire_invocation_lock",
                    "has no temporal state and does not own expiry, replay, or "
                    "revocation; it binds one current per-UID abstract socket and "
                    "retains only the live descriptor for the local evidence invocation.",
                ),
                "rollback_or_no_partial_state": [acquire_failures],
                "audit_lineage": n_a(
                    "acquire_invocation_lock",
                    "does not emit audit and has no audit side effect; it establishes "
                    "a local pre-artifact serialization lock, while the later evidence "
                    "journey owns bounded audit and report lineage.",
                ),
                "leak_safety": [acquire_failures, prebound_busy],
                "remote_http": n_a(
                    "acquire_invocation_lock",
                    "is not an HTTP boundary and does not perform HTTP; it uses one "
                    "local AF_UNIX abstract socket before the runner enters any "
                    "containerized or remote evidence flow.",
                ),
            },
            "decode_mountinfo_field": {
                "success": [mount_decode],
                "invalid_or_protocol": [decode_literal, kernel_parsers],
                "expiry_replay_or_revocation": n_a(
                    "decode_mountinfo_field",
                    "has no temporal state and does not own expiry, replay, or "
                    "revocation; it decodes one current kernel mountinfo field without "
                    "retaining lifecycle state.",
                ),
                "rollback_or_no_partial_state": n_a(
                    "decode_mountinfo_field",
                    "performs no durable write and mutates no repository state; it "
                    "returns one in-memory decoded string without opening a transaction "
                    "or changing the source field.",
                ),
                "audit_lineage": n_a(
                    "decode_mountinfo_field",
                    "does not emit audit and has no audit side effect; it is an internal "
                    "kernel-text decoder used before any evidence artifact or audit "
                    "record exists.",
                ),
                "leak_safety": n_a(
                    "decode_mountinfo_field",
                    "returns no caller-visible data; it decodes only the four kernel "
                    "mountinfo escapes for an internal comparison and does not log, "
                    "serialize, or publicly expose the decoded path.",
                ),
                "remote_http": n_a(
                    "decode_mountinfo_field",
                    "is not an HTTP boundary and does not perform HTTP; it operates "
                    "only on one local mountinfo text field below every transport layer.",
                ),
            },
            "invocation_lock_address": {
                "success": [lock_lifecycle],
                "invalid_or_protocol": n_a(
                    "invocation_lock_address",
                    "has no caller-controlled input and accepts no protocol input; it "
                    "deterministically combines a fixed private abstract-socket prefix "
                    "with the current numeric UID.",
                ),
                "expiry_replay_or_revocation": n_a(
                    "invocation_lock_address",
                    "has no temporal state and does not own expiry, replay, or "
                    "revocation; it derives the same current per-UID address on each "
                    "call without storing session state.",
                ),
                "rollback_or_no_partial_state": n_a(
                    "invocation_lock_address",
                    "performs no durable write and mutates no repository state; it "
                    "constructs immutable address bytes in memory and opens no socket "
                    "or transaction.",
                ),
                "audit_lineage": n_a(
                    "invocation_lock_address",
                    "does not emit audit and has no audit side effect; it only derives "
                    "the private local lock identity used before evidence execution.",
                ),
                "leak_safety": n_a(
                    "invocation_lock_address",
                    "returns only a fixed internal per-UID socket address and cannot "
                    "expose a raw path, credential, secret, or backend payload through "
                    "a public result.",
                ),
                "remote_http": n_a(
                    "invocation_lock_address",
                    "is not an HTTP boundary and does not perform HTTP; its bytes name "
                    "a local Linux abstract socket and never select a route, status, "
                    "header, or response body.",
                ),
            },
            "main": {
                "success": [path_swap, main_verify],
                "invalid_or_protocol": [
                    main_trust_predicates,
                    main_failures,
                    main_verify,
                ],
                "expiry_replay_or_revocation": n_a(
                    "main",
                    "has no temporal state and does not own expiry, replay, or "
                    "revocation; it validates one current runner invocation and live "
                    "lock descriptor before process replacement.",
                ),
                "rollback_or_no_partial_state": [
                    path_swap,
                    main_dup2,
                    main_trust_predicates,
                    main_failures,
                    main_exec_restore,
                ],
                "audit_lineage": n_a(
                    "main",
                    "does not emit audit and has no audit side effect; it runs before "
                    "the selected evidence mode creates its separately governed report "
                    "or audit lineage.",
                ),
                "leak_safety": [
                    path_swap,
                    main_dup2,
                    main_trust_predicates,
                    main_failures,
                    main_exec_restore,
                    prebound_busy,
                ],
                "remote_http": n_a(
                    "main",
                    "is not an HTTP boundary and does not perform HTTP; it is a local "
                    "command dispatcher for lock verification, boundary verification, "
                    "and pinned shell execution.",
                ),
            },
            "mount_options": {
                "success": [kernel_parsers, mount_decode],
                "invalid_or_protocol": [kernel_parsers],
                "expiry_replay_or_revocation": n_a(
                    "mount_options",
                    "has no temporal state and does not own expiry, replay, or "
                    "revocation; it reads the current process mount table for one path "
                    "and retains no lifecycle state.",
                ),
                "rollback_or_no_partial_state": n_a(
                    "mount_options",
                    "is read-only and performs no durable write; it parses local kernel "
                    "text into an option set without opening a transaction or mutating "
                    "mount state.",
                ),
                "audit_lineage": n_a(
                    "mount_options",
                    "does not emit audit and has no audit side effect; it is a local "
                    "kernel boundary predicate evaluated before evidence artifacts are "
                    "created.",
                ),
                "leak_safety": n_a(
                    "mount_options",
                    "returns no caller-visible data; it supplies an internal option set "
                    "to the boundary verifier without logging or serializing mount "
                    "paths.",
                ),
                "remote_http": n_a(
                    "mount_options",
                    "is not an HTTP boundary and does not perform HTTP; it reads only "
                    "the local process mount table below every remote transport.",
                ),
            },
            "process_status": {
                "success": [kernel_parsers],
                "invalid_or_protocol": [kernel_parsers],
                "expiry_replay_or_revocation": n_a(
                    "process_status",
                    "has no temporal state and does not own expiry, replay, or "
                    "revocation; it snapshots the current process status text and "
                    "retains no token or session lifecycle.",
                ),
                "rollback_or_no_partial_state": n_a(
                    "process_status",
                    "is read-only and performs no durable write; it parses one local "
                    "proc-status file into memory without a transaction or repository "
                    "mutation.",
                ),
                "audit_lineage": n_a(
                    "process_status",
                    "does not emit audit and has no audit side effect; it provides "
                    "current kernel flags to the pre-artifact boundary predicate only.",
                ),
                "leak_safety": n_a(
                    "process_status",
                    "returns no caller-visible data; its internal status mapping is "
                    "consumed only by the local boundary verifier and is never logged "
                    "or serialized into a public result.",
                ),
                "remote_http": n_a(
                    "process_status",
                    "is not an HTTP boundary and does not perform HTTP; it reads a local "
                    "proc-status file without routing or response behavior.",
                ),
            },
            "trusted_executable": {
                "success": [trusted_executable],
                "invalid_or_protocol": [trusted_executable],
                "expiry_replay_or_revocation": n_a(
                    "trusted_executable",
                    "has no temporal state and does not own expiry, replay, or "
                    "revocation; it evaluates current filesystem identity, mode, and "
                    "execute permission only.",
                ),
                "rollback_or_no_partial_state": n_a(
                    "trusted_executable",
                    "is read-only and performs no durable write; it inspects one "
                    "resolved executable without changing bytes, metadata, repository "
                    "state, or transaction state.",
                ),
                "audit_lineage": n_a(
                    "trusted_executable",
                    "does not emit audit and has no audit side effect; it is a local "
                    "pre-execution trust predicate, while later evidence operations own "
                    "their audit lineage.",
                ),
                "leak_safety": n_a(
                    "trusted_executable",
                    "returns only a boolean and cannot expose a raw path, credential, "
                    "secret, or executable contents through a caller-visible result.",
                ),
                "remote_http": n_a(
                    "trusted_executable",
                    "is not an HTTP boundary and does not perform HTTP; it inspects one "
                    "local executable below all transport and request handling.",
                ),
            },
            "trusted_invocation_lock_descriptor": {
                "success": [trusted_lock],
                "invalid_or_protocol": [trusted_lock],
                "expiry_replay_or_revocation": n_a(
                    "trusted_invocation_lock_descriptor",
                    "has no temporal state and does not own expiry, replay, or "
                    "revocation; it validates the current kernel socket identity and "
                    "type for one live descriptor.",
                ),
                "rollback_or_no_partial_state": n_a(
                    "trusted_invocation_lock_descriptor",
                    "is read-only and performs no durable write; it closes only its "
                    "temporary duplicate while leaving the supplied descriptor and "
                    "repository state unchanged.",
                ),
                "audit_lineage": n_a(
                    "trusted_invocation_lock_descriptor",
                    "does not emit audit and has no audit side effect; it is a local "
                    "descriptor predicate used before any evidence report or audit "
                    "record.",
                ),
                "leak_safety": [trusted_lock],
                "remote_http": n_a(
                    "trusted_invocation_lock_descriptor",
                    "is not an HTTP boundary and does not perform HTTP; it inspects a "
                    "local AF_UNIX descriptor without request, route, header, or "
                    "response behavior.",
                ),
            },
            "trusted_private_directory": {
                "success": [trusted_private],
                "invalid_or_protocol": [trusted_private],
                "expiry_replay_or_revocation": n_a(
                    "trusted_private_directory",
                    "has no temporal state and does not own expiry, replay, or "
                    "revocation; it validates the current directory path, ownership, "
                    "mode, and optional emptiness only.",
                ),
                "rollback_or_no_partial_state": [trusted_private],
                "audit_lineage": n_a(
                    "trusted_private_directory",
                    "does not emit audit and has no audit side effect; it is a local "
                    "scratch-directory predicate evaluated before evidence artifacts "
                    "are written.",
                ),
                "leak_safety": [trusted_private],
                "remote_http": n_a(
                    "trusted_private_directory",
                    "is not an HTTP boundary and does not perform HTTP; it inspects one "
                    "local private directory below all remote transport layers.",
                ),
            },
            "verify_held_invocation_lock": {
                "success": [trusted_lock, main_verify],
                "invalid_or_protocol": [trusted_lock, main_verify],
                "expiry_replay_or_revocation": n_a(
                    "verify_held_invocation_lock",
                    "has no temporal state and does not own expiry, replay, or "
                    "revocation; it checks whether one descriptor currently holds the "
                    "fixed per-UID kernel lock.",
                ),
                "rollback_or_no_partial_state": n_a(
                    "verify_held_invocation_lock",
                    "is read-only and performs no durable write; it delegates one "
                    "descriptor predicate without opening a transaction or mutating "
                    "repository state.",
                ),
                "audit_lineage": n_a(
                    "verify_held_invocation_lock",
                    "does not emit audit and has no audit side effect; it verifies a "
                    "local inherited descriptor before the evidence mode owns any "
                    "report or audit lineage.",
                ),
                "leak_safety": [trusted_lock],
                "remote_http": n_a(
                    "verify_held_invocation_lock",
                    "is not an HTTP boundary and does not perform HTTP; it returns one "
                    "local descriptor predicate result without remote transport "
                    "behavior.",
                ),
            },
            "verify_inner_boundary": {
                "success": [inner_boundary],
                "invalid_or_protocol": [inner_boundary],
                "expiry_replay_or_revocation": n_a(
                    "verify_inner_boundary",
                    "has no temporal state and does not own expiry, replay, or "
                    "revocation; it verifies one current process, complete capability "
                    "set, mount, executable, environment, socket, and private-directory "
                    "boundary before an inner evidence mode starts.",
                ),
                "rollback_or_no_partial_state": n_a(
                    "verify_inner_boundary",
                    "is read-only and performs no durable write; it returns a boolean "
                    "after kernel and filesystem checks without creating reports, "
                    "changing scratch children, or mutating repository state.",
                ),
                "audit_lineage": n_a(
                    "verify_inner_boundary",
                    "does not emit audit and has no audit side effect; it is a "
                    "pre-artifact kernel boundary predicate, while later evidence "
                    "journeys own their separate bounded audit records.",
                ),
                "leak_safety": [inner_boundary],
                "remote_http": n_a(
                    "verify_inner_boundary",
                    "is not an HTTP boundary and does not perform HTTP; it inspects "
                    "only local process status including all five capability sets, "
                    "mount options, fixed environment values, executables, a Unix "
                    "socket, and private scratch directories.",
                ),
            },
        }
        self.assertEqual(set(expected), affected_qualnames)

        for qualname in sorted(affected_qualnames):
            key = (module, qualname)
            with self.subTest(function_key=key):
                entry = entries[key]
                self.assertEqual(entry["status"], "onboarded")
                self.assertEqual(entry["source_binding"], bindings[key])
                self.assertEqual(
                    set(entry["categories"]),
                    set(REQUIRED_HARNESS_CATEGORIES),
                )
                category_union: set[str] = set()
                for category in REQUIRED_HARNESS_CATEGORIES:
                    expected_value = expected[qualname][category]
                    expected_ids = expected_value if isinstance(expected_value, list) else []
                    expected_reason = expected_value if isinstance(expected_value, str) else None
                    evidence = entry["categories"][category]
                    self.assertEqual(evidence["test_ids"], expected_ids)
                    self.assertEqual(
                        evidence["not_applicable_reason"],
                        expected_reason,
                    )
                    self.assertIn(evidence["pending_reason"], (None, ""))
                    self.assertTrue(set(expected_ids).issubset(collected))
                    category_union.update(expected_ids)
                self.assertTrue(category_union)
                self.assertEqual(entry["test_ids"], sorted(category_union))

        self.assert_batch_status_partition(manifest, target_keys)

    def test_connected_runtime_postgresql_live_e2e_evidence_owner_limit_ignores_unrelated_entries(
        self,
    ) -> None:
        manifest = copy.deepcopy(load_function_harness_manifest())
        target_module = "scripts.connected_runtime_postgres_live_e2e"
        target_test_id = next(
            entry["test_ids"][0]
            for entry in manifest["functions"]
            if entry["module"] == target_module and entry["test_ids"]
        )
        unrelated_entries = [
            entry for entry in manifest["functions"] if entry["module"] != target_module
        ][:13]
        self.assertEqual(len(unrelated_entries), 13)
        for entry in unrelated_entries:
            entry["test_ids"] = [target_test_id]

        with patch(
            f"{__name__}.load_function_harness_manifest",
            return_value=manifest,
        ):
            self.test_connected_runtime_postgresql_live_e2e_batch_is_manifest_onboarded()

    def test_connected_runtime_postgresql_live_e2e_batch_is_manifest_onboarded(
        self,
    ) -> None:
        manifest = load_function_harness_manifest()
        root = Path(__file__).resolve().parents[1]
        bindings = changed_scoped_function_bindings(
            root,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )
        collected = collect_unittest_test_ids(root / "tests")
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}
        module = "scripts.connected_runtime_postgres_live_e2e"
        test_prefix = (
            "tests.test_connected_runtime_postgres_live_e2e."
            "ConnectedRuntimePostgresLiveE2ETests."
        )

        def test_id(name: str) -> str:
            return test_prefix + name

        client_aclose = test_id("test_closable_rewriting_async_http_client_aclose_is_inert")
        client_init = test_id(
            "test_closable_rewriting_async_http_client_init_copies_mapping_and_stays_inert"
        )
        client_getattr = test_id(
            "test_closable_rewriting_async_http_client_getattr_delegates_without_mutation"
        )
        client_get = test_id(
            "test_closable_rewriting_async_http_client_get_forwards_once_without_mutation"
        )
        client_post = test_id(
            "test_closable_rewriting_async_http_client_post_forwards_once_without_mutation"
        )
        client_request_failure = test_id(
            "test_closable_rewriting_async_http_client_request_failure_preserves_state"
        )
        client_request_success = test_id(
            "test_closable_rewriting_async_http_client_request_rewrites_and_records_success"
        )
        chatgpt_client = test_id("test_chatgpt_client_builds_exact_dependencies_without_mutation")
        oauth_success = test_id(
            "test_complete_oauth_login_returns_exact_resource_bound_token_without_mutation"
        )
        oauth_failure = test_id(
            "test_complete_oauth_login_fails_closed_for_callback_and_token_response_errors"
        )
        jwks_invalid = test_id("test_jwks_summary_rejects_failed_status_and_malformed_shapes")
        jwks_leak_safety = test_id(
            "test_jwks_summary_reports_only_safe_shape_and_private_count_without_material"
        )
        listed_tool_names_invalid = test_id(
            "test_listed_tool_names_rejects_malformed_protocol_shapes"
        )
        invalid_token_challenge = test_id(
            "test_invalid_token_challenge_formats_exact_caller_metadata_without_leak"
        )
        load_dependencies_invalid = test_id(
            "test_load_inside_dependencies_rejects_protocol_version_mismatch_" "without_publication"
        )
        bearer_denial_invalid = test_id(
            "test_assert_bearer_denied_rejects_wrong_status_challenge_and_exact_body"
        )
        tool_call_result_invalid = test_id(
            "test_tool_call_result_rejects_malformed_missing_and_failed_results"
        )
        structured_call_invalid = test_id(
            "test_structured_call_rejects_error_and_malformed_payloads"
        )
        tool_call_is_error_invalid = test_id(
            "test_tool_call_is_error_propagates_delegated_protocol_validation"
        )
        jwt_kid_success = test_id("test_jwt_kid_returns_exact_builtin_key_id_without_mutation")
        jwt_kid_invalid = test_id(
            "test_jwt_kid_rejects_malformed_headers_with_one_suppressed_error"
        )
        jwt_expiry_success = test_id(
            "test_jwt_expiry_returns_exact_aware_utc_datetime_without_mutation"
        )
        jwt_expiry_invalid = test_id(
            "test_jwt_expiry_rejects_malformed_payloads_with_one_suppressed_error"
        )
        compose_success = test_id(
            "test_compose_runtime_builds_exact_google_rewrites_without_mutation"
        )
        compose_failure = test_id(
            "test_compose_runtime_propagates_compose_failure_without_retry_or_mutation"
        )
        count_rows_success = test_id(
            "test_count_rows_returns_exact_nonnegative_counts_for_allowed_tables_without_mutation"
        )
        count_rows_invalid = test_id(
            "test_count_rows_rejects_invalid_database_counts_without_coercion_or_mutation"
        )
        count_oauth_success = test_id(
            "test_count_oauth_state_returns_exact_nonnegative_counts_without_mutation"
        )
        count_oauth_unsupported = test_id(
            "test_count_oauth_state_rejects_unsupported_state_without_query_or_mutation"
        )
        count_oauth_invalid = test_id(
            "test_count_oauth_state_rejects_invalid_database_counts_without_coercion_or_mutation"
        )
        token_binding = test_id(
            "test_token_session_binding_requires_exact_row_and_values_without_hooks_or_mutation"
        )
        latest_binding_success = test_id(
            "test_latest_token_session_binding_for_user_returns_fresh_principal_bound_payload"
        )
        latest_binding_invalid = test_id(
            "test_latest_token_session_binding_for_user_rejects_unbound_or_invalid_rows"
        )
        initial_migrate_success = test_id(
            "test_initial_migrate_with_safe_diagnostics_returns_exact_result_without_rerun_or_mutation"
        )
        initial_migrate_diagnostic = test_id(
            "test_initial_migrate_with_safe_diagnostics_suppresses_initial_error_after_"
            "successful_diagnostic_rerun"
        )
        migration_forward = test_id(
            "test_migration_diagnostic_connection_forwards_queries_and_bounds_failures"
        )
        migration_rollback_close = test_id(
            "test_migration_diagnostic_connection_bounds_rollback_and_close_errors"
        )
        schema_readiness = test_id(
            "test_schema_readiness_failure_validates_exact_rows_in_order_without_hooks_or_mutation"
        )
        preflight_success = test_id(
            "test_preflight_with_safe_diagnostics_accepts_exact_ready_payload_without_diagnostics"
        )
        preflight_invalid = test_id(
            "test_preflight_with_safe_diagnostics_rejects_hooked_payloads_without_hooks"
        )
        audit_lineage = test_id(
            "test_mcp_authorization_audit_lineage_rejects_equality_spoofs_without_mutation"
        )
        run_inside_revoked = test_id(
            "test_run_inside_rechecks_revoked_bearer_after_same_subject_relink"
        )
        run_inside_binding_failure = test_id(
            "test_run_inside_maps_raising_upload_binding_accessors_to_generic_failure"
        )
        run_inside_binding_snapshot = test_id(
            "test_run_inside_snapshots_upload_binding_accessors_once_for_guard_and_metric"
        )
        run_inside_early_cleanup = test_id(
            "test_run_inside_early_failure_removes_stale_output_and_helper"
        )
        transaction_rollback = test_id(
            "test_run_transaction_rollback_probe_uses_exact_sentinel_identity_and_rolls_back"
        )
        run_command_success = test_id(
            "test_run_command_invokes_subprocess_once_and_returns_exact_result_without_mutation"
        )
        run_command_failure = test_id(
            "test_run_command_translates_launch_and_decode_failures_without_leaks_or_mutation"
        )
        run_command_invalid = test_id(
            "test_run_command_rejects_invalid_or_hooked_inputs_before_subprocess_without_hooks"
        )
        runner_image = test_id(
            "test_runner_immutable_image_id_reaches_nested_live_postgresql_command"
        )
        failed_live_e2e = test_id("test_failed_live_e2e_cannot_retain_or_reuse_stale_valid_output")
        pinned_image_drift = test_id("test_pinned_postgres_image_drift_stops_before_docker")
        invalid_runner_image = test_id(
            "test_missing_invalid_or_unbound_runner_image_id_stops_before_docker"
        )
        inside_image_authority = test_id(
            "test_inside_mode_requires_image_authority_before_journey_execution"
        )
        validate_report_read_only = test_id(
            "test_validate_report_mode_leaves_input_and_sibling_bytes_unchanged"
        )
        safe_report = test_id("test_safe_report_deterministically_emits_exact_harness_layer")
        count_downgrade = test_id("test_layer_and_report_counts_cannot_be_coherently_downgraded")
        relink_evidence = test_id(
            "test_relink_claim_rejects_missing_or_zero_post_relink_denial_evidence"
        )
        command_contract = test_id(
            "test_command_contract_binds_pinned_postgres_image_and_is_recomputed"
        )
        report_leak = test_id("test_report_rejects_dsn_url_email_token_path_and_sql")

        groups = {
            client_aclose: {"_ClosableRewritingAsyncHttpClient.aclose"},
            client_init: {"_ClosableRewritingAsyncHttpClient.__init__"},
            client_getattr: {"_ClosableRewritingAsyncHttpClient.__getattr__"},
            client_get: {"_ClosableRewritingAsyncHttpClient.get"},
            client_post: {"_ClosableRewritingAsyncHttpClient.post"},
            client_request_success: {"_ClosableRewritingAsyncHttpClient._request"},
            initial_migrate_diagnostic: {"_MigrationDiagnosticConnection.__init__"},
            migration_forward: {
                "_MigrationDiagnosticConnection._call",
                "_MigrationDiagnosticConnection.begin",
                "_MigrationDiagnosticConnection.commit",
                "_MigrationDiagnosticConnection.execute",
                "_MigrationDiagnosticConnection.query_all",
                "_MigrationDiagnosticConnection.query_one",
            },
            migration_rollback_close: {
                "_MigrationDiagnosticConnection.close",
                "_MigrationDiagnosticConnection.rollback",
            },
            run_inside_revoked: {
                "_assert_bearer_denied",
                "_denial_shape",
                "_initialize_request",
                "_jwks_summary",
            },
            chatgpt_client: {
                "_chatgpt_client",
                "_load_inside_dependencies",
            },
            command_contract: {"_command_contract_hash"},
            oauth_success: {"_complete_oauth_login"},
            compose_success: {"_compose_runtime"},
            report_leak: {"_contains_forbidden_text"},
            count_oauth_success: {"_count_oauth_state"},
            count_rows_success: {"_count_rows"},
            safe_report: {
                "_evidence_hash",
                "_sha256_json",
                "_validate_live_postgresql_layer",
                "build_live_postgresql_layer",
                "build_live_postgresql_layer.<locals>.journey",
                "validate_live_postgresql_external_layer",
                "validate_report",
            },
            count_downgrade: {
                "_exact_keys",
                "_is_nonnegative_int",
                "_metrics_pass",
            },
            initial_migrate_success: {"_initial_migrate_with_safe_diagnostics"},
            invalid_token_challenge: {"_invalid_token_challenge"},
            jwt_expiry_success: {"_jwt_expiry"},
            jwt_kid_success: {"_jwt_kid"},
            latest_binding_success: {"_latest_token_session_binding_for_user"},
            run_inside_binding_snapshot: {
                "_listed_tool_names",
                "_run_inside",
                "_shape",
                "_structured_call",
                "_tool_call_is_error",
                "_tool_call_result",
            },
            preflight_success: {"_preflight_with_safe_diagnostics"},
            runner_image: {
                "_require_pinned_postgres_image",
                "run_live_e2e",
            },
            run_command_success: {"_run_command"},
            transaction_rollback: {"_run_transaction_rollback_probe"},
            schema_readiness: {"_schema_readiness_failure"},
            token_binding: {"_token_session_binding"},
            audit_lineage: {"_validate_mcp_authorization_audit_lineage"},
            validate_report_read_only: {"main"},
        }
        primary_test_by_qualname = {
            qualname: primary_test
            for primary_test, qualnames in groups.items()
            for qualname in qualnames
        }
        target_keys = {(module, qualname) for qualname in primary_test_by_qualname}
        module_entry_keys = {key for key in entries if key[0] == module}
        module_binding_keys = {key for key in bindings if key[0] == module}

        self.assertEqual(len(target_keys), 57)
        self.assertEqual(sum(map(len, groups.values())), 57)
        self.assertTrue(all(len(qualnames) <= 7 for qualnames in groups.values()))
        final_source_keys = {
            (module, "_campaign_source_root"),
            (module, "_unique_json_object"),
            (module, "_verify_campaign_source_mount"),
            (module, "_visible_campaign_source_is_valid"),
        }
        self.assertEqual(module_entry_keys, target_keys | final_source_keys)
        self.assertEqual(module_binding_keys, target_keys | final_source_keys)
        self.assertTrue(target_keys.issubset(bindings))
        self.assertTrue(target_keys.issubset(entries))

        invalid_tests = {
            "_ClosableRewritingAsyncHttpClient.__getattr__": client_getattr,
            "_ClosableRewritingAsyncHttpClient._request": client_request_failure,
            "_MigrationDiagnosticConnection.__init__": initial_migrate_diagnostic,
            "_MigrationDiagnosticConnection._call": migration_forward,
            "_MigrationDiagnosticConnection.begin": migration_forward,
            "_MigrationDiagnosticConnection.close": migration_rollback_close,
            "_MigrationDiagnosticConnection.commit": migration_forward,
            "_MigrationDiagnosticConnection.execute": migration_forward,
            "_MigrationDiagnosticConnection.query_all": migration_forward,
            "_MigrationDiagnosticConnection.query_one": migration_forward,
            "_MigrationDiagnosticConnection.rollback": migration_rollback_close,
            "_assert_bearer_denied": bearer_denial_invalid,
            "_complete_oauth_login": oauth_failure,
            "_compose_runtime": compose_failure,
            "_contains_forbidden_text": report_leak,
            "_count_oauth_state": count_oauth_unsupported,
            "_count_rows": count_rows_invalid,
            "_denial_shape": run_inside_revoked,
            "_exact_keys": count_downgrade,
            "_initial_migrate_with_safe_diagnostics": initial_migrate_diagnostic,
            "_invalid_token_challenge": invalid_token_challenge,
            "_is_nonnegative_int": count_downgrade,
            "_jwks_summary": jwks_invalid,
            "_jwt_expiry": jwt_expiry_invalid,
            "_jwt_kid": jwt_kid_invalid,
            "_latest_token_session_binding_for_user": latest_binding_invalid,
            "_listed_tool_names": listed_tool_names_invalid,
            "_load_inside_dependencies": load_dependencies_invalid,
            "_metrics_pass": count_downgrade,
            "_preflight_with_safe_diagnostics": preflight_invalid,
            "_require_pinned_postgres_image": pinned_image_drift,
            "_run_command": run_command_invalid,
            "_run_inside": run_inside_binding_failure,
            "_run_transaction_rollback_probe": transaction_rollback,
            "_schema_readiness_failure": schema_readiness,
            "_structured_call": structured_call_invalid,
            "_token_session_binding": token_binding,
            "_tool_call_is_error": tool_call_is_error_invalid,
            "_tool_call_result": tool_call_result_invalid,
            "_validate_live_postgresql_layer": count_downgrade,
            "_validate_mcp_authorization_audit_lineage": audit_lineage,
            "build_live_postgresql_layer": count_downgrade,
            "build_live_postgresql_layer.<locals>.journey": count_downgrade,
            "main": inside_image_authority,
            "run_live_e2e": invalid_runner_image,
            "validate_live_postgresql_external_layer": count_downgrade,
            "validate_report": report_leak,
        }
        temporal_tests = {
            "_assert_bearer_denied": run_inside_revoked,
            "_count_oauth_state": count_oauth_success,
            "_denial_shape": run_inside_revoked,
            "_jwks_summary": run_inside_revoked,
            "_jwt_expiry": jwt_expiry_success,
            "_latest_token_session_binding_for_user": latest_binding_success,
            "_run_inside": run_inside_revoked,
            "_token_session_binding": token_binding,
            "_validate_live_postgresql_layer": relink_evidence,
            "build_live_postgresql_layer": relink_evidence,
            "build_live_postgresql_layer.<locals>.journey": relink_evidence,
            "validate_live_postgresql_external_layer": relink_evidence,
            "validate_report": relink_evidence,
        }
        rollback_tests = {
            "_ClosableRewritingAsyncHttpClient._request": client_request_failure,
            "_MigrationDiagnosticConnection.__init__": initial_migrate_diagnostic,
            "_MigrationDiagnosticConnection._call": migration_forward,
            "_MigrationDiagnosticConnection.begin": migration_forward,
            "_MigrationDiagnosticConnection.close": migration_rollback_close,
            "_MigrationDiagnosticConnection.commit": migration_forward,
            "_MigrationDiagnosticConnection.execute": migration_forward,
            "_MigrationDiagnosticConnection.query_all": migration_forward,
            "_MigrationDiagnosticConnection.query_one": migration_forward,
            "_MigrationDiagnosticConnection.rollback": migration_rollback_close,
            "_complete_oauth_login": oauth_failure,
            "_compose_runtime": compose_failure,
            "_count_oauth_state": count_oauth_invalid,
            "_count_rows": count_rows_invalid,
            "_initial_migrate_with_safe_diagnostics": initial_migrate_diagnostic,
            "_latest_token_session_binding_for_user": latest_binding_invalid,
            "_preflight_with_safe_diagnostics": preflight_invalid,
            "_run_command": run_command_failure,
            "_run_inside": run_inside_early_cleanup,
            "_run_transaction_rollback_probe": transaction_rollback,
            "_schema_readiness_failure": schema_readiness,
            "_structured_call": run_inside_binding_failure,
            "_token_session_binding": token_binding,
            "_tool_call_is_error": run_inside_binding_failure,
            "_tool_call_result": run_inside_binding_failure,
            "_validate_mcp_authorization_audit_lineage": audit_lineage,
            "main": validate_report_read_only,
            "run_live_e2e": failed_live_e2e,
        }
        audit_tests = {
            "_assert_bearer_denied": run_inside_revoked,
            "_denial_shape": run_inside_revoked,
            "_initialize_request": run_inside_revoked,
            "_jwks_summary": run_inside_revoked,
            "_listed_tool_names": run_inside_binding_snapshot,
            "_run_inside": run_inside_binding_snapshot,
            "_shape": run_inside_binding_snapshot,
            "_structured_call": run_inside_binding_snapshot,
            "_tool_call_is_error": run_inside_binding_snapshot,
            "_tool_call_result": run_inside_binding_snapshot,
            "_validate_live_postgresql_layer": safe_report,
            "_validate_mcp_authorization_audit_lineage": audit_lineage,
            "build_live_postgresql_layer": safe_report,
            "build_live_postgresql_layer.<locals>.journey": safe_report,
            "validate_live_postgresql_external_layer": safe_report,
            "validate_report": safe_report,
        }
        leak_tests = {
            "_ClosableRewritingAsyncHttpClient._request": client_request_failure,
            "_MigrationDiagnosticConnection.__init__": initial_migrate_diagnostic,
            "_MigrationDiagnosticConnection._call": migration_forward,
            "_MigrationDiagnosticConnection.begin": migration_forward,
            "_MigrationDiagnosticConnection.close": migration_rollback_close,
            "_MigrationDiagnosticConnection.commit": migration_forward,
            "_MigrationDiagnosticConnection.execute": migration_forward,
            "_MigrationDiagnosticConnection.query_all": migration_forward,
            "_MigrationDiagnosticConnection.query_one": migration_forward,
            "_MigrationDiagnosticConnection.rollback": migration_rollback_close,
            "_complete_oauth_login": oauth_failure,
            "_compose_runtime": compose_failure,
            "_contains_forbidden_text": report_leak,
            "_count_oauth_state": count_oauth_invalid,
            "_count_rows": count_rows_invalid,
            "_evidence_hash": report_leak,
            "_exact_keys": report_leak,
            "_initial_migrate_with_safe_diagnostics": initial_migrate_diagnostic,
            "_invalid_token_challenge": invalid_token_challenge,
            "_is_nonnegative_int": report_leak,
            "_jwks_summary": jwks_leak_safety,
            "_jwt_expiry": jwt_expiry_invalid,
            "_jwt_kid": jwt_kid_invalid,
            "_latest_token_session_binding_for_user": latest_binding_invalid,
            "_metrics_pass": report_leak,
            "_preflight_with_safe_diagnostics": preflight_invalid,
            "_require_pinned_postgres_image": pinned_image_drift,
            "_run_command": run_command_failure,
            "_run_inside": run_inside_binding_failure,
            "_run_transaction_rollback_probe": transaction_rollback,
            "_schema_readiness_failure": schema_readiness,
            "_sha256_json": report_leak,
            "_structured_call": run_inside_binding_failure,
            "_token_session_binding": token_binding,
            "_tool_call_is_error": run_inside_binding_failure,
            "_tool_call_result": run_inside_binding_failure,
            "_validate_live_postgresql_layer": report_leak,
            "_validate_mcp_authorization_audit_lineage": audit_lineage,
            "build_live_postgresql_layer": report_leak,
            "build_live_postgresql_layer.<locals>.journey": report_leak,
            "main": validate_report_read_only,
            "run_live_e2e": failed_live_e2e,
            "validate_live_postgresql_external_layer": report_leak,
            "validate_report": report_leak,
        }
        remote_http_tests = {
            "_ClosableRewritingAsyncHttpClient._request": client_request_success,
            "_ClosableRewritingAsyncHttpClient.get": client_get,
            "_ClosableRewritingAsyncHttpClient.post": client_post,
            "_assert_bearer_denied": run_inside_revoked,
            "_chatgpt_client": chatgpt_client,
            "_complete_oauth_login": oauth_success,
            "_compose_runtime": compose_success,
            "_denial_shape": run_inside_revoked,
            "_initialize_request": run_inside_revoked,
            "_jwks_summary": run_inside_revoked,
            "_listed_tool_names": run_inside_binding_snapshot,
            "_preflight_with_safe_diagnostics": preflight_success,
            "_run_inside": run_inside_binding_snapshot,
            "_structured_call": run_inside_binding_snapshot,
            "_tool_call_is_error": run_inside_binding_snapshot,
            "_tool_call_result": run_inside_binding_snapshot,
        }
        category_tests = {
            "invalid_or_protocol": invalid_tests,
            "expiry_replay_or_revocation": temporal_tests,
            "rollback_or_no_partial_state": rollback_tests,
            "audit_lineage": audit_tests,
            "leak_safety": leak_tests,
            "remote_http": remote_http_tests,
        }
        self.assertEqual(set(category_tests), set(REQUIRED_HARNESS_CATEGORIES) - {"success"})
        self.assertTrue(
            all(
                set(test_map).issubset(primary_test_by_qualname)
                for test_map in category_tests.values()
            )
        )

        def not_applicable_reason(qualname: str, category: str) -> str:
            identity = f"{module}.{qualname}"
            details = {
                "invalid_or_protocol": (
                    "has no caller-controlled input and does not independently parse "
                    "protocol input; its bounded helper either accepts no external "
                    "input or delegates typed request validation to the named "
                    "lower-level boundary."
                ),
                "expiry_replay_or_revocation": (
                    "has no temporal state and does not own expiry, replay, "
                    "revocation, relink, membership, grant, or signing-key lifecycle."
                ),
                "rollback_or_no_partial_state": (
                    "performs no durable write and does not open a transaction; its "
                    "bounded operation returns or forwards one in-memory value while "
                    "the explicit caller owns persistence and cleanup."
                ),
                "audit_lineage": (
                    "does not emit audit and does not persist audit; the connected "
                    "runtime or report validator owns the governed OAuth, MCP, "
                    "upload, and denial lineage."
                ),
                "leak_safety": (
                    "returns no caller-visible data and cannot expose a raw path; it "
                    "returns one internal value unchanged or delegates redaction to "
                    "the governed transport and report validation boundary."
                ),
                "remote_http": (
                    "is not an HTTP boundary and does not perform a remote request; "
                    "it operates below transport or on local database, subprocess, "
                    "hash, validation, report, or orchestration state."
                ),
            }
            return f"{identity} {details[category]}"

        for qualname, primary_test in sorted(primary_test_by_qualname.items()):
            key = (module, qualname)
            expected = {"success": [primary_test]}
            for category, test_map in category_tests.items():
                if qualname not in test_map:
                    expected[category] = not_applicable_reason(qualname, category)
                    continue
                expected_ids = [test_map[qualname]]
                if qualname == "_invalid_token_challenge" and category == "invalid_or_protocol":
                    expected_ids.append(bearer_denial_invalid)
                expected[category] = sorted(expected_ids)

            with self.subTest(function_key=key):
                entry = entries[key]
                self.assertEqual(entry["status"], "onboarded")
                self.assertEqual(entry["source_binding"], bindings[key])
                self.assertEqual(
                    set(entry["categories"]),
                    set(REQUIRED_HARNESS_CATEGORIES),
                )
                category_union: set[str] = set()
                for category in REQUIRED_HARNESS_CATEGORIES:
                    expected_value = expected[category]
                    expected_ids = expected_value if isinstance(expected_value, list) else []
                    expected_reason = expected_value if isinstance(expected_value, str) else None
                    evidence = entry["categories"][category]
                    self.assertEqual(evidence["test_ids"], expected_ids)
                    self.assertEqual(
                        evidence["not_applicable_reason"],
                        expected_reason,
                    )
                    self.assertIn(evidence["pending_reason"], (None, ""))
                    self.assertTrue(set(expected_ids).issubset(collected))
                    category_union.update(expected_ids)
                self.assertTrue(category_union)
                self.assertEqual(entry["test_ids"], sorted(category_union))

        self.assert_batch_status_partition(manifest, target_keys)

        evidence_owners: dict[str, set[tuple[str, str]]] = {}
        for key in sorted(target_keys):
            item = entries[key]
            for evidence_test_id in item["test_ids"]:
                evidence_owners.setdefault(evidence_test_id, set()).add(key)
        self.assertLessEqual(max(map(len, evidence_owners.values())), 12)

    def test_runner_execution_capture_local_evidence_adapter(self) -> None:
        from tests.test_issue20_containerized_evidence_runner import (
            Issue20ContainerizedEvidenceRunnerContractTest,
        )

        evidence = Issue20ContainerizedEvidenceRunnerContractTest(
            "test_live_postgresql_execution_error_capture_is_fixed_consumed_and_closed"
        )
        evidence.test_live_postgresql_execution_error_capture_is_fixed_consumed_and_closed()

    def test_final_runner_live_e2e_source_batch_is_manifest_onboarded(self) -> None:
        manifest = load_function_harness_manifest()
        root = Path(__file__).resolve().parents[1]
        bindings = changed_scoped_function_bindings(
            root,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )
        collected = collect_unittest_test_ids(root / "tests")
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}
        live_module = "scripts.connected_runtime_postgres_live_e2e"
        runner_module = "scripts.issue20_runner_boundary"
        live_qualnames = {
            "_campaign_source_root",
            "_unique_json_object",
            "_verify_campaign_source_mount",
            "_visible_campaign_source_is_valid",
        }
        runner_failure_qualnames = {
            "_open_runner_failure_directory",
            "_open_trusted_private_directory",
            "_runner_failure_payload",
            "consume_runner_failure_diagnostic",
            "write_runner_failure_diagnostic",
        }
        execution_capture_qualnames = {
            "_consume_live_postgresql_execution_capture",
            "_open_live_postgresql_execution_capture_directory",
            "clear_live_postgresql_execution_capture",
            "consume_live_postgresql_execution_error",
        }
        target_keys = {
            *((live_module, qualname) for qualname in live_qualnames),
            *((runner_module, qualname) for qualname in runner_failure_qualnames),
            *((runner_module, qualname) for qualname in execution_capture_qualnames),
        }
        refreshed_keys = {
            (live_module, "run_live_e2e"),
            (runner_module, "main"),
        }
        self.assertEqual(len(live_qualnames), 4)
        self.assertEqual(len(runner_failure_qualnames), 5)
        self.assertEqual(len(execution_capture_qualnames), 4)
        self.assertEqual(len(target_keys), 13)
        self.assertTrue(target_keys.isdisjoint(refreshed_keys))
        self.assertTrue((target_keys | refreshed_keys).issubset(bindings))
        self.assertTrue((target_keys | refreshed_keys).issubset(entries))

        live_prefix = (
            "tests.test_connected_runtime_postgres_live_e2e."
            "ConnectedRuntimePostgresLiveE2ETests."
        )
        runner_prefix = (
            "tests.test_issue20_containerized_evidence_runner."
            "Issue20ContainerizedEvidenceRunnerContractTest."
        )
        campaign_success = (
            live_prefix + "test_runner_campaign_mount_uses_frozen_snapshot_instead_of_live_root"
        )
        campaign_invalid = (
            live_prefix + "test_runner_campaign_source_rejects_invalid_pin_and_snapshot_layouts"
        )
        runner_failure = (
            runner_prefix + "test_runner_failure_diagnostic_handoff_is_fixed_validated_and_one_shot"
        )
        execution_capture = (
            "tests.test_issue20_function_onboarding.Issue20FunctionOnboardingTests."
            "test_runner_execution_capture_local_evidence_adapter"
        )
        roles = {
            (live_module, "_campaign_source_root"): (
                "validates one immutable campaign pin and resolves its frozen source snapshot"
            ),
            (live_module, "_unique_json_object"): (
                "rejects duplicate JSON object keys while parsing the campaign pin"
            ),
            (live_module, "_verify_campaign_source_mount"): (
                "accepts a visible frozen snapshot or launches one isolated verifier"
            ),
            (live_module, "_visible_campaign_source_is_valid"): (
                "checks the visible frozen snapshot directory and required regular files"
            ),
            (runner_module, "_consume_live_postgresql_execution_capture"): (
                "validates, reads, unlinks, and fsyncs one fixed private execution capture"
            ),
            (runner_module, "_open_live_postgresql_execution_capture_directory"): (
                "opens the exact invocation inner-log directory through trusted descriptors"
            ),
            (runner_module, "_open_runner_failure_directory"): (
                "opens the exact runner private-log directory through trusted descriptors"
            ),
            (runner_module, "_open_trusted_private_directory"): (
                "opens one exact mode-0700 same-UID directory without following links"
            ),
            (runner_module, "_runner_failure_payload"): (
                "serializes one allowlisted stage and failure-code pair into the closed schema"
            ),
            (runner_module, "clear_live_postgresql_execution_capture"): (
                "consumes only an empty fixed private execution capture"
            ),
            (runner_module, "consume_live_postgresql_execution_error"): (
                "consumes one fixed private capture and maps only allowlisted error codes"
            ),
            (runner_module, "consume_runner_failure_diagnostic"): (
                "validates and consumes one fixed runner-owned failure diagnostic"
            ),
            (runner_module, "write_runner_failure_diagnostic"): (
                "atomically creates one fixed runner-owned failure diagnostic"
            ),
        }
        self.assertEqual(set(roles), target_keys)

        def n_a(key: tuple[str, str], category: str) -> str:
            identity = ".".join(key)
            role = roles[key]
            details = {
                "expiry_replay_or_revocation": (
                    "it has no temporal state and does not own expiry, replay, or "
                    "revocation; current campaign hashes or filesystem identity define "
                    "the bounded invocation state."
                ),
                "rollback_or_no_partial_state": (
                    "it performs no durable write and does not open a transaction; the "
                    "enclosing live runner owns public-artifact cleanup and retry state."
                ),
                "audit_lineage": (
                    "it does not emit audit and does not persist audit; the connected "
                    "OAuth journey and validated report own governed audit lineage."
                ),
                "remote_http": (
                    "it is not an HTTP boundary and does not perform HTTP; it operates "
                    "only on local JSON, filesystem descriptors, or an isolated Docker "
                    "verification command."
                ),
            }
            return f"{identity} {role}; {details[category]}"

        expected: dict[tuple[str, str], dict[str, list[str] | str]] = {}
        for qualname in sorted(live_qualnames):
            key = (live_module, qualname)
            expected[key] = {
                "success": [campaign_success],
                "invalid_or_protocol": [campaign_invalid],
                "expiry_replay_or_revocation": n_a(
                    key,
                    "expiry_replay_or_revocation",
                ),
                "rollback_or_no_partial_state": n_a(
                    key,
                    "rollback_or_no_partial_state",
                ),
                "audit_lineage": n_a(key, "audit_lineage"),
                "leak_safety": [campaign_invalid],
                "remote_http": n_a(key, "remote_http"),
            }
        for qualname in sorted(runner_failure_qualnames):
            key = (runner_module, qualname)
            expected[key] = {
                "success": [runner_failure],
                "invalid_or_protocol": [runner_failure],
                "expiry_replay_or_revocation": n_a(
                    key,
                    "expiry_replay_or_revocation",
                ),
                "rollback_or_no_partial_state": [runner_failure],
                "audit_lineage": n_a(key, "audit_lineage"),
                "leak_safety": [runner_failure],
                "remote_http": n_a(key, "remote_http"),
            }
        for qualname in sorted(execution_capture_qualnames):
            key = (runner_module, qualname)
            expected[key] = {
                "success": [execution_capture],
                "invalid_or_protocol": [execution_capture],
                "expiry_replay_or_revocation": n_a(
                    key,
                    "expiry_replay_or_revocation",
                ),
                "rollback_or_no_partial_state": [execution_capture],
                "audit_lineage": n_a(key, "audit_lineage"),
                "leak_safety": [execution_capture],
                "remote_http": n_a(key, "remote_http"),
            }
        self.assertEqual(set(expected), target_keys)

        for key in sorted(target_keys):
            with self.subTest(function_key=key):
                entry = entries[key]
                self.assertEqual(entry["status"], "onboarded")
                self.assertEqual(entry["source_binding"], bindings[key])
                self.assertEqual(
                    set(entry["categories"]),
                    set(REQUIRED_HARNESS_CATEGORIES),
                )
                category_union: set[str] = set()
                for category in REQUIRED_HARNESS_CATEGORIES:
                    expected_value = expected[key][category]
                    expected_ids = expected_value if isinstance(expected_value, list) else []
                    expected_reason = expected_value if isinstance(expected_value, str) else None
                    evidence = entry["categories"][category]
                    self.assertEqual(evidence["test_ids"], expected_ids)
                    self.assertEqual(
                        evidence["not_applicable_reason"],
                        expected_reason,
                    )
                    self.assertIn(evidence["pending_reason"], (None, ""))
                    self.assertTrue(set(expected_ids).issubset(collected))
                    category_union.update(expected_ids)
                self.assertTrue(category_union)
                self.assertEqual(entry["test_ids"], sorted(category_union))

        for key in sorted(refreshed_keys):
            self.assertEqual(entries[key]["status"], "onboarded")
            self.assertEqual(entries[key]["source_binding"], bindings[key])

        self.assert_batch_status_partition(manifest, target_keys)

        evidence_owners: dict[str, set[tuple[str, str]]] = {}
        for key in sorted(target_keys):
            for evidence_test_id in entries[key]["test_ids"]:
                evidence_owners.setdefault(evidence_test_id, set()).add(key)
        self.assertLessEqual(max(map(len, evidence_owners.values())), 12)

    def test_external_layer_count_validator_is_manifest_onboarded(self) -> None:
        manifest = load_function_harness_manifest()
        root = Path(__file__).resolve().parents[1]
        bindings = changed_scoped_function_bindings(
            root,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )
        collected = collect_unittest_test_ids(root / "tests")
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}
        key = ("scripts.oauth_mcp_harness", "_validate_external_layer_counts")
        success = (
            "tests.test_oauth_mcp_harness_script.OAuthMcpHarnessScriptTests."
            "test_external_layer_count_validator_accepts_exact_layers_without_mutation"
        )
        invalid = (
            "tests.test_oauth_mcp_harness_script.OAuthMcpHarnessScriptTests."
            "test_external_layer_count_validator_rejects_invalid_counts_without_mutation"
        )
        expected = {
            "success": [success],
            **{
                category: [invalid]
                for category in REQUIRED_HARNESS_CATEGORIES
                if category != "success"
            },
        }

        self.assertIn(key, bindings)
        self.assertIn(key, entries)
        entry = entries[key]
        self.assertEqual(entry["status"], "onboarded")
        self.assertEqual(entry["source_binding"], bindings[key])
        self.assertEqual(set(entry["categories"]), set(REQUIRED_HARNESS_CATEGORIES))
        category_union: set[str] = set()
        for category in REQUIRED_HARNESS_CATEGORIES:
            evidence = entry["categories"][category]
            self.assertEqual(evidence["test_ids"], expected[category])
            self.assertIsNone(evidence["not_applicable_reason"])
            self.assertIn(evidence["pending_reason"], (None, ""))
            self.assertTrue(set(expected[category]).issubset(collected))
            category_union.update(expected[category])
        self.assertEqual(entry["test_ids"], sorted(category_union))

        validation = validate_function_harness_manifest(manifest, root=root)
        self.assertEqual(validation["source_binding_mismatch_count"], 0)
        self.assertEqual(
            [
                blocker
                for blocker in validation["blockers"]
                if "scripts.oauth_mcp_harness._validate_external_layer_counts" in blocker
            ],
            [],
        )

    def test_oauth_mcp_harness_remaining_batch_is_manifest_onboarded(self) -> None:
        manifest = load_function_harness_manifest()
        root = Path(__file__).resolve().parents[1]
        bindings = changed_scoped_function_bindings(
            root,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )
        collected = collect_unittest_test_ids(root / "tests")
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}
        module = "scripts.oauth_mcp_harness"
        prefix = "tests.test_oauth_mcp_harness_script.OAuthMcpHarnessScriptTests."
        lifecycle_success = (
            prefix + "test_lifecycle_reports_aggregate_and_bind_without_enabling_completion"
        )
        lifecycle_invalid = (
            prefix + "test_lifecycle_aggregate_rejects_duplicate_tampered_and_unattested_reports"
        )
        lifecycle_leak = (
            prefix + "test_cli_aggregates_and_binds_lifecycle_reports_without_exposing_paths"
        )
        hostile_error_codes = (
            prefix
            + "test_evidence_errors_map_hostile_codes_to_generic_fallbacks_without_side_effects"
        )
        operator_cli = prefix + "test_cli_builds_operator_layer_and_requires_explicit_attestation"
        main_success = prefix + "test_main_direct_success_atomically_replaces_existing_safe_report"
        output_write_failure = (
            prefix + "test_cli_output_write_failure_preserves_previous_artifact_and_cleans_temp"
        )
        completion_binding = (
            prefix + "test_full_packet_recomputes_completion_audit_artifact_binding"
        )
        inspector_builder = prefix + "test_mcp_inspector_builder_source_hash_and_leak_guards"
        chatgpt_builder = prefix + "test_chatgpt_google_builder_and_dedicated_guards_local_contract"
        reviewer_builder = prefix + "test_reviewer_gate_builder_and_dedicated_guards"
        report_shape = (
            prefix + "test_report_shape_is_hash_status_count_boolean_only_and_deterministic"
        )
        run_harness_success = (
            prefix + "test_run_oauth_mcp_harness_direct_success_is_safe_and_side_effect_free"
        )
        report_invalid = (
            prefix + "test_validator_rejects_sensitive_fields_tampering_and_live_overclaims"
        )
        packet_invalid = (
            prefix + "test_external_packet_rejects_sensitive_fake_or_inconsistent_evidence"
        )
        packet_revalidation = (
            prefix + "test_external_claim_report_revalidation_accepts_matching_packet"
        )
        documentation_binding = (
            prefix + "test_completion_documentation_hash_rejects_stale_operator_critical_docs"
        )
        completion_prefix = (
            "tests.test_issue20_completion_finalization." "Issue20CompletionFinalizationTests."
        )
        malformed_preclosure = (
            completion_prefix
            + "test_malformed_preclosure_array_fails_closed_without_replacing_output"
        )
        missing_implementation_contract = (
            completion_prefix + "test_missing_operator_deploy_document_fails_preclosure_closed"
        )

        groups = {
            lifecycle_invalid: {"LifecycleEvidenceError.__init__"},
            operator_cli: {
                "OperatorEvidenceError.__init__",
                "build_operator_cli_postgresql_external_layer",
                "validate_operator_cli_postgresql_external_layer",
            },
            main_success: {"main"},
            report_shape: {
                "_LocalCompletionContext.__init__",
                "_build_local_safe_outputs",
                "_local_completion_audit_report_hash",
                "_mapping",
                "_repository_contract_hash",
                "_run_local_completion_context",
                "_safe_count",
                "_safe_hash",
                "validate_report",
            },
            run_harness_success: {"run_oauth_mcp_harness"},
            packet_invalid: {
                "_exact_keys",
                "_hash_external_packet",
                "_is_sha256",
                "_validate_external_attestations",
                "_validate_external_hash_fields",
                "validate_external_evidence_packet",
            },
            lifecycle_success: {
                "aggregate_production_container_lifecycle_reports",
                "validate_production_container_lifecycle_external_layer",
            },
            completion_binding: {
                "build_completion_audit_external_layer",
                "validate_completion_audit_external_layer",
            },
            chatgpt_builder: {
                "build_live_chatgpt_google_external_layer",
                "validate_live_chatgpt_google_external_layer",
            },
            inspector_builder: {
                "build_mcp_inspector_external_layer",
                "validate_mcp_inspector_external_layer",
            },
            reviewer_builder: {
                "build_reviewer_gate_external_layer",
                "validate_reviewer_gate_external_layer",
            },
        }
        primary_test_by_qualname = {
            qualname: primary_test
            for primary_test, qualnames in groups.items()
            for qualname in qualnames
        }
        target_keys = {(module, qualname) for qualname in primary_test_by_qualname}
        preserved_count_key = (module, "_validate_external_layer_counts")
        preserved_completion_keys = {
            (module, "_issue20_completion_document_semantics"),
            (module, "_issue20_completion_state_projection"),
            (module, "_issue20_expected_completion_document_texts"),
            (module, "_repository_contract_file_hashes"),
            (module, "build_issue20_completion_transition"),
            (module, "build_issue20_preclosure_manifest"),
            (module, "validate_issue20_completion_transition"),
            (module, "validate_issue20_preclosure_manifest"),
        }
        module_entry_keys = {key for key in entries if key[0] == module}
        module_binding_keys = {key for key in bindings if key[0] == module}

        self.assertEqual(len(target_keys), 31)
        self.assertEqual(sum(map(len, groups.values())), 31)
        self.assertTrue(all(len(qualnames) <= 10 for qualnames in groups.values()))
        expected_module_keys = target_keys | {preserved_count_key} | preserved_completion_keys
        self.assertEqual(module_entry_keys, expected_module_keys)
        self.assertEqual(module_binding_keys, expected_module_keys)
        self.assertTrue(target_keys.issubset(bindings))
        self.assertTrue(target_keys.issubset(entries))

        invalid_tests = {
            "LifecycleEvidenceError.__init__": hostile_error_codes,
            "OperatorEvidenceError.__init__": hostile_error_codes,
            "_LocalCompletionContext.__init__": report_invalid,
            "_build_local_safe_outputs": report_invalid,
            "_exact_keys": packet_invalid,
            "_hash_external_packet": packet_invalid,
            "_is_sha256": packet_invalid,
            "_local_completion_audit_report_hash": report_invalid,
            "_mapping": report_invalid,
            "_repository_contract_hash": documentation_binding,
            "_run_local_completion_context": report_invalid,
            "_safe_count": report_invalid,
            "_safe_hash": report_invalid,
            "_validate_external_attestations": packet_invalid,
            "_validate_external_hash_fields": packet_invalid,
            "aggregate_production_container_lifecycle_reports": lifecycle_invalid,
            "build_completion_audit_external_layer": completion_binding,
            "build_live_chatgpt_google_external_layer": chatgpt_builder,
            "build_mcp_inspector_external_layer": inspector_builder,
            "build_operator_cli_postgresql_external_layer": operator_cli,
            "build_reviewer_gate_external_layer": reviewer_builder,
            "main": [malformed_preclosure, operator_cli],
            "run_oauth_mcp_harness": report_invalid,
            "validate_completion_audit_external_layer": completion_binding,
            "validate_external_evidence_packet": [
                missing_implementation_contract,
                packet_invalid,
            ],
            "validate_live_chatgpt_google_external_layer": chatgpt_builder,
            "validate_mcp_inspector_external_layer": inspector_builder,
            "validate_operator_cli_postgresql_external_layer": operator_cli,
            "validate_production_container_lifecycle_external_layer": lifecycle_invalid,
            "validate_report": report_invalid,
            "validate_reviewer_gate_external_layer": reviewer_builder,
        }
        temporal_tests = {
            "build_live_chatgpt_google_external_layer": chatgpt_builder,
            "build_operator_cli_postgresql_external_layer": operator_cli,
            "run_oauth_mcp_harness": packet_revalidation,
            "validate_external_evidence_packet": packet_invalid,
            "validate_live_chatgpt_google_external_layer": chatgpt_builder,
            "validate_operator_cli_postgresql_external_layer": operator_cli,
            "validate_report": packet_revalidation,
        }
        rollback_tests = {
            "build_operator_cli_postgresql_external_layer": operator_cli,
            "main": [malformed_preclosure, output_write_failure],
            "run_oauth_mcp_harness": packet_revalidation,
            "validate_external_evidence_packet": [
                missing_implementation_contract,
                packet_invalid,
            ],
            "validate_operator_cli_postgresql_external_layer": operator_cli,
            "validate_report": packet_revalidation,
        }
        audit_tests = {
            "_build_local_safe_outputs": report_shape,
            "_local_completion_audit_report_hash": report_shape,
            "_run_local_completion_context": report_shape,
            "build_completion_audit_external_layer": completion_binding,
            "build_live_chatgpt_google_external_layer": chatgpt_builder,
            "build_operator_cli_postgresql_external_layer": operator_cli,
            "run_oauth_mcp_harness": report_shape,
            "validate_completion_audit_external_layer": completion_binding,
            "validate_external_evidence_packet": packet_invalid,
            "validate_live_chatgpt_google_external_layer": chatgpt_builder,
            "validate_operator_cli_postgresql_external_layer": operator_cli,
            "validate_report": packet_revalidation,
        }
        leak_tests = {
            "LifecycleEvidenceError.__init__": hostile_error_codes,
            "OperatorEvidenceError.__init__": hostile_error_codes,
            "_LocalCompletionContext.__init__": report_shape,
            "_build_local_safe_outputs": report_shape,
            "_exact_keys": packet_invalid,
            "_hash_external_packet": packet_invalid,
            "_is_sha256": packet_invalid,
            "_local_completion_audit_report_hash": report_shape,
            "_mapping": report_invalid,
            "_repository_contract_hash": documentation_binding,
            "_run_local_completion_context": report_shape,
            "_safe_count": report_shape,
            "_safe_hash": report_shape,
            "_validate_external_attestations": packet_invalid,
            "_validate_external_hash_fields": packet_invalid,
            "aggregate_production_container_lifecycle_reports": lifecycle_leak,
            "build_completion_audit_external_layer": packet_invalid,
            "build_live_chatgpt_google_external_layer": chatgpt_builder,
            "build_mcp_inspector_external_layer": inspector_builder,
            "build_operator_cli_postgresql_external_layer": operator_cli,
            "build_reviewer_gate_external_layer": reviewer_builder,
            "main": operator_cli,
            "run_oauth_mcp_harness": report_shape,
            "validate_completion_audit_external_layer": packet_invalid,
            "validate_external_evidence_packet": [
                missing_implementation_contract,
                packet_invalid,
            ],
            "validate_live_chatgpt_google_external_layer": chatgpt_builder,
            "validate_mcp_inspector_external_layer": inspector_builder,
            "validate_operator_cli_postgresql_external_layer": operator_cli,
            "validate_production_container_lifecycle_external_layer": lifecycle_leak,
            "validate_report": report_invalid,
            "validate_reviewer_gate_external_layer": reviewer_builder,
        }
        category_tests = {
            "invalid_or_protocol": invalid_tests,
            "expiry_replay_or_revocation": temporal_tests,
            "rollback_or_no_partial_state": rollback_tests,
            "audit_lineage": audit_tests,
            "leak_safety": leak_tests,
            "remote_http": {},
        }
        self.assertEqual(set(category_tests), set(REQUIRED_HARNESS_CATEGORIES) - {"success"})
        self.assertTrue(
            all(
                set(test_map).issubset(primary_test_by_qualname)
                for test_map in category_tests.values()
            )
        )

        def not_applicable_reason(qualname: str, category: str) -> str:
            identity = f"{module}.{qualname}"
            details = {
                "invalid_or_protocol": (
                    "receives only validated input and does not parse protocol input; "
                    "the caller-facing harness or dedicated layer validator owns "
                    "malformed packet and command rejection."
                ),
                "expiry_replay_or_revocation": (
                    "has no temporal state and does not own expiry, replay, or "
                    "revocation; the live identity journey and its dedicated layer "
                    "validator own those lifecycle assertions."
                ),
                "rollback_or_no_partial_state": (
                    "performs no durable write and does not open a transaction; it "
                    "only transforms or validates in-memory evidence while the source "
                    "journey owns rollback and partial-state cleanup."
                ),
                "audit_lineage": (
                    "does not emit audit and does not persist audit; it only carries "
                    "or validates bounded evidence while the connected runtime and "
                    "completion-audit layer own durable lineage."
                ),
                "leak_safety": (
                    "returns only a fixed public shape and cannot expose a raw path; "
                    "the bounded report and packet validators reject secret, path, "
                    "SQL, and transcript material before output."
                ),
                "remote_http": (
                    "is not an HTTP boundary and does not perform HTTP; it processes "
                    "local hash, status, count, CLI, or evidence objects while remote "
                    "transport belongs to Inspector and live ChatGPT runners."
                ),
            }
            return f"{identity} {details[category]}"

        for qualname, primary_test in sorted(primary_test_by_qualname.items()):
            key = (module, qualname)
            expected: dict[str, list[str] | str] = {"success": [primary_test]}
            for category, test_map in category_tests.items():
                mapped_test_ids = test_map.get(qualname)
                if mapped_test_ids is None:
                    expected[category] = not_applicable_reason(qualname, category)
                elif isinstance(mapped_test_ids, list):
                    expected[category] = sorted(mapped_test_ids)
                else:
                    expected[category] = [mapped_test_ids]

            with self.subTest(function_key=key):
                entry = entries[key]
                self.assertEqual(entry["status"], "onboarded")
                self.assertEqual(entry["source_binding"], bindings[key])
                self.assertEqual(
                    set(entry["categories"]),
                    set(REQUIRED_HARNESS_CATEGORIES),
                )
                category_union: set[str] = set()
                for category in REQUIRED_HARNESS_CATEGORIES:
                    expected_value = expected[category]
                    expected_ids = expected_value if isinstance(expected_value, list) else []
                    expected_reason = expected_value if isinstance(expected_value, str) else None
                    evidence = entry["categories"][category]
                    self.assertEqual(evidence["test_ids"], expected_ids)
                    self.assertEqual(
                        evidence["not_applicable_reason"],
                        expected_reason,
                    )
                    self.assertIn(evidence["pending_reason"], (None, ""))
                    self.assertTrue(set(expected_ids).issubset(collected))
                    category_union.update(expected_ids)
                self.assertTrue(category_union)
                self.assertEqual(entry["test_ids"], sorted(category_union))

        self.assert_batch_status_partition(manifest, target_keys)

        evidence_owners: dict[str, set[tuple[str, str]]] = {}
        for key in sorted(target_keys):
            item = entries[key]
            for evidence_test_id in item["test_ids"]:
                evidence_owners.setdefault(evidence_test_id, set()).add(key)
        self.assertLessEqual(max(map(len, evidence_owners.values())), 12)

    def test_connected_operator_postgresql_live_journey_batch_is_manifest_onboarded(
        self,
    ) -> None:
        manifest = load_function_harness_manifest()
        root = Path(__file__).resolve().parents[1]
        bindings = changed_scoped_function_bindings(
            root,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )
        collected = collect_unittest_test_ids(root / "tests")
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}
        module = "scripts.connected_operator_postgres_live_journey"
        prefix = (
            "tests.test_connected_operator_postgres_live_journey."
            "ConnectedOperatorPostgresLiveJourneyTests."
        )

        def test_id(name: str) -> str:
            return prefix + name

        command_boundary = test_id("test_command_boundary_is_exact_and_redacts_process_failures")
        operator_sequence = test_id(
            "test_operator_v2_command_sequence_covers_lifecycle_and_denials"
        )
        audit_contract = test_id("test_operator_v2_exact_audit_contract_is_closed")
        seed_records = test_id(
            "test_seed_operator_records_commits_exact_state_and_rolls_back_failure"
        )
        rollback_probe = test_id(
            "test_operator_rollback_probe_preserves_state_audit_and_safe_output"
        )
        outer_flow = test_id("test_outer_flow_bootstraps_an_empty_directory_with_the_built_image")
        authority_pin = test_id("test_execution_authority_pin_is_exact_and_tamper_evident")
        inside_success = test_id("test_inside_success_binds_runtime_and_emits_only_safe_report")
        inside_report_cleanup = test_id(
            "test_inside_report_creation_failures_cleanup_exact_inode_and_allow_retry"
        )
        nonroot_runtime = test_id("test_nonroot_runtime_requires_all_five_capability_sets_zero")
        report_body = test_id("test_report_body_validation_is_strict_side_effect_free_and_redacted")
        cli_validation = test_id("test_cli_validation_writes_only_safe_validation_result")
        failure_diagnostic = test_id(
            "test_cli_failure_diagnostic_is_finite_redacted_and_public_error_stays_generic"
        )
        runtime_cleanup_failure = test_id(
            "test_main_post_report_cleanup_failure_removes_success_artifact_and_writes_diagnostic"
        )
        primary_cleanup_failure = test_id(
            "test_outer_cleanup_preserves_primary_failure_and_still_removes_image"
        )
        resource_cleanup_failure = test_id(
            "test_nonzero_stop_or_network_cleanup_fails_closed_before_report_publication"
        )
        inside_failure_diagnostic = test_id(
            "test_inside_failure_diagnostic_maps_migration_stage_without_private_detail"
        )
        failure_stage_handoff_writer = test_id(
            "test_failure_stage_handoff_writer_never_masks_or_deletes_replacement"
        )
        failure_stage_handoff_validator = test_id(
            "test_failure_stage_handoff_validator_rejects_metadata_content_and_races"
        )
        diagnostic_persistence = test_id(
            "test_failure_diagnostic_persistence_never_masks_or_replaces_original_failure"
        )
        diagnostic_replacement_race = test_id(
            "test_failure_diagnostic_cleanup_preserves_replacement_race"
        )
        inner_diagnostic_transfer = test_id(
            "test_outer_accepts_only_exact_inside_failure_diagnostic_stages"
        )
        diagnostic_alias = test_id(
            "test_failure_diagnostic_output_aliases_fail_closed_before_docker"
        )
        inside_diagnostic_alias = test_id(
            "test_inside_failure_diagnostic_output_aliases_fail_closed_before_cli"
        )
        report_contract = test_id("test_report_contract_accepts_only_bound_hash_count_evidence")
        partial_authority = test_id(
            "test_partial_execution_authority_pair_locks_campaign_before_raw_run"
        )
        invalid_iid = test_id("test_missing_or_invalid_build_iid_stops_before_runtime_run")
        mutable_postgres = test_id("test_mutable_postgres_override_is_rejected_before_docker")
        inside_authority = test_id("test_inside_requires_exact_runtime_iid_authority_before_cli")
        report_handoff = test_id("test_outer_report_handoff_rejects_untrusted_metadata_and_bytes")
        runtime_data_cleanup = test_id(
            "test_runtime_data_cleanup_is_hardened_verified_then_removes_exact_image"
        )
        runtime_data_cleanup_payload = test_id(
            "test_runtime_data_cleanup_payload_deletes_uid_10001_mode_0700_tree"
        )

        groups = {
            command_boundary: {
                "_parse_json_output",
                "_run_command",
                "_run_operator_cli",
                "_safe_process_error",
            },
            operator_sequence: {
                "_execute_operator_v2_commands",
                "_execute_operator_v2_commands.<locals>.denial",
                "_execute_operator_v2_commands.<locals>.success",
            },
            audit_contract: {
                "_operator_audit_summary",
                "_summarize_operator_audit_rows",
            },
            seed_records: {
                "_operator_member_state",
                "_seed_operator_records",
            },
            rollback_probe: {
                "_AuditFailingRepository.__getattr__",
                "_AuditFailingRepository.__init__",
                "_AuditFailingRepository.append_audit_log",
                "_run_operator_rollback_probe",
            },
            outer_flow: {
                "_read_built_runtime_image_id",
                "_require_pinned_postgres_image",
                "_require_runtime_image_id",
                "_runtime_data_directory_is_empty",
                "_runtime_environment",
                "_runtime_secret_mounts",
                "_write_secret",
                "run_outer",
            },
            runtime_data_cleanup: {
                "_cleanup_runtime_data_and_image",
                "_runtime_data_cleanup_command",
            },
            failure_diagnostic: {"_write_failure_diagnostic"},
            failure_stage_handoff_writer: {"_write_failure_stage_handoff"},
            failure_stage_handoff_validator: {"_read_failure_stage_handoff"},
            authority_pin: {
                "_sha256_bytes",
                "_sha256_json",
            },
            inside_success: {"run_inside"},
            nonroot_runtime: {"_require_nonroot_runtime"},
            report_body: {"_contains_forbidden_text"},
            cli_validation: {
                "_build_parser",
                "main",
                "validate_report",
            },
        }
        primary_test_by_qualname = {
            qualname: primary_test
            for primary_test, qualnames in groups.items()
            for qualname in qualnames
        }
        target_keys = {(module, qualname) for qualname in primary_test_by_qualname}
        preserved_onboarded_qualnames = {
            "_execution_authority_blockers",
            "_execution_receipt_payload",
            "_validate_report_body",
            "attach_execution_receipt",
            "create_execution_authority",
            "create_execution_authority_pin",
            "validate_execution_authority_pin",
            "validate_execution_receipt",
        }
        preserved_keys = {(module, qualname) for qualname in preserved_onboarded_qualnames}
        module_entry_keys = {key for key in entries if key[0] == module}
        module_binding_keys = {key for key in bindings if key[0] == module}

        self.assertEqual(len(target_keys), 36)
        self.assertEqual(sum(map(len, groups.values())), 36)
        self.assertTrue(all(len(qualnames) <= 8 for qualnames in groups.values()))
        self.assertEqual(module_entry_keys, target_keys | preserved_keys)
        self.assertEqual(module_binding_keys, target_keys | preserved_keys)
        self.assertTrue(target_keys.issubset(bindings))
        self.assertTrue(target_keys.issubset(entries))
        for key in sorted(preserved_keys):
            with self.subTest(preserved_onboarded_key=key):
                self.assertEqual(entries[key]["status"], "onboarded")
                self.assertEqual(entries[key]["source_binding"], bindings[key])

        invalid_tests = {
            "_AuditFailingRepository.append_audit_log": rollback_probe,
            "_build_parser": failure_diagnostic,
            "_contains_forbidden_text": report_body,
            "_execute_operator_v2_commands": operator_sequence,
            "_execute_operator_v2_commands.<locals>.denial": operator_sequence,
            "_execute_operator_v2_commands.<locals>.success": operator_sequence,
            "_operator_audit_summary": audit_contract,
            "_parse_json_output": command_boundary,
            "_read_built_runtime_image_id": invalid_iid,
            "_read_failure_stage_handoff": failure_stage_handoff_validator,
            "_require_nonroot_runtime": nonroot_runtime,
            "_require_pinned_postgres_image": mutable_postgres,
            "_require_runtime_image_id": invalid_iid,
            "_run_command": command_boundary,
            "_run_operator_cli": command_boundary,
            "_run_operator_rollback_probe": rollback_probe,
            "_safe_process_error": command_boundary,
            "_seed_operator_records": seed_records,
            "_summarize_operator_audit_rows": audit_contract,
            "_write_failure_diagnostic": diagnostic_persistence,
            "_write_failure_stage_handoff": failure_stage_handoff_writer,
            "_write_secret": partial_authority,
            "main": (
                failure_diagnostic,
                inside_diagnostic_alias,
                runtime_cleanup_failure,
            ),
            "run_inside": (
                inside_diagnostic_alias,
                inside_authority,
            ),
            "run_outer": (
                diagnostic_alias,
                report_handoff,
                resource_cleanup_failure,
                runtime_cleanup_failure,
            ),
            "validate_report": report_contract,
        }
        temporal_tests = {
            "_execute_operator_v2_commands": operator_sequence,
            "_execute_operator_v2_commands.<locals>.denial": operator_sequence,
            "_execute_operator_v2_commands.<locals>.success": operator_sequence,
            "_operator_audit_summary": audit_contract,
            "_operator_member_state": seed_records,
            "_seed_operator_records": seed_records,
            "_summarize_operator_audit_rows": audit_contract,
            "main": cli_validation,
            "run_inside": inside_success,
            "validate_report": report_contract,
        }
        rollback_tests = {
            "_AuditFailingRepository.__getattr__": rollback_probe,
            "_AuditFailingRepository.__init__": rollback_probe,
            "_AuditFailingRepository.append_audit_log": rollback_probe,
            "_operator_member_state": rollback_probe,
            "_cleanup_runtime_data_and_image": (
                runtime_data_cleanup,
                runtime_data_cleanup_payload,
            ),
            "_run_operator_rollback_probe": rollback_probe,
            "_seed_operator_records": seed_records,
            "_write_failure_diagnostic": (
                diagnostic_persistence,
                diagnostic_replacement_race,
            ),
            "_write_failure_stage_handoff": failure_stage_handoff_writer,
            "_write_secret": partial_authority,
            "main": (
                diagnostic_persistence,
                runtime_cleanup_failure,
            ),
            "run_inside": (
                inside_failure_diagnostic,
                inside_report_cleanup,
            ),
            "run_outer": (
                diagnostic_persistence,
                report_handoff,
                resource_cleanup_failure,
                runtime_cleanup_failure,
                primary_cleanup_failure,
            ),
        }
        audit_tests = {
            "_AuditFailingRepository.__getattr__": rollback_probe,
            "_AuditFailingRepository.__init__": rollback_probe,
            "_AuditFailingRepository.append_audit_log": rollback_probe,
            "_operator_audit_summary": audit_contract,
            "_run_operator_rollback_probe": rollback_probe,
            "_summarize_operator_audit_rows": audit_contract,
            "main": cli_validation,
            "run_inside": inside_success,
            "validate_report": report_contract,
        }
        leak_tests = {
            "_AuditFailingRepository.__getattr__": rollback_probe,
            "_AuditFailingRepository.__init__": rollback_probe,
            "_AuditFailingRepository.append_audit_log": rollback_probe,
            "_contains_forbidden_text": report_body,
            "_operator_audit_summary": audit_contract,
            "_operator_member_state": rollback_probe,
            "_parse_json_output": command_boundary,
            "_read_built_runtime_image_id": invalid_iid,
            "_read_failure_stage_handoff": failure_stage_handoff_validator,
            "_require_nonroot_runtime": nonroot_runtime,
            "_require_pinned_postgres_image": mutable_postgres,
            "_require_runtime_image_id": invalid_iid,
            "_runtime_data_cleanup_command": runtime_data_cleanup,
            "_run_command": command_boundary,
            "_run_operator_cli": command_boundary,
            "_run_operator_rollback_probe": rollback_probe,
            "_safe_process_error": command_boundary,
            "_sha256_bytes": authority_pin,
            "_sha256_json": authority_pin,
            "_summarize_operator_audit_rows": audit_contract,
            "_write_failure_diagnostic": failure_diagnostic,
            "_write_failure_stage_handoff": failure_stage_handoff_writer,
            "main": (
                failure_diagnostic,
                runtime_cleanup_failure,
            ),
            "run_inside": (
                inside_failure_diagnostic,
                inside_report_cleanup,
            ),
            "run_outer": (
                inner_diagnostic_transfer,
                report_handoff,
                resource_cleanup_failure,
                runtime_cleanup_failure,
                primary_cleanup_failure,
            ),
            "validate_report": report_contract,
        }
        category_tests = {
            "invalid_or_protocol": invalid_tests,
            "expiry_replay_or_revocation": temporal_tests,
            "rollback_or_no_partial_state": rollback_tests,
            "audit_lineage": audit_tests,
            "leak_safety": leak_tests,
            "remote_http": {},
        }
        self.assertEqual(
            set(category_tests),
            set(REQUIRED_HARNESS_CATEGORIES) - {"success"},
        )
        self.assertTrue(
            all(
                set(test_map).issubset(primary_test_by_qualname)
                for test_map in category_tests.values()
            )
        )

        function_roles = {
            "_AuditFailingRepository.__getattr__": (
                "delegates non-audit repository access inside the injected " "audit-failure probe"
            ),
            "_AuditFailingRepository.__init__": (
                "stores one repository delegate for the injected audit-failure probe"
            ),
            "_AuditFailingRepository.append_audit_log": (
                "injects the exact audit persistence failure used by the rollback probe"
            ),
            "_build_parser": "constructs the fixed local command-line schema",
            "_contains_forbidden_text": (
                "recursively checks the bounded public report for forbidden material"
            ),
            "_execute_operator_v2_commands": (
                "orchestrates the fixed local operator CLI lifecycle"
            ),
            "_execute_operator_v2_commands.<locals>.denial": (
                "records one expected local CLI denial and hashes its safe stderr"
            ),
            "_execute_operator_v2_commands.<locals>.success": (
                "records one successful local CLI payload for later report hashing"
            ),
            "_operator_audit_summary": (
                "queries and delegates normalization of the closed operator audit set"
            ),
            "_operator_member_state": (
                "projects membership and token-session state into role and count fields"
            ),
            "_parse_json_output": ("parses one completed local process result into a dictionary"),
            "_read_built_runtime_image_id": (
                "reads and validates the immutable runtime image identifier"
            ),
            "_require_nonroot_runtime": (
                "validates uid, gid, supplementary groups, five capability sets, "
                "and no-new-privileges"
            ),
            "_require_pinned_postgres_image": (
                "accepts only the compile-time PostgreSQL image digest"
            ),
            "_require_runtime_image_id": (
                "accepts only an immutable sha256 runtime image identifier"
            ),
            "_run_command": "executes one bounded local subprocess command",
            "_run_operator_cli": (
                "adapts the local operator CLI result into success or exact denial"
            ),
            "_run_operator_rollback_probe": (
                "forces an audit failure and verifies membership and audit preservation"
            ),
            "_cleanup_runtime_data_and_image": (
                "removes runtime-owned data through the constrained runtime identity, "
                "verifies exact directory emptiness, and then removes the exact image"
            ),
            "_runtime_data_cleanup_command": (
                "constructs the capability-free UID/GID 10001 cleanup command"
            ),
            "_runtime_data_directory_is_empty": (
                "verifies the exact runtime data directory has no remaining entries"
            ),
            "_runtime_environment": ("constructs the fixed private runtime environment mapping"),
            "_runtime_secret_mounts": ("constructs private read-only secret mount arguments"),
            "_safe_process_error": (
                "extracts only an allowlisted safe error code from local stderr"
            ),
            "_seed_operator_records": (
                "atomically seeds the exact users, memberships, identities, "
                "authorizations, and token sessions"
            ),
            "_sha256_bytes": "returns one deterministic digest for internal bytes",
            "_sha256_json": "returns one deterministic digest for canonical JSON",
            "_summarize_operator_audit_rows": (
                "validates and summarizes the closed operator audit contract"
            ),
            "_write_secret": (
                "exclusively persists one private trust or secret file with mode 0400"
            ),
            "_write_failure_diagnostic": (
                "best-effort persists one closed redacted failure-stage artifact "
                "without replacing the original journey failure"
            ),
            "_write_failure_stage_handoff": (
                "best-effort persists one closed inner stage as a cross-UID-readable "
                "private handoff without replacing the original journey failure"
            ),
            "_read_failure_stage_handoff": (
                "validates one stable inner-owned handoff and returns only an "
                "allowlisted inner failure stage"
            ),
            "main": (
                "dispatches local validate, inner, or outer journey modes and emits "
                "only a safe error envelope"
            ),
            "run_inside": (
                "assembles the governed inner journey report from repository and CLI " "evidence"
            ),
            "run_outer": (
                "orchestrates the isolated runtime, PostgreSQL, inner journey, "
                "authority, receipt, and redacted failure-stage transfer"
            ),
            "validate_report": (
                "validates the public report body and independently pinned receipt"
            ),
        }
        self.assertEqual(
            set(function_roles),
            set(primary_test_by_qualname),
        )

        def not_applicable_reason(qualname: str, category: str) -> str:
            identity = f"{module}.{qualname}"
            role = function_roles[qualname]
            details = {
                "invalid_or_protocol": (
                    "it has no caller-controlled input and does not parse protocol "
                    "input at this layer; it receives only internally constructed "
                    "typed values."
                ),
                "expiry_replay_or_revocation": (
                    "it does not own expiry, replay, or revocation decisions; the "
                    "fixed lifecycle command, state projection, audit summary, or "
                    "report validator owns that temporal evidence."
                ),
                "rollback_or_no_partial_state": (
                    "it does not open a transaction and performs no durable write at "
                    "this layer; the seed transaction, audit-failure probe, or "
                    "exclusive trust-file writer owns partial-state behavior."
                ),
                "audit_lineage": (
                    "it does not emit audit or persist audit rows; the operator CLI, "
                    "closed audit summary, and rollback probe own durable audit lineage."
                ),
                "leak_safety": (
                    "it returns no caller-visible data at this boundary; its private "
                    "internal value is consumed by the enclosing journey before safe "
                    "report validation."
                ),
                "remote_http": (
                    "it is not an HTTP boundary and does not perform HTTP; its "
                    "behavior is limited to local hashing, parsing, subprocess, "
                    "filesystem, PostgreSQL, or report orchestration."
                ),
            }
            return f"{identity} {role}; {details[category]}"

        for qualname, primary_test in sorted(primary_test_by_qualname.items()):
            key = (module, qualname)
            expected: dict[str, list[str] | str] = {"success": [primary_test]}
            for category, test_map in category_tests.items():
                mapped_tests = test_map.get(qualname)
                expected[category] = (
                    list(mapped_tests)
                    if isinstance(mapped_tests, tuple)
                    else [mapped_tests]
                    if isinstance(mapped_tests, str)
                    else not_applicable_reason(qualname, category)
                )

            with self.subTest(function_key=key):
                entry = entries[key]
                self.assertEqual(entry["status"], "onboarded")
                self.assertEqual(entry["source_binding"], bindings[key])
                self.assertEqual(
                    set(entry["categories"]),
                    set(REQUIRED_HARNESS_CATEGORIES),
                )
                category_union: set[str] = set()
                for category in REQUIRED_HARNESS_CATEGORIES:
                    expected_value = expected[category]
                    expected_ids = expected_value if isinstance(expected_value, list) else []
                    expected_reason = expected_value if isinstance(expected_value, str) else None
                    evidence = entry["categories"][category]
                    self.assertEqual(evidence["test_ids"], expected_ids)
                    self.assertEqual(
                        evidence["not_applicable_reason"],
                        expected_reason,
                    )
                    self.assertIn(evidence["pending_reason"], (None, ""))
                    self.assertTrue(set(expected_ids).issubset(collected))
                    category_union.update(expected_ids)
                self.assertTrue(category_union)
                self.assertEqual(entry["test_ids"], sorted(category_union))

        self.assert_batch_status_partition(manifest, target_keys)

        evidence_owners: dict[str, set[tuple[str, str]]] = {}
        for key in sorted(target_keys):
            item = entries[key]
            for evidence_test_id in item["test_ids"]:
                evidence_owners.setdefault(evidence_test_id, set()).add(key)
        self.assertLessEqual(max(map(len, evidence_owners.values())), 12)

        validation = validate_function_harness_manifest(manifest, root=root)
        self.assertEqual(
            [blocker for blocker in validation["blockers"] if module in blocker],
            [],
        )

    def test_issue20_external_packet_batch_is_manifest_onboarded(self) -> None:
        manifest = load_function_harness_manifest()
        root = Path(__file__).resolve().parents[1]
        bindings = changed_scoped_function_bindings(
            root,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )
        collected = collect_unittest_test_ids(root / "tests")
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}
        module = "formowl_evidence.issue20_packet"
        test_prefix = (
            "tests.test_issue20_external_evidence_packet." "Issue20GovernedSourceTemplateTest."
        )
        validation_prefix = (
            "tests.test_issue20_external_evidence_packet." "Issue20GovernedSourceValidationTest."
        )
        builder_prefix = (
            "tests.test_issue20_external_evidence_packet." "Issue20ExternalPacketBuilderTest."
        )
        template_exact = test_prefix + "test_templates_are_safe_exact_and_intentionally_incomplete"
        template_cli = test_prefix + "test_template_cli_writes_private_files_without_echoing_paths"
        template_rollback = test_prefix + "test_template_write_failure_rolls_back_the_whole_set"
        validation_output_failure = (
            test_prefix + "test_validation_cli_persistent_output_failure_returns_safe_stdout"
        )
        json_loader = (
            test_prefix + "test_json_input_loader_accepts_objects_and_rejects_invalid_inputs_safely"
        )
        completed_sources = (
            validation_prefix + "test_completed_sources_build_authority_valid_public_layers"
        )
        audit_ordering = (
            validation_prefix + "test_missing_duplicate_and_out_of_order_audit_records_are_rejected"
        )
        forbidden_material = (
            validation_prefix + "test_secret_url_email_transcript_and_path_material_are_rejected"
        )
        local_receipt = (
            validation_prefix + "test_local_harness_receipt_remains_local_only_and_contract_bound"
        )
        operator_delegation = (
            builder_prefix + "test_operator_report_contract_is_delegated_to_current_authority"
        )
        preparation = (
            builder_prefix
            + "test_preparation_helpers_bind_sources_without_claiming_external_completion"
        )
        complete_packet = (
            builder_prefix + "test_complete_packet_is_accepted_by_current_schema_v5_authority"
        )
        migration_pin = (
            builder_prefix + "test_schema_migration_candidate_cannot_replace_original_pre_run_pin"
        )
        paired_validation = (
            builder_prefix + "test_paired_validation_accepts_the_exact_same_rebuilt_packet"
        )

        groups = {
            template_exact: {
                "_chatgpt_source_template",
                "_completion_source_template",
                "_event_templates",
                "_is_real_hash",
                "_mapping",
                "_mcp_source_template",
                "_reviewer_source_template",
                "source_templates",
                "_validate_attestations",
                "_validate_common_source_header",
                "_validate_exact_keys",
                "_validate_required_hash",
            },
            completed_sources: {
                "_build_live_chatgpt_google_layer",
                "_build_live_chatgpt_google_layer.<locals>.lineage",
                "_build_live_chatgpt_google_layer.<locals>.observation",
                "_build_mcp_inspector_layer",
                "_build_reviewer_gate_layer",
                "_source_hash",
                "_source_validation_result",
                "_validate_built_layer",
                "validate_governed_sources",
                "validate_live_chatgpt_google_source",
                "validate_mcp_inspector_source",
                "validate_reviewer_gate_source",
            },
            audit_ordering: {
                "_event",
                "_safe_audit_record_hash",
                "_safe_blocker",
                "_validate_audit_records",
                "_validate_events",
                "_validate_identities",
                "_validate_no_forbidden_material",
                "_validate_no_forbidden_material.<locals>.walk",
                "_validate_relink_bindings",
            },
            complete_packet: {
                "_build_external_packet_from_validated_inputs",
                "_raise_source_validation",
                "_validate_existing_layer",
                "validate_completion_audit_source",
            },
            template_cli: {
                "_add_core_evidence_arguments",
                "_add_source_arguments",
                "_template_command",
                "_write_atomic_directory",
                "_write_json",
                "main",
            },
            json_loader: {
                "EvidencePacketError.__init__",
                "_read_json",
            },
            local_receipt: {
                "_validated_local_receipt",
                "validate_local_harness_report",
            },
            preparation: {
                "_core_evidence_review_packet",
                "_reviewed_layer_artifact_set_hash",
                "prepare_completion_audit_source",
                "prepare_reviewer_materials",
            },
            operator_delegation: {"_operator_layer_from_report"},
            migration_pin: {
                "_lifecycle_layer_from_reports",
                "build_external_packet",
                "validated_live_postgresql_report_layer",
            },
            paired_validation: {"validate_current_packet"},
        }
        primary_test_by_qualname = {
            qualname: test_id for test_id, qualnames in groups.items() for qualname in qualnames
        }
        target_keys = {(module, qualname) for qualname in primary_test_by_qualname}
        self.assertEqual(len(target_keys), 56)
        self.assertEqual(sum(map(len, groups.values())), 56)
        self.assertTrue(all(len(qualnames) <= 12 for qualnames in groups.values()))
        self.assertTrue(target_keys.issubset(bindings))
        self.assertTrue(target_keys.issubset(entries))
        self.assertEqual(
            {key for key in entries if key[0] == module},
            target_keys,
        )

        temporal_qualnames = {
            "_build_live_chatgpt_google_layer",
            "_build_live_chatgpt_google_layer.<locals>.lineage",
            "_build_live_chatgpt_google_layer.<locals>.observation",
            "_lifecycle_layer_from_reports",
            "_validate_audit_records",
            "_validate_events",
            "_validate_identities",
            "_validate_relink_bindings",
            "build_external_packet",
            "validate_current_packet",
            "validate_governed_sources",
            "validate_live_chatgpt_google_source",
            "validated_live_postgresql_report_layer",
        }
        rollback_tests = {
            "_template_command": template_rollback,
            "_write_atomic_directory": template_rollback,
            "_write_json": template_rollback,
            "main": validation_output_failure,
        }
        invalid_tests = {"main": validation_output_failure}
        leak_tests = {"main": validation_output_failure}
        audit_qualnames = (
            groups[completed_sources]
            | groups[audit_ordering]
            | groups[complete_packet]
            | groups[local_receipt]
            | groups[preparation]
            | groups[operator_delegation]
            | groups[migration_pin]
            | groups[paired_validation]
        )
        self.assertTrue(temporal_qualnames.issubset(primary_test_by_qualname))
        self.assertTrue(set(rollback_tests).issubset(primary_test_by_qualname))
        self.assertTrue(audit_qualnames.issubset(primary_test_by_qualname))

        def not_applicable_reason(qualname: str, category: str) -> str:
            identity = f"{module}.{qualname}"
            details = {
                "expiry_replay_or_revocation": (
                    "has no temporal state and does not own expiry, replay, or "
                    "revocation; its bounded packet operation neither decides nor "
                    "changes a token, membership, grant, or external-evidence lifecycle."
                ),
                "rollback_or_no_partial_state": (
                    "performs no durable write and mutates no repository state; its "
                    "bounded in-memory packet operation opens no transaction and leaves "
                    "artifact persistence to the explicit atomic writer boundary."
                ),
                "audit_lineage": (
                    "does not emit audit and has no audit side effect; it supplies one "
                    "bounded packet value or local orchestration step while governed "
                    "source and completion validators own evidence audit lineage."
                ),
                "remote_http": (
                    "is not an HTTP boundary and does not perform HTTP; it runs in the "
                    "offline evidence-packet library or local CLI below every remote "
                    "route, request, response, challenge, and transport adapter."
                ),
            }
            return f"{identity} {details[category]}"

        for qualname, primary_test in sorted(primary_test_by_qualname.items()):
            key = (module, qualname)
            expected = {
                "success": [primary_test],
                "invalid_or_protocol": [invalid_tests.get(qualname, primary_test)],
                "expiry_replay_or_revocation": (
                    [primary_test]
                    if qualname in temporal_qualnames
                    else not_applicable_reason(
                        qualname,
                        "expiry_replay_or_revocation",
                    )
                ),
                "rollback_or_no_partial_state": (
                    [rollback_tests[qualname]]
                    if qualname in rollback_tests
                    else not_applicable_reason(
                        qualname,
                        "rollback_or_no_partial_state",
                    )
                ),
                "audit_lineage": (
                    [primary_test]
                    if qualname in audit_qualnames
                    else not_applicable_reason(qualname, "audit_lineage")
                ),
                "leak_safety": (
                    [forbidden_material]
                    if qualname in groups[audit_ordering]
                    else [leak_tests.get(qualname, primary_test)]
                ),
                "remote_http": not_applicable_reason(qualname, "remote_http"),
            }
            with self.subTest(function_key=key):
                entry = entries[key]
                self.assertEqual(entry["status"], "onboarded")
                self.assertEqual(entry["source_binding"], bindings[key])
                self.assertEqual(
                    set(entry["categories"]),
                    set(REQUIRED_HARNESS_CATEGORIES),
                )
                category_union: set[str] = set()
                for category in REQUIRED_HARNESS_CATEGORIES:
                    expected_value = expected[category]
                    expected_ids = expected_value if isinstance(expected_value, list) else []
                    expected_reason = expected_value if isinstance(expected_value, str) else None
                    evidence = entry["categories"][category]
                    self.assertEqual(evidence["test_ids"], expected_ids)
                    self.assertEqual(
                        evidence["not_applicable_reason"],
                        expected_reason,
                    )
                    self.assertIn(evidence["pending_reason"], (None, ""))
                    self.assertTrue(set(expected_ids).issubset(collected))
                    category_union.update(expected_ids)
                self.assertTrue(category_union)
                self.assertEqual(entry["test_ids"], sorted(category_union))

        self.assert_batch_status_partition(manifest, target_keys)

        evidence_owners: dict[str, set[tuple[str, str]]] = {}
        for item in manifest["functions"]:
            key = (item["module"], item["qualname"])
            for test_id in item["test_ids"]:
                evidence_owners.setdefault(test_id, set()).add(key)
        self.assertLessEqual(max(map(len, evidence_owners.values())), 12)

    def test_connected_runtime_container_lifecycle_probe_batch_is_manifest_onboarded(
        self,
    ) -> None:
        manifest = load_function_harness_manifest()
        root = Path(__file__).resolve().parents[1]
        bindings = changed_scoped_function_bindings(
            root,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )
        collected = collect_unittest_test_ids(root / "tests")
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}
        module, function_roles, expected_by_qualname = lifecycle_probe_onboarding_contract()
        target_keys = {(module, qualname) for qualname in expected_by_qualname}
        module_entry_keys = {key for key in entries if key[0] == module}
        module_binding_keys = {key for key in bindings if key[0] == module}

        self.assertEqual(len(target_keys), 66)
        self.assertEqual(set(function_roles), set(expected_by_qualname))
        self.assertEqual(module_entry_keys, target_keys)
        self.assertEqual(module_binding_keys, target_keys)
        self.assertTrue(target_keys.issubset(entries))
        self.assertTrue(target_keys.issubset(bindings))

        for qualname, expected in sorted(expected_by_qualname.items()):
            key = (module, qualname)
            with self.subTest(function_key=key):
                entry = entries[key]
                self.assertEqual(entry["status"], "onboarded")
                self.assertEqual(entry["source_binding"], bindings[key])
                self.assertEqual(
                    set(entry["categories"]),
                    set(REQUIRED_HARNESS_CATEGORIES),
                )
                category_union: set[str] = set()
                for category in REQUIRED_HARNESS_CATEGORIES:
                    expected_value = expected[category]
                    expected_ids = expected_value if isinstance(expected_value, list) else []
                    expected_reason = expected_value if isinstance(expected_value, str) else None
                    evidence = entry["categories"][category]
                    self.assertEqual(evidence["test_ids"], expected_ids)
                    self.assertEqual(
                        evidence["not_applicable_reason"],
                        expected_reason,
                    )
                    self.assertIn(evidence["pending_reason"], (None, ""))
                    self.assertTrue(set(expected_ids).issubset(collected))
                    category_union.update(expected_ids)
                self.assertTrue(category_union)
                self.assertEqual(entry["test_ids"], sorted(category_union))

        self.assert_batch_status_partition(manifest, target_keys)

        evidence_owners: dict[str, set[tuple[str, str]]] = {}
        for item in manifest["functions"]:
            key = (item["module"], item["qualname"])
            for evidence_test_id in item["test_ids"]:
                evidence_owners.setdefault(evidence_test_id, set()).add(key)
        self.assertLessEqual(max(map(len, evidence_owners.values())), 12)

        validation = validate_function_harness_manifest(manifest, root=root)
        self.assertEqual(
            [blocker for blocker in validation["blockers"] if module in blocker],
            [],
        )

    def test_shared_manifest_convergence_rows_are_source_bound_and_evidence_backed(
        self,
    ) -> None:
        manifest = load_function_harness_manifest()
        root = Path(__file__).resolve().parents[1]
        bindings = changed_scoped_function_bindings(
            root,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}
        audit_keys = {
            (
                "formowl_auth.postgres",
                "PostgreSQLOAuthRepository.list_issue20_live_audit_rows",
            ),
            ("formowl_gateway.runtime", "ConnectedRuntime.export_issue20_live_audit"),
            ("formowl_gateway.runtime", "_build_issue20_audit_records"),
            ("formowl_gateway.runtime", "_issue20_action_rows"),
            ("formowl_gateway.runtime", "_issue20_between"),
            ("formowl_gateway.runtime", "_issue20_binding_hash"),
            ("formowl_gateway.runtime", "_issue20_callback_row"),
            ("formowl_gateway.runtime", "_issue20_metadata_shape"),
            ("formowl_gateway.runtime", "_issue20_one"),
            ("formowl_gateway.runtime", "_issue20_row_sort_key"),
            ("formowl_gateway.runtime", "_issue20_row_time"),
            ("formowl_gateway.runtime", "_issue20_tool_window_one"),
            ("formowl_gateway.runtime", "_issue20_window_one"),
            ("formowl_gateway.runtime", "_normalize_issue20_audit_rows"),
            ("formowl_gateway.runtime", "_project_issue20_audit_record"),
            ("formowl_gateway.runtime", "_require_issue20_operator_membership_row"),
            ("formowl_gateway.runtime", "_require_issue20_row"),
            ("formowl_gateway.runtime", "_require_issue20_scopes"),
            ("formowl_gateway.runtime", "_require_issue20_service_row"),
            ("formowl_gateway.runtime", "_validate_issue20_audit_output_path"),
            ("formowl_gateway.runtime", "_validate_issue20_http_denial"),
            ("formowl_gateway.runtime", "_validate_issue20_initial_callback"),
            ("formowl_gateway.runtime", "_validate_issue20_relink_callback"),
            ("formowl_gateway.runtime", "_validate_issue20_token_row"),
            ("formowl_gateway.runtime", "_validate_issue20_tool_row"),
            ("formowl_gateway.runtime", "_write_issue20_audit_artifact"),
        }
        runner_qualnames = {
            "_git_output",
            "_implementation_contract_hash",
            "_read_campaign_pin",
            "_read_regular_file",
            "_sha256_bytes",
            "_unique_object",
            "clear_operator_candidates",
            "create_campaign_pin",
            "file_sha256",
            "seal_operator_trust_inputs",
            "tree_sha256",
            "verify_campaign",
        }
        runner_keys = {
            ("scripts.issue20_runner_boundary", qualname) for qualname in runner_qualnames
        }
        target_keys = audit_keys | runner_keys
        self.assertEqual(len(audit_keys), 26)
        self.assertEqual(len(runner_keys), 12)
        self.assertEqual(len(target_keys), 38)
        self.assertTrue(target_keys.issubset(bindings))
        self.assertTrue(target_keys.issubset(entries))

        for key in target_keys:
            entry = entries[key]
            self.assertEqual(entry["status"], "onboarded")
            self.assertEqual(entry["source_binding"], bindings[key])
            self.assertTrue(entry["categories"]["success"]["test_ids"])
            self.assertTrue(entry["test_ids"])

        runner_prefix = (
            "tests.test_issue20_containerized_evidence_runner."
            "Issue20ContainerizedEvidenceRunnerContractTest."
        )
        runner_test_ids = {
            runner_prefix + "test_campaign_pin_rejects_mixed_source_snapshot_and_pin_tamper",
            runner_prefix
            + "test_operator_candidates_are_outer_sealed_and_failed_seal_is_retryable",
            runner_prefix + "test_non_preflight_mode_without_campaign_pin_fails_stale_closed",
            runner_prefix + "test_runner_explicitly_reports_docker_daemon_authority_not_sandboxing",
        }
        claimed_runner_tests = {
            test_id for key in runner_keys for test_id in entries[key]["test_ids"]
        }
        self.assertTrue(runner_test_ids.issubset(claimed_runner_tests))

        audit_cli_test = (
            "tests.test_issue20_operator_audit_export.Issue20AuditExportTests."
            "test_cli_success_and_failure_outputs_do_not_disclose_private_values"
        )
        for key in (
            ("formowl_gateway.runtime", "_build_parser"),
            ("formowl_gateway.runtime", "_run_command"),
        ):
            self.assertIn(audit_cli_test, entries[key]["test_ids"])
            self.assertEqual(entries[key]["source_binding"], bindings[key])

    def test_deploy_operator_config_batch_is_manifest_onboarded(self) -> None:
        manifest = load_function_harness_manifest()
        root = Path(__file__).resolve().parents[1]
        bindings = changed_scoped_function_bindings(
            root,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )
        collected = collect_unittest_test_ids(root / "tests")
        entries = {(item["module"], item["qualname"]): item for item in manifest["functions"]}
        module = "deploy.connected.operator_config"
        validation_qualnames = {
            "_compose_environment",
            "_parser",
            "_require_callback",
            "_require_chatgpt_client_id",
            "_require_google_redirect_uri",
            "_require_identifier",
            "_require_image_id",
            "_require_public_host",
            "_require_text",
            "_unique_object",
        }
        io_qualnames = {
            "_check_public",
            "_import_google_secret",
            "_predefined_client_id",
            "_read_json_file",
            "_read_public_json",
            "_read_public_status",
            "_wait_until_expired",
            "_write_compose_env",
            "_write_exclusive",
            "_write_replace",
            "main",
        }
        helper_qualnames = {
            "_parser",
            "_predefined_client_id",
            "_require_chatgpt_client_id",
            "_write_exclusive",
            "main",
        }
        container_qualnames = {
            "_compose_environment",
            "_predefined_client_id",
            "_require_callback",
            "_require_chatgpt_client_id",
        }
        expected_qualnames = validation_qualnames | io_qualnames
        target_keys = {(module, qualname) for qualname in expected_qualnames}
        self.assertEqual(len(validation_qualnames), 10)
        self.assertEqual(len(io_qualnames), 11)
        self.assertTrue(validation_qualnames.isdisjoint(io_qualnames))
        self.assertEqual(len(target_keys), 21)
        self.assertTrue(target_keys.issubset(bindings))
        self.assertTrue(target_keys.issubset(entries))

        prefix = "tests.test_issue20_operator_docs_contracts." "Issue20OperatorDocsContractsTest."
        validation_test = (
            prefix + "test_operator_config_validation_and_compose_helpers_run_in_process"
        )
        io_test = prefix + "test_operator_config_io_public_and_cli_helpers_run_in_process"
        helper_test = (
            prefix + "test_operator_helper_derives_and_validates_safe_predefined_client_id"
        )
        container_test = (
            "tests.test_connected_runtime_container.ConnectedRuntimeContainerTests."
            "test_operator_docs_pin_exact_callback_and_discovery_only_boundary"
        )
        expected_ids_by_qualname = {
            qualname: sorted(
                {
                    *({validation_test} if qualname in validation_qualnames else set()),
                    *({io_test} if qualname in io_qualnames else set()),
                    *({helper_test} if qualname in helper_qualnames else set()),
                    *({container_test} if qualname in container_qualnames else set()),
                }
            )
            for qualname in expected_qualnames
        }

        for qualname in sorted(expected_qualnames):
            key = (module, qualname)
            with self.subTest(function_key=key):
                entry = entries[key]
                self.assertEqual(entry["status"], "onboarded")
                self.assertEqual(entry["source_binding"], bindings[key])
                self.assertEqual(
                    entry["source_binding"]["source_path"],
                    "deploy/connected/operator_config.py",
                )
                self.assertEqual(entry["source_binding"]["change_kind"], "added")
                self.assertEqual(set(entry["categories"]), set(REQUIRED_HARNESS_CATEGORIES))
                category_union: set[str] = set()
                for category in REQUIRED_HARNESS_CATEGORIES:
                    evidence = entry["categories"][category]
                    self.assertIn(evidence["pending_reason"], (None, ""))
                    if evidence["test_ids"]:
                        self.assertIn(evidence["not_applicable_reason"], (None, ""))
                        self.assertTrue(set(evidence["test_ids"]).issubset(collected))
                        category_union.update(evidence["test_ids"])
                    else:
                        self.assertNotEqual(category, "success")
                        reason = evidence["not_applicable_reason"]
                        self.assertIsInstance(reason, str)
                        self.assertIn(f"{module}.{qualname}", reason)
                self.assertEqual(entry["test_ids"], sorted(category_union))
                self.assertEqual(entry["test_ids"], expected_ids_by_qualname[qualname])

        evidence_owners: dict[str, set[tuple[str, str]]] = {}
        for item in manifest["functions"]:
            key = (item["module"], item["qualname"])
            for evidence_test_id in item["test_ids"]:
                evidence_owners.setdefault(evidence_test_id, set()).add(key)
        self.assertEqual(
            evidence_owners[validation_test],
            {(module, qualname) for qualname in validation_qualnames},
        )
        self.assertEqual(
            evidence_owners[io_test],
            {(module, qualname) for qualname in io_qualnames},
        )
        self.assertLessEqual(max(map(len, evidence_owners.values())), 12)

        self.assert_batch_status_partition(manifest, target_keys)
        validation = validate_function_harness_manifest(manifest, root=root)
        self.assertEqual(
            {
                "changed": validation["changed_function_count"],
                "manifest": validation["function_entry_count"],
                "manifested": validation["manifested_function_count"],
                "onboarded": validation["onboarded_function_count"],
            },
            {
                "changed": 689,
                "manifest": 689,
                "manifested": 689,
                "onboarded": 689,
            },
        )
        self.assertEqual(
            {
                "missing": validation["missing_function_count"],
                "extra": validation["extra_function_count"],
                "duplicate": validation["duplicate_function_count"],
                "binding_mismatch": validation["source_binding_mismatch_count"],
                "pending": validation["pending_function_count"],
            },
            {
                "missing": 0,
                "extra": 0,
                "duplicate": 0,
                "binding_mismatch": 0,
                "pending": 0,
            },
        )
        self.assertEqual(
            [blocker for blocker in validation["blockers"] if module in blocker],
            [],
        )

    def test_manifest_is_bound_to_locked_base_and_every_changed_function_is_onboarded(
        self,
    ) -> None:
        manifest = load_function_harness_manifest()

        validation = validate_function_harness_manifest(manifest)

        self.assertEqual(manifest["base_commit"], ISSUE20_BASE_COMMIT)
        self.assertTrue(validation["passed"], validation["blockers"])
        self.assertEqual(validation["blockers"], [])
        self.assertGreater(validation["function_entry_count"], 0)
        self.assertGreater(validation["test_id_count"], 0)
        self.assertTrue(validation["manifest_hash"].startswith("sha256:"))
        self.assertTrue(validation["changed_function_set_hash"].startswith("sha256:"))

    def test_validator_rejects_duplicate_unknown_and_incomplete_entries(self) -> None:
        function_key = ("formowl_auth.synthetic", "pending_function")
        duplicate_identity = ".".join(function_key)
        source_binding = {
            "source_path": "python/formowl_auth/synthetic.py",
            "change_kind": "added",
            "base_ast_sha256": None,
            "current_ast_sha256": f"sha256:{'1' * 64}",
            "diff_sha256": f"sha256:{'2' * 64}",
        }
        categories = {
            category: {
                "test_ids": [],
                "not_applicable_reason": None,
                "pending_reason": (
                    f"{duplicate_identity} is pending "
                    f"{category.replace('_', ' ')} evidence because this isolated "
                    "synthetic validator fixture intentionally withholds the "
                    "category-specific executable test."
                ),
            }
            for category in REQUIRED_HARNESS_CATEGORIES
        }
        first = {
            "module": function_key[0],
            "qualname": function_key[1],
            "status": "pending",
            "source_binding": source_binding,
            "categories": categories,
            "test_ids": [],
        }
        manifest = {
            "schema_version": 2,
            "issue_number": 20,
            "base_commit": ISSUE20_BASE_COMMIT,
            "scope": {
                "include_globs": list(ISSUE20_FUNCTION_SCOPE_GLOBS),
                "exclusion_rules": list(ISSUE20_FUNCTION_EXCLUSION_RULES),
            },
            "required_categories": list(REQUIRED_HARNESS_CATEGORIES),
            "functions": [first],
        }
        duplicate_index = len(manifest["functions"])
        unknown_test_id = "tests.test_missing.MissingTests.test_missing"
        duplicate = copy.deepcopy(first)
        duplicate["test_ids"] = [unknown_test_id]
        duplicate["categories"]["success"] = {
            "test_ids": [],
            "not_applicable_reason": "",
        }
        duplicate["categories"].pop("remote_http")
        for category in REQUIRED_HARNESS_CATEGORIES:
            if category in {"success", "remote_http"}:
                continue
            duplicate["categories"][category]["pending_reason"] += (
                " The duplicate-row variant uses separate bounded wording."
            )
        manifest["functions"].append(duplicate)

        with (
            patch("oauth_harness.collect_unittest_test_ids", return_value=set()),
            patch(
                "oauth_harness.current_scoped_functions",
                return_value={function_key},
            ),
            patch(
                "oauth_harness.changed_scoped_function_bindings",
                return_value={function_key: source_binding},
            ),
        ):
            validation = validate_function_harness_manifest(manifest)

        self.assertFalse(validation["passed"])
        blockers = validation["blockers"]
        self.assertIn(
            f"duplicate function manifest entry: {duplicate_identity}",
            blockers,
        )
        self.assertIn(
            f"unknown test id for {duplicate_identity}: {unknown_test_id}",
            blockers,
        )
        self.assertIn(
            f"manifest.functions[{duplicate_index}].categories.success.pending_reason "
            "must be a non-empty function-specific reason",
            blockers,
        )
        self.assertIn(
            f"manifest.functions[{duplicate_index}].categories.remote_http must be an object",
            blockers,
        )

    def test_missing_git_base_fails_closed_instead_of_skipping_completeness(self) -> None:
        manifest = load_function_harness_manifest()
        manifest["base_commit"] = "0" * 40

        with self.assertRaises(AssertionError):
            validate_function_harness_manifest(manifest)

    def test_changed_function_gate_includes_untracked_production_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            tracked = root / "python" / "example" / "tracked.py"
            tracked.parent.mkdir(parents=True)
            tracked.write_text("def unchanged():\n    return 1\n", encoding="utf-8")
            self._git(root, "init")
            self._git(root, "config", "user.name", "FormOwl Harness")
            self._git(root, "config", "user.email", "harness@example.invalid")
            self._git(root, "add", tracked.relative_to(root).as_posix())
            self._git(root, "commit", "-m", "locked base")
            base_commit = self._git(root, "rev-parse", "HEAD").stdout.strip()

            untracked = root / "scripts" / "oauth_feature.py"
            untracked.parent.mkdir()
            untracked.write_text(
                "def newly_added():\n    return 2\n\n"
                "async def newly_added_async():\n    return 3\n",
                encoding="utf-8",
            )

            changed = changed_scoped_functions(
                root,
                base_commit=base_commit,
                include_globs=("python/example/**/*.py", "scripts/*.py"),
            )

        self.assertEqual(
            changed,
            {
                ("scripts.oauth_feature", "newly_added"),
                ("scripts.oauth_feature", "newly_added_async"),
            },
        )

    def test_authoritative_changed_bindings_include_both_live_script_bodies(self) -> None:
        bindings = changed_scoped_function_bindings(
            Path(__file__).resolve().parents[1],
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
        )
        source_paths = {binding["source_path"] for binding in bindings.values()}

        self.assertIn(
            "scripts/connected_runtime_container_lifecycle_probe.py",
            source_paths,
        )
        self.assertIn(
            "scripts/connected_runtime_postgres_live_e2e.py",
            source_paths,
        )
        self.assertNotIn(
            ("formowl_retrieval.gateway", "RetrievalGateway._audit"),
            bindings,
        )
        self.assertNotIn(
            ("formowl_retrieval.gateway", "RetrievalGateway._query_effective_graph"),
            bindings,
        )

    def test_changed_function_bindings_pin_path_change_kind_and_ast_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            tracked = root / "python" / "example" / "tracked.py"
            tracked.parent.mkdir(parents=True)
            tracked.write_text("def modified():\n    return 1\n", encoding="utf-8")
            self._git(root, "init")
            self._git(root, "config", "user.name", "FormOwl Harness")
            self._git(root, "config", "user.email", "harness@example.invalid")
            self._git(root, "add", tracked.relative_to(root).as_posix())
            self._git(root, "commit", "-m", "locked base")
            base_commit = self._git(root, "rev-parse", "HEAD").stdout.strip()

            tracked.write_text("def modified():\n    return 2\n", encoding="utf-8")
            added = root / "scripts" / "connected_runtime_added.py"
            added.parent.mkdir()
            added.write_text(
                "class Runner:\n" "    def __call__(self):\n" "        return 'ready'\n",
                encoding="utf-8",
            )

            bindings = changed_scoped_function_bindings(
                root,
                base_commit=base_commit,
                include_globs=("python/example/**/*.py", "scripts/*.py"),
            )

        modified = bindings[("example.tracked", "modified")]
        added_dunder = bindings[("scripts.connected_runtime_added", "Runner.__call__")]
        self.assertEqual(modified["source_path"], "python/example/tracked.py")
        self.assertEqual(modified["change_kind"], "modified")
        self.assertTrue(str(modified["base_ast_sha256"]).startswith("sha256:"))
        self.assertTrue(str(modified["current_ast_sha256"]).startswith("sha256:"))
        self.assertNotEqual(modified["base_ast_sha256"], modified["current_ast_sha256"])
        self.assertTrue(str(modified["diff_sha256"]).startswith("sha256:"))
        self.assertEqual(
            added_dunder,
            {
                "source_path": "scripts/connected_runtime_added.py",
                "change_kind": "added",
                "base_ast_sha256": None,
                "current_ast_sha256": added_dunder["current_ast_sha256"],
                "diff_sha256": added_dunder["diff_sha256"],
            },
        )
        self.assertTrue(str(added_dunder["current_ast_sha256"]).startswith("sha256:"))
        self.assertTrue(str(added_dunder["diff_sha256"]).startswith("sha256:"))

    @staticmethod
    def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-c", f"safe.directory={root.resolve()}", *arguments],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
