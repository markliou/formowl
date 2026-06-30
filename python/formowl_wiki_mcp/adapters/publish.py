from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Protocol

from formowl_contract import sha256_json

from ..markdown import slugify

_SAFE_TARGET_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_SAFE_TARGET_KEYS = {
    "target_system",
    "source_instance",
    "workspace_id",
    "project_id",
    "space_id",
    "page_id",
    "page_slug",
}
_RAW_TARGET_MARKERS = (
    "://",
    "\\",
    "/",
    "postgres",
    "sql",
    "token",
    "secret",
    "password",
    "api_key",
    "raw_path",
    "internal",
)


class WikiPublishProposalAdapter(Protocol):
    target_system: str

    def prepare_publish_proposal(
        self,
        *,
        draft: dict[str, Any],
        target: dict[str, Any],
        diff_markdown: str,
        automatic_publish_requested: bool,
    ) -> "WikiPublishProposal": ...


@dataclass(frozen=True)
class WikiPublishProposal:
    target: dict[str, Any]
    backend: dict[str, Any]
    warnings: list[str]


class WikiPublishAdapterRegistry:
    def __init__(
        self,
        adapters: list[WikiPublishProposalAdapter] | None = None,
        fallback_adapter: WikiPublishProposalAdapter | None = None,
    ) -> None:
        self._fallback = fallback_adapter or GenericWikiPublishProposalAdapter()
        self._adapters: dict[str, WikiPublishProposalAdapter] = {
            self._fallback.target_system: self._fallback
        }
        for adapter in adapters or [OpenProjectWikiPublishProposalAdapter()]:
            self.register(adapter)

    def register(self, adapter: WikiPublishProposalAdapter) -> None:
        target_system = _safe_target_system(adapter.target_system)
        self._adapters[target_system] = adapter

    def resolve(self, target: dict[str, Any]) -> WikiPublishProposalAdapter:
        target_system = _safe_target_system(str(target.get("target_system") or "generic_wiki"))
        return self._adapters.get(target_system, self._fallback)


class GenericWikiPublishProposalAdapter:
    target_system = "generic_wiki"

    def prepare_publish_proposal(
        self,
        *,
        draft: dict[str, Any],
        target: dict[str, Any],
        diff_markdown: str,
        automatic_publish_requested: bool,
    ) -> WikiPublishProposal:
        safe_target, omitted_keys = _safe_target_dict(
            {
                **target,
                "target_system": str(target.get("target_system") or self.target_system),
                "page_slug": str(target.get("page_slug") or slugify(str(draft.get("title")))),
            }
        )
        backend = _proposal_backend(
            backend_type=safe_target["target_system"],
            operation="prepare_publish_proposal",
            draft=draft,
            diff_markdown=diff_markdown,
            automatic_publish_requested=automatic_publish_requested,
            extra={"safe_target_hash": sha256_json(safe_target)},
        )
        warnings = _proposal_warnings(
            automatic_publish_requested=automatic_publish_requested,
            omitted_keys=omitted_keys,
        )
        return WikiPublishProposal(target=safe_target, backend=backend, warnings=warnings)


class OpenProjectWikiPublishProposalAdapter:
    target_system = "openproject_wiki"

    def prepare_publish_proposal(
        self,
        *,
        draft: dict[str, Any],
        target: dict[str, Any],
        diff_markdown: str,
        automatic_publish_requested: bool,
    ) -> WikiPublishProposal:
        project_id = _required_target_value(target.get("project_id"), "project_id")
        page_slug = _required_target_value(
            target.get("page_slug") or slugify(str(draft.get("title"))),
            "page_slug",
        )
        safe_target, omitted_keys = _safe_target_dict(
            {
                **target,
                "target_system": self.target_system,
                "project_id": project_id,
                "page_slug": page_slug,
            }
        )
        source_id = f"{project_id}:{page_slug}"
        backend = _proposal_backend(
            backend_type=self.target_system,
            operation="upsert_wiki_page",
            draft=draft,
            diff_markdown=diff_markdown,
            automatic_publish_requested=automatic_publish_requested,
            extra={
                "source_ref": {
                    "source_system": "openproject",
                    "source_type": "wiki_page",
                    "source_id": source_id,
                    "source_key": page_slug,
                },
                "requires_review_decision": True,
                "safe_target_hash": sha256_json(safe_target),
            },
        )
        warnings = _proposal_warnings(
            automatic_publish_requested=automatic_publish_requested,
            omitted_keys=omitted_keys,
        )
        return WikiPublishProposal(target=safe_target, backend=backend, warnings=warnings)


def _proposal_backend(
    *,
    backend_type: str,
    operation: str,
    draft: dict[str, Any],
    diff_markdown: str,
    automatic_publish_requested: bool,
    extra: dict[str, Any],
) -> dict[str, Any]:
    return {
        "type": backend_type,
        "operation": operation,
        "draft_id": draft["draft_id"],
        "revision_id": draft.get("frontmatter", {}).get("revision_id"),
        "content_hash": draft.get("markdown_hash"),
        "diff_hash": sha256_json({"diff_markdown": diff_markdown}),
        "publish_mode": "proposal_only",
        "status": "pending_review",
        "automatic_publish_requested": bool(automatic_publish_requested),
        "automatic_publish_enabled": False,
        "external_write_performed": False,
        **extra,
    }


def _proposal_warnings(
    *,
    automatic_publish_requested: bool,
    omitted_keys: list[str],
) -> list[str]:
    warnings = ["This is proposal-only. No wiki page was published."]
    if automatic_publish_requested:
        warnings.append(
            "Automatic wiki publishing is disabled because no approved publish backend is configured."
        )
    if omitted_keys:
        warnings.append("Backend-internal or unsafe target fields were omitted from the proposal.")
    return warnings


def _safe_target_dict(target: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    safe: dict[str, Any] = {}
    omitted: list[str] = []
    for key, value in target.items():
        if value is None:
            continue
        key_text = str(key)
        if key_text not in _SAFE_TARGET_KEYS or _is_raw_marker(key_text):
            omitted.append(key_text)
            continue
        if not isinstance(value, str):
            raise ValueError("wiki publish target fields must be strings")
        if not _SAFE_TARGET_VALUE.fullmatch(value) or _is_raw_marker(value):
            raise ValueError("wiki publish target contains an unsafe value")
        safe[key_text] = value
    if "target_system" not in safe:
        safe["target_system"] = "generic_wiki"
    return safe, sorted(set(omitted))


def _required_target_value(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"wiki publish target requires {field_name}")
    if not _SAFE_TARGET_VALUE.fullmatch(value) or _is_raw_marker(value):
        raise ValueError(f"wiki publish target contains unsafe {field_name}")
    return value


def _safe_target_system(value: str) -> str:
    if not _SAFE_TARGET_VALUE.fullmatch(value) or _is_raw_marker(value):
        raise ValueError("wiki publish target_system is unsafe")
    return value


def _is_raw_marker(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _RAW_TARGET_MARKERS)
