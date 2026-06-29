from __future__ import annotations

import re
from typing import Any

from formowl_contract import now_iso, sha256_json, to_plain


class MarkdownFrontmatterBuilder:
    def build_frontmatter(
        self, input_data: dict[str, Any], citations: list[dict[str, Any]]
    ) -> dict[str, Any]:
        context_package = input_data["context_package"]
        title = str(input_data["title"])
        page_type = str(input_data["page_type"])
        revision_id = _id("rev_wiki", slugify(title), {"title": title, "context": context_package})
        project = _project_from_permission(context_package.get("permission_scope"))
        frontmatter = {
            "title": title,
            "type": page_type,
            "status": "draft",
            "revision_id": revision_id,
            "parent_revision_id": None,
            "change_kind": "generated",
            "project": project,
            "owner": None,
            "generated": True,
            "generated_by": "formowl-wiki-mcp",
            "review_status": "pending",
            "created_at": now_iso(),
            "last_reviewed": None,
            "source_refs": context_package.get("source_refs", []),
            "evidence_snapshot_ids": context_package.get("evidence_snapshot_ids", []),
            "related_work_items": _related_work_items(context_package.get("source_refs", [])),
            "citations": citations,
            "permission_scope": context_package.get("permission_scope"),
            "revision_backend": {"type": "markdown-store", "id": revision_id},
        }
        return frontmatter

    def serialize_frontmatter(self, frontmatter: dict[str, Any]) -> str:
        return "---\n" + _to_yaml(to_plain(frontmatter)).rstrip() + "\n---\n"

    def build_projection_frontmatter(
        self,
        input_data: dict[str, Any],
        projection: dict[str, Any],
    ) -> dict[str, Any]:
        spec = projection["projection_spec"]
        title = input_data["title"]
        page_type = spec["page_type"]
        graph_revision = projection["graph_revision"]
        graph_object_ids = projection["graph_object_ids"]
        revision_id = _id(
            "rev_wiki",
            slugify(title),
            _projection_identity(title, spec, graph_revision, graph_object_ids),
        )
        frontmatter = {
            "title": title,
            "type": page_type,
            "status": "draft",
            "revision_id": revision_id,
            "parent_revision_id": None,
            "change_kind": "projection_generated",
            "project": spec["scope_id"] if spec["scope_type"] == "project" else None,
            "owner": spec.get("created_by"),
            "generated": True,
            "generated_by": "formowl-wiki-mcp",
            "review_status": "pending",
            "created_at": now_iso(),
            "last_reviewed": None,
            "projection_spec_id": spec["projection_spec_id"],
            "ontology_revision_id": spec["ontology_revision_id"],
            "projection_policy_id": spec["projection_policy_id"],
            "include_graph_lineage": spec["include_graph_lineage"],
            "graph_scope": {
                "scope_type": graph_revision["scope_type"],
                "scope_id": graph_revision["scope_id"],
            },
            "projected_graph_object_ids": graph_object_ids,
            "source_refs": projection["source_refs"],
            "evidence_snapshot_ids": projection["evidence_snapshot_ids"],
            "related_work_items": _related_work_items(projection["source_refs"]),
            "citations": projection["citations"],
            "source_evidence_lineage": projection["source_evidence_lineage"],
            "permission_scope": {
                "scope_type": spec["scope_type"],
                "scope_id": spec["scope_id"],
                "visibility": "restricted",
            },
            "revision_backend": {"type": "markdown-store", "id": revision_id},
        }
        # Projection specs select exactly one graph lineage source. Keeping only
        # the active key makes the in-memory frontmatter match the serialized
        # markdown and prevents downstream tools from treating null lineage keys
        # as meaningful graph references.
        if spec.get("canonical_graph_revision_id"):
            frontmatter["canonical_graph_revision_id"] = spec["canonical_graph_revision_id"]
        if spec.get("user_graph_revision_id"):
            frontmatter["user_graph_revision_id"] = spec["user_graph_revision_id"]
        return frontmatter


class MarkdownDraftRenderer:
    def __init__(self, frontmatter_builder: MarkdownFrontmatterBuilder | None = None) -> None:
        self.frontmatter_builder = frontmatter_builder or MarkdownFrontmatterBuilder()

    def render_draft(self, input_data: dict[str, Any], frontmatter: dict[str, Any]) -> str:
        if "projection" in input_data:
            body = _projection_body(
                str(input_data["title"]),
                input_data["projection"],
            )
            return self.frontmatter_builder.serialize_frontmatter(frontmatter) + "\n" + body
        context_package = input_data["context_package"]
        title = str(input_data["title"])
        page_type = str(input_data["page_type"])
        body = _body_for_page_type(
            page_type, title, context_package, frontmatter.get("citations", [])
        )
        return self.frontmatter_builder.serialize_frontmatter(frontmatter) + "\n" + body


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "wiki-page"


