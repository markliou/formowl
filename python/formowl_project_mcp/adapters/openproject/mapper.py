from __future__ import annotations

from html import unescape
import re
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlparse


class OpenProjectMapper:
    def __init__(self, *, source_instance: str, base_url: str) -> None:
        self.source_instance = source_instance
        self.base_url = base_url.rstrip("/")

    def map_search_results(
        self, collection: dict[str, Any], *, query: str = "", limit: int | None = None
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for payload in _collection_elements(collection):
            if _first_id(payload.get("id"), _link_id(payload, "self")) is None:
                continue
            item = self.map_work_item(payload)
            results.append(
                {
                    "item": item,
                    "score": 1.0,
                    "matched_fields": self._matched_fields(item, query),
                }
            )
        return results[:limit] if limit is not None else results

    def map_work_item(self, payload: dict[str, Any]) -> dict[str, Any]:
        work_package_id = _first_id(payload.get("id"), _link_id(payload, "self")) or "unknown"
        project_id = _link_id(payload, "project") or "unknown"
        source_ref = self.work_package_source_ref(work_package_id)
        return {
            "title": _first_text(payload.get("subject"), _link_title(payload, "self"))
            or "Untitled work item",
            "description": _rich_text(payload.get("description")),
            "status": _link_title(payload, "status") or "unknown",
            "type": _link_title(payload, "type") or "unknown",
            "priority": _link_title(payload, "priority") or "unknown",
            "assignee": _link_title(payload, "assignee"),
            "responsible": _link_title(payload, "responsible"),
            "start_date": _scalar_text(payload.get("startDate")),
            "due_date": _scalar_text(payload.get("dueDate")),
            "updated_at": _scalar_text(payload.get("updatedAt")),
            "source_url": source_ref["source_url"],
            "source_ref": source_ref,
            "permission_scope": self.permission_scope(project_id),
        }

    def map_comments(self, activities_collection: dict[str, Any]) -> list[dict[str, Any]]:
        comments: list[dict[str, Any]] = []
        for activity in _collection_elements(activities_collection):
            body = _rich_text(activity.get("comment")).strip()
            if not body:
                continue
            activity_id = _first_id(activity.get("id"), _link_id(activity, "self"))
            work_package_id = _link_id(activity, "workPackage")
            if activity_id is None or work_package_id is None:
                continue
            comments.append(
                {
                    "comment_id": activity_id,
                    "body": body,
                    "author": _link_title(activity, "user") or "unknown",
                    "created_at": _scalar_text(activity.get("createdAt")),
                    "source_ref": self.work_package_child_source_ref(
                        work_package_id,
                        source_type="work_package_comment",
                        source_id=activity_id,
                    ),
                }
            )
        return comments

    def map_activities(self, collection: dict[str, Any]) -> list[dict[str, Any]]:
        activities: list[dict[str, Any]] = []
        for activity in _collection_elements(collection):
            activity_id = _first_id(activity.get("id"), _link_id(activity, "self"))
            body = _rich_text(activity.get("comment")).strip()
            details_body = _details_text(activity.get("details"))
            work_package_id = _link_id(activity, "workPackage")
            if activity_id is None or work_package_id is None:
                continue
            activities.append(
                {
                    "activity_id": activity_id,
                    "type": "comment" if body else "activity",
                    "actor": _link_title(activity, "user") or "unknown",
                    "body": body or details_body,
                    "created_at": _scalar_text(activity.get("createdAt")),
                    "source_ref": self.work_package_child_source_ref(
                        work_package_id,
                        source_type="work_package_activity",
                        source_id=activity_id,
                    ),
                }
            )
        return activities

    def map_relations(
        self, collection: dict[str, Any], *, source_work_package_id: str
    ) -> list[dict[str, Any]]:
        relations: list[dict[str, Any]] = []
        for relation in _collection_elements(collection):
            relation_id = _first_id(relation.get("id"), _link_id(relation, "self"))
            endpoints = self._relation_endpoint_ids(
                relation, source_work_package_id=source_work_package_id
            )
            if relation_id is None or endpoints is None:
                continue
            source_id, target_id = endpoints
            relations.append(
                {
                    "relation_id": relation_id,
                    "relation_type": _first_text(
                        relation.get("type"),
                        relation.get("relationType"),
                        _link_title(relation, "type"),
                    )
                    or "related",
                    "relation_source_ref": self.relation_source_ref(relation_id),
                    "source_ref": self.work_package_source_ref(source_id),
                    "target_ref": self.work_package_source_ref(target_id),
                    "description": _first_text(
                        relation.get("description"), _link_title(relation, "self")
                    ),
                }
            )
        return relations

    def map_attachments(
        self, collection: dict[str, Any], *, work_package_id: str
    ) -> list[dict[str, Any]]:
        attachments: list[dict[str, Any]] = []
        for attachment in _collection_elements(collection):
            attachment_id = _first_id(attachment.get("id"), _link_id(attachment, "self"))
            if attachment_id is None:
                continue
            fallback_url = self.ui_url(f"/api/v3/attachments/{_quote_path_segment(attachment_id)}")
            download_url = self.safe_same_origin_url(
                _link_href(attachment, "downloadLocation")
                or _link_href(attachment, "content")
                or _link_href(attachment, "self"),
                fallback_url=fallback_url,
            )
            attachments.append(
                {
                    "attachment_id": attachment_id,
                    "file_name": _attachment_file_name(attachment),
                    "content_type": _first_text(
                        attachment.get("contentType"), attachment.get("content_type")
                    ),
                    "size_bytes": _first_number(
                        attachment.get("fileSize"), attachment.get("filesize")
                    ),
                    "source_url": download_url,
                    "source_ref": self.work_package_child_source_ref(
                        work_package_id,
                        source_type="attachment",
                        source_id=attachment_id,
                        source_url=download_url,
                    ),
                }
            )
        return attachments

    def map_project_ref(self, payload: dict[str, Any]) -> dict[str, Any]:
        project_id = _project_identifier(payload)
        return {
            "source_system": "openproject",
            "source_instance": self.source_instance,
            "source_type": "project",
            "source_id": project_id,
            "source_key": _string_id(payload.get("identifier") or project_id),
            "source_url": self.ui_url(f"/projects/{_quote_path_segment(project_id)}"),
        }

    def map_project_status(
        self,
        project: dict[str, Any],
        work_packages_collection: dict[str, Any],
        *,
        include_recent_updates: bool,
    ) -> dict[str, Any]:
        project_ref = self.map_project_ref(project)
        status_counts: dict[str, int] = {}
        source_refs: list[dict[str, Any]] = []
        recent_updates: list[dict[str, Any]] = []
        for payload in _collection_elements(work_packages_collection):
            if _first_id(payload.get("id"), _link_id(payload, "self")) is None:
                continue
            item = self.map_work_item(payload)
            status = str(item.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
            source_refs.append(item["source_ref"])
            if include_recent_updates:
                recent_updates.append(
                    {
                        "activity_id": f"work_package_{item['source_ref']['source_id']}_updated",
                        "type": "work_package_update",
                        "actor": "openproject",
                        "body": f"{item['title']} is {status}.",
                        "created_at": item.get("updated_at"),
                        "source_ref": item["source_ref"],
                    }
                )
        return {
            "project_ref": project_ref,
            "summary_markdown": self.project_summary_markdown(project, status_counts),
            "status_counts": status_counts,
            "recent_updates": recent_updates,
            "source_refs": source_refs,
        }

    def project_summary_markdown(
        self, project: dict[str, Any], status_counts: dict[str, int]
    ) -> str:
        title = _first_text(project.get("name"), _link_title(project, "self")) or "Project Status"
        lines = [f"# {title} Status", "", "| Status | Count |", "| --- | ---: |"]
        for status, count in sorted(status_counts.items()):
            lines.append(f"| {status} | {count} |")
        return "\n".join(lines)

    def work_package_source_ref(self, source_id: str) -> dict[str, Any]:
        clean_id = _string_id(source_id)
        return {
            "source_system": "openproject",
            "source_instance": self.source_instance,
            "source_type": "work_package",
            "source_id": clean_id,
            "source_key": f"OP-{clean_id}",
            "source_url": self.ui_url(f"/work_packages/{_quote_path_segment(clean_id)}"),
        }

    def work_package_child_source_ref(
        self,
        work_package_id: str,
        *,
        source_type: str,
        source_id: str,
        source_url: str | None = None,
    ) -> dict[str, Any]:
        ref = self.work_package_source_ref(work_package_id)
        ref["source_type"] = source_type
        ref["source_id"] = _string_id(source_id)
        if source_url is not None:
            ref["source_url"] = source_url
        return ref

    def relation_source_ref(self, relation_id: str) -> dict[str, Any]:
        clean_id = _string_id(relation_id)
        return {
            "source_system": "openproject",
            "source_instance": self.source_instance,
            "source_type": "work_package_relation",
            "source_id": clean_id,
            "source_key": f"OP-REL-{clean_id}",
            "source_url": self.ui_url(f"/relations/{_quote_path_segment(clean_id)}"),
        }

    def permission_scope(self, project_id: str) -> dict[str, Any]:
        clean_project_id = _string_id(project_id or "unknown")
        return {
            "scope_type": "project",
            "scope_id": clean_project_id,
            "visibility": "restricted",
            "inherited_from": f"openproject:project:{clean_project_id}",
        }

    def ui_url(self, path: str) -> str:
        return urljoin(f"{self.base_url}/", path.lstrip("/"))

    def absolute_url(self, href: str) -> str:
        return urljoin(f"{self.base_url}/", href.lstrip("/"))

    def safe_same_origin_url(self, href: str | None, *, fallback_url: str) -> str:
        # Attachment links are copied into MCP-facing payloads and snapshots, so
        # only public same-origin OpenProject URLs may survive normalization.
        if not href:
            return fallback_url
        raw_href = str(href).strip()
        parsed_href = urlparse(raw_href)
        if parsed_href.scheme or parsed_href.netloc:
            candidate = urljoin(f"{self.base_url}/", raw_href)
        else:
            candidate = urljoin(f"{self.base_url}/", raw_href.lstrip("/"))
        if _same_http_origin(candidate, self.base_url) and not _contains_internal_locator(
            candidate
        ):
            return candidate
        return fallback_url

    def _matched_fields(self, item: dict[str, Any], query: str) -> list[str]:
        if not query:
            return []
        query = query.lower()
        fields: list[str] = []
        if query in str(item.get("title") or "").lower():
            fields.append("title")
        if query in str(item.get("description") or "").lower():
            fields.append("description")
        return fields or ["work_package"]

    def _relation_endpoint_ids(
        self, relation: dict[str, Any], *, source_work_package_id: str
    ) -> tuple[str, str] | None:
        from_id = _link_id(relation, "from")
        to_id = _link_id(relation, "to")
        if from_id is None or to_id is None:
            return None
        if from_id == source_work_package_id:
            return from_id, to_id
        if to_id == source_work_package_id:
            return to_id, from_id
        return None


def link_href(payload: dict[str, Any], name: str) -> str | None:
    return _link_href(payload, name)


def link_id(payload: dict[str, Any], name: str) -> str | None:
    return _link_id(payload, name)


def _collection_elements(collection: dict[str, Any]) -> list[dict[str, Any]]:
    embedded = collection.get("_embedded")
    if isinstance(embedded, dict) and isinstance(embedded.get("elements"), list):
        return [element for element in embedded["elements"] if isinstance(element, dict)]
    if isinstance(collection.get("elements"), list):
        return [element for element in collection["elements"] if isinstance(element, dict)]
    return []


def _links(payload: dict[str, Any]) -> dict[str, Any]:
    links = payload.get("_links")
    return links if isinstance(links, dict) else {}


def _link(payload: dict[str, Any], name: str) -> dict[str, Any]:
    link = _links(payload).get(name)
    return link if isinstance(link, dict) else {}


def _link_href(payload: dict[str, Any], name: str) -> str | None:
    href = _link(payload, name).get("href")
    return href if isinstance(href, str) and href else None


def _link_title(payload: dict[str, Any], name: str) -> str | None:
    title = _link(payload, name).get("title")
    return _scalar_text(title)


def _link_id(payload: dict[str, Any], name: str) -> str | None:
    href = _link_href(payload, name)
    return _id_from_href(href) if href else None


def _id_from_href(href: str | None) -> str | None:
    if not href:
        return None
    path = urlparse(str(href)).path.rstrip("/")
    if not path:
        return None
    encoded_id = path.rsplit("/", 1)[-1]
    return unquote(encoded_id) if encoded_id else None


def _quote_path_segment(value: str) -> str:
    return quote(value, safe="")


def _same_http_origin(url: str, base_url: str) -> bool:
    parsed_url = urlparse(url)
    parsed_base = urlparse(base_url)
    if parsed_url.scheme not in {"http", "https"}:
        return False
    return (parsed_url.scheme, parsed_url.netloc) == (parsed_base.scheme, parsed_base.netloc)


_INTERNAL_LOCATOR_PATTERN = re.compile(
    r"(?:file|storage|smb|nfs|webdav|object|sqlite|sqlite3|postgres|postgresql|"
    r"mysql|mariadb|mongodb|redis|formowl):/{0,2}",
    re.IGNORECASE,
)
_RAW_PATH_PATTERN = re.compile(r"(^|[\s=;&])(?:/[A-Za-z0-9._-]+/|[A-Za-z]:[\\/]|\\\\)")


def _contains_internal_locator(url: str) -> bool:
    parsed = urlparse(url)
    decoded_path = _repeatedly_unquote(parsed.path)
    decoded_query_fragment = _repeatedly_unquote(f"{parsed.query} {parsed.fragment}")
    return (
        _INTERNAL_LOCATOR_PATTERN.search(f"{decoded_path} {decoded_query_fragment}") is not None
        or _RAW_PATH_PATTERN.search(decoded_query_fragment) is not None
    )


def _repeatedly_unquote(value: str, *, max_rounds: int = 3) -> str:
    decoded = value
    for _ in range(max_rounds):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    return decoded


def _rich_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("raw", "markdown", "plain"):
            text = _scalar_text(value.get(key))
            if text is not None:
                return text
        html = _scalar_text(value.get("html"))
        if html is not None:
            return unescape(html).replace("<p>", "").replace("</p>", "")
        return ""
    return _scalar_text(value) or ""


def _details_text(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for detail in value:
        if isinstance(detail, dict):
            raw = _scalar_text(detail.get("raw"))
            if raw is not None:
                parts.append(raw)
                continue
            name = _first_text(detail.get("property"), detail.get("name"))
            before = _scalar_text(detail.get("from"))
            after = _scalar_text(detail.get("to"))
            if name and (before or after):
                parts.append(f"{name} changed from {before or 'empty'} to {after or 'empty'}.")
        else:
            text = _scalar_text(detail)
            if text is not None:
                parts.append(text)
    return " ".join(parts)


def _attachment_file_name(payload: dict[str, Any]) -> str | None:
    for key in ("fileName", "filename", "name"):
        value = _scalar_text(payload.get(key))
        if value is not None:
            return value
    return _link_title(payload, "self")


def _project_identifier(payload: dict[str, Any]) -> str:
    return (
        _first_id(payload.get("identifier"), payload.get("id"), _link_id(payload, "self"))
        or "unknown"
    )


def _string_id(value: Any) -> str:
    return _optional_id(value) or "unknown"


def _optional_id(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    clean_value = str(value).strip()
    return clean_value or None


def _first_id(*values: Any) -> str | None:
    for value in values:
        clean_value = _optional_id(value)
        if clean_value is not None:
            return clean_value
    return None


def _scalar_text(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    text = str(value)
    return text if text else None


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _scalar_text(value)
        if text is not None:
            return text
    return None


def _first_number(*values: Any) -> int | float | None:
    for value in values:
        if not isinstance(value, bool) and isinstance(value, (int, float)):
            return value
    return None
