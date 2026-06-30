from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import unittest

import _paths  # noqa: F401
from formowl_contract import (
    Asset,
    ContractValidationError,
    Observation,
    PermissionScope,
    SourceRef,
    stable_observation_id,
)
from formowl_ingestion.assets import register_asset_from_local_file
from formowl_ingestion.extraction import ExtractionInput, ExtractionResult, run_extractor
from formowl_ingestion.extractors import (
    FixtureAudioTranscriptExtractor,
    FixtureDocumentParserExtractor,
    FixtureMailArchiveExtractor,
    FixtureOcrExtractor,
    FixtureVideoSceneExtractor,
    PlainTextObservationExtractor,
)
from formowl_ingestion.storage import (
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    ObservationStore,
    StorageBackendRegistry,
)


class ExtractionEdgeCaseTests(unittest.TestCase):
    def test_unsupported_mime_type_rejects_before_run_or_observation_write(self) -> None:
        context = _ExtractionContext.create(
            "extraction-edge-unsupported-mime",
            filename="payload.json",
            mime_type="application/json",
            content='{"not": "plain text"}',
        )

        with self.assertRaises(ValueError):
            run_extractor(
                asset=context.asset,
                object_store=context.object_store,
                extractor_run_store=context.run_store,
                observation_store=context.observation_store,
                adapter=PlainTextObservationExtractor(),
            )

        self.assertEqual(context.run_store.list(), [])
        self.assertEqual(context.observation_store.list(), [])

    def test_family_wildcard_mime_type_is_supported(self) -> None:
        context = _ExtractionContext.create(
            "extraction-edge-family-wildcard",
            filename="notes.txt",
            mime_type="text/plain",
            content="The adapter declares text/* support.\n",
        )

        stored = run_extractor(
            asset=context.asset,
            object_store=context.object_store,
            extractor_run_store=context.run_store,
            observation_store=context.observation_store,
            adapter=_WarningOnlyFamilyTextAdapter(),
            started_at="2026-06-17T10:00:00+00:00",
            completed_at="2026-06-17T10:00:00+00:00",
        )

        self.assertEqual(stored.extractor_run.status, "succeeded")
        self.assertEqual(stored.extractor_run.warnings, ["family_wildcard_supported"])
        self.assertEqual(stored.observations, [])
        self.assertEqual(context.observation_store.list(), [])

    def test_adapter_exception_persists_failed_run_without_observations(self) -> None:
        context = _ExtractionContext.create(
            "extraction-edge-adapter-exception",
            filename="notes.txt",
            mime_type="text/plain",
            content="This fixture forces adapter failure.\n",
        )

        with self.assertRaisesRegex(RuntimeError, "fixture failure"):
            run_extractor(
                asset=context.asset,
                object_store=context.object_store,
                extractor_run_store=context.run_store,
                observation_store=context.observation_store,
                adapter=_ExplodingFamilyTextAdapter(),
                started_at="2026-06-17T10:00:00+00:00",
                completed_at="2026-06-17T10:00:00+00:00",
            )

        failed_runs = context.run_store.list()
        self.assertEqual(len(failed_runs), 1)
        self.assertEqual(failed_runs[0].status, "failed")
        self.assertEqual(failed_runs[0].extractor_name, "exploding_family_text_adapter")
        self.assertIn("fixture failure", failed_runs[0].errors[0])
        self.assertEqual(context.observation_store.list(), [])

    def test_run_extractor_rejects_empty_timestamps_without_writes(self) -> None:
        invalid_cases = [
            ("started_at", {"started_at": "", "completed_at": "2026-06-17T10:00:00+00:00"}),
            ("completed_at", {"started_at": "2026-06-17T10:00:00+00:00", "completed_at": ""}),
            (
                "started_at",
                {
                    "started_at": "not-a-timestamp",
                    "completed_at": "2026-06-17T10:00:00+00:00",
                },
            ),
            (
                "completed_at",
                {
                    "started_at": "2026-06-17T10:00:00+00:00",
                    "completed_at": "not-a-timestamp",
                },
            ),
        ]

        for field_name, timestamp_kwargs in invalid_cases:
            context = _ExtractionContext.create(
                f"extraction-edge-empty-{field_name}",
                filename="notes.txt",
                mime_type="text/plain",
                content="Explicit empty timestamps must fail before persistence.\n",
            )
            with self.subTest(field_name=field_name):
                with self.assertRaisesRegex(ContractValidationError, field_name):
                    run_extractor(
                        asset=context.asset,
                        object_store=context.object_store,
                        extractor_run_store=context.run_store,
                        observation_store=context.observation_store,
                        adapter=PlainTextObservationExtractor(),
                        **timestamp_kwargs,
                    )

                self.assertEqual(context.run_store.list(), [])
                self.assertEqual(context.observation_store.list(), [])

    def test_adapter_error_result_does_not_return_or_persist_observations(self) -> None:
        context = _ExtractionContext.create(
            "extraction-edge-error-result",
            filename="notes.txt",
            mime_type="text/plain",
            content="The adapter returns an error result.\n",
        )

        stored = run_extractor(
            asset=context.asset,
            object_store=context.object_store,
            extractor_run_store=context.run_store,
            observation_store=context.observation_store,
            adapter=_ErrorResultTextAdapter(),
            started_at="2026-06-17T10:00:00+00:00",
            completed_at="2026-06-17T10:00:00+00:00",
        )

        self.assertEqual(stored.extractor_run.status, "failed")
        self.assertEqual(stored.extractor_run.errors, ["adapter_reported_error"])
        self.assertEqual(stored.observations, [])
        self.assertEqual(context.observation_store.list(), [])

    def test_partial_observation_validation_failure_leaves_no_observations(self) -> None:
        context = _ExtractionContext.create(
            "extraction-edge-partial-observation-validation",
            filename="notes.txt",
            mime_type="text/plain",
            content="The second observation will fail validation.\n",
        )

        with self.assertRaises(ContractValidationError):
            run_extractor(
                asset=context.asset,
                object_store=context.object_store,
                extractor_run_store=context.run_store,
                observation_store=context.observation_store,
                adapter=_PartiallyInvalidObservationAdapter(),
                started_at="2026-06-17T10:00:00+00:00",
                completed_at="2026-06-17T10:00:00+00:00",
            )

        failed_runs = context.run_store.list()
        self.assertEqual(len(failed_runs), 1)
        self.assertEqual(failed_runs[0].status, "failed")
        self.assertIn("Observation.confidence", failed_runs[0].errors[0])
        self.assertEqual(context.observation_store.list(), [])

    def test_observation_store_id_failure_leaves_no_observations(self) -> None:
        context = _ExtractionContext.create(
            "extraction-edge-observation-store-id-failure",
            filename="notes.txt",
            mime_type="text/plain",
            content="The second observation id is unsafe for the file store.\n",
        )

        with self.assertRaisesRegex(ValueError, "safe file name"):
            run_extractor(
                asset=context.asset,
                object_store=context.object_store,
                extractor_run_store=context.run_store,
                observation_store=context.observation_store,
                adapter=_StoreUnsafeObservationIdAdapter(),
                started_at="2026-06-17T10:00:00+00:00",
                completed_at="2026-06-17T10:00:00+00:00",
            )

        failed_runs = context.run_store.list()
        self.assertEqual(len(failed_runs), 1)
        self.assertEqual(failed_runs[0].status, "failed")
        self.assertIn("safe file name", failed_runs[0].errors[0])
        self.assertEqual(context.observation_store.list(), [])

    def test_boolean_observation_confidence_fails_without_persistence(self) -> None:
        context = _ExtractionContext.create(
            "extraction-edge-boolean-observation-confidence",
            filename="notes.txt",
            mime_type="text/plain",
            content="Boolean confidence must not be normalized to 1.0.\n",
        )

        with self.assertRaises(ContractValidationError):
            run_extractor(
                asset=context.asset,
                object_store=context.object_store,
                extractor_run_store=context.run_store,
                observation_store=context.observation_store,
                adapter=_BooleanConfidenceObservationAdapter(),
                started_at="2026-06-17T10:00:00+00:00",
                completed_at="2026-06-17T10:00:00+00:00",
            )

        failed_runs = context.run_store.list()
        self.assertEqual(len(failed_runs), 1)
        self.assertEqual(failed_runs[0].status, "failed")
        self.assertIn("Observation.confidence", failed_runs[0].errors[0])
        self.assertEqual(context.observation_store.list(), [])

    def test_observation_lineage_mismatch_fails_without_persistence(self) -> None:
        cases = [
            ("asset_id", "Observation.asset_id"),
            ("extractor_run_id", "Observation.extractor_run_id"),
            ("permission_scope", "Observation.permission_scope"),
        ]

        for mismatch_field, expected_error in cases:
            context = _ExtractionContext.create(
                f"extraction-edge-lineage-mismatch-{mismatch_field}",
                filename="notes.txt",
                mime_type="text/plain",
                content="The adapter will return mismatched lineage.\n",
            )
            with self.subTest(mismatch_field=mismatch_field):
                with self.assertRaises(ContractValidationError):
                    run_extractor(
                        asset=context.asset,
                        object_store=context.object_store,
                        extractor_run_store=context.run_store,
                        observation_store=context.observation_store,
                        adapter=_LineageMismatchObservationAdapter(mismatch_field),
                        started_at="2026-06-17T10:00:00+00:00",
                        completed_at="2026-06-17T10:00:00+00:00",
                    )
                failed_runs = context.run_store.list()
                self.assertEqual(len(failed_runs), 1)
                self.assertEqual(failed_runs[0].status, "failed")
                self.assertIn(expected_error, failed_runs[0].errors[0])
                self.assertEqual(context.observation_store.list(), [])

    def test_empty_fixture_inputs_record_adapter_specific_warnings(self) -> None:
        cases = [
            (
                "text",
                PlainTextObservationExtractor(),
                "empty.txt",
                "text/plain",
                "",
                "no_text_observations",
            ),
            (
                "document",
                FixtureDocumentParserExtractor(),
                "empty.pdf",
                "application/pdf",
                "",
                "no_document_observations",
            ),
            (
                "ocr",
                FixtureOcrExtractor(),
                "empty.png",
                "image/png",
                "",
                "no_ocr_text",
            ),
            (
                "audio",
                FixtureAudioTranscriptExtractor(),
                "empty.wav",
                "audio/wav",
                "",
                "no_transcript_segments",
            ),
            (
                "video",
                FixtureVideoSceneExtractor(),
                "empty.mp4",
                "video/mp4",
                "",
                "no_video_scene_observations",
            ),
            (
                "mail",
                FixtureMailArchiveExtractor(),
                "empty-mail.json",
                "application/vnd.formowl.mail-archive+json",
                json.dumps({"archive_id": "archive_001", "mailbox_id": "mailbox_yifan"}),
                "no_mail_observations",
            ),
        ]

        for case_name, adapter, filename, mime_type, content, expected_warning in cases:
            context = _ExtractionContext.create(
                f"extraction-edge-empty-{case_name}",
                filename=filename,
                mime_type=mime_type,
                content=content,
            )
            with self.subTest(case_name=case_name):
                stored = run_extractor(
                    asset=context.asset,
                    object_store=context.object_store,
                    extractor_run_store=context.run_store,
                    observation_store=context.observation_store,
                    adapter=adapter,
                    started_at="2026-06-17T10:00:00+00:00",
                    completed_at="2026-06-17T10:00:00+00:00",
                )
                self.assertEqual(stored.extractor_run.status, "succeeded")
                self.assertEqual(stored.extractor_run.warnings, [expected_warning])
                self.assertEqual(stored.observations, [])
                self.assertEqual(context.observation_store.list(), [])

    def test_malformed_fixture_inputs_persist_failed_runs_without_observations(self) -> None:
        cases = [
            (
                "ocr-bad-bbox",
                FixtureOcrExtractor(),
                "bad-ocr.png",
                "image/png",
                "1|10,20,30|Bad bbox\n",
                "OCR bbox",
            ),
            (
                "audio-backwards-time",
                FixtureAudioTranscriptExtractor(),
                "bad-audio.wav",
                "audio/wav",
                "5.0|1.0|speaker_01|Backwards time.\n",
                "end_sec",
            ),
            (
                "video-unknown-record",
                FixtureVideoSceneExtractor(),
                "bad-video.mp4",
                "video/mp4",
                "unknown|0.0|1.0|Unsupported record.\n",
                "unsupported video fixture record type",
            ),
            (
                "video-backwards-scene-time",
                FixtureVideoSceneExtractor(),
                "bad-video-time.mp4",
                "video/mp4",
                "scene|5.0|1.0|Backwards scene time.\n",
                "end_sec",
            ),
            (
                "mail-missing-archive",
                FixtureMailArchiveExtractor(),
                "bad-mail.json",
                "application/vnd.formowl.mail-archive+json",
                json.dumps({"mailbox_id": "mailbox_yifan"}),
                "archive_id",
            ),
            (
                "mail-non-string-archive",
                FixtureMailArchiveExtractor(),
                "bad-mail-archive.json",
                "application/vnd.formowl.mail-archive+json",
                json.dumps({"archive_id": 1, "mailbox_id": "mailbox_yifan"}),
                "archive_id",
            ),
            (
                "mail-non-string-mailbox",
                FixtureMailArchiveExtractor(),
                "bad-mail-mailbox.json",
                "application/vnd.formowl.mail-archive+json",
                json.dumps({"archive_id": "archive_001", "mailbox_id": 1}),
                "mailbox_id",
            ),
            (
                "mail-non-string-folder-path",
                FixtureMailArchiveExtractor(),
                "bad-mail-folder.json",
                "application/vnd.formowl.mail-archive+json",
                json.dumps(
                    {
                        "archive_id": "archive_001",
                        "mailbox_id": "mailbox_yifan",
                        "folders": [{"folder_path_hash": 1}],
                    }
                ),
                "folder_path_hash",
            ),
            (
                "mail-non-string-message",
                FixtureMailArchiveExtractor(),
                "bad-mail-message.json",
                "application/vnd.formowl.mail-archive+json",
                json.dumps(
                    {
                        "archive_id": "archive_001",
                        "mailbox_id": "mailbox_yifan",
                        "messages": [
                            {
                                "message_id": 1,
                                "folder_path_hash": "sha256:folder-inbox",
                            }
                        ],
                    }
                ),
                "message_id",
            ),
            (
                "mail-non-string-thread",
                FixtureMailArchiveExtractor(),
                "bad-mail-thread.json",
                "application/vnd.formowl.mail-archive+json",
                json.dumps(
                    {
                        "archive_id": "archive_001",
                        "mailbox_id": "mailbox_yifan",
                        "messages": [
                            {
                                "message_id": "<msg-001@example.test>",
                                "thread_id": 1,
                                "folder_path_hash": "sha256:folder-inbox",
                            }
                        ],
                    }
                ),
                "thread_id",
            ),
            (
                "mail-invalid-headers",
                FixtureMailArchiveExtractor(),
                "bad-mail-headers.json",
                "application/vnd.formowl.mail-archive+json",
                json.dumps(
                    {
                        "archive_id": "archive_001",
                        "mailbox_id": "mailbox_yifan",
                        "messages": [
                            {
                                "message_id": "<msg-001@example.test>",
                                "folder_path_hash": "sha256:folder-inbox",
                                "headers": "not-a-header-object",
                            }
                        ],
                    }
                ),
                "headers",
            ),
        ]

        for case_name, adapter, filename, mime_type, content, expected_error in cases:
            context = _ExtractionContext.create(
                f"extraction-edge-malformed-{case_name}",
                filename=filename,
                mime_type=mime_type,
                content=content,
            )
            with self.subTest(case_name=case_name):
                with self.assertRaises(ValueError):
                    run_extractor(
                        asset=context.asset,
                        object_store=context.object_store,
                        extractor_run_store=context.run_store,
                        observation_store=context.observation_store,
                        adapter=adapter,
                        started_at="2026-06-17T10:00:00+00:00",
                        completed_at="2026-06-17T10:00:00+00:00",
                    )
                failed_runs = context.run_store.list()
                self.assertEqual(len(failed_runs), 1)
                self.assertEqual(failed_runs[0].status, "failed")
                self.assertIn(expected_error, failed_runs[0].errors[0])
                self.assertEqual(context.observation_store.list(), [])

    def test_object_hash_verification_failure_rejects_before_run_creation(self) -> None:
        context = _ExtractionContext.create(
            "extraction-edge-object-verification",
            filename="notes.txt",
            mime_type="text/plain",
            content="Original content.\n",
        )
        object_path = context.object_store.resolve_object_path(context.asset.object_uri)
        object_path.write_text("Tampered content that changes the hash.\n", encoding="utf-8")

        with self.assertRaises(FileNotFoundError):
            run_extractor(
                asset=context.asset,
                object_store=context.object_store,
                extractor_run_store=context.run_store,
                observation_store=context.observation_store,
                adapter=PlainTextObservationExtractor(),
            )

        self.assertEqual(context.run_store.list(), [])
        self.assertEqual(context.observation_store.list(), [])


