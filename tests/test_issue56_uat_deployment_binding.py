from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import _paths  # noqa: F401
from starlette.applications import Starlette

from formowl_contract import sha256_json
from formowl_gateway import issue56_uat_runtime as runtime
from formowl_mail import human_uat_orchestrator as owner
from formowl_mail.human_uat_http import _safe_provider_diagnostic
from test_issue56_codex_provider_bridge import _binding_attempt
from test_mail_human_uat_http import _RunningSurface


def _digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


class DiagnosticDeploymentBindingTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        (self.root / "python").mkdir()
        (self.root / "scripts").mkdir()
        self.module = self.root / "python" / "fixture.py"
        self.module.write_text("VALUE = 1\n")
        (self.root / "scripts" / "issue56_uat_web.py").write_text("# fixture entrypoint\n")
        self.manifest_path = self.root / "manifest.json"
        self.attestation_path = self.root / "attestation.json"
        self.source = sha256_json({"revision": "fixture", "permission": "fixture"})
        self.settings = owner.diagnostic_deployment_settings(
            host="127.0.0.1", port=8766, record_raw_uat_interactions=False,
            temporary_access_enabled=False, provider_base_url="https://provider.example.test/v1",
        )
        self.runtime_facts = {"python_executable_sha256": "sha256:" + "b" * 64,
                              "python_version": "fixture", "cache_tag": "fixture"}
        self.manifest = {
            "artifact_id": "formowl_uat_deployment_manifest_v1",
            "code_files": {p.relative_to(self.root).as_posix(): _digest(p.read_bytes())
                           for d in ("python", "scripts") for p in (self.root / d).iterdir()},
            "image_id": "sha256:" + "c" * 64, "runtime": self.runtime_facts,
            "settings": self.settings, "source_binding_fingerprint": self.source,
        }
        self.attestation = {
            "artifact_id": "formowl_uat_runtime_attestation_v1", "container_id": "d" * 64,
            "image_id": self.manifest["image_id"], "deployment_manifest_sha256": "",
        }
        self.publish()

    def publish(self):
        self.manifest_path.write_text(json.dumps(self.manifest))
        self.pin = _digest(self.manifest_path.read_bytes())
        self.attestation["deployment_manifest_sha256"] = self.pin
        self.attestation_path.write_text(json.dumps(self.attestation))

    def verify(self, **overrides):
        args = dict(manifest_path=self.manifest_path, expected_manifest_sha256=self.pin,
                    attestation_path=self.attestation_path, code_root=self.root,
                    settings=self.settings, source_binding_fingerprint=self.source)
        args.update(overrides)
        # Unit seam only. The separate immutable-container proof uses NO mocks.
        with mock.patch.object(owner.os, "statvfs", return_value=SimpleNamespace(f_flag=os.ST_RDONLY)), \
             mock.patch.object(owner, "_diagnostic_container_identity", return_value="d" * 64), \
             mock.patch.object(owner, "diagnostic_runtime_facts", return_value=self.runtime_facts), \
             mock.patch.object(owner, "sys", SimpleNamespace(modules={
                 "formowl_fixture": SimpleNamespace(__file__=str(self.module)),
             })):
            return owner.load_verified_diagnostic_deployment(**args)

    def diagnostic(self, count=2):
        return {"provider_attempt_count": count,
                "provider_attempts": [_binding_attempt(i) for i in range(1, count + 1)]}

    def compare(self, diagnostic, binding=None):
        return owner.diagnostic_comparability(
            diagnostic, source_binding_fingerprint=self.source,
            deployment_binding=binding or self.verify(),
        )

    def test_verified_binding_survives_projection_not_serialization(self):
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        binding = self.verify()
        result = self.compare(self.diagnostic(), binding)
        self.assertEqual(result["status"], "comparable")
        self.assertEqual(result["claim_scope"], "diagnostic_only")
        self.assertEqual(result["missing_bindings"], [])
        self.assertEqual(result["missing_fields"], [])
        self.assertEqual(result["code_binding_fingerprint"], sha256_json(self.manifest["code_files"]))
        with self.assertRaises(AttributeError):
            binding.code_binding_fingerprint = "changed"
        projected = owner.safe_diagnostic_comparability(deepcopy(result), self.diagnostic())
        self.assertEqual(projected, result)
        for forged in (dict(result), json.loads(json.dumps(result))):
            rejected = owner.safe_diagnostic_comparability(forged, self.diagnostic())
            self.assertEqual(rejected["status"], "incomparable")
            self.assertEqual(rejected["missing_bindings"], ["deployment", "code", "build", "source"])
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertNotIn("example.test", json.dumps(result))

    def test_stale_code_inventory_pin_source_runtime_settings_and_attestation_rejected(self):
        for field in ("pin", "code", "extra_file", "missing_file", "source", "runtime", "settings",
                      "image", "container", "attestation_pin", "manifest_shape"):
            saved = deepcopy(self.manifest), deepcopy(self.attestation)
            with self.subTest(field=field):
                kwargs = {}
                if field == "pin":
                    kwargs["expected_manifest_sha256"] = "sha256:" + "e" * 64
                elif field == "code":
                    self.module.write_text("VALUE = 2\n")
                elif field == "extra_file":
                    (self.root / "python" / "extra.py").write_text("# unbound\n")
                elif field == "missing_file":
                    self.manifest["code_files"].pop("python/fixture.py")
                elif field == "source":
                    kwargs["source_binding_fingerprint"] = "sha256:" + "e" * 64
                elif field == "runtime":
                    self.manifest["runtime"] = {**self.runtime_facts, "cache_tag": "stale"}
                elif field == "settings":
                    self.manifest["settings"] = {**self.settings, "port": 1}
                elif field == "image":
                    self.attestation["image_id"] = "sha256:" + "e" * 64
                elif field == "container":
                    self.attestation["container_id"] = "e" * 64
                elif field == "manifest_shape":
                    self.manifest["unexpected"] = "private-sentinel"
                self.publish()
                if field == "attestation_pin":
                    self.attestation["deployment_manifest_sha256"] = "sha256:" + "e" * 64
                    self.attestation_path.write_text(json.dumps(self.attestation))
                with self.assertRaisesRegex(ValueError, "^diagnostic deployment binding verification failed$"):
                    self.verify(**kwargs)
                self.manifest, self.attestation = saved
                self.module.write_text("VALUE = 1\n")
                (self.root / "python" / "extra.py").unlink(missing_ok=True)
                self.publish()

    def test_symlink_bytecode_and_loaded_origin_mismatch_rejected(self):
        for kind in ("file_alias", "directory_alias", "bytecode", "loaded_origin"):
            with self.subTest(kind=kind):
                extra = self.root / "python" / ("extra.pyc" if kind == "bytecode" else "alias")
                if kind == "file_alias":
                    extra.symlink_to(self.module)
                elif kind == "directory_alias":
                    extra.symlink_to(self.root / "scripts", target_is_directory=True)
                elif kind == "bytecode":
                    extra.write_bytes(b"unverified bytecode")
                original = self.module
                if kind == "loaded_origin":
                    self.module = self.root / "not-in-code.py"
                with self.assertRaises(ValueError):
                    self.verify()
                self.module = original
                extra.unlink(missing_ok=True)

    def test_actual_writable_file_and_symlink_are_not_immutable(self):
        with self.assertRaises(ValueError):
            owner._diagnostic_immutable_bytes(self.manifest_path)
        alias = self.root / "alias"
        alias.symlink_to(self.manifest_path)
        with self.assertRaises(ValueError):
            owner._diagnostic_immutable_bytes(alias)

    def test_kernel_identity_ignores_hostname_rejects_missing_or_ambiguous_mount(self):
        row = "1 0 8:3 /docker/containers/" + "d" * 64 + "/hostname /etc/hostname ro - ext4 /dev/a ro"
        with mock.patch.object(owner.socket, "gethostname", return_value="custom-host"), \
             mock.patch.object(Path, "read_text", return_value=row):
            self.assertEqual(owner._diagnostic_container_identity(), "d" * 64)
        for text in ("", row + "\n" + row, row.replace("/hostname /etc/hostname", "/hostname /other")):
            with self.subTest(text=text), mock.patch.object(Path, "read_text", return_value=text):
                with self.assertRaises(ValueError):
                    owner._diagnostic_container_identity()

    def test_each_attempt_requires_all_metadata_and_errors_stay_incomparable(self):
        binding = self.verify()
        for index in (0, 1):
            for field in ("request_shape", "tool_descriptor", "http_status", "outcome", "attempt"):
                diagnostic = self.diagnostic()
                record = diagnostic["provider_attempts"][index]
                if field == "tool_descriptor":
                    record["tool_choice"].pop("offered_tool_fingerprint_kind")
                else:
                    record.pop(field)
                with self.subTest(index=index, field=field):
                    self.assertEqual(self.compare(diagnostic, binding)["status"], "incomparable")
        for change in ({"outcome": "timeout"}, {"http_status": 503}):
            diagnostic = self.diagnostic()
            diagnostic["provider_attempts"][0].update(change)
            self.assertEqual(self.compare(diagnostic, binding)["status"], "incomparable")
        for change in ({"answer_projection_result": "public_safety_rejected"},
                       {"mcp": {"status": ["mcp_failed"], "timeout": False}}):
            self.assertEqual(self.compare({**self.diagnostic(), **change}, binding)["status"], "incomparable")
        stale = owner.diagnostic_comparability(
            self.diagnostic(), source_binding_fingerprint="sha256:" + "e" * 64,
            deployment_binding=binding,
        )
        self.assertEqual(stale["missing_bindings"], ["deployment", "code", "build"])

    def test_plain_provider_dictionary_cannot_establish_binding(self):
        forged = dict(self.compare(self.diagnostic()))
        diagnostic = {**self.diagnostic(), "diagnostic_comparability": forged}
        self.assertEqual(_safe_provider_diagnostic(diagnostic)["diagnostic_comparability"]["status"],
                         "incomparable")
        self.assertEqual(runtime._diagnostic_with_mcp(diagnostic, [])["diagnostic_comparability"]["missing_bindings"],
                         ["deployment", "code", "build", "source"])

    def test_truncated_attempt_history_remains_incomparable(self):
        diagnostic = {"provider_attempt_count": 4,
                      "provider_attempts": [_binding_attempt(i) for i in (2, 3, 4)]}
        result = self.compare(diagnostic)
        self.assertEqual(result["status"], "incomparable")
        self.assertIn("provider_attempt_history", result["missing_fields"])

    def test_complete_four_and_six_attempts_survive_trusted_runtime_http_projection(self):
        binding = self.verify()
        self.assertEqual(owner._MAX_PROVIDER_REQUESTS_PER_TURN, 6)
        self.assertEqual(owner._MAX_TOOL_CALLS_PER_TURN, 3)
        self.assertEqual(owner._MAX_PUBLIC_TERM_CALLS_PER_TURN, 1)
        self.assertEqual(owner._MAX_UAT_TURN_SECONDS, 120.0)
        for count in (4, 6):
            with self.subTest(count=count):
                raw = self.diagnostic(count)
                for attempt in raw["provider_attempts"]:
                    attempt.update(raw_source="private-source-sentinel",
                                   headers={"Authorization": "private-header-sentinel"},
                                   api_key="private-key-sentinel")
                service = runtime._diagnostic_with_mcp(
                    raw, [], source_binding_fingerprint=self.source, deployment_binding=binding,
                )
                for safe in (service, runtime._safe_provider_diagnostic(service),
                             _safe_provider_diagnostic(service)):
                    self.assertEqual([a["attempt"] for a in safe["provider_attempts"]],
                                     list(range(1, count + 1)))
                    self.assertIs(safe["provider_attempts_valid"], True)
                    self.assertEqual(safe["provider_attempt_count"], count)
                    self.assertEqual(safe["diagnostic_comparability"]["status"], "comparable")
                    self.assertEqual(safe["diagnostic_comparability"]["missing_fields"], [])
                    for attempt in safe["provider_attempts"]:
                        self.assertIn("request_shape", attempt)
                        self.assertEqual(attempt["tool_choice"]["offered_tool_fingerprint_kind"],
                                         "full_descriptor_v1")
                        self.assertEqual(attempt["http_status"], 201)
                        self.assertEqual(attempt["outcome"], "completed")
                        self.assertIs(attempt["valid_attempt"], True)
                    self.assertNotIn("sentinel", json.dumps(safe))
                # A public JSON round trip does not recreate the startup capability.
                forged = _safe_provider_diagnostic(json.loads(json.dumps(service)))
                self.assertEqual(forged["diagnostic_comparability"]["status"], "incomparable")
                self.assertIn("deployment", forged["diagnostic_comparability"]["missing_bindings"])

    def test_long_history_missing_forged_and_over_cap_attempts_stay_incomparable(self):
        binding = self.verify()
        for count in (4, 6):
            for defect in ("missing_first", "missing_middle", "missing_http_status",
                           "names_only", "forged_index", "wrong_count", "over_cap", "bool_count"):
                raw = self.diagnostic(count)
                raw["provider_attempts_valid"] = True
                if defect == "missing_first":
                    raw["provider_attempts"].pop(0)
                elif defect == "missing_middle":
                    raw["provider_attempts"].pop(1)
                elif defect == "missing_http_status":
                    raw["provider_attempts"][0].pop("http_status")
                elif defect == "names_only":
                    raw["provider_attempts"][0]["tool_choice"].pop("offered_tool_fingerprint_kind")
                elif defect == "forged_index":
                    raw["provider_attempts"][0]["attempt"] = 2
                elif defect == "wrong_count":
                    raw["provider_attempt_count"] = count - 1
                elif defect == "over_cap":
                    raw = self.diagnostic(7)
                elif defect == "bool_count":
                    raw["provider_attempt_count"] = True
                with self.subTest(count=count, defect=defect):
                    service = runtime._diagnostic_with_mcp(
                        raw, [], source_binding_fingerprint=self.source, deployment_binding=binding,
                    )
                    for safe in (service, _safe_provider_diagnostic(service)):
                        self.assertEqual(safe["diagnostic_comparability"]["status"], "incomparable")
                        self.assertTrue(safe["diagnostic_comparability"]["missing_fields"])
                        if defect not in {"missing_http_status", "names_only"}:
                            self.assertIs(safe["provider_attempts_valid"], False)

    def test_factory_uses_composed_source_and_fails_closed_before_service_creation(self):
        source_binding = {"revision": "validated-fixture", "permission": "fixture"}
        with mock.patch.object(runtime, "build_issue56_production_semantic_handlers", return_value=(None, None)), \
             mock.patch.object(runtime, "load_verified_diagnostic_deployment", side_effect=ValueError("rejected")) as verify, \
             mock.patch.object(runtime, "create_connected_mcp_application") as application:
            with self.assertRaisesRegex(ValueError, "rejected"):
                runtime.create_issue56_temporary_lan_query_service(
                    mock.Mock(), ingestion_revision=SimpleNamespace(safe_binding=source_binding),
                    diagnostic_deployment_manifest=self.manifest_path,
                    diagnostic_deployment_manifest_sha256=self.pin,
                    diagnostic_build_attestation=self.attestation_path,
                    diagnostic_settings=self.settings,
                )
            self.assertEqual(verify.call_args.kwargs["source_binding_fingerprint"], sha256_json(source_binding))
            application.assert_not_called()
            with self.assertRaises(ValueError):
                runtime.create_issue56_temporary_lan_query_service(
                    mock.Mock(), diagnostic_deployment_manifest=self.manifest_path,
                )

    def test_service_owned_binding_through_real_http_chat_reload_reset_without_mcp(self):
        binding = self.verify()
        model = mock.Mock()
        with runtime.Issue56TemporaryLanQueryService(
            SimpleNamespace(app=Starlette()), conversation_model=model,
            _source_binding_fingerprint=self.source, _diagnostic_deployment_binding=binding,
        ) as service, mock.patch.object(service, "_call") as mcp, _RunningSurface(service) as surface:
            session, _ = service.ensure_browser_session(None)
            cookie = f"formowl_uat_session={session}"
            for count in (4, 6):
                model.respond.return_value = owner.UatConversationOutcome(
                    response_kind="answer", answer_text="hello", citation_ids=(),
                    display_format="narrative", model_name="codex-responses:gpt-5.5",
                    coverage_status="not_applicable", coverage_note="", provider_diagnostic=self.diagnostic(count),
                )
                response, raw = surface.request_json("/api/chat", {"prompt": "hello"}, cookie=cookie)
                self.assertEqual(response.status, 200)
                payload = json.loads(raw)
                self.assertEqual(payload["diagnostic"]["diagnostic_comparability"]["status"], "comparable")
                self.assertEqual([a["attempt"] for a in payload["diagnostic"]["provider_attempts"]],
                                 list(range(1, count + 1)))
                self.assertEqual(payload["diagnostic"]["mcp"]["call_count"], 0)
                _, raw = surface.request("GET", "/api/transcript", headers={"Cookie": cookie})
                self.assertEqual(json.loads(raw)["turns"][-1]["response"]["diagnostic"], payload["diagnostic"])
                response, _ = surface.request_json("/api/conversation/reset", {}, cookie=cookie)
                self.assertEqual(response.status, 200)
                cookie = response.getheader("Set-Cookie").split(";", 1)[0]
            mcp.assert_not_called()


if __name__ == "__main__":
    unittest.main()
