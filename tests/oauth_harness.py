from __future__ import annotations

import ast
import asyncio
import base64
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import logging
import math
from pathlib import Path
import re
import subprocess
import sys
import threading
from threading import Event, Thread
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Iterator, Mapping, Sequence
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests" / "issue20_function_harness_manifest.json"
ISSUE20_BASE_COMMIT = "8848c69f532dbb8d412e14be1ed1c6b12a4cfc90"
ISSUE20_FUNCTION_SCOPE_GLOBS = (
    "python/**/*.py",
    "scripts/**/*.py",
    "deploy/**/*.py",
)
ISSUE20_FUNCTION_EXCLUSION_RULES = (
    "explicit dunder implementations are included",
    "typing.overload declarations are excluded",
    "Protocol ellipsis-only declarations are excluded",
    "dataclass-generated methods are not AST-defined and are excluded",
    "deleted functions are outside the added-or-modified function gate",
)
REQUIRED_HARNESS_CATEGORIES = (
    "success",
    "invalid_or_protocol",
    "expiry_replay_or_revocation",
    "rollback_or_no_partial_state",
    "audit_lineage",
    "leak_safety",
    "remote_http",
)
_MAX_FUNCTIONS_PER_EVIDENCE_TEST = 12
_SOURCE_BINDING_KEYS = {
    "source_path",
    "change_kind",
    "base_ast_sha256",
    "current_ast_sha256",
    "diff_sha256",
}
_LIVE_ONLY_TEST_MARKERS = (
    "_postgres_live.",
    ".test_live_",
    ".LiveTests.",
)
_GENERIC_REASON_PHRASES = (
    "not applicable",
    "n/a",
    "covered elsewhere",
    "generic helper",
    "pure helper",
    "same as above",
)
_CATEGORY_REASON_TERMS = {
    "invalid_or_protocol": (
        "accepts no protocol input",
        "does not parse protocol input",
        "receives only validated input",
        "has no caller-controlled input",
    ),
    "expiry_replay_or_revocation": (
        "does not own expiry",
        "does not own replay",
        "does not own revocation",
        "has no temporal state",
    ),
    "rollback_or_no_partial_state": (
        "performs no durable write",
        "does not open a transaction",
        "is read-only",
        "mutates no repository state",
    ),
    "audit_lineage": (
        "does not emit audit",
        "does not persist audit",
        "audit emission is owned by",
        "has no audit side effect",
    ),
    "leak_safety": (
        "returns no caller-visible data",
        "does not receive secret material",
        "returns only a fixed public shape",
        "cannot expose a raw path",
    ),
    "remote_http": (
        "is not an http boundary",
        "does not perform http",
        "runs below the http boundary",
        "has no remote transport behavior",
    ),
}

_SENSITIVE_FIELD_PARTS = {
    "access_token",
    "authorization_code",
    "bearer",
    "claims",
    "client_state",
    "code_verifier",
    "email",
    "google_code",
    "id_token",
    "nonce",
    "private_payload",
    "refresh_token",
    "state",
    "transcript",
}
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_BEARER_RE = re.compile(r"\bbearer\s+[A-Za-z0-9._~+/-]{8,}", re.IGNORECASE)
_RAW_PATH_RE = re.compile(
    r"(^|[\s'\"([{=,:;])(/(?:home|tmp|srv|mnt|var|root|workspace)/|[A-Za-z]:[\\/])"
)
_SQL_RE = re.compile(
    r"\b(select\s+.+\s+from|insert\s+into|update\s+\w+\s+set|delete\s+from|drop\s+table)\b",
    re.IGNORECASE,
)


@dataclass
class FakeClock:
    current: datetime = field(
        default_factory=lambda: datetime(2026, 7, 12, 4, 0, 0, tzinfo=timezone.utc)
    )

    def now(self) -> datetime:
        return self.current

    def now_iso(self) -> str:
        return self.current.isoformat()

    def timestamp(self) -> int:
        return int(self.current.timestamp())

    def advance(self, *, seconds: int = 0, minutes: int = 0, hours: int = 0) -> None:
        self.current += timedelta(seconds=seconds, minutes=minutes, hours=hours)


class DeterministicRng:
    def __init__(self, seed: str | bytes = "formowl-issue20-oauth-harness") -> None:
        self._seed = seed.encode("utf-8") if isinstance(seed, str) else bytes(seed)
        self._counter = 0

    def bytes(self, length: int) -> bytes:
        if length < 0:
            raise ValueError("length must not be negative")
        output = bytearray()
        while len(output) < length:
            self._counter += 1
            output.extend(hashlib.sha256(self._seed + self._counter.to_bytes(16, "big")).digest())
        return bytes(output[:length])

    def token_urlsafe(self, byte_length: int = 32) -> str:
        return _b64url(self.bytes(byte_length))

    def identifier(self, prefix: str) -> str:
        return f"{prefix}_{self.token_urlsafe(18)}"


@dataclass(frozen=True)
class DeterministicRsaKey:
    kid: str
    n: int
    e: int
    d: int
    p: int
    q: int

    @classmethod
    def generate(cls, seed: str, *, kid: str, bits: int = 2048) -> "DeterministicRsaKey":
        if bits < 2048 or bits % 2:
            raise ValueError("test RSA keys must be an even size of at least 2048 bits")
        rng = DeterministicRng(seed)
        e = 65537
        prime_bits = bits // 2
        while True:
            p = _deterministic_prime(rng, prime_bits)
            q = _deterministic_prime(rng, prime_bits)
            if p == q:
                continue
            phi = (p - 1) * (q - 1)
            if math.gcd(e, phi) != 1:
                continue
            n = p * q
            if n.bit_length() < bits - 1:
                continue
            return cls(kid=kid, n=n, e=e, d=pow(e, -1, phi), p=p, q=q)

    def public_jwk(self) -> dict[str, str]:
        return {
            "kty": "RSA",
            "kid": self.kid,
            "use": "sig",
            "alg": "RS256",
            "n": _b64url(_int_bytes(self.n)),
            "e": _b64url(_int_bytes(self.e)),
        }

    def jwks(self) -> dict[str, list[dict[str, str]]]:
        return {"keys": [self.public_jwk()]}

    def sign_jwt(
        self,
        claims: Mapping[str, Any],
        *,
        headers: Mapping[str, Any] | None = None,
    ) -> str:
        header = {"alg": "RS256", "typ": "JWT", "kid": self.kid, **dict(headers or {})}
        encoded_header = _b64url(_canonical_json_bytes(header))
        encoded_claims = _b64url(_canonical_json_bytes(dict(claims)))
        signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")
        digest_info = (
            bytes.fromhex("3031300d060960864801650304020105000420")
            + hashlib.sha256(signing_input).digest()
        )
        key_size = (self.n.bit_length() + 7) // 8
        padding_length = key_size - len(digest_info) - 3
        if padding_length < 8:
            raise ValueError("RSA key is too small for RS256")
        encoded_message = b"\x00\x01" + b"\xff" * padding_length + b"\x00" + digest_info
        signature = pow(int.from_bytes(encoded_message, "big"), self.d, self.n).to_bytes(
            key_size, "big"
        )
        return f"{signing_input.decode('ascii')}.{_b64url(signature)}"


def generate_ephemeral_formowl_signing_key(*, kid: str) -> Any:
    """Create runtime-only FormOwl signing material; no private fixture is stored."""

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from formowl_auth.tokens import FormOwlSigningKey

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return FormOwlSigningKey(
        kid=kid,
        private_key_pem=private_key_pem,
        active=True,
    )


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> dict[str, Any]:
        value = json.loads(self.body.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("HTTP response JSON must be an object")
        return value

    @property
    def location(self) -> str | None:
        return self.headers.get("location")


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Mapping[str, str],
        newurl: str,
    ) -> None:
        return None


