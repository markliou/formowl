from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
VERIFIER_PATH = ROOT / "verify-browser-contract-r8.py"
SPEC = importlib.util.spec_from_file_location("verify_browser_contract_r8", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)


class BrowserContractR8Tests(unittest.TestCase):
    def _response(self, answer: str) -> dict[str, object]:
        return {
            "assistant_text": answer,
            "claim_state": "CANDIDATE_MATCHES",
            "canonical_kg": False,
            "source_count": 0,
            "citation_count": 0,
            "trace": {
                "retrieval_path": "mail_authorized_structured_set",
                "mcp_call_count": 1,
            },
            "orchestration": {
                "action": "call_formowl_tool",
                "response_kind": "answer",
                "formowl_tool_called": True,
                "model": "gpt-test-codex",
            },
        }

    def _health(self) -> dict[str, object]:
        return {
            "status": "ready",
            "surface": "mail_human_uat",
            "conversation_orchestrator_enabled": True,
            "conversation_model": "gpt-test-codex",
        }

    @staticmethod
    def _summary(chat_count: int, tool_count: int) -> dict[str, object]:
        return {
            "status": "ready",
            "chat_count": chat_count,
            "formowl_tool_call_count": tool_count,
        }

    def _verify(
        self,
        answer: str,
        values: tuple[str, ...],
        *,
        health: dict[str, object] | None = None,
        before: dict[str, object] | None = None,
        response: dict[str, object] | None = None,
        after: dict[str, object] | None = None,
        expected_fingerprint: str | None = None,
        expected_count: int | None = None,
    ) -> dict[str, object]:
        with patch.object(
            verifier,
            "_request_json",
            side_effect=[
                health or self._health(),
                before or self._summary(10, 20),
                response or self._response(answer),
                after or self._summary(11, 21),
            ],
        ):
            return verifier.verify_browser_contract(
                base_url="http://127.0.0.1:8088",
                health_path="/api/health",
                summary_path="/api/session-summary",
                query_path="/api/chat",
                query=verifier.DEFAULT_QUERY,
                expected_fingerprint=(
                    expected_fingerprint or verifier._projection_fingerprint(values)
                ),
                expected_count=expected_count if expected_count is not None else len(values),
            )

    def test_report_matches_deployment_gate_shape(self) -> None:
        values = ("PART-01", "PART-02", "PART-03")
        report = self._verify(
            "找到 3 個符合項目：\n" + "\n".join(f"- {value}" for value in values),
            values,
        )
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["query_route"], "browser_to_sidecar_to_one_mcp")
        self.assertEqual(report["mcp_call_count"], 1)
        self.assertEqual(report["chat_count_delta"], 1)
        self.assertEqual(report["formowl_tool_call_count_delta"], 1)
        self.assertEqual(report["distinct_projection_count"], 3)
        self.assertEqual(report["distinct_bullet_count"], 3)
        self.assertEqual(report["retrieval_path"], "mail_authorized_structured_set")
        self.assertEqual(report["claim_state"], "CANDIDATE_MATCHES")
        self.assertFalse(report["canonical_kg"])
        self.assertEqual(report["source_count"], 0)
        self.assertEqual(report["citation_count"], 0)
        self.assertEqual(
            report["fingerprint"],
            verifier._projection_fingerprint(values),
        )

    def test_table_wall_is_rejected_even_before_valid_bullets(self) -> None:
        values = ("PART-01", "PART-02", "PART-03")
        answer = "\n".join(
            [
                "| Part | COO |",
                "| --- | --- |",
                *[f"- {value}" for value in values],
            ]
        )
        with self.assertRaisesRegex(verifier.VerificationFailure, "table"):
            self._verify(answer, values)

    def test_sources_and_raw_dumps_are_rejected(self) -> None:
        values = ("PART-01", "PART-02", "PART-03")
        for extra in ("Sources:", "來源：synthetic", "structuredContent: synthetic"):
            with self.subTest(extra=extra):
                answer = "\n".join([*[f"- {value}" for value in values], extra])
                with self.assertRaises(verifier.VerificationFailure):
                    self._verify(answer, values)

    def test_placeholder_and_truncated_bullets_are_rejected(self) -> None:
        for invalid in ("TBD", "PART-03...", "continued"):
            with self.subTest(invalid=invalid):
                values = ("PART-01", "PART-02", invalid)
                answer = "\n".join(f"- {value}" for value in values)
                with self.assertRaisesRegex(
                    verifier.VerificationFailure,
                    "placeholder or truncated bullet",
                ):
                    self._verify(answer, values)

    def test_markdown_formatting_cannot_bypass_duplicate_detection(self) -> None:
        values = ("PART-01", "PART-01", "PART-03")
        for formatted in ("*PART-01*", "_PART-01_", "__PART-01__", "~~PART-01~~"):
            with self.subTest(formatted=formatted):
                answer = "\n".join(["- PART-01", f"- {formatted}", "- PART-03"])
                with self.assertRaisesRegex(
                    verifier.VerificationFailure,
                    "duplicate bullets",
                ):
                    self._verify(answer, values)

    def test_route_requires_ready_sidecar_and_exactly_one_tool_delta(self) -> None:
        values = ("PART-01", "PART-02", "PART-03")
        answer = "\n".join(f"- {value}" for value in values)
        for kwargs in (
            {
                "health": {
                    "status": "ready",
                    "surface": "mail_human_uat",
                    "conversation_orchestrator_enabled": False,
                    "conversation_model": "gpt-test-codex",
                }
            },
            {"after": self._summary(11, 22)},
            {"after": self._summary(12, 21)},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(verifier.VerificationFailure):
                    self._verify(answer, values, **kwargs)

    def test_response_requires_one_mcp_call_and_matching_sidecar_model(self) -> None:
        values = ("PART-01", "PART-02", "PART-03")
        answer = "\n".join(f"- {value}" for value in values)
        for field, value in (
            ("mcp_call_count", 2),
            ("mcp_call_count", True),
            ("model", "different-model"),
            ("formowl_tool_called", False),
        ):
            response = self._response(answer)
            target = response["trace"] if field == "mcp_call_count" else response["orchestration"]
            target[field] = value
            with self.subTest(field=field, value=value):
                with self.assertRaises(verifier.VerificationFailure):
                    self._verify(answer, values, response=response)

    def test_exact_count_and_fingerprint_are_enforced(self) -> None:
        values = ("PART-01", "PART-02", "PART-03")
        answer = "\n".join(f"- {value}" for value in values)
        with self.assertRaisesRegex(
            verifier.VerificationFailure,
            "bullet count",
        ):
            self._verify(answer, values, expected_count=4)
        with self.assertRaisesRegex(
            verifier.VerificationFailure,
            "fingerprint",
        ):
            self._verify(
                answer,
                values,
                expected_fingerprint="sha256:" + "0" * 64,
            )

    def test_failure_report_does_not_serialize_answer_values(self) -> None:
        values = ("PART-01", "PART-02", "PRIVATE-MARKER...")
        answer = "\n".join(f"- {value}" for value in values)
        with tempfile.TemporaryDirectory() as temporary:
            report_path = Path(temporary) / "failure.json"
            with (
                patch.object(
                    verifier,
                    "_request_json",
                    side_effect=[
                        self._health(),
                        self._summary(10, 20),
                        self._response(answer),
                        self._summary(11, 21),
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
                        "--expected-count",
                        "3",
                        "--expected-fingerprint",
                        verifier._projection_fingerprint(values),
                    ],
                ),
            ):
                with self.assertRaises(SystemExit) as raised:
                    verifier.main()
            self.assertEqual(raised.exception.code, 1)
            report_text = report_path.read_text(encoding="utf-8")
            self.assertNotIn("PRIVATE-MARKER", report_text)
            self.assertNotIn("PART-01", report_text)

    def test_frozen_diagnostic_constants_remain_exact(self) -> None:
        self.assertEqual(verifier.EXPECTED_BULLET_COUNT, 77)
        self.assertEqual(
            verifier.EXPECTED_FINGERPRINT,
            "sha256:d791cfcd424910ed766f4092b51c6a9c1f1b756943935544134e626301e7c705",
        )
        self.assertEqual(verifier.DEFAULT_QUERY, "把COO是日本的料號取出")


if __name__ == "__main__":
    unittest.main()
