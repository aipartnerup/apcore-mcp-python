"""Tests for ExecutionRouter streaming path via extra parameter."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock

from apcore_mcp.helpers import MCP_PROGRESS_KEY
from apcore_mcp.server.router import ExecutionRouter, _deep_merge

# ---------------------------------------------------------------------------
# Stub executors
# ---------------------------------------------------------------------------


class StubExecutor:
    """Non-streaming executor (no stream() method)."""

    def __init__(self, results: dict[str, Any] | None = None) -> None:
        self._results: dict[str, Any] = results or {}
        self.calls: list[tuple[str, dict[str, Any], Any]] = []

    async def call_async(
        self,
        module_id: str,
        inputs: dict[str, Any],
        context: Any = None,
    ) -> Any:
        self.calls.append((module_id, inputs, context))
        return self._results.get(module_id, {})


class StreamingExecutor:
    """Executor that also exposes an async stream() method."""

    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self._chunks = chunks
        self.call_async_calls: list[tuple[str, dict[str, Any], Any]] = []
        self.stream_calls: list[tuple[str, dict[str, Any], Any]] = []

    async def call_async(
        self,
        module_id: str,
        inputs: dict[str, Any],
        context: Any = None,
    ) -> Any:
        self.call_async_calls.append((module_id, inputs, context))
        # Merge all chunks as the non-streaming fallback result
        accumulated: dict[str, Any] = {}
        for chunk in self._chunks:
            accumulated = {**accumulated, **chunk}
        return accumulated

    async def stream(
        self,
        module_id: str,
        inputs: dict[str, Any],
        context: Any = None,
    ) -> AsyncIterator[dict[str, Any]]:
        self.stream_calls.append((module_id, inputs, context))
        for chunk in self._chunks:
            yield chunk


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStreamingPath:
    """Tests for the streaming path in ExecutionRouter.handle_call()."""

    async def test_streams_chunks_via_send_notification(self) -> None:
        """When executor has stream(), progress_token and send_notification are
        provided, each chunk is sent as a notifications/progress message."""
        chunks = [
            {"step": "downloading"},
            {"progress": 50},
            {"step": "done", "progress": 100},
        ]
        executor = StreamingExecutor(chunks)
        router = ExecutionRouter(executor)

        send_notification = AsyncMock()
        extra: dict[str, Any] = {
            "progress_token": "tok-1",
            "send_notification": send_notification,
        }

        content, is_error, trace_id = await router.handle_call("my.tool", {"x": 1}, extra=extra)

        assert is_error is False
        # Executor.stream() should have been called, NOT call_async()
        assert len(executor.stream_calls) == 1
        assert executor.call_async_calls == []

        # Each chunk should trigger a send_notification call
        assert send_notification.call_count == len(chunks)
        for i, chunk in enumerate(chunks):
            call_args = send_notification.call_args_list[i]
            notification = call_args[0][0]  # first positional arg
            assert notification["params"]["progressToken"] == "tok-1"
            assert notification["params"]["message"] == json.dumps(chunk, default=str)

        # Accumulated result should be shallow merge of all chunks
        assert len(content) == 1
        parsed = json.loads(content[0]["text"])
        assert parsed == {"step": "done", "progress": 100}

        # trace_id returned as third tuple element
        assert trace_id is not None

    async def test_falls_back_to_call_async_when_no_stream_method(self) -> None:
        """When executor has no stream() method, falls back to call_async()
        even when progress_token is provided."""
        executor = StubExecutor(results={"my.tool": {"result": "ok"}})
        router = ExecutionRouter(executor)

        send_notification = AsyncMock()
        extra: dict[str, Any] = {
            "progress_token": "tok-2",
            "send_notification": send_notification,
        }

        content, is_error, trace_id = await router.handle_call("my.tool", {"x": 1}, extra=extra)

        assert is_error is False
        assert len(content) == 1
        assert len(executor.calls) == 1
        # send_notification should NOT have been called
        send_notification.assert_not_called()

        parsed = json.loads(content[0]["text"])
        assert parsed == {"result": "ok"}

    async def test_falls_back_to_call_async_when_no_progress_token(self) -> None:
        """When no progress_token is provided (extra is None), falls back to
        call_async() even if executor has stream()."""
        chunks = [{"a": 1}, {"b": 2}]
        executor = StreamingExecutor(chunks)
        router = ExecutionRouter(executor)

        # No extra -> no streaming
        content, is_error, trace_id = await router.handle_call("my.tool", {"x": 1})

        assert is_error is False
        # Should use call_async, not stream
        assert len(executor.call_async_calls) == 1
        assert executor.stream_calls == []

    async def test_falls_back_when_extra_missing_progress_token(self) -> None:
        """When extra dict exists but lacks progress_token, falls back to
        call_async()."""
        chunks = [{"a": 1}]
        executor = StreamingExecutor(chunks)
        router = ExecutionRouter(executor)

        extra: dict[str, Any] = {"send_notification": AsyncMock()}

        content, is_error, trace_id = await router.handle_call("my.tool", {}, extra=extra)

        assert is_error is False
        assert len(executor.call_async_calls) == 1
        assert executor.stream_calls == []

    async def test_falls_back_when_extra_missing_send_notification(self) -> None:
        """When extra dict exists but lacks send_notification, falls back to
        call_async()."""
        chunks = [{"a": 1}]
        executor = StreamingExecutor(chunks)
        router = ExecutionRouter(executor)

        extra: dict[str, Any] = {"progress_token": "tok-3"}

        content, is_error, trace_id = await router.handle_call("my.tool", {}, extra=extra)

        assert is_error is False
        assert len(executor.call_async_calls) == 1
        assert executor.stream_calls == []

    async def test_accumulates_disjoint_keys_correctly(self) -> None:
        """Disjoint keys across chunks are all present in the final result via
        shallow merge."""
        chunks = [
            {"alpha": 1},
            {"beta": 2},
            {"gamma": 3},
        ]
        executor = StreamingExecutor(chunks)
        router = ExecutionRouter(executor)

        send_notification = AsyncMock()
        extra: dict[str, Any] = {
            "progress_token": "tok-disjoint",
            "send_notification": send_notification,
        }

        content, is_error, trace_id = await router.handle_call("my.tool", {}, extra=extra)

        assert is_error is False
        assert len(content) == 1
        parsed = json.loads(content[0]["text"])
        assert parsed == {"alpha": 1, "beta": 2, "gamma": 3}

    async def test_later_chunks_overwrite_earlier_keys(self) -> None:
        """Shallow merge means later chunks overwrite earlier keys."""
        chunks = [
            {"status": "pending", "count": 0},
            {"status": "in_progress", "count": 5},
            {"status": "done", "count": 10},
        ]
        executor = StreamingExecutor(chunks)
        router = ExecutionRouter(executor)

        send_notification = AsyncMock()
        extra: dict[str, Any] = {
            "progress_token": "tok-overwrite",
            "send_notification": send_notification,
        }

        content, is_error, trace_id = await router.handle_call("my.tool", {}, extra=extra)

        assert is_error is False
        assert len(content) == 1
        parsed = json.loads(content[0]["text"])
        assert parsed == {"status": "done", "count": 10}

    async def test_stream_cancelled_error_is_retryable(self) -> None:
        """ExecutionCancelledError during streaming returns retryable error."""
        from apcore.cancel import ExecutionCancelledError

        class CancellingStreamExecutor:
            async def call_async(self, module_id: str, inputs: dict[str, Any], context: Any = None) -> Any:
                return {}

            async def stream(
                self, module_id: str, inputs: dict[str, Any], context: Any = None
            ) -> AsyncIterator[dict[str, Any]]:
                yield {"partial": "data"}
                raise ExecutionCancelledError("token cancelled mid-stream")

        executor = CancellingStreamExecutor()
        router = ExecutionRouter(executor)

        send_notification = AsyncMock()
        extra: dict[str, Any] = {
            "progress_token": "tok-cancel",
            "send_notification": send_notification,
        }

        content, is_error, _ = await router.handle_call("my.tool", {}, extra=extra)

        assert is_error is True
        text = content[0]["text"]
        assert "Execution was cancelled" in text
        assert "retryable" in text
        # Internal message must NOT leak
        assert "token cancelled" not in text

    async def test_stream_error_is_caught_and_returned(self) -> None:
        """If stream() raises, the error is caught and returned as is_error=True."""

        class FailingStreamExecutor:
            async def call_async(self, module_id: str, inputs: dict[str, Any], context: Any = None) -> Any:
                return {}

            async def stream(
                self, module_id: str, inputs: dict[str, Any], context: Any = None
            ) -> AsyncIterator[dict[str, Any]]:
                yield {"partial": "data"}
                raise RuntimeError("Stream exploded")

        executor = FailingStreamExecutor()
        router = ExecutionRouter(executor)

        send_notification = AsyncMock()
        extra: dict[str, Any] = {
            "progress_token": "tok-err",
            "send_notification": send_notification,
        }

        content, is_error, trace_id = await router.handle_call("my.tool", {}, extra=extra)

        assert is_error is True
        # The first chunk should still have been notified before the error
        assert send_notification.call_count == 1

    async def test_progress_notification_format(self) -> None:
        """Verify the exact format of progress notifications sent."""
        chunks = [{"key": "value"}]
        executor = StreamingExecutor(chunks)
        router = ExecutionRouter(executor)

        send_notification = AsyncMock()
        extra: dict[str, Any] = {
            "progress_token": "tok-format",
            "send_notification": send_notification,
        }

        await router.handle_call("my.tool", {}, extra=extra)

        notification = send_notification.call_args_list[0][0][0]
        assert notification["method"] == "notifications/progress"
        assert "params" in notification
        params = notification["params"]
        assert params["progressToken"] == "tok-format"
        assert isinstance(params["progress"], int | float)
        assert "total" in params
        assert "message" in params

    # ── New tests for context passing ────────────────────────────────────

    async def test_context_passed_to_stream(self) -> None:
        """Context with _mcp_progress is passed to executor.stream() as 3rd arg."""
        chunks = [{"done": True}]
        executor = StreamingExecutor(chunks)
        router = ExecutionRouter(executor)

        send_notification = AsyncMock()
        extra: dict[str, Any] = {
            "progress_token": "tok-ctx",
            "send_notification": send_notification,
        }

        await router.handle_call("my.tool", {}, extra=extra)

        assert len(executor.stream_calls) == 1
        _, _, context = executor.stream_calls[0]
        assert context is not None
        assert MCP_PROGRESS_KEY in context.data
        assert callable(context.data[MCP_PROGRESS_KEY])

    async def test_streaming_uses_deep_merge_for_nested(self) -> None:
        """Streaming accumulation deep-merges nested structures."""
        chunks = [
            {"data": {"x": 1, "y": 2}},
            {"data": {"y": 3, "z": 4}},
        ]
        executor = StreamingExecutor(chunks)
        router = ExecutionRouter(executor)

        send_notification = AsyncMock()
        extra: dict[str, Any] = {
            "progress_token": "tok-deep",
            "send_notification": send_notification,
        }

        content, is_error, _ = await router.handle_call("my.tool", {}, extra=extra)

        assert is_error is False
        parsed = json.loads(content[0]["text"])
        # Deep merge: data.x preserved, data.y overwritten, data.z added
        assert parsed == {"data": {"x": 1, "y": 3, "z": 4}}

    async def test_stream_backward_compat_legacy_executor(self) -> None:
        """Stream falls back when executor.stream() doesn't accept context arg."""

        class LegacyStreamExecutor:
            """Executor whose stream() doesn't accept context."""

            def __init__(self, chunks: list[dict[str, Any]]) -> None:
                self._chunks = chunks
                self.stream_calls: list[tuple[str, dict[str, Any]]] = []

            async def call_async(self, module_id: str, inputs: dict[str, Any]) -> Any:
                return {}

            async def stream(self, module_id: str, inputs: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
                self.stream_calls.append((module_id, inputs))
                for chunk in self._chunks:
                    yield chunk

        chunks = [{"result": "ok"}]
        executor = LegacyStreamExecutor(chunks)
        router = ExecutionRouter(executor)

        send_notification = AsyncMock()
        extra: dict[str, Any] = {
            "progress_token": "tok-legacy",
            "send_notification": send_notification,
        }

        content, is_error, trace_id = await router.handle_call("my.tool", {"x": 1}, extra=extra)

        assert is_error is False
        assert len(content) == 1
        parsed = json.loads(content[0]["text"])
        assert parsed == {"result": "ok"}
        assert len(executor.stream_calls) == 1


# ---------------------------------------------------------------------------
# Deep merge unit tests
# ---------------------------------------------------------------------------


class TestDeepMerge:
    """Tests for _deep_merge used in streaming chunk accumulation."""

    def test_flat_merge(self) -> None:
        assert _deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_overwrite_scalar(self) -> None:
        assert _deep_merge({"a": 1}, {"a": 2}) == {"a": 2}

    def test_nested_dict_merge(self) -> None:
        base = {"outer": {"a": 1, "b": 2}}
        overlay = {"outer": {"b": 3, "c": 4}}
        assert _deep_merge(base, overlay) == {"outer": {"a": 1, "b": 3, "c": 4}}

    def test_deeply_nested_merge(self) -> None:
        base = {"l1": {"l2": {"l3": "old", "keep": True}}}
        overlay = {"l1": {"l2": {"l3": "new"}}}
        assert _deep_merge(base, overlay) == {"l1": {"l2": {"l3": "new", "keep": True}}}

    def test_depth_cap_falls_back_to_shallow(self) -> None:
        base = {"nested": {"old_key": 1}}
        overlay = {"nested": {"new_key": 2}}
        result = _deep_merge(base, overlay, depth=32)
        assert result == {"nested": {"new_key": 2}}
        assert "old_key" not in result["nested"]

    def test_overlay_replaces_non_dict_with_dict(self) -> None:
        assert _deep_merge({"a": 1}, {"a": {"nested": True}}) == {"a": {"nested": True}}

    def test_overlay_replaces_dict_with_scalar(self) -> None:
        assert _deep_merge({"a": {"nested": True}}, {"a": 1}) == {"a": 1}

    def test_empty_base(self) -> None:
        assert _deep_merge({}, {"a": 1}) == {"a": 1}

    def test_empty_overlay(self) -> None:
        assert _deep_merge({"a": 1}, {}) == {"a": 1}

    def test_does_not_mutate_base(self) -> None:
        base = {"a": {"b": 1}}
        _deep_merge(base, {"a": {"c": 2}})
        assert base == {"a": {"b": 1}}