class HttpClient:
    def __init__(self, url_rewrites: Mapping[str, str] | None = None) -> None:
        self._opener = build_opener(NoRedirectHandler())
        self._url_rewrites = dict(url_rewrites or {})
        self.request_history: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        form: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        resolved_headers = dict(headers or {})
        resolved_body = body
        if form is not None:
            resolved_body = urlencode(dict(form)).encode("ascii")
            resolved_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        request = Request(
            self._rewrite_url(url),
            data=resolved_body,
            headers=resolved_headers,
            method=method.upper(),
        )
        try:
            response = self._opener.open(request, timeout=10)
        except HTTPError as error:
            result = HttpResponse(
                status=error.code,
                headers={key.lower(): value for key, value in error.headers.items()},
                body=error.read(),
            )
            self._record(method, url, result.status)
            return result
        with response:
            result = HttpResponse(
                status=response.status,
                headers={key.lower(): value for key, value in response.headers.items()},
                body=response.read(),
            )
        self._record(method, url, result.status)
        return result

    def _rewrite_url(self, url: str) -> str:
        for source in sorted(self._url_rewrites, key=len, reverse=True):
            if url.startswith(source):
                return self._url_rewrites[source] + url[len(source) :]
        return url

    def _record(self, method: str, url: str, status: int) -> None:
        parsed = urlparse(url)
        self.request_history.append(
            {
                "method": method.upper(),
                "path": parsed.path or "/",
                "status": status,
            }
        )

    def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> HttpResponse:
        return self.request("GET", url, headers=headers)

    def post_form(
        self,
        url: str,
        form: Mapping[str, str],
        *,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        return self.request("POST", url, headers=headers, form=form)

    def post_json(
        self,
        url: str,
        payload: Mapping[str, Any],
        *,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        resolved_headers = {"Content-Type": "application/json", **dict(headers or {})}
        return self.request(
            "POST",
            url,
            headers=resolved_headers,
            body=_canonical_json_bytes(dict(payload)),
        )


class RewritingAsyncHttpClient:
    """Use real localhost HTTP while production code requests fixed public URLs."""

    def __init__(self, url_rewrites: Mapping[str, str]) -> None:
        self._url_rewrites = dict(url_rewrites)
        self.request_history: list[dict[str, Any]] = []

    async def get(self, url: str, **kwargs: Any) -> Any:
        return await self._request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> Any:
        return await self._request("POST", url, **kwargs)

    async def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        import httpx

        rewritten = self._rewrite_url(url)
        async with httpx.AsyncClient() as client:
            response = await client.request(method, rewritten, **kwargs)
        parsed = urlparse(url)
        self.request_history.append(
            {
                "method": method,
                "path": parsed.path or "/",
                "status": response.status_code,
            }
        )
        return response

    def _rewrite_url(self, url: str) -> str:
        for source in sorted(self._url_rewrites, key=len, reverse=True):
            if url.startswith(source):
                return self._url_rewrites[source] + url[len(source) :]
        return url


class AsgiHttpServer:
    def __init__(self, app_factory: Callable[[str], Any]) -> None:
        self._app_factory = app_factory
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: Thread | None = None
        self._lifespan_receive: asyncio.Queue[dict[str, Any]] | None = None
        self._lifespan_send: asyncio.Queue[dict[str, Any]] | None = None
        self._lifespan_task: asyncio.Task[None] | None = None
        self._asgi_state: dict[str, Any] = {}
        self.request_history: list[dict[str, Any]] = []
        self.base_url = ""

    def __enter__(self) -> "AsgiHttpServer":
        holder: dict[str, Any] = {}
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "FormOwlIssue20ASGIHarness/1"

            def do_GET(self) -> None:  # noqa: N802
                self._dispatch()

            def do_POST(self) -> None:  # noqa: N802
                self._dispatch()

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                return

            def _dispatch(self) -> None:
                content_length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(content_length) if content_length else b""
                future = asyncio.run_coroutine_threadsafe(
                    _invoke_asgi(
                        holder["app"],
                        method=self.command,
                        target=self.path,
                        headers=list(self.headers.items()),
                        body=body,
                        state=holder["state"],
                    ),
                    holder["loop"],
                )
                status, headers, response_body = future.result(timeout=15)
                owner.request_history.append(
                    {
                        "method": self.command,
                        "path": urlparse(self.path).path or "/",
                        "status": status,
                    }
                )
                self.send_response(status)
                for key, value in headers:
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(response_body)))
                self.end_headers()
                self.wfile.write(response_body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        host, port = server.server_address[:2]
        self.base_url = f"http://{host}:{port}"
        holder["app"] = self._app_factory(self.base_url)
        holder["state"] = self._asgi_state
        loop = asyncio.new_event_loop()
        loop_started = Event()

        def run_loop() -> None:
            asyncio.set_event_loop(loop)
            loop_started.set()
            loop.run_forever()

        self._loop = loop
        self._loop_thread = Thread(target=run_loop, daemon=True)
        self._loop_thread.start()
        if not loop_started.wait(timeout=5):
            raise RuntimeError("ASGI harness event loop did not start")
        holder["loop"] = loop
        startup = asyncio.run_coroutine_threadsafe(
            self._start_lifespan(holder["app"]),
            loop,
        )
        startup.result(timeout=15)
        self._server = server
        self._thread = Thread(target=server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self._loop is not None:
            shutdown = asyncio.run_coroutine_threadsafe(
                self._stop_lifespan(),
                self._loop,
            )
            shutdown.result(timeout=15)
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._loop_thread is not None:
            self._loop_thread.join(timeout=5)
        if self._loop is not None:
            self._loop.close()

    async def _start_lifespan(self, app: Any) -> None:
        receive_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        send_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        async def receive() -> dict[str, Any]:
            return await receive_queue.get()

        async def send(message: Mapping[str, Any]) -> None:
            await send_queue.put(dict(message))

        task = asyncio.create_task(
            app(
                {
                    "type": "lifespan",
                    "asgi": {"version": "3.0", "spec_version": "2.0"},
                    "state": self._asgi_state,
                },
                receive,
                send,
            )
        )
        await receive_queue.put({"type": "lifespan.startup"})
        message = await asyncio.wait_for(send_queue.get(), timeout=10)
        if message.get("type") != "lifespan.startup.complete":
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise RuntimeError("ASGI harness lifespan startup failed")
        self._lifespan_receive = receive_queue
        self._lifespan_send = send_queue
        self._lifespan_task = task

    async def _stop_lifespan(self) -> None:
        if (
            self._lifespan_receive is None
            or self._lifespan_send is None
            or self._lifespan_task is None
        ):
            return
        await self._lifespan_receive.put({"type": "lifespan.shutdown"})
        message = await asyncio.wait_for(self._lifespan_send.get(), timeout=10)
        if message.get("type") != "lifespan.shutdown.complete":
            raise RuntimeError("ASGI harness lifespan shutdown failed")
        await asyncio.wait_for(self._lifespan_task, timeout=10)


@dataclass(frozen=True)
class FakeGoogleAccount:
    subject: str
    email: str
    email_verified: bool = True
    hosted_domain: str | None = None


class FakeGoogleOidcProvider:
    def __init__(
        self,
        *,
        clock: FakeClock,
        rng: DeterministicRng,
        signing_key: DeterministicRsaKey,
        client_id: str = "fake-google-client",
        client_secret: str = "fake-google-client-secret",
        issuer: str = "https://accounts.google.com",
        public_authorization_endpoint: str = "https://accounts.google.com/o/oauth2/v2/auth",
        public_token_endpoint: str = "https://oauth2.googleapis.com/token",
        public_jwks_uri: str = "https://www.googleapis.com/oauth2/v3/certs",
    ) -> None:
        self.clock = clock
        self.rng = rng
        self.signing_key = signing_key
        self.client_id = client_id
        self.client_secret = client_secret
        self.issuer = issuer
        self.public_authorization_endpoint = public_authorization_endpoint
        self.public_token_endpoint = public_token_endpoint
        self.public_jwks_uri = public_jwks_uri
        self.account = FakeGoogleAccount(
            subject="google-subject-alpha",
            email="invited-alpha@example.test",
        )
        self.base_url = ""
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None
        self._codes: dict[str, dict[str, str]] = {}
        self.next_claim_overrides: dict[str, Any] = {}
        self.next_signing_key: DeterministicRsaKey | None = None
        self.next_authorize_error: str | None = None
        self.request_counts = {"authorize": 0, "token": 0, "jwks": 0}

    def __enter__(self) -> "FakeGoogleOidcProvider":
        provider = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "FakeGoogleOIDC/1"

            def do_GET(self) -> None:  # noqa: N802
                provider._handle_get(self)

            def do_POST(self) -> None:  # noqa: N802
                provider._handle_post(self)

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        host, port = server.server_address[:2]
        self.base_url = f"http://{host}:{port}"
        self._server = server
        self._thread = Thread(target=server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    @property
    def authorization_endpoint(self) -> str:
        return self.base_url + "/authorize"

    @property
    def token_endpoint(self) -> str:
        return self.base_url + "/token"

    @property
    def jwks_uri(self) -> str:
        return self.base_url + "/jwks"

    @property
    def discovery_url(self) -> str:
        return self.base_url + "/.well-known/openid-configuration"

    def set_account(self, account: FakeGoogleAccount) -> None:
        self.account = account

    def _handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(handler.path)
        if parsed.path == "/.well-known/openid-configuration":
            self._send_json(
                handler,
                HTTPStatus.OK,
                {
                    "issuer": self.issuer,
                    "authorization_endpoint": self.public_authorization_endpoint,
                    "token_endpoint": self.public_token_endpoint,
                    "jwks_uri": self.public_jwks_uri,
                    "response_types_supported": ["code"],
                    "subject_types_supported": ["public"],
                    "id_token_signing_alg_values_supported": ["RS256"],
                },
            )
            return
        if parsed.path == "/jwks":
            self.request_counts["jwks"] += 1
            self._send_json(handler, HTTPStatus.OK, self.signing_key.jwks())
            return
        if parsed.path == "/authorize":
            self.request_counts["authorize"] += 1
            self._authorize(handler, parse_qs(parsed.query))
            return
        self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def _handle_post(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(handler.path)
        if parsed.path != "/token":
            self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        self.request_counts["token"] += 1
        length = int(handler.headers.get("Content-Length", "0"))
        form = parse_qs(handler.rfile.read(length).decode("ascii"))
        self._token(handler, form)

    def _authorize(
        self,
        handler: BaseHTTPRequestHandler,
        query: Mapping[str, Sequence[str]],
    ) -> None:
        redirect_uri = _first(query, "redirect_uri")
        state = _first(query, "state")
        if self.next_authorize_error:
            error = self.next_authorize_error
            self.next_authorize_error = None
            location = redirect_uri + "?" + urlencode({"error": error, "state": state})
            self._send_redirect(handler, location)
            return
        required = {
            "client_id": self.client_id,
            "response_type": "code",
        }
        if any(_first(query, key) != value for key, value in required.items()):
            self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid_request"})
            return
        nonce = _first(query, "nonce")
        if not redirect_uri or not state or not nonce:
            self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid_request"})
            return
        code = self.rng.identifier("google_code")
        self._codes[code] = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "nonce": nonce,
        }
        self._send_redirect(handler, redirect_uri + "?" + urlencode({"code": code, "state": state}))

    def _token(
        self,
        handler: BaseHTTPRequestHandler,
        form: Mapping[str, Sequence[str]],
    ) -> None:
        code = _first(form, "code")
        record = self._codes.pop(code, None)
        if (
            record is None
            or _first(form, "grant_type") != "authorization_code"
            or _first(form, "client_id") != self.client_id
            or _first(form, "client_secret") != self.client_secret
            or _first(form, "redirect_uri") != record["redirect_uri"]
        ):
            self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid_grant"})
            return
        now = self.clock.timestamp()
        claims: dict[str, Any] = {
            "iss": self.issuer,
            "sub": self.account.subject,
            "aud": self.client_id,
            "iat": now,
            "nbf": now,
            "exp": now + 300,
            "nonce": record["nonce"],
            "email": self.account.email,
            "email_verified": self.account.email_verified,
        }
        if self.account.hosted_domain:
            claims["hd"] = self.account.hosted_domain
        claims.update(self.next_claim_overrides)
        self.next_claim_overrides = {}
        signing_key = self.next_signing_key or self.signing_key
        self.next_signing_key = None
        self._send_json(
            handler,
            HTTPStatus.OK,
            {
                "access_token": self.rng.identifier("google_access"),
                "token_type": "Bearer",
                "expires_in": 300,
                "id_token": signing_key.sign_jwt(claims),
            },
        )

    @staticmethod
    def _send_redirect(handler: BaseHTTPRequestHandler, location: str) -> None:
        handler.send_response(HTTPStatus.FOUND)
        handler.send_header("Location", location)
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    @staticmethod
    def _send_json(
        handler: BaseHTTPRequestHandler,
        status: HTTPStatus,
        payload: Mapping[str, Any],
    ) -> None:
        body = _canonical_json_bytes(dict(payload))
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)


class SimulatedChatGptOAuthClient:
    def __init__(
        self,
        *,
        rng: DeterministicRng,
        client_id: str,
        redirect_uri: str,
        resource: str,
        scope: str = "formowl.use",
        http_client: HttpClient | None = None,
    ) -> None:
        self.rng = rng
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.resource = resource
        self.scope = scope
        self.http = http_client or HttpClient()

    def new_authorization(self) -> dict[str, str]:
        verifier = self.rng.token_urlsafe(48)
        challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
        return {
            "state": self.rng.token_urlsafe(32),
            "code_verifier": verifier,
            "code_challenge": challenge,
        }

    def authorization_url(self, authorization_endpoint: str, values: Mapping[str, str]) -> str:
        query = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "resource": self.resource,
            "scope": self.scope,
            "state": values["state"],
            "code_challenge": values["code_challenge"],
            "code_challenge_method": "S256",
        }
        return authorization_endpoint + "?" + urlencode(query)

    def complete_browser_redirects(self, authorization_url: str) -> dict[str, str]:
        first = self.http.get(authorization_url)
        if first.status not in {302, 303, 307, 308} or not first.location:
            raise AssertionError("FormOwl authorize endpoint did not redirect to Google")
        second = self.http.get(first.location)
        if second.status not in {302, 303, 307, 308} or not second.location:
            raise AssertionError("fake Google authorize endpoint did not return to FormOwl")
        third = self.http.get(second.location)
        if third.status not in {302, 303, 307, 308} or not third.location:
            raise AssertionError("FormOwl callback did not return to ChatGPT")
        callback = urlparse(third.location)
        if third.location.split("?", 1)[0] != self.redirect_uri:
            raise AssertionError("FormOwl callback used an unexpected ChatGPT redirect URI")
        query = parse_qs(callback.query)
        return {key: values[0] for key, values in query.items() if values}

    def exchange_code(
        self,
        token_endpoint: str,
        *,
        code: str,
        verifier: str,
    ) -> HttpResponse:
        return self.http.post_form(
            token_endpoint,
            {
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "resource": self.resource,
                "code": code,
                "code_verifier": verifier,
            },
        )

    def mcp_call(
        self,
        mcp_endpoint: str,
        payload: Mapping[str, Any],
        *,
        bearer: str | None = None,
    ) -> HttpResponse:
        headers = {
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": _latest_mcp_protocol_version(),
        }
        if bearer is not None:
            headers["Authorization"] = f"Bearer {bearer}"
        return self.http.post_json(mcp_endpoint, payload, headers=headers)


async def run_official_mcp_client_sequence(
    endpoint: str,
    *,
    bearer: str | None,
    tool_calls: Sequence[tuple[str, Mapping[str, Any]]],
) -> dict[str, Any]:
    """Negotiate and call tools through the official MCP Streamable HTTP client."""

    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    headers = {"MCP-Protocol-Version": _latest_mcp_protocol_version()}
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    async with httpx.AsyncClient(
        headers=headers,
        follow_redirects=False,
        timeout=10.0,
        trust_env=False,
    ) as http_client:
        async with streamable_http_client(endpoint, http_client=http_client) as streams:
            read_stream, write_stream = streams[0], streams[1]
            async with ClientSession(read_stream, write_stream) as session:
                initialized = await session.initialize()
                listed = await session.list_tools()
                results = []
                for name, arguments in tool_calls:
                    result = await session.call_tool(name, arguments=dict(arguments))
                    results.append(
                        {
                            "name": name,
                            "result": _model_dump(result),
                        }
                    )
    return {
        "initialize": _model_dump(initialized),
        "tools": _model_dump(listed),
        "calls": results,
    }


class _HarnessUploadRecorder:
    """Synthetic handler evidence; this is not a production persistence adapter."""

    def __init__(self, *, clock: Callable[[], datetime]) -> None:
        self.clock = clock
        self.calls: list[dict[str, Any]] = []
        self.results: list[dict[str, Any]] = []
        self.audit_events: list[dict[str, Any]] = []

    def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        safe_payload = json.loads(json.dumps(payload, sort_keys=True))
        self.calls.append(safe_payload)
        sequence = len(self.calls)
        upload_session_id = f"upload_e2e_{sequence}"
        audit_log_id = f"audit_upload_e2e_{sequence}"
        self.audit_events.append(
            {
                "audit_log_id": audit_log_id,
                "action": "upload_session_created",
                "actor_user_id": safe_payload["requester_user_id"],
                "target_type": "upload_session",
                "target_id": upload_session_id,
                "session_id": safe_payload["session_id"],
                "workspace_id": safe_payload["workspace_id"],
                "status": "ok",
                "reason_code": "upload_session_created",
                "timestamp": self.clock().astimezone(timezone.utc).isoformat(),
                "authorization_request_id": None,
                "authorization_tool_call_id": None,
                "evidence_mode": "deterministic_fake_upload_recorder",
            }
        )
        result = {
            "upload_session_id": upload_session_id,
            "status": "ok",
            "next_required_action": "upload_prepared_resource",
            "audit_ref": audit_log_id,
            "upload_task_card": {
                "card_type": "generic_resource_upload",
                "workspace_id": safe_payload["workspace_id"],
                "current_user_id": safe_payload["requester_user_id"],
            },
            "source_preparation_guidance": {
                "status": "ready",
                "intended_asset_type": safe_payload.get("intended_asset_type"),
            },
        }
        self.results.append(json.loads(json.dumps(result, sort_keys=True)))
        return result

    def bind_authorization_decision(self, decision: Mapping[str, Any]) -> bool:
        if len(self.calls) != 1 or len(self.audit_events) != 1:
            return False
        call = self.calls[0]
        audit = self.audit_events[0]
        if (
            decision.get("action") != "mcp_authorization_allowed"
            or decision.get("target_type") != "mcp_tool"
            or decision.get("target_id") != "open_upload_session"
            or decision.get("actor_user_id") != call.get("requester_user_id")
            or decision.get("workspace_id") != call.get("workspace_id")
            or decision.get("oauth_token_session_id") != call.get("session_id")
            or not isinstance(decision.get("request_id"), str)
            or not isinstance(decision.get("tool_call_id"), str)
        ):
            return False
        audit["authorization_request_id"] = decision["request_id"]
        audit["authorization_tool_call_id"] = decision["tool_call_id"]
        return True


class FailureInjected(RuntimeError):
    pass


class TransactionAwareMemoryRepository:
    def __init__(self) -> None:
        self._tables: dict[str, dict[str, dict[str, Any]]] = {}
        self._transaction_snapshot: bytes | None = None
        self._transaction_committed = False
        self._write_index = 0
        self._fail_at_write_index: int | None = None
        self.write_operations: list[str] = []

    @contextmanager
    def transaction(self) -> Iterator["TransactionAwareMemoryRepository"]:
        if self._transaction_snapshot is not None:
            raise RuntimeError("nested harness transactions are not supported")
        snapshot = self.snapshot_bytes()
        self._transaction_snapshot = snapshot
        self._transaction_committed = False
        try:
            yield self
        except Exception:
            self._restore_snapshot(snapshot)
            raise
        else:
            if not self._transaction_committed:
                self._restore_snapshot(snapshot)
        finally:
            self._transaction_snapshot = None
            self._transaction_committed = False

    def commit(self) -> None:
        if self._transaction_snapshot is None:
            raise RuntimeError("repository commit requires an active transaction")
        self._transaction_committed = True

    def inject_failure_at(self, write_index: int | None) -> None:
        if write_index is not None and write_index < 1:
            raise ValueError("write_index must be positive")
        self._fail_at_write_index = write_index
        self._write_index = 0

    def put(self, table: str, key: str, value: Mapping[str, Any], *, operation: str) -> None:
        self._before_write(operation)
        self._tables.setdefault(table, {})[key] = json.loads(
            json.dumps(dict(value), sort_keys=True)
        )

    def delete(self, table: str, key: str, *, operation: str) -> None:
        self._before_write(operation)
        self._tables.setdefault(table, {}).pop(key, None)

    def get(self, table: str, key: str) -> dict[str, Any] | None:
        value = self._tables.get(table, {}).get(key)
        return None if value is None else json.loads(json.dumps(value, sort_keys=True))

    def list(self, table: str) -> list[dict[str, Any]]:
        return [
            json.loads(json.dumps(value, sort_keys=True))
            for _, value in sorted(self._tables.get(table, {}).items())
        ]

    def insert_user(self, user: Any) -> None:
        payload = user.to_dict()
        self.put("users", payload["user_id"], payload, operation="insert_user")

    def get_user(self, user_id: str) -> Any | None:
        from formowl_contract import User

        payload = self.get("users", user_id)
        return User.from_dict(payload) if payload is not None else None

    def find_users_by_email(self, normalized_email: str) -> list[Any]:
        from formowl_contract import User

        rows = [
            payload for payload in self.list("users") if payload.get("email") == normalized_email
        ]
        rows.sort(key=lambda payload: str(payload["user_id"]))
        return [User.from_dict(payload) for payload in rows]

    def list_workspace_users(self, workspace_id: str) -> list[tuple[Any, Any]]:
        from formowl_contract import User, WorkspaceMember

        rows: list[tuple[Any, Any]] = []
        for membership in self.list("workspace_members"):
            if (
                membership.get("workspace_id") != workspace_id
                or membership.get("removed_at") is not None
            ):
                continue
            user = self.get("users", str(membership["user_id"]))
            if user is None:
                continue
            rows.append(
                (
                    User.from_dict(user),
                    WorkspaceMember.from_dict(
                        {
                            "workspace_id": membership["workspace_id"],
                            "user_id": membership["user_id"],
                            "role": membership["role"],
                        }
                    ),
                )
            )
        rows.sort(key=lambda row: row[0].user_id)
        return rows

    def update_user_profile(self, user_id: str, *, display_name: str, email: str) -> None:
        payload = self.get("users", user_id)
        self._before_write("update_user_profile")
        if payload is None:
            return
        payload.update({"display_name": display_name, "email": email})
        self._store("users", user_id, payload)

    def insert_workspace_member(self, member: Any, *, created_at: str) -> None:
        payload = {**member.to_dict(), "created_at": created_at, "removed_at": None}
        key = self._workspace_member_key(payload["user_id"], payload["workspace_id"])
        self.put(
            "workspace_members",
            key,
            payload,
            operation="insert_workspace_member",
        )

    def get_active_workspace_member(
        self,
        user_id: str,
        workspace_id: str,
        *,
        for_update: bool = False,
    ) -> Any | None:
        del for_update
        from formowl_contract import WorkspaceMember

        payload = self.get(
            "workspace_members",
            self._workspace_member_key(user_id, workspace_id),
        )
        if payload is None or payload.get("removed_at") is not None:
            return None
        return WorkspaceMember.from_dict(
            {
                "workspace_id": payload["workspace_id"],
                "user_id": payload["user_id"],
                "role": payload["role"],
            }
        )

    def get_removed_workspace_member(
        self,
        user_id: str,
        workspace_id: str,
        *,
        for_update: bool = False,
    ) -> Any | None:
        del for_update
        from formowl_contract import WorkspaceMember

        payload = self.get(
            "workspace_members",
            self._workspace_member_key(user_id, workspace_id),
        )
        if payload is None or payload.get("removed_at") is None:
            return None
        return WorkspaceMember.from_dict(
            {
                "workspace_id": payload["workspace_id"],
                "user_id": payload["user_id"],
                "role": payload["role"],
            }
        )

    def remove_workspace_member(
        self,
        user_id: str,
        workspace_id: str,
        *,
        removed_at: str,
    ) -> None:
        key = self._workspace_member_key(user_id, workspace_id)
        payload = self.get("workspace_members", key)
        self._before_write("remove_workspace_member")
        if payload is None or payload.get("removed_at") is not None:
            return
        payload["removed_at"] = removed_at
        self._store("workspace_members", key, payload)

    def restore_workspace_member(self, user_id: str, workspace_id: str) -> None:
        key = self._workspace_member_key(user_id, workspace_id)
        payload = self.get("workspace_members", key)
        self._before_write("restore_workspace_member")
        if payload is None or payload.get("removed_at") is None:
            return
        payload["removed_at"] = None
        self._store("workspace_members", key, payload)

    def list_active_workspace_members(self, user_id: str) -> list[Any]:
        from formowl_contract import WorkspaceMember

        rows = [
            payload
            for payload in self.list("workspace_members")
            if payload.get("user_id") == user_id and payload.get("removed_at") is None
        ]
        rows.sort(key=lambda payload: str(payload["workspace_id"]))
        return [
            WorkspaceMember.from_dict(
                {
                    "workspace_id": payload["workspace_id"],
                    "user_id": payload["user_id"],
                    "role": payload["role"],
                }
            )
            for payload in rows
        ]

    def list_active_workspace_members_in_workspace(
        self,
        workspace_id: str,
        *,
        for_update: bool = False,
    ) -> list[Any]:
        del for_update
        from formowl_contract import WorkspaceMember

        rows = [
            payload
            for payload in self.list("workspace_members")
            if payload.get("workspace_id") == workspace_id and payload.get("removed_at") is None
        ]
        rows.sort(key=lambda payload: str(payload["user_id"]))
        return [
            WorkspaceMember.from_dict(
                {
                    "workspace_id": payload["workspace_id"],
                    "user_id": payload["user_id"],
                    "role": payload["role"],
                }
            )
            for payload in rows
        ]

    def count_active_workspace_members(self, workspace_id: str) -> int:
        return sum(
            1
            for payload in self.list("workspace_members")
            if payload.get("workspace_id") == workspace_id and payload.get("removed_at") is None
        )

    def list_active_grants(self, user_id: str, *, now: str) -> list[Any]:
        from formowl_contract import Grant

        rows = [
            payload
            for payload in self.list("grants")
            if payload.get("grantee_user_id") == user_id
            and payload.get("revoked_at") is None
            and str(payload.get("expires_at", "")) > now
        ]
        rows.sort(key=lambda payload: str(payload["grant_id"]))
        return [Grant.from_dict(payload) for payload in rows]

    def insert_external_identity(self, identity: Any) -> None:
        payload = identity.to_dict()
        self.put(
            "external_identities",
            payload["external_identity_id"],
            payload,
            operation="insert_external_identity",
        )

    def find_external_identity(self, issuer: str, subject: str) -> Any | None:
        from formowl_auth.models import ExternalIdentity

        matches = [
            payload
            for payload in self.list("external_identities")
            if payload.get("issuer") == issuer and payload.get("subject") == subject
        ]
        if not matches:
            return None
        matches.sort(key=lambda payload: str(payload["external_identity_id"]))
        return ExternalIdentity.from_dict(matches[0])

    def get_external_identity(self, external_identity_id: str) -> Any | None:
        from formowl_auth.models import ExternalIdentity

        payload = self.get("external_identities", external_identity_id)
        return ExternalIdentity.from_dict(payload) if payload is not None else None

    def update_external_identity_profile(
        self,
        external_identity_id: str,
        *,
        email: str,
        authenticated_at: str,
    ) -> None:
        payload = self.get("external_identities", external_identity_id)
        self._before_write("update_external_identity_profile")
        if payload is None:
            return
        payload.update({"email": email, "last_authenticated_at": authenticated_at})
        self._store("external_identities", external_identity_id, payload)

    def insert_invitation(self, invitation: Any) -> None:
        payload = invitation.to_dict()
        self.put(
            "oauth_invitations",
            payload["invitation_id"],
            payload,
            operation="insert_invitation",
        )

    def get_invitation(self, invitation_id: str) -> Any | None:
        from formowl_auth.models import OAuthInvitation

        payload = self.get("oauth_invitations", invitation_id)
        return OAuthInvitation.from_dict(payload) if payload is not None else None

    def find_pending_owner_invitations(
        self,
        workspace_id: str,
        *,
        now: str,
        for_update: bool = False,
    ) -> list[Any]:
        del for_update
        from formowl_auth.models import OAuthInvitation

        rows = [
            payload
            for payload in self.list("oauth_invitations")
            if payload.get("workspace_id") == workspace_id
            and payload.get("role") == "owner"
            and payload.get("status") == "pending"
            and str(payload.get("expires_at", "")) > now
        ]
        rows.sort(key=lambda payload: str(payload["invitation_id"]))
        return [OAuthInvitation.from_dict(payload) for payload in rows]

    def find_active_invitations(
        self,
        normalized_email: str,
        *,
        now: str,
        for_update: bool = False,
    ) -> list[Any]:
        del for_update
        from formowl_auth.models import OAuthInvitation

        rows = [
            payload
            for payload in self.list("oauth_invitations")
            if payload.get("normalized_email") == normalized_email
            and payload.get("status") == "pending"
            and str(payload.get("expires_at", "")) > now
        ]
        rows.sort(key=lambda payload: str(payload["invitation_id"]))
        return [OAuthInvitation.from_dict(payload) for payload in rows]

    def mark_invitation_accepted(
        self,
        invitation_id: str,
        *,
        external_identity_id: str,
        accepted_at: str,
    ) -> None:
        payload = self.get("oauth_invitations", invitation_id)
        self._before_write("mark_invitation_accepted")
        if payload is None or payload.get("status") != "pending":
            return
        payload.update(
            {
                "status": "accepted",
                "accepted_at": accepted_at,
                "accepted_external_identity_id": external_identity_id,
            }
        )
        self._store("oauth_invitations", invitation_id, payload)

    def upsert_owner_bootstrap(self, bootstrap: Any) -> bool:
        payload = bootstrap.to_dict()
        self._before_write("upsert_owner_bootstrap")
        if self.get("oauth_owner_bootstraps", payload["workspace_id"]) is not None:
            return False
        self._store("oauth_owner_bootstraps", payload["workspace_id"], payload)
        return True

    def get_owner_bootstrap(
        self,
        workspace_id: str,
        *,
        for_update: bool = False,
    ) -> Any | None:
        del for_update
        from formowl_auth.models import OAuthOwnerBootstrap

        payload = self.get("oauth_owner_bootstraps", workspace_id)
        return OAuthOwnerBootstrap.from_dict(payload) if payload is not None else None

    def get_owner_bootstrap_by_invitation(
        self,
        invitation_id: str,
        *,
        for_update: bool = False,
    ) -> Any | None:
        del for_update
        from formowl_auth.models import OAuthOwnerBootstrap

        rows = [
            payload
            for payload in self.list("oauth_owner_bootstraps")
            if payload.get("invitation_id") == invitation_id
        ]
        if not rows:
            return None
        return OAuthOwnerBootstrap.from_dict(rows[0])

    def complete_owner_bootstrap(self, invitation_id: str, *, completed_at: str) -> None:
        matches = [
            payload
            for payload in self.list("oauth_owner_bootstraps")
            if payload.get("invitation_id") == invitation_id
        ]
        self._before_write("complete_owner_bootstrap")
        if not matches or matches[0].get("status") != "pending":
            return
        payload = matches[0]
        payload.update({"status": "completed", "completed_at": completed_at})
        self._store("oauth_owner_bootstraps", payload["workspace_id"], payload)

    def insert_client_authorization(self, authorization: Any) -> None:
        payload = authorization.to_dict()
        self.put(
            "oauth_client_authorizations",
            payload["oauth_client_authorization_id"],
            payload,
            operation="insert_client_authorization",
        )

    def get_client_authorization(
        self,
        client_id: str,
        external_identity_id: str,
    ) -> Any | None:
        from formowl_auth.models import OAuthClientAuthorization

        matches = [
            payload
            for payload in self.list("oauth_client_authorizations")
            if payload.get("client_id") == client_id
            and payload.get("external_identity_id") == external_identity_id
        ]
        if not matches:
            return None
        matches.sort(key=lambda payload: str(payload["oauth_client_authorization_id"]))
        return OAuthClientAuthorization.from_dict(matches[0])

    def get_client_authorization_by_id(
        self,
        oauth_client_authorization_id: str,
    ) -> Any | None:
        from formowl_auth.models import OAuthClientAuthorization

        payload = self.get(
            "oauth_client_authorizations",
            oauth_client_authorization_id,
        )
        return OAuthClientAuthorization.from_dict(payload) if payload is not None else None

    def insert_transaction(self, transaction: Any) -> None:
        payload = transaction.to_dict()
        self.put(
            "oauth_transactions",
            payload["transaction_id"],
            payload,
            operation="insert_transaction",
        )

    def get_transaction_by_state_hash(
        self,
        google_state_hash: str,
        *,
        for_update: bool = False,
    ) -> Any | None:
        del for_update
        from formowl_auth.models import OAuthTransaction

        matches = [
            payload
            for payload in self.list("oauth_transactions")
            if payload.get("google_state_hash") == google_state_hash
        ]
        if not matches:
            return None
        matches.sort(key=lambda payload: str(payload["transaction_id"]))
        return OAuthTransaction.from_dict(matches[0])

    def consume_transaction(self, transaction_id: str, *, consumed_at: str) -> None:
        payload = self.get("oauth_transactions", transaction_id)
        self._before_write("consume_transaction")
        if (
            payload is None
            or payload.get("status") != "pending"
            or payload.get("consumed_at") is not None
        ):
            return
        payload.update({"status": "consumed", "consumed_at": consumed_at})
        self._store("oauth_transactions", transaction_id, payload)

    def fail_transaction(self, transaction_id: str, *, failed_at: str) -> None:
        payload = self.get("oauth_transactions", transaction_id)
        self._before_write("fail_transaction")
        if (
            payload is None
            or payload.get("status") != "pending"
            or payload.get("consumed_at") is not None
        ):
            return
        payload.update({"status": "failed", "consumed_at": failed_at})
        self._store("oauth_transactions", transaction_id, payload)

    def insert_authorization_code(self, code: Any) -> None:
        payload = code.to_dict()
        self.put(
            "oauth_authorization_codes",
            payload["code_hash"],
            payload,
            operation="insert_authorization_code",
        )

    def get_authorization_code(
        self,
        code_hash: str,
        *,
        for_update: bool = False,
    ) -> Any | None:
        del for_update
        from formowl_auth.models import OAuthAuthorizationCode

        payload = self.get("oauth_authorization_codes", code_hash)
        return OAuthAuthorizationCode.from_dict(payload) if payload is not None else None

    def consume_authorization_code(
        self,
        code_hash: str,
        *,
        consumed_at: str,
        user_id: str,
        external_identity_id: str,
        client_id: str,
        redirect_uri: str,
        resource: str,
    ) -> None:
        from formowl_auth.models import OAuthAccessDenied

        payload = self.get("oauth_authorization_codes", code_hash)
        self._before_write("consume_authorization_code")
        if (
            payload is None
            or payload.get("consumed_at") is not None
            or datetime.fromisoformat(str(payload.get("expires_at")).replace("Z", "+00:00"))
            <= datetime.fromisoformat(consumed_at.replace("Z", "+00:00"))
            or payload.get("user_id") != user_id
            or payload.get("external_identity_id") != external_identity_id
            or payload.get("client_id") != client_id
            or payload.get("redirect_uri") != redirect_uri
            or payload.get("resource") != resource
        ):
            raise OAuthAccessDenied(
                "invalid_grant",
                "authorization_code_not_consumable",
                400,
            )
        payload["consumed_at"] = consumed_at
        self._store("oauth_authorization_codes", code_hash, payload)

    def insert_token_session(self, session: Any) -> None:
        payload = session.to_dict()
        self.put(
            "oauth_token_sessions",
            payload["token_session_id"],
            payload,
            operation="insert_token_session",
        )

    def get_token_session(self, token_session_id: str) -> Any | None:
        from formowl_auth.models import OAuthTokenSession

        payload = self.get("oauth_token_sessions", token_session_id)
        return OAuthTokenSession.from_dict(payload) if payload is not None else None

    def list_token_sessions(self, user_id: str, workspace_id: str) -> list[Any]:
        from formowl_auth.models import OAuthTokenSession

        rows = [
            payload
            for payload in self.list("oauth_token_sessions")
            if payload.get("user_id") == user_id
            and payload.get("current_workspace_id") == workspace_id
        ]
        rows.sort(key=lambda payload: str(payload["token_session_id"]))
        rows.sort(key=lambda payload: str(payload["issued_at"]), reverse=True)
        return [OAuthTokenSession.from_dict(payload) for payload in rows]

    def revoke_active_token_sessions_for_membership(
        self,
        user_id: str,
        workspace_id: str,
        *,
        revoked_at: str,
        reason_code: str,
    ) -> None:
        self._before_write("revoke_active_token_sessions_for_membership")
        for payload in self.list("oauth_token_sessions"):
            if (
                payload.get("user_id") != user_id
                or payload.get("current_workspace_id") != workspace_id
                or payload.get("revoked_at") is not None
            ):
                continue
            payload.update({"revoked_at": revoked_at, "revocation_reason": reason_code})
            self._store("oauth_token_sessions", str(payload["token_session_id"]), payload)

    def revoke_token_session(
        self,
        token_session_id: str,
        *,
        revoked_at: str,
        reason_code: str,
    ) -> None:
        payload = self.get("oauth_token_sessions", token_session_id)
        self._before_write("revoke_token_session")
        if payload is None or payload.get("revoked_at") is not None:
            return
        payload.update({"revoked_at": revoked_at, "revocation_reason": reason_code})
        self._store("oauth_token_sessions", token_session_id, payload)

    def append_audit_log(self, audit_log: Any) -> None:
        payload = audit_log.to_dict()
        self.put(
            "audit_log",
            payload["audit_log_id"],
            payload,
            operation="append_audit_log",
        )

    def snapshot_bytes(self) -> bytes:
        return _canonical_json_bytes(self._tables)

    def mutable_state_snapshot_bytes(self) -> bytes:
        return _canonical_json_bytes(
            {table: rows for table, rows in self._tables.items() if table != "audit_log"}
        )

    @property
    def audit_event_count(self) -> int:
        return len(self._tables.get("audit_log", {}))

    def assert_unchanged(self, snapshot: bytes) -> None:
        if self.snapshot_bytes() != snapshot:
            raise AssertionError("repository state changed after an injected failure")

    def assert_mutable_state_unchanged(self, snapshot: bytes) -> None:
        if self.mutable_state_snapshot_bytes() != snapshot:
            raise AssertionError("mutable OAuth state changed after a denied request")

    def _before_write(self, operation: str) -> None:
        self._write_index += 1
        self.write_operations.append(operation)
        if self._fail_at_write_index == self._write_index:
            raise FailureInjected(f"injected repository failure at write {self._write_index}")

    def _store(self, table: str, key: str, value: Mapping[str, Any]) -> None:
        self._tables.setdefault(table, {})[key] = json.loads(
            json.dumps(dict(value), sort_keys=True)
        )

    @staticmethod
    def _workspace_member_key(user_id: str, workspace_id: str) -> str:
        return json.dumps([user_id, workspace_id], separators=(",", ":"))

    def _restore_snapshot(self, snapshot: bytes) -> None:
        value = json.loads(snapshot.decode("utf-8"))
        if not isinstance(value, dict):
            raise AssertionError("repository snapshot is malformed")
        self._tables = value


class CapturedLogs:
    def __init__(self, logger_name: str | None = None) -> None:
        self.logger_name = logger_name
        self.records: list[logging.LogRecord] = []
        self._handler: logging.Handler | None = None
        self._logger: logging.Logger | None = None

    def __enter__(self) -> "CapturedLogs":
        owner = self

        class Handler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                owner.records.append(record)

        self._handler = Handler()
        self._logger = logging.getLogger(self.logger_name)
        self._logger.addHandler(self._handler)
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._logger is not None and self._handler is not None:
            self._logger.removeHandler(self._handler)

    def rendered(self) -> str:
        return "\n".join(record.getMessage() for record in self.records)


class Issue20HarnessDependencyMissing(RuntimeError):
    pass


def run_issue20_deterministic_e2e() -> dict[str, Any]:
    try:
        from formowl_auth.config import (
            GOOGLE_AUTHORIZATION_ENDPOINT,
            GOOGLE_DISCOVERY_URL,
            GOOGLE_JWKS_URI,
            GOOGLE_TOKEN_ENDPOINT,
            OAuthBridgeConfig,
        )
        from formowl_auth.google_oidc import GoogleOidcClient
        from formowl_auth.service import FormOwlOAuthBridge
        from formowl_auth.tokens import FormOwlSigningKeySet, FormOwlTokenCodec
        from formowl_contract import User, WorkspaceMember
        from formowl_gateway.remote import (
            build_www_authenticate_challenge,
            create_connected_mcp_application,
        )
        from formowl_gateway.semantic import SemanticMcpGateway
    except ModuleNotFoundError as exc:
        raise Issue20HarnessDependencyMissing(
            "issue #20 production OAuth and remote MCP dependencies are unavailable"
        ) from exc

    clock = FakeClock()
    rng = DeterministicRng("formowl-issue20-primary-e2e")
    fake_google_key = DeterministicRsaKey.generate(
        "formowl-issue20-fake-google-primary",
        kid="fake-google-primary-1",
    )
    public_origin = "https://formowl.example.test"
    workspace_id = "workspace_alpha"
    admin_user_id = "user_admin"
    operator_service_id = "operator_service_primary"
    sensitive_values: list[str] = []
    upload_recorder = _HarnessUploadRecorder(clock=clock.now)

    with CapturedLogs() as captured_logs:
        with FakeGoogleOidcProvider(
            clock=clock,
            rng=DeterministicRng("formowl-issue20-fake-google-provider"),
            signing_key=fake_google_key,
        ) as fake_google:
            config = OAuthBridgeConfig(
                issuer=public_origin,
                resource=f"{public_origin}/mcp",
                chatgpt_client_id="chatgpt-formowl-closed-beta",
                chatgpt_redirect_uri=("https://chatgpt.com/connector/oauth/deterministic-harness"),
                google_client_id=fake_google.client_id,
                google_client_secret=fake_google.client_secret,
                google_redirect_uri=f"{public_origin}/oauth/google/callback",
                state_encryption_key=base64.urlsafe_b64encode(rng.bytes(32)).decode("ascii"),
                access_token_lifetime_seconds=120,
                authorization_code_lifetime_seconds=120,
                authorization_transaction_lifetime_seconds=240,
                clock_skew_seconds=5,
            )
            google_http = RewritingAsyncHttpClient(
                {
                    GOOGLE_DISCOVERY_URL: fake_google.discovery_url,
                    GOOGLE_TOKEN_ENDPOINT: fake_google.token_endpoint,
                    GOOGLE_JWKS_URI: fake_google.jwks_uri,
                }
            )
            google_client = GoogleOidcClient(
                config=config,
                http_client=google_http,
            )
            signing_key = generate_ephemeral_formowl_signing_key(kid="formowl-e2e-active-1")
            token_codec = FormOwlTokenCodec(
                issuer=config.issuer,
                client_id=config.chatgpt_client_id,
                key_set=FormOwlSigningKeySet([signing_key]),
                lifetime_seconds=config.access_token_lifetime_seconds,
                clock_skew_seconds=config.clock_skew_seconds,
            )
            repository = TransactionAwareMemoryRepository()
            bridge = FormOwlOAuthBridge(
                config=config,
                repository=repository,
                google_client=google_client,
                token_codec=token_codec,
                random_bytes=rng.bytes,
                owner_bootstrap_operator_authorizer=(
                    lambda candidate: candidate == operator_service_id
                ),
            )
            repository.insert_user(
                User(
                    user_id=admin_user_id,
                    display_name="FormOwl Admin",
                    email="admin@example.test",
                    status="active",
                    created_at=clock.now_iso(),
                )
            )
            repository.insert_workspace_member(
                WorkspaceMember(
                    workspace_id=workspace_id,
                    user_id=admin_user_id,
                    role="owner",
                ),
                created_at=clock.now_iso(),
            )
            bridge.provision_invitation(
                email=fake_google.account.email,
                workspace_id=workspace_id,
                role="member",
                invited_by_user_id=admin_user_id,
                operator_service_id=operator_service_id,
                expires_at=clock.now() + timedelta(hours=1),
                now=clock.now(),
            )
            semantic_gateway = SemanticMcpGateway(
                upload_session_handler=upload_recorder,
            )
            application_holder: dict[str, Any] = {}

            def app_factory(_base_url: str) -> Any:
                application = create_connected_mcp_application(
                    bridge=bridge,
                    config=config,
                    google_client=google_client,
                    semantic_gateway=semantic_gateway,
                    clock=clock.now,
                    environ={"FORMOWL_AUTH_MODE": "oauth_google"},
                )
                application_holder["application"] = application
                return application.app

            with AsgiHttpServer(app_factory) as formowl_server:
                browser_http = HttpClient(
                    {
                        public_origin: formowl_server.base_url,
                        GOOGLE_AUTHORIZATION_ENDPOINT: fake_google.authorization_endpoint,
                    }
                )
                chatgpt = SimulatedChatGptOAuthClient(
                    rng=DeterministicRng("formowl-issue20-chatgpt-primary"),
                    client_id=config.chatgpt_client_id,
                    redirect_uri=config.chatgpt_redirect_uri,
                    resource=config.resource,
                    http_client=browser_http,
                )

                google_metadata = asyncio.run(google_client.load_provider_metadata())
                google_jwks = asyncio.run(google_client.load_jwks())
                protected_metadata_response = browser_http.get(
                    config.protected_resource_metadata_url
                )
                authorization_metadata_response = browser_http.get(
                    config.authorization_server_metadata_url
                )
                formowl_jwks_response = browser_http.get(config.jwks_uri)
                metadata_and_jwks_verified = _metadata_and_jwks_are_valid(
                    config=config,
                    google_metadata=google_metadata,
                    google_jwks=google_jwks,
                    protected_response=protected_metadata_response,
                    authorization_response=authorization_metadata_response,
                    formowl_jwks_response=formowl_jwks_response,
                )

                mcp_endpoint = f"{formowl_server.base_url}/mcp"
                unauthenticated = asyncio.run(
                    run_official_mcp_client_sequence(
                        mcp_endpoint,
                        bearer=None,
                        tool_calls=(("whoami", {}),),
                    )
                )
                expected_challenge = build_www_authenticate_challenge(
                    config.protected_resource_metadata_url,
                    error="invalid_token",
                    error_description="Authentication required.",
                )
                unauthenticated_challenges_verified = (
                    _listed_tool_names(unauthenticated) >= {"whoami", "open_upload_session"}
                    and _call_is_error(unauthenticated, 0)
                    and _call_challenges(unauthenticated, 0) == [expected_challenge]
                )

                first_authorization = chatgpt.new_authorization()
                sensitive_values.extend(first_authorization.values())
                browser_result = chatgpt.complete_browser_redirects(
                    chatgpt.authorization_url(
                        config.authorization_endpoint,
                        first_authorization,
                    )
                )
                sensitive_values.extend(browser_result.values())
                token_response = chatgpt.exchange_code(
                    config.token_endpoint,
                    code=browser_result["code"],
                    verifier=first_authorization["code_verifier"],
                )
                token_payload = token_response.json()
                access_token = str(token_payload["access_token"])
                sensitive_values.append(access_token)
                authorization_code_pkce_flow_verified = (
                    browser_result.get("state") == first_authorization["state"]
                    and token_response.status == 200
                    and token_payload.get("token_type") == "Bearer"
                    and token_payload.get("resource") == config.resource
                )

                authenticated = asyncio.run(
                    run_official_mcp_client_sequence(
                        mcp_endpoint,
                        bearer=access_token,
                        tool_calls=(
                            ("whoami", {}),
                            (
                                "open_upload_session",
                                {
                                    "intent": "Import a governed mail archive.",
                                    "intended_asset_type": "pst",
                                    "owner_scope_type": "workspace",
                                    "owner_scope_id": workspace_id,
                                    "visibility_scope": "workspace",
                                    "permission_scope": {
                                        "scope_type": "workspace",
                                        "scope_id": workspace_id,
                                        "visibility": "restricted",
                                    },
                                },
                            ),
                            (
                                "open_upload_session",
                                {
                                    "intent": "Attempt another workspace.",
                                    "intended_asset_type": "pst",
                                    "owner_scope_type": "workspace",
                                    "owner_scope_id": "workspace_other",
                                    "visibility_scope": "workspace",
                                },
                            ),
                            (
                                "open_upload_session",
                                {
                                    "intent": "Attempt caller identity forgery.",
                                    "intended_asset_type": "pst",
                                    "requester_user_id": "user_forged",
                                },
                            ),
                        ),
                    )
                )
                whoami = _call_structured_content(authenticated, 0)
                current_user_id = str(whoami.get("user_id", ""))
                allowed_upload = _call_structured_content(authenticated, 1)
                bearer_streamable_http_mcp_verified = (
                    _listed_tool_names(authenticated) >= {"whoami", "open_upload_session"}
                    and not _call_is_error(authenticated, 0)
                    and not _call_is_error(authenticated, 1)
                    and all(
                        entry["status"] not in {301, 302, 303, 307, 308}
                        for entry in formowl_server.request_history
                        if entry["path"] == "/mcp"
                    )
                )
                whoami_verified = (
                    whoami.get("auth_mode") == "google_oidc_oauth"
                    and whoami.get("current_workspace")
                    == {"workspace_id": workspace_id, "role": "member"}
                    and bool(current_user_id)
                )
                allowed_workspace_upload_session_verified = (
                    allowed_upload.get("status") == "ok"
                    and len(upload_recorder.calls) == 1
                    and upload_recorder.calls[0].get("workspace_id") == workspace_id
                    and upload_recorder.calls[0].get("requester_user_id") == current_user_id
                )
                cross_workspace_and_forgery_denied = (
                    _call_is_error(authenticated, 2)
                    and _call_is_error(authenticated, 3)
                    and len(upload_recorder.calls) == 1
                )
                google_identity_mapping_verified = (
                    len(repository.list("external_identities")) == 1
                    and len(repository.list("users")) == 2
                    and repository.get_active_workspace_member(
                        current_user_id,
                        workspace_id,
                    )
                    is not None
                )

                first_session = repository.list("oauth_token_sessions")[0]
                bridge.revoke_token_session(
                    str(first_session["token_session_id"]),
                    revoked_by_user_id=current_user_id,
                    reason_code="user_requested",
                    now=clock.now(),
                )
                revoked_response = chatgpt.mcp_call(
                    config.resource,
                    _mcp_initialize_request("revoked_token_probe"),
                    bearer=access_token,
                )
                revocation_immediate = (
                    revoked_response.status == 401
                    and revoked_response.headers.get("www-authenticate") == expected_challenge
                )

                second_authorization = chatgpt.new_authorization()
                sensitive_values.extend(second_authorization.values())
                second_browser_result = chatgpt.complete_browser_redirects(
                    chatgpt.authorization_url(
                        config.authorization_endpoint,
                        second_authorization,
                    )
                )
                sensitive_values.extend(second_browser_result.values())
                second_token_response = chatgpt.exchange_code(
                    config.token_endpoint,
                    code=second_browser_result["code"],
                    verifier=second_authorization["code_verifier"],
                )
                second_access_token = str(second_token_response.json()["access_token"])
                sensitive_values.append(second_access_token)
                reconnected = asyncio.run(
                    run_official_mcp_client_sequence(
                        mcp_endpoint,
                        bearer=second_access_token,
                        tool_calls=(("whoami", {}),),
                    )
                )
                same_subject_reconnect_verified = (
                    second_token_response.status == 200
                    and _call_structured_content(reconnected, 0).get("user_id") == current_user_id
                    and len(repository.list("external_identities")) == 1
                    and len(repository.list("oauth_token_sessions")) == 2
                )

                negotiated_protocols = {
                    _negotiated_protocol_version(unauthenticated),
                    _negotiated_protocol_version(authenticated),
                    _negotiated_protocol_version(reconnected),
                }
                protocol_negotiation_verified = negotiated_protocols == {
                    _latest_mcp_protocol_version()
                }

                different_subject_isolated = _different_subject_is_denied(
                    fake_google=fake_google,
                    chatgpt=chatgpt,
                    config=config,
                    repository=repository,
                    sensitive_values=sensitive_values,
                )
                negative_case_count = _run_issue20_negative_matrix(
                    clock=clock,
                    fake_google=fake_google,
                    config=config,
                    bridge=bridge,
                    repository=repository,
                    chatgpt=chatgpt,
                    active_access_token=second_access_token,
                    current_user_id=current_user_id,
                    workspace_id=workspace_id,
                    expected_challenge=expected_challenge,
                    sensitive_values=sensitive_values,
                )
                rollback_case_count = _run_issue20_rollback_matrix(
                    clock=clock,
                    config=config,
                    signing_key=signing_key,
                )

            audit_rows = repository.list("audit_log")
            upload_authorization_decisions = [
                row
                for row in audit_rows
                if row.get("action") == "mcp_authorization_allowed"
                and row.get("target_id") == "open_upload_session"
                and row.get("actor_user_id") == current_user_id
                and row.get("workspace_id") == workspace_id
            ]
            upload_authorization_bound = len(
                upload_authorization_decisions
            ) == 1 and upload_recorder.bind_authorization_decision(
                upload_authorization_decisions[0]
            )
            audit_lineage_verified = upload_authorization_bound and _audit_lineage_is_complete(
                audit_rows,
                external_identities=repository.list("external_identities"),
                client_authorizations=repository.list("oauth_client_authorizations"),
                token_sessions=repository.list("oauth_token_sessions"),
                upload_calls=upload_recorder.calls,
                upload_results=upload_recorder.results,
                upload_envelopes=(allowed_upload,),
                upload_audit_rows=upload_recorder.audit_events,
                tool_call_logs=[item.to_dict() for item in semantic_gateway.tool_call_logs],
                expected_user_id=current_user_id,
                expected_client_id=config.chatgpt_client_id,
                expected_workspace_id=workspace_id,
            )
            runtime_logs = captured_logs.rendered()
            runtime_log_leak_scan_verified = not _sensitive_text_violations(
                runtime_logs,
                sensitive_values,
            )
            audit_leak_scan_verified = not _sensitive_text_violations(
                json.dumps(audit_rows, sort_keys=True),
                sensitive_values,
            )
            leak_scan_verified = runtime_log_leak_scan_verified and audit_leak_scan_verified
            http_history = [
                *formowl_server.request_history,
                *browser_http.request_history,
                *google_http.request_history,
            ]

    evidence = {
        "metadata_and_jwks_verified": metadata_and_jwks_verified,
        "protocol_negotiation_verified": protocol_negotiation_verified,
        "unauthenticated_challenges_verified": unauthenticated_challenges_verified,
        "authorization_code_pkce_flow_verified": authorization_code_pkce_flow_verified,
        "google_identity_mapping_verified": google_identity_mapping_verified,
        "bearer_streamable_http_mcp_verified": bearer_streamable_http_mcp_verified,
        "whoami_verified": whoami_verified,
        "allowed_workspace_upload_session_verified": (allowed_workspace_upload_session_verified),
        "cross_workspace_and_forgery_denied": cross_workspace_and_forgery_denied,
        "revocation_immediate": revocation_immediate,
        "same_subject_reconnect_verified": same_subject_reconnect_verified,
        "different_subject_isolated": different_subject_isolated,
        "negative_matrix_verified": negative_case_count >= 20,
        "rollback_matrix_verified": rollback_case_count >= 1,
        "audit_lineage_verified": audit_lineage_verified,
        "runtime_log_leak_scan_verified": runtime_log_leak_scan_verified,
        "leak_scan_verified": leak_scan_verified,
        "scenario_contract_hash": sha256_json(
            {
                "flow": [
                    "metadata",
                    "unauthenticated_discovery",
                    "google_authorization_code_pkce",
                    "authenticated_mcp",
                    "workspace_denial",
                    "revocation",
                    "same_subject_reconnect",
                    "negative_matrix",
                    "rollback_matrix",
                ],
                "negotiated_protocol_hash": sha256_json(sorted(negotiated_protocols)),
                "supported_protocol_matrix_hash": sha256_json(_supported_mcp_protocol_versions()),
                "transport": "streamable_http_stateless_json",
            }
        ),
        "negotiated_protocol_version_hash": sha256_json(sorted(negotiated_protocols)),
        "supported_protocol_matrix_hash": sha256_json(_supported_mcp_protocol_versions()),
        "http_exchange_shape_hash": sha256_json(http_history),
        "audit_lineage_shape_hash": sha256_json(
            {
                "oauth_audit_rows": [
                    {
                        "action": row.get("action"),
                        "status": row.get("status"),
                        "reason_code": row.get("reason_code"),
                    }
                    for row in audit_rows
                ],
                "synthetic_upload_audit_rows": [
                    {
                        "action": row.get("action"),
                        "status": row.get("status"),
                        "reason_code": row.get("reason_code"),
                        "authorization_bound": bool(
                            row.get("authorization_request_id")
                            and row.get("authorization_tool_call_id")
                        ),
                    }
                    for row in upload_recorder.audit_events
                ],
                "semantic_tool_log_count": len(semantic_gateway.tool_call_logs),
            }
        ),
        "http_exchange_count": len(http_history),
        "negative_case_count": negative_case_count,
        "rollback_case_count": rollback_case_count,
        "audit_event_count": len(audit_rows),
    }
    assert_safe_harness_report(evidence)
    return evidence


def _metadata_and_jwks_are_valid(
    *,
    config: Any,
    google_metadata: Mapping[str, Any],
    google_jwks: Mapping[str, Any],
    protected_response: HttpResponse,
    authorization_response: HttpResponse,
    formowl_jwks_response: HttpResponse,
) -> bool:
    if any(
        response.status != 200
        for response in (
            protected_response,
            authorization_response,
            formowl_jwks_response,
        )
    ):
        return False
    protected = protected_response.json()
    authorization = authorization_response.json()
    formowl_jwks = formowl_jwks_response.json()
    expected_google = {
        "issuer": "https://accounts.google.com",
        "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_endpoint": "https://oauth2.googleapis.com/token",
        "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
    }
    return (
        all(google_metadata.get(key) == value for key, value in expected_google.items())
        and _public_jwks_only(google_jwks)
        and protected.get("resource") == config.resource
        and protected.get("authorization_servers") == [config.issuer]
        and authorization.get("issuer") == config.issuer
        and authorization.get("authorization_endpoint") == config.authorization_endpoint
        and authorization.get("token_endpoint") == config.token_endpoint
        and authorization.get("jwks_uri") == config.jwks_uri
        and authorization.get("code_challenge_methods_supported") == ["S256"]
        and _public_jwks_only(formowl_jwks)
    )


def _public_jwks_only(value: Mapping[str, Any]) -> bool:
    keys = value.get("keys")
    if not isinstance(keys, list) or not keys:
        return False
    private_fields = {"d", "p", "q", "dp", "dq", "qi", "oth"}
    return all(
        isinstance(key, dict)
        and key.get("kty") == "RSA"
        and key.get("alg") == "RS256"
        and not (set(key) & private_fields)
        for key in keys
    )


def _listed_tool_names(sequence: Mapping[str, Any]) -> set[str]:
    listed = sequence.get("tools")
    if not isinstance(listed, Mapping):
        return set()
    tools = listed.get("tools")
    if not isinstance(tools, list):
        return set()
    return {
        str(tool["name"])
        for tool in tools
        if isinstance(tool, Mapping) and isinstance(tool.get("name"), str)
    }


def _call_result(sequence: Mapping[str, Any], index: int) -> dict[str, Any]:
    calls = sequence.get("calls")
    if not isinstance(calls, list) or not 0 <= index < len(calls):
        return {}
    call = calls[index]
    if not isinstance(call, Mapping):
        return {}
    result = call.get("result")
    return dict(result) if isinstance(result, Mapping) else {}


def _call_is_error(sequence: Mapping[str, Any], index: int) -> bool:
    result = _call_result(sequence, index)
    return result.get("isError", result.get("is_error")) is True


def _call_structured_content(sequence: Mapping[str, Any], index: int) -> dict[str, Any]:
    result = _call_result(sequence, index)
    value = result.get("structuredContent", result.get("structured_content"))
    return dict(value) if isinstance(value, Mapping) else {}


def _call_challenges(sequence: Mapping[str, Any], index: int) -> list[str]:
    result = _call_result(sequence, index)
    meta = result.get("_meta", result.get("meta"))
    if not isinstance(meta, Mapping):
        return []
    values = meta.get("mcp/www_authenticate")
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        return []
    return list(values)


def _mcp_initialize_request(request_id: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "protocolVersion": _latest_mcp_protocol_version(),
            "capabilities": {},
            "clientInfo": {
                "name": "formowl-issue20-harness",
                "version": "1.0.0",
            },
        },
    }


