"""Unit tests for MCPServer non-blocking wrapper."""

from __future__ import annotations

import asyncio
import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from apcore_mcp.server.server import MCPServer

# ---------------------------------------------------------------------------
# Stub Registry / Executor
# ---------------------------------------------------------------------------


class StubRegistry:
    """Minimal Registry stub."""

    def __init__(self) -> None:
        self._modules: dict[str, Any] = {}

    def list(self, tags: list[str] | None = None, prefix: str | None = None) -> list[str]:
        return list(self._modules.keys())

    def get_definition(self, module_id: str) -> Any:
        return self._modules.get(module_id)


class StubExecutor:
    """Minimal Executor stub with registry attribute."""

    def __init__(self) -> None:
        self.registry = StubRegistry()

    async def call_async(self, module_id: str, inputs: dict[str, Any]) -> Any:
        return {"ok": True}


# ---------------------------------------------------------------------------
# Tests for MCPServer.__init__ and properties
# ---------------------------------------------------------------------------


class TestMCPServerInit:
    """Tests for MCPServer constructor and properties."""

    def test_default_parameters(self) -> None:
        """MCPServer stores default parameters correctly."""
        registry = StubRegistry()
        server = MCPServer(registry)
        assert server._transport == "stdio"
        assert server._host == "127.0.0.1"
        assert server._port == 8000
        assert server._name == "apcore-mcp"
        assert server._version is None
        assert server._thread is None
        assert server._loop is None

    def test_custom_parameters(self) -> None:
        """MCPServer stores custom parameters correctly."""
        registry = StubRegistry()
        server = MCPServer(
            registry,
            transport="streamable-http",
            host="0.0.0.0",
            port=9000,
            name="custom-server",
            version="1.0.0",
        )
        assert server._transport == "streamable-http"
        assert server._host == "0.0.0.0"
        assert server._port == 9000
        assert server._name == "custom-server"
        assert server._version == "1.0.0"

    def test_started_and_stopped_events_initialized(self) -> None:
        """Internal threading events are properly initialized."""
        server = MCPServer(StubRegistry())
        assert isinstance(server._started, threading.Event)
        assert isinstance(server._stopped, threading.Event)
        assert not server._started.is_set()
        assert not server._stopped.is_set()


# ---------------------------------------------------------------------------
# Tests for MCPServer.address
# ---------------------------------------------------------------------------


class TestMCPServerAddress:
    """Tests for MCPServer.address property."""

    def test_stdio_address(self) -> None:
        """stdio transport returns 'stdio' as address."""
        server = MCPServer(StubRegistry(), transport="stdio")
        assert server.address == "stdio"

    def test_http_address(self) -> None:
        """HTTP transport returns formatted URL."""
        server = MCPServer(
            StubRegistry(),
            transport="streamable-http",
            host="0.0.0.0",
            port=9000,
        )
        assert server.address == "http://0.0.0.0:9000"

    def test_sse_address(self) -> None:
        """SSE transport returns formatted URL."""
        server = MCPServer(
            StubRegistry(),
            transport="sse",
            host="127.0.0.1",
            port=8080,
        )
        assert server.address == "http://127.0.0.1:8080"


# ---------------------------------------------------------------------------
# Tests for MCPServer.start / stop / wait
# ---------------------------------------------------------------------------


class TestMCPServerLifecycle:
    """Tests for MCPServer start/stop/wait lifecycle."""

    def test_start_creates_daemon_thread(self) -> None:
        """start() creates a daemon thread and waits for _started."""
        registry = StubRegistry()
        server = MCPServer(registry)

        # Mock _run to just set _started and block until _stopped
        def mock_run() -> None:
            server._started.set()
            server._stopped.wait()

        with patch.object(server, "_run", side_effect=mock_run):
            server.start()
            assert server._thread is not None
            assert server._thread.daemon is True
            assert server._started.is_set()
            server.stop()
            server._thread.join(timeout=2)

    def test_start_is_idempotent(self) -> None:
        """Calling start() twice does not create a second thread."""
        registry = StubRegistry()
        server = MCPServer(registry)

        def mock_run() -> None:
            server._started.set()
            server._stopped.wait()

        with patch.object(server, "_run", side_effect=mock_run):
            server.start()
            first_thread = server._thread
            server.start()  # Second call should be no-op
            assert server._thread is first_thread
            server.stop()
            server._thread.join(timeout=2)

    def test_wait_blocks_until_thread_finishes(self) -> None:
        """wait() blocks until the thread completes."""
        registry = StubRegistry()
        server = MCPServer(registry)

        def mock_run() -> None:
            server._started.set()
            # Immediately finish

        with patch.object(server, "_run", side_effect=mock_run):
            server.start()
            server.wait()  # Should return immediately since _run finishes
            assert not server._thread.is_alive()

    def test_wait_noop_without_start(self) -> None:
        """wait() does nothing if start() was never called."""
        server = MCPServer(StubRegistry())
        server.wait()  # Should not raise

    def test_stop_sets_stopped_event(self) -> None:
        """stop() sets the _stopped event."""
        server = MCPServer(StubRegistry())
        assert not server._stopped.is_set()
        server.stop()
        assert server._stopped.is_set()

    def test_stop_calls_loop_stop(self) -> None:
        """stop() calls loop.stop() when loop is available."""
        server = MCPServer(StubRegistry())
        mock_loop = MagicMock(spec=asyncio.AbstractEventLoop)
        server._loop = mock_loop
        server.stop()
        mock_loop.call_soon_threadsafe.assert_called_once_with(mock_loop.stop)

    def test_stop_without_loop(self) -> None:
        """stop() handles None loop gracefully."""
        server = MCPServer(StubRegistry())
        server._loop = None
        server.stop()  # Should not raise
        assert server._stopped.is_set()


