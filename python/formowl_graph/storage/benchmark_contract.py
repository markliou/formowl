"""Storage-neutral, source-free benchmark contract for FormOwl issue #33.

No adapter, database, runner, migration, MCP export, source reader, or verdict
selection belongs in this module.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, replace
from functools import lru_cache
import hashlib
import json
import re
from types import UnionType
from typing import (
    Any,
    Mapping,
    Protocol,
    Sequence,
    TypeVar,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from formowl_contract import ContractValidationError, assert_no_public_raw_references

SCHEMA = "storage_engine_benchmark_contract_r5"
GENERATOR = "issue33_source_free_fixture_r5"
INPUT_KIND = "synthetic_governed_fixture_only"
AUTH_TIME = "2026-08-10T00:00:00Z"
CURRENT_TOKENIZER = "ascii_identifier_regex_v1"
TARGET_TOKENIZER = "jieba_sentencepiece_frozen_profile_candidate_admission_v1"

_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT = re.compile(r"^[0-9a-f]{40}$")
_OPERATIONS = (
    "backup_restore",
    "bounded_traverse",
    "effective_view",
    "resolve_lifecycle",
    "reviewed_commit_with_lifecycle",
    "stage_candidate_batch",
    "structured_set_handoff",
)
_POLICY_IDS = (
    "extraction_policy_r1",
    "granularity_policy_r1",
    "lifecycle_policy_r1",
    "relation_resolution_policy_r1",
)
_PERMISSION_STATES = ("matching", "missing", "mutable", "nonmatching", "null", "wrong_type")
_INDEXES = (
    ("canonical_id", "canonical_record", ("opaque_id",), True),
    ("lifecycle_prior_id", "lifecycle_event", ("previous_id",), False),
    ("relation_endpoint", "canonical_relation", ("source_node_id", "target_node_id"), False),
    ("scope", "governed_record", ("scope_id",), False),
    ("structured_handoff", "structural_row", ("scope_id", "structural_kind", "row_id"), False),
)
# fmt: off
_FAULT_ROWS = """
bad_policy_pin|policy_validation|review_commit|rejected|contract_rejected|0|replace_value|policy_pin|policy_manifest|policy_id|"bad_policy_r0"
connection_loss_open_transaction|open_transaction|review_commit|rejected|transaction_failed|1|raise_error|transaction|commit_plan_alpha|driver_event|"connection_lost"
cross_scope_relation|relation_scope_validation|candidate_stage_cross_scope_reject|rejected|contract_rejected|0|insert_relation|candidate_batch|batch_rejected_cross_scope|relation|{"source_candidate_id":"candidate_0000","target_candidate_id":"candidate_0001"}
denied_actor|authorizer|effective_view_deny|denied|access_denied|0|assert_value|actor_grant|actor_denied|decision|"deny"
duplicate_lifecycle_id|lifecycle_write|review_commit|rejected|contract_rejected|1|duplicate_id|lifecycle_event|lifecycle_000|event_id|"lifecycle_000"
expired_grant|authorizer|effective_view_deny|denied|access_denied|0|replace_value|actor_grant|actor_denied|grant_state|"expired"
invalid_candidate_after_validation|post_validation_pre_write|candidate_stage_write|rejected|contract_rejected|1|replace_value|candidate|candidate_0000|schema_version|"invalid_r0"
lifecycle_cycle|lifecycle_validation|review_commit|rejected|contract_rejected|1|insert_cycle|lifecycle_chain|chain_split_merge|target_ids|["node_0000"]
malformed_typed_plan|typed_plan_validation|structured_set_handoff|rejected|contract_rejected|0|replace_value|typed_predicate|typed_predicate_r1|schema_version|"unsupported_r0"
permission_matching|authorizer|property_permission_matching|success|-|0|assert_value|permission_property|permission_matching|value|"scope_alpha"
permission_missing|authorizer|property_permission_missing|denied|access_denied|0|remove_field|permission_property|permission_missing|value|null
permission_mutable|pre_materialization_reauthorization|property_permission_mutable|denied|access_denied|0|replace_value|permission_property|permission_mutable|value|"nonmatching_after_plan"
permission_nonmatching|authorizer|property_permission_nonmatching|denied|access_denied|0|replace_value|permission_property|permission_nonmatching|value|"scope_beta"
permission_null|authorizer|property_permission_null|denied|access_denied|0|replace_value|permission_property|permission_null|value|null
permission_wrong_type|authorizer|property_permission_wrong_type|denied|access_denied|0|replace_value|permission_property|permission_wrong_type|value|{"unexpected":"mapping"}
post_members_pre_revision|post_members_pre_revision|review_commit|rejected|transaction_failed|1|raise_error|transaction|commit_plan_alpha|driver_event|"injected_failure"
post_revision_pre_audit|post_revision_pre_audit|review_commit|rejected|transaction_failed|1|raise_error|transaction|commit_plan_alpha|driver_event|"injected_failure"
rejected_review|review_validation|review_commit|rejected|contract_rejected|0|replace_value|review_decision|review_decision_r1|decision|"rejected"
revoked_grant|authorizer|effective_view_deny|denied|access_denied|0|replace_value|actor_grant|actor_denied|grant_state|"revoked"
stale_ontology|ontology_validation|review_commit|rejected|contract_rejected|0|replace_value|ontology_pin|ontology_revision_r1|revision_id|"stale_ontology_revision_r0"
traversal_fanout_limit|fanout_limit|bounded_traversal_allow|partial|bounded_limit|0|enforce_limit|traversal|node_0000|per_frontier_fanout|4
traversal_path_limit|path_limit|bounded_traversal_allow|partial|bounded_limit|0|enforce_limit|traversal|node_0000|maximum_returned_paths|32
traversal_timeout|timeout|bounded_traversal_allow|timeout|bounded_timeout|0|expire_timer|traversal|node_0000|timeout_milliseconds|1000
wrong_scope_grant|authorizer|effective_view_deny|denied|access_denied|0|replace_value|actor_grant|actor_denied|scope_id|"scope_beta"
""".strip()
# fmt: on


class Record:
    """One strict codec shared by every sealed record."""

    def to_dict(self) -> dict[str, Any]:
        payload = _plain(self)
        if not isinstance(payload, dict):
            _invalid()
        _safe_values(payload, type(self).__name__)
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]):
        record = _decode(cls, value)
        _validate(record)
        return record


@dataclass(frozen=True)
class MethodologyAuthorityState(Record):
    authority_state_fingerprint: str
    execution_fingerprint: str
    status: str
    methodology_ready: bool
    current_tokenizer_id: str
    target_tokenizer_id: str
    require_ready_exit_code: int


@dataclass(frozen=True)
class SealedInputRecord(Record):
    record_id: str
    record_kind: str
    payload_json: str
    record_hash: str


@dataclass(frozen=True)
class DependencyPin(Record):
    package_name: str
    version: str
    artifact_hash: str


@dataclass(frozen=True)
class DependencyLock(Record):
    lock_id: str
    dependencies: tuple[DependencyPin, ...]
    lock_hash: str


@dataclass(frozen=True)
class EngineProfile(Record):
    profile_id: str
    engine_id: str
    product_name: str
    product_version: str
    edition: str
    image_reference: str
    image_digest: str
    driver_package: str
    driver_version: str
    driver_artifact_hash: str
    deployment_mode: str
    license_declaration: str
    settings_profile: SealedInputRecord
    index_profile: SealedInputRecord
    profile_hash: str


@dataclass(frozen=True)
class EvaluatorProfile(Record):
    evaluator_id: str
    module_id: str
    entrypoint_id: str
    source_revision: str
    source_hash: str
    adapter_contract_hash: str
    profile_hash: str


@dataclass(frozen=True)
class ResourceProfile(Record):
    profile_id: str
    cpu_limit: int
    memory_limit_bytes: int
    memory_swap_limit_bytes: int
    pid_limit: int
    gpu_allowed: bool
    workers: int
    storage_kind: str
    network_kind: str
    input_mount_mode: str
    profile_hash: str


@dataclass(frozen=True)
class FixturePayload(Record):
    profile: str
    seed: int
    content_json: str
    content_hash: str


@dataclass(frozen=True)
class SemanticState(Record):
    fixture_hash: str
    state_json: str


@dataclass(frozen=True)
class BenchmarkRequest(Record):
    schema_version: str
    case_id: str
    operation: str
    authorization: SealedInputRecord
    inputs: tuple[SealedInputRecord, ...]
    fixture_hash: str
    request_hash: str


StorageEngineBenchmarkRequest = BenchmarkRequest


@dataclass(frozen=True)
class BenchmarkResult(Record):
    schema_version: str
    case_id: str
    operation: str
    status: str
    payload_json: str
    materialization_calls: int
    reason_code: str
    authority_state_fingerprint: str
    execution_fingerprint: str
    methodology_ready: bool
    result_hash: str


StorageEngineBenchmarkResult = BenchmarkResult


@dataclass(frozen=True)
class StructuredSetResult(Record):
    payload_json: str
    result_hash: str


@dataclass(frozen=True)
class SealedCase(Record):
    case_id: str
    request: BenchmarkRequest
    expected_result: BenchmarkResult
    expected_pre_state: SemanticState
    expected_post_state: SemanticState
    expected_structured_set: StructuredSetResult | None
    case_hash: str


@dataclass(frozen=True)
class FaultAction(Record):
    action_id: str
    action_kind: str
    injection_point: str
    target_kind: str
    target_id: str
    field_name: str
    value_json: str
    consume_once: bool


@dataclass(frozen=True)
class FaultRecord(Record):
    fault_id: str
    baseline_case_ids: tuple[str, ...]
    request: BenchmarkRequest
    action: FaultAction
    expected_result: BenchmarkResult
    expected_pre_state: SemanticState
    expected_post_state: SemanticState
    forbidden_success_audit_ids: tuple[str, ...]
    retry_case_id: str
    fault_hash: str


@dataclass(frozen=True)
class NamedHash(Record):
    name: str
    value: str


@dataclass(frozen=True)
class StorageEngineBenchmarkPackage(Record):
    schema_version: str
    generator_revision: str
    fixture_profile: str
    seed: int
    input_kind: str
    raw_pst_read_count: int
    pst_parser_invocation_count: int
    new_extractor_run_count: int
    authorization_time: str
    authority_state: MethodologyAuthorityState
    engine_profiles: tuple[EngineProfile, ...]
    evaluator_profile: EvaluatorProfile
    dependency_lock: DependencyLock
    resource_profile: ResourceProfile
    fixture: FixturePayload
    cases: tuple[SealedCase, ...]
    faults: tuple[FaultRecord, ...]
    manifest_hashes: tuple[NamedHash, ...]
    package_hash: str


@dataclass(frozen=True)
class BenchmarkComparison(Record):
    equivalent: bool
    mismatch_fields: tuple[str, ...]
    expected_result_hash: str
    actual_result_hash: str


@dataclass(frozen=True)
class CaseVerification(Record):
    case_id: str
    result_hash: str
    pre_state_digest: str
    post_state_digest: str
    structured_set_result_hash: str
    operation_evidence_hash: str
    verification_hash: str


@dataclass(frozen=True)
class FaultVerification(Record):
    fault_id: str
    result_hash: str
    pre_state_digest: str
    post_state_digest: str
    retry_state_digest: str
    retry_verified: bool
    execution_evidence_hash: str
    verification_hash: str


@dataclass(frozen=True)
class FaultExecutionEvidence(Record):
    action_id: str
    action_kind: str
    injection_point: str
    target_kind: str
    target_id: str
    field_name: str
    value_hash: str
    native_transaction_started: bool
    native_action_exercised: bool
    transaction_rolled_back: bool
    pre_state_digest: str
    post_state_digest: str
    evidence_hash: str


@dataclass(frozen=True)
class RestoreExecutionEvidence(Record):
    backup_state_digest: str
    destructive_state_digest: str
    restored_state_digest: str
    native_backup_created: bool
    native_destructive_mutation_observed: bool
    restore_verified: bool
    evidence_hash: str


class GovernedGraphBenchmarkStore(Protocol):
    """The seven storage operations fixed by §11.2."""

    def stage_candidate_batch(self, request: BenchmarkRequest) -> BenchmarkResult: ...

    def reviewed_commit_with_lifecycle(self, request: BenchmarkRequest) -> BenchmarkResult: ...

    def effective_view(self, request: BenchmarkRequest) -> BenchmarkResult: ...

    def bounded_traverse(self, request: BenchmarkRequest) -> BenchmarkResult: ...

    def resolve_lifecycle(self, request: BenchmarkRequest) -> BenchmarkResult: ...

    def structured_set_handoff(self, request: BenchmarkRequest) -> BenchmarkResult: ...

    def backup_restore(self, request: BenchmarkRequest) -> BenchmarkResult: ...


class GovernedGraphBenchmarkControl(Protocol):
    """Storage-neutral load, fault-arm, and independent inspection controls."""

    def load_sealed_package(self, package: StorageEngineBenchmarkPackage) -> None: ...

    def arm_fault(self, action: FaultAction) -> None: ...

    def inspect_semantic_state(self) -> SemanticState: ...

    def inspect_last_fault_execution(self) -> FaultExecutionEvidence | None: ...

    def inspect_last_restore_execution(self) -> RestoreExecutionEvidence | None: ...


class GovernedGraphBenchmarkExecutionPort(
    GovernedGraphBenchmarkStore, GovernedGraphBenchmarkControl, Protocol
):
    pass


class SealedPackageGate:
    def __init__(self, package: StorageEngineBenchmarkPackage) -> None:
        validate_benchmark_package(package)
        self._package_hash = package.package_hash
        self._runs: set[str] = set()

    def begin_engine_load(self, run_id: str, package: StorageEngineBenchmarkPackage) -> None:
        _require_id(run_id)
        validate_benchmark_package(package)
        if package.package_hash != self._package_hash or run_id in self._runs:
            _invalid()
        self._runs.add(run_id)

    @property
    def package_hash(self) -> str:
        return self._package_hash


def canonical_utf8_json(value: Any) -> bytes:
    payload = _plain(value)
    _safe_values(payload, "benchmark JSON")
    try:
        text = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        _invalid()
    return text.encode("utf-8")


def canonical_json_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_utf8_json(value)).hexdigest()


def seal_input_record(record_id: str, record_kind: str, payload: Any) -> SealedInputRecord:
    record = SealedInputRecord(record_id, record_kind, _json_text(payload), "")
    record = replace(record, record_hash=_hash_without(record, "record_hash"))
    _validate_input_record(record)
    return record


def input_record_payload(record: SealedInputRecord) -> dict[str, Any]:
    _validate_input_record(record)
    return _json_object(record.payload_json)


def request_input_payload(request: BenchmarkRequest, record_kind: str) -> dict[str, Any]:
    """Return one validated request input selected by sealed record kind."""

    _validate_request(request)
    return input_record_payload(_input(request, record_kind))


def semantic_state_payload(state: SemanticState) -> dict[str, Any]:
    _validate_state_shape(state)
    return _json_object(state.state_json)


def result_payload(result: BenchmarkResult) -> dict[str, Any]:
    _validate_result(result)
    return _json_object(result.payload_json)


def structured_set_payload(result: StructuredSetResult) -> dict[str, Any]:
    _validate_structured_result(result)
    return _json_object(result.payload_json)


def seal_semantic_state(fixture_hash: str, payload: Mapping[str, Any]) -> SemanticState:
    state = SemanticState(fixture_hash, _json_text(payload))
    _validate_state_shape(state)
    return state


def semantic_state_digest(state: SemanticState) -> str:
    _validate_state_shape(state)
    return canonical_json_sha256(state)


def benchmark_result_digest(result: BenchmarkResult) -> str:
    _validate_result(result)
    return result.result_hash


def engine_setting(setting_name: str, value: Any) -> dict[str, Any]:
    _require_id(setting_name)
    return {"setting_name": setting_name, "value_json": _json_text(value)}


def logical_index_declarations() -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "logical_index_id": index_id,
            "entity_kind": entity_kind,
            "fields": list(index_fields),
            "unique": unique,
        }
        for index_id, entity_kind, index_fields, unique in _INDEXES
    )


def engine_profile_settings(profile: EngineProfile) -> tuple[dict[str, Any], ...]:
    payload = input_record_payload(profile.settings_profile)
    return tuple(payload["settings"])


def engine_profile_indexes(profile: EngineProfile) -> tuple[dict[str, Any], ...]:
    payload = input_record_payload(profile.index_profile)
    return tuple(payload["indexes"])


def seal_dependency_lock(lock_id: str, pins: Sequence[DependencyPin]) -> DependencyLock:
    lock = DependencyLock(lock_id, tuple(sorted(pins, key=lambda item: item.package_name)), "")
    lock = replace(lock, lock_hash=_hash_without(lock, "lock_hash"))
    _validate_lock(lock)
    return lock


def seal_engine_profile(**values: Any) -> EngineProfile:
    values = dict(values)
    settings_id = values.pop("settings_profile_id")
    index_id = values.pop("index_profile_id")
    settings = sorted(values.pop("settings"), key=lambda item: item["setting_name"])
    indexes = sorted(
        values.pop("indexes", logical_index_declarations()),
        key=lambda item: item["logical_index_id"],
    )
    profile = EngineProfile(
        **values,
        settings_profile=seal_input_record(
            settings_id, "engine_settings_r1", {"settings": settings}
        ),
        index_profile=seal_input_record(index_id, "logical_index_profile_r1", {"indexes": indexes}),
        profile_hash="",
    )
    profile = replace(profile, profile_hash=_hash_without(profile, "profile_hash"))
    _validate_engine(profile)
    return profile


def seal_evaluator_profile(
    *, evaluator_id: str, module_id: str, entrypoint_id: str, source_revision: str, source_hash: str
) -> EvaluatorProfile:
    profile = EvaluatorProfile(
        evaluator_id,
        module_id,
        entrypoint_id,
        source_revision,
        source_hash,
        benchmark_port_contract_hash(),
        "",
    )
    profile = replace(profile, profile_hash=_hash_without(profile, "profile_hash"))
    _validate_evaluator(profile)
    return profile


def resource_profile_r1() -> ResourceProfile:
    profile = ResourceProfile(
        "resource_profile_r1",
        2,
        4 * 1024**3,
        4 * 1024**3,
        256,
        False,
        1,
        "local_docker_managed_volume",
        "private_benchmark_network",
        "read_only",
        "",
    )
    return replace(profile, profile_hash=_hash_without(profile, "profile_hash"))


def methodology_authority_state_from_check(
    payload: Mapping[str, Any], *, require_ready_exit_code: int
) -> MethodologyAuthorityState:
    try:
        state = MethodologyAuthorityState(
            payload["authority_state_fingerprint"],
            payload["execution_fingerprint"],
            payload["status"],
            payload["methodology_ready"],
            payload["current_tokenizer_id"],
            payload["target_tokenizer_id"],
            require_ready_exit_code,
        )
    except (KeyError, TypeError):
        _invalid()
    _validate_authority(state)
    return state


def generate_source_free_fixture(profile: str, *, seed: int = 33) -> FixturePayload:
    fixture = _make_fixture(profile, seed)
    _validate_fixture(fixture)
    return fixture


def fixture_data(fixture: FixturePayload) -> dict[str, Any]:
    _validate_fixture(fixture)
    return _fixture_mapping(fixture)


def fixture_counts(fixture: FixturePayload) -> dict[str, int]:
    return _counts(fixture_data(fixture))


def generate_storage_engine_benchmark_package(
    profile: str,
    *,
    seed: int,
    authority_state: MethodologyAuthorityState,
    engine_profiles: Sequence[EngineProfile],
    evaluator_profile: EvaluatorProfile,
    dependency_lock: DependencyLock,
) -> StorageEngineBenchmarkPackage:
    package = _assemble_package(
        profile,
        seed,
        authority_state,
        tuple(engine_profiles),
        evaluator_profile,
        dependency_lock,
    )
    validate_benchmark_package(package)
    return package


def validate_benchmark_package(package: StorageEngineBenchmarkPackage) -> None:
    _validate_package(package)


def validate_package_request_result(
    package: StorageEngineBenchmarkPackage, request: BenchmarkRequest, result: BenchmarkResult
) -> None:
    _validate_package(package)
    _validate_case_result(package, request, result)


def compare_benchmark_results(
    expected: BenchmarkResult, actual: BenchmarkResult
) -> BenchmarkComparison:
    _validate_result(expected)
    _validate_result(actual)
    left, right = expected.to_dict(), actual.to_dict()
    changed = tuple(key for key in sorted(left) if left[key] != right[key])
    return BenchmarkComparison(not changed, changed, expected.result_hash, actual.result_hash)


def reseal_benchmark_request(request: BenchmarkRequest, **changes: Any) -> BenchmarkRequest:
    changed = replace(request, **changes, request_hash="")
    changed = replace(changed, request_hash=_hash_without(changed, "request_hash"))
    _validate_request(changed)
    return changed


def reseal_benchmark_result(
    result: BenchmarkResult, *, payload: Mapping[str, Any] | None = None, **changes: Any
) -> BenchmarkResult:
    if payload is not None:
        changes["payload_json"] = _json_text(payload)
    changed = replace(result, **changes, result_hash="")
    changed = replace(changed, result_hash=_hash_without(changed, "result_hash"))
    _validate_result(changed)
    return changed


def benchmark_port_contract_hash() -> str:
    return canonical_json_sha256(
        {
            "schema_version": SCHEMA,
            "operations": list(_OPERATIONS),
            "control_methods": ["arm_fault", "inspect_semantic_state", "load_sealed_package"],
            "permission_authority": "formowl_actor_scope_contract_only",
            "structured_set_executor": "common_executor_only",
            "source_access": "forbidden",
            "traversal": traversal_contract(),
        }
    )


def traversal_contract() -> dict[str, Any]:
    return {
        "direction": "outgoing",
        "maximum_hops": 2,
        "per_frontier_fanout": 4,
        "maximum_returned_paths": 32,
        "cycle_policy": "no_repeated_node_in_path",
        "visibility_check": "start_edge_target",
        "ordering": "hop_count_target_node_id_incoming_relation_id",
        "timeout_milliseconds": 1000,
        "cross_scope_relation_policy": "reject_at_stage_or_load",
    }


def execute_store_request(
    store: GovernedGraphBenchmarkStore, request: BenchmarkRequest
) -> BenchmarkResult:
    return getattr(store, request.operation)(request)


def initial_semantic_state(package: StorageEngineBenchmarkPackage) -> SemanticState:
    """Return the only valid state before a sealed package is loaded.

    Adapters use this pure helper rather than copying expected states out of a
    case.  The package still seals the independently generated expected states
    used by the verifier.
    """

    _validate_package(package)
    return _empty_state(package.fixture)


def transition_semantic_state(
    package: StorageEngineBenchmarkPackage,
    request: BenchmarkRequest,
    state: SemanticState,
) -> SemanticState:
    """Apply the storage-neutral write transition for one sealed request.

    This is deliberately a pure contract function.  Database adapters must
    persist the returned state atomically and independently expose it through
    :meth:`GovernedGraphBenchmarkControl.inspect_semantic_state`.
    """

    _validate_package(package)
    _validate_request_binding(package.fixture, request)
    _validate_state_binding(package.fixture, state)
    data = _fixture_mapping(package.fixture)
    payload = semantic_state_payload(state)
    actor = input_record_payload(request.authorization)["actor"]
    permission = input_record_payload(request.authorization)["permission"]
    if actor["decision"] != "allow" or permission["decision"] != "allow":
        return state

    if request.operation == "stage_candidate_batch":
        batch = input_record_payload(_input(request, "candidate_batch_r1"))
        if not batch["valid"]:
            return state
        target = seal_semantic_state(
            package.fixture.content_hash,
            _state_payload(
                staged_candidate_ids=batch["candidate_ids"],
                staged_relation_ids=batch["relation_ids"],
            ),
        )
        if state == target:
            return state
        if (
            payload["staged_candidate_ids"]
            or payload["staged_relation_ids"]
            or payload["nodes"]
            or payload["relations"]
            or payload["revision_ids"]
            or payload["lifecycle_event_ids"]
            or payload["success_audit_ids"]
        ):
            _invalid()
        return target

    if request.operation == "reviewed_commit_with_lifecycle":
        plan = input_record_payload(_input(request, "reviewed_commit_plan_r1"))
        if not payload["staged_candidate_ids"] or not payload["staged_relation_ids"]:
            _invalid()
        staged_candidates = set(payload["staged_candidate_ids"])
        staged_relations = set(payload["staged_relation_ids"])
        if (
            not set(plan["candidate_ids"]) <= staged_candidates
            or not set(plan["candidate_relation_ids"]) <= staged_relations
        ):
            _invalid()
        nodes = [
            {
                "node_id": item["node_id"],
                "scope_id": item["scope_id"],
                "visible_actor_ids": item["visible_to"],
            }
            for item in data["canonical_nodes"]
            if item["node_id"] in set(plan["node_ids"])
        ]
        relations = [
            {
                "relation_id": item["relation_id"],
                "scope_id": item["scope_id"],
                "source_node_id": item["source_node_id"],
                "target_node_id": item["target_node_id"],
                "visible_actor_ids": item["visible_to"],
            }
            for item in data["canonical_relations"]
            if item["relation_id"] in set(plan["relation_ids"])
        ]
        return seal_semantic_state(
            package.fixture.content_hash,
            _state_payload(
                staged_candidate_ids=payload["staged_candidate_ids"],
                staged_relation_ids=payload["staged_relation_ids"],
                nodes=nodes,
                relations=relations,
                revision_ids=[plan["revision_id"]],
                lifecycle_event_ids=plan["lifecycle_event_ids"],
                success_audit_ids=[plan["success_audit_id"]],
            ),
        )
    return state


def reference_execute_request(
    package: StorageEngineBenchmarkPackage,
    request: BenchmarkRequest,
    state: SemanticState,
) -> BenchmarkResult:
    """Compute a result from sealed fixture data and inspected adapter state.

    This is a deterministic reference evaluator, not an adapter.  It exists
    so both database implementations produce results from the same logical
    state without treating a pre-sealed expected result as their answer.
    """

    _validate_package(package)
    _validate_request_binding(package.fixture, request)
    _validate_state_binding(package.fixture, state)
    data = _fixture_mapping(package.fixture)
    authorization = input_record_payload(request.authorization)
    actor = authorization["actor"]
    permission = authorization["permission"]
    if actor["decision"] != "allow" or permission["decision"] != "allow":
        return _result(
            request.case_id,
            request.operation,
            package.authority_state,
            "denied",
            None,
            calls=0,
            reason="access_denied",
        )

    if request.operation == "stage_candidate_batch":
        batch = input_record_payload(_input(request, "candidate_batch_r1"))
        if not batch["valid"]:
            return _result(
                request.case_id,
                request.operation,
                package.authority_state,
                "rejected",
                None,
                calls=0,
                reason="contract_rejected",
            )
        return _result(
            request.case_id,
            request.operation,
            package.authority_state,
            "success",
            _payload(item_ids=(batch["batch_id"],)),
            calls=1,
            reason="",
        )

    if request.operation == "reviewed_commit_with_lifecycle":
        post = transition_semantic_state(package, request, state)
        visible = _visible_items(post, actor["actor_profile_id"], actor["scope_id"])
        return _result(
            request.case_id,
            request.operation,
            package.authority_state,
            "success",
            _payload(
                item_ids=visible, provenance=_provenance(data, visible, request.authorization, "")
            ),
            calls=1,
            reason="",
        )

    if request.operation == "effective_view":
        visible = _visible_items(state, actor["actor_profile_id"], actor["scope_id"])
        return _result(
            request.case_id,
            request.operation,
            package.authority_state,
            "success",
            _payload(
                item_ids=visible, provenance=_provenance(data, visible, request.authorization, "")
            ),
            calls=1,
            reason="",
        )

    if request.operation == "bounded_traverse":
        paths = _bounded_paths(state, request)
        values = tuple(
            sorted({value for path in paths for value in path["node_ids"] + path["relation_ids"]})
        )
        return _result(
            request.case_id,
            request.operation,
            package.authority_state,
            "success",
            _payload(
                item_ids=values,
                paths=paths,
                provenance=_provenance(data, values, request.authorization, ""),
            ),
            calls=1,
            reason="",
        )

    if request.operation == "resolve_lifecycle":
        historical = input_record_payload(_input(request, "lifecycle_resolution_r1"))[
            "historical_node_id"
        ]
        current, events, status = _resolve_lifecycle(data, state, historical)
        return _result(
            request.case_id,
            request.operation,
            package.authority_state,
            "success",
            _payload(
                item_ids=current,
                provenance=_provenance(data, current, request.authorization, ""),
                lifecycle={
                    "status": status,
                    "current_ids": list(current),
                    "event_ids": list(events),
                },
            ),
            calls=1,
            reason="",
        )

    if request.operation == "structured_set_handoff":
        coverage = input_record_payload(_input(request, "coverage_contract_r1"))
        rows = _authorized_rows(data, request, coverage)
        row_ids = tuple(row["row_id"] for row in rows)
        return _result(
            request.case_id,
            request.operation,
            package.authority_state,
            "success",
            _payload(
                structural_rows=rows,
                provenance=_provenance(
                    data, row_ids, request.authorization, coverage["coverage_contract_id"]
                ),
            ),
            calls=1,
            reason="",
        )

    if request.operation == "backup_restore":
        return _result(
            request.case_id,
            request.operation,
            package.authority_state,
            "success",
            None,
            calls=1,
            reason="",
        )
    _invalid()


def fault_for_action(package: StorageEngineBenchmarkPackage, action: FaultAction) -> FaultRecord:
    """Resolve one sealed, one-shot fault action without adapter-local policy."""

    _validate_package(package)
    matches = [item for item in package.faults if item.action == action]
    if len(matches) != 1:
        _invalid()
    return matches[0]


def fault_action_value_hash(action: FaultAction) -> str:
    """Hash the decoded, canonical fault value without exposing its surface form."""

    _validate(action)
    return canonical_json_sha256(_decode_json(action.value_json))


def seal_fault_execution_evidence(
    action: FaultAction,
    before: SemanticState,
    after: SemanticState,
    *,
    native_transaction_started: bool,
    native_action_exercised: bool,
    transaction_rolled_back: bool,
) -> FaultExecutionEvidence:
    record = FaultExecutionEvidence(
        action.action_id,
        action.action_kind,
        action.injection_point,
        action.target_kind,
        action.target_id,
        action.field_name,
        fault_action_value_hash(action),
        native_transaction_started,
        native_action_exercised,
        transaction_rolled_back,
        semantic_state_digest(before),
        semantic_state_digest(after),
        "",
    )
    return replace(record, evidence_hash=_hash_without(record, "evidence_hash"))


def seal_restore_execution_evidence(
    backup: SemanticState,
    destructive: SemanticState,
    restored: SemanticState,
    *,
    native_backup_created: bool,
    native_destructive_mutation_observed: bool,
    restore_verified: bool,
) -> RestoreExecutionEvidence:
    record = RestoreExecutionEvidence(
        semantic_state_digest(backup),
        semantic_state_digest(destructive),
        semantic_state_digest(restored),
        native_backup_created,
        native_destructive_mutation_observed,
        restore_verified,
        "",
    )
    return replace(record, evidence_hash=_hash_without(record, "evidence_hash"))


def execute_structured_set(
    package: StorageEngineBenchmarkPackage,
    request: BenchmarkRequest,
    adapter_result: BenchmarkResult,
) -> StructuredSetResult:
    """Validate the authorized row universe, then compute exact membership here."""

    _validate_package(package)
    return _execute_structured_set(package, request, adapter_result)


def verify_case_execution(
    port: GovernedGraphBenchmarkExecutionPort,
    package: StorageEngineBenchmarkPackage,
    case_id: str,
) -> CaseVerification:
    """Execute one sealed case and verify independently inspected storage state."""

    _validate_package(package)
    return _verify_case_execution(port, package, case_id)


def execute_fault_conformance(
    port: GovernedGraphBenchmarkExecutionPort,
    package: StorageEngineBenchmarkPackage,
    fault_id: str,
) -> FaultVerification:
    """Load, build baseline, execute fault, inspect rollback, and verify retry."""

    _validate_package(package)
    fault = _find(package.faults, "fault_id", fault_id)
    port.load_sealed_package(package)
    loaded = port.inspect_semantic_state()
    _validate_state_binding(package.fixture, loaded)
    if loaded != _empty_state(package.fixture):
        _invalid()
    for case_id in fault.baseline_case_ids:
        _verify_case_execution(port, package, case_id)
    before = port.inspect_semantic_state()
    if before != fault.expected_pre_state:
        _invalid()
    port.arm_fault(fault.action)
    actual = execute_store_request(port, fault.request)
    _validate_fault_result(package, fault, actual)
    after = port.inspect_semantic_state()
    _validate_state_binding(package.fixture, after)
    after_payload = semantic_state_payload(after)
    if after != before or after != fault.expected_post_state:
        _invalid()
    if set(fault.forbidden_success_audit_ids) & set(after_payload["success_audit_ids"]):
        _invalid()
    execution_evidence = port.inspect_last_fault_execution()
    _validate_fault_execution_evidence(fault, execution_evidence, before, after)

    retry_verified, retry_digest = False, ""
    if fault.retry_case_id:
        case = _find(package.cases, "case_id", fault.retry_case_id)
        _verify_case_execution(port, package, case.case_id)
        retry_state = port.inspect_semantic_state()
        retry_digest = semantic_state_digest(retry_state)
        repeated = execute_store_request(port, case.request)
        _validate_case_result(package, case.request, repeated)
        repeated_state = port.inspect_semantic_state()
        _validate_state_binding(package.fixture, repeated_state)
        if repeated_state != retry_state:
            _invalid()
        retry_verified = True

    verification = FaultVerification(
        fault_id,
        actual.result_hash,
        semantic_state_digest(before),
        semantic_state_digest(after),
        retry_digest,
        retry_verified,
        execution_evidence.evidence_hash,
        "",
    )
    return replace(verification, verification_hash=_hash_without(verification, "verification_hash"))


def _verify_case_execution(
    port: GovernedGraphBenchmarkExecutionPort,
    package: StorageEngineBenchmarkPackage,
    case_id: str,
) -> CaseVerification:
    case = _find(package.cases, "case_id", case_id)
    before = port.inspect_semantic_state()
    _validate_state_binding(package.fixture, before)
    if before != case.expected_pre_state:
        _invalid()
    actual = execute_store_request(port, case.request)
    _validate_case_result(package, case.request, actual)
    after = port.inspect_semantic_state()
    _validate_state_binding(package.fixture, after)
    if after != case.expected_post_state:
        _invalid()
    if case.request.operation == "bounded_traverse" and actual.status == "success":
        if result_payload(actual)["paths"] != _bounded_paths(after, case.request):
            _invalid()
    operation_evidence_hash = ""
    if case.request.operation == "backup_restore":
        restore_evidence = port.inspect_last_restore_execution()
        _validate_restore_execution_evidence(restore_evidence, before, after)
        operation_evidence_hash = restore_evidence.evidence_hash
    structured_hash = ""
    if case.request.operation == "structured_set_handoff":
        structured_hash = _execute_structured_set(package, case.request, actual).result_hash
    verification = CaseVerification(
        case_id,
        actual.result_hash,
        semantic_state_digest(before),
        semantic_state_digest(after),
        structured_hash,
        operation_evidence_hash,
        "",
    )
    return replace(verification, verification_hash=_hash_without(verification, "verification_hash"))


def _execute_structured_set(
    package: StorageEngineBenchmarkPackage, request: BenchmarkRequest, result: BenchmarkResult
) -> StructuredSetResult:
    _validate_request(request)
    _validate_result(result)
    _validate_request_binding(package.fixture, request)
    if request.operation != "structured_set_handoff" or result.status != "success":
        _invalid()
    predicate = input_record_payload(_input(request, "typed_predicate_r1"))
    coverage = input_record_payload(_input(request, "coverage_contract_r1"))
    payload = result_payload(result)
    if payload["item_ids"] or payload["paths"] or payload["lifecycle"] != _empty_lifecycle():
        _invalid()
    data = _fixture_mapping(package.fixture)
    expected_rows = _authorized_rows(data, request, coverage)
    if payload["structural_rows"] != expected_rows:
        _invalid()
    row_ids = tuple(row["row_id"] for row in expected_rows)
    if payload["provenance"] != _provenance(
        data, row_ids, request.authorization, coverage["coverage_contract_id"]
    ):
        _invalid()
    members = [
        row["row_id"]
        for row in expected_rows
        if row["field_name"] == predicate["field_name"]
        and row["field_value_json"] == predicate["operand_json"]
    ]
    outcome = {
        "predicate_id": predicate["predicate_id"],
        "coverage_contract_id": coverage["coverage_contract_id"],
        "member_ids": members,
        "completeness_state": coverage["completeness_state"],
        "executor_id": coverage["executor_id"],
        "executor_source_hash": coverage["executor_source_hash"],
    }
    record = StructuredSetResult(_json_text(outcome), "")
    return replace(record, result_hash=_hash_without(record, "result_hash"))


def _validate_case_result(
    package: StorageEngineBenchmarkPackage, request: BenchmarkRequest, result: BenchmarkResult
) -> None:
    _validate_request(request)
    _validate_result(result)
    case = _find(package.cases, "case_id", request.case_id)
    if request != case.request or result != case.expected_result:
        _invalid()
    _validate_request_binding(package.fixture, request)
    _validate_result_binding(package, request, result)
    if request.operation == "structured_set_handoff":
        if _execute_structured_set(package, request, result) != case.expected_structured_set:
            _invalid()


def _assemble_package(
    profile: str,
    seed: int,
    authority: MethodologyAuthorityState,
    engines: tuple[EngineProfile, ...],
    evaluator: EvaluatorProfile,
    lock: DependencyLock,
) -> StorageEngineBenchmarkPackage:
    fixture = _make_fixture(profile, seed)
    engines = tuple(sorted(engines, key=lambda item: item.engine_id))
    resource = resource_profile_r1()
    cases = _make_cases(fixture, authority)
    faults = _make_faults(fixture, cases)
    manifests = _make_manifests(fixture, cases, faults, engines, evaluator, lock, resource)
    package = StorageEngineBenchmarkPackage(
        SCHEMA,
        GENERATOR,
        profile,
        seed,
        INPUT_KIND,
        0,
        0,
        0,
        AUTH_TIME,
        authority,
        engines,
        evaluator,
        lock,
        resource,
        fixture,
        cases,
        faults,
        manifests,
        "",
    )
    return replace(package, package_hash=_hash_without(package, "package_hash"))


def _make_fixture(profile: str, seed: int) -> FixturePayload:
    sizes = {
        "conformance_r1": (32, 48, 16, 24, 6, 12),
        "workload_r1": (1024, 4096, 256, 1024, 13, 128),
    }
    if profile not in sizes or type(seed) is not int or seed < 0:
        _invalid()
    nc, nr, nn, ncr, ne, nrow = sizes[profile]
    observations = [
        {
            "observation_id": f"observation_{i:04d}",
            "scope_id": _scope(i),
            "content_hash": _label_hash("observation", profile, seed, i),
            "extractor_run_hash": _label_hash("extractor", profile, seed, i),
        }
        for i in range(nc)
    ]
    candidates = [
        {
            "candidate_id": f"candidate_{i:04d}",
            "observation_id": f"observation_{i:04d}",
            "scope_id": _scope(i),
            "candidate_type": "synthetic_entity",
        }
        for i in range(nc)
    ]
    candidate_relations = [_candidate_relation(i, nc, nn, ncr, seed) for i in range(nr)]
    nodes = [
        {
            "node_id": f"node_{i:04d}",
            "candidate_id": f"candidate_{i:04d}",
            "scope_id": _scope(i),
            "visible_to": [] if i == 14 else [_actor(i)],
        }
        for i in range(nn)
    ]
    relations = [_canonical_relation(candidate_relations[i], nodes) for i in range(ncr)]
    actors = sorted(
        [
            _actor_record("actor_allow_alpha", "scope_alpha", "active", "allow"),
            _actor_record("actor_allow_beta", "scope_beta", "active", "allow"),
            _actor_record("actor_denied", "scope_alpha", "denied", "deny"),
        ],
        key=lambda item: item["actor_profile_id"],
    )
    permissions = [_permission(state) for state in sorted(_PERMISSION_STATES)]
    predicate = _predicate()
    rows = [
        {
            "row_id": f"structured_row_{i:04d}",
            "observation_id": f"observation_{i % nc:04d}",
            "candidate_id": f"candidate_{i % nc:04d}",
            "scope_id": _scope(i),
            "structural_kind": "included" if i % 4 == 0 else "excluded",
            "visible_to": [_actor(i)],
        }
        for i in range(nrow)
    ]
    coverage = [_coverage(scope, predicate, rows) for scope in ("scope_alpha", "scope_beta")]
    lifecycle = _lifecycle(nodes, ne)
    batches = _batches(candidates, candidate_relations)
    plans = _plans(nodes, relations, lifecycle)
    content = {
        "pins": {
            "tokenization_profile_id": "tokenization_profile_source_free_r1",
            "tokenization_profile_fingerprint": _label_hash("tokenization_profile_source_free_r1"),
            "candidate_admission_profile_id": "candidate_admission_source_free_r1",
            "candidate_admission_profile_hash": _label_hash("candidate_admission_source_free_r1"),
            "candidate_schema_version": "candidate_schema_r1",
            "ontology_revision_id": "ontology_revision_r1",
            "ontology_revision_hash": _label_hash("ontology_revision_r1"),
            "policy_ids": list(_POLICY_IDS),
            "policy_manifest_hash": canonical_json_sha256(_POLICY_IDS),
            "review_decision_id": "review_decision_r1",
            "review_decision_hash": canonical_json_sha256(plans),
        },
        "scope_ids": ["scope_alpha", "scope_beta"],
        "observations": observations,
        "candidate_nodes": candidates,
        "candidate_relations": candidate_relations,
        "canonical_nodes": nodes,
        "canonical_relations": relations,
        "actors": actors,
        "permission_cases": permissions,
        "predicates": [predicate],
        "coverage_contracts": coverage,
        "structured_rows": rows,
        "lifecycle_events": lifecycle,
        "batches": batches,
        "commit_plans": plans,
    }
    return FixturePayload(profile, seed, _json_text(content), canonical_json_sha256(content))


def _candidate_relation(i: int, nc: int, nn: int, ncr: int, seed: int) -> dict[str, Any]:
    special = (
        (0, 2),
        (0, 4),
        (0, 6),
        (0, 8),
        (0, 10),
        (0, 12),
        (2, 4),
        (4, 0),
        (2, 14),
        (2, 6),
        (4, 6),
    )
    if i < len(special):
        source, target = special[i]
    else:
        limit = nn if i < ncr else nc
        members = tuple(range(i % 2, limit, 2))
        source = members[(i * 3 + seed) % len(members)]
        target = members[(i * 7 + seed + 1) % len(members)]
        if source == target:
            target = members[(members.index(target) + 1) % len(members)]
    return {
        "candidate_relation_id": f"candidate_relation_{i:05d}",
        "observation_id": f"observation_{source:04d}",
        "scope_id": _scope(source),
        "source_candidate_id": f"candidate_{source:04d}",
        "target_candidate_id": f"candidate_{target:04d}",
        "relation_type": "synthetic_related_to",
    }


def _canonical_relation(
    candidate: Mapping[str, Any], nodes: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    by_candidate = {node["candidate_id"]: node for node in nodes}
    source = by_candidate[candidate["source_candidate_id"]]
    target = by_candidate[candidate["target_candidate_id"]]
    return {
        "relation_id": candidate["candidate_relation_id"].replace("candidate_", "", 1),
        "candidate_relation_id": candidate["candidate_relation_id"],
        "scope_id": candidate["scope_id"],
        "source_node_id": source["node_id"],
        "target_node_id": target["node_id"],
        "visible_to": sorted(set(source["visible_to"]) & set(target["visible_to"])),
    }


def _actor_record(profile_id: str, scope: str, grant_state: str, decision: str) -> dict[str, Any]:
    base = {
        "actor_profile_id": profile_id,
        "actor_id": profile_id.replace("actor_", "user_", 1),
        "scope_id": scope,
        "grant_id": profile_id.replace("actor_", "grant_", 1),
        "grant_state": grant_state,
        "decision": decision,
    }
    return {
        **base,
        "scope_decision_hash": canonical_json_sha256({**base, "authorization_time": AUTH_TIME}),
    }


def _permission(state: str) -> dict[str, Any]:
    decision, calls = ("allow", 1) if state == "matching" else ("deny", 0)
    present, planned, current = {
        "matching": (True, "scope_alpha", "scope_alpha"),
        "missing": (False, None, None),
        "mutable": (True, "scope_alpha", "scope_beta"),
        "nonmatching": (True, "scope_beta", "scope_beta"),
        "null": (True, None, None),
        "wrong_type": (True, {"unexpected": "mapping"}, {"unexpected": "mapping"}),
    }[state]
    base = {
        "property_state": state,
        "property_present": present,
        "planned_value_json": _json_text(planned) if present else "",
        "materialization_value_json": _json_text(current) if present else "",
        "reauthorize_before_materialization": state == "mutable",
        "decision": decision,
        "materialization_calls": calls,
    }
    return {
        "permission_case_id": f"permission_{state}",
        **base,
        "authorizer_trace_hash": canonical_json_sha256(base),
    }


def _predicate() -> dict[str, Any]:
    base = {
        "predicate_id": "typed_predicate_r1",
        "schema_version": "typed_structural_predicate_r1",
        "field_name": "structural_kind",
        "operator": "equals",
        "operand_json": _json_text("included"),
    }
    return {**base, "predicate_hash": canonical_json_sha256(base)}


def _coverage(
    scope: str, predicate: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    base = {
        "coverage_contract_id": f"coverage_{scope}",
        "scope_id": scope,
        "predicate_id": predicate["predicate_id"],
        "covered_row_ids": [row["row_id"] for row in rows if row["scope_id"] == scope],
        "completeness_state": "fixture_complete",
        "executor_id": "deterministic_executor_r1",
        "executor_source_hash": canonical_json_sha256(
            {
                "executor_id": "deterministic_executor_r1",
                "algorithm": "validate_authorized_coverage_then_typed_equals_filter_then_sort",
            }
        ),
    }
    return {**base, "contract_hash": canonical_json_sha256(base)}


def _lifecycle(nodes: Sequence[Mapping[str, Any]], count: int) -> list[dict[str, Any]]:
    events = [
        _event(
            "lifecycle_000",
            "chain_split_merge",
            1,
            "split",
            "scope_alpha",
            ["node_0000"],
            ["node_0002", "node_0004"],
        ),
        _event(
            "lifecycle_001",
            "chain_split_merge",
            2,
            "merge",
            "scope_alpha",
            ["node_0002", "node_0004"],
            ["node_0006"],
        ),
        _event("lifecycle_002", "chain_archive", 1, "archive", "scope_beta", ["node_0001"], []),
        _event("lifecycle_003", "chain_deprecate", 1, "deprecate", "scope_beta", ["node_0003"], []),
        _event(
            "lifecycle_004",
            "chain_supersede",
            1,
            "supersede",
            "scope_beta",
            ["node_0005"],
            ["node_0007"],
        ),
        _event(
            "lifecycle_005",
            "chain_equivalence",
            1,
            "equivalence",
            "scope_beta",
            ["node_0009"],
            ["node_0011"],
        ),
    ]
    used = {value for event in events for value in event["previous_ids"]} | {"node_0006"}
    available = [node for node in nodes if node["node_id"] not in used]
    while len(events) < count:
        i, node = len(events), available[len(events) - 6]
        events.append(
            _event(
                f"lifecycle_{i:03d}",
                f"chain_extra_{i:03d}",
                1,
                "archive",
                node["scope_id"],
                [node["node_id"]],
                [],
            )
        )
    return events


def _event(
    event_id: str,
    chain_id: str,
    sequence: int,
    kind: str,
    scope: str,
    previous: list[str],
    targets: list[str],
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "chain_id": chain_id,
        "sequence": sequence,
        "event_type": kind,
        "scope_id": scope,
        "previous_ids": previous,
        "target_ids": targets,
    }


def _batches(
    candidates: Sequence[Mapping[str, Any]], relations: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    records = [
        {
            "batch_id": f"batch_{scope}",
            "scope_id": scope,
            "candidate_schema_version": "candidate_schema_r1",
            "ontology_revision_id": "ontology_revision_r1",
            "policy_ids": list(_POLICY_IDS),
            "candidate_ids": [
                item["candidate_id"] for item in candidates if item["scope_id"] == scope
            ],
            "relation_ids": [
                item["candidate_relation_id"] for item in relations if item["scope_id"] == scope
            ],
            "valid": True,
            "attempted_source_id": "",
            "attempted_target_id": "",
            "rejection_code": "",
        }
        for scope in ("scope_alpha", "scope_beta")
    ]
    records.extend(
        [
            {
                "batch_id": "batch_rejected_cross_scope",
                "scope_id": "scope_alpha",
                "candidate_schema_version": "candidate_schema_r1",
                "ontology_revision_id": "ontology_revision_r1",
                "policy_ids": list(_POLICY_IDS),
                "candidate_ids": ["candidate_0000", "candidate_0001"],
                "relation_ids": [],
                "valid": False,
                "attempted_source_id": "candidate_0000",
                "attempted_target_id": "candidate_0001",
                "rejection_code": "cross_scope_relation",
            },
            {
                "batch_id": "batch_rejected_schema_ontology",
                "scope_id": "scope_alpha",
                "candidate_schema_version": "unsupported_schema_r0",
                "ontology_revision_id": "stale_ontology_revision_r0",
                "policy_ids": ["bad_policy_r0"],
                "candidate_ids": ["candidate_0000"],
                "relation_ids": [],
                "valid": False,
                "attempted_source_id": "",
                "attempted_target_id": "",
                "rejection_code": "contract_rejected",
            },
        ]
    )
    return sorted(records, key=lambda item: item["batch_id"])


def _plans(
    nodes: Sequence[Mapping[str, Any]],
    relations: Sequence[Mapping[str, Any]],
    lifecycle: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    records = []
    for scope in ("scope_alpha", "scope_beta"):
        suffix = scope.removeprefix("scope_")
        scope_nodes = [item for item in nodes if item["scope_id"] == scope]
        scope_relations = [item for item in relations if item["scope_id"] == scope]
        records.append(
            {
                "plan_id": f"commit_plan_{suffix}",
                "scope_id": scope,
                "ontology_revision_id": "ontology_revision_r1",
                "review_decision_id": "review_decision_r1",
                "policy_ids": list(_POLICY_IDS),
                "candidate_ids": [item["candidate_id"] for item in scope_nodes],
                "candidate_relation_ids": [
                    item["candidate_relation_id"] for item in scope_relations
                ],
                "node_ids": [item["node_id"] for item in scope_nodes],
                "relation_ids": [item["relation_id"] for item in scope_relations],
                "lifecycle_event_ids": [
                    item["event_id"] for item in lifecycle if item["scope_id"] == scope
                ],
                "revision_id": f"graph_revision_{suffix}_r1",
                "success_audit_id": f"audit_commit_{suffix}_r1",
            }
        )
    return records


def _make_cases(
    fixture: FixturePayload, authority: MethodologyAuthorityState
) -> tuple[SealedCase, ...]:
    data = _fixture_mapping(fixture)
    empty = _empty_state(fixture)
    batch = _find_dict(data["batches"], "batch_id", "batch_scope_alpha")
    staged = _staged_state(fixture, batch)
    plan = _find_dict(data["commit_plans"], "plan_id", "commit_plan_alpha")
    committed = _committed_state(fixture, data, batch, plan)
    cases: list[SealedCase] = []

    def add(
        case_id: str,
        request: BenchmarkRequest,
        pre: SemanticState,
        post: SemanticState,
        status: str,
        payload: Mapping[str, Any] | None = None,
        *,
        calls: int = 0,
        reason: str = "",
        structured: StructuredSetResult | None = None,
    ) -> None:
        result = _result(case_id, request.operation, authority, status, payload, calls, reason)
        record = SealedCase(case_id, request, result, pre, post, structured, "")
        cases.append(replace(record, case_hash=_hash_without(record, "case_hash")))

    allow_auth = _authorization(data, "actor_allow_alpha", "permission_matching")
    visible = _visible_items(committed, "actor_allow_alpha", "scope_alpha")
    visible_payload = _payload(
        item_ids=visible,
        provenance=_provenance(data, visible, allow_auth, ""),
    )
    add(
        "candidate_stage_write",
        _request(
            fixture,
            "candidate_stage_write",
            "stage_candidate_batch",
            allow_auth,
            [_input_from("candidate_batch_r1", batch["batch_id"], batch)],
        ),
        empty,
        staged,
        "success",
        _payload(item_ids=(batch["batch_id"],)),
        calls=1,
    )
    rejected = _find_dict(data["batches"], "batch_id", "batch_rejected_cross_scope")
    add(
        "candidate_stage_cross_scope_reject",
        _request(
            fixture,
            "candidate_stage_cross_scope_reject",
            "stage_candidate_batch",
            allow_auth,
            [_input_from("candidate_batch_r1", rejected["batch_id"], rejected)],
        ),
        empty,
        empty,
        "rejected",
        reason="contract_rejected",
    )
    add(
        "review_commit",
        _request(
            fixture,
            "review_commit",
            "reviewed_commit_with_lifecycle",
            allow_auth,
            [_input_from("reviewed_commit_plan_r1", plan["plan_id"], plan)],
        ),
        staged,
        committed,
        "success",
        visible_payload,
        calls=1,
    )
    revision = _input_from("revision_r1", plan["revision_id"], {"revision_id": plan["revision_id"]})
    add(
        "effective_view_allow",
        _request(fixture, "effective_view_allow", "effective_view", allow_auth, [revision]),
        committed,
        committed,
        "success",
        visible_payload,
        calls=1,
    )
    add(
        "effective_view_deny",
        _request(
            fixture,
            "effective_view_deny",
            "effective_view",
            _authorization(data, "actor_denied", "permission_matching"),
            [revision],
        ),
        committed,
        committed,
        "denied",
        reason="access_denied",
    )
    for permission in data["permission_cases"]:
        allowed = permission["decision"] == "allow"
        case_id = f"property_permission_{permission['property_state']}"
        add(
            case_id,
            _request(
                fixture,
                case_id,
                "effective_view",
                _authorization(data, "actor_allow_alpha", permission["permission_case_id"]),
                [revision],
            ),
            committed,
            committed,
            "success" if allowed else "denied",
            visible_payload if allowed else None,
            calls=permission["materialization_calls"],
            reason="" if allowed else "access_denied",
        )
    traversal = _input_from(
        "bounded_traversal_r1",
        "traversal_node_0000",
        {"start_node_id": "node_0000", **traversal_contract()},
    )
    traversal_request = _request(
        fixture, "bounded_traversal_allow", "bounded_traverse", allow_auth, [traversal]
    )
    paths = _bounded_paths(committed, traversal_request)
    traversal_ids = tuple(
        sorted({value for path in paths for value in path["node_ids"] + path["relation_ids"]})
    )
    add(
        "bounded_traversal_allow",
        traversal_request,
        committed,
        committed,
        "success",
        _payload(
            item_ids=traversal_ids,
            paths=paths,
            provenance=_provenance(data, traversal_ids, allow_auth, ""),
        ),
        calls=1,
    )
    add(
        "bounded_traversal_deny",
        _request(
            fixture,
            "bounded_traversal_deny",
            "bounded_traverse",
            _authorization(data, "actor_denied", "permission_matching"),
            [traversal],
        ),
        committed,
        committed,
        "denied",
        reason="access_denied",
    )
    current, events, lifecycle_status = _resolve_lifecycle(data, committed, "node_0000")
    add(
        "lifecycle_resolution_split_merge",
        _request(
            fixture,
            "lifecycle_resolution_split_merge",
            "resolve_lifecycle",
            allow_auth,
            [
                _input_from(
                    "lifecycle_resolution_r1", "node_0000", {"historical_node_id": "node_0000"}
                )
            ],
        ),
        committed,
        committed,
        "success",
        _payload(
            item_ids=current,
            provenance=_provenance(data, current, allow_auth, ""),
            lifecycle={
                "status": lifecycle_status,
                "current_ids": list(current),
                "event_ids": list(events),
            },
        ),
        calls=1,
    )
    predicate = _find_dict(data["predicates"], "predicate_id", "typed_predicate_r1")
    coverage = _find_dict(
        data["coverage_contracts"], "coverage_contract_id", "coverage_scope_alpha"
    )
    structured_request = _request(
        fixture,
        "structured_set_handoff",
        "structured_set_handoff",
        allow_auth,
        [
            _input_from("typed_predicate_r1", predicate["predicate_id"], predicate),
            _input_from("coverage_contract_r1", coverage["coverage_contract_id"], coverage),
        ],
    )
    rows = _authorized_rows(data, structured_request, coverage)
    structured_payload = _payload(
        structural_rows=rows,
        provenance=_provenance(
            data, tuple(row["row_id"] for row in rows), allow_auth, coverage["coverage_contract_id"]
        ),
    )
    structured_result = _structured_expected(structured_request, rows)
    add(
        "structured_set_handoff",
        structured_request,
        committed,
        committed,
        "success",
        structured_payload,
        calls=1,
        structured=structured_result,
    )
    invalid = _find_dict(data["batches"], "batch_id", "batch_rejected_schema_ontology")
    add(
        "schema_and_ontology_reject",
        _request(
            fixture,
            "schema_and_ontology_reject",
            "stage_candidate_batch",
            allow_auth,
            [_input_from("candidate_batch_r1", invalid["batch_id"], invalid)],
        ),
        committed,
        committed,
        "rejected",
        reason="contract_rejected",
    )
    add(
        "backup_restore",
        _request(fixture, "backup_restore", "backup_restore", allow_auth, [revision]),
        committed,
        committed,
        "success",
        calls=1,
    )
    return tuple(sorted(cases, key=lambda item: item.case_id))


def _authorization(data: Mapping[str, Any], actor_id: str, permission_id: str) -> SealedInputRecord:
    actor = _find_dict(data["actors"], "actor_profile_id", actor_id)
    permission = _find_dict(data["permission_cases"], "permission_case_id", permission_id)
    payload = {
        "actor": actor,
        "permission": permission,
        "authorization_time": AUTH_TIME,
    }
    return seal_input_record(
        f"authorization_{actor_id}_{permission['property_state']}",
        "governed_authorization_r1",
        payload,
    )


def _input_from(kind: str, record_id: str, payload: Mapping[str, Any]) -> SealedInputRecord:
    return seal_input_record(record_id, kind, payload)


def _request(
    fixture: FixturePayload,
    case_id: str,
    operation: str,
    authorization: SealedInputRecord,
    inputs: Sequence[SealedInputRecord],
) -> BenchmarkRequest:
    request = BenchmarkRequest(
        SCHEMA,
        case_id,
        operation,
        authorization,
        tuple(sorted(inputs, key=lambda item: (item.record_kind, item.record_id))),
        fixture.content_hash,
        "",
    )
    return replace(request, request_hash=_hash_without(request, "request_hash"))


def _result(
    case_id: str,
    operation: str,
    authority: MethodologyAuthorityState,
    status: str,
    payload: Mapping[str, Any] | None,
    calls: int,
    reason: str,
) -> BenchmarkResult:
    result = BenchmarkResult(
        SCHEMA,
        case_id,
        operation,
        status,
        _json_text(payload or _payload()),
        calls,
        reason,
        authority.authority_state_fingerprint,
        authority.execution_fingerprint,
        authority.methodology_ready,
        "",
    )
    return replace(result, result_hash=_hash_without(result, "result_hash"))


def _payload(
    *,
    item_ids: Sequence[str] = (),
    paths: Sequence[Mapping[str, Any]] = (),
    structural_rows: Sequence[Mapping[str, Any]] = (),
    provenance: Sequence[Mapping[str, Any]] = (),
    lifecycle: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "item_ids": list(item_ids),
        "paths": list(paths),
        "structural_rows": list(structural_rows),
        "provenance": list(provenance),
        "lifecycle": dict(lifecycle or _empty_lifecycle()),
    }


def _empty_lifecycle() -> dict[str, Any]:
    return {"status": "", "current_ids": [], "event_ids": []}


def _empty_state(fixture: FixturePayload) -> SemanticState:
    return seal_semantic_state(fixture.content_hash, _state_payload())


def _staged_state(fixture: FixturePayload, batch: Mapping[str, Any]) -> SemanticState:
    return seal_semantic_state(
        fixture.content_hash,
        _state_payload(
            staged_candidate_ids=batch["candidate_ids"],
            staged_relation_ids=batch["relation_ids"],
        ),
    )


def _committed_state(
    fixture: FixturePayload,
    data: Mapping[str, Any],
    batch: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> SemanticState:
    node_ids, relation_ids = set(plan["node_ids"]), set(plan["relation_ids"])
    nodes = [
        {
            "node_id": item["node_id"],
            "scope_id": item["scope_id"],
            "visible_actor_ids": item["visible_to"],
        }
        for item in data["canonical_nodes"]
        if item["node_id"] in node_ids
    ]
    relations = [
        {
            "relation_id": item["relation_id"],
            "scope_id": item["scope_id"],
            "source_node_id": item["source_node_id"],
            "target_node_id": item["target_node_id"],
            "visible_actor_ids": item["visible_to"],
        }
        for item in data["canonical_relations"]
        if item["relation_id"] in relation_ids
    ]
    return seal_semantic_state(
        fixture.content_hash,
        _state_payload(
            staged_candidate_ids=batch["candidate_ids"],
            staged_relation_ids=batch["relation_ids"],
            nodes=nodes,
            relations=relations,
            revision_ids=[plan["revision_id"]],
            lifecycle_event_ids=plan["lifecycle_event_ids"],
            success_audit_ids=[plan["success_audit_id"]],
        ),
    )


def _state_payload(
    *,
    staged_candidate_ids: Sequence[str] = (),
    staged_relation_ids: Sequence[str] = (),
    nodes: Sequence[Mapping[str, Any]] = (),
    relations: Sequence[Mapping[str, Any]] = (),
    revision_ids: Sequence[str] = (),
    lifecycle_event_ids: Sequence[str] = (),
    success_audit_ids: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "staged_candidate_ids": list(staged_candidate_ids),
        "staged_relation_ids": list(staged_relation_ids),
        "nodes": list(nodes),
        "relations": list(relations),
        "revision_ids": list(revision_ids),
        "lifecycle_event_ids": list(lifecycle_event_ids),
        "success_audit_ids": list(success_audit_ids),
    }


def _visible_items(state: SemanticState, actor_id: str, scope: str) -> tuple[str, ...]:
    payload = semantic_state_payload(state)
    nodes = {
        item["node_id"]
        for item in payload["nodes"]
        if item["scope_id"] == scope and actor_id in item["visible_actor_ids"]
    }
    relations = {
        item["relation_id"]
        for item in payload["relations"]
        if item["scope_id"] == scope
        and actor_id in item["visible_actor_ids"]
        and item["source_node_id"] in nodes
        and item["target_node_id"] in nodes
    }
    return tuple(sorted(nodes | relations))


def _bounded_paths(state: SemanticState, request: BenchmarkRequest) -> list[dict[str, Any]]:
    state_data = semantic_state_payload(state)
    traversal = input_record_payload(_input(request, "bounded_traversal_r1"))
    authorization = input_record_payload(request.authorization)
    actor = authorization["actor"]
    nodes = {item["node_id"]: item for item in state_data["nodes"]}
    start_id = traversal["start_node_id"]
    start = nodes.get(start_id)
    if (
        start is None
        or start["scope_id"] != actor["scope_id"]
        or actor["actor_profile_id"] not in start["visible_actor_ids"]
    ):
        return []
    outgoing: dict[str, list[dict[str, Any]]] = {}
    for relation in state_data["relations"]:
        target = nodes.get(relation["target_node_id"])
        if (
            target is not None
            and relation["scope_id"] == actor["scope_id"]
            and actor["actor_profile_id"] in relation["visible_actor_ids"]
            and actor["actor_profile_id"] in target["visible_actor_ids"]
        ):
            outgoing.setdefault(relation["source_node_id"], []).append(relation)
    for values in outgoing.values():
        values.sort(key=lambda item: (item["target_node_id"], item["relation_id"]))
    frontier = [{"node_ids": [start_id], "relation_ids": []}]
    returned = []
    for _ in range(traversal["maximum_hops"]):
        following = []
        for path in frontier:
            for relation in outgoing.get(path["node_ids"][-1], [])[
                : traversal["per_frontier_fanout"]
            ]:
                if relation["target_node_id"] in path["node_ids"]:
                    continue
                extended = {
                    "node_ids": path["node_ids"] + [relation["target_node_id"]],
                    "relation_ids": path["relation_ids"] + [relation["relation_id"]],
                }
                returned.append(extended)
                following.append(extended)
        frontier = following
    return sorted(returned, key=_path_key)[: traversal["maximum_returned_paths"]]


def _resolve_lifecycle(
    data: Mapping[str, Any], state: SemanticState, historical_id: str
) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    state_events = set(semantic_state_payload(state)["lifecycle_event_ids"])
    current, applied, kinds = {historical_id}, [], []
    for _ in range(len(state_events) + 1):
        match = next(
            (
                item
                for item in data["lifecycle_events"]
                if item["event_id"] in state_events
                and item["event_id"] not in applied
                and set(item["previous_ids"]).issubset(current)
            ),
            None,
        )
        if match is None:
            break
        current.difference_update(match["previous_ids"])
        current.update(match["target_ids"])
        applied.append(match["event_id"])
        kinds.append(match["event_type"])
    status = "merged" if kinds[-2:] == ["split", "merge"] else (kinds[-1] if kinds else "current")
    return tuple(sorted(current)), tuple(applied), status


def _provenance(
    data: Mapping[str, Any],
    result_ids: Sequence[str],
    authorization: SealedInputRecord,
    coverage_id: str,
) -> list[dict[str, Any]]:
    auth = input_record_payload(authorization)
    actor = auth["actor"]
    observations = {item["observation_id"]: item for item in data["observations"]}
    candidates = {item["candidate_id"]: item for item in data["candidate_nodes"]}
    candidate_relations = {
        item["candidate_relation_id"]: item for item in data["candidate_relations"]
    }
    nodes = {item["node_id"]: item for item in data["canonical_nodes"]}
    relations = {item["relation_id"]: item for item in data["canonical_relations"]}
    rows = {item["row_id"]: item for item in data["structured_rows"]}
    records = []
    for result_id in sorted(result_ids):
        if result_id in nodes:
            candidate = candidates[nodes[result_id]["candidate_id"]]
            observation, candidate_id = (
                observations[candidate["observation_id"]],
                candidate["candidate_id"],
            )
        elif result_id in relations:
            candidate = candidate_relations[relations[result_id]["candidate_relation_id"]]
            observation, candidate_id = (
                observations[candidate["observation_id"]],
                candidate["candidate_relation_id"],
            )
        elif result_id in rows:
            row = rows[result_id]
            observation, candidate_id = observations[row["observation_id"]], row["candidate_id"]
        else:
            continue
        records.append(
            {
                "result_id": result_id,
                "observation_id": observation["observation_id"],
                "observation_content_hash": observation["content_hash"],
                "extractor_run_hash": observation["extractor_run_hash"],
                "candidate_id": candidate_id,
                "ontology_revision_id": data["pins"]["ontology_revision_id"],
                "review_decision_id": data["pins"]["review_decision_id"],
                "scope_decision_hash": actor["scope_decision_hash"],
                "coverage_contract_id": coverage_id,
            }
        )
    return records


def _authorized_rows(
    data: Mapping[str, Any], request: BenchmarkRequest, coverage: Mapping[str, Any]
) -> list[dict[str, Any]]:
    auth = input_record_payload(request.authorization)
    actor_id = auth["actor"]["actor_profile_id"]
    covered = set(coverage["covered_row_ids"])
    return [
        {
            "row_id": item["row_id"],
            "scope_id": item["scope_id"],
            "field_name": "structural_kind",
            "field_value_json": _json_text(item["structural_kind"]),
        }
        for item in data["structured_rows"]
        if item["row_id"] in covered
        and item["scope_id"] == coverage["scope_id"]
        and actor_id in item["visible_to"]
    ]


def _structured_expected(
    request: BenchmarkRequest, rows: Sequence[Mapping[str, Any]]
) -> StructuredSetResult:
    predicate = input_record_payload(_input(request, "typed_predicate_r1"))
    coverage = input_record_payload(_input(request, "coverage_contract_r1"))
    outcome = {
        "predicate_id": predicate["predicate_id"],
        "coverage_contract_id": coverage["coverage_contract_id"],
        "member_ids": [
            row["row_id"]
            for row in rows
            if row["field_name"] == predicate["field_name"]
            and row["field_value_json"] == predicate["operand_json"]
        ],
        "completeness_state": coverage["completeness_state"],
        "executor_id": coverage["executor_id"],
        "executor_source_hash": coverage["executor_source_hash"],
    }
    record = StructuredSetResult(_json_text(outcome), "")
    return replace(record, result_hash=_hash_without(record, "result_hash"))


def _make_faults(fixture: FixturePayload, cases: Sequence[SealedCase]) -> tuple[FaultRecord, ...]:
    by_case = {item.case_id: item for item in cases}
    data = _fixture_mapping(fixture)
    faults = []
    for row in _FAULT_ROWS.splitlines():
        (
            fault_id,
            point,
            case_id,
            status,
            reason,
            retry,
            kind,
            target_kind,
            target_id,
            field_name,
            value_json,
        ) = row.split("|", 10)
        case = by_case[case_id]
        expected = case.expected_result
        reason = "" if reason == "-" else reason
        if status == "partial" and fault_id == "traversal_path_limit":
            payload = result_payload(expected)
            paths = payload["paths"][:2]
            ids = tuple(
                sorted(
                    {value for path in paths for value in path["node_ids"] + path["relation_ids"]}
                )
            )
            payload = _payload(
                item_ids=ids,
                paths=paths,
                provenance=_provenance(data, ids, case.request.authorization, ""),
            )
            expected = reseal_benchmark_result(
                expected, payload=payload, status=status, reason_code=reason
            )
        elif status == "partial":
            expected = reseal_benchmark_result(expected, status=status, reason_code=reason)
        elif status != "success":
            expected = reseal_benchmark_result(
                expected,
                payload=_payload(),
                status=status,
                materialization_calls=0,
                reason_code=reason,
            )
        action = FaultAction(
            fault_id,
            kind,
            point,
            target_kind,
            target_id,
            field_name,
            _json_text(_decode_json(value_json)),
            True,
        )
        forbidden = ()
        if case.request.operation == "reviewed_commit_with_lifecycle":
            forbidden = (
                input_record_payload(_input(case.request, "reviewed_commit_plan_r1"))[
                    "success_audit_id"
                ],
            )
        record = FaultRecord(
            fault_id,
            _baseline_case_ids(case.expected_pre_state, by_case),
            case.request,
            action,
            expected,
            case.expected_pre_state,
            case.expected_pre_state,
            forbidden,
            case.case_id if retry == "1" else "",
            "",
        )
        faults.append(replace(record, fault_hash=_hash_without(record, "fault_hash")))
    return tuple(sorted(faults, key=lambda item: item.fault_id))


def _baseline_case_ids(state: SemanticState, cases: Mapping[str, SealedCase]) -> tuple[str, ...]:
    if state == cases["candidate_stage_write"].expected_pre_state:
        return ()
    if state == cases["candidate_stage_write"].expected_post_state:
        return ("candidate_stage_write",)
    if state == cases["review_commit"].expected_post_state:
        return ("candidate_stage_write", "review_commit")
    _invalid()


def _make_manifests(
    fixture: FixturePayload,
    cases: Sequence[SealedCase],
    faults: Sequence[FaultRecord],
    engines: Sequence[EngineProfile],
    evaluator: EvaluatorProfile,
    lock: DependencyLock,
    resource: ResourceProfile,
) -> tuple[NamedHash, ...]:
    data = _fixture_mapping(fixture)
    values = {
        "actor_grant_scope_manifest_hash": canonical_json_sha256(data["actors"]),
        "adapter_contract_hash": benchmark_port_contract_hash(),
        "candidate_admission_profile_hash": data["pins"]["candidate_admission_profile_hash"],
        "candidate_graph_manifest_hash": canonical_json_sha256(
            [
                data[name]
                for name in (
                    "candidate_nodes",
                    "candidate_relations",
                    "canonical_nodes",
                    "canonical_relations",
                )
            ]
        ),
        "coverage_contract_manifest_hash": canonical_json_sha256(data["coverage_contracts"]),
        "dependency_lock_hash": lock.lock_hash,
        "deterministic_executor_hash": canonical_json_sha256(
            [item["executor_source_hash"] for item in data["coverage_contracts"]]
        ),
        "engine_index_manifest_hash": canonical_json_sha256(
            [(item.engine_id, item.index_profile) for item in engines]
        ),
        "engine_profile_manifest_hash": canonical_json_sha256(engines),
        "engine_settings_manifest_hash": canonical_json_sha256(
            [(item.engine_id, item.settings_profile) for item in engines]
        ),
        "evaluator_profile_hash": evaluator.profile_hash,
        "expected_result_manifest_hash": canonical_json_sha256(
            [item.expected_result.result_hash for item in cases]
        ),
        "expected_state_manifest_hash": canonical_json_sha256(
            [
                (
                    item.case_id,
                    semantic_state_digest(item.expected_pre_state),
                    semantic_state_digest(item.expected_post_state),
                )
                for item in cases
            ]
        ),
        "fault_manifest_hash": canonical_json_sha256(faults),
        "fixture_generator_hash": canonical_json_sha256({"generator_revision": GENERATOR}),
        "formowl_authorizer_trace_hash": canonical_json_sha256(
            {
                "actors": [item["scope_decision_hash"] for item in data["actors"]],
                "permissions": [item["authorizer_trace_hash"] for item in data["permission_cases"]],
            }
        ),
        "observation_snapshot_manifest_hash": canonical_json_sha256(data["observations"]),
        "ontology_revision_hash": data["pins"]["ontology_revision_hash"],
        "permission_property_manifest_hash": canonical_json_sha256(data["permission_cases"]),
        "policy_pin_manifest_hash": data["pins"]["policy_manifest_hash"],
        "resource_profile_hash": resource.profile_hash,
        "reviewed_decision_hash": data["pins"]["review_decision_hash"],
        "sealed_query_manifest_hash": canonical_json_sha256(cases),
        "tokenization_profile_fingerprint": data["pins"]["tokenization_profile_fingerprint"],
        "traversal_bound_manifest_hash": canonical_json_sha256(traversal_contract()),
    }
    return tuple(NamedHash(name, value) for name, value in sorted(values.items()))


def _validate(value: Any) -> None:
    validators = (
        (StorageEngineBenchmarkPackage, _validate_package),
        (FixturePayload, _validate_fixture),
        (BenchmarkRequest, _validate_request),
        (BenchmarkResult, _validate_result),
        (SemanticState, _validate_state_shape),
        (StructuredSetResult, _validate_structured_result),
        (SealedInputRecord, _validate_input_record),
        (EngineProfile, _validate_engine),
        (EvaluatorProfile, _validate_evaluator),
        (DependencyLock, _validate_lock),
        (MethodologyAuthorityState, _validate_authority),
    )
    for kind, validator in validators:
        if isinstance(value, kind):
            validator(value)
            return
    if not is_dataclass(value):
        _invalid()
    value.to_dict()


@lru_cache(maxsize=8)
def _validate_package(package: StorageEngineBenchmarkPackage) -> None:
    if (
        package.schema_version != SCHEMA
        or package.generator_revision != GENERATOR
        or package.input_kind != INPUT_KIND
        or package.authorization_time != AUTH_TIME
        or package.fixture_profile != package.fixture.profile
        or package.seed != package.fixture.seed
        or any(
            value != 0
            for value in (
                package.raw_pst_read_count,
                package.pst_parser_invocation_count,
                package.new_extractor_run_count,
            )
        )
    ):
        _invalid()
    _validate_authority(package.authority_state)
    if tuple(item.engine_id for item in package.engine_profiles) != ("neo4j", "postgresql"):
        _invalid()
    for engine in package.engine_profiles:
        _validate_engine(engine)
    _validate_lock(package.dependency_lock)
    dependencies = {item.package_name: item for item in package.dependency_lock.dependencies}
    for engine in package.engine_profiles:
        pin = dependencies.get(engine.driver_package)
        if pin is None or (pin.version, pin.artifact_hash) != (
            engine.driver_version,
            engine.driver_artifact_hash,
        ):
            _invalid()
    _validate_evaluator(package.evaluator_profile)
    if package.resource_profile != resource_profile_r1():
        _invalid()
    _validate_fixture(package.fixture)
    expected = _assemble_package(
        package.fixture_profile,
        package.seed,
        package.authority_state,
        package.engine_profiles,
        package.evaluator_profile,
        package.dependency_lock,
    )
    if package != expected:
        _invalid()
    package.to_dict()


@lru_cache(maxsize=16)
def _validate_fixture(fixture: FixturePayload) -> None:
    _require_hash(fixture.content_hash)
    if fixture != _make_fixture(fixture.profile, fixture.seed):
        _invalid()
    data = _fixture_mapping(fixture)
    minimum = {
        "conformance_r1": {
            "staged_candidates": 32,
            "staged_relations": 48,
            "canonical_members": 16,
            "canonical_relations": 24,
            "lifecycle_events": 6,
            "structured_rows": 12,
            "actor_grant_profiles": 3,
            "isolated_scopes": 2,
        },
        "workload_r1": {
            "staged_candidates": 1024,
            "staged_relations": 4096,
            "canonical_members": 256,
            "canonical_relations": 1024,
            "lifecycle_chains": 12,
            "structured_rows": 128,
            "actor_grant_profiles": 3,
            "isolated_scopes": 2,
        },
    }.get(fixture.profile)
    if minimum is None or any(_counts(data)[name] < count for name, count in minimum.items()):
        _invalid()
    edges = {
        (item["source_node_id"], item["target_node_id"]) for item in data["canonical_relations"]
    }
    if not {("node_0000", "node_0004"), ("node_0004", "node_0000")} <= edges:
        _invalid()
    plan = _find_dict(data["commit_plans"], "plan_id", "commit_plan_alpha")
    batch = _find_dict(data["batches"], "batch_id", "batch_scope_alpha")
    state = _committed_state(fixture, data, batch, plan)
    if _resolve_lifecycle(data, state, "node_0000") != (
        ("node_0006",),
        ("lifecycle_000", "lifecycle_001"),
        "merged",
    ):
        _invalid()


def _counts(data: Mapping[str, Any]) -> dict[str, int]:
    return {
        "staged_candidates": len(data["candidate_nodes"]),
        "staged_relations": len(data["candidate_relations"]),
        "canonical_members": len(data["canonical_nodes"]),
        "canonical_relations": len(data["canonical_relations"]),
        "lifecycle_events": len(data["lifecycle_events"]),
        "lifecycle_chains": len({item["chain_id"] for item in data["lifecycle_events"]}),
        "structured_rows": len(data["structured_rows"]),
        "actor_grant_profiles": len(data["actors"]),
        "isolated_scopes": len(data["scope_ids"]),
    }


def _validate_input_record(record: SealedInputRecord) -> None:
    _require_id(record.record_id)
    _require_id(record.record_kind)
    _json_object(record.payload_json)
    _require_hash(record.record_hash)
    if record.record_hash != _hash_without(record, "record_hash"):
        _invalid()


def _validate_request(request: BenchmarkRequest) -> None:
    if request.schema_version != SCHEMA or request.operation not in _OPERATIONS:
        _invalid()
    _require_id(request.case_id)
    _validate_input_record(request.authorization)
    if request.authorization.record_kind != "governed_authorization_r1":
        _invalid()
    if request.inputs != tuple(
        sorted(request.inputs, key=lambda item: (item.record_kind, item.record_id))
    ):
        _invalid()
    if len({(item.record_kind, item.record_id) for item in request.inputs}) != len(request.inputs):
        _invalid()
    for item in request.inputs:
        _validate_input_record(item)
    expected_kinds = {
        "stage_candidate_batch": ("candidate_batch_r1",),
        "reviewed_commit_with_lifecycle": ("reviewed_commit_plan_r1",),
        "effective_view": ("revision_r1",),
        "bounded_traverse": ("bounded_traversal_r1",),
        "resolve_lifecycle": ("lifecycle_resolution_r1",),
        "structured_set_handoff": ("coverage_contract_r1", "typed_predicate_r1"),
        "backup_restore": ("revision_r1",),
    }[request.operation]
    if tuple(item.record_kind for item in request.inputs) != expected_kinds:
        _invalid()
    _require_hash(request.fixture_hash)
    _require_hash(request.request_hash)
    if request.request_hash != _hash_without(request, "request_hash"):
        _invalid()
    if request.operation == "bounded_traverse":
        traversal = input_record_payload(request.inputs[0])
        if traversal != {"start_node_id": traversal.get("start_node_id"), **traversal_contract()}:
            _invalid()


def _validate_request_binding(fixture: FixturePayload, request: BenchmarkRequest) -> None:
    data = _fixture_mapping(fixture)
    if request.fixture_hash != fixture.content_hash:
        _invalid()
    authorization = input_record_payload(request.authorization)
    actor = authorization.get("actor", {})
    permission = authorization.get("permission", {})
    if authorization.get("authorization_time") != AUTH_TIME:
        _invalid()
    if actor != _find_dict(data["actors"], "actor_profile_id", actor.get("actor_profile_id")):
        _invalid()
    if permission != _find_dict(
        data["permission_cases"], "permission_case_id", permission.get("permission_case_id")
    ):
        _invalid()
    scope = actor["scope_id"]
    if request.operation == "stage_candidate_batch":
        value = input_record_payload(request.inputs[0])
        if (
            value != _find_dict(data["batches"], "batch_id", value.get("batch_id"))
            or value["scope_id"] != scope
        ):
            _invalid()
    elif request.operation == "reviewed_commit_with_lifecycle":
        value = input_record_payload(request.inputs[0])
        if (
            value != _find_dict(data["commit_plans"], "plan_id", value.get("plan_id"))
            or value["scope_id"] != scope
        ):
            _invalid()
    elif request.operation in {"effective_view", "backup_restore"}:
        revision_id = input_record_payload(request.inputs[0]).get("revision_id")
        if (
            len(
                [
                    item
                    for item in data["commit_plans"]
                    if item["revision_id"] == revision_id and item["scope_id"] == scope
                ]
            )
            != 1
        ):
            _invalid()
    elif request.operation == "bounded_traverse":
        start_id = input_record_payload(request.inputs[0]).get("start_node_id")
        if _find_dict(data["canonical_nodes"], "node_id", start_id)["scope_id"] != scope:
            _invalid()
    elif request.operation == "resolve_lifecycle":
        historical_id = input_record_payload(request.inputs[0]).get("historical_node_id")
        if _find_dict(data["canonical_nodes"], "node_id", historical_id)["scope_id"] != scope:
            _invalid()
    elif request.operation == "structured_set_handoff":
        predicate = input_record_payload(_input(request, "typed_predicate_r1"))
        coverage = input_record_payload(_input(request, "coverage_contract_r1"))
        if predicate != _find_dict(
            data["predicates"], "predicate_id", predicate.get("predicate_id")
        ):
            _invalid()
        if coverage != _find_dict(
            data["coverage_contracts"], "coverage_contract_id", coverage.get("coverage_contract_id")
        ):
            _invalid()
        if coverage["scope_id"] != scope or coverage["predicate_id"] != predicate["predicate_id"]:
            _invalid()


def _validate_result(result: BenchmarkResult) -> None:
    if (
        result.schema_version != SCHEMA
        or result.operation not in _OPERATIONS
        or result.status not in {"success", "denied", "rejected", "partial", "timeout"}
        or result.methodology_ready is not False
        or type(result.materialization_calls) is not int
        or result.materialization_calls < 0
    ):
        _invalid()
    _require_id(result.case_id)
    payload = _json_object(result.payload_json)
    if set(payload) != {"item_ids", "paths", "structural_rows", "provenance", "lifecycle"}:
        _invalid()
    _ordered_ids(payload["item_ids"])
    lifecycle = payload["lifecycle"]
    if not isinstance(lifecycle, dict) or set(lifecycle) != {"status", "current_ids", "event_ids"}:
        _invalid()
    _ordered_ids(lifecycle["current_ids"])
    _ordered_ids(lifecycle["event_ids"])
    for path in payload["paths"]:
        _validate_path(path)
    if payload["paths"] != sorted(payload["paths"], key=_path_key) or len(
        {_json_text(item) for item in payload["paths"]}
    ) != len(payload["paths"]):
        _invalid()
    _validate_rows(payload["structural_rows"])
    _validate_provenance(payload["provenance"])
    if result.status == "denied" and (
        payload != _payload()
        or result.materialization_calls != 0
        or result.reason_code != "access_denied"
    ):
        _invalid()
    if result.status in {"rejected", "timeout"} and (
        payload != _payload() or result.materialization_calls != 0
    ):
        _invalid()
    if result.operation != "structured_set_handoff" and payload["structural_rows"]:
        _invalid()
    for value in (
        result.authority_state_fingerprint,
        result.execution_fingerprint,
        result.result_hash,
    ):
        _require_hash(value)
    if result.result_hash != _hash_without(result, "result_hash"):
        _invalid()


def _validate_result_binding(
    package: StorageEngineBenchmarkPackage, request: BenchmarkRequest, result: BenchmarkResult
) -> None:
    if (
        result.case_id != request.case_id
        or result.operation != request.operation
        or result.authority_state_fingerprint != package.authority_state.authority_state_fingerprint
        or result.execution_fingerprint != package.authority_state.execution_fingerprint
        or result.methodology_ready != package.authority_state.methodology_ready
    ):
        _invalid()
    authorization = input_record_payload(request.authorization)
    if result.status == "success" and (
        authorization["actor"]["decision"] != "allow"
        or authorization["permission"]["decision"] != "allow"
    ):
        _invalid()
    payload = result_payload(result)
    coverage_id = ""
    if request.operation == "structured_set_handoff":
        coverage_id = input_record_payload(_input(request, "coverage_contract_r1"))[
            "coverage_contract_id"
        ]
    result_ids = tuple(payload["item_ids"] + [row["row_id"] for row in payload["structural_rows"]])
    expected = _provenance(
        _fixture_mapping(package.fixture), result_ids, request.authorization, coverage_id
    )
    if payload["provenance"] != expected:
        _invalid()
    if request.operation == "bounded_traverse" and result.status == "success":
        state = _find(package.cases, "case_id", request.case_id).expected_pre_state
        if payload["paths"] != _bounded_paths(state, request):
            _invalid()


def _validate_state_shape(state: SemanticState) -> None:
    _require_hash(state.fixture_hash)
    payload = _json_object(state.state_json)
    expected = {
        "staged_candidate_ids",
        "staged_relation_ids",
        "nodes",
        "relations",
        "revision_ids",
        "lifecycle_event_ids",
        "success_audit_ids",
    }
    if set(payload) != expected:
        _invalid()
    for name in (
        "staged_candidate_ids",
        "staged_relation_ids",
        "revision_ids",
        "lifecycle_event_ids",
        "success_audit_ids",
    ):
        _ordered_ids(payload[name])
    _ordered_records(payload["nodes"], "node_id", {"node_id", "scope_id", "visible_actor_ids"})
    _ordered_records(
        payload["relations"],
        "relation_id",
        {"relation_id", "scope_id", "source_node_id", "target_node_id", "visible_actor_ids"},
    )
    for item in payload["nodes"] + payload["relations"]:
        _ordered_ids(item["visible_actor_ids"])


def _validate_state_binding(fixture: FixturePayload, state: SemanticState) -> None:
    _validate_state_shape(state)
    if state.fixture_hash != fixture.content_hash:
        _invalid()
    data, payload = _fixture_mapping(fixture), semantic_state_payload(state)
    if not set(payload["staged_candidate_ids"]) <= {
        item["candidate_id"] for item in data["candidate_nodes"]
    }:
        _invalid()
    if not set(payload["staged_relation_ids"]) <= {
        item["candidate_relation_id"] for item in data["candidate_relations"]
    }:
        _invalid()
    nodes = {
        item["node_id"]: {
            "node_id": item["node_id"],
            "scope_id": item["scope_id"],
            "visible_actor_ids": item["visible_to"],
        }
        for item in data["canonical_nodes"]
    }
    relations = {
        item["relation_id"]: {
            "relation_id": item["relation_id"],
            "scope_id": item["scope_id"],
            "source_node_id": item["source_node_id"],
            "target_node_id": item["target_node_id"],
            "visible_actor_ids": item["visible_to"],
        }
        for item in data["canonical_relations"]
    }
    if any(nodes.get(item["node_id"]) != item for item in payload["nodes"]):
        _invalid()
    if any(relations.get(item["relation_id"]) != item for item in payload["relations"]):
        _invalid()
    if not set(payload["revision_ids"]) <= {item["revision_id"] for item in data["commit_plans"]}:
        _invalid()
    if not set(payload["lifecycle_event_ids"]) <= {
        item["event_id"] for item in data["lifecycle_events"]
    }:
        _invalid()
    if not set(payload["success_audit_ids"]) <= {
        item["success_audit_id"] for item in data["commit_plans"]
    }:
        _invalid()


def _validate_path(path: Any) -> None:
    if not isinstance(path, dict) or set(path) != {"node_ids", "relation_ids"}:
        _invalid()
    _ordered_id_values(path["node_ids"], sorted_required=False)
    _ordered_id_values(path["relation_ids"], sorted_required=False)
    if (
        len(path["node_ids"]) != len(path["relation_ids"]) + 1
        or not 1 <= len(path["relation_ids"]) <= 2
        or len(set(path["node_ids"])) != len(path["node_ids"])
    ):
        _invalid()


def _validate_rows(rows: Any) -> None:
    _ordered_records(rows, "row_id", {"row_id", "scope_id", "field_name", "field_value_json"})
    for row in rows:
        if row["field_name"] != "structural_kind":
            _invalid()
        _decode_json(row["field_value_json"])


def _validate_provenance(records: Any) -> None:
    fields_expected = {
        "result_id",
        "observation_id",
        "observation_content_hash",
        "extractor_run_hash",
        "candidate_id",
        "ontology_revision_id",
        "review_decision_id",
        "scope_decision_hash",
        "coverage_contract_id",
    }
    _ordered_records(records, "result_id", fields_expected)
    for record in records:
        for name in ("observation_content_hash", "extractor_run_hash", "scope_decision_hash"):
            _require_hash(record[name])
        if record["coverage_contract_id"]:
            _require_id(record["coverage_contract_id"])


def _validate_structured_result(result: StructuredSetResult) -> None:
    payload = _json_object(result.payload_json)
    if set(payload) != {
        "predicate_id",
        "coverage_contract_id",
        "member_ids",
        "completeness_state",
        "executor_id",
        "executor_source_hash",
    }:
        _invalid()
    _ordered_ids(payload["member_ids"])
    _require_hash(payload["executor_source_hash"])
    _require_hash(result.result_hash)
    if result.result_hash != _hash_without(result, "result_hash"):
        _invalid()


def _validate_fault_result(
    package: StorageEngineBenchmarkPackage, fault: FaultRecord, actual: BenchmarkResult
) -> None:
    _validate_result(actual)
    if actual != fault.expected_result:
        _invalid()
    _validate_request_binding(package.fixture, fault.request)
    _validate_result_binding(package, fault.request, actual)
    if fault.request.operation == "structured_set_handoff" and actual.status == "success":
        _execute_structured_set(package, fault.request, actual)


def _validate_fault_execution_evidence(
    fault: FaultRecord,
    evidence: FaultExecutionEvidence | None,
    before: SemanticState,
    after: SemanticState,
) -> None:
    if evidence is None:
        _invalid()
    action = fault.action
    if (
        evidence.action_id != action.action_id
        or evidence.action_kind != action.action_kind
        or evidence.injection_point != action.injection_point
        or evidence.target_kind != action.target_kind
        or evidence.target_id != action.target_id
        or evidence.field_name != action.field_name
        or evidence.value_hash != fault_action_value_hash(action)
        or not evidence.native_transaction_started
        or not evidence.native_action_exercised
        or not evidence.transaction_rolled_back
        or evidence.pre_state_digest != semantic_state_digest(before)
        or evidence.post_state_digest != semantic_state_digest(after)
        or evidence.pre_state_digest != evidence.post_state_digest
        or evidence.evidence_hash != _hash_without(evidence, "evidence_hash")
    ):
        _invalid()


def _validate_restore_execution_evidence(
    evidence: RestoreExecutionEvidence | None,
    before: SemanticState,
    after: SemanticState,
) -> None:
    if evidence is None:
        _invalid()
    before_digest = semantic_state_digest(before)
    after_digest = semantic_state_digest(after)
    if (
        evidence.backup_state_digest != before_digest
        or evidence.restored_state_digest != after_digest
        or evidence.destructive_state_digest == before_digest
        or not evidence.native_backup_created
        or not evidence.native_destructive_mutation_observed
        or not evidence.restore_verified
        or before_digest != after_digest
        or evidence.evidence_hash != _hash_without(evidence, "evidence_hash")
    ):
        _invalid()


def _validate_authority(state: MethodologyAuthorityState) -> None:
    _require_hash(state.authority_state_fingerprint)
    _require_hash(state.execution_fingerprint)
    if (
        state.status != "blocked"
        or state.methodology_ready is not False
        or state.current_tokenizer_id != CURRENT_TOKENIZER
        or state.target_tokenizer_id != TARGET_TOKENIZER
        or type(state.require_ready_exit_code) is not int
        or state.require_ready_exit_code == 0
    ):
        _invalid()


def _validate_lock(lock: DependencyLock) -> None:
    _require_id(lock.lock_id)
    if lock.dependencies != tuple(sorted(lock.dependencies, key=lambda item: item.package_name)):
        _invalid()
    if len({item.package_name for item in lock.dependencies}) != len(lock.dependencies):
        _invalid()
    for pin in lock.dependencies:
        _require_id(pin.package_name)
        _text(pin.version)
        _require_hash(pin.artifact_hash)
    _require_hash(lock.lock_hash)
    if lock.lock_hash != _hash_without(lock, "lock_hash"):
        _invalid()


def _validate_engine(engine: EngineProfile) -> None:
    for value in (
        engine.profile_id,
        engine.engine_id,
        engine.product_name,
        engine.driver_package,
        engine.deployment_mode,
    ):
        _require_id(value)
    for value in (
        engine.product_version,
        engine.edition,
        engine.image_reference,
        engine.driver_version,
        engine.license_declaration,
    ):
        _text(value)
    for value in (engine.image_digest, engine.driver_artifact_hash, engine.profile_hash):
        _require_hash(value)
    if not engine.image_reference.endswith("@" + engine.image_digest):
        _invalid()
    settings = engine_profile_settings(engine)
    if not settings or list(settings) != sorted(settings, key=lambda item: item["setting_name"]):
        _invalid()
    if len({item["setting_name"] for item in settings}) != len(settings):
        _invalid()
    for item in settings:
        if set(item) != {"setting_name", "value_json"}:
            _invalid()
        _require_id(item["setting_name"])
        _decode_json(item["value_json"])
    if engine.index_profile.record_id != "governed_graph_indexes_r1":
        _invalid()
    if engine_profile_indexes(engine) != logical_index_declarations():
        _invalid()
    if engine.profile_hash != _hash_without(engine, "profile_hash"):
        _invalid()


def _validate_evaluator(profile: EvaluatorProfile) -> None:
    for value in (profile.evaluator_id, profile.module_id, profile.entrypoint_id):
        _require_id(value)
    if not _GIT.fullmatch(profile.source_revision):
        _invalid()
    for value in (profile.source_hash, profile.adapter_contract_hash, profile.profile_hash):
        _require_hash(value)
    if (
        profile.adapter_contract_hash != benchmark_port_contract_hash()
        or profile.profile_hash != _hash_without(profile, "profile_hash")
    ):
        _invalid()


def _input(request: BenchmarkRequest, kind: str) -> SealedInputRecord:
    matches = [item for item in request.inputs if item.record_kind == kind]
    if len(matches) != 1:
        _invalid()
    return matches[0]


def _path_key(path: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        len(path["relation_ids"]),
        path["node_ids"][-1],
        path["relation_ids"][-1],
        tuple(path["node_ids"]),
        tuple(path["relation_ids"]),
    )


def _scope(index: int) -> str:
    return "scope_alpha" if index % 2 == 0 else "scope_beta"


def _actor(index: int) -> str:
    return "actor_allow_alpha" if index % 2 == 0 else "actor_allow_beta"


def _hash_without(record: Record, field_name: str) -> str:
    payload = record.to_dict()
    payload.pop(field_name, None)
    return canonical_json_sha256(payload)


def _label_hash(*parts: Any) -> str:
    return canonical_json_sha256({"parts": list(parts)})


def _find(records: Sequence[Any], field_name: str, value: str) -> Any:
    matches = [record for record in records if getattr(record, field_name) == value]
    if len(matches) != 1:
        _invalid()
    return matches[0]


def _find_dict(
    records: Sequence[Mapping[str, Any]], field_name: str, value: Any
) -> Mapping[str, Any]:
    matches = [record for record in records if record.get(field_name) == value]
    if len(matches) != 1:
        _invalid()
    return matches[0]


def _ordered_ids(values: Any) -> None:
    _ordered_id_values(values, sorted_required=True)


def _ordered_id_values(values: Any, *, sorted_required: bool) -> None:
    if not isinstance(values, list) or len(set(values)) != len(values):
        _invalid()
    if sorted_required and values != sorted(values):
        _invalid()
    for value in values:
        _require_id(value)


def _ordered_records(records: Any, id_field: str, expected_fields: set[str]) -> None:
    if not isinstance(records, list) or any(
        not isinstance(item, dict) or set(item) != expected_fields for item in records
    ):
        _invalid()
    ids = [item[id_field] for item in records]
    _ordered_ids(ids)


def _require_id(value: Any) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        _invalid()
    return value


def _require_hash(value: Any) -> str:
    if type(value) is not str or not _HASH.fullmatch(value):
        _invalid()
    return value


def _text(value: Any) -> str:
    if type(value) is not str or not value:
        _invalid()
    _safe_values(value, "benchmark text")
    return value


def _json_text(value: Any) -> str:
    return canonical_utf8_json(value).decode("utf-8")


def _decode_json(value: Any) -> Any:
    if type(value) is not str:
        _invalid()
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        _invalid()
    if _json_text(decoded) != value:
        _invalid()
    return decoded


def _json_object(value: Any) -> dict[str, Any]:
    decoded = _decode_json(value)
    if not isinstance(decoded, dict):
        _invalid()
    return decoded


def _fixture_mapping(fixture: FixturePayload) -> dict[str, Any]:
    value = json.loads(fixture.content_json)
    if not isinstance(value, dict):
        _invalid()
    return value


T = TypeVar("T")


def _decode(record_type: type[T], value: Mapping[str, Any]) -> T:
    if not isinstance(value, Mapping) or not is_dataclass(record_type):
        _invalid()
    expected = {field.name for field in fields(record_type)}
    if set(value) != expected or any(type(key) is not str for key in value):
        _invalid()
    _safe_values(value, record_type.__name__)
    hints = get_type_hints(record_type)
    try:
        return record_type(
            **{
                field.name: _decode_value(hints[field.name], value[field.name])
                for field in fields(record_type)
            }
        )
    except TypeError:
        _invalid()


def _decode_value(annotation: Any, value: Any) -> Any:
    origin = get_origin(annotation)
    if origin is tuple:
        args = get_args(annotation)
        if type(value) is not list or len(args) != 2 or args[1] is not Ellipsis:
            _invalid()
        return tuple(_decode_value(args[0], item) for item in value)
    if origin in {Union, UnionType}:
        if value is None and type(None) in get_args(annotation):
            return None
        decoded = []
        for option in get_args(annotation):
            if option is type(None):
                continue
            try:
                decoded.append(_decode_value(option, value))
            except ContractValidationError:
                pass
        if len(decoded) != 1:
            _invalid()
        return decoded[0]
    if isinstance(annotation, type) and issubclass(annotation, Record):
        return _decode(annotation, value)
    if annotation is str and type(value) is str:
        return value
    if annotation is int and type(value) is int:
        return value
    if annotation is bool and type(value) is bool:
        return value
    _invalid()


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            _invalid()
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if value is None or type(value) in {str, int, float, bool}:
        return value
    _invalid()


def _safe_values(value: Any, context: str) -> None:
    assert_no_public_raw_references(_value_shape(value), context)


def _value_shape(value: Any) -> Any:
    if isinstance(value, Mapping):
        return [_value_shape(item) for item in value.values()]
    if isinstance(value, (list, tuple)):
        return [_value_shape(item) for item in value]
    return value


def _invalid() -> None:
    raise ContractValidationError("storage benchmark contract is invalid")


__all__ = [
    "BenchmarkComparison",
    "BenchmarkRequest",
    "BenchmarkResult",
    "CaseVerification",
    "DependencyLock",
    "DependencyPin",
    "EngineProfile",
    "EvaluatorProfile",
    "FaultAction",
    "FaultRecord",
    "FaultVerification",
    "FixturePayload",
    "GovernedGraphBenchmarkControl",
    "GovernedGraphBenchmarkExecutionPort",
    "GovernedGraphBenchmarkStore",
    "MethodologyAuthorityState",
    "ResourceProfile",
    "SealedCase",
    "SealedInputRecord",
    "SealedPackageGate",
    "SemanticState",
    "StorageEngineBenchmarkPackage",
    "StorageEngineBenchmarkRequest",
    "StorageEngineBenchmarkResult",
    "StructuredSetResult",
    "benchmark_port_contract_hash",
    "benchmark_result_digest",
    "canonical_json_sha256",
    "canonical_utf8_json",
    "compare_benchmark_results",
    "engine_profile_indexes",
    "engine_profile_settings",
    "engine_setting",
    "execute_fault_conformance",
    "execute_store_request",
    "execute_structured_set",
    "fault_for_action",
    "fixture_counts",
    "fixture_data",
    "generate_source_free_fixture",
    "generate_storage_engine_benchmark_package",
    "initial_semantic_state",
    "input_record_payload",
    "logical_index_declarations",
    "methodology_authority_state_from_check",
    "reference_execute_request",
    "request_input_payload",
    "reseal_benchmark_request",
    "reseal_benchmark_result",
    "resource_profile_r1",
    "result_payload",
    "seal_dependency_lock",
    "seal_engine_profile",
    "seal_evaluator_profile",
    "seal_input_record",
    "seal_semantic_state",
    "semantic_state_digest",
    "semantic_state_payload",
    "structured_set_payload",
    "transition_semantic_state",
    "traversal_contract",
    "validate_benchmark_package",
    "validate_package_request_result",
    "verify_case_execution",
]
