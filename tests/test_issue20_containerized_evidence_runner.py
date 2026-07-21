from __future__ import annotations

import ast
from contextlib import ExitStack
import errno
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/issue20_containerized_evidence_runner.sh"
BOUNDARY_HELPER = ROOT / "scripts/issue20_runner_boundary.py"
BOUNDARY_SPEC = importlib.util.spec_from_file_location("issue20_runner_boundary", BOUNDARY_HELPER)
if BOUNDARY_SPEC is None or BOUNDARY_SPEC.loader is None:
    raise RuntimeError("issue20 runner boundary helper could not be loaded")
BOUNDARY_MODULE = importlib.util.module_from_spec(BOUNDARY_SPEC)
BOUNDARY_SPEC.loader.exec_module(BOUNDARY_MODULE)


def _load_issue20_contract_module() -> object:
    contract_spec = importlib.util.spec_from_file_location(
        "issue20_campaign_contract_fixture",
        ROOT / "python" / "formowl_evidence" / "issue20.py",
    )
    if contract_spec is None or contract_spec.loader is None:
        raise RuntimeError("issue20 implementation contract could not be loaded")
    contract_module = importlib.util.module_from_spec(contract_spec)
    previous_dont_write_bytecode = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        contract_spec.loader.exec_module(contract_module)
    finally:
        sys.dont_write_bytecode = previous_dont_write_bytecode
    return contract_module


def _write_issue20_contract_fixture(root: Path) -> None:
    contract_module = _load_issue20_contract_module()
    for pattern in contract_module.ISSUE20_IMPLEMENTATION_CONTRACT_GLOBS:
        concrete_parts: list[str] = []
        for component in pattern.split("/"):
            if component == "**":
                concrete_parts.append("fixture")
                continue
            if re.search(r"[\[\]?]", component):
                raise AssertionError(component)
            concrete_parts.append(component.replace("*", "fixture"))
        fixture_path = root.joinpath(*concrete_parts)
        fixture_path.parent.mkdir(parents=True, exist_ok=True)
        fixture_path.write_text("fixture\n", encoding="utf-8")

    issue20_contract = root / "python" / "formowl_evidence" / "issue20.py"
    issue20_contract.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        ROOT / "python" / "formowl_evidence" / "issue20.py",
        issue20_contract,
    )
    shutil.copy2(RUNNER, root / "scripts" / RUNNER.name)
    shutil.copy2(
        BOUNDARY_HELPER,
        root / "scripts" / BOUNDARY_HELPER.name,
    )


def _tree_state(root: Path, *, excluded: set[Path] | None = None) -> dict[str, object]:
    excluded_paths = excluded or set()
    state: dict[str, object] = {}
    for path in sorted(root.rglob("*")):
        if path in excluded_paths:
            continue
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        if path.is_dir():
            state[relative] = ("directory", stat.S_IMODE(metadata.st_mode))
        else:
            state[relative] = (
                "file",
                stat.S_IMODE(metadata.st_mode),
                path.read_bytes(),
            )
    return state


