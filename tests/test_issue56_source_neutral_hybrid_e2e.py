from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import math
import unittest
from unittest.mock import patch
from typing import Iterator, Sequence

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, Observation, sha256_json
from formowl_core import (
    Issue56TargetRuntimeComponents,
    SentenceTransformerDenseEncoder,
    build_issue56_execution_component_binding,
    issue56_target_dense_embedding_profile,
    load_issue56_target_mail_tokenizer_profile,
)
from formowl_mail.hybrid import (
    AuthorizedSemanticObservationSession,
    attach_authorized_source_occurrence_providers,
    build_authorized_hybrid_mail_index,
    build_authorized_semantic_mail_session,
    build_authorized_semantic_observation_session,
    build_authorized_source_backed_effective_graph_view,
    run_authorized_semantic_mail_query,
)
from formowl_mail.exact import (
    SourceOccurrenceProvider,
    authorized_source_occurrence_scope_fingerprint,
)
from formowl_mail.query import (
    build_authorized_observation_snippet_index,
    source_occurrence_lineage_from_observation,
)
from formowl_mail.semantic_plan import (
    AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
    GITHUB_PROJECT_OBSERVATION_SOURCE_KIND,
    validated_authorized_semantic_source,
)
from scripts.issue56_semantic_execution_smoke import (
    REQUESTER_USER_ID as MAIL_REQUESTER_ID,
    WORKSPACE_ID as MAIL_WORKSPACE_ID,
    build_semantic_poc_inputs,
)


WORKSPACE_ID = "workspace_source_neutral_hybrid"
PROJECT_SCOPE_ID = "project_source_neutral_hybrid"
REQUESTER_ID = "user_source_neutral_hybrid"
CO_OCCURS_WITH = "co_occurs_with"


def _github_observation(
    *,
    observation_id: str,
    record_kind: str,
    source_local_key: str,
    text: str,
    parent_source_local_key: str | None = None,
) -> Observation:
    source_record_fingerprint = sha256_json(
        {
            "observation_id": observation_id,
            "record_kind": record_kind,
            "source_local_key": source_local_key,
        }
    )
    location: dict[str, object] = {
        "source_local_key": source_local_key,
        "source_record_fingerprint": source_record_fingerprint,
        "record_kind": record_kind,
    }
    if parent_source_local_key is not None:
        location["parent_source_local_key"] = parent_source_local_key
    payload = {
        **location,
        "issue_number": 56,
        "created_at": "2026-08-19T00:00:00+00:00",
        "updated_at": "2026-08-19T01:00:00+00:00",
        "source_native_issue_references": [51],
    }
    if record_kind == "issue_record":
        payload["state"] = "open"
        payload["label_names"] = ["kg", "transfer"]
    return Observation.from_dict(
        Observation(
            observation_id=observation_id,
            extractor_run_id="extractor_source_neutral_hybrid",
            observation_type=record_kind,
            modality="project",
            location=location,
            confidence=1.0,
            permission_scope={
                "scope_type": "project",
                "visibility": "shared",
                "scope_id": PROJECT_SCOPE_ID,
            },
            created_at="2026-08-19T01:00:00+00:00",
            asset_id="asset_source_neutral_hybrid",
            text=text,
            payload=payload,
        ).to_dict()
    )


