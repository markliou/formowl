from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_contract import (
    ASSERTION_KIND_VALUES,
    CandidateAssertion,
    ContractValidationError,
    EPISTEMIC_STATUS_VALUES,
    TemporalContext,
    sha256_json,
    stable_candidate_assertion_id,
)
from formowl_graph import DomainPackDefinition


CREATED_AT = "2026-07-15T04:00:00+00:00"
DOMAIN_PACK_CONTENT_HASH = sha256_json({"fixture": "domain pack"})
PERMISSION_SCOPE = {
    "scope_type": "workspace",
    "scope_id": "formowl",
    "visibility": "restricted",
}
EVIDENCE_SPAN = {
    "span_id": "span_candidate_assertion_001",
    "source_observation_id": "obs_candidate_assertion_001",
    "locator": {"section": "fixture", "row_index": 1},
    "text_hash": sha256_json({"fixture": "candidate assertion"}),
}


class CandidateAssertionContractTests(unittest.TestCase):
    def test_all_universal_assertion_kinds_round_trip_as_reviewable_candidates(
        self,
    ) -> None:
        variants = {
            "property": {"value": "2026-07-31"},
            "relation": {"object_candidate_business_object_id": "cbobj_supplier_001"},
            "state": {"value": "pending"},
            "event": {
                "previous_value": "pending",
                "proposed_value": "approved",
            },
            "coordination": {
                "actor_candidate_business_object_id": "cbobj_actor_001",
                "counterparty_candidate_business_object_id": "cbobj_counterparty_001",
                "value": "deliver_by_due_date",
            },
        }

        self.assertEqual(set(variants), set(ASSERTION_KIND_VALUES))
        for assertion_kind, semantic_fields in variants.items():
            with self.subTest(assertion_kind=assertion_kind):
                assertion = _candidate_assertion(
                    assertion_kind=assertion_kind,
                    **semantic_fields,
                )
                data = assertion.to_dict()
                self.assertEqual(CandidateAssertion.from_dict(data).to_dict(), data)
                self.assertEqual(assertion.status, "pending_review")
                self.assertTrue(assertion.requires_review)
                self.assertFalse(assertion.metadata["canonical_write_allowed"])
                self.assertEqual(
                    assertion.source_observation_ids,
                    ["obs_candidate_assertion_001"],
                )
                self.assertEqual(
                    assertion.evidence_spans[0]["source_observation_id"],
                    "obs_candidate_assertion_001",
                )

    def test_stable_id_is_order_independent_and_includes_participants(self) -> None:
        common = {
            "source_observation_ids": [
                "obs_candidate_assertion_002",
                "obs_candidate_assertion_001",
            ],
            "assertion_kind": "coordination",
            "subject_candidate_business_object_id": "cbobj_subject_001",
            "predicate": "Commitment",
            "actor_candidate_business_object_id": "cbobj_actor_001",
            "counterparty_candidate_business_object_id": "cbobj_counterparty_001",
            "value": "deliver",
            "extractor_run_id": "run_candidate_assertion_001",
            "ontology_revision_id": "ontology_rev_candidate_core_v1",
            "domain_pack_id": "domain_pack_procurement_v1",
            "domain_pack_content_hash": DOMAIN_PACK_CONTENT_HASH,
        }
        first = stable_candidate_assertion_id(
            **common,
            temporal_context={"effective_at": "2026-07-31", "precision": "day"},
            context={"b": 2, "a": 1},
        )
        second = stable_candidate_assertion_id(
            **{
                **common,
                "source_observation_ids": list(reversed(common["source_observation_ids"])),
            },
            temporal_context={"precision": "day", "effective_at": "2026-07-31"},
            context={"a": 1, "b": 2},
        )
        different_actor = stable_candidate_assertion_id(
            **{**common, "actor_candidate_business_object_id": "cbobj_actor_002"}
        )
        different_counterparty = stable_candidate_assertion_id(
            **{
                **common,
                "counterparty_candidate_business_object_id": ("cbobj_counterparty_002"),
            }
        )
        different_pack_content = stable_candidate_assertion_id(
            **{
                **common,
                "domain_pack_content_hash": sha256_json({"fixture": "different domain pack"}),
            }
        )
        different_epistemic_status = stable_candidate_assertion_id(
            **common,
            epistemic_status="committed",
        )
        different_lifecycle_status = stable_candidate_assertion_id(
            **common,
            lifecycle_status="corrected",
        )

        self.assertEqual(first, second)
        self.assertTrue(first.startswith("cassert_"))
        self.assertNotEqual(first, different_actor)
        self.assertNotEqual(first, different_counterparty)
        self.assertNotEqual(first, different_pack_content)
        self.assertNotEqual(first, different_epistemic_status)
        self.assertNotEqual(first, different_lifecycle_status)

    def test_kind_specific_requirements_reject_empty_semantics(self) -> None:
        valid_coordination = _candidate_assertion(
            "coordination",
            actor_candidate_business_object_id="cbobj_actor_001",
            value="deliver",
        ).to_dict()
        invalid_payloads = [
            {**_candidate_assertion("property", value="x").to_dict(), "value": None},
            {**_candidate_assertion("property", value="x").to_dict(), "value": "   "},
            {**_candidate_assertion("state", value="x").to_dict(), "value": None},
            {**_candidate_assertion("state", value="x").to_dict(), "value": {}},
            {
                key: value
                for key, value in _candidate_assertion(
                    "relation",
                    object_candidate_business_object_id="cbobj_object_001",
                )
                .to_dict()
                .items()
                if key != "object_candidate_business_object_id"
            },
            {
                **_candidate_assertion(
                    "event",
                    previous_value="pending",
                    proposed_value="approved",
                ).to_dict(),
                "previous_value": None,
                "proposed_value": None,
            },
            {
                **_candidate_assertion(
                    "event",
                    previous_value="pending",
                    proposed_value="approved",
                ).to_dict(),
                "previous_value": " ",
                "proposed_value": [],
            },
            {
                **_candidate_assertion(
                    "event",
                    previous_value="pending",
                    proposed_value="approved",
                ).to_dict(),
                "previous_value": "pending",
                "proposed_value": "pending",
            },
            {
                key: value
                for key, value in valid_coordination.items()
                if key
                not in {
                    "actor_candidate_business_object_id",
                    "counterparty_candidate_business_object_id",
                    "value",
                }
            },
            {
                **valid_coordination,
                "predicate": "DepartmentApproval",
            },
            {
                **_candidate_assertion("property", value="x").to_dict(),
                "assertion_kind": "department_specific_fact",
            },
            {
                **_candidate_assertion("property", value="x").to_dict(),
                "domain_pack_content_hash": "not-a-sha256",
            },
        ]

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ContractValidationError):
                    CandidateAssertion.from_dict(payload)

    def test_predicate_and_pack_hash_require_canonical_non_empty_forms(self) -> None:
        valid = _candidate_assertion("property", value="x").to_dict()
        invalid_payloads = [
            {**valid, "predicate": "   "},
            {**valid, "domain_pack_content_hash": "sha256:x"},
            {**valid, "domain_pack_content_hash": "sha256:" + "A" * 64},
            {**valid, "domain_pack_content_hash": "sha256:" + "a" * 63},
            {**valid, "domain_pack_content_hash": "sha256:" + "a" * 65},
        ]

        for payload in invalid_payloads:
            with self.subTest(
                predicate=payload["predicate"],
                domain_pack_content_hash=payload["domain_pack_content_hash"],
            ):
                with self.assertRaises(ContractValidationError):
                    CandidateAssertion.from_dict(payload)

    def test_relation_and_evidence_references_must_be_governed_ids(self) -> None:
        relation = _candidate_assertion(
            "relation",
            object_candidate_business_object_id="cbobj_object_001",
        ).to_dict()
        with self.assertRaises(ContractValidationError):
            CandidateAssertion.from_dict(
                {
                    **relation,
                    "object_candidate_business_object_id": "../private/object",
                }
            )
        with self.assertRaises(ContractValidationError):
            CandidateAssertion.from_dict(
                {
                    **relation,
                    "evidence_spans": [
                        {
                            **EVIDENCE_SPAN,
                            "source_observation_id": "obs_not_in_lineage",
                        }
                    ],
                }
            )
        with self.assertRaises(ContractValidationError):
            CandidateAssertion.from_dict(
                {
                    **relation,
                    "context": {"internal_note": "/tmp/private/export.csv"},
                }
            )
        for unsafe_value in (
            "s3://private-bucket/export.csv",
            "object://private/export.csv",
            "minio://private/export.csv",
            "formowl://object/private/export.csv",
            "truncate table candidate_assertions",
            "COPY candidate_assertions TO STDOUT",
            "WITH x AS (VALUES (1)) SELECT 1",
            "GRANT SELECT ON candidate_assertions TO analyst",
            (
                "MERGE INTO candidate_assertions AS target "
                "USING staged_assertions AS source ON target.id = source.id"
            ),
            "CALL refresh_candidate_assertions()",
            ("/tmp/private/procurement.xlsx",),
        ):
            with self.subTest(unsafe_value=unsafe_value):
                with self.assertRaises(ContractValidationError):
                    CandidateAssertion.from_dict(
                        {
                            **relation,
                            "context": {"internal_note": unsafe_value},
                        }
                    )

    def test_candidate_assertion_cannot_enable_canonical_write(self) -> None:
        valid = _candidate_assertion("property", value="x").to_dict()
        invalid_payloads = [
            {
                **valid,
                "metadata": {
                    **valid["metadata"],
                    "canonical_write_allowed": True,
                },
            },
            {**valid, "canonical_write_allowed": True},
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ContractValidationError):
                    CandidateAssertion.from_dict(payload)

    def test_domain_pack_round_trips_scoped_vocabulary_over_stable_core(self) -> None:
        pack = _domain_pack()

        self.assertEqual(DomainPackDefinition.from_dict(pack.to_dict()), pack)
        self.assertEqual(pack.to_dict()["content_hash"], pack.content_hash)
        self.assertEqual(pack.resolve_core_supertype("Invoice"), "Transaction")
        self.assertEqual(
            pack.resolve_assertion_mapping("approval_request"),
            {
                "assertion_kind": "coordination",
                "predicate": "Request",
                "epistemic_status": "asserted",
                "lifecycle_status": "active",
                "temporal_roles": {},
            },
        )

    def test_temporal_context_and_epistemic_status_are_first_class_candidate_fields(
        self,
    ) -> None:
        context = TemporalContext.from_dict(
            {
                "valid_from": "2026-07-01",
                "valid_to": "2026-07-31",
                "recorded_at": "2026-07-15T04:00:00+00:00",
                "precision": "day",
                "uncertainty": 0.1,
            }
        )
        assertion = _candidate_assertion("state", value="active")
        payload = assertion.to_dict()
        payload["epistemic_status"] = "actual"
        payload["temporal_context"] = context.to_dict()
        payload["candidate_assertion_id"] = stable_candidate_assertion_id(
            source_observation_ids=payload["source_observation_ids"],
            assertion_kind=payload["assertion_kind"],
            subject_candidate_business_object_id=payload["subject_candidate_business_object_id"],
            predicate=payload["predicate"],
            value=payload["value"],
            temporal_context=payload["temporal_context"],
            context=payload["context"],
            extractor_run_id=payload["extractor_run_id"],
            ontology_revision_id=payload["ontology_revision_id"],
            domain_pack_id=payload["domain_pack_id"],
            domain_pack_content_hash=payload["domain_pack_content_hash"],
            epistemic_status="actual",
            lifecycle_status="active",
        )

        candidate = CandidateAssertion.from_dict(payload)

        self.assertIn(candidate.epistemic_status, EPISTEMIC_STATUS_VALUES)
        self.assertEqual(candidate.epistemic_status, "actual")
        self.assertEqual(candidate.lifecycle_status, "active")
        self.assertEqual(candidate.temporal_context, context.to_dict())
        with self.assertRaises(ContractValidationError):
            TemporalContext.from_dict({"valid_from": "2026-08-01", "valid_to": "2026-07-31"})

    def test_domain_pack_rejects_core_bypass_and_invalid_assertion_mapping(
        self,
    ) -> None:
        valid = _domain_pack().to_dict()
        invalid_packs = [
            {**valid, "object_types": {"Invoice": "DepartmentInvoice"}},
            {**valid, "canonical_write_allowed": True},
            {
                **valid,
                "assertion_mappings": {
                    "invoice_amount": {
                        "assertion_kind": "department_specific_fact",
                        "predicate": "invoice_amount",
                    }
                },
            },
            {
                **valid,
                "assertion_mappings": {
                    "invoice_amount": {
                        "assertion_kind": "property",
                        "predicate": "invoice_amount",
                        "lifecycle_status": "withdrawn",
                    }
                },
            },
            {
                **valid,
                "assertion_mappings": {
                    "invoice_amount": {
                        "assertion_kind": "property",
                        "predicate": "invoice_amount",
                        "epistemic_status": "rumored",
                    }
                },
            },
            {
                **valid,
                "assertion_mappings": {
                    "invoice_amount": {
                        "assertion_kind": "property",
                        "predicate": "invoice_amount",
                        "temporal_roles": {"posting_day": "department_time"},
                    }
                },
            },
            {
                **valid,
                "assertion_mappings": {
                    "invoice_amount": {
                        "assertion_kind": "property",
                        "predicate": "invoice_amount",
                        "temporal_roles": {"posting_day": "captured_at"},
                    }
                },
            },
            {
                **valid,
                "assertion_mappings": {
                    "approval_request": {
                        "assertion_kind": "coordination",
                        "predicate": "FinanceApproval",
                    }
                },
            },
            {
                **valid,
                "content_hash": sha256_json({"tampered": True}),
            },
        ]
        for pack in invalid_packs:
            with self.subTest(pack=pack):
                with self.assertRaises(ContractValidationError):
                    DomainPackDefinition.from_dict(pack)

        legacy = DomainPackDefinition.from_dict(
            {
                **{key: value for key, value in valid.items() if key != "content_hash"},
                "object_types": {"Invoice": "WorkObject"},
            }
        )
        with self.assertRaises(ContractValidationError):
            legacy.resolve_core_supertype("Invoice")


