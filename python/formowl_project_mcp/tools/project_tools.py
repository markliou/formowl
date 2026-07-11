from __future__ import annotations

import re
import time
from typing import Any

from formowl_contract import (
    ContextPackage,
    EvidenceSnapshot,
    McpResultEnvelope,
    now_iso,
    sha256_json,
)


class ProjectMcpTools:
    def __init__(self, adapter: Any, evidence_snapshot_store: Any, logger: Any) -> None:
        self.adapter = adapter
        self.evidence_snapshot_store = evidence_snapshot_store
        self.logger = logger

    def search_work_items(self, input_data: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        items = self.adapter.search_work_items(input_data)
        envelope = _envelope("work_item_search_results", "ok", {"items": items})
        self._log("search_work_items", input_data, envelope, started)
        return envelope

    def get_work_item(self, input_data: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        item = self.adapter.get_work_item(input_data.get("source_ref", {}))
        if item is None:
            envelope = _envelope(
                "work_item", "not_found", {"work_item": None}, warnings=["Work item was not found."]
            )
        else:
            envelope = _envelope(
                "work_item",
                "ok",
                {"work_item": item},
                source_refs=[item["source_ref"]],
                permission_scope=item.get("permission_scope"),
            )
        self._log("get_work_item", input_data, envelope, started)
        return envelope

    def get_work_item_context(self, input_data: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        context = self.adapter.get_work_item_context(input_data)
        if context is None:
            envelope = _envelope(
                "work_item_context", "not_found", {}, warnings=["Work item context was not found."]
            )
            self._log("get_work_item_context", input_data, envelope, started)
            return envelope

        work_item = context["work_item"]
        source_refs = _collect_context_source_refs(context)
        permission_scope = work_item.get("permission_scope")
        context_markdown = build_context_markdown(context)
        evidence_snapshot_ids: list[str] = []

        if input_data.get("create_evidence_snapshot", False):
            snapshot_ref = self._create_evidence_snapshot(
                "get_work_item_context",
                input_data,
                context,
                context_markdown,
                source_refs,
                permission_scope,
            )
            evidence_snapshot_ids.append(snapshot_ref["evidence_snapshot_id"])

        context_package = ContextPackage(
            context_package_id=_id("ctx_project", work_item["source_ref"]["source_id"], context),
            context_type="work_item_context",
            context_markdown=context_markdown,
            source_refs=source_refs,
            evidence_snapshot_ids=evidence_snapshot_ids,
            citations=[],
            permission_scope=permission_scope,
        ).to_dict()

        envelope = _envelope(
            "work_item_context",
            "ok",
            context,
            context_package=context_package,
            source_refs=source_refs,
            evidence_snapshot_ids=evidence_snapshot_ids,
            permission_scope=permission_scope,
        )
        self._log("get_work_item_context", input_data, envelope, started, evidence_snapshot_ids)
        return envelope

    def list_work_item_activities(self, input_data: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        activities = self.adapter.list_work_item_activities(input_data)
        evidence_snapshot_ids: list[str] = []
        source_refs = _collect_activity_source_refs(input_data, activities)
        if input_data.get("create_evidence_snapshot", False):
            normalized = build_activities_markdown(activities)
            snapshot_ref = self._create_evidence_snapshot(
                "list_work_item_activities",
                input_data,
                {"activities": activities},
                normalized,
                source_refs,
                None,
            )
            evidence_snapshot_ids.append(snapshot_ref["evidence_snapshot_id"])
        envelope = _envelope(
            "work_item_activities",
            "ok",
            {"activities": activities},
            source_refs=source_refs,
            evidence_snapshot_ids=evidence_snapshot_ids,
        )
        self._log("list_work_item_activities", input_data, envelope, started, evidence_snapshot_ids)
        return envelope

    def list_work_item_relations(self, input_data: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        relations = self.adapter.list_work_item_relations(input_data)
        source_refs = _collect_relation_source_refs(input_data, relations)
        evidence_snapshot_ids: list[str] = []
        if input_data.get("create_evidence_snapshot", False):
            snapshot_ref = self._create_evidence_snapshot(
                "list_work_item_relations",
                input_data,
                {"relations": relations},
                build_relations_markdown(relations),
                source_refs,
                None,
            )
            evidence_snapshot_ids.append(snapshot_ref["evidence_snapshot_id"])
        envelope = _envelope(
            "work_item_relations",
            "ok",
            {"relations": relations},
            source_refs=source_refs,
            evidence_snapshot_ids=evidence_snapshot_ids,
        )
        self._log("list_work_item_relations", input_data, envelope, started, evidence_snapshot_ids)
        return envelope

    def get_project_status(self, input_data: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        status = self.adapter.get_project_status(input_data)
        if status is None:
            envelope = _envelope(
                "project_status", "not_found", {}, warnings=["Project was not found."]
            )
            self._log("get_project_status", input_data, envelope, started)
            return envelope

        evidence_snapshot_ids: list[str] = []
        if input_data.get("create_evidence_snapshot", False):
            snapshot_ref = self._create_evidence_snapshot(
                "get_project_status",
                input_data,
                status,
                status.get("summary_markdown", ""),
                status.get("source_refs", []),
                None,
            )
            evidence_snapshot_ids.append(snapshot_ref["evidence_snapshot_id"])
        envelope = _envelope(
            "project_status",
            "ok",
            status,
            source_refs=status.get("source_refs", []),
            evidence_snapshot_ids=evidence_snapshot_ids,
        )
        self._log("get_project_status", input_data, envelope, started, evidence_snapshot_ids)
        return envelope

    def propose_work_item_comment(self, input_data: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        source_ref = input_data.get("source_ref", {})
        body = str(input_data.get("body") or "")
        proposal = {
            "proposal_id": _id(
                "proposal_comment", source_ref.get("source_id", "unknown"), input_data
            ),
            "target_source_ref": source_ref,
            "diff_markdown": f"```diff\n+ {body.replace(chr(10), chr(10) + '+ ')}\n```",
            "reason": input_data.get("reason"),
        }
        envelope = _envelope(
            "write_proposal",
            "pending_review",
            proposal,
            source_refs=[source_ref],
            warnings=["This is proposal-only. No project-system write was performed."],
        )
        self._log("propose_work_item_comment", input_data, envelope, started)
        return envelope

    def _create_evidence_snapshot(
        self,
        tool_name: str,
        request_payload: dict[str, Any],
        response_payload: dict[str, Any],
        normalized_markdown: str,
        source_refs: list[dict[str, Any]],
        permission_scope: dict[str, Any] | None,
    ) -> dict[str, str]:
        snapshot = EvidenceSnapshot(
            evidence_snapshot_id=_id("ev_project", tool_name, response_payload),
            mcp_server="project-mcp",
            tool_name=tool_name,
            captured_at=now_iso(),
            permission_scope=permission_scope or {"scope_type": "unknown", "visibility": "unknown"},
            source_refs=source_refs,
            request_hash=sha256_json(request_payload),
            response_hash=sha256_json(response_payload),
        )
        return self.evidence_snapshot_store.save_snapshot(
            {
                "snapshot": snapshot,
                "request_payload": request_payload,
                "response_payload": response_payload,
                "normalized_markdown": normalized_markdown,
            }
        )

    def _log(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        envelope: dict[str, Any],
        started: float,
        evidence_snapshot_ids: list[str] | None = None,
    ) -> None:
        self.logger.log(
            {
                "event_type": "mcp_tool_call",
                "server_name": "project-mcp",
                "tool_name": tool_name,
                "session_id": input_data.get("session_id"),
                "actor_user_id": input_data.get("requester_user_id"),
                "workspace_id": input_data.get("workspace_id"),
                "request_id": _id("req", tool_name, input_data),
                "called_at": now_iso(),
                "arguments_hash": sha256_json(input_data),
                "response_hash": sha256_json(envelope),
                "status": envelope["status"],
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "evidence_snapshot_id": evidence_snapshot_ids[0] if evidence_snapshot_ids else None,
            }
        )


def build_context_markdown(context: dict[str, Any]) -> str:
    item = context["work_item"]
    lines = [
        f"# {item.get('title', 'Untitled work item')}",
        "",
        f"- Source: {item['source_ref'].get('source_key') or item['source_ref'].get('source_id')}",
        f"- Status: {item.get('status', 'unknown')}",
        f"- Type: {item.get('type', 'unknown')}",
        f"- Priority: {item.get('priority', 'unknown')}",
        "",
        "## Description",
        "",
        item.get("description") or "_No description._",
    ]
    _append_comment_section(lines, "Comments", context.get("comments", []), "body")
    _append_comment_section(lines, "Activities", context.get("activities", []), "body")
    _append_relations(lines, context.get("relations", []))
    _append_attachments(lines, context.get("attachments", []))
    return "\n".join(lines).strip() + "\n"


def build_activities_markdown(activities: list[dict[str, Any]]) -> str:
    lines = ["# Work Item Activities", ""]
    for activity in activities:
        label = activity.get("activity_id", "activity")
        lines.append(f"- {label}: {activity.get('body', '')}")
    return "\n".join(lines).strip() + "\n"


def build_relations_markdown(relations: list[dict[str, Any]]) -> str:
    lines = ["# Work Item Relations", ""]
    for relation in relations:
        relation_id = relation.get("relation_id", "relation")
        target = relation.get("target_ref", {})
        target_label = target.get("source_key") or target.get("source_id") or "unknown target"
        lines.append(f"- {relation_id}: {relation.get('relation_type', 'related')} {target_label}")
    return "\n".join(lines).strip() + "\n"


def _collect_context_source_refs(context: dict[str, Any]) -> list[dict[str, Any]]:
    # Context packages and evidence snapshots must preserve all returned
    # OpenProject evidence refs, not only the top-level work package.
    source_refs: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_ref(value: Any) -> None:
        if not isinstance(value, dict):
            return
        key = sha256_json(value)
        if key not in seen:
            seen.add(key)
            source_refs.append(value)

    add_ref(context.get("work_item", {}).get("source_ref"))
    for comment in context.get("comments", []):
        add_ref(comment.get("source_ref"))
    for activity in context.get("activities", []):
        add_ref(activity.get("source_ref"))
    for relation in context.get("relations", []):
        add_ref(relation.get("relation_source_ref"))
        add_ref(relation.get("source_ref"))
        add_ref(relation.get("target_ref"))
    for attachment in context.get("attachments", []):
        add_ref(attachment.get("source_ref"))
    return source_refs


def _collect_activity_source_refs(
    input_data: dict[str, Any], activities: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    refs = [input_data.get("source_ref", {})]
    refs.extend(activity.get("source_ref") for activity in activities)
    return _dedupe_source_refs(refs)


def _collect_relation_source_refs(
    input_data: dict[str, Any], relations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    refs: list[Any] = []
    for relation in relations:
        refs.extend(
            [
                relation.get("source_ref"),
                relation.get("relation_source_ref"),
                relation.get("target_ref"),
            ]
        )
    if not refs:
        refs.append(input_data.get("source_ref", {}))
    return _dedupe_source_refs(refs)


def _dedupe_source_refs(values: list[Any]) -> list[dict[str, Any]]:
    source_refs: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for value in values:
        if not isinstance(value, dict):
            continue
        key = (
            str(value.get("source_system") or ""),
            str(value.get("source_type") or ""),
            str(value.get("source_id") or ""),
        )
        if not all(key) or key in seen:
            continue
        seen.add(key)
        source_refs.append(value)
    return source_refs


def _append_comment_section(
    lines: list[str], title: str, values: list[dict[str, Any]], body_key: str
) -> None:
    lines.extend(["", f"## {title}", ""])
    if not values:
        lines.append("_None._")
        return
    for value in values:
        author = value.get("author") or value.get("actor") or "unknown"
        created_at = value.get("created_at") or "unknown time"
        body = str(value.get(body_key) or "").strip()
        lines.append(f"- {author} at {created_at}: {body}")


def _append_relations(lines: list[str], relations: list[dict[str, Any]]) -> None:
    lines.extend(["", "## Relations", ""])
    if not relations:
        lines.append("_None._")
        return
    for relation in relations:
        target = relation.get("target_ref", {})
        lines.append(
            f"- {relation.get('relation_type', 'related')}: {target.get('source_key') or target.get('source_id')}"
        )


def _append_attachments(lines: list[str], attachments: list[dict[str, Any]]) -> None:
    lines.extend(["", "## Attachments", ""])
    if not attachments:
        lines.append("_None._")
        return
    for attachment in attachments:
        lines.append(
            f"- {attachment.get('file_name')} ({attachment.get('content_type', 'unknown')})"
        )


def _envelope(
    result_type: str,
    status: str,
    data: Any,
    *,
    context_package: dict[str, Any] | None = None,
    source_refs: list[dict[str, Any]] | None = None,
    evidence_snapshot_ids: list[str] | None = None,
    citations: list[dict[str, Any]] | None = None,
    permission_scope: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return McpResultEnvelope(
        result_type=result_type,
        status=status,  # type: ignore[arg-type]
        data=data,
        context_package=context_package,
        source_refs=source_refs or [],
        evidence_snapshot_ids=evidence_snapshot_ids or [],
        citations=citations or [],
        permission_scope=permission_scope,
        warnings=warnings or [],
    ).to_dict()


def _id(prefix: str, seed: str, payload: Any) -> str:
    digest = re.sub(r"[^a-f0-9]", "", sha256_json(payload).split(":", 1)[1])[:12]
    clean_seed = re.sub(r"[^a-zA-Z0-9]+", "_", str(seed)).strip("_").lower() or "item"
    return f"{prefix}_{clean_seed}_{digest}"
