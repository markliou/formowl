from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, Grant, PermissionScope
from formowl_graph.index import (
    FileGraphProjectionStore,
    FileVectorStore,
    GraphProjectionEdge,
    GraphProjectionNode,
    VectorRecord,
)

NOW = "2026-06-18T00:00:00+00:00"


class GraphIndexStoreTests(unittest.TestCase):
    def test_vector_search_filters_ready_and_stale_records_by_permission(self) -> None:
        temp_dir = _paths.fresh_test_dir("graph-index-vectors-permission")
        store = FileVectorStore(temp_dir)
        allowed_scope = PermissionScope.project("project_formowl").to_dict()
        denied_scope = PermissionScope.project("project_private").to_dict()

        store.create(
            _vector_record(
                vector_id="vec_ready_allowed",
                source_id="obs_ready_allowed",
                embedding=[1.0, 0.0],
                permission_scope=allowed_scope,
                index_state="ready",
            )
        )
        store.create(
            _vector_record(
                vector_id="vec_stale_allowed",
                source_id="obs_stale_allowed",
                embedding=[0.9, 0.1],
                permission_scope=allowed_scope,
                index_state="stale",
            )
        )
        store.create(
            _vector_record(
                vector_id="vec_stale_denied",
                source_id="obs_stale_denied",
                embedding=[0.99, 0.01],
                permission_scope=denied_scope,
                index_state="stale",
            )
        )

        grant = _project_grant("project_formowl")
        without_stale = store.search(
            [1.0, 0.0],
            requester_user_id="user_yifan",
            grants=[grant],
            allow_stale=False,
            now=NOW,
        )
        self.assertEqual(
            [result.record.vector_id for result in without_stale], ["vec_ready_allowed"]
        )
        self.assertFalse(without_stale[0].stale)

        with_stale = store.search(
            [1.0, 0.0],
            requester_user_id="user_yifan",
            grants=[grant],
            allow_stale=True,
            now=NOW,
        )
        self.assertEqual(
            {result.record.vector_id for result in with_stale},
            {"vec_ready_allowed", "vec_stale_allowed"},
        )
        self.assertTrue(
            next(
                result for result in with_stale if result.record.vector_id == "vec_stale_allowed"
            ).stale
        )
        self.assertNotIn(
            "vec_stale_denied",
            {result.record.vector_id for result in with_stale},
        )

        no_grant_results = store.search(
            [1.0, 0.0],
            requester_user_id="user_yifan",
            grants=[],
            allow_stale=True,
            now=NOW,
        )
        self.assertEqual(no_grant_results, [])

        invalid_grants = [
            _project_grant("project_formowl", revoked_at=NOW),
            _project_grant("project_formowl", expires_at=NOW),
            _project_grant("project_formowl", grantee_user_id="user_other"),
            _project_grant("project_formowl", permission="raw_asset_admin"),
        ]
        for invalid_grant in invalid_grants:
            with self.subTest(grant=invalid_grant):
                self.assertEqual(
                    store.search(
                        [1.0, 0.0],
                        requester_user_id="user_yifan",
                        grants=[invalid_grant],
                        allow_stale=True,
                        now=NOW,
                    ),
                    [],
                )

    def test_grant_based_access_requires_current_time_for_expiration_checks(self) -> None:
        temp_dir = _paths.fresh_test_dir("graph-index-requires-now")
        vector_store = FileVectorStore(temp_dir)
        projection_store = FileGraphProjectionStore(temp_dir)
        permission_scope = PermissionScope.project("project_formowl").to_dict()
        grant = _project_grant("project_formowl")
        vector_store.create(
            _vector_record(
                vector_id="vec_stale",
                source_id="obs_stale",
                embedding=[1.0, 0.0],
                permission_scope=permission_scope,
                index_state="stale",
            )
        )
        projection_store.create_node(
            _projection_node("node_visible", "catom_visible", permission_scope)
        )

        with self.assertRaises(ContractValidationError):
            vector_store.search(
                [1.0, 0.0],
                requester_user_id="user_yifan",
                grants=[grant],
                allow_stale=True,
            )
        with self.assertRaises(ContractValidationError):
            projection_store.visible_nodes(requester_user_id="user_yifan", grants=[grant])
        with self.assertRaises(ContractValidationError):
            projection_store.neighbors(
                "node_visible", requester_user_id="user_yifan", grants=[grant]
            )

    def test_vector_store_persists_records_and_marks_source_vectors_stale(self) -> None:
        temp_dir = _paths.fresh_test_dir("graph-index-vectors-restart")
        store = FileVectorStore(temp_dir)
        record = _vector_record(
            vector_id="vec_obs_001",
            source_id="obs_001",
            embedding=[0.25, 0.75],
            permission_scope=PermissionScope.project("project_formowl").to_dict(),
        )

        self.assertEqual(store.create(record).to_dict(), record.to_dict())
        stale_records = store.mark_stale_for_source(
            source_type="observation",
            source_id="obs_001",
            reason="source permission changed",
        )

        self.assertEqual(len(stale_records), 1)
        self.assertEqual(stale_records[0].index_state, "stale")
        self.assertEqual(stale_records[0].metadata["stale_reason"], "source permission changed")

        restarted = FileVectorStore(temp_dir)
        restarted_record = restarted.get("vec_obs_001")
        self.assertIsNotNone(restarted_record)
        self.assertEqual(restarted_record.index_state, "stale")
        self.assertEqual(restarted_record.permission_scope, record.permission_scope)
        self.assertEqual(restarted_record.source_content_hash, record.source_content_hash)
        self.assertEqual([item.vector_id for item in restarted.list()], ["vec_obs_001"])
        restarted_results = restarted.search(
            [0.25, 0.75],
            requester_user_id="user_yifan",
            grants=[_project_grant("project_formowl")],
            allow_stale=True,
            now=NOW,
        )
        self.assertEqual([result.record.vector_id for result in restarted_results], ["vec_obs_001"])
        self.assertTrue(restarted_results[0].stale)
        self.assertEqual(
            restarted.search(
                [0.25, 0.75],
                requester_user_id="user_yifan",
                grants=[],
                allow_stale=True,
                now=NOW,
            ),
            [],
        )
        self.assertTrue((temp_dir / "graph" / "index" / "vectors" / "vec_obs_001.json").exists())
        self.assertFalse((temp_dir / "graph" / "vectors").exists())
        self.assertFalse((temp_dir / "graph" / "canonical").exists())

    def test_vector_store_rejects_invalid_payloads_without_partial_writes(self) -> None:
        temp_dir = _paths.fresh_test_dir("graph-index-vectors-invalid")
        store = FileVectorStore(temp_dir)
        valid_record = _vector_record(
            vector_id="vec_valid",
            source_id="obs_valid",
            embedding=[1.0, 0.0],
            permission_scope=PermissionScope.project("project_formowl").to_dict(),
        )
        store.create(valid_record)

        invalid_embedding = valid_record.to_dict()
        invalid_embedding["vector_id"] = "vec_invalid_embedding"
        invalid_embedding["embedding"] = [True, 0.0]
        invalid_source_payloads = []
        for index, source_id in enumerate(
            [
                "/tmp/raw/path.txt",
                "tmp/raw.txt",
                "tmp\\raw.txt",
                "smb://nas/share/file.txt",
                "s3://bucket/key",
            ],
            start=1,
        ):
            invalid_source = valid_record.to_dict()
            invalid_source["vector_id"] = f"vec_invalid_source_{index}"
            invalid_source["source_id"] = source_id
            invalid_source_payloads.append(invalid_source)
        invalid_metadata_nan = valid_record.to_dict()
        invalid_metadata_nan["vector_id"] = "vec_invalid_metadata_nan"
        invalid_metadata_nan["metadata"] = {"score": float("nan")}
        invalid_metadata_raw_locator = valid_record.to_dict()
        invalid_metadata_raw_locator["vector_id"] = "vec_invalid_metadata_raw_locator"
        invalid_metadata_raw_locator["metadata"] = {"source": "smb://nas/share/file.txt"}
        invalid_metadata_raw_key = valid_record.to_dict()
        invalid_metadata_raw_key["vector_id"] = "vec_invalid_metadata_raw_key"
        invalid_metadata_raw_key["metadata"] = {"smb://nas/share/file.txt": "source"}
        invalid_metadata_non_string_key = valid_record.to_dict()
        invalid_metadata_non_string_key["vector_id"] = "vec_invalid_metadata_non_string_key"
        invalid_metadata_non_string_key["metadata"] = {1: "source"}
        invalid_metadata_nested_non_string_key = valid_record.to_dict()
        invalid_metadata_nested_non_string_key["vector_id"] = "vec_invalid_metadata_nested_key"
        invalid_metadata_nested_non_string_key["metadata"] = {"outer": {1: "source"}}
        invalid_metadata_tuple_raw_locator = valid_record.to_dict()
        invalid_metadata_tuple_raw_locator["vector_id"] = "vec_invalid_metadata_tuple"
        invalid_metadata_tuple_raw_locator["metadata"] = {
            "paths": ("smb://nas/share/file.txt",),
        }
        unsafe_id_payloads = []
        for unsafe_vector_id in _unsafe_index_ids("vec"):
            unsafe_id = valid_record.to_dict()
            unsafe_id["vector_id"] = unsafe_vector_id
            unsafe_id_payloads.append(unsafe_id)
        before_invalid_state = _tree_state(temp_dir)

        with self.assertRaises(ContractValidationError):
            store.create(invalid_embedding)
        for invalid_source in invalid_source_payloads:
            with self.subTest(source_id=invalid_source["source_id"]):
                with self.assertRaises(ContractValidationError):
                    store.create(invalid_source)
        with self.assertRaises(ContractValidationError):
            store.create(invalid_metadata_nan)
        with self.assertRaises(ContractValidationError):
            store.create(invalid_metadata_raw_locator)
        with self.assertRaises(ContractValidationError):
            store.create(invalid_metadata_raw_key)
        with self.assertRaises(ContractValidationError):
            store.create(invalid_metadata_non_string_key)
        with self.assertRaises(ContractValidationError):
            store.create(invalid_metadata_nested_non_string_key)
        with self.assertRaises(ContractValidationError):
            store.create(invalid_metadata_tuple_raw_locator)
        for unsafe_id in unsafe_id_payloads:
            with self.subTest(vector_id=unsafe_id["vector_id"]):
                with self.assertRaises(ValueError):
                    store.create(unsafe_id)

        self.assertEqual([record.vector_id for record in store.list()], ["vec_valid"])
        self.assertEqual(_tree_state(temp_dir), before_invalid_state)

    def test_graph_projection_store_filters_nodes_and_edges_by_permission(self) -> None:
        temp_dir = _paths.fresh_test_dir("graph-index-projection-permission")
        store = FileGraphProjectionStore(temp_dir)
        allowed_scope = PermissionScope.project("project_formowl").to_dict()
        denied_scope = PermissionScope.project("project_private").to_dict()
        allowed_a = _projection_node("node_allowed_a", "catom_allowed_a", allowed_scope)
        allowed_b = _projection_node("node_allowed_b", "catom_allowed_b", allowed_scope)
        denied = _projection_node("node_denied", "catom_denied", denied_scope)

        store.create_node(allowed_a)
        store.create_node(allowed_b)
        store.create_node(denied)
        store.create_edge(
            _projection_edge("edge_allowed", allowed_a.node_id, allowed_b.node_id, allowed_scope)
        )
        store.create_edge(
            _projection_edge(
                "edge_allowed_nodes_denied_scope",
                allowed_a.node_id,
                allowed_b.node_id,
                denied_scope,
            )
        )
        store.create_edge(
            _projection_edge("edge_denied_node", allowed_a.node_id, denied.node_id, allowed_scope)
        )

        grant = _project_grant("project_formowl")
        self.assertEqual(
            [
                node.node_id
                for node in store.visible_nodes(
                    requester_user_id="user_yifan",
                    grants=[grant],
                    now=NOW,
                )
            ],
            ["node_allowed_a", "node_allowed_b"],
        )
        self.assertEqual(
            [
                edge.edge_id
                for edge in store.neighbors(
                    "node_allowed_a",
                    requester_user_id="user_yifan",
                    grants=[grant],
                    now=NOW,
                )
            ],
            ["edge_allowed"],
        )
        self.assertEqual(
            store.neighbors("node_denied", requester_user_id="user_yifan", grants=[grant], now=NOW),
            [],
        )
        self.assertEqual(store.visible_nodes(requester_user_id="user_yifan", grants=[]), [])
        self.assertEqual(
            store.neighbors("node_allowed_a", requester_user_id="user_yifan", grants=[]),
            [],
        )

        restarted = FileGraphProjectionStore(temp_dir)
        self.assertEqual(
            [
                node.node_id
                for node in restarted.visible_nodes(
                    requester_user_id="user_yifan",
                    grants=[grant],
                    now=NOW,
                )
            ],
            ["node_allowed_a", "node_allowed_b"],
        )
        self.assertEqual(
            [
                edge.edge_id
                for edge in restarted.neighbors(
                    "node_allowed_a",
                    requester_user_id="user_yifan",
                    grants=[grant],
                    now=NOW,
                )
            ],
            ["edge_allowed"],
        )
        self.assertEqual(
            [node.node_id for node in restarted.list_nodes()],
            [
                "node_allowed_a",
                "node_allowed_b",
                "node_denied",
            ],
        )
        self.assertEqual(
            [edge.edge_id for edge in restarted.list_edges()],
            ["edge_allowed", "edge_allowed_nodes_denied_scope", "edge_denied_node"],
        )

        graph_root = temp_dir / "graph"
        directory_names = {child.name for child in graph_root.iterdir() if child.is_dir()}
        self.assertEqual(directory_names, {"index"})
        self.assertFalse(any("canonical" in name for name in directory_names))

    def test_graph_projection_stale_and_dangling_records_still_filter_by_permission(self) -> None:
        temp_dir = _paths.fresh_test_dir("graph-index-projection-stale")
        store = FileGraphProjectionStore(temp_dir)
        allowed_scope = PermissionScope.project("project_formowl").to_dict()
        denied_scope = PermissionScope.project("project_private").to_dict()
        ready_node = _projection_node("node_ready", "catom_ready", allowed_scope)
        stale_node = _projection_node(
            "node_stale",
            "catom_stale",
            allowed_scope,
            projection_state="stale",
        )
        denied_stale_node = _projection_node(
            "node_denied_stale",
            "catom_denied_stale",
            denied_scope,
            projection_state="stale",
        )

        store.create_node(ready_node)
        store.create_node(stale_node)
        store.create_node(denied_stale_node)
        store.create_edge(
            _projection_edge(
                "edge_stale_allowed",
                ready_node.node_id,
                stale_node.node_id,
                allowed_scope,
                projection_state="stale",
            )
        )
        store.create_edge(
            _projection_edge(
                "edge_stale_denied",
                ready_node.node_id,
                stale_node.node_id,
                denied_scope,
                projection_state="stale",
            )
        )
        store.create_edge(
            _projection_edge("edge_dangling", ready_node.node_id, "node_missing", allowed_scope)
        )

        grant = _project_grant("project_formowl")
        self.assertEqual(
            [
                node.node_id
                for node in store.visible_nodes(
                    requester_user_id="user_yifan",
                    grants=[grant],
                    allow_stale=False,
                    now=NOW,
                )
            ],
            ["node_ready"],
        )
        self.assertEqual(
            store.neighbors(
                "node_ready",
                requester_user_id="user_yifan",
                grants=[grant],
                allow_stale=False,
                now=NOW,
            ),
            [],
        )
        self.assertEqual(
            [
                node.node_id
                for node in store.visible_nodes(
                    requester_user_id="user_yifan",
                    grants=[grant],
                    allow_stale=True,
                    now=NOW,
                )
            ],
            ["node_ready", "node_stale"],
        )
        self.assertEqual(
            [
                edge.edge_id
                for edge in store.neighbors(
                    "node_ready",
                    requester_user_id="user_yifan",
                    grants=[grant],
                    allow_stale=True,
                    now=NOW,
                )
            ],
            ["edge_stale_allowed"],
        )
        self.assertEqual(
            store.neighbors(
                "node_missing",
                requester_user_id="user_yifan",
                grants=[grant],
                allow_stale=True,
                now=NOW,
            ),
            [],
        )

    def test_graph_projection_rejects_invalid_payloads_without_partial_writes(self) -> None:
        temp_dir = _paths.fresh_test_dir("graph-index-projection-invalid")
        store = FileGraphProjectionStore(temp_dir)
        permission_scope = PermissionScope.project("project_formowl").to_dict()
        invalid_node_source = _projection_node(
            "node_invalid_source",
            "internal/share/file.txt",
            permission_scope,
        )
        invalid_node_properties = _projection_node(
            "node_invalid_properties",
            "catom_invalid_properties",
            permission_scope,
        ).to_dict()
        invalid_node_properties["properties"] = {"weight": float("inf")}
        invalid_node_property_key = _projection_node(
            "node_invalid_property_key",
            "catom_invalid_property_key",
            permission_scope,
        ).to_dict()
        invalid_node_property_key["properties"] = {"/tmp/raw.txt": "label"}
        invalid_node_property_non_string_key = _projection_node(
            "node_invalid_property_non_string_key",
            "catom_invalid_property_non_string_key",
            permission_scope,
        ).to_dict()
        invalid_node_property_non_string_key["properties"] = {1: "label"}
        invalid_node_property_tuple = _projection_node(
            "node_invalid_property_tuple",
            "catom_invalid_property_tuple",
            permission_scope,
        ).to_dict()
        invalid_node_property_tuple["properties"] = {
            "paths": ("smb://nas/share/file.txt",),
        }
        invalid_node_label = _projection_node(
            "node_invalid_label",
            "catom_invalid_label",
            permission_scope,
        ).to_dict()
        invalid_node_label["labels"] = ["smb://nas/share/file.txt"]
        invalid_edge_properties = _projection_edge(
            "edge_invalid_properties",
            "node_left",
            "node_right",
            permission_scope,
        ).to_dict()
        invalid_edge_properties["properties"] = {"source": "object://bucket/key"}
        invalid_edge_property_key = _projection_edge(
            "edge_invalid_property_key",
            "node_left",
            "node_right",
            permission_scope,
        ).to_dict()
        invalid_edge_property_key["properties"] = {"s3://bucket/key": "source"}
        invalid_edge_property_non_string_key = _projection_edge(
            "edge_invalid_property_non_string_key",
            "node_left",
            "node_right",
            permission_scope,
        ).to_dict()
        invalid_edge_property_non_string_key["properties"] = {1: "source"}
        invalid_edge_property_tuple = _projection_edge(
            "edge_invalid_property_tuple",
            "node_left",
            "node_right",
            permission_scope,
        ).to_dict()
        invalid_edge_property_tuple["properties"] = {
            "paths": ("smb://nas/share/file.txt",),
        }
        invalid_edge_relation_type = _projection_edge(
            "edge_invalid_relation_type",
            "node_left",
            "node_right",
            permission_scope,
        ).to_dict()
        invalid_edge_relation_type["relation_type"] = "s3://bucket/key"
        invalid_node_id_payloads = []
        for unsafe_node_id in _unsafe_index_ids("node"):
            invalid_node_id_payloads.append(
                _projection_node(
                    unsafe_node_id,
                    "catom_invalid_node_id",
                    permission_scope,
                )
            )
        invalid_edge_id_payloads = []
        for unsafe_edge_id in _unsafe_index_ids("edge"):
            invalid_edge_id_payloads.append(
                _projection_edge(
                    unsafe_edge_id,
                    "node_left",
                    "node_right",
                    permission_scope,
                )
            )
        invalid_edge_endpoint_payloads = []
        for index, unsafe_endpoint_id in enumerate(_unsafe_index_ids("endpoint"), start=1):
            invalid_edge_endpoint_payloads.append(
                _projection_edge(
                    f"edge_invalid_source_endpoint_{index}",
                    unsafe_endpoint_id,
                    "node_right",
                    permission_scope,
                )
            )
            invalid_edge_endpoint_payloads.append(
                _projection_edge(
                    f"edge_invalid_target_endpoint_{index}",
                    "node_left",
                    unsafe_endpoint_id,
                    permission_scope,
                )
            )
        before_invalid_state = _tree_state(temp_dir)

        with self.assertRaises(ContractValidationError):
            store.create_node(invalid_node_source)
        with self.assertRaises(ContractValidationError):
            store.create_node(invalid_node_properties)
        with self.assertRaises(ContractValidationError):
            store.create_node(invalid_node_property_key)
        with self.assertRaises(ContractValidationError):
            store.create_node(invalid_node_property_non_string_key)
        with self.assertRaises(ContractValidationError):
            store.create_node(invalid_node_property_tuple)
        with self.assertRaises(ContractValidationError):
            store.create_node(invalid_node_label)
        with self.assertRaises(ContractValidationError):
            store.create_edge(invalid_edge_properties)
        with self.assertRaises(ContractValidationError):
            store.create_edge(invalid_edge_property_key)
        with self.assertRaises(ContractValidationError):
            store.create_edge(invalid_edge_property_non_string_key)
        with self.assertRaises(ContractValidationError):
            store.create_edge(invalid_edge_property_tuple)
        with self.assertRaises(ContractValidationError):
            store.create_edge(invalid_edge_relation_type)
        for invalid_node in invalid_node_id_payloads:
            with self.subTest(node_id=invalid_node.node_id):
                with self.assertRaises(ValueError):
                    store.create_node(invalid_node)
        for invalid_edge in invalid_edge_id_payloads:
            with self.subTest(edge_id=invalid_edge.edge_id):
                with self.assertRaises(ValueError):
                    store.create_edge(invalid_edge)
        for invalid_edge in invalid_edge_endpoint_payloads:
            with self.subTest(edge_id=invalid_edge.edge_id):
                with self.assertRaises(ValueError):
                    store.create_edge(invalid_edge)

        self.assertEqual(store.list_nodes(), [])
        self.assertEqual(store.list_edges(), [])
        projection_root = temp_dir / "graph" / "index" / "graph-projections"
        self.assertEqual(list(projection_root.rglob("*.json")), [])
        self.assertEqual(list(projection_root.rglob("*.tmp")), [])
        self.assertEqual(_tree_state(temp_dir), before_invalid_state)


