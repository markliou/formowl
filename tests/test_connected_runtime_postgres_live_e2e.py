from __future__ import annotations

import asyncio
from collections.abc import Iterator, Mapping
from contextlib import ExitStack
import copy
import errno
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import _paths  # noqa: F401

from formowl_core import json_files as json_files_module
from formowl_evidence.issue20 import ISSUE20_IMPLEMENTATION_DEPLOY_CONTRACT_PATHS


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "connected_runtime_postgres_live_e2e.py"
HARNESS_PATH = ROOT / "scripts" / "oauth_mcp_harness.py"
RUNNER_PATH = ROOT / "scripts" / "issue20_containerized_evidence_runner.sh"
BOUNDARY_PATH = ROOT / "scripts" / "issue20_runner_boundary.py"
IMPLEMENTATION_CONTRACT_FIXTURE_PATHS = (
    "pyproject.toml",
    "compose.yaml",
    "containers/dev/Dockerfile",
    "containers/runtime/Dockerfile",
    *ISSUE20_IMPLEMENTATION_DEPLOY_CONTRACT_PATHS,
    "python/formowl_auth/contract.py",
    "python/formowl_contract/models.py",
    "python/formowl_evidence/issue20.py",
    "python/formowl_gateway/runtime.py",
    "python/formowl_graph/storage/postgres.py",
    "python/formowl_graph/storage/migrations/005_oauth_identity.sql",
    "python/formowl_ingestion/storage/records.py",
    "python/formowl_ingestion/uploads.py",
    "python/formowl_mail/__init__.py",
    "python/formowl_mail/upload_session.py",
    "scripts/connected_runtime_container_lifecycle_probe.py",
    "scripts/connected_runtime_postgres_live_e2e.py",
    "scripts/connected_operator_postgres_live_journey.py",
    "scripts/issue20_containerized_evidence_runner.sh",
    "scripts/issue20_runner_boundary.py",
    "scripts/oauth_mcp_harness.py",
    "tests/oauth_harness.py",
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_implementation_contract_fixture(root: Path) -> None:
    for relative_path in IMPLEMENTATION_CONTRACT_FIXTURE_PATHS:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"contract:{relative_path}\n", encoding="utf-8")


def _campaign_pin_payload(module, runner_image_id: str) -> dict[str, object]:
    return {
        "artifact_type": module._CAMPAIGN_PIN_ARTIFACT_TYPE,
        "boundary_sha256": f"sha256:{'1' * 64}",
        "dev_image_id": runner_image_id,
        "docker_authority": module._CAMPAIGN_DOCKER_AUTHORITY,
        "git_base_commit": "2" * 40,
        "git_head_commit": "3" * 40,
        "git_metadata_sha256": f"sha256:{'4' * 64}",
        "implementation_contract_hash": f"sha256:{'5' * 64}",
        "runner_sha256": f"sha256:{'6' * 64}",
        "sandboxed_untrusted_source": False,
        "source_snapshot_sha256": f"sha256:{'7' * 64}",
        "status": "frozen",
    }


def _write_campaign_pin(
    module,
    pin_path: Path,
    runner_image_id: str,
    *,
    payload: object | None = None,
) -> str:
    pin_path.parent.mkdir(parents=True, exist_ok=True)
    value = _campaign_pin_payload(module, runner_image_id) if payload is None else payload
    pin_bytes = (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    pin_path.write_bytes(pin_bytes)
    pin_path.chmod(0o400)
    return "sha256:" + hashlib.sha256(pin_bytes).hexdigest()


def _write_campaign_source(source_root: Path) -> None:
    for relative_path in (
        "scripts/connected_runtime_postgres_live_e2e.py",
        "scripts/issue20_containerized_evidence_runner.sh",
        "scripts/issue20_runner_boundary.py",
    ):
        path = source_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"frozen:{relative_path}\n", encoding="utf-8")


def _seal_campaign_source(
    module,
    source_root: Path,
    pin_path: Path,
    runner_image_id: str,
) -> str:
    boundary_module = _load_module(
        f"issue20_runner_boundary_for_{id(source_root)}",
        BOUNDARY_PATH,
    )
    payload = _campaign_pin_payload(module, runner_image_id)
    payload["source_snapshot_sha256"] = boundary_module.tree_sha256(
        source_root,
        expected_uid=os.getuid(),
    )
    return _write_campaign_pin(
        module,
        pin_path,
        runner_image_id,
        payload=payload,
    )


