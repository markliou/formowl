from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_VERIFIER_PATH = (
    _REPOSITORY_ROOT / "docs" / "recovery" / "2026-08-10" / "verify-browser-contract-r8.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "verify_browser_contract_r8_focused",
    _VERIFIER_PATH,
)
assert _SPEC is not None and _SPEC.loader is not None
verifier = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = verifier
_SPEC.loader.exec_module(verifier)

_MCP_COMMITMENT = "sha256:" + "1" * 64
_FINAL_COMMITMENT = "sha256:" + "2" * 64
_RAW_CONTENT_SENTINEL = "SYNTHETIC_RAW_DOCUMENT_SENTINEL_C_94d8b2"


def _summary(
    attempted: int,
    successful: int,
    *,
    commitments: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "mcp_attempted_call_count": attempted,
        "mcp_successful_call_count": successful,
    }
    if commitments:
        payload.update(
            {
                "mcp_response_commitment": _MCP_COMMITMENT,
                "tool_result_reinject_commitment": _MCP_COMMITMENT,
                "final_response_commitment": _FINAL_COMMITMENT,
            }
        )
    return payload


def _chat_response() -> dict[str, object]:
    return {
        "status": "ok",
        "assistant_text": "Ａuthorized   answer",
        "document_payload_projection": "formowl_document_uat_public_metadata_v1",
        "result_count": 1,
        "results": [
            {
                "source_label": "authorized-document-0001",
                "segment_label": "table-0001-rows-0001-0001",
                "subject": "Authorized document table 1",
                "content_char_count": 27,
                "content_utf8_bytes": 27,
                "content_sha256": "sha256:" + "3" * 64,
                "sent_at": None,
                "source_kind": "authorized_document_export",
            }
        ],
        "answer_items": [],
        "orchestration": {
            "action": "call_formowl_tool",
            "response_kind": "answer",
            "formowl_tool_called": True,
            "answer_fallback_used": False,
            "tool_name": "search_formowl_evidence",
            "mcp_attempted_call_count": 1,
            "mcp_successful_call_count": 1,
            "mcp_response_commitment": _MCP_COMMITMENT,
            "tool_result_reinject_commitment": _MCP_COMMITMENT,
            "final_response_commitment": _FINAL_COMMITMENT,
        },
        "claim_boundary": {
            "document_first": True,
            "existing_export_only": True,
            "read_only": True,
            "pst_or_extractor_invoked": False,
            "kg_or_ontology_invoked": False,
            "oracle_or_expected_answer_used": False,
            "canonical_graph_write_performed": False,
            "production_ready": False,
        },
    }


