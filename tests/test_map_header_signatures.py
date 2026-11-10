from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import _paths  # noqa: F401
from formowl_contract import sha256_json
from formowl_graph.ontology import CandidatePropertyMapping
from scripts import map_header_signatures as mapper


def aliases():
    return CandidatePropertyMapping.from_dict({
        "artifact_id": "formowl_candidate_property_mapping_v1", "mapping_id": "fictional",
        "review_status": "pending_review", "properties": list(mapper.PROPERTIES),
        "aliases": [{"label": label, "property_id": prop, "qualifiers": qualifiers}
                    for label, prop, qualifiers in (("PO No.", "po_number", {}), ("COO", "origin_country", {}),
                        ("ETD", "delivery_date", {"kind": "etd"}),
                        ("promised_delivery_date", "delivery_date", {"kind": "promised"}))],
    })


def signature(names, count=8):
    return {"header_signature_hash": sha256_json(names), "column_names": names,
            "row_count": count, "sample_cells": [[f"fictional-{row}-{column}" for column in range(len(names))] for row in range(5)]}


def good_call(system, user, schema):
    columns = json.loads(user)["columns"]
    return {"columns": [{"column_index": item["column_index"], "property_id": "quantity", "date_role": None,
                          "reason": "Fictional count field."} for item in columns]}, {
        "attempted": True, "requested_model": "fictional", "observed_model": "fictional",
        "digest": "fictional-digest", "prompt_tokens": 20, "eval_tokens": 30, "wall_seconds": 0.5,
    }


