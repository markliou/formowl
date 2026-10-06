from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest import mock

import _paths
from formowl_contract import (
    ASSERTION_KIND_VALUES,
    CORE_SUPERTYPE_IDS,
    CandidateAssertion,
    CandidateBusinessObject,
    ContractValidationError,
    Observation,
    stable_candidate_assertion_id,
    stable_candidate_business_object_id,
)
from formowl_graph import (
    CandidateKnowledgeExtractionResult,
    DeterministicCandidateKnowledgeExtractor,
    DomainPackDefinition,
    extract_and_store_candidate_knowledge,
)
from formowl_graph.storage import (
    CandidateAssertionStore,
    CandidateBusinessObjectStore,
    DomainPackStore,
    persist_candidate_knowledge_batch,
)
from formowl_graph.storage import records as storage_records


CREATED_AT = "2026-07-15T04:30:00+00:00"
FIXTURE_ROOT = _paths.ROOT / "tests" / "fixtures" / "candidate_knowledge"


class CandidateKnowledgePipelineTests(unittest.TestCase):
    def test_procurement_and_finance_share_one_source_neutral_pipeline(self) -> None:
        extractor = DeterministicCandidateKnowledgeExtractor()
        results = {}

        for domain in ("procurement", "finance"):
            fixture = _load_fixture(domain)
            observations = _observations(fixture)
            pack = DomainPackDefinition.from_dict(fixture["domain_pack"])
            first = extractor.extract(
                observations,
                extractor_run_id=f"run_candidate_knowledge_{domain}_v1",
                domain_pack=pack,
                created_at=CREATED_AT,
            )
            second = extractor.extract(
                observations,
                extractor_run_id=f"run_candidate_knowledge_{domain}_v1",
                domain_pack=pack,
                created_at="2026-07-16T04:30:00+00:00",
            )
            results[domain] = first

            self.assertEqual(
                {assertion.assertion_kind for assertion in first.candidate_assertions},
                set(ASSERTION_KIND_VALUES),
            )
            self.assertEqual(
                [
                    candidate.candidate_business_object_id
                    for candidate in first.candidate_business_objects
                ],
                [
                    candidate.candidate_business_object_id
                    for candidate in second.candidate_business_objects
                ],
            )
            self.assertEqual(
                [assertion.candidate_assertion_id for assertion in first.candidate_assertions],
                [assertion.candidate_assertion_id for assertion in second.candidate_assertions],
            )
            self.assertFalse(first.canonical_write_allowed)
            self.assertEqual(first.warnings, [])
            observation_by_id = {
                observation.observation_id: observation for observation in observations
            }
            for candidate in first.candidate_business_objects:
                with self.subTest(domain=domain, candidate=candidate.object_type):
                    self.assertIn(candidate.object_supertype, CORE_SUPERTYPE_IDS)
                    self.assertEqual(candidate.status, "pending_review")
                    self.assertTrue(candidate.requires_review)
                    self.assertEqual(candidate.metadata["domain_pack_id"], pack.pack_id)
                    self.assertEqual(
                        candidate.metadata["domain_pack_content_hash"],
                        pack.content_hash,
                    )
                    self.assertEqual(
                        candidate.metadata["ontology_revision_id"],
                        pack.ontology_revision_id,
                    )
                    self.assertFalse(candidate.metadata["canonical_write_allowed"])
            for assertion in first.candidate_assertions:
                with self.subTest(
                    domain=domain,
                    assertion=assertion.predicate,
                ):
                    self.assertEqual(assertion.domain_pack_id, pack.pack_id)
                    self.assertEqual(
                        assertion.domain_pack_content_hash,
                        pack.content_hash,
                    )
                    self.assertEqual(
                        assertion.ontology_revision_id,
                        pack.ontology_revision_id,
                    )
                    self.assertEqual(assertion.status, "pending_review")
                    self.assertTrue(assertion.requires_review)
                    self.assertFalse(assertion.metadata["canonical_write_allowed"])
                    self.assertTrue(
                        set(assertion.source_observation_ids).issubset(observation_by_id)
                    )
                    for span in assertion.evidence_spans:
                        source = observation_by_id[span["source_observation_id"]]
                        self.assertEqual(
                            assertion.permission_scope,
                            source.permission_scope,
                        )

        self.assertEqual(
            {
                observation.observation_type
                for observation in _observations(_load_fixture("procurement"))
            },
            {"domain_pack_definition", "email_body_segment"},
        )
        self.assertEqual(
            {
                observation.observation_type
                for observation in _observations(_load_fixture("finance"))
            },
            {"domain_pack_definition", "erp_transaction_row", "approval_event"},
        )
        self.assertEqual(
            len(results["procurement"].candidate_assertions),
            len(results["finance"].candidate_assertions),
        )

    def test_finance_assertions_preserve_cross_observation_lineage(self) -> None:
        fixture = _load_fixture("finance")
        result = _extract_fixture(fixture)
        by_predicate = {assertion.predicate: assertion for assertion in result.candidate_assertions}

        for predicate in ("payment_approval", "Request"):
            with self.subTest(predicate=predicate):
                assertion = by_predicate[predicate]
                self.assertEqual(
                    assertion.source_observation_ids,
                    [
                        "obs_finance_approval_event",
                        "obs_finance_invoice_row",
                    ],
                )
                self.assertEqual(
                    assertion.evidence_spans[0]["source_observation_id"],
                    "obs_finance_approval_event",
                )

    def test_business_object_ids_bind_pack_ontology_and_core_supertype(self) -> None:
        fixture = _load_fixture("procurement")
        baseline = _extract_fixture(fixture)
        baseline_ids = {
            candidate.object_type: candidate.candidate_business_object_id
            for candidate in baseline.candidate_business_objects
        }

        different_pack = _load_fixture("procurement")
        different_pack["domain_pack"]["pack_id"] = "domain_pack_procurement_v2"
        _sync_domain_pack_definition(different_pack)
        different_pack_ids = {
            candidate.object_type: candidate.candidate_business_object_id
            for candidate in _extract_fixture(different_pack).candidate_business_objects
        }
        self.assertEqual(set(different_pack_ids), set(baseline_ids))
        self.assertTrue(all(different_pack_ids[key] != baseline_ids[key] for key in baseline_ids))

        different_ontology = _load_fixture("procurement")
        different_ontology["domain_pack"]["ontology_revision_id"] = "ontology_rev_candidate_core_v2"
        _sync_domain_pack_definition(different_ontology)
        different_ontology_ids = {
            candidate.object_type: candidate.candidate_business_object_id
            for candidate in _extract_fixture(different_ontology).candidate_business_objects
        }
        self.assertTrue(
            all(different_ontology_ids[key] != baseline_ids[key] for key in baseline_ids)
        )

        different_supertype = _load_fixture("procurement")
        different_supertype["domain_pack"]["object_types"]["PurchaseOrderLine"] = "Agreement"
        _sync_domain_pack_definition(different_supertype)
        different_supertype_ids = {
            candidate.object_type: candidate.candidate_business_object_id
            for candidate in _extract_fixture(different_supertype).candidate_business_objects
        }
        self.assertNotEqual(
            different_supertype_ids["PurchaseOrderLine"],
            baseline_ids["PurchaseOrderLine"],
        )
        self.assertNotEqual(
            different_supertype_ids["Supplier"],
            baseline_ids["Supplier"],
        )

    def test_duplicate_business_object_ids_fail_before_candidate_writes(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-knowledge-duplicate-object-id")
        fixture = _load_fixture("procurement")
        objects = fixture["observations"][0]["payload"]["candidate_knowledge"]["business_objects"]
        duplicate = deepcopy(objects[0])
        duplicate["local_id"] = "duplicate_local_reference"
        objects.append(duplicate)

        with self.assertRaises(ContractValidationError):
            _extract_and_store_fixture(fixture, temp_dir)

        self.assertEqual(CandidateBusinessObjectStore(temp_dir).list(), [])
        self.assertEqual(CandidateAssertionStore(temp_dir).list(), [])
        self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])

    def test_duplicate_assertion_ids_fail_before_candidate_writes(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-knowledge-duplicate-assertion-id")
        fixture = _load_fixture("procurement")
        assertions = fixture["observations"][0]["payload"]["candidate_knowledge"]["assertions"]
        assertions.append(deepcopy(assertions[0]))

        with self.assertRaisesRegex(
            ContractValidationError,
            "candidate assertion ids must be unique per extraction",
        ):
            _extract_and_store_fixture(fixture, temp_dir)

        self.assertEqual(DomainPackStore(temp_dir).list(), [])
        self.assertEqual(CandidateBusinessObjectStore(temp_dir).list(), [])
        self.assertEqual(CandidateAssertionStore(temp_dir).list(), [])
        self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])

    def test_injected_extractor_duplicate_assertion_ids_fail_before_candidate_writes(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-knowledge-injected-duplicate-assertion-id")
        fixture = _load_fixture("procurement")
        baseline = _extract_fixture(fixture)
        extractor = mock.create_autospec(
            DeterministicCandidateKnowledgeExtractor,
            instance=True,
        )
        extractor.extract.return_value = CandidateKnowledgeExtractionResult(
            candidate_business_objects=list(baseline.candidate_business_objects),
            candidate_assertions=[
                *baseline.candidate_assertions,
                baseline.candidate_assertions[0],
            ],
        )

        domain_pack = fixture["domain_pack"]
        if not isinstance(domain_pack, dict):
            raise AssertionError("fixture domain pack must be an object")
        with self.assertRaisesRegex(
            ContractValidationError,
            "candidate assertion ids must be unique per extraction",
        ):
            extract_and_store_candidate_knowledge(
                observations=_observations(fixture),
                domain_pack_store=DomainPackStore(temp_dir),
                candidate_business_object_store=CandidateBusinessObjectStore(temp_dir),
                candidate_assertion_store=CandidateAssertionStore(temp_dir),
                extractor_run_id=f"run_{fixture['fixture_id']}",
                domain_pack=DomainPackDefinition.from_dict(domain_pack),
                created_at=CREATED_AT,
                extractor=extractor,
            )

        self.assertEqual(DomainPackStore(temp_dir).list(), [])
        self.assertEqual(CandidateBusinessObjectStore(temp_dir).list(), [])
        self.assertEqual(CandidateAssertionStore(temp_dir).list(), [])
        self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])

    def test_injected_extractor_cannot_bypass_domain_pack_provenance(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-knowledge-injected-missing-pack-provenance")
        complete_fixture = _load_fixture("procurement")
        baseline = _extract_fixture(complete_fixture)
        extractor = mock.create_autospec(
            DeterministicCandidateKnowledgeExtractor,
            instance=True,
        )
        extractor.extract.return_value = baseline
        incomplete_fixture = _load_fixture("procurement")
        incomplete_fixture["observations"] = [
            observation
            for observation in incomplete_fixture["observations"]
            if observation["observation_type"] != "domain_pack_definition"
        ]

        with self.assertRaisesRegex(
            ContractValidationError,
            "Domain Pack provenance observations must be present",
        ):
            _extract_and_store_fixture(
                incomplete_fixture,
                temp_dir,
                extractor=extractor,
            )

        extractor.extract.assert_not_called()
        self.assertEqual(DomainPackStore(temp_dir).list(), [])
        self.assertEqual(CandidateBusinessObjectStore(temp_dir).list(), [])
        self.assertEqual(CandidateAssertionStore(temp_dir).list(), [])
        self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])

    def test_injected_extractor_candidate_sources_must_be_in_input(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-knowledge-injected-missing-candidate-source")
        complete_fixture = _load_fixture("procurement")
        baseline = _extract_fixture(complete_fixture)
        extractor = mock.create_autospec(
            DeterministicCandidateKnowledgeExtractor,
            instance=True,
        )
        extractor.extract.return_value = baseline
        definition_only_fixture = _load_fixture("procurement")
        definition_only_fixture["observations"] = [
            observation
            for observation in definition_only_fixture["observations"]
            if observation["observation_type"] == "domain_pack_definition"
        ]

        with self.assertRaisesRegex(
            ContractValidationError,
            "source observations must be present in the extraction input",
        ):
            _extract_and_store_fixture(
                definition_only_fixture,
                temp_dir,
                extractor=extractor,
            )

        extractor.extract.assert_called_once()
        self.assertEqual(DomainPackStore(temp_dir).list(), [])
        self.assertEqual(CandidateBusinessObjectStore(temp_dir).list(), [])
        self.assertEqual(CandidateAssertionStore(temp_dir).list(), [])
        self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])

    def test_injected_extractor_cannot_forge_ids_or_review_state(self) -> None:
        fixture = _load_fixture("procurement")
        baseline = _extract_fixture(fixture)

        for case in _candidate_tamper_cases():
            with self.subTest(case=case):
                temp_dir = _paths.fresh_test_dir(f"candidate-knowledge-injected-tamper-{case}")
                extractor = mock.create_autospec(
                    DeterministicCandidateKnowledgeExtractor,
                    instance=True,
                )
                extractor.extract.return_value = _tamper_candidate_result(
                    baseline,
                    case,
                )

                with self.assertRaises(ContractValidationError):
                    _extract_and_store_fixture(
                        fixture,
                        temp_dir,
                        extractor=extractor,
                    )

                self.assertEqual(DomainPackStore(temp_dir).list(), [])
                self.assertEqual(CandidateBusinessObjectStore(temp_dir).list(), [])
                self.assertEqual(CandidateAssertionStore(temp_dir).list(), [])
                self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])

    def test_mismatched_domain_pack_provenance_observation_fails_before_writes(
        self,
    ) -> None:
        cases = ("wrong_type", "missing_definition", "different_definition")
        for case in cases:
            with self.subTest(case=case):
                temp_dir = _paths.fresh_test_dir(
                    f"candidate-knowledge-mismatched-pack-source-{case}"
                )
                fixture = _load_fixture("procurement")
                observation = _domain_pack_observation(fixture)
                if case == "wrong_type":
                    observation["observation_type"] = "email_body_segment"
                elif case == "missing_definition":
                    del observation["payload"]["domain_pack_definition"]
                else:
                    observation["payload"]["domain_pack_definition"]["domain"] = "unrelated"

                with self.assertRaises(ContractValidationError):
                    _extract_and_store_fixture(fixture, temp_dir)

                self.assertEqual(DomainPackStore(temp_dir).list(), [])
                self.assertEqual(CandidateBusinessObjectStore(temp_dir).list(), [])
                self.assertEqual(CandidateAssertionStore(temp_dir).list(), [])
                self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])

    def test_store_helper_persists_only_candidate_collections(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-knowledge-stores")
        fixture = _load_fixture("procurement")

        result = extract_and_store_candidate_knowledge(
            observations=_observations(fixture),
            domain_pack_store=DomainPackStore(temp_dir),
            candidate_business_object_store=CandidateBusinessObjectStore(temp_dir),
            candidate_assertion_store=CandidateAssertionStore(temp_dir),
            extractor_run_id="run_candidate_knowledge_procurement_v1",
            domain_pack=DomainPackDefinition.from_dict(fixture["domain_pack"]),
            created_at=CREATED_AT,
        )

        self.assertEqual(
            DomainPackStore(temp_dir).list(),
            [DomainPackDefinition.from_dict(fixture["domain_pack"])],
        )
        self.assertEqual(
            {
                candidate.candidate_business_object_id: candidate.to_dict()
                for candidate in CandidateBusinessObjectStore(temp_dir).list()
            },
            {
                candidate.candidate_business_object_id: candidate.to_dict()
                for candidate in result.candidate_business_objects
            },
        )
        self.assertEqual(
            {
                assertion.candidate_assertion_id: assertion.to_dict()
                for assertion in CandidateAssertionStore(temp_dir).list()
            },
            {
                assertion.candidate_assertion_id: assertion.to_dict()
                for assertion in result.candidate_assertions
            },
        )
        graph_root = temp_dir / "graph"
        self.assertEqual(
            {entry.name for entry in graph_root.iterdir()},
            {
                "candidate-assertions",
                "candidate-business-objects",
                "domain-packs",
            },
        )
        public_paths = [path.relative_to(temp_dir).as_posix() for path in temp_dir.rglob("*")]
        self.assertFalse(any("canonical" in path for path in public_paths))
        self.assertFalse(any("user-graph" in path for path in public_paths))
        self.assertFalse((temp_dir / "wiki").exists())
        self.assertFalse((temp_dir / "external").exists())

    def test_candidate_batch_rejects_records_from_a_different_domain_pack(self) -> None:
        fixture = _load_fixture("procurement")
        pack = DomainPackDefinition.from_dict(fixture["domain_pack"])
        result = _extract_fixture(fixture)

        for case in ("business_object", "assertion"):
            with self.subTest(case=case):
                temp_dir = _paths.fresh_test_dir(f"candidate-knowledge-pack-lineage-{case}")
                candidates = list(result.candidate_business_objects)
                assertions = list(result.candidate_assertions)
                if case == "business_object":
                    payload = candidates[0].to_dict()
                    payload["metadata"]["domain_pack_id"] = "domain_pack_other_v1"
                    candidates[0] = CandidateBusinessObject.from_dict(payload)
                else:
                    payload = assertions[0].to_dict()
                    payload["domain_pack_id"] = "domain_pack_other_v1"
                    assertions[0] = CandidateAssertion.from_dict(payload)

                with self.assertRaises(ContractValidationError):
                    persist_candidate_knowledge_batch(
                        domain_pack_store=DomainPackStore(temp_dir),
                        candidate_business_object_store=CandidateBusinessObjectStore(temp_dir),
                        candidate_assertion_store=CandidateAssertionStore(temp_dir),
                        domain_pack=pack,
                        observations=_observations(fixture),
                        extractor_run_id=f"run_{fixture['fixture_id']}",
                        candidate_business_objects=candidates,
                        candidate_assertions=assertions,
                    )

                self.assertEqual(DomainPackStore(temp_dir).list(), [])
                self.assertEqual(CandidateBusinessObjectStore(temp_dir).list(), [])
                self.assertEqual(CandidateAssertionStore(temp_dir).list(), [])

    def test_candidate_batch_rejects_duplicate_ids_before_any_write(self) -> None:
        fixture = _load_fixture("procurement")
        pack = DomainPackDefinition.from_dict(fixture["domain_pack"])
        result = _extract_fixture(fixture)

        for case in ("business_object", "assertion"):
            with self.subTest(case=case):
                temp_dir = _paths.fresh_test_dir(
                    f"candidate-knowledge-direct-batch-duplicate-{case}"
                )
                candidates = list(result.candidate_business_objects)
                assertions = list(result.candidate_assertions)
                if case == "business_object":
                    candidates.append(candidates[0])
                else:
                    assertions.append(assertions[0])

                with self.assertRaisesRegex(
                    ContractValidationError,
                    "candidate .* ids must be unique per extraction",
                ):
                    persist_candidate_knowledge_batch(
                        domain_pack_store=DomainPackStore(temp_dir),
                        candidate_business_object_store=CandidateBusinessObjectStore(temp_dir),
                        candidate_assertion_store=CandidateAssertionStore(temp_dir),
                        domain_pack=pack,
                        observations=_observations(fixture),
                        extractor_run_id=f"run_{fixture['fixture_id']}",
                        candidate_business_objects=candidates,
                        candidate_assertions=assertions,
                    )

                self.assertEqual(DomainPackStore(temp_dir).list(), [])
                self.assertEqual(CandidateBusinessObjectStore(temp_dir).list(), [])
                self.assertEqual(CandidateAssertionStore(temp_dir).list(), [])
                self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])

    def test_direct_candidate_batch_requires_provenance_and_candidate_sources(
        self,
    ) -> None:
        fixture = _load_fixture("procurement")
        pack = DomainPackDefinition.from_dict(fixture["domain_pack"])
        result = _extract_fixture(fixture)
        cases = {
            "missing_pack_provenance": (
                [
                    observation
                    for observation in _observations(fixture)
                    if observation.observation_type != "domain_pack_definition"
                ],
                "Domain Pack provenance observations must be present",
            ),
            "missing_candidate_sources": (
                [
                    observation
                    for observation in _observations(fixture)
                    if observation.observation_type == "domain_pack_definition"
                ],
                "source observations must be present in the extraction input",
            ),
        }

        for case, (observations, expected_error) in cases.items():
            with self.subTest(case=case):
                temp_dir = _paths.fresh_test_dir(f"candidate-knowledge-direct-batch-{case}")
                with self.assertRaisesRegex(
                    ContractValidationError,
                    expected_error,
                ):
                    persist_candidate_knowledge_batch(
                        domain_pack_store=DomainPackStore(temp_dir),
                        candidate_business_object_store=CandidateBusinessObjectStore(temp_dir),
                        candidate_assertion_store=CandidateAssertionStore(temp_dir),
                        domain_pack=pack,
                        observations=observations,
                        extractor_run_id=f"run_{fixture['fixture_id']}",
                        candidate_business_objects=list(result.candidate_business_objects),
                        candidate_assertions=list(result.candidate_assertions),
                    )

                self.assertEqual(DomainPackStore(temp_dir).list(), [])
                self.assertEqual(CandidateBusinessObjectStore(temp_dir).list(), [])
                self.assertEqual(CandidateAssertionStore(temp_dir).list(), [])
                self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])

    def test_direct_candidate_batch_binds_participant_scope_and_source_lineage(
        self,
    ) -> None:
        fixture = _load_fixture("procurement")
        pack = DomainPackDefinition.from_dict(fixture["domain_pack"])
        baseline = _extract_fixture(fixture)
        source_observation = next(
            observation
            for observation in _observations(fixture)
            if observation.observation_type != "domain_pack_definition"
        )
        subject = next(
            candidate
            for candidate in baseline.candidate_business_objects
            if candidate.object_type == "PurchaseOrderLine"
        )
        original_participant = next(
            candidate
            for candidate in baseline.candidate_business_objects
            if candidate.object_type == "Supplier"
        )
        original_assertion = next(
            assertion
            for assertion in baseline.candidate_assertions
            if assertion.predicate == "supplied_by"
        )
        cases = {
            "permission_scope": (
                {
                    "scope_type": "private_user",
                    "scope_id": "procurement_owner",
                    "visibility": "restricted",
                },
                "participant permission scope",
            ),
            "source_lineage": (
                deepcopy(source_observation.to_dict()["permission_scope"]),
                "include every participant source observation",
            ),
        }

        for case, (participant_scope, expected_error) in cases.items():
            with self.subTest(case=case):
                temp_dir = _paths.fresh_test_dir(f"candidate-knowledge-participant-lineage-{case}")
                participant_observation_payload = source_observation.to_dict()
                participant_observation_payload["observation_id"] = (
                    f"obs_procurement_supplier_{case}"
                )
                participant_observation_payload["permission_scope"] = participant_scope
                participant_observation = Observation.from_dict(participant_observation_payload)

                participant_payload = original_participant.to_dict()
                participant_payload["source_observation_ids"] = [
                    participant_observation.observation_id
                ]
                participant_payload["access_boundary"]["permission_scope"] = deepcopy(
                    participant_observation.to_dict()["permission_scope"]
                )
                participant = _rebind_candidate_business_object_id(participant_payload)

                assertion_payload = original_assertion.to_dict()
                assertion_payload["object_candidate_business_object_id"] = (
                    participant.candidate_business_object_id
                )
                assertion = _rebind_candidate_assertion_id(assertion_payload)

                with self.assertRaisesRegex(ContractValidationError, expected_error):
                    persist_candidate_knowledge_batch(
                        domain_pack_store=DomainPackStore(temp_dir),
                        candidate_business_object_store=CandidateBusinessObjectStore(temp_dir),
                        candidate_assertion_store=CandidateAssertionStore(temp_dir),
                        domain_pack=pack,
                        observations=[
                            *_observations(fixture),
                            participant_observation,
                        ],
                        extractor_run_id=f"run_{fixture['fixture_id']}",
                        candidate_business_objects=[subject, participant],
                        candidate_assertions=[assertion],
                    )

                self.assertEqual(DomainPackStore(temp_dir).list(), [])
                self.assertEqual(CandidateBusinessObjectStore(temp_dir).list(), [])
                self.assertEqual(CandidateAssertionStore(temp_dir).list(), [])
                self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])

    def test_direct_candidate_batch_recomputes_ids_and_enforces_review_state(
        self,
    ) -> None:
        fixture = _load_fixture("procurement")
        pack = DomainPackDefinition.from_dict(fixture["domain_pack"])
        baseline = _extract_fixture(fixture)

        for case in _candidate_tamper_cases():
            with self.subTest(case=case):
                temp_dir = _paths.fresh_test_dir(f"candidate-knowledge-direct-batch-tamper-{case}")
                tampered = _tamper_candidate_result(baseline, case)

                with self.assertRaises(ContractValidationError):
                    persist_candidate_knowledge_batch(
                        domain_pack_store=DomainPackStore(temp_dir),
                        candidate_business_object_store=CandidateBusinessObjectStore(temp_dir),
                        candidate_assertion_store=CandidateAssertionStore(temp_dir),
                        domain_pack=pack,
                        observations=_observations(fixture),
                        extractor_run_id=f"run_{fixture['fixture_id']}",
                        candidate_business_objects=tampered.candidate_business_objects,
                        candidate_assertions=tampered.candidate_assertions,
                    )

                self.assertEqual(DomainPackStore(temp_dir).list(), [])
                self.assertEqual(CandidateBusinessObjectStore(temp_dir).list(), [])
                self.assertEqual(CandidateAssertionStore(temp_dir).list(), [])
                self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])

    def test_domain_pack_store_rejects_same_id_with_different_content(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-knowledge-pack-overwrite")
        fixture = _load_fixture("procurement")
        original = DomainPackDefinition.from_dict(fixture["domain_pack"])
        changed_payload = original.to_unhashed_dict()
        changed_payload["aliases"]["PurchaseOrderLine"].append("purchase line")
        changed = DomainPackDefinition.from_dict(changed_payload)
        store = DomainPackStore(temp_dir)

        store.create(original)
        with self.assertRaises(ContractValidationError):
            store.create(changed)

        self.assertEqual(store.get(original.pack_id), original)

    def test_candidate_stores_reject_same_id_with_different_content(self) -> None:
        fixture = _load_fixture("procurement")
        baseline = _extract_fixture(fixture)
        cases = {
            "business_object": (
                CandidateBusinessObjectStore,
                baseline.candidate_business_objects[0],
                "candidate_business_object_id",
                {"label": "Changed label with stale id"},
            ),
            "assertion": (
                CandidateAssertionStore,
                baseline.candidate_assertions[0],
                "candidate_assertion_id",
                {"value": "changed value with stale id"},
            ),
        }

        for case, (store_type, original, id_field, changes) in cases.items():
            with self.subTest(case=case):
                temp_dir = _paths.fresh_test_dir(f"candidate-knowledge-store-overwrite-{case}")
                payload = original.to_dict()
                payload.update(changes)
                changed = type(original).from_dict(payload)
                store = store_type(temp_dir)

                store.create(original)
                with self.assertRaisesRegex(
                    ContractValidationError,
                    "already exists with different",
                ):
                    store.create(changed)

                self.assertEqual(
                    store.get(getattr(original, id_field)),
                    original,
                )

    def test_cross_permission_references_fail_closed_before_candidate_writes(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-knowledge-permission")
        fixture = _load_fixture("finance")
        fixture["observations"][1]["permission_scope"] = {
            "scope_type": "private_user",
            "scope_id": "finance_controller",
            "visibility": "restricted",
        }

        with self.assertRaises(ContractValidationError):
            _extract_and_store_fixture(fixture, temp_dir)

        self.assertEqual(CandidateBusinessObjectStore(temp_dir).list(), [])
        self.assertEqual(CandidateAssertionStore(temp_dir).list(), [])
        self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])

    def test_missing_domain_pack_provenance_observation_fails_before_writes(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-knowledge-missing-pack-source")
        fixture = _load_fixture("procurement")
        fixture["observations"] = [
            observation
            for observation in fixture["observations"]
            if observation["observation_id"] != "obs_domain_pack_procurement_v1"
        ]

        with self.assertRaises(ContractValidationError):
            _extract_and_store_fixture(fixture, temp_dir)

        self.assertEqual(DomainPackStore(temp_dir).list(), [])
        self.assertEqual(CandidateBusinessObjectStore(temp_dir).list(), [])
        self.assertEqual(CandidateAssertionStore(temp_dir).list(), [])
        self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])

    def test_invalid_late_assertion_does_not_persist_earlier_candidates(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-knowledge-invalid-late")
        fixture = _load_fixture("procurement")
        fixture["observations"][0]["payload"]["candidate_knowledge"]["assertions"].append(
            {
                "assertion_type": "unmapped_department_fact",
                "subject": "po_line_450001_10",
                "value": "must_not_persist",
            }
        )

        with self.assertRaises(ContractValidationError):
            _extract_and_store_fixture(fixture, temp_dir)

        self.assertEqual(CandidateBusinessObjectStore(temp_dir).list(), [])
        self.assertEqual(CandidateAssertionStore(temp_dir).list(), [])
        self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])

    def test_candidate_batch_rolls_back_when_assertion_write_fails(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-knowledge-write-rollback")
        fixture = _load_fixture("procurement")
        original_write_json = storage_records._write_json
        assertion_write_count = 0

        def fail_on_second_assertion(path, payload):
            nonlocal assertion_write_count
            if path.parent.name == "candidate-assertions":
                assertion_write_count += 1
                if assertion_write_count == 2:
                    path.with_suffix(f"{path.suffix}.tmp").write_text(
                        json.dumps(payload),
                        encoding="utf-8",
                    )
                    raise OSError("simulated candidate assertion write failure")
            original_write_json(path, payload)

        with mock.patch.object(
            storage_records,
            "_write_json",
            side_effect=fail_on_second_assertion,
        ):
            with self.assertRaises(OSError):
                _extract_and_store_fixture(fixture, temp_dir)

        self.assertEqual(CandidateBusinessObjectStore(temp_dir).list(), [])
        self.assertEqual(CandidateAssertionStore(temp_dir).list(), [])
        self.assertEqual(DomainPackStore(temp_dir).list(), [])
        self.assertEqual(
            [path for path in (temp_dir / "graph").rglob("*") if path.is_file()],
            [],
        )

    def test_raw_or_internal_values_fail_before_candidate_writes(self) -> None:
        unsafe_values = (
            "/tmp/private/procurement.xlsx",
            "s3://private-bucket/procurement.xlsx",
            "object://private/procurement.xlsx",
            "minio://private/procurement.xlsx",
            "formowl://object/private/procurement.xlsx",
            "truncate table candidate_assertions",
        )
        for index, unsafe_value in enumerate(unsafe_values):
            with self.subTest(unsafe_value=unsafe_value):
                temp_dir = _paths.fresh_test_dir(f"candidate-knowledge-raw-value-{index}")
                fixture = _load_fixture("procurement")
                fixture["observations"][0]["payload"]["candidate_knowledge"]["assertions"][0][
                    "value"
                ] = unsafe_value

                with self.assertRaises(ContractValidationError):
                    _extract_and_store_fixture(fixture, temp_dir)

                self.assertEqual(
                    CandidateBusinessObjectStore(temp_dir).list(),
                    [],
                )
                self.assertEqual(CandidateAssertionStore(temp_dir).list(), [])
                self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])

    def test_internal_business_object_values_fail_before_candidate_writes(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-knowledge-raw-object")
        fixture = _load_fixture("finance")
        fixture["observations"][0]["payload"]["candidate_knowledge"]["business_objects"][0][
            "properties"
        ]["source"] = "s3://private-bucket/invoice.csv"

        with self.assertRaises(ContractValidationError):
            _extract_and_store_fixture(fixture, temp_dir)

        self.assertEqual(CandidateBusinessObjectStore(temp_dir).list(), [])
        self.assertEqual(CandidateAssertionStore(temp_dir).list(), [])
        self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])

    def test_direct_business_object_contract_rejects_backend_locators(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-knowledge-direct-raw-object")
        baseline = _extract_fixture(_load_fixture("finance"))
        payload = baseline.candidate_business_objects[0].to_dict()
        payload["properties"]["source"] = "s3://private-bucket/invoice.csv"

        with self.assertRaises(ContractValidationError):
            _rebind_candidate_business_object_id(payload)

        self.assertEqual(CandidateBusinessObjectStore(temp_dir).list(), [])
        self.assertEqual(CandidateAssertionStore(temp_dir).list(), [])
        self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])

    def test_unknown_domain_object_type_fails_before_candidate_writes(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-knowledge-unknown-object")
        fixture = _load_fixture("finance")
        fixture["observations"][0]["payload"]["candidate_knowledge"]["business_objects"][0][
            "object_type"
        ] = "DepartmentSpecificInvoice"

        with self.assertRaises(ContractValidationError):
            _extract_and_store_fixture(fixture, temp_dir)

        self.assertEqual(CandidateBusinessObjectStore(temp_dir).list(), [])
        self.assertEqual(CandidateAssertionStore(temp_dir).list(), [])
        self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])


