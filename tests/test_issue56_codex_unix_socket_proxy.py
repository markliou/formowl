from __future__ import annotations

from contextlib import redirect_stderr
import io
import os
import selectors
import socket
from types import SimpleNamespace
import unittest
from unittest import mock

import _paths  # noqa: F401
from formowl_mail import codex_unix_socket_proxy as proxy


class CodexUnixSocketProxyTests(unittest.TestCase):
    def run_proxy(self, initial, *, tail=None, eof=False):
        read_fd, write_fd = os.pipe()
        source = os.fdopen(read_fd, "rb")
        incoming, peer = socket.socketpair()
        selector = selectors.DefaultSelector()
        select = selector.select
        forwarded = []

        def bounded_select():
            events = select(timeout=1)
            if not events:
                raise RuntimeError("synthetic idle timeout")
            return events

        def send_text(text):
            forwarded.append(text)
            if len(forwarded) == 1 and tail is not None:
                os.write(write_fd, tail)
            if len(forwarded) == 2 and not eof:
                # End the loop only after both messages arrive. No extra stdin
                # write wakes a stranded, buffered second line in the regression.
                peer.sendall(b"x")

        def recv_text():
            incoming.recv(1)
            return None

        websocket = SimpleNamespace(
            socket=incoming, send_text=send_text, recv_text=recv_text, close=mock.Mock(),
        )
        try:
            os.write(write_fd, initial)
            if eof:
                os.close(write_fd)
            with (
                mock.patch.object(proxy.sys, "argv", ["proxy", "--socket", "/synthetic.sock"]),
                mock.patch.object(proxy.sys, "stdin", SimpleNamespace(buffer=source)),
                mock.patch.object(proxy, "_UnixWebSocket", return_value=websocket),
                mock.patch.object(proxy.selectors, "DefaultSelector", return_value=selector),
                mock.patch.object(selector, "select", side_effect=bounded_select),
                redirect_stderr(io.StringIO()) as stderr,
            ):
                result = proxy.main()
            websocket.close.assert_called_once()
            return result, forwarded, stderr.getvalue()
        finally:
            source.close()
            if not eof:
                os.close(write_fd)
            incoming.close()
            peer.close()
            selector.close()

    def test_single_write_forwards_both_jsonl_messages_without_more_input(self):
        messages = ['{"method":"initialized"}', '{"id":2,"method":"config/read"}']
        result, forwarded, error = self.run_proxy(("\n".join(messages) + "\n").encode())
        self.assertEqual(forwarded, messages)
        self.assertEqual(result, 0)
        self.assertEqual(error, "")

    def test_fragmented_utf8_tail_is_preserved_until_newline(self):
        messages = ['{"id":1}', '{"text":"甲社"}']
        second = messages[1].encode() + b"\n"
        # Split inside the first multi-byte character, after a complete first line.
        boundary = len(b'{"text":"') + 1
        result, forwarded, error = self.run_proxy(
            messages[0].encode() + b"\n" + second[:boundary], tail=second[boundary:],
        )
        self.assertEqual(forwarded, messages)
        self.assertEqual(result, 0)
        self.assertEqual(error, "")

    def test_eof_preserves_complete_lines_and_rejects_incomplete_tail(self):
        for tail, expected in ((b"", 0), (b'{"private":"unfinished', 1)):
            with self.subTest(incomplete=bool(tail)):
                result, forwarded, error = self.run_proxy(b'{"id":1}\n' + tail, eof=True)
                self.assertEqual(forwarded, ['{"id":1}'])
                self.assertEqual(result, expected)
                if tail:
                    self.assertEqual(error, "Codex Unix socket proxy failed: RuntimeError\n")
                else:
                    self.assertEqual(error, "")


if __name__ == "__main__":
    unittest.main()
