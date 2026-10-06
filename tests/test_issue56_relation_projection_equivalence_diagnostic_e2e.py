from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, sha256_json
from formowl_gateway import issue56_diagnostic as diagnostic
from formowl_gateway import issue56_sealed_source_loader as gateway_loader
from formowl_mail import hybrid as hybrid_module
from scripts import issue56_prompt_mcp_hybrid_diagnostic as diagnostic_cli
import test_issue56_real_prompt_mcp_phase_trace_e2e as real_prompt_fixture


_TEST_MODE_ID = diagnostic._ISSUE56_RELATION_PROJECTION_EQUIVALENCE_TEST_MODE_ID
_TEST_CONTRACT = diagnostic_cli._RelationProjectionEquivalenceVersionContract(
    diagnostic_mode_id=_TEST_MODE_ID,
    loader_contract_id="issue56_relation_projection_equivalence_test_loader_v0",
    claim_artifact_id=("formowl_issue56_relation_projection_equivalence_test_consumed_claim_v0"),
    claim_schema_version=1,
    enforce_repository_state_root=False,
)
_PRIVATE_PROMPT = "PO470002002 與 ORIGIN-TAIWAN-01 的關係"
_OFFICIAL_STATE_ROOT = (
    Path(__file__).resolve().parents[1]
    / ".test-tmp"
    / (f"{diagnostic.ISSUE56_RELATION_PROJECTION_EQUIVALENCE_DIAGNOSTIC_MODE_ID}" "-state")
)


def _snapshot_formal_state_root(
    root: Path,
) -> tuple[str, str | None, int | None, str | None, tuple[tuple[str, str, int, str | None], ...]]:
    """Capture hash-only immutable state without following links."""

    try:
        root.lstat()
    except FileNotFoundError:
        return ("absent", None, None, None, ())

    def file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return f"sha256:{digest.hexdigest()}"

    def entry_metadata(
        path: Path,
        relative_path: str,
    ) -> tuple[str, str, int, str | None]:
        metadata = path.lstat()
        if stat.S_ISREG(metadata.st_mode):
            entry_type = "regular_file"
            byte_sha256 = file_sha256(path)
        elif stat.S_ISDIR(metadata.st_mode):
            entry_type = "directory"
            byte_sha256 = None
        elif stat.S_ISLNK(metadata.st_mode):
            entry_type = "symlink"
            byte_sha256 = "sha256:" + hashlib.sha256(os.fsencode(os.readlink(path))).hexdigest()
        else:
            entry_type = "other"
            byte_sha256 = None
        return (
            relative_path,
            entry_type,
            metadata.st_size,
            byte_sha256,
        )

    root_entry = entry_metadata(root, ".")
    inventory: list[tuple[str, str, int, str | None]] = []

    def visit(directory: Path) -> None:
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda entry: entry.name)
        for entry in entries:
            path = Path(entry.path)
            relative_path = path.relative_to(root).as_posix()
            inventory.append(entry_metadata(path, relative_path))
            if entry.is_dir(follow_symlinks=False):
                visit(path)

    if root_entry[1] == "directory":
        visit(root)
    return (
        "present",
        root_entry[1],
        root_entry[2],
        root_entry[3],
        tuple(inventory),
    )


