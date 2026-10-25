"""Archive (ZIP/gzip/tar) expansion and legacy Word/PowerPoint text extraction."""

from __future__ import annotations

import gzip
import io
from pathlib import Path
import struct
import sys
import tarfile
import unittest
from unittest import mock
from zipfile import ZipFile, ZipInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from formowl_ingestion.extractors.document.attachment import (  # noqa: E402
    _ParsedContent,
    _TextBlock,
    _add_member,
    _declared_kind,
    _parse_content,
    _sniff_kind,
    _zip_member_name,
)

try:
    import xlrd  # noqa: F401
except ImportError:  # the dev image may omit the optional xlrd dependency
    xlrd = None

_MB = 1 << 20


def _parse(data: bytes, filename: str, **config):
    declared = _declared_kind(None, filename)
    sniffed = _sniff_kind(data, max_bytes=config.get("attachment_max_bytes", _MB))
    kind = declared if declared in {"text", "delimited"} else sniffed
    return _parse_content(data, kind=kind, declared_kind=declared,
                          max_bytes=config.get("attachment_max_bytes", _MB), config=config)


def _zip(members: dict[str, bytes], *, encrypted: tuple[str, ...] = ()) -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, content in members.items():
            archive.writestr(ZipInfo(name), content)
    data = bytearray(buffer.getvalue())
    # zipfile cannot write encrypted members; set the flag in the central directory.
    position = data.find(b"PK\x01\x02")
    while position >= 0:
        name_length, extra_length, comment_length = struct.unpack_from("<HHH", data, position + 28)
        if data[position + 46:position + 46 + name_length].decode() in encrypted:
            data[position + 8] |= 0x1
        position = data.find(b"PK\x01\x02", position + 46 + name_length + extra_length + comment_length)
    return bytes(data)


def _members(parsed):
    return {block.text: block.payload["member_status"]
            for block in parsed.blocks if block.observation_type == "container_member"}


