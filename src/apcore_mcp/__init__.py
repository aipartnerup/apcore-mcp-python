"""apcore-mcp: Automatic MCP Server & OpenAI Tools Bridge for apcore."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from apcore_mcp.converters.openai import OpenAIConverter
from apcore_mcp.server.factory import MCPServerFactory
from apcore_mcp.server.router import ExecutionRouter
from apcore_mcp.server.transport import TransportManager

__version__ = "0.1.0"

__all__ = ["serve", "to_openai_tools"]

logger = logging.getLogger(__name__)


def _resolve_registry(registry_or_executor: Any) -> Any:
    """Extract Registry from either a Registry or Executor instance."""
    if hasattr(registry_or_executor, "registry"):
        # It's an Executor — get its registry
        return registry_or_executor.registry
    # Assume it's a Registry
    return registry_or_executor


def _resolve_executor(registry_or_executor: Any) -> Any:
    """Get or create an Executor from either a Registry or Executor instance."""
    if hasattr(registry_or_executor, "call_async"):
        # Already an Executor
        return registry_or_executor
    # It's a Registry — create a default Executor
    from apcore.executor import Executor

    return Executor(registry_or_executor)


def serve(
    registry_or_executor: object,
    *,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8000,
    name: str = "apcore-mcp",
    version: str | None = None,
) -> None:
    """Launch an MCP Server that exposes all apcore modules as tools.

    Args:
        registry_or_executor: An apcore Registry or Executor instance.
        transport: Transport type - "stdio", "streamable-http", or "sse".
        host: Host address for HTTP-based transports.
        port: Port number for HTTP-based transports.
        name: MCP server name.
        version: MCP server version. Defaults to apcore-mcp version.
    """
    version = version or __version__

    registry = _resolve_registry(registry_or_executor)
    executor = _resolve_executor(registry_or_executor)

    # Build MCP server components
    factory = MCPServerFactory()
    server = factory.create_server(name=name, version=version)
    tools = factory.build_tools(registry)
    router = ExecutionRouter(executor)
    factory.register_handlers(server, tools, router)
    init_options = factory.build_init_options(server, name=name, version=version)

    logger.info(
        "Starting MCP server '%s' v%s with %d tools via %s",
        name,
        version,
        len(tools),
        transport,
    )

    # Select and run transport
    transport_manager = TransportManager()

    async def _run() -> None:
        if transport == "stdio":
            await transport_manager.run_stdio(server, init_options)
        elif transport == "streamable-http":
            await transport_manager.run_streamable_http(server, init_options, host=host, port=port)
        elif transport == "sse":
            await transport_manager.run_sse(server, init_options, host=host, port=port)
        else:
            raise ValueError(f"Unknown transport: {transport!r}. " "Expected 'stdio', 'streamable-http', or 'sse'.")

    asyncio.run(_run())


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
    registry = _resolve_registry(registry_or_executor)
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
