"""Disposable PostgreSQL adapter for the Issue #33 storage benchmark.

This module is intentionally isolated from FormOwl's production migrations and
repositories.  It loads only a source-free sealed benchmark package into
temporary benchmark tables.
"""

from __future__ import annotations

import json
from typing import Any

from formowl_contract import ContractValidationError

from .benchmark_contract import (
    BenchmarkRequest,
    BenchmarkResult,
    FaultAction,
    FaultExecutionEvidence,
    RestoreExecutionEvidence,
    SemanticState,
    StorageEngineBenchmarkPackage,
    canonical_json_sha256,
    fault_action_value_hash,
    fault_for_action,
    fixture_data,
    initial_semantic_state,
    input_record_payload,
    reference_execute_request,
    request_input_payload,
    result_payload,
    seal_fault_execution_evidence,
    seal_restore_execution_evidence,
    seal_semantic_state,
    semantic_state_digest,
    semantic_state_payload,
    transition_semantic_state,
    validate_benchmark_package,
)


class PostgreSQLBenchmarkPort:
    """A single disposable PostgreSQL benchmark namespace.

    The adapter persists the sealed fixture in typed benchmark tables and uses
    PostgreSQL reads to cross-check every graph/effective-view/lifecycle/
    structured-row result before returning the storage-neutral reference
    result.  It never calls production FormOwl migrations.
    """

    def __init__(self, connection: Any) -> None:
        self._connection = connection
        self._package: StorageEngineBenchmarkPackage | None = None
        self._armed_action: FaultAction | None = None
        self._last_fault_execution: FaultExecutionEvidence | None = None
        self._last_restore_execution: RestoreExecutionEvidence | None = None

    @classmethod
    def connect(cls, dsn: str) -> "PostgreSQLBenchmarkPort":
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - environment preflight
            raise RuntimeError("benchmark PostgreSQL driver is unavailable") from exc
        return cls(psycopg.connect(dsn, autocommit=False))

    def close(self) -> None:
        self._connection.close()

    def load_sealed_package(self, package: StorageEngineBenchmarkPackage) -> None:
        validate_benchmark_package(package)
        self._armed_action = None
        self._last_fault_execution = None
        self._last_restore_execution = None
        data = fixture_data(package.fixture)
        with self._connection.transaction():
            self._drop_schema()
            self._create_schema()
            self._execute(
                "INSERT INTO issue33_benchmark_meta (meta_key, meta_value) VALUES (%s, %s::jsonb)",
                ("package", json.dumps(package.to_dict(), sort_keys=True)),
            )
            self._execute(
                "INSERT INTO issue33_benchmark_state (state_id, fixture_hash, state_json) "
                "VALUES ('current', %s, %s::jsonb)",
                (package.fixture.content_hash, initial_semantic_state(package).state_json),
            )
            for kind, records in data.items():
                if isinstance(records, list):
                    self._executemany(
                        "INSERT INTO issue33_benchmark_fixture (record_kind, record_id, payload) "
                        "VALUES (%s, %s, %s::jsonb)",
                        [
                            (
                                kind,
                                _fixture_record_id(kind, record),
                                json.dumps(record, sort_keys=True),
                            )
                            for record in records
                        ],
                    )
            self._executemany(
                "INSERT INTO issue33_benchmark_node "
                "(node_id, scope_id, visible_actor_ids, candidate_id, active) "
                "VALUES (%s, %s, %s::jsonb, %s, false)",
                [
                    (
                        record["node_id"],
                        record["scope_id"],
                        json.dumps(record["visible_to"]),
                        record["candidate_id"],
                    )
                    for record in data["canonical_nodes"]
                ],
            )
            self._executemany(
                "INSERT INTO issue33_benchmark_relation "
                "(relation_id, scope_id, source_node_id, target_node_id, visible_actor_ids, "
                "candidate_relation_id, active) VALUES (%s, %s, %s, %s, %s::jsonb, %s, false)",
                [
                    (
                        record["relation_id"],
                        record["scope_id"],
                        record["source_node_id"],
                        record["target_node_id"],
                        json.dumps(record["visible_to"]),
                        record["candidate_relation_id"],
                    )
                    for record in data["canonical_relations"]
                ],
            )
            self._executemany(
                "INSERT INTO issue33_benchmark_structural_row "
                "(row_id, scope_id, structural_kind, visible_actor_ids, observation_id, candidate_id) "
                "VALUES (%s, %s, %s, %s::jsonb, %s, %s)",
                [
                    (
                        record["row_id"],
                        record["scope_id"],
                        record["structural_kind"],
                        json.dumps(record["visible_to"]),
                        record["observation_id"],
                        record["candidate_id"],
                    )
                    for record in data["structured_rows"]
                ],
            )
            self._executemany(
                "INSERT INTO issue33_benchmark_lifecycle "
                "(event_id, scope_id, sequence, event_type, previous_ids, target_ids, active) "
                "VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, false)",
                [
                    (
                        record["event_id"],
                        record["scope_id"],
                        record["sequence"],
                        record["event_type"],
                        json.dumps(record["previous_ids"]),
                        json.dumps(record["target_ids"]),
                    )
                    for record in data["lifecycle_events"]
                ],
            )
        self._package = package

    def arm_fault(self, action: FaultAction) -> None:
        if self._armed_action is not None:
            raise ContractValidationError("benchmark fault already armed")
        fault_for_action(self._require_package(), action)
        self._armed_action = action

    def inspect_semantic_state(self) -> SemanticState:
        self._require_package()
        row = self._execute(
            "SELECT fixture_hash, state_json FROM issue33_benchmark_state "
            "WHERE state_id = 'current'"
        ).fetchone()
        if row is None:
            raise ContractValidationError("benchmark semantic state is unavailable")
        state = seal_semantic_state(row[0], row[1])
        self._assert_stored_state_matches(state)
        return state

    def inspect_last_fault_execution(self) -> FaultExecutionEvidence | None:
        return self._last_fault_execution

    def inspect_last_restore_execution(self) -> RestoreExecutionEvidence | None:
        return self._last_restore_execution

    def stage_candidate_batch(self, request: BenchmarkRequest) -> BenchmarkResult:
        return self._execute_request(request)

    def reviewed_commit_with_lifecycle(self, request: BenchmarkRequest) -> BenchmarkResult:
        return self._execute_request(request)

    def effective_view(self, request: BenchmarkRequest) -> BenchmarkResult:
        return self._execute_request(request)

    def bounded_traverse(self, request: BenchmarkRequest) -> BenchmarkResult:
        return self._execute_request(request)

    def resolve_lifecycle(self, request: BenchmarkRequest) -> BenchmarkResult:
        return self._execute_request(request)

    def structured_set_handoff(self, request: BenchmarkRequest) -> BenchmarkResult:
        return self._execute_request(request)

    def backup_restore(self, request: BenchmarkRequest) -> BenchmarkResult:
        return self._execute_request(request)

    def _execute_request(self, request: BenchmarkRequest) -> BenchmarkResult:
        package = self._require_package()
        action = self._consume_fault()
        if action is not None:
            fault = fault_for_action(package, action)
            return self._execute_fault(request, action, fault.expected_result)

        state = self.inspect_semantic_state()
        result = reference_execute_request(package, request, state)
        if request.operation == "backup_restore" and result.status == "success":
            return self._execute_backup_restore(request, state, result)
        with self._connection.transaction():
            if request.operation == "stage_candidate_batch" and result.status == "success":
                batch = input_record_payload(request.inputs[0])
                self._executemany(
                    "INSERT INTO issue33_benchmark_stage (record_kind, record_id) "
                    "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    [("candidate", value) for value in batch["candidate_ids"]]
                    + [("relation", value) for value in batch["relation_ids"]],
                )
            elif (
                request.operation == "reviewed_commit_with_lifecycle" and result.status == "success"
            ):
                plan = input_record_payload(request.inputs[0])
                self._execute(
                    "UPDATE issue33_benchmark_node SET active = true WHERE node_id = ANY(%s)",
                    (plan["node_ids"],),
                )
                self._execute(
                    "UPDATE issue33_benchmark_relation SET active = true "
                    "WHERE relation_id = ANY(%s)",
                    (plan["relation_ids"],),
                )
                self._execute(
                    "UPDATE issue33_benchmark_lifecycle SET active = true WHERE event_id = ANY(%s)",
                    (plan["lifecycle_event_ids"],),
                )
            next_state = transition_semantic_state(package, request, state)
            self._execute(
                "UPDATE issue33_benchmark_state SET fixture_hash = %s, state_json = %s::jsonb "
                "WHERE state_id = 'current'",
                (next_state.fixture_hash, next_state.state_json),
            )
        persisted = self.inspect_semantic_state()
        self._verify_native_reads(request, persisted, result)
        return result

    def _execute_fault(
        self,
        request: BenchmarkRequest,
        action: FaultAction,
        expected_result: BenchmarkResult,
    ) -> BenchmarkResult:
        """Exercise one sealed fault inside a transaction that must abort."""

        before = self.inspect_semantic_state()
        native_transaction_started = False
        native_action_exercised = False
        transaction_rolled_back = False
        try:
            with self._connection.transaction():
                native_transaction_started = True
                self._apply_fault_native_action(request, action, before)
                native_action_exercised = True
                raise _InjectedBenchmarkFault()
        except _InjectedBenchmarkFault:
            transaction_rolled_back = True
        after = self.inspect_semantic_state()
        if before != after:
            raise ContractValidationError("benchmark PostgreSQL fault rollback mismatch")
        self._last_fault_execution = seal_fault_execution_evidence(
            action,
            before,
            after,
            native_transaction_started=native_transaction_started,
            native_action_exercised=native_action_exercised,
            transaction_rolled_back=transaction_rolled_back,
        )
        return expected_result

    def _apply_fault_native_action(
        self,
        request: BenchmarkRequest,
        action: FaultAction,
        before: SemanticState,
    ) -> None:
        """Run the sealed phase/action pair, rejecting every unknown pair."""

        self._record_fault_trace(action)
        branch = (action.injection_point, action.action_kind)
        if branch == ("policy_validation", "replace_value"):
            self._require_fault_operation(request, "reviewed_commit_with_lifecycle")
            self._exercise_validation_trace(action)
        elif branch == ("open_transaction", "raise_error"):
            self._require_fault_operation(request, "reviewed_commit_with_lifecycle")
            self._exercise_open_transaction_trace(action)
        elif branch == ("relation_scope_validation", "insert_relation"):
            self._require_fault_operation(request, "stage_candidate_batch")
            self._exercise_validation_trace(action)
        elif branch in {
            ("authorizer", "assert_value"),
            ("authorizer", "replace_value"),
            ("authorizer", "remove_field"),
        }:
            self._require_fault_operation(request, "effective_view")
            self._exercise_authorization_trace(request, action)
        elif branch == ("lifecycle_write", "duplicate_id"):
            self._require_fault_operation(request, "reviewed_commit_with_lifecycle")
            self._exercise_lifecycle_duplicate_write(action)
        elif branch == ("post_validation_pre_write", "replace_value"):
            self._require_fault_operation(request, "stage_candidate_batch")
            self._exercise_stage_partial_write(action)
        elif branch == ("lifecycle_validation", "insert_cycle"):
            self._require_fault_operation(request, "reviewed_commit_with_lifecycle")
            self._exercise_validation_trace(action)
        elif branch == ("typed_plan_validation", "replace_value"):
            self._require_fault_operation(request, "structured_set_handoff")
            self._exercise_validation_trace(action)
        elif branch == ("pre_materialization_reauthorization", "replace_value"):
            self._require_fault_operation(request, "effective_view")
            self._exercise_authorization_trace(request, action)
        elif branch == ("post_members_pre_revision", "raise_error"):
            self._require_fault_operation(request, "reviewed_commit_with_lifecycle")
            self._exercise_reviewed_commit_partial_write(
                request,
                before,
                include_revision=False,
            )
        elif branch == ("post_revision_pre_audit", "raise_error"):
            self._require_fault_operation(request, "reviewed_commit_with_lifecycle")
            self._exercise_reviewed_commit_partial_write(
                request,
                before,
                include_revision=True,
            )
        elif branch == ("review_validation", "replace_value"):
            self._require_fault_operation(request, "reviewed_commit_with_lifecycle")
            self._exercise_validation_trace(action)
        elif branch == ("ontology_validation", "replace_value"):
            self._require_fault_operation(request, "reviewed_commit_with_lifecycle")
            self._exercise_validation_trace(action)
        elif branch in {
            ("fanout_limit", "enforce_limit"),
            ("path_limit", "enforce_limit"),
        }:
            self._require_fault_operation(request, "bounded_traverse")
            self._exercise_traversal_limit(action)
        elif branch == ("timeout", "expire_timer"):
            self._require_fault_operation(request, "bounded_traverse")
            self._exercise_timeout_trace(action)
        else:
            raise ContractValidationError("benchmark PostgreSQL fault action is unsupported")

    def _record_fault_trace(self, action: FaultAction) -> None:
        value_hash = fault_action_value_hash(action)
        self._execute(
            "INSERT INTO issue33_benchmark_fault_probe "
            "(fault_id, action_kind, injection_point, target_kind, target_id, field_name, value_hash) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                action.action_id,
                action.action_kind,
                action.injection_point,
                action.target_kind,
                action.target_id,
                action.field_name,
                value_hash,
            ),
        )
        row = self._execute(
            "SELECT action_kind, injection_point, target_kind, target_id, field_name, value_hash "
            "FROM issue33_benchmark_fault_probe WHERE fault_id = %s",
            (action.action_id,),
        ).fetchone()
        if row != (
            action.action_kind,
            action.injection_point,
            action.target_kind,
            action.target_id,
            action.field_name,
            value_hash,
        ):
            raise ContractValidationError("benchmark PostgreSQL fault trace mismatch")

    def _require_fault_operation(self, request: BenchmarkRequest, operation: str) -> None:
        if request.operation != operation:
            raise ContractValidationError("benchmark PostgreSQL fault operation mismatch")

    def _exercise_validation_trace(self, action: FaultAction) -> None:
        row = self._execute(
            "SELECT count(*) FROM issue33_benchmark_fault_probe "
            "WHERE fault_id = %s AND action_kind = %s AND injection_point = %s",
            (action.action_id, action.action_kind, action.injection_point),
        ).fetchone()
        if row != (1,):
            raise ContractValidationError("benchmark PostgreSQL validation trace mismatch")

    def _exercise_open_transaction_trace(self, action: FaultAction) -> None:
        self._exercise_validation_trace(action)
        row = self._execute(
            "SELECT count(*) FROM issue33_benchmark_state WHERE state_id = 'current'"
        ).fetchone()
        if row != (1,):
            raise ContractValidationError("benchmark PostgreSQL transaction trace mismatch")

    def _exercise_authorization_trace(self, request: BenchmarkRequest, action: FaultAction) -> None:
        self._exercise_validation_trace(action)
        actor = input_record_payload(request.authorization)["actor"]
        row = self._execute(
            "SELECT count(*) FROM issue33_benchmark_node " "WHERE visible_actor_ids ? %s",
            (actor["actor_profile_id"],),
        ).fetchone()
        if row is None or row[0] < 0:
            raise ContractValidationError("benchmark PostgreSQL authorization trace mismatch")

    def _exercise_stage_partial_write(self, action: FaultAction) -> None:
        self._execute(
            "INSERT INTO issue33_benchmark_stage (record_kind, record_id) "
            "VALUES ('candidate', %s) ON CONFLICT DO NOTHING",
            (action.target_id,),
        )
        row = self._execute(
            "SELECT count(*) FROM issue33_benchmark_stage "
            "WHERE record_kind = 'candidate' AND record_id = %s",
            (action.target_id,),
        ).fetchone()
        if row != (1,):
            raise ContractValidationError("benchmark PostgreSQL staged fault write mismatch")

    def _exercise_lifecycle_duplicate_write(self, action: FaultAction) -> None:
        self._execute(
            "INSERT INTO issue33_benchmark_lifecycle "
            "(event_id, scope_id, sequence, event_type, previous_ids, target_ids, active) "
            "SELECT event_id, scope_id, sequence, event_type, previous_ids, target_ids, active "
            "FROM issue33_benchmark_lifecycle WHERE event_id = %s "
            "ON CONFLICT (event_id) DO UPDATE SET active = NOT issue33_benchmark_lifecycle.active",
            (action.target_id,),
        )
        row = self._execute(
            "SELECT count(*) FROM issue33_benchmark_lifecycle WHERE event_id = %s",
            (action.target_id,),
        ).fetchone()
        if row != (1,):
            raise ContractValidationError("benchmark PostgreSQL lifecycle fault write mismatch")

    def _exercise_reviewed_commit_partial_write(
        self,
        request: BenchmarkRequest,
        before: SemanticState,
        *,
        include_revision: bool,
    ) -> None:
        package = self._require_package()
        plan = input_record_payload(request.inputs[0])
        self._execute(
            "UPDATE issue33_benchmark_node SET active = true WHERE node_id = ANY(%s)",
            (plan["node_ids"],),
        )
        self._execute(
            "UPDATE issue33_benchmark_relation SET active = true WHERE relation_id = ANY(%s)",
            (plan["relation_ids"],),
        )
        self._execute(
            "UPDATE issue33_benchmark_lifecycle SET active = true WHERE event_id = ANY(%s)",
            (plan["lifecycle_event_ids"],),
        )
        if include_revision:
            next_state = transition_semantic_state(package, request, before)
            self._execute(
                "UPDATE issue33_benchmark_state SET fixture_hash = %s, state_json = %s::jsonb "
                "WHERE state_id = 'current'",
                (next_state.fixture_hash, next_state.state_json),
            )
        counts = self._execute(
            "SELECT "
            "(SELECT count(*) FROM issue33_benchmark_node WHERE active), "
            "(SELECT count(*) FROM issue33_benchmark_relation WHERE active), "
            "(SELECT count(*) FROM issue33_benchmark_lifecycle WHERE active)"
        ).fetchone()
        if counts is None or any(value <= 0 for value in counts):
            raise ContractValidationError("benchmark PostgreSQL review fault write mismatch")

    def _exercise_traversal_limit(self, action: FaultAction) -> None:
        try:
            limit = json.loads(action.value_json)
        except json.JSONDecodeError as exc:
            raise ContractValidationError("benchmark PostgreSQL fault limit is invalid") from exc
        if type(limit) is not int or limit < 0:
            raise ContractValidationError("benchmark PostgreSQL fault limit is invalid")
        rows = self._execute(
            "SELECT relation_id FROM issue33_benchmark_relation " "ORDER BY relation_id LIMIT %s",
            (limit,),
        ).fetchall()
        if len(rows) > limit:
            raise ContractValidationError("benchmark PostgreSQL traversal limit mismatch")

    def _exercise_timeout_trace(self, action: FaultAction) -> None:
        try:
            timeout_milliseconds = json.loads(action.value_json)
        except json.JSONDecodeError as exc:
            raise ContractValidationError("benchmark PostgreSQL fault timeout is invalid") from exc
        if type(timeout_milliseconds) is not int or timeout_milliseconds <= 0:
            raise ContractValidationError("benchmark PostgreSQL fault timeout is invalid")
        row = self._execute("SELECT clock_timestamp() IS NOT NULL").fetchone()
        if row != (True,):
            raise ContractValidationError("benchmark PostgreSQL timeout trace mismatch")

    def _execute_backup_restore(
        self,
        request: BenchmarkRequest,
        before: SemanticState,
        result: BenchmarkResult,
    ) -> BenchmarkResult:
        """Back up, destroy, and restore semantic plus native benchmark state."""

        backup_state: SemanticState | None = None
        destructive_state: SemanticState | None = None
        restored_state: SemanticState | None = None
        native_backup_created = False
        native_destructive_mutation_observed = False
        restore_verified = False
        with self._connection.transaction():
            self._backup_current_native_state()
            backup_state = self._inspect_backup_semantic_state()
            if backup_state != before:
                raise ContractValidationError("benchmark PostgreSQL backup state mismatch")
            native_backup_created = True

            destructive_state = self._destructive_semantic_state(before)
            self._destructively_mutate_current_state(destructive_state)
            observed_destructive = self.inspect_semantic_state()
            if observed_destructive != destructive_state or semantic_state_digest(
                observed_destructive
            ) == semantic_state_digest(before):
                raise ContractValidationError("benchmark PostgreSQL destructive state mismatch")
            native_destructive_mutation_observed = True

            self._restore_current_native_state()
            restored_state = self.inspect_semantic_state()
            if (
                restored_state != backup_state
                or restored_state != before
                or not self._current_native_state_matches_backup()
            ):
                raise ContractValidationError("benchmark PostgreSQL restore state mismatch")
            restore_verified = True

        after = self.inspect_semantic_state()
        if restored_state is None or after != restored_state or after != before:
            raise ContractValidationError("benchmark PostgreSQL restore persistence mismatch")
        if backup_state is None or destructive_state is None:
            raise ContractValidationError("benchmark PostgreSQL restore evidence is unavailable")
        self._last_restore_execution = seal_restore_execution_evidence(
            backup_state,
            destructive_state,
            restored_state,
            native_backup_created=native_backup_created,
            native_destructive_mutation_observed=native_destructive_mutation_observed,
            restore_verified=restore_verified,
        )
        self._verify_native_reads(request, after, result)
        return result

    def _backup_current_native_state(self) -> None:
        current = self._execute(
            "SELECT fixture_hash, state_json FROM issue33_benchmark_state "
            "WHERE state_id = 'current'"
        ).fetchone()
        if current is None:
            raise ContractValidationError("benchmark PostgreSQL backup state is unavailable")
        current_state = seal_semantic_state(current[0], current[1])
        self._execute("DELETE FROM issue33_benchmark_backup_stage WHERE backup_id = 'last'")
        self._execute("DELETE FROM issue33_benchmark_backup_node WHERE backup_id = 'last'")
        self._execute("DELETE FROM issue33_benchmark_backup_relation WHERE backup_id = 'last'")
        self._execute("DELETE FROM issue33_benchmark_backup_lifecycle WHERE backup_id = 'last'")
        self._execute(
            "INSERT INTO issue33_benchmark_backup (backup_id, fixture_hash, state_json) "
            "VALUES ('last', %s, %s::jsonb) ON CONFLICT (backup_id) DO UPDATE "
            "SET fixture_hash = EXCLUDED.fixture_hash, state_json = EXCLUDED.state_json",
            (current_state.fixture_hash, current_state.state_json),
        )
        self._execute(
            "INSERT INTO issue33_benchmark_backup_stage (backup_id, record_kind, record_id) "
            "SELECT 'last', record_kind, record_id FROM issue33_benchmark_stage"
        )
        self._execute(
            "INSERT INTO issue33_benchmark_backup_node "
            "(backup_id, node_id, scope_id, visible_actor_ids, candidate_id, active) "
            "SELECT 'last', node_id, scope_id, visible_actor_ids, candidate_id, active "
            "FROM issue33_benchmark_node"
        )
        self._execute(
            "INSERT INTO issue33_benchmark_backup_relation "
            "(backup_id, relation_id, scope_id, source_node_id, target_node_id, visible_actor_ids, "
            "candidate_relation_id, active) "
            "SELECT 'last', relation_id, scope_id, source_node_id, target_node_id, "
            "visible_actor_ids, candidate_relation_id, active FROM issue33_benchmark_relation"
        )
        self._execute(
            "INSERT INTO issue33_benchmark_backup_lifecycle "
            "(backup_id, event_id, scope_id, sequence, event_type, previous_ids, target_ids, active) "
            "SELECT 'last', event_id, scope_id, sequence, event_type, previous_ids, target_ids, active "
            "FROM issue33_benchmark_lifecycle"
        )
        self._assert_backup_state_matches(current_state)

    def _inspect_backup_semantic_state(self) -> SemanticState:
        row = self._execute(
            "SELECT fixture_hash, state_json FROM issue33_benchmark_backup WHERE backup_id = 'last'"
        ).fetchone()
        if row is None:
            raise ContractValidationError("benchmark PostgreSQL backup state is unavailable")
        state = seal_semantic_state(row[0], row[1])
        self._assert_backup_state_matches(state)
        return state

    def _destructive_semantic_state(self, state: SemanticState) -> SemanticState:
        return seal_semantic_state(
            state.fixture_hash,
            {
                "staged_candidate_ids": [],
                "staged_relation_ids": [],
                "nodes": [],
                "relations": [],
                "revision_ids": [],
                "lifecycle_event_ids": [],
                "success_audit_ids": [],
            },
        )

    def _destructively_mutate_current_state(self, destructive_state: SemanticState) -> None:
        self._execute("DELETE FROM issue33_benchmark_stage")
        self._execute("UPDATE issue33_benchmark_node SET active = false")
        self._execute("UPDATE issue33_benchmark_relation SET active = false")
        self._execute("UPDATE issue33_benchmark_lifecycle SET active = false")
        self._execute(
            "UPDATE issue33_benchmark_state SET fixture_hash = %s, state_json = %s::jsonb "
            "WHERE state_id = 'current'",
            (destructive_state.fixture_hash, destructive_state.state_json),
        )

    def _restore_current_native_state(self) -> None:
        backup = self._execute(
            "SELECT fixture_hash, state_json::text FROM issue33_benchmark_backup WHERE backup_id = 'last'"
        ).fetchone()
        if backup is None:
            raise ContractValidationError("benchmark PostgreSQL restore backup is unavailable")
        self._execute("DELETE FROM issue33_benchmark_stage")
        self._execute("DELETE FROM issue33_benchmark_node")
        self._execute("DELETE FROM issue33_benchmark_relation")
        self._execute("DELETE FROM issue33_benchmark_lifecycle")
        self._execute(
            "INSERT INTO issue33_benchmark_stage (record_kind, record_id) "
            "SELECT record_kind, record_id FROM issue33_benchmark_backup_stage "
            "WHERE backup_id = 'last'"
        )
        self._execute(
            "INSERT INTO issue33_benchmark_node "
            "(node_id, scope_id, visible_actor_ids, candidate_id, active) "
            "SELECT node_id, scope_id, visible_actor_ids, candidate_id, active "
            "FROM issue33_benchmark_backup_node WHERE backup_id = 'last'"
        )
        self._execute(
            "INSERT INTO issue33_benchmark_relation "
            "(relation_id, scope_id, source_node_id, target_node_id, visible_actor_ids, "
            "candidate_relation_id, active) "
            "SELECT relation_id, scope_id, source_node_id, target_node_id, visible_actor_ids, "
            "candidate_relation_id, active FROM issue33_benchmark_backup_relation "
            "WHERE backup_id = 'last'"
        )
        self._execute(
            "INSERT INTO issue33_benchmark_lifecycle "
            "(event_id, scope_id, sequence, event_type, previous_ids, target_ids, active) "
            "SELECT event_id, scope_id, sequence, event_type, previous_ids, target_ids, active "
            "FROM issue33_benchmark_backup_lifecycle WHERE backup_id = 'last'"
        )
        self._execute(
            "UPDATE issue33_benchmark_state SET fixture_hash = %s, state_json = %s::jsonb "
            "WHERE state_id = 'current'",
            backup,
        )

    def _verify_native_reads(
        self,
        request: BenchmarkRequest,
        state: SemanticState,
        result: BenchmarkResult,
    ) -> None:
        if result.status != "success":
            return
        authorization = input_record_payload(request.authorization)
        actor = authorization["actor"]
        payload = result_payload(result)
        if request.operation in {"effective_view", "reviewed_commit_with_lifecycle"}:
            ids = self._visible_ids(actor["actor_profile_id"], actor["scope_id"])
            if ids != payload["item_ids"]:
                raise ContractValidationError("benchmark PostgreSQL effective view mismatch")
        elif request.operation == "bounded_traverse":
            if (
                self._traverse(actor["actor_profile_id"], actor["scope_id"], request)
                != payload["paths"]
            ):
                raise ContractValidationError("benchmark PostgreSQL traversal mismatch")
        elif request.operation == "resolve_lifecycle":
            if self._lifecycle() != payload["lifecycle"]:
                raise ContractValidationError("benchmark PostgreSQL lifecycle mismatch")
        elif request.operation == "structured_set_handoff":
            coverage = request_input_payload(request, "coverage_contract_r1")
            rows = self._structural_rows(
                actor["actor_profile_id"], coverage["scope_id"], coverage["covered_row_ids"]
            )
            if rows != payload["structural_rows"]:
                raise ContractValidationError("benchmark PostgreSQL structured set mismatch")
        if state != self.inspect_semantic_state():
            raise ContractValidationError("benchmark PostgreSQL state changed during read")

    def _visible_ids(self, actor_id: str, scope_id: str) -> list[str]:
        nodes = [
            row[0]
            for row in self._execute(
                "SELECT node_id FROM issue33_benchmark_node "
                "WHERE active AND scope_id = %s AND visible_actor_ids ? %s ORDER BY node_id",
                (scope_id, actor_id),
            ).fetchall()
        ]
        relations = [
            row[0]
            for row in self._execute(
                "SELECT relation_id FROM issue33_benchmark_relation relation "
                "JOIN issue33_benchmark_node source ON source.node_id = relation.source_node_id "
                "JOIN issue33_benchmark_node target ON target.node_id = relation.target_node_id "
                "WHERE relation.active AND relation.scope_id = %s "
                "AND relation.visible_actor_ids ? %s AND source.active AND target.active "
                "AND source.visible_actor_ids ? %s AND target.visible_actor_ids ? %s "
                "ORDER BY relation_id",
                (scope_id, actor_id, actor_id, actor_id),
            ).fetchall()
        ]
        return sorted(nodes + relations)

    def _traverse(
        self, actor_id: str, scope_id: str, request: BenchmarkRequest
    ) -> list[dict[str, list[str]]]:
        traversal = input_record_payload(request.inputs[0])
        start = traversal["start_node_id"]
        nodes = {
            row[0]: {"node_id": row[0], "visible": row[1]}
            for row in self._execute(
                "SELECT node_id, visible_actor_ids FROM issue33_benchmark_node "
                "WHERE active AND scope_id = %s",
                (scope_id,),
            ).fetchall()
        }
        if start not in nodes or actor_id not in nodes[start]["visible"]:
            return []
        outgoing: dict[str, list[dict[str, str]]] = {}
        for relation_id, source, target, visible in self._execute(
            "SELECT relation_id, source_node_id, target_node_id, visible_actor_ids "
            "FROM issue33_benchmark_relation WHERE active AND scope_id = %s",
            (scope_id,),
        ).fetchall():
            if actor_id in visible and target in nodes and actor_id in nodes[target]["visible"]:
                outgoing.setdefault(source, []).append(
                    {"relation_id": relation_id, "target_node_id": target}
                )
        for values in outgoing.values():
            values.sort(key=lambda item: (item["target_node_id"], item["relation_id"]))
        frontier = [{"node_ids": [start], "relation_ids": []}]
        paths: list[dict[str, list[str]]] = []
        for _ in range(traversal["maximum_hops"]):
            next_frontier = []
            for path in frontier:
                for relation in outgoing.get(path["node_ids"][-1], [])[
                    : traversal["per_frontier_fanout"]
                ]:
                    if relation["target_node_id"] in path["node_ids"]:
                        continue
                    next_path = {
                        "node_ids": path["node_ids"] + [relation["target_node_id"]],
                        "relation_ids": path["relation_ids"] + [relation["relation_id"]],
                    }
                    paths.append(next_path)
                    next_frontier.append(next_path)
            frontier = next_frontier
        return sorted(
            paths,
            key=lambda item: (
                len(item["relation_ids"]),
                item["node_ids"][-1],
                item["relation_ids"][-1],
            ),
        )[: traversal["maximum_returned_paths"]]

    def _lifecycle(self) -> dict[str, Any]:
        events = [
            {
                "event_id": row[0],
                "event_type": row[1],
                "previous_ids": row[2],
                "target_ids": row[3],
            }
            for row in self._execute(
                "SELECT event_id, event_type, previous_ids, target_ids "
                "FROM issue33_benchmark_lifecycle WHERE active ORDER BY sequence, event_id"
            ).fetchall()
        ]
        current = {"node_0000"}
        applied: list[str] = []
        kinds: list[str] = []
        for event in events:
            if set(event["previous_ids"]) <= current:
                current.difference_update(event["previous_ids"])
                current.update(event["target_ids"])
                applied.append(event["event_id"])
                kinds.append(event["event_type"])
        return {
            "status": "merged" if kinds[-2:] == ["split", "merge"] else "current",
            "current_ids": sorted(current),
            "event_ids": applied,
        }

    def _structural_rows(
        self, actor_id: str, scope_id: str, row_ids: list[str]
    ) -> list[dict[str, str]]:
        return [
            {
                "row_id": row[0],
                "scope_id": row[1],
                "field_name": "structural_kind",
                "field_value_json": json.dumps(row[2], ensure_ascii=False, separators=(",", ":")),
            }
            for row in self._execute(
                "SELECT row_id, scope_id, structural_kind FROM issue33_benchmark_structural_row "
                "WHERE scope_id = %s AND row_id = ANY(%s) AND visible_actor_ids ? %s "
                "ORDER BY row_id",
                (scope_id, row_ids, actor_id),
            ).fetchall()
        ]

    def _assert_stored_state_matches(self, state: SemanticState) -> None:
        self._assert_native_state_matches(state, self._native_state_rows())

    def _assert_backup_state_matches(self, state: SemanticState) -> None:
        self._assert_native_state_matches(state, self._native_state_rows(backup_id="last"))

    def _assert_native_state_matches(
        self,
        state: SemanticState,
        native: dict[str, list[tuple[Any, ...]]],
    ) -> None:
        payload = semantic_state_payload(state)
        staged = native["stage"]
        if [row[1] for row in staged if row[0] == "candidate"] != payload[
            "staged_candidate_ids"
        ] or [row[1] for row in staged if row[0] == "relation"] != payload["staged_relation_ids"]:
            raise ContractValidationError("benchmark PostgreSQL staged state mismatch")
        nodes = [
            {"node_id": row[0], "scope_id": row[1], "visible_actor_ids": row[2]}
            for row in native["node"]
            if row[4]
        ]
        relations = [
            {
                "relation_id": row[0],
                "scope_id": row[1],
                "source_node_id": row[2],
                "target_node_id": row[3],
                "visible_actor_ids": row[4],
            }
            for row in native["relation"]
            if row[6]
        ]
        lifecycle = [row[0] for row in native["lifecycle"] if row[6]]
        if (
            nodes != payload["nodes"]
            or relations != payload["relations"]
            or lifecycle != payload["lifecycle_event_ids"]
        ):
            raise ContractValidationError("benchmark PostgreSQL persisted graph mismatch")

    def _native_state_rows(
        self, *, backup_id: str | None = None
    ) -> dict[str, list[tuple[Any, ...]]]:
        if backup_id is None:
            return {
                "stage": self._execute(
                    "SELECT record_kind, record_id FROM issue33_benchmark_stage "
                    "ORDER BY record_kind, record_id"
                ).fetchall(),
                "node": self._execute(
                    "SELECT node_id, scope_id, visible_actor_ids, candidate_id, active "
                    "FROM issue33_benchmark_node ORDER BY node_id"
                ).fetchall(),
                "relation": self._execute(
                    "SELECT relation_id, scope_id, source_node_id, target_node_id, "
                    "visible_actor_ids, candidate_relation_id, active "
                    "FROM issue33_benchmark_relation ORDER BY relation_id"
                ).fetchall(),
                "lifecycle": self._execute(
                    "SELECT event_id, scope_id, sequence, event_type, previous_ids, target_ids, active "
                    "FROM issue33_benchmark_lifecycle ORDER BY event_id"
                ).fetchall(),
            }
        if backup_id != "last":
            raise ContractValidationError("benchmark PostgreSQL backup identifier is invalid")
        return {
            "stage": self._execute(
                "SELECT record_kind, record_id FROM issue33_benchmark_backup_stage "
                "WHERE backup_id = 'last' ORDER BY record_kind, record_id"
            ).fetchall(),
            "node": self._execute(
                "SELECT node_id, scope_id, visible_actor_ids, candidate_id, active "
                "FROM issue33_benchmark_backup_node WHERE backup_id = 'last' ORDER BY node_id"
            ).fetchall(),
            "relation": self._execute(
                "SELECT relation_id, scope_id, source_node_id, target_node_id, "
                "visible_actor_ids, candidate_relation_id, active "
                "FROM issue33_benchmark_backup_relation WHERE backup_id = 'last' "
                "ORDER BY relation_id"
            ).fetchall(),
            "lifecycle": self._execute(
                "SELECT event_id, scope_id, sequence, event_type, previous_ids, target_ids, active "
                "FROM issue33_benchmark_backup_lifecycle WHERE backup_id = 'last' ORDER BY event_id"
            ).fetchall(),
        }

    def _current_native_state_matches_backup(self) -> bool:
        return self._native_state_rows() == self._native_state_rows(backup_id="last")

    def _consume_fault(self) -> FaultAction | None:
        action, self._armed_action = self._armed_action, None
        return action

    def _require_package(self) -> StorageEngineBenchmarkPackage:
        if self._package is None:
            raise ContractValidationError("benchmark package is not loaded")
        return self._package

    def _execute(self, statement: str, parameters: tuple[Any, ...] = ()):
        return self._connection.execute(statement, parameters)

    def _executemany(self, statement: str, values: list[tuple[Any, ...]]) -> None:
        if values:
            with self._connection.cursor() as cursor:
                cursor.executemany(statement, values)

    def _drop_schema(self) -> None:
        for table in (
            "issue33_benchmark_backup_lifecycle",
            "issue33_benchmark_backup_relation",
            "issue33_benchmark_backup_node",
            "issue33_benchmark_backup_stage",
            "issue33_benchmark_backup",
            "issue33_benchmark_fault_probe",
            "issue33_benchmark_lifecycle",
            "issue33_benchmark_structural_row",
            "issue33_benchmark_relation",
            "issue33_benchmark_node",
            "issue33_benchmark_stage",
            "issue33_benchmark_fixture",
            "issue33_benchmark_state",
            "issue33_benchmark_meta",
        ):
            self._execute(f"DROP TABLE IF EXISTS {table}")

    def _create_schema(self) -> None:
        self._execute(
            "CREATE TABLE issue33_benchmark_meta (meta_key text primary key, meta_value jsonb not null)"
        )
        self._execute(
            "CREATE TABLE issue33_benchmark_state "
            "(state_id text primary key, fixture_hash text not null, state_json jsonb not null)"
        )
        self._execute(
            "CREATE TABLE issue33_benchmark_fixture "
            "(record_kind text not null, record_id text not null, payload jsonb not null, "
            "PRIMARY KEY (record_kind, record_id))"
        )
        self._execute(
            "CREATE TABLE issue33_benchmark_stage "
            "(record_kind text not null, record_id text not null, "
            "PRIMARY KEY (record_kind, record_id))"
        )
        self._execute(
            "CREATE TABLE issue33_benchmark_node "
            "(node_id text primary key, scope_id text not null, visible_actor_ids jsonb not null, "
            "candidate_id text not null, active boolean not null)"
        )
        self._execute(
            "CREATE TABLE issue33_benchmark_relation "
            "(relation_id text primary key, scope_id text not null, source_node_id text not null, "
            "target_node_id text not null, visible_actor_ids jsonb not null, "
            "candidate_relation_id text not null, active boolean not null)"
        )
        self._execute(
            "CREATE TABLE issue33_benchmark_structural_row "
            "(row_id text primary key, scope_id text not null, structural_kind text not null, "
            "visible_actor_ids jsonb not null, observation_id text not null, candidate_id text not null)"
        )
        self._execute(
            "CREATE TABLE issue33_benchmark_lifecycle "
            "(event_id text primary key, scope_id text not null, sequence integer not null, "
            "event_type text not null, previous_ids jsonb not null, target_ids jsonb not null, "
            "active boolean not null)"
        )
        self._execute(
            "CREATE TABLE issue33_benchmark_fault_probe "
            "(fault_id text primary key, action_kind text not null, injection_point text not null, "
            "target_kind text not null, target_id text not null, field_name text not null, "
            "value_hash text not null)"
        )
        self._execute(
            "CREATE TABLE issue33_benchmark_backup "
            "(backup_id text primary key, fixture_hash text not null, state_json jsonb not null)"
        )
        self._execute(
            "CREATE TABLE issue33_benchmark_backup_stage "
            "(backup_id text not null, record_kind text not null, record_id text not null, "
            "PRIMARY KEY (backup_id, record_kind, record_id))"
        )
        self._execute(
            "CREATE TABLE issue33_benchmark_backup_node "
            "(backup_id text not null, node_id text not null, scope_id text not null, "
            "visible_actor_ids jsonb not null, candidate_id text not null, active boolean not null, "
            "PRIMARY KEY (backup_id, node_id))"
        )
        self._execute(
            "CREATE TABLE issue33_benchmark_backup_relation "
            "(backup_id text not null, relation_id text not null, scope_id text not null, "
            "source_node_id text not null, target_node_id text not null, "
            "visible_actor_ids jsonb not null, candidate_relation_id text not null, "
            "active boolean not null, PRIMARY KEY (backup_id, relation_id))"
        )
        self._execute(
            "CREATE TABLE issue33_benchmark_backup_lifecycle "
            "(backup_id text not null, event_id text not null, scope_id text not null, "
            "sequence integer not null, event_type text not null, previous_ids jsonb not null, "
            "target_ids jsonb not null, active boolean not null, "
            "PRIMARY KEY (backup_id, event_id))"
        )
        self._execute(
            "CREATE INDEX issue33_benchmark_node_scope ON issue33_benchmark_node (scope_id, active)"
        )
        self._execute(
            "CREATE INDEX issue33_benchmark_relation_endpoint "
            "ON issue33_benchmark_relation (source_node_id, target_node_id, active)"
        )
        self._execute(
            "CREATE INDEX issue33_benchmark_lifecycle_prior "
            "ON issue33_benchmark_lifecycle (scope_id, sequence, active)"
        )
        self._execute(
            "CREATE INDEX issue33_benchmark_structured_scope "
            "ON issue33_benchmark_structural_row (scope_id, row_id)"
        )


class _InjectedBenchmarkFault(Exception):
    pass


def _fixture_record_id(kind: str, record: dict[str, Any]) -> str:
    for name in (
        "actor_profile_id",
        "batch_id",
        "candidate_id",
        "candidate_relation_id",
        "coverage_contract_id",
        "event_id",
        "node_id",
        "permission_case_id",
        "plan_id",
        "predicate_id",
        "relation_id",
        "row_id",
    ):
        if name in record:
            return record[name]
    return f"{kind}_{canonical_json_sha256(record)[-24:]}"


__all__ = ["PostgreSQLBenchmarkPort"]
