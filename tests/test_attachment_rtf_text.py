"""Bounded RTF text extraction for mail bodies/attachments readpst stores as RTF."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from formowl_ingestion.extractors.document.attachment import (  # noqa: E402
    _parse_content,
    _rtf_to_text,
    _sniff_kind,
)


def _cp950_hex(text: str) -> bytes:
    return b"".join(b"\\'%02x" % byte for byte in text.encode("cp950"))


class RtfTextTests(unittest.TestCase):
    def test_plain_rtf_with_cp950_bytes_and_skipped_tables(self):
        data = (b"{\\rtf1\\ansi\\ansicpg950\\deff0{\\fonttbl{\\f0 \\'b7\\'73\\'b2\\'d3\\'a9\\'fa\\'c5\\'e9;}}"
                b"{\\colortbl;\\red0\\green0\\blue0;}"
                b"\\pard PO 470002138 " + _cp950_hex("交期") + b" 2026/05/14\\par "
                + _cp950_hex("請確認") + b"\\par}")
        self.assertEqual(_sniff_kind(data, max_bytes=1 << 20), "rtf")
        text = _rtf_to_text(data)
        self.assertIn("PO 470002138 交期 2026/05/14", text)
        self.assertIn("請確認", text)
        self.assertNotIn("新細明體", text)

    def test_unicode_escape_skips_fallback_character(self):
        data = b"{\\rtf1\\ansi\\uc1 Delivery \\u20132?\\u26399? confirmed\\par}"
        self.assertEqual(_rtf_to_text(data), "Delivery 交期 confirmed")

    def test_outlook_encapsulated_html_keeps_visible_text_only(self):
        data = (b"{\\rtf1\\ansi\\ansicpg1252\\fromhtml1 \\deff0{\\fonttbl{\\f0 Arial;}}"
                b"{\\*\\htmltag19 <html>}{\\*\\htmltag148 <span style=\"color:#1F497D\">}"
                b"\\htmlrtf {\\htmlrtf0 Shipment ETD moved to 2026-07-13.\\par}"
                b"{\\*\\htmltag156 </span>}{\\*\\htmltag27 </html>}}")
        text = _rtf_to_text(data)
        self.assertIn("Shipment ETD moved to 2026-07-13.", text)
        self.assertNotIn("<span", text)
        self.assertNotIn("htmltag", text)

    def test_rtf_becomes_paragraph_blocks(self):
        data = b"{\\rtf1\\ansi First paragraph.\\par\\par Second paragraph.\\par}"
        parsed = _parse_content(data, kind="rtf", declared_kind="rtf", max_bytes=1 << 20, config={})
        self.assertEqual([block.text for block in parsed.blocks], ["First paragraph.", "Second paragraph."])
        self.assertEqual({block.payload["source_format"] for block in parsed.blocks}, {"rtf"})

    def test_binary_payloads_are_skipped_and_html_entities_decoded(self):
        data = (b"{\\rtf1\\ansi\\fromhtml1 Before {\\pict\\bin4 \x00\x01{}} after "
                b"&quot;quoted&quot; &lt;tag&gt;\\par}")
        text = _rtf_to_text(data)
        self.assertIn("Before", text)
        self.assertIn('after "quoted" <tag>', text)
        self.assertNotIn("\x00", text)

    def test_garbled_rtf_is_withheld_not_emitted(self):
        garbled = b"{\\rtf1\\ansi " + bytes(range(1, 31)) * 20 + b" text\\par}"
        parsed = _parse_content(garbled, kind="rtf", declared_kind="rtf", max_bytes=1 << 20, config={})
        self.assertEqual(parsed.blocks, [])
        self.assertIn("attachment_document_rtf_text_unreliable", parsed.warnings)
        self.assertEqual(_rtf_to_text(b"{\\rtf1\\ansi Regards\\par\x00}"), "Regards")

    def test_surrogate_pairs_are_recombined(self):
        # U+1F600 as \\u-10179?\\u-8704? (UTF-16 surrogate pair in signed form)
        self.assertEqual(_rtf_to_text(b"{\\rtf1\\ansi\\uc1 ok \\u-10179?\\u-8704? done\\par}"), "ok \U0001F600 done")


if __name__ == "__main__":
    unittest.main()
