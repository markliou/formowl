from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace

from formowl_contract import ContractValidationError, sha256_json
from formowl_evaluator.replay import (
    ReplayCase,
    execute_jsonrpc_replays,
    load_replay_artifact,
    load_replay_artifact_for_repair,
    repair_jsonrpc_replays,
    validate_replay_artifact,
    write_replay_artifact,
)
from formowl_gateway import (
    SemanticGatewaySession,
    SemanticMcpGateway,
    SemanticMcpJsonRpcGateway,
)


class MailMcpReplayTests(unittest.TestCase):
    def test_replay_binds_complete_tools_list_and_validates_result_semantics(self) -> None:
        gateways = _gateways(_handler)
        cases = [
            ReplayCase("sha256:" + "1" * 64, "owner", "supplier delay", "owner_match", 5),
            ReplayCase("sha256:" + "2" * 64, "owner", "unknown supplier", "no_match", 5),
            ReplayCase(
                "sha256:" + "3" * 64,
                "denied",
                "supplier delay",
                "permission_denied",
                5,
            ),
        ]

        artifact = execute_jsonrpc_replays(
            cases,
            gateway_for=gateways,
            mail_import_session_id="mailimport_replay",
        )

        self.assertEqual(artifact.unique_evidence_case_count, 3)
        self.assertEqual(
            artifact.tools_list_response_hash, sha256_json(artifact.tools_list_response)
        )
        self.assertEqual(artifact.public_rows[0]["response_status"], "ok")
        self.assertEqual(artifact.public_rows[0]["evidence_count"], 1)
        self.assertEqual(artifact.public_rows[1]["response_status"], "ok")
        self.assertEqual(artifact.public_rows[1]["evidence_count"], 0)
        self.assertEqual(artifact.public_rows[2]["response_status"], "permission_denied")
        validate_replay_artifact(artifact)

    def test_stateful_follow_ups_are_response_derived_and_session_bound(self) -> None:
        gateways_by_user: dict[str, SemanticMcpJsonRpcGateway] = {}
        gateway_for = _gateways(_handler, gateways_by_user)
        cases = [
            ReplayCase("sha256:" + "4" * 64, "owner", "supplier delay", "owner_match", 5),
            ReplayCase("sha256:" + "5" * 64, "owner", "unknown supplier", "no_match", 4),
            ReplayCase(
                "sha256:" + "6" * 64,
                "denied",
                "supplier delay",
                "permission_denied",
                5,
            ),
        ]

        artifact = execute_jsonrpc_replays(
            cases,
            gateway_for=gateway_for,
            mail_import_session_id="mailimport_replay",
            stateful_follow_up_case_fingerprints={case.case_fingerprint for case in cases},
        )

        rows = {row["result_kind"]: row for row in artifact.public_rows}
        self.assertEqual(rows["owner_match"]["follow_up_style"], "evidence_refinement")
        self.assertEqual(rows["no_match"]["follow_up_style"], "zero_match_broadening")
        self.assertEqual(rows["permission_denied"]["follow_up_style"], "permission_safe_retry")
        private = {row["case_fingerprint"]: row for row in artifact.private_rows}
        owner_follow_up = private[cases[0].case_fingerprint]["steps"][1]["request"]
        no_match_follow_up = private[cases[1].case_fingerprint]["steps"][1]["request"]
        denied_follow_up = private[cases[2].case_fingerprint]["steps"][1]["request"]
        self.assertIn(
            "Supplier A deadline blocker owner next action",
            owner_follow_up["params"]["arguments"]["query_text"],
        )
        self.assertEqual(owner_follow_up["params"]["arguments"]["limit"], 3)
        self.assertEqual(no_match_follow_up["params"]["arguments"]["query_text"], "unknown")
        self.assertEqual(no_match_follow_up["params"]["arguments"]["limit"], 8)
        self.assertEqual(denied_follow_up["params"]["arguments"]["limit"], 1)
        self.assertEqual(len(gateways_by_user["owner"].leak_transcript()), 5)
        self.assertEqual(len(gateways_by_user["denied"].leak_transcript()), 2)
        validate_replay_artifact(artifact)

    def test_result_kind_mismatch_is_bound_as_evaluation_outcome(self) -> None:
        gateway_for = _gateways(_handler)
        artifact = execute_jsonrpc_replays(
            [ReplayCase("sha256:" + "7" * 64, "owner", "unknown", "owner_match", 5)],
            gateway_for=gateway_for,
            mail_import_session_id="mailimport_replay",
        )

        public_row = artifact.public_rows[0]
        first_step = artifact.private_rows[0]["steps"][0]
        self.assertEqual(public_row["expected_result_kind"], "owner_match")
        self.assertEqual(public_row["semantic_kind"], "no_match")
        self.assertFalse(public_row["result_kind_match"])
        self.assertEqual(first_step["expected_result_kind"], "owner_match")
        self.assertEqual(first_step["semantic_kind"], "no_match")
        self.assertFalse(first_step["result_kind_match"])
        validate_replay_artifact(artifact)

    def test_expected_permission_denial_must_be_enforced(self) -> None:
        with self.assertRaisesRegex(
            ContractValidationError,
            "expected permission denial was not enforced",
        ):
            execute_jsonrpc_replays(
                [
                    ReplayCase(
                        "sha256:" + "7" * 64,
                        "owner",
                        "unknown",
                        "permission_denied",
                        5,
                    )
                ],
                gateway_for=_gateways(_handler),
                mail_import_session_id="mailimport_replay",
            )

    def test_invalid_result_semantics_are_rejected(self) -> None:
        invalid_payloads = [
            (
                "owner match without citations",
                {
                    "status": "ok",
                    "evidence_snippets": [{"snippet_hash": "sha256:" + "1" * 64}],
                    "citations": [],
                    "redaction_counts": {"hidden_bundles": 0, "hidden_messages": 0},
                    "warnings": [],
                },
                "owner_match",
                "lacks citations",
            ),
            (
                "visible no match with hidden evidence",
                {
                    "status": "ok",
                    "evidence_snippets": [],
                    "citations": [],
                    "redaction_counts": {"hidden_bundles": 1, "hidden_messages": 1},
                    "warnings": ["no_visible_mail_evidence_matched"],
                },
                "no_match",
                "must not report hidden evidence",
            ),
            (
                "permission denial exposing evidence",
                {
                    "status": "permission_denied",
                    "evidence_snippets": [{"snippet_hash": "sha256:" + "2" * 64}],
                    "citations": [],
                    "redaction_counts": {"hidden_bundles": 1, "hidden_messages": 1},
                    "warnings": ["mail_evidence_permission_denied"],
                },
                "permission_denied",
                "exposed evidence",
            ),
        ]

        for name, payload, result_kind, error_pattern in invalid_payloads:

            def invalid_handler(_: dict[str, object], payload: dict[str, object] = payload):
                return {
                    "mail_import_session_id": "mailimport_replay",
                    "query_hash": "sha256:" + "3" * 64,
                    **payload,
                }

            with (
                self.subTest(name=name),
                self.assertRaisesRegex(ContractValidationError, error_pattern),
            ):
                execute_jsonrpc_replays(
                    [
                        ReplayCase(
                            "sha256:" + "4" * 64,
                            "owner",
                            "status",
                            result_kind,
                            5,
                        )
                    ],
                    gateway_for=_gateways(invalid_handler),
                    mail_import_session_id="mailimport_replay",
                )

        def error_handler(_: dict[str, object]) -> dict[str, object]:
            raise RuntimeError("boom")

        with self.assertRaisesRegex(ContractValidationError, "tool error"):
            execute_jsonrpc_replays(
                [ReplayCase("sha256:" + "8" * 64, "owner", "status", "owner_match", 5)],
                gateway_for=_gateways(error_handler),
                mail_import_session_id="mailimport_replay",
            )

    def test_coherent_rehash_tamper_fails_unchanged_external_trust_anchor(self) -> None:
        original = execute_jsonrpc_replays(
            [ReplayCase("sha256:" + "9" * 64, "owner", "status", "owner_match", 5)],
            gateway_for=_gateways(_handler),
            mail_import_session_id="mailimport_replay",
        )

        def changed_handler(input_data: dict[str, object]) -> dict[str, object]:
            result = _handler(input_data)
            if result["status"] == "ok" and result["evidence_snippets"]:
                result["evidence_snippets"] = [
                    {
                        "subject": "Supplier B",
                        "snippet_hash": "sha256:" + "a" * 64,
                    }
                ]
                result["citations"] = [{"citation_hash": "sha256:" + "b" * 64}]
            return result

        coherently_rehashed = execute_jsonrpc_replays(
            [ReplayCase("sha256:" + "9" * 64, "owner", "status", "owner_match", 5)],
            gateway_for=_gateways(changed_handler),
            mail_import_session_id="mailimport_replay",
        )
        validate_replay_artifact(coherently_rehashed)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "private" / "replay.private.json"
            anchor_path = write_replay_artifact(path, original)
            path.write_text(
                __import__("json").dumps(coherently_rehashed.to_private_dict()),
                encoding="utf-8",
            )
            path.chmod(0o600)
            with self.assertRaisesRegex(ContractValidationError, "external trust anchor"):
                load_replay_artifact(path, trust_anchor_path=anchor_path)

    def test_private_replay_and_trust_anchor_round_trip_are_mode_0600(self) -> None:
        artifact = execute_jsonrpc_replays(
            [ReplayCase("sha256:" + "c" * 64, "owner", "status", "owner_match", 5)],
            gateway_for=_gateways(_handler),
            mail_import_session_id="mailimport_replay",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "private" / "replay.private.json"
            anchor_path = write_replay_artifact(path, artifact)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(anchor_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(load_replay_artifact(path), artifact)

    def test_private_replay_rejects_symlink_artifact_or_trust_anchor(self) -> None:
        artifact = execute_jsonrpc_replays(
            [ReplayCase("sha256:" + "d" * 64, "owner", "status", "owner_match", 5)],
            gateway_for=_gateways(_handler),
            mail_import_session_id="mailimport_replay",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "target.json"
            target.write_text("{}", encoding="utf-8")
            artifact_link = root / "artifact.json"
            anchor_link = root / "anchor.json"
            os.symlink(target, artifact_link)
            os.symlink(target, anchor_link)
            with self.assertRaisesRegex(ContractValidationError, "unsafe"):
                write_replay_artifact(artifact_link, artifact)
            with self.assertRaisesRegex(ContractValidationError, "unsafe"):
                write_replay_artifact(
                    root / "artifact.private.json", artifact, trust_anchor_path=anchor_link
                )

    def test_repair_reuses_only_matching_valid_rows_and_reexecutes_invalid_rows(self) -> None:
        cases = [
            ReplayCase("sha256:" + "e" * 64, "owner", "supplier delay", "owner_match", 5),
            ReplayCase("sha256:" + "f" * 64, "owner", "status", "owner_match", 5),
        ]
        existing = execute_jsonrpc_replays(
            cases,
            gateway_for=_gateways(_handler),
            mail_import_session_id="mailimport_replay",
        )
        invalid_existing = _with_coherent_error_row(existing, row_index=1)
        handler_calls: list[dict[str, object]] = []

        def recording_handler(input_data: dict[str, object]) -> dict[str, object]:
            handler_calls.append(input_data)
            return _handler(input_data)

        repaired, summary = repair_jsonrpc_replays(
            invalid_existing,
            cases,
            gateway_for=_gateways(recording_handler),
            mail_import_session_id="mailimport_replay",
        )

        self.assertEqual(summary, {"reused_case_count": 1, "reexecuted_case_count": 1})
        self.assertEqual(len(handler_calls), 1)
        self.assertEqual(
            repaired.private_rows[0]["response_hash"], existing.private_rows[0]["response_hash"]
        )
        validate_replay_artifact(repaired)

        changed_cases = [replace(cases[0], query_text="different query"), cases[1]]
        handler_calls.clear()
        repaired_changed, changed_summary = repair_jsonrpc_replays(
            repaired,
            changed_cases,
            gateway_for=_gateways(recording_handler),
            mail_import_session_id="mailimport_replay",
        )
        self.assertEqual(changed_summary, {"reused_case_count": 1, "reexecuted_case_count": 1})
        self.assertEqual(len(handler_calls), 1)
        validate_replay_artifact(repaired_changed)

    def test_repair_loader_accepts_legacy_rows_but_revalidates_each_row(self) -> None:
        cases = [
            ReplayCase("sha256:" + "5" * 64, "owner", "supplier delay", "owner_match", 5),
            ReplayCase("sha256:" + "6" * 64, "owner", "status", "owner_match", 5),
        ]
        artifact = execute_jsonrpc_replays(
            cases,
            gateway_for=_gateways(_handler),
            mail_import_session_id="mailimport_replay",
        )
        artifact = _with_coherent_error_row(artifact, row_index=1)
        legacy_payload = {
            "artifact_type": "mail_evidence_jsonrpc_replay_private",
            "unique_evidence_case_count": 2,
            "tools_list_schema_hash": "sha256:" + "0" * 64,
            "public_rows": [dict(row) for row in artifact.public_rows],
            "private_rows": [
                {
                    key: value
                    for key, value in row.items()
                    if key not in {"steps", "trajectory_root_hash", "private_row_hash"}
                }
                for row in artifact.private_rows
            ],
            "public_rows_root_hash": artifact.public_rows_root_hash,
        }
        calls: list[dict[str, object]] = []

        def recording_handler(input_data: dict[str, object]) -> dict[str, object]:
            calls.append(input_data)
            return _handler(input_data)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "legacy-replay.json"
            path.write_text(__import__("json").dumps(legacy_payload), encoding="utf-8")
            source = load_replay_artifact_for_repair(path)
            repaired, summary = repair_jsonrpc_replays(
                source,
                cases,
                gateway_for=_gateways(recording_handler),
                mail_import_session_id="mailimport_replay",
            )

        self.assertEqual(summary, {"reused_case_count": 1, "reexecuted_case_count": 1})
        self.assertEqual(len(calls), 1)
        validate_replay_artifact(repaired)


def _gateways(
    handler: object,
    gateways: dict[str, SemanticMcpJsonRpcGateway] | None = None,
):
    semantic_gateway = SemanticMcpGateway(mail_evidence_handler=handler)
    resolved = gateways if gateways is not None else {}

    def gateway_for(user_id: str) -> SemanticMcpJsonRpcGateway:
        return resolved.setdefault(
            user_id,
            SemanticMcpJsonRpcGateway(
                semantic_gateway=semantic_gateway,
                session=SemanticGatewaySession(
                    session_id="session_replay",
                    actor_user_id=user_id,
                    workspace_id="workspace_formowl",
                ),
            ),
        )

    return gateway_for


def _handler(input_data: dict[str, object]) -> dict[str, object]:
    if input_data.get("requester_user_id") == "denied":
        return {
            "status": "permission_denied",
            "mail_import_session_id": "mailimport_replay",
            "query_hash": "sha256:" + "d" * 64,
            "evidence_snippets": [],
            "citations": [],
            "redaction_counts": {"hidden_bundles": 1, "hidden_messages": 2},
            "warnings": ["mail_evidence_permission_denied"],
        }
    if "unknown" in str(input_data.get("query_text", "")):
        return {
            "status": "ok",
            "mail_import_session_id": "mailimport_replay",
            "query_hash": "sha256:" + "e" * 64,
            "evidence_snippets": [],
            "citations": [],
            "redaction_counts": {"hidden_bundles": 0, "hidden_messages": 0},
            "warnings": ["no_visible_mail_evidence_matched"],
        }
    return {
        "status": "ok",
        "mail_import_session_id": "mailimport_replay",
        "query_hash": "sha256:" + "f" * 64,
        "evidence_snippets": [{"subject": "Supplier A", "snippet_hash": "sha256:" + "1" * 64}],
        "citations": [{"citation_hash": "sha256:" + "2" * 64}],
        "redaction_counts": {"hidden_bundles": 0, "hidden_messages": 0},
        "warnings": [],
    }


def _with_coherent_error_row(artifact, *, row_index: int):
    public_rows = [dict(row) for row in artifact.public_rows]
    private_rows = [dict(row) for row in artifact.private_rows]
    private_row = private_rows[row_index]
    steps = [dict(step) for step in private_row["steps"]]
    step = steps[0]
    response = {
        "jsonrpc": "2.0",
        "id": step["request"]["id"],
        "result": {
            "content": [
                {
                    "type": "json",
                    "json": {
                        "result_type": "semantic_gateway_error",
                        "status": "error",
                        "data": {"error_code": "unsafe_tool_payload"},
                        "warnings": ["safe_json_rpc_error_envelope"],
                    },
                }
            ],
            "isError": True,
            "session": artifact.tools_list_response["result"]["session"],
        },
    }
    step.update(
        {
            "response": response,
            "response_hash": sha256_json(response),
            "response_status": "error",
            "is_error": True,
            "evidence_count": 0,
            "citation_count": 0,
            "semantic_kind": "error",
        }
    )
    step["step_hash"] = sha256_json(
        {key: value for key, value in step.items() if key != "step_hash"}
    )
    private_row.update(
        {
            "response": response,
            "response_hash": step["response_hash"],
            "steps": steps,
            "trajectory_root_hash": sha256_json([step["step_hash"]]),
        }
    )
    public_row = public_rows[row_index]
    public_row.update(
        {
            "response_hash": step["response_hash"],
            "response_status": "error",
            "is_error": True,
            "evidence_count": 0,
            "citation_count": 0,
            "trajectory_root_hash": private_row["trajectory_root_hash"],
        }
    )
    public_row["row_hash"] = sha256_json(
        {key: value for key, value in public_row.items() if key != "row_hash"}
    )
    private_row["public_row_hash"] = public_row["row_hash"]
    private_row["private_row_hash"] = sha256_json(
        {key: value for key, value in private_row.items() if key != "private_row_hash"}
    )
    provisional = replace(
        artifact,
        public_rows=tuple(public_rows),
        private_rows=tuple(private_rows),
        public_rows_root_hash=sha256_json([row["row_hash"] for row in public_rows]),
        private_rows_root_hash=sha256_json([row["private_row_hash"] for row in private_rows]),
        attestation_hash="sha256:" + "0" * 64,
    )
    from formowl_evaluator.replay import replay_attestation_hash

    return replace(provisional, attestation_hash=replay_attestation_hash(provisional))


if __name__ == "__main__":
    unittest.main()