class VerifyBrowserContractR8FocusedTests(unittest.TestCase):
    def test_exact_session_summary_counters_require_one_attempt_and_success(self) -> None:
        counts = verifier._validate_count_deltas(
            _summary(7, 7, commitments=False),
            _summary(8, 8, commitments=True),
        )

        self.assertEqual(counts["attempted_delta"], 1)
        self.assertEqual(counts["successful_delta"], 1)
        for before, after in (
            ((7, 7), (9, 8)),
            ((7, 7), (8, 9)),
            ((7, 7), (8, 7)),
        ):
            with self.subTest(before=before, after=after):
                with self.assertRaises(verifier.VerificationFailure):
                    verifier._validate_count_deltas(
                        _summary(*before, commitments=False),
                        _summary(*after, commitments=True),
                    )

    def test_commitments_are_exact_nonempty_equal_and_match_summary(self) -> None:
        commitments = verifier._validate_commitments(
            _chat_response(),
            _summary(8, 8, commitments=True),
        )

        self.assertEqual(commitments["mcp_response"], _MCP_COMMITMENT)
        self.assertEqual(commitments["reinject_tool_result"], _MCP_COMMITMENT)
        self.assertEqual(commitments["final_response"], _FINAL_COMMITMENT)

        mismatched = _chat_response()
        mismatched["orchestration"] = {
            **mismatched["orchestration"],
            "tool_result_reinject_commitment": "sha256:" + "3" * 64,
        }
        with self.assertRaisesRegex(
            verifier.VerificationFailure,
            "commitments differ",
        ):
            verifier._validate_commitments(
                mismatched,
                _summary(8, 8, commitments=True),
            )

        missing_summary = _summary(8, 8, commitments=False)
        with self.assertRaisesRegex(
            verifier.VerificationFailure,
            "commitment is missing",
        ):
            verifier._validate_commitments(_chat_response(), missing_summary)

    def test_turn_orchestration_proves_one_dynamic_tool_and_one_success(self) -> None:
        report = verifier._validate_turn_orchestration(_chat_response())

        self.assertEqual(report["dynamic_tool_invocation_count"], 1)
        self.assertEqual(report["mcp_attempted_call_count"], 1)
        self.assertEqual(report["mcp_successful_call_count"], 1)
        self.assertFalse(report["answer_fallback_used"])

        for field, value in (
            ("mcp_attempted_call_count", 2),
            ("mcp_successful_call_count", 0),
            ("formowl_tool_called", False),
            ("answer_fallback_used", True),
            ("tool_name", "unexpected_tool"),
        ):
            invalid = _chat_response()
            invalid["orchestration"] = {
                **invalid["orchestration"],
                field: value,
            }
            with self.subTest(field=field, value=value):
                with self.assertRaises(verifier.VerificationFailure):
                    verifier._validate_turn_orchestration(invalid)

    def test_document_first_response_exposes_only_safe_metadata_and_browser_output(
        self,
    ) -> None:
        report = verifier._validate_document_first_browser_observation(
            _chat_response(),
            ("Authorized answer\n" "authorized-document-0001\n" "sha256:" + ("3" * 64)),
            forbidden_raw_sentinel=_RAW_CONTENT_SENTINEL,
        )

        self.assertEqual(report["result_count"], 1)
        self.assertEqual(report["answer_items_count"], 0)
        self.assertTrue(report["authorized_existing_export_only"])
        self.assertTrue(report["raw_document_fields_absent"])
        self.assertTrue(report["captured_network_json_redacted"])
        self.assertTrue(report["rendered_dom_redacted"])
        self.assertFalse(report["pst_or_extractor_invoked"])
        self.assertFalse(report["kg_or_ontology_invoked"])
        self.assertFalse(report["oracle_or_expected_answer_used"])

        invalid_answer_items = _chat_response()
        invalid_answer_items["answer_items"] = ["precomputed answer"]
        with self.assertRaisesRegex(
            verifier.VerificationFailure,
            "precomputed answer items",
        ):
            verifier._validate_document_first_response(invalid_answer_items)

        invalid_claim = _chat_response()
        invalid_claim["claim_boundary"] = {
            **invalid_claim["claim_boundary"],
            "kg_or_ontology_invoked": True,
        }
        with self.assertRaisesRegex(
            verifier.VerificationFailure,
            "claim boundary",
        ):
            verifier._validate_document_first_response(invalid_claim)

        missing_metadata = _chat_response()
        missing_metadata["results"] = []
        missing_metadata["result_count"] = 0
        with self.assertRaisesRegex(
            verifier.VerificationFailure,
            "no readable document result",
        ):
            verifier._validate_document_first_response(missing_metadata)

        leaked_network = _chat_response()
        leaked_network["results"][0]["content"] = _RAW_CONTENT_SENTINEL
        with self.assertRaisesRegex(
            verifier.VerificationFailure,
            "raw document fields",
        ):
            verifier._validate_document_first_browser_observation(
                leaked_network,
                "Authorized answer",
                forbidden_raw_sentinel=_RAW_CONTENT_SENTINEL,
            )
        with self.assertRaisesRegex(
            verifier.VerificationFailure,
            "raw document content",
        ):
            verifier._validate_document_first_browser_observation(
                _chat_response(),
                "Authorized answer " + _RAW_CONTENT_SENTINEL,
                forbidden_raw_sentinel=_RAW_CONTENT_SENTINEL,
            )

    def test_browser_flow_requires_new_dom_answer_equal_to_chat_assistant_text(
        self,
    ) -> None:
        valid_probe = {
            "addedAssistantCount": 1,
            "answer": "Authorized answer",
            "error": "",
            "sendDisabled": False,
        }
        _FakeCdpConnection.event_batches = [
            [],
            [_request_event()],
            [_response_event(), _loading_finished_event()],
        ]

        with (
            mock.patch.object(verifier, "_CdpConnection", _FakeCdpConnection),
            mock.patch.object(
                verifier,
                "_runtime_value",
                side_effect=[True, True, True, True, valid_probe, valid_probe],
            ),
            mock.patch.object(
                verifier,
                "_browser_fetch_json",
                side_effect=[
                    _summary(7, 7, commitments=False),
                    _summary(8, 8, commitments=True),
                ],
            ),
        ):
            before, after, response, answer, _elapsed = verifier._run_browser_flow(
                websocket_url="ws://127.0.0.1/devtools/browser/test",
                page_url="http://127.0.0.1:8088/",
                summary_path="/api/session-summary",
                query_path="/api/chat",
                query="test query",
                timeout_seconds=5,
            )

        self.assertEqual(before["mcp_attempted_call_count"], 7)
        self.assertEqual(after["mcp_successful_call_count"], 8)
        self.assertEqual(response["assistant_text"], "Ａuthorized   answer")
        self.assertEqual(answer, "Authorized answer")

        for field, value, reason in (
            ("addedAssistantCount", 0, "newly rendered"),
            ("answer", "Unrelated existing text", "does not match"),
        ):
            invalid_probe = {**valid_probe, field: value}
            _FakeCdpConnection.event_batches = [
                [],
                [_request_event(), _response_event(), _loading_finished_event()],
            ]
            with (
                mock.patch.object(verifier, "_CdpConnection", _FakeCdpConnection),
                mock.patch.object(
                    verifier,
                    "_runtime_value",
                    side_effect=[True, True, True, True, invalid_probe],
                ),
                mock.patch.object(
                    verifier,
                    "_browser_fetch_json",
                    return_value=_summary(7, 7, commitments=False),
                ),
                self.assertRaisesRegex(verifier.VerificationFailure, reason),
            ):
                verifier._run_browser_flow(
                    websocket_url="ws://127.0.0.1/devtools/browser/test",
                    page_url="http://127.0.0.1:8088/",
                    summary_path="/api/session-summary",
                    query_path="/api/chat",
                    query="test query",
                    timeout_seconds=5,
                )

    def test_browser_flow_bootstraps_observer_in_current_context(self) -> None:
        connection = _FakeCdpConnection("", 1)

        with (
            mock.patch.object(
                verifier,
                "_CdpConnection",
                return_value=connection,
            ),
            mock.patch.object(verifier, "_wait_for", return_value=True) as wait_for,
            mock.patch.object(
                verifier,
                "_runtime_value",
                return_value=False,
            ) as runtime_value,
            self.assertRaisesRegex(
                verifier.VerificationFailure,
                "browser observer bootstrap failed",
            ),
        ):
            verifier._run_browser_flow(
                websocket_url="ws://127.0.0.1/devtools/browser/test",
                page_url="http://127.0.0.1:8088/",
                summary_path="/api/session-summary",
                query_path="/api/chat",
                query="test query",
                timeout_seconds=5,
            )

        observer_source = verifier._observer_script()
        registrations = [
            params
            for method, params, _session_id in connection.calls
            if method == "Page.addScriptToEvaluateOnNewDocument"
        ]
        self.assertEqual(registrations, [{"source": observer_source}])
        self.assertNotIn("__formowlR8Observer", wait_for.call_args.args[2])
        self.assertEqual(
            wait_for.call_args.kwargs["failure"],
            "UAT page did not expose the chat controls",
        )
        self.assertEqual(runtime_value.call_args.args[2], observer_source)

    def test_browser_flow_reports_controls_missing_before_observer_bootstrap(
        self,
    ) -> None:
        connection = _FakeCdpConnection("", 1)

        with (
            mock.patch.object(
                verifier,
                "_CdpConnection",
                return_value=connection,
            ),
            mock.patch.object(
                verifier,
                "_wait_for",
                side_effect=verifier.VerificationFailure(
                    "UAT page did not expose the chat controls"
                ),
            ) as wait_for,
            mock.patch.object(verifier, "_runtime_value") as runtime_value,
            self.assertRaisesRegex(
                verifier.VerificationFailure,
                "UAT page did not expose the chat controls",
            ),
        ):
            verifier._run_browser_flow(
                websocket_url="ws://127.0.0.1/devtools/browser/test",
                page_url="http://127.0.0.1:8088/",
                summary_path="/api/session-summary",
                query_path="/api/chat",
                query="test query",
                timeout_seconds=5,
            )

        self.assertNotIn("__formowlR8Observer", wait_for.call_args.args[2])
        runtime_value.assert_not_called()

    def test_cdp_network_filter_accepts_only_same_origin_chat_post(self) -> None:
        request_ids: set[str] = set()
        successful_ids: set[str] = set()
        completed_ids: set[str] = set()
        connection = _FakeCdpConnection("", 1)
        connection.events = [
            _request_event(url="http://unrelated.test/api/chat"),
            _request_event(
                request_id="summary",
                url="http://127.0.0.1:8088/api/session-summary",
            ),
            _request_event(),
            _response_event(),
            _loading_finished_event(),
        ]

        verifier._collect_chat_network_events(
            connection,
            session_id="session",
            page_url="http://127.0.0.1:8088/",
            query_path="/api/chat",
            request_ids=request_ids,
            successful_response_ids=successful_ids,
            completed_ids=completed_ids,
        )

        self.assertEqual(request_ids, {"chat"})
        self.assertEqual(successful_ids, {"chat"})
        self.assertEqual(completed_ids, {"chat"})

    def test_verifier_has_no_frozen_answer_contract_and_rejects_oracle_fields(
        self,
    ) -> None:
        source = _VERIFIER_PATH.read_text(encoding="utf-8").casefold()

        self.assertNotIn("expected_answer_item_count", source)
        self.assertNotIn("expected_fingerprint", source)
        self.assertNotIn("expected_answer_items", source)
        self.assertTrue(
            {
                "expected_answer",
                "expected_count",
                "final_answer",
                "fingerprint",
                "oracle",
            }.issubset(verifier._FORBIDDEN_DOCUMENT_RESPONSE_KEYS)
        )

        for forbidden_field in verifier._FORBIDDEN_DOCUMENT_RESPONSE_KEYS:
            invalid = _chat_response()
            invalid[forbidden_field] = "forbidden"
            with self.subTest(forbidden_field=forbidden_field):
                with self.assertRaisesRegex(
                    verifier.VerificationFailure,
                    "forbidden oracle field",
                ):
                    verifier._validate_document_first_response(invalid)


