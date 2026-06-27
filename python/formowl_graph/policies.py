from __future__ import annotations

from typing import Any

from formowl_contract import (
    AtomGranularityPolicy,
    ContractValidationError,
    EntityResolutionPolicy,
    ExtractionPolicy,
    LifecyclePolicy,
    RelationResolutionPolicy,
    WikiProjectionPolicy,
    sha256_json,
)

PolicyContract = (
    ExtractionPolicy
    | AtomGranularityPolicy
    | EntityResolutionPolicy
    | RelationResolutionPolicy
    | LifecyclePolicy
    | WikiProjectionPolicy
)

_POLICY_KIND_BY_TYPE = {
    ExtractionPolicy: "extraction",
    AtomGranularityPolicy: "atom_granularity",
    EntityResolutionPolicy: "entity_resolution",
    RelationResolutionPolicy: "relation_resolution",
    LifecyclePolicy: "lifecycle",
    WikiProjectionPolicy: "wiki_projection",
}


def policy_kind(policy: PolicyContract) -> str:
    try:
        return _POLICY_KIND_BY_TYPE[type(policy)]
    except KeyError as exc:
        raise ContractValidationError("unsupported policy contract type") from exc


def policy_contract_hash(policy: PolicyContract) -> str:
    return sha256_json(policy.to_dict())


def policy_version_ref(policy: PolicyContract) -> dict[str, Any]:
    payload = policy.to_dict()
    return {
        "policy_id": payload["policy_id"],
        "policy_kind": policy_kind(policy),
        "policy_version": payload["policy_version"],
        "scope_type": payload["scope_type"],
        "scope_id": payload["scope_id"],
        "status": payload["status"],
        "contract_hash": policy_contract_hash(policy),
    }


def require_active_policy(policy: PolicyContract, *, expected_kind: str) -> dict[str, Any]:
    ref = policy_version_ref(policy)
    if ref["policy_kind"] != expected_kind:
        raise ContractValidationError("policy kind does not match expected kind")
    if ref["status"] != "active":
        raise ContractValidationError("policy must be active")
    return ref
