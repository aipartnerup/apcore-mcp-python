"""ElicitationApprovalHandler: bridges MCP elicitation to apcore's approval system."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from apcore.approval import ApprovalHandler, ApprovalRequest, ApprovalResult

from apcore_mcp.helpers import MCP_ELICIT_KEY

logger = logging.getLogger(__name__)


class ElicitationApprovalHandler(ApprovalHandler):
    """Bridges MCP elicitation to apcore's approval system.

    Uses the MCP elicit callback (injected into Context.data) to present
    approval requests to the human user via the MCP client.
    """

    async def request_approval(self, request: ApprovalRequest) -> ApprovalResult:
        """Request approval via MCP elicitation.

        Extracts the elicit callback from ``request.context.data``, builds
        an approval message, and maps the elicit response to an
        ``ApprovalResult``.

        Args:
            request: The approval request containing module_id, description,
                arguments, and context.

        Returns:
            ApprovalResult with status "approved" or "rejected".
        """
        # Extract elicit callback from context
        context = request.context
        data = getattr(context, "data", None) if context is not None else None
        if data is None:
            return ApprovalResult(status="rejected", reason="No context available for elicitation")

        elicit_callback = data.get(MCP_ELICIT_KEY)
        if elicit_callback is None:
            return ApprovalResult(status="rejected", reason="No elicitation callback available")

        # Build approval message
        message = (
            f"Approval required for tool: {request.module_id}\n\n"
            f"{request.description}\n\n"
            f"Arguments: {json.dumps(request.arguments)}"
        )

        try:
            result = await elicit_callback(message)
        except Exception:
            logger.debug("Elicitation approval request failed", exc_info=True)
            return ApprovalResult(status="rejected", reason="Elicitation request failed")

        if result is None:
            return ApprovalResult(status="rejected", reason="Elicitation returned no response")

        action = result.get("action") if isinstance(result, dict) else getattr(result, "action", None)

        if action == "accept":
            return ApprovalResult(status="approved")
        else:
            return ApprovalResult(status="rejected", reason=f"User action: {action}")

    async def check_approval(self, approval_id: str) -> ApprovalResult:
        """Check status of an existing approval.

        Phase B (async polling) is not supported via MCP elicitation since
        elicitation is stateless.

        Args:
            approval_id: The approval ID to check.

        Returns:
            Always returns rejected since Phase B is not supported.
        """
        return ApprovalResult(status="rejected", reason="Phase B not supported via MCP elicitation")


class StorageBackedApprovalHandler(ApprovalHandler):
    """Phase B approval handler backed by a pluggable ApprovalStore.

    ``request_approval()`` saves a pending record and returns
    ``ApprovalResult(status="pending", approval_id=...)`` causing apcore to raise
    ``ApprovalPendingError``, which the bridge maps to ``APPROVAL_PENDING`` in
    the MCP envelope. The agent receives ``{"errorType": "APPROVAL_PENDING",
    "details": {"approvalId": "..."}}`` and polls ``__apcore_approval_check``.

    ``check_approval()`` reads the store; called by apcore when the client
    retries with ``_meta.approvalId`` set.

    ``notify_callback`` (optional) lets callers fan out to Slack/email/etc.
    Signature: ``async (approval_id: str, module_id: str, arguments: dict) -> None``
    """

    def __init__(
        self,
        store: Any,
        *,
        notify_callback: Any | None = None,
    ) -> None:
        self._store = store
        self._notify = notify_callback

    async def request_approval(self, request: ApprovalRequest) -> ApprovalResult:
        approval_id = str(uuid.uuid4())
        module_id = getattr(request, "module_id", "unknown")
        arguments = getattr(request, "arguments", {}) or {}

        await self._store.save_pending(approval_id, module_id, arguments)

        if self._notify is not None:
            try:
                await self._notify(approval_id, module_id, arguments)
            except Exception:
                logger.warning("notify_callback raised for approval %s", approval_id, exc_info=True)

        return ApprovalResult(status="pending", approval_id=approval_id)

    async def check_approval(self, approval_id: str) -> ApprovalResult:
        record = await self._store.get_result(approval_id)
        if record is None:
            return ApprovalResult(status="rejected", reason="approval_id not found")
        status = record.get("status", "pending")
        reason = record.get("reason")
        if status == "approved":
            return ApprovalResult(status="approved")
        if status == "rejected":
            return ApprovalResult(status="rejected", reason=reason)
        return ApprovalResult(status="pending", approval_id=approval_id)
