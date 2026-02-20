"""Tests for MCP extension helpers: report_progress and elicit."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from apcore_mcp.helpers import (
    MCP_ELICIT_KEY,
    MCP_PROGRESS_KEY,
    elicit,
    report_progress,
)


class _FakeContext:
    """Minimal context stub with a data dict."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data: dict[str, Any] = data if data is not None else {}


class _NoDataContext:
    """Context stub without a data attribute."""

    pass


class TestReportProgress:
    async def test_calls_callback_with_correct_args(self) -> None:
        callback = AsyncMock()
        ctx = _FakeContext({MCP_PROGRESS_KEY: callback})

        await report_progress(ctx, 5, total=10, message="halfway there")

        callback.assert_called_once_with(5, 10, "halfway there")

    async def test_calls_callback_with_only_progress(self) -> None:
        callback = AsyncMock()
        ctx = _FakeContext({MCP_PROGRESS_KEY: callback})

        await report_progress(ctx, 3)

        callback.assert_called_once_with(3, None, None)

    async def test_noops_when_callback_absent(self) -> None:
        ctx = _FakeContext({})

        # Should not raise
        await report_progress(ctx, 1, total=10, message="test")

    async def test_noops_when_context_has_no_data_attribute(self) -> None:
        ctx = _NoDataContext()

        # Should not raise
        await report_progress(ctx, 1, total=10, message="test")


class TestElicit:
    async def test_calls_callback_and_returns_result(self) -> None:
        result = {"action": "accept", "content": {"confirmed": True}}
        callback = AsyncMock(return_value=result)
        ctx = _FakeContext({MCP_ELICIT_KEY: callback})

        response = await elicit(ctx, "Continue?", requested_schema={"type": "object"})

        callback.assert_called_once_with("Continue?", {"type": "object"})
        assert response == result

    async def test_calls_callback_without_schema(self) -> None:
        result = {"action": "decline"}
        callback = AsyncMock(return_value=result)
        ctx = _FakeContext({MCP_ELICIT_KEY: callback})

        response = await elicit(ctx, "Are you sure?")

        callback.assert_called_once_with("Are you sure?", None)
        assert response == result

    async def test_returns_none_when_callback_absent(self) -> None:
        ctx = _FakeContext({})

        response = await elicit(ctx, "Hello?")

        assert response is None

    async def test_returns_none_when_context_has_no_data_attribute(self) -> None:
        ctx = _NoDataContext()

        response = await elicit(ctx, "Hello?")

        assert response is None
