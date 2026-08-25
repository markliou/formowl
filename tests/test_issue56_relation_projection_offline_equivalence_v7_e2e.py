from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, sha256_json
from formowl_gateway import issue56_diagnostic as diagnostic
from formowl_gateway import issue56_sealed_source_loader as gateway_loader
from formowl_graph import EffectiveGraphView
import formowl_mail
from formowl_mail import hybrid as hybrid_module
from scripts import issue56_prompt_mcp_hybrid_diagnostic as diagnostic_cli
import test_issue56_real_prompt_mcp_phase_trace_e2e as real_prompt_fixture


_TEST_MODE_ID = diagnostic._ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_TEST_MODE_ID
_TEST_CONTRACT = diagnostic_cli._RelationProjectionEquivalenceVersionContract(
    diagnostic_mode_id=_TEST_MODE_ID,
    loader_contract_id=("issue56_relation_projection_offline_equivalence_v7_test_loader_v0"),
    claim_artifact_id=("formowl_issue56_relation_projection_offline_equivalence_v7_test_claim_v0"),
    claim_schema_version=7,
    enforce_repository_state_root=False,
    preseal_graph_content=True,
    offline_equivalence=True,
)
_PRIVATE_PROMPT = "PO470002002 與 ORIGIN-TAIWAN-01 的關係"
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_FORMAL_V7_STATE_ROOT = (
    _REPOSITORY_ROOT
    / ".test-tmp"
    / (
        f"{diagnostic.ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_DIAGNOSTIC_MODE_ID}"
        "-state"
    )
)


