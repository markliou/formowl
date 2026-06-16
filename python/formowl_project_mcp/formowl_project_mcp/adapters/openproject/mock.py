from __future__ import annotations

from copy import deepcopy
from typing import Any


class MockOpenProjectAdapter:
    source_system = "openproject"

    def __init__(self, source_instance: str = "mock-openproject") -> None:
        self.source_instance = source_instance
        self._work_items = _default_work_items(source_instance)
        self._comments = _default_comments(source_instance)
        self._activities = _default_activities(source_instance)
        self._relations = _default_relations(source_instance)
        self._attachments = _default_attachments(source_instance)

    def search_work_items(self, input_data: dict[str, Any]) -> list[dict[str, Any]]:
        query = str(input_data.get("query", "")).lower()
        limit = int(input_data.get("limit") or 10)
        results: list[dict[str, Any]] = []
        for item in self._work_items.values():
            haystack = " ".join(
                [
                    str(item.get("title", "")),
                    str(item.get("description", "")),
                    " ".join(
                        comment.get("body", "")
                        for comment in self._comments.get(item["source_ref"]["source_id"], [])
                    ),
                ]
            ).lower()
            if not query or query in haystack:
                matched_fields = (
                    ["title"]
                    if query and query in item.get("title", "").lower()
                    else ["description"]
                )
                results.append(
                    {"item": deepcopy(item), "score": 1.0, "matched_fields": matched_fields}
                )
        return results[:limit]

    def get_work_item(self, source_ref: dict[str, Any]) -> dict[str, Any] | None:
        item = self._work_items.get(str(source_ref.get("source_id")))
        return deepcopy(item) if item else None

    def get_work_item_context(self, input_data: dict[str, Any]) -> dict[str, Any] | None:
        source_id = str(input_data.get("source_ref", {}).get("source_id"))
        item = self.get_work_item(input_data.get("source_ref", {}))
        if item is None:
            return None
        return {
            "work_item": item,
            "comments": deepcopy(self._comments.get(source_id, []))
            if input_data.get("include_comments", True)
            else [],
            "activities": deepcopy(self._activities.get(source_id, []))
            if input_data.get("include_activities", True)
            else [],
            "relations": deepcopy(self._relations.get(source_id, []))
            if input_data.get("include_relations", True)
            else [],
            "attachments": deepcopy(self._attachments.get(source_id, []))
            if input_data.get("include_attachments", True)
            else [],
        }

    def list_work_item_activities(self, input_data: dict[str, Any]) -> list[dict[str, Any]]:
        source_id = str(input_data.get("source_ref", {}).get("source_id"))
        limit = int(input_data.get("limit") or 50)
        return deepcopy(self._activities.get(source_id, []))[:limit]

    def list_work_item_relations(self, input_data: dict[str, Any]) -> list[dict[str, Any]]:
        source_id = str(input_data.get("source_ref", {}).get("source_id"))
        return deepcopy(self._relations.get(source_id, []))

    def get_project_status(self, input_data: dict[str, Any]) -> dict[str, Any] | None:
        project_ref = deepcopy(input_data.get("project_ref") or _project_ref(self.source_instance))
        status_counts: dict[str, int] = {}
        source_refs: list[dict[str, Any]] = []
        recent_updates: list[dict[str, Any]] = []
        for item in self._work_items.values():
            status = str(item.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
            source_refs.append(deepcopy(item["source_ref"]))
            recent_updates.extend(
                deepcopy(self._activities.get(item["source_ref"]["source_id"], []))[:1]
            )
        return {
            "project_ref": project_ref,
            "summary_markdown": _project_summary(status_counts),
            "status_counts": status_counts,
            "recent_updates": recent_updates
            if input_data.get("include_recent_updates", True)
            else [],
            "source_refs": source_refs,
        }

    def resolve_project_ref(self, project_ref: dict[str, Any]) -> dict[str, Any] | None:
        if project_ref.get("source_type") == "project":
            return deepcopy(project_ref)
        return None


def _source_ref(source_instance: str, source_id: str, key: str) -> dict[str, Any]:
    return {
        "source_system": "openproject",
        "source_instance": source_instance,
        "source_type": "work_package",
        "source_id": source_id,
        "source_key": key,
        "source_url": f"https://openproject.example.test/work_packages/{source_id}",
    }


def _project_ref(source_instance: str) -> dict[str, Any]:
    return {
        "source_system": "openproject",
        "source_instance": source_instance,
        "source_type": "project",
        "source_id": "formowl",
        "source_key": "formowl",
        "source_url": "https://openproject.example.test/projects/formowl",
    }


def _permission_scope() -> dict[str, Any]:
    return {
        "scope_type": "project",
        "scope_id": "formowl",
        "visibility": "restricted",
        "inherited_from": "openproject:project:formowl",
    }


def _default_work_items(source_instance: str) -> dict[str, dict[str, Any]]:
    return {
        "123": {
            "title": "Define source-preserving wiki draft workflow",
            "description": "Build an ADR draft flow that keeps raw project context, evidence snapshots, and citations traceable.",
            "status": "In progress",
            "type": "Feature",
            "priority": "High",
            "assignee": "process-operator",
            "responsible": "admin-owner",
            "start_date": "2026-06-16",
            "due_date": "2026-06-30",
            "updated_at": "2026-06-16T12:00:00+08:00",
            "source_url": "https://openproject.example.test/work_packages/123",
            "source_ref": _source_ref(source_instance, "123", "OP-123"),
            "permission_scope": _permission_scope(),
        },
        "124": {
            "title": "Review markdown frontmatter provenance",
            "description": "Confirm generated wiki pages expose review state while keeping backend details implementation-facing.",
            "status": "New",
            "type": "Task",
            "priority": "Normal",
            "assignee": "reviewer",
            "responsible": "admin-owner",
            "updated_at": "2026-06-15T09:30:00+08:00",
            "source_url": "https://openproject.example.test/work_packages/124",
            "source_ref": _source_ref(source_instance, "124", "OP-124"),
            "permission_scope": _permission_scope(),
        },
    }


def _default_comments(source_instance: str) -> dict[str, list[dict[str, Any]]]:
    return {
        "123": [
            {
                "comment_id": "activity_456",
                "body": "The first version should generate a reviewable ADR and must not publish automatically.",
                "author": "admin-owner",
                "created_at": "2026-06-16T10:15:00+08:00",
                "source_ref": {
                    **_source_ref(source_instance, "123", "OP-123"),
                    "source_type": "work_package_comment",
                    "source_id": "activity_456",
                },
            }
        ]
    }


def _default_activities(source_instance: str) -> dict[str, list[dict[str, Any]]]:
    return {
        "123": [
            {
                "activity_id": "activity_455",
                "type": "status_change",
                "actor": "process-operator",
                "body": "Status changed from New to In progress.",
                "created_at": "2026-06-16T09:00:00+08:00",
                "source_ref": {
                    **_source_ref(source_instance, "123", "OP-123"),
                    "source_type": "work_package_activity",
                    "source_id": "activity_455",
                },
            },
            {
                "activity_id": "activity_456",
                "type": "comment",
                "actor": "admin-owner",
                "body": "The first version should generate a reviewable ADR and must not publish automatically.",
                "created_at": "2026-06-16T10:15:00+08:00",
                "source_ref": {
                    **_source_ref(source_instance, "123", "OP-123"),
                    "source_type": "work_package_activity",
                    "source_id": "activity_456",
                },
            },
        ]
    }


def _default_relations(source_instance: str) -> dict[str, list[dict[str, Any]]]:
    return {
        "123": [
            {
                "relation_id": "rel_123_124",
                "relation_type": "follows",
                "source_ref": _source_ref(source_instance, "123", "OP-123"),
                "target_ref": _source_ref(source_instance, "124", "OP-124"),
                "description": "Frontmatter review depends on the draft workflow.",
            }
        ]
    }


def _default_attachments(source_instance: str) -> dict[str, list[dict[str, Any]]]:
    return {
        "123": [
            {
                "attachment_id": "att_001",
                "file_name": "wiki-draft-input.json",
                "content_type": "application/json",
                "size_bytes": 1024,
                "source_url": "https://openproject.example.test/attachments/att_001",
                "source_ref": {
                    **_source_ref(source_instance, "123", "OP-123"),
                    "source_type": "attachment",
                    "source_id": "att_001",
                },
            }
        ]
    }


def _project_summary(status_counts: dict[str, int]) -> str:
    lines = ["# Project Status", "", "| Status | Count |", "| --- | ---: |"]
    for status, count in sorted(status_counts.items()):
        lines.append(f"| {status} | {count} |")
    return "\n".join(lines)
