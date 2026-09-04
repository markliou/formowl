from __future__ import annotations

from collections.abc import Mapping, Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from typing import Any, Protocol
from urllib.parse import urlparse

_MAX_REQUEST_BYTES = 64 * 1024
_MAX_PROMPT_CHARS = 8_000


class MailHumanUatQueryService(Protocol):
    def ask(self, prompt: str) -> Mapping[str, Any]: ...


def create_mail_human_uat_http_server(
    host: str,
    port: int,
    query_service: MailHumanUatQueryService,
) -> ThreadingHTTPServer:
    """Create the minimal same-origin browser UAT surface."""

    return ThreadingHTTPServer(
        (host, port),
        _build_mail_human_uat_http_handler(query_service),
    )


def _build_mail_human_uat_http_handler(
    query_service: MailHumanUatQueryService,
) -> type[BaseHTTPRequestHandler]:
    class MailHumanUatHttpHandler(BaseHTTPRequestHandler):
        server_version = "FormOwlMailHumanUAT/0.1"

        def do_GET(self) -> None:  # noqa: N802
            route = urlparse(self.path).path
            if route == "/":
                self._send_html(HTTPStatus.OK, _PAGE)
                return
            if route == "/api/health":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "status": "ok",
                        "service": "mail_human_uat_http",
                        "query_service_connected": True,
                    },
                )
                return
            self._send_error(HTTPStatus.NOT_FOUND, "route_not_found")

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/api/chat":
                self._send_error(HTTPStatus.NOT_FOUND, "route_not_found")
                return
            if not self._same_origin_allowed():
                self._send_error(HTTPStatus.FORBIDDEN, "same_origin_required")
                return
            try:
                payload = self._read_json()
                prompt = payload.get("prompt")
                if (
                    not isinstance(prompt, str)
                    or not prompt.strip()
                    or len(prompt) > _MAX_PROMPT_CHARS
                ):
                    raise ValueError("invalid prompt")
                response = _normalize_query_response(query_service.ask(prompt))
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError):
                self._send_error(HTTPStatus.BAD_REQUEST, "request_rejected")
                return
            except Exception:
                self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "query_failed")
                return
            self._send_json(HTTPStatus.OK, response)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _same_origin_allowed(self) -> bool:
            origins = self.headers.get_all("Origin")
            hosts = self.headers.get_all("Host")
            if not origins or len(origins) != 1 or not hosts or len(hosts) != 1:
                return False
            origin = urlparse(origins[0].strip())
            return (
                origin.scheme.lower() in {"http", "https"}
                and origin.netloc.casefold() == hosts[0].strip().casefold()
                and not origin.path
                and not origin.params
                and not origin.query
                and not origin.fragment
                and not origin.username
                and not origin.password
            )

        def _read_json(self) -> dict[str, Any]:
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != (
                "application/json"
            ):
                raise ValueError("invalid content type")
            value = self.headers.get("Content-Length")
            if value is None or not value.isdigit():
                raise ValueError("missing content length")
            length = int(value)
            if length <= 0 or length > _MAX_REQUEST_BYTES:
                raise ValueError("invalid content length")
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("incomplete body")
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("invalid payload")
            return payload

        def _send_error(self, status: HTTPStatus, error_code: str) -> None:
            self._send_json(
                status,
                {
                    "status": "error",
                    "error_code": error_code,
                    "http_status_code": int(status),
                },
            )

        def _send_html(self, status: HTTPStatus, body: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(status)
            self._send_common_headers("text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_json(self, status: HTTPStatus, payload: Mapping[str, Any]) -> None:
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self._send_common_headers("application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_common_headers(self, content_type: str) -> None:
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; connect-src 'self'; "
                "base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
            )

    return MailHumanUatHttpHandler


def _normalize_query_response(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("query response must be a mapping")
    status = _optional_text(value.get("status"), default="complete")
    answer = _optional_text(value.get("answer"), default="")
    clarification_value = value.get("clarification")
    clarification = (
        None if clarification_value is None else _optional_text(clarification_value, default="")
    )
    citation_values = value.get("citations", ())
    if isinstance(citation_values, (str, bytes)) or not isinstance(citation_values, Sequence):
        raise TypeError("citations must be a sequence")
    citations: list[str] = []
    for citation in citation_values:
        if isinstance(citation, str):
            label = citation
        elif isinstance(citation, Mapping):
            label = citation.get("label")
            if not isinstance(label, str):
                raise TypeError("citation label must be text")
        else:
            raise TypeError("citation must be text or a mapping")
        if label.strip():
            citations.append(label)
    return {
        "status": status,
        "answer": answer,
        "citations": citations,
        "citation_count": len(citations),
        "clarification": clarification,
    }


def _optional_text(value: Any, *, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise TypeError("response text must be a string")
    return value


_PAGE = """<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FormOwl UAT</title>
  <style>
    :root { color-scheme: light; --ink: #171717; --muted: #6b7280; --line: #dedede; }
    * { box-sizing: border-box; }
    body {
      margin: 0; min-height: 100vh; background: #fafafa; color: var(--ink);
      font-family: ui-sans-serif, system-ui, "Noto Sans TC", sans-serif;
    }
    main { width: min(760px, calc(100% - 32px)); margin: 0 auto; padding: 48px 0; }
    h1 { margin: 0 0 8px; }
    .muted { color: var(--muted); }
    form, article {
      margin-top: 24px; padding: 20px; border: 1px solid var(--line);
      border-radius: 16px; background: white;
    }
    textarea {
      width: 100%; min-height: 112px; padding: 12px; border: 1px solid var(--line);
      border-radius: 10px; resize: vertical; font: inherit;
    }
    button {
      margin-top: 12px; padding: 10px 18px; border: 0; border-radius: 999px;
      background: var(--ink); color: white; font: inherit; cursor: pointer;
    }
    button:disabled { opacity: .45; cursor: wait; }
    [hidden] { display: none !important; }
    #submitted-prompt, #answer-text, #clarification-text { white-space: pre-wrap; }
    #loading-state { margin-top: 16px; }
    #clarification-panel { border-color: #d9a400; background: #fffdf2; }
    #error-text { color: #b42318; }
  </style>
</head>
<body>
  <main>
    <h1>FormOwl</h1>
    <div id="health-status" class="muted" role="status">檢查服務中…</div>
    <form id="chat-form">
      <label for="prompt-input"><strong>問題</strong></label>
      <textarea id="prompt-input" name="prompt" required></textarea>
      <button id="send-button" type="submit">送出</button>
    </form>
    <article id="prompt-panel" hidden>
      <strong>你的問題</strong>
      <div id="submitted-prompt"></div>
    </article>
    <div id="loading-state" role="status" aria-live="polite" hidden>FormOwl 查詢中…</div>
    <article id="answer-panel" hidden>
      <strong>回答</strong>
      <div id="answer-text"></div>
    </article>
    <article id="citation-panel" hidden>
      <strong id="citation-summary">引用 0 則</strong>
      <ul id="citation-list"></ul>
    </article>
    <article id="clarification-panel" hidden>
      <strong>需要釐清</strong>
      <div id="clarification-text"></div>
    </article>
    <p id="error-text" role="alert" hidden>查詢失敗，請稍後再試。</p>
  </main>
  <script>
    const form = document.getElementById("chat-form");
    const input = document.getElementById("prompt-input");
    const send = document.getElementById("send-button");
    const loading = document.getElementById("loading-state");

    function setBusy(busy) {
      send.disabled = busy;
      input.disabled = busy;
      loading.hidden = !busy;
    }

    function resetResult() {
      for (const id of ["answer-panel", "citation-panel", "clarification-panel", "error-text"]) {
        document.getElementById(id).hidden = true;
      }
      document.getElementById("citation-list").replaceChildren();
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const prompt = input.value;
      if (!prompt.trim()) return;
      resetResult();
      document.getElementById("submitted-prompt").textContent = prompt;
      document.getElementById("prompt-panel").hidden = false;
      setBusy(true);
      try {
        const response = await fetch("/api/chat", {
          method: "POST",
          cache: "no-store",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt })
        });
        if (!response.ok) throw new Error("request_failed");
        const payload = await response.json();
        if (payload.answer) {
          document.getElementById("answer-text").textContent = payload.answer;
          document.getElementById("answer-panel").hidden = false;
        }
        const citations = Array.isArray(payload.citations) ? payload.citations : [];
        document.getElementById("citation-summary").textContent =
          `引用 ${payload.citation_count || citations.length} 則`;
        for (const citation of citations) {
          const item = document.createElement("li");
          item.textContent = citation;
          document.getElementById("citation-list").appendChild(item);
        }
        document.getElementById("citation-panel").hidden = citations.length === 0;
        if (payload.clarification) {
          document.getElementById("clarification-text").textContent = payload.clarification;
          document.getElementById("clarification-panel").hidden = false;
        }
      } catch (_) {
        document.getElementById("error-text").hidden = false;
      } finally {
        setBusy(false);
      }
    });

    fetch("/api/health", { cache: "no-store" })
      .then((response) => response.json())
      .then((payload) => {
        document.getElementById("health-status").textContent =
          payload.status === "ok" ? "服務已連線" : "服務未就緒";
      })
      .catch(() => {
        document.getElementById("health-status").textContent = "服務未就緒";
      });
  </script>
</body>
</html>
"""
