"""Tests for the Async Task Bridge (F-043).

Covers: async-hint detection, submit envelope, status/cancel/list meta-tools,
progress fan-out, reserved-prefix rejection in factory.build_tool, and the
TaskLimitExceededError error path.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import pytest
from apcore.async_task import AsyncTaskManager, TaskStatus
from apcore.errors import TaskLimitExceededError

from apcore_mcp.server.async_task_bridge import META_TOOL_NAMES, AsyncTaskBridge
from apcore_mcp.server.factory import MCPServerFactory

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


@dataclass
class _Annotations:
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Descriptor:
    module_id: str
    description: str = "x"
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    annotations: _Annotations | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class _SlowExecutor:
    """Executor whose call_async awaits an event before completing."""

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.calls: list[tuple[str, dict[str, Any] | None, Any]] = []

    async def call_async(
        self,
        module_id: str,
        inputs: dict[str, Any] | None = None,
        context: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append((module_id, inputs, context))
        await self.release.wait()
        return {"done": True, "module": module_id}


# ---------------------------------------------------------------------------
# is_async_module detection
# ---------------------------------------------------------------------------


def test_is_async_module_metadata_bool_true() -> None:
    d = _Descriptor(module_id="m", metadata={"async": True})
    assert AsyncTaskBridge.is_async_module(d) is True


def test_is_async_module_annotations_extra_string() -> None:
    d = _Descriptor(module_id="m", annotations=_Annotations(extra={"mcp_async": "true"}))
    assert AsyncTaskBridge.is_async_module(d) is True


def test_is_async_module_not_hinted() -> None:
    d = _Descriptor(module_id="m", metadata={"async": False})
    assert AsyncTaskBridge.is_async_module(d) is False
    assert AsyncTaskBridge.is_async_module(None) is False


# ---------------------------------------------------------------------------
# Submit + status round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_returns_pending_envelope() -> None:
    executor = _SlowExecutor()
    mgr = AsyncTaskManager(executor)
    bridge = AsyncTaskBridge(mgr)

    envelope = await bridge.submit("m", {"x": 1}, None)
    assert envelope["status"] == TaskStatus.PENDING.value
    assert isinstance(envelope["task_id"], str)

    # Release and wait for completion.
    executor.release.set()
    await asyncio.sleep(0.01)
    info = mgr.get_status(envelope["task_id"])
    assert info is not None
    assert info.status in (TaskStatus.COMPLETED, TaskStatus.RUNNING)


@pytest.mark.asyncio
async def test_status_tool_returns_result_when_completed() -> None:
    executor = _SlowExecutor()
    executor.release.set()  # resolve immediately
    mgr = AsyncTaskManager(executor)
    bridge = AsyncTaskBridge(mgr)

    envelope = await bridge.submit("m", {}, None)
    task_id = envelope["task_id"]
    # Poll briefly for completion.
    for _ in range(20):
        if mgr.get_status(task_id).status == TaskStatus.COMPLETED:
            break
        await asyncio.sleep(0.005)

    content, is_error, _ = await bridge.handle_meta_tool("__apcore_task_status", {"task_id": task_id})
    assert is_error is False
    body = json.loads(content[0]["text"])
    assert body["status"] == "completed"
    assert body["result"] == {"done": True, "module": "m"}


@pytest.mark.asyncio
async def test_status_tool_unknown_task_id() -> None:
    mgr = AsyncTaskManager(_SlowExecutor())
    bridge = AsyncTaskBridge(mgr)
    content, is_error, _ = await bridge.handle_meta_tool("__apcore_task_status", {"task_id": "missing"})
    assert is_error is True
    body = json.loads(content[0]["text"])
    assert body["error"] == "ASYNC_TASK_NOT_FOUND"


# ---------------------------------------------------------------------------
# Cancel + list meta-tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_tool_cancels_running_task() -> None:
    executor = _SlowExecutor()
    mgr = AsyncTaskManager(executor)
    bridge = AsyncTaskBridge(mgr)

    envelope = await bridge.submit("m", {}, None)
    task_id = envelope["task_id"]

    content, is_error, _ = await bridge.handle_meta_tool("__apcore_task_cancel", {"task_id": task_id})
    assert is_error is False
    body = json.loads(content[0]["text"])
    assert body["task_id"] == task_id
    assert body["cancelled"] is True
    assert mgr.get_status(task_id).status == TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_list_tool_filters_by_status() -> None:
    executor = _SlowExecutor()
    executor.release.set()
    mgr = AsyncTaskManager(executor)
    bridge = AsyncTaskBridge(mgr)

    await bridge.submit("m1", {}, None)
    await bridge.submit("m2", {}, None)
    await asyncio.sleep(0.02)  # let tasks finish

    content, _, _ = await bridge.handle_meta_tool("__apcore_task_list", {"status": "completed"})
    body = json.loads(content[0]["text"])
    assert len(body["tasks"]) == 2
    assert all(t["status"] == "completed" for t in body["tasks"])


# ---------------------------------------------------------------------------
# Submit meta-tool rejects non-async modules
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_tool_rejects_non_async_module() -> None:
    executor = _SlowExecutor()
    bridge = AsyncTaskBridge(AsyncTaskManager(executor))
    sync_desc = _Descriptor(module_id="m", metadata={})

    content, is_error, _ = await bridge.handle_meta_tool(
        "__apcore_task_submit",
        {"module_id": "m", "arguments": {}},
        resolve_descriptor=lambda mid: sync_desc,
    )
    assert is_error is True
    body = json.loads(content[0]["text"])
    assert body["error"] == "ASYNC_MODULE_NOT_ASYNC"


# ---------------------------------------------------------------------------
# Capacity error surfaces via ErrorMapper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_limit_exceeded_mapped() -> None:
    executor = _SlowExecutor()
    mgr = AsyncTaskManager(executor, max_tasks=1)
    bridge = AsyncTaskBridge(mgr)

    await bridge.submit("m", {}, None)  # fills the slot
    async_desc = _Descriptor(module_id="m", metadata={"async": True})

    # Second submit via meta-tool should surface the mapped error.
    content, is_error, _ = await bridge.handle_meta_tool(
        "__apcore_task_submit",
        {"module_id": "m", "arguments": {}},
        resolve_descriptor=lambda mid: async_desc,
    )
    assert is_error is True
    # Error text contains the apcore message; we only assert it's non-empty.
    assert content[0]["text"]


# ---------------------------------------------------------------------------
# Progress fan-out
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_progress_fanout_binds_token_and_sink() -> None:
    executor = _SlowExecutor()
    mgr = AsyncTaskManager(executor)
    bridge = AsyncTaskBridge(mgr)

    received: list[dict[str, Any]] = []

    async def send(notification: dict[str, Any]) -> None:
        received.append(notification)

    from apcore import Context

    ctx = Context.create()
    await bridge._submit_with_progress("m", {}, ctx, progress_token="tok-1", send_notification=send)
    # Simulate the module invoking the installed progress callback.
    cb = ctx.data["_mcp_progress"]
    await cb(0.5, 1.0, "halfway")

    assert len(received) == 1
    assert received[0]["method"] == "notifications/progress"
    assert received[0]["params"]["progressToken"] == "tok-1"
    assert received[0]["params"]["progress"] == 0.5


# ---------------------------------------------------------------------------
# Reserved-prefix rejection in factory
# ---------------------------------------------------------------------------


def test_factory_rejects_reserved_prefix() -> None:
    factory = MCPServerFactory()
    desc = _Descriptor(module_id="__apcore_evil", description="x")

    with pytest.raises(ValueError) as excinfo:
        factory.build_tool(desc)
    assert "reserved prefix" in str(excinfo.value)


def test_meta_tool_names_match_spec() -> None:
    bridge = AsyncTaskBridge(AsyncTaskManager(_SlowExecutor()))
    names = [t.name for t in bridge.build_meta_tools()]
    assert set(names) == set(META_TOOL_NAMES)


@pytest.mark.asyncio
async def test_submit_raises_task_limit_directly() -> None:
    """AsyncTaskManager.submit raises TaskLimitExceededError (apcore 0.19)."""
    executor = _SlowExecutor()
    mgr = AsyncTaskManager(executor, max_tasks=1)
    bridge = AsyncTaskBridge(mgr)
    await bridge.submit("a", {}, None)
    with pytest.raises(TaskLimitExceededError):
        await bridge.submit("b", {}, None)


# ---------------------------------------------------------------------------
# __apcore_module_preview meta-tool (apcore 0.21 PROTOCOL_SPEC §5.6)
# ---------------------------------------------------------------------------


def test_preview_meta_tool_is_registered() -> None:
    bridge = AsyncTaskBridge(AsyncTaskManager(_SlowExecutor()))
    names = [t.name for t in bridge.build_meta_tools()]
    assert "__apcore_module_preview" in names


@pytest.mark.asyncio
async def test_preview_meta_tool_returns_predicted_changes() -> None:
    """Preview drives executor.validate() and surfaces predicted_changes."""
    from apcore import Change, Context, PreviewResult, Registry
    from apcore.executor import Executor
    from apcore.module import Module

    class _PreviewableModule(Module):
        input_schema = {"type": "object"}
        output_schema = {"type": "object"}

        def execute(self, inputs: Any, context: Context | None = None) -> Any:
            return {}

        def preview(self, inputs: Any, context: Context | None = None) -> PreviewResult:
            return PreviewResult(changes=[Change(action="create", target="row:42", summary="insert row")])

    registry = Registry()
    registry.register("demo.preview", _PreviewableModule())
    executor = Executor(registry)
    mgr = AsyncTaskManager(executor)
    bridge = AsyncTaskBridge(mgr)

    content, is_error, _ = await bridge.handle_meta_tool(
        "__apcore_module_preview",
        {"module_id": "demo.preview", "arguments": {}},
    )
    assert is_error is False
    payload = json.loads(content[0]["text"])
    assert payload["valid"] is True
    assert any(c["action"] == "create" for c in payload["predicted_changes"])
    assert any(c["check"] == "module_preview" for c in payload["checks"])


@pytest.mark.asyncio
async def test_preview_meta_tool_rejects_missing_module_id() -> None:
    bridge = AsyncTaskBridge(AsyncTaskManager(_SlowExecutor()))
    content, is_error, _ = await bridge.handle_meta_tool(
        "__apcore_module_preview",
        {"arguments": {}},
    )
    assert is_error is True
    # The error is mapped through ErrorMapper which sanitizes to "Internal
    # error occurred"; the important contract is that is_error is True.


@pytest.mark.asyncio
async def test_preview_meta_tool_preserves_arguments_null() -> None:
    """`arguments: null` must reach executor.validate() as None — the
    calling business decides whether null is acceptable. Pre-fix code
    silently coerced to `{}` via `args.get("arguments") or {}`."""

    captured: list[Any] = []

    class _Spy:
        def validate(self, module_id: str, inputs: Any, context: Any) -> Any:
            captured.append((module_id, inputs))

            class _Result:
                valid = True
                requires_approval = False
                checks: list[Any] = []
                predicted_changes: list[Any] = []

            return _Result()

    bridge = AsyncTaskBridge(
        AsyncTaskManager(_SlowExecutor()),
        executor=_Spy(),  # type: ignore[arg-type]
    )
    await bridge.handle_meta_tool(
        "__apcore_module_preview",
        {"module_id": "demo.x", "arguments": None},
    )
    assert captured == [
        ("demo.x", None)
    ], f"executor.validate must receive inputs=None when arguments is null; got {captured}"

    # Same for missing arguments — both paths collapse to None for
    # cross-SDK consistency with TS+Rust.
    captured.clear()
    await bridge.handle_meta_tool(
        "__apcore_module_preview",
        {"module_id": "demo.x"},
    )
    assert captured == [("demo.x", None)], f"missing arguments must also pass inputs=None; got {captured}"


@pytest.mark.asyncio
async def test_preview_meta_tool_rejects_non_object_arguments() -> None:
    """Structurally-wrong shapes (array, scalar) must be rejected."""
    bridge = AsyncTaskBridge(AsyncTaskManager(_SlowExecutor()))
    content, is_error, _ = await bridge.handle_meta_tool(
        "__apcore_module_preview",
        {"module_id": "demo.x", "arguments": [1, 2, 3]},
    )
    assert is_error is True


# ---------------------------------------------------------------------------
# CIRCUIT_BREAKER_OPEN error mapping (apcore 0.20 sync alignment A-001)
# ---------------------------------------------------------------------------


def test_error_mapper_handles_circuit_breaker_open() -> None:
    from apcore.errors import CircuitBreakerOpenError

    from apcore_mcp.adapters.errors import ErrorMapper

    err = CircuitBreakerOpenError("demo.module")
    mapped = ErrorMapper().to_mcp_error(err)
    assert mapped["errorType"] == "CIRCUIT_BREAKER_OPEN"
    assert mapped["retryable"] is True
    # The guidance comes from CircuitBreakerOpenError's default ai_guidance
    # (per-module recovery hint) which the mapper mirrors onto aiGuidance.
    assert "demo.module" in mapped["aiGuidance"]


# ---------------------------------------------------------------------------
# [A-D-AT-4] __apcore_task_submit rejects every non-object `arguments`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [[], "", 0, False, [1, 2], "text", 42, True])
async def test_submit_tool_rejects_non_object_arguments(bad: object) -> None:
    """Falsy non-objects used to be coerced to {} and submitted with empty inputs.

    TypeScript (async-task-bridge.ts:500) and Rust (async_task_bridge.rs:607)
    reject every non-object, non-null value; so does Python's own preview
    handler. Only the submit branch short-circuited with `or {}`.
    """
    executor = _SlowExecutor()
    bridge = AsyncTaskBridge(AsyncTaskManager(executor))
    async_desc = _Descriptor(module_id="m", metadata={"async": True})

    content, is_error, _ = await bridge.handle_meta_tool(
        "__apcore_task_submit",
        {"module_id": "m", "arguments": bad},
        resolve_descriptor=lambda mid: async_desc,
    )

    assert is_error is True
    assert content[0]["text"]
    # The error text is sanitised by ErrorMapper; what matters is that nothing
    # was submitted with silently-emptied inputs.
    assert bridge.manager.list_tasks() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, {}])
async def test_submit_tool_accepts_null_and_empty_arguments(value: object) -> None:
    """null and {} both mean "no inputs" and must still submit."""
    executor = _SlowExecutor()
    bridge = AsyncTaskBridge(AsyncTaskManager(executor))
    async_desc = _Descriptor(module_id="m", metadata={"async": True})

    args: dict[str, object] = {"module_id": "m"}
    if value is not None:
        args["arguments"] = value

    _content, is_error, _ = await bridge.handle_meta_tool(
        "__apcore_task_submit",
        args,
        resolve_descriptor=lambda mid: async_desc,
    )

    assert is_error is False
