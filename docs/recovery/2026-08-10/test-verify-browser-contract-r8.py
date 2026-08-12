from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parent
VERIFIER_PATH = ROOT / "verify-browser-contract-r8.py"
SPEC = importlib.util.spec_from_file_location("verify_browser_contract_r8", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)

PAGE_HTML = """
<!doctype html>
<html>
<body>
<script>
function renderAssistantResult(payload, holder) {
  holder.replaceChildren();
  const results = Array.isArray(payload.results) ? payload.results : [];
  const answerItems = Array.isArray(payload.answer_items)
    ? payload.answer_items.filter((item) => typeof item === "string" && item.trim())
    : [];
  if (answerItems.length) {
    const list = document.createElement("ol");
    list.className = "semantic-answer-list";
    for (const [index, value] of answerItems.entries()) {
      const item = document.createElement("li");
      item.className = "semantic-answer-item";
      const order = document.createElement("span");
      order.className = "semantic-answer-order";
      order.textContent = String(index + 1);
      const content = document.createElement("span");
      content.textContent = value;
      item.append(order, content);
      list.appendChild(item);
    }
    holder.appendChild(list);
  }
  if (!results.length) {
    addFeedbackControls(holder, payload.query_id);
    scrollToLatest();
    return;
  }
  const disclosure = document.createElement("button");
  disclosure.className = "sources-disclosure";
  disclosure.textContent = "查看來源";
  holder.appendChild(disclosure);
}
async function ask() {}
</script>
</body>
</html>
"""