@dataclass(frozen=True)
class _ExtractionContext:
    temp_dir: Path
    object_store: FileObjectStore
    run_store: ExtractorRunStore
    observation_store: ObservationStore
    asset: Asset

    @classmethod
    def create(
        cls,
        test_dir_name: str,
        *,
        filename: str,
        mime_type: str,
        content: str,
    ) -> "_ExtractionContext":
        temp_dir = _paths.fresh_test_dir(test_dir_name)
        source_path = temp_dir / "incoming" / filename
        source_path.parent.mkdir(parents=True)
        source_path.write_text(content, encoding="utf-8")

        registry = StorageBackendRegistry(temp_dir)
        backend = registry.register_local_backend(
            temp_dir / "object-root",
            workspace_scope="workspace_formowl",
        )
        object_store = FileObjectStore(registry)
        asset = register_asset_from_local_file(
            source_path,
            object_store=object_store,
            asset_store=AssetStore(temp_dir),
            storage_backend_id=backend.storage_backend_id,
            workspace_id="workspace_formowl",
            owner_user_id="user_yifan",
            permission_scope=PermissionScope.project("project_formowl"),
            source_ref=SourceRef(
                source_system="local",
                source_type="file",
                source_id=filename,
            ),
            mime_type=mime_type,
            created_at="2026-06-17T10:00:00+00:00",
            registered_at="2026-06-17T10:00:00+00:00",
        )
        return cls(
            temp_dir=temp_dir,
            object_store=object_store,
            run_store=ExtractorRunStore(temp_dir),
            observation_store=ObservationStore(temp_dir),
            asset=asset,
        )


