#!/usr/bin/env python3
"""Verify the diagnostic browser response without exposing answer evidence."""

from __future__ import annotations

import argparse
from collections.abc import Iterator, Mapping
import hashlib
import json
from pathlib import Path
import re
import secrets
import tempfile
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
import unicodedata

EXPECTED_RETRIEVAL_PATH = "mail_authorized_structured_set"
EXPECTED_FINGERPRINT = "sha256:d791cfcd424910ed766f4092b51c6a9c1f1b756943935544134e626301e7c705"
DEFAULT_QUERY = "把COO是日本的料號取出"
EXPECTED_BULLET_COUNT = 77
MAX_NON_BULLET_LINES = 2
MAX_NON_BULLET_CHARACTERS = 160

_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.+?)\s*$")
_BULLET_MARKER_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])(?:\s|$)")
_MARKDOWN_TABLE_RULE_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$")
_MARKDOWN_TABLE_ROW_RE = re.compile(
    r"^\s*\|?\s*[^|\n]+\s*\|\s*[^|\n]+(?:\s*\|\s*[^|\n]+)*\s*\|?\s*$"
)
_SOURCE_HEADING_RE = re.compile(
    r"^\s*(?:sources?|citations?|references?|來源|參考來源|引用|證據來源)\s*[:：]?\s*$",
    re.IGNORECASE,
)
_SOURCE_OR_CITATION_DUMP_RE = re.compile(
    r"(?:"
    r"(?:^|\s)(?:source|citation|reference|evidence)"
    r"(?:[\s_.-]+(?:id|ids|ref|refs|url|urls|uri|uris|handle|handles|"
    r"locator|locators|count|counts|"
    r"(?:observation|observations|message|messages|snapshot|snapshots)"
    r"(?:[\s_.-]+(?:id|ids|ref|refs))?))?\s*[:=：]"
    r"|\[(?:source|citation|reference|evidence)\b[^\]]*\]"
    r"|(?:^|\s)\[\^?\d+(?:\s*,\s*\^?\d+)*\](?=\s|$)"
    r"|\b(?:https?|file)://"
    r"|(?:來源|參考來源|引用|證據來源|證據)\s*[:：=]"
    r")",
    re.IGNORECASE,
)
_RAW_DUMP_RE = re.compile(
    r"(?:structuredContent|complete_projection|citation_handles|"
    r"source_observation_id|email_message_id|retrieval_trace|"
    r"mcp_call_count|retrieval_path|source_count)",
    re.IGNORECASE,
)
_RAW_STRUCTURED_DUMP_RE = re.compile(r"^\s*(?:\{\s*(?:[\"']|\})|\[\s*(?:\{|[\"'\d]|\]))")
_RAW_STRUCTURAL_DELIMITER_RE = re.compile(r"^\s*(?:[{}\[\]])\s*$")
_MARKDOWN_CODE_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")
_PLACEHOLDER_RE = re.compile(
    r"^(?:n[./ ]?a|none|null|unknown|tbd|placeholder|not available|"
    r"not found|未提供|未知|待確認|省略)$",
    re.IGNORECASE,
)
_CONTINUATION_RE = re.compile(
    r"^(?:\(?continued\)?|continuation|cont(?:inued)?\.?|to be continued|"
    r"see (?:above|below)|(?:and )?more|etc\.?|未完|續)$",
    re.IGNORECASE,
)
_TRUNCATION_RE = re.compile(r"(?:…|\.{2,})")
_CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_HTML_TAG_RE = re.compile(r"</?[a-z][^>]*>", re.IGNORECASE)


class VerificationFailure(RuntimeError):
    """A safe, non-evidence-bearing browser-contract failure."""


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--health-path", default="/api/health")
    parser.add_argument("--summary-path", default="/api/session-summary")
    parser.add_argument("--query-path", default="/api/chat")
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--expected-fingerprint", default=EXPECTED_FINGERPRINT)
    parser.add_argument("--expected-count", type=int, default=EXPECTED_BULLET_COUNT)
    return parser


