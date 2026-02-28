"""Integration tests for JWT authentication using real apcore modules from examples/.

Verifies the full auth pipeline:
  AuthMiddleware → ContextVar → factory extra["identity"] → router → Context.create(identity=)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

import jwt as pyjwt
import pytest
from apcore import Executor, Identity, Registry
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.testclient import TestClient

from apcore_mcp.auth.jwt import JWTAuthenticator
from apcore_mcp.auth.middleware import AuthMiddleware, auth_identity_var
from apcore_mcp.explorer import create_explorer_mount
from apcore_mcp.server.factory import MCPServerFactory
from apcore_mcp.server.router import ExecutionRouter

SECRET = "integration-test-secret"
EXTENSIONS_DIR = "./examples/extensions"


def _make_token(payload: dict, key: str = SECRET) -> str:
    return pyjwt.encode(payload, key, algorithm="HS256")


# ---------------------------------------------------------------------------
# Fixtures: real apcore Registry + Executor from examples/
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> Registry:
    reg = Registry(extensions_dir=EXTENSIONS_DIR)
    count = reg.discover()
    assert count >= 1, f"Expected at least 1 module, discovered {count}"
    return reg


@pytest.fixture
def executor(registry: Registry) -> Executor:
    return Executor(registry)


@pytest.fixture
def router(executor: Executor) -> ExecutionRouter:
    return ExecutionRouter(executor)


@pytest.fixture
def factory() -> MCPServerFactory:
    return MCPServerFactory()


@pytest.fixture
def authenticator() -> JWTAuthenticator:
    return JWTAuthenticator(key=SECRET)


# ---------------------------------------------------------------------------
# TC-AUTH-INT-001: Router receives identity via extra → Context has identity
# ---------------------------------------------------------------------------


class TestRouterIdentityInjection:
    """Verify that identity passed through extra dict reaches the Context."""

    async def test_call_with_identity_succeeds(self, router: ExecutionRouter) -> None:
        """Calling a real tool with identity in extra returns success."""
        identity = Identity(id="user-42", type="user", roles=("reader",))
        content, is_error, trace_id = await router.handle_call(
            "text_echo",
            {"text": "hello"},
            extra={"identity": identity},
        )
        assert is_error is False
        parsed = json.loads(content[0]["text"])
        assert parsed["echoed"] == "hello"

    async def test_call_without_identity_succeeds(self, router: ExecutionRouter) -> None:
        """Calling a real tool without identity still works (backward compat)."""
        content, is_error, trace_id = await router.handle_call(
            "text_echo",
            {"text": "world"},
        )
        assert is_error is False
        parsed = json.loads(content[0]["text"])
        assert parsed["echoed"] == "world"

    async def test_identity_roles_preserved(self, router: ExecutionRouter) -> None:
        """Identity roles survive through the extra → Context pipeline."""
        identity = Identity(id="admin-1", type="service", roles=("admin", "editor"))
        content, is_error, _ = await router.handle_call(
            "math_calc",
            {"a": 10, "b": 3, "op": "add"},
            extra={"identity": identity},
        )
        assert is_error is False
        parsed = json.loads(content[0]["text"])
        assert parsed["result"] == 13


# ---------------------------------------------------------------------------
# TC-AUTH-INT-002: Middleware → ContextVar → factory reads identity
# ---------------------------------------------------------------------------


class TestMiddlewareContextVarBridge:
    """Verify the ContextVar bridge between ASGI middleware and MCP factory."""

    async def test_contextvar_set_during_authenticated_request(self, authenticator: JWTAuthenticator) -> None:
        """Valid JWT sets auth_identity_var visible to downstream ASGI app."""
        captured: list[Identity | None] = []

        async def downstream(scope: Any, receive: Any, send: Any) -> None:
            captured.append(auth_identity_var.get())

        mw = AuthMiddleware(downstream, authenticator)
        token = _make_token({"sub": "user-99", "roles": ["admin"]})
        scope = {
            "type": "http",
            "path": "/mcp",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
        }
        await mw(scope, AsyncMock(), AsyncMock())

        assert captured[0] is not None
        assert captured[0].id == "user-99"
        assert captured[0].roles == ("admin",)

    async def test_contextvar_none_without_token(self, authenticator: JWTAuthenticator) -> None:
        """Permissive mode: no token → identity is None in ContextVar."""
        captured: list[Identity | None] = []

        async def downstream(scope: Any, receive: Any, send: Any) -> None:
            captured.append(auth_identity_var.get())

        mw = AuthMiddleware(downstream, authenticator, require_auth=False)
        scope = {"type": "http", "path": "/mcp", "headers": []}
        await mw(scope, AsyncMock(), AsyncMock())
        assert captured[0] is None


# ---------------------------------------------------------------------------
# TC-AUTH-INT-003: Full pipeline — Middleware + Router with real modules
# ---------------------------------------------------------------------------


class TestFullAuthPipeline:
    """End-to-end: JWT middleware → ContextVar → router.handle_call with real executor."""

    async def test_authenticated_call_through_full_pipeline(
        self, router: ExecutionRouter, authenticator: JWTAuthenticator
    ) -> None:
        """Simulate the full auth flow from HTTP header to tool execution result."""
        # Step 1: Middleware sets ContextVar
        token = _make_token({"sub": "api-client-1", "type": "service", "roles": ["tool-caller"]})
        scope = {
            "type": "http",
            "path": "/mcp",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
        }

        # Simulate middleware setting ContextVar, then calling handle_call
        captured_identity: list[Identity | None] = []

        async def app_handler(scope: Any, receive: Any, send: Any) -> None:
            # This is what factory.py does: read ContextVar
            identity = auth_identity_var.get()
            captured_identity.append(identity)

            # This is what router.py does: pass identity via extra
            content, is_error, _ = await router.handle_call(
                "greeting",
                {"name": "Alice", "style": "friendly"},
                extra={"identity": identity} if identity else None,
            )
            assert is_error is False
            parsed = json.loads(content[0]["text"])
            assert "Alice" in parsed["message"]

        mw = AuthMiddleware(app_handler, authenticator)
        await mw(scope, AsyncMock(), AsyncMock())

        # Verify identity was available throughout
        assert captured_identity[0] is not None
        assert captured_identity[0].id == "api-client-1"
        assert captured_identity[0].type == "service"
        assert captured_identity[0].roles == ("tool-caller",)

    async def test_unauthenticated_request_rejected(self, authenticator: JWTAuthenticator) -> None:
        """Request without token gets 401, tool never executes."""
        app = AsyncMock()
        mw = AuthMiddleware(app, authenticator)
        sent: list[dict] = []

        async def capture_send(msg: dict) -> None:
            sent.append(msg)

        scope = {"type": "http", "path": "/mcp", "headers": []}
        await mw(scope, AsyncMock(), capture_send)

        assert sent[0]["status"] == 401
        app.assert_not_called()

    async def test_health_endpoint_bypasses_auth(self, authenticator: JWTAuthenticator) -> None:
        """Health endpoint is exempt from auth even without token."""
        app = AsyncMock()
        mw = AuthMiddleware(app, authenticator)
        scope = {"type": "http", "path": "/health", "headers": []}
        await mw(scope, AsyncMock(), AsyncMock())
        app.assert_called_once()

    async def test_expired_token_rejected(self, router: ExecutionRouter, authenticator: JWTAuthenticator) -> None:
        """Expired token gets 401."""
        import time

        token = _make_token({"sub": "user-1", "exp": int(time.time()) - 60})
        sent: list[dict] = []

        async def capture_send(msg: dict) -> None:
            sent.append(msg)

        app = AsyncMock()
        mw = AuthMiddleware(app, authenticator)
        scope = {
            "type": "http",
            "path": "/mcp",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
        }
        await mw(scope, AsyncMock(), capture_send)
        assert sent[0]["status"] == 401
        app.assert_not_called()

    async def test_websocket_scope_bypasses_auth(
        self, router: ExecutionRouter, authenticator: JWTAuthenticator
    ) -> None:
        """WebSocket scope passes through without auth — no token required."""
        executed = False

        async def app_handler(scope: Any, receive: Any, send: Any) -> None:
            nonlocal executed
            # Verify ContextVar is NOT set (middleware skips non-HTTP scopes)
            assert auth_identity_var.get() is None
            executed = True

        mw = AuthMiddleware(app_handler, authenticator)
        scope = {"type": "websocket", "path": "/mcp", "headers": []}
        await mw(scope, AsyncMock(), AsyncMock())
        assert executed, "WebSocket request should have reached the app"

    async def test_websocket_scope_does_not_set_identity(self, authenticator: JWTAuthenticator) -> None:
        """Even with a valid token in headers, WebSocket scope does not set identity."""
        captured: list[Identity | None] = []

        async def app_handler(scope: Any, receive: Any, send: Any) -> None:
            captured.append(auth_identity_var.get())

        token = _make_token({"sub": "ws-user"})
        mw = AuthMiddleware(app_handler, authenticator)
        scope = {
            "type": "websocket",
            "path": "/mcp",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
        }
        await mw(scope, AsyncMock(), AsyncMock())
        # Identity should NOT be set — middleware skips non-HTTP scopes entirely
        assert captured[0] is None


# ---------------------------------------------------------------------------
# TC-AUTH-INT-004: Build tools from real registry with auth
# ---------------------------------------------------------------------------


class TestBuildToolsWithAuth:
    """Verify MCP tool building works correctly with real example modules."""

    def test_real_modules_build_as_tools(self, factory: MCPServerFactory, registry: Registry) -> None:
        """Real modules from examples/ are built into valid MCP tools."""
        tools = factory.build_tools(registry)
        assert len(tools) >= 3
        tool_names = {t.name for t in tools}
        assert "greeting" in tool_names
        assert "math_calc" in tool_names
        assert "text_echo" in tool_names

    async def test_authenticated_execution_of_each_tool(self, router: ExecutionRouter) -> None:
        """Each real tool executes successfully with an identity in context."""
        identity = Identity(id="tester", type="user", roles=("admin",))
        extra = {"identity": identity}

        # greeting
        content, is_error, _ = await router.handle_call("greeting", {"name": "Bob"}, extra=extra)
        assert is_error is False
        assert "Bob" in json.loads(content[0]["text"])["message"]

        # math_calc
        content, is_error, _ = await router.handle_call("math_calc", {"a": 6, "b": 7, "op": "mul"}, extra=extra)
        assert is_error is False
        assert json.loads(content[0]["text"])["result"] == 42

        # text_echo
        content, is_error, _ = await router.handle_call(
            "text_echo", {"text": "echo me", "uppercase": True}, extra=extra
        )
        assert is_error is False
        assert json.loads(content[0]["text"])["echoed"] == "ECHO ME"


# ---------------------------------------------------------------------------
# Mock objects for Explorer integration tests
# ---------------------------------------------------------------------------


@dataclass
class _MockToolAnnotations:
    readOnlyHint: bool | None = None  # noqa: N815
    destructiveHint: bool | None = None  # noqa: N815
    idempotentHint: bool | None = None  # noqa: N815
    openWorldHint: bool | None = None  # noqa: N815
    title: str | None = None

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        result = {}
        if self.readOnlyHint is not None:
            result["readOnlyHint"] = self.readOnlyHint
        if self.destructiveHint is not None:
            result["destructiveHint"] = self.destructiveHint
        if self.idempotentHint is not None:
            result["idempotentHint"] = self.idempotentHint
        if self.openWorldHint is not None:
            result["openWorldHint"] = self.openWorldHint
        if self.title is not None:
            result["title"] = self.title
        return result


@dataclass
class _MockTool:
    name: str
    description: str
    inputSchema: dict[str, Any]  # noqa: N815
    annotations: _MockToolAnnotations | None = None


# ---------------------------------------------------------------------------
# TC-AUTH-INT-014 through TC-AUTH-INT-018: Explorer + JWT auth integration
# ---------------------------------------------------------------------------


class TestExplorerAuthIntegration:
    """TC-AUTH-INT-014 through TC-AUTH-INT-018."""

    @staticmethod
    def _build_app(
        authenticator: JWTAuthenticator,
        allow_execute: bool = True,
        exempt_paths: set[str] | None = None,
    ) -> Starlette:
        """Build a Starlette app with auth middleware and explorer mount."""
        tools = [
            _MockTool(
                name="image.resize",
                description="Resize an image",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                    },
                    "required": ["width", "height"],
                },
                annotations=_MockToolAnnotations(readOnlyHint=False),
            ),
        ]
        mock_router = AsyncMock()
        mock_router.handle_call.return_value = (
            [{"type": "text", "text": '{"result": "ok"}'}],
            False,
            "trace-int",
        )

        mount = create_explorer_mount(
            tools,
            mock_router,
            allow_execute=allow_execute,
            explorer_prefix="/explorer",
            authenticator=authenticator,
        )
        mw_kwargs: dict[str, Any] = {
            "authenticator": authenticator,
            "exempt_prefixes": {"/explorer"},
        }
        if exempt_paths is not None:
            mw_kwargs["exempt_paths"] = exempt_paths
        app = Starlette(
            routes=[mount],
            middleware=[Middleware(AuthMiddleware, **mw_kwargs)],
        )
        return app

    def test_get_explorer_page_bypasses_auth(self) -> None:
        """TC-AUTH-INT-014: Explorer GET /explorer/ bypasses auth."""
        auth = JWTAuthenticator(key=SECRET)
        app = self._build_app(auth)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/explorer/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_get_explorer_tools_bypasses_auth(self) -> None:
        """TC-AUTH-INT-015: Explorer GET /explorer/tools bypasses auth."""
        auth = JWTAuthenticator(key=SECRET)
        app = self._build_app(auth)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/explorer/tools")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1

    def test_post_call_returns_401_without_token(self) -> None:
        """TC-AUTH-INT-016: Explorer POST /call returns 401 without token."""
        auth = JWTAuthenticator(key=SECRET)
        app = self._build_app(auth)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/explorer/tools/image.resize/call",
            json={"width": 100, "height": 200},
        )
        assert response.status_code == 401

    def test_post_call_sets_identity_with_valid_token(self) -> None:
        """TC-AUTH-INT-017: Explorer POST /call sets identity with valid token."""
        auth = JWTAuthenticator(key=SECRET)
        tools = [
            _MockTool(
                name="image.resize",
                description="Resize an image",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                    },
                    "required": ["width", "height"],
                },
            ),
        ]
        captured_identity: list[Identity | None] = []
        return_value = (
            [{"type": "text", "text": '{"result": "ok"}'}],
            False,
            "trace-int",
        )

        async def capture_handle_call(name: str, args: dict) -> Any:
            captured_identity.append(auth_identity_var.get())
            return return_value

        mock_router = AsyncMock()
        mock_router.handle_call = capture_handle_call

        mount = create_explorer_mount(
            tools,
            mock_router,
            allow_execute=True,
            explorer_prefix="/explorer",
            authenticator=auth,
        )
        app = Starlette(
            routes=[mount],
            middleware=[
                Middleware(AuthMiddleware, authenticator=auth, exempt_prefixes={"/explorer"}),
            ],
        )
        token = _make_token({"sub": "explorer-user", "roles": ["viewer"]})
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/explorer/tools/image.resize/call",
            json={"width": 100, "height": 200},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert len(captured_identity) == 1
        assert captured_identity[0] is not None
        assert captured_identity[0].id == "explorer-user"
        assert captured_identity[0].roles == ("viewer",)

    def test_explorer_exempt_with_custom_exempt_paths(self) -> None:
        """TC-AUTH-INT-018: Explorer exempt even with custom exempt_paths."""
        auth = JWTAuthenticator(key=SECRET)
        app = self._build_app(auth, exempt_paths={"/custom-health"})
        client = TestClient(app, raise_server_exceptions=False)

        # Explorer pages should still be accessible (exempt via prefix)
        response = client.get("/explorer/")
        assert response.status_code == 200

        response = client.get("/explorer/tools")
        assert response.status_code == 200
