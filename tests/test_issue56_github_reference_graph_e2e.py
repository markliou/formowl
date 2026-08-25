from __future__ import annotations

from contextlib import contextmanager
import math
import unittest
from unittest.mock import patch
from typing import Any, Iterator, Sequence

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
    build_authorized_semantic_mail_session,
    build_authorized_semantic_observation_session,
    build_authorized_source_backed_effective_graph_view,
)
from formowl_mail.query import (
    build_authorized_observation_snippet_index,
    source_occurrence_lineage_from_observation,
)
from formowl_mail.semantic_plan import (
    GITHUB_PROJECT_OBSERVATION_SOURCE_KIND,
    validated_authorized_semantic_source,
)
from scripts.issue56_semantic_execution_smoke import (
    REQUESTER_USER_ID as MAIL_REQUESTER_ID,
    WORKSPACE_ID as MAIL_WORKSPACE_ID,
    build_semantic_poc_inputs,
)


WORKSPACE_ID = "workspace_github_reference_graph"
PROJECT_A = "project_github_reference_a"
PROJECT_B = "project_github_reference_b"
REQUESTER_ID = "user_github_reference_graph"
GITHUB_REFERENCE_POLICY_ID = "source_backed_github_candidate_graph_v1"
GITHUB_REFERENCE_RELATION = "source_native_issue_reference"
CO_OCCURS_WITH = "co_occurs_with"

MAIL_INDEX_FINGERPRINT = "sha256:7bf7cc99463d14363d7f7ef91afec8be44e3d79572d016c917582100360e26fb"
MAIL_GRAPH_BUILD_FINGERPRINT = (
    "sha256:8f0e2a38614f5a990818b9d2e427ee4c1e625aee9bda5f33a67dd53df96773cb"
)
MAIL_GRAPH_REVISION_FINGERPRINT = (
    "sha256:9d355b300b1d7cd99555e99f2a42e64fe2f8526009632f32c9fd715f80966037"
)


