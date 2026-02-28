"""Tests for AuthMiddleware."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock

import jwt as pyjwt
import pytest
from apcore import Identity

from apcore_mcp.auth.jwt import JWTAuthenticator
from apcore_mcp.auth.middleware import AuthMiddleware, auth_identity_var, extract_headers

SECRET = "test-secret-key"


def _make_token(payload: dict, key: str = SECRET) -> str:
    return pyjwt.encode(payload, key, algorithm="HS256")


def _build_scope(
    path: str = "/mcp",
    headers: list[tuple[bytes, bytes]] | None = None,
    scope_type: str = "http",
) -> dict[str, Any]:
    return {
        "type": scope_type,
        "path": path,
        "headers": headers or [],
    }


def _build_auth_header(token: str) -> list[tuple[bytes, bytes]]:
    return [(b"authorization", f"Bearer {token}".encode("latin-1"))]


class TestAuthMiddleware401:
    @pytest.mark.asyncio
    async def test_returns_401_without_token(self):
        app = AsyncMock()
        auth = JWTAuthenticator(key=SECRET)
        mw = AuthMiddleware(app, auth)
        sent: list[dict] = []

        async def capture_send(message: dict) -> None:
            sent.append(message)

        await mw(_build_scope(), AsyncMock(), capture_send)
        assert sent[0]["status"] == 401
        assert any(header == [b"www-authenticate", b"Bearer"] for header in sent[0]["headers"])
        app.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_401_with_invalid_token(self):
        app = AsyncMock()
        auth = JWTAuthenticator(key=SECRET)
        mw = AuthMiddleware(app, auth)
        sent: list[dict] = []

        async def capture_send(message: dict) -> None:
            sent.append(message)

        scope = _build_scope(headers=_build_auth_header("bad.token.here"))
        await mw(scope, AsyncMock(), capture_send)
        assert sent[0]["status"] == 401
        app.assert_not_called()


class TestExemptPaths:
    @pytest.mark.asyncio
    async def test_health_exempt(self):
        app = AsyncMock()
        auth = JWTAuthenticator(key=SECRET)
        mw = AuthMiddleware(app, auth)

        scope = _build_scope(path="/health")
        await mw(scope, AsyncMock(), AsyncMock())
        app.assert_called_once()

    @pytest.mark.asyncio
    async def test_metrics_exempt(self):
        app = AsyncMock()
        auth = JWTAuthenticator(key=SECRET)
        mw = AuthMiddleware(app, auth)

        scope = _build_scope(path="/metrics")
        await mw(scope, AsyncMock(), AsyncMock())
        app.assert_called_once()

    @pytest.mark.asyncio
    async def test_custom_exempt_paths(self):
        app = AsyncMock()
        auth = JWTAuthenticator(key=SECRET)
        mw = AuthMiddleware(app, auth, exempt_paths={"/custom"})

        scope = _build_scope(path="/custom")
        await mw(scope, AsyncMock(), AsyncMock())
        app.assert_called_once()


class TestPermissiveMode:
    @pytest.mark.asyncio
    async def test_no_token_passes_without_identity(self):
        captured_identity: list[Identity | None] = []

        async def app(scope: Any, receive: Any, send: Any) -> None:
            captured_identity.append(auth_identity_var.get())

        auth = JWTAuthenticator(key=SECRET)
        mw = AuthMiddleware(app, auth, require_auth=False)

        await mw(_build_scope(), AsyncMock(), AsyncMock())
        assert captured_identity == [None]

    @pytest.mark.asyncio
    async def test_valid_token_sets_identity(self):
        captured_identity: list[Identity | None] = []

        async def app(scope: Any, receive: Any, send: Any) -> None:
            captured_identity.append(auth_identity_var.get())

        auth = JWTAuthenticator(key=SECRET)
        mw = AuthMiddleware(app, auth, require_auth=False)

        token = _make_token({"sub": "user-1"})
        scope = _build_scope(headers=_build_auth_header(token))
        await mw(scope, AsyncMock(), AsyncMock())
        assert captured_identity[0] is not None
        assert captured_identity[0].id == "user-1"


class TestContextVarLifecycle:
    @pytest.mark.asyncio
    async def test_identity_set_during_request(self):
        captured_identity: list[Identity | None] = []

        async def app(scope: Any, receive: Any, send: Any) -> None:
            captured_identity.append(auth_identity_var.get())

        auth = JWTAuthenticator(key=SECRET)
        mw = AuthMiddleware(app, auth)

        token = _make_token({"sub": "test-user", "roles": ["admin"]})
        scope = _build_scope(headers=_build_auth_header(token))
        await mw(scope, AsyncMock(), AsyncMock())

        assert captured_identity[0] is not None
        assert captured_identity[0].id == "test-user"
        assert captured_identity[0].roles == ("admin",)

    @pytest.mark.asyncio
    async def test_identity_reset_after_request(self):
        async def app(scope: Any, receive: Any, send: Any) -> None:
            pass

        auth = JWTAuthenticator(key=SECRET)
        mw = AuthMiddleware(app, auth)

        token = _make_token({"sub": "user-1"})
        scope = _build_scope(headers=_build_auth_header(token))
        await mw(scope, AsyncMock(), AsyncMock())

        assert auth_identity_var.get() is None

    @pytest.mark.asyncio
    async def test_identity_reset_on_exception(self):
        async def app(scope: Any, receive: Any, send: Any) -> None:
            raise RuntimeError("boom")

        auth = JWTAuthenticator(key=SECRET)
        mw = AuthMiddleware(app, auth)

        token = _make_token({"sub": "user-1"})
        scope = _build_scope(headers=_build_auth_header(token))
        with pytest.raises(RuntimeError, match="boom"):
            await mw(scope, AsyncMock(), AsyncMock())

        assert auth_identity_var.get() is None


class TestExemptPrefixes:
    @pytest.mark.asyncio
    async def test_prefix_exempts_matching_paths(self):
        app = AsyncMock()
        auth = JWTAuthenticator(key=SECRET)
        mw = AuthMiddleware(app, auth, exempt_prefixes={"/explorer"})

        for path in ["/explorer", "/explorer/", "/explorer/tools", "/explorer/tools/foo/call"]:
            app.reset_mock()
            scope = _build_scope(path=path)
            await mw(scope, AsyncMock(), AsyncMock())
            assert app.call_count == 1, f"Expected pass-through for {path}"

    @pytest.mark.asyncio
    async def test_prefix_does_not_exempt_non_matching(self):
        app = AsyncMock()
        auth = JWTAuthenticator(key=SECRET)
        mw = AuthMiddleware(app, auth, exempt_prefixes={"/explorer"})
        sent: list[dict] = []

        async def capture_send(message: dict) -> None:
            sent.append(message)

        scope = _build_scope(path="/mcp")
        await mw(scope, AsyncMock(), capture_send)
        assert sent[0]["status"] == 401
        app.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_prefixes(self):
        app = AsyncMock()
        auth = JWTAuthenticator(key=SECRET)
        mw = AuthMiddleware(app, auth, exempt_prefixes={"/explorer", "/docs"})

        for path in ["/explorer/tools", "/docs/api"]:
            app.reset_mock()
            scope = _build_scope(path=path)
            await mw(scope, AsyncMock(), AsyncMock())
            app.assert_called_once()


class TestNonHTTPPassthrough:
    @pytest.mark.asyncio
    async def test_websocket_scope_passes_through(self):
        app = AsyncMock()
        auth = JWTAuthenticator(key=SECRET)
        mw = AuthMiddleware(app, auth)

        scope = _build_scope(scope_type="websocket")
        await mw(scope, AsyncMock(), AsyncMock())
        app.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_scope_passes_through(self):
        app = AsyncMock()
        auth = JWTAuthenticator(key=SECRET)
        mw = AuthMiddleware(app, auth)

        scope = _build_scope(scope_type="lifespan")
        await mw(scope, AsyncMock(), AsyncMock())
        app.assert_called_once()


class TestAuditLogging:
    @pytest.mark.asyncio
    async def test_auth_failure_logs_warning(self, caplog: pytest.LogCaptureFixture):
        """Authentication failure emits a WARNING log with the request path."""
        app = AsyncMock()
        auth = JWTAuthenticator(key=SECRET)
        mw = AuthMiddleware(app, auth)
        sent: list[dict] = []

        async def capture_send(message: dict) -> None:
            sent.append(message)

        with caplog.at_level(logging.WARNING, logger="apcore_mcp.auth.middleware"):
            await mw(_build_scope(path="/api/data"), AsyncMock(), capture_send)

        assert sent[0]["status"] == 401
        assert any("Authentication failed for /api/data" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_auth_failure_with_invalid_token_logs_warning(self, caplog: pytest.LogCaptureFixture):
        """Invalid token triggers WARNING log."""
        app = AsyncMock()
        auth = JWTAuthenticator(key=SECRET)
        mw = AuthMiddleware(app, auth)
        sent: list[dict] = []

        async def capture_send(message: dict) -> None:
            sent.append(message)

        scope = _build_scope(path="/mcp", headers=_build_auth_header("bad.token"))
        with caplog.at_level(logging.WARNING, logger="apcore_mcp.auth.middleware"):
            await mw(scope, AsyncMock(), capture_send)

        assert sent[0]["status"] == 401
        assert any("Authentication failed for /mcp" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_successful_auth_does_not_log_warning(self, caplog: pytest.LogCaptureFixture):
        """Successful authentication should not produce a WARNING log."""
        app = AsyncMock()
        auth = JWTAuthenticator(key=SECRET)
        mw = AuthMiddleware(app, auth)

        token = _make_token({"sub": "user-1"})
        scope = _build_scope(headers=_build_auth_header(token))
        with caplog.at_level(logging.WARNING, logger="apcore_mcp.auth.middleware"):
            await mw(scope, AsyncMock(), AsyncMock())

        assert not any("Authentication failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_permissive_mode_does_not_log_warning(self, caplog: pytest.LogCaptureFixture):
        """Permissive mode (require_auth=False) should not log on missing token."""
        app = AsyncMock()
        auth = JWTAuthenticator(key=SECRET)
        mw = AuthMiddleware(app, auth, require_auth=False)

        with caplog.at_level(logging.WARNING, logger="apcore_mcp.auth.middleware"):
            await mw(_build_scope(), AsyncMock(), AsyncMock())

        assert not any("Authentication failed" in r.message for r in caplog.records)


class TestExtractHeaders:
    def test_extracts_headers_from_scope(self):
        scope = {
            "headers": [
                (b"content-type", b"application/json"),
                (b"authorization", b"Bearer abc"),
            ]
        }
        result = extract_headers(scope)
        assert result == {"content-type": "application/json", "authorization": "Bearer abc"}

    def test_lowercases_header_keys(self):
        scope = {"headers": [(b"X-Custom-Header", b"value")]}
        result = extract_headers(scope)
        assert "x-custom-header" in result

    def test_empty_headers(self):
        assert extract_headers({"headers": []}) == {}

    def test_missing_headers_key(self):
        assert extract_headers({}) == {}
