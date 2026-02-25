"""Starlette route handlers for the MCP Tool Explorer."""

from __future__ import annotations

import logging
from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from apcore_mcp.explorer.html import _EXPLORER_HTML

logger = logging.getLogger(__name__)


def _make_serializable(obj: Any) -> Any:
    """Convert Pydantic models and other non-JSON-serializable objects to dicts."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump(exclude_none=True)
    if hasattr(obj, "dict"):
        return obj.dict(exclude_none=True)
    return obj


def _tool_summary(tool: Any) -> dict[str, Any]:
    """Return a summary dict for a tool (used in the list endpoint)."""
    result: dict[str, Any] = {
        "name": tool.name,
        "description": tool.description or "",
    }
    annotations = _make_serializable(getattr(tool, "annotations", None))
    if annotations:
        result["annotations"] = annotations
    return result


def _tool_detail(tool: Any) -> dict[str, Any]:
    """Return a full detail dict for a tool (used in the detail endpoint)."""
    result: dict[str, Any] = {
        "name": tool.name,
        "description": tool.description or "",
        "inputSchema": _make_serializable(tool.inputSchema),
    }
    annotations = _make_serializable(getattr(tool, "annotations", None))
    if annotations:
        result["annotations"] = annotations
    return result


def build_explorer_routes(
    tools: list[Any],
    router: Any,
    *,
    allow_execute: bool = False,
) -> list[Route]:
    """Build Starlette routes for the MCP Tool Explorer.

    Args:
        tools: List of MCP Tool objects.
        router: An ExecutionRouter with async handle_call(name, arguments)
            returning (content, is_error, trace_id).
        allow_execute: Whether to allow tool execution via the call endpoint.

    Returns:
        List of Starlette Route objects to be mounted under the explorer prefix.
    """
    tools_by_name: dict[str, Any] = {t.name: t for t in tools}

    async def explorer_page(request: Request) -> HTMLResponse:
        return HTMLResponse(_EXPLORER_HTML)

    async def list_tools(request: Request) -> JSONResponse:
        return JSONResponse([_tool_summary(t) for t in tools])

    async def tool_detail(request: Request) -> Response:
        name = request.path_params["name"]
        tool = tools_by_name.get(name)
        if tool is None:
            return JSONResponse({"error": f"Tool not found: {name}"}, status_code=404)
        return JSONResponse(_tool_detail(tool))

    async def call_tool(request: Request) -> Response:
        if not allow_execute:
            return JSONResponse(
                {"error": "Tool execution is disabled. Launch with --allow-execute to enable."},
                status_code=403,
            )
        name = request.path_params["name"]
        tool = tools_by_name.get(name)
        if tool is None:
            return JSONResponse({"error": f"Tool not found: {name}"}, status_code=404)

        try:
            body = await request.json()
        except Exception:
            body = {}

        try:
            content, is_error, trace_id = await router.handle_call(name, body)
            # Return MCP-compliant CallToolResult format
            result: dict[str, Any] = {
                "content": content,
                "isError": is_error,
            }
            if trace_id:
                result["_meta"] = {"_trace_id": trace_id}
            return JSONResponse(result, status_code=500 if is_error else 200)
        except Exception as exc:
            logger.error("Explorer call_tool error for %s: %s", name, exc)
            return JSONResponse(
                {
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                },
                status_code=500,
            )

    return [
        Route("/", endpoint=explorer_page, methods=["GET"]),
        Route("/tools", endpoint=list_tools, methods=["GET"]),
        Route("/tools/{name:path}/call", endpoint=call_tool, methods=["POST"]),
        Route("/tools/{name:path}", endpoint=tool_detail, methods=["GET"]),
    ]
