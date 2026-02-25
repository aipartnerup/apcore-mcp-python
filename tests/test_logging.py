"""Tests for structured logging across apcore-mcp components."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import ModuleAnnotations, ModuleDescriptor

# ---------------------------------------------------------------------------
# Stub Registry / Executor (same pattern as test_api.py)
# ---------------------------------------------------------------------------


class StubRegistry:
    """Minimal Registry stub with list() and get_definition()."""

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
    """Minimal Executor stub with call_async() and registry attribute."""

    def __init__(self, registry: StubRegistry):
        self.registry = registry

    async def call_async(self, module_id: str, inputs: dict | None = None) -> dict:
        return {"ok": True}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_descriptors() -> list[ModuleDescriptor]:
    return [
        ModuleDescriptor(
            module_id="image.resize",
            description="Resize an image",
            input_schema={
                "type": "object",
                "properties": {
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                },
                "required": ["width", "height"],
            },
            output_schema={"type": "object"},
            tags=["image"],
            annotations=ModuleAnnotations(idempotent=True),
        ),
        ModuleDescriptor(
            module_id="text.echo",
            description="Echo text",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            output_schema={"type": "object"},
            tags=["text"],
        ),
    ]


@pytest.fixture
def registry(sample_descriptors) -> StubRegistry:
    return StubRegistry(sample_descriptors)


@pytest.fixture
def executor(registry) -> StubExecutor:
    return StubExecutor(registry)


# ===========================================================================
# Test 1: serve() logs startup message at INFO level
# ===========================================================================


class TestServeLogging:
    """Verify serve() emits the expected startup log."""

    def test_serve_logs_startup(self, registry, caplog):
        """serve() logs 'Starting MCP server' at INFO level with name, version, tool count, and transport."""
        with (
            patch("apcore_mcp.TransportManager") as mock_tm_cls,
            patch("apcore_mcp.MCPServerFactory") as mock_factory_cls,
            patch("apcore_mcp.ExecutionRouter"),
        ):
            mock_factory = mock_factory_cls.return_value
            mock_factory.create_server.return_value = MagicMock()
            mock_factory.build_tools.return_value = [MagicMock(), MagicMock()]
            mock_factory.build_init_options.return_value = MagicMock()

            mock_tm = mock_tm_cls.return_value
            mock_tm.run_stdio = AsyncMock()

            with caplog.at_level(logging.INFO, logger="apcore_mcp"):
                from apcore_mcp import serve

                serve(registry, transport="stdio", name="test-srv", version="2.0.0")

            assert "Starting MCP server" in caplog.text
            assert "test-srv" in caplog.text
            assert "2.0.0" in caplog.text
            assert "2 tools" in caplog.text
            assert "stdio" in caplog.text

            # Verify the log record level is INFO
            startup_records = [r for r in caplog.records if "Starting MCP server" in r.message]
            assert len(startup_records) == 1
            assert startup_records[0].levelno == logging.INFO


# ===========================================================================
# Test 2: to_openai_tools() logs conversion at DEBUG level
# ===========================================================================


class TestToOpenaiToolsLogging:
    """Verify to_openai_tools() emits the expected DEBUG log."""

    def test_to_openai_tools_logs_conversion(self, registry, caplog):
        """to_openai_tools() logs 'Converted N tools to OpenAI format' at DEBUG level."""
        with caplog.at_level(logging.DEBUG, logger="apcore_mcp"):
            from apcore_mcp import to_openai_tools

            tools = to_openai_tools(registry)

        assert "Converted" in caplog.text
        assert "tools to OpenAI format" in caplog.text
        assert str(len(tools)) in caplog.text

        # Verify the log record level is DEBUG
        conversion_records = [r for r in caplog.records if "Converted" in r.message and "OpenAI format" in r.message]
        assert len(conversion_records) == 1
        assert conversion_records[0].levelno == logging.DEBUG


# ===========================================================================
# Test 3: Logger namespace starts with "apcore_mcp"
# ===========================================================================


class TestLoggerNamespace:
    """Verify all loggers use the apcore_mcp namespace."""

    def test_init_logger_namespace(self):
        """apcore_mcp.__init__ logger uses 'apcore_mcp' namespace."""
        import apcore_mcp

        assert apcore_mcp.logger.name == "apcore_mcp"

    def test_router_logger_namespace(self):
        """router.py logger uses 'apcore_mcp.server.router' namespace."""
        from apcore_mcp.server import router

        assert router.logger.name == "apcore_mcp.server.router"

    def test_factory_logger_namespace(self):
        """factory.py logger uses 'apcore_mcp.server.factory' namespace."""
        from apcore_mcp.server import factory

        assert factory.logger.name == "apcore_mcp.server.factory"

    def test_transport_logger_namespace(self):
        """transport.py logger uses 'apcore_mcp.server.transport' namespace."""
        from apcore_mcp.server import transport

        assert transport.logger.name == "apcore_mcp.server.transport"

    def test_all_loggers_start_with_apcore_mcp(self):
        """All component loggers start with 'apcore_mcp'."""
        import apcore_mcp
        from apcore_mcp.server import factory, router, transport

        for mod_logger in [
            apcore_mcp.logger,
            router.logger,
            factory.logger,
            transport.logger,
        ]:
            assert mod_logger.name.startswith(
                "apcore_mcp"
            ), f"Logger {mod_logger.name!r} does not start with 'apcore_mcp'"


# ===========================================================================
# Test 4: Router logs tool call name at DEBUG level
# ===========================================================================


class TestRouterLogging:
    """Verify ExecutionRouter emits the expected DEBUG logs."""

    async def test_router_logs_tool_call_name(self, caplog):
        """Router logs 'Executing tool call: <tool_name>' at DEBUG level."""
        from apcore_mcp.server.router import ExecutionRouter

        mock_executor = MagicMock()
        mock_executor.call_async = AsyncMock(return_value={"ok": True})
        router = ExecutionRouter(mock_executor)

        with caplog.at_level(logging.DEBUG, logger="apcore_mcp.server.router"):
            await router.handle_call("image.resize", {"width": 100})

        tool_call_records = [r for r in caplog.records if "Executing tool call" in r.message]
        assert len(tool_call_records) == 1
        assert "image.resize" in tool_call_records[0].message
        assert tool_call_records[0].levelno == logging.DEBUG


# ===========================================================================
# Test 5: Router logs errors at ERROR level
# ===========================================================================


class TestRouterErrorLogging:
    """Verify ExecutionRouter logs errors at ERROR level."""

    async def test_router_logs_error(self, caplog):
        """Router logs 'handle_call error' at ERROR level when executor raises."""
        from apcore_mcp.server.router import ExecutionRouter

        mock_executor = MagicMock()
        mock_executor.call_async = AsyncMock(side_effect=RuntimeError("something went wrong"))
        router = ExecutionRouter(mock_executor)

        with caplog.at_level(logging.DEBUG, logger="apcore_mcp.server.router"):
            content, is_error, trace_id = await router.handle_call("bad.module", {})

        assert is_error is True
        error_records = [r for r in caplog.records if "handle_call error" in r.message]
        assert len(error_records) == 1
        assert "bad.module" in error_records[0].message
        assert error_records[0].levelno == logging.ERROR


# ===========================================================================
# Test 6: Transport logs startup info
# ===========================================================================


class TestTransportLogging:
    """Verify TransportManager emits the expected log messages."""

    async def test_stdio_logs_startup(self, caplog):
        """run_stdio logs 'Starting stdio transport' at INFO level."""
        from apcore_mcp.server.transport import TransportManager

        tm = TransportManager()
        mock_server = MagicMock()
        mock_server.run = AsyncMock()
        mock_init_options = MagicMock()

        with (
            caplog.at_level(logging.INFO, logger="apcore_mcp.server.transport"),
            patch("apcore_mcp.server.transport.stdio_server") as mock_stdio,
        ):
            # Make stdio_server an async context manager
            mock_read = MagicMock()
            mock_write = MagicMock()
            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=(mock_read, mock_write))
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_stdio.return_value = mock_ctx

            await tm.run_stdio(mock_server, mock_init_options)

        startup_records = [r for r in caplog.records if "Starting stdio transport" in r.message]
        assert len(startup_records) == 1
        assert startup_records[0].levelno == logging.INFO

    async def test_streamable_http_logs_startup(self, caplog):
        """run_streamable_http logs transport type, host, and port at INFO level."""
        from apcore_mcp.server.transport import TransportManager

        tm = TransportManager()
        mock_server = MagicMock()
        mock_server.run = AsyncMock()
        mock_init_options = MagicMock()

        with (
            caplog.at_level(logging.INFO, logger="apcore_mcp.server.transport"),
            patch("apcore_mcp.server.transport.StreamableHTTPServerTransport") as mock_transport_cls,
            patch("apcore_mcp.server.transport.uvicorn") as mock_uvicorn,
            patch("apcore_mcp.server.transport.anyio") as mock_anyio,
        ):
            mock_transport = mock_transport_cls.return_value
            mock_read = MagicMock()
            mock_write = MagicMock()
            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=(mock_read, mock_write))
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_transport.connect.return_value = mock_ctx
            mock_transport.handle_request = MagicMock()

            mock_uv_server = MagicMock()
            mock_uv_server.serve = AsyncMock()
            mock_uvicorn.Config.return_value = MagicMock()
            mock_uvicorn.Server.return_value = mock_uv_server

            # Make the task group a no-op that doesn't start tasks
            mock_tg = MagicMock()
            mock_tg.start_soon = MagicMock()
            mock_tg_ctx = MagicMock()
            mock_tg_ctx.__aenter__ = AsyncMock(return_value=mock_tg)
            mock_tg_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_anyio.create_task_group.return_value = mock_tg_ctx

            await tm.run_streamable_http(
                mock_server,
                mock_init_options,
                host="0.0.0.0",
                port=9000,
            )

        startup_records = [r for r in caplog.records if "Starting streamable-http transport" in r.message]
        assert len(startup_records) == 1
        assert "0.0.0.0" in startup_records[0].message
        assert "9000" in startup_records[0].message
        assert startup_records[0].levelno == logging.INFO

    async def test_sse_logs_deprecation_warning(self, caplog):
        """run_sse logs SSE deprecation at WARNING level."""
        from apcore_mcp.server.transport import TransportManager

        tm = TransportManager()
        mock_server = MagicMock()
        mock_server.run = AsyncMock()
        mock_init_options = MagicMock()

        with (
            caplog.at_level(logging.INFO, logger="apcore_mcp.server.transport"),
            patch("apcore_mcp.server.transport.SseServerTransport"),
            patch("apcore_mcp.server.transport.uvicorn") as mock_uvicorn,
        ):
            mock_uv_server = MagicMock()
            mock_uv_server.serve = AsyncMock()
            mock_uvicorn.Config.return_value = MagicMock()
            mock_uvicorn.Server.return_value = mock_uv_server

            await tm.run_sse(
                mock_server,
                mock_init_options,
                host="localhost",
                port=8080,
            )

        # Check for the INFO startup log
        startup_records = [r for r in caplog.records if "Starting sse transport" in r.message]
        assert len(startup_records) == 1
        assert "localhost" in startup_records[0].message
        assert "8080" in startup_records[0].message
        assert startup_records[0].levelno == logging.INFO

        # Check for the WARNING deprecation log
        deprecation_records = [r for r in caplog.records if "deprecated" in r.message.lower()]
        assert len(deprecation_records) == 1
        assert deprecation_records[0].levelno == logging.WARNING
