"""MCP Tool Inspector: browser-based UI for inspecting and testing MCP tools."""

from __future__ import annotations

from typing import Any

from starlette.routing import Mount

from apcore_mcp.inspector.routes import build_inspector_routes


def create_inspector_mount(
    tools: list[Any],
    router: Any,
    *,
    allow_execute: bool = False,
    inspector_prefix: str = "/inspector",
) -> Mount:
    """Create a Starlette Mount for the MCP Tool Inspector.

    Args:
        tools: List of MCP Tool objects to expose in the inspector.
        router: An ExecutionRouter for executing tool calls.
        allow_execute: Whether to allow tool execution from the inspector UI.
        inspector_prefix: URL prefix for the inspector (default: "/inspector").

    Returns:
        A Starlette Mount that can be included in the app's route list.
    """
    routes = build_inspector_routes(tools, router, allow_execute=allow_execute)
    return Mount(inspector_prefix, routes=routes)
