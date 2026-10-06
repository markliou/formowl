from __future__ import annotations

from dataclasses import replace
import json
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from formowl_contract import CandidateMention, sha256_json
from formowl_graph import EffectiveGraphView
from formowl_graph.index import GraphProjectionEdge
from formowl_mail import (
    build_authorized_semantic_mail_session,
    build_authorized_source_backed_effective_graph_view,
)
from formowl_mail import hybrid as hybrid_module
from formowl_mail.candidates import (
    SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT,
    SourceBoundIdentifierMentionBatch,
    SourceIdentifierIdentityScope,
    WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
    extract_source_bound_identifier_mentions,
)
from formowl_mail.issue56_real_prompt import (
    SELECTION_ALGORITHM_ID,
    SourceBackedIdentifierPromptSelectionError,
    select_source_backed_connected_identifier_prompt,
)
from scripts.issue56_semantic_execution_smoke import (
    WORKSPACE_ID,
    _build_bundle,
    _mail_observations,
)
from test_issue56_node_backed_fallback_e2e import _contract_only_runtime


_REQUESTER = "user_issue56_real_prompt"
_WORKSPACE = WORKSPACE_ID
_SOURCE_BINDING = sha256_json("issue56_real_prompt_source_binding_v1")
_IDENTIFIER_A = "ORDER-ALPHA-1001"
_IDENTIFIER_B = "ORIGIN-BETA-2002"
_DENIED_IDENTIFIER = "PRIVATE-GAMMA-9009"
_COOCCURS = "co_occurs_with"
_MENTIONS = "mentions_identifier"


class Issue56RealSourcePromptSelectionEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = _contract_only_runtime()
        cls.authorized_observations = _body_preserving_observations(
            namespace="real_prompt_authorized",
            messages=(
                (
                    "source backed relation",
                    f"{_IDENTIFIER_A} relates to {_IDENTIFIER_B}",
                ),
            ),
        )
        cls.denied_observations = _body_preserving_observations(
            namespace="real_prompt_denied",
            messages=(
                (
                    "denied source relation",
                    f"{_DENIED_IDENTIFIER} relates to DENIED-DELTA-9010",
                ),
            ),
        )
        cls.authorized_bundle = _build_bundle(
            observations=cls.authorized_observations,
            namespace="real_prompt_authorized",
            owner_user_id=_REQUESTER,
        )
        cls.denied_bundle = _build_bundle(
            observations=cls.denied_observations,
            namespace="real_prompt_denied",
            owner_user_id="user_issue56_real_prompt_denied",
        )
        cls.observations_by_bundle_id = {
            cls.authorized_bundle.mail_evidence_bundle_id: (cls.authorized_observations),
            cls.denied_bundle.mail_evidence_bundle_id: cls.denied_observations,
        }
        cls.identity_scope = _identity_scope()
        with patch.object(
            hybrid_module,
            "_load_pinned_issue56_runtime_components",
            return_value=cls.runtime,
        ):
            cls.session = build_authorized_semantic_mail_session(
                observations_by_bundle_id=cls.observations_by_bundle_id,
                bundles=(cls.authorized_bundle, cls.denied_bundle),
                requester_user_id=_REQUESTER,
                workspace_id=_WORKSPACE,
            )
        cls.batch = extract_source_bound_identifier_mentions(
            (*cls.authorized_observations, *cls.denied_observations),
            identity_scope=cls.identity_scope,
            extractor_run_id="run_issue56_real_prompt_selection",
            tokenizer_profile=cls.runtime.tokenizer_profile,
            created_at="2026-08-23T00:00:00+00:00",
        )
        cls.graph = build_authorized_source_backed_effective_graph_view(
            session=cls.session,
            observations_by_bundle_id=cls.observations_by_bundle_id,
            source_binding_fingerprint=_SOURCE_BINDING,
            identifier_mention_batch=cls.batch,
            source_graph_policy_id="source_backed_mail_candidate_graph_v2",
        )
        cls.authorized_observation_ids = frozenset(dict(cls.session.authorized_observation_hashes))
        cls.denied_observation_ids = frozenset(
            observation.observation_id for observation in cls.denied_observations
        )

    def test_selects_deterministic_source_backed_pair_without_query_execution(
        self,
    ) -> None:
        with patch.object(
            hybrid_module.AuthorizedSemanticMailSession,
            "query",
            side_effect=AssertionError("query must not execute"),
        ) as query:
            first = self._select()
            second = self._select()

        query.assert_not_called()
        self.assertIn(_IDENTIFIER_A.casefold(), first.runtime_prompt)
        self.assertIn(_IDENTIFIER_B.casefold(), first.runtime_prompt)
        self.assertEqual(first.runtime_prompt, second.runtime_prompt)
        self.assertEqual(first.to_safe_dict(), second.to_safe_dict())
        safe = first.to_safe_dict()
        self.assertEqual(safe["selection_algorithm_id"], SELECTION_ALGORITHM_ID)
        self.assertEqual(safe["selected_identifier_count"], 2)
        self.assertEqual(safe["path_hop_count"], 1)
        self.assertEqual(safe["path_edge_count"], 1)
        self.assertEqual(safe["path_observation_count"], 1)
        self.assertFalse(safe["synthetic_fallback_used"])
        self.assertFalse(safe["query_executed"])
        self.assertEqual(
            safe["selected_term_hashes"],
            sorted(
                (
                    sha256_json(_IDENTIFIER_A.casefold()),
                    sha256_json(_IDENTIFIER_B.casefold()),
                )
            ),
        )
        selected_observation_hashes = set(safe["selected_observation_hashes"])
        for row in safe["identifier_support"]:
            self.assertEqual(len(row["support_observation_hashes"]), 1)
            self.assertTrue(
                set(row["support_observation_hashes"]).issubset(selected_observation_hashes)
            )

    def test_safe_proof_excludes_terms_ids_private_content_and_tenant(self) -> None:
        selection = self._select()
        serialized = json.dumps(
            selection.to_safe_dict(),
            ensure_ascii=False,
            sort_keys=True,
        )
        private_values = (
            _IDENTIFIER_A,
            _IDENTIFIER_B,
            _DENIED_IDENTIFIER,
            "obs_issue56_semantic_real_prompt_authorized_body_1",
            *(node.node_id for node in self.graph.effective_graph_view.visible_nodes),
            *(edge.edge_id for edge in self.graph.effective_graph_view.visible_edges),
        )
        for value in private_values:
            with self.subTest(value=value):
                self.assertNotIn(value, serialized)
        self.assertNotIn("tenant_id", serialized)
        self.assertNotIn(_WORKSPACE, serialized)
        self.assertNotIn(_REQUESTER, serialized)

    def test_graph_only_term_and_observation_term_mismatch_fail_closed(self) -> None:
        authorized_mentions = tuple(
            mention
            for mention in self.batch.candidate_mentions
            if mention.source_observation_ids[0] in self.authorized_observation_ids
        )
        one_term_hash = authorized_mentions[0].text_hash
        one_term_mentions = tuple(
            mention
            for mention in self.batch.candidate_mentions
            if mention.text_hash == one_term_hash
            or mention.source_observation_ids[0] in self.denied_observation_ids
        )
        graph_only_inventory = _batch_with_mentions(
            self.batch,
            one_term_mentions,
            self.identity_scope,
        )
        with self.assertRaisesRegex(
            SourceBackedIdentifierPromptSelectionError,
            "connected_identifier_pair_unavailable",
        ):
            self._select(candidate_inventory=graph_only_inventory)

        target_index = next(
            index
            for index, mention in enumerate(self.batch.candidate_mentions)
            if mention.source_observation_ids[0] in self.authorized_observation_ids
        )
        target = self.batch.candidate_mentions[target_index]
        tampered_payload = target.to_dict()
        tampered_payload["location"]["span_start"] += 1
        tampered = CandidateMention.from_dict(tampered_payload)
        mentions = list(self.batch.candidate_mentions)
        mentions[target_index] = tampered
        mismatched_inventory = _batch_with_mentions(
            self.batch,
            tuple(mentions),
            self.identity_scope,
        )
        with self.assertRaisesRegex(
            SourceBackedIdentifierPromptSelectionError,
            "candidate_exact_term_lineage_invalid",
        ):
            self._select(candidate_inventory=mismatched_inventory)

    def test_denied_or_unsupported_path_evidence_fails_closed(self) -> None:
        cooccurrence_edge = next(
            edge
            for edge in self.graph.effective_graph_view.visible_edges
            if edge.relation_type == _COOCCURS
        )
        denied_observation = self.denied_observations[-1]
        denied_edge = replace(
            cooccurrence_edge,
            properties={
                **cooccurrence_edge.properties,
                "source_observation_ids": [denied_observation.observation_id],
            },
            permission_scope=dict(denied_observation.permission_scope),
        )
        view = _view_with_replaced_edge(
            self.graph.effective_graph_view,
            target_edge_id=cooccurrence_edge.edge_id,
            replacement=denied_edge,
        )
        with self.assertRaisesRegex(
            SourceBackedIdentifierPromptSelectionError,
            "effective_graph_evidence_not_authorized",
        ):
            self._select(effective_graph_view=view)

    def test_disallowed_relation_and_over_max_hops_have_no_fallback(self) -> None:
        with self.assertRaisesRegex(
            SourceBackedIdentifierPromptSelectionError,
            "connected_identifier_pair_unavailable",
        ):
            self._select(allowed_relation_types=("unsupported_relation",))

        with self.assertRaisesRegex(
            SourceBackedIdentifierPromptSelectionError,
            "connected_identifier_pair_unavailable",
        ):
            self._select(
                allowed_relation_types=(_MENTIONS,),
                max_hops=1,
            )
        two_hop = self._select(
            allowed_relation_types=(_MENTIONS,),
            max_hops=2,
        )
        two_hop_safe = two_hop.to_safe_dict()
        self.assertEqual(two_hop_safe["path_hop_count"], 2)
        self.assertEqual(two_hop_safe["path_observation_count"], 1)

    def test_requester_workspace_and_tenant_drift_fail_closed(self) -> None:
        changed_requester = replace(
            self.graph.effective_graph_view,
            requester_user_id="user_issue56_other",
        )
        with self.assertRaisesRegex(
            SourceBackedIdentifierPromptSelectionError,
            "graph_requester_binding_mismatch",
        ):
            self._select(effective_graph_view=changed_requester)

        changed_workspace = replace(
            self.batch,
            workspace_id="workspace_issue56_other",
        )
        with self.assertRaisesRegex(
            SourceBackedIdentifierPromptSelectionError,
            "candidate_identity_scope_invalid",
        ):
            self._select(candidate_inventory=changed_workspace)

        fabricated_tenant = replace(
            self.batch,
            tenant_id="tenant_must_not_exist",
        )
        with self.assertRaisesRegex(
            SourceBackedIdentifierPromptSelectionError,
            "candidate_identity_scope_invalid",
        ):
            self._select(candidate_inventory=fabricated_tenant)

    def _select(
        self,
        *,
        effective_graph_view: EffectiveGraphView | None = None,
        candidate_inventory: SourceBoundIdentifierMentionBatch | None = None,
        allowed_relation_types: tuple[str, ...] = (_COOCCURS,),
        max_hops: int = 2,
    ):
        return select_source_backed_connected_identifier_prompt(
            session=self.session,
            effective_graph_view=(effective_graph_view or self.graph.effective_graph_view),
            candidate_inventory=candidate_inventory or self.batch,
            allowed_relation_types=allowed_relation_types,
            max_hops=max_hops,
        )


