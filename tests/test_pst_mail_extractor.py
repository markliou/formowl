from __future__ import annotations

from pathlib import Path
import json
import subprocess
import unittest

import _paths  # noqa: F401
from formowl_contract import (
    PermissionScope,
    SourceRef,
    assert_no_public_raw_references,
    sha256_json,
)
from formowl_ingestion.assets import register_asset_from_local_file
from formowl_ingestion.extraction import run_extractor
from formowl_ingestion.extractors.mail.pst import (
    PstMailArchiveExtractor,
    _ParserCommandResult,
)
from formowl_ingestion.storage import (
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    ObservationStore,
    StorageBackendRegistry,
)
from formowl_mail import MailEvidenceQueryGateway, build_mail_evidence_bundle


NOW = "2026-07-06T10:00:00+00:00"


class PstMailArchiveExtractorTests(unittest.TestCase):
    def test_pst_adapter_exports_mail_observations_from_runner_output(self) -> None:
        context = _PstExtractionContext.create("pst-extractor-basic")
        adapter = context.adapter_with_runner(_runner_with_messages([_rfc822_message()]))

        result = run_extractor(
            asset=context.asset,
            object_store=context.object_store,
            extractor_run_store=context.run_store,
            observation_store=context.observation_store,
            adapter=adapter,
            config={"max_messages": 25},
            started_at=NOW,
            completed_at=NOW,
        )

        self.assertEqual(result.extractor_run.status, "succeeded")
        self.assertEqual(result.extractor_run.extractor_name, "pst_mail_archive_extractor")
        self.assertEqual(result.extractor_run.errors, [])
        self.assertTrue(
            {
                "email_message",
                "email_header",
                "email_body_segment",
                "email_thread",
                "mail_folder_occurrence",
                "email_attachment_occurrence",
            }.issubset({observation.observation_type for observation in result.observations})
        )
        for observation in result.observations:
            self.assertEqual(observation.asset_id, context.asset.asset_id)
            self.assertEqual(observation.extractor_run_id, result.extractor_run.extractor_run_id)
            self.assertEqual(observation.permission_scope, context.asset.permission_scope)
            self.assertEqual(observation.modality, "mail")
            self.assertIn("archive_id", observation.location)
            self.assertIn("mailbox_id", observation.location)
            assert_no_public_raw_references(observation.to_dict(), "pst_observation")
        rendered = json.dumps(
            [observation.to_dict() for observation in result.observations],
            sort_keys=True,
        )
        self.assertNotIn(str(context.temp_dir), rendered)
        self.assertNotIn("formowl-pst-export", rendered)
        self.assertNotIn("payload.bin", rendered)
        self.assertNotIn("readpst", rendered)

    def test_duplicate_message_preserves_occurrence_lineage(self) -> None:
        context = _PstExtractionContext.create("pst-extractor-duplicates")
        adapter = context.adapter_with_runner(
            _runner_with_messages([_rfc822_message(), _rfc822_message()])
        )

        result = run_extractor(
            asset=context.asset,
            object_store=context.object_store,
            extractor_run_store=context.run_store,
            observation_store=context.observation_store,
            adapter=adapter,
            config={"max_messages": 25},
            started_at=NOW,
            completed_at=NOW,
        )

        message_payloads = [
            observation.payload
            for observation in result.observations
            if observation.observation_type == "email_message"
        ]
        self.assertEqual(len(message_payloads), 2)
        self.assertEqual(
            len({payload["message_fingerprint"] for payload in message_payloads}),
            1,
        )
        self.assertEqual(
            len({payload["message_occurrence_id"] for payload in message_payloads}),
            2,
        )
        bundle = build_mail_evidence_bundle(
            result.observations,
            workspace_id="workspace_formowl",
            owner_user_id="user_owner",
            source_asset_id=context.asset.asset_id,
            archive_sha256=context.asset.content_hash,
            upload_session_id="upload_real_pst_unit",
            parser_name="pst_mail_archive_extractor",
            parser_version="0.1.0",
            created_at=NOW,
            started_at=NOW,
            completed_at=NOW,
            parse_warnings=result.extractor_run.warnings,
        )
        self.assertEqual(len(bundle.messages), 1)
        self.assertEqual(len(bundle.message_occurrences), 2)

    def test_message_identity_is_stable_when_export_order_changes(self) -> None:
        first_message = _rfc822_message(message_id="", body="Stable fallback message alpha")
        second_message = _rfc822_message(message_id="", body="Stable fallback message beta")

        first = _extract_message_identities(
            "pst-extractor-stable-order-first",
            [first_message, second_message],
        )
        second = _extract_message_identities(
            "pst-extractor-stable-order-second",
            [second_message, first_message],
        )

        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)

    def test_readpst_command_contract_and_timeout_are_forwarded(self) -> None:
        context = _PstExtractionContext.create("pst-extractor-command-contract")
        runner = _CapturingRunner([_rfc822_message()])
        adapter = context.adapter_with_runner(runner)

        result = run_extractor(
            asset=context.asset,
            object_store=context.object_store,
            extractor_run_store=context.run_store,
            observation_store=context.observation_store,
            adapter=adapter,
            config={
                "max_messages": 25,
                "timeout_seconds": 123,
                "include_deleted_items": True,
            },
            started_at=NOW,
            completed_at=NOW,
        )

        self.assertEqual(result.extractor_run.status, "succeeded")
        self.assertEqual(runner.timeout_seconds, 123)
        self.assertIsNotNone(runner.command)
        assert runner.command is not None
        self.assertEqual(runner.command[0], "readpst")
        self.assertIn("-S", runner.command)
        self.assertIn("-D", runner.command)
        self.assertIn("-o", runner.command)
        output_dir = Path(runner.command[runner.command.index("-o") + 1])
        self.assertFalse(output_dir.exists())
        self.assertEqual(Path(runner.command[-1]).name, "payload.bin")

    def test_parallel_parser_workers_parse_exported_messages(self) -> None:
        context = _PstExtractionContext.create("pst-extractor-parser-workers")
        runner = _CapturingRunner(
            [
                _rfc822_message(
                    message_id=f"<unit-{index:03d}@example.test>",
                    body=f"Parallel parse item {index}",
                )
                for index in range(5)
            ]
        )
        adapter = context.adapter_with_runner(runner)

        result = run_extractor(
            asset=context.asset,
            object_store=context.object_store,
            extractor_run_store=context.run_store,
            observation_store=context.observation_store,
            adapter=adapter,
            config={"parser_workers": 2},
            started_at=NOW,
            completed_at=NOW,
        )

        self.assertEqual(result.extractor_run.status, "succeeded")
        email_messages = [
            observation
            for observation in result.observations
            if observation.observation_type == "email_message"
        ]
        self.assertEqual(len(email_messages), 5)

    def test_parser_failures_are_bounded(self) -> None:
        cases = [
            (
                "bad-signature",
                b"NOTPST",
                _runner_with_messages([_rfc822_message()]),
                ["pst_parser_input_signature_mismatch"],
            ),
            (
                "missing-parser",
                b"!BDN unit fixture",
                _runner_raises(FileNotFoundError()),
                ["pst_parser_unavailable"],
            ),
            (
                "timeout",
                b"!BDN unit fixture",
                _runner_raises(subprocess.TimeoutExpired(cmd="pst", timeout=1)),
                ["pst_parser_timeout"],
            ),
            (
                "nonzero",
                b"!BDN unit fixture",
                lambda command, timeout: _ParserCommandResult(1),
                ["pst_parser_failed"],
            ),
            (
                "no-messages",
                b"!BDN unit fixture",
                _runner_with_raw_files([b"not an email"]),
                ["pst_parser_no_messages"],
            ),
        ]

        for case_name, content, runner, expected_errors in cases:
            with self.subTest(case=case_name):
                context = _PstExtractionContext.create(
                    f"pst-extractor-{case_name}", content=content
                )
                adapter = context.adapter_with_runner(runner)
                result = run_extractor(
                    asset=context.asset,
                    object_store=context.object_store,
                    extractor_run_store=context.run_store,
                    observation_store=context.observation_store,
                    adapter=adapter,
                    started_at=NOW,
                    completed_at=NOW,
                )

                self.assertEqual(result.extractor_run.status, "failed")
                self.assertEqual(result.extractor_run.errors, expected_errors)
                self.assertEqual(result.observations, [])
                self.assertEqual(context.observation_store.list(), [])
                rendered = json.dumps(result.extractor_run.to_dict(), sort_keys=True)
                self.assertNotIn(str(context.temp_dir), rendered)
                self.assertNotIn("payload.bin", rendered)
                self.assertNotIn("readpst", rendered)
                scratch_root = context.temp_dir / "pst-scratch"
                if scratch_root.exists():
                    self.assertEqual(list(scratch_root.rglob("*")), [])

    def test_parser_config_validation_fails_before_runner_invocation(self) -> None:
        invalid_configs = [
            {"max_messages": 0},
            {"timeout_seconds": 0},
            {"max_message_file_bytes": -1},
            {"body_segment_max_chars": True},
            {"max_body_segments_per_message": 0},
            {"max_attachment_hash_bytes": 0},
            {"include_deleted_items": "yes"},
            {"parser_workers": 0},
            {"parser_workers": True},
        ]

        for config in invalid_configs:
            with self.subTest(config=config):
                context = _PstExtractionContext.create(
                    "pst-extractor-invalid-config-" + sha256_json(config)[-8:]
                )
                runner = _CountingRunner()
                with self.assertRaises(ValueError):
                    run_extractor(
                        asset=context.asset,
                        object_store=context.object_store,
                        extractor_run_store=context.run_store,
                        observation_store=context.observation_store,
                        adapter=context.adapter_with_runner(runner),
                        config=config,
                        started_at=NOW,
                        completed_at=NOW,
                    )
                self.assertEqual(runner.calls, 0)
                self.assertEqual(context.observation_store.list(), [])

    def test_preserves_private_body_and_redacts_only_public_query_output(self) -> None:
        context = _PstExtractionContext.create("pst-extractor-sanitizes")
        unsafe_body = "Review scratch path C:\\tmp\\archive.pst before approval."
        unsafe_attachment = "C:\\private\\attachment.pdf"
        adapter = context.adapter_with_runner(
            _runner_with_messages(
                [
                    _rfc822_message(
                        body=unsafe_body,
                        attachment_name=unsafe_attachment,
                    )
                ]
            )
        )

        result = run_extractor(
            asset=context.asset,
            object_store=context.object_store,
            extractor_run_store=context.run_store,
            observation_store=context.observation_store,
            adapter=adapter,
            config={"max_messages": 25},
            started_at=NOW,
            completed_at=NOW,
        )

        private_rendered = json.dumps(
            [observation.to_dict() for observation in result.observations],
            sort_keys=True,
        )
        self.assertIn(
            "pst_parser_body_segment_contains_publicly_unsafe_text",
            result.extractor_run.warnings,
        )
        private_body_segments = [
            observation.text
            for observation in result.observations
            if observation.observation_type == "email_body_segment"
        ]
        self.assertIn(unsafe_body, private_body_segments)
        self.assertIn("redacted_filename_", private_rendered)
        self.assertNotIn(unsafe_attachment, private_rendered)

        bundle = build_mail_evidence_bundle(
            result.observations,
            workspace_id="workspace_formowl",
            owner_user_id="user_owner",
            source_asset_id=context.asset.asset_id,
            archive_sha256=context.asset.content_hash,
            upload_session_id="upload_real_pst_unit",
            parser_name="pst_mail_archive_extractor",
            parser_version="0.1.0",
            created_at=NOW,
            started_at=NOW,
            completed_at=NOW,
            parse_warnings=result.extractor_run.warnings,
        )
        self.assertIn(unsafe_body, [segment.text for segment in bundle.body_segments])

        public_result = MailEvidenceQueryGateway([bundle]).query_mail_evidence(
            query_text="Review approval",
            requester_user_id="user_owner",
            workspace_id="workspace_formowl",
            session_id="session_unit",
            mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
            limit=5,
        )
        public_rendered = json.dumps(public_result.to_dict(), sort_keys=True)
        self.assertNotIn(unsafe_body, public_rendered)
        self.assertNotIn("C:\\tmp", public_rendered)
        self.assertIn("unsafe_mail_evidence_content_redacted", public_result.warnings)

    def test_body_segments_are_complete_and_attachment_text_is_searchable(self) -> None:
        context = _PstExtractionContext.create("pst-extractor-complete-segments")
        body = "A" * 9001
        adapter = context.adapter_with_runner(_runner_with_messages([_rfc822_message(body=body)]))

        result = run_extractor(
            asset=context.asset,
            object_store=context.object_store,
            extractor_run_store=context.run_store,
            observation_store=context.observation_store,
            adapter=adapter,
            config={"body_segment_max_chars": 4000},
            started_at=NOW,
            completed_at=NOW,
        )

        message = next(
            observation
            for observation in result.observations
            if observation.observation_type == "email_message"
        )
        segments = [
            observation
            for observation in result.observations
            if observation.observation_type == "email_body_segment"
        ]
        attachment_segments = [
            observation
            for observation in result.observations
            if observation.observation_type == "email_attachment_text_segment"
        ]
        self.assertEqual([len(segment.text or "") for segment in segments], [4000, 4000, 1001])
        self.assertEqual("".join(segment.text or "" for segment in segments), body)
        self.assertEqual(message.payload["source_body_char_count"], 9001)
        self.assertEqual(message.payload["stored_body_char_count"], 9001)
        self.assertEqual(message.payload["body_segment_count"], 3)
        self.assertEqual(message.payload["body_evidence_state"], "complete")
        self.assertEqual(len(attachment_segments), 1)
        self.assertIn("attachment body", attachment_segments[0].text or "")

        bundle = build_mail_evidence_bundle(
            result.observations,
            workspace_id="workspace_formowl",
            owner_user_id="user_owner",
            source_asset_id=context.asset.asset_id,
            archive_sha256=context.asset.content_hash,
            upload_session_id="upload_real_pst_unit",
            parser_name="pst_mail_archive_extractor",
            parser_version="0.1.0",
            created_at=NOW,
            started_at=NOW,
            completed_at=NOW,
            parse_warnings=result.extractor_run.warnings,
        )
        gateway = MailEvidenceQueryGateway([bundle])
        search = gateway.query_mail_evidence(
            query_text="attachment",
            requester_user_id="user_owner",
            workspace_id="workspace_formowl",
            session_id="session_unit",
            mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
            limit=5,
        )
        self.assertEqual(search.answerability_state, "evidence_found_complete")
        read = gateway.read_mail_evidence(
            requester_user_id="user_owner",
            workspace_id="workspace_formowl",
            session_id="session_unit",
            mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
            email_message_ids=[bundle.messages[0].email_message_id],
        )
        self.assertEqual(read.status, "ok")
        self.assertEqual(read.evidence_completeness, "complete")
        self.assertEqual(len(read.evidence_segments), 4)
        self.assertEqual(
            [
                segment["body_segment_index"]
                for segment in read.evidence_segments
                if segment["segment_source_type"] == "message_body"
            ],
            [1, 2, 3],
        )
        limited_read = gateway.read_mail_evidence(
            requester_user_id="user_owner",
            workspace_id="workspace_formowl",
            session_id="session_unit",
            mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
            email_message_ids=[bundle.messages[0].email_message_id],
            limit=2,
        )
        self.assertEqual(limited_read.status, "partial")
        self.assertEqual(limited_read.evidence_completeness, "incomplete")
        self.assertEqual(limited_read.answerability_state, "read_limit_reached")
        self.assertIn("mail_evidence_read_limit_reached", limited_read.warnings)