def _load_fixture(domain: str) -> dict[str, object]:
    path = FIXTURE_ROOT / f"{domain}.json"
    return deepcopy(json.loads(path.read_text(encoding="utf-8")))


def _observations(fixture: dict[str, object]) -> list[Observation]:
    raw_observations = fixture["observations"]
    if not isinstance(raw_observations, list):
        raise AssertionError("fixture observations must be a list")
    return [Observation.from_dict(observation) for observation in raw_observations]


def _domain_pack_observation(fixture: dict[str, object]) -> dict[str, object]:
    observations = fixture["observations"]
    if not isinstance(observations, list):
        raise AssertionError("fixture observations must be a list")
    for observation in observations:
        if (
            isinstance(observation, dict)
            and observation.get("observation_type") == "domain_pack_definition"
        ):
            return observation
    raise AssertionError("fixture must include a domain_pack_definition observation")


def _sync_domain_pack_definition(fixture: dict[str, object]) -> None:
    domain_pack = fixture["domain_pack"]
    if not isinstance(domain_pack, dict):
        raise AssertionError("fixture domain pack must be an object")
    observation = _domain_pack_observation(fixture)
    payload = observation.get("payload")
    if not isinstance(payload, dict):
        raise AssertionError("domain pack observation payload must be an object")
    payload["domain_pack_definition"] = deepcopy(domain_pack)


