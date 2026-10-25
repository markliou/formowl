from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

import _paths
from formowl_contract import ContractValidationError, sha256_json
from formowl_retrieval.gateway import _SourcePhaseTrace

sys.path.insert(0, str(_paths.ROOT))
from formowl_gateway.issue56_sealed_source_loader import (  # noqa: E402
    _expand_reviewed_relations,
    _reviewed_annotation_catalog_trace_fields,
    _select_reviewed_annotation_sources,
    reviewed_relations_for,
)
from formowl_mail.issue56_sealed_source import (  # noqa: E402
    APPROVER_ACTOR,
    ReviewedAnnotationQueryBinding,
    _bind_reviewed_relations,
    reviewed_annotation_query_scope,
)
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
    def test_partial_identity_nomination_selects_only_source_bound_candidates_without_anchor(self) -> None:
        candidate_id = "atom_reviewed_candidate"
        source_hash = "sha256:" + "a" * 64
        revision = SimpleNamespace(
            reviewed_source_annotations=({
                "candidate_atom_id": candidate_id,
                "source_hashes": (source_hash,),
            },),
            reviewed_source_relations=(),
            safe_binding={"source_revision_sha256": BINDING["source_revision_sha256"]},
            reviewed_annotation_pin="sha256:" + "b" * 64,
        )
        catalog = {
            "source_revision_sha256": BINDING["source_revision_sha256"],
            "reviewed_annotation_pin": revision.reviewed_annotation_pin,
        }
        arguments = {
            "reviewed_annotation_ids": [candidate_id],
            "request_contract": {"query_class": "evidence_lookup"},
        }
        with mock.patch(
            "formowl_mail.human_uat_orchestrator.validated_reviewed_annotation_selection",
            return_value=None,
        ):
            selected, hashes, target = _select_reviewed_annotation_sources(
                revision, arguments=arguments, catalog=catalog, deadline=None,
            )

        self.assertEqual(selected, (candidate_id,))
        self.assertEqual(hashes, (source_hash,))
        self.assertIsNone(target)

    def test_selection_follows_updates_and_conflicts_but_not_restatements(self) -> None:
        revision = SimpleNamespace(reviewed_source_relations=(
            _relation("updates", "a", "b", ["sha256:quote_a"]), _relation("contradicts", "c", "b", ["sha256:c"]),
            _relation("same_fact", "d", "a"), _relation("refines", "e", "b")))
        selected, hashes = _expand_reviewed_relations(revision, {"b"})
        self.assertEqual(selected, {"a", "b", "c"})
        self.assertEqual(set(hashes), {"sha256:quote_a", "sha256:c"})
        stats = {}
        self.assertEqual(_expand_reviewed_relations(
            revision, {"b"}, trace_stats=stats), (selected, hashes))
        self.assertEqual(stats["expanded_atom_count"], 2)
        self.assertEqual(stats["relation_edge_count"], 2)
        self.assertEqual(len(stats["relation_id_hashes"]), 2)
        self.assertTrue(all(value.startswith("sha256:") for value in stats["relation_id_hashes"]))
        self.assertEqual(_expand_reviewed_relations(SimpleNamespace(reviewed_source_relations=()), {"b"}),
                         ({"b"}, ()))

    def test_catalog_trace_distinguishes_unavailable_unpaged_and_paged_view(self) -> None:
        self.assertEqual(_reviewed_annotation_catalog_trace_fields(None), {
            "catalog_provided": False, "view_status": "unavailable",
            "view_status_code": 255, "eligible_count": None,
        })
        self.assertEqual(_reviewed_annotation_catalog_trace_fields({"entries": [{}, {}]}), {
            "catalog_provided": True, "view_status": "unpaged",
            "view_status_code": 4, "eligible_count": 2,
        })
        self.assertEqual(_reviewed_annotation_catalog_trace_fields({
            "entries": [], "view_mode": "original_exact_identity_v1",
            "view_status": "partial_identity", "eligible_atom_count": 2,
        }), {
            "catalog_provided": True, "view_status": "partial_identity",
            "view_status_code": 5, "eligible_count": 2,
        })
        binding = ReviewedAnnotationQueryBinding(
            "query", json.dumps({"view_status": "unknown", "eligible_atom_count": 0}), "fingerprint",
        )
        with reviewed_annotation_query_scope(binding):
            self.assertEqual(_reviewed_annotation_catalog_trace_fields({"entries": []}), {
                "catalog_provided": True, "view_status": "unknown",
                "view_status_code": 0, "eligible_count": 0,
            })

    def test_private_trace_sanitizes_status_and_keeps_only_identifier_hashes(self) -> None:
        trace = _SourcePhaseTrace("sha256:" + "f" * 64)
        cell = trace.phase("project", view_status="partial_identity", view_status_code=5,
                           selected_count=1, selected_id_hashes=[sha256_json("atom_private_123")])
        cell.finish()
        serialized = trace.snapshot()
        self.assertNotIn("atom_private_123", serialized)
        details = json.loads(serialized)["details"][0]
        self.assertEqual(details["view_status"], "unknown")
        self.assertEqual(details["view_status_code"], 5)
        self.assertEqual(details["selected_count"], 1)
        self.assertEqual(details["selected_id_hashes"], [sha256_json("atom_private_123")])

    def test_evidence_context_lists_relations_by_atom_or_quoted_observation(self) -> None:
        revision = SimpleNamespace(reviewed_source_relations=(_relation("updates", "a", "b", ["sha256:q"]),))
        expected = [{"relation_type": "updates", "source_candidate_id": "a", "target_candidate_id": "b"}]
        self.assertEqual(reviewed_relations_for(revision, ["b"]), expected)
        self.assertEqual(reviewed_relations_for(revision, [], "sha256:q"), expected)
        self.assertEqual(reviewed_relations_for(revision, ["z"], "sha256:other"), [])


class RelationBindingTests(unittest.TestCase):
    setUp = ReconciliationTests.setUp  # two annotated delivery-date atoms (1/20, then 1/27)
    _run = ReconciliationTests._run
    _run_members = ReconciliationTests._run_members
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
