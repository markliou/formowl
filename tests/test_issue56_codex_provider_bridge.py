from __future__ import annotations

import copy
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib
from types import SimpleNamespace
import unittest
from unittest import mock

import _paths  # noqa: F401
import scripts.mail_human_uat_codex_engine as codex_engine
from formowl_contract import ContractValidationError
from formowl_mail.human_uat_orchestrator import (
    CodexAppServerConversationModel,
    CodexAppServerStdioTransport,
    CodexAppServerThread,
    CodexAppServerTurn,
    CodexDynamicToolInvocation,
    _CODEX_DISABLED_FEATURES,
    _assert_hardened_codex_runtime,
    build_hardened_codex_app_server_command,
    build_codex_runtime_environment,
    prepare_codex_runtime_state_for_custom_provider,
    prepare_codex_runtime_state_with_device_auth,
    validate_codex_runtime_state,
)


def _decision(
    *,
    citations: tuple[str, ...] = (),
    coverage_status: str = "not_applicable",
    coverage_note: str = "",
) -> str:
    return json.dumps(
        {
            "response_kind": "answer",
            "answer_text": "bounded answer",
            "display_format": "narrative",
            "citation_ids": list(citations),
            "coverage_status": coverage_status,
            "coverage_note": coverage_note,
        },
        separators=(",", ":"),
    )


class _RecordingTransport:
    def __init__(self, *, calls, final_message) -> None:
        self.calls = tuple(calls)
        self.final_message = final_message
        self.thread_start = None
        self.turn_call = None
        self.tool_outputs = []
        self.deleted_threads = []

    def start_thread(
        self,
        *,
        model,
        cwd,
        base_instructions,
        developer_instructions,
        dynamic_tools,
    ):
        self.thread_start = {
            "model": model,
            "cwd": cwd,
            "base_instructions": base_instructions,
            "developer_instructions": developer_instructions,
            "dynamic_tools": tuple(dynamic_tools),
        }
        return CodexAppServerThread(thread_id="thread-1", model_name=model)

    def run_turn(
        self,
        *,
        thread_id,
        user_text,
        additional_context,
        output_schema,
        reasoning_effort,
        client_metadata,
        tool_handler,
    ):
        self.turn_call = {
            "thread_id": thread_id,
            "user_text": user_text,
            "additional_context": additional_context,
            "output_schema": output_schema,
            "reasoning_effort": reasoning_effort,
            "client_metadata": client_metadata,
        }
        invocations = []
        for index, arguments in enumerate(self.calls):
            result = tool_handler("query_effective_graph_view", arguments)
            self.tool_outputs.append(result)
            invocations.append(
                CodexDynamicToolInvocation(
                    thread_id=thread_id,
                    turn_id="turn-1",
                    call_id=f"call-{index}",
                    tool_name="query_effective_graph_view",
                    arguments=arguments,
                    result=result,
                )
            )
        return CodexAppServerTurn(
            thread_id=thread_id,
            turn_id="turn-1",
            final_message=self.final_message,
            tool_invocations=tuple(invocations),
        )

    def delete_thread(self, thread_id):
        self.deleted_threads.append(thread_id)

    def close(self):
        return None


