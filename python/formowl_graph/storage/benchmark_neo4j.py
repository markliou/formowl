"""Disposable Neo4j adapter for the Issue #33 storage benchmark.

It is a benchmark-only, source-free store.  It does not expose Neo4j through
FormOwl MCP, add a production service, or establish a second authority store.
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
    semantic_state_payload,
    transition_semantic_state,
    validate_benchmark_package,
)

_FAULT_BRANCHES = {
    ("replace_value", "policy_validation"): "trace",
    ("raise_error", "open_transaction"): "trace",
    ("insert_relation", "relation_scope_validation"): "trace",
    ("assert_value", "authorizer"): "trace",
    ("remove_field", "authorizer"): "trace",
    ("replace_value", "authorizer"): "trace",
    ("duplicate_id", "lifecycle_write"): "lifecycle",
    ("replace_value", "post_validation_pre_write"): "stage",
    ("insert_cycle", "lifecycle_validation"): "trace",
    ("replace_value", "typed_plan_validation"): "trace",
    ("replace_value", "pre_materialization_reauthorization"): "trace",
    ("raise_error", "post_members_pre_revision"): "commit_members",
    ("raise_error", "post_revision_pre_audit"): "commit_revision",
    ("replace_value", "review_validation"): "trace",
    ("replace_value", "ontology_validation"): "trace",
    ("enforce_limit", "fanout_limit"): "trace",
    ("enforce_limit", "path_limit"): "trace",
    ("expire_timer", "timeout"): "trace",
}


class Neo4jBenchmarkPort:
    """One disposable Neo4j database loaded from a sealed fixture package."""

    def __init__(self, driver: Any, *, database: str = "neo4j") -> None:
        self._driver = driver
        self._database = database
        self._package: StorageEngineBenchmarkPackage | None = None
        self._armed_action: FaultAction | None = None
        self._last_fault_execution: FaultExecutionEvidence | None = None
        self._last_restore_execution: RestoreExecutionEvidence | None = None

    @classmethod
    def connect(cls, uri: str, user: str, password: str, *, database: str = "neo4j"):
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:  # pragma: no cover - environment preflight
            raise RuntimeError("benchmark Neo4j driver is unavailable") from exc
        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        return cls(driver, database=database)

    def close(self) -> None:
        self._driver.close()

    def load_sealed_package(self, package: StorageEngineBenchmarkPackage) -> None:
        validate_benchmark_package(package)
        data = fixture_data(package.fixture)
        with self._driver.session(database=self._database) as session:
            session.execute_write(self._ensure_schema)
            session.execute_write(lambda tx: self._load(tx, package, data))
        self._package = package
        self._armed_action = None
        self._last_fault_execution = None
        self._last_restore_execution = None

    def arm_fault(self, action: FaultAction) -> None:
        if self._armed_action is not None:
            raise ContractValidationError("benchmark fault already armed")
        fault_for_action(self._require_package(), action)
        self._armed_action = action

    def inspect_semantic_state(self) -> SemanticState:
        with self._driver.session(database=self._database) as session:
            record = session.run(
                "MATCH (state:Issue33BenchmarkState {state_id: 'current'}) "
                "RETURN state.fixture_hash AS fixture_hash, state.state_json AS state_json"
            ).single()
            if record is None:
                raise ContractValidationError("benchmark semantic state is unavailable")
            state = SemanticState(record["fixture_hash"], record["state_json"])
            self._assert_stored_state_matches(session, state)
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

    def _load(
        self,
        tx: Any,
        package: StorageEngineBenchmarkPackage,
        data: dict[str, Any],
    ) -> None:
        tx.run("MATCH (node) DETACH DELETE node").consume()
        tx.run(
            "CREATE (:Issue33BenchmarkState {state_id: 'current', fixture_hash: $fixture_hash, "
            "state_json: $state_json})",
            fixture_hash=package.fixture.content_hash,
            state_json=initial_semantic_state(package).state_json,
        ).consume()
        tx.run(
            "UNWIND $rows AS row CREATE (:Issue33Fixture {record_kind: row.kind, "
            "record_id: row.record_id, payload_json: row.payload_json})",
            rows=[
                {
                    "kind": kind,
                    "record_id": _fixture_record_id(kind, item),
                    "payload_json": json.dumps(item, sort_keys=True),
                }
                for kind, records in data.items()
                if isinstance(records, list)
                for item in records
            ],
        ).consume()
        tx.run(
            "UNWIND $rows AS row CREATE (:Issue33Node {node_id: row.node_id, "
            "scope_id: row.scope_id, visible_actor_ids: row.visible_to, "
            "candidate_id: row.candidate_id, active: false})",
            rows=data["canonical_nodes"],
        ).consume()
        tx.run(
            "UNWIND $rows AS row CREATE (:Issue33StructuralRow {row_id: row.row_id, "
            "scope_id: row.scope_id, structural_kind: row.structural_kind, "
            "visible_actor_ids: row.visible_to, observation_id: row.observation_id, "
            "candidate_id: row.candidate_id})",
            rows=data["structured_rows"],
        ).consume()
        tx.run(
            "UNWIND $rows AS row CREATE (:Issue33Lifecycle {event_id: row.event_id, "
            "scope_id: row.scope_id, sequence: row.sequence, event_type: row.event_type, "
            "previous_ids: row.previous_ids, target_ids: row.target_ids, active: false})",
            rows=data["lifecycle_events"],
        ).consume()
        tx.run(
            "UNWIND $rows AS row MATCH (source:Issue33Node {node_id: row.source_node_id}) "
            "MATCH (target:Issue33Node {node_id: row.target_node_id}) "
            "CREATE (source)-[:ISSUE33_REL {relation_id: row.relation_id, scope_id: row.scope_id, "
            "visible_actor_ids: row.visible_to, candidate_relation_id: row.candidate_relation_id, "
            "active: false}]->(target)",
            rows=data["canonical_relations"],
        ).consume()

    @staticmethod
    def _ensure_schema(tx: Any) -> None:
        for statement in (
            "CREATE CONSTRAINT issue33_node_id IF NOT EXISTS FOR (node:Issue33Node) "
            "REQUIRE node.node_id IS UNIQUE",
            "CREATE CONSTRAINT issue33_structural_row_id IF NOT EXISTS "
            "FOR (row:Issue33StructuralRow) REQUIRE row.row_id IS UNIQUE",
            "CREATE CONSTRAINT issue33_lifecycle_id IF NOT EXISTS "
            "FOR (event:Issue33Lifecycle) REQUIRE event.event_id IS UNIQUE",
            "CREATE INDEX issue33_node_scope IF NOT EXISTS FOR (node:Issue33Node) ON (node.scope_id)",
            "CREATE INDEX issue33_structural_scope IF NOT EXISTS "
            "FOR (row:Issue33StructuralRow) ON (row.scope_id)",
        ):
            tx.run(statement).consume()

    def _execute_request(self, request: BenchmarkRequest) -> BenchmarkResult:
        package = self._require_package()
        action = self._consume_fault()
        if action is not None:
            fault = fault_for_action(package, action)
            if request != fault.request:
                raise ContractValidationError(
                    "benchmark fault request does not match its sealed action"
                )
            before = self.inspect_semantic_state()
            self._last_fault_execution = None
            try:
                with self._driver.session(database=self._database) as session:
                    session.execute_write(
                        lambda tx: self._exercise_fault_and_abort(tx, package, request, action)
                    )
            except _InjectedBenchmarkFault:
                pass
            else:
                raise ContractValidationError("benchmark fault transaction unexpectedly committed")
            after = self.inspect_semantic_state()
            with self._driver.session(database=self._database) as session:
                self._assert_fault_rolled_back(session, action, before, after)
            if after != before:
                raise ContractValidationError("benchmark fault changed semantic state")
            self._last_fault_execution = seal_fault_execution_evidence(
                action,
                before,
                after,
                native_transaction_started=True,
                native_action_exercised=True,
                transaction_rolled_back=True,
            )
            return fault.expected_result

        if request.operation == "backup_restore":
            return self._backup_restore_request(package, request)

        with self._driver.session(database=self._database) as session:
            result = session.execute_write(lambda tx: self._apply_request(tx, package, request))
            state = self.inspect_semantic_state()
            self._verify_native_reads(session, request, state, result)
            return result

    def _exercise_fault_and_abort(
        self,
        tx: Any,
        package: StorageEngineBenchmarkPackage,
        request: BenchmarkRequest,
        action: FaultAction,
    ) -> None:
        branch = _FAULT_BRANCHES.get((action.action_kind, action.injection_point))
        if branch is None:
            raise ContractValidationError("unsupported benchmark fault action or injection point")
        self._write_fault_trace(tx, action)
        if branch == "stage":
            if request.operation != "stage_candidate_batch":
                raise ContractValidationError("stage fault is not bound to a stage request")
            self._write_stage(tx, request)
            tx.run(
                "MATCH (candidate:Issue33Fixture {record_kind: 'candidate_nodes', "
                "record_id: $target_id}) "
                "SET candidate.fault_action_id = $action_id",
                target_id=action.target_id,
                action_id=action.action_id,
            ).consume()
        elif branch == "lifecycle":
            if request.operation != "reviewed_commit_with_lifecycle":
                raise ContractValidationError("lifecycle fault is not bound to a commit request")
            self._write_commit_members(tx, request)
            tx.run(
                "MATCH (event:Issue33Lifecycle {event_id: $target_id}) "
                "SET event.fault_duplicate_attempt_id = $action_id",
                target_id=action.target_id,
                action_id=action.action_id,
            ).consume()
        elif branch == "commit_members":
            if request.operation != "reviewed_commit_with_lifecycle":
                raise ContractValidationError("member fault is not bound to a commit request")
            self._write_commit_members(tx, request)
        elif branch == "commit_revision":
            if request.operation != "reviewed_commit_with_lifecycle":
                raise ContractValidationError("revision fault is not bound to a commit request")
            self._write_commit_members(tx, request)
            self._write_commit_revision(tx, request, action)
        elif branch != "trace":
            raise ContractValidationError("unsupported benchmark fault branch")
        raise _InjectedBenchmarkFault()

    @staticmethod
    def _write_fault_trace(tx: Any, action: FaultAction) -> None:
        value_hash = fault_action_value_hash(action)
        tx.run(
            "CREATE (:Issue33FaultTrace {action_id: $action_id, action_kind: $action_kind, "
            "injection_point: $injection_point, target_kind: $target_kind, "
            "target_id: $target_id, field_name: $field_name, value_hash: $value_hash})",
            action_id=action.action_id,
            action_kind=action.action_kind,
            injection_point=action.injection_point,
            target_kind=action.target_kind,
            target_id=action.target_id,
            field_name=action.field_name,
            value_hash=value_hash,
        ).consume()
        record = tx.run(
            "MATCH (trace:Issue33FaultTrace {action_id: $action_id}) "
            "RETURN trace.action_kind AS action_kind, "
            "trace.injection_point AS injection_point, trace.target_kind AS target_kind, "
            "trace.target_id AS target_id, trace.field_name AS field_name, "
            "trace.value_hash AS value_hash",
            action_id=action.action_id,
        ).single()
        if record is None or record.data() != {
            "action_kind": action.action_kind,
            "injection_point": action.injection_point,
            "target_kind": action.target_kind,
            "target_id": action.target_id,
            "field_name": action.field_name,
            "value_hash": value_hash,
        }:
            raise ContractValidationError("benchmark Neo4j fault trace mismatch")

    @staticmethod
    def _assert_fault_rolled_back(
        session: Any,
        action: FaultAction,
        before: SemanticState,
        after: SemanticState,
    ) -> None:
        if before != after:
            raise ContractValidationError("benchmark fault rollback state mismatch")
        record = session.run(
            "MATCH (trace:Issue33FaultTrace {action_id: $action_id}) "
            "RETURN count(trace) AS trace_count",
            action_id=action.action_id,
        ).single()
        if record is None or record["trace_count"] != 0:
            raise ContractValidationError("benchmark fault trace survived rollback")
        Neo4jBenchmarkPort._assert_stored_state_matches(session, after)

    def _backup_restore_request(
        self,
        package: StorageEngineBenchmarkPackage,
        request: BenchmarkRequest,
    ) -> BenchmarkResult:
        before = self.inspect_semantic_state()
        destructive = initial_semantic_state(package)
        if destructive == before:
            raise ContractValidationError("benchmark restore requires a nonempty semantic state")
        result = reference_execute_request(package, request, before)
        self._last_restore_execution = None
        with self._driver.session(database=self._database) as session:
            session.execute_write(
                lambda tx: self._backup_destructively_mutate_and_restore(tx, before, destructive)
            )
            restored = self.inspect_semantic_state()
            self._verify_native_reads(session, request, restored, result)
        if restored != before:
            raise ContractValidationError("benchmark restore did not restore semantic state")
        self._last_restore_execution = seal_restore_execution_evidence(
            before,
            destructive,
            restored,
            native_backup_created=True,
            native_destructive_mutation_observed=True,
            restore_verified=True,
        )
        return result

    def _backup_destructively_mutate_and_restore(
        self,
        tx: Any,
        before: SemanticState,
        destructive: SemanticState,
    ) -> None:
        if self._state_from_tx(tx) != before:
            raise ContractValidationError("benchmark backup state changed before snapshot")
        snapshot = self._native_snapshot(tx)
        snapshot_json = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
        tx.run(
            "MERGE (backup:Issue33BenchmarkBackup {backup_id: 'last'}) "
            "SET backup.fixture_hash = $fixture_hash, backup.state_json = $state_json, "
            "backup.native_snapshot_json = $native_snapshot_json "
            "RETURN backup.native_snapshot_json AS native_snapshot_json",
            fixture_hash=before.fixture_hash,
            state_json=before.state_json,
            native_snapshot_json=snapshot_json,
        ).consume()
        backup = tx.run(
            "MATCH (backup:Issue33BenchmarkBackup {backup_id: 'last'}) "
            "RETURN backup.fixture_hash AS fixture_hash, backup.state_json AS state_json, "
            "backup.native_snapshot_json AS native_snapshot_json"
        ).single()
        if (
            backup is None
            or backup["fixture_hash"] != before.fixture_hash
            or backup["state_json"] != before.state_json
            or backup["native_snapshot_json"] != snapshot_json
        ):
            raise ContractValidationError("benchmark native backup verification failed")

        self._destructively_mutate_native_state(tx, destructive)
        destructive_snapshot = self._native_snapshot(tx)
        self._assert_stored_state_matches(tx, destructive)
        if destructive_snapshot == snapshot:
            raise ContractValidationError("benchmark destructive mutation was not observed")

        self._restore_native_snapshot(tx, snapshot)
        if self._native_snapshot(tx) != snapshot:
            raise ContractValidationError("benchmark native restore snapshot mismatch")
        if self._state_from_tx(tx) != before:
            raise ContractValidationError("benchmark native restore state mismatch")
        self._assert_stored_state_matches(tx, before)

    @staticmethod
    def _native_snapshot(tx: Any) -> dict[str, Any]:
        state = tx.run(
            "MATCH (state:Issue33BenchmarkState {state_id: 'current'}) "
            "RETURN state.fixture_hash AS fixture_hash, state.state_json AS state_json"
        ).single()
        if state is None:
            raise ContractValidationError("benchmark semantic state is unavailable")
        return {
            "state": {
                "fixture_hash": state["fixture_hash"],
                "state_json": state["state_json"],
            },
            "stage": [
                record.data()
                for record in tx.run(
                    "MATCH (stage:Issue33Stage) RETURN stage.record_kind AS record_kind, "
                    "stage.record_id AS record_id ORDER BY record_kind, record_id"
                )
            ],
            "nodes": [
                record.data()
                for record in tx.run(
                    "MATCH (node:Issue33Node) RETURN node.node_id AS node_id, "
                    "node.active AS active ORDER BY node_id"
                )
            ],
            "relations": [
                record.data()
                for record in tx.run(
                    "MATCH ()-[relation:ISSUE33_REL]->() "
                    "RETURN relation.relation_id AS relation_id, relation.active AS active "
                    "ORDER BY relation_id"
                )
            ],
            "lifecycle": [
                record.data()
                for record in tx.run(
                    "MATCH (event:Issue33Lifecycle) RETURN event.event_id AS event_id, "
                    "event.active AS active ORDER BY event_id"
                )
            ],
        }

    @staticmethod
    def _destructively_mutate_native_state(tx: Any, destructive: SemanticState) -> None:
        tx.run("MATCH (stage:Issue33Stage) DETACH DELETE stage").consume()
        tx.run("MATCH (node:Issue33Node) SET node.active = false").consume()
        tx.run("MATCH ()-[relation:ISSUE33_REL]->() SET relation.active = false").consume()
        tx.run("MATCH (event:Issue33Lifecycle) SET event.active = false").consume()
        tx.run(
            "MATCH (state:Issue33BenchmarkState {state_id: 'current'}) "
            "SET state.fixture_hash = $fixture_hash, state.state_json = $state_json",
            fixture_hash=destructive.fixture_hash,
            state_json=destructive.state_json,
        ).consume()

    @staticmethod
    def _restore_native_snapshot(tx: Any, snapshot: dict[str, Any]) -> None:
        tx.run("MATCH (stage:Issue33Stage) DETACH DELETE stage").consume()
        tx.run(
            "UNWIND $rows AS row MERGE (:Issue33Stage {record_kind: row.record_kind, "
            "record_id: row.record_id})",
            rows=snapshot["stage"],
        ).consume()
        tx.run("MATCH (node:Issue33Node) SET node.active = false").consume()
        tx.run(
            "UNWIND $rows AS row MATCH (node:Issue33Node {node_id: row.node_id}) "
            "SET node.active = row.active",
            rows=snapshot["nodes"],
        ).consume()
        tx.run("MATCH ()-[relation:ISSUE33_REL]->() SET relation.active = false").consume()
        tx.run(
            "UNWIND $rows AS row "
            "MATCH ()-[relation:ISSUE33_REL {relation_id: row.relation_id}]->() "
            "SET relation.active = row.active",
            rows=snapshot["relations"],
        ).consume()
        tx.run("MATCH (event:Issue33Lifecycle) SET event.active = false").consume()
        tx.run(
            "UNWIND $rows AS row MATCH (event:Issue33Lifecycle {event_id: row.event_id}) "
            "SET event.active = row.active",
            rows=snapshot["lifecycle"],
        ).consume()
        tx.run(
            "MATCH (state:Issue33BenchmarkState {state_id: 'current'}) "
            "SET state.fixture_hash = $fixture_hash, state.state_json = $state_json",
            fixture_hash=snapshot["state"]["fixture_hash"],
            state_json=snapshot["state"]["state_json"],
        ).consume()

    def _apply_request(
        self,
        tx: Any,
        package: StorageEngineBenchmarkPackage,
        request: BenchmarkRequest,
    ) -> BenchmarkResult:
        state = self._state_from_tx(tx)
        result = reference_execute_request(package, request, state)
        if request.operation == "stage_candidate_batch" and result.status == "success":
            self._write_stage(tx, request)
        elif request.operation == "reviewed_commit_with_lifecycle" and result.status == "success":
            self._write_commit_members(tx, request)
        next_state = transition_semantic_state(package, request, state)
        tx.run(
            "MATCH (state:Issue33BenchmarkState {state_id: 'current'}) "
            "SET state.fixture_hash = $fixture_hash, state.state_json = $state_json",
            fixture_hash=next_state.fixture_hash,
            state_json=next_state.state_json,
        ).consume()
        return result

    @staticmethod
    def _write_stage(tx: Any, request: BenchmarkRequest) -> None:
        batch = request_input_payload(request, "candidate_batch_r1")
        tx.run(
            "UNWIND $rows AS row MERGE (:Issue33Stage {record_kind: row.record_kind, "
            "record_id: row.record_id})",
            rows=[
                {"record_kind": "candidate", "record_id": value} for value in batch["candidate_ids"]
            ]
            + [{"record_kind": "relation", "record_id": value} for value in batch["relation_ids"]],
        ).consume()

    @staticmethod
    def _write_commit_members(tx: Any, request: BenchmarkRequest) -> None:
        plan = request_input_payload(request, "reviewed_commit_plan_r1")
        tx.run(
            "MATCH (node:Issue33Node) WHERE node.node_id IN $node_ids SET node.active = true",
            node_ids=plan["node_ids"],
        ).consume()
        tx.run(
            "MATCH ()-[relation:ISSUE33_REL]->() WHERE relation.relation_id IN $relation_ids "
            "SET relation.active = true",
            relation_ids=plan["relation_ids"],
        ).consume()
        tx.run(
            "MATCH (event:Issue33Lifecycle) WHERE event.event_id IN $event_ids "
            "SET event.active = true",
            event_ids=plan["lifecycle_event_ids"],
        ).consume()

    @staticmethod
    def _write_commit_revision(tx: Any, request: BenchmarkRequest, action: FaultAction) -> None:
        plan = request_input_payload(request, "reviewed_commit_plan_r1")
        tx.run(
            "MERGE (revision:Issue33FaultRevision {revision_id: $revision_id}) "
            "SET revision.fault_action_id = $action_id",
            revision_id=plan["revision_id"],
            action_id=action.action_id,
        ).consume()

    def _state_from_tx(self, tx: Any) -> SemanticState:
        record = tx.run(
            "MATCH (state:Issue33BenchmarkState {state_id: 'current'}) "
            "RETURN state.fixture_hash AS fixture_hash, state.state_json AS state_json"
        ).single()
        if record is None:
            raise ContractValidationError("benchmark semantic state is unavailable")
        return SemanticState(record["fixture_hash"], record["state_json"])

    def _verify_native_reads(
        self, session: Any, request: BenchmarkRequest, state: SemanticState, result: BenchmarkResult
    ) -> None:
        if result.status != "success":
            return
        authorization = input_record_payload(request.authorization)
        actor = authorization["actor"]
        payload = result_payload(result)
        if request.operation in {"effective_view", "reviewed_commit_with_lifecycle"}:
            if (
                self._visible_ids(session, actor["actor_profile_id"], actor["scope_id"])
                != payload["item_ids"]
            ):
                raise ContractValidationError("benchmark Neo4j effective view mismatch")
        elif request.operation == "bounded_traverse":
            if (
                self._traverse(session, actor["actor_profile_id"], actor["scope_id"], request)
                != payload["paths"]
            ):
                raise ContractValidationError("benchmark Neo4j traversal mismatch")
        elif request.operation == "resolve_lifecycle":
            if self._lifecycle(session) != payload["lifecycle"]:
                raise ContractValidationError("benchmark Neo4j lifecycle mismatch")
        elif request.operation == "structured_set_handoff":
            coverage = request_input_payload(request, "coverage_contract_r1")
            if (
                self._structural_rows(
                    session,
                    actor["actor_profile_id"],
                    coverage["scope_id"],
                    coverage["covered_row_ids"],
                )
                != payload["structural_rows"]
            ):
                raise ContractValidationError("benchmark Neo4j structured set mismatch")
        if state != self.inspect_semantic_state():
            raise ContractValidationError("benchmark Neo4j state changed during read")

    @staticmethod
    def _visible_ids(session: Any, actor_id: str, scope_id: str) -> list[str]:
        nodes = [
            record["node_id"]
            for record in session.run(
                "MATCH (node:Issue33Node {active: true, scope_id: $scope_id}) "
                "WHERE $actor_id IN node.visible_actor_ids RETURN node.node_id AS node_id "
                "ORDER BY node_id",
                actor_id=actor_id,
                scope_id=scope_id,
            )
        ]
        relations = [
            record["relation_id"]
            for record in session.run(
                "MATCH (source:Issue33Node {active: true})-[relation:ISSUE33_REL "
                "{active: true, scope_id: $scope_id}]->(target:Issue33Node {active: true}) "
                "WHERE $actor_id IN source.visible_actor_ids AND $actor_id IN target.visible_actor_ids "
                "AND $actor_id IN relation.visible_actor_ids RETURN relation.relation_id AS relation_id "
                "ORDER BY relation_id",
                actor_id=actor_id,
                scope_id=scope_id,
            )
        ]
        return sorted(nodes + relations)

    @staticmethod
    def _traverse(
        session: Any, actor_id: str, scope_id: str, request: BenchmarkRequest
    ) -> list[dict[str, list[str]]]:
        traversal = request_input_payload(request, "bounded_traversal_r1")
        start_id = traversal["start_node_id"]
        visible_nodes = {
            record["node_id"]
            for record in session.run(
                "MATCH (node:Issue33Node {active: true, scope_id: $scope_id}) "
                "WHERE $actor_id IN node.visible_actor_ids "
                "RETURN node.node_id AS node_id ORDER BY node_id",
                actor_id=actor_id,
                scope_id=scope_id,
            )
        }
        if start_id not in visible_nodes:
            return []
        outgoing: dict[str, list[dict[str, str]]] = {}
        for record in session.run(
            "MATCH (source:Issue33Node {active: true, scope_id: $scope_id})"
            "-[relation:ISSUE33_REL {active: true, scope_id: $scope_id}]->"
            "(target:Issue33Node {active: true, scope_id: $scope_id}) "
            "WHERE $actor_id IN source.visible_actor_ids "
            "AND $actor_id IN relation.visible_actor_ids "
            "AND $actor_id IN target.visible_actor_ids "
            "RETURN source.node_id AS source_node_id, "
            "target.node_id AS target_node_id, relation.relation_id AS relation_id "
            "ORDER BY source_node_id, target_node_id, relation_id",
            actor_id=actor_id,
            scope_id=scope_id,
        ):
            outgoing.setdefault(record["source_node_id"], []).append(
                {
                    "relation_id": record["relation_id"],
                    "target_node_id": record["target_node_id"],
                }
            )
        frontier = [{"node_ids": [start_id], "relation_ids": []}]
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

    @staticmethod
    def _lifecycle(session: Any) -> dict[str, Any]:
        events = [
            record.data()
            for record in session.run(
                "MATCH (event:Issue33Lifecycle {active: true}) "
                "RETURN event.event_id AS event_id, event.event_type AS event_type, "
                "event.previous_ids AS previous_ids, event.target_ids AS target_ids "
                "ORDER BY event.sequence, event.event_id"
            )
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

    @staticmethod
    def _structural_rows(
        session: Any, actor_id: str, scope_id: str, row_ids: list[str]
    ) -> list[dict[str, str]]:
        return [
            {
                "row_id": record["row_id"],
                "scope_id": record["scope_id"],
                "field_name": "structural_kind",
                "field_value_json": json.dumps(
                    record["structural_kind"], ensure_ascii=False, separators=(",", ":")
                ),
            }
            for record in session.run(
                "MATCH (row:Issue33StructuralRow {scope_id: $scope_id}) "
                "WHERE row.row_id IN $row_ids AND $actor_id IN row.visible_actor_ids "
                "RETURN row.row_id AS row_id, row.scope_id AS scope_id, "
                "row.structural_kind AS structural_kind ORDER BY row_id",
                actor_id=actor_id,
                scope_id=scope_id,
                row_ids=row_ids,
            )
        ]

    @staticmethod
    def _assert_stored_state_matches(session: Any, state: SemanticState) -> None:
        payload = semantic_state_payload(state)
        staged = [
            record.data()
            for record in session.run(
                "MATCH (stage:Issue33Stage) RETURN stage.record_kind AS record_kind, "
                "stage.record_id AS record_id ORDER BY record_kind, record_id"
            )
        ]
        nodes = [
            record.data()
            for record in session.run(
                "MATCH (node:Issue33Node {active: true}) RETURN node.node_id AS node_id, "
                "node.scope_id AS scope_id, node.visible_actor_ids AS visible_actor_ids ORDER BY node_id"
            )
        ]
        relations = [
            record.data()
            for record in session.run(
                "MATCH ()-[relation:ISSUE33_REL {active: true}]->() "
                "RETURN relation.relation_id AS relation_id, relation.scope_id AS scope_id, "
                "startNode(relation).node_id AS source_node_id, endNode(relation).node_id AS target_node_id, "
                "relation.visible_actor_ids AS visible_actor_ids ORDER BY relation_id"
            )
        ]
        lifecycle = [
            record["event_id"]
            for record in session.run(
                "MATCH (event:Issue33Lifecycle {active: true}) RETURN event.event_id AS event_id "
                "ORDER BY event_id"
            )
        ]
        staged_candidates = [
            item["record_id"] for item in staged if item["record_kind"] == "candidate"
        ]
        staged_relations = [
            item["record_id"] for item in staged if item["record_kind"] == "relation"
        ]
        if staged_candidates != payload["staged_candidate_ids"]:
            raise ContractValidationError("benchmark Neo4j staged candidate mismatch")
        if staged_relations != payload["staged_relation_ids"]:
            raise ContractValidationError("benchmark Neo4j staged relation mismatch")
        if nodes != payload["nodes"]:
            raise ContractValidationError("benchmark Neo4j active node mismatch")
        if relations != payload["relations"]:
            raise ContractValidationError("benchmark Neo4j active relation mismatch")
        if lifecycle != payload["lifecycle_event_ids"]:
            raise ContractValidationError("benchmark Neo4j lifecycle mismatch")

    def _consume_fault(self) -> FaultAction | None:
        action, self._armed_action = self._armed_action, None
        return action

    def _require_package(self) -> StorageEngineBenchmarkPackage:
        if self._package is None:
            raise ContractValidationError("benchmark package is not loaded")
        return self._package


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


__all__ = ["Neo4jBenchmarkPort"]
