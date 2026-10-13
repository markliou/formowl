from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
import unittest

import _paths  # noqa: F401
from formowl_contract import (
    AdmissibleSemanticScope,
    PermissionFirstSemanticPlanner,
    SemanticPlanClarificationRequired,
    SemanticSchemaAliasMap,
    SemanticTaskSkeleton,
    sha256_json,
)

# The isolated dirty UAT worktree overlays diagnostic_mcp.py ahead of a base
# container package.  The base-only persistence module is not checked out in
# this source tree, so install a deliberately inert import stub only for these
# host contract tests.  No execution path or persisted record is exercised.
if importlib.util.find_spec("formowl_mail.persistence") is None:
    _persistence = ModuleType("formowl_mail.persistence")
    for _name in (
        "DIAGNOSTIC_STRUCTURAL_BASELINE_SCOPE_KIND",
        "DIAGNOSTIC_STRUCTURAL_BRIDGE_IMPLEMENTATION_VERSION",
        "DIAGNOSTIC_STRUCTURAL_BRIDGE_PRODUCER_TYPE",
        "DIAGNOSTIC_STRUCTURAL_SCOPE_POLICY_ID",
        "DIAGNOSTIC_STRUCTURAL_SCOPE_POLICY_VERSION",
    ):
        setattr(_persistence, _name, "test-only")
    for _name in (
        "DiagnosticStructuralAggregateManifest",
        "DiagnosticStructuralShardRecord",
        "FileDiagnosticStructuralShardStore",
    ):
        setattr(_persistence, _name, type(_name, (), {}))
    for _name in (
        "diagnostic_structural_baseline_parameters",
        "diagnostic_structural_implementation_fingerprint",
        "diagnostic_structural_scope_policy_fingerprint",
    ):
        setattr(_persistence, _name, lambda *args, **kwargs: {})
    sys.modules[_persistence.__name__] = _persistence

from formowl_mail import query as _query

if not hasattr(_query, "StructuredSetMatch"):
    _query.StructuredSetMatch = type("StructuredSetMatch", (), {})
if not hasattr(_query, "execute_authorized_structured_set"):
    _query.execute_authorized_structured_set = lambda *args, **kwargs: None

from formowl_mail.diagnostic_mcp import DiagnosticSemanticProfile


def _scope() -> AdmissibleSemanticScope:
    return AdmissibleSemanticScope(
        permission_admissible=True,
        source_admissible=True,
        version_admissible=True,
        context_admissible=True,
        time_admissible=True,
        status_admissible=True,
    )


def _aliases() -> SemanticSchemaAliasMap:
    return SemanticSchemaAliasMap(
        object_aliases={"synthetic record": ("synthetic record",)},
        predicate_aliases={
            "synthetic property": ("synthetic property",),
            "lifecycle state": ("lifecycle state",),
        },
        value_aliases={
            "lifecycle state": {
                "ready": ("ready",),
            },
        },
        value_domains={
            "synthetic property": "open_public_value",
            "lifecycle state": "closed_enum",
        },
    )


def _profile(aliases: SemanticSchemaAliasMap) -> DiagnosticSemanticProfile:
    fingerprint = DiagnosticSemanticProfile.fingerprint_for(
        profile_id="diagnostic-synthetic",
        profile_version="1",
        schema_alias_map=aliases,
        workspace_id="workspace-synthetic",
        owner_user_id="owner-synthetic",
        actor_context_id="actor-synthetic",
        known_as_of="2026-08-12T00:00:00Z",
    )
    return DiagnosticSemanticProfile(
        profile_id="diagnostic-synthetic",
        profile_version="1",
        profile_fingerprint=fingerprint,
        schema_alias_map=aliases,
        workspace_id="workspace-synthetic",
        owner_user_id="owner-synthetic",
        actor_context_id="actor-synthetic",
        known_as_of="2026-08-12T00:00:00Z",
    )


def _legacy_profile_payload(aliases: SemanticSchemaAliasMap) -> dict[str, object]:
    return {
        "profile_id": "diagnostic-synthetic",
        "profile_version": "0",
        "scope": {
            "workspace_id": "workspace-synthetic",
            "owner_user_id": "owner-synthetic",
            "actor_context_id": "actor-synthetic",
            "known_as_of": "2026-08-12T00:00:00Z",
        },
        "aliases": {
            "object_aliases": {key: list(forms) for key, forms in aliases.object_aliases.items()},
            "predicate_aliases": {
                key: list(forms) for key, forms in aliases.predicate_aliases.items()
            },
            "value_aliases": {
                predicate: {key: list(forms) for key, forms in values.items()}
                for predicate, values in aliases.value_aliases.items()
            },
        },
    }


