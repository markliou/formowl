from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_DEPLOY_SCRIPT = _REPOSITORY_ROOT / "docs" / "recovery" / "2026-08-10" / "uat-mcp-r8-deploy.sh"
_PUBLIC_ONTOLOGY = (
    _REPOSITORY_ROOT / "docs" / "recovery" / "2026-08-10" / "public-semantic-ontology-v1.json"
)
_RUNTIME_TOOL_FILES = (
    "formowl_diagnostic_mcp_sharded.py",
    "diagnostic_structural_projection.py",
    "reviewed_structural_bindings.py",
    "diagnostic_current_export_table_snapshot.py",
    "diagnostic_xlsx_attachment_augmentation.py",
    "formowl_materialize_reviewed_bindings_private.py",
    "r8_source_only_ledgers.py",
)


def _embedded_public_ontology_validator() -> str:
    script = _DEPLOY_SCRIPT.read_text(encoding="utf-8")
    match = re.search(
        r"""validate_public_ontology\(\) \{
.*?python3 - "\$PUBLIC_ONTOLOGY" <<'PY'
(?P<validator>.*?)
PY
\}""",
        script,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError("deploy script public ontology validator is missing")
    return match.group("validator")


def _validate(ontology: object) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as directory:
        ontology_path = Path(directory) / "public-ontology.json"
        ontology_path.write_text(
            json.dumps(ontology, ensure_ascii=False),
            encoding="utf-8",
        )
        return subprocess.run(
            [sys.executable, "-c", _embedded_public_ontology_validator(), str(ontology_path)],
            check=False,
            capture_output=True,
            text=True,
        )


def _dry_run(
    *,
    tokenizer_model: Path | None = None,
    tokenizer_sha256: str | None = None,
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        private_root = root / "private"
        bridge_root = root / "bridge"
        runtime_tools_root = root / "runtime-tools"
        runtime_root = root / "runtime"
        corpus_root = root / "corpus"
        for path in (
            private_root,
            bridge_root,
            runtime_tools_root,
            runtime_root,
            corpus_root,
        ):
            path.mkdir()
        for name in _RUNTIME_TOOL_FILES:
            (runtime_tools_root / name).write_text("# test fixture\n", encoding="utf-8")
        auth_cache = root / "auth-cache.json"
        auth_cache.write_text("{}\n", encoding="utf-8")
        private_manifest = root / "manifest.private.json"
        private_manifest.write_text("{}\n", encoding="utf-8")
        diagnostic_command = root / "diagnostic-command.json"
        diagnostic_command.write_text(
            json.dumps(["python3", "/opt/formowl/scripts/diagnostic.py"]),
            encoding="utf-8",
        )
        command = [
            "bash",
            str(_DEPLOY_SCRIPT),
            "dry-run",
            "--image",
            "formowl-test:latest",
            "--private-root",
            str(private_root),
            "--bridge-root",
            str(bridge_root),
            "--worktree-root",
            str(_REPOSITORY_ROOT),
            "--runtime-tools-root",
            str(runtime_tools_root),
            "--auth-cache",
            str(auth_cache),
            "--runtime-root",
            str(runtime_root),
            "--diagnostic-command-json",
            str(diagnostic_command),
            "--corpus-root-host",
            str(corpus_root),
            "--private-manifest-host",
            str(private_manifest),
            "--public-ontology",
            str(_PUBLIC_ONTOLOGY),
        ]
        if tokenizer_model is not None:
            command.extend(["--tokenizer-model", str(tokenizer_model)])
        if tokenizer_sha256 is not None:
            command.extend(["--tokenizer-sha256", tokenizer_sha256])
        return subprocess.run(command, check=False, capture_output=True, text=True)


class UatMcpR8DeployPublicOntologyValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ontology = json.loads(_PUBLIC_ONTOLOGY.read_text(encoding="utf-8"))

    def test_current_public_ontology_passes_embedded_deploy_validator(self) -> None:
        result = _validate(self.ontology)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_deploy_validator_requires_complete_domains_and_rejects_open_enumerations(
        self,
    ) -> None:
        missing_domain = copy.deepcopy(self.ontology)
        del missing_domain["value_domains"]["p/n"]
        invalid_domain = copy.deepcopy(self.ontology)
        invalid_domain["value_domains"]["coo"] = "unbounded"
        enumerated_open_value = copy.deepcopy(self.ontology)
        enumerated_open_value["value_aliases"]["coo"] = {
            "synthetic value": ["synthetic value"],
        }

        self.assertNotEqual(_validate(missing_domain).returncode, 0)
        self.assertNotEqual(_validate(invalid_domain).returncode, 0)
        self.assertNotEqual(_validate(enumerated_open_value).returncode, 0)

    def test_deploy_requires_and_validates_explicit_tokenizer_contract(self) -> None:
        no_inputs = _dry_run()

        self.assertNotEqual(no_inputs.returncode, 0)
        self.assertIn("--tokenizer-model is required", no_inputs.stderr)

        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "sentencepiece.model"
            model.write_bytes(b"frozen tokenizer fixture")
            model_only = _dry_run(tokenizer_model=model)
            sha_only = _dry_run(
                tokenizer_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),
            )
            digest = hashlib.sha256(model.read_bytes()).hexdigest()
            valid = _dry_run(tokenizer_model=model, tokenizer_sha256=digest)
            mismatched = _dry_run(
                tokenizer_model=model,
                tokenizer_sha256="0" * 64,
            )

        self.assertNotEqual(model_only.returncode, 0)
        self.assertIn("--tokenizer-sha256", model_only.stderr)
        self.assertNotEqual(sha_only.returncode, 0)
        self.assertIn("--tokenizer-model is required", sha_only.stderr)
        script = _DEPLOY_SCRIPT.read_text(encoding="utf-8")

        self.assertIn('TOKENIZER_MODEL=""', script)
        self.assertIn('TOKENIZER_SHA256=""', script)
        self.assertNotIn("/home/", script)

        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertIn(f"tokenizer_sha256=sha256:{digest}", valid.stdout)
        self.assertNotEqual(mismatched.returncode, 0)
        self.assertIn("tokenizer model SHA256 does not match", mismatched.stderr)


if __name__ == "__main__":
    unittest.main()
