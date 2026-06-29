from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_contract import (
    CORE_SUPERTYPE_IDS,
    ContractValidationError,
    TypeAlias,
    TypeAlignmentCandidate,
    TypeDefinition,
    TypeMapping,
    stable_type_alias_id,
    stable_type_definition_id,
    stable_type_mapping_id,
)
from formowl_graph import core_supertypes_compatible, propose_type_alignment_candidate


class OntologyContractTests(unittest.TestCase):
    def test_type_definitions_keep_core_extension_and_promoted_tiers_separate(self) -> None:
        core = _core_type("Organization")
        extension = _extension_type("Customer", "workspace", "workspace_alpha")
        promoted = _promoted_type("Client", "workspace", "workspace_beta")

        self.assertIn(core.core_supertype_id, CORE_SUPERTYPE_IDS)
        self.assertEqual(core.scope_type, "core")
        self.assertEqual(extension.scope_id, "workspace_alpha")
        self.assertEqual(promoted.scope_id, "workspace_beta")
        self.assertNotEqual(core.type_id, extension.type_id)
        self.assertNotEqual(extension.type_id, promoted.type_id)

        for type_definition in (core, extension, promoted):
            with self.subTest(type_definition=type_definition.pref_label):
                data = type_definition.to_dict()
                self.assertEqual(TypeDefinition.from_dict(data).to_dict(), data)

    def test_type_alias_mapping_and_alignment_candidate_round_trip(self) -> None:
        source = _extension_type("Customer", "workspace", "workspace_alpha")
        target = _promoted_type("Client", "workspace", "workspace_beta")
        alias = TypeAlias.from_dict(
            {
                "alias_id": stable_type_alias_id(
                    type_id=source.type_id,
                    alias_label="Account",
                    scope_type=source.scope_type,
                    scope_id=source.scope_id,
                    ontology_revision_id=source.ontology_revision_id,
                ),
                "type_id": source.type_id,
                "alias_label": "Account",
                "scope_type": source.scope_type,
                "scope_id": source.scope_id,
                "status": "candidate",
                "ontology_revision_id": source.ontology_revision_id,
                "confidence": 0.73,
                "created_at": "2026-06-27T00:00:00+00:00",
                "created_by": "user_reviewer",
                "source_candidate_ids": ["catom_type_customer"],
            }
        )
        mapping = TypeMapping.from_dict(
            {
                "mapping_id": stable_type_mapping_id(
                    source_type_id=target.type_id,
                    target_core_supertype_id="Organization",
                    scope_type=target.scope_type,
                    scope_id=target.scope_id,
                    ontology_revision_id=target.ontology_revision_id,
                ),
                "source_type_id": target.type_id,
                "target_core_supertype_id": "Organization",
                "scope_type": target.scope_type,
                "scope_id": target.scope_id,
                "status": "active",
                "ontology_revision_id": target.ontology_revision_id,
                "confidence": 0.88,
                "created_at": "2026-06-27T00:00:00+00:00",
                "created_by": "user_reviewer",
                "source_candidate_ids": ["catom_type_client"],
                "review_event_id": "review_type_mapping_001",
            }
        )
        candidate = propose_type_alignment_candidate(
            source_type=source,
            target_type=target,
            ontology_revision_id="ontology_rev_alignment_001",
            score_breakdown={"lexical": 0.82, "embedding": 0.76},
            created_by="user_reviewer",
            created_at="2026-06-27T00:00:00+00:00",
        )

        self.assertEqual(TypeAlias.from_dict(alias.to_dict()).to_dict(), alias.to_dict())
        self.assertEqual(TypeMapping.from_dict(mapping.to_dict()).to_dict(), mapping.to_dict())
        self.assertEqual(
            TypeAlignmentCandidate.from_dict(candidate.to_dict()).to_dict(),
            candidate.to_dict(),
        )
        self.assertEqual(candidate.status, "pending_review")
        self.assertTrue(candidate.requires_review)
        self.assertFalse(candidate.canonical_type_write_allowed)
        self.assertIsNone(candidate.access_grant_id)

    def test_type_contracts_reject_malformed_scope_core_and_side_effects(self) -> None:
        extension = _extension_type("Customer", "workspace", "workspace_alpha")
        target = _promoted_type("Client", "workspace", "workspace_beta")
        valid_candidate = propose_type_alignment_candidate(
            source_type=extension,
            target_type=target,
            ontology_revision_id="ontology_rev_alignment_001",
            score_breakdown={"lexical": 0.82},
            created_by="user_reviewer",
            created_at="2026-06-27T00:00:00+00:00",
        ).to_dict()
        malformed_cases = [
            (
                _replace(
                    _extension_type("Customer", "workspace", "workspace_alpha"),
                    core_supertype_id="Customer",
                )
            ),
            (
                _replace(
                    _extension_type("Customer", "workspace", "workspace_alpha"), scope_type="core"
                )
            ),
            (
                _replace(
                    _extension_type("Customer", "workspace", "workspace_alpha"),
                    source_observation_ids=[],
                    source_candidate_ids=[],
                )
            ),
            (_replace(_core_type("Organization"), scope_id="workspace_alpha")),
            (
                {
                    **valid_candidate,
                    "canonical_type_write_allowed": True,
                }
            ),
            (
                {
                    **valid_candidate,
                    "access_grant_id": "grant_type_alignment",
                }
            ),
            (
                {
                    **valid_candidate,
                    "evidence_links": [{"summary": "/home/private/type-notes.md"}],
                }
            ),
            (
                {
                    **valid_candidate,
                    "score_breakdown": {"lexical": "0.82"},
                }
            ),
            (
                {
                    **valid_candidate,
                    "score_breakdown": {"lexical": True},
                }
            ),
            (
                {
                    **valid_candidate,
                    "score_breakdown": {"lexical": 1.1},
                }
            ),
            (
                {
                    **valid_candidate,
                    "score_breakdown": {"": 0.82},
                }
            ),
            (
                {
                    **valid_candidate,
                    "score_breakdown": {123: 0.82},
                }
            ),
        ]

        for payload in malformed_cases:
            with self.subTest(payload=payload):
                with self.assertRaises(ContractValidationError):
                    if payload.get("alignment_candidate_id"):
                        TypeAlignmentCandidate.from_dict(payload)
                    else:
                        TypeDefinition.from_dict(payload)

    def test_core_supertype_compatibility_is_the_only_hard_alignment_gate(self) -> None:
        same_core = core_supertypes_compatible("Organization", "Organization")
        parent_core = core_supertypes_compatible("Artifact", "Document")
        incompatible = core_supertypes_compatible("Person", "Document")

        self.assertTrue(same_core.compatible)
        self.assertEqual(same_core.reason, "same_core_supertype")
        self.assertTrue(parent_core.compatible)
        self.assertEqual(parent_core.reason, "core_supertype_ancestor_match")
        self.assertFalse(incompatible.compatible)
        self.assertEqual(incompatible.reason, "core_supertype_incompatible")

        with self.assertRaises(ContractValidationError):
            propose_type_alignment_candidate(
                source_type=_extension_type("Customer", "workspace", "workspace_alpha"),
                target_type=_extension_type(
                    "Kickoff Event",
                    "workspace",
                    "workspace_beta",
                    core_supertype_id="Event",
                ),
                ontology_revision_id="ontology_rev_alignment_001",
                score_breakdown={"lexical": 0.91},
                created_by="user_reviewer",
                created_at="2026-06-27T00:00:00+00:00",
            )