class OpenPublicValueSemanticProfileTests(unittest.TestCase):
    def test_unenumerated_public_value_is_exact_normalized_runtime_filter(self) -> None:
        plan = PermissionFirstSemanticPlanner().ground_all_matching(
            skeleton=SemanticTaskSkeleton(
                query_class="attribute_filter",
                projection_slots=("projection",),
                constraint_slots=("object_type", "predicate", "value"),
            ),
            scope=_scope(),
            aliases=_aliases(),
            object_type="synthetic record",
            predicate="synthetic property",
            value="Synthetic  Reference  Delta",
            projection="synthetic property",
        )

        self.assertEqual(plan.value, "synthetic reference delta")
        self.assertEqual(plan.value_match_forms, ("synthetic reference delta",))

    def test_closed_enum_unknown_value_fails_closed(self) -> None:
        with self.assertRaises(SemanticPlanClarificationRequired):
            PermissionFirstSemanticPlanner().ground_all_matching(
                skeleton=SemanticTaskSkeleton(
                    query_class="attribute_filter",
                    projection_slots=("projection",),
                    constraint_slots=("object_type", "predicate", "value"),
                ),
                scope=_scope(),
                aliases=_aliases(),
                object_type="synthetic record",
                predicate="lifecycle state",
                value="unlisted state",
                projection="synthetic property",
            )

    def test_profile_round_trip_and_fingerprint_bind_value_domains(self) -> None:
        profile = _profile(_aliases())
        payload = profile.to_private_dict()

        self.assertEqual(
            sha256_json(profile.binding_fingerprint_payload),
            profile.profile_fingerprint,
        )
        self.assertEqual(
            payload["aliases"]["value_domains"],
            {
                "synthetic property": "open_public_value",
                "lifecycle state": "closed_enum",
            },
        )
        self.assertEqual(DiagnosticSemanticProfile.from_private_dict(payload), profile)

        changed_aliases = SemanticSchemaAliasMap(
            object_aliases={"synthetic record": ("synthetic record",)},
            predicate_aliases={
                "synthetic property": ("synthetic property",),
                "lifecycle state": ("lifecycle state",),
            },
            value_aliases={
                "synthetic property": {
                    "fixed reference": ("fixed reference",),
                },
                "lifecycle state": {
                    "ready": ("ready",),
                },
            },
            value_domains={
                "synthetic property": "closed_enum",
                "lifecycle state": "closed_enum",
            },
        )
        self.assertNotEqual(
            profile.profile_fingerprint,
            _profile(changed_aliases).profile_fingerprint,
        )

    def test_legacy_closed_profile_accepts_only_manually_computed_old_shape_hash(self) -> None:
        aliases = SemanticSchemaAliasMap(
            object_aliases={"synthetic record": ("synthetic record",)},
            predicate_aliases={
                "synthetic property": ("synthetic property",),
                "lifecycle state": ("lifecycle state",),
            },
            value_aliases={
                "synthetic property": {
                    "fixed reference": ("fixed reference",),
                },
                "lifecycle state": {
                    "ready": ("ready",),
                },
            },
        )
        legacy_payload = _legacy_profile_payload(aliases)
        legacy_payload["profile_fingerprint"] = sha256_json(legacy_payload)

        restored = DiagnosticSemanticProfile.from_private_dict(legacy_payload)

        self.assertEqual(
            sha256_json(restored.binding_fingerprint_payload),
            restored.profile_fingerprint,
        )
        self.assertEqual(
            restored.schema_alias_map.value_domain("synthetic property"), "closed_enum"
        )
        self.assertEqual(restored.profile_fingerprint, legacy_payload["profile_fingerprint"])
        migrated = restored.to_private_dict()
        self.assertIn("value_domains", migrated["aliases"])
        self.assertNotEqual(migrated["profile_fingerprint"], restored.profile_fingerprint)
        self.assertEqual(
            DiagnosticSemanticProfile.from_private_dict(migrated).to_private_dict(), migrated
        )

    def test_legacy_profile_rejects_new_shape_hash_without_domains(self) -> None:
        aliases = SemanticSchemaAliasMap(
            object_aliases={"synthetic record": ("synthetic record",)},
            predicate_aliases={
                "synthetic property": ("synthetic property",),
                "lifecycle state": ("lifecycle state",),
            },
            value_aliases={
                "synthetic property": {
                    "fixed reference": ("fixed reference",),
                },
                "lifecycle state": {
                    "ready": ("ready",),
                },
            },
        )
        payload = _legacy_profile_payload(aliases)
        current_hash = DiagnosticSemanticProfile.fingerprint_for(
            profile_id=payload["profile_id"],
            profile_version=payload["profile_version"],
            schema_alias_map=aliases,
            workspace_id=payload["scope"]["workspace_id"],
            owner_user_id=payload["scope"]["owner_user_id"],
            actor_context_id=payload["scope"]["actor_context_id"],
            known_as_of=payload["scope"]["known_as_of"],
        )
        payload["profile_fingerprint"] = current_hash

        with self.assertRaises(ValueError):
            DiagnosticSemanticProfile.from_private_dict(payload)

    def test_public_ontology_declares_open_policy_without_enumerated_open_values(self) -> None:
        ontology_path = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "recovery"
            / "2026-08-10"
            / "public-semantic-ontology-v1.json"
        )
        ontology = json.loads(ontology_path.read_text(encoding="utf-8"))

        self.assertEqual(ontology["value_domains"]["coo"], "open_public_value")
        self.assertTrue(
            all(
                predicate not in ontology["value_aliases"]
                for predicate, domain in ontology["value_domains"].items()
                if domain == "open_public_value"
            )
        )


if __name__ == "__main__":
    unittest.main()
