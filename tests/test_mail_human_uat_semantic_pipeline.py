from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from typing import Any, Mapping, Sequence

import _paths  # noqa: F401
from formowl_contract import (
    ContractValidationError,
    SemanticSchemaAliasMap,
    semantic_request_json_schema,
    validate_semantic_request,
)
from formowl_mail.human_uat_orchestrator import (
    CodexAppServerConversationModel,
    CodexAppServerThread,
    CodexAppServerTurn,
    _is_completed_web_search_item,
    _parse_semantic_extraction,
)


class _RecordingSemanticTransport:
    """A no-I/O app-server substitute that records each isolation boundary."""

    def __init__(
        self,
        turns: Sequence[Mapping[str, Any]],
        *,
        runtime_workspace: Path | None = None,
        allows_public_web_search: bool = False,
    ) -> None:
        self._turns = list(turns)
        self.runtime_workspace = runtime_workspace
        self.allows_public_web_search = allows_public_web_search
        self.start_calls: list[dict[str, Any]] = []
        self.turn_calls: list[dict[str, Any]] = []
        self.deleted_threads: list[str] = []
        self.closed = False

    def start_thread(
        self,
        *,
        model: str | None,
        cwd: Path,
        base_instructions: str,
        developer_instructions: str,
        dynamic_tools: Sequence[Mapping[str, Any]],
    ) -> CodexAppServerThread:
        thread_id = f"thread_{len(self.start_calls) + 1}"
        self.start_calls.append(
            {
                "model": model,
                "cwd": cwd,
                "base_instructions": base_instructions,
                "developer_instructions": developer_instructions,
                "dynamic_tools": tuple(dynamic_tools),
                "thread_id": thread_id,
            }
        )
        return CodexAppServerThread(
            thread_id=thread_id,
            model_name=model or "semantic-test-model",
        )

    def run_turn(
        self,
        *,
        thread_id: str,
        user_text: str,
        additional_context: Mapping[str, Mapping[str, str]],
        output_schema: Mapping[str, Any],
        reasoning_effort: str,
        client_metadata: Mapping[str, str],
        tool_handler: Any,
    ) -> CodexAppServerTurn:
        if not self._turns:
            raise AssertionError("semantic transport received an unexpected turn")
        step = dict(self._turns.pop(0))
        self.turn_calls.append(
            {
                "thread_id": thread_id,
                "user_text": user_text,
                "additional_context": {
                    key: dict(value) for key, value in additional_context.items()
                },
                "output_schema": dict(output_schema),
                "reasoning_effort": reasoning_effort,
                "client_metadata": dict(client_metadata),
            }
        )
        if step.pop("request_dynamic_tool", False):
            tool_handler(
                "search_formowl_evidence",
                {
                    "query_text": "legacy lexical request",
                    "required_terms": [],
                    "sort": "relevance",
                    "limit": 1,
                },
            )
        return CodexAppServerTurn(
            thread_id=thread_id,
            turn_id=f"turn_{len(self.turn_calls)}",
            final_message=str(step["final_message"]),
            tool_invocations=(),
            completed_item_types=tuple(step.get("completed_item_types", ())),
            completed_web_search_item_types=tuple(step.get("completed_web_search_item_types", ())),
        )

    def delete_thread(self, thread_id: str) -> None:
        self.deleted_threads.append(thread_id)

    def close(self) -> None:
        self.closed = True


def _semantic_ontology() -> SemanticSchemaAliasMap:
    """A governed public vocabulary deliberately unrelated to business aliases."""

    return SemanticSchemaAliasMap(
        object_aliases={
            "vessel record": ("vessel record", "vessels"),
        },
        predicate_aliases={
            "vessel record": ("vessel record", "vessels"),
            "resonance state": ("resonance state", "state"),
        },
        value_aliases={
            "resonance state": {
                "quiescent": ("quiescent",),
            },
        },
        value_domains={"resonance state": "closed_enum"},
    )


