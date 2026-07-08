from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_contract import (
    CandidateBusinessObject,
    CandidateFrame,
    CandidateMention,
    CanonicalFrame,
    ContractValidationError,
    ExternalGraphImport,
    SourceRef,
    sha256_json,
    stable_candidate_business_object_id,
    stable_candidate_frame_id,
    stable_candidate_mention_id,
    stable_canonical_frame_id,
    stable_external_graph_import_id,
)


CREATED_AT = "2026-07-08T09:00:00+00:00"
PERMISSION_SCOPE = {
    "scope_type": "workspace",
    "scope_id": "formowl",
    "visibility": "restricted",
}
ACCESS_BOUNDARY = {
    "boundary_type": "source_observation_scope",
    "permission_scope": PERMISSION_SCOPE,
    "raw_access_required": False,
    "redacted_slot_names": [],
}
EVIDENCE_SPAN = {
    "span_id": "span_obs_email_001_1",
    "source_observation_id": "obs_email_001",
    "locator": {"message_id": "msg_001", "line": 1},
    "text_hash": sha256_json({"line": "Request fixture line"}),
}


class CoordinationFrameContractTests(unittest.TestCase):
    def test_candidate_frame_contracts_round_trip(self) -> None:
        mention = _candidate_mention()
        business_object = _candidate_business_object([mention.candidate_mention_id])
        frame = _candidate_frame(
            [mention.candidate_mention_id],
            [business_object.candidate_business_object_id],
        )
        source_ref = SourceRef(
            source_system="fixture_mail",
            source_type="candidate_coordination_frames",
            source_id="import_001",
        )
        graph_import = ExternalGraphImport(
            external_graph_import_id=stable_external_graph_import_id(
                source_system="fixture_mail",
                source_ref=source_ref,
                extractor_run_id="run_coordination_001",
                imported_at=CREATED_AT,
            ),
            source_system="fixture_mail",
            source_ref=source_ref,
            extractor_run_id="run_coordination_001",
            imported_at=CREATED_AT,
            candidate_mention_ids=[mention.candidate_mention_id],
            candidate_business_object_ids=[business_object.candidate_business_object_id],
            candidate_frame_ids=[frame.candidate_frame_id],
            metadata={"canonical_write_allowed": False},
        )

        for model in (mention, business_object, frame, graph_import):
            data = model.to_dict()
            self.assertEqual(type(model).from_dict(data).to_dict(), data)

        self.assertTrue(frame.requires_review)
        self.assertEqual(frame.status, "pending_review")
        self.assertFalse(frame.metadata["canonical_write_allowed"])

    def test_candidate_ids_are_stable_from_evidence_and_slots(self) -> None:
        first = stable_candidate_frame_id(
            source_observation_ids=["obs_email_001"],
            frame_type="Request",
            slots={"target": "Quote v2", "actor": "Sales"},
            evidence_spans=[EVIDENCE_SPAN],
            extractor_run_id="run_coordination_001",
        )
        second = stable_candidate_frame_id(
            source_observation_ids=["obs_email_001"],
            frame_type="Request",
            slots={"actor": "Sales", "target": "Quote v2"},
            evidence_spans=[EVIDENCE_SPAN],
            extractor_run_id="run_coordination_001",
        )
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("cframe_"))

        mention_id = stable_candidate_mention_id(
            source_observation_ids=["obs_email_001"],
            mention_type="actor",
            normalized_label="Sales",
            location={"message_id": "msg_001", "line": 1, "slot": "actor"},
            extractor_run_id="run_coordination_001",
        )
        object_id = stable_candidate_business_object_id(
            source_observation_ids=["obs_email_001"],
            object_type="Quote",
            label="Quote v2",
            properties={"line": 1},
            extractor_run_id="run_coordination_001",
        )
        self.assertTrue(mention_id.startswith("cmention_"))
        self.assertTrue(object_id.startswith("cbobj_"))

    def test_canonical_frame_contract_is_review_target_not_store_write_path(self) -> None:
        candidate = _candidate_frame([], [])
        canonical_id = stable_canonical_frame_id(
            scope_type="workspace",
            scope_id="formowl",
            ontology_revision_id="ontology_rev_coordination_v2_001",
            frame_type="Request",
            canonical_slots=candidate.slots,
            source_candidate_frame_ids=[candidate.candidate_frame_id],
        )
        canonical = CanonicalFrame(
            canonical_frame_id=canonical_id,
            scope_type="workspace",
            scope_id="formowl",
            frame_type="Request",
            canonical_slots=candidate.slots,
            evidence_spans=candidate.evidence_spans,
            domain_hints=candidate.domain_hints,
            granularity_level=candidate.granularity_level,
            access_boundary=candidate.access_boundary,
            status="active",
            source_candidate_frame_ids=[candidate.candidate_frame_id],
            source_observation_ids=["obs_email_001"],
            confidence=0.82,
            ontology_revision_id="ontology_rev_coordination_v2_001",
            frame_policy_id="frame_policy_coordination_v2",
            created_at=CREATED_AT,
            created_by="reviewer_001",
            metadata={"review_event_id": "review_event_001"},
        )

        data = canonical.to_dict()
        self.assertEqual(CanonicalFrame.from_dict(data).to_dict(), data)
        self.assertTrue(data["canonical_frame_id"].startswith("canframe_"))

    def test_frame_validation_rejects_bypassing_core_or_missing_evidence(self) -> None:
        valid = _candidate_frame([], []).to_dict()

        with self.assertRaises(ContractValidationError):
            CandidateFrame.from_dict({**valid, "frame_type": "QuoteApproval"})

        with self.assertRaises(ContractValidationError):
            CandidateFrame.from_dict({**valid, "evidence_spans": []})

        with self.assertRaises(ContractValidationError):
            CandidateBusinessObject.from_dict(
                {**_candidate_business_object([]).to_dict(), "object_supertype": "Invoice"}
            )

    def test_frame_validation_rejects_raw_references_in_slots(self) -> None:
        valid = _candidate_frame([], []).to_dict()
        with self.assertRaises(ContractValidationError):
            CandidateFrame.from_dict(
                {
                    **valid,
                    "slots": {
                        **valid["slots"],
                        "target": "/home/example/private/archive.pst",
                    },
                }
            )

    def test_frame_validation_allows_business_update_language_but_rejects_sql(self) -> None:
        valid = _candidate_frame([], []).to_dict()

        allowed = CandidateFrame.from_dict(
            {
                **valid,
                "slots": {
                    **valid["slots"],
                    "action": "send payment update today",
                },
            }
        )
        self.assertEqual(allowed.slots["action"], "send payment update today")

        with self.assertRaises(ContractValidationError):
            CandidateFrame.from_dict(
                {
                    **valid,
                    "slots": {
                        **valid["slots"],
                        "action": "select * from private_table",
                    },
                }
            )

    def test_frame_validation_rejects_broader_raw_reference_shapes(self) -> None:
        valid = _candidate_frame([], []).to_dict()
        raw_reference_values = [
            r"\\nas01\private\archive.pst",
            "//nas01/share/archive.pst",
            "/Users/example/private/archive.pst",
            "/etc/passwd",
            "../private/archive.pst",
            "./scratch/tmp/archive.pst",
            "~/private/archive.pst",
            r"..\private\archive.pst",
            r".\scratch\tmp\archive.pst",
            "nas/share/archive.pst",
            "scratch/tmp/archive.pst",
        ]

        for raw_value in raw_reference_values:
            with self.subTest(raw_value=raw_value):
                with self.assertRaises(ContractValidationError):
                    CandidateFrame.from_dict(
                        {
                            **valid,
                            "slots": {
                                **valid["slots"],
                                "target": raw_value,
                            },
                        }
                    )

        with self.assertRaises(ContractValidationError):
            CandidateBusinessObject.from_dict(
                {
                    **_candidate_business_object([]).to_dict(),
                    "label": r"\\nas01\private\quote.xlsx",
                }
            )