# ---------------------------------------------------------------------------
# Tests for MCPServer._run
# ---------------------------------------------------------------------------


def _patch_serve_coro(server: MCPServer, *, side_effect: Any = None) -> Any:
    """Patch ``MCPServer._build_app`` so ``_run`` delegates to a stub APCoreMCP.

    The stub's ``_build_serve_coro`` returns a zero-arg coroutine factory that
    completes immediately (or raises *side_effect*), so ``_run`` exercises the
    real thread/loop lifecycle without spinning a live transport. Returns the
    mock APCoreMCP for assertions on how it was configured.
    """
    mock_mcp = MagicMock()

    async def _coro() -> None:
        if side_effect is not None:
            raise side_effect

    mock_mcp._build_serve_coro.return_value = _coro
    return patch.object(server, "_build_app", return_value=mock_mcp), mock_mcp


class TestMCPServerRun:
    """Tests for MCPServer._run internal method (delegates to APCoreMCP)."""

    def test_run_stdio(self) -> None:
        """_run runs the delegated coroutine to completion for stdio."""
        server = MCPServer(StubRegistry(), transport="stdio")
        ctx, mock_mcp = _patch_serve_coro(server)
        with ctx:
            server._run()
        assert server._loop is not None
        assert server._started.is_set()
        assert server._stopped.is_set()
        # The configured transport flows into the serve coroutine builder.
        assert mock_mcp._build_serve_coro.call_args.kwargs["transport"] == "stdio"

    def test_run_streamable_http(self) -> None:
        """_run forwards host/port for streamable-http."""
        server = MCPServer(
            StubRegistry(),
            transport="streamable-http",
            host="0.0.0.0",
            port=9000,
        )
        ctx, mock_mcp = _patch_serve_coro(server)
        with ctx:
            server._run()
        assert server._stopped.is_set()
        kwargs = mock_mcp._build_serve_coro.call_args.kwargs
        assert kwargs["transport"] == "streamable-http"
        assert kwargs["host"] == "0.0.0.0"
        assert kwargs["port"] == 9000

    def test_run_sse(self) -> None:
        """_run runs the delegated coroutine for sse."""
        server = MCPServer(StubRegistry(), transport="sse", host="127.0.0.1", port=8080)
        ctx, mock_mcp = _patch_serve_coro(server)
        with ctx:
            server._run()
        assert server._stopped.is_set()
        assert mock_mcp._build_serve_coro.call_args.kwargs["transport"] == "sse"

    def test_run_unknown_transport_raises(self) -> None:
        """Unknown transport raises ValueError at construction time."""
        registry = StubRegistry()
        # Transport is validated in __init__ so the error surfaces immediately.
        with pytest.raises(ValueError, match="Unknown transport"):
            MCPServer(registry, transport="unknown")

    def test_run_builds_app_with_executor(self) -> None:
        """_run builds the delegated APCoreMCP from the given backend."""
        executor = StubExecutor()
        server = MCPServer(executor, transport="stdio")
        ctx, mock_mcp = _patch_serve_coro(server)
        with ctx:
            server._run()
        # _build_app is the single assembly choke point; it was invoked once.
        assert server._stopped.is_set()
        mock_mcp._build_serve_coro.assert_called_once()

    def test_run_forwards_capabilities_to_apcore_mcp(self) -> None:
        """_build_app forwards the full capability set to APCoreMCP."""
        registry = StubRegistry()
        sentinel_handler = object()
        sentinel_store = object()
        sentinel_acl = object()
        server = MCPServer(
            registry,
            transport="stdio",
            validate_inputs=True,
            strategy="performance",
            output_format="csv",
            redact_output=False,
            trace=True,
            observability=True,
            dynamic=True,
            approval_handler=sentinel_handler,
            approval_store=sentinel_store,
            acl=sentinel_acl,
        )
        with patch("apcore_mcp.apcore_mcp.APCoreMCP") as mock_cls:
            mock_cls.return_value._build_serve_coro.return_value = lambda: _done()
            server._build_app()
        kwargs = mock_cls.call_args.kwargs
        assert kwargs["validate_inputs"] is True
        assert kwargs["strategy"] == "performance"
        assert kwargs["output_format"] == "csv"
        assert kwargs["redact_output"] is False
        assert kwargs["trace"] is True
        assert kwargs["observability"] is True
        assert kwargs["dynamic"] is True
        assert kwargs["approval_handler"] is sentinel_handler
        assert kwargs["approval_store"] is sentinel_store
        assert kwargs["acl"] is sentinel_acl

    def test_run_closes_loop_on_error(self) -> None:
        """_run closes the event loop and captures errors raised by the coroutine."""
        server = MCPServer(StubRegistry(), transport="stdio")
        ctx, _mock_mcp = _patch_serve_coro(server, side_effect=RuntimeError("Transport failed"))
        with ctx:
            # _run() does not propagate — it stores the error and signals _started.
            server._run()
        assert server._start_error is not None
        assert "Transport failed" in str(server._start_error)
        assert server._stopped.is_set()


async def _done() -> None:
    """No-op coroutine used as a serve-coro stand-in in unit tests."""
    return None
