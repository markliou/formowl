"""OAuth security primitives composed from standard libraries and Fernet."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from typing import Callable

from cryptography.fernet import Fernet, InvalidToken
from formowl_contract import ContractValidationError


RandomBytes = Callable[[int], bytes]

_PKCE_VERIFIER = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
_SAFE_PREFIX = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+$")


def generate_opaque_value(
    *, random_bytes: RandomBytes = secrets.token_bytes, size: int = 32
) -> str:
    if isinstance(size, bool) or not isinstance(size, int) or size < 32:
        raise ValueError("OAuth opaque values require at least 32 random bytes")
    raw = random_bytes(size)
    if not isinstance(raw, bytes) or len(raw) != size:
        raise ValueError("OAuth random source returned an invalid byte sequence")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate_safe_id(prefix: str, *, random_bytes: RandomBytes = secrets.token_bytes) -> str:
    if not _SAFE_PREFIX.fullmatch(prefix):
        raise ValueError("OAuth identifier prefix is invalid")
    return f"{prefix}_{generate_opaque_value(random_bytes=random_bytes, size=32)}"


def hash_oauth_value(kind: str, value: str) -> str:
    if not isinstance(kind, str) or not _SAFE_PREFIX.fullmatch(kind):
        raise ValueError("OAuth hash kind is invalid")
    if not isinstance(value, str) or not value:
        raise ValueError("OAuth hash value is required")
    digest = hashlib.sha256(f"formowl:{kind}\0{value}".encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def oauth_hash_matches(kind: str, value: str, expected_hash: str) -> bool:
    if not isinstance(expected_hash, str):
        return False
    return hmac.compare_digest(hash_oauth_value(kind, value), expected_hash)


def validate_pkce_verifier(verifier: str) -> str:
    if not isinstance(verifier, str) or not _PKCE_VERIFIER.fullmatch(verifier):
        raise ContractValidationError("PKCE verifier is invalid")
    return verifier


def pkce_s256_challenge(verifier: str) -> str:
    validated = validate_pkce_verifier(verifier)
    digest = hashlib.sha256(validated.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def encrypt_client_state(client_state: str, encryption_key: str) -> str:
    if not isinstance(client_state, str) or not client_state:
        raise ContractValidationError("OAuth client state is required")
    try:
        fernet = Fernet(encryption_key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise ContractValidationError("OAuth state encryption key is invalid") from exc
    return fernet.encrypt(client_state.encode("utf-8")).decode("ascii")


def decrypt_client_state(encrypted_state: str, encryption_key: str) -> str:
    if not isinstance(encrypted_state, str) or not encrypted_state:
        raise ContractValidationError("encrypted OAuth client state is required")
    try:
        fernet = Fernet(encryption_key.encode("ascii"))
        return fernet.decrypt(encrypted_state.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError) as exc:
        raise ContractValidationError("encrypted OAuth client state is invalid") from exc


def normalize_verified_email(email: str) -> str:
    if not isinstance(email, str):
        raise ContractValidationError("verified email is required")
    normalized = email.strip().casefold()
    if (
        not normalized
        or len(normalized) > 320
        or any(ord(char) < 32 or ord(char) == 127 for char in normalized)
        or not _EMAIL.fullmatch(normalized)
    ):
        raise ContractValidationError("verified email is invalid")
    return normalized


__all__ = [
    "RandomBytes",
    "decrypt_client_state",
    "encrypt_client_state",
    "generate_opaque_value",
    "generate_safe_id",
    "hash_oauth_value",
    "normalize_verified_email",
    "oauth_hash_matches",
    "pkce_s256_challenge",
    "validate_pkce_verifier",
]
