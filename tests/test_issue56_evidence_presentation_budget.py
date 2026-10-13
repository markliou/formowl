from __future__ import annotations

import json
import unittest

import _paths  # noqa: F401
from formowl_mail.human_uat_orchestrator import (
    _MAX_MODEL_EVIDENCE_BYTES,
    _evidence_is_incomplete,
    _model_evidence_envelope,
    _validate_evidence_bound_decision,
    compact_evidence_for_model,
)


def _size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _decision(
    citations: tuple[str, ...],
    coverage_status: str,
    *,
    response_kind: str = "answer",
) -> dict[str, object]:
    return {
        "response_kind": response_kind,
        "citation_ids": list(citations),
        "coverage_status": coverage_status,
    }


class EvidencePresentationBudgetTests(unittest.TestCase):
    def test_graph_hash_links_survive_shuffled_evidence_and_lineages(self) -> None:
        citations = [f"sha256:{index:064x}" for index in range(10)]
        evidence = [
            {
                "observation_id": f"obs-{index}",
                "citation_hash": citation,
                "snippet": f"Source-backed deadline {index}.",
                "occurrence_lineage_fingerprint": f"lineage-{index}",
            }
            for index, citation in enumerate(citations)
        ]
        lineages = [
            {"source_observation_id": f"obs-{index}", "lineage_id": f"lineage-{index}"}
            for index in range(10)
        ]
        # The orphan has no source-backed evidence. Neither evidence nor
        # lineage ordering follows the citation array.
        result = {
            "status": "ok",
            "citations": [*citations, "sha256:orphan"],
            "evidence": evidence[3:] + evidence[:3],
            "lineages": list(reversed(lineages)),
        }
        for limit in (8, 0):
            with self.subTest(limit=limit):
                compact = compact_evidence_for_model(result, item_limit=limit)
                expected = set(citations[:limit])
                self.assertEqual(set(compact["citations"]), expected)
                self.assertEqual(
                    {item["citation_hash"] for item in compact["evidence"]}, expected,
                )
                self.assertEqual(
                    {item["source_observation_id"] for item in compact["lineages"]},
                    {f"obs-{index}" for index in range(limit)},
                )
                for item in compact["evidence"]:
                    index = int(item["observation_id"].split("-")[1])
                    self.assertEqual(item["citation_hash"], citations[index])
                    self.assertEqual(item["snippet"], evidence[index]["snippet"])
                    self.assertIn(lineages[index], compact["lineages"])
                self.assertTrue(compact["presentation_truncated"])
                self.assertLessEqual(_size(compact), _MAX_MODEL_EVIDENCE_BYTES)

    def test_graph_oversized_hash_group_skips_to_small_linked_evidence(self) -> None:
        result = {
            "status": "ok",
            "citations": ["sha256:large", "sha256:small"],
            "evidence": [
                {"observation_id": "large", "citation_hash": "sha256:large", "snippet": "界" * 6000},
                {"observation_id": "small", "citation_hash": "sha256:small", "snippet": "bounded"},
            ],
            "lineages": [
                {"source_observation_id": "small", "lineage_id": "small-lineage"},
                {"source_observation_id": "large", "lineage_id": "large-lineage"},
            ],
        }
        compact = compact_evidence_for_model(result)
        self.assertEqual(compact["citations"], ["sha256:small"])
        self.assertEqual(compact["evidence"], [result["evidence"][1]])
        self.assertEqual(compact["lineages"], [result["lineages"][0]])
        self.assertTrue(compact["presentation_truncated"])
        self.assertLessEqual(_size(compact), _MAX_MODEL_EVIDENCE_BYTES)

    def test_unknown_graph_lineage_does_not_get_a_positional_pair(self) -> None:
        result = {
            "status": "ok",
            "citations": [f"sha256:{index}" for index in range(10)],
            "evidence": [
                {"observation_id": f"obs-{index}", "citation_hash": f"sha256:{index}", "snippet": "bounded"}
                for index in range(10)
            ],
            "lineages": [{"source_observation_id": "unknown", "lineage_id": "unknown"}],
        }
        compact = compact_evidence_for_model(result, item_limit=8)
        self.assertEqual(compact["citations"], [])
        self.assertEqual(compact["evidence"], [])
        self.assertEqual(compact["lineages"], [])
        self.assertTrue(compact["presentation_truncated"])

    def test_graph_recovery_keeps_field_text_with_citation_not_trace_or_orphan_ids(self) -> None:
        snippet = "Synthetic approval deadline: 2030-01-02."
        result = {
            "status": "ok",
            "coverage": {"status": "incomplete"},
            "citations": ["sha256:oversized", "sha256:deadline", "sha256:orphan"],
            "evidence": [
                {"citation_hash": "sha256:oversized", "snippet": "界" * 6_000},
                {
                    "citation_hash": "sha256:deadline",
                    "snippet": snippet,
                    "occurrence_lineage_fingerprint": "sha256:lineage",
                    "document_locator": {"line_start": 2, "line_end": 2},
                },
            ],
            "query_agent": {
                "status": "replan_required",
                "stop_reason": "external_replan_required",
                "request_contract": {
                    "requested_field_count": 1,
                    "maximum_claim_strength": "cited_evidence",
                },
                "context_bundle": {
                    "missing_field_hashes": ["sha256:requested-deadline"],
                    "source_recovery": {
                        "status": "ok", "attempted": True,
                        "evidence": [{"snippet": "duplicate trace " * 5_000}],
                    },
                },
            },
        }
        compact = compact_evidence_for_model(result)
        self.assertEqual(compact["citations"], ["sha256:deadline"])
        self.assertEqual(compact["evidence"], [result["evidence"][1]])
        self.assertEqual(compact["evidence"][0]["snippet"], snippet)
        self.assertEqual(
            compact["query_agent"]["context_bundle"]["missing_field_hashes"],
            ["sha256:requested-deadline"],
        )
        self.assertLessEqual(_size(compact), _MAX_MODEL_EVIDENCE_BYTES)
        self.assertTrue(_evidence_is_incomplete(compact))
        with self.assertRaisesRegex(RuntimeError, "incomplete coverage"):
            _validate_evidence_bound_decision(
                _decision(("sha256:deadline",), "complete"),
                evidence_results=(compact,),
            )

    def test_mail_and_document_groups_keep_citations_and_lineage_together(self) -> None:
        large = "郵件與文件證據" * 1_800
        cases = (
            (
                "mail",
                {
                    "status": "ok",
                    "query_hash": "sha256:mail",
                    "coverage": {"status": "complete", "coverage_status": "complete"},
                    "citations": [
                        {"citation_id": "mail-large", "source_observation_id": "mail-obs-large"},
                        {"citation_id": "mail-small", "source_observation_id": "mail-obs-small"},
                    ],
                    "evidence_snippets": [
                        {
                            "source_observation_id": "mail-obs-large",
                            "snippet": large,
                            "source_type": "mail_body_segment",
                        },
                        {
                            "source_observation_id": "mail-obs-small",
                            "snippet": "bounded mail evidence",
                            "source_type": "mail_body_segment",
                        },
                    ],
                    "lineages": [
                        {"source_observation_id": "mail-obs-large", "lineage_id": "mail-lineage-large"},
                        {"source_observation_id": "mail-obs-small", "lineage_id": "mail-lineage-small"},
                    ],
                },
                "mail-small",
                "mail-obs-small",
            ),
            (
                "document_text",
                {
                    "status": "ok",
                    "query_hash": "sha256:document",
                    "coverage": {"status": "complete", "coverage_status": "complete"},
                    "citations": [
                        {"citation_id": "doc-large", "source_observation_id": "doc-obs-large"},
                        {"citation_id": "doc-small", "source_observation_id": "doc-obs-small"},
                    ],
                    "results": [
                        {
                            "source_family": "document_text",
                            "source_observation_id": "doc-obs-large",
                            "citation_id": "doc-large",
                            "lineage_id": "doc-lineage-large",
                            "line_start": 1,
                            "line_end": 3,
                            "text": large,
                        },
                        {
                            "source_family": "document_text",
                            "source_observation_id": "doc-obs-small",
                            "citation_id": "doc-small",
                            "lineage_id": "doc-lineage-small",
                            "line_start": 4,
                            "line_end": 4,
                            "text": "bounded document evidence",
                        },
                    ],
                    "lineages": [
                        {"source_observation_id": "doc-obs-large", "lineage_id": "doc-lineage-large"},
                        {"source_observation_id": "doc-obs-small", "lineage_id": "doc-lineage-small"},
                    ],
                },
                "doc-small",
                "doc-obs-small",
            ),
        )
        for source_family, result, kept_citation, kept_observation in cases:
            with self.subTest(source_family=source_family):
                compact = compact_evidence_for_model(result)
                self.assertTrue(compact["presentation_truncated"])
                self.assertEqual(
                    {item["citation_id"] for item in compact["citations"]},
                    {kept_citation},
                )
                retained_records = (
                    compact.get("evidence_snippets", ()) or compact.get("results", ())
                )
                self.assertEqual(
                    {item["source_observation_id"] for item in retained_records},
                    {kept_observation},
                )
                self.assertEqual(
                    {item["source_observation_id"] for item in compact["lineages"]},
                    {kept_observation},
                )
                self.assertEqual(
                    {item["source_observation_id"] for item in compact["citations"]},
                    {kept_observation},
                )
                self.assertLessEqual(_size(compact), _MAX_MODEL_EVIDENCE_BYTES)
                self.assertTrue(_evidence_is_incomplete(compact))

    def test_utf8_item_is_kept_whole_and_oversized_group_is_omitted(self) -> None:
        snippet = "界" * 5_000
        result = {
            "status": "ok",
            "coverage": {"status": "complete", "coverage_status": "complete"},
            "citations": [{"citation_id": "utf8-citation", "source_observation_id": "utf8-obs"}],
            "evidence_snippets": [{"source_observation_id": "utf8-obs", "snippet": snippet}],
        }
        compact = compact_evidence_for_model(result)
        self.assertEqual(compact["evidence_snippets"][0]["snippet"], snippet)
        self.assertNotIn("presentation_truncated", compact)
        self.assertLessEqual(_size(compact), _MAX_MODEL_EVIDENCE_BYTES)

        result["evidence_snippets"] = [
            {"source_observation_id": "utf8-obs", "snippet": "界" * 6_000}
        ]
        omitted = compact_evidence_for_model(result)
        self.assertTrue(omitted["presentation_truncated"])
        self.assertEqual(omitted["evidence_snippets"], [])
        self.assertEqual(omitted["citations"], [])
        self.assertLessEqual(_size(omitted), _MAX_MODEL_EVIDENCE_BYTES)

        unknown_link = compact_evidence_for_model(
            {
                "status": "ok",
                "coverage": {"status": "complete", "coverage_status": "complete"},
                "citations": [{"citation_id": "unmatched", "source_observation_id": "obs-a"}],
                "results": [{"source_observation_id": "obs-b", "text": "x" * 20_000}],
            }
        )
        self.assertTrue(unknown_link["presentation_truncated"])
        self.assertEqual(unknown_link["citations"], [])
        self.assertEqual(unknown_link["results"], [])
        self.assertEqual(
            _model_evidence_envelope(unknown_link)["evidence_disposition"],
            "incomplete_without_cited_evidence",
        )

    def test_unknown_many_to_many_mail_group_is_not_positionally_trimmed(self) -> None:
        result = {
            "status": "ok",
            "coverage": {"status": "complete", "coverage_status": "complete"},
            "citations": [
                {
                    "citation_id": f"citation-{index}",
                    "source_observation_id": "observation-shared",
                }
                for index in range(10)
            ],
            "evidence_snippets": [
                {
                    "source_observation_id": "observation-shared",
                    "snippet": f"bounded evidence {index}",
                }
                for index in range(10)
            ],
            "lineages": [
                {
                    "source_observation_id": "observation-shared",
                    "lineage_id": f"lineage-{index}",
                }
                for index in range(10)
            ],
        }

        compact = compact_evidence_for_model(result, item_limit=8)

        self.assertTrue(compact["presentation_truncated"])
        self.assertEqual(compact["citations"], [])
        self.assertEqual(compact["evidence_snippets"], [])
        self.assertEqual(compact["lineages"], [])
        self.assertTrue(_evidence_is_incomplete(compact))

    def test_original_incomplete_and_presentation_truncation_reject_complete_claims(self) -> None:
        result = {
            "status": "partial",
            "coverage": {"status": "incomplete", "coverage_status": "incomplete"},
            "citations": ["partial-citation"],
        }
        compact = compact_evidence_for_model(result)
        self.assertEqual(compact["status"], result["status"])
        self.assertEqual(compact["coverage"], result["coverage"])
        self.assertTrue(_evidence_is_incomplete(compact))
        _validate_evidence_bound_decision(
            _decision(("partial-citation",), "incomplete"),
            evidence_results=(compact,),
        )
        with self.assertRaisesRegex(RuntimeError, "hid incomplete coverage"):
            _validate_evidence_bound_decision(
                _decision(("partial-citation",), "complete"),
                evidence_results=(compact,),
            )

        oversized = compact_evidence_for_model(
            {
                "status": "ok",
                "coverage": {"status": "complete", "coverage_status": "complete"},
                "citations": [{"citation_id": "too-large", "source_observation_id": "large-obs"}],
                "evidence_snippets": [
                    {"source_observation_id": "large-obs", "snippet": "x" * 20_000}
                ],
            }
        )
        self.assertTrue(oversized["presentation_truncated"])
        self.assertEqual(
            _model_evidence_envelope(oversized)["evidence_disposition"],
            "incomplete_without_cited_evidence",
        )
        re_compacted = compact_evidence_for_model(oversized)
        self.assertTrue(re_compacted["presentation_truncated"])
        self.assertEqual(re_compacted["coverage"], oversized["coverage"])
        self.assertTrue(_evidence_is_incomplete(re_compacted))
        with self.assertRaisesRegex(RuntimeError, "hid incomplete coverage"):
            _validate_evidence_bound_decision(
                _decision((), "complete", response_kind="clarification"),
                evidence_results=(oversized,),
            )

    def test_exact_inventory_overflow_is_all_or_nothing(self) -> None:
        result = {
            "status": "ok",
            "coverage": {"status": "complete", "coverage_status": "complete"},
            "citations": [
                {"citation_id": "exact-citation", "source_observation_id": "exact-obs"}
            ],
            "evidence_snippets": [
                {"source_observation_id": "exact-obs", "snippet": "a row of evidence"}
            ],
            "exact_inventory": {
                "status": "complete_authorized_scope",
                "coverage": {"authorized_scope_complete": True},
                "items": [
                    {
                        "item_hash": "x" * 17_000,
                        "governed_references": [{"citation_hash": "exact-citation"}],
                    }
                ],
            },
        }
        compact = compact_evidence_for_model(result)
        self.assertNotIn("exact_inventory", compact)
        self.assertTrue(compact["presentation_truncated"])
        self.assertEqual(compact["citations"], [])
        self.assertEqual(compact["evidence_snippets"], [])
        self.assertEqual(compact["coverage"], result["coverage"])
        self.assertTrue(_evidence_is_incomplete(compact))
        with self.assertRaisesRegex(RuntimeError, "hid incomplete coverage"):
            _validate_evidence_bound_decision(
                _decision((), "complete", response_kind="clarification"),
                evidence_results=(compact,),
            )
        self.assertLessEqual(_size(compact), _MAX_MODEL_EVIDENCE_BYTES)


if __name__ == "__main__":
    unittest.main()