class HeaderMappingTests(unittest.TestCase):
    def test_collection_deduplicates_normalized_names_per_row_and_bounds_context(self):
        fields = mapper.collect_fields([signature(["Custom Qty", "CUSTOM-QTY", None, "Other Label"]),
                                        signature(["Custom Qty", "Third"], count=2)])
        self.assertEqual(fields["customqty"]["row_count"], 10)
        self.assertEqual(fields["customqty"]["named_cell_count"], 18)
        self.assertEqual(len(fields["customqty"]["sample_values"]), 3)
        self.assertEqual(fields["customqty"]["neighbor_names"][0]["normalized_name"], "otherlabel")
        self.assertEqual(fields["customqty"]["neighbor_names"][0]["cooccurring_row_count"], 8)

    def test_aliases_and_unnamed_columns_never_call_model(self):
        client = mock.Mock(side_effect=AssertionError("model must not run"))
        items = [signature(["ＰＯ　Ｎｏ．", None, "COO", "ETD", "promised_delivery_date"]), signature([None, None])]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            summary = mapper.run(items, aliases(), client, output, {"pin": "a"})
            results = json.loads((output / "signature_mapping.json").read_bytes())
            self.assertEqual(results[items[0]["header_signature_hash"]], [
                {"property_id": "po_number", "date_role": None}, None,
                {"property_id": "origin_country", "date_role": None},
                {"property_id": "delivery_date", "date_role": "estimated_ship"},
                {"property_id": "delivery_date", "date_role": "committed"}])
            self.assertEqual(results[items[1]["header_signature_hash"]], [None, None])
            self.assertEqual(summary["alias_resolved_names"], 4)
            self.assertEqual(summary["model_call_count"], 0)
            client.assert_not_called()

    def test_shared_names_have_one_result_across_signatures_and_resume(self):
        client = mock.Mock(side_effect=good_call)
        items = [signature(["Custom Qty", None, "PO No."]), signature(["CUSTOM-QTY", "COO"])]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            first = mapper.run(items, aliases(), client, output, {"pin": "a"})
            mapping = json.loads((output / "signature_mapping.json").read_bytes())
            self.assertEqual(mapping[items[0]["header_signature_hash"]][0], mapping[items[1]["header_signature_hash"]][0])
            self.assertEqual(first["distinct_column_names"], 3)
            self.assertEqual(first["model_call_count"], 1)
            second = mapper.run(items, aliases(), client, output, {"pin": "a"})
            self.assertEqual(second["new_model_calls"], 0)
            client.assert_called_once()
            with self.assertRaises(ValueError):
                mapper.run(items, aliases(), client, output, {"pin": "b"})

    def test_batches_have_at_most_twenty_fields_and_use_row_frequency_order(self):
        client = mock.Mock(side_effect=good_call)
        items = [signature([f"Fictional field {index}"], count=index+1) for index in range(85)]
        with tempfile.TemporaryDirectory() as temporary:
            result = mapper.run(items, aliases(), client, Path(temporary), {"pin": "a"})
        sizes = [len(json.loads(call.args[1])["columns"]) for call in client.call_args_list]
        self.assertEqual(sizes, [20, 20, 20, 20, 5])
        self.assertEqual(result["new_model_calls"], 5)
        first = json.loads(client.call_args_list[0].args[1])["columns"][0]
        self.assertEqual(first["row_count"], 85)
        self.assertLessEqual(len(first["sample_values"]), 3)
        self.assertLessEqual(len(first["neighbor_names"]), 5)

    def test_invalid_schema_retries_once_then_nulls_only_that_batch(self):
        client = mock.Mock(return_value=({}, {"attempted": True, "wall_seconds": 0.1}))
        items = [signature(["PO No.", "Custom Qty"])]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            result = mapper.run(items, aliases(), client, output, {"pin": "a"})
            values = json.loads((output / "signature_mapping.json").read_bytes())[items[0]["header_signature_hash"]]
            self.assertEqual(values, [{"property_id": "po_number", "date_role": None}, None])
            self.assertEqual(client.call_count, 2)
            self.assertEqual(result["field_statuses"], {"complete": 1, "failed": 1})
            mapper.run(items, aliases(), client, output, {"pin": "a"})
            self.assertEqual(client.call_count, 2)

    def test_schema_retry_can_succeed_without_a_third_call(self):
        calls = []
        def retry(system, user, schema):
            calls.append(user)
            return ({}, {"attempted": True}) if len(calls) == 1 else good_call(system, user, schema)
        with tempfile.TemporaryDirectory() as temporary:
            result = mapper.run([signature(["Custom Qty"])], aliases(), retry, Path(temporary), {"pin": "a"})
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["field_statuses"], {"complete": 1})

    def test_interrupted_batch_is_consumed_without_duplicate_calls(self):
        client = mock.Mock(side_effect=KeyboardInterrupt)
        items = [signature(["Custom Qty", "Fictional other"])]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with self.assertRaises(KeyboardInterrupt):
                mapper.run(items, aliases(), client, output, {"pin": "a"})
            result = mapper.run(items, aliases(), client, output, {"pin": "a"})
            self.assertEqual(result["field_statuses"], {"interrupted": 2})
            client.assert_called_once()

    def test_two_failed_batches_stop_before_a_third_batch(self):
        client = mock.Mock(return_value=({}, {"attempted": True}))
        items = [signature([f"Fictional field {index}"]) for index in range(81)]
        with tempfile.TemporaryDirectory() as temporary:
            result = mapper.run(items, aliases(), client, Path(temporary), {"pin": "a"})
        self.assertEqual(result["status"], "stopped_after_repeated_failure")
        self.assertEqual(result["processed_column_names"], 40)
        self.assertEqual(client.call_count, 4)

    def test_schema_rejects_unknown_properties_duplicate_positions_and_wrong_roles(self):
        valid = {"column_index": 0, "property_id": "delivery_date", "date_role": "requested", "reason": "Fictional date."}
        mapper.validate_response({"columns": [valid]}, ["Fictional date"])
        for item in [dict(valid, property_id="new_property"), dict(valid, date_role=None), dict(valid, property_id="quantity"), dict(valid, extra=True)]:
            with self.subTest(item=item), self.assertRaises(ValueError):
                mapper.validate_response({"columns": [item]}, ["Fictional date"])
        with self.assertRaises(ValueError):
            mapper.validate_response({"columns": [valid, valid]}, ["Fictional date", "Other"])

    def test_coverage_uses_shortest_cell_count_prefix_with_stable_ties(self):
        profiles = mapper.collect_fields([signature(["Frequent"], count=90),
                                          signature(["Middle"], count=5),
                                          signature(["Tail"], count=5)])
        selected, stats = mapper.coverage_selection(profiles, 0.95)
        self.assertEqual(selected, {"frequent", "middle"})
        self.assertEqual(stats["named_cell_count"], 100)
        self.assertEqual(stats["coverage_selected_cells"], 95)
        self.assertEqual(mapper.coverage_selection({}, 0.95)[0], set())
        for invalid in (0, -0.1, 1.1):
            with self.assertRaises(ValueError):
                mapper.coverage_selection(profiles, invalid)

    def test_coverage_tail_is_null_and_aliases_remain_available(self):
        items = [signature(["Frequent"], count=95), signature(["Tail"], count=4), signature(["COO"], count=1)]
        client = mock.Mock(side_effect=good_call)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            result = mapper.run(items, aliases(), client, output, {"pin": "a"}, coverage=0.95)
            values = json.loads((output / "signature_mapping.json").read_bytes())
            self.assertEqual(values[items[1]["header_signature_hash"]], [None])
            self.assertEqual(values[items[2]["header_signature_hash"]][0]["property_id"], "origin_country")
            self.assertEqual(result["unmapped_column_names"], 1)
            self.assertEqual(result["unmapped_named_cells"], 4)
            self.assertEqual(result["outside_coverage_cells"], 5)
            self.assertEqual(result["new_model_calls"], 1)
            rows = [json.loads(line) for line in (output / "column_coverage.jsonl").read_text().splitlines()]
            self.assertEqual(sum(row["named_cell_count"] for row in rows), 100)

    def test_call_budget_counts_existing_and_archived_interrupted_calls(self):
        items = [signature([f"Fictional field {index}"]) for index in range(85)]
        client = mock.Mock(side_effect=good_call)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            archive = output / ".interrupted-batches"
            archive.mkdir()
            (archive / "old.json").write_text(json.dumps({"batch_id": "old", "calls": [{"attempted": True}]}))
            first = mapper.run(items, aliases(), client, output, {"pin": "a"}, max_calls=2)
            self.assertEqual(first["status"], "call_limit_reached")
            self.assertEqual(first["total_batches"], 2)
            self.assertEqual(first["processed_column_names"], 20)
            self.assertEqual(first["unmapped_column_names"], 65)
            self.assertEqual(first["calls_missing_duration"], 1)
            second = mapper.run(items, aliases(), client, output, {"pin": "a"}, max_calls=2)
            self.assertEqual(second["new_model_calls"], 0)
            self.assertEqual(second["model_call_count"], 2)
            client.assert_called_once()

    def test_scope_extension_reuses_completed_fields_and_updates_coverage_counts(self):
        client = mock.Mock(side_effect=good_call)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            mapper.run([signature(["Frequent"], count=2)], aliases(), client, output, {"pin": "a"})
            records = {path.name: path.read_bytes() for path in (output / ".field-checkpoints").glob("*.json")}
            result = mapper.run([signature(["Frequent"], count=96), signature(["Tail"], count=4)],
                                aliases(), client, output, {"pin": "a"}, coverage=0.95)
            self.assertEqual(result["named_cell_count"], 100)
            self.assertEqual(result["coverage_selected_cells"], 96)
            self.assertEqual(result["new_model_calls"], 0)
            self.assertEqual(records, {path.name: path.read_bytes() for path in (output / ".field-checkpoints").glob("*.json")})
            client.assert_called_once()

    def test_superseded_results_are_preserved_in_provenance_and_reprocessed(self):
        client = mock.Mock(side_effect=good_call)
        items = [signature(["Fictional field"])]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            mapper.run(items, aliases(), client, output, {"pin": "a"})
            archive = output / ".superseded-batches"
            archive.mkdir()
            for path in (output / ".batches").glob("*.json"):
                path.rename(archive / path.name)
            archived_fields = output / ".superseded-fields"
            archived_fields.mkdir()
            for path in (output / ".field-checkpoints").glob("*.json"):
                path.rename(archived_fields / path.name)
            capped = mapper.run(items, aliases(), client, output, {"pin": "a"}, max_calls=1)
            self.assertEqual(capped["new_model_calls"], 0)
            self.assertEqual(json.loads((output / "signature_mapping.json").read_bytes())[items[0]["header_signature_hash"]], [None])
            result = mapper.run(items, aliases(), client, output, {"pin": "a"}, max_calls=2)
            self.assertEqual(result["new_model_calls"], 1)
            self.assertEqual(result["superseded_column_names"], 1)
            self.assertEqual(result["total_batches"], 2)
            provenance = json.loads((output / "mapping_provenance.jsonl").read_text())
            self.assertEqual(provenance["columns"][0]["superseded"][0]["status"], "superseded")
            self.assertEqual(len(provenance["superseded_calls"]), 1)
            another = json.loads(next(archive.glob("*.json")).read_bytes())
            another["prompt_sha256"] = "fictional-earlier-generation"
            (archive / "earlier-generation.json").write_text(json.dumps(another))
            mapper.run(items, aliases(), client, output, {"pin": "a"}, max_calls=3)
            provenance = json.loads((output / "mapping_provenance.jsonl").read_text())
            self.assertEqual(len(provenance["columns"][0]["superseded"]), 2)
            self.assertEqual(len(provenance["superseded_calls"]), 2)
            self.assertEqual(client.call_count, 2)

    def test_active_batches_from_different_prompt_are_rejected(self):
        client = mock.Mock(side_effect=good_call)
        items = [signature(["Fictional field"])]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            mapper.run(items, aliases(), client, output, {"pin": "a"})
            path = next((output / ".batches").glob("*.json"))
            data = json.loads(path.read_bytes())
            data["prompt_profile_sha256"] = "old-profile"
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                mapper.run(items, aliases(), client, output, {"pin": "a"})
            client.assert_called_once()

    def test_schema_orders_reason_first_in_properties_and_required(self):
        variants = mapper.response_schema(["Fictional field"])["properties"]["columns"]["items"]["anyOf"]
        for variant in variants:
            self.assertEqual(list(variant["properties"]), ["reason", "column_index", "property_id", "date_role"])
            self.assertEqual(variant["required"], ["reason", "column_index", "property_id", "date_role"])

    def test_order_remap_uses_only_selected_properties_and_reason_first(self):
        properties = {key: mapper.PROPERTIES[key] for key in ("po_number", "sales_order_number")}
        fields = list(mapper.collect_fields([signature(["Fictional order code"])]).values())
        data = {"columns": [{"reason": "Fictional sales order identifier.", "column_index": 0,
                             "property_id": "sales_order_number", "date_role": None}]}
        client = mock.Mock(return_value=(data, {"attempted": True}))
        batch = mapper.call_batch(fields, client, mock.Mock(), {}, properties=properties,
                                  instructions="Fictional scoped instructions.")
        self.assertEqual(batch["status"], "complete")
        self.assertEqual(batch["mappings"], [{"property_id": "sales_order_number", "date_role": None}])
        system, user, schema = client.call_args.args
        self.assertEqual(system, "Fictional scoped instructions.")
        self.assertEqual(json.loads(user)["properties"], properties)
        variants = schema["properties"]["columns"]["items"]["anyOf"]
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0]["properties"]["property_id"]["enum"],
                         ["po_number", "sales_order_number", None])
        self.assertEqual(variants[0]["required"], ["reason", "column_index", "property_id", "date_role"])
        self.assertEqual(batch["prompt_profile_sha256"], mapper.sha256_json({
            "instructions": system, "properties": properties}))
        for property_id in ("quantity", "manufacturer", "delivery_date"):
            data["columns"][0]["property_id"] = property_id
            with self.subTest(property_id=property_id), self.assertRaises(ValueError):
                mapper.validate_response(data, ["Fictional order code"], properties)
        for property_id in ("po_number", "sales_order_number", None):
            data["columns"][0]["property_id"] = property_id
            mapper.validate_response(data, ["Fictional order code"], properties)

    def test_sales_order_is_an_identifier_and_has_no_purchase_order_entity_binding(self):
        from formowl_records.store import ENTITY_TYPES, PROPERTY_TYPES

        self.assertEqual(PROPERTY_TYPES["sales_order_number"], "identifier")
        self.assertNotIn("sales_order_number", ENTITY_TYPES)

    def test_call_budget_includes_schema_retry_without_overrun(self):
        client = mock.Mock(return_value=({}, {"attempted": True}))
        with tempfile.TemporaryDirectory() as temporary:
            result = mapper.run([signature(["Fictional field"])], aliases(), client,
                                Path(temporary), {"pin": "a"}, max_calls=1)
        self.assertEqual(result["status"], "call_limit_reached")
        self.assertEqual(result["model_call_count"], 1)
        client.assert_called_once()

    def test_three_batch_pilot_contains_all_prior_review_names(self):
        items = [signature([f"Fictional field {index}"], count=index+1) for index in range(85)]
        priorities = {mapper.fold_property_label(f"Fictional field {index}") for index in range(30)}
        client = mock.Mock(side_effect=good_call)
        with tempfile.TemporaryDirectory() as temporary:
            result = mapper.run(items, aliases(), client, Path(temporary), {"pin": "a"},
                                max_new_batches=3, priority_names=priorities)
        actual = {field["normalized_name"] for call in client.call_args_list
                  for field in json.loads(call.args[1])["columns"]}
        self.assertTrue(priorities <= actual)
        self.assertEqual(result["status"], "pilot_batch_limit_reached")
        self.assertEqual(client.call_count, 3)
        self.assertEqual(result["processed_column_names"], 60)

    def test_operator_boundary_stop_preserves_resumability(self):
        client = mock.Mock(side_effect=good_call)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            flag = output / ".stop-after-batch"
            flag.touch()
            result = mapper.run([signature(["Frequent"])], aliases(), client, output, {"pin": "a"})
            self.assertEqual(result["status"], "stopped_at_batch_boundary")
            client.assert_not_called()
            flag.unlink()
            mapper.run([signature(["Frequent"])], aliases(), client, output, {"pin": "a"})
            client.assert_called_once()

    def test_digest_mismatch_stops_before_inference_and_has_fresh_receipt(self):
        client = mapper.OllamaClient("fictional", "expected")
        client.reader.last = {"prompt_tokens": 999, "output_tokens": 888}
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({"models": [{"name": "fictional", "digest": "different"}]}).encode()
        with mock.patch.object(mapper.urllib.request, "urlopen", return_value=response), mock.patch.object(client.reader, "complete_json") as inference:
            with self.assertRaises(mapper.CallFailure) as caught:
                client("system", "user", {})
            self.assertEqual(caught.exception.reason, "model_digest_mismatch")
            self.assertFalse(caught.exception.receipt["attempted"])
            self.assertIsNone(caught.exception.receipt["prompt_tokens"])
            inference.assert_not_called()


if __name__ == "__main__":
    unittest.main()
