from __future__ import annotations

from collections import Counter
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts import issue56_holdout_oracle_free_projection as projection_builder
from scripts import issue56_holdout_source_author_projection_inputs as author_inputs


_RAW_QUERY_MARKER = "PRIVATE_QUERY_SENTINEL_DO_NOT_EMIT"
_RAW_ANSWER_MARKER = "PRIVATE_ANSWER_SENTINEL_DO_NOT_EMIT"
_RAW_EXPECTED_MARKER = "PRIVATE_EXPECTED_SENTINEL_DO_NOT_EMIT"
_RAW_LOCATOR_MARKER = "/private/source/mail/secret-message.eml"
_RAW_IDENTIFIER_MARKER = "CUSTOMER-SECRET-48291"
_REAL_SOURCE_COMPLETENESS_COUNTS = {
    "attachment_content_hash_count": 5645,
    "attachment_embedded_message_count": 4,
    "attachment_export_file_binding_count": 5641,
    "attachment_export_occurrence_count": 5645,
    "attachment_parent_lineage_count": 5645,
    "attachment_separate_export_count": 5178,
    "attachment_source_descriptor_binding_count": 4,
    "attachment_source_inventory_binding_count": 5645,
    "attachment_synthetic_representation_count": 463,
    "blocker_count": 0,
    "failed_record_count": 0,
    "folder_occurrence_count": 3,
    "message_occurrence_count": 2793,
    "message_parent_lineage_count": 2793,
    "message_source_inventory_binding_count": 2793,
    "missing_content_hash_count": 0,
    "missing_parent_lineage_count": 0,
    "missing_source_inventory_binding_count": 0,
    "observation_count": 8443,
    "source_inventory_item_count": 8443,
    "unexplained_loss_count": 0,
    "unsupported_preserved_occurrence_count": 2,
}


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _fingerprint(value: object) -> str:
    return _sha256_bytes(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _contract_fingerprint(value: object) -> str:
    return _sha256_bytes(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _payload_fingerprint(
    value: dict[str, object],
    field_name: str,
) -> str:
    return _fingerprint({key: item for key, item in value.items() if key != field_name})


def _contract_payload_fingerprint(
    value: dict[str, object],
    field_name: str,
) -> str:
    return _contract_fingerprint({key: item for key, item in value.items() if key != field_name})


def _write_json(path: Path, value: object) -> str:
    payload = _canonical_bytes(value)
    path.write_bytes(payload)
    return _sha256_bytes(payload)


def _holdout_case(
    *,
    case_number: int,
    stratum: str,
    result_kind: str,
    required_count: int,
    forbidden_count: int,
) -> dict[str, object]:
    required_ids = [
        f"holdout-observation-{case_number:03d}-required-{index}" for index in range(required_count)
    ]
    forbidden_ids = [
        f"holdout-observation-{case_number:03d}-forbidden-{index}"
        for index in range(forbidden_count)
    ]
    authoring_ids = required_ids or forbidden_ids
    required_message_hashes = [
        _fingerprint(
            {
                "scope": "holdout-message",
                "observation_id": observation_id,
            }
        )
        for observation_id in authoring_ids
    ]
    required_occurrence_hashes = [
        _fingerprint(
            {
                "scope": "holdout-message-occurrence",
                "observation_id": observation_id,
            }
        )
        for observation_id in authoring_ids
    ]
    thread_hashes = [
        _fingerprint(
            {
                "scope": "holdout-thread",
                "case_number": case_number,
            }
        )
    ]
    native_observation_hashes = [
        _fingerprint(
            {
                "scope": "holdout-native-observation",
                "observation_id": observation_id,
            }
        )
        for observation_id in authoring_ids
    ]
    if stratum == "no_answer_near_miss_negative":
        source_evidence_binding: dict[str, object] = {
            "near_miss_source_observation_hash": native_observation_hashes[0],
            "near_miss_source_candidate_fingerprint": _fingerprint(
                {
                    "scope": "near-miss-source-candidate",
                    "case_number": case_number,
                }
            ),
            "near_miss_mutation_fingerprint": _fingerprint(
                {
                    "scope": "near-miss-mutation",
                    "case_number": case_number,
                }
            ),
            "full_source_absence_proof_fingerprint": _fingerprint(
                {
                    "scope": "full-source-absence-proof",
                    "case_number": case_number,
                }
            ),
        }
    elif stratum == "permission_denied":
        source_evidence_binding = {
            "denied_message_hashes": required_message_hashes,
            "denied_message_occurrence_hashes": required_occurrence_hashes,
            "denied_thread_hashes": thread_hashes,
            "denied_observation_hashes": native_observation_hashes,
        }
    else:
        source_evidence_binding = {
            "required_message_hashes": required_message_hashes,
            "required_message_occurrence_hashes": required_occurrence_hashes,
            "required_thread_hashes": thread_hashes,
            "required_observation_hashes": native_observation_hashes,
        }
    case: dict[str, object] = {
        "case_id": f"private-holdout-case-{case_number:03d}",
        "domain": "mail",
        "intent_kind": (
            "relation_reasoning"
            if stratum == "graph_required"
            else "exact_inventory"
            if stratum.startswith("exact_")
            else "evidence_lookup"
        ),
        "pattern": f"private-{stratum}",
        "result_kind": result_kind,
        "query_text": (f"{_RAW_QUERY_MARKER} {_RAW_IDENTIFIER_MARKER} {case_number}"),
        "requester_user_id": f"private-requester-{case_number % 3}",
        "required_source_observation_ids": required_ids,
        "forbidden_source_observation_ids": forbidden_ids,
        "required_match_count": required_count,
        "limit": 10,
        "private_fingerprint": _fingerprint(
            {
                "scope": "private-holdout-case",
                "case_number": case_number,
                "stratum": stratum,
            }
        ),
        "source_evidence_binding": source_evidence_binding,
    }
    if stratum != "graph_required":
        case |= {
            "authoring_source_observation_ids": authoring_ids,
            "stratum_id": stratum,
            "answer_oracle": {
                "answer": f"{_RAW_ANSWER_MARKER}-{case_number}",
                "source_locator": _RAW_LOCATOR_MARKER,
            },
        }
    return case


def _holdout_cases() -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    case_number = 0
    for _ in range(30):
        case_number += 1
        cases.append(
            _holdout_case(
                case_number=case_number,
                stratum="graph_required",
                result_kind="owner_match",
                required_count=2,
                forbidden_count=0,
            )
        )
    for _ in range(4):
        case_number += 1
        cases.append(
            _holdout_case(
                case_number=case_number,
                stratum="single_document_direct_lookup",
                result_kind="source_evidence",
                required_count=1,
                forbidden_count=0,
            )
        )
    for stratum, required_count in (
        ("exact_set", 3),
        ("exact_count", 3),
        ("exact_aggregation", 4),
    ):
        case_number += 1
        cases.append(
            _holdout_case(
                case_number=case_number,
                stratum=stratum,
                result_kind=stratum,
                required_count=required_count,
                forbidden_count=0,
            )
        )
    for _ in range(2):
        case_number += 1
        cases.append(
            _holdout_case(
                case_number=case_number,
                stratum="no_answer_near_miss_negative",
                result_kind="no_answer",
                required_count=0,
                forbidden_count=1,
            )
        )
    for _ in range(2):
        case_number += 1
        cases.append(
            _holdout_case(
                case_number=case_number,
                stratum="permission_denied",
                result_kind="permission_denied",
                required_count=0,
                forbidden_count=1,
            )
        )
    return cases


class _Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.holdout_manifest_path = root / "holdout.private.json"
        self.holdout_preflight_path = root / "holdout-preflight.safe.json"
        self.development_manifest_path = root / "development.private.json"
        self.development_report_path = root / "development.safe.json"
        self.source_bundle_path = root / "source-bundle.private.bin"
        self.source_snapshot_path = root / "source-snapshot.private.bin"
        self.source_report_path = root / "source-report.safe.json"

        self.holdout_cases = _holdout_cases()
        self._build_source_artifacts()

        self.source_report = self._source_report()
        self.source_report_sha256 = _write_json(
            self.source_report_path,
            self.source_report,
        )
        self.source_oracle_bindings = self._source_oracle_bindings()

        self.development_cases = self._development_cases()
        self.development_manifest = self._development_manifest()
        self.development_manifest_sha256 = _write_json(
            self.development_manifest_path,
            self.development_manifest,
        )
        self.development_registry_fingerprint = self._development_registry_fingerprint()
        self.development_report = self._development_report()
        self.development_report_sha256 = _write_json(
            self.development_report_path,
            self.development_report,
        )
        self.development_exclusion_binding = self._development_exclusion_binding()

        self.disjointness = self._disjointness()
        self.holdout_manifest = self._holdout_manifest()
        self.holdout_manifest_sha256 = _write_json(
            self.holdout_manifest_path,
            self.holdout_manifest,
        )
        self.holdout_preflight = self._holdout_preflight()
        self.holdout_preflight_sha256 = _write_json(
            self.holdout_preflight_path,
            self.holdout_preflight,
        )

    def _build_source_artifacts(self) -> None:
        self.source_asset_sha256 = _fingerprint("source-asset-bytes")
        self.native_manifest_fingerprint = _fingerprint("native-manifest")
        self.asset_binding_fingerprint = _fingerprint("asset-binding")
        self.source_ref_fingerprint = _fingerprint("source-ref")
        self.parser_fingerprint = _fingerprint("parser")
        self.permission_fingerprint = _fingerprint("source-permission")
        self.source_provenance_fingerprint = _contract_fingerprint(
            {
                "source_asset_sha256": self.source_asset_sha256,
                "native_manifest_fingerprint": self.native_manifest_fingerprint,
                "source_ref_fingerprint": self.source_ref_fingerprint,
                "asset_binding_fingerprint": self.asset_binding_fingerprint,
                "parser_fingerprint": self.parser_fingerprint,
            }
        )
        self.development_observation_ids = [
            f"development-observation-{index:03d}" for index in range(200)
        ]
        self.development_occurrence_ids = [
            (
                f"development-occurrence-{index:03d}"
                if index < 189
                else f"development-occurrence-{index - 189:03d}"
            )
            for index in range(200)
        ]
        occurrence_ids = sorted(set(self.development_occurrence_ids))
        self.development_occurrence_to_message = {
            occurrence_id: f"development-message-{index:03d}"
            for index, occurrence_id in enumerate(occurrence_ids)
        }
        self.development_occurrence_to_email_message = {
            occurrence_id: f"development-email-record-{index:03d}"
            for index, occurrence_id in enumerate(occurrence_ids)
        }
        self.development_message_to_thread = {
            message_id: f"development-thread-{index // 2:03d}"
            for index, message_id in enumerate(self.development_occurrence_to_message.values())
        }
        self.development_occurrence_to_thread = {
            occurrence_id: self.development_message_to_thread[message_id]
            for occurrence_id, message_id in self.development_occurrence_to_message.items()
        }
        holdout_observation_ids = [
            observation_id
            for case in self.holdout_cases
            for observation_id in case.get(
                "authoring_source_observation_ids",
                case["required_source_observation_ids"] or case["forbidden_source_observation_ids"],
            )
        ]
        self.assert_equal_for_fixture(len(holdout_observation_ids), 78)
        self.assert_equal_for_fixture(len(set(holdout_observation_ids)), 78)
        shared_occurrence_observation_ids = set(holdout_observation_ids[64:66])
        holdout_observation_to_occurrence: dict[str, str] = {}
        holdout_occurrence_order: list[str] = []
        for index, observation_id in enumerate(holdout_observation_ids):
            occurrence_id = (
                "holdout-occurrence-shared"
                if observation_id in shared_occurrence_observation_ids
                else f"holdout-occurrence-{index:03d}"
            )
            holdout_observation_to_occurrence[observation_id] = occurrence_id
            if occurrence_id not in holdout_occurrence_order:
                holdout_occurrence_order.append(occurrence_id)
        self.assert_equal_for_fixture(len(holdout_occurrence_order), 77)
        holdout_occurrence_to_message = {
            occurrence_id: f"holdout-message-{index:03d}"
            for index, occurrence_id in enumerate(holdout_occurrence_order)
        }
        holdout_occurrence_to_message[holdout_occurrence_order[1]] = holdout_occurrence_to_message[
            holdout_occurrence_order[0]
        ]
        holdout_occurrence_to_email_message = {
            occurrence_id: f"holdout-email-record-{index:03d}"
            for index, occurrence_id in enumerate(holdout_occurrence_order)
        }
        holdout_occurrence_to_thread = {
            occurrence_id: f"holdout-thread-{index:03d}"
            for index, occurrence_id in enumerate(holdout_occurrence_order)
        }
        for case in self.holdout_cases[:2]:
            case_observation_ids = case["required_source_observation_ids"]
            first_occurrence = holdout_observation_to_occurrence[case_observation_ids[0]]
            second_occurrence = holdout_observation_to_occurrence[case_observation_ids[1]]
            holdout_occurrence_to_thread[second_occurrence] = holdout_occurrence_to_thread[
                first_occurrence
            ]
        holdout_message_to_thread: dict[str, str] = {}
        for occurrence_id, message_id in holdout_occurrence_to_message.items():
            thread_id = holdout_occurrence_to_thread[occurrence_id]
            previous_thread_id = holdout_message_to_thread.setdefault(message_id, thread_id)
            self.assert_equal_for_fixture(previous_thread_id, thread_id)
        self.assert_equal_for_fixture(
            len(set(holdout_occurrence_to_message.values())),
            76,
        )
        self.assert_equal_for_fixture(
            len(set(holdout_occurrence_to_email_message.values())),
            77,
        )
        self.assert_equal_for_fixture(len(set(holdout_occurrence_to_thread.values())), 75)
        self.holdout_observation_to_occurrence = holdout_observation_to_occurrence
        self.holdout_occurrence_to_message = holdout_occurrence_to_message
        self.holdout_occurrence_to_email_message = holdout_occurrence_to_email_message
        self.holdout_occurrence_to_thread = holdout_occurrence_to_thread
        self.holdout_message_to_thread = holdout_message_to_thread

        self.development_observation_rows = [
            self._parsed_observation_row(
                observation_id=observation_id,
                observation_type="email_body_segment",
                occurrence_id=occurrence_id,
                message_id=self.development_occurrence_to_message[occurrence_id],
                thread_id=self.development_occurrence_to_thread[occurrence_id],
                index=index,
            )
            for index, (observation_id, occurrence_id) in enumerate(
                zip(
                    self.development_observation_ids,
                    self.development_occurrence_ids,
                    strict=True,
                )
            )
        ]
        self.holdout_observation_rows = [
            self._parsed_observation_row(
                observation_id=observation_id,
                observation_type=("email_header" if index < 17 else "email_body_segment"),
                occurrence_id=holdout_observation_to_occurrence[observation_id],
                message_id=holdout_occurrence_to_message[
                    holdout_observation_to_occurrence[observation_id]
                ],
                thread_id=holdout_occurrence_to_thread[
                    holdout_observation_to_occurrence[observation_id]
                ],
                index=200 + index,
            )
            for index, observation_id in enumerate(holdout_observation_ids)
        ]
        all_observation_rows = self.development_observation_rows + self.holdout_observation_rows
        all_occurrence_to_message = (
            self.development_occurrence_to_message | holdout_occurrence_to_message
        )
        all_occurrence_to_email_message = (
            self.development_occurrence_to_email_message | holdout_occurrence_to_email_message
        )
        all_occurrence_to_thread = (
            self.development_occurrence_to_thread | holdout_occurrence_to_thread
        )
        self.source_message_occurrence_count = len(all_occurrence_to_message)
        self.source_inventory_item_count = 1 + self.source_message_occurrence_count
        bundle = {
            "folder_occurrences": [
                {
                    "folder_occurrence_id": "synthetic-folder-occurrence",
                }
            ],
            "body_segments": [
                {
                    "source_observation_id": row["observation_id"],
                    "message_occurrence_id": row["location"]["message_occurrence_id"],
                    "email_message_id": all_occurrence_to_email_message[
                        row["location"]["message_occurrence_id"]
                    ],
                }
                for row in all_observation_rows
                if row["observation_type"] == "email_body_segment"
            ],
            "message_occurrences": [
                {
                    "message_occurrence_id": occurrence_id,
                    "message_id": message_id,
                    "email_message_id": all_occurrence_to_email_message[occurrence_id],
                    "thread_id": all_occurrence_to_thread[occurrence_id],
                }
                for occurrence_id, message_id in all_occurrence_to_message.items()
            ],
            "messages": [
                {
                    "message_id": all_occurrence_to_message[occurrence_id],
                    "email_message_id": email_message_id,
                    "thread_id": all_occurrence_to_thread[occurrence_id],
                }
                for occurrence_id, email_message_id in all_occurrence_to_email_message.items()
            ],
            "attachment_occurrences": [],
            "attachments": [],
        }
        self._bind_holdout_case_lineage(
            observation_rows=self.holdout_observation_rows,
            observation_to_occurrence=holdout_observation_to_occurrence,
            occurrence_to_email_message=holdout_occurrence_to_email_message,
            occurrence_to_thread=holdout_occurrence_to_thread,
        )
        bundle_fingerprint = _contract_fingerprint(bundle)
        source_occurrence_observations = [{"observation_type": "mail_folder_occurrence"}] + [
            {"observation_type": "email_message_occurrence"} for _ in all_occurrence_to_message
        ]
        source_inventory_items = [
            {"source_local_key": f"synthetic-source-item-{index:03d}"}
            for index in range(len(source_occurrence_observations))
        ]
        self.source_snapshot: dict[str, object] = {
            "artifact_id": ("formowl_issue56_native_source_complete_retrieval_ready_snapshot_v1"),
            "schema_version": 1,
            "status": "passed",
            "claim_boundary_status": "retrieval_ready_evidence_not_canonical_fact",
            "source_snapshot_fingerprint": _fingerprint("source-snapshot"),
            "source_asset_sha256": self.source_asset_sha256,
            "native_manifest_fingerprint": self.native_manifest_fingerprint,
            "source_inventory_fingerprint": _fingerprint("source-inventory"),
            "source_provenance_fingerprint": self.source_provenance_fingerprint,
            "permission_fingerprint": self.permission_fingerprint,
            "mail_evidence_bundle_fingerprint": bundle_fingerprint,
            "tokenizer_profile_fingerprint": _fingerprint("candidate-admission-profile"),
            "index_fingerprint": _fingerprint("source-index"),
            "parsed_mail_observations": all_observation_rows,
            "source_inventory": {
                "items": source_inventory_items,
                "parser_fingerprint": self.parser_fingerprint,
                "permission_fingerprint": self.permission_fingerprint,
            },
            "source_occurrence_observations": source_occurrence_observations,
            "counts": {
                "mail_bundle_message_occurrence_count": len(bundle["message_occurrences"]),
                "mail_bundle_message_count": len(bundle["messages"]),
                "mail_bundle_attachment_occurrence_count": len(bundle["attachment_occurrences"]),
                "mail_bundle_attachment_count": len(bundle["attachments"]),
                "mail_bundle_body_segment_count": len(bundle["body_segments"]),
                "parsed_message_observation_count": len(bundle["message_occurrences"]),
                "parsed_attachment_observation_count": len(bundle["attachment_occurrences"]),
                "parsed_body_segment_observation_count": len(bundle["body_segments"]),
                "parsed_folder_observation_count": len(bundle["folder_occurrences"]),
                "source_inventory_item_count": len(source_inventory_items),
                "source_occurrence_observation_count": len(source_occurrence_observations),
                "missing_source_inventory_binding_count": 0,
                "missing_source_local_key_binding_count": 0,
                "missing_content_hash_binding_count": 0,
                "missing_permission_binding_count": 0,
                "unexplained_loss_count": 0,
                "blocker_count": 0,
            },
            "blocker_fingerprints": [],
        }
        self.source_snapshot["snapshot_fingerprint"] = _contract_payload_fingerprint(
            self.source_snapshot,
            "snapshot_fingerprint",
        )
        source_snapshot_bytes = _canonical_bytes(self.source_snapshot)
        self.source_snapshot_path.write_bytes(source_snapshot_bytes)
        self.source_snapshot_sha256 = _sha256_bytes(source_snapshot_bytes)

        source_bundle_artifact: dict[str, object] = {
            "artifact_id": "formowl_issue56_native_mail_evidence_bundle_v1",
            "schema_version": 1,
            "status": "passed",
            "source_snapshot_fingerprint": _fingerprint("source-snapshot"),
            "source_inventory_fingerprint": _fingerprint("source-inventory"),
            "source_provenance_fingerprint": self.source_provenance_fingerprint,
            "bundle": bundle,
            "bundle_fingerprint": bundle_fingerprint,
        }
        source_bundle_artifact["artifact_fingerprint"] = _contract_payload_fingerprint(
            source_bundle_artifact,
            "artifact_fingerprint",
        )
        self.source_bundle_artifact = source_bundle_artifact
        source_bundle_bytes = _canonical_bytes(source_bundle_artifact)
        self.source_bundle_path.write_bytes(source_bundle_bytes)
        self.source_bundle_sha256 = _sha256_bytes(source_bundle_bytes)

    def _parsed_observation_row(
        self,
        *,
        observation_id: str,
        observation_type: str,
        occurrence_id: str,
        message_id: str,
        thread_id: str,
        index: int,
    ) -> dict[str, object]:
        native_lineage: dict[str, object] = {
            "message_occurrence_id": occurrence_id,
            "message_id": message_id,
            "thread_id": thread_id,
            "source_provenance_fingerprint": self.source_provenance_fingerprint,
        }
        if observation_type == "email_header":
            native_lineage |= {
                "header_index": index,
                "header_name": "synthetic-header",
            }
            payload_extension = {
                "header_name": "synthetic-header",
                "header_value": f"合成標頭 {index:03d}",
            }
        else:
            native_lineage |= {"body_segment_index": index}
            payload_extension = {"body_segment_index": index}
        return {
            "observation_id": observation_id,
            "observation_type": observation_type,
            "source_ref": f"safe-source-ref-{index:03d}",
            "text": f"合成證據 {index:03d}",
            "permission_scope": {"workspace_ids": ["workspace-formowl"]},
            "location": dict(native_lineage),
            "payload": dict(native_lineage) | payload_extension,
        }

    def _bind_holdout_case_lineage(
        self,
        *,
        observation_rows: list[dict[str, object]],
        observation_to_occurrence: dict[str, str],
        occurrence_to_email_message: dict[str, str],
        occurrence_to_thread: dict[str, str],
    ) -> None:
        row_by_observation_id = {str(row["observation_id"]): row for row in observation_rows}
        for case in self.holdout_cases:
            authoring_ids = case.get(
                "authoring_source_observation_ids",
                case["required_source_observation_ids"] or case["forbidden_source_observation_ids"],
            )
            occurrence_ids = [
                observation_to_occurrence[observation_id] for observation_id in authoring_ids
            ]
            message_ids = [
                occurrence_to_email_message[occurrence_id] for occurrence_id in occurrence_ids
            ]
            thread_ids = [occurrence_to_thread[occurrence_id] for occurrence_id in occurrence_ids]
            binding = case["source_evidence_binding"]
            binding["candidate_fingerprint"] = _fingerprint(
                {
                    "scope": "holdout-candidate",
                    "case_id": case["case_id"],
                }
            )
            binding["partition_fingerprint"] = _fingerprint("holdout-partition")
            observation_hashes = sorted(
                _contract_fingerprint(row_by_observation_id[observation_id])
                for observation_id in authoring_ids
            )
            occurrence_hashes = sorted(_contract_fingerprint(value) for value in occurrence_ids)
            message_hashes = sorted({_contract_fingerprint(value) for value in message_ids})
            thread_hashes = sorted(_contract_fingerprint(value) for value in thread_ids)
            stratum = str(case.get("stratum_id", "graph_required"))
            if stratum == "no_answer_near_miss_negative":
                binding.pop("candidate_fingerprint")
                binding["near_miss_source_observation_hash"] = observation_hashes[0]
            elif stratum == "permission_denied":
                binding |= {
                    "denied_observation_hashes": observation_hashes,
                    "denied_message_occurrence_hashes": occurrence_hashes,
                    "denied_message_hashes": message_hashes,
                    "denied_thread_hashes": sorted(set(thread_hashes)),
                    "permission_fingerprint": self.permission_fingerprint,
                }
            else:
                binding |= {
                    "required_observation_hashes": observation_hashes,
                    "required_message_occurrence_hashes": occurrence_hashes,
                    "required_message_hashes": message_hashes,
                    "required_thread_hashes": (
                        sorted(set(thread_hashes))
                        if stratum.startswith("exact_")
                        else thread_hashes
                    ),
                }
                if stratum.startswith("exact_"):
                    binding["complete_source_identifier_occurrence_count"] = len(authoring_ids)

    def _development_cases(self) -> list[dict[str, object]]:
        observation_hashes = {
            str(row["observation_id"]): _contract_fingerprint(row)
            for row in self.development_observation_rows
        }
        cases: list[dict[str, object]] = []
        for case_number in range(100):
            required_ids = self.development_observation_ids[2 * case_number : 2 * case_number + 2]
            required_occurrence_ids = self.development_occurrence_ids[
                2 * case_number : 2 * case_number + 2
            ]
            case: dict[str, object] = {
                "case_id": f"private-development-case-{case_number + 1:03d}",
                "domain": "mail_business_identifier",
                "forbidden_source_observation_ids": [],
                "intent_kind": "relation_reasoning",
                "limit": 10,
                "pattern": "shared_protected_identifier_cross_message_relation_v1",
                "query_text": f"合成開發查詢 {case_number + 1:03d}",
                "requester_user_id": "development-owner",
                "required_match_count": 2,
                "required_source_observation_ids": required_ids,
                "result_kind": "owner_match",
                "source_evidence_binding": {
                    "candidate_fingerprint": _contract_fingerprint(
                        {
                            "scope": "development-candidate",
                            "case_number": case_number + 1,
                        }
                    ),
                    "required_message_occurrence_hashes": sorted(
                        _contract_fingerprint(occurrence_id)
                        for occurrence_id in required_occurrence_ids
                    ),
                    "required_observation_hashes": sorted(
                        observation_hashes[observation_id] for observation_id in required_ids
                    ),
                },
            }
            case["private_fingerprint"] = _contract_fingerprint(case)
            cases.append(case)
        return cases

    def _source_report(self) -> dict[str, object]:
        report: dict[str, object] = {
            "artifact_id": author_inputs.SOURCE_REPORT_ARTIFACT_ID,
            "schema_version": 1,
            "status": "passed",
            "source_completeness_gate_status": "eligible",
            "claim_boundary_status": "source_complete_observation_snapshot_only",
            "methodology_readiness_status": "blocked",
            "canonical_fact_status": "not_asserted",
            "source_asset_sha256": self.source_asset_sha256,
            "native_manifest_fingerprint": self.native_manifest_fingerprint,
            "asset_binding_fingerprint": self.asset_binding_fingerprint,
            "permission_fingerprint": self.source_snapshot["permission_fingerprint"],
            "source_ref_fingerprint": self.source_ref_fingerprint,
            "parser_fingerprint": self.parser_fingerprint,
            "source_inventory_fingerprint": self.source_bundle_artifact[
                "source_inventory_fingerprint"
            ],
            "observation_snapshot_fingerprint": _fingerprint("source-observation-snapshot"),
            "message_lineage_fingerprint": _fingerprint("message-lineage"),
            "attachment_lineage_fingerprint": _fingerprint("attachment-lineage"),
            "folder_lineage_fingerprint": _fingerprint("folder-lineage"),
            "unsupported_lineage_fingerprint": _fingerprint("unsupported-lineage"),
            "snapshot_fingerprint": self.source_snapshot["source_snapshot_fingerprint"],
            "blocker_fingerprints": [],
            "round_trip_status": "passed",
            "counts": {
                "folder_occurrence_count": 1,
                "message_occurrence_count": self.source_message_occurrence_count,
                "attachment_export_occurrence_count": 0,
                "attachment_separate_export_count": 0,
                "attachment_embedded_message_count": 0,
                "attachment_synthetic_representation_count": 0,
                "attachment_source_descriptor_binding_count": 0,
                "attachment_export_file_binding_count": 0,
                "attachment_source_inventory_binding_count": 0,
                "attachment_parent_lineage_count": 0,
                "attachment_content_hash_count": 0,
                "message_source_inventory_binding_count": (self.source_message_occurrence_count),
                "message_parent_lineage_count": self.source_message_occurrence_count,
                "unsupported_preserved_occurrence_count": 0,
                "source_inventory_item_count": self.source_inventory_item_count,
                "observation_count": self.source_inventory_item_count,
                "missing_source_inventory_binding_count": 0,
                "missing_parent_lineage_count": 0,
                "missing_content_hash_count": 0,
                "unexplained_loss_count": 0,
                "failed_record_count": 0,
                "blocker_count": 0,
            },
        }
        report["report_fingerprint"] = _contract_payload_fingerprint(
            report,
            "report_fingerprint",
        )
        return report

    def _source_oracle_bindings(self) -> dict[str, object]:
        return {
            "bundle_artifact_sha256": self.source_bundle_sha256,
            "bundle_artifact_fingerprint": self.source_bundle_artifact["artifact_fingerprint"],
            "mail_evidence_bundle_fingerprint": self.source_bundle_artifact["bundle_fingerprint"],
            "retrieval_snapshot_sha256": self.source_snapshot_sha256,
            "source_report_sha256": self.source_report_sha256,
            "source_snapshot_fingerprint": self.source_snapshot["source_snapshot_fingerprint"],
            "source_inventory_fingerprint": self.source_snapshot["source_inventory_fingerprint"],
            "source_provenance_fingerprint": self.source_snapshot["source_provenance_fingerprint"],
            "index_fingerprint": self.source_snapshot["index_fingerprint"],
            "tokenizer_profile_fingerprint": self.source_snapshot["tokenizer_profile_fingerprint"],
            "native_source_manifest_fingerprint": _fingerprint("real-v2-source-binding-extension"),
            "source_author_permission_fingerprint": _fingerprint(
                "real-v2-source-author-permission-extension"
            ),
        }

    def _development_manifest(self) -> dict[str, object]:
        selection_policy = {
            "anchor_message_frequency_maximum": 8,
            "anchor_policy": (
                "lowest_document_frequency_nonprotected_token_per_exact_body_observation"
            ),
            "case_count": 100,
            "classification": "development_not_holdout",
            "holdout_or_oracle_content_read": False,
            "identifier_message_frequency": {
                "minimum": 2,
                "maximum": 6,
            },
            "observation_reuse": "forbidden",
            "pair_policy": (
                "two_distinct_message_occurrences_with_one_shared_protected_identifier"
            ),
            "policy_id": "issue56_source_development_relation_owner_match_selection_v1",
            "quality_result_read": False,
            "query_template_id": "cross_message_relationship_identifier_two_anchors_v1",
            "required_match_count": 2,
            "result_limit": 10,
            "selection_order": "stratum_round_robin_then_hash",
            "source_kind": "authorized_retrieval_ready_mail_body_observation",
        }
        strata = {
            "amount": 17,
            "business_identifier": 17,
            "date": 17,
            "domain": 17,
            "email": 16,
            "url": 16,
        }
        manifest: dict[str, object] = {
            "archive_sha256": _fingerprint("development-archive"),
            "artifact_id": author_inputs.DEVELOPMENT_MANIFEST_ARTIFACT_ID,
            "case_count": 100,
            "case_strata_counts": strata,
            "cases": self.development_cases,
            "claim_boundary_status": ("development_cases_not_quality_or_holdout_evidence"),
            "classification": "development_not_holdout",
            "distinct_required_message_occurrence_count": 189,
            "distinct_required_observation_count": 200,
            "holdout_content_consumed": False,
            "mail_evidence_bundle_id": "synthetic-mail-evidence-bundle",
            "mail_import_session_id": "synthetic-mail-import-session",
            "oracle_content_consumed": False,
            "quality_evaluation_status": "not_run",
            "required_evidence_reference_count": 200,
            "schema_version": 1,
            "selection_policy": selection_policy,
            "selection_policy_fingerprint": _contract_fingerprint(selection_policy),
            "source_bindings": {
                "bundle_artifact_byte_hash": self.source_bundle_sha256,
                "bundle_artifact_fingerprint": self.source_bundle_artifact["artifact_fingerprint"],
                "index_fingerprint": self.source_snapshot["index_fingerprint"],
                "mail_evidence_bundle_fingerprint": self.source_bundle_artifact[
                    "bundle_fingerprint"
                ],
                "permission_fingerprint": self.source_snapshot["permission_fingerprint"],
                "retrieval_report_byte_hash": _fingerprint(
                    "independently-sealed-retrieval-ready-report-bytes"
                ),
                "retrieval_snapshot_byte_hash": self.source_snapshot_sha256,
                "retrieval_snapshot_fingerprint": self.source_snapshot["snapshot_fingerprint"],
                "source_inventory_fingerprint": self.source_snapshot[
                    "source_inventory_fingerprint"
                ],
                "source_provenance_fingerprint": self.source_snapshot[
                    "source_provenance_fingerprint"
                ],
                "source_snapshot_fingerprint": self.source_snapshot["source_snapshot_fingerprint"],
                "tokenizer_profile_fingerprint": self.source_snapshot[
                    "tokenizer_profile_fingerprint"
                ],
            },
        }
        manifest["manifest_fingerprint"] = _contract_payload_fingerprint(
            manifest,
            "manifest_fingerprint",
        )
        return manifest

    def _development_registry_fingerprint(self) -> str:
        case_fingerprints = sorted(
            str(case["private_fingerprint"]) for case in self.development_cases
        )
        observation_ids = sorted(
            _contract_fingerprint(observation_id)
            for case in self.development_cases
            for observation_id in case["required_source_observation_ids"]
        )
        return _contract_fingerprint(
            {
                "development_manifest_sha256": (self.development_manifest_sha256),
                "development_manifest_fingerprint": (
                    self.development_manifest["manifest_fingerprint"]
                ),
                "case_fingerprints": case_fingerprints,
                "observation_id_hashes": observation_ids,
            }
        )

    def _development_report(self) -> dict[str, object]:
        source_bindings = self.development_manifest["source_bindings"]
        report: dict[str, object] = {
            "artifact_id": author_inputs.DEVELOPMENT_SAFE_REPORT_ARTIFACT_ID,
            "blocker_ids": [],
            "claim_boundary_status": "development_manifest_only",
            "classification": "development_not_holdout",
            "counts": {
                "blocker_count": 0,
                "case_count": 100,
                "distinct_required_message_occurrence_count": 189,
                "distinct_required_observation_count": 200,
                "positive_graph_required_owner_case_count": 100,
                "required_evidence_reference_count": 200,
                "source_attachment_occurrence_count": 0,
                "source_body_segment_count": 200,
                "source_message_count": 189,
                "unexplained_evidence_binding_count": 0,
            },
            "fingerprints": {
                "bundle_artifact_fingerprint": source_bindings["bundle_artifact_fingerprint"],
                "candidate_admission_profile_fingerprint": source_bindings[
                    "tokenizer_profile_fingerprint"
                ],
                "index_fingerprint": source_bindings["index_fingerprint"],
                "mail_evidence_bundle_fingerprint": source_bindings[
                    "mail_evidence_bundle_fingerprint"
                ],
                "manifest_fingerprint": self.development_manifest["manifest_fingerprint"],
                "manifest_sha256": self.development_manifest_sha256,
                "permission_fingerprint": source_bindings["permission_fingerprint"],
                "retrieval_snapshot_fingerprint": source_bindings["retrieval_snapshot_fingerprint"],
                "selection_policy_fingerprint": self.development_manifest[
                    "selection_policy_fingerprint"
                ],
                "source_snapshot_fingerprint": source_bindings["source_snapshot_fingerprint"],
            },
            "holdout_content_status": "not_read",
            "immutable_write_status": "passed",
            "lineage_validation_status": "passed",
            "manifest_intake_status": "passed",
            "quality_evaluation_status": "not_run",
            "schema_version": 1,
            "status": "passed",
            "strata": self.development_manifest["case_strata_counts"],
        }
        report["report_fingerprint"] = _contract_payload_fingerprint(
            report,
            "report_fingerprint",
        )
        return report

    def _development_exclusion_binding(self) -> dict[str, object]:
        return {
            "development_case_count": 100,
            "development_manifest_fingerprint": self.development_manifest["manifest_fingerprint"],
            "development_manifest_sha256": self.development_manifest_sha256,
            "development_registry_fingerprint": (self.development_registry_fingerprint),
            "development_safe_report_sha256": (self.development_report_sha256),
        }

    def _disjointness(self) -> dict[str, object]:
        holdout_observation_ids = {
            observation_id
            for case in self.holdout_cases
            for observation_id in case.get(
                "authoring_source_observation_ids",
                case["required_source_observation_ids"] or case["forbidden_source_observation_ids"],
            )
        }
        self.assert_equal_for_fixture(
            len(holdout_observation_ids),
            78,
        )
        holdout_message_ids = {
            self.holdout_occurrence_to_email_message[
                self.holdout_observation_to_occurrence[observation_id]
            ]
            for observation_id in holdout_observation_ids
        }
        holdout_thread_ids = {
            self.holdout_occurrence_to_thread[
                self.holdout_observation_to_occurrence[observation_id]
            ]
            for observation_id in holdout_observation_ids
        }
        self.assert_equal_for_fixture(len(holdout_message_ids), 77)
        self.assert_equal_for_fixture(len(holdout_thread_ids), 75)
        return {
            "status": "passed",
            "development_holdout_observation_overlap_count": 0,
            "development_holdout_message_overlap_count": 0,
            "development_holdout_thread_overlap_count": 0,
            "holdout_authoring_observation_count": len(holdout_observation_ids),
            "holdout_authoring_message_count": len(holdout_message_ids),
            "holdout_authoring_thread_count": len(holdout_thread_ids),
            "holdout_observation_set_fingerprint": _fingerprint(
                sorted(_fingerprint(value) for value in holdout_observation_ids)
            ),
            "holdout_message_set_fingerprint": _fingerprint(
                sorted(_fingerprint(value) for value in holdout_message_ids)
            ),
            "holdout_thread_set_fingerprint": _fingerprint(
                sorted(_fingerprint(value) for value in holdout_thread_ids)
            ),
        }

    @staticmethod
    def assert_equal_for_fixture(actual: object, expected: object) -> None:
        if actual != expected:
            raise AssertionError(f"invalid fixture count: {actual!r} != {expected!r}")

    def _holdout_manifest(self) -> dict[str, object]:
        manifest: dict[str, object] = {
            "artifact_id": projection_builder.HOLDOUT_MANIFEST_ARTIFACT_ID,
            "schema_version": 2,
            "classification": "independent_mail_holdout",
            "claim_boundary_status": ("sealed_independent_holdout_manifest_not_executed"),
            "execution_status": "not_run",
            "quality_result_status": "not_read",
            "seal_required_before_execution": True,
            "author_evaluator_boundary": {
                "author_role_fingerprint": _fingerprint("source-author-role"),
                "evaluator_role_fingerprint": _fingerprint("independent-evaluator-role"),
                "roles_are_distinct": True,
                "evaluator_invoked": False,
                "development_quality_output_read": False,
            },
            "source_oracle_bindings": self.source_oracle_bindings,
            "development_exclusion_binding": (self.development_exclusion_binding),
            "sealed_graph_positive_v1_binding": {
                "v1_manifest_sha256": _fingerprint("sealed-v1-manifest"),
                "v1_safe_report_sha256": _fingerprint("sealed-v1-safe-report"),
                "v1_manifest_fingerprint": _fingerprint("sealed-v1-manifest-fingerprint"),
                "v1_case_count": 30,
                "v1_case_payloads_reused_without_modification": True,
            },
            "selection_policy": {
                "policy_id": "synthetic-independent-holdout-v2-selection",
                "quality_output_read": False,
            },
            "selection_policy_fingerprint": _fingerprint(
                {
                    "policy_id": "synthetic-independent-holdout-v2-selection",
                    "quality_output_read": False,
                }
            ),
            "partition_policy": {
                "partition_side": "latest",
                "thread_pure": True,
            },
            "partition_policy_fingerprint": _fingerprint(
                {
                    "partition_side": "latest",
                    "thread_pure": True,
                }
            ),
            "time_boundary_fingerprint": _fingerprint("synthetic-time-boundary"),
            "partition_fingerprint": _fingerprint("holdout-partition"),
            "disjointness": self.disjointness,
            "source_time_split": {
                "partition_side": "latest",
                "partition_fraction_numerator": 1,
                "partition_fraction_denominator": 4,
                "thread_pure": True,
                "latest_partition_message_count": 77,
                "eligible_message_count": 77,
                "eligible_thread_count": 75,
                "eligible_body_observation_count": 61,
            },
            "case_count": projection_builder.EXPECTED_CASE_COUNT,
            "case_strata_counts": dict(projection_builder.EXPECTED_STRATA_COUNTS),
            "stratum_case_fingerprints": {
                stratum: [
                    case["private_fingerprint"]
                    for case in self.holdout_cases
                    if str(case.get("stratum_id", "graph_required")) == stratum
                ]
                for stratum in projection_builder.EXPECTED_STRATA_COUNTS
            },
            "cases": self.holdout_cases,
        }
        manifest["manifest_fingerprint"] = _fingerprint(
            {
                "scope": "externally-sealed-real-v2-manifest-fingerprint",
                "partition_fingerprint": manifest["partition_fingerprint"],
                "case_count": manifest["case_count"],
            }
        )
        if manifest["manifest_fingerprint"] == _payload_fingerprint(
            manifest,
            "manifest_fingerprint",
        ):
            raise AssertionError("fixture must exercise non-recomputed v2 fingerprint")
        return manifest

    def _holdout_preflight(self) -> dict[str, object]:
        report: dict[str, object] = {
            "artifact_id": projection_builder.HOLDOUT_PREFLIGHT_ARTIFACT_ID,
            "schema_version": 2,
            "status": "passed",
            "classification": "independent_mail_holdout",
            "claim_boundary_status": "holdout_manifest_only",
            "execution_status": "not_run",
            "quality_result_status": "not_read",
            "development_quality_output_status": "not_read",
            "source_lineage_status": "passed",
            "source_oracle_status": "passed",
            "source_time_split_status": "passed",
            "thread_pure_status": "passed",
            "disjointness_status": "passed",
            "strata_coverage_status": "passed",
            "seal_before_execution_status": "passed",
            "counts": {
                "case_count": projection_builder.EXPECTED_CASE_COUNT,
                "holdout_authoring_observation_count": self.disjointness[
                    "holdout_authoring_observation_count"
                ],
                "holdout_authoring_message_count": self.disjointness[
                    "holdout_authoring_message_count"
                ],
                "holdout_authoring_thread_count": self.disjointness[
                    "holdout_authoring_thread_count"
                ],
                "development_holdout_observation_overlap_count": 0,
                "development_holdout_message_overlap_count": 0,
                "development_holdout_thread_overlap_count": 0,
                "source_unexplained_loss_count": 0,
                "blocker_count": 0,
                "source_message_count": self.source_message_occurrence_count,
                "source_body_segment_count": len(
                    [
                        row
                        for row in self.development_observation_rows + self.holdout_observation_rows
                        if row["observation_type"] == "email_body_segment"
                    ]
                ),
                "source_attachment_occurrence_count": 0,
                "latest_time_partition_message_count": 77,
                "eligible_message_count": 77,
                "eligible_thread_count": 75,
                "eligible_body_observation_count": 61,
                "base_graph_required_case_count": 30,
                "additional_case_count": 11,
                "time_partition_fraction_numerator": 1,
                "time_partition_fraction_denominator": 4,
            },
            "strata_counts": dict(projection_builder.EXPECTED_STRATA_COUNTS),
            "hashes": {
                "manifest_sha256": self.holdout_manifest_sha256,
                "manifest_fingerprint": self.holdout_manifest["manifest_fingerprint"],
                "partition_fingerprint": self.holdout_manifest["partition_fingerprint"],
                "development_manifest_sha256": (self.development_manifest_sha256),
                "development_registry_fingerprint": (self.development_registry_fingerprint),
                "source_snapshot_fingerprint": self.source_oracle_bindings[
                    "source_snapshot_fingerprint"
                ],
                "source_inventory_fingerprint": self.source_oracle_bindings[
                    "source_inventory_fingerprint"
                ],
                "source_provenance_fingerprint": self.source_oracle_bindings[
                    "source_provenance_fingerprint"
                ],
                "index_fingerprint": self.source_oracle_bindings["index_fingerprint"],
                "segmentation_profile_fingerprint": (
                    self.source_oracle_bindings["tokenizer_profile_fingerprint"]
                ),
                "holdout_observation_set_fingerprint": self.disjointness[
                    "holdout_observation_set_fingerprint"
                ],
                "holdout_message_set_fingerprint": self.disjointness[
                    "holdout_message_set_fingerprint"
                ],
                "holdout_thread_set_fingerprint": self.disjointness[
                    "holdout_thread_set_fingerprint"
                ],
                "safe_selection_policy_fingerprint": self.holdout_manifest[
                    "selection_policy_fingerprint"
                ],
                "source_oracle_manifest_fingerprint": (self.native_manifest_fingerprint),
                "permission_fingerprint": self.permission_fingerprint,
                "sealed_graph_positive_v1_manifest_sha256": (
                    self.holdout_manifest["sealed_graph_positive_v1_binding"]["v1_manifest_sha256"]
                ),
                "partition_policy_fingerprint": self.holdout_manifest[
                    "partition_policy_fingerprint"
                ],
                "time_boundary_fingerprint": self.holdout_manifest["time_boundary_fingerprint"],
            },
            "blocker_ids": [],
        }
        report["report_fingerprint"] = _payload_fingerprint(
            report,
            "report_fingerprint",
        )
        return report

    def rewrite_holdout_and_preflight(
        self,
        holdout_manifest: dict[str, object],
    ) -> None:
        self.holdout_manifest = holdout_manifest
        self.holdout_manifest_sha256 = _write_json(
            self.holdout_manifest_path,
            holdout_manifest,
        )
        self.holdout_preflight = self._holdout_preflight()
        self.holdout_preflight_sha256 = _write_json(
            self.holdout_preflight_path,
            self.holdout_preflight,
        )

    def rewrite_source_report(
        self,
        source_report: dict[str, object],
        *,
        rebind_holdout: bool,
    ) -> None:
        self.source_report = source_report
        self.source_report_sha256 = _write_json(
            self.source_report_path,
            self.source_report,
        )
        if rebind_holdout:
            holdout_manifest = copy.deepcopy(self.holdout_manifest)
            holdout_manifest["source_oracle_bindings"]["source_report_sha256"] = (
                self.source_report_sha256
            )
            self.rewrite_holdout_and_preflight(holdout_manifest)

    def rewrite_development(
        self,
        development_manifest: dict[str, object],
        *,
        rebuild_report: bool,
        rebind_holdout: bool,
    ) -> None:
        self.development_manifest = development_manifest
        self.development_manifest_sha256 = _write_json(
            self.development_manifest_path,
            self.development_manifest,
        )
        if rebuild_report:
            self.development_report = self._development_report()
            self.development_report_sha256 = _write_json(
                self.development_report_path,
                self.development_report,
            )
        if rebind_holdout:
            self.development_registry_fingerprint = self._development_registry_fingerprint()
            holdout_manifest = copy.deepcopy(self.holdout_manifest)
            holdout_manifest["development_exclusion_binding"] = (
                self._development_exclusion_binding()
            )
            self.rewrite_holdout_and_preflight(holdout_manifest)

    def rewrite_development_report(
        self,
        development_report: dict[str, object],
        *,
        rebind_holdout: bool,
    ) -> None:
        self.development_report = development_report
        self.development_report_sha256 = _write_json(
            self.development_report_path,
            self.development_report,
        )
        if rebind_holdout:
            holdout_manifest = copy.deepcopy(self.holdout_manifest)
            holdout_manifest["development_exclusion_binding"] = (
                self._development_exclusion_binding()
            )
            self.rewrite_holdout_and_preflight(holdout_manifest)

    def build(
        self,
        output_root: Path,
        *,
        expected_holdout_manifest_sha256: str | None = None,
        expected_development_manifest_sha256: str | None = None,
        expected_development_safe_report_sha256: str | None = None,
        write_staged_file: object | None = None,
    ) -> author_inputs.HoldoutSourceAuthorProjectionInputArtifacts:
        kwargs: dict[str, object] = {}
        if write_staged_file is not None:
            kwargs["_write_staged_file"] = write_staged_file
        return author_inputs.build_holdout_source_author_projection_inputs(
            holdout_manifest_path=self.holdout_manifest_path,
            expected_holdout_manifest_sha256=(
                expected_holdout_manifest_sha256 or self.holdout_manifest_sha256
            ),
            holdout_preflight_safe_path=self.holdout_preflight_path,
            expected_holdout_preflight_safe_sha256=(self.holdout_preflight_sha256),
            development_manifest_path=self.development_manifest_path,
            expected_development_manifest_sha256=(
                expected_development_manifest_sha256 or self.development_manifest_sha256
            ),
            development_safe_report_path=self.development_report_path,
            expected_development_safe_report_sha256=(
                expected_development_safe_report_sha256 or self.development_report_sha256
            ),
            source_bundle_artifact_path=self.source_bundle_path,
            expected_source_bundle_artifact_sha256=(self.source_bundle_sha256),
            source_retrieval_snapshot_path=self.source_snapshot_path,
            expected_source_retrieval_snapshot_sha256=(self.source_snapshot_sha256),
            source_report_path=self.source_report_path,
            expected_source_report_sha256=self.source_report_sha256,
            output_root=output_root,
            **kwargs,
        )

    def cli_args(self, output_root: Path) -> list[str]:
        return [
            "--holdout-manifest",
            str(self.holdout_manifest_path),
            "--expected-holdout-manifest-sha256",
            self.holdout_manifest_sha256,
            "--holdout-preflight-safe",
            str(self.holdout_preflight_path),
            "--expected-holdout-preflight-safe-sha256",
            self.holdout_preflight_sha256,
            "--development-manifest",
            str(self.development_manifest_path),
            "--expected-development-manifest-sha256",
            self.development_manifest_sha256,
            "--development-safe-report",
            str(self.development_report_path),
            "--expected-development-safe-report-sha256",
            self.development_report_sha256,
            "--source-bundle-artifact",
            str(self.source_bundle_path),
            "--expected-source-bundle-artifact-sha256",
            self.source_bundle_sha256,
            "--source-retrieval-snapshot",
            str(self.source_snapshot_path),
            "--expected-source-retrieval-snapshot-sha256",
            self.source_snapshot_sha256,
            "--source-report",
            str(self.source_report_path),
            "--expected-source-report-sha256",
            self.source_report_sha256,
            "--output-root",
            str(output_root),
        ]


class HoldoutSourceAuthorProjectionInputsE2ETest(unittest.TestCase):
    def test_exact_source_completeness_authorized_report_contract_is_accepted(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)

            self.assertEqual(
                set(fixture.source_report),
                author_inputs._SOURCE_COMPLETENESS_REPORT_FIELDS,
            )
            self.assertEqual(
                fixture.source_report["artifact_id"],
                author_inputs.SOURCE_REPORT_ARTIFACT_ID,
            )
            self.assertEqual(
                fixture.source_report["report_fingerprint"],
                _contract_payload_fingerprint(
                    fixture.source_report,
                    "report_fingerprint",
                ),
            )
            self.assertEqual(
                set(fixture.source_report["counts"]),
                author_inputs._SOURCE_COMPLETENESS_REQUIRED_COUNT_FIELDS,
            )
            self.assertTrue(
                author_inputs._SOURCE_COMPLETENESS_OPTIONAL_COUNT_FIELDS.isdisjoint(
                    fixture.source_report["counts"]
                )
            )
            self.assertNotEqual(
                fixture.development_manifest["source_bindings"]["retrieval_report_byte_hash"],
                fixture.source_report_sha256,
            )

            artifacts = fixture.build(root / "authorized-source-report")
            self.assertEqual(artifacts.result["status"], "passed")
            self.assertEqual(
                artifacts.result["hashes"]["source_report_sha256"],
                fixture.source_report_sha256,
            )

            real_schema_report = copy.deepcopy(fixture.source_report)
            real_schema_report["counts"] = dict(_REAL_SOURCE_COMPLETENESS_COUNTS)
            real_schema_report["report_fingerprint"] = _contract_payload_fingerprint(
                real_schema_report,
                "report_fingerprint",
            )
            author_inputs._validate_source_completeness_report(
                real_schema_report,
                source_artifact_bindings={
                    "source_asset_sha256": fixture.source_asset_sha256,
                    "native_manifest_fingerprint": fixture.native_manifest_fingerprint,
                    "permission_fingerprint": fixture.permission_fingerprint,
                    "parser_fingerprint": fixture.parser_fingerprint,
                    "source_inventory_fingerprint": fixture.source_snapshot[
                        "source_inventory_fingerprint"
                    ],
                    "source_snapshot_fingerprint": fixture.source_snapshot[
                        "source_snapshot_fingerprint"
                    ],
                    "source_provenance_fingerprint": (fixture.source_provenance_fingerprint),
                    "source_count_crosswalk": {
                        "bundle_folder_occurrence_count": 3,
                        "bundle_message_occurrence_count": 2793,
                        "bundle_attachment_occurrence_count": 5645,
                        "retrieval_source_inventory_item_count": 8443,
                        "retrieval_source_occurrence_observation_count": 8443,
                        "folder_occurrence_count": 3,
                        "message_occurrence_count": 2793,
                        "attachment_export_occurrence_count": 5645,
                        "unsupported_preserved_occurrence_count": 2,
                    },
                },
            )

    def test_source_completeness_report_gap_and_binding_tamper_fail_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            gap_report = copy.deepcopy(fixture.source_report)
            gap_report["counts"]["unexplained_loss_count"] = 1
            gap_report["report_fingerprint"] = _contract_payload_fingerprint(
                gap_report,
                "report_fingerprint",
            )
            fixture.rewrite_source_report(
                gap_report,
                rebind_holdout=True,
            )
            with self.assertRaisesRegex(
                author_inputs.HoldoutSourceAuthorProjectionInputsError,
                "^source_report_unexplained_loss$",
            ):
                fixture.build(root / "unexplained-loss")
            self.assertFalse((root / "unexplained-loss").exists())

        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            cross_run_report = copy.deepcopy(fixture.source_report)
            cross_run_report["source_inventory_fingerprint"] = _fingerprint(
                "different-source-inventory"
            )
            cross_run_report["report_fingerprint"] = _contract_payload_fingerprint(
                cross_run_report,
                "report_fingerprint",
            )
            fixture.rewrite_source_report(
                cross_run_report,
                rebind_holdout=True,
            )
            with self.assertRaisesRegex(
                author_inputs.HoldoutSourceAuthorProjectionInputsError,
                "^source_report_binding_mismatch$",
            ):
                fixture.build(root / "source-report-cross-binding")
            self.assertFalse((root / "source-report-cross-binding").exists())

        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            parity_report = copy.deepcopy(fixture.source_report)
            parity_report["counts"]["attachment_synthetic_representation_count"] = 1
            parity_report["report_fingerprint"] = _contract_payload_fingerprint(
                parity_report,
                "report_fingerprint",
            )
            fixture.rewrite_source_report(
                parity_report,
                rebind_holdout=True,
            )
            with self.assertRaisesRegex(
                author_inputs.HoldoutSourceAuthorProjectionInputsError,
                "^source_report_count_parity_invalid$",
            ):
                fixture.build(root / "source-report-count-parity")
            self.assertFalse((root / "source-report-count-parity").exists())

        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            crosswalk_report = copy.deepcopy(fixture.source_report)
            crosswalk_report["counts"].update(
                {
                    "message_occurrence_count": 188,
                    "message_source_inventory_binding_count": 188,
                    "message_parent_lineage_count": 188,
                    "source_inventory_item_count": 189,
                    "observation_count": 189,
                }
            )
            crosswalk_report["report_fingerprint"] = _contract_payload_fingerprint(
                crosswalk_report,
                "report_fingerprint",
            )
            fixture.rewrite_source_report(
                crosswalk_report,
                rebind_holdout=True,
            )
            with self.assertRaisesRegex(
                author_inputs.HoldoutSourceAuthorProjectionInputsError,
                "^source_report_count_binding_mismatch$",
            ):
                fixture.build(root / "source-report-count-cross-binding")
            self.assertFalse((root / "source-report-count-cross-binding").exists())

    def test_source_completeness_count_required_optional_and_extra_contract(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            compatible_report = copy.deepcopy(fixture.source_report)
            compatible_report["counts"]["attachment_occurrence_count"] = 0
            compatible_report["counts"]["future_safe_count"] = 7
            compatible_report["report_fingerprint"] = _contract_payload_fingerprint(
                compatible_report,
                "report_fingerprint",
            )
            fixture.rewrite_source_report(
                compatible_report,
                rebind_holdout=True,
            )
            artifacts = fixture.build(root / "compatible-count-extension")
            self.assertEqual(artifacts.result["status"], "passed")

        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            missing_required_report = copy.deepcopy(fixture.source_report)
            del missing_required_report["counts"]["attachment_content_hash_count"]
            missing_required_report["report_fingerprint"] = _contract_payload_fingerprint(
                missing_required_report,
                "report_fingerprint",
            )
            fixture.rewrite_source_report(
                missing_required_report,
                rebind_holdout=True,
            )
            with self.assertRaisesRegex(
                author_inputs.HoldoutSourceAuthorProjectionInputsError,
                "^source_report_counts_invalid$",
            ):
                fixture.build(root / "missing-required-count")
            self.assertFalse((root / "missing-required-count").exists())

        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            alias_mismatch_report = copy.deepcopy(fixture.source_report)
            alias_mismatch_report["counts"]["attachment_occurrence_count"] = 1
            alias_mismatch_report["report_fingerprint"] = _contract_payload_fingerprint(
                alias_mismatch_report,
                "report_fingerprint",
            )
            fixture.rewrite_source_report(
                alias_mismatch_report,
                rebind_holdout=True,
            )
            with self.assertRaisesRegex(
                author_inputs.HoldoutSourceAuthorProjectionInputsError,
                "^source_report_counts_invalid$",
            ):
                fixture.build(root / "attachment-alias-mismatch")
            self.assertFalse((root / "attachment-alias-mismatch").exists())

    def test_bundle_and_retrieval_snapshot_count_crosswalk_fail_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            fixture = _Fixture(Path(raw_root))
            preflight_summary = author_inputs._validate_preflight(
                fixture.holdout_preflight,
                private_manifest_sha256=fixture.holdout_manifest_sha256,
            )
            tampered_snapshot = copy.deepcopy(fixture.source_snapshot)
            tampered_snapshot["counts"]["mail_bundle_message_occurrence_count"] -= 1
            tampered_snapshot["snapshot_fingerprint"] = _contract_payload_fingerprint(
                tampered_snapshot,
                "snapshot_fingerprint",
            )
            with self.assertRaisesRegex(
                author_inputs.HoldoutSourceAuthorProjectionInputsError,
                "^source_bundle_snapshot_count_mismatch$",
            ):
                author_inputs._validated_source_artifact_bindings(
                    source_bundle_bytes=fixture.source_bundle_path.read_bytes(),
                    source_snapshot_bytes=_canonical_bytes(tampered_snapshot),
                    preflight_summary=preflight_summary,
                )

        with tempfile.TemporaryDirectory() as raw_root:
            fixture = _Fixture(Path(raw_root))
            preflight_summary = author_inputs._validate_preflight(
                fixture.holdout_preflight,
                private_manifest_sha256=fixture.holdout_manifest_sha256,
            )
            tampered_bundle = copy.deepcopy(fixture.source_bundle_artifact)
            tampered_bundle["bundle"]["attachment_occurrences"].append(
                {"attachment_occurrence_id": "synthetic-extra-occurrence"}
            )
            tampered_bundle["bundle_fingerprint"] = _contract_fingerprint(tampered_bundle["bundle"])
            tampered_bundle["artifact_fingerprint"] = _contract_payload_fingerprint(
                tampered_bundle,
                "artifact_fingerprint",
            )
            with self.assertRaisesRegex(
                author_inputs.HoldoutSourceAuthorProjectionInputsError,
                "^source_bundle_snapshot_count_mismatch$",
            ):
                author_inputs._validated_source_artifact_bindings(
                    source_bundle_bytes=_canonical_bytes(tampered_bundle),
                    source_snapshot_bytes=fixture.source_snapshot_path.read_bytes(),
                    preflight_summary=preflight_summary,
                )

    def test_retrieval_profile_crosswalk_comes_from_snapshot_and_safe_preflight(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            mismatched_preflight = copy.deepcopy(fixture.holdout_preflight)
            mismatched_preflight["hashes"]["segmentation_profile_fingerprint"] = _fingerprint(
                "different-preflight-profile"
            )
            mismatched_preflight["report_fingerprint"] = _payload_fingerprint(
                mismatched_preflight,
                "report_fingerprint",
            )
            fixture.holdout_preflight = mismatched_preflight
            fixture.holdout_preflight_sha256 = _write_json(
                fixture.holdout_preflight_path,
                mismatched_preflight,
            )
            with self.assertRaisesRegex(
                author_inputs.HoldoutSourceAuthorProjectionInputsError,
                "^source_retrieval_preflight_binding_mismatch$",
            ):
                fixture.build(root / "profile-cross-binding")
            self.assertFalse((root / "profile-cross-binding").exists())

    def test_exact_development_v1_unicode_contract_and_lineage_are_accepted(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)

            self.assertEqual(
                set(fixture.development_manifest),
                author_inputs._DEVELOPMENT_MANIFEST_FIELDS,
            )
            self.assertEqual(
                fixture.development_manifest["manifest_fingerprint"],
                _contract_payload_fingerprint(
                    fixture.development_manifest,
                    "manifest_fingerprint",
                ),
            )
            self.assertNotEqual(
                fixture.development_manifest["manifest_fingerprint"],
                _payload_fingerprint(
                    fixture.development_manifest,
                    "manifest_fingerprint",
                ),
            )
            first_case = fixture.development_cases[0]
            self.assertEqual(
                set(first_case),
                author_inputs._DEVELOPMENT_CASE_FIELDS,
            )
            self.assertEqual(
                first_case["private_fingerprint"],
                _contract_payload_fingerprint(
                    first_case,
                    "private_fingerprint",
                ),
            )
            self.assertNotEqual(
                first_case["private_fingerprint"],
                _payload_fingerprint(
                    first_case,
                    "private_fingerprint",
                ),
            )

            artifacts = fixture.build(root / "accepted-development-v1")
            self.assertEqual(artifacts.result["status"], "passed")
            self.assertEqual(
                artifacts.result["counts"]["development_case_count"],
                100,
            )
            self.assertEqual(
                artifacts.development_disjointness["disjointness"][
                    "development_holdout_observation_overlap_count"
                ],
                0,
            )

    def test_sanitized_actual_v2_shape_and_source_authoritative_cardinality(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            self.assertEqual(
                set(fixture.holdout_manifest),
                {
                    "artifact_id",
                    "author_evaluator_boundary",
                    "case_count",
                    "case_strata_counts",
                    "cases",
                    "claim_boundary_status",
                    "classification",
                    "development_exclusion_binding",
                    "disjointness",
                    "execution_status",
                    "manifest_fingerprint",
                    "partition_fingerprint",
                    "partition_policy",
                    "partition_policy_fingerprint",
                    "quality_result_status",
                    "schema_version",
                    "seal_required_before_execution",
                    "sealed_graph_positive_v1_binding",
                    "selection_policy",
                    "selection_policy_fingerprint",
                    "source_oracle_bindings",
                    "source_time_split",
                    "stratum_case_fingerprints",
                    "time_boundary_fingerprint",
                },
            )
            self.assertEqual(
                set(fixture.holdout_preflight),
                {
                    "artifact_id",
                    "blocker_ids",
                    "claim_boundary_status",
                    "classification",
                    "counts",
                    "development_quality_output_status",
                    "disjointness_status",
                    "execution_status",
                    "hashes",
                    "quality_result_status",
                    "report_fingerprint",
                    "schema_version",
                    "seal_before_execution_status",
                    "source_lineage_status",
                    "source_oracle_status",
                    "source_time_split_status",
                    "status",
                    "strata_counts",
                    "strata_coverage_status",
                    "thread_pure_status",
                },
            )
            case_field_presence = Counter(
                field_name for case in fixture.holdout_cases for field_name in case
            )
            self.assertEqual(
                case_field_presence,
                Counter(
                    {
                        "answer_oracle": 11,
                        "authoring_source_observation_ids": 11,
                        "case_id": 41,
                        "domain": 41,
                        "forbidden_source_observation_ids": 41,
                        "intent_kind": 41,
                        "limit": 41,
                        "pattern": 41,
                        "private_fingerprint": 41,
                        "query_text": 41,
                        "requester_user_id": 41,
                        "required_match_count": 41,
                        "required_source_observation_ids": 41,
                        "result_kind": 41,
                        "source_evidence_binding": 41,
                        "stratum_id": 11,
                    }
                ),
            )
            binding_field_presence = Counter(
                field_name
                for case in fixture.holdout_cases
                for field_name in case["source_evidence_binding"]
            )
            self.assertEqual(
                binding_field_presence,
                Counter(
                    {
                        "candidate_fingerprint": 39,
                        "complete_source_identifier_occurrence_count": 3,
                        "denied_message_hashes": 2,
                        "denied_message_occurrence_hashes": 2,
                        "denied_observation_hashes": 2,
                        "denied_thread_hashes": 2,
                        "full_source_absence_proof_fingerprint": 2,
                        "near_miss_mutation_fingerprint": 2,
                        "near_miss_source_candidate_fingerprint": 2,
                        "near_miss_source_observation_hash": 2,
                        "partition_fingerprint": 41,
                        "permission_fingerprint": 2,
                        "required_message_hashes": 37,
                        "required_message_occurrence_hashes": 37,
                        "required_observation_hashes": 37,
                        "required_thread_hashes": 37,
                    }
                ),
            )
            duplicate_occurrence_case_count = sum(
                len(values) != len(set(values))
                for case in fixture.holdout_cases
                if isinstance(
                    (
                        values := case["source_evidence_binding"].get(
                            "required_message_occurrence_hashes"
                        )
                    ),
                    list,
                )
            )
            duplicate_thread_case_count = sum(
                len(values) != len(set(values))
                for case in fixture.holdout_cases
                if isinstance(
                    (values := case["source_evidence_binding"].get("required_thread_hashes")),
                    list,
                )
            )
            self.assertEqual(duplicate_occurrence_case_count, 1)
            self.assertEqual(duplicate_thread_case_count, 2)
            self.assertEqual(
                Counter(str(row["observation_type"]) for row in fixture.holdout_observation_rows),
                Counter(
                    {
                        "email_body_segment": 61,
                        "email_header": 17,
                    }
                ),
            )
            bundle = fixture.source_bundle_artifact["bundle"]
            occurrence_by_id = {
                row["message_occurrence_id"]: row for row in bundle["message_occurrences"]
            }
            message_by_email_id = {row["email_message_id"]: row for row in bundle["messages"]}
            source_native_match_count = 0
            distinct_mail_record_identity_count = 0
            for row in fixture.holdout_observation_rows:
                location = row["location"]
                occurrence = occurrence_by_id[location["message_occurrence_id"]]
                message = message_by_email_id[occurrence["email_message_id"]]
                source_native_match_count += (
                    occurrence["message_id"] == location["message_id"]
                    and occurrence["thread_id"] == location["thread_id"]
                    and message["thread_id"] == location["thread_id"]
                )
                distinct_mail_record_identity_count += (
                    occurrence["email_message_id"] != location["message_id"]
                    and message["email_message_id"] == occurrence["email_message_id"]
                )
            self.assertEqual(source_native_match_count, 78)
            self.assertEqual(distinct_mail_record_identity_count, 78)
            holdout_occurrence_ids = {
                fixture.holdout_observation_to_occurrence[observation_id]
                for observation_id in {
                    observation_id
                    for case in fixture.holdout_cases
                    for observation_id in case.get(
                        "authoring_source_observation_ids",
                        case["required_source_observation_ids"]
                        or case["forbidden_source_observation_ids"],
                    )
                }
            }
            self.assertEqual(len(holdout_occurrence_ids), 77)
            self.assertEqual(
                len(
                    {
                        fixture.holdout_occurrence_to_email_message[occurrence_id]
                        for occurrence_id in holdout_occurrence_ids
                    }
                ),
                77,
            )
            self.assertEqual(
                len(
                    {
                        fixture.holdout_occurrence_to_message[occurrence_id]
                        for occurrence_id in holdout_occurrence_ids
                    }
                ),
                76,
            )
            self.assertEqual(
                len(
                    {
                        fixture.holdout_occurrence_to_thread[occurrence_id]
                        for occurrence_id in holdout_occurrence_ids
                    }
                ),
                75,
            )

            artifacts = fixture.build(root / "actual-v2-sanitized")
            self.assertEqual(artifacts.result["status"], "passed")
            self.assertEqual(
                artifacts.development_disjointness["disjointness"][
                    "holdout_authoring_message_count"
                ],
                77,
            )
            self.assertEqual(
                artifacts.development_disjointness["disjointness"][
                    "holdout_authoring_thread_count"
                ],
                75,
            )

    def test_source_native_message_hash_is_not_case_message_hash(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            malformed = copy.deepcopy(fixture.holdout_manifest)
            first_case = malformed["cases"][0]
            authoring_ids = first_case["required_source_observation_ids"]
            occurrence_ids = [
                fixture.holdout_observation_to_occurrence[observation_id]
                for observation_id in authoring_ids
            ]
            source_native_hashes = sorted(
                {
                    _contract_fingerprint(fixture.holdout_occurrence_to_message[occurrence_id])
                    for occurrence_id in occurrence_ids
                }
            )
            email_record_hashes = first_case["source_evidence_binding"]["required_message_hashes"]
            self.assertNotEqual(source_native_hashes, email_record_hashes)
            first_case["source_evidence_binding"]["required_message_hashes"] = source_native_hashes
            fixture.rewrite_holdout_and_preflight(malformed)

            with self.assertRaisesRegex(
                author_inputs.HoldoutSourceAuthorProjectionInputsError,
                "^holdout_case_message_hashes_binding_mismatch$",
            ):
                fixture.build(root / "source-native-message-hash")
            self.assertFalse((root / "source-native-message-hash").exists())

    def test_actual_scale_source_native_message_identity_is_not_mail_record_identity(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            message_occurrence_count = 2_793
            body_observation_count = 5_098
            header_observation_count = 18_586
            supported_observation_count = body_observation_count + header_observation_count
            source_native_message_ids = [
                f"actual-source-message-{index:04d}" for index in range(message_occurrence_count)
            ]
            source_native_message_ids[-1] = source_native_message_ids[-2]
            email_message_ids = [
                f"actual-email-record-{index:04d}" for index in range(message_occurrence_count)
            ]
            occurrence_ids = [
                f"actual-message-occurrence-{index:04d}"
                for index in range(message_occurrence_count)
            ]
            thread_ids = [
                f"actual-source-thread-{index:04d}" for index in range(message_occurrence_count)
            ]
            thread_ids[-1] = thread_ids[-2]
            self.assertEqual(len(set(source_native_message_ids)), 2_792)
            self.assertEqual(len(set(email_message_ids)), 2_793)
            self.assertEqual(
                len(
                    {
                        (message_id, thread_id)
                        for message_id, thread_id in zip(
                            source_native_message_ids,
                            thread_ids,
                            strict=True,
                        )
                    }
                ),
                2_792,
            )
            occurrence_rows = [
                {
                    "message_occurrence_id": occurrence_id,
                    "message_id": message_id,
                    "email_message_id": email_message_id,
                    "thread_id": thread_id,
                }
                for occurrence_id, message_id, email_message_id, thread_id in zip(
                    occurrence_ids,
                    source_native_message_ids,
                    email_message_ids,
                    thread_ids,
                    strict=True,
                )
            ]
            message_rows = [
                {
                    "message_id": message_id,
                    "email_message_id": email_message_id,
                    "thread_id": thread_id,
                }
                for message_id, email_message_id, thread_id in zip(
                    source_native_message_ids,
                    email_message_ids,
                    thread_ids,
                    strict=True,
                )
            ]
            parsed_rows: list[dict[str, object]] = []
            body_segment_rows: list[dict[str, object]] = []
            source_native_match_count = 0
            mail_record_identity_mismatch_count = 0
            for index in range(supported_observation_count):
                occurrence_index = index % message_occurrence_count
                observation_type = (
                    "email_body_segment" if index < body_observation_count else "email_header"
                )
                observation_id = f"actual-observation-{index:05d}"
                row = fixture._parsed_observation_row(
                    observation_id=observation_id,
                    observation_type=observation_type,
                    occurrence_id=occurrence_ids[occurrence_index],
                    message_id=source_native_message_ids[occurrence_index],
                    thread_id=thread_ids[occurrence_index],
                    index=index,
                )
                parsed_rows.append(row)
                source_native_match_count += (
                    row["location"]["message_id"] == occurrence_rows[occurrence_index]["message_id"]
                )
                mail_record_identity_mismatch_count += (
                    row["location"]["message_id"]
                    != occurrence_rows[occurrence_index]["email_message_id"]
                )
                if observation_type == "email_body_segment":
                    body_segment_rows.append(
                        {
                            "source_observation_id": observation_id,
                            "message_occurrence_id": occurrence_ids[occurrence_index],
                            "email_message_id": email_message_ids[occurrence_index],
                        }
                    )
            self.assertEqual(source_native_match_count, supported_observation_count)
            self.assertEqual(
                mail_record_identity_mismatch_count,
                supported_observation_count,
            )

            bundle_artifact = copy.deepcopy(fixture.source_bundle_artifact)
            bundle = bundle_artifact["bundle"]
            bundle["body_segments"] = body_segment_rows
            bundle["message_occurrences"] = occurrence_rows
            bundle["messages"] = message_rows
            bundle_artifact["bundle_fingerprint"] = _contract_fingerprint(bundle)
            bundle_artifact["artifact_fingerprint"] = _contract_payload_fingerprint(
                bundle_artifact,
                "artifact_fingerprint",
            )

            source_snapshot = copy.deepcopy(fixture.source_snapshot)
            source_snapshot["parsed_mail_observations"] = parsed_rows
            source_snapshot["mail_evidence_bundle_fingerprint"] = bundle_artifact[
                "bundle_fingerprint"
            ]
            source_snapshot["snapshot_fingerprint"] = _contract_payload_fingerprint(
                source_snapshot,
                "snapshot_fingerprint",
            )
            source_bindings = {
                "bundle_artifact_fingerprint": bundle_artifact["artifact_fingerprint"],
                "mail_evidence_bundle_fingerprint": bundle_artifact["bundle_fingerprint"],
                "retrieval_snapshot_fingerprint": source_snapshot["snapshot_fingerprint"],
                "source_snapshot_fingerprint": source_snapshot["source_snapshot_fingerprint"],
                "source_inventory_fingerprint": source_snapshot["source_inventory_fingerprint"],
                "source_provenance_fingerprint": source_snapshot["source_provenance_fingerprint"],
                "permission_fingerprint": source_snapshot["permission_fingerprint"],
                "tokenizer_profile_fingerprint": source_snapshot["tokenizer_profile_fingerprint"],
                "index_fingerprint": source_snapshot["index_fingerprint"],
            }
            lineage = author_inputs._development_source_lineage(
                _canonical_bytes(bundle_artifact),
                _canonical_bytes(source_snapshot),
                source_bindings=source_bindings,
            )
            self.assertEqual(
                len(lineage["observation_hashes"]),
                supported_observation_count,
            )
            self.assertEqual(
                Counter(lineage["observation_types"].values()),
                Counter(
                    {
                        "email_body_segment": body_observation_count,
                        "email_header": header_observation_count,
                    }
                ),
            )
            self.assertEqual(
                len(lineage["occurrence_to_source_message"]),
                message_occurrence_count,
            )
            self.assertEqual(
                len(set(lineage["occurrence_to_source_message"].values())),
                2_792,
            )
            self.assertEqual(
                len(lineage["occurrence_to_email_message"]),
                message_occurrence_count,
            )
            self.assertEqual(
                len(set(lineage["occurrence_to_email_message"].values())),
                message_occurrence_count,
            )
            self.assertEqual(
                len(lineage["occurrence_to_thread"]),
                message_occurrence_count,
            )
            duplicate_occurrence_ids = [
                occurrence_id
                for occurrence_id, message_id in lineage["occurrence_to_source_message"].items()
                if message_id == source_native_message_ids[-1]
            ]
            self.assertEqual(len(duplicate_occurrence_ids), 2)
            self.assertEqual(
                {
                    lineage["occurrence_to_thread"][occurrence_id]
                    for occurrence_id in duplicate_occurrence_ids
                },
                {thread_ids[-1]},
            )

            invalid_snapshot = copy.deepcopy(source_snapshot)
            invalid_row = invalid_snapshot["parsed_mail_observations"][0]
            invalid_occurrence_id = invalid_row["location"]["message_occurrence_id"]
            invalid_occurrence = {row["message_occurrence_id"]: row for row in occurrence_rows}[
                invalid_occurrence_id
            ]
            invalid_row["location"]["message_id"] = invalid_occurrence["email_message_id"]
            invalid_row["payload"]["message_id"] = invalid_occurrence["email_message_id"]
            invalid_snapshot["snapshot_fingerprint"] = _contract_payload_fingerprint(
                invalid_snapshot,
                "snapshot_fingerprint",
            )
            invalid_bindings = dict(source_bindings)
            invalid_bindings["retrieval_snapshot_fingerprint"] = invalid_snapshot[
                "snapshot_fingerprint"
            ]
            with self.assertRaisesRegex(
                author_inputs.HoldoutSourceAuthorProjectionInputsError,
                "^development_source_observation_lineage_invalid$",
            ):
                author_inputs._development_source_lineage(
                    _canonical_bytes(bundle_artifact),
                    _canonical_bytes(invalid_snapshot),
                    source_bindings=invalid_bindings,
                )

    def test_optional_thread_hints_are_not_required_as_lineage_authority(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            no_thread_hints = copy.deepcopy(fixture.holdout_manifest)
            for case in no_thread_hints["cases"]:
                binding = case["source_evidence_binding"]
                binding.pop("required_thread_hashes", None)
                binding.pop("denied_thread_hashes", None)
            fixture.rewrite_holdout_and_preflight(no_thread_hints)

            artifacts = fixture.build(root / "without-thread-hints")
            self.assertEqual(
                artifacts.development_disjointness["disjointness"],
                fixture.disjointness,
            )
            for case in artifacts.source_lineage["cases"]:
                self.assertRegex(
                    case["source_evidence_binding"]["thread_evidence_hash_set_fingerprint"],
                    r"^sha256:[0-9a-f]{64}$",
                )

    def test_source_bundle_body_mapping_tamper_fails_before_projection(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            source_bindings = author_inputs._validated_source_artifact_bindings(
                source_bundle_bytes=fixture.source_bundle_path.read_bytes(),
                source_snapshot_bytes=fixture.source_snapshot_path.read_bytes(),
                preflight_summary=author_inputs._validate_preflight(
                    fixture.holdout_preflight,
                    private_manifest_sha256=fixture.holdout_manifest_sha256,
                ),
            )
            tampered_bundle_artifact = copy.deepcopy(fixture.source_bundle_artifact)
            body_segments = tampered_bundle_artifact["bundle"]["body_segments"]
            body_segments[-1]["message_occurrence_id"] = body_segments[0]["message_occurrence_id"]
            tampered_bundle_artifact["bundle_fingerprint"] = _contract_fingerprint(
                tampered_bundle_artifact["bundle"]
            )
            tampered_bundle_artifact["artifact_fingerprint"] = _contract_payload_fingerprint(
                tampered_bundle_artifact,
                "artifact_fingerprint",
            )
            tampered_bindings = dict(source_bindings)
            tampered_bindings["bundle_artifact_fingerprint"] = tampered_bundle_artifact[
                "artifact_fingerprint"
            ]
            tampered_bindings["mail_evidence_bundle_fingerprint"] = tampered_bundle_artifact[
                "bundle_fingerprint"
            ]
            with self.assertRaisesRegex(
                author_inputs.HoldoutSourceAuthorProjectionInputsError,
                "^development_source_observation_lineage_invalid$",
            ):
                author_inputs._development_source_lineage(
                    _canonical_bytes(tampered_bundle_artifact),
                    fixture.source_snapshot_path.read_bytes(),
                    source_bindings=tampered_bindings,
                )

    def test_build_emits_only_strict_safe_allowlisted_projection_inputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            output_root = root / "author-inputs"
            artifacts = fixture.build(output_root)

            self.assertNotEqual(
                fixture.holdout_manifest["manifest_fingerprint"],
                _payload_fingerprint(
                    fixture.holdout_manifest,
                    "manifest_fingerprint",
                ),
            )
            self.assertEqual(
                fixture.holdout_manifest["manifest_fingerprint"],
                fixture.holdout_preflight["hashes"]["manifest_fingerprint"],
            )
            for optional_v2_field in (
                "stratum_id",
                "authoring_source_observation_ids",
                "answer_oracle",
            ):
                self.assertEqual(
                    sum(optional_v2_field in case for case in fixture.holdout_cases),
                    11,
                )
            self.assertEqual(
                fixture.disjointness["holdout_authoring_observation_count"],
                78,
            )
            self.assertEqual(
                fixture.disjointness["holdout_authoring_message_count"],
                77,
            )
            self.assertEqual(
                fixture.disjointness["holdout_authoring_thread_count"],
                75,
            )
            self.assertEqual(
                sorted(path.name for path in output_root.iterdir()),
                sorted(
                    [
                        author_inputs.SOURCE_LINEAGE_FILENAME,
                        author_inputs.DEVELOPMENT_DISJOINTNESS_FILENAME,
                    ]
                ),
            )
            self.assertEqual(
                stat_mode(artifacts.source_lineage_path),
                0o400,
            )
            self.assertEqual(
                stat_mode(artifacts.development_disjointness_path),
                0o400,
            )
            source_lineage = json.loads(artifacts.source_lineage_path.read_bytes())
            development_disjointness = json.loads(
                artifacts.development_disjointness_path.read_bytes()
            )
            self.assertEqual(
                set(source_lineage),
                {
                    "artifact_id",
                    "schema_version",
                    "status",
                    "execution_status",
                    "quality_result_status",
                    "holdout_preflight_safe_sha256",
                    "private_manifest_sha256",
                    "manifest_fingerprint",
                    "partition_fingerprint",
                    "case_count",
                    "case_strata_counts",
                    "source_oracle_bindings",
                    "cases",
                    "source_lineage_fingerprint",
                },
            )
            self.assertEqual(
                set(development_disjointness),
                {
                    "artifact_id",
                    "schema_version",
                    "status",
                    "execution_status",
                    "quality_result_status",
                    "holdout_preflight_safe_sha256",
                    "private_manifest_sha256",
                    "manifest_fingerprint",
                    "partition_fingerprint",
                    "case_count",
                    "case_strata_counts",
                    "development_exclusion_binding",
                    "disjointness",
                    "development_disjointness_fingerprint",
                },
            )
            self.assertEqual(
                source_lineage["source_lineage_fingerprint"],
                _payload_fingerprint(
                    source_lineage,
                    "source_lineage_fingerprint",
                ),
            )
            self.assertEqual(
                development_disjointness["development_disjointness_fingerprint"],
                _payload_fingerprint(
                    development_disjointness,
                    "development_disjointness_fingerprint",
                ),
            )
            expected_case_fields = set(projection_builder._ORACLE_FREE_CASE_FIELD_NAMES)
            expected_binding_fields = {
                "source_evidence_binding_fingerprint",
                "required_observation_hash_set_fingerprint",
                "forbidden_observation_hash_set_fingerprint",
                "authoring_observation_hash_set_fingerprint",
                "message_occurrence_evidence_hash_set_fingerprint",
                "message_evidence_hash_set_fingerprint",
                "thread_evidence_hash_set_fingerprint",
                "thread_occurrence_evidence_hash_sequence_fingerprint",
                "native_observation_evidence_hash_set_fingerprint",
                "projection_policy_fingerprint",
            }
            self.assertEqual(
                set(source_lineage["source_oracle_bindings"]),
                set(projection_builder._SOURCE_BINDING_FIELDS),
            )
            self.assertNotIn(
                "native_source_manifest_fingerprint",
                source_lineage["source_oracle_bindings"],
            )
            self.assertNotIn(
                "source_author_permission_fingerprint",
                source_lineage["source_oracle_bindings"],
            )
            for case in source_lineage["cases"]:
                self.assertEqual(set(case), expected_case_fields)
                self.assertRegex(case["case_id"], r"^sha256:[0-9a-f]{64}$")
                self.assertRegex(
                    case["query_text"],
                    r"^sha256:[0-9a-f]{64}$",
                )
                self.assertRegex(
                    case["requester_user_id"],
                    r"^sha256:[0-9a-f]{64}$",
                )
                for field_name in (
                    "required_source_observation_ids",
                    "forbidden_source_observation_ids",
                    "authoring_source_observation_ids",
                ):
                    for identifier_hash in case[field_name]:
                        self.assertRegex(
                            identifier_hash,
                            r"^sha256:[0-9a-f]{64}$",
                        )
                self.assertEqual(
                    set(case["source_evidence_binding"]),
                    expected_binding_fields,
                )
                for value in case["source_evidence_binding"].values():
                    self.assertRegex(value, r"^sha256:[0-9a-f]{64}$")

            output_payload = b"".join(path.read_bytes() for path in output_root.iterdir())
            for forbidden in (
                b"answer_oracle",
                b"expected_private",
                _RAW_QUERY_MARKER.encode(),
                _RAW_ANSWER_MARKER.encode(),
                _RAW_EXPECTED_MARKER.encode(),
                _RAW_LOCATOR_MARKER.encode(),
                _RAW_IDENTIFIER_MARKER.encode(),
                b"private-holdout-case-",
                b"holdout-observation-",
                b"private-requester-",
            ):
                self.assertNotIn(forbidden, output_payload)

            projection_root = root / "projection"
            built_projection = projection_builder.build_holdout_oracle_free_projection_artifacts(
                holdout_preflight_safe_path=(fixture.holdout_preflight_path),
                expected_holdout_preflight_safe_sha256=(fixture.holdout_preflight_sha256),
                private_holdout_manifest_path=(fixture.holdout_manifest_path),
                expected_private_holdout_manifest_sha256=(fixture.holdout_manifest_sha256),
                source_lineage_safe_path=(artifacts.source_lineage_path),
                expected_source_lineage_safe_sha256=_sha256_bytes(
                    artifacts.source_lineage_path.read_bytes()
                ),
                development_disjointness_safe_path=(artifacts.development_disjointness_path),
                expected_development_disjointness_safe_sha256=(
                    _sha256_bytes(artifacts.development_disjointness_path.read_bytes())
                ),
                output_root=projection_root,
            )
            self.assertEqual(
                built_projection.projection["status"],
                "sealed_oracle_free",
            )
            self.assertEqual(
                built_projection.projection["case_count"],
                projection_builder.EXPECTED_CASE_COUNT,
            )

    def test_cli_stdout_is_hash_count_status_only_and_never_leaks(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            output_root = root / "cli-output"
            command = [
                sys.executable,
                "scripts/issue56_holdout_source_author_projection_inputs.py",
                *fixture.cli_args(output_root),
            ]
            completed = subprocess.run(
                command,
                cwd=Path(__file__).resolve().parents[1],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stderr, "")
            self.assertEqual(len(completed.stdout.splitlines()), 1)
            stdout_payload = json.loads(completed.stdout)
            self.assertEqual(
                set(stdout_payload),
                {
                    "artifact_id",
                    "schema_version",
                    "status",
                    "source_author_boundary_status",
                    "private_manifest_decode_status",
                    "quality_execution_status",
                    "oracle_output_status",
                    "raw_query_output_status",
                    "reversible_identifier_output_status",
                    "immutability_status",
                    "policy_fingerprint",
                    "counts",
                    "hashes",
                    "result_fingerprint",
                },
            )
            self.assertEqual(stdout_payload["status"], "passed")
            self.assertEqual(
                stdout_payload["quality_execution_status"],
                "not_run",
            )
            self.assertEqual(stdout_payload["counts"]["blocker_count"], 0)
            for forbidden in (
                "answer_oracle",
                "expected_private",
                _RAW_QUERY_MARKER,
                _RAW_ANSWER_MARKER,
                _RAW_EXPECTED_MARKER,
                _RAW_LOCATOR_MARKER,
                _RAW_IDENTIFIER_MARKER,
                str(root),
            ):
                self.assertNotIn(forbidden, completed.stdout)

    def test_deterministic_bytes_and_immutable_no_overwrite(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            first_root = root / "first"
            second_root = root / "second"
            first = fixture.build(first_root)
            second = fixture.build(second_root)
            self.assertEqual(
                first.source_lineage_path.read_bytes(),
                second.source_lineage_path.read_bytes(),
            )
            self.assertEqual(
                first.development_disjointness_path.read_bytes(),
                second.development_disjointness_path.read_bytes(),
            )
            before = {path.name: path.read_bytes() for path in first_root.iterdir()}
            with self.assertRaisesRegex(
                author_inputs.HoldoutSourceAuthorProjectionInputsError,
                "^immutable_output_already_exists$",
            ):
                fixture.build(first_root)
            self.assertEqual(
                before,
                {path.name: path.read_bytes() for path in first_root.iterdir()},
            )

    def test_seal_tamper_and_cross_manifest_binding_fail_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            with self.assertRaisesRegex(
                author_inputs.HoldoutSourceAuthorProjectionInputsError,
                "^holdout_manifest_seal_mismatch$",
            ):
                fixture.build(
                    root / "bad-seal",
                    expected_holdout_manifest_sha256=_fingerprint("wrong-holdout-bytes"),
                )
            self.assertFalse((root / "bad-seal").exists())
            with self.assertRaisesRegex(
                author_inputs.HoldoutSourceAuthorProjectionInputsError,
                "^development_manifest_seal_mismatch$",
            ):
                fixture.build(
                    root / "bad-development-seal",
                    expected_development_manifest_sha256=_fingerprint("wrong-development-bytes"),
                )
            self.assertFalse((root / "bad-development-seal").exists())

            cross_manifest = copy.deepcopy(fixture.holdout_manifest)
            cross_manifest["development_exclusion_binding"]["development_registry_fingerprint"] = (
                _fingerprint("different-development-registry")
            )
            fixture.rewrite_holdout_and_preflight(cross_manifest)
            with self.assertRaisesRegex(
                author_inputs.HoldoutSourceAuthorProjectionInputsError,
                "^development_exclusion_cross_manifest_mismatch$",
            ):
                fixture.build(root / "cross-manifest")
            self.assertFalse((root / "cross-manifest").exists())

    def test_preflight_cross_binding_and_legacy_schema_fail_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)

            mismatched_preflight = copy.deepcopy(fixture.holdout_preflight)
            mismatched_preflight["hashes"]["manifest_fingerprint"] = _fingerprint(
                "different-sealed-manifest-fingerprint"
            )
            mismatched_preflight["report_fingerprint"] = _payload_fingerprint(
                mismatched_preflight,
                "report_fingerprint",
            )
            fixture.holdout_preflight = mismatched_preflight
            fixture.holdout_preflight_sha256 = _write_json(
                fixture.holdout_preflight_path,
                mismatched_preflight,
            )
            with self.assertRaisesRegex(
                author_inputs.HoldoutSourceAuthorProjectionInputsError,
                "^holdout_manifest_preflight_cross_binding_mismatch$",
            ):
                fixture.build(root / "cross-binding")
            self.assertFalse((root / "cross-binding").exists())

            legacy_root = root / "legacy-fixture"
            legacy_root.mkdir()
            fixture = _Fixture(legacy_root)
            legacy = copy.deepcopy(fixture.holdout_manifest)
            legacy["schema_version"] = 1
            fixture.rewrite_holdout_and_preflight(legacy)
            with self.assertRaisesRegex(
                author_inputs.HoldoutSourceAuthorProjectionInputsError,
                "^holdout_manifest_legacy_or_unknown_schema_rejected$",
            ):
                fixture.build(root / "legacy")
            self.assertFalse((root / "legacy").exists())

    def test_development_unknown_fields_are_strictly_rejected(
        self,
    ) -> None:
        scenarios = (
            ("top", "development_manifest_contract_invalid"),
            ("case", "development_case_contract_invalid"),
            ("source_binding", "development_source_bindings_contract_invalid"),
        )
        for scenario, reason_code in scenarios:
            with self.subTest(scenario=scenario):
                with tempfile.TemporaryDirectory() as raw_root:
                    root = Path(raw_root)
                    fixture = _Fixture(root)
                    manifest = copy.deepcopy(fixture.development_manifest)
                    if scenario == "top":
                        manifest["unknown_private_field"] = {"query": "合成私有擴充"}
                    elif scenario == "case":
                        manifest["cases"][0]["unknown_private_field"] = {"query": "合成私有擴充"}
                        manifest["cases"][0]["private_fingerprint"] = _contract_payload_fingerprint(
                            manifest["cases"][0],
                            "private_fingerprint",
                        )
                        manifest["manifest_fingerprint"] = _contract_payload_fingerprint(
                            manifest,
                            "manifest_fingerprint",
                        )
                    else:
                        manifest["source_bindings"]["unknown_private_field"] = _fingerprint(
                            "unknown-development-source-binding"
                        )
                        manifest["manifest_fingerprint"] = _contract_payload_fingerprint(
                            manifest,
                            "manifest_fingerprint",
                        )
                    fixture.rewrite_development(
                        manifest,
                        rebuild_report=False,
                        rebind_holdout=False,
                    )
                    with self.assertRaisesRegex(
                        author_inputs.HoldoutSourceAuthorProjectionInputsError,
                        f"^{reason_code}$",
                    ):
                        fixture.build(root / "rejected")
                    self.assertFalse((root / "rejected").exists())

    def test_development_internal_and_case_lineage_tamper_fail_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            fingerprint_tamper = copy.deepcopy(fixture.development_manifest)
            fingerprint_tamper["manifest_fingerprint"] = _fingerprint(
                "tampered-development-manifest"
            )
            fixture.rewrite_development(
                fingerprint_tamper,
                rebuild_report=False,
                rebind_holdout=False,
            )
            with self.assertRaisesRegex(
                author_inputs.HoldoutSourceAuthorProjectionInputsError,
                "^development_manifest_contract_invalid$",
            ):
                fixture.build(root / "manifest-fingerprint-tamper")

        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            lineage_tamper = copy.deepcopy(fixture.development_manifest)
            lineage_tamper["cases"][0]["source_evidence_binding"]["required_observation_hashes"][
                0
            ] = _contract_fingerprint("different-observation")
            lineage_tamper["cases"][0]["private_fingerprint"] = _contract_payload_fingerprint(
                lineage_tamper["cases"][0],
                "private_fingerprint",
            )
            lineage_tamper["manifest_fingerprint"] = _contract_payload_fingerprint(
                lineage_tamper,
                "manifest_fingerprint",
            )
            fixture.rewrite_development(
                lineage_tamper,
                rebuild_report=True,
                rebind_holdout=True,
            )
            with self.assertRaisesRegex(
                author_inputs.HoldoutSourceAuthorProjectionInputsError,
                "^development_case_source_lineage_binding_mismatch$",
            ):
                fixture.build(root / "case-lineage-tamper")
            self.assertFalse((root / "case-lineage-tamper").exists())

    def test_development_safe_report_and_source_cross_run_binding_fail_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            report_tamper = copy.deepcopy(fixture.development_report)
            report_tamper["fingerprints"]["index_fingerprint"] = _fingerprint(
                "different-report-index"
            )
            report_tamper["report_fingerprint"] = _contract_payload_fingerprint(
                report_tamper,
                "report_fingerprint",
            )
            fixture.rewrite_development_report(
                report_tamper,
                rebind_holdout=True,
            )
            with self.assertRaisesRegex(
                author_inputs.HoldoutSourceAuthorProjectionInputsError,
                "^development_safe_report_binding_mismatch$",
            ):
                fixture.build(root / "safe-report-binding-tamper")

        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            cross_run = copy.deepcopy(fixture.development_manifest)
            cross_run["source_bindings"]["index_fingerprint"] = _fingerprint(
                "different-source-run-index"
            )
            cross_run["manifest_fingerprint"] = _contract_payload_fingerprint(
                cross_run,
                "manifest_fingerprint",
            )
            fixture.rewrite_development(
                cross_run,
                rebuild_report=True,
                rebind_holdout=True,
            )
            with self.assertRaisesRegex(
                author_inputs.HoldoutSourceAuthorProjectionInputsError,
                "^development_source_artifact_cross_run_mismatch$",
            ):
                fixture.build(root / "cross-run")

    def test_development_holdout_overlap_uses_derived_source_lineage(
        self,
    ) -> None:
        scenarios = ("observation", "message", "thread")
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                with tempfile.TemporaryDirectory() as raw_root:
                    root = Path(raw_root)
                    fixture = _Fixture(root)
                    holdout_manifest = copy.deepcopy(fixture.holdout_manifest)
                    first_case = holdout_manifest["cases"][0]
                    if scenario == "observation":
                        observation_id = fixture.development_observation_ids[0]
                        occurrence_id = fixture.development_occurrence_ids[0]
                        message_id = fixture.development_occurrence_to_email_message[occurrence_id]
                        thread_id = fixture.development_occurrence_to_thread[occurrence_id]
                        first_case["required_source_observation_ids"][0] = observation_id
                        second_observation_id = first_case["required_source_observation_ids"][1]
                        holdout_row_by_id = {
                            str(row["observation_id"]): row
                            for row in fixture.holdout_observation_rows
                        }
                        second_occurrence_id = fixture.holdout_observation_to_occurrence[
                            second_observation_id
                        ]
                        second_message_id = fixture.holdout_occurrence_to_email_message[
                            second_occurrence_id
                        ]
                        second_thread_id = fixture.holdout_occurrence_to_thread[
                            second_occurrence_id
                        ]
                        first_case["source_evidence_binding"] |= {
                            "required_observation_hashes": sorted(
                                (
                                    _contract_fingerprint(fixture.development_observation_rows[0]),
                                    _contract_fingerprint(holdout_row_by_id[second_observation_id]),
                                )
                            ),
                            "required_message_occurrence_hashes": sorted(
                                (
                                    _contract_fingerprint(occurrence_id),
                                    _contract_fingerprint(second_occurrence_id),
                                )
                            ),
                            "required_message_hashes": sorted(
                                (
                                    _contract_fingerprint(message_id),
                                    _contract_fingerprint(second_message_id),
                                )
                            ),
                            "required_thread_hashes": sorted(
                                (
                                    _contract_fingerprint(thread_id),
                                    _contract_fingerprint(second_thread_id),
                                )
                            ),
                        }
                        expected_reason = "development_holdout_overlap_detected"
                    elif scenario == "message":
                        first_occurrence = fixture.development_occurrence_ids[0]
                        first_message = fixture.development_occurrence_to_email_message[
                            first_occurrence
                        ]
                        first_case["source_evidence_binding"]["required_message_hashes"][0] = (
                            _contract_fingerprint(first_message)
                        )
                        expected_reason = "holdout_case_message_hashes_binding_mismatch"
                    else:
                        first_occurrence = fixture.development_occurrence_ids[0]
                        first_thread = fixture.development_occurrence_to_thread[first_occurrence]
                        first_case["source_evidence_binding"]["required_thread_hashes"][0] = (
                            _contract_fingerprint(first_thread)
                        )
                        expected_reason = "holdout_case_thread_hashes_binding_mismatch"
                    fixture.rewrite_holdout_and_preflight(holdout_manifest)
                    with self.assertRaisesRegex(
                        author_inputs.HoldoutSourceAuthorProjectionInputsError,
                        f"^{expected_reason}$",
                    ):
                        fixture.build(root / "overlap")
                    self.assertFalse((root / "overlap").exists())

    def test_unknown_private_fields_are_ignored_but_never_projected(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            baseline_artifacts = fixture.build(root / "baseline")
            unknown_private_marker = "PRIVATE_UNKNOWN_EXTENSION_DO_NOT_PROJECT"
            extended = copy.deepcopy(fixture.holdout_manifest)
            extended["cases"][0]["unlisted_private_hint"] = {
                "value": unknown_private_marker,
                "raw_source_locator": _RAW_LOCATOR_MARKER,
            }
            extended["cases"][0]["source_evidence_binding"]["unlisted_binding_hint"] = {
                "value": unknown_private_marker,
                "private_identifier": _RAW_IDENTIFIER_MARKER,
            }
            fixture.rewrite_holdout_and_preflight(extended)
            artifacts = fixture.build(root / "extended")
            self.assertEqual(
                artifacts.source_lineage["cases"],
                baseline_artifacts.source_lineage["cases"],
            )
            output_payload = (
                artifacts.source_lineage_path.read_bytes()
                + artifacts.development_disjointness_path.read_bytes()
            )
            for forbidden in (
                unknown_private_marker.encode(),
                _RAW_LOCATOR_MARKER.encode(),
                _RAW_IDENTIFIER_MARKER.encode(),
                b"unlisted_private_hint",
                b"unlisted_binding_hint",
            ):
                self.assertNotIn(forbidden, output_payload)

    def test_malformed_v2_evidence_hash_aliases_fail_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            malformed = copy.deepcopy(fixture.holdout_manifest)
            malformed["cases"][0]["source_evidence_binding"]["required_message_hashes"] = [
                "not-a-sha256"
            ]
            fixture.rewrite_holdout_and_preflight(malformed)
            with self.assertRaisesRegex(
                author_inputs.HoldoutSourceAuthorProjectionInputsError,
                "^holdout_case_message_hashes_invalid$",
            ):
                fixture.build(root / "malformed")
            self.assertFalse((root / "malformed").exists())

    def test_second_staged_write_failure_leaves_no_partial_output(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            output_root = root / "atomic-failure"
            write_count = 0

            def fail_second_write(
                path: Path,
                payload: bytes,
                mode: int,
            ) -> None:
                nonlocal write_count
                write_count += 1
                if write_count == 2:
                    raise OSError("injected second write failure")
                author_inputs._write_file_exclusive(path, payload, mode)

            with self.assertRaisesRegex(
                author_inputs.HoldoutSourceAuthorProjectionInputsError,
                "^atomic_artifact_persistence_failed$",
            ):
                fixture.build(
                    output_root,
                    write_staged_file=fail_second_write,
                )
            self.assertFalse(output_root.exists())
            self.assertEqual(
                list(root.glob(".atomic-failure.staging-*")),
                [],
            )


def stat_mode(path: Path) -> int:
    return os.stat(path, follow_symlinks=False).st_mode & 0o777


if __name__ == "__main__":
    unittest.main()
