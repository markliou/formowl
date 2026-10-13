import unittest
from types import SimpleNamespace

from formowl_contract import sha256_json
from formowl_graph import EffectiveGraphView
import formowl_mail.exact as exact
import formowl_mail.hybrid as hybrid
from formowl_mail.semantic_plan import route_semantic_query


class RequestedProjectionIntegrityTest(unittest.TestCase):
    @staticmethod
    def _adaptive_session(
        fields_by_query,
        *,
        structure_status="source_provided",
    ):
        def result(query_text):
            citation = sha256_json([query_text, "citation"])
            lineage = sha256_json([query_text, "lineage"])
            fields = fields_by_query[query_text]
            item = SimpleNamespace(
                structured_values=tuple(
                    (field, "", citation, lineage) for field in fields
                ),
                cited_observation_hashes=(citation,),
                structure_status=structure_status,
            )
            return SimpleNamespace(
                query_hash=sha256_json(query_text),
                exact_result=SimpleNamespace(
                    source_occurrence_page={
                        "coverage_status": "complete",
                        "unsupported_projection_hashes": [],
                    },
                    items=(item,),
                ),
                answer_citation_hashes=(citation,),
                status="complete_authorized_scope",
                result_fingerprint=sha256_json([query_text, fields]),
                warnings=(),
            )

        return SimpleNamespace(
            index=SimpleNamespace(
                _runtime_components=SimpleNamespace(tokenizer_profile=None),
                _runtime_store=None,
                _runtime_store_seal=None,
            ),
            source_occurrence_providers=(),
            authorized_observations=(SimpleNamespace(modality="mail"),),
            source_session_binding_fingerprint=sha256_json("adaptive-session"),
            query=lambda *, query_text, **_kwargs: result(query_text),
        )

    def test_missing_original_requested_field_blocks_adaptive_completion(self):
        query_text = "generic requested field lookup"
        requested_fields = ("Field A", "Field B")
        _result, _results, payload = hybrid.execute_bounded_adaptive_query(
            session=self._adaptive_session({query_text: (requested_fields[0],)}),
            query_text=query_text,
            request_contract={
                "original_query_hash": sha256_json(query_text),
                "query_class": "evidence_lookup",
                "source_family_scope": ["mail"],
                "requested_fields": list(requested_fields),
                "maximum_claim_strength": "cited_evidence",
            },
            effective_graph_view=EffectiveGraphView(
                requester_user_id="user_projection_integrity",
                user_graph_revision_id="user_graph_projection_integrity",
                canonical_graph_revision_id="canonical_graph_projection_integrity",
                ontology_revision_id="ontology_projection_integrity",
                assembly_policy_id="assembly_projection_integrity",
            ),
            planner=lambda original, steps, _profile, _limit: (
                original if not steps else None
            ),
        )

        missing_hash = sha256_json(requested_fields[1])
        self.assertEqual(payload["status"], "partial")
        self.assertEqual(
            payload["subqueries"][0]["missing_field_hashes"],
            [missing_hash],
        )
        self.assertEqual(
            payload["context_bundle"]["missing_field_hashes"],
            [missing_hash],
        )

        _result, _results, candidate_payload = (
            hybrid.execute_bounded_adaptive_query(
                session=self._adaptive_session(
                    {query_text: (requested_fields[0],)},
                    structure_status="candidate_only",
                ),
                query_text=query_text,
                request_contract={
                    "original_query_hash": sha256_json(query_text),
                    "query_class": "evidence_lookup",
                    "source_family_scope": ["mail"],
                    "requested_fields": [requested_fields[0]],
                    "maximum_claim_strength": "cited_evidence",
                },
                effective_graph_view=EffectiveGraphView(
                    requester_user_id="user_projection_integrity",
                    user_graph_revision_id="user_graph_projection_integrity",
                    canonical_graph_revision_id="canonical_graph_projection_integrity",
                    ontology_revision_id="ontology_projection_integrity",
                    assembly_policy_id="assembly_projection_integrity",
                ),
                planner=lambda original, steps, _profile, _limit: (
                    original if not steps else None
                ),
            )
        )
        self.assertEqual(
            candidate_payload["context_bundle"]["missing_field_hashes"],
            [sha256_json(requested_fields[0])],
        )

    def test_partial_subqueries_cover_original_requested_field_union(self):
        first_query = "generic requested field lookup"
        second_query = "generic requested field followup"
        requested_fields = ("Field A", "Field B")
        planned_queries = (first_query, second_query)

        def planner(_original, steps, _profile, _limit):
            return planned_queries[len(steps)] if len(steps) < 2 else None

        _result, results, payload = hybrid.execute_bounded_adaptive_query(
            session=self._adaptive_session(
                {
                    first_query: (requested_fields[0],),
                    second_query: (requested_fields[1],),
                }
            ),
            query_text=first_query,
            request_contract={
                "original_query_hash": sha256_json(first_query),
                "query_class": "evidence_lookup",
                "source_family_scope": ["mail"],
                "requested_fields": list(requested_fields),
                "maximum_claim_strength": "cited_evidence",
            },
            effective_graph_view=EffectiveGraphView(
                requester_user_id="user_projection_integrity",
                user_graph_revision_id="user_graph_projection_integrity",
                canonical_graph_revision_id="canonical_graph_projection_integrity",
                ontology_revision_id="ontology_projection_integrity",
                assembly_policy_id="assembly_projection_integrity",
            ),
            planner=planner,
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(payload["status"], "complete")
        self.assertEqual(payload["stop_reason"], "coverage_complete")
        self.assertEqual(
            payload["context_bundle"]["missing_field_hashes"],
            [],
        )

    def test_missing_requested_projection_keeps_exact_coverage_incomplete(self):
        identifier = "ITEM-GAMMA-42"
        requested = "ProjectionField"
        fields = ("IdentifierField", requested, "AuxiliaryField", "BlankField")
        columns = {field: exact.source_occurrence_column_capability_hash(field) for field in fields}
        candidates = {field: sha256_json(field) for field in fields}

        def row(name, values):
            citation = sha256_json([name, "citation"])
            lineage = sha256_json([name, "lineage"])
            return exact.AuthorizedSourceOccurrence(
                item_hash=sha256_json(name),
                value_bindings=tuple(
                    (sha256_json(value), sha256_json(value), citation, lineage)
                    for _field, value in values
                ),
                projection_bindings=tuple(
                    (field, value, citation, lineage) for field, value in values
                ),
                structure_status="source_provided",
                structured_column_bindings=tuple(
                    (
                        columns[field],
                        candidates[field],
                        sha256_json(value),
                        field,
                        value,
                        citation,
                        lineage,
                    )
                    for field, value in values
                ),
            )

        provider = exact.SourceOccurrenceProvider(
            provider_id="projection_integrity_provider_v1",
            inventory_kind_alias="synthetic_rows",
            resource_kind="synthetic_row_occurrence",
            normalized_field="synthetic.row.value",
            predicate="synthetic_row_contains",
            operator="case_insensitive_exact",
            requester_user_id="user_projection_integrity",
            workspace_id="workspace_projection_integrity",
            source_scope_ids=("source_projection_integrity",),
            authorized_scope_fingerprint=sha256_json("authorized_scope"),
            filter_slot_policy="combined_present_intersection_v1",
            occurrences=(
                row(
                    "row-a",
                    (
                        (fields[0], identifier),
                        (requested, "TargetValue"),
                        (fields[2], "OtherValue"),
                        (fields[3], ""),
                    ),
                ),
                row("row-b", ((fields[0], identifier), (fields[2], "PeerValue"), (fields[3], ""))),
            ),
        )
        identifier_hash = sha256_json(identifier)
        plan = route_semantic_query(
            query_text=f"list {identifier} {requested}",
            requester_user_id=provider.requester_user_id,
            workspace_id=provider.workspace_id,
            source_scope_ids=provider.source_scope_ids,
            effective_graph_view=EffectiveGraphView(
                requester_user_id=provider.requester_user_id,
                user_graph_revision_id="user_graph_projection_integrity",
                canonical_graph_revision_id="canonical_graph_projection_integrity",
                ontology_revision_id="ontology_projection_integrity",
                assembly_policy_id="assembly_projection_integrity",
            ),
            exact_inventory_kind=provider.resource_kind,
            exact_filter_term_hashes=(identifier_hash,),
            exact_projection_term_hashes=(columns[requested],),
            exact_column_value_hash_pairs=((columns[fields[0]], identifier_hash),),
            exact_lexical_term_ledger=(
                (
                    sha256_json("identifier-term"),
                    "filter_value",
                    columns[fields[0]],
                    identifier_hash,
                ),
                (
                    sha256_json("projection-term"),
                    "projection_field",
                    columns[requested],
                    candidates[requested],
                ),
            ),
            exact_grammar_policy_fingerprint=sha256_json("grammar-policy"),
            exact_source_occurrence_provider_fingerprint=provider.provider_fingerprint,
            exact_topic_term_hashes=(identifier_hash,),
            exact_normalized_field=provider.normalized_field,
            exact_predicate=provider.predicate,
            exact_operator=provider.operator,
            query_class_override="exact_set_or_inventory",
        )
        result = exact.execute_deterministic_source_occurrence_inventory(
            plan=plan,
            provider=provider,
            expected_authorized_scope_fingerprint=provider.authorized_scope_fingerprint,
            page_size=20,
            cursor=None,
        )
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.source_occurrence_page["coverage_status"], "incomplete")
        self.assertFalse(result.coverage.authorized_scope_complete)
        self.assertEqual(result.returned_item_count, 1)
        item = result.items[0]
        self.assertEqual(item.structure_status, "source_provided")
        self.assertEqual({field for field, *_ in item.structured_values}, {requested})
        for _field, _value, citation, lineage in item.structured_values:
            self.assertIn(citation, item.cited_observation_hashes)
            self.assertIn((citation, lineage), item.governed_references)
        self.assertEqual(result.source_occurrence_page["candidate_only_occurrence_count"], 0)

    def test_multiple_requested_projections_return_source_backed_partial_rows(self):
        filter_field = "Supplier"
        projection_fields = ("Lead Time", "Part Number")
        all_fields = (filter_field, *projection_fields, "Notes")
        columns = {
            field: exact.source_occurrence_column_capability_hash(field) for field in all_fields
        }
        candidates = {field: sha256_json(field) for field in all_fields}

        def row(name, values):
            citation = sha256_json([name, "citation"])
            lineage = sha256_json([name, "lineage"])
            return exact.AuthorizedSourceOccurrence(
                item_hash=sha256_json(name),
                value_bindings=tuple(
                    (sha256_json(value), sha256_json(value), citation, lineage)
                    for _field, value in values
                ),
                projection_bindings=tuple(
                    (field, value, citation, lineage) for field, value in values
                ),
                structure_status="source_provided",
                structured_column_bindings=tuple(
                    (
                        columns[field],
                        candidates[field],
                        sha256_json(value),
                        field,
                        value,
                        citation,
                        lineage,
                    )
                    for field, value in values
                ),
            )

        filter_value = "Supplier A"
        provider = exact.SourceOccurrenceProvider(
            provider_id="multi_projection_integrity_provider_v1",
            inventory_kind_alias="synthetic_rows",
            resource_kind="synthetic_row_occurrence",
            normalized_field="synthetic.row.value",
            predicate="synthetic_row_contains",
            operator="case_insensitive_exact",
            requester_user_id="user_projection_integrity",
            workspace_id="workspace_projection_integrity",
            source_scope_ids=("source_projection_integrity",),
            authorized_scope_fingerprint=sha256_json("authorized_scope"),
            filter_slot_policy="combined_present_intersection_v1",
            occurrences=(
                row(
                    "lead-time-row",
                    ((filter_field, filter_value), (projection_fields[0], "12 weeks")),
                ),
                row(
                    "part-number-row",
                    ((filter_field, filter_value), (projection_fields[1], "PN-42")),
                ),
                row(
                    "no-requested-field-row",
                    ((filter_field, filter_value), ("Notes", "source note")),
                ),
                row(
                    "other-supplier-row",
                    (
                        (filter_field, "Supplier B"),
                        (projection_fields[0], "8 weeks"),
                        (projection_fields[1], "PN-99"),
                    ),
                ),
            ),
        )
        filter_value_hash = sha256_json(filter_value)
        requested_columns = tuple(columns[field] for field in projection_fields)
        plan = route_semantic_query(
            query_text="generic multi-column source query",
            requester_user_id=provider.requester_user_id,
            workspace_id=provider.workspace_id,
            source_scope_ids=provider.source_scope_ids,
            effective_graph_view=EffectiveGraphView(
                requester_user_id=provider.requester_user_id,
                user_graph_revision_id="user_graph_projection_integrity",
                canonical_graph_revision_id="canonical_graph_projection_integrity",
                ontology_revision_id="ontology_projection_integrity",
                assembly_policy_id="assembly_projection_integrity",
            ),
            exact_inventory_kind=provider.resource_kind,
            exact_filter_term_hashes=(filter_value_hash,),
            exact_projection_term_hashes=tuple(sorted(requested_columns)),
            exact_column_value_hash_pairs=((columns[filter_field], filter_value_hash),),
            exact_lexical_term_ledger=(
                (
                    sha256_json("filter-term"),
                    "filter_value",
                    columns[filter_field],
                    filter_value_hash,
                ),
                *(
                    (
                        sha256_json(["projection-term", field]),
                        "projection_field",
                        columns[field],
                        candidates[field],
                    )
                    for field in projection_fields
                ),
            ),
            exact_grammar_policy_fingerprint=sha256_json("grammar-policy"),
            exact_source_occurrence_provider_fingerprint=provider.provider_fingerprint,
            exact_topic_term_hashes=(filter_value_hash,),
            exact_normalized_field=provider.normalized_field,
            exact_predicate=provider.predicate,
            exact_operator=provider.operator,
            query_class_override="exact_set_or_inventory",
        )

        result = exact.execute_deterministic_source_occurrence_inventory(
            plan=plan,
            provider=provider,
            expected_authorized_scope_fingerprint=provider.authorized_scope_fingerprint,
            page_size=20,
            cursor=None,
        )

        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.source_occurrence_page["coverage_status"], "incomplete")
        self.assertFalse(result.coverage.authorized_scope_complete)
        self.assertEqual(result.returned_item_count, 2)
        projected_fields = [
            {field for field, *_rest in item.structured_values} for item in result.items
        ]
        self.assertEqual(
            {field for fields in projected_fields for field in fields},
            set(projection_fields),
        )
        self.assertTrue(all(len(fields) == 1 for fields in projected_fields))
