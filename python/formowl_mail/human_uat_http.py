from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping, Sequence
from http.cookies import SimpleCookie
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
from typing import Any, Protocol
from urllib.parse import parse_qs, urlparse

_MAX_REQUEST_BYTES = 64 * 1024
_MAX_PROMPT_CHARS = 8_000
_PRE_AUTH_COOKIE = "formowl_uat_pre_auth"
_SESSION_COOKIE = "formowl_uat_session"
_TEMPORARY_BASIC_USERNAME = b"formowl-uat"
_TEMPORARY_BASIC_CHALLENGE = 'Basic realm="FormOwl temporary UAT", charset="UTF-8"'


class MailHumanUatQueryService(Protocol):
    secure_cookie: bool

    def begin_browser_authorization(self) -> tuple[str, str, int]: ...

    def complete_browser_authorization(
        self,
        *,
        state: str,
        code: str,
        browser_nonce: str | None,
    ) -> tuple[str, int]: ...

    def is_browser_session_authenticated(self, session_id: str | None) -> bool: ...

    def logout_browser_session(self, session_id: str | None) -> None: ...

    def ask(
        self,
        prompt: str,
        *,
        session_id: str | None,
    ) -> Mapping[str, Any]: ...


def create_mail_human_uat_http_server(
    host: str,
    port: int,
    query_service: MailHumanUatQueryService,
    *,
    temporary_access_code: str | None = None,
) -> ThreadingHTTPServer:
    """Create the minimal same-origin browser UAT surface."""

    if temporary_access_code is not None and (
        not isinstance(temporary_access_code, str) or not temporary_access_code
    ):
        raise ValueError("temporary access code must be non-empty text")
    return ThreadingHTTPServer(
        (host, port),
        _build_mail_human_uat_http_handler(
            query_service,
            temporary_access_code=temporary_access_code,
        ),
    )