def _project_from_permission(permission_scope: dict[str, Any] | None) -> str | None:
    if permission_scope and permission_scope.get("scope_type") == "project":
        return permission_scope.get("scope_id")
    return None


def _related_work_items(source_refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [ref for ref in source_refs if ref.get("source_type") in {"work_package", "issue"}]


def _body_for_page_type(
    page_type: str,
    title: str,
    context_package: dict[str, Any],
    citations: list[dict[str, Any]],
) -> str:
    context_markdown = str(context_package.get("context_markdown") or "").strip()
    if page_type == "adr":
        lines = [
            f"# {title}",
            "",
            "## Status",
            "",
            "Draft - pending human review.",
            "",
            "## Context",
            "",
            context_markdown or "_No context provided._",
            "",
            "## Decision",
            "",
            "_To be completed during review._",
            "",
            "## Consequences",
            "",
            "_To be completed during review._",
        ]
    else:
        lines = [
            f"# {title}",
            "",
            "## Summary",
            "",
            context_markdown or "_No context provided._",
        ]
    lines.extend(_source_section(context_package))
    lines.extend(_citation_section(citations))
    return "\n".join(lines).strip() + "\n"


def _source_section(context_package: dict[str, Any]) -> list[str]:
    lines = ["", "## Sources", ""]
    source_refs = context_package.get("source_refs", [])
    if not source_refs:
        lines.append("_No source references supplied._")
    for ref in source_refs:
        label = ref.get("source_key") or ref.get("source_id")
        source = ref.get("source_system")
        url = ref.get("source_url")
        lines.append(f"- {source}:{label}" + (f" - {url}" if url else ""))

    lines.extend(["", "## Evidence Snapshots", ""])
    evidence_ids = context_package.get("evidence_snapshot_ids", [])
    if not evidence_ids:
        lines.append("_No evidence snapshots supplied._")
    for evidence_id in evidence_ids:
        lines.append(f"- {evidence_id}")
    return lines


def _citation_section(citations: list[dict[str, Any]]) -> list[str]:
    lines = ["", "## Citations", ""]
    if not citations:
        lines.append("_No citations supplied._")
    for citation in citations:
        source_ref = citation.get("source_ref", {})
        label = source_ref.get("source_key") or source_ref.get("source_id")
        summary = citation.get("summary") or "Referenced source material."
        evidence_id = citation.get("evidence_snapshot_id")
        suffix = f" Evidence: {evidence_id}." if evidence_id else ""
        lines.append(
            f"- {citation.get('citation_id')}: {source_ref.get('source_system')}:{label}. {summary}.{suffix}"
        )
    return lines


def _projection_body(title: str, projection: dict[str, Any]) -> str:
    spec = projection["projection_spec"]
    graph_revision = projection["graph_revision"]
    graph_object_ids = projection["graph_object_ids"]
    graph_objects = projection["graph_objects"]
    lines = [
        f"# {title}",
        "",
        "## Projection",
        "",
        f"- Projection spec: {spec['projection_spec_id']}",
        f"- Ontology revision: {spec['ontology_revision_id']}",
        f"- Projection policy: {spec['projection_policy_id']}",
    ]
    if spec.get("user_graph_revision_id"):
        lines.append(f"- User graph revision: {spec['user_graph_revision_id']}")
    if spec.get("canonical_graph_revision_id"):
        lines.append(f"- Canonical graph revision: {spec['canonical_graph_revision_id']}")

    lines.extend(["", "## Graph Objects", ""])
    for label, ids in (
        ("Atoms", graph_object_ids["atom_ids"]),
        ("Entities", graph_object_ids["entity_ids"]),
        ("Relations", graph_object_ids["relation_ids"]),
    ):
        lines.append(f"### {label}")
        lines.append("")
        if not ids:
            lines.append("_No projected objects._")
        for graph_id in ids:
            summary = _graph_object_summary(graph_id, graph_objects)
            lines.append(f"- `{graph_id}`" + (f" - {summary}" if summary else ""))
        lines.append("")

    lines.extend(["## Sections", ""])
    for section in spec["section_specs"]:
        lines.append(f"### {section['title']}")
        lines.append("")
        lines.append(f"- Source: `{section['source']}`")
        if section.get("filters"):
            lines.append(f"- Filters: `{sha256_json(section['filters'])}`")
        lines.append(_section_projection_text(section, graph_revision, graph_object_ids))
        lines.append("")

    lines.extend(_projection_lineage_section(projection))
    lines.extend(_citation_section(projection["citations"]))
    return "\n".join(lines).strip() + "\n"


def _graph_object_summary(graph_id: str, graph_objects: dict[str, dict[str, Any]]) -> str | None:
    graph_object = graph_objects.get(graph_id)
    if not graph_object:
        return None
    if "canonical_text" in graph_object:
        return _one_line(str(graph_object["canonical_text"]))
    if "label" in graph_object:
        return _one_line(str(graph_object["label"]))
    if "relation_type" in graph_object:
        return (
            f"{graph_object.get('source_id')} "
            f"--{graph_object.get('relation_type')}--> "
            f"{graph_object.get('target_id')}"
        )
    return None


def _section_projection_text(
    section: dict[str, Any],
    graph_revision: dict[str, Any],
    graph_object_ids: dict[str, list[str]],
) -> str:
    source = section["source"]
    if source == "entity_summary":
        count = len(graph_object_ids["entity_ids"])
        return (
            f"Projected {count} entity reference(s) from revision `{_revision_id(graph_revision)}`."
        )
    if source == "source_observations":
        object_count = sum(len(ids) for ids in graph_object_ids.values())
        return f"Projected source lineage for {object_count} graph object(s)."
    if source == "graph_query":
        return "Projected graph ids are listed for reviewer validation."
    if source == "graph_neighbors":
        return "Projected neighboring graph objects are listed for reviewer validation."
    if source == "manual_notes":
        return "_Manual reviewer notes can be added here._"
    return "Projected graph content is available for reviewer validation."


def _projection_lineage_section(projection: dict[str, Any]) -> list[str]:
    lines = ["## Source And Evidence Lineage", ""]
    lineage = projection["source_evidence_lineage"]
    if not lineage:
        lines.append("_No source lineage supplied._")
        return lines
    for item in lineage:
        lines.append(
            f"- `{item['object_id']}`: "
            f"sources={', '.join(item['source_ids']) or 'none'}; "
            f"evidence={', '.join(item['evidence_snapshot_ids']) or 'none'}; "
            f"citations={', '.join(item['citation_ids']) or 'none'}"
        )
    return lines


def _revision_id(graph_revision: dict[str, Any]) -> str:
    return str(
        graph_revision.get("user_graph_revision_id")
        or graph_revision.get("graph_revision_id")
        or "unknown"
    )


def _projection_identity(
    title: str,
    spec: dict[str, Any],
    graph_revision: dict[str, Any],
    graph_object_ids: dict[str, list[str]],
) -> dict[str, Any]:
    return {
        "title": title,
        "page_type": spec["page_type"],
        "projection_spec_id": spec["projection_spec_id"],
        "canonical_graph_revision_id": spec.get("canonical_graph_revision_id"),
        "user_graph_revision_id": spec.get("user_graph_revision_id"),
        "graph_revision_id": _revision_id(graph_revision),
        "ontology_revision_id": spec["ontology_revision_id"],
        "projection_policy_id": spec["projection_policy_id"],
        "graph_object_ids": graph_object_ids,
    }


def _one_line(value: str) -> str:
    return " ".join(value.strip().split())[:240]


def _to_yaml(value: Any, indent: int = 0) -> str:
    spaces = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if item is None:
                lines.append(f"{spaces}{key}: null")
            elif isinstance(item, (dict, list)):
                lines.append(f"{spaces}{key}:")
                lines.append(_to_yaml(item, indent + 2))
            else:
                lines.append(f"{spaces}{key}: {_scalar(item)}")
        return "\n".join(lines) + ("\n" if lines else "")
    if isinstance(value, list):
        if not value:
            return f"{spaces}[]\n"
        lines = []
        for item in value:
            if isinstance(item, dict):
                lines.append(f"{spaces}-")
                lines.append(_to_yaml(item, indent + 2))
            elif isinstance(item, list):
                lines.append(f"{spaces}-")
                lines.append(_to_yaml(item, indent + 2))
            else:
                lines.append(f"{spaces}- {_scalar(item)}")
        return "\n".join(lines) + "\n"
    return f"{spaces}{_scalar(value)}\n"


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "" or any(
        char in text
        for char in [
            ":",
            "#",
            "{",
            "}",
            "[",
            "]",
            ",",
            "&",
            "*",
            "!",
            "|",
            ">",
            "'",
            '"',
            "%",
            "@",
            "`",
        ]
    ):
        escaped = text.replace('"', '\\"')
        return f'"{escaped}"'
    return text


def _id(prefix: str, seed: str, payload: Any) -> str:
    return f"{prefix}_{seed}_{sha256_json(payload).split(':', 1)[1][:12]}"
