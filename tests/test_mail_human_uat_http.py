from __future__ import annotations

import http.client
import json
import threading
import unittest
from urllib.parse import parse_qs, urlparse

import _paths  # noqa: F401
from formowl_mail.human_uat_http import create_mail_human_uat_http_server


class _QueryService:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.prompts: list[str] = []
        self.sessions: set[str] = set()
        self.secure_cookie = False
        self.browser_nonce = "pre-auth-browser-nonce"

    def begin_browser_authorization(self) -> tuple[str, str, int]:
        return (
            (
                "https://auth.example.test/oauth/authorize"
                "?state=browser-state&code_challenge=challenge&code_challenge_method=S256"
            ),
            self.browser_nonce,
            120,
        )

    def complete_browser_authorization(
        self,
        *,
        state: str,
        code: str,
        browser_nonce: str | None,
    ) -> tuple[str, int]:
        if (
            state != "browser-state"
            or code != "authorization-code"
            or browser_nonce != self.browser_nonce
        ):
            raise ValueError("invalid callback")
        self.sessions.add("browser-session")
        return "browser-session", 300

    def is_browser_session_authenticated(self, session_id: str | None) -> bool:
        return session_id in self.sessions

    def logout_browser_session(self, session_id: str | None) -> None:
        self.sessions.discard(session_id)

    def ask(
        self,
        prompt: str,
        *,
        session_id: str | None,
    ) -> dict[str, object]:
        if not self.is_browser_session_authenticated(session_id):
            raise PermissionError("auth_required")
        self.prompts.append(prompt)
        return self.response


