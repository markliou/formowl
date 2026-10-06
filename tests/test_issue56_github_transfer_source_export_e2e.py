from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import stat
import tempfile
import unittest

from formowl_contract import (
    Asset,
    Observation,
    SourceInventory,
    assert_no_public_raw_references,
)
from formowl_mail.query import source_occurrence_lineage_from_observation
from formowl_mail.semantic_plan import (
    GITHUB_PROJECT_OBSERVATION_SOURCE_KIND,
    deterministic_query_class,
    validated_authorized_semantic_source,
)
from scripts.issue56_github_transfer_source_export import (
    COMPLETENESS_REPORT_ARTIFACT_ID,
    GitHubTransferError,
    HOLDOUT_REPORT_ARTIFACT_ID,
    HttpJsonResponse,
    ISSUE_NUMBERS,
    ORACLE_FREE_PROJECTION_SCHEMA_ID,
    ROUTING_PROFILE_FINGERPRINT,
    ROUTING_PROFILE_ID,
    SOURCE_OCCURRENCE_SCHEMA_FINGERPRINT,
    _payload_fingerprint,
    _validate_private_export,
    _validate_safe_holdout_binding,
    _validate_safe_report,
    _validate_transfer_holdout,
    acquire_github_scope,
    build_and_persist_transfer_artifacts,
)


class _FixtureGitHubClient:
    def __init__(
        self,
        *,
        issue_records: dict[int, dict[str, object]],
        comment_pages: dict[tuple[int, int], list[dict[str, object]]],
    ) -> None:
        self.issue_records = issue_records
        self.comment_pages = comment_pages

    def get_json(
        self,
        endpoint: str,
        query: dict[str, str] | None = None,
    ) -> HttpJsonResponse:
        parts = endpoint.strip("/").split("/")
        issue_number = int(parts[4])
        if len(parts) == 5:
            return HttpJsonResponse(
                payload=self.issue_records[issue_number],
                headers={},
            )
        page = int((query or {})["page"])
        payload = self.comment_pages.get((issue_number, page), [])
        next_page = page + 1
        headers: dict[str, str] = {}
        if (issue_number, next_page) in self.comment_pages:
            headers["link"] = (
                "<https://api.github.com/repos/markliou/formowl/issues/"
                f'{issue_number}/comments?per_page=100&page={next_page}>; rel="next"'
            )
        return HttpJsonResponse(payload=payload, headers=headers)


def _user(login: str = "source-author") -> dict[str, object]:
    return {"login": login, "id": 101, "node_id": f"USER_{login}"}


def _issue(
    issue_number: int,
    *,
    comments: int,
    state: str = "open",
    body: str | None = None,
    updated_day: int | None = None,
) -> dict[str, object]:
    day = updated_day or min(18, issue_number - 38)
    closed_at = "2026-08-17T10:43:48Z" if state == "closed" else None
    return {
        "id": 10_000 + issue_number,
        "node_id": f"ISSUE_{issue_number}",
        "number": issue_number,
        "title": f"Project transfer source issue {issue_number}",
        "body": body
        or (
            f"Source-preserving project work for #{51 + ((issue_number - 50) % 6)} "
            f"and #{51 + ((issue_number - 49) % 6)}."
        ),
        "state": state,
        "state_reason": "completed" if state == "closed" else None,
        "locked": False,
        "comments": comments,
        "created_at": f"2026-07-{issue_number - 30:02d}T12:00:00Z",
        "updated_at": f"2026-08-{day:02d}T12:00:00Z",
        "closed_at": closed_at,
        "user": _user(),
        "author_association": "OWNER",
        "labels": [{"name": "testing"}],
    }


def _comment(
    issue_number: int,
    comment_number: int,
    *,
    body: str | None = None,
) -> dict[str, object]:
    return {
        "id": issue_number * 100 + comment_number,
        "node_id": f"COMMENT_{issue_number}_{comment_number}",
        "body": body or f"Comment evidence connects #{issue_number} to #52.",
        "created_at": f"2026-08-{comment_number + 1:02d}T10:00:00Z",
        "updated_at": f"2026-08-{comment_number + 1:02d}T10:00:00Z",
        "user": _user(f"commenter-{comment_number}"),
        "author_association": "COLLABORATOR",
    }