def _build_mail_human_uat_http_handler(
    query_service: MailHumanUatQueryService,
    *,
    temporary_access_code: str | None,
) -> type[BaseHTTPRequestHandler]:
    expected_basic_password = (
        temporary_access_code.encode("utf-8") if temporary_access_code is not None else None
    )

    class MailHumanUatHttpHandler(BaseHTTPRequestHandler):
        server_version = "FormOwlMailHumanUAT/0.1"

        def do_GET(self) -> None:  # noqa: N802
            if not self._basic_access_allowed():
                self._send_basic_auth_required()
                return
            parsed = urlparse(self.path)
            route = parsed.path
            if route == "/":
                authenticated = query_service.is_browser_session_authenticated(self._session_id())
                self._send_html(HTTPStatus.OK, _render_page(authenticated))
                return
            if route == "/auth/start":
                try:
                    location, browser_nonce, max_age = query_service.begin_browser_authorization()
                except Exception:
                    self._send_error(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        "auth_start_failed",
                    )
                    return
                self._send_redirect(
                    HTTPStatus.FOUND,
                    location,
                    set_cookies=(
                        _browser_cookie(
                            _PRE_AUTH_COOKIE,
                            browser_nonce,
                            max_age=max_age,
                            secure=query_service.secure_cookie,
                        ),
                    ),
                )
                return
            if route == "/auth/callback":
                try:
                    parameters = parse_qs(
                        parsed.query,
                        keep_blank_values=True,
                        strict_parsing=True,
                    )
                    if set(parameters) != {"state", "code"} or any(
                        len(values) != 1 or not values[0] for values in parameters.values()
                    ):
                        raise ValueError("invalid callback")
                    session_id, max_age = query_service.complete_browser_authorization(
                        state=parameters["state"][0],
                        code=parameters["code"][0],
                        browser_nonce=self._cookie_value(_PRE_AUTH_COOKIE),
                    )
                except (ValueError, TypeError):
                    self._send_error(
                        HTTPStatus.BAD_REQUEST,
                        "auth_callback_rejected",
                    )
                    return
                except Exception:
                    self._send_error(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        "auth_callback_failed",
                    )
                    return
                self._send_redirect(
                    HTTPStatus.SEE_OTHER,
                    "/",
                    set_cookies=(
                        _browser_cookie(
                            _PRE_AUTH_COOKIE,
                            "",
                            max_age=0,
                            secure=query_service.secure_cookie,
                        ),
                        _browser_cookie(
                            _SESSION_COOKIE,
                            session_id,
                            max_age=max_age,
                            secure=query_service.secure_cookie,
                        ),
                    ),
                )
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
            if not self._basic_access_allowed():
                self._send_basic_auth_required()
                return
            route = urlparse(self.path).path
            if route not in {"/api/chat", "/auth/logout"}:
                self._send_error(HTTPStatus.NOT_FOUND, "route_not_found")
                return
            if not self._same_origin_allowed():
                self._send_error(HTTPStatus.FORBIDDEN, "same_origin_required")
                return
            session_id = self._session_id()
            if route == "/auth/logout":
                query_service.logout_browser_session(session_id)
                self._send_redirect(
                    HTTPStatus.SEE_OTHER,
                    "/",
                    set_cookies=(
                        _browser_cookie(
                            _SESSION_COOKIE,
                            "",
                            max_age=0,
                            secure=query_service.secure_cookie,
                        ),
                    ),
                )
                return
            if not query_service.is_browser_session_authenticated(session_id):
                self._send_error(HTTPStatus.UNAUTHORIZED, "auth_required")
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
                response = _normalize_query_response(
                    query_service.ask(prompt, session_id=session_id)
                )
            except PermissionError:
                self._send_error(HTTPStatus.UNAUTHORIZED, "auth_required")
                return
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError):
                self._send_error(HTTPStatus.BAD_REQUEST, "request_rejected")
                return
            except Exception:
                self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "query_failed")
                return
            self._send_json(HTTPStatus.OK, response)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _basic_access_allowed(self) -> bool:
            if expected_basic_password is None:
                return True
            authorization_values = self.headers.get_all("Authorization")
            if not authorization_values or len(authorization_values) != 1:
                return False
            scheme, separator, encoded_credentials = authorization_values[0].partition(" ")
            if scheme.casefold() != "basic" or not separator or not encoded_credentials:
                return False
            try:
                decoded_credentials = base64.b64decode(
                    encoded_credentials,
                    validate=True,
                )
            except (binascii.Error, ValueError):
                return False
            if b":" not in decoded_credentials:
                return False
            username, password = decoded_credentials.split(b":", 1)
            username_matches = secrets.compare_digest(
                username,
                _TEMPORARY_BASIC_USERNAME,
            )
            password_matches = secrets.compare_digest(
                password,
                expected_basic_password,
            )
            return username_matches and password_matches

        def _send_basic_auth_required(self) -> None:
            payload = {
                "status": "error",
                "error_code": "temporary_access_required",
                "http_status_code": int(HTTPStatus.UNAUTHORIZED),
            }
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self._send_common_headers("application/json; charset=utf-8")
            self.send_header("WWW-Authenticate", _TEMPORARY_BASIC_CHALLENGE)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

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

        def _session_id(self) -> str | None:
            return self._cookie_value(_SESSION_COOKIE)

        def _cookie_value(self, name: str) -> str | None:
            raw_cookie = self.headers.get("Cookie")
            if not raw_cookie:
                return None
            try:
                cookie = SimpleCookie()
                cookie.load(raw_cookie)
            except Exception:
                return None
            value = cookie.get(name)
            return value.value if value is not None and value.value else None

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

        def _send_redirect(
            self,
            status: HTTPStatus,
            location: str,
            *,
            set_cookies: Sequence[str] = (),
        ) -> None:
            self.send_response(status)
            self._send_common_headers("text/plain; charset=utf-8")
            self.send_header("Location", location)
            for set_cookie in set_cookies:
                self.send_header("Set-Cookie", set_cookie)
            self.send_header("Content-Length", "0")
            self.end_headers()

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


def _browser_cookie(
    name: str,
    value: str,
    *,
    max_age: int,
    secure: bool,
) -> str:
    cookie = SimpleCookie()
    cookie[name] = value
    cookie[name]["httponly"] = True
    cookie[name]["samesite"] = "Lax"
    cookie[name]["path"] = "/"
    cookie[name]["max-age"] = str(max_age)
    if secure:
        cookie[name]["secure"] = True
    return cookie.output(header="").strip()


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
    #auth-controls { display: flex; gap: 16px; align-items: center; }
    #logout-form { margin: 0; padding: 0; border: 0; background: transparent; }
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
    <nav id="auth-controls" data-authenticated="__AUTHENTICATED__">
      <a id="login-link" href="/auth/start" __LOGIN_HIDDEN__>登入</a>
      <form id="logout-form" action="/auth/logout" method="post" __LOGOUT_HIDDEN__>
        <button type="submit">登出</button>
      </form>
    </nav>
    <form id="chat-form" __CHAT_HIDDEN__>
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


def _render_page(authenticated: bool) -> str:
    return (
        _PAGE.replace("__AUTHENTICATED__", "true" if authenticated else "false")
        .replace("__LOGIN_HIDDEN__", "hidden" if authenticated else "")
        .replace("__LOGOUT_HIDDEN__", "" if authenticated else "hidden")
        .replace("__CHAT_HIDDEN__", "" if authenticated else "hidden")
    )
