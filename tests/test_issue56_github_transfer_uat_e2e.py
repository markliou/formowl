from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch
from typing import Any, Iterator, Mapping

from formowl_contract import (
    assert_no_public_raw_references,
    sha256_json,
    stable_resource_contract_id,
)
from formowl_core import (
    Issue56TargetRuntimeComponents,
    SentenceTransformerDenseEncoder,
    build_issue56_execution_component_binding,
    issue56_target_dense_embedding_profile,
    load_issue56_target_mail_tokenizer_profile,
)
from scripts.issue56_github_transfer_source_export import (
    HttpJsonResponse,
    ISSUE_NUMBERS,
    acquire_github_scope,
    build_and_persist_transfer_artifacts,
)
from scripts import issue56_github_transfer_uat as runner
from scripts.issue56_github_transfer_uat import (
    EXECUTION_ARTIFACT_ID,
    FULL_CASE_ARM_IDS,
    ORACLE_FREE_PROJECTION_SCHEMA_ID,
    REPORT_ARTIFACT_ID,
    ROUTING_CONTRACT_SCHEMA_ID,
    ROUTING_PROFILE_FINGERPRINT,
    ROUTING_PROFILE_ID,
    SOURCE_GRAPH_POLICY_ID,
    SOURCE_NATIVE_RELATION,
    TransferUatValidationError,
    build_transfer_uat_preflight,
    execute_transfer_uat_once,
)
from formowl_mail.semantic_plan import deterministic_query_class


class _VectorRow(list[float]):
    def tolist(self) -> list[float]:
        return list(self)


class _ContractOnlySentenceTransformerModel:
    def encode(self, texts: list[str], **_kwargs: Any) -> list[_VectorRow]:
        rows: list[_VectorRow] = []
        for text in texts:
            vector = [0.0] * 384
            for character in text.casefold():
                vector[ord(character) % len(vector)] += 1.0
            norm = math.sqrt(sum(value * value for value in vector))
            rows.append(_VectorRow(value / norm for value in vector))
        return rows


class _FixtureGitHubClient:
    def __init__(self) -> None:
        self.issues = {issue_number: _issue(issue_number) for issue_number in ISSUE_NUMBERS}
        self.comments = {
            (issue_number, 1): [
                _comment(issue_number, 1),
                _comment(issue_number, 2),
            ]
            for issue_number in ISSUE_NUMBERS
        }

    def get_json(
        self,
        endpoint: str,
        query: dict[str, str] | None = None,
    ) -> HttpJsonResponse:
        parts = endpoint.strip("/").split("/")
        issue_number = int(parts[4])
        if len(parts) == 5:
            return HttpJsonResponse(payload=self.issues[issue_number], headers={})
        page = int((query or {})["page"])
        return HttpJsonResponse(
            payload=self.comments.get((issue_number, page), []),
            headers={},
        )


def _issue(issue_number: int) -> dict[str, object]:
    closed = issue_number == 55
    first_reference = 51 if issue_number != 51 else 52
    second_reference = 54 if issue_number != 54 else 55
    return {
        "id": 20_000 + issue_number,
        "node_id": f"ISSUE_{issue_number}",
        "number": issue_number,
        "title": f"Transfer record {issue_number}",
        "body": (f"Bounded source record links #{first_reference} and #{second_reference}."),
        "state": "closed" if closed else "open",
        "state_reason": "completed" if closed else None,
        "locked": False,
        "comments": 2,
        "created_at": f"2026-07-{issue_number - 30:02d}T12:00:00Z",
        "updated_at": f"2026-08-{issue_number - 38:02d}T12:00:00Z",
        "closed_at": "2026-08-17T10:43:48Z" if closed else None,
        "user": {
            "login": "fixture-author",
            "id": 101,
            "node_id": "FIXTURE_AUTHOR",
        },
        "author_association": "OWNER",
        "labels": [{"name": "transfer"}],
    }