def _negotiated_protocol_version(sequence: Mapping[str, Any]) -> str:
    initialized = sequence.get("initialize")
    if not isinstance(initialized, Mapping):
        return ""
    value = initialized.get("protocolVersion", initialized.get("protocol_version"))
    return value if isinstance(value, str) else ""


def _latest_mcp_protocol_version() -> str:
    from mcp.shared.version import LATEST_PROTOCOL_VERSION

    return str(LATEST_PROTOCOL_VERSION)


def _supported_mcp_protocol_versions() -> list[str]:
    from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS

    return [str(value) for value in SUPPORTED_PROTOCOL_VERSIONS]


def _different_subject_is_denied(
    *,
    fake_google: FakeGoogleOidcProvider,
    chatgpt: SimulatedChatGptOAuthClient,
    config: Any,
    repository: TransactionAwareMemoryRepository,
    sensitive_values: list[str],
) -> bool:
    original_account = fake_google.account
    original_identity_count = len(repository.list("external_identities"))
    try:
        fake_google.set_account(
            FakeGoogleAccount(
                subject="google-subject-independent",
                email=original_account.email,
                email_verified=True,
            )
        )
        authorization = chatgpt.new_authorization()
        sensitive_values.extend(authorization.values())
        first = chatgpt.http.get(
            chatgpt.authorization_url(config.authorization_endpoint, authorization)
        )
        if first.status != 302 or not first.location:
            return False
        sensitive_values.extend(_query_values(first.location))
        second = chatgpt.http.get(first.location)
        if second.status != 302 or not second.location:
            return False
        sensitive_values.extend(_query_values(second.location))
        mutable_snapshot = repository.mutable_state_snapshot_bytes()
        audit_count = repository.audit_event_count
        third = chatgpt.http.get(second.location)
        repository.assert_mutable_state_unchanged(mutable_snapshot)
        return (
            third.status == 403
            and repository.audit_event_count == audit_count + 1
            and len(repository.list("external_identities")) == original_identity_count
        )
    finally:
        fake_google.set_account(original_account)


