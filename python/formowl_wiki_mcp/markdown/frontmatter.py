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
        return {
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

    def serialize_frontmatter(self, frontmatter: dict[str, Any]) -> str:
        return "---\n" + _to_yaml(to_plain(frontmatter)).rstrip() + "\n---\n"


class MarkdownDraftRenderer:
    def __init__(self, frontmatter_builder: MarkdownFrontmatterBuilder | None = None) -> None:
        self.frontmatter_builder = frontmatter_builder or MarkdownFrontmatterBuilder()

    def render_draft(self, input_data: dict[str, Any], frontmatter: dict[str, Any]) -> str:
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