def _candidate_mention() -> CandidateMention:
    location = {"message_id": "msg_001", "line": 1, "slot": "actor"}
    return CandidateMention(
        candidate_mention_id=stable_candidate_mention_id(
            source_observation_ids=["obs_email_001"],
            mention_type="actor",
            normalized_label="Sales",
            location=location,
            extractor_run_id="run_coordination_001",
        ),
        source_observation_ids=["obs_email_001"],
        mention_type="actor",
        normalized_label="Sales",
        location=location,
        text_hash=sha256_json({"mention": "Sales"}),
        confidence=0.86,
        extractor_run_id="run_coordination_001",
        status="pending_review",
        requires_review=True,
        created_at=CREATED_AT,
        metadata={"canonical_write_allowed": False},
    )


def _candidate_business_object(source_candidate_mention_ids: list[str]) -> CandidateBusinessObject:
    properties = {"line": 1, "source_observation_type": "email_body_segment"}
    return CandidateBusinessObject(
        candidate_business_object_id=stable_candidate_business_object_id(
            source_observation_ids=["obs_email_001"],
            object_type="Quote",
            label="Quote v2",
            properties=properties,
            extractor_run_id="run_coordination_001",
        ),
        source_observation_ids=["obs_email_001"],
        object_type="Quote",
        object_supertype="WorkObject",
        label="Quote v2",
        domain_hints=["rd", "sales"],
        properties=properties,
        granularity_level="work_object_reference",
        access_boundary=ACCESS_BOUNDARY,
        confidence=0.84,
        extractor_run_id="run_coordination_001",
        status="pending_review",
        requires_review=True,
        source_candidate_mention_ids=source_candidate_mention_ids,
        created_at=CREATED_AT,
        metadata={"canonical_write_allowed": False},
    )


def _candidate_frame(
    source_candidate_mention_ids: list[str],
    candidate_business_object_ids: list[str],
) -> CandidateFrame:
    slots = {
        "actor": "Sales",
        "target": "Quote v2",
        "action": "deliver revised quotation",
        "deadline": "2026-07-20",
    }
    return CandidateFrame(
        candidate_frame_id=stable_candidate_frame_id(
            source_observation_ids=["obs_email_001"],
            frame_type="Request",
            slots=slots,
            evidence_spans=[EVIDENCE_SPAN],
            extractor_run_id="run_coordination_001",
        ),
        source_observation_ids=["obs_email_001"],
        frame_type="Request",
        slots=slots,
        evidence_spans=[EVIDENCE_SPAN],
        domain_hints=["rd", "sales"],
        granularity_level="coordination_obligation",
        access_boundary=ACCESS_BOUNDARY,
        confidence=0.82,
        extractor_run_id="run_coordination_001",
        ontology_revision_id="ontology_rev_coordination_v2_001",
        status="pending_review",
        requires_review=True,
        source_candidate_mention_ids=source_candidate_mention_ids,
        candidate_business_object_ids=candidate_business_object_ids,
        created_at=CREATED_AT,
        metadata={"canonical_write_allowed": False},
    )


if __name__ == "__main__":
    unittest.main()
