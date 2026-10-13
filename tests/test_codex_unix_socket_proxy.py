from __future__ import annotations

import base64
import hashlib
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest

import _paths  # noqa: F401
from formowl_mail.codex_unix_socket_proxy import _UnixWebSocket

_WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class CodexUnixSocketProxyTests(unittest.TestCase):
    def test_private_unix_websocket_round_trip_masks_client_frames(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            socket_path = Path(temp_dir) / "codex.sock"
            ready = threading.Event()
            received: list[str] = []
            failures: list[BaseException] = []

            def serve() -> None:
                listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    listener.bind(str(socket_path))
                    listener.listen(1)
                    ready.set()
                    connection, _ = listener.accept()
                    with connection:
                        request = _read_until(connection, b"\r\n\r\n")
                        key = _header_value(request, "sec-websocket-key")
                        accept = base64.b64encode(
                            hashlib.sha1((key + _WEBSOCKET_GUID).encode("ascii")).digest()
                        ).decode("ascii")
                        connection.sendall(
                            (
                                "HTTP/1.1 101 Switching Protocols\r\n"
                                "Upgrade: websocket\r\n"
                                "Connection: Upgrade\r\n"
                                f"Sec-WebSocket-Accept: {accept}\r\n"
                                "\r\n"
                            ).encode("ascii")
                        )
                        opcode, masked, payload = _read_frame(connection)
                        self.assertEqual(opcode, 0x1)
                        self.assertTrue(masked)
                        received.append(payload.decode("utf-8"))
                        _send_server_text(connection, '{"id":1,"result":{}}')
                except BaseException as exc:  # pragma: no cover - surfaced below
                    failures.append(exc)
                    ready.set()
                finally:
                    listener.close()

            server = threading.Thread(target=serve, daemon=True)
            server.start()
            self.assertTrue(ready.wait(5))
            client = _UnixWebSocket(socket_path)
            try:
                client.send_text('{"id":1,"method":"initialize"}')
                self.assertEqual(client.recv_text(), '{"id":1,"result":{}}')
            finally:
                client.close()
            server.join(timeout=5)

        self.assertFalse(server.is_alive())
        if failures:
            raise failures[0]
        self.assertEqual(received, ['{"id":1,"method":"initialize"}'])


def _read_until(connection: socket.socket, marker: bytes) -> bytes:
    payload = bytearray()
    while marker not in payload:
        chunk = connection.recv(4096)
        if not chunk:
            raise RuntimeError("test WebSocket handshake was interrupted")
        payload.extend(chunk)
    return bytes(payload)


def _header_value(request: bytes, name: str) -> str:
    for line in request.decode("ascii").split("\r\n")[1:]:
        key, separator, value = line.partition(":")
        if separator and key.strip().casefold() == name:
            return value.strip()
    raise RuntimeError(f"missing test header: {name}")


def _read_frame(connection: socket.socket) -> tuple[int, bool, bytes]:
    first, second = _read_exact(connection, 2)
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", _read_exact(connection, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _read_exact(connection, 8))[0]
    masked = bool(second & 0x80)
    mask = _read_exact(connection, 4) if masked else b""
    payload = _read_exact(connection, length)
    if masked:
        payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    return first & 0x0F, masked, payload


def _read_exact(connection: socket.socket, size: int) -> bytes:
    payload = bytearray()
    while len(payload) < size:
        chunk = connection.recv(size - len(payload))
        if not chunk:
            raise RuntimeError("test WebSocket frame was interrupted")
        payload.extend(chunk)
    return bytes(payload)


def _send_server_text(connection: socket.socket, text: str) -> None:
    payload = text.encode("utf-8")
    if len(payload) >= 126:
        raise RuntimeError("test payload is too large")
    connection.sendall(bytes((0x81, len(payload))) + payload)


if __name__ == "__main__":
    unittest.main()