def _query_values(url: str) -> list[str]:
    values: list[str] = []
    for items in parse_qs(urlparse(url).query, keep_blank_values=True).values():
        values.extend(str(item) for item in items if item)
    return values


def _audit_lineage_is_complete(
    rows: Sequence[Mapping[str, Any]],
    *,
    external_identities: Sequence[Mapping[str, Any]],
    client_authorizations: Sequence[Mapping[str, Any]],
    token_sessions: Sequence[Mapping[str, Any]],
    upload_calls: Sequence[Mapping[str, Any]],
    upload_results: Sequence[Mapping[str, Any]],
    upload_envelopes: Sequence[Mapping[str, Any]],
    upload_audit_rows: Sequence[Mapping[str, Any]],
    tool_call_logs: Sequence[Mapping[str, Any]],
    expected_user_id: str,
    expected_client_id: str,
    expected_workspace_id: str,
) -> bool:
    """Prove the deterministic identity-to-tool lineage without a production claim."""

    expected_actions = {
        "oauth_invitation_create",
        "oauth_authorization_started",
        "oauth_external_identity_created",
        "oauth_invitation_accepted",
        "google_authentication_succeeded",
        "oauth_authorization_code_issued",
        "oauth_token_session_issued",
        "mcp_authorization_allowed",
        "mcp_authorization_denied",
        "oauth_token_session_revoked",
    }
    actions = {str(row.get("action", "")) for row in rows}
    if not expected_actions <= actions:
        return False
    if not all(
        isinstance(row.get("reason_code"), str)
        and bool(row.get("reason_code"))
        and isinstance(row.get("timestamp"), str)
        and bool(row.get("timestamp"))
        for row in rows
    ):
        return False

    invitation_rows = [row for row in rows if row.get("action") == "oauth_invitation_create"]
    if len(invitation_rows) != 1:
        return False
    invitation_row = invitation_rows[0]
    invitation_metadata = invitation_row.get("metadata")
    if (
        invitation_row.get("actor_type") != "service"
        or invitation_row.get("actor_user_id") is not None
        or not isinstance(invitation_row.get("actor_service_id"), str)
        or not invitation_row.get("actor_service_id")
        or invitation_row.get("workspace_id") != expected_workspace_id
        or invitation_row.get("status") != "ok"
        or invitation_row.get("reason_code") != "invitation_created"
        or not isinstance(invitation_metadata, Mapping)
        or invitation_metadata.get("event_stage") != "invitation"
        or invitation_metadata.get("lineage_source") != "owner_approval"
        or not isinstance(invitation_metadata.get("approval_user_id"), str)
        or not invitation_metadata.get("approval_user_id")
    ):
        return False

    identities = [dict(item) for item in external_identities]
    authorizations = [dict(item) for item in client_authorizations]
    sessions = [dict(item) for item in token_sessions]
    if len(identities) != 1 or len(authorizations) != 1 or len(sessions) != 2:
        return False
    identity = identities[0]
    external_identity_id = identity.get("external_identity_id")
    if (
        not isinstance(external_identity_id, str)
        or not external_identity_id
        or identity.get("provider") != "google"
        or identity.get("user_id") != expected_user_id
        or identity.get("status") != "active"
    ):
        return False
    authorization = authorizations[0]
    client_authorization_id = authorization.get("oauth_client_authorization_id")
    if (
        not isinstance(client_authorization_id, str)
        or not client_authorization_id
        or authorization.get("client_id") != expected_client_id
        or authorization.get("external_identity_id") != external_identity_id
        or authorization.get("user_id") != expected_user_id
        or authorization.get("default_workspace_id") != expected_workspace_id
        or authorization.get("revoked_at") is not None
    ):
        return False

    token_session_ids: set[str] = set()
    for session in sessions:
        token_session_id = session.get("token_session_id")
        if (
            not isinstance(token_session_id, str)
            or not token_session_id
            or token_session_id in token_session_ids
            or session.get("user_id") != expected_user_id
            or session.get("external_identity_id") != external_identity_id
            or session.get("oauth_client_authorization_id") != client_authorization_id
            or session.get("client_id") != expected_client_id
            or session.get("current_workspace_id") != expected_workspace_id
        ):
            return False
        token_session_ids.add(token_session_id)
    revoked_sessions = [item for item in sessions if item.get("revoked_at") is not None]
    if len(revoked_sessions) != 2:
        return False

    def identity_linked(row: Mapping[str, Any]) -> bool:
        return (
            row.get("actor_user_id") == expected_user_id
            and row.get("external_identity_id") == external_identity_id
            and row.get("oauth_client_id") == expected_client_id
            and row.get("workspace_id") == expected_workspace_id
        )

    for action in (
        "oauth_external_identity_created",
        "oauth_invitation_accepted",
        "google_authentication_succeeded",
        "oauth_authorization_code_issued",
    ):
        matching = [row for row in rows if row.get("action") == action]
        if not matching or not all(identity_linked(row) for row in matching):
            return False
    authorization_starts = [
        row for row in rows if row.get("action") == "oauth_authorization_started"
    ]
    if len(authorization_starts) < 2 or not all(
        row.get("oauth_client_id") == expected_client_id
        and row.get("target_id") == row.get("session_id")
        for row in authorization_starts
    ):
        return False

    for token_session_id in token_session_ids:
        issued = [
            row
            for row in rows
            if row.get("action") == "oauth_token_session_issued"
            and row.get("oauth_token_session_id") == token_session_id
        ]
        if len(issued) != 1 or not _audit_token_link_matches(
            issued[0],
            token_session_id=token_session_id,
            user_id=expected_user_id,
            external_identity_id=external_identity_id,
            client_id=expected_client_id,
            workspace_id=expected_workspace_id,
        ):
            return False
    for revoked_session in revoked_sessions:
        revoked_token_session_id = str(revoked_session["token_session_id"])
        revocations = [
            row
            for row in rows
            if row.get("action") == "oauth_token_session_revoked"
            and row.get("oauth_token_session_id") == revoked_token_session_id
        ]
        if len(revocations) != 1 or not _audit_token_link_matches(
            revocations[0],
            token_session_id=revoked_token_session_id,
            user_id=expected_user_id,
            external_identity_id=external_identity_id,
            client_id=expected_client_id,
            workspace_id=expected_workspace_id,
        ):
            return False

    principal_decisions = [
        row
        for row in rows
        if row.get("actor_user_id") == expected_user_id
        and row.get("reason_code") in {"tool_authorized", "invalid_tool_arguments"}
    ]
    if not principal_decisions:
        return False
    decision_pairs: set[tuple[str, str]] = set()
    for row in principal_decisions:
        request_id = row.get("request_id")
        tool_call_id = row.get("tool_call_id")
        allowed = row.get("action") == "mcp_authorization_allowed"
        if (
            row.get("action") not in {"mcp_authorization_allowed", "mcp_authorization_denied"}
            or row.get("target_type") != "mcp_tool"
            or row.get("external_identity_id") != external_identity_id
            or row.get("oauth_client_id") != expected_client_id
            or row.get("oauth_token_session_id") not in token_session_ids
            or row.get("session_id") != row.get("oauth_token_session_id")
            or row.get("workspace_id") != expected_workspace_id
            or not isinstance(request_id, str)
            or not request_id
            or not isinstance(tool_call_id, str)
            or not tool_call_id
            or request_id == tool_call_id
            or (request_id, tool_call_id) in decision_pairs
            or row.get("status") != ("ok" if allowed else "permission_denied")
            or not isinstance(row.get("metadata"), Mapping)
            or row["metadata"].get("workspace_decision") != ("allowed" if allowed else "denied")
        ):
            return False
        decision_pairs.add((request_id, tool_call_id))

    allowed_whoami = [
        row
        for row in principal_decisions
        if row.get("action") == "mcp_authorization_allowed" and row.get("target_id") == "whoami"
    ]
    allowed_uploads = [
        row
        for row in principal_decisions
        if row.get("action") == "mcp_authorization_allowed"
        and row.get("target_id") == "open_upload_session"
    ]
    denied_uploads = [
        row
        for row in principal_decisions
        if row.get("action") == "mcp_authorization_denied"
        and row.get("target_id") == "open_upload_session"
        and row.get("reason_code") == "invalid_tool_arguments"
    ]
    if len(allowed_whoami) < 2 or len(allowed_uploads) != 1 or len(denied_uploads) < 2:
        return False

    if (
        len(upload_calls) != 1
        or len(upload_results) != 1
        or len(upload_envelopes) != 1
        or len(upload_audit_rows) != 1
    ):
        return False
    upload_call = upload_calls[0]
    upload_result = upload_results[0]
    upload_envelope = upload_envelopes[0]
    upload_audit = upload_audit_rows[0]
    upload_decision = allowed_uploads[0]
    if (
        upload_call.get("requester_user_id") != expected_user_id
        or upload_call.get("workspace_id") != expected_workspace_id
        or upload_call.get("owner_scope_type") != "workspace"
        or upload_call.get("owner_scope_id") != expected_workspace_id
        or upload_call.get("session_id") != upload_decision.get("oauth_token_session_id")
        or upload_result.get("status") != "ok"
        or upload_envelope.get("result_type") != "upload_session_request"
        or upload_envelope.get("status") != "ok"
        or upload_envelope.get("data") != upload_result
        or upload_result.get("audit_ref") != upload_audit.get("audit_log_id")
        or upload_result.get("upload_session_id") != upload_audit.get("target_id")
        or upload_audit.get("action") != "upload_session_created"
        or upload_audit.get("actor_user_id") != expected_user_id
        or upload_audit.get("session_id") != upload_call.get("session_id")
        or upload_audit.get("workspace_id") != expected_workspace_id
        or upload_audit.get("status") != "ok"
        or upload_audit.get("authorization_request_id") != upload_decision.get("request_id")
        or upload_audit.get("authorization_tool_call_id") != upload_decision.get("tool_call_id")
        or upload_audit.get("evidence_mode") != "deterministic_fake_upload_recorder"
    ):
        return False
    matching_tool_logs = [
        row
        for row in tool_call_logs
        if row.get("tool_name") == "open_upload_session"
        and row.get("audit_log_id") == upload_audit.get("audit_log_id")
        and row.get("status") == "ok"
        and row.get("arguments_hash") == sha256_json(upload_call)
        and row.get("response_hash") == sha256_json(upload_envelope)
    ]
    return len(matching_tool_logs) == 1


