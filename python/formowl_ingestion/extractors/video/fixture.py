from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from formowl_contract import Observation, now_iso, stable_observation_id, to_plain

from ...extraction import ExtractionInput, ExtractionResult

_SUPPORTED_VIDEO_MIME_TYPES = [
    "video/mp4",
    "video/quicktime",
    "video/x-matroska",
]


@dataclass(frozen=True)
class _VideoObservation:
    observation_type: str
    text: str
    location: dict[str, Any]
    payload: dict[str, Any]


class FixtureVideoSceneExtractor:
    """Deterministic video scene/keyframe adapter for text-backed fixtures."""

    def __init__(self, *, version: str = "0.1.0") -> None:
        self._version = version

    def name(self) -> str:
        return "fixture_video_scene_extractor"

    def version(self) -> str:
        return self._version

    def supported_mime_types(self) -> list[str]:
        return list(_SUPPORTED_VIDEO_MIME_TYPES)

    def extractor_type(self) -> str:
        return "video_scene_detection"

    def extract(self, extraction_input: ExtractionInput) -> ExtractionResult:
        created_at = extraction_input.created_at or now_iso()
        text = extraction_input.object_path.read_text(encoding="utf-8")
        source_ref = _source_payload(extraction_input.asset.source_ref)
        observations: list[Observation] = []

        # Fixture format keeps video extraction deterministic:
        # scene|start|end|description or keyframe|timestamp|frame|caption.
        for parsed in _iter_video_observations(text, source_ref=source_ref):
            observation_id = stable_observation_id(
                asset_id=extraction_input.asset.asset_id,
                extractor_run_id=extraction_input.extractor_run_id,
                observation_type=parsed.observation_type,
                modality="video",
                location=parsed.location,
                text=parsed.text,
                payload=parsed.payload,
            )
            observations.append(
                Observation(
                    observation_id=observation_id,
                    asset_id=extraction_input.asset.asset_id,
                    extractor_run_id=extraction_input.extractor_run_id,
                    observation_type=parsed.observation_type,
                    modality="video",
                    text=parsed.text,
                    location=parsed.location,
                    confidence=0.99,
                    permission_scope=extraction_input.asset.permission_scope,
                    created_at=created_at,
                    payload=parsed.payload,
                )
            )

        warnings = [] if observations else ["no_video_scene_observations"]
        return ExtractionResult(observations=observations, warnings=warnings)


def _iter_video_observations(
    text: str,
    *,
    source_ref: dict[str, Any] | None,
) -> Iterable[_VideoObservation]:
    scene_index = 0
    keyframe_index = 0
    for line_index, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        parts = raw_line.split("|", 3)
        if len(parts) != 4:
            raise ValueError(
                "video fixture lines must be scene|start|end|text or keyframe|time|frame|text"
            )
        record_type = parts[0].strip()
        if record_type == "scene":
            scene_index += 1
            start_sec = float(parts[1])
            end_sec = float(parts[2])
            if end_sec < start_sec:
                raise ValueError("video scene end_sec cannot be before start_sec")
            payload = _with_source({"source_ref": source_ref, "line_index": line_index})
            yield _VideoObservation(
                observation_type="video_scene",
                text=parts[3].strip(),
                location={
                    "start_sec": start_sec,
                    "end_sec": end_sec,
                    "scene_index": scene_index,
                },
                payload=payload,
            )
        elif record_type == "keyframe":
            keyframe_index += 1
            timestamp_sec = float(parts[1])
            frame_index = int(parts[2])
            payload = _with_source({"source_ref": source_ref, "line_index": line_index})
            yield _VideoObservation(
                observation_type="keyframe",
                text=parts[3].strip(),
                location={
                    "timestamp_sec": timestamp_sec,
                    "frame_index": frame_index,
                    "keyframe_index": keyframe_index,
                },
                payload=payload,
            )
        else:
            raise ValueError(f"unsupported video fixture record type: {record_type}")


def _with_source(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _source_payload(source_ref: Any) -> dict[str, Any] | None:
    if source_ref is None:
        return None
    return to_plain(source_ref)