def _extract_fixture(
    fixture: dict[str, object],
):
    domain_pack = fixture["domain_pack"]
    if not isinstance(domain_pack, dict):
        raise AssertionError("fixture domain pack must be an object")
    return DeterministicCandidateKnowledgeExtractor().extract(
        _observations(fixture),
        extractor_run_id=f"run_{fixture['fixture_id']}",
        domain_pack=DomainPackDefinition.from_dict(domain_pack),
        created_at=CREATED_AT,
    )


def _extract_and_store_fixture(
    fixture: dict[str, object],
    temp_dir: Path,
    *,
    extractor: DeterministicCandidateKnowledgeExtractor | None = None,
):
    domain_pack = fixture["domain_pack"]
    if not isinstance(domain_pack, dict):
        raise AssertionError("fixture domain pack must be an object")
    return extract_and_store_candidate_knowledge(
        observations=_observations(fixture),
        domain_pack_store=DomainPackStore(temp_dir),
        candidate_business_object_store=CandidateBusinessObjectStore(temp_dir),
        candidate_assertion_store=CandidateAssertionStore(temp_dir),
        extractor_run_id=f"run_{fixture['fixture_id']}",
        domain_pack=DomainPackDefinition.from_dict(domain_pack),
        created_at=CREATED_AT,
        extractor=extractor,
    )


