"""Synthetic requested-model policy checks; no provider or source access."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import tomllib
from types import SimpleNamespace
import unittest
from unittest import mock

import _paths  # noqa: F401
from formowl_contract import ContractValidationError
from formowl_mail import human_uat_orchestrator as owner
from scripts import issue56_uat_web as web


MODEL = "gpt-5.6-luna"
BASE_URL = "https://provider.example.test/v1"
ENV_KEY = "FORMOWL_TEST_PROVIDER_API_KEY"
DECISION = json.dumps({
    "response_kind": "answer", "answer_text": "hello", "display_format": "narrative",
    "citation_ids": [], "coverage_status": "not_applicable", "coverage_note": "",
})


class Issue56UatModelPolicyTests(unittest.TestCase):
    def _respond(self, model):
        evidence_tool = mock.Mock(side_effect=AssertionError("no evidence access"))
        outcome = model.respond(
            history=(), user_text="hello", latest_evidence=None,
            safety_identifier="synthetic-model-policy", evidence_tool=evidence_tool,
        )
        evidence_tool.assert_not_called()
        self.assertEqual(outcome.answer_text, "hello")

    def test_launcher_pins_both_transports_without_starting_services(self):
        for custom in (False, True):
            with self.subTest(custom_provider=custom):
                paths = SimpleNamespace(
                    workspace=Path("/tmp/synthetic-model-policy/workspace"),
                    codex_home=Path("/tmp/synthetic-model-policy/home"),
                    provider_env_key=ENV_KEY if custom else None,
                    provider_base_url=BASE_URL if custom else None,
                )
                argv = [
                    "issue56_uat_web.py", "--temporary-lan-diagnostic",
                    "--host", "127.0.0.1", "--port", "8099",
                    "--codex-runtime-state-dir", "/tmp/synthetic-model-policy/runtime",
                ]
                if custom:
                    argv += ["--codex-provider-api-key-file", "/tmp/synthetic-key"]
                with (
                    mock.patch.object(sys, "argv", argv),
                    mock.patch.object(web, "validate_codex_runtime_state", return_value=paths),
                    mock.patch.object(web, "CodexAppServerStdioTransport"),
                    mock.patch.object(web, "_read_codex_provider_api_key", return_value="synthetic"),
                    mock.patch.object(web, "create_issue56_temporary_lan_query_service") as service,
                    mock.patch.object(web, "create_mail_human_uat_http_server") as server,
                    redirect_stdout(io.StringIO()),
                ):
                    self.assertEqual(web.main(), 0)
                model = service.call_args.args[0]
                self.assertEqual(model._model, MODEL)
                self.assertEqual(model._reasoning_effort, "xhigh")
                if custom:
                    self.assertTrue(model._stream_initial_requests)
                server.return_value.serve_forever.assert_called_once_with()
                server.return_value.server_close.assert_called_once_with()

    def test_responses_request_default_and_explicit_historical_model(self):
        for explicit in (None, "gpt-5.5"):
            with self.subTest(explicit=explicit):
                model = owner.CodexResponsesConversationModel(
                    base_url=BASE_URL, api_key="synthetic",
                    **({"model": explicit} if explicit else {}),
                )
                with mock.patch.object(model, "_request_response", return_value={
                    "status": "completed", "output_text": DECISION,
                }) as request:
                    self._respond(model)
                request.assert_called_once()
                payload = request.call_args.args[0]
                self.assertEqual(payload["model"], explicit or MODEL)
                self.assertEqual(payload["reasoning"], {"effort": "xhigh"})
                self.assertIs(payload["store"], False)

    def test_app_server_thread_and_turn_default_and_explicit_historical_model(self):
        for explicit in (None, "gpt-5.5"):
            with self.subTest(explicit=explicit):
                transport = mock.Mock()
                transport.start_thread.return_value = owner.CodexAppServerThread(
                    thread_id="synthetic-thread", model_name=explicit or MODEL,
                )
                transport.run_turn.return_value = owner.CodexAppServerTurn(
                    thread_id="synthetic-thread", turn_id="synthetic-turn",
                    final_message=DECISION, tool_invocations=(),
                )
                model = owner.CodexAppServerConversationModel(
                    transport, workspace_dir="/tmp/synthetic-model-policy/workspace",
                    **({"model": explicit} if explicit else {}),
                )
                self.addCleanup(model.close)
                self._respond(model)
                transport.start_thread.assert_called_once()
                transport.run_turn.assert_called_once()
                self.assertEqual(transport.start_thread.call_args.kwargs["model"], explicit or MODEL)
                self.assertEqual(transport.run_turn.call_args.kwargs["reasoning_effort"], "xhigh")

    def _prepare(self, path):
        return owner.prepare_codex_runtime_state_for_custom_provider(
            state_dir=path, base_url=BASE_URL, env_key=ENV_KEY,
        )

    def test_fresh_runtime_pin_and_attestation_preserve_safety(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = self._prepare(Path(temporary) / "runtime")
            config = tomllib.loads((paths.codex_home / "config.toml").read_text())
            marker = json.loads((paths.state_dir / "formowl-uat-codex-runtime-v3.json").read_text())
            self.assertEqual(config["model"], MODEL)
            self.assertEqual(marker["model"], MODEL)
            self.assertEqual(owner.validate_codex_runtime_state(paths.state_dir), paths)
            self.assertFalse((paths.codex_home / "auth.json").exists())
            self.assertEqual(config["approval_policy"], "never")
            self.assertEqual(config["sandbox_mode"], "read-only")
            self.assertEqual(config["web_search"], "disabled")
            provider = config["model_providers"]["formowl_uat_custom"]
            self.assertEqual(provider["wire_api"], "responses")
            self.assertEqual(provider["env_key"], ENV_KEY)
            self.assertIs(provider["requires_openai_auth"], False)
            # Attestation reads effective CLI configuration, not only the TOML.
            command = owner.build_hardened_codex_app_server_command()
            config["features"] = {
                command[index + 1]: False
                for index, argument in enumerate(command) if argument == "--disable"
            }
            attestation = dict(
                config_response={"config": config}, mcp_response={"data": []},
                skills_response={"data": [{"cwd": str(paths.workspace), "errors": [], "skills": []}]},
                apps_response={"data": []}, runtime_workspace=paths.workspace,
                provider_base_url=BASE_URL, provider_env_key=ENV_KEY,
            )
            owner._assert_hardened_codex_runtime(**attestation)
            config["model"] = "gpt-5.5"
            with self.assertRaisesRegex(RuntimeError, "rejected unsafe configuration"):
                owner._assert_hardened_codex_runtime(**attestation)

    def test_old_policy_or_relocated_runtime_is_not_silently_resealed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with mock.patch.object(owner, "_DEFAULT_CODEX_MODEL", "gpt-5.5"):
                old = self._prepare(root / "old-runtime")
                self.assertEqual(owner.validate_codex_runtime_state(old.state_dir), old)
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            with self.assertRaisesRegex(ContractValidationError, "integrity check failed"):
                owner.validate_codex_runtime_state(old.state_dir)
            after = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            self.assertEqual(after, before)
            fresh = self._prepare(root / "new-final-runtime")
            self.assertEqual(owner.validate_codex_runtime_state(fresh.state_dir), fresh)
            relocated = root / "relocated-copy"
            shutil.copytree(fresh.state_dir, relocated)
            with self.assertRaisesRegex(ContractValidationError, "integrity check failed"):
                owner.validate_codex_runtime_state(relocated)

    def test_deployment_settings_agree_with_requested_policy(self):
        settings = owner.diagnostic_deployment_settings(
            host="127.0.0.1", port=8099, record_raw_uat_interactions=False,
            temporary_access_enabled=True, provider_base_url=BASE_URL,
        )
        self.assertEqual(settings["model"], MODEL)
        self.assertEqual(settings["reasoning_effort"], "xhigh")
        self.assertEqual(settings["provider_transport"], "codex_responses")


if __name__ == "__main__":
    unittest.main()
