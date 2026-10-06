from __future__ import annotations

from copy import deepcopy
from collections import Counter
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from formowl_contract import (
    CandidateMention,
    ContractValidationError,
    assert_no_public_raw_references,
    sha256_json,
)
from formowl_mail import (
    build_authorized_semantic_mail_session,
    build_authorized_source_backed_effective_graph_view,
)
from formowl_mail import hybrid as hybrid_module
from formowl_mail.candidates import (
    SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT,
    SourceBoundIdentifierMentionBatch,
    SourceIdentifierIdentityScope,
    TENANT_WORKSPACE_IDENTITY_SCOPE_MODE,
    WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
    extract_source_bound_identifier_mentions,
)
from scripts.issue56_semantic_execution_smoke import (
    REQUESTER_USER_ID,
    WORKSPACE_ID,
    _build_bundle,
    _mail_observations,
)

_GRAPH_POLICY_V1 = "source_backed_mail_candidate_graph_v1"
_GRAPH_POLICY_V2 = "source_backed_mail_candidate_graph_v2"
_MENTION_RELATION = "mentions_identifier"
_COOCCURRENCE_RELATION = "co_occurs_with"
_TENANT_ID = "tenant_issue56_mentions_graph"
_MENTION_EXTRACTOR_RUN_ID = "extractor_issue56_mentions_graph"
_SOURCE_BINDING_FINGERPRINT = sha256_json("issue56_mentions_identifier_source_binding_v1")
_IDENTITY_SCOPE_POLICY_FINGERPRINT = sha256_json("issue56_identity_scope_policy_v3")
_OPERATOR_APPROVAL_FINGERPRINT = sha256_json("issue56_identity_scope_operator_approval_v3")
_SPEC_APPROVAL_FINGERPRINT = sha256_json("issue56_workspace_only_spec_approval_v1")


class Issue56MentionsIdentifierGraphEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.authorized_a = _occurrence_preserving_mail_observations(
            namespace="mentions_a",
            messages=(
                (
                    "識別碼",
                    "PO470002002 SUPPLIER-ALPHA-01 PO470002002",
                ),
            ),
        )
        cls.authorized_b = _occurrence_preserving_mail_observations(
            namespace="mentions_b",
            messages=(("識別碼", "PO470002002"),),
        )
        cls.denied = _occurrence_preserving_mail_observations(
            namespace="mentions_denied",
            messages=(("識別碼", "SECRET-PO-99001"),),
        )
        cls.authorized_a_bundle = _build_bundle(
            observations=cls.authorized_a,
            namespace="mentions_a",
            owner_user_id=REQUESTER_USER_ID,
        )
        cls.authorized_b_bundle = _build_bundle(
            observations=cls.authorized_b,
            namespace="mentions_b",
            owner_user_id=REQUESTER_USER_ID,
        )
        cls.denied_bundle = _build_bundle(
            observations=cls.denied,
            namespace="mentions_denied",
            owner_user_id="user_issue56_mentions_denied",
        )
        cls.observations_by_bundle_id = {
            cls.authorized_a_bundle.mail_evidence_bundle_id: cls.authorized_a,
            cls.authorized_b_bundle.mail_evidence_bundle_id: cls.authorized_b,
            cls.denied_bundle.mail_evidence_bundle_id: cls.denied,
        }
        cls.bundles = (
            cls.authorized_a_bundle,
            cls.authorized_b_bundle,
            cls.denied_bundle,
        )
        cls.session = build_authorized_semantic_mail_session(
            observations_by_bundle_id=cls.observations_by_bundle_id,
            bundles=cls.bundles,
            requester_user_id=REQUESTER_USER_ID,
            workspace_id=WORKSPACE_ID,
        )
        cls.tenant_identity_scope = _identity_scope(
            mode=TENANT_WORKSPACE_IDENTITY_SCOPE_MODE,
        )
        cls.batch = extract_source_bound_identifier_mentions(
            (
                *cls.authorized_a,
                *cls.authorized_b,
                *cls.denied,
            ),
            identity_scope=cls.tenant_identity_scope,
            extractor_run_id=_MENTION_EXTRACTOR_RUN_ID,
        )
        cls.workspace_identity_scope = _identity_scope(
            mode=WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
            tenant_id=None,
        )
        cls.workspace_batch = extract_source_bound_identifier_mentions(
            (
                *cls.authorized_a,
                *cls.authorized_b,
                *cls.denied,
            ),
            identity_scope=cls.workspace_identity_scope,
            extractor_run_id=_MENTION_EXTRACTOR_RUN_ID,
        )
        cls.authorized_observation_ids = frozenset(dict(cls.session.authorized_observation_hashes))
        cls.denied_observation_ids = frozenset(
            observation.observation_id for observation in cls.denied
        )
        authorized_a_body_hashes = Counter(
            mention.text_hash
            for mention in cls.batch.candidate_mentions
            if mention.source_observation_ids == ["obs_issue56_semantic_mentions_a_body_1"]
        )
        cls.repeated_identifier_hash = next(
            term_hash
            for term_hash, occurrence_count in authorized_a_body_hashes.items()
            if occurrence_count == 2
        )

    def test_v2_builds_one_scoped_occurrence_edge_and_filters_denied_before_resolution(
        self,
    ) -> None:
        original_resolver = hybrid_module.resolve_exact_protected_identifier_candidates
        with patch.object(
            hybrid_module,
            "resolve_exact_protected_identifier_candidates",
            wraps=original_resolver,
        ) as resolver:
            graph = self._build()

        resolved_mentions = tuple(resolver.call_args.args[0])
        self.assertEqual(len(resolved_mentions), 4)
        self.assertTrue(
            all(
                mention.source_observation_ids[0] in self.authorized_observation_ids
                for mention in resolved_mentions
            )
        )
        self.assertFalse(
            self.denied_observation_ids
            & {
                observation_id
                for mention in resolved_mentions
                for observation_id in mention.source_observation_ids
            }
        )

        mention_edges = [
            edge
            for edge in graph.effective_graph_view.visible_edges
            if edge.relation_type == _MENTION_RELATION
        ]
        self.assertEqual(len(mention_edges), 4)
        self.assertEqual(
            len({edge.edge_id for edge in mention_edges}),
            len(mention_edges),
        )
        self.assertTrue(
            all(
                edge.properties["source_observation_ids"][0] in self.authorized_observation_ids
                for edge in mention_edges
            )
        )
        self.assertFalse(
            self.denied_observation_ids
            & {
                observation_id
                for edge in graph.effective_graph_view.visible_edges
                for observation_id in edge.properties.get(
                    "source_observation_ids",
                    (),
                )
            }
        )

        repeated_edges = [
            edge
            for edge in mention_edges
            if edge.properties["protected_term_hashes"] == [self.repeated_identifier_hash]
            and edge.properties["source_observation_ids"]
            == ["obs_issue56_semantic_mentions_a_body_1"]
        ]
        self.assertEqual(len(repeated_edges), 2)
        self.assertEqual(
            len({edge.target_node_id for edge in repeated_edges}),
            1,
        )
        self.assertEqual(
            len({edge.properties["occurrence_scope_fingerprint"] for edge in repeated_edges}),
            2,
        )

    def test_identifier_identity_is_exact_and_permission_governed_scope_scoped(
        self,
    ) -> None:
        first = self._build()
        rerun = self._build()
        first_nodes = _identifier_nodes(first)
        repeated_nodes = [
            node
            for node in first_nodes
            if node.properties["protected_term_hashes"] == [self.repeated_identifier_hash]
        ]

        self.assertEqual(len(repeated_nodes), 2)
        self.assertEqual(
            len({node.properties["permission_boundary_fingerprint"] for node in repeated_nodes}),
            2,
        )
        self.assertEqual(
            len({node.properties["governed_scope_fingerprint"] for node in repeated_nodes}),
            1,
        )
        self.assertNotIn(
            repeated_nodes[1].node_id,
            _reachable_node_ids(
                first,
                start_node_id=repeated_nodes[0].node_id,
            ),
        )
        self.assertEqual(
            [node.to_dict() for node in first.effective_graph_view.visible_nodes],
            [node.to_dict() for node in rerun.effective_graph_view.visible_nodes],
        )
        self.assertEqual(
            [edge.to_dict() for edge in first.effective_graph_view.visible_edges],
            [edge.to_dict() for edge in rerun.effective_graph_view.visible_edges],
        )
        self.assertEqual(first.build_fingerprint, rerun.build_fingerprint)
        self.assertEqual(
            first.graph_revision_fingerprint,
            rerun.graph_revision_fingerprint,
        )

        other_scope = self._build(
            source_binding_fingerprint=sha256_json(
                "issue56_mentions_identifier_other_governed_scope"
            )
        )
        self.assertNotEqual(
            {node.node_id for node in first_nodes},
            {node.node_id for node in _identifier_nodes(other_scope)},
        )
        self.assertNotEqual(
            first.build_fingerprint,
            other_scope.build_fingerprint,
        )

    def test_v3_identity_modes_bind_every_graph_record_without_cross_scope_paths(
        self,
    ) -> None:
        tenant_graph = self._build()
        workspace_graph = self._build(batch=self.workspace_batch)
        tenant_safe = tenant_graph.to_safe_dict()
        workspace_safe = workspace_graph.to_safe_dict()

        self.assertEqual(
            tenant_safe["identity_scope_mode"],
            TENANT_WORKSPACE_IDENTITY_SCOPE_MODE,
        )
        self.assertEqual(
            workspace_safe["identity_scope_mode"],
            WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
        )
        self.assertEqual(
            workspace_safe["spec_approval_fingerprint"],
            self.workspace_identity_scope.spec_approval_fingerprint,
        )
        self.assertNotEqual(
            tenant_safe["identity_scope_graph_binding_fingerprint"],
            workspace_safe["identity_scope_graph_binding_fingerprint"],
        )
        self.assertNotEqual(
            tenant_graph.build_fingerprint,
            workspace_graph.build_fingerprint,
        )
        tenant_nodes = {node.node_id for node in tenant_graph.effective_graph_view.visible_nodes}
        workspace_nodes = {
            node.node_id for node in workspace_graph.effective_graph_view.visible_nodes
        }
        self.assertTrue(tenant_nodes.isdisjoint(workspace_nodes))

        for graph, identity_scope in (
            (tenant_graph, self.tenant_identity_scope),
            (workspace_graph, self.workspace_identity_scope),
        ):
            node_by_id = {node.node_id: node for node in graph.effective_graph_view.visible_nodes}
            for node in node_by_id.values():
                self.assertEqual(
                    node.properties["identity_scope_mode"],
                    identity_scope.identity_scope_mode,
                )
                self.assertEqual(
                    node.properties["identity_scope_fingerprint"],
                    identity_scope.identity_scope_fingerprint,
                )
                self.assertEqual(
                    node.properties["identity_scope_attestation_fingerprint"],
                    identity_scope.identity_scope_attestation_fingerprint,
                )
                self.assertEqual(
                    node.properties["operator_approval_fingerprint"],
                    identity_scope.operator_approval_fingerprint,
                )
            for edge in graph.effective_graph_view.visible_edges:
                self.assertEqual(
                    edge.properties["identity_scope_fingerprint"],
                    identity_scope.identity_scope_fingerprint,
                )
                self.assertEqual(
                    node_by_id[edge.source_node_id].properties["identity_scope_fingerprint"],
                    edge.properties["identity_scope_fingerprint"],
                )
                self.assertEqual(
                    node_by_id[edge.target_node_id].properties["identity_scope_fingerprint"],
                    edge.properties["identity_scope_fingerprint"],
                )

        workspace_serialized = json.dumps(
            {
                "build": workspace_safe,
                "nodes": [
                    node.to_dict() for node in workspace_graph.effective_graph_view.visible_nodes
                ],
                "edges": [
                    edge.to_dict() for edge in workspace_graph.effective_graph_view.visible_edges
                ],
            },
            sort_keys=True,
        )
        self.assertNotIn("tenant_id", workspace_serialized)
        self.assertNotIn(_TENANT_ID, workspace_serialized)

    def test_v3_attestation_and_approval_change_node_edge_and_build_identity(
        self,
    ) -> None:
        changed_scope = _identity_scope(
            mode=TENANT_WORKSPACE_IDENTITY_SCOPE_MODE,
            attestation_fingerprint=sha256_json("issue56_changed_identity_scope_attestation"),
            operator_approval_fingerprint=sha256_json("issue56_changed_operator_approval"),
        )
        changed_batch = extract_source_bound_identifier_mentions(
            (
                *self.authorized_a,
                *self.authorized_b,
                *self.denied,
            ),
            identity_scope=changed_scope,
            extractor_run_id=_MENTION_EXTRACTOR_RUN_ID,
        )
        baseline = self._build()
        changed = self._build(batch=changed_batch)

        self.assertNotEqual(
            {node.node_id for node in baseline.effective_graph_view.visible_nodes},
            {node.node_id for node in changed.effective_graph_view.visible_nodes},
        )
        self.assertNotEqual(
            {edge.edge_id for edge in baseline.effective_graph_view.visible_edges},
            {edge.edge_id for edge in changed.effective_graph_view.visible_edges},
        )
        self.assertNotEqual(
            baseline.build_fingerprint,
            changed.build_fingerprint,
        )

    def test_v2_safe_artifact_binds_mentions_resolution_and_relations_without_raw_values(
        self,
    ) -> None:
        graph = self._build()
        safe = graph.to_safe_dict()

        self.assertEqual(
            safe["artifact_id"],
            "formowl_issue56_source_backed_graph_build_v2",
        )
        self.assertEqual(safe["graph_policy_id"], _GRAPH_POLICY_V2)
        self.assertTrue(safe["candidate_graph_only"])
        self.assertFalse(safe["human_review_complete"])
        self.assertEqual(
            safe["identifier_mention_count"],
            self.batch.occurrence_count,
        )
        self.assertEqual(safe["authorized_identifier_mention_count"], 4)
        self.assertRegex(
            safe["complete_identifier_mention_fingerprint"],
            r"^sha256:[0-9a-f]{64}$",
        )
        self.assertRegex(
            safe["authorized_identifier_mention_fingerprint"],
            r"^sha256:[0-9a-f]{64}$",
        )
        self.assertRegex(
            safe["identifier_resolution_fingerprint"],
            r"^sha256:[0-9a-f]{64}$",
        )
        self.assertEqual(
            safe["identity_scope_mode"],
            TENANT_WORKSPACE_IDENTITY_SCOPE_MODE,
        )
        self.assertEqual(
            safe["identity_scope_fingerprint"],
            self.tenant_identity_scope.identity_scope_fingerprint,
        )
        self.assertEqual(
            safe["identity_scope_attestation_fingerprint"],
            self.tenant_identity_scope.identity_scope_attestation_fingerprint,
        )
        self.assertEqual(
            safe["operator_approval_fingerprint"],
            self.tenant_identity_scope.operator_approval_fingerprint,
        )
        self.assertNotIn("tenant_id", safe)
        self.assertEqual(
            set(safe["relation_type_hashes"]),
            {
                sha256_json(_MENTION_RELATION),
                sha256_json(_COOCCURRENCE_RELATION),
            },
        )

        internal_payload = {
            "build": safe,
            "nodes": [node.to_dict() for node in graph.effective_graph_view.visible_nodes],
            "edges": [edge.to_dict() for edge in graph.effective_graph_view.visible_edges],
        }
        assert_no_public_raw_references(
            internal_payload,
            "issue56_mentions_identifier_graph",
        )
        serialized = json.dumps(
            internal_payload,
            ensure_ascii=True,
            sort_keys=True,
        )
        for raw_value in (
            "PO470002002",
            "SUPPLIER-ALPHA-01",
            "SECRET-PO-99001",
            "archive_issue56_semantic_mentions_a",
            "mailbox_issue56_semantic_mentions_a",
        ):
            self.assertNotIn(raw_value, serialized)

    def test_v2_fails_closed_for_missing_profile_policy_count_order_seal_and_coverage(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ContractValidationError,
            "artifact is unavailable",
        ):
            self._build(batch=None, source_graph_policy_id=_GRAPH_POLICY_V2)
        with self.assertRaisesRegex(
            ContractValidationError,
            "v1 cannot consume",
        ):
            self._build(source_graph_policy_id=_GRAPH_POLICY_V1)

        cases = (
            (
                "profile",
                replace(
                    self.batch,
                    tokenizer_profile_fingerprint=sha256_json("mismatched_profile"),
                ),
                "tokenizer profile mismatch",
            ),
            (
                "policy",
                replace(
                    self.batch,
                    extraction_policy_id="unsupported_identifier_policy",
                ),
                "policy or workspace mismatch",
            ),
            (
                "count",
                replace(
                    self.batch,
                    occurrence_count=self.batch.occurrence_count + 1,
                ),
                "occurrence count mismatch",
            ),
            (
                "order",
                _batch_with_mentions(
                    self.batch,
                    tuple(reversed(self.batch.candidate_mentions)),
                ),
                "order mismatch",
            ),
            (
                "seal",
                replace(
                    self.batch,
                    batch_fingerprint=sha256_json("tampered_batch_seal"),
                ),
                "batch seal mismatch",
            ),
            (
                "missing_occurrence",
                _batch_with_mentions(
                    self.batch,
                    self.batch.candidate_mentions[:-1],
                ),
                "occurrence coverage mismatch",
            ),
        )
        for name, batch, reason in cases:
            with self.subTest(name=name):
                with self.assertRaisesRegex(ContractValidationError, reason):
                    self._build(batch=batch)

    def test_v2_fails_closed_for_legacy_raw_tenant_mention_schema(self) -> None:
        mention_index = next(
            index
            for index, mention in enumerate(self.batch.candidate_mentions)
            if mention.source_observation_ids == ["obs_issue56_semantic_mentions_a_body_1"]
        )

        def legacy_schema(payload) -> None:
            metadata = payload["metadata"]
            location = payload["location"]
            for field_name in (
                "identity_scope_mode",
                "identity_scope_fingerprint",
                "identity_scope_attestation_fingerprint",
                "identity_scope_policy_fingerprint",
                "operator_approval_fingerprint",
            ):
                metadata.pop(field_name, None)
                location.pop(field_name, None)
            legacy_fingerprint = sha256_json(
                {
                    "tenant_id": _TENANT_ID,
                    "workspace_id": WORKSPACE_ID,
                }
            )
            metadata["tenant_workspace_fingerprint"] = legacy_fingerprint
            location["tenant_workspace_fingerprint"] = legacy_fingerprint

        legacy_batch = _batch_with_mutated_mention(
            self.batch,
            mention_index=mention_index,
            mutate=legacy_schema,
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "legacy raw tenant schema is unsupported",
        ):
            self._build(batch=legacy_batch)

    def test_v2_fails_closed_for_identifier_occurrence_lineage_tamper(
        self,
    ) -> None:
        mention_index = next(
            index
            for index, mention in enumerate(self.batch.candidate_mentions)
            if mention.source_observation_ids == ["obs_issue56_semantic_mentions_a_body_1"]
        )
        cases = (
            (
                "id",
                lambda payload: payload.__setitem__(
                    "candidate_mention_id",
                    "cmnt_issue56_mentions_tampered",
                ),
                "mention identity mismatch",
            ),
            (
                "observation",
                lambda payload: payload["metadata"].__setitem__(
                    "source_observation_fingerprint",
                    sha256_json("different_observation"),
                ),
                "Observation fingerprint mismatch",
            ),
            (
                "message",
                lambda payload: payload["metadata"].__setitem__(
                    "message_occurrence_fingerprint",
                    sha256_json("different_message_occurrence"),
                ),
                "source occurrence binding mismatch",
            ),
            (
                "span",
                lambda payload: payload["location"].__setitem__(
                    "span_start",
                    payload["location"]["span_start"] + 1,
                ),
                "occurrence fingerprint mismatch",
            ),
            (
                "token",
                lambda payload: payload.__setitem__(
                    "text_hash",
                    sha256_json("different_identifier"),
                ),
                "exact hash mismatch",
            ),
            (
                "provenance",
                lambda payload: payload["metadata"].__setitem__(
                    "source_extractor_provenance_fingerprint",
                    sha256_json("different_provenance"),
                ),
                "provenance binding mismatch",
            ),
            (
                "permission",
                lambda payload: payload["metadata"].__setitem__(
                    "permission_scope",
                    {
                        "scope_type": "project",
                        "visibility": "restricted",
                        "scope_id": "different_scope",
                    },
                ),
                "permission binding mismatch",
            ),
            (
                "attestation",
                lambda payload: payload["metadata"].__setitem__(
                    "identity_scope_attestation_fingerprint",
                    sha256_json("different_identity_scope_attestation"),
                ),
                "identity scope binding mismatch",
            ),
            (
                "approval",
                lambda payload: payload["location"].__setitem__(
                    "operator_approval_fingerprint",
                    sha256_json("different_operator_approval"),
                ),
                "occurrence location mismatch",
            ),
        )
        for name, mutate, reason in cases:
            with self.subTest(name=name):
                batch = _batch_with_mutated_mention(
                    self.batch,
                    mention_index=mention_index,
                    mutate=mutate,
                )
                with self.assertRaisesRegex(ContractValidationError, reason):
                    self._build(batch=batch)

    def test_v2_fails_closed_when_authorized_observation_snapshot_mutates(self) -> None:
        changed_observations = dict(self.observations_by_bundle_id)
        authorized_items = list(
            changed_observations[self.authorized_a_bundle.mail_evidence_bundle_id]
        )
        body_index = next(
            index
            for index, observation in enumerate(authorized_items)
            if observation.observation_id == "obs_issue56_semantic_mentions_a_body_1"
        )
        authorized_items[body_index] = replace(
            authorized_items[body_index],
            text="PO470002002 changed",
        )
        changed_observations[self.authorized_a_bundle.mail_evidence_bundle_id] = tuple(
            authorized_items
        )

        with self.assertRaisesRegex(
            ContractValidationError,
            "Observation (?:lineage|fingerprint) mismatch",
        ):
            build_authorized_source_backed_effective_graph_view(
                session=self.session,
                observations_by_bundle_id=changed_observations,
                source_binding_fingerprint=_SOURCE_BINDING_FINGERPRINT,
                identifier_mention_batch=self.batch,
            )

    def _build(
        self,
        *,
        batch: SourceBoundIdentifierMentionBatch | None | object = ...,
        source_graph_policy_id: str | None = None,
        source_binding_fingerprint: str = _SOURCE_BINDING_FINGERPRINT,
    ):
        resolved_batch = self.batch if batch is ... else batch
        return build_authorized_source_backed_effective_graph_view(
            session=self.session,
            observations_by_bundle_id=self.observations_by_bundle_id,
            source_binding_fingerprint=source_binding_fingerprint,
            identifier_mention_batch=resolved_batch,
            source_graph_policy_id=source_graph_policy_id,
        )