def _core_type(core_supertype_id: str) -> TypeDefinition:
    return TypeDefinition.from_dict(
        {
            "type_id": stable_type_definition_id(
                tier="core",
                core_supertype_id=core_supertype_id,
                pref_label=core_supertype_id,
                scope_type="core",
                scope_id="formowl_core",
                ontology_revision_id="ontology_rev_core_001",
            ),
            "tier": "core",
            "core_supertype_id": core_supertype_id,
            "pref_label": core_supertype_id,
            "scope_type": "core",
            "scope_id": "formowl_core",
            "status": "active",
            "ontology_revision_id": "ontology_rev_core_001",
            "confidence": 1.0,
            "created_at": "2026-06-27T00:00:00+00:00",
            "created_by": "system_spec",
        }
    )


def _extension_type(
    pref_label: str,
    scope_type: str,
    scope_id: str,
    *,
    core_supertype_id: str = "Organization",
) -> TypeDefinition:
    return TypeDefinition.from_dict(
        {
            "type_id": stable_type_definition_id(
                tier="extension",
                core_supertype_id=core_supertype_id,
                pref_label=pref_label,
                scope_type=scope_type,
                scope_id=scope_id,
                ontology_revision_id="ontology_rev_workspace_001",
            ),
            "tier": "extension",
            "core_supertype_id": core_supertype_id,
            "pref_label": pref_label,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "status": "candidate",
            "ontology_revision_id": "ontology_rev_workspace_001",
            "confidence": 0.74,
            "created_at": "2026-06-27T00:00:00+00:00",
            "created_by": "user_reviewer",
            "source_observation_ids": ["obs_type_label_customer"],
            "source_candidate_ids": ["catom_type_customer"],
            "alt_labels": ["Account"],
        }
    )


def _promoted_type(pref_label: str, scope_type: str, scope_id: str) -> TypeDefinition:
    return TypeDefinition.from_dict(
        {
            "type_id": stable_type_definition_id(
                tier="promoted",
                core_supertype_id="Organization",
                pref_label=pref_label,
                scope_type=scope_type,
                scope_id=scope_id,
                ontology_revision_id="ontology_rev_workspace_001",
            ),
            "tier": "promoted",
            "core_supertype_id": "Organization",
            "pref_label": pref_label,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "status": "active",
            "ontology_revision_id": "ontology_rev_workspace_001",
            "confidence": 0.9,
            "created_at": "2026-06-27T00:00:00+00:00",
            "created_by": "user_reviewer",
            "source_observation_ids": ["obs_type_label_client"],
            "source_candidate_ids": ["catom_type_client"],
        }
    )


def _replace(type_definition: TypeDefinition, **changes: object) -> dict[str, object]:
    data = type_definition.to_dict()
    data.update(changes)
    return data


if __name__ == "__main__":
    unittest.main()