def _run_nested_campaign_exec(
    module,
    *,
    source_root: Path,
    pin_path: Path,
    pin_hash: str,
    runner_image_id: str,
    destination_parent: Path,
    target_path: Path,
    target_arguments: tuple[str, ...],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-c",
            module._NESTED_CAMPAIGN_EXEC_PROGRAM,
            str(source_root),
            str(pin_path),
            pin_hash,
            runner_image_id,
            str(destination_parent),
            str(target_path),
            *target_arguments,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


class ConnectedRuntimePostgresLiveE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        environment_patch = mock.patch.dict(os.environ)
        environment_patch.start()
        self.addCleanup(environment_patch.stop)
        os.environ.pop("FORMOWL_RUNNER_CAMPAIGN_PIN", None)
        os.environ.pop("FORMOWL_RUNNER_CAMPAIGN_PIN_SHA256", None)

    def test_load_inside_dependencies_rejects_protocol_version_mismatch_without_publication(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_protocol_version_mismatch",
            SCRIPT_PATH,
        )
        module_keys_before = set(vars(module))
        unpublished_dependencies = {
            "ConnectedRuntime",
            "ConnectedRuntimeConfig",
            "Fernet",
            "FileAuditLogStore",
            "FormOwlSigningKey",
            "FormOwlSigningKeySet",
            "OAuthBridgeConfig",
            "SQLStatement",
            "UploadSessionStore",
        }
        self.assertTrue(unpublished_dependencies.isdisjoint(module_keys_before))

        with (
            mock.patch(
                "mcp.shared.version.LATEST_PROTOCOL_VERSION",
                "synthetic-protocol-version-mismatch",
            ),
            self.assertRaises(RuntimeError) as raised,
        ):
            module._load_inside_dependencies()

        self.assertIs(type(raised.exception), RuntimeError)
        self.assertEqual(
            str(raised.exception),
            "live_e2e_protocol_version_mismatch",
        )
        self.assertIsNone(raised.exception.__cause__)
        self.assertEqual(set(vars(module)), module_keys_before)
        self.assertTrue(unpublished_dependencies.isdisjoint(vars(module)))

    def test_closable_rewriting_async_http_client_aclose_is_inert(self) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_closable_client_aclose",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()
        close_hook = mock.AsyncMock()
        delegate = SimpleNamespace(
            aclose=close_hook,
            request_history=[
                {
                    "method": "SYNTHETIC",
                    "path": "/unchanged",
                    "status": 299,
                }
            ],
            sentinel_state={"phase": "before", "items": ["unchanged"]},
        )
        client = object.__new__(module._ClosableRewritingAsyncHttpClient)
        client._client = delegate
        wrapper_state_before = dict(vars(client))
        delegate_keys_before = set(vars(delegate))
        delegate_state_before = copy.deepcopy(
            {key: value for key, value in vars(delegate).items() if key != "aclose"}
        )

        # Per-request transports own their lifecycle, so wrapper close is inert.
        with mock.patch("httpx.AsyncClient") as async_client:
            returned = asyncio.run(client.aclose())

        self.assertIsNone(returned)
        close_hook.assert_not_awaited()
        close_hook.assert_not_called()
        async_client.assert_not_called()
        self.assertEqual(vars(client), wrapper_state_before)
        self.assertEqual(set(vars(delegate)), delegate_keys_before)
        self.assertIs(delegate.aclose, close_hook)
        self.assertEqual(
            {key: value for key, value in vars(delegate).items() if key != "aclose"},
            delegate_state_before,
        )

    def test_closable_rewriting_async_http_client_init_copies_mapping_and_stays_inert(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_closable_client_init",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()
        url_rewrites = {
            "https://service.example.invalid": "http://127.0.0.1:1",
            "https://service.example.invalid/nested": "http://localhost:2",
        }
        expected_rewrites = dict(url_rewrites)

        # Construction must stay inert; network I/O begins only in get/post.
        with mock.patch("httpx.AsyncClient") as async_client:
            client = module._ClosableRewritingAsyncHttpClient(url_rewrites)

        delegate = client._client
        self.assertIsInstance(delegate, module.RewritingAsyncHttpClient)
        self.assertEqual(set(vars(client)), {"_client"})
        self.assertEqual(url_rewrites, expected_rewrites)
        self.assertIsNot(delegate._url_rewrites, url_rewrites)
        self.assertEqual(delegate._url_rewrites, expected_rewrites)
        self.assertEqual(delegate.request_history, [])
        async_client.assert_not_called()

        url_rewrites.clear()
        url_rewrites["https://later.example.invalid"] = "http://127.0.0.1:3"
        self.assertEqual(delegate._url_rewrites, expected_rewrites)

        delegate._url_rewrites["https://delegate.example.invalid"] = "http://127.0.0.1:4"
        self.assertEqual(
            url_rewrites,
            {"https://later.example.invalid": "http://127.0.0.1:3"},
        )

    def test_closable_rewriting_async_http_client_getattr_delegates_without_mutation(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_closable_client_getattr",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()
        client = module._ClosableRewritingAsyncHttpClient(
            {
                "https://service.example.invalid": "http://127.0.0.1:1",
            }
        )
        delegate = client._client
        delegate.request_history.append(
            {
                "method": "SYNTHETIC",
                "path": "/unchanged",
                "status": 299,
            }
        )
        wrapper_state_before = dict(vars(client))
        delegate_state_before = copy.deepcopy(vars(delegate))

        delegated_history = client.request_history

        self.assertIs(delegated_history, delegate.request_history)
        self.assertNotIn("request_history", vars(client))
        self.assertEqual(vars(client), wrapper_state_before)
        self.assertEqual(vars(delegate), delegate_state_before)

        with self.assertRaises(AttributeError):
            client.missing_synthetic_attribute

        self.assertEqual(vars(client), wrapper_state_before)
        self.assertEqual(vars(delegate), delegate_state_before)

    def test_closable_rewriting_async_http_client_get_forwards_once_without_mutation(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_closable_client_get",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()
        client = object.__new__(module._ClosableRewritingAsyncHttpClient)
        response = object()
        request_seam = mock.AsyncMock(return_value=response)
        sentinel_state = {"phase": "before", "items": ["unchanged"]}
        client._request = request_seam
        client.sentinel_state = sentinel_state
        wrapper_keys_before = set(vars(client))
        sentinel_state_before = copy.deepcopy(sentinel_state)
        url = "https://service.example.invalid/original/path?case=get"
        request_kwargs = {
            "headers": {"X-Synthetic-Request": "1"},
            "params": {"mode": "synthetic"},
            "timeout": 1.25,
            "follow_redirects": False,
        }
        request_kwargs_before = copy.deepcopy(request_kwargs)

        # Bind the seam directly so only get, not _request, earns trace credit.
        with mock.patch("httpx.AsyncClient") as async_client:
            returned = asyncio.run(client.get(url, **request_kwargs))

        self.assertIs(returned, response)
        request_seam.assert_awaited_once_with("GET", url, **request_kwargs)
        async_client.assert_not_called()
        self.assertEqual(set(vars(client)), wrapper_keys_before)
        self.assertIs(client._request, request_seam)
        self.assertEqual(client.sentinel_state, sentinel_state_before)
        self.assertEqual(request_kwargs, request_kwargs_before)

    def test_closable_rewriting_async_http_client_post_forwards_once_without_mutation(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_closable_client_post",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()
        client = object.__new__(module._ClosableRewritingAsyncHttpClient)
        response = object()
        request_seam = mock.AsyncMock(return_value=response)
        sentinel_state = {"phase": "before", "items": ["unchanged"]}
        client._request = request_seam
        client.sentinel_state = sentinel_state
        wrapper_keys_before = set(vars(client))
        sentinel_state_before = copy.deepcopy(sentinel_state)
        url = "https://service.example.invalid/original/path?case=post"
        request_kwargs = {
            "headers": {
                "Content-Type": "application/octet-stream",
                "X-Synthetic-Request": "1",
            },
            "content": b"synthetic-post-body",
            "timeout": 1.25,
            "follow_redirects": False,
        }
        request_kwargs_before = copy.deepcopy(request_kwargs)

        # Bind the seam directly so only post, not _request, earns trace credit.
        with mock.patch("httpx.AsyncClient") as async_client:
            returned = asyncio.run(client.post(url, **request_kwargs))

        self.assertIs(returned, response)
        request_seam.assert_awaited_once_with("POST", url, **request_kwargs)
        request_seam.assert_called_once_with("POST", url, **request_kwargs)
        async_client.assert_not_called()
        self.assertEqual(set(vars(client)), wrapper_keys_before)
        self.assertIs(client._request, request_seam)
        self.assertEqual(client.sentinel_state, sentinel_state_before)
        self.assertEqual(request_kwargs, request_kwargs_before)

    def test_closable_rewriting_async_http_client_request_failure_preserves_state(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_closable_client_request_failure",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()
        client = object.__new__(module._ClosableRewritingAsyncHttpClient)
        client._client = module.RewritingAsyncHttpClient(
            {
                "https://failure.example.invalid": "http://127.0.0.1:2",
            }
        )
        delegate = client._client
        delegate.request_history.append(
            {
                "method": "SYNTHETIC",
                "path": "/before",
                "status": 299,
            }
        )
        wrapper_state_before = dict(vars(client))
        delegate_state_before = copy.deepcopy(vars(delegate))
        transport_failure = RuntimeError("synthetic_transport_failure")
        transport = mock.AsyncMock()
        transport.request.side_effect = transport_failure
        context = mock.MagicMock()
        context.__aenter__ = mock.AsyncMock(return_value=transport)
        context.__aexit__ = mock.AsyncMock(return_value=None)
        request_kwargs = {
            "headers": {"X-Synthetic-Failure": "1"},
            "follow_redirects": False,
        }

        with (
            mock.patch("httpx.AsyncClient", return_value=context) as async_client,
            self.assertRaises(RuntimeError) as raised,
        ):
            asyncio.run(
                client._request(
                    "DELETE",
                    "https://failure.example.invalid/original?case=failure",
                    **request_kwargs,
                )
            )

        self.assertIs(raised.exception, transport_failure)
        async_client.assert_called_once_with(trust_env=False)
        context.__aenter__.assert_awaited_once_with()
        context.__aexit__.assert_awaited_once()
        transport.request.assert_awaited_once_with(
            "DELETE",
            "http://127.0.0.1:2/original?case=failure",
            **request_kwargs,
        )
        self.assertEqual(vars(client), wrapper_state_before)
        self.assertEqual(vars(delegate), delegate_state_before)

    def test_closable_rewriting_async_http_client_request_rewrites_and_records_success(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_closable_client_request_success",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()
        client = object.__new__(module._ClosableRewritingAsyncHttpClient)
        client._client = module.RewritingAsyncHttpClient(
            {
                "https://service.example.invalid": "http://127.0.0.1:1",
            }
        )
        delegate = client._client
        prior_history = {
            "method": "SYNTHETIC",
            "path": "/before",
            "status": 299,
        }
        delegate.request_history.append(prior_history)
        wrapper_state_before = dict(vars(client))
        rewrites_before = dict(delegate._url_rewrites)
        response = SimpleNamespace(status_code=207)
        transport = mock.AsyncMock()
        transport.request.return_value = response
        context = mock.MagicMock()
        context.__aenter__ = mock.AsyncMock(return_value=transport)
        context.__aexit__ = mock.AsyncMock(return_value=None)
        request_kwargs = {
            "headers": {"X-Synthetic-Request": "1"},
            "content": b"synthetic-body",
            "follow_redirects": False,
        }

        with mock.patch("httpx.AsyncClient", return_value=context) as async_client:
            returned = asyncio.run(
                client._request(
                    "PATCH",
                    "https://service.example.invalid/original/path?case=success",
                    **request_kwargs,
                )
            )

        self.assertIs(returned, response)
        async_client.assert_called_once_with(trust_env=False)
        context.__aenter__.assert_awaited_once_with()
        context.__aexit__.assert_awaited_once_with(None, None, None)
        transport.request.assert_awaited_once_with(
            "PATCH",
            "http://127.0.0.1:1/original/path?case=success",
            **request_kwargs,
        )
        self.assertEqual(vars(client), wrapper_state_before)
        self.assertEqual(delegate._url_rewrites, rewrites_before)
        self.assertEqual(
            delegate.request_history,
            [
                prior_history,
                {
                    "method": "PATCH",
                    "path": "/original/path",
                    "status": 207,
                },
            ],
        )

    def test_chatgpt_client_builds_exact_dependencies_without_mutation(self) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_chatgpt_client_dependencies",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()
        oauth = SimpleNamespace(
            issuer="https://issuer.example.invalid",
            chatgpt_client_id="synthetic-chatgpt-client-id",
            chatgpt_redirect_uri="https://chatgpt.example.invalid/oauth/callback",
            resource="https://resource.example.invalid/mcp",
        )
        fake_google = SimpleNamespace(
            authorization_endpoint="https://google.example.invalid/o/oauth2/v2/auth"
        )
        server_base_url = "http://127.0.0.1:31415"
        seed = "synthetic-chatgpt-client-seed"
        oauth_before = copy.deepcopy(vars(oauth))
        fake_google_before = copy.deepcopy(vars(fake_google))
        browser_sentinel = object()
        rng_sentinel = object()
        returned_client_sentinel = object()

        # Replace every dependency seam so only the helper itself earns trace credit.
        with (
            mock.patch.object(
                module,
                "HttpClient",
                return_value=browser_sentinel,
            ) as http_client,
            mock.patch.object(
                module,
                "DeterministicRng",
                return_value=rng_sentinel,
            ) as deterministic_rng,
            mock.patch.object(
                module,
                "SimulatedChatGptOAuthClient",
                return_value=returned_client_sentinel,
            ) as simulated_chatgpt_client,
        ):
            returned = module._chatgpt_client(
                oauth=oauth,
                server_base_url=server_base_url,
                fake_google=fake_google,
                seed=seed,
            )

        self.assertIs(returned, returned_client_sentinel)
        http_client.assert_called_once_with(
            {
                oauth.issuer: server_base_url,
                module.GOOGLE_AUTHORIZATION_ENDPOINT: fake_google.authorization_endpoint,
            }
        )
        deterministic_rng.assert_called_once_with(seed)
        simulated_chatgpt_client.assert_called_once_with(
            rng=rng_sentinel,
            client_id=oauth.chatgpt_client_id,
            redirect_uri=oauth.chatgpt_redirect_uri,
            resource=oauth.resource,
            http_client=browser_sentinel,
        )
        self.assertEqual(vars(oauth), oauth_before)
        self.assertEqual(vars(fake_google), fake_google_before)

    def test_complete_oauth_login_returns_exact_resource_bound_token_without_mutation(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_complete_oauth_login_success",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()
        oauth = SimpleNamespace(
            authorization_endpoint="https://authorization.example.invalid/authorize",
            token_endpoint="https://token.example.invalid/exchange",
            resource="https://resource.example.invalid/mcp",
        )
        authorization = {
            "state": "synthetic-state",
            "code_verifier": "synthetic-code-verifier",
        }
        callback = {
            "state": "synthetic-state",
            "code": "synthetic-authorization-code",
        }
        access_token = "synthetic-resource-bound-access-token"
        payload = {
            "access_token": access_token,
            "resource": oauth.resource,
        }
        authorization_url = "https://authorization.example.invalid/consent"
        oauth_before = copy.deepcopy(vars(oauth))
        authorization_before = copy.deepcopy(authorization)
        callback_before = copy.deepcopy(callback)
        payload_before = copy.deepcopy(payload)
        token_response = mock.Mock(status=200)
        token_response.json.return_value = payload
        chatgpt = mock.Mock()
        chatgpt.new_authorization.return_value = authorization
        chatgpt.authorization_url.return_value = authorization_url
        chatgpt.complete_browser_redirects.return_value = callback
        chatgpt.exchange_code.return_value = token_response

        returned = module._complete_oauth_login(chatgpt, oauth)

        self.assertIs(returned, access_token)
        self.assertEqual(
            chatgpt.method_calls,
            [
                mock.call.new_authorization(),
                mock.call.authorization_url(
                    oauth.authorization_endpoint,
                    authorization,
                ),
                mock.call.complete_browser_redirects(authorization_url),
                mock.call.exchange_code(
                    oauth.token_endpoint,
                    code=callback["code"],
                    verifier=authorization["code_verifier"],
                ),
            ],
        )
        token_response.json.assert_called_once_with()
        self.assertEqual(vars(oauth), oauth_before)
        self.assertEqual(authorization, authorization_before)
        self.assertEqual(callback, callback_before)
        self.assertEqual(payload, payload_before)

    def test_complete_oauth_login_fails_closed_for_callback_and_token_response_errors(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_complete_oauth_login_failures",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()
        state = "synthetic-state"
        code = "synthetic-authorization-code"
        verifier = "synthetic-code-verifier"
        access_token = "synthetic-resource-bound-access-token"
        resource = "https://resource.example.invalid/mcp"
        authorization_url = "https://authorization.example.invalid/consent"
        sensitive_marker = "synthetic-sensitive-response-marker"
        cases = (
            {
                "name": "mismatched_callback_state",
                "callback": {"state": "synthetic-other-state", "code": code},
                "status": 200,
                "payload": {"access_token": access_token, "resource": resource},
                "json_raises": False,
                "expected_error": "live_e2e_oauth_callback_invalid",
                "expects_exchange": False,
                "expects_json": False,
            },
            {
                "name": "missing_callback_code",
                "callback": {"state": state},
                "status": 200,
                "payload": {"access_token": access_token, "resource": resource},
                "json_raises": False,
                "expected_error": "live_e2e_oauth_callback_invalid",
                "expects_exchange": False,
                "expects_json": False,
            },
            {
                "name": "non_200_token_status",
                "callback": {"state": state, "code": code},
                "status": 503,
                "payload": {"access_token": access_token, "resource": resource},
                "json_raises": False,
                "expected_error": "live_e2e_token_exchange_failed",
                "expects_exchange": True,
                "expects_json": False,
            },
            {
                "name": "token_json_value_error",
                "callback": {"state": state, "code": code},
                "status": 200,
                "payload": {"access_token": access_token, "resource": resource},
                "json_raises": True,
                "expected_error": "live_e2e_token_exchange_failed",
                "expects_exchange": True,
                "expects_json": True,
            },
            {
                "name": "token_json_unicode_error",
                "callback": {"state": state, "code": code},
                "status": 200,
                "payload": {"access_token": access_token, "resource": resource},
                "json_raises": True,
                "json_error": "unicode",
                "expected_error": "live_e2e_token_exchange_failed",
                "expects_exchange": True,
                "expects_json": True,
            },
            {
                "name": "non_mapping_token_payload",
                "callback": {"state": state, "code": code},
                "status": 200,
                "payload": [],
                "json_raises": False,
                "expected_error": "live_e2e_token_exchange_failed",
                "expects_exchange": True,
                "expects_json": True,
            },
            {
                "name": "missing_access_token",
                "callback": {"state": state, "code": code},
                "status": 200,
                "payload": {"resource": resource},
                "json_raises": False,
                "expected_error": "live_e2e_access_token_invalid",
                "expects_exchange": True,
                "expects_json": True,
            },
            {
                "name": "empty_access_token",
                "callback": {"state": state, "code": code},
                "status": 200,
                "payload": {"access_token": "", "resource": resource},
                "json_raises": False,
                "expected_error": "live_e2e_access_token_invalid",
                "expects_exchange": True,
                "expects_json": True,
            },
            {
                "name": "wrong_type_access_token",
                "callback": {"state": state, "code": code},
                "status": 200,
                "payload": {"access_token": 31415, "resource": resource},
                "json_raises": False,
                "expected_error": "live_e2e_access_token_invalid",
                "expects_exchange": True,
                "expects_json": True,
            },
            {
                "name": "resource_mismatch",
                "callback": {"state": state, "code": code},
                "status": 200,
                "payload": {
                    "access_token": access_token,
                    "resource": "https://other-resource.example.invalid/mcp",
                },
                "json_raises": False,
                "expected_error": "live_e2e_access_token_invalid",
                "expects_exchange": True,
                "expects_json": True,
            },
        )

        for case in cases:
            with self.subTest(case=case["name"]):
                oauth = SimpleNamespace(
                    authorization_endpoint=("https://authorization.example.invalid/authorize"),
                    token_endpoint="https://token.example.invalid/exchange",
                    resource=resource,
                )
                authorization = {
                    "state": state,
                    "code_verifier": verifier,
                }
                callback = copy.deepcopy(case["callback"])
                payload = copy.deepcopy(case["payload"])
                oauth_before = copy.deepcopy(vars(oauth))
                authorization_before = copy.deepcopy(authorization)
                callback_before = copy.deepcopy(callback)
                payload_before = copy.deepcopy(payload)
                token_response = mock.Mock(status=case["status"])
                if case.get("json_error") == "unicode":
                    token_response.json.side_effect = UnicodeError(sensitive_marker)
                elif case["json_raises"]:
                    token_response.json.side_effect = ValueError(sensitive_marker)
                else:
                    token_response.json.return_value = payload
                chatgpt = mock.Mock()
                chatgpt.new_authorization.return_value = authorization
                chatgpt.authorization_url.return_value = authorization_url
                chatgpt.complete_browser_redirects.return_value = callback
                chatgpt.exchange_code.return_value = token_response

                with self.assertRaises(RuntimeError) as raised:
                    module._complete_oauth_login(chatgpt, oauth)

                self.assertEqual(str(raised.exception), case["expected_error"])
                self.assertNotIn(sensitive_marker, str(raised.exception))
                if case["json_raises"]:
                    self.assertIsNone(raised.exception.__cause__)
                    self.assertTrue(raised.exception.__suppress_context__)
                    self.assertIs(
                        raised.exception.__context__,
                        token_response.json.side_effect,
                    )
                expected_method_calls = [
                    mock.call.new_authorization(),
                    mock.call.authorization_url(
                        oauth.authorization_endpoint,
                        authorization,
                    ),
                    mock.call.complete_browser_redirects(authorization_url),
                ]
                if case["expects_exchange"]:
                    expected_method_calls.append(
                        mock.call.exchange_code(
                            oauth.token_endpoint,
                            code=code,
                            verifier=verifier,
                        )
                    )
                    chatgpt.exchange_code.assert_called_once_with(
                        oauth.token_endpoint,
                        code=code,
                        verifier=verifier,
                    )
                else:
                    chatgpt.exchange_code.assert_not_called()
                self.assertEqual(chatgpt.method_calls, expected_method_calls)
                if case["expects_json"]:
                    token_response.json.assert_called_once_with()
                else:
                    token_response.json.assert_not_called()
                self.assertEqual(vars(oauth), oauth_before)
                self.assertEqual(authorization, authorization_before)
                self.assertEqual(callback, callback_before)
                self.assertEqual(payload, payload_before)

    def test_jwks_summary_rejects_failed_status_and_malformed_shapes(self) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_jwks_failures",
            SCRIPT_PATH,
        )
        valid_key = {"kid": "kid-current", "kty": "RSA"}
        cases = (
            {
                "name": "failed_status",
                "status": 503,
                "payload": {"keys": [valid_key]},
                "expected_error": "live_e2e_jwks_request_failed",
                "expects_json": False,
            },
            {
                "name": "non_mapping_payload",
                "status": 200,
                "payload": [],
                "expected_error": "live_e2e_jwks_shape_invalid",
                "expects_json": True,
            },
            {
                "name": "missing_keys",
                "status": 200,
                "payload": {},
                "expected_error": "live_e2e_jwks_shape_invalid",
                "expects_json": True,
            },
            {
                "name": "empty_keys",
                "status": 200,
                "payload": {"keys": []},
                "expected_error": "live_e2e_jwks_shape_invalid",
                "expects_json": True,
            },
            {
                "name": "non_list_keys",
                "status": 200,
                "payload": {"keys": {}},
                "expected_error": "live_e2e_jwks_shape_invalid",
                "expects_json": True,
            },
            {
                "name": "non_mapping_key",
                "status": 200,
                "payload": {"keys": ["not-a-jwk"]},
                "expected_error": "live_e2e_jwks_shape_invalid",
                "expects_json": True,
            },
            {
                "name": "missing_kid",
                "status": 200,
                "payload": {"keys": [{"kty": "RSA"}]},
                "expected_error": "live_e2e_jwks_shape_invalid",
                "expects_json": True,
            },
            {
                "name": "empty_kid",
                "status": 200,
                "payload": {"keys": [{"kid": "", "kty": "RSA"}]},
                "expected_error": "live_e2e_jwks_shape_invalid",
                "expects_json": True,
            },
            {
                "name": "non_string_kid",
                "status": 200,
                "payload": {"keys": [{"kid": 1, "kty": "RSA"}]},
                "expected_error": "live_e2e_jwks_shape_invalid",
                "expects_json": True,
            },
        )

        for case in cases:
            with self.subTest(case=case["name"]):
                payload = case["payload"]
                payload_before = copy.deepcopy(payload)
                json_result = mock.Mock(return_value=payload)
                response = SimpleNamespace(status=case["status"], json=json_result)

                with self.assertRaises(RuntimeError) as raised:
                    module._jwks_summary(response)

                self.assertIs(type(raised.exception), RuntimeError)
                self.assertEqual(str(raised.exception), case["expected_error"])
                self.assertIsNone(raised.exception.__cause__)
                if case["expects_json"]:
                    json_result.assert_called_once_with()
                else:
                    json_result.assert_not_called()
                self.assertEqual(payload, payload_before)

    def test_jwks_summary_reports_only_safe_shape_and_private_count_without_material(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_jwks_safe_summary",
            SCRIPT_PATH,
        )
        private_material = "synthetic-private-jwk-material"
        payload = {
            "keys": [
                {
                    "d": private_material,
                    "e": "AQAB",
                    "kid": "kid-current",
                    "kty": "RSA",
                    "n": "synthetic-public-modulus",
                }
            ]
        }
        payload_before = copy.deepcopy(payload)
        json_result = mock.Mock(return_value=payload)
        response = SimpleNamespace(status=200, json=json_result)

        returned = module._jwks_summary(response)

        self.assertEqual(
            returned,
            {
                "key_count": 1,
                "kids": ["kid-current"],
                "private_key_exposure_count": 1,
                "shape": {
                    "keys": {
                        "type": "list",
                        "length": 1,
                        "items": [
                            {
                                "d": "string",
                                "e": "string",
                                "kid": "string",
                                "kty": "string",
                                "n": "string",
                            }
                        ],
                    }
                },
            },
        )
        rendered = json.dumps(returned, sort_keys=True)
        self.assertNotIn(private_material, rendered)
        self.assertNotIn("synthetic-public-modulus", rendered)
        self.assertEqual(payload, payload_before)
        json_result.assert_called_once_with()

    def test_listed_tool_names_rejects_malformed_protocol_shapes(self) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_listed_tool_names_failures",
            SCRIPT_PATH,
        )
        cases = (
            ("missing_tools_payload", {}),
            ("null_tools_payload", {"tools": None}),
            ("list_tools_payload", {"tools": []}),
            ("missing_nested_tools", {"tools": {}}),
            ("non_list_nested_tools", {"tools": {"tools": {}}}),
        )

        for name, sequence in cases:
            with self.subTest(case=name):
                sequence_before = copy.deepcopy(sequence)

                with self.assertRaises(RuntimeError) as raised:
                    module._listed_tool_names(sequence)

                self.assertIs(type(raised.exception), RuntimeError)
                self.assertEqual(
                    str(raised.exception),
                    "live_e2e_tool_list_invalid",
                )
                self.assertIsNone(raised.exception.__cause__)
                self.assertEqual(sequence, sequence_before)

    def test_invalid_token_challenge_formats_exact_caller_metadata_without_leak(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_invalid_token_challenge",
            SCRIPT_PATH,
        )
        metadata_url = "https://resource.example.invalid/.well-known/oauth-protected-resource"
        metadata_url_before = copy.deepcopy(metadata_url)

        challenge = module._invalid_token_challenge(metadata_url)

        self.assertIs(type(challenge), str)
        self.assertEqual(
            challenge,
            (
                'Bearer resource_metadata="'
                "https://resource.example.invalid/.well-known/"
                'oauth-protected-resource", error="invalid_token", '
                'error_description="Authentication required."'
            ),
        )
        self.assertEqual(metadata_url, metadata_url_before)
        self.assertNotIn("postgresql://", challenge)
        self.assertNotIn("/workspace/", challenge)
        self.assertNotIn("person@example.com", challenge)
        self.assertNotIn("secret-value", challenge)

    def test_assert_bearer_denied_rejects_wrong_status_challenge_and_exact_body(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_bearer_denial_failures",
            SCRIPT_PATH,
        )
        metadata_url = "https://resource.example.invalid/.well-known/oauth-protected-resource"
        exact_challenge = module._invalid_token_challenge(metadata_url)
        cases = (
            {
                "name": "wrong_status",
                "status": 403,
                "headers": {"www-authenticate": exact_challenge},
                "body": {"error": "invalid_token"},
            },
            {
                "name": "missing_challenge",
                "status": 401,
                "headers": {},
                "body": {"error": "invalid_token"},
            },
            {
                "name": "wrong_challenge",
                "status": 401,
                "headers": {
                    "www-authenticate": (
                        'Bearer error="invalid_token", '
                        'error_description="Authentication required."'
                    )
                },
                "body": {"error": "invalid_token"},
            },
            {
                "name": "wrong_exact_body",
                "status": 401,
                "headers": {"www-authenticate": exact_challenge},
                "body": {"error": "invalid_token", "detail": "unsupported"},
            },
        )

        for case in cases:
            with self.subTest(case=case["name"]):
                headers = copy.deepcopy(case["headers"])
                body = copy.deepcopy(case["body"])
                headers_before = copy.deepcopy(headers)
                body_before = copy.deepcopy(body)
                json_result = mock.Mock(return_value=body)
                response = SimpleNamespace(
                    status=case["status"],
                    headers=headers,
                    json=json_result,
                )

                with self.assertRaises(RuntimeError) as raised:
                    module._assert_bearer_denied(
                        response,
                        expected_metadata_url=metadata_url,
                    )

                self.assertIs(type(raised.exception), RuntimeError)
                self.assertEqual(
                    str(raised.exception),
                    "live_e2e_bearer_denial_failed",
                )
                self.assertIsNone(raised.exception.__cause__)
                json_result.assert_called_once_with()
                self.assertEqual(headers, headers_before)
                self.assertEqual(body, body_before)

    def test_tool_call_result_rejects_malformed_missing_and_failed_results(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_tool_call_result_failures",
            SCRIPT_PATH,
        )
        cases = (
            {
                "name": "calls_not_list",
                "sequence": {"calls": {}},
                "occurrence": 0,
                "expected_error": "live_e2e_mcp_calls_invalid",
            },
            {
                "name": "missing_call",
                "sequence": {"calls": [{"name": "other", "result": {}}]},
                "occurrence": 0,
                "expected_error": "live_e2e_mcp_call_missing",
            },
            {
                "name": "negative_occurrence",
                "sequence": {"calls": [{"name": "whoami", "result": {}}]},
                "occurrence": -1,
                "expected_error": "live_e2e_mcp_call_missing",
            },
            {
                "name": "occurrence_out_of_range",
                "sequence": {"calls": [{"name": "whoami", "result": {}}]},
                "occurrence": 1,
                "expected_error": "live_e2e_mcp_call_missing",
            },
            {
                "name": "result_not_dict",
                "sequence": {"calls": [{"name": "whoami", "result": []}]},
                "occurrence": 0,
                "expected_error": "live_e2e_mcp_call_failed",
            },
        )

        for case in cases:
            with self.subTest(case=case["name"]):
                sequence = copy.deepcopy(case["sequence"])
                sequence_before = copy.deepcopy(sequence)

                with self.assertRaises(RuntimeError) as raised:
                    module._tool_call_result(
                        sequence,
                        "whoami",
                        occurrence=case["occurrence"],
                    )

                self.assertIs(type(raised.exception), RuntimeError)
                self.assertEqual(str(raised.exception), case["expected_error"])
                self.assertIsNone(raised.exception.__cause__)
                self.assertEqual(sequence, sequence_before)

    def test_structured_call_rejects_error_and_malformed_payloads(self) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_structured_call_failures",
            SCRIPT_PATH,
        )
        cases = (
            {
                "name": "error_result",
                "result": {"isError": True, "structuredContent": {}},
                "expected_error": "live_e2e_mcp_call_failed",
            },
            {
                "name": "missing_structured_content",
                "result": {"isError": False},
                "expected_error": "live_e2e_mcp_payload_invalid",
            },
            {
                "name": "null_structured_content",
                "result": {"isError": False, "structuredContent": None},
                "expected_error": "live_e2e_mcp_payload_invalid",
            },
            {
                "name": "non_dict_structured_content",
                "result": {"isError": False, "structuredContent": []},
                "expected_error": "live_e2e_mcp_payload_invalid",
            },
        )

        for case in cases:
            with self.subTest(case=case["name"]):
                sequence = {
                    "calls": [
                        {
                            "name": "whoami",
                            "result": copy.deepcopy(case["result"]),
                        }
                    ]
                }
                sequence_before = copy.deepcopy(sequence)

                with self.assertRaises(RuntimeError) as raised:
                    module._structured_call(sequence, "whoami")

                self.assertIs(type(raised.exception), RuntimeError)
                self.assertEqual(str(raised.exception), case["expected_error"])
                self.assertIsNone(raised.exception.__cause__)
                self.assertEqual(sequence, sequence_before)

    def test_tool_call_is_error_propagates_delegated_protocol_validation(self) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_tool_call_is_error_failures",
            SCRIPT_PATH,
        )
        cases = (
            {
                "name": "calls_not_list",
                "sequence": {"calls": None},
                "expected_error": "live_e2e_mcp_calls_invalid",
            },
            {
                "name": "missing_call",
                "sequence": {"calls": []},
                "expected_error": "live_e2e_mcp_call_missing",
            },
            {
                "name": "failed_result",
                "sequence": {"calls": [{"name": "whoami", "result": None}]},
                "expected_error": "live_e2e_mcp_call_failed",
            },
        )

        for case in cases:
            with self.subTest(case=case["name"]):
                sequence = copy.deepcopy(case["sequence"])
                sequence_before = copy.deepcopy(sequence)

                with self.assertRaises(RuntimeError) as raised:
                    module._tool_call_is_error(
                        sequence,
                        "whoami",
                        occurrence=0,
                    )

                self.assertIs(type(raised.exception), RuntimeError)
                self.assertEqual(str(raised.exception), case["expected_error"])
                self.assertIsNone(raised.exception.__cause__)
                self.assertEqual(sequence, sequence_before)

        error_sequence = {"calls": [{"name": "whoami", "result": {"isError": True}}]}
        error_sequence_before = copy.deepcopy(error_sequence)
        self.assertIs(
            module._tool_call_is_error(
                error_sequence,
                "whoami",
                occurrence=0,
            ),
            True,
        )
        self.assertEqual(error_sequence, error_sequence_before)

    def test_jwt_kid_returns_exact_builtin_key_id_without_mutation(self) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_jwt_kid_success",
            SCRIPT_PATH,
        )
        header = b'{"alg":"RS256","kid":"kid-current","typ":"JWT"}'
        encoded_header = module.base64.urlsafe_b64encode(header).rstrip(b"=").decode("ascii")
        raw_token = f"{encoded_header}.payload.signature"
        raw_token_before = raw_token

        returned = module._jwt_kid(raw_token)

        self.assertIs(type(raw_token), str)
        self.assertIs(type(returned), str)
        self.assertEqual(returned, "kid-current")
        self.assertTrue(returned)
        self.assertEqual(raw_token, raw_token_before)

    def test_jwt_kid_rejects_non_string_split_probes_without_hooks_or_mutation(
        self,
    ) -> None:
        import traceback

        module = _load_module(
            "connected_runtime_postgres_live_e2e_jwt_kid_type_guards",
            SCRIPT_PATH,
        )
        sensitive_marker = "synthetic-sensitive-jwt-kid-split-marker"

        class NonStringSplitProbe:
            def __init__(self) -> None:
                self.split_call_count = 0
                self.sentinel_state = {"phase": "before", "items": ["unchanged"]}

            def split(self, *_: object, **__: object) -> list[str]:
                self.split_call_count += 1
                raise AssertionError(sensitive_marker)

        class StringSubclassSplitProbe(str):
            def __new__(cls, value: str):
                instance = super().__new__(cls, value)
                instance.split_call_count = 0
                instance.sentinel_state = {
                    "phase": "before",
                    "items": ["unchanged"],
                }
                return instance

            def split(self, *_: object, **__: object) -> list[str]:
                self.split_call_count += 1
                raise AssertionError(sensitive_marker)

        probes = (
            ("non_string", NonStringSplitProbe()),
            (
                "string_subclass",
                StringSubclassSplitProbe("header.payload.signature"),
            ),
        )
        for name, probe in probes:
            with self.subTest(case=name):
                probe_state = probe.sentinel_state
                probe_before = copy.deepcopy(vars(probe))

                with self.assertRaises(RuntimeError) as raised:
                    module._jwt_kid(probe)

                rendered = "".join(
                    traceback.format_exception(
                        type(raised.exception),
                        raised.exception,
                        raised.exception.__traceback__,
                    )
                )
                self.assertIs(type(raised.exception), RuntimeError)
                self.assertEqual(
                    str(raised.exception),
                    "live_e2e_token_header_invalid",
                )
                self.assertIsNone(raised.exception.__cause__)
                self.assertTrue(raised.exception.__suppress_context__)
                self.assertNotIn(sensitive_marker, str(raised.exception))
                self.assertNotIn(sensitive_marker, rendered)
                self.assertEqual(probe.split_call_count, 0)
                self.assertEqual(vars(probe), probe_before)
                self.assertIs(probe.sentinel_state, probe_state)

    def test_jwt_kid_rejects_malformed_headers_with_one_suppressed_error(
        self,
    ) -> None:
        import traceback

        module = _load_module(
            "connected_runtime_postgres_live_e2e_jwt_kid_failures",
            SCRIPT_PATH,
        )
        sensitive_marker = "synthetic-sensitive-jwt-kid-marker"

        def encode_header(header: bytes) -> str:
            return module.base64.urlsafe_b64encode(header).rstrip(b"=").decode("ascii")

        def token(header_segment: str) -> str:
            return f"{header_segment}.payload.signature"

        valid_header = encode_header(b'{"kid":"kid-current"}')
        padded_header_source = b'{"kid":"kid-current","x":""}'
        noncanonical_header = encode_header(padded_header_source)
        self.assertTrue(noncanonical_header.endswith("Q"))
        noncanonical_header = f"{noncanonical_header[:-1]}R"
        noncanonical_padding = "=" * (-len(noncanonical_header) % 4)
        self.assertEqual(
            module.base64.urlsafe_b64decode(
                (noncanonical_header + noncanonical_padding).encode("ascii")
            ),
            padded_header_source,
        )

        class HeaderDictSubclass(dict):
            def __init__(self) -> None:
                super().__init__(kid="kid-current")
                self.get_call_count = 0
                self.sentinel_state = {
                    "phase": "before",
                    "items": ["unchanged"],
                }

            def get(self, *_: object, **__: object) -> str:
                self.get_call_count += 1
                raise AssertionError(sensitive_marker)

        class KidStringSubclass(str):
            def __new__(cls, value: str):
                instance = super().__new__(cls, value)
                instance.bool_call_count = 0
                instance.sentinel_state = {
                    "phase": "before",
                    "items": ["unchanged"],
                }
                return instance

            def __bool__(self) -> bool:
                self.bool_call_count += 1
                raise AssertionError(sensitive_marker)

        header_dict_subclass = HeaderDictSubclass()
        kid_string_subclass = KidStringSubclass("kid-current")
        exact_dict_with_kid_subclass = {"kid": kid_string_subclass}
        cases = (
            {"name": "one_segment", "raw_token": valid_header},
            {
                "name": "two_segments",
                "raw_token": f"{valid_header}.payload",
            },
            {
                "name": "four_segments",
                "raw_token": f"{valid_header}.payload.signature.extra",
            },
            {"name": "empty_header", "raw_token": ".payload.signature"},
            {
                "name": "empty_payload",
                "raw_token": f"{valid_header}..signature",
            },
            {
                "name": "empty_signature",
                "raw_token": f"{valid_header}.payload.",
            },
            {
                "name": "padded_header",
                "raw_token": token(f"{valid_header}="),
            },
            {
                "name": "illegal_base64url_header",
                "raw_token": token(f"{valid_header[:3]}*{valid_header[3:]}"),
            },
            {
                "name": "non_ascii_header",
                "raw_token": token("é"),
            },
            {
                "name": "noncanonical_base64url_header",
                "raw_token": token(noncanonical_header),
            },
            {
                "name": "invalid_utf8_header",
                "raw_token": token(encode_header(b"\xff")),
            },
            {
                "name": "invalid_json_header",
                "raw_token": token(encode_header(b"{")),
            },
            {
                "name": "non_object_json_header",
                "raw_token": token(encode_header(b"[]")),
            },
            {
                "name": "missing_kid",
                "raw_token": token(encode_header(b"{}")),
            },
            {
                "name": "empty_kid",
                "raw_token": token(encode_header(b'{"kid":""}')),
            },
            {
                "name": "wrong_type_kid",
                "raw_token": token(encode_header(b'{"kid":1}')),
            },
            {
                "name": "dict_subclass_header",
                "raw_token": token(valid_header),
                "json_result": header_dict_subclass,
            },
            {
                "name": "string_subclass_kid",
                "raw_token": token(valid_header),
                "json_result": exact_dict_with_kid_subclass,
            },
        )

        for case in cases:
            with self.subTest(case=case["name"]):
                raw_token = case["raw_token"]
                raw_token_before = raw_token
                json_result = case.get("json_result")
                json_result_before = copy.deepcopy(json_result)
                json_result_state = (
                    json_result.sentinel_state
                    if isinstance(json_result, HeaderDictSubclass)
                    else None
                )
                json_result_attrs_before = (
                    copy.deepcopy(vars(json_result))
                    if isinstance(json_result, HeaderDictSubclass)
                    else None
                )
                kid_state = (
                    kid_string_subclass.sentinel_state
                    if json_result is exact_dict_with_kid_subclass
                    else None
                )
                kid_attrs_before = (
                    copy.deepcopy(vars(kid_string_subclass))
                    if json_result is exact_dict_with_kid_subclass
                    else None
                )
                json_loads = None
                with ExitStack() as stack:
                    if json_result is not None:
                        json_loads = stack.enter_context(
                            mock.patch.object(
                                module.json,
                                "loads",
                                return_value=json_result,
                            )
                        )

                    with self.assertRaises(RuntimeError) as raised:
                        module._jwt_kid(raw_token)

                rendered = "".join(
                    traceback.format_exception(
                        type(raised.exception),
                        raised.exception,
                        raised.exception.__traceback__,
                    )
                )
                self.assertIs(type(raised.exception), RuntimeError)
                self.assertEqual(
                    str(raised.exception),
                    "live_e2e_token_header_invalid",
                )
                self.assertIsNone(raised.exception.__cause__)
                self.assertTrue(raised.exception.__suppress_context__)
                self.assertNotIn(sensitive_marker, str(raised.exception))
                self.assertNotIn(sensitive_marker, rendered)
                self.assertEqual(raw_token, raw_token_before)
                self.assertEqual(json_result, json_result_before)
                if json_loads is not None:
                    json_loads.assert_called_once_with('{"kid":"kid-current"}')
                if isinstance(json_result, HeaderDictSubclass):
                    self.assertEqual(json_result.get_call_count, 0)
                    self.assertEqual(vars(json_result), json_result_attrs_before)
                    self.assertIs(json_result.sentinel_state, json_result_state)
                if json_result is exact_dict_with_kid_subclass:
                    self.assertIs(type(json_result), dict)
                    self.assertIs(json_result["kid"], kid_string_subclass)
                    self.assertEqual(kid_string_subclass.bool_call_count, 0)
                    self.assertEqual(vars(kid_string_subclass), kid_attrs_before)
                    self.assertIs(kid_string_subclass.sentinel_state, kid_state)

    def test_jwt_expiry_returns_exact_aware_utc_datetime_without_mutation(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_jwt_expiry_success",
            SCRIPT_PATH,
        )
        payload = b'{"exp":946684800}'
        encoded_payload = module.base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
        raw_token = f"header.{encoded_payload}.signature"
        raw_token_before = raw_token

        returned = module._jwt_expiry(raw_token)

        self.assertIs(type(raw_token), str)
        self.assertIs(type(returned), module.datetime)
        self.assertEqual(
            returned,
            module.datetime(2000, 1, 1, tzinfo=module.timezone.utc),
        )
        self.assertIs(returned.tzinfo, module.timezone.utc)
        self.assertEqual(raw_token, raw_token_before)

    def test_jwt_expiry_rejects_non_string_split_probes_without_hooks_or_mutation(
        self,
    ) -> None:
        import traceback

        module = _load_module(
            "connected_runtime_postgres_live_e2e_jwt_expiry_type_guards",
            SCRIPT_PATH,
        )
        sensitive_marker = "synthetic-sensitive-jwt-split-marker"

        class NonStringSplitProbe:
            def __init__(self) -> None:
                self.split_call_count = 0
                self.sentinel_state = {"phase": "before", "items": ["unchanged"]}

            def split(self, *_: object, **__: object) -> list[str]:
                self.split_call_count += 1
                raise AssertionError(sensitive_marker)

        class StringSubclassSplitProbe(str):
            def __new__(cls, value: str):
                instance = super().__new__(cls, value)
                instance.split_call_count = 0
                instance.sentinel_state = {
                    "phase": "before",
                    "items": ["unchanged"],
                }
                return instance

            def split(self, *_: object, **__: object) -> list[str]:
                self.split_call_count += 1
                raise AssertionError(sensitive_marker)

        probes = (
            ("non_string", NonStringSplitProbe()),
            (
                "string_subclass",
                StringSubclassSplitProbe("header.payload.signature"),
            ),
        )
        for name, probe in probes:
            with self.subTest(case=name):
                probe_state = probe.sentinel_state
                probe_before = copy.deepcopy(vars(probe))

                with self.assertRaises(RuntimeError) as raised:
                    module._jwt_expiry(probe)

                rendered = "".join(
                    traceback.format_exception(
                        type(raised.exception),
                        raised.exception,
                        raised.exception.__traceback__,
                    )
                )
                self.assertIs(type(raised.exception), RuntimeError)
                self.assertEqual(
                    str(raised.exception),
                    "live_e2e_token_payload_invalid",
                )
                self.assertIsNone(raised.exception.__cause__)
                self.assertTrue(raised.exception.__suppress_context__)
                self.assertNotIn(sensitive_marker, str(raised.exception))
                self.assertNotIn(sensitive_marker, rendered)
                self.assertEqual(probe.split_call_count, 0)
                self.assertEqual(vars(probe), probe_before)
                self.assertIs(probe.sentinel_state, probe_state)

    def test_jwt_expiry_rejects_malformed_payloads_with_one_suppressed_error(
        self,
    ) -> None:
        import traceback

        module = _load_module(
            "connected_runtime_postgres_live_e2e_jwt_expiry_failures",
            SCRIPT_PATH,
        )
        sensitive_marker = "synthetic-sensitive-jwt-payload-marker"

        def encode_payload(payload: bytes) -> str:
            return module.base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")

        def token(payload_segment: str) -> str:
            return f"header.{payload_segment}.signature"

        valid_payload = encode_payload(b'{"exp":0}')
        noncanonical_payload = encode_payload(b'{"exp":0,"x":""}')
        self.assertTrue(noncanonical_payload.endswith("Q"))

        class ExpiryIntSubclass(int):
            pass

        exact_int_subclass_payload = {
            "exp": ExpiryIntSubclass(0),
            "sentinel_state": {"phase": "before", "items": ["unchanged"]},
        }
        cases = (
            {"name": "two_segments", "raw_token": "header.payload"},
            {
                "name": "four_segments",
                "raw_token": "header.payload.signature.extra",
            },
            {"name": "empty_header", "raw_token": f".{valid_payload}.signature"},
            {"name": "empty_payload", "raw_token": "header..signature"},
            {"name": "empty_signature", "raw_token": f"header.{valid_payload}."},
            {
                "name": "padded_payload",
                "raw_token": token(f"{valid_payload}="),
            },
            {
                "name": "illegal_base64url_payload",
                "raw_token": token(f"{valid_payload[:3]}*{valid_payload[3:]}"),
            },
            {
                "name": "non_ascii_payload",
                "raw_token": token("é"),
            },
            {
                "name": "noncanonical_base64url_payload",
                "raw_token": token(f"{noncanonical_payload[:-1]}R"),
            },
            {
                "name": "invalid_utf8_payload",
                "raw_token": token(encode_payload(b"\xff")),
            },
            {
                "name": "invalid_json_payload",
                "raw_token": token(encode_payload(b"{")),
            },
            {
                "name": "non_mapping_payload",
                "raw_token": token(encode_payload(b"[]")),
            },
            {
                "name": "missing_expiry",
                "raw_token": token(encode_payload(b"{}")),
            },
            {
                "name": "boolean_expiry",
                "raw_token": token(encode_payload(b'{"exp":true}')),
            },
            {
                "name": "string_expiry",
                "raw_token": token(encode_payload(b'{"exp":"0"}')),
            },
            {
                "name": "float_expiry",
                "raw_token": token(encode_payload(b'{"exp":0.0}')),
            },
            {
                "name": "exact_int_subclass_expiry",
                "raw_token": token(valid_payload),
                "json_result": exact_int_subclass_payload,
            },
            {
                "name": "out_of_range_expiry",
                "raw_token": token(
                    encode_payload(
                        module.json.dumps(
                            {"exp": 10**100},
                            separators=(",", ":"),
                        ).encode("utf-8")
                    )
                ),
            },
            {
                "name": "timestamp_conversion_failure",
                "raw_token": token(valid_payload),
                "timestamp_error": OSError(sensitive_marker),
            },
        )

        for case in cases:
            with self.subTest(case=case["name"]):
                raw_token = case["raw_token"]
                raw_token_before = raw_token
                json_result = case.get("json_result")
                json_result_before = copy.deepcopy(json_result)
                json_result_state = (
                    json_result.get("sentinel_state") if isinstance(json_result, dict) else None
                )
                json_loads = None
                fromtimestamp = None
                with ExitStack() as stack:
                    if json_result is not None:
                        json_loads = stack.enter_context(
                            mock.patch.object(
                                module.json,
                                "loads",
                                return_value=json_result,
                            )
                        )
                    if "timestamp_error" in case:
                        fromtimestamp = mock.Mock(
                            side_effect=case["timestamp_error"],
                        )
                        stack.enter_context(
                            mock.patch.object(
                                module,
                                "datetime",
                                SimpleNamespace(fromtimestamp=fromtimestamp),
                            )
                        )

                    with self.assertRaises(RuntimeError) as raised:
                        module._jwt_expiry(raw_token)

                rendered = "".join(
                    traceback.format_exception(
                        type(raised.exception),
                        raised.exception,
                        raised.exception.__traceback__,
                    )
                )
                self.assertIs(type(raised.exception), RuntimeError)
                self.assertEqual(
                    str(raised.exception),
                    "live_e2e_token_payload_invalid",
                )
                self.assertIsNone(raised.exception.__cause__)
                self.assertTrue(raised.exception.__suppress_context__)
                self.assertNotIn(sensitive_marker, str(raised.exception))
                self.assertNotIn(sensitive_marker, rendered)
                self.assertEqual(raw_token, raw_token_before)
                self.assertEqual(json_result, json_result_before)
                if json_loads is not None:
                    json_loads.assert_called_once_with('{"exp":0}')
                    self.assertIs(type(json_result["exp"]), ExpiryIntSubclass)
                    self.assertIs(json_result["sentinel_state"], json_result_state)
                if fromtimestamp is not None:
                    fromtimestamp.assert_called_once_with(
                        0,
                        tz=module.timezone.utc,
                    )

    def test_compose_runtime_builds_exact_google_rewrites_without_mutation(self) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_compose_runtime_success",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()
        config = SimpleNamespace(sentinel_state={"phase": "before", "items": ["unchanged"]})
        fake_google = SimpleNamespace(
            discovery_url=(
                "https://google-discovery.example.invalid/.well-known/openid-configuration"
            ),
            authorization_endpoint=(
                "https://google-authorization.example.invalid/oauth2/authorize"
            ),
            token_endpoint="https://google-token.example.invalid/oauth2/token",
            jwks_uri="https://google-jwks.example.invalid/keys",
            sentinel_state={"phase": "before", "items": ["unchanged"]},
        )
        expected_rewrites = {
            module.GOOGLE_DISCOVERY_URL: fake_google.discovery_url,
            module.GOOGLE_AUTHORIZATION_ENDPOINT: fake_google.authorization_endpoint,
            module.GOOGLE_TOKEN_ENDPOINT: fake_google.token_endpoint,
            module.GOOGLE_JWKS_URI: fake_google.jwks_uri,
        }
        config_before = copy.deepcopy(vars(config))
        fake_google_before = copy.deepcopy(vars(fake_google))
        config_state = config.sentinel_state
        fake_google_state = fake_google.sentinel_state
        client_sentinel = object()
        runtime_sentinel = object()
        compose = mock.AsyncMock(return_value=runtime_sentinel)

        with (
            mock.patch.object(
                module,
                "_ClosableRewritingAsyncHttpClient",
                return_value=client_sentinel,
            ) as client_constructor,
            mock.patch.object(module.ConnectedRuntime, "compose", compose),
        ):
            returned = asyncio.run(module._compose_runtime(config, fake_google=fake_google))

        self.assertIs(returned, runtime_sentinel)
        client_constructor.assert_called_once_with(expected_rewrites)
        compose.assert_awaited_once_with(config, http_client=client_sentinel)
        compose.assert_called_once_with(config, http_client=client_sentinel)
        self.assertIs(compose.await_args.args[0], config)
        self.assertIs(compose.await_args.kwargs["http_client"], client_sentinel)
        self.assertIs(compose.call_args.args[0], config)
        self.assertIs(compose.call_args.kwargs["http_client"], client_sentinel)
        self.assertIs(config.sentinel_state, config_state)
        self.assertIs(fake_google.sentinel_state, fake_google_state)
        self.assertEqual(vars(config), config_before)
        self.assertEqual(vars(fake_google), fake_google_before)

    def test_compose_runtime_propagates_compose_failure_without_retry_or_mutation(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_compose_runtime_failure",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()
        config = SimpleNamespace(sentinel_state={"phase": "before", "items": ["unchanged"]})
        fake_google = SimpleNamespace(
            discovery_url=(
                "https://google-discovery.example.invalid/.well-known/openid-configuration"
            ),
            authorization_endpoint=(
                "https://google-authorization.example.invalid/oauth2/authorize"
            ),
            token_endpoint="https://google-token.example.invalid/oauth2/token",
            jwks_uri="https://google-jwks.example.invalid/keys",
            sentinel_state={"phase": "before", "items": ["unchanged"]},
        )
        expected_rewrites = {
            module.GOOGLE_DISCOVERY_URL: fake_google.discovery_url,
            module.GOOGLE_AUTHORIZATION_ENDPOINT: fake_google.authorization_endpoint,
            module.GOOGLE_TOKEN_ENDPOINT: fake_google.token_endpoint,
            module.GOOGLE_JWKS_URI: fake_google.jwks_uri,
        }
        config_before = copy.deepcopy(vars(config))
        fake_google_before = copy.deepcopy(vars(fake_google))
        config_state = config.sentinel_state
        fake_google_state = fake_google.sentinel_state
        client_sentinel = object()
        compose_failure = RuntimeError("synthetic-compose-failure")
        compose = mock.AsyncMock(side_effect=compose_failure)

        with (
            mock.patch.object(
                module,
                "_ClosableRewritingAsyncHttpClient",
                return_value=client_sentinel,
            ) as client_constructor,
            mock.patch.object(module.ConnectedRuntime, "compose", compose),
            self.assertRaises(RuntimeError) as raised,
        ):
            asyncio.run(module._compose_runtime(config, fake_google=fake_google))

        self.assertIs(raised.exception, compose_failure)
        client_constructor.assert_called_once_with(expected_rewrites)
        compose.assert_awaited_once_with(config, http_client=client_sentinel)
        compose.assert_called_once_with(config, http_client=client_sentinel)
        self.assertIs(compose.await_args.args[0], config)
        self.assertIs(compose.await_args.kwargs["http_client"], client_sentinel)
        self.assertIs(compose.call_args.args[0], config)
        self.assertIs(compose.call_args.kwargs["http_client"], client_sentinel)
        self.assertIs(config.sentinel_state, config_state)
        self.assertIs(fake_google.sentinel_state, fake_google_state)
        self.assertEqual(vars(config), config_before)
        self.assertEqual(vars(fake_google), fake_google_before)

    def test_count_rows_returns_exact_nonnegative_counts_for_allowed_tables_without_mutation(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_count_rows_success",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()
        query_one = mock.Mock()
        connection_state = {"phase": "before", "items": ["unchanged"]}
        repository_state = {"phase": "before", "items": ["unchanged"]}
        runtime_state = {"phase": "before", "items": ["unchanged"]}
        connection = SimpleNamespace(
            query_one=query_one,
            sentinel_state=connection_state,
        )
        repository = SimpleNamespace(
            connection=connection,
            sentinel_state=repository_state,
        )
        runtime = SimpleNamespace(
            repository=repository,
            sentinel_state=runtime_state,
        )
        connection_keys_before = set(vars(connection))
        repository_keys_before = set(vars(repository))
        runtime_keys_before = set(vars(runtime))
        connection_state_before = copy.deepcopy(connection_state)
        repository_state_before = copy.deepcopy(repository_state)
        runtime_state_before = copy.deepcopy(runtime_state)
        table_names = (
            "formowl_audit_log",
            "formowl_external_identities",
            "formowl_oauth_invitations",
            "formowl_oauth_token_sessions",
            "formowl_schema_migrations",
            "formowl_users",
            "formowl_workspace_members",
        )

        for row_count, table_name in enumerate(table_names):
            with self.subTest(table_name=table_name):
                query_one.reset_mock()
                row = {"row_count": row_count}
                row_before = copy.copy(row)
                query_one.return_value = row
                expected_statement = module.SQLStatement(
                    sql=f"SELECT COUNT(*) AS row_count FROM {table_name}",
                    parameters={},
                )

                returned = module._count_rows(runtime, table_name)

                self.assertIs(type(returned), int)
                self.assertEqual(returned, row_count)
                self.assertGreaterEqual(returned, 0)
                query_one.assert_called_once_with(expected_statement)
                actual_statement = query_one.call_args.args[0]
                self.assertIs(type(actual_statement), module.SQLStatement)
                self.assertEqual(actual_statement, expected_statement)
                self.assertEqual(actual_statement.parameters, {})
                self.assertEqual(row, row_before)
                self.assertIs(runtime.repository, repository)
                self.assertIs(repository.connection, connection)
                self.assertIs(connection.query_one, query_one)
                self.assertIs(runtime.sentinel_state, runtime_state)
                self.assertIs(repository.sentinel_state, repository_state)
                self.assertIs(connection.sentinel_state, connection_state)
                self.assertEqual(set(vars(runtime)), runtime_keys_before)
                self.assertEqual(set(vars(repository)), repository_keys_before)
                self.assertEqual(set(vars(connection)), connection_keys_before)
                self.assertEqual(runtime.sentinel_state, runtime_state_before)
                self.assertEqual(repository.sentinel_state, repository_state_before)
                self.assertEqual(connection.sentinel_state, connection_state_before)

    def test_count_rows_rejects_invalid_database_counts_without_coercion_or_mutation(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_count_rows_invalid",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()
        sensitive_marker = "synthetic-sensitive-row-count-marker"

        class SyntheticIntSubclass(int):
            pass

        class IntCoercionProbe:
            def __init__(self) -> None:
                self.int_call_count = 0
                self.sentinel_state = {
                    "phase": "before",
                    "items": ["unchanged"],
                }

            def __int__(self) -> int:
                self.int_call_count += 1
                self.sentinel_state["phase"] = "int-called"
                raise RuntimeError(sensitive_marker)

        coercion_probe = IntCoercionProbe()
        coercion_probe_keys_before = set(vars(coercion_probe))
        coercion_probe_state = coercion_probe.sentinel_state
        coercion_probe_state_before = copy.deepcopy(coercion_probe_state)
        query_one = mock.Mock()
        connection_state = {"phase": "before", "items": ["unchanged"]}
        repository_state = {"phase": "before", "items": ["unchanged"]}
        runtime_state = {"phase": "before", "items": ["unchanged"]}
        connection = SimpleNamespace(
            query_one=query_one,
            sentinel_state=connection_state,
        )
        repository = SimpleNamespace(
            connection=connection,
            sentinel_state=repository_state,
        )
        runtime = SimpleNamespace(
            repository=repository,
            sentinel_state=runtime_state,
        )
        connection_keys_before = set(vars(connection))
        repository_keys_before = set(vars(repository))
        runtime_keys_before = set(vars(runtime))
        connection_state_before = copy.deepcopy(connection_state)
        repository_state_before = copy.deepcopy(repository_state)
        runtime_state_before = copy.deepcopy(runtime_state)
        expected_statement = module.SQLStatement(
            sql="SELECT COUNT(*) AS row_count FROM formowl_users",
            parameters={},
        )
        cases = (
            ("non_mapping", []),
            ("missing_row_count", {}),
            ("bool", {"row_count": True}),
            ("string", {"row_count": "7"}),
            ("float", {"row_count": 1.25}),
            ("negative_int", {"row_count": -1}),
            ("int_subclass", {"row_count": SyntheticIntSubclass(7)}),
            ("custom_int_coercion", {"row_count": coercion_probe}),
        )

        for case_name, row in cases:
            with self.subTest(case=case_name):
                query_one.reset_mock()
                query_one.return_value = row
                row_before = copy.copy(row)

                with self.assertRaises(RuntimeError) as raised:
                    module._count_rows(runtime, "formowl_users")

                self.assertIs(type(raised.exception), RuntimeError)
                self.assertEqual(
                    str(raised.exception),
                    "live_e2e_database_count_invalid",
                )
                self.assertNotIn(sensitive_marker, str(raised.exception))
                query_one.assert_called_once_with(expected_statement)
                self.assertEqual(query_one.call_count, 1)
                actual_statement = query_one.call_args.args[0]
                self.assertIs(type(actual_statement), module.SQLStatement)
                self.assertEqual(actual_statement, expected_statement)
                self.assertEqual(actual_statement.parameters, {})
                self.assertEqual(row, row_before)
                self.assertEqual(coercion_probe.int_call_count, 0)
                self.assertEqual(set(vars(coercion_probe)), coercion_probe_keys_before)
                self.assertIs(coercion_probe.sentinel_state, coercion_probe_state)
                self.assertEqual(coercion_probe.sentinel_state, coercion_probe_state_before)
                self.assertIs(runtime.repository, repository)
                self.assertIs(repository.connection, connection)
                self.assertIs(connection.query_one, query_one)
                self.assertIs(runtime.sentinel_state, runtime_state)
                self.assertIs(repository.sentinel_state, repository_state)
                self.assertIs(connection.sentinel_state, connection_state)
                self.assertEqual(set(vars(runtime)), runtime_keys_before)
                self.assertEqual(set(vars(repository)), repository_keys_before)
                self.assertEqual(set(vars(connection)), connection_keys_before)
                self.assertEqual(runtime.sentinel_state, runtime_state_before)
                self.assertEqual(repository.sentinel_state, repository_state_before)
                self.assertEqual(connection.sentinel_state, connection_state_before)

    def test_count_oauth_state_returns_exact_nonnegative_counts_without_mutation(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_count_oauth_state_success",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()
        query_one = mock.Mock()
        connection_state = {"phase": "before", "items": ["unchanged"]}
        repository_state = {"phase": "before", "items": ["unchanged"]}
        runtime_state = {"phase": "before", "items": ["unchanged"]}
        connection = SimpleNamespace(
            query_one=query_one,
            sentinel_state=connection_state,
        )
        repository = SimpleNamespace(
            connection=connection,
            sentinel_state=repository_state,
        )
        runtime = SimpleNamespace(
            repository=repository,
            sentinel_state=runtime_state,
        )
        connection_keys_before = set(vars(connection))
        repository_keys_before = set(vars(repository))
        runtime_keys_before = set(vars(runtime))
        connection_state_before = copy.deepcopy(connection_state)
        repository_state_before = copy.deepcopy(repository_state)
        runtime_state_before = copy.deepcopy(runtime_state)
        cases = (
            (
                "accepted_invitations",
                0,
                "SELECT COUNT(*) AS row_count FROM formowl_oauth_invitations "
                "WHERE status = 'accepted'",
            ),
            (
                "revoked_token_sessions",
                7,
                "SELECT COUNT(*) AS row_count FROM formowl_oauth_token_sessions "
                "WHERE revoked_at IS NOT NULL",
            ),
        )

        for state_name, row_count, sql in cases:
            with self.subTest(state_name=state_name):
                query_one.reset_mock()
                query_one.return_value = {"row_count": row_count}
                expected_statement = module.SQLStatement(sql=sql, parameters={})

                returned = module._count_oauth_state(runtime, state_name)

                self.assertIs(type(returned), int)
                self.assertEqual(returned, row_count)
                self.assertGreaterEqual(returned, 0)
                query_one.assert_called_once_with(expected_statement)
                actual_statement = query_one.call_args.args[0]
                self.assertIs(type(actual_statement), module.SQLStatement)
                self.assertEqual(actual_statement, expected_statement)
                self.assertEqual(actual_statement.parameters, {})
                self.assertIs(runtime.repository, repository)
                self.assertIs(repository.connection, connection)
                self.assertIs(connection.query_one, query_one)
                self.assertIs(runtime.sentinel_state, runtime_state)
                self.assertIs(repository.sentinel_state, repository_state)
                self.assertIs(connection.sentinel_state, connection_state)
                self.assertEqual(set(vars(runtime)), runtime_keys_before)
                self.assertEqual(set(vars(repository)), repository_keys_before)
                self.assertEqual(set(vars(connection)), connection_keys_before)
                self.assertEqual(runtime.sentinel_state, runtime_state_before)
                self.assertEqual(repository.sentinel_state, repository_state_before)
                self.assertEqual(connection.sentinel_state, connection_state_before)

    def test_count_oauth_state_rejects_unsupported_state_without_query_or_mutation(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_count_oauth_state_unsupported",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()
        sensitive_marker = "synthetic-sensitive-state-marker"

        class StateNameHashProbe(str):
            def __new__(cls, value: str) -> StateNameHashProbe:
                instance = super().__new__(cls, value)
                instance.hash_call_count = 0
                instance.sentinel_state = {
                    "phase": "before",
                    "items": ["unchanged"],
                }
                return instance

            def __hash__(self) -> int:
                self.hash_call_count += 1
                self.sentinel_state["phase"] = "hash-called"
                raise RuntimeError(sensitive_marker)

        unhashable_state_name = ["accepted_invitations"]
        hash_probe = StateNameHashProbe("accepted_invitations")
        unhashable_state_name_before = copy.deepcopy(unhashable_state_name)
        hash_probe_keys_before = set(vars(hash_probe))
        hash_probe_state = hash_probe.sentinel_state
        hash_probe_state_before = copy.deepcopy(hash_probe_state)
        query_one = mock.Mock()
        connection_state = {"phase": "before", "items": ["unchanged"]}
        repository_state = {"phase": "before", "items": ["unchanged"]}
        runtime_state = {"phase": "before", "items": ["unchanged"]}
        connection = SimpleNamespace(
            query_one=query_one,
            sentinel_state=connection_state,
        )
        repository = SimpleNamespace(
            connection=connection,
            sentinel_state=repository_state,
        )
        runtime = SimpleNamespace(
            repository=repository,
            sentinel_state=runtime_state,
        )
        connection_keys_before = set(vars(connection))
        repository_keys_before = set(vars(repository))
        runtime_keys_before = set(vars(runtime))
        connection_state_before = copy.deepcopy(connection_state)
        repository_state_before = copy.deepcopy(repository_state)
        runtime_state_before = copy.deepcopy(runtime_state)
        cases = (
            ("unknown_string", f"unknown-{sensitive_marker}"),
            ("non_string", 31415),
            ("unhashable_non_string", unhashable_state_name),
            ("str_subclass_hash_probe", hash_probe),
        )

        for case_name, state_name in cases:
            with self.subTest(case=case_name):
                query_one.reset_mock()

                with self.assertRaises(ValueError) as raised:
                    module._count_oauth_state(runtime, state_name)

                self.assertIs(type(raised.exception), ValueError)
                self.assertEqual(
                    str(raised.exception),
                    "unsupported live E2E OAuth state count",
                )
                self.assertNotIn(sensitive_marker, str(raised.exception))
                query_one.assert_not_called()
                self.assertEqual(unhashable_state_name, unhashable_state_name_before)
                self.assertEqual(hash_probe.hash_call_count, 0)
                self.assertEqual(set(vars(hash_probe)), hash_probe_keys_before)
                self.assertIs(hash_probe.sentinel_state, hash_probe_state)
                self.assertEqual(hash_probe.sentinel_state, hash_probe_state_before)
                self.assertIs(runtime.repository, repository)
                self.assertIs(repository.connection, connection)
                self.assertIs(connection.query_one, query_one)
                self.assertIs(runtime.sentinel_state, runtime_state)
                self.assertIs(repository.sentinel_state, repository_state)
                self.assertIs(connection.sentinel_state, connection_state)
                self.assertEqual(set(vars(runtime)), runtime_keys_before)
                self.assertEqual(set(vars(repository)), repository_keys_before)
                self.assertEqual(set(vars(connection)), connection_keys_before)
                self.assertEqual(runtime.sentinel_state, runtime_state_before)
                self.assertEqual(repository.sentinel_state, repository_state_before)
                self.assertEqual(connection.sentinel_state, connection_state_before)

    def test_count_oauth_state_rejects_invalid_database_counts_without_coercion_or_mutation(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_count_oauth_state_invalid_rows",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()
        sensitive_marker = "synthetic-sensitive-count-marker"

        class SyntheticIntSubclass(int):
            pass

        class IntCoercionProbe:
            def __init__(self) -> None:
                self.int_call_count = 0

            def __int__(self) -> int:
                self.int_call_count += 1
                raise RuntimeError(sensitive_marker)

        coercion_probe = IntCoercionProbe()
        query_one = mock.Mock()
        connection_state = {"phase": "before", "items": ["unchanged"]}
        repository_state = {"phase": "before", "items": ["unchanged"]}
        runtime_state = {"phase": "before", "items": ["unchanged"]}
        connection = SimpleNamespace(
            query_one=query_one,
            sentinel_state=connection_state,
        )
        repository = SimpleNamespace(
            connection=connection,
            sentinel_state=repository_state,
        )
        runtime = SimpleNamespace(
            repository=repository,
            sentinel_state=runtime_state,
        )
        connection_keys_before = set(vars(connection))
        repository_keys_before = set(vars(repository))
        runtime_keys_before = set(vars(runtime))
        connection_state_before = copy.deepcopy(connection_state)
        repository_state_before = copy.deepcopy(repository_state)
        runtime_state_before = copy.deepcopy(runtime_state)
        expected_statement = module.SQLStatement(
            sql=(
                "SELECT COUNT(*) AS row_count FROM formowl_oauth_invitations "
                "WHERE status = 'accepted'"
            ),
            parameters={},
        )
        cases = (
            ("non_mapping", []),
            ("missing_row_count", {}),
            ("bool", {"row_count": True}),
            ("string", {"row_count": "7"}),
            ("float", {"row_count": 1.25}),
            ("negative_int", {"row_count": -1}),
            ("int_subclass", {"row_count": SyntheticIntSubclass(7)}),
            ("custom_int_coercion", {"row_count": coercion_probe}),
        )

        for case_name, row in cases:
            with self.subTest(case=case_name):
                query_one.reset_mock()
                query_one.return_value = row
                row_before = copy.copy(row)

                with self.assertRaises(RuntimeError) as raised:
                    module._count_oauth_state(runtime, "accepted_invitations")

                if case_name == "custom_int_coercion":
                    self.assertEqual(coercion_probe.int_call_count, 0)
                self.assertEqual(
                    str(raised.exception),
                    "live_e2e_database_count_invalid",
                )
                self.assertNotIn(sensitive_marker, str(raised.exception))
                query_one.assert_called_once_with(expected_statement)
                actual_statement = query_one.call_args.args[0]
                self.assertIs(type(actual_statement), module.SQLStatement)
                self.assertEqual(actual_statement, expected_statement)
                self.assertEqual(actual_statement.parameters, {})
                self.assertEqual(row, row_before)
                self.assertIs(runtime.repository, repository)
                self.assertIs(repository.connection, connection)
                self.assertIs(connection.query_one, query_one)
                self.assertIs(runtime.sentinel_state, runtime_state)
                self.assertIs(repository.sentinel_state, repository_state)
                self.assertIs(connection.sentinel_state, connection_state)
                self.assertEqual(set(vars(runtime)), runtime_keys_before)
                self.assertEqual(set(vars(repository)), repository_keys_before)
                self.assertEqual(set(vars(connection)), connection_keys_before)
                self.assertEqual(runtime.sentinel_state, runtime_state_before)
                self.assertEqual(repository.sentinel_state, repository_state_before)
                self.assertEqual(connection.sentinel_state, connection_state_before)

    def test_token_session_binding_requires_exact_row_and_values_without_hooks_or_mutation(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_token_binding_exact_row",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()
        sensitive_marker = "synthetic-sensitive-token-binding.invalid"
        fields = (
            "token_session_id",
            "user_id",
            "current_workspace_id",
        )
        valid_row = {
            "token_session_id": "session-token.invalid",
            "user_id": "user-actor.invalid",
            "current_workspace_id": "workspace-scope.invalid",
        }
        expected_statement = module.SQLStatement(
            sql=(
                "SELECT token_session_id, user_id, current_workspace_id "
                "FROM formowl_oauth_token_sessions ORDER BY issued_at LIMIT 1"
            ),
            parameters={},
        )

        class MappingRow(Mapping[object, object]):
            def __init__(self, payload: dict[str, object]) -> None:
                self.payload = dict(payload)
                self.hook_calls = {
                    "get": 0,
                    "getitem": 0,
                    "iter": 0,
                    "len": 0,
                }
                self.sentinel_state = {
                    "phase": "before",
                    "items": ["unchanged"],
                }

            def _record(self, name: str) -> None:
                self.hook_calls[name] += 1
                self.sentinel_state["phase"] = f"{name}-called"

            def get(self, key: object, default: object = None) -> object:
                self._record("get")
                return dict.get(self.payload, key, default)

            def __getitem__(self, key: object) -> object:
                self._record("getitem")
                return dict.__getitem__(self.payload, key)

            def __iter__(self) -> Iterator[object]:
                self._record("iter")
                return iter(dict.keys(self.payload))

            def __len__(self) -> int:
                self._record("len")
                return dict.__len__(self.payload)

        class DictRow(dict[str, object]):
            def __init__(self, payload: dict[str, object]) -> None:
                dict.__init__(self, payload)
                self.hook_calls = {
                    "get": 0,
                    "getitem": 0,
                    "iter": 0,
                }
                self.sentinel_state = {
                    "phase": "before",
                    "items": ["unchanged"],
                }

            def _record(self, name: str) -> None:
                self.hook_calls[name] += 1
                self.sentinel_state["phase"] = f"{name}-called"

            def get(self, key: object, default: object = None) -> object:
                self._record("get")
                return dict.get(self, key, default)

            def __getitem__(self, key: object) -> object:
                self._record("getitem")
                return dict.__getitem__(self, key)

            def __iter__(self) -> Iterator[str]:
                self._record("iter")
                return iter(dict.keys(self))

        class FieldStringSubclass(str):
            def __new__(cls, value: str):
                instance = super().__new__(cls, value)
                instance.hook_calls = {
                    "bool": 0,
                    "str": 0,
                    "eq": 0,
                    "ne": 0,
                }
                instance.sentinel_state = {
                    "phase": "before",
                    "items": ["unchanged"],
                }
                return instance

            def _record(self, name: str) -> None:
                self.hook_calls[name] += 1
                self.sentinel_state["phase"] = f"{name}-called"

            def __bool__(self) -> bool:
                self._record("bool")
                return True

            def __str__(self) -> str:
                self._record("str")
                return sensitive_marker

            def __eq__(self, _other: object) -> bool:
                self._record("eq")
                return True

            def __ne__(self, _other: object) -> bool:
                self._record("ne")
                return False

        class CollisionKey:
            def __init__(self, target: str) -> None:
                self.target = target
                self.hook_calls = {
                    "hash": 0,
                    "eq": 0,
                    "str": 0,
                    "bool": 0,
                }
                self.sentinel_state = {
                    "phase": "before",
                    "items": ["unchanged"],
                }

            def _record(self, name: str) -> None:
                self.hook_calls[name] += 1
                self.sentinel_state["phase"] = f"{name}-called"

            def reset_hooks(self) -> None:
                for name in dict.keys(self.hook_calls):
                    self.hook_calls[name] = 0
                self.sentinel_state["phase"] = "before"
                self.sentinel_state["items"][:] = ["unchanged"]

            def __hash__(self) -> int:
                self._record("hash")
                return hash(self.target)

            def __eq__(self, other: object) -> bool:
                self._record("eq")
                return type(other) is str and other == self.target

            def __str__(self) -> str:
                self._record("str")
                return sensitive_marker

            def __bool__(self) -> bool:
                self._record("bool")
                return True

        def row_state(row: object) -> tuple[object, ...]:
            if isinstance(row, dict):
                return (
                    id(row),
                    type(row),
                    tuple(
                        (id(key), type(key), id(value), type(value))
                        for key, value in dict.items(row)
                    ),
                )
            return (id(row), type(row))

        def identity_state(value: object) -> tuple[tuple[str, int], ...]:
            return tuple(sorted((key, id(item)) for key, item in vars(value).items()))

        query_one = mock.Mock(return_value=valid_row)
        write = mock.Mock(side_effect=AssertionError(sensitive_marker))
        connection_state = {"phase": "before", "items": ["unchanged"]}
        repository_state = {"phase": "before", "items": ["unchanged"]}
        runtime_state = {"phase": "before", "items": ["unchanged"]}
        connection = SimpleNamespace(
            query_one=query_one,
            execute=write,
            sentinel_state=connection_state,
        )
        repository = SimpleNamespace(
            connection=connection,
            sentinel_state=repository_state,
        )
        runtime = SimpleNamespace(
            repository=repository,
            sentinel_state=runtime_state,
        )
        connection_identity_before = identity_state(connection)
        repository_identity_before = identity_state(repository)
        runtime_identity_before = identity_state(runtime)
        connection_state_before = copy.deepcopy(connection_state)
        repository_state_before = copy.deepcopy(repository_state)
        runtime_state_before = copy.deepcopy(runtime_state)

        def assert_query_and_state(row: object, row_before: tuple[object, ...]) -> None:
            query_one.assert_called_once_with(expected_statement)
            self.assertEqual(query_one.call_count, 1)
            actual_statement = query_one.call_args.args[0]
            self.assertIs(type(actual_statement), module.SQLStatement)
            self.assertEqual(actual_statement, expected_statement)
            self.assertEqual(
                actual_statement.sql,
                "SELECT token_session_id, user_id, current_workspace_id "
                "FROM formowl_oauth_token_sessions ORDER BY issued_at LIMIT 1",
            )
            self.assertIs(type(actual_statement.parameters), dict)
            self.assertEqual(actual_statement.parameters, {})
            write.assert_not_called()
            self.assertEqual(row_state(row), row_before)
            self.assertIs(runtime.repository, repository)
            self.assertIs(repository.connection, connection)
            self.assertIs(connection.query_one, query_one)
            self.assertIs(connection.execute, write)
            self.assertIs(runtime.sentinel_state, runtime_state)
            self.assertIs(repository.sentinel_state, repository_state)
            self.assertIs(connection.sentinel_state, connection_state)
            self.assertEqual(identity_state(runtime), runtime_identity_before)
            self.assertEqual(identity_state(repository), repository_identity_before)
            self.assertEqual(identity_state(connection), connection_identity_before)
            self.assertEqual(runtime.sentinel_state, runtime_state_before)
            self.assertEqual(repository.sentinel_state, repository_state_before)
            self.assertEqual(connection.sentinel_state, connection_state_before)

        valid_row_before = row_state(valid_row)
        returned = module._token_session_binding(runtime)

        self.assertIs(type(returned), dict)
        self.assertIsNot(returned, valid_row)
        self.assertEqual(tuple(returned), fields)
        self.assertEqual(returned, valid_row)
        self.assertTrue(all(type(value) is str and value for value in returned.values()))
        assert_query_and_state(valid_row, valid_row_before)

        mapping_row = MappingRow(valid_row)
        dict_row = DictRow(valid_row)
        collision_key = CollisionKey("token_session_id")
        collision_row = {
            collision_key: valid_row["token_session_id"],
            "user_id": valid_row["user_id"],
            "current_workspace_id": valid_row["current_workspace_id"],
        }
        self.assertIs(type(collision_row), dict)
        self.assertIs(next(dict.__iter__(collision_row)), collision_key)
        self.assertEqual(
            dict.get(collision_row, "token_session_id"),
            valid_row["token_session_id"],
        )
        self.assertGreater(collision_key.hook_calls["eq"], 0)
        collision_key.reset_hooks()
        cases: list[dict[str, object]] = [
            {
                "name": "none_row",
                "row": None,
                "expected_error": "live_e2e_token_session_missing",
                "probes": (),
            },
            {
                "name": "non_dict_row",
                "row": object(),
                "expected_error": "live_e2e_token_session_missing",
                "probes": (),
            },
            {
                "name": "mapping_subclass_row",
                "row": mapping_row,
                "expected_error": "live_e2e_token_session_missing",
                "probes": (mapping_row,),
            },
            {
                "name": "dict_subclass_row",
                "row": dict_row,
                "expected_error": "live_e2e_token_session_missing",
                "probes": (dict_row,),
            },
            {
                "name": "non_string_collision_key",
                "row": collision_row,
                "expected_error": "live_e2e_token_session_invalid",
                "probes": (collision_key,),
            },
        ]
        for field in fields:
            missing_row = dict(valid_row)
            missing_row.pop(field)
            field_probe = FieldStringSubclass(valid_row[field])
            cases.extend(
                (
                    {
                        "name": f"missing_{field}",
                        "row": missing_row,
                        "expected_error": "live_e2e_token_session_invalid",
                        "probes": (),
                    },
                    {
                        "name": f"wrong_type_{field}",
                        "row": {**valid_row, field: object()},
                        "expected_error": "live_e2e_token_session_invalid",
                        "probes": (),
                    },
                    {
                        "name": f"empty_{field}",
                        "row": {**valid_row, field: ""},
                        "expected_error": "live_e2e_token_session_invalid",
                        "probes": (),
                    },
                    {
                        "name": f"string_subclass_{field}",
                        "row": {**valid_row, field: field_probe},
                        "expected_error": "live_e2e_token_session_invalid",
                        "probes": (field_probe,),
                    },
                )
            )

        for case in cases:
            with self.subTest(case=case["name"]):
                row = case["row"]
                probes = case["probes"]
                query_one.reset_mock()
                query_one.return_value = row
                row_before = row_state(row)
                probe_states_before = tuple((probe, copy.deepcopy(vars(probe))) for probe in probes)

                with self.assertRaises(RuntimeError) as raised:
                    module._token_session_binding(runtime)

                self.assertIs(type(raised.exception), RuntimeError)
                error_message = str(raised.exception)
                self.assertEqual(error_message, case["expected_error"])
                for forbidden in (sensitive_marker, *valid_row.values()):
                    self.assertNotIn(forbidden, error_message)
                assert_query_and_state(row, row_before)
                for probe, state_before in probe_states_before:
                    self.assertEqual(
                        sum(probe.hook_calls.values()),
                        0,
                    )
                    self.assertEqual(vars(probe), state_before)

    def test_latest_token_session_binding_for_user_returns_fresh_principal_bound_payload(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_latest_token_binding_success",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()
        user_id = "user_requested"
        user_id_before = user_id
        row = {
            "token_session_id": "session_latest",
            "user_id": user_id,
            "current_workspace_id": "workspace_current",
        }
        row_before = copy.copy(row)
        query_one = mock.Mock(return_value=row)
        connection_state = {"phase": "before", "items": ["unchanged"]}
        repository_state = {"phase": "before", "items": ["unchanged"]}
        runtime_state = {"phase": "before", "items": ["unchanged"]}
        connection = SimpleNamespace(
            query_one=query_one,
            sentinel_state=connection_state,
        )
        repository = SimpleNamespace(
            connection=connection,
            sentinel_state=repository_state,
        )
        runtime = SimpleNamespace(
            repository=repository,
            sentinel_state=runtime_state,
        )
        connection_keys_before = set(vars(connection))
        repository_keys_before = set(vars(repository))
        runtime_keys_before = set(vars(runtime))
        connection_state_before = copy.deepcopy(connection_state)
        repository_state_before = copy.deepcopy(repository_state)
        runtime_state_before = copy.deepcopy(runtime_state)
        expected_statement = module.SQLStatement(
            sql=(
                "SELECT token_session_id, user_id, current_workspace_id "
                "FROM formowl_oauth_token_sessions WHERE user_id = %(user_id)s "
                "ORDER BY issued_at DESC, token_session_id DESC LIMIT 1"
            ),
            parameters={"user_id": user_id},
        )

        returned = module._latest_token_session_binding_for_user(
            runtime,
            user_id=user_id,
        )

        self.assertIs(type(user_id), str)
        self.assertTrue(user_id)
        self.assertIs(type(returned), dict)
        self.assertIsNot(returned, row)
        self.assertEqual(
            tuple(returned),
            ("token_session_id", "user_id", "current_workspace_id"),
        )
        self.assertEqual(returned, row)
        self.assertTrue(all(type(value) is str and value for value in returned.values()))
        query_one.assert_called_once_with(expected_statement)
        self.assertEqual(query_one.call_count, 1)
        actual_statement = query_one.call_args.args[0]
        self.assertIs(type(actual_statement), module.SQLStatement)
        self.assertEqual(actual_statement, expected_statement)
        self.assertEqual(
            actual_statement.sql,
            "SELECT token_session_id, user_id, current_workspace_id "
            "FROM formowl_oauth_token_sessions WHERE user_id = %(user_id)s "
            "ORDER BY issued_at DESC, token_session_id DESC LIMIT 1",
        )
        self.assertIs(type(actual_statement.parameters), dict)
        self.assertEqual(actual_statement.parameters, {"user_id": user_id})
        self.assertEqual(user_id, user_id_before)
        self.assertEqual(row, row_before)
        self.assertIs(runtime.repository, repository)
        self.assertIs(repository.connection, connection)
        self.assertIs(connection.query_one, query_one)
        self.assertIs(runtime.sentinel_state, runtime_state)
        self.assertIs(repository.sentinel_state, repository_state)
        self.assertIs(connection.sentinel_state, connection_state)
        self.assertEqual(set(vars(runtime)), runtime_keys_before)
        self.assertEqual(set(vars(repository)), repository_keys_before)
        self.assertEqual(set(vars(connection)), connection_keys_before)
        self.assertEqual(runtime.sentinel_state, runtime_state_before)
        self.assertEqual(repository.sentinel_state, repository_state_before)
        self.assertEqual(connection.sentinel_state, connection_state_before)

    def test_latest_token_session_binding_for_user_rejects_invalid_principal_before_query(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_latest_token_binding_principal_guards",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()
        sensitive_marker = "synthetic-sensitive-latest-token-principal-marker"

        class NonStringTruthinessProbe:
            def __init__(self) -> None:
                self.bool_call_count = 0
                self.sentinel_state = {
                    "phase": "before",
                    "items": ["unchanged"],
                }

            def __bool__(self) -> bool:
                self.bool_call_count += 1
                self.sentinel_state["phase"] = "bool-called"
                raise AssertionError(sensitive_marker)

        class UserIdStringSubclass(str):
            def __new__(cls, value: str):
                instance = super().__new__(cls, value)
                instance.bool_call_count = 0
                instance.sentinel_state = {
                    "phase": "before",
                    "items": ["unchanged"],
                }
                return instance

            def __bool__(self) -> bool:
                self.bool_call_count += 1
                self.sentinel_state["phase"] = "bool-called"
                raise AssertionError(sensitive_marker)

        non_string_probe = NonStringTruthinessProbe()
        string_subclass_probe = UserIdStringSubclass("user_requested")
        query_one = mock.Mock(side_effect=AssertionError(sensitive_marker))
        connection_state = {"phase": "before", "items": ["unchanged"]}
        repository_state = {"phase": "before", "items": ["unchanged"]}
        runtime_state = {"phase": "before", "items": ["unchanged"]}
        connection = SimpleNamespace(
            query_one=query_one,
            sentinel_state=connection_state,
        )
        repository = SimpleNamespace(
            connection=connection,
            sentinel_state=repository_state,
        )
        runtime = SimpleNamespace(
            repository=repository,
            sentinel_state=runtime_state,
        )
        connection_keys_before = set(vars(connection))
        repository_keys_before = set(vars(repository))
        runtime_keys_before = set(vars(runtime))
        connection_state_before = copy.deepcopy(connection_state)
        repository_state_before = copy.deepcopy(repository_state)
        runtime_state_before = copy.deepcopy(runtime_state)
        cases = (
            ("empty_string", ""),
            ("non_string", non_string_probe),
            ("string_subclass", string_subclass_probe),
        )

        for case_name, user_id in cases:
            with self.subTest(case=case_name):
                query_one.reset_mock()
                probe_state = getattr(user_id, "sentinel_state", None)
                probe_attrs_before = (
                    copy.deepcopy(vars(user_id))
                    if isinstance(
                        user_id,
                        (NonStringTruthinessProbe, UserIdStringSubclass),
                    )
                    else None
                )

                with self.assertRaises(RuntimeError) as raised:
                    module._latest_token_session_binding_for_user(
                        runtime,
                        user_id=user_id,
                    )

                self.assertIs(type(raised.exception), RuntimeError)
                self.assertEqual(
                    str(raised.exception),
                    "live_e2e_token_session_invalid",
                )
                self.assertNotIn(sensitive_marker, str(raised.exception))
                query_one.assert_not_called()
                if isinstance(
                    user_id,
                    (NonStringTruthinessProbe, UserIdStringSubclass),
                ):
                    self.assertEqual(user_id.bool_call_count, 0)
                    self.assertEqual(vars(user_id), probe_attrs_before)
                    self.assertIs(user_id.sentinel_state, probe_state)
                self.assertIs(runtime.repository, repository)
                self.assertIs(repository.connection, connection)
                self.assertIs(connection.query_one, query_one)
                self.assertIs(runtime.sentinel_state, runtime_state)
                self.assertIs(repository.sentinel_state, repository_state)
                self.assertIs(connection.sentinel_state, connection_state)
                self.assertEqual(set(vars(runtime)), runtime_keys_before)
                self.assertEqual(set(vars(repository)), repository_keys_before)
                self.assertEqual(set(vars(connection)), connection_keys_before)
                self.assertEqual(runtime.sentinel_state, runtime_state_before)
                self.assertEqual(repository.sentinel_state, repository_state_before)
                self.assertEqual(connection.sentinel_state, connection_state_before)

    def test_latest_token_session_binding_for_user_rejects_unbound_or_invalid_rows(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_latest_token_binding_row_guards",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()
        sensitive_marker = "synthetic-sensitive-latest-token-row-marker"
        user_id = "user_requested_sensitive"
        fields = (
            "token_session_id",
            "user_id",
            "current_workspace_id",
        )
        valid_row = {
            "token_session_id": "session_latest",
            "user_id": user_id,
            "current_workspace_id": "workspace_current",
        }

        class HeaderDictSubclass(dict):
            def __init__(self) -> None:
                super().__init__(valid_row)
                self.get_call_count = 0
                self.sentinel_state = {
                    "phase": "before",
                    "items": ["unchanged"],
                }

            def get(self, *_: object, **__: object) -> str:
                self.get_call_count += 1
                self.sentinel_state["phase"] = "get-called"
                raise AssertionError(sensitive_marker)

        class FieldStringSubclass(str):
            def __new__(cls, value: str):
                instance = super().__new__(cls, value)
                instance.bool_call_count = 0
                instance.sentinel_state = {
                    "phase": "before",
                    "items": ["unchanged"],
                }
                return instance

            def __bool__(self) -> bool:
                self.bool_call_count += 1
                self.sentinel_state["phase"] = "bool-called"
                raise AssertionError(sensitive_marker)

        cases = [
            {
                "name": "mismatched_user",
                "row": {**valid_row, "user_id": "user_other_sensitive"},
                "expected_error": "live_e2e_token_session_invalid",
            },
            {
                "name": "dict_subclass_row",
                "row": HeaderDictSubclass(),
                "expected_error": "live_e2e_token_session_missing",
            },
        ]
        for field in fields:
            missing_row = dict(valid_row)
            missing_row.pop(field)
            wrong_type_row = {**valid_row, field: 31415}
            empty_row = {**valid_row, field: ""}
            field_probe = FieldStringSubclass(valid_row[field])
            string_subclass_row = {**valid_row, field: field_probe}
            cases.extend(
                (
                    {
                        "name": f"missing_{field}",
                        "row": missing_row,
                        "expected_error": "live_e2e_token_session_invalid",
                    },
                    {
                        "name": f"wrong_type_{field}",
                        "row": wrong_type_row,
                        "expected_error": "live_e2e_token_session_invalid",
                    },
                    {
                        "name": f"empty_{field}",
                        "row": empty_row,
                        "expected_error": "live_e2e_token_session_invalid",
                    },
                    {
                        "name": f"string_subclass_{field}",
                        "row": string_subclass_row,
                        "expected_error": "live_e2e_token_session_invalid",
                        "field_probe": field_probe,
                    },
                )
            )

        query_one = mock.Mock()
        connection_state = {"phase": "before", "items": ["unchanged"]}
        repository_state = {"phase": "before", "items": ["unchanged"]}
        runtime_state = {"phase": "before", "items": ["unchanged"]}
        connection = SimpleNamespace(
            query_one=query_one,
            sentinel_state=connection_state,
        )
        repository = SimpleNamespace(
            connection=connection,
            sentinel_state=repository_state,
        )
        runtime = SimpleNamespace(
            repository=repository,
            sentinel_state=runtime_state,
        )
        connection_keys_before = set(vars(connection))
        repository_keys_before = set(vars(repository))
        runtime_keys_before = set(vars(runtime))
        connection_state_before = copy.deepcopy(connection_state)
        repository_state_before = copy.deepcopy(repository_state)
        runtime_state_before = copy.deepcopy(runtime_state)
        expected_statement = module.SQLStatement(
            sql=(
                "SELECT token_session_id, user_id, current_workspace_id "
                "FROM formowl_oauth_token_sessions WHERE user_id = %(user_id)s "
                "ORDER BY issued_at DESC, token_session_id DESC LIMIT 1"
            ),
            parameters={"user_id": user_id},
        )

        for case in cases:
            with self.subTest(case=case["name"]):
                row = case["row"]
                query_one.reset_mock()
                query_one.return_value = row
                row_items_before = list(dict.items(row))
                row_state = row.sentinel_state if isinstance(row, HeaderDictSubclass) else None
                row_attrs_before = (
                    copy.deepcopy(vars(row)) if isinstance(row, HeaderDictSubclass) else None
                )
                field_probe = case.get("field_probe")
                field_probe_state = field_probe.sentinel_state if field_probe is not None else None
                field_probe_attrs_before = (
                    copy.deepcopy(vars(field_probe)) if field_probe is not None else None
                )

                with self.assertRaises(RuntimeError) as raised:
                    module._latest_token_session_binding_for_user(
                        runtime,
                        user_id=user_id,
                    )

                self.assertIs(type(raised.exception), RuntimeError)
                self.assertEqual(
                    str(raised.exception),
                    case["expected_error"],
                )
                self.assertNotIn(sensitive_marker, str(raised.exception))
                self.assertNotIn(user_id, str(raised.exception))
                self.assertNotIn("user_other_sensitive", str(raised.exception))
                query_one.assert_called_once_with(expected_statement)
                self.assertEqual(query_one.call_count, 1)
                actual_statement = query_one.call_args.args[0]
                self.assertIs(type(actual_statement), module.SQLStatement)
                self.assertEqual(actual_statement, expected_statement)
                self.assertIs(type(actual_statement.parameters), dict)
                self.assertEqual(actual_statement.parameters, {"user_id": user_id})
                self.assertEqual(list(dict.items(row)), row_items_before)
                if isinstance(row, HeaderDictSubclass):
                    self.assertEqual(row.get_call_count, 0)
                    self.assertEqual(vars(row), row_attrs_before)
                    self.assertIs(row.sentinel_state, row_state)
                if field_probe is not None:
                    self.assertEqual(field_probe.bool_call_count, 0)
                    self.assertEqual(vars(field_probe), field_probe_attrs_before)
                    self.assertIs(field_probe.sentinel_state, field_probe_state)
                self.assertIs(runtime.repository, repository)
                self.assertIs(repository.connection, connection)
                self.assertIs(connection.query_one, query_one)
                self.assertIs(runtime.sentinel_state, runtime_state)
                self.assertIs(repository.sentinel_state, repository_state)
                self.assertIs(connection.sentinel_state, connection_state)
                self.assertEqual(set(vars(runtime)), runtime_keys_before)
                self.assertEqual(set(vars(repository)), repository_keys_before)
                self.assertEqual(set(vars(connection)), connection_keys_before)
                self.assertEqual(runtime.sentinel_state, runtime_state_before)
                self.assertEqual(repository.sentinel_state, repository_state_before)
                self.assertEqual(connection.sentinel_state, connection_state_before)

    def test_implementation_contract_hash_changes_with_runtime_or_migration_source(self) -> None:
        module = _load_module("connected_runtime_postgres_live_e2e_contract", SCRIPT_PATH)
        with tempfile.TemporaryDirectory(
            prefix="formowl-issue20-contract-",
            dir=tempfile.gettempdir(),
        ) as value:
            root = Path(value)
            _write_implementation_contract_fixture(root)

            first = module.issue20_implementation_contract_hash(root)
            repeated = module.issue20_implementation_contract_hash(root)
            migration = root / "python/formowl_graph/storage/migrations/005_oauth_identity.sql"
            migration.write_text("contract:changed-migration\n", encoding="utf-8")
            second = module.issue20_implementation_contract_hash(root)
            runtime_dockerfile = root / "containers/runtime/Dockerfile"
            runtime_dockerfile.write_text("contract:changed-runtime\n", encoding="utf-8")
            third = module.issue20_implementation_contract_hash(root)
            compose = root / "compose.yaml"
            compose.write_text("contract:changed-compose\n", encoding="utf-8")
            fourth = module.issue20_implementation_contract_hash(root)
            runner = root / "scripts/issue20_containerized_evidence_runner.sh"
            runner.write_text("contract:changed-runner\n", encoding="utf-8")
            fifth = module.issue20_implementation_contract_hash(root)
            boundary = root / "scripts/issue20_runner_boundary.py"
            boundary.write_text("contract:changed-runner-boundary\n", encoding="utf-8")
            sixth = module.issue20_implementation_contract_hash(root)

        self.assertRegex(first, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(repeated, first)
        self.assertRegex(second, r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(third, r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(fourth, r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(fifth, r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(sixth, r"^sha256:[0-9a-f]{64}$")
        self.assertNotEqual(first, second)
        self.assertNotEqual(second, third)
        self.assertNotEqual(third, fourth)
        self.assertNotEqual(fourth, fifth)
        self.assertNotEqual(fifth, sixth)

    def test_implementation_contract_hash_missing_required_glob_fails_closed_without_mutation_or_leak(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_contract_missing",
            SCRIPT_PATH,
        )
        with tempfile.TemporaryDirectory(
            prefix="formowl-issue20-contract-missing-",
            dir=tempfile.gettempdir(),
        ) as value:
            root = Path(value)
            _write_implementation_contract_fixture(root)
            (root / "compose.yaml").unlink()
            before = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }

            with self.assertRaisesRegex(
                RuntimeError,
                "^issue20_implementation_contract_missing$",
            ) as caught:
                module.issue20_implementation_contract_hash(root)

            after = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }

        self.assertEqual(after, before)
        self.assertEqual(str(caught.exception), "issue20_implementation_contract_missing")
        self.assertNotIn(str(root), str(caught.exception))
        self.assertNotIn("compose.yaml", str(caught.exception))

    def test_initial_migrate_with_safe_diagnostics_returns_exact_result_without_rerun_or_mutation(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_initial_migrate_success",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()
        migration_result = {
            "applied_migration_count": 1,
            "skipped_migration_count": 4,
        }
        migration_result_before = copy.deepcopy(migration_result)
        operation_events: list[tuple[str, object]] = []
        connection_state = {"phase": "before", "items": ["unchanged"]}
        repository_state = {"phase": "before", "items": ["unchanged"]}
        runtime_state = {"phase": "before", "items": ["unchanged"]}
        original_connection = SimpleNamespace(sentinel_state=connection_state)
        repository = SimpleNamespace(
            connection=original_connection,
            apply_migrations=None,
            sentinel_state=repository_state,
        )

        def migrate_probe() -> dict[str, int]:
            operation_events.append(("migrate", repository.connection))
            return migration_result

        def apply_migrations_probe() -> dict[str, int]:
            operation_events.append(("apply_migrations", repository.connection))
            return migration_result

        migrate = mock.Mock(side_effect=migrate_probe)
        repository.apply_migrations = mock.Mock(side_effect=apply_migrations_probe)
        runtime = SimpleNamespace(
            repository=repository,
            migrate=migrate,
            sentinel_state=runtime_state,
        )
        connection_keys_before = set(vars(original_connection))
        repository_keys_before = set(vars(repository))
        runtime_keys_before = set(vars(runtime))
        connection_state_before = copy.deepcopy(connection_state)
        repository_state_before = copy.deepcopy(repository_state)
        runtime_state_before = copy.deepcopy(runtime_state)

        returned = module._initial_migrate_with_safe_diagnostics(runtime)

        self.assertIs(returned, migration_result)
        self.assertEqual(returned, migration_result_before)
        migrate.assert_called_once_with()
        repository.apply_migrations.assert_not_called()
        self.assertEqual(len(operation_events), 1)
        self.assertEqual(
            [operation_name for operation_name, _ in operation_events],
            ["migrate"],
        )
        self.assertIs(operation_events[0][1], original_connection)
        self.assertIs(runtime.repository, repository)
        self.assertIs(repository.connection, original_connection)
        self.assertIs(original_connection.sentinel_state, connection_state)
        self.assertIs(repository.sentinel_state, repository_state)
        self.assertIs(runtime.sentinel_state, runtime_state)
        self.assertEqual(set(vars(original_connection)), connection_keys_before)
        self.assertEqual(set(vars(repository)), repository_keys_before)
        self.assertEqual(set(vars(runtime)), runtime_keys_before)
        self.assertEqual(original_connection.sentinel_state, connection_state_before)
        self.assertEqual(repository.sentinel_state, repository_state_before)
        self.assertEqual(runtime.sentinel_state, runtime_state_before)

    def test_initial_migrate_with_safe_diagnostics_suppresses_initial_error_after_successful_diagnostic_rerun(
        self,
    ) -> None:
        import traceback

        module = _load_module(
            "connected_runtime_postgres_live_e2e_initial_migrate_diagnostic_success",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()
        sensitive_marker = "synthetic-sensitive-initial-migration-marker"
        initial_error = RuntimeError(sensitive_marker)
        migration_result = {
            "applied_migration_count": 1,
            "skipped_migration_count": 4,
        }
        migration_result_before = copy.deepcopy(migration_result)
        operation_events: list[tuple[str, object]] = []
        connection_state = {"phase": "before", "items": ["unchanged"]}
        repository_state = {"phase": "before", "items": ["unchanged"]}
        runtime_state = {"phase": "before", "items": ["unchanged"]}
        original_connection = SimpleNamespace(sentinel_state=connection_state)
        repository = SimpleNamespace(
            connection=original_connection,
            apply_migrations=None,
            sentinel_state=repository_state,
        )

        def migrate_probe() -> None:
            operation_events.append(("migrate", repository.connection))
            raise initial_error

        def apply_migrations_probe() -> dict[str, int]:
            operation_events.append(("apply_migrations", repository.connection))
            return migration_result

        migrate = mock.Mock(side_effect=migrate_probe)
        repository.apply_migrations = mock.Mock(side_effect=apply_migrations_probe)
        runtime = SimpleNamespace(
            repository=repository,
            migrate=migrate,
            sentinel_state=runtime_state,
        )
        connection_keys_before = set(vars(original_connection))
        repository_keys_before = set(vars(repository))
        runtime_keys_before = set(vars(runtime))
        connection_state_before = copy.deepcopy(connection_state)
        repository_state_before = copy.deepcopy(repository_state)
        runtime_state_before = copy.deepcopy(runtime_state)

        with self.assertRaises(RuntimeError) as caught:
            module._initial_migrate_with_safe_diagnostics(runtime)

        rendered = "".join(
            traceback.format_exception(
                type(caught.exception),
                caught.exception,
                caught.exception.__traceback__,
            )
        )
        self.assertIs(type(caught.exception), RuntimeError)
        self.assertEqual(
            str(caught.exception),
            "live_e2e_migration_wrapper_inconsistent",
        )
        migrate.assert_called_once_with()
        repository.apply_migrations.assert_called_once_with()
        self.assertEqual(len(operation_events), 2)
        self.assertEqual(
            [operation_name for operation_name, _ in operation_events],
            ["migrate", "apply_migrations"],
        )
        self.assertIs(operation_events[0][1], original_connection)
        diagnostic_connection = operation_events[1][1]
        self.assertIs(type(diagnostic_connection), module._MigrationDiagnosticConnection)
        self.assertIs(diagnostic_connection.delegate, original_connection)
        self.assertEqual(diagnostic_connection.operation_index, 0)
        self.assertIs(runtime.repository, repository)
        self.assertIs(repository.connection, original_connection)
        self.assertEqual(migration_result, migration_result_before)
        self.assertIs(original_connection.sentinel_state, connection_state)
        self.assertIs(repository.sentinel_state, repository_state)
        self.assertIs(runtime.sentinel_state, runtime_state)
        self.assertEqual(set(vars(original_connection)), connection_keys_before)
        self.assertEqual(set(vars(repository)), repository_keys_before)
        self.assertEqual(set(vars(runtime)), runtime_keys_before)
        self.assertEqual(original_connection.sentinel_state, connection_state_before)
        self.assertEqual(repository.sentinel_state, repository_state_before)
        self.assertEqual(runtime.sentinel_state, runtime_state_before)
        self.assertNotIn(sensitive_marker, str(caught.exception))
        self.assertNotIn(sensitive_marker, rendered)
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)

    def test_migration_diagnostic_connection_bounds_rollback_and_close_errors(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_migration_diagnostics",
            SCRIPT_PATH,
        )

        class DriverDiagnostic:
            def __init__(self, statement_position: object) -> None:
                self.statement_position = statement_position

        class DriverError(RuntimeError):
            def __init__(
                self,
                message: str,
                *,
                sqlstate: str,
                statement_position: object,
            ) -> None:
                super().__init__(message)
                self.sqlstate = sqlstate
                self.diag = DriverDiagnostic(statement_position)

        rollback_error = DriverError(
            "driver rollback failed "
            "dsn=postgresql://user:secret@db/formowl "
            "sql=SELECT secret FROM oauth_tokens "
            "path=/workspace/private/rollback.sql "
            "backend=postgres-primary",
            sqlstate="40P01",
            statement_position=17,
        )
        close_error = DriverError(
            "driver close failed "
            "dsn=postgresql://close_user:close_secret@db/formowl "
            "sql=DELETE FROM oauth_tokens "
            "path=/workspace/private/close.sql "
            "backend=postgres-replica",
            sqlstate="40P0!",
            statement_position="-7",
        )

        class Delegate:
            def __init__(self) -> None:
                self.calls: list[str] = []
                self.sentinel_state = {
                    "opaque_bytes": b"\x00\xffdelegate-state",
                    "value": ("unchanged", 17),
                }

            def rollback(self) -> None:
                self.calls.append("rollback")
                raise rollback_error

            def close(self) -> None:
                self.calls.append("close")
                raise close_error

        delegate = Delegate()
        sentinel_before = copy.deepcopy(delegate.sentinel_state)
        connection = module._MigrationDiagnosticConnection(delegate)
        cases = (
            (
                "rollback",
                connection.rollback,
                rollback_error,
                "live_e2e_migration_rollback_1_40p01_pos_17_h_unknown",
                1,
                (
                    "postgresql://user:secret@db/formowl",
                    "SELECT secret FROM oauth_tokens",
                    "/workspace/private/rollback.sql",
                    "user:secret",
                    "backend=postgres-primary",
                ),
            ),
            (
                "close",
                connection.close,
                close_error,
                "live_e2e_migration_close_2_unknown_pos_unknown_h_unknown",
                2,
                (
                    "postgresql://close_user:close_secret@db/formowl",
                    "DELETE FROM oauth_tokens",
                    "/workspace/private/close.sql",
                    "close_user:close_secret",
                    "backend=postgres-replica",
                ),
            ),
        )

        for operation, function, driver_error, expected, expected_index, forbidden in cases:
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(RuntimeError, f"^{expected}$") as caught:
                    function()

                rendered = str(caught.exception)
                self.assertEqual(rendered, expected)
                self.assertEqual(connection.operation_index, expected_index)
                self.assertNotIn(str(driver_error), rendered)
                self.assertNotIn("secret", rendered)
                for value in forbidden:
                    self.assertNotIn(value, rendered)

        self.assertEqual(delegate.calls, ["rollback", "close"])
        self.assertEqual(delegate.calls.count("rollback"), 1)
        self.assertEqual(delegate.calls.count("close"), 1)
        self.assertEqual(connection.operation_index, 2)
        self.assertEqual(delegate.sentinel_state, sentinel_before)
        self.assertEqual(
            delegate.sentinel_state["opaque_bytes"],
            sentinel_before["opaque_bytes"],
        )

    def test_migration_diagnostic_connection_forwards_queries_and_bounds_failures(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_migration_wrappers",
            SCRIPT_PATH,
        )

        execute_statement = SimpleNamespace(sql="SELECT migration_success_execute")
        query_one_statement = SimpleNamespace(sql="SELECT migration_success_one")
        query_all_statement = SimpleNamespace(sql="SELECT migration_success_all")
        query_one_result = {"opaque": object()}
        query_all_result = [{"row": object()}]

        class SuccessDelegate:
            def __init__(self) -> None:
                self.calls: list[tuple[str, object | None]] = []
                self.sentinel_state = {
                    "opaque_bytes": b"\x00\xffsuccess-delegate-state",
                    "value": ("unchanged", 23),
                }

            def begin(self) -> None:
                self.calls.append(("begin", None))

            def execute(self, statement: object) -> None:
                self.calls.append(("execute", statement))

            def query_one(self, statement: object) -> object:
                self.calls.append(("query_one", statement))
                return query_one_result

            def query_all(self, statement: object) -> object:
                self.calls.append(("query_all", statement))
                return query_all_result

            def commit(self) -> None:
                self.calls.append(("commit", None))

        success_delegate = SuccessDelegate()
        success_sentinel_before = copy.deepcopy(success_delegate.sentinel_state)
        success_connection = module._MigrationDiagnosticConnection(success_delegate)

        self.assertIsNone(success_connection.begin())
        self.assertEqual(success_connection.operation_index, 1)
        self.assertIsNone(success_connection.execute(execute_statement))
        self.assertEqual(success_connection.operation_index, 2)
        self.assertIs(success_connection.query_one(query_one_statement), query_one_result)
        self.assertEqual(success_connection.operation_index, 3)
        self.assertIs(success_connection.query_all(query_all_statement), query_all_result)
        self.assertEqual(success_connection.operation_index, 4)
        self.assertIsNone(success_connection.commit())
        self.assertEqual(success_connection.operation_index, 5)

        self.assertEqual(
            [operation for operation, _statement in success_delegate.calls],
            ["begin", "execute", "query_one", "query_all", "commit"],
        )
        for operation in ("begin", "execute", "query_one", "query_all", "commit"):
            self.assertEqual(
                [name for name, _statement in success_delegate.calls].count(operation),
                1,
            )
        self.assertIs(success_delegate.calls[1][1], execute_statement)
        self.assertIs(success_delegate.calls[2][1], query_one_statement)
        self.assertIs(success_delegate.calls[3][1], query_all_statement)
        self.assertEqual(success_delegate.sentinel_state, success_sentinel_before)
        self.assertEqual(
            success_delegate.sentinel_state["opaque_bytes"],
            success_sentinel_before["opaque_bytes"],
        )

        class DriverDiagnostic:
            def __init__(self, statement_position: object) -> None:
                self.statement_position = statement_position

        class DriverError(RuntimeError):
            def __init__(
                self,
                message: str,
                *,
                sqlstate: str,
                statement_position: object,
            ) -> None:
                super().__init__(message)
                self.sqlstate = sqlstate
                self.diag = DriverDiagnostic(statement_position)

        failing_statement = SimpleNamespace(
            sql="SELECT private_token FROM oauth_tokens WHERE secret = 'credential'"
        )
        execute_error = DriverError(
            "driver execute failed "
            "dsn=postgresql://user:secret@db/formowl "
            f"sql={failing_statement.sql} "
            "path=/workspace/private/migration.sql "
            "backend=postgres-primary",
            sqlstate="40P01",
            statement_position="29",
        )
        commit_error = DriverError(
            "driver commit failed "
            "dsn=postgresql://commit_user:commit_secret@db/formowl "
            "sql=COMMIT WITH PRIVATE CREDENTIAL "
            "path=/workspace/private/commit.sql "
            "backend=postgres-replica",
            sqlstate="40P0!",
            statement_position="-7",
        )

        class FailureDelegate:
            def __init__(self) -> None:
                self.calls: list[tuple[str, object | None]] = []
                self.sentinel_state = {
                    "opaque_bytes": b"\x00\xfffailure-delegate-state",
                    "value": ("unchanged", 29),
                }

            def execute(self, statement: object) -> None:
                self.calls.append(("execute", statement))
                raise execute_error

            def commit(self) -> None:
                self.calls.append(("commit", None))
                raise commit_error

        failure_delegate = FailureDelegate()
        failure_sentinel_before = copy.deepcopy(failure_delegate.sentinel_state)
        failure_connection = module._MigrationDiagnosticConnection(failure_delegate)
        statement_hash = hashlib.sha256(failing_statement.sql.encode("utf-8")).hexdigest()[:12]
        failure_cases = (
            (
                "execute",
                lambda: failure_connection.execute(failing_statement),
                execute_error,
                f"live_e2e_migration_execute_1_40p01_pos_29_h_{statement_hash}",
                1,
            ),
            (
                "commit",
                failure_connection.commit,
                commit_error,
                "live_e2e_migration_commit_2_unknown_pos_unknown_h_unknown",
                2,
            ),
        )

        for operation, function, driver_error, expected, expected_index in failure_cases:
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(RuntimeError, f"^{expected}$") as caught:
                    function()

                rendered = str(caught.exception)
                self.assertEqual(rendered, expected)
                self.assertEqual(failure_connection.operation_index, expected_index)
                self.assertNotIn(str(driver_error), rendered)
                for forbidden in (
                    "driver",
                    "postgresql://",
                    "secret",
                    "credential",
                    "oauth_tokens",
                    "/workspace/",
                    "backend=",
                ):
                    self.assertNotIn(forbidden, rendered)

        self.assertEqual(
            [operation for operation, _statement in failure_delegate.calls],
            ["execute", "commit"],
        )
        self.assertEqual(
            [operation for operation, _statement in failure_delegate.calls].count("execute"),
            1,
        )
        self.assertEqual(
            [operation for operation, _statement in failure_delegate.calls].count("commit"),
            1,
        )
        self.assertIs(failure_delegate.calls[0][1], failing_statement)
        self.assertEqual(failure_connection.operation_index, 2)
        self.assertEqual(failure_delegate.sentinel_state, failure_sentinel_before)
        self.assertEqual(
            failure_delegate.sentinel_state["opaque_bytes"],
            failure_sentinel_before["opaque_bytes"],
        )

    def test_migration_diagnostic_connection_does_not_convert_untrusted_position(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_migration_position",
            SCRIPT_PATH,
        )
        sensitive_position = (
            "postgresql://position_user:position_secret@db/formowl "
            "path=/workspace/private/position.sql "
            "backend=postgres-primary"
        )

        class StatefulPosition:
            def __init__(self) -> None:
                self.str_call_count = 0
                self.int_call_count = 0
                self.index_call_count = 0
                self.format_call_count = 0

            def __str__(self) -> str:
                self.str_call_count += 1
                return "17" if self.str_call_count == 1 else sensitive_position

            def __int__(self) -> int:
                self.int_call_count += 1
                return 17

            def __index__(self) -> int:
                self.index_call_count += 1
                return 17

            def __format__(self, _format_spec: str) -> str:
                self.format_call_count += 1
                return sensitive_position

        position = StatefulPosition()

        class DriverDiagnostic:
            def __init__(self) -> None:
                self.statement_position_access_count = 0

            @property
            def statement_position(self) -> object:
                self.statement_position_access_count += 1
                return position

        diagnostic = DriverDiagnostic()

        class DriverError(RuntimeError):
            def __init__(self) -> None:
                super().__init__(
                    "driver execute failed "
                    "dsn=postgresql://driver_user:driver_secret@db/formowl "
                    "path=/workspace/private/driver.sql "
                    "backend=postgres-replica"
                )
                self.sqlstate = "40P01"
                self.diag_access_count = 0

            @property
            def diag(self) -> object:
                self.diag_access_count += 1
                return diagnostic

        driver_error = DriverError()
        statement = SimpleNamespace(
            sql="SELECT private_token FROM oauth_tokens WHERE secret = 'credential'"
        )

        class Delegate:
            def __init__(self) -> None:
                self.calls: list[object] = []
                self.sentinel_state = {
                    "opaque_bytes": b"\x00\xffposition-delegate-state",
                    "value": ("unchanged", 17),
                }

            def execute(self, received_statement: object) -> None:
                self.calls.append(received_statement)
                raise driver_error

        delegate = Delegate()
        sentinel_before = copy.deepcopy(delegate.sentinel_state)
        connection = module._MigrationDiagnosticConnection(delegate)
        statement_hash = hashlib.sha256(statement.sql.encode("utf-8")).hexdigest()[:12]
        expected = f"live_e2e_migration_execute_1_40p01_pos_unknown_h_{statement_hash}"

        with self.assertRaises(RuntimeError) as caught:
            connection.execute(statement)

        rendered = str(caught.exception)
        self.assertEqual(delegate.calls, [statement])
        self.assertEqual(len(delegate.calls), 1)
        self.assertIs(delegate.calls[0], statement)
        self.assertEqual(connection.operation_index, 1)
        self.assertEqual(delegate.sentinel_state, sentinel_before)
        self.assertEqual(
            delegate.sentinel_state["opaque_bytes"],
            sentinel_before["opaque_bytes"],
        )
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)
        self.assertIs(caught.exception.__context__, driver_error)
        self.assertEqual(
            {
                "rendered": rendered,
                "diag_access_count": driver_error.diag_access_count,
                "statement_position_access_count": diagnostic.statement_position_access_count,
                "str_call_count": position.str_call_count,
                "int_call_count": position.int_call_count,
                "index_call_count": position.index_call_count,
                "format_call_count": position.format_call_count,
            },
            {
                "rendered": expected,
                "diag_access_count": 1,
                "statement_position_access_count": 1,
                "str_call_count": 0,
                "int_call_count": 0,
                "index_call_count": 0,
                "format_call_count": 0,
            },
        )
        for forbidden in (
            sensitive_position,
            str(driver_error),
            "postgresql://",
            "secret",
            "credential",
            "oauth_tokens",
            "/workspace/",
            "backend=",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_migration_diagnostic_connection_rejects_str_subclass_sqlstate_without_leak(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_migration_sqlstate_subclass",
            SCRIPT_PATH,
        )
        sensitive_sqlstate = (
            "postgresql://state_user:state_secret@example.test/formowl "
            "sql=SELECT synthetic_secret FROM synthetic_tokens "
            "path=/synthetic/private/sqlstate.sql "
            "backend=synthetic-primary credential=synthetic-credential"
        )

        class StatefulSQLState(str):
            str_call_count = 0
            repr_call_count = 0
            format_call_count = 0
            lower_call_count = 0

            def __str__(self) -> str:
                type(self).str_call_count += 1
                return sensitive_sqlstate

            def __repr__(self) -> str:
                type(self).repr_call_count += 1
                return sensitive_sqlstate

            def __format__(self, _format_spec: str) -> str:
                type(self).format_call_count += 1
                return sensitive_sqlstate

            def lower(self) -> str:
                type(self).lower_call_count += 1
                return sensitive_sqlstate

        sqlstate = StatefulSQLState("40P01")

        class DriverDiagnostic:
            def __init__(self) -> None:
                self.statement_position_access_count = 0

            @property
            def statement_position(self) -> int:
                self.statement_position_access_count += 1
                return 31

        diagnostic = DriverDiagnostic()

        class DriverError(RuntimeError):
            def __init__(self) -> None:
                super().__init__(
                    "driver execute failed "
                    "dsn=postgresql://driver_user:driver_secret@example.test/formowl "
                    "sql=SELECT private_token FROM synthetic_tokens "
                    "path=/synthetic/private/driver.sql "
                    "backend=synthetic-replica credential=driver-credential"
                )
                self.sqlstate_access_count = 0
                self.pgcode_access_count = 0
                self.diag_access_count = 0

            @property
            def sqlstate(self) -> object:
                self.sqlstate_access_count += 1
                return sqlstate

            @property
            def pgcode(self) -> str:
                self.pgcode_access_count += 1
                return "40P01"

            @property
            def diag(self) -> object:
                self.diag_access_count += 1
                return diagnostic

        driver_error = DriverError()
        statement = SimpleNamespace(
            sql="SELECT private_token FROM synthetic_tokens WHERE secret = 'credential'"
        )

        class Delegate:
            def __init__(self) -> None:
                self.calls: list[object] = []
                self.sentinel_state = {
                    "opaque_bytes": b"\x00\xffsqlstate-delegate-state",
                    "value": ("unchanged", 31),
                }

            def execute(self, received_statement: object) -> None:
                self.calls.append(received_statement)
                raise driver_error

        delegate = Delegate()
        sentinel_before = copy.deepcopy(delegate.sentinel_state)
        connection = module._MigrationDiagnosticConnection(delegate)
        statement_hash = hashlib.sha256(statement.sql.encode("utf-8")).hexdigest()[:12]
        expected = f"live_e2e_migration_execute_1_unknown_pos_31_h_{statement_hash}"

        with self.assertRaises(RuntimeError) as caught:
            connection.execute(statement)

        rendered = str(caught.exception)
        self.assertEqual(delegate.calls, [statement])
        self.assertEqual(len(delegate.calls), 1)
        self.assertIs(delegate.calls[0], statement)
        self.assertEqual(connection.operation_index, 1)
        self.assertEqual(delegate.sentinel_state, sentinel_before)
        self.assertEqual(
            delegate.sentinel_state["opaque_bytes"],
            sentinel_before["opaque_bytes"],
        )
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)
        self.assertIs(caught.exception.__context__, driver_error)
        self.assertEqual(
            {
                "rendered": rendered,
                "sqlstate_access_count": driver_error.sqlstate_access_count,
                "pgcode_access_count": driver_error.pgcode_access_count,
                "diag_access_count": driver_error.diag_access_count,
                "statement_position_access_count": (diagnostic.statement_position_access_count),
                "str_call_count": StatefulSQLState.str_call_count,
                "repr_call_count": StatefulSQLState.repr_call_count,
                "format_call_count": StatefulSQLState.format_call_count,
                "lower_call_count": StatefulSQLState.lower_call_count,
            },
            {
                "rendered": expected,
                "sqlstate_access_count": 1,
                "pgcode_access_count": 0,
                "diag_access_count": 1,
                "statement_position_access_count": 1,
                "str_call_count": 0,
                "repr_call_count": 0,
                "format_call_count": 0,
                "lower_call_count": 0,
            },
        )
        for forbidden in (
            sensitive_sqlstate,
            sensitive_sqlstate.lower(),
            str(driver_error),
            "SELECT private_token FROM synthetic_tokens",
            "postgresql://",
            "secret",
            "credential",
            "/synthetic/",
            "backend=",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_migration_diagnostic_connection_snapshots_statement_sql_once_and_bounds_accessor_failures(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_migration_statement_accessor",
            SCRIPT_PATH,
        )
        statement_sql = "SELECT private_token FROM synthetic_tokens WHERE secret = 'credential'"
        sensitive_accessor_error = (
            "statement accessor failed "
            "dsn=postgresql://statement_user:statement_secret@example.test/formowl "
            "sql=DELETE FROM synthetic_tokens "
            "path=/synthetic/private/statement.sql "
            "backend=synthetic-primary credential=statement-credential"
        )

        class DriverDiagnostic:
            def __init__(self) -> None:
                self.statement_position_access_count = 0

            @property
            def statement_position(self) -> int:
                self.statement_position_access_count += 1
                return 37

        diagnostic = DriverDiagnostic()

        class DriverError(RuntimeError):
            def __init__(self) -> None:
                super().__init__(
                    "driver execute failed "
                    "dsn=postgresql://driver_user:driver_secret@example.test/formowl "
                    "sql=SELECT private_token FROM synthetic_tokens "
                    "path=/synthetic/private/driver.sql "
                    "backend=synthetic-replica credential=driver-credential"
                )
                self.sqlstate_access_count = 0
                self.diag_access_count = 0

            @property
            def sqlstate(self) -> str:
                self.sqlstate_access_count += 1
                return "40P01"

            @property
            def diag(self) -> object:
                self.diag_access_count += 1
                return diagnostic

        driver_error = DriverError()

        class StatefulStatement:
            def __init__(self) -> None:
                self.sql_access_count = 0

            @property
            def sql(self) -> str:
                self.sql_access_count += 1
                if self.sql_access_count == 1:
                    return statement_sql
                raise RuntimeError(sensitive_accessor_error)

        statement = StatefulStatement()

        class Delegate:
            def __init__(self) -> None:
                self.calls: list[object] = []
                self.sentinel_state = {
                    "opaque_bytes": b"\x00\xffstatement-delegate-state",
                    "value": ("unchanged", 37),
                }

            def execute(self, received_statement: object) -> None:
                self.calls.append(received_statement)
                raise driver_error

        delegate = Delegate()
        sentinel_before = copy.deepcopy(delegate.sentinel_state)
        connection = module._MigrationDiagnosticConnection(delegate)
        statement_hash = hashlib.sha256(statement_sql.encode("utf-8")).hexdigest()[:12]
        expected = f"live_e2e_migration_execute_1_40p01_pos_37_h_{statement_hash}"

        with self.assertRaises(RuntimeError) as caught:
            connection.execute(statement)

        rendered = str(caught.exception)
        self.assertEqual(delegate.calls, [statement])
        self.assertEqual(len(delegate.calls), 1)
        self.assertIs(delegate.calls[0], statement)
        self.assertEqual(connection.operation_index, 1)
        self.assertEqual(delegate.sentinel_state, sentinel_before)
        self.assertEqual(
            delegate.sentinel_state["opaque_bytes"],
            sentinel_before["opaque_bytes"],
        )
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)
        self.assertIs(caught.exception.__context__, driver_error)
        self.assertEqual(
            {
                "rendered": rendered,
                "sqlstate_access_count": driver_error.sqlstate_access_count,
                "diag_access_count": driver_error.diag_access_count,
                "statement_position_access_count": (diagnostic.statement_position_access_count),
                "statement_sql_access_count": statement.sql_access_count,
            },
            {
                "rendered": expected,
                "sqlstate_access_count": 1,
                "diag_access_count": 1,
                "statement_position_access_count": 1,
                "statement_sql_access_count": 1,
            },
        )
        for forbidden in (
            sensitive_accessor_error,
            str(driver_error),
            statement_sql,
            "DELETE FROM synthetic_tokens",
            "postgresql://",
            "secret",
            "credential",
            "/synthetic/",
            "backend=",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_migration_diagnostic_connection_bounds_first_statement_sql_accessor_failure(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_migration_first_statement_accessor",
            SCRIPT_PATH,
        )
        sensitive_accessor_error = (
            "first statement accessor failed "
            "dsn=postgresql://first_user:first_secret@example.test/formowl "
            "sql=DELETE FROM synthetic_tokens "
            "path=/synthetic/private/first-statement.sql "
            "backend=synthetic-primary credential=first-credential"
        )

        class DriverDiagnostic:
            def __init__(self) -> None:
                self.statement_position_access_count = 0

            @property
            def statement_position(self) -> int:
                self.statement_position_access_count += 1
                return 41

        diagnostic = DriverDiagnostic()

        class DriverError(RuntimeError):
            def __init__(self) -> None:
                super().__init__(
                    "driver execute failed "
                    "dsn=postgresql://driver_user:driver_secret@example.test/formowl "
                    "sql=SELECT private_token FROM synthetic_tokens "
                    "path=/synthetic/private/driver.sql "
                    "backend=synthetic-replica credential=driver-credential"
                )
                self.sqlstate_access_count = 0
                self.diag_access_count = 0

            @property
            def sqlstate(self) -> str:
                self.sqlstate_access_count += 1
                return "40P01"

            @property
            def diag(self) -> object:
                self.diag_access_count += 1
                return diagnostic

        driver_error = DriverError()

        class FirstAccessFailingStatement:
            def __init__(self) -> None:
                self.sql_access_count = 0

            @property
            def sql(self) -> str:
                self.sql_access_count += 1
                raise RuntimeError(sensitive_accessor_error)

        statement = FirstAccessFailingStatement()

        class Delegate:
            def __init__(self) -> None:
                self.calls: list[object] = []
                self.sentinel_state = {
                    "opaque_bytes": b"\x00\xfffirst-statement-delegate-state",
                    "value": ("unchanged", 41),
                }

            def execute(self, received_statement: object) -> None:
                self.calls.append(received_statement)
                raise driver_error

        delegate = Delegate()
        sentinel_before = copy.deepcopy(delegate.sentinel_state)
        connection = module._MigrationDiagnosticConnection(delegate)
        expected = "live_e2e_migration_execute_1_40p01_pos_41_h_unknown"

        with self.assertRaises(RuntimeError) as caught:
            connection.execute(statement)

        rendered = str(caught.exception)
        self.assertEqual(delegate.calls, [statement])
        self.assertEqual(len(delegate.calls), 1)
        self.assertIs(delegate.calls[0], statement)
        self.assertEqual(connection.operation_index, 1)
        self.assertEqual(delegate.sentinel_state, sentinel_before)
        self.assertEqual(
            delegate.sentinel_state["opaque_bytes"],
            sentinel_before["opaque_bytes"],
        )
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)
        self.assertIs(caught.exception.__context__, driver_error)
        self.assertEqual(
            {
                "rendered": rendered,
                "sqlstate_access_count": driver_error.sqlstate_access_count,
                "diag_access_count": driver_error.diag_access_count,
                "statement_position_access_count": (diagnostic.statement_position_access_count),
                "statement_sql_access_count": statement.sql_access_count,
            },
            {
                "rendered": expected,
                "sqlstate_access_count": 1,
                "diag_access_count": 1,
                "statement_position_access_count": 1,
                "statement_sql_access_count": 1,
            },
        )
        for forbidden in (
            sensitive_accessor_error,
            str(driver_error),
            "SELECT private_token FROM synthetic_tokens",
            "DELETE FROM synthetic_tokens",
            "postgresql://",
            "secret",
            "credential",
            "/synthetic/",
            "backend=",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_migration_diagnostic_connection_bounds_unpaired_surrogate_statement_hash_failure(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_migration_surrogate_statement",
            SCRIPT_PATH,
        )
        sensitive_marker = "synthetic-surrogate-sensitive-marker"
        statement_sql = "SELECT '" + chr(0xD800) + f"' /* {sensitive_marker} */"
        self.assertIs(type(statement_sql), str)

        class DriverDiagnostic:
            def __init__(self) -> None:
                self.statement_position_access_count = 0

            @property
            def statement_position(self) -> int:
                self.statement_position_access_count += 1
                return 47

        diagnostic = DriverDiagnostic()

        class DriverError(RuntimeError):
            def __init__(self) -> None:
                super().__init__(
                    "driver execute failed "
                    "dsn=postgresql://surrogate_user:surrogate_secret@example.test/formowl "
                    "sql=SELECT private_token FROM synthetic_tokens "
                    "path=/synthetic/private/surrogate-driver.sql "
                    "backend=synthetic-replica credential=surrogate-credential"
                )
                self.sqlstate_access_count = 0
                self.diag_access_count = 0

            @property
            def sqlstate(self) -> str:
                self.sqlstate_access_count += 1
                return "40P01"

            @property
            def diag(self) -> object:
                self.diag_access_count += 1
                return diagnostic

        driver_error = DriverError()

        class Statement:
            def __init__(self) -> None:
                self.sql_access_count = 0

            @property
            def sql(self) -> str:
                self.sql_access_count += 1
                return statement_sql

        statement = Statement()

        class Delegate:
            def __init__(self) -> None:
                self.calls: list[object] = []
                self.sentinel_state = {
                    "opaque_bytes": b"\x00\xffsurrogate-statement-delegate-state",
                    "value": ("unchanged", 47),
                }

            def execute(self, received_statement: object) -> None:
                self.calls.append(received_statement)
                raise driver_error

        delegate = Delegate()
        sentinel_before = copy.deepcopy(delegate.sentinel_state)
        connection = module._MigrationDiagnosticConnection(delegate)
        expected = "live_e2e_migration_execute_1_40p01_pos_47_h_unknown"

        with self.assertRaises(RuntimeError) as caught:
            connection.execute(statement)

        rendered = str(caught.exception)
        self.assertIs(type(caught.exception), RuntimeError)
        self.assertEqual(rendered, expected)
        self.assertEqual(delegate.calls, [statement])
        self.assertEqual(len(delegate.calls), 1)
        self.assertIs(delegate.calls[0], statement)
        self.assertEqual(connection.operation_index, 1)
        self.assertEqual(delegate.sentinel_state, sentinel_before)
        self.assertEqual(
            delegate.sentinel_state["opaque_bytes"],
            sentinel_before["opaque_bytes"],
        )
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)
        self.assertIs(caught.exception.__context__, driver_error)
        self.assertEqual(
            {
                "sqlstate_access_count": driver_error.sqlstate_access_count,
                "diag_access_count": driver_error.diag_access_count,
                "statement_position_access_count": (diagnostic.statement_position_access_count),
                "statement_sql_access_count": statement.sql_access_count,
            },
            {
                "sqlstate_access_count": 1,
                "diag_access_count": 1,
                "statement_position_access_count": 1,
                "statement_sql_access_count": 1,
            },
        )
        for forbidden in (
            sensitive_marker,
            str(driver_error),
            "SELECT private_token FROM synthetic_tokens",
            "postgresql://",
            "surrogate_secret",
            "surrogate-credential",
            "/synthetic/",
            "backend=",
            "UnicodeEncodeError",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_schema_readiness_failure_validates_exact_rows_in_order_without_hooks_or_mutation(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_schema_readiness",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()
        sensitive_marker = "synthetic-sensitive-schema.invalid"
        tables = tuple(module.runtime_module._REQUIRED_OAUTH_TABLES)
        column_groups = tuple(
            (table_name, tuple(column_names))
            for table_name, column_names in dict.items(
                module.runtime_module._REQUIRED_SCHEMA_COLUMNS
            )
        )
        constraints = tuple(module.runtime_module._REQUIRED_SCHEMA_CONSTRAINTS)
        indexes = tuple(module.runtime_module._REQUIRED_SCHEMA_INDEXES)
        constants_before = (
            id(module.runtime_module._REQUIRED_OAUTH_TABLES),
            tables,
            id(module.runtime_module._REQUIRED_SCHEMA_COLUMNS),
            column_groups,
            id(module.runtime_module._REQUIRED_SCHEMA_CONSTRAINTS),
            constraints,
            id(module.runtime_module._REQUIRED_SCHEMA_INDEXES),
            indexes,
        )

        expected_queries: list[object] = []
        valid_rows: list[object] = []
        for index, table_name in enumerate(tables, start=1):
            expected_queries.append(
                module.SQLStatement(
                    sql="SELECT to_regclass(%(table_name)s) AS relation",
                    parameters={"table_name": table_name},
                )
            )
            valid_rows.append({"relation": f"synthetic_table_{index}.invalid"})
        table_query_count = len(expected_queries)

        for table_name, column_names in column_groups:
            for column_name in column_names:
                expected_queries.append(
                    module.SQLStatement(
                        sql=(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = current_schema() "
                            "AND table_name = %(table_name)s "
                            "AND column_name = %(column_name)s"
                        ),
                        parameters={
                            "table_name": table_name,
                            "column_name": column_name,
                        },
                    )
                )
                valid_rows.append({"column_name": column_name})
        column_query_count = len(expected_queries) - table_query_count

        for index, item in enumerate(constraints, start=1):
            table_name, constraint_type, constraint_name, constraint_pattern = item
            constraint_name_clause = (
                "AND conname = %(constraint_name)s " if constraint_name is not None else ""
            )
            expected_queries.append(
                module.SQLStatement(
                    sql=(
                        "SELECT conname AS constraint_name FROM pg_constraint "
                        "WHERE conrelid = to_regclass(%(table_name)s) "
                        "AND contype = %(constraint_type)s "
                        f"{constraint_name_clause}"
                        "AND pg_get_constraintdef(oid) LIKE %(constraint_pattern)s"
                    ),
                    parameters={
                        "table_name": table_name,
                        "constraint_type": constraint_type,
                        "constraint_name": constraint_name,
                        "constraint_pattern": constraint_pattern,
                    },
                )
            )
            valid_rows.append(
                {"constraint_name": (constraint_name or f"synthetic_constraint_{index}.invalid")}
            )
        constraint_query_count = len(expected_queries) - table_query_count - column_query_count

        for index, relation_name in enumerate(indexes, start=1):
            expected_queries.append(
                module.SQLStatement(
                    sql="SELECT to_regclass(%(relation_name)s) AS relation",
                    parameters={"relation_name": relation_name},
                )
            )
            valid_rows.append({"relation": f"synthetic_index_{index}.invalid"})

        class MappingSubclass(dict[str, object]):
            def __init__(self, value: dict[str, object]) -> None:
                dict.__init__(self, value)
                self.hook_count = 0

            def _fail(self) -> None:
                self.hook_count += 1
                raise AssertionError(sensitive_marker)

            def get(self, *_: object, **__: object) -> object:
                self._fail()

            def __getitem__(self, _key: object) -> object:
                self._fail()

            def __iter__(self) -> object:
                self._fail()

        class StringSubclass(str):
            pass

        class EqualityStringProbe(str):
            def __new__(cls, value: str):
                instance = super().__new__(cls, value)
                instance.equality_count = 0
                return instance

            def _fail(self) -> bool:
                self.equality_count += 1
                raise AssertionError(sensitive_marker)

            def __eq__(self, _other: object) -> bool:
                return self._fail()

            def __ne__(self, _other: object) -> bool:
                return self._fail()

        def row_state(rows: tuple[object, ...]) -> tuple[object, ...]:
            state: list[object] = []
            for row in rows:
                if isinstance(row, dict):
                    state.append(
                        (
                            id(row),
                            type(row),
                            tuple(
                                (id(key), type(key), id(value), type(value))
                                for key, value in dict.items(row)
                            ),
                        )
                    )
                else:
                    state.append((id(row), type(row)))
            return tuple(state)

        def identity_state(value: object) -> tuple[tuple[str, int], ...]:
            return tuple(sorted((key, id(item)) for key, item in vars(value).items()))

        def exercise(
            rows: tuple[object, ...],
            *,
            expected_result: str,
            expected_query_count: int,
            probes: tuple[object, ...] = (),
            query_error: RuntimeError | None = None,
        ) -> str:
            query_log: list[object] = []
            query_position = 0
            rows_before = row_state(rows)
            probe_states_before = tuple((probe, copy.deepcopy(vars(probe))) for probe in probes)
            repository_sentinel = {"phase": "before", "items": ["unchanged"]}
            connection_sentinel = {"phase": "before", "items": ["unchanged"]}
            write = mock.Mock(side_effect=AssertionError(sensitive_marker))

            def query_one(statement: object) -> object:
                nonlocal query_position
                query_log.append(statement)
                current_position = query_position
                query_position += 1
                if query_error is not None and current_position == 0:
                    raise query_error
                return rows[current_position]

            connection = SimpleNamespace(
                query_one=query_one,
                execute=write,
                sentinel_state=connection_sentinel,
            )
            repository = SimpleNamespace(
                connection=connection,
                sentinel_state=repository_sentinel,
            )
            repository_identity_before = identity_state(repository)
            connection_identity_before = identity_state(connection)
            repository_sentinel_before = copy.deepcopy(repository_sentinel)
            connection_sentinel_before = copy.deepcopy(connection_sentinel)

            result = module._schema_readiness_failure(repository)

            self.assertEqual(result, expected_result)
            self.assertEqual(query_position, expected_query_count)
            self.assertEqual(
                query_log,
                expected_queries[:expected_query_count],
            )
            write.assert_not_called()
            self.assertEqual(row_state(rows), rows_before)
            self.assertEqual(identity_state(repository), repository_identity_before)
            self.assertEqual(identity_state(connection), connection_identity_before)
            self.assertEqual(repository_sentinel, repository_sentinel_before)
            self.assertEqual(connection_sentinel, connection_sentinel_before)
            for probe, state_before in probe_states_before:
                self.assertEqual(vars(probe), state_before)
            current_constants = (
                id(module.runtime_module._REQUIRED_OAUTH_TABLES),
                tuple(module.runtime_module._REQUIRED_OAUTH_TABLES),
                id(module.runtime_module._REQUIRED_SCHEMA_COLUMNS),
                tuple(
                    (table_name, tuple(column_names))
                    for table_name, column_names in dict.items(
                        module.runtime_module._REQUIRED_SCHEMA_COLUMNS
                    )
                ),
                id(module.runtime_module._REQUIRED_SCHEMA_CONSTRAINTS),
                tuple(module.runtime_module._REQUIRED_SCHEMA_CONSTRAINTS),
                id(module.runtime_module._REQUIRED_SCHEMA_INDEXES),
                tuple(module.runtime_module._REQUIRED_SCHEMA_INDEXES),
            )
            self.assertEqual(current_constants, constants_before)
            return result

        valid_rows_tuple = tuple(valid_rows)
        self.assertEqual(
            exercise(
                valid_rows_tuple,
                expected_result="unknown",
                expected_query_count=len(expected_queries),
            ),
            "unknown",
        )

        table_rows = (
            MappingSubclass({"relation": "synthetic_mapping.invalid"}),
            {"relation": 0},
            {"relation": False},
            {"relation": object()},
            {"relation": ""},
            {"relation": StringSubclass("synthetic_subclass.invalid")},
        )
        for position, malformed_row in enumerate(table_rows, start=1):
            with self.subTest(family="table", position=position):
                rows = list(valid_rows_tuple)
                rows[position - 1] = malformed_row
                probes = (malformed_row,) if isinstance(malformed_row, MappingSubclass) else ()
                exercise(
                    tuple(rows),
                    expected_result=f"table_{position}",
                    expected_query_count=position,
                    probes=probes,
                )

        column_values: tuple[object, ...] = (
            MappingSubclass({"column_name": column_groups[0][1][0]}),
            object(),
            "",
            StringSubclass(column_groups[0][1][3]),
            EqualityStringProbe(column_groups[0][1][4]),
            "synthetic_wrong_column",
        )
        for position, malformed_value in enumerate(column_values, start=1):
            with self.subTest(family="column", position=position):
                rows = list(valid_rows_tuple)
                malformed_row = (
                    malformed_value
                    if isinstance(malformed_value, MappingSubclass)
                    else {"column_name": malformed_value}
                )
                rows[table_query_count + position - 1] = malformed_row
                probes = (
                    (malformed_value,)
                    if isinstance(
                        malformed_value,
                        (MappingSubclass, EqualityStringProbe),
                    )
                    else ()
                )
                exercise(
                    tuple(rows),
                    expected_result=f"column_{position}",
                    expected_query_count=table_query_count + position,
                    probes=probes,
                )

        constraint_values: tuple[object, ...] = (
            MappingSubclass({"constraint_name": "synthetic_mapping.invalid"}),
            object(),
            "",
            StringSubclass("synthetic_subclass.invalid"),
        )
        constraint_offset = table_query_count + column_query_count
        for position, malformed_value in enumerate(constraint_values, start=1):
            with self.subTest(family="constraint", position=position):
                rows = list(valid_rows_tuple)
                malformed_row = (
                    malformed_value
                    if isinstance(malformed_value, MappingSubclass)
                    else {"constraint_name": malformed_value}
                )
                rows[constraint_offset + position - 1] = malformed_row
                probes = (malformed_value,) if isinstance(malformed_value, MappingSubclass) else ()
                exercise(
                    tuple(rows),
                    expected_result=f"constraint_{position}",
                    expected_query_count=constraint_offset + position,
                    probes=probes,
                )

        index_rows = (
            MappingSubclass({"relation": "synthetic_mapping.invalid"}),
            {"relation": 0},
            {"relation": False},
            {"relation": object()},
            {"relation": ""},
            {"relation": StringSubclass("synthetic_subclass.invalid")},
        )
        index_offset = constraint_offset + constraint_query_count
        for position, malformed_row in enumerate(index_rows, start=1):
            with self.subTest(family="index", position=position):
                rows = list(valid_rows_tuple)
                rows[index_offset + position - 1] = malformed_row
                probes = (malformed_row,) if isinstance(malformed_row, MappingSubclass) else ()
                exercise(
                    tuple(rows),
                    expected_result=f"index_{position}",
                    expected_query_count=index_offset + position,
                    probes=probes,
                )

        query_error = RuntimeError(
            f"{sensitive_marker} "
            "url=https://credential.invalid/private "
            "path=/tmp/synthetic/private.sql "
            "sql=SELECT credential FROM synthetic_secrets"
        )
        query_error_args_before = query_error.args
        exception_result = exercise(
            valid_rows_tuple,
            expected_result="exception_runtimeerror",
            expected_query_count=1,
            query_error=query_error,
        )
        self.assertEqual(query_error.args, query_error_args_before)
        self.assertRegex(exception_result, r"^exception_[a-z0-9_]{1,32}$")
        for forbidden in (
            sensitive_marker,
            "https://",
            "credential.invalid",
            "/tmp/",
            "SELECT ",
            "synthetic_secrets",
        ):
            self.assertNotIn(forbidden, exception_result)

    def test_preflight_with_safe_diagnostics_accepts_exact_ready_payload_without_diagnostics(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_preflight_success",
            SCRIPT_PATH,
        )
        readiness_keys = (
            "runtime",
            "database",
            "schema",
            "configuration",
            "oauth_callback",
            "signing_key",
            "google_oidc",
            "upload_store",
        )
        checks = {key: True for key in readiness_keys}
        payload = {
            "status": "ready",
            "mode": "production_exact",
            "checks": checks,
        }
        payload_before = list(dict.items(payload))
        checks_before = list(dict.items(checks))
        preflight = mock.AsyncMock(return_value=payload)
        repository_state = {"phase": "before", "items": ["unchanged"]}
        google_state = {"phase": "before", "items": ["unchanged"]}
        http_state = {"phase": "before", "items": ["unchanged"]}
        runtime_state = {"phase": "before", "items": ["unchanged"]}
        repository = SimpleNamespace(sentinel_state=repository_state)
        google_client = SimpleNamespace(
            load_provider_metadata=mock.AsyncMock(
                side_effect=AssertionError("ready payload must not run diagnostics")
            ),
            load_jwks=mock.AsyncMock(
                side_effect=AssertionError("ready payload must not run diagnostics")
            ),
            sentinel_state=google_state,
        )
        http_client = SimpleNamespace(
            request_history=[
                {
                    "method": "SYNTHETIC",
                    "path": "/unchanged",
                    "status": 299,
                }
            ],
            sentinel_state=http_state,
        )
        runtime = SimpleNamespace(
            preflight=preflight,
            repository=repository,
            google_client=google_client,
            http_client=http_client,
            sentinel_state=runtime_state,
        )
        runtime_keys_before = set(vars(runtime))
        repository_keys_before = set(vars(repository))
        google_keys_before = set(vars(google_client))
        http_keys_before = set(vars(http_client))
        repository_state_before = copy.deepcopy(repository_state)
        google_state_before = copy.deepcopy(google_state)
        http_state_before = copy.deepcopy(http_state)
        runtime_state_before = copy.deepcopy(runtime_state)
        history_before = copy.deepcopy(http_client.request_history)

        with mock.patch.object(
            module,
            "_schema_readiness_failure",
            side_effect=AssertionError("ready payload must not run diagnostics"),
        ) as schema_diagnostic:
            returned = asyncio.run(
                module._preflight_with_safe_diagnostics(
                    runtime,
                    stage="initial",
                )
            )

        self.assertIsNone(returned)
        self.assertIs(type(payload), dict)
        self.assertEqual(tuple(dict.keys(payload)), ("status", "mode", "checks"))
        self.assertTrue(all(type(key) is str for key in dict.keys(payload)))
        self.assertIs(type(checks), dict)
        self.assertEqual(tuple(dict.keys(checks)), readiness_keys)
        self.assertTrue(all(type(key) is str for key in dict.keys(checks)))
        self.assertTrue(all(type(value) is bool for value in dict.values(checks)))
        self.assertTrue(all(value is True for value in dict.values(checks)))
        preflight.assert_awaited_once_with()
        preflight.assert_called_once_with()
        schema_diagnostic.assert_not_called()
        google_client.load_provider_metadata.assert_not_awaited()
        google_client.load_provider_metadata.assert_not_called()
        google_client.load_jwks.assert_not_awaited()
        google_client.load_jwks.assert_not_called()
        self.assertEqual(list(dict.items(payload)), payload_before)
        self.assertEqual(list(dict.items(checks)), checks_before)
        self.assertEqual(http_client.request_history, history_before)
        self.assertIs(runtime.repository, repository)
        self.assertIs(runtime.google_client, google_client)
        self.assertIs(runtime.http_client, http_client)
        self.assertIs(runtime.sentinel_state, runtime_state)
        self.assertIs(repository.sentinel_state, repository_state)
        self.assertIs(google_client.sentinel_state, google_state)
        self.assertIs(http_client.sentinel_state, http_state)
        self.assertEqual(set(vars(runtime)), runtime_keys_before)
        self.assertEqual(set(vars(repository)), repository_keys_before)
        self.assertEqual(set(vars(google_client)), google_keys_before)
        self.assertEqual(set(vars(http_client)), http_keys_before)
        self.assertEqual(repository.sentinel_state, repository_state_before)
        self.assertEqual(google_client.sentinel_state, google_state_before)
        self.assertEqual(http_client.sentinel_state, http_state_before)
        self.assertEqual(runtime.sentinel_state, runtime_state_before)

    def test_preflight_with_safe_diagnostics_rejects_ready_payload_with_invalid_checks(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_preflight_invalid_checks",
            SCRIPT_PATH,
        )
        readiness_keys = (
            "runtime",
            "database",
            "schema",
            "configuration",
            "oauth_callback",
            "signing_key",
            "google_oidc",
            "upload_store",
        )
        valid_checks = {key: True for key in readiness_keys}
        missing_checks = dict(valid_checks)
        missing_checks.pop("upload_store")
        extra_checks = {**valid_checks, "unexpected": True}
        wrong_type_checks = {**valid_checks, "runtime": 1}
        cases = (
            (
                "ordinary_false",
                "ready",
                "restart",
                {**valid_checks, "runtime": False},
                "live_e2e_restart_preflight_runtime",
            ),
            (
                "missing_readiness_key",
                "ready",
                "restart",
                missing_checks,
                "live_e2e_restart_preflight_unknown",
            ),
            (
                "extra_readiness_key",
                "ready",
                "restart",
                extra_checks,
                "live_e2e_restart_preflight_unknown",
            ),
            (
                "wrong_type_readiness_value",
                "ready",
                "restart",
                wrong_type_checks,
                "live_e2e_restart_preflight_unknown",
            ),
            (
                "non_ready_all_checks_true",
                "not_ready",
                "initial",
                valid_checks,
                "live_e2e_initial_preflight_unknown",
            ),
        )

        for case_name, status, stage, checks, expected_error in cases:
            with self.subTest(case=case_name):
                payload = {
                    "status": status,
                    "mode": "production_exact",
                    "checks": checks,
                }
                if case_name == "non_ready_all_checks_true":
                    self.assertIs(type(payload), dict)
                    self.assertEqual(
                        tuple(dict.keys(payload)),
                        ("status", "mode", "checks"),
                    )
                    self.assertTrue(all(type(key) is str for key in dict.keys(payload)))
                    self.assertIs(type(status), str)
                    self.assertNotEqual(status, "ready")
                    self.assertIs(type(checks), dict)
                    self.assertEqual(tuple(dict.keys(checks)), readiness_keys)
                    self.assertTrue(all(type(key) is str for key in dict.keys(checks)))
                    self.assertTrue(
                        all(type(value) is bool and value is True for value in dict.values(checks))
                    )
                payload_before = list(dict.items(payload))
                checks_before = list(dict.items(checks))
                preflight = mock.AsyncMock(return_value=payload)
                repository_state = {"phase": "before", "items": ["unchanged"]}
                google_state = {"phase": "before", "items": ["unchanged"]}
                http_state = {"phase": "before", "items": ["unchanged"]}
                runtime_state = {"phase": "before", "items": ["unchanged"]}
                repository = SimpleNamespace(sentinel_state=repository_state)
                google_client = SimpleNamespace(
                    load_provider_metadata=mock.AsyncMock(
                        side_effect=AssertionError("invalid checks must not run Google diagnostics")
                    ),
                    load_jwks=mock.AsyncMock(
                        side_effect=AssertionError("invalid checks must not run Google diagnostics")
                    ),
                    sentinel_state=google_state,
                )
                request_history = [
                    {
                        "method": "SYNTHETIC",
                        "path": "/unchanged",
                        "status": 299,
                    }
                ]
                request_history_access = mock.Mock(return_value=request_history)

                class HttpClient:
                    def __init__(self) -> None:
                        self.sentinel_state = http_state

                    @property
                    def request_history(self) -> list[dict[str, object]]:
                        return request_history_access()

                http_client = HttpClient()
                runtime = SimpleNamespace(
                    preflight=preflight,
                    repository=repository,
                    google_client=google_client,
                    http_client=http_client,
                    sentinel_state=runtime_state,
                )
                runtime_keys_before = set(vars(runtime))
                repository_keys_before = set(vars(repository))
                google_keys_before = set(vars(google_client))
                http_keys_before = set(vars(http_client))
                repository_state_before = copy.deepcopy(repository_state)
                google_state_before = copy.deepcopy(google_state)
                http_state_before = copy.deepcopy(http_state)
                runtime_state_before = copy.deepcopy(runtime_state)
                history_before = copy.deepcopy(request_history)

                with mock.patch.object(
                    module,
                    "_schema_readiness_failure",
                    side_effect=AssertionError("invalid checks must not run schema diagnostics"),
                ) as schema_diagnostic:
                    with self.assertRaises(RuntimeError) as raised:
                        asyncio.run(
                            module._preflight_with_safe_diagnostics(
                                runtime,
                                stage=stage,
                            )
                        )

                self.assertIs(type(raised.exception), RuntimeError)
                self.assertEqual(str(raised.exception), expected_error)
                self.assertIsNone(raised.exception.__cause__)
                preflight.assert_awaited_once_with()
                preflight.assert_called_once_with()
                schema_diagnostic.assert_not_called()
                google_client.load_provider_metadata.assert_not_awaited()
                google_client.load_provider_metadata.assert_not_called()
                google_client.load_jwks.assert_not_awaited()
                google_client.load_jwks.assert_not_called()
                request_history_access.assert_not_called()
                self.assertEqual(list(dict.items(payload)), payload_before)
                self.assertEqual(list(dict.items(checks)), checks_before)
                self.assertEqual(http_client.request_history, history_before)
                self.assertIs(runtime.repository, repository)
                self.assertIs(runtime.google_client, google_client)
                self.assertIs(runtime.http_client, http_client)
                self.assertIs(runtime.sentinel_state, runtime_state)
                self.assertIs(repository.sentinel_state, repository_state)
                self.assertIs(google_client.sentinel_state, google_state)
                self.assertIs(http_client.sentinel_state, http_state)
                self.assertEqual(set(vars(runtime)), runtime_keys_before)
                self.assertEqual(set(vars(repository)), repository_keys_before)
                self.assertEqual(set(vars(google_client)), google_keys_before)
                self.assertEqual(set(vars(http_client)), http_keys_before)
                self.assertEqual(repository.sentinel_state, repository_state_before)
                self.assertEqual(google_client.sentinel_state, google_state_before)
                self.assertEqual(http_client.sentinel_state, http_state_before)
                self.assertEqual(runtime.sentinel_state, runtime_state_before)

    def test_preflight_with_safe_diagnostics_rejects_hooked_payloads_without_hooks(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_preflight_hook_guards",
            SCRIPT_PATH,
        )
        sensitive_marker = "synthetic-sensitive-preflight-hook-marker"
        readiness_keys = (
            "runtime",
            "database",
            "schema",
            "configuration",
            "oauth_callback",
            "signing_key",
            "google_oidc",
            "upload_store",
        )

        class HookedDict(dict[str, object]):
            def __init__(self, payload: dict[str, object]) -> None:
                super().__init__(payload)
                self.call_counts = {
                    "get": 0,
                    "items": 0,
                    "keys": 0,
                    "getitem": 0,
                    "iter": 0,
                    "bool": 0,
                }
                self.sentinel_state = {
                    "phase": "before",
                    "items": ["unchanged"],
                }

            def _fail(self, name: str) -> None:
                self.call_counts[name] += 1
                self.sentinel_state["phase"] = f"{name}-called"
                raise AssertionError(sensitive_marker)

            def get(self, *_: object, **__: object) -> object:
                self._fail("get")

            def items(self) -> object:
                self._fail("items")

            def keys(self) -> object:
                self._fail("keys")

            def __getitem__(self, _key: object) -> object:
                self._fail("getitem")

            def __iter__(self) -> object:
                self._fail("iter")

            def __bool__(self) -> bool:
                self._fail("bool")

        class KeyProbe(str):
            def __new__(cls, value: str):
                instance = super().__new__(cls, value)
                instance.armed = False
                instance.hash_call_count = 0
                instance.equality_call_count = 0
                instance.sentinel_state = {
                    "phase": "before",
                    "items": ["unchanged"],
                }
                return instance

            def __hash__(self) -> int:
                if self.armed:
                    self.hash_call_count += 1
                    self.sentinel_state["phase"] = "hash-called"
                    raise AssertionError(sensitive_marker)
                return str.__hash__(self)

            def __eq__(self, other: object) -> bool:
                if self.armed:
                    self.equality_call_count += 1
                    self.sentinel_state["phase"] = "equality-called"
                    raise AssertionError(sensitive_marker)
                return str.__eq__(self, other)

        class TextTruthinessProbe(str):
            def __new__(cls, value: str):
                instance = super().__new__(cls, value)
                instance.bool_call_count = 0
                instance.sentinel_state = {
                    "phase": "before",
                    "items": ["unchanged"],
                }
                return instance

            def __bool__(self) -> bool:
                self.bool_call_count += 1
                self.sentinel_state["phase"] = "bool-called"
                raise AssertionError(sensitive_marker)

        class ValueTruthinessProbe:
            def __init__(self) -> None:
                self.bool_call_count = 0
                self.sentinel_state = {
                    "phase": "before",
                    "items": ["unchanged"],
                }

            def __bool__(self) -> bool:
                self.bool_call_count += 1
                self.sentinel_state["phase"] = "bool-called"
                raise AssertionError(sensitive_marker)

        def exact_checks() -> dict[str, object]:
            return {key: True for key in readiness_keys}

        def value_state(value: object) -> tuple[object, ...]:
            if isinstance(value, str):
                return ("str", type(value), str.encode(value))
            if type(value) is bool:
                return ("bool", value)
            if type(value) is int:
                return ("int", value)
            return ("object", type(value), id(value))

        def mapping_state(value: dict[object, object]) -> tuple[object, ...]:
            return (
                type(value),
                tuple(
                    (
                        id(key),
                        type(key),
                        str.encode(key) if isinstance(key, str) else id(key),
                        id(item),
                        value_state(item),
                    )
                    for key, item in dict.items(value)
                ),
            )

        hooked_payload_checks = exact_checks()
        hooked_payload = HookedDict(
            {
                "status": "ready",
                "mode": "production_exact",
                "checks": hooked_payload_checks,
            }
        )
        hooked_checks = HookedDict(exact_checks())
        payload_with_hooked_checks = {
            "status": "ready",
            "mode": "production_exact",
            "checks": hooked_checks,
        }
        payload_key_probe = KeyProbe("status")
        payload_with_key_probe = {
            payload_key_probe: "ready",
            "mode": "production_exact",
            "checks": exact_checks(),
        }
        payload_key_probe.armed = True
        checks_key_probe = KeyProbe("runtime")
        checks_with_key_probe = {
            checks_key_probe: True,
            **{key: True for key in readiness_keys if key != "runtime"},
        }
        checks_key_probe.armed = True
        payload_with_checks_key_probe = {
            "status": "not_ready",
            "mode": "production_exact",
            "checks": checks_with_key_probe,
        }
        status_probe = TextTruthinessProbe("ready")
        payload_with_status_probe = {
            "status": status_probe,
            "mode": "production_exact",
            "checks": exact_checks(),
        }
        mode_probe = TextTruthinessProbe("production_exact")
        payload_with_mode_probe = {
            "status": "ready",
            "mode": mode_probe,
            "checks": exact_checks(),
        }
        value_probe = ValueTruthinessProbe()
        checks_with_value_probe = {**exact_checks(), "runtime": value_probe}
        payload_with_value_probe = {
            "status": "ready",
            "mode": "production_exact",
            "checks": checks_with_value_probe,
        }
        cases = (
            (
                "payload_dict_subclass",
                hooked_payload,
                hooked_payload_checks,
                (hooked_payload,),
            ),
            (
                "checks_dict_subclass",
                payload_with_hooked_checks,
                hooked_checks,
                (hooked_checks,),
            ),
            (
                "payload_key_subclass",
                payload_with_key_probe,
                dict.__getitem__(payload_with_key_probe, "checks"),
                (payload_key_probe,),
            ),
            (
                "checks_key_subclass",
                payload_with_checks_key_probe,
                checks_with_key_probe,
                (checks_key_probe,),
            ),
            (
                "status_string_subclass",
                payload_with_status_probe,
                dict.__getitem__(payload_with_status_probe, "checks"),
                (status_probe,),
            ),
            (
                "mode_string_subclass",
                payload_with_mode_probe,
                dict.__getitem__(payload_with_mode_probe, "checks"),
                (mode_probe,),
            ),
            (
                "wrong_type_truthiness_value",
                payload_with_value_probe,
                checks_with_value_probe,
                (value_probe,),
            ),
        )

        for case_name, payload, checks, probes in cases:
            with self.subTest(case=case_name):
                payload_before = mapping_state(payload)
                checks_before = mapping_state(checks)
                probe_attrs_before = tuple((probe, copy.deepcopy(vars(probe))) for probe in probes)
                preflight = mock.AsyncMock(return_value=payload)
                repository_state = {"phase": "before", "items": ["unchanged"]}
                google_state = {"phase": "before", "items": ["unchanged"]}
                http_state = {"phase": "before", "items": ["unchanged"]}
                runtime_state = {"phase": "before", "items": ["unchanged"]}
                repository = SimpleNamespace(sentinel_state=repository_state)
                google_client = SimpleNamespace(
                    load_provider_metadata=mock.AsyncMock(
                        side_effect=AssertionError(sensitive_marker)
                    ),
                    load_jwks=mock.AsyncMock(side_effect=AssertionError(sensitive_marker)),
                    sentinel_state=google_state,
                )
                http_client = SimpleNamespace(
                    request_history=[
                        {
                            "method": "SYNTHETIC",
                            "path": "/unchanged",
                            "status": 299,
                        }
                    ],
                    sentinel_state=http_state,
                )
                runtime = SimpleNamespace(
                    preflight=preflight,
                    repository=repository,
                    google_client=google_client,
                    http_client=http_client,
                    sentinel_state=runtime_state,
                )
                runtime_keys_before = set(vars(runtime))
                repository_keys_before = set(vars(repository))
                google_keys_before = set(vars(google_client))
                http_keys_before = set(vars(http_client))
                repository_state_before = copy.deepcopy(repository_state)
                google_state_before = copy.deepcopy(google_state)
                http_state_before = copy.deepcopy(http_state)
                runtime_state_before = copy.deepcopy(runtime_state)
                history_before = copy.deepcopy(http_client.request_history)

                with mock.patch.object(
                    module,
                    "_schema_readiness_failure",
                    side_effect=AssertionError(sensitive_marker),
                ) as schema_diagnostic:
                    with self.assertRaises(RuntimeError) as raised:
                        asyncio.run(
                            module._preflight_with_safe_diagnostics(
                                runtime,
                                stage="expiry",
                            )
                        )

                self.assertIs(type(raised.exception), RuntimeError)
                self.assertEqual(
                    str(raised.exception),
                    "live_e2e_expiry_preflight_unknown",
                )
                self.assertNotIn(sensitive_marker, str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)
                preflight.assert_awaited_once_with()
                preflight.assert_called_once_with()
                schema_diagnostic.assert_not_called()
                google_client.load_provider_metadata.assert_not_awaited()
                google_client.load_provider_metadata.assert_not_called()
                google_client.load_jwks.assert_not_awaited()
                google_client.load_jwks.assert_not_called()
                self.assertEqual(mapping_state(payload), payload_before)
                self.assertEqual(mapping_state(checks), checks_before)
                for probe, attrs_before in probe_attrs_before:
                    self.assertEqual(vars(probe), attrs_before)
                self.assertEqual(http_client.request_history, history_before)
                self.assertIs(runtime.repository, repository)
                self.assertIs(runtime.google_client, google_client)
                self.assertIs(runtime.http_client, http_client)
                self.assertIs(runtime.sentinel_state, runtime_state)
                self.assertIs(repository.sentinel_state, repository_state)
                self.assertIs(google_client.sentinel_state, google_state)
                self.assertIs(http_client.sentinel_state, http_state)
                self.assertEqual(set(vars(runtime)), runtime_keys_before)
                self.assertEqual(set(vars(repository)), repository_keys_before)
                self.assertEqual(set(vars(google_client)), google_keys_before)
                self.assertEqual(set(vars(http_client)), http_keys_before)
                self.assertEqual(repository.sentinel_state, repository_state_before)
                self.assertEqual(google_client.sentinel_state, google_state_before)
                self.assertEqual(http_client.sentinel_state, http_state_before)
                self.assertEqual(runtime.sentinel_state, runtime_state_before)

    def test_mcp_authorization_audit_lineage_rejects_equality_spoofs_without_mutation(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_audit_lineage",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()

        class EqualitySpoof(str):
            equality_call_count = 0

            def __eq__(self, _other: object) -> bool:
                type(self).equality_call_count += 1
                return True

            def __ne__(self, _other: object) -> bool:
                type(self).equality_call_count += 1
                return False

        class MappingKeySpoof(str):
            hash_call_count = 0
            equality_call_count = 0

            def __hash__(self) -> int:
                type(self).hash_call_count += 1
                return str.__hash__(self)

            def __eq__(self, other: object) -> bool:
                type(self).equality_call_count += 1
                return str.__eq__(self, other)

            def __ne__(self, other: object) -> bool:
                type(self).equality_call_count += 1
                return str.__ne__(self, other)

            @classmethod
            def reset_counts(cls) -> None:
                cls.hash_call_count = 0
                cls.equality_call_count = 0

        class StatefulRow(dict[str, object]):
            get_call_count = 0

            def get(self, _key: str, _default: object = None) -> object:
                type(self).get_call_count += 1
                raise RuntimeError("sensitive stateful row access")

        token_session = SimpleNamespace(
            user_id="user_expected",
            current_workspace_id="workspace_expected",
            external_identity_id="external_expected",
            client_id="client_expected",
            token_session_id="session_expected",
        )
        expected_token_binding = {
            "token_session_id": token_session.token_session_id,
            "user_id": token_session.user_id,
            "current_workspace_id": token_session.current_workspace_id,
        }
        expected_lineage = {
            "actor_user_id": token_session.user_id,
            "workspace_id": token_session.current_workspace_id,
            "external_identity_id": token_session.external_identity_id,
            "oauth_client_id": token_session.client_id,
            "oauth_token_session_id": token_session.token_session_id,
        }
        decisions = (
            (
                "mcp_authorization_allowed",
                "whoami",
                "tool_authorized",
                "ok",
            ),
            (
                "mcp_authorization_allowed",
                "open_upload_session",
                "tool_authorized",
                "ok",
            ),
            (
                "mcp_authorization_denied",
                "open_upload_session",
                "invalid_tool_arguments",
                "permission_denied",
            ),
            (
                "mcp_authorization_denied",
                "open_upload_session",
                "invalid_tool_arguments",
                "permission_denied",
            ),
        )

        def build_rows(*, spoof_lineage: bool) -> list[dict[str, object]]:
            rows: list[dict[str, object]] = []
            for index, (action, target_id, reason_code, status) in enumerate(
                decisions,
                start=1,
            ):
                lineage = (
                    {key: EqualitySpoof(f"wrong_{key}_{index}") for key in expected_lineage}
                    if spoof_lineage
                    else dict(expected_lineage)
                )
                rows.append(
                    {
                        "action": action,
                        "target_id": target_id,
                        **lineage,
                        "request_id": f"request_{index}",
                        "tool_call_id": f"tool_call_{index}",
                        "reason_code": reason_code,
                        "status": status,
                    }
                )
            return rows

        def spoof_mapping_keys(
            payload: dict[str, object],
        ) -> dict[str, object]:
            return {MappingKeySpoof(key): value for key, value in dict.items(payload)}

        def rows_state(
            rows: list[dict[str, object]],
        ) -> tuple[
            tuple[
                tuple[type[object], bytes, type[object], bytes],
                ...,
            ],
            ...,
        ]:
            return tuple(
                tuple(
                    (
                        type(key),
                        str.encode(key),
                        type(value),
                        str.encode(value),
                    )
                    for key, value in dict.items(row)
                )
                for row in rows
            )

        class Connection:
            def __init__(self, rows: list[dict[str, object]]) -> None:
                self.rows = rows
                self.query_count = 0
                self.write_count = 0
                self.sentinel_state = {"opaque_bytes": b"\x00\xffconnection"}

            def query_all(self, _statement: object) -> list[dict[str, object]]:
                self.query_count += 1
                return self.rows

            def execute(self, _statement: object) -> None:
                self.write_count += 1
                raise AssertionError("audit lineage validation must not write")

        class Repository:
            def __init__(self, rows: list[dict[str, object]]) -> None:
                self.connection = Connection(rows)
                self.token_session_read_count = 0
                self.write_count = 0
                self.sentinel_state = {"opaque_bytes": b"\x00\xffrepository"}

            def get_token_session(self, token_session_id: str) -> object:
                self.token_session_read_count += 1
                self.asserted_token_session_id = token_session_id
                return token_session

            def append_audit_log(self, _audit: object) -> None:
                self.write_count += 1
                raise AssertionError("audit lineage validation must not write")

        def assert_read_only_state(
            repository: Repository,
            *,
            rows_before: tuple[
                tuple[
                    tuple[type[object], bytes, type[object], bytes],
                    ...,
                ],
                ...,
            ],
            repository_before: dict[str, bytes],
            connection_before: dict[str, bytes],
            expected_token_session_read_count: int = 1,
            expected_query_count: int = 1,
            expected_asserted_token_session_id: str | None = "session_expected",
        ) -> None:
            self.assertEqual(rows_state(repository.connection.rows), rows_before)
            self.assertEqual(repository.sentinel_state, repository_before)
            self.assertEqual(repository.connection.sentinel_state, connection_before)
            self.assertEqual(
                repository.token_session_read_count,
                expected_token_session_read_count,
            )
            self.assertEqual(repository.connection.query_count, expected_query_count)
            self.assertEqual(repository.write_count, 0)
            self.assertEqual(repository.connection.write_count, 0)
            if expected_asserted_token_session_id is None:
                self.assertFalse(hasattr(repository, "asserted_token_session_id"))
            else:
                self.assertEqual(
                    repository.asserted_token_session_id,
                    expected_asserted_token_session_id,
                )

        def assert_token_binding_rejected(
            name: str,
            token_binding: dict[str, object],
            *,
            expected_token_session_read_count: int,
            expected_query_count: int,
            expected_asserted_token_session_id: str | None,
        ) -> None:
            rows = build_rows(spoof_lineage=False)
            repository = Repository(rows)
            rows_before = rows_state(rows)
            binding_before = rows_state([token_binding])
            repository_before = copy.deepcopy(repository.sentinel_state)
            connection_before = copy.deepcopy(repository.connection.sentinel_state)
            EqualitySpoof.equality_call_count = 0
            try:
                module._validate_mcp_authorization_audit_lineage(
                    SimpleNamespace(repository=repository),
                    token_binding=token_binding,
                )
            except RuntimeError as exc:
                self.assertEqual(
                    str(exc),
                    "live_e2e_mcp_audit_lineage_failed",
                )
            else:
                self.fail(
                    f"{name} token binding was accepted after "
                    f"{repository.token_session_read_count} token-session reads, "
                    f"{repository.connection.query_count} audit queries, and "
                    f"{EqualitySpoof.equality_call_count} spoofed equality calls"
                )
            self.assertEqual(EqualitySpoof.equality_call_count, 0)
            self.assertEqual(rows_state([token_binding]), binding_before)
            assert_read_only_state(
                repository,
                rows_before=rows_before,
                repository_before=repository_before,
                connection_before=connection_before,
                expected_token_session_read_count=expected_token_session_read_count,
                expected_query_count=expected_query_count,
                expected_asserted_token_session_id=expected_asserted_token_session_id,
            )
            self.assertEqual(EqualitySpoof.equality_call_count, 0)

        plain_rows = build_rows(spoof_lineage=False)
        plain_repository = Repository(plain_rows)
        plain_rows_before = rows_state(plain_rows)
        plain_repository_before = copy.deepcopy(plain_repository.sentinel_state)
        plain_connection_before = copy.deepcopy(plain_repository.connection.sentinel_state)
        plain_result = module._validate_mcp_authorization_audit_lineage(
            SimpleNamespace(repository=plain_repository),
            token_binding=expected_token_binding,
        )
        self.assertEqual(
            plain_result,
            {
                "allowed_count": 2,
                "denied_count": 2,
                "lineage_complete_count": 4,
                "distinct_tool_call_count": 4,
            },
        )
        assert_read_only_state(
            plain_repository,
            rows_before=plain_rows_before,
            repository_before=plain_repository_before,
            connection_before=plain_connection_before,
        )

        malformed_binding_cases = (
            (
                "non_plain_user_id",
                {
                    **expected_token_binding,
                    "user_id": EqualitySpoof("sensitive_non_plain_user"),
                },
            ),
            (
                "non_plain_current_workspace_id",
                {
                    **expected_token_binding,
                    "current_workspace_id": EqualitySpoof("sensitive_non_plain_workspace"),
                },
            ),
            (
                "empty_user_id",
                {
                    **expected_token_binding,
                    "user_id": "",
                },
            ),
            (
                "empty_current_workspace_id",
                {
                    **expected_token_binding,
                    "current_workspace_id": "",
                },
            ),
        )
        for name, token_binding in malformed_binding_cases:
            with self.subTest(token_binding_case=name):
                assert_token_binding_rejected(
                    name,
                    token_binding,
                    expected_token_session_read_count=0,
                    expected_query_count=0,
                    expected_asserted_token_session_id=None,
                )

        with self.subTest(token_binding_case="mismatched_token_session_id"):
            assert_token_binding_rejected(
                "mismatched_token_session_id",
                {
                    **expected_token_binding,
                    "token_session_id": "session_other",
                },
                expected_token_session_read_count=1,
                expected_query_count=0,
                expected_asserted_token_session_id="session_other",
            )

        mismatched_binding_cases = (
            (
                "mismatched_user_id",
                {
                    **expected_token_binding,
                    "user_id": "wrong_user",
                },
            ),
            (
                "mismatched_current_workspace_id",
                {
                    **expected_token_binding,
                    "current_workspace_id": "wrong_workspace",
                },
            ),
        )
        for name, token_binding in mismatched_binding_cases:
            with self.subTest(token_binding_case=name):
                assert_token_binding_rejected(
                    name,
                    token_binding,
                    expected_token_session_read_count=1,
                    expected_query_count=0,
                    expected_asserted_token_session_id="session_expected",
                )

        key_spoofed_rows = [spoof_mapping_keys(row) for row in build_rows(spoof_lineage=False)]
        key_spoofed_repository = Repository(key_spoofed_rows)
        key_spoofed_rows_before = rows_state(key_spoofed_rows)
        key_spoofed_repository_before = copy.deepcopy(key_spoofed_repository.sentinel_state)
        key_spoofed_connection_before = copy.deepcopy(
            key_spoofed_repository.connection.sentinel_state
        )
        MappingKeySpoof.reset_counts()
        try:
            module._validate_mcp_authorization_audit_lineage(
                SimpleNamespace(repository=key_spoofed_repository),
                token_binding=expected_token_binding,
            )
        except RuntimeError as exc:
            self.assertEqual(
                str(exc),
                "live_e2e_mcp_audit_lineage_failed",
            )
        else:
            self.fail(
                "audit mapping-key equality spoof was accepted with "
                f"{MappingKeySpoof.hash_call_count} hash calls and "
                f"{MappingKeySpoof.equality_call_count} equality calls"
            )
        self.assertEqual(MappingKeySpoof.hash_call_count, 0)
        self.assertEqual(MappingKeySpoof.equality_call_count, 0)
        assert_read_only_state(
            key_spoofed_repository,
            rows_before=key_spoofed_rows_before,
            repository_before=key_spoofed_repository_before,
            connection_before=key_spoofed_connection_before,
        )
        self.assertEqual(MappingKeySpoof.hash_call_count, 0)
        self.assertEqual(MappingKeySpoof.equality_call_count, 0)

        token_key_spoofed_rows = build_rows(spoof_lineage=False)
        token_key_spoofed_repository = Repository(token_key_spoofed_rows)
        token_key_spoofed_rows_before = rows_state(token_key_spoofed_rows)
        token_key_spoofed_repository_before = copy.deepcopy(
            token_key_spoofed_repository.sentinel_state
        )
        token_key_spoofed_connection_before = copy.deepcopy(
            token_key_spoofed_repository.connection.sentinel_state
        )
        token_key_spoofed_binding = spoof_mapping_keys(expected_token_binding)
        MappingKeySpoof.reset_counts()
        with self.assertRaisesRegex(
            RuntimeError,
            "^live_e2e_mcp_audit_lineage_failed$",
        ):
            module._validate_mcp_authorization_audit_lineage(
                SimpleNamespace(repository=token_key_spoofed_repository),
                token_binding=token_key_spoofed_binding,
            )
        self.assertEqual(MappingKeySpoof.hash_call_count, 0)
        self.assertEqual(MappingKeySpoof.equality_call_count, 0)
        assert_read_only_state(
            token_key_spoofed_repository,
            rows_before=token_key_spoofed_rows_before,
            repository_before=token_key_spoofed_repository_before,
            connection_before=token_key_spoofed_connection_before,
            expected_token_session_read_count=0,
            expected_query_count=0,
            expected_asserted_token_session_id=None,
        )
        self.assertEqual(MappingKeySpoof.hash_call_count, 0)
        self.assertEqual(MappingKeySpoof.equality_call_count, 0)

        extra_token_key_rows = build_rows(spoof_lineage=False)
        extra_token_key_repository = Repository(extra_token_key_rows)
        extra_token_key_rows_before = rows_state(extra_token_key_rows)
        extra_token_key_repository_before = copy.deepcopy(extra_token_key_repository.sentinel_state)
        extra_token_key_connection_before = copy.deepcopy(
            extra_token_key_repository.connection.sentinel_state
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "^live_e2e_mcp_audit_lineage_failed$",
        ):
            module._validate_mcp_authorization_audit_lineage(
                SimpleNamespace(repository=extra_token_key_repository),
                token_binding={
                    **expected_token_binding,
                    "unexpected": "sensitive_extra_token_binding",
                },
            )
        assert_read_only_state(
            extra_token_key_repository,
            rows_before=extra_token_key_rows_before,
            repository_before=extra_token_key_repository_before,
            connection_before=extra_token_key_connection_before,
            expected_token_session_read_count=0,
            expected_query_count=0,
            expected_asserted_token_session_id=None,
        )

        extra_row_key_rows = build_rows(spoof_lineage=False)
        extra_row_key_rows[0]["unexpected"] = "sensitive_extra_audit_row"
        extra_row_key_repository = Repository(extra_row_key_rows)
        extra_row_key_rows_before = rows_state(extra_row_key_rows)
        extra_row_key_repository_before = copy.deepcopy(extra_row_key_repository.sentinel_state)
        extra_row_key_connection_before = copy.deepcopy(
            extra_row_key_repository.connection.sentinel_state
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "^live_e2e_mcp_audit_lineage_failed$",
        ):
            module._validate_mcp_authorization_audit_lineage(
                SimpleNamespace(repository=extra_row_key_repository),
                token_binding=expected_token_binding,
            )
        assert_read_only_state(
            extra_row_key_repository,
            rows_before=extra_row_key_rows_before,
            repository_before=extra_row_key_repository_before,
            connection_before=extra_row_key_connection_before,
        )

        spoofed_rows = build_rows(spoof_lineage=True)
        spoofed_repository = Repository(spoofed_rows)
        spoofed_rows_before = rows_state(spoofed_rows)
        spoofed_repository_before = copy.deepcopy(spoofed_repository.sentinel_state)
        spoofed_connection_before = copy.deepcopy(spoofed_repository.connection.sentinel_state)
        with self.assertRaisesRegex(
            RuntimeError,
            "^live_e2e_mcp_audit_lineage_failed$",
        ):
            module._validate_mcp_authorization_audit_lineage(
                SimpleNamespace(repository=spoofed_repository),
                token_binding=expected_token_binding,
            )
        self.assertEqual(EqualitySpoof.equality_call_count, 0)
        assert_read_only_state(
            spoofed_repository,
            rows_before=spoofed_rows_before,
            repository_before=spoofed_repository_before,
            connection_before=spoofed_connection_before,
        )

        stateful_rows = build_rows(spoof_lineage=False)
        stateful_rows[0] = StatefulRow(stateful_rows[0])
        stateful_repository = Repository(stateful_rows)
        stateful_rows_before = rows_state(stateful_rows)
        stateful_repository_before = copy.deepcopy(stateful_repository.sentinel_state)
        stateful_connection_before = copy.deepcopy(stateful_repository.connection.sentinel_state)
        with self.assertRaisesRegex(
            RuntimeError,
            "^live_e2e_mcp_audit_lineage_failed$",
        ):
            module._validate_mcp_authorization_audit_lineage(
                SimpleNamespace(repository=stateful_repository),
                token_binding=expected_token_binding,
            )
        self.assertEqual(StatefulRow.get_call_count, 0)
        assert_read_only_state(
            stateful_repository,
            rows_before=stateful_rows_before,
            repository_before=stateful_repository_before,
            connection_before=stateful_connection_before,
        )

    def test_run_inside_rechecks_revoked_bearer_after_same_subject_relink(
        self,
    ) -> None:
        self._exercise_fake_inside_relink_journey()

    def test_run_inside_rejects_upload_audit_target_mismatch_without_publication(
        self,
    ) -> None:
        self._exercise_fake_inside_relink_journey(
            audit_target_id="upload_other",
            expected_error="live_e2e_upload_actor_binding_failed",
        )

    def test_run_inside_rejects_upload_audit_equality_spoofs_without_publication(
        self,
    ) -> None:
        class EqualitySpoof:
            def __init__(self) -> None:
                self.comparison_count = 0

            def __eq__(self, _other: object) -> bool:
                self.comparison_count += 1
                return True

            def __ne__(self, _other: object) -> bool:
                self.comparison_count += 1
                return False

            @staticmethod
            def __str__() -> str:
                return "sensitive-equality-spoof"

        expected_fields = {
            "action": "upload_session_created",
            "target_type": "upload_session",
            "target_id": "upload_expected",
            "status": "ok",
        }
        for field_name in expected_fields:
            with self.subTest(field_name=field_name):
                spoof = EqualitySpoof()
                audit_fields: dict[str, object] = {
                    **expected_fields,
                    "actor_user_id": "user_owner",
                    "session_id": "session_owner",
                    "workspace_id": "workspace_live_e2e",
                }
                audit_fields[field_name] = spoof

                self._exercise_fake_inside_relink_journey(
                    stored_audit_override=SimpleNamespace(**audit_fields),
                    expected_error="live_e2e_upload_actor_binding_failed",
                    forbidden_error_text=("sensitive-equality-spoof",),
                )

                self.assertEqual(spoof.comparison_count, 0)

    def test_run_inside_rejects_upload_audit_str_subclasses_without_publication(
        self,
    ) -> None:
        class AuditStringSubclass(str):
            pass

        expected_fields = {
            "action": "upload_session_created",
            "target_type": "upload_session",
            "target_id": "upload_expected",
            "status": "ok",
        }
        for field_name, expected_value in expected_fields.items():
            with self.subTest(field_name=field_name):
                audit_fields: dict[str, object] = {
                    **expected_fields,
                    "actor_user_id": "user_owner",
                    "session_id": "session_owner",
                    "workspace_id": "workspace_live_e2e",
                }
                audit_fields[field_name] = AuditStringSubclass(expected_value)

                self._exercise_fake_inside_relink_journey(
                    stored_audit_override=SimpleNamespace(**audit_fields),
                    expected_error="live_e2e_upload_actor_binding_failed",
                )

    def test_run_inside_rejects_non_plain_required_binding_ids_without_publication(
        self,
    ) -> None:
        class IdentifierStringSubclass(str):
            pass

        stored_session = SimpleNamespace(
            upload_session_id="upload_expected",
            actor_user_id=IdentifierStringSubclass("user_owner"),
            session_id="session_owner",
            workspace_id="workspace_live_e2e",
            owner_scope_id="workspace_live_e2e",
            to_dict=lambda: {
                "upload_session_id": "upload_expected",
                "actor_user_id": "user_owner",
                "session_id": "session_owner",
                "workspace_id": "workspace_live_e2e",
                "owner_scope_id": "workspace_live_e2e",
            },
        )
        token_binding = {
            "token_session_id": "session_owner",
            "user_id": IdentifierStringSubclass("user_owner"),
            "current_workspace_id": "workspace_live_e2e",
        }
        first_whoami = {
            "auth_mode": "google_oidc_oauth",
            "user_id": IdentifierStringSubclass("user_owner"),
            "current_workspace": {
                "workspace_id": "workspace_live_e2e",
                "role": "owner",
            },
        }
        cases = (
            {"stored_session_override": stored_session},
            {"token_binding_override": token_binding},
            {"first_whoami_override": first_whoami},
        )
        for overrides in cases:
            with self.subTest(overrides=tuple(overrides)):
                self._exercise_fake_inside_relink_journey(
                    expected_error="live_e2e_upload_actor_binding_failed",
                    **overrides,
                )

    def test_run_inside_maps_raising_upload_binding_accessors_to_generic_failure(
        self,
    ) -> None:
        class RaisingStoredSession:
            upload_session_id = "upload_expected"
            session_id = "session_owner"
            workspace_id = "workspace_live_e2e"
            owner_scope_id = "workspace_live_e2e"

            @property
            def actor_user_id(self) -> str:
                raise ValueError("sensitive-session-accessor")

        class RaisingUploadAudit:
            action = "upload_session_created"
            target_type = "upload_session"
            actor_user_id = "user_owner"
            session_id = "session_owner"
            workspace_id = "workspace_live_e2e"
            status = "ok"

            @property
            def target_id(self) -> str:
                raise ValueError("sensitive-audit-accessor")

        cases = (
            (
                {"stored_session_override": RaisingStoredSession()},
                "sensitive-session-accessor",
            ),
            (
                {"stored_audit_override": RaisingUploadAudit()},
                "sensitive-audit-accessor",
            ),
        )
        for overrides, sensitive_text in cases:
            with self.subTest(sensitive_text=sensitive_text):
                self._exercise_fake_inside_relink_journey(
                    expected_error="live_e2e_upload_actor_binding_failed",
                    forbidden_error_text=(sensitive_text,),
                    **overrides,
                )

    def test_run_inside_snapshots_upload_binding_accessors_once_for_guard_and_metric(
        self,
    ) -> None:
        class StatefulValue:
            def __init__(
                self,
                expected: str,
                changed: str,
                *,
                expected_read_count: int,
            ) -> None:
                self.expected = expected
                self.changed = changed
                self.expected_read_count = expected_read_count
                self.read_count = 0

            def read(self) -> str:
                self.read_count += 1
                if self.read_count <= self.expected_read_count:
                    return self.expected
                return self.changed

        stored_actor = StatefulValue(
            "user_owner",
            "user_changed_after_guard",
            expected_read_count=3,
        )
        audit_action = StatefulValue(
            "upload_session_created",
            "audit_changed_after_guard",
            expected_read_count=1,
        )
        token_user = StatefulValue(
            "user_owner",
            "token_changed_after_guard",
            expected_read_count=2,
        )
        whoami_user = StatefulValue(
            "user_owner",
            "whoami_changed_after_guard",
            expected_read_count=1,
        )

        class StatefulStoredSession:
            upload_session_id = "upload_expected"
            session_id = "session_owner"
            workspace_id = "workspace_live_e2e"
            owner_scope_id = "workspace_live_e2e"

            @property
            def actor_user_id(self) -> str:
                return stored_actor.read()

            @staticmethod
            def to_dict() -> dict[str, str]:
                return {
                    "upload_session_id": "upload_expected",
                    "actor_user_id": "user_owner",
                    "session_id": "session_owner",
                    "workspace_id": "workspace_live_e2e",
                    "owner_scope_id": "workspace_live_e2e",
                }

        class StatefulUploadAudit:
            target_type = "upload_session"
            target_id = "upload_expected"
            actor_user_id = "user_owner"
            session_id = "session_owner"
            workspace_id = "workspace_live_e2e"
            status = "ok"

            @property
            def action(self) -> str:
                return audit_action.read()

        class StatefulTokenBinding(dict[str, str]):
            def __getitem__(self, key: str) -> str:
                if key == "user_id":
                    return token_user.read()
                return super().__getitem__(key)

        class StatefulWhoami(dict[str, object]):
            def get(self, key: str, default: object = None) -> object:
                if key == "user_id":
                    return whoami_user.read()
                return super().get(key, default)

        token_binding = StatefulTokenBinding(
            token_session_id="session_owner",
            user_id="user_owner",
            current_workspace_id="workspace_live_e2e",
        )
        first_whoami = StatefulWhoami(
            auth_mode="google_oidc_oauth",
            user_id="user_owner",
            current_workspace={
                "workspace_id": "workspace_live_e2e",
                "role": "owner",
            },
        )
        report = self._exercise_fake_inside_relink_journey(
            stored_session_override=StatefulStoredSession(),
            stored_audit_override=StatefulUploadAudit(),
            token_binding_override=token_binding,
            first_whoami_override=first_whoami,
        )

        self.assertIsNotNone(report)
        self.assertIs(report["metrics"]["upload_file_audit_token_binding_verified"], True)
        self.assertEqual(stored_actor.read_count, 1)
        self.assertEqual(audit_action.read_count, 1)
        self.assertEqual(token_user.read_count, 1)
        self.assertEqual(whoami_user.read_count, 1)

    def _exercise_fake_inside_relink_journey(
        self,
        *,
        audit_target_id: object = "upload_expected",
        stored_session_override: object | None = None,
        stored_audit_override: object | None = None,
        token_binding_override: dict[str, str] | None = None,
        first_whoami_override: dict[str, object] | None = None,
        expected_error: str | None = None,
        forbidden_error_text: tuple[str, ...] = (),
    ) -> dict[str, object] | None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_post_relink_revocation",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()
        owner_token = "owner-sensitive-bearer"
        revoked_token = "revoked-sensitive-bearer"
        relinked_token = "relinked-sensitive-bearer"
        state = {
            "users": 0,
            "workspace_members": 0,
            "external_identities": 0,
            "accepted_invitations": 0,
            "token_sessions": 0,
            "revoked_token_sessions": 0,
            "postgres_audits": 8,
        }
        token_records: dict[str, SimpleNamespace] = {}
        evidence = {
            "events": [],
            "latest_binding_calls": [],
            "token_session_reads": [],
            "oauth_count_calls": [],
        }

        class FakeRepository:
            def __init__(self, runtime_name: str) -> None:
                self.runtime_name = runtime_name

            def get_owner_bootstrap(self, workspace_id: str) -> SimpleNamespace:
                self.assert_workspace(workspace_id)
                return SimpleNamespace(status="completed")

            def get_invitation(self, invitation_id: str) -> SimpleNamespace:
                if invitation_id not in {"invitation_owner", "invitation_member"}:
                    raise AssertionError("unexpected invitation")
                return SimpleNamespace(status="accepted")

            def get_token_session(self, token_session_id: str) -> SimpleNamespace | None:
                evidence["token_session_reads"].append((self.runtime_name, token_session_id))
                return token_records.get(token_session_id)

            @staticmethod
            def assert_workspace(workspace_id: str) -> None:
                if workspace_id != "workspace_live_e2e":
                    raise AssertionError("unexpected workspace")

        class FakeRuntime:
            def __init__(self, name: str) -> None:
                self.name = name
                self.application = SimpleNamespace(app=object())
                self.repository = FakeRepository(name)

            def bootstrap_owner(self, **kwargs: object) -> dict[str, str]:
                FakeRepository.assert_workspace(str(kwargs["workspace_id"]))
                return {"invitation_id": "invitation_owner"}

            def migrate(self) -> dict[str, int]:
                return {"applied_migration_count": 0, "skipped_migration_count": 5}

            def invite_user(
                self,
                *,
                workspace_id: str,
                email: str,
                role: str,
                invited_by_user_id: str,
                operator_service_id: str,
                expires_at: object,
                intended_user_id: str | None = None,
            ) -> dict[str, str]:
                FakeRepository.assert_workspace(workspace_id)
                if operator_service_id != "operator_live_e2e":
                    raise AssertionError("unexpected operator service")
                del email, role, invited_by_user_id, expires_at, intended_user_id
                return {"invitation_id": "invitation_member"}

            def revoke_token_session(self, *, token_session_id: str, **_: object) -> None:
                token_records[token_session_id].revoked_at = "2026-07-16T00:00:00Z"
                state["revoked_token_sessions"] = 1

        runtimes = [FakeRuntime(name) for name in ("initial", "restart", "retired", "expiry")]
        runtime_iterator = iter(runtimes)

        class FakeGoogle:
            authorization_endpoint = "https://google.test/auth"
            discovery_url = "https://google.test/discovery"
            jwks_uri = "https://google.test/jwks"
            token_endpoint = "https://google.test/token"

            def __init__(self, **_: object) -> None:
                return None

            def __enter__(self) -> "FakeGoogle":
                return self

            def __exit__(self, *_: object) -> None:
                return None

            def set_account(self, account: object) -> None:
                del account

        class FakeResponse:
            def __init__(
                self,
                metadata_url: str,
                *,
                url: str,
                request: dict[str, object],
                bearer: str,
            ) -> None:
                self.url = url
                self.request = request
                self.bearer = bearer
                self.status = 401
                self.headers = {
                    "www-authenticate": (
                        f'Bearer resource_metadata="{metadata_url}", '
                        'error="invalid_token", '
                        'error_description="Authentication required."'
                    ),
                    "cache-control": "no-store",
                    "pragma": "no-cache",
                }

            @staticmethod
            def json() -> dict[str, str]:
                return {"error": "invalid_token"}

        class FakeJwksResponse:
            status = 200

            def __init__(self, kids: list[str]) -> None:
                self.kids = kids

            def json(self) -> dict[str, list[dict[str, str]]]:
                return {"keys": [{"kid": kid, "kty": "RSA"} for kid in self.kids]}

        class FakeClient:
            def __init__(
                self,
                *,
                oauth: object,
                server_base_url: str,
                seed: str,
                fake_google: object,
            ) -> None:
                del fake_google
                self.oauth = oauth
                self.endpoint = f"{server_base_url}/mcp"
                kids = (
                    ["formowl-live-key", "formowl-live-key-rotated"]
                    if seed == "connected-runtime-live-rotation-probe"
                    else ["formowl-live-key-rotated"]
                )
                self.http = SimpleNamespace(get=lambda _url: FakeJwksResponse(kids))

            def mcp_call(
                self,
                url: str,
                request: dict[str, object],
                *,
                bearer: str,
            ) -> FakeResponse:
                response = FakeResponse(
                    self.oauth.protected_resource_metadata_url,
                    url=url,
                    request=request,
                    bearer=bearer,
                )
                evidence["events"].append(
                    {
                        "kind": "mcp_request",
                        "url": url,
                        "request": request,
                        "bearer": bearer,
                        "response": response,
                    }
                )
                return response

        server_count = 0

        class FakeServer:
            def __init__(self, _factory: object) -> None:
                nonlocal server_count
                server_count += 1
                self.base_url = f"https://runtime-{server_count}.test"

            def __enter__(self) -> "FakeServer":
                return self

            def __exit__(self, *_: object) -> None:
                return None

        def add_session(
            token_session_id: str,
            user_id: str,
            *,
            revoked_at: str | None = None,
        ) -> None:
            token_records[token_session_id] = SimpleNamespace(
                token_session_id=token_session_id,
                user_id=user_id,
                current_workspace_id="workspace_live_e2e",
                revoked_at=revoked_at,
            )

        login_index = 0

        def complete_login(_client: object, _oauth: object) -> str:
            nonlocal login_index
            login_index += 1
            if login_index == 1:
                state.update(
                    users=1,
                    workspace_members=1,
                    external_identities=1,
                    accepted_invitations=1,
                    token_sessions=1,
                )
                add_session("session_owner", "user_owner")
                return owner_token
            if login_index == 2:
                state.update(
                    users=2,
                    workspace_members=2,
                    external_identities=2,
                    accepted_invitations=2,
                    token_sessions=2,
                )
                add_session("session_revoked", "user_member")
                return revoked_token
            state["token_sessions"] = 3
            add_session("session_relinked", "user_member")
            return relinked_token

        def sequence(
            whoami: dict[str, object],
            *,
            first: bool = False,
        ) -> dict[str, object]:
            calls = [
                {
                    "name": "whoami",
                    "result": {"isError": False, "structuredContent": whoami},
                }
            ]
            if first:
                calls.extend(
                    [
                        {
                            "name": "open_upload_session",
                            "result": {
                                "isError": False,
                                "structuredContent": {"status": "ok"},
                            },
                        },
                        {"name": "open_upload_session", "result": {"isError": True}},
                        {"name": "open_upload_session", "result": {"isError": True}},
                    ]
                )
            return {
                "initialize": {"protocolVersion": module.LATEST_PROTOCOL_VERSION},
                "tools": {
                    "tools": [
                        {"name": "open_upload_session"},
                        {"name": "whoami"},
                    ]
                },
                "calls": calls,
            }

        sequence_counts = {owner_token: 0, revoked_token: 0, relinked_token: 0}

        async def run_sequence(
            url: str,
            *,
            bearer: str,
            tool_calls: object,
        ) -> dict[str, object]:
            evidence["events"].append(
                {
                    "kind": "sequence",
                    "url": url,
                    "bearer": bearer,
                    "tool_calls": tool_calls,
                }
            )
            sequence_counts[bearer] += 1
            if bearer == owner_token:
                first_owner_sequence = sequence_counts[bearer] == 1
                return sequence(
                    (
                        first_whoami_override
                        if first_owner_sequence and first_whoami_override is not None
                        else {
                            "auth_mode": "google_oidc_oauth",
                            "user_id": "user_owner",
                            "current_workspace": {
                                "workspace_id": "workspace_live_e2e",
                                "role": "owner",
                            },
                        }
                    ),
                    first=first_owner_sequence,
                )
            return sequence(
                {
                    "user_id": "user_member",
                    "current_workspace": {
                        "workspace_id": "workspace_live_e2e",
                        "role": "member",
                    },
                }
            )

        def count_rows(_runtime: FakeRuntime, table_name: str) -> int:
            return {
                "formowl_schema_migrations": 5,
                "formowl_users": state["users"],
                "formowl_workspace_members": state["workspace_members"],
                "formowl_external_identities": state["external_identities"],
                "formowl_oauth_invitations": state["accepted_invitations"],
                "formowl_oauth_token_sessions": state["token_sessions"],
                "formowl_audit_log": state["postgres_audits"],
            }[table_name]

        def count_oauth_state(runtime: FakeRuntime, state_name: str) -> int:
            evidence["oauth_count_calls"].append((runtime.name, state_name))
            return state[state_name]

        def latest_binding(runtime: FakeRuntime, *, user_id: str) -> dict[str, str]:
            evidence["latest_binding_calls"].append((runtime.name, user_id))
            session_id = (
                "session_relinked"
                if runtime.name == "expiry" and state["token_sessions"] == 3
                else "session_revoked"
            )
            return {
                "token_session_id": session_id,
                "user_id": user_id,
                "current_workspace_id": "workspace_live_e2e",
            }

        stored_session = (
            stored_session_override
            if stored_session_override is not None
            else SimpleNamespace(
                upload_session_id="upload_expected",
                actor_user_id="user_owner",
                session_id="session_owner",
                workspace_id="workspace_live_e2e",
                owner_scope_id="workspace_live_e2e",
                to_dict=lambda: {
                    "upload_session_id": "upload_expected",
                    "actor_user_id": "user_owner",
                    "session_id": "session_owner",
                    "workspace_id": "workspace_live_e2e",
                    "owner_scope_id": "workspace_live_e2e",
                },
            )
        )
        stored_audit = (
            stored_audit_override
            if stored_audit_override is not None
            else SimpleNamespace(
                action="upload_session_created",
                target_type="upload_session",
                target_id=audit_target_id,
                actor_user_id="user_owner",
                session_id="session_owner",
                workspace_id="workspace_live_e2e",
                status="ok",
            )
        )
        token_binding = (
            token_binding_override
            if token_binding_override is not None
            else {
                "token_session_id": "session_owner",
                "user_id": "user_owner",
                "current_workspace_id": "workspace_live_e2e",
            }
        )
        file_audit_store_read_count = 0

        def list_file_audits() -> list[object]:
            nonlocal file_audit_store_read_count
            file_audit_store_read_count += 1
            if file_audit_store_read_count == 1:
                return [stored_audit]
            return [
                SimpleNamespace(
                    action="upload_session_created",
                    target_type="upload_session",
                    target_id="upload_expected",
                    actor_user_id="user_owner",
                    session_id="session_owner",
                    workspace_id="workspace_live_e2e",
                    status="ok",
                )
            ]

        async def record_sleep(seconds: float) -> None:
            evidence["events"].append({"kind": "sleep", "seconds": seconds})

        original_assert_bearer_denied = module._assert_bearer_denied

        def assert_bearer_denied(
            response: FakeResponse,
            *,
            expected_metadata_url: str | None = None,
        ) -> dict[str, object]:
            shape = original_assert_bearer_denied(
                response,
                expected_metadata_url=expected_metadata_url,
            )
            evidence["events"].append(
                {
                    "kind": "denial_validated",
                    "url": response.url,
                    "request": response.request,
                    "bearer": response.bearer,
                    "expected_metadata_url": expected_metadata_url,
                    "response": response,
                    "shape": shape,
                }
            )
            return shape

        async def compose_runtime(*_: object, **__: object) -> FakeRuntime:
            return next(runtime_iterator)

        async def preflight(*_: object, **__: object) -> None:
            return None

        with tempfile.TemporaryDirectory(
            prefix="formowl-post-relink-ordering-",
            dir=tempfile.gettempdir(),
        ) as temporary:
            output_path = Path(temporary) / "live-report.json"
            output_helper_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
            output_path.write_bytes(b"stale-valid-looking-output\n")
            output_helper_path.write_bytes(b"stale-atomic-helper\n")
            atomic_write = mock.Mock(wraps=module.write_json_atomic)
            self._fake_inside_atomic_write = atomic_write
            self._fake_inside_output_path = output_path
            self._fake_inside_output_helper_path = output_helper_path
            patches = (
                mock.patch.dict(
                    os.environ,
                    {
                        module._INSIDE_DSN_ENV: "postgresql://synthetic:test@db/formowl",
                        module._INSIDE_DATA_DIR_ENV: "/tmp/formowl-live-test",
                    },
                    clear=True,
                ),
                mock.patch.object(module, "FakeGoogleOidcProvider", FakeGoogle),
                mock.patch.object(module, "AsgiHttpServer", FakeServer),
                mock.patch.object(module, "_compose_runtime", side_effect=compose_runtime),
                mock.patch.object(
                    module,
                    "_initial_migrate_with_safe_diagnostics",
                    return_value={"applied_migration_count": 5, "skipped_migration_count": 0},
                ),
                mock.patch.object(
                    module,
                    "_run_transaction_rollback_probe",
                    return_value={
                        "before_user_count": 0,
                        "after_user_count": 0,
                        "probe_count": 1,
                    },
                ),
                mock.patch.object(
                    module,
                    "_preflight_with_safe_diagnostics",
                    side_effect=preflight,
                ),
                mock.patch.object(
                    module,
                    "_chatgpt_client",
                    side_effect=lambda **kwargs: FakeClient(**kwargs),
                ),
                mock.patch.object(module, "_complete_oauth_login", side_effect=complete_login),
                mock.patch.object(
                    module,
                    "_jwt_expiry",
                    return_value=module.datetime.now(module.timezone.utc)
                    - module.timedelta(seconds=2),
                ),
                mock.patch.object(
                    module,
                    "_jwt_kid",
                    return_value="formowl-live-key-rotated",
                ),
                mock.patch.object(
                    module,
                    "run_official_mcp_client_sequence",
                    side_effect=run_sequence,
                ),
                mock.patch.object(
                    module,
                    "_token_session_binding",
                    return_value=token_binding,
                ),
                mock.patch.object(
                    module,
                    "_validate_mcp_authorization_audit_lineage",
                    return_value={
                        "allowed_count": 2,
                        "denied_count": 2,
                        "lineage_complete_count": 4,
                        "distinct_tool_call_count": 4,
                    },
                ),
                mock.patch.object(
                    module,
                    "UploadSessionStore",
                    side_effect=lambda _path: SimpleNamespace(list=lambda: [stored_session]),
                ),
                mock.patch.object(
                    module,
                    "FileAuditLogStore",
                    side_effect=lambda _path: SimpleNamespace(list=list_file_audits),
                ),
                mock.patch.object(module, "_count_rows", side_effect=count_rows),
                mock.patch.object(module, "_count_oauth_state", side_effect=count_oauth_state),
                mock.patch.object(
                    module,
                    "_latest_token_session_binding_for_user",
                    side_effect=latest_binding,
                ),
                mock.patch.object(module, "_assert_bearer_denied", new=assert_bearer_denied),
                mock.patch.object(module.asyncio, "sleep", side_effect=record_sleep),
                mock.patch.object(module, "write_json_atomic", new=atomic_write),
            )
            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                if expected_error is not None:
                    with self.assertRaisesRegex(
                        RuntimeError,
                        f"^{expected_error}$",
                    ) as caught:
                        asyncio.run(module._run_inside(output_path))

                    self.assertEqual(str(caught.exception), expected_error)
                    for sensitive_text in forbidden_error_text:
                        self.assertNotIn(sensitive_text, str(caught.exception))
                    atomic_write.assert_not_called()
                    self.assertFalse(output_path.exists())
                    self.assertFalse(output_helper_path.exists())
                    return None

                report = asyncio.run(module._run_inside(output_path))

                self.assertEqual(report["status"], "passed")
                self.assertTrue(output_path.is_file())
                self.assertFalse(output_helper_path.exists())
                self.assertEqual(
                    json.loads(output_path.read_text(encoding="utf-8")),
                    report,
                )
                atomic_write.assert_called_once_with(output_path, report)

        runtime_four_events = [
            event
            for event in evidence["events"]
            if (
                event["kind"] in {"sequence", "mcp_request", "denial_validated"}
                and event.get("url") == "https://runtime-4.test/mcp"
            )
            or (event["kind"] == "sleep" and event["seconds"] == 2)
        ]
        self.assertEqual(
            [event["kind"] for event in runtime_four_events],
            [
                "sequence",
                "mcp_request",
                "denial_validated",
                "sleep",
                "mcp_request",
                "denial_validated",
            ],
        )
        relink_whoami_event, old_request, old_denial, expiry_wait, expiry_request, expiry_denial = (
            runtime_four_events
        )
        self.assertEqual(relink_whoami_event["bearer"], relinked_token)
        self.assertEqual(relink_whoami_event["tool_calls"], (("whoami", {}),))
        self.assertEqual(old_request["bearer"], revoked_token)
        self.assertEqual(
            old_request["request"],
            module._initialize_request("live_e2e_post_relink_revoked_token"),
        )
        self.assertEqual(old_denial["bearer"], revoked_token)
        self.assertEqual(expiry_wait, {"kind": "sleep", "seconds": 2})
        self.assertEqual(expiry_request["bearer"], relinked_token)
        self.assertEqual(
            expiry_request["request"],
            module._initialize_request("live_e2e_expired_token"),
        )
        self.assertEqual(expiry_denial["bearer"], relinked_token)

        expected_metadata_url = "https://formowl-live.example/.well-known/oauth-protected-resource"
        expected_challenge = (
            f'Bearer resource_metadata="{expected_metadata_url}", '
            'error="invalid_token", error_description="Authentication required."'
        )
        for event in (old_denial, expiry_denial):
            self.assertEqual(event["expected_metadata_url"], expected_metadata_url)
            self.assertEqual(
                event["shape"],
                {
                    "status": 401,
                    "challenge_present": True,
                    "body_shape": {"error": "string"},
                    "challenge_exact": True,
                    "body_exact": True,
                },
            )
            response = event["response"]
            self.assertEqual(response.status, 401)
            self.assertEqual(response.json(), {"error": "invalid_token"})
            self.assertEqual(response.headers["www-authenticate"], expected_challenge)
            rendered = json.dumps(response.json()) + response.headers["www-authenticate"]
            for forbidden in (
                owner_token,
                revoked_token,
                relinked_token,
                "postgresql://",
                "SELECT ",
                "/workspace/",
                "backend=",
            ):
                self.assertNotIn(forbidden, rendered)

        self.assertIn(("expiry", "revoked_token_sessions"), evidence["oauth_count_calls"])
        self.assertIn(("expiry", "user_member"), evidence["latest_binding_calls"])
        self.assertIn(("expiry", "session_revoked"), evidence["token_session_reads"])
        self.assertIn(("expiry", "session_relinked"), evidence["token_session_reads"])
        self.assertEqual(state["revoked_token_sessions"], 1)
        self.assertEqual(report["safe_counts"]["revoked_token_sessions_after_relink_count"], 1)
        self.assertIsNot(token_records["session_revoked"], token_records["session_relinked"])
        self.assertIsNotNone(token_records["session_revoked"].revoked_at)
        self.assertIsNone(token_records["session_relinked"].revoked_at)
        rendered_report = json.dumps(report, sort_keys=True)
        for forbidden in (
            owner_token,
            revoked_token,
            relinked_token,
            "postgresql://",
            "SELECT ",
            "/workspace/",
            "backend=",
        ):
            self.assertNotIn(forbidden, rendered_report)
        return report

    def test_run_transaction_rollback_probe_uses_exact_sentinel_identity_and_rolls_back(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_transaction_rollback_probe",
            SCRIPT_PATH,
        )
        module._load_inside_dependencies()
        now = module.datetime(
            2026,
            7,
            18,
            12,
            34,
            56,
            123456,
            tzinfo=module.timezone.utc,
        )

        class FakeRepository:
            def __init__(
                self,
                *,
                entry_error: RuntimeError | None = None,
                insert_error: RuntimeError | None = None,
                rollback_error: RuntimeError | None = None,
            ) -> None:
                self.entry_error = entry_error
                self.insert_error = insert_error
                self.rollback_error = rollback_error
                self.rows = [object()]
                self.inserted_users: list[object] = []
                self.transaction_count = 0
                self.enter_count = 0
                self.exit_count = 0
                self.rollback_count = 0
                self.commit_count = 0
                self.exit_exception_types: list[object] = []
                self.exit_exceptions: list[object] = []

            def transaction(self) -> object:
                repository = self
                self.transaction_count += 1

                class FakeUnitOfWork:
                    def __init__(self) -> None:
                        self.snapshot: list[object] | None = None

                    def __enter__(self) -> "FakeUnitOfWork":
                        repository.enter_count += 1
                        if repository.entry_error is not None:
                            raise repository.entry_error
                        self.snapshot = list(repository.rows)
                        return self

                    def __exit__(
                        self,
                        exc_type: object,
                        exc: object,
                        traceback: object,
                    ) -> bool:
                        del traceback
                        repository.exit_count += 1
                        repository.exit_exception_types.append(exc_type)
                        repository.exit_exceptions.append(exc)
                        if exc_type is None and exc is None:
                            repository.commit_count += 1
                        else:
                            repository.rollback_count += 1
                            assert self.snapshot is not None
                            repository.rows[:] = self.snapshot
                            if repository.rollback_error is not None:
                                raise repository.rollback_error
                        return False

                return FakeUnitOfWork()

            def insert_user(self, user: object) -> None:
                self.inserted_users.append(user)
                if self.insert_error is not None:
                    raise self.insert_error
                self.rows.append(user)

        def run_with_repository(repository: FakeRepository) -> dict[str, int]:
            runtime = SimpleNamespace(repository=repository)

            def count_rows(candidate_runtime: object, table_name: str) -> int:
                self.assertIs(candidate_runtime, runtime)
                self.assertEqual(table_name, "formowl_users")
                return len(repository.rows)

            with mock.patch.object(module, "_count_rows", side_effect=count_rows) as count:
                result = module._run_transaction_rollback_probe(runtime, now=now)

            self.assertEqual(count.call_count, 2)
            return result

        repository = FakeRepository()
        rows_before = tuple(repository.rows)

        result = run_with_repository(repository)

        self.assertEqual(
            result,
            {
                "before_user_count": 1,
                "after_user_count": 1,
                "probe_count": 1,
            },
        )
        self.assertEqual(repository.transaction_count, 1)
        self.assertEqual(repository.enter_count, 1)
        self.assertEqual(repository.exit_count, 1)
        self.assertEqual(repository.rollback_count, 1)
        self.assertEqual(repository.commit_count, 0)
        self.assertEqual(tuple(repository.rows), rows_before)
        self.assertEqual(repository.exit_exception_types, [RuntimeError])
        self.assertEqual(len(repository.exit_exceptions), 1)
        injected_error = repository.exit_exceptions[0]
        self.assertIsNotNone(injected_error)
        self.assertIs(type(injected_error), RuntimeError)
        self.assertEqual(injected_error.args, ("live_e2e_injected_rollback",))
        self.assertEqual(str(injected_error), "live_e2e_injected_rollback")
        self.assertEqual(len(repository.inserted_users), 1)
        inserted_user = repository.inserted_users[0]
        self.assertIs(type(inserted_user), module.User)
        self.assertEqual(inserted_user.user_id, "user_live_rollback_probe")
        self.assertEqual(inserted_user.display_name, "Rollback Probe")
        self.assertEqual(inserted_user.email, "rollback-probe@example.test")
        self.assertEqual(inserted_user.status, "active")
        self.assertEqual(inserted_user.created_at, now.isoformat())

        collision_errors = {
            phase: RuntimeError("live_e2e_injected_rollback")
            for phase in ("transaction_entry", "insert_user", "rollback")
        }
        self.assertEqual(
            len({id(error) for error in collision_errors.values()}),
            len(collision_errors),
        )
        for phase, expected_error in collision_errors.items():
            with self.subTest(phase=phase):
                repository = FakeRepository(
                    entry_error=expected_error if phase == "transaction_entry" else None,
                    insert_error=expected_error if phase == "insert_user" else None,
                    rollback_error=expected_error if phase == "rollback" else None,
                )
                rows_before = tuple(repository.rows)
                runtime = SimpleNamespace(repository=repository)

                def count_rows(candidate_runtime: object, table_name: str) -> int:
                    self.assertIs(candidate_runtime, runtime)
                    self.assertEqual(table_name, "formowl_users")
                    return len(repository.rows)

                with (
                    mock.patch.object(module, "_count_rows", side_effect=count_rows) as count,
                    self.assertRaises(RuntimeError) as raised,
                ):
                    module._run_transaction_rollback_probe(runtime, now=now)

                self.assertIs(raised.exception, expected_error)
                self.assertEqual(count.call_count, 1)
                self.assertEqual(tuple(repository.rows), rows_before)
                self.assertEqual(repository.transaction_count, 1)
                self.assertEqual(repository.enter_count, 1)
                self.assertEqual(repository.commit_count, 0)
                if phase == "transaction_entry":
                    self.assertEqual(repository.exit_count, 0)
                    self.assertEqual(repository.rollback_count, 0)
                    self.assertEqual(repository.inserted_users, [])
                    self.assertEqual(repository.exit_exception_types, [])
                    self.assertEqual(repository.exit_exceptions, [])
                elif phase == "insert_user":
                    self.assertEqual(repository.exit_count, 1)
                    self.assertEqual(repository.rollback_count, 1)
                    self.assertEqual(len(repository.inserted_users), 1)
                    self.assertEqual(repository.exit_exception_types, [RuntimeError])
                    self.assertEqual(repository.exit_exceptions, [expected_error])
                    self.assertIs(repository.exit_exceptions[0], expected_error)
                else:
                    self.assertEqual(repository.exit_count, 1)
                    self.assertEqual(repository.rollback_count, 1)
                    self.assertEqual(len(repository.inserted_users), 1)
                    self.assertEqual(repository.exit_exception_types, [RuntimeError])
                    self.assertEqual(len(repository.exit_exceptions), 1)
                    self.assertIsNot(repository.exit_exceptions[0], expected_error)
                    self.assertIs(type(repository.exit_exceptions[0]), RuntimeError)
                    self.assertEqual(
                        repository.exit_exceptions[0].args,
                        ("live_e2e_injected_rollback",),
                    )

    def test_run_command_invokes_subprocess_once_and_returns_exact_result_without_mutation(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_run_command_success",
            SCRIPT_PATH,
        )
        command = ["docker", "version"]
        command_before = list(command)
        command_element_ids_before = tuple(id(value) for value in command)
        completed = subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="Docker version synthetic\n",
            stderr="",
        )

        with mock.patch.object(
            module.subprocess,
            "run",
            return_value=completed,
        ) as subprocess_run:
            returned = module._run_command(command, check=True)

        self.assertIs(type(command), list)
        self.assertTrue(command)
        self.assertTrue(all(type(value) is str and value for value in command))
        self.assertIs(type(True), bool)
        self.assertIs(returned, completed)
        self.assertIs(type(returned), subprocess.CompletedProcess)
        self.assertIs(returned.args, command)
        self.assertEqual(returned.returncode, 0)
        self.assertEqual(returned.stdout, "Docker version synthetic\n")
        self.assertEqual(returned.stderr, "")
        subprocess_run.assert_called_once_with(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(subprocess_run.call_count, 1)
        self.assertIs(subprocess_run.call_args.args[0], command)
        self.assertEqual(command, command_before)
        self.assertEqual(
            tuple(id(value) for value in command),
            command_element_ids_before,
        )

    def test_run_command_translates_launch_and_decode_failures_without_leaks_or_mutation(
        self,
    ) -> None:
        import traceback

        module = _load_module(
            "connected_runtime_postgres_live_e2e_run_command_execution_failures",
            SCRIPT_PATH,
        )
        sensitive_marker = "synthetic-sensitive-subprocess-failure-marker"
        cases = (
            (
                "os_launch_failure",
                True,
                FileNotFoundError(
                    2,
                    sensitive_marker,
                    f"/private/{sensitive_marker}",
                ),
            ),
            (
                "text_decode_failure",
                False,
                UnicodeDecodeError(
                    "utf-8",
                    b"\xff",
                    0,
                    1,
                    sensitive_marker,
                ),
            ),
        )

        for case_name, check, execution_error in cases:
            with self.subTest(case=case_name):
                command = ["docker", "version"]
                command_before = list(command)
                command_element_ids_before = tuple(id(value) for value in command)
                check_before = check
                parser_state = {"call_count": 0}

                def forbidden_json_loads(*_: object, **__: object) -> object:
                    parser_state["call_count"] += 1
                    raise AssertionError(sensitive_marker)

                self.assertIn(sensitive_marker, str(execution_error))
                with (
                    mock.patch.object(
                        module.subprocess,
                        "run",
                        side_effect=execution_error,
                    ) as subprocess_run,
                    mock.patch.object(
                        module.json,
                        "loads",
                        side_effect=forbidden_json_loads,
                    ) as json_loads,
                    self.assertRaises(RuntimeError) as raised,
                ):
                    module._run_command(command, check=check)

                self.assertIs(type(raised.exception), RuntimeError)
                self.assertEqual(
                    raised.exception.args,
                    ("live_e2e_command_failed",),
                )
                self.assertEqual(
                    str(raised.exception),
                    "live_e2e_command_failed",
                )
                self.assertIsNone(raised.exception.__cause__)
                self.assertTrue(raised.exception.__suppress_context__)
                rendered = "".join(traceback.format_exception(raised.exception))
                self.assertNotIn(sensitive_marker, rendered)
                subprocess_run.assert_called_once_with(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(subprocess_run.call_count, 1)
                self.assertIs(subprocess_run.call_args.args[0], command)
                json_loads.assert_not_called()
                self.assertEqual(parser_state, {"call_count": 0})
                self.assertEqual(command, command_before)
                self.assertEqual(
                    tuple(id(value) for value in command),
                    command_element_ids_before,
                )
                self.assertIs(check, check_before)

    def test_run_command_handles_nonzero_results_without_leaks_or_mutation(
        self,
    ) -> None:
        import traceback

        module = _load_module(
            "connected_runtime_postgres_live_e2e_run_command_nonzero_results",
            SCRIPT_PATH,
        )
        sensitive_marker = "synthetic-sensitive-nonzero.invalid"
        safe_stderr_lines = (
            '{"error":"synthetic_first_safe"}',
            f"malformed:{sensitive_marker}",
            '{"error":"synthetic_last_safe"}',
            json.dumps({"error": f"../{sensitive_marker}"}, sort_keys=True),
        )
        fallback_stderr_lines = (
            f"malformed:{sensitive_marker}",
            json.dumps({"error": f"../{sensitive_marker}"}, sort_keys=True),
            json.dumps([{"error": "synthetic_not_a_mapping"}], sort_keys=True),
            json.dumps({"error": 7}, sort_keys=True),
            json.dumps({"detail": sensitive_marker}, sort_keys=True),
        )
        cases = (
            (
                "check_false_returns_exact_result",
                False,
                safe_stderr_lines,
                None,
                0,
            ),
            (
                "check_true_uses_last_valid_safe_code",
                True,
                safe_stderr_lines,
                "synthetic_last_safe",
                2,
            ),
            (
                "check_true_unsafe_payloads_fall_back",
                True,
                fallback_stderr_lines,
                "live_e2e_command_failed",
                len(fallback_stderr_lines),
            ),
        )

        for case_name, check, stderr_lines, expected_error, expected_json_calls in cases:
            with self.subTest(case=case_name):
                command = ["driver.invalid", "--synthetic"]
                command_before = list(command)
                command_element_ids_before = tuple(id(value) for value in command)
                check_before = check
                completed = subprocess.CompletedProcess(
                    args=command,
                    returncode=23,
                    stdout=f"synthetic-stdout:{sensitive_marker}",
                    stderr="\n".join(stderr_lines) + "\n",
                )
                completed_before = copy.deepcopy(vars(completed))

                with (
                    mock.patch.object(
                        module.subprocess,
                        "run",
                        return_value=completed,
                    ) as subprocess_run,
                    mock.patch.object(
                        module.json,
                        "loads",
                        wraps=module.json.loads,
                    ) as json_loads,
                ):
                    if expected_error is None:
                        returned = module._run_command(command, check=check)
                        self.assertIs(returned, completed)
                    else:
                        with self.assertRaises(RuntimeError) as raised:
                            module._run_command(command, check=check)

                        self.assertIs(type(raised.exception), RuntimeError)
                        self.assertEqual(raised.exception.args, (expected_error,))
                        self.assertEqual(str(raised.exception), expected_error)
                        self.assertIsNone(raised.exception.__cause__)
                        self.assertIsNone(raised.exception.__context__)
                        rendered = "".join(traceback.format_exception(raised.exception))
                        self.assertNotIn(sensitive_marker, rendered)
                        self.assertNotIn("driver.invalid", rendered)

                subprocess_run.assert_called_once_with(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(subprocess_run.call_count, 1)
                self.assertIs(subprocess_run.call_args.args[0], command)
                self.assertEqual(json_loads.call_count, expected_json_calls)
                if not check:
                    json_loads.assert_not_called()
                self.assertEqual(command, command_before)
                self.assertEqual(
                    tuple(id(value) for value in command),
                    command_element_ids_before,
                )
                self.assertIs(check, check_before)
                self.assertEqual(vars(completed), completed_before)
                self.assertIs(completed.args, command)

    def test_run_command_suppresses_json_value_and_recursion_errors_without_retry_or_mutation(
        self,
    ) -> None:
        import sys
        import traceback

        module = _load_module(
            "connected_runtime_postgres_live_e2e_run_command_json_parser_failures",
            SCRIPT_PATH,
        )
        sensitive_marker = "synthetic-sensitive-parser.invalid"
        max_int_digits = sys.get_int_max_str_digits()
        self.assertGreater(max_int_digits, 0)
        nested_depth = max(10_000, sys.getrecursionlimit() * 10)
        cases = (
            (
                "oversized_integer",
                (f'{{"detail":"{sensitive_marker}","error":' f'{"9" * (max_int_digits + 1)}}}'),
                ValueError,
            ),
            (
                "excessive_nesting",
                (
                    f'{{"detail":"{sensitive_marker}","error":'
                    f'{"[" * nested_depth}0{"]" * nested_depth}}}'
                ),
                RecursionError,
            ),
        )

        for case_name, stderr_line, parser_error_type in cases:
            with self.subTest(case=case_name):
                with self.assertRaises(parser_error_type) as parser_error:
                    json.loads(stderr_line)

                self.assertIs(type(parser_error.exception), parser_error_type)
                parser_detail = str(parser_error.exception)
                self.assertTrue(parser_detail)
                command = ["driver.invalid", "--synthetic"]
                command_before = list(command)
                command_element_ids_before = tuple(id(value) for value in command)
                check = True
                check_before = check
                completed = subprocess.CompletedProcess(
                    args=command,
                    returncode=23,
                    stdout=f"synthetic-stdout:{sensitive_marker}",
                    stderr=f"{stderr_line}\n",
                )
                completed_before = copy.deepcopy(vars(completed))

                with (
                    mock.patch.object(
                        module.subprocess,
                        "run",
                        return_value=completed,
                    ) as subprocess_run,
                    mock.patch.object(
                        module.json,
                        "loads",
                        wraps=module.json.loads,
                    ) as json_loads,
                    self.assertRaises(RuntimeError) as raised,
                ):
                    module._run_command(command, check=check)

                self.assertIs(type(raised.exception), RuntimeError)
                self.assertEqual(
                    raised.exception.args,
                    ("live_e2e_command_failed",),
                )
                self.assertEqual(
                    str(raised.exception),
                    "live_e2e_command_failed",
                )
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)
                rendered = "".join(traceback.format_exception(raised.exception))
                self.assertNotIn(sensitive_marker, rendered)
                self.assertNotIn(parser_detail, rendered)
                self.assertNotIn("driver.invalid", rendered)
                subprocess_run.assert_called_once_with(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(subprocess_run.call_count, 1)
                self.assertIs(subprocess_run.call_args.args[0], command)
                self.assertEqual(json_loads.call_count, 1)
                self.assertEqual(command, command_before)
                self.assertEqual(
                    tuple(id(value) for value in command),
                    command_element_ids_before,
                )
                self.assertIs(check, check_before)
                self.assertEqual(vars(completed), completed_before)
                self.assertIs(completed.args, command)

    def test_run_command_rejects_invalid_or_hooked_inputs_before_subprocess_without_hooks(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_run_command_guards",
            SCRIPT_PATH,
        )
        sensitive_marker = "synthetic-sensitive-run-command-marker"

        class CommandProbe:
            def __init__(self) -> None:
                self.call_counts = {
                    "bool": 0,
                    "iter": 0,
                    "len": 0,
                    "getitem": 0,
                }
                self.sentinel_state = {
                    "phase": "before",
                    "items": ["unchanged"],
                }

            def _fail(self, name: str) -> None:
                self.call_counts[name] += 1
                self.sentinel_state["phase"] = f"{name}-called"
                raise AssertionError(sensitive_marker)

            def __bool__(self) -> bool:
                self._fail("bool")

            def __iter__(self) -> object:
                self._fail("iter")

            def __len__(self) -> int:
                self._fail("len")

            def __getitem__(self, _index: object) -> object:
                self._fail("getitem")

        class HookedList(list[object]):
            def __init__(self, values: list[object]) -> None:
                super().__init__(values)
                self.call_counts = {
                    "bool": 0,
                    "iter": 0,
                    "len": 0,
                    "getitem": 0,
                }
                self.sentinel_state = {
                    "phase": "before",
                    "items": ["unchanged"],
                }

            def _fail(self, name: str) -> None:
                self.call_counts[name] += 1
                self.sentinel_state["phase"] = f"{name}-called"
                raise AssertionError(sensitive_marker)

            def __bool__(self) -> bool:
                self._fail("bool")

            def __iter__(self) -> object:
                self._fail("iter")

            def __len__(self) -> int:
                self._fail("len")

            def __getitem__(self, _index: object) -> object:
                self._fail("getitem")

        class StringProbe(str):
            def __new__(cls, value: str):
                instance = super().__new__(cls, value)
                instance.call_counts = {
                    "bool": 0,
                    "eq": 0,
                    "str": 0,
                    "encode": 0,
                }
                instance.sentinel_state = {
                    "phase": "before",
                    "items": ["unchanged"],
                }
                return instance

            def _fail(self, name: str) -> None:
                self.call_counts[name] += 1
                self.sentinel_state["phase"] = f"{name}-called"
                raise AssertionError(sensitive_marker)

            def __bool__(self) -> bool:
                self._fail("bool")

            def __eq__(self, _other: object) -> bool:
                self._fail("eq")

            def __str__(self) -> str:
                self._fail("str")

            def encode(self, *_: object, **__: object) -> bytes:
                self._fail("encode")

        class NonStringProbe:
            def __init__(self) -> None:
                self.call_counts = {
                    "bool": 0,
                    "str": 0,
                }
                self.sentinel_state = {
                    "phase": "before",
                    "items": ["unchanged"],
                }

            def _fail(self, name: str) -> None:
                self.call_counts[name] += 1
                self.sentinel_state["phase"] = f"{name}-called"
                raise AssertionError(sensitive_marker)

            def __bool__(self) -> bool:
                self._fail("bool")

            def __str__(self) -> str:
                self._fail("str")

        class CheckProbe:
            def __init__(self) -> None:
                self.bool_call_count = 0
                self.sentinel_state = {
                    "phase": "before",
                    "items": ["unchanged"],
                }

            def __bool__(self) -> bool:
                self.bool_call_count += 1
                self.sentinel_state["phase"] = "bool-called"
                raise AssertionError(sensitive_marker)

        def value_state(value: object) -> tuple[object, ...]:
            if isinstance(value, str):
                return (
                    id(value),
                    type(value),
                    str.encode(value),
                )
            return (
                id(value),
                type(value),
            )

        def command_state(command: object) -> tuple[object, ...]:
            if isinstance(command, list):
                values = tuple(value_state(value) for value in list.__iter__(command))
                attrs = copy.deepcopy(vars(command)) if type(command) is not list else {}
                return (
                    type(command),
                    values,
                    attrs,
                )
            if type(command) is tuple:
                return (
                    type(command),
                    tuple(value_state(value) for value in command),
                )
            return (
                type(command),
                id(command),
                copy.deepcopy(vars(command)),
            )

        command_probe = CommandProbe()
        hooked_list = HookedList(["docker", "version"])
        string_probe = StringProbe(sensitive_marker)
        non_string_probe = NonStringProbe()
        check_probe = CheckProbe()
        cases = (
            ("empty_list", [], True, ()),
            ("tuple_command", ("docker", "version"), True, ()),
            ("command_probe", command_probe, True, (command_probe,)),
            ("list_subclass", hooked_list, True, (hooked_list,)),
            ("empty_element", ["docker", ""], True, ()),
            (
                "string_subclass_element",
                ["docker", string_probe],
                True,
                (string_probe,),
            ),
            (
                "non_string_element",
                ["docker", non_string_probe],
                True,
                (non_string_probe,),
            ),
            ("wrong_type_check", ["docker", "version"], 1, ()),
            (
                "check_truthiness_probe",
                ["docker", "version"],
                check_probe,
                (check_probe,),
            ),
        )

        for case_name, command, check, probes in cases:
            with self.subTest(case=case_name):
                command_before = command_state(command)
                check_before = (
                    copy.deepcopy(vars(check)) if isinstance(check, CheckProbe) else check
                )
                probe_attrs_before = tuple((probe, copy.deepcopy(vars(probe))) for probe in probes)
                completed = subprocess.CompletedProcess(
                    args=["synthetic"],
                    returncode=0,
                    stdout="",
                    stderr="",
                )

                with (
                    mock.patch.object(
                        module.subprocess,
                        "run",
                        return_value=completed,
                    ) as subprocess_run,
                    self.assertRaises(RuntimeError) as raised,
                ):
                    module._run_command(command, check=check)

                self.assertIs(type(raised.exception), RuntimeError)
                self.assertEqual(
                    str(raised.exception),
                    "live_e2e_command_invalid",
                )
                self.assertNotIn(sensitive_marker, str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)
                self.assertTrue(raised.exception.__suppress_context__)
                subprocess_run.assert_not_called()
                self.assertEqual(command_state(command), command_before)
                if isinstance(check, CheckProbe):
                    self.assertEqual(vars(check), check_before)
                else:
                    self.assertIs(check, check_before)
                for probe, attrs_before in probe_attrs_before:
                    self.assertEqual(vars(probe), attrs_before)

    def test_runner_immutable_image_id_reaches_nested_live_postgresql_command(
        self,
    ) -> None:
        module = _load_module("connected_runtime_postgres_live_e2e_image", SCRIPT_PATH)
        runner_source = RUNNER_PATH.read_text(encoding="utf-8")
        script_source = SCRIPT_PATH.read_text(encoding="utf-8")
        runner_image_id = f"sha256:{'a' * 64}"
        expected_report = _valid_report(module)
        commands: list[list[str]] = []
        nested_output_paths: list[Path] = []

        with tempfile.TemporaryDirectory(prefix="formowl-live-image-") as temporary:
            output_path = Path(temporary) / "live-report.json"

            def fake_run_command(
                command: list[str],
                *,
                check: bool = True,
            ) -> subprocess.CompletedProcess[str]:
                del check
                commands.append(command)
                if "/workspace/scripts/connected_runtime_postgres_live_e2e.py" in command:
                    nested_output = Path(command[command.index("--output") + 1])
                    self.assertEqual(nested_output.parent, Path("/out"))
                    exchange_mount = next(
                        Path(value.removesuffix(":/out"))
                        for value in command
                        if value.endswith(":/out")
                    )
                    host_nested_output = exchange_mount / nested_output.name
                    nested_output_paths.append(host_nested_output)
                    host_nested_output.write_text(
                        json.dumps(
                            expected_report,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                mock.patch.dict(
                    os.environ,
                    {"FORMOWL_RUNNER_IMAGE_ID": runner_image_id},
                    clear=False,
                ),
                mock.patch.object(module, "_run_command", side_effect=fake_run_command),
            ):
                self.assertEqual(
                    module.run_live_e2e(
                        output_path,
                        runner_image_id=runner_image_id,
                    ),
                    expected_report,
                )
            self.assertEqual(len(nested_output_paths), 1)
            self.assertFalse(nested_output_paths[0].is_relative_to(output_path.parent))
            self.assertFalse(nested_output_paths[0].exists())
            published_report = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(published_report, expected_report)
            self.assertTrue(module.validate_report(published_report)["passed"])

        nested_commands = [
            command
            for command in commands
            if "/workspace/scripts/connected_runtime_postgres_live_e2e.py" in command
        ]
        self.assertEqual(len(nested_commands), 1)
        nested_command = nested_commands[0]
        self.assertEqual(nested_command[nested_command.index("python") - 1], runner_image_id)
        self.assertNotIn("formowl-dev:local", nested_command)
        self.assertIn(f"FORMOWL_RUNNER_IMAGE_ID={runner_image_id}", nested_command)
        inside_index = nested_command.index("--inside")
        self.assertEqual(
            nested_command[inside_index : inside_index + 3],
            ["--inside", "--runner-image-id", runner_image_id],
        )
        self.assertIn(f"{module.ROOT}:/workspace:ro", nested_command)
        self.assertIn('--runner-image-id "$FORMOWL_RUNNER_IMAGE_ID"', runner_source)
        self.assertNotIn('DEV_IMAGE = "formowl-dev:local"', script_source)
        postgres_commands = [
            command for command in commands if "POSTGRES_HOST_AUTH_METHOD=trust" in command
        ]
        self.assertEqual(len(postgres_commands), 1)
        self.assertEqual(postgres_commands[0][-1], module.PINNED_POSTGRES_IMAGE)
        self.assertNotIn("pgvector/pgvector:0.8.0-pg17", script_source)

    def test_runner_campaign_mount_uses_frozen_snapshot_instead_of_live_root(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_campaign_source",
            SCRIPT_PATH,
        )
        runner_image_id = f"sha256:{'a' * 64}"
        expected_report = _valid_report(module)
        valid_bytes = (
            json.dumps(
                expected_report,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
        commands: list[list[str]] = []

        with tempfile.TemporaryDirectory(
            prefix="formowl-issue20-containerized-evidence-runner-",
            dir="/tmp",
        ) as temporary:
            scratch_root = Path(temporary)
            source_root = scratch_root / "campaign" / "source-snapshot"
            pin_path = scratch_root / "trust-inputs" / "campaign-source-pin.json"
            output_path = scratch_root / "reports" / "live-report.json"
            _write_campaign_source(source_root)
            pin_hash = _write_campaign_pin(module, pin_path, runner_image_id)

            def fake_run_command(
                command: list[str],
                *,
                check: bool = True,
            ) -> subprocess.CompletedProcess[str]:
                del check
                commands.append(command)
                if "/workspace/scripts/connected_runtime_postgres_live_e2e.py" in command:
                    nested_output = Path(command[command.index("--output") + 1])
                    exchange_mount = next(
                        Path(value.removesuffix(":/out"))
                        for value in command
                        if value.endswith(":/out")
                    )
                    (exchange_mount / nested_output.name).write_bytes(valid_bytes)
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "FORMOWL_RUNNER_CAMPAIGN_PIN": str(pin_path),
                        "FORMOWL_RUNNER_CAMPAIGN_PIN_SHA256": pin_hash,
                        "FORMOWL_RUNNER_IMAGE_ID": runner_image_id,
                    },
                    clear=False,
                ),
                mock.patch.object(module, "_run_command", side_effect=fake_run_command),
            ):
                report = module.run_live_e2e(
                    output_path,
                    runner_image_id=runner_image_id,
                )

            nested_commands = [
                command
                for command in commands
                if "/workspace/scripts/connected_runtime_postgres_live_e2e.py" in command
            ]
            self.assertEqual(len(nested_commands), 1)
            nested_command = nested_commands[0]
            self.assertNotEqual(source_root, module.ROOT)
            self.assertIn(f"{source_root}:/workspace:ro", nested_command)
            self.assertNotIn(f"{module.ROOT}:/workspace:ro", nested_command)
            self.assertEqual(report, expected_report)
            self.assertEqual(
                json.loads(output_path.read_text(encoding="utf-8")),
                expected_report,
            )
            rendered = output_path.read_text(encoding="utf-8")
            self.assertNotIn(str(source_root), rendered)
            self.assertNotIn(str(module.ROOT), rendered)

    def test_nested_campaign_exec_runs_only_the_verified_private_copy(self) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_verified_copy",
            SCRIPT_PATH,
        )
        runner_image_id = f"sha256:{'a' * 64}"

        with tempfile.TemporaryDirectory(
            prefix="formowl-issue20-containerized-evidence-runner-",
            dir="/tmp",
        ) as temporary:
            scratch_root = Path(temporary)
            source_root = scratch_root / "campaign" / "source-snapshot"
            pin_path = scratch_root / "trust-inputs" / "campaign-source-pin.json"
            destination_parent = scratch_root / "nested-tmp"
            marker_path = scratch_root / "verified-target.json"
            _write_campaign_source(source_root)
            target_path = source_root / "scripts" / "verified_campaign_probe.py"
            target_path.write_text(
                "\n".join(
                    (
                        "import json",
                        "from pathlib import Path",
                        "import sys",
                        "Path(sys.argv[1]).write_text(",
                        "    json.dumps({",
                        "        'cwd': str(Path.cwd()),",
                        "        'script': str(Path(__file__).resolve()),",
                        "    }, sort_keys=True),",
                        "    encoding='utf-8',",
                        ")",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            destination_parent.mkdir(mode=0o700)
            pin_hash = _seal_campaign_source(
                module,
                source_root,
                pin_path,
                runner_image_id,
            )

            result = _run_nested_campaign_exec(
                module,
                source_root=source_root,
                pin_path=pin_path,
                pin_hash=pin_hash,
                runner_image_id=runner_image_id,
                destination_parent=destination_parent,
                target_path=target_path,
                target_arguments=(str(marker_path),),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, "")
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            verified_root = Path(marker["cwd"])
            verified_script = Path(marker["script"])
            self.assertTrue(verified_root.is_relative_to(destination_parent))
            self.assertTrue(verified_script.is_relative_to(verified_root))
            self.assertFalse(verified_root.is_relative_to(source_root))
            self.assertEqual(
                verified_script.relative_to(verified_root),
                Path("scripts/verified_campaign_probe.py"),
            )

    def test_nested_campaign_exec_rejects_post_verification_mutation(self) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_post_verify_mutation",
            SCRIPT_PATH,
        )
        runner_image_id = f"sha256:{'a' * 64}"

        with tempfile.TemporaryDirectory(
            prefix="formowl-issue20-containerized-evidence-runner-",
            dir="/tmp",
        ) as temporary:
            scratch_root = Path(temporary)
            source_root = scratch_root / "campaign" / "source-snapshot"
            pin_path = scratch_root / "trust-inputs" / "campaign-source-pin.json"
            destination_parent = scratch_root / "nested-tmp"
            marker_path = scratch_root / "must-not-exist"
            _write_campaign_source(source_root)
            target_path = source_root / "scripts" / "verified_campaign_probe.py"
            target_path.write_text(
                "from pathlib import Path\n"
                "import sys\n"
                "Path(sys.argv[1]).write_text('executed', encoding='utf-8')\n",
                encoding="utf-8",
            )
            destination_parent.mkdir(mode=0o700)
            pin_hash = _seal_campaign_source(
                module,
                source_root,
                pin_path,
                runner_image_id,
            )
            mutated_path = source_root / "scripts" / "connected_runtime_postgres_live_e2e.py"
            mutated_path.write_text(
                "post-verification same-uid mutation\n",
                encoding="utf-8",
            )

            result = _run_nested_campaign_exec(
                module,
                source_root=source_root,
                pin_path=pin_path,
                pin_hash=pin_hash,
                runner_image_id=runner_image_id,
                destination_parent=destination_parent,
                target_path=target_path,
                target_arguments=(str(marker_path),),
            )

            self.assertEqual(result.returncode, 70)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, "")
            self.assertFalse(marker_path.exists())

    def test_nested_campaign_exec_rejects_symlink_and_wrong_owned_entries(self) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_unsafe_snapshot_entries",
            SCRIPT_PATH,
        )
        runner_image_id = f"sha256:{'a' * 64}"
        cases = ["nested_symlink"]
        if os.geteuid() == 0:
            cases.append("wrong_owner")

        for name in cases:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory(
                    prefix="formowl-issue20-containerized-evidence-runner-",
                    dir="/tmp",
                ) as temporary:
                    scratch_root = Path(temporary)
                    source_root = scratch_root / "campaign" / "source-snapshot"
                    pin_path = scratch_root / "trust-inputs" / "campaign-source-pin.json"
                    destination_parent = scratch_root / "nested-tmp"
                    marker_path = scratch_root / "must-not-exist"
                    _write_campaign_source(source_root)
                    target_path = source_root / "scripts" / "verified_campaign_probe.py"
                    target_path.write_text(
                        "from pathlib import Path\n"
                        "import sys\n"
                        "Path(sys.argv[1]).write_text('executed', encoding='utf-8')\n",
                        encoding="utf-8",
                    )
                    owned_path = source_root / "python" / "owned.py"
                    owned_path.parent.mkdir(parents=True)
                    owned_path.write_text("sealed = True\n", encoding="utf-8")
                    destination_parent.mkdir(mode=0o700)
                    pin_hash = _seal_campaign_source(
                        module,
                        source_root,
                        pin_path,
                        runner_image_id,
                    )

                    if name == "nested_symlink":
                        external = scratch_root / "external.py"
                        external.write_text("sealed = False\n", encoding="utf-8")
                        owned_path.unlink()
                        owned_path.symlink_to(external)
                    else:
                        os.chown(owned_path, 65534, -1)

                    result = _run_nested_campaign_exec(
                        module,
                        source_root=source_root,
                        pin_path=pin_path,
                        pin_hash=pin_hash,
                        runner_image_id=runner_image_id,
                        destination_parent=destination_parent,
                        target_path=target_path,
                        target_arguments=(str(marker_path),),
                    )

                    self.assertEqual(result.returncode, 70)
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(result.stderr, "")
                    self.assertFalse(marker_path.exists())

    def test_runner_campaign_source_rejects_invalid_pin_and_snapshot_layouts(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_campaign_source_invalid",
            SCRIPT_PATH,
        )
        runner_image_id = f"sha256:{'a' * 64}"
        valid_pin_hash = f"sha256:{'b' * 64}"
        cases = (
            "missing_pin",
            "non_absolute_pin",
            "symlink_pin",
            "wrong_pin_layout",
            "malformed_pin",
            "duplicate_pin",
            "missing_source",
            "symlink_source",
        )

        for name in cases:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory(
                    prefix="formowl-issue20-containerized-evidence-runner-",
                    dir="/tmp",
                ) as temporary:
                    scratch_root = Path(temporary)
                    pin_path = scratch_root / "trust-inputs" / "campaign-source-pin.json"
                    source_root = scratch_root / "campaign" / "source-snapshot"
                    environment = {
                        "FORMOWL_RUNNER_IMAGE_ID": runner_image_id,
                    }
                    verifier_expected = False

                    if name == "missing_pin":
                        environment.update(
                            {
                                "FORMOWL_RUNNER_CAMPAIGN_PIN": str(pin_path),
                                "FORMOWL_RUNNER_CAMPAIGN_PIN_SHA256": valid_pin_hash,
                            }
                        )
                    elif name == "non_absolute_pin":
                        environment.update(
                            {
                                "FORMOWL_RUNNER_CAMPAIGN_PIN": (
                                    "trust-inputs/campaign-source-pin.json"
                                ),
                                "FORMOWL_RUNNER_CAMPAIGN_PIN_SHA256": valid_pin_hash,
                            }
                        )
                    elif name == "symlink_pin":
                        target = scratch_root / "campaign-pin-target.json"
                        target_hash = _write_campaign_pin(
                            module,
                            target,
                            runner_image_id,
                        )
                        pin_path.parent.mkdir(parents=True)
                        pin_path.symlink_to(target)
                        environment.update(
                            {
                                "FORMOWL_RUNNER_CAMPAIGN_PIN": str(pin_path),
                                "FORMOWL_RUNNER_CAMPAIGN_PIN_SHA256": target_hash,
                            }
                        )
                    elif name == "wrong_pin_layout":
                        pin_path = scratch_root / "wrong-trust-inputs" / "campaign-source-pin.json"
                        pin_hash = _write_campaign_pin(
                            module,
                            pin_path,
                            runner_image_id,
                        )
                        environment.update(
                            {
                                "FORMOWL_RUNNER_CAMPAIGN_PIN": str(pin_path),
                                "FORMOWL_RUNNER_CAMPAIGN_PIN_SHA256": pin_hash,
                            }
                        )
                    elif name == "malformed_pin":
                        pin_hash = _write_campaign_pin(
                            module,
                            pin_path,
                            runner_image_id,
                            payload=[],
                        )
                        environment.update(
                            {
                                "FORMOWL_RUNNER_CAMPAIGN_PIN": str(pin_path),
                                "FORMOWL_RUNNER_CAMPAIGN_PIN_SHA256": pin_hash,
                            }
                        )
                    elif name == "duplicate_pin":
                        pin_path.parent.mkdir(parents=True)
                        pin_bytes = (
                            b'{"artifact_type":"'
                            + module._CAMPAIGN_PIN_ARTIFACT_TYPE.encode()
                            + b'","artifact_type":"duplicate"}\n'
                        )
                        pin_path.write_bytes(pin_bytes)
                        pin_path.chmod(0o400)
                        pin_hash = "sha256:" + hashlib.sha256(pin_bytes).hexdigest()
                        environment.update(
                            {
                                "FORMOWL_RUNNER_CAMPAIGN_PIN": str(pin_path),
                                "FORMOWL_RUNNER_CAMPAIGN_PIN_SHA256": pin_hash,
                            }
                        )
                    elif name == "missing_source":
                        pin_hash = _write_campaign_pin(
                            module,
                            pin_path,
                            runner_image_id,
                        )
                        environment.update(
                            {
                                "FORMOWL_RUNNER_CAMPAIGN_PIN": str(pin_path),
                                "FORMOWL_RUNNER_CAMPAIGN_PIN_SHA256": pin_hash,
                            }
                        )
                        verifier_expected = True
                    else:
                        pin_hash = _write_campaign_pin(
                            module,
                            pin_path,
                            runner_image_id,
                        )
                        target = scratch_root / "real-source"
                        _write_campaign_source(target)
                        source_root.parent.mkdir(parents=True)
                        source_root.symlink_to(target, target_is_directory=True)
                        environment.update(
                            {
                                "FORMOWL_RUNNER_CAMPAIGN_PIN": str(pin_path),
                                "FORMOWL_RUNNER_CAMPAIGN_PIN_SHA256": pin_hash,
                            }
                        )

                    output_path = scratch_root / "reports" / "live-report.json"
                    output_helper_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
                    output_path.parent.mkdir(parents=True)
                    output_path.write_bytes(b"stale-public-report\n")
                    output_helper_path.write_bytes(b"stale-helper\n")
                    verifier_failure = subprocess.CompletedProcess(
                        ["docker", "run"],
                        41,
                        "",
                        "",
                    )

                    with (
                        mock.patch.dict(os.environ, environment, clear=False),
                        mock.patch.object(
                            module,
                            "_run_command",
                            return_value=verifier_failure,
                        ) as run_command,
                        self.assertRaisesRegex(
                            RuntimeError,
                            "^live_e2e_campaign_source_invalid$",
                        ),
                    ):
                        module.run_live_e2e(
                            output_path,
                            runner_image_id=runner_image_id,
                        )

                    if verifier_expected:
                        run_command.assert_called_once()
                        verifier_command = run_command.call_args.args[0]
                        self.assertIn("--mount", verifier_command)
                        self.assertIn(
                            (f"type=bind,src={scratch_root}," "dst=/campaign-root,readonly"),
                            verifier_command,
                        )
                    else:
                        run_command.assert_not_called()
                    self.assertFalse(output_path.exists())
                    self.assertFalse(output_helper_path.exists())
                    self.assertFalse(
                        any(
                            path.name.startswith("live-report.json")
                            for path in output_path.parent.iterdir()
                        )
                    )

    def test_failed_live_e2e_cannot_retain_or_reuse_stale_valid_output(self) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_stale_output",
            SCRIPT_PATH,
        )
        runner_image_id = f"sha256:{'a' * 64}"
        with tempfile.TemporaryDirectory(prefix="formowl-live-stale-output-") as temporary:
            output_path = Path(temporary) / "live-report.json"
            stale_bytes = (
                json.dumps(
                    _valid_report(module),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode()
            output_path.write_bytes(stale_bytes)
            self.assertTrue(
                module.validate_report(json.loads(stale_bytes))["passed"],
            )

            def fake_run_command(
                command: list[str],
                *,
                check: bool = True,
            ) -> subprocess.CompletedProcess[str]:
                del check
                if "/workspace/scripts/connected_runtime_postgres_live_e2e.py" in command:
                    raise RuntimeError("live_e2e_nested_runtime_failed")
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                mock.patch.dict(
                    os.environ,
                    {"FORMOWL_RUNNER_IMAGE_ID": runner_image_id},
                    clear=False,
                ),
                mock.patch.object(module, "_run_command", side_effect=fake_run_command),
                self.assertRaisesRegex(
                    RuntimeError,
                    "^live_e2e_nested_runtime_failed$",
                ),
            ):
                module.run_live_e2e(
                    output_path,
                    runner_image_id=runner_image_id,
                )

            self.assertFalse(output_path.exists())
            with self.assertRaises(FileNotFoundError):
                output_path.read_bytes()
            remaining_artifacts = list(Path(temporary).iterdir())
            self.assertEqual(remaining_artifacts, [])
            self.assertNotIn(
                stale_bytes,
                [path.read_bytes() for path in remaining_artifacts if path.is_file()],
            )

    def test_live_e2e_publishes_on_report_mount_without_cross_mount_path_replace(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_cross_mount_publication",
            SCRIPT_PATH,
        )
        runner_image_id = f"sha256:{'a' * 64}"
        expected_report = _valid_report(module)
        valid_bytes = (
            json.dumps(
                expected_report,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
        real_replace = os.replace

        with tempfile.TemporaryDirectory(
            prefix="formowl-live-cross-mount-publication-",
        ) as temporary:
            output_path = Path(temporary) / "live-report.json"
            output_helper_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
            output_path.write_bytes(valid_bytes)
            output_helper_path.write_bytes(b"stale-helper\n")

            def fake_run_command(
                command: list[str],
                *,
                check: bool = True,
            ) -> subprocess.CompletedProcess[str]:
                del check
                if "/workspace/scripts/connected_runtime_postgres_live_e2e.py" in command:
                    nested_output = Path(command[command.index("--output") + 1])
                    exchange_mount = next(
                        Path(value.removesuffix(":/out"))
                        for value in command
                        if value.endswith(":/out")
                    )
                    (exchange_mount / nested_output.name).write_bytes(valid_bytes)
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                mock.patch.dict(
                    os.environ,
                    {"FORMOWL_RUNNER_IMAGE_ID": runner_image_id},
                    clear=False,
                ),
                mock.patch.object(module, "_run_command", side_effect=fake_run_command),
                mock.patch.object(
                    Path,
                    "replace",
                    autospec=True,
                    side_effect=OSError(
                        errno.EXDEV,
                        "synthetic cross-mount replace failure",
                    ),
                ) as path_replace,
                mock.patch.object(
                    json_files_module.os,
                    "replace",
                    wraps=real_replace,
                ) as atomic_replace,
            ):
                report = module.run_live_e2e(
                    output_path,
                    runner_image_id=runner_image_id,
                )

            self.assertEqual(report, expected_report)
            path_replace.assert_not_called()
            atomic_replace.assert_called_once()
            replace_call = atomic_replace.call_args
            self.assertEqual(
                replace_call.args,
                (output_helper_path.name, output_path.name),
            )
            self.assertEqual(
                replace_call.kwargs["src_dir_fd"],
                replace_call.kwargs["dst_dir_fd"],
            )
            self.assertEqual(
                json.loads(output_path.read_text(encoding="utf-8")),
                expected_report,
            )
            self.assertFalse(output_helper_path.exists())
            self.assertEqual([path.name for path in Path(temporary).iterdir()], [output_path.name])

    def test_final_mount_atomic_publication_failures_remove_public_artifacts(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_atomic_publication_failures",
            SCRIPT_PATH,
        )
        runner_image_id = f"sha256:{'a' * 64}"
        expected_report = _valid_report(module)
        valid_bytes = (
            json.dumps(
                expected_report,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
        real_close = os.close
        real_atomic_write = module.write_json_atomic

        def fail_first_close() -> tuple[object, dict[str, int]]:
            state = {"calls": 0}

            def close(descriptor: int) -> None:
                state["calls"] += 1
                if state["calls"] == 1:
                    raise OSError("sensitive close failure")
                real_close(descriptor)

            return close, state

        def fail_second_fsync() -> tuple[object, dict[str, int]]:
            state = {"calls": 0}
            real_fsync = os.fsync

            def fsync(descriptor: int) -> None:
                state["calls"] += 1
                if state["calls"] == 2:
                    raise OSError("sensitive directory fsync failure")
                real_fsync(descriptor)

            return fsync, state

        cases = (
            (
                "write",
                "write",
                OSError("sensitive write failure"),
                None,
            ),
            (
                "fsync",
                "fsync",
                OSError("sensitive fsync failure"),
                None,
            ),
            (
                "directory_fsync",
                "fsync",
                None,
                fail_second_fsync,
            ),
            (
                "close",
                "close",
                None,
                fail_first_close,
            ),
            (
                "replace",
                "replace",
                OSError(errno.EXDEV, "sensitive replace failure"),
                None,
            ),
        )

        for name, operation, side_effect, factory in cases:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory(
                    prefix=f"formowl-live-atomic-{name}-",
                ) as temporary:
                    output_path = Path(temporary) / "live-report.json"
                    output_helper_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
                    output_path.write_bytes(valid_bytes)
                    output_helper_path.write_bytes(b"stale-helper\n")

                    def fake_run_command(
                        command: list[str],
                        *,
                        check: bool = True,
                    ) -> subprocess.CompletedProcess[str]:
                        del check
                        if "/workspace/scripts/connected_runtime_postgres_live_e2e.py" in command:
                            nested_output = Path(command[command.index("--output") + 1])
                            exchange_mount = next(
                                Path(value.removesuffix(":/out"))
                                for value in command
                                if value.endswith(":/out")
                            )
                            (exchange_mount / nested_output.name).write_bytes(valid_bytes)
                        return subprocess.CompletedProcess(command, 0, "", "")

                    close_state: dict[str, int] | None = None
                    operation_side_effect = side_effect
                    if factory is not None:
                        operation_side_effect, close_state = factory()

                    def fail_during_atomic_write(path: Path, payload: object) -> None:
                        with mock.patch.object(
                            json_files_module.os,
                            operation,
                            side_effect=operation_side_effect,
                        ):
                            real_atomic_write(path, payload)

                    with ExitStack() as stack:
                        stack.enter_context(
                            mock.patch.dict(
                                os.environ,
                                {"FORMOWL_RUNNER_IMAGE_ID": runner_image_id},
                                clear=False,
                            )
                        )
                        stack.enter_context(
                            mock.patch.object(
                                module,
                                "_run_command",
                                side_effect=fake_run_command,
                            )
                        )
                        validation = stack.enter_context(
                            mock.patch.object(
                                module,
                                "validate_report",
                                wraps=module.validate_report,
                            )
                        )
                        stack.enter_context(
                            mock.patch.object(
                                module,
                                "write_json_atomic",
                                side_effect=fail_during_atomic_write,
                            )
                        )
                        with self.assertRaisesRegex(
                            RuntimeError,
                            "^live_e2e_report_persist_failed$",
                        ) as raised:
                            module.run_live_e2e(
                                output_path,
                                runner_image_id=runner_image_id,
                            )

                    self.assertNotIn("sensitive", str(raised.exception))
                    validation.assert_called_once_with(expected_report)
                    if close_state is not None:
                        self.assertGreaterEqual(close_state["calls"], 3)
                    self.assertFalse(output_path.exists())
                    self.assertFalse(output_helper_path.exists())
                    self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_publication_cleanup_retry_preserves_primary_error_and_removes_artifacts(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_public_cleanup_retry",
            SCRIPT_PATH,
        )
        runner_image_id = f"sha256:{'a' * 64}"
        valid_bytes = (
            json.dumps(
                _valid_report(module),
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
        original_unlink = Path.unlink

        with tempfile.TemporaryDirectory(
            prefix="formowl-live-public-cleanup-retry-",
        ) as temporary:
            output_path = Path(temporary) / "live-report.json"
            output_helper_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
            output_path.write_bytes(valid_bytes)
            output_helper_path.write_bytes(b"stale-helper\n")
            publication_started = False
            cleanup_failure_injected = False

            def fake_run_command(
                command: list[str],
                *,
                check: bool = True,
            ) -> subprocess.CompletedProcess[str]:
                del check
                if "/workspace/scripts/connected_runtime_postgres_live_e2e.py" in command:
                    nested_output = Path(command[command.index("--output") + 1])
                    exchange_mount = next(
                        Path(value.removesuffix(":/out"))
                        for value in command
                        if value.endswith(":/out")
                    )
                    (exchange_mount / nested_output.name).write_bytes(valid_bytes)
                return subprocess.CompletedProcess(command, 0, "", "")

            def fail_atomic_write(path: Path, _payload: object) -> None:
                nonlocal publication_started
                publication_started = True
                path.write_bytes(b"partial-public-report\n")
                path.with_suffix(f"{path.suffix}.tmp").write_bytes(b"partial-helper\n")
                raise OSError("sensitive primary persistence failure")

            def flaky_unlink(path: Path, *, missing_ok: bool = False) -> None:
                nonlocal cleanup_failure_injected
                if publication_started and not cleanup_failure_injected and path == output_path:
                    cleanup_failure_injected = True
                    raise OSError("sensitive cleanup failure")
                original_unlink(path, missing_ok=missing_ok)

            with (
                mock.patch.dict(
                    os.environ,
                    {"FORMOWL_RUNNER_IMAGE_ID": runner_image_id},
                    clear=False,
                ),
                mock.patch.object(module, "_run_command", side_effect=fake_run_command),
                mock.patch.object(
                    module,
                    "write_json_atomic",
                    side_effect=fail_atomic_write,
                ),
                mock.patch.object(
                    Path,
                    "unlink",
                    autospec=True,
                    side_effect=flaky_unlink,
                ),
                self.assertRaisesRegex(
                    RuntimeError,
                    "^live_e2e_report_persist_failed$",
                ) as raised,
            ):
                module.run_live_e2e(
                    output_path,
                    runner_image_id=runner_image_id,
                )

            self.assertTrue(cleanup_failure_injected)
            self.assertNotIn("sensitive", str(raised.exception))
            self.assertFalse(output_path.exists())
            self.assertFalse(output_helper_path.exists())
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_live_e2e_publication_failures_remove_final_and_partial_artifacts(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_publication_failures",
            SCRIPT_PATH,
        )
        runner_image_id = f"sha256:{'a' * 64}"
        valid_bytes = (
            json.dumps(
                _valid_report(module),
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
        cases = (
            ("missing", None, False, "live_e2e_report_missing"),
            ("parse", b"{not-json\n", False, "live_e2e_report_parse_failed"),
            ("validation", b"{}\n", False, "live_e2e_report_validation_failed"),
            ("persistence", valid_bytes, True, "live_e2e_report_persist_failed"),
        )

        for name, nested_bytes, fail_persistence, expected_error in cases:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory(
                    prefix=f"formowl-live-publication-{name}-",
                ) as temporary:
                    output_path = Path(temporary) / "live-report.json"
                    output_helper_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
                    persistence_artifacts: list[Path] = []
                    output_path.write_bytes(valid_bytes)
                    output_helper_path.write_bytes(b"stale-helper\n")

                    def fake_run_command(
                        command: list[str],
                        *,
                        check: bool = True,
                    ) -> subprocess.CompletedProcess[str]:
                        del check
                        if "/workspace/scripts/connected_runtime_postgres_live_e2e.py" in command:
                            nested_output = Path(command[command.index("--output") + 1])
                            if nested_bytes is not None:
                                exchange_mount = next(
                                    Path(value.removesuffix(":/out"))
                                    for value in command
                                    if value.endswith(":/out")
                                )
                                (exchange_mount / nested_output.name).write_bytes(nested_bytes)
                        return subprocess.CompletedProcess(command, 0, "", "")

                    def fail_atomic_write(path: Path, _payload: object) -> None:
                        helper_path = path.with_suffix(f"{path.suffix}.tmp")
                        path.write_bytes(b"partial-final\n")
                        helper_path.write_bytes(b"partial-helper\n")
                        persistence_artifacts.extend((path, helper_path))
                        raise OSError("sensitive persistence failure")

                    with ExitStack() as stack:
                        stack.enter_context(
                            mock.patch.dict(
                                os.environ,
                                {"FORMOWL_RUNNER_IMAGE_ID": runner_image_id},
                                clear=False,
                            )
                        )
                        stack.enter_context(
                            mock.patch.object(
                                module,
                                "_run_command",
                                side_effect=fake_run_command,
                            )
                        )
                        if fail_persistence:
                            stack.enter_context(
                                mock.patch.object(
                                    module,
                                    "write_json_atomic",
                                    side_effect=fail_atomic_write,
                                )
                            )
                        with self.assertRaisesRegex(
                            RuntimeError,
                            f"^{expected_error}$",
                        ):
                            module.run_live_e2e(
                                output_path,
                                runner_image_id=runner_image_id,
                            )

                    if fail_persistence:
                        self.assertEqual(len(persistence_artifacts), 2)
                        self.assertEqual(
                            persistence_artifacts,
                            [output_path, output_helper_path],
                        )
                        self.assertTrue(all(not path.exists() for path in persistence_artifacts))
                    else:
                        self.assertEqual(persistence_artifacts, [])
                    self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_cleanup_failure_does_not_replace_nested_runtime_error(self) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_cleanup_failure",
            SCRIPT_PATH,
        )
        runner_image_id = f"sha256:{'a' * 64}"
        valid_bytes = (
            json.dumps(
                _valid_report(module),
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
        nested_artifacts: list[Path] = []
        original_unlink = Path.unlink

        with tempfile.TemporaryDirectory(prefix="formowl-live-cleanup-error-") as temporary:
            output_path = Path(temporary) / "live-report.json"

            def fake_run_command(
                command: list[str],
                *,
                check: bool = True,
            ) -> subprocess.CompletedProcess[str]:
                del check
                if "/workspace/scripts/connected_runtime_postgres_live_e2e.py" in command:
                    exchange_mount = next(
                        Path(value.removesuffix(":/out"))
                        for value in command
                        if value.endswith(":/out")
                    )
                    nested_output = Path(command[command.index("--output") + 1])
                    host_nested_output = exchange_mount / nested_output.name
                    host_nested_helper = host_nested_output.with_suffix(
                        f"{host_nested_output.suffix}.tmp"
                    )
                    host_nested_output.write_bytes(valid_bytes)
                    host_nested_helper.write_bytes(b"partial-helper\n")
                    nested_artifacts.extend((host_nested_output, host_nested_helper))
                    raise RuntimeError("live_e2e_nested_runtime_failed")
                return subprocess.CompletedProcess(command, 0, "", "")

            def flaky_unlink(path: Path, *, missing_ok: bool = False) -> None:
                if path in nested_artifacts:
                    raise OSError("sensitive cleanup failure")
                original_unlink(path, missing_ok=missing_ok)

            with (
                mock.patch.dict(
                    os.environ,
                    {"FORMOWL_RUNNER_IMAGE_ID": runner_image_id},
                    clear=False,
                ),
                mock.patch.object(module, "_run_command", side_effect=fake_run_command),
                mock.patch.object(Path, "unlink", autospec=True, side_effect=flaky_unlink),
                self.assertRaisesRegex(
                    RuntimeError,
                    "^live_e2e_nested_runtime_failed$",
                ),
            ):
                module.run_live_e2e(
                    output_path,
                    runner_image_id=runner_image_id,
                )

            self.assertEqual(len(nested_artifacts), 2)
            self.assertTrue(all(not path.exists() for path in nested_artifacts))
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_output_isolation_failure_stops_before_outer_or_inner_execution(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_isolation_failure",
            SCRIPT_PATH,
        )
        runner_image_id = f"sha256:{'a' * 64}"
        original_unlink = Path.unlink

        for mode in ("outer", "inner"):
            with self.subTest(mode=mode):
                with tempfile.TemporaryDirectory(
                    prefix=f"formowl-live-isolation-{mode}-",
                ) as temporary:
                    output_path = Path(temporary) / "live-report.json"
                    output_path.write_bytes(b"stale-output\n")

                    def deny_output_unlink(
                        path: Path,
                        *,
                        missing_ok: bool = False,
                    ) -> None:
                        if path == output_path:
                            raise OSError("sensitive unlink failure")
                        original_unlink(path, missing_ok=missing_ok)

                    with (
                        mock.patch.object(
                            Path,
                            "unlink",
                            autospec=True,
                            side_effect=deny_output_unlink,
                        ),
                        mock.patch.object(module, "_run_command") as run_command,
                        mock.patch.object(
                            module,
                            "_load_inside_dependencies",
                        ) as load_inside_dependencies,
                        mock.patch.dict(
                            os.environ,
                            {"FORMOWL_RUNNER_IMAGE_ID": runner_image_id},
                            clear=True,
                        ),
                        self.assertRaisesRegex(
                            RuntimeError,
                            "^live_e2e_output_isolation_failed$",
                        ),
                    ):
                        if mode == "outer":
                            module.run_live_e2e(
                                output_path,
                                runner_image_id=runner_image_id,
                            )
                        else:
                            asyncio.run(module._run_inside(output_path))

                    run_command.assert_not_called()
                    load_inside_dependencies.assert_not_called()
                    self.assertEqual(output_path.read_bytes(), b"stale-output\n")

    def test_run_inside_early_failure_removes_stale_output_and_helper(self) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_inside_early_failure",
            SCRIPT_PATH,
        )
        with tempfile.TemporaryDirectory(
            prefix="formowl-live-inside-early-failure-",
        ) as temporary:
            output_path = Path(temporary) / "live-report.json"
            output_helper_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
            output_path.write_bytes(b"stale-output\n")
            output_helper_path.write_bytes(b"stale-helper\n")

            with (
                mock.patch.dict(os.environ, {}, clear=True),
                mock.patch.object(module, "_load_inside_dependencies"),
                self.assertRaisesRegex(
                    RuntimeError,
                    "^live_e2e_environment_missing$",
                ),
            ):
                asyncio.run(module._run_inside(output_path))

            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_execution_fail_fast_checks_isolate_stale_output_before_rejection(
        self,
    ) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_fail_fast_isolation",
            SCRIPT_PATH,
        )
        valid_image_id = f"sha256:{'a' * 64}"
        other_image_id = f"sha256:{'b' * 64}"
        valid_bytes = (
            json.dumps(
                _valid_report(module),
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
        cases = (
            (
                "outer_missing_runner",
                "outer",
                None,
                {"FORMOWL_RUNNER_IMAGE_ID": valid_image_id},
                None,
                "runner_image_id_required",
            ),
            (
                "outer_invalid_runner",
                "outer",
                "formowl-dev:local",
                {"FORMOWL_RUNNER_IMAGE_ID": "formowl-dev:local"},
                None,
                "runner_image_id_required",
            ),
            (
                "outer_missing_authority",
                "outer",
                valid_image_id,
                {},
                None,
                "runner_image_id_authority_missing",
            ),
            (
                "outer_authority_mismatch",
                "outer",
                valid_image_id,
                {"FORMOWL_RUNNER_IMAGE_ID": other_image_id},
                None,
                "runner_image_id_authority_mismatch",
            ),
            (
                "outer_postgres_pin_mismatch",
                "outer",
                valid_image_id,
                {"FORMOWL_RUNNER_IMAGE_ID": valid_image_id},
                "pgvector/pgvector:0.8.0-pg17",
                "postgres_image_contract_mismatch",
            ),
            (
                "inside_missing_runner",
                "inside",
                None,
                {"FORMOWL_RUNNER_IMAGE_ID": valid_image_id},
                None,
                "runner_image_id_required",
            ),
            (
                "inside_invalid_runner",
                "inside",
                "formowl-dev:local",
                {"FORMOWL_RUNNER_IMAGE_ID": "formowl-dev:local"},
                None,
                "runner_image_id_required",
            ),
            (
                "inside_missing_authority",
                "inside",
                valid_image_id,
                {},
                None,
                "runner_image_id_authority_missing",
            ),
            (
                "inside_authority_mismatch",
                "inside",
                valid_image_id,
                {"FORMOWL_RUNNER_IMAGE_ID": other_image_id},
                None,
                "runner_image_id_authority_mismatch",
            ),
        )

        for (
            name,
            mode,
            runner_image_id,
            environment,
            postgres_image,
            expected_error,
        ) in cases:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory(
                    prefix=f"formowl-live-fail-fast-{name}-",
                    dir=tempfile.gettempdir(),
                ) as temporary:
                    output_path = Path(temporary) / "live-report.json"
                    output_helper_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
                    output_path.write_bytes(valid_bytes)
                    output_helper_path.write_bytes(b"stale-helper\n")

                    with ExitStack() as stack:
                        stack.enter_context(mock.patch.dict(os.environ, environment, clear=True))
                        run_command = stack.enter_context(mock.patch.object(module, "_run_command"))
                        run_inside = stack.enter_context(mock.patch.object(module.asyncio, "run"))
                        if postgres_image is not None:
                            stack.enter_context(
                                mock.patch.object(
                                    module,
                                    "POSTGRES_IMAGE",
                                    postgres_image,
                                )
                            )

                        if mode == "outer":
                            with self.assertRaisesRegex(
                                RuntimeError,
                                f"^{expected_error}$",
                            ):
                                module.run_live_e2e(
                                    output_path,
                                    runner_image_id=runner_image_id,
                                )
                        else:
                            argv = [
                                str(SCRIPT_PATH),
                                "--inside",
                                "--output",
                                str(output_path),
                            ]
                            if runner_image_id is not None:
                                argv.extend(["--runner-image-id", runner_image_id])
                            stderr = io.StringIO()
                            stdout = io.StringIO()
                            with (
                                mock.patch.object(module.sys, "argv", argv),
                                mock.patch.object(module.sys, "stderr", stderr),
                                mock.patch.object(module.sys, "stdout", stdout),
                            ):
                                result = module.main()
                            self.assertEqual(result, 1)
                            self.assertEqual(stdout.getvalue(), "")
                            self.assertEqual(
                                json.loads(stderr.getvalue()),
                                {"error": expected_error, "status": "error"},
                            )

                    run_command.assert_not_called()
                    run_inside.assert_not_called()
                    self.assertFalse(output_path.exists())
                    self.assertFalse(output_helper_path.exists())
                    self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_pinned_postgres_image_drift_stops_before_docker(self) -> None:
        module = _load_module("connected_runtime_postgres_live_e2e_pg_drift", SCRIPT_PATH)
        runner_image_id = f"sha256:{'a' * 64}"
        with (
            mock.patch.dict(
                os.environ,
                {"FORMOWL_RUNNER_IMAGE_ID": runner_image_id},
                clear=True,
            ),
            mock.patch.object(module, "POSTGRES_IMAGE", "pgvector/pgvector:0.8.0-pg17"),
            mock.patch.object(module, "_run_command") as run_command,
            self.assertRaisesRegex(RuntimeError, "^postgres_image_contract_mismatch$"),
        ):
            module.run_live_e2e(
                Path("/tmp/not-created-live-report.json"),
                runner_image_id=runner_image_id,
            )
        run_command.assert_not_called()

    def test_missing_invalid_or_unbound_runner_image_id_stops_before_docker(self) -> None:
        module = _load_module("connected_runtime_postgres_live_e2e_image_reject", SCRIPT_PATH)
        valid_image_id = f"sha256:{'a' * 64}"
        other_image_id = f"sha256:{'b' * 64}"
        cases = (
            (
                "missing_argument",
                None,
                {"FORMOWL_RUNNER_IMAGE_ID": valid_image_id},
                "runner_image_id_required",
            ),
            (
                "mutable_tag",
                "formowl-dev:local",
                {"FORMOWL_RUNNER_IMAGE_ID": "formowl-dev:local"},
                "runner_image_id_required",
            ),
            (
                "missing_authority",
                valid_image_id,
                {},
                "runner_image_id_authority_missing",
            ),
            (
                "authority_mismatch",
                valid_image_id,
                {"FORMOWL_RUNNER_IMAGE_ID": other_image_id},
                "runner_image_id_authority_mismatch",
            ),
        )
        for name, runner_image_id, environment, expected_error in cases:
            with self.subTest(name=name):
                with (
                    mock.patch.dict(os.environ, environment, clear=True),
                    mock.patch.object(module, "_run_command") as run_command,
                    self.assertRaisesRegex(RuntimeError, f"^{expected_error}$"),
                ):
                    module.run_live_e2e(
                        Path("/tmp/not-created-live-report.json"),
                        runner_image_id=runner_image_id,
                    )
                run_command.assert_not_called()

    def test_inside_mode_requires_image_authority_before_journey_execution(self) -> None:
        module = _load_module("connected_runtime_postgres_live_e2e_inside_image", SCRIPT_PATH)
        stderr = io.StringIO()
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(
                module.sys,
                "argv",
                [str(SCRIPT_PATH), "--inside", "--output", "/tmp/not-created.json"],
            ),
            mock.patch.object(module.asyncio, "run") as run_inside,
            mock.patch.object(module.sys, "stderr", stderr),
        ):
            result = module.main()

        self.assertEqual(result, 1)
        run_inside.assert_not_called()
        self.assertEqual(
            json.loads(stderr.getvalue()),
            {"error": "runner_image_id_required", "status": "error"},
        )

    def test_validate_report_mode_leaves_input_and_sibling_bytes_unchanged(self) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_validate_read_only",
            SCRIPT_PATH,
        )
        with tempfile.TemporaryDirectory(prefix="formowl-live-validate-read-only-") as temporary:
            output_path = Path(temporary) / "live-report.json"
            helper_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
            output_bytes = (
                json.dumps(
                    _valid_report(module),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode()
            helper_bytes = b"operator-controlled-sibling\n"
            output_path.write_bytes(output_bytes)
            helper_path.write_bytes(helper_bytes)
            stdout = io.StringIO()
            stderr = io.StringIO()

            with (
                mock.patch.object(
                    module.sys,
                    "argv",
                    [
                        str(SCRIPT_PATH),
                        "--validate-report",
                        "--output",
                        str(output_path),
                    ],
                ),
                mock.patch.object(module.sys, "stdout", stdout),
                mock.patch.object(module.sys, "stderr", stderr),
            ):
                result = module.main()

            self.assertEqual(result, 0)
            self.assertEqual(output_path.read_bytes(), output_bytes)
            self.assertEqual(helper_path.read_bytes(), helper_bytes)
            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(json.loads(stdout.getvalue())["status"], "passed")

    def test_safe_report_deterministically_emits_exact_harness_layer(self) -> None:
        module = _load_module("connected_runtime_postgres_live_e2e", SCRIPT_PATH)
        harness = _load_module("oauth_mcp_harness_live_layer_contract", HARNESS_PATH)
        report = _valid_report(module)

        validation = module.validate_report(report)
        layer = report["live_postgresql_layer"]

        self.assertTrue(validation["passed"], validation["blockers"])
        self.assertEqual(
            set(layer),
            set(harness._EXTERNAL_LAYER_FIELDS["live_postgresql"]),
        )
        self.assertEqual(layer, module.build_live_postgresql_layer(report))
        self.assertEqual(layer["status"], "passed")
        self.assertTrue(layer["operator_attested"])
        self.assertEqual(layer["endpoint_scheme"], "postgresql")
        source_report_payload = {
            key: report[key]
            for key in (
                "artifact_id",
                "status",
                "protocol_version",
                "metrics",
                "safe_counts",
                "safe_hashes",
                "claim_boundary",
            )
        }
        self.assertEqual(
            layer["source_report_commitment_hash"],
            module._evidence_hash(
                "live_postgresql_source_report_commitment_v1",
                source_report_payload,
            ),
        )
        layer_without_artifact_hash = {
            key: value for key, value in layer.items() if key != "evidence_artifact_hash"
        }
        self.assertEqual(
            layer["evidence_artifact_hash"],
            module._evidence_hash(
                "live_postgresql_external_layer_v3",
                layer_without_artifact_hash,
            ),
        )
        self.assertTrue(module.validate_live_postgresql_external_layer(layer)["passed"])
        blockers: list[str] = []
        harness._validate_external_hash_fields("live_postgresql", layer, blockers)
        harness._validate_external_attestations("live_postgresql", layer["attestations"], blockers)
        harness._validate_external_layer_counts("live_postgresql", layer, blockers)
        self.assertEqual(blockers, [])

    def test_false_raw_exposure_metric_is_the_expected_passing_value(self) -> None:
        module = _load_module("connected_runtime_postgres_live_e2e_metric", SCRIPT_PATH)
        report = _valid_report(module)

        self.assertFalse(report["metrics"]["raw_secret_or_path_exposed"])
        self.assertEqual(report["status"], "passed")
        self.assertTrue(module.validate_report(report)["passed"])

    def test_layer_and_report_counts_cannot_be_coherently_downgraded(self) -> None:
        module = _load_module("connected_runtime_postgres_live_e2e_counts", SCRIPT_PATH)
        report = _valid_report(module)
        report["safe_counts"]["expiry_denial_count"] = 0
        report["live_postgresql_layer"] = module.build_live_postgresql_layer(report)

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "safe count is invalid: expiry_denial_count",
            validation["blockers"],
        )
        self.assertIn(
            "live PostgreSQL external layer count is invalid: expiry_denial_count",
            validation["blockers"],
        )

    def test_relink_claim_rejects_missing_or_zero_post_relink_denial_evidence(self) -> None:
        module = _load_module(
            "connected_runtime_postgres_live_e2e_post_relink_report",
            SCRIPT_PATH,
        )
        cases = {
            "missing": lambda report: report["safe_counts"].pop(
                "post_relink_old_token_denial_count"
            ),
            "zero": lambda report: report["safe_counts"].__setitem__(
                "post_relink_old_token_denial_count",
                0,
            ),
        }

        for name, tamper in cases.items():
            with self.subTest(name=name):
                report = _valid_report(module)
                self.assertTrue(report["claim_boundary"]["revoke_and_expiry_relink_verified"])
                tamper(report)
                report["live_postgresql_layer"] = module.build_live_postgresql_layer(report)

                validation = module.validate_report(report)

                self.assertFalse(validation["passed"])
                if name == "missing":
                    self.assertIn(
                        "safe counts is missing required fields",
                        validation["blockers"],
                    )
                else:
                    self.assertIn(
                        "safe count is invalid: post_relink_old_token_denial_count",
                        validation["blockers"],
                    )
                self.assertIn(
                    (
                        "live PostgreSQL external layer count is invalid: "
                        "post_relink_old_token_denial_count"
                    ),
                    validation["blockers"],
                )

    def test_stale_implementation_contract_cannot_be_relabelled_as_current_evidence(self) -> None:
        module = _load_module("connected_runtime_postgres_live_e2e_stale", SCRIPT_PATH)
        report = _valid_report(module)
        report["safe_hashes"]["implementation_contract_hash"] = "sha256:" + "f" * 64
        report["live_postgresql_layer"] = module.build_live_postgresql_layer(report)

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn("implementation contract hash is stale", validation["blockers"])
        self.assertEqual(report["live_postgresql_layer"]["status"], "failed")

    def test_command_contract_binds_pinned_postgres_image_and_is_recomputed(self) -> None:
        module = _load_module("connected_runtime_postgres_live_e2e_command_contract", SCRIPT_PATH)
        report = _valid_report(module)
        implementation_contract_hash = report["safe_hashes"]["implementation_contract_hash"]

        self.assertEqual(
            report["safe_hashes"]["command_contract_hash"],
            module._command_contract_hash(implementation_contract_hash),
        )
        report["safe_hashes"]["command_contract_hash"] = module._evidence_hash(
            "command_contract",
            {"postgres_image": "pgvector/pgvector:0.8.0-pg17"},
        )
        report["live_postgresql_layer"] = module.build_live_postgresql_layer(report)

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn("command contract hash is stale", validation["blockers"])

    def test_stale_source_report_cannot_reuse_prior_public_layer_commitment(self) -> None:
        module = _load_module("connected_runtime_postgres_live_e2e_stale_source", SCRIPT_PATH)
        report = _valid_report(module)
        original_commitment = report["live_postgresql_layer"]["source_report_commitment_hash"]
        report["safe_hashes"]["schema_state_hash"] = module._evidence_hash(
            "stale_source_schema_state",
            {"fixture": "changed-after-layer-build"},
        )

        validation = module.validate_report(report)

        self.assertEqual(
            report["live_postgresql_layer"]["source_report_commitment_hash"],
            original_commitment,
        )
        self.assertFalse(validation["passed"])
        self.assertIn(
            "live PostgreSQL source report commitment is stale",
            validation["blockers"],
        )

    def test_report_rejects_dsn_url_email_token_path_and_sql(self) -> None:
        module = _load_module("connected_runtime_postgres_live_e2e_safety", SCRIPT_PATH)
        forbidden_values = (
            "postgresql://user:secret@db/formowl",
            "https://private.example.test/oauth",
            "person@example.test",
            "Bearer eyJsecret.payload.signature",
            "/workspace/private/report.json",
            "SELECT secret FROM formowl_users",
        )
        for value in forbidden_values:
            with self.subTest(value=value):
                report = _valid_report(module)
                report["artifact_id"] = value
                validation = module.validate_report(report)
                self.assertFalse(validation["passed"])
                self.assertIn(
                    "public report contains a DSN, URL, email, token, path, or SQL",
                    validation["blockers"],
                )

    def test_serialized_report_contains_only_bounded_safe_evidence(self) -> None:
        module = _load_module("connected_runtime_postgres_live_e2e_serialized", SCRIPT_PATH)
        report = _valid_report(module)
        rendered = json.dumps(report, sort_keys=True).lower()

        for forbidden in (
            "postgresql://",
            "https://",
            "@example.test",
            "authorization: bearer",
            "/workspace/",
            "select ",
            "insert ",
            "update ",
            "delete ",
        ):
            self.assertNotIn(forbidden, rendered)


def _valid_report(module) -> dict:
    metrics = {field: True for field in module._METRIC_FIELDS}
    metrics["raw_secret_or_path_exposed"] = False
    counts = {
        "migration_ledger_rows": 5,
        "migration_applied_count": 5,
        "migration_restart_skipped_count": 5,
        "postgres_audit_rows_before_restart": 8,
        "postgres_audit_rows_after_all_journeys": 24,
        "persisted_upload_session_rows": 1,
        "persisted_file_audit_rows": 1,
        "listed_tool_count": 2,
        "user_rows_after_second_login": 2,
        "workspace_member_rows_after_second_login": 2,
        "external_identity_rows_after_second_login": 2,
        "accepted_invitation_rows_after_second_login": 2,
        "token_session_rows_after_all_journeys": 3,
        "revoked_token_denial_count": 1,
        "post_relink_old_token_denial_count": 1,
        "revoked_token_sessions_after_relink_count": 1,
        "relink_distinct_token_session_count": 1,
        "expiry_denial_count": 1,
        "relink_count": 1,
        "transaction_rollback_probe_count": 1,
        "postgres_mcp_allowed_audit_count": 2,
        "postgres_mcp_denied_audit_count": 2,
        "postgres_mcp_lineage_complete_count": 4,
        "cross_workspace_denial_count": 1,
        "identity_forgery_denial_count": 1,
        "signing_key_rotation_count": 1,
        "overlap_old_token_verification_count": 1,
        "overlap_jwks_public_key_count": 2,
        "new_key_token_verification_count": 1,
        "post_overlap_old_token_denial_count": 1,
        "post_overlap_jwks_public_key_count": 1,
        "post_overlap_new_token_verification_count": 1,
        "private_signing_key_exposure_count": 0,
    }
    hashes = {
        field: module._evidence_hash(field, {"fixture": field})
        for field in module._SAFE_HASH_FIELDS
    }
    hashes["implementation_contract_hash"] = module.issue20_implementation_contract_hash(
        module.ROOT
    )
    hashes["command_contract_hash"] = module._command_contract_hash(
        hashes["implementation_contract_hash"]
    )
    claims = {
        "live_postgresql": True,
        "production_oauth_and_mcp_runtime": True,
        "production_upload_and_file_audit_stores": True,
        "fake_google_oidc": True,
        "live_google_account": False,
        "live_chatgpt_connector": False,
        "live_postgresql_external_layer_contract": True,
        "revoke_and_expiry_relink_verified": True,
        "second_user_invitation_verified": True,
        "cross_workspace_verified": True,
        "signing_key_rotation_verified": True,
        "whole_issue_20_complete": False,
        "production_readiness": False,
    }
    report = {
        "artifact_id": module.ARTIFACT_ID,
        "status": "passed",
        "protocol_version": module.LATEST_PROTOCOL_VERSION,
        "metrics": metrics,
        "safe_counts": counts,
        "safe_hashes": hashes,
        "claim_boundary": claims,
    }
    report["live_postgresql_layer"] = module.build_live_postgresql_layer(report)
    return copy.deepcopy(report)


if __name__ == "__main__":
    unittest.main()
