from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import _paths  # noqa: F401
from formowl_contract import Observation, sha256_json
from formowl_core import ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT
from formowl_mail.bundle import (
    EmailBodySegment,
    EmailMessage,
    EmailMessageOccurrence,
    MailArchiveOccurrence,
    MailEvidenceBundle,
    MailFolderOccurrence,
    MailImportSession,
    MailParseRun,
)
from scripts import issue56_independent_mail_holdout_uat as holdout_uat
from scripts import issue56_source_independent_mail_holdout_extension as extension


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


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _letters(index: int) -> str:
    value = index
    digits: list[str] = []
    while True:
        digits.append(chr(ord("a") + (value % 26)))
        value //= 26
        if value == 0:
            break
    return "".join(reversed(digits)).rjust(3, "a")


class _Fixture:
    def __init__(self, root: Path, *, graph_pair_count: int = 42) -> None:
        self.root = root
        self.bundle_path = root / "bundle.private.json"
        self.snapshot_path = root / "snapshot.private.json"
        self.development_manifest_path = root / "development.private.json"
        self.development_safe_path = root / "development.safe.json"
        self.base_manifest_path = root / "base-holdout.private.json"
        self.base_safe_path = root / "base-holdout.safe.json"
        self.permission_scope = {
            "scope_type": "workspace",
            "visibility": "restricted",
            "scope_id": "workspace-fixture",
        }
        self.permission_fingerprint = sha256_json(self.permission_scope)
        self.source_snapshot_fingerprint = sha256_json("synthetic-source-snapshot")
        self.source_inventory_fingerprint = sha256_json("synthetic-source-inventory")
        self.source_provenance_fingerprint = sha256_json("synthetic-source-provenance")
        self.index_fingerprint = sha256_json("synthetic-source-index")
        self.observations: list[Observation] = []
        self.texts: list[str] = []
        self.lineage_by_observation_id: dict[str, dict[str, str]] = {}

        self._append_development_records()
        self._append_base_holdout_records()
        self.extension_start = len(self.observations)
        self._append_extension_records(graph_pair_count=graph_pair_count)
        self._write_source_artifacts()
        self._write_development_artifacts()
        self._write_base_artifacts()

    def _append_record(
        self,
        text: str,
        *,
        observation_type: str = "email_body_segment",
        occurrence_id: str | None = None,
        email_message_id: str | None = None,
        source_message_id: str | None = None,
        thread_id: str | None = None,
        source_inventory_item_id: str | None = None,
        source_local_key: str | None = None,
        source_content_hash: str | None = None,
    ) -> str:
        index = len(self.observations)
        observation_id = f"observation-{index:04d}"
        occurrence_id = occurrence_id or f"occurrence-{index:04d}"
        email_message_id = email_message_id or f"email-message-{index:04d}"
        source_message_id = source_message_id or f"message-local-{index:04d}"
        thread_id = thread_id or f"thread-{index:04d}"
        source_inventory_item_id = source_inventory_item_id or f"inventory-item-{index:04d}"
        source_local_key = source_local_key or f"source-item-{index:04d}"
        source_content_hash = source_content_hash or sha256_json(
            {
                "email_message_id": email_message_id,
                "source_message_id": source_message_id,
            }
        )
        native_lineage = {
            "message_occurrence_id": occurrence_id,
            "message_id": source_message_id,
            "thread_id": thread_id,
            "source_provenance_fingerprint": self.source_provenance_fingerprint,
        }
        location: dict[str, object] = {
            **native_lineage,
            "source_inventory_item_id": source_inventory_item_id,
            "source_local_key": source_local_key,
            "source_content_hash": source_content_hash,
        }
        payload: dict[str, object] = {
            **native_lineage,
            "canonical_fact_status": "not_asserted",
        }
        if observation_type == "email_header":
            location |= {
                "header_index": index,
                "header_name": "fixture-header",
            }
            payload |= {
                "header_name": "fixture-header",
                "header_value": text,
            }
        else:
            location["body_segment_index"] = 0
            payload["body_segment_index"] = 0
        self.observations.append(
            Observation(
                observation_id=observation_id,
                extractor_run_id="extractor-run-fixture",
                observation_type=observation_type,
                modality="mail",
                location=location,
                confidence=1.0,
                permission_scope=dict(self.permission_scope),
                created_at="2026-08-01T00:00:00+00:00",
                asset_id="asset-fixture",
                text=text,
                payload=payload,
            )
        )
        self.texts.append(text)
        self.lineage_by_observation_id[observation_id] = {
            "message_occurrence_id": occurrence_id,
            "email_message_id": email_message_id,
            "message_id": source_message_id,
            "thread_id": thread_id,
            "source_inventory_item_id": source_inventory_item_id,
            "source_local_key": source_local_key,
            "source_content_hash": source_content_hash,
        }
        return observation_id

    def _append_development_records(self) -> None:
        self.development_observation_ids = [
            self._append_record(f"PO{100_000_000 + index:09d} developmentconcept{_letters(index)}")
            for index in range(200)
        ]

    def _append_base_holdout_records(self) -> None:
        self.base_observation_ids: list[str] = []
        first_lineage: dict[str, str] | None = None
        shared_thread_one: str | None = None
        shared_thread_two: str | None = None
        for index in range(78):
            observation_type = "email_header" if index < 17 else "email_body_segment"
            kwargs: dict[str, str] = {}
            if index == 1:
                if shared_thread_one is None:
                    raise AssertionError("base shared thread fixture missing")
                kwargs["thread_id"] = shared_thread_one
                if first_lineage is None:
                    raise AssertionError("base duplicate source message fixture missing")
                kwargs["source_message_id"] = first_lineage["message_id"]
            elif index == 3:
                if shared_thread_two is None:
                    raise AssertionError("base shared thread fixture missing")
                kwargs["thread_id"] = shared_thread_two
            elif index == 17:
                if first_lineage is None:
                    raise AssertionError("base duplicate occurrence fixture missing")
                kwargs = {
                    "occurrence_id": first_lineage["message_occurrence_id"],
                    "email_message_id": first_lineage["email_message_id"],
                    "source_message_id": first_lineage["message_id"],
                    "thread_id": first_lineage["thread_id"],
                    "source_inventory_item_id": first_lineage["source_inventory_item_id"],
                    "source_local_key": first_lineage["source_local_key"],
                    "source_content_hash": first_lineage["source_content_hash"],
                }
            observation_id = self._append_record(
                f"PO{200_000_000 + index:09d} baseconcept{_letters(index)}",
                observation_type=observation_type,
                **kwargs,
            )
            self.base_observation_ids.append(observation_id)
            lineage = self.lineage_by_observation_id[observation_id]
            if index == 0:
                first_lineage = dict(lineage)
                shared_thread_one = lineage["thread_id"]
            elif index == 2:
                shared_thread_two = lineage["thread_id"]

        self.base_message_ids = {
            self.lineage_by_observation_id[observation_id]["email_message_id"]
            for observation_id in self.base_observation_ids
        }
        self.base_thread_ids = {
            self.lineage_by_observation_id[observation_id]["thread_id"]
            for observation_id in self.base_observation_ids
        }
        self.assert_fixture(
            sum(
                self._observation(observation_id).observation_type == "email_body_segment"
                for observation_id in self.base_observation_ids
            )
            == 61
        )
        self.assert_fixture(
            sum(
                self._observation(observation_id).observation_type == "email_header"
                for observation_id in self.base_observation_ids
            )
            == 17
        )
        self.assert_fixture(len(self.base_message_ids) == 77)
        self.assert_fixture(len(self.base_thread_ids) == 75)

    def _append_extension_records(self, *, graph_pair_count: int) -> None:
        record_number = 0
        for pair_index in range(graph_pair_count):
            identifier = f"PO{300_000_000 + pair_index:09d}"
            for side in range(2):
                self._append_record(f"{identifier} graphconcept{_letters(record_number)}")
                record_number += 1
        for exact_index in range(16):
            left = f"PO{400_000_000 + exact_index * 2:09d}"
            right = f"PO{400_000_001 + exact_index * 2:09d}"
            self._append_record(f"{left} {right} exactconcept{_letters(exact_index)}")
        singleton_count = 43
        for singleton_index in range(singleton_count):
            self._append_record(
                f"PO{500_000_000 + singleton_index:09d} "
                f"singleconcept{_letters(singleton_index)}"
            )

    def _observation(self, observation_id: str) -> Observation:
        for observation in self.observations:
            if observation.observation_id == observation_id:
                return observation
        raise AssertionError("fixture observation missing")

    def _write_source_artifacts(self) -> None:
        import_session = MailImportSession(
            mail_import_session_id="mail-import-session-fixture",
            workspace_id="workspace-fixture",
            owner_user_id="owner-fixture",
            source_asset_id="asset-fixture",
            archive_sha256=sha256_json("archive-fixture"),
            retention_policy="retain_7_days",
            raw_archive_retention_decision="retained_by_policy",
            created_at="2026-08-01T00:00:00+00:00",
            upload_session_id="upload-session-fixture",
        )
        archive_occurrence = MailArchiveOccurrence(
            mail_archive_occurrence_id="archive-occurrence-fixture",
            mail_import_session_id=import_session.mail_import_session_id,
            source_asset_id=import_session.source_asset_id,
            archive_id="archive-fixture",
            mailbox_id="mailbox-fixture",
            archive_sha256=import_session.archive_sha256,
            created_at="2026-08-01T00:00:00+00:00",
        )
        folder_occurrence = MailFolderOccurrence(
            mail_folder_occurrence_id="folder-occurrence-fixture",
            mail_archive_occurrence_id=archive_occurrence.mail_archive_occurrence_id,
            archive_id=archive_occurrence.archive_id,
            mailbox_id=archive_occurrence.mailbox_id,
            folder_path_hash=sha256_json("folder-fixture"),
            source_observation_id=self.observations[0].observation_id,
            folder_label="Fixture",
        )
        messages: list[EmailMessage] = []
        occurrences: list[EmailMessageOccurrence] = []
        segments: list[EmailBodySegment] = []
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        observations_by_email_message: dict[str, list[Observation]] = {}
        observation_index_by_email_message: dict[str, int] = {}
        for index, observation in enumerate(self.observations):
            lineage = self.lineage_by_observation_id[observation.observation_id]
            email_message_id = lineage["email_message_id"]
            observations_by_email_message.setdefault(email_message_id, []).append(observation)
            observation_index_by_email_message.setdefault(email_message_id, index)

        for email_message_id, source_observations in observations_by_email_message.items():
            first = source_observations[0]
            index = observation_index_by_email_message[email_message_id]
            lineage = self.lineage_by_observation_id[first.observation_id]
            sent_at = (start + timedelta(minutes=index)).isoformat()
            message_fingerprint = sha256_json(
                {
                    "email_message_id": email_message_id,
                    "message_id": lineage["message_id"],
                    "source_observation_ids": [
                        observation.observation_id for observation in source_observations
                    ],
                }
            )
            messages.append(
                EmailMessage(
                    email_message_id=email_message_id,
                    message_fingerprint=message_fingerprint,
                    message_id=lineage["message_id"],
                    archive_id=archive_occurrence.archive_id,
                    mailbox_id=archive_occurrence.mailbox_id,
                    source_observation_ids=[
                        observation.observation_id for observation in source_observations
                    ],
                    subject=f"Fixture {index:04d}",
                    normalized_subject=f"fixture {index:04d}",
                    sender="fixture@example.test",
                    sent_at=sent_at,
                    body_hash=lineage["source_content_hash"],
                    thread_id=lineage["thread_id"],
                )
            )

        seen_occurrences: set[str] = set()
        for index, observation in enumerate(self.observations):
            lineage = self.lineage_by_observation_id[observation.observation_id]
            occurrence_id = lineage["message_occurrence_id"]
            if occurrence_id in seen_occurrences:
                continue
            seen_occurrences.add(occurrence_id)
            occurrences.append(
                EmailMessageOccurrence(
                    email_message_occurrence_id=f"email-occurrence-{index:04d}",
                    email_message_id=lineage["email_message_id"],
                    mail_archive_occurrence_id=(archive_occurrence.mail_archive_occurrence_id),
                    message_occurrence_id=occurrence_id,
                    message_id=lineage["message_id"],
                    archive_id=archive_occurrence.archive_id,
                    mailbox_id=archive_occurrence.mailbox_id,
                    folder_path_hash=folder_occurrence.folder_path_hash,
                    source_observation_id=observation.observation_id,
                    thread_id=lineage["thread_id"],
                )
            )

        for index, observation in enumerate(self.observations):
            if observation.observation_type != "email_body_segment":
                continue
            lineage = self.lineage_by_observation_id[observation.observation_id]
            body_segment_hash = sha256_json(
                {
                    "email_message_id": lineage["email_message_id"],
                    "body_segment_index": 0,
                    "text": observation.text,
                }
            )
            segments.append(
                EmailBodySegment(
                    email_body_segment_id=f"body-segment-{index:04d}",
                    email_message_id=lineage["email_message_id"],
                    message_occurrence_id=lineage["message_occurrence_id"],
                    source_observation_id=observation.observation_id,
                    text=str(observation.text),
                    body_segment_hash=body_segment_hash,
                    body_segment_index=0,
                )
            )
        parse_run = MailParseRun(
            mail_parse_run_id="parse-run-fixture",
            mail_import_session_id=import_session.mail_import_session_id,
            extractor_run_id="extractor-run-fixture",
            parser_name="fixture-parser",
            parser_version="1",
            input_hash=import_session.archive_sha256,
            config_hash=sha256_json("fixture-config"),
            status="succeeded",
            started_at="2026-08-01T00:00:00+00:00",
            completed_at="2026-08-01T00:01:00+00:00",
        )
        bundle = MailEvidenceBundle(
            mail_evidence_bundle_id="mail-evidence-bundle-fixture",
            producer_type="fixture_parser",
            mail_import_session=import_session,
            archive_occurrences=[archive_occurrence],
            folder_occurrences=[folder_occurrence],
            messages=messages,
            message_occurrences=occurrences,
            body_segments=segments,
            attachments=[],
            attachment_occurrences=[],
            quoted_message_candidates=[],
            embedded_message_relations=[],
            mail_parse_run=parse_run,
            parse_warnings=[],
            created_at="2026-08-01T00:02:00+00:00",
        )
        bundle_payload = bundle.to_dict()
        self.bundle = bundle
        self.bundle_payload = bundle_payload
        self.expected_message_count = len(messages)
        bundle_artifact: dict[str, object] = {
            "artifact_id": "formowl_issue56_native_mail_evidence_bundle_v1",
            "schema_version": 1,
            "status": "passed",
            "source_snapshot_fingerprint": self.source_snapshot_fingerprint,
            "source_inventory_fingerprint": self.source_inventory_fingerprint,
            "source_provenance_fingerprint": (self.source_provenance_fingerprint),
            "bundle": bundle_payload,
            "bundle_fingerprint": sha256_json(bundle_payload),
        }
        bundle_artifact["artifact_fingerprint"] = extension._payload_fingerprint(
            bundle_artifact,
            "artifact_fingerprint",
        )
        self.bundle_sha256 = self._write(self.bundle_path, bundle_artifact)

        snapshot: dict[str, object] = {
            "artifact_id": ("formowl_issue56_native_source_complete_retrieval_ready_snapshot_v1"),
            "schema_version": 1,
            "status": "passed",
            "claim_boundary_status": ("retrieval_ready_evidence_not_canonical_fact"),
            "source_snapshot_fingerprint": self.source_snapshot_fingerprint,
            "source_inventory_fingerprint": self.source_inventory_fingerprint,
            "source_provenance_fingerprint": (self.source_provenance_fingerprint),
            "permission_fingerprint": self.permission_fingerprint,
            "mail_evidence_bundle_fingerprint": sha256_json(bundle_payload),
            "tokenizer_profile_fingerprint": (ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT),
            "index_fingerprint": self.index_fingerprint,
            "parsed_mail_observations": [
                observation.to_dict() for observation in self.observations
            ],
            "counts": {
                "mail_bundle_message_count": len(messages),
                "mail_bundle_message_occurrence_count": len(occurrences),
                "parsed_body_segment_observation_count": sum(
                    observation.observation_type == "email_body_segment"
                    for observation in self.observations
                ),
                "parsed_header_observation_count": sum(
                    observation.observation_type == "email_header"
                    for observation in self.observations
                ),
                "missing_source_inventory_binding_count": 0,
                "missing_source_local_key_binding_count": 0,
                "missing_content_hash_binding_count": 0,
                "missing_permission_binding_count": 0,
                "unexplained_loss_count": 0,
                "blocker_count": 0,
            },
            "blocker_fingerprints": [],
        }
        snapshot["snapshot_fingerprint"] = extension._payload_fingerprint(
            snapshot,
            "snapshot_fingerprint",
        )
        self.snapshot = snapshot
        self.snapshot_sha256 = self._write(self.snapshot_path, snapshot)

    def _write_development_artifacts(self) -> None:
        cases: list[dict[str, object]] = []
        for case_index in range(100):
            required = self.development_observation_ids[case_index * 2 : case_index * 2 + 2]
            case: dict[str, object] = {
                "case_id": f"development-case-{case_index:03d}",
                "query_text": f"development query {case_index:03d}",
                "required_source_observation_ids": required,
                "forbidden_source_observation_ids": [],
            }
            case["private_fingerprint"] = sha256_json(case)
            cases.append(case)
        manifest: dict[str, object] = {
            "artifact_id": extension.DEVELOPMENT_MANIFEST_ARTIFACT_ID,
            "schema_version": 1,
            "classification": "development_not_holdout",
            "case_count": 100,
            "quality_evaluation_status": "not_run",
            "source_bindings": {
                "source_snapshot_fingerprint": self.source_snapshot_fingerprint,
                "permission_fingerprint": self.permission_fingerprint,
                "tokenizer_profile_fingerprint": (
                    ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT
                ),
                "index_fingerprint": self.index_fingerprint,
            },
            "cases": cases,
        }
        manifest["manifest_fingerprint"] = extension._payload_fingerprint(
            manifest,
            "manifest_fingerprint",
        )
        self.development_manifest_sha256 = self._write(
            self.development_manifest_path,
            manifest,
        )
        safe: dict[str, object] = {
            "artifact_id": extension.DEVELOPMENT_SAFE_REPORT_ARTIFACT_ID,
            "schema_version": 1,
            "status": "passed",
            "quality_evaluation_status": "not_run",
            "fingerprints": {
                "manifest_sha256": self.development_manifest_sha256,
            },
        }
        safe["report_fingerprint"] = extension._payload_fingerprint(
            safe,
            "report_fingerprint",
        )
        self.development_safe_sha256 = self._write(
            self.development_safe_path,
            safe,
        )

    def _write_base_artifacts(self) -> None:
        strata: list[tuple[str, int, int]] = [
            ("graph_required", 7, 3),
            ("graph_required", 23, 2),
            ("single_document_direct_lookup", 4, 1),
            ("exact_set", 1, 1),
            ("exact_count", 1, 1),
            ("exact_aggregation", 1, 1),
            ("no_answer_near_miss_negative", 2, 1),
            ("permission_denied", 2, 1),
        ]
        cases: list[dict[str, object]] = []
        cursor = 0
        for stratum, count, evidence_count in strata:
            for _ in range(count):
                authoring = self.base_observation_ids[cursor : cursor + evidence_count]
                cursor += evidence_count
                result_kind = {
                    "graph_required": "owner_match",
                    "single_document_direct_lookup": "source_evidence",
                    "no_answer_near_miss_negative": "no_answer",
                    "permission_denied": "permission_denied",
                }.get(stratum, stratum)
                required = (
                    authoring
                    if stratum
                    not in {
                        "no_answer_near_miss_negative",
                        "permission_denied",
                    }
                    else []
                )
                forbidden = authoring if not required else []
                case: dict[str, object] = {
                    "case_id": f"base-case-{len(cases):03d}",
                    "stratum_id": stratum,
                    "result_kind": result_kind,
                    "query_text": f"base query {len(cases):03d}",
                    "required_source_observation_ids": required,
                    "forbidden_source_observation_ids": forbidden,
                    "authoring_source_observation_ids": authoring,
                    "answer_oracle": {"private_fixture": f"not-read-{len(cases):03d}"},
                }
                case["private_fingerprint"] = sha256_json(
                    {
                        "case_id": case["case_id"],
                        "query_text": case["query_text"],
                        "authoring": authoring,
                    }
                )
                cases.append(case)
        self.assert_fixture(cursor == len(self.base_observation_ids))
        source_bindings = {
            "source_snapshot_fingerprint": self.source_snapshot_fingerprint,
            "source_inventory_fingerprint": self.source_inventory_fingerprint,
            "source_provenance_fingerprint": (self.source_provenance_fingerprint),
            "permission_fingerprint": self.permission_fingerprint,
            "index_fingerprint": self.index_fingerprint,
            "tokenizer_profile_fingerprint": (ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT),
        }
        manifest: dict[str, object] = {
            "artifact_id": extension.BASE_HOLDOUT_ARTIFACT_ID,
            "schema_version": 2,
            "classification": "independent_mail_holdout",
            "execution_status": "not_run",
            "quality_result_status": "not_read",
            "case_count": 41,
            "case_strata_counts": {
                "exact_aggregation": 1,
                "exact_count": 1,
                "exact_set": 1,
                "graph_required": 30,
                "no_answer_near_miss_negative": 2,
                "permission_denied": 2,
                "single_document_direct_lookup": 4,
            },
            "source_oracle_bindings": source_bindings,
            "cases": cases,
        }
        manifest["manifest_fingerprint"] = extension._payload_fingerprint(
            manifest,
            "manifest_fingerprint",
        )
        self.base_manifest_sha256 = self._write(
            self.base_manifest_path,
            manifest,
        )
        safe: dict[str, object] = {
            "artifact_id": extension.BASE_HOLDOUT_SAFE_ARTIFACT_ID,
            "schema_version": 2,
            "status": "passed",
            "execution_status": "not_run",
            "quality_result_status": "not_read",
            "counts": {"case_count": 41, "blocker_count": 0},
            "strata_counts": dict(extension.BASE_HOLDOUT_STRATA_COUNTS),
            "hashes": {"manifest_sha256": self.base_manifest_sha256},
        }
        safe["report_fingerprint"] = extension._payload_fingerprint(
            safe,
            "report_fingerprint",
        )
        self.base_safe_sha256 = self._write(self.base_safe_path, safe)

    @staticmethod
    def assert_fixture(condition: bool) -> None:
        if not condition:
            raise AssertionError("invalid synthetic fixture")

    @staticmethod
    def _write(path: Path, value: object) -> str:
        payload = _canonical_bytes(value)
        path.write_bytes(payload)
        return _sha256_bytes(payload)

    def build(
        self,
        output_root: Path,
        *,
        bundle_path: Path | None = None,
        bundle_sha256: str | None = None,
        snapshot_path: Path | None = None,
        snapshot_sha256: str | None = None,
        base_manifest_path: Path | None = None,
        base_manifest_sha256: str | None = None,
        base_safe_path: Path | None = None,
        base_safe_sha256: str | None = None,
        write_staged_file: object | None = None,
    ) -> extension.HoldoutExtensionArtifacts:
        kwargs: dict[str, object] = {}
        if write_staged_file is not None:
            kwargs["_write_staged_file"] = write_staged_file
        return extension.author_independent_mail_holdout_extension(
            bundle_artifact_path=bundle_path or self.bundle_path,
            expected_bundle_artifact_sha256=bundle_sha256 or self.bundle_sha256,
            retrieval_snapshot_path=snapshot_path or self.snapshot_path,
            expected_retrieval_snapshot_sha256=(snapshot_sha256 or self.snapshot_sha256),
            development_manifest_path=self.development_manifest_path,
            expected_development_manifest_sha256=(self.development_manifest_sha256),
            development_safe_report_path=self.development_safe_path,
            expected_development_safe_report_sha256=(self.development_safe_sha256),
            base_holdout_manifest_path=base_manifest_path or self.base_manifest_path,
            expected_base_holdout_manifest_sha256=(
                base_manifest_sha256 or self.base_manifest_sha256
            ),
            base_holdout_safe_report_path=base_safe_path or self.base_safe_path,
            expected_base_holdout_safe_report_sha256=(base_safe_sha256 or self.base_safe_sha256),
            output_root=output_root,
            expected_message_count=self.expected_message_count,
            **kwargs,
        )


