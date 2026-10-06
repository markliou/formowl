from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from formowl_contract import ContractValidationError
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


class Issue56GraphProjectionSnapshotLatencyEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inputs = build_semantic_poc_inputs()
        self.runtime = _contract_only_runtime()
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=self.runtime,
        ):
            self.session = build_authorized_semantic_mail_session(
                observations_by_bundle_id=self.inputs.observations_by_bundle_id,
                bundles=self.inputs.bundles,
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=WORKSPACE_ID,
            )

    def test_repeated_queries_reuse_only_the_immutable_query_independent_base(
        self,
    ) -> None:
        fixture = _connected_off_path_support_fixture(
            self.inputs.effective_graph_view,
        )
        content_builder = hybrid_module._build_effective_graph_content_snapshot
        base_builder = hybrid_module._build_relation_projection_base

        with (
            patch.object(
                hybrid_module,
                "_build_effective_graph_content_snapshot",
                wraps=content_builder,
            ) as build_content,
            patch.object(
                hybrid_module,
                "_build_relation_projection_base",
                wraps=base_builder,
            ) as build_base,
        ):
            first = self._run(fixture)
            second = self._run(fixture)

        self.assertEqual(build_content.call_count, 1)
        self.assertEqual(build_base.call_count, 1)
        self.assertEqual(
            first.graph_revision_fingerprint,
            "sha256:fd8594efd6c321f024c4acb78bd6096e4c41e1e472bae43bf193544af711056e",
        )
        self.assertEqual(
            first.result_fingerprint,
            "sha256:04b54caa19e9c91b744d6433357db5b1dc081122a141b46aa504d0bb96c0bc21",
        )
        self.assertEqual(first.plan_fingerprint, second.plan_fingerprint)
        self.assertEqual(first.graph_paths, second.graph_paths)
        self.assertEqual(first.scores, second.scores)
        self.assertEqual(first.answer_citation_hashes, second.answer_citation_hashes)
        self.assertEqual(first.result_fingerprint, second.result_fingerprint)

    def test_sealed_view_rejects_mutation_and_requester_cache_reuse(self) -> None:
        fixture = _connected_off_path_support_fixture(
            self.inputs.effective_graph_view,
        )
        result = self._run(fixture)
        sealed_snapshot = hybrid_module._require_effective_graph_content_snapshot(fixture.view)

        with self.assertRaises(ContractValidationError):
            fixture.view.visible_nodes.append(fixture.view.visible_nodes[0])
        with self.assertRaises(ContractValidationError):
            fixture.view.visible_nodes[0].properties["node_kind"] = "changed"

        other_requester_view = replace(
            fixture.view,
            requester_user_id="user_issue56_other",
        )
        other_fingerprint = hybrid_module._graph_revision_fingerprint(other_requester_view)
        other_snapshot = hybrid_module._require_effective_graph_content_snapshot(
            other_requester_view
        )
        self.assertNotEqual(result.graph_revision_fingerprint, other_fingerprint)
        self.assertIsNot(sealed_snapshot, other_snapshot)
        with self.assertRaisesRegex(
            ContractValidationError,
            "effective graph requester mismatch",
        ):
            self._run(fixture, effective_graph_view=other_requester_view)

    def _run(self, fixture, *, effective_graph_view=None):
        return self.session.query(
            query_text=fixture.query_text,
            effective_graph_view=effective_graph_view or fixture.view,
            allowed_relation_types=ALLOWED_RELATIONS,
            seed_node_ids=(fixture.anchor_node_id,),
        )


if __name__ == "__main__":
    unittest.main()