def _body_preserving_observations(
    *,
    namespace: str,
    messages: tuple[tuple[str, str], ...],
):
    observations = list(
        _mail_observations(
            namespace=namespace,
            messages=messages,
        )
    )
    observations[0] = replace(observations[0], text=None)
    return tuple(observations)


def _identity_scope() -> SourceIdentifierIdentityScope:
    scope_payload = {
        "mode": WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
        "workspace_id": _WORKSPACE,
    }
    return SourceIdentifierIdentityScope(
        identity_scope_mode=WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
        identity_scope_fingerprint=sha256_json(scope_payload),
        workspace_id=_WORKSPACE,
        identity_scope_attestation_fingerprint=sha256_json(
            {
                "scope": scope_payload,
                "attestation": "issue56_real_prompt_synthetic_v1",
            }
        ),
        identity_scope_policy_fingerprint=sha256_json(
            "issue56_real_prompt_identity_scope_policy_v1"
        ),
        operator_approval_fingerprint=sha256_json(
            "issue56_real_prompt_synthetic_operator_approval_v1"
        ),
        tenant_id=None,
        spec_approval_fingerprint=sha256_json(
            "issue56_real_prompt_workspace_only_spec_approval_v1"
        ),
    )


def _batch_with_mentions(
    batch: SourceBoundIdentifierMentionBatch,
    mentions: tuple[CandidateMention, ...],
    identity_scope: SourceIdentifierIdentityScope,
) -> SourceBoundIdentifierMentionBatch:
    ordered_mentions = tuple(sorted(mentions, key=lambda item: item.candidate_mention_id))
    return replace(
        batch,
        candidate_mentions=ordered_mentions,
        occurrence_count=len(ordered_mentions),
        batch_fingerprint=sha256_json(
            {
                "candidate_mention_ids": [
                    mention.candidate_mention_id for mention in ordered_mentions
                ],
                "extraction_policy_fingerprint": (
                    SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT
                ),
                "identity_scope": identity_scope.to_dict(),
                "tokenizer_profile_fingerprint": (batch.tokenizer_profile_fingerprint),
            }
        ),
    )


def _view_with_replaced_edge(
    view: EffectiveGraphView,
    *,
    target_edge_id: str,
    replacement: GraphProjectionEdge,
) -> EffectiveGraphView:
    return replace(
        view,
        visible_nodes=list(view.visible_nodes),
        visible_edges=[
            replacement if edge.edge_id == target_edge_id else edge for edge in view.visible_edges
        ],
        access_required=list(view.access_required),
        applied_grant_ids=list(view.applied_grant_ids),
    )


if __name__ == "__main__":
    unittest.main()
