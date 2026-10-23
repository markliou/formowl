"""readpst embeds attached messages after an mbox ``>From`` line; parse them as mail."""

from __future__ import annotations

import base64
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from formowl_ingestion.extractors.mail.pst import _body_parts, _parse_mail_bytes  # noqa: E402

_RTF = base64.encodebytes(b"{\\rtf1 {\\*\\htmltag148 <span>}} " * 40).decode()


def _exported(separator: str) -> bytes:
    inner = (
        f"{separator}\n"
        "From: Alice <alice@example.com>\n"
        "Subject: inner\n"
        "MIME-Version: 1.0\n"
        'Content-Type: multipart/mixed; boundary="IN"\n'
        "\n"
        "--IN\n"
        "Content-Type: text/plain; charset=utf-8\n"
        "Content-Transfer-Encoding: base64\n"
        "\n"
        + base64.encodebytes("交期確認：2026/05/14".encode()).decode()
        + "--IN\n"
        "Content-Type: application/rtf\n"
        "Content-Transfer-Encoding: base64\n"
        'Content-Disposition: attachment; filename="rtf-body.rtf"\n'
        "\n"
        + _RTF
        + "--IN--\n"
    )
    return (
        "From: Bob <bob@example.com>\n"
        "Subject: outer\n"
        "MIME-Version: 1.0\n"
        'Content-Type: multipart/mixed; boundary="OUT"\n'
        "\n"
        "--OUT\n"
        "Content-Type: text/plain; charset=utf-8\n"
        "\n"
        "see attached\n"
        "--OUT\n"
        "Content-Type: message/rfc822\n"
        "\n"
        + inner
        + "--OUT--\n"
    ).encode("utf-8")


class EmbeddedMboxFromLineTests(unittest.TestCase):
    def test_embedded_message_is_parsed_instead_of_dumped_as_text(self):
        for separator in ('>From "MAILER-DAEMON" Tue Jun 24 01:11:55 2025', "From MAILER-DAEMON Tue Jun 24 2025"):
            with self.subTest(separator=separator):
                message = _parse_mail_bytes(_exported(separator))
                texts = [part["text"] for part in _body_parts(message, warnings=[])]
                self.assertIn("see attached", texts[0])
                self.assertTrue(any("交期確認：2026/05/14" in text for text in texts))
                self.assertFalse(any("htmltag" in text or "MAILER-DAEMON" in text for text in texts))
                inner = next(part for part in message.walk() if part.get_content_type() == "message/rfc822")
                self.assertEqual(inner.get_payload(0)["Subject"], "inner")

    def test_well_formed_embedded_message_is_unchanged(self):
        raw = _exported('>From x').replace(b'>From x\n', b'')
        message = _parse_mail_bytes(raw)
        texts = [part["text"] for part in _body_parts(message, warnings=[])]
        self.assertTrue(any("交期確認：2026/05/14" in text for text in texts))

    def test_headerless_embedded_body_without_separator_is_left_alone(self):
        raw = _exported(">From x").replace(b">From x\nFrom: Alice", b"just text\nFrom: Alice")
        message = _parse_mail_bytes(raw)
        inner = next(part for part in message.walk() if part.get_content_type() == "message/rfc822")
        self.assertEqual(list(inner.get_payload(0).keys()), [])


if __name__ == "__main__":
    unittest.main()
