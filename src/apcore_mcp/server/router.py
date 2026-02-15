"""ExecutionRouter: route MCP tool calls -> apcore Executor pipeline."""

from __future__ import annotations

import json
import logging
from typing import Any

from apcore_mcp.adapters.errors import ErrorMapper

logger = logging.getLogger(__name__)


class ExecutionRouter:
    """Routes MCP tool calls through the apcore Executor pipeline.

    The router sits between the MCP server's call_tool handler and the
    apcore Executor.  It delegates to ``executor.call_async()`` and
    converts the result (or any exception) into a ``(content, is_error)``
    tuple that the MCP factory can pass directly to ``CallToolResult``.

    Args:
        executor: An apcore Executor instance (duck-typed -- must expose
            an async ``call_async(module_id, inputs)`` method).
    """

    def __init__(self, executor: Any) -> None:
        self._executor = executor
        self._error_mapper = ErrorMapper()

    async def handle_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> tuple[list[dict[str, str]], bool]:
        """Execute a tool call through the Executor pipeline.

        Args:
            tool_name: The MCP tool name (already denormalized to apcore
                module ID by the caller, or passed through as-is).
            arguments: The tool call arguments dict.

        Returns:
            A ``(content, is_error)`` tuple where *content* is a list of
            ``TextContent``-compatible dicts and *is_error* signals
            whether the result represents an error.
        """
        logger.debug("Executing tool call: %s", tool_name)
        try:
            result = await self._executor.call_async(tool_name, arguments)
            json_output = json.dumps(result, default=str)
            return ([{"type": "text", "text": json_output}], False)
        except Exception as error:
            logger.debug("handle_call error for %s: %s", tool_name, error)
            error_info = self._error_mapper.to_mcp_error(error)
            return ([{"type": "text", "text": error_info["message"]}], True)
