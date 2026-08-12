#!/usr/bin/env python3
"""Verify the frozen diagnostic browser contract without exposing evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import time
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
import unicodedata

EXPECTED_RETRIEVAL_PATH = "mail_authorized_structured_set"
EXPECTED_CLAIM_STATE = "CANDIDATE_MATCHES"
EXPECTED_FINGERPRINT = "sha256:d791cfcd424910ed766f4092b51c6a9c1f1b756943935544134e626301e7c705"
EXPECTED_ANSWER_ITEM_COUNT = 77
MAX_QUERY_ELAPSED_SECONDS = 360.0
DEFAULT_QUERY = "把COO是日本的料號取出"

_MARKDOWN_TABLE_RULE_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$")
_RAW_STRUCTURED_DUMP_RE = re.compile(r"^\s*(?:\{\s*(?:[\"']|\})|\[\s*(?:\{|[\"'\d]|\]))")
_MARKDOWN_CODE_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")
_PLACEHOLDER_RE = re.compile(
    r"^(?:n[./ ]?a|none|null|unknown|tbd|placeholder|not available|"
    r"not found|omitted|未提供|未知|待確認|省略)$",
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
_NODE_DOM_HARNESS = r"""
import crypto from "node:crypto";
import fs from "node:fs";
import vm from "node:vm";

const [renderPath, payloadPath] = process.argv.slice(2);
const renderSource = fs.readFileSync(renderPath, "utf8");
const payload = JSON.parse(fs.readFileSync(payloadPath, "utf8"));

class FakeElement {
  constructor(tagName = "div") {
    this.tagName = String(tagName).toLowerCase();
    this.children = [];
    this.attributes = new Map();
    this.className = "";
    this.hidden = false;
    this.id = "";
    this.textContent = "";
  }

  addEventListener() {}

  setAttribute(name, value) {
    this.attributes.set(String(name), String(value));
  }

