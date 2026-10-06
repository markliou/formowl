from __future__ import annotations

import json
from pathlib import Path
import unittest

import _paths  # noqa: F401
from formowl_contract import sha256_json

import scripts.real_pst_domain_hard_100_lock as lock_script


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = (
    ROOT / "experiments" / "kg_ontology_v2_coordination" / "real_pst_domain_hard_100.lock.json"
)


class RealPstDomainHard100LockTests(unittest.TestCase):
    def test_exact_locked_manifest_passes(self) -> None:
        lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        manifest = _fixture_manifest(lock)
        lock["case_set"]["private_manifest_sha256_json"] = sha256_json(manifest)
        lock["case_set"]["case_definition_sha256_json"] = sha256_json(
            [
                {field: case.get(field) for field in lock_script.CASE_FIELDS}
                for case in manifest["cases"]
            ]
        )
        lock["case_set"]["case_id_sequence_sha256_json"] = sha256_json(
            [case["case_id"] for case in manifest["cases"]]
        )

        report = lock_script.validate_frozen_manifest(manifest, lock)

        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["claim_boundary"]["same_private_questions_locked"])
        self.assertFalse(report["claim_boundary"]["methodology_ready"])

    def test_changed_question_is_blocked(self) -> None:
        lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        manifest = _fixture_manifest(lock)

        report = lock_script.validate_frozen_manifest(manifest, lock)

        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["claim_boundary"]["same_private_questions_locked"])
        self.assertEqual(len(report["safe_outputs"]["blocker_hashes"]), 3)
        self.assertNotIn("query text", json.dumps(report))


def _fixture_manifest(lock: dict) -> dict:
    cases = []
    result_kinds = ["owner_match"] * 80 + ["no_match"] * 10 + ["permission_denied"] * 10
    for index, result_kind in enumerate(result_kinds):
        cases.append(
            {
                "case_id": f"case_{index:03d}",
                "domain": f"domain_{index % 10}",
                "pattern": f"pattern_{index % 4}",
                "intent_kind": "fixture",
                "result_kind": result_kind,
                "query_text": f"private fixture query {index}",
                "requester_user_id": "fixture_user",
                "limit": 5,
                "required_match_count": 1,
                "required_source_observation_ids": [f"obs_{index:03d}"],
                "forbidden_source_observation_ids": [],
            }
        )
    return {
        "manifest_type": "mail_full_pst_domain_hard_case_manifest_private",
        "archive_sha256": lock["source_fixture"]["archive_sha256"],
        "case_count": 100,
        "cases": cases,
        "policy_version": lock["policy"]["case_policy_version"],
    }


if __name__ == "__main__":
    unittest.main()
