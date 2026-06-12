"""ApprovalBridge: exposes __apcore_approval_check as an MCP meta-tool.

Symmetric with AsyncTaskBridge. Registered in MCPServerFactory.register_handlers()
alongside async_bridge.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp import types as mcp_types

from apcore_mcp.adapters.errors import ErrorMapper

logger = logging.getLogger(__name__)

__all__ = ["ApprovalBridge", "APPROVAL_META_TOOL_NAMES"]

APPROVAL_META_TOOL_NAMES = ("__apcore_approval_check",)


class ApprovalBridge:
    """Thin meta-tool layer over StorageBackedApprovalHandler.

    Exposes ``__apcore_approval_check`` so MCP clients can poll the status
    of a pending approval without blocking the connection. The full flow::

        1. Module call → APPROVAL_PENDING {approvalId: "abc"}
        2. Agent calls __apcore_approval_check(approval_id="abc")
           → {status: "pending"}
        3. External system resolves: store.resolve("abc", approved=True)
        4. Agent polls again → {status: "approved"}
        5. Agent retries module call with _meta.approvalId="abc"
           → apcore calls handler.check_approval("abc") → approved → executes
    """

    def __init__(self, handler: Any) -> None:
        self._handler = handler
        self._error_mapper = ErrorMapper()

    @staticmethod
    def is_meta_tool(name: str) -> bool:
        return name in APPROVAL_META_TOOL_NAMES

    def build_meta_tools(self) -> list[mcp_types.Tool]:
        return [
            mcp_types.Tool(
                name="__apcore_approval_check",
                description=(
                    "Poll the status of a pending approval request. "
                    "Returns {approval_id, status, reason}. "
                    "status is 'pending', 'approved', or 'rejected'. "
                    "When 'approved', retry the original tool call with "
                    "_meta.approvalId set to this approval_id."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "approval_id": {
                            "type": "string",
                            "description": "The approval_id from the APPROVAL_PENDING response",
                        }
                    },
                    "required": ["approval_id"],
                    "additionalProperties": False,
                },
            )
        ]

    async def handle_meta_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], bool, str | None]:
        """Dispatch a meta-tool call. Returns (content, is_error, trace_id)."""
        if name == "__apcore_approval_check":
            return await self._handle_check(arguments or {})
        return self._error_response(ValueError(f"Unknown approval meta-tool: {name}"))

    async def _handle_check(self, args: dict[str, Any]) -> tuple[list[dict[str, Any]], bool, str | None]:
        approval_id = args.get("approval_id")
        if not isinstance(approval_id, str) or not approval_id:
            return self._error_response(ValueError("approval_id is required"))
        try:
            result = await self._handler.check_approval(approval_id)
        except Exception as exc:
            logger.exception("approval check failed for %s", approval_id)
            return self._error_response(exc)
        status = getattr(result, "status", "pending")
        reason = getattr(result, "reason", None)
        payload: dict[str, Any] = {"approval_id": approval_id, "status": status}
        if reason is not None:
            payload["reason"] = reason
        return ([{"type": "text", "text": json.dumps(payload)}], False, None)

    def _error_response(self, exc: Exception) -> tuple[list[dict[str, Any]], bool, str | None]:
        info = self._error_mapper.to_mcp_error(exc)
        return ([{"type": "text", "text": info["message"]}], True, None)
