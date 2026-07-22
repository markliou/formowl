#!/usr/bin/env python3
"""Run the production entrypoint flow for the capability bounding-set A/B probe."""

from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterator, Sequence


_ARMS = ("pre_fix_control", "post_fix")
_CAPABILITY_FIELDS = ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")
_HEX_VALUE = re.compile(r"[0-9A-Fa-f]+\Z")


class CapabilityProbeError(RuntimeError):
    """Fixed test-only failure without repository or runtime internals."""


class _NoopBoundingSetLibc:
    def __init__(self, delegate: Any, *, bounding_drop_operation: int) -> None:
        self._delegate = delegate
        self._bounding_drop_operation = bounding_drop_operation
        self.bounding_drop_calls: list[int] = []

    def prctl(self, operation: int, argument: int, *remaining: int) -> int:
        if operation == self._bounding_drop_operation:
            self.bounding_drop_calls.append(argument)
            return 0
        return int(self._delegate.prctl(operation, argument, *remaining))


@contextmanager
def pre_fix_bounding_drop_control(entrypoint_module: Any) -> Iterator[_NoopBoundingSetLibc]:
    """Make only PR_CAPBSET_DROP a no-op for the test-only pre-fix arm."""

    original_factory = entrypoint_module.ctypes.CDLL
    delegate = original_factory(None, use_errno=True)
    controlled = _NoopBoundingSetLibc(
        delegate,
        bounding_drop_operation=entrypoint_module._PR_CAPBSET_DROP,
    )

    def controlled_factory(name: object, *args: object, **kwargs: object) -> Any:
        if name is None and not args and kwargs == {"use_errno": True}:
            return controlled
        return original_factory(name, *args, **kwargs)

    entrypoint_module.ctypes.CDLL = controlled_factory
    try:
        yield controlled
    finally:
        entrypoint_module.ctypes.CDLL = original_factory


def _process_status() -> dict[str, str]:
    try:
        lines = Path("/proc/self/status").read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise CapabilityProbeError("capability_probe_failed") from error
    return {
        key.strip(): value.strip()
        for line in lines
        if ":" in line
        for key, value in (line.split(":", 1),)
        if key.strip()
    }


def _report(*, arm: str, launcher_pid: int) -> dict[str, object]:
    status = _process_status()
    capability_sets = {field: status.get(field, "") for field in _CAPABILITY_FIELDS}
    if (
        os.getpid() != launcher_pid
        or any(_HEX_VALUE.fullmatch(value) is None for value in capability_sets.values())
        or status.get("NoNewPrivs") not in {"0", "1"}
    ):
        raise CapabilityProbeError("capability_probe_failed")
    return {
        "arm": arm,
        "artifact_type": "issue20_capability_bounding_set_probe_v1",
        "capability_sets": capability_sets,
        "entrypoint_main_exercised": True,
        "gid": os.getegid(),
        "no_new_privs": int(status["NoNewPrivs"]),
        "status": "passed",
        "supplementary_group_count": len(os.getgroups()),
        "uid": os.geteuid(),
    }


def _launch(*, arm: str, repository_root: Path) -> int:
    import formowl_gateway.container_entrypoint as entrypoint

    try:
        canonical_root = repository_root.resolve(strict=True)
        installed_entrypoint = Path(entrypoint.__file__).resolve(strict=True)
        helper_path = Path(__file__).resolve(strict=True)
    except OSError as error:
        raise CapabilityProbeError("capability_probe_failed") from error
    if (
        os.geteuid() != 0
        or installed_entrypoint.is_relative_to(canonical_root)
        or helper_path != canonical_root / "tests" / Path(__file__).name
    ):
        raise CapabilityProbeError("capability_probe_failed")

    production_drop_privileges = entrypoint._drop_privileges

    def measured_drop_privileges() -> None:
        try:
            production_drop_privileges()
        except entrypoint.ContainerEntrypointError as error:
            if arm == "pre_fix_control" and error.code == "container_privilege_drop_unverified":
                return
            raise
        if arm == "pre_fix_control":
            raise CapabilityProbeError("capability_probe_failed")

    entrypoint._drop_privileges = measured_drop_privileges
    control = (
        pre_fix_bounding_drop_control(entrypoint) if arm == "pre_fix_control" else nullcontext()
    )
    command = [
        sys.executable,
        str(helper_path),
        "--phase",
        "report",
        "--repository-root",
        str(canonical_root),
        "--launcher-pid",
        str(os.getpid()),
        "--arm",
        arm,
    ]
    with control:
        return entrypoint.main(command)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=_ARMS, required=True)
    parser.add_argument("--phase", choices=("launch", "report"), required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--launcher-pid", type=int)
    args = parser.parse_args(argv)
    try:
        if args.phase == "launch":
            if args.launcher_pid is not None:
                raise CapabilityProbeError("capability_probe_failed")
            return _launch(arm=args.arm, repository_root=args.repository_root)
        if args.launcher_pid is None or args.launcher_pid <= 0:
            raise CapabilityProbeError("capability_probe_failed")
        report = _report(arm=args.arm, launcher_pid=args.launcher_pid)
    except (CapabilityProbeError, OSError, TypeError, ValueError):
        print(
            '{"error":"capability_probe_failed","status":"error"}',
            file=sys.stderr,
        )
        return 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
