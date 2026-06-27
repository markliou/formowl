from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from formowl_contract import Observation, now_iso, stable_observation_id, to_plain

from ...extraction import ExtractionInput, ExtractionResult

_SUPPORTED_OCR_MIME_TYPES = [
    "image/png",
    "image/jpeg",
    "image/tiff",
    "application/pdf",
]


@dataclass(frozen=True)
class _OcrLine:
    page: int | None
    bbox: list[int] | None
    text: str
    line_index: int


class FixtureOcrExtractor:
    """Deterministic OCR adapter for text-backed image/PDF fixtures."""

    def __init__(self, *, version: str = "0.1.0") -> None:
        self._version = version

    def name(self) -> str:
        return "fixture_ocr_extractor"

    def version(self) -> str:
        return self._version

    def supported_mime_types(self) -> list[str]:
        return list(_SUPPORTED_OCR_MIME_TYPES)

    def extractor_type(self) -> str:
        return "ocr"

    def extract(self, extraction_input: ExtractionInput) -> ExtractionResult:
        created_at = extraction_input.created_at or now_iso()
        text = extraction_input.object_path.read_text(encoding="utf-8")
        observations: list[Observation] = []
        source_ref = _source_payload(extraction_input.asset.source_ref)

        # Fixture format: page|x1,y1,x2,y2|recognized text. It lets tests prove
        # OCR provenance and locators before a real OCR engine is wired in.
        for line in _iter_ocr_lines(text):
            location: dict[str, Any] = {"line_index": line.line_index}
            if line.page is not None:
                location["page"] = line.page
            if line.bbox is not None:
                location["bbox"] = line.bbox
            else:
                location["image_index"] = 1
            payload = _with_source({"source_ref": source_ref})
            observation_id = stable_observation_id(
                asset_id=extraction_input.asset.asset_id,
                extractor_run_id=extraction_input.extractor_run_id,
                observation_type="ocr_line",
                modality="image",
                location=location,
                text=line.text,
                payload=payload,
            )
            observations.append(
                Observation(
                    observation_id=observation_id,
                    asset_id=extraction_input.asset.asset_id,
                    extractor_run_id=extraction_input.extractor_run_id,
                    observation_type="ocr_line",
                    modality="image",
                    text=line.text,
                    location=location,
                    confidence=0.99,
                    permission_scope=extraction_input.asset.permission_scope,
                    created_at=created_at,
                    payload=payload,
                )
            )

        warnings = [] if observations else ["no_ocr_text"]
        return ExtractionResult(observations=observations, warnings=warnings)


def _iter_ocr_lines(text: str) -> Iterable[_OcrLine]:
    for line_index, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        parts = raw_line.split("|", 2)
        if len(parts) == 3:
            page = int(parts[0]) if parts[0].strip() else None
            bbox = _parse_bbox(parts[1])
            yield _OcrLine(page=page, bbox=bbox, text=parts[2].strip(), line_index=line_index)
        else:
            yield _OcrLine(page=None, bbox=None, text=raw_line.strip(), line_index=line_index)


def _parse_bbox(value: str) -> list[int] | None:
    stripped = value.strip()
    if not stripped:
        return None
    items = [int(item.strip()) for item in stripped.split(",")]
    if len(items) != 4:
        raise ValueError("OCR bbox must contain four integer coordinates")
    return items


def _with_source(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _source_payload(source_ref: Any) -> dict[str, Any] | None:
    if source_ref is None:
        return None
    return to_plain(source_ref)