class Issue56CodexProviderBridgeTests(unittest.TestCase):
    def test_pinned_provider_allows_three_untrusted_queries_and_discloses_incomplete(
        self,
    ) -> None:
        transport = _RecordingTransport(
            calls=(
                {"query_text": "standalone query one"},
                {"query_text": "standalone query two"},
                {"query_text": "standalone query three"},
            ),
            final_message=_decision(
                citations=("citation-final",),
                coverage_status="incomplete",
                coverage_note="Authorized evidence coverage remains incomplete.",
            ),
        )
        returned = (
            {
                "status": "replan_required",
                "query_agent": {"external_replan": {"status": "required"}},
                "citations": [],
            },
            {"status": "partial", "citations": ["citation-middle"]},
            {
                "status": "partial",
                "exact_inventory": {
                    "coverage_status": "incomplete",
                    "items": [
                        {
                            "item_hash": "item-final",
                            "governed_references": [{"citation_hash": "citation-final"}],
                        }
                    ],
                },
            },
        )
        requests = []

        def query_tool(request):
            requests.append(request)
            return returned[len(requests) - 1]

        with tempfile.TemporaryDirectory() as workspace:
            provider = CodexAppServerConversationModel(
                transport,
                workspace_dir=workspace,
            )
            outcome = provider.respond(
                history=(),
                user_text="fragmentary request",
                latest_evidence=None,
                safety_identifier="diagnostic-session",
                evidence_tool=query_tool,
            )

        self.assertEqual(transport.thread_start["model"], "gpt-5.6-sol")
        tool = transport.thread_start["dynamic_tools"][0]
        self.assertEqual(tool["name"], "query_effective_graph_view")
        self.assertEqual(set(tool["inputSchema"]["properties"]), {"query_text"})
        self.assertIn("standalone rich", tool["description"])
        self.assertIn("three calls", tool["description"])
        self.assertIn("source_provided", tool["description"])
        self.assertIn("candidate_only", tool["description"])
        self.assertIn("untrusted evidence", tool["description"])
        self.assertEqual(transport.turn_call["reasoning_effort"], "ultra")
        self.assertEqual(
            [request.query_text for request in requests],
            [
                "standalone query one",
                "standalone query two",
                "standalone query three",
            ],
        )
        self.assertTrue(
            all(output["trust"] == "untrusted_evidence" for output in transport.tool_outputs)
        )
        self.assertEqual(outcome.model_name, "codex:gpt-5.6-sol")
        self.assertEqual(outcome.citation_ids, ("citation-final",))
        self.assertEqual(outcome.coverage_status, "incomplete")
        self.assertEqual(len(outcome.tool_requests), 3)

    def test_provider_rejects_fourth_call_or_uncited_incomplete_answer(self) -> None:
        cases = (
            (
                ({"query_text": f"query {index}"} for index in range(4)),
                _decision(),
                "too many UAT tools",
            ),
            (
                ({"query_text": "query"},),
                _decision(coverage_status="complete"),
                "omitted citations",
            ),
            (
                ({"query_text": "query"},),
                _decision(citations=("citation",), coverage_status="complete"),
                "hid incomplete coverage",
            ),
        )
        for calls, final_message, error in cases:
            with self.subTest(error=error), tempfile.TemporaryDirectory() as workspace:
                provider = CodexAppServerConversationModel(
                    _RecordingTransport(calls=tuple(calls), final_message=final_message),
                    workspace_dir=workspace,
                )
                with self.assertRaisesRegex(RuntimeError, error):
                    provider.respond(
                        history=(),
                        user_text="request",
                        latest_evidence=None,
                        safety_identifier=f"session-{error}",
                        evidence_tool=lambda request: {
                            "status": "partial",
                            "citations": ["citation"],
                        },
                    )

    def test_device_auth_is_provisioned_in_isolated_chatgpt_runtime(self) -> None:
        auth_cache = json.dumps(
            {
                "OPENAI_API_KEY": None,
                "auth_mode": "chatgpt",
                "tokens": {
                    "access_token": "synthetic-access",
                    "account_id": "synthetic-account",
                    "id_token": "synthetic-id",
                    "refresh_token": "synthetic-refresh",
                },
            }
        )

        def fake_login(*args, **kwargs):
            auth_path = Path(kwargs["env"]["CODEX_HOME"]) / "auth.json"
            auth_path.write_text(auth_cache, encoding="utf-8")
            auth_path.chmod(0o600)
            return subprocess.CompletedProcess(args[0], 0)

        with tempfile.TemporaryDirectory() as temporary_directory:
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "PATH": os.environ.get("PATH", ""),
                        "OPENAI_API_KEY": "must-not-propagate",
                    },
                    clear=True,
                ),
                mock.patch(
                    "formowl_mail.human_uat_orchestrator.subprocess.run",
                    side_effect=fake_login,
                ) as run,
            ):
                paths = prepare_codex_runtime_state_with_device_auth(
                    codex_command="codex",
                    state_dir=Path(temporary_directory) / "runtime",
                )
                validated = validate_codex_runtime_state(paths.state_dir)
                config = (paths.codex_home / "config.toml").read_text(encoding="utf-8")

                self.assertEqual(
                    run.call_args.args[0],
                    ["codex", "login", "--device-auth"],
                )
                environment = run.call_args.kwargs["env"]
                self.assertEqual(environment["HOME"], environment["CODEX_HOME"])
                self.assertNotIn("OPENAI_API_KEY", environment)
                self.assertEqual(paths.login_method, "chatgpt")
                self.assertEqual(validated, paths)
        self.assertIn('forced_login_method = "chatgpt"', config)
        self.assertEqual(config.count('SKILL.md"\nenabled = false'), 6)
        for skill_name in (
            "imagegen",
            "openai-docs",
            "plugin-creator",
            "review-agent",
            "skill-creator",
            "skill-installer",
        ):
            self.assertIn(f'/{skill_name}/SKILL.md"\nenabled = false', config)

    def test_app_server_command_disables_non_provider_capabilities(self) -> None:
        command = build_hardened_codex_app_server_command("codex")
        disabled = {
            command[index + 1] for index, value in enumerate(command[:-1]) if value == "--disable"
        }
        self.assertTrue(set(_CODEX_DISABLED_FEATURES).issubset(disabled))
        self.assertIn('sandbox_mode="read-only"', command)
        self.assertIn('web_search="disabled"', command)
        self.assertIn("mcp_servers={}", command)

    def test_custom_provider_runtime_is_secretless_and_hash_bound(self) -> None:
        base_url = "https://provider.example.test/v1"
        env_key = "FORMOWL_TEST_PROVIDER_API_KEY"
        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = prepare_codex_runtime_state_for_custom_provider(
                state_dir=Path(temporary_directory) / "runtime",
                base_url=base_url,
                env_key=env_key,
            )
            config_path = paths.codex_home / "config.toml"
            config_text = config_path.read_text(encoding="utf-8")
            config = tomllib.loads(config_text)
            marker = json.loads(
                (paths.state_dir / "formowl-uat-codex-runtime-v3.json").read_text(encoding="utf-8")
            )

            self.assertEqual(paths.login_method, "custom_provider")
            self.assertEqual(paths.provider_env_key, env_key)
            self.assertEqual(validate_codex_runtime_state(paths.state_dir), paths)
            self.assertFalse((paths.codex_home / "auth.json").exists())
            self.assertEqual(config["model"], "gpt-5.6-sol")
            self.assertEqual(config["model_provider"], "formowl_uat_custom")
            provider = config["model_providers"]["formowl_uat_custom"]
            self.assertEqual(provider["base_url"], base_url)
            self.assertEqual(provider["wire_api"], "responses")
            self.assertEqual(provider["env_key"], env_key)
            self.assertIs(provider["requires_openai_auth"], False)
            self.assertEqual(
                marker["config_sha256"],
                hashlib.sha256(config_text.encode("utf-8")).hexdigest(),
            )
            self.assertNotIn("auth.json", config_text)

            auth_path = paths.codex_home / "auth.json"
            auth_path.write_text('{"auth_mode":"chatgpt"}', encoding="utf-8")
            auth_path.chmod(0o600)
            with self.assertRaisesRegex(
                ContractValidationError,
                "runtime state integrity check failed",
            ):
                validate_codex_runtime_state(paths.state_dir)
            auth_path.unlink()

            config_path.chmod(0o600)
            config_path.write_text(config_text + "# tampered\n", encoding="utf-8")
            config_path.chmod(0o400)
            with self.assertRaisesRegex(
                ContractValidationError,
                "runtime state integrity check failed",
            ):
                validate_codex_runtime_state(paths.state_dir)

    def test_custom_provider_environment_and_attestation_are_exact(self) -> None:
        base_url = "https://provider.example.test/v1"
        env_key = "FORMOWL_TEST_PROVIDER_API_KEY"
        provider_secret = "synthetic-provider-secret"
        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = prepare_codex_runtime_state_for_custom_provider(
                state_dir=Path(temporary_directory) / "runtime",
                base_url=base_url,
                env_key=env_key,
            )
            source = {
                "PATH": os.environ.get("PATH", ""),
                env_key: provider_secret,
                "OTHER_API_KEY": "must-not-propagate",
                "OTHER_TOKEN": "must-not-propagate",
                "OTHER_SECRET": "must-not-propagate",
            }
            environment = build_codex_runtime_environment(
                paths.codex_home,
                source=source,
                provider_env_key=env_key,
            )
            self.assertEqual(environment[env_key], provider_secret)
            self.assertNotIn("OTHER_API_KEY", environment)
            self.assertNotIn("OTHER_TOKEN", environment)
            self.assertNotIn("OTHER_SECRET", environment)

            process = mock.MagicMock()
            process.stdin = mock.MagicMock()
            process.stdout = mock.MagicMock()
            process.stderr = None
            process.poll.return_value = 0
            with (
                mock.patch(
                    "formowl_mail.human_uat_orchestrator.subprocess.Popen",
                    return_value=process,
                ) as popen,
                mock.patch("formowl_mail.human_uat_orchestrator.threading.Thread"),
                mock.patch.object(
                    CodexAppServerStdioTransport,
                    "_request",
                    return_value={},
                ),
                mock.patch.object(CodexAppServerStdioTransport, "_send"),
            ):
                transport = CodexAppServerStdioTransport(
                    command=("codex", "app-server"),
                    cwd=paths.workspace,
                    codex_home=paths.codex_home,
                    environment=source,
                    provider_env_key=env_key,
                    attest_runtime=False,
                )
                transport.close()
            spawned_environment = popen.call_args.kwargs["env"]
            self.assertEqual(spawned_environment[env_key], provider_secret)
            self.assertNotIn("OTHER_API_KEY", spawned_environment)
            self.assertNotIn("OTHER_TOKEN", spawned_environment)
            self.assertNotIn("OTHER_SECRET", spawned_environment)

        config_response = {
            "config": {
                "model": "gpt-5.6-sol",
                "model_provider": "formowl_uat_custom",
                "forced_login_method": None,
                "cli_auth_credentials_store": "file",
                "approval_policy": "never",
                "sandbox_mode": "read-only",
                "web_search": "disabled",
                "mcp_servers": {},
                "analytics": {"enabled": False},
                "apps": {
                    "_default": {
                        "enabled": False,
                        "destructive_enabled": False,
                        "open_world_enabled": False,
                    }
                },
                "features": {name: False for name in _CODEX_DISABLED_FEATURES},
                "model_providers": {
                    "formowl_uat_custom": {
                        "name": "FormOwl UAT custom provider",
                        "base_url": base_url,
                        "wire_api": "responses",
                        "env_key": env_key,
                        "requires_openai_auth": False,
                    }
                },
            }
        }
        attestation = {
            "config_response": config_response,
            "mcp_response": {"data": [], "nextCursor": None},
            "skills_response": {
                "data": [
                    {
                        "cwd": "/tmp/formowl-codex-workspace",
                        "errors": [],
                        "skills": [],
                    }
                ]
            },
            "apps_response": {"data": [], "nextCursor": None},
            "runtime_workspace": Path("/tmp/formowl-codex-workspace"),
            "provider_base_url": base_url,
            "provider_env_key": env_key,
        }
        _assert_hardened_codex_runtime(**attestation)
        unsafe_values = (
            ("model", "other-model"),
            ("model_provider", "other-provider"),
        )
        for key, value in unsafe_values:
            with self.subTest(key=key):
                altered = copy.deepcopy(config_response)
                altered["config"][key] = value
                with self.assertRaisesRegex(RuntimeError, "unsafe configuration"):
                    _assert_hardened_codex_runtime(**(attestation | {"config_response": altered}))
        provider_values = (
            ("base_url", "https://other.example.test/v1"),
            ("wire_api", "chat"),
            ("env_key", "OTHER_API_KEY"),
            ("requires_openai_auth", True),
        )
        for key, value in provider_values:
            with self.subTest(key=key):
                altered = copy.deepcopy(config_response)
                altered["config"]["model_providers"]["formowl_uat_custom"][key] = value
                with self.assertRaisesRegex(RuntimeError, "unsafe configuration"):
                    _assert_hardened_codex_runtime(**(attestation | {"config_response": altered}))

    def test_cli_custom_provider_init_persists_metadata_not_secret(self) -> None:
        base_url = "https://provider.example.test/v1"
        env_key = "FORMOWL_TEST_PROVIDER_API_KEY"
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_dir = Path(temporary_directory) / "runtime"
            paths = SimpleNamespace(
                state_dir=state_dir,
                login_method="custom_provider",
            )
            standard_output = io.StringIO()
            arguments = [
                "mail_human_uat_codex_engine.py",
                "init",
                "--state-dir",
                str(state_dir),
                "--custom-provider",
                "--custom-provider-base-url",
                base_url,
                "--custom-provider-env-key",
                env_key,
            ]
            with (
                mock.patch.object(codex_engine.os, "geteuid", return_value=1000),
                mock.patch.object(codex_engine.sys, "argv", arguments),
                mock.patch.object(
                    codex_engine,
                    "prepare_codex_runtime_state_for_custom_provider",
                    return_value=paths,
                ) as prepare,
                redirect_stdout(standard_output),
            ):
                self.assertEqual(codex_engine.main(), 0)
            prepare.assert_called_once_with(
                state_dir=state_dir,
                base_url=base_url,
                env_key=env_key,
            )
            self.assertNotIn("secret", standard_output.getvalue())


if __name__ == "__main__":
    unittest.main()