def _cfb(streams: dict[str, bytes]) -> bytes:
    """Minimal version-3 compound file; "/" in a name nests it in storages.

    Streams under 4096 bytes live in the mini stream, as in real Outlook files.
    """
    sector, mini, end, free = 512, 64, 0xFFFFFFFE, 0xFFFFFFFF
    children: dict[str, list[str]] = {"": []}
    for path in streams:
        parts = path.split("/")
        for depth in range(1, len(parts)):
            storage = "/".join(parts[:depth])
            if storage not in children:
                children[storage] = []
                children["/".join(parts[:depth - 1])].append(storage)
        children["/".join(parts[:-1])].append(path)
    order = [""]
    for name in order:
        order.extend(children.get(name, []))
    did = {name: index for index, name in enumerate(order)}

    mini_stream, minifat, large, starts = b"", [], [], {}
    for path, data in streams.items():
        if len(data) < 4096:
            starts[path] = len(mini_stream) // mini if data else end
            count = -(-len(data) // mini)
            minifat.extend(range(len(minifat) + 1, len(minifat) + count))
            if count:
                minifat.append(end)
            mini_stream += data.ljust(count * mini, b"\0")
        else:
            large.append(path)
    entries_sectors = -(-len(order) // 4)
    minifat_sectors = -(-len(minifat) * 4 // sector)
    mini_sectors = -(-len(mini_stream) // sector)
    large_sectors = [-(-len(streams[path]) // sector) for path in large]
    body = entries_sectors + minifat_sectors + mini_sectors + sum(large_sectors)
    fat_sectors = 1
    while fat_sectors * (sector // 4) < fat_sectors + body:
        fat_sectors += 1
    fat = [0xFFFFFFFD] * fat_sectors

    def chain(count):
        start = len(fat)
        fat.extend(range(start + 1, start + count))
        if count:
            fat.append(end)
        return start if count else end

    directory_start = chain(entries_sectors)
    minifat_start = chain(minifat_sectors)
    mini_start = chain(mini_sectors)
    for path, count in zip(large, large_sectors):
        starts[path] = chain(count)
    fat.extend([free] * (fat_sectors * (sector // 4) - len(fat)))

    def entry(name, kind, *, child=free, right=free, start=end, size=0):
        encoded = (name.rsplit("/", 1)[-1] + "\0").encode("utf-16-le") if kind else b""
        return (encoded.ljust(64, b"\0") + struct.pack("<HBB", len(encoded), kind, 1)
                + struct.pack("<III", free, right, child) + b"\0" * 36 + struct.pack("<IQ", start, size))

    entries = []
    for name in order:
        siblings = children[name.rsplit("/", 1)[0] if "/" in name else ""] if name else []
        right = did[siblings[siblings.index(name) + 1]] if name and siblings.index(name) + 1 < len(siblings) else free
        first_child = did[children[name][0]] if children.get(name) else free
        if name == "":
            entries.append(entry("Root Entry", 5, child=first_child, start=mini_start if mini_stream else end,
                                 size=len(mini_stream)))
        elif name in streams:
            entries.append(entry(name, 2, right=right, start=starts[name], size=len(streams[name])))
        else:
            entries.append(entry(name, 1, child=first_child, right=right, start=0))
    while len(entries) % 4:
        entries.append(entry("", 0))
    difat = list(range(fat_sectors)) + [free] * (109 - fat_sectors)
    header = (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 16
              + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6) + b"\0" * 6
              + struct.pack("<IIIIIIIII", 0, fat_sectors, directory_start, 0, 4096,
                            minifat_start if minifat else end, minifat_sectors, end, 0)
              + struct.pack("<109I", *difat))
    content = (struct.pack(f"<{len(fat)}I", *fat) + b"".join(entries)
               + struct.pack(f"<{len(minifat)}I", *minifat).ljust(minifat_sectors * sector, b"\xff")
               + mini_stream.ljust(mini_sectors * sector, b"\0")
               + b"".join(streams[path].ljust(count * sector, b"\0") for path, count in zip(large, large_sectors)))
    return header + content


def _word_document(pieces: list[tuple[str, bool]], *, story_lengths=None, encrypted=False) -> bytes:
    """FIB + piece table; each piece is (text, cp1252-compressed)."""
    text_offset = 0x800
    word = bytearray(text_offset)
    struct.pack_into("<HH", word, 0, 0xA5EC, 0x00C1)
    struct.pack_into("<H", word, 0x0A, 0x0200 | (0x0100 if encrypted else 0))
    struct.pack_into("<H", word, 32, 14)
    longs = 32 + 2 + 28
    struct.pack_into("<H", word, longs, 22)
    total = sum(len(text) for text, _ in pieces)
    for index, length in enumerate(story_lengths or [total]):
        struct.pack_into("<I", word, longs + 2 + 4 * (3 + index), length)
    pairs = longs + 2 + 88
    struct.pack_into("<H", word, pairs, 93)
    positions = [0]
    descriptors = b""
    for text, compressed in pieces:
        offset = len(word)
        if compressed:
            word += text.encode("cp1252")
            descriptors += struct.pack("<HIH", 0, 0x40000000 | (offset * 2), 0)
        else:
            word += text.encode("utf-16-le")
            descriptors += struct.pack("<HIH", 0, offset, 0)
        positions.append(positions[-1] + len(text))
    plc = struct.pack(f"<{len(positions)}I", *positions) + descriptors
    table = b"\x01" + struct.pack("<H", 2) + b"\0\0" + b"\x02" + struct.pack("<I", len(plc)) + plc
    struct.pack_into("<II", word, pairs + 2 + 33 * 8, 0, len(table))
    return _cfb({"WordDocument": bytes(word), "1Table": table})


class ArchiveExpansionTests(unittest.TestCase):
    def test_zip_members_are_recorded_and_readable_ones_extracted(self):
        nested = _zip({"inner/readme.txt": "內層說明：交期 2026/05/14".encode()})
        data = _zip({
            "docs/values.csv": b"PO,ETD\n470002138,2026-07-13\n",
            "notes.txt": b"First note.\n\nSecond note.",
            "photo.png": b"\x89PNG\r\n\x1a\n",
            "nested.zip": nested,
            "secret.txt": b"hidden",
        }, encrypted=("secret.txt",))
        self.assertEqual(_declared_kind("application/zip", None), "zip")
        self.assertEqual(_sniff_kind(data, max_bytes=_MB), "zip")
        parsed = _parse(data, "bundle.zip")
        self.assertEqual(_members(parsed), {
            "values.csv": "extracted", "notes.txt": "extracted", "photo.png": "unsupported",
            "nested.zip": "extracted", "readme.txt": "extracted", "secret.txt": "encrypted",
        })
        self.assertIn("attachment_container_incomplete", parsed.warnings)
        self.assertIn("attachment_document_partial_text_coverage", parsed.warnings)
        [table] = parsed.tables
        self.assertEqual(table.location_extra["container_members"][0]["name"], "values.csv")
        texts = {block.text: block for block in parsed.blocks if block.observation_type == "paragraph"}
        self.assertEqual({"First note.", "Second note.", "內層說明：交期 2026/05/14"}, set(texts))
        chain = texts["內層說明：交期 2026/05/14"].location["container_members"]
        self.assertEqual([member["name"] for member in chain], ["nested.zip", "readme.txt"])
        self.assertTrue(all(member["content_hash"].startswith("sha256:") for member in chain))
        member_names = [block.location["container_members"][0] for block in parsed.blocks
                        if block.observation_type == "container_member"]
        self.assertNotIn("docs/", str(member_names))  # directory components never leak
        self.assertTrue(all(member["name_fingerprint"].startswith("sha256:") for member in member_names))

    def test_archive_tables_become_located_observations(self):
        from formowl_ingestion.extractors.document.attachment import _observations
        from types import SimpleNamespace

        data = _zip({"a.csv": b"x,y\n1,2\n", "b.csv": b"x,y\n3,4\n"})
        parsed = _parse(data, "two.zip")
        source = SimpleNamespace(
            asset=SimpleNamespace(asset_id="asset_1", content_hash="sha256:" + "0" * 64,
                                  permission_scope={"workspace_id": "w"}),
            extractor_run_id="run_1", config={}, created_at="2026-10-24T00:00:00Z")
        observations = _observations(source, parsed.tables, blocks=parsed.blocks)
        cells = [item for item in observations if item.observation_type == "table_cell"]
        self.assertEqual({item.location["table_index"] for item in cells}, {1, 2})
        self.assertEqual({item.location["container_members"][0]["name"] for item in cells},
                         {"a.csv", "b.csv"})
        self.assertEqual(len({item.observation_id for item in observations}), len(observations))

    def test_member_byte_limit_depth_limit_and_member_limit(self):
        big = _zip({"big.txt": b"x" * 5000, "small.txt": b"ok"})
        self.assertEqual(_members(_parse(big, "big.zip", attachment_max_bytes=4096)),
                         {"big.txt": "byte_limit", "small.txt": "extracted"})
        deep = b"deep text"
        for level in range(4):
            deep = _zip({f"level{level}.zip" if level else "deep.txt": deep})
        statuses = _members(_parse(deep, "deep.zip"))
        self.assertIn("depth_limit", statuses.values())
        self.assertNotIn("deep.txt", statuses)
        many = _zip({f"{index}.txt": b"t" for index in range(5)})
        parsed = _parse(many, "many.zip", attachment_container_max_members=3)
        self.assertEqual(len(_members(parsed)), 3)
        self.assertIn("attachment_container_member_limit_reached", parsed.warnings)

    def test_gzip_is_not_inflated_once_the_shared_budget_is_spent(self):
        buffer = io.BytesIO()
        with gzip.GzipFile(filename="values.txt", mode="wb", fileobj=buffer, mtime=0) as stream:
            stream.write(b"y" * 3000)
        with mock.patch.object(gzip.GzipFile, "read", side_effect=AssertionError("inflated")):
            parsed = _parse_content(buffer.getvalue(), kind="gzip", declared_kind="gzip", max_bytes=_MB,
                                    config={}, archive_budget={"bytes": 0, "members": 5})
        self.assertEqual(_members(parsed), {"values.txt": "expansion_limit"})

    def test_embedded_msg_is_not_parsed_once_the_shared_budget_is_spent(self):
        parsed = _ParsedContent()
        parse = mock.Mock(side_effect=AssertionError("embedded msg was parsed"))
        self.assertTrue(_add_member(
            parsed, source_name="inner.msg", index=1, size=None, read=None,
            encrypted=False, container_format="msg", max_bytes=_MB, config={}, depth=0,
            budget={"bytes": 0, "members": 5}, parse=parse,
        ))
        parse.assert_not_called()
        self.assertEqual(_members(parsed), {"inner.msg": "expansion_limit"})

    def test_embedded_msg_text_charges_bytes_without_negative_budget(self):
        parsed = _ParsedContent()
        budget = {"bytes": 2, "members": 5}
        inner = _ParsedContent(blocks=[_TextBlock(
            observation_type="paragraph", text="three", location={"block_index": 1}, payload={},
        )])
        self.assertTrue(_add_member(
            parsed, source_name="inner.msg", index=1, size=None, read=None,
            encrypted=False, container_format="msg", max_bytes=_MB, config={}, depth=0,
            budget=budget, parse=lambda: inner,
        ))
        self.assertEqual(_members(parsed), {"inner.msg": "extracted"})
        self.assertEqual(budget["bytes"], 0)

    def test_unsupported_compression_method_fails_only_that_member(self):
        data = bytearray(_zip({"odd.txt": b"x", "fine.txt": b"fine"}))
        for marker in (b"PK\x03\x04", b"PK\x01\x02"):  # set odd.txt's method to Deflate64 (9)
            position = data.find(marker)
            struct.pack_into("<H", data, position + (8 if marker == b"PK\x03\x04" else 10), 9)
        parsed = _parse(bytes(data), "odd.zip")
        self.assertEqual(_members(parsed), {"odd.txt": "parse_failed", "fine.txt": "extracted"})

    def test_legacy_zip_member_names_are_decoded(self):
        class Info:
            flag_bits = 0
            filename = "交期表.csv".encode("cp950").decode("cp437")

        self.assertEqual(_zip_member_name(Info()), "交期表.csv")

        class UnicodeExtraInfo:  # zipfile already applied the Info-ZIP Unicode path field
            flag_bits = 0
            filename = "交期表.csv"

        self.assertEqual(_zip_member_name(UnicodeExtraInfo()), "交期表.csv")

    def test_legacy_code_page_text_and_csv_members(self):
        data = _zip({"notes.txt": "交期確認".encode("cp950"), "values.csv": "品號,交期\nA1,5/14\n".encode("cp950"),
                     "config.json": b'{"po": "470002138"}', "blob.txt": bytes(range(256)) * 4})
        parsed = _parse(data, "legacy.zip")
        self.assertEqual(_members(parsed), {"notes.txt": "extracted", "values.csv": "extracted",
                                            "config.json": "extracted", "blob.txt": "parse_failed"})
        self.assertIn("交期確認", [block.text for block in parsed.blocks])
        self.assertEqual(parsed.tables[0].rows[0][1][1][1], "交期")

    def test_gzip_and_tar_gz(self):
        buffer = io.BytesIO()
        with gzip.GzipFile(filename="values.csv", mode="wb", fileobj=buffer, mtime=0) as stream:
            stream.write(b"PO,ETD\n1,2\n")
        parsed = _parse(buffer.getvalue(), "values.csv.gz")
        self.assertEqual(_members(parsed), {"values.csv": "extracted"})
        self.assertEqual(len(parsed.tables), 1)
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w:gz") as archive:
            content = "封存內文".encode()
            info = tarfile.TarInfo("dir/notes.txt")
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
        parsed = _parse(tar_buffer.getvalue(), "bundle.tgz")
        chain = next(block for block in parsed.blocks if block.text == "封存內文").location["container_members"]
        # tarfile's gzip layer stores no FNAME, so the outer member gets a positional name.
        self.assertEqual([member["name"] for member in chain], ["member-1", "notes.txt"])

    def test_7z_and_rar_are_disclosed_unsupported(self):
        for magic, name, code in ((b"7z\xbc\xaf\x27\x1c\0\4", "a.7z", "7z"),
                                  (b"Rar!\x1a\x07\x01\0", "a.rar", "rar")):
            with self.subTest(name=name):
                parsed = _parse(magic + b"\0" * 64, name)
                self.assertFalse(parsed.blocks or parsed.tables)
                self.assertEqual(parsed.warnings, [f"attachment_document_{code}_parser_unavailable"])
        inner = _parse(_zip({"a.rar": b"Rar!\x1a\x07\x01\0" + b"\0" * 8}), "x.zip")
        self.assertEqual(_members(inner), {"a.rar": "unsupported"})

    def test_ooxml_zip_is_not_treated_as_archive(self):
        corrupt_docx = _zip({"other.xml": b"<x/>"})
        parsed = _parse_content(corrupt_docx, kind="zip", declared_kind="docx", max_bytes=_MB, config={})
        self.assertFalse(parsed.blocks)


@unittest.skipIf(xlrd is None, "xlrd (compound-file reader) unavailable")
class LegacyOfficeTests(unittest.TestCase):
    def test_word_97_text_fields_tables_and_stories(self):
        main = ("交期確認：PO 470002138\r"
                "\x13 HYPERLINK \"http://x\" \x14連結\x15 見附件\r"
                "品號\x07數量\x07\x07")
        footnote = "Footnote text\r"
        data = _word_document([(main, False), (footnote, True)],
                              story_lengths=[len(main), len(footnote)])
        self.assertEqual(_sniff_kind(data, max_bytes=_MB), "ole")
        parsed = _parse(data, "report.doc")
        texts = [(block.payload["story"], block.text) for block in parsed.blocks]
        self.assertEqual(texts, [("main", "交期確認：PO 470002138"), ("main", "連結 見附件"),
                                 ("main", "品號\t數量"), ("footnote", "Footnote text")])
        self.assertEqual({block.payload["source_format"] for block in parsed.blocks}, {"doc"})
        self.assertIn("doc_page_locations_unavailable", parsed.warnings)

    def test_undeclared_ole_word_is_detected_by_stream(self):
        parsed = _parse(_word_document([("Plain body\r", True)]), "attachment-1")
        self.assertEqual([block.text for block in parsed.blocks], ["Plain body"])

    def test_encrypted_and_malformed_word_are_withheld(self):
        encrypted = _parse(_word_document([("secret\r", True)], encrypted=True), "a.doc")
        self.assertEqual((encrypted.blocks, encrypted.warnings), ([], ["attachment_document_doc_encrypted"]))
        broken = _cfb({"WordDocument": b"\x34\x12" + b"\0" * 900, "1Table": b"\0" * 16})  # bad wIdent
        malformed = _parse(broken, "a.doc")
        self.assertEqual((malformed.blocks, malformed.warnings), ([], ["attachment_document_doc_parse_failed"]))

    def test_powerpoint_text_atoms(self):
        chars = "簡報標題".encode("utf-16-le")
        atoms = (struct.pack("<HHI", 0, 0x0FA0, len(chars)) + chars
                 + struct.pack("<HHI", 0, 0x0FA8, 9) + b"Body text")
        stream = struct.pack("<HHI", 0x000F, 0x03E8, len(atoms)) + atoms
        parsed = _parse(_cfb({"PowerPoint Document": stream}), "deck.ppt")
        self.assertEqual([block.text for block in parsed.blocks], ["簡報標題", "Body text"])
        self.assertEqual({block.payload["source_format"] for block in parsed.blocks}, {"ppt"})


def _utf16(text: str) -> bytes:
    return text.encode("utf-16-le")


def _outlook_message() -> bytes:
    sent = struct.pack("<Q", (1_783_000_000 + 11_644_473_600) * 10_000_000)  # 2026-07-02T13:46:40Z
    inner = "__attach_version1.0_#00000001/__substg1.0_3701000D/"
    return _cfb({
        "__properties_version1.0": b"\0" * 32 + struct.pack("<II", 0x00390040, 6) + sent,
        "__substg1.0_0037001F": _utf16("PO 470002138 交期確認"),
        "__substg1.0_0C1A001F": _utf16("Alice"),
        "__substg1.0_0C1F001F": _utf16("alice@example.com"),
        "__substg1.0_1000001F": _utf16("交期改為 2026/05/14。\r\n\r\n請確認附件。"),
        "__recip_version1.0_#00000000/__substg1.0_3001001F": _utf16("Bob"),
        "__recip_version1.0_#00000000/__substg1.0_39FE001F": _utf16("bob@example.com"),
        "__attach_version1.0_#00000000/__substg1.0_3707001F": _utf16("values.csv"),
        "__attach_version1.0_#00000000/__substg1.0_37010102": b"PO,ETD\n470002138,2026-07-13\n",
        "__attach_version1.0_#00000001/__substg1.0_3707001F": _utf16("forwarded.msg"),
        inner + "__properties_version1.0": b"\0" * 24,
        inner + "__substg1.0_0037001F": _utf16("Inner subject"),
        inner + "__substg1.0_10130102": b"<html><head><style>p{}</style></head><body><p>Inner &amp; body</p></body></html>",
    })


@unittest.skipIf(xlrd is None, "xlrd (compound-file reader) unavailable")
class OutlookMessageTests(unittest.TestCase):
    def test_msg_header_body_attachments_and_embedded_message(self):
        parsed = _parse(_outlook_message(), "mail.msg")
        header = next(block for block in parsed.blocks if block.payload.get("span_role") == "message_header")
        self.assertEqual(header.text, "From: Alice <alice@example.com>\nTo: Bob <bob@example.com>\n"
                                      "Date: 2026-07-02T13:46:40Z\nSubject: PO 470002138 交期確認")
        paragraphs = [block for block in parsed.blocks if block.observation_type == "paragraph"
                      and block.payload.get("span_role") != "message_header"]
        self.assertEqual([block.text for block in paragraphs],
                         ["交期改為 2026/05/14。", "請確認附件。", "Inner & body"])
        outer, inner = paragraphs[0].location["embedded_message"], paragraphs[2].location["embedded_message"]
        self.assertEqual((outer["subject"], outer["sender"], outer["depth"]),
                         ("PO 470002138 交期確認", "Alice <alice@example.com>", 1))
        self.assertEqual((inner["subject"], inner["depth"]), ("Inner subject", 2))
        self.assertEqual([member["name"] for member in paragraphs[2].location["container_members"]],
                         ["forwarded.msg"])
        [table] = parsed.tables
        self.assertEqual(table.location_extra["container_members"][0]["name"], "values.csv")
        self.assertEqual(table.location_extra["embedded_message"]["subject"], "PO 470002138 交期確認")
        self.assertEqual(_members(parsed), {"values.csv": "extracted", "forwarded.msg": "extracted"})
        self.assertNotIn("attachment_container_incomplete", parsed.warnings)

    def test_msg_inside_zip_and_compressed_rtf_body(self):
        from formowl_ingestion.extractors.document.attachment import _LZFU_DICTIONARY, _lzfu_decompress

        self.assertEqual(len(_LZFU_DICTIONARY), 207)
        literal = b"{\\rtf1 Hi} "  # 12 bytes: one full group of 8 + 4 literals
        body = b"\0" + literal[:8] + bytes([1 << 4]) + literal[8:]
        body += struct.pack(">H", ((207 + len(literal)) % 4096) << 4)  # end marker
        compressed = struct.pack("<IIII", len(body) + 12, len(literal), 0x75465A4C, 0) + body
        self.assertEqual(_lzfu_decompress(compressed, limit=4096), literal)
        with self.assertRaises(OverflowError):
            _lzfu_decompress(compressed, limit=len(literal) - 1)
        reference = b"\x01" + struct.pack(">H", 4) + b"\x01" + struct.pack(">H", (207 + 6) << 4)
        packed = struct.pack("<IIII", len(reference) + 12, 6, 0x75465A4C, 0) + reference
        self.assertEqual(_lzfu_decompress(packed, limit=4096), b"{\\rtf1")
        rtf = b"{\\rtf1\\ansi RTF only body.\\par}"
        stored = struct.pack("<IIII", len(rtf) + 12, len(rtf), 0x414C454D, 0) + rtf
        message = _cfb({"__properties_version1.0": b"\0" * 32, "__substg1.0_10090102": stored})
        parsed = _parse(_zip({"note.msg": message}), "bundle.zip")
        body = next(block for block in parsed.blocks if block.observation_type == "paragraph"
                    and block.payload.get("span_role") != "message_header")
        self.assertEqual(body.text, "RTF only body.")
        self.assertEqual(body.payload["body_format"], "rtf")
        self.assertEqual(body.location["container_members"][0]["name"], "note.msg")
        oversized = struct.pack("<IIII", len(rtf) + 12, 1 << 30, 0x414C454D, 0) + rtf
        message = _cfb({"__properties_version1.0": b"\0" * 32, "__substg1.0_10090102": oversized})
        parsed = _parse(message, "big.msg")
        self.assertIn("msg_body_byte_limit", parsed.warnings)
        self.assertIn("attachment_document_partial_text_coverage", parsed.warnings)


class EmlMessageTests(unittest.TestCase):
    def test_eml_in_zip_keeps_its_own_context_and_attachments(self):
        from email.message import EmailMessage

        inner = EmailMessage()
        inner["From"], inner["Subject"] = "Carol <carol@example.com>", "Inner note"
        inner.set_content("Inner body text.")
        message = EmailMessage()
        message["From"], message["To"] = "Alice <alice@example.com>", "Bob <bob@example.com>"
        message["Subject"], message["Date"] = "交期確認", "Thu, 02 Jul 2026 21:46:40 +0800"
        message.set_content("Please see attached.\n\nThanks.")
        message.add_attachment(b"PO,ETD\n470002138,2026-07-13\n", maintype="text", subtype="csv",
                               filename="values.csv")
        message.add_attachment(inner)
        parsed = _parse(_zip({"fwd.eml": message.as_bytes()}), "mail.zip")
        self.assertEqual(_members(parsed), {"fwd.eml": "extracted", "values.csv": "extracted",
                                            "embedded-2.eml": "extracted"})
        header = next(block for block in parsed.blocks if block.payload.get("span_role") == "message_header"
                      and "交期確認" in block.text)
        self.assertIn("Date: 2026-07-02T13:46:40Z", header.text)
        texts = {block.text: block for block in parsed.blocks if block.observation_type == "paragraph"}
        self.assertEqual(texts["Please see attached."].location["embedded_message"]["subject"], "交期確認")
        self.assertEqual(texts["Inner body text."].location["embedded_message"]["subject"], "Inner note")
        self.assertEqual(parsed.tables[0].location_extra["embedded_message"]["sender"],
                         "Alice <alice@example.com>")

    def test_non_message_eml_fails_closed(self):
        parsed = _parse(_zip({"x.eml": b"just some text without headers"}), "x.zip")
        self.assertEqual(_members(parsed), {"x.eml": "parse_failed"})


if __name__ == "__main__":
    unittest.main()
