"""TransportManager: stdio / Streamable HTTP / SSE transport lifecycle."""

from __future__ import annotations

import contextlib
import logging
import time as _time
import uuid
from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

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


@runtime_checkable
class MetricsExporter(Protocol):
    """Protocol for metrics collectors that can export Prometheus text format."""

    def export_prometheus(self) -> str: ...


class TransportManager:
    """Manages MCP server transport lifecycle."""

    def __init__(self, metrics_collector: MetricsExporter | None = None) -> None:
        self._start_time = _time.monotonic()
        self._metrics_collector: MetricsExporter | None = metrics_collector
        self._module_count: int = 0

    def set_module_count(self, count: int) -> None:
        """Set the number of registered modules for health reporting."""
        self._module_count = count

    def _build_health_response(self) -> dict[str, object]:
        """Build health check response."""
        return {
            "status": "ok",
            "uptime_seconds": round(_time.monotonic() - self._start_time, 1),
            "module_count": self._module_count,
        }

    def _build_metrics_response(self) -> Response:
        """Build Prometheus metrics response.

        Returns 200 with Prometheus text if a metrics collector is configured,
        or 404 if no collector is available.
        """
        if self._metrics_collector is None:
            return Response(status_code=404)
        body = self._metrics_collector.export_prometheus()
        return Response(
            content=body,
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @contextlib.asynccontextmanager
    async def build_streamable_http_app(
        self,
        server: Server,
        init_options: InitializationOptions,
        *,
        extra_routes: list[Route | Mount] | None = None,
        middleware: list[tuple[type, dict[str, Any]]] | None = None,
    ) -> AsyncIterator[Starlette]:
        """Build a Starlette ASGI app for Streamable HTTP transport.

        Returns a Starlette app that can be mounted into a larger application.
        Must be used as an async context manager — the MCP protocol session
        runs as a background task for the lifetime of the context.

        Example::

            async with transport_manager.build_streamable_http_app(
                server, init_options
            ) as mcp_app:
                # Mount mcp_app into a parent Starlette app, then run uvicorn.
                combined = Starlette(routes=[
                    Mount("/mcp", app=mcp_app),
                    Mount("/a2a", app=a2a_app),
                ])
                await uvicorn.Server(
                    uvicorn.Config(combined, host="0.0.0.0", port=8000)
                ).serve()
        """
        transport = StreamableHTTPServerTransport(
            mcp_session_id=uuid.uuid4().hex,
        )

        async with transport.connect() as (read_stream, write_stream):

            async def _health(request: Any) -> JSONResponse:
                return JSONResponse(self._build_health_response())

            async def _metrics(request: Any) -> Response:
                return self._build_metrics_response()

            routes: list[Route | Mount] = [
                Route("/health", endpoint=_health, methods=["GET"]),
                Route("/metrics", endpoint=_metrics, methods=["GET"]),
            ]
            if extra_routes:
                routes.extend(extra_routes)
            routes.append(Mount("/mcp", app=transport.handle_request))

            app: Any = Starlette(routes=routes)
            if middleware:
                for mw_cls, mw_kwargs in middleware:
                    app = mw_cls(app, **mw_kwargs)

            async with anyio.create_task_group() as tg:
                tg.start_soon(server.run, read_stream, write_stream, init_options)
                yield app
                tg.cancel_scope.cancel()

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
        extra_routes: list[Route | Mount] | None = None,
        middleware: list[tuple[type, dict[str, Any]]] | None = None,
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

            async def _metrics(request: Any) -> Response:
                return self._build_metrics_response()

            routes: list[Route | Mount] = [
                Route("/health", endpoint=_health, methods=["GET"]),
                Route("/metrics", endpoint=_metrics, methods=["GET"]),
            ]
            if extra_routes:
                routes.extend(extra_routes)
            routes.append(Mount("/mcp", app=transport.handle_request))

            app: Any = Starlette(routes=routes)
            if middleware:
                for mw_cls, mw_kwargs in middleware:
                    app = mw_cls(app, **mw_kwargs)

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
        extra_routes: list[Route | Mount] | None = None,
        middleware: list[tuple[type, dict[str, Any]]] | None = None,
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

        async def _metrics(request: Any) -> Response:
            return self._build_metrics_response()

        routes: list[Route | Mount] = [
            Route("/health", endpoint=_health, methods=["GET"]),
            Route("/metrics", endpoint=_metrics, methods=["GET"]),
        ]
        if extra_routes:
            routes.extend(extra_routes)
        routes.extend(
            [
                Route("/sse", endpoint=handle_sse, methods=["GET"]),
                Mount("/messages/", app=sse_transport.handle_post_message),
            ]
        )

        app: Any = Starlette(routes=routes)
        if middleware:
            for mw_cls, mw_kwargs in middleware:
                app = mw_cls(app, **mw_kwargs)

        config = uvicorn.Config(app, host=host, port=port, log_level="info")
        uv_server = uvicorn.Server(config)
        await uv_server.serve()

    def _validate_host_port(self, host: str, port: int) -> None:
        """Validate host and port parameters."""
        if not host:
            raise ValueError("Host must not be empty")
        if not isinstance(port, int) or port < 1 or port > 65535:
            raise ValueError(f"Port must be between 1 and 65535, got {port}")
