from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_contract import (
    CandidateBusinessObject,
    CandidateFrame,
    CandidateMention,
    CanonicalFrame,
    ContractValidationError,
    DomainPackDefinition,
    SourceRef,
    stable_candidate_business_object_id,
    stable_candidate_frame_id,
    stable_candidate_mention_id,
    stable_canonical_frame_id,
    stable_domain_pack_id,
)


CREATED_AT = "2026-07-08T00:00:00+00:00"
ONTOLOGY_REVISION_ID = "ontology_rev_coordination_v2_fixture_001"
EXTRACTOR_RUN_ID = "run_ontology_v2_coordination_fixture"


class OntologyV2ContractTests(unittest.TestCase):
    def test_candidate_frame_contracts_round_trip(self) -> None:
        mention = _mention()
        business_object = _business_object(mention.candidate_mention_id)
        frame = _frame(mention.candidate_mention_id, business_object.candidate_business_object_id)

        for model in (mention, business_object, frame):
            data = model.to_dict()
            self.assertEqual(type(model).from_dict(data).to_dict(), data)
            self.assertEqual(data["ontology_revision_id"], ONTOLOGY_REVISION_ID)
            self.assertEqual(data["status"], "pending_review")
            self.assertTrue(data["requires_review"])

    def test_domain_pack_requires_frame_specializations_to_extend_core(self) -> None:
        pack = DomainPackDefinition.from_dict(
            {
                "domain_pack_id": stable_domain_pack_id(
                    domain_name="sales",
                    scope_type="workspace",
                    scope_id="workspace_issue28",
                    ontology_revision_id=ONTOLOGY_REVISION_ID,
                ),
                "domain_name": "sales",
                "scope_type": "workspace",
                "scope_id": "workspace_issue28",
                "ontology_revision_id": ONTOLOGY_REVISION_ID,
                "business_object_types": ["Quote", "Opportunity"],
                "frame_specializations": {
                    "QuoteApproval": "Decision",
                    "CustomerCommitment": "Commitment",
                },
                "created_at": CREATED_AT,
                "created_by": "issue28_experiment",
                "aliases": {"Quote": ["quotation"]},
            }
        )
        self.assertEqual(DomainPackDefinition.from_dict(pack.to_dict()).to_dict(), pack.to_dict())

        malformed = pack.to_dict()
        malformed["frame_specializations"] = {"QuoteApproval": "Invoice"}
        with self.assertRaises(ContractValidationError):
            DomainPackDefinition.from_dict(malformed)

    def test_canonical_frame_is_reviewed_target_but_not_graph_revision_member(self) -> None:
        mention = _mention()
        business_object = _business_object(mention.candidate_mention_id)
        frame = _frame(mention.candidate_mention_id, business_object.candidate_business_object_id)
        canonical_frame_id = stable_canonical_frame_id(
            scope_type="workspace",
            scope_id="workspace_issue28",
            frame_type="Request",
            canonical_summary="Sales requested a revised quotation.",
            source_candidate_frame_ids=[frame.candidate_frame_id],
            ontology_revision_id=ONTOLOGY_REVISION_ID,
        )
        source_ref = SourceRef(
            source_system="fixture_email",
            source_type="email_body_segment",
            source_id="obs_sales_rd_quote_firmware",
        )
        canonical = CanonicalFrame.from_dict(
            {
                "canonical_frame_id": canonical_frame_id,
                "scope_type": "workspace",
                "scope_id": "workspace_issue28",
                "frame_type": "Request",
                "canonical_summary": "Sales requested a revised quotation.",
                "ontology_revision_id": ONTOLOGY_REVISION_ID,
                "status": "active",
                "source_candidate_frame_ids": [frame.candidate_frame_id],
                "source_observation_ids": ["obs_sales_rd_quote_firmware"],
                "source_refs": [source_ref.to_dict()],
                "evidence_snapshot_ids": ["ev_issue28_fixture"],
                "citations": [
                    {
                        "citation_id": "cite_issue28_frame",
                        "source_ref": source_ref.to_dict(),
                        "evidence_snapshot_id": "ev_issue28_fixture",
                        "locator": {"line_start": 1, "line_end": 1},
                    }
                ],
                "slots": frame.slots,
                "confidence": 0.91,
                "created_at": CREATED_AT,
                "metadata": {"review_decision_ids": ["review_issue28_frame"]},
            }
        )

        data = canonical.to_dict()
        self.assertEqual(CanonicalFrame.from_dict(data).to_dict(), data)
        self.assertIn("source_candidate_frame_ids", data)
        self.assertNotIn("canonical_graph_revision_id", data)

    def test_candidate_frame_rejects_missing_evidence_and_raw_references(self) -> None:
        mention = _mention()
        business_object = _business_object(mention.candidate_mention_id)
        frame = _frame(mention.candidate_mention_id, business_object.candidate_business_object_id)

        missing_evidence = frame.to_dict()
        missing_evidence["evidence_span"] = {}
        with self.assertRaises(ContractValidationError):
            CandidateFrame.from_dict(missing_evidence)

        raw_reference = frame.to_dict()
        raw_reference["slots"] = {"target": "C:/private/mail/archive.pst"}
        with self.assertRaises(ContractValidationError):
            CandidateFrame.from_dict(raw_reference)

    def test_candidate_and_canonical_frame_reject_flat_business_label_frame_type(self) -> None:
        mention = _mention()
        business_object = _business_object(mention.candidate_mention_id)
        frame = _frame(mention.candidate_mention_id, business_object.candidate_business_object_id)

        flat_business_label = frame.to_dict()
        flat_business_label["frame_type"] = "Invoice"
        with self.assertRaises(ContractValidationError):
            CandidateFrame.from_dict(flat_business_label)

        source_ref = SourceRef(
            source_system="fixture_email",
            source_type="email_body_segment",
            source_id="obs_sales_rd_quote_firmware",
        )
        canonical_frame_id = stable_canonical_frame_id(
            scope_type="workspace",
            scope_id="workspace_issue28",
            frame_type="Invoice",
            canonical_summary="A flat invoice label must not become a frame.",
            source_candidate_frame_ids=[frame.candidate_frame_id],
            ontology_revision_id=ONTOLOGY_REVISION_ID,
        )
        with self.assertRaises(ContractValidationError):
            CanonicalFrame.from_dict(
                {
                    "canonical_frame_id": canonical_frame_id,
                    "scope_type": "workspace",
                    "scope_id": "workspace_issue28",
                    "frame_type": "Invoice",
                    "canonical_summary": "A flat invoice label must not become a frame.",
                    "ontology_revision_id": ONTOLOGY_REVISION_ID,
                    "status": "active",
                    "source_candidate_frame_ids": [frame.candidate_frame_id],
                    "source_observation_ids": ["obs_sales_rd_quote_firmware"],
                    "source_refs": [source_ref.to_dict()],
                    "evidence_snapshot_ids": ["ev_issue28_fixture"],
                    "citations": [
                        {
                            "citation_id": "cite_issue28_frame",
                            "source_ref": source_ref.to_dict(),
                            "evidence_snapshot_id": "ev_issue28_fixture",
                            "locator": {"line_start": 1, "line_end": 1},
                        }
                    ],
                    "slots": frame.slots,
                    "confidence": 0.91,
                    "created_at": CREATED_AT,
                }
            )


