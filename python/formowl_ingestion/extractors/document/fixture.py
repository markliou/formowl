from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from formowl_contract import Observation, now_iso, stable_observation_id, to_plain

from ...extraction import ExtractionInput, ExtractionResult

_SUPPORTED_DOCUMENT_MIME_TYPES = [
    "text/plain",
    "text/markdown",
    "text/html",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
]


@dataclass(frozen=True)
class _DocumentBlock:
    observation_type: str
    page: int
    block_index: int
    text: str
    payload: dict[str, Any]


class FixtureDocumentParserExtractor:
    """Deterministic document parser for text-backed Phase 0 fixtures."""

    def __init__(self, *, version: str = "0.1.0") -> None:
        self._version = version

    def name(self) -> str:
        return "fixture_document_parser"

    def version(self) -> str:
        return self._version

    def supported_mime_types(self) -> list[str]:
        return list(_SUPPORTED_DOCUMENT_MIME_TYPES)

    def extractor_type(self) -> str:
        return "document_structure"

    def extract(self, extraction_input: ExtractionInput) -> ExtractionResult:
        created_at = extraction_input.created_at or now_iso()
        source_payload = _source_payload(extraction_input.asset.source_ref)
        text = extraction_input.object_path.read_text(encoding="utf-8")
        observations: list[Observation] = []

        # The first adapter keeps parser behavior deterministic: fixtures use
        # form-feed page breaks and simple markdown-like structure markers.
        for block in _iter_document_blocks(text, source_payload=source_payload):
            location = {"page": block.page, "block_index": block.block_index}
            if block.observation_type == "table":
                location["table_index"] = block.payload["table_index"]
            elif block.observation_type == "list_item":
                location["list_item_index"] = block.payload["list_item_index"]
            elif block.observation_type == "paragraph":
                location["paragraph_index"] = block.payload["paragraph_index"]
            observation_id = stable_observation_id(
                asset_id=extraction_input.asset.asset_id,
                extractor_run_id=extraction_input.extractor_run_id,
                observation_type=block.observation_type,
                modality="document",
                location=location,
                text=block.text,
                payload=block.payload,
            )
            observations.append(
                Observation(
                    observation_id=observation_id,
                    asset_id=extraction_input.asset.asset_id,
                    extractor_run_id=extraction_input.extractor_run_id,
                    observation_type=block.observation_type,
                    modality="document",
                    text=block.text,
                    location=location,
                    confidence=1.0,
                    permission_scope=extraction_input.asset.permission_scope,
                    created_at=created_at,
                    payload=block.payload,
                )
            )

        warnings = [] if observations else ["no_document_observations"]
        return ExtractionResult(observations=observations, warnings=warnings)


def _iter_document_blocks(
    text: str,
    *,
    source_payload: dict[str, Any] | None,
) -> Iterable[_DocumentBlock]:
    paragraph_index = 0
    table_index = 0
    list_item_index = 0
    for page_number, page_text in enumerate(text.split("\f"), start=1):
        block_index = 0
        for raw_block in _split_blocks(page_text):
            block_index += 1
            stripped = raw_block.strip()
            payload = _with_source({"source_ref": source_payload})
            if _is_table_block(stripped):
                table_index += 1
                payload.update({"table_index": table_index, "rows": _table_rows(stripped)})
                yield _DocumentBlock("table", page_number, block_index, stripped, payload)
            elif _is_list_item(stripped):
                list_item_index += 1
                payload.update({"list_item_index": list_item_index})
                yield _DocumentBlock("list_item", page_number, block_index, stripped, payload)
            elif stripped.startswith("#"):
                payload.update({"heading_level": len(stripped) - len(stripped.lstrip("#"))})
                yield _DocumentBlock("heading", page_number, block_index, stripped, payload)
            else:
                paragraph_index += 1
                payload.update({"paragraph_index": paragraph_index})
                yield _DocumentBlock("paragraph", page_number, block_index, stripped, payload)


def _split_blocks(page_text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for line in page_text.splitlines():
        if line.strip():
            current.append(line)
            continue
        if current:
            blocks.append("\n".join(current))
            current = []
    if current:
        blocks.append("\n".join(current))
    return blocks


def _is_table_block(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    return len(lines) >= 2 and all("|" in line for line in lines)


def _table_rows(text: str) -> list[list[str]]:
    return [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in text.splitlines()
        if line.strip()
    ]


def _is_list_item(text: str) -> bool:
    return text.startswith(("- ", "* "))


def _with_source(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _source_payload(source_ref: Any) -> dict[str, Any] | None:
    if source_ref is None:
        return None
    return to_plain(source_ref)