def _audit_token_link_matches(
    row: Mapping[str, Any],
    *,
    token_session_id: str,
    user_id: str,
    external_identity_id: str,
    client_id: str,
    workspace_id: str,
) -> bool:
    return (
        row.get("actor_user_id") == user_id
        and row.get("target_id") == token_session_id
        and row.get("session_id") == token_session_id
        and row.get("workspace_id") == workspace_id
        and row.get("external_identity_id") == external_identity_id
        and row.get("oauth_client_id") == client_id
        and row.get("oauth_token_session_id") == token_session_id
    )


def _sensitive_text_violations(text: str, sensitive_values: Sequence[str]) -> list[str]:
    lowered = text.lower()
    violations = [
        "known_oauth_value"
        for value in sensitive_values
        if isinstance(value, str) and len(value) >= 8 and value.lower() in lowered
    ]
    for name, pattern in (
        ("jwt", _JWT_RE),
        ("email", _EMAIL_RE),
        ("bearer", _BEARER_RE),
        ("raw_path", _RAW_PATH_RE),
        ("sql", _SQL_RE),
    ):
        if pattern.search(text):
            violations.append(name)
    return sorted(set(violations))


def _run_issue20_negative_matrix(
    *,
    clock: FakeClock,
    fake_google: FakeGoogleOidcProvider,
    config: Any,
    bridge: Any,
    repository: TransactionAwareMemoryRepository,
    chatgpt: SimulatedChatGptOAuthClient,
    active_access_token: str,
    current_user_id: str,
    workspace_id: str,
    expected_challenge: str,
    sensitive_values: list[str],
) -> int:
    """Exercise fail-closed OAuth, OIDC, HTTP, and live-authorization denials."""

    from formowl_auth.models import OAuthAccessDenied

    case_count = 0

    def expect_denial(
        operation: Callable[[], Any],
        *,
        reason_code: str,
        mutable_snapshot: bytes | None = None,
    ) -> None:
        nonlocal case_count
        snapshot = mutable_snapshot or repository.mutable_state_snapshot_bytes()
        try:
            operation()
        except OAuthAccessDenied as exc:
            if exc.reason_code != reason_code:
                raise AssertionError(
                    f"negative matrix expected {reason_code}, received {exc.reason_code}"
                ) from exc
        else:
            raise AssertionError(f"negative matrix case did not deny: {reason_code}")
        repository.assert_mutable_state_unchanged(snapshot)
        case_count += 1

    valid_authorization = {
        "client_id": config.chatgpt_client_id,
        "redirect_uri": config.chatgpt_redirect_uri,
        "response_type": "code",
        "resource": config.resource,
        "scope": "formowl.use",
        "state": "matrix-client-state",
        "code_challenge": "A" * 43,
        "code_challenge_method": "S256",
    }
    authorization_cases = (
        ("client_id", "other-client", "oauth_client_invalid"),
        ("redirect_uri", "https://attacker.example/callback", "redirect_uri_invalid"),
        ("response_type", "token", "response_type_invalid"),
        ("resource", "https://formowl.example.test/other", "resource_invalid"),
        ("scope", "formowl.admin", "scope_invalid"),
        ("code_challenge_method", "plain", "pkce_method_invalid"),
        ("code_challenge", "short", "pkce_challenge_invalid"),
        ("state", "s" * 2049, "client_state_invalid"),
    )
    for field_name, invalid_value, reason_code in authorization_cases:
        request = {**valid_authorization, field_name: invalid_value}
        expect_denial(
            lambda request=request: bridge.validate_authorization_request(request),
            reason_code=reason_code,
        )
    missing = dict(valid_authorization)
    missing.pop("state")
    expect_denial(
        lambda: bridge.validate_authorization_request(missing),
        reason_code="authorization_parameter_missing",
    )

    expect_denial(
        lambda: bridge.authenticate_access_token(
            "not-a-jwt",
            required_scope="formowl.use",
            resource=config.resource,
            now=clock.now(),
        ),
        reason_code="token_shape_invalid",
    )
    expect_denial(
        lambda: bridge.authenticate_access_token(
            active_access_token,
            required_scope="formowl.admin",
            resource=config.resource,
            now=clock.now(),
        ),
        reason_code="required_scope_missing",
    )
    expect_denial(
        lambda: bridge.authenticate_access_token(
            active_access_token,
            required_scope="formowl.use",
            resource=f"{config.issuer}/other-resource",
            now=clock.now(),
        ),
        reason_code="token_resource_invalid",
    )
    expect_denial(
        lambda: bridge.authenticate_access_token(
            active_access_token,
            required_scope="formowl.use",
            resource=config.resource,
            now=clock.now() + timedelta(seconds=config.access_token_lifetime_seconds + 10),
        ),
        reason_code="token_expired",
    )

    principal = bridge.authenticate_access_token(
        active_access_token,
        required_scope="formowl.use",
        resource=config.resource,
        now=clock.now(),
    )
    member_key = repository._workspace_member_key(current_user_id, workspace_id)
    member_payload = repository.get("workspace_members", member_key)
    if member_payload is None:
        raise AssertionError("negative matrix requires the active workspace membership")
    repository.delete(
        "workspace_members",
        member_key,
        operation="negative_matrix_remove_membership",
    )
    try:
        expect_denial(
            lambda: bridge.resolve_actor_context(principal, now=clock.now()),
            reason_code="workspace_membership_inactive",
        )
    finally:
        repository.put(
            "workspace_members",
            member_key,
            member_payload,
            operation="negative_matrix_restore_membership",
        )

    user_payload = repository.get("users", current_user_id)
    if user_payload is None:
        raise AssertionError("negative matrix requires the active FormOwl user")
    repository.put(
        "users",
        current_user_id,
        {**user_payload, "status": "disabled"},
        operation="negative_matrix_disable_user",
    )
    try:
        expect_denial(
            lambda: bridge.resolve_actor_context(principal, now=clock.now()),
            reason_code="formowl_user_disabled",
        )
    finally:
        repository.put(
            "users",
            current_user_id,
            user_payload,
            operation="negative_matrix_restore_user",
        )

    identity_payload = repository.get("external_identities", principal.external_identity_id)
    if identity_payload is None:
        raise AssertionError("negative matrix requires the active external identity")
    repository.put(
        "external_identities",
        principal.external_identity_id,
        {**identity_payload, "status": "disabled"},
        operation="negative_matrix_disable_identity",
    )
    try:
        expect_denial(
            lambda: bridge.resolve_actor_context(principal, now=clock.now()),
            reason_code="external_identity_disabled",
        )
    finally:
        repository.put(
            "external_identities",
            principal.external_identity_id,
            identity_payload,
            operation="negative_matrix_restore_identity",
        )

    def google_claim_denial(
        *,
        claim_overrides: Mapping[str, Any] | None = None,
        signing_key: DeterministicRsaKey | None = None,
    ) -> None:
        nonlocal case_count
        authorization = chatgpt.new_authorization()
        sensitive_values.extend(authorization.values())
        first = chatgpt.http.get(
            chatgpt.authorization_url(config.authorization_endpoint, authorization)
        )
        if first.status != 302 or not first.location:
            raise AssertionError("negative matrix authorization did not reach fake Google")
        sensitive_values.extend(_query_values(first.location))
        if claim_overrides is not None:
            fake_google.next_claim_overrides = dict(claim_overrides)
        if signing_key is not None:
            fake_google.next_signing_key = signing_key
        second = chatgpt.http.get(first.location)
        if second.status != 302 or not second.location:
            raise AssertionError("negative matrix fake Google did not return a callback")
        sensitive_values.extend(_query_values(second.location))
        mutable_snapshot = repository.mutable_state_snapshot_bytes()
        response = chatgpt.http.get(second.location)
        if response.status != 400 or response.json() != {"error": "access_denied"}:
            raise AssertionError("negative Google claim was not rejected by the HTTP callback")
        repository.assert_mutable_state_unchanged(mutable_snapshot)
        if _sensitive_text_violations(response.body.decode("utf-8"), sensitive_values):
            raise AssertionError("negative Google callback reflected sensitive material")
        case_count += 1

    now_epoch = clock.timestamp()
    google_claim_denial(claim_overrides={"iss": "https://issuer.invalid"})
    google_claim_denial(claim_overrides={"aud": "wrong-google-client"})
    google_claim_denial(claim_overrides={"exp": now_epoch - 1, "iat": now_epoch - 60})
    google_claim_denial(claim_overrides={"nonce": "wrong-nonce"})
    google_claim_denial(claim_overrides={"email_verified": False})
    google_claim_denial(claim_overrides={"sub": ""})
    google_claim_denial(
        claim_overrides={
            "iat": now_epoch + 600,
            "nbf": now_epoch + 600,
            "exp": now_epoch + 900,
        }
    )
    google_claim_denial(
        signing_key=DeterministicRsaKey.generate(
            "formowl-issue20-negative-unknown-google-key",
            kid="unknown-google-key",
        )
    )

    duplicate_authorize = (
        chatgpt.authorization_url(
            config.authorization_endpoint,
            chatgpt.new_authorization(),
        )
        + "&client_id=duplicate-client"
    )
    mutable_snapshot = repository.mutable_state_snapshot_bytes()
    duplicate_response = chatgpt.http.get(duplicate_authorize)
    if duplicate_response.status != 400 or duplicate_response.json() != {
        "error": "invalid_request"
    }:
        raise AssertionError("duplicate authorization parameter was not rejected")
    repository.assert_mutable_state_unchanged(mutable_snapshot)
    case_count += 1

    mutable_snapshot = repository.mutable_state_snapshot_bytes()
    token_json_response = chatgpt.http.post_json(config.token_endpoint, {"code": "unsafe"})
    if token_json_response.status != 400 or token_json_response.json() != {
        "error": "invalid_request"
    }:
        raise AssertionError("non-form token request was not rejected")
    repository.assert_mutable_state_unchanged(mutable_snapshot)
    case_count += 1

    malformed_bearer = chatgpt.http.post_json(
        config.resource,
        _mcp_initialize_request("negative_matrix_bad_bearer"),
        headers={
            "Authorization": "Basic invalid",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": _latest_mcp_protocol_version(),
        },
    )
    if (
        malformed_bearer.status != 401
        or malformed_bearer.headers.get("www-authenticate") != expected_challenge
    ):
        raise AssertionError("malformed bearer request did not fail with the canonical challenge")
    case_count += 1

    bridge.revoke_token_session(
        principal.token_session_id,
        revoked_by_user_id=current_user_id,
        reason_code="negative_matrix_complete",
        now=clock.now(),
    )
    expect_denial(
        lambda: bridge.authenticate_access_token(
            active_access_token,
            required_scope="formowl.use",
            resource=config.resource,
            now=clock.now(),
        ),
        reason_code="token_session_revoked",
    )
    return case_count


