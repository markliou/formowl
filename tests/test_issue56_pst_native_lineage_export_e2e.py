from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "issue56_pst_native_lineage_export.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "issue56_pst_native_lineage_export",
        SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("native lineage module unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


native = _load_module()


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _row(
    *,
    kind: str,
    folder: str,
    message: str,
    message_data: str,
    attachment: str = "0000000000000000",
    disposition: str,
    status: str,
    reason: str = "none",
    path: Path | None = None,
    content: bytes | None = None,
) -> list[str]:
    return [
        native.SIDECAR_SCHEMA,
        kind,
        folder,
        message,
        message_data,
        attachment,
        disposition,
        status,
        reason,
        path.as_posix().encode("utf-8").hex() if path is not None else "-",
        _hash_bytes(content) if content is not None else "-",
        str(len(content) if content is not None else 0),
    ]


class Issue56PstNativeLineageExportE2E(unittest.TestCase):
    def _fixture(self, root: Path) -> dict[str, Path | str]:
        export_root = root / "export"
        export_root.mkdir()
        message_one = export_root / "private-message-one"
        message_two = export_root / "private-message-two"
        attachment = export_root / "private-attachment"
        message_one_bytes = b"From: synthetic@example.invalid\n\nalpha"
        message_two_bytes = b"From: synthetic@example.invalid\n\nbeta"
        attachment_bytes = b"authorized synthetic attachment"
        message_one.write_bytes(message_one_bytes)
        message_two.write_bytes(message_two_bytes)
        attachment.write_bytes(attachment_bytes)
        pst = root / "synthetic.pst"
        binary = root / "readpst"
        runtime = root / "libpst.so.4"
        pst.write_bytes(b"synthetic authorized pst fixture")
        binary.write_bytes(b"synthetic direct-link binary")
        runtime.write_bytes(b"synthetic pinned runtime")
        sidecar = root / "lineage.private.tsv"
        rows = [
            _row(
                kind="folder",
                folder="0000000000000000",
                message="0000000000000100",
                message_data="0000000000000200",
                disposition="traversed",
                status="passed",
            ),
            _row(
                kind="message",
                folder="0000000000000100",
                message="0000000000000101",
                message_data="0000000000000201",
                disposition="export_attempt",
                status="started",
            ),
            _row(
                kind="attachment",
                folder="0000000000000100",
                message="0000000000000101",
                message_data="0000000000000201",
                attachment="0000000000000301",
                disposition="separate_exported",
                status="passed",
                path=attachment,
                content=attachment_bytes,
            ),
            _row(
                kind="message",
                folder="0000000000000100",
                message="0000000000000101",
                message_data="0000000000000201",
                disposition="exported",
                status="passed",
                path=message_one,
                content=message_one_bytes,
            ),
            _row(
                kind="message",
                folder="0000000000000100",
                message="0000000000000102",
                message_data="0000000000000202",
                disposition="export_attempt",
                status="started",
            ),
            _row(
                kind="message",
                folder="0000000000000100",
                message="0000000000000102",
                message_data="0000000000000202",
                disposition="exported",
                status="passed",
                path=message_two,
                content=message_two_bytes,
            ),
        ]
        sidecar.write_text(
            "\t".join(native.SIDECAR_HEADER)
            + "\n"
            + "\n".join("\t".join(row) for row in rows)
            + "\n",
            encoding="utf-8",
        )
        return {
            "pst": pst,
            "export_root": export_root,
            "sidecar": sidecar,
            "binary": binary,
            "runtime": runtime,
            "expected_asset_sha256": f"sha256:{_hash_bytes(pst.read_bytes())}",
        }

    def test_existing_native_export_round_trip_and_safe_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = self._fixture(root)
            private_output = root / "private-manifest.json"
            public_output = root / "public-report.json"
            command = [
                sys.executable,
                str(SCRIPT),
                "--pst",
                str(fixture["pst"]),
                "--export-root",
                str(fixture["export_root"]),
                "--sidecar",
                str(fixture["sidecar"]),
                "--parser-binary",
                str(fixture["binary"]),
                "--runtime-library",
                str(fixture["runtime"]),
                "--private-manifest-output",
                str(private_output),
                "--public-report-output",
                str(public_output),
                "--expected-asset-sha256",
                str(fixture["expected_asset_sha256"]),
            ]
            completed = subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            public_report = json.loads(completed.stdout)
            self.assertEqual(public_report["status"], "passed")
            self.assertEqual(public_report["counts"]["message_occurrence_count"], 2)
            self.assertEqual(
                public_report["counts"]["attachment_output_occurrence_count"],
                1,
            )
            self.assertNotIn(str(root), completed.stdout)
            self.assertNotIn("private-message", completed.stdout)
            native.validate_private_manifest(json.loads(private_output.read_text(encoding="utf-8")))
            native.validate_public_report(json.loads(public_output.read_text(encoding="utf-8")))

    def test_tampered_output_and_missing_message_final_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = self._fixture(root)
            export_files = sorted(Path(fixture["export_root"]).iterdir())
            export_files[0].write_bytes(b"tampered")
            with self.assertRaisesRegex(
                RuntimeError,
                "native_lineage_output_(byte_count|content_hash)_drift",
            ):
                native.build_manifest_from_existing_native_export(
                    pst_path=Path(fixture["pst"]),
                    export_root=Path(fixture["export_root"]),
                    sidecar_path=Path(fixture["sidecar"]),
                    parser_binary_path=Path(fixture["binary"]),
                    runtime_library_path=Path(fixture["runtime"]),
                    expected_asset_sha256=str(fixture["expected_asset_sha256"]),
                )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = self._fixture(root)
            sidecar = Path(fixture["sidecar"])
            lines = sidecar.read_text(encoding="utf-8").splitlines()
            sidecar.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(
                RuntimeError,
                "native_lineage_message_start_final_mismatch",
            ):
                native.build_manifest_from_existing_native_export(
                    pst_path=Path(fixture["pst"]),
                    export_root=Path(fixture["export_root"]),
                    sidecar_path=sidecar,
                    parser_binary_path=Path(fixture["binary"]),
                    runtime_library_path=Path(fixture["runtime"]),
                    expected_asset_sha256=str(fixture["expected_asset_sha256"]),
                )


if __name__ == "__main__":
    unittest.main()
