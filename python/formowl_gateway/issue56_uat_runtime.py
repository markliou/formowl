"""Thin real-source browser UAT adapter for the normal Issue #56 MCP route."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
import re
from threading import Lock
from typing import Any

from starlette.testclient import TestClient

from formowl_contract import assert_no_public_raw_references
from formowl_core import load_issue56_target_mail_tokenizer_profile

from .issue56_diagnostic import mcp_headers, mcp_query_request
from .runtime import ConnectedRuntime, ConnectedRuntimeConfig
from .semantic import validate_public_gateway_payload


_BEARER_ENV = "FORMOWL_ISSUE56_UAT_BEARER_TOKEN"


class Issue56UatQueryService:
    """Adapt one browser prompt to bounded calls on an existing runtime."""

    def __init__(self, runtime: ConnectedRuntime, *, bearer_token: str) -> None:
        if not isinstance(bearer_token, str) or not bearer_token.strip():
            raise RuntimeError("issue56_uat_bearer_required")
        self._bearer_token = bearer_token
        self._client_context = TestClient(
            runtime.application.app,
            raise_server_exceptions=False,
        )
        self._client = self._client_context.__enter__()
        self._lock = Lock()
        self.request_count = 0
        self.last_mcp_statuses: tuple[str, ...] = ()

    def __enter__(self) -> Issue56UatQueryService:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def close(self) -> None:
        context = getattr(self, "_client_context", None)
        if context is not None:
            self._client_context = None
            context.__exit__(None, None, None)

    def ask(self, prompt: str) -> Mapping[str, Any]:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt is required")
        with self._lock:
            self.request_count = 0
            responses = [self._call(prompt)]
            for follow_up in _follow_up_queries(prompt, responses[0]):
                responses.append(self._call(follow_up))
            self.last_mcp_statuses = tuple(
                str(response.get("status", "unknown")) for response in responses
            )
            result = _browser_projection(responses)
            validate_public_gateway_payload(result)
            assert_no_public_raw_references(result, "issue56_uat_browser_result")
            return result

    def _call(self, query_text: str) -> Mapping[str, Any]:
        self.request_count += 1
        response = self._client.post(
            "/mcp",
            headers=mcp_headers(bearer=self._bearer_token),
            json=mcp_query_request(query_text),
        )
        envelope = response.json()
        result = envelope.get("result") if isinstance(envelope, Mapping) else None
        structured = (
            result.get("structuredContent")
            if isinstance(result, Mapping) and result.get("isError") is not True
            else None
        )
        data = structured.get("data") if isinstance(structured, Mapping) else None
        if response.status_code != 200 or not isinstance(data, Mapping):
            return {"status": "mcp_failed", "citations": []}
        validate_public_gateway_payload(data)
        return data


def _follow_up_queries(prompt: str, data: Mapping[str, Any]) -> tuple[str, ...]:
    if data.get("status") not in {"replan_required", "partial", "incomplete"}:
        return ()
    agent = data.get("query_agent")
    replan = agent.get("external_replan") if isinstance(agent, Mapping) else None
    capability = agent.get("authorized_capability_summary") if isinstance(agent, Mapping) else None
    requested = (
        replan.get("requested_projection_field_hashes") if isinstance(replan, Mapping) else None
    )
    fields = capability.get("projection_fields") if isinstance(capability, Mapping) else None
    if (
        not isinstance(replan, Mapping)
        or not isinstance(capability, Mapping)
        or not isinstance(requested, Sequence)
        or isinstance(requested, (str, bytes))
        or not isinstance(fields, Sequence)
        or isinstance(fields, (str, bytes))
        or capability.get("listing_status") != "complete"
    ):
        return ()
    raw_ambiguous = replan.get("ambiguous_projection_term_hashes", ())
    if not isinstance(raw_ambiguous, Sequence) or isinstance(raw_ambiguous, (str, bytes)):
        return ()
    ambiguous = {value for value in raw_ambiguous if isinstance(value, str)}
    requested = tuple(value for value in requested if value not in ambiguous)
    if not 1 <= len(requested) <= 2:
        return ()
    authorized: dict[str, list[str]] = {}
    for field in fields:
        if (
            isinstance(field, Mapping)
            and field.get("structure_status") == "source_provided"
            and field.get("label_redacted") is False
            and isinstance(field.get("field_hash"), str)
            and isinstance(field.get("field"), str)
        ):
            authorized.setdefault(field["field_hash"], []).append(field["field"])
    labels: list[str] = []
    for field_hash in requested:
        matches = authorized.get(field_hash, ())
        if len(matches) != 1:
            return ()
        labels.append(matches[0])
    prefix = _filter_prefix(prompt, labels)
    if prefix is None:
        return ()
    return tuple(f"{prefix}{label}？" for label in labels)


def _filter_prefix(prompt: str, labels: Sequence[str]) -> str | None:
    label_starts = [
        match.start()
        for label in labels
        for match in re.finditer(re.escape(label), prompt, flags=re.IGNORECASE)
    ]
    if label_starts:
        prefix = prompt[: min(label_starts)]
        if prefix.strip():
            return prefix
    terms = load_issue56_target_mail_tokenizer_profile().analyze_query_grounding(prompt).terms
    boundaries = [
        term
        for index, term in enumerate(terms)
        if term.grammar_role == "particle"
        and index
        and prompt[: term.start].strip()
        and any(later.grammar_role in {"lexical", "operator"} for later in terms[index + 1 :])
    ]
    if not boundaries:
        return None
    return prompt[: boundaries[0].end]


def _browser_projection(responses: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    citations: set[str] = set()
    answers: list[str] = []
    complete = True
    row_number = 0
    for data in responses:
        exact = data.get("exact_inventory")
        if not isinstance(exact, Mapping):
            complete = False
            raw_citations = data.get("citations", ())
            if isinstance(raw_citations, Sequence) and not isinstance(raw_citations, (str, bytes)):
                citations.update(item for item in raw_citations if isinstance(item, str))
            answer = data.get("answer")
            if isinstance(answer, Mapping) and isinstance(answer.get("text"), str):
                answers.append(answer["text"])
            continue
        complete &= exact.get("coverage_status") == "complete"
        for item in exact.get("items", ()):
            if not isinstance(item, Mapping):
                continue
            row_number += 1
            item_citations = {
                reference["citation_hash"]
                for reference in item.get("governed_references", ())
                if isinstance(reference, Mapping)
                and isinstance(reference.get("citation_hash"), str)
            }
            item_values: list[str] = []
            for value in item.get("structured_values", ()):
                if (
                    isinstance(value, Mapping)
                    and isinstance(value.get("field"), str)
                    and isinstance(value.get("value"), str)
                ):
                    item_values.append(f"{value['field']}: {value['value']}")
                    citation = value.get("citation_hash")
                    if isinstance(citation, str):
                        item_citations.add(citation)
            if item_values and item_citations:
                answers.append(f"來源列 {row_number}\n" + "\n".join(item_values))
                citations.update(item_citations)
            elif item_values:
                complete = False
    answer_text = "\n".join(dict.fromkeys(answers))
    if answer_text and citations:
        return {
            "status": "complete" if complete else "partial",
            "answer": answer_text,
            "citations": sorted(citations),
            "clarification": (
                None if complete else "目前只有部分經授權且可引用的來源證據，請縮小問題範圍。"
            ),
        }
    return {
        "status": "clarification_required",
        "answer": "",
        "citations": [],
        "clarification": "請補充要查詢的實體與來源欄位。",
    }


async def create_issue56_uat_query_service(
    environment: Mapping[str, str] | None = None,
    *,
    http_client: Any | None = None,
) -> Issue56UatQueryService:
    """Compose the existing zero-argument production runtime."""

    resolved = dict(os.environ if environment is None else environment)
    bearer = resolved.get(_BEARER_ENV)
    if not bearer:
        raise RuntimeError("issue56_uat_bearer_required")
    config = ConnectedRuntimeConfig.from_env_and_secrets(resolved)
    runtime = await ConnectedRuntime.compose(config, http_client=http_client)
    return Issue56UatQueryService(runtime, bearer_token=bearer)
