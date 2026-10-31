from __future__ import annotations

import json
from copy import deepcopy
import time
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from formowl_contract import sha256_json
from formowl_gateway import issue56_sealed_source_loader as loader
from formowl_mail import human_uat_orchestrator as orchestrator
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
    def test_candidate_fact_conflicts_travel_atomically(self):
        hashes = [sha256_json(label) for label in ("clienta-a", "clienta-b")]
        evidence = [{"citation_hash": key, "snippet": "候選事實（由標註取得，未經人工審核） " + value,
                     "source_context": {"candidate_fact_group": "clienta", "required_citation_hashes": hashes}}
                    for key, value in zip(hashes, ("2031-04-02", "2031-04-09"))]
        payload = {"status": "partial", "evidence": evidence, "citations": hashes}
        self.assertEqual(compact_evidence_for_model(payload)["evidence"], evidence)
        self.assertEqual(compact_evidence_for_model(payload, item_limit=1)["evidence"], [])
        broken = {**payload, "evidence": evidence[:1], "citations": hashes[:1]}
        self.assertEqual(compact_evidence_for_model(broken)["evidence"], [])
        oversized = deepcopy(payload)
        oversized["evidence"][1]["snippet"] += "x" * 17000
        self.assertEqual(compact_evidence_for_model(oversized)["evidence"], [])

    def _native_envelope_fixture(self, *, oversized=False, orphan=False):
        row_id, header_id = (sha256_json(label) for label in ("synthetic-row", "synthetic-header"))
        header = {
            "citation_hash": header_id, "snippet": "Synthetic outer message.",
            "occurrence_lineage_fingerprint": sha256_json("header-lineage"),
            "source_context": {"relationship": "outer_message_header", "anchor_citation_hash": row_id},
        }
        row = {
            "citation_hash": row_id, "snippet": "x" * 17000 if oversized else "Verified synthetic row.",
            "occurrence_lineage_fingerprint": sha256_json("row-lineage"),
            "table_row": {"cells": [
                {"citation_hash": sha256_json("synthetic-code-cell"), "field": "Code", "value": "ZX-742"},
                {"citation_hash": sha256_json("synthetic-state-cell"), "field": "State", "value": "ready"},
            ]},
            "_mail_parent_header": header,
        }
        if orphan:
            row.pop("_mail_parent_header")
            row["mail_header_citation_hash"] = header_id
        large = {"citation_hash": sha256_json("oversized-source"), "snippet": "x" * 17000,
                 "occurrence_lineage_fingerprint": sha256_json("oversized-lineage")}
        # Both complete source groups have already been validated by the caller.
        records, _ = loader._bounded_mail_header_groups([large, row], limit=10, byte_limit=100000)
        payload = {"status": "partial", "coverage": {"status": "incomplete"},
                   "evidence": records, "citations": [item["citation_hash"] for item in records]}
        return payload, (large, row), row_id, header_id

    def test_native_envelope_reselection_preserves_row_cell_and_header_citations(self):
        payload, staged, row_id, header_id = self._native_envelope_fixture()
        original = deepcopy(payload)
        diagnostic = {}
        compact_evidence_for_model(payload, diagnostic=diagnostic)
        self.assertGreater(diagnostic["reason_counts"]["group_byte_budget"], 0)
        result = loader._admit_source_model_envelope(
            payload, staged_items=staged, limit=10, deadline=time.monotonic() + 2,
        )
        expected, _ = loader._bounded_mail_header_groups([staged[1]], limit=10)
        self.assertEqual(result["evidence"], expected)
        self.assertEqual(set(orchestrator.evidence_citation_ids(result)), {
            row_id, header_id, sha256_json("synthetic-code-cell"), sha256_json("synthetic-state-cell"),
        })
        self.assertEqual(payload, original)
        self.assertTrue(result["presentation_truncated"])
        self.assertLessEqual(_size(compact_evidence_for_model(result)), _MAX_MODEL_EVIDENCE_BYTES)

    def test_native_envelope_reselection_rejects_missing_or_unknown_citations(self):
        for damage in ("missing_cell", "unknown_citation"):
            with self.subTest(damage=damage):
                payload, staged, _, _ = self._native_envelope_fixture()
                def corrupt(value, **kwargs):
                    compact = deepcopy(compact_evidence_for_model(value, **kwargs))
                    if compact.get("evidence"):
                        if damage == "unknown_citation":
                            compact["citations"].append(sha256_json("unknown-source"))
                        else:
                            next(item for item in compact["evidence"] if "table_row" in item)["table_row"]["cells"][0].pop("citation_hash")
                    return compact
                with patch.object(orchestrator, "compact_evidence_for_model", side_effect=corrupt):
                    result = loader._admit_source_model_envelope(
                        payload, staged_items=staged, limit=10, deadline=time.monotonic() + 2,
                    )
                self.assertEqual(result["evidence"], [])
                self.assertEqual(result["citations"], [])

    def test_native_envelope_reselection_keeps_capacity_and_dependency_guards(self):
        for invalid in ("oversized", "orphan"):
            with self.subTest(invalid=invalid):
                payload, staged, _, _ = self._native_envelope_fixture(**{invalid: True})
                result = loader._admit_source_model_envelope(
                    payload, staged_items=staged, limit=10, deadline=time.monotonic() + 2,
                )
                self.assertEqual(result["evidence"], [])
                self.assertEqual(result["citations"], [])

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