def _comment(issue_number: int, ordinal: int) -> dict[str, object]:
    return {
        "id": issue_number * 1_000 + ordinal,
        "node_id": f"COMMENT_{issue_number}_{ordinal}",
        "body": f"Bounded comment links #{issue_number} to #52.",
        "created_at": f"2026-08-{ordinal + 1:02d}T10:00:00Z",
        "updated_at": f"2026-08-{ordinal + 1:02d}T10:00:00Z",
        "user": {
            "login": f"fixture-commenter-{ordinal}",
            "id": 200 + ordinal,
            "node_id": f"FIXTURE_COMMENTER_{ordinal}",
        },
        "author_association": "COLLABORATOR",
    }


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


def _environment_components(
    *,
    run_binding_fingerprint: str,
    expected_image_id: str,
    expected_image_metadata_fingerprint: str,
) -> dict[str, dict[str, Any]]:
    return {
        "code_component": {
            "artifact_fingerprint": sha256_json(
                {"kind": "code", "run_binding": run_binding_fingerprint}
            ),
            "code_tree_fingerprint": sha256_json(
                {"kind": "tree", "run_binding": run_binding_fingerprint}
            ),
        },
        "image_component": {
            "artifact_fingerprint": sha256_json(
                {
                    "kind": "image",
                    "run_binding": run_binding_fingerprint,
                    "image_id": expected_image_id,
                    "metadata": expected_image_metadata_fingerprint,
                }
            ),
            "image_id": expected_image_id,
            "image_metadata_fingerprint": expected_image_metadata_fingerprint,
        },
        "authority_component": {
            "artifact_fingerprint": sha256_json(
                {"kind": "authority", "run_binding": run_binding_fingerprint}
            ),
            "authority_state_fingerprint": sha256_json("authority_state"),
            "authority_execution_fingerprint": sha256_json("authority_execution"),
            "blocking_gate_set_fingerprint": sha256_json(
                ["source_completeness", "real_source_ablation"]
            ),
            "status": "blocked",
        },
    }


def _sha256_file(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _canonical_pretty_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _payload_fingerprint(payload: Mapping[str, Any], field_name: str) -> str:
    return sha256_json({key: value for key, value in payload.items() if key != field_name})


def _case_id(case: Mapping[str, Any]) -> str:
    identity_payload = {
        key: value for key, value in case.items() if key not in {"case_id", "case_fingerprint"}
    }
    return stable_resource_contract_id(
        "transfercase",
        "Issue56GitHubTransferHoldoutCase",
        identity_payload,
    )


def _preflight_kwargs(output_root: Path) -> dict[str, object]:
    source_export = output_root / "source-export.private.json"
    source_report = output_root / "source-completeness.safe.json"
    holdout = output_root / "transfer-holdout-manifest.private.json"
    holdout_report = output_root / "transfer-holdout-preflight.safe.json"
    return {
        "source_export_path": source_export,
        "expected_source_export_sha256": _sha256_file(source_export),
        "source_report_path": source_report,
        "expected_source_report_sha256": _sha256_file(source_report),
        "holdout_manifest_path": holdout,
        "expected_holdout_manifest_sha256": _sha256_file(holdout),
        "holdout_report_path": holdout_report,
        "expected_holdout_report_sha256": _sha256_file(holdout_report),
    }


def _build_fixture(output_root: Path) -> dict[str, object]:
    capture = acquire_github_scope(_FixtureGitHubClient())
    build_and_persist_transfer_artifacts(capture=capture, output_root=output_root)
    return _preflight_kwargs(output_root)


def _rewrite_manifest_and_safe_binding(
    output_root: Path,
    manifest: dict[str, Any],
    *,
    update_safe_routes: bool,
) -> None:
    manifest_path = output_root / "transfer-holdout-manifest.private.json"
    projection_path = output_root / "transfer-holdout-preflight.safe.json"
    output_root.chmod(0o700)
    manifest_path.chmod(0o600)
    projection_path.chmod(0o600)
    manifest["manifest_fingerprint"] = _payload_fingerprint(
        manifest,
        "manifest_fingerprint",
    )
    manifest_bytes = _canonical_pretty_bytes(manifest)
    manifest_path.write_bytes(manifest_bytes)
    manifest_sha256 = f"sha256:{hashlib.sha256(manifest_bytes).hexdigest()}"

    projection = json.loads(projection_path.read_bytes())
    projection["hashes"]["private_holdout_sha256"] = manifest_sha256
    projection["hashes"]["private_holdout_fingerprint"] = manifest["manifest_fingerprint"]
    if update_safe_routes:
        manifest_projection = runner._manifest_route_projection(
            cases=manifest["cases"],
            strata_counts=manifest["strata_counts"],
            query_class_counts=manifest["query_class_counts"],
        )
        projection["manifest_projection"] = manifest_projection
        projection["hashes"]["manifest_projection_fingerprint"] = manifest_projection[
            "projection_fingerprint"
        ]
        projection["hashes"]["routing_binding_set_fingerprint"] = manifest[
            "routing_binding_set_fingerprint"
        ]
    projection["report_fingerprint"] = _payload_fingerprint(
        projection,
        "report_fingerprint",
    )
    projection_path.write_bytes(_canonical_pretty_bytes(projection))
    manifest_path.chmod(0o400)
    projection_path.chmod(0o444)
    output_root.chmod(0o500)


def _rewrite_safe_projection(
    output_root: Path,
    mutation: Any,
) -> None:
    projection_path = output_root / "transfer-holdout-preflight.safe.json"
    output_root.chmod(0o700)
    projection_path.chmod(0o600)
    projection = json.loads(projection_path.read_bytes())
    mutation(projection)
    projection["report_fingerprint"] = _payload_fingerprint(
        projection,
        "report_fingerprint",
    )
    projection_path.write_bytes(_canonical_pretty_bytes(projection))
    projection_path.chmod(0o444)
    output_root.chmod(0o500)


@contextmanager
def _runtime_contract() -> Iterator[None]:
    with (
        patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=_contract_only_runtime(),
        ),
        patch.object(
            runner,
            "_build_environment_components",
            side_effect=_environment_components,
        ),
    ):
        yield


