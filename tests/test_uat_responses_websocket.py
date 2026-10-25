from __future__ import annotations

import base64
import hashlib
import json
import socket
import threading
import unittest

import _paths  # noqa: F401
from formowl_mail.human_uat_orchestrator import CodexResponsesConversationModel, _UatProviderFailure

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _frame(opcode: int, payload: bytes) -> bytes:
    size = len(payload)
    header = bytes([0x80 | opcode]) + (bytes([size]) if size < 126 else bytes([126]) + size.to_bytes(2, "big")
                                       if size < 65536 else bytes([127]) + size.to_bytes(8, "big"))
    return header + payload


class _Server:
    """One-connection Responses WebSocket stub: records the handshake and the request message."""

    def __init__(self, events: list[dict] | None, *, status: int = 101) -> None:
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.events, self.status = events, status
        self.headers: dict[str, str] = {}
        self.request: dict | None = None
        self.pong = False
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _recv_frame(self, conn: socket.socket) -> tuple[int, bytes]:
        def exact(n: int) -> bytes:
            data = b""
            while len(data) < n:
                chunk = conn.recv(n - len(data))
                if not chunk:
                    raise ConnectionError
                data += chunk
            return data
        first, second = exact(2)
        size = second & 0x7F
        if size == 126:
            size = int.from_bytes(exact(2), "big")
        elif size == 127:
            size = int.from_bytes(exact(8), "big")
        mask = exact(4)
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(exact(size)))
        return first & 0x0F, payload

    def _serve(self) -> None:
        conn, _ = self.listener.accept()
        self.listener.close()
        with conn:
            data = b""
            while b"\r\n\r\n" not in data:
                data += conn.recv(4096)
            lines = data.split(b"\r\n\r\n")[0].decode().split("\r\n")
            self.path = lines[0].split(" ")[1]
            self.headers = {k.strip().lower(): v.strip() for k, _, v in (line.partition(":") for line in lines[1:])}
            if self.status != 101:
                body = b'{"error":{"message":"unauthorized"}}'
                conn.sendall(b"HTTP/1.1 401 Unauthorized\r\nContent-Type: application/json\r\nContent-Length: "
                             + str(len(body)).encode() + b"\r\n\r\n" + body)
                return
            accept = base64.b64encode(hashlib.sha1((self.headers["sec-websocket-key"] + GUID).encode()).digest())
            conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                         b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n")
            _, payload = self._recv_frame(conn)
            self.request = json.loads(payload)
            conn.sendall(_frame(0x9, b"hb"))
            opcode, _ = self._recv_frame(conn)
            self.pong = opcode == 0xA
            for event in self.events:
                conn.sendall(_frame(0x1, json.dumps(event).encode()))
            try:
                self._recv_frame(conn)  # client close
            except ConnectionError:
                pass


def _completed(text: str) -> dict:
    return {"type": "response.completed", "response": {
        "status": "completed", "model": "gpt-5.6-luna",
        "output": [{"type": "message", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": text}]}]}}


class ResponsesWebSocketTests(unittest.TestCase):
    def _read(self, server: _Server):
        model = CodexResponsesConversationModel(base_url=f"http://127.0.0.1:{server.port}/v1", api_key="synthetic-key",
                                                model="gpt-5.6-luna", reasoning_effort="low", websocket=True)
        return model.extract_structured_json(
            instructions="Return JSON.", source_unit={"observations": []},
            response_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
                             "additionalProperties": False}, schema_name="probe")

    def test_request_is_one_response_create_message_with_codex_websocket_headers(self) -> None:
        server = _Server([{"type": "response.created", "response": {"status": "in_progress"}},
                          {"type": "response.output_text.delta", "delta": "{"}, _completed('{"ok":true}')])
        result = self._read(server)
        server.thread.join(timeout=5)
        self.assertEqual(result["data"], {"ok": True})
        self.assertEqual(server.path, "/v1/responses")
        self.assertEqual(server.headers["openai-beta"], "responses_websockets=2026-02-06")
        self.assertEqual(server.headers["authorization"], "Bearer synthetic-key")
        self.assertEqual(server.request["type"], "response.create")
        self.assertNotIn("stream", server.request)
        self.assertEqual((server.request["model"], server.request["reasoning"]), ("gpt-5.6-luna", {"effort": "low"}))
        self.assertTrue(server.pong)

    def test_fields_codex_does_not_send_are_omitted(self) -> None:
        import urllib.request

        server = _Server([_completed('{"ok":true}')])
        model = CodexResponsesConversationModel(base_url=f"http://127.0.0.1:{server.port}/v1", api_key="k",
                                                websocket=True)
        request = urllib.request.Request(model._responses_url, headers={"Authorization": "Bearer k"})
        parsed, _, status, _ = model._websocket_round_trip(
            request, {"model": "m", "stream": True, "safety_identifier": "uat-user", "input": []},
            deadline=__import__("time").monotonic() + 10, timeout_seconds=10, request_shape=None)
        server.thread.join(timeout=5)
        self.assertEqual((parsed["status"], status), ("completed", 200))
        self.assertEqual(server.request, {"type": "response.create", "model": "m", "input": []})

    def test_error_event_and_rejected_upgrade_are_provider_failures(self) -> None:
        with self.assertRaises(_UatProviderFailure) as error:
            self._read(_Server([{"type": "error", "error": {"message": "bad request"}}]))
        self.assertEqual(error.exception.safe_diagnostic["reason_code"], "provider_error")
        with self.assertRaises(_UatProviderFailure) as rejected:
            self._read(_Server(None, status=401))
        self.assertEqual((rejected.exception.safe_diagnostic["reason_code"],
                          rejected.exception.safe_diagnostic["http_status"]), ("http_error", 401))


if __name__ == "__main__":
    unittest.main()
