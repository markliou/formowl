from __future__ import annotations

from dataclasses import replace
import unittest

import _paths  # noqa: F401
from formowl_contract import (
    AtomGranularityPolicy,
    ContractValidationError,
    EntityResolutionPolicy,
    ExtractionPolicy,
    LifecyclePolicy,
    RelationResolutionPolicy,
    WikiProjectionPolicy,
    stable_policy_id,
)
from formowl_graph.policies import policy_version_ref, require_active_policy


class PolicyContractTests(unittest.TestCase):
    def test_policy_contracts_round_trip_and_keep_versioned_ids(self) -> None:
        policies = _valid_policy_contracts()

        for policy in policies:
            with self.subTest(policy=type(policy).__name__):
                data = policy.to_dict()
                self.assertEqual(type(policy).from_dict(data).to_dict(), data)
                self.assertTrue(data["policy_id"].startswith("policy_"))

        base_id = stable_policy_id(
            policy_kind="atom_granularity",
            policy_version="v1",
            scope_type="workspace",
            scope_id="workspace_formowl",
            rules={
                "merge_rules": {"b": 2, "a": 1},
                "split_rules": {"max_claims_per_atom": 1},
            },
        )
        same_id = stable_policy_id(
            policy_kind="atom_granularity",
            policy_version="v1",
            scope_type="workspace",
            scope_id="workspace_formowl",
            rules={
                "split_rules": {"max_claims_per_atom": 1},
                "merge_rules": {"a": 1, "b": 2},
            },
        )
        next_version_id = stable_policy_id(
            policy_kind="atom_granularity",
            policy_version="v2",
            scope_type="workspace",
            scope_id="workspace_formowl",
            rules={
                "merge_rules": {"b": 2, "a": 1},
                "split_rules": {"max_claims_per_atom": 1},
            },
        )

        self.assertEqual(base_id, same_id)
        self.assertNotEqual(base_id, next_version_id)

    def test_graph_policy_boundary_returns_refs_and_requires_active_kind(self) -> None:
        policy = _extraction_policy()
        ref = policy_version_ref(policy)

        self.assertEqual(
            ref,
            {
                "policy_id": policy.policy_id,
                "policy_kind": "extraction",
                "policy_version": "v1",
                "scope_type": "workspace",
                "scope_id": "workspace_formowl",
                "status": "active",
                "contract_hash": ref["contract_hash"],
            },
        )
        self.assertTrue(ref["contract_hash"].startswith("sha256:"))
        self.assertEqual(require_active_policy(policy, expected_kind="extraction"), ref)

        with self.assertRaises(ContractValidationError):
            require_active_policy(policy, expected_kind="lifecycle")
        with self.assertRaises(ContractValidationError):
            require_active_policy(
                replace(policy, status="draft"),
                expected_kind="extraction",
            )

    def test_policy_contracts_reject_malformed_ids_rules_and_raw_references(self) -> None:
        malformed_cases = [
            (ExtractionPolicy, _replace(_extraction_policy(), policy_id="/tmp/policy")),
            (ExtractionPolicy, _replace(_extraction_policy(), policy_version="")),
            (ExtractionPolicy, _replace(_extraction_policy(), routing_rules=["txt"])),
            (
                ExtractionPolicy,
                _replace(
                    _extraction_policy(),
                    routing_rules={"scratch_path": "/tmp/raw-assets"},
                ),
            ),
            (
                AtomGranularityPolicy,
                _replace(_atom_granularity_policy(), split_rules=[]),
            ),
            (
                AtomGranularityPolicy,
                _replace(_atom_granularity_policy(), status="pending_review"),
            ),
            (
                EntityResolutionPolicy,
                _replace(_entity_resolution_policy(), ontology_revision_id="ontology/rev"),
            ),
            (
                RelationResolutionPolicy,
                _replace(_relation_resolution_policy(), relation_rules=[]),
            ),
            (LifecyclePolicy, _replace(_lifecycle_policy(), created_at="not-a-timestamp")),
            (
                WikiProjectionPolicy,
                _replace(_wiki_projection_policy(), allowed_projection_kinds=[]),
            ),
            (
                WikiProjectionPolicy,
                _replace(_wiki_projection_policy(), redaction_rules={"sql": "select * from t"}),
            ),
        ]

        for policy_type, payload in malformed_cases:
            with self.subTest(policy_type=policy_type.__name__, payload=payload):
                with self.assertRaises(ContractValidationError):
                    policy_type.from_dict(payload)