class Issue56GitHubTransferUatEndToEndTests(unittest.TestCase):
    def test_preflight_is_oracle_free_and_binds_source_graph_and_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "github-transfer-v1"
            kwargs = _build_fixture(output_root)
            sealed_projection = json.loads(Path(kwargs["holdout_report_path"]).read_bytes())[
                "manifest_projection"
            ]
            self.assertEqual(
                sealed_projection["schema_id"],
                ORACLE_FREE_PROJECTION_SCHEMA_ID,
            )
            self.assertEqual(
                sealed_projection["routing_profile_id"],
                ROUTING_PROFILE_ID,
            )
            with (
                _runtime_contract(),
                patch.object(
                    runner,
                    "_decode_private_transfer_manifest_after_claim",
                    side_effect=AssertionError("private manifest decode during preflight"),
                ) as decode_spy,
            ):
                report = build_transfer_uat_preflight(**kwargs)

        decode_spy.assert_not_called()
        self.assertEqual(report["preflight_status"], "passed")
        self.assertEqual(report["execution_status"], "not_run")
        self.assertEqual(report["quality_result_status"], "not_read")
        self.assertEqual(report["oracle_access_status"], "not_read")
        self.assertEqual(report["counts"]["sealed_quality_field_read_count"], 0)
        self.assertEqual(report["counts"]["case_count"], 10)
        self.assertEqual(report["counts"]["arm_count"], 6)
        self.assertEqual(report["counts"]["exact_executor_count"], 1)
        self.assertFalse(report["final_acceptance_eligible"])
        self.assertEqual(report["source_kind_status"], "passed")
        self.assertEqual(report["routing_contract_status"], "passed")
        self.assertEqual(
            report["query_class_counts"],
            {
                "evidence_lookup": 4,
                "exact_set_or_inventory": 2,
                "relation_reasoning": 4,
            },
        )
        self.assertEqual(
            report["hashes"]["graph_relation_set_fingerprint"],
            sha256_json(
                sorted(
                    (
                        sha256_json("co_occurs_with"),
                        sha256_json(SOURCE_NATIVE_RELATION),
                    )
                )
            ),
        )
        for field_name in (
            "source_binding_fingerprint",
            "manifest_projection_fingerprint",
            "manifest_route_projection_fingerprint",
            "routing_profile_fingerprint",
            "routing_binding_set_fingerprint",
            "routing_contract_schema_fingerprint",
            "identity_scope_fingerprint",
            "segmentation_profile_fingerprint",
            "index_fingerprint",
            "graph_fingerprint",
            "method_fingerprint",
            "answer_model_fingerprint",
            "answer_prompt_fingerprint",
            "evaluator_fingerprint",
            "code_fingerprint",
            "image_fingerprint",
            "authority_fingerprint",
            "runtime_fingerprint",
        ):
            self.assertRegex(report["hashes"][field_name], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(
            report["hashes"]["routing_profile_fingerprint"],
            ROUTING_PROFILE_FINGERPRINT,
        )
        self.assertEqual(
            report["hashes"]["routing_contract_schema_fingerprint"],
            sha256_json(ROUTING_CONTRACT_SCHEMA_ID),
        )
        assert_no_public_raw_references(report, REPORT_ARTIFACT_ID)

    def test_execute_once_runs_six_arms_exact_and_permission(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture_root = root / "github-transfer-v1"
            kwargs = _build_fixture(fixture_root)
            execution_output = root / "transfer-execution.safe.json"
            with _runtime_contract():
                preflight = build_transfer_uat_preflight(**kwargs)
                report = execute_transfer_uat_once(
                    **kwargs,
                    expected_runtime_fingerprint=preflight["hashes"]["runtime_fingerprint"],
                    execution_output=execution_output,
                )

            self.assertEqual(report["execution_status"], "passed")
            self.assertEqual(report["quality_result_status"], "diagnostic_only")
            self.assertEqual(report["final_acceptance_status"], "blocked")
            self.assertFalse(report["final_acceptance_eligible"])
            self.assertEqual(report["counts"]["case_count"], 10)
            self.assertEqual(report["counts"]["executed_full_case_arm_row_count"], 50)
            self.assertEqual(report["counts"]["executed_exact_case_count"], 2)
            self.assertEqual(report["counts"]["permission_leakage_count"], 0)
            for arm_id in FULL_CASE_ARM_IDS:
                arm = report["arms"][arm_id]
                self.assertEqual(arm["scored_case_count"], 10)
                self.assertEqual(arm["permission_denial_count"], 1)
            self.assertEqual(report["arms"]["structured_exact"]["scored_case_count"], 2)
            self.assertEqual(
                report["runtime_binding"]["source_graph_policy_fingerprint"],
                sha256_json(SOURCE_GRAPH_POLICY_ID),
            )
            self.assertEqual(
                report["runtime_binding"]["source_native_relation_fingerprint"],
                sha256_json(SOURCE_NATIVE_RELATION),
            )
            self.assertEqual(
                report["runtime_binding"]["routing_profile_fingerprint"],
                ROUTING_PROFILE_FINGERPRINT,
            )
            self.assertEqual(
                report["runtime_binding"]["manifest_route_projection_fingerprint"],
                report["hashes"]["manifest_route_projection_fingerprint"],
            )
            claim_path = runner._consumed_claim_path(execution_output)
            self.assertTrue(claim_path.is_file())
            self.assertEqual(stat.S_IMODE(claim_path.stat().st_mode) & 0o222, 0)
            self.assertEqual(stat.S_IMODE(execution_output.stat().st_mode) & 0o222, 0)
            claim = json.loads(claim_path.read_bytes())
            self.assertEqual(
                claim["hashes"]["runtime_fingerprint"],
                report["hashes"]["runtime_fingerprint"],
            )
            self.assertEqual(
                claim["hashes"]["claim_fingerprint"],
                report["hashes"]["consumed_claim_fingerprint"],
            )
            self.assertEqual(
                _sha256_file(claim_path),
                report["hashes"]["consumed_claim_sha256"],
            )
            self.assertEqual(
                claim["hashes"]["routing_profile_fingerprint"],
                ROUTING_PROFILE_FINGERPRINT,
            )
            self.assertEqual(
                claim["hashes"]["routing_binding_set_fingerprint"],
                report["hashes"]["routing_binding_set_fingerprint"],
            )
            self.assertFalse(list(root.glob(".*.tmp")))
            assert_no_public_raw_references(report, EXECUTION_ARTIFACT_ID)
            serialized = json.dumps(report, ensure_ascii=True, sort_keys=True)
            for forbidden in (
                "private_query",
                "expected_private",
                "fixture-author",
                "Bounded source record",
                str(root),
            ):
                self.assertNotIn(forbidden, serialized)

    def test_source_authored_manifest_and_projection_share_exact_route_contract(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_root = Path(temp_dir) / "github-transfer-v1"
            kwargs = _build_fixture(fixture_root)
            manifest = json.loads(Path(kwargs["holdout_manifest_path"]).read_bytes())
            safe_report = json.loads(Path(kwargs["holdout_report_path"]).read_bytes())
            expected_projection = runner._manifest_route_projection(
                cases=manifest["cases"],
                strata_counts=manifest["strata_counts"],
                query_class_counts=manifest["query_class_counts"],
            )

            self.assertEqual(safe_report["manifest_projection"], expected_projection)
            self.assertEqual(
                safe_report["hashes"]["manifest_projection_fingerprint"],
                expected_projection["projection_fingerprint"],
            )

            def tamper_boundary(projection: dict[str, Any]) -> None:
                route_projection = projection["manifest_projection"]
                route_projection["classification"] = "different_classification"
                route_projection["projection_fingerprint"] = _payload_fingerprint(
                    route_projection,
                    "projection_fingerprint",
                )
                projection["hashes"]["manifest_projection_fingerprint"] = route_projection[
                    "projection_fingerprint"
                ]

            _rewrite_safe_projection(fixture_root, tamper_boundary)
            with (
                _runtime_contract(),
                self.assertRaisesRegex(
                    TransferUatValidationError,
                    "holdout_route_projection_invalid",
                ),
            ):
                build_transfer_uat_preflight(**_preflight_kwargs(fixture_root))

    def test_projection_tamper_recomputed_self_seals_still_fails_cross_binding(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "github-transfer-v1"
            kwargs = _build_fixture(output_root)
            projection_path = Path(kwargs["holdout_report_path"])
            output_root.chmod(0o700)
            projection_path.chmod(0o600)
            projection = json.loads(projection_path.read_bytes())
            projection["hashes"]["source_snapshot_fingerprint"] = sha256_json(
                "different_source_snapshot"
            )
            projection["report_fingerprint"] = _payload_fingerprint(
                projection,
                "report_fingerprint",
            )
            projection_path.write_bytes(_canonical_pretty_bytes(projection))
            projection_path.chmod(0o444)
            output_root.chmod(0o500)
            kwargs["expected_holdout_report_sha256"] = _sha256_file(projection_path)
            with (
                _runtime_contract(),
                self.assertRaisesRegex(
                    TransferUatValidationError,
                    "holdout_projection_binding_mismatch",
                ),
            ):
                build_transfer_uat_preflight(**kwargs)

    def test_router_projection_profile_tamper_fails_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "github-transfer-v1"
            _build_fixture(output_root)

            def tamper(projection: dict[str, Any]) -> None:
                manifest_projection = projection["manifest_projection"]
                tampered_profile = sha256_json("different_router_profile")
                manifest_projection["routing_profile_fingerprint"] = tampered_profile
                manifest_projection["projection_fingerprint"] = _payload_fingerprint(
                    manifest_projection,
                    "projection_fingerprint",
                )
                projection["hashes"]["routing_profile_fingerprint"] = tampered_profile
                projection["hashes"]["manifest_projection_fingerprint"] = manifest_projection[
                    "projection_fingerprint"
                ]

            _rewrite_safe_projection(output_root, tamper)
            kwargs = _preflight_kwargs(output_root)
            with (
                _runtime_contract(),
                self.assertRaisesRegex(
                    TransferUatValidationError,
                    "holdout_route_projection_invalid",
                ),
            ):
                build_transfer_uat_preflight(**kwargs)

    def test_router_projection_class_count_tamper_fails_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "github-transfer-v1"
            _build_fixture(output_root)

            def tamper(projection: dict[str, Any]) -> None:
                altered_counts = {
                    "evidence_lookup": 5,
                    "exact_set_or_inventory": 2,
                    "relation_reasoning": 3,
                }
                projection["query_class_counts"] = altered_counts
                manifest_projection = projection["manifest_projection"]
                manifest_projection["query_class_counts"] = altered_counts
                manifest_projection["projection_fingerprint"] = _payload_fingerprint(
                    manifest_projection,
                    "projection_fingerprint",
                )
                projection["hashes"]["manifest_projection_fingerprint"] = manifest_projection[
                    "projection_fingerprint"
                ]

            _rewrite_safe_projection(output_root, tamper)
            kwargs = _preflight_kwargs(output_root)
            with (
                _runtime_contract(),
                self.assertRaisesRegex(
                    TransferUatValidationError,
                    "holdout_projection_boundary_invalid",
                ),
            ):
                build_transfer_uat_preflight(**kwargs)

    def test_legacy_projection_without_router_fails_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "github-transfer-v1"
            _build_fixture(output_root)

            def remove_router(projection: dict[str, Any]) -> None:
                projection.pop("manifest_projection")
                projection.pop("query_class_counts")
                projection.pop("routing_contract_status")
                projection.pop("oracle_free_projection_status")
                for field_name in (
                    "routing_profile_fingerprint",
                    "routing_binding_set_fingerprint",
                    "manifest_projection_fingerprint",
                ):
                    projection["hashes"].pop(field_name)

            _rewrite_safe_projection(output_root, remove_router)
            kwargs = _preflight_kwargs(output_root)
            with (
                _runtime_contract(),
                self.assertRaisesRegex(
                    TransferUatValidationError,
                    "holdout_projection_boundary_invalid",
                ),
            ):
                build_transfer_uat_preflight(**kwargs)

    def test_private_query_hash_tamper_is_consumed_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture_root = root / "github-transfer-v1"
            _build_fixture(fixture_root)
            manifest_path = fixture_root / "transfer-holdout-manifest.private.json"
            manifest = json.loads(manifest_path.read_bytes())
            case = manifest["cases"][0]
            case["private_query"] = f"{case['private_query']} Synthetic suffix."
            case["case_id"] = _case_id(case)
            case["case_fingerprint"] = _payload_fingerprint(
                case,
                "case_fingerprint",
            )
            _rewrite_manifest_and_safe_binding(
                fixture_root,
                manifest,
                update_safe_routes=False,
            )
            kwargs = _preflight_kwargs(fixture_root)
            output = root / "query-hash-tamper.safe.json"
            with _runtime_contract():
                preflight = build_transfer_uat_preflight(**kwargs)
                with self.assertRaisesRegex(
                    TransferUatValidationError,
                    "holdout_case_routing_contract_invalid",
                ):
                    execute_transfer_uat_once(
                        **kwargs,
                        expected_runtime_fingerprint=preflight["hashes"]["runtime_fingerprint"],
                        execution_output=output,
                    )
            self.assertTrue(runner._consumed_claim_path(output).is_file())
            self.assertFalse(output.exists())

    def test_cross_case_route_swap_is_consumed_and_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture_root = root / "github-transfer-v1"
            _build_fixture(fixture_root)
            manifest_path = fixture_root / "transfer-holdout-manifest.private.json"
            manifest = json.loads(manifest_path.read_bytes())
            direct_cases = [case for case in manifest["cases"] if case["stratum"] == "direct"]
            self.assertEqual(len(direct_cases), 2)
            first_query = direct_cases[0]["private_query"]
            first_contract = direct_cases[0]["routing_contract"]
            direct_cases[0]["private_query"] = direct_cases[1]["private_query"]
            direct_cases[0]["routing_contract"] = direct_cases[1]["routing_contract"]
            direct_cases[1]["private_query"] = first_query
            direct_cases[1]["routing_contract"] = first_contract
            for case in direct_cases:
                case["case_id"] = _case_id(case)
                case["case_fingerprint"] = _payload_fingerprint(
                    case,
                    "case_fingerprint",
                )
            _rewrite_manifest_and_safe_binding(
                fixture_root,
                manifest,
                update_safe_routes=False,
            )
            kwargs = _preflight_kwargs(fixture_root)
            output = root / "route-swap.safe.json"
            with _runtime_contract():
                preflight = build_transfer_uat_preflight(**kwargs)
                with self.assertRaisesRegex(
                    TransferUatValidationError,
                    "holdout_private_projection_cross_binding_mismatch",
                ):
                    execute_transfer_uat_once(
                        **kwargs,
                        expected_runtime_fingerprint=preflight["hashes"]["runtime_fingerprint"],
                        execution_output=output,
                    )
            self.assertTrue(runner._consumed_claim_path(output).is_file())
            self.assertFalse(output.exists())

    def test_private_legacy_manifest_without_router_is_consumed_and_rejected(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture_root = root / "github-transfer-v1"
            _build_fixture(fixture_root)
            manifest_path = fixture_root / "transfer-holdout-manifest.private.json"
            manifest = json.loads(manifest_path.read_bytes())
            manifest.pop("routing_profile")
            _rewrite_manifest_and_safe_binding(
                fixture_root,
                manifest,
                update_safe_routes=False,
            )
            kwargs = _preflight_kwargs(fixture_root)
            output = root / "legacy-private.safe.json"
            with _runtime_contract():
                preflight = build_transfer_uat_preflight(**kwargs)
                with self.assertRaisesRegex(
                    TransferUatValidationError,
                    "holdout_routing_profile_invalid",
                ):
                    execute_transfer_uat_once(
                        **kwargs,
                        expected_runtime_fingerprint=preflight["hashes"]["runtime_fingerprint"],
                        execution_output=output,
                    )
            self.assertTrue(runner._consumed_claim_path(output).is_file())
            self.assertFalse(output.exists())

    def test_lexical_disagreement_uses_sealed_source_authored_route(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture_root = root / "github-transfer-v1"
            kwargs = _build_fixture(fixture_root)
            manifest = json.loads(Path(kwargs["holdout_manifest_path"]).read_bytes())
            expected_routes = {
                sha256_json(case["private_query"]): case["query_class"]
                for case in manifest["cases"]
                if case["stratum"] != "permission_denied"
            }
            disagreements = {
                query_hash: query_class
                for query_hash, query_class in expected_routes.items()
                if deterministic_query_class(
                    next(
                        case["private_query"]
                        for case in manifest["cases"]
                        if sha256_json(case["private_query"]) == query_hash
                    )
                )
                != query_class
            }
            self.assertTrue(disagreements)
            observed_routes: dict[str, str] = {}
            original_run_case_arms = runner._run_case_arms

            def capture_route(**arguments: Any) -> Any:
                observed_routes[sha256_json(arguments["query_text"])] = arguments["query_class"]
                return original_run_case_arms(**arguments)

            output = root / "source-authored-route.safe.json"
            with _runtime_contract():
                preflight = build_transfer_uat_preflight(**kwargs)
                with patch.object(
                    runner,
                    "_run_case_arms",
                    side_effect=capture_route,
                ):
                    report = execute_transfer_uat_once(
                        **kwargs,
                        expected_runtime_fingerprint=preflight["hashes"]["runtime_fingerprint"],
                        execution_output=output,
                    )

            self.assertEqual(report["execution_status"], "passed")
            self.assertEqual(observed_routes, expected_routes)
            self.assertTrue(
                all(
                    observed_routes[query_hash] == query_class
                    for query_hash, query_class in disagreements.items()
                )
            )
            self.assertFalse(hasattr(runner, "deterministic_query_class"))
            self.assertTrue(output.is_file())

    def test_manifest_tamper_after_claim_is_consumed_and_has_no_partial_output(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture_root = root / "github-transfer-v1"
            kwargs = _build_fixture(fixture_root)
            output = root / "tampered.safe.json"
            manifest_path = Path(kwargs["holdout_manifest_path"])

            def tamper_after_claim() -> None:
                fixture_root.chmod(0o700)
                manifest_path.chmod(0o600)
                manifest_path.write_bytes(manifest_path.read_bytes() + b"\n")

            with _runtime_contract():
                preflight = build_transfer_uat_preflight(**kwargs)
                with self.assertRaisesRegex(
                    TransferUatValidationError,
                    "holdout_manifest_seal_mismatch_after_claim",
                ):
                    execute_transfer_uat_once(
                        **kwargs,
                        expected_runtime_fingerprint=preflight["hashes"]["runtime_fingerprint"],
                        execution_output=output,
                        _after_claim_hook=tamper_after_claim,
                    )
            claim_path = runner._consumed_claim_path(output)
            self.assertTrue(claim_path.is_file())
            self.assertFalse(output.exists())
            self.assertEqual(stat.S_IMODE(claim_path.stat().st_mode) & 0o222, 0)
            self.assertFalse(list(root.glob(".*.tmp")))

    def test_crash_after_claim_is_permanently_consumed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture_root = root / "github-transfer-v1"
            kwargs = _build_fixture(fixture_root)
            output = root / "crash.safe.json"

            def crash_after_claim() -> None:
                raise RuntimeError("synthetic_crash_after_claim")

            with _runtime_contract():
                preflight = build_transfer_uat_preflight(**kwargs)
                runtime_fingerprint = preflight["hashes"]["runtime_fingerprint"]
                with self.assertRaisesRegex(RuntimeError, "synthetic_crash_after_claim"):
                    execute_transfer_uat_once(
                        **kwargs,
                        expected_runtime_fingerprint=runtime_fingerprint,
                        execution_output=output,
                        _after_claim_hook=crash_after_claim,
                    )
                with self.assertRaisesRegex(
                    TransferUatValidationError,
                    "one_shot_consumed_claim_already_exists",
                ):
                    execute_transfer_uat_once(
                        **kwargs,
                        expected_runtime_fingerprint=runtime_fingerprint,
                        execution_output=output,
                    )
            self.assertTrue(runner._consumed_claim_path(output).is_file())
            self.assertFalse(output.exists())
            self.assertFalse(list(root.glob(".*.tmp")))

    def test_concurrent_execute_once_has_one_claim_winner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture_root = root / "github-transfer-v1"
            kwargs = _build_fixture(fixture_root)
            output = root / "race.safe.json"
            start = threading.Barrier(2)
            winner_count = 0
            winner_lock = threading.Lock()

            def stop_winner_after_claim() -> None:
                nonlocal winner_count
                with winner_lock:
                    winner_count += 1
                raise RuntimeError("synthetic_race_winner_stopped")

            def invoke(runtime_fingerprint: str) -> str:
                start.wait(timeout=10)
                try:
                    execute_transfer_uat_once(
                        **kwargs,
                        expected_runtime_fingerprint=runtime_fingerprint,
                        execution_output=output,
                        _after_claim_hook=stop_winner_after_claim,
                    )
                except (RuntimeError, TransferUatValidationError) as exc:
                    return str(exc)
                return "unexpected_success"

            with _runtime_contract():
                preflight = build_transfer_uat_preflight(**kwargs)
                runtime_fingerprint = preflight["hashes"]["runtime_fingerprint"]
                with ThreadPoolExecutor(max_workers=2) as executor:
                    outcomes = list(
                        executor.map(
                            invoke,
                            (runtime_fingerprint, runtime_fingerprint),
                        )
                    )
            self.assertEqual(winner_count, 1)
            self.assertCountEqual(
                outcomes,
                [
                    "synthetic_race_winner_stopped",
                    "one_shot_consumed_claim_already_exists",
                ],
            )
            self.assertTrue(runner._consumed_claim_path(output).is_file())
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
