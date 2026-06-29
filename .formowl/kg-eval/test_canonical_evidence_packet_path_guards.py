#!/usr/bin/env python3
"""Tests for canonical broad evidence packet path guards."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import unittest

import enterprise_multimodal_validation_validator as enterprise
import fair_external_baseline_run_validator as fair
import human_annotation_adjudication_validator as human
import production_adapter_path_validator as production


VALIDATORS = (
    (
        fair,
        "fair external baseline run packet",
    ),
    (
        human,
        "human annotation results packet",
    ),
    (
        enterprise,
        "enterprise multimodal validation packet",
    ),
    (
        production,
        "production adapter evidence packet",
    ),
)


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path, ignore_errors=True)


class PacketPathState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.was_symlink = path.is_symlink()
        self.symlink_target = path.readlink() if self.was_symlink else None
        self.was_file = path.exists() and path.is_file() and not self.was_symlink
        self.file_bytes = path.read_bytes() if self.was_file else None
        self.was_dir = path.exists() and path.is_dir() and not self.was_symlink

    def clear_for_test(self) -> None:
        if self.was_dir:
            raise AssertionError(f"refusing to replace directory: {self.path}")
        remove_path(self.path)

    def restore(self) -> None:
        if self.was_dir:
            return
        remove_path(self.path)
        if self.was_symlink:
            assert self.symlink_target is not None
            self.path.symlink_to(self.symlink_target)
        elif self.file_bytes is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_bytes(self.file_bytes)


class CanonicalEvidencePacketPathGuardTest(unittest.TestCase):
    def _target_path(self, module: object, name: str) -> Path:
        return module.INPUTS / "test_canonical_packet_path_guards" / name

    def _write_target(self, module: object, name: str) -> Path:
        target = self._target_path(module, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"artifact_id": "guard_target_should_not_be_read"}) + "\n",
            encoding="utf-8",
        )
        return target

    def test_canonical_input_packets_reject_symlinks(self) -> None:
        for module, packet_label in VALIDATORS:
            with self.subTest(packet=packet_label):
                packet_path = module.PACKET_PATH
                state = PacketPathState(packet_path)
                target = self._write_target(module, f"{packet_path.name}.symlink-target.json")
                try:
                    state.clear_for_test()
                    packet_path.symlink_to(target)

                    report = module.build_report()

                    self.assertFalse(report["passed"])
                    self.assertEqual(
                        report["blockers"],
                        [f"{packet_label} symlink not accepted"],
                    )
                    self.assertTrue(
                        all(value is False for value in report["claim_boundary"].values())
                    )
                finally:
                    state.restore()
                    remove_path(target.parent)

    def test_canonical_input_packets_reject_hardlink_aliases(self) -> None:
        for module, packet_label in VALIDATORS:
            with self.subTest(packet=packet_label):
                packet_path = module.PACKET_PATH
                state = PacketPathState(packet_path)
                target = self._write_target(module, f"{packet_path.name}.hardlink-target.json")
                try:
                    state.clear_for_test()
                    os.link(target, packet_path)

                    report = module.build_report()

                    self.assertFalse(report["passed"])
                    self.assertEqual(
                        report["blockers"],
                        [f"{packet_label} hardlink alias not accepted"],
                    )
                    self.assertTrue(
                        all(value is False for value in report["claim_boundary"].values())
                    )
                finally:
                    state.restore()
                    remove_path(target.parent)

    def test_canonical_input_packets_reject_directories(self) -> None:
        for module, packet_label in VALIDATORS:
            with self.subTest(packet=packet_label):
                packet_path = module.PACKET_PATH
                state = PacketPathState(packet_path)
                try:
                    state.clear_for_test()
                    packet_path.mkdir(parents=True, exist_ok=False)

                    report = module.build_report()

                    self.assertFalse(report["passed"])
                    self.assertEqual(
                        report["blockers"],
                        [f"{packet_label} is not a file"],
                    )
                    self.assertTrue(
                        all(value is False for value in report["claim_boundary"].values())
                    )
                finally:
                    state.restore()


if __name__ == "__main__":
    unittest.main()