def _candidate_tamper_cases() -> tuple[str, ...]:
    return (
        "business_object_id",
        "assertion_id",
        "business_object_review_state",
        "business_object_canonical_write",
        "assertion_review_state",
        "business_object_extractor_run",
        "assertion_extractor_run",
        "assertion_captured_at",
    )


def _tamper_candidate_result(
    baseline: CandidateKnowledgeExtractionResult,
    case: str,
) -> CandidateKnowledgeExtractionResult:
    candidates = list(baseline.candidate_business_objects)
    assertions = list(baseline.candidate_assertions)
    if case.startswith("business_object_"):
        payload = candidates[0].to_dict()
        if case == "business_object_id":
            payload["candidate_business_object_id"] = "cbobj_unbound_injected"
        elif case == "business_object_review_state":
            payload["status"] = "approved"
            payload["requires_review"] = False
        elif case == "business_object_canonical_write":
            payload["metadata"]["canonical_write_allowed"] = True
        elif case == "business_object_extractor_run":
            payload["extractor_run_id"] = "run_unbound_injected"
        else:
            raise AssertionError(f"unsupported business-object tamper case: {case}")
        candidates[0] = CandidateBusinessObject.from_dict(payload)
    else:
        payload = assertions[0].to_dict()
        if case == "assertion_id":
            payload["candidate_assertion_id"] = "cassert_unbound_injected"
        elif case == "assertion_review_state":
            payload["status"] = "approved"
            payload["requires_review"] = False
        elif case == "assertion_extractor_run":
            payload["extractor_run_id"] = "run_unbound_injected"
        elif case == "assertion_captured_at":
            payload["temporal_context"]["captured_at"] = "2026-07-14T00:00:00+00:00"
            assertions[0] = _rebind_candidate_assertion_id(payload)
            return CandidateKnowledgeExtractionResult(
                candidate_business_objects=candidates,
                candidate_assertions=assertions,
                warnings=list(baseline.warnings),
            )
        else:
            raise AssertionError(f"unsupported assertion tamper case: {case}")
        assertions[0] = CandidateAssertion.from_dict(payload)
    return CandidateKnowledgeExtractionResult(
        candidate_business_objects=candidates,
        candidate_assertions=assertions,
        warnings=list(baseline.warnings),
    )