  append(...children) {
    this.children.push(...children);
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  replaceChildren(...children) {
    this.children = [...children];
    this.textContent = "";
  }
}

const document = {
  createElement(tagName) {
    return new FakeElement(tagName);
  },
};
const holder = new FakeElement("div");
const context = vm.createContext({
  Array,
  Boolean,
  Date,
  Intl,
  JSON,
  Map,
  Math,
  Number,
  Object,
  Set,
  String,
  addFeedbackControls() {},
  document,
  formatEvidenceTime() {
    return "time";
  },
  holder,
  openUpload() {},
  payload,
  scrollToLatest() {},
  sourceDisclosureSequence: 0,
  updateSourceReadingMode() {},
});

vm.runInContext(
  `${renderSource}\nrenderAssistantResult(payload, holder);`,
  context,
  { timeout: 5000 },
);

function classTokens(node) {
  return String(node.className || "").split(/\s+/u).filter(Boolean);
}

function walk(node) {
  return [node, ...node.children.flatMap((child) => walk(child))];
}

function textTree(node, excludedClass = null) {
  if (excludedClass && classTokens(node).includes(excludedClass)) return "";
  return [String(node.textContent || ""), ...node.children.map(
    (child) => textTree(child, excludedClass),
  )].join("");
}

function sha256(value) {
  return `sha256:${crypto.createHash("sha256").update(value, "utf8").digest("hex")}`;
}

function containsMarkdownTable(lines) {
  let consecutiveRows = 0;
  for (const line of lines) {
    if (/^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$/u.test(line)) {
      return true;
    }
    if (/^\s*\|?\s*[^|\n]+\s*\|\s*[^|\n]+(?:\s*\|\s*[^|\n]+)*\s*\|?\s*$/u.test(line)) {
      consecutiveRows += 1;
      if (consecutiveRows >= 2) return true;
    } else if (line.trim()) {
      consecutiveRows = 0;
    }
  }
  return false;
}

const elements = walk(holder);
const semanticItems = elements.filter(
  (node) => classTokens(node).includes("semantic-answer-item"),
);
const itemHashes = semanticItems.map(
  (node) => sha256(textTree(node, "semantic-answer-order")),
);
const renderedText = textTree(holder);
const lines = renderedText.split(/\r?\n/u);
const classNames = elements.flatMap((node) => classTokens(node));
const sourceCitationUi = classNames.some(
  (name) => /(?:source|citation|reference|evidence)/iu.test(name),
) || /(?:\b(?:sources?|citations?|references?)\b|來源|參考來源|引用|證據來源)/iu.test(
  renderedText,
);
const rawJson = lines.some(
  (line) => /^\s*(?:\{\s*(?:["']|\})|\[\s*(?:\{|["'\d]|\])|```|~~~)/u.test(line),
) || /(?:structuredContent|answer_items|retrieval_path|claim_state)\s*[:=：]/iu.test(
  renderedText,
);
const tableWall = elements.some((node) => node.tagName === "table")
  || /<table\b/iu.test(renderedText)
  || containsMarkdownTable(lines);

process.stdout.write(JSON.stringify({
  semantic_answer_item_count: semanticItems.length,
  semantic_answer_item_hashes: itemHashes,
  distinct_semantic_answer_item_hash_count: new Set(itemHashes).size,
  source_citation_ui_present: sourceCitationUi,
  raw_json_present: rawJson,
  table_wall_present: tableWall,
}));
"""


class VerificationFailure(RuntimeError):
    """A safe, non-evidence-bearing browser-contract failure."""


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--page-path", default="/")
    parser.add_argument("--summary-path", default="/api/session-summary")
    parser.add_argument("--query-path", default="/api/chat")
    parser.add_argument("--query", default=DEFAULT_QUERY)
    return parser


def _safe_url(base_url: str, path: str) -> str:
    parsed_base = urlparse(base_url)
    if parsed_base.scheme not in {"http", "https"} or not parsed_base.netloc:
        raise VerificationFailure("base URL is invalid")
    if not isinstance(path, str) or not path.startswith("/"):
        raise VerificationFailure("endpoint path is invalid")
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def _same_origin(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise VerificationFailure("request URL is invalid")
    return f"{parsed.scheme}://{parsed.netloc}"


def _request_bytes(
    url: str,
    *,
    accept: str,
    body: Mapping[str, Any] | None = None,
    timeout_seconds: float,
) -> bytes:
    request_body = None
    headers = {"Accept": accept}
    if body is not None:
        request_body = json.dumps(
            dict(body),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        headers["Content-Type"] = "application/json"
        headers["Origin"] = _same_origin(url)
    request = Request(
        url,
        data=request_body,
        headers=headers,
        method="POST" if body is not None else "GET",
    )
    try:
        with urlopen(  # noqa: S310 - supplied diagnostic URL
            request,
            timeout=timeout_seconds,
        ) as response:
            if response.status != 200:
                raise VerificationFailure("browser endpoint did not return success")
            return response.read()
    except (HTTPError, URLError, TimeoutError) as error:
        raise VerificationFailure("browser endpoint is unavailable") from error


def _request_json(
    url: str,
    body: Mapping[str, Any] | None = None,
    *,
    timeout_seconds: float = 30,
) -> dict[str, Any]:
    raw_response = _request_bytes(
        url,
        accept="application/json",
        body=body,
        timeout_seconds=timeout_seconds,
    )
    try:
        payload = json.loads(raw_response.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VerificationFailure("browser endpoint returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise VerificationFailure("browser endpoint returned an invalid response")
    return payload


def _request_text(url: str, *, timeout_seconds: float = 30) -> str:
    raw_response = _request_bytes(
        url,
        accept="text/html",
        timeout_seconds=timeout_seconds,
    )
    try:
        return raw_response.decode("utf-8")
    except UnicodeDecodeError as error:
        raise VerificationFailure("browser page is not UTF-8") from error


def _summary_tool_count(payload: Mapping[str, Any]) -> int:
    tool_count = payload.get("formowl_tool_call_count")
    if type(tool_count) is not int or tool_count < 0:
        raise VerificationFailure("browser session tool count is invalid")
    return tool_count


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
            return stripped


def _normalized_item(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", _display_value(value)).casefold().split())


def _validate_answer_item(value: Any) -> str:
    if not isinstance(value, str):
        raise VerificationFailure("browser response contains a non-text answer item")
    display = _display_value(value)
    normalized = _normalized_item(value)
    if not normalized or not any(character.isalnum() for character in display):
        raise VerificationFailure("browser response contains an empty answer item")
    if (
        "\n" in value
        or "\r" in value
        or "\t" in value
        or "|" in value
        or _CONTROL_CHARACTER_RE.search(value)
        or _HTML_TAG_RE.search(value)
        or _MARKDOWN_CODE_FENCE_RE.match(display)
        or _MARKDOWN_TABLE_RULE_RE.match(display)
        or _RAW_STRUCTURED_DUMP_RE.match(display)
    ):
        raise VerificationFailure("browser response contains a raw or table-shaped answer item")
    if (
        _TRUNCATION_RE.search(display)
        or _PLACEHOLDER_RE.fullmatch(normalized)
        or _CONTINUATION_RE.fullmatch(normalized)
    ):
        raise VerificationFailure(
            "browser response contains a placeholder or truncated answer item"
        )
    return value


def _answer_items(
    payload: Mapping[str, Any],
    *,
    expected_count: int,
) -> tuple[str, ...]:
    values = payload.get("answer_items")
    if not isinstance(values, list):
        raise VerificationFailure("browser response answer_items is invalid")
    if len(values) != expected_count:
        raise VerificationFailure("browser response answer item count does not match")
    checked = tuple(_validate_answer_item(value) for value in values)
    normalized = [_normalized_item(value) for value in checked]
    if len(set(normalized)) != len(normalized):
        raise VerificationFailure("browser response contains duplicate answer items")
    return checked


def _validate_response_contract(payload: Mapping[str, Any]) -> None:
    if payload.get("results") != []:
        raise VerificationFailure("browser response results must be empty")
    if payload.get("retrieval_path") != EXPECTED_RETRIEVAL_PATH:
        raise VerificationFailure("browser response retrieval path does not match")
    if payload.get("claim_state") != EXPECTED_CLAIM_STATE:
        raise VerificationFailure("browser response claim state does not match")
    if payload.get("canonical_kg") is not False:
        raise VerificationFailure("browser response canonical KG boundary does not match")


def _projection_fingerprint(values: tuple[str, ...]) -> str:
    encoded = json.dumps(
        [[value] for value in values],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _item_hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _extract_render_function(page_html: str) -> str:
    match = re.search(
        r"\bfunction\s+renderAssistantResult\s*\(\s*payload\s*,\s*holder\s*\)\s*\{",
        page_html,
    )
    if match is None:
        raise VerificationFailure("browser page lacks renderAssistantResult")
    opening_brace = page_html.find("{", match.start())
    depth = 0
    state = "code"
    escaped = False
    index = opening_brace
    while index < len(page_html):
        character = page_html[index]
        following = page_html[index + 1] if index + 1 < len(page_html) else ""
        if state in {"single", "double", "template"}:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif (
                (state == "single" and character == "'")
                or (state == "double" and character == '"')
                or (state == "template" and character == "`")
            ):
                state = "code"
        elif state == "line_comment":
            if character in "\r\n":
                state = "code"
        elif state == "block_comment":
            if character == "*" and following == "/":
                state = "code"
                index += 1
        elif character == "/" and following == "/":
            state = "line_comment"
            index += 1
        elif character == "/" and following == "*":
            state = "block_comment"
            index += 1
        elif character == "'":
            state = "single"
        elif character == '"':
            state = "double"
        elif character == "`":
            state = "template"
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return page_html[match.start() : index + 1]
        index += 1
    raise VerificationFailure("browser page renderAssistantResult is malformed")


def _render_browser_dom(
    page_html: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    render_source = _extract_render_function(page_html)
    node_path = shutil.which("node")
    if node_path is None:
        raise VerificationFailure("browser DOM verifier requires Node.js")
    with tempfile.TemporaryDirectory(prefix="formowl-browser-contract-") as temporary:
        root = Path(temporary)
        render_path = root / "render.js"
        payload_path = root / "payload.json"
        harness_path = root / "harness.mjs"
        render_path.write_text(render_source, encoding="utf-8")
        payload_path.write_text(
            json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        harness_path.write_text(_NODE_DOM_HARNESS, encoding="utf-8")
        for path in (render_path, payload_path, harness_path):
            path.chmod(0o600)
        try:
            completed = subprocess.run(  # noqa: S603 - fixed Node executable and local files
                [node_path, str(harness_path), str(render_path), str(payload_path)],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except subprocess.TimeoutExpired as error:
            raise VerificationFailure("browser DOM rendering timed out") from error
    if completed.returncode != 0:
        raise VerificationFailure("browser DOM rendering failed")
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise VerificationFailure("browser DOM verifier returned invalid output") from error
    if not isinstance(report, dict):
        raise VerificationFailure("browser DOM verifier returned an invalid report")
    return report


def _validate_dom_contract(
    report: Mapping[str, Any],
    *,
    answer_items: tuple[str, ...],
) -> None:
    expected_hashes = [_item_hash(value) for value in answer_items]
    if report.get("semantic_answer_item_count") != len(answer_items):
        raise VerificationFailure("browser DOM semantic answer item count does not match")
    if report.get("semantic_answer_item_hashes") != expected_hashes:
        raise VerificationFailure("browser DOM semantic answer items do not match the response")
    if report.get("distinct_semantic_answer_item_hash_count") != len(answer_items):
        raise VerificationFailure("browser DOM contains duplicate semantic answer items")
    if report.get("source_citation_ui_present") is not False:
        raise VerificationFailure("browser DOM initially exposes source or citation UI")
    if report.get("raw_json_present") is not False:
        raise VerificationFailure("browser DOM initially exposes raw JSON")
    if report.get("table_wall_present") is not False:
        raise VerificationFailure("browser DOM initially exposes a table wall")


def _write_report(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
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
    page_path: str,
    summary_path: str,
    query_path: str,
    query: str,
    expected_fingerprint: str = EXPECTED_FINGERPRINT,
    expected_count: int = EXPECTED_ANSWER_ITEM_COUNT,
) -> dict[str, Any]:
    if not isinstance(query, str) or not query.strip():
        raise VerificationFailure("query is invalid")
    if (
        type(expected_count) is not int
        or expected_count < 1
        or re.fullmatch(r"sha256:[0-9a-f]{64}", expected_fingerprint) is None
    ):
        raise VerificationFailure("frozen expectation is invalid")

    page_html = _request_text(_safe_url(base_url, page_path), timeout_seconds=10)
    before_tool_count = _summary_tool_count(
        _request_json(_safe_url(base_url, summary_path), timeout_seconds=10)
    )
    query_started = time.monotonic()
    response = _request_json(
        _safe_url(base_url, query_path),
        {
            "query_text": query,
            "visitor_id": "uatvisitor_" + secrets.token_hex(16),
            "session_id": "uatsession_" + secrets.token_hex(16),
            "sequence": 1,
            "source": "composer",
        },
        timeout_seconds=MAX_QUERY_ELAPSED_SECONDS,
    )
    query_elapsed_seconds = time.monotonic() - query_started
    if not 0 <= query_elapsed_seconds < MAX_QUERY_ELAPSED_SECONDS:
        raise VerificationFailure("browser query exceeded the 360-second limit")
    after_tool_count = _summary_tool_count(
        _request_json(_safe_url(base_url, summary_path), timeout_seconds=10)
    )
    if after_tool_count - before_tool_count != 1:
        raise VerificationFailure("browser session did not record exactly one FormOwl tool call")

    _validate_response_contract(response)
    answer_items = _answer_items(response, expected_count=expected_count)
    observed_fingerprint = _projection_fingerprint(answer_items)
    if observed_fingerprint != expected_fingerprint:
        raise VerificationFailure("browser answer fingerprint does not match")
    dom_report = _render_browser_dom(page_html, response)
    _validate_dom_contract(dom_report, answer_items=answer_items)

    return {
        "artifact_type": "formowl_browser_diagnostic_contract_v2",
        "status": "passed",
        "query_route": "browser_to_sidecar_to_one_mcp",
        "query_sha256": "sha256:" + hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "retrieval_path": response["retrieval_path"],
        "claim_state": response["claim_state"],
        "canonical_kg": response["canonical_kg"],
        "results_count": 0,
        "query_elapsed_ms": round(query_elapsed_seconds * 1000, 3),
        "formowl_tool_call_count_delta": after_tool_count - before_tool_count,
        "fingerprint": observed_fingerprint,
        "answer_item_count": len(answer_items),
        "dom_semantic_answer_item_count": dom_report["semantic_answer_item_count"],
        "human_readability_guards": {
            "no_initial_sources_or_citations": True,
            "no_raw_json": True,
            "no_table_wall": True,
            "no_placeholder_duplicate_empty_or_truncation": True,
        },
    }


def main() -> int:
    args = _argument_parser().parse_args()
    try:
        report = verify_browser_contract(
            base_url=args.base_url,
            page_path=args.page_path,
            summary_path=args.summary_path,
            query_path=args.query_path,
            query=args.query,
        )
    except VerificationFailure as error:
        _write_report(
            args.report,
            {
                "artifact_type": "formowl_browser_diagnostic_contract_v2",
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
