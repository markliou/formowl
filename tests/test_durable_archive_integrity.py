from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = ROOT / "docs" / "archive"
SNAPSHOT_FILE_COUNTS = {
    "2026-07-11": 4,
    "2026-07-16": 1,
    "2026-07-19": 1,
    "2026-07-21": 1,
    "2026-08-13": 1,
    "2026-08-18": 28,
    "2026-08-25": 1,
    "2026-10-01": 1,
    "2026-10-04": 1,
    "2026-10-07T081844Z-uat-source-start-truth": 3,
}
HISTORICAL_BOARD_SNAPSHOT_ROOT = ARCHIVE_ROOT / "2026-07-11"
POLICY_SNAPSHOT = "2026-10-07T014115Z-worker-policy-cleanup"
POLICY_SNAPSHOT_LINE_COUNTS = {
    "kg-research-agent.md": 187,
    "handoff-log.md": 332,
}


class DurableArchiveIntegrityTests(unittest.TestCase):
    def _assert_snapshot_file(
        self,
        snapshot_root: Path,
        path_root: Path,
        relative_path: str,
        byte_count: int,
        line_count: int,
        sha256: str,
    ) -> Path:
        path = Path(relative_path)
        self.assertFalse(path.is_absolute(), relative_path)
        self.assertNotIn("..", path.parts, relative_path)
        archive_path = (path_root / path).resolve()
        self.assertTrue(
            archive_path.is_relative_to(snapshot_root.resolve()),
            f"archive path escaped snapshot root: {relative_path}",
        )
        payload = archive_path.read_bytes()
        self.assertEqual(len(payload), byte_count, archive_path)
        self.assertEqual(len(payload.decode("utf-8").splitlines()), line_count, archive_path)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), sha256, archive_path)
        return archive_path

    def test_manifest_matches_every_lossless_snapshot(self) -> None:
        discovered_dates = {
            manifest.parent.name for manifest in ARCHIVE_ROOT.glob("*/manifest.json")
        }
        self.assertEqual(discovered_dates, set(SNAPSHOT_FILE_COUNTS))

        for archive_date, expected_file_count in SNAPSHOT_FILE_COUNTS.items():
            snapshot_root = ARCHIVE_ROOT / archive_date
            manifest = json.loads((snapshot_root / "manifest.json").read_text(encoding="utf-8"))

            path_root = ROOT
            digest_prefix = ""
            if archive_date == "2026-10-04":
                self.assertEqual(set(manifest), {"snapshot_date", "snapshot_scope", "files"})
                self.assertEqual(manifest["snapshot_date"], archive_date)
                self.assertEqual(
                    manifest["snapshot_scope"],
                    "active handoff log immediately before retention trim",
                )
                source_key, path_key, bytes_key, lines_key = (
                    "source_path", "archive_path", "byte_count", "line_count"
                )
            elif archive_date == "2026-10-07T081844Z-uat-source-start-truth":
                self.assertEqual(set(manifest), {"snapshot_id", "files"})
                self.assertEqual(manifest["snapshot_id"], "2026-10-07T081844Z")
                source_key, path_key, bytes_key, lines_key = None, "path", "bytes", "lines"
                path_root = snapshot_root
                digest_prefix = "sha256:"
            else:
                expected_keys = {"archive_date", "files"}
                if archive_date == "2026-08-18":
                    expected_keys.add("purpose")
                self.assertEqual(set(manifest), expected_keys)
                self.assertEqual(manifest["archive_date"], archive_date)
                source_key, path_key, bytes_key, lines_key = "source", "archive", "bytes", "lines"
            self.assertEqual(len(manifest["files"]), expected_file_count)
            archived_paths: set[Path] = set()
            for item in manifest["files"]:
                expected_keys = {path_key, bytes_key, lines_key, "sha256"}
                if source_key is not None:
                    expected_keys.add(source_key)
                    source_path = Path(item[source_key])
                    self.assertFalse(source_path.is_absolute())
                    self.assertNotIn("..", source_path.parts)
                    self.assertTrue((ROOT / source_path).resolve().is_relative_to(ROOT))
                self.assertEqual(set(item), expected_keys)
                self.assertRegex(item["sha256"], rf"^{digest_prefix}[0-9a-f]{{64}}$")
                archive_path = self._assert_snapshot_file(
                    snapshot_root, path_root, item[path_key],
                    item[bytes_key], item[lines_key],
                    item["sha256"][len(digest_prefix):],
                )
                self.assertNotIn(archive_path, archived_paths)
                archived_paths.add(archive_path)

    def test_worker_policy_readme_matches_both_lossless_snapshots(self) -> None:
        snapshot_root = ARCHIVE_ROOT / POLICY_SNAPSHOT
        readme = (snapshot_root / "README.md").read_text(encoding="utf-8")
        rows = re.findall(
            r"^\| ([^|]+) \| ([0-9]+) \| ([0-9a-f]{64}) \|$", readme, re.MULTILINE
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual({row[0] for row in rows}, set(POLICY_SNAPSHOT_LINE_COUNTS))
        for relative_path, byte_count, sha256 in rows:
            self._assert_snapshot_file(
                snapshot_root, snapshot_root, relative_path, int(byte_count),
                POLICY_SNAPSHOT_LINE_COUNTS[relative_path], sha256,
            )

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
        archived = (HISTORICAL_BOARD_SNAPSHOT_ROOT / "implementation-task-breakdown.md").read_text(
            encoding="utf-8"
        )
        active = (ROOT / "docs" / "implementation-task-breakdown.md").read_text(encoding="utf-8")

        self.assertEqual(len(re.findall(r"^\s*- \[x\]", archived, re.MULTILINE)), 147)
        self.assertEqual(len(re.findall(r"^\s*- \[ \]", archived, re.MULTILINE)), 1)
        archived_unchecked = set(re.findall(r"^\s*- \[ \] (.+)$", archived, re.MULTILINE))
        active_unchecked = set(re.findall(r"^\s*- \[ \] (.+)$", active, re.MULTILINE))
        self.assertGreaterEqual(len(active_unchecked), len(archived_unchecked))
        self.assertTrue(archived_unchecked.issubset(active_unchecked))


if __name__ == "__main__":
    unittest.main()
