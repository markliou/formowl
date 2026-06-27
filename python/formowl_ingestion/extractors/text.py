from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from formowl_contract import Observation, now_iso, stable_observation_id, to_plain

from ..extraction import ExtractionInput, ExtractionResult


_SUPPORTED_TEXT_MIME_TYPES = [
    "text/plain",
    "text/markdown",
    "text/x-markdown",
]


@dataclass(frozen=True)
class _TextBlock:
    line_start: int
    line_end: int
    text: str


class PlainTextObservationExtractor:
    """Deterministic extractor for plain text and markdown assets."""

    def __init__(self, *, version: str = "0.1.0") -> None:
        self._version = version

    def name(self) -> str:
        return "plain_text_extractor"

    def version(self) -> str:
        return self._version

    def supported_mime_types(self) -> list[str]:
        return list(_SUPPORTED_TEXT_MIME_TYPES)

    def extractor_type(self) -> str:
        return "document_structure"

    def extract(self, extraction_input: ExtractionInput) -> ExtractionResult:
        text = extraction_input.object_path.read_text(encoding="utf-8")
        observations: list[Observation] = []
        warnings: list[str] = []
        created_at = extraction_input.created_at or now_iso()

        for block in _iter_text_blocks(text.splitlines()):
            location = {"line_start": block.line_start, "line_end": block.line_end}
            observation_type = _observation_type(
                mime_type=extraction_input.asset.mime_type,
                text=block.text,
            )
            payload = _source_payload(extraction_input.asset.source_ref)
            observation_id = stable_observation_id(
                asset_id=extraction_input.asset.asset_id,
                extractor_run_id=extraction_input.extractor_run_id,
                observation_type=observation_type,
                modality="text",
                location=location,
                text=block.text,
                payload=payload,
            )
            observations.append(
                Observation(
                    observation_id=observation_id,
                    asset_id=extraction_input.asset.asset_id,
                    extractor_run_id=extraction_input.extractor_run_id,
                    observation_type=observation_type,
                    modality="text",
                    text=block.text,
                    location=location,
                    confidence=1.0,
                    permission_scope=extraction_input.asset.permission_scope,
                    created_at=created_at,
                    payload=payload,
                )
            )

        if not observations:
            warnings.append("no_text_observations")
        return ExtractionResult(observations=observations, warnings=warnings)


def _iter_text_blocks(lines: Iterable[str]) -> Iterable[_TextBlock]:
    start_line: int | None = None
    block_lines: list[str] = []

    for line_number, line in enumerate(lines, start=1):
        if line.strip():
            if start_line is None:
                start_line = line_number
            block_lines.append(line)
            continue
        if start_line is not None:
            yield _TextBlock(
                line_start=start_line,
                line_end=line_number - 1,
                text="\n".join(block_lines),
            )
            start_line = None
            block_lines = []

    if start_line is not None:
        yield _TextBlock(
            line_start=start_line,
            line_end=start_line + len(block_lines) - 1,
            text="\n".join(block_lines),
        )


def _observation_type(*, mime_type: str, text: str) -> str:
    if mime_type in {"text/markdown", "text/x-markdown"} and text.lstrip().startswith("#"):
        return "heading"
    return "paragraph"


def _source_payload(source_ref: Any) -> dict[str, Any] | None:
    if source_ref is None:
        return None
    return {"source_ref": to_plain(source_ref)}


__all__ = [
    "PlainTextObservationExtractor",
]
