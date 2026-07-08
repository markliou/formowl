from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, Observation
from formowl_graph.coordination_frames import (
    DeterministicCoordinationFrameExtractor,
    DomainPackDefinition,
    extract_and_store_coordination_frames,
)
from formowl_graph.storage import (
    CandidateBusinessObjectStore,
    CandidateFrameStore,
    CandidateMentionStore,
)


CREATED_AT = "2026-07-08T09:00:00+00:00"
PERMISSION_SCOPE = {
    "scope_type": "workspace",
    "scope_id": "formowl",
    "visibility": "restricted",
}


class CoordinationFrameExtractionTests(unittest.TestCase):
    def test_domain_pack_extensions_must_target_coordination_core(self) -> None:
        pack = _domain_pack()
        self.assertEqual(pack.frame_extensions["QuoteApproval"], "Decision")
        self.assertEqual(pack.object_types["Quote"], "WorkObject")

        with self.assertRaises(ContractValidationError):
            DomainPackDefinition.from_dict(
                {
                    **pack.to_dict(),
                    "frame_extensions": {"QuoteApproval": "Email"},
                }
            )

        with self.assertRaises(ContractValidationError):
            DomainPackDefinition.from_dict(
                {
                    **pack.to_dict(),
                    "object_types": {"Quote": "Invoice"},
                }
            )

    def test_extractor_creates_candidate_frames_mentions_and_business_objects(self) -> None:
        observations = [
            _observation(
                "obs_email_sales_rd",
                """
Request: actor=Sales; target=Quote v2; action=deliver revised quotation; deadline=2026-07-20; condition=firmware confirmed; fallback=use old specification; domains=sales,rd; object_type=Quote
Blocker: actor=R&D; target=Firmware capability; blocker=firmware confirmation pending; owner=Firmware team; deadline=2026-07-12; domains=rd,sales; object_type=FirmwareSpec
Deadline: actor=Customer; target=Quote v2; deadline=2026-07-20; domains=sales; object_type=Quote
""",
            )
        ]

        result = DeterministicCoordinationFrameExtractor().extract(
            observations,
            extractor_run_id="run_coordination_001",
            ontology_revision_id="ontology_rev_coordination_v2_001",
            domain_packs=[_domain_pack()],
            created_at=CREATED_AT,
        )

        frame_types = [frame.frame_type for frame in result.candidate_frames]
        self.assertEqual(frame_types, ["Request", "Blocker", "Deadline"])
        self.assertGreaterEqual(len(result.candidate_mentions), 12)
        self.assertEqual(len(result.candidate_business_objects), 3)
        for frame in result.candidate_frames:
            data = frame.to_dict()
            self.assertTrue(data["evidence_spans"])
            self.assertEqual(data["status"], "pending_review")
            self.assertFalse(data["metadata"]["canonical_write_allowed"])
            self.assertIn("permission_scope", data["access_boundary"])
            self.assertIn(data["frame_type"], {"Request", "Blocker", "Deadline"})

    def test_domain_specific_frame_maps_to_core_frame_without_core_mutation(self) -> None:
        observations = [
            _observation(
                "obs_email_finance_sales",
                """
InvoiceApproval: actor=Finance; target=Invoice INV-22; decision=approve revised payment term; owner=Controller; domains=finance,sales; object_type=Invoice
""",
            )
        ]

        result = DeterministicCoordinationFrameExtractor().extract(
            observations,
            extractor_run_id="run_coordination_002",
            ontology_revision_id="ontology_rev_coordination_v2_001",
            domain_packs=[_domain_pack()],
            created_at=CREATED_AT,
        )

        self.assertEqual(len(result.candidate_frames), 1)
        frame = result.candidate_frames[0]
        self.assertEqual(frame.frame_type, "Decision")
        self.assertEqual(frame.metadata["raw_frame_type"], "InvoiceApproval")
        self.assertEqual(frame.metadata["domain_pack_ids"], ["coord_pack_enterprise_v2"])

    def test_extract_and_store_writes_candidate_collections_only(self) -> None:
        observations = [
            _observation(
                "obs_email_project",
                """
Decision: actor=Management; target=Project Alpha; decision=use phased rollout; owner=PMO; domains=management,project; object_type=ProjectPlan
Dependency: actor=PMO; target=Project Alpha; depends_on=QA signoff; owner=QA; domains=project,production; object_type=ProjectPlan
OpenQuestion: actor=QA; target=Project Alpha; question=which acceptance checklist applies; owner=QA; domains=project,production; object_type=ProjectPlan
""",
            )
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            result = extract_and_store_coordination_frames(
                observations=observations,
                candidate_mention_store=CandidateMentionStore(temp_dir),
                candidate_business_object_store=CandidateBusinessObjectStore(temp_dir),
                candidate_frame_store=CandidateFrameStore(temp_dir),
                extractor_run_id="run_coordination_003",
                ontology_revision_id="ontology_rev_coordination_v2_001",
                domain_packs=[_domain_pack()],
                created_at=CREATED_AT,
            )

            self.assertEqual(len(CandidateFrameStore(temp_dir).list()), 3)
            self.assertEqual(
                len(CandidateBusinessObjectStore(temp_dir).list()),
                len(result.candidate_business_objects),
            )
            self.assertEqual(
                len(CandidateMentionStore(temp_dir).list()),
                len(result.candidate_mentions),
            )
            graph_dir = Path(temp_dir) / "graph"
            self.assertFalse((graph_dir / "canonical-frames").exists())
            self.assertFalse((graph_dir / "user-graph-revisions").exists())
            self.assertFalse((Path(temp_dir) / "wiki").exists())

    def test_access_boundary_preserves_redacted_slot_names(self) -> None:
        observations = [
            _observation(
                "obs_email_private",
                """
Escalation: actor=Sales; target=Payment issue; owner=VP Sales; domains=sales,finance; object_type=CustomerCommitment; redacted_slots=owner
""",
            )
        ]

        result = DeterministicCoordinationFrameExtractor().extract(
            observations,
            extractor_run_id="run_coordination_004",
            ontology_revision_id="ontology_rev_coordination_v2_001",
            domain_packs=[_domain_pack()],
            created_at=CREATED_AT,
        )

        self.assertEqual(
            result.candidate_frames[0].access_boundary["redacted_slot_names"], ["owner"]
        )


def _domain_pack() -> DomainPackDefinition:
    return DomainPackDefinition.from_dict(
        {
            "pack_id": "coord_pack_enterprise_v2",
            "domain": "sales",
            "ontology_revision_id": "ontology_rev_coordination_v2_001",
            "source_observation_ids": ["obs_domain_pack_001"],
            "frame_extensions": {
                "CustomerRequest": "Request",
                "CustomerCommitment": "Commitment",
                "InvoiceApproval": "Decision",
                "FirmwareCapabilityQuestion": "OpenQuestion",
                "ShipmentDelay": "Blocker",
                "InventoryShortage": "Blocker",
                "LineStopIncident": "Issue",
                "QuoteApproval": "Decision",
            },
            "object_types": {
                "Quote": "WorkObject",
                "FirmwareSpec": "WorkObject",
                "Shipment": "WorkObject",
                "WorkOrder": "WorkObject",
                "Invoice": "WorkObject",
                "CustomerCommitment": "WorkObject",
                "ProjectPlan": "WorkObject",
            },
            "aliases": {"complaint": ["customer issue", "客訴"]},
        }
    )


def _observation(observation_id: str, text: str) -> Observation:
    return Observation(
        observation_id=observation_id,
        asset_id="asset_mail_fixture",
        extractor_run_id="run_mail_fixture",
        observation_type="email_body_segment",
        modality="text",
        text=text.strip(),
        location={"message_id": observation_id.replace("obs_", "msg_"), "section": "body"},
        confidence=0.95,
        permission_scope=PERMISSION_SCOPE,
        created_at=CREATED_AT,
    )


if __name__ == "__main__":
    unittest.main()