def _candidate_assertion(
    assertion_kind: str,
    *,
    object_candidate_business_object_id: str | None = None,
    actor_candidate_business_object_id: str | None = None,
    counterparty_candidate_business_object_id: str | None = None,
    value: object | None = None,
    previous_value: object | None = None,
    proposed_value: object | None = None,
) -> CandidateAssertion:
    predicate = "Commitment" if assertion_kind == "coordination" else "fixture_predicate"
    assertion_id = stable_candidate_assertion_id(
        source_observation_ids=["obs_candidate_assertion_001"],
        assertion_kind=assertion_kind,
        subject_candidate_business_object_id="cbobj_subject_001",
        predicate=predicate,
        object_candidate_business_object_id=object_candidate_business_object_id,
        actor_candidate_business_object_id=actor_candidate_business_object_id,
        counterparty_candidate_business_object_id=(counterparty_candidate_business_object_id),
        value=value,
        previous_value=previous_value,
        proposed_value=proposed_value,
        temporal_context={"observed_at": "2026-07-15"},
        context={"fixture": True},
        extractor_run_id="run_candidate_assertion_001",
        ontology_revision_id="ontology_rev_candidate_core_v1",
        domain_pack_id="domain_pack_fixture_v1",
        domain_pack_content_hash=DOMAIN_PACK_CONTENT_HASH,
    )
    payload = {
        "candidate_assertion_id": assertion_id,
        "assertion_kind": assertion_kind,
        "subject_candidate_business_object_id": "cbobj_subject_001",
        "predicate": predicate,
        "source_observation_ids": ["obs_candidate_assertion_001"],
        "evidence_spans": [EVIDENCE_SPAN],
        "permission_scope": PERMISSION_SCOPE,
        "confidence": 0.9,
        "extractor_run_id": "run_candidate_assertion_001",
        "ontology_revision_id": "ontology_rev_candidate_core_v1",
        "domain_pack_id": "domain_pack_fixture_v1",
        "domain_pack_content_hash": DOMAIN_PACK_CONTENT_HASH,
        "status": "pending_review",
        "requires_review": True,
        "temporal_context": {"observed_at": "2026-07-15"},
        "context": {"fixture": True},
        "created_at": CREATED_AT,
        "metadata": {"canonical_write_allowed": False},
    }
    for field_name, field_value in (
        ("object_candidate_business_object_id", object_candidate_business_object_id),
        ("actor_candidate_business_object_id", actor_candidate_business_object_id),
        (
            "counterparty_candidate_business_object_id",
            counterparty_candidate_business_object_id,
        ),
        ("value", value),
        ("previous_value", previous_value),
        ("proposed_value", proposed_value),
    ):
        if field_value is not None:
            payload[field_name] = field_value
    return CandidateAssertion.from_dict(payload)


def _domain_pack() -> DomainPackDefinition:
    return DomainPackDefinition.from_dict(
        {
            "pack_id": "domain_pack_finance_v1",
            "domain": "finance",
            "ontology_revision_id": "ontology_rev_candidate_core_v1",
            "source_observation_ids": ["obs_domain_pack_finance_v1"],
            "object_types": {
                "Invoice": "Transaction",
                "Controller": "Person",
            },
            "assertion_mappings": {
                "invoice_amount": {
                    "assertion_kind": "property",
                    "predicate": "invoice_amount",
                },
                "approval_request": {
                    "assertion_kind": "coordination",
                    "predicate": "Request",
                },
            },
            "frame_extensions": {"PaymentApprovalRequest": "Request"},
            "aliases": {"Invoice": ["payable document"]},
        }
    )


if __name__ == "__main__":
    unittest.main()