class _PstExtractionContext:
    def __init__(
        self,
        *,
        temp_dir: Path,
        object_store: FileObjectStore,
        run_store: ExtractorRunStore,
        observation_store: ObservationStore,
        asset,
    ) -> None:
        self.temp_dir = temp_dir
        self.object_store = object_store
        self.run_store = run_store
        self.observation_store = observation_store
        self.asset = asset

    def adapter_with_runner(self, runner) -> PstMailArchiveExtractor:
        return PstMailArchiveExtractor(
            runner=runner,
            scratch_parent=self.temp_dir / "pst-scratch",
        )

    @classmethod
    def create(
        cls,
        test_dir_name: str,
        *,
        content: bytes = b"!BDN unit fixture",
    ) -> "_PstExtractionContext":
        temp_dir = _paths.fresh_test_dir(test_dir_name)
        source_path = temp_dir / "incoming" / "unit.pst"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(content)
        registry = StorageBackendRegistry(temp_dir)
        backend = registry.register_local_backend(
            temp_dir / "object-root",
            workspace_scope="workspace_formowl",
            storage_backend_id="storage_pst_unit",
        )
        object_store = FileObjectStore(registry)
        asset_store = AssetStore(temp_dir)
        asset = register_asset_from_local_file(
            source_path,
            object_store=object_store,
            asset_store=asset_store,
            storage_backend_id=backend.storage_backend_id,
            workspace_id="workspace_formowl",
            owner_user_id="user_owner",
            permission_scope=PermissionScope.project("project_formowl"),
            source_ref=SourceRef(
                source_system="formowl_upload_session",
                source_type="mail_archive_upload",
                source_id="upload_real_pst_unit",
            ),
            mime_type="application/vnd.ms-outlook",
            created_at=NOW,
            registered_at=NOW,
        )
        return cls(
            temp_dir=temp_dir,
            object_store=object_store,
            run_store=ExtractorRunStore(temp_dir),
            observation_store=ObservationStore(temp_dir),
            asset=asset,
        )


