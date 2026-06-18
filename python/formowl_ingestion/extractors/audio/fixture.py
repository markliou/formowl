from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from formowl_contract import Observation, now_iso, stable_observation_id, to_plain

from ...extraction import ExtractionInput, ExtractionResult

_SUPPORTED_AUDIO_MIME_TYPES = [
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp4",
]


@dataclass(frozen=True)
class _TranscriptSegment:
    start_sec: float
    end_sec: float
    speaker: str | None
    text: str
    segment_index: int


class FixtureAudioTranscriptExtractor:
    """Deterministic transcript adapter for text-backed audio fixtures."""

    def __init__(self, *, version: str = "0.1.0") -> None:
        self._version = version

    def name(self) -> str:
        return "fixture_audio_transcript_extractor"

    def version(self) -> str:
        return self._version

    def supported_mime_types(self) -> list[str]:
        return list(_SUPPORTED_AUDIO_MIME_TYPES)

    def extractor_type(self) -> str:
        return "asr"

    def extract(self, extraction_input: ExtractionInput) -> ExtractionResult:
        created_at = extraction_input.created_at or now_iso()
        text = extraction_input.object_path.read_text(encoding="utf-8")
        observations: list[Observation] = []
        source_ref = _source_payload(extraction_input.asset.source_ref)

        # Fixture format: start_sec|end_sec|speaker|transcript text. This keeps
        # ASR lineage and timing contracts testable before Whisper-like adapters.
        for segment in _iter_transcript_segments(text):
            location: dict[str, Any] = {
                "start_sec": segment.start_sec,
                "end_sec": segment.end_sec,
                "segment_index": segment.segment_index,
            }
            if segment.speaker is not None:
                location["speaker"] = segment.speaker
            payload = _with_source({"source_ref": source_ref})
            observation_id = stable_observation_id(
                asset_id=extraction_input.asset.asset_id,
                extractor_run_id=extraction_input.extractor_run_id,
                observation_type="transcript_segment",
                modality="audio",
                location=location,
                text=segment.text,
                payload=payload,
            )
            observations.append(
                Observation(
                    observation_id=observation_id,
                    asset_id=extraction_input.asset.asset_id,
                    extractor_run_id=extraction_input.extractor_run_id,
                    observation_type="transcript_segment",
                    modality="audio",
                    text=segment.text,
                    location=location,
                    confidence=0.99,
                    permission_scope=extraction_input.asset.permission_scope,
                    created_at=created_at,
                    payload=payload,
                )
            )

        warnings = [] if observations else ["no_transcript_segments"]
        return ExtractionResult(observations=observations, warnings=warnings)


def _iter_transcript_segments(text: str) -> Iterable[_TranscriptSegment]:
    for segment_index, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        parts = raw_line.split("|", 3)
        if len(parts) != 4:
            raise ValueError("audio transcript fixture lines must be start|end|speaker|text")
        start_sec = float(parts[0])
        end_sec = float(parts[1])
        if end_sec < start_sec:
            raise ValueError("audio transcript segment end_sec cannot be before start_sec")
        speaker = parts[2].strip() or None
        yield _TranscriptSegment(
            start_sec=start_sec,
            end_sec=end_sec,
            speaker=speaker,
            text=parts[3].strip(),
            segment_index=segment_index,
        )


def _with_source(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _source_payload(source_ref: Any) -> dict[str, Any] | None:
    if source_ref is None:
        return None
    return to_plain(source_ref)