class Issue56SourceNeutralHybridEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = load_issue56_target_mail_tokenizer_profile()
        cls.runtime = _contract_only_runtime()
        cls.authorized_source = validated_authorized_semantic_source(
            source_kind=GITHUB_PROJECT_OBSERVATION_SOURCE_KIND,
            workspace_id=WORKSPACE_ID,
            source_scope_ids=(PROJECT_SCOPE_ID,),
        )
        issue_key = "source_local_issue_source_neutral_hybrid"
        cls.issue = _github_observation(
            observation_id="observation_github_issue_source_neutral_hybrid",
            record_kind="issue_record",
            source_local_key=issue_key,
            text="Issue 56 tracks source-neutral semantic execution and graph evidence.",
        )
        cls.comment = _github_observation(
            observation_id="observation_github_comment_source_neutral_hybrid",
            record_kind="top_level_issue_comment",
            source_local_key="source_local_comment_source_neutral_hybrid",
            parent_source_local_key=issue_key,
            text="The typed project comment confirms semantic graph execution.",
        )
        cls.observations = (cls.issue, cls.comment)
        cls.authorized_hashes = {
            observation.observation_id: sha256_json(observation.to_dict())
            for observation in cls.observations
        }
        cls.lineages = tuple(
            source_occurrence_lineage_from_observation(
                observation,
                authorized_source=cls.authorized_source,
            )
            for observation in cls.observations
        )
        cls.snippet_index, cls.index_manifest = build_authorized_observation_snippet_index(
            cls.observations,
            authorized_source=cls.authorized_source,
            occurrence_lineages=cls.lineages,
            authorized_observation_hash_by_id=cls.authorized_hashes,
            tokenizer_profile=cls.profile,
        )

    @contextmanager
    def _runtime_patch(self) -> Iterator[None]:
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=self.runtime,
        ):
            yield

    def _session_and_graph(self):
        with self._runtime_patch():
            session = build_authorized_semantic_observation_session(
                authorized_source=self.authorized_source,
                snippet_index=self.snippet_index,
                authorized_observations=self.observations,
                occurrence_lineages=self.lineages,
                requester_user_id=REQUESTER_ID,
            )
        graph_build = build_authorized_source_backed_effective_graph_view(
            session=session,
            source_binding_fingerprint=self.index_manifest.index_fingerprint,
        )
        return session, graph_build

    def test_github_issue_comment_query_uses_typed_occurrence_graph_and_citations(
        self,
    ) -> None:
        session, graph_build = self._session_and_graph()
        self.assertIsInstance(session, AuthorizedSemanticObservationSession)
        self.assertEqual(
            session.authorized_source.source_kind,
            GITHUB_PROJECT_OBSERVATION_SOURCE_KIND,
        )
        self.assertEqual(graph_build.source_observation_count, 2)
        self.assertEqual(
            graph_build.relation_type_hashes,
            (sha256_json(CO_OCCURS_WITH),),
        )
        source_kind_hash = sha256_json(GITHUB_PROJECT_OBSERVATION_SOURCE_KIND)
        self.assertTrue(graph_build.effective_graph_view.visible_nodes)
        self.assertTrue(
            all(
                node.properties["source_kind_hash"] == source_kind_hash
                for node in graph_build.effective_graph_view.visible_nodes
            )
        )
        parent_edges = [
            edge
            for edge in graph_build.effective_graph_view.visible_edges
            if len(edge.properties["source_observation_ids"]) == 2
        ]
        self.assertEqual(len(parent_edges), 1)
        self.assertEqual(parent_edges[0].relation_type, CO_OCCURS_WITH)

        result = session.query(
            query_text="Find source-neutral semantic graph execution evidence.",
            effective_graph_view=graph_build.effective_graph_view,
        )
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.semantic_result_count, 2)
        self.assertTrue(result.answer_citation_hashes)
        self.assertTrue(
            set(result.answer_citation_hashes).issubset(set(self.authorized_hashes.values()))
        )
        self.assertEqual(result.repair_attempt_count, 0)
        provider = SourceOccurrenceProvider(
            provider_id="source_neutral_provider_extension",
            inventory_kind_alias="source_neutral_record",
            resource_kind="source_neutral_record",
            normalized_field="source_neutral.record",
            predicate="source_occurrence_contains",
            operator="case_insensitive_exact",
            requester_user_id=session.requester_user_id,
            workspace_id=session.workspace_id,
            source_scope_ids=session.authorized_source_scope_ids,
            authorized_scope_fingerprint=authorized_source_occurrence_scope_fingerprint(
                requester_user_id=session.requester_user_id,
                workspace_id=session.workspace_id,
                source_scope_ids=session.authorized_source_scope_ids,
                authorized_observation_hashes=session.authorized_observation_hashes,
                source_session_binding_fingerprint=session.source_session_binding_fingerprint
                or "",
            ),
            occurrences=(),
        )
        attached_result = attach_authorized_source_occurrence_providers(
            session, (provider,)
        ).query(
            query_text="Find source-neutral semantic graph execution evidence.",
            effective_graph_view=graph_build.effective_graph_view,
        )
        self.assertEqual(attached_result.result_fingerprint, result.result_fingerprint)

    def test_github_exact_inventory_and_rerun_are_deterministic(self) -> None:
        session, graph_build = self._session_and_graph()
        query = "List every source-neutral issue record in the complete inventory."
        first = session.query(
            query_text=query,
            effective_graph_view=graph_build.effective_graph_view,
            exact_inventory_kind="issue_record",
        )
        second = session.query(
            query_text=query,
            effective_graph_view=graph_build.effective_graph_view,
            exact_inventory_kind="issue_record",
        )

        self.assertEqual(first.status, "complete_authorized_scope")
        self.assertIsNotNone(first.exact_result)
        assert first.exact_result is not None
        self.assertEqual(first.exact_result.exact_count, 1)
        self.assertEqual(first.exact_result.returned_item_count, 1)
        self.assertEqual(
            first.answer_citation_hashes,
            (self.authorized_hashes[self.issue.observation_id],),
        )
        self.assertEqual(first.plan_fingerprint, second.plan_fingerprint)
        self.assertEqual(first.result_fingerprint, second.result_fingerprint)
        self.assertEqual(first.to_safe_dict(), second.to_safe_dict())

    def test_source_kind_permission_and_graph_mismatch_fail_closed(self) -> None:
        mail_source = validated_authorized_semantic_source(
            source_kind=AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
            workspace_id=WORKSPACE_ID,
            source_scope_ids=(PROJECT_SCOPE_ID,),
        )
        with (
            self._runtime_patch(),
            self.assertRaisesRegex(
                ContractValidationError,
                "permission scope mismatch",
            ),
        ):
            build_authorized_semantic_observation_session(
                authorized_source=mail_source,
                snippet_index=self.snippet_index,
                authorized_observations=self.observations,
                occurrence_lineages=self.lineages,
                requester_user_id=REQUESTER_ID,
            )

        denied_comment = replace(
            self.comment,
            permission_scope={
                "scope_type": "project",
                "visibility": "shared",
                "scope_id": "project_not_authorized",
            },
        )
        with (
            self._runtime_patch(),
            self.assertRaisesRegex(
                ContractValidationError,
                "permission scope mismatch",
            ),
        ):
            build_authorized_semantic_observation_session(
                authorized_source=self.authorized_source,
                snippet_index=self.snippet_index,
                authorized_observations=(self.issue, denied_comment),
                occurrence_lineages=self.lineages,
                requester_user_id=REQUESTER_ID,
            )

        session, graph_build = self._session_and_graph()
        first_node = graph_build.effective_graph_view.visible_nodes[0]
        mismatched_node = replace(
            first_node,
            properties={
                **first_node.properties,
                "source_kind_hash": sha256_json(AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND),
            },
        )
        mismatched_view = replace(
            graph_build.effective_graph_view,
            visible_nodes=[
                mismatched_node,
                *graph_build.effective_graph_view.visible_nodes[1:],
            ],
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "effective graph content snapshot is unavailable",
        ):
            session.query(
                query_text="Find source-neutral semantic graph evidence.",
                effective_graph_view=mismatched_view,
            )

    def test_mail_compatibility_wrapper_preserves_index_and_result_fingerprints(
        self,
    ) -> None:
        inputs = build_semantic_poc_inputs()
        observations_by_bundle_id = inputs.observations_by_bundle_id
        bundles = (
            inputs.current_bundle,
            inputs.superseded_bundle,
            inputs.denied_bundle,
        )
        with self._runtime_patch():
            session = build_authorized_semantic_mail_session(
                observations_by_bundle_id=observations_by_bundle_id,
                bundles=bundles,
                requester_user_id=MAIL_REQUESTER_ID,
                workspace_id=MAIL_WORKSPACE_ID,
            )
            direct_index = build_authorized_hybrid_mail_index(
                observations_by_bundle_id=observations_by_bundle_id,
                bundles=bundles,
                requester_user_id=MAIL_REQUESTER_ID,
                workspace_id=MAIL_WORKSPACE_ID,
            )
            session_result = session.query(
                query_text="PO470002002",
                effective_graph_view=inputs.effective_graph_view,
            )
            wrapper_result = run_authorized_semantic_mail_query(
                observations_by_bundle_id=observations_by_bundle_id,
                bundles=bundles,
                query_text="PO470002002",
                requester_user_id=MAIL_REQUESTER_ID,
                workspace_id=MAIL_WORKSPACE_ID,
                effective_graph_view=inputs.effective_graph_view,
            )

        self.assertEqual(session.index.index_fingerprint, direct_index.index_fingerprint)
        self.assertEqual(session_result.plan_fingerprint, wrapper_result.plan_fingerprint)
        self.assertEqual(session_result.result_fingerprint, wrapper_result.result_fingerprint)
        self.assertEqual(session_result.to_safe_dict(), wrapper_result.to_safe_dict())


class _ContractOnlySentenceTransformerModel:
    def encode(self, texts: Sequence[str], **_kwargs):
        rows = []
        for text in texts:
            vector = [0.0] * 384
            for character in text.casefold():
                vector[ord(character) % len(vector)] += 1.0
            norm = math.sqrt(sum(value * value for value in vector))
            rows.append(_VectorRow(value / norm for value in vector))
        return rows


class _VectorRow(list[float]):
    def tolist(self) -> list[float]:
        return list(self)


def _contract_only_runtime() -> Issue56TargetRuntimeComponents:
    tokenizer_profile = load_issue56_target_mail_tokenizer_profile()
    dense_profile = issue56_target_dense_embedding_profile()
    encoder = SentenceTransformerDenseEncoder(
        profile=dense_profile,
        _model=_ContractOnlySentenceTransformerModel(),
    )
    binding = build_issue56_execution_component_binding(
        tokenizer_profile=tokenizer_profile,
        dense_profile=dense_profile,
    )
    return Issue56TargetRuntimeComponents(
        tokenizer_profile=tokenizer_profile,
        dense_encoder=encoder,
        execution_binding=binding,
    )


if __name__ == "__main__":
    unittest.main()
