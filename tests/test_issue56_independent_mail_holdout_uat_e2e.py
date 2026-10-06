from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

import _paths  # noqa: F401
from formowl_contract import (
    Observation,
    SourceInventory,
    sha256_json,
)
from formowl_core import ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT
from formowl_mail import (
    DeterministicExactExecutionResult,
    ExactCoverageContract,
    ExactInventoryItem,
)
from formowl_mail.candidates import (
    TENANT_WORKSPACE_IDENTITY_SCOPE_MODE,
    WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
    SourceIdentifierIdentityScope,
)
from scripts import issue56_simulated_uat as development_uat
from scripts import issue56_independent_mail_holdout_uat as holdout_uat
from scripts import issue56_holdout_source_author_projection_inputs as source_author_projection
from scripts import issue56_source_independent_mail_holdout_extension as extension_author
from scripts.issue56_independent_mail_holdout_uat import (
    EXPECTED_CASE_COUNT,
    IndependentMailHoldoutUatError,
    _DevelopmentAcceptance,
    _HoldoutExecutionContext,
    _adapt_holdout_case_for_development_helpers,
    _build_runtime_binding,
    _execute_independent_holdout_once,
    _validate_development_acceptance,
    _validate_pre_holdout_authority,
    project_validated_holdout_observations,
    run_holdout_case_arms,
    score_deterministic_exact_holdout_case,
)


def _observation(
    observation_id: str,
    *,
    observation_type: str,
    occurrence_id: str,
    thread_id: str,
    text: str,
    index: int,
) -> Observation:
    location = {
        "message_occurrence_id": occurrence_id,
        "thread_id": thread_id,
    }
    payload: dict[str, object]
    if observation_type == "email_header":
        location |= {
            "header_name": "Subject",
            "header_index": index,
        }
        payload = {
            "header_name": "Subject",
            "header_value": text.removeprefix("Subject: "),
        }
    else:
        location["body_segment_index"] = index
        payload = {"body_segment_index": index}
    return Observation(
        observation_id=observation_id,
        extractor_run_id="extractor_run_fixture",
        observation_type=observation_type,
        modality="mail",
        location=location,
        confidence=1.0,
        permission_scope={
            "scope_type": "workspace",
            "visibility": "restricted",
            "scope_id": "workspace_fixture",
        },
        created_at="2026-08-18T12:00:00+00:00",
        asset_id="asset_fixture",
        text=text,
        payload=payload,
    )


def _bundle_fixture(
    observations: list[Observation],
    *,
    senders: dict[str, str] | None = None,
) -> SimpleNamespace:
    senders = senders or {}
    occurrences = []
    messages = []
    body_segments = []
    seen_messages: set[str] = set()
    for observation in observations:
        occurrence_id = str(observation.location["message_occurrence_id"])
        message_id = f"message_{occurrence_id}"
        thread_id = str(observation.location["thread_id"])
        if message_id not in seen_messages:
            occurrences.append(
                SimpleNamespace(
                    message_occurrence_id=occurrence_id,
                    email_message_id=message_id,
                )
            )
            messages.append(
                SimpleNamespace(
                    email_message_id=message_id,
                    thread_id=thread_id,
                    sender=senders.get(message_id, "sender-a@example.test"),
                )
            )
            seen_messages.add(message_id)
        if observation.observation_type == "email_body_segment":
            segment_index = int(observation.location["body_segment_index"])
            body_segments.append(
                SimpleNamespace(
                    source_observation_id=observation.observation_id,
                    email_body_segment_id=f"segment_{observation.observation_id}",
                    email_message_id=message_id,
                    message_occurrence_id=occurrence_id,
                    text=observation.text,
                    body_segment_index=segment_index,
                    body_segment_hash=sha256_json(
                        {
                            "email_message_id": message_id,
                            "body_segment_index": segment_index,
                            "text": observation.text,
                        }
                    ),
                )
            )
    return SimpleNamespace(
        mail_evidence_bundle_id="bundle_fixture",
        message_occurrences=occurrences,
        messages=messages,
        body_segments=body_segments,
        mail_import_session=SimpleNamespace(
            owner_user_id="owner_fixture",
            workspace_id="workspace_fixture",
        ),
    )


def _case(
    result_kind: str,
    observation_ids: list[str],
) -> dict[str, object]:
    return {
        "case_id": f"case_{result_kind}",
        "domain": "mail",
        "intent_kind": "exact_inventory",
        "pattern": result_kind,
        "result_kind": result_kind,
        "query_text": "sealed fixture query",
        "requester_user_id": "owner_fixture",
        "required_source_observation_ids": observation_ids,
        "forbidden_source_observation_ids": [],
        "required_match_count": len(observation_ids),
        "limit": 10,
        "private_fingerprint": sha256_json(result_kind),
        "stratum_id": result_kind,
        "answer_oracle": _ExplodingOracle(),
    }


class _ExplodingOracle(dict[str, object]):
    def __getitem__(self, key: str) -> object:
        raise AssertionError(f"quality oracle read during preflight: {key}")

    def get(self, key: str, default: object = None) -> object:
        raise AssertionError(f"quality oracle read during preflight: {key}")