class _WarningOnlyFamilyTextAdapter:
    def name(self) -> str:
        return "warning_only_family_text_adapter"

    def version(self) -> str:
        return "0.1.0"

    def supported_mime_types(self) -> list[str]:
        return ["text/*"]

    def extractor_type(self) -> str:
        return "test_warning_only"

    def extract(self, extraction_input: ExtractionInput) -> ExtractionResult:
        return ExtractionResult(warnings=["family_wildcard_supported"])


class _ExplodingFamilyTextAdapter(_WarningOnlyFamilyTextAdapter):
    def name(self) -> str:
        return "exploding_family_text_adapter"

    def extract(self, extraction_input: ExtractionInput) -> ExtractionResult:
        raise RuntimeError("fixture failure")


class _ErrorResultTextAdapter(_WarningOnlyFamilyTextAdapter):
    def name(self) -> str:
        return "error_result_text_adapter"

    def extract(self, extraction_input: ExtractionInput) -> ExtractionResult:
        location = {"line_start": 1, "line_end": 1}
        text = "This observation must not be persisted when errors are present."
        observation = Observation(
            observation_id=stable_observation_id(
                asset_id=extraction_input.asset.asset_id,
                extractor_run_id=extraction_input.extractor_run_id,
                observation_type="paragraph",
                modality="text",
                location=location,
                text=text,
            ),
            asset_id=extraction_input.asset.asset_id,
            extractor_run_id=extraction_input.extractor_run_id,
            observation_type="paragraph",
            modality="text",
            text=text,
            location=location,
            confidence=1.0,
            permission_scope=extraction_input.asset.permission_scope,
            created_at=extraction_input.created_at,
        )
        return ExtractionResult(observations=[observation], errors=["adapter_reported_error"])