def _extraction(
    candidates: Sequence[tuple[str, str]],
    *,
    response_kind: str = "execute_semantic",
    answer_text: str = "semantic planning",
) -> str:
    return json.dumps(
        {
            "response_kind": response_kind,
            "answer_text": answer_text,
            "display_format": "list",
            "terminology_candidates": [
                {"span": span, "classification": classification}
                for span, classification in candidates
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _grounding(
    term: str,
    normalized_output: str,
    *,
    status: str = "grounded",
    kind: str = "governed_schema_concept",
    text_prefix: str = "",
) -> str:
    payload = {
        "grounding": {
            "term": term,
            "status": status,
            "kind": kind,
            "normalized_output": normalized_output,
        }
    }
    return text_prefix + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _semantic_request() -> dict[str, Any]:
    return {
        "query_class": "attribute_filter",
        "object_type_mention": "vessel record",
        "predicate_mention": "resonance state",
        "operator": "equals",
        "value_mention": "quiescent",
        "projection_mention": "vessel record",
        "cardinality": "all_matching",
        "page_size": 100,
        "page_number": 1,
    }


def _open_value_ontology() -> SemanticSchemaAliasMap:
    return SemanticSchemaAliasMap(
        object_aliases={"catalog record": ("catalog record", "catalogs")},
        predicate_aliases={
            "catalog record": ("catalog record", "catalogs"),
            "origin zone": ("origin zone", "origin"),
        },
        value_aliases={},
        value_domains={"origin zone": "open_public_value"},
    )


def _open_value_request() -> dict[str, Any]:
    return {
        "query_class": "attribute_filter",
        "object_type_mention": "catalog record",
        "predicate_mention": "origin zone",
        "operator": "equals",
        "value_mention": "northern archipelago",
        "projection_mention": "catalog record",
        "cardinality": "all_matching",
        "page_size": 100,
        "page_number": 1,
    }


def _semantic_result() -> dict[str, Any]:
    return {
        "status": "ok",
        "results": [],
        "total_result_count": 0,
        "displayed_result_count": 0,
        "projection": {"output_format": "list"},
    }


class MailHumanUatSemanticPipelineTests(unittest.TestCase):
    def _run_model(
        self,
        *,
        private_turns: Sequence[Mapping[str, Any]],
        web_turns: Sequence[Mapping[str, Any]],
        user_text: str,
        latest_evidence: Mapping[str, Any] | None = None,
        ontology: SemanticSchemaAliasMap | None = None,
    ) -> tuple[
        Any,
        _RecordingSemanticTransport,
        _RecordingSemanticTransport,
        list[Mapping[str, Any]],
    ]:
        formowl_calls: list[Mapping[str, Any]] = []

        def invoke_formowl(arguments: Mapping[str, Any]) -> Mapping[str, Any]:
            if not isinstance(arguments, Mapping):
                raise AssertionError("semantic executor must receive an MCP argument object")
            formowl_calls.append(dict(arguments))
            return _semantic_result()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            private_workspace = root / "private-workspace"
            web_workspace = root / "public-web-workspace"
            private_workspace.mkdir()
            web_workspace.mkdir()
            private_transport = _RecordingSemanticTransport(
                private_turns,
                runtime_workspace=private_workspace,
            )
            web_transport = _RecordingSemanticTransport(
                web_turns,
                runtime_workspace=web_workspace,
                allows_public_web_search=True,
            )
            model = CodexAppServerConversationModel(
                private_transport,
                workspace_dir=private_workspace,
                ontology_context=ontology or _semantic_ontology(),
                web_grounding_transport=web_transport,
            )
            try:
                outcome = model.respond(
                    history=(),
                    user_text=user_text,
                    latest_evidence=latest_evidence,
                    safety_identifier="semantic-test",
                    evidence_tool=invoke_formowl,
                )
            finally:
                model.close()

        self.assertTrue(private_transport.closed)
        self.assertTrue(web_transport.closed)
        return outcome, private_transport, web_transport, formowl_calls

    def test_already_canonical_safe_public_terms_reach_web_then_one_semantic_mcp_request(
        self,
    ) -> None:
        """A governed public ontology, not a domain dictionary, drives the plan."""

        request = "Return all vessels whose resonance state is quiescent."
        plan = _semantic_request()
        # The concrete transport has already normalized these authoritative
        # completions before it constructs CodexAppServerTurn:
        # app-server item/completed webSearch; Responses completed
        # web_search_call.
        completed_web_search_provenance = (
            ("app-server item/completed webSearch", "webSearch"),
            ("Responses completed web_search_call", "web_search_call"),
        )
        for provenance, completed_web_search_item_type in completed_web_search_provenance:
            with self.subTest(
                provenance=provenance,
                completed_web_search_item_type=completed_web_search_item_type,
            ):
                outcome, private, web, formowl_calls = self._run_model(
                    private_turns=(
                        {
                            "final_message": _extraction(
                                (
                                    ("vessels", "public_terminology"),
                                    ("resonance state", "public_terminology"),
                                    ("quiescent", "public_terminology"),
                                ),
                                answer_text="",
                            ),
                        },
                        {"final_message": json.dumps(plan, separators=(",", ":"))},
                    ),
                    web_turns=(
                        {
                            "final_message": _grounding(
                                "vessels",
                                "vessel record",
                            ),
                            "completed_web_search_item_types": (completed_web_search_item_type,),
                        },
                        {
                            "final_message": _grounding(
                                "resonance state",
                                "resonance state",
                            ),
                            "completed_web_search_item_types": (completed_web_search_item_type,),
                        },
                        {
                            "final_message": _grounding(
                                "quiescent",
                                "quiescent",
                            ),
                            "completed_web_search_item_types": (completed_web_search_item_type,),
                        },
                    ),
                    user_text=request,
                )

                self.assertEqual(outcome.response_kind, "answer")
                self.assertEqual(len(private.turn_calls), 2)
                self.assertEqual(len(web.turn_calls), 3)
                self.assertTrue(private.start_calls)
                self.assertTrue(web.start_calls)
                self.assertTrue(
                    all(not call["dynamic_tools"] for call in private.start_calls),
                    "private semantic stages must not expose a FormOwl or web tool",
                )
                self.assertTrue(
                    all(not call["dynamic_tools"] for call in web.start_calls),
                    "public web grounding must not expose FormOwl tools",
                )

                extraction_schema = private.turn_calls[0]["output_schema"]
                self.assertIn("terminology_candidates", extraction_schema["properties"])
                self.assertNotIn("semantic_request", extraction_schema["properties"])
                self.assertEqual(private.turn_calls[0]["user_text"], request)
                self.assertEqual(
                    set(private.turn_calls[1]["output_schema"]["properties"]),
                    set(semantic_request_json_schema()["properties"]),
                )

                web_payload = _serialized_transport_turn(web.turn_calls[0])
                web_inputs = [json.loads(turn["user_text"]) for turn in web.turn_calls]
                self.assertNotIn(request, web_payload)
                self.assertEqual(
                    [payload["term"] for payload in web_inputs],
                    ["vessels", "resonance state", "quiescent"],
                )
                self.assertTrue(all(turn["additional_context"] == {} for turn in web.turn_calls))
                private_plan_input = json.loads(private.turn_calls[1]["user_text"])
                self.assertEqual(
                    private_plan_input["public_web_groundings"],
                    [
                        {
                            "term": "vessels",
                            "kind": "governed_schema_concept",
                            "normalized_output": "vessel record",
                        },
                        {
                            "term": "resonance state",
                            "kind": "governed_schema_concept",
                            "normalized_output": "resonance state",
                        },
                        {
                            "term": "quiescent",
                            "kind": "governed_schema_concept",
                            "normalized_output": "quiescent",
                        },
                    ],
                )
                self.assertIn(
                    "web search for every",
                    web.start_calls[0]["base_instructions"],
                )

                self.assertEqual(len(formowl_calls), 1)
                self.assertEqual(formowl_calls[0], plan)
                self.assertEqual(
                    validate_semantic_request(formowl_calls[0]),
                    plan,
                )
                self.assertEqual(
                    set(formowl_calls[0]), set(semantic_request_json_schema()["required"])
                )

    def test_only_execute_semantic_may_have_empty_answer_text(self) -> None:
        execute_payload = _parse_semantic_extraction(
            _extraction(
                (("quiescent", "public_terminology"),),
                answer_text="",
            )
        )
        self.assertEqual(execute_payload["response_kind"], "execute_semantic")
        self.assertEqual(execute_payload["answer_text"], "")

        for response_kind in ("answer", "clarification", "render_prior_evidence"):
            with self.subTest(response_kind=response_kind):
                with self.assertRaises(ContractValidationError):
                    _parse_semantic_extraction(
                        _extraction(
                            (),
                            response_kind=response_kind,
                            answer_text="",
                        )
                    )

    def test_private_names_and_unmistakable_identifiers_never_reach_web(self) -> None:
        """Misclassification cannot release name-like or opaque private spans."""

        candidates = (
            ("Taylor Rowe", "public_terminology"),
            ("taylor.rowe@example.invalid", "public_terminology"),
            ("https://example.invalid/private", "public_terminology"),
            ("/vault/private-note.txt", "public_terminology"),
            ("1f2e3d4c5b6a7980", "public_terminology"),
        )
        for sensitive_span, classification in candidates:
            with self.subTest(sensitive_span=sensitive_span):
                request = "Return vessels whose resonance state is quiescent. " + sensitive_span
                outcome, private, web, formowl_calls = self._run_model(
                    private_turns=(
                        {
                            "final_message": _extraction(
                                (
                                    ("quiescent", "public_terminology"),
                                    (sensitive_span, classification),
                                )
                            )
                        },
                    ),
                    web_turns=(),
                    user_text=request,
                    latest_evidence={
                        "results": [{"snippet": "private evidence must not be released"}]
                    },
                )

                self.assertEqual(outcome.response_kind, "clarification")
                self.assertFalse(formowl_calls)
                self.assertFalse(web.turn_calls)
                self.assertIn(
                    request,
                    _serialized_transport_turn(private.turn_calls[0]),
                )

    def test_unlisted_open_public_value_has_per_term_receipts_then_one_callback(self) -> None:
        """Open values are runtime-grounded, not pre-enumerated in ontology."""

        plan = _open_value_request()
        outcome, private, web, formowl_calls = self._run_model(
            private_turns=(
                {
                    "final_message": _extraction(
                        (
                            ("catalogs", "public_terminology"),
                            ("origin", "public_terminology"),
                            ("northern archipelago", "public_terminology"),
                        )
                    )
                },
                {"final_message": json.dumps(plan, separators=(",", ":"))},
            ),
            web_turns=(
                {
                    "final_message": _grounding("catalogs", "catalog record"),
                    "completed_web_search_item_types": ("websearch",),
                },
                {
                    "final_message": _grounding("origin", "origin zone"),
                    "completed_web_search_item_types": ("websearch",),
                },
                {
                    "final_message": _grounding(
                        "northern archipelago",
                        "northern archipelago",
                        kind="open_public_value",
                    ),
                    "completed_web_search_item_types": ("websearch",),
                },
            ),
            user_text=("Return all catalogs whose origin is northern archipelago."),
            ontology=_open_value_ontology(),
        )

        self.assertEqual(outcome.response_kind, "answer")
        self.assertEqual(formowl_calls, [plan])
        self.assertEqual(len(web.turn_calls), 3)
        planner_input = json.loads(private.turn_calls[1]["user_text"])
        self.assertEqual(
            planner_input["public_web_groundings"][-1],
            {
                "term": "northern archipelago",
                "kind": "open_public_value",
                "normalized_output": "northern archipelago",
            },
        )

    def test_missing_or_wrong_slot_receipt_fails_closed_before_callback(self) -> None:
        """The planner cannot substitute a count of searches for slot binding."""

        plan = _semantic_request()
        outcome, _private, web, formowl_calls = self._run_model(
            private_turns=(
                {
                    "final_message": _extraction(
                        (
                            ("vessels", "public_terminology"),
                            ("resonance state", "public_terminology"),
                            ("quiescent", "public_terminology"),
                        )
                    )
                },
                {"final_message": json.dumps(plan, separators=(",", ":"))},
            ),
            web_turns=(
                {
                    "final_message": _grounding("vessels", "vessel record"),
                    "completed_web_search_item_types": ("websearch",),
                },
                {
                    "final_message": _grounding("resonance state", "resonance state"),
                    "completed_web_search_item_types": ("websearch",),
                },
                {
                    "final_message": _grounding("quiescent", "wrong state"),
                    "completed_web_search_item_types": ("websearch",),
                },
            ),
            user_text="Return all vessels whose resonance state is quiescent.",
        )

        self.assertEqual(outcome.response_kind, "clarification")
        self.assertFalse(formowl_calls)
        self.assertEqual(len(web.turn_calls), 3)

    def test_ordinary_reference_misclassified_protected_literal_cannot_bypass_web(self) -> None:
        outcome, _private, web, formowl_calls = self._run_model(
            private_turns=(
                {"final_message": _extraction((("northern archipelago", "protected_literal"),))},
            ),
            web_turns=(),
            user_text="Return all catalogs whose origin is northern archipelago.",
            ontology=_open_value_ontology(),
        )

        self.assertEqual(outcome.response_kind, "clarification")
        self.assertFalse(web.turn_calls)
        self.assertFalse(formowl_calls)

    def test_noncompleted_web_provenance_returns_clarification_without_mcp_call(self) -> None:
        """Started, in-progress, and text-only web claims are not evidence."""

        rejected_provenance = (
            ("app-server started", ("webSearch:started",)),
            ("responses in progress", ("web_search_call:in_progress",)),
            ("text-only claim", ("agentMessage",)),
        )
        for label, completed_item_types in rejected_provenance:
            with self.subTest(label=label):
                outcome, _private, _web, formowl_calls = self._run_model(
                    private_turns=(
                        {
                            "final_message": _extraction(
                                (
                                    ("vessels", "public_terminology"),
                                    ("resonance state", "public_terminology"),
                                    ("dormant", "public_terminology"),
                                )
                            ),
                        },
                    ),
                    web_turns=(
                        {
                            "final_message": _grounding(
                                "vessels",
                                "vessel record",
                                text_prefix=("webSearch completed according to prose only\n"),
                            ),
                            "completed_item_types": completed_item_types,
                        },
                        {
                            "final_message": _grounding(
                                "vessels",
                                "vessel record",
                                text_prefix=("webSearch completed according to prose only\n"),
                            ),
                            "completed_item_types": completed_item_types,
                        },
                    ),
                    user_text="Return all vessels whose resonance state is dormant.",
                )

                self.assertEqual(outcome.response_kind, "clarification")
                self.assertFalse(formowl_calls)
                self.assertEqual(len(_web.turn_calls), 2)

    def test_missing_web_receipt_retries_once_then_calls_exactly_one_mcp(self) -> None:
        """A transient skipped search retries grounding, never the MCP."""

        plan = _semantic_request()
        outcome, private, web, formowl_calls = self._run_model(
            private_turns=(
                {
                    "final_message": _extraction(
                        (
                            ("vessels", "public_terminology"),
                            ("resonance state", "public_terminology"),
                            ("quiescent", "public_terminology"),
                        )
                    )
                },
                {"final_message": json.dumps(plan, separators=(",", ":"))},
            ),
            web_turns=(
                {
                    "final_message": _grounding("vessels", "vessel record"),
                    "completed_web_search_item_types": (),
                },
                {
                    "final_message": _grounding("vessels", "vessel record"),
                    "completed_web_search_item_types": ("websearch",),
                },
                {
                    "final_message": _grounding("resonance state", "resonance state"),
                    "completed_web_search_item_types": ("websearch",),
                },
                {
                    "final_message": _grounding("quiescent", "quiescent"),
                    "completed_web_search_item_types": ("websearch",),
                },
            ),
            user_text="Return all vessels whose resonance state is quiescent.",
        )

        self.assertEqual(outcome.response_kind, "answer")
        self.assertEqual(formowl_calls, [plan])
        self.assertEqual(len(private.turn_calls), 2)
        self.assertEqual(len(web.turn_calls), 4)
        self.assertEqual(
            [
                (
                    record.stage,
                    record.reason_code,
                    record.attempt_count,
                    record.completed_web_search_count,
                )
                for record in outcome.semantic_telemetry
                if record.stage == "public_web_grounding"
            ],
            [
                ("public_web_grounding", "web_search_incomplete", 1, 0),
                ("public_web_grounding", "ok", 2, 3),
            ],
        )

    def test_missing_web_receipt_twice_fails_closed_without_mcp(self) -> None:
        """A semantic answer cannot bypass missing completed-search receipts."""

        outcome, private, web, formowl_calls = self._run_model(
            private_turns=(
                {
                    "final_message": _extraction(
                        (
                            ("vessels", "public_terminology"),
                            ("resonance state", "public_terminology"),
                            ("quiescent", "public_terminology"),
                        )
                    )
                },
            ),
            web_turns=(
                {
                    "final_message": _grounding("vessels", "vessel record"),
                    "completed_web_search_item_types": (),
                },
                {
                    "final_message": _grounding("vessels", "vessel record"),
                    "completed_web_search_item_types": (),
                },
            ),
            user_text="Return all vessels whose resonance state is quiescent.",
        )

        self.assertEqual(outcome.response_kind, "clarification")
        self.assertFalse(formowl_calls)
        self.assertEqual(len(private.turn_calls), 1)
        self.assertEqual(len(web.turn_calls), 2)
        self.assertEqual(
            [
                (
                    record.stage,
                    record.reason_code,
                    record.attempt_count,
                    record.completed_web_search_count,
                )
                for record in outcome.semantic_telemetry
                if record.stage == "public_web_grounding"
            ],
            [
                ("public_web_grounding", "web_search_incomplete", 1, 0),
                ("public_web_grounding", "web_search_incomplete", 2, 0),
            ],
        )

    def test_ambiguous_public_grounding_returns_clarification_without_mcp_call(self) -> None:
        outcome, _private, _web, formowl_calls = self._run_model(
            private_turns=(
                {
                    "final_message": _extraction(
                        (
                            ("vessels", "public_terminology"),
                            ("resonance state", "public_terminology"),
                            ("dormant", "public_terminology"),
                        )
                    ),
                },
            ),
            web_turns=(
                {
                    "final_message": _grounding(
                        "vessels",
                        "vessel record",
                    ),
                    "completed_web_search_item_types": ("websearch",),
                },
                {
                    "final_message": _grounding(
                        "resonance state",
                        "resonance state",
                    ),
                    "completed_web_search_item_types": ("websearch",),
                },
                {
                    "final_message": _grounding(
                        "dormant",
                        "quiescent",
                        status="ambiguous",
                    ),
                    "completed_web_search_item_types": ("websearch",),
                },
            ),
            user_text="Return all vessels whose resonance state is dormant.",
        )

        self.assertEqual(outcome.response_kind, "clarification")
        self.assertFalse(formowl_calls)

    def test_only_completed_web_item_shapes_count_as_public_search_evidence(self) -> None:
        self.assertTrue(_is_completed_web_search_item({"type": "webSearch"}))
        self.assertTrue(
            _is_completed_web_search_item({"type": "web_search_call", "status": "completed"})
        )
        self.assertFalse(
            _is_completed_web_search_item({"type": "web_search_call", "status": "in_progress"})
        )

    def test_web_grounder_must_return_existing_canonical_concept(self) -> None:
        outcome, _private, _web, formowl_calls = self._run_model(
            private_turns=(
                {
                    "final_message": _extraction((("quiescent", "public_terminology"),)),
                },
            ),
            web_turns=(
                {
                    "final_message": _grounding(
                        "quiescent",
                        "state",
                    ),
                    "completed_web_search_item_types": ("websearch",),
                },
            ),
            user_text="Return all vessels whose resonance state is quiescent.",
        )

        self.assertEqual(outcome.response_kind, "clarification")
        self.assertFalse(formowl_calls)

    def test_protected_value_still_requires_governed_nonliteral_slots(self) -> None:
        protected_identifier = "1f2e3d4c5b6a7980"
        invalid_plan = {
            **_semantic_request(),
            "predicate_mention": "unmapped attribute",
            "value_mention": protected_identifier,
        }
        outcome, _private, web, formowl_calls = self._run_model(
            private_turns=(
                {
                    "final_message": _extraction(((protected_identifier, "protected_literal"),)),
                },
                {"final_message": json.dumps(invalid_plan, separators=(",", ":"))},
            ),
            web_turns=(),
            user_text=f"Return all vessel records matching {protected_identifier}.",
        )

        self.assertEqual(outcome.response_kind, "clarification")
        self.assertFalse(web.turn_calls)
        self.assertFalse(formowl_calls)


def _serialized_transport_turn(turn: Mapping[str, Any]) -> str:
    return json.dumps(turn, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


if __name__ == "__main__":
    unittest.main()