def _safe_url(base_url: str, path: str) -> str:
    parsed_base = urlparse(base_url)
    if parsed_base.scheme not in {"http", "https"} or not parsed_base.netloc:
        raise VerificationFailure("base URL is invalid")
    if not isinstance(path, str) or not path.startswith("/"):
        raise VerificationFailure("endpoint path is invalid")
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def _request_json(
    url: str,
    body: dict[str, str] | None = None,
    *,
    timeout_seconds: float = 30,
) -> dict[str, Any]:
    request_body = None
    headers: dict[str, str] = {"Accept": "application/json"}
    if body is not None:
        request_body = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=request_body, headers=headers, method="POST" if body else "GET")
    try:
        with urlopen(  # noqa: S310 - supplied diagnostic URL
            request,
            timeout=timeout_seconds,
        ) as response:
            if response.status != 200:
                raise VerificationFailure("browser endpoint did not return success")
            raw_response = response.read()
    except (HTTPError, URLError, TimeoutError) as error:
        raise VerificationFailure("browser endpoint is unavailable") from error
    try:
        payload = json.loads(raw_response.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VerificationFailure("browser endpoint returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise VerificationFailure("browser endpoint returned an invalid response")
    return payload


def _mappings(value: Any) -> Iterator[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for nested in value.values():
            yield from _mappings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _mappings(nested)


def _find_metadata(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    trace = payload.get("trace")
    orchestration = payload.get("orchestration")
    if (
        not isinstance(trace, Mapping)
        or trace.get("retrieval_path") != EXPECTED_RETRIEVAL_PATH
        or type(trace.get("mcp_call_count")) is not int
        or trace.get("mcp_call_count") != 1
        or payload.get("claim_state") != "CANDIDATE_MATCHES"
        or payload.get("canonical_kg") is not False
        or type(payload.get("source_count")) is not int
        or payload.get("source_count") != 0
        or type(payload.get("citation_count")) is not int
        or payload.get("citation_count") != 0
        or not isinstance(orchestration, Mapping)
        or orchestration.get("action") != "call_formowl_tool"
        or orchestration.get("response_kind") != "answer"
        or orchestration.get("formowl_tool_called") is not True
        or not isinstance(orchestration.get("model"), str)
        or not orchestration["model"].strip()
    ):
        raise VerificationFailure("browser response lacks the required diagnostic metadata")
    return trace


def _summary_counts(payload: Mapping[str, Any]) -> tuple[int, int]:
    chat_count = payload.get("chat_count")
    tool_count = payload.get("formowl_tool_call_count")
    if (
        payload.get("status") != "ready"
        or type(chat_count) is not int
        or chat_count < 0
        or type(tool_count) is not int
        or tool_count < 0
    ):
        raise VerificationFailure("browser session summary is invalid")
    return chat_count, tool_count


def _answer_text(payload: Mapping[str, Any]) -> str:
    assistant_text = payload.get("assistant_text")
    if isinstance(assistant_text, str):
        return assistant_text
    direct_answer = payload.get("answer")
    if isinstance(direct_answer, str):
        return direct_answer
    for key in ("message", "response", "result"):
        candidate = payload.get(key)
        if isinstance(candidate, Mapping):
            for content_key in ("content", "text", "answer"):
                content = candidate.get(content_key)
                if isinstance(content, str):
                    return content
    raise VerificationFailure("browser response has no answer text")


def _normalized_bullet(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _display_value(value: str) -> str:
    stripped = value.strip()
    while True:
        previous = stripped
        if len(stripped) >= 2 and stripped[0] == stripped[-1] == "`":
            stripped = stripped[1:-1].strip()
        for marker in ("**", "__", "~~", "*", "_"):
            if (
                len(stripped) > 2 * len(marker)
                and stripped.startswith(marker)
                and stripped.endswith(marker)
            ):
                stripped = stripped[len(marker) : -len(marker)].strip()
                break
        if stripped == previous:
            break
    return stripped


def _contains_markdown_table(lines: list[str]) -> bool:
    consecutive_rows = 0
    for line in lines:
        if _MARKDOWN_TABLE_RULE_RE.match(line):
            return True
        if _MARKDOWN_TABLE_ROW_RE.match(line):
            consecutive_rows += 1
            if consecutive_rows >= 2:
                return True
        elif line.strip():
            consecutive_rows = 0
    return False


def _validate_answer_surface(answer: str) -> None:
    lines = answer.splitlines()
    bullet_indexes = [index for index, line in enumerate(lines) if _BULLET_RE.match(line)]
    if not bullet_indexes:
        raise VerificationFailure("browser answer has no readable bullets")
    if _contains_markdown_table(lines):
        raise VerificationFailure("browser answer contains a markdown table wall")
    if any(_SOURCE_HEADING_RE.match(line) for line in lines):
        raise VerificationFailure("browser answer contains sources or citations")
    if any(_SOURCE_OR_CITATION_DUMP_RE.search(line) for line in lines):
        raise VerificationFailure("browser answer contains sources or citations")
    if any(_RAW_DUMP_RE.search(line) for line in lines):
        raise VerificationFailure("browser answer contains a raw diagnostic dump")
    if any(
        _RAW_STRUCTURED_DUMP_RE.match(line)
        or _RAW_STRUCTURAL_DELIMITER_RE.match(line)
        or _MARKDOWN_CODE_FENCE_RE.match(line)
        for line in lines
    ):
        raise VerificationFailure("browser answer contains a raw structured dump")
    non_bullet_lines = [
        line.strip() for line in lines if line.strip() and not _BULLET_RE.match(line)
    ]
    if (
        len(non_bullet_lines) > MAX_NON_BULLET_LINES
        or sum(len(line) for line in non_bullet_lines) > MAX_NON_BULLET_CHARACTERS
    ):
        raise VerificationFailure("browser answer contains excessive non-bullet prose")


def _validate_bullet_value(value: str) -> str:
    bullet = _display_value(value)
    normalized = _normalized_bullet(bullet)
    if not normalized:
        raise VerificationFailure("browser answer contains an empty or malformed bullet")
    if (
        _RAW_STRUCTURED_DUMP_RE.match(bullet)
        or _RAW_STRUCTURAL_DELIMITER_RE.match(bullet)
        or _MARKDOWN_CODE_FENCE_RE.match(bullet)
    ):
        raise VerificationFailure("browser answer contains a raw structured dump")
    if (
        len(bullet) > 240
        or "|" in bullet
        or "\t" in bullet
        or _CONTROL_CHARACTER_RE.search(bullet)
        or _HTML_TAG_RE.search(bullet)
        or _TRUNCATION_RE.search(bullet)
        or _PLACEHOLDER_RE.fullmatch(normalized)
        or _CONTINUATION_RE.fullmatch(normalized)
    ):
        raise VerificationFailure("browser answer contains a placeholder or truncated bullet")
    if not any(character.isalnum() for character in bullet):
        raise VerificationFailure("browser answer contains an empty or malformed bullet")
    return bullet


def _distinct_bullets(answer: str, *, expected_count: int) -> tuple[str, ...]:
    _validate_answer_surface(answer)
    if (
        not isinstance(expected_count, int)
        or isinstance(expected_count, bool)
        or expected_count < 1
    ):
        raise VerificationFailure("expected bullet count is invalid")
    values: list[str] = []
    seen: set[str] = set()
    for line in answer.splitlines():
        match = _BULLET_RE.match(line)
        if match is None:
            if _BULLET_MARKER_RE.match(line):
                raise VerificationFailure("browser answer contains an empty or malformed bullet")
            continue
        bullet = _validate_bullet_value(match.group(1))
        normalized = _normalized_bullet(bullet)
        if normalized in seen:
            raise VerificationFailure("browser answer contains duplicate bullets")
        seen.add(normalized)
        values.append(bullet)
    if len(values) != expected_count:
        raise VerificationFailure("browser answer bullet count does not match")
    return tuple(values)


def _projection_fingerprint(values: tuple[str, ...]) -> str:
    encoded = json.dumps(
        [[value] for value in values],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _write_report(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary.write(encoded)
        temporary.flush()
        temporary_path = Path(temporary.name)
    temporary_path.chmod(0o600)
    temporary_path.replace(path)
    path.chmod(0o600)


def verify_browser_contract(
    *,
    base_url: str,
    health_path: str,
    summary_path: str,
    query_path: str,
    query: str,
    expected_fingerprint: str,
    expected_count: int,
) -> dict[str, Any]:
    if not isinstance(query, str) or not query.strip():
        raise VerificationFailure("query is invalid")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_fingerprint):
        raise VerificationFailure("expected fingerprint is invalid")

    health = _request_json(_safe_url(base_url, health_path), timeout_seconds=10)
    conversation_model = health.get("conversation_model")
    if (
        health.get("status") != "ready"
        or health.get("surface") != "mail_human_uat"
        or health.get("conversation_orchestrator_enabled") is not True
        or not isinstance(conversation_model, str)
        or not conversation_model.strip()
    ):
        raise VerificationFailure("browser health endpoint is not ready")
    before_chat_count, before_tool_count = _summary_counts(
        _request_json(_safe_url(base_url, summary_path), timeout_seconds=10)
    )

    response = _request_json(
        _safe_url(base_url, query_path),
        {
            "query_text": query,
            "visitor_id": "visitor_contract_" + secrets.token_hex(12),
            "session_id": "session_contract_" + secrets.token_hex(12),
        },
        timeout_seconds=390,
    )
    metadata = _find_metadata(response)
    orchestration = response["orchestration"]
    if orchestration["model"] != conversation_model:
        raise VerificationFailure("browser response is not bound to the ready sidecar model")
    after_chat_count, after_tool_count = _summary_counts(
        _request_json(_safe_url(base_url, summary_path), timeout_seconds=10)
    )
    if (
        after_chat_count - before_chat_count != 1
        or after_tool_count - before_tool_count != 1
    ):
        raise VerificationFailure("browser route did not perform exactly one sidecar tool turn")
    bullets = _distinct_bullets(_answer_text(response), expected_count=expected_count)
    observed_fingerprint = _projection_fingerprint(bullets)
    if observed_fingerprint != expected_fingerprint:
        raise VerificationFailure("browser answer fingerprint does not match")
    return {
        "artifact_type": "formowl_browser_diagnostic_contract_v1",
        "status": "passed",
        "query_route": "browser_to_sidecar_to_one_mcp",
        "conversation_model_sha256": "sha256:"
        + hashlib.sha256(conversation_model.encode("utf-8")).hexdigest(),
        "query_sha256": "sha256:" + hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "retrieval_path": metadata["retrieval_path"],
        "mcp_call_count": metadata["mcp_call_count"],
        "chat_count_delta": after_chat_count - before_chat_count,
        "formowl_tool_call_count_delta": after_tool_count - before_tool_count,
        "claim_state": response["claim_state"],
        "canonical_kg": response["canonical_kg"],
        "source_count": response["source_count"],
        "citation_count": response["citation_count"],
        "fingerprint": observed_fingerprint,
        "distinct_projection_count": len(bullets),
        "distinct_bullet_count": len(bullets),
        "human_readability_guards": {
            "no_initial_sources": True,
            "no_citations": True,
            "no_table_wall": True,
            "no_raw_dump": True,
            "no_placeholder_or_truncation": True,
        },
    }


def main() -> int:
    args = _argument_parser().parse_args()
    try:
        report = verify_browser_contract(
            base_url=args.base_url,
            health_path=args.health_path,
            summary_path=args.summary_path,
            query_path=args.query_path,
            query=args.query,
            expected_fingerprint=args.expected_fingerprint,
            expected_count=args.expected_count,
        )
    except VerificationFailure as error:
        _write_report(
            args.report,
            {
                "artifact_type": "formowl_browser_diagnostic_contract_v1",
                "status": "failed",
                "reason": str(error),
            },
        )
        raise SystemExit(1) from error
    _write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
