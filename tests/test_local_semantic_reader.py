from __future__ import annotations

import io
import json
import unittest
from unittest import mock

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, Observation, sha256_json
from formowl_graph.candidates import read_and_store_source_unit
from formowl_graph.local_semantic_reader import Adapter, LocalOllamaReader, presented
from formowl_graph.storage import CandidateAtomStore, CandidateRelationStore, SemanticMetadataStore

BODY = "From: Kc Yeh 葉坤杰 ( 中光電 )\nPO No. 4500123 交期 2025/12/08\nPO No. 4500124 交期 2025/12/09"


def _observation(observation_id: str, text: str, payload: dict | None = None) -> Observation:
    return Observation(
        observation_id=observation_id, asset_id="asset_local_reader_001",
        extractor_run_id="run_local_reader_source_001", observation_type="email_body_segment",
        modality="mail", text=text,
        location={"message_occurrence_id": "mailocc_0123456789abcdef0123", "body_segment_index": 0},
        confidence=1.0, created_at="2026-10-25T00:00:00+00:00", payload=payload,
        permission_scope={"scope_type": "workspace", "visibility": "restricted", "scope_id": "ws_local_reader"},
    )


def _sources(*observations: Observation) -> dict:
    return {o.observation_id: o.to_dict() for o in observations}


def _record(**overrides) -> dict:
    record = {"record_type": "claim", "topic": "交期", "subject": None, "subject_label": None,
              "subject_quote": None, "item_or_row": None, "property": "交期", "value": "2025/12/08",
              "unit": None, "event_type": None, "state": None, "actor": None, "times": [],
              "evidence": [{"observation_id": "obs_body", "quote": "PO No. 4500123 交期 2025/12/08"}],
              "confidence": 0.9}
    record.update(overrides)
    return record


class AdapterLocationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = Adapter(_sources(_observation("obs_body", BODY)))

    def test_exact_quote_gets_its_field_path(self) -> None:
        span = self.adapter.span({"observation_id": "obs_body", "quote": "交期 2025/12/08"})
        self.assertEqual((span["field_path"], span["quote"], span["occurrence_index"]),
                         (["text"], "交期 2025/12/08", None))
        self.assertEqual(self.adapter.relocated, 0)

    def test_whitespace_only_difference_maps_to_the_unique_source_text(self) -> None:
        span = self.adapter.span({"observation_id": "obs_body", "quote": "葉坤杰 (中光電)"})
        self.assertEqual(span["quote"], "葉坤杰 ( 中光電 )")
        self.assertEqual(self.adapter.relocated, 1)

    def test_other_differences_and_repeats_are_left_for_the_validator(self) -> None:
        changed = self.adapter.span({"observation_id": "obs_body", "quote": "葉坤杰（中光電）"})
        self.assertEqual(changed["quote"], "葉坤杰（中光電）")
        repeated = self.adapter.span({"observation_id": "obs_body", "quote": "PONo."})
        self.assertEqual(repeated["quote"], "PONo.")
        self.assertEqual(self.adapter.relocated, 0)

    def test_subject_outside_its_quote_is_located_in_the_cited_observation(self) -> None:
        data = self.adapter.convert({"records": [_record(
            subject="Kc Yeh 葉坤杰 ( 中光電 )",
            subject_quote={"observation_id": "obs_body", "quote": "PO No. 4500123"})]})
        identity = data["identities"][0]
        self.assertEqual(identity["value_surface"], "Kc Yeh 葉坤杰 ( 中光電 )")
        self.assertEqual(identity["evidence"][0]["quote"], "Kc Yeh 葉坤杰 ( 中光電 )")
        self.assertEqual(data["atoms"][0]["assertion"]["target"], "Kc Yeh 葉坤杰 ( 中光電 )")
        self.assertEqual(self.adapter.counts["surface_located"], 1)

    def test_invented_label_and_subject_are_cleared_but_the_fact_is_kept(self) -> None:
        data = self.adapter.convert({"records": [
            _record(subject="4500123", subject_label="訂單編號",
                    subject_quote={"observation_id": "obs_body", "quote": "PO No. 4500123"}),
            _record(subject="地圖車驗證", subject_quote=None)]})
        self.assertIsNone(data["identities"][0]["type_surface"])
        self.assertEqual(len(data["identities"]), 1)
        self.assertIsNone(data["atoms"][1]["assertion"]["target"])
        self.assertEqual(data["atoms"][1]["assertion"]["value"], "2025/12/08")
        self.assertEqual(self.adapter.counts["invented_label_cleared"], 1)
        self.assertEqual(self.adapter.counts["invented_subject_cleared"], 1)

    def test_model_view_drops_only_opaque_hashes_and_ids(self) -> None:
        observation = _observation("obs_body", BODY, payload={
            "message_fingerprint": "sha256:" + "a" * 64, "thread_id": "mailthread_0123456789abcdef",
            "header_value": "Kc Yeh"})
        unit = {"observations": [observation.to_dict()], "focus_observation_ids": ["obs_body"],
                "context_observation_ids": []}
        view = presented(unit)["observations"][0]
        self.assertEqual(view["payload"], {"header_value": "Kc Yeh"})
        self.assertEqual(view["text"], BODY)
        self.assertNotIn("permission_scope", view)


