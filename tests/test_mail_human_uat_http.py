from __future__ import annotations

import http.client
import json
import threading
import unittest

import _paths  # noqa: F401
from formowl_mail.human_uat_http import create_mail_human_uat_http_server


class _QueryService:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.prompts: list[str] = []

    def ask(self, prompt: str) -> dict[str, object]:
        self.prompts.append(prompt)
        return self.response


class MailHumanUatHttpTests(unittest.TestCase):
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
        self.assertNotIn("/api/upload", html)
        self.assertNotIn("analytics", html.lower())
        self.assertNotIn("login", html.lower())
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
            response, body = surface.request_json("/api/chat", {"prompt": "請查詢這個問題"})

        payload = json.loads(body)
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
            response, body = surface.request_json("/api/chat", {"prompt": "幫我查一下"})
            rejected, rejected_body = surface.request_json(
                "/api/chat",
                {"prompt": "不應執行"},
                origin="https://example.invalid",
            )

        payload = json.loads(body)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["status"], "clarification_required")
        self.assertEqual(payload["clarification"], "請補充要查詢的範圍。")
        self.assertEqual(rejected.status, 403)
        self.assertEqual(json.loads(rejected_body)["error_code"], "same_origin_required")
        self.assertEqual(service.prompts, ["幫我查一下"])


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
    ):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self.request(
            "POST",
            path,
            body=body,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
                "Origin": origin or self.origin,
            },
        )


if __name__ == "__main__":
    unittest.main()
