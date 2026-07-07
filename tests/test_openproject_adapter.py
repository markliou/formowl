from __future__ import annotations

import base64
from io import BytesIO
import json
from pathlib import Path
from urllib import error, parse, request
import unittest
from unittest.mock import patch

import _paths
from formowl_contract import sha256_json
import formowl_project_mcp.storage.evidence_snapshot_store as evidence_snapshot_store_module
from formowl_project_mcp.adapters.openproject import (
    OpenProjectAdapter,
    OpenProjectClient,
    OpenProjectHttpError,
)
from formowl_project_mcp.observability import JsonlToolCallLogger
from formowl_project_mcp.storage import FileEvidenceSnapshotStore
from formowl_project_mcp.tools import ProjectMcpTools


BASE_URL = "https://openproject.example.test"


class FakeResponse:
    def __init__(self, payload: bytes | dict[str, object]) -> None:
        self.payload = payload

    def read(self) -> bytes:
        if isinstance(self.payload, bytes):
            return self.payload
        return json.dumps(self.payload).encode("utf-8")

    def close(self) -> None:
        return None


class FakeOpener:
    def __init__(self, responses: dict[str, bytes | dict[str, object] | Exception]) -> None:
        self.responses = responses
        self.requests: list[object] = []
        self.timeouts: list[float] = []

    def open(self, request: object, timeout: float) -> FakeResponse:
        self.requests.append(request)
        self.timeouts.append(timeout)
        url = getattr(request, "full_url")
        path = parse.urlparse(url).path
        response = self.responses.get(path)
        if isinstance(response, Exception):
            raise response
        if response is None:
            raise AssertionError(f"Unexpected OpenProject request: {url}")
        return FakeResponse(response)

    def last_query(self) -> dict[str, list[str]]:
        url = getattr(self.requests[-1], "full_url")
        return parse.parse_qs(parse.urlparse(url).query)

    def requested_paths(self) -> list[str]:
        return [parse.urlparse(getattr(request, "full_url")).path for request in self.requests]

    def requested_methods(self) -> list[str]:
        return [getattr(request, "get_method")() for request in self.requests]