class _MatrixGoogleClient:
    def __init__(self, identity: Any) -> None:
        self.identity = identity
        self.last_nonce: str | None = None
        self.last_state: str | None = None

    def build_authorization_url(self, *, google_state: str, google_nonce: str) -> str:
        self.last_state = google_state
        self.last_nonce = google_nonce
        return "https://accounts.google.test/authorize?" + urlencode(
            {"state": google_state, "nonce": google_nonce}
        )

    async def authenticate_code(
        self,
        google_code: str,
        *,
        expected_nonce_hash: str,
        now: datetime,
    ) -> Any:
        from formowl_auth.security import hash_oauth_value

        del google_code, now
        if self.last_nonce is None or expected_nonce_hash != hash_oauth_value(
            "google_nonce",
            self.last_nonce,
        ):
            raise AssertionError("rollback matrix nonce binding is invalid")
        return self.identity


class _RollbackMatrixFixture:
    def __init__(self, *, config: Any, signing_key: Any, seed: str) -> None:
        from formowl_auth.google_oidc import GoogleIdentity
        from formowl_auth.service import FormOwlOAuthBridge
        from formowl_auth.tokens import FormOwlSigningKeySet, FormOwlTokenCodec
        from formowl_contract import User, WorkspaceMember

        self.clock = FakeClock()
        self.repository = TransactionAwareMemoryRepository()
        self.rng = DeterministicRng(seed)
        self.config = config
        self.verifier = "v" * 43
        self.operator_service_id = "operator_service_rollback"
        self.google_client = _MatrixGoogleClient(
            GoogleIdentity(
                issuer="https://accounts.google.com",
                subject="rollback-google-subject",
                email="rollback-user@example.test",
                email_verified=True,
                display_name="Rollback User",
            )
        )
        self.bridge = FormOwlOAuthBridge(
            config=config,
            repository=self.repository,
            google_client=self.google_client,
            token_codec=FormOwlTokenCodec(
                issuer=config.issuer,
                client_id=config.chatgpt_client_id,
                key_set=FormOwlSigningKeySet([signing_key]),
                lifetime_seconds=config.access_token_lifetime_seconds,
                clock_skew_seconds=config.clock_skew_seconds,
            ),
            random_bytes=self.rng.bytes,
            owner_bootstrap_operator_authorizer=(
                lambda candidate: candidate == self.operator_service_id
            ),
        )
        with self.repository.transaction() as unit:
            self.repository.insert_user(
                User(
                    user_id="rollback-owner",
                    display_name="Rollback Owner",
                    email="rollback-owner@example.test",
                    status="active",
                    created_at=self.clock.now_iso(),
                )
            )
            self.repository.insert_workspace_member(
                WorkspaceMember(
                    workspace_id="rollback-workspace",
                    user_id="rollback-owner",
                    role="owner",
                ),
                created_at=self.clock.now_iso(),
            )
            unit.commit()

    def provision_invitation(self) -> None:
        self.bridge.provision_invitation(
            email="rollback-user@example.test",
            workspace_id="rollback-workspace",
            role="member",
            invited_by_user_id="rollback-owner",
            operator_service_id=self.operator_service_id,
            expires_at=self.clock.now() + timedelta(hours=1),
            now=self.clock.now(),
        )

    def start_authorization(self) -> str:
        from formowl_auth.security import pkce_s256_challenge

        self.bridge.start_authorization(
            {
                "client_id": self.config.chatgpt_client_id,
                "redirect_uri": self.config.chatgpt_redirect_uri,
                "response_type": "code",
                "resource": self.config.resource,
                "scope": "formowl.use",
                "state": "rollback-client-state",
                "code_challenge": pkce_s256_challenge(self.verifier),
                "code_challenge_method": "S256",
            },
            now=self.clock.now(),
        )
        if self.google_client.last_state is None:
            raise AssertionError("rollback matrix authorization state was not generated")
        return self.google_client.last_state

    def complete_callback(self, state: str) -> str:
        result = asyncio.run(
            self.bridge.complete_google_callback(
                google_state=state,
                google_code="rollback-google-code",
                now=self.clock.now(),
            )
        )
        values = parse_qs(urlparse(result["redirect_uri"]).query)
        return values["code"][0]

    def exchange_code(self, code: str) -> dict[str, Any]:
        return self.bridge.exchange_authorization_code(
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": self.config.chatgpt_client_id,
                "redirect_uri": self.config.chatgpt_redirect_uri,
                "code_verifier": self.verifier,
                "resource": self.config.resource,
            },
            now=self.clock.now(),
        )


def _run_issue20_rollback_matrix(
    *,
    clock: FakeClock,
    config: Any,
    signing_key: Any,
) -> int:
    """Inject failure at every durable write in each state-changing OAuth stage."""

    del clock
    case_count = 0

    def exercise_stage(
        *,
        stage: str,
        prepare: Callable[[_RollbackMatrixFixture], Callable[[], Any]],
        wrapped_failure_reason: str | None = None,
    ) -> None:
        nonlocal case_count
        baseline = _RollbackMatrixFixture(
            config=config,
            signing_key=signing_key,
            seed=f"rollback-baseline-{stage}",
        )
        baseline_operation = prepare(baseline)
        baseline.repository.write_operations.clear()
        baseline.repository.inject_failure_at(None)
        baseline_operation()
        write_count = len(baseline.repository.write_operations)
        if write_count < 1:
            raise AssertionError(f"rollback stage has no durable writes: {stage}")
        for write_index in range(1, write_count + 1):
            fixture = _RollbackMatrixFixture(
                config=config,
                signing_key=signing_key,
                seed=f"rollback-{stage}-{write_index}",
            )
            operation = prepare(fixture)
            snapshot = fixture.repository.snapshot_bytes()
            fixture.repository.write_operations.clear()
            fixture.repository.inject_failure_at(write_index)
            try:
                operation()
            except FailureInjected:
                pass
            except Exception as error:
                if not (
                    wrapped_failure_reason is not None
                    and getattr(error, "error", None) == "server_error"
                    and getattr(error, "reason_code", None) == wrapped_failure_reason
                    and getattr(error, "http_status", None) == 500
                ):
                    raise
            else:
                raise AssertionError(
                    f"rollback failure injection did not fire: {stage}:{write_index}"
                )
            fixture.repository.assert_unchanged(snapshot)
            case_count += 1

    exercise_stage(
        stage="invitation",
        prepare=lambda fixture: fixture.provision_invitation,
        wrapped_failure_reason="invitation_persistence_unavailable",
    )

    def prepare_authorization(fixture: _RollbackMatrixFixture) -> Callable[[], Any]:
        fixture.provision_invitation()
        return fixture.start_authorization

    exercise_stage(stage="authorization", prepare=prepare_authorization)

    def prepare_callback(fixture: _RollbackMatrixFixture) -> Callable[[], Any]:
        fixture.provision_invitation()
        state = fixture.start_authorization()
        return lambda: fixture.complete_callback(state)

    exercise_stage(stage="callback", prepare=prepare_callback)

    def prepare_token(fixture: _RollbackMatrixFixture) -> Callable[[], Any]:
        fixture.provision_invitation()
        code = fixture.complete_callback(fixture.start_authorization())
        return lambda: fixture.exchange_code(code)

    exercise_stage(stage="token", prepare=prepare_token)

    def prepare_revocation(fixture: _RollbackMatrixFixture) -> Callable[[], Any]:
        fixture.provision_invitation()
        token = fixture.exchange_code(fixture.complete_callback(fixture.start_authorization()))
        principal = fixture.bridge.authenticate_access_token(
            str(token["access_token"]),
            required_scope="formowl.use",
            resource=fixture.config.resource,
            now=fixture.clock.now(),
        )
        return lambda: fixture.bridge.revoke_token_session(
            principal.token_session_id,
            revoked_by_user_id=principal.user_id,
            reason_code="rollback_matrix",
            now=fixture.clock.now(),
        )

    exercise_stage(stage="revocation", prepare=prepare_revocation)
    return case_count


def load_function_harness_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError("function harness manifest must be an object")
    return value


def generate_function_harness_manifest_skeleton(
    *,
    root: Path = ROOT,
    base_commit: str = ISSUE20_BASE_COMMIT,
) -> dict[str, Any]:
    """Build a deterministic pending schema-v2 manifest without writing it."""

    if base_commit != ISSUE20_BASE_COMMIT:
        raise AssertionError("function harness generation requires the locked issue #20 base")
    bindings = changed_scoped_function_bindings(
        root,
        base_commit=base_commit,
        include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
    )
    functions: list[dict[str, Any]] = []
    for module, qualname in sorted(bindings):
        identity = f"{module}.{qualname}"
        source_binding = dict(bindings[(module, qualname)])
        categories = {
            category: {
                "test_ids": [],
                "not_applicable_reason": None,
                "pending_reason": (
                    f"{identity} is pending {category.replace('_', ' ')} evidence for current "
                    f"source diff {source_binding['diff_sha256']}; add a canonical executable "
                    "test or precise category-specific probe after the production diff is frozen."
                ),
            }
            for category in REQUIRED_HARNESS_CATEGORIES
        }
        functions.append(
            {
                "module": module,
                "qualname": qualname,
                "status": "pending",
                "source_binding": source_binding,
                "categories": categories,
                "test_ids": [],
            }
        )
    return {
        "schema_version": 2,
        "issue_number": 20,
        "base_commit": base_commit,
        "scope": {
            "include_globs": list(ISSUE20_FUNCTION_SCOPE_GLOBS),
            "exclusion_rules": list(ISSUE20_FUNCTION_EXCLUSION_RULES),
        },
        "required_categories": list(REQUIRED_HARNESS_CATEGORIES),
        "functions": functions,
    }