class Issue20ContainerizedEvidenceRunnerContractTest(unittest.TestCase):
    def test_dev_image_installs_runner_dependencies_and_docker_plugins(self) -> None:
        dockerfile = (ROOT / "containers/dev/Dockerfile").read_text(encoding="utf-8")

        self.assertIn(
            'python -m pip install --no-cache-dir --no-build-isolation ".[dev]"', dockerfile
        )
        for package in ("docker-buildx", "docker-cli", "docker-compose"):
            self.assertIn(package, dockerfile)

    def test_runner_has_only_fixed_evidence_modes_and_shared_path_contract(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")

        for mode in (
            "preflight",
            "operator",
            "operator-layer",
            "live-postgresql",
            "lifecycle-a",
            "lifecycle-b",
            "lifecycle-aggregate",
            "local-harness",
        ):
            self.assertIn(mode, source)
        self.assertIn(
            '--volume "$GIT_METADATA_ROOT:$GIT_METADATA_ROOT:ro"',
            source,
        )
        self.assertIn('--volume "$SOURCE_SNAPSHOT_ROOT:$ROOT:ro"', source)
        self.assertEqual(source.count('--volume "$ROOT:$ROOT:ro"'), 1)
        self.assertIn('--volume "$SCRATCH_ROOT:$SCRATCH_ROOT:ro"', source)
        self.assertIn('--volume "$REPORT_DIR:$REPORT_DIR:rw"', source)
        self.assertIn('--volume "$HANDOFF_DIR:$HANDOFF_DIR:$CANDIDATE_MOUNT_MODE"', source)
        self.assertIn('--volume "$TRUST_INPUT_DIR:$TRUST_INPUT_DIR:ro"', source)
        self.assertIn("--read-only", source)
        self.assertIn("--cap-drop ALL", source)
        self.assertIn("--security-opt no-new-privileges:true", source)
        self.assertIn("--volume /var/run/docker.sock:/var/run/docker.sock", source)
        self.assertIn('--env "TMPDIR=$INNER_TMP"', source)
        self.assertIn('--env "PYTHONPATH=$ROOT/python"', source)
        self.assertEqual(source.count('    --env "'), 15)
        self.assertIn('--env "DOCKER_HOST=unix:///var/run/docker.sock"', source)
        self.assertIn('--env "DOCKER_CONFIG=$INNER_DOCKER_CONFIG"', source)
        self.assertIn('--env "HOME=$INNER_HOME"', source)
        self.assertIn('--env "COMPOSE_DISABLE_ENV_FILE=1"', source)
        self.assertIn('--env "FORMOWL_RUNNER_CAMPAIGN_PIN=$CAMPAIGN_PIN"', source)
        self.assertIn(
            '--env "FORMOWL_RUNNER_DOCKER_AUTHORITY=trusted_operator_docker_daemon"',
            source,
        )
        self.assertIn('--env "FORMOWL_RUNNER_IMAGE_ID=$IMAGE_ID"', source)
        self.assertIn('--env "FORMOWL_RUNNER_SANDBOXED_UNTRUSTED_SOURCE=0"', source)
        self.assertEqual(source.count("/usr/bin/env -i"), 5)
        self.assertIn("unset DOCKER_CONTEXT", source)
        for forbidden in (
            "DOCKER_CLI_PLUGIN_EXTRA_DIRS",
            "BUILDX_CONFIG",
            "BUILDKIT_HOST",
            "COMPOSE_FILE",
            "COMPOSE_PROFILES",
            "COMPOSE_PROJECT_NAME",
            "COMPOSE_ENV_FILES",
        ):
            self.assertIn(forbidden, source)
        self.assertIn('SCRIPT_PATH=$(/usr/bin/readlink -f "$0")', source)
        self.assertIn("ROOT=${SCRIPT_DIR%/scripts}", source)
        self.assertNotIn("ROOT=$(pwd -P)", source)
        self.assertNotIn("--env-file", source)
        self.assertNotIn("eval ", source)

    def test_runner_uses_private_tmpfs_without_repurposing_governed_scratch(
        self,
    ) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        outer_run_start = source.index('    "$DOCKER_BIN" run --rm \\')
        outer_run_end = source.index('    "$IMAGE_ID" \\', outer_run_start)
        outer_run = source[outer_run_start:outer_run_end]
        tmpfs_contract = "--tmpfs /tmp:rw,exec,nosuid,nodev,size=256m,mode=1777"

        self.assertEqual(outer_run.count(tmpfs_contract), 1)
        self.assertIn(
            '--volume "$GIT_METADATA_ROOT:$GIT_METADATA_ROOT:ro"',
            outer_run,
        )
        self.assertIn('--volume "$SOURCE_SNAPSHOT_ROOT:$ROOT:ro"', outer_run)
        self.assertNotIn('--volume "$ROOT:$ROOT:ro"', outer_run)
        scratch_mount = '--volume "$SCRATCH_ROOT:$SCRATCH_ROOT:ro"'
        self.assertIn(scratch_mount, outer_run)
        self.assertIn('--volume "$REPORT_DIR:$REPORT_DIR:rw"', outer_run)
        private_log_base_mount = '--volume "$PRIVATE_LOG_BASE:$PRIVATE_LOG_BASE:rw"'
        inner_log_dir_mount = '--volume "$INNER_LOG_DIR:$INNER_LOG_DIR:rw"'
        self.assertEqual(outer_run.count(private_log_base_mount), 1)
        self.assertEqual(outer_run.count(inner_log_dir_mount), 1)
        self.assertLess(
            outer_run.index(private_log_base_mount),
            outer_run.index(inner_log_dir_mount),
        )
        self.assertIn(
            '--volume "$HANDOFF_DIR:$HANDOFF_DIR:$CANDIDATE_MOUNT_MODE"',
            outer_run,
        )
        self.assertIn('--volume "$TRUST_INPUT_DIR:$TRUST_INPUT_DIR:ro"', outer_run)
        self.assertIn('--env "TMPDIR=$INNER_TMP"', outer_run)
        self.assertLess(
            outer_run.index(tmpfs_contract),
            outer_run.index(scratch_mount),
        )
        for forbidden in (
            '--volume "$SCRATCH_ROOT:/tmp"',
            '--volume "$TRUST_INPUT_DIR:/tmp"',
            '--volume "$TMP_BASE:/tmp"',
            '--volume "$INVOCATION_TMP_ROOT:/tmp"',
            '--volume "$INNER_TMP:/tmp"',
            '--volume "$SOURCE_SNAPSHOT_ROOT:/tmp"',
            '--volume "$GIT_METADATA_ROOT:/tmp"',
        ):
            self.assertNotIn(forbidden, source)
        for relative_path in (
            "tests/test_connected_container_entrypoint.py",
            "tests/test_connected_runtime_container.py",
            "tests/test_oauth_mcp_harness_script.py",
        ):
            test_source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn('dir="/tmp"', test_source)
            self.assertNotIn('Path("/tmp")', test_source)

    def test_runner_builds_and_executes_one_private_read_only_source_snapshot(
        self,
    ) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        snapshot_assignment = 'SOURCE_SNAPSHOT_ROOT="$CAMPAIGN_DIR/source-snapshot"'
        snapshot_export = '--output "type=local,dest=$SOURCE_SNAPSHOT_ROOT"'
        image_build = '--file "$SOURCE_SNAPSHOT_ROOT/containers/dev/Dockerfile"'
        git_metadata_mount = '--volume "$GIT_METADATA_ROOT:$GIT_METADATA_ROOT:ro"'
        snapshot_mount = '--volume "$SOURCE_SNAPSHOT_ROOT:$ROOT:ro"'
        outer_run_start = source.index('    "$DOCKER_BIN" run --rm \\')
        outer_run_end = source.index('    "$IMAGE_ID" \\', outer_run_start)
        outer_run = source[outer_run_start:outer_run_end]

        self.assertEqual(source.count(snapshot_assignment), 1)
        self.assertEqual(source.count(snapshot_export), 1)
        self.assertEqual(source.count(image_build), 1)
        self.assertEqual(source.count(git_metadata_mount), 1)
        self.assertEqual(source.count(snapshot_mount), 2)
        self.assertIn('CAMPAIGN_DIR="$SCRATCH_ROOT/campaign"', source)
        self.assertIn('CAMPAIGN_PIN="$TRUST_INPUT_DIR/campaign-source-pin.json"', source)
        self.assertIn("create-campaign-pin", source)
        self.assertIn("verify-campaign", source)
        self.assertIn("'FROM scratch'", source)
        self.assertIn("'ARG SNAPSHOT_UID'", source)
        self.assertIn("'ARG SNAPSHOT_GID'", source)
        self.assertIn(
            "'COPY --chown=${SNAPSHOT_UID}:${SNAPSHOT_GID} . /'",
            source,
        )
        self.assertIn('--build-arg "SNAPSHOT_UID=$RUNNER_UID"', source)
        self.assertIn('--build-arg "SNAPSHOT_GID=$(/usr/bin/id -g)"', source)
        self.assertIn('"$SOURCE_SNAPSHOT_ROOT" > "$BUILD_LOG" 2>&1', source)
        self.assertIn(
            'GIT_SNAPSHOT_ROOT="$CAMPAIGN_DIR/git-snapshot"',
            source,
        )
        self.assertIn('GIT_METADATA_ROOT="$GIT_SNAPSHOT_ROOT/.git"', source)
        self.assertIn(
            '/usr/bin/git -c "safe.directory=$ROOT" clone \\',
            source,
        )
        for clone_option in ("--local", "--no-checkout", "--no-hardlinks"):
            self.assertIn(clone_option, source)
        self.assertIn("|| ! /usr/bin/git \\", source)
        self.assertIn('--git-dir="$GIT_METADATA_ROOT" \\', source)
        self.assertIn(
            "cat-file -e '8848c69f532dbb8d412e14be1ed1c6b12a4cfc90^{commit}'",
            source,
        )
        self.assertIn(
            "printf 'gitdir: %s\\n' \"$GIT_METADATA_ROOT\" " '> "$SOURCE_SNAPSHOT_ROOT/.git"',
            source,
        )
        self.assertIn('/usr/bin/chmod 400 "$SOURCE_SNAPSHOT_ROOT/.git"', source)
        self.assertIn('"git_metadata_sha256"', BOUNDARY_HELPER.read_text(encoding="utf-8"))
        self.assertNotIn('--file "$ROOT/containers/dev/Dockerfile"', source)
        self.assertIn(git_metadata_mount, outer_run)
        self.assertIn(snapshot_mount, outer_run)
        self.assertNotIn('--volume "$ROOT:$ROOT:ro"', outer_run)
        self.assertNotIn('--volume "$ROOT/.git:', source)
        self.assertEqual(source.count('--volume "$ROOT:$ROOT:ro"'), 1)
        self.assertLess(source.index(snapshot_export), source.index(image_build))
        self.assertLess(source.index(snapshot_export), source.index(git_metadata_mount))
        self.assertLess(source.index(image_build), source.index(snapshot_mount))
        self.assertLess(source.index("create-campaign-pin"), source.index("verify-campaign"))
        for excluded_path in (
            "$SOURCE_SNAPSHOT_ROOT/.git",
            "$SOURCE_SNAPSHOT_ROOT/.formowl",
            "$SOURCE_SNAPSHOT_ROOT/.test-tmp",
            "$SOURCE_SNAPSHOT_ROOT/tests/pst-exm",
        ):
            self.assertIn(excluded_path, source)
        self.assertIn(
            'SNAPSHOT_SECRET_DIR="$SOURCE_SNAPSHOT_ROOT/deploy/connected/secrets"',
            source,
        )
        self.assertIn("! -name README.md", source)
        for forbidden_assignment in (
            'SOURCE_SNAPSHOT_ROOT="$REPORT_DIR',
            'SOURCE_SNAPSHOT_ROOT="$TRUST_INPUT_DIR',
            'SOURCE_SNAPSHOT_ROOT="$INNER_TMP',
            'SOURCE_SNAPSHOT_ROOT="$INVOCATION_TMP_ROOT',
        ):
            self.assertNotIn(forbidden_assignment, source)

    def test_campaign_pin_rejects_mixed_source_snapshot_and_pin_tamper(self) -> None:
        image_id = f"sha256:{'a' * 64}"
        head_commit = "b" * 40
        repository_head = BOUNDARY_MODULE._git_output(
            [
                "/usr/bin/git",
                "-c",
                f"safe.directory={ROOT}",
                "-C",
                str(ROOT),
                "rev-parse",
                "HEAD",
            ]
        )
        implementation_contract_hash = BOUNDARY_MODULE._implementation_contract_hash(ROOT)
        self.assertRegex(repository_head, r"\A[0-9a-f]{40}\Z")
        self.assertRegex(implementation_contract_hash, r"\Asha256:[0-9a-f]{64}\Z")

        with tempfile.TemporaryDirectory(prefix="formowl-runner-campaign-") as temporary:
            temporary_path = Path(temporary)
            current_root = temporary_path / "current"
            source_snapshot_root = temporary_path / "snapshot"
            git_metadata_root = temporary_path / "campaign" / "git-snapshot" / ".git"
            trust_input_dir = temporary_path / "trust-inputs"
            pin_path = trust_input_dir / "campaign-source-pin.json"
            for root in (current_root, source_snapshot_root):
                scripts_dir = root / "scripts"
                scripts_dir.mkdir(parents=True)
                (scripts_dir / RUNNER.name).write_text("#!/bin/sh\n", encoding="utf-8")
                (scripts_dir / BOUNDARY_HELPER.name).write_text(
                    "# boundary\n",
                    encoding="utf-8",
                )
                (root / "contract.txt").write_text("contract-v1\n", encoding="utf-8")
                (root / "ordinary-source.txt").write_text("source-v1\n", encoding="utf-8")
            git_metadata_root.mkdir(parents=True, mode=0o700)
            git_metadata_root.chmod(0o700)
            (git_metadata_root / "HEAD").write_text(
                f"{head_commit}\n",
                encoding="utf-8",
            )
            trust_input_dir.mkdir(mode=0o700)
            trust_input_dir.chmod(0o700)

            def contract_hash(root: Path) -> str:
                return BOUNDARY_MODULE._sha256_bytes((root / "contract.txt").read_bytes())

            def git_output(arguments: list[str]) -> str:
                if "rev-parse" in arguments:
                    return head_commit
                if "cat-file" in arguments:
                    return ""
                raise AssertionError(arguments)

            with (
                mock.patch.object(
                    BOUNDARY_MODULE,
                    "_implementation_contract_hash",
                    side_effect=contract_hash,
                ),
                mock.patch.object(
                    BOUNDARY_MODULE,
                    "_git_output",
                    side_effect=git_output,
                ),
            ):
                self.assertFalse(
                    BOUNDARY_MODULE.create_campaign_pin(
                        current_root=current_root,
                        source_snapshot_root=source_snapshot_root,
                        git_metadata_root=git_metadata_root,
                        pin_path=pin_path,
                        image_id="invalid-image-id",
                        git_base_commit=head_commit,
                    )
                )
                self.assertFalse(pin_path.exists())
                self.assertTrue(
                    BOUNDARY_MODULE.create_campaign_pin(
                        current_root=current_root,
                        source_snapshot_root=source_snapshot_root,
                        git_metadata_root=git_metadata_root,
                        pin_path=pin_path,
                        image_id=image_id,
                        git_base_commit=head_commit,
                    )
                )
                original_pin = pin_path.read_bytes()
                campaign = BOUNDARY_MODULE.verify_campaign(
                    current_root=current_root,
                    source_snapshot_root=source_snapshot_root,
                    git_metadata_root=git_metadata_root,
                    pin_path=pin_path,
                )
                self.assertIsNotNone(campaign)
                self.assertEqual(campaign["dev_image_id"], image_id)
                self.assertEqual(
                    campaign["docker_authority"],
                    "trusted_operator_docker_daemon",
                )
                self.assertIs(campaign["sandboxed_untrusted_source"], False)

                (current_root / "contract.txt").write_text(
                    "contract-v2\n",
                    encoding="utf-8",
                )
                self.assertIsNone(
                    BOUNDARY_MODULE.verify_campaign(
                        current_root=current_root,
                        source_snapshot_root=source_snapshot_root,
                        git_metadata_root=git_metadata_root,
                        pin_path=pin_path,
                    )
                )
                self.assertIsNotNone(
                    BOUNDARY_MODULE.verify_campaign(
                        current_root=None,
                        source_snapshot_root=source_snapshot_root,
                        git_metadata_root=git_metadata_root,
                        pin_path=pin_path,
                    )
                )
                (current_root / "contract.txt").write_text(
                    "contract-v1\n",
                    encoding="utf-8",
                )

                snapshot_source = source_snapshot_root / "ordinary-source.txt"
                snapshot_source.write_text("source-tampered\n", encoding="utf-8")
                self.assertIsNone(
                    BOUNDARY_MODULE.verify_campaign(
                        current_root=current_root,
                        source_snapshot_root=source_snapshot_root,
                        git_metadata_root=git_metadata_root,
                        pin_path=pin_path,
                    )
                )
                snapshot_source.write_text("source-v1\n", encoding="utf-8")

                pin_path.chmod(0o600)
                pin_path.write_bytes(original_pin.replace(b'"status":"frozen"', b'"status":"bad"'))
                pin_path.chmod(0o400)
                self.assertIsNone(
                    BOUNDARY_MODULE.verify_campaign(
                        current_root=current_root,
                        source_snapshot_root=source_snapshot_root,
                        git_metadata_root=git_metadata_root,
                        pin_path=pin_path,
                    )
                )
                pin_path.chmod(0o600)
                pin_path.write_bytes(original_pin)
                pin_path.chmod(0o400)
                pin_path.unlink()
                self.assertIsNone(
                    BOUNDARY_MODULE.verify_campaign(
                        current_root=current_root,
                        source_snapshot_root=source_snapshot_root,
                        git_metadata_root=git_metadata_root,
                        pin_path=pin_path,
                    )
                )

    def test_campaign_pin_real_happy_path_creates_and_verifies(self) -> None:
        image_id = f"sha256:{'a' * 64}"

        with tempfile.TemporaryDirectory(prefix="formowl-runner-campaign-real-") as temporary:
            temporary_path = Path(temporary)
            current_root = temporary_path / "current"
            source_snapshot_root = temporary_path / "snapshot"
            git_metadata_root = temporary_path / "campaign" / "git-snapshot" / ".git"
            trust_input_dir = temporary_path / "trust-inputs"
            pin_path = trust_input_dir / "campaign-source-pin.json"

            _write_issue20_contract_fixture(current_root)
            shutil.copytree(current_root, source_snapshot_root)
            trust_input_dir.mkdir(mode=0o700)

            subprocess.run(
                ["/usr/bin/git", "init", "--quiet", str(current_root)],
                check=True,
            )
            subprocess.run(
                ["/usr/bin/git", "-C", str(current_root), "add", "."],
                check=True,
            )
            subprocess.run(
                [
                    "/usr/bin/git",
                    "-C",
                    str(current_root),
                    "-c",
                    "user.name=FormOwl Test",
                    "-c",
                    "user.email=formowl-test@example.invalid",
                    "commit",
                    "--quiet",
                    "-m",
                    "fixture",
                ],
                check=True,
            )
            head_commit = BOUNDARY_MODULE._git_output(
                ["/usr/bin/git", "-C", str(current_root), "rev-parse", "HEAD"]
            )
            subprocess.run(
                [
                    "/usr/bin/git",
                    "clone",
                    "--quiet",
                    "--bare",
                    "--no-hardlinks",
                    str(current_root),
                    str(git_metadata_root),
                ],
                check=True,
            )
            tree_before_pin = _tree_state(temporary_path)

            self.assertTrue(
                BOUNDARY_MODULE.create_campaign_pin(
                    current_root=current_root,
                    source_snapshot_root=source_snapshot_root,
                    git_metadata_root=git_metadata_root,
                    pin_path=pin_path,
                    image_id=image_id,
                    git_base_commit=head_commit,
                )
            )
            campaign = BOUNDARY_MODULE.verify_campaign(
                current_root=current_root,
                source_snapshot_root=source_snapshot_root,
                git_metadata_root=git_metadata_root,
                pin_path=pin_path,
            )

            self.assertIsNotNone(campaign)
            self.assertEqual(campaign["git_head_commit"], head_commit)
            self.assertEqual(campaign["dev_image_id"], image_id)
            self.assertEqual(
                campaign["runner_sha256"],
                BOUNDARY_MODULE.file_sha256(
                    source_snapshot_root / "scripts" / RUNNER.name,
                    expected_uid=os.getuid(),
                ),
            )
            self.assertEqual(
                _tree_state(temporary_path, excluded={pin_path}),
                tree_before_pin,
            )
            self.assertFalse(
                any(
                    path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"}
                    for path in source_snapshot_root.rglob("*")
                )
            )

    def test_real_implementation_contract_hash_never_writes_bytecode(self) -> None:
        with tempfile.TemporaryDirectory(prefix="formowl-runner-contract-bytecode-") as temporary:
            root = Path(temporary) / "fixture"
            _write_issue20_contract_fixture(root)
            tree_before = _tree_state(root)
            original_setting = sys.dont_write_bytecode

            value = BOUNDARY_MODULE._implementation_contract_hash(root)

            self.assertRegex(value, r"\Asha256:[0-9a-f]{64}\Z")
            self.assertEqual(_tree_state(root), tree_before)
            self.assertIs(sys.dont_write_bytecode, original_setting)
            self.assertFalse(
                any(
                    path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"}
                    for path in root.rglob("*")
                )
            )

    def test_implementation_contract_hash_restores_bytecode_setting_on_error(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="formowl-runner-contract-bytecode-error-"
        ) as temporary:
            root = Path(temporary) / "fixture"
            module_path = root / "python" / "formowl_evidence" / "issue20.py"
            module_path.parent.mkdir(parents=True)
            module_path.write_text("raise RuntimeError('fixture failure')\n", encoding="utf-8")
            tree_before = _tree_state(root)

            for original_setting in (False, True):
                with self.subTest(original_setting=original_setting):
                    previous_setting = sys.dont_write_bytecode
                    sys.dont_write_bytecode = original_setting
                    try:
                        with self.assertRaisesRegex(RuntimeError, "fixture failure"):
                            BOUNDARY_MODULE._implementation_contract_hash(root)
                        self.assertIs(sys.dont_write_bytecode, original_setting)
                        self.assertEqual(_tree_state(root), tree_before)
                    finally:
                        sys.dont_write_bytecode = previous_setting

    def test_operator_trust_inputs_are_outside_reports_exclusive_and_never_replaced(
        self,
    ) -> None:
        source = RUNNER.read_text(encoding="utf-8")

        self.assertIn('TRUST_INPUT_DIR="$SCRATCH_ROOT/trust-inputs"', source)
        self.assertIn(
            'AUTHORITY="$TRUST_INPUT_DIR/operator-postgresql-execution-authority.json"',
            source,
        )
        self.assertIn(
            'AUTHORITY_PIN="$TRUST_INPUT_DIR/operator-postgresql-execution-authority-pin.json"',
            source,
        )
        self.assertNotIn('AUTHORITY="$REPORT_DIR/', source)
        self.assertNotIn('AUTHORITY_PIN="$REPORT_DIR/', source)
        self.assertNotIn('rm -f "$REPORT" "$VALIDATION" "$AUTHORITY"', source)
        self.assertNotIn('rm -f "$AUTHORITY"', source)
        self.assertNotIn('rm -f "$AUTHORITY_PIN"', source)
        self.assertGreaterEqual(source.count("stat -c '%a' \"$TRUST_INPUT\""), 2)
        self.assertGreaterEqual(source.count("stat -c '%u' \"$TRUST_INPUT\""), 2)
        self.assertGreaterEqual(source.count('"$TRUST_INPUT_CANONICAL" != "$TRUST_INPUT"'), 2)
        operator_case = source.index("        operator)\n")
        existing_rejection = source.index('[ -e "$AUTHORITY" ]', operator_case)
        raw_journey = source.index(
            '"$ROOT/scripts/connected_operator_postgres_live_journey.py"',
            existing_rejection,
        )
        self.assertLess(existing_rejection, raw_journey)
        self.assertIn('grep -R -F "$ROOT" "$REPORT_DIR"', source)
        self.assertNotIn('grep -R -F "$ROOT" "$TRUST_INPUT_DIR"', source)

    def test_operator_candidates_are_outer_sealed_and_failed_seal_is_retryable(
        self,
    ) -> None:
        authority_name, pin_name = BOUNDARY_MODULE._OPERATOR_AUTHORITY_NAMES
        with tempfile.TemporaryDirectory(prefix="formowl-runner-sealing-") as temporary:
            temporary_path = Path(temporary)
            candidate_dir = temporary_path / "handoff-candidates"
            trust_input_dir = temporary_path / "trust-inputs"
            candidate_dir.mkdir(mode=0o700)
            trust_input_dir.mkdir(mode=0o700)
            candidate_dir.chmod(0o700)
            trust_input_dir.chmod(0o700)
            candidate_payloads = {
                authority_name: b'{"authority":"candidate"}\n',
                pin_name: b'{"pin":"candidate"}\n',
            }
            for name, payload in candidate_payloads.items():
                path = candidate_dir / name
                path.write_bytes(payload)
                path.chmod(0o400)
            (candidate_dir / "outer-validation.json").write_text(
                '{"blockers":[],"passed":true}\n',
                encoding="utf-8",
            )

            real_open = os.open

            def fail_second_seal(
                path: str | os.PathLike[str], flags: int, mode: int = 0o777
            ) -> int:
                if Path(path) == trust_input_dir / pin_name and flags & os.O_CREAT:
                    raise OSError(errno.EIO, "bounded test failure")
                return real_open(path, flags, mode)

            with mock.patch.object(
                BOUNDARY_MODULE.os,
                "open",
                side_effect=fail_second_seal,
            ):
                self.assertFalse(
                    BOUNDARY_MODULE.seal_operator_trust_inputs(
                        candidate_dir=candidate_dir,
                        trust_input_dir=trust_input_dir,
                    )
                )
            self.assertFalse((trust_input_dir / authority_name).exists())
            self.assertFalse((trust_input_dir / pin_name).exists())

            self.assertTrue(
                BOUNDARY_MODULE.seal_operator_trust_inputs(
                    candidate_dir=candidate_dir,
                    trust_input_dir=trust_input_dir,
                )
            )
            sealed_payloads = {
                name: (trust_input_dir / name).read_bytes()
                for name in BOUNDARY_MODULE._OPERATOR_AUTHORITY_NAMES
            }
            for name, payload in sealed_payloads.items():
                self.assertEqual(payload, candidate_payloads[name])
                self.assertEqual(
                    stat.S_IMODE((trust_input_dir / name).stat().st_mode),
                    0o400,
                )

            for name in BOUNDARY_MODULE._OPERATOR_AUTHORITY_NAMES:
                candidate = candidate_dir / name
                candidate.chmod(0o600)
                candidate.write_bytes(b'{"inner":"replacement-attempt"}\n')
                candidate.chmod(0o400)
            self.assertFalse(
                BOUNDARY_MODULE.seal_operator_trust_inputs(
                    candidate_dir=candidate_dir,
                    trust_input_dir=trust_input_dir,
                )
            )
            self.assertEqual(
                {
                    name: (trust_input_dir / name).read_bytes()
                    for name in BOUNDARY_MODULE._OPERATOR_AUTHORITY_NAMES
                },
                sealed_payloads,
            )
            self.assertTrue(BOUNDARY_MODULE.clear_operator_candidates(candidate_dir))
            self.assertEqual(list(candidate_dir.iterdir()), [])

            unexpected = candidate_dir / "unexpected.json"
            unexpected.write_text('{"status":"unexpected"}\n', encoding="utf-8")
            self.assertFalse(BOUNDARY_MODULE.clear_operator_candidates(candidate_dir))
            self.assertEqual(unexpected.read_text(encoding="utf-8"), '{"status":"unexpected"}\n')

    def test_runner_explicitly_reports_docker_daemon_authority_not_sandboxing(
        self,
    ) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        boundary_source = BOUNDARY_HELPER.read_text(encoding="utf-8")

        self.assertGreaterEqual(
            source.count('"docker_authority":"trusted_operator_docker_daemon"'),
            2,
        )
        self.assertGreaterEqual(source.count('"host_docker_socket_delegated":true'), 2)
        self.assertGreaterEqual(source.count('"sandboxed_untrusted_source":false'), 2)
        self.assertNotIn('"sandboxed_untrusted_source":true', source)
        self.assertIn(
            "FORMOWL_RUNNER_DOCKER_AUTHORITY=trusted_operator_docker_daemon",
            source,
        )
        self.assertIn("FORMOWL_RUNNER_SANDBOXED_UNTRUSTED_SOURCE=0", source)
        self.assertIn(
            '_DOCKER_AUTHORITY = "trusted_operator_docker_daemon"',
            boundary_source,
        )
        self.assertIn('value.get("sandboxed_untrusted_source") is not False', boundary_source)

    def test_operator_failure_diagnostic_is_fixed_private_and_stage_safe(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")

        self.assertIn(
            'OPERATOR_FAILURE_DIAGNOSTIC="$SCRATCH_ROOT/private-logs/'
            'operator-postgresql-failure-diagnostic.json"',
            source,
        )
        self.assertNotIn('OPERATOR_FAILURE_DIAGNOSTIC="$REPORT_DIR/', source)
        self.assertNotIn('OPERATOR_FAILURE_DIAGNOSTIC="$TRUST_INPUT_DIR/', source)
        inside_runner = source.index('if [ "$#" -eq 2 ] && [ "$MODE" = "__inside-runner" ]')
        diagnostic_collision = source.index(
            '[ -e "$OPERATOR_FAILURE_DIAGNOSTIC" ]',
            inside_runner,
        )
        operator_case = source.index("        operator)\n")
        raw_journey = source.index(
            '"$ROOT/scripts/connected_operator_postgres_live_journey.py"',
            operator_case,
        )
        diagnostic_argument = source.index(
            '--failure-diagnostic-output "$OPERATOR_FAILURE_DIAGNOSTIC"',
            raw_journey,
        )
        self.assertLess(diagnostic_collision, raw_journey)
        self.assertGreater(diagnostic_argument, raw_journey)
        self.assertGreaterEqual(
            source.count('[ -e "$OPERATOR_FAILURE_DIAGNOSTIC" ]'),
            3,
        )
        self.assertIn(
            '{"error":"runner_command_failed","stage":"%s","status":"error"}',
            source,
        )
        self.assertIn(
            '{"error":"runner_command_failed","status":"error"}',
            source,
        )
        self.assertNotIn('cat "$RUN_LOG"', source)
        self.assertNotIn('tail "$RUN_LOG"', source)

    def test_operator_failure_diagnostic_docs_pin_two_stage_cross_uid_custody(
        self,
    ) -> None:
        evidence_runbook = (ROOT / "docs/issue20-oauth-evidence-runbook.md").read_text(
            encoding="utf-8"
        )
        closed_beta_runbook = (ROOT / "docs/closed-beta-runbook.md").read_text(encoding="utf-8")
        verification_status = (
            ROOT / "docs/issue20-account-system-verification-status.md"
        ).read_text(encoding="utf-8")

        self.assertNotIn(
            "The child may create it only on failure, with exclusive mode-`0400` creation",
            evidence_runbook,
        )
        for name, document in (
            ("evidence_runbook", evidence_runbook),
            ("closed_beta_runbook", closed_beta_runbook),
            ("verification_status", verification_status),
        ):
            with self.subTest(document=name):
                normalized = " ".join(document.lower().split())
                self.assertIn("inner runtime uid `10001`", normalized)
                self.assertIn("mode `0444`", normalized)
                self.assertIn(
                    "runner-owned mode `0400` final diagnostic",
                    normalized,
                )
                self.assertIn("outer", normalized)

    def test_persisted_operator_failure_diagnostic_locks_every_campaign_mode(
        self,
    ) -> None:
        runner_source = RUNNER.read_text(encoding="utf-8")
        helper_source = BOUNDARY_HELPER.read_text(encoding="utf-8")
        scratch_assignment = (
            'SCRATCH_ROOT="/tmp/formowl-issue20-containerized-evidence-runner-$RUNNER_UID"'
        )
        modes = (
            "preflight",
            "operator",
            "operator-layer",
            "live-postgresql",
            "lifecycle-a",
            "lifecycle-b",
            "lifecycle-aggregate",
            "local-harness",
        )

        for mode in modes:
            with self.subTest(mode=mode):
                with tempfile.TemporaryDirectory(
                    prefix="formowl-runner-locked-campaign-"
                ) as temporary:
                    temporary_path = Path(temporary)
                    root = temporary_path / "root"
                    scripts_dir = root / "scripts"
                    dockerfile = root / "containers" / "dev" / "Dockerfile"
                    scratch_root = temporary_path / "scratch"
                    scripts_dir.mkdir(parents=True)
                    dockerfile.parent.mkdir(parents=True)
                    scratch_root.mkdir(mode=0o700)
                    scratch_root.chmod(0o700)
                    for child_name in (
                        "home",
                        "tmp",
                        "reports",
                        "private-logs",
                        "trust-inputs",
                    ):
                        child = scratch_root / child_name
                        child.mkdir(mode=0o700)
                        child.chmod(0o700)
                    diagnostic = (
                        scratch_root
                        / "private-logs"
                        / "operator-postgresql-failure-diagnostic.json"
                    )
                    diagnostic.write_text('{"untrusted":"must-lock"}', encoding="utf-8")
                    diagnostic.chmod(0o600)
                    script = scripts_dir / RUNNER.name
                    script.write_text(
                        runner_source.replace(
                            scratch_assignment,
                            f'SCRATCH_ROOT="{scratch_root}"',
                            1,
                        ).replace(
                            "HOST_PYTHON_BIN=/usr/bin/python3",
                            f"HOST_PYTHON_BIN={shlex.quote(sys.executable)}",
                            1,
                        ),
                        encoding="utf-8",
                    )
                    script.chmod(0o700)
                    (scripts_dir / BOUNDARY_HELPER.name).write_text(
                        helper_source,
                        encoding="utf-8",
                    )
                    dockerfile.write_text("FROM scratch\n", encoding="utf-8")

                    result = subprocess.run(
                        ["/bin/sh", str(script), mode],
                        cwd=root,
                        text=True,
                        capture_output=True,
                        timeout=5,
                        check=False,
                    )

                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stderr, "")
                self.assertEqual(
                    json.loads(result.stdout),
                    {"error": "runner_command_failed", "status": "error"},
                )
                self.assertNotIn("must-lock", result.stdout)

    def test_operator_failure_diagnostic_validator_accepts_only_closed_schema(
        self,
    ) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        match = re.search(
            r"^OPERATOR_FAILURE_DIAGNOSTIC_VALIDATION_PROGRAM='(?P<program>.*?)'"
            r"\n\nDOCKER_HOST=",
            source,
            flags=re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(match)
        program = match.group("program")
        stages = (
            "inside_migration",
            "inside_operator_commands",
            "inside_report",
            "inside_runtime_setup",
            "inside_seed",
            "inside_verification",
            "outer_authority",
            "outer_inner_journey",
            "outer_postgresql",
            "outer_report",
            "outer_runtime_cleanup",
            "outer_runtime_setup",
            "outer_secret_set",
        )

        def run_validator(
            path: Path,
            expected_uid: int = os.getuid(),
            *,
            validation_program: str = program,
        ) -> subprocess.CompletedProcess:
            return subprocess.run(
                [
                    sys.executable,
                    "-c",
                    validation_program,
                    str(path),
                    str(expected_uid),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        def run_validator_in_process(
            validation_program: str,
            path: Path,
            expected_uid: int = os.getuid(),
            *,
            patches: tuple[object, ...] = (),
        ) -> subprocess.CompletedProcess[str]:
            stdout = io.StringIO()
            stderr = io.StringIO()
            returncode = 0
            with ExitStack() as stack:
                stack.enter_context(
                    mock.patch.object(
                        sys,
                        "argv",
                        ["validator", str(path), str(expected_uid)],
                    )
                )
                stack.enter_context(mock.patch.object(sys, "stdout", stdout))
                stack.enter_context(mock.patch.object(sys, "stderr", stderr))
                for patcher in patches:
                    stack.enter_context(patcher)
                try:
                    exec(validation_program, {"__name__": "__main__"})
                except SystemExit as error:
                    returncode = error.code if type(error.code) is int else 1
            return subprocess.CompletedProcess(
                args=["validator", str(path), str(expected_uid)],
                returncode=returncode,
                stdout=stdout.getvalue(),
                stderr=stderr.getvalue(),
            )

        def program_without(fragment: str) -> str:
            self.assertEqual(program.count(fragment), 1, fragment)
            return program.replace(fragment, "", 1)

        def valid_payload(stage: str = stages[0]) -> dict[str, object]:
            return {
                "artifact_id": (
                    "formowl_connected_operator_postgres_live_journey_" "failure_diagnostic_v1"
                ),
                "failure_code": "stage_failed",
                "schema_version": 1,
                "stage": stage,
                "status": "failed",
            }

        def assert_guard_required(
            guard_name: str,
            rejected: subprocess.CompletedProcess[str],
            accepted_without_guard: subprocess.CompletedProcess[str],
            *,
            expected_stage: str = stages[0],
        ) -> None:
            with self.subTest(deletion_proof=guard_name):
                self.assertNotEqual(rejected.returncode, 0)
                self.assertEqual(rejected.stdout, "")
                self.assertEqual(rejected.stderr, "")
                self.assertEqual(
                    accepted_without_guard.returncode,
                    0,
                    accepted_without_guard.stderr,
                )
                self.assertEqual(
                    accepted_without_guard.stdout,
                    f"{expected_stage}\n",
                )
                self.assertEqual(accepted_without_guard.stderr, "")

        with tempfile.TemporaryDirectory(prefix="formowl-runner-failure-diagnostic-") as temporary:
            temporary_path = Path(temporary)
            diagnostic = temporary_path / "diagnostic.json"
            for stage in stages:
                with self.subTest(valid_stage=stage):
                    diagnostic.write_text(
                        json.dumps(valid_payload(stage)),
                        encoding="utf-8",
                    )
                    diagnostic.chmod(0o400)
                    result = run_validator(diagnostic)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, f"{stage}\n")
                    self.assertEqual(result.stderr, "")
                    diagnostic.chmod(0o600)

            invalid_payloads: dict[str, object] = {
                "missing": {key: value for key, value in valid_payload().items() if key != "stage"},
                "extra": {**valid_payload(), "detail": "private"},
                "unknown_stage": {**valid_payload(), "stage": "private_stage"},
                "wrong_artifact": {**valid_payload(), "artifact_id": "wrong"},
                "wrong_failure_code": {
                    **valid_payload(),
                    "failure_code": "private_failure",
                },
                "wrong_schema_type": {**valid_payload(), "schema_version": True},
                "wrong_status": {**valid_payload(), "status": "error"},
                "not_an_object": ["inside_migration"],
            }
            for name, payload in invalid_payloads.items():
                with self.subTest(invalid_payload=name):
                    diagnostic.write_text(json.dumps(payload), encoding="utf-8")
                    diagnostic.chmod(0o400)
                    result = run_validator(diagnostic)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(result.stderr, "")
                    diagnostic.chmod(0o600)

            for name, raw_payload in {
                "malformed": "{",
                "duplicate_key": (
                    '{"artifact_id":"formowl_connected_operator_postgres_live_'
                    'journey_failure_diagnostic_v1","artifact_id":"duplicate",'
                    '"failure_code":"stage_failed","schema_version":1,'
                    '"stage":"inside_migration","status":"failed"}'
                ),
            }.items():
                with self.subTest(invalid_json=name):
                    diagnostic.write_text(raw_payload, encoding="utf-8")
                    diagnostic.chmod(0o400)
                    result = run_validator(diagnostic)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(result.stderr, "")
                    diagnostic.chmod(0o600)

            diagnostic.write_text(json.dumps(valid_payload()), encoding="utf-8")
            diagnostic.chmod(0o600)
            wrong_mode = run_validator(diagnostic)
            self.assertNotEqual(wrong_mode.returncode, 0)
            self.assertEqual(wrong_mode.stdout, "")
            self.assertEqual(wrong_mode.stderr, "")

            diagnostic.chmod(0o400)
            wrong_owner = run_validator(diagnostic, expected_uid=os.getuid() + 1)
            self.assertNotEqual(wrong_owner.returncode, 0)
            self.assertEqual(wrong_owner.stdout, "")
            self.assertEqual(wrong_owner.stderr, "")

            link = temporary_path / "diagnostic-link.json"
            link.symlink_to(diagnostic)
            symlinked = run_validator(link)
            self.assertNotEqual(symlinked.returncode, 0)
            self.assertEqual(symlinked.stdout, "")
            self.assertEqual(symlinked.stderr, "")

            hardlink_guard = "            or opened_stat.st_nlink != 1\n"
            hardlink = temporary_path / "diagnostic-hardlink.json"
            os.link(diagnostic, hardlink)
            try:
                assert_guard_required(
                    "hardlink",
                    run_validator(diagnostic),
                    run_validator(
                        diagnostic,
                        validation_program=program_without(hardlink_guard),
                    ),
                )
            finally:
                hardlink.unlink()

            compact_payload = json.dumps(
                valid_payload(),
                separators=(",", ":"),
            ).encode("utf-8")

            too_short_guard = "            or opened_stat.st_size < 2\n"
            diagnostic.chmod(0o600)
            diagnostic.write_bytes(b"{")
            diagnostic.chmod(0o400)

            def run_too_short(validation_program: str) -> subprocess.CompletedProcess[str]:
                return run_validator_in_process(
                    validation_program,
                    diagnostic,
                    patches=(
                        mock.patch.object(
                            json,
                            "loads",
                            return_value=valid_payload(),
                        ),
                    ),
                )

            assert_guard_required(
                "too_short",
                run_too_short(program),
                run_too_short(program_without(too_short_guard)),
            )

            oversized_guard = "            or opened_stat.st_size > 2048\n"
            oversized_payload = compact_payload + b" " * (2049 - len(compact_payload))
            self.assertEqual(len(oversized_payload), 2049)
            diagnostic.chmod(0o600)
            diagnostic.write_bytes(oversized_payload)
            diagnostic.chmod(0o400)
            assert_guard_required(
                "oversized",
                run_validator(diagnostic),
                run_validator(
                    diagnostic,
                    validation_program=program_without(oversized_guard),
                ),
            )

            lstat_open_guard = (
                "            or (opened_stat.st_dev, opened_stat.st_ino)\n"
                "            != (path_stat.st_dev, path_stat.st_ino)\n"
            )
            replacement = temporary_path / "diagnostic-replacement.json"

            def run_lstat_open_replacement(
                validation_program: str,
            ) -> subprocess.CompletedProcess[str]:
                diagnostic.unlink(missing_ok=True)
                replacement.unlink(missing_ok=True)
                diagnostic.write_bytes(compact_payload)
                diagnostic.chmod(0o400)
                replacement.write_text(
                    json.dumps(
                        valid_payload(stages[1]),
                        separators=(",", ":"),
                    ),
                    encoding="utf-8",
                )
                replacement.chmod(0o400)
                real_open = os.open

                def replacing_open(path: str, flags: int) -> int:
                    self.assertEqual(Path(path), diagnostic)
                    os.replace(replacement, diagnostic)
                    return real_open(path, flags)

                return run_validator_in_process(
                    validation_program,
                    diagnostic,
                    patches=(mock.patch.object(os, "open", side_effect=replacing_open),),
                )

            assert_guard_required(
                "lstat_to_open_replacement",
                run_lstat_open_replacement(program),
                run_lstat_open_replacement(program_without(lstat_open_guard)),
                expected_stage=stages[1],
            )

            current_path_guard = (
                "            or (opened_stat.st_dev, opened_stat.st_ino)\n"
                "            != (current_stat.st_dev, current_stat.st_ino)\n"
            )

            def run_current_path_replacement(
                validation_program: str,
            ) -> subprocess.CompletedProcess[str]:
                diagnostic.unlink(missing_ok=True)
                replacement.unlink(missing_ok=True)
                diagnostic.write_bytes(compact_payload)
                diagnostic.chmod(0o400)
                replacement.write_text(
                    json.dumps(
                        valid_payload(stages[1]),
                        separators=(",", ":"),
                    ),
                    encoding="utf-8",
                )
                replacement.chmod(0o400)
                real_stat = os.stat

                def replacing_stat(
                    path: str,
                    *,
                    follow_symlinks: bool = True,
                ) -> os.stat_result:
                    if follow_symlinks is False:
                        self.assertEqual(Path(path), diagnostic)
                        os.replace(replacement, diagnostic)
                    return real_stat(path, follow_symlinks=follow_symlinks)

                return run_validator_in_process(
                    validation_program,
                    diagnostic,
                    patches=(mock.patch.object(os, "stat", side_effect=replacing_stat),),
                )

            assert_guard_required(
                "opened_fd_to_current_path_replacement",
                run_current_path_replacement(program),
                run_current_path_replacement(program_without(current_path_guard)),
            )

            read_size_guard = (
                "        if len(payload) != opened_stat.st_size:\n"
                '            raise ValueError("unstable file")\n'
            )
            diagnostic.unlink(missing_ok=True)
            diagnostic.write_bytes(compact_payload + b"     ")
            diagnostic.chmod(0o400)

            def run_short_read(validation_program: str) -> subprocess.CompletedProcess[str]:
                chunks = iter((compact_payload, b""))
                return run_validator_in_process(
                    validation_program,
                    diagnostic,
                    patches=(
                        mock.patch.object(
                            os,
                            "read",
                            side_effect=lambda *_args: next(chunks, b""),
                        ),
                    ),
                )

            assert_guard_required(
                "read_size_instability",
                run_short_read(program),
                run_short_read(program_without(read_size_guard)),
            )

    def test_runner_failure_diagnostic_handoff_is_fixed_validated_and_one_shot(
        self,
    ) -> None:
        pairs = {
            ("live_postgresql_execution", "command_failed"),
            ("live_postgresql_execution", "report_persist_failed"),
            ("live_postgresql_report", "report_rejected"),
            ("live_postgresql_report_validation", "command_failed"),
            ("live_postgresql_validation", "validation_rejected"),
        }

        def payload(
            stage: str = "live_postgresql_execution",
            failure_code: str = "command_failed",
        ) -> dict[str, object]:
            return {
                "artifact_type": "issue20_runner_failure_diagnostic_v1",
                "failure_code": failure_code,
                "mode": "live-postgresql",
                "schema_version": 1,
                "stage": stage,
                "status": "failed",
            }

        def write_payload(path: Path, value: object, *, mode: int = 0o400) -> None:
            if path.exists() and not path.is_symlink():
                path.chmod(0o600)
            path.write_text(
                json.dumps(value, separators=(",", ":"), sort_keys=True),
                encoding="utf-8",
            )
            path.chmod(mode)

        with tempfile.TemporaryDirectory(prefix="formowl-runner-bounded-diagnostic-") as temporary:
            temporary_path = Path(temporary)
            scratch_root = temporary_path / "scratch"
            private_log_dir = scratch_root / "private-logs"
            scratch_root.mkdir(mode=0o700)
            private_log_dir.mkdir(mode=0o700)
            scratch_root.chmod(0o700)
            private_log_dir.chmod(0o700)
            diagnostic = private_log_dir / BOUNDARY_MODULE._RUNNER_FAILURE_DIAGNOSTIC_NAME

            self.assertIsNone(
                BOUNDARY_MODULE.consume_runner_failure_diagnostic(
                    scratch_root=scratch_root,
                    private_log_dir=private_log_dir,
                )
            )

            for stage, failure_code in sorted(pairs):
                with self.subTest(valid_pair=(stage, failure_code)):
                    self.assertTrue(
                        BOUNDARY_MODULE.write_runner_failure_diagnostic(
                            scratch_root=scratch_root,
                            private_log_dir=private_log_dir,
                            stage=stage,
                            failure_code=failure_code,
                        )
                    )
                    self.assertEqual(
                        stat.S_IMODE(diagnostic.stat().st_mode),
                        0o400,
                    )
                    raw_payload = diagnostic.read_text(encoding="utf-8")
                    self.assertNotIn(str(ROOT), raw_payload)
                    self.assertNotIn("postgresql://", raw_payload)
                    self.assertNotIn("secret", raw_payload)
                    self.assertEqual(
                        BOUNDARY_MODULE.consume_runner_failure_diagnostic(
                            scratch_root=scratch_root,
                            private_log_dir=private_log_dir,
                        ),
                        (stage, failure_code),
                    )
                    self.assertFalse(diagnostic.exists())

            self.assertFalse(
                BOUNDARY_MODULE.write_runner_failure_diagnostic(
                    scratch_root=scratch_root,
                    private_log_dir=private_log_dir,
                    stage="private/path",
                    failure_code="raw_command",
                )
            )
            self.assertFalse(diagnostic.exists())

            collision_payload = json.dumps(
                payload(),
                separators=(",", ":"),
                sort_keys=True,
            )
            diagnostic.write_text(collision_payload, encoding="utf-8")
            diagnostic.chmod(0o400)
            self.assertFalse(
                BOUNDARY_MODULE.write_runner_failure_diagnostic(
                    scratch_root=scratch_root,
                    private_log_dir=private_log_dir,
                    stage="live_postgresql_execution",
                    failure_code="command_failed",
                )
            )
            self.assertEqual(
                diagnostic.read_text(encoding="utf-8"),
                collision_payload,
            )
            diagnostic.chmod(0o600)
            diagnostic.unlink()

            wrong_location = scratch_root / "wrong-private-logs"
            wrong_location.mkdir(mode=0o700)
            wrong_location.chmod(0o700)
            self.assertFalse(
                BOUNDARY_MODULE.write_runner_failure_diagnostic(
                    scratch_root=scratch_root,
                    private_log_dir=wrong_location,
                    stage="live_postgresql_execution",
                    failure_code="command_failed",
                )
            )

            invalid_payloads = {
                "malformed": "{",
                "unknown_stage": json.dumps(
                    payload(stage="private_stage"),
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                "unknown_code": json.dumps(
                    payload(failure_code="private_code"),
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                "extra_field": json.dumps(
                    {**payload(), "detail": "private"},
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            }
            for name, raw_payload in invalid_payloads.items():
                with self.subTest(invalid_content=name):
                    diagnostic.write_text(raw_payload, encoding="utf-8")
                    diagnostic.chmod(0o400)
                    self.assertIsNone(
                        BOUNDARY_MODULE.consume_runner_failure_diagnostic(
                            scratch_root=scratch_root,
                            private_log_dir=private_log_dir,
                        )
                    )
                    diagnostic.chmod(0o600)
                    diagnostic.unlink()

            write_payload(diagnostic, payload(), mode=0o600)
            self.assertIsNone(
                BOUNDARY_MODULE.consume_runner_failure_diagnostic(
                    scratch_root=scratch_root,
                    private_log_dir=private_log_dir,
                )
            )
            diagnostic.unlink()

            oversized = b"{" + b"x" * (BOUNDARY_MODULE._RUNNER_FAILURE_DIAGNOSTIC_MAXIMUM_SIZE)
            diagnostic.write_bytes(oversized)
            diagnostic.chmod(0o400)
            self.assertIsNone(
                BOUNDARY_MODULE.consume_runner_failure_diagnostic(
                    scratch_root=scratch_root,
                    private_log_dir=private_log_dir,
                )
            )
            diagnostic.chmod(0o600)
            diagnostic.unlink()

            target = private_log_dir / "target.json"
            write_payload(target, payload())
            diagnostic.symlink_to(target.name)
            self.assertIsNone(
                BOUNDARY_MODULE.consume_runner_failure_diagnostic(
                    scratch_root=scratch_root,
                    private_log_dir=private_log_dir,
                )
            )
            diagnostic.unlink()
            target.chmod(0o600)
            target.unlink()

            write_payload(diagnostic, payload())
            hardlink = private_log_dir / "diagnostic-hardlink.json"
            os.link(diagnostic, hardlink)
            self.assertIsNone(
                BOUNDARY_MODULE.consume_runner_failure_diagnostic(
                    scratch_root=scratch_root,
                    private_log_dir=private_log_dir,
                )
            )
            hardlink.unlink()
            self.assertEqual(
                BOUNDARY_MODULE.consume_runner_failure_diagnostic(
                    scratch_root=scratch_root,
                    private_log_dir=private_log_dir,
                ),
                ("live_postgresql_execution", "command_failed"),
            )

            diagnostic.mkdir(mode=0o700)
            self.assertIsNone(
                BOUNDARY_MODULE.consume_runner_failure_diagnostic(
                    scratch_root=scratch_root,
                    private_log_dir=private_log_dir,
                )
            )
            diagnostic.rmdir()

            if os.geteuid() == 0:
                write_payload(diagnostic, payload())
                os.chown(diagnostic, 1, -1)
                self.assertIsNone(
                    BOUNDARY_MODULE.consume_runner_failure_diagnostic(
                        scratch_root=scratch_root,
                        private_log_dir=private_log_dir,
                    )
                )
                os.chown(diagnostic, os.getuid(), -1)
                diagnostic.chmod(0o600)
                diagnostic.unlink()

            write_payload(diagnostic, payload())
            with mock.patch.object(os, "unlink", side_effect=OSError("blocked cleanup")):
                self.assertIsNone(
                    BOUNDARY_MODULE.consume_runner_failure_diagnostic(
                        scratch_root=scratch_root,
                        private_log_dir=private_log_dir,
                    )
                )
            self.assertTrue(diagnostic.exists())
            self.assertEqual(
                BOUNDARY_MODULE.consume_runner_failure_diagnostic(
                    scratch_root=scratch_root,
                    private_log_dir=private_log_dir,
                ),
                ("live_postgresql_execution", "command_failed"),
            )
            self.assertFalse(diagnostic.exists())

    def test_live_postgresql_execution_error_capture_is_fixed_consumed_and_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="formowl-runner-live-execution-capture-"
        ) as temporary:
            temporary_path = Path(temporary)
            scratch_root = temporary_path / "scratch"
            private_log_base = scratch_root / "private-logs"
            invocation_log_dir = private_log_base / "invocation.ABCDEFGHIJ"
            private_log_dir = invocation_log_dir / "inner-logs"
            for directory in (
                scratch_root,
                private_log_base,
                invocation_log_dir,
                private_log_dir,
            ):
                directory.mkdir(parents=True, mode=0o700)
                directory.chmod(0o700)
            capture = private_log_dir / BOUNDARY_MODULE._LIVE_POSTGRESQL_EXECUTION_CAPTURE_NAME

            def write_capture(payload: bytes, *, mode: int = 0o600) -> None:
                capture.write_bytes(payload)
                capture.chmod(mode)

            known_error = (
                json.dumps(
                    {
                        "error": "live_e2e_report_persist_failed",
                        "status": "error",
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
                + b"\n"
            )
            write_capture(known_error)
            self.assertEqual(
                BOUNDARY_MODULE.consume_live_postgresql_execution_error(
                    scratch_root=scratch_root,
                    private_log_dir=private_log_dir,
                ),
                "report_persist_failed",
            )
            self.assertFalse(capture.exists())

            write_capture(b"")
            self.assertTrue(
                BOUNDARY_MODULE.clear_live_postgresql_execution_capture(
                    scratch_root=scratch_root,
                    private_log_dir=private_log_dir,
                )
            )
            self.assertFalse(capture.exists())
            self.assertFalse(
                BOUNDARY_MODULE.clear_live_postgresql_execution_capture(
                    scratch_root=scratch_root,
                    private_log_dir=private_log_dir,
                )
            )

            consumed_invalid_payloads = {
                "malformed": b"{",
                "multiple_json_lines": known_error + known_error,
                "unknown_error": b'{"error":"live_e2e_other_safe_error","status":"error"}\n',
                "extra_field": (
                    b'{"detail":"private","error":"live_e2e_report_persist_failed",'
                    b'"status":"error"}\n'
                ),
                "wrong_status": (b'{"error":"live_e2e_report_persist_failed","status":"failed"}\n'),
            }
            for name, payload in consumed_invalid_payloads.items():
                with self.subTest(invalid_payload=name):
                    write_capture(payload)
                    self.assertIsNone(
                        BOUNDARY_MODULE.consume_live_postgresql_execution_error(
                            scratch_root=scratch_root,
                            private_log_dir=private_log_dir,
                        )
                    )
                    self.assertFalse(capture.exists())

            write_capture(known_error, mode=0o640)
            self.assertIsNone(
                BOUNDARY_MODULE.consume_live_postgresql_execution_error(
                    scratch_root=scratch_root,
                    private_log_dir=private_log_dir,
                )
            )
            self.assertTrue(capture.exists())
            capture.chmod(0o600)
            capture.unlink()

            oversized = b"x" * (BOUNDARY_MODULE._LIVE_POSTGRESQL_EXECUTION_CAPTURE_MAXIMUM_SIZE + 1)
            write_capture(oversized)
            self.assertIsNone(
                BOUNDARY_MODULE.consume_live_postgresql_execution_error(
                    scratch_root=scratch_root,
                    private_log_dir=private_log_dir,
                )
            )
            self.assertTrue(capture.exists())
            capture.unlink()

            target = private_log_dir / "capture-target.json"
            target.write_bytes(known_error)
            target.chmod(0o600)
            capture.symlink_to(target.name)
            self.assertIsNone(
                BOUNDARY_MODULE.consume_live_postgresql_execution_error(
                    scratch_root=scratch_root,
                    private_log_dir=private_log_dir,
                )
            )
            self.assertTrue(capture.is_symlink())
            capture.unlink()
            target.unlink()

            write_capture(known_error)
            hardlink = private_log_dir / "capture-hardlink.json"
            os.link(capture, hardlink)
            self.assertIsNone(
                BOUNDARY_MODULE.consume_live_postgresql_execution_error(
                    scratch_root=scratch_root,
                    private_log_dir=private_log_dir,
                )
            )
            self.assertTrue(capture.exists())
            hardlink.unlink()
            capture.unlink()

            write_capture(known_error)
            with mock.patch.object(
                BOUNDARY_MODULE.os,
                "unlink",
                side_effect=OSError("blocked cleanup"),
            ):
                self.assertIsNone(
                    BOUNDARY_MODULE.consume_live_postgresql_execution_error(
                        scratch_root=scratch_root,
                        private_log_dir=private_log_dir,
                    )
                )
            self.assertTrue(capture.exists())
            self.assertEqual(
                BOUNDARY_MODULE.consume_live_postgresql_execution_error(
                    scratch_root=scratch_root,
                    private_log_dir=private_log_dir,
                ),
                "report_persist_failed",
            )

            wrong_location = private_log_base / "inner-logs"
            wrong_location.mkdir(mode=0o700)
            wrong_location.chmod(0o700)
            wrong_capture = wrong_location / BOUNDARY_MODULE._LIVE_POSTGRESQL_EXECUTION_CAPTURE_NAME
            wrong_capture.write_bytes(known_error)
            wrong_capture.chmod(0o600)
            self.assertIsNone(
                BOUNDARY_MODULE.consume_live_postgresql_execution_error(
                    scratch_root=scratch_root,
                    private_log_dir=wrong_location,
                )
            )
            self.assertTrue(wrong_capture.exists())

            if os.geteuid() == 0:
                write_capture(known_error)
                os.chown(capture, 1, -1)
                self.assertIsNone(
                    BOUNDARY_MODULE.consume_live_postgresql_execution_error(
                        scratch_root=scratch_root,
                        private_log_dir=private_log_dir,
                    )
                )
                self.assertTrue(capture.exists())
                os.chown(capture, os.getuid(), -1)
                capture.unlink()

    def test_live_postgresql_inner_stages_write_only_bounded_failure_diagnostics(
        self,
    ) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        case_start = source.index("        live-postgresql)\n")
        case_end = source.index("        lifecycle-a)\n", case_start)
        live_postgresql_case = source[case_start:case_end]
        expected_pairs = {
            1: ("live_postgresql_execution", "command_failed"),
            2: ("live_postgresql_report", "report_rejected"),
            3: ("live_postgresql_report_validation", "command_failed"),
            4: ("live_postgresql_validation", "validation_rejected"),
        }

        with tempfile.TemporaryDirectory(
            prefix="formowl-runner-live-postgresql-stage-"
        ) as temporary:
            temporary_path = Path(temporary)

            def run_scenario(
                fail_at: int,
                *,
                failure_stderr: str | None = None,
                scenario_label: str = "default",
            ) -> tuple[subprocess.CompletedProcess[str], Path]:
                scenario = temporary_path / f"failure-{fail_at}-{scenario_label}"
                scratch_root = scenario / "scratch"
                private_log_base = scratch_root / "private-logs"
                private_log_dir = private_log_base / "invocation.ABCDEFGHIJ" / "inner-logs"
                report_dir = scratch_root / "reports"
                for directory in (
                    scratch_root,
                    private_log_base,
                    private_log_dir.parent,
                    private_log_dir,
                    report_dir,
                ):
                    directory.mkdir(parents=True, mode=0o700)
                    directory.chmod(0o700)
                counter = scenario / "counter"
                counter.write_text("0\n", encoding="utf-8")
                fake_python = scenario / "python"
                fake_python.write_text(
                    "\n".join(
                        (
                            "#!/bin/sh",
                            (
                                f'if [ "$1" = {shlex.quote(str(BOUNDARY_HELPER))} ]; '
                                f'then exec {shlex.quote(sys.executable)} "$@"; fi'
                            ),
                            f"COUNT=$(/bin/cat {shlex.quote(str(counter))})",
                            "COUNT=$((COUNT + 1))",
                            f"printf '%s\\n' \"$COUNT\" > {shlex.quote(str(counter))}",
                            (
                                f'if [ "$COUNT" -eq {fail_at} ]; then '
                                + (
                                    f"printf '%s\\n' {shlex.quote(failure_stderr)} >&2; "
                                    if failure_stderr is not None
                                    else ""
                                )
                                + "exit 41; fi"
                            ),
                            "exit 0",
                        )
                    )
                    + "\n",
                    encoding="utf-8",
                )
                fake_python.chmod(0o700)
                harness = scenario / "inner-live-postgresql.sh"
                harness.write_text(
                    "\n".join(
                        (
                            "#!/bin/sh",
                            "set -eu",
                            "umask 077",
                            f"PYTHON_BIN={shlex.quote(str(fake_python))}",
                            f"ROOT={shlex.quote(str(ROOT))}",
                            f"SCRATCH_ROOT={shlex.quote(str(scratch_root))}",
                            f"PRIVATE_LOG_BASE={shlex.quote(str(private_log_base))}",
                            f"REPORT_DIR={shlex.quote(str(report_dir))}",
                            (
                                "FORMOWL_RUNNER_PRIVATE_LOG_DIR="
                                f"{shlex.quote(str(private_log_dir))}"
                            ),
                            "FORMOWL_RUNNER_IMAGE_ID=sha256:" + "0" * 64,
                            f"LIVE_POSTGRESQL_VALIDATION_PROGRAM={shlex.quote('raise SystemExit(0)')}",
                            "case live-postgresql in",
                            live_postgresql_case,
                            "esac",
                        )
                    ),
                    encoding="utf-8",
                )
                result = subprocess.run(
                    ["/bin/sh", str(harness)],
                    cwd=scenario,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                return result, private_log_base

            success, success_private_log_dir = run_scenario(0)
            self.assertEqual(success.returncode, 0, success.stderr)
            self.assertEqual(success.stdout, "")
            self.assertEqual(success.stderr, "")
            self.assertFalse(
                (success_private_log_dir / BOUNDARY_MODULE._RUNNER_FAILURE_DIAGNOSTIC_NAME).exists()
            )
            self.assertFalse(
                list(
                    success_private_log_dir.rglob(
                        BOUNDARY_MODULE._LIVE_POSTGRESQL_EXECUTION_CAPTURE_NAME
                    )
                )
            )

            for fail_at, expected_pair in expected_pairs.items():
                with self.subTest(fail_at=fail_at):
                    result, private_log_dir = run_scenario(fail_at)
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(result.stderr, "")
                    self.assertEqual(
                        BOUNDARY_MODULE.consume_runner_failure_diagnostic(
                            scratch_root=private_log_dir.parent,
                            private_log_dir=private_log_dir,
                        ),
                        expected_pair,
                    )
                    self.assertFalse(
                        (private_log_dir / BOUNDARY_MODULE._RUNNER_FAILURE_DIAGNOSTIC_NAME).exists()
                    )
                    self.assertFalse(
                        list(
                            private_log_dir.rglob(
                                BOUNDARY_MODULE._LIVE_POSTGRESQL_EXECUTION_CAPTURE_NAME
                            )
                        )
                    )

            persist_failure, persist_private_log_dir = run_scenario(
                1,
                failure_stderr=json.dumps(
                    {
                        "error": "live_e2e_report_persist_failed",
                        "status": "error",
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                scenario_label="known-safe-error",
            )
            self.assertEqual(persist_failure.returncode, 1)
            self.assertEqual(persist_failure.stdout, "")
            self.assertEqual(persist_failure.stderr, "")
            self.assertEqual(
                BOUNDARY_MODULE.consume_runner_failure_diagnostic(
                    scratch_root=persist_private_log_dir.parent,
                    private_log_dir=persist_private_log_dir,
                ),
                ("live_postgresql_execution", "report_persist_failed"),
            )
            self.assertFalse(
                list(
                    persist_private_log_dir.rglob(
                        BOUNDARY_MODULE._LIVE_POSTGRESQL_EXECUTION_CAPTURE_NAME
                    )
                )
            )

            unknown_failure, unknown_private_log_dir = run_scenario(
                1,
                failure_stderr=json.dumps(
                    {
                        "error": "live_e2e_other_safe_error",
                        "status": "error",
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                scenario_label="unknown-safe-error",
            )
            self.assertEqual(unknown_failure.returncode, 1)
            self.assertEqual(unknown_failure.stdout, "")
            self.assertEqual(unknown_failure.stderr, "")
            self.assertEqual(
                BOUNDARY_MODULE.consume_runner_failure_diagnostic(
                    scratch_root=unknown_private_log_dir.parent,
                    private_log_dir=unknown_private_log_dir,
                ),
                ("live_postgresql_execution", "command_failed"),
            )
            self.assertFalse(
                list(
                    unknown_private_log_dir.rglob(
                        BOUNDARY_MODULE._LIVE_POSTGRESQL_EXECUTION_CAPTURE_NAME
                    )
                )
            )

    def test_inner_boundary_is_kernel_verified_before_any_report_write(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        boundary_source = BOUNDARY_HELPER.read_text(encoding="utf-8")

        for required in (
            "os.getppid() == 1",
            'Path("/.dockerenv").is_file()',
            '"ro" in mount_options(Path("/"))',
            '"ro" in mount_options(canonical_root)',
            '"rw" in mount_options(canonical_reports)',
            '"rw" in mount_options(canonical_private_log)',
            '"ro" in mount_options(canonical_trust_inputs)',
            '"ro" in mount_options(canonical_git_metadata)',
            '"rw" in mount_options(canonical_socket)',
            'status.get("NoNewPrivs") == "1"',
            "capability_set_is_empty",
            're.fullmatch(r"[0-9A-Fa-f]+", value)',
            "int(value, 16) == 0",
            "trusted_executable(python_bin)",
            "trusted_executable(docker_bin)",
        ):
            self.assertIn(required, boundary_source)
        self.assertEqual(
            BOUNDARY_MODULE._CAPABILITY_STATUS_FIELDS,
            ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"),
        )
        self.assertNotRegex(
            source,
            r"(?m)^[A-Za-z_][A-Za-z0-9_]*\(\)[ \t]*\{",
        )
        helper_functions = {
            node.name
            for node in ast.parse(boundary_source).body
            if isinstance(node, ast.FunctionDef)
        }
        self.assertEqual(
            helper_functions,
            {
                "_sha256_bytes",
                "_read_regular_file",
                "_open_trusted_private_directory",
                "_open_runner_failure_directory",
                "_runner_failure_payload",
                "write_runner_failure_diagnostic",
                "consume_runner_failure_diagnostic",
                "_open_live_postgresql_execution_capture_directory",
                "_consume_live_postgresql_execution_capture",
                "clear_live_postgresql_execution_capture",
                "consume_live_postgresql_execution_error",
                "file_sha256",
                "tree_sha256",
                "_implementation_contract_hash",
                "_git_output",
                "_unique_object",
                "_read_campaign_pin",
                "create_campaign_pin",
                "verify_campaign",
                "clear_operator_candidates",
                "seal_operator_trust_inputs",
                "trusted_executable",
                "trusted_private_directory",
                "invocation_lock_address",
                "trusted_invocation_lock_descriptor",
                "acquire_invocation_lock",
                "verify_held_invocation_lock",
                "decode_mountinfo_field",
                "mount_options",
                "process_status",
                "verify_inner_boundary",
                "main",
            },
        )
        inside_runner = source.index('if [ "$#" -eq 2 ] && [ "$MODE" = "__inside-runner" ]')
        runner_verification = source.index("issue20_runner_boundary.py", inside_runner)
        runner_write = source.index('rm -f "$REPORT" "$VALIDATION"', inside_runner)
        self.assertLess(runner_verification, runner_write)
        self.assertIn('REPORT_DIR="$SCRATCH_ROOT/reports"', source)
        inside_preflight = source.index('if [ "$MODE" = "__inside-preflight" ]')
        preflight_verification = source.index("issue20_runner_boundary.py", inside_preflight)
        preflight_write = source.index(
            "printf '%s\\n' 'formowl-issue20-runner-fixture-v1'", inside_preflight
        )
        self.assertLess(preflight_verification, preflight_write)

    def test_mount_options_decodes_each_kernel_path_escape_once(self) -> None:
        cases = {
            r"/workspace/with\040space": "/workspace/with space",
            r"/workspace/with\011tab": "/workspace/with\ttab",
            r"/workspace/with\012newline": "/workspace/with\nnewline",
            r"/workspace/with\134backslash": r"/workspace/with\backslash",
        }
        with tempfile.TemporaryDirectory(prefix="formowl-mountinfo-") as temporary:
            mountinfo = Path(temporary) / "mountinfo"
            for index, (encoded, decoded) in enumerate(cases.items(), start=1):
                with self.subTest(encoded=encoded):
                    mountinfo.write_text(
                        f"{index} 1 0:{index} / {encoded} ro,nosuid - ext4 /dev/root ro\n",
                        encoding="utf-8",
                    )
                    self.assertEqual(
                        BOUNDARY_MODULE.mount_options(
                            Path(decoded),
                            mountinfo_path=mountinfo,
                        ),
                        {"ro", "nosuid"},
                    )

    def test_mountinfo_decode_does_not_recursively_reinterpret_literal_escape_text(
        self,
    ) -> None:
        self.assertEqual(
            BOUNDARY_MODULE.decode_mountinfo_field(r"/workspace/literal\134040"),
            r"/workspace/literal\040",
        )

    def test_invocation_lock_is_fixed_kernel_bound_and_reusable_after_close(self) -> None:
        expected_address = b"\0formowl-issue20-evidence-runner-v1-uid-" + str(os.getuid()).encode(
            "ascii"
        )
        self.assertEqual(BOUNDARY_MODULE.invocation_lock_address(), expected_address)

        descriptor, error = BOUNDARY_MODULE.acquire_invocation_lock()
        self.assertIsNone(error)
        self.assertIsNotNone(descriptor)
        self.assertTrue(BOUNDARY_MODULE.verify_held_invocation_lock(descriptor))
        self.assertTrue(stat.S_ISSOCK(os.fstat(descriptor).st_mode))

        second_descriptor, second_error = BOUNDARY_MODULE.acquire_invocation_lock()
        self.assertIsNone(second_descriptor)
        self.assertEqual(second_error, "busy")
        os.close(descriptor)

        replacement_descriptor, replacement_error = BOUNDARY_MODULE.acquire_invocation_lock()
        self.assertIsNone(replacement_error)
        self.assertIsNotNone(replacement_descriptor)
        os.close(replacement_descriptor)

    def test_prebound_same_uid_address_returns_only_bounded_busy_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="formowl-runner-busy-") as temporary:
            root = Path(temporary).resolve() / "root"
            script_path = root / "scripts" / RUNNER.name
            script_path.parent.mkdir(parents=True)
            script_path.write_bytes(RUNNER.read_bytes())
            script_path.chmod(0o700)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as prebound:
                prebound.bind(BOUNDARY_MODULE.invocation_lock_address())
                result = subprocess.run(
                    [
                        sys.executable,
                        str(BOUNDARY_HELPER),
                        "lock-and-exec",
                        "--root",
                        str(root),
                        "--script-path",
                        str(script_path),
                        "--mode",
                        "preflight",
                    ],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    check=False,
                )

        self.assertEqual(result.returncode, 75)
        self.assertEqual(result.stderr, "")
        self.assertEqual(
            json.loads(result.stdout),
            {"error": "runner_invocation_busy", "status": "error"},
        )
        self.assertLess(len(result.stdout.encode("utf-8")), 256)

    def test_lock_and_exec_keeps_validated_runner_inode_across_path_swap(self) -> None:
        trusted_bytes = b"#!/bin/sh\nprintf '%s\\n' trusted-runner\n"
        attacker_bytes = b"#!/bin/sh\nprintf '%s\\n' attacker-runner\n"
        with tempfile.TemporaryDirectory(prefix="formowl-runner-path-swap-") as temporary:
            root = Path(temporary).resolve() / "root"
            script_path = root / "scripts" / RUNNER.name
            displaced_path = root / "scripts" / f"{RUNNER.name}.trusted"
            script_path.parent.mkdir(parents=True)
            script_path.write_bytes(trusted_bytes)
            attacker_path = Path(temporary) / "attacker.sh"
            attacker_path.write_bytes(attacker_bytes)
            lock_descriptor, lock_writer = os.pipe()
            os.close(lock_writer)
            observed_script_bytes: list[bytes] = []
            observed_script_descriptors: list[int] = []

            def swap_path_and_return_lock() -> tuple[int, None]:
                script_path.rename(displaced_path)
                attacker_path.replace(script_path)
                return lock_descriptor, None

            def observe_exec(
                executable: str,
                arguments: list[str],
                environment: dict[str, str],
            ) -> None:
                self.assertEqual(executable, "/bin/sh")
                self.assertEqual(arguments[0], "/bin/sh")
                self.assertEqual(arguments[2:], ["__locked-outer", "preflight"])
                self.assertEqual(environment, dict(os.environ))
                observed_script_bytes.append(Path(arguments[1]).read_bytes())
                observed_script_descriptors.append(int(Path(arguments[1]).name))
                raise OSError("test prevents process replacement")

            stdout = io.StringIO()
            with (
                mock.patch.object(
                    BOUNDARY_MODULE,
                    "acquire_invocation_lock",
                    side_effect=swap_path_and_return_lock,
                ),
                mock.patch.object(BOUNDARY_MODULE.os, "execve", side_effect=observe_exec),
                mock.patch("sys.stdout", stdout),
            ):
                result = BOUNDARY_MODULE.main(
                    [
                        "lock-and-exec",
                        "--root",
                        str(root),
                        "--script-path",
                        str(script_path),
                        "--mode",
                        "preflight",
                    ]
                )

            self.assertEqual(result, 1)
            self.assertEqual(
                json.loads(stdout.getvalue()),
                {"error": "runner_invocation_lock_unavailable", "status": "error"},
            )
            self.assertEqual(observed_script_bytes, [trusted_bytes])
            self.assertEqual(displaced_path.read_bytes(), trusted_bytes)
            self.assertEqual(script_path.read_bytes(), attacker_bytes)
            for descriptor in (
                lock_descriptor,
                BOUNDARY_MODULE._INVOCATION_LOCK_FD,
                *observed_script_descriptors,
            ):
                with self.subTest(descriptor=descriptor):
                    with self.assertRaises(OSError):
                        os.fstat(descriptor)

    def test_trusted_executable_covers_metadata_and_oserror_matrix(self) -> None:
        self.assertTrue(BOUNDARY_MODULE.trusted_executable(Path("/bin/sh")))
        with tempfile.TemporaryDirectory(prefix="formowl-trusted-executable-") as temporary:
            temporary_path = Path(temporary)
            executable = temporary_path / "runner"
            executable.write_bytes(b"#!/bin/sh\nexit 0\n")
            executable.chmod(0o700)
            original_bytes = executable.read_bytes()
            directory = temporary_path / "directory"
            directory.mkdir()

            resolve_failure = mock.Mock(spec=Path)
            resolve_failure.resolve.side_effect = OSError("resolve")
            # Keep the failure local so the function harness can resolve traced files.
            self.assertFalse(BOUNDARY_MODULE.trusted_executable(resolve_failure))
            with mock.patch.object(Path, "stat", side_effect=OSError("stat")):
                self.assertFalse(BOUNDARY_MODULE.trusted_executable(executable))
            self.assertFalse(BOUNDARY_MODULE.trusted_executable(directory))
            with mock.patch.object(BOUNDARY_MODULE.os, "access", return_value=False):
                self.assertFalse(BOUNDARY_MODULE.trusted_executable(executable))

            metadata_values = list(executable.stat())
            metadata_values[4] = 1
            with (
                mock.patch.object(
                    Path,
                    "stat",
                    return_value=os.stat_result(metadata_values),
                ),
                mock.patch.object(Path, "is_file", return_value=True),
                mock.patch.object(BOUNDARY_MODULE.os, "access", return_value=True),
            ):
                self.assertFalse(BOUNDARY_MODULE.trusted_executable(executable))

            executable.chmod(0o722)
            self.assertFalse(BOUNDARY_MODULE.trusted_executable(executable))
            executable.chmod(0o600)
            self.assertFalse(BOUNDARY_MODULE.trusted_executable(executable))
            self.assertEqual(executable.read_bytes(), original_bytes)

    def test_trusted_private_directory_covers_identity_errors_without_mutation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="formowl-private-directory-") as temporary:
            temporary_path = Path(temporary)
            private_directory = temporary_path / "private"
            private_directory.mkdir(mode=0o700)
            private_directory.chmod(0o700)
            expected_path = private_directory.resolve()
            marker = private_directory / "marker.bin"
            marker_bytes = b"private-directory-target-must-not-change"

            self.assertTrue(
                BOUNDARY_MODULE.trusted_private_directory(
                    private_directory,
                    expected_path=expected_path,
                    require_empty=True,
                )
            )
            marker.write_bytes(marker_bytes)
            self.assertTrue(
                BOUNDARY_MODULE.trusted_private_directory(
                    private_directory,
                    expected_path=expected_path,
                )
            )
            self.assertFalse(
                BOUNDARY_MODULE.trusted_private_directory(
                    private_directory,
                    expected_path=expected_path,
                    require_empty=True,
                )
            )
            self.assertFalse(
                BOUNDARY_MODULE.trusted_private_directory(
                    private_directory,
                    expected_path=temporary_path / "wrong",
                )
            )

            private_directory.chmod(0o750)
            self.assertFalse(
                BOUNDARY_MODULE.trusted_private_directory(
                    private_directory,
                    expected_path=expected_path,
                )
            )
            private_directory.chmod(0o700)

            metadata_values = list(private_directory.lstat())
            metadata_values[4] = os.getuid() + 1
            with mock.patch.object(
                Path,
                "lstat",
                return_value=os.stat_result(metadata_values),
            ):
                self.assertFalse(
                    BOUNDARY_MODULE.trusted_private_directory(
                        private_directory,
                        expected_path=expected_path,
                    )
                )

            not_directory = temporary_path / "not-directory"
            not_directory.write_bytes(b"not-a-directory")
            self.assertFalse(
                BOUNDARY_MODULE.trusted_private_directory(
                    not_directory,
                    expected_path=not_directory,
                )
            )
            symlink = temporary_path / "private-link"
            symlink.symlink_to(private_directory, target_is_directory=True)
            self.assertFalse(
                BOUNDARY_MODULE.trusted_private_directory(
                    symlink,
                    expected_path=expected_path,
                )
            )
            resolve_failure = mock.Mock(spec=Path)
            resolve_failure.resolve.side_effect = OSError("resolve")
            # Keep the failure local: the function harness uses Path.resolve while
            # tracing calls, so a process-wide patch would invalidate the evidence run.
            self.assertFalse(
                BOUNDARY_MODULE.trusted_private_directory(
                    resolve_failure,
                    expected_path=expected_path,
                )
            )
            with mock.patch.object(Path, "lstat", side_effect=OSError("lstat")):
                self.assertFalse(
                    BOUNDARY_MODULE.trusted_private_directory(
                        private_directory,
                        expected_path=expected_path,
                    )
                )
            with mock.patch.object(Path, "iterdir", side_effect=OSError("iterdir")):
                self.assertFalse(
                    BOUNDARY_MODULE.trusted_private_directory(
                        private_directory,
                        expected_path=expected_path,
                    )
                )
            self.assertEqual(marker.read_bytes(), marker_bytes)
            self.assertEqual(
                tuple(path.name for path in private_directory.iterdir()), ("marker.bin",)
            )

    def test_lock_descriptor_validation_covers_type_address_and_duplicate_lifetime(
        self,
    ) -> None:
        descriptor, error = BOUNDARY_MODULE.acquire_invocation_lock()
        self.assertIsNone(error)
        self.assertIsNotNone(descriptor)
        before_descriptors = set(os.listdir("/proc/self/fd"))
        self.assertTrue(BOUNDARY_MODULE.trusted_invocation_lock_descriptor(descriptor))
        self.assertTrue(BOUNDARY_MODULE.verify_held_invocation_lock(descriptor))
        self.assertEqual(set(os.listdir("/proc/self/fd")), before_descriptors)
        with socket.socket(fileno=os.dup(descriptor)) as duplicate:
            self.assertEqual(
                duplicate.getsockname(),
                BOUNDARY_MODULE.invocation_lock_address(),
            )
        os.close(descriptor)
        self.assertFalse(BOUNDARY_MODULE.trusted_invocation_lock_descriptor(descriptor))
        self.assertFalse(BOUNDARY_MODULE.verify_held_invocation_lock(descriptor))

        with tempfile.TemporaryFile() as regular_file:
            regular_descriptor = regular_file.fileno()
            self.assertFalse(BOUNDARY_MODULE.trusted_invocation_lock_descriptor(regular_descriptor))
            regular_file.write(b"still-usable")
            regular_file.flush()

        wrong_address = b"\0formowl-issue20-wrong-address-" + str(os.getpid()).encode("ascii")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as wrong_socket:
            wrong_socket.bind(wrong_address)
            self.assertFalse(
                BOUNDARY_MODULE.trusted_invocation_lock_descriptor(wrong_socket.fileno())
            )
            self.assertEqual(wrong_socket.getsockname(), wrong_address)

        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as datagram_socket:
            datagram_socket.bind(BOUNDARY_MODULE.invocation_lock_address())
            self.assertFalse(
                BOUNDARY_MODULE.trusted_invocation_lock_descriptor(datagram_socket.fileno())
            )
            self.assertEqual(
                datagram_socket.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE),
                socket.SOCK_DGRAM,
            )

        class FailingDuplicate:
            def __init__(self) -> None:
                self.closed = False

            def getsockname(self) -> bytes:
                raise OSError("getsockname")

            def close(self) -> None:
                self.closed = True

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as source_socket:
            source_socket.bind(b"\0formowl-issue20-source-" + str(os.getpid()).encode("ascii"))
            failing_duplicate = FailingDuplicate()
            with mock.patch.object(
                BOUNDARY_MODULE.socket,
                "fromfd",
                return_value=failing_duplicate,
            ):
                self.assertFalse(
                    BOUNDARY_MODULE.trusted_invocation_lock_descriptor(source_socket.fileno())
                )
            self.assertTrue(failing_duplicate.closed)
            with mock.patch.object(
                BOUNDARY_MODULE.socket,
                "fromfd",
                side_effect=OSError("fromfd"),
            ):
                self.assertFalse(
                    BOUNDARY_MODULE.trusted_invocation_lock_descriptor(source_socket.fileno())
                )
            self.assertEqual(
                source_socket.getsockname(),
                b"\0formowl-issue20-source-" + str(os.getpid()).encode("ascii"),
            )

    def test_acquire_invocation_lock_failure_matrix_closes_handles_and_retries(
        self,
    ) -> None:
        class FakeSocket:
            def __init__(
                self,
                *,
                bind_error: OSError | None = None,
                fileno_error: OSError | None = None,
                inheritable_error: OSError | None = None,
                detach_error: OSError | None = None,
            ) -> None:
                self.bind_error = bind_error
                self.fileno_error = fileno_error
                self.inheritable_error = inheritable_error
                self.detach_error = detach_error
                self.bound_address: bytes | None = None
                self.closed = False

            def bind(self, address: bytes) -> None:
                self.bound_address = address
                if self.bind_error is not None:
                    raise self.bind_error

            def fileno(self) -> int:
                if self.fileno_error is not None:
                    raise self.fileno_error
                return 41

            def set_inheritable(self, inheritable: bool) -> None:
                self.assertion = inheritable
                if self.inheritable_error is not None:
                    raise self.inheritable_error

            def detach(self) -> int:
                if self.detach_error is not None:
                    raise self.detach_error
                return 41

            def close(self) -> None:
                self.closed = True

        with mock.patch.object(
            BOUNDARY_MODULE.socket,
            "socket",
            side_effect=OSError("socket"),
        ):
            self.assertEqual(
                BOUNDARY_MODULE.acquire_invocation_lock(),
                (None, "unavailable"),
            )

        cases = (
            (
                FakeSocket(bind_error=OSError(errno.EACCES, "bind")),
                None,
                (None, "unavailable"),
            ),
            (
                FakeSocket(bind_error=OSError(errno.EADDRINUSE, "bind")),
                None,
                (None, "busy"),
            ),
            (
                FakeSocket(),
                False,
                (None, "unavailable"),
            ),
            (
                FakeSocket(fileno_error=OSError("fileno")),
                True,
                (None, "unavailable"),
            ),
            (
                FakeSocket(inheritable_error=OSError("set_inheritable")),
                True,
                (None, "unavailable"),
            ),
            (
                FakeSocket(detach_error=OSError("detach")),
                True,
                (None, "unavailable"),
            ),
        )
        for fake_socket, trusted, expected in cases:
            with self.subTest(expected=expected, trusted=trusted):
                patches = [
                    mock.patch.object(
                        BOUNDARY_MODULE.socket,
                        "socket",
                        return_value=fake_socket,
                    )
                ]
                if trusted is not None:
                    patches.append(
                        mock.patch.object(
                            BOUNDARY_MODULE,
                            "trusted_invocation_lock_descriptor",
                            return_value=trusted,
                        )
                    )
                with patches[0]:
                    if len(patches) == 2:
                        with patches[1]:
                            result = BOUNDARY_MODULE.acquire_invocation_lock()
                    else:
                        result = BOUNDARY_MODULE.acquire_invocation_lock()
                self.assertEqual(result, expected)
                self.assertTrue(fake_socket.closed)
                self.assertEqual(
                    fake_socket.bound_address,
                    BOUNDARY_MODULE.invocation_lock_address(),
                )

        descriptor, error = BOUNDARY_MODULE.acquire_invocation_lock()
        self.assertIsNone(error)
        self.assertIsNotNone(descriptor)
        os.close(descriptor)
        replacement, replacement_error = BOUNDARY_MODULE.acquire_invocation_lock()
        self.assertIsNone(replacement_error)
        self.assertIsNotNone(replacement)
        os.close(replacement)

    def test_mount_and_process_parsers_fail_closed_and_use_topmost_mount(self) -> None:
        with tempfile.TemporaryDirectory(prefix="formowl-kernel-parser-") as temporary:
            temporary_path = Path(temporary)
            mountinfo = temporary_path / "mountinfo"
            target = Path("/workspace/stacked")
            mountinfo.write_text(
                "\n".join(
                    (
                        "malformed",
                        "1 0 0:1 / /workspace/stacked ro,nosuid - ext4 /dev/root ro",
                        "2 0 0:2 / /workspace/stacked rw,nodev - tmpfs tmpfs rw",
                        "3 0 0:3 / /workspace/other ro - ext4 /dev/root ro",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                BOUNDARY_MODULE.mount_options(target, mountinfo_path=mountinfo),
                {"rw", "nodev"},
            )
            self.assertEqual(
                BOUNDARY_MODULE.mount_options(
                    Path("/workspace/missing"),
                    mountinfo_path=mountinfo,
                ),
                set(),
            )
            self.assertEqual(
                BOUNDARY_MODULE.mount_options(
                    target,
                    mountinfo_path=temporary_path / "missing-mountinfo",
                ),
                set(),
            )
            self.assertEqual(
                BOUNDARY_MODULE.decode_mountinfo_field(r"/workspace/unknown\999-truncated\04"),
                r"/workspace/unknown\999-truncated\04",
            )

            status_path = temporary_path / "status"
            status_path.write_text(
                "\n".join(
                    (
                        "Name:\tformowl",
                        "Malformed",
                        "Value: first:second",
                        " : ignored-empty-key",
                        "Name: final",
                        "CapInh:\t0000000000000000",
                        "CapPrm:\t0000000000000000",
                        "CapEff:\t0000000000000000",
                        "CapBnd:\t0000000000000000",
                        "CapAmb:\t0000000000000000",
                        "NoNewPrivs:\t1",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                BOUNDARY_MODULE.process_status(status_path=status_path),
                {
                    "Name": "final",
                    "Value": "first:second",
                    "CapInh": "0000000000000000",
                    "CapPrm": "0000000000000000",
                    "CapEff": "0000000000000000",
                    "CapBnd": "0000000000000000",
                    "CapAmb": "0000000000000000",
                    "NoNewPrivs": "1",
                },
            )
            self.assertEqual(
                BOUNDARY_MODULE.process_status(status_path=temporary_path / "missing-status"),
                {},
            )

    def test_main_open_metadata_inheritable_and_dup_failures_are_bounded(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="formowl-runner-main-failures-") as temporary:
            root = Path(temporary).resolve() / "root"
            script_path = root / "scripts" / RUNNER.name
            script_path.parent.mkdir(parents=True)
            script_path.write_bytes(b"#!/bin/sh\nexit 0\n")
            script_path.chmod(0o700)
            arguments = [
                "lock-and-exec",
                "--root",
                str(root),
                "--script-path",
                str(script_path),
                "--mode",
                "preflight",
            ]

            def assert_bounded(stdout: io.StringIO, result: int) -> None:
                self.assertEqual(result, 1)
                self.assertEqual(
                    json.loads(stdout.getvalue()),
                    {
                        "error": "runner_invocation_lock_unavailable",
                        "status": "error",
                    },
                )
                self.assertNotIn(str(root), stdout.getvalue())

            acquire_mock = mock.Mock()
            exec_mock = mock.Mock()
            stdout = io.StringIO()
            with (
                mock.patch.object(BOUNDARY_MODULE.os, "open", side_effect=OSError("open")),
                mock.patch.object(
                    BOUNDARY_MODULE,
                    "acquire_invocation_lock",
                    acquire_mock,
                ),
                mock.patch.object(BOUNDARY_MODULE.os, "execve", exec_mock),
                mock.patch("sys.stdout", stdout),
            ):
                result = BOUNDARY_MODULE.main(arguments)
            assert_bounded(stdout, result)
            acquire_mock.assert_not_called()
            exec_mock.assert_not_called()

            real_open = os.open
            opened_descriptors: list[int] = []

            def tracked_open(path: os.PathLike[str], flags: int) -> int:
                descriptor = real_open(path, flags)
                opened_descriptors.append(descriptor)
                return descriptor

            stdout = io.StringIO()
            with (
                mock.patch.object(BOUNDARY_MODULE.os, "open", side_effect=tracked_open),
                mock.patch.object(BOUNDARY_MODULE.os, "fstat", side_effect=OSError("fstat")),
                mock.patch.object(
                    BOUNDARY_MODULE,
                    "acquire_invocation_lock",
                    acquire_mock,
                ),
                mock.patch.object(BOUNDARY_MODULE.os, "execve", exec_mock),
                mock.patch("sys.stdout", stdout),
            ):
                result = BOUNDARY_MODULE.main(arguments)
            assert_bounded(stdout, result)
            self.assertEqual(len(opened_descriptors), 1)
            with self.assertRaises(OSError):
                os.fstat(opened_descriptors[0])

            opened_descriptors.clear()
            stdout = io.StringIO()
            with (
                mock.patch.object(BOUNDARY_MODULE.os, "open", side_effect=tracked_open),
                mock.patch.object(
                    BOUNDARY_MODULE.os,
                    "set_inheritable",
                    side_effect=OSError("set_inheritable"),
                ),
                mock.patch.object(
                    BOUNDARY_MODULE,
                    "acquire_invocation_lock",
                    acquire_mock,
                ),
                mock.patch.object(BOUNDARY_MODULE.os, "execve", exec_mock),
                mock.patch("sys.stdout", stdout),
            ):
                result = BOUNDARY_MODULE.main(arguments)
            assert_bounded(stdout, result)
            self.assertEqual(len(opened_descriptors), 1)
            with self.assertRaises(OSError):
                os.fstat(opened_descriptors[0])

            metadata = script_path.stat()
            close_mock = mock.Mock()
            stdout = io.StringIO()
            with (
                mock.patch.object(BOUNDARY_MODULE.os, "open", return_value=9),
                mock.patch.object(BOUNDARY_MODULE.os, "fstat", return_value=metadata),
                mock.patch.object(BOUNDARY_MODULE.os, "dup", side_effect=OSError("dup")),
                mock.patch.object(BOUNDARY_MODULE.os, "close", close_mock),
                mock.patch.object(
                    BOUNDARY_MODULE,
                    "acquire_invocation_lock",
                    acquire_mock,
                ),
                mock.patch.object(BOUNDARY_MODULE.os, "execve", exec_mock),
                mock.patch("sys.stdout", stdout),
            ):
                result = BOUNDARY_MODULE.main(arguments)
            assert_bounded(stdout, result)
            self.assertEqual(close_mock.call_args_list, [mock.call(9)])
            acquire_mock.assert_not_called()
            exec_mock.assert_not_called()

    def test_main_lock_and_exec_rejects_aliases_and_each_untrusted_metadata_predicate(
        self,
    ) -> None:
        boundary_tree = ast.parse(BOUNDARY_HELPER.read_text(encoding="utf-8"))
        main_definition = next(
            node
            for node in boundary_tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        )
        main_open_calls = [
            node
            for node in ast.walk(main_definition)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "os"
            and node.func.attr == "open"
        ]
        self.assertEqual(len(main_open_calls), 1)
        self.assertGreaterEqual(len(main_open_calls[0].args), 2)
        open_flag_names = {
            node.attr
            for node in ast.walk(main_open_calls[0].args[1])
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
        }
        self.assertEqual(open_flag_names, {"O_RDONLY", "O_NOFOLLOW", "O_CLOEXEC"})
        expected_open_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC

        def replace_metadata(
            metadata: os.stat_result,
            *,
            st_mode: int | None = None,
            st_dev: int | None = None,
            st_ino: int | None = None,
            st_uid: int | None = None,
        ) -> os.stat_result:
            values = list(metadata)
            replacements = (
                (stat.ST_MODE, st_mode),
                (stat.ST_DEV, st_dev),
                (stat.ST_INO, st_ino),
                (stat.ST_UID, st_uid),
            )
            for index, value in replacements:
                if value is not None:
                    values[index] = value
            return os.stat_result(values)

        def fixture_snapshot(base: Path) -> dict[str, tuple[object, ...]]:
            snapshot: dict[str, tuple[object, ...]] = {}
            paths = [base, *sorted(base.rglob("*"), key=lambda path: path.as_posix())]
            for path in paths:
                metadata = path.lstat()
                relative_path = "." if path == base else path.relative_to(base).as_posix()
                if stat.S_ISLNK(metadata.st_mode):
                    payload: object = ("symlink", os.readlink(path))
                elif stat.S_ISREG(metadata.st_mode):
                    payload = ("file", path.read_bytes())
                elif stat.S_ISDIR(metadata.st_mode):
                    payload = ("directory", None)
                else:
                    payload = ("other", None)
                snapshot[relative_path] = (
                    metadata.st_mode,
                    metadata.st_dev,
                    metadata.st_ino,
                    metadata.st_uid,
                    metadata.st_gid,
                    metadata.st_nlink,
                    metadata.st_size,
                    metadata.st_mtime_ns,
                    metadata.st_ctime_ns,
                    payload,
                )
            return snapshot

        cases = (
            ("root_symlink_alias", "root", None, None),
            ("script_symlink_alias", "script", None, None),
            (
                "descriptor_not_regular",
                None,
                lambda metadata: replace_metadata(
                    metadata,
                    st_mode=stat.S_IFIFO | 0o700,
                ),
                lambda metadata: replace_metadata(
                    metadata,
                    st_mode=stat.S_IFIFO | 0o700,
                ),
            ),
            (
                "st_dev_mismatch",
                None,
                lambda metadata: replace_metadata(
                    metadata,
                    st_dev=metadata.st_dev + 1,
                ),
                None,
            ),
            (
                "st_ino_mismatch",
                None,
                lambda metadata: replace_metadata(
                    metadata,
                    st_ino=metadata.st_ino + 1,
                ),
                None,
            ),
            (
                "st_uid_mismatch",
                None,
                lambda metadata: replace_metadata(
                    metadata,
                    st_uid=metadata.st_uid + 1,
                ),
                None,
            ),
            (
                "mode_mismatch",
                None,
                lambda metadata: replace_metadata(
                    metadata,
                    st_mode=stat.S_IFREG | 0o500,
                ),
                None,
            ),
            (
                "group_writable",
                None,
                lambda metadata: replace_metadata(
                    metadata,
                    st_mode=stat.S_IFREG | 0o720,
                ),
                lambda metadata: replace_metadata(
                    metadata,
                    st_mode=stat.S_IFREG | 0o720,
                ),
            ),
            (
                "world_writable",
                None,
                lambda metadata: replace_metadata(
                    metadata,
                    st_mode=stat.S_IFREG | 0o702,
                ),
                lambda metadata: replace_metadata(
                    metadata,
                    st_mode=stat.S_IFREG | 0o702,
                ),
            ),
        )
        expected_error = '{"error":"runner_invocation_lock_unavailable","status":"error"}\n'

        for case_name, alias_kind, descriptor_mutator, path_mutator in cases:
            with (
                self.subTest(case=case_name),
                tempfile.TemporaryDirectory(
                    prefix=f"formowl-runner-main-trust-{case_name}-"
                ) as temporary,
            ):
                temporary_path = Path(temporary).resolve()
                root = temporary_path / "root"
                script_path = root / "scripts" / RUNNER.name
                script_path.parent.mkdir(parents=True)
                script_path.write_bytes(b"#!/bin/sh\nexit 0\n")
                script_path.chmod(0o700)
                root_argument = root
                script_argument = script_path
                if alias_kind == "root":
                    root_argument = temporary_path / "root-alias"
                    root_argument.symlink_to(root.name, target_is_directory=True)
                elif alias_kind == "script":
                    script_argument = script_path.with_name("runner-alias.sh")
                    script_argument.symlink_to(script_path.name)

                script_bytes = script_path.read_bytes()
                tree_before = fixture_snapshot(temporary_path)
                arguments = [
                    "lock-and-exec",
                    "--root",
                    str(root_argument),
                    "--script-path",
                    str(script_argument),
                    "--mode",
                    "preflight",
                ]
                real_open = os.open
                real_fstat = os.fstat
                real_path_stat = Path.stat
                open_records: list[tuple[Path, int, int]] = []
                opened_descriptors: list[int] = []

                def tracked_open(
                    path: os.PathLike[str],
                    flags: int,
                    mode: int = 0o777,
                    *,
                    dir_fd: int | None = None,
                ) -> int:
                    self.assertEqual(Path(path), script_path)
                    self.assertEqual(flags, expected_open_flags)
                    self.assertEqual(flags & os.O_ACCMODE, os.O_RDONLY)
                    self.assertEqual(flags & (os.O_WRONLY | os.O_RDWR), 0)
                    self.assertEqual(flags & os.O_NOFOLLOW, os.O_NOFOLLOW)
                    self.assertEqual(flags & os.O_CLOEXEC, os.O_CLOEXEC)
                    descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
                    open_records.append((Path(path), flags, descriptor))
                    opened_descriptors.append(descriptor)
                    return descriptor

                def tracked_fstat(descriptor: int) -> os.stat_result:
                    metadata = real_fstat(descriptor)
                    if descriptor in opened_descriptors and descriptor_mutator is not None:
                        return descriptor_mutator(metadata)
                    return metadata

                def tracked_path_stat(
                    path: Path,
                    *args: object,
                    **kwargs: object,
                ) -> os.stat_result:
                    metadata = real_path_stat(path, *args, **kwargs)
                    if Path(path) == script_path and path_mutator is not None:
                        return path_mutator(metadata)
                    return metadata

                acquire_mock = mock.Mock(return_value=(None, "unavailable"))
                exec_mock = mock.Mock()
                stdout = io.StringIO()
                with (
                    mock.patch.object(
                        BOUNDARY_MODULE.os,
                        "open",
                        side_effect=tracked_open,
                    ),
                    mock.patch.object(
                        BOUNDARY_MODULE.os,
                        "fstat",
                        side_effect=tracked_fstat,
                    ),
                    mock.patch.object(
                        BOUNDARY_MODULE.Path,
                        "stat",
                        new=tracked_path_stat,
                    ),
                    mock.patch.object(
                        BOUNDARY_MODULE,
                        "acquire_invocation_lock",
                        acquire_mock,
                    ),
                    mock.patch.object(BOUNDARY_MODULE.os, "execve", exec_mock),
                    mock.patch("sys.stdout", stdout),
                ):
                    result = BOUNDARY_MODULE.main(arguments)

                output = stdout.getvalue()
                self.assertEqual(result, 1)
                self.assertEqual(output, expected_error)
                self.assertEqual(
                    json.loads(output),
                    {
                        "error": "runner_invocation_lock_unavailable",
                        "status": "error",
                    },
                )
                for sensitive_path in (
                    temporary_path,
                    root,
                    root_argument,
                    script_path,
                    script_argument,
                ):
                    self.assertNotIn(str(sensitive_path), output)
                acquire_mock.assert_not_called()
                exec_mock.assert_not_called()
                self.assertEqual(len(open_records), 0 if alias_kind else 1)
                for opened_path, flags, descriptor in open_records:
                    self.assertEqual(opened_path, script_path)
                    self.assertEqual(flags, expected_open_flags)
                    self.assertEqual(flags & os.O_ACCMODE, os.O_RDONLY)
                    self.assertEqual(flags & (os.O_WRONLY | os.O_RDWR), 0)
                    self.assertEqual(flags & os.O_NOFOLLOW, os.O_NOFOLLOW)
                    self.assertEqual(flags & os.O_CLOEXEC, os.O_CLOEXEC)
                    self.assertIn(descriptor, opened_descriptors)
                for descriptor in opened_descriptors:
                    with self.assertRaises(OSError):
                        os.fstat(descriptor)
                self.assertEqual(script_path.read_bytes(), script_bytes)
                self.assertEqual(fixture_snapshot(temporary_path), tree_before)

    def test_main_dup2_failure_preserves_existing_fd9_and_releases_lock(self) -> None:
        with tempfile.TemporaryDirectory(prefix="formowl-runner-main-dup2-") as temporary:
            root = Path(temporary).resolve() / "root"
            script_path = root / "scripts" / RUNNER.name
            script_path.parent.mkdir(parents=True)
            script_path.write_bytes(b"#!/bin/sh\nexit 0\n")
            script_path.chmod(0o700)
            sentinel = Path(temporary) / "fd9-sentinel"
            sentinel_bytes = b"pre-existing-fd9-must-survive"
            sentinel.write_bytes(sentinel_bytes)
            saved_fd9: int | None
            try:
                saved_fd9 = os.dup(BOUNDARY_MODULE._INVOCATION_LOCK_FD)
            except OSError:
                saved_fd9 = None
            sentinel_descriptor = os.open(sentinel, os.O_RDONLY)
            try:
                os.dup2(sentinel_descriptor, BOUNDARY_MODULE._INVOCATION_LOCK_FD)
                if sentinel_descriptor != BOUNDARY_MODULE._INVOCATION_LOCK_FD:
                    os.close(sentinel_descriptor)
                stdout = io.StringIO()
                exec_mock = mock.Mock()
                with (
                    mock.patch.object(
                        BOUNDARY_MODULE.os,
                        "dup2",
                        side_effect=OSError("dup2"),
                    ),
                    mock.patch.object(BOUNDARY_MODULE.os, "execve", exec_mock),
                    mock.patch("sys.stdout", stdout),
                ):
                    result = BOUNDARY_MODULE.main(
                        [
                            "lock-and-exec",
                            "--root",
                            str(root),
                            "--script-path",
                            str(script_path),
                            "--mode",
                            "preflight",
                        ]
                    )

                self.assertEqual(result, 1)
                self.assertEqual(
                    json.loads(stdout.getvalue()),
                    {
                        "error": "runner_invocation_lock_unavailable",
                        "status": "error",
                    },
                )
                self.assertNotIn(str(root), stdout.getvalue())
                exec_mock.assert_not_called()
                os.lseek(BOUNDARY_MODULE._INVOCATION_LOCK_FD, 0, os.SEEK_SET)
                self.assertEqual(
                    os.read(
                        BOUNDARY_MODULE._INVOCATION_LOCK_FD,
                        len(sentinel_bytes),
                    ),
                    sentinel_bytes,
                )
                descriptor, error = BOUNDARY_MODULE.acquire_invocation_lock()
                self.assertIsNone(error)
                self.assertIsNotNone(descriptor)
                os.close(descriptor)
            finally:
                try:
                    os.close(BOUNDARY_MODULE._INVOCATION_LOCK_FD)
                except OSError:
                    pass
                if saved_fd9 is not None:
                    os.dup2(saved_fd9, BOUNDARY_MODULE._INVOCATION_LOCK_FD)
                    os.close(saved_fd9)

    def test_main_post_dup2_exec_failure_restores_existing_fd9_and_closes_temporaries(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="formowl-runner-main-post-dup2-") as temporary:
            root = Path(temporary).resolve() / "root"
            script_path = root / "scripts" / RUNNER.name
            script_path.parent.mkdir(parents=True)
            script_path.write_bytes(b"#!/bin/sh\nexit 0\n")
            script_path.chmod(0o700)
            sentinel = Path(temporary) / "fd9-sentinel"
            sentinel_bytes = b"pre-existing-fd9-must-survive-exec-failure"
            sentinel.write_bytes(sentinel_bytes)
            saved_fd9: int | None
            try:
                saved_fd9 = os.dup(BOUNDARY_MODULE._INVOCATION_LOCK_FD)
            except OSError:
                saved_fd9 = None
            sentinel_descriptor = os.open(sentinel, os.O_RDONLY)
            try:
                os.dup2(sentinel_descriptor, BOUNDARY_MODULE._INVOCATION_LOCK_FD)
                if sentinel_descriptor != BOUNDARY_MODULE._INVOCATION_LOCK_FD:
                    os.close(sentinel_descriptor)

                real_open = os.open
                opened_descriptors: list[int] = []

                def tracked_open(path: os.PathLike[str], flags: int) -> int:
                    descriptor = real_open(path, flags)
                    opened_descriptors.append(descriptor)
                    return descriptor

                real_dup = os.dup
                temporary_descriptors: list[int] = []

                def tracked_dup(descriptor: int) -> int:
                    duplicate = real_dup(descriptor)
                    temporary_descriptors.append(duplicate)
                    return duplicate

                real_acquire = BOUNDARY_MODULE.acquire_invocation_lock
                acquired_descriptors: list[int] = []

                def tracked_acquire() -> tuple[int | None, str | None]:
                    descriptor, error = real_acquire()
                    if descriptor is not None:
                        acquired_descriptors.append(descriptor)
                    return descriptor, error

                stdout = io.StringIO()
                exec_mock = mock.Mock(side_effect=OSError("execve"))
                with (
                    mock.patch.object(
                        BOUNDARY_MODULE.os,
                        "open",
                        side_effect=tracked_open,
                    ),
                    mock.patch.object(
                        BOUNDARY_MODULE.os,
                        "dup",
                        side_effect=tracked_dup,
                    ),
                    mock.patch.object(
                        BOUNDARY_MODULE,
                        "acquire_invocation_lock",
                        side_effect=tracked_acquire,
                    ),
                    mock.patch.object(BOUNDARY_MODULE.os, "execve", exec_mock),
                    mock.patch("sys.stdout", stdout),
                ):
                    result = BOUNDARY_MODULE.main(
                        [
                            "lock-and-exec",
                            "--root",
                            str(root),
                            "--script-path",
                            str(script_path),
                            "--mode",
                            "preflight",
                        ]
                    )

                self.assertEqual(result, 1)
                self.assertEqual(
                    json.loads(stdout.getvalue()),
                    {
                        "error": "runner_invocation_lock_unavailable",
                        "status": "error",
                    },
                )
                self.assertNotIn(str(root), stdout.getvalue())
                self.assertNotIn(str(script_path), stdout.getvalue())
                self.assertNotIn(str(sentinel), stdout.getvalue())
                exec_mock.assert_called_once()
                try:
                    os.lseek(
                        BOUNDARY_MODULE._INVOCATION_LOCK_FD,
                        0,
                        os.SEEK_SET,
                    )
                    observed_sentinel = os.read(
                        BOUNDARY_MODULE._INVOCATION_LOCK_FD,
                        len(sentinel_bytes),
                    )
                except OSError:
                    observed_sentinel = None
                self.assertEqual(observed_sentinel, sentinel_bytes)
                self.assertEqual(len(opened_descriptors), 1)
                self.assertEqual(len(acquired_descriptors), 1)
                self.assertEqual(len(temporary_descriptors), 1)
                for descriptor in (
                    *opened_descriptors,
                    *acquired_descriptors,
                    *temporary_descriptors,
                ):
                    with self.subTest(closed_descriptor=descriptor):
                        with self.assertRaises(OSError):
                            os.fstat(descriptor)
                descriptor, error = BOUNDARY_MODULE.acquire_invocation_lock()
                self.assertIsNone(error)
                self.assertIsNotNone(descriptor)
                os.close(descriptor)
            finally:
                try:
                    os.close(BOUNDARY_MODULE._INVOCATION_LOCK_FD)
                except OSError:
                    pass
                if saved_fd9 is not None:
                    os.dup2(saved_fd9, BOUNDARY_MODULE._INVOCATION_LOCK_FD)
                    os.close(saved_fd9)

    def test_main_verify_held_lock_traces_success_and_closed_failure(self) -> None:
        descriptor, error = BOUNDARY_MODULE.acquire_invocation_lock()
        self.assertIsNone(error)
        self.assertIsNotNone(descriptor)
        self.assertEqual(
            BOUNDARY_MODULE.main(["verify-held-lock", "--lock-fd", str(descriptor)]),
            0,
        )
        os.close(descriptor)
        self.assertEqual(
            BOUNDARY_MODULE.main(["verify-held-lock", "--lock-fd", str(descriptor)]),
            1,
        )

    def test_inner_boundary_rejects_forged_authority_and_scratch_links(self) -> None:
        with (
            tempfile.TemporaryDirectory(prefix="formowl-runner-boundary-") as temporary,
            tempfile.TemporaryDirectory(prefix="f20-sock-", dir="/tmp") as socket_temporary,
        ):
            temporary_path = Path(temporary)
            root = temporary_path / "root"
            script_path = root / "scripts" / "issue20_containerized_evidence_runner.sh"
            dockerfile = root / "containers" / "dev" / "Dockerfile"
            scratch_root = temporary_path / "scratch"
            socket_path = Path(socket_temporary) / "d.sock"
            self.assertLessEqual(len(os.fsencode(socket_path)), 107)
            script_path.parent.mkdir(parents=True)
            dockerfile.parent.mkdir(parents=True)
            script_path.write_text("#!/bin/sh\n", encoding="utf-8")
            dockerfile.write_text("FROM scratch\n", encoding="utf-8")
            scratch_root.mkdir(mode=0o700)
            scratch_root.chmod(0o700)
            for child_name in (
                "campaign",
                "handoff-candidates",
                "home",
                "tmp",
                "reports",
                "private-logs",
                "trust-inputs",
            ):
                child = scratch_root / child_name
                child.mkdir(mode=0o700)
                child.chmod(0o700)
            git_metadata_root = scratch_root / "campaign" / "git-snapshot" / ".git"
            git_metadata_root.mkdir(parents=True, mode=0o700)
            git_metadata_root.chmod(0o700)
            campaign_pin = scratch_root / "trust-inputs" / "campaign-source-pin.json"
            campaign_pin.write_text("{}\n", encoding="utf-8")
            campaign_pin.chmod(0o400)
            reports_dir = scratch_root / "reports"
            candidate_dir = scratch_root / "handoff-candidates"
            trust_input_dir = scratch_root / "trust-inputs"
            home_dir = scratch_root / "home" / "inner-home"
            docker_config_dir = scratch_root / "home" / "inner-docker-config"
            tmp_dir = scratch_root / "tmp" / "inner-tmp"
            private_log_dir = scratch_root / "private-logs" / "inner-logs"
            image_id = f"sha256:{'a' * 64}"
            for child in (home_dir, docker_config_dir, tmp_dir, private_log_dir):
                child.mkdir(mode=0o700)
                child.chmod(0o700)

            root_path = root.resolve()
            filesystem_root = Path("/").resolve()
            original_is_file = Path.is_file

            def controlled_is_file(path: Path) -> bool:
                if path == Path("/.dockerenv"):
                    return True
                return original_is_file(path)

            def controlled_mount_options(path: Path) -> set[str]:
                resolved = path.resolve()
                if resolved in {filesystem_root, root_path}:
                    return {"ro"}
                if resolved in {
                    reports_dir.resolve(),
                    home_dir.resolve(),
                    docker_config_dir.resolve(),
                    tmp_dir.resolve(),
                    private_log_dir.resolve(),
                    candidate_dir.resolve(),
                    socket_path.resolve(),
                }:
                    return {"rw"}
                if resolved in {
                    git_metadata_root.resolve(),
                    trust_input_dir.resolve(),
                }:
                    return {"ro"}
                return set()

            valid_process_status = {
                "CapInh": "0000000000000000",
                "CapPrm": "0000000000000000",
                "CapEff": "0000000000000000",
                "CapBnd": "0000000000000000",
                "CapAmb": "0000000000000000",
                "NoNewPrivs": "1",
            }

            def verify(
                scratch: Path,
                environment: dict[str, str],
                *,
                process_status_value: dict[str, str] | None = None,
            ) -> bool:
                with (
                    mock.patch.dict(os.environ, environment, clear=True),
                    mock.patch.object(BOUNDARY_MODULE.os, "getppid", return_value=1),
                    mock.patch.object(
                        BOUNDARY_MODULE,
                        "process_status",
                        return_value=(
                            valid_process_status
                            if process_status_value is None
                            else process_status_value
                        ),
                    ),
                    mock.patch.object(BOUNDARY_MODULE, "trusted_executable", return_value=True),
                    mock.patch.object(
                        BOUNDARY_MODULE,
                        "verify_campaign",
                        return_value={"dev_image_id": image_id},
                    ),
                    mock.patch.object(
                        BOUNDARY_MODULE,
                        "mount_options",
                        side_effect=controlled_mount_options,
                    ),
                    mock.patch.object(Path, "is_file", controlled_is_file),
                ):
                    return BOUNDARY_MODULE.verify_inner_boundary(
                        mode="operator",
                        root=root,
                        scratch_root=scratch,
                        source_snapshot_root=root,
                        git_metadata_root=git_metadata_root,
                        campaign_pin=campaign_pin,
                        reports_dir=reports_dir,
                        candidate_dir=candidate_dir,
                        trust_input_dir=trust_input_dir,
                        script_path=script_path,
                        python_bin=temporary_path / "python",
                        docker_bin=temporary_path / "docker",
                        docker_socket=socket_path,
                        home_dir=home_dir,
                        docker_config_dir=docker_config_dir,
                        tmp_dir=tmp_dir,
                        private_log_dir=private_log_dir,
                        image_id=image_id,
                    )

            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as socket_handle:
                    socket_handle.bind(str(socket_path))
                    exact_environment = {
                        "COMPOSE_DISABLE_ENV_FILE": "1",
                        "DOCKER_CONFIG": str(docker_config_dir),
                        "DOCKER_HOST": "unix:///var/run/docker.sock",
                        "FORMOWL_RUNNER_CAMPAIGN_PIN": str(campaign_pin),
                        "FORMOWL_RUNNER_CAMPAIGN_PIN_SHA256": BOUNDARY_MODULE.file_sha256(
                            campaign_pin,
                            expected_uid=os.getuid(),
                        ),
                        "FORMOWL_RUNNER_DOCKER_AUTHORITY": ("trusted_operator_docker_daemon"),
                        "FORMOWL_RUNNER_PRIVATE_LOG_DIR": str(private_log_dir),
                        "FORMOWL_RUNNER_IMAGE_ID": image_id,
                        "FORMOWL_RUNNER_SANDBOXED_UNTRUSTED_SOURCE": "0",
                        "HOME": str(home_dir),
                        "TMPDIR": str(tmp_dir),
                    }
                    self.assertTrue(verify(scratch_root, exact_environment))
                    for capability_field in (
                        "CapInh",
                        "CapPrm",
                        "CapEff",
                        "CapBnd",
                        "CapAmb",
                    ):
                        for invalid_kind, invalid_value in (
                            ("missing", None),
                            ("malformed", "not-hex"),
                            ("nonzero", "0000000000000001"),
                        ):
                            with self.subTest(
                                capability_field=capability_field,
                                invalid_kind=invalid_kind,
                            ):
                                invalid_status = dict(valid_process_status)
                                if invalid_value is None:
                                    invalid_status.pop(capability_field)
                                else:
                                    invalid_status[capability_field] = invalid_value
                                self.assertFalse(
                                    verify(
                                        scratch_root,
                                        exact_environment,
                                        process_status_value=invalid_status,
                                    )
                                )
                    self.assertFalse(
                        verify(
                            scratch_root,
                            {"DOCKER_HOST": "unix:///tmp/forged-docker.sock"},
                        )
                    )
                    self.assertFalse(
                        verify(
                            scratch_root,
                            {
                                **exact_environment,
                                "DOCKER_CONTEXT": "forged-context",
                            },
                        )
                    )
                    self.assertFalse(
                        verify(
                            scratch_root,
                            {
                                **exact_environment,
                                "FORMOWL_RUNNER_IMAGE_ID": "formowl-dev:local",
                            },
                        )
                    )
                    for forbidden_name in (
                        "DOCKER_CLI_PLUGIN_EXTRA_DIRS",
                        "BUILDX_CONFIG",
                        "BUILDKIT_HOST",
                        "COMPOSE_FILE",
                        "COMPOSE_PROFILES",
                        "COMPOSE_PROJECT_NAME",
                        "COMPOSE_ENV_FILES",
                        "HTTPS_PROXY",
                    ):
                        with self.subTest(forbidden_name=forbidden_name):
                            self.assertFalse(
                                verify(
                                    scratch_root,
                                    {
                                        **exact_environment,
                                        forbidden_name: "forged-value",
                                    },
                                )
                            )
                    forged_config = docker_config_dir / "config.json"
                    forged_config.write_text("{}\n", encoding="utf-8")
                    try:
                        self.assertFalse(verify(scratch_root, exact_environment))
                    finally:
                        forged_config.unlink()
                    scratch_link = temporary_path / "scratch-link"
                    scratch_link.symlink_to(scratch_root, target_is_directory=True)
                    self.assertFalse(verify(scratch_link, exact_environment))
                    for child_name in (
                        "campaign",
                        "handoff-candidates",
                        "home",
                        "tmp",
                        "reports",
                        "private-logs",
                        "trust-inputs",
                    ):
                        with self.subTest(child_name=child_name):
                            child = scratch_root / child_name
                            saved_child = scratch_root / f"{child_name}-saved"
                            child.rename(saved_child)
                            child.symlink_to(saved_child, target_is_directory=True)
                            try:
                                self.assertFalse(verify(scratch_root, exact_environment))
                            finally:
                                child.unlink()
                                saved_child.rename(child)
            finally:
                os.chdir(previous_cwd)

    def test_clean_docker_cli_environment_ignores_caller_config_and_user_plugins(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="formowl-runner-docker-env-") as temporary:
            temporary_path = Path(temporary)
            caller_home = temporary_path / "caller-home"
            caller_plugins = caller_home / ".docker" / "cli-plugins"
            fresh_home = temporary_path / "fresh-home"
            fresh_config = temporary_path / "fresh-docker-config"
            fresh_tmp = temporary_path / "fresh-tmp"
            marker = temporary_path / "forged-plugin-executed"
            caller_plugins.mkdir(parents=True)
            fresh_home.mkdir(mode=0o700)
            fresh_config.mkdir(mode=0o700)
            fresh_tmp.mkdir(mode=0o700)
            (caller_home / ".docker" / "config.json").write_text(
                '{"proxies":{"default":{"httpProxy":"http://forged.invalid"}}}\n',
                encoding="utf-8",
            )
            for plugin_name in ("docker-buildx", "docker-compose"):
                plugin = caller_plugins / plugin_name
                plugin.write_text(
                    f"#!/bin/sh\nprintf '%s\\n' forged > {marker}\nexit 99\n",
                    encoding="utf-8",
                )
                plugin.chmod(0o755)

            exact_environment = {
                "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "HOME": str(fresh_home),
                "DOCKER_CONFIG": str(fresh_config),
                "DOCKER_HOST": "unix:///var/run/docker.sock",
                "TMPDIR": str(fresh_tmp),
                "COMPOSE_DISABLE_ENV_FILE": "1",
            }
            environment_arguments = [f"{name}={value}" for name, value in exact_environment.items()]
            forged_caller_environment = {
                **os.environ,
                "HOME": str(caller_home),
                "DOCKER_CLI_PLUGIN_EXTRA_DIRS": str(caller_plugins),
                "HTTPS_PROXY": "http://forged.invalid",
            }

            rendered_environment = subprocess.run(
                ["/usr/bin/env", "-i", *environment_arguments, "/usr/bin/env"],
                env=forged_caller_environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(rendered_environment.returncode, 0)
            self.assertEqual(
                set(rendered_environment.stdout.splitlines()),
                {f"{name}={value}" for name, value in exact_environment.items()},
            )

            for plugin_command in (("buildx", "version"), ("compose", "version")):
                with self.subTest(plugin_command=plugin_command):
                    result = subprocess.run(
                        [
                            "/usr/bin/env",
                            "-i",
                            *environment_arguments,
                            "/usr/bin/docker",
                            *plugin_command,
                        ],
                        env=forged_caller_environment,
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertFalse(marker.exists())

    def test_outer_runner_rejects_each_scratch_child_symlink_without_writing_target(
        self,
    ) -> None:
        runner_source = RUNNER.read_text(encoding="utf-8")
        scratch_assignment = (
            'SCRATCH_ROOT="/tmp/formowl-issue20-containerized-evidence-runner-$RUNNER_UID"'
        )
        for child_name in ("home", "tmp", "reports", "private-logs", "trust-inputs"):
            with self.subTest(child_name=child_name):
                with tempfile.TemporaryDirectory(
                    prefix="formowl-runner-child-symlink-"
                ) as temporary:
                    temporary_path = Path(temporary)
                    root = temporary_path / "root"
                    script = root / "scripts" / RUNNER.name
                    scratch_root = temporary_path / "scratch"
                    external_target = temporary_path / "external-target"
                    marker = external_target / "marker.bin"
                    script.parent.mkdir(parents=True)
                    scratch_root.mkdir(mode=0o700)
                    scratch_root.chmod(0o700)
                    external_target.mkdir(mode=0o700)
                    marker.write_bytes(b"external-target-must-remain-byte-identical")
                    for name in (
                        "home",
                        "tmp",
                        "reports",
                        "private-logs",
                        "trust-inputs",
                    ):
                        child = scratch_root / name
                        if name == child_name:
                            child.symlink_to(external_target, target_is_directory=True)
                        else:
                            child.mkdir(mode=0o700)
                            child.chmod(0o700)
                    script.write_text(
                        runner_source.replace(
                            scratch_assignment,
                            f'SCRATCH_ROOT="{scratch_root}"',
                            1,
                        ),
                        encoding="utf-8",
                    )

                    result = subprocess.run(
                        ["/bin/sh", str(script), "preflight"],
                        cwd=temporary_path,
                        text=True,
                        capture_output=True,
                        check=False,
                    )

                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stderr, "")
                    self.assertEqual(
                        json.loads(result.stdout),
                        {"error": "runner_scratch_unavailable", "status": "error"},
                    )
                    self.assertEqual(
                        marker.read_bytes(),
                        b"external-target-must-remain-byte-identical",
                    )
                    self.assertEqual(
                        tuple(path.name for path in external_target.iterdir()),
                        ("marker.bin",),
                    )

    def test_outer_runner_atomically_creates_missing_private_scratch_children(
        self,
    ) -> None:
        runner_source = RUNNER.read_text(encoding="utf-8")
        scratch_assignment = (
            'SCRATCH_ROOT="/tmp/formowl-issue20-containerized-evidence-runner-$RUNNER_UID"'
        )
        with tempfile.TemporaryDirectory(prefix="formowl-runner-child-create-") as temporary:
            temporary_path = Path(temporary)
            root = temporary_path / "root"
            script = root / "scripts" / RUNNER.name
            scratch_root = temporary_path / "scratch"
            script.parent.mkdir(parents=True)
            scratch_root.mkdir(mode=0o700)
            scratch_root.chmod(0o700)
            script.write_text(
                runner_source.replace(
                    scratch_assignment,
                    f'SCRATCH_ROOT="{scratch_root}"',
                    1,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                ["/bin/sh", str(script), "preflight"],
                cwd=temporary_path,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 64)
            self.assertEqual(result.stderr, "")
            self.assertEqual(
                json.loads(result.stdout),
                {"error": "runner_repository_root_required", "status": "error"},
            )
            for child_name in ("home", "tmp", "reports", "private-logs", "trust-inputs"):
                child = scratch_root / child_name
                with self.subTest(child_name=child_name):
                    self.assertTrue(child.is_dir())
                    self.assertFalse(child.is_symlink())
                    self.assertEqual(child.resolve(), child)
                    self.assertEqual(child.stat().st_uid, os.getuid())
                    self.assertEqual(child.stat().st_mode & 0o777, 0o700)

    def test_cross_checkout_second_invocation_fails_busy_without_docker_socket(
        self,
    ) -> None:
        runner_source = RUNNER.read_text(encoding="utf-8")
        helper_source = BOUNDARY_HELPER.read_text(encoding="utf-8")
        scratch_assignment = (
            'SCRATCH_ROOT="/tmp/formowl-issue20-containerized-evidence-runner-$RUNNER_UID"'
        )
        lock_anchor = (
            "# The inherited abstract-socket descriptor stays bound through inner completion."
        )
        with tempfile.TemporaryDirectory(prefix="formowl-runner-concurrency-") as temporary:
            temporary_path = Path(temporary)
            scratch_root = temporary_path / "shared-scratch"
            ready_marker = temporary_path / "first-lock-held"
            release_fifo = temporary_path / "release-first"
            missing_socket = temporary_path / "no-docker.sock"
            fake_docker = temporary_path / "trusted-docker-placeholder"
            os.mkfifo(release_fifo)
            fake_docker.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
            fake_docker.chmod(0o700)
            blocking_source = runner_source.replace(
                lock_anchor,
                "\n".join(
                    (
                        lock_anchor,
                        f"if [ ! -e {shlex.quote(str(ready_marker))} ]; then",
                        f"    printf '%s\\n' locked > {shlex.quote(str(ready_marker))}",
                        f"    /bin/cat {shlex.quote(str(release_fifo))} > /dev/null",
                        "fi",
                    )
                ),
                1,
            )
            blocking_source = blocking_source.replace(
                scratch_assignment,
                f'SCRATCH_ROOT="{scratch_root}"',
                1,
            )
            blocking_source = blocking_source.replace(
                "HOST_PYTHON_BIN=/usr/bin/python3",
                f"HOST_PYTHON_BIN={shlex.quote(sys.executable)}",
                1,
            )
            blocking_source = blocking_source.replace(
                "DOCKER_BIN=/usr/bin/docker",
                f"DOCKER_BIN={shlex.quote(str(fake_docker))}",
                1,
            )
            blocking_source = blocking_source.replace(
                """[ "$(/usr/bin/stat -c '%u' "$DOCKER_RESOLVED")" != "0" ]""",
                """[ "$(/usr/bin/stat -c '%u' "$DOCKER_RESOLVED")" != "$RUNNER_UID" ]""",
                1,
            )
            blocking_source = blocking_source.replace(
                "/var/run/docker.sock",
                str(missing_socket),
            )

            checkout_roots: list[Path] = []
            for checkout_name in ("checkout-a", "checkout-b"):
                root = temporary_path / checkout_name
                scripts_dir = root / "scripts"
                dockerfile = root / "containers" / "dev" / "Dockerfile"
                scripts_dir.mkdir(parents=True)
                dockerfile.parent.mkdir(parents=True)
                (scripts_dir / RUNNER.name).write_text(blocking_source, encoding="utf-8")
                (scripts_dir / BOUNDARY_HELPER.name).write_text(
                    helper_source,
                    encoding="utf-8",
                )
                dockerfile.write_text("FROM scratch\n", encoding="utf-8")
                checkout_roots.append(root)

            first_script = checkout_roots[0] / "scripts" / RUNNER.name
            second_script = checkout_roots[1] / "scripts" / RUNNER.name
            first = subprocess.Popen(
                ["/bin/sh", str(first_script), "preflight"],
                cwd=checkout_roots[0],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and not ready_marker.exists():
                    if first.poll() is not None:
                        break
                    time.sleep(0.01)
                self.assertTrue(ready_marker.exists(), "first runner did not acquire the lock")
                old_lock_path = scratch_root / "invocation.lock"
                old_lock_path.write_bytes(b"obsolete-filesystem-lock")
                old_lock_path.chmod(0o600)
                displaced_scratch = temporary_path / "displaced-scratch"
                scratch_root.rename(displaced_scratch)
                scratch_root.mkdir(mode=0o700)
                scratch_root.chmod(0o700)
                replacement_lock_path = scratch_root / "invocation.lock"
                replacement_lock_path.write_bytes(b"replacement-filesystem-lock")
                replacement_lock_path.chmod(0o600)
                self.assertNotEqual(
                    (displaced_scratch / "invocation.lock").stat().st_ino,
                    replacement_lock_path.stat().st_ino,
                )
                started_at = time.monotonic()
                second = subprocess.run(
                    ["/bin/sh", str(second_script), "preflight"],
                    cwd=checkout_roots[1],
                    text=True,
                    capture_output=True,
                    timeout=3,
                    check=False,
                )
                elapsed = time.monotonic() - started_at

                self.assertEqual(second.returncode, 75)
                self.assertEqual(second.stderr, "")
                self.assertEqual(
                    json.loads(second.stdout),
                    {"error": "runner_invocation_busy", "status": "error"},
                )
                self.assertLess(len(second.stdout.encode("utf-8")), 256)
                self.assertLess(elapsed, 2.0)

                with release_fifo.open("w", encoding="utf-8") as release_handle:
                    release_handle.write("release\n")
                first_stdout, first_stderr = first.communicate(timeout=5)
                self.assertEqual(first.returncode, 1)
                self.assertEqual(first_stderr, "")
                self.assertEqual(
                    json.loads(first_stdout),
                    {"error": "runner_docker_socket_unavailable", "status": "error"},
                )
                after_release = subprocess.run(
                    ["/bin/sh", str(second_script), "preflight"],
                    cwd=checkout_roots[1],
                    text=True,
                    capture_output=True,
                    timeout=3,
                    check=False,
                )
                self.assertEqual(after_release.returncode, 1)
                self.assertEqual(after_release.stderr, "")
                self.assertEqual(
                    json.loads(after_release.stdout),
                    {"error": "runner_docker_socket_unavailable", "status": "error"},
                )
                self.assertFalse(missing_socket.exists())
            finally:
                if first.poll() is None:
                    first.terminate()
                    first.communicate(timeout=5)

    def test_runner_preflight_covers_nested_bind_scripts_and_safe_validation(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")

        for script in (
            "issue20_runner_boundary.py",
            "connected_operator_postgres_live_journey.py",
            "connected_runtime_container_lifecycle_probe.py",
            "connected_runtime_postgres_live_e2e.py",
            "oauth_mcp_harness.py",
        ):
            self.assertIn(script, source)
        self.assertIn("nested_workspace_bind", source)
        self.assertIn("safe_validation", source)
        self.assertIn("runner_validation_output_leak", source)
        self.assertIn('"issue20_script_startup_count":5', source)

    def test_runner_build_failure_stops_before_run_and_success_reaches_run(
        self,
    ) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        build_guard = "if ! /usr/bin/env -i \\\n"
        image_build = '    --file "$SOURCE_SNAPSHOT_ROOT/containers/dev/Dockerfile" \\'
        build_start = source.rfind(build_guard, 0, source.index(image_build))
        self.assertNotEqual(build_start, -1)
        build_end = source.index(
            '\n    IMAGE_ID=$(/bin/cat "$IMAGE_ID_FILE")',
            build_start,
        )
        build_block = source[build_start:build_end]
        self.assertEqual(build_block.count(build_guard), 1)
        mutant_block = build_block.replace(
            build_guard,
            "if /usr/bin/env -i \\\n",
            1,
        )
        image_id = f"sha256:{'0' * 64}"

        def run_build_block(
            block: str,
            *,
            label: str,
            build_succeeds: bool,
        ) -> tuple[subprocess.CompletedProcess[str], tuple[str, ...], Path]:
            scenario = temporary_path / label
            outer_home = scenario / "outer-home"
            outer_docker_config = scenario / "outer-docker-config"
            outer_tmp = scenario / "outer-tmp"
            outer_log_dir = scenario / "outer-logs"
            root = scenario / "root"
            source_snapshot_root = scenario / "source-snapshot"
            for directory in (
                outer_home,
                outer_docker_config,
                outer_tmp,
                outer_log_dir,
                root,
                source_snapshot_root,
            ):
                directory.mkdir(parents=True)
            call_log = scenario / "docker-calls.log"
            build_status = scenario / "build-status"
            build_status.write_text(
                "success" if build_succeeds else "failure",
                encoding="utf-8",
            )
            fake_docker = scenario / "docker"
            fake_docker.write_text(
                "\n".join(
                    (
                        "#!/bin/sh",
                        f"printf '%s\\n' \"$1\" >> {shlex.quote(str(call_log))}",
                        'if [ "$1" = "build" ]; then',
                        (
                            f'    if [ "$(/bin/cat {shlex.quote(str(build_status))})" '
                            '= "failure" ]; then'
                        ),
                        "        exit 41",
                        "    fi",
                        '    while [ "$#" -gt 0 ]; do',
                        '        if [ "$1" = "--iidfile" ]; then',
                        "            shift",
                        f"            printf '%s\\n' {shlex.quote(image_id)} > \"$1\"",
                        "            exit 0",
                        "        fi",
                        "        shift",
                        "    done",
                        "    exit 42",
                        "fi",
                        'if [ "$1" = "run" ]; then',
                        "    exit 0",
                        "fi",
                        "exit 43",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            fake_docker.chmod(0o700)
            build_log = outer_log_dir / "build.log"
            image_id_file = outer_tmp / "formowl-dev.iid"
            harness = scenario / "build-harness.sh"
            harness.write_text(
                "\n".join(
                    (
                        "#!/bin/sh",
                        "set -eu",
                        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                        "export PATH",
                        f"OUTER_HOME={shlex.quote(str(outer_home))}",
                        ("OUTER_DOCKER_CONFIG=" f"{shlex.quote(str(outer_docker_config))}"),
                        f"OUTER_TMP={shlex.quote(str(outer_tmp))}",
                        f"ROOT={shlex.quote(str(root))}",
                        ("SOURCE_SNAPSHOT_ROOT=" f"{shlex.quote(str(source_snapshot_root))}"),
                        f"BUILD_LOG={shlex.quote(str(build_log))}",
                        f"IMAGE_ID_FILE={shlex.quote(str(image_id_file))}",
                        f"DOCKER_BIN={shlex.quote(str(fake_docker))}",
                        "DOCKER_HOST=unix:///bounded-test.sock",
                        "COMPOSE_DISABLE_ENV_FILE=1",
                        block,
                        '"$DOCKER_BIN" run',
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["/bin/sh", str(harness)],
                cwd=scenario,
                text=True,
                capture_output=True,
                check=False,
            )
            calls = (
                tuple(call_log.read_text(encoding="utf-8").splitlines())
                if call_log.exists()
                else ()
            )
            return result, calls, image_id_file

        with tempfile.TemporaryDirectory(prefix="formowl-runner-build-polarity-") as temporary:
            temporary_path = Path(temporary)
            success, success_calls, success_iidfile = run_build_block(
                build_block,
                label="success",
                build_succeeds=True,
            )
            self.assertEqual(success.returncode, 0, success.stderr)
            self.assertEqual(success.stdout, "")
            self.assertEqual(success.stderr, "")
            self.assertEqual(success_calls, ("build", "run"))
            self.assertEqual(success_iidfile.read_text(encoding="utf-8").strip(), image_id)

            failure, failure_calls, failure_iidfile = run_build_block(
                build_block,
                label="failure",
                build_succeeds=False,
            )
            self.assertEqual(failure.returncode, 1)
            self.assertEqual(failure.stderr, "")
            self.assertEqual(
                json.loads(failure.stdout),
                {"error": "runner_image_build_failed", "status": "error"},
            )
            self.assertEqual(failure_calls, ("build",))
            self.assertFalse(failure_iidfile.exists())

            mutant_success, mutant_calls, mutant_iidfile = run_build_block(
                mutant_block,
                label="mutant-success",
                build_succeeds=True,
            )
            self.assertEqual(mutant_success.returncode, 1)
            self.assertEqual(mutant_success.stderr, "")
            self.assertEqual(
                json.loads(mutant_success.stdout),
                {"error": "runner_image_build_failed", "status": "error"},
            )
            self.assertEqual(mutant_calls, ("build",))
            self.assertTrue(mutant_iidfile.exists())

    def test_outer_run_status_follows_inner_exit_and_bounds_operator_diagnostic(
        self,
    ) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        outer_run_start = source.index(
            "if /usr/bin/env -i \\\n",
            source.index("CANDIDATE_MOUNT_MODE=ro"),
        )
        outer_run_end = source.index(
            '\nif [ "$MODE" = "operator" ]; then',
            outer_run_start,
        )
        outer_run_block = source[outer_run_start:outer_run_end]
        success_epilogue = (
            '\nrm -f "$SNAPSHOT_LOG" "$GIT_SNAPSHOT_LOG" "$BUILD_LOG" "$RUN_LOG"\n'
            'printf \'{"artifact_type":"issue20_containerized_evidence_runner_result_v1",'
            '"docker_authority":"trusted_operator_docker_daemon",'
            '"host_docker_socket_delegated":true,"mode":"%s",'
            '"report_validation":"passed","sandboxed_untrusted_source":false,'
            '"status":"passed"}\\n\' "$MODE"\n'
        )
        validation_assignment = "OPERATOR_FAILURE_DIAGNOSTIC_VALIDATION_PROGRAM='"
        validation_start = source.index(validation_assignment) + len(validation_assignment)
        validation_end = source.index("'\n\nDOCKER_HOST=", validation_start)
        validation_program = source[validation_start:validation_end]
        image_id = f"sha256:{'0' * 64}"

        def run_outer_block(
            *,
            label: str,
            mode: str,
            inner_succeeds: bool,
            diagnostic_payload: dict[str, object] | None = None,
        ) -> tuple[subprocess.CompletedProcess[str], tuple[str, ...], Path, Path]:
            scenario = temporary_path / label
            root = scenario / "root"
            scratch_root = scenario / "scratch"
            campaign_dir = scratch_root / "campaign"
            source_snapshot_root = campaign_dir / "source-snapshot"
            git_metadata_root = campaign_dir / "git-snapshot" / ".git"
            report_dir = scratch_root / "reports"
            private_log_base = scratch_root / "private-logs"
            handoff_dir = scratch_root / "handoff-candidates"
            trust_input_dir = scratch_root / "trust-inputs"
            outer_home = scenario / "outer-home"
            outer_docker_config = scenario / "outer-docker-config"
            outer_tmp = scenario / "outer-tmp"
            inner_home = scenario / "inner-home"
            inner_docker_config = scenario / "inner-docker-config"
            inner_log_dir = scenario / "inner-logs"
            inner_tmp = scenario / "inner-tmp"
            for directory in (
                root,
                scratch_root,
                source_snapshot_root,
                git_metadata_root,
                report_dir,
                private_log_base,
                handoff_dir,
                trust_input_dir,
                outer_home,
                outer_docker_config,
                outer_tmp,
                inner_home,
                inner_docker_config,
                inner_log_dir,
                inner_tmp,
            ):
                directory.mkdir(parents=True, mode=0o700)
            diagnostic = scenario / "operator-postgresql-failure-diagnostic.json"
            runner_diagnostic = scenario / "live-postgresql-failure-diagnostic.json"
            if diagnostic_payload is not None:
                diagnostic.write_text(
                    json.dumps(
                        diagnostic_payload,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
                diagnostic.chmod(0o400)
            call_log = scenario / "docker-calls.log"
            fake_docker = scenario / "docker"
            fake_docker.write_text(
                "\n".join(
                    (
                        "#!/bin/sh",
                        f"printf '%s\\n' \"$1\" >> {shlex.quote(str(call_log))}",
                        f"exit {0 if inner_succeeds else 41}",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            fake_docker.chmod(0o700)
            snapshot_log = scenario / "source-snapshot.log"
            git_snapshot_log = scenario / "git-snapshot.log"
            build_log = scenario / "build.log"
            run_log = scenario / "run.log"
            build_log.write_bytes(b"bounded-build-log")
            harness = scenario / "outer-run-harness.sh"
            harness.write_text(
                "\n".join(
                    (
                        "#!/bin/sh",
                        "set -eu",
                        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                        "export PATH",
                        f"MODE={shlex.quote(mode)}",
                        f"ROOT={shlex.quote(str(root))}",
                        f"SCRATCH_ROOT={shlex.quote(str(scratch_root))}",
                        f"CAMPAIGN_DIR={shlex.quote(str(campaign_dir))}",
                        ("SOURCE_SNAPSHOT_ROOT=" f"{shlex.quote(str(source_snapshot_root))}"),
                        f"GIT_METADATA_ROOT={shlex.quote(str(git_metadata_root))}",
                        f"REPORT_DIR={shlex.quote(str(report_dir))}",
                        f"PRIVATE_LOG_BASE={shlex.quote(str(private_log_base))}",
                        f"HANDOFF_DIR={shlex.quote(str(handoff_dir))}",
                        f"TRUST_INPUT_DIR={shlex.quote(str(trust_input_dir))}",
                        (
                            "CAMPAIGN_PIN="
                            f"{shlex.quote(str(trust_input_dir / 'campaign-source-pin.json'))}"
                        ),
                        f"OUTER_HOME={shlex.quote(str(outer_home))}",
                        ("OUTER_DOCKER_CONFIG=" f"{shlex.quote(str(outer_docker_config))}"),
                        f"OUTER_TMP={shlex.quote(str(outer_tmp))}",
                        f"INNER_HOME={shlex.quote(str(inner_home))}",
                        ("INNER_DOCKER_CONFIG=" f"{shlex.quote(str(inner_docker_config))}"),
                        f"INNER_LOG_DIR={shlex.quote(str(inner_log_dir))}",
                        f"INNER_TMP={shlex.quote(str(inner_tmp))}",
                        f"DOCKER_BIN={shlex.quote(str(fake_docker))}",
                        "DOCKER_HOST=unix:///bounded-test.sock",
                        "COMPOSE_DISABLE_ENV_FILE=1",
                        "SOCKET_GID=0",
                        "CANDIDATE_MOUNT_MODE=ro",
                        "CAMPAIGN_PIN_SHA256=sha256:" + "1" * 64,
                        f"IMAGE_ID={shlex.quote(image_id)}",
                        f"SNAPSHOT_LOG={shlex.quote(str(snapshot_log))}",
                        f"GIT_SNAPSHOT_LOG={shlex.quote(str(git_snapshot_log))}",
                        f"BUILD_LOG={shlex.quote(str(build_log))}",
                        f"RUN_LOG={shlex.quote(str(run_log))}",
                        ("OPERATOR_FAILURE_DIAGNOSTIC=" f"{shlex.quote(str(diagnostic))}"),
                        ("RUNNER_FAILURE_DIAGNOSTIC=" f"{shlex.quote(str(runner_diagnostic))}"),
                        f"HOST_PYTHON_BIN={shlex.quote(sys.executable)}",
                        (
                            "OPERATOR_FAILURE_DIAGNOSTIC_VALIDATION_PROGRAM="
                            f"{shlex.quote(validation_program)}"
                        ),
                        f"RUNNER_UID={os.getuid()}",
                        "set -- /bin/sh /bounded/inner-command",
                        outer_run_block,
                        success_epilogue,
                    )
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                ["/bin/sh", str(harness)],
                cwd=scenario,
                text=True,
                capture_output=True,
                check=False,
            )
            calls = (
                tuple(call_log.read_text(encoding="utf-8").splitlines())
                if call_log.exists()
                else ()
            )
            return result, calls, build_log, run_log

        valid_diagnostic = {
            "artifact_id": (
                "formowl_connected_operator_postgres_live_journey_" "failure_diagnostic_v1"
            ),
            "failure_code": "stage_failed",
            "schema_version": 1,
            "stage": "outer_inner_journey",
            "status": "failed",
        }
        invalid_diagnostic = {
            **valid_diagnostic,
            "stage": "/private/unbounded-stage",
        }

        with tempfile.TemporaryDirectory(prefix="formowl-runner-outer-status-") as temporary:
            temporary_path = Path(temporary)
            success, success_calls, success_build_log, success_run_log = run_outer_block(
                label="success",
                mode="preflight",
                inner_succeeds=True,
            )
            self.assertEqual(success.returncode, 0, success.stderr)
            self.assertEqual(success.stderr, "")
            self.assertEqual(
                json.loads(success.stdout),
                {
                    "artifact_type": ("issue20_containerized_evidence_runner_result_v1"),
                    "docker_authority": "trusted_operator_docker_daemon",
                    "host_docker_socket_delegated": True,
                    "mode": "preflight",
                    "report_validation": "passed",
                    "sandboxed_untrusted_source": False,
                    "status": "passed",
                },
            )
            self.assertEqual(success_calls, ("run",))
            self.assertFalse(success_build_log.exists())
            self.assertFalse(success_run_log.exists())

            failure, failure_calls, _, failure_run_log = run_outer_block(
                label="non-operator-failure",
                mode="preflight",
                inner_succeeds=False,
            )
            self.assertEqual(failure.returncode, 1)
            self.assertEqual(failure.stderr, "")
            self.assertEqual(
                json.loads(failure.stdout),
                {"error": "runner_command_failed", "status": "error"},
            )
            self.assertEqual(failure_calls, ("run",))
            self.assertTrue(failure_run_log.exists())

            live_missing, live_missing_calls, _, live_missing_run_log = run_outer_block(
                label="live-postgresql-missing-diagnostic",
                mode="live-postgresql",
                inner_succeeds=False,
            )
            self.assertEqual(live_missing.returncode, 1)
            self.assertEqual(live_missing.stderr, "")
            self.assertEqual(
                json.loads(live_missing.stdout),
                {"error": "runner_command_failed", "status": "error"},
            )
            self.assertEqual(live_missing_calls, ("run",))
            self.assertTrue(live_missing_run_log.exists())

            operator_failure, operator_calls, _, operator_run_log = run_outer_block(
                label="operator-failure",
                mode="operator",
                inner_succeeds=False,
                diagnostic_payload=valid_diagnostic,
            )
            self.assertEqual(operator_failure.returncode, 1)
            self.assertEqual(operator_failure.stderr, "")
            self.assertEqual(
                json.loads(operator_failure.stdout),
                {
                    "error": "runner_command_failed",
                    "stage": "outer_inner_journey",
                    "status": "error",
                },
            )
            self.assertEqual(operator_calls, ("run",))
            self.assertTrue(operator_run_log.exists())

            invalid_failure, invalid_calls, _, invalid_run_log = run_outer_block(
                label="operator-invalid-diagnostic",
                mode="operator",
                inner_succeeds=False,
                diagnostic_payload=invalid_diagnostic,
            )
            self.assertEqual(invalid_failure.returncode, 1)
            self.assertEqual(invalid_failure.stderr, "")
            self.assertEqual(
                json.loads(invalid_failure.stdout),
                {"error": "runner_command_failed", "status": "error"},
            )
            self.assertNotIn("/private/unbounded-stage", invalid_failure.stdout)
            self.assertEqual(invalid_calls, ("run",))
            self.assertTrue(invalid_run_log.exists())

    def test_live_postgresql_failure_survives_invocation_log_cleanup_as_bounded_diagnostic(
        self,
    ) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        outer_run_start = source.index(
            "if /usr/bin/env -i \\\n",
            source.index("CANDIDATE_MOUNT_MODE=ro"),
        )
        outer_run_end = source.index(
            '\nif [ "$MODE" = "operator" ]; then',
            outer_run_start,
        )
        outer_run_block = source[outer_run_start:outer_run_end]
        image_id = f"sha256:{'0' * 64}"
        diagnostic_payload = {
            "artifact_type": "issue20_runner_failure_diagnostic_v1",
            "failure_code": "report_persist_failed",
            "mode": "live-postgresql",
            "schema_version": 1,
            "stage": "live_postgresql_execution",
            "status": "failed",
        }

        with tempfile.TemporaryDirectory(
            prefix="formowl-runner-live-postgresql-diagnostic-"
        ) as temporary:
            temporary_path = Path(temporary)
            root = temporary_path / "root"
            scripts_dir = root / "scripts"
            scratch_root = temporary_path / "scratch"
            campaign_dir = scratch_root / "campaign"
            source_snapshot_root = campaign_dir / "source-snapshot"
            git_metadata_root = campaign_dir / "git-snapshot" / ".git"
            report_dir = scratch_root / "reports"
            private_log_base = scratch_root / "private-logs"
            handoff_dir = scratch_root / "handoff-candidates"
            trust_input_dir = scratch_root / "trust-inputs"
            invocation_home_root = scratch_root / "home" / "invocation.test"
            invocation_tmp_root = scratch_root / "tmp" / "invocation.test"
            invocation_log_root = private_log_base / "invocation.test"
            outer_home = invocation_home_root / "outer-home"
            outer_docker_config = invocation_home_root / "outer-docker-config"
            outer_tmp = invocation_tmp_root / "outer-tmp"
            inner_home = invocation_home_root / "inner-home"
            inner_docker_config = invocation_home_root / "inner-docker-config"
            inner_log_dir = invocation_log_root / "inner-logs"
            inner_tmp = invocation_tmp_root / "inner-tmp"
            outer_log_dir = invocation_log_root / "outer-logs"
            for directory in (
                scripts_dir,
                source_snapshot_root,
                git_metadata_root,
                report_dir,
                private_log_base,
                handoff_dir,
                trust_input_dir,
                outer_home,
                outer_docker_config,
                outer_tmp,
                inner_home,
                inner_docker_config,
                inner_log_dir,
                inner_tmp,
                outer_log_dir,
            ):
                directory.mkdir(parents=True, mode=0o700)
                directory.chmod(0o700)
            scratch_root.chmod(0o700)
            shutil.copy2(BOUNDARY_HELPER, scripts_dir / BOUNDARY_HELPER.name)
            diagnostic = private_log_base / "live-postgresql-failure-diagnostic.json"
            operator_diagnostic = private_log_base / "operator-postgresql-failure-diagnostic.json"
            run_log = outer_log_dir / "live-postgresql.log"
            fake_docker = temporary_path / "docker"
            fake_docker.write_text(
                "\n".join(
                    (
                        "#!/bin/sh",
                        f"printf '%s' {shlex.quote(json.dumps(diagnostic_payload, separators=(',', ':'), sort_keys=True))} > {shlex.quote(str(diagnostic))}",
                        f"chmod 400 {shlex.quote(str(diagnostic))}",
                        "printf '%s\\n' 'private-inner-command --dsn secret' ",
                        "exit 41",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            fake_docker.chmod(0o700)
            harness = temporary_path / "outer-run-harness.sh"
            harness.write_text(
                "\n".join(
                    (
                        "#!/bin/sh",
                        "set -eu",
                        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                        "export PATH",
                        "MODE=live-postgresql",
                        f"ROOT={shlex.quote(str(root))}",
                        f"SCRATCH_ROOT={shlex.quote(str(scratch_root))}",
                        f"CAMPAIGN_DIR={shlex.quote(str(campaign_dir))}",
                        ("SOURCE_SNAPSHOT_ROOT=" f"{shlex.quote(str(source_snapshot_root))}"),
                        f"GIT_METADATA_ROOT={shlex.quote(str(git_metadata_root))}",
                        f"REPORT_DIR={shlex.quote(str(report_dir))}",
                        f"PRIVATE_LOG_BASE={shlex.quote(str(private_log_base))}",
                        f"HANDOFF_DIR={shlex.quote(str(handoff_dir))}",
                        f"TRUST_INPUT_DIR={shlex.quote(str(trust_input_dir))}",
                        (
                            "CAMPAIGN_PIN="
                            f"{shlex.quote(str(trust_input_dir / 'campaign-source-pin.json'))}"
                        ),
                        f"INVOCATION_HOME_ROOT={shlex.quote(str(invocation_home_root))}",
                        f"INVOCATION_TMP_ROOT={shlex.quote(str(invocation_tmp_root))}",
                        f"INVOCATION_LOG_ROOT={shlex.quote(str(invocation_log_root))}",
                        "CAMPAIGN_INITIALIZING=0",
                        (
                            'trap \'[ -z "$INVOCATION_HOME_ROOT" ] || '
                            '/bin/rm -rf -- "$INVOCATION_HOME_ROOT"; '
                            '[ -z "$INVOCATION_TMP_ROOT" ] || '
                            '/bin/rm -rf -- "$INVOCATION_TMP_ROOT"; '
                            '[ -z "$INVOCATION_LOG_ROOT" ] || '
                            '/bin/rm -rf -- "$INVOCATION_LOG_ROOT"\' EXIT HUP INT TERM'
                        ),
                        f"OUTER_HOME={shlex.quote(str(outer_home))}",
                        ("OUTER_DOCKER_CONFIG=" f"{shlex.quote(str(outer_docker_config))}"),
                        f"OUTER_TMP={shlex.quote(str(outer_tmp))}",
                        f"INNER_HOME={shlex.quote(str(inner_home))}",
                        ("INNER_DOCKER_CONFIG=" f"{shlex.quote(str(inner_docker_config))}"),
                        f"INNER_LOG_DIR={shlex.quote(str(inner_log_dir))}",
                        f"INNER_TMP={shlex.quote(str(inner_tmp))}",
                        f"DOCKER_BIN={shlex.quote(str(fake_docker))}",
                        "DOCKER_HOST=unix:///bounded-test.sock",
                        "COMPOSE_DISABLE_ENV_FILE=1",
                        "SOCKET_GID=0",
                        "CANDIDATE_MOUNT_MODE=ro",
                        "CAMPAIGN_PIN_SHA256=sha256:" + "1" * 64,
                        f"IMAGE_ID={shlex.quote(image_id)}",
                        f"SNAPSHOT_LOG={shlex.quote(str(outer_log_dir / 'snapshot.log'))}",
                        (
                            "GIT_SNAPSHOT_LOG="
                            f"{shlex.quote(str(outer_log_dir / 'git-snapshot.log'))}"
                        ),
                        f"BUILD_LOG={shlex.quote(str(outer_log_dir / 'build.log'))}",
                        f"RUN_LOG={shlex.quote(str(run_log))}",
                        ("OPERATOR_FAILURE_DIAGNOSTIC=" f"{shlex.quote(str(operator_diagnostic))}"),
                        ("RUNNER_FAILURE_DIAGNOSTIC=" f"{shlex.quote(str(diagnostic))}"),
                        f"HOST_PYTHON_BIN={shlex.quote(sys.executable)}",
                        f"RUNNER_UID={os.getuid()}",
                        "set -- /bin/sh /bounded/inner-command",
                        outer_run_block,
                    )
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                ["/bin/sh", str(harness)],
                cwd=temporary_path,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stderr, "")
            self.assertEqual(
                json.loads(result.stdout),
                {
                    "error": "runner_command_failed",
                    "failure_code": "report_persist_failed",
                    "stage": "live_postgresql_execution",
                    "status": "error",
                },
            )
            self.assertNotIn("private-inner-command", result.stdout)
            self.assertNotIn("secret", result.stdout)
            self.assertFalse(diagnostic.exists())
            self.assertFalse(invocation_log_root.exists())
            self.assertFalse(run_log.exists())

    def test_runner_builds_and_runs_only_the_captured_immutable_image_id(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        boundary_source = BOUNDARY_HELPER.read_text(encoding="utf-8")

        self.assertIn('--iidfile "$IMAGE_ID_FILE"', source)
        self.assertIn("'^sha256:[0-9a-f]{64}$'", source)
        self.assertIn('--env "FORMOWL_RUNNER_IMAGE_ID=$IMAGE_ID"', source)
        self.assertIn('        "$FORMOWL_RUNNER_IMAGE_ID" \\', source)
        self.assertIn('    "$IMAGE_ID" \\', source)
        self.assertEqual(source.count("formowl-dev:local"), 1)
        self.assertIn('os.environ.get("FORMOWL_RUNNER_IMAGE_ID") == image_id', boundary_source)
        self.assertIn("_IMAGE_ID_RE.fullmatch(image_id) is not None", boundary_source)
        lock_index = source.index('issue20_runner_boundary.py" lock-and-exec')
        build_index = source.index('    "$DOCKER_BIN" build \\')
        outer_run_index = source.index('    "$DOCKER_BIN" run --rm \\')
        self.assertLess(lock_index, build_index)
        self.assertLess(build_index, outer_run_index)
        self.assertNotIn("9>&-", source)
        self.assertNotIn('exec 9<> "$LOCK_PATH"', source)
        self.assertNotIn("invocation.lock", boundary_source)
        self.assertIn("socket.AF_UNIX", boundary_source)
        self.assertIn("EADDRINUSE", boundary_source)

    def test_each_evidence_mode_validates_current_reports_before_success(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")

        self.assertGreaterEqual(source.count("--validate-report"), 7)
        self.assertIn("operator-postgresql-validation.json", source)
        self.assertIn("operator-cli-postgresql-external-layer.json", source)
        self.assertIn("--operator-cli-postgresql-report", source)
        self.assertIn("live-postgresql-validation.json", source)
        self.assertIn("production-lifecycle-a-validation.json", source)
        self.assertIn("production-lifecycle-b-validation.json", source)
        self.assertIn("local-oauth-harness-validation.json", source)
        self.assertIn("--aggregate-lifecycle-reports", source)
        self.assertIn("production-lifecycle-external-layer.json", source)
        self.assertIn('get("status") == "passed"', source)
        self.assertIn('get("passed") is True', source)
        self.assertIn('if [ "$HASH_A" = "$HASH_B" ]', source)
        self.assertIn('"report_validation":"passed"', source)

    def test_live_postgresql_validator_program_matches_current_cli_schema(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        match = re.search(
            r"^LIVE_POSTGRESQL_VALIDATION_PROGRAM='([^']+)'$",
            source,
            flags=re.MULTILINE,
        )
        self.assertIsNotNone(match)
        program = match.group(1)

        with tempfile.TemporaryDirectory(prefix="formowl-runner-schema-") as temporary:
            current = Path(temporary) / "current.json"
            legacy = Path(temporary) / "legacy.json"
            blocked = Path(temporary) / "blocked.json"
            current.write_text(
                json.dumps(
                    {
                        "artifact_id": "formowl_connected_runtime_postgres_live_e2e_v1",
                        "blocker_count": 0,
                        "status": "passed",
                    }
                ),
                encoding="utf-8",
            )
            legacy.write_text(json.dumps({"passed": True}), encoding="utf-8")
            blocked.write_text(
                json.dumps(
                    {
                        "artifact_id": "formowl_connected_runtime_postgres_live_e2e_v1",
                        "blocker_count": 1,
                        "status": "passed",
                    }
                ),
                encoding="utf-8",
            )

            results = {
                name: subprocess.run(
                    [sys.executable, "-c", program, str(path)],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                for name, path in {
                    "current": current,
                    "legacy": legacy,
                    "blocked": blocked,
                }.items()
            }

        self.assertEqual(results["current"].returncode, 0)
        self.assertNotEqual(results["legacy"].returncode, 0)
        self.assertNotEqual(results["blocked"].returncode, 0)

    def test_private_inner_modes_require_outer_kernel_boundary_before_artifacts(
        self,
    ) -> None:
        scratch_root = Path(f"/tmp/formowl-issue20-containerized-evidence-runner-{os.getuid()}")

        def scratch_snapshot() -> dict[str, tuple[int, int]]:
            if not scratch_root.exists():
                return {}
            return {
                str(path.relative_to(scratch_root)): (
                    path.stat().st_size,
                    path.stat().st_mtime_ns,
                )
                for path in scratch_root.rglob("*")
                if path.is_file()
            }

        before = scratch_snapshot()
        with tempfile.TemporaryDirectory(prefix="formowl-runner-direct-") as temporary:
            foreign_root = Path(temporary) / "foreign"
            bin_dir = Path(temporary) / "bin"
            marker = Path(temporary) / "fake-python-invoked"
            foreign_root.mkdir()
            bin_dir.mkdir()
            fake_python = bin_dir / "python"
            fake_python.write_text(
                f"#!/bin/sh\nprintf '%s\\n' invoked > {marker}\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            environment = {
                **os.environ,
                "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                "DOCKER_HOST": "unix:///tmp/forged.sock",
                "FORMOWL_RUNNER_INNER": "forged",
            }
            commands = (
                ["/bin/sh", str(RUNNER), "__inside-runner", "live-postgresql"],
                ["/bin/sh", str(RUNNER), "__inside-preflight"],
            )
            for command in commands:
                with self.subTest(command=command[-1]):
                    result = subprocess.run(
                        command,
                        cwd=foreign_root,
                        env=environment,
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stderr, "")
                    self.assertEqual(
                        json.loads(result.stdout),
                        {
                            "error": "runner_inner_boundary_unverified",
                            "status": "error",
                        },
                    )
                    self.assertFalse(marker.exists())
                    self.assertEqual(scratch_snapshot(), before)

    def test_runner_scratch_is_ignored_and_private(self) -> None:
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        source = RUNNER.read_text(encoding="utf-8")

        self.assertIn(".test-tmp/", gitignore)
        self.assertIn("umask 077", source)
        self.assertIn(
            'SCRATCH_ROOT="/tmp/formowl-issue20-containerized-evidence-runner-$RUNNER_UID"',
            source,
        )
        self.assertIn('SCRATCH_CANONICAL=$(/usr/bin/readlink -f "$SCRATCH_ROOT")', source)
        self.assertIn("runner_scratch_unavailable", source)
        self.assertIn("/usr/bin/mkdir -m 700", source)
        self.assertIn('chmod 700 "$SCRATCH_ROOT"', source)
        self.assertIn("CAMPAIGN_INITIALIZING=0", source)
        self.assertIn(
            '/bin/rm -rf -- "$SOURCE_SNAPSHOT_ROOT" "$GIT_SNAPSHOT_ROOT"',
            source,
        )
        self.assertIn('/bin/rm -f -- "$CAMPAIGN_PIN"', source)

    def test_non_preflight_mode_without_campaign_pin_fails_stale_closed(self) -> None:
        runner_source = RUNNER.read_text(encoding="utf-8")
        helper_source = BOUNDARY_HELPER.read_text(encoding="utf-8")
        scratch_assignment = (
            'SCRATCH_ROOT="/tmp/formowl-issue20-containerized-evidence-runner-$RUNNER_UID"'
        )
        docker_owner_check = '[ "$(/usr/bin/stat -c \'%u\' "$DOCKER_RESOLVED")" != "0" ]'
        with (
            tempfile.TemporaryDirectory(prefix="formowl-runner-stale-mode-") as temporary,
            tempfile.TemporaryDirectory(prefix="f20-stale-sock-", dir="/tmp") as socket_dir,
        ):
            temporary_path = Path(temporary)
            root = temporary_path / "root"
            scripts_dir = root / "scripts"
            dockerfile = root / "containers" / "dev" / "Dockerfile"
            scratch_root = temporary_path / "scratch"
            fake_docker = temporary_path / "docker"
            docker_marker = temporary_path / "docker-called"
            socket_path = Path(socket_dir) / "docker.sock"
            scripts_dir.mkdir(parents=True)
            dockerfile.parent.mkdir(parents=True)
            fake_docker.write_text(
                f"#!/bin/sh\nprintf called > {shlex.quote(str(docker_marker))}\nexit 99\n",
                encoding="utf-8",
            )
            fake_docker.chmod(0o755)
            script = scripts_dir / RUNNER.name
            script.write_text(
                runner_source.replace(
                    scratch_assignment,
                    f'SCRATCH_ROOT="{scratch_root}"',
                    1,
                )
                .replace(
                    "DOCKER_BIN=/usr/bin/docker",
                    f"DOCKER_BIN={shlex.quote(str(fake_docker))}",
                    1,
                )
                .replace(
                    "HOST_PYTHON_BIN=/usr/bin/python3",
                    "HOST_PYTHON_BIN=/usr/local/bin/python",
                    1,
                )
                .replace(
                    docker_owner_check,
                    ('[ "$(/usr/bin/stat -c \'%u\' "$DOCKER_RESOLVED")" ' '!= "$RUNNER_UID" ]'),
                    1,
                )
                .replace("/var/run/docker.sock", str(socket_path)),
                encoding="utf-8",
            )
            script.chmod(0o700)
            (scripts_dir / BOUNDARY_HELPER.name).write_text(
                helper_source,
                encoding="utf-8",
            )
            dockerfile.write_text("FROM scratch\n", encoding="utf-8")

            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as socket_handle:
                socket_handle.bind(str(socket_path))
                result = subprocess.run(
                    ["/bin/sh", str(script), "operator-layer"],
                    cwd=root,
                    text=True,
                    capture_output=True,
                    timeout=5,
                    check=False,
                )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        self.assertEqual(
            json.loads(result.stdout),
            {"error": "runner_campaign_required", "status": "error"},
        )
        self.assertFalse(docker_marker.exists())

    def test_invalid_mode_fails_with_bounded_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="formowl-runner-cwd-") as temporary:
            result = subprocess.run(
                ["sh", str(RUNNER), "not-a-runner-mode"],
                cwd=temporary,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 64)
        self.assertEqual(result.stderr, "")
        self.assertEqual(
            json.loads(result.stdout),
            {"error": "runner_mode_invalid", "status": "error"},
        )
        self.assertNotIn(str(ROOT), result.stdout)
        self.assertNotIn("/var/run/docker.sock", result.stdout)

    def test_public_status_lines_do_not_render_private_paths_or_socket_location(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        public_lines = [line for line in source.splitlines() if "printf" in line]

        self.assertTrue(public_lines)
        for line in public_lines:
            self.assertNotIn(str(ROOT), line)
            self.assertNotIn("$ROOT", line)
            self.assertNotIn(".test-tmp", line)
            self.assertNotIn("/var/run/docker.sock", line)

    def test_shell_contract_parses(self) -> None:
        result = subprocess.run(
            ["sh", "-n", str(RUNNER)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