class _PartiallyInvalidObservationAdapter(_WarningOnlyFamilyTextAdapter):
    def name(self) -> str:
        return "partially_invalid_observation_adapter"

    def extract(self, extraction_input: ExtractionInput) -> ExtractionResult:
        valid_location = {"line_start": 1, "line_end": 1}
        invalid_location = {"line_start": 2, "line_end": 2}
        valid = _observation_for_edge_adapter(
            extraction_input=extraction_input,
            text="This observation is valid.",
            location=valid_location,
            confidence=1.0,
        )
        invalid = _observation_for_edge_adapter(
            extraction_input=extraction_input,
            text="This observation is invalid.",
            location=invalid_location,
            confidence=1.1,
        )
        return ExtractionResult(observations=[valid, invalid])


class _StoreUnsafeObservationIdAdapter(_WarningOnlyFamilyTextAdapter):
    def name(self) -> str:
        return "store_unsafe_observation_id_adapter"

    def extract(self, extraction_input: ExtractionInput) -> ExtractionResult:
        valid = _observation_for_edge_adapter(
            extraction_input=extraction_input,
            text="This observation should not be written before preflight passes.",
            location={"line_start": 1, "line_end": 1},
            confidence=1.0,
        )
        unsafe = replace(
            _observation_for_edge_adapter(
                extraction_input=extraction_input,
                text="This observation has an unsafe store id.",
                location={"line_start": 2, "line_end": 2},
                confidence=1.0,
            ),
            observation_id="unsafe/observation",
        )
        return ExtractionResult(observations=[valid, unsafe])