def _vector_record(
    *,
    vector_id: str,
    source_id: str,
    embedding: list[float],
    permission_scope: dict[str, object],
    index_state: str = "ready",
) -> VectorRecord:
    return VectorRecord(
        vector_id=vector_id,
        source_type="observation",
        source_id=source_id,
        source_content_hash=f"sha256:{source_id}",
        embedding_model="fixture-embedding-v1",
        embedding=embedding,
        permission_scope=permission_scope,
        index_state=index_state,
        metadata={"source_kind": "test"},
        created_at="2026-06-18T00:00:00+00:00",
    )


def _projection_node(
    node_id: str,
    source_id: str,
    permission_scope: dict[str, object],
    projection_state: str = "ready",
) -> GraphProjectionNode:
    return GraphProjectionNode(
        node_id=node_id,
        source_type="candidate_atom",
        source_id=source_id,
        labels=["CandidateAtom"],
        properties={"label": source_id},
        permission_scope=permission_scope,
        projection_state=projection_state,
    )


def _projection_edge(
    edge_id: str,
    source_node_id: str,
    target_node_id: str,
    permission_scope: dict[str, object],
    projection_state: str = "ready",
) -> GraphProjectionEdge:
    return GraphProjectionEdge(
        edge_id=edge_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        relation_type="related_to",
        properties={"basis": "candidate relation projection"},
        permission_scope=permission_scope,
        projection_state=projection_state,
    )


def _project_grant(
    project_id: str,
    *,
    grantee_user_id: str = "user_yifan",
    permission: str = "graph_snippet",
    expires_at: str = "2026-06-19T00:00:00+00:00",
    revoked_at: str | None = None,
) -> Grant:
    return Grant(
        grant_id=f"grant_{project_id}",
        owner_user_id="user_owner",
        grantee_user_id=grantee_user_id,
        scope_type="project",
        scope_id=project_id,
        permission=permission,
        expires_at=expires_at,
        revoked_at=revoked_at,
    )


def _unsafe_index_ids(prefix: str) -> tuple[str, ...]:
    return (
        ".",
        "..",
        ".hidden",
        "-hidden",
        "_hidden",
        "+hidden",
        f"../{prefix}",
        rf"..\{prefix}",
        f"{prefix}/path",
        rf"{prefix}\path",
    )


def _tree_state(root) -> dict[str, str]:
    if not root.exists():
        return {}
    state: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative_path = path.relative_to(root).as_posix()
        if path.is_dir():
            state[f"{relative_path}/"] = "<dir>"
        else:
            state[relative_path] = path.read_text(encoding="utf-8")
    return state


if __name__ == "__main__":
    unittest.main()
