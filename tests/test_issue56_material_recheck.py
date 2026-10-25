"""Bounded identity-only source recheck behavior; synthetic inputs only."""

from types import SimpleNamespace
import unittest

import _paths  # noqa: F401
from formowl_contract import sha256_json
from formowl_gateway.issue56_sealed_source_loader import (
    _graph_source_recovery_is_eligible,
    _identity_only_recheck_terms,
)
from formowl_gateway.issue56_uat_runtime import _private_graph_recheck_trace
from formowl_mail.query import RevisionOwnedMailSourceScan
from formowl_retrieval.gateway import source_evidence_double_check


class MaterialSourceRecheckTests(unittest.TestCase):
    def test_identity_terms_remain_hard_and_topic_terms_change_the_fingerprint(self):
        first_terms = ("ZX-421", "Kestrel", "Quarterly update")
        hard, soft = _identity_only_recheck_terms(
            first_terms,
            protected_terms=("ZX-421",),
            reviewed_annotations=({
                "candidate_atom_id": "atom-synthetic",
                "target": "Kestrel Label Printer",
                "identity_bindings": [],
            },),
        )
        self.assertEqual(hard, ("kestrel", "zx-421"))
        self.assertEqual(soft, ("quarterly update",))
        self.assertNotEqual(sha256_json(first_terms), sha256_json(hard))

    def test_identity_term_uses_the_n2_complete_word_boundary_rule(self):
        from unittest.mock import patch

        from formowl_mail import issue56_sealed_source

        surfaces = ("Kestrel Label Printer",)
        self.assertTrue(issue56_sealed_source._reviewed_identity_surface_has_complete_term(
            "Kestrel", surfaces,
        ))
        self.assertFalse(issue56_sealed_source._reviewed_identity_surface_has_complete_term(
            "Kestrelx", surfaces,
        ))
        profile = SimpleNamespace(analyze=lambda _text: SimpleNamespace(tokens=frozenset({"Kestrel"})))
        with patch.object(issue56_sealed_source, "load_issue56_target_mail_tokenizer_profile",
                          return_value=profile):
            self.assertEqual(issue56_sealed_source._partial_reviewed_identity_terms(
                ({"annotation_id": "ann-synthetic", "target": surfaces[0], "identity_bindings": []},),
                "query",
            ), ("kestrel",))

    def test_identity_boundary_does_not_turn_a_topic_only_plan_into_a_variant(self):
        result = _identity_only_recheck_terms(
            ("Kestrelx", "quarterly"),
            protected_terms=(),
            reviewed_annotations=({
                "candidate_atom_id": "atom-synthetic",
                "target": "Kestrel Label Printer",
                "identity_bindings": [],
            },),
        )
        self.assertIsNone(result)

    def test_topic_terms_rank_but_do_not_filter_and_identity_stays_hard(self):
        candidates = (
            SimpleNamespace(text="ZX-421 ordinary update"),
            SimpleNamespace(text="ZX-421 quarterly update"),
            SimpleNamespace(text="ZX-999 quarterly update"),
        )

        def reader(**kwargs):
            for item in candidates:
                self.assertTrue(kwargs["observation_callback"](item, "scope"))
            return RevisionOwnedMailSourceScan((), len(candidates), True)

        def project(observation, scope, _deadline):
            if scope != "scope" or "ZX-421" not in observation.text:
                return None
            return sha256_json(observation.text), {"snippet": observation.text}

        result = source_evidence_double_check(
            initial_status="pending_review",
            query_class="evidence_lookup",
            result_query_class="evidence_lookup",
            initial_warnings=(),
            verified_evidence_count=0,
            evidence_limit=2,
            sealed_coverage_complete=False,
            read_source=reader,
            project_observation=project,
            requested_fields=("owner",),
            supported_requested_fields=(),
            candidate_rank=lambda observation: int("quarterly" in observation.text),
        )
        self.assertEqual(
            [item["snippet"] for item in result.evidence],
            ["ZX-421 quarterly update", "ZX-421 ordinary update"],
        )
        self.assertTrue(result.scan.complete)

    def test_zero_citations_without_requested_fields_do_not_authorize_recheck(self):
        result = SimpleNamespace(
            status="pending_review", query_class="evidence_lookup",
            query_hash="query-hash", plan_fingerprint="plan-hash",
            exact_result=None, answer_citation_hashes=(), result_fingerprint="result-hash",
        )
        contract_fingerprint = "contract-fingerprint"
        query_agent = {
            "status": "pending_review",
            "subqueries": [{
                "status": "pending_review",
                "validation_status": "validated_existing_scope_schema_permission",
                "query_hash": result.query_hash,
                "plan_fingerprint": result.plan_fingerprint,
                "request_contract_fingerprint": contract_fingerprint,
                "result_fingerprint": result.result_fingerprint,
            }],
        }
        bindings = {
            "arguments": {},
            "request_query_class": "evidence_lookup",
            "result": result,
            "request_contract_summary": {
                "query_class": "evidence_lookup",
                "request_contract_fingerprint": contract_fingerprint,
            },
            "query_agent_payload": query_agent,
            "supported_requested_fields": (),
        }
        self.assertFalse(_graph_source_recovery_is_eligible(
            **bindings, requested_fields=(),
        ))
        self.assertTrue(_graph_source_recovery_is_eligible(
            **bindings, requested_fields=("owner",),
        ))

    def test_private_trace_exposes_variant_and_term_counts_without_terms(self):
        trace = {
            "response_stage": "payload_validated",
            "browser_request_sha256": sha256_json("turn"),
            "query_hash": sha256_json("query"),
            "mcp_call_index": 1,
            "citation_count": 0,
            "request_discriminator": {
                "tool_name": "query_effective_graph_view",
                "selector_kind": "none",
                "selector_present": False,
                "selector_count": 0,
                "query_text_char_count": 5,
                "required_term_count": 2,
                "required_terms_fingerprint": "sha256:" + "a" * 64,
            },
        }
        response = {"status": "pending_review", "query_agent": {"context_bundle": {
            "source_recovery": {
                "attempted": True,
                "recheck_variant": "identity_only",
                "hard_term_count": 2,
                "soft_term_count": 1,
                "initial_required_terms_fingerprint": sha256_json(["id", "topic"]),
                "recheck_required_terms_fingerprint": sha256_json(["id"]),
                "warnings": ["identity_only_recheck", "topic_terms_ranked_only"],
                "raw_terms": ["private term"],
            },
        }}}
        safe = _private_graph_recheck_trace(trace, response)
        self.assertEqual(safe["recheck_variant"], "identity_only")
        self.assertEqual((safe["hard_term_count"], safe["soft_term_count"]), (2, 1))
        self.assertNotEqual(
            safe["initial_required_terms_fingerprint"],
            safe["recheck_required_terms_fingerprint"],
        )
        self.assertNotIn("private term", str(safe))


if __name__ == "__main__":
    unittest.main()