class _BooleanConfidenceObservationAdapter(_WarningOnlyFamilyTextAdapter):
    def name(self) -> str:
        return "boolean_confidence_observation_adapter"

    def extract(self, extraction_input: ExtractionInput) -> ExtractionResult:
        observation = _observation_for_edge_adapter(
            extraction_input=extraction_input,
            text="Boolean confidence should fail validation.",
            location={"line_start": 1, "line_end": 1},
            confidence=True,  # type: ignore[arg-type]
        )
        return ExtractionResult(observations=[observation])


class _LineageMismatchObservationAdapter(_WarningOnlyFamilyTextAdapter):
    def __init__(self, mismatch_field: str) -> None:
        self.mismatch_field = mismatch_field

    def name(self) -> str:
        return f"lineage_mismatch_{self.mismatch_field}_adapter"

    def extract(self, extraction_input: ExtractionInput) -> ExtractionResult:
        location = {"line_start": 1, "line_end": 1}
        asset_id = extraction_input.asset.asset_id
        extractor_run_id = extraction_input.extractor_run_id
        permission_scope = extraction_input.asset.permission_scope
        if self.mismatch_field == "asset_id":
            asset_id = "asset_other"
        elif self.mismatch_field == "extractor_run_id":
            extractor_run_id = "run_other"
        elif self.mismatch_field == "permission_scope":
            permission_scope = {
                "scope_type": "workspace",
                "scope_id": "workspace_other",
                "visibility": "restricted",
            }
        observation = _observation_for_edge_adapter(
            extraction_input=extraction_input,
            text=f"Mismatched {self.mismatch_field}.",
            location=location,
            confidence=1.0,
            asset_id=asset_id,
            extractor_run_id=extractor_run_id,
            permission_scope=permission_scope,
        )
        return ExtractionResult(observations=[observation])


def _observation_for_edge_adapter(
    *,
    extraction_input: ExtractionInput,
    text: str,
    location: dict[str, int],
    confidence: float,
    asset_id: str | None = None,
    extractor_run_id: str | None = None,
    permission_scope: PermissionScope | dict[str, object] | None = None,
) -> Observation:
    resolved_asset_id = asset_id or extraction_input.asset.asset_id
    resolved_extractor_run_id = extractor_run_id or extraction_input.extractor_run_id
    resolved_permission_scope = permission_scope or extraction_input.asset.permission_scope
    return Observation(
        observation_id=stable_observation_id(
            asset_id=resolved_asset_id,
            extractor_run_id=resolved_extractor_run_id,
            observation_type="paragraph",
            modality="text",
            location=location,
            text=text,
        ),
        asset_id=resolved_asset_id,
        extractor_run_id=resolved_extractor_run_id,
        observation_type="paragraph",
        modality="text",
        text=text,
        location=location,
        confidence=confidence,
        permission_scope=resolved_permission_scope,
        created_at=extraction_input.created_at,
    )


if __name__ == "__main__":
    unittest.main()
