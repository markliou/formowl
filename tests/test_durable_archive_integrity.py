from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = ROOT / "docs" / "archive"
SNAPSHOT_ROOT = ARCHIVE_ROOT / "2026-07-11"


class DurableArchiveIntegrityTests(unittest.TestCase):
    def test_manifest_matches_every_lossless_snapshot(self) -> None:
        manifest = json.loads((SNAPSHOT_ROOT / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["archive_date"], "2026-07-11")
        self.assertEqual(len(manifest["files"]), 4)
        for item in manifest["files"]:
            archive_path = ROOT / item["archive"]
            payload = archive_path.read_bytes()
            self.assertEqual(len(payload), item["bytes"], archive_path)
            self.assertEqual(len(payload.decode("utf-8").splitlines()), item["lines"])
            self.assertEqual(hashlib.sha256(payload).hexdigest(), item["sha256"])

    def test_archive_index_links_and_startup_paths_exist(self) -> None:
        archive_index = (ARCHIVE_ROOT / "README.md").read_text(encoding="utf-8")
        for relative_link in re.findall(r"\[[^]]+\]\(([^)]+)\)", archive_index):
            self.assertTrue((ARCHIVE_ROOT / relative_link).exists(), relative_link)

        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        startup_paths = re.findall(r"`((?:docs|SPEC|RESOURCE)[^`]+\.md)`", agents)
        for startup_path in startup_paths:
            if "*" in startup_path:
                continue
            self.assertTrue((ROOT / startup_path).exists(), startup_path)

    def test_active_files_obey_retention_and_archive_is_not_current_authority(self) -> None:
        active_limits = {
            "docs/implementation-task-breakdown.md": 400,
            "docs/agent-goals/kg-research-agent.md": 180,
            "docs/agent-goals/system-backbone-agent.md": 180,
            "docs/agent-goals/handoff-log.md": 300,
        }
        for relative_path, limit in active_limits.items():
            line_count = len((ROOT / relative_path).read_text(encoding="utf-8").splitlines())
            self.assertLessEqual(line_count, limit, relative_path)

        archive_index = (ARCHIVE_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Lifecycle label: `immutable-history`", archive_index)
        self.assertIn(
            "not current task or role instructions",
            " ".join(archive_index.split()),
        )
        for relative_path in (
            "docs/implementation-task-breakdown.md",
            "docs/agent-goals/kg-research-agent.md",
            "docs/agent-goals/system-backbone-agent.md",
        ):
            self.assertNotIn(
                "Lifecycle label: `immutable-history`",
                (ROOT / relative_path).read_text(encoding="utf-8"),
            )

    def test_archived_board_preserves_historical_checklist_states(self) -> None:
        archived = (SNAPSHOT_ROOT / "implementation-task-breakdown.md").read_text(encoding="utf-8")
        active = (ROOT / "docs" / "implementation-task-breakdown.md").read_text(encoding="utf-8")
        archived_unchecked = re.findall(r"^\s*- \[ \] (.+)$", archived, re.MULTILINE)
        active_unchecked = re.findall(r"^\s*- \[ \] (.+)$", active, re.MULTILINE)

        self.assertEqual(len(re.findall(r"^\s*- \[x\]", archived, re.MULTILINE)), 147)
        self.assertEqual(
            archived_unchecked,
            ["Complete the full KG real-evidence objective across sessions."],
        )
        self.assertEqual(
            active_unchecked,
            [
                *archived_unchecked,
                "Implement issue #20 Google-backed ChatGPT MCP OAuth identity mapping and",
            ],
        )


if __name__ == "__main__":
    unittest.main()
