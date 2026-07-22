from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, tzinfo
import json
import unittest
from urllib.parse import parse_qs, urlparse

from authlib.jose import JsonWebKey, JsonWebToken
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import httpx

import _paths  # noqa: F401
from formowl_auth import (
    FormOwlOAuthBridge,
    FormOwlSigningKey,
    FormOwlSigningKeySet,
    FormOwlTokenCodec,
    GoogleOidcClient,
    OAuthAccessDenied,
    OAuthBridgeConfig,
    OAuthTokenSession,
)
from formowl_auth.config import (
    GOOGLE_AUTHORIZATION_ENDPOINT,
    GOOGLE_DISCOVERY_URL,
    GOOGLE_ISSUER,
    GOOGLE_JWKS_URI,
    GOOGLE_TOKEN_ENDPOINT,
)
from formowl_auth.google_oidc import (
    _json_object as google_json_object,
    _require_aware as require_google_aware,
    _safe_display_name,
    _select_jwk,
    _unverified_header as google_unverified_header,
)
from formowl_auth.security import hash_oauth_value
from formowl_auth.tokens import (
    _require_aware as require_token_aware,
    _scope_tuple,
    _unverified_header as token_unverified_header,
)
from formowl_contract import ContractValidationError
from oauth_harness import FakeClock
from test_oauth_bridge_service import BridgeFixture


_JWT = JsonWebToken(["RS256"])


class OAuthTokenAndGoogleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.config = _config()

    def test_formowl_rs256_token_has_resource_binding_and_no_workspace_or_google_claims(
        self,
    ) -> None:
        key = _signing_key("formowl-active", active=True)
        key_set = FormOwlSigningKeySet([key])
        codec = FormOwlTokenCodec(
            issuer=self.config.issuer,
            client_id=self.config.chatgpt_client_id,
            key_set=key_set,
        )
        session = _token_session(self.clock)

        token = codec.issue_access_token(session=session, jti="jti_001", now=self.clock.now())
        claims = codec.verify_access_token(
            token,
            resource=self.config.resource,
            required_scope="formowl.use",
            now=self.clock.now(),
        )

        self.assertEqual(claims["aud"], self.config.resource)
        self.assertEqual(claims["sub"], session.user_id)
        self.assertEqual(claims["sid"], session.token_session_id)
        self.assertNotIn("workspace", claims)
        self.assertNotIn("email", claims)
        self.assertNotIn("google", str(claims).lower())
        jwks = key_set.public_jwks(now=self.clock.now())
        self.assertEqual(jwks["keys"][0]["kid"], "formowl-active")
        for private_name in ("d", "p", "q", "dp", "dq", "qi"):
            self.assertNotIn(private_name, jwks["keys"][0])

    def test_formowl_token_rejects_wrong_resource_scope_expiry_signature_and_alg(self) -> None:
        active = _signing_key("active", active=True)
        codec = FormOwlTokenCodec(
            issuer=self.config.issuer,
            client_id=self.config.chatgpt_client_id,
            key_set=FormOwlSigningKeySet([active]),
        )
        session = _token_session(self.clock)
        token = codec.issue_access_token(session=session, jti="jti_001", now=self.clock.now())

        cases = (
            {
                "resource": "https://auth.example.test/other",
                "scope": "formowl.use",
                "now": self.clock.now(),
                "reason": "token_resource_invalid",
            },
            {
                "resource": self.config.resource,
                "scope": "assets.write",
                "now": self.clock.now(),
                "reason": "required_scope_missing",
            },
            {
                "resource": self.config.resource,
                "scope": "formowl.use",
                "now": self.clock.now() + timedelta(hours=2),
                "reason": "token_expired",
            },
        )
        for case in cases:
            with self.subTest(reason=case["reason"]):
                with self.assertRaises(OAuthAccessDenied) as caught:
                    codec.verify_access_token(
                        token,
                        resource=case["resource"],
                        required_scope=case["scope"],
                        now=case["now"],
                    )
                self.assertEqual(caught.exception.reason_code, case["reason"])

        other_codec = FormOwlTokenCodec(
            issuer=self.config.issuer,
            client_id=self.config.chatgpt_client_id,
            key_set=FormOwlSigningKeySet([_signing_key("active", active=True)]),
        )
        with self.assertRaises(OAuthAccessDenied) as caught:
            other_codec.verify_access_token(
                token,
                resource=self.config.resource,
                required_scope="formowl.use",
                now=self.clock.now(),
            )
        self.assertEqual(caught.exception.reason_code, "token_signature_invalid")

        header, payload, _signature = token.split(".")
        bad_header = _b64_json({"alg": "none", "kid": "active", "typ": "JWT"})
        with self.assertRaises(OAuthAccessDenied) as caught:
            codec.verify_access_token(
                f"{bad_header}.{payload}.",
                resource=self.config.resource,
                required_scope="formowl.use",
                now=self.clock.now(),
            )
        self.assertEqual(caught.exception.reason_code, "token_header_invalid")
        self.assertTrue(header)

    def test_verify_access_token_rejects_invalid_now_before_decode_without_mutation(
        self,
    ) -> None:
        materialized_public_kids: list[str] = []
        decode_calls: list[tuple[str, datetime]] = []

        class TrackingSigningKey(FormOwlSigningKey):
            def public_jwk(self) -> dict[str, object]:
                materialized_public_kids.append(self.kid)
                return super().public_jwk()

        class TrackingTokenCodec(FormOwlTokenCodec):
            def _decode_signed_claims(
                self,
                raw_token: str,
                *,
                now: datetime,
            ) -> dict[str, object]:
                decode_calls.append((raw_token, now))
                return super()._decode_signed_claims(raw_token, now=now)

        source_key = _signing_key("private-verify-access-kid-marker", active=True)
        signing_key = TrackingSigningKey(
            kid=source_key.kid,
            private_key_pem=source_key.private_key_pem,
            active=True,
        )
        key_set = FormOwlSigningKeySet([signing_key])
        codec = TrackingTokenCodec(
            issuer=self.config.issuer,
            client_id=self.config.chatgpt_client_id,
            key_set=key_set,
        )
        session = _token_session(self.clock)
        raw_token = codec.issue_access_token(
            session=session,
            jti="jti_verify_invalid_now",
            now=self.clock.now(),
        )
        resource = self.config.resource
        required_scope = "formowl.use"

        token_snapshot = (id(raw_token), type(raw_token), repr(raw_token))
        resource_snapshot = (id(resource), type(resource), repr(resource))
        scope_snapshot = (id(required_scope), type(required_scope), repr(required_scope))
        session_identity = id(session)
        session_dict_identity = id(session.__dict__)
        session_state_snapshot = session.to_dict()
        codec_identity = id(codec)
        codec_dict_identity = id(codec.__dict__)
        codec_state_snapshot = dict(codec.__dict__)
        key_set_identity = id(key_set)
        key_tuple_identity = id(key_set._keys)
        key_set_state_snapshot = tuple(
            (id(key), key.kid, key.private_key_pem, key.active, key.verify_until)
            for key in key_set._keys
        )
        key_identity = id(signing_key)
        key_dict_identity = id(signing_key.__dict__)
        key_state_snapshot = (
            signing_key.kid,
            signing_key.private_key_pem,
            signing_key.active,
            signing_key.verify_until,
        )
        materialization_snapshot = tuple(materialized_public_kids)
        decode_snapshot = tuple(decode_calls)
        private_key_text = signing_key.private_key_pem.decode("ascii")
        self.assertEqual(materialized_public_kids, [])
        self.assertEqual(decode_calls, [])

        invalid_now_cases = (
            ("naive-datetime", self.clock.now().replace(tzinfo=None)),
            ("non-datetime", "raw-verify-access-now-secret-marker"),
        )
        for case_name, invalid_now in invalid_now_cases:
            with self.subTest(case_name=case_name):
                input_snapshot = (id(invalid_now), type(invalid_now), repr(invalid_now))
                result: dict[str, object] | None = None

                with self.assertRaises(ValueError) as caught:
                    result = codec.verify_access_token(
                        raw_token,
                        resource=resource,
                        required_scope=required_scope,
                        now=invalid_now,  # type: ignore[arg-type]
                    )

                self.assertIsNone(result)
                self.assertIs(type(caught.exception), ValueError)
                self.assertEqual(
                    str(caught.exception),
                    "now must be a timezone-aware datetime",
                )
                for rendered in (str(caught.exception), repr(caught.exception)):
                    for private_marker in (
                        raw_token,
                        str(invalid_now),
                        repr(invalid_now),
                        signing_key.kid,
                        private_key_text,
                    ):
                        self.assertNotIn(private_marker, rendered)
                self.assertEqual(
                    (id(invalid_now), type(invalid_now), repr(invalid_now)),
                    input_snapshot,
                )
                self.assertEqual(tuple(materialized_public_kids), materialization_snapshot)
                self.assertEqual(tuple(decode_calls), decode_snapshot)
                self.assertEqual(
                    (id(raw_token), type(raw_token), repr(raw_token)),
                    token_snapshot,
                )
                self.assertEqual(
                    (id(resource), type(resource), repr(resource)),
                    resource_snapshot,
                )
                self.assertEqual(
                    (id(required_scope), type(required_scope), repr(required_scope)),
                    scope_snapshot,
                )
                self.assertEqual(id(session), session_identity)
                self.assertEqual(id(session.__dict__), session_dict_identity)
                self.assertEqual(session.to_dict(), session_state_snapshot)
                self.assertEqual(id(codec), codec_identity)
                self.assertEqual(id(codec.__dict__), codec_dict_identity)
                self.assertEqual(codec.__dict__, codec_state_snapshot)
                self.assertEqual(id(key_set), key_set_identity)
                self.assertEqual(id(key_set._keys), key_tuple_identity)
                self.assertEqual(
                    tuple(
                        (
                            id(key),
                            key.kid,
                            key.private_key_pem,
                            key.active,
                            key.verify_until,
                        )
                        for key in key_set._keys
                    ),
                    key_set_state_snapshot,
                )
                self.assertEqual(id(signing_key), key_identity)
                self.assertEqual(id(signing_key.__dict__), key_dict_identity)
                self.assertEqual(
                    (
                        signing_key.kid,
                        signing_key.private_key_pem,
                        signing_key.active,
                        signing_key.verify_until,
                    ),
                    key_state_snapshot,
                )

    def test_token_codec_configuration_requires_non_boolean_integers_and_safe_errors(
        self,
    ) -> None:
        signing_key = _signing_key("codec-config-active", active=True)
        key_set = FormOwlSigningKeySet([signing_key])
        private_key_text = signing_key.private_key_pem.decode("ascii")
        valid_cases = (
            {"lifetime_seconds": 1, "clock_skew_seconds": 0},
            {"lifetime_seconds": 3600, "clock_skew_seconds": 300},
        )
        for values in valid_cases:
            with self.subTest(valid=values):
                codec = FormOwlTokenCodec(
                    issuer=self.config.issuer,
                    client_id=self.config.chatgpt_client_id,
                    key_set=key_set,
                    **values,
                )
                self.assertEqual(codec.lifetime_seconds, values["lifetime_seconds"])
                self.assertEqual(codec.clock_skew_seconds, values["clock_skew_seconds"])

        invalid_cases = (
            ({"lifetime_seconds": True}, "FormOwl token lifetime is invalid"),
            ({"lifetime_seconds": False}, "FormOwl token lifetime is invalid"),
            ({"lifetime_seconds": 1.0}, "FormOwl token lifetime is invalid"),
            ({"lifetime_seconds": "3600"}, "FormOwl token lifetime is invalid"),
            ({"lifetime_seconds": None}, "FormOwl token lifetime is invalid"),
            ({"clock_skew_seconds": True}, "FormOwl token clock skew is invalid"),
            ({"clock_skew_seconds": False}, "FormOwl token clock skew is invalid"),
            ({"clock_skew_seconds": 0.0}, "FormOwl token clock skew is invalid"),
            ({"clock_skew_seconds": "30"}, "FormOwl token clock skew is invalid"),
            ({"clock_skew_seconds": None}, "FormOwl token clock skew is invalid"),
        )
        for values, expected_message in invalid_cases:
            with self.subTest(invalid=values):
                with self.assertRaises(ContractValidationError) as caught:
                    FormOwlTokenCodec(
                        issuer=self.config.issuer,
                        client_id=self.config.chatgpt_client_id,
                        key_set=key_set,
                        **values,
                    )
                rendered = str(caught.exception)
                self.assertEqual(rendered, expected_message)
                self.assertNotIn(private_key_text, rendered)

    def test_token_codec_identity_configuration_requires_nonblank_strings_and_safe_errors(
        self,
    ) -> None:
        signing_key = _signing_key("codec-identity-active", active=True)
        key_set = FormOwlSigningKeySet([signing_key])
        private_key_text = signing_key.private_key_pem.decode("ascii")
        codec = FormOwlTokenCodec(
            issuer=self.config.issuer,
            client_id=self.config.chatgpt_client_id,
            key_set=key_set,
        )
        self.assertEqual(codec.issuer, self.config.issuer)
        self.assertEqual(codec.client_id, self.config.chatgpt_client_id)

        preserved_issuer = "  https://auth.example.test/opaque-issuer  "
        preserved_client_id = "  opaque-chatgpt-client  "
        preserved = FormOwlTokenCodec(
            issuer=preserved_issuer,
            client_id=preserved_client_id,
            key_set=key_set,
        )
        self.assertEqual(preserved.issuer, preserved_issuer)
        self.assertEqual(preserved.client_id, preserved_client_id)

        invalid_values = (
            True,
            False,
            7,
            1.5,
            None,
            object(),
            ["private-identity"],
            {"private": "identity"},
            "",
            "   ",
        )
        for field_name in ("issuer", "client_id"):
            for invalid_value in invalid_values:
                with self.subTest(field_name=field_name, invalid_value=invalid_value):
                    values = {
                        "issuer": self.config.issuer,
                        "client_id": self.config.chatgpt_client_id,
                        field_name: invalid_value,
                    }
                    with self.assertRaises(ContractValidationError) as caught:
                        FormOwlTokenCodec(key_set=key_set, **values)
                    rendered = str(caught.exception)
                    self.assertEqual(
                        rendered,
                        "FormOwl token issuer and client id are required",
                    )
                    self.assertNotIn("private-identity", rendered)
                    self.assertNotIn(private_key_text, rendered)

    def test_issue_access_token_requires_bounded_safe_string_jti_without_mutation(self) -> None:
        signing_key = _signing_key("jti-validation-active", active=True)
        key_set = FormOwlSigningKeySet([signing_key])
        codec = FormOwlTokenCodec(
            issuer=self.config.issuer,
            client_id=self.config.chatgpt_client_id,
            key_set=key_set,
        )
        session = _token_session(self.clock)
        valid_jti = "jti.Valid_01:-"
        token = codec.issue_access_token(
            session=session,
            jti=valid_jti,
            now=self.clock.now(),
        )
        claims = codec.verify_access_token(
            token,
            resource=self.config.resource,
            required_scope="formowl.use",
            now=self.clock.now(),
        )
        self.assertEqual(claims["jti"], valid_jti)

        invalid_jtis = (
            True,
            False,
            7,
            1.5,
            None,
            object(),
            ["private-jti"],
            {"private": "jti"},
            "",
            "   ",
            "unsafe/jti",
            "j" * 129,
        )
        invalid_snapshot = tuple(repr(value) for value in invalid_jtis)
        session_snapshot = session.to_dict()
        key_snapshot = key_set.public_jwks(now=self.clock.now())
        codec_snapshot = dict(codec.__dict__)
        private_key_text = signing_key.private_key_pem.decode("ascii")

        for invalid_jti in invalid_jtis:
            with self.subTest(invalid_jti=invalid_jti):
                with self.assertRaises(ContractValidationError) as caught:
                    codec.issue_access_token(
                        session=session,
                        jti=invalid_jti,  # type: ignore[arg-type]
                        now=self.clock.now(),
                    )
                rendered = str(caught.exception)
                self.assertEqual(rendered, "FormOwl token jti is invalid")
                self.assertNotIn("private-jti", rendered)
                self.assertNotIn(private_key_text, rendered)

        self.assertEqual(tuple(repr(value) for value in invalid_jtis), invalid_snapshot)
        self.assertEqual(session.to_dict(), session_snapshot)
        self.assertEqual(key_set.public_jwks(now=self.clock.now()), key_snapshot)
        self.assertEqual(codec.__dict__, codec_snapshot)

    def test_expired_access_token_for_audit_returns_trusted_safe_claims_without_mutation(
        self,
    ) -> None:
        active = _signing_key("audit-expired-active", active=True)
        key_set = FormOwlSigningKeySet([active])
        codec = FormOwlTokenCodec(
            issuer=self.config.issuer,
            client_id=self.config.chatgpt_client_id,
            key_set=key_set,
        )
        session = _token_session(self.clock)
        raw_token = codec.issue_access_token(
            session=session,
            jti="jti_audit_expired",
            now=self.clock.now(),
        )
        key_snapshot = key_set.public_jwks(now=self.clock.now())
        codec_snapshot = dict(codec.__dict__)

        claims = codec.verify_expired_access_token_for_audit(
            raw_token,
            resource=self.config.resource,
            required_scope="formowl.use",
            now=self.clock.now() + timedelta(hours=2),
        )

        self.assertEqual(claims["sub"], session.user_id)
        self.assertEqual(claims["sid"], session.token_session_id)
        self.assertEqual(claims["jti"], "jti_audit_expired")
        self.assertEqual(claims["client_id"], session.client_id)
        self.assertEqual(claims["aud"], session.resource)
        self.assertEqual(claims["scope"], "formowl.use")
        rendered = repr(claims).lower()
        for forbidden in (
            "google",
            "email",
            "workspace",
            "grant",
            "access_token",
            raw_token.lower(),
        ):
            self.assertNotIn(forbidden, rendered)
        self.assertEqual(key_set.public_jwks(now=self.clock.now()), key_snapshot)
        self.assertEqual(codec.__dict__, codec_snapshot)

    def test_expired_access_token_for_audit_rejects_invalid_now_before_decode_without_mutation(
        self,
    ) -> None:
        materialized_public_kids: list[str] = []
        decode_calls: list[tuple[str, datetime]] = []

        class TrackingSigningKey(FormOwlSigningKey):
            def public_jwk(self) -> dict[str, object]:
                materialized_public_kids.append(self.kid)
                return super().public_jwk()

        class TrackingTokenCodec(FormOwlTokenCodec):
            def _decode_signed_claims(
                self,
                raw_token: str,
                *,
                now: datetime,
            ) -> dict[str, object]:
                decode_calls.append((raw_token, now))
                return super()._decode_signed_claims(raw_token, now=now)

        source_key = _signing_key("private-audit-invalid-now-kid-marker", active=True)
        signing_key = TrackingSigningKey(
            kid=source_key.kid,
            private_key_pem=source_key.private_key_pem,
            active=True,
        )
        key_set = FormOwlSigningKeySet([signing_key])
        codec = TrackingTokenCodec(
            issuer=self.config.issuer,
            client_id=self.config.chatgpt_client_id,
            key_set=key_set,
        )
        session = _token_session(self.clock)
        raw_token = codec.issue_access_token(
            session=session,
            jti="jti_audit_invalid_now",
            now=self.clock.now(),
        )
        resource = self.config.resource
        required_scope = "formowl.use"

        token_snapshot = (id(raw_token), type(raw_token), repr(raw_token))
        resource_snapshot = (id(resource), type(resource), repr(resource))
        scope_snapshot = (id(required_scope), type(required_scope), repr(required_scope))
        session_identity = id(session)
        session_dict_identity = id(session.__dict__)
        session_state_snapshot = session.to_dict()
        codec_identity = id(codec)
        codec_dict_identity = id(codec.__dict__)
        codec_state_snapshot = dict(codec.__dict__)
        key_set_identity = id(key_set)
        key_tuple_identity = id(key_set._keys)
        key_set_state_snapshot = tuple(
            (id(key), key.kid, key.private_key_pem, key.active, key.verify_until)
            for key in key_set._keys
        )
        key_identity = id(signing_key)
        key_dict_identity = id(signing_key.__dict__)
        key_state_snapshot = (
            signing_key.kid,
            signing_key.private_key_pem,
            signing_key.active,
            signing_key.verify_until,
        )
        materialization_snapshot = tuple(materialized_public_kids)
        decode_snapshot = tuple(decode_calls)
        private_key_text = signing_key.private_key_pem.decode("ascii")
        self.assertEqual(materialized_public_kids, [])
        self.assertEqual(decode_calls, [])

        invalid_now_cases = (
            ("naive-datetime", self.clock.now().replace(tzinfo=None)),
            ("non-datetime", "raw-audit-verify-now-secret-marker"),
        )
        for case_name, invalid_now in invalid_now_cases:
            with self.subTest(case_name=case_name):
                input_snapshot = (id(invalid_now), type(invalid_now), repr(invalid_now))
                result: dict[str, object] | None = None

                with self.assertRaises(ValueError) as caught:
                    result = codec.verify_expired_access_token_for_audit(
                        raw_token,
                        resource=resource,
                        required_scope=required_scope,
                        now=invalid_now,  # type: ignore[arg-type]
                    )

                self.assertIsNone(result)
                self.assertIs(type(caught.exception), ValueError)
                self.assertEqual(
                    str(caught.exception),
                    "now must be a timezone-aware datetime",
                )
                for rendered in (str(caught.exception), repr(caught.exception)):
                    for private_marker in (
                        raw_token,
                        str(invalid_now),
                        repr(invalid_now),
                        signing_key.kid,
                        private_key_text,
                    ):
                        self.assertNotIn(private_marker, rendered)
                self.assertEqual(
                    (id(invalid_now), type(invalid_now), repr(invalid_now)),
                    input_snapshot,
                )
                self.assertEqual(tuple(materialized_public_kids), materialization_snapshot)
                self.assertEqual(tuple(decode_calls), decode_snapshot)
                self.assertEqual(
                    (id(raw_token), type(raw_token), repr(raw_token)),
                    token_snapshot,
                )
                self.assertEqual(
                    (id(resource), type(resource), repr(resource)),
                    resource_snapshot,
                )
                self.assertEqual(
                    (id(required_scope), type(required_scope), repr(required_scope)),
                    scope_snapshot,
                )
                self.assertEqual(id(session), session_identity)
                self.assertEqual(id(session.__dict__), session_dict_identity)
                self.assertEqual(session.to_dict(), session_state_snapshot)
                self.assertEqual(id(codec), codec_identity)
                self.assertEqual(id(codec.__dict__), codec_dict_identity)
                self.assertEqual(codec.__dict__, codec_state_snapshot)
                self.assertEqual(id(key_set), key_set_identity)
                self.assertEqual(id(key_set._keys), key_tuple_identity)
                self.assertEqual(
                    tuple(
                        (
                            id(key),
                            key.kid,
                            key.private_key_pem,
                            key.active,
                            key.verify_until,
                        )
                        for key in key_set._keys
                    ),
                    key_set_state_snapshot,
                )
                self.assertEqual(id(signing_key), key_identity)
                self.assertEqual(id(signing_key.__dict__), key_dict_identity)
                self.assertEqual(
                    (
                        signing_key.kid,
                        signing_key.private_key_pem,
                        signing_key.active,
                        signing_key.verify_until,
                    ),
                    key_state_snapshot,
                )

    def test_expired_access_token_for_audit_rejects_live_and_nonexpiry_failures(self) -> None:
        active = _signing_key("audit-denial-active", active=True)
        key_set = FormOwlSigningKeySet([active])
        codec = FormOwlTokenCodec(
            issuer=self.config.issuer,
            client_id=self.config.chatgpt_client_id,
            key_set=key_set,
        )
        session = _token_session(self.clock)
        valid_token = codec.issue_access_token(
            session=session,
            jti="jti_audit_denial",
            now=self.clock.now(),
        )
        now_epoch = self.clock.timestamp()
        base_claims = {
            "iss": self.config.issuer,
            "sub": session.user_id,
            "aud": session.resource,
            "scope": "formowl.use",
            "client_id": session.client_id,
            "sid": session.token_session_id,
            "jti": "jti_audit_denial",
            "iat": now_epoch,
            "nbf": now_epoch,
            "exp": now_epoch + 3600,
        }
        other_signing_key = _signing_key("audit-denial-active", active=True)
        cases = (
            (
                valid_token,
                self.config.resource,
                "formowl.use",
                self.clock.now(),
                "token_not_expired",
            ),
            (
                valid_token,
                "https://auth.example.test/other",
                "formowl.use",
                self.clock.now() + timedelta(hours=2),
                "token_resource_invalid",
            ),
            (
                _signed_formowl_token(active, {**base_claims, "iss": "https://evil.example"}),
                self.config.resource,
                "formowl.use",
                self.clock.now() + timedelta(hours=2),
                "token_issuer_invalid",
            ),
            (
                _signed_formowl_token(active, {**base_claims, "client_id": "other-client"}),
                self.config.resource,
                "formowl.use",
                self.clock.now() + timedelta(hours=2),
                "token_client_invalid",
            ),
            (
                valid_token,
                self.config.resource,
                "assets.write",
                self.clock.now() + timedelta(hours=2),
                "required_scope_missing",
            ),
            (
                _signed_formowl_token(other_signing_key, base_claims),
                self.config.resource,
                "formowl.use",
                self.clock.now() + timedelta(hours=2),
                "token_signature_invalid",
            ),
            (
                _signed_formowl_token(
                    active,
                    {
                        **base_claims,
                        "iat": now_epoch + 600,
                        "nbf": now_epoch + 600,
                        "exp": now_epoch + 1200,
                    },
                ),
                self.config.resource,
                "formowl.use",
                self.clock.now(),
                "token_issued_in_future",
            ),
        )
        key_snapshot = key_set.public_jwks(now=self.clock.now())
        codec_snapshot = dict(codec.__dict__)

        for raw_token, resource, required_scope, now, reason_code in cases:
            with self.subTest(reason_code=reason_code):
                with self.assertRaises(OAuthAccessDenied) as caught:
                    codec.verify_expired_access_token_for_audit(
                        raw_token,
                        resource=resource,
                        required_scope=required_scope,
                        now=now,
                    )
                self.assertEqual(caught.exception.reason_code, reason_code)
                self.assertNotIn(raw_token, str(caught.exception))

        self.assertEqual(key_set.public_jwks(now=self.clock.now()), key_snapshot)
        self.assertEqual(codec.__dict__, codec_snapshot)

    def test_formowl_temporal_claims_require_strict_integer_dates_and_valid_order(
        self,
    ) -> None:
        active = _signing_key("temporal-active", active=True)
        codec = FormOwlTokenCodec(
            issuer=self.config.issuer,
            client_id=self.config.chatgpt_client_id,
            key_set=FormOwlSigningKeySet([active]),
        )
        session = _token_session(self.clock)
        now_epoch = self.clock.timestamp()
        base_claims = {
            "iss": self.config.issuer,
            "sub": session.user_id,
            "aud": session.resource,
            "scope": " ".join(session.scopes),
            "client_id": session.client_id,
            "sid": session.token_session_id,
            "jti": "jti_temporal",
            "iat": now_epoch,
            "nbf": now_epoch,
            "exp": now_epoch + 3600,
        }
        cases = (
            ({"iat": float("nan")}, (), "token_iat_invalid"),
            ({"nbf": float("inf")}, (), "token_nbf_invalid"),
            ({"exp": float("-inf")}, (), "token_exp_invalid"),
            ({"exp": now_epoch + 1.5}, (), "token_exp_invalid"),
            ({"iat": str(now_epoch)}, (), "token_iat_invalid"),
            ({"nbf": True}, (), "token_nbf_invalid"),
            ({}, ("exp",), "token_exp_invalid"),
            ({"exp": now_epoch}, (), "token_temporal_order_invalid"),
            ({"nbf": now_epoch - 1}, (), "token_temporal_order_invalid"),
            ({"nbf": now_epoch + 3600}, (), "token_temporal_order_invalid"),
            ({"exp": now_epoch + 3601}, (), "token_lifetime_invalid"),
        )
        for overrides, removed, reason_code in cases:
            with self.subTest(reason_code=reason_code, overrides=overrides, removed=removed):
                claims = {**base_claims, **overrides}
                for field_name in removed:
                    claims.pop(field_name, None)
                token = _signed_formowl_token(active, claims)
                with self.assertRaises(OAuthAccessDenied) as caught:
                    codec.verify_access_token(
                        token,
                        resource=self.config.resource,
                        required_scope="formowl.use",
                        now=self.clock.now(),
                    )
                self.assertEqual(caught.exception.reason_code, reason_code)
                self.assertNotIn(token, str(caught.exception))

    def test_validate_claim_structure_rejects_invalid_ids_and_scopes_safely(
        self,
    ) -> None:
        signing_key = _signing_key("claim-structure-active", active=True)
        key_set = FormOwlSigningKeySet([signing_key])
        codec = FormOwlTokenCodec(
            issuer=self.config.issuer,
            client_id=self.config.chatgpt_client_id,
            key_set=key_set,
        )
        session = _token_session(self.clock)
        now_epoch = self.clock.timestamp()
        resource = self.config.resource
        required_scope = "formowl.use"
        base_claims: dict[str, object] = {
            "iss": self.config.issuer,
            "sub": session.user_id,
            "aud": resource,
            "scope": required_scope,
            "client_id": session.client_id,
            "sid": session.token_session_id,
            "jti": "jti_claim_structure",
            "iat": now_epoch,
            "nbf": now_epoch,
            "exp": now_epoch + 3600,
        }
        base_claims_snapshot = json.loads(json.dumps(base_claims))
        codec_identity = id(codec)
        codec_state_snapshot = dict(codec.__dict__)
        key_set_identity = id(key_set)
        key_tuple_identity = id(key_set._keys)
        key_set_state_snapshot = tuple(
            (id(key), key.kid, key.private_key_pem, key.active, key.verify_until)
            for key in key_set._keys
        )
        resource_snapshot = (id(resource), type(resource), repr(resource))
        required_scope_snapshot = (
            id(required_scope),
            type(required_scope),
            repr(required_scope),
        )
        private_key_text = signing_key.private_key_pem.decode("ascii")
        base_private_markers = (
            session.user_id,
            session.token_session_id,
            "jti_claim_structure",
            private_key_text,
        )

        def assert_denied(
            claims: dict[str, object],
            *,
            expected_reason: str,
            private_markers: tuple[str, ...],
        ) -> None:
            claims_identity = id(claims)
            claims_snapshot = json.loads(json.dumps(claims))
            nested_identities = {
                field_name: id(value)
                for field_name, value in claims.items()
                if isinstance(value, (dict, list))
            }
            result: None = None

            with self.assertRaises(OAuthAccessDenied) as caught:
                result = codec._validate_claim_structure(
                    claims,
                    resource=resource,
                    required_scope=required_scope,
                )

            self.assertIsNone(result)
            self.assertEqual(
                caught.exception.to_safe_dict(),
                {
                    "error": "invalid_token",
                    "reason_code": expected_reason,
                    "http_status": 401,
                },
            )
            rendered = f"{caught.exception!s} {caught.exception!r}"
            for private_marker in (*base_private_markers, *private_markers):
                self.assertNotIn(private_marker, rendered)
            self.assertEqual(id(claims), claims_identity)
            self.assertEqual(claims, claims_snapshot)
            self.assertEqual(
                {
                    field_name: id(value)
                    for field_name, value in claims.items()
                    if isinstance(value, (dict, list))
                },
                nested_identities,
            )
            self.assertEqual(id(codec), codec_identity)
            self.assertEqual(codec.__dict__, codec_state_snapshot)
            self.assertEqual(id(key_set), key_set_identity)
            self.assertEqual(id(key_set._keys), key_tuple_identity)
            self.assertEqual(
                tuple(
                    (
                        id(key),
                        key.kid,
                        key.private_key_pem,
                        key.active,
                        key.verify_until,
                    )
                    for key in key_set._keys
                ),
                key_set_state_snapshot,
            )
            self.assertEqual(
                (id(resource), type(resource), repr(resource)),
                resource_snapshot,
            )
            self.assertEqual(
                (id(required_scope), type(required_scope), repr(required_scope)),
                required_scope_snapshot,
            )
            self.assertEqual(base_claims, base_claims_snapshot)

        identity_cases: list[tuple[str, str, bool, object, str, tuple[str, ...]]] = []
        for field_name in ("sub", "sid", "jti"):
            reason_code = f"token_{field_name}_invalid"
            non_string_marker = f"raw-private-{field_name}-marker"
            unsafe_value = f"raw/private-{field_name}-marker"
            identity_cases.extend(
                (
                    (
                        f"{field_name}-missing",
                        field_name,
                        True,
                        None,
                        reason_code,
                        (),
                    ),
                    (
                        f"{field_name}-non-string",
                        field_name,
                        False,
                        [non_string_marker],
                        reason_code,
                        (non_string_marker,),
                    ),
                    (
                        f"{field_name}-unsafe-string",
                        field_name,
                        False,
                        unsafe_value,
                        reason_code,
                        (unsafe_value,),
                    ),
                )
            )

        for (
            case_name,
            field_name,
            remove_field,
            invalid_value,
            reason_code,
            private_markers,
        ) in identity_cases:
            with self.subTest(identity_case=case_name):
                claims = dict(base_claims)
                if remove_field:
                    claims.pop(field_name)
                else:
                    claims[field_name] = invalid_value
                assert_denied(
                    claims,
                    expected_reason=reason_code,
                    private_markers=private_markers,
                )

        scope_cases = (
            ("scope-missing", True, None, ()),
            ("scope-none", False, None, ()),
            ("scope-empty", False, "", ()),
            ("scope-whitespace", False, "   ", ()),
            (
                "scope-duplicate",
                False,
                "raw-private-scope-marker raw-private-scope-marker",
                ("raw-private-scope-marker",),
            ),
        )
        for case_name, remove_scope, invalid_scope, private_markers in scope_cases:
            with self.subTest(scope_case=case_name):
                claims = dict(base_claims)
                if remove_scope:
                    claims.pop("scope")
                else:
                    claims["scope"] = invalid_scope
                assert_denied(
                    claims,
                    expected_reason="token_scope_invalid",
                    private_markers=private_markers,
                )

    def test_validate_claim_time_window_enforces_exact_clock_skew_boundaries(
        self,
    ) -> None:
        signing_key = _signing_key("time-window-active", active=True)
        key_set = FormOwlSigningKeySet([signing_key])
        codec = FormOwlTokenCodec(
            issuer=self.config.issuer,
            client_id=self.config.chatgpt_client_id,
            key_set=key_set,
            clock_skew_seconds=30,
        )
        session = _token_session(self.clock)
        now = self.clock.now()
        now_epoch = int(now.timestamp())
        skew = codec.clock_skew_seconds
        base_claims: dict[str, object] = {
            "iss": self.config.issuer,
            "sub": session.user_id,
            "aud": session.resource,
            "scope": "formowl.use",
            "client_id": session.client_id,
            "sid": session.token_session_id,
            "jti": "jti_time_window",
            "iat": now_epoch,
            "nbf": now_epoch,
            "exp": now_epoch + 3600,
            "private_marker": "raw-temporal-claim-secret",
        }
        base_claims_snapshot = json.loads(json.dumps(base_claims))
        now_snapshot = (id(now), type(now), repr(now))
        codec_identity = id(codec)
        codec_state_snapshot = dict(codec.__dict__)
        key_set_identity = id(key_set)
        key_tuple_identity = id(key_set._keys)
        key_set_state_snapshot = tuple(
            (id(key), key.kid, key.private_key_pem, key.active, key.verify_until)
            for key in key_set._keys
        )
        private_key_text = signing_key.private_key_pem.decode("ascii")

        def assert_state_unchanged(claims: dict[str, object], snapshot: object) -> None:
            self.assertEqual(claims, snapshot)
            self.assertEqual((id(now), type(now), repr(now)), now_snapshot)
            self.assertEqual(id(codec), codec_identity)
            self.assertEqual(codec.__dict__, codec_state_snapshot)
            self.assertEqual(id(key_set), key_set_identity)
            self.assertEqual(id(key_set._keys), key_tuple_identity)
            self.assertEqual(
                tuple(
                    (
                        id(key),
                        key.kid,
                        key.private_key_pem,
                        key.active,
                        key.verify_until,
                    )
                    for key in key_set._keys
                ),
                key_set_state_snapshot,
            )
            self.assertEqual(base_claims, base_claims_snapshot)

        success_cases = (
            (
                "iat-at-positive-skew",
                {
                    "iat": now_epoch + skew,
                    "nbf": now_epoch + skew,
                    "exp": now_epoch + 3600,
                },
            ),
            (
                "nbf-at-positive-skew",
                {
                    "iat": now_epoch,
                    "nbf": now_epoch + skew,
                    "exp": now_epoch + 3600,
                },
            ),
            (
                "exp-one-second-inside-negative-skew",
                {
                    "iat": now_epoch - skew - 2,
                    "nbf": now_epoch - skew - 1,
                    "exp": now_epoch - skew + 1,
                },
            ),
        )
        for case_name, overrides in success_cases:
            with self.subTest(success_case=case_name):
                claims = {**base_claims, **overrides}
                claims_identity = id(claims)
                claims_snapshot = json.loads(json.dumps(claims))

                result = codec._validate_claim_time_window(claims, now=now)

                self.assertIsNone(result)
                self.assertEqual(id(claims), claims_identity)
                assert_state_unchanged(claims, claims_snapshot)

        denial_cases = (
            (
                "iat-beyond-positive-skew",
                {
                    "iat": now_epoch + skew + 1,
                    "nbf": now_epoch + skew,
                    "exp": now_epoch + 3600,
                },
                "token_issued_in_future",
            ),
            (
                "nbf-beyond-positive-skew",
                {
                    "iat": now_epoch,
                    "nbf": now_epoch + skew + 1,
                    "exp": now_epoch + 3600,
                },
                "token_not_yet_valid",
            ),
            (
                "exp-at-negative-skew-cutoff",
                {
                    "iat": now_epoch - skew - 2,
                    "nbf": now_epoch - skew - 1,
                    "exp": now_epoch - skew,
                },
                "token_expired",
            ),
        )
        for case_name, overrides, expected_reason in denial_cases:
            with self.subTest(denial_case=case_name):
                claims = {**base_claims, **overrides}
                claims_identity = id(claims)
                claims_snapshot = json.loads(json.dumps(claims))
                result: None = None

                with self.assertRaises(OAuthAccessDenied) as caught:
                    result = codec._validate_claim_time_window(claims, now=now)

                self.assertIsNone(result)
                self.assertEqual(
                    caught.exception.to_safe_dict(),
                    {
                        "error": "invalid_token",
                        "reason_code": expected_reason,
                        "http_status": 401,
                    },
                )
                rendered = f"{caught.exception!s} {caught.exception!r}"
                for private_marker in (
                    "raw-temporal-claim-secret",
                    session.user_id,
                    session.token_session_id,
                    "jti_time_window",
                    *(str(claims[field_name]) for field_name in ("iat", "nbf", "exp")),
                    private_key_text,
                ):
                    self.assertNotIn(private_marker, rendered)
                self.assertNotIn(repr(claims), rendered)
                self.assertEqual(id(claims), claims_identity)
                assert_state_unchanged(claims, claims_snapshot)

    def test_require_token_aware_rejects_none_offset_timezone_without_mutation(
        self,
    ) -> None:
        class NoneOffsetTimezone(tzinfo):
            def __init__(self, marker: str) -> None:
                self.marker = marker

            def utcoffset(self, value: datetime | None) -> None:
                return None

            def dst(self, value: datetime | None) -> None:
                return None

            def tzname(self, value: datetime | None) -> str:
                return self.marker

        valid_now = self.clock.now()
        valid_snapshot = (id(valid_now), type(valid_now), repr(valid_now))

        valid_result = require_token_aware(valid_now, "now")

        self.assertIsNone(valid_result)
        self.assertEqual(
            (id(valid_now), type(valid_now), repr(valid_now)),
            valid_snapshot,
        )

        timezone_marker = "raw-none-offset-timezone-secret-marker"
        none_offset_timezone = NoneOffsetTimezone(timezone_marker)
        invalid_now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=none_offset_timezone)
        self.assertIsNone(invalid_now.utcoffset())
        input_snapshot = (
            id(invalid_now),
            type(invalid_now),
            invalid_now.year,
            invalid_now.month,
            invalid_now.day,
            invalid_now.hour,
            invalid_now.minute,
            invalid_now.second,
            invalid_now.microsecond,
            invalid_now.fold,
            id(invalid_now.tzinfo),
            repr(invalid_now),
        )
        timezone_identity = id(none_offset_timezone)
        timezone_dict_identity = id(none_offset_timezone.__dict__)
        timezone_state_snapshot = dict(none_offset_timezone.__dict__)
        result: None = None

        with self.assertRaises(ValueError) as caught:
            result = require_token_aware(invalid_now, "now")

        self.assertIsNone(result)
        self.assertIs(type(caught.exception), ValueError)
        self.assertEqual(
            str(caught.exception),
            "now must be a timezone-aware datetime",
        )
        for rendered in (str(caught.exception), repr(caught.exception)):
            self.assertNotIn(timezone_marker, rendered)
        self.assertEqual(
            (
                id(invalid_now),
                type(invalid_now),
                invalid_now.year,
                invalid_now.month,
                invalid_now.day,
                invalid_now.hour,
                invalid_now.minute,
                invalid_now.second,
                invalid_now.microsecond,
                invalid_now.fold,
                id(invalid_now.tzinfo),
                repr(invalid_now),
            ),
            input_snapshot,
        )
        self.assertIs(invalid_now.tzinfo, none_offset_timezone)
        self.assertEqual(id(none_offset_timezone), timezone_identity)
        self.assertEqual(id(none_offset_timezone.__dict__), timezone_dict_identity)
        self.assertEqual(none_offset_timezone.__dict__, timezone_state_snapshot)

    def test_token_unverified_header_enforces_shape_and_safe_errors_without_mutation(
        self,
    ) -> None:
        import base64

        def encode_header(raw_header: bytes) -> str:
            return base64.urlsafe_b64encode(raw_header).rstrip(b"=").decode("ascii")

        valid_header = {
            "alg": "RS256",
            "kid": "token-dedicated-helper-key",
            "typ": "JWT",
        }
        valid_token = f"{_b64_json(valid_header)}.e30.signature"
        valid_token_snapshot = (id(valid_token), type(valid_token), repr(valid_token))

        parsed_header = token_unverified_header(valid_token)

        self.assertEqual(parsed_header, valid_header)
        self.assertEqual(
            (id(valid_token), type(valid_token), repr(valid_token)),
            valid_token_snapshot,
        )

        mutable_token = ["raw-mutable-token-private-marker"]
        overlong_marker = "raw-overlong-token-private-marker"
        overlong_token = overlong_marker + "x" * (16385 - len(overlong_marker))
        self.assertEqual(len(overlong_token), 16385)
        shape_cases = (
            ("non-string-none", None, ("None",)),
            (
                "non-string-mutable",
                mutable_token,
                ("raw-mutable-token-private-marker", repr(mutable_token)),
            ),
            ("empty", "", ()),
            ("overlong", overlong_token, (overlong_marker, overlong_token)),
            (
                "one-segment",
                "raw-private-one-segment-token",
                ("raw-private-one-segment-token",),
            ),
            (
                "two-segments",
                "raw-private-two-segment.token",
                ("raw-private-two-segment.token",),
            ),
            (
                "four-segments",
                "raw-private-four.segment.token.extra",
                ("raw-private-four.segment.token.extra",),
            ),
        )
        invalid_utf8_header = encode_header(b"\xff\xfe")
        invalid_json_marker = "raw-private-invalid-json-marker"
        invalid_json_header = encode_header(f'{{"marker":"{invalid_json_marker}"'.encode("utf-8"))
        non_object_marker = "raw-private-non-object-header-marker"
        non_object_header = encode_header(json.dumps([non_object_marker]).encode("utf-8"))
        trailing_base64_marker = "raw-private-trailing-base64-header-marker"
        trailing_base64_header = (
            encode_header(
                json.dumps({**valid_header, "marker": trailing_base64_marker}).encode("utf-8")
            )
            + "!!!!"
        )
        header_cases = (
            (
                "invalid-base64",
                "!!!!.raw-private-base64-token-marker.signature",
                (
                    "raw-private-base64-token-marker",
                    "!!!!.raw-private-base64-token-marker.signature",
                ),
            ),
            (
                "invalid-utf8",
                f"{invalid_utf8_header}.raw-private-utf8-token-marker.signature",
                (
                    "raw-private-utf8-token-marker",
                    f"{invalid_utf8_header}.raw-private-utf8-token-marker.signature",
                ),
            ),
            (
                "invalid-json",
                f"{invalid_json_header}.raw-private-json-token-marker.signature",
                (
                    invalid_json_marker,
                    "raw-private-json-token-marker",
                    f"{invalid_json_header}.raw-private-json-token-marker.signature",
                ),
            ),
            (
                "non-object-json",
                f"{non_object_header}.raw-private-list-token-marker.signature",
                (
                    non_object_marker,
                    "raw-private-list-token-marker",
                    f"{non_object_header}.raw-private-list-token-marker.signature",
                ),
            ),
            (
                "valid-json-with-invalid-base64-suffix",
                f"{trailing_base64_header}.raw-private-trailing-base64-token-marker.signature",
                (
                    trailing_base64_marker,
                    "raw-private-trailing-base64-token-marker",
                    (
                        f"{trailing_base64_header}."
                        "raw-private-trailing-base64-token-marker.signature"
                    ),
                ),
            ),
        )

        def assert_denied(
            unsafe_token: object,
            *,
            expected_reason: str,
            private_markers: tuple[str, ...],
        ) -> None:
            input_snapshot = (id(unsafe_token), type(unsafe_token), repr(unsafe_token))
            mutable_snapshot = list(unsafe_token) if isinstance(unsafe_token, list) else None
            result: dict[str, object] | None = None

            with self.assertRaises(OAuthAccessDenied) as caught:
                result = token_unverified_header(unsafe_token)  # type: ignore[arg-type]

            self.assertIsNone(result)
            self.assertIs(type(caught.exception), OAuthAccessDenied)
            self.assertEqual(
                caught.exception.to_safe_dict(),
                {
                    "error": "invalid_token",
                    "reason_code": expected_reason,
                    "http_status": 401,
                },
            )
            raw_markers = (
                str(unsafe_token),
                repr(unsafe_token),
                *private_markers,
            )
            for rendered in (str(caught.exception), repr(caught.exception)):
                for private_marker in raw_markers:
                    if private_marker:
                        self.assertNotIn(private_marker, rendered)
            self.assertEqual(
                (id(unsafe_token), type(unsafe_token), repr(unsafe_token)),
                input_snapshot,
            )
            if mutable_snapshot is not None:
                self.assertEqual(unsafe_token, mutable_snapshot)

        for case_name, unsafe_token, private_markers in shape_cases:
            with self.subTest(shape_case=case_name):
                assert_denied(
                    unsafe_token,
                    expected_reason="token_shape_invalid",
                    private_markers=private_markers,
                )

        for case_name, unsafe_token, private_markers in header_cases:
            with self.subTest(header_case=case_name):
                assert_denied(
                    unsafe_token,
                    expected_reason="token_header_invalid",
                    private_markers=private_markers,
                )

    def test_formowl_token_validation_helpers_reject_unsafe_shapes_without_leaks(self) -> None:
        self.assertEqual(_scope_tuple("formowl.use assets.read"), ("formowl.use", "assets.read"))
        private_scope_marker = "raw-private-scope-marker"
        unsafe_scope_cases = (
            (None, ("None",)),
            ("", ()),
            ("formowl.use formowl.use", ("formowl.use formowl.use",)),
            (
                f"formowl.use\t{private_scope_marker}",
                (
                    private_scope_marker,
                    f"formowl.use\t{private_scope_marker}",
                    repr(f"formowl.use\t{private_scope_marker}"),
                ),
            ),
            (
                f"formowl.use\n{private_scope_marker}",
                (
                    private_scope_marker,
                    f"formowl.use\n{private_scope_marker}",
                    repr(f"formowl.use\n{private_scope_marker}"),
                ),
            ),
        )
        for unsafe_scope, private_markers in unsafe_scope_cases:
            with self.subTest(unsafe_scope=unsafe_scope):
                with self.assertRaises(OAuthAccessDenied) as caught:
                    _scope_tuple(unsafe_scope)
                self.assertEqual(
                    caught.exception.to_safe_dict(),
                    {
                        "error": "invalid_token",
                        "reason_code": "token_scope_invalid",
                        "http_status": 401,
                    },
                )
                rendered = f"{caught.exception!s} {caught.exception!r}"
                for private_marker in private_markers:
                    self.assertNotIn(private_marker, rendered)

        header_token = f'{_b64_json({"alg": "RS256", "kid": "token-helper-key"})}.e30.sig'
        self.assertEqual(
            token_unverified_header(header_token),
            {"alg": "RS256", "kid": "token-helper-key"},
        )
        for unsafe_token in ("raw-formowl-token-secret", "!!!!.e30.sig", "a.b.c.d"):
            with self.subTest(unsafe_token=unsafe_token):
                with self.assertRaises(OAuthAccessDenied) as caught:
                    token_unverified_header(unsafe_token)
                self.assertNotIn(unsafe_token, str(caught.exception))

        require_token_aware(self.clock.now(), "now")
        for unsafe_now in (self.clock.now().replace(tzinfo=None), "raw-formowl-now-secret"):
            with self.subTest(unsafe_now=unsafe_now):
                with self.assertRaises(ValueError) as caught:
                    require_token_aware(unsafe_now, "now")  # type: ignore[arg-type]
                self.assertNotIn("raw-formowl-now-secret", str(caught.exception))

    def test_signing_key_rejects_invalid_identity_and_material_with_safe_errors(
        self,
    ) -> None:
        valid_private_pem = _signing_key(
            "signing-key-validation-fixture",
            active=True,
        ).private_key_pem
        valid_private_pem_text = valid_private_pem.decode("ascii")
        invalid_cases: tuple[
            tuple[object, object, str, tuple[str, ...]],
            ...,
        ] = (
            (
                "",
                valid_private_pem,
                "FormOwl signing key kid is invalid",
                (),
            ),
            (
                "unsafe/kid",
                valid_private_pem,
                "FormOwl signing key kid is invalid",
                (),
            ),
            (
                ["raw-private-kid-marker"],
                valid_private_pem,
                "FormOwl signing key kid is invalid",
                ("raw-private-kid-marker",),
            ),
            (
                "empty-private-key",
                b"",
                "FormOwl signing private key is required",
                (),
            ),
            (
                "nonbytes-private-key",
                "raw-nonbytes-private-key-marker",
                "FormOwl signing private key is required",
                ("raw-nonbytes-private-key-marker",),
            ),
            (
                "malformed-private-key",
                b"raw-malformed-private-key-marker",
                "FormOwl signing key is invalid",
                ("raw-malformed-private-key-marker",),
            ),
        )
        all_private_markers = (
            "raw-private-kid-marker",
            "raw-nonbytes-private-key-marker",
            "raw-malformed-private-key-marker",
            valid_private_pem_text,
        )

        for kid, private_key_pem, expected_message, case_markers in invalid_cases:
            with self.subTest(kid=kid, expected_message=expected_message):
                input_snapshot = (repr(kid), repr(private_key_pem))
                created: FormOwlSigningKey | None = None

                with self.assertRaises(ContractValidationError) as caught:
                    created = FormOwlSigningKey(
                        kid=kid,  # type: ignore[arg-type]
                        private_key_pem=private_key_pem,  # type: ignore[arg-type]
                    )

                self.assertIsNone(created)
                self.assertEqual(str(caught.exception), expected_message)
                rendered = f"{caught.exception!s} {caught.exception!r}"
                for private_marker in (*all_private_markers, *case_markers):
                    self.assertNotIn(private_marker, rendered)
                self.assertEqual((repr(kid), repr(private_key_pem)), input_snapshot)

    def test_signing_key_set_rejects_invalid_composition_without_leaks_or_mutation(
        self,
    ) -> None:
        duplicate = _signing_key("private-duplicate-kid-marker", active=True)
        inactive_one = _signing_key("private-inactive-one-marker", active=False)
        inactive_two = _signing_key("private-inactive-two-marker", active=False)
        active_one = _signing_key("private-active-one-marker", active=True)
        active_two = _signing_key("private-active-two-marker", active=True)
        cases = (
            ("empty", [], "FormOwl signing key set is empty"),
            (
                "duplicate-kid",
                [duplicate, duplicate],
                "FormOwl signing key ids must be unique",
            ),
            (
                "zero-active-single",
                [inactive_one],
                "FormOwl requires exactly one active signing key",
            ),
            (
                "zero-active-multiple",
                [inactive_one, inactive_two],
                "FormOwl requires exactly one active signing key",
            ),
            (
                "multiple-active",
                [active_one, active_two],
                "FormOwl requires exactly one active signing key",
            ),
        )

        for case_name, keys, expected_message in cases:
            with self.subTest(case_name=case_name):
                sequence_snapshot = tuple(keys)
                key_state_snapshot = tuple(
                    (
                        id(key),
                        key.kid,
                        key.private_key_pem,
                        key.active,
                        key.verify_until,
                    )
                    for key in keys
                )
                private_markers = tuple(
                    marker
                    for key in keys
                    for marker in (key.kid, key.private_key_pem.decode("ascii"))
                )
                created: FormOwlSigningKeySet | None = None

                with self.assertRaises(ContractValidationError) as caught:
                    created = FormOwlSigningKeySet(keys)

                self.assertIsNone(created)
                self.assertIs(type(caught.exception), ContractValidationError)
                self.assertEqual(str(caught.exception), expected_message)
                rendered = f"{caught.exception!s} {caught.exception!r}"
                for private_marker in private_markers:
                    self.assertNotIn(private_marker, rendered)
                self.assertEqual(tuple(keys), sequence_snapshot)
                self.assertEqual(
                    tuple(
                        (
                            id(key),
                            key.kid,
                            key.private_key_pem,
                            key.active,
                            key.verify_until,
                        )
                        for key in keys
                    ),
                    key_state_snapshot,
                )

    def test_public_jwks_rejects_invalid_now_without_materialization_or_leaks(
        self,
    ) -> None:
        materialized_kids: list[str] = []

        class TrackingSigningKey(FormOwlSigningKey):
            def public_jwk(self) -> dict[str, object]:
                materialized_kids.append(self.kid)
                return super().public_jwk()

        source_key = _signing_key("private-public-jwks-kid-marker", active=True)
        key = TrackingSigningKey(
            kid=source_key.kid,
            private_key_pem=source_key.private_key_pem,
            active=True,
        )
        key_set = FormOwlSigningKeySet([key])
        key_identity = id(key)
        key_state_snapshot = (
            key.kid,
            key.private_key_pem,
            key.active,
            key.verify_until,
        )
        key_set_identity = id(key_set)
        key_tuple_identity = id(key_set._keys)
        key_set_state_snapshot = tuple(
            (id(item), item.kid, item.private_key_pem, item.active, item.verify_until)
            for item in key_set._keys
        )
        private_key_text = key.private_key_pem.decode("ascii")
        cases = (
            ("naive-datetime", self.clock.now().replace(tzinfo=None)),
            ("non-datetime", "raw-now-secret-marker"),
        )

        for case_name, invalid_now in cases:
            with self.subTest(case_name=case_name):
                input_snapshot = (id(invalid_now), type(invalid_now), repr(invalid_now))
                materialization_snapshot = tuple(materialized_kids)
                result: dict[str, list[dict[str, object]]] | None = None

                with self.assertRaises(ValueError) as caught:
                    result = key_set.public_jwks(
                        now=invalid_now,  # type: ignore[arg-type]
                    )

                self.assertIsNone(result)
                self.assertIs(type(caught.exception), ValueError)
                self.assertEqual(
                    str(caught.exception),
                    "now must be a timezone-aware datetime",
                )
                rendered = f"{caught.exception!s} {caught.exception!r}"
                for private_marker in (
                    str(invalid_now),
                    repr(invalid_now),
                    key.kid,
                    private_key_text,
                ):
                    self.assertNotIn(private_marker, rendered)
                self.assertEqual(
                    (id(invalid_now), type(invalid_now), repr(invalid_now)),
                    input_snapshot,
                )
                self.assertEqual(tuple(materialized_kids), materialization_snapshot)
                self.assertEqual(materialized_kids, [])
                self.assertEqual(id(key), key_identity)
                self.assertEqual(
                    (
                        key.kid,
                        key.private_key_pem,
                        key.active,
                        key.verify_until,
                    ),
                    key_state_snapshot,
                )
                self.assertEqual(id(key_set), key_set_identity)
                self.assertEqual(id(key_set._keys), key_tuple_identity)
                self.assertEqual(
                    tuple(
                        (
                            id(item),
                            item.kid,
                            item.private_key_pem,
                            item.active,
                            item.verify_until,
                        )
                        for item in key_set._keys
                    ),
                    key_set_state_snapshot,
                )

    def test_verification_key_enforces_availability_and_safe_validation_order(
        self,
    ) -> None:
        materialized_kids: list[str] = []

        class TrackingSigningKey(FormOwlSigningKey):
            def public_jwk(self) -> dict[str, object]:
                materialized_kids.append(self.kid)
                return super().public_jwk()

        source_key = _signing_key("verification-key-material-source", active=True)
        now = self.clock.now()
        now_snapshot = (id(now), type(now), repr(now))

        def tracked_key(
            kid: str,
            *,
            active: bool,
            verify_until=None,
        ) -> TrackingSigningKey:
            return TrackingSigningKey(
                kid=kid,
                private_key_pem=source_key.private_key_pem,
                active=active,
                verify_until=verify_until,
            )

        active = tracked_key("private-verification-active-kid", active=True)
        overlap = tracked_key(
            "private-verification-overlap-kid",
            active=False,
            verify_until=now + timedelta(minutes=10),
        )
        expired = tracked_key(
            "private-verification-expired-kid",
            active=False,
            verify_until=now - timedelta(seconds=1),
        )
        no_overlap = tracked_key(
            "private-verification-no-overlap-kid",
            active=False,
        )
        keys = (active, overlap, expired, no_overlap)
        key_set = FormOwlSigningKeySet(keys)
        key_set_identity = id(key_set)
        key_tuple_identity = id(key_set._keys)
        key_set_state_snapshot = tuple(
            (id(key), key.kid, key.private_key_pem, key.active, key.verify_until)
            for key in key_set._keys
        )
        private_key_text = source_key.private_key_pem.decode("ascii")
        private_kids = tuple(key.kid for key in keys)

        def assert_key_set_unchanged() -> None:
            self.assertEqual((id(now), type(now), repr(now)), now_snapshot)
            self.assertEqual(id(key_set), key_set_identity)
            self.assertEqual(id(key_set._keys), key_tuple_identity)
            self.assertEqual(
                tuple(
                    (
                        id(key),
                        key.kid,
                        key.private_key_pem,
                        key.active,
                        key.verify_until,
                    )
                    for key in key_set._keys
                ),
                key_set_state_snapshot,
            )

        for expected_key in (active, overlap):
            with self.subTest(success_kid=expected_key.kid):
                input_snapshot = (
                    id(expected_key.kid),
                    type(expected_key.kid),
                    repr(expected_key.kid),
                )
                materialization_snapshot = tuple(materialized_kids)

                resolved = key_set.verification_key(expected_key.kid, now=now)

                public = resolved.as_dict(is_private=False)
                self.assertEqual(public["kid"], expected_key.kid)
                for private_name in ("d", "p", "q", "dp", "dq", "qi"):
                    self.assertNotIn(private_name, public)
                self.assertNotIn(private_key_text, repr(public))
                self.assertEqual(
                    (
                        id(expected_key.kid),
                        type(expected_key.kid),
                        repr(expected_key.kid),
                    ),
                    input_snapshot,
                )
                self.assertEqual(
                    tuple(materialized_kids),
                    (*materialization_snapshot, expected_key.kid),
                )
                assert_key_set_unchanged()

        denial_cases = (
            ("expired", expired.kid),
            ("no-overlap", no_overlap.kid),
            ("unknown", "raw-unknown-verification-kid-secret"),
        )
        for case_name, attempted_kid in denial_cases:
            with self.subTest(denial_case=case_name):
                input_snapshot = (
                    id(attempted_kid),
                    type(attempted_kid),
                    repr(attempted_kid),
                )
                materialization_snapshot = tuple(materialized_kids)
                resolved = None

                with self.assertRaises(OAuthAccessDenied) as caught:
                    resolved = key_set.verification_key(attempted_kid, now=now)

                self.assertIsNone(resolved)
                self.assertEqual(
                    caught.exception.to_safe_dict(),
                    {
                        "error": "invalid_token",
                        "reason_code": "signing_key_unavailable",
                        "http_status": 401,
                    },
                )
                rendered = f"{caught.exception!s} {caught.exception!r}"
                for private_marker in (
                    attempted_kid,
                    *private_kids,
                    private_key_text,
                ):
                    self.assertNotIn(private_marker, rendered)
                self.assertEqual(
                    (id(attempted_kid), type(attempted_kid), repr(attempted_kid)),
                    input_snapshot,
                )
                self.assertEqual(tuple(materialized_kids), materialization_snapshot)
                assert_key_set_unchanged()

        invalid_now_cases = (
            ("naive-datetime", now.replace(tzinfo=None)),
            ("non-datetime", "raw-verification-now-secret"),
        )
        for case_name, invalid_now in invalid_now_cases:
            with self.subTest(invalid_now_case=case_name):
                input_snapshot = (
                    id(invalid_now),
                    type(invalid_now),
                    repr(invalid_now),
                )
                materialization_snapshot = tuple(materialized_kids)
                resolved = None

                with self.assertRaises(ValueError) as caught:
                    resolved = key_set.verification_key(
                        active.kid,
                        now=invalid_now,  # type: ignore[arg-type]
                    )

                self.assertIsNone(resolved)
                self.assertIs(type(caught.exception), ValueError)
                self.assertEqual(
                    str(caught.exception),
                    "now must be a timezone-aware datetime",
                )
                rendered = f"{caught.exception!s} {caught.exception!r}"
                for private_marker in (
                    str(invalid_now),
                    repr(invalid_now),
                    *private_kids,
                    private_key_text,
                ):
                    self.assertNotIn(private_marker, rendered)
                self.assertEqual(
                    (id(invalid_now), type(invalid_now), repr(invalid_now)),
                    input_snapshot,
                )
                self.assertEqual(tuple(materialized_kids), materialization_snapshot)
                assert_key_set_unchanged()

    def test_jwks_rotation_keeps_only_unexpired_overlap_key(self) -> None:
        old = _signing_key(
            "old",
            active=False,
            verify_until=self.clock.now() + timedelta(minutes=10),
        )
        expired = _signing_key(
            "expired",
            active=False,
            verify_until=self.clock.now() - timedelta(seconds=1),
        )
        key_set = FormOwlSigningKeySet([old, expired, _signing_key("active", active=True)])
        kids = {item["kid"] for item in key_set.public_jwks(now=self.clock.now())["keys"]}
        self.assertEqual(kids, {"old", "active"})
        with self.assertRaises(OAuthAccessDenied):
            key_set.verification_key("expired", now=self.clock.now())

    def test_google_oidc_success_uses_fixed_endpoints_and_discards_access_token(self) -> None:
        google_key = _rsa_material("google-key")
        nonce = "google-nonce-value"
        id_token = _google_id_token(
            google_key,
            client_id=self.config.google_client_id,
            nonce=nonce,
            now_epoch=self.clock.timestamp(),
        )
        calls: list[tuple[str, str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((request.method, str(request.url), request.content.decode()))
            if str(request.url) == GOOGLE_DISCOVERY_URL:
                return httpx.Response(200, json=_discovery())
            if str(request.url) == GOOGLE_JWKS_URI:
                return httpx.Response(200, json={"keys": [google_key["public_jwk"]]})
            if str(request.url) == GOOGLE_TOKEN_ENDPOINT:
                form = parse_qs(request.content.decode())
                self.assertEqual(form["client_secret"], ["google-secret"])
                return httpx.Response(
                    200,
                    json={
                        "id_token": id_token,
                        "access_token": "google-access-token-must-be-discarded",
                        "token_type": "Bearer",
                    },
                )
            return httpx.Response(404)

        async def exercise() -> None:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
                client = GoogleOidcClient(config=self.config, http_client=http_client)
                authorization_url = client.build_authorization_url(
                    google_state="formowl-google-state",
                    google_nonce=nonce,
                )
                parsed = urlparse(authorization_url)
                query = parse_qs(parsed.query)
                self.assertEqual(
                    f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
                    GOOGLE_AUTHORIZATION_ENDPOINT,
                )
                self.assertEqual(query["state"], ["formowl-google-state"])
                self.assertEqual(query["nonce"], [nonce])
                self.assertEqual(query["prompt"], ["select_account"])
                identity = await client.authenticate_code(
                    "google-code",
                    expected_nonce_hash=hash_oauth_value("google_nonce", nonce),
                    now=self.clock.now(),
                )
                self.assertEqual(identity.subject, "google-subject-001")
                self.assertEqual(identity.email, "person@example.test")
                self.assertEqual(identity.display_name, "Safe Person")
                self.assertNotIn("google-access-token", str(client.__dict__))

        asyncio.run(exercise())
        self.assertEqual(
            [(method, url) for method, url, _body in calls],
            [
                ("POST", GOOGLE_TOKEN_ENDPOINT),
                ("GET", GOOGLE_DISCOVERY_URL),
                ("GET", GOOGLE_JWKS_URI),
            ],
        )
        self.assertNotIn("google-access-token-must-be-discarded", str(calls))

    def test_google_oidc_accepts_only_trusted_issuer_forms_and_canonicalizes(
        self,
    ) -> None:
        google_key = _rsa_material("google-issuer-key")
        nonce = "google-issuer-nonce"

        async def validate_issuer(issuer: str):
            id_token = _google_id_token(
                google_key,
                client_id=self.config.google_client_id,
                nonce=nonce,
                now_epoch=self.clock.timestamp(),
                overrides={"iss": issuer},
            )

            def handler(request: httpx.Request) -> httpx.Response:
                if str(request.url) == GOOGLE_DISCOVERY_URL:
                    return httpx.Response(200, json=_discovery())
                if str(request.url) == GOOGLE_JWKS_URI:
                    return httpx.Response(
                        200,
                        json={"keys": [google_key["public_jwk"]]},
                    )
                return httpx.Response(404)

            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
                client = GoogleOidcClient(config=self.config, http_client=http_client)
                return await client.validate_id_token(
                    id_token,
                    expected_nonce_hash=hash_oauth_value("google_nonce", nonce),
                    now=self.clock.now(),
                )

        for issuer in (GOOGLE_ISSUER, "accounts.google.com"):
            with self.subTest(trusted_issuer=issuer):
                identity = asyncio.run(validate_issuer(issuer))
                self.assertEqual(identity.issuer, GOOGLE_ISSUER)
                self.assertEqual(identity.subject, "google-subject-001")

        with self.assertRaises(OAuthAccessDenied) as caught:
            asyncio.run(validate_issuer("https://accounts.google.com/"))
        self.assertEqual(caught.exception.reason_code, "google_issuer_invalid")

    def test_legacy_google_issuer_reconnect_reuses_canonical_external_identity(
        self,
    ) -> None:
        fixture = BridgeFixture(
            _signing_key("google-legacy-reconnect-key", active=True),
            seed="google-legacy-reconnect",
        )
        fixture.seed_owner()
        fixture.seed_invitation()
        google_key = _rsa_material("google-legacy-issuer-key")
        tokens_by_code: dict[str, str] = {}

        class GoogleHttpClient:
            async def get(self, url: str, **_kwargs: object) -> httpx.Response:
                if url == GOOGLE_DISCOVERY_URL:
                    return httpx.Response(200, json=_discovery())
                if url == GOOGLE_JWKS_URI:
                    return httpx.Response(
                        200,
                        json={"keys": [google_key["public_jwk"]]},
                    )
                return httpx.Response(404)

            async def post(self, url: str, **kwargs: object) -> httpx.Response:
                if url != GOOGLE_TOKEN_ENDPOINT:
                    return httpx.Response(404)
                data = kwargs.get("data")
                if not isinstance(data, dict):
                    raise AssertionError("Google token request data is missing")
                google_code = data.get("code")
                if not isinstance(google_code, str):
                    raise AssertionError("Google token request code is missing")
                return httpx.Response(200, json={"id_token": tokens_by_code[google_code]})

        fixture.bridge.google_client = GoogleOidcClient(
            config=fixture.config,
            http_client=GoogleHttpClient(),
        )

        def login(*, issuer: str, client_state: str, google_code: str):
            started = fixture.bridge.start_authorization(
                fixture.authorization_request(client_state=client_state),
                now=fixture.clock.now(),
            )
            google_query = parse_qs(urlparse(started["authorization_url"]).query)
            google_state = google_query["state"][0]
            google_nonce = google_query["nonce"][0]
            tokens_by_code[google_code] = _google_id_token(
                google_key,
                client_id=fixture.config.google_client_id,
                nonce=google_nonce,
                now_epoch=fixture.clock.timestamp(),
                overrides={"iss": issuer},
            )
            callback = asyncio.run(
                fixture.bridge.complete_google_callback(
                    google_state=google_state,
                    google_code=google_code,
                    now=fixture.clock.now(),
                )
            )
            authorization_code = parse_qs(urlparse(callback["redirect_uri"]).query)["code"][0]
            token = fixture.bridge.exchange_authorization_code(
                fixture.token_request(authorization_code),
                now=fixture.clock.now(),
            )
            return fixture.bridge.authenticate_access_token(
                str(token["access_token"]),
                required_scope="formowl.use",
                resource=fixture.config.resource,
                now=fixture.clock.now(),
            )

        first_principal = login(
            issuer=GOOGLE_ISSUER,
            client_state="canonical-google-issuer",
            google_code="canonical-google-code",
        )
        second_principal = login(
            issuer="accounts.google.com",
            client_state="legacy-google-issuer",
            google_code="legacy-google-code",
        )

        self.assertEqual(second_principal.user_id, first_principal.user_id)
        self.assertEqual(
            second_principal.external_identity_id,
            first_principal.external_identity_id,
        )
        identities = fixture.repository.list("external_identities")
        self.assertEqual(len(identities), 1)
        self.assertEqual(identities[0]["issuer"], GOOGLE_ISSUER)
        self.assertEqual(identities[0]["subject"], "google-subject-001")
        self.assertEqual(len(fixture.repository.list("users")), 2)

    def test_google_authorization_url_rejects_missing_correlation_without_side_effects(
        self,
    ) -> None:
        calls: list[tuple[str, str]] = []

        class RecordingHttpClient:
            async def get(self, url: str, **_kwargs: object) -> httpx.Response:
                calls.append(("GET", url))
                raise AssertionError("unexpected Google HTTP GET")

            async def post(self, url: str, **_kwargs: object) -> httpx.Response:
                calls.append(("POST", url))
                raise AssertionError("unexpected Google HTTP POST")

        client = GoogleOidcClient(
            config=self.config,
            http_client=RecordingHttpClient(),
        )
        config_snapshot = dict(self.config.__dict__)
        client_snapshot = dict(client.__dict__)
        cases = (
            ("raw-google-state-secret", ""),
            ("", "raw-google-nonce-secret"),
        )

        for google_state, google_nonce in cases:
            with self.subTest(google_state=google_state, google_nonce=google_nonce):
                with self.assertRaises(OAuthAccessDenied) as caught:
                    client.build_authorization_url(
                        google_state=google_state,
                        google_nonce=google_nonce,
                    )

                denial = caught.exception
                self.assertEqual(
                    denial.to_safe_dict(),
                    {
                        "error": "invalid_request",
                        "reason_code": "google_correlation_missing",
                        "http_status": 400,
                    },
                )
                for raw_value in (google_state, google_nonce):
                    if raw_value:
                        self.assertNotIn(raw_value, str(denial))
                        self.assertNotIn(raw_value, str(denial.to_safe_dict()))
                self.assertEqual(calls, [])
                self.assertEqual(dict(self.config.__dict__), config_snapshot)
                self.assertEqual(client.__dict__, client_snapshot)

    def test_google_exchange_code_rejects_missing_code_before_http_or_state(self) -> None:
        class RecordingHttpClient:
            def __init__(self) -> None:
                self.get_calls: list[tuple[str, dict[str, object]]] = []
                self.post_calls: list[tuple[str, dict[str, object]]] = []

            async def get(self, url: str, **kwargs: object) -> httpx.Response:
                self.get_calls.append((url, dict(kwargs)))
                raise AssertionError("unexpected Google HTTP GET")

            async def post(self, url: str, **kwargs: object) -> httpx.Response:
                self.post_calls.append((url, dict(kwargs)))
                raise AssertionError("unexpected Google HTTP POST")

        http_client = RecordingHttpClient()
        client = GoogleOidcClient(config=self.config, http_client=http_client)
        config_snapshot = dict(self.config.__dict__)
        client_snapshot = dict(client.__dict__)
        invalid_codes: tuple[object, ...] = (
            "",
            ["raw-google-code-secret"],
        )
        input_snapshot = tuple(repr(value) for value in invalid_codes)

        async def exercise(google_code: object) -> None:
            with self.assertRaises(OAuthAccessDenied) as caught:
                await client.exchange_code(google_code)  # type: ignore[arg-type]

            denial = caught.exception
            safe_denial = denial.to_safe_dict()
            self.assertEqual(
                safe_denial,
                {
                    "error": "access_denied",
                    "reason_code": "google_code_missing",
                    "http_status": 400,
                },
            )
            self.assertNotIn("raw-google-code-secret", str(denial))
            self.assertNotIn("raw-google-code-secret", str(safe_denial))
            self.assertEqual(http_client.get_calls, [])
            self.assertEqual(http_client.post_calls, [])
            self.assertEqual(dict(self.config.__dict__), config_snapshot)
            self.assertEqual(client.__dict__, client_snapshot)
            self.assertIsNone(client._provider_metadata)
            self.assertIsNone(client._jwks)

        for google_code in invalid_codes:
            with self.subTest(google_code=google_code):
                asyncio.run(exercise(google_code))

        self.assertEqual(tuple(repr(value) for value in invalid_codes), input_snapshot)

    def test_google_oidc_rejects_signature_claim_nonce_and_verified_email_failures(self) -> None:
        key = _rsa_material("google-key")

        async def run_case(overrides: dict[str, object], expected_reason: str) -> None:
            token = _google_id_token(
                key,
                client_id=self.config.google_client_id,
                nonce="expected-nonce",
                now_epoch=self.clock.timestamp(),
                overrides=overrides,
            )

            def handler(request: httpx.Request) -> httpx.Response:
                if str(request.url) == GOOGLE_DISCOVERY_URL:
                    return httpx.Response(200, json=_discovery())
                if str(request.url) == GOOGLE_JWKS_URI:
                    return httpx.Response(200, json={"keys": [key["public_jwk"]]})
                if str(request.url) == GOOGLE_TOKEN_ENDPOINT:
                    return httpx.Response(200, json={"id_token": token})
                return httpx.Response(404)

            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
                client = GoogleOidcClient(config=self.config, http_client=http_client)
                with self.assertRaises(OAuthAccessDenied) as caught:
                    await client.authenticate_code(
                        "google-code",
                        expected_nonce_hash=hash_oauth_value(
                            "google_nonce",
                            "expected-nonce",
                        ),
                        now=self.clock.now(),
                    )
                self.assertEqual(caught.exception.reason_code, expected_reason)
                self.assertNotIn("google-code", str(caught.exception))

        cases = (
            ({"iss": "https://evil.example"}, "google_issuer_invalid"),
            ({"aud": "wrong-client"}, "google_audience_invalid"),
            ({"azp": "wrong-client"}, "google_authorized_party_invalid"),
            ({"exp": self.clock.timestamp() - 60}, "google_token_expired"),
            ({"nbf": self.clock.timestamp() + 600}, "google_token_not_yet_valid"),
            ({"nonce": "wrong-nonce"}, "google_nonce_invalid"),
            ({"sub": ""}, "google_subject_invalid"),
            ({"email_verified": False}, "google_email_unverified"),
        )
        for overrides, reason in cases:
            with self.subTest(reason=reason):
                asyncio.run(run_case(overrides, reason))

        other_key = _rsa_material(str(key["kid"]))
        token = _google_id_token(
            other_key,
            client_id=self.config.google_client_id,
            nonce="expected-nonce",
            now_epoch=self.clock.timestamp(),
        )

        async def invalid_signature() -> None:
            def handler(request: httpx.Request) -> httpx.Response:
                if str(request.url) == GOOGLE_DISCOVERY_URL:
                    return httpx.Response(200, json=_discovery())
                if str(request.url) == GOOGLE_JWKS_URI:
                    return httpx.Response(200, json={"keys": [key["public_jwk"]]})
                return httpx.Response(200, json={"id_token": token})

            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
                client = GoogleOidcClient(config=self.config, http_client=http_client)
                with self.assertRaises(OAuthAccessDenied) as caught:
                    await client.authenticate_code(
                        "google-code",
                        expected_nonce_hash=hash_oauth_value(
                            "google_nonce",
                            "expected-nonce",
                        ),
                        now=self.clock.now(),
                    )
                self.assertEqual(caught.exception.reason_code, "google_signature_invalid")

        asyncio.run(invalid_signature())

    def test_google_temporal_claims_require_strict_integer_dates_and_valid_order(
        self,
    ) -> None:
        key = _rsa_material("google-temporal-key")
        now_epoch = self.clock.timestamp()
        cases = (
            ({"exp": float("nan")}, (), "google_exp_invalid"),
            ({"iat": float("inf")}, (), "google_iat_invalid"),
            ({"nbf": float("-inf")}, (), "google_nbf_invalid"),
            ({"exp": now_epoch + 1.5}, (), "google_exp_invalid"),
            ({"iat": str(now_epoch)}, (), "google_iat_invalid"),
            ({"nbf": False}, (), "google_nbf_invalid"),
            ({}, ("exp",), "google_exp_invalid"),
            ({"exp": now_epoch}, (), "google_temporal_order_invalid"),
            (
                {"nbf": now_epoch + 601, "exp": now_epoch + 600},
                (),
                "google_temporal_order_invalid",
            ),
        )

        async def run_case(
            overrides: dict[str, object],
            removed: tuple[str, ...],
            reason_code: str,
        ) -> None:
            token = _google_id_token(
                key,
                client_id=self.config.google_client_id,
                nonce="expected-nonce",
                now_epoch=now_epoch,
                overrides=overrides,
                remove_claims=removed,
            )

            def handler(request: httpx.Request) -> httpx.Response:
                if str(request.url) == GOOGLE_DISCOVERY_URL:
                    return httpx.Response(200, json=_discovery())
                if str(request.url) == GOOGLE_JWKS_URI:
                    return httpx.Response(200, json={"keys": [key["public_jwk"]]})
                return httpx.Response(200, json={"id_token": token})

            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
                client = GoogleOidcClient(config=self.config, http_client=http_client)
                with self.assertRaises(OAuthAccessDenied) as caught:
                    await client.authenticate_code(
                        "google-code",
                        expected_nonce_hash=hash_oauth_value(
                            "google_nonce",
                            "expected-nonce",
                        ),
                        now=self.clock.now(),
                    )
                self.assertEqual(caught.exception.reason_code, reason_code)
                self.assertNotIn(token, str(caught.exception))
                self.assertNotIn("google-code", str(caught.exception))

        for overrides, removed, reason_code in cases:
            with self.subTest(reason_code=reason_code, overrides=overrides, removed=removed):
                asyncio.run(run_case(overrides, removed, reason_code))

        long_lived = _google_id_token(
            key,
            client_id=self.config.google_client_id,
            nonce="expected-nonce",
            now_epoch=now_epoch,
            overrides={"exp": now_epoch + 86400},
        )

        async def validate_long_lived_token() -> None:
            def handler(request: httpx.Request) -> httpx.Response:
                if str(request.url) == GOOGLE_DISCOVERY_URL:
                    return httpx.Response(200, json=_discovery())
                if str(request.url) == GOOGLE_JWKS_URI:
                    return httpx.Response(200, json={"keys": [key["public_jwk"]]})
                return httpx.Response(200, json={"id_token": long_lived})

            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
                client = GoogleOidcClient(config=self.config, http_client=http_client)
                identity = await client.authenticate_code(
                    "google-code",
                    expected_nonce_hash=hash_oauth_value(
                        "google_nonce",
                        "expected-nonce",
                    ),
                    now=self.clock.now(),
                )
                self.assertEqual(identity.subject, "google-subject-001")

        asyncio.run(validate_long_lived_token())

    def test_google_temporal_denial_precedes_callback_mutation(self) -> None:
        fixture = BridgeFixture(
            _signing_key("callback-temporal-key", active=True),
            seed="google-temporal-callback",
        )
        fixture.seed_owner()
        fixture.seed_invitation()
        state = fixture.start_authorization()
        nonce = fixture.google_client.last_nonce
        self.assertIsNotNone(nonce)
        google_key = _rsa_material("google-temporal-callback-key")
        id_token = _google_id_token(
            google_key,
            client_id=fixture.config.google_client_id,
            nonce=str(nonce),
            now_epoch=fixture.clock.timestamp(),
            overrides={"exp": float("nan")},
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == GOOGLE_DISCOVERY_URL:
                return httpx.Response(200, json=_discovery())
            if str(request.url) == GOOGLE_JWKS_URI:
                return httpx.Response(200, json={"keys": [google_key["public_jwk"]]})
            return httpx.Response(200, json={"id_token": id_token})

        async def exercise() -> None:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
                google_client = GoogleOidcClient(
                    config=fixture.config,
                    http_client=http_client,
                )
                bridge = FormOwlOAuthBridge(
                    config=fixture.config,
                    repository=fixture.repository,
                    google_client=google_client,
                    token_codec=fixture.bridge.token_codec,
                    random_bytes=fixture.rng.bytes,
                )
                snapshot = fixture.repository.snapshot_bytes()
                with self.assertRaises(OAuthAccessDenied) as caught:
                    await bridge.complete_google_callback(
                        google_state=state,
                        google_code="google-temporal-code",
                        now=fixture.clock.now(),
                    )
                self.assertEqual(caught.exception.reason_code, "google_exp_invalid")
                self.assertNotIn(id_token, str(caught.exception))
                self.assertNotIn("google-temporal-code", str(caught.exception))
                fixture.repository.assert_unchanged(snapshot)

        asyncio.run(exercise())
        self.assertEqual(fixture.repository.list("external_identities"), [])
        self.assertEqual(fixture.repository.list("oauth_client_authorizations"), [])
        self.assertEqual(fixture.repository.list("oauth_authorization_codes"), [])
        self.assertEqual(fixture.repository.list("oauth_token_sessions"), [])
        self.assertEqual(
            fixture.repository.list("oauth_transactions")[0]["status"],
            "pending",
        )

    def test_google_discovery_and_http_failures_return_safe_codes(self) -> None:
        async def exercise() -> None:
            def handler(request: httpx.Request) -> httpx.Response:
                if str(request.url) == GOOGLE_DISCOVERY_URL:
                    return httpx.Response(
                        200,
                        json={**_discovery(), "token_endpoint": "https://evil.example/token"},
                    )
                return httpx.Response(503, text="google raw failure body with token")

            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
                client = GoogleOidcClient(config=self.config, http_client=http_client)
                with self.assertRaises(OAuthAccessDenied) as caught:
                    await client.load_provider_metadata()
                self.assertEqual(caught.exception.reason_code, "google_discovery_untrusted")
                self.assertNotIn("evil.example", str(caught.exception))

                with self.assertRaises(OAuthAccessDenied) as caught:
                    await client.exchange_code("google-secret-code")
                self.assertEqual(caught.exception.reason_code, "google_code_exchange_failed")
                self.assertNotIn("google-secret-code", str(caught.exception))

        asyncio.run(exercise())

    def test_google_safe_get_failures_return_exact_denial_without_state(self) -> None:
        async def run_case(mode: str, private_markers: tuple[str, ...]) -> None:
            config = _config()

            class RecordingHttpClient:
                def __init__(self) -> None:
                    self.get_calls: list[tuple[str, dict[str, object]]] = []
                    self.post_calls: list[tuple[str, dict[str, object]]] = []

                async def get(self, url: str, **kwargs: object) -> httpx.Response:
                    self.get_calls.append((url, dict(kwargs)))
                    if mode == "http_error":
                        raise httpx.ConnectError(
                            "raw-google-http-error-secret https://secret.example/private",
                            request=httpx.Request("GET", url),
                        )
                    return httpx.Response(
                        503,
                        text="raw-google-response-body-secret",
                    )

                async def post(self, url: str, **kwargs: object) -> httpx.Response:
                    self.post_calls.append((url, dict(kwargs)))
                    raise AssertionError("unexpected Google HTTP POST")

            http_client = RecordingHttpClient()
            client = GoogleOidcClient(config=config, http_client=http_client)
            config_snapshot = dict(config.__dict__)
            client_snapshot = dict(client.__dict__)

            with self.assertRaises(OAuthAccessDenied) as caught:
                await client.load_provider_metadata()

            denial = caught.exception
            safe_denial = denial.to_safe_dict()
            self.assertEqual(
                safe_denial,
                {
                    "error": "server_error",
                    "reason_code": "google_metadata_unavailable",
                    "http_status": 500,
                },
            )
            for private_marker in private_markers:
                self.assertNotIn(private_marker, str(denial))
                self.assertNotIn(private_marker, str(safe_denial))
            self.assertEqual(
                http_client.get_calls,
                [
                    (
                        GOOGLE_DISCOVERY_URL,
                        {
                            "headers": {"Accept": "application/json"},
                            "timeout": 10.0,
                            "follow_redirects": False,
                        },
                    )
                ],
            )
            self.assertEqual(http_client.post_calls, [])
            self.assertEqual(dict(config.__dict__), config_snapshot)
            self.assertEqual(client.__dict__, client_snapshot)
            self.assertIsNone(client._provider_metadata)
            self.assertIsNone(client._jwks)

        cases = (
            (
                "http_error",
                (
                    "raw-google-http-error-secret",
                    "https://secret.example/private",
                ),
            ),
            (
                "non_200",
                ("raw-google-response-body-secret",),
            ),
        )
        for mode, private_markers in cases:
            with self.subTest(mode=mode):
                asyncio.run(run_case(mode, private_markers))

    def test_google_load_jwks_rejects_invalid_keys_without_caching_and_recovers(
        self,
    ) -> None:
        async def run_case(
            invalid_jwks: dict[str, object],
            private_markers: tuple[str, ...],
        ) -> None:
            config = _config()
            valid_key = _rsa_material("google-jwks-recovery-key")["public_jwk"]
            valid_jwks = {"keys": [valid_key]}
            invalid_snapshot = json.loads(json.dumps(invalid_jwks))

            class RecordingHttpClient:
                def __init__(self) -> None:
                    self.get_calls: list[tuple[str, dict[str, object]]] = []
                    self.post_calls: list[tuple[str, dict[str, object]]] = []
                    self.jwks_request_count = 0

                async def get(self, url: str, **kwargs: object) -> httpx.Response:
                    self.get_calls.append((url, dict(kwargs)))
                    if url == GOOGLE_DISCOVERY_URL:
                        return httpx.Response(200, json=_discovery())
                    if url == GOOGLE_JWKS_URI:
                        self.jwks_request_count += 1
                        payload = invalid_jwks if self.jwks_request_count == 1 else valid_jwks
                        return httpx.Response(200, json=payload)
                    raise AssertionError("unexpected Google HTTP GET URL")

                async def post(self, url: str, **kwargs: object) -> httpx.Response:
                    self.post_calls.append((url, dict(kwargs)))
                    raise AssertionError("unexpected Google HTTP POST")

            http_client = RecordingHttpClient()
            client = GoogleOidcClient(config=config, http_client=http_client)
            config_snapshot = dict(config.__dict__)

            with self.assertRaises(OAuthAccessDenied) as caught:
                await client.load_jwks()

            denial = caught.exception
            safe_denial = denial.to_safe_dict()
            self.assertEqual(
                safe_denial,
                {
                    "error": "server_error",
                    "reason_code": "google_jwks_invalid",
                    "http_status": 500,
                },
            )
            for private_marker in private_markers:
                self.assertNotIn(private_marker, str(denial))
                self.assertNotIn(private_marker, str(safe_denial))
            self.assertEqual(invalid_jwks, invalid_snapshot)
            self.assertEqual(client._provider_metadata, _discovery())
            self.assertIsNone(client._jwks)
            self.assertEqual(dict(config.__dict__), config_snapshot)
            self.assertEqual(http_client.post_calls, [])

            recovered = await client.load_jwks()

            self.assertEqual(recovered, valid_jwks)
            self.assertEqual(client._jwks, valid_jwks)
            expected_options = {
                "headers": {"Accept": "application/json"},
                "timeout": 10.0,
                "follow_redirects": False,
            }
            self.assertEqual(
                http_client.get_calls,
                [
                    (GOOGLE_DISCOVERY_URL, expected_options),
                    (GOOGLE_JWKS_URI, expected_options),
                    (GOOGLE_JWKS_URI, expected_options),
                ],
            )
            self.assertEqual(http_client.post_calls, [])
            self.assertEqual(dict(config.__dict__), config_snapshot)
            self.assertEqual(invalid_jwks, invalid_snapshot)

        cases = (
            (
                {
                    "keys": [],
                    "diagnostic": "raw-google-empty-jwks-secret",
                },
                ("raw-google-empty-jwks-secret",),
            ),
            (
                {
                    "keys": [
                        {
                            "kid": "raw-google-malformed-jwk-secret",
                            "kty": "EC",
                            "alg": "RS256",
                        }
                    ]
                },
                ("raw-google-malformed-jwk-secret",),
            ),
        )
        for invalid_jwks, private_markers in cases:
            with self.subTest(invalid_jwks=invalid_jwks):
                asyncio.run(run_case(invalid_jwks, private_markers))

    def test_require_google_aware_rejects_none_offset_timezone_without_mutation(
        self,
    ) -> None:
        class NoneOffsetTimezone(tzinfo):
            def __init__(self, marker: str) -> None:
                self.marker = marker

            def utcoffset(self, value: datetime | None) -> None:
                return None

            def dst(self, value: datetime | None) -> None:
                return None

            def tzname(self, value: datetime | None) -> str:
                return self.marker

        valid_now = self.clock.now()
        valid_snapshot = (id(valid_now), type(valid_now), repr(valid_now))

        valid_result = require_google_aware(valid_now)

        self.assertIsNone(valid_result)
        self.assertEqual(
            (id(valid_now), type(valid_now), repr(valid_now)),
            valid_snapshot,
        )

        timezone_marker = "raw-google-none-offset-timezone-secret-marker"
        none_offset_timezone = NoneOffsetTimezone(timezone_marker)
        invalid_now = datetime(2026, 2, 3, 4, 5, 6, tzinfo=none_offset_timezone)
        self.assertIsNone(invalid_now.utcoffset())
        input_snapshot = (
            id(invalid_now),
            type(invalid_now),
            invalid_now.year,
            invalid_now.month,
            invalid_now.day,
            invalid_now.hour,
            invalid_now.minute,
            invalid_now.second,
            invalid_now.microsecond,
            invalid_now.fold,
            id(invalid_now.tzinfo),
            repr(invalid_now),
        )
        timezone_identity = id(none_offset_timezone)
        timezone_dict_identity = id(none_offset_timezone.__dict__)
        timezone_state_snapshot = dict(none_offset_timezone.__dict__)
        result: None = None

        with self.assertRaises(ValueError) as caught:
            result = require_google_aware(invalid_now)

        self.assertIsNone(result)
        self.assertIs(type(caught.exception), ValueError)
        self.assertEqual(
            str(caught.exception),
            "now must be a timezone-aware datetime",
        )
        for rendered in (str(caught.exception), repr(caught.exception)):
            self.assertNotIn(timezone_marker, rendered)
        self.assertEqual(
            (
                id(invalid_now),
                type(invalid_now),
                invalid_now.year,
                invalid_now.month,
                invalid_now.day,
                invalid_now.hour,
                invalid_now.minute,
                invalid_now.second,
                invalid_now.microsecond,
                invalid_now.fold,
                id(invalid_now.tzinfo),
                repr(invalid_now),
            ),
            input_snapshot,
        )
        self.assertIs(invalid_now.tzinfo, none_offset_timezone)
        self.assertEqual(id(none_offset_timezone), timezone_identity)
        self.assertEqual(id(none_offset_timezone.__dict__), timezone_dict_identity)
        self.assertEqual(none_offset_timezone.__dict__, timezone_state_snapshot)

    def test_google_oidc_validation_helpers_reject_unsafe_shapes_without_leaks(self) -> None:
        self.assertEqual(_safe_display_name("  Safe   Person  "), "Safe Person")
        for unsafe_name in (None, "   ", "control\x00name", "x" * 121):
            with self.subTest(unsafe_name=unsafe_name):
                self.assertEqual(_safe_display_name(unsafe_name), "FormOwl User")

        public_jwk = {"kid": "google-helper-key", "kty": "RSA", "alg": "RS256"}
        self.assertEqual(
            _select_jwk({"keys": [public_jwk]}, "google-helper-key"),
            public_jwk,
        )
        invalid_jwks = (
            {},
            {"keys": "not-a-list"},
            {"keys": [public_jwk, public_jwk]},
            {"keys": [{**public_jwk, "kty": "EC"}]},
            {"keys": [{**public_jwk, "alg": "HS256"}]},
        )
        for jwks in invalid_jwks:
            with self.subTest(jwks=jwks):
                self.assertIsNone(_select_jwk(jwks, "google-helper-key"))

        header_token = f'{_b64_json({"alg": "RS256", "kid": "google-helper-key"})}.e30.sig'
        self.assertEqual(
            google_unverified_header(header_token),
            {"alg": "RS256", "kid": "google-helper-key"},
        )
        for unsafe_token in ("raw-google-token-secret", "!!!!.e30.sig", "a.b.c.d"):
            with self.subTest(unsafe_token=unsafe_token):
                with self.assertRaises(OAuthAccessDenied) as caught:
                    google_unverified_header(unsafe_token)
                self.assertNotIn(unsafe_token, str(caught.exception))

        self.assertEqual(
            google_json_object(httpx.Response(200, json={"status": "ok"}), "json_invalid"),
            {"status": "ok"},
        )
        invalid_responses = (
            httpx.Response(200, json=["raw-google-json-secret"]),
            httpx.Response(200, text="raw-google-json-secret"),
        )
        for response in invalid_responses:
            with self.subTest(response=response):
                with self.assertRaises(OAuthAccessDenied) as caught:
                    google_json_object(response, "google_helper_json_invalid")
                self.assertEqual(caught.exception.reason_code, "google_helper_json_invalid")
                self.assertNotIn("raw-google-json-secret", str(caught.exception))

        require_google_aware(self.clock.now())
        for unsafe_now in (self.clock.now().replace(tzinfo=None), "raw-google-now-secret"):
            with self.subTest(unsafe_now=unsafe_now):
                with self.assertRaises(ValueError) as caught:
                    require_google_aware(unsafe_now)  # type: ignore[arg-type]
                self.assertNotIn("raw-google-now-secret", str(caught.exception))


def _config() -> OAuthBridgeConfig:
    return OAuthBridgeConfig(
        issuer="https://auth.example.test",
        resource="https://auth.example.test/mcp",
        chatgpt_client_id="chatgpt-client",
        chatgpt_redirect_uri="https://chatgpt.com/connector/oauth/callback",
        google_client_id="google-client",
        google_client_secret="google-secret",
        google_redirect_uri="https://auth.example.test/oauth/google/callback",
        state_encryption_key=Fernet.generate_key().decode("ascii"),
    )


def _rsa_material(kid: str) -> dict[str, object]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    key = JsonWebKey.import_key(
        private_key_pem,
        {"kid": kid, "use": "sig", "alg": "RS256"},
    )
    return {
        "kid": kid,
        "private_key": key,
        "public_jwk": key.as_dict(is_private=False),
    }


def _signed_formowl_token(
    signing_key: FormOwlSigningKey,
    claims: dict[str, object],
) -> str:
    encoded = _JWT.encode(
        {"alg": "RS256", "kid": signing_key.kid, "typ": "JWT"},
        claims,
        signing_key.private_key(),
    )
    return encoded.decode("ascii") if isinstance(encoded, bytes) else str(encoded)


def _signing_key(
    kid: str,
    *,
    active: bool,
    verify_until=None,
) -> FormOwlSigningKey:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return FormOwlSigningKey(
        kid=kid,
        private_key_pem=pem,
        active=active,
        verify_until=verify_until,
    )


def _token_session(clock: FakeClock) -> OAuthTokenSession:
    return OAuthTokenSession(
        token_session_id="oauthsid_001",
        user_id="user_001",
        external_identity_id="extid_001",
        oauth_client_authorization_id="clientauth_001",
        client_id="chatgpt-client",
        current_workspace_id="workspace_001",
        resource="https://auth.example.test/mcp",
        scopes=("formowl.use",),
        token_jti_hash="sha256:" + "a" * 64,
        issued_at=clock.now_iso(),
        expires_at=(clock.now() + timedelta(hours=1)).isoformat(),
    )


def _google_id_token(
    material: dict[str, object],
    *,
    client_id: str,
    nonce: str,
    now_epoch: int,
    overrides: dict[str, object] | None = None,
    headers: dict[str, object] | None = None,
    remove_claims: tuple[str, ...] = (),
) -> str:
    claims = {
        "iss": GOOGLE_ISSUER,
        "sub": "google-subject-001",
        "aud": client_id,
        "azp": client_id,
        "iat": now_epoch,
        "nbf": now_epoch,
        "exp": now_epoch + 600,
        "nonce": nonce,
        "email": "Person@Example.TEST",
        "email_verified": True,
        "name": "  Safe   Person  ",
        **dict(overrides or {}),
    }
    for field_name in remove_claims:
        claims.pop(field_name, None)
    header = {
        "alg": "RS256",
        "kid": material["kid"],
        "typ": "JWT",
        **dict(headers or {}),
    }
    encoded = _JWT.encode(header, claims, material["private_key"])
    return encoded.decode("ascii") if isinstance(encoded, bytes) else str(encoded)


def _discovery() -> dict[str, object]:
    return {
        "issuer": GOOGLE_ISSUER,
        "authorization_endpoint": GOOGLE_AUTHORIZATION_ENDPOINT,
        "token_endpoint": GOOGLE_TOKEN_ENDPOINT,
        "jwks_uri": GOOGLE_JWKS_URI,
        "id_token_signing_alg_values_supported": ["RS256"],
    }


def _b64_json(value: dict[str, object]) -> str:
    import base64

    raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


if __name__ == "__main__":
    unittest.main()
