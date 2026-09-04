"""Minimal JSONL-to-WebSocket bridge for a private Codex Unix socket."""

from __future__ import annotations

import argparse
import base64
import hashlib
from pathlib import Path
import secrets
import selectors
import socket
import struct
import sys

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_contract import ContractValidationError  # noqa: E402

_MAX_HANDSHAKE_BYTES = 16 * 1024
_MAX_MESSAGE_BYTES = 4 * 1024 * 1024
_WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class _UnixWebSocket:
    def __init__(self, socket_path: Path) -> None:
        if not socket_path.is_absolute():
            raise ContractValidationError("Codex Unix socket path must be absolute")
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.socket.connect(str(socket_path))
            self._handshake()
        except Exception:
            self.socket.close()
            raise
        self._closed = False

    def fileno(self) -> int:
        return self.socket.fileno()

    def send_text(self, text: str) -> None:
        payload = text.encode("utf-8")
        if not payload or len(payload) > _MAX_MESSAGE_BYTES:
            raise RuntimeError("Codex proxy outbound message is invalid")
        self._send_frame(0x1, payload)

    def recv_text(self) -> str | None:
        fragments = bytearray()
        started = False
        while True:
            first, second = self._read_exact(2)
            final = bool(first & 0x80)
            if first & 0x70:
                raise RuntimeError("Codex proxy received an unsupported WebSocket frame")
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            if masked:
                raise RuntimeError("Codex proxy received a masked server frame")
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(8))[0]
            if length > _MAX_MESSAGE_BYTES:
                raise RuntimeError("Codex proxy received an oversized message")
            payload = self._read_exact(length)

            if opcode == 0x8:
                if not self._closed:
                    self._send_frame(0x8, payload[:125])
                self._closed = True
                return None
            if opcode == 0x9:
                if not final or len(payload) > 125:
                    raise RuntimeError("Codex proxy received an invalid ping")
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x1:
                if started:
                    raise RuntimeError("Codex proxy received nested text fragments")
                fragments.extend(payload)
                started = True
            elif opcode == 0x0:
                if not started:
                    raise RuntimeError("Codex proxy received an orphan fragment")
                fragments.extend(payload)
            else:
                raise RuntimeError("Codex proxy received a non-text message")
            if len(fragments) > _MAX_MESSAGE_BYTES:
                raise RuntimeError("Codex proxy received an oversized message")
            if final:
                try:
                    return fragments.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise RuntimeError("Codex proxy received invalid UTF-8") from exc

    def close(self) -> None:
        if self._closed:
            self.socket.close()
            return
        self._closed = True
        try:
            self._send_frame(0x8, b"")
        except OSError:
            pass
        self.socket.close()

    def _handshake(self) -> None:
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = (
            "GET / HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self.socket.sendall(request.encode("ascii"))
        response = bytearray()
        while b"\r\n\r\n" not in response:
            if len(response) >= _MAX_HANDSHAKE_BYTES:
                raise RuntimeError("Codex proxy handshake was oversized")
            chunk = self.socket.recv(4096)
            if not chunk:
                raise RuntimeError("Codex proxy handshake was interrupted")
            response.extend(chunk)
        header_block, remainder = bytes(response).split(b"\r\n\r\n", 1)
        if remainder:
            raise RuntimeError("Codex proxy handshake returned unexpected data")
        try:
            lines = header_block.decode("ascii").split("\r\n")
        except UnicodeDecodeError as exc:
            raise RuntimeError("Codex proxy handshake was invalid") from exc
        if not lines or " 101 " not in f" {lines[0]} ":
            raise RuntimeError("Codex proxy handshake was rejected")
        headers: dict[str, str] = {}
        for line in lines[1:]:
            name, separator, value = line.partition(":")
            if not separator:
                raise RuntimeError("Codex proxy handshake was invalid")
            headers[name.strip().casefold()] = value.strip()
        expected_accept = base64.b64encode(
            hashlib.sha1((key + _WEBSOCKET_GUID).encode("ascii")).digest()
        ).decode("ascii")
        if (
            headers.get("upgrade", "").casefold() != "websocket"
            or "upgrade" not in headers.get("connection", "").casefold()
            or headers.get("sec-websocket-accept") != expected_accept
        ):
            raise RuntimeError("Codex proxy handshake was invalid")

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        mask = secrets.token_bytes(4)
        length = len(payload)
        if length < 126:
            header = bytes((0x80 | opcode, 0x80 | length))
        elif length <= 0xFFFF:
            header = bytes((0x80 | opcode, 0x80 | 126)) + struct.pack("!H", length)
        else:
            header = bytes((0x80 | opcode, 0x80 | 127)) + struct.pack("!Q", length)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        self.socket.sendall(header + mask + masked)

    def _read_exact(self, size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            chunk = self.socket.recv(size - len(chunks))
            if not chunk:
                raise RuntimeError("Codex proxy connection closed unexpectedly")
            chunks.extend(chunk)
        return bytes(chunks)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", type=Path, required=True)
    args = parser.parse_args()
    websocket = _UnixWebSocket(args.socket)
    selector = selectors.DefaultSelector()
    selector.register(sys.stdin.buffer, selectors.EVENT_READ, "stdin")
    selector.register(websocket.socket, selectors.EVENT_READ, "websocket")
    try:
        while True:
            for key, _ in selector.select():
                if key.data == "stdin":
                    line = sys.stdin.buffer.readline()
                    if not line:
                        return 0
                    if not line.endswith(b"\n"):
                        raise RuntimeError("Codex proxy stdin message is incomplete")
                    websocket.send_text(line[:-1].decode("utf-8"))
                    continue
                message = websocket.recv_text()
                if message is None:
                    return 0
                sys.stdout.write(message + "\n")
                sys.stdout.flush()
    except (OSError, RuntimeError, UnicodeError) as exc:
        print(
            f"Codex Unix socket proxy failed: {type(exc).__name__}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    finally:
        selector.close()
        websocket.close()


if __name__ == "__main__":
    raise SystemExit(main())