def _occurrence_preserving_mail_observations(
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


def _identifier_nodes(graph):
    return [
        node
        for node in graph.effective_graph_view.visible_nodes
        if node.properties.get("node_kind") == "candidate_identifier"
    ]


def _reachable_node_ids(graph, *, start_node_id: str) -> set[str]:
    adjacency: dict[str, set[str]] = {}
    for edge in graph.effective_graph_view.visible_edges:
        adjacency.setdefault(edge.source_node_id, set()).add(edge.target_node_id)
        adjacency.setdefault(edge.target_node_id, set()).add(edge.source_node_id)
    reached = {start_node_id}
    pending = [start_node_id]
    while pending:
        node_id = pending.pop()
        for adjacent_id in adjacency.get(node_id, set()):
            if adjacent_id in reached:
                continue
            reached.add(adjacent_id)
            pending.append(adjacent_id)
    reached.remove(start_node_id)
    return reached


def _identity_scope(
    *,
    mode: str,
    tenant_id: str | None = _TENANT_ID,
    workspace_id: str = WORKSPACE_ID,
    attestation_fingerprint: str | None = None,
    operator_approval_fingerprint: str = _OPERATOR_APPROVAL_FINGERPRINT,
    spec_approval_fingerprint: str | None = None,
) -> SourceIdentifierIdentityScope:
    scope_payload = {
        "mode": mode,
        "workspace_id": workspace_id,
    }
    if mode == TENANT_WORKSPACE_IDENTITY_SCOPE_MODE:
        scope_payload["tenant_id"] = tenant_id
    return SourceIdentifierIdentityScope(
        identity_scope_mode=mode,
        identity_scope_fingerprint=sha256_json(scope_payload),
        workspace_id=workspace_id,
        identity_scope_attestation_fingerprint=(
            attestation_fingerprint
            or sha256_json(
                {
                    "scope": scope_payload,
                    "attestation": "issue56_mentions_identifier_graph_v3",
                }
            )
        ),
        identity_scope_policy_fingerprint=(_IDENTITY_SCOPE_POLICY_FINGERPRINT),
        operator_approval_fingerprint=operator_approval_fingerprint,
        tenant_id=tenant_id,
        spec_approval_fingerprint=(
            spec_approval_fingerprint or _SPEC_APPROVAL_FINGERPRINT
            if mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
            else None
        ),
    )


def _batch_identity_scope_dict(
    batch: SourceBoundIdentifierMentionBatch,
) -> dict[str, str]:
    return SourceIdentifierIdentityScope(
        identity_scope_mode=batch.identity_scope_mode,
        identity_scope_fingerprint=batch.identity_scope_fingerprint,
        workspace_id=batch.workspace_id,
        identity_scope_attestation_fingerprint=(batch.identity_scope_attestation_fingerprint),
        identity_scope_policy_fingerprint=(batch.identity_scope_policy_fingerprint),
        operator_approval_fingerprint=batch.operator_approval_fingerprint,
        tenant_id=batch.tenant_id,
        spec_approval_fingerprint=batch.spec_approval_fingerprint,
    ).to_dict()


def _batch_with_mentions(
    batch: SourceBoundIdentifierMentionBatch,
    mentions: tuple[CandidateMention, ...],
) -> SourceBoundIdentifierMentionBatch:
    mention_ids = [mention.candidate_mention_id for mention in mentions]
    return replace(
        batch,
        candidate_mentions=mentions,
        occurrence_count=len(mentions),
        batch_fingerprint=sha256_json(
            {
                "candidate_mention_ids": mention_ids,
                "extraction_policy_fingerprint": (
                    SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT
                ),
                "identity_scope": _batch_identity_scope_dict(batch),
                "tokenizer_profile_fingerprint": (batch.tokenizer_profile_fingerprint),
            }
        ),
    )


def _batch_with_mutated_mention(
    batch: SourceBoundIdentifierMentionBatch,
    *,
    mention_index: int,
    mutate,
) -> SourceBoundIdentifierMentionBatch:
    mentions = list(batch.candidate_mentions)
    payload = deepcopy(mentions[mention_index].to_dict())
    mutate(payload)
    mentions[mention_index] = CandidateMention.from_dict(payload)
    mentions.sort(key=lambda mention: mention.candidate_mention_id)
    return _batch_with_mentions(batch, tuple(mentions))


if __name__ == "__main__":
    unittest.main()
