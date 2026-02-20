"""ExecutionRouter: route MCP tool calls -> apcore Executor pipeline."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from apcore_mcp.adapters.errors import ErrorMapper

logger = logging.getLogger(__name__)


class ExecutionRouter:
    """Routes MCP tool calls through the apcore Executor pipeline.

    The router sits between the MCP server's call_tool handler and the
    apcore Executor.  It delegates to ``executor.call_async()`` and
    converts the result (or any exception) into a ``(content, is_error)``
    tuple that the MCP factory can pass directly to ``CallToolResult``.

    When the executor also exposes an async ``stream()`` method **and**
    the caller provides a ``progress_token`` + ``send_notification``
    callback via the *extra* dict, the router iterates the async
    generator and forwards each chunk as a ``notifications/progress``
    message, accumulating chunks via shallow merge.

    Args:
        executor: An apcore Executor instance (duck-typed -- must expose
            an async ``call_async(module_id, inputs)`` method and
            optionally an async ``stream(module_id, inputs)`` generator).
    """

    def __init__(self, executor: Any) -> None:
        self._executor = executor
        self._error_mapper = ErrorMapper()

    async def handle_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        extra: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, str]], bool]:
        """Execute a tool call through the Executor pipeline.

        Args:
            tool_name: The MCP tool name (already denormalized to apcore
                module ID by the caller, or passed through as-is).
            arguments: The tool call arguments dict.
            extra: Optional dict with ``progress_token`` and
                ``send_notification`` for streaming support.

        Returns:
            A ``(content, is_error)`` tuple where *content* is a list of
            ``TextContent``-compatible dicts and *is_error* signals
            whether the result represents an error.
        """
        logger.debug("Executing tool call: %s", tool_name)

        # Extract streaming helpers from extra
        progress_token: str | int | None = None
        send_notification: Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None = None
        if extra is not None:
            progress_token = extra.get("progress_token")
            send_notification = extra.get("send_notification")

        # Streaming path: executor has stream() AND we have both helpers
        can_stream = (
            hasattr(self._executor, "stream")
            and progress_token is not None
            and send_notification is not None
        )

        if can_stream:
            return await self._handle_stream(
                tool_name, arguments, progress_token, send_notification  # type: ignore[arg-type]
            )

        # Non-streaming path (unchanged)
        return await self._handle_call_async(tool_name, arguments)

    async def _handle_call_async(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> tuple[list[dict[str, str]], bool]:
        """Non-streaming execution via executor.call_async()."""
        try:
            result = await self._executor.call_async(tool_name, arguments)
            json_output = json.dumps(result, default=str)
            return ([{"type": "text", "text": json_output}], False)
        except Exception as error:
            logger.debug("handle_call error for %s: %s", tool_name, error)
            error_info = self._error_mapper.to_mcp_error(error)
            return ([{"type": "text", "text": error_info["message"]}], True)

    async def _handle_stream(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        progress_token: str | int,
        send_notification: Callable[[dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> tuple[list[dict[str, str]], bool]:
        """Streaming execution via executor.stream().

        Iterates the async generator, sends each chunk as a
        ``notifications/progress`` message, accumulates via shallow
        merge, and returns the final accumulated result.
        """
        accumulated: dict[str, Any] = {}
        chunk_index = 0

        try:
            async for chunk in self._executor.stream(tool_name, arguments):
                # Send progress notification for this chunk
                notification: dict[str, Any] = {
                    "method": "notifications/progress",
                    "params": {
                        "progressToken": progress_token,
                        "progress": chunk_index + 1,
                        "total": None,
                        "message": json.dumps(chunk, default=str),
                    },
                }
                await send_notification(notification)

                # Shallow merge into accumulated result
                accumulated = {**accumulated, **chunk}
                chunk_index += 1

            json_output = json.dumps(accumulated, default=str)
            return ([{"type": "text", "text": json_output}], False)
        except Exception as error:
            logger.debug("handle_call stream error for %s: %s", tool_name, error)
            error_info = self._error_mapper.to_mcp_error(error)
            return ([{"type": "text", "text": error_info["message"]}], True)