class _CountingRunner:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, command, timeout):
        self.calls += 1
        return _ParserCommandResult(0)


class _CapturingRunner:
    def __init__(self, files: list[bytes]) -> None:
        self.files = files
        self.command: list[str] | None = None
        self.timeout_seconds: int | None = None

    def __call__(self, command, timeout):
        self.command = list(command)
        self.timeout_seconds = timeout
        output_dir = Path(command[command.index("-o") + 1])
        for index, content in enumerate(self.files, start=1):
            (output_dir / f"{index}.eml").write_bytes(content)
        return _ParserCommandResult(0)


def _runner_raises(exc: Exception):
    def runner(command, timeout):
        raise exc

    return runner


def _runner_with_messages(messages: list[bytes]):
    return _runner_with_raw_files(messages)


def _runner_with_raw_files(files: list[bytes]):
    def runner(command, timeout):
        output_dir = Path(command[command.index("-o") + 1])
        for index, content in enumerate(files, start=1):
            (output_dir / f"{index}.eml").write_bytes(content)
        return _ParserCommandResult(0)

    return runner


def _extract_message_identities(
    case_name: str, messages: list[bytes]
) -> dict[str, tuple[str, str]]:
    context = _PstExtractionContext.create(case_name)
    result = run_extractor(
        asset=context.asset,
        object_store=context.object_store,
        extractor_run_store=context.run_store,
        observation_store=context.observation_store,
        adapter=context.adapter_with_runner(_runner_with_messages(messages)),
        config={"max_messages": 25},
        started_at=NOW,
        completed_at=NOW,
    )
    return {
        str(observation.payload["body_hash"]): (
            str(observation.payload["message_id"]),
            str(observation.payload["message_occurrence_id"]),
        )
        for observation in result.observations
        if observation.observation_type == "email_message"
    }


def _rfc822_message(
    *,
    message_id: str = "<unit-001@example.test>",
    body: str = "Launch reviewed.\nAudit approval is next.",
    attachment_name: str = "brief.txt",
) -> bytes:
    return (
        f"Message-ID: {message_id}\n"
        "Subject: Launch checklist\n"
        "From: pm@example.test\n"
        "To: team@example.test\n"
        f"Date: {NOW}\n"
        "MIME-Version: 1.0\n"
        "Content-Type: multipart/mixed; boundary=unit-boundary\n"
        "\n"
        "--unit-boundary\n"
        "Content-Type: text/plain; charset=utf-8\n"
        "\n"
        f"{body}\n"
        "--unit-boundary\n"
        f'Content-Disposition: attachment; filename="{attachment_name}"\n'
        "Content-Type: text/plain\n"
        "\n"
        "attachment body\n"
        "--unit-boundary--\n"
    ).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
