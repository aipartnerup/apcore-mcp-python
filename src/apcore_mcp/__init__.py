"""apcore-mcp: Automatic MCP Server & OpenAI Tools Bridge for apcore."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from apcore_mcp._utils import resolve_executor, resolve_registry
from apcore_mcp.adapters.annotations import AnnotationMapper
from apcore_mcp.adapters.errors import ErrorMapper
from apcore_mcp.adapters.id_normalizer import ModuleIDNormalizer
from apcore_mcp.adapters.schema import SchemaConverter
from apcore_mcp.constants import ERROR_CODES, MODULE_ID_PATTERN, REGISTRY_EVENTS
from apcore_mcp.converters.openai import OpenAIConverter
from apcore_mcp.helpers import MCP_ELICIT_KEY, MCP_PROGRESS_KEY, elicit, report_progress
from apcore_mcp.server.factory import MCPServerFactory
from apcore_mcp.server.listener import RegistryListener
from apcore_mcp.server.router import ExecutionRouter
from apcore_mcp.server.server import MCPServer
from apcore_mcp.server.transport import MetricsExporter, TransportManager

__all__ = [
    # Public API
    "serve",
    "to_openai_tools",
    # Server building blocks
    "MetricsExporter",
    "MCPServer",
    "MCPServerFactory",
    "ExecutionRouter",
    "RegistryListener",
    "TransportManager",
    # Adapters
    "AnnotationMapper",
    "SchemaConverter",
    "ErrorMapper",
    "ModuleIDNormalizer",
    # Converters
    "OpenAIConverter",
    # Constants
    "REGISTRY_EVENTS",
    "ERROR_CODES",
    "MODULE_ID_PATTERN",
    # Extension helpers
    "report_progress",
    "elicit",
    "MCP_PROGRESS_KEY",
    "MCP_ELICIT_KEY",
]

__version__ = "0.4.0"

logger = logging.getLogger(__name__)


def serve(
    registry_or_executor: object,
    *,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8000,
    name: str = "apcore-mcp",
    version: str | None = None,
    on_startup: Callable[[], None] | None = None,
    on_shutdown: Callable[[], None] | None = None,
    tags: list[str] | None = None,
    prefix: str | None = None,
    log_level: str | None = None,
    dynamic: bool = False,
    validate_inputs: bool = False,
    metrics_collector: MetricsExporter | None = None,
) -> None:
    """Launch an MCP Server that exposes all apcore modules as tools.

    Args:
        registry_or_executor: An apcore Registry or Executor instance.
        transport: Transport type - "stdio", "streamable-http", or "sse".
        host: Host address for HTTP-based transports.
        port: Port number for HTTP-based transports.
        name: MCP server name.
        version: MCP server version. Defaults to apcore-mcp version.
        on_startup: Optional callback invoked after setup, before transport starts.
        on_shutdown: Optional callback invoked after the transport completes.
        tags: Filter modules by tags. Only modules with ALL specified tags are exposed.
        prefix: Filter modules by ID prefix.
        log_level: Set the log level for the apcore_mcp logger (e.g. "DEBUG", "INFO").
        dynamic: Reserved for future dynamic tool registration support.
        validate_inputs: Validate tool inputs against schemas before execution.
        metrics_collector: Optional MetricsCollector for Prometheus /metrics endpoint.
    """
    if not name:
        raise ValueError("name must not be empty")
    if len(name) > 255:
        raise ValueError(f"name exceeds maximum length of 255: {len(name)}")
    if tags is not None:
        for tag in tags:
            if not tag:
                raise ValueError("Tag values must not be empty")
    if prefix is not None and not prefix:
        raise ValueError("prefix must not be empty")
    if log_level is not None:
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if log_level.upper() not in valid_levels:
            raise ValueError(f"Unknown log level: {log_level!r}. Valid: {sorted(valid_levels)}")

    version = version or __version__

    if log_level is not None:
        logging.getLogger("apcore_mcp").setLevel(getattr(logging, log_level.upper()))

    registry = resolve_registry(registry_or_executor)
    executor = resolve_executor(registry_or_executor)

    # Build MCP server components
    factory = MCPServerFactory()
    server = factory.create_server(name=name, version=version)
    tools = factory.build_tools(registry, tags=tags, prefix=prefix)
    router = ExecutionRouter(executor, validate_inputs=validate_inputs)
    factory.register_handlers(server, tools, router)
    factory.register_resource_handlers(server, registry)
    init_options = factory.build_init_options(server, name=name, version=version)

    logger.info(
        "Starting MCP server '%s' v%s with %d tools via %s",
        name,
        version,
        len(tools),
        transport,
    )

    # Select and run transport
    transport_lower = transport.lower()
    transport_manager = TransportManager(metrics_collector=metrics_collector)
    transport_manager.set_module_count(len(tools))

    async def _run() -> None:
        if transport_lower == "stdio":
            await transport_manager.run_stdio(server, init_options)
        elif transport_lower == "streamable-http":
            await transport_manager.run_streamable_http(server, init_options, host=host, port=port)
        elif transport_lower == "sse":
            await transport_manager.run_sse(server, init_options, host=host, port=port)
        else:
            raise ValueError(f"Unknown transport: {transport!r}. Expected 'stdio', 'streamable-http', or 'sse'.")

    if on_startup is not None:
        on_startup()

    try:
        asyncio.run(_run())
    finally:
        if on_shutdown is not None:
            on_shutdown()


def to_openai_tools(
    registry_or_executor: object,
    *,
    embed_annotations: bool = False,
    strict: bool = False,
    tags: list[str] | None = None,
    prefix: str | None = None,
) -> list[dict]:
    """Export apcore Registry modules as OpenAI-compatible tool definitions.

    Args:
        registry_or_executor: An apcore Registry or Executor instance.
        embed_annotations: Embed annotation metadata in tool descriptions.
        strict: Add strict: true for OpenAI Structured Outputs.
        tags: Filter modules by tags.
        prefix: Filter modules by ID prefix.

    Returns:
        List of OpenAI tool definition dicts, directly usable with
        openai.chat.completions.create(tools=...).
    """
    registry = resolve_registry(registry_or_executor)
    converter = OpenAIConverter()
    tools = converter.convert_registry(
        registry,
        embed_annotations=embed_annotations,
        strict=strict,
        tags=tags,
        prefix=prefix,
    )
    logger.debug("Converted %d tools to OpenAI format", len(tools))
    return tools