class _FakeCdpConnection:
    event_batches: list[list[dict[str, object]]] = []

    def __init__(self, _websocket_url: str, _timeout_seconds: float) -> None:
        self.closed = False
        self.events: list[dict[str, object]] = []
        self.calls: list[tuple[str, object, object]] = []

    def call(self, method, params=None, *, session_id=None):
        self.calls.append((method, params, session_id))
        if method == "Target.createBrowserContext":
            return {"browserContextId": "context"}
        if method == "Target.createTarget":
            return {"targetId": "target"}
        if method == "Target.attachToTarget":
            return {"sessionId": "session"}
        if method == "Page.addScriptToEvaluateOnNewDocument":
            return {"identifier": "observer-script"}
        if method == "Network.getResponseBody":
            return {
                "body": __import__("json").dumps(_chat_response()),
                "base64Encoded": False,
            }
        return {}

    def take_events(self):
        if self.events:
            events = self.events
            self.events = []
            return events
        if self.event_batches:
            return self.event_batches.pop(0)
        return []

    def close(self) -> None:
        self.closed = True


def _request_event(
    *,
    request_id: str = "chat",
    url: str = "http://127.0.0.1:8088/api/chat",
) -> dict[str, object]:
    return {
        "sessionId": "session",
        "method": "Network.requestWillBeSent",
        "params": {
            "requestId": request_id,
            "request": {"method": "POST", "url": url},
        },
    }


def _response_event(*, request_id: str = "chat") -> dict[str, object]:
    return {
        "sessionId": "session",
        "method": "Network.responseReceived",
        "params": {
            "requestId": request_id,
            "response": {"status": 200},
        },
    }


def _loading_finished_event(*, request_id: str = "chat") -> dict[str, object]:
    return {
        "sessionId": "session",
        "method": "Network.loadingFinished",
        "params": {"requestId": request_id},
    }


if __name__ == "__main__":
    unittest.main()