class Issue56SourceIndependentMailHoldoutExtensionE2ETest(unittest.TestCase):
    def test_actual_sealed_source_capacity_dry_run_matches_frozen_selection_proof(
        self,
    ) -> None:
        paths = {
            "bundle": Path(
                ".test-tmp/issue56-native-retrieval-ready-real/retrieval/"
                "mail-evidence-bundle.private.json"
            ),
            "snapshot": Path(
                ".test-tmp/issue56-native-retrieval-ready-real/retrieval/"
                "retrieval-ready-snapshot.private.json"
            ),
            "development_manifest": Path(
                ".test-tmp/issue56-source-development-uat-v1/" "development-manifest.private.json"
            ),
            "development_safe": Path(
                ".test-tmp/issue56-source-development-uat-v1/" "development-manifest.safe.json"
            ),
            "base_manifest": Path(
                ".test-tmp/issue56-source-independent-mail-holdout-v2/"
                "holdout-manifest.private.json"
            ),
            "base_safe": Path(
                ".test-tmp/issue56-source-independent-mail-holdout-v2/"
                "holdout-preflight.safe.json"
            ),
        }
        try:
            if not all(path.is_file() for path in paths.values()):
                self.skipTest("sealed real source-author artifacts unavailable")
            sealed = {
                role: extension._read_sealed_json(
                    path,
                    _sha256_bytes(path.read_bytes()),
                    maximum_bytes=(
                        extension._MAX_SOURCE_BYTES
                        if role in {"bundle", "snapshot"}
                        else extension._MAX_SAFE_BYTES
                        if role in {"development_safe", "base_safe"}
                        else extension._MAX_MANIFEST_BYTES
                    ),
                    reason_prefix=role,
                )
                for role, path in paths.items()
            }
        except PermissionError:
            self.skipTest("sealed real source-author artifacts unreadable")

        bundle_bytes, bundle_artifact = sealed["bundle"]
        snapshot_bytes, retrieval_snapshot = sealed["snapshot"]
        development_bytes, development_manifest = sealed["development_manifest"]
        development_safe_bytes, development_safe = sealed["development_safe"]
        base_bytes, base_manifest = sealed["base_manifest"]
        base_safe_bytes, base_safe = sealed["base_safe"]
        self.assertTrue(bundle_bytes)
        self.assertTrue(snapshot_bytes)

        bundle_payload = extension._validated_bundle_artifact(bundle_artifact)
        source_bindings = extension._validate_source_snapshot_and_bindings(
            bundle_artifact=bundle_artifact,
            bundle_payload=bundle_payload,
            retrieval_snapshot=retrieval_snapshot,
            expected_message_count=2793,
        )
        profile = extension.load_issue56_target_mail_tokenizer_profile()
        development_registry = extension._validate_development_exclusion(
            manifest=development_manifest,
            manifest_sha256=_sha256_bytes(development_bytes),
            safe_report=development_safe,
            safe_report_sha256=_sha256_bytes(development_safe_bytes),
            source_bindings=source_bindings,
        )
        base_registry = extension._validate_base_holdout_exclusion(
            manifest=base_manifest,
            manifest_sha256=_sha256_bytes(base_bytes),
            safe_report=base_safe,
            safe_report_sha256=_sha256_bytes(base_safe_bytes),
            source_bindings=source_bindings,
        )
        evidence_records = extension._validated_body_evidence_records(
            bundle_payload=bundle_payload,
            retrieval_snapshot=retrieval_snapshot,
            profile=profile,
        )
        source_records, body_to_message, body_to_thread = extension._build_source_records(
            bundle_payload=bundle_payload,
            evidence_records=evidence_records,
        )
        observation_to_message, observation_to_thread = (
            extension._build_exclusion_observation_lineage(
                bundle_payload=bundle_payload,
                retrieval_snapshot=retrieval_snapshot,
                evidence_records=evidence_records,
            )
        )
        self.assertTrue(
            all(
                observation_to_message[observation_id] == message_id
                and observation_to_thread[observation_id] == body_to_thread[observation_id]
                for observation_id, message_id in body_to_message.items()
            )
        )
        development_registry = extension._bind_registry_lineage(
            development_registry,
            observation_to_message=observation_to_message,
            observation_to_thread=observation_to_thread,
            reason_prefix="development",
        )
        base_registry = extension._bind_registry_lineage(
            base_registry,
            observation_to_message=observation_to_message,
            observation_to_thread=observation_to_thread,
            reason_prefix="base_holdout",
        )
        partition = extension._partition_records(
            records=source_records,
            observation_to_message=observation_to_message,
            observation_to_thread=observation_to_thread,
            development_registry=development_registry,
            base_registry=base_registry,
        )
        candidates = extension._build_candidates(
            partition.eligible_records,
            profile=profile,
            owner_user_id=str(bundle_payload["mail_import_session"]["owner_user_id"]),
            workspace_id=str(bundle_payload["mail_import_session"]["workspace_id"]),
        )
        selected, capacity = extension._select_candidates(
            candidates,
            base_registry=base_registry,
        )
        cases = extension._build_private_cases(selected, partition=partition)
        disjointness = extension._validate_extension_disjointness(
            cases=cases,
            selected=selected,
            partition=partition,
            development_registry=development_registry,
            base_registry=base_registry,
        )
        selection_proof = extension._selection_proof(
            candidates=candidates,
            selected=selected,
            capacity=capacity,
        )
        capacity_binding = extension._capacity_audit_binding(
            source_bindings=source_bindings,
            partition=partition,
            selection_proof=selection_proof,
        )

        self.assertEqual(len(cases), 59)
        self.assertEqual(
            Counter(candidate.stratum for candidate in selected),
            Counter(extension.TARGET_STRATA_COUNTS),
        )
        self.assertEqual(
            selection_proof["selected_counts"],
            dict(sorted(extension.TARGET_STRATA_COUNTS.items())),
        )
        self.assertEqual(
            source_bindings["source_snapshot_fingerprint"],
            extension.FROZEN_ACTUAL_SOURCE_SNAPSHOT_FINGERPRINT,
        )
        self.assertEqual(
            partition.partition_fingerprint,
            extension.FROZEN_ACTUAL_PARTITION_FINGERPRINT,
        )
        self.assertEqual(
            selection_proof["candidate_inventory_fingerprint"],
            extension.FROZEN_ACTUAL_CANDIDATE_INVENTORY_FINGERPRINT,
        )
        self.assertEqual(
            selection_proof["selected_candidate_fingerprint"],
            extension.FROZEN_ACTUAL_SELECTED_CANDIDATE_FINGERPRINT,
        )
        self.assertEqual(
            selection_proof["selection_proof_fingerprint"],
            extension.FROZEN_ACTUAL_SELECTION_PROOF_FINGERPRINT,
        )
        self.assertEqual(
            capacity_binding["capacity_audit_policy_fingerprint"],
            extension.FROZEN_ALTERNATIVE_STRATA_POLICY_FINGERPRINT,
        )
        for key, value in disjointness.items():
            if key.endswith("_overlap_count") or key.endswith("_reuse_count"):
                self.assertEqual(value, 0, key)

    def test_actual_style_mixed_base_lineage_is_fully_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            artifacts = fixture.build(root / "mixed-base")

            bundle_artifact = json.loads(fixture.bundle_path.read_bytes())
            snapshot = json.loads(fixture.snapshot_path.read_bytes())
            bundle_payload = extension._validated_bundle_artifact(bundle_artifact)
            profile = extension.load_issue56_target_mail_tokenizer_profile()
            evidence_records = extension._validated_body_evidence_records(
                bundle_payload=bundle_payload,
                retrieval_snapshot=snapshot,
                profile=profile,
            )
            observation_to_message, observation_to_thread = (
                extension._build_exclusion_observation_lineage(
                    bundle_payload=bundle_payload,
                    retrieval_snapshot=snapshot,
                    evidence_records=evidence_records,
                )
            )
            base_manifest = json.loads(fixture.base_manifest_path.read_bytes())
            base_safe = json.loads(fixture.base_safe_path.read_bytes())
            source_bindings = extension._validate_source_snapshot_and_bindings(
                bundle_artifact=bundle_artifact,
                bundle_payload=bundle_payload,
                retrieval_snapshot=snapshot,
                expected_message_count=fixture.expected_message_count,
            )
            registry = extension._validate_base_holdout_exclusion(
                manifest=base_manifest,
                manifest_sha256=fixture.base_manifest_sha256,
                safe_report=base_safe,
                safe_report_sha256=fixture.base_safe_sha256,
                source_bindings=source_bindings,
            )
            registry = extension._bind_registry_lineage(
                registry,
                observation_to_message=observation_to_message,
                observation_to_thread=observation_to_thread,
                reason_prefix="base_holdout",
            )

            base_type_counts = {
                observation_type: sum(
                    fixture._observation(observation_id).observation_type == observation_type
                    for observation_id in fixture.base_observation_ids
                )
                for observation_type in ("email_body_segment", "email_header")
            }
            self.assertEqual(
                base_type_counts,
                {
                    "email_body_segment": 61,
                    "email_header": 17,
                },
            )
            self.assertEqual(len(registry.observation_ids), 78)
            self.assertEqual(len(registry.message_ids), 77)
            self.assertEqual(len(registry.thread_ids), 75)
            base_lineages = [
                fixture.lineage_by_observation_id[observation_id]
                for observation_id in fixture.base_observation_ids
            ]
            source_message_to_records: dict[str, set[tuple[str, str]]] = {}
            for lineage in base_lineages:
                source_message_to_records.setdefault(lineage["message_id"], set()).add(
                    (
                        lineage["message_occurrence_id"],
                        lineage["email_message_id"],
                    )
                )
            duplicate_source_message_records = [
                records for records in source_message_to_records.values() if len(records) > 1
            ]
            self.assertEqual(len(duplicate_source_message_records), 1)
            self.assertEqual(len(duplicate_source_message_records[0]), 2)
            self.assertEqual(
                registry.observation_ids,
                frozenset(fixture.base_observation_ids),
            )
            self.assertEqual(registry.message_ids, fixture.base_message_ids)
            self.assertEqual(registry.thread_ids, fixture.base_thread_ids)

            selected_observation_ids = {
                observation_id
                for case in artifacts.manifest["cases"]
                for observation_id in case["authoring_source_observation_ids"]
            }
            selected_message_ids = {
                observation_to_message[observation_id]
                for observation_id in selected_observation_ids
            }
            selected_thread_ids = {
                observation_to_thread[observation_id] for observation_id in selected_observation_ids
            }
            development_message_ids = {
                observation_to_message[observation_id]
                for observation_id in fixture.development_observation_ids
            }
            development_thread_ids = {
                observation_to_thread[observation_id]
                for observation_id in fixture.development_observation_ids
            }
            self.assertFalse(
                selected_observation_ids
                & (set(fixture.development_observation_ids) | set(fixture.base_observation_ids))
            )
            self.assertFalse(
                selected_message_ids & (development_message_ids | fixture.base_message_ids)
            )
            self.assertFalse(
                selected_thread_ids & (development_thread_ids | fixture.base_thread_ids)
            )
            for key, value in artifacts.manifest["disjointness_proof"].items():
                if key.endswith("_overlap_count") or key.endswith("_reuse_count"):
                    self.assertEqual(value, 0, key)

    def test_duplicate_source_message_occurrence_record_conflict_fails_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            first_lineage = fixture.lineage_by_observation_id[fixture.base_observation_ids[0]]
            second_lineage = fixture.lineage_by_observation_id[fixture.base_observation_ids[1]]
            self.assertEqual(
                first_lineage["message_id"],
                second_lineage["message_id"],
            )
            self.assertNotEqual(
                first_lineage["message_occurrence_id"],
                second_lineage["message_occurrence_id"],
            )
            self.assertNotEqual(
                first_lineage["email_message_id"],
                second_lineage["email_message_id"],
            )

            bundle_artifact = json.loads(fixture.bundle_path.read_bytes())
            occurrence = next(
                row
                for row in bundle_artifact["bundle"]["message_occurrences"]
                if row["message_occurrence_id"] == second_lineage["message_occurrence_id"]
            )
            occurrence["thread_id"] = "conflicting-thread"
            bundle_artifact["bundle_fingerprint"] = sha256_json(bundle_artifact["bundle"])
            bundle_artifact["artifact_fingerprint"] = extension._payload_fingerprint(
                bundle_artifact,
                "artifact_fingerprint",
            )
            bundle_path = root / "conflict.bundle.json"
            bundle_sha256 = fixture._write(bundle_path, bundle_artifact)

            snapshot = json.loads(fixture.snapshot_path.read_bytes())
            snapshot["mail_evidence_bundle_fingerprint"] = bundle_artifact["bundle_fingerprint"]
            snapshot["snapshot_fingerprint"] = extension._payload_fingerprint(
                snapshot,
                "snapshot_fingerprint",
            )
            snapshot_path = root / "conflict.snapshot.json"
            snapshot_sha256 = fixture._write(snapshot_path, snapshot)

            output_root = root / "conflict.output"
            with self.assertRaisesRegex(
                extension.HoldoutExtensionError,
                "^message_occurrence_lineage_invalid$",
            ):
                fixture.build(
                    output_root,
                    bundle_path=bundle_path,
                    bundle_sha256=bundle_sha256,
                    snapshot_path=snapshot_path,
                    snapshot_sha256=snapshot_sha256,
                )
            self.assertFalse(output_root.exists())

    def test_builder_output_satisfies_runner_projection_and_execution_lineage_contract(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            artifacts = fixture.build(root / "runner-contract")
            bundle_artifact = json.loads(fixture.bundle_path.read_bytes())
            retrieval_snapshot = json.loads(fixture.snapshot_path.read_bytes())
            development_manifest = json.loads(fixture.development_manifest_path.read_bytes())
            base_safe = json.loads(fixture.base_safe_path.read_bytes())

            holdout_uat._validate_extension_private_manifest_boundary(
                artifacts.manifest,
                holdout_policy=holdout_uat._EXTENSION_HOLDOUT_POLICY,
            )
            holdout_uat._validate_extension_manifest_projection_cross_binding(
                manifest=artifacts.manifest,
                manifest_sha256=artifacts.manifest_sha256,
                projection=artifacts.projection,
                holdout_policy=holdout_uat._EXTENSION_HOLDOUT_POLICY,
            )
            projection_lineage = holdout_uat._validate_extension_holdout_projection(
                holdout_policy=holdout_uat._EXTENSION_HOLDOUT_POLICY,
                projection=artifacts.projection,
                manifest_sha256=artifacts.manifest_sha256,
                safe_report=base_safe,
                safe_report_sha256=fixture.base_safe_sha256,
                retrieval_bundle_sha256=fixture.bundle_sha256,
                retrieval_snapshot_sha256=fixture.snapshot_sha256,
                bundle_artifact=bundle_artifact,
                bundle=fixture.bundle,
                retrieval_snapshot=retrieval_snapshot,
                source_report_sha256=sha256_json("unused-source-report"),
                development_manifest=development_manifest,
                development_manifest_sha256=fixture.development_manifest_sha256,
                development_report_sha256=fixture.development_safe_sha256,
                development_observation_ids=frozenset(fixture.development_observation_ids),
                development_registry_fingerprint=artifacts.manifest[
                    "development_exclusion_binding"
                ]["registry_fingerprint"],
            )
            self.assertEqual(projection_lineage["case_count"], 59)
            self.assertEqual(
                projection_lineage["strata_counts"],
                extension.TARGET_STRATA_COUNTS,
            )

            observations_by_id = {
                observation.observation_id: observation for observation in fixture.observations
            }
            execution_context = holdout_uat._HoldoutExecutionContext(
                observations_by_bundle_id={
                    fixture.bundle.mail_evidence_bundle_id: tuple(fixture.observations)
                },
                observations_by_id=observations_by_id,
                observation_hash_by_id={
                    observation_id: sha256_json(observation.to_dict())
                    for observation_id, observation in observations_by_id.items()
                },
                sessions={},
                effective_graph_views={},
                lineage_crosswalks={},
                graph_builds={},
                graph_ontology_binding={},
            )
            holdout_uat._validate_extension_execution_manifest_lineage(
                manifest=artifacts.manifest,
                projection=artifacts.projection,
                preflight_report={
                    "hashes": {
                        "retrieval_bundle_sha256": fixture.bundle_sha256,
                        "retrieval_snapshot_sha256": fixture.snapshot_sha256,
                        "source_snapshot_fingerprint": (fixture.source_snapshot_fingerprint),
                        "source_inventory_fingerprint": (fixture.source_inventory_fingerprint),
                        "source_provenance_fingerprint": (fixture.source_provenance_fingerprint),
                        "lexical_profile_fingerprint": (
                            ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT
                        ),
                        "index_fingerprint": fixture.index_fingerprint,
                        "retrieval_snapshot_fingerprint": retrieval_snapshot[
                            "snapshot_fingerprint"
                        ],
                        "development_manifest_sha256": (fixture.development_manifest_sha256),
                        "development_report_sha256": (fixture.development_safe_sha256),
                        "holdout_report_sha256": fixture.base_safe_sha256,
                    }
                },
                execution_context=execution_context,
                bundle=fixture.bundle,
                holdout_policy=holdout_uat._EXTENSION_HOLDOUT_POLICY,
            )

    def test_header_lineage_missing_mismatch_and_message_id_substitution_fail_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            header_observation_id = fixture.base_observation_ids[0]
            header_lineage = fixture.lineage_by_observation_id[header_observation_id]
            mutations = (
                (
                    "missing-occurrence",
                    "missing-occurrence",
                    "email_header_message_occurrence_lineage_missing",
                ),
                (
                    "email-message-as-occurrence",
                    header_lineage["email_message_id"],
                    "email_header_message_occurrence_lineage_missing",
                ),
            )
            for label, replacement_occurrence, reason_code in mutations:
                with self.subTest(label=label):
                    snapshot = json.loads(fixture.snapshot_path.read_bytes())
                    row = next(
                        row
                        for row in snapshot["parsed_mail_observations"]
                        if row["observation_id"] == header_observation_id
                    )
                    row["location"]["message_occurrence_id"] = replacement_occurrence
                    row["payload"]["message_occurrence_id"] = replacement_occurrence
                    snapshot["snapshot_fingerprint"] = extension._payload_fingerprint(
                        snapshot,
                        "snapshot_fingerprint",
                    )
                    snapshot_path = root / f"{label}.snapshot.json"
                    snapshot_sha256 = fixture._write(snapshot_path, snapshot)
                    output_root = root / f"{label}.output"
                    with self.assertRaisesRegex(
                        extension.HoldoutExtensionError,
                        reason_code,
                    ):
                        fixture.build(
                            output_root,
                            snapshot_path=snapshot_path,
                            snapshot_sha256=snapshot_sha256,
                        )
                    self.assertFalse(output_root.exists())

            mismatch = json.loads(fixture.snapshot_path.read_bytes())
            mismatch_row = next(
                row
                for row in mismatch["parsed_mail_observations"]
                if row["observation_id"] == header_observation_id
            )
            mismatch_row["location"]["thread_id"] = "wrong-thread"
            mismatch_row["payload"]["thread_id"] = "wrong-thread"
            mismatch["snapshot_fingerprint"] = extension._payload_fingerprint(
                mismatch,
                "snapshot_fingerprint",
            )
            mismatch_path = root / "mismatch.snapshot.json"
            mismatch_sha256 = fixture._write(mismatch_path, mismatch)
            with self.assertRaisesRegex(
                extension.HoldoutExtensionError,
                "email_header_source_native_lineage_mismatch",
            ):
                fixture.build(
                    root / "mismatch.output",
                    snapshot_path=mismatch_path,
                    snapshot_sha256=mismatch_sha256,
                )
            self.assertFalse((root / "mismatch.output").exists())

            unsupported = json.loads(fixture.snapshot_path.read_bytes())
            unsupported_row = next(
                row
                for row in unsupported["parsed_mail_observations"]
                if row["observation_id"] == header_observation_id
            )
            unsupported_row["observation_type"] = "email_subject_projection"
            unsupported["counts"]["parsed_header_observation_count"] = 16
            unsupported["snapshot_fingerprint"] = extension._payload_fingerprint(
                unsupported,
                "snapshot_fingerprint",
            )
            unsupported_path = root / "unsupported.snapshot.json"
            unsupported_sha256 = fixture._write(unsupported_path, unsupported)
            with self.assertRaisesRegex(
                extension.HoldoutExtensionError,
                "base_holdout_observation_lineage_missing",
            ):
                fixture.build(
                    root / "unsupported.output",
                    snapshot_path=unsupported_path,
                    snapshot_sha256=unsupported_sha256,
                )
            self.assertFalse((root / "unsupported.output").exists())

    def test_authors_deterministic_59_case_additive_extension(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            first = fixture.build(root / "first")
            second = fixture.build(root / "second")

            self.assertEqual(first.manifest_path.read_bytes(), second.manifest_path.read_bytes())
            self.assertEqual(
                first.projection_path.read_bytes(),
                second.projection_path.read_bytes(),
            )
            self.assertEqual(first.manifest["extension_case_count"], 59)
            self.assertEqual(first.manifest["combined_acceptance_case_count"], 100)
            self.assertEqual(
                first.manifest["case_strata_counts"],
                extension.TARGET_STRATA_COUNTS,
            )
            self.assertEqual(sum(extension.TARGET_STRATA_COUNTS.values()), 59)
            self.assertEqual(
                first.manifest["selection_policy"]["capacity_shortfall_policy"],
                "fail_closed_no_redistribution",
            )
            self.assertEqual(
                first.manifest["capacity_audit_binding"]["capacity_audit_policy_fingerprint"],
                extension.FROZEN_ALTERNATIVE_STRATA_POLICY_FINGERPRINT,
            )
            self.assertTrue(first.manifest["final_acceptance_eligible"])
            self.assertFalse(first.manifest["diagnostic_only"])
            self.assertEqual(first.manifest["execution_status"], "not_run")
            self.assertEqual(
                first.projection["status"],
                "sealed_oracle_free",
            )

            cases = first.manifest["cases"]
            self.assertEqual(len(cases), 59)
            authoring_ids = [
                value for case in cases for value in case["authoring_source_observation_ids"]
            ]
            message_hashes = [
                value
                for case in cases
                for value in case["source_evidence_binding"]["authoring_message_hashes"]
            ]
            thread_hashes = [
                value
                for case in cases
                for value in case["source_evidence_binding"]["authoring_thread_hashes"]
            ]
            self.assertEqual(len(authoring_ids), len(set(authoring_ids)))
            self.assertEqual(len(message_hashes), len(set(message_hashes)))
            self.assertEqual(len(thread_hashes), len(set(thread_hashes)))
            self.assertEqual(
                len({case["query_hash"] for case in cases}),
                len(cases),
            )
            self.assertEqual(
                len({case["private_fingerprint"] for case in cases}),
                len(cases),
            )
            proof = first.manifest["disjointness_proof"]
            for key, value in proof.items():
                if key.endswith("_overlap_count") or key.endswith("_reuse_count"):
                    self.assertEqual(value, 0, key)

            public_text = first.projection_path.read_text(encoding="utf-8")
            for private_name in (
                "query_text",
                "requester_user_id",
                "required_source_observation_ids",
                "forbidden_source_observation_ids",
                "authoring_source_observation_ids",
                "adjudication",
                "answer_oracle",
                "PO300",
                "graphconcept",
                "singleconcept",
            ):
                self.assertNotIn(private_name, public_text)
            self.assertEqual(
                first.manifest_sha256,
                _sha256_bytes(first.manifest_path.read_bytes()),
            )
            self.assertEqual(
                first.projection_sha256,
                _sha256_bytes(first.projection_path.read_bytes()),
            )

    def test_capacity_shortfall_fails_closed_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root, graph_pair_count=19)
            output = root / "shortfall"
            with self.assertRaisesRegex(
                extension.HoldoutExtensionError,
                "capacity_shortfall_graph_required",
            ):
                fixture.build(output)
            self.assertFalse(output.exists())

    def test_seal_and_cross_binding_tamper_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)

            fixture.base_safe_path.write_bytes(fixture.base_safe_path.read_bytes() + b" ")
            with self.assertRaisesRegex(
                extension.HoldoutExtensionError,
                "base_holdout_safe_report_seal_mismatch",
            ):
                fixture.build(root / "byte-tamper")
            self.assertFalse((root / "byte-tamper").exists())

            safe = json.loads(fixture.base_safe_path.read_bytes().rstrip())
            safe["hashes"]["manifest_sha256"] = sha256_json("wrong-manifest")
            safe["report_fingerprint"] = extension._payload_fingerprint(
                safe,
                "report_fingerprint",
            )
            drift_path = root / "base-safe-drift.json"
            drift_sha = fixture._write(drift_path, safe)
            with self.assertRaisesRegex(
                extension.HoldoutExtensionError,
                "base_holdout_exclusion_contract_invalid",
            ):
                fixture.build(
                    root / "binding-tamper",
                    base_safe_path=drift_path,
                    base_safe_sha256=drift_sha,
                )
            self.assertFalse((root / "binding-tamper").exists())

            safe_strata = json.loads(fixture.base_safe_path.read_bytes())
            safe_strata["strata_counts"]["graph_required"] = 29
            safe_strata["strata_counts"]["single_document_direct_lookup"] = 5
            safe_strata["report_fingerprint"] = extension._payload_fingerprint(
                safe_strata,
                "report_fingerprint",
            )
            strata_drift_path = root / "base-safe-strata-drift.json"
            strata_drift_sha = fixture._write(strata_drift_path, safe_strata)
            with self.assertRaisesRegex(
                extension.HoldoutExtensionError,
                "base_holdout_exclusion_contract_invalid",
            ):
                fixture.build(
                    root / "strata-tamper",
                    base_safe_path=strata_drift_path,
                    base_safe_sha256=strata_drift_sha,
                )
            self.assertFalse((root / "strata-tamper").exists())

            base_manifest = json.loads(fixture.base_manifest_path.read_bytes())
            base_manifest["source_oracle_bindings"]["permission_fingerprint"] = sha256_json(
                "wrong-permission"
            )
            base_manifest["manifest_fingerprint"] = extension._payload_fingerprint(
                base_manifest,
                "manifest_fingerprint",
            )
            base_manifest_drift_path = root / "base-manifest-permission-drift.json"
            base_manifest_drift_sha = fixture._write(
                base_manifest_drift_path,
                base_manifest,
            )
            base_safe = json.loads(fixture.base_safe_path.read_bytes())
            base_safe["hashes"]["manifest_sha256"] = base_manifest_drift_sha
            base_safe["report_fingerprint"] = extension._payload_fingerprint(
                base_safe,
                "report_fingerprint",
            )
            base_safe_drift_path = root / "base-safe-permission-drift.json"
            base_safe_drift_sha = fixture._write(base_safe_drift_path, base_safe)
            with self.assertRaisesRegex(
                extension.HoldoutExtensionError,
                "base_holdout_source_binding_mismatch",
            ):
                fixture.build(
                    root / "permission-tamper",
                    base_manifest_path=base_manifest_drift_path,
                    base_manifest_sha256=base_manifest_drift_sha,
                    base_safe_path=base_safe_drift_path,
                    base_safe_sha256=base_safe_drift_sha,
                )
            self.assertFalse((root / "permission-tamper").exists())

    def test_atomic_failure_and_no_overwrite_leave_no_partial_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            fixture = _Fixture(root)
            writes = 0

            def fail_second(path: Path, payload: bytes, mode: int) -> None:
                nonlocal writes
                writes += 1
                if writes == 1:
                    extension._write_file_exclusive(path, payload, mode)
                    return
                raise extension.HoldoutExtensionError("injected_write_failure")

            output = root / "atomic"
            with self.assertRaisesRegex(
                extension.HoldoutExtensionError,
                "injected_write_failure",
            ):
                fixture.build(output, write_staged_file=fail_second)
            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".atomic.staging-*")), [])

            completed = fixture.build(output)
            with self.assertRaisesRegex(
                extension.HoldoutExtensionError,
                "immutable_output_already_exists",
            ):
                fixture.build(output)
            self.assertEqual(
                completed.manifest_sha256,
                _sha256_bytes(completed.manifest_path.read_bytes()),
            )


if __name__ == "__main__":
    unittest.main()
