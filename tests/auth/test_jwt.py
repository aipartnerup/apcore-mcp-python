"""Tests for JWTAuthenticator."""

from __future__ import annotations

import time

import jwt as pyjwt
import pytest

from apcore_mcp.auth.jwt import ClaimMapping, JWTAuthenticator
from apcore_mcp.auth.protocol import Authenticator

SECRET = "test-secret-key"


def _make_token(payload: dict, key: str = SECRET, algorithm: str = "HS256") -> str:
    return pyjwt.encode(payload, key, algorithm=algorithm)


class TestJWTAuthenticatorProtocol:
    def test_implements_authenticator_protocol(self):
        auth = JWTAuthenticator(key=SECRET)
        assert isinstance(auth, Authenticator)


class TestAuthenticate:
    def test_valid_token(self):
        auth = JWTAuthenticator(key=SECRET)
        token = _make_token({"sub": "user-1"})
        identity = auth.authenticate({"authorization": f"Bearer {token}"})
        assert identity is not None
        assert identity.id == "user-1"
        assert identity.type == "user"
        assert identity.roles == ()

    def test_valid_token_with_roles(self):
        auth = JWTAuthenticator(key=SECRET)
        token = _make_token({"sub": "user-2", "roles": ["admin", "editor"]})
        identity = auth.authenticate({"authorization": f"Bearer {token}"})
        assert identity is not None
        assert identity.roles == ("admin", "editor")

    def test_valid_token_with_type(self):
        auth = JWTAuthenticator(key=SECRET)
        token = _make_token({"sub": "svc-1", "type": "service"})
        identity = auth.authenticate({"authorization": f"Bearer {token}"})
        assert identity is not None
        assert identity.type == "service"

    def test_missing_authorization_header(self):
        auth = JWTAuthenticator(key=SECRET)
        assert auth.authenticate({}) is None

    def test_non_bearer_scheme(self):
        auth = JWTAuthenticator(key=SECRET)
        assert auth.authenticate({"authorization": "Basic abc123"}) is None

    def test_empty_bearer_token(self):
        auth = JWTAuthenticator(key=SECRET)
        assert auth.authenticate({"authorization": "Bearer "}) is None

    def test_expired_token(self):
        auth = JWTAuthenticator(key=SECRET)
        token = _make_token({"sub": "user-1", "exp": int(time.time()) - 60})
        assert auth.authenticate({"authorization": f"Bearer {token}"}) is None

    def test_invalid_signature(self):
        auth = JWTAuthenticator(key=SECRET)
        token = _make_token({"sub": "user-1"}, key="wrong-key")
        assert auth.authenticate({"authorization": f"Bearer {token}"}) is None

    def test_malformed_token(self):
        auth = JWTAuthenticator(key=SECRET)
        assert auth.authenticate({"authorization": "Bearer not.a.valid.jwt"}) is None

    def test_missing_required_claim(self):
        auth = JWTAuthenticator(key=SECRET, require_claims=["sub", "email"])
        token = _make_token({"sub": "user-1"})
        assert auth.authenticate({"authorization": f"Bearer {token}"}) is None

    def test_audience_validation_pass(self):
        auth = JWTAuthenticator(key=SECRET, audience="my-app")
        token = _make_token({"sub": "user-1", "aud": "my-app"})
        identity = auth.authenticate({"authorization": f"Bearer {token}"})
        assert identity is not None
        assert identity.id == "user-1"

    def test_audience_validation_fail(self):
        auth = JWTAuthenticator(key=SECRET, audience="my-app")
        token = _make_token({"sub": "user-1", "aud": "other-app"})
        assert auth.authenticate({"authorization": f"Bearer {token}"}) is None

    def test_issuer_validation_pass(self):
        auth = JWTAuthenticator(key=SECRET, issuer="auth-server")
        token = _make_token({"sub": "user-1", "iss": "auth-server"})
        identity = auth.authenticate({"authorization": f"Bearer {token}"})
        assert identity is not None

    def test_issuer_validation_fail(self):
        auth = JWTAuthenticator(key=SECRET, issuer="auth-server")
        token = _make_token({"sub": "user-1", "iss": "bad-issuer"})
        assert auth.authenticate({"authorization": f"Bearer {token}"}) is None

    def test_bearer_case_insensitive(self):
        auth = JWTAuthenticator(key=SECRET)
        token = _make_token({"sub": "user-1"})
        identity = auth.authenticate({"authorization": f"BEARER {token}"})
        assert identity is not None
        assert identity.id == "user-1"


class TestCustomClaimMapping:
    def test_custom_id_claim(self):
        mapping = ClaimMapping(id_claim="user_id")
        auth = JWTAuthenticator(key=SECRET, claim_mapping=mapping, require_claims=[])
        token = _make_token({"user_id": "custom-1"})
        identity = auth.authenticate({"authorization": f"Bearer {token}"})
        assert identity is not None
        assert identity.id == "custom-1"

    def test_custom_roles_claim(self):
        mapping = ClaimMapping(roles_claim="permissions")
        auth = JWTAuthenticator(key=SECRET, claim_mapping=mapping)
        token = _make_token({"sub": "u1", "permissions": ["read", "write"]})
        identity = auth.authenticate({"authorization": f"Bearer {token}"})
        assert identity is not None
        assert identity.roles == ("read", "write")

    def test_attrs_claims(self):
        mapping = ClaimMapping(attrs_claims=["email", "org"])
        auth = JWTAuthenticator(key=SECRET, claim_mapping=mapping)
        token = _make_token({"sub": "u1", "email": "a@b.com", "org": "acme"})
        identity = auth.authenticate({"authorization": f"Bearer {token}"})
        assert identity is not None
        assert identity.attrs == {"email": "a@b.com", "org": "acme"}

    def test_attrs_claims_missing_key_skipped(self):
        mapping = ClaimMapping(attrs_claims=["email", "missing_claim"])
        auth = JWTAuthenticator(key=SECRET, claim_mapping=mapping)
        token = _make_token({"sub": "u1", "email": "a@b.com"})
        identity = auth.authenticate({"authorization": f"Bearer {token}"})
        assert identity is not None
        assert identity.attrs == {"email": "a@b.com"}

    def test_non_list_roles_ignored(self):
        auth = JWTAuthenticator(key=SECRET)
        token = _make_token({"sub": "u1", "roles": "admin"})
        identity = auth.authenticate({"authorization": f"Bearer {token}"})
        assert identity is not None
        assert identity.roles == ()


class TestClaimMappingFrozen:
    def test_frozen(self):
        mapping = ClaimMapping()
        with pytest.raises(AttributeError):
            mapping.id_claim = "other"  # type: ignore[misc]
