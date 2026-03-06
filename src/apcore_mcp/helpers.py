"""MCP extension helpers for apcore modules.

Provides report_progress() and elicit() that modules can call during execute().
Both read callbacks injected into context.data by the ExecutionRouter.
Gracefully no-op when callbacks are absent (non-MCP execution paths).
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

# Keys under context.data where MCP callbacks are stored.
MCP_PROGRESS_KEY = "_mcp_progress"
MCP_ELICIT_KEY = "_mcp_elicit"


class ElicitResult(TypedDict):
    """Typed result from an MCP elicitation request.

    Matches the TypeScript SDK's ``ElicitResult`` interface.
    """

    action: Literal["accept", "decline", "cancel"]
    content: NotRequired[dict[str, Any] | None]


async def report_progress(
    context: Any,
    progress: float,
    total: float | None = None,
    message: str | None = None,
) -> None:
    """Report execution progress to the MCP client.

    No-ops silently when called outside an MCP context (no callback injected)
    or when the context object has no ``data`` attribute.

    Args:
        context: Object with a ``data`` dict (apcore Context).
        progress: Current progress value.
        total: Optional total for percentage calculation.
        message: Optional human-readable progress message.
    """
    data = getattr(context, "data", None)
    if data is None:
        return
    callback = data.get(MCP_PROGRESS_KEY)
    if callback is not None:
        await callback(progress, total, message)


async def elicit(
    context: Any,
    message: str,
    requested_schema: dict[str, Any] | None = None,
) -> ElicitResult | None:
    """Ask the MCP client for user input via the elicitation protocol.

    Returns None when called outside an MCP context (no callback injected)
    or when the context object has no ``data`` attribute.

    Args:
        context: Object with a ``data`` dict (apcore Context).
        message: Message to display to the user.
        requested_schema: Optional JSON Schema describing the expected input.

    Returns:
        An ``ElicitResult`` with ``action`` ("accept"/"decline"/"cancel") and
        optional ``content``, or None if elicitation is unavailable.
    """
    data = getattr(context, "data", None)
    if data is None:
        return None
    callback = data.get(MCP_ELICIT_KEY)
    if callback is not None:
        result: ElicitResult | None = await callback(message, requested_schema)
        return result
    return None
