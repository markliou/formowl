from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
from unittest import mock

import _paths
from formowl_contract import Observation, sha256_json
from formowl_graph.candidates import read_and_store_source_unit
from formowl_graph.local_semantic_reader import LocalOllamaReader
from formowl_graph.storage import CandidateAtomStore, CandidateRelationStore, SemanticMetadataStore

sys.path.insert(0, str(_paths.ROOT))
_SCRIPT = _paths.ROOT / "scripts" / "issue56_reviewed_annotation_review.py"
_spec = importlib.util.spec_from_file_location("issue56_reviewed_annotation_review", _SCRIPT)
review = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(review)

TEXT = "PO No. 4500123 交期 2025/12/08\n請盡快確認"


def _record(**overrides) -> dict:
    record = {"record_type": "claim", "topic": "交期", "subject": None, "subject_label": None,
              "subject_quote": None, "item_or_row": None, "property": "交期", "value": "2025/12/08",
              "unit": None, "event_type": None, "state": None, "actor": None, "times": [],
              "evidence": [{"observation_id": "obs_review", "quote": "交期 2025/12/08"}], "confidence": 0.9}
    record.update(overrides)
    return record


class ReviewedAnnotationReviewTests(unittest.TestCase):
    def test_policy_approves_only_validated_atoms_that_name_a_target(self) -> None:
        temp_dir = _paths.fresh_test_dir("reviewed-annotation-review")
        observation = Observation(
            observation_id="obs_review", asset_id="asset_review_001", extractor_run_id="run_review_source",
            observation_type="email_body_segment", modality="mail", text=TEXT, location={"body_segment_index": 0},
            confidence=1.0, created_at="2026-10-25T00:00:00+00:00",
            permission_scope={"scope_type": "workspace", "visibility": "restricted", "scope_id": "ws_review"})
        flat = {"read_status": "complete", "relations": [], "records": [
            _record(subject="4500123", subject_quote={"observation_id": "obs_review", "quote": "PO No. 4500123"}),
            _record(property="待辦", value="確認", evidence=[{"observation_id": "obs_review", "quote": "請盡快確認"}])]}
        body = json.dumps({"model": "m", "done_reason": "stop",
                           "message": {"content": json.dumps(flat, ensure_ascii=False)}})
        reader = LocalOllamaReader("http://127.0.0.1:1", "m")
        with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(body.encode())):
            read_and_store_source_unit(
                source_unit_id="su_review_001", observations=[observation],
                expected_observation_hashes={"obs_review": sha256_json(observation.to_dict())},
                source_revision_fingerprint=sha256_json({"revision": 1}),
                permission_scope_fingerprint=sha256_json(observation.to_dict()["permission_scope"]),
                source_complete=True, extractor_run_id="semrun_review_001", ontology_revision_id="ontology_review",
                model_name="m", reasoning_effort="none", reader=reader.extract_structured_json,
                configuration=reader.configuration, semantic_metadata_store=SemanticMetadataStore(temp_dir),
                candidate_atom_store=CandidateAtomStore(temp_dir),
                candidate_relation_store=CandidateRelationStore(temp_dir))
        entries, counts = review.select_entries(temp_dir, {"semrun_review_001"}, 0.0)
        self.assertEqual(counts, {"ledger_annotated": 1, "approved": 1, "skipped_no_target": 1})
        atom = CandidateAtomStore(temp_dir).get(entries[0]["candidate_atom_id"])
        self.assertEqual(atom.properties["assertion"]["target"], "4500123")
        self.assertEqual(entries[0]["approved_identity_binding_fingerprints"],
                         [sha256_json(atom.properties["identity_bindings"][0])])
        self.assertEqual(review.select_entries(temp_dir, {"another_run"}, 0.0), ([], {}))
        self.assertEqual(review.select_entries(temp_dir, {"semrun_review_001"}, 0.95)[1]["skipped_low_confidence"], 1)

    def test_catalog_identity_tolerates_a_binding_without_type_surface(self) -> None:
        from formowl_mail.issue56_sealed_source import _reviewed_annotation_scope

        entries = [{"annotation_id": "catom_a", "target": "4500123",
                    "identity_bindings": [{"scope_role": "primary", "value_surface": "4500123"}]}]
        eligible, anchor, status = _reviewed_annotation_scope(entries, user_text="4500123 的交期")
        self.assertEqual((eligible, anchor, status), ({"catom_a"}, ("", "4500123"), "matched"))


if __name__ == "__main__":
    unittest.main()