def validate_function_harness_manifest(
    manifest: Mapping[str, Any],
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    blockers: list[str] = []
    expected_top_level = {
        "schema_version",
        "issue_number",
        "base_commit",
        "scope",
        "required_categories",
        "functions",
    }
    _check_exact_keys(manifest, expected_top_level, "manifest", blockers)
    if manifest.get("schema_version") != 2:
        blockers.append("manifest.schema_version must be 2")
    if manifest.get("issue_number") != 20:
        blockers.append("manifest.issue_number must be 20")
    if manifest.get("base_commit") != ISSUE20_BASE_COMMIT:
        blockers.append("manifest.base_commit does not match the locked issue #20 base")
    if tuple(manifest.get("required_categories", ())) != REQUIRED_HARNESS_CATEGORIES:
        blockers.append("manifest.required_categories mismatch")
    scope = manifest.get("scope")
    if not isinstance(scope, dict):
        blockers.append("manifest.scope must be an object")
        scope = {}
    else:
        _check_exact_keys(
            scope,
            {"include_globs", "exclusion_rules"},
            "manifest.scope",
            blockers,
        )
        if tuple(scope.get("include_globs", ())) != ISSUE20_FUNCTION_SCOPE_GLOBS:
            blockers.append("manifest.scope.include_globs mismatch")
        if tuple(scope.get("exclusion_rules", ())) != ISSUE20_FUNCTION_EXCLUSION_RULES:
            blockers.append("manifest.scope.exclusion_rules mismatch")
    entries = manifest.get("functions")
    if not isinstance(entries, list):
        blockers.append("manifest.functions must be a list")
        entries = []
    test_ids = collect_unittest_test_ids(root / "tests")
    current_functions = current_scoped_functions(root, ISSUE20_FUNCTION_SCOPE_GLOBS)
    changed_bindings = changed_scoped_function_bindings(
        root,
        base_commit=str(manifest.get("base_commit", "")),
        include_globs=ISSUE20_FUNCTION_SCOPE_GLOBS,
    )
    changed = set(changed_bindings)
    seen: set[tuple[str, str]] = set()
    manifested: set[tuple[str, str]] = set()
    duplicate_function_count = 0
    source_binding_mismatch_count = 0
    pending_functions: list[tuple[str, str]] = []
    onboarded_functions: list[tuple[str, str]] = []
    reason_owners: dict[str, str] = {}
    test_function_owners: dict[str, set[tuple[str, str]]] = {}
    for index, raw_entry in enumerate(entries):
        context = f"manifest.functions[{index}]"
        if not isinstance(raw_entry, dict):
            blockers.append(f"{context} must be an object")
            continue
        _check_exact_keys(
            raw_entry,
            {
                "module",
                "qualname",
                "status",
                "source_binding",
                "categories",
                "test_ids",
            },
            context,
            blockers,
        )
        module = raw_entry.get("module")
        qualname = raw_entry.get("qualname")
        if not isinstance(module, str) or not module:
            blockers.append(f"{context}.module must be a non-empty string")
            continue
        if not isinstance(qualname, str) or not qualname:
            blockers.append(f"{context}.qualname must be a non-empty string")
            continue
        key = (module, qualname)
        if key in seen:
            blockers.append(f"duplicate function manifest entry: {module}.{qualname}")
            duplicate_function_count += 1
        seen.add(key)
        manifested.add(key)
        status = raw_entry.get("status")
        if status not in {"onboarded", "pending"}:
            blockers.append(f"{context}.status is not supported")
        elif status == "pending":
            pending_functions.append(key)
        else:
            onboarded_functions.append(key)
        if key not in current_functions:
            blockers.append(f"manifested function does not exist: {module}.{qualname}")
        source_binding = raw_entry.get("source_binding")
        binding_valid = isinstance(source_binding, dict)
        if not binding_valid:
            blockers.append(f"{context}.source_binding must be an object")
        else:
            _check_exact_keys(
                source_binding,
                _SOURCE_BINDING_KEYS,
                f"{context}.source_binding",
                blockers,
            )
        expected_binding = changed_bindings.get(key)
        if expected_binding is not None and (
            not binding_valid or dict(source_binding) != expected_binding
        ):
            source_binding_mismatch_count += 1
            blockers.append(f"source binding mismatch: {module}.{qualname}")
        categories = raw_entry.get("categories")
        if not isinstance(categories, dict):
            blockers.append(f"{context}.categories must be an object")
            categories = {}
        else:
            _check_exact_keys(
                categories,
                set(REQUIRED_HARNESS_CATEGORIES),
                f"{context}.categories",
                blockers,
            )
        entry_test_ids = raw_entry.get("test_ids")
        if not _valid_string_list(entry_test_ids):
            blockers.append(f"{context}.test_ids must be a unique non-empty string list")
            entry_test_ids = []
        for test_id in entry_test_ids:
            if test_id not in test_ids:
                blockers.append(f"unknown test id for {module}.{qualname}: {test_id}")
            if any(marker in test_id for marker in _LIVE_ONLY_TEST_MARKERS):
                blockers.append(
                    f"live-only test cannot satisfy local function evidence: "
                    f"{module}.{qualname}: {test_id}"
                )
            test_function_owners.setdefault(test_id, set()).add(key)
        category_tests: set[str] = set()
        for category in REQUIRED_HARNESS_CATEGORIES:
            category_value = categories.get(category)
            if not isinstance(category_value, dict):
                blockers.append(f"{context}.categories.{category} must be an object")
                continue
            _check_exact_keys(
                category_value,
                {"test_ids", "not_applicable_reason", "pending_reason"},
                f"{context}.categories.{category}",
                blockers,
            )
            category_ids = category_value.get("test_ids")
            reason = category_value.get("not_applicable_reason")
            pending_reason = category_value.get("pending_reason")
            if not isinstance(category_ids, list) or any(
                not isinstance(item, str) or not item for item in category_ids
            ):
                blockers.append(f"{context}.categories.{category}.test_ids is invalid")
                category_ids = []
            if len(category_ids) != len(set(category_ids)):
                blockers.append(f"{context}.categories.{category}.test_ids contains duplicates")
            if category_ids and reason not in (None, ""):
                blockers.append(
                    f"{context}.categories.{category} cannot have tests and an N/A reason"
                )
            if category_ids and pending_reason not in (None, ""):
                blockers.append(
                    f"{context}.categories.{category} cannot have tests and a pending reason"
                )
            if status == "pending":
                if category_ids or reason not in (None, ""):
                    blockers.append(
                        f"{context}.categories.{category} pending evidence cannot use tests or N/A"
                    )
                _validate_function_specific_reason(
                    pending_reason,
                    module=module,
                    qualname=qualname,
                    category=category,
                    pending=True,
                    context=f"{context}.categories.{category}.pending_reason",
                    blockers=blockers,
                    reason_owners=reason_owners,
                )
            else:
                if pending_reason not in (None, ""):
                    blockers.append(
                        f"{context}.categories.{category} onboarded evidence cannot be pending"
                    )
                if not category_ids:
                    if category == "success":
                        blockers.append(
                            f"{context}.categories.success requires a passing local test"
                        )
                    else:
                        _validate_function_specific_reason(
                            reason,
                            module=module,
                            qualname=qualname,
                            category=category,
                            pending=False,
                            context=(f"{context}.categories.{category}.not_applicable_reason"),
                            blockers=blockers,
                            reason_owners=reason_owners,
                        )
            for test_id in category_ids:
                category_tests.add(test_id)
                if test_id not in test_ids:
                    blockers.append(f"unknown category test id for {module}.{qualname}: {test_id}")
                if any(marker in test_id for marker in _LIVE_ONLY_TEST_MARKERS):
                    blockers.append(
                        f"live-only category test cannot satisfy local evidence: "
                        f"{module}.{qualname}: {test_id}"
                    )
        if set(entry_test_ids) != category_tests:
            blockers.append(f"{context}.test_ids must equal the category test-id union")
        if status == "pending" and entry_test_ids:
            blockers.append(f"{context}.pending function must not claim executed test evidence")
    for test_id, owners in sorted(test_function_owners.items()):
        if len(owners) > _MAX_FUNCTIONS_PER_EVIDENCE_TEST:
            blockers.append(
                f"over-broad manifest test id is assigned to {len(owners)} functions: {test_id}"
            )
    missing = sorted(changed - manifested)
    if missing:
        blockers.extend(
            "changed function is not harness-onboarded: " + ".".join(item) for item in missing
        )
    extra = sorted(manifested - changed)
    if extra:
        blockers.extend(
            "manifested function is not added or modified: " + ".".join(item) for item in extra
        )
    if len(entries) != len(changed):
        blockers.append(
            "manifest function entry count does not equal changed function count: "
            f"manifest={len(entries)} changed={len(changed)}"
        )
    unknown = sorted(manifested - current_functions)
    if unknown:
        blockers.extend("unknown function manifest entry: " + ".".join(item) for item in unknown)
    blockers.extend(
        "changed function remains pending: " + ".".join(item) for item in pending_functions
    )
    return {
        "passed": not blockers,
        "blockers": blockers,
        "function_entry_count": len(entries),
        "manifested_function_count": len(manifested),
        "onboarded_function_count": len(onboarded_functions),
        "pending_function_count": len(pending_functions),
        "changed_function_count": len(changed),
        "missing_function_count": len(missing),
        "extra_function_count": len(extra),
        "duplicate_function_count": duplicate_function_count,
        "source_binding_mismatch_count": source_binding_mismatch_count,
        "test_id_count": len(test_ids),
        "manifest_hash": sha256_json(manifest),
        "changed_function_set_hash": sha256_json(sorted(changed)),
        "changed_function_binding_hash": sha256_json(
            [
                {
                    "module": module,
                    "qualname": qualname,
                    "source_binding": changed_bindings[(module, qualname)],
                }
                for module, qualname in sorted(changed)
            ]
        ),
    }


def _validate_function_specific_reason(
    value: Any,
    *,
    module: str,
    qualname: str,
    category: str,
    pending: bool,
    context: str,
    blockers: list[str],
    reason_owners: dict[str, str],
) -> None:
    if not isinstance(value, str) or not value.strip():
        blockers.append(f"{context} must be a non-empty function-specific reason")
        return
    reason = " ".join(value.split())
    identity = f"{module}.{qualname}"
    lowered = reason.lower()
    if len(reason) < 80 or len(reason) > 700 or len(reason.split()) < 10:
        blockers.append(f"{context} must contain a bounded semantic explanation")
    if identity not in reason:
        blockers.append(f"{context} must name the exact qualified function {identity}")
    if any(phrase in lowered for phrase in _GENERIC_REASON_PHRASES):
        blockers.append(f"{context} contains a rejected generic phrase")
    previous_owner = reason_owners.get(reason)
    if previous_owner is not None and previous_owner != context:
        blockers.append(f"{context} duplicates another function/category reason")
    reason_owners[reason] = context
    if pending:
        if "pending" not in lowered or category.replace("_", " ") not in lowered:
            blockers.append(
                f"{context} must state the exact pending evidence category and missing proof"
            )
        if not any(term in lowered for term in ("test", "probe", "execution", "evidence")):
            blockers.append(f"{context} must name the missing executable proof")
        return
    terms = _CATEGORY_REASON_TERMS.get(category, ())
    if terms and not any(term in lowered for term in terms):
        blockers.append(f"{context} does not explain why {category} is semantically absent")


class _FunctionCoverageResult(unittest.TextTestResult):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.active_test_id: str | None = None
        self.started_test_ids: set[str] = set()
        self.successful_test_ids: set[str] = set()
        self.failed_test_ids: set[str] = set()
        self.skipped_test_ids: set[str] = set()
        self.expected_failure_test_ids: set[str] = set()
        self.unexpected_success_test_ids: set[str] = set()
        self.coverage_by_test: dict[str, set[tuple[str, str]]] = {}

    def startTest(self, test: unittest.case.TestCase) -> None:  # noqa: N802
        test_id = test.id()
        self.started_test_ids.add(test_id)
        super().startTest(test)

    def stopTest(self, test: unittest.case.TestCase) -> None:  # noqa: N802
        try:
            super().stopTest(test)
        finally:
            self.active_test_id = None

    def addSuccess(self, test: unittest.case.TestCase) -> None:  # noqa: N802
        self.successful_test_ids.add(test.id())
        super().addSuccess(test)

    def addFailure(self, test: unittest.case.TestCase, err: Any) -> None:  # noqa: N802
        self.failed_test_ids.add(test.id())
        super().addFailure(test, err)

    def addError(self, test: unittest.case.TestCase, err: Any) -> None:  # noqa: N802
        self.failed_test_ids.add(test.id())
        super().addError(test, err)

    def addSkip(self, test: unittest.case.TestCase, reason: str) -> None:  # noqa: N802
        self.skipped_test_ids.add(test.id())
        super().addSkip(test, reason)

    def addExpectedFailure(self, test: unittest.case.TestCase, err: Any) -> None:  # noqa: N802
        self.expected_failure_test_ids.add(test.id())
        super().addExpectedFailure(test, err)

    def addUnexpectedSuccess(self, test: unittest.case.TestCase) -> None:  # noqa: N802
        self.unexpected_success_test_ids.add(test.id())
        super().addUnexpectedSuccess(test)

    def addSubTest(
        self,
        test: unittest.case.TestCase,
        subtest: unittest.case.TestCase,
        err: Any,
    ) -> None:  # noqa: N802
        if err is not None:
            self.failed_test_ids.add(test.id())
        super().addSubTest(test, subtest, err)


def run_function_harness_test_suite(
    manifest: Mapping[str, Any],
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Resolve and execute each unique manifest test while tracing scoped calls."""

    resolved_root = root.resolve()
    tests_root = resolved_root / "tests"
    scripts_root = resolved_root / "scripts"
    python_root = resolved_root / "python"
    deploy_root = resolved_root / "deploy"
    repository_module_roots = (
        tests_root,
        scripts_root,
        python_root,
        deploy_root,
    )
    import_roots = (
        resolved_root,
        tests_root,
        scripts_root,
        python_root,
        deploy_root,
    )
    original_sys_path = list(sys.path)
    original_repository_modules = _snapshot_repository_modules(repository_module_roots)
    original_active_import_aliases = _snapshot_active_import_aliases(
        tests_root=tests_root,
        scripts_root=scripts_root,
    )
    try:
        for name in {
            *original_repository_modules,
            *original_active_import_aliases,
        }:
            sys.modules.pop(name, None)
        sys.path[:0] = [str(path) for path in import_roots]
        return _run_function_harness_test_suite(manifest, root=resolved_root)
    finally:
        _restore_repository_modules(
            original_repository_modules,
            module_roots=repository_module_roots,
        )
        sys.modules.update(original_active_import_aliases)
        sys.path[:] = original_sys_path


def _snapshot_repository_modules(module_roots: Sequence[Path]) -> dict[str, Any]:
    return {
        name: module
        for name, module in sys.modules.items()
        if module is not None and _module_is_under_roots(module, module_roots)
    }


def _snapshot_active_import_aliases(
    *,
    tests_root: Path,
    scripts_root: Path,
) -> dict[str, Any]:
    bare_alias_names = {
        path.stem
        for root in (tests_root, scripts_root)
        for path in root.glob("*.py")
        if path.name != "__init__.py"
    }
    return {
        name: module
        for name, module in sys.modules.items()
        if name == "tests" or name.startswith("tests.") or name in bare_alias_names
    }


def _restore_repository_modules(
    original_modules: Mapping[str, Any],
    *,
    module_roots: Sequence[Path],
) -> None:
    names_to_remove = [
        name
        for name, module in tuple(sys.modules.items())
        if name not in original_modules
        and module is not None
        and _module_is_under_roots(module, module_roots)
    ]
    for name in names_to_remove:
        sys.modules.pop(name, None)
    for name, module in original_modules.items():
        sys.modules[name] = module


def _module_is_under_roots(module: Any, roots: Sequence[Path]) -> bool:
    module_file = getattr(module, "__file__", None)
    if module_file is not None and any(_path_is_within(module_file, root) for root in roots):
        return True
    module_path = getattr(module, "__path__", None)
    if module_path is None:
        return False
    return any(_path_is_within(path, root) for path in module_path for root in roots)


def _path_is_within(path: Any, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(root)
    except (OSError, TypeError, ValueError):
        return False
    return True


def _run_function_harness_test_suite(
    manifest: Mapping[str, Any],
    *,
    root: Path,
) -> dict[str, Any]:
    entries = manifest.get("functions")
    if not isinstance(entries, list):
        raise AssertionError("manifest functions must be available before suite execution")
    requested_test_ids = sorted(
        {
            test_id
            for entry in entries
            if isinstance(entry, Mapping)
            for test_id in entry.get("test_ids", ())
            if isinstance(test_id, str) and test_id
        }
    )
    loader = unittest.TestLoader()
    resolved_cases: list[unittest.case.TestCase] = []
    resolution_blockers: list[str] = []
    for test_id in requested_test_ids:
        loaded = loader.loadTestsFromName(test_id)
        cases = list(_flatten_test_suite(loaded))
        resolved_ids = [case.id() for case in cases]
        if resolved_ids != [test_id]:
            resolution_blockers.append(test_id)
            continue
        resolved_cases.extend(cases)
    if loader.errors:
        resolution_blockers.extend(f"loader_error_{index}" for index, _ in enumerate(loader.errors))

    include_globs = manifest.get("scope", {}).get("include_globs", ())
    scoped_paths = {
        str(path.resolve()): _module_name(root, path)
        for path in _scoped_python_paths(root, include_globs)
    }
    current_functions = current_scoped_functions(root, include_globs)
    stream = io.StringIO()
    runner = unittest.TextTestRunner(
        stream=stream,
        verbosity=0,
        resultclass=_FunctionCoverageResult,
    )
    suite = unittest.TestSuite(resolved_cases)
    result: _FunctionCoverageResult
    runner_thread = threading.current_thread()
    thread_body_origins: dict[threading.Thread, str] = {}
    original_thread_start = threading.Thread.start
    original_test_method_callers: list[
        tuple[unittest.case.TestCase, Callable[[Callable[..., Any]], Any]]
    ] = []

    def active_body_for_current_thread() -> str | None:
        active_test_id = result.active_test_id
        if active_test_id is None:
            return None
        current_thread = threading.current_thread()
        if current_thread is runner_thread:
            return active_test_id
        if thread_body_origins.get(current_thread) == active_test_id:
            return active_test_id
        return None

    def start_thread_with_body_origin(
        thread: threading.Thread,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        origin = active_body_for_current_thread()
        if origin is not None:
            thread_body_origins[thread] = origin
        try:
            return original_thread_start(thread, *args, **kwargs)
        except BaseException:
            thread_body_origins.pop(thread, None)
            raise

    def trace_calls(frame: Any, event: str, _argument: Any) -> Any:
        if event != "call":
            return None
        module = scoped_paths.get(str(Path(frame.f_code.co_filename).resolve()))
        if module is None:
            return None
        key = (module, frame.f_code.co_qualname)
        if key not in current_functions:
            return None
        active_test_id = active_body_for_current_thread()
        if active_test_id is not None:
            result.coverage_by_test.setdefault(active_test_id, set()).add(key)
        return None

    previous_sys_trace = sys.gettrace()
    previous_thread_trace = threading.gettrace()
    try:
        result = runner._makeResult()
        result.failfast = runner.failfast
        result.buffer = runner.buffer
        result.tb_locals = runner.tb_locals
        for case in resolved_cases:
            original_call_test_method = case._callTestMethod
            test_id = case.id()

            def call_test_method_body(
                method: Callable[..., Any],
                *,
                _original: Callable[[Callable[..., Any]], Any] = original_call_test_method,
                _test_id: str = test_id,
            ) -> Any:
                if result.active_test_id is not None:
                    raise AssertionError("function harness test-body trace is already active")
                result.active_test_id = _test_id
                try:
                    return _original(method)
                finally:
                    result.active_test_id = None

            original_test_method_callers.append((case, original_call_test_method))
            case._callTestMethod = call_test_method_body
        threading.Thread.start = start_thread_with_body_origin
        sys.settrace(trace_calls)
        threading.settrace(trace_calls)
        result.startTestRun()
        try:
            suite(result)
        finally:
            result.stopTestRun()
    finally:
        sys.settrace(previous_sys_trace)
        threading.settrace(previous_thread_trace)
        threading.Thread.start = original_thread_start
        for case, original_call_test_method in original_test_method_callers:
            case._callTestMethod = original_call_test_method

    # Only calls made while unittest is executing the test method body count as
    # evidence. Class/module fixtures, per-test setUp/tearDown, result callbacks,
    # and cleanups all run outside this boundary and cannot create false credit.
    combined_coverage = {
        test_id: set(result.coverage_by_test.get(test_id, set())) for test_id in requested_test_ids
    }
    nonpassing_ids = {
        *result.failed_test_ids,
        *result.skipped_test_ids,
        *result.expected_failure_test_ids,
        *result.unexpected_success_test_ids,
    }
    passed = (
        not resolution_blockers
        and result.testsRun == len(requested_test_ids)
        and result.started_test_ids == set(requested_test_ids)
        and result.successful_test_ids == set(requested_test_ids)
        and not nonpassing_ids
        and result.wasSuccessful()
    )
    coverage_pairs = sorted(
        (test_id, module, qualname)
        for test_id, functions in combined_coverage.items()
        for module, qualname in functions
    )
    return {
        "passed": passed,
        "requested_test_count": len(requested_test_ids),
        "resolved_test_count": len(resolved_cases),
        "run_count": result.testsRun,
        "pass_count": len(result.successful_test_ids),
        "skip_count": len(result.skipped_test_ids),
        "failure_count": len(result.failures),
        "error_count": len(result.errors),
        "expected_failure_count": len(result.expectedFailures),
        "unexpected_success_count": len(result.unexpectedSuccesses),
        "resolution_blocker_count": len(resolution_blockers),
        "test_set_hash": sha256_json(requested_test_ids),
        "executed_test_set_hash": sha256_json(sorted(result.started_test_ids)),
        "coverage_pairs_hash": sha256_json(coverage_pairs),
        "covered_function_count": len(
            {function for functions in combined_coverage.values() for function in functions}
        ),
        "_coverage_by_test": {
            test_id: sorted(functions) for test_id, functions in combined_coverage.items()
        },
    }


def validate_function_harness_execution(
    manifest: Mapping[str, Any],
    execution: Mapping[str, Any],
) -> dict[str, Any]:
    blockers: list[str] = []
    if execution.get("passed") is not True:
        blockers.append("manifest test suite did not pass exactly")
    coverage_by_test = execution.get("_coverage_by_test")
    if not isinstance(coverage_by_test, Mapping):
        blockers.append("manifest execution coverage is unavailable")
        coverage_by_test = {}
    checked_pair_count = 0
    checked_pairs: list[tuple[str, str, str]] = []
    direct_trace_function_count = 0
    directly_covered_functions: set[tuple[str, str]] = set()
    missing_direct_traces: list[tuple[str, str]] = []
    for entry in manifest.get("functions", ()):
        if not isinstance(entry, Mapping) or entry.get("status") == "pending":
            continue
        module = entry.get("module")
        qualname = entry.get("qualname")
        key = (module, qualname)
        if not isinstance(module, str) or not isinstance(qualname, str):
            continue
        direct_trace_function_count += 1
        entry_test_ids = sorted(
            {
                test_id
                for test_id in entry.get("test_ids", ())
                if isinstance(test_id, str) and test_id
            }
        )
        observed_functions: set[tuple[str, str]] = set()
        for test_id in entry_test_ids:
            checked_pair_count += 1
            checked_pairs.append((test_id, module, qualname))
            observed_functions.update(
                tuple(item)
                for item in coverage_by_test.get(test_id, ())
                if isinstance(item, (list, tuple)) and len(item) == 2
            )
        if key in observed_functions:
            directly_covered_functions.add(key)
        else:
            missing_direct_traces.append(key)
            blockers.append(
                f"onboarded function has no passing direct runtime trace: {module}.{qualname}"
            )
    return {
        "passed": not blockers,
        "blockers": blockers,
        "checked_pair_count": checked_pair_count,
        "checked_pair_set_hash": sha256_json(sorted(checked_pairs)),
        "direct_trace_function_count": direct_trace_function_count,
        "direct_trace_covered_function_count": len(directly_covered_functions),
        "direct_trace_missing_function_count": len(missing_direct_traces),
        "direct_trace_function_set_hash": sha256_json(sorted(directly_covered_functions)),
    }


def _flatten_test_suite(suite: unittest.TestSuite) -> Iterator[unittest.case.TestCase]:
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten_test_suite(item)
        elif isinstance(item, unittest.case.TestCase):
            yield item


def collect_unittest_test_ids(tests_root: Path) -> set[str]:
    collected: set[str] = set()
    for path in sorted(tests_root.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module = f"tests.{path.stem}"
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for child in node.body:
                if isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef)
                ) and child.name.startswith("test_"):
                    collected.add(f"{module}.{node.name}.{child.name}")
    return collected


def current_scoped_functions(
    root: Path,
    include_globs: Sequence[str],
) -> set[tuple[str, str]]:
    functions: set[tuple[str, str]] = set()
    for path in _scoped_python_paths(root, include_globs):
        module = _module_name(root, path)
        functions.update(
            (module, item.qualname) for item in _function_fingerprints(path.read_text())
        )
    return functions


def changed_scoped_functions(
    root: Path,
    *,
    base_commit: str,
    include_globs: Sequence[str],
) -> set[tuple[str, str]]:
    return set(
        changed_scoped_function_bindings(
            root,
            base_commit=base_commit,
            include_globs=include_globs,
        )
    )


def changed_scoped_function_bindings(
    root: Path,
    *,
    base_commit: str,
    include_globs: Sequence[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    _require_git_base(root, base_commit)
    changed: dict[tuple[str, str], dict[str, Any]] = {}
    for path in _scoped_python_paths(root, include_globs):
        relative = path.relative_to(root).as_posix()
        current = {
            item.qualname: item.fingerprint for item in _function_fingerprints(path.read_text())
        }
        base_text = _git_show(root, base_commit, relative)
        base = (
            {}
            if base_text is None
            else {item.qualname: item.fingerprint for item in _function_fingerprints(base_text)}
        )
        module = _module_name(root, path)
        for qualname, fingerprint in current.items():
            base_fingerprint = base.get(qualname)
            if base_fingerprint == fingerprint:
                continue
            key = (module, qualname)
            if key in changed:
                raise AssertionError(
                    f"scoped function identity resolves to multiple files: {module}.{qualname}"
                )
            change_kind = "added" if base_fingerprint is None else "modified"
            base_ast_sha256 = None if base_fingerprint is None else f"sha256:{base_fingerprint}"
            current_ast_sha256 = f"sha256:{fingerprint}"
            diff_payload = {
                "module": module,
                "qualname": qualname,
                "source_path": relative,
                "change_kind": change_kind,
                "base_ast_sha256": base_ast_sha256,
                "current_ast_sha256": current_ast_sha256,
            }
            changed[key] = {
                "source_path": relative,
                "change_kind": change_kind,
                "base_ast_sha256": base_ast_sha256,
                "current_ast_sha256": current_ast_sha256,
                "diff_sha256": sha256_json(diff_payload),
            }
    return changed


@dataclass(frozen=True)
class _FunctionFingerprint:
    qualname: str
    fingerprint: str


def _function_fingerprints(source: str) -> list[_FunctionFingerprint]:
    tree = ast.parse(source)
    results: list[_FunctionFingerprint] = []

    def walk(nodes: Sequence[ast.stmt], parents: tuple[str, ...] = ()) -> None:
        for node in nodes:
            if isinstance(node, ast.ClassDef):
                walk(node.body, (*parents, node.name))
                continue
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            qualname = ".".join((*parents, node.name))
            if _excluded_function(node):
                continue
            normalized = ast.dump(node, annotate_fields=True, include_attributes=False)
            results.append(
                _FunctionFingerprint(
                    qualname=qualname,
                    fingerprint=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
                )
            )
            walk(node.body, (*parents, node.name, "<locals>"))

    walk(tree.body)
    return results


def assert_safe_harness_report(payload: Any) -> None:
    violations: list[str] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key)
                normalized = re.sub(r"[^a-z0-9]+", "_", key_text.lower()).strip("_")
                if not (
                    isinstance(item, bool)
                    or normalized.endswith("_hash")
                    or normalized.endswith("_count")
                ):
                    if any(part in normalized for part in _SENSITIVE_FIELD_PARTS):
                        violations.append(f"sensitive field: {path}.{key_text}")
                    if normalized in {"path", "sql", "raw_payload", "private_key"}:
                        violations.append(f"forbidden field: {path}.{key_text}")
                walk(item, f"{path}.{key_text}")
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
            return
        if isinstance(value, str) and (
            _JWT_RE.search(value)
            or _EMAIL_RE.search(value)
            or _BEARER_RE.search(value)
            or _RAW_PATH_RE.search(value)
            or _SQL_RE.search(value)
        ):
            violations.append(f"sensitive value: {path}")

    walk(payload, "report")
    if violations:
        raise AssertionError("unsafe OAuth harness report: " + ", ".join(sorted(violations)))


def sha256_json(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _invoke_asgi(
    app: Any,
    *,
    method: str,
    target: str,
    headers: Sequence[tuple[str, str]],
    body: bytes,
    state: Mapping[str, Any] | None = None,
) -> Any:
    parsed = urlparse(target)
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": parsed.path,
        "raw_path": parsed.path.encode("ascii"),
        "query_string": parsed.query.encode("ascii"),
        "root_path": "",
        "headers": [
            (key.lower().encode("latin1"), value.encode("latin1")) for key, value in headers
        ],
        "client": ("127.0.0.1", 1),
        "server": ("127.0.0.1", 0),
        "state": dict(state or {}),
    }
    sent_request = False
    status = 500
    response_headers: list[tuple[str, str]] = []
    response_body = bytearray()

    async def receive() -> dict[str, Any]:
        nonlocal sent_request
        if sent_request:
            return {"type": "http.disconnect"}
        sent_request = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: Mapping[str, Any]) -> None:
        nonlocal status, response_headers
        if message["type"] == "http.response.start":
            status = int(message["status"])
            response_headers = [
                (key.decode("latin1"), value.decode("latin1"))
                for key, value in message.get("headers", [])
            ]
        elif message["type"] == "http.response.body":
            response_body.extend(message.get("body", b""))

    async def run() -> tuple[int, list[tuple[str, str]], bytes]:
        await app(scope, receive, send)
        return status, response_headers, bytes(response_body)

    return run()


def _deterministic_prime(rng: DeterministicRng, bits: int) -> int:
    byte_length = (bits + 7) // 8
    while True:
        candidate = int.from_bytes(rng.bytes(byte_length), "big")
        candidate |= 1
        candidate |= 1 << (bits - 1)
        candidate &= (1 << bits) - 1
        while candidate.bit_length() == bits:
            if _is_probable_prime(candidate):
                return candidate
            candidate += 2


def _is_probable_prime(value: int) -> bool:
    small_primes = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43)
    if value in small_primes:
        return True
    if any(value % prime == 0 for prime in small_primes):
        return False
    d = value - 1
    shifts = 0
    while d % 2 == 0:
        shifts += 1
        d //= 2
    for base in small_primes[1:]:
        x = pow(base, d, value)
        if x in (1, value - 1):
            continue
        for _ in range(shifts - 1):
            x = pow(x, 2, value)
            if x == value - 1:
                break
        else:
            return False
    return True


def _int_bytes(value: int) -> bytes:
    return value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big")


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _model_dump(value: Any) -> Any:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(value, Mapping):
        return {str(key): _model_dump(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_model_dump(item) for item in value]
    return value


def _first(value: Mapping[str, Sequence[str]], key: str) -> str:
    items = value.get(key, ())
    return str(items[0]) if items else ""


def _check_exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    context: str,
    blockers: list[str],
) -> None:
    actual = set(value)
    if actual != expected:
        blockers.append(
            f"{context} keys mismatch: expected={sorted(expected)} actual={sorted(actual)}"
        )


def _valid_string_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and all(isinstance(item, str) and item for item in value)
        and len(value) == len(set(value))
    )


def _scoped_python_paths(root: Path, include_globs: Sequence[str]) -> list[Path]:
    paths: set[Path] = set()
    for pattern in include_globs:
        paths.update(path for path in root.glob(pattern) if path.is_file() and path.suffix == ".py")
    return sorted(paths)


def _module_name(root: Path, path: Path) -> str:
    relative = path.relative_to(root)
    parts = list(relative.with_suffix("").parts)
    if parts and parts[0] == "python":
        parts.pop(0)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _excluded_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    decorator_names = {
        ast.unparse(decorator) if hasattr(ast, "unparse") else ""
        for decorator in node.decorator_list
    }
    if "overload" in decorator_names or "typing.overload" in decorator_names:
        return True
    return (
        len(node.body) == 1
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and node.body[0].value.value is Ellipsis
    )


def _require_git_base(root: Path, base_commit: str) -> None:
    completed = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={root.resolve()}",
            "cat-file",
            "-e",
            f"{base_commit}^{{commit}}",
        ],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError("locked issue #20 base commit is unavailable; fail closed")


def _git_show(root: Path, base_commit: str, relative_path: str) -> str | None:
    completed = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={root.resolve()}",
            "show",
            f"{base_commit}:{relative_path}",
        ],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode == 0:
        return completed.stdout
    if "does not exist" in completed.stderr or "exists on disk, but not in" in completed.stderr:
        return None
    raise AssertionError("could not inspect locked base commit; fail closed")


__all__ = [
    "AsgiHttpServer",
    "CapturedLogs",
    "DeterministicRng",
    "DeterministicRsaKey",
    "FakeClock",
    "FakeGoogleAccount",
    "FakeGoogleOidcProvider",
    "FailureInjected",
    "HttpClient",
    "HttpResponse",
    "ISSUE20_BASE_COMMIT",
    "ISSUE20_FUNCTION_EXCLUSION_RULES",
    "ISSUE20_FUNCTION_SCOPE_GLOBS",
    "Issue20HarnessDependencyMissing",
    "MANIFEST_PATH",
    "REQUIRED_HARNESS_CATEGORIES",
    "RewritingAsyncHttpClient",
    "SimulatedChatGptOAuthClient",
    "TransactionAwareMemoryRepository",
    "assert_safe_harness_report",
    "changed_scoped_function_bindings",
    "changed_scoped_functions",
    "collect_unittest_test_ids",
    "current_scoped_functions",
    "generate_function_harness_manifest_skeleton",
    "generate_ephemeral_formowl_signing_key",
    "load_function_harness_manifest",
    "run_official_mcp_client_sequence",
    "run_function_harness_test_suite",
    "run_issue20_deterministic_e2e",
    "sha256_json",
    "validate_function_harness_execution",
    "validate_function_harness_manifest",
]
