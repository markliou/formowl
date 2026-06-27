from __future__ import annotations

from formowl_contract import Observation, now_iso, stable_observation_id, to_plain

from ...extraction import ExtractionInput, ExtractionResult


class FileTechnicalMetadataExtractor:
    """Deterministic metadata extractor for registered file assets."""

    def __init__(self, *, version: str = "0.1.0") -> None:
        self._version = version

    def name(self) -> str:
        return "file_technical_metadata_extractor"

    def version(self) -> str:
        return self._version

    def supported_mime_types(self) -> list[str]:
        return ["*/*"]

    def extractor_type(self) -> str:
        return "technical_metadata"

    def extract(self, extraction_input: ExtractionInput) -> ExtractionResult:
        asset = extraction_input.asset
        created_at = extraction_input.created_at or now_iso()
        metadata = {
            "asset_id": asset.asset_id,
            "mime_type": asset.mime_type,
            "file_size": asset.file_size,
            "content_hash": asset.content_hash,
            "storage_backend_id": asset.storage_backend_id,
            "workspace_id": asset.workspace_id,
            "object_uri": asset.object_uri,
            "original_filename": asset.original_filename,
            "source_ref": to_plain(asset.source_ref),
        }
        warnings: list[str] = []
        actual_file_size = extraction_input.object_path.stat().st_size
        if actual_file_size != asset.file_size:
            warnings.append("asset_file_size_mismatch")
            metadata["actual_file_size"] = actual_file_size

        location = {"object_uri": asset.object_uri}
        observation_id = stable_observation_id(
            asset_id=asset.asset_id,
            extractor_run_id=extraction_input.extractor_run_id,
            observation_type="technical_metadata",
            modality="file",
            location=location,
            payload={"metadata": metadata},
            extracted_value=metadata,
        )
        observation = Observation(
            observation_id=observation_id,
            asset_id=asset.asset_id,
            extractor_run_id=extraction_input.extractor_run_id,
            observation_type="technical_metadata",
            modality="file",
            location=location,
            confidence=1.0,
            permission_scope=asset.permission_scope,
            created_at=created_at,
            payload={"metadata": metadata},
            extracted_value=metadata,
        )
        return ExtractionResult(observations=[observation], warnings=warnings)
