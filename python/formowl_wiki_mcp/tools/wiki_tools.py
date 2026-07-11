from __future__ import annotations

import time
from typing import Any

from formowl_contract import McpResultEnvelope, now_iso, sha256_json
from formowl_core import diff_lines, sha256_prefixed

from ..adapters import WikiPublishAdapterRegistry
from ..markdown import MarkdownDraftRenderer, MarkdownFrontmatterBuilder, slugify
from ..projection import build_graph_projection_draft


class WikiMcpTools:
    def __init__(
        self,
        draft_store: Any,
        wiki_snapshot_store: Any,
        logger: Any,
        frontmatter_builder: MarkdownFrontmatterBuilder | None = None,
        draft_renderer: MarkdownDraftRenderer | None = None,
        publish_adapter_registry: WikiPublishAdapterRegistry | None = None,
    ) -> None:
        self.draft_store = draft_store
        self.wiki_snapshot_store = wiki_snapshot_store
        self.logger = logger
        self.frontmatter_builder = frontmatter_builder or MarkdownFrontmatterBuilder()
        self.draft_renderer = draft_renderer or MarkdownDraftRenderer(self.frontmatter_builder)
        self.publish_adapter_registry = publish_adapter_registry or WikiPublishAdapterRegistry()

    def search_wiki_pages(self, input_data: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        query = str(input_data.get("query") or "").lower()
        project = input_data.get("project")
        limit = int(input_data.get("limit") or 10)
        results = []
        for draft in self.draft_store.list_drafts(project):
            haystack = f"{draft.get('title', '')}\n{draft.get('markdown', '')}".lower()
            if not query or query in haystack:
                results.append(
                    {
                        "page": _page_from_draft(draft),
                        "score": 1.0,
                        "matched_fields": ["title", "markdown"],
                    }
                )
        envelope = _envelope("wiki_page_search_results", "ok", {"pages": results[:limit]})
        self._log("search_wiki_pages", input_data, envelope, started)
        return envelope

    def get_wiki_page(self, input_data: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        page_ref = input_data.get("page_ref", {})
        page_id = str(page_ref.get("source_id") or page_ref.get("page_id") or "")
        draft = self.draft_store.get_draft(page_id)
        if draft is None:
            envelope = _envelope(
                "wiki_page", "not_found", {"page": None}, warnings=["Wiki page was not found."]
            )
        else:
            envelope = _envelope(
                "wiki_page",
                "ok",
                {"page": _page_from_draft(draft)},
                source_refs=draft.get("source_refs", []),
                evidence_snapshot_ids=draft.get("evidence_snapshot_ids", []),
                citations=draft.get("citations", []),
                permission_scope=draft.get("frontmatter", {}).get("permission_scope"),
            )
        self._log("get_wiki_page", input_data, envelope, started)
        return envelope

    def generate_wiki_draft(self, input_data: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        context_package = input_data["context_package"]
        citations = _ensure_citations(context_package)
        frontmatter = self.frontmatter_builder.build_frontmatter(input_data, citations)
        markdown = self.draft_renderer.render_draft(input_data, frontmatter)
        draft_id = _draft_id(input_data["page_type"], input_data["title"], context_package)
        draft = {
            "draft_id": draft_id,
            "page_type": input_data["page_type"],
            "title": input_data["title"],
            "markdown": markdown,
            "frontmatter": frontmatter,
            "status": "draft",
            "source_refs": context_package.get("source_refs", []),
            "evidence_snapshot_ids": context_package.get("evidence_snapshot_ids", []),
            "citations": citations,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "markdown_hash": sha256_prefixed(markdown),
        }
        self.draft_store.save_draft(draft)
        envelope = _envelope(
            "wiki_draft",
            "ok",
            {"draft_id": draft_id, "markdown": markdown, "frontmatter": frontmatter},
            source_refs=draft["source_refs"],
            evidence_snapshot_ids=draft["evidence_snapshot_ids"],
            citations=citations,
            permission_scope=frontmatter.get("permission_scope"),
        )
        self._log("generate_wiki_draft", input_data, envelope, started, wiki_draft_id=draft_id)
        return envelope

    def generate_wiki_draft_from_graph_view(self, input_data: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        projection_spec = input_data["projection_spec"]
        previous_draft = _latest_projection_draft(
            self.draft_store.list_drafts(),
            str(projection_spec.get("projection_spec_id", "")),
        )
        draft = build_graph_projection_draft(
            projection_spec=projection_spec,
            graph_view=input_data.get("graph_view") or {},
            frontmatter_builder=self.frontmatter_builder,
            previous_draft=previous_draft,
        )
        self.draft_store.save_draft(draft)
        envelope = _envelope(
            "wiki_draft",
            "ok",
            {
                "draft_id": draft["draft_id"],
                "markdown": draft["markdown"],
                "frontmatter": draft["frontmatter"],
                "diff_markdown": draft.get("diff_markdown"),
                "revision_status": "draft",
                "redaction_counts": draft.get("redaction_counts", {}),
            },
            source_refs=draft.get("source_refs", []),
            evidence_snapshot_ids=draft.get("evidence_snapshot_ids", []),
            citations=draft.get("citations", []),
            permission_scope=draft.get("frontmatter", {}).get("permission_scope"),
            warnings=["Draft generated from graph view only; no wiki page was published."],
        )
        self._log(
            "generate_wiki_draft_from_graph_view",
            input_data,
            envelope,
            started,
            wiki_draft_id=draft["draft_id"],
        )
        return envelope

    def update_wiki_draft(self, input_data: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        draft = self.draft_store.get_draft(str(input_data.get("draft_id")))
        if draft is None:
            envelope = _envelope(
                "wiki_draft", "not_found", {"draft": None}, warnings=["Draft was not found."]
            )
            self._log("update_wiki_draft", input_data, envelope, started)
            return envelope

        patch = input_data.get("patch") or {}
        if "status" in patch:
            draft["status"] = patch["status"]
            draft["frontmatter"]["status"] = patch["status"]
            draft["frontmatter"]["review_status"] = (
                "reviewed" if patch["status"] == "reviewed" else "pending"
            )
            if patch["status"] == "reviewed":
                draft["frontmatter"]["last_reviewed"] = now_iso()
        if "title" in patch:
            draft["title"] = patch["title"]
            draft["frontmatter"]["title"] = patch["title"]
        if "frontmatter" in patch:
            draft["frontmatter"].update(patch["frontmatter"])
        if "content" in patch:
            draft["markdown"] = (
                self.frontmatter_builder.serialize_frontmatter(draft["frontmatter"])
                + "\n"
                + str(patch["content"]).strip()
                + "\n"
            )
            draft["markdown_hash"] = sha256_prefixed(draft["markdown"])
        draft["updated_at"] = now_iso()
        self.draft_store.save_draft(draft)
        envelope = _envelope(
            "wiki_draft",
            "ok",
            {"draft": draft},
            source_refs=draft.get("source_refs", []),
            evidence_snapshot_ids=draft.get("evidence_snapshot_ids", []),
            citations=draft.get("citations", []),
            permission_scope=draft.get("frontmatter", {}).get("permission_scope"),
        )
        self._log(
            "update_wiki_draft", input_data, envelope, started, wiki_draft_id=draft["draft_id"]
        )
        return envelope

    def publish_wiki_page(self, input_data: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        draft_id = str(input_data.get("draft_id"))
        draft = self.draft_store.get_draft(draft_id)
        if draft is None:
            envelope = _envelope(
                "publish_proposal", "not_found", {}, warnings=["Draft was not found."]
            )
            self._log("publish_wiki_page", input_data, envelope, started)
            return envelope

        target = input_data.get("target") or {}
        if not isinstance(target, dict):
            envelope = _envelope(
                "publish_proposal",
                "error",
                {"error_code": "invalid_publish_target"},
                source_refs=draft.get("source_refs", []),
                evidence_snapshot_ids=draft.get("evidence_snapshot_ids", []),
                citations=draft.get("citations", []),
                permission_scope=draft.get("frontmatter", {}).get("permission_scope"),
                warnings=["Wiki publish target was rejected before any publish side effect."],
            )
            self._log("publish_wiki_page", input_data, envelope, started, wiki_draft_id=draft_id)
            return envelope
        diff = diff_lines("", draft["markdown"], fromfile="empty", tofile=draft_id)
        try:
            adapter = self.publish_adapter_registry.resolve(target)
            backend_proposal = adapter.prepare_publish_proposal(
                draft=draft,
                target=target,
                diff_markdown=diff,
                automatic_publish_requested=bool(
                    input_data.get("auto_publish") or input_data.get("publish_mode") == "automatic"
                ),
            )
        except ValueError:
            envelope = _envelope(
                "publish_proposal",
                "error",
                {"error_code": "invalid_publish_target"},
                source_refs=draft.get("source_refs", []),
                evidence_snapshot_ids=draft.get("evidence_snapshot_ids", []),
                citations=draft.get("citations", []),
                permission_scope=draft.get("frontmatter", {}).get("permission_scope"),
                warnings=["Wiki publish target was rejected before any publish side effect."],
            )
            self._log("publish_wiki_page", input_data, envelope, started, wiki_draft_id=draft_id)
            return envelope
        proposal = {
            "proposal_id": _proposal_id("proposal_publish", draft_id, target),
            "target": backend_proposal.target,
            "backend": backend_proposal.backend,
            "diff_markdown": f"```diff\n{diff}```",
            "draft_id": draft_id,
            "revision_id": draft.get("frontmatter", {}).get("revision_id"),
        }
        envelope = _envelope(
            "publish_proposal",
            "pending_review",
            proposal,
            source_refs=draft.get("source_refs", []),
            evidence_snapshot_ids=draft.get("evidence_snapshot_ids", []),
            citations=draft.get("citations", []),
            permission_scope=draft.get("frontmatter", {}).get("permission_scope"),
            warnings=backend_proposal.warnings,
        )
        self._log("publish_wiki_page", input_data, envelope, started, wiki_draft_id=draft_id)
        return envelope

    def capture_wiki_snapshot(self, input_data: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        page_ref = input_data.get("page_ref", {})
        page_id = str(page_ref.get("source_id") or page_ref.get("page_id") or "")
        draft = self.draft_store.get_draft(page_id)
        if draft is None:
            envelope = _envelope(
                "wiki_snapshot", "not_found", {}, warnings=["Wiki page was not found."]
            )
            self._log("capture_wiki_snapshot", input_data, envelope, started)
            return envelope
        snapshot = {
            "wiki_snapshot_id": _proposal_id("wiki_snapshot", page_id, draft),
            "page_ref": page_ref,
            "captured_at": now_iso(),
            "source_refs": draft.get("source_refs", []),
            "storage_uri": None,
            "raw": {"draft": draft},
        }
        self.wiki_snapshot_store.save_snapshot(snapshot)
        envelope = _envelope(
            "wiki_snapshot",
            "ok",
            {"snapshot": snapshot},
            source_refs=draft.get("source_refs", []),
            evidence_snapshot_ids=draft.get("evidence_snapshot_ids", []),
            citations=draft.get("citations", []),
        )
        self._log("capture_wiki_snapshot", input_data, envelope, started, wiki_draft_id=page_id)
        return envelope

    def _log(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        envelope: dict[str, Any],
        started: float,
        wiki_draft_id: str | None = None,
    ) -> None:
        self.logger.log(
            {
                "event_type": "mcp_tool_call",
                "server_name": "wiki-mcp",
                "tool_name": tool_name,
                "session_id": input_data.get("session_id"),
                "actor_user_id": input_data.get("requester_user_id"),
                "workspace_id": input_data.get("workspace_id"),
                "request_id": _proposal_id("req", tool_name, input_data),
                "called_at": now_iso(),
                "arguments_hash": sha256_json(input_data),
                "response_hash": sha256_json(envelope),
                "status": envelope["status"],
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "wiki_draft_id": wiki_draft_id,
                "evidence_snapshot_id": (envelope.get("evidence_snapshot_ids") or [None])[0],
            }
        )


def _ensure_citations(context_package: dict[str, Any]) -> list[dict[str, Any]]:
    citations = list(context_package.get("citations") or [])
    if citations:
        return citations
    evidence_ids = context_package.get("evidence_snapshot_ids") or []
    generated = []
    for index, source_ref in enumerate(context_package.get("source_refs") or [], start=1):
        generated.append(
            {
                "citation_id": f"cit_{index:03d}",
                "source_ref": source_ref,
                "evidence_snapshot_id": evidence_ids[0] if evidence_ids else None,
                "summary": "Generated draft content is derived from this source reference",
            }
        )
    return generated


def _page_from_draft(draft: dict[str, Any]) -> dict[str, Any]:
    return {
        "page_ref": {
            "source_system": "markdown-store",
            "source_type": "markdown_page",
            "source_id": draft["draft_id"],
        },
        "title": draft["title"],
        "markdown": draft["markdown"],
        "frontmatter": draft["frontmatter"],
        "updated_at": draft.get("updated_at"),
        "permission_scope": draft.get("frontmatter", {}).get("permission_scope"),
    }


def _envelope(
    result_type: str,
    status: str,
    data: Any,
    *,
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
        source_refs=source_refs or [],
        evidence_snapshot_ids=evidence_snapshot_ids or [],
        citations=citations or [],
        permission_scope=permission_scope,
        warnings=warnings or [],
    ).to_dict()


def _draft_id(page_type: str, title: str, context_package: dict[str, Any]) -> str:
    return (
        f"draft_{page_type}_{slugify(title)}_{sha256_json(context_package).split(':', 1)[1][:10]}"
    )


def _proposal_id(prefix: str, seed: str, payload: Any) -> str:
    return f"{prefix}_{slugify(seed)}_{sha256_json(payload).split(':', 1)[1][:12]}"


def _latest_projection_draft(
    drafts: list[dict[str, Any]],
    projection_spec_id: str,
) -> dict[str, Any] | None:
    matches = [
        draft
        for draft in drafts
        if draft.get("frontmatter", {}).get("projection_spec_id") == projection_spec_id
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda draft: str(draft.get("updated_at") or ""))[-1]
