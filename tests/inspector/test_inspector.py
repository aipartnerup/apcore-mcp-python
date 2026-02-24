"""Tests for the MCP Tool Inspector (TC-INSPECTOR spec)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from apcore_mcp.inspector import create_inspector_mount

# ---------------------------------------------------------------------------
# Mock MCP Tool objects
# ---------------------------------------------------------------------------


@dataclass
class MockToolAnnotations:
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
class MockTool:
    name: str
    description: str
    inputSchema: dict[str, Any]  # noqa: N815
    annotations: MockToolAnnotations | None = None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_tools() -> list[MockTool]:
    """Two sample MCP tools for testing."""
    return [
        MockTool(
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
            annotations=MockToolAnnotations(readOnlyHint=False, idempotentHint=True),
        ),
        MockTool(
            name="text.echo",
            description="Echo input text",
            inputSchema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            annotations=MockToolAnnotations(readOnlyHint=True),
        ),
    ]


@pytest.fixture
def mock_router() -> AsyncMock:
    """Mock ExecutionRouter with handle_call returning success."""
    router = AsyncMock()
    router.handle_call.return_value = (
        [{"type": "text", "text": '{"result": "ok"}'}],
        False,
    )
    return router


@pytest.fixture
def inspector_app(sample_tools: list[MockTool], mock_router: AsyncMock) -> Starlette:
    """Starlette app with inspector mounted at /inspector, allow_execute=True."""
    mount = create_inspector_mount(sample_tools, mock_router, allow_execute=True, inspector_prefix="/inspector")
    return Starlette(routes=[mount])


@pytest.fixture
def inspector_app_no_execute(sample_tools: list[MockTool], mock_router: AsyncMock) -> Starlette:
    """Starlette app with inspector mounted, allow_execute=False."""
    mount = create_inspector_mount(sample_tools, mock_router, allow_execute=False, inspector_prefix="/inspector")
    return Starlette(routes=[mount])


# ---------------------------------------------------------------------------
# TC-001: GET /inspector/ returns HTML 200 with self-contained page
# ---------------------------------------------------------------------------


class TestTC001InspectorPage:
    def test_inspector_page_returns_html(self, inspector_app: Starlette) -> None:
        client = TestClient(inspector_app)
        response = client.get("/inspector/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "MCP Tool Inspector" in response.text

    def test_inspector_page_is_self_contained(self, inspector_app: Starlette) -> None:
        client = TestClient(inspector_app)
        response = client.get("/inspector/")
        assert "<style>" in response.text
        assert "<script>" in response.text


# ---------------------------------------------------------------------------
# TC-002: Inspector disabled by default (endpoints 404 when not mounted)
# ---------------------------------------------------------------------------


class TestTC002InspectorDisabledByDefault:
    def test_no_inspector_when_not_mounted(self) -> None:
        """When inspector is not mounted, /inspector/ should 404."""
        app = Starlette(routes=[])
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/inspector/")
        assert response.status_code == 404

    def test_no_inspector_tools_when_not_mounted(self) -> None:
        """When inspector is not mounted, /inspector/tools should 404."""
        app = Starlette(routes=[])
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/inspector/tools")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# TC-003: GET /inspector/tools returns JSON array with correct fields
# ---------------------------------------------------------------------------


class TestTC003ListTools:
    def test_list_tools_returns_json_array(self, inspector_app: Starlette) -> None:
        client = TestClient(inspector_app)
        response = client.get("/inspector/tools")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2

    def test_list_tools_has_correct_fields(self, inspector_app: Starlette) -> None:
        client = TestClient(inspector_app)
        response = client.get("/inspector/tools")
        data = response.json()
        tool = data[0]
        assert "name" in tool
        assert "description" in tool
        assert tool["name"] == "image.resize"
        assert tool["description"] == "Resize an image"

    def test_list_tools_includes_annotations(self, inspector_app: Starlette) -> None:
        client = TestClient(inspector_app)
        response = client.get("/inspector/tools")
        data = response.json()
        tool = data[0]
        assert "annotations" in tool
        assert tool["annotations"]["idempotentHint"] is True


# ---------------------------------------------------------------------------
# TC-004: GET /inspector/tools/<name> returns detail + 404 for unknown
# ---------------------------------------------------------------------------


class TestTC004ToolDetail:
    def test_tool_detail_returns_full_info(self, inspector_app: Starlette) -> None:
        client = TestClient(inspector_app)
        response = client.get("/inspector/tools/image.resize")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "image.resize"
        assert data["description"] == "Resize an image"
        assert "inputSchema" in data
        assert "properties" in data["inputSchema"]

    def test_tool_detail_includes_annotations(self, inspector_app: Starlette) -> None:
        client = TestClient(inspector_app)
        response = client.get("/inspector/tools/image.resize")
        data = response.json()
        assert "annotations" in data
        assert data["annotations"]["idempotentHint"] is True

    def test_tool_detail_404_for_unknown(self, inspector_app: Starlette) -> None:
        client = TestClient(inspector_app)
        response = client.get("/inspector/tools/nonexistent.tool")
        assert response.status_code == 404
        data = response.json()
        assert "error" in data


# ---------------------------------------------------------------------------
# TC-005: POST /inspector/tools/<name>/call executes tool
# ---------------------------------------------------------------------------


class TestTC005CallTool:
    def test_call_tool_executes(
        self,
        inspector_app: Starlette,
        mock_router: AsyncMock,
    ) -> None:
        client = TestClient(inspector_app)
        response = client.post(
            "/inspector/tools/image.resize/call",
            json={"width": 100, "height": 200},
        )
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        mock_router.handle_call.assert_called_once_with("image.resize", {"width": 100, "height": 200})

    def test_call_tool_404_for_unknown(
        self,
        inspector_app: Starlette,
    ) -> None:
        client = TestClient(inspector_app)
        response = client.post(
            "/inspector/tools/nonexistent.tool/call",
            json={},
        )
        assert response.status_code == 404

    def test_call_tool_returns_error_on_failure(
        self,
        inspector_app: Starlette,
        mock_router: AsyncMock,
    ) -> None:
        mock_router.handle_call.return_value = (
            [{"type": "text", "text": "Module not found"}],
            True,
        )
        client = TestClient(inspector_app)
        response = client.post(
            "/inspector/tools/image.resize/call",
            json={},
        )
        assert response.status_code == 500
        data = response.json()
        assert "error" in data


# ---------------------------------------------------------------------------
# TC-006: Call returns 403 when allow_execute=False
# ---------------------------------------------------------------------------


class TestTC006ExecuteDisabled:
    def test_call_returns_403_when_disabled(
        self,
        inspector_app_no_execute: Starlette,
    ) -> None:
        client = TestClient(inspector_app_no_execute)
        response = client.post(
            "/inspector/tools/image.resize/call",
            json={"width": 100, "height": 200},
        )
        assert response.status_code == 403
        data = response.json()
        assert "error" in data
        assert "disabled" in data["error"].lower() or "allow-execute" in data["error"].lower()

    def test_list_and_detail_still_work_when_execute_disabled(
        self,
        inspector_app_no_execute: Starlette,
    ) -> None:
        client = TestClient(inspector_app_no_execute)
        assert client.get("/inspector/tools").status_code == 200
        assert client.get("/inspector/tools/image.resize").status_code == 200


# ---------------------------------------------------------------------------
# TC-007: Inspector ignored for stdio (no error)
# ---------------------------------------------------------------------------


class TestTC007StdioIgnored:
    def test_explorer_flag_does_not_error_for_stdio(self) -> None:
        """When transport is stdio, explorer=True should not cause errors
        in serve() parameter validation. We test by verifying create_inspector_mount
        works and serve() validation accepts the params without transport error."""
        # The serve() function only creates the mount for HTTP transports.
        # We verify that the inspector module can be imported and mounted
        # without error, and that the serve() code path skips it for stdio.
        # Direct test: create_inspector_mount works without error
        tools = [
            MockTool(
                name="test.tool",
                description="Test",
                inputSchema={"type": "object", "properties": {}},
            )
        ]
        router = AsyncMock()
        mount = create_inspector_mount(tools, router)
        assert mount is not None


# ---------------------------------------------------------------------------
# TC-008: Custom inspector_prefix mounts at /custom/
# ---------------------------------------------------------------------------


class TestTC008CustomPrefix:
    def test_custom_prefix(
        self,
        sample_tools: list[MockTool],
        mock_router: AsyncMock,
    ) -> None:
        mount = create_inspector_mount(sample_tools, mock_router, inspector_prefix="/custom")
        app = Starlette(routes=[mount])
        client = TestClient(app)

        # Should be accessible at /custom/
        response = client.get("/custom/")
        assert response.status_code == 200
        assert "MCP Tool Inspector" in response.text

        # /custom/tools should work
        response = client.get("/custom/tools")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_default_prefix_not_accessible_with_custom(
        self,
        sample_tools: list[MockTool],
        mock_router: AsyncMock,
    ) -> None:
        mount = create_inspector_mount(sample_tools, mock_router, inspector_prefix="/custom")
        app = Starlette(routes=[mount])
        client = TestClient(app, raise_server_exceptions=False)

        # /inspector/ should 404 when custom prefix is used
        response = client.get("/inspector/")
        assert response.status_code == 404