def _source_client() -> _FixtureGitHubClient:
    issue_records = {
        issue_number: _issue(
            issue_number,
            comments=2 if issue_number == 51 else (1 if issue_number in {52, 54, 55} else 0),
            state="closed" if issue_number == 55 else "open",
            body=(
                "Implementation scope links #51 and #52."
                if issue_number == 54
                else f"Project record #{issue_number} references #52 and #54."
            ),
            updated_day=18 if issue_number == 56 else issue_number - 38,
        )
        for issue_number in ISSUE_NUMBERS
    }
    comment_pages: dict[tuple[int, int], list[dict[str, object]]] = {
        (51, 1): [_comment(51, 1, body="First source comment links #52.")],
        (51, 2): [_comment(51, 2, body="Second source comment links #54.")],
        (52, 1): [_comment(52, 1)],
        (54, 1): [_comment(54, 1)],
        (55, 1): [_comment(55, 1)],
    }
    return _FixtureGitHubClient(
        issue_records=issue_records,
        comment_pages=comment_pages,
    )


class Issue56GitHubTransferSourceExportE2ETests(unittest.TestCase):
    def test_complete_source_to_owner_records_and_sealed_holdout(self) -> None:
        capture = acquire_github_scope(_source_client())
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "github-transfer-v1"
            artifacts = build_and_persist_transfer_artifacts(
                capture=capture,
                output_root=output_root,
            )
            private_export = json.loads(artifacts.private_export_path.read_bytes())
            private_holdout = json.loads(artifacts.private_holdout_path.read_bytes())
            safe_completeness = json.loads(artifacts.safe_completeness_path.read_bytes())
            safe_holdout = json.loads(artifacts.safe_holdout_path.read_bytes())

            self.assertEqual(safe_completeness["status"], "passed")
            self.assertEqual(safe_completeness["counts"]["issue_record_count"], 6)
            self.assertEqual(safe_completeness["counts"]["comment_record_count"], 5)
            self.assertEqual(safe_completeness["counts"]["source_record_count"], 11)
            self.assertEqual(
                safe_completeness["counts"]["source_inventory_item_count"],
                11,
            )
            self.assertEqual(safe_completeness["counts"]["observation_count"], 11)
            self.assertEqual(safe_completeness["counts"]["unexplained_loss_count"], 0)
            self.assertEqual(safe_completeness["event_scope_status"], "excluded")
            self.assertEqual(safe_completeness["attachment_scope_status"], "excluded")
            self.assertEqual(safe_holdout["execution_status"], "not_run")
            self.assertEqual(safe_holdout["quality_result_status"], "not_read")
            self.assertTrue(safe_holdout["diagnostic_only"])
            self.assertFalse(safe_holdout["final_acceptance_eligible"])
            self.assertEqual(
                safe_holdout["claim_boundary_status"],
                "ten_case_diagnostic_not_final_acceptance",
            )
            self.assertEqual(
                safe_holdout["runtime_freeze_status"],
                "pending_master_confirmation",
            )
            self.assertEqual(
                safe_holdout["strata_counts"],
                {
                    "cross_issue_relation": 2,
                    "direct": 2,
                    "exact_count_inventory": 2,
                    "no_answer": 1,
                    "permission_denied": 1,
                    "temporal_status": 2,
                },
            )
            self.assertEqual(private_holdout["case_count"], 10)
            self.assertTrue(private_holdout["diagnostic_only"])
            self.assertFalse(private_holdout["final_acceptance_eligible"])
            self.assertEqual(
                private_holdout["classification"],
                "diagnostic_only_source_authored_transfer_fixture",
            )
            self.assertFalse(private_holdout["mail_source_consumed"])
            self.assertEqual(private_holdout["execution_status"], "not_run")
            self.assertEqual(
                private_export["claim_boundary_status"],
                "source_observations_not_canonical_fact",
            )
            Asset.from_dict(private_export["asset"])
            inventory = SourceInventory.from_dict(private_export["source_inventory"])
            observations = [
                Observation.from_dict(value) for value in private_export["observations"]
            ]
            self.assertEqual(len(inventory.items), len(observations))
            self.assertEqual(
                {item.location["source_local_key"] for item in inventory.items},
                {observation.location["source_local_key"] for observation in observations},
            )
            authorized_source = validated_authorized_semantic_source(
                source_kind=GITHUB_PROJECT_OBSERVATION_SOURCE_KIND,
                workspace_id=str(private_export["asset"]["workspace_id"]),
                source_scope_ids=(str(private_export["asset"]["project_id"]),),
            )
            issue_keys = {
                int(observation.payload["issue_number"]): observation.location["source_local_key"]
                for observation in observations
                if observation.observation_type == "issue_record"
            }
            for observation in observations:
                lineage = source_occurrence_lineage_from_observation(
                    observation,
                    authorized_source=authorized_source,
                )
                if observation.observation_type == "issue_record":
                    self.assertIsNone(lineage.parent_source_local_key)
                    self.assertNotIn(
                        "parent_source_local_key",
                        observation.location,
                    )
                    self.assertNotIn(
                        "parent_source_local_key",
                        observation.payload,
                    )
                else:
                    expected_parent = issue_keys[int(observation.payload["issue_number"])]
                    self.assertEqual(lineage.parent_source_local_key, expected_parent)
                    self.assertEqual(
                        observation.location["parent_source_local_key"],
                        expected_parent,
                    )
                    self.assertEqual(
                        observation.payload["parent_source_local_key"],
                        expected_parent,
                    )
            self.assertEqual(
                private_export["source_occurrence_schema_fingerprint"],
                SOURCE_OCCURRENCE_SCHEMA_FINGERPRINT,
            )
            self.assertEqual(
                private_holdout["routing_profile_fingerprint"],
                ROUTING_PROFILE_FINGERPRINT,
            )
            self.assertEqual(
                private_holdout["routing_profile"]["profile_id"],
                ROUTING_PROFILE_ID,
            )
            self.assertEqual(
                private_holdout["routing_profile"]["classifier_kind"],
                "source_authored_typed_intent_router",
            )
            self.assertEqual(
                safe_holdout["manifest_projection"]["schema_id"],
                ORACLE_FREE_PROJECTION_SCHEMA_ID,
            )
            self.assertTrue(safe_holdout["manifest_projection"]["diagnostic_only"])
            self.assertFalse(safe_holdout["manifest_projection"]["final_acceptance_eligible"])
            self.assertEqual(
                safe_holdout["manifest_projection"]["query_class_counts"],
                {
                    "evidence_lookup": 4,
                    "exact_set_or_inventory": 2,
                    "relation_reasoning": 4,
                },
            )
            relation_cases = [
                case
                for case in private_holdout["cases"]
                if case["stratum"] == "cross_issue_relation"
            ]
            permission_case = next(
                case for case in private_holdout["cases"] if case["stratum"] == "permission_denied"
            )
            self.assertTrue(
                all(case["query_class"] == "relation_reasoning" for case in relation_cases)
            )
            self.assertTrue(
                any(
                    deterministic_query_class(case["private_query"]) != case["query_class"]
                    for case in relation_cases
                )
            )
            self.assertEqual(permission_case["query_class"], "evidence_lookup")
            self.assertNotEqual(
                deterministic_query_class(permission_case["private_query"]),
                permission_case["query_class"],
            )
            for case in private_holdout["cases"]:
                routing_contract = case["routing_contract"]
                self.assertEqual(
                    routing_contract["authored_query_class"],
                    case["query_class"],
                )
                self.assertEqual(
                    routing_contract["typed_stratum"],
                    case["stratum"],
                )
                self.assertTrue(routing_contract["authored_intent_kind"])
                self.assertEqual(
                    routing_contract["routing_profile_fingerprint"],
                    ROUTING_PROFILE_FINGERPRINT,
                )
            assert_no_public_raw_references(
                safe_completeness,
                COMPLETENESS_REPORT_ARTIFACT_ID,
            )
            assert_no_public_raw_references(safe_holdout, HOLDOUT_REPORT_ARTIFACT_ID)
            public_bytes = (
                artifacts.safe_completeness_path.read_text()
                + artifacts.safe_holdout_path.read_text()
            )
            for forbidden in (
                "private_query",
                "expected_private",
                "source-author",
                "Project transfer source issue",
                "Comment evidence",
                "markliou/formowl",
            ):
                self.assertNotIn(forbidden, public_bytes)
            self.assertEqual(stat.S_IMODE(output_root.stat().st_mode), 0o500)
            self.assertEqual(
                stat.S_IMODE(artifacts.private_export_path.stat().st_mode),
                0o400,
            )
            self.assertEqual(
                stat.S_IMODE(artifacts.safe_completeness_path.stat().st_mode),
                0o444,
            )
            with self.assertRaisesRegex(
                GitHubTransferError,
                "immutable_output_root_exists",
            ):
                build_and_persist_transfer_artifacts(
                    capture=capture,
                    output_root=output_root,
                )

    def test_deterministic_second_root_has_same_seals(self) -> None:
        capture = acquire_github_scope(_source_client())
        with tempfile.TemporaryDirectory() as temp_dir:
            first = build_and_persist_transfer_artifacts(
                capture=capture,
                output_root=Path(temp_dir) / "first",
            )
            second = build_and_persist_transfer_artifacts(
                capture=capture,
                output_root=Path(temp_dir) / "second",
            )
            self.assertEqual(first.private_export_sha256, second.private_export_sha256)
            self.assertEqual(first.private_holdout_sha256, second.private_holdout_sha256)
            self.assertEqual(first.safe_completeness, second.safe_completeness)
            self.assertEqual(first.safe_holdout, second.safe_holdout)

    def test_comment_count_gap_fails_before_persistence(self) -> None:
        client = _source_client()
        client.issue_records[51]["comments"] = 3
        with self.assertRaisesRegex(
            GitHubTransferError,
            "github_comment_count_mismatch",
        ):
            acquire_github_scope(client)

    def test_tamper_is_rejected_by_owner_round_trip(self) -> None:
        capture = acquire_github_scope(_source_client())
        capture["issue_records"][0]["title"] = "tampered"
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "blocked"
            with self.assertRaisesRegex(
                GitHubTransferError,
                "github_capture_fingerprint_drift",
            ):
                build_and_persist_transfer_artifacts(
                    capture=capture,
                    output_root=output_root,
                )
            self.assertFalse(output_root.exists())

    def test_recomputed_issue_parent_and_routing_tamper_fail_closed(self) -> None:
        capture = acquire_github_scope(_source_client())
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts = build_and_persist_transfer_artifacts(
                capture=capture,
                output_root=Path(temp_dir) / "sealed",
            )
            private_export = json.loads(artifacts.private_export_path.read_bytes())
            private_holdout = json.loads(artifacts.private_holdout_path.read_bytes())

            parent_tamper = deepcopy(private_export)
            issue_observation = next(
                observation
                for observation in parent_tamper["observations"]
                if observation["observation_type"] == "issue_record"
            )
            source_local_key = issue_observation["location"]["source_local_key"]
            issue_observation["location"]["parent_source_local_key"] = source_local_key
            issue_observation["payload"]["parent_source_local_key"] = source_local_key
            parent_tamper["export_fingerprint"] = _payload_fingerprint(
                parent_tamper,
                "export_fingerprint",
            )
            with self.assertRaisesRegex(
                GitHubTransferError,
                "github_issue_occurrence_parent_invalid",
            ):
                _validate_private_export(parent_tamper)

            routing_tamper = deepcopy(private_holdout)
            relation_case = next(
                case
                for case in routing_tamper["cases"]
                if case["stratum"] == "cross_issue_relation"
            )
            relation_case["query_class"] = "evidence_lookup"
            relation_case["case_fingerprint"] = _payload_fingerprint(
                relation_case,
                "case_fingerprint",
            )
            routing_tamper["manifest_fingerprint"] = _payload_fingerprint(
                routing_tamper,
                "manifest_fingerprint",
            )
            with self.assertRaisesRegex(
                GitHubTransferError,
                "github_holdout_authored_query_class_drift",
            ):
                _validate_transfer_holdout(
                    routing_tamper,
                    private_export=private_export,
                )

    def test_oracle_free_projection_self_seal_tamper_fails_cross_binding(self) -> None:
        capture = acquire_github_scope(_source_client())
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts = build_and_persist_transfer_artifacts(
                capture=capture,
                output_root=Path(temp_dir) / "sealed",
            )
            private_export = json.loads(artifacts.private_export_path.read_bytes())
            private_holdout = json.loads(artifacts.private_holdout_path.read_bytes())
            safe_holdout = deepcopy(artifacts.safe_holdout)
            projected_route = next(
                route
                for route in safe_holdout["manifest_projection"]["case_routes"]
                if route["query_class"] == "evidence_lookup"
            )
            projected_route["query_class"] = "relation_reasoning"
            safe_holdout["manifest_projection"]["projection_fingerprint"] = _payload_fingerprint(
                safe_holdout["manifest_projection"],
                "projection_fingerprint",
            )
            safe_holdout["hashes"]["manifest_projection_fingerprint"] = safe_holdout[
                "manifest_projection"
            ]["projection_fingerprint"]
            safe_holdout["report_fingerprint"] = _payload_fingerprint(
                safe_holdout,
                "report_fingerprint",
            )
            _validate_safe_report(safe_holdout, HOLDOUT_REPORT_ARTIFACT_ID)
            with self.assertRaisesRegex(
                GitHubTransferError,
                "github_safe_holdout_cross_binding_drift",
            ):
                _validate_safe_holdout_binding(
                    safe_holdout,
                    private_export=private_export,
                    private_export_sha256=artifacts.private_export_sha256,
                    holdout=private_holdout,
                    holdout_sha256=artifacts.private_holdout_sha256,
                )


if __name__ == "__main__":
    unittest.main()
