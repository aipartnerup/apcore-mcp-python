"""TransportManager: stdio / Streamable HTTP / SSE transport lifecycle."""

from __future__ import annotations

import logging
import time as _time
import uuid
from typing import Any

import anyio
import uvicorn
from mcp.server.lowlevel import Server
from mcp.server.models import InitializationOptions
from mcp.server.sse import SseServerTransport
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http import StreamableHTTPServerTransport
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

logger = logging.getLogger(__name__)


class TransportManager:
    """Manages MCP server transport lifecycle."""

    def __init__(self) -> None:
        self._start_time = _time.monotonic()

    def _build_health_response(self, module_count: int = 0) -> dict[str, object]:
        """Build health check response."""
        return {
            "status": "ok",
            "uptime_seconds": round(_time.monotonic() - self._start_time, 1),
            "module_count": module_count,
        }

    async def run_stdio(
        self,
        server: Server,
        init_options: InitializationOptions,
    ) -> None:
        """Start MCP server with stdio transport. Blocks until connection closes."""
        logger.info("Starting stdio transport")
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, init_options)

    async def run_streamable_http(
        self,
        server: Server,
        init_options: InitializationOptions,
        host: str = "127.0.0.1",
        port: int = 8000,
    ) -> None:
        """Start MCP server with Streamable HTTP transport."""
        self._validate_host_port(host, port)
        logger.info("Starting streamable-http transport on %s:%d", host, port)

        transport = StreamableHTTPServerTransport(
            mcp_session_id=uuid.uuid4().hex,
        )

        async with transport.connect() as (read_stream, write_stream):

            async def _health(request: Any) -> JSONResponse:
                return JSONResponse(self._build_health_response())

            app = Starlette(
                routes=[
                    Route("/health", endpoint=_health, methods=["GET"]),
                    Mount("/mcp", app=transport.handle_request),
                ],
            )

            config = uvicorn.Config(app, host=host, port=port, log_level="info")
            uv_server = uvicorn.Server(config)

            # Run both the MCP server and HTTP server concurrently
            async with anyio.create_task_group() as tg:
                tg.start_soon(server.run, read_stream, write_stream, init_options)
                tg.start_soon(uv_server.serve)

    async def run_sse(
        self,
        server: Server,
        init_options: InitializationOptions,
        host: str = "127.0.0.1",
        port: int = 8000,
    ) -> None:
        """Start MCP server with SSE transport (deprecated)."""
        self._validate_host_port(host, port)
        logger.info("Starting sse transport on %s:%d", host, port)
        logger.warning("SSE transport is deprecated. Use Streamable HTTP instead.")

        sse_transport = SseServerTransport("/messages/")

        async def handle_sse(request: Any) -> Response:
            async with sse_transport.connect_sse(request.scope, request.receive, request._send) as (
                read_stream,
                write_stream,
            ):
                await server.run(read_stream, write_stream, init_options)
            return Response()

        async def _health(request: Any) -> JSONResponse:
            return JSONResponse(self._build_health_response())

        app = Starlette(
            routes=[
                Route("/health", endpoint=_health, methods=["GET"]),
                Route("/sse", endpoint=handle_sse, methods=["GET"]),
                Mount("/messages/", app=sse_transport.handle_post_message),
            ],
        )

        config = uvicorn.Config(app, host=host, port=port, log_level="info")
        uv_server = uvicorn.Server(config)
        await uv_server.serve()

    def _validate_host_port(self, host: str, port: int) -> None:
        """Validate host and port parameters."""
        if not host:
            raise ValueError("Host must not be empty")
        if not isinstance(port, int) or port < 1 or port > 65535:
            raise ValueError(f"Port must be between 1 and 65535, got {port}")
