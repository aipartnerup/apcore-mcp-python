"""Tests for ElicitationApprovalHandler."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from apcore import Context
from apcore.approval import ApprovalRequest
from apcore.module import ModuleAnnotations

from apcore_mcp.adapters.approval import ElicitationApprovalHandler
from apcore_mcp.helpers import MCP_ELICIT_KEY

_DEFAULT_ANNOTATIONS = ModuleAnnotations(requires_approval=True)


class TestElicitationApprovalHandler:
    """Test suite for ElicitationApprovalHandler."""

    @pytest.fixture
    def handler(self) -> ElicitationApprovalHandler:
        return ElicitationApprovalHandler()

    def _make_request(
        self,
        context_data: dict[str, Any] | None = None,
        module_id: str = "test.module",
        description: str = "Test operation",
        arguments: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        ctx = Context.create(data=context_data or {})
        return ApprovalRequest(
            module_id=module_id,
            description=description,
            arguments=arguments or {},
            context=ctx,
            annotations=_DEFAULT_ANNOTATIONS,
        )

    async def test_request_approval_accept(self, handler: ElicitationApprovalHandler) -> None:
        """Elicit callback returning 'accept' -> ApprovalResult status 'approved'."""
        elicit_mock = AsyncMock(return_value={"action": "accept", "content": {}})
        request = self._make_request(context_data={MCP_ELICIT_KEY: elicit_mock})

        result = await handler.request_approval(request)

        assert result.status == "approved"
        assert result.reason is None
        elicit_mock.assert_called_once()

    async def test_request_approval_decline(self, handler: ElicitationApprovalHandler) -> None:
        """Elicit callback returning 'decline' -> ApprovalResult status 'rejected'."""
        elicit_mock = AsyncMock(return_value={"action": "decline", "content": None})
        request = self._make_request(context_data={MCP_ELICIT_KEY: elicit_mock})

        result = await handler.request_approval(request)

        assert result.status == "rejected"
        assert "decline" in result.reason

    async def test_request_approval_cancel(self, handler: ElicitationApprovalHandler) -> None:
        """Elicit callback returning 'cancel' -> ApprovalResult status 'rejected'."""
        elicit_mock = AsyncMock(return_value={"action": "cancel", "content": None})
        request = self._make_request(context_data={MCP_ELICIT_KEY: elicit_mock})

        result = await handler.request_approval(request)

        assert result.status == "rejected"
        assert "cancel" in result.reason

    async def test_request_approval_no_callback(self, handler: ElicitationApprovalHandler) -> None:
        """No elicit callback in context -> ApprovalResult status 'rejected'."""
        request = self._make_request(context_data={})

        result = await handler.request_approval(request)

        assert result.status == "rejected"
        assert "callback" in result.reason.lower()

    async def test_request_approval_elicit_returns_none(self, handler: ElicitationApprovalHandler) -> None:
        """Elicit callback returning None -> rejected."""
        elicit_mock = AsyncMock(return_value=None)
        request = self._make_request(context_data={MCP_ELICIT_KEY: elicit_mock})

        result = await handler.request_approval(request)

        assert result.status == "rejected"

    async def test_request_approval_elicit_raises(self, handler: ElicitationApprovalHandler) -> None:
        """Elicit callback raising exception -> rejected."""
        elicit_mock = AsyncMock(side_effect=RuntimeError("Connection lost"))
        request = self._make_request(context_data={MCP_ELICIT_KEY: elicit_mock})

        result = await handler.request_approval(request)

        assert result.status == "rejected"
        assert "failed" in result.reason.lower()

    async def test_check_approval_always_rejected(self, handler: ElicitationApprovalHandler) -> None:
        """check_approval always returns 'rejected' (Phase B not supported)."""
        result = await handler.check_approval("apr-123")

        assert result.status == "rejected"
        assert "Phase B" in result.reason

    async def test_approval_message_formatting(self, handler: ElicitationApprovalHandler) -> None:
        """Approval message includes module_id, description, and arguments."""
        received_messages: list[str] = []

        async def capture_elicit(message: str, schema: Any = None) -> dict[str, Any]:
            received_messages.append(message)
            return {"action": "accept", "content": {}}

        request = self._make_request(
            context_data={MCP_ELICIT_KEY: capture_elicit},
            module_id="file.delete",
            description="Delete a file permanently",
            arguments={"path": "/tmp/data.csv"},
        )

        await handler.request_approval(request)

        assert len(received_messages) == 1
        msg = received_messages[0]
        assert "file.delete" in msg
        assert "Delete a file permanently" in msg
        assert "/tmp/data.csv" in msg

    async def test_request_approval_sends_nonempty_schema(self, handler: ElicitationApprovalHandler) -> None:
        """Approval elicitation must carry a non-empty object schema; an empty {}
        breaks form-rendering clients (Cursor / Codex)."""
        received: list[Any] = []

        async def capture(message: str, schema: Any = None) -> dict[str, Any]:
            received.append(schema)
            return {"action": "accept", "content": {}}

        request = self._make_request(context_data={MCP_ELICIT_KEY: capture})
        await handler.request_approval(request)

        assert len(received) == 1
        schema = received[0]
        assert isinstance(schema, dict) and schema, "schema must be a non-empty dict"
        assert schema.get("type") == "object"
        assert "approve" in schema.get("properties", {})

    async def test_request_approval_accept_but_approve_false(self, handler: ElicitationApprovalHandler) -> None:
        """action=accept with content.approve=False -> rejected (explicit decline via form field)."""
        elicit_mock = AsyncMock(return_value={"action": "accept", "content": {"approve": False}})
        request = self._make_request(context_data={MCP_ELICIT_KEY: elicit_mock})

        result = await handler.request_approval(request)

        assert result.status == "rejected"

    async def test_request_approval_accept_with_approve_true(self, handler: ElicitationApprovalHandler) -> None:
        """action=accept with content.approve=True -> approved."""
        elicit_mock = AsyncMock(return_value={"action": "accept", "content": {"approve": True}})
        request = self._make_request(context_data={MCP_ELICIT_KEY: elicit_mock})

        result = await handler.request_approval(request)

        assert result.status == "approved"

    async def test_isinstance_check_passes(self) -> None:
        """ElicitationApprovalHandler passes isinstance check against ApprovalHandler protocol."""
        from apcore.approval import ApprovalHandler

        handler = ElicitationApprovalHandler()
        assert isinstance(handler, ApprovalHandler)