class Issue56RelationProjectionEquivalenceDiagnosticEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self._official_state_root_snapshot = _snapshot_formal_state_root(_OFFICIAL_STATE_ROOT)

    def tearDown(self) -> None:
        self.assertEqual(
            _snapshot_formal_state_root(_OFFICIAL_STATE_ROOT),
            self._official_state_root_snapshot,
            "focused tests must preserve the official v5 state root byte-for-byte",
        )

    def test_two_full_http_arms_are_semantically_equal_and_cache_isolated(
        self,
    ) -> None:
        source = self._test_source()
        loader_calls = 0

        def loader() -> diagnostic.Issue56SealedSourceDiagnosticInput:
            nonlocal loader_calls
            loader_calls += 1
            return source

        real_builder = hybrid_module._build_relation_projection_base
        real_ranker = hybrid_module._rank_relation_projection_query_anchors
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory)
            with (
                mock.patch.object(
                    hybrid_module,
                    "_build_relation_projection_base",
                    wraps=real_builder,
                ) as build_base,
                mock.patch.object(
                    hybrid_module,
                    "_rank_relation_projection_query_anchors",
                    wraps=real_ranker,
                ) as rank_anchors,
            ):
                report = diagnostic_cli._run_relation_projection_equivalence_diagnostic_once(
                    loader=loader,
                    loader_spec_fingerprint=sha256_json("test relation projection loader"),
                    state_root=state_root,
                    contract=_TEST_CONTRACT,
                )

            self.assertEqual(loader_calls, 1)
            self.assertEqual(build_base.call_count, 1)
            self.assertEqual(rank_anchors.call_count, 4)
            self.assertEqual(report["status"], "passed", report)
            self.assertTrue(all(report["equivalence"].values()))
            self.assertTrue(all(report["cache_acceptance"].values()))
            self.assertEqual(report["counts"]["arm_count"], 2)
            self.assertEqual(
                report["counts"]["owner_relation_base_precompute_count"],
                1,
            )
            self.assertEqual(
                report["counts"]["before_relation_base_build_count"],
                1,
            )
            self.assertEqual(
                report["counts"]["after_relation_base_build_count"],
                0,
            )
            for arm_id in ("before_cold", "after_precomputed"):
                arm = report["arms"][arm_id]
                self.assertEqual(arm["status"], "passed")
                self.assertEqual(arm["counts"]["http_request_count"], 3)
                self.assertEqual(arm["counts"]["hybrid_query_count"], 1)
                self.assertGreater(arm["counts"]["graph_path_count"], 0)
                self.assertGreater(arm["counts"]["citation_count"], 0)
                self.assertEqual(
                    arm["timing"]["semantic_phases"]["terminal_status"],
                    "completed",
                )
                self.assertIsNone(arm["timing"]["semantic_phases"]["deadline_exhausted_phase"])
                self.assertGreaterEqual(
                    arm["timing"]["relation_projection_elapsed_ms"],
                    0,
                )
                self.assertGreaterEqual(arm["timing"]["query_elapsed_ms"], 0)
                self.assertGreaterEqual(arm["timing"]["http_elapsed_ms"], 0)

            claim_path, output_path = diagnostic_cli._relation_projection_equivalence_paths(
                state_root,
                contract=_TEST_CONTRACT,
            )
            self.assertTrue(claim_path.is_file())
            self.assertTrue(output_path.is_file())
            self.assertEqual(
                json.loads(output_path.read_text(encoding="utf-8")),
                report,
            )
            claim = json.loads(claim_path.read_text(encoding="utf-8"))
            self.assertEqual(claim["status"], "consumed")
            self.assertEqual(claim["arm_count"], 2)

            rendered = json.dumps(report, ensure_ascii=False, sort_keys=True)
            for private_value in (
                _PRIVATE_PROMPT,
                "PO470002002",
                "ORIGIN-TAIWAN-01",
                "project_issue56_sealed_source_fixture",
                '"permission_scope"',
                '"tenant"',
                '"tenant_id"',
            ):
                self.assertNotIn(private_value, rendered)

            with self.assertRaisesRegex(
                ContractValidationError,
                "already consumed",
            ):
                diagnostic_cli._run_relation_projection_equivalence_diagnostic_once(
                    loader=loader,
                    loader_spec_fingerprint=sha256_json("test relation projection loader"),
                    state_root=state_root,
                    contract=_TEST_CONTRACT,
                )
            self.assertEqual(loader_calls, 1)

    def test_v5_loader_reuses_owner_precompute_without_second_invocation(
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
            source = gateway_loader.load_issue56_relation_projection_equivalence_diagnostic_input(
                selector=selector,
            )

        owner_loader.assert_called_once_with()
        selector.assert_called_once()
        self.assertEqual(
            source.diagnostic_mode_id,
            diagnostic.ISSUE56_RELATION_PROJECTION_EQUIVALENCE_DIAGNOSTIC_MODE_ID,
        )
        self.assertEqual(source.private_prompt, _PRIVATE_PROMPT)
        self.assertEqual(
            source.relation_projection_base_precompute.helper_invocation_count,
            1,
        )
        self.assertEqual(
            source.relation_projection_base_precompute.cache_status,
            "primed",
        )

    def test_preclaim_prompt_drift_does_not_consume_test_version(self) -> None:
        source = replace(
            self._test_source(),
            private_prompt="different private prompt",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory)
            with self.assertRaisesRegex(
                ContractValidationError,
                "prompt selection proof binding mismatch",
            ):
                diagnostic_cli._run_relation_projection_equivalence_diagnostic_once(
                    loader=lambda: source,
                    loader_spec_fingerprint=sha256_json("test drift loader"),
                    state_root=state_root,
                    contract=_TEST_CONTRACT,
                )
            claim_path, output_path = diagnostic_cli._relation_projection_equivalence_paths(
                state_root,
                contract=_TEST_CONTRACT,
            )
            self.assertFalse(claim_path.exists())
            self.assertFalse(output_path.exists())

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
                    side_effect=RuntimeError("synthetic post-claim crash"),
                ),
                self.assertRaisesRegex(
                    RuntimeError,
                    "post-claim crash",
                ),
            ):
                diagnostic_cli._run_relation_projection_equivalence_diagnostic_once(
                    loader=loader,
                    loader_spec_fingerprint=sha256_json("test crash loader"),
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
                    loader_spec_fingerprint=sha256_json("test crash loader"),
                    state_root=state_root,
                    contract=_TEST_CONTRACT,
                )
            self.assertEqual(loader_calls, 1)

    def test_official_v5_requires_canonical_root_and_v1_v4_remain_immutable(
        self,
    ) -> None:
        loader = mock.Mock()
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(
                ContractValidationError,
                "state root mismatch",
            ):
                diagnostic_cli.run_relation_projection_equivalence_diagnostic_once(
                    loader=loader,
                    loader_spec_fingerprint=sha256_json("official loader"),
                    state_root=Path(temporary_directory),
                )
        loader.assert_not_called()

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
                    state_root=Path("/tmp/unused-issue56-legacy-state"),
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
                gateway_loader.RELATION_PROJECTION_EQUIVALENCE_LOADER_CONTRACT_FINGERPRINT
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
