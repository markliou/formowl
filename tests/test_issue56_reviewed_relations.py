from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from types import SimpleNamespace
import unittest

import _paths
from formowl_contract import ContractValidationError, sha256_json

sys.path.insert(0, str(_paths.ROOT))
from formowl_gateway.issue56_sealed_source_loader import _expand_reviewed_relations, reviewed_relations_for  # noqa: E402
from formowl_mail.issue56_sealed_source import APPROVER_ACTOR, _bind_reviewed_relations  # noqa: E402
from test_graph_reconciliation import ReconciliationTests  # noqa: E402

_spec = importlib.util.spec_from_file_location("review", _paths.ROOT / "scripts" / "issue56_reviewed_annotation_review.py")
review = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(review)

BINDING = {"source_revision_sha256": "sha256:" + "1" * 64, "source_authority_fingerprint": "sha256:" + "2" * 64,
           "source_session_binding_fingerprint": "sha256:" + "3" * 64}


def _relation(kind, source, target, evidence=()):
    return {"candidate_relation_id": f"crel_{source}_{target}", "relation_type": kind,
            "source_candidate_atom_id": source, "target_candidate_atom_id": target,
            "evidence_hashes": tuple(evidence), "evidence_observation_ids": ()}


class RelationSelectionTests(unittest.TestCase):
    def test_selection_follows_updates_and_conflicts_but_not_restatements(self) -> None:
        revision = SimpleNamespace(reviewed_source_relations=(
            _relation("updates", "a", "b", ["sha256:quote_a"]), _relation("contradicts", "c", "b", ["sha256:c"]),
            _relation("same_fact", "d", "a"), _relation("refines", "e", "b")))
        selected, hashes = _expand_reviewed_relations(revision, {"b"})
        self.assertEqual(selected, {"a", "b", "c"})
        self.assertEqual(set(hashes), {"sha256:quote_a", "sha256:c"})
        self.assertEqual(_expand_reviewed_relations(SimpleNamespace(reviewed_source_relations=()), {"b"}),
                         ({"b"}, ()))

    def test_evidence_context_lists_relations_by_atom_or_quoted_observation(self) -> None:
        revision = SimpleNamespace(reviewed_source_relations=(_relation("updates", "a", "b", ["sha256:q"]),))
        expected = [{"relation_type": "updates", "source_candidate_id": "a", "target_candidate_id": "b"}]
        self.assertEqual(reviewed_relations_for(revision, ["b"]), expected)
        self.assertEqual(reviewed_relations_for(revision, [], "sha256:q"), expected)
        self.assertEqual(reviewed_relations_for(revision, ["z"], "sha256:other"), [])


class RelationBindingTests(unittest.TestCase):
    setUp = ReconciliationTests.setUp  # two annotated delivery-date atoms (1/20, then 1/27)
    _run = ReconciliationTests._run
    def _receipt(self, entries) -> dict:
        receipt = {"artifact_id": "formowl_uat_relation_review_receipt_v1", "reviewer_user_id": APPROVER_ACTOR,
                   "decision": "approve_for_uat_source_selection", **BINDING, "entries": entries}
        path = self.temp_dir / f"relation-receipt-{len(list(self.temp_dir.glob('relation-receipt-*')))}.json"
        data = json.dumps(receipt).encode()
        path.write_bytes(data)
        path.chmod(0o600)
        return {"relation_receipt_pages": [{"review_receipt_path": str(path),
                                            "review_receipt_sha256": "sha256:" + hashlib.sha256(data).hexdigest()}]}

    def _revision(self):
        observations = {**self.old.observations, **self.new.observations}
        records = SimpleNamespace(observation_hash=lambda oid: sha256_json(observations[oid]))
        return SimpleNamespace(safe_binding=BINDING, source_records=records)

    def test_reviewed_update_binds_only_with_both_endpoints_reviewed_and_unchanged_hashes(self) -> None:
        self._run([{"source": 1, "target": 0, "relation_type": "updates", "confidence": 0.8,
                    "evidence": [{"observation_id": "obs_new", "quote": "交期改為 1/27"}]}])
        both = {self.old.atom.candidate_atom_id, self.new.atom.candidate_atom_id}
        entries, counts = review.select_relation_entries(self.temp_dir, {"recon_run_001"}, both)
        self.assertEqual(counts, {"approved_updates": 1})
        relations, pages = _bind_reviewed_relations(self._receipt(entries), self._revision(), self.temp_dir, both)
        self.assertEqual(len(pages), 1)
        self.assertEqual((relations[0]["relation_type"], relations[0]["source_candidate_atom_id"]),
                         ("updates", self.new.atom.candidate_atom_id))
        self.assertEqual(relations[0]["evidence_observation_ids"], ("obs_new",))
        with self.assertRaisesRegex(ContractValidationError, "pin mismatch"):
            _bind_reviewed_relations(self._receipt(entries), self._revision(), self.temp_dir,
                                     {self.new.atom.candidate_atom_id})
        tampered = [{**entries[0], "candidate_relation_sha256": "sha256:" + "0" * 64}]
        with self.assertRaisesRegex(ContractValidationError, "pin mismatch"):
            _bind_reviewed_relations(self._receipt(tampered), self._revision(), self.temp_dir, both)
        self.assertEqual(review.select_relation_entries(self.temp_dir, {"recon_run_001"},
                                                        {self.new.atom.candidate_atom_id})[1],
                         {"skipped_endpoint_not_approved": 1})

    def test_no_relation_pages_keeps_the_binding_unchanged(self) -> None:
        self.assertEqual(_bind_reviewed_relations({}, self._revision(), self.temp_dir, set()), ((), []))


if __name__ == "__main__":
    unittest.main()
