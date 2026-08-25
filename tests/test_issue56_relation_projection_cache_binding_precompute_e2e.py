from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, sha256_json
from formowl_mail import build_authorized_semantic_mail_session
from formowl_mail import hybrid as hybrid_module
from scripts.issue56_semantic_execution_smoke import (
    ALLOWED_RELATIONS,
    REQUESTER_USER_ID,
    WORKSPACE_ID,
    build_semantic_poc_inputs,
)
from test_issue56_node_backed_fallback_e2e import (
    _connected_off_path_support_fixture,
    _contract_only_runtime,
)


class Issue56RelationProjectionCacheBindingPrecomputeEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = _contract_only_runtime()

    def setUp(self) -> None:
        self.inputs = build_semantic_poc_inputs()
        with patch.object(
            hybrid_module,
            "_load_pinned_issue56_runtime_components",
            return_value=self.runtime,
        ):
            self.session = build_authorized_semantic_mail_session(
                observations_by_bundle_id=self.inputs.observations_by_bundle_id,
                bundles=self.inputs.bundles,
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=WORKSPACE_ID,
            )
        self.fixture = _connected_off_path_support_fixture(self.inputs.effective_graph_view)

    def test_precompute_builds_once_and_primed_queries_do_not_rescan_binding(
        self,
    ) -> None:
        real_scan = hybrid_module._relation_projection_candidate_binding_inputs
        real_builder = hybrid_module._build_relation_projection_base
        with (
            patch.object(
                hybrid_module,
                "_relation_projection_candidate_binding_inputs",
                wraps=real_scan,
            ) as binding_scan,
            patch.object(
                hybrid_module,
                "_build_relation_projection_base",
                wraps=real_builder,
            ) as build_base,
        ):
            first_precompute = hybrid_module.precompute_relation_projection_base(
                session=self.session,
                effective_graph_view=self.fixture.view,
            )
            repeated_precompute = hybrid_module.precompute_relation_projection_base(
                session=self.session,
                effective_graph_view=self.fixture.view,
            )
            first_result = self._query()
            second_result = self._query()

        self.assertEqual(binding_scan.call_count, 1)
        self.assertEqual(build_base.call_count, 1)
        self.assertEqual(repeated_precompute, first_precompute)
        self.assertEqual(first_result.to_safe_dict(), second_result.to_safe_dict())

    def test_cold_and_warm_results_are_identical_but_query_projections_are_not_shared(
        self,
    ) -> None:
        real_projection_builder = hybrid_module._build_relation_query_projection
        projections = []

        def record_projection(**kwargs):
            projection = real_projection_builder(**kwargs)
            projections.append(projection)
            return projection

        with patch.object(
            hybrid_module,
            "_build_relation_query_projection",
            side_effect=record_projection,
        ):
            cold = self._query()
            warm = self._query()

        self.assertEqual(cold.to_safe_dict(), warm.to_safe_dict())
        self.assertEqual(cold.status, warm.status)
        self.assertEqual(cold.plan_fingerprint, warm.plan_fingerprint)
        self.assertEqual(cold.result_fingerprint, warm.result_fingerprint)
        self.assertEqual(cold.graph_paths, warm.graph_paths)
        self.assertEqual(cold.scores, warm.scores)
        self.assertEqual(
            cold.answer_citation_hashes,
            warm.answer_citation_hashes,
        )
        self.assertEqual(len(projections), 2)
        self.assertIsNot(projections[0], projections[1])
        self.assertIsNot(projections[0].adjacency, projections[1].adjacency)

    def test_candidate_tuple_replacement_fails_closed(self) -> None:
        hybrid_module.precompute_relation_projection_base(
            session=self.session,
            effective_graph_view=self.fixture.view,
        )
        first_candidate = self.session.index.candidates[0]
        changed_candidate = replace(
            first_candidate,
            observation_tokens=(
                first_candidate.observation_tokens
                | frozenset({"synthetic_candidate_content_drift"})
            ),
        )
        changed_candidates = (
            changed_candidate,
            *self.session.index.candidates[1:],
        )
        changed_index = replace(
            self.session.index,
            candidates=changed_candidates,
            _integrity_fingerprint=hybrid_module._hybrid_index_integrity_fingerprint(
                index_fingerprint=self.session.index.index_fingerprint,
                tokenizer_id=self.session.index.tokenizer_id,
                profile_fingerprint=self.session.index.profile_fingerprint,
                execution_component_fingerprint=(
                    self.session.index.execution_component_fingerprint
                ),
                candidates=changed_candidates,
            ),
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "candidate content snapshot mismatch",
        ):
            hybrid_module.precompute_relation_projection_base(
                session=replace(self.session, index=changed_index),
                effective_graph_view=self.fixture.view,
            )

    def test_graph_index_requester_and_permission_drift_fail_closed(self) -> None:
        hybrid_module.precompute_relation_projection_base(
            session=self.session,
            effective_graph_view=self.fixture.view,
        )

        with self.subTest("graph content mutation"):
            with self.assertRaisesRegex(
                ContractValidationError,
                "effective graph snapshot is immutable",
            ):
                self.fixture.view.visible_nodes[0].properties["node_kind"] = "drifted"

        with self.subTest("permission mutation"):
            with self.assertRaisesRegex(
                ContractValidationError,
                "effective graph snapshot is immutable",
            ):
                self.fixture.view.visible_nodes[0].permission_scope["visibility"] = "drifted"

        with self.subTest("index fingerprint drift"):
            changed_index_fingerprint = sha256_json(
                {
                    "index_fingerprint": self.session.index.index_fingerprint,
                    "drift": True,
                }
            )
            with self.assertRaisesRegex(
                ContractValidationError,
                "mail evidence index binding mismatch",
            ):
                hybrid_module.precompute_relation_projection_base(
                    session=replace(
                        self.session,
                        index=replace(
                            self.session.index,
                            index_fingerprint=changed_index_fingerprint,
                        ),
                    ),
                    effective_graph_view=self.fixture.view,
                )

        with self.subTest("requester drift"):
            with self.assertRaisesRegex(
                ContractValidationError,
                "requester mismatch",
            ):
                hybrid_module.precompute_relation_projection_base(
                    session=self.session,
                    effective_graph_view=replace(
                        self.fixture.view,
                        requester_user_id="user_issue56_other",
                    ),
                )

    def _query(self):
        return self.session.query(
            query_text=self.fixture.query_text,
            effective_graph_view=self.fixture.view,
            allowed_relation_types=ALLOWED_RELATIONS,
            seed_node_ids=(self.fixture.anchor_node_id,),
        )


if __name__ == "__main__":
    unittest.main()
