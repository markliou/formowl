from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_SIZE_BYTES = 1024 * 1024

SKIP_DIRS = {
    ".git",
    ".formowl",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".test-tmp",
    "__pycache__",
    "dist",
    "node_modules",
    "target",
}

BINARY_EXTENSIONS = {
    ".bmp",
    ".dll",
    ".exe",
    ".gif",
    ".ico",
    ".jpg",
    ".jpeg",
    ".pdf",
    ".png",
    ".pyc",
    ".so",
    ".webp",
    ".zip",
}

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private key block", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\b(?:A3T[A-Z0-9]|AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{36,}\b")),
    ("GitLab token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("OpenAI API key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("Stripe live secret key", re.compile(r"\bsk_live_[A-Za-z0-9]{24,}\b")),
)

GENERIC_SECRET_ASSIGNMENT = re.compile(
    r"""(?ix)
    \b(password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|private[_-]?key)\b
    \s*[:=]\s*
    (?P<quote>["'])?
    (?P<value>[^\s"',}]{12,})
    (?P=quote)?
    """
)

PLACEHOLDER_MARKERS = (
    "changeme",
    "dummy",
    "example",
    "fake",
    "placeholder",
    "sample",
    "test",
    "todo",
    "your_",
)


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: precommit_checks.py <command> [args...]", file=sys.stderr)
        return 2

    command = sys.argv[1]
    args = sys.argv[2:]
    commands: dict[str, Callable[[list[str]], int]] = {
        "conflicts": check_conflicts,
        "credentials": check_credentials,
        "json-syntax": check_json_syntax,
        "large-files": check_large_files,
        "python-syntax": check_python_syntax,
        "run": run_external,
        "text-style": check_text_style,
        "toml-syntax": check_toml_syntax,
    }

    handler = commands.get(command)
    if handler is None:
        print(f"Unknown pre-commit command: {command}", file=sys.stderr)
        return 2
    return handler(args)


def iter_paths(args: list[str]) -> list[Path]:
    paths: list[Path] = []
    for arg in args:
        path = (ROOT / arg).resolve() if not Path(arg).is_absolute() else Path(arg)
        try:
            relative_parts = path.relative_to(ROOT).parts
        except ValueError:
            continue
        if any(part in SKIP_DIRS for part in relative_parts):
            continue
        if not path.exists() or not path.is_file():
            continue
        paths.append(path)
    return paths


def display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def read_text(path: Path) -> str | None:
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return None

    data = path.read_bytes()
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def check_large_files(args: list[str]) -> int:
    failed = False
    for path in iter_paths(args):
        size = path.stat().st_size
        if size > MAX_FILE_SIZE_BYTES:
            print(f"{display_path(path)}: file is {size // 1024} KiB; limit is 1024 KiB")
            failed = True
    return 1 if failed else 0


def check_conflicts(args: list[str]) -> int:
    failed = False
    markers = ("<<<<<<< ", "=======\n", ">>>>>>> ")
    for path in iter_paths(args):
        text = read_text(path)
        if text is None:
            continue
        for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
            if any(line.startswith(marker) for marker in markers):
                print(f"{display_path(path)}:{line_number}: merge conflict marker")
                failed = True
    return 1 if failed else 0


def check_text_style(args: list[str]) -> int:
    failed = False
    for path in iter_paths(args):
        text = read_text(path)
        if text is None or not text:
            continue

        if not text.endswith(("\n", "\r\n")):
            print(f"{display_path(path)}: missing final newline")
            failed = True

        for line_number, line in enumerate(text.splitlines(), start=1):
            if line.rstrip(" \t") != line:
                print(f"{display_path(path)}:{line_number}: trailing whitespace")
                failed = True
    return 1 if failed else 0


def check_credentials(args: list[str]) -> int:
    failed = False
    for path in iter_paths(args):
        text = read_text(path)
        if text is None:
            continue

        for label, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(text):
                line_number = text.count("\n", 0, match.start()) + 1
                print(f"{display_path(path)}:{line_number}: possible credential ({label})")
                failed = True

        for match in GENERIC_SECRET_ASSIGNMENT.finditer(text):
            value = match.group("value").strip()
            if looks_like_placeholder(value):
                continue
            line_number = text.count("\n", 0, match.start()) + 1
            key_name = match.group(1)
            print(
                f"{display_path(path)}:{line_number}: possible credential assignment ({key_name})"
            )
            failed = True
    return 1 if failed else 0


def looks_like_placeholder(value: str) -> bool:
    lowered = value.lower()
    if lowered.startswith(("${", "<", "env.", "process.env.")):
        return True
    if lowered.endswith(("}", ">")):
        return True
    if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
        return True
    if set(value) <= {"*", "x", "X", "."}:
        return True
    return False


def check_python_syntax(args: list[str]) -> int:
    failed = False
    for path in iter_paths(args):
        if path.suffix != ".py":
            continue
        source = path.read_text(encoding="utf-8")
        try:
            compile(source, str(path), "exec")
        except SyntaxError as exc:
            print(f"{display_path(path)}:{exc.lineno}: Python syntax error: {exc.msg}")
            failed = True
    return 1 if failed else 0


def check_json_syntax(args: list[str]) -> int:
    failed = False
    for path in iter_paths(args):
        if path.suffix != ".json":
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"{display_path(path)}:{exc.lineno}: JSON syntax error: {exc.msg}")
            failed = True
    return 1 if failed else 0


def check_toml_syntax(args: list[str]) -> int:
    failed = False
    for path in iter_paths(args):
        if path.suffix != ".toml":
            continue
        try:
            tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            print(f"{display_path(path)}: TOML syntax error: {exc}")
            failed = True
    return 1 if failed else 0


def run_external(args: list[str]) -> int:
    if not args:
        print("No external command provided", file=sys.stderr)
        return 2

    executable = resolve_executable(args[0])
    if executable is None:
        print(
            f"Required tool '{args[0]}' was not found. Install it or run this hook in the devcontainer.",
            file=sys.stderr,
        )
        return 1

    completed = subprocess.run([executable, *args[1:]], cwd=ROOT, check=False)
    return completed.returncode


def resolve_executable(command: str) -> str | None:
    if os.path.dirname(command):
        return command

    candidates = [command]
    if os.name == "nt":
        candidates = [f"{command}.cmd", f"{command}.exe", f"{command}.bat", command]

    local_node_bin = ROOT / "node_modules" / ".bin"
    local_candidates = [str(local_node_bin / candidate) for candidate in candidates]
    for candidate in local_candidates:
        if Path(candidate).exists():
            return candidate

    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved is not None:
            return resolved
    return None


if __name__ == "__main__":
    raise SystemExit(main())
