"""Tests for builtin output formatters in ExecutionRouter."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from apcore_mcp.server.router import ExecutionRouter


@pytest.mark.asyncio
async def test_router_output_format_csv():
    # Mock executor. registry=None prevents the version_hint cascade
    # from invoking AsyncMock auto-generated `get_definition`, which would
    # otherwise emit a "coroutine never awaited" RuntimeWarning.
    executor = AsyncMock()
    executor.registry = None
    # List of dicts (tabular data)
    result = [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]
    executor.call_async.return_value = result

    # Router with csv format
    router = ExecutionRouter(executor, output_format="csv")

    content, is_error, _ = await router.handle_call("test_tool", {})

    assert not is_error
    text = content[0]["text"]
    # Check if it looks like CSV.
    # Header: name,age
    # Rows: Alice,30 Bob,25
    assert "name,age" in text
    assert "Alice,30" in text
    assert "Bob,25" in text
    assert text.endswith("\r\n")


@pytest.mark.asyncio
async def test_router_output_format_jsonl():
    # Mock executor. registry=None prevents the version_hint cascade
    # from invoking AsyncMock auto-generated `get_definition`, which would
    # otherwise emit a "coroutine never awaited" RuntimeWarning.
    executor = AsyncMock()
    executor.registry = None
    result = [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]
    executor.call_async.return_value = result

    # Router with jsonl format
    router = ExecutionRouter(executor, output_format="jsonl")

    content, is_error, _ = await router.handle_call("test_tool", {})

    assert not is_error
    text = content[0]["text"]
    lines = text.strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"name": "Alice", "age": 30}
    assert json.loads(lines[1]) == {"name": "Bob", "age": 25}


@pytest.mark.asyncio
async def test_router_output_format_fallback_non_tabular():
    # Mock executor. registry=None prevents the version_hint cascade
    # from invoking AsyncMock auto-generated `get_definition`, which would
    # otherwise emit a "coroutine never awaited" RuntimeWarning.
    executor = AsyncMock()
    executor.registry = None
    # Non-tabular result (just a string)
    result = "just a string"
    executor.call_async.return_value = result

    # Router with csv format
    router = ExecutionRouter(executor, output_format="csv")

    content, is_error, _ = await router.handle_call("test_tool", {})

    assert not is_error
    text = content[0]["text"]
    # Should fall back to JSON
    assert json.loads(text) == result


@pytest.mark.asyncio
async def test_router_output_format_single_dict_to_csv():
    # Mock executor. registry=None prevents the version_hint cascade
    # from invoking AsyncMock auto-generated `get_definition`, which would
    # otherwise emit a "coroutine never awaited" RuntimeWarning.
    executor = AsyncMock()
    executor.registry = None
    # Single dict (one row)
    result = {"name": "Alice", "age": 30}
    executor.call_async.return_value = result

    # Router with csv format
    router = ExecutionRouter(executor, output_format="csv")

    content, is_error, _ = await router.handle_call("test_tool", {})

    assert not is_error
    text = content[0]["text"]
    assert "name,age" in text
    assert "Alice,30" in text
