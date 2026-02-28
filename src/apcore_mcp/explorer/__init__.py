"""MCP Tool Explorer: browser-based UI for inspecting and testing MCP tools."""

from __future__ import annotations

from typing import Any

from starlette.routing import Mount

from apcore_mcp.explorer.routes import build_explorer_routes


def create_explorer_mount(
    tools: list[Any],
    router: Any,
    *,
    allow_execute: bool = False,
    explorer_prefix: str = "/explorer",
    authenticator: Any | None = None,
) -> Mount:
    """Create a Starlette Mount for the MCP Tool Explorer.

    Args:
        tools: List of MCP Tool objects to expose in the explorer.
        router: An ExecutionRouter for executing tool calls.
        allow_execute: Whether to allow tool execution from the explorer UI.
        explorer_prefix: URL prefix for the explorer (default: "/explorer").
        authenticator: Optional Authenticator for per-request identity in tool execution.

    Returns:
        A Starlette Mount that can be included in the app's route list.
    """
    routes = build_explorer_routes(
        tools,
        router,
        allow_execute=allow_execute,
        authenticator=authenticator,
    )
    return Mount(explorer_prefix, routes=routes)
