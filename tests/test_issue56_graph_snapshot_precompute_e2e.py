from __future__ import annotations

from dataclasses import replace
import json
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, sha256_json
from formowl_mail import (
    EffectiveGraphContentSnapshotPrecompute,
    precompute_effective_graph_content_snapshot,
)
from formowl_mail import hybrid as hybrid_module
import test_issue56_source_neutral_hybrid_e2e as source_neutral_fixture


class Issue56GraphSnapshotPrecomputeEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = source_neutral_fixture.Issue56SourceNeutralHybridEndToEndTests(
            methodName="runTest"
        )
        cls.fixture.setUpClass()

    def setUp(self) -> None:
        self.session, graph_build = self.fixture._session_and_graph()
        self.expected_graph_revision_fingerprint = graph_build.graph_revision_fingerprint
        self.view = self._cold_clone(graph_build.effective_graph_view)
        self.expected_view_fingerprint = sha256_json(self.view.to_dict())

    def test_materializes_once_reuses_snapshot_and_keeps_relation_caches_cold(
        self,
    ) -> None:
        content_builder = hybrid_module._build_effective_graph_content_snapshot
        with (
            patch.object(
                hybrid_module,
                "_build_effective_graph_content_snapshot",
                wraps=content_builder,
            ) as build_content,
            patch.object(
                hybrid_module,
                "_relation_projection_base_cache_binding_snapshot",
            ) as build_binding,
            patch.object(
                hybrid_module,
                "_build_relation_projection_base",
            ) as build_base,
        ):
            first = self._precompute()
            first_snapshot = hybrid_module._require_effective_graph_content_snapshot(self.view)
            repeated = self._precompute()
            repeated_snapshot = hybrid_module._require_effective_graph_content_snapshot(self.view)

        self.assertIsInstance(first, EffectiveGraphContentSnapshotPrecompute)
        self.assertEqual(repeated, first)
        self.assertEqual(build_content.call_count, 1)
        self.assertIs(repeated_snapshot, first_snapshot)
        build_binding.assert_not_called()
        build_base.assert_not_called()
        self.assertEqual(
            len(first_snapshot.relation_projection_cache_binding_snapshots),
            0,
        )
        self.assertEqual(len(first_snapshot.relation_projection_bases), 0)
        self.assertEqual(first.relation_projection_cache_binding_entry_count, 0)
        self.assertEqual(first.relation_projection_base_entry_count, 0)

    def test_safe_metadata_is_hash_count_only_and_binds_complete_snapshot(
        self,
    ) -> None:
        precomputed = self._precompute()
        safe = precomputed.to_safe_dict()

        self.assertEqual(
            set(safe),
            {
                "artifact_id",
                "schema_version",
                "status",
                "snapshot_status",
                "graph_revision_fingerprint",
                "graph_content_fingerprint",
                "effective_graph_view_fingerprint",
                "source_session_binding_fingerprint",
                "source_access_fingerprint",
                "permission_lineage_fingerprint",
                "index_fingerprint",
                "candidate_admission_profile_fingerprint",
                "authorized_observation_set_fingerprint",
                "counts",
                "precompute_fingerprint",
            },
        )
        for field_name in (
            "graph_revision_fingerprint",
            "graph_content_fingerprint",
            "effective_graph_view_fingerprint",
            "source_session_binding_fingerprint",
            "source_access_fingerprint",
            "permission_lineage_fingerprint",
            "index_fingerprint",
            "candidate_admission_profile_fingerprint",
            "authorized_observation_set_fingerprint",
            "precompute_fingerprint",
        ):
            self.assertRegex(safe[field_name], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(
            safe["graph_revision_fingerprint"],
            self.expected_graph_revision_fingerprint,
        )
        self.assertEqual(
            safe["effective_graph_view_fingerprint"],
            self.expected_view_fingerprint,
        )
        self.assertEqual(
            safe["counts"],
            {
                "authorized_observation_count": len(self.session.authorized_observations),
                "source_scope_count": len(self.session.authorized_source_scope_ids),
                "node_count": len(self.view.visible_nodes),
                "edge_count": len(self.view.visible_edges),
                "access_required_count": len(self.view.access_required),
                "applied_grant_count": len(self.view.applied_grant_ids),
                "relation_projection_cache_binding_entry_count": 0,
                "relation_projection_base_entry_count": 0,
            },
        )
        rendered = json.dumps(safe, ensure_ascii=True, sort_keys=True)
        for private_value in (
            self.session.requester_user_id,
            self.session.workspace_id,
            self.session.authorized_observations[0].observation_id,
            self.session.authorized_observations[0].text,
            self.view.visible_nodes[0].node_id,
            "tenant_id",
        ):
            self.assertNotIn(private_value, rendered)

    def test_session_source_observation_permission_index_and_tokenizer_drift_fail_closed(
        self,
    ) -> None:
        cases = (
            (
                "requester",
                replace(
                    self.view,
                    requester_user_id="user_graph_snapshot_not_authorized",
                ),
                self.session,
                "requester mismatch",
            ),
            (
                "source_scope",
                self._cold_clone(self.view),
                replace(
                    self.session,
                    selected_source_scope_ids=("project_graph_snapshot_drift",),
                ),
                "source binding mismatch",
            ),
            (
                "observation",
                self._cold_clone(self.view),
                replace(
                    self.session,
                    authorized_observation_hashes=tuple(
                        (
                            observation_id,
                            sha256_json(["drift", observation_hash]),
                        )
                        for observation_id, observation_hash in (
                            self.session.authorized_observation_hashes
                        )
                    ),
                ),
                "Observation binding mismatch",
            ),
            (
                "permission",
                self._permission_drift_view(),
                self.session,
                "permission scope mismatch",
            ),
            (
                "index",
                self._cold_clone(self.view),
                replace(
                    self.session,
                    index=replace(
                        self.session.index,
                        _integrity_fingerprint=sha256_json("graph snapshot stale index integrity"),
                    ),
                ),
                "index binding mismatch",
            ),
            (
                "tokenizer",
                self._cold_clone(self.view),
                self._tokenizer_drift_session(),
                "tokenizer profile mismatch",
            ),
            (
                "session_binding",
                self._cold_clone(self.view),
                replace(
                    self.session,
                    source_session_binding_fingerprint=sha256_json(
                        "graph snapshot stale source session"
                    ),
                ),
                "session binding mismatch",
            ),
        )
        for label, view, session, error_pattern in cases:
            with (
                self.subTest(label=label),
                self.assertRaisesRegex(ContractValidationError, error_pattern),
            ):
                precompute_effective_graph_content_snapshot(
                    session=session,
                    effective_graph_view=view,
                    expected_graph_revision_fingerprint=(self.expected_graph_revision_fingerprint),
                    expected_effective_graph_view_fingerprint=sha256_json(view.to_dict()),
                )

    def test_expected_view_graph_and_cold_cache_bindings_fail_closed(self) -> None:
        with self.assertRaisesRegex(
            ContractValidationError,
            "effective graph binding mismatch",
        ):
            precompute_effective_graph_content_snapshot(
                session=self.session,
                effective_graph_view=self.view,
                expected_graph_revision_fingerprint=(self.expected_graph_revision_fingerprint),
                expected_effective_graph_view_fingerprint=sha256_json(
                    "different effective graph view"
                ),
            )

        graph_mismatch_view = self._cold_clone(self.view)
        with self.assertRaisesRegex(
            ContractValidationError,
            "graph revision binding mismatch",
        ):
            precompute_effective_graph_content_snapshot(
                session=self.session,
                effective_graph_view=graph_mismatch_view,
                expected_graph_revision_fingerprint=sha256_json("different graph revision"),
                expected_effective_graph_view_fingerprint=sha256_json(
                    graph_mismatch_view.to_dict()
                ),
            )
        mismatched_snapshot = hybrid_module._require_effective_graph_content_snapshot(
            graph_mismatch_view
        )
        self.assertFalse(mismatched_snapshot.relation_projection_cache_binding_snapshots)
        self.assertFalse(mismatched_snapshot.relation_projection_bases)

        self._precompute()
        snapshot = hybrid_module._require_effective_graph_content_snapshot(self.view)
        with snapshot.relation_projection_base_lock:
            snapshot.relation_projection_bases[sha256_json("unexpected")] = object()
        with self.assertRaisesRegex(
            ContractValidationError,
            "relation projection caches are not cold",
        ):
            self._precompute()

    def _precompute(self) -> EffectiveGraphContentSnapshotPrecompute:
        return precompute_effective_graph_content_snapshot(
            session=self.session,
            effective_graph_view=self.view,
            expected_graph_revision_fingerprint=(self.expected_graph_revision_fingerprint),
            expected_effective_graph_view_fingerprint=self.expected_view_fingerprint,
        )

    def _permission_drift_view(self):
        first_node = self.view.visible_nodes[0]
        changed_node = replace(
            first_node,
            permission_scope={
                **dict(first_node.permission_scope),
                "scope_id": "project_graph_snapshot_not_authorized",
            },
        )
        return replace(
            self.view,
            visible_nodes=[changed_node, *self.view.visible_nodes[1:]],
            visible_edges=list(self.view.visible_edges),
            access_required=list(self.view.access_required),
            applied_grant_ids=list(self.view.applied_grant_ids),
        )

    def _tokenizer_drift_session(self):
        changed_profile_fingerprint = sha256_json("graph snapshot changed tokenizer profile")
        changed_index = replace(
            self.session.index,
            profile_fingerprint=changed_profile_fingerprint,
            _integrity_fingerprint=hybrid_module._hybrid_index_integrity_fingerprint(
                index_fingerprint=self.session.index.index_fingerprint,
                tokenizer_id=self.session.index.tokenizer_id,
                profile_fingerprint=changed_profile_fingerprint,
                execution_component_fingerprint=(
                    self.session.index.execution_component_fingerprint
                ),
                candidates=self.session.index.candidates,
            ),
        )
        return replace(self.session, index=changed_index)

    @staticmethod
    def _cold_clone(view):
        return replace(
            view,
            visible_nodes=list(view.visible_nodes),
            visible_edges=list(view.visible_edges),
            access_required=list(view.access_required),
            applied_grant_ids=list(view.applied_grant_ids),
        )


if __name__ == "__main__":
    unittest.main()
