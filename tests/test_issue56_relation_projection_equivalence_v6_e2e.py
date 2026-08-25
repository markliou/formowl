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
from test_issue56_relation_projection_equivalence_diagnostic_e2e import (
    _snapshot_formal_state_root,
)
import test_issue56_real_prompt_mcp_phase_trace_e2e as real_prompt_fixture


_TEST_MODE_ID = diagnostic._ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_TEST_MODE_ID
_TEST_CONTRACT = diagnostic_cli._RelationProjectionEquivalenceVersionContract(
    diagnostic_mode_id=_TEST_MODE_ID,
    loader_contract_id="issue56_relation_projection_equivalence_v6_test_loader_v0",
    claim_artifact_id=("formowl_issue56_relation_projection_equivalence_v6_test_claim_v0"),
    claim_schema_version=6,
    enforce_repository_state_root=False,
    preseal_graph_content=True,
)
_PRIVATE_PROMPT = "PO470002002 與 ORIGIN-TAIWAN-01 的關係"
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_FORMAL_V5_STATE_ROOT = (
    _REPOSITORY_ROOT
    / ".test-tmp"
    / (f"{diagnostic.ISSUE56_RELATION_PROJECTION_EQUIVALENCE_DIAGNOSTIC_MODE_ID}" "-state")
)
_FORMAL_V6_STATE_ROOT = (
    _REPOSITORY_ROOT
    / ".test-tmp"
    / (f"{diagnostic.ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_DIAGNOSTIC_MODE_ID}" "-state")
)