class LocalReaderContractTests(unittest.TestCase):
    def test_converted_output_passes_the_unchanged_contract_validator(self) -> None:
        temp_dir = _paths.fresh_test_dir("local-semantic-reader")
        observation = _observation("obs_body", BODY)
        flat = {"read_status": "complete", "read_observation_ids": ["obs_body"], "relations": [],
                "records": [_record(
                    subject="4500123", subject_label="PO No.",
                    subject_quote={"observation_id": "obs_body", "quote": "PO No. 4500123"},
                    times=[{"role": "due", "raw": "2025/12/08", "normalized": "2025-12-08",
                            "precision": "day",
                            "quote": {"observation_id": "obs_body", "quote": "交期 2025/12/08"}}])]}
        body = json.dumps({"model": "local-model", "done_reason": "stop", "prompt_eval_count": 10,
                           "eval_count": 20, "message": {"content": json.dumps(flat, ensure_ascii=False)}})
        reader = LocalOllamaReader("http://127.0.0.1:1", "local-model")
        with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(body.encode())) as urlopen:
            result = read_and_store_source_unit(
                source_unit_id="su_local_reader_001", observations=[observation],
                expected_observation_hashes={"obs_body": sha256_json(observation.to_dict())},
                source_revision_fingerprint=sha256_json({"revision": 1}),
                permission_scope_fingerprint=sha256_json(observation.to_dict()["permission_scope"]),
                source_complete=True, extractor_run_id="semrun_local_reader_001",
                ontology_revision_id="ontology_local_reader", model_name="local-model",
                reasoning_effort="none", reader=reader.extract_structured_json,
                configuration=reader.configuration,
                semantic_metadata_store=SemanticMetadataStore(temp_dir),
                candidate_atom_store=CandidateAtomStore(temp_dir),
                candidate_relation_store=CandidateRelationStore(temp_dir))
        sent = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(sent["format"]["properties"]["read_observation_ids"]["items"]["enum"], ["obs_body"])
        self.assertEqual(result.read_ledger.value["annotation_status"], "annotated")
        atom = result.candidate_atoms[0]
        self.assertEqual(atom.status, "pending_review")
        self.assertEqual(atom.properties["assertion"]["target"], "4500123")
        self.assertEqual(atom.properties["times"][0]["property"], "交期")
        self.assertEqual(result.read_ledger.value["pins"]["model_name"], "local-model")

    def test_truncated_generation_is_not_a_completed_read(self) -> None:
        body = json.dumps({"done_reason": "length", "message": {"content": "{"}})
        reader = LocalOllamaReader("http://127.0.0.1:1", "local-model")
        unit = {"observations": [_observation("obs_body", BODY).to_dict()],
                "focus_observation_ids": ["obs_body"], "context_observation_ids": []}
        schema = {"properties": {"atoms": {}}}
        with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(body.encode())):
            with self.assertRaisesRegex(ContractValidationError, "incomplete"):
                reader.extract_structured_json(instructions="", source_unit=unit, response_schema=schema,
                                               schema_name="x")


if __name__ == "__main__":
    unittest.main()