def _sha256_bytes(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _write_json(path: Path, payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    path.write_bytes(encoded)
    return _sha256_bytes(encoded)


def _sealed_holdout_manifest_and_projection(
    root: Path,
    cases: list[dict[str, object]],
) -> tuple[dict[str, object], Path, str, dict[str, object], Path, str]:
    manifest: dict[str, object] = {
        "artifact_id": holdout_uat.HOLDOUT_ARTIFACT_ID,
        "schema_version": 2,
        "classification": "independent_mail_holdout",
        "claim_boundary_status": "sealed_independent_holdout_manifest_not_executed",
        "execution_status": "not_run",
        "quality_result_status": "not_read",
        "seal_required_before_execution": True,
        "source_oracle_bindings": {},
        "development_exclusion_binding": {},
        "partition_fingerprint": sha256_json("partition"),
        "disjointness": {},
        "case_count": EXPECTED_CASE_COUNT,
        "case_strata_counts": dict(holdout_uat.EXPECTED_STRATA_COUNTS),
        "cases": cases,
    }
    manifest["manifest_fingerprint"] = holdout_uat._payload_fingerprint(
        manifest,
        "manifest_fingerprint",
    )
    manifest_path = root / "manifest.json"
    manifest_sha256 = _write_json(manifest_path, manifest)
    projection = holdout_uat.build_oracle_free_holdout_projection(
        private_manifest=manifest,
        private_manifest_sha256=manifest_sha256,
    )
    projection_path = root / "holdout-oracle-free-projection.json"
    projection_sha256 = _write_json(projection_path, projection)
    return (
        manifest,
        manifest_path,
        manifest_sha256,
        projection,
        projection_path,
        projection_sha256,
    )


def _source_author_hashed_base_fixture(
    root: Path,
) -> tuple[
    dict[str, object],
    Path,
    str,
    dict[str, object],
    str,
    dict[str, object],
    SimpleNamespace,
    _HoldoutExecutionContext,
]:
    partition_fingerprint = sha256_json("source-author-partition")
    strata_specs = (
        ("graph_required", 30, (2,) * 30),
        ("single_document_direct_lookup", 4, (1,) * 4),
        ("exact_set", 1, (4,)),
        ("exact_count", 1, (3,)),
        ("exact_aggregation", 1, (3,)),
        ("no_answer_near_miss_negative", 2, (1, 1)),
        ("permission_denied", 2, (1, 1)),
    )
    cases: list[dict[str, object]] = []
    observations: list[Observation] = []
    observation_index = 0
    for stratum, case_count, cardinalities in strata_specs:
        self_cardinalities = tuple(cardinalities)
        if len(self_cardinalities) != case_count:
            raise AssertionError("fixture stratum cardinality mismatch")
        for stratum_index, cardinality in enumerate(self_cardinalities):
            case_observation_ids: list[str] = []
            for _ in range(cardinality):
                observation_index += 1
                observation_id = f"holdout-observation-{observation_index:03d}"
                occurrence_number = observation_index if observation_index != 18 else 17
                occurrence_id = f"holdout-occurrence-{occurrence_number:03d}"
                if occurrence_number in {1, 2}:
                    thread_id = "holdout-thread-shared-a"
                elif occurrence_number in {3, 4}:
                    thread_id = "holdout-thread-shared-b"
                else:
                    thread_id = f"holdout-thread-{occurrence_number:03d}"
                observation_type = (
                    "email_header" if observation_index <= 17 else "email_body_segment"
                )
                text = (
                    f"Subject: protected-{observation_index:03d}"
                    if observation_type == "email_header"
                    else f"protected body {observation_index:03d}"
                )
                observations.append(
                    _observation(
                        observation_id,
                        observation_type=observation_type,
                        occurrence_id=occurrence_id,
                        thread_id=thread_id,
                        text=text,
                        index=observation_index,
                    )
                )
                case_observation_ids.append(observation_id)
            result_kind = {
                "graph_required": "owner_match",
                "single_document_direct_lookup": "source_evidence",
                "exact_set": "exact_set",
                "exact_count": "exact_count",
                "exact_aggregation": "exact_aggregation",
                "no_answer_near_miss_negative": "no_answer",
                "permission_denied": "permission_denied",
            }[stratum]
            intent_kind = (
                "relation_reasoning"
                if stratum in {"graph_required", "no_answer_near_miss_negative"}
                else (
                    "exact_inventory"
                    if stratum in {"exact_set", "exact_count", "exact_aggregation"}
                    else "evidence_lookup"
                )
            )
            required_ids = (
                []
                if stratum in {"no_answer_near_miss_negative", "permission_denied"}
                else case_observation_ids
            )
            forbidden_ids = (
                case_observation_ids
                if stratum in {"no_answer_near_miss_negative", "permission_denied"}
                else []
            )
            requester_user_id = (
                f"denied-requester-{stratum_index}"
                if stratum == "permission_denied"
                else "owner_fixture"
            )
            case: dict[str, object] = {
                "case_id": f"holdout-{stratum}-{stratum_index}",
                "domain": "mail",
                "intent_kind": intent_kind,
                "pattern": f"{stratum}-fixture",
                "result_kind": result_kind,
                "query_text": f"private query {stratum} {stratum_index}",
                "requester_user_id": requester_user_id,
                "required_source_observation_ids": required_ids,
                "forbidden_source_observation_ids": forbidden_ids,
                "authoring_source_observation_ids": case_observation_ids,
                "required_match_count": len(required_ids),
                "limit": 10,
                "stratum_id": stratum,
                "source_evidence_binding": {
                    "partition_fingerprint": partition_fingerprint,
                },
            }
            case["private_fingerprint"] = sha256_json(
                {
                    "stratum": stratum,
                    "index": stratum_index,
                    "observations": case_observation_ids,
                }
            )
            case["answer_oracle"] = {"private": True}
            cases.append(case)
    if observation_index != 78 or len(cases) != EXPECTED_CASE_COUNT:
        raise AssertionError("fixture count mismatch")

    development_observation = _observation(
        "development-observation",
        observation_type="email_body_segment",
        occurrence_id="development-occurrence",
        thread_id="development-thread",
        text="development only",
        index=1,
    )
    all_observations = [*observations, development_observation]
    bundle = _bundle_fixture(all_observations)
    observations_by_id = {
        observation.observation_id: observation for observation in all_observations
    }
    observation_hash_by_id = {
        observation_id: sha256_json(observation.to_dict())
        for observation_id, observation in observations_by_id.items()
    }
    occurrence_to_message = {
        occurrence.message_occurrence_id: occurrence.email_message_id
        for occurrence in bundle.message_occurrences
    }
    message_to_thread = {message.email_message_id: message.thread_id for message in bundle.messages}
    observation_to_occurrence = {
        observation_id: str(observation.location["message_occurrence_id"])
        for observation_id, observation in observations_by_id.items()
    }
    source_lineage = {
        "observation_hashes": observation_hash_by_id,
        "observation_types": {
            observation_id: observation.observation_type
            for observation_id, observation in observations_by_id.items()
        },
        "observation_to_occurrence": observation_to_occurrence,
        "occurrence_to_email_message": occurrence_to_message,
        "occurrence_to_thread": {
            occurrence_id: str(message_to_thread[message_id])
            for occurrence_id, message_id in occurrence_to_message.items()
        },
    }
    validated_cases = source_author_projection._validated_holdout_case_lineage(
        cases,
        source_lineage=source_lineage,
        source_permission_fingerprint=sha256_json(observations[0].permission_scope),
        partition_fingerprint=partition_fingerprint,
    )
    projected_cases = [
        source_author_projection._oracle_free_nonreversible_case_projection(case)
        for case in validated_cases
    ]
    holdout_observation_ids = {
        observation_id
        for validated_case in validated_cases
        for observation_id in validated_case["authoring_ids"]
    }
    holdout_message_ids = {
        occurrence_to_message[observation_to_occurrence[observation_id]]
        for observation_id in holdout_observation_ids
    }
    holdout_thread_ids = {str(message_to_thread[message_id]) for message_id in holdout_message_ids}
    disjointness = {
        "status": "passed",
        "development_holdout_observation_overlap_count": 0,
        "development_holdout_message_overlap_count": 0,
        "development_holdout_thread_overlap_count": 0,
        "holdout_authoring_observation_count": len(holdout_observation_ids),
        "holdout_authoring_message_count": len(holdout_message_ids),
        "holdout_authoring_thread_count": len(holdout_thread_ids),
        "holdout_observation_set_fingerprint": sha256_json(
            sorted(sha256_json(value) for value in holdout_observation_ids)
        ),
        "holdout_message_set_fingerprint": sha256_json(
            sorted(sha256_json(value) for value in holdout_message_ids)
        ),
        "holdout_thread_set_fingerprint": sha256_json(
            sorted(sha256_json(value) for value in holdout_thread_ids)
        ),
    }
    source_oracle_bindings = {
        "bundle_artifact_sha256": sha256_json("fixture-bundle-bytes"),
        "bundle_artifact_fingerprint": sha256_json("fixture-bundle-artifact"),
        "mail_evidence_bundle_fingerprint": sha256_json("fixture-mail-bundle"),
        "retrieval_snapshot_sha256": sha256_json("fixture-snapshot-bytes"),
        "source_report_sha256": sha256_json("fixture-source-report-bytes"),
        "source_snapshot_fingerprint": sha256_json("fixture-source-snapshot"),
        "source_inventory_fingerprint": sha256_json("fixture-source-inventory"),
        "source_provenance_fingerprint": sha256_json("fixture-source-provenance"),
        "index_fingerprint": sha256_json("fixture-index"),
        "tokenizer_profile_fingerprint": sha256_json("fixture-tokenizer"),
    }
    development_exclusion_binding = {
        "development_case_count": 100,
        "development_manifest_fingerprint": sha256_json("fixture-development-manifest"),
        "development_manifest_sha256": sha256_json("fixture-development-bytes"),
        "development_registry_fingerprint": sha256_json("fixture-development-registry"),
        "development_safe_report_sha256": sha256_json("fixture-development-safe-bytes"),
    }
    manifest: dict[str, object] = {
        "artifact_id": holdout_uat.HOLDOUT_ARTIFACT_ID,
        "schema_version": 2,
        "classification": "independent_mail_holdout",
        "claim_boundary_status": "sealed_independent_holdout_manifest_not_executed",
        "execution_status": "not_run",
        "quality_result_status": "not_read",
        "seal_required_before_execution": True,
        "source_oracle_bindings": source_oracle_bindings,
        "development_exclusion_binding": development_exclusion_binding,
        "partition_fingerprint": partition_fingerprint,
        "disjointness": disjointness,
        "case_count": EXPECTED_CASE_COUNT,
        "case_strata_counts": dict(holdout_uat.EXPECTED_STRATA_COUNTS),
        "cases": cases,
    }
    manifest["manifest_fingerprint"] = holdout_uat._payload_fingerprint(
        manifest,
        "manifest_fingerprint",
    )
    manifest_path = root / "source-author-holdout.private.json"
    manifest_sha256 = _write_json(manifest_path, manifest)
    private_manifest_id = sha256_json(
        {
            "artifact_id": holdout_uat.HOLDOUT_ARTIFACT_ID,
            "manifest_fingerprint": manifest["manifest_fingerprint"],
        }
    )
    projection: dict[str, object] = {
        "artifact_id": holdout_uat.HOLDOUT_ORACLE_FREE_PROJECTION_ARTIFACT_ID,
        "schema_version": holdout_uat.HOLDOUT_ORACLE_FREE_PROJECTION_SCHEMA_VERSION,
        "status": "sealed_oracle_free",
        "execution_status": "not_run",
        "quality_result_status": "not_read",
        "private_manifest_binding": {
            "manifest_artifact_id": holdout_uat.HOLDOUT_ARTIFACT_ID,
            "manifest_schema_version": 2,
            "manifest_classification": "independent_mail_holdout",
            "private_manifest_id": private_manifest_id,
            "manifest_sha256": manifest_sha256,
            "manifest_fingerprint": manifest["manifest_fingerprint"],
            "partition_fingerprint": partition_fingerprint,
            "case_count": EXPECTED_CASE_COUNT,
        },
        "source_oracle_bindings": source_oracle_bindings,
        "development_exclusion_binding": development_exclusion_binding,
        "disjointness": disjointness,
        "case_count": EXPECTED_CASE_COUNT,
        "case_strata_counts": dict(holdout_uat.EXPECTED_STRATA_COUNTS),
        "cases": projected_cases,
    }
    projection["projection_fingerprint"] = holdout_uat._payload_fingerprint(
        projection,
        "projection_fingerprint",
    )
    projection_sha256 = _write_json(root / "source-author-projection.safe.json", projection)
    safe_report: dict[str, object] = {
        "artifact_id": holdout_uat.HOLDOUT_REPORT_ARTIFACT_ID,
        "schema_version": 2,
        "status": "passed",
        "execution_status": "not_run",
        "quality_result_status": "not_read",
        "seal_before_execution_status": "passed",
        "source_lineage_status": "passed",
        "disjointness_status": "passed",
        "strata_coverage_status": "passed",
        "counts": {
            "case_count": EXPECTED_CASE_COUNT,
            "holdout_authoring_observation_count": len(holdout_observation_ids),
            "development_holdout_observation_overlap_count": 0,
            "development_holdout_message_overlap_count": 0,
            "development_holdout_thread_overlap_count": 0,
            "source_unexplained_loss_count": 0,
            "blocker_count": 0,
        },
        "strata_counts": dict(holdout_uat.EXPECTED_STRATA_COUNTS),
        "hashes": {
            "manifest_sha256": manifest_sha256,
            "manifest_fingerprint": manifest["manifest_fingerprint"],
            "holdout_observation_set_fingerprint": disjointness[
                "holdout_observation_set_fingerprint"
            ],
            "holdout_message_set_fingerprint": disjointness["holdout_message_set_fingerprint"],
            "holdout_thread_set_fingerprint": disjointness["holdout_thread_set_fingerprint"],
        },
        "blocker_ids": [],
    }
    safe_report["report_fingerprint"] = holdout_uat._payload_fingerprint(
        safe_report,
        "report_fingerprint",
    )
    context = _HoldoutExecutionContext(
        observations_by_bundle_id={},
        observations_by_id=observations_by_id,
        observation_hash_by_id=observation_hash_by_id,
        sessions={"owner_fixture": SimpleNamespace()},
        effective_graph_views={"owner_fixture": object()},
        lineage_crosswalks={"owner_fixture": object()},
        graph_builds={},
        graph_ontology_binding=_graph_ontology_binding(),
        development_observation_ids=frozenset({"development-observation"}),
    )
    return (
        manifest,
        manifest_path,
        manifest_sha256,
        projection,
        projection_sha256,
        safe_report,
        bundle,
        context,
    )


def _extension_manifest_projection_fixture(
    root: Path,
) -> tuple[
    dict[str, object],
    Path,
    str,
    dict[str, object],
    Path,
    str,
    _HoldoutExecutionContext,
    SimpleNamespace,
    dict[str, object],
]:
    policy = holdout_uat._EXTENSION_HOLDOUT_POLICY
    permission_scope = {
        "scope_type": "workspace",
        "visibility": "restricted",
        "scope_id": "workspace_fixture",
    }
    partition_fingerprint = sha256_json("extension-partition")
    owner_user_id = "owner"
    workspace_id = "workspace_fixture"
    denied_requester_id = holdout_uat._extension_denied_requester_id(
        owner_user_id=owner_user_id,
        workspace_id=workspace_id,
    )
    observations: list[Observation] = []
    occurrences: list[SimpleNamespace] = []
    messages: list[SimpleNamespace] = []
    cases: list[dict[str, object]] = []
    safe_cases: list[dict[str, object]] = []
    observation_counter = 0

    def add_observation(*, text: str) -> Observation:
        nonlocal observation_counter
        observation_counter += 1
        observation = Observation(
            observation_id=f"extension-observation-{observation_counter}",
            extractor_run_id="extension-extractor-run",
            observation_type="email_body_segment",
            modality="mail",
            location={
                "message_occurrence_id": f"extension-occurrence-{observation_counter}",
                "thread_id": f"extension-thread-{observation_counter}",
                "body_segment_index": 1,
            },
            confidence=1.0,
            permission_scope=permission_scope,
            created_at="2026-08-18T12:00:00+00:00",
            asset_id="extension-asset",
            text=text,
            payload={"body_segment_index": 1},
        )
        observations.append(observation)
        occurrences.append(
            SimpleNamespace(
                message_occurrence_id=observation.location["message_occurrence_id"],
                email_message_id=f"extension-message-{observation_counter}",
            )
        )
        messages.append(
            SimpleNamespace(
                email_message_id=f"extension-message-{observation_counter}",
                thread_id=observation.location["thread_id"],
                sender="source-author@example.test",
            )
        )
        return observation

    strata_order = (
        "graph_required",
        "single_document_direct_lookup",
        "exact_set",
        "exact_count",
        "exact_aggregation",
        "no_answer_near_miss_negative",
        "permission_denied",
    )
    for stratum in strata_order:
        for case_index in range(policy.strata_counts[stratum]):
            unique_id = f"{len(cases) + 1:03d}"
            if stratum in {"graph_required", "no_answer_near_miss_negative"}:
                case_observations = (
                    add_observation(text=f"PO-{unique_id} alpha concept"),
                    add_observation(text=f"PO-{unique_id} beta concept"),
                )
            elif stratum in {"exact_set", "exact_count", "exact_aggregation"}:
                case_observations = (
                    add_observation(
                        text=(f"PO-{unique_id} INV-{unique_id} " f"protected identifiers inventory")
                    ),
                )
            else:
                case_observations = (add_observation(text=f"PO-{unique_id} direct concept"),)
            authoring_ids = tuple(
                sorted(observation.observation_id for observation in case_observations)
            )
            if stratum == "no_answer_near_miss_negative":
                result_kind = "no_answer"
                required_ids: tuple[str, ...] = ()
                forbidden_ids = authoring_ids
                query_class = "relation_reasoning"
                intent_kind = "relation_reasoning"
            elif stratum == "permission_denied":
                result_kind = "permission_denied"
                required_ids = ()
                forbidden_ids = authoring_ids
                query_class = "evidence_lookup"
                intent_kind = "evidence_lookup"
            elif stratum == "single_document_direct_lookup":
                result_kind = "source_evidence"
                required_ids = authoring_ids
                forbidden_ids = ()
                query_class = "evidence_lookup"
                intent_kind = "evidence_lookup"
            elif stratum == "graph_required":
                result_kind = "owner_match"
                required_ids = authoring_ids
                forbidden_ids = ()
                query_class = "relation_reasoning"
                intent_kind = "relation_reasoning"
            else:
                result_kind = stratum
                required_ids = authoring_ids
                forbidden_ids = ()
                query_class = "exact_inventory"
                intent_kind = "exact_inventory"
            route = extension_author._route(
                stratum=stratum,
                query_class=query_class,
                result_kind=result_kind,
            )
            candidate_fingerprint = sha256_json(
                {
                    "stratum": stratum,
                    "case_index": case_index,
                    "observation_ids": authoring_ids,
                }
            )
            query_text = f"source authored extension {stratum} {unique_id}"
            observation_hashes = {
                observation.observation_id: sha256_json(observation.to_dict())
                for observation in case_observations
            }
            evidence_binding = {
                "candidate_fingerprint": candidate_fingerprint,
                "required_observation_hashes": sorted(
                    observation_hashes[observation_id] for observation_id in required_ids
                ),
                "authoring_observation_hashes": sorted(observation_hashes.values()),
                "authoring_message_hashes": sorted(
                    sha256_json(
                        f"extension-message-{int(observation.observation_id.rsplit('-', 1)[1])}"
                    )
                    for observation in case_observations
                ),
                "authoring_thread_hashes": sorted(
                    sha256_json(str(observation.location["thread_id"]))
                    for observation in case_observations
                ),
                "partition_fingerprint": partition_fingerprint,
            }
            adjudication: dict[str, object]
            if stratum == "graph_required":
                adjudication = {
                    "answer_kind": "source_backed_relation",
                    "shared_identifier": f"PO-{unique_id}",
                    "left_concept": "alpha",
                    "right_concept": "beta",
                    "required_source_observation_ids": list(required_ids),
                }
            elif stratum == "single_document_direct_lookup":
                adjudication = {
                    "answer_kind": "source_evidence",
                    "required_source_observation_ids": list(required_ids),
                    "requester_user_id": owner_user_id,
                }
            elif stratum == "exact_set":
                adjudication = {
                    "answer_kind": "exact_set",
                    "inventory_kind": "protected_identifier",
                    "required_source_observation_ids": list(required_ids),
                    "items": [f"INV-{unique_id}", f"PO-{unique_id}"],
                }
            elif stratum == "exact_count":
                adjudication = {
                    "answer_kind": "exact_count",
                    "inventory_kind": "protected_identifier",
                    "required_source_observation_ids": list(required_ids),
                    "count": 2,
                }
            elif stratum == "exact_aggregation":
                adjudication = {
                    "answer_kind": "exact_aggregation",
                    "inventory_kind": "protected_identifier",
                    "required_source_observation_ids": list(required_ids),
                    "counts_by_identifier_kind": {
                        "invoice_id": 1,
                        "purchase_order": 1,
                    },
                }
            elif stratum == "no_answer_near_miss_negative":
                adjudication = {
                    "answer_kind": "no_answer",
                    "forbidden_source_observation_ids": list(forbidden_ids),
                    "absence_proof_fingerprint": sha256_json(
                        {"case_index": case_index, "stratum": stratum}
                    ),
                }
            else:
                adjudication = {
                    "answer_kind": "permission_denied",
                    "denied_source_observation_ids": list(forbidden_ids),
                    "requester_user_id": denied_requester_id,
                }
            case: dict[str, object] = {
                "case_id": f"extension-case-{unique_id}",
                "domain": "mail",
                "source_kind": "mail",
                "stratum_id": stratum,
                "intent_kind": intent_kind,
                "pattern": f"source_authored_{stratum}_v1",
                "result_kind": result_kind,
                "query_text": query_text,
                "query_hash": sha256_json(query_text),
                "requester_user_id": (
                    denied_requester_id if stratum == "permission_denied" else owner_user_id
                ),
                "required_source_observation_ids": list(required_ids),
                "forbidden_source_observation_ids": list(forbidden_ids),
                "authoring_source_observation_ids": list(authoring_ids),
                "required_match_count": len(required_ids),
                "limit": 10,
                "typed_route": route,
                "route_fingerprint": route["route_fingerprint"],
                "source_evidence_binding": evidence_binding,
                "adjudication": adjudication,
            }
            case["private_fingerprint"] = sha256_json(
                {
                    "candidate_fingerprint": candidate_fingerprint,
                    "query_hash": case["query_hash"],
                    "route_fingerprint": route["route_fingerprint"],
                    "authoring_observation_hashes": evidence_binding[
                        "authoring_observation_hashes"
                    ],
                }
            )
            cases.append(case)
            safe_cases.append(
                {
                    "manifest_entry_hash": case["private_fingerprint"],
                    "case_id_hash": sha256_json(case["case_id"]),
                    "query_hash": case["query_hash"],
                    "stratum_id": stratum,
                    "identifier_kind": "fixture_identifier",
                    "route": route,
                    "route_fingerprint": route["route_fingerprint"],
                    "authoring_observation_count": len(authoring_ids),
                    "authoring_message_count": len(authoring_ids),
                    "authoring_thread_count": len(authoring_ids),
                    "authoring_observation_set_fingerprint": sha256_json(
                        evidence_binding["authoring_observation_hashes"]
                    ),
                }
            )

    observation_hash_by_id = {
        observation.observation_id: sha256_json(observation.to_dict())
        for observation in observations
    }
    observation_ids = [observation.observation_id for observation in observations]
    message_ids = [message.email_message_id for message in messages]
    thread_ids = [message.thread_id for message in messages]
    query_hashes = [str(case["query_hash"]) for case in cases]
    case_fingerprints = [str(case["private_fingerprint"]) for case in cases]
    disjointness = {
        "status": "passed",
        "development_observation_overlap_count": 0,
        "development_message_overlap_count": 0,
        "development_thread_overlap_count": 0,
        "base_holdout_observation_overlap_count": 0,
        "base_holdout_message_overlap_count": 0,
        "base_holdout_thread_overlap_count": 0,
        "base_holdout_query_overlap_count": 0,
        "base_holdout_case_fingerprint_overlap_count": 0,
        "extension_observation_reuse_count": 0,
        "extension_message_reuse_count": 0,
        "extension_thread_reuse_count": 0,
        "extension_query_reuse_count": 0,
        "extension_case_fingerprint_reuse_count": 0,
        "extension_observation_count": len(observation_ids),
        "extension_message_count": len(message_ids),
        "extension_thread_count": len(thread_ids),
        "extension_observation_set_fingerprint": sha256_json(
            sorted(sha256_json(value) for value in observation_ids)
        ),
        "extension_message_set_fingerprint": sha256_json(
            sorted(sha256_json(value) for value in message_ids)
        ),
        "extension_thread_set_fingerprint": sha256_json(
            sorted(sha256_json(value) for value in thread_ids)
        ),
        "extension_query_set_fingerprint": sha256_json(sorted(query_hashes)),
        "extension_case_set_fingerprint": sha256_json(sorted(case_fingerprints)),
    }
    selection_proof: dict[str, object] = {
        "status": "passed",
        "selection_order": extension_author._SELECTION_POLICY["selection_order"],
        "capacity_shortfall_policy": "fail_closed_no_redistribution",
        "candidate_counts": dict(policy.strata_counts),
        "selected_counts": dict(policy.strata_counts),
        "eligible_candidate_count": policy.case_count,
        "selected_candidate_count": policy.case_count,
        "candidate_inventory_fingerprint": sha256_json(case_fingerprints),
        "selected_candidate_fingerprint": sha256_json(case_fingerprints),
    }
    selection_proof["selection_proof_fingerprint"] = sha256_json(selection_proof)

    base_manifest_sha256 = sha256_json("base-holdout-manifest-bytes")
    base_manifest_fingerprint = sha256_json("base-holdout-manifest")
    base_registry_fingerprint = sha256_json("base-holdout-registry")
    base_safe_report: dict[str, object] = {
        "artifact_id": holdout_uat.HOLDOUT_EXTENSION_BASE_REPORT_ARTIFACT_ID,
        "schema_version": 2,
        "status": "passed",
        "execution_status": "not_run",
        "quality_result_status": "not_read",
        "counts": {
            "case_count": holdout_uat.HOLDOUT_EXTENSION_BASE_CASE_COUNT,
            "blocker_count": 0,
        },
        "strata_counts": dict(holdout_uat.EXPECTED_STRATA_COUNTS),
        "hashes": {"manifest_sha256": base_manifest_sha256},
    }
    base_safe_report["report_fingerprint"] = holdout_uat._payload_fingerprint(
        base_safe_report,
        "report_fingerprint",
    )
    base_safe_path = root / "base-holdout.safe.json"
    base_safe_sha256 = _write_json(base_safe_path, base_safe_report)
    base_binding = {
        "artifact_id": holdout_uat.HOLDOUT_EXTENSION_BASE_ARTIFACT_ID,
        "manifest_sha256": base_manifest_sha256,
        "safe_report_sha256": base_safe_sha256,
        "manifest_fingerprint": base_manifest_fingerprint,
        "case_count": holdout_uat.HOLDOUT_EXTENSION_BASE_CASE_COUNT,
        "registry_fingerprint": base_registry_fingerprint,
    }
    bundle_payload = {
        "workspace_id": workspace_id,
        "owner_user_id": owner_user_id,
        "message_count": len(messages),
        "observation_hashes": sorted(observation_hash_by_id.values()),
    }
    bundle = SimpleNamespace(
        message_occurrences=occurrences,
        messages=messages,
        body_segments=(),
        mail_import_session=SimpleNamespace(
            owner_user_id=owner_user_id,
            workspace_id=workspace_id,
        ),
        to_dict=lambda: bundle_payload,
    )
    source_bindings = {
        "bundle_artifact_sha256": sha256_json("retrieval-bundle-bytes"),
        "retrieval_snapshot_sha256": sha256_json("retrieval-snapshot-bytes"),
        "source_snapshot_fingerprint": sha256_json("source-snapshot"),
        "source_inventory_fingerprint": sha256_json("source-inventory"),
        "source_provenance_fingerprint": sha256_json("source-provenance"),
        "permission_fingerprint": sha256_json(permission_scope),
        "mail_evidence_bundle_fingerprint": sha256_json(bundle_payload),
        "tokenizer_profile_fingerprint": (ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT),
        "index_fingerprint": sha256_json("index"),
        "snapshot_fingerprint": sha256_json("retrieval-snapshot"),
    }
    development_binding = {
        "artifact_id": holdout_uat.DEVELOPMENT_MANIFEST_ARTIFACT_ID,
        "manifest_sha256": sha256_json("development-manifest-bytes"),
        "safe_report_sha256": sha256_json("development-report-bytes"),
        "manifest_fingerprint": sha256_json("development-manifest"),
        "case_count": 100,
        "registry_fingerprint": sha256_json("development-registry"),
    }
    capacity_audit_binding: dict[str, object] = {
        "artifact_id": "formowl_issue56_holdout_extension_capacity_audit_binding_v1",
        "status": "passed",
        "capacity_audit_policy_id": extension_author.CAPACITY_AUDIT_POLICY_ID,
        "capacity_audit_policy_fingerprint": (
            extension_author.ALTERNATIVE_STRATA_POLICY_FINGERPRINT
        ),
        "target_strata_counts": dict(policy.strata_counts),
        "source_snapshot_fingerprint": source_bindings["source_snapshot_fingerprint"],
        "partition_fingerprint": partition_fingerprint,
        "candidate_inventory_fingerprint": selection_proof["candidate_inventory_fingerprint"],
        "selected_candidate_fingerprint": selection_proof["selected_candidate_fingerprint"],
        "selection_proof_fingerprint": selection_proof["selection_proof_fingerprint"],
        "capacity_shortfall_policy": "fail_closed_no_redistribution",
    }
    capacity_audit_binding["capacity_audit_binding_fingerprint"] = sha256_json(
        capacity_audit_binding
    )
    manifest: dict[str, object] = {
        "artifact_id": policy.manifest_artifact_id,
        "schema_version": policy.manifest_schema_version,
        "classification": policy.manifest_classification,
        "status": "sealed",
        "claim_boundary_status": policy.manifest_claim_boundary_status,
        "execution_status": "not_run",
        "quality_result_status": "not_read",
        "final_acceptance_eligible": True,
        "diagnostic_only": False,
        "source_author_role_id": extension_author.SOURCE_AUTHOR_ROLE_ID,
        "source_bindings": source_bindings,
        "base_holdout_binding": base_binding,
        "development_exclusion_binding": development_binding,
        "selection_policy": extension_author._SELECTION_POLICY,
        "selection_policy_fingerprint": (
            holdout_uat.HOLDOUT_EXTENSION_SELECTION_POLICY_FINGERPRINT
        ),
        "capacity_audit_binding": capacity_audit_binding,
        "partition_policy": extension_author._PARTITION_POLICY,
        "partition_policy_fingerprint": (
            holdout_uat.HOLDOUT_EXTENSION_PARTITION_POLICY_FINGERPRINT
        ),
        "time_boundary_fingerprint": sha256_json("time-boundary"),
        "partition_fingerprint": partition_fingerprint,
        "disjointness_proof": disjointness,
        "selection_proof": selection_proof,
        "base_case_count": holdout_uat.HOLDOUT_EXTENSION_BASE_CASE_COUNT,
        "extension_case_count": policy.case_count,
        "combined_acceptance_case_count": (holdout_uat.HOLDOUT_EXTENSION_COMBINED_CASE_COUNT),
        "case_strata_counts": dict(policy.strata_counts),
        "cases": cases,
    }
    manifest["manifest_fingerprint"] = holdout_uat._payload_fingerprint(
        manifest,
        "manifest_fingerprint",
    )
    manifest_path = root / "extension-manifest.private.json"
    manifest_sha256 = _write_json(manifest_path, manifest)
    projection: dict[str, object] = {
        "artifact_id": policy.projection_artifact_id,
        "schema_version": policy.projection_schema_version,
        "status": "sealed_oracle_free",
        "classification": policy.manifest_classification,
        "execution_status": "not_run",
        "quality_result_status": "not_read",
        "final_acceptance_eligible": True,
        "diagnostic_only": False,
        "private_manifest_binding": {
            "artifact_id": policy.manifest_artifact_id,
            "schema_version": policy.manifest_schema_version,
            "manifest_sha256": manifest_sha256,
            "manifest_fingerprint": manifest["manifest_fingerprint"],
        },
        "base_holdout_binding": base_binding,
        "source_binding_hashes": {
            (
                "segmentation_profile_fingerprint"
                if key == "tokenizer_profile_fingerprint"
                else key
            ): value
            for key, value in source_bindings.items()
        },
        "selection_policy_fingerprint": (
            holdout_uat.HOLDOUT_EXTENSION_SELECTION_POLICY_FINGERPRINT
        ),
        "capacity_audit_binding": capacity_audit_binding,
        "partition_policy_fingerprint": (
            holdout_uat.HOLDOUT_EXTENSION_PARTITION_POLICY_FINGERPRINT
        ),
        "partition_fingerprint": partition_fingerprint,
        "selection_proof_fingerprint": selection_proof["selection_proof_fingerprint"],
        "counts": {
            "base_case_count": holdout_uat.HOLDOUT_EXTENSION_BASE_CASE_COUNT,
            "extension_case_count": policy.case_count,
            "combined_acceptance_case_count": (holdout_uat.HOLDOUT_EXTENSION_COMBINED_CASE_COUNT),
            "eligible_observation_count": len(observations),
            "eligible_message_count": len(messages),
            "eligible_thread_count": len(thread_ids),
            "selected_observation_count": len(observations),
            "selected_message_count": len(messages),
            "selected_thread_count": len(thread_ids),
            "candidate_count": policy.case_count,
            "overlap_count": 0,
            "reuse_count": 0,
            "blocker_count": 0,
        },
        "strata_counts": dict(policy.strata_counts),
        "disjointness_proof_hash": sha256_json(disjointness),
        "cases": safe_cases,
    }
    projection["projection_fingerprint"] = holdout_uat._payload_fingerprint(
        projection,
        "projection_fingerprint",
    )
    projection_path = root / "extension-projection.safe.json"
    projection_sha256 = _write_json(projection_path, projection)
    context = _HoldoutExecutionContext(
        observations_by_bundle_id={},
        observations_by_id={
            observation.observation_id: observation for observation in observations
        },
        observation_hash_by_id=observation_hash_by_id,
        sessions={},
        effective_graph_views={},
        lineage_crosswalks={},
        graph_builds={},
        graph_ontology_binding=_graph_ontology_binding(),
    )
    extra_hashes = {
        "retrieval_bundle_sha256": source_bindings["bundle_artifact_sha256"],
        "retrieval_snapshot_sha256": source_bindings["retrieval_snapshot_sha256"],
        "source_snapshot_fingerprint": source_bindings["source_snapshot_fingerprint"],
        "source_inventory_fingerprint": source_bindings["source_inventory_fingerprint"],
        "source_provenance_fingerprint": source_bindings["source_provenance_fingerprint"],
        "retrieval_snapshot_fingerprint": source_bindings["snapshot_fingerprint"],
        "lexical_profile_fingerprint": source_bindings["tokenizer_profile_fingerprint"],
        "index_fingerprint": source_bindings["index_fingerprint"],
        "development_manifest_sha256": development_binding["manifest_sha256"],
        "development_report_sha256": development_binding["safe_report_sha256"],
        "holdout_report_sha256": base_safe_sha256,
    }
    return (
        manifest,
        manifest_path,
        manifest_sha256,
        projection,
        projection_path,
        projection_sha256,
        context,
        bundle,
        extra_hashes,
    )


def _extension_projection_validation_kwargs(
    *,
    root: Path,
    manifest_sha256: str,
    projection: dict[str, object],
    bundle: SimpleNamespace,
    extra_hashes: dict[str, object],
) -> dict[str, object]:
    base_safe_path = root / "base-holdout.safe.json"
    base_safe_bytes = base_safe_path.read_bytes()
    base_safe_report = json.loads(base_safe_bytes)
    return {
        "holdout_policy": holdout_uat._EXTENSION_HOLDOUT_POLICY,
        "projection": projection,
        "manifest_sha256": manifest_sha256,
        "safe_report": base_safe_report,
        "safe_report_sha256": _sha256_bytes(base_safe_bytes),
        "retrieval_bundle_sha256": extra_hashes["retrieval_bundle_sha256"],
        "retrieval_snapshot_sha256": extra_hashes["retrieval_snapshot_sha256"],
        "bundle_artifact": {
            "bundle_fingerprint": sha256_json(bundle.to_dict()),
        },
        "bundle": bundle,
        "retrieval_snapshot": {
            "source_snapshot_fingerprint": extra_hashes["source_snapshot_fingerprint"],
            "source_inventory_fingerprint": extra_hashes["source_inventory_fingerprint"],
            "source_provenance_fingerprint": extra_hashes["source_provenance_fingerprint"],
            "permission_fingerprint": sha256_json(
                {
                    "scope_type": "workspace",
                    "visibility": "restricted",
                    "scope_id": "workspace_fixture",
                }
            ),
            "mail_evidence_bundle_fingerprint": sha256_json(bundle.to_dict()),
            "tokenizer_profile_fingerprint": extra_hashes["lexical_profile_fingerprint"],
            "index_fingerprint": extra_hashes["index_fingerprint"],
            "snapshot_fingerprint": extra_hashes["retrieval_snapshot_fingerprint"],
        },
        "source_report_sha256": sha256_json("source-report-bytes"),
        "development_manifest": {
            "case_count": 100,
            "manifest_fingerprint": sha256_json("development-manifest"),
        },
        "development_manifest_sha256": extra_hashes["development_manifest_sha256"],
        "development_report_sha256": extra_hashes["development_report_sha256"],
        "development_observation_ids": frozenset(),
        "development_registry_fingerprint": sha256_json("development-registry"),
    }


def _extension_execution_fixture(
    root: Path,
) -> tuple[
    dict[str, object],
    Path,
    str,
    dict[str, object],
    str,
    _HoldoutExecutionContext,
    SimpleNamespace,
    dict[str, object],
    dict[str, object],
]:
    (
        manifest,
        manifest_path,
        manifest_sha256,
        projection,
        _projection_path,
        projection_sha256,
        source_context,
        bundle,
        extra_hashes,
    ) = _extension_manifest_projection_fixture(root)
    source_identifier_binding = _source_identifier_binding(
        tokenizer_profile_fingerprint=extra_hashes["lexical_profile_fingerprint"]
    )
    runtime_fingerprint = sha256_json("extension-runtime")
    runtime = _execution_runtime_binding(
        index_fingerprint=extra_hashes["index_fingerprint"],
        runtime_fingerprint=runtime_fingerprint,
        source_identifier_binding=source_identifier_binding,
    )
    index = SimpleNamespace(
        execution_component_fingerprint=sha256_json("component"),
        index_fingerprint=extra_hashes["index_fingerprint"],
    )
    owner_user_id = bundle.mail_import_session.owner_user_id
    denied_requester_id = holdout_uat._extension_denied_requester_id(
        owner_user_id=owner_user_id,
        workspace_id=bundle.mail_import_session.workspace_id,
    )
    context = _HoldoutExecutionContext(
        observations_by_bundle_id=source_context.observations_by_bundle_id,
        observations_by_id=source_context.observations_by_id,
        observation_hash_by_id=source_context.observation_hash_by_id,
        sessions={
            owner_user_id: SimpleNamespace(index=index),
            denied_requester_id: SimpleNamespace(index=index),
        },
        effective_graph_views={
            owner_user_id: object(),
            denied_requester_id: object(),
        },
        lineage_crosswalks={
            owner_user_id: object(),
            denied_requester_id: object(),
        },
        graph_builds={},
        graph_ontology_binding=source_context.graph_ontology_binding,
    )
    preflight = _execution_preflight_report(
        manifest_sha256=manifest_sha256,
        runtime_fingerprint=runtime_fingerprint,
        source_identifier_binding=source_identifier_binding,
        oracle_free_projection=projection,
        oracle_free_projection_sha256=projection_sha256,
        holdout_policy=holdout_uat._EXTENSION_HOLDOUT_POLICY,
        extra_hashes=extra_hashes,
    )
    return (
        manifest,
        manifest_path,
        manifest_sha256,
        projection,
        projection_sha256,
        context,
        bundle,
        runtime,
        preflight,
    )


def _development_component_binding() -> dict[str, str]:
    runtime = {
        "index_fingerprint": sha256_json("index"),
        "lexical_profile_fingerprint": sha256_json("tokenizer"),
        "query_lexical_profile_fingerprint": sha256_json("tokenizer"),
        "evidence_lexical_profile_fingerprint": sha256_json("tokenizer"),
        "candidate_admission_profile_fingerprint": sha256_json("tokenizer"),
        "dense_profile_fingerprint": sha256_json("dense"),
        "execution_component_fingerprint": sha256_json("component"),
        "runtime_method_fingerprint": sha256_json("method"),
        "graph_adapter_fingerprint": sha256_json("graph-adapter"),
        "ontology_target_fingerprint": sha256_json("ontology-target"),
        "answer_model_fingerprint": sha256_json("answer-model"),
        "answer_prompt_fingerprint": sha256_json("answer-prompt"),
        "answer_budget_fingerprint": sha256_json("answer-budget"),
        "evaluator_fingerprint": sha256_json("evaluator"),
        "image_id": holdout_uat.FROZEN_CANONICAL_IMAGE_ID,
        "image_metadata_fingerprint": (holdout_uat.FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT),
        "source_completeness_gate_status": "passed",
        "real_source_ablation_gate_status": "passed",
    }
    runtime["component_binding_fingerprint"] = sha256_json(runtime)
    return runtime


def _development_acceptance() -> _DevelopmentAcceptance:
    component = _development_component_binding()
    payload = {
        "completed_report_sha256": sha256_json("development-report"),
        "operational_budget_bundle_sha256": sha256_json("budget-bundle"),
        "operational_budget_fingerprint": (holdout_uat.FROZEN_BUDGET_FINGERPRINT),
        "operational_budget_bundle_fingerprint": sha256_json("budget-bundle-fingerprint"),
        "operational_budget_check_set_fingerprint": sha256_json("budget-checks"),
        "component_binding_fingerprint": component["component_binding_fingerprint"],
    }
    return _DevelopmentAcceptance(
        completed_report_sha256=payload["completed_report_sha256"],
        operational_budget_bundle_sha256=payload["operational_budget_bundle_sha256"],
        operational_budget_fingerprint=payload["operational_budget_fingerprint"],
        operational_budget_bundle_fingerprint=payload["operational_budget_bundle_fingerprint"],
        operational_budget_check_set_fingerprint=payload[
            "operational_budget_check_set_fingerprint"
        ],
        component_binding=component,
        acceptance_fingerprint=sha256_json(payload),
    )


def _source_identifier_binding(
    label: str = "one",
    *,
    tokenizer_profile_fingerprint: str | None = None,
    identity_scope_mode: str = TENANT_WORKSPACE_IDENTITY_SCOPE_MODE,
) -> dict[str, object]:
    workspace_id = "workspace_fixture"
    tenant_id = (
        "tenant_fixture" if identity_scope_mode == TENANT_WORKSPACE_IDENTITY_SCOPE_MODE else None
    )
    spec_approval_fingerprint = (
        sha256_json(f"spec-approval-{label}")
        if identity_scope_mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
        else None
    )
    scope_payload = {
        "mode": identity_scope_mode,
        "workspace_id": workspace_id,
    }
    if tenant_id is not None:
        scope_payload["tenant_id"] = tenant_id
    identity_scope = SourceIdentifierIdentityScope(
        identity_scope_mode=identity_scope_mode,
        identity_scope_fingerprint=sha256_json(scope_payload),
        workspace_id=workspace_id,
        identity_scope_attestation_fingerprint=sha256_json(f"identity-attestation-{label}"),
        identity_scope_policy_fingerprint=(holdout_uat.IDENTITY_SCOPE_POLICY_FINGERPRINT),
        operator_approval_fingerprint=sha256_json(f"operator-approval-{label}"),
        tenant_id=tenant_id,
        spec_approval_fingerprint=spec_approval_fingerprint,
    )
    graph_identity_binding = holdout_uat._identity_scope_graph_binding(identity_scope)
    mode_approval_fingerprint = sha256_json(
        {
            "identity_scope_mode": identity_scope_mode,
            "operator_approval_fingerprint": (identity_scope.operator_approval_fingerprint),
            "spec_approval_fingerprint": spec_approval_fingerprint,
        }
    )
    binding: dict[str, object] = {
        "status": "sealed_passed",
        "candidate_artifact_schema_version": (holdout_uat.CANDIDATE_ARTIFACT_SCHEMA_VERSION),
        "candidate_artifact_schema_fingerprint": sha256_json(
            holdout_uat.CANDIDATE_ARTIFACT_SCHEMA_VERSION
        ),
        "source_artifact_byte_hash": sha256_json(f"candidate-bytes-{label}"),
        "source_artifact_fingerprint": sha256_json(f"candidate-artifact-{label}"),
        "source_snapshot_fingerprint": sha256_json(f"source-snapshot-{label}"),
        "source_inventory_fingerprint": sha256_json(f"source-inventory-{label}"),
        "source_observation_hash_set_fingerprint": sha256_json(f"observation-set-{label}"),
        "retrieval_snapshot_fingerprint": sha256_json(f"retrieval-snapshot-{label}"),
        "retrieval_report_fingerprint": sha256_json(f"retrieval-report-{label}"),
        "retrieval_snapshot_byte_sha256": sha256_json(f"retrieval-snapshot-bytes-{label}"),
        "retrieval_report_byte_sha256": sha256_json(f"retrieval-report-bytes-{label}"),
        "candidate_admission_profile_fingerprint": (
            tokenizer_profile_fingerprint or sha256_json("tokenizer")
        ),
        "extraction_policy_fingerprint": sha256_json(f"extraction-{label}"),
        "resolution_policy_fingerprint": sha256_json(f"resolution-{label}"),
        "identity_scope_mode": identity_scope_mode,
        "identity_scope_mode_status": identity_scope_mode,
        "identity_scope_mode_fingerprint": sha256_json(identity_scope_mode),
        "identity_scope_fingerprint": identity_scope.identity_scope_fingerprint,
        "identity_scope_binding_fingerprint": sha256_json(identity_scope.to_dict()),
        "identity_scope_graph_binding_fingerprint": sha256_json(graph_identity_binding),
        "identity_scope_attestation_byte_sha256": sha256_json(
            f"identity-attestation-bytes-{label}"
        ),
        "identity_scope_attestation_fingerprint": (
            identity_scope.identity_scope_attestation_fingerprint
        ),
        "identity_scope_policy_fingerprint": (identity_scope.identity_scope_policy_fingerprint),
        "workspace_scope_fingerprint": sha256_json(workspace_id),
        "operator_approval_fingerprint": (identity_scope.operator_approval_fingerprint),
        "spec_approval_status": (
            "passed_bound"
            if identity_scope_mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
            else "not_required_for_mode"
        ),
        "mode_approval_binding_fingerprint": mode_approval_fingerprint,
        "mode_approval_fingerprint": mode_approval_fingerprint,
        "attested_asset_fingerprint": sha256_json(f"attested-asset-{label}"),
        "complete_mention_batch_fingerprint": sha256_json(f"complete-mentions-{label}"),
        "complete_resolution_fingerprint": sha256_json(f"complete-resolution-{label}"),
        "selected_mention_batch_fingerprint": sha256_json(f"selected-mentions-{label}"),
        "selected_resolution_fingerprint": sha256_json(f"selected-resolution-{label}"),
        "complete_mention_count": 7,
        "complete_resolved_candidate_count": 3,
        "selected_mention_count": 5,
        "selected_resolved_candidate_count": 2,
        "overflow_count": 0,
        "candidate_graph_only": True,
        "canonical_write_allowed": False,
        "source_graph_policy_fingerprint": sha256_json(development_uat.SOURCE_GRAPH_POLICY_ID),
        "source_identifier_adapter_fingerprint": sha256_json(
            development_uat.SOURCE_IDENTIFIER_ADAPTER_ID
        ),
        "holdout_adapter_fingerprint": (holdout_uat.SOURCE_IDENTIFIER_HOLDOUT_ADAPTER_FINGERPRINT),
    }
    if spec_approval_fingerprint is not None:
        binding["spec_approval_fingerprint"] = spec_approval_fingerprint
    binding["binding_fingerprint"] = sha256_json(binding)
    return binding


def _graph_ontology_binding(
    label: str = "one",
    *,
    permission_scoped_graph_count: int = 2,
    source_identifier_binding: dict[str, object] | None = None,
) -> dict[str, object]:
    source_identifier_binding = source_identifier_binding or _source_identifier_binding()
    payload: dict[str, object] = {
        "graph_artifact_fingerprint": sha256_json(f"graph-artifact-{label}"),
        "graph_revision_fingerprint": sha256_json(f"graph-revision-{label}"),
        "graph_revision_id_fingerprint": sha256_json(f"graph-revision-id-{label}"),
        "ontology_artifact_fingerprint": sha256_json(f"ontology-artifact-{label}"),
        "ontology_revision_fingerprint": sha256_json(f"ontology-revision-{label}"),
        "permission_scoped_graph_count": permission_scoped_graph_count,
        "graph_node_count": 7,
        "graph_edge_count": 5,
        "ontology_revision_count": 1,
        "source_graph_policy_fingerprint": source_identifier_binding[
            "source_graph_policy_fingerprint"
        ],
        "source_identifier_adapter_fingerprint": source_identifier_binding[
            "source_identifier_adapter_fingerprint"
        ],
        "source_identifier_candidate_artifact_fingerprint": (
            source_identifier_binding["source_artifact_fingerprint"]
        ),
        "source_identifier_candidate_binding_fingerprint": (
            source_identifier_binding["binding_fingerprint"]
        ),
        "candidate_artifact_schema_fingerprint": source_identifier_binding[
            "candidate_artifact_schema_fingerprint"
        ],
        "complete_identifier_mention_fingerprint_set_hash": sha256_json(
            f"complete-mention-set-{label}"
        ),
        "authorized_identifier_mention_fingerprint_set_hash": sha256_json(
            f"authorized-mention-set-{label}"
        ),
        "identifier_resolution_fingerprint_set_hash": sha256_json(f"resolution-set-{label}"),
        "requester_projected_mention_batch_fingerprint_set_hash": sha256_json(
            f"requester-projection-set-{label}"
        ),
        "selected_identifier_mention_batch_fingerprint": (
            source_identifier_binding["selected_mention_batch_fingerprint"]
        ),
        "selected_identifier_resolution_fingerprint": (
            source_identifier_binding["selected_resolution_fingerprint"]
        ),
        "identifier_mention_count": 5,
        "authorized_identifier_mention_count": 5,
        "selected_resolved_candidate_count": 2,
        "identity_scope_mode_status": source_identifier_binding["identity_scope_mode_status"],
        "identity_scope_mode_fingerprint": source_identifier_binding[
            "identity_scope_mode_fingerprint"
        ],
        "identity_scope_fingerprint": source_identifier_binding["identity_scope_fingerprint"],
        "identity_scope_binding_fingerprint": source_identifier_binding[
            "identity_scope_binding_fingerprint"
        ],
        "identity_scope_attestation_byte_sha256": source_identifier_binding[
            "identity_scope_attestation_byte_sha256"
        ],
        "identity_scope_attestation_fingerprint": source_identifier_binding[
            "identity_scope_attestation_fingerprint"
        ],
        "identity_scope_policy_fingerprint": source_identifier_binding[
            "identity_scope_policy_fingerprint"
        ],
        "operator_approval_fingerprint": source_identifier_binding["operator_approval_fingerprint"],
        "mode_approval_fingerprint": source_identifier_binding["mode_approval_fingerprint"],
        "workspace_scope_fingerprint": source_identifier_binding["workspace_scope_fingerprint"],
        "identity_scope_graph_binding_fingerprint_set_hash": sha256_json(
            [source_identifier_binding["identity_scope_graph_binding_fingerprint"]]
        ),
        "candidate_graph_only": True,
        "human_review_complete": False,
    }
    if (
        source_identifier_binding["identity_scope_mode_status"]
        == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
    ):
        payload["spec_approval_fingerprint"] = source_identifier_binding[
            "spec_approval_fingerprint"
        ]
    payload["graph_ontology_binding_fingerprint"] = sha256_json(payload)
    return payload


def _execution_runtime_binding(
    *,
    index_fingerprint: str,
    runtime_fingerprint: str,
    source_identifier_binding: dict[str, object] | None = None,
) -> dict[str, object]:
    source_identifier_binding = source_identifier_binding or _source_identifier_binding()
    graph_binding = _graph_ontology_binding(source_identifier_binding=source_identifier_binding)
    runtime: dict[str, object] = {
        "index_fingerprint": index_fingerprint,
        "runtime_fingerprint": runtime_fingerprint,
        "source_identifier_candidate_artifact_sha256": (
            source_identifier_binding["source_artifact_byte_hash"]
        ),
        "source_identifier_candidate_binding_fingerprint": (
            source_identifier_binding["binding_fingerprint"]
        ),
        "source_identifier_candidate_schema_version_fingerprint": (
            source_identifier_binding["candidate_artifact_schema_fingerprint"]
        ),
        "source_identifier_identity_scope_mode_status": source_identifier_binding[
            "identity_scope_mode_status"
        ],
        "source_identifier_identity_scope_mode_fingerprint": (
            source_identifier_binding["identity_scope_mode_fingerprint"]
        ),
        "source_identifier_identity_scope_fingerprint": source_identifier_binding[
            "identity_scope_fingerprint"
        ],
        "source_identifier_identity_scope_attestation_sha256": (
            source_identifier_binding["identity_scope_attestation_byte_sha256"]
        ),
        "source_identifier_identity_scope_attestation_fingerprint": (
            source_identifier_binding["identity_scope_attestation_fingerprint"]
        ),
        "source_identifier_identity_scope_policy_fingerprint": (
            source_identifier_binding["identity_scope_policy_fingerprint"]
        ),
        "source_identifier_identity_scope_binding_fingerprint": (
            source_identifier_binding["identity_scope_binding_fingerprint"]
        ),
        "source_identifier_identity_scope_graph_binding_fingerprint": (
            source_identifier_binding["identity_scope_graph_binding_fingerprint"]
        ),
        "source_identifier_operator_approval_fingerprint": (
            source_identifier_binding["operator_approval_fingerprint"]
        ),
        "source_identifier_mode_approval_binding_fingerprint": (
            source_identifier_binding["mode_approval_fingerprint"]
        ),
        "source_identifier_attested_asset_fingerprint": source_identifier_binding[
            "attested_asset_fingerprint"
        ],
        "source_identifier_candidate_profile_fingerprint": (
            source_identifier_binding["candidate_admission_profile_fingerprint"]
        ),
        "source_identifier_extraction_policy_fingerprint": (
            source_identifier_binding["extraction_policy_fingerprint"]
        ),
        "source_identifier_resolution_policy_fingerprint": (
            source_identifier_binding["resolution_policy_fingerprint"]
        ),
        "source_identifier_complete_mention_batch_fingerprint": (
            source_identifier_binding["complete_mention_batch_fingerprint"]
        ),
        "source_identifier_complete_resolution_fingerprint": (
            source_identifier_binding["complete_resolution_fingerprint"]
        ),
        "source_identifier_projected_mention_batch_fingerprint": (
            source_identifier_binding["selected_mention_batch_fingerprint"]
        ),
        "source_identifier_projected_resolution_fingerprint": (
            source_identifier_binding["selected_resolution_fingerprint"]
        ),
        "source_identifier_complete_mention_fingerprint_set_hash": graph_binding[
            "complete_identifier_mention_fingerprint_set_hash"
        ],
        "source_identifier_authorized_mention_fingerprint_set_hash": (
            graph_binding["authorized_identifier_mention_fingerprint_set_hash"]
        ),
        "source_identifier_resolution_fingerprint_set_hash": graph_binding[
            "identifier_resolution_fingerprint_set_hash"
        ],
        "source_identifier_requester_projection_fingerprint_set_hash": (
            graph_binding["requester_projected_mention_batch_fingerprint_set_hash"]
        ),
        "source_graph_policy_fingerprint": source_identifier_binding[
            "source_graph_policy_fingerprint"
        ],
        "source_identifier_adapter_fingerprint": source_identifier_binding[
            "source_identifier_adapter_fingerprint"
        ],
        "holdout_source_identifier_adapter_fingerprint": (
            source_identifier_binding["holdout_adapter_fingerprint"]
        ),
        "consumed_claim_contract_fingerprint": (holdout_uat.CONSUMED_CLAIM_CONTRACT_FINGERPRINT),
        "execution_output_contract_fingerprint": (
            holdout_uat.EXECUTION_OUTPUT_CONTRACT_FINGERPRINT
        ),
    }
    if (
        source_identifier_binding["identity_scope_mode_status"]
        == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
    ):
        runtime["source_identifier_spec_approval_fingerprint"] = source_identifier_binding[
            "spec_approval_fingerprint"
        ]
    return runtime


def _candidate_artifact_fixture(
    *,
    source_identifier_binding: dict[str, object],
    retrieval_snapshot: dict[str, object],
    retrieval_snapshot_sha256: str,
    observation_hashes: list[str],
) -> dict[str, object]:
    mode = str(source_identifier_binding["identity_scope_mode_status"])
    identity_scope_binding: dict[str, object] = {
        "identity_scope_mode": mode,
        "identity_scope_fingerprint": source_identifier_binding["identity_scope_fingerprint"],
        "workspace_id": "workspace_fixture",
        "identity_scope_attestation_fingerprint": source_identifier_binding[
            "identity_scope_attestation_fingerprint"
        ],
        "identity_scope_policy_fingerprint": source_identifier_binding[
            "identity_scope_policy_fingerprint"
        ],
        "operator_approval_fingerprint": source_identifier_binding["operator_approval_fingerprint"],
    }
    if mode == TENANT_WORKSPACE_IDENTITY_SCOPE_MODE:
        identity_scope_binding["tenant_id"] = "tenant_fixture"
    else:
        identity_scope_binding["spec_approval_fingerprint"] = source_identifier_binding[
            "spec_approval_fingerprint"
        ]
    empty_batch = holdout_uat.SourceBoundIdentifierMentionBatch(
        candidate_mentions=(),
        tokenizer_id=holdout_uat.JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
        tokenizer_profile_fingerprint=str(retrieval_snapshot["tokenizer_profile_fingerprint"]),
        extraction_policy_id=(holdout_uat.SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_ID),
        extraction_policy_fingerprint=(
            holdout_uat.SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT
        ),
        identity_scope_mode=mode,
        identity_scope_fingerprint=str(source_identifier_binding["identity_scope_fingerprint"]),
        workspace_id="workspace_fixture",
        identity_scope_attestation_fingerprint=str(
            source_identifier_binding["identity_scope_attestation_fingerprint"]
        ),
        identity_scope_policy_fingerprint=str(
            source_identifier_binding["identity_scope_policy_fingerprint"]
        ),
        operator_approval_fingerprint=str(
            source_identifier_binding["operator_approval_fingerprint"]
        ),
        tenant_id=("tenant_fixture" if mode == TENANT_WORKSPACE_IDENTITY_SCOPE_MODE else None),
        spec_approval_fingerprint=(
            str(source_identifier_binding["spec_approval_fingerprint"])
            if mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
            else None
        ),
        occurrence_count=0,
        batch_fingerprint=sha256_json(
            {
                "candidate_mention_ids": [],
                "extraction_policy_fingerprint": (
                    holdout_uat.SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT
                ),
                "identity_scope": identity_scope_binding,
                "tokenizer_profile_fingerprint": retrieval_snapshot[
                    "tokenizer_profile_fingerprint"
                ],
            }
        ),
    )
    empty_resolution = holdout_uat.resolve_exact_protected_identifier_candidates(())
    return {
        "artifact_id": holdout_uat.SOURCE_IDENTIFIER_CANDIDATE_ARTIFACT_ID,
        "schema_version": holdout_uat.CANDIDATE_ARTIFACT_SCHEMA_VERSION,
        "artifact_fingerprint": source_identifier_binding["source_artifact_fingerprint"],
        "identity_scope_mode": mode,
        "identity_scope_binding": identity_scope_binding,
        "identity_scope_attestation_byte_sha256": source_identifier_binding[
            "identity_scope_attestation_byte_sha256"
        ],
        "identity_scope_attestation_fingerprint": source_identifier_binding[
            "identity_scope_attestation_fingerprint"
        ],
        "identity_scope_policy_fingerprint": source_identifier_binding[
            "identity_scope_policy_fingerprint"
        ],
        "attested_asset_fingerprint": source_identifier_binding["attested_asset_fingerprint"],
        "retrieval_snapshot_byte_sha256": retrieval_snapshot_sha256,
        "retrieval_report_byte_sha256": sha256_json("retrieval-report-bytes"),
        "retrieval_snapshot_fingerprint": retrieval_snapshot["snapshot_fingerprint"],
        "retrieval_report_fingerprint": sha256_json("retrieval-report"),
        "source_snapshot_fingerprint": retrieval_snapshot["source_snapshot_fingerprint"],
        "source_inventory_fingerprint": retrieval_snapshot["source_inventory_fingerprint"],
        "tokenizer_id": holdout_uat.JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
        "tokenizer_profile_fingerprint": retrieval_snapshot["tokenizer_profile_fingerprint"],
        "source_observation_hashes": sorted(observation_hashes),
        "source_observation_hash_set_fingerprint": sha256_json(sorted(observation_hashes)),
        "extraction_policy_id": (holdout_uat.SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_ID),
        "extraction_policy_fingerprint": (
            holdout_uat.SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT
        ),
        "resolution_policy_id": holdout_uat.SOURCE_IDENTIFIER_RESOLUTION_POLICY_ID,
        "resolution_policy_fingerprint": (
            holdout_uat.SOURCE_IDENTIFIER_RESOLUTION_POLICY_FINGERPRINT
        ),
        "candidate_only": True,
        "canonical_write_allowed": False,
        "overflow_count": 0,
        "mention_batch": empty_batch.to_dict(),
        "resolution": empty_resolution.to_dict(),
        "counts": {
            "identifier_occurrence_count": 0,
            "resolved_candidate_count": 0,
            "overflow_count": 0,
        },
    }


def _execution_preflight_report(
    *,
    manifest_sha256: str,
    runtime_fingerprint: str,
    source_identifier_binding: dict[str, object] | None = None,
    oracle_free_projection: dict[str, object] | None = None,
    oracle_free_projection_sha256: str | None = None,
    holdout_policy: object = holdout_uat._BASE_HOLDOUT_POLICY,
    extra_hashes: dict[str, object] | None = None,
) -> dict[str, object]:
    source_identifier_binding = source_identifier_binding or _source_identifier_binding()
    oracle_free_projection = oracle_free_projection or {
        "projection_fingerprint": sha256_json("holdout-projection"),
        "private_manifest_binding": {
            "private_manifest_id": sha256_json("private-manifest-id"),
        },
    }
    oracle_free_projection_sha256 = oracle_free_projection_sha256 or sha256_json(
        "holdout-projection-bytes"
    )
    manifest_binding = oracle_free_projection["private_manifest_binding"]
    private_manifest_id = manifest_binding.get("private_manifest_id")
    if private_manifest_id is None:
        private_manifest_id = sha256_json(
            {
                "artifact_id": holdout_policy.manifest_artifact_id,
                "manifest_fingerprint": manifest_binding["manifest_fingerprint"],
            }
        )
    report: dict[str, object] = {
        "status": "passed",
        "preflight_status": "passed",
        "runtime_freeze_status": "matched",
        "owner_execution_status": "passed",
        "execution_status": "not_run",
        "quality_result_status": "not_read",
        "strata_counts": dict(holdout_policy.strata_counts),
        "counts": {
            "blocker_count": 0,
        },
        "hashes": {
            "runtime_fingerprint": runtime_fingerprint,
            "holdout_manifest_sha256": manifest_sha256,
            "holdout_policy_fingerprint": holdout_policy.policy_fingerprint,
            "holdout_oracle_free_projection_sha256": oracle_free_projection_sha256,
            "holdout_oracle_free_projection_fingerprint": oracle_free_projection[
                "projection_fingerprint"
            ],
            "holdout_private_manifest_id": private_manifest_id,
            "source_identifier_candidate_artifact_sha256": (
                source_identifier_binding["source_artifact_byte_hash"]
            ),
            "source_identifier_candidate_binding_fingerprint": (
                source_identifier_binding["binding_fingerprint"]
            ),
            **{
                field_name: _execution_runtime_binding(
                    index_fingerprint=sha256_json("index"),
                    runtime_fingerprint=runtime_fingerprint,
                    source_identifier_binding=source_identifier_binding,
                )[field_name]
                for field_name in holdout_uat._SOURCE_IDENTIFIER_CLAIM_HASH_FIELDS
                if field_name
                not in {
                    "source_identifier_candidate_artifact_sha256",
                    "source_identifier_candidate_binding_fingerprint",
                }
            },
            "consumed_claim_contract_fingerprint": (
                holdout_uat.CONSUMED_CLAIM_CONTRACT_FINGERPRINT
            ),
            "execution_output_contract_fingerprint": (
                holdout_uat.EXECUTION_OUTPUT_CONTRACT_FINGERPRINT
            ),
            "preflight_input_fingerprint": sha256_json("preflight-input"),
            **(extra_hashes or {}),
        },
    }
    if (
        source_identifier_binding["identity_scope_mode_status"]
        == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
    ):
        report["hashes"]["source_identifier_spec_approval_fingerprint"] = source_identifier_binding[
            "spec_approval_fingerprint"
        ]
    report["hashes"]["report_fingerprint"] = holdout_uat._report_fingerprint(report)
    return report


def _exact_result(
    observations: list[Observation],
    observation_hash_by_id: dict[str, str],
    *,
    complete: bool = True,
) -> DeterministicExactExecutionResult:
    items = tuple(
        ExactInventoryItem(
            item_hash=sha256_json(
                {
                    "inventory_kind": "mail_observation",
                    "inventory_value": observation.observation_id,
                }
            ),
            cited_observation_hashes=(observation_hash_by_id[observation.observation_id],),
        )
        for observation in observations
    )
    count = len(items)
    reason_hashes = () if complete else (sha256_json("fixture_incomplete"),)
    coverage = ExactCoverageContract(
        coverage_fingerprint=sha256_json({"count": count, "complete": complete}),
        view_revision_fingerprint=sha256_json("view_fixture"),
        visible_node_count=count,
        inventory_schema_record_count=count,
        filter_term_count=1,
        identifier_filter_count=1,
        topic_filter_count=0,
        eligible_record_count=count,
        enumerated_record_count=count,
        cited_observation_count=count,
        missing_evidence_record_count=0 if complete else 1,
        access_required_scope_count=0,
        authorized_scope_complete=complete,
        global_scope_complete=complete,
        incompleteness_reason_hashes=reason_hashes,
    )
    return DeterministicExactExecutionResult(
        status="complete_authorized_scope" if complete else "incomplete",
        query_hash=sha256_json("query_fixture"),
        plan_fingerprint=sha256_json("plan_fixture"),
        operation_hash=sha256_json("inventory_with_count"),
        inventory_kind_hash=sha256_json("mail_observation"),
        exact_count=count,
        returned_item_count=count,
        cited_observation_count=count,
        items=items,
        coverage=coverage,
        result_fingerprint=sha256_json(
            {"items": [item.item_hash for item in items], "complete": complete}
        ),
    )


class Issue56IndependentMailHoldoutUatE2ETests(unittest.TestCase):
    def test_holdout_policy_registry_preserves_41_and_accepts_extension_59(
        self,
    ) -> None:
        self.assertEqual(holdout_uat._BASE_HOLDOUT_POLICY.case_count, 41)
        self.assertEqual(
            dict(holdout_uat._BASE_HOLDOUT_POLICY.strata_counts),
            holdout_uat.EXPECTED_STRATA_COUNTS,
        )
        self.assertEqual(holdout_uat._EXTENSION_HOLDOUT_POLICY.case_count, 59)
        self.assertEqual(
            holdout_uat.HOLDOUT_EXTENSION_COMBINED_CASE_COUNT,
            holdout_uat._BASE_HOLDOUT_POLICY.case_count
            + holdout_uat._EXTENSION_HOLDOUT_POLICY.case_count,
        )
        self.assertEqual(holdout_uat.HOLDOUT_EXTENSION_COMBINED_CASE_COUNT, 100)
        self.assertEqual(
            dict(holdout_uat._EXTENSION_HOLDOUT_POLICY.strata_counts),
            extension_author.TARGET_STRATA_COUNTS,
        )
        self.assertNotEqual(
            holdout_uat._BASE_HOLDOUT_POLICY.policy_fingerprint,
            holdout_uat._EXTENSION_HOLDOUT_POLICY.policy_fingerprint,
        )
        self.assertEqual(
            holdout_uat.validate_execution_safety_metrics(
                case_count=41,
                permission_leakage_count=0,
                unresolved_citation_count=0,
                unresolved_graph_hop_count=0,
                exact_incomplete_count=0,
            )["case_count"],
            41,
        )
        self.assertEqual(
            holdout_uat.validate_execution_safety_metrics(
                case_count=59,
                permission_leakage_count=0,
                unresolved_citation_count=0,
                unresolved_graph_hop_count=0,
                exact_incomplete_count=0,
                holdout_policy_id=holdout_uat.EXTENSION_HOLDOUT_POLICY_ID,
            )["case_count"],
            59,
        )

    def test_base_preflight_accepts_78_sealed_observation_references_without_lookup(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (
                manifest,
                _manifest_path,
                manifest_sha,
                projection,
                _projection_sha,
                safe_report,
                bundle,
                _context,
            ) = _source_author_hashed_base_fixture(Path(directory))
            source_binding = projection["source_oracle_bindings"]
            disjointness = projection["disjointness"]
            self.assertEqual(disjointness["holdout_authoring_observation_count"], 78)
            self.assertEqual(disjointness["holdout_authoring_message_count"], 77)
            self.assertEqual(disjointness["holdout_authoring_thread_count"], 75)
            self.assertEqual(
                len(
                    {
                        observation_hash
                        for case in projection["cases"]
                        for observation_hash in case["authoring_source_observation_ids"]
                    }
                ),
                78,
            )
            with mock.patch.object(
                holdout_uat,
                "_validated_referenced_observation_lineage",
                side_effect=AssertionError("preflight must not resolve sealed observation hashes"),
            ) as raw_lookup:
                lineage = holdout_uat._validate_base_holdout_projection(
                    projection=projection,
                    manifest_sha256=manifest_sha,
                    safe_report=safe_report,
                    safe_report_sha256=sha256_json("safe-report-bytes"),
                    retrieval_bundle_sha256=source_binding["bundle_artifact_sha256"],
                    retrieval_snapshot_sha256=source_binding["retrieval_snapshot_sha256"],
                    bundle_artifact={
                        "artifact_fingerprint": source_binding["bundle_artifact_fingerprint"],
                        "bundle_fingerprint": source_binding["mail_evidence_bundle_fingerprint"],
                    },
                    bundle=bundle,
                    retrieval_snapshot={
                        "source_snapshot_fingerprint": source_binding[
                            "source_snapshot_fingerprint"
                        ],
                        "source_inventory_fingerprint": source_binding[
                            "source_inventory_fingerprint"
                        ],
                        "source_provenance_fingerprint": source_binding[
                            "source_provenance_fingerprint"
                        ],
                        "index_fingerprint": source_binding["index_fingerprint"],
                        "tokenizer_profile_fingerprint": source_binding[
                            "tokenizer_profile_fingerprint"
                        ],
                    },
                    source_report_sha256=source_binding["source_report_sha256"],
                    development_manifest={
                        "case_count": 100,
                        "manifest_fingerprint": manifest["development_exclusion_binding"][
                            "development_manifest_fingerprint"
                        ],
                    },
                    development_manifest_sha256=manifest["development_exclusion_binding"][
                        "development_manifest_sha256"
                    ],
                    development_report_sha256=manifest["development_exclusion_binding"][
                        "development_safe_report_sha256"
                    ],
                    development_observation_ids=frozenset({"raw-development-observation"}),
                    development_registry_fingerprint=manifest["development_exclusion_binding"][
                        "development_registry_fingerprint"
                    ],
                )
            raw_lookup.assert_not_called()
            self.assertEqual(lineage["case_count"], 41)
            self.assertEqual(lineage["projected_observation_count"], 78)
            self.assertEqual(lineage["readable_observation_count"], 0)
            self.assertEqual(lineage["permission_denied_case_count"], 2)

    def test_requester_identifier_projection_uses_authorized_not_selected_scopes(
        self,
    ) -> None:
        observation = _observation(
            "projection-observation",
            observation_type="email_body_segment",
            occurrence_id="projection-occurrence",
            thread_id="projection-thread",
            text="Authorized ABC-123 evidence",
            index=1,
        )
        mention = SimpleNamespace(
            source_observation_ids=(observation.observation_id,),
        )
        complete_batch = SimpleNamespace(candidate_mentions=(mention,))
        denied_session = SimpleNamespace(
            selected_source_scope_ids=("bundle_fixture",),
            authorized_source_scope_ids=(),
        )
        owner_session = SimpleNamespace(
            selected_source_scope_ids=("bundle_fixture",),
            authorized_source_scope_ids=("bundle_fixture",),
        )
        with mock.patch.object(
            holdout_uat,
            "_source_identifier_batch_projection",
            side_effect=("denied-projection", "owner-projection"),
        ) as projector:
            denied_projection = holdout_uat._project_source_identifier_batch_for_session(
                complete_batch=complete_batch,
                session=denied_session,
                observations_by_bundle_id={"bundle_fixture": (observation,)},
            )
            owner_projection = holdout_uat._project_source_identifier_batch_for_session(
                complete_batch=complete_batch,
                session=owner_session,
                observations_by_bundle_id={"bundle_fixture": (observation,)},
            )
        self.assertEqual(denied_projection, "denied-projection")
        self.assertEqual(owner_projection, "owner-projection")
        self.assertEqual(
            projector.call_args_list[0].kwargs["selected_mentions"],
            (),
        )
        self.assertEqual(
            projector.call_args_list[1].kwargs["selected_mentions"],
            (mention,),
        )

    def test_consumed_claim_precedes_raw_identity_crosswalk_and_source_lineage(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (
                _manifest,
                manifest_path,
                manifest_sha,
                projection,
                projection_sha,
                _safe_report,
                bundle,
                context,
            ) = _source_author_hashed_base_fixture(root)
            source_identifier_binding = _source_identifier_binding()
            runtime_fingerprint = sha256_json("source-author-runtime")
            runtime = _execution_runtime_binding(
                index_fingerprint=sha256_json("source-author-index"),
                runtime_fingerprint=runtime_fingerprint,
                source_identifier_binding=source_identifier_binding,
            )
            preflight = _execution_preflight_report(
                manifest_sha256=manifest_sha,
                runtime_fingerprint=runtime_fingerprint,
                source_identifier_binding=source_identifier_binding,
                oracle_free_projection=projection,
                oracle_free_projection_sha256=projection_sha,
            )
            output_path = root / "result.safe.json"
            private_bytes = manifest_path.read_bytes()
            real_json_loads = holdout_uat.json.loads
            decoded_after_claim = 0

            def guarded_json_loads(
                payload: bytes | bytearray | str,
                *args: object,
                **kwargs: object,
            ) -> object:
                nonlocal decoded_after_claim
                normalized = bytes(payload) if isinstance(payload, bytearray) else payload
                if normalized == private_bytes:
                    self.assertTrue(holdout_uat._consumed_claim_path(output_path).exists())
                    self.assertFalse(output_path.exists())
                    decoded_after_claim += 1
                return real_json_loads(payload, *args, **kwargs)

            def authorized(
                _bundles: object,
                *,
                requester_user_id: str,
                workspace_id: str,
            ) -> tuple[object, ...]:
                self.assertEqual(workspace_id, "workspace_fixture")
                return (bundle,) if requester_user_id == "owner_fixture" else ()

            post_claim_binding = {
                "requester_context_count": 3,
                "authorized_requester_context_count": 1,
                "denied_requester_context_count": 2,
                "requester_context_set_fingerprint": sha256_json("requester-contexts"),
                "permission_scoped_index_fingerprint_set_hash": sha256_json("permission-indexes"),
                "graph_ontology_binding_fingerprint": sha256_json("post-claim-graph-binding"),
            }
            with (
                mock.patch.object(
                    holdout_uat,
                    "authorize_mail_evidence_bundles",
                    side_effect=authorized,
                ),
                mock.patch.object(
                    holdout_uat,
                    "_source_author_execution_context_after_claim",
                    return_value=(context, post_claim_binding),
                ),
                mock.patch.object(
                    holdout_uat,
                    "run_holdout_case_arms",
                    side_effect=RuntimeError("quality boundary reached"),
                ),
                mock.patch.object(
                    holdout_uat.json,
                    "loads",
                    side_effect=guarded_json_loads,
                ),
                self.assertRaisesRegex(RuntimeError, "quality boundary reached"),
            ):
                _execute_independent_holdout_once(
                    preflight_report=preflight,
                    execution_context=context,
                    bundle=bundle,
                    oracle_free_projection=projection,
                    manifest_path=manifest_path,
                    expected_manifest_sha256=manifest_sha,
                    runtime_binding=runtime,
                    execution_output=output_path,
                )
            self.assertEqual(decoded_after_claim, 1)
            self.assertTrue(holdout_uat._consumed_claim_path(output_path).exists())
            self.assertFalse(output_path.exists())

    def test_claim_then_raw_crosswalk_rebuilds_and_executes_all_requester_contexts(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (
                manifest,
                manifest_path,
                manifest_sha,
                projection,
                projection_sha,
                _safe_report,
                bundle,
                fixture_context,
            ) = _source_author_hashed_base_fixture(root)
            source_identifier_binding = _source_identifier_binding()
            identity_scope = SourceIdentifierIdentityScope(
                identity_scope_mode=TENANT_WORKSPACE_IDENTITY_SCOPE_MODE,
                identity_scope_fingerprint=str(
                    source_identifier_binding["identity_scope_fingerprint"]
                ),
                workspace_id="workspace_fixture",
                identity_scope_attestation_fingerprint=str(
                    source_identifier_binding["identity_scope_attestation_fingerprint"]
                ),
                identity_scope_policy_fingerprint=str(
                    source_identifier_binding["identity_scope_policy_fingerprint"]
                ),
                operator_approval_fingerprint=str(
                    source_identifier_binding["operator_approval_fingerprint"]
                ),
                tenant_id="tenant_fixture",
            )
            complete_batch = holdout_uat.SourceBoundIdentifierMentionBatch(
                candidate_mentions=(),
                tokenizer_id=(holdout_uat.JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID),
                tokenizer_profile_fingerprint=(ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT),
                extraction_policy_id=(holdout_uat.SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_ID),
                extraction_policy_fingerprint=(
                    holdout_uat.SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT
                ),
                identity_scope_mode=TENANT_WORKSPACE_IDENTITY_SCOPE_MODE,
                identity_scope_fingerprint=identity_scope.identity_scope_fingerprint,
                workspace_id="workspace_fixture",
                identity_scope_attestation_fingerprint=(
                    identity_scope.identity_scope_attestation_fingerprint
                ),
                identity_scope_policy_fingerprint=(
                    identity_scope.identity_scope_policy_fingerprint
                ),
                operator_approval_fingerprint=(identity_scope.operator_approval_fingerprint),
                tenant_id="tenant_fixture",
                spec_approval_fingerprint=None,
                occurrence_count=0,
                batch_fingerprint=sha256_json(
                    {
                        "candidate_mention_ids": [],
                        "extraction_policy_fingerprint": (
                            holdout_uat.SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT
                        ),
                        "identity_scope": identity_scope.to_dict(),
                        "tokenizer_profile_fingerprint": (
                            ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT
                        ),
                    }
                ),
            )
            preflight_context = _HoldoutExecutionContext(
                observations_by_bundle_id={
                    bundle.mail_evidence_bundle_id: tuple(
                        fixture_context.observations_by_id.values()
                    )
                },
                observations_by_id=fixture_context.observations_by_id,
                observation_hash_by_id=fixture_context.observation_hash_by_id,
                sessions=fixture_context.sessions,
                effective_graph_views=fixture_context.effective_graph_views,
                lineage_crosswalks=fixture_context.lineage_crosswalks,
                graph_builds=fixture_context.graph_builds,
                graph_ontology_binding=fixture_context.graph_ontology_binding,
                source_binding_fingerprint=sha256_json("source-binding"),
                identifier_mention_batch=complete_batch,
                source_identifier_binding=source_identifier_binding,
                development_observation_ids=(fixture_context.development_observation_ids),
            )
            requester_ids = {str(case["requester_user_id"]) for case in manifest["cases"]}
            runtime_index_fingerprint = sha256_json("source-author-index")
            execution_component_fingerprint = sha256_json("source-author-execution-component")
            sessions = {
                requester_id: SimpleNamespace(
                    requester_user_id=requester_id,
                    index=SimpleNamespace(
                        execution_component_fingerprint=(execution_component_fingerprint),
                        index_fingerprint=(
                            runtime_index_fingerprint
                            if requester_id == "owner_fixture"
                            else sha256_json("denied-index")
                        ),
                    ),
                )
                for requester_id in requester_ids
            }
            post_claim_context = _HoldoutExecutionContext(
                observations_by_bundle_id=preflight_context.observations_by_bundle_id,
                observations_by_id=preflight_context.observations_by_id,
                observation_hash_by_id=preflight_context.observation_hash_by_id,
                sessions=sessions,
                effective_graph_views={requester_id: object() for requester_id in requester_ids},
                lineage_crosswalks={requester_id: object() for requester_id in requester_ids},
                graph_builds={requester_id: object() for requester_id in requester_ids},
                graph_ontology_binding=(
                    _graph_ontology_binding(
                        permission_scoped_graph_count=len(requester_ids),
                        source_identifier_binding=source_identifier_binding,
                    )
                ),
                source_binding_fingerprint=preflight_context.source_binding_fingerprint,
                identifier_mention_batch=complete_batch,
                source_identifier_binding=source_identifier_binding,
                development_observation_ids=(preflight_context.development_observation_ids),
            )
            post_claim_binding = {
                "requester_context_count": len(requester_ids),
                "authorized_requester_context_count": 1,
                "denied_requester_context_count": 2,
                "requester_context_set_fingerprint": sha256_json(
                    sorted(sha256_json(value) for value in requester_ids)
                ),
                "permission_scoped_index_fingerprint_set_hash": sha256_json(
                    sorted(
                        {
                            runtime_index_fingerprint,
                            sha256_json("denied-index"),
                        }
                    )
                ),
                "graph_ontology_binding_fingerprint": (
                    post_claim_context.graph_ontology_binding["graph_ontology_binding_fingerprint"]
                ),
            }
            runtime_fingerprint = sha256_json("source-author-runtime")
            runtime = _execution_runtime_binding(
                index_fingerprint=runtime_index_fingerprint,
                runtime_fingerprint=runtime_fingerprint,
                source_identifier_binding=source_identifier_binding,
            )
            preflight = _execution_preflight_report(
                manifest_sha256=manifest_sha,
                runtime_fingerprint=runtime_fingerprint,
                source_identifier_binding=source_identifier_binding,
                oracle_free_projection=projection,
                oracle_free_projection_sha256=projection_sha,
            )
            output_path = root / "all-requesters.safe.json"
            executed_requesters: list[str] = []

            def rebuild_context(**kwargs: object) -> _HoldoutExecutionContext:
                self.assertTrue(holdout_uat._consumed_claim_path(output_path).exists())
                self.assertFalse(output_path.exists())
                self.assertEqual(
                    {str(case["requester_user_id"]) for case in kwargs["cases"]},
                    requester_ids,
                )
                return post_claim_context

            def execute_arms(**kwargs: object) -> tuple[object, ...]:
                executed_requesters.append(str(kwargs["session"].requester_user_id))
                return ()

            arm_summary = {
                "latency_ms": {"p95": 1.0},
                "cost_units": {"maximum": 1},
            }
            with (
                mock.patch.object(
                    holdout_uat,
                    "_build_holdout_execution_context",
                    side_effect=rebuild_context,
                ) as context_builder,
                mock.patch.object(
                    holdout_uat,
                    "_validate_source_author_execution_context_after_claim",
                    return_value=post_claim_binding,
                ) as context_validator,
                mock.patch.object(
                    holdout_uat,
                    "run_holdout_case_arms",
                    side_effect=execute_arms,
                ),
                mock.patch.object(
                    development_uat,
                    "_aggregate_arm",
                    return_value=arm_summary,
                ),
                mock.patch.object(
                    development_uat,
                    "_budget_fairness_report",
                    return_value={
                        "all_full_case_arms_match_per_case": True,
                        "structured_exact_matches_routed_cases": True,
                    },
                ),
                mock.patch.object(
                    holdout_uat,
                    "_holdout_paired_transitions",
                    return_value={},
                ),
                mock.patch.object(
                    development_uat,
                    "_quality_gate_report",
                    return_value={
                        "status": "passed",
                        "checks": {"base": {"status": "passed"}},
                    },
                ),
                mock.patch.object(
                    holdout_uat,
                    "_peak_memory_kib",
                    return_value=1,
                ),
            ):
                report = _execute_independent_holdout_once(
                    preflight_report=preflight,
                    execution_context=preflight_context,
                    bundle=bundle,
                    oracle_free_projection=projection,
                    manifest_path=manifest_path,
                    expected_manifest_sha256=manifest_sha,
                    runtime_binding=runtime,
                    execution_output=output_path,
                )
            context_builder.assert_called_once()
            context_validator.assert_called_once()
            self.assertEqual(len(executed_requesters), EXPECTED_CASE_COUNT)
            self.assertIn("owner_fixture", executed_requesters)
            self.assertIn("denied-requester-0", executed_requesters)
            self.assertIn("denied-requester-1", executed_requesters)
            self.assertEqual(
                report["counts"]["post_claim_requester_context_count"],
                3,
            )
            self.assertEqual(
                report["counts"]["post_claim_denied_requester_context_count"],
                2,
            )
            self.assertEqual(
                report["hashes"]["post_claim_requester_context_set_fingerprint"],
                post_claim_binding["requester_context_set_fingerprint"],
            )
            serialized = output_path.read_text()
            for requester_id in requester_ids:
                self.assertNotIn(requester_id, serialized)

    def test_post_claim_missing_or_tampered_raw_identity_consumes_claim_without_output(
        self,
    ) -> None:
        for mutation in ("missing_requester", "tampered_observation"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (
                    manifest,
                    _manifest_path,
                    _manifest_sha,
                    projection,
                    _projection_sha,
                    _safe_report,
                    bundle,
                    context,
                ) = _source_author_hashed_base_fixture(root)
                changed_manifest = json.loads(json.dumps(manifest))
                if mutation == "missing_requester":
                    changed_manifest["cases"][0].pop("requester_user_id")
                else:
                    changed_manifest["cases"][0]["required_source_observation_ids"][0] = (
                        "missing-raw-observation"
                    )
                    changed_manifest["cases"][0]["authoring_source_observation_ids"][0] = (
                        "missing-raw-observation"
                    )
                changed_manifest["manifest_fingerprint"] = holdout_uat._payload_fingerprint(
                    changed_manifest,
                    "manifest_fingerprint",
                )
                manifest_path = root / f"{mutation}.private.json"
                manifest_sha = _write_json(manifest_path, changed_manifest)
                changed_projection = json.loads(json.dumps(projection))
                changed_projection["private_manifest_binding"].update(
                    {
                        "manifest_sha256": manifest_sha,
                        "manifest_fingerprint": changed_manifest["manifest_fingerprint"],
                        "private_manifest_id": sha256_json(
                            {
                                "artifact_id": holdout_uat.HOLDOUT_ARTIFACT_ID,
                                "manifest_fingerprint": changed_manifest["manifest_fingerprint"],
                            }
                        ),
                    }
                )
                changed_projection["projection_fingerprint"] = holdout_uat._payload_fingerprint(
                    changed_projection,
                    "projection_fingerprint",
                )
                projection_sha = _write_json(
                    root / f"{mutation}.projection.safe.json",
                    changed_projection,
                )
                source_identifier_binding = _source_identifier_binding()
                runtime_fingerprint = sha256_json(f"{mutation}-runtime")
                runtime = _execution_runtime_binding(
                    index_fingerprint=sha256_json(f"{mutation}-index"),
                    runtime_fingerprint=runtime_fingerprint,
                    source_identifier_binding=source_identifier_binding,
                )
                preflight = _execution_preflight_report(
                    manifest_sha256=manifest_sha,
                    runtime_fingerprint=runtime_fingerprint,
                    source_identifier_binding=source_identifier_binding,
                    oracle_free_projection=changed_projection,
                    oracle_free_projection_sha256=projection_sha,
                )
                output_path = root / f"{mutation}.result.safe.json"
                with (
                    mock.patch.object(
                        holdout_uat,
                        "run_holdout_case_arms",
                        side_effect=AssertionError("quality must not start"),
                    ) as quality,
                    self.assertRaisesRegex(
                        IndependentMailHoldoutUatError,
                        (
                            "holdout_private_manifest_raw_lineage_crosswalk_invalid"
                            "|holdout_private_manifest_projection_cross_binding_mismatch"
                        ),
                    ),
                ):
                    _execute_independent_holdout_once(
                        preflight_report=preflight,
                        execution_context=context,
                        bundle=bundle,
                        oracle_free_projection=changed_projection,
                        manifest_path=manifest_path,
                        expected_manifest_sha256=manifest_sha,
                        runtime_binding=runtime,
                        execution_output=output_path,
                    )
                quality.assert_not_called()
                self.assertTrue(holdout_uat._consumed_claim_path(output_path).exists())
                self.assertFalse(output_path.exists())
        with self.assertRaisesRegex(
            IndependentMailHoldoutUatError,
            "holdout_execution_case_count_mismatch",
        ):
            holdout_uat.validate_execution_safety_metrics(
                case_count=49,
                permission_leakage_count=0,
                unresolved_citation_count=0,
                unresolved_graph_hop_count=0,
                exact_incomplete_count=0,
                holdout_policy_id=holdout_uat.EXTENSION_HOLDOUT_POLICY_ID,
            )

    def test_extension_legacy_15_direct_policy_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (
                manifest,
                _manifest_path,
                manifest_sha256,
                projection,
                _projection_path,
                _projection_sha256,
                _context,
                bundle,
                extra_hashes,
            ) = _extension_manifest_projection_fixture(root)

            legacy_manifest = json.loads(json.dumps(manifest))
            legacy_manifest["case_strata_counts"] = dict(
                extension_author.LEGACY_TARGET_STRATA_COUNTS
            )
            legacy_manifest["selection_policy"] = {
                **legacy_manifest["selection_policy"],
                "selection_policy_id": ("issue56_independent_mail_holdout_extension_selection_v1"),
                "target_strata_counts": dict(extension_author.LEGACY_TARGET_STRATA_COUNTS),
            }
            legacy_manifest["selection_policy_fingerprint"] = (
                extension_author.LEGACY_SELECTION_POLICY_FINGERPRINT
            )
            legacy_manifest["capacity_audit_binding"]["target_strata_counts"] = dict(
                extension_author.LEGACY_TARGET_STRATA_COUNTS
            )
            legacy_manifest["capacity_audit_binding"]["capacity_audit_binding_fingerprint"] = (
                holdout_uat._payload_fingerprint(
                    legacy_manifest["capacity_audit_binding"],
                    "capacity_audit_binding_fingerprint",
                )
            )
            legacy_manifest["manifest_fingerprint"] = holdout_uat._payload_fingerprint(
                legacy_manifest,
                "manifest_fingerprint",
            )
            with self.assertRaisesRegex(
                IndependentMailHoldoutUatError,
                "holdout_extension_manifest_boundary_invalid",
            ):
                holdout_uat._validate_extension_private_manifest_boundary(
                    legacy_manifest,
                    holdout_policy=holdout_uat._EXTENSION_HOLDOUT_POLICY,
                )

            legacy_projection = json.loads(json.dumps(projection))
            legacy_projection["strata_counts"] = dict(extension_author.LEGACY_TARGET_STRATA_COUNTS)
            legacy_projection["selection_policy_fingerprint"] = (
                extension_author.LEGACY_SELECTION_POLICY_FINGERPRINT
            )
            legacy_projection["capacity_audit_binding"]["target_strata_counts"] = dict(
                extension_author.LEGACY_TARGET_STRATA_COUNTS
            )
            legacy_projection["capacity_audit_binding"]["capacity_audit_binding_fingerprint"] = (
                holdout_uat._payload_fingerprint(
                    legacy_projection["capacity_audit_binding"],
                    "capacity_audit_binding_fingerprint",
                )
            )
            legacy_projection["projection_fingerprint"] = holdout_uat._payload_fingerprint(
                legacy_projection,
                "projection_fingerprint",
            )
            with self.assertRaisesRegex(
                IndependentMailHoldoutUatError,
                "holdout_extension_projection_invalid",
            ):
                holdout_uat._validate_extension_holdout_projection(
                    **_extension_projection_validation_kwargs(
                        root=root,
                        manifest_sha256=manifest_sha256,
                        projection=legacy_projection,
                        bundle=bundle,
                        extra_hashes=extra_hashes,
                    )
                )

    def test_extension_projection_and_private_lineage_success_fixture(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (
                manifest,
                _manifest_path,
                manifest_sha256,
                projection,
                _projection_path,
                projection_sha256,
                context,
                bundle,
                extra_hashes,
            ) = _extension_manifest_projection_fixture(root)
            lineage = holdout_uat._validate_extension_holdout_projection(
                **_extension_projection_validation_kwargs(
                    root=root,
                    manifest_sha256=manifest_sha256,
                    projection=projection,
                    bundle=bundle,
                    extra_hashes=extra_hashes,
                )
            )
            self.assertEqual(lineage["case_count"], 59)
            self.assertEqual(
                lineage["strata_counts"],
                extension_author.TARGET_STRATA_COUNTS,
            )
            source_identifier_binding = _source_identifier_binding(
                tokenizer_profile_fingerprint=extra_hashes["lexical_profile_fingerprint"]
            )
            runtime_fingerprint = sha256_json("extension-runtime")
            preflight = _execution_preflight_report(
                manifest_sha256=manifest_sha256,
                runtime_fingerprint=runtime_fingerprint,
                source_identifier_binding=source_identifier_binding,
                oracle_free_projection=projection,
                oracle_free_projection_sha256=projection_sha256,
                holdout_policy=holdout_uat._EXTENSION_HOLDOUT_POLICY,
                extra_hashes=extra_hashes,
            )
            holdout_uat._validate_extension_execution_manifest_lineage(
                manifest=manifest,
                projection=projection,
                preflight_report=preflight,
                execution_context=context,
                bundle=bundle,
                holdout_policy=holdout_uat._EXTENSION_HOLDOUT_POLICY,
            )
            serialized_projection = json.dumps(projection, sort_keys=True)
            self.assertNotIn("adjudication", serialized_projection)
            self.assertNotIn("query_text", serialized_projection)
            self.assertEqual(
                preflight["hashes"]["holdout_policy_fingerprint"],
                holdout_uat._EXTENSION_HOLDOUT_POLICY.policy_fingerprint,
            )

    def test_extension_rejects_wrong_case_count_strata_and_tamper(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (
                _manifest,
                _manifest_path,
                manifest_sha256,
                projection,
                _projection_path,
                _projection_sha256,
                _context,
                bundle,
                extra_hashes,
            ) = _extension_manifest_projection_fixture(root)
            kwargs = _extension_projection_validation_kwargs(
                root=root,
                manifest_sha256=manifest_sha256,
                projection=projection,
                bundle=bundle,
                extra_hashes=extra_hashes,
            )

            wrong_count = json.loads(json.dumps(projection))
            wrong_count["cases"] = wrong_count["cases"][:49]
            wrong_count["counts"]["extension_case_count"] = 49
            wrong_count["projection_fingerprint"] = holdout_uat._payload_fingerprint(
                wrong_count,
                "projection_fingerprint",
            )
            with self.assertRaisesRegex(
                IndependentMailHoldoutUatError,
                "holdout_extension_projection_counts_invalid",
            ):
                holdout_uat._validate_extension_holdout_projection(
                    **(kwargs | {"projection": wrong_count})
                )

            wrong_strata = json.loads(json.dumps(projection))
            wrong_strata["strata_counts"]["graph_required"] -= 1
            wrong_strata["strata_counts"]["single_document_direct_lookup"] += 1
            wrong_strata["projection_fingerprint"] = holdout_uat._payload_fingerprint(
                wrong_strata,
                "projection_fingerprint",
            )
            with self.assertRaisesRegex(
                IndependentMailHoldoutUatError,
                "holdout_extension_projection_invalid",
            ):
                holdout_uat._validate_extension_holdout_projection(
                    **(kwargs | {"projection": wrong_strata})
                )

            tampered = json.loads(json.dumps(projection))
            tampered["cases"][0]["route_fingerprint"] = sha256_json("tampered-route")
            tampered["projection_fingerprint"] = holdout_uat._payload_fingerprint(
                tampered,
                "projection_fingerprint",
            )
            with self.assertRaisesRegex(
                IndependentMailHoldoutUatError,
                "holdout_extension_case_route_invalid",
            ):
                holdout_uat._validate_extension_holdout_projection(
                    **(kwargs | {"projection": tampered})
                )

    def test_extension_cross_manifest_projection_swap_fails_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (
                manifest,
                _manifest_path,
                _manifest_sha256,
                projection,
                _projection_path,
                _projection_sha256,
                _context,
                _bundle,
                _extra_hashes,
            ) = _extension_manifest_projection_fixture(root)
            changed = json.loads(json.dumps(manifest))
            changed["time_boundary_fingerprint"] = sha256_json("different-time-boundary")
            changed["manifest_fingerprint"] = holdout_uat._payload_fingerprint(
                changed,
                "manifest_fingerprint",
            )
            changed_path = root / "different-extension-manifest.private.json"
            changed_sha256 = _write_json(changed_path, changed)
            with self.assertRaisesRegex(
                IndependentMailHoldoutUatError,
                "holdout_extension_projection_manifest_binding_mismatch",
            ):
                holdout_uat._decode_private_holdout_manifest_after_claim(
                    manifest_path=changed_path,
                    expected_manifest_sha256=changed_sha256,
                    oracle_free_projection=projection,
                    holdout_policy=holdout_uat._EXTENSION_HOLDOUT_POLICY,
                )

    def test_extension_exact_scoring_uses_protected_identifier_inventory(
        self,
    ) -> None:
        observation = _observation(
            "extension_exact_observation",
            observation_type="email_body_segment",
            occurrence_id="extension_exact_occurrence",
            thread_id="extension_exact_thread",
            text="PO-900001 INV-700001 protected identifier inventory",
            index=1,
        )
        observation_hash = sha256_json(observation.to_dict())
        identifiers = tuple(
            sorted(
                span.exact_token
                for span in holdout_uat.load_issue56_target_mail_tokenizer_profile()
                .analyze(observation.text)
                .protected_identifiers
            )
        )
        identifier_kinds = Counter(
            span.identifier_kind
            for span in holdout_uat.load_issue56_target_mail_tokenizer_profile()
            .analyze(observation.text)
            .protected_identifiers
        )
        items = tuple(
            ExactInventoryItem(
                item_hash=sha256_json(
                    {
                        "inventory_kind": "protected_identifier",
                        "inventory_value": identifier,
                    }
                ),
                cited_observation_hashes=(observation_hash,),
            )
            for identifier in identifiers
        )
        coverage = ExactCoverageContract(
            coverage_fingerprint=sha256_json("extension-exact-coverage"),
            view_revision_fingerprint=sha256_json("extension-exact-view"),
            visible_node_count=len(items),
            inventory_schema_record_count=len(items),
            filter_term_count=1,
            identifier_filter_count=0,
            topic_filter_count=1,
            eligible_record_count=len(items),
            enumerated_record_count=len(items),
            cited_observation_count=1,
            missing_evidence_record_count=0,
            access_required_scope_count=0,
            authorized_scope_complete=True,
            global_scope_complete=True,
            incompleteness_reason_hashes=(),
        )
        exact_result = DeterministicExactExecutionResult(
            status="complete_authorized_scope",
            query_hash=sha256_json("extension-exact-query"),
            plan_fingerprint=sha256_json("extension-exact-plan"),
            operation_hash=sha256_json("inventory_with_count"),
            inventory_kind_hash=sha256_json("protected_identifier"),
            exact_count=len(items),
            returned_item_count=len(items),
            cited_observation_count=1,
            items=items,
            coverage=coverage,
            result_fingerprint=sha256_json(
                {"extension_exact_item_hashes": [item.item_hash for item in items]}
            ),
        )
        case = {
            "result_kind": "exact_aggregation",
            "required_source_observation_ids": [observation.observation_id],
            "private_fingerprint": sha256_json("extension-exact-case"),
        }
        score = score_deterministic_exact_holdout_case(
            case=case,
            expected_private={
                "answer_kind": "exact_aggregation",
                "inventory_kind": "protected_identifier",
                "required_source_observation_ids": [observation.observation_id],
                "counts_by_identifier_kind": dict(sorted(identifier_kinds.items())),
            },
            exact_result=exact_result,
            observations_by_id={observation.observation_id: observation},
            observation_hash_by_id={observation.observation_id: observation_hash},
            bundle=_bundle_fixture([observation]),
            holdout_policy=holdout_uat._EXTENSION_HOLDOUT_POLICY,
        )
        self.assertEqual(score["status"], "passed")
        self.assertTrue(score["inventory_kind_match"])
        self.assertTrue(score["item_set_match"])
        self.assertEqual(score["unresolved_item_citation_count"], 0)

    def test_extension_execute_once_publishes_independent_59_case_output(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (
                manifest,
                manifest_path,
                manifest_sha256,
                projection,
                _projection_sha256,
                context,
                bundle,
                runtime,
                preflight,
            ) = _extension_execution_fixture(root)
            exact_queries = {
                case["query_text"]
                for case in manifest["cases"]
                if str(case["result_kind"]).startswith("exact_")
            }
            fake_answer = SimpleNamespace(
                status="answered",
                citation_hashes=(),
                exact_count=None,
                answer_hash=sha256_json("extension-answer"),
                source_result_fingerprint=sha256_json("extension-source-result"),
                cost_units=1,
            )
            empty_exact_result = _exact_result([], {})

            def arm_results(**kwargs: object) -> tuple[tuple[object, ...], ...]:
                rows: list[tuple[object, ...]] = [
                    (
                        arm_id,
                        SimpleNamespace(exact_result=None),
                        1.0,
                        1.0,
                        sha256_json("budget"),
                    )
                    for arm_id in development_uat.FULL_CASE_ARM_IDS
                ]
                if kwargs["query_text"] in exact_queries:
                    rows.append(
                        (
                            "structured_exact",
                            SimpleNamespace(exact_result=empty_exact_result),
                            1.0,
                            1.0,
                            sha256_json("budget"),
                        )
                    )
                return tuple(rows)

            def score(case: dict[str, object], **kwargs: object) -> dict[str, object]:
                return {
                    "case_manifest_entry_hash": case["private_fingerprint"],
                    "status": "passed",
                    "answer_hash": sha256_json("extension-answer"),
                    "source_result_fingerprint": sha256_json("extension-result"),
                    "forbidden_evidence_match_count": 0,
                    "lineage_audit_unresolved_count": 0,
                    "graph_hop_unresolved_evidence_count": 0,
                    "query_class": (
                        "exact_set_or_inventory"
                        if str(case["result_kind"]).startswith("exact_")
                        else "relation_reasoning"
                        if case["holdout_stratum_id"]
                        in {
                            "graph_required",
                            "no_answer_near_miss_negative",
                        }
                        else "evidence_lookup"
                    ),
                    "positive_required_graph_case": (
                        case["holdout_stratum_id"] == "graph_required"
                    ),
                }

            arm_summary = {
                "latency_ms": {"p95": 1.0},
                "cost_units": {"maximum": 1},
            }
            output_path = root / "extension-result.safe.json"
            with (
                mock.patch.object(
                    holdout_uat,
                    "run_holdout_case_arms",
                    side_effect=arm_results,
                ),
                mock.patch.object(
                    holdout_uat,
                    "render_governed_evidence_answer",
                    return_value=fake_answer,
                ),
                mock.patch.object(
                    development_uat,
                    "_score_case",
                    side_effect=score,
                ),
                mock.patch.object(
                    holdout_uat,
                    "score_deterministic_exact_holdout_case",
                    return_value={
                        "status": "passed",
                        "exact_status": "complete_authorized_scope",
                        "actual_item_count": 2,
                        "duplicate_item_count": 0,
                        "coverage_complete": True,
                    },
                ),
                mock.patch.object(
                    development_uat,
                    "_aggregate_arm",
                    return_value=arm_summary,
                ),
                mock.patch.object(
                    development_uat,
                    "_budget_fairness_report",
                    return_value={
                        "all_full_case_arms_match_per_case": True,
                        "structured_exact_matches_routed_cases": True,
                    },
                ),
                mock.patch.object(
                    holdout_uat,
                    "_holdout_paired_transitions",
                    return_value={},
                ),
                mock.patch.object(
                    development_uat,
                    "_quality_gate_report",
                    return_value={
                        "status": "passed",
                        "checks": {"base": {"status": "passed"}},
                    },
                ),
                mock.patch.object(
                    holdout_uat,
                    "_peak_memory_kib",
                    return_value=1,
                ),
            ):
                report = _execute_independent_holdout_once(
                    preflight_report=preflight,
                    execution_context=context,
                    bundle=bundle,
                    oracle_free_projection=projection,
                    holdout_policy=holdout_uat._EXTENSION_HOLDOUT_POLICY,
                    manifest_path=manifest_path,
                    expected_manifest_sha256=manifest_sha256,
                    runtime_binding=runtime,
                    execution_output=output_path,
                )
            self.assertEqual(report["counts"]["case_count"], 59)
            self.assertEqual(report["counts"]["executed_case_count"], 59)
            self.assertEqual(
                report["hashes"]["holdout_policy_fingerprint"],
                holdout_uat._EXTENSION_HOLDOUT_POLICY.policy_fingerprint,
            )
            self.assertTrue(output_path.exists())
            claim_path = holdout_uat._consumed_claim_path(output_path)
            self.assertTrue(claim_path.exists())
            claim = json.loads(claim_path.read_bytes())
            self.assertEqual(
                claim["hashes"]["holdout_policy_fingerprint"],
                holdout_uat._EXTENSION_HOLDOUT_POLICY.policy_fingerprint,
            )
            self.assertNotEqual(
                holdout_uat._consumed_claim_path(root / "base-result.safe.json"),
                claim_path,
            )

    def test_extension_consumed_claim_race_allows_one_winner(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (
                _manifest,
                _manifest_path,
                manifest_sha256,
                _projection,
                _projection_sha256,
                _context,
                _bundle,
                runtime,
                preflight,
            ) = _extension_execution_fixture(root)
            output_path = root / "extension-race.safe.json"
            receipts: list[object] = []
            errors: list[BaseException] = []
            start = threading.Barrier(3)
            lock = threading.Lock()

            def acquire() -> None:
                start.wait()
                try:
                    receipt = holdout_uat._acquire_consumed_claim(
                        preflight_report=preflight,
                        runtime_binding=runtime,
                        expected_manifest_sha256=manifest_sha256,
                        execution_output=output_path,
                    )
                    with lock:
                        receipts.append(receipt)
                except BaseException as exc:  # noqa: BLE001 - thread result capture
                    with lock:
                        errors.append(exc)

            workers = [threading.Thread(target=acquire) for _ in range(2)]
            for worker in workers:
                worker.start()
            start.wait()
            for worker in workers:
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
            self.assertEqual(len(receipts), 1)
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], IndependentMailHoldoutUatError)
            self.assertEqual(
                str(errors[0]),
                "one_shot_consumed_claim_already_exists",
            )
            self.assertFalse(output_path.exists())
            self.assertTrue(holdout_uat._consumed_claim_path(output_path).exists())

    def test_extension_execution_failure_consumes_claim_without_partial_output(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (
                _manifest,
                manifest_path,
                manifest_sha256,
                projection,
                _projection_sha256,
                context,
                bundle,
                runtime,
                preflight,
            ) = _extension_execution_fixture(root)
            output_path = root / "extension-crash.safe.json"
            with (
                mock.patch.object(
                    holdout_uat,
                    "run_holdout_case_arms",
                    side_effect=RuntimeError("synthetic extension crash"),
                ) as execute,
                self.assertRaisesRegex(
                    RuntimeError,
                    "synthetic extension crash",
                ),
            ):
                _execute_independent_holdout_once(
                    preflight_report=preflight,
                    execution_context=context,
                    bundle=bundle,
                    oracle_free_projection=projection,
                    holdout_policy=holdout_uat._EXTENSION_HOLDOUT_POLICY,
                    manifest_path=manifest_path,
                    expected_manifest_sha256=manifest_sha256,
                    runtime_binding=runtime,
                    execution_output=output_path,
                )
            self.assertEqual(execute.call_count, 1)
            self.assertFalse(output_path.exists())
            self.assertTrue(holdout_uat._consumed_claim_path(output_path).exists())
            with self.assertRaisesRegex(
                IndependentMailHoldoutUatError,
                "one_shot_consumed_claim_already_exists",
            ):
                _execute_independent_holdout_once(
                    preflight_report=preflight,
                    execution_context=context,
                    bundle=bundle,
                    oracle_free_projection=projection,
                    holdout_policy=holdout_uat._EXTENSION_HOLDOUT_POLICY,
                    manifest_path=manifest_path,
                    expected_manifest_sha256=manifest_sha256,
                    runtime_binding=runtime,
                    execution_output=output_path,
                )

    def test_header_and_body_projection_preserves_owner_text_hash_and_lineage(
        self,
    ) -> None:
        header = _observation(
            "observation_header",
            observation_type="email_header",
            occurrence_id="occurrence_one",
            thread_id="thread_one",
            text="Subject: Alpha",
            index=1,
        )
        body = _observation(
            "observation_body",
            observation_type="email_body_segment",
            occurrence_id="occurrence_two",
            thread_id="thread_two",
            text="Body evidence Alpha",
            index=1,
        )
        observations = {observation.observation_id: observation for observation in (header, body)}
        projection = project_validated_holdout_observations(
            observations_by_id=observations,
            observation_ids=set(observations),
            bundle=_bundle_fixture([header, body]),
        )

        self.assertEqual(
            projection["observation_type_counts"],
            {"email_header": 1, "email_body_segment": 1},
        )
        records = {record["observation_id"]: record for record in projection["records"]}
        self.assertEqual(
            records[header.observation_id]["projection_kind"],
            "sealed_email_header_observation",
        )
        self.assertEqual(
            records[body.observation_id]["projection_kind"],
            "preserved_email_body_segment",
        )
        for observation in (header, body):
            record = records[observation.observation_id]
            self.assertEqual(record["raw_safe_text"], observation.text)
            self.assertEqual(record["normalized_text"], observation.text)
            self.assertEqual(
                record["observation_hash"],
                sha256_json(observation.to_dict()),
            )
            self.assertEqual(
                record["store_record_fingerprint"],
                sha256_json(Observation.from_dict(observation.to_dict()).to_dict()),
            )
            self.assertEqual(
                record["source_native_locator"],
                observation.location,
            )
            self.assertEqual(
                record["permission_fingerprint"],
                sha256_json(observation.to_dict()["permission_scope"]),
            )
        self.assertEqual(
            projection["projection_fingerprint"],
            sha256_json(list(projection["records"])),
        )

    def test_exact_set_count_and_aggregation_use_complete_executor_result(
        self,
    ) -> None:
        observations = [
            _observation(
                f"observation_{index}",
                observation_type="email_header",
                occurrence_id=f"occurrence_{index}",
                thread_id=f"thread_{index}",
                text=f"Subject: Exact {index}",
                index=1,
            )
            for index in range(1, 4)
        ]
        observation_by_id = {
            observation.observation_id: observation for observation in observations
        }
        observation_hash_by_id = {
            observation_id: sha256_json(observation.to_dict())
            for observation_id, observation in observation_by_id.items()
        }
        bundle = _bundle_fixture(
            observations,
            senders={
                "message_occurrence_1": "sender-a@example.test",
                "message_occurrence_2": "sender-a@example.test",
                "message_occurrence_3": "sender-b@example.test",
            },
        )
        result = _exact_result(observations, observation_hash_by_id)
        observation_ids = list(observation_by_id)
        message_ids = [f"message_occurrence_{index}" for index in range(1, 4)]
        shared_oracle = {
            "status": "exact_complete",
            "exact_observation_ids": observation_ids,
            "exact_message_ids": message_ids,
            "exact_message_count": 3,
        }
        cases_and_oracles = (
            (
                _case("exact_set", observation_ids),
                shared_oracle | {"exact_set_message_ids": message_ids},
            ),
            (
                _case("exact_count", observation_ids),
                shared_oracle | {"exact_count": 3},
            ),
            (
                _case("exact_aggregation", observation_ids),
                shared_oracle
                | {
                    "group_by": "sender",
                    "groups": [
                        {
                            "sender": "sender-a@example.test",
                            "count": 2,
                            "message_ids": message_ids[:2],
                        },
                        {
                            "sender": "sender-b@example.test",
                            "count": 1,
                            "message_ids": message_ids[2:],
                        },
                    ],
                },
            ),
        )
        for case, oracle in cases_and_oracles:
            with self.subTest(result_kind=case["result_kind"]):
                score = score_deterministic_exact_holdout_case(
                    case=case,
                    expected_private=oracle,
                    exact_result=result,
                    observations_by_id=observation_by_id,
                    observation_hash_by_id=observation_hash_by_id,
                    bundle=bundle,
                )
                self.assertEqual(score["status"], "passed")
                self.assertTrue(score["coverage_complete"])
                self.assertTrue(score["item_set_match"])
                self.assertTrue(score["message_set_match"])
                self.assertTrue(score["aggregation_match"])
                self.assertEqual(score["unresolved_item_citation_count"], 0)

    def test_exact_scorer_fails_closed_on_incomplete_coverage(self) -> None:
        observation = _observation(
            "observation_exact",
            observation_type="email_header",
            occurrence_id="occurrence_exact",
            thread_id="thread_exact",
            text="Subject: Exact",
            index=1,
        )
        observation_hash = sha256_json(observation.to_dict())
        case = _case("exact_count", [observation.observation_id])
        score = score_deterministic_exact_holdout_case(
            case=case,
            expected_private={
                "status": "exact_complete",
                "exact_observation_ids": [observation.observation_id],
                "exact_message_ids": ["message_occurrence_exact"],
                "exact_message_count": 1,
                "exact_count": 1,
            },
            exact_result=_exact_result(
                [observation],
                {observation.observation_id: observation_hash},
                complete=False,
            ),
            observations_by_id={observation.observation_id: observation},
            observation_hash_by_id={observation.observation_id: observation_hash},
            bundle=_bundle_fixture([observation]),
        )
        self.assertEqual(score["status"], "failed")
        self.assertFalse(score["coverage_complete"])

    def test_preflight_projection_is_oracle_free_and_exact_is_not_owner_match(
        self,
    ) -> None:
        no_answer = _case("no_answer", [])
        no_answer["stratum_id"] = "no_answer_near_miss_negative"
        no_answer["forbidden_source_observation_ids"] = ["forbidden"]
        denied = _case("permission_denied", [])
        denied["stratum_id"] = "permission_denied"
        denied["forbidden_source_observation_ids"] = ["forbidden"]
        exact = _case("exact_set", ["observation_exact"])

        no_answer_projection = _adapt_holdout_case_for_development_helpers(no_answer)
        denied_projection = _adapt_holdout_case_for_development_helpers(denied)
        exact_projection = _adapt_holdout_case_for_development_helpers(exact)
        self.assertEqual(no_answer_projection["result_kind"], "no_match")
        self.assertEqual(denied_projection["result_kind"], "permission_denied")
        self.assertEqual(exact_projection["result_kind"], "exact_set")
        self.assertEqual(
            exact_projection["score_adapter"],
            "deterministic_exact",
        )
        for projection in (
            no_answer_projection,
            denied_projection,
            exact_projection,
        ):
            self.assertNotIn("answer_oracle", projection)

    def test_arm_adapter_delegates_to_existing_generic_owner_helper(self) -> None:
        expected = (("strong_rag", object(), 1.0, 1.0, sha256_json("budget")),)
        with mock.patch.object(
            development_uat,
            "_run_case_arms",
            return_value=expected,
        ) as delegated:
            actual = run_holdout_case_arms(
                session=object(),
                effective_graph_view=object(),
                query_text="bounded query",
                result_limit=5,
            )
        self.assertIs(actual, expected)
        delegated.assert_called_once_with(
            session=mock.ANY,
            effective_graph_view=mock.ANY,
            query_text="bounded query",
            result_limit=5,
        )

    def test_source_identifier_v3_binding_supports_both_approved_modes(self) -> None:
        for mode in (
            TENANT_WORKSPACE_IDENTITY_SCOPE_MODE,
            WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
        ):
            with self.subTest(mode=mode):
                complete_binding = _source_identifier_binding(identity_scope_mode=mode)
                identity_scope = SourceIdentifierIdentityScope(
                    identity_scope_mode=mode,
                    identity_scope_fingerprint=str(complete_binding["identity_scope_fingerprint"]),
                    workspace_id="workspace_fixture",
                    identity_scope_attestation_fingerprint=str(
                        complete_binding["identity_scope_attestation_fingerprint"]
                    ),
                    identity_scope_policy_fingerprint=str(
                        complete_binding["identity_scope_policy_fingerprint"]
                    ),
                    operator_approval_fingerprint=str(
                        complete_binding["operator_approval_fingerprint"]
                    ),
                    tenant_id=(
                        "tenant_fixture" if mode == TENANT_WORKSPACE_IDENTITY_SCOPE_MODE else None
                    ),
                    spec_approval_fingerprint=(
                        str(complete_binding["spec_approval_fingerprint"])
                        if mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
                        else None
                    ),
                )
                artifact = {
                    "artifact_fingerprint": complete_binding["source_artifact_fingerprint"],
                    "source_snapshot_fingerprint": complete_binding["source_snapshot_fingerprint"],
                    "source_inventory_fingerprint": complete_binding[
                        "source_inventory_fingerprint"
                    ],
                    "source_observation_hash_set_fingerprint": complete_binding[
                        "source_observation_hash_set_fingerprint"
                    ],
                    "retrieval_snapshot_fingerprint": complete_binding[
                        "retrieval_snapshot_fingerprint"
                    ],
                    "retrieval_report_fingerprint": complete_binding[
                        "retrieval_report_fingerprint"
                    ],
                    "retrieval_snapshot_byte_sha256": complete_binding[
                        "retrieval_snapshot_byte_sha256"
                    ],
                    "retrieval_report_byte_sha256": complete_binding[
                        "retrieval_report_byte_sha256"
                    ],
                    "tokenizer_profile_fingerprint": complete_binding[
                        "candidate_admission_profile_fingerprint"
                    ],
                    "extraction_policy_fingerprint": complete_binding[
                        "extraction_policy_fingerprint"
                    ],
                    "resolution_policy_fingerprint": complete_binding[
                        "resolution_policy_fingerprint"
                    ],
                    "identity_scope_attestation_byte_sha256": complete_binding[
                        "identity_scope_attestation_byte_sha256"
                    ],
                    "attested_asset_fingerprint": complete_binding["attested_asset_fingerprint"],
                    "mention_batch": {
                        "batch_fingerprint": complete_binding["complete_mention_batch_fingerprint"]
                    },
                    "resolution": {
                        "resolution_fingerprint": complete_binding[
                            "complete_resolution_fingerprint"
                        ]
                    },
                    "counts": {
                        "identifier_occurrence_count": 7,
                        "resolved_candidate_count": 3,
                    },
                }
                accepted = holdout_uat._validated_source_identifier_v3_safe_binding(
                    artifact=artifact,
                    expected_artifact_sha256=str(complete_binding["source_artifact_byte_hash"]),
                    identity_scope=identity_scope,
                    projected_batch=SimpleNamespace(
                        batch_fingerprint=complete_binding["selected_mention_batch_fingerprint"],
                        occurrence_count=5,
                    ),
                    selected_resolution=SimpleNamespace(
                        resolution_fingerprint=complete_binding["selected_resolution_fingerprint"],
                        candidate_count=2,
                    ),
                )
                self.assertEqual(
                    accepted["holdout_adapter_fingerprint"],
                    holdout_uat.SOURCE_IDENTIFIER_HOLDOUT_ADAPTER_FINGERPRINT,
                )
                self.assertEqual(accepted["identity_scope_mode_status"], mode)
                self.assertEqual(
                    accepted["candidate_artifact_schema_version"],
                    holdout_uat.CANDIDATE_ARTIFACT_SCHEMA_VERSION,
                )
                serialized = json.dumps(
                    accepted,
                    ensure_ascii=True,
                    sort_keys=True,
                )
                if mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE:
                    self.assertNotIn("tenant", serialized)
                    self.assertIn("spec_approval_fingerprint", accepted)
                else:
                    self.assertNotIn("spec_approval_fingerprint", accepted)

    def test_source_identifier_v3_preflight_rejects_legacy_artifacts(self) -> None:
        complete_binding = _source_identifier_binding()
        artifact = {
            "artifact_id": "formowl_issue56_source_identifier_candidates_private_v2",
            "schema_version": 2,
            "tenant_workspace_fingerprint": sha256_json("legacy"),
        }
        with tempfile.TemporaryDirectory() as directory:
            artifact_path = Path(directory) / "legacy.private.json"
            artifact_sha = _write_json(artifact_path, artifact)
            with self.assertRaisesRegex(
                IndependentMailHoldoutUatError,
                "source_identifier_v3_candidate_artifact_required",
            ):
                holdout_uat._load_holdout_source_identifier_candidate_intake(
                    artifact_path=artifact_path,
                    expected_artifact_sha256=artifact_sha,
                    expected_identity_scope_mode=(TENANT_WORKSPACE_IDENTITY_SCOPE_MODE),
                    expected_identity_scope_fingerprint=str(
                        complete_binding["identity_scope_fingerprint"]
                    ),
                    expected_identity_scope_attestation_sha256=str(
                        complete_binding["identity_scope_attestation_byte_sha256"]
                    ),
                    expected_identity_scope_attestation_fingerprint=str(
                        complete_binding["identity_scope_attestation_fingerprint"]
                    ),
                    expected_identity_scope_policy_fingerprint=str(
                        complete_binding["identity_scope_policy_fingerprint"]
                    ),
                    expected_operator_approval_fingerprint=str(
                        complete_binding["operator_approval_fingerprint"]
                    ),
                    expected_spec_approval_fingerprint=None,
                    expected_workspace_id="workspace_fixture",
                    observations_by_id={},
                    observation_hash_by_id={},
                    retrieval_snapshot={},
                    retrieval_snapshot_sha256=sha256_json("snapshot"),
                    retrieval_report_sha256=sha256_json("report"),
                    retrieval_report_fingerprint=sha256_json("report-fingerprint"),
                )

    def test_preflight_requires_candidate_artifact_and_identity_scope_binding(
        self,
    ) -> None:
        with (
            mock.patch.object(
                holdout_uat,
                "_read_sealed_json",
                side_effect=AssertionError("preflight read before v3 input check"),
            ),
            self.assertRaisesRegex(
                IndependentMailHoldoutUatError,
                "source_identifier_v3_candidate_artifact_required",
            ),
        ):
            holdout_uat.build_independent_mail_holdout_preflight(
                retrieval_bundle_path=Path("bundle"),
                expected_retrieval_bundle_sha256=sha256_json("bundle"),
                retrieval_snapshot_path=Path("snapshot"),
                expected_retrieval_snapshot_sha256=sha256_json("snapshot"),
                source_report_path=Path("source"),
                expected_source_report_sha256=sha256_json("source"),
                development_manifest_path=Path("development"),
                expected_development_manifest_sha256=sha256_json("development"),
                development_report_path=Path("development-safe"),
                expected_development_report_sha256=sha256_json("development-safe"),
                completed_development_quality_report_path=Path("quality"),
                expected_completed_development_quality_report_sha256=(sha256_json("quality")),
                operational_budget_bundle_path=Path("budget"),
                expected_operational_budget_bundle_sha256=sha256_json("budget"),
                holdout_manifest_path=Path("holdout"),
                expected_holdout_manifest_sha256=sha256_json("holdout"),
                holdout_oracle_free_projection_path=Path("holdout-projection"),
                expected_holdout_oracle_free_projection_sha256=sha256_json("holdout-projection"),
                holdout_report_path=Path("holdout-safe"),
                expected_holdout_report_sha256=sha256_json("holdout-safe"),
            )

    def test_candidate_artifact_tamper_profile_and_permission_fail_closed(
        self,
    ) -> None:
        observation = _observation(
            "observation_candidate",
            observation_type="email_header",
            occurrence_id="occurrence_candidate",
            thread_id="thread_candidate",
            text="Subject: Case ABC-123",
            index=1,
        )
        observation_hash = sha256_json(observation.to_dict())
        retrieval_snapshot = {
            "source_snapshot_fingerprint": sha256_json("source-snapshot"),
            "snapshot_fingerprint": sha256_json("retrieval-snapshot"),
            "tokenizer_profile_fingerprint": (ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT),
        }
        source_asset_sha256 = sha256_json("source-asset")
        permission_fingerprint = sha256_json(observation.permission_scope)
        source_inventory = SourceInventory.create(
            source_asset_id=str(observation.asset_id),
            items=(),
            source_fingerprint=source_asset_sha256,
            parser_fingerprint=sha256_json("parser"),
            permission_fingerprint=permission_fingerprint,
            created_at="2026-08-18T12:00:00+00:00",
        )
        retrieval_snapshot |= {
            "source_inventory": source_inventory.to_dict(),
            "source_inventory_fingerprint": sha256_json(source_inventory.to_dict()),
            "source_asset_sha256": source_asset_sha256,
            "permission_fingerprint": permission_fingerprint,
        }
        retrieval_snapshot_sha256 = sha256_json("retrieval-snapshot-bytes")
        retrieval_report_sha256 = sha256_json("retrieval-report-bytes")
        retrieval_report_fingerprint = sha256_json("retrieval-report")
        source_identifier_binding = _source_identifier_binding(
            tokenizer_profile_fingerprint=str(retrieval_snapshot["tokenizer_profile_fingerprint"])
        )
        source_identifier_binding["attested_asset_fingerprint"] = sha256_json(
            {
                "asset_id": source_inventory.source_asset_id,
                "asset_content_hash": source_asset_sha256,
                "workspace_id": "workspace_fixture",
                "permission_fingerprint": permission_fingerprint,
            }
        )
        artifact = _candidate_artifact_fixture(
            source_identifier_binding=source_identifier_binding,
            retrieval_snapshot=retrieval_snapshot,
            retrieval_snapshot_sha256=retrieval_snapshot_sha256,
            observation_hashes=[observation_hash],
        )
        with tempfile.TemporaryDirectory() as directory:
            artifact_path = Path(directory) / "candidate.private.json"
            artifact_sha256 = _write_json(artifact_path, artifact)
            common = {
                "artifact_path": artifact_path,
                "expected_identity_scope_mode": (
                    source_identifier_binding["identity_scope_mode_status"]
                ),
                "expected_identity_scope_fingerprint": (
                    source_identifier_binding["identity_scope_fingerprint"]
                ),
                "expected_identity_scope_attestation_sha256": (
                    source_identifier_binding["identity_scope_attestation_byte_sha256"]
                ),
                "expected_identity_scope_attestation_fingerprint": (
                    source_identifier_binding["identity_scope_attestation_fingerprint"]
                ),
                "expected_identity_scope_policy_fingerprint": (
                    source_identifier_binding["identity_scope_policy_fingerprint"]
                ),
                "expected_operator_approval_fingerprint": (
                    source_identifier_binding["operator_approval_fingerprint"]
                ),
                "expected_spec_approval_fingerprint": None,
                "expected_workspace_id": "workspace_fixture",
                "observations_by_id": {observation.observation_id: observation},
                "observation_hash_by_id": {observation.observation_id: observation_hash},
                "retrieval_snapshot": retrieval_snapshot,
                "retrieval_snapshot_sha256": retrieval_snapshot_sha256,
                "retrieval_report_sha256": retrieval_report_sha256,
                "retrieval_report_fingerprint": retrieval_report_fingerprint,
            }
            with self.assertRaisesRegex(
                IndependentMailHoldoutUatError,
                "source_identifier_candidate_artifact_seal_mismatch",
            ):
                holdout_uat._load_holdout_source_identifier_candidate_intake(
                    expected_artifact_sha256=sha256_json("tampered"),
                    **common,
                )

            profile_drift = dict(artifact)
            profile_drift["tokenizer_profile_fingerprint"] = sha256_json("wrong-profile")
            profile_path = Path(directory) / "profile-drift.private.json"
            profile_sha256 = _write_json(profile_path, profile_drift)
            with (
                mock.patch.object(
                    holdout_uat,
                    "validate_private_identifier_candidate_artifact",
                ),
                self.assertRaisesRegex(
                    IndependentMailHoldoutUatError,
                    "source_identifier_candidate_retrieval_binding_mismatch",
                ),
            ):
                holdout_uat._load_holdout_source_identifier_candidate_intake(
                    **(
                        common
                        | {
                            "artifact_path": profile_path,
                            "expected_artifact_sha256": profile_sha256,
                        }
                    )
                )

            with (
                mock.patch.object(
                    holdout_uat,
                    "validate_private_identifier_candidate_artifact",
                ),
                mock.patch.object(
                    holdout_uat,
                    "_validate_source_identifier_occurrence_bindings",
                    side_effect=IndependentMailHoldoutUatError(
                        "source_identifier_candidate_permission_or_lineage_mismatch"
                    ),
                ),
                self.assertRaisesRegex(
                    IndependentMailHoldoutUatError,
                    "source_identifier_candidate_permission_or_lineage_mismatch",
                ),
            ):
                holdout_uat._load_holdout_source_identifier_candidate_intake(
                    expected_artifact_sha256=artifact_sha256,
                    **common,
                )

    def test_execution_context_uses_explicit_v3_projected_batch_per_requester(
        self,
    ) -> None:
        observation = _observation(
            "observation_context",
            observation_type="email_body_segment",
            occurrence_id="occurrence_context",
            thread_id="thread_context",
            text="Authorized ABC-123 evidence",
            index=1,
        )
        observation_hash = sha256_json(observation.to_dict())
        bundle = SimpleNamespace(
            mail_evidence_bundle_id="bundle_fixture",
            mail_import_session=SimpleNamespace(workspace_id="workspace_fixture"),
        )
        complete_batch = object()
        projected_batches = (object(), object())
        source_identifier_binding = _source_identifier_binding()
        sessions = [
            SimpleNamespace(
                requester_user_id="denied",
                selected_source_scope_ids=("bundle_fixture",),
            ),
            SimpleNamespace(
                requester_user_id="owner",
                selected_source_scope_ids=("bundle_fixture",),
            ),
        ]
        builds = [
            SimpleNamespace(effective_graph_view=object()),
            SimpleNamespace(effective_graph_view=object()),
        ]
        with (
            mock.patch.object(
                holdout_uat,
                "build_authorized_semantic_mail_session",
                side_effect=sessions,
            ) as session_builder,
            mock.patch.object(
                holdout_uat,
                "build_authorized_source_backed_effective_graph_view",
                side_effect=builds,
            ) as graph_builder,
            mock.patch.object(
                holdout_uat,
                "_project_source_identifier_batch_for_session",
                side_effect=projected_batches,
            ) as batch_projector,
            mock.patch.object(
                holdout_uat,
                "build_evidence_identity_lineage_crosswalk",
                side_effect=(object(), object()),
            ),
            mock.patch.object(
                holdout_uat,
                "_graph_ontology_binding",
                return_value=_graph_ontology_binding(
                    source_identifier_binding=source_identifier_binding
                ),
            ),
        ):
            context = holdout_uat._build_holdout_execution_context(
                bundle=bundle,
                observations_by_id={observation.observation_id: observation},
                observation_hash_by_id={observation.observation_id: observation_hash},
                source_binding_fingerprint=sha256_json("source-binding"),
                cases=(
                    {"requester_user_id": "owner"},
                    {"requester_user_id": "denied"},
                ),
                identifier_mention_batch=complete_batch,
                source_identifier_binding=source_identifier_binding,
            )
        self.assertEqual(session_builder.call_count, 2)
        self.assertEqual(batch_projector.call_count, 2)
        self.assertEqual(graph_builder.call_count, 2)
        self.assertEqual(set(context.sessions), {"owner", "denied"})
        actual_projected_batches = []
        for call in graph_builder.call_args_list:
            self.assertEqual(
                call.kwargs["source_graph_policy_id"],
                development_uat.SOURCE_GRAPH_POLICY_ID,
            )
            actual_projected_batches.append(call.kwargs["identifier_mention_batch"])
        self.assertEqual(actual_projected_batches, list(projected_batches))
        self.assertIsNot(actual_projected_batches[0], actual_projected_batches[1])

    def test_development_quality_and_budget_seals_bind_only_all_passed_report(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            completed_path = root / "development.json"
            budget_path = root / "budget.json"
            completed_sha = _write_json(
                completed_path,
                {"artifact_id": "synthetic-development"},
            )
            budget_payload = {
                "status": "passed",
                "budget_fingerprint": holdout_uat.FROZEN_BUDGET_FINGERPRINT,
                "bundle_fingerprint": sha256_json("budget-bundle"),
                "check_set_fingerprint": sha256_json("budget-checks"),
            }
            budget_sha = _write_json(budget_path, budget_payload)
            component = _development_component_binding()
            accepted_report = {
                "status": "passed",
                "quality_gate_status": "passed",
                "quality_gate": {
                    "status": "passed",
                    "checks": {
                        "correctness": {"status": "passed"},
                        "operational_budget": {"status": "passed"},
                    },
                },
                "operational_budget_binding": {
                    "status": "passed",
                    "completed_report_byte_hash": completed_sha,
                    "budget_bundle_byte_hash": budget_sha,
                    "budget_fingerprint": (holdout_uat.FROZEN_BUDGET_FINGERPRINT),
                    "budget_bundle_fingerprint": budget_payload["bundle_fingerprint"],
                    "budget_check_set_fingerprint": budget_payload["check_set_fingerprint"],
                },
            }
            with (
                mock.patch.object(
                    development_uat,
                    "bind_completed_uat_operational_budget",
                    return_value=accepted_report,
                ) as bind,
                mock.patch.object(
                    development_uat,
                    "_validated_completed_uat_component_binding",
                    return_value=component,
                ),
            ):
                acceptance = _validate_development_acceptance(
                    completed_report_path=completed_path,
                    expected_completed_report_sha256=completed_sha,
                    operational_budget_bundle_path=budget_path,
                    expected_operational_budget_bundle_sha256=budget_sha,
                )
            self.assertEqual(acceptance.completed_report_sha256, completed_sha)
            self.assertEqual(
                acceptance.operational_budget_bundle_sha256,
                budget_sha,
            )
            self.assertEqual(
                acceptance.component_binding["component_binding_fingerprint"],
                component["component_binding_fingerprint"],
            )
            bind.assert_called_once()

    def test_development_acceptance_rejects_seal_and_failed_quality_gate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            completed_path = root / "development.json"
            budget_path = root / "budget.json"
            completed_sha = _write_json(completed_path, {"safe": True})
            budget_payload = {
                "status": "passed",
                "budget_fingerprint": holdout_uat.FROZEN_BUDGET_FINGERPRINT,
                "bundle_fingerprint": sha256_json("budget"),
                "check_set_fingerprint": sha256_json("checks"),
            }
            budget_sha = _write_json(budget_path, budget_payload)
            with self.assertRaisesRegex(
                IndependentMailHoldoutUatError,
                "completed_development_quality_report_seal_mismatch",
            ):
                _validate_development_acceptance(
                    completed_report_path=completed_path,
                    expected_completed_report_sha256=sha256_json("wrong"),
                    operational_budget_bundle_path=budget_path,
                    expected_operational_budget_bundle_sha256=budget_sha,
                )

            accepted_report = {
                "status": "quality_failed",
                "quality_gate_status": "failed",
                "quality_gate": {
                    "status": "failed",
                    "checks": {
                        "correctness": {"status": "failed"},
                        "operational_budget": {"status": "passed"},
                    },
                },
                "operational_budget_binding": {
                    "status": "passed",
                    "completed_report_byte_hash": completed_sha,
                    "budget_bundle_byte_hash": budget_sha,
                    "budget_fingerprint": (holdout_uat.FROZEN_BUDGET_FINGERPRINT),
                    "budget_bundle_fingerprint": budget_payload["bundle_fingerprint"],
                    "budget_check_set_fingerprint": budget_payload["check_set_fingerprint"],
                },
            }
            with (
                mock.patch.object(
                    development_uat,
                    "bind_completed_uat_operational_budget",
                    return_value=accepted_report,
                ),
                mock.patch.object(
                    development_uat,
                    "_validated_completed_uat_component_binding",
                    return_value=_development_component_binding(),
                ),
                self.assertRaisesRegex(
                    IndependentMailHoldoutUatError,
                    "development_quality_gate_not_passed",
                ),
            ):
                _validate_development_acceptance(
                    completed_report_path=completed_path,
                    expected_completed_report_sha256=completed_sha,
                    operational_budget_bundle_path=budget_path,
                    expected_operational_budget_bundle_sha256=budget_sha,
                )

    def test_pre_holdout_authority_accepts_only_registered_holdout_blockers(
        self,
    ) -> None:
        state = sha256_json("authority-state")
        execution = sha256_json("authority-execution")
        result = SimpleNamespace(
            authority_valid=True,
            status="blocked",
            methodology_ready=False,
            errors=(),
            execution_fingerprint=execution,
            authority_state_fingerprint=state,
            blocking_gate_ids=("real_user_end_answer_acceptance",),
        )
        component = {
            "status": "blocked",
            "methodology_ready_status": "blocked",
            "authority_state_fingerprint": state,
            "authority_execution_fingerprint": execution,
            "blocking_gate_count": 1,
            "blocking_gate_set_fingerprint": sha256_json(["real_user_end_answer_acceptance"]),
            "source_completeness_gate_status": "passed",
            "real_source_ablation_gate_status": "passed",
        }
        with (
            mock.patch.object(
                holdout_uat,
                "check_methodology_authority",
                return_value=result,
            ),
            mock.patch.object(
                holdout_uat,
                "build_current_authority_component",
                return_value=component,
            ),
        ):
            self.assertEqual(
                _validate_pre_holdout_authority(run_binding_fingerprint=sha256_json("run")),
                component,
            )

        result.blocking_gate_ids = (
            "real_user_end_answer_acceptance",
            "source_completeness_compared_with_raw_oracle",
        )
        with (
            mock.patch.object(
                holdout_uat,
                "check_methodology_authority",
                return_value=result,
            ),
            self.assertRaisesRegex(
                IndependentMailHoldoutUatError,
                "pre_holdout_authority_has_unrelated_blocker",
            ),
        ):
            _validate_pre_holdout_authority(run_binding_fingerprint=sha256_json("run"))

    def test_runtime_fingerprint_binds_actual_graph_and_ontology_revisions(
        self,
    ) -> None:
        acceptance = _development_acceptance()
        component = acceptance.component_binding
        source_identifier_binding = _source_identifier_binding(
            tokenizer_profile_fingerprint=component["lexical_profile_fingerprint"]
        )
        runtime = {
            "lexical_profile_fingerprint": component["lexical_profile_fingerprint"],
            "dense_profile_fingerprint": component["dense_profile_fingerprint"],
            "runtime_component_fingerprint": component["execution_component_fingerprint"],
            "runtime_method_fingerprint": component["runtime_method_fingerprint"],
            "graph_adapter_fingerprint": component["graph_adapter_fingerprint"],
            "ontology_target_fingerprint": component["ontology_target_fingerprint"],
            "answer_model_fingerprint": component["answer_model_fingerprint"],
            "answer_prompt_fingerprint": component["answer_prompt_fingerprint"],
            "answer_budget_fingerprint": component["answer_budget_fingerprint"],
            "evaluator_fingerprint": component["evaluator_fingerprint"],
        }
        code = {
            "artifact_fingerprint": sha256_json("code-attestation"),
            "code_tree_fingerprint": sha256_json("code-tree"),
        }
        image = {
            "artifact_fingerprint": sha256_json("image-attestation"),
            "image_id": holdout_uat.FROZEN_CANONICAL_IMAGE_ID,
            "image_metadata_fingerprint": (holdout_uat.FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT),
        }
        authority = {
            "artifact_fingerprint": sha256_json("authority-attestation"),
            "authority_state_fingerprint": sha256_json("authority-state"),
            "authority_execution_fingerprint": sha256_json("authority-execution"),
            "blocking_gate_set_fingerprint": sha256_json(["real_user_end_answer_acceptance"]),
            "methodology_ready_status": "blocked",
        }
        with (
            mock.patch.object(
                holdout_uat,
                "current_runtime_binding_fingerprints",
                return_value=runtime,
            ),
            mock.patch.object(
                holdout_uat,
                "build_current_code_component",
                return_value=code,
            ),
            mock.patch.object(
                holdout_uat,
                "build_image_component",
                return_value=image,
            ),
            mock.patch.object(
                holdout_uat,
                "_validate_pre_holdout_authority",
                return_value=authority,
            ),
        ):
            first = _build_runtime_binding(
                source_binding_fingerprint=sha256_json("source"),
                index_fingerprint=component["index_fingerprint"],
                tokenizer_profile_fingerprint=component["lexical_profile_fingerprint"],
                execution_contract={"contract": "same"},
                development_acceptance=acceptance,
                graph_ontology_binding=_graph_ontology_binding(
                    "one",
                    source_identifier_binding=source_identifier_binding,
                ),
                source_identifier_binding=source_identifier_binding,
            )
            second = _build_runtime_binding(
                source_binding_fingerprint=sha256_json("source"),
                index_fingerprint=component["index_fingerprint"],
                tokenizer_profile_fingerprint=component["lexical_profile_fingerprint"],
                execution_contract={"contract": "same"},
                development_acceptance=acceptance,
                graph_ontology_binding=_graph_ontology_binding(
                    "two",
                    source_identifier_binding=source_identifier_binding,
                ),
                source_identifier_binding=source_identifier_binding,
            )
            changed_resolution_binding = dict(source_identifier_binding)
            changed_resolution_binding["selected_resolution_fingerprint"] = sha256_json(
                "selected-resolution-changed"
            )
            changed_resolution_binding["binding_fingerprint"] = sha256_json(
                {
                    key: value
                    for key, value in changed_resolution_binding.items()
                    if key != "binding_fingerprint"
                }
            )
            changed_resolution = _build_runtime_binding(
                source_binding_fingerprint=sha256_json("source"),
                index_fingerprint=component["index_fingerprint"],
                tokenizer_profile_fingerprint=component["lexical_profile_fingerprint"],
                execution_contract={"contract": "same"},
                development_acceptance=acceptance,
                graph_ontology_binding=_graph_ontology_binding(
                    "one",
                    source_identifier_binding=changed_resolution_binding,
                ),
                source_identifier_binding=changed_resolution_binding,
            )
        self.assertNotEqual(
            first["runtime_fingerprint"],
            second["runtime_fingerprint"],
        )
        self.assertEqual(
            first["graph_artifact_fingerprint"],
            _graph_ontology_binding(
                "one",
                source_identifier_binding=source_identifier_binding,
            )["graph_artifact_fingerprint"],
        )
        self.assertEqual(
            first["ontology_revision_fingerprint"],
            _graph_ontology_binding(
                "one",
                source_identifier_binding=source_identifier_binding,
            )["ontology_revision_fingerprint"],
        )
        self.assertEqual(
            first["source_identifier_candidate_binding_fingerprint"],
            source_identifier_binding["binding_fingerprint"],
        )
        self.assertEqual(
            first["source_identifier_complete_mention_batch_fingerprint"],
            source_identifier_binding["complete_mention_batch_fingerprint"],
        )
        self.assertEqual(
            first["source_identifier_projected_resolution_fingerprint"],
            source_identifier_binding["selected_resolution_fingerprint"],
        )
        self.assertNotEqual(
            first["runtime_fingerprint"],
            changed_resolution["runtime_fingerprint"],
        )
        self.assertEqual(
            first["consumed_claim_contract_fingerprint"],
            holdout_uat.CONSUMED_CLAIM_CONTRACT_FINGERPRINT,
        )
        self.assertEqual(
            first["execution_output_contract_fingerprint"],
            holdout_uat.EXECUTION_OUTPUT_CONTRACT_FINGERPRINT,
        )

    def test_preflight_reads_private_manifest_bytes_without_json_decode(
        self,
    ) -> None:
        fake_cases = [{"requester_user_id": "owner"}]
        bundle = SimpleNamespace(
            to_dict=lambda: {"bundle": True},
            messages=(),
            body_segments=(),
            mail_import_session=SimpleNamespace(
                owner_user_id="owner",
                workspace_id="workspace_fixture",
            ),
        )
        lineage = {
            "case_count": EXPECTED_CASE_COUNT,
            "strata_counts": holdout_uat.EXPECTED_STRATA_COUNTS,
            "readable_observation_count": 1,
            "observation_type_counts": {
                "email_header": 1,
                "email_body_segment": 0,
            },
            "projected_observation_count": 1,
            "projection_type_counts": {
                "email_header": 1,
                "email_body_segment": 0,
            },
            "projection_fingerprint": sha256_json("observation-projection"),
            "permission_denied_case_count": 2,
            "manifest_fingerprint": sha256_json("holdout-manifest"),
            "private_manifest_id": sha256_json("private-manifest-id"),
            "partition_fingerprint": sha256_json("partition"),
        }
        source_identifier_binding = _source_identifier_binding(
            tokenizer_profile_fingerprint=sha256_json("tokenizer")
        )
        graph_binding = _graph_ontology_binding(source_identifier_binding=source_identifier_binding)
        context = _HoldoutExecutionContext(
            observations_by_bundle_id={},
            observations_by_id={},
            observation_hash_by_id={},
            sessions={},
            effective_graph_views={},
            lineage_crosswalks={},
            graph_builds={},
            graph_ontology_binding=graph_binding,
        )
        runtime = {
            key: sha256_json(key)
            for key in (
                "tokenizer_profile_fingerprint",
                "index_fingerprint",
                "dense_profile_fingerprint",
                "runtime_component_fingerprint",
                "runtime_method_fingerprint",
                "graph_adapter_fingerprint",
                "graph_artifact_fingerprint",
                "graph_revision_fingerprint",
                "graph_revision_id_fingerprint",
                "ontology_target_fingerprint",
                "ontology_artifact_fingerprint",
                "ontology_revision_fingerprint",
                "answer_model_fingerprint",
                "answer_prompt_fingerprint",
                "answer_budget_fingerprint",
                "evaluator_fingerprint",
                "operational_budget_fingerprint",
                "code_attestation_fingerprint",
                "code_tree_fingerprint",
                "image_attestation_fingerprint",
                "image_id",
                "image_metadata_fingerprint",
                "authority_attestation_fingerprint",
                "authority_state_fingerprint",
                "authority_execution_fingerprint",
                "authority_blocking_gate_set_fingerprint",
                "consumed_claim_contract_fingerprint",
                "execution_output_contract_fingerprint",
                "runtime_fingerprint",
            )
        }
        runtime.update(
            _execution_runtime_binding(
                index_fingerprint=sha256_json("index"),
                runtime_fingerprint=runtime["runtime_fingerprint"],
                source_identifier_binding=source_identifier_binding,
            )
        )
        runtime["graph_ontology_binding_fingerprint"] = graph_binding[
            "graph_ontology_binding_fingerprint"
        ]
        source_identifier_intake = holdout_uat._HoldoutSourceIdentifierCandidateIntake(
            projected_batch=object(),
            safe_binding=source_identifier_binding,
            artifact_sha256=str(source_identifier_binding["source_artifact_byte_hash"]),
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "holdout.private.json"
            manifest_payload = {
                "private": True,
                "answer_oracle": {"sentinel": "must-not-be-decoded-before-claim"},
            }
            manifest_sha = _write_json(manifest_path, manifest_payload)
            manifest_bytes = manifest_path.read_bytes()
            oracle_free_projection = {
                "cases": fake_cases,
                "projection_fingerprint": sha256_json("holdout-projection"),
            }
            projection_path = root / "holdout-projection.private.json"
            projection_sha = _write_json(projection_path, oracle_free_projection)

            mocked_reads = iter(
                (
                    (b"bundle", {"bundle": True}),
                    (
                        b"snapshot",
                        {
                            "source_snapshot_fingerprint": sha256_json("source-snapshot"),
                            "source_inventory_fingerprint": sha256_json("source-inventory"),
                            "source_provenance_fingerprint": sha256_json("source-provenance"),
                            "snapshot_fingerprint": sha256_json("snapshot"),
                            "index_fingerprint": sha256_json("index"),
                            "tokenizer_profile_fingerprint": sha256_json("tokenizer"),
                            "counts": {
                                "source_inventory_item_count": 1,
                                "unexplained_loss_count": 0,
                            },
                        },
                    ),
                    (
                        b"source",
                        {"report_fingerprint": sha256_json("retrieval-report")},
                    ),
                    (
                        b"development",
                        {
                            "case_count": 100,
                            "manifest_fingerprint": sha256_json("development"),
                        },
                    ),
                    (b"development-safe", {}),
                    (b"holdout-safe", {}),
                )
            )
            original_read_sealed_json = holdout_uat._read_sealed_json
            real_json_loads = holdout_uat.json.loads
            decoded_payloads: list[bytes | str] = []

            def read_sealed_json(
                path: Path,
                expected_sha256: str,
                **kwargs: object,
            ) -> tuple[bytes, dict[str, object]]:
                if path == projection_path:
                    return original_read_sealed_json(
                        path,
                        expected_sha256,
                        **kwargs,
                    )
                return next(mocked_reads)

            def guarded_json_loads(
                payload: bytes | bytearray | str,
                *args: object,
                **kwargs: object,
            ) -> object:
                normalized = bytes(payload) if isinstance(payload, bytearray) else payload
                decoded_payloads.append(normalized)
                if normalized == manifest_bytes:
                    raise AssertionError("private holdout oracle decoded before claim")
                return real_json_loads(payload, *args, **kwargs)

            with (
                mock.patch.object(
                    holdout_uat,
                    "_read_sealed_json",
                    side_effect=read_sealed_json,
                ),
                mock.patch.object(
                    holdout_uat.json,
                    "loads",
                    side_effect=guarded_json_loads,
                ),
                mock.patch.object(
                    holdout_uat,
                    "_validate_development_acceptance",
                    return_value=_development_acceptance(),
                ),
                mock.patch.object(
                    holdout_uat,
                    "_validated_bundle_artifact",
                    return_value={"bundle": True},
                ),
                mock.patch.object(
                    holdout_uat.MailEvidenceBundle,
                    "from_dict",
                    return_value=bundle,
                ),
                mock.patch.object(holdout_uat, "_validate_native_retrieval_snapshot"),
                mock.patch.object(holdout_uat, "_validate_source_bindings"),
                mock.patch.object(holdout_uat, "_validate_source_report"),
                mock.patch.object(
                    holdout_uat,
                    "_validated_retrieval_observation_maps",
                    return_value=({}, {}),
                ),
                mock.patch.object(
                    holdout_uat,
                    "_load_holdout_source_identifier_candidate_intake",
                    return_value=source_identifier_intake,
                ) as candidate_intake,
                mock.patch.object(
                    holdout_uat,
                    "_validated_development_exclusion_registry",
                    return_value=(frozenset(), sha256_json("registry")),
                ),
                mock.patch.object(
                    holdout_uat,
                    "_validate_holdout_projection",
                    return_value=lineage,
                ),
                mock.patch.object(
                    holdout_uat,
                    "_build_holdout_execution_context",
                    return_value=context,
                ),
                mock.patch.object(
                    holdout_uat,
                    "_build_runtime_binding",
                    return_value=runtime,
                ),
                mock.patch.object(holdout_uat, "_owner_gap_ids", return_value=()),
                mock.patch.object(holdout_uat, "_validate_public_report"),
            ):
                report = holdout_uat.build_independent_mail_holdout_preflight(
                    retrieval_bundle_path=Path("bundle"),
                    expected_retrieval_bundle_sha256=sha256_json("bundle"),
                    retrieval_snapshot_path=Path("snapshot"),
                    expected_retrieval_snapshot_sha256=sha256_json("snapshot"),
                    source_report_path=Path("source"),
                    expected_source_report_sha256=sha256_json("source"),
                    source_identifier_candidate_artifact_path=Path("source-identifier-candidates"),
                    expected_source_identifier_candidate_artifact_sha256=str(
                        source_identifier_binding["source_artifact_byte_hash"]
                    ),
                    expected_identity_scope_mode=str(
                        source_identifier_binding["identity_scope_mode_status"]
                    ),
                    expected_identity_scope_fingerprint=str(
                        source_identifier_binding["identity_scope_fingerprint"]
                    ),
                    expected_identity_scope_attestation_sha256=str(
                        source_identifier_binding["identity_scope_attestation_byte_sha256"]
                    ),
                    expected_identity_scope_attestation_fingerprint=str(
                        source_identifier_binding["identity_scope_attestation_fingerprint"]
                    ),
                    expected_identity_scope_policy_fingerprint=str(
                        source_identifier_binding["identity_scope_policy_fingerprint"]
                    ),
                    expected_operator_approval_fingerprint=str(
                        source_identifier_binding["operator_approval_fingerprint"]
                    ),
                    expected_spec_approval_fingerprint=None,
                    development_manifest_path=Path("development"),
                    expected_development_manifest_sha256=sha256_json("development"),
                    development_report_path=Path("development-safe"),
                    expected_development_report_sha256=sha256_json("development-safe"),
                    completed_development_quality_report_path=Path("quality"),
                    expected_completed_development_quality_report_sha256=sha256_json("quality"),
                    operational_budget_bundle_path=Path("budget"),
                    expected_operational_budget_bundle_sha256=sha256_json("budget"),
                    holdout_manifest_path=manifest_path,
                    expected_holdout_manifest_sha256=manifest_sha,
                    holdout_oracle_free_projection_path=projection_path,
                    expected_holdout_oracle_free_projection_sha256=projection_sha,
                    holdout_report_path=Path("holdout-safe"),
                    expected_holdout_report_sha256=sha256_json("holdout-safe"),
                )
            self.assertEqual(report["quality_result_status"], "not_read")
            self.assertEqual(report["counts"]["sealed_quality_field_read_count"], 0)
            self.assertNotIn(manifest_bytes, decoded_payloads)
            self.assertIn(projection_path.read_bytes(), decoded_payloads)
            self.assertEqual(
                report["hashes"]["holdout_manifest_sha256"],
                manifest_sha,
            )
            self.assertEqual(
                report["hashes"]["holdout_oracle_free_projection_sha256"],
                projection_sha,
            )
            candidate_intake.assert_called_once()

    def test_manifest_and_projection_byte_tamper_fail_before_json_decode(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "holdout.private.json"
            manifest_sha = _write_json(
                manifest_path,
                {"answer_oracle": {"sentinel": "private"}},
            )
            manifest_path.write_bytes(manifest_path.read_bytes() + b" ")
            with (
                mock.patch.object(
                    holdout_uat.json,
                    "loads",
                    side_effect=AssertionError("tampered manifest must not decode"),
                ) as decode,
                self.assertRaisesRegex(
                    IndependentMailHoldoutUatError,
                    "holdout_manifest_seal_mismatch",
                ),
            ):
                holdout_uat._read_sealed_bytes(
                    manifest_path,
                    manifest_sha,
                    max_bytes=holdout_uat.MAX_MANIFEST_BYTES,
                    invalid_reason="holdout_manifest_missing_or_invalid",
                    seal_reason="holdout_manifest_seal_mismatch",
                )
            self.assertEqual(decode.call_count, 0)

            projection_path = root / "holdout-projection.private.json"
            projection_sha = _write_json(
                projection_path,
                {"projection_fingerprint": sha256_json("projection")},
            )
            projection_path.write_bytes(projection_path.read_bytes() + b" ")
            with (
                mock.patch.object(
                    holdout_uat.json,
                    "loads",
                    side_effect=AssertionError("tampered projection must not decode"),
                ) as decode,
                self.assertRaisesRegex(
                    IndependentMailHoldoutUatError,
                    "holdout_oracle_free_projection_seal_mismatch",
                ),
            ):
                holdout_uat._read_sealed_json(
                    projection_path,
                    projection_sha,
                    max_bytes=holdout_uat.MAX_HOLDOUT_PROJECTION_BYTES,
                    invalid_reason="holdout_oracle_free_projection_missing_or_invalid",
                    seal_reason="holdout_oracle_free_projection_seal_mismatch",
                )
            self.assertEqual(decode.call_count, 0)

    def test_execute_claim_consumes_then_rejects_projection_cross_binding_drift(
        self,
    ) -> None:
        cases = [
            {
                "case_id": f"case-{index}",
                "domain": "mail",
                "intent_kind": "relation_reasoning",
                "pattern": "graph_required",
                "stratum_id": "graph_required",
                "result_kind": "owner_match",
                "query_text": "find linked owner",
                "requester_user_id": "owner",
                "required_source_observation_ids": ["observation"],
                "forbidden_source_observation_ids": [],
                "required_match_count": 1,
                "limit": 10,
                "private_fingerprint": sha256_json(f"case-{index}"),
            }
            for index in range(EXPECTED_CASE_COUNT)
        ]
        source_identifier_binding = _source_identifier_binding()
        runtime_fingerprint = sha256_json("runtime")
        runtime = _execution_runtime_binding(
            index_fingerprint=sha256_json("index"),
            runtime_fingerprint=runtime_fingerprint,
            source_identifier_binding=source_identifier_binding,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (
                _manifest,
                manifest_path,
                manifest_sha,
                oracle_free_projection,
                _projection_path,
                _projection_sha,
            ) = _sealed_holdout_manifest_and_projection(root, cases)
            drifted_projection = json.loads(json.dumps(oracle_free_projection))
            drifted_projection["cases"][0]["query_text"] = "tampered query"
            drifted_projection["projection_fingerprint"] = holdout_uat._payload_fingerprint(
                drifted_projection,
                "projection_fingerprint",
            )
            drifted_path = root / "drifted-projection.json"
            drifted_sha = _write_json(drifted_path, drifted_projection)
            preflight = _execution_preflight_report(
                manifest_sha256=manifest_sha,
                runtime_fingerprint=runtime_fingerprint,
                source_identifier_binding=source_identifier_binding,
                oracle_free_projection=drifted_projection,
                oracle_free_projection_sha256=drifted_sha,
            )
            output_path = root / "result.json"
            with (
                mock.patch.object(
                    holdout_uat,
                    "run_holdout_case_arms",
                    side_effect=AssertionError("quality must not start"),
                ) as execute,
                self.assertRaisesRegex(
                    IndependentMailHoldoutUatError,
                    "holdout_private_manifest_projection_cross_binding_mismatch",
                ),
            ):
                _execute_independent_holdout_once(
                    preflight_report=preflight,
                    execution_context=SimpleNamespace(),
                    bundle=SimpleNamespace(),
                    oracle_free_projection=drifted_projection,
                    manifest_path=manifest_path,
                    expected_manifest_sha256=manifest_sha,
                    runtime_binding=runtime,
                    execution_output=output_path,
                )
            self.assertEqual(execute.call_count, 0)
            self.assertFalse(output_path.exists())
            self.assertTrue(holdout_uat._consumed_claim_path(output_path).exists())

    def test_execute_once_is_atomic_immutable_and_emits_safe_aggregate(
        self,
    ) -> None:
        cases = []
        for index in range(EXPECTED_CASE_COUNT):
            result_kind = "exact_count" if index < 3 else "owner_match"
            case = {
                "case_id": f"case-{index}",
                "domain": "mail",
                "intent_kind": (
                    "exact_inventory" if result_kind == "exact_count" else "relation_reasoning"
                ),
                "pattern": ("exact_count" if result_kind == "exact_count" else "graph_required"),
                "stratum_id": ("exact_count" if result_kind == "exact_count" else "graph_required"),
                "result_kind": result_kind,
                "query_text": (
                    "count all items" if result_kind == "exact_count" else "find linked owner"
                ),
                "requester_user_id": "owner",
                "required_source_observation_ids": ["observation"],
                "forbidden_source_observation_ids": [],
                "required_match_count": 1,
                "limit": 10,
                "private_fingerprint": sha256_json(f"case-{index}"),
            }
            if result_kind == "exact_count":
                case["answer_oracle"] = {
                    "secret": f"oracle-{index}",
                }
            cases.append(case)
        index = SimpleNamespace(
            execution_component_fingerprint=sha256_json("component"),
            index_fingerprint=sha256_json("index"),
        )
        context = _HoldoutExecutionContext(
            observations_by_bundle_id={},
            observations_by_id={},
            observation_hash_by_id={},
            sessions={"owner": SimpleNamespace(index=index)},
            effective_graph_views={"owner": object()},
            lineage_crosswalks={"owner": object()},
            graph_builds={},
            graph_ontology_binding=_graph_ontology_binding(),
        )
        fake_answer = SimpleNamespace(
            status="answered",
            citation_hashes=(),
            exact_count=None,
            answer_hash=sha256_json("answer"),
            source_result_fingerprint=sha256_json("source-result"),
            cost_units=1,
        )
        exact_result = _exact_result([], {})

        def arm_results(**kwargs: object) -> tuple[tuple[object, ...], ...]:
            query_text = str(kwargs["query_text"])
            rows: list[tuple[object, ...]] = [
                (
                    arm_id,
                    SimpleNamespace(exact_result=None),
                    1.0,
                    1.0,
                    sha256_json("budget"),
                )
                for arm_id in development_uat.FULL_CASE_ARM_IDS
            ]
            if query_text == "count all items":
                rows.append(
                    (
                        "structured_exact",
                        SimpleNamespace(exact_result=exact_result),
                        1.0,
                        1.0,
                        sha256_json("budget"),
                    )
                )
            return tuple(rows)

        def score(case: dict[str, object], **kwargs: object) -> dict[str, object]:
            return {
                "case_manifest_entry_hash": case["private_fingerprint"],
                "status": "passed",
                "answer_hash": sha256_json("answer"),
                "source_result_fingerprint": sha256_json("result"),
                "forbidden_evidence_match_count": 0,
                "lineage_audit_unresolved_count": 0,
                "graph_hop_unresolved_evidence_count": 0,
                "query_class": (
                    "exact_set_or_inventory"
                    if case["result_kind"] == "exact_count"
                    else "relation_reasoning"
                ),
                "positive_required_graph_case": (case["result_kind"] == "owner_match"),
            }

        arm_summary = {
            "latency_ms": {"p95": 1.0},
            "cost_units": {"maximum": 1},
        }
        runtime_fingerprint = sha256_json("runtime")
        source_identifier_binding = _source_identifier_binding()
        runtime = _execution_runtime_binding(
            index_fingerprint=index.index_fingerprint,
            runtime_fingerprint=runtime_fingerprint,
            source_identifier_binding=source_identifier_binding,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (
                _manifest,
                manifest_path,
                manifest_sha,
                oracle_free_projection,
                _projection_path,
                projection_sha,
            ) = _sealed_holdout_manifest_and_projection(root, cases)
            preflight = _execution_preflight_report(
                manifest_sha256=manifest_sha,
                runtime_fingerprint=runtime_fingerprint,
                source_identifier_binding=source_identifier_binding,
                oracle_free_projection=oracle_free_projection,
                oracle_free_projection_sha256=projection_sha,
            )
            output_path = root / "result.json"
            oracle_reads_after_claim: list[str] = []
            manifest_bytes = manifest_path.read_bytes()
            real_json_loads = holdout_uat.json.loads
            manifest_decode_count = 0

            def guarded_json_loads(
                payload: bytes | bytearray | str,
                *args: object,
                **kwargs: object,
            ) -> object:
                nonlocal manifest_decode_count
                normalized = bytes(payload) if isinstance(payload, bytearray) else payload
                if normalized == manifest_bytes:
                    self.assertTrue(holdout_uat._consumed_claim_path(output_path).exists())
                    self.assertFalse(output_path.exists())
                    manifest_decode_count += 1
                return real_json_loads(payload, *args, **kwargs)

            def read_exact_oracle(
                case: dict[str, object],
                **_kwargs: object,
            ) -> dict[str, object]:
                self.assertTrue(holdout_uat._consumed_claim_path(output_path).exists())
                self.assertFalse(output_path.exists())
                oracle_reads_after_claim.append(str(case["case_id"]))
                return {"sealed": True}

            with (
                mock.patch.object(
                    holdout_uat,
                    "run_holdout_case_arms",
                    side_effect=arm_results,
                ),
                mock.patch.object(
                    holdout_uat,
                    "render_governed_evidence_answer",
                    return_value=fake_answer,
                ),
                mock.patch.object(
                    development_uat,
                    "_score_case",
                    side_effect=score,
                ),
                mock.patch.object(
                    holdout_uat,
                    "score_deterministic_exact_holdout_case",
                    return_value={
                        "status": "passed",
                        "exact_status": "complete_authorized_scope",
                        "actual_item_count": 0,
                        "duplicate_item_count": 0,
                        "coverage_complete": True,
                    },
                ),
                mock.patch.object(
                    holdout_uat,
                    "_exact_case_oracle",
                    side_effect=read_exact_oracle,
                ),
                mock.patch.object(
                    development_uat,
                    "_aggregate_arm",
                    return_value=arm_summary,
                ),
                mock.patch.object(
                    development_uat,
                    "_budget_fairness_report",
                    return_value={
                        "all_full_case_arms_match_per_case": True,
                        "structured_exact_matches_routed_cases": True,
                    },
                ),
                mock.patch.object(
                    holdout_uat,
                    "_holdout_paired_transitions",
                    return_value={},
                ),
                mock.patch.object(
                    development_uat,
                    "_quality_gate_report",
                    return_value={
                        "status": "passed",
                        "checks": {
                            "base": {"status": "passed"},
                            "operational_budget": {"status": "blocked"},
                        },
                    },
                ),
                mock.patch.object(
                    holdout_uat,
                    "_peak_memory_kib",
                    return_value=1,
                ),
                mock.patch.object(
                    holdout_uat.json,
                    "loads",
                    side_effect=guarded_json_loads,
                ),
            ):
                report = _execute_independent_holdout_once(
                    preflight_report=preflight,
                    execution_context=context,
                    bundle=SimpleNamespace(),
                    oracle_free_projection=oracle_free_projection,
                    manifest_path=manifest_path,
                    expected_manifest_sha256=manifest_sha,
                    runtime_binding=runtime,
                    execution_output=output_path,
                )
            self.assertTrue(output_path.exists())
            self.assertEqual(output_path.stat().st_mode & 0o222, 0)
            self.assertEqual(
                json.loads(output_path.read_text()),
                report,
            )
            claim_path = holdout_uat._consumed_claim_path(output_path)
            claim_bytes = claim_path.read_bytes()
            claim = json.loads(claim_bytes)
            self.assertTrue(claim_path.exists())
            self.assertEqual(claim_path.stat().st_mode & 0o222, 0)
            self.assertEqual(claim["status"], "consumed")
            self.assertEqual(claim["retry_policy"], "never")
            self.assertEqual(
                report["hashes"]["consumed_claim_sha256"],
                _sha256_bytes(claim_bytes),
            )
            self.assertEqual(
                report["hashes"]["consumed_claim_fingerprint"],
                claim["hashes"]["claim_fingerprint"],
            )
            self.assertEqual(
                report["hashes"]["execution_output_binding_fingerprint"],
                claim["hashes"]["execution_output_binding_fingerprint"],
            )
            self.assertEqual(
                claim["hashes"]["preflight_report_fingerprint"],
                preflight["hashes"]["report_fingerprint"],
            )
            self.assertEqual(
                claim["hashes"]["runtime_fingerprint"],
                runtime_fingerprint,
            )
            self.assertEqual(
                claim["hashes"]["holdout_manifest_sha256"],
                manifest_sha,
            )
            self.assertEqual(len(oracle_reads_after_claim), 3)
            self.assertEqual(manifest_decode_count, 1)
            self.assertEqual(
                claim["hashes"]["source_identifier_candidate_artifact_sha256"],
                source_identifier_binding["source_artifact_byte_hash"],
            )
            self.assertEqual(
                claim["hashes"]["source_identifier_candidate_binding_fingerprint"],
                source_identifier_binding["binding_fingerprint"],
            )
            self.assertEqual(
                claim["hashes"]["consumed_claim_contract_fingerprint"],
                holdout_uat.CONSUMED_CLAIM_CONTRACT_FINGERPRINT,
            )
            self.assertEqual(
                report["hashes"]["execution_output_contract_fingerprint"],
                holdout_uat.EXECUTION_OUTPUT_CONTRACT_FINGERPRINT,
            )
            self.assertIn(
                "execution_artifact_binding_fingerprint",
                report["hashes"],
            )
            serialized = output_path.read_text()
            self.assertNotIn("oracle-", serialized)
            self.assertNotIn("query_text", serialized)
            with self.assertRaisesRegex(
                IndependentMailHoldoutUatError,
                "one_shot_consumed_claim_already_exists",
            ):
                _execute_independent_holdout_once(
                    preflight_report=preflight,
                    execution_context=context,
                    bundle=SimpleNamespace(),
                    oracle_free_projection=oracle_free_projection,
                    manifest_path=manifest_path,
                    expected_manifest_sha256=manifest_sha,
                    runtime_binding=runtime,
                    execution_output=output_path,
                )

    def test_execute_once_concurrent_claim_allows_only_one_quality_execution(
        self,
    ) -> None:
        cases = [
            {
                "case_id": f"case-{index}",
                "domain": "mail",
                "intent_kind": "relation_reasoning",
                "pattern": "graph_required",
                "stratum_id": "graph_required",
                "result_kind": "owner_match",
                "query_text": "find linked owner",
                "requester_user_id": "owner",
                "required_source_observation_ids": ["observation"],
                "forbidden_source_observation_ids": [],
                "required_match_count": 1,
                "limit": 10,
                "private_fingerprint": sha256_json(f"case-{index}"),
            }
            for index in range(EXPECTED_CASE_COUNT)
        ]
        index = SimpleNamespace(
            execution_component_fingerprint=sha256_json("component"),
            index_fingerprint=sha256_json("index"),
        )
        context = _HoldoutExecutionContext(
            observations_by_bundle_id={},
            observations_by_id={},
            observation_hash_by_id={},
            sessions={"owner": SimpleNamespace(index=index)},
            effective_graph_views={"owner": object()},
            lineage_crosswalks={"owner": object()},
            graph_builds={},
            graph_ontology_binding=_graph_ontology_binding(),
        )
        fake_answer = SimpleNamespace(
            status="answered",
            citation_hashes=(),
            exact_count=None,
            answer_hash=sha256_json("answer"),
            source_result_fingerprint=sha256_json("source-result"),
            cost_units=1,
        )
        first_execution_entered = threading.Event()
        release_first_execution = threading.Event()
        failed_contender_finished = threading.Event()
        invocation_lock = threading.Lock()
        invocation_count = 0

        def arm_results(**kwargs: object) -> tuple[tuple[object, ...], ...]:
            nonlocal invocation_count
            with invocation_lock:
                invocation_count += 1
                first = invocation_count == 1
            if first:
                first_execution_entered.set()
                self.assertTrue(release_first_execution.wait(timeout=5))
            return tuple(
                (
                    arm_id,
                    SimpleNamespace(exact_result=None),
                    1.0,
                    1.0,
                    sha256_json("budget"),
                )
                for arm_id in development_uat.FULL_CASE_ARM_IDS
            )

        def score(case: dict[str, object], **kwargs: object) -> dict[str, object]:
            return {
                "case_manifest_entry_hash": case["private_fingerprint"],
                "status": "passed",
                "answer_hash": sha256_json("answer"),
                "source_result_fingerprint": sha256_json("result"),
                "forbidden_evidence_match_count": 0,
                "lineage_audit_unresolved_count": 0,
                "graph_hop_unresolved_evidence_count": 0,
                "query_class": "relation_reasoning",
                "positive_required_graph_case": True,
            }

        arm_summary = {
            "latency_ms": {"p95": 1.0},
            "cost_units": {"maximum": 1},
        }
        runtime_fingerprint = sha256_json("runtime")
        source_identifier_binding = _source_identifier_binding()
        runtime = _execution_runtime_binding(
            index_fingerprint=index.index_fingerprint,
            runtime_fingerprint=runtime_fingerprint,
            source_identifier_binding=source_identifier_binding,
        )
        reports: list[dict[str, object]] = []
        errors: list[BaseException] = []
        result_lock = threading.Lock()
        start_barrier = threading.Barrier(3)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (
                _manifest,
                manifest_path,
                manifest_sha,
                oracle_free_projection,
                _projection_path,
                projection_sha,
            ) = _sealed_holdout_manifest_and_projection(root, cases)
            preflight = _execution_preflight_report(
                manifest_sha256=manifest_sha,
                runtime_fingerprint=runtime_fingerprint,
                source_identifier_binding=source_identifier_binding,
                oracle_free_projection=oracle_free_projection,
                oracle_free_projection_sha256=projection_sha,
            )
            output_path = root / "result.json"

            def invoke() -> None:
                start_barrier.wait()
                try:
                    report = _execute_independent_holdout_once(
                        preflight_report=preflight,
                        execution_context=context,
                        bundle=SimpleNamespace(),
                        oracle_free_projection=oracle_free_projection,
                        manifest_path=manifest_path,
                        expected_manifest_sha256=manifest_sha,
                        runtime_binding=runtime,
                        execution_output=output_path,
                    )
                    with result_lock:
                        reports.append(report)
                except BaseException as exc:  # noqa: BLE001 - thread result capture
                    with result_lock:
                        errors.append(exc)
                    failed_contender_finished.set()

            with (
                mock.patch.object(
                    holdout_uat,
                    "run_holdout_case_arms",
                    side_effect=arm_results,
                ),
                mock.patch.object(
                    holdout_uat,
                    "render_governed_evidence_answer",
                    return_value=fake_answer,
                ),
                mock.patch.object(
                    development_uat,
                    "_score_case",
                    side_effect=score,
                ),
                mock.patch.object(
                    development_uat,
                    "_aggregate_arm",
                    return_value=arm_summary,
                ),
                mock.patch.object(
                    development_uat,
                    "_budget_fairness_report",
                    return_value={
                        "all_full_case_arms_match_per_case": True,
                        "structured_exact_matches_routed_cases": True,
                    },
                ),
                mock.patch.object(
                    holdout_uat,
                    "_holdout_paired_transitions",
                    return_value={},
                ),
                mock.patch.object(
                    development_uat,
                    "_quality_gate_report",
                    return_value={
                        "status": "passed",
                        "checks": {
                            "base": {"status": "passed"},
                        },
                    },
                ),
                mock.patch.object(
                    holdout_uat,
                    "_peak_memory_kib",
                    return_value=1,
                ),
            ):
                workers = [threading.Thread(target=invoke) for _ in range(2)]
                for worker in workers:
                    worker.start()
                start_barrier.wait()
                self.assertTrue(first_execution_entered.wait(timeout=5))
                self.assertTrue(failed_contender_finished.wait(timeout=5))
                release_first_execution.set()
                for worker in workers:
                    worker.join(timeout=5)
                    self.assertFalse(worker.is_alive())

            self.assertEqual(len(reports), 1)
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], IndependentMailHoldoutUatError)
            self.assertEqual(
                str(errors[0]),
                "one_shot_consumed_claim_already_exists",
            )
            self.assertEqual(invocation_count, EXPECTED_CASE_COUNT)
            self.assertTrue(output_path.exists())
            self.assertTrue(holdout_uat._consumed_claim_path(output_path).exists())

    def test_execution_failure_leaves_no_partial_output(self) -> None:
        case = {
            "case_id": "case",
            "domain": "mail",
            "intent_kind": "relation_reasoning",
            "pattern": "graph_required",
            "result_kind": "owner_match",
            "query_text": "bounded",
            "requester_user_id": "owner",
            "required_source_observation_ids": ["observation"],
            "forbidden_source_observation_ids": [],
            "required_match_count": 1,
            "limit": 10,
            "private_fingerprint": sha256_json("case"),
        }
        cases = [dict(case) for _ in range(EXPECTED_CASE_COUNT)]
        context = _HoldoutExecutionContext(
            observations_by_bundle_id={},
            observations_by_id={},
            observation_hash_by_id={},
            sessions={
                "owner": SimpleNamespace(
                    index=SimpleNamespace(
                        execution_component_fingerprint=sha256_json("component"),
                        index_fingerprint=sha256_json("index"),
                    )
                )
            },
            effective_graph_views={"owner": object()},
            lineage_crosswalks={"owner": object()},
            graph_builds={},
            graph_ontology_binding=_graph_ontology_binding(),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (
                _manifest,
                manifest_path,
                manifest_sha,
                oracle_free_projection,
                _projection_path,
                projection_sha,
            ) = _sealed_holdout_manifest_and_projection(root, cases)
            output_path = root / "result.json"
            runtime_fingerprint = sha256_json("runtime")
            source_identifier_binding = _source_identifier_binding()
            runtime = _execution_runtime_binding(
                index_fingerprint=sha256_json("index"),
                runtime_fingerprint=runtime_fingerprint,
                source_identifier_binding=source_identifier_binding,
            )
            preflight = _execution_preflight_report(
                manifest_sha256=manifest_sha,
                runtime_fingerprint=runtime_fingerprint,
                source_identifier_binding=source_identifier_binding,
                oracle_free_projection=oracle_free_projection,
                oracle_free_projection_sha256=projection_sha,
            )
            with (
                mock.patch.object(
                    holdout_uat,
                    "run_holdout_case_arms",
                    side_effect=RuntimeError("synthetic execution failure"),
                ) as execute,
                self.assertRaisesRegex(
                    RuntimeError,
                    "synthetic execution failure",
                ),
            ):
                _execute_independent_holdout_once(
                    preflight_report=preflight,
                    execution_context=context,
                    bundle=SimpleNamespace(),
                    oracle_free_projection=oracle_free_projection,
                    manifest_path=manifest_path,
                    expected_manifest_sha256=manifest_sha,
                    runtime_binding=runtime,
                    execution_output=output_path,
                )
            self.assertFalse(output_path.exists())
            claim_path = holdout_uat._consumed_claim_path(output_path)
            self.assertTrue(claim_path.exists())
            self.assertEqual(claim_path.stat().st_mode & 0o222, 0)
            with (
                self.assertRaisesRegex(
                    IndependentMailHoldoutUatError,
                    "one_shot_consumed_claim_already_exists",
                ),
            ):
                _execute_independent_holdout_once(
                    preflight_report=preflight,
                    execution_context=context,
                    bundle=SimpleNamespace(),
                    oracle_free_projection=oracle_free_projection,
                    manifest_path=manifest_path,
                    expected_manifest_sha256=manifest_sha,
                    runtime_binding=runtime,
                    execution_output=output_path,
                )
            self.assertEqual(execute.call_count, 1)


if __name__ == "__main__":
    unittest.main()
