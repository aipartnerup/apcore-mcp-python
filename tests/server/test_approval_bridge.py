"""Tests for ApprovalBridge meta-tool (Phase B approval polling)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from apcore_mcp.adapters.approval import StorageBackedApprovalHandler
from apcore_mcp.approval_store import InMemoryApprovalStore
from apcore_mcp.server.approval_bridge import APPROVAL_META_TOOL_NAMES, ApprovalBridge

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bridge() -> tuple[ApprovalBridge, StorageBackedApprovalHandler, InMemoryApprovalStore]:
    store = InMemoryApprovalStore()
    handler = StorageBackedApprovalHandler(store)
    bridge = ApprovalBridge(handler)
    return bridge, handler, store


# ---------------------------------------------------------------------------
# is_meta_tool
# ---------------------------------------------------------------------------


def test_is_meta_tool_returns_true_for_check() -> None:
    assert ApprovalBridge.is_meta_tool("__apcore_approval_check") is True


def test_is_meta_tool_returns_false_for_others() -> None:
    assert ApprovalBridge.is_meta_tool("__apcore_task_status") is False
    assert ApprovalBridge.is_meta_tool("my_module") is False
    assert ApprovalBridge.is_meta_tool("") is False


def test_approval_meta_tool_names_constant() -> None:
    assert "__apcore_approval_check" in APPROVAL_META_TOOL_NAMES


# ---------------------------------------------------------------------------
# build_meta_tools schema
# ---------------------------------------------------------------------------


def test_build_meta_tools_returns_one_tool() -> None:
    bridge, _, _ = _make_bridge()
    tools = bridge.build_meta_tools()
    assert len(tools) == 1
    tool = tools[0]
    assert tool.name == "__apcore_approval_check"


def test_build_meta_tools_schema_correct() -> None:
    bridge, _, _ = _make_bridge()
    tool = bridge.build_meta_tools()[0]
    schema = tool.inputSchema
    assert schema["type"] == "object"
    assert "approval_id" in schema["properties"]
    assert schema["required"] == ["approval_id"]
    assert schema.get("additionalProperties") is False


def test_build_meta_tools_has_description() -> None:
    bridge, _, _ = _make_bridge()
    tool = bridge.build_meta_tools()[0]
    assert tool.description
    assert "approval_id" in tool.description.lower() or "approval" in tool.description.lower()


# ---------------------------------------------------------------------------
# handle_meta_tool: check pending
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_returns_pending() -> None:
    bridge, handler, store = _make_bridge()
    await store.save_pending("abc-123", "mod", {"x": 1})
    content, is_error, trace_id = await bridge.handle_meta_tool("__apcore_approval_check", {"approval_id": "abc-123"})
    assert is_error is False
    body = json.loads(content[0]["text"])
    assert body["status"] == "pending"
    assert body["approval_id"] == "abc-123"


@pytest.mark.asyncio
async def test_check_returns_approved() -> None:
    bridge, handler, store = _make_bridge()
    await store.save_pending("abc-456", "mod", {})
    await store.resolve("abc-456", approved=True)
    content, is_error, _ = await bridge.handle_meta_tool("__apcore_approval_check", {"approval_id": "abc-456"})
    assert is_error is False
    body = json.loads(content[0]["text"])
    assert body["status"] == "approved"
    assert body["approval_id"] == "abc-456"
    assert "reason" not in body


@pytest.mark.asyncio
async def test_check_returns_rejected_with_reason() -> None:
    bridge, handler, store = _make_bridge()
    await store.save_pending("abc-789", "mod", {})
    await store.resolve("abc-789", approved=False, reason="not today")
    content, is_error, _ = await bridge.handle_meta_tool("__apcore_approval_check", {"approval_id": "abc-789"})
    assert is_error is False
    body = json.loads(content[0]["text"])
    assert body["status"] == "rejected"
    assert body["reason"] == "not today"


@pytest.mark.asyncio
async def test_check_unknown_id_returns_rejected() -> None:
    bridge, handler, store = _make_bridge()
    content, is_error, _ = await bridge.handle_meta_tool("__apcore_approval_check", {"approval_id": "unknown-xyz"})
    # handler.check_approval returns rejected for unknown ids
    assert is_error is False
    body = json.loads(content[0]["text"])
    assert body["status"] == "rejected"


# ---------------------------------------------------------------------------
# handle_meta_tool: validation errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_missing_approval_id_is_error() -> None:
    bridge, _, _ = _make_bridge()
    content, is_error, _ = await bridge.handle_meta_tool("__apcore_approval_check", {})
    assert is_error is True


@pytest.mark.asyncio
async def test_check_empty_approval_id_is_error() -> None:
    bridge, _, _ = _make_bridge()
    content, is_error, _ = await bridge.handle_meta_tool("__apcore_approval_check", {"approval_id": ""})
    assert is_error is True


@pytest.mark.asyncio
async def test_check_unknown_meta_tool_name_is_error() -> None:
    bridge, _, _ = _make_bridge()
    content, is_error, _ = await bridge.handle_meta_tool("__apcore_approval_check_nonexistent", {"approval_id": "x"})
    assert is_error is True


# ---------------------------------------------------------------------------
# StorageBackedApprovalHandler: request_approval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_approval_returns_pending_with_id() -> None:
    store = InMemoryApprovalStore()
    handler = StorageBackedApprovalHandler(store)

    from apcore import Context
    from apcore.approval import ApprovalRequest
    from apcore.module import ModuleAnnotations

    ctx = Context.create(data={})
    request = ApprovalRequest(
        module_id="test_mod",
        arguments={"k": "v"},
        context=ctx,
        annotations=ModuleAnnotations(),
        description="needs approval",
    )
    result = await handler.request_approval(request)
    assert result.status == "pending"
    assert result.approval_id is not None
    # store should have the pending record
    record = await store.get_result(result.approval_id)
    assert record is not None
    assert record["status"] == "pending"


@pytest.mark.asyncio
async def test_request_approval_calls_notify_callback() -> None:
    store = InMemoryApprovalStore()
    notify = AsyncMock()
    handler = StorageBackedApprovalHandler(store, notify_callback=notify)

    from apcore import Context
    from apcore.approval import ApprovalRequest
    from apcore.module import ModuleAnnotations

    ctx = Context.create(data={})
    request = ApprovalRequest(
        module_id="notify_mod",
        arguments={},
        context=ctx,
        annotations=ModuleAnnotations(),
        description="needs approval",
    )
    result = await handler.request_approval(request)
    notify.assert_awaited_once()
    args = notify.call_args
    assert args[0][0] == result.approval_id


@pytest.mark.asyncio
async def test_request_approval_swallows_notify_exception() -> None:
    """notify_callback errors must not propagate."""
    store = InMemoryApprovalStore()

    async def bad_notify(*args: Any) -> None:
        raise RuntimeError("notify failed")

    handler = StorageBackedApprovalHandler(store, notify_callback=bad_notify)

    from apcore import Context
    from apcore.approval import ApprovalRequest
    from apcore.module import ModuleAnnotations

    ctx = Context.create(data={})
    request = ApprovalRequest(
        module_id="mod",
        arguments={},
        context=ctx,
        annotations=ModuleAnnotations(),
        description="x",
    )
    # Should not raise
    result = await handler.request_approval(request)
    assert result.status == "pending"


# ---------------------------------------------------------------------------
# APCoreMCP integration: approval_store param auto-wires handler
# ---------------------------------------------------------------------------


def test_approval_store_param_creates_handler() -> None:
    """Passing approval_store to APCoreMCP auto-creates StorageBackedApprovalHandler."""
    from unittest.mock import MagicMock

    store = InMemoryApprovalStore()

    mock_registry = MagicMock()
    mock_registry.list.return_value = []
    mock_executor = MagicMock()
    mock_executor.registry = mock_registry

    from apcore_mcp.apcore_mcp import APCoreMCP

    mcp = APCoreMCP(mock_executor, approval_store=store, async_tasks=False)
    assert mcp._approval_store is store
    assert isinstance(mcp._approval_handler, StorageBackedApprovalHandler)


def test_explicit_approval_handler_not_overridden_by_store() -> None:
    """Explicit approval_handler takes precedence over approval_store auto-wiring."""
    from unittest.mock import MagicMock

    store = InMemoryApprovalStore()
    explicit_handler = StorageBackedApprovalHandler(store)

    mock_registry = MagicMock()
    mock_registry.list.return_value = []
    mock_executor = MagicMock()
    mock_executor.registry = mock_registry

    from apcore_mcp.apcore_mcp import APCoreMCP

    mcp = APCoreMCP(
        mock_executor,
        approval_handler=explicit_handler,
        approval_store=store,
        async_tasks=False,
    )
    assert mcp._approval_handler is explicit_handler
