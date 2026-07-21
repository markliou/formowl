from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
for import_root in (ROOT / "python", ROOT / "tests", ROOT / "scripts"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from formowl_evidence import issue20_packet as packet_module  # noqa: E402
from formowl_evidence.issue20 import ISSUE20_IMPLEMENTATION_CONTRACT_GLOBS  # noqa: E402
from oauth_harness import (  # noqa: E402
    ISSUE20_BASE_COMMIT,
    changed_scoped_function_bindings,
    load_function_harness_manifest,
)


AUTHORITY_PATH = ROOT / "scripts" / "oauth_mcp_harness.py"
AUTHORITY_FIXTURE_PATH = ROOT / "tests" / "test_oauth_mcp_harness_script.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("issue20 finalization fixture import failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Issue20CompletionFinalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.authority = _load_module("issue20_finalization_authority", AUTHORITY_PATH)
        cls.fixture = _load_module(
            "issue20_finalization_authority_fixture",
            AUTHORITY_FIXTURE_PATH,
        )
        cls.operator_pin = cls.fixture._valid_operator_journey_authority_pin(cls.authority)
        cls.packet = cls.fixture._valid_external_evidence(cls.authority)
        cls.local_hash = cls.fixture._passing_local_completion_hash(cls.authority)

    def _copy_contract_root(self) -> Path:
        temporary = tempfile.TemporaryDirectory(prefix="formowl-issue20-finalization-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        copied: set[str] = set()
        patterns = (
            *ISSUE20_IMPLEMENTATION_CONTRACT_GLOBS,
            *self.authority._PRE_CLOSURE_DOCUMENTATION_CONTRACT_PATHS,
            *self.authority._REVIEWER_GATE_GOVERNANCE_PATHS,
            *self.authority._COMPLETION_STATE_CONTRACT_PATHS,
        )
        for pattern in patterns:
            matches = sorted(path for path in ROOT.glob(pattern) if path.is_file())
            if not matches:
                self.fail(f"issue20 finalization fixture missing: {pattern}")
            for source in matches:
                relative = source.relative_to(ROOT).as_posix()
                if relative in copied:
                    continue
                copied.add(relative)
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        return root

    def _append_line(self, path: Path, line: str) -> None:
        text = path.read_text(encoding="utf-8")
        path.write_text(f"{text.rstrip()}\n\n{line}\n", encoding="utf-8")

    def _write_json(self, path: Path, value) -> None:
        path.write_text(
            json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

    def _completion_document_texts(self, root: Path) -> dict[str, str]:
        return {
            relative_path: (root / relative_path).read_text(encoding="utf-8")
            for relative_path in self.authority._COMPLETION_STATE_CONTRACT_PATHS
        }

    def _complete_mutable_state(self, root: Path) -> None:
        expected = self.authority._issue20_expected_completion_document_texts(
            self._completion_document_texts(root)
        )
        self.assertEqual(set(expected), set(self.authority._COMPLETION_STATE_CONTRACT_PATHS))
        for relative_path, text in expected.items():
            (root / relative_path).write_text(text, encoding="utf-8")

    def _build_preclosure(self, packet: dict, root: Path) -> dict:
        return self.authority.build_issue20_preclosure_manifest(
            packet,
            expected_local_harness_report_hash=self.local_hash,
            expected_operator_execution_authority_pin=self.operator_pin,
            operator_attested=True,
            root=root,
        )

    def _validate_preclosure(
        self,
        manifest,
        packet: dict,
        root: Path,
        *,
        require_current_before_state: bool,
    ) -> dict:
        return self.authority.validate_issue20_preclosure_manifest(
            manifest,
            external_evidence=packet,
            expected_local_harness_report_hash=self.local_hash,
            expected_operator_execution_authority_pin=self.operator_pin,
            root=root,
            require_current_before_state=require_current_before_state,
        )

    def _build_transition(
        self,
        packet: dict,
        manifest: dict,
        root: Path,
    ) -> dict:
        return self.authority.build_issue20_completion_transition(
            packet,
            preclosure_manifest=manifest,
            expected_local_harness_report_hash=self.local_hash,
            expected_operator_execution_authority_pin=self.operator_pin,
            operator_attested=True,
            root=root,
        )

    def _validate_transition(
        self,
        transition,
        packet: dict,
        manifest,
        root: Path,
    ) -> dict:
        return self.authority.validate_issue20_completion_transition(
            transition,
            external_evidence=packet,
            preclosure_manifest=manifest,
            expected_local_harness_report_hash=self.local_hash,
            expected_operator_execution_authority_pin=self.operator_pin,
            root=root,
        )

    def test_contract_path_sets_are_exact_and_mutually_exclusive(self) -> None:
        self.assertEqual(
            self.authority._PRE_CLOSURE_OPERATOR_DEPLOY_DOCUMENTATION_PATHS,
            (
                "deploy/connected/Caddyfile.example",
                "deploy/connected/compose.env.example",
                "deploy/connected/secrets/README.md",
                "deploy/connected/signing-key-set.example.json",
            ),
        )
        self.assertEqual(
            self.authority._PRE_CLOSURE_DOCUMENTATION_CONTRACT_PATHS,
            (
                "SPEC.md",
                "deploy/connected/Caddyfile.example",
                "deploy/connected/compose.env.example",
                "deploy/connected/secrets/README.md",
                "deploy/connected/signing-key-set.example.json",
                "docs/closed-beta-runbook.md",
                "docs/infra-spec.md",
                "docs/mcp-boundaries.md",
                "docs/workflows.md",
                "docs/issue20-oauth-evidence-runbook.md",
            ),
        )
        self.assertEqual(
            self.authority._REVIEWER_GATE_GOVERNANCE_PATHS,
            ("docs/agent-goals/reviewer-gate.md",),
        )
        self.assertEqual(
            self.authority._COMPLETION_STATE_CONTRACT_PATHS,
            (
                "README.md",
                "docs/implementation-task-breakdown.md",
                "docs/agent-goals/system-backbone-agent.md",
                "docs/agent-goals/handoff-log.md",
                "docs/issue20-account-system-verification-status.md",
            ),
        )
        path_sets = (
            set(self.authority._PRE_CLOSURE_DOCUMENTATION_CONTRACT_PATHS),
            set(self.authority._REVIEWER_GATE_GOVERNANCE_PATHS),
            set(self.authority._COMPLETION_STATE_CONTRACT_PATHS),
        )
        self.assertFalse(path_sets[0] & path_sets[1])
        self.assertFalse(path_sets[0] & path_sets[2])
        self.assertFalse(path_sets[1] & path_sets[2])
        self.assertEqual(
            self.authority._DOCUMENTATION_CONTRACT_PATHS,
            self.authority._PRE_CLOSURE_DOCUMENTATION_CONTRACT_PATHS,
        )

    def test_each_operator_deploy_document_invalidates_frozen_preclosure(self) -> None:
        for relative_path in self.authority._PRE_CLOSURE_OPERATOR_DEPLOY_DOCUMENTATION_PATHS:
            with self.subTest(relative_path=relative_path):
                root = self._copy_contract_root()
                packet = copy.deepcopy(self.packet)
                manifest = self._build_preclosure(packet, root)
                self.assertTrue(manifest)
                self._append_line(root / relative_path, "operator deploy documentation drift")
                self.assertFalse(
                    self._validate_preclosure(
                        manifest,
                        packet,
                        root,
                        require_current_before_state=True,
                    )["passed"]
                )

    def test_missing_operator_deploy_document_fails_preclosure_closed(self) -> None:
        for relative_path in self.authority._PRE_CLOSURE_OPERATOR_DEPLOY_DOCUMENTATION_PATHS:
            with self.subTest(relative_path=relative_path):
                root = self._copy_contract_root()
                (root / relative_path).unlink()
                packet = copy.deepcopy(self.packet)
                validation = self.authority.validate_external_evidence_packet(
                    packet,
                    expected_local_harness_report_hash=self.local_hash,
                    expected_operator_execution_authority_pin=self.operator_pin,
                    root=root,
                )
                self.assertFalse(validation["passed"])
                self.assertEqual(validation["blocker_count"], 2)
                self.assertEqual(
                    validation["blockers"],
                    [
                        "external evidence implementation contract validation failed",
                        "completion audit documentation contract binding mismatch",
                    ],
                )
                self.assertEqual(
                    validation["layer_statuses"],
                    {layer_name: "failed" for layer_name in self.authority._EXTERNAL_LAYER_FIELDS},
                )
                public_failure = json.dumps(validation, sort_keys=True)
                self.assertNotIn(relative_path, public_failure)
                self.assertNotIn("issue20_implementation_contract_missing", public_failure)
                self.assertEqual(self._build_preclosure(packet, root), {})

    def test_ignored_operator_state_does_not_change_frozen_preclosure(self) -> None:
        root = self._copy_contract_root()
        packet = copy.deepcopy(self.packet)
        operator_state = root / ".formowl/issue20/operator-state.json"
        ignored_secret = root / "deploy/connected/secrets/database-dsn"
        for path in (operator_state, ignored_secret):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("ignored:first\n", encoding="utf-8")

        manifest = self._build_preclosure(packet, root)
        self.assertTrue(manifest)
        operator_state.write_text("ignored:second\n", encoding="utf-8")
        ignored_secret.write_text("ignored:second\n", encoding="utf-8")

        self.assertTrue(
            self._validate_preclosure(
                manifest,
                packet,
                root,
                require_current_before_state=True,
            )["passed"]
        )

    def test_preclosure_rejects_already_completed_mutable_state(self) -> None:
        root = self._copy_contract_root()
        self._complete_mutable_state(root)
        self.assertEqual(self._build_preclosure(copy.deepcopy(self.packet), root), {})

    def test_mutable_completion_state_does_not_invalidate_frozen_preclosure(self) -> None:
        root = self._copy_contract_root()
        packet = copy.deepcopy(self.packet)
        manifest = self._build_preclosure(packet, root)
        self.assertTrue(manifest)
        self.assertTrue(
            self._validate_preclosure(
                manifest,
                packet,
                root,
                require_current_before_state=True,
            )["passed"]
        )

        self._complete_mutable_state(root)

        self.assertTrue(
            self._validate_preclosure(
                manifest,
                packet,
                root,
                require_current_before_state=False,
            )["passed"]
        )
        transition = self._build_transition(packet, manifest, root)
        self.assertTrue(transition)
        validation = self._validate_transition(transition, packet, manifest, root)
        self.assertTrue(validation["passed"])
        self.assertTrue(validation["supports_issue20_closure_claim"])

    def test_substantive_or_governance_drift_invalidates_closure(self) -> None:
        for relative_path in ("SPEC.md", "docs/agent-goals/reviewer-gate.md"):
            with self.subTest(relative_path=relative_path):
                root = self._copy_contract_root()
                packet = copy.deepcopy(self.packet)
                manifest = self._build_preclosure(packet, root)
                self.assertTrue(manifest)
                self._complete_mutable_state(root)
                self._append_line(root / relative_path, "governed drift")
                self.assertFalse(
                    self._validate_preclosure(
                        manifest,
                        packet,
                        root,
                        require_current_before_state=False,
                    )["passed"]
                )
                self.assertEqual(self._build_transition(packet, manifest, root), {})

    def test_transition_requires_reviewer_audit_and_all_external_layers(self) -> None:
        root = self._copy_contract_root()
        packet = copy.deepcopy(self.packet)
        manifest = self._build_preclosure(packet, root)
        self.assertTrue(manifest)
        self._complete_mutable_state(root)
        self.assertTrue(self._build_transition(packet, manifest, root))

        mutations = (
            ("reviewer_gate", "reviewer_count", 2),
            ("completion_audit", "status", "failed"),
            ("mcp_inspector", "status", "failed"),
        )
        for layer_name, field, value in mutations:
            with self.subTest(layer_name=layer_name, field=field):
                invalid = copy.deepcopy(packet)
                invalid["layers"][layer_name][field] = value
                self.assertEqual(
                    self._build_transition(invalid, manifest, root),
                    {},
                )

    def test_partial_completion_state_update_is_rejected(self) -> None:
        root = self._copy_contract_root()
        packet = copy.deepcopy(self.packet)
        manifest = self._build_preclosure(packet, root)
        self.assertTrue(manifest)
        board_path = root / "docs/implementation-task-breakdown.md"
        board_path.write_text(
            board_path.read_text(encoding="utf-8").replace(
                self.authority._ISSUE20_BOARD_OPEN_MARKER,
                self.authority._ISSUE20_BOARD_COMPLETE_MARKER,
            ),
            encoding="utf-8",
        )
        self.assertEqual(self._build_transition(packet, manifest, root), {})

    def test_unrelated_mutable_document_delta_is_rejected(self) -> None:
        for relative_path in self.authority._COMPLETION_STATE_CONTRACT_PATHS:
            with self.subTest(relative_path=relative_path):
                root = self._copy_contract_root()
                packet = copy.deepcopy(self.packet)
                manifest = self._build_preclosure(packet, root)
                self.assertTrue(manifest)
                self._complete_mutable_state(root)
                path = root / relative_path
                text = path.read_text(encoding="utf-8")
                path.write_text(
                    text.replace(
                        "\n",
                        "\nUnrelated mutable-state text must not be accepted.\n",
                        1,
                    ),
                    encoding="utf-8",
                )
                self.assertEqual(self._build_transition(packet, manifest, root), {})

    def test_other_checkbox_issue41_and_production_claim_mutations_are_rejected(self) -> None:
        mutation_kinds = ("other_checkbox", "issue41", "production_claim")
        for mutation_kind in mutation_kinds:
            with self.subTest(mutation_kind=mutation_kind):
                root = self._copy_contract_root()
                packet = copy.deepcopy(self.packet)
                manifest = self._build_preclosure(packet, root)
                self.assertTrue(manifest)
                self._complete_mutable_state(root)
                board_path = root / "docs/implementation-task-breakdown.md"
                if mutation_kind == "production_claim":
                    self._append_line(root / "README.md", "FormOwl is production-ready.")
                elif mutation_kind == "issue41":
                    board_path.write_text(
                        board_path.read_text(encoding="utf-8").replace(
                            self.authority._ISSUE41_BOARD_OPEN_MARKER,
                            self.authority._ISSUE41_BOARD_OPEN_MARKER.replace(
                                "- [ ]",
                                "- [x]",
                                1,
                            ),
                        ),
                        encoding="utf-8",
                    )
                else:
                    board_text = board_path.read_text(encoding="utf-8")
                    other_open = next(
                        line
                        for line in board_text.splitlines()
                        if line.startswith("- [ ] ")
                        and line != self.authority._ISSUE41_BOARD_OPEN_MARKER
                    )
                    board_path.write_text(
                        board_text.replace(
                            other_open,
                            other_open.replace("- [ ]", "- [x]", 1),
                            1,
                        ),
                        encoding="utf-8",
                    )
                self.assertEqual(self._build_transition(packet, manifest, root), {})

    def test_preclosure_rejects_production_readiness_wording_variants(self) -> None:
        root = self._copy_contract_root()
        self._append_line(root / "README.md", "FormOwl is ready for production.")
        self.assertEqual(self._build_preclosure(copy.deepcopy(self.packet), root), {})

    def test_preclosure_rejects_unresolved_wording_in_append_preserved_docs(self) -> None:
        for relative_path in (
            "README.md",
            "docs/agent-goals/handoff-log.md",
        ):
            with self.subTest(relative_path=relative_path):
                root = self._copy_contract_root()
                self._append_line(
                    root / relative_path,
                    "Issue #20 is unfinished and must stay unresolved.",
                )
                self.assertEqual(self._build_preclosure(copy.deepcopy(self.packet), root), {})

    def test_expected_completion_transform_preserves_durable_context(self) -> None:
        root = self._copy_contract_root()
        before = self._completion_document_texts(root)
        after = self.authority._issue20_expected_completion_document_texts(before)
        self.assertTrue(after)

        goal = after["docs/agent-goals/system-backbone-agent.md"]
        for preserved in (
            "Maintain and extend the system backbone behind the accepted FormOwl contracts:",
            "FormOwl System Backbone Agent. Durable role definition: `../agent-roles.md`.",
            "- Issue #41 still owns generic Asset tenant/owner binding, byte storage,",
            "- Lossless history: `../archive/2026-07-11/system-backbone-agent.md`",
        ):
            self.assertIn(preserved, goal)

        verification = after["docs/issue20-account-system-verification-status.md"]
        for preserved in (
            "## PM 快速檢查總表",
            "## 被檢查的完整帳號旅程",
            "## Reviewer finding 狀態與外部證據",
            "Cross-UID failure-diagnostic custody",
            "`test_id_count` 1,434",
            "Issue #41 是 blocking",
        ):
            self.assertIn(preserved, verification)
        self.assertGreaterEqual(
            len(verification),
            len(before["docs/issue20-account-system-verification-status.md"]),
        )

        client_authority_markers = {
            "README.md": (
                "derive or validate and record one stable non-secret predefined client ID",
                "ChatGPT supplies and displays only the",
                "production callback; never invent the ID or claim ChatGPT generated/displayed",
            ),
            "docs/agent-goals/system-backbone-agent.md": (
                "Preserve the operator-recorded predefined client ID and ChatGPT-displayed",
                "do not claim ChatGPT generated",
                "or displayed the client ID, and do not substitute another registration model.",
            ),
            "docs/agent-goals/handoff-log.md": (
                "helper now derives or validates one safe non-secret predefined client ID",
                "replaces only the ChatGPT-displayed callback",
                "the live campaign stops as an external blocker",
            ),
            "docs/issue20-account-system-verification-status.md": (
                "predefined client ID 必須由 operator 在 discovery 前",
                "ChatGPT app management 僅顯示 callback",
                "不可宣稱 ChatGPT 產生或顯示 client ID",
            ),
        }
        for relative_path, markers in client_authority_markers.items():
            with self.subTest(relative_path=relative_path):
                for marker in markers:
                    self.assertIn(marker, after[relative_path])

    def test_expected_completion_board_is_coherent_and_preserves_unrelated_work(self) -> None:
        root = self._copy_contract_root()
        before = self._completion_document_texts(root)
        after = self.authority._issue20_expected_completion_document_texts(before)
        self.assertTrue(after)
        board = after["docs/implementation-task-breakdown.md"]

        self.assertEqual(board.count(self.authority._ISSUE20_BOARD_COMPLETE_MARKER), 1)
        self.assertNotIn(self.authority._ISSUE20_BOARD_OPEN_MARKER, board)
        for contradiction in (
            "seven external layers remain `not_supplied`, so #20",
            "issue #20 stays unchecked and open",
            "and `completion_audit` remain `not_supplied`",
            "keep #20 unchecked",
        ):
            self.assertNotIn(contradiction, board)
        for preserved in (
            self.authority._ISSUE41_BOARD_OPEN_MARKER,
            "- [ ] Complete the full KG real-evidence objective across sessions.",
            "## Pre-Feature Production Cleanup",
            "## Pre-Feature Structural Cleanup",
        ):
            self.assertIn(preserved, board)

    def test_completion_transition_rejects_direct_closure_prohibition_bypass(self) -> None:
        root = self._copy_contract_root()
        self._complete_mutable_state(root)
        texts = self._completion_document_texts(root)
        readme_marker = self.authority._ISSUE20_README_COMPLETE_MARKER
        for contradiction in (
            "Issue #20 must not be closed.",
            "Do not close Issue #20.",
            "Issue #20 is not ready for closure.",
        ):
            with self.subTest(contradiction=contradiction):
                mutated = dict(texts)
                mutated["README.md"] = texts["README.md"].replace(
                    readme_marker,
                    f"{contradiction}\n\n{readme_marker}",
                    1,
                )
                semantics = self.authority._issue20_completion_document_semantics(mutated)
                self.assertFalse(semantics["completion_document_complete"]["README.md"])

        scoped = dict(texts)
        scoped["README.md"] = texts["README.md"].replace(
            readme_marker,
            (
                "Issue #20 closure does not establish general product production "
                f"readiness.\n\n{readme_marker}"
            ),
            1,
        )
        semantics = self.authority._issue20_completion_document_semantics(scoped)
        self.assertTrue(semantics["completion_document_complete"]["README.md"])

    def test_contradictory_completion_document_states_are_rejected(self) -> None:
        mutations = (
            (
                "docs/agent-goals/system-backbone-agent.md",
                "- Label: `active-blocked`",
            ),
            (
                "docs/agent-goals/handoff-log.md",
                "- Issue #20 remains open and unchecked.",
            ),
            (
                "docs/issue20-account-system-verification-status.md",
                self.authority._ISSUE20_VERIFICATION_OPEN_MARKER,
            ),
            (
                "README.md",
                "- Issue #20 remains open.",
            ),
        )
        for relative_path, contradiction in mutations:
            with self.subTest(relative_path=relative_path):
                root = self._copy_contract_root()
                packet = copy.deepcopy(self.packet)
                manifest = self._build_preclosure(packet, root)
                self.assertTrue(manifest)
                self._complete_mutable_state(root)
                self._append_line(root / relative_path, contradiction)
                self.assertEqual(self._build_transition(packet, manifest, root), {})

    def test_plan_substitution_replay_and_artifact_mismatch_are_rejected(self) -> None:
        root = self._copy_contract_root()
        packet = copy.deepcopy(self.packet)
        manifest = self._build_preclosure(packet, root)
        self.assertTrue(manifest)
        self._complete_mutable_state(root)
        transition = self._build_transition(packet, manifest, root)
        self.assertTrue(transition)

        substituted_manifest = copy.deepcopy(manifest)
        substituted_manifest["closure_transition_plan_hash"] = self.authority.sha256_json(
            {"plan": "substituted"}
        )
        substituted_manifest["evidence_artifact_hash"] = self.authority.sha256_json(
            {
                "binding_type": "issue20_preclosure_manifest_v1",
                "manifest_without_artifact_hash": {
                    key: value
                    for key, value in substituted_manifest.items()
                    if key != "evidence_artifact_hash"
                },
            }
        )
        self.assertEqual(
            self._build_transition(packet, substituted_manifest, root),
            {},
        )

        self.assertFalse(self._validate_transition(None, packet, manifest, root)["passed"])
        missing = copy.deepcopy(transition)
        missing.pop("evidence_artifact_hash")
        self.assertFalse(self._validate_transition(missing, packet, manifest, root)["passed"])
        tampered = copy.deepcopy(transition)
        tampered["completion_state_after_hashes_hash"] = self.authority.sha256_json(
            {"tampered": True}
        )
        self.assertFalse(self._validate_transition(tampered, packet, manifest, root)["passed"])

        self._append_line(root / "README.md", "post-transition replay drift")
        replay_validation = self._validate_transition(
            transition,
            packet,
            manifest,
            root,
        )
        self.assertFalse(replay_validation["passed"])
        self.assertFalse(replay_validation["supports_issue20_closure_claim"])

    def test_contract_hashing_rejects_escape_symlink_and_non_regular_files(self) -> None:
        root = self._copy_contract_root()
        self.assertEqual(
            self.authority._repository_contract_file_hashes(
                ("../escape",),
                root=root,
            ),
            {},
        )

        outside = Path(tempfile.mkdtemp(prefix="formowl-issue20-outside-"))
        self.addCleanup(shutil.rmtree, outside)
        outside_file = outside / "SPEC.md"
        outside_file.write_text("outside\n", encoding="utf-8")
        spec_path = root / "SPEC.md"
        spec_path.unlink()
        spec_path.symlink_to(outside_file)
        self.assertEqual(
            self.authority._repository_contract_file_hashes(("SPEC.md",), root=root),
            {},
        )

        spec_path.unlink()
        spec_path.mkdir()
        self.assertEqual(
            self.authority._repository_contract_file_hashes(("SPEC.md",), root=root),
            {},
        )

    def test_reviewer_packet_and_audit_sources_prebind_transition_plan(self) -> None:
        templates = packet_module.source_templates()
        reviewer = templates["reviewer_gate"]
        completion = templates["completion_audit"]
        for source in (reviewer, completion):
            self.assertEqual(
                source["closure_transition_plan_hash"],
                self.authority._CLOSURE_TRANSITION_PLAN_HASH,
            )
            self.assertEqual(
                source["reviewer_gate_governance_hash"],
                self.authority._repository_contract_hash(
                    self.authority._REVIEWER_GATE_GOVERNANCE_PATHS,
                ),
            )

        core_layers = {
            name: {
                "status": "passed",
                "evidence_artifact_hash": self.authority.sha256_json(name),
            }
            for name in (
                "live_postgresql",
                "operator_cli_postgresql",
                "production_container_lifecycle",
                "mcp_inspector",
                "live_chatgpt_google",
            )
        }
        review_packet = packet_module._core_evidence_review_packet(
            local_receipt={
                "implementation_contract_hash": self.authority.sha256_json("implementation"),
            },
            core_layers=core_layers,
            mcp_inspector_source_hash=self.authority.sha256_json("mcp-source"),
            live_chatgpt_google_source_hash=self.authority.sha256_json("live-source"),
        )
        self.assertEqual(
            review_packet["closure_transition_plan_hash"],
            self.authority._CLOSURE_TRANSITION_PLAN_HASH,
        )
        self.assertEqual(
            review_packet["reviewer_gate_governance_hash"],
            self.authority._repository_contract_hash(
                self.authority._REVIEWER_GATE_GOVERNANCE_PATHS,
            ),
        )

        tampered_reviewer = copy.deepcopy(reviewer)
        tampered_reviewer["closure_transition_plan_hash"] = self.authority.sha256_json("other-plan")
        self.assertIn(
            "reviewer_closure_transition_plan_mismatch",
            packet_module.validate_reviewer_gate_source(tampered_reviewer)["blockers"],
        )
        tampered_completion = copy.deepcopy(completion)
        tampered_completion["reviewer_gate_governance_hash"] = self.authority.sha256_json(
            "other-governance"
        )
        self.assertIn(
            "completion_reviewer_gate_governance_stale",
            packet_module.validate_completion_audit_source(tampered_completion)["blockers"],
        )

    def test_finalization_cli_builds_and_validates_artifacts_atomically(self) -> None:
        root = self._copy_contract_root()
        working = Path(tempfile.mkdtemp(prefix="formowl-issue20-finalization-cli-"))
        self.addCleanup(shutil.rmtree, working)
        packet_path = working / "external-evidence.json"
        pin_path = working / "operator-pin.json"
        preclosure_path = working / "preclosure.json"
        preclosure_validation_path = working / "preclosure-validation.json"
        transition_path = working / "transition.json"
        transition_validation_path = working / "transition-validation.json"
        self._write_json(packet_path, self.packet)
        self._write_json(pin_path, self.operator_pin)
        common = [
            "--external-evidence",
            str(packet_path),
            "--operator-cli-postgresql-authority-pin",
            str(pin_path),
            "--expected-local-harness-report-hash",
            self.local_hash,
        ]
        with patch.object(self.authority, "ROOT", root):
            self.assertEqual(
                self.authority.main(
                    [
                        "--issue20-finalization-action",
                        "build-preclosure-manifest",
                        "--operator-attest-finalization",
                        *common,
                        "--output",
                        str(preclosure_path),
                    ]
                ),
                0,
            )
            preclosure = json.loads(preclosure_path.read_text(encoding="utf-8"))
            self.assertEqual(preclosure["status"], "passed")
            self.assertEqual(
                self.authority.main(
                    [
                        "--issue20-finalization-action",
                        "validate-preclosure-manifest",
                        "--preclosure-manifest",
                        str(preclosure_path),
                        *common,
                        "--output",
                        str(preclosure_validation_path),
                    ]
                ),
                0,
            )
            self.assertTrue(
                json.loads(preclosure_validation_path.read_text(encoding="utf-8"))["passed"]
            )

            self._complete_mutable_state(root)

            self.assertEqual(
                self.authority.main(
                    [
                        "--issue20-finalization-action",
                        "build-completion-transition",
                        "--preclosure-manifest",
                        str(preclosure_path),
                        "--operator-attest-finalization",
                        *common,
                        "--output",
                        str(transition_path),
                    ]
                ),
                0,
            )
            transition = json.loads(transition_path.read_text(encoding="utf-8"))
            self.assertEqual(
                transition["artifact_type"],
                self.authority._COMPLETION_TRANSITION_TYPE,
            )
            self.assertEqual(
                self.authority.main(
                    [
                        "--issue20-finalization-action",
                        "validate-completion-transition",
                        "--preclosure-manifest",
                        str(preclosure_path),
                        "--completion-transition",
                        str(transition_path),
                        *common,
                        "--output",
                        str(transition_validation_path),
                    ]
                ),
                0,
            )
            self.assertTrue(
                json.loads(transition_validation_path.read_text(encoding="utf-8"))[
                    "supports_issue20_closure_claim"
                ]
            )

            prior = b'{"prior":true}\n'
            failed_output = working / "failed-output.json"
            failed_output.write_bytes(prior)
            with patch.object(
                self.authority,
                "write_json_atomic",
                side_effect=OSError("synthetic write failure"),
            ):
                self.assertEqual(
                    self.authority.main(
                        [
                            "--issue20-finalization-action",
                            "validate-completion-transition",
                            "--preclosure-manifest",
                            str(preclosure_path),
                            "--completion-transition",
                            str(transition_path),
                            *common,
                            "--output",
                            str(failed_output),
                        ]
                    ),
                    1,
                )
            self.assertEqual(failed_output.read_bytes(), prior)
            self.assertFalse(failed_output.with_suffix(f"{failed_output.suffix}.tmp").exists())

    def test_malformed_preclosure_array_fails_closed_without_replacing_output(self) -> None:
        root = self._copy_contract_root()
        self.assertEqual(
            self.authority.build_issue20_completion_transition(
                copy.deepcopy(self.packet),
                preclosure_manifest=[],
                expected_local_harness_report_hash=self.local_hash,
                expected_operator_execution_authority_pin=self.operator_pin,
                operator_attested=True,
                root=root,
            ),
            {},
        )

        working = Path(tempfile.mkdtemp(prefix="formowl-issue20-malformed-preclosure-"))
        self.addCleanup(shutil.rmtree, working)
        packet_path = working / "external-evidence.json"
        pin_path = working / "operator-pin.json"
        preclosure_path = working / "preclosure.json"
        output_path = working / "transition.json"
        self._write_json(packet_path, self.packet)
        self._write_json(pin_path, self.operator_pin)
        self._write_json(preclosure_path, [])
        prior = b'{"prior":true}\n'
        output_path.write_bytes(prior)

        with patch.object(self.authority, "ROOT", root):
            self.assertEqual(
                self.authority.main(
                    [
                        "--issue20-finalization-action",
                        "build-completion-transition",
                        "--preclosure-manifest",
                        str(preclosure_path),
                        "--operator-attest-finalization",
                        "--external-evidence",
                        str(packet_path),
                        "--operator-cli-postgresql-authority-pin",
                        str(pin_path),
                        "--expected-local-harness-report-hash",
                        self.local_hash,
                        "--output",
                        str(output_path),
                    ]
                ),
                1,
            )
        self.assertEqual(output_path.read_bytes(), prior)

    def test_finalization_functions_are_manifest_onboarded(self) -> None:
        bindings = changed_scoped_function_bindings(
            ROOT,
            base_commit=ISSUE20_BASE_COMMIT,
            include_globs=ISSUE20_IMPLEMENTATION_CONTRACT_GLOBS,
        )
        manifest = load_function_harness_manifest()
        entries = {(entry["module"], entry["qualname"]): entry for entry in manifest["functions"]}
        expected_test = (
            "tests.test_issue20_completion_finalization."
            "Issue20CompletionFinalizationTests."
            "test_mutable_completion_state_does_not_invalidate_frozen_preclosure"
        )
        for key in (
            ("scripts.oauth_mcp_harness", "_repository_contract_file_hashes"),
            (
                "scripts.oauth_mcp_harness",
                "_issue20_expected_completion_document_texts",
            ),
            ("scripts.oauth_mcp_harness", "_issue20_completion_state_projection"),
            ("scripts.oauth_mcp_harness", "build_issue20_preclosure_manifest"),
            ("scripts.oauth_mcp_harness", "validate_issue20_preclosure_manifest"),
            ("scripts.oauth_mcp_harness", "build_issue20_completion_transition"),
            ("scripts.oauth_mcp_harness", "validate_issue20_completion_transition"),
        ):
            self.assertIn(key, bindings)
            self.assertIn(key, entries)
            self.assertEqual(entries[key]["status"], "onboarded")
            self.assertEqual(entries[key]["source_binding"], bindings[key])
            self.assertIn(expected_test, entries[key]["test_ids"])
        json.loads(
            (ROOT / "tests" / "issue20_function_harness_manifest.json").read_text(encoding="utf-8")
        )


if __name__ == "__main__":
    unittest.main()
