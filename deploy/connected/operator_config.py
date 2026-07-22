"""Create safe connected-deployment configuration without printing secrets."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
from typing import Sequence
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


PINNED_POSTGRES_IMAGE = (
    "pgvector/pgvector@sha256:" "131dcf7ff6a900545df8e7e092c270aa8c6db2f2c818e408cb45ec21316b74e6"
)
DISCOVERY_SENTINEL = "https://invalid.example.invalid/formowl-discovery-only"
LEGACY_DISCOVERY_CLIENT_ID = "formowl-discovery-only"
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_PUBLIC_HOST = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_PROJECT_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{2,62}$")
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_CHATGPT_CALLBACK = re.compile(r"^https://chatgpt\.com/connector/oauth/[A-Za-z0-9._~-]+$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SECRET_MAX_BYTES = 64 * 1024
_ZERO_IMAGE_ID = f"sha256:{'0' * 64}"
_RESERVED_PUBLIC_SUFFIXES = (".example", ".invalid", ".localhost", ".test")
_PLACEHOLDER_VALUES = {
    "formowl-chatgpt-replace-with-deployment-id",
    "formowl-chatgpt-client-id-pending-app-management",
    "formowl-issue20-replace-with-unique-campaign",
    "replace-with-google-web-client-id",
    "replace-with-operator-service-id",
}


class OperatorConfigError(RuntimeError):
    """Bounded operator configuration failure."""


def _require_text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\n" in value:
        raise OperatorConfigError(f"{label}_invalid")
    return value


def _require_image_id(value: str, label: str) -> str:
    value = _require_text(value, label)
    if _IMAGE_ID.fullmatch(value) is None or value == _ZERO_IMAGE_ID:
        raise OperatorConfigError(f"{label}_invalid")
    return value


def _require_public_host(value: str) -> str:
    value = _require_text(value, "public_host")
    if value != value.lower() or _PUBLIC_HOST.fullmatch(value) is None:
        raise OperatorConfigError("public_host_invalid")
    if value.endswith(_RESERVED_PUBLIC_SUFFIXES):
        raise OperatorConfigError("public_host_invalid")
    return value


def _require_identifier(value: str, label: str) -> str:
    value = _require_text(value, label)
    if _SAFE_IDENTIFIER.fullmatch(value) is None:
        raise OperatorConfigError(f"{label}_invalid")
    return value


def _require_chatgpt_client_id(value: str) -> str:
    value = _require_identifier(value, "chatgpt_client_id")
    if value == LEGACY_DISCOVERY_CLIENT_ID or value in _PLACEHOLDER_VALUES:
        raise OperatorConfigError("chatgpt_client_id_invalid")
    return value


def _require_callback(value: str) -> str:
    value = _require_text(value, "chatgpt_redirect_uri")
    if value != DISCOVERY_SENTINEL and _CHATGPT_CALLBACK.fullmatch(value) is None:
        raise OperatorConfigError("chatgpt_redirect_uri_invalid")
    return value


def _require_google_redirect_uri(value: str) -> str:
    value = _require_text(value, "google_redirect_uri")
    prefix = "https://"
    suffix = "/oauth/google/callback"
    if not value.startswith(prefix) or not value.endswith(suffix):
        raise OperatorConfigError("google_redirect_uri_invalid")
    host = value[len(prefix) : -len(suffix)]
    if value != f"{prefix}{_require_public_host(host)}{suffix}":
        raise OperatorConfigError("google_redirect_uri_invalid")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise OperatorConfigError("google_credential_json_invalid")
        value[key] = item
    return value


def _read_json_file(path: Path) -> dict[str, object]:
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or metadata.st_size < 2
            or metadata.st_size > _SECRET_MAX_BYTES
        ):
            raise OperatorConfigError("google_credential_json_invalid")
        payload = b""
        while len(payload) <= _SECRET_MAX_BYTES:
            chunk = os.read(descriptor, _SECRET_MAX_BYTES + 1 - len(payload))
            if not chunk:
                break
            payload += chunk
        if len(payload) != metadata.st_size:
            raise OperatorConfigError("google_credential_json_invalid")
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_unique_object,
        )
    except OperatorConfigError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise OperatorConfigError("google_credential_json_invalid") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if type(value) is not dict:
        raise OperatorConfigError("google_credential_json_invalid")
    return value


def _write_exclusive(path: Path, payload: bytes, *, mode: int) -> None:
    descriptor: int | None = None
    try:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, mode)
        os.fchmod(descriptor, mode)
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("write made no progress")
            offset += written
        os.fsync(descriptor)
    except FileExistsError:
        raise OperatorConfigError("output_already_exists") from None
    except OperatorConfigError:
        raise
    except OSError:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
            descriptor = None
        try:
            path.unlink()
        except OSError:
            pass
        raise OperatorConfigError("output_write_failed") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _write_replace(path: Path, payload: bytes, *, mode: int) -> None:
    try:
        metadata = os.lstat(path)
    except OSError:
        raise OperatorConfigError("replace_target_invalid") from None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != mode
    ):
        raise OperatorConfigError("replace_target_invalid")
    temporary = path.with_name(f".{path.name}.replace-{os.getpid()}")
    _write_exclusive(temporary, payload, mode=mode)
    try:
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise OperatorConfigError("output_write_failed") from None


def _compose_environment(args: argparse.Namespace) -> bytes:
    project_name = _require_text(args.project_name, "project_name")
    if _PROJECT_NAME.fullmatch(project_name) is None or project_name in _PLACEHOLDER_VALUES:
        raise OperatorConfigError("project_name_invalid")
    runtime_image = _require_image_id(args.runtime_image, "runtime_image")
    tls_proxy_image = _require_image_id(args.tls_proxy_image, "tls_proxy_image")
    public_host = _require_public_host(args.public_host)
    acme_email = _require_text(args.acme_email, "acme_email")
    if _EMAIL.fullmatch(acme_email) is None or acme_email.lower().endswith(
        _RESERVED_PUBLIC_SUFFIXES
    ):
        raise OperatorConfigError("acme_email_invalid")
    chatgpt_client_id = _require_chatgpt_client_id(args.chatgpt_client_id)
    chatgpt_redirect_uri = _require_callback(args.chatgpt_redirect_uri)
    google_client_id = _require_identifier(args.google_client_id, "google_client_id")
    if google_client_id in _PLACEHOLDER_VALUES:
        raise OperatorConfigError("google_client_id_invalid")
    operator_id = _require_identifier(
        args.owner_bootstrap_operator_service_id,
        "owner_bootstrap_operator_service_id",
    )
    if operator_id in _PLACEHOLDER_VALUES:
        raise OperatorConfigError("owner_bootstrap_operator_service_id_invalid")
    issuer = f"https://{public_host}"
    values = (
        ("COMPOSE_PROJECT_NAME", project_name),
        ("FORMOWL_RUNTIME_IMAGE", runtime_image),
        ("FORMOWL_POSTGRES_IMAGE", PINNED_POSTGRES_IMAGE),
        ("FORMOWL_TLS_PROXY_IMAGE", tls_proxy_image),
        ("FORMOWL_PUBLIC_HOST", public_host),
        ("FORMOWL_ACME_EMAIL", acme_email),
        ("FORMOWL_OAUTH_ISSUER", issuer),
        ("FORMOWL_MCP_RESOURCE", f"{issuer}/mcp"),
        ("FORMOWL_CHATGPT_CLIENT_ID", chatgpt_client_id),
        ("FORMOWL_CHATGPT_REDIRECT_URI", chatgpt_redirect_uri),
        ("FORMOWL_GOOGLE_CLIENT_ID", google_client_id),
        ("FORMOWL_GOOGLE_REDIRECT_URI", f"{issuer}/oauth/google/callback"),
        ("FORMOWL_OWNER_BOOTSTRAP_OPERATOR_SERVICE_ID", operator_id),
        ("FORMOWL_CONNECTED_PUBLISH_PORT", "8000"),
        ("FORMOWL_UPLOAD_SESSION_LIFETIME_SECONDS", "3600"),
        ("FORMOWL_LOG_LEVEL", "info"),
        (
            "FORMOWL_POSTGRES_PASSWORD_FILE",
            "./deploy/connected/secrets/postgres-password",
        ),
        ("FORMOWL_DATABASE_DSN_FILE", "./deploy/connected/secrets/database-dsn"),
        (
            "FORMOWL_GOOGLE_CLIENT_SECRET_FILE",
            "./deploy/connected/secrets/google-client-secret",
        ),
        (
            "FORMOWL_STATE_ENCRYPTION_KEY_FILE",
            "./deploy/connected/secrets/state-encryption-key",
        ),
        (
            "FORMOWL_SIGNING_KEY_SET_FILE",
            "./deploy/connected/secrets/signing-key-set.json",
        ),
        (
            "FORMOWL_SIGNING_KEY_CURRENT_FILE",
            "./deploy/connected/secrets/signing-current.pem",
        ),
        (
            "FORMOWL_SIGNING_KEY_PREVIOUS_FILE",
            "./deploy/connected/secrets/signing-previous.pem",
        ),
    )
    return ("".join(f"{key}={value}\n" for key, value in values)).encode("utf-8")


def _write_compose_env(args: argparse.Namespace) -> None:
    payload = _compose_environment(args)
    if args.replace:
        _write_replace(args.output, payload, mode=0o600)
    else:
        _write_exclusive(args.output, payload, mode=0o600)


def _import_google_secret(args: argparse.Namespace) -> None:
    expected_client_id = _require_identifier(args.expected_client_id, "google_client_id")
    if expected_client_id in _PLACEHOLDER_VALUES:
        raise OperatorConfigError("google_client_id_invalid")
    expected_redirect_uri = _require_google_redirect_uri(args.expected_redirect_uri)
    credential = _read_json_file(args.credential_json)
    web = credential.get("web")
    if type(web) is not dict:
        raise OperatorConfigError("google_credential_web_client_required")
    client_id = web.get("client_id")
    client_secret = web.get("client_secret")
    redirect_uris = web.get("redirect_uris")
    if client_id != expected_client_id:
        raise OperatorConfigError("google_client_id_mismatch")
    if (
        not isinstance(redirect_uris, list)
        or expected_redirect_uri not in redirect_uris
        or any(not isinstance(item, str) for item in redirect_uris)
    ):
        raise OperatorConfigError("google_redirect_uri_mismatch")
    if (
        not isinstance(client_secret, str)
        or not client_secret
        or "\x00" in client_secret
        or "\n" in client_secret
        or len(client_secret.encode("utf-8")) > 4096
    ):
        raise OperatorConfigError("google_client_secret_invalid")
    _write_exclusive(args.output, f"{client_secret}\n".encode("utf-8"), mode=0o400)


def _read_public_json(url: str) -> tuple[int, dict[str, object]]:
    try:
        with urlopen(url, timeout=10) as response:
            if response.geturl() != url:
                raise OperatorConfigError("public_route_redirected")
            status_code = int(response.status)
            payload = response.read(16 * 1024)
    except HTTPError as error:
        if error.geturl() != url:
            raise OperatorConfigError("public_route_redirected") from None
        status_code = int(error.code)
        payload = error.read(16 * 1024)
    except OperatorConfigError:
        raise
    except (OSError, URLError):
        raise OperatorConfigError("public_route_unavailable") from None
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise OperatorConfigError("public_route_response_invalid") from None
    if type(value) is not dict:
        raise OperatorConfigError("public_route_response_invalid")
    return status_code, value


def _read_public_status(url: str) -> tuple[int, str | None]:
    status_code, value = _read_public_json(url)
    status = value.get("status")
    return status_code, status if isinstance(status, str) else None


def _check_public(args: argparse.Namespace) -> None:
    origin = _require_text(args.origin, "origin")
    if not origin.startswith("https://") or origin != f"https://{_require_public_host(origin[8:])}":
        raise OperatorConfigError("origin_invalid")
    expected_ready = (503, "discovery_only") if args.mode == "discovery" else (200, "ready")
    last_error = "public_route_unavailable"
    for attempt in range(args.attempts):
        try:
            health = _read_public_status(f"{origin}/healthz")
            ready = _read_public_status(f"{origin}/readyz")
            protected_code, protected = _read_public_json(
                f"{origin}/.well-known/oauth-protected-resource"
            )
            server_code, server = _read_public_json(
                f"{origin}/.well-known/oauth-authorization-server"
            )
            metadata_ready = (
                protected_code == 200
                and protected.get("resource") == f"{origin}/mcp"
                and protected.get("authorization_servers") == [origin]
                and server_code == 200
                and server.get("issuer") == origin
                and server.get("authorization_endpoint") == f"{origin}/oauth/authorize"
                and server.get("token_endpoint") == f"{origin}/oauth/token"
                and server.get("jwks_uri") == f"{origin}/.well-known/jwks.json"
                and server.get("code_challenge_methods_supported") == ["S256"]
            )
            if health == (200, "ok") and ready == expected_ready and metadata_ready:
                return
            last_error = "public_route_response_invalid"
        except OperatorConfigError as error:
            last_error = str(error)
        if attempt + 1 < args.attempts:
            time.sleep(args.delay_seconds)
    raise OperatorConfigError(last_error)


def _wait_until_expired(args: argparse.Namespace) -> None:
    value = _require_text(args.expires_at, "expires_at")
    try:
        expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise OperatorConfigError("expires_at_invalid") from None
    if expiry.tzinfo is None or expiry.utcoffset() is None:
        raise OperatorConfigError("expires_at_invalid")
    gate = expiry.astimezone(timezone.utc) + timedelta(seconds=30)
    now = datetime.now(timezone.utc)
    wait_seconds = (gate - now).total_seconds()
    if wait_seconds > 3700:
        raise OperatorConfigError("expiry_wait_too_long")
    while datetime.now(timezone.utc) <= gate:
        time.sleep(min(5.0, max(0.05, (gate - datetime.now(timezone.utc)).total_seconds())))


def _predefined_client_id(args: argparse.Namespace) -> dict[str, str]:
    if args.deployment_id is not None:
        deployment_id = _require_identifier(args.deployment_id, "deployment_id")
        if deployment_id in _PLACEHOLDER_VALUES:
            raise OperatorConfigError("deployment_id_invalid")
        client_id = _require_chatgpt_client_id(f"formowl-chatgpt-{deployment_id}")
    else:
        client_id = _require_chatgpt_client_id(args.client_id)
    if args.output is not None:
        _write_exclusive(args.output, f"{client_id}\n".encode("utf-8"), mode=0o600)
        return {
            "command": "predefined-client-id",
            "status": "written",
        }
    return {
        "chatgpt_client_id": client_id,
        "command": "predefined-client-id",
        "status": "valid",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    compose = subparsers.add_parser("write-compose-env")
    compose.add_argument("--output", type=Path, required=True)
    compose.add_argument("--project-name", required=True)
    compose.add_argument("--runtime-image", required=True)
    compose.add_argument("--tls-proxy-image", required=True)
    compose.add_argument("--public-host", required=True)
    compose.add_argument("--acme-email", required=True)
    compose.add_argument("--chatgpt-client-id", required=True)
    compose.add_argument("--chatgpt-redirect-uri", required=True)
    compose.add_argument("--google-client-id", required=True)
    compose.add_argument("--owner-bootstrap-operator-service-id", required=True)
    compose.add_argument("--replace", action="store_true")

    google = subparsers.add_parser("import-google-client-secret")
    google.add_argument("--credential-json", type=Path, required=True)
    google.add_argument("--output", type=Path, required=True)
    google.add_argument("--expected-client-id", required=True)
    google.add_argument("--expected-redirect-uri", required=True)

    public = subparsers.add_parser("check-public")
    public.add_argument("--origin", required=True)
    public.add_argument("--mode", choices=("discovery", "ready"), required=True)
    public.add_argument("--attempts", type=int, default=24)
    public.add_argument("--delay-seconds", type=float, default=5.0)

    predefined_client = subparsers.add_parser("predefined-client-id")
    predefined_client_source = predefined_client.add_mutually_exclusive_group(required=True)
    predefined_client_source.add_argument("--deployment-id")
    predefined_client_source.add_argument("--client-id")
    predefined_client.add_argument("--output", type=Path)

    expiry = subparsers.add_parser("wait-until-expired")
    expiry.add_argument("--expires-at", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = {"command": args.command, "status": "written"}
    try:
        if args.command == "write-compose-env":
            _write_compose_env(args)
        elif args.command == "import-google-client-secret":
            _import_google_secret(args)
        elif args.command == "check-public":
            if not 1 <= args.attempts <= 120 or not 0 <= args.delay_seconds <= 30:
                raise OperatorConfigError("public_check_retry_invalid")
            _check_public(args)
        elif args.command == "predefined-client-id":
            result = _predefined_client_id(args)
        elif args.command == "wait-until-expired":
            _wait_until_expired(args)
        else:
            raise OperatorConfigError("command_invalid")
    except OperatorConfigError as error:
        print(
            json.dumps(
                {"error": str(error), "status": "error"},
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            result,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
