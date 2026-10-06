from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, sha256_json
from formowl_mail import build_authorized_semantic_mail_session
from formowl_mail import hybrid as hybrid_module
from formowl_mail import issue56_sealed_source as sealed_source
from scripts.issue56_semantic_execution_smoke import (
    ALLOWED_RELATIONS,
    REQUESTER_USER_ID,
    WORKSPACE_ID,
    build_semantic_poc_inputs,
)
from test_issue56_node_backed_fallback_e2e import _contract_only_runtime
from test_issue56_sealed_source_loader_e2e import _loader_kwargs, _prepare_package
import test_issue56_source_neutral_hybrid_e2e as source_neutral_fixture


class Issue56RelationProjectionBasePrecomputeEndToEndTests(unittest.TestCase):
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

    def test_cold_precompute_builds_once_and_real_query_reuses_exact_base(
        self,
    ) -> None:
        query_text = "PO470002002 與 ORIGIN-TAIWAN-01 的關係"
        real_builder = hybrid_module._build_relation_projection_base
        real_ranker = hybrid_module._rank_relation_projection_query_anchors
        with (
            patch.object(
                hybrid_module,
                "_build_relation_projection_base",
                wraps=real_builder,
            ) as build_base,
            patch.object(
                hybrid_module,
                "_rank_relation_projection_query_anchors",
                wraps=real_ranker,
            ) as rank_anchors,
        ):
            precomputed = hybrid_module.precompute_relation_projection_base(
                session=self.session,
                effective_graph_view=self.inputs.effective_graph_view,
            )
            repeated = hybrid_module.precompute_relation_projection_base(
                session=self.session,
                effective_graph_view=self.inputs.effective_graph_view,
            )
            self.assertEqual(build_base.call_count, 1)
            self.assertEqual(rank_anchors.call_count, 0)
            warmed = self.session.query(
                query_text=query_text,
                effective_graph_view=self.inputs.effective_graph_view,
                allowed_relation_types=ALLOWED_RELATIONS,
            )
            self.assertEqual(build_base.call_count, 1)
            self.assertEqual(rank_anchors.call_count, 2)

        self.assertEqual(repeated, precomputed)
        snapshot = hybrid_module._build_query_graph_snapshot(self.inputs.effective_graph_view)
        with snapshot.content_snapshot.relation_projection_base_lock:
            snapshot.content_snapshot.relation_projection_bases.clear()
        cold = self.session.query(
            query_text=query_text,
            effective_graph_view=self.inputs.effective_graph_view,
            allowed_relation_types=ALLOWED_RELATIONS,
        )
        self.assertEqual(warmed.to_safe_dict(), cold.to_safe_dict())

    def test_graph_and_index_revision_changes_miss_cache_and_stale_base_fails_closed(
        self,
    ) -> None:
        real_builder = hybrid_module._build_relation_projection_base
        with patch.object(
            hybrid_module,
            "_build_relation_projection_base",
            wraps=real_builder,
        ) as build_base:
            original = hybrid_module.precompute_relation_projection_base(
                session=self.session,
                effective_graph_view=self.inputs.effective_graph_view,
            )
            changed_graph = replace(
                self.inputs.effective_graph_view,
                applied_grant_ids=["grant_issue56_relation_projection_changed"],
            )
            graph_changed = hybrid_module.precompute_relation_projection_base(
                session=self.session,
                effective_graph_view=changed_graph,
            )
            self.assertEqual(build_base.call_count, 2)
            self.assertNotEqual(
                graph_changed.graph_revision_fingerprint,
                original.graph_revision_fingerprint,
            )

            changed_index_fingerprint = sha256_json(
                {
                    "base": self.session.index.index_fingerprint,
                    "revision": 2,
                }
            )
            changed_index = replace(
                self.session.index,
                index_fingerprint=changed_index_fingerprint,
                _integrity_fingerprint=hybrid_module._hybrid_index_integrity_fingerprint(
                    index_fingerprint=changed_index_fingerprint,
                    tokenizer_id=self.session.index.tokenizer_id,
                    profile_fingerprint=self.session.index.profile_fingerprint,
                    execution_component_fingerprint=(
                        self.session.index.execution_component_fingerprint
                    ),
                    candidates=self.session.index.candidates,
                ),
            )
            index_changed = hybrid_module.precompute_relation_projection_base(
                session=replace(self.session, index=changed_index),
                effective_graph_view=self.inputs.effective_graph_view,
            )
            self.assertEqual(build_base.call_count, 3)
            self.assertEqual(index_changed.index_fingerprint, changed_index_fingerprint)

        snapshot = hybrid_module._build_query_graph_snapshot(self.inputs.effective_graph_view)
        with snapshot.content_snapshot.relation_projection_base_lock:
            cache_key, cached = next(
                iter(snapshot.content_snapshot.relation_projection_bases.items())
            )
            snapshot.content_snapshot.relation_projection_bases[cache_key] = replace(
                cached,
                candidate_set_fingerprint=sha256_json("stale_candidate_set"),
            )
        with self.assertRaisesRegex(
            ContractValidationError,
            "precompute binding mismatch",
        ):
            hybrid_module.precompute_relation_projection_base(
                session=self.session,
                effective_graph_view=self.inputs.effective_graph_view,
            )

    def test_requester_source_observation_tokenizer_and_candidate_drift_fail_closed(
        self,
    ) -> None:
        changed_requester_graph = replace(
            self.inputs.effective_graph_view,
            requester_user_id="user_not_authorized",
        )
        with self.assertRaisesRegex(ContractValidationError, "requester mismatch"):
            hybrid_module.precompute_relation_projection_base(
                session=self.session,
                effective_graph_view=changed_requester_graph,
            )

        with self.assertRaisesRegex(ContractValidationError, "source binding mismatch"):
            hybrid_module.precompute_relation_projection_base(
                session=replace(self.session, workspace_id="workspace_not_authorized"),
                effective_graph_view=self.inputs.effective_graph_view,
            )

        changed_hashes = tuple(
            (
                observation_id,
                sha256_json(["drift", observation_hash]),
            )
            for observation_id, observation_hash in self.session.authorized_observation_hashes
        )
        with self.assertRaisesRegex(ContractValidationError, "Observation binding mismatch"):
            hybrid_module.precompute_relation_projection_base(
                session=replace(
                    self.session,
                    authorized_observation_hashes=changed_hashes,
                ),
                effective_graph_view=self.inputs.effective_graph_view,
            )

        changed_profile_fingerprint = sha256_json("changed_profile")
        changed_profile_index = replace(
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
        with self.assertRaisesRegex(ContractValidationError, "tokenizer profile mismatch"):
            hybrid_module.precompute_relation_projection_base(
                session=replace(self.session, index=changed_profile_index),
                effective_graph_view=self.inputs.effective_graph_view,
            )

        first_candidate = self.session.index.candidates[0]
        changed_candidate = replace(
            first_candidate,
            index_binding_hash=sha256_json("stale_candidate_binding"),
        )
        changed_candidates = (changed_candidate, *self.session.index.candidates[1:])
        changed_candidate_index = replace(
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
            "authorized candidate mismatch",
        ):
            hybrid_module.precompute_relation_projection_base(
                session=replace(self.session, index=changed_candidate_index),
                effective_graph_view=self.inputs.effective_graph_view,
            )

    def test_source_neutral_session_binding_and_safe_metadata_are_fail_closed(
        self,
    ) -> None:
        fixture = source_neutral_fixture.Issue56SourceNeutralHybridEndToEndTests(
            methodName="test_github_issue_comment_query_uses_typed_occurrence_graph_and_citations"
        )
        fixture.setUpClass()
        session, graph_build = fixture._session_and_graph()
        precomputed = hybrid_module.precompute_relation_projection_base(
            session=session,
            effective_graph_view=graph_build.effective_graph_view,
        )
        safe = precomputed.to_safe_dict()
        rendered = json.dumps(safe, ensure_ascii=True, sort_keys=True)
        for private_value in (
            fixture.issue.observation_id,
            fixture.comment.observation_id,
            fixture.issue.text,
            fixture.comment.text,
            session.requester_user_id,
            session.workspace_id,
            graph_build.effective_graph_view.visible_nodes[0].node_id,
            "tenant_id",
        ):
            self.assertNotIn(private_value, rendered)
        self.assertEqual(
            safe["counts"]["authorized_observation_count"],
            len(session.authorized_observations),
        )
        self.assertEqual(
            safe["graph_revision_fingerprint"],
            graph_build.graph_revision_fingerprint,
        )

        with self.assertRaisesRegex(ContractValidationError, "session binding mismatch"):
            hybrid_module.precompute_relation_projection_base(
                session=replace(
                    session,
                    source_session_binding_fingerprint=sha256_json("stale"),
                ),
                effective_graph_view=graph_build.effective_graph_view,
            )

    def test_sealed_loader_primes_once_after_lineage_and_exposes_safe_binding(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package = _prepare_package(Path(temp_dir))
            real_lineage = sealed_source.precompute_evidence_identity_lineage_crosswalk
            real_relation = sealed_source.precompute_relation_projection_base
            call_order: list[str] = []

            def lineage(**kwargs):
                call_order.append("lineage")
                return real_lineage(**kwargs)

            def relation(**kwargs):
                call_order.append("relation")
                return real_relation(**kwargs)

            with (
                patch.object(
                    hybrid_module,
                    "_load_pinned_issue56_runtime_components",
                    return_value=self.runtime,
                ),
                patch.object(
                    sealed_source,
                    "precompute_evidence_identity_lineage_crosswalk",
                    side_effect=lineage,
                ) as lineage_helper,
                patch.object(
                    sealed_source,
                    "precompute_relation_projection_base",
                    side_effect=relation,
                ) as relation_helper,
            ):
                loaded = sealed_source.load_issue56_sealed_source(**_loader_kwargs(package))

        lineage_helper.assert_called_once()
        relation_helper.assert_called_once()
        self.assertEqual(call_order, ["lineage", "relation"])
        binding = loaded.safe_binding["relation_projection_base_precompute"]
        self.assertEqual(binding["status"], "passed")
        self.assertEqual(binding["cache_status"], "primed")
        self.assertEqual(binding["helper_invocation_count"], 1)
        self.assertGreaterEqual(binding["elapsed_ms"], 0.0)
        self.assertEqual(
            binding["index_fingerprint"],
            loaded.safe_binding["index_fingerprint"],
        )
        self.assertEqual(
            binding["graph_revision_fingerprint"],
            loaded.safe_binding["graph_revision_fingerprint"],
        )
        self.assertEqual(
            binding["counts"]["authorized_observation_count"],
            loaded.safe_binding["counts"]["authorized_observation_count"],
        )
        rendered = json.dumps(binding, ensure_ascii=True, sort_keys=True)
        self.assertNotIn("tenant_id", rendered)
        self.assertNotIn(sealed_source.WORKSPACE_ID, rendered)
        self.assertNotIn(sealed_source.APPROVER_ACTOR, rendered)


if __name__ == "__main__":
    unittest.main()