def _github_observation(
    *,
    observation_id: str,
    project_scope_id: str,
    record_kind: str,
    issue_number: int,
    source_local_key: str,
    text: str,
    source_native_issue_references: Sequence[Any],
    parent_source_local_key: str | None = None,
) -> Observation:
    source_record_fingerprint = sha256_json(
        {
            "project_scope_hash": sha256_json(project_scope_id),
            "record_kind": record_kind,
            "issue_number": issue_number,
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
    payload: dict[str, object] = {
        **location,
        "issue_number": issue_number,
        "created_at": "2026-08-19T00:00:00+00:00",
        "updated_at": "2026-08-19T01:00:00+00:00",
        "source_native_issue_references": list(source_native_issue_references),
    }
    if record_kind == "issue_record":
        payload.update(
            {
                "state": "open",
                "state_reason": None,
                "closed_at": None,
                "label_names": ["kg", "source-reference"],
            }
        )
    return Observation.from_dict(
        Observation(
            observation_id=observation_id,
            extractor_run_id="extractor_github_reference_graph",
            observation_type=record_kind,
            modality="project",
            location=location,
            confidence=1.0,
            permission_scope={
                "scope_type": "project",
                "visibility": "shared",
                "scope_id": project_scope_id,
            },
            created_at="2026-08-19T01:00:00+00:00",
            asset_id="asset_github_reference_graph",
            text=text,
            payload=payload,
        ).to_dict()
    )


class Issue56GitHubReferenceGraphEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = load_issue56_target_mail_tokenizer_profile()
        cls.runtime = _contract_only_runtime()
        cls.issue_51 = _github_observation(
            observation_id="observation_github_reference_issue_51",
            project_scope_id=PROJECT_A,
            record_kind="issue_record",
            issue_number=51,
            source_local_key="source_local_github_reference_issue_51",
            text="Target issue contains source native reference graph evidence.",
            source_native_issue_references=(),
        )
        cls.issue_56 = _github_observation(
            observation_id="observation_github_reference_issue_56",
            project_scope_id=PROJECT_A,
            record_kind="issue_record",
            issue_number=56,
            source_local_key="source_local_github_reference_issue_56",
            text="Source issue records source native issue reference relationship evidence.",
            source_native_issue_references=(51,),
        )
        cls.comment_56 = _github_observation(
            observation_id="observation_github_reference_comment_56",
            project_scope_id=PROJECT_A,
            record_kind="top_level_issue_comment",
            issue_number=56,
            source_local_key="source_local_github_reference_comment_56",
            parent_source_local_key="source_local_github_reference_issue_56",
            text="Comment parent relationship records authorized parent evidence.",
            source_native_issue_references=(),
        )
        cls.observations = (cls.comment_56, cls.issue_56, cls.issue_51)

    @contextmanager
    def _runtime_patch(self) -> Iterator[None]:
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=self.runtime,
        ):
            yield

    def _build(
        self,
        observations: Sequence[Observation],
        *,
        project_scope_ids: Sequence[str] = (PROJECT_A,),
    ):
        authorized_source = validated_authorized_semantic_source(
            source_kind=GITHUB_PROJECT_OBSERVATION_SOURCE_KIND,
            workspace_id=WORKSPACE_ID,
            source_scope_ids=project_scope_ids,
        )
        lineages = tuple(
            source_occurrence_lineage_from_observation(
                observation,
                authorized_source=authorized_source,
            )
            for observation in observations
        )
        authorized_hashes = {
            observation.observation_id: sha256_json(observation.to_dict())
            for observation in observations
        }
        snippet_index, manifest = build_authorized_observation_snippet_index(
            observations,
            authorized_source=authorized_source,
            occurrence_lineages=lineages,
            authorized_observation_hash_by_id=authorized_hashes,
            tokenizer_profile=self.profile,
        )
        with self._runtime_patch():
            session = build_authorized_semantic_observation_session(
                authorized_source=authorized_source,
                snippet_index=snippet_index,
                authorized_observations=observations,
                occurrence_lineages=lineages,
                requester_user_id=REQUESTER_ID,
            )
        graph = build_authorized_source_backed_effective_graph_view(
            session=session,
            source_binding_fingerprint=manifest.index_fingerprint,
            source_graph_policy_id=GITHUB_REFERENCE_POLICY_ID,
        )
        return session, graph, authorized_hashes

    def test_comment_parent_relation_is_source_authored_and_cites_the_comment(
        self,
    ) -> None:
        session, graph, authorized_hashes = self._build(self.observations)
        node_ids = _observation_node_ids(graph.effective_graph_view.visible_nodes)
        parent_edges = [
            edge
            for edge in graph.effective_graph_view.visible_edges
            if edge.relation_type == GITHUB_REFERENCE_RELATION
            and edge.source_node_id == node_ids[self.comment_56.observation_id]
            and edge.target_node_id == node_ids[self.issue_56.observation_id]
        ]
        self.assertEqual(len(parent_edges), 1)
        self.assertEqual(
            parent_edges[0].properties["source_observation_ids"],
            [self.comment_56.observation_id],
        )
        self.assertEqual(
            parent_edges[0].properties["source_scope_hash"],
            sha256_json(PROJECT_A),
        )

        result = session.query(
            query_text="What relationship records authorized parent evidence?",
            effective_graph_view=graph.effective_graph_view,
            allowed_relation_types=(GITHUB_REFERENCE_RELATION,),
            seed_node_ids=(node_ids[self.comment_56.observation_id],),
        )
        self.assertEqual(result.status, "ok")
        self.assertTrue(result.graph_paths)
        self.assertEqual(
            result.graph_paths[0].hops[0].cited_observation_hashes,
            (authorized_hashes[self.comment_56.observation_id],),
        )
        self.assertEqual(
            result.answer_citation_hashes,
            (authorized_hashes[self.comment_56.observation_id],),
        )

    def test_cross_issue_explicit_reference_is_source_authored_and_exactly_cited(
        self,
    ) -> None:
        session, graph, authorized_hashes = self._build(self.observations)
        node_ids = _observation_node_ids(graph.effective_graph_view.visible_nodes)
        reference_edges = [
            edge
            for edge in graph.effective_graph_view.visible_edges
            if edge.relation_type == GITHUB_REFERENCE_RELATION
            and edge.source_node_id == node_ids[self.issue_56.observation_id]
            and edge.target_node_id == node_ids[self.issue_51.observation_id]
        ]
        self.assertEqual(len(reference_edges), 1)
        self.assertEqual(
            reference_edges[0].properties["source_observation_ids"],
            [self.issue_56.observation_id],
        )
        self.assertTrue(reference_edges[0].properties["candidate_graph_only"])
        self.assertEqual(
            graph.relation_type_hashes,
            tuple(
                sorted(
                    (
                        sha256_json(CO_OCCURS_WITH),
                        sha256_json(GITHUB_REFERENCE_RELATION),
                    )
                )
            ),
        )

        result = session.query(
            query_text="What relationship records source native issue reference evidence?",
            effective_graph_view=graph.effective_graph_view,
            allowed_relation_types=(GITHUB_REFERENCE_RELATION,),
            seed_node_ids=(node_ids[self.issue_56.observation_id],),
        )
        self.assertEqual(result.status, "ok")
        self.assertTrue(result.graph_paths)
        self.assertEqual(
            result.graph_paths[0].hops[0].cited_observation_hashes,
            (authorized_hashes[self.issue_56.observation_id],),
        )
        self.assertEqual(
            result.answer_citation_hashes,
            (authorized_hashes[self.issue_56.observation_id],),
        )

    def test_denied_cross_project_bridge_is_rejected_before_graph_materialization(
        self,
    ) -> None:
        denied_target = _github_observation(
            observation_id="observation_github_reference_denied_target",
            project_scope_id=PROJECT_B,
            record_kind="issue_record",
            issue_number=51,
            source_local_key="source_local_github_reference_denied_target",
            text="Denied project target.",
            source_native_issue_references=(),
        )
        authorized_source = validated_authorized_semantic_source(
            source_kind=GITHUB_PROJECT_OBSERVATION_SOURCE_KIND,
            workspace_id=WORKSPACE_ID,
            source_scope_ids=(PROJECT_A,),
        )
        observations = (self.issue_56, denied_target)
        lineages = tuple(
            source_occurrence_lineage_from_observation(
                observation,
                authorized_source=authorized_source,
            )
            for observation in observations
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "permission scope mismatch",
        ):
            build_authorized_observation_snippet_index(
                observations,
                authorized_source=authorized_source,
                occurrence_lineages=lineages,
                authorized_observation_hash_by_id={
                    observation.observation_id: sha256_json(observation.to_dict())
                    for observation in observations
                },
                tokenizer_profile=self.profile,
            )

    def test_malformed_unknown_and_cross_project_targets_fail_closed(self) -> None:
        malformed = _github_observation(
            observation_id="observation_github_reference_malformed",
            project_scope_id=PROJECT_A,
            record_kind="issue_record",
            issue_number=56,
            source_local_key="source_local_github_reference_malformed",
            text="Malformed source reference fields.",
            source_native_issue_references=("51",),
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "fields are malformed",
        ):
            self._build((malformed, self.issue_51))

        unknown = _github_observation(
            observation_id="observation_github_reference_unknown",
            project_scope_id=PROJECT_A,
            record_kind="issue_record",
            issue_number=56,
            source_local_key="source_local_github_reference_unknown",
            text="Unknown source reference target.",
            source_native_issue_references=(404,),
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "target is unavailable",
        ):
            self._build((unknown,))

        other_project_target = _github_observation(
            observation_id="observation_github_reference_other_project_target",
            project_scope_id=PROJECT_B,
            record_kind="issue_record",
            issue_number=51,
            source_local_key="source_local_github_reference_other_project_target",
            text="Other project issue target.",
            source_native_issue_references=(),
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "crosses project scope",
        ):
            self._build(
                (self.issue_56, other_project_target),
                project_scope_ids=(PROJECT_A, PROJECT_B),
            )

    def test_determinism_and_unsupported_relation_are_fail_closed(self) -> None:
        first_session, first_graph, _ = self._build(self.observations)
        second_session, second_graph, _ = self._build(tuple(reversed(self.observations)))
        self.assertEqual(first_graph.to_safe_dict(), second_graph.to_safe_dict())
        self.assertEqual(
            [edge.to_dict() for edge in first_graph.effective_graph_view.visible_edges],
            [edge.to_dict() for edge in second_graph.effective_graph_view.visible_edges],
        )
        node_ids = _observation_node_ids(first_graph.effective_graph_view.visible_nodes)
        first = first_session.query(
            query_text="What relationship records source native issue reference evidence?",
            effective_graph_view=first_graph.effective_graph_view,
            allowed_relation_types=(GITHUB_REFERENCE_RELATION,),
            seed_node_ids=(node_ids[self.issue_56.observation_id],),
        )
        second = second_session.query(
            query_text="What relationship records source native issue reference evidence?",
            effective_graph_view=second_graph.effective_graph_view,
            allowed_relation_types=(GITHUB_REFERENCE_RELATION,),
            seed_node_ids=(node_ids[self.issue_56.observation_id],),
        )
        self.assertEqual(first.to_safe_dict(), second.to_safe_dict())

        unsupported = first_session.query(
            query_text="What relationship records source native issue reference evidence?",
            effective_graph_view=first_graph.effective_graph_view,
            allowed_relation_types=("unsupported_source_relation",),
            seed_node_ids=(node_ids[self.issue_56.observation_id],),
        )
        self.assertEqual(unsupported.status, "no_answer")
        self.assertEqual(unsupported.answer_citation_hashes, ())

    def test_mail_index_and_graph_fingerprints_are_unchanged(self) -> None:
        inputs = build_semantic_poc_inputs()
        with self._runtime_patch():
            session = build_authorized_semantic_mail_session(
                observations_by_bundle_id=inputs.observations_by_bundle_id,
                bundles=(inputs.current_bundle,),
                requester_user_id=MAIL_REQUESTER_ID,
                workspace_id=MAIL_WORKSPACE_ID,
            )
            graph = build_authorized_source_backed_effective_graph_view(
                session=session,
                observations_by_bundle_id=inputs.observations_by_bundle_id,
                source_binding_fingerprint="sha256:" + "a" * 64,
            )
        self.assertEqual(session.index.index_fingerprint, MAIL_INDEX_FINGERPRINT)
        self.assertEqual(graph.build_fingerprint, MAIL_GRAPH_BUILD_FINGERPRINT)
        self.assertEqual(
            graph.graph_revision_fingerprint,
            MAIL_GRAPH_REVISION_FINGERPRINT,
        )
        self.assertEqual(
            graph.relation_type_hashes,
            (sha256_json(CO_OCCURS_WITH),),
        )
        self.assertEqual(graph.edge_count, 14)


def _observation_node_ids(nodes) -> dict[str, str]:
    result: dict[str, str] = {}
    for node in nodes:
        if node.properties.get("node_kind") != "source_observation":
            continue
        observation_ids = node.properties.get("source_observation_ids")
        if isinstance(observation_ids, list) and len(observation_ids) == 1:
            result[str(observation_ids[0])] = node.node_id
    return result


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
