"""Observation query and bridge helpers for extracted resource content."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from formowl_contract import (
    Asset,
    Citation,
    ContextPackage,
    ExtractorRun,
    Observation,
    SourceRef,
    stable_resource_contract_id,
    to_plain,
)


def build_context_package_from_text_observations(
    observations: Sequence[Observation],
    *,
    assets: Mapping[str, Asset] | Sequence[Asset] | None = None,
    extractor_runs: Mapping[str, ExtractorRun] | Sequence[ExtractorRun] | None = None,
    title: str = "Selected Text Observations",
    context_type: str = "text_observation_context",
    context_package_id: str | None = None,
) -> ContextPackage:
    """Build a reviewable ContextPackage from selected text observations."""

    selected = list(observations)
    if not selected:
        raise ValueError("at least one observation is required")
    for observation in selected:
        if observation.modality != "text" or not observation.text:
            raise ValueError("only text observations with text can be bridged")

    asset_lookup = _index_records(assets, "asset_id")
    run_lookup = _index_records(extractor_runs, "extractor_run_id")
    permission_scope = _shared_permission_scope(selected, asset_lookup)
    source_refs = _source_refs(selected, asset_lookup)
    citations = _citations(selected, asset_lookup, run_lookup)
    evidence_snapshot_ids = _unique(
        observation.evidence_snapshot_id
        for observation in selected
        if observation.evidence_snapshot_id
    )
    context_markdown = _context_markdown(
        title=title,
        observations=selected,
        assets=asset_lookup,
        extractor_runs=run_lookup,
    )
    context_payload = {
        "context_type": context_type,
        "context_markdown": context_markdown,
        "source_refs": source_refs,
        "evidence_snapshot_ids": evidence_snapshot_ids,
        "citations": citations,
        "permission_scope": permission_scope,
    }
    return ContextPackage(
        context_package_id=context_package_id
        or stable_resource_contract_id("ctx", "ContextPackage", context_payload),
        context_type=context_type,
        context_markdown=context_markdown,
        source_refs=source_refs,
        evidence_snapshot_ids=evidence_snapshot_ids,
        citations=citations,
        permission_scope=permission_scope,
    )


def _index_records(
    records: Mapping[str, Any] | Sequence[Any] | None,
    id_field: str,
) -> dict[str, Any]:
    if records is None:
        return {}
    if isinstance(records, Mapping):
        return dict(records)
    return {str(getattr(record, id_field)): record for record in records}


def _shared_permission_scope(
    observations: list[Observation],
    assets: dict[str, Asset],
) -> dict[str, Any]:
    permission_scope = to_plain(observations[0].permission_scope)
    for observation in observations:
        if to_plain(observation.permission_scope) != permission_scope:
            raise ValueError("text observation permission scopes must match")
        asset = assets.get(observation.asset_id or "")
        if asset is not None and to_plain(asset.permission_scope) != permission_scope:
            raise ValueError("asset and observation permission scopes must match")
    return permission_scope


def _source_refs(
    observations: list[Observation],
    assets: dict[str, Asset],
) -> list[dict[str, Any]]:
    refs = [
        to_plain(_source_ref_for_observation(observation, assets)) for observation in observations
    ]
    return _dedupe_dicts(refs)


def _citations(
    observations: list[Observation],
    assets: dict[str, Asset],
    extractor_runs: dict[str, ExtractorRun],
) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for index, observation in enumerate(observations, start=1):
        asset = assets.get(observation.asset_id or "")
        run = extractor_runs.get(observation.extractor_run_id)
        locator = {
            "asset_id": observation.asset_id,
            "extractor_run_id": observation.extractor_run_id,
            "extractor_name": run.extractor_name if run is not None else None,
            "observation_id": observation.observation_id,
            "observation_type": observation.observation_type,
            "location": observation.location,
        }
        citations.append(
            Citation(
                citation_id=f"cit_obs_{index:03d}",
                source_ref=_source_ref_for_observation(observation, assets),
                evidence_snapshot_id=observation.evidence_snapshot_id,
                locator=locator,
                summary=_citation_summary(observation, asset),
            ).to_dict()
        )
    return citations


def _source_ref_for_observation(
    observation: Observation,
    assets: dict[str, Asset],
) -> SourceRef | dict[str, Any]:
    asset = assets.get(observation.asset_id or "")
    if asset is not None and asset.source_ref is not None:
        return asset.source_ref
    payload_source_ref = (observation.payload or {}).get("source_ref")
    if payload_source_ref is not None:
        return payload_source_ref
    if observation.asset_id:
        return SourceRef(
            source_system="formowl",
            source_type="asset",
            source_id=observation.asset_id,
            source_key=asset.original_filename if asset is not None else observation.asset_id,
        )
    return SourceRef(
        source_system="formowl",
        source_type="observation",
        source_id=observation.observation_id,
        source_key=observation.observation_id,
    )


def _context_markdown(
    *,
    title: str,
    observations: list[Observation],
    assets: dict[str, Asset],
    extractor_runs: dict[str, ExtractorRun],
) -> str:
    lines = [
        f"# {title}",
        "",
        "This context package is derived from persisted FormOwl text observations.",
        "",
    ]
    for index, observation in enumerate(observations, start=1):
        asset = assets.get(observation.asset_id or "")
        run = extractor_runs.get(observation.extractor_run_id)
        lines.extend(
            [
                f"## Observation {index}",
                "",
                f"- Asset ID: {observation.asset_id or 'none'}",
                f"- Extractor Run ID: {observation.extractor_run_id}",
                f"- Extractor: {run.extractor_name if run is not None else 'unknown'}",
                f"- Observation ID: {observation.observation_id}",
                f"- Observation Type: {observation.observation_type}",
                f"- Source Title: {_source_title(asset, observation)}",
                f"- Locator: {_location_label(observation.location)}",
                "",
                observation.text.strip(),
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def _citation_summary(observation: Observation, asset: Asset | None) -> str:
    return (
        f"Text observation {observation.observation_id} from "
        f"{_source_title(asset, observation)}"
    )


def _source_title(asset: Asset | None, observation: Observation) -> str:
    if asset is not None and asset.original_filename:
        return asset.original_filename
    if observation.asset_id:
        return observation.asset_id
    return observation.observation_id


def _location_label(location: dict[str, Any]) -> str:
    if "line_start" in location and "line_end" in location:
        return f"lines {location['line_start']}-{location['line_end']}"
    return json.dumps(to_plain(location), ensure_ascii=False, sort_keys=True)


def _dedupe_dicts(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for value in values:
        key = json.dumps(to_plain(value), ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def _unique(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return unique_values


__all__ = [
    "build_context_package_from_text_observations",
]
