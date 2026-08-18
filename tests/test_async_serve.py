"""Tests for async_serve() — non-blocking ASGI app builder."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.applications import Starlette

from apcore_mcp import async_serve
from tests.conftest import ModuleAnnotations, ModuleDescriptor

# ---------------------------------------------------------------------------
# Stub Registry / Executor (same as test_serve_params.py)
# ---------------------------------------------------------------------------


class StubRegistry:
    def __init__(self, descriptors: list[ModuleDescriptor] | None = None):
        self._descriptors = {d.module_id: d for d in (descriptors or [])}

    def list(self, tags=None, prefix=None):
        ids = list(self._descriptors.keys())
        if prefix is not None:
            ids = [mid for mid in ids if mid.startswith(prefix)]
        if tags is not None:
            tag_set = set(tags)
            ids = [mid for mid in ids if tag_set.issubset(set(self._descriptors[mid].tags))]
        return sorted(ids)

    def get_definition(self, module_id):
        return self._descriptors.get(module_id)


class StubExecutor:
    def __init__(self, registry: StubRegistry):
        self.registry = registry

    async def call_async(self, _module_id: str, _inputs: dict | None = None) -> dict:
        return {"ok": True}


def _make_registry() -> StubRegistry:
    return StubRegistry(
        [
            ModuleDescriptor(
                module_id="test.hello",
                description="Say hello",
                input_schema={"type": "object", "properties": {"name": {"type": "string"}}},
                output_schema={"type": "object"},
                tags=["demo"],
                annotations=ModuleAnnotations(),
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Validation tests (same rules as serve())
# ---------------------------------------------------------------------------


class TestAsyncServeValidation:
    async def test_empty_name_raises(self) -> None:
        with pytest.raises(ValueError, match="name must not be empty"):
            async with async_serve(_make_registry(), name="") as _app:
                pass  # pragma: no cover

    async def test_long_name_raises(self) -> None:
        with pytest.raises(ValueError, match="exceeds maximum length"):
            async with async_serve(_make_registry(), name="x" * 256) as _app:
                pass  # pragma: no cover

    async def test_empty_tag_raises(self) -> None:
        with pytest.raises(ValueError, match="Tag values must not be empty"):
            async with async_serve(_make_registry(), tags=[""]) as _app:
                pass  # pragma: no cover

    async def test_empty_prefix_raises(self) -> None:
        with pytest.raises(ValueError, match="prefix must not be empty"):
            async with async_serve(_make_registry(), prefix="") as _app:
                pass  # pragma: no cover

    async def test_invalid_log_level_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown log level"):
            async with async_serve(_make_registry(), log_level="TRACE") as _app:
                pass  # pragma: no cover

    async def test_bad_explorer_prefix_raises(self) -> None:
        with pytest.raises(ValueError, match="explorer_prefix must start with"):
            async with async_serve(_make_registry(), explorer=True, explorer_prefix="no-slash") as _app:
                pass  # pragma: no cover


# ---------------------------------------------------------------------------
# Integration: yields a Starlette app
# ---------------------------------------------------------------------------


class TestAsyncServeApp:
    @patch("apcore_mcp.server.transport.StreamableHTTPServerTransport")
    async def test_yields_starlette_app(self, mock_transport_cls: MagicMock) -> None:
        """async_serve yields a Starlette ASGI application."""
        # Mock the transport so we don't actually start MCP protocol
        mock_transport = MagicMock()
        mock_transport_cls.return_value = mock_transport

        mock_read = MagicMock()
        mock_write = MagicMock()

        # connect() returns an async context manager yielding (read, write)
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=(mock_read, mock_write))
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_transport.connect.return_value = mock_cm

        mock_transport.handle_request = AsyncMock()

        registry = _make_registry()

        async with async_serve(registry, name="test-mcp") as app:
            assert isinstance(app, Starlette)

    async def test_is_async_context_manager(self) -> None:
        """async_serve is an async context manager."""

        registry = _make_registry()
        result = async_serve(registry)
        assert hasattr(result, "__aenter__")
        assert hasattr(result, "__aexit__")


# ---------------------------------------------------------------------------
# TransportManager.build_streamable_http_app tests
# ---------------------------------------------------------------------------


class TestBuildStreamableHttpApp:
    @patch("apcore_mcp.server.transport.StreamableHTTPServerTransport")
    async def test_yields_starlette_app(self, mock_transport_cls: MagicMock) -> None:
        from apcore_mcp.server.transport import TransportManager

        mock_transport = MagicMock()
        mock_transport_cls.return_value = mock_transport

        mock_read = MagicMock()
        mock_write = MagicMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=(mock_read, mock_write))
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_transport.connect.return_value = mock_cm
        mock_transport.handle_request = AsyncMock()

        server = MagicMock(spec=["run"])
        server.run = AsyncMock()
        init_options = MagicMock()

        tm = TransportManager()

        async with tm.build_streamable_http_app(server, init_options) as app:
            assert isinstance(app, Starlette)

    def test_build_streamable_http_app_is_async(self) -> None:
        """build_streamable_http_app returns an async context manager."""
        from apcore_mcp.server.transport import TransportManager

        tm = TransportManager()
        server = MagicMock(spec=["run"])
        init_options = MagicMock()

        result = tm.build_streamable_http_app(server, init_options)
        assert hasattr(result, "__aenter__")
        assert hasattr(result, "__aexit__")
