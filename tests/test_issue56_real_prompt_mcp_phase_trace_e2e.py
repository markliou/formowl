from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, sha256_json
from formowl_gateway import issue56_sealed_source_loader as gateway_loader
from formowl_gateway.issue56_diagnostic import (
    ISSUE56_DIAGNOSTIC_IDENTITY_SCOPE_MODE,
    ISSUE56_DIAGNOSTIC_USER_ID,
    ISSUE56_DIAGNOSTIC_WORKSPACE_ID,
    ISSUE56_REAL_PROMPT_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
    ISSUE56_REAL_PROMPT_SEALED_SOURCE_LOADER_CONTRACT_ID,
    ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
    ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V1_MODE_ID,
    ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V2_MODE_ID,
    Issue56SealedSourceDiagnosticInput,
    build_issue56_sealed_source_diagnostic_input,
)
from formowl_mail import issue56_real_prompt as owner_prompt
from scripts import issue56_prompt_mcp_hybrid_diagnostic as diagnostic_cli
import test_issue56_prompt_mcp_hybrid_e2e as existing_diagnostic_fixture


_PRIVATE_PROMPT = "PO470002002 與 ORIGIN-TAIWAN-01 的關係"


class Issue56RealPromptMcpPhaseTraceE2ETests(unittest.TestCase):
    def test_stub_selector_loads_after_sealed_source_and_real_prompt_crosses_http(
        self,
    ) -> None:
        base = self._base_source()
        loaded = self._owner_loaded_fixture(base)
        events: list[str] = []

        def load_owner_source() -> object:
            events.append("load")
            return loaded

        def selector(**values: object) -> object:
            self.assertIs(values["session"], loaded.session)
            self.assertIs(
                values["effective_graph_view"],
                loaded.effective_graph_view,
            )
            self.assertIs(
                values["candidate_inventory"],
                loaded.identifier_mention_batch,
            )
            self.assertEqual(
                values["allowed_relation_types"],
                ("origin_in", "supplied_by"),
            )
            events.append("select")
            return SimpleNamespace(
                runtime_prompt=_PRIVATE_PROMPT,
                safe_selection_proof=self._owner_selection_proof(base),
            )

        with (
            mock.patch.object(
                gateway_loader,
                "_load_approved_sealed_source",
                side_effect=load_owner_source,
            ),
            mock.patch.object(
                owner_prompt,
                "select_source_backed_connected_identifier_prompt",
                side_effect=selector,
                create=True,
            ) as owner_selector,
        ):
            source = gateway_loader.load_issue56_real_prompt_sealed_source_diagnostic_input()
        self.assertEqual(events, ["load", "select"])
        owner_selector.assert_called_once()
        self.assertEqual(
            source.diagnostic_mode_id,
            ISSUE56_REAL_PROMPT_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
        )
        self.assertEqual(source.private_prompt, _PRIVATE_PROMPT)
        self.assertEqual(source.prompt_selection.lexical_anchor_count, 2)

        loader_calls = 0

        def loader() -> Issue56SealedSourceDiagnosticInput:
            nonlocal loader_calls
            loader_calls += 1
            return source

        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory)
            report = diagnostic_cli.run_real_prompt_sealed_source_diagnostic_once(
                loader=loader,
                loader_spec_fingerprint=sha256_json(
                    {
                        "loader_contract_id": (
                            ISSUE56_REAL_PROMPT_SEALED_SOURCE_LOADER_CONTRACT_ID
                        ),
                        "loader_spec": gateway_loader.REAL_PROMPT_LOADER_SPEC,
                    }
                ),
                state_root=state_root,
            )
            self.assertEqual(loader_calls, 1)
            self.assertEqual(report["status"], "passed", report)
            self.assertTrue(report["diagnostic_only"])
            self.assertEqual(report["methodology_authority_status"], "blocked")
            self.assertEqual(report["source_fixture_mode"], "sealed_source_real_prompt")
            self.assertEqual(
                report["identity_scope_mode"],
                ISSUE56_DIAGNOSTIC_IDENTITY_SCOPE_MODE,
            )
            self.assertGreater(report["counts"]["lexical_anchor_count"], 0)
            self.assertGreater(
                report["counts"]["source_selected_connected_path_count"],
                0,
            )
            self.assertGreater(report["counts"]["graph_path_count"], 0)
            self.assertGreater(report["counts"]["citation_count"], 0)
            self.assertEqual(
                report["boundary_status"]["source_backed_prompt_selection"],
                "passed",
            )
            self.assertEqual(
                report["boundary_status"]["semantic_phase_completion"],
                "passed",
            )
            phase_trace = report["timing"]["semantic_phases"]
            self.assertEqual(phase_trace["terminal_status"], "completed")
            self.assertTrue(phase_trace["phases"])
            self.assertTrue(
                all(phase["outcome"] in {"completed", "skipped"} for phase in phase_trace["phases"])
            )
            self.assertIsNone(phase_trace["deadline_exhausted_phase"])
            rendered = json.dumps(report, ensure_ascii=False, sort_keys=True)
            self.assertNotIn(_PRIVATE_PROMPT, rendered)
            self.assertNotIn("PO470002002", rendered)
            self.assertNotIn("ORIGIN-TAIWAN-01", rendered)
            self.assertNotIn('"tenant"', rendered.lower())
            self.assertNotIn('"tenant_id"', rendered.lower())

            claim_path, report_path = diagnostic_cli._real_prompt_sealed_paths(state_root)
            self.assertTrue(claim_path.is_file())
            self.assertTrue(report_path.is_file())
            claim = json.loads(claim_path.read_text(encoding="utf-8"))
            self.assertEqual(
                claim["diagnostic_mode_id"],
                ISSUE56_REAL_PROMPT_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
            )
            self.assertEqual(claim["status"], "consumed")
            self.assertNotIn(_PRIVATE_PROMPT, json.dumps(claim))

            with self.assertRaisesRegex(ContractValidationError, "already consumed"):
                diagnostic_cli.run_real_prompt_sealed_source_diagnostic_once(
                    loader=loader,
                    loader_spec_fingerprint=sha256_json(
                        {
                            "loader_contract_id": (
                                ISSUE56_REAL_PROMPT_SEALED_SOURCE_LOADER_CONTRACT_ID
                            ),
                            "loader_spec": gateway_loader.REAL_PROMPT_LOADER_SPEC,
                        }
                    ),
                    state_root=state_root,
                )
            self.assertEqual(loader_calls, 1)

    def test_selection_drift_fails_before_consumed_claim(self) -> None:
        source = self._v4_source()
        drifted = replace(source, private_prompt="different private prompt")
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory)
            with self.assertRaisesRegex(
                ContractValidationError,
                "prompt selection proof binding mismatch",
            ):
                diagnostic_cli.run_real_prompt_sealed_source_diagnostic_once(
                    loader=lambda: drifted,
                    loader_spec_fingerprint=sha256_json("stub loader"),
                    state_root=state_root,
                )
            claim_path, report_path = diagnostic_cli._real_prompt_sealed_paths(state_root)
            self.assertFalse(claim_path.exists())
            self.assertFalse(report_path.exists())

    def test_post_claim_failure_is_consumed_without_partial_report(self) -> None:
        source = self._v4_source()
        loader_calls = 0

        def loader() -> Issue56SealedSourceDiagnosticInput:
            nonlocal loader_calls
            loader_calls += 1
            return source

        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory)
            with (
                mock.patch.object(
                    diagnostic_cli,
                    "_run_http_diagnostic",
                    side_effect=RuntimeError("synthetic post-claim failure"),
                ),
                self.assertRaisesRegex(RuntimeError, "post-claim failure"),
            ):
                diagnostic_cli.run_real_prompt_sealed_source_diagnostic_once(
                    loader=loader,
                    loader_spec_fingerprint=sha256_json("stub loader"),
                    state_root=state_root,
                )
            claim_path, report_path = diagnostic_cli._real_prompt_sealed_paths(state_root)
            self.assertTrue(claim_path.is_file())
            self.assertFalse(report_path.exists())
            with self.assertRaisesRegex(ContractValidationError, "already consumed"):
                diagnostic_cli.run_real_prompt_sealed_source_diagnostic_once(
                    loader=loader,
                    loader_spec_fingerprint=sha256_json("stub loader"),
                    state_root=state_root,
                )
            self.assertEqual(loader_calls, 1)

    def test_v1_v2_v3_are_immutable_and_cannot_create_v4_state(self) -> None:
        for mode in (
            ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V1_MODE_ID,
            ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V2_MODE_ID,
            ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
        ):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                state_root = Path(directory)
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    exit_code = diagnostic_cli.main(
                        [
                            "--mode",
                            mode,
                            "--sealed-source-loader",
                            gateway_loader.REAL_PROMPT_LOADER_SPEC,
                            "--state-root",
                            str(state_root),
                        ]
                    )
                self.assertEqual(exit_code, 2)
                report = json.loads(stdout.getvalue())
                self.assertEqual(report["status"], "blocked")
                self.assertEqual(report["version_guard_status"], "consumed")
                self.assertEqual(list(state_root.iterdir()), [])
        legacy_loader = mock.Mock()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                ContractValidationError,
                "immutable and already consumed",
            ):
                diagnostic_cli.run_sealed_source_diagnostic_once(
                    loader=legacy_loader,
                    loader_spec_fingerprint=sha256_json("legacy loader"),
                    state_root=Path(directory),
                )
            legacy_loader.assert_not_called()

    def _v4_source(self) -> Issue56SealedSourceDiagnosticInput:
        base = self._base_source()
        return build_issue56_sealed_source_diagnostic_input(
            session=base.session,
            effective_graph_view=base.effective_graph_view,
            allowed_relation_types=base.allowed_relation_types,
            source_asset_fingerprint=base.source_asset_fingerprint,
            loader_contract_fingerprint=(gateway_loader.REAL_PROMPT_LOADER_CONTRACT_FINGERPRINT),
            graph_revision_fingerprint=base.graph_revision_fingerprint,
            source_loader_binding_fingerprint=(base.source_loader_binding_fingerprint),
            lineage_crosswalk_precompute=(base.lineage_crosswalk_precompute.to_safe_dict()),
            relation_projection_base_precompute=(
                base.relation_projection_base_precompute.to_safe_dict()
            ),
            private_prompt=_PRIVATE_PROMPT,
            prompt_selection=self._selection_binding(base),
            diagnostic_mode_id=(ISSUE56_REAL_PROMPT_SEALED_SOURCE_DIAGNOSTIC_MODE_ID),
        )

    def _base_source(self) -> Issue56SealedSourceDiagnosticInput:
        fixture = existing_diagnostic_fixture.Issue56PromptMcpHybridE2ETests(methodName="runTest")
        return fixture._build_temp_sealed_source()

    def _owner_loaded_fixture(
        self,
        base: Issue56SealedSourceDiagnosticInput,
    ) -> object:
        relation = base.relation_projection_base_precompute
        lineage = base.lineage_crosswalk_precompute
        counts = {
            "authorized_observation_count": base.observation_count,
            "graph_observation_node_count": relation.projected_node_count,
            "graph_entity_node_count": 0,
            "graph_edge_count": relation.adjacency_transition_count // 2,
        }
        safe_binding: dict[str, object] = {
            "status": "passed",
            "identity_scope_mode_status": ISSUE56_DIAGNOSTIC_IDENTITY_SCOPE_MODE,
            "tenant_dimension_status": "not_modeled_not_fabricated",
            "source_asset_fingerprint": base.source_asset_fingerprint,
            "permission_fingerprint": sha256_json("permission lineage fixture"),
            "index_fingerprint": lineage.index_fingerprint,
            "graph_revision_fingerprint": lineage.graph_revision_fingerprint,
            "candidate_admission_profile_fingerprint": (
                relation.candidate_admission_profile_fingerprint
            ),
            "counts": counts,
            "lineage_crosswalk_precompute": lineage.to_safe_dict(),
            "relation_projection_base_precompute": relation.to_safe_dict(),
        }
        safe_binding["binding_fingerprint"] = sha256_json(safe_binding)
        return SimpleNamespace(
            session=base.session,
            effective_graph_view=base.effective_graph_view,
            identifier_mention_batch=object(),
            safe_binding=safe_binding,
        )

    def _owner_selection_proof(
        self,
        base: Issue56SealedSourceDiagnosticInput,
    ) -> dict[str, object]:
        proof: dict[str, object] = {
            "artifact_id": (
                "formowl_issue56_source_backed_connected_identifier_prompt_selection_v1"
            ),
            "schema_version": 1,
            "status": "selected",
            "claim_boundary": ("diagnostic_prompt_selection_only_no_query_executed"),
            "selection_algorithm_id": (
                "issue56_source_backed_connected_identifier_prompt_selection_v1"
            ),
            "prompt_template_fingerprint": sha256_json(
                "issue56_private_identifier_relation_prompt_zh_v1"
            ),
            "selected_identifier_count": 2,
            "selected_term_hashes": [
                sha256_json("PO470002002"),
                sha256_json("ORIGIN-TAIWAN-01"),
            ],
            "selected_node_hashes": [
                sha256_json("node-po"),
                sha256_json("node-supplier"),
                sha256_json("node-origin"),
            ],
            "selected_edge_hashes": [
                sha256_json("edge-supplied-by"),
                sha256_json("edge-origin-in"),
            ],
            "selected_observation_hashes": [
                sha256_json("observation-1"),
                sha256_json("observation-2"),
            ],
            "identifier_support": [
                {
                    "term_hash": sha256_json("PO470002002"),
                    "node_hash": sha256_json("node-po"),
                    "support_observation_hashes": [sha256_json("observation-1")],
                },
                {
                    "term_hash": sha256_json("ORIGIN-TAIWAN-01"),
                    "node_hash": sha256_json("node-origin"),
                    "support_observation_hashes": [sha256_json("observation-2")],
                },
            ],
            "path_hop_count": 2,
            "path_node_count": 3,
            "path_edge_count": 2,
            "path_observation_count": 2,
            "allowed_relation_type_hashes": [
                sha256_json("origin_in"),
                sha256_json("supplied_by"),
            ],
            "max_hops": 2,
            "index_fingerprint": base.session.index.index_fingerprint,
            "graph_revision_fingerprint": base.graph_revision_fingerprint,
            "source_access_fingerprint": (base.session.authorized_source.authorization_fingerprint),
            "source_session_binding_fingerprint": sha256_json("source-session-binding"),
            "candidate_inventory_fingerprint": sha256_json("candidate-inventory"),
            "identity_scope_mode_fingerprint": sha256_json(ISSUE56_DIAGNOSTIC_IDENTITY_SCOPE_MODE),
            "identity_scope_fingerprint": sha256_json("workspace-only-scope"),
            "workspace_scope_fingerprint": sha256_json(ISSUE56_DIAGNOSTIC_WORKSPACE_ID),
            "requester_fingerprint": sha256_json(ISSUE56_DIAGNOSTIC_USER_ID),
            "synthetic_fallback_used": False,
            "query_executed": False,
        }
        proof["selection_proof_fingerprint"] = sha256_json(proof)
        return proof

    def _selection_binding(
        self,
        base: Issue56SealedSourceDiagnosticInput,
    ) -> dict[str, object]:
        proof = {
            "artifact_id": ("formowl_issue56_real_prompt_gateway_selection_binding_v1"),
            "schema_version": 1,
            "status": "passed",
            "prompt_hash": sha256_json(_PRIVATE_PROMPT),
            "source_loader_binding_fingerprint": (base.source_loader_binding_fingerprint),
            "permission_fingerprint": sha256_json("permission lineage fixture"),
            "owner_selection_proof": self._owner_selection_proof(base),
            "counts": {
                "lexical_anchor_count": 2,
                "selected_identifier_count": 2,
                "authorized_connected_graph_path_count": 1,
                "supporting_observation_count": 2,
            },
        }
        proof["selection_proof_fingerprint"] = sha256_json(proof)
        return proof


if __name__ == "__main__":
    unittest.main()