def _replace(policy: object, **changes: object) -> dict[str, object]:
    data = policy.to_dict()  # type: ignore[attr-defined]
    data.update(changes)
    return data


def _valid_policy_contracts() -> list[object]:
    return [
        _extraction_policy(),
        _atom_granularity_policy(),
        _entity_resolution_policy(),
        _relation_resolution_policy(),
        _lifecycle_policy(),
        _wiki_projection_policy(),
    ]


def _policy_id(policy_kind: str, rules: dict[str, object], policy_version: str = "v1") -> str:
    return stable_policy_id(
        policy_kind=policy_kind,
        policy_version=policy_version,
        scope_type="workspace",
        scope_id="workspace_formowl",
        rules=rules,
    )


def _base_fields(policy_kind: str, rules: dict[str, object]) -> dict[str, object]:
    return {
        "policy_id": _policy_id(policy_kind, rules),
        "policy_version": "v1",
        "scope_type": "workspace",
        "scope_id": "workspace_formowl",
        "status": "active",
        "created_at": "2026-06-17T10:00:00+00:00",
        "created_by": "user_yifan",
        "description": f"{policy_kind} fixture policy",
    }


def _extraction_policy() -> ExtractionPolicy:
    rules = {
        "extractor_rules": {
            "allowed_mime_types": ["text/plain", "text/markdown"],
            "semantic_extraction": "separate_adapter",
        },
        "routing_rules": {"text/plain": ["plain_text_observation_extractor"]},
        "review_requirements": {"semantic_metadata": "human_review"},
    }
    return ExtractionPolicy.from_dict({**_base_fields("extraction", rules), **rules})


def _atom_granularity_policy() -> AtomGranularityPolicy:
    rules = {
        "split_rules": {"max_claims_per_atom": 1},
        "merge_rules": {"merge_when_always_displayed_together": True},
        "archive_rules": {"preserve_resolvable_old_ids": True},
        "usage_signal_window": {"days": 90},
        "review_requirements": {"split": "reviewer_required", "merge": "reviewer_required"},
    }
    return AtomGranularityPolicy.from_dict({**_base_fields("atom_granularity", rules), **rules})


def _entity_resolution_policy() -> EntityResolutionPolicy:
    rules = {
        "match_rules": {"exact_alias": True, "fuzzy_name": "candidate_only"},
        "threshold_rules": {"same_as_min": 0.86, "clerical_min": 0.70},
        "clerical_review_rules": {"private_pair_redaction": True},
        "review_requirements": {"cross_scope_merge": "explicit_review"},
    }
    return EntityResolutionPolicy.from_dict(
        {
            **_base_fields("entity_resolution", rules),
            **rules,
            "ontology_revision_id": "ontology_rev_001",
        }
    )


def _relation_resolution_policy() -> RelationResolutionPolicy:
    rules = {
        "relation_rules": {"type_compatibility": "core_supertype"},
        "conversion_rules": {"decision_relations_as_nodes": True},
        "contradiction_rules": {"defer_on_conflict": True},
        "review_requirements": {"low_confidence": "clerical_review"},
    }
    return RelationResolutionPolicy.from_dict(
        {
            **_base_fields("relation_resolution", rules),
            **rules,
            "ontology_revision_id": "ontology_rev_001",
        }
    )


def _lifecycle_policy() -> LifecyclePolicy:
    rules = {
        "lifecycle_rules": {"destructive_delete": False},
        "split_rules": {"relation": "split_into"},
        "merge_rules": {"relation": "merged_into"},
        "archive_rules": {"keep_resolvable": True},
        "supersede_rules": {"relation": "supersedes"},
        "equivalence_rules": {"relation": "equivalent_to"},
        "review_requirements": {"all_lifecycle_changes": "reviewer_required"},
    }
    return LifecyclePolicy.from_dict({**_base_fields("lifecycle", rules), **rules})


def _wiki_projection_policy() -> WikiProjectionPolicy:
    rules = {
        "section_rules": {"allowed_sources": ["entity_summary", "graph_query"]},
        "citation_rules": {"citations_required": True},
        "redaction_rules": {"private_notes": "exclude_by_default"},
        "review_requirements": {"publish": "proposal_only"},
    }
    return WikiProjectionPolicy.from_dict(
        {
            **_base_fields("wiki_projection", rules),
            **rules,
            "allowed_projection_kinds": ["adr", "project_hub"],
        }
    )


if __name__ == "__main__":
    unittest.main()