def _mention() -> CandidateMention:
    mention_id = stable_candidate_mention_id(
        source_observation_ids=["obs_sales_rd_quote_firmware"],
        mention_type="Actor",
        label="sales_manager",
        evidence_span={"line_start": 1, "line_end": 1},
        extractor_run_id=EXTRACTOR_RUN_ID,
        ontology_revision_id=ONTOLOGY_REVISION_ID,
    )
    return CandidateMention.from_dict(
        {
            "candidate_mention_id": mention_id,
            "source_observation_ids": ["obs_sales_rd_quote_firmware"],
            "mention_type": "Actor",
            "label": "sales_manager",
            "normalized_value": "sales_manager",
            "evidence_span": {"line_start": 1, "line_end": 1},
            "confidence": 0.9,
            "extractor_run_id": EXTRACTOR_RUN_ID,
            "ontology_revision_id": ONTOLOGY_REVISION_ID,
            "status": "pending_review",
            "requires_review": True,
            "created_at": CREATED_AT,
            "properties": {"slot_name": "actor"},
        }
    )


def _business_object(source_mention_id: str) -> CandidateBusinessObject:
    object_id = stable_candidate_business_object_id(
        object_type="Quote",
        label="quote_v2",
        source_mention_ids=[source_mention_id],
        ontology_revision_id=ONTOLOGY_REVISION_ID,
        extractor_run_id=EXTRACTOR_RUN_ID,
    )
    return CandidateBusinessObject.from_dict(
        {
            "candidate_business_object_id": object_id,
            "object_type": "Quote",
            "label": "quote_v2",
            "source_mention_ids": [source_mention_id],
            "source_observation_ids": ["obs_sales_rd_quote_firmware"],
            "ontology_revision_id": ONTOLOGY_REVISION_ID,
            "confidence": 0.9,
            "extractor_run_id": EXTRACTOR_RUN_ID,
            "status": "pending_review",
            "requires_review": True,
            "domain_hints": ["sales", "rd"],
            "created_at": CREATED_AT,
            "properties": {"source_slot": "target"},
        }
    )


def _frame(source_mention_id: str, source_business_object_id: str) -> CandidateFrame:
    slots = {
        "actor": "sales_manager",
        "target": "quote_v2",
        "requested_action": "deliver revised quotation",
        "deadline": "2026-07-20",
        "obligation": "coordination_obligation",
    }
    frame_id = stable_candidate_frame_id(
        frame_type="Request",
        slots=slots,
        source_observation_ids=["obs_sales_rd_quote_firmware"],
        ontology_revision_id=ONTOLOGY_REVISION_ID,
        extractor_run_id=EXTRACTOR_RUN_ID,
    )
    return CandidateFrame.from_dict(
        {
            "candidate_frame_id": frame_id,
            "frame_type": "Request",
            "source_observation_ids": ["obs_sales_rd_quote_firmware"],
            "ontology_revision_id": ONTOLOGY_REVISION_ID,
            "slots": slots,
            "evidence_span": {"line_start": 1, "line_end": 1},
            "confidence": 0.9,
            "extractor_run_id": EXTRACTOR_RUN_ID,
            "status": "pending_review",
            "requires_review": True,
            "source_mention_ids": [source_mention_id],
            "source_business_object_ids": [source_business_object_id],
            "domain_hints": ["sales", "rd"],
            "created_at": CREATED_AT,
            "properties": {"representation": "ontology_v2_coordination_frame"},
        }
    )


if __name__ == "__main__":
    unittest.main()