class MailHumanUatHttpTests(unittest.TestCase):
    def test_auth_start_sets_short_lived_pre_auth_cookie(self) -> None:
        service = _QueryService({})
        with _RunningSurface(service) as surface:
            response, _body = surface.request("GET", "/auth/start")

        self.assertEqual(response.status, 302)
        self.assertIn("code_challenge_method=S256", response.getheader("Location"))
        cookie = response.getheader("Set-Cookie")
        self.assertIsInstance(cookie, str)
        assert isinstance(cookie, str)
        for required in (
            "formowl_uat_pre_auth=",
            "HttpOnly",
            "SameSite=Lax",
            "Path=/",
            "Max-Age=120",
        ):
            self.assertIn(required, cookie)
        self.assertNotIn("Secure", cookie)

    def test_auth_callback_requires_same_pre_auth_browser_cookie(self) -> None:
        service = _QueryService({})
        with _RunningSurface(service) as surface:
            start, _body = surface.request("GET", "/auth/start")
            state = parse_qs(urlparse(start.getheader("Location")).query)["state"][0]
            callback_path = f"/auth/callback?state={state}&code=authorization-code"
            missing, _body = surface.request("GET", callback_path)
            wrong, _body = surface.request(
                "GET",
                callback_path,
                headers={"Cookie": "formowl_uat_pre_auth=wrong-browser"},
            )
            pre_auth_cookie = start.getheader("Set-Cookie").split(";", 1)[0]
            wrong_state, _body = surface.request(
                "GET",
                "/auth/callback?state=wrong-state&code=authorization-code",
                headers={"Cookie": pre_auth_cookie},
            )
            success, _body = surface.request(
                "GET",
                callback_path,
                headers={"Cookie": pre_auth_cookie},
            )

        self.assertEqual(missing.status, 400)
        self.assertEqual(wrong.status, 400)
        self.assertEqual(wrong_state.status, 400)
        self.assertEqual(service.sessions, {"browser-session"})
        self.assertEqual(success.status, 303)
        set_cookies = [
            value for name, value in success.getheaders() if name.casefold() == "set-cookie"
        ]
        self.assertEqual(len(set_cookies), 2)
        self.assertTrue(
            any("formowl_uat_pre_auth=" in value and "Max-Age=0" in value for value in set_cookies)
        )
        self.assertTrue(any("formowl_uat_session=" in value for value in set_cookies))

    def test_https_auth_cookies_are_secure(self) -> None:
        service = _QueryService({})
        service.secure_cookie = True
        with _RunningSurface(service) as surface:
            start, _body = surface.request("GET", "/auth/start")
            state = parse_qs(urlparse(start.getheader("Location")).query)["state"][0]
            pre_auth_cookie = start.getheader("Set-Cookie").split(";", 1)[0]
            callback, _body = surface.request(
                "GET",
                f"/auth/callback?state={state}&code=authorization-code",
                headers={"Cookie": pre_auth_cookie},
            )

        self.assertIn("Secure", start.getheader("Set-Cookie"))
        for name, value in callback.getheaders():
            if name.casefold() == "set-cookie":
                self.assertIn("Secure", value)

    def test_page_and_health_expose_only_minimal_same_origin_chat_surface(self) -> None:
        service = _QueryService({})
        with _RunningSurface(service) as surface:
            page_response, page_body = surface.request("GET", "/")
            health_response, health_body = surface.request("GET", "/api/health")

        html = page_body.decode("utf-8")
        health = json.loads(health_body)
        self.assertEqual(page_response.status, 200)
        self.assertEqual(health_response.status, 200)
        self.assertEqual(
            health,
            {
                "query_service_connected": True,
                "service": "mail_human_uat_http",
                "status": "ok",
            },
        )
        for element_id in (
            "login-link",
            "logout-form",
            "prompt-input",
            "loading-state",
            "submitted-prompt",
            "answer-text",
            "citation-summary",
            "clarification-text",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn('fetch("/api/chat"', html)
        self.assertIn('fetch("/api/health"', html)
        self.assertIn(".textContent = prompt", html)
        self.assertIn('data-authenticated="false"', html)
        self.assertIn('id="chat-form" hidden', html)
        self.assertNotIn("/api/upload", html)
        self.assertNotIn("analytics", html.lower())
        self.assertNotIn("codex", html.lower())
        self.assertEqual(page_response.getheader("Cache-Control"), "no-store, max-age=0")

    def test_chat_calls_injected_service_once_and_returns_allowlisted_fields(self) -> None:
        service = _QueryService(
            {
                "status": "complete",
                "answer": "找到可引用的回答。",
                "citations": ["來源一", {"label": "來源二"}],
                "clarification": None,
                "private_backend_detail": "must not pass through",
            }
        )
        with _RunningSurface(service) as surface:
            unauthenticated, unauthenticated_body = surface.request_json(
                "/api/chat",
                {"prompt": "不應執行"},
            )
            cookie = surface.login()
            page_response, page_body = surface.request(
                "GET",
                "/",
                headers={"Cookie": cookie},
            )
            response, body = surface.request_json(
                "/api/chat",
                {"prompt": "請查詢這個問題"},
                cookie=cookie,
            )

        payload = json.loads(body)
        self.assertEqual(unauthenticated.status, 401)
        self.assertEqual(
            json.loads(unauthenticated_body)["error_code"],
            "auth_required",
        )
        self.assertEqual(page_response.status, 200)
        self.assertIn(
            'data-authenticated="true"',
            page_body.decode("utf-8"),
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(service.prompts, ["請查詢這個問題"])
        self.assertEqual(
            payload,
            {
                "answer": "找到可引用的回答。",
                "citation_count": 2,
                "citations": ["來源一", "來源二"],
                "clarification": None,
                "status": "complete",
            },
        )
        self.assertNotIn("private_backend_detail", payload)

    def test_clarification_is_renderable_and_cross_origin_post_is_rejected(self) -> None:
        service = _QueryService(
            {
                "status": "clarification_required",
                "answer": "",
                "citations": [],
                "clarification": "請補充要查詢的範圍。",
            }
        )
        with _RunningSurface(service) as surface:
            cookie = surface.login()
            response, body = surface.request_json(
                "/api/chat",
                {"prompt": "幫我查一下"},
                cookie=cookie,
            )
            rejected, rejected_body = surface.request_json(
                "/api/chat",
                {"prompt": "不應執行"},
                origin="https://example.invalid",
                cookie=cookie,
            )
            logout, _logout_body = surface.request(
                "POST",
                "/auth/logout",
                headers={"Origin": surface.origin, "Cookie": cookie},
            )

        payload = json.loads(body)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["status"], "clarification_required")
        self.assertEqual(payload["clarification"], "請補充要查詢的範圍。")
        self.assertEqual(rejected.status, 403)
        self.assertEqual(json.loads(rejected_body)["error_code"], "same_origin_required")
        self.assertEqual(service.prompts, ["幫我查一下"])
        self.assertEqual(logout.status, 303)
        self.assertIn("Max-Age=0", logout.getheader("Set-Cookie"))


class _RunningSurface:
    def __init__(self, query_service: _QueryService) -> None:
        self.server = create_mail_human_uat_http_server("127.0.0.1", 0, query_service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> _RunningSurface:
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    @property
    def origin(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response, response.read()
        finally:
            connection.close()

    def request_json(
        self,
        path: str,
        payload: dict[str, object],
        *,
        origin: str | None = None,
        cookie: str | None = None,
    ):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
            "Origin": origin or self.origin,
        }
        if cookie is not None:
            headers["Cookie"] = cookie
        return self.request(
            "POST",
            path,
            body=body,
            headers=headers,
        )

    def login(self) -> str:
        start, _body = self.request("GET", "/auth/start")
        self.assert_status(start.status, 302)
        state = parse_qs(urlparse(start.getheader("Location")).query)["state"][0]
        pre_auth_cookie = start.getheader("Set-Cookie")
        if not isinstance(pre_auth_cookie, str):
            raise AssertionError("missing pre-auth browser cookie")
        callback, _body = self.request(
            "GET",
            f"/auth/callback?state={state}&code=authorization-code",
            headers={"Cookie": pre_auth_cookie.split(";", 1)[0]},
        )
        self.assert_status(callback.status, 303)
        set_cookies = [
            value for name, value in callback.getheaders() if name.casefold() == "set-cookie"
        ]
        session_cookie = next(
            (value for value in set_cookies if value.startswith("formowl_uat_session=")),
            None,
        )
        if not isinstance(session_cookie, str):
            raise AssertionError("missing browser session cookie")
        for required in ("HttpOnly", "SameSite=Lax", "Path=/", "Max-Age=300"):
            if required not in session_cookie:
                raise AssertionError(f"missing cookie attribute: {required}")
        return session_cookie.split(";", 1)[0]

    @staticmethod
    def assert_status(actual: int, expected: int) -> None:
        if actual != expected:
            raise AssertionError(f"expected HTTP {expected}, got {actual}")


if __name__ == "__main__":
    unittest.main()