class BrowserContractR8Tests(unittest.TestCase):
    @staticmethod
    def _values() -> tuple[str, ...]:
        return ("PART-01", "PART-02", "PART-03")

    @staticmethod
    def _summary(tool_count: int) -> dict[str, object]:
        return {"formowl_tool_call_count": tool_count}

    def _response(
        self,
        values: tuple[object, ...] | None = None,
    ) -> dict[str, object]:
        return {
            "answer_items": list(values if values is not None else self._values()),
            "results": [],
            "retrieval_path": "mail_authorized_structured_set",
            "claim_state": "CANDIDATE_MATCHES",
            "canonical_kg": False,
        }

    def _verify(
        self,
        *,
        response: dict[str, object] | None = None,
        page_html: str = PAGE_HTML,
        before: dict[str, object] | None = None,
        after: dict[str, object] | None = None,
        expected_fingerprint: str | None = None,
        expected_count: int | None = None,
        query_elapsed_seconds: float = 1.0,
    ) -> tuple[dict[str, object], object]:
        values = self._values()
        response_payload = response or self._response()
        request_mock = Mock(
            side_effect=[
                before or self._summary(20),
                response_payload,
                after or self._summary(21),
            ]
        )
        answer_items = tuple(response_payload.get("answer_items", []))
        dom_report = {
            "semantic_answer_item_count": len(answer_items),
            "semantic_answer_item_hashes": [
                verifier._item_hash(value) for value in answer_items if isinstance(value, str)
            ],
            "distinct_semantic_answer_item_hash_count": len(
                {verifier._item_hash(value) for value in answer_items if isinstance(value, str)}
            ),
            "source_citation_ui_present": False,
            "raw_json_present": False,
            "table_wall_present": False,
        }
        with (
            patch.object(verifier, "_request_text", return_value=page_html),
            patch.object(verifier, "_request_json", request_mock),
            patch.object(verifier, "_render_browser_dom", return_value=dom_report),
            patch.object(
                verifier.time,
                "monotonic",
                side_effect=[100.0, 100.0 + query_elapsed_seconds],
            ),
        ):
            report = verifier.verify_browser_contract(
                base_url="http://127.0.0.1:8088",
                page_path="/",
                summary_path="/api/session-summary",
                query_path="/api/chat",
                query=verifier.DEFAULT_QUERY,
                expected_fingerprint=(
                    expected_fingerprint or verifier._projection_fingerprint(values)
                ),
                expected_count=expected_count if expected_count is not None else len(values),
            )
        return report, request_mock

    def test_current_response_and_rendered_dom_contract_passes(self) -> None:
        report, request_mock = self._verify()

        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["query_route"], "browser_to_sidecar_to_one_mcp")
        self.assertEqual(report["retrieval_path"], "mail_authorized_structured_set")
        self.assertEqual(report["claim_state"], "CANDIDATE_MATCHES")
        self.assertFalse(report["canonical_kg"])
        self.assertEqual(report["results_count"], 0)
        self.assertEqual(report["query_elapsed_ms"], 1000.0)
        self.assertEqual(report["formowl_tool_call_count_delta"], 1)
        self.assertEqual(report["answer_item_count"], 3)
        self.assertEqual(report["dom_semantic_answer_item_count"], 3)
        self.assertEqual(report["fingerprint"], verifier._projection_fingerprint(self._values()))

        chat_body = request_mock.call_args_list[1].args[1]
        self.assertEqual(chat_body["query_text"], verifier.DEFAULT_QUERY)
        self.assertRegex(chat_body["visitor_id"], r"^uatvisitor_[0-9a-f]{32}$")
        self.assertRegex(chat_body["session_id"], r"^uatsession_[0-9a-f]{32}$")
        self.assertEqual(chat_body["sequence"], 1)
        self.assertEqual(chat_body["source"], "composer")
        self.assertEqual(
            verifier._same_origin("http://127.0.0.1:8088/api/chat"),
            "http://127.0.0.1:8088",
        )

        class Response:
            status = 200

            def __enter__(self) -> Response:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            @staticmethod
            def read() -> bytes:
                return b"{}"

        with patch.object(verifier, "urlopen", return_value=Response()) as urlopen:
            verifier._request_bytes(
                "http://127.0.0.1:8088/api/chat",
                accept="application/json",
                body={"query_text": "test"},
                timeout_seconds=1,
            )
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Origin"), "http://127.0.0.1:8088")

    def test_frozen_contract_constants_remain_exact(self) -> None:
        self.assertEqual(verifier.EXPECTED_ANSWER_ITEM_COUNT, 77)
        self.assertEqual(
            verifier.EXPECTED_FINGERPRINT,
            "sha256:d791cfcd424910ed766f4092b51c6a9c1f1b756943935544134e626301e7c705",
        )
        self.assertEqual(verifier.EXPECTED_RETRIEVAL_PATH, "mail_authorized_structured_set")
        self.assertEqual(verifier.EXPECTED_CLAIM_STATE, "CANDIDATE_MATCHES")
        self.assertEqual(verifier.DEFAULT_QUERY, "把COO是日本的料號取出")

    def test_response_requires_exact_current_metadata_contract(self) -> None:
        for field, invalid in (
            ("results", [{}]),
            ("results", None),
            ("retrieval_path", "legacy_path"),
            ("claim_state", "FOUND"),
            ("canonical_kg", True),
            ("canonical_kg", 0),
        ):
            with self.subTest(field=field, invalid=invalid):
                response = self._response()
                response[field] = invalid
                with self.assertRaises(verifier.VerificationFailure):
                    self._verify(response=response)

    def test_answer_items_require_exact_count_and_distinct_readable_text(self) -> None:
        cases = (
            (("PART-01", "PART-02"), "count"),
            (("PART-01", "part-01", "PART-03"), "duplicate"),
            (("PART-01", " ", "PART-03"), "empty"),
            (("PART-01", None, "PART-03"), "non-text"),
        )
        for values, reason in cases:
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(verifier.VerificationFailure, reason):
                    self._verify(response=self._response(values))

    def test_placeholder_and_visibly_truncated_items_are_rejected(self) -> None:
        for invalid in ("TBD", "continued", "PART-03...", "PART-03…"):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(
                    verifier.VerificationFailure,
                    "placeholder or truncated",
                ):
                    self._verify(response=self._response(("PART-01", "PART-02", invalid)))

    def test_raw_json_table_and_markup_items_are_rejected(self) -> None:
        for invalid in (
            '{"part":"PART-03"}',
            "| PART-03 | Japan |",
            "```json",
            "<table>PART-03</table>",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(
                    verifier.VerificationFailure,
                    "raw or table-shaped",
                ):
                    self._verify(response=self._response(("PART-01", "PART-02", invalid)))

    def test_session_formowl_tool_call_delta_must_be_exactly_one(self) -> None:
        for before, after in ((20, 20), (20, 22), (20, 19)):
            with self.subTest(before=before, after=after):
                with self.assertRaisesRegex(verifier.VerificationFailure, "exactly one"):
                    self._verify(
                        before=self._summary(before),
                        after=self._summary(after),
                    )
        for invalid in (True, -1, "20", None):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(verifier.VerificationFailure, "tool count"):
                    self._verify(
                        before={"formowl_tool_call_count": invalid},
                        after=self._summary(21),
                    )
        with self.assertRaisesRegex(verifier.VerificationFailure, "360-second"):
            self._verify(query_elapsed_seconds=360.0)

    def test_dom_requires_exact_semantic_item_count_order_and_content(self) -> None:
        values = self._values()
        valid = {
            "semantic_answer_item_count": len(values),
            "semantic_answer_item_hashes": [verifier._item_hash(value) for value in values],
            "distinct_semantic_answer_item_hash_count": len(values),
            "source_citation_ui_present": False,
            "raw_json_present": False,
            "table_wall_present": False,
        }
        invalid_reports = (
            {**valid, "semantic_answer_item_count": 2},
            {
                **valid,
                "semantic_answer_item_hashes": list(reversed(valid["semantic_answer_item_hashes"])),
            },
            {
                **valid,
                "semantic_answer_item_hashes": [
                    *valid["semantic_answer_item_hashes"][:2],
                    verifier._item_hash("PART..."),
                ],
            },
            {**valid, "distinct_semantic_answer_item_hash_count": 2},
        )
        for report in invalid_reports:
            with self.subTest(report=report):
                with self.assertRaisesRegex(verifier.VerificationFailure, "DOM"):
                    verifier._validate_dom_contract(report, answer_items=values)

    def test_dom_rejects_initial_source_or_citation_ui(self) -> None:
        values = self._values()
        report = {
            "semantic_answer_item_count": len(values),
            "semantic_answer_item_hashes": [verifier._item_hash(value) for value in values],
            "distinct_semantic_answer_item_hash_count": len(values),
            "source_citation_ui_present": True,
            "raw_json_present": False,
            "table_wall_present": False,
        }
        with self.assertRaisesRegex(verifier.VerificationFailure, "source or citation"):
            verifier._validate_dom_contract(report, answer_items=values)

    def test_dom_rejects_raw_json_and_table_walls(self) -> None:
        values = self._values()
        valid = {
            "semantic_answer_item_count": len(values),
            "semantic_answer_item_hashes": [verifier._item_hash(value) for value in values],
            "distinct_semantic_answer_item_hash_count": len(values),
            "source_citation_ui_present": False,
            "raw_json_present": False,
            "table_wall_present": False,
        }
        for field, reason in (
            ("raw_json_present", "raw JSON"),
            ("table_wall_present", "table wall"),
        ):
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(verifier.VerificationFailure, reason):
                    verifier._validate_dom_contract(
                        {**valid, field: True},
                        answer_items=values,
                    )

    def test_browser_page_must_expose_the_real_render_function(self) -> None:
        with self.assertRaisesRegex(
            verifier.VerificationFailure,
            "renderAssistantResult",
        ):
            verifier._extract_render_function("<html><body>missing renderer</body></html>")
        with (
            patch.object(verifier.shutil, "which", return_value=None),
            self.assertRaisesRegex(verifier.VerificationFailure, "requires Node.js"),
        ):
            verifier._render_browser_dom(PAGE_HTML, self._response())

    def test_failure_report_never_serializes_answer_values(self) -> None:
        private_marker = "PRIVATE-MARKER..."
        with tempfile.TemporaryDirectory() as temporary:
            report_path = Path(temporary) / "failure.json"
            with (
                patch.object(verifier, "_request_text", return_value=PAGE_HTML),
                patch.object(
                    verifier,
                    "_request_json",
                    side_effect=[
                        self._summary(20),
                        self._response(("PART-01", "PART-02", private_marker)),
                        self._summary(21),
                    ],
                ),
                patch.object(
                    sys,
                    "argv",
                    [
                        str(VERIFIER_PATH),
                        "--base-url",
                        "http://127.0.0.1:8088",
                        "--report",
                        str(report_path),
                    ],
                ),
            ):
                with self.assertRaises(SystemExit) as raised:
                    verifier.main()
            self.assertEqual(raised.exception.code, 1)
            report_text = report_path.read_text(encoding="utf-8")
            self.assertNotIn("PRIVATE-MARKER", report_text)
            self.assertNotIn("PART-01", report_text)
            self.assertRegex(report_text, re.escape('"status":"failed"'))


if __name__ == "__main__":
    unittest.main()