def _rebind_candidate_business_object_id(
    payload: dict[str, object],
) -> CandidateBusinessObject:
    payload["candidate_business_object_id"] = stable_candidate_business_object_id(
        source_observation_ids=payload["source_observation_ids"],
        object_type=payload["object_type"],
        label=payload["label"],
        properties=payload["properties"],
        extractor_run_id=payload["extractor_run_id"],
        object_supertype=payload["object_supertype"],
        ontology_revision_id=payload["metadata"]["ontology_revision_id"],
        domain_pack_id=payload["metadata"]["domain_pack_id"],
        domain_pack_content_hash=payload["metadata"]["domain_pack_content_hash"],
    )
    return CandidateBusinessObject.from_dict(payload)


def _rebind_candidate_assertion_id(
    payload: dict[str, object],
) -> CandidateAssertion:
    payload["candidate_assertion_id"] = stable_candidate_assertion_id(
        source_observation_ids=payload["source_observation_ids"],
        assertion_kind=payload["assertion_kind"],
        subject_candidate_business_object_id=payload["subject_candidate_business_object_id"],
        predicate=payload["predicate"],
        object_candidate_business_object_id=payload.get("object_candidate_business_object_id"),
        actor_candidate_business_object_id=payload.get("actor_candidate_business_object_id"),
        counterparty_candidate_business_object_id=payload.get(
            "counterparty_candidate_business_object_id"
        ),
        value=payload.get("value"),
        previous_value=payload.get("previous_value"),
        proposed_value=payload.get("proposed_value"),
        temporal_context=payload.get("temporal_context"),
        context=payload.get("context"),
        extractor_run_id=payload["extractor_run_id"],
        ontology_revision_id=payload["ontology_revision_id"],
        domain_pack_id=payload["domain_pack_id"],
        domain_pack_content_hash=payload["domain_pack_content_hash"],
        epistemic_status=payload.get("epistemic_status", "asserted"),
        lifecycle_status=payload.get("lifecycle_status", "active"),
    )
    return CandidateAssertion.from_dict(payload)


if __name__ == "__main__":
    unittest.main()