class Issue56RelationProjectionEquivalenceV6EndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self._formal_state_root_snapshots = {
            "v5": _snapshot_formal_state_root(_FORMAL_V5_STATE_ROOT),
            "v6": _snapshot_formal_state_root(_FORMAL_V6_STATE_ROOT),
        }

    def tearDown(self) -> None:
        self.assertEqual(
            {
                "v5": _snapshot_formal_state_root(_FORMAL_V5_STATE_ROOT),
                "v6": _snapshot_formal_state_root(_FORMAL_V6_STATE_ROOT),
            },
            self._formal_state_root_snapshots,
            "focused tests must preserve formal v5/v6 state roots byte-for-byte",
        )

    def test_presealed_cold_and_primed_arms_are_equivalent_over_full_http(
        self,
    ) -> None:
        source = self._test_source()
        real_content_builder = hybrid_module._build_effective_graph_content_snapshot
        real_base_builder = hybrid_module._build_relation_projection_base
        real_public_materializer = formowl_mail.precompute_effective_graph_content_snapshot

        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory)
            with (
                mock.patch.object(
                    formowl_mail,
                    "precompute_effective_graph_content_snapshot",
                    wraps=real_public_materializer,
                ) as materialize_content,
                mock.patch.object(
                    hybrid_module,
                    "_build_effective_graph_content_snapshot",
                    wraps=real_content_builder,
                ) as build_content,
                mock.patch.object(
                    hybrid_module,
                    "_build_relation_projection_base",
                    wraps=real_base_builder,
                ) as build_base,
            ):
                report = diagnostic_cli._run_relation_projection_equivalence_diagnostic_once(
                    loader=lambda: source,
                    loader_spec_fingerprint=sha256_json("test relation projection v6 loader"),
                    state_root=state_root,
                    contract=_TEST_CONTRACT,
                )

            self.assertEqual(materialize_content.call_count, 1)
            self.assertEqual(build_content.call_count, 1)
            self.assertEqual(build_base.call_count, 1)
            self.assertEqual(report["status"], "passed", report)
            self.assertEqual(report["schema_version"], 2)
            self.assertTrue(all(report["equivalence"].values()))
            self.assertTrue(all(report["cache_acceptance"].values()))
            self.assertEqual(
                report["boundary_status"]["graph_content_preseal"],
                "passed",
            )
            preseal_counts = report["graph_content_preseal"]["counts"]
            self.assertEqual(
                {
                    key: preseal_counts[key]
                    for key in (
                        "before_binding_cache_entry_count",
                        "before_base_cache_entry_count",
                        "after_binding_cache_entry_count",
                        "after_base_cache_entry_count",
                    )
                },
                {
                    "before_binding_cache_entry_count": 0,
                    "before_base_cache_entry_count": 0,
                    "after_binding_cache_entry_count": 1,
                    "after_base_cache_entry_count": 1,
                },
            )
            self.assertEqual(
                {
                    key: preseal_counts[key]
                    for key in (
                        "authorized_observation_count",
                        "source_scope_count",
                        "node_count",
                        "edge_count",
                        "access_required_count",
                        "applied_grant_count",
                    )
                },
                {
                    "authorized_observation_count": source.observation_count,
                    "source_scope_count": len(source.session.authorized_source_scope_ids),
                    "node_count": len(source.effective_graph_view.visible_nodes),
                    "edge_count": len(source.effective_graph_view.visible_edges),
                    "access_required_count": len(source.effective_graph_view.access_required),
                    "applied_grant_count": len(source.effective_graph_view.applied_grant_ids),
                },
            )
            self.assertEqual(
                report["counts"]["before_relation_binding_build_count"],
                1,
            )
            self.assertEqual(
                report["counts"]["before_relation_base_build_count"],
                1,
            )
            self.assertEqual(
                report["counts"]["after_relation_binding_build_count"],
                0,
            )
            self.assertEqual(
                report["counts"]["after_relation_base_build_count"],
                0,
            )
            self.assertEqual(
                (
                    report["arms"]["before_cold"]["cache"]["before"][
                        "binding_snapshot_entry_count"
                    ],
                    report["arms"]["before_cold"]["cache"]["before"]["entry_count"],
                    report["arms"]["before_cold"]["cache"]["after"]["binding_snapshot_entry_count"],
                    report["arms"]["before_cold"]["cache"]["after"]["entry_count"],
                ),
                (0, 0, 1, 1),
            )
            self.assertEqual(
                (
                    report["arms"]["after_precomputed"]["cache"]["before"][
                        "binding_snapshot_entry_count"
                    ],
                    report["arms"]["after_precomputed"]["cache"]["before"]["entry_count"],
                    report["arms"]["after_precomputed"]["cache"]["after"][
                        "binding_snapshot_entry_count"
                    ],
                    report["arms"]["after_precomputed"]["cache"]["after"]["entry_count"],
                ),
                (1, 1, 1, 1),
            )
            for arm_id in ("before_cold", "after_precomputed"):
                arm = report["arms"][arm_id]
                self.assertEqual(arm["status"], "passed", arm)
                self.assertEqual(arm["counts"]["http_request_count"], 3)
                self.assertEqual(arm["counts"]["hybrid_query_count"], 1)
                self.assertGreater(arm["counts"]["graph_path_count"], 0)
                self.assertGreater(arm["counts"]["citation_count"], 0)
                self.assertEqual(
                    arm["timing"]["semantic_phases"]["terminal_status"],
                    "completed",
                )
                self.assertIsNone(arm["timing"]["semantic_phases"]["deadline_exhausted_phase"])
                graph_snapshot = self._phase(arm, "graph_snapshot")
                relation_projection = self._phase(
                    arm,
                    "relation_projection",
                )
                self.assertEqual(graph_snapshot["outcome"], "completed")
                self.assertEqual(relation_projection["outcome"], "completed")

            claim_path, output_path = diagnostic_cli._relation_projection_equivalence_paths(
                state_root,
                contract=_TEST_CONTRACT,
            )
            self.assertTrue(claim_path.is_file())
            self.assertTrue(output_path.is_file())
            claim = json.loads(claim_path.read_text(encoding="utf-8"))
            self.assertEqual(claim["status"], "consumed")
            self.assertEqual(
                claim["graph_content_preseal_fingerprint"],
                report["graph_content_preseal"]["evidence_binding_fingerprint"],
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

    def test_snapshot_objects_locks_and_both_cache_maps_are_isolated(self) -> None:
        before, after, evidence = (
            diagnostic.build_issue56_relation_projection_equivalence_v6_compositions(
                self._test_source()
            )
        )
        before_state = diagnostic._effective_graph_snapshot_cache_state(
            before.effective_graph_view,
            expected_graph_revision_fingerprint=(before.graph_revision_fingerprint),
        )
        after_state = diagnostic._effective_graph_snapshot_cache_state(
            after.effective_graph_view,
            expected_graph_revision_fingerprint=(after.graph_revision_fingerprint),
        )
        self.assertIsNot(before_state["snapshot"], after_state["snapshot"])
        self.assertIsNot(before_state["lock"], after_state["lock"])
        self.assertIsNot(
            before_state["binding_cache_container"],
            after_state["binding_cache_container"],
        )
        self.assertIsNot(
            before_state["base_cache_container"],
            after_state["base_cache_container"],
        )
        self.assertEqual(
            (
                before_state["binding_entry_count"],
                before_state["base_entry_count"],
                after_state["binding_entry_count"],
                after_state["base_entry_count"],
            ),
            (0, 0, 1, 1),
        )
        self.assertEqual(evidence.status, "passed")

    def test_permission_drift_fails_before_claim(self) -> None:
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
            user_graph_revision_id=(source.effective_graph_view.user_graph_revision_id),
            canonical_graph_revision_id=(source.effective_graph_view.canonical_graph_revision_id),
            ontology_revision_id=(source.effective_graph_view.ontology_revision_id),
            assembly_policy_id=source.effective_graph_view.assembly_policy_id,
            visible_nodes=[
                changed_node,
                *source.effective_graph_view.visible_nodes[1:],
            ],
            visible_edges=list(source.effective_graph_view.visible_edges),
            access_required=list(source.effective_graph_view.access_required),
            applied_grant_ids=list(source.effective_graph_view.applied_grant_ids),
        )
        drifted = replace(source, effective_graph_view=changed_view)
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory)
            with self.assertRaisesRegex(
                ContractValidationError,
                "permission scope mismatch",
            ):
                diagnostic_cli._run_relation_projection_equivalence_diagnostic_once(
                    loader=lambda: drifted,
                    loader_spec_fingerprint=sha256_json("test relation projection v6 drift loader"),
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
                    loader_spec_fingerprint=sha256_json("test relation projection v6 race loader"),
                    state_root=state_root,
                    contract=_TEST_CONTRACT,
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(execute) for _ in range(2)]
            reports = []
            errors = []
            for future in futures:
                try:
                    reports.append(future.result())
                except ContractValidationError as exc:
                    errors.append(str(exc))

            self.assertEqual(len(reports), 1)
            self.assertEqual(reports[0]["status"], "passed")
            self.assertEqual(len(errors), 1)
            self.assertRegex(errors[0], "already exists|already consumed")
            claim_path, output_path = diagnostic_cli._relation_projection_equivalence_paths(
                state_root,
                contract=_TEST_CONTRACT,
            )
            self.assertTrue(claim_path.is_file())
            self.assertTrue(output_path.is_file())

    def test_postclaim_crash_is_consumed_without_partial_report(self) -> None:
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
                    "_execute_http_diagnostic_exchange",
                    side_effect=RuntimeError("synthetic v6 post-claim crash"),
                ),
                self.assertRaisesRegex(RuntimeError, "post-claim crash"),
            ):
                diagnostic_cli._run_relation_projection_equivalence_diagnostic_once(
                    loader=loader,
                    loader_spec_fingerprint=sha256_json("test relation projection v6 crash loader"),
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
                    loader_spec_fingerprint=sha256_json("test relation projection v6 crash loader"),
                    state_root=state_root,
                    contract=_TEST_CONTRACT,
                )
            self.assertEqual(loader_calls, 1)

    def test_v6_loader_and_version_guards_do_not_execute_formal_modes(
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
            source = (
                gateway_loader.load_issue56_relation_projection_equivalence_v6_diagnostic_input(
                    selector=selector,
                )
            )
        owner_loader.assert_called_once_with()
        selector.assert_called_once()
        self.assertEqual(
            source.diagnostic_mode_id,
            (diagnostic.ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_DIAGNOSTIC_MODE_ID),
        )
        self.assertEqual(
            source.loader_contract_fingerprint,
            gateway_loader.RELATION_PROJECTION_EQUIVALENCE_V6_LOADER_CONTRACT_FINGERPRINT,
        )

        loader = mock.Mock()
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(
                ContractValidationError,
                "state root mismatch",
            ):
                diagnostic_cli.run_relation_projection_equivalence_v6_diagnostic_once(
                    loader=loader,
                    loader_spec_fingerprint=sha256_json("formal v6 loader"),
                    state_root=Path(temporary_directory),
                )
        loader.assert_not_called()

        with self.assertRaisesRegex(
            ContractValidationError,
            "immutable and already consumed",
        ):
            diagnostic_cli.run_relation_projection_equivalence_diagnostic_once(
                loader=loader,
                loader_spec_fingerprint=sha256_json("formal v5 loader"),
                state_root=_FORMAL_V5_STATE_ROOT,
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
                gateway_loader.RELATION_PROJECTION_EQUIVALENCE_V6_LOADER_CONTRACT_FINGERPRINT
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

    @staticmethod
    def _phase(
        arm: dict[str, object],
        phase_name: str,
    ) -> dict[str, object]:
        phases = arm["timing"]["semantic_phases"]["phases"]
        return next(phase for phase in phases if phase["phase"] == phase_name)


if __name__ == "__main__":
    unittest.main()
