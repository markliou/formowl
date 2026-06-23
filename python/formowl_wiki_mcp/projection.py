from __future__ import annotations

from typing import Any, Mapping
import re

from formowl_contract import (
    Citation,
    ContractValidationError,
    SourceRef,
    WikiProjectionSpec,
    now_iso,
    sha256_json,
)
from formowl_core import diff_lines, sha256_prefixed

from .markdown import MarkdownFrontmatterBuilder, slugify

_RAW_PRIVATE_PATTERNS = (
    re.compile(r"(^|[\s'\"])/(srv|home|tmp|var|mnt|opt|root)/", re.IGNORECASE),
    re.compile(r"[A-Za-z]:[\\/]"),
    re.compile(r"\b(file|smb|nfs|postgres|postgresql|mysql|sqlite)://", re.IGNORECASE),
    re.compile(r"\b(select|with|copy|insert|update|delete|drop|alter)\b\s+", re.IGNORECASE),
)
_FORBIDDEN_KEYS = {
    "raw_path",
    "filesystem_path",
    "object_store_uri",
    "object_key",
    "sql",
    "internal_sql",
    "worker_scratch",
    "raw_private_evidence",
    "private_evidence",
}


def build_graph_projection_draft(
    *,
    projection_spec: WikiProjectionSpec | dict[str, Any],
    graph_view: dict[str, Any],
    frontmatter_builder: MarkdownFrontmatterBuilder,
    previous_draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spec = (
        projection_spec
        if isinstance(projection_spec, WikiProjectionSpec)
        else WikiProjectionSpec.from_dict(projection_spec)
    )
    _validate_graph_view_matches_spec(spec, graph_view)
    visible_evidence_only(graph_view)
    citations = _projection_citations(spec, graph_view)
    graph_view_hash = sha256_json(graph_view)
    draft_id = _projection_draft_id(spec, graph_view_hash)
    frontmatter = _projection_frontmatter(
        spec=spec,
        graph_view=graph_view,
        citations=citations,
        graph_view_hash=graph_view_hash,
        previous_draft=previous_draft,
    )
    markdown = _render_projection_markdown(spec, graph_view, frontmatter_builder, frontmatter)
    diff_markdown = _diff_against_previous(previous_draft, markdown)
    created_at = now_iso()
    return {
        "draft_id": draft_id,
        "page_type": spec.projection_kind,
        "title": spec.title,
        "markdown": markdown,
        "frontmatter": frontmatter,
        "status": "draft",
        "source_refs": list(spec.source_refs),
        "evidence_snapshot_ids": list(spec.evidence_snapshot_ids),
        "evidence_snapshot_refs": [
            evidence_snapshot_ref(evidence_snapshot_id)
            for evidence_snapshot_id in spec.evidence_snapshot_ids
        ],
        "citations": citations,
        "created_at": created_at,
        "updated_at": created_at,
        "markdown_hash": sha256_prefixed(markdown),
        "diff_markdown": diff_markdown,
        "redaction_counts": dict(graph_view.get("redaction_counts", {})),
    }


def visible_evidence_only(graph_view: dict[str, Any]) -> bool:
    if graph_view.get("visible_evidence_only") is not True:
        raise ContractValidationError("graph_view.visible_evidence_only must be true")
    _reject_raw_private_evidence_projection(graph_view)
    for collection_name in ("nodes", "relations", "evidence_snippets"):
        collection = graph_view.get(collection_name, [])
        if not isinstance(collection, list):
            raise ContractValidationError(f"graph_view.{collection_name} must be a list")
        for item in collection:
            if not isinstance(item, dict):
                raise ContractValidationError(
                    f"graph_view.{collection_name} entries must be objects"
                )
            if item.get("visible") is False:
                raise ContractValidationError("graph projection cannot include hidden evidence")
    return True


def ontology_revision_pin(projection_spec: WikiProjectionSpec) -> str:
    return projection_spec.ontology_revision_id


def source_lineage_preserved(draft: dict[str, Any]) -> bool:
    return bool(draft.get("source_refs")) and bool(draft.get("evidence_snapshot_ids"))


def draft_not_publish(draft: dict[str, Any]) -> bool:
    return draft.get("status") == "draft" and draft.get("published_at") is None


def diff_created_on_refresh(draft: dict[str, Any]) -> bool:
    return bool(draft.get("diff_markdown"))


def evidence_snapshot_ref(evidence_snapshot_id: str) -> dict[str, str]:
    if not isinstance(evidence_snapshot_id, str) or not evidence_snapshot_id:
        raise ContractValidationError("evidence_snapshot_ref requires an evidence snapshot id")
    return {"evidence_snapshot_id": evidence_snapshot_id}


def _validate_graph_view_matches_spec(spec: WikiProjectionSpec, graph_view: dict[str, Any]) -> None:
    if not isinstance(graph_view, dict):
        raise ContractValidationError("graph_view must be an object")
    if graph_view.get("graph_revision_id") != spec.graph_revision_id:
        raise ContractValidationError("graph_view.graph_revision_id must match projection spec")
    if graph_view.get("ontology_revision_id") != spec.ontology_revision_id:
        raise ContractValidationError("graph_view.ontology_revision_id must match projection spec")
    if spec.user_graph_revision_id and graph_view.get("user_graph_revision_id") not in (
        None,
        spec.user_graph_revision_id,
    ):
        raise ContractValidationError(
            "graph_view.user_graph_revision_id must match projection spec"
        )


def _projection_citations(
    spec: WikiProjectionSpec,
    graph_view: dict[str, Any],
) -> list[dict[str, Any]]:
    snippets = graph_view.get("evidence_snippets", [])
    citations: list[dict[str, Any]] = []
    for index, snippet in enumerate(snippets, start=1):
        source_ref = snippet.get("source_ref") or spec.source_refs[0]
        SourceRef.from_dict(source_ref)
        evidence_snapshot_id = snippet.get("evidence_snapshot_id") or spec.evidence_snapshot_ids[0]
        citation = Citation(
            citation_id=str(snippet.get("citation_id") or f"cit_graph_{index:03d}"),
            source_ref=source_ref,
            evidence_snapshot_id=evidence_snapshot_id,
            locator=snippet.get("locator"),
            summary=str(snippet.get("summary") or snippet.get("snippet") or "Graph evidence."),
        ).to_dict()
        citations.append(citation)
    if citations:
        return citations
    return [
        Citation(
            citation_id=f"cit_graph_{index:03d}",
            source_ref=source_ref,
            evidence_snapshot_id=spec.evidence_snapshot_ids[0],
            summary="Graph-derived draft source.",
        ).to_dict()
        for index, source_ref in enumerate(spec.source_refs, start=1)
    ]


def _projection_frontmatter(
    *,
    spec: WikiProjectionSpec,
    graph_view: dict[str, Any],
    citations: list[dict[str, Any]],
    graph_view_hash: str,
    previous_draft: dict[str, Any] | None,
) -> dict[str, Any]:
    change_kind = "source_refresh" if previous_draft is not None else "generated"
    parent_revision_id = (
        previous_draft.get("frontmatter", {}).get("revision_id") if previous_draft else None
    )
    revision_id = _revision_id(spec, graph_view_hash, parent_revision_id)
    return {
        "title": spec.title,
        "type": spec.projection_kind,
        "status": "draft",
        "revision_id": revision_id,
        "parent_revision_id": parent_revision_id,
        "change_kind": change_kind,
        "generated": True,
        "generated_by": "formowl-wiki-mcp",
        "review_status": "pending",
        "created_at": now_iso(),
        "projection_spec_id": spec.projection_spec_id,
        "graph_revision_id": spec.graph_revision_id,
        "ontology_revision_id": spec.ontology_revision_id,
        "user_graph_revision_id": spec.user_graph_revision_id,
        "graph_view_hash": graph_view_hash,
        "citation_behavior": spec.citation_behavior,
        "redaction_policy": spec.redaction_policy,
        "projection_rules": dict(spec.projection_rules),
        "included_graph_node_ids": [
            str(node.get("node_id")) for node in graph_view.get("nodes", []) if node.get("node_id")
        ],
        "included_relation_ids": [
            str(relation.get("relation_id"))
            for relation in graph_view.get("relations", [])
            if relation.get("relation_id")
        ],
        "source_refs": list(spec.source_refs),
        "evidence_snapshot_ids": list(spec.evidence_snapshot_ids),
        "evidence_snapshot_refs": [
            evidence_snapshot_ref(evidence_snapshot_id)
            for evidence_snapshot_id in spec.evidence_snapshot_ids
        ],
        "citations": citations,
        "permission_scope": spec.permission_scope,
        "redaction_counts": dict(graph_view.get("redaction_counts", {})),
        "revision_backend": {"type": "markdown-store", "id": revision_id},
    }


def _render_projection_markdown(
    spec: WikiProjectionSpec,
    graph_view: dict[str, Any],
    frontmatter_builder: MarkdownFrontmatterBuilder,
    frontmatter: dict[str, Any],
) -> str:
    lines = [
        f"# {spec.title}",
        "",
        "## Graph Summary",
        "",
        str(graph_view.get("summary") or "_No graph summary supplied._"),
        "",
        "## Included Graph Nodes",
        "",
    ]
    nodes = graph_view.get("nodes", [])
    if not nodes:
        lines.append("_No visible graph nodes supplied._")
    for node in nodes:
        label = node.get("label") or node.get("node_id")
        summary = node.get("summary") or "Visible graph node."
        lines.append(f"- {label}: {summary}")

    lines.extend(["", "## Evidence", ""])
    snippets = graph_view.get("evidence_snippets", [])
    if not snippets:
        lines.append("_No visible evidence snippets supplied._")
    for snippet in snippets:
        citation_id = snippet.get("citation_id") or "citation"
        summary = snippet.get("summary") or snippet.get("snippet") or "Visible evidence."
        lines.append(f"- {citation_id}: {summary}")

    lines.extend(["", "## Redactions", ""])
    redaction_counts = graph_view.get("redaction_counts", {})
    if not redaction_counts:
        lines.append("- hidden_records: 0")
    for key, value in redaction_counts.items():
        lines.append(f"- {key}: {value}")

    return (
        frontmatter_builder.serialize_frontmatter(frontmatter)
        + "\n"
        + "\n".join(lines).strip()
        + "\n"
    )


def _projection_draft_id(spec: WikiProjectionSpec, graph_view_hash: str) -> str:
    return (
        f"draft_graph_{slugify(spec.title)}_"
        f"{sha256_json([spec.projection_spec_id, graph_view_hash]).split(':', 1)[1][:12]}"
    )


def _revision_id(
    spec: WikiProjectionSpec,
    graph_view_hash: str,
    parent_revision_id: str | None,
) -> str:
    return (
        f"rev_wiki_{slugify(spec.title)}_"
        f"{sha256_json([spec.projection_spec_id, graph_view_hash, parent_revision_id]).split(':', 1)[1][:12]}"
    )


def _diff_against_previous(previous_draft: dict[str, Any] | None, markdown: str) -> str | None:
    if previous_draft is None:
        return None
    return (
        "```diff\n"
        + diff_lines(
            str(previous_draft.get("markdown", "")),
            markdown,
            fromfile=str(previous_draft.get("draft_id", "previous")),
            tofile="projection-refresh",
        )
        + "```"
    )


def _reject_raw_private_evidence_projection(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in _FORBIDDEN_KEYS:
                raise ContractValidationError("raw private evidence projection is forbidden")
            _reject_raw_private_evidence_projection(item)
        return
    if isinstance(value, list):
        for item in value:
            _reject_raw_private_evidence_projection(item)
        return
    if isinstance(value, str):
        for pattern in _RAW_PRIVATE_PATTERNS:
            if pattern.search(value):
                raise ContractValidationError("raw private evidence projection is forbidden")
