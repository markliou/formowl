#!/usr/bin/env python3
"""Run a non-claim-bearing Issue #56 prompt-to-MCP Hybrid diagnostic."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_contract import ContractValidationError, assert_no_public_raw_references, sha256_json  # noqa: E402
from formowl_core import DenseEmbeddingUnavailableError  # noqa: E402
from formowl_gateway.issue56_diagnostic import (  # noqa: E402
    ISSUE56_DIAGNOSTIC_ARTIFACT_ID,
    ISSUE56_DIAGNOSTIC_DEFAULT_PROMPT,
    ISSUE56_DIAGNOSTIC_IDENTITY_SCOPE_MODE,
    ISSUE56_DIAGNOSTIC_USER_ID,
    ISSUE56_DIAGNOSTIC_WORKSPACE_ID,
    ISSUE56_REAL_PROMPT_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
    ISSUE56_RELATION_PROJECTION_EQUIVALENCE_DIAGNOSTIC_MODE_ID,
    ISSUE56_RELATION_PROJECTION_EQUIVALENCE_LOADER_CONTRACT_ID,
    ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_DIAGNOSTIC_MODE_ID,
    ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_LOADER_CONTRACT_ID,
    ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_DIAGNOSTIC_MODE_ID,
    ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_LOADER_CONTRACT_ID,
    ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
    ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V1_MODE_ID,
    ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V2_MODE_ID,
    ISSUE56_SYNTHETIC_DIAGNOSTIC_MODE_ID,
    Issue56DiagnosticComposition,
    Issue56SealedSourceDiagnosticInput,
    build_issue56_diagnostic_composition,
    build_issue56_relation_projection_equivalence_compositions,
    build_issue56_relation_projection_equivalence_v6_compositions,
    build_issue56_relation_projection_offline_equivalence_v7_compositions,
    build_safe_diagnostic_report,
    build_safe_relation_projection_equivalence_arm,
    build_safe_relation_projection_equivalence_report,
    build_safe_relation_projection_offline_equivalence_v7_report,
    mcp_headers,
    mcp_initialize_request,
    mcp_list_tools_request,
    mcp_query_request,
    relation_projection_cache_containers_are_isolated,
    relation_projection_cache_evidence,
    precompute_issue56_offline_relation_projection_base,
    safe_blocked_report,
)
from starlette.testclient import TestClient  # noqa: E402


_REAL_PROMPT_CONSUMED_CLAIM_ARTIFACT_ID = (
    "formowl_issue56_real_prompt_sealed_source_diagnostic_consumed_claim_v4"
)
_REAL_PROMPT_CONSUMED_CLAIM_SCHEMA_VERSION = 4
_RELATION_PROJECTION_EQUIVALENCE_CONSUMED_CLAIM_ARTIFACT_ID = (
    "formowl_issue56_relation_projection_equivalence_consumed_claim_v5"
)
_RELATION_PROJECTION_EQUIVALENCE_CONSUMED_CLAIM_SCHEMA_VERSION = 5
_RELATION_PROJECTION_EQUIVALENCE_V6_CONSUMED_CLAIM_ARTIFACT_ID = (
    "formowl_issue56_relation_projection_equivalence_consumed_claim_v6"
)
_RELATION_PROJECTION_EQUIVALENCE_V6_CONSUMED_CLAIM_SCHEMA_VERSION = 6
_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_CONSUMED_CLAIM_ARTIFACT_ID = (
    "formowl_issue56_relation_projection_offline_equivalence_consumed_claim_v7"
)
_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_CONSUMED_CLAIM_SCHEMA_VERSION = 7
_LOADER_SPEC_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$")
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class _ConsumedClaimReceipt:
    claim_fingerprint: str
    byte_sha256: str
    execution_binding_fingerprint: str


@dataclass(frozen=True)
class _RelationProjectionEquivalenceVersionContract:
    diagnostic_mode_id: str
    loader_contract_id: str
    claim_artifact_id: str
    claim_schema_version: int
    enforce_repository_state_root: bool
    preseal_graph_content: bool = False
    offline_equivalence: bool = False


@dataclass(frozen=True)
class _DiagnosticHttpExchange:
    initialize_response: Mapping[str, Any]
    list_response: Mapping[str, Any]
    query_response: Mapping[str, Any]
    elapsed_ms: float


_RELATION_PROJECTION_EQUIVALENCE_V5_CONTRACT = _RelationProjectionEquivalenceVersionContract(
    diagnostic_mode_id=(ISSUE56_RELATION_PROJECTION_EQUIVALENCE_DIAGNOSTIC_MODE_ID),
    loader_contract_id=(ISSUE56_RELATION_PROJECTION_EQUIVALENCE_LOADER_CONTRACT_ID),
    claim_artifact_id=(_RELATION_PROJECTION_EQUIVALENCE_CONSUMED_CLAIM_ARTIFACT_ID),
    claim_schema_version=(_RELATION_PROJECTION_EQUIVALENCE_CONSUMED_CLAIM_SCHEMA_VERSION),
    enforce_repository_state_root=True,
)
_RELATION_PROJECTION_EQUIVALENCE_V6_CONTRACT = _RelationProjectionEquivalenceVersionContract(
    diagnostic_mode_id=(ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_DIAGNOSTIC_MODE_ID),
    loader_contract_id=(ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_LOADER_CONTRACT_ID),
    claim_artifact_id=(_RELATION_PROJECTION_EQUIVALENCE_V6_CONSUMED_CLAIM_ARTIFACT_ID),
    claim_schema_version=(_RELATION_PROJECTION_EQUIVALENCE_V6_CONSUMED_CLAIM_SCHEMA_VERSION),
    enforce_repository_state_root=True,
    preseal_graph_content=True,
)
_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_CONTRACT = (
    _RelationProjectionEquivalenceVersionContract(
        diagnostic_mode_id=(ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_DIAGNOSTIC_MODE_ID),
        loader_contract_id=(ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_LOADER_CONTRACT_ID),
        claim_artifact_id=(_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_CONSUMED_CLAIM_ARTIFACT_ID),
        claim_schema_version=(
            _RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_CONSUMED_CLAIM_SCHEMA_VERSION
        ),
        enforce_repository_state_root=True,
        preseal_graph_content=True,
        offline_equivalence=True,
    )
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=(
            ISSUE56_SYNTHETIC_DIAGNOSTIC_MODE_ID,
            ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V1_MODE_ID,
            ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V2_MODE_ID,
            ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
            ISSUE56_REAL_PROMPT_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
            ISSUE56_RELATION_PROJECTION_EQUIVALENCE_DIAGNOSTIC_MODE_ID,
            ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_DIAGNOSTIC_MODE_ID,
            ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_DIAGNOSTIC_MODE_ID,
        ),
        default=ISSUE56_SYNTHETIC_DIAGNOSTIC_MODE_ID,
    )
    parser.add_argument(
        "--prompt",
        default=None,
        help=(
            "Synthetic-only prompt override; raw value is never emitted. "
            "The sealed mode rejects this option."
        ),
    )
    parser.add_argument(
        "--sealed-source-loader",
        default=None,
        help=("Sealed mode only: module:function returning " "Issue56SealedSourceDiagnosticInput."),
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        default=None,
        help=(
            "Persistent sealed-mode directory for the immutable consumed claim " "and safe report."
        ),
    )
    args = parser.parse_args(argv)
    version_consumed = False
    try:
        if args.mode in {
            ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V1_MODE_ID,
            ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V2_MODE_ID,
            ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
            ISSUE56_REAL_PROMPT_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
            ISSUE56_RELATION_PROJECTION_EQUIVALENCE_DIAGNOSTIC_MODE_ID,
            ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_DIAGNOSTIC_MODE_ID,
        }:
            raise ContractValidationError(
                "sealed diagnostic version is immutable and already consumed"
            )
        if args.mode == ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_DIAGNOSTIC_MODE_ID:
            if args.prompt is not None:
                raise ContractValidationError(
                    "sealed diagnostic prompt is repository-owned and immutable"
                )
            if not args.sealed_source_loader or args.state_root is None:
                raise ContractValidationError(
                    "sealed diagnostic loader and state root are required"
                )
            loader = resolve_sealed_source_loader(args.sealed_source_loader)
            report = run_relation_projection_offline_equivalence_v7_diagnostic_once(
                loader=loader,
                loader_spec_fingerprint=sha256_json(
                    {
                        "loader_contract_id": (
                            ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_LOADER_CONTRACT_ID
                        ),
                        "loader_spec": args.sealed_source_loader,
                    }
                ),
                state_root=args.state_root,
            )
        else:
            if args.sealed_source_loader is not None or args.state_root is not None:
                raise ContractValidationError(
                    "synthetic diagnostic cannot use sealed-source arguments"
                )
            report = run_diagnostic(args.prompt or ISSUE56_DIAGNOSTIC_DEFAULT_PROMPT)
    except DenseEmbeddingUnavailableError as exc:
        if args.mode == ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_DIAGNOSTIC_MODE_ID:
            version_consumed = _relation_projection_equivalence_claim_exists(
                args.state_root,
                contract=_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_CONTRACT,
            )
        report = safe_blocked_report(
            exc.reason_code,
            diagnostic_mode_id=args.mode,
            version_consumed=version_consumed,
        )
    except Exception as exc:
        if args.mode in {
            ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V1_MODE_ID,
            ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V2_MODE_ID,
            ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
            ISSUE56_REAL_PROMPT_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
            ISSUE56_RELATION_PROJECTION_EQUIVALENCE_DIAGNOSTIC_MODE_ID,
            ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_DIAGNOSTIC_MODE_ID,
        }:
            version_consumed = True
        elif args.mode == ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_DIAGNOSTIC_MODE_ID:
            version_consumed = _relation_projection_equivalence_claim_exists(
                args.state_root,
                contract=_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_CONTRACT,
            )
        report = safe_blocked_report(
            type(exc).__name__,
            diagnostic_mode_id=args.mode,
            version_consumed=version_consumed,
        )
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 2


def run_diagnostic(prompt: str) -> dict[str, Any]:
    """Run the repeatable synthetic diagnostic compatibility mode."""

    composition = build_issue56_diagnostic_composition()
    return _run_http_diagnostic(
        composition=composition,
        prompt=prompt,
    )


def run_sealed_source_diagnostic_once(
    *,
    loader: Callable[[], Issue56SealedSourceDiagnosticInput],
    loader_spec_fingerprint: str,
    state_root: Path,
) -> dict[str, Any]:
    """Reject the immutable, already-consumed v3 execution boundary."""

    del loader, loader_spec_fingerprint, state_root
    raise ContractValidationError("sealed diagnostic version is immutable and already consumed")


def run_real_prompt_sealed_source_diagnostic_once(
    *,
    loader: Callable[[], Issue56SealedSourceDiagnosticInput],
    loader_spec_fingerprint: str,
    state_root: Path,
) -> dict[str, Any]:
    """Reject the immutable, already-consumed v4 execution boundary."""

    del loader, loader_spec_fingerprint, state_root
    raise ContractValidationError("sealed diagnostic version is immutable and already consumed")


def run_relation_projection_equivalence_diagnostic_once(
    *,
    loader: Callable[[], Issue56SealedSourceDiagnosticInput],
    loader_spec_fingerprint: str,
    state_root: Path,
) -> dict[str, Any]:
    """Reject the immutable, already-consumed v5 execution boundary."""

    expected_state_root = (
        ROOT
        / ".test-tmp"
        / f"{_RELATION_PROJECTION_EQUIVALENCE_V5_CONTRACT.diagnostic_mode_id}-state"
    ).resolve()
    if state_root.resolve() != expected_state_root:
        raise ContractValidationError("relation projection diagnostic state root mismatch")
    del loader, loader_spec_fingerprint
    raise ContractValidationError("sealed diagnostic version is immutable and already consumed")


def run_relation_projection_equivalence_v6_diagnostic_once(
    *,
    loader: Callable[[], Issue56SealedSourceDiagnosticInput],
    loader_spec_fingerprint: str,
    state_root: Path,
) -> dict[str, Any]:
    """Reject the immutable, already-consumed v6 execution boundary."""

    expected_state_root = (
        ROOT
        / ".test-tmp"
        / f"{_RELATION_PROJECTION_EQUIVALENCE_V6_CONTRACT.diagnostic_mode_id}-state"
    ).resolve()
    if state_root.resolve() != expected_state_root:
        raise ContractValidationError("relation projection diagnostic state root mismatch")
    del loader, loader_spec_fingerprint
    raise ContractValidationError("sealed diagnostic version is immutable and already consumed")


def run_relation_projection_offline_equivalence_v7_diagnostic_once(
    *,
    loader: Callable[[], Issue56SealedSourceDiagnosticInput],
    loader_spec_fingerprint: str,
    state_root: Path,
) -> dict[str, Any]:
    """Execute the official v7 contract once at its canonical state root."""

    return _run_relation_projection_equivalence_diagnostic_once(
        loader=loader,
        loader_spec_fingerprint=loader_spec_fingerprint,
        state_root=state_root,
        contract=_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_CONTRACT,
    )


def _run_relation_projection_equivalence_diagnostic_once(
    *,
    loader: Callable[[], Issue56SealedSourceDiagnosticInput],
    loader_spec_fingerprint: str,
    state_root: Path,
    contract: _RelationProjectionEquivalenceVersionContract,
) -> dict[str, Any]:
    """Preflight both arms, consume once, execute both HTTP paths, publish once."""

    if not callable(loader):
        raise ContractValidationError("sealed diagnostic loader is not callable")
    _require_sha256(
        loader_spec_fingerprint,
        "sealed diagnostic loader spec fingerprint",
    )
    _validate_relation_projection_equivalence_version_contract(contract)
    if contract.enforce_repository_state_root:
        expected_state_root = (
            ROOT / ".test-tmp" / f"{contract.diagnostic_mode_id}-state"
        ).resolve()
        if state_root.resolve() != expected_state_root:
            raise ContractValidationError("relation projection diagnostic state root mismatch")
    defer_formal_v7_state_root = (
        contract.offline_equivalence and contract.enforce_repository_state_root
    )
    if defer_formal_v7_state_root:
        if state_root.exists() or state_root.is_symlink():
            raise ContractValidationError(
                "relation projection diagnostic state root already exists"
            )
    else:
        state_root = _prepare_state_root(state_root)
    claim_path, output_path = _relation_projection_equivalence_paths(
        state_root,
        contract=contract,
    )
    if claim_path.exists() or claim_path.is_symlink():
        raise ContractValidationError("sealed diagnostic version is already consumed")
    if output_path.exists() or output_path.is_symlink():
        raise ContractValidationError("sealed diagnostic output already exists")

    source_load_started_at = time.perf_counter()
    source = loader()
    source_loader_elapsed_ms = (time.perf_counter() - source_load_started_at) * 1_000.0
    if not isinstance(source, Issue56SealedSourceDiagnosticInput):
        raise ContractValidationError("sealed diagnostic loader returned an unsupported contract")
    if (
        source.diagnostic_mode_id != contract.diagnostic_mode_id
        or source.private_prompt is None
        or source.prompt_selection is None
    ):
        raise ContractValidationError("relation projection diagnostic loader contract mismatch")
    graph_content_preseal = None
    offline_preflight = None
    if contract.offline_equivalence:
        (
            before,
            after,
            offline_preflight,
        ) = build_issue56_relation_projection_offline_equivalence_v7_compositions(source)
    elif contract.preseal_graph_content:
        (
            before,
            after,
            graph_content_preseal,
        ) = build_issue56_relation_projection_equivalence_v6_compositions(source)
    else:
        before, after = build_issue56_relation_projection_equivalence_compositions(source)
    prompt_hash = sha256_json(source.private_prompt)
    if prompt_hash != source.prompt_selection.prompt_hash:
        raise ContractValidationError("relation projection diagnostic prompt binding mismatch")
    cache_containers_isolated = relation_projection_cache_containers_are_isolated(before, after)
    before_cache_before = relation_projection_cache_evidence(before)
    after_cache_before = relation_projection_cache_evidence(after)
    if (
        not cache_containers_isolated
        or before_cache_before["entry_count"] != 0
        or before_cache_before["expected_binding_present"]
        or before_cache_before["binding_snapshot_entry_count"] != 0
        or before_cache_before["expected_binding_snapshot_present"]
        or after_cache_before["entry_count"] != 1
        or not after_cache_before["expected_binding_present"]
        or after_cache_before["binding_snapshot_entry_count"] != 1
        or not after_cache_before["expected_binding_snapshot_present"]
        or (
            contract.preseal_graph_content
            and not contract.offline_equivalence
            and (
                graph_content_preseal is None
                or graph_content_preseal.status != "passed"
                or graph_content_preseal.before_binding_cache_entry_count != 0
                or graph_content_preseal.before_base_cache_entry_count != 0
                or graph_content_preseal.after_binding_cache_entry_count != 1
                or graph_content_preseal.after_base_cache_entry_count != 1
            )
        )
        or (
            contract.offline_equivalence
            and (
                offline_preflight is None
                or offline_preflight.status != "passed"
                or offline_preflight.cold_binding_cache_entry_count != 0
                or offline_preflight.cold_base_cache_entry_count != 0
                or offline_preflight.after_binding_cache_entry_count != 1
                or offline_preflight.after_base_cache_entry_count != 1
                or before.state.hybrid_query_count != 0
                or after.state.hybrid_query_count != 0
                or before.state.authentication_count != 0
                or after.state.authentication_count != 0
            )
        )
    ):
        raise ContractValidationError("relation projection diagnostic cache preflight mismatch")
    arm_order = (
        ["offline_cold_precomputed", "preexisting_precomputed"]
        if contract.offline_equivalence
        else ["before_cold", "after_precomputed"]
    )
    execution_binding_fingerprint = sha256_json(
        {
            "schema_version": contract.claim_schema_version,
            "artifact_id": ISSUE56_DIAGNOSTIC_ARTIFACT_ID,
            "diagnostic_mode_id": contract.diagnostic_mode_id,
            "prompt_hash": prompt_hash,
            "selection_proof_fingerprint": (source.prompt_selection.selection_proof_fingerprint),
            "source_binding_fingerprint": source.source_binding_fingerprint,
            "permission_lineage_fingerprint": (source.permission_lineage_fingerprint),
            "effective_graph_view_fingerprint": (source.effective_graph_view_fingerprint),
            "graph_revision_fingerprint": source.graph_revision_fingerprint,
            "index_fingerprint": source.session.index.index_fingerprint,
            "relation_projection_base_precompute_fingerprint": (
                source.relation_projection_base_precompute.precompute_fingerprint
            ),
            "relation_projection_cache_binding_fingerprint": (
                source.relation_projection_base_precompute.cache_binding_fingerprint
            ),
            "graph_content_preseal_fingerprint": (
                graph_content_preseal.evidence_binding_fingerprint
                if graph_content_preseal is not None
                else None
            ),
            "offline_preflight_fingerprint": (
                offline_preflight.evidence_binding_fingerprint
                if offline_preflight is not None
                else None
            ),
            "user_query_time_budget_ms": (1500 if contract.offline_equivalence else None),
            "offline_precompute_consumes_query_budget": (
                False if contract.offline_equivalence else None
            ),
            "identity_scope_mode": ISSUE56_DIAGNOSTIC_IDENTITY_SCOPE_MODE,
            "workspace_id": ISSUE56_DIAGNOSTIC_WORKSPACE_ID,
            "approver_user_id": ISSUE56_DIAGNOSTIC_USER_ID,
            "loader_contract_id": contract.loader_contract_id,
            "loader_spec_fingerprint": loader_spec_fingerprint,
            "arm_order": arm_order,
        }
    )
    claim = {
        "artifact_id": contract.claim_artifact_id,
        "schema_version": contract.claim_schema_version,
        "status": "consumed",
        "claim_boundary": ("diagnostic_only_not_quality_or_methodology_evidence"),
        "diagnostic_mode_id": contract.diagnostic_mode_id,
        "prompt_hash": prompt_hash,
        "selection_proof_fingerprint": (source.prompt_selection.selection_proof_fingerprint),
        "source_binding_fingerprint": source.source_binding_fingerprint,
        "permission_lineage_fingerprint": (source.permission_lineage_fingerprint),
        "graph_content_preseal_fingerprint": (
            graph_content_preseal.evidence_binding_fingerprint
            if graph_content_preseal is not None
            else None
        ),
        "offline_preflight_fingerprint": (
            offline_preflight.evidence_binding_fingerprint
            if offline_preflight is not None
            else None
        ),
        "identity_scope_mode": ISSUE56_DIAGNOSTIC_IDENTITY_SCOPE_MODE,
        "identity_scope_fingerprint": sha256_json(
            {
                "identity_scope_mode": ISSUE56_DIAGNOSTIC_IDENTITY_SCOPE_MODE,
                "workspace_id": ISSUE56_DIAGNOSTIC_WORKSPACE_ID,
                "approver_user_id": ISSUE56_DIAGNOSTIC_USER_ID,
            }
        ),
        "loader_contract_id": contract.loader_contract_id,
        "loader_spec_fingerprint": loader_spec_fingerprint,
        "execution_binding_fingerprint": execution_binding_fingerprint,
        "arm_count": 2,
    }
    claim["claim_fingerprint"] = sha256_json(claim)
    assert_no_public_raw_references(claim, contract.claim_artifact_id)
    _assert_no_legacy_identity_fields(claim)
    if defer_formal_v7_state_root:
        state_root = _prepare_state_root(state_root)
        claim_path, output_path = _relation_projection_equivalence_paths(
            state_root,
            contract=contract,
        )
        if (
            claim_path.exists()
            or claim_path.is_symlink()
            or output_path.exists()
            or output_path.is_symlink()
        ):
            raise ContractValidationError("sealed diagnostic immutable artifact already exists")
    claim_byte_sha256 = _atomic_publish_json_once(claim_path, claim)
    receipt = _ConsumedClaimReceipt(
        claim_fingerprint=claim["claim_fingerprint"],
        byte_sha256=claim_byte_sha256,
        execution_binding_fingerprint=execution_binding_fingerprint,
    )

    offline_precompute = None
    if contract.offline_equivalence:
        offline_precompute = precompute_issue56_offline_relation_projection_base(before)
        before_cache_before = relation_projection_cache_evidence(before)
        after_cache_before = relation_projection_cache_evidence(after)
        if (
            before_cache_before["binding_snapshot_entry_count"] != 1
            or before_cache_before["entry_count"] != 1
            or not before_cache_before["expected_binding_snapshot_present"]
            or not before_cache_before["expected_binding_present"]
            or after_cache_before["binding_snapshot_entry_count"] != 1
            or after_cache_before["entry_count"] != 1
            or not after_cache_before["expected_binding_snapshot_present"]
            or not after_cache_before["expected_binding_present"]
        ):
            raise ContractValidationError("relation projection offline precompute cache mismatch")

    before_exchange = _execute_http_diagnostic_exchange(
        composition=before,
        prompt=source.private_prompt,
    )
    before_cache_after = relation_projection_cache_evidence(before)
    before_arm = build_safe_relation_projection_equivalence_arm(
        arm_id=("offline_cold_precomputed" if contract.offline_equivalence else "before_cold"),
        composition=before,
        prompt=source.private_prompt,
        initialize_response=before_exchange.initialize_response,
        list_response=before_exchange.list_response,
        query_response=before_exchange.query_response,
        http_elapsed_ms=before_exchange.elapsed_ms,
        cache_before=before_cache_before,
        cache_after=before_cache_after,
    )

    after_exchange = _execute_http_diagnostic_exchange(
        composition=after,
        prompt=source.private_prompt,
    )
    after_cache_after = relation_projection_cache_evidence(after)
    after_arm = build_safe_relation_projection_equivalence_arm(
        arm_id=("preexisting_precomputed" if contract.offline_equivalence else "after_precomputed"),
        composition=after,
        prompt=source.private_prompt,
        initialize_response=after_exchange.initialize_response,
        list_response=after_exchange.list_response,
        query_response=after_exchange.query_response,
        http_elapsed_ms=after_exchange.elapsed_ms,
        cache_before=after_cache_before,
        cache_after=after_cache_after,
    )
    if contract.offline_equivalence:
        if offline_preflight is None or offline_precompute is None:
            raise ContractValidationError("relation projection offline evidence is unavailable")
        report = build_safe_relation_projection_offline_equivalence_v7_report(
            source=source,
            prompt=source.private_prompt,
            cold_arm=before_arm,
            after_arm=after_arm,
            source_loader_elapsed_ms=source_loader_elapsed_ms,
            consumed_claim_fingerprint=receipt.claim_fingerprint,
            consumed_claim_byte_sha256=receipt.byte_sha256,
            execution_binding_fingerprint=(receipt.execution_binding_fingerprint),
            cache_containers_isolated=(
                relation_projection_cache_containers_are_isolated(before, after)
            ),
            preflight=offline_preflight,
            offline_precompute=offline_precompute,
        )
    else:
        report = build_safe_relation_projection_equivalence_report(
            source=source,
            prompt=source.private_prompt,
            before_arm=before_arm,
            after_arm=after_arm,
            source_loader_elapsed_ms=source_loader_elapsed_ms,
            consumed_claim_fingerprint=receipt.claim_fingerprint,
            consumed_claim_byte_sha256=receipt.byte_sha256,
            execution_binding_fingerprint=(receipt.execution_binding_fingerprint),
            cache_containers_isolated=(
                relation_projection_cache_containers_are_isolated(before, after)
            ),
            graph_content_preseal=graph_content_preseal,
        )
    _atomic_publish_json_once(output_path, report)
    return report


def resolve_sealed_source_loader(
    loader_spec: str,
) -> Callable[[], Issue56SealedSourceDiagnosticInput]:
    """Resolve the narrow Worker-A adapter without accepting file paths."""

    if not isinstance(loader_spec, str) or not _LOADER_SPEC_PATTERN.fullmatch(loader_spec):
        raise ContractValidationError("sealed diagnostic loader spec is invalid")
    module_name, attribute_name = loader_spec.split(":", 1)
    module = importlib.import_module(module_name)
    loader = getattr(module, attribute_name, None)
    if not callable(loader):
        raise ContractValidationError("sealed diagnostic loader callable is unavailable")
    return loader


def _run_http_diagnostic(
    *,
    composition: Issue56DiagnosticComposition,
    prompt: str,
    source_loader_elapsed_ms: float | None = None,
    consumed_claim: _ConsumedClaimReceipt | None = None,
) -> dict[str, Any]:
    exchange = _execute_http_diagnostic_exchange(
        composition=composition,
        prompt=prompt,
    )
    return build_safe_diagnostic_report(
        composition=composition,
        prompt=prompt,
        initialize_response=exchange.initialize_response,
        list_response=exchange.list_response,
        query_response=exchange.query_response,
        http_elapsed_ms=exchange.elapsed_ms,
        source_loader_elapsed_ms=source_loader_elapsed_ms,
        consumed_claim_fingerprint=(
            consumed_claim.claim_fingerprint if consumed_claim is not None else None
        ),
        consumed_claim_byte_sha256=(
            consumed_claim.byte_sha256 if consumed_claim is not None else None
        ),
        execution_binding_fingerprint=(
            consumed_claim.execution_binding_fingerprint if consumed_claim is not None else None
        ),
    )


def _execute_http_diagnostic_exchange(
    *,
    composition: Issue56DiagnosticComposition,
    prompt: str,
) -> _DiagnosticHttpExchange:
    started_at = time.perf_counter()
    with TestClient(
        composition.application.app,
        raise_server_exceptions=False,
    ) as client:
        initialized = client.post(
            "/mcp",
            json=mcp_initialize_request(),
            headers=mcp_headers(),
        )
        listed = client.post(
            "/mcp",
            json=mcp_list_tools_request(),
            headers=mcp_headers(),
        )
        queried = client.post(
            "/mcp",
            json=mcp_query_request(prompt),
            headers=mcp_headers(bearer=composition.bearer_token),
        )
    elapsed_ms = (time.perf_counter() - started_at) * 1_000.0
    if initialized.status_code != 200:
        raise RuntimeError("diagnostic_initialize_http_failed")
    if listed.status_code != 200:
        raise RuntimeError("diagnostic_list_http_failed")
    if queried.status_code != 200:
        raise RuntimeError("diagnostic_query_http_failed")
    return _DiagnosticHttpExchange(
        initialize_response=initialized.json(),
        list_response=listed.json(),
        query_response=queried.json(),
        elapsed_ms=elapsed_ms,
    )


def _prepare_state_root(state_root: Path) -> Path:
    if not isinstance(state_root, Path):
        raise ContractValidationError("sealed diagnostic state root is invalid")
    state_root.mkdir(parents=True, exist_ok=True)
    if state_root.is_symlink() or not state_root.is_dir():
        raise ContractValidationError("sealed diagnostic state root is unsafe")
    return state_root


def _sealed_paths(state_root: Path) -> tuple[Path, Path]:
    stem = ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID
    return (
        state_root / f"{stem}.consumed.safe.json",
        state_root / f"{stem}.safe.json",
    )


def _real_prompt_sealed_paths(state_root: Path) -> tuple[Path, Path]:
    stem = ISSUE56_REAL_PROMPT_SEALED_SOURCE_DIAGNOSTIC_MODE_ID
    return (
        state_root / f"{stem}.consumed.safe.json",
        state_root / f"{stem}.safe.json",
    )


def _relation_projection_equivalence_paths(
    state_root: Path,
    *,
    contract: _RelationProjectionEquivalenceVersionContract = (
        _RELATION_PROJECTION_EQUIVALENCE_V5_CONTRACT
    ),
) -> tuple[Path, Path]:
    stem = contract.diagnostic_mode_id
    return (
        state_root / f"{stem}.consumed.safe.json",
        state_root / f"{stem}.safe.json",
    )


def _sealed_claim_exists(state_root: Path | None) -> bool:
    if state_root is None or not isinstance(state_root, Path):
        return False
    claim_path, _ = _sealed_paths(state_root)
    return claim_path.exists() or claim_path.is_symlink()


def _real_prompt_sealed_claim_exists(state_root: Path | None) -> bool:
    if state_root is None or not isinstance(state_root, Path):
        return False
    claim_path, _ = _real_prompt_sealed_paths(state_root)
    return claim_path.exists() or claim_path.is_symlink()


def _relation_projection_equivalence_claim_exists(
    state_root: Path | None,
    *,
    contract: _RelationProjectionEquivalenceVersionContract,
) -> bool:
    if state_root is None or not isinstance(state_root, Path):
        return False
    claim_path, _ = _relation_projection_equivalence_paths(
        state_root,
        contract=contract,
    )
    return claim_path.exists() or claim_path.is_symlink()


def _validate_relation_projection_equivalence_version_contract(
    contract: _RelationProjectionEquivalenceVersionContract,
) -> None:
    if (
        not isinstance(contract, _RelationProjectionEquivalenceVersionContract)
        or not isinstance(contract.diagnostic_mode_id, str)
        or not contract.diagnostic_mode_id
        or not isinstance(contract.loader_contract_id, str)
        or not contract.loader_contract_id
        or not isinstance(contract.claim_artifact_id, str)
        or not contract.claim_artifact_id
        or type(contract.claim_schema_version) is not int
        or contract.claim_schema_version <= 0
        or type(contract.preseal_graph_content) is not bool
        or type(contract.offline_equivalence) is not bool
    ):
        raise ContractValidationError("relation projection diagnostic version contract is invalid")
    if contract.enforce_repository_state_root and (
        contract != _RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_CONTRACT
    ):
        raise ContractValidationError("relation projection diagnostic production contract mismatch")
    if contract.offline_equivalence and not contract.preseal_graph_content:
        raise ContractValidationError(
            "relation projection offline diagnostic requires graph preseal"
        )


def _atomic_publish_json_once(path: Path, payload: Mapping[str, Any]) -> str:
    encoded = (json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise ContractValidationError(
                "sealed diagnostic immutable artifact already exists"
            ) from exc
        directory_descriptor = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _require_sha256(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise ContractValidationError(f"{label} is invalid")


def _assert_no_legacy_identity_fields(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in {"tenant", "tenant_id"}:
                raise ContractValidationError("legacy identity field is forbidden")
            _assert_no_legacy_identity_fields(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_no_legacy_identity_fields(item)


if __name__ == "__main__":
    raise SystemExit(main())