class Issue56RelationProjectionOfflineEquivalenceV7EndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertFalse(
            _FORMAL_V7_STATE_ROOT.exists(),
            "focused tests must not create the formal v7 state root",
        )

    def tearDown(self) -> None:
        self.assertFalse(
            _FORMAL_V7_STATE_ROOT.exists(),
            "focused tests must leave the formal v7 state root absent",
        )

    def test_offline_cold_prime_then_two_normal_http_queries_are_equivalent(
        self,
    ) -> None:
        source = self._test_source()
        real_graph_preseal = formowl_mail.precompute_effective_graph_content_snapshot
        real_after_precompute = hybrid_module.precompute_relation_projection_base
        real_cold_diagnostic = formowl_mail.precompute_relation_projection_base_cold_diagnostic

        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory)
            with (
                mock.patch.object(
                    formowl_mail,
                    "precompute_effective_graph_content_snapshot",
                    wraps=real_graph_preseal,
                ) as graph_preseal,
                mock.patch.object(
                    hybrid_module,
                    "precompute_relation_projection_base",
                    wraps=real_after_precompute,
                ) as after_precompute,
                mock.patch.object(
                    formowl_mail,
                    "precompute_relation_projection_base_cold_diagnostic",
                    wraps=real_cold_diagnostic,
                ) as cold_diagnostic,
            ):
                report = diagnostic_cli._run_relation_projection_equivalence_diagnostic_once(
                    loader=lambda: source,
                    loader_spec_fingerprint=sha256_json("test relation projection v7 loader"),
                    state_root=state_root,
                    contract=_TEST_CONTRACT,
                )

            self.assertEqual(graph_preseal.call_count, 2)
            self.assertEqual(after_precompute.call_count, 1)
            self.assertEqual(cold_diagnostic.call_count, 1)
            self.assertEqual(report["status"], "passed", report)
            self.assertTrue(all(report["equivalence"].values()))
            self.assertTrue(all(report["cache_acceptance"].values()))
            self.assertEqual(
                report["query_budget"],
                {
                    "per_arm_ms": 1500,
                    "offline_precompute_consumes_query_budget": False,
                    "phase_local_budget_override": False,
                },
            )
            self.assertEqual(
                {
                    key: report["preflight"]["counts"][key]
                    for key in (
                        "cold_binding_cache_entry_count",
                        "cold_base_cache_entry_count",
                        "after_binding_cache_entry_count",
                        "after_base_cache_entry_count",
                    )
                },
                {
                    "cold_binding_cache_entry_count": 0,
                    "cold_base_cache_entry_count": 0,
                    "after_binding_cache_entry_count": 1,
                    "after_base_cache_entry_count": 1,
                },
            )
            self.assertEqual(
                report["offline_precompute"]["cache"],
                {
                    "binding_entry_count_before": 0,
                    "binding_entry_count_after": 1,
                    "base_entry_count_before": 0,
                    "base_entry_count_after": 1,
                },
            )
            self.assertEqual(
                report["offline_precompute"]["phases"]["binding_snapshot"]["status"],
                "completed",
            )
            self.assertEqual(
                report["offline_precompute"]["phases"]["base_builder"]["status"],
                "completed",
            )
            for arm_id in (
                "offline_cold_precomputed",
                "preexisting_precomputed",
            ):
                arm = report["arms"][arm_id]
                self.assertEqual(arm["status"], "passed", arm)
                self.assertEqual(arm["counts"]["http_request_count"], 3)
                self.assertEqual(arm["counts"]["hybrid_query_count"], 1)
                self.assertGreater(arm["counts"]["graph_path_count"], 0)
                self.assertGreater(arm["counts"]["citation_count"], 0)
                self.assertEqual(
                    (
                        arm["cache"]["before"]["binding_snapshot_entry_count"],
                        arm["cache"]["before"]["entry_count"],
                        arm["cache"]["after"]["binding_snapshot_entry_count"],
                        arm["cache"]["after"]["entry_count"],
                    ),
                    (1, 1, 1, 1),
                )
                self.assertEqual(
                    arm["timing"]["semantic_phases"]["terminal_status"],
                    "completed",
                )
                self.assertIsNone(arm["timing"]["semantic_phases"]["deadline_exhausted_phase"])

            claim_path, output_path = diagnostic_cli._relation_projection_equivalence_paths(
                state_root,
                contract=_TEST_CONTRACT,
            )
            self.assertTrue(claim_path.is_file())
            self.assertTrue(output_path.is_file())
            claim = json.loads(claim_path.read_text(encoding="utf-8"))
            self.assertEqual(claim["status"], "consumed")
            self.assertEqual(
                claim["offline_preflight_fingerprint"],
                report["preflight"]["evidence_binding_fingerprint"],
            )
            rendered = json.dumps(
                {"claim": claim, "report": report},
                ensure_ascii=False,
                sort_keys=True,
            )
            for private_value in (
                _PRIVATE_PROMPT,
                "PO470002002",
                "ORIGIN-TAIWAN-01",
                "project_issue56_sealed_source_fixture",
                '"permission_scope"',
                '"tenant"',
                '"tenant_id"',
                str(state_root),
            ):
                self.assertNotIn(private_value, rendered)

    def test_source_permission_and_graph_drift_fail_before_claim(self) -> None:
        source = self._test_source()
        changed_node = replace(
            source.effective_graph_view.visible_nodes[0],
            permission_scope={
                "scope_type": "project",
                "scope_id": "project_issue56_permission_drift",
                "visibility": "public",
            },
        )
        changed_view = EffectiveGraphView(
            requester_user_id=source.effective_graph_view.requester_user_id,
            user_graph_revision_id=source.effective_graph_view.user_graph_revision_id,
            canonical_graph_revision_id=(source.effective_graph_view.canonical_graph_revision_id),
            ontology_revision_id=source.effective_graph_view.ontology_revision_id,
            assembly_policy_id=source.effective_graph_view.assembly_policy_id,
            visible_nodes=[
                changed_node,
                *source.effective_graph_view.visible_nodes[1:],
            ],
            visible_edges=list(source.effective_graph_view.visible_edges),
            access_required=list(source.effective_graph_view.access_required),
            applied_grant_ids=list(source.effective_graph_view.applied_grant_ids),
        )
        drifted_sources = (
            replace(source, source_binding_fingerprint=sha256_json("source drift")),
            replace(source, effective_graph_view=changed_view),
            replace(source, graph_revision_fingerprint=sha256_json("graph drift")),
        )
        for drifted in drifted_sources:
            with self.subTest(drift=drifted):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    state_root = Path(temporary_directory)
                    with self.assertRaises(ContractValidationError):
                        diagnostic_cli._run_relation_projection_equivalence_diagnostic_once(
                            loader=lambda selected=drifted: selected,
                            loader_spec_fingerprint=sha256_json(
                                "test relation projection v7 drift loader"
                            ),
                            state_root=state_root,
                            contract=_TEST_CONTRACT,
                        )
                    claim_path, output_path = diagnostic_cli._relation_projection_equivalence_paths(
                        state_root,
                        contract=_TEST_CONTRACT,
                    )
                    self.assertFalse(claim_path.exists())
                    self.assertFalse(output_path.exists())

    def test_race_has_one_claim_bearing_winner(self) -> None:
        source = self._test_source()
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory)

            def execute() -> dict[str, object]:
                return diagnostic_cli._run_relation_projection_equivalence_diagnostic_once(
                    loader=lambda: source,
                    loader_spec_fingerprint=sha256_json("test relation projection v7 race loader"),
                    state_root=state_root,
                    contract=_TEST_CONTRACT,
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(execute) for _ in range(2)]
            reports: list[dict[str, object]] = []
            errors: list[str] = []
            for future in futures:
                try:
                    reports.append(future.result())
                except ContractValidationError as exc:
                    errors.append(str(exc))

            self.assertEqual(len(reports), 1)
            self.assertEqual(reports[0]["status"], "passed")
            self.assertEqual(len(errors), 1)
            self.assertRegex(errors[0], "already exists|already consumed")

    def test_postclaim_cold_precompute_crash_consumes_without_report(self) -> None:
        source = self._test_source()
        loader_calls = 0

        def loader() -> diagnostic.Issue56SealedSourceDiagnosticInput:
            nonlocal loader_calls
            loader_calls += 1
            return source

        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory)
            with (
                mock.patch.object(
                    diagnostic_cli,
                    "precompute_issue56_offline_relation_projection_base",
                    side_effect=RuntimeError("synthetic v7 post-claim crash"),
                ),
                self.assertRaisesRegex(RuntimeError, "post-claim crash"),
            ):
                diagnostic_cli._run_relation_projection_equivalence_diagnostic_once(
                    loader=loader,
                    loader_spec_fingerprint=sha256_json("test relation projection v7 crash loader"),
                    state_root=state_root,
                    contract=_TEST_CONTRACT,
                )
            claim_path, output_path = diagnostic_cli._relation_projection_equivalence_paths(
                state_root,
                contract=_TEST_CONTRACT,
            )
            self.assertTrue(claim_path.is_file())
            self.assertFalse(output_path.exists())
            with self.assertRaisesRegex(
                ContractValidationError,
                "already consumed",
            ):
                diagnostic_cli._run_relation_projection_equivalence_diagnostic_once(
                    loader=loader,
                    loader_spec_fingerprint=sha256_json("test relation projection v7 crash loader"),
                    state_root=state_root,
                    contract=_TEST_CONTRACT,
                )
            self.assertEqual(loader_calls, 1)

    def test_v7_loader_and_v1_through_v6_guards_do_not_execute_formal_modes(
        self,
    ) -> None:
        fixture = real_prompt_fixture.Issue56RealPromptMcpPhaseTraceE2ETests(methodName="runTest")
        base = fixture._base_source()
        loaded = fixture._owner_loaded_fixture(base)
        selector = mock.Mock(
            return_value=SimpleNamespace(
                runtime_prompt=_PRIVATE_PROMPT,
                safe_selection_proof=fixture._owner_selection_proof(base),
            )
        )
        with mock.patch.object(
            gateway_loader,
            "_load_approved_sealed_source",
            return_value=loaded,
        ) as owner_loader:
            source = gateway_loader.load_issue56_relation_projection_offline_equivalence_v7_diagnostic_input(
                selector=selector,
            )
        owner_loader.assert_called_once_with()
        selector.assert_called_once()
        self.assertEqual(
            source.diagnostic_mode_id,
            diagnostic.ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_DIAGNOSTIC_MODE_ID,
        )
        self.assertEqual(
            source.loader_contract_fingerprint,
            gateway_loader.RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_LOADER_CONTRACT_FINGERPRINT,
        )

        formal_roots = {
            diagnostic_cli.run_relation_projection_equivalence_diagnostic_once: (
                diagnostic.ISSUE56_RELATION_PROJECTION_EQUIVALENCE_DIAGNOSTIC_MODE_ID
            ),
            diagnostic_cli.run_relation_projection_equivalence_v6_diagnostic_once: (
                diagnostic.ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_DIAGNOSTIC_MODE_ID
            ),
        }
        loader = mock.Mock()
        for runner, mode in formal_roots.items():
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(
                    ContractValidationError,
                    "immutable and already consumed",
                ):
                    runner(
                        loader=loader,
                        loader_spec_fingerprint=sha256_json("legacy loader"),
                        state_root=(_REPOSITORY_ROOT / ".test-tmp" / f"{mode}-state"),
                    )
        for runner in (
            diagnostic_cli.run_sealed_source_diagnostic_once,
            diagnostic_cli.run_real_prompt_sealed_source_diagnostic_once,
        ):
            with self.assertRaisesRegex(
                ContractValidationError,
                "immutable and already consumed",
            ):
                runner(
                    loader=loader,
                    loader_spec_fingerprint=sha256_json("legacy loader"),
                    state_root=Path("/tmp/unused-issue56-formal-state"),
                )
        loader.assert_not_called()

    def _test_source(self) -> diagnostic.Issue56SealedSourceDiagnosticInput:
        fixture = real_prompt_fixture.Issue56RealPromptMcpPhaseTraceE2ETests(methodName="runTest")
        source = fixture._v4_source()
        return diagnostic.build_issue56_sealed_source_diagnostic_input(
            session=source.session,
            effective_graph_view=source.effective_graph_view,
            allowed_relation_types=source.allowed_relation_types,
            source_asset_fingerprint=source.source_asset_fingerprint,
            loader_contract_fingerprint=(
                gateway_loader.RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_LOADER_CONTRACT_FINGERPRINT
            ),
            graph_revision_fingerprint=source.graph_revision_fingerprint,
            source_loader_binding_fingerprint=(source.source_loader_binding_fingerprint),
            lineage_crosswalk_precompute=(source.lineage_crosswalk_precompute.to_safe_dict()),
            relation_projection_base_precompute=(
                source.relation_projection_base_precompute.to_safe_dict()
            ),
            private_prompt=source.private_prompt,
            prompt_selection=source.prompt_selection.to_safe_dict(),
            diagnostic_mode_id=_TEST_MODE_ID,
        )


if __name__ == "__main__":
    unittest.main()