class OpenProjectAdapterTests(unittest.TestCase):
    def test_client_sends_bearer_auth_and_decodes_hal_json(self) -> None:
        opener = FakeOpener({"/api/v3/work_packages/42": work_package(42)})
        client = OpenProjectClient(
            base_url=BASE_URL,
            api_token="opapi-token",
            opener=opener,
            timeout_seconds=12,
        )

        payload = client.get("/api/v3/work_packages/42")

        request = opener.requests[0]
        self.assertEqual(payload["id"], 42)
        self.assertEqual(getattr(request, "get_header")("Authorization"), "Bearer opapi-token")
        self.assertIn("application/hal+json", getattr(request, "get_header")("Accept"))
        self.assertEqual(opener.timeouts, [12])

    def test_client_auth_modes_cover_basic_none_and_invalid_schemes(self) -> None:
        opener = FakeOpener({"/api/v3/work_packages/42": work_package(42)})
        basic_client = OpenProjectClient(
            base_url=BASE_URL,
            api_token="opapi-token",
            auth_scheme="basic",
            opener=opener,
        )
        none_client = OpenProjectClient(
            base_url=BASE_URL,
            api_token="opapi-token",
            auth_scheme="none",
            opener=opener,
        )

        basic_client.get("/api/v3/work_packages/42")
        none_client.get("/api/v3/work_packages/42")

        expected_basic = base64.b64encode(b"apikey:opapi-token").decode("ascii")
        self.assertEqual(
            getattr(opener.requests[0], "get_header")("Authorization"),
            f"Basic {expected_basic}",
        )
        self.assertIsNone(getattr(opener.requests[1], "get_header")("Authorization"))

        invalid_client = OpenProjectClient(
            base_url=BASE_URL,
            api_token="opapi-token",
            auth_scheme="digest",
            opener=opener,
        )
        with self.assertRaisesRegex(ValueError, "Unsupported OpenProject auth scheme"):
            invalid_client.get("/api/v3/work_packages/42")
        self.assertEqual(len(opener.requests), 2)

        invalid_without_token = OpenProjectClient(
            base_url=BASE_URL,
            auth_scheme="digest",
            opener=opener,
        )
        with self.assertRaisesRegex(ValueError, "Unsupported OpenProject auth scheme"):
            invalid_without_token.get("/api/v3/work_packages/42")
        self.assertEqual(len(opener.requests), 2)

    def test_client_rejects_absolute_links_outside_openproject_origin(self) -> None:
        opener = FakeOpener({})
        client = OpenProjectClient(
            base_url=BASE_URL,
            api_token="opapi-token",
            opener=opener,
        )

        unsafe_targets = [
            "https://attacker.example.test/api/v3/work_packages/42",
            "file:/tmp/raw-openproject.json",
            "storage://bucket/raw-openproject.json",
            "//attacker.example.test/api/v3/work_packages/42",
        ]
        for target in unsafe_targets:
            with self.subTest(target=target):
                with self.assertRaisesRegex(
                    OpenProjectHttpError, "outside the configured base URL"
                ):
                    client.get(target)

        self.assertEqual(opener.requests, [])

        with self.assertRaisesRegex(ValueError, "http or https origin"):
            OpenProjectClient(base_url="file:///tmp/openproject", opener=opener)

    def test_default_client_rejects_cross_origin_redirect_before_forwarding_auth(self) -> None:
        client = OpenProjectClient(base_url=BASE_URL, api_token="opapi-secret")
        redirect_handler = next(
            handler
            for handler in client.opener.handlers
            if handler.__class__.__name__ == "_SameOriginRedirectHandler"
        )
        original_request = request.Request(
            f"{BASE_URL}/api/v3/work_packages/42",
            headers={"Authorization": "Bearer opapi-secret"},
        )

        with self.assertRaisesRegex(
            OpenProjectHttpError,
            "redirect target is outside the configured base URL",
        ):
            redirect_handler.redirect_request(
                original_request,
                None,
                302,
                "Found",
                {},
                "https://attacker.example.test/collect",
            )

        redirected_request = redirect_handler.redirect_request(
            original_request,
            None,
            302,
            "Found",
            {},
            f"{BASE_URL}/api/v3/work_packages/43",
        )
        self.assertIsNotNone(redirected_request)
        assert redirected_request is not None
        self.assertEqual(
            redirected_request.full_url,
            f"{BASE_URL}/api/v3/work_packages/43",
        )
        self.assertEqual(
            redirected_request.get_header("Authorization"),
            "Bearer opapi-secret",
        )

    def test_get_work_item_context_maps_work_package_comments_relations_and_attachments(
        self,
    ) -> None:
        opener = FakeOpener(
            {
                "/api/v3/work_packages/42": work_package(42),
                "/api/v3/work_packages/42/activities": activities_collection(),
                "/api/v3/work_packages/42/relations": relations_collection(),
                "/api/v3/work_packages/42/attachments": attachments_collection(),
            }
        )
        adapter = adapter_for(opener)

        context = adapter.get_work_item_context(
            {
                "source_ref": {
                    "source_system": "openproject",
                    "source_type": "work_package",
                    "source_id": "42",
                },
                "include_comments": True,
                "include_activities": True,
                "include_relations": True,
                "include_attachments": True,
            }
        )

        self.assertIsNotNone(context)
        assert context is not None
        item = context["work_item"]
        self.assertEqual(item["title"], "Implement real adapter")
        self.assertEqual(item["description"], "Map OpenProject API responses.")
        self.assertEqual(item["status"], "In progress")
        self.assertEqual(item["source_ref"]["source_key"], "OP-42")
        self.assertEqual(item["permission_scope"]["scope_id"], "formowl")
        self.assertEqual(context["comments"][0]["body"], "Please keep writes proposal-only.")
        self.assertEqual(
            context["comments"][0]["source_ref"]["source_type"], "work_package_comment"
        )
        self.assertEqual(
            context["activities"][1]["body"], "Status changed from New to In progress."
        )
        self.assertEqual(
            context["relations"][0]["relation_source_ref"]["source_type"],
            "work_package_relation",
        )
        self.assertEqual(context["relations"][0]["target_ref"]["source_id"], "43")
        self.assertEqual(context["attachments"][0]["file_name"], "adapter-notes.md")
        self.assertEqual(
            opener.requested_paths(),
            [
                "/api/v3/work_packages/42",
                "/api/v3/work_packages/42/activities",
                "/api/v3/work_packages/42/relations",
                "/api/v3/work_packages/42/attachments",
            ],
        )
        self.assertEqual(opener.requested_methods(), ["GET", "GET", "GET", "GET"])

    def test_minimal_hal_payloads_map_with_controlled_defaults(self) -> None:
        opener = FakeOpener(
            {
                "/api/v3/work_packages/44": {
                    "_type": "WorkPackage",
                    "id": 44,
                    "subject": "Minimal work package",
                    "_links": [],
                },
            }
        )
        adapter = adapter_for(opener)

        context = adapter.get_work_item_context(
            {
                "source_ref": {
                    "source_system": "openproject",
                    "source_type": "work_package",
                    "source_id": "44",
                },
                "include_comments": False,
                "include_activities": False,
                "include_relations": False,
                "include_attachments": False,
            }
        )

        self.assertIsNotNone(context)
        assert context is not None
        item = context["work_item"]
        self.assertEqual(item["title"], "Minimal work package")
        self.assertEqual(item["description"], "")
        self.assertEqual(item["status"], "unknown")
        self.assertEqual(item["type"], "unknown")
        self.assertEqual(item["priority"], "unknown")
        self.assertEqual(item["permission_scope"]["scope_id"], "unknown")
        self.assertEqual(context["comments"], [])
        self.assertEqual(context["activities"], [])
        self.assertEqual(context["relations"], [])
        self.assertEqual(context["attachments"], [])
        self.assertEqual(opener.requested_paths(), ["/api/v3/work_packages/44"])

    def test_malformed_nested_hal_values_do_not_create_requests_lineage_or_leaks(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("openproject-malformed-nested-hal")
        opener = FakeOpener(
            {
                "/api/v3/work_packages/45": malformed_nested_work_package(),
                "/api/v3/work_packages/45/activities": malformed_activities_collection(),
                "/api/v3/work_packages/45/relations": malformed_relations_collection(),
                "/api/v3/work_packages/45/attachments": malformed_attachments_collection(),
            }
        )
        snapshot_store = FileEvidenceSnapshotStore(temp_dir)
        tools = ProjectMcpTools(
            adapter_for(opener),
            snapshot_store,
            JsonlToolCallLogger(temp_dir / "logs" / "project-mcp-tool-calls.jsonl"),
        )

        envelope = tools.get_work_item_context(
            {
                "source_ref": {
                    "source_system": "openproject",
                    "source_type": "work_package",
                    "source_id": "45",
                },
                "include_comments": True,
                "include_activities": True,
                "include_relations": True,
                "include_attachments": True,
                "create_evidence_snapshot": True,
            }
        )

        self.assertEqual(envelope["status"], "ok")
        context = envelope["data"]
        item = context["work_item"]
        self.assertEqual(item["title"], "Untitled work item")
        self.assertEqual(item["description"], "")
        self.assertEqual(item["status"], "unknown")
        self.assertEqual(item["type"], "unknown")
        self.assertEqual(item["priority"], "unknown")
        self.assertEqual(item["permission_scope"]["scope_id"], "unknown")
        self.assertEqual([comment["comment_id"] for comment in context["comments"]], ["202"])
        self.assertEqual([activity["activity_id"] for activity in context["activities"]], ["202"])
        self.assertNotIn("created_at", context["comments"][0])
        self.assertNotIn("created_at", context["activities"][0])
        self.assertEqual(context["relations"], [])
        self.assertEqual(
            context["attachments"],
            [
                {
                    "attachment_id": "400",
                    "source_url": f"{BASE_URL}/api/v3/attachments/400",
                    "source_ref": {
                        "source_system": "openproject",
                        "source_instance": "test-openproject",
                        "source_type": "attachment",
                        "source_id": "400",
                        "source_key": "OP-45",
                        "source_url": f"{BASE_URL}/api/v3/attachments/400",
                    },
                }
            ],
        )
        self.assertEqual(
            envelope["source_refs"],
            [
                item["source_ref"],
                context["comments"][0]["source_ref"],
                context["activities"][0]["source_ref"],
                context["attachments"][0]["source_ref"],
            ],
        )
        self.assertNotIn("unknown", [ref["source_id"] for ref in envelope["source_refs"]])
        self.assertEqual(
            opener.requested_paths(),
            [
                "/api/v3/work_packages/45",
                "/api/v3/work_packages/45/activities",
                "/api/v3/work_packages/45/relations",
                "/api/v3/work_packages/45/attachments",
            ],
        )

        snapshot_id = envelope["evidence_snapshot_ids"][0]
        metadata_files = list(Path(temp_dir).glob("raw/evidence/openproject/*/*/*/*/metadata.json"))
        self.assertEqual(len(metadata_files), 1)
        snapshot_dir = metadata_files[0].parent
        response_payload = json.loads((snapshot_dir / "response.json").read_text(encoding="utf-8"))
        normalized_markdown = (snapshot_dir / "normalized.md").read_text(encoding="utf-8")
        snapshot = snapshot_store.get_snapshot(snapshot_id)
        self.assertIsNotNone(snapshot)
        rendered_outputs = [
            json.dumps(envelope, sort_keys=True),
            json.dumps(response_payload, sort_keys=True),
            json.dumps(snapshot, sort_keys=True),
            normalized_markdown,
        ]
        for rendered_output in rendered_outputs:
            for marker in (
                "file:///tmp/nested-secret.txt",
                "storage://nested-bucket/private.txt",
                "attacker.example.test",
            ):
                with self.subTest(marker=marker):
                    self.assertNotIn(marker, rendered_output)

    def test_attachment_links_reject_internal_and_cross_origin_urls(self) -> None:
        temp_dir = _paths.fresh_test_dir("openproject-unsafe-attachment-links")
        opener = FakeOpener(
            {
                "/api/v3/work_packages/42": work_package(42),
                "/api/v3/work_packages/42/attachments": unsafe_attachments_collection(),
            }
        )
        snapshot_store = FileEvidenceSnapshotStore(temp_dir)
        tools = ProjectMcpTools(
            adapter_for(opener),
            snapshot_store,
            JsonlToolCallLogger(temp_dir / "logs" / "project-mcp-tool-calls.jsonl"),
        )

        envelope = tools.get_work_item_context(
            {
                "source_ref": {
                    "source_system": "openproject",
                    "source_type": "work_package",
                    "source_id": "42",
                },
                "include_comments": False,
                "include_activities": False,
                "include_relations": False,
                "include_attachments": True,
                "create_evidence_snapshot": True,
            }
        )

        self.assertEqual(envelope["status"], "ok")
        context = envelope["data"]
        self.assertEqual(
            [attachment["source_url"] for attachment in context["attachments"]],
            [
                f"{BASE_URL}/api/v3/attachments/56",
                f"{BASE_URL}/api/v3/attachments/57",
                f"{BASE_URL}/api/v3/attachments/58",
                f"{BASE_URL}/api/v3/attachments/59",
                f"{BASE_URL}/api/v3/attachments/60",
                f"{BASE_URL}/api/v3/attachments/61",
                f"{BASE_URL}/api/v3/attachments/62",
                f"{BASE_URL}/api/v3/attachments/63",
                f"{BASE_URL}/api/v3/attachments/64",
            ],
        )
        snapshot_id = envelope["evidence_snapshot_ids"][0]
        metadata_files = list(Path(temp_dir).glob("raw/evidence/openproject/*/*/*/*/metadata.json"))
        self.assertEqual(len(metadata_files), 1)
        snapshot_dir = metadata_files[0].parent
        response_payload = json.loads((snapshot_dir / "response.json").read_text(encoding="utf-8"))
        normalized_markdown = (snapshot_dir / "normalized.md").read_text(encoding="utf-8")
        snapshot = snapshot_store.get_snapshot(snapshot_id)
        self.assertIsNotNone(snapshot)
        rendered_outputs = [
            json.dumps(envelope, sort_keys=True),
            json.dumps(response_payload, sort_keys=True),
            json.dumps(snapshot, sort_keys=True),
            normalized_markdown,
        ]
        unsafe_markers = [
            "file:/tmp/private.txt",
            "storage://bucket/private.txt",
            "file:///tmp/private.txt",
            "storage%3A%2F%2Fbucket%2Fprivate.txt",
            "storage%253A%252F%252Fbucket%252Fprivate.txt",
            "/tmp/private.txt",
            "attacker.example.test",
        ]
        for rendered_output in rendered_outputs:
            for marker in unsafe_markers:
                with self.subTest(marker=marker):
                    self.assertNotIn(marker, rendered_output)

    def test_search_work_items_uses_mocked_http_and_maps_results(self) -> None:
        opener = FakeOpener(
            {
                "/api/v3/projects/formowl/work_packages": {
                    "_type": "Collection",
                    "_embedded": {"elements": [work_package(42)]},
                }
            }
        )
        adapter = adapter_for(opener)

        results = adapter.search_work_items(
            {
                "query": "adapter",
                "limit": 5,
                "project_ref": {
                    "source_system": "openproject",
                    "source_type": "project",
                    "source_id": "formowl",
                },
            }
        )

        query = opener.last_query()
        self.assertEqual(query["pageSize"], ["5"])
        self.assertIn("adapter", query["filters"][0])
        self.assertEqual(results[0]["item"]["source_ref"]["source_id"], "42")
        self.assertEqual(results[0]["matched_fields"], ["title"])

    def test_source_ids_are_quoted_as_single_openproject_path_segments(self) -> None:
        opener = FakeOpener(
            {
                "/api/v3/work_packages/wp%2F42": work_package(42),
                "/api/v3/work_packages/wp%2F42/activities": activities_collection(),
                "/api/v3/work_packages/wp%2F42/relations": relations_collection(),
                "/api/v3/projects/formowl%2Fprivate/work_packages": {
                    "_type": "Collection",
                    "_embedded": {"elements": [work_package(42)]},
                },
            }
        )
        adapter = adapter_for(opener)
        source_ref = {
            "source_system": "openproject",
            "source_type": "work_package",
            "source_id": "wp/42",
        }

        self.assertIsNotNone(adapter.get_work_item(source_ref))
        adapter.list_work_item_activities({"source_ref": source_ref})
        adapter.list_work_item_relations({"source_ref": source_ref})
        adapter.search_work_items(
            {
                "query": "adapter",
                "project_ref": {
                    "source_system": "openproject",
                    "source_type": "project",
                    "source_id": "formowl/private",
                },
            }
        )

        self.assertEqual(
            opener.requested_paths(),
            [
                "/api/v3/work_packages/wp%2F42",
                "/api/v3/work_packages/wp%2F42/activities",
                "/api/v3/work_packages/wp%2F42/relations",
                "/api/v3/projects/formowl%2Fprivate/work_packages",
            ],
        )

    def test_context_fallback_collection_paths_quote_source_ids(self) -> None:
        opener = FakeOpener(
            {
                "/api/v3/work_packages/wp%2F42": {
                    "_type": "WorkPackage",
                    "id": "wp/42",
                    "subject": "Fallback links",
                    "_links": {},
                },
                "/api/v3/work_packages/wp%2F42/activities": {"_embedded": {"elements": []}},
                "/api/v3/work_packages/wp%2F42/relations": {"_embedded": {"elements": []}},
                "/api/v3/work_packages/wp%2F42/attachments": {"_embedded": {"elements": []}},
            }
        )
        adapter = adapter_for(opener)

        context = adapter.get_work_item_context(
            {
                "source_ref": {
                    "source_system": "openproject",
                    "source_type": "work_package",
                    "source_id": "wp/42",
                },
                "include_comments": True,
                "include_activities": True,
                "include_relations": True,
                "include_attachments": True,
            }
        )

        self.assertIsNotNone(context)
        self.assertEqual(
            opener.requested_paths(),
            [
                "/api/v3/work_packages/wp%2F42",
                "/api/v3/work_packages/wp%2F42/activities",
                "/api/v3/work_packages/wp%2F42/relations",
                "/api/v3/work_packages/wp%2F42/attachments",
            ],
        )

    def test_mapped_source_urls_quote_work_package_and_project_ids(self) -> None:
        opener = FakeOpener(
            {
                "/api/v3/work_packages/wp%2F42": {
                    "_type": "WorkPackage",
                    "id": "wp/42",
                    "subject": "Quoted UI link",
                    "_links": {
                        "project": {
                            "href": "/api/v3/projects/formowl%2Fprivate",
                            "title": "Private FormOwl",
                        }
                    },
                },
                "/api/v3/projects/formowl%2Fprivate": project_payload("formowl/private"),
                "/api/v3/projects/formowl%2Fprivate/work_packages": {
                    "_type": "Collection",
                    "_embedded": {"elements": []},
                },
            }
        )
        adapter = adapter_for(opener)

        item = adapter.get_work_item(
            {
                "source_system": "openproject",
                "source_type": "work_package",
                "source_id": "wp/42",
            }
        )
        status = adapter.get_project_status(
            {
                "project_ref": {
                    "source_system": "openproject",
                    "source_type": "project",
                    "source_id": "formowl/private",
                }
            }
        )

        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item["source_url"], f"{BASE_URL}/work_packages/wp%2F42")
        self.assertIsNotNone(status)
        assert status is not None
        self.assertEqual(
            status["project_ref"]["source_url"],
            f"{BASE_URL}/projects/formowl%2Fprivate",
        )

    def test_percent_encoded_hal_ids_decode_once_before_url_construction(self) -> None:
        temp_dir = _paths.fresh_test_dir("openproject-encoded-hal-ids")
        opener = FakeOpener(
            {
                "/api/v3/work_packages/wp%2F42": self_link_only_work_package(),
                "/api/v3/work_packages/wp%2F42/relations": encoded_relations_collection(),
                "/api/v3/projects/formowl%2Fprivate": self_link_only_project(),
                "/api/v3/projects/formowl%2Fprivate/work_packages": {
                    "_type": "Collection",
                    "_embedded": {"elements": []},
                },
            }
        )
        adapter = adapter_for(opener)
        tools = ProjectMcpTools(
            adapter,
            FileEvidenceSnapshotStore(temp_dir),
            JsonlToolCallLogger(temp_dir / "logs" / "project-mcp-tool-calls.jsonl"),
        )

        envelope = tools.get_work_item_context(
            {
                "source_ref": {
                    "source_system": "openproject",
                    "source_type": "work_package",
                    "source_id": "wp/42",
                },
                "include_comments": False,
                "include_activities": False,
                "include_relations": True,
                "include_attachments": False,
            }
        )
        status = adapter.get_project_status(
            {
                "project_ref": {
                    "source_system": "openproject",
                    "source_type": "project",
                    "source_id": "formowl/private",
                }
            }
        )

        self.assertEqual(envelope["status"], "ok")
        item = envelope["data"]["work_item"]
        relation = envelope["data"]["relations"][0]
        self.assertEqual(item["source_ref"]["source_id"], "wp/42")
        self.assertEqual(item["source_url"], f"{BASE_URL}/work_packages/wp%2F42")
        self.assertEqual(item["permission_scope"]["scope_id"], "formowl/private")
        self.assertEqual(relation["relation_source_ref"]["source_id"], "rel/7")
        self.assertEqual(
            relation["relation_source_ref"]["source_url"],
            f"{BASE_URL}/relations/rel%2F7",
        )
        self.assertEqual(relation["source_ref"]["source_id"], "wp/42")
        self.assertEqual(relation["target_ref"]["source_id"], "wp/43")
        self.assertEqual(
            relation["target_ref"]["source_url"],
            f"{BASE_URL}/work_packages/wp%2F43",
        )
        self.assertEqual(
            envelope["source_refs"],
            [
                item["source_ref"],
                relation["relation_source_ref"],
                relation["target_ref"],
            ],
        )
        self.assertEqual(
            envelope["context_package"]["source_refs"],
            envelope["source_refs"],
        )
        self.assertIsNotNone(status)
        assert status is not None
        self.assertEqual(status["project_ref"]["source_id"], "formowl/private")
        self.assertEqual(
            status["project_ref"]["source_url"],
            f"{BASE_URL}/projects/formowl%2Fprivate",
        )
        self.assertEqual(
            opener.requested_paths(),
            [
                "/api/v3/work_packages/wp%2F42",
                "/api/v3/work_packages/wp%2F42/relations",
                "/api/v3/projects/formowl%2Fprivate",
                "/api/v3/projects/formowl%2Fprivate/work_packages",
            ],
        )

    def test_get_project_status_counts_statuses_and_preserves_source_refs(self) -> None:
        second = work_package(43)
        second["subject"] = "Document adapter behavior"
        second["_links"]["status"]["title"] = "New"  # type: ignore[index]
        opener = FakeOpener(
            {
                "/api/v3/projects/formowl": project_payload(),
                "/api/v3/projects/formowl/work_packages": {
                    "_type": "Collection",
                    "_embedded": {"elements": [work_package(42), second]},
                },
            }
        )
        adapter = adapter_for(opener)

        status = adapter.get_project_status(
            {
                "project_ref": {
                    "source_system": "openproject",
                    "source_type": "project",
                    "source_id": "formowl",
                },
                "include_recent_updates": True,
            }
        )

        self.assertIsNotNone(status)
        assert status is not None
        self.assertEqual(status["project_ref"]["source_id"], "formowl")
        self.assertEqual(status["status_counts"], {"In progress": 1, "New": 1})
        self.assertEqual(
            [ref["source_id"] for ref in status["source_refs"]],
            ["42", "43"],
        )
        self.assertIn("| In progress | 1 |", status["summary_markdown"])
        self.assertEqual(status["recent_updates"][0]["source_ref"]["source_id"], "42")

    def test_missing_work_item_returns_none_for_project_mcp_not_found_path(self) -> None:
        not_found = error.HTTPError(
            f"{BASE_URL}/api/v3/work_packages/404",
            404,
            "Not Found",
            hdrs=None,
            fp=BytesIO(
                json.dumps(
                    {
                        "_type": "Error",
                        "message": "The specified work package does not exist.",
                    }
                ).encode("utf-8")
            ),
        )
        opener = FakeOpener({"/api/v3/work_packages/404": not_found})
        adapter = adapter_for(opener)

        result = adapter.get_work_item(
            {"source_system": "openproject", "source_type": "work_package", "source_id": "404"}
        )

        self.assertIsNone(result)

    def test_malformed_and_cross_system_refs_do_not_call_openproject(self) -> None:
        opener = FakeOpener({})
        adapter = adapter_for(opener)
        malformed_work_refs = [
            None,
            "42",
            {},
            {"source_system": "jira", "source_type": "work_package", "source_id": "42"},
            {"source_system": "openproject", "source_type": "issue", "source_id": "42"},
            {"source_system": "openproject", "source_type": "work_package"},
            {"source_system": "openproject", "source_type": "work_package", "source_id": True},
            {"source_system": "openproject", "source_type": "work_package", "source_id": ["42"]},
            {
                "source_system": "openproject",
                "source_type": "work_package",
                "source_id": {"value": "42"},
            },
            {"source_system": "openproject", "source_type": "work_package", "source_id": " "},
        ]

        for source_ref in malformed_work_refs:
            with self.subTest(source_ref=source_ref):
                self.assertIsNone(adapter.get_work_item(source_ref))  # type: ignore[arg-type]
                self.assertIsNone(adapter.get_work_item_context({"source_ref": source_ref}))
                self.assertEqual(adapter.list_work_item_activities({"source_ref": source_ref}), [])
                self.assertEqual(adapter.list_work_item_relations({"source_ref": source_ref}), [])

        malformed_project_refs = [
            None,
            "formowl",
            {},
            {"source_system": "jira", "source_type": "project", "source_id": "formowl"},
            {"source_system": "openproject", "source_type": "workspace", "source_id": "formowl"},
            {"source_system": "openproject", "source_type": "project"},
            {"source_system": "openproject", "source_type": "project", "source_id": False},
            {"source_system": "openproject", "source_type": "project", "source_id": ["formowl"]},
            {
                "source_system": "openproject",
                "source_type": "project",
                "source_id": {"value": "formowl"},
            },
            {"source_system": "openproject", "source_type": "project", "source_key": True},
        ]
        for project_ref in malformed_project_refs:
            with self.subTest(project_ref=project_ref):
                self.assertIsNone(adapter.get_project_status({"project_ref": project_ref}))
                self.assertEqual(
                    adapter.search_work_items({"query": "adapter", "project_ref": project_ref}),
                    [],
                )

        self.assertEqual(opener.requests, [])

    def test_client_negative_paths_raise_controlled_errors_without_token_leaks(self) -> None:
        encoded_basic = base64.b64encode(b"apikey:opapi-secret").decode("ascii")
        server_error = error.HTTPError(
            f"{BASE_URL}/api/v3/work_packages/500",
            500,
            "Internal Server Error",
            hdrs=None,
            fp=BytesIO(
                json.dumps(
                    {
                        "_type": "Error",
                        "message": (
                            "OpenProject rejected Bearer opapi-secret and Basic "
                            f"{encoded_basic}."
                        ),
                    }
                ).encode("utf-8")
            ),
        )
        opener = FakeOpener(
            {
                "/api/v3/work_packages/bad-json": b'{"token":"opapi-secret"',
                "/api/v3/work_packages/500": server_error,
                "/api/v3/work_packages/network": error.URLError(
                    f"connection failed with opapi-secret and {encoded_basic}"
                ),
            }
        )
        client = OpenProjectClient(
            base_url=BASE_URL,
            api_token="opapi-secret",
            opener=opener,
        )

        with self.assertRaises(OpenProjectHttpError) as invalid_json:
            client.get("/api/v3/work_packages/bad-json")
        self.assertEqual(str(invalid_json.exception), "OpenProject returned invalid JSON.")
        self.assertNotIn("opapi-secret", str(invalid_json.exception))
        self.assertNotIn(encoded_basic, str(invalid_json.exception))

        with self.assertRaises(OpenProjectHttpError) as http_failure:
            client.get("/api/v3/work_packages/500")
        self.assertEqual(http_failure.exception.status_code, 500)
        self.assertIn("OpenProject rejected", str(http_failure.exception))
        self.assertNotIn("opapi-secret", str(http_failure.exception))
        self.assertNotIn(encoded_basic, str(http_failure.exception))

        with self.assertRaises(OpenProjectHttpError) as url_failure:
            client.get("/api/v3/work_packages/network")
        self.assertIsNone(url_failure.exception.status_code)
        self.assertIn("connection failed", str(url_failure.exception))
        self.assertNotIn("opapi-secret", str(url_failure.exception))
        self.assertNotIn(encoded_basic, str(url_failure.exception))

    def test_project_mcp_tools_accept_real_adapter_shape_with_evidence_snapshot(self) -> None:
        temp_dir = _paths.fresh_test_dir("openproject-adapter-tools")
        opener = FakeOpener(
            {
                "/api/v3/work_packages/42": work_package(42),
                "/api/v3/work_packages/42/activities": activities_collection(),
                "/api/v3/work_packages/42/relations": relations_collection(),
                "/api/v3/work_packages/42/attachments": attachments_collection(),
            }
        )
        snapshot_store = FileEvidenceSnapshotStore(temp_dir)
        tools = ProjectMcpTools(
            adapter_for(opener),
            snapshot_store,
            JsonlToolCallLogger(temp_dir / "logs" / "project-mcp-tool-calls.jsonl"),
        )

        envelope = tools.get_work_item_context(
            {
                "source_ref": {
                    "source_system": "openproject",
                    "source_type": "work_package",
                    "source_id": "42",
                },
                "create_evidence_snapshot": True,
            }
        )

        self.assertEqual(envelope["status"], "ok")
        self.assertEqual(envelope["context_package"]["context_type"], "work_item_context")
        self.assertIn("Implement real adapter", envelope["context_package"]["context_markdown"])
        source_ref_pairs = {
            (ref["source_type"], ref["source_id"]) for ref in envelope["source_refs"]
        }
        self.assertEqual(
            source_ref_pairs,
            {
                ("work_package", "42"),
                ("work_package_comment", "100"),
                ("work_package_activity", "100"),
                ("work_package_activity", "101"),
                ("work_package_relation", "7"),
                ("work_package", "43"),
                ("attachment", "55"),
            },
        )
        self.assertEqual(envelope["context_package"]["source_refs"], envelope["source_refs"])
        self.assertEqual(len(envelope["evidence_snapshot_ids"]), 1)
        snapshot_id = envelope["evidence_snapshot_ids"][0]
        metadata_files = list(Path(temp_dir).glob("raw/evidence/openproject/*/*/*/*/metadata.json"))
        self.assertEqual(len(metadata_files), 1)
        snapshot_dir = metadata_files[0].parent
        request_payload = json.loads((snapshot_dir / "request.json").read_text(encoding="utf-8"))
        response_payload = json.loads((snapshot_dir / "response.json").read_text(encoding="utf-8"))
        normalized_markdown = (snapshot_dir / "normalized.md").read_text(encoding="utf-8")
        snapshot = snapshot_store.get_snapshot(snapshot_id)
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(request_payload["source_ref"]["source_id"], "42")
        self.assertEqual(response_payload["work_item"]["source_ref"], envelope["source_refs"][0])
        self.assertEqual(snapshot["source_refs"], envelope["source_refs"])
        self.assertEqual(
            response_payload["comments"][0]["body"],
            "Please keep writes proposal-only.",
        )
        self.assertIn("Please keep writes proposal-only.", normalized_markdown)
        self.assertEqual(snapshot["request_hash"], sha256_json(request_payload))
        self.assertEqual(snapshot["response_hash"], sha256_json(response_payload))

    def test_list_tools_preserve_nested_lineage_in_envelopes_and_snapshots(self) -> None:
        temp_dir = _paths.fresh_test_dir("openproject-list-tool-lineage")
        opener = FakeOpener(
            {
                "/api/v3/work_packages/42/activities": activities_collection(),
                "/api/v3/work_packages/42/relations": relations_collection(),
            }
        )
        snapshot_store = FileEvidenceSnapshotStore(temp_dir)
        tools = ProjectMcpTools(
            adapter_for(opener),
            snapshot_store,
            JsonlToolCallLogger(temp_dir / "logs" / "project-mcp-tool-calls.jsonl"),
        )

        activities_envelope = tools.list_work_item_activities(
            {
                "source_ref": {
                    "source_system": "openproject",
                    "source_type": "work_package",
                    "source_id": "42",
                },
                "create_evidence_snapshot": True,
            }
        )
        relations_envelope = tools.list_work_item_relations(
            {
                "source_ref": {
                    "source_system": "openproject",
                    "source_type": "work_package",
                    "source_id": "42",
                },
                "create_evidence_snapshot": True,
            }
        )

        self.assertEqual(activities_envelope["status"], "ok")
        self.assertEqual(
            [(ref["source_type"], ref["source_id"]) for ref in activities_envelope["source_refs"]],
            [
                ("work_package", "42"),
                ("work_package_activity", "100"),
                ("work_package_activity", "101"),
            ],
        )
        activity_snapshot_id = activities_envelope["evidence_snapshot_ids"][0]
        activity_snapshot = snapshot_store.get_snapshot(activity_snapshot_id)
        activity_payload = snapshot_store.get_snapshot_payload(activity_snapshot_id)
        self.assertIsNotNone(activity_snapshot)
        assert activity_snapshot is not None
        self.assertEqual(activity_snapshot["source_refs"], activities_envelope["source_refs"])
        self.assertEqual(activity_payload, activities_envelope["data"])

        self.assertEqual(relations_envelope["status"], "ok")
        self.assertEqual(
            [(ref["source_type"], ref["source_id"]) for ref in relations_envelope["source_refs"]],
            [
                ("work_package", "42"),
                ("work_package_relation", "7"),
                ("work_package", "43"),
            ],
        )
        relation_snapshot_id = relations_envelope["evidence_snapshot_ids"][0]
        relation_snapshot = snapshot_store.get_snapshot(relation_snapshot_id)
        relation_payload = snapshot_store.get_snapshot_payload(relation_snapshot_id)
        self.assertIsNotNone(relation_snapshot)
        assert relation_snapshot is not None
        self.assertEqual(relation_snapshot["source_refs"], relations_envelope["source_refs"])
        self.assertEqual(relation_payload, relations_envelope["data"])
        self.assertEqual(
            relation_payload["relations"][0]["relation_source_ref"],
            relations_envelope["source_refs"][1],
        )
        self.assertEqual(
            opener.requested_paths(),
            [
                "/api/v3/work_packages/42/activities",
                "/api/v3/work_packages/42/relations",
            ],
        )

    def test_evidence_snapshot_mid_write_failure_leaves_no_retrievable_partial_data(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("openproject-atomic-evidence-snapshot")
        snapshot_store = FileEvidenceSnapshotStore(temp_dir)
        snapshot_id = "ev_openproject_atomic_failure"
        original_write_json = evidence_snapshot_store_module._write_json
        write_count = 0

        def fail_metadata_write(path: Path, payload: object) -> None:
            nonlocal write_count
            write_count += 1
            if write_count == 3:
                raise OSError("injected metadata write failure")
            original_write_json(path, payload)

        with patch.object(
            evidence_snapshot_store_module,
            "_write_json",
            side_effect=fail_metadata_write,
        ):
            with self.assertRaisesRegex(OSError, "injected metadata write failure"):
                snapshot_store.save_snapshot(
                    {
                        "snapshot": {
                            "evidence_snapshot_id": snapshot_id,
                            "captured_at": "2026-06-18T10:00:00+00:00",
                            "source_refs": [
                                {
                                    "source_system": "openproject",
                                    "source_type": "work_package",
                                    "source_id": "42",
                                }
                            ],
                        },
                        "request_payload": {"source_id": "42"},
                        "response_payload": {"subject": "Atomic snapshot"},
                        "normalized_markdown": "# Atomic snapshot\n",
                    }
                )

        final_directory = (
            Path(temp_dir) / "raw" / "evidence" / "openproject" / "2026" / "06" / "18" / snapshot_id
        )
        self.assertFalse(final_directory.exists())
        evidence_root = Path(temp_dir) / "raw" / "evidence"
        self.assertEqual([path for path in evidence_root.rglob("*") if path.is_file()], [])
        self.assertEqual(list(final_directory.parent.glob(f"{snapshot_id}.tmp-*")), [])
        self.assertIsNone(snapshot_store.get_snapshot(snapshot_id))
        self.assertIsNone(snapshot_store.get_snapshot_payload(snapshot_id))

    def test_evidence_snapshot_rename_permission_fallback_publishes_complete_snapshot(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("openproject-evidence-snapshot-rename-fallback")
        snapshot_store = FileEvidenceSnapshotStore(temp_dir)
        snapshot_id = "ev_openproject_rename_fallback"
        original_rename = Path.rename
        rename_call_count = 0

        def deny_temporary_directory_rename(self: Path, target: Path) -> Path:
            nonlocal rename_call_count
            if self.name.startswith(f"{snapshot_id}.tmp-"):
                rename_call_count += 1
                raise PermissionError("bind mount denied directory rename")
            return original_rename(self, target)

        with patch.object(Path, "rename", deny_temporary_directory_rename):
            result = snapshot_store.save_snapshot(
                {
                    "snapshot": {
                        "evidence_snapshot_id": snapshot_id,
                        "captured_at": "2026-06-18T10:00:00+00:00",
                        "source_refs": [
                            {
                                "source_system": "openproject",
                                "source_type": "work_package",
                                "source_id": "42",
                            }
                        ],
                    },
                    "request_payload": {"source_id": "42"},
                    "response_payload": {"subject": "Rename fallback snapshot"},
                    "normalized_markdown": "# Rename fallback snapshot\n",
                }
            )

        final_directory = (
            Path(temp_dir) / "raw" / "evidence" / "openproject" / "2026" / "06" / "18" / snapshot_id
        )
        self.assertEqual(rename_call_count, 1)
        self.assertEqual(result["evidence_snapshot_id"], snapshot_id)
        self.assertTrue(final_directory.is_dir())
        self.assertEqual(list(final_directory.parent.glob(f"{snapshot_id}.tmp-*")), [])
        snapshot = snapshot_store.get_snapshot(snapshot_id)
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot["evidence_snapshot_id"], snapshot_id)
        self.assertEqual(
            snapshot_store.get_snapshot_payload(snapshot_id),
            {"subject": "Rename fallback snapshot"},
        )

    def test_evidence_snapshot_ids_reject_globs_paths_and_non_strings(self) -> None:
        temp_dir = _paths.fresh_test_dir("openproject-safe-evidence-snapshot-ids")
        snapshot_store = FileEvidenceSnapshotStore(temp_dir)
        valid_snapshot_id = "ev_openproject_safe_id"
        valid_write = {
            "snapshot": {
                "evidence_snapshot_id": valid_snapshot_id,
                "captured_at": "2026-06-18T10:00:00+00:00",
                "source_refs": [
                    {
                        "source_system": "openproject",
                        "source_type": "work_package",
                        "source_id": "42",
                    }
                ],
            },
            "request_payload": {"source_id": "42"},
            "response_payload": {"subject": "Safe snapshot id"},
            "normalized_markdown": "# Safe snapshot id\n",
        }
        snapshot_store.save_snapshot(valid_write)
        baseline_files = {
            path.relative_to(temp_dir).as_posix()
            for path in Path(temp_dir).rglob("*")
            if path.is_file()
        }

        unsafe_ids: list[object] = [
            "",
            "*",
            "?",
            ".",
            "..",
            ".hidden",
            "../other",
            "snapshot/path",
            "snapshot\\path",
            True,
            [valid_snapshot_id],
            {"value": valid_snapshot_id},
        ]
        for unsafe_id in unsafe_ids:
            with self.subTest(unsafe_id=unsafe_id):
                with self.assertRaisesRegex(ValueError, "safe FormOwl identifier"):
                    snapshot_store.get_snapshot(unsafe_id)  # type: ignore[arg-type]
                with self.assertRaisesRegex(ValueError, "safe FormOwl identifier"):
                    snapshot_store.get_snapshot_payload(unsafe_id)  # type: ignore[arg-type]
                invalid_write = {
                    **valid_write,
                    "snapshot": {
                        **valid_write["snapshot"],
                        "evidence_snapshot_id": unsafe_id,
                    },
                }
                with self.assertRaisesRegex(ValueError, "safe FormOwl identifier"):
                    snapshot_store.save_snapshot(invalid_write)

        current_files = {
            path.relative_to(temp_dir).as_posix()
            for path in Path(temp_dir).rglob("*")
            if path.is_file()
        }
        self.assertEqual(current_files, baseline_files)
        self.assertIsNotNone(snapshot_store.get_snapshot(valid_snapshot_id))
        self.assertEqual(
            snapshot_store.get_snapshot_payload(valid_snapshot_id),
            valid_write["response_payload"],
        )

    def test_real_adapter_tools_keep_project_writes_proposal_only(self) -> None:
        temp_dir = _paths.fresh_test_dir("openproject-adapter-proposal-only")
        opener = FakeOpener({})
        tools = ProjectMcpTools(
            adapter_for(opener),
            FileEvidenceSnapshotStore(temp_dir),
            JsonlToolCallLogger(temp_dir / "logs" / "project-mcp-tool-calls.jsonl"),
        )

        envelope = tools.propose_work_item_comment(
            {
                "source_ref": {
                    "source_system": "openproject",
                    "source_type": "work_package",
                    "source_id": "42",
                },
                "body": "Please review before posting.",
                "reason": "Generated from sourced context.",
            }
        )

        self.assertEqual(envelope["status"], "pending_review")
        self.assertIn("No project-system write", envelope["warnings"][0])
        self.assertEqual(opener.requests, [])


def adapter_for(opener: FakeOpener) -> OpenProjectAdapter:
    client = OpenProjectClient(
        base_url=BASE_URL,
        api_token="opapi-token",
        opener=opener,
    )
    return OpenProjectAdapter(
        client=client,
        source_instance="test-openproject",
    )


def work_package(identifier: int) -> dict[str, object]:
    return {
        "_type": "WorkPackage",
        "id": identifier,
        "subject": "Implement real adapter",
        "description": {
            "format": "markdown",
            "raw": "Map OpenProject API responses.",
            "html": "<p>Map OpenProject API responses.</p>",
        },
        "startDate": "2026-06-18",
        "dueDate": "2026-06-30",
        "updatedAt": "2026-06-20T12:30:00Z",
        "_links": {
            "self": {
                "href": f"/api/v3/work_packages/{identifier}",
                "title": "Implement real adapter",
            },
            "project": {"href": "/api/v3/projects/formowl", "title": "FormOwl"},
            "status": {"href": "/api/v3/statuses/7", "title": "In progress"},
            "type": {"href": "/api/v3/types/1", "title": "Feature"},
            "priority": {"href": "/api/v3/priorities/8", "title": "High"},
            "assignee": {"href": "/api/v3/users/3", "title": "process-operator"},
            "responsible": {"href": "/api/v3/users/4", "title": "admin-owner"},
            "activities": {"href": f"/api/v3/work_packages/{identifier}/activities"},
            "relations": {"href": f"/api/v3/work_packages/{identifier}/relations"},
            "attachments": {"href": f"/api/v3/work_packages/{identifier}/attachments"},
        },
    }


def activities_collection() -> dict[str, object]:
    return {
        "_type": "Collection",
        "_embedded": {
            "elements": [
                {
                    "_type": "Activity",
                    "id": 100,
                    "comment": {
                        "format": "markdown",
                        "raw": "Please keep writes proposal-only.",
                    },
                    "createdAt": "2026-06-20T10:00:00Z",
                    "_links": {
                        "self": {"href": "/api/v3/activity/100"},
                        "workPackage": {"href": "/api/v3/work_packages/42"},
                        "user": {"href": "/api/v3/users/4", "title": "admin-owner"},
                    },
                },
                {
                    "_type": "Activity",
                    "id": 101,
                    "details": [{"raw": "Status changed from New to In progress."}],
                    "createdAt": "2026-06-20T11:00:00Z",
                    "_links": {
                        "self": {"href": "/api/v3/activity/101"},
                        "workPackage": {"href": "/api/v3/work_packages/42"},
                        "user": {"href": "/api/v3/users/3", "title": "process-operator"},
                    },
                },
            ]
        },
    }


def relations_collection() -> dict[str, object]:
    return {
        "_type": "Collection",
        "_embedded": {
            "elements": [
                {
                    "_type": "Relation",
                    "id": 7,
                    "type": "follows",
                    "description": "Documentation follows adapter implementation.",
                    "_links": {
                        "self": {"href": "/api/v3/relations/7"},
                        "from": {"href": "/api/v3/work_packages/42", "title": "Adapter"},
                        "to": {"href": "/api/v3/work_packages/43", "title": "Docs"},
                    },
                }
            ]
        },
    }


def attachments_collection() -> dict[str, object]:
    return {
        "_type": "Collection",
        "_embedded": {
            "elements": [
                {
                    "_type": "Attachment",
                    "id": 55,
                    "fileName": "adapter-notes.md",
                    "contentType": "text/markdown",
                    "fileSize": 512,
                    "_links": {
                        "self": {"href": "/api/v3/attachments/55"},
                        "downloadLocation": {"href": "/api/v3/attachments/55/content"},
                    },
                }
            ]
        },
    }


def unsafe_attachments_collection() -> dict[str, object]:
    return {
        "_type": "Collection",
        "_embedded": {
            "elements": [
                _attachment_with_href(56, "file:/tmp/private.txt"),
                _attachment_with_href(57, "storage://bucket/private.txt"),
                _attachment_with_href(58, "https://attacker.example.test/private.txt"),
                _attachment_with_href(59, "//attacker.example.test/private.txt"),
                _attachment_with_href(
                    60,
                    f"{BASE_URL}/api/v3/attachments/60/content?next=file:///tmp/private.txt",
                ),
                _attachment_with_href(
                    61,
                    f"{BASE_URL}/api/v3/attachments/61/content?next=storage%3A%2F%2Fbucket%2Fprivate.txt",
                ),
                _attachment_with_href(
                    62,
                    f"{BASE_URL}/api/v3/attachments/62/content#/tmp/private.txt",
                ),
                _attachment_with_href(
                    63,
                    f"{BASE_URL}/api/v3/attachments/63/file:///tmp/private.txt",
                ),
                _attachment_with_href(
                    64,
                    f"{BASE_URL}/api/v3/attachments/64/content"
                    "?next=storage%253A%252F%252Fbucket%252Fprivate.txt",
                ),
            ]
        },
    }


def malformed_nested_work_package() -> dict[str, object]:
    return {
        "_type": "WorkPackage",
        "id": 45,
        "subject": {"value": "file:///tmp/nested-secret.txt"},
        "description": {"raw": ["storage://nested-bucket/private.txt"]},
        "startDate": {"value": "file:///tmp/nested-secret.txt"},
        "_links": {
            "self": {
                "href": "/api/v3/work_packages/45",
                "title": ["file:///tmp/nested-secret.txt"],
            },
            "project": {
                "href": ["/api/v3/projects/private"],
                "title": {"value": "Private"},
            },
            "status": {"title": {"value": "In progress"}},
            "type": {"title": ["Feature"]},
            "priority": {"title": {"value": "High"}},
            "activities": {"href": {"value": "https://attacker.example.test/activities"}},
            "relations": {"href": ["storage://nested-bucket/private.txt"]},
            "attachments": {"href": {"value": "file:///tmp/nested-secret.txt"}},
        },
    }


def malformed_activities_collection() -> dict[str, object]:
    return {
        "_type": "Collection",
        "_embedded": {
            "elements": [
                {
                    "id": {"value": 200},
                    "comment": {"raw": ["file:///tmp/nested-secret.txt"]},
                    "_links": {
                        "self": {"href": {"value": "/api/v3/activities/200"}},
                        "workPackage": {"href": ["/api/v3/work_packages/45"]},
                    },
                },
                {
                    "id": 201,
                    "comment": {"raw": "file:///tmp/nested-secret.txt"},
                    "_links": {"workPackage": {"href": {"value": "/api/v3/work_packages/45"}}},
                },
                {
                    "id": 202,
                    "comment": {"raw": "Safe linked comment."},
                    "createdAt": {"value": "file:///tmp/nested-secret.txt"},
                    "_links": {
                        "self": {"href": "/api/v3/activities/202"},
                        "workPackage": {"href": "/api/v3/work_packages/45"},
                        "user": {"title": {"value": "storage://nested-bucket/private.txt"}},
                    },
                },
            ]
        },
    }


def malformed_relations_collection() -> dict[str, object]:
    return {
        "_type": "Collection",
        "_embedded": {
            "elements": [
                {
                    "id": 300,
                    "type": {"value": "storage://nested-bucket/private.txt"},
                    "description": ["file:///tmp/nested-secret.txt"],
                    "_links": {
                        "self": {"href": {"value": "/api/v3/relations/300"}},
                        "from": {"href": ["/api/v3/work_packages/45"]},
                        "to": {"href": {"value": "/api/v3/work_packages/46"}},
                    },
                }
            ]
        },
    }


def malformed_attachments_collection() -> dict[str, object]:
    return {
        "_type": "Collection",
        "_embedded": {
            "elements": [
                {
                    "id": {"value": 399},
                    "fileName": "file:///tmp/nested-secret.txt",
                    "_links": {"self": {"href": {"value": "/api/v3/attachments/399"}}},
                },
                {
                    "id": 400,
                    "fileName": {"value": "file:///tmp/nested-secret.txt"},
                    "contentType": ["text/plain"],
                    "fileSize": {"value": 10},
                    "_links": {
                        "self": {"href": ["/api/v3/attachments/400"]},
                        "downloadLocation": {
                            "href": {"value": "storage://nested-bucket/private.txt"}
                        },
                    },
                },
            ]
        },
    }


def _attachment_with_href(identifier: int, href: str) -> dict[str, object]:
    return {
        "_type": "Attachment",
        "id": identifier,
        "fileName": f"attachment-{identifier}.txt",
        "contentType": "text/plain",
        "fileSize": 10,
        "_links": {
            "self": {"href": f"/api/v3/attachments/{identifier}"},
            "downloadLocation": {"href": href},
        },
    }


def project_payload(identifier: str = "formowl") -> dict[str, object]:
    return {
        "_type": "Project",
        "id": 9,
        "identifier": identifier,
        "name": "FormOwl",
        "_links": {
            "self": {"href": f"/api/v3/projects/{identifier}", "title": "FormOwl"},
            "workPackages": {
                "href": f"/api/v3/projects/{parse.quote(identifier, safe='')}/work_packages"
            },
        },
    }


def self_link_only_work_package() -> dict[str, object]:
    return {
        "_type": "WorkPackage",
        "subject": "Encoded HAL identifiers",
        "_links": {
            "self": {
                "href": "/api/v3/work_packages/wp%2F42",
                "title": "Encoded HAL identifiers",
            },
            "project": {
                "href": "/api/v3/projects/formowl%2Fprivate",
                "title": "Private FormOwl",
            },
            "relations": {"href": "/api/v3/work_packages/wp%2F42/relations"},
        },
    }


def encoded_relations_collection() -> dict[str, object]:
    return {
        "_type": "Collection",
        "_embedded": {
            "elements": [
                {
                    "_type": "Relation",
                    "type": "follows",
                    "_links": {
                        "self": {"href": "/api/v3/relations/rel%2F7"},
                        "from": {"href": "/api/v3/work_packages/wp%2F42"},
                        "to": {"href": "/api/v3/work_packages/wp%2F43"},
                    },
                }
            ]
        },
    }


def self_link_only_project() -> dict[str, object]:
    return {
        "_type": "Project",
        "name": "Private FormOwl",
        "_links": {
            "self": {
                "href": "/api/v3/projects/formowl%2Fprivate",
                "title": "Private FormOwl",
            },
            "workPackages": {"href": "/api/v3/projects/formowl%2Fprivate/work_packages"},
        },
    }


if __name__ == "__main__":
    unittest.main()
